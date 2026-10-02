// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <atomic>
#include <cstddef>
#include <functional>
#include <memory>
#include <optional>
#include <shared_mutex>
#include <string>
#include <string_view>
#include <unordered_map>

#include "NameId.h"

namespace Data
{

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

        explicit Entry(std::string_view text)
            : content(text)
            , hasCaret(text.find('^') != std::string_view::npos)
        {}
    };
    struct IdHash
    {
        std::size_t operator()(const NameId& id) const;
    };

    /// The entry of  id, or null. Entries never change or go, so the pointer stays valid
    /// for the table's life without the lock.
    const Entry* get(const NameId& id) const;
    int depthOfContent(std::string_view content) const;
    std::string internSection(std::string_view section);
    std::string plainSection(std::string_view section) const;

    friend class ExpansionCursor;

    mutable std::shared_mutex _mutex;
    std::unordered_map<NameId, std::unique_ptr<Entry>, IdHash> _entries;
    std::atomic<std::size_t> _collisions {0};
    IdHook _hook;
};

}  // namespace Data
