// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <atomic>
#include <cstddef>
#include <functional>
#include <iosfwd>
#include <memory>
#include <optional>
#include <set>
#include <shared_mutex>
#include <streambuf>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "NameId.h"

namespace Base
{
class XMLAttributeFilter;
class XMLReader;
}  // namespace Base

namespace Data
{

class NameRemap;

/** The process-wide table of interned V2 name nodes (bounded names, ops#6).
 *
 * **Interned form.** A V2 name in full form embeds the full strings of its Linked and Connected
 * Names, escaped, and a split piece carries its whole history as earlier sections. In interned
 * (canonical) form:
 * - each Linked and Connected Name is written `~<ID>`, the ID of that name's own canonical form;
 * - a name of more than one section is written `~<ID>|<last section>`, where the ID is that of
 *   the prefix (the name before its last top-level `|`), itself in canonical form.
 *
 * So `_;Edge1^;_^;5^;FLT^;0^;E^;0^;IDX^,SRC^;_;7;FLT;0;F;0;GEN;_` becomes
 * `_;~<ID>;7;FLT;0;F;0;GEN;_`, with the entry `<ID>` → `Edge1;_;5;FLT;0;E;0;IDX,SRC;_`. A name
 * without embedded names and with one section is the same in both forms. An ID is
 * NameId::compute() of the node's canonical bytes, IdBits wide, written in base32hex (13
 * characters); `~` occurs in no V2 name and in no subname syntax.
 *
 * **Entries** map an ID to the canonical string of its node: an embedded name or a prefix.
 * Top-level names aren't entries. The table is append-only (an entry never changes or goes) and
 * guarded by a shared mutex, so it can be read from any thread.
 *
 * **Collisions.** Inserting a content whose ID is already taken by a different content is refused
 * and logged. The name embedding it then keeps that name inline in full V2 form (escaped as
 * today), which every reader of this class and the decoder accept. Such a name contains `^`;
 * a canonical string otherwise never does.
 *
 * **Expansion** (toPlain()) reproduces the full V2 string byte for byte: `~<ID>` in a list
 * becomes the escaped expansion of the entry, and a leading `~<ID>|` the prefix's expansion.
 */
class AppExport NameTable
{
public:
    /// The width of the IDs of interned names (the Phase 4 checkpoint, decision 2: 64 bits).
    static constexpr int IdBits = 64;
    /// The marker that starts an ID reference in a name.
    static constexpr char Marker = '~';
    /// The length of `~<ID>`.
    static constexpr std::size_t RefLength = 1 + NameId::base32Length(IdBits);

    /// What insertLoaded() did with an entry.
    enum class LoadResult
    {
        Inserted,   ///< new entry
        Identical,  ///< the ID was there with the same content: nothing changed
        Collision,  ///< the ID was there with another content: refused and logged
        WrongId,    ///< the ID isn't the content's ID: refused and logged
    };

    NameTable();
    ~NameTable();
    NameTable(const NameTable&) = delete;
    NameTable& operator=(const NameTable&) = delete;

    /// The process-wide table, which MappedName's decoder and the Python functions use.
    static NameTable& instance();

    /// The ID of \a content in this table's ID function (NameId::compute(), or the test hook).
    NameId idOf(std::string_view content) const;

    /** Inserts the canonical string \a content of a node.
     *
     * Returns its ID, also if the same content was there. Returns nothing, and logs, if the ID
     * is taken by another content (a collision). The caller must pass a canonical string:
     * toInterned() of a name, or an entry's content.
     */
    std::optional<NameId> intern(std::string_view content);

    /** Inserts the node of the name \a name (in any form), with its embedded names and prefixes.
     *
     * Returns the node's ID, or nothing if its own content collides. A name that is a bare
     * reference `~<ID>` returns that ID, known or not.
     */
    std::optional<NameId> internName(std::string_view name);

    /// Inserts an entry read from a file. The content isn't checked for canonical form.
    LoadResult insertLoaded(const NameId& id, std::string_view content);

    /// An entry: its ID and its canonical string.
    using SavedEntry = std::pair<NameId, std::string>;

    /** Writes a file's table (ops#6 T2): a line `NameTableStart v2 <count>`, then one line per
     * entry, its content in file form (NameRefCollector::appendFileForm()), in index order. An
     * entry's index is its position; the file has no IDs, its reader computes them. A content
     * holds no whitespace (setElementName() refuses it in a name).
     */
    static void writeEntries(std::ostream& stream, const std::vector<std::string>& contents);

    /// What readEntries() did.
    struct LoadSummary
    {
        std::size_t inserted = 0;
        std::size_t identical = 0;
        /// The entries refused as Collision (their ID holds other content here).
        std::vector<SavedEntry> refused;
        /// Lines that aren't an entry (empty, or with whitespace), and references to an index
        /// that isn't an earlier entry's.
        std::size_t malformed = 0;
    };

    /** Reads a table written by writeEntries() into this table. Each entry's references to
     * earlier entries (`~<index>`) are put back in hash form, then its ID is computed and it is
     * inserted (a collision is refused, as insertLoaded() does). A reference to an index that
     * isn't an earlier entry's becomes a reference to indexStandIn(), which no file holds.
     * \a entries, if given, gets every entry in hash form, refused ones too; \a byIndex the ID
     * of each position (indexStandIn() for a malformed line).
     */
    LoadSummary readEntries(std::istream& stream,
                            std::vector<SavedEntry>* entries = nullptr,
                            std::vector<NameId>* byIndex = nullptr);

    /// The ID a reference to the index \a index of a file stands for when the file has no
    /// such entry: the ID of no content (it holds a space).
    static NameId indexStandIn(std::size_t index);

    /** Inserts \a content under \a id whatever its real ID, if \a id is free; for tests that
     * force a collision with a file's entry. Returns false if \a id was taken.
     */
    bool insertForTesting(const NameId& id, std::string_view content);

    /// The canonical string of the node \a id, or nothing if it isn't in the table.
    std::optional<std::string> lookup(const NameId& id) const;

    /** The depth of the node \a id: 1 if its content refers to no other node, else one more
     * than the deepest node it refers to (its prefix and its embedded names). 0 if \a id, or a
     * node below it, isn't in the table.
     */
    int depth(const NameId& id) const;

    /// The full V2 form of the node \a id (unescaped, as a top-level name), or nothing if \a id
    /// isn't in the table.
    std::optional<std::string> expand(const NameId& id) const;

    /** The canonical (interned) form of the name \a name, which may be in full, interned or
     * mixed form. Inserts every node it embeds. Unknown `~<ID>` references are kept as they are.
     * A name that is a bare known reference `~<ID>` gives the entry's content.
     */
    std::string toInterned(std::string_view name);

    /** toInterned() without inserting anything: the canonical form of \a name if every node it
     * would refer to is in the table already, else nothing. A node whose ID is taken by other
     * content stays inline, as toInterned() leaves it, but isn't counted or logged as a
     * collision. A stored interned name refers only to nodes in the table, so a name this gives
     * nothing for can't be in an interned map (ops#97).
     */
    std::optional<std::string> toInternedIfKnown(std::string_view name) const;

    /** The full V2 form of the name \a name, in any form: every `~<ID>` the table knows is
     * expanded. Unknown references are kept as they are, so the name stays unresolved.
     */
    std::string toPlain(std::string_view name) const;

    /** Compares the full V2 forms of \a a and \a b byte by byte (as `std::memcmp`), without
     * building them: equal references at equal depth are skipped, so the cost follows the
     * history depth rather than the names' length. Returns <0, 0 or >0.
     */
    int compareExpanded(std::string_view a, std::string_view b) const;

    /// The number of entries.
    std::size_t size() const;
    /// The number of refused inserts (collisions and wrong IDs) so far.
    std::size_t collisions() const;

    /// Replaces the ID function, for tests that force collisions; an empty function restores
    /// NameId::compute(). The hook returns nothing to keep the real ID of a content.
    using IdHook = std::function<std::optional<NameId>(std::string_view content)>;
    void setIdHookForTesting(IdHook hook);

    /// The position of the last top-level `|` in \a name (the one before its last section), or
    /// npos for a name of one section.
    static std::size_t lastTopLevelBar(std::string_view name);

    /// `~<ID>`, or nothing if \a text isn't exactly a reference in valid form.
    static std::optional<NameId> parseRef(std::string_view text);
    static std::string makeRef(const NameId& id);

private:
    struct Entry
    {
        const std::string content;
        const bool hasCaret;  // an inline name (collision fallback) in it
        mutable std::atomic<int> depth {0};  // 0: not known yet
        mutable std::atomic<bool> collisionWarned {false};  // a collision on its ID was logged

        explicit Entry(std::string_view text)
            : content(text)
            , hasCaret(text.find('^') != std::string_view::npos)
        {}
    };
    struct IdHash
    {
        std::size_t operator()(const NameId& id) const;
    };

    /// The entry of \a id, or null. Entries never change or go, so the pointer stays valid
    /// for the table's life without the lock.
    const Entry* get(const NameId& id) const;
    int depthOfContent(std::string_view content) const;
    // With \a missing set, nothing is inserted: a node the table lacks sets *missing instead
    // (toInternedIfKnown()), and a collision isn't counted or logged
    std::optional<NameId> intern(std::string_view content, bool* missing);
    /// intern() of \a content whose ID \a id is known
    std::optional<NameId> intern(const NameId& id, std::string_view content, bool* missing);
    std::optional<NameId> internName(std::string_view name, bool* missing);
    std::string toInterned(std::string_view name, bool* missing);
    std::string internSection(std::string_view section, bool* missing);
    /// toPlain(), with the references \a remap rewrites resolved as its file has them
    std::string toPlain(std::string_view name, const NameRemap* remap) const;
    std::string plainSection(std::string_view section, const NameRemap* remap) const;
    /// The content \a id expands to: the file's for \a remap's inline IDs, nothing for its
    /// unknown ones, else this table's
    const std::string* contentOf(const NameId& id, const NameRemap* remap) const;

    friend class ExpansionCursor;
    friend class NameRefCollector;
    friend class NameRemap;

    mutable std::shared_mutex _mutex;
    std::unordered_map<NameId, std::unique_ptr<Entry>, IdHash> _entries;
    std::atomic<std::size_t> _collisions {0};
    IdHook _hook;
};

/** Gathers the entries a saved document needs (ops#6, Task 1 PR 7).
 *
 * A file that holds interned names must hold the entries they refer to, or another process
 * can't expand them. A collector takes the references (`~<ID>`) in whatever is added to it, and
 * entries() closes them over the table: an entry's content can refer to other entries.
 *
 * It reads the references from what a save writes, not from each kind of property: while a
 * collector is active on a thread (from its construction to its destruction),
 * ElementMap::beforeSave() adds every name of the maps it prepares for saving, and a
 * NameRefScanBuffer adds everything written through it. So a carrier of names needs no code of
 * its own here, as long as it writes into the scanned stream or is an element map.
 *
 * **File-local indices** (ops#6 T2). In a file's element maps and in its table, a reference is
 * written `~<index>`, decimal, the entry's position in the file's table; Document.xml keeps the
 * hash form. The entries are numbered in the order the references were first added, each after
 * the entries its content refers to (so an entry refers only to lower indices). A save binds
 * its collector to its writer once the maps have handed in their names (bind()); the maps are
 * written afterwards, by the writer's writeFiles(), so the collector lives on until then
 * (Document::saveToFile() makes it), and the maps find it through a FileFormScope.
 */
class AppExport NameRefCollector
{
public:
    NameRefCollector();
    ~NameRefCollector();
    NameRefCollector(const NameRefCollector&) = delete;
    NameRefCollector& operator=(const NameRefCollector&) = delete;

    /// The collector active on this thread (the latest one constructed), or null.
    static NameRefCollector* active();

    /// Adds every reference in \a text: a `~` followed by an ID in valid form.
    void add(std::string_view text);

    /// The distinct references added so far.
    const std::set<NameId>& refs() const
    {
        return _refs;
    }

    /** The entries of \a table reachable from the references added: those referenced, and
     * recursively the ones their contents refer to, in index order. The ones not numbered yet
     * are numbered now, after the others. References \a table doesn't know are left out and
     * counted in \a unknown.
     */
    const std::vector<NameTable::SavedEntry>& entries(const NameTable& table,
                                                      std::size_t* unknown = nullptr);

    /// The table as a file writes it (NameTable::writeEntries()): entries() with their
    /// references in file form.
    std::vector<std::string> fileEntries(const NameTable& table, std::size_t* unknown = nullptr);

    /// The index of \a id in the file, if it is numbered.
    std::optional<std::size_t> indexOf(const NameId& id) const;

    /** Appends \a text to \a out with every reference to a numbered entry written `~<index>`.
     * \a next is the character that follows \a text in the file's name (a name's data is
     * followed by its postfix), `\0` for none: a reference followed by a base32hex character
     * stays in hash form, so that the reader never takes the digits after an index for its own.
     */
    void appendFileForm(std::string& out, std::string_view text, char next = '\0') const;

    /// Numbers the entries of the references added so far (entries()), and makes this the
    /// collector of the maps that \a writer writes from now on (FileFormScope).
    void bind(const void* writer, const NameTable& table);
    bool isBound() const
    {
        return _writer != nullptr;
    }

    /** While it lives, the element maps written on this thread are written in file form if an
     * active collector is bound to \a writer (ComplexGeoData's Save() and SaveDocFile() make
     * one around ElementMap::save()). Maps written otherwise keep the hash form, which a
     * reader accepts too.
     */
    class AppExport FileFormScope
    {
    public:
        explicit FileFormScope(const void* writer);
        ~FileFormScope();
        FileFormScope(const FileFormScope&) = delete;
        FileFormScope& operator=(const FileFormScope&) = delete;

    private:
        const NameRefCollector* _previous;
    };

    /// The collector of the innermost FileFormScope on this thread, or null.
    static const NameRefCollector* fileForm();

private:
    void number(const NameId& root, const NameTable& table);

    std::set<NameId> _refs;
    std::vector<NameId> _order;  // _refs in the order they were first added
    std::size_t _numbered = 0;   // the references of _order numbered so far
    std::vector<NameTable::SavedEntry> _entries;  // by index
    std::unordered_map<NameId, std::size_t, NameTable::IdHash> _index;
    std::set<NameId> _unknown;
    const void* _writer = nullptr;
    NameRefCollector* _previous;
};

/** A stream buffer that passes everything on to another one and adds it to a collector,
 * references split between two writes included. Document::Save() puts one in front of the
 * stream it writes the document's XML to.
 */
class AppExport NameRefScanBuffer: public std::streambuf
{
public:
    NameRefScanBuffer(std::streambuf* target, NameRefCollector& collector);

protected:
    int_type overflow(int_type c) override;
    std::streamsize xsputn(const char* s, std::streamsize n) override;
    int sync() override;

private:
    void scan(std::string_view data);

    std::streambuf* _target;
    NameRefCollector& _collector;
    std::string _tail;  // the last bytes written, shorter than a reference
};

/** Rewrites the interned names a document load reads (ops#6, Task 1 PR 8).
 *
 * A file's references (`~<ID>`) mean what its own `NameTable` element says. In this process an
 * ID can mean something else, or nothing yet; the remap makes the names that the load reads
 * mean what the file meant, or nothing:
 * - **Inline IDs**: an entry the process table refused (its ID holds other content here: a
 *   collision, or the ID isn't the content's), and every entry of the file whose content
 *   refers to one. A reference to one is replaced by the file's name in full V2 form (inline,
 *   as for a collision while interning), so it can't resolve to this process's content.
 * - **Unknown IDs**: one the file's table lacks, or an entry of it that refers to one. A
 *   reference to one is made unresolvable (`~!<ID>`): it is missing, and stays missing even
 *   if another document brings an entry with that ID.
 * - **A newer naming format**: the file's table isn't read, every ID is unknown, and the maps
 *   holding references are dropped (the shape is recomputed).
 *
 * One is active on its thread from its construction to its destruction (Document::restore()
 * and Document::importObjects() make one). The load reads the file's table into it first,
 * before the objects, and then:
 * - every attribute of the document's XML passes through remapText(), if there are inline IDs
 *   (filterAttributes());
 * - link subnames, shadows and the solver's `from` pass through remapSubName();
 * - every element map name passes through remapMapName().
 * Unknown IDs are made unresolvable only in names, not in other text (expressions, labels,
 * spreadsheet cells), where a `~` and 13 characters can be the user's own.
 */
class AppExport NameRemap
{
public:
    /// What remapMapName() did.
    enum class MapName
    {
        Unchanged,
        Changed,
        Dropped,  ///< a newer naming format: the map must be dropped
    };

    /// Inserted after the marker of an unknown reference: `~!<ID>` is no reference.
    static constexpr char UnknownMark = '!';

    explicit NameRemap(NameTable& table = NameTable::instance());
    ~NameRemap();
    NameRemap(const NameRemap&) = delete;
    NameRemap& operator=(const NameRemap&) = delete;

    /// The remap active on this thread (the latest one constructed), or null.
    static NameRemap* active();

    /// Reads the file's entries into the table (NameTable::readEntries()) and works out which
    /// IDs are inline and which unknown. Once only: the indices of a file's maps refer to its own
    /// table, so a second table is refused (an error, and an empty summary).
    NameTable::LoadSummary load(std::istream& stream);
    /// True once a file's table was loaded or its naming format found newer: the remap belongs
    /// to that file, and another file's restore must make its own.
    bool holdsFile() const
    {
        return _loaded || _newerFormat;
    }
    /// The file's names are in a newer naming format than this build's.
    void setNewerFormat();
    bool isNewerFormat() const
    {
        return _newerFormat;
    }

    /// Makes every attribute that \a reader reads from now on pass through remapText(), while
    /// this remap lives. Does nothing if there are no inline IDs.
    void filterAttributes(const Base::XMLReader& reader);

    /// The number of inline IDs (collisions and the entries above them).
    std::size_t inlineCount() const
    {
        return _inlineIds.size();
    }
    /// True if \a id is unknown to the file (or refers to an ID unknown to it).
    bool isUnknown(const NameId& id) const;
    /// True if a reference to \a id is replaced by the file's name in full form.
    bool isInline(const NameId& id) const;

    /** Any text read from the file: each reference to an inline ID is replaced by the file's
     * name in full form, escaped as an embedded name unless it is a prefix (followed by `|`).
     * Returns true if \a text changed.
     */
    bool remapText(std::string& text) const;
    /// A link's subname, shadow or `from`: as remapText(), and every unknown reference made
    /// unresolvable. Returns true if \a text changed.
    bool remapSubName(std::string& text);
    /// A name of an element map: with an inline reference, the file's name in canonical form
    /// (colliding nodes inline); unknown references unresolvable. Indices are taken as by
    /// fromFileForm().
    MapName remapMapName(std::string& name);

    /** Text of the file's element maps (ops#6 T2): each reference `~<index>` (a `~` and up to
     * 12 decimal digits, followed by no other base32hex character, nor \a next at the end) is put
     * in hash form, the ID of the file's entry at that index, or of NameTable::indexStandIn() for
     * an index the table hasn't (unknown, then). References in hash form are kept. Returns true
     * if \a text changed.
     */
    bool fromFileForm(std::string& text, char next = '\0') const;

    /// The distinct unknown IDs met in names so far.
    std::size_t unknownCount() const
    {
        return _unknownSeen.size();
    }
    /// The map names refused so far (a newer naming format).
    std::size_t droppedCount() const
    {
        return _dropped;
    }

private:
    friend class NameTable;

    /// The file's full form of the node \a id (unknown references inside unresolvable).
    std::string inlineForm(const NameId& id) const;
    /// Marks every unknown reference in \a text unresolvable; true if any.
    bool markUnknown(std::string& text) const;
    /// Whether \a text refers to an inline or an unknown ID.
    void scan(std::string_view text, bool& hasInline, bool& hasUnknown) const;

    NameTable& _table;
    NameRemap* _previous;
    bool _newerFormat = false;
    bool _loaded = false;
    /// Every well-formed entry of the file, in hash form
    std::unordered_map<NameId, std::string, NameTable::IdHash> _file;
    /// The ID of each position of the file's table
    std::vector<NameId> _byIndex;
    std::set<NameId> _inlineIds;
    std::set<NameId> _incomplete;  // entries of the file that refer to an ID it lacks
    mutable std::set<NameId> _unknownSeen;
    std::size_t _dropped = 0;
    std::unique_ptr<Base::XMLAttributeFilter> _filter;
};

}  // namespace Data
