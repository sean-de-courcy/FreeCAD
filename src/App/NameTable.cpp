// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <charconv>
#include <cstring>
#include <istream>
#include <mutex>
#include <ostream>
#include <vector>

#include <Base/Console.h>
#include <Base/XMLAttributeFilter.h>

#include "ElementNamingUtils.h"
#include "NameTable.h"

FC_LOG_LEVEL_INIT("NameTable", true, 2);  // NOLINT

using namespace Data;

namespace
{

const char escapeChar = *SUB_SECTION_ESCAPE_CHAR;
const char nameDelimiter = *NAME_SECTION_DELIMINATOR;
const char fieldDelimiter = *SECTION_SUB_DELIMINATOR;
const char listDelimiter = *SUB_SECTION_LIST_DELIMINATOR;

bool isDelimiter(char c)
{
    return c == nameDelimiter || c == fieldDelimiter || c == listDelimiter;
}

/// True for the fields whose entries are names: Linked Names and Connected Names.
bool isNameListField(int field)
{
    return field == SECTION_LINKED_NAME_INDEX || field == SECTION_CONNECTED_ELEMENTS_INDEX;
}

/// The parts of \a text between top-level \a delimiter characters. A delimiter inside an
/// embedded name is escaped, so it has a `^` right before it; a top-level one never has (no
/// field ends in `^`).
std::vector<std::string_view> splitTopLevel(std::string_view text, char delimiter)
{
    std::vector<std::string_view> parts;
    std::size_t start = 0;
    for (std::size_t i = 0; i < text.size(); ++i) {
        if (text[i] == delimiter && (i == 0 || text[i - 1] != escapeChar)) {
            parts.push_back(text.substr(start, i - start));
            start = i + 1;
        }
    }
    parts.push_back(text.substr(start));
    return parts;
}

/// Calls \a visit with each part splitTopLevel() would list, without building the list.
template<typename Visit>
void forEachTopLevel(std::string_view text, char delimiter, Visit visit)
{
    std::size_t start = 0;
    for (std::size_t i = 0; i < text.size(); ++i) {
        if (text[i] == delimiter && (i == 0 || text[i - 1] != escapeChar)) {
            visit(text.substr(start, i - start));
            start = i + 1;
        }
    }
    visit(text.substr(start));
}

/// One level of unescaping, as the decoder does it: the first `^` of each run goes.
std::string unescapeOnce(std::string_view text)
{
    std::string result;
    result.reserve(text.size());
    bool afterCaret = false;
    for (char c : text) {
        if (c == escapeChar && !afterCaret) {
            afterCaret = true;
            continue;
        }
        afterCaret = c == escapeChar;
        result += c;
    }
    return result;
}

/// One level of escaping, as MappedName::escapeString() does it: a `^` before each delimiter.
std::string escapeOnce(std::string_view text)
{
    std::string result;
    result.reserve(text.size() + text.size() / 4);
    for (char c : text) {
        if (isDelimiter(c)) {
            result += escapeChar;
        }
        result += c;
    }
    return result;
}

void join(std::string& out, const std::vector<std::string>& parts, char delimiter)
{
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i != 0) {
            out += delimiter;
        }
        out += parts[i];
    }
}

/// The valid references in \a text, in order.
std::vector<NameId> refsIn(std::string_view text)
{
    std::vector<NameId> refs;
    for (std::size_t pos = text.find(NameTable::Marker);
         pos != std::string_view::npos && pos + NameTable::RefLength <= text.size();
         pos = text.find(NameTable::Marker, pos + 1)) {
        if (auto id = NameTable::parseRef(text.substr(pos, NameTable::RefLength))) {
            refs.push_back(*id);
        }
    }
    return refs;
}

bool isBase32Digit(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'v');
}

/// The end of the run of base32hex characters that starts at \a pos.
std::size_t base32RunEnd(std::string_view text, std::size_t pos)
{
    while (pos < text.size() && isBase32Digit(text[pos])) {
        ++pos;
    }
    return pos;
}

/** Puts the references `~<index>` of a file's text in hash form (NameRemap::fromFileForm()):
 * \a byIndex[i] for an index below \a limit, else NameTable::indexStandIn(). Counts those in
 * \a bad. Returns true if \a text changed.
 */
bool indicesToRefs(std::string& text,
                   const std::vector<NameId>& byIndex,
                   std::size_t limit,
                   char next,
                   std::size_t* bad = nullptr)
{
    // An index has at most 12 digits: a run of 13 is an ID (NameTable::RefLength - 1)
    constexpr std::size_t maxDigits = NameTable::RefLength - 2;
    std::size_t pos = text.find(NameTable::Marker);
    if (pos == std::string::npos) {
        return false;
    }
    std::string out;
    std::size_t done = 0;
    for (; pos != std::string::npos; pos = text.find(NameTable::Marker, pos + 1)) {
        std::size_t end = base32RunEnd(text, pos + 1);
        std::size_t digits = end - pos - 1;
        if (digits == 0 || digits > maxDigits || (end == text.size() && isBase32Digit(next))) {
            continue;
        }
        std::size_t index = 0;
        bool decimal = true;
        for (std::size_t i = pos + 1; i < end; ++i) {
            if (text[i] < '0' || text[i] > '9') {
                decimal = false;
                break;
            }
            index = index * 10 + static_cast<std::size_t>(text[i] - '0');
        }
        if (!decimal) {
            continue;
        }
        if (out.empty()) {
            out.reserve(text.size() + 4 * NameTable::RefLength);
        }
        out.append(text, done, pos - done);
        if (index < limit && index < byIndex.size()) {
            out += NameTable::makeRef(byIndex[index]);
        }
        else {
            out += NameTable::makeRef(NameTable::indexStandIn(index));
            if (bad) {
                ++*bad;
            }
        }
        done = end;
        pos = end - 1;
    }
    if (done == 0) {
        return false;
    }
    out.append(text, done, std::string::npos);
    text = std::move(out);
    return true;
}

}  // namespace

std::size_t NameTable::IdHash::operator()(const NameId& id) const
{
    std::size_t value = 0;
    std::memcpy(&value, id.bytes().data(), std::min(sizeof(value), id.bytes().size()));
    return value;
}

NameTable::NameTable() = default;
NameTable::~NameTable() = default;

NameTable& NameTable::instance()
{
    static NameTable table;
    return table;
}

std::size_t NameTable::lastTopLevelBar(std::string_view name)
{
    for (std::size_t i = name.size(); i-- > 0;) {
        if (name[i] == nameDelimiter && (i == 0 || name[i - 1] != escapeChar)) {
            return i;
        }
    }
    return std::string_view::npos;
}

std::optional<NameId> NameTable::parseRef(std::string_view text)
{
    if (text.size() != RefLength || text.front() != Marker) {
        return std::nullopt;
    }
    return NameId::fromBase32(text.substr(1));
}

std::string NameTable::makeRef(const NameId& id)
{
    std::string ref(1, Marker);
    ref += id.toBase32();
    return ref;
}

NameId NameTable::idOf(std::string_view content) const
{
    if (_hook) {
        if (auto id = _hook(content)) {
            return *id;
        }
    }
    return NameId::compute(content, IdBits);
}

void NameTable::setIdHookForTesting(IdHook hook)
{
    _hook = std::move(hook);
}

const NameTable::Entry* NameTable::get(const NameId& id) const
{
    std::shared_lock lock(_mutex);
    auto it = _entries.find(id);
    return it == _entries.end() ? nullptr : it->second.get();
}

std::size_t NameTable::size() const
{
    std::shared_lock lock(_mutex);
    return _entries.size();
}

std::size_t NameTable::collisions() const
{
    return _collisions;
}

std::optional<std::string> NameTable::lookup(const NameId& id) const
{
    if (const Entry* entry = get(id)) {
        return entry->content;
    }
    return std::nullopt;
}

std::optional<NameId> NameTable::intern(std::string_view content)
{
    return intern(content, nullptr);
}

std::optional<NameId> NameTable::intern(std::string_view content, bool* missing)
{
    return intern(idOf(content), content, missing);
}

std::optional<NameId> NameTable::intern(const NameId& id, std::string_view content, bool* missing)
{
    const Entry* existing = get(id);
    if (!existing && missing) {
        *missing = true;  // a dry run goes on as if it were inserted
        return id;
    }
    if (!existing) {
        int depth = depthOfContent(content);  // before the lock: it reads other entries
        std::unique_lock lock(_mutex);
        auto [it, inserted] = _entries.try_emplace(id);
        if (inserted) {
            it->second = std::make_unique<Entry>(content);
            it->second->depth = depth;
            return id;
        }
        existing = it->second.get();  // another thread inserted it meanwhile
    }
    if (existing->content == content) {
        return id;
    }
    if (missing) {
        return std::nullopt;
    }
    ++_collisions;
    // Once per ID: a name that keeps a colliding node inline meets the collision again at every
    // conversion (ops#97)
    if (!existing->collisionWarned.exchange(true)) {
        FC_WARN("Name ID collision: " << id.toBase32() << " holds '" << existing->content
                                      << "'; refused '" << content
                                      << "', which stays inline in full form");
    }
    else {
        FC_LOG("Name ID collision again: " << id.toBase32() << ", refused '" << content << "'");
    }
    return std::nullopt;
}

bool NameTable::insertForTesting(const NameId& id, std::string_view content)
{
    std::unique_lock lock(_mutex);
    auto [it, inserted] = _entries.try_emplace(id);
    if (inserted) {
        it->second = std::make_unique<Entry>(content);  // its depth is found when asked for
    }
    return inserted;
}

NameTable::LoadResult NameTable::insertLoaded(const NameId& id, std::string_view content)
{
    if (idOf(content) != id) {
        ++_collisions;
        FC_WARN("Name table entry " << id.toBase32() << " doesn't match its content '"
                                    << content << "'; refused");
        return LoadResult::WrongId;
    }
    bool hadIt = get(id) != nullptr;
    if (!intern(content)) {
        return LoadResult::Collision;
    }
    return hadIt ? LoadResult::Identical : LoadResult::Inserted;
}

int NameTable::depthOfContent(std::string_view content) const
{
    // Every `~` starts a reference: it occurs nowhere else in a name.
    int deepest = 0;
    for (std::size_t pos = content.find(Marker); pos != std::string_view::npos;
         pos = content.find(Marker, pos + 1)) {
        auto ref = parseRef(content.substr(pos, RefLength));
        if (!ref) {
            continue;
        }
        const Entry* entry = get(*ref);
        if (!entry) {
            return 0;
        }
        int childDepth = entry->depth;
        if (childDepth == 0) {
            childDepth = depthOfContent(entry->content);
            if (childDepth == 0) {
                return 0;
            }
            entry->depth = childDepth;
        }
        deepest = std::max(deepest, childDepth);
    }
    return deepest + 1;
}

int NameTable::depth(const NameId& id) const
{
    const Entry* entry = get(id);
    if (!entry) {
        return 0;
    }
    int value = entry->depth;
    if (value == 0) {
        // Entries loaded from a file come in ID order, so a node can arrive before the nodes
        // it refers to; its depth is found when asked for.
        value = depthOfContent(entry->content);
        if (value != 0) {
            entry->depth = value;
        }
    }
    return value;
}

std::optional<std::string> NameTable::expand(const NameId& id) const
{
    if (const Entry* entry = get(id)) {
        return toPlain(entry->content);
    }
    return std::nullopt;
}

std::optional<NameId> NameTable::internName(std::string_view name)
{
    return internName(name, nullptr);
}

std::optional<NameId> NameTable::internName(std::string_view name, bool* missing)
{
    if (auto ref = parseRef(name)) {
        return ref;
    }
    return intern(toInterned(name, missing), missing);
}

std::string NameTable::toInterned(std::string_view name)
{
    return toInterned(name, nullptr);
}

std::optional<std::string> NameTable::toInternedIfKnown(std::string_view name) const
{
    bool missing = false;
    // A dry run changes nothing: with `missing` set, intern() doesn't insert
    std::string form = const_cast<NameTable*>(this)->toInterned(name, &missing);  // NOLINT
    if (missing) {
        return std::nullopt;
    }
    return form;
}

std::string NameTable::toInterned(std::string_view name, bool* missing)
{
    if (auto ref = parseRef(name)) {
        // A whole name that is one reference: its canonical form is the entry's.
        if (const Entry* entry = get(*ref)) {
            return entry->content;
        }
        return std::string(name);
    }
    std::size_t bar = lastTopLevelBar(name);
    if (bar == std::string_view::npos) {
        return internSection(name, missing);
    }
    std::string_view prefix = name.substr(0, bar);
    std::string result;
    result.reserve(name.size());
    if (parseRef(prefix)) {
        result = prefix;
    }
    else if (auto id = internName(prefix, missing)) {
        result = makeRef(*id);
    }
    else {
        result = toPlain(prefix);  // collision: the prefix stays inline in full form
    }
    result += nameDelimiter;
    result += internSection(name.substr(bar + 1), missing);
    return result;
}

std::string NameTable::internSection(std::string_view section, bool* missing)
{
    // Written into one string as the fields are read, with no lists of parts: this runs for
    // every name a V2i map stores, and its allocations were most of its cost (ops#101)
    std::string out;
    out.reserve(section.size());
    int field = 0;
    forEachTopLevel(section, fieldDelimiter, [&](std::string_view text) {
        if (field != 0) {
            out += fieldDelimiter;
        }
        if (!isNameListField(field++) || text.empty() || text == EMPTY_VALUE) {
            out += text;
            return;
        }
        bool first = true;
        forEachTopLevel(text, listDelimiter, [&](std::string_view entry) {
            if (!first) {
                out += listDelimiter;
            }
            first = false;
            // An entry without a caret is its own unescaped form
            std::string unescaped;
            std::string_view name = entry;
            if (entry.find(escapeChar) != std::string_view::npos) {
                unescaped = unescapeOnce(entry);
                name = unescaped;
            }
            if (parseRef(name)) {
                out += name;
            }
            else if (auto id = internName(name, missing)) {
                out += Marker;
                out += id->toBase32();
            }
            else {
                out += escapeOnce(toPlain(name));  // collision: inline, full form
            }
        });
    });
    return out;
}

std::string NameTable::toPlain(std::string_view name) const
{
    return toPlain(name, nullptr);
}

const std::string* NameTable::contentOf(const NameId& id, const NameRemap* remap) const
{
    if (remap) {
        if (remap->isUnknown(id)) {
            return nullptr;
        }
        if (remap->isInline(id)) {
            return &remap->_file.at(id);
        }
    }
    const Entry* entry = get(id);
    return entry ? &entry->content : nullptr;
}

std::string NameTable::toPlain(std::string_view name, const NameRemap* remap) const
{
    if (name.find(Marker) == std::string_view::npos) {
        return std::string(name);
    }
    if (auto ref = parseRef(name)) {
        if (const std::string* content = contentOf(*ref, remap)) {
            return toPlain(*content, remap);
        }
        return std::string(name);
    }
    auto sections = splitTopLevel(name, nameDelimiter);
    std::vector<std::string> result;
    result.reserve(sections.size());
    for (std::size_t i = 0; i < sections.size(); ++i) {
        if (i == 0 && parseRef(sections[0])) {
            result.push_back(toPlain(sections[0], remap));  // the prefix of a split piece
        }
        else {
            result.push_back(plainSection(sections[i], remap));
        }
    }
    std::string out;
    join(out, result, nameDelimiter);
    return out;
}

std::string NameTable::plainSection(std::string_view section, const NameRemap* remap) const
{
    if (section.find(Marker) == std::string_view::npos) {
        return std::string(section);
    }
    auto fields = splitTopLevel(section, fieldDelimiter);
    std::vector<std::string> result;
    result.reserve(fields.size());
    for (std::size_t field = 0; field < fields.size(); ++field) {
        std::string_view text = fields[field];
        if (!isNameListField(static_cast<int>(field))
            || text.find(Marker) == std::string_view::npos) {
            result.emplace_back(text);
            continue;
        }
        std::vector<std::string> entries;
        for (std::string_view entry : splitTopLevel(text, listDelimiter)) {
            if (entry.find(Marker) == std::string_view::npos) {
                entries.emplace_back(entry);
            }
            else {
                entries.push_back(escapeOnce(toPlain(unescapeOnce(entry), remap)));
            }
        }
        std::string list;
        join(list, entries, listDelimiter);
        result.push_back(std::move(list));
    }
    std::string out;
    join(out, result, fieldDelimiter);
    return out;
}

namespace Data
{

/** Walks the full V2 form of a name byte by byte without building it.
 *
 * Each frame is a text written at an escape level: a delimiter at level L comes out as L carets
 * and the delimiter. A known reference in a caret-free text is a frame of its own: a leading
 * `~<ID>` (a prefix) at the same level, a `~<ID>` entry of a Linked or Connected Names list one
 * level deeper. A text with carets holds an inline name (the collision fallback), so it is
 * expanded with toPlain() and walked as plain bytes.
 */
class ExpansionCursor
{
public:
    struct Ref
    {
        const NameTable::Entry* entry = nullptr;
        NameId id;
        int level = 0;
    };

    ExpansionCursor(const NameTable& table, std::string_view name)
        : _table(table)
    {
        push(name, 0, name.find(escapeChar) != std::string_view::npos);
    }

    bool atEnd()
    {
        normalize();
        return _frames.empty();
    }

    /// The reference starting here, if there is one (normalize() first).
    const std::optional<Ref>& ref() const
    {
        return _ref;
    }

    /// The next byte (normalize() first, no reference here).
    unsigned char byte() const
    {
        const Frame& frame = _frames.back();
        char c = frame.text[frame.pos];
        if (isDelimiter(c) && frame.caretsDone < frame.level) {
            return static_cast<unsigned char>(escapeChar);
        }
        return static_cast<unsigned char>(c);
    }

    void advanceByte()
    {
        Frame& frame = _frames.back();
        char c = frame.text[frame.pos];
        if (isDelimiter(c)) {
            if (frame.caretsDone < frame.level) {
                ++frame.caretsDone;
                return;
            }
            frame.caretsDone = 0;
            if (c == nameDelimiter) {
                frame.field = 0;
            }
            else if (c == fieldDelimiter) {
                ++frame.field;
            }
            frame.entryStart = true;
        }
        else {
            frame.entryStart = false;
        }
        ++frame.pos;
    }

    /// Skips the reference here without walking its expansion.
    void skipRef()
    {
        stepOverRef();
    }

    /// Walks into the reference here.
    void enterRef()
    {
        Ref ref = *_ref;
        stepOverRef();
        const NameTable::Entry* entry = ref.entry;
        push(entry->content, ref.level, entry->hasCaret);
    }

    /// Finds what comes next: pops finished frames and recognizes a reference.
    void normalize()
    {
        _ref.reset();
        while (!_frames.empty()) {
            Frame& frame = _frames.back();
            if (frame.pos == frame.text.size()) {
                _frames.pop_back();
                continue;
            }
            if (!frame.literal && frame.text[frame.pos] == NameTable::Marker) {
                findRef(frame);
            }
            return;
        }
    }

private:
    struct Frame
    {
        std::string_view text;
        std::unique_ptr<std::string> owned;  // the text, if expanded here
        std::size_t pos = 0;
        int level = 0;
        int caretsDone = 0;  // carets of the delimiter at pos already given out
        int field = 0;
        bool entryStart = true;
        bool literal = false;  // no references to find in it
    };

    void push(std::string_view text, int level, bool hasCaret)
    {
        Frame frame;
        frame.level = level;
        if (hasCaret) {
            frame.owned = std::make_unique<std::string>(_table.toPlain(text));
            frame.text = *frame.owned;
            frame.literal = true;
        }
        else {
            frame.text = text;
        }
        _frames.push_back(std::move(frame));
    }

    void findRef(const Frame& frame)
    {
        std::string_view rest = frame.text.substr(frame.pos);
        if (rest.size() < NameTable::RefLength) {
            return;
        }
        int level = 0;
        char next = rest.size() > NameTable::RefLength ? rest[NameTable::RefLength] : '\0';
        if (frame.pos == 0 && (next == '\0' || next == nameDelimiter)) {
            level = frame.level;  // a prefix, or a whole name that is a reference
        }
        else if (frame.entryStart && isNameListField(frame.field)
                 && (next == '\0' || isDelimiter(next))) {
            level = frame.level + 1;  // an embedded name
        }
        else {
            return;
        }
        auto id = NameTable::parseRef(rest.substr(0, NameTable::RefLength));
        if (!id) {
            return;
        }
        const NameTable::Entry* entry = _table.get(*id);
        if (!entry) {
            return;  // unknown: its bytes are given out as they are, as toPlain() keeps them
        }
        _ref = Ref {entry, *id, level};
    }

    void stepOverRef()
    {
        Frame& frame = _frames.back();
        frame.pos += NameTable::RefLength;
        frame.entryStart = false;
        _ref.reset();
    }

    const NameTable& _table;
    std::vector<Frame> _frames;
    std::optional<Ref> _ref;
};

}  // namespace Data

int NameTable::compareExpanded(std::string_view a, std::string_view b) const
{
    if (a.find(Marker) == std::string_view::npos && b.find(Marker) == std::string_view::npos) {
        int value = a.compare(b);  // plain names: the bytes are the expansion
        return value < 0 ? -1 : (value > 0 ? 1 : 0);
    }
    ExpansionCursor left(*this, a);
    ExpansionCursor right(*this, b);
    while (true) {
        bool leftEnd = left.atEnd();
        bool rightEnd = right.atEnd();
        if (leftEnd || rightEnd) {
            return leftEnd == rightEnd ? 0 : (leftEnd ? -1 : 1);
        }
        const auto& leftRef = left.ref();
        const auto& rightRef = right.ref();
        if (leftRef && rightRef && leftRef->id == rightRef->id
            && leftRef->level == rightRef->level) {
            left.skipRef();  // the same node at the same depth expands to the same bytes
            right.skipRef();
            continue;
        }
        if (leftRef) {
            left.enterRef();
            continue;
        }
        if (rightRef) {
            right.enterRef();
            continue;
        }
        unsigned char l = left.byte();
        unsigned char r = right.byte();
        if (l != r) {
            return l < r ? -1 : 1;
        }
        left.advanceByte();
        right.advanceByte();
    }
}

// ---------------------------------------------------------------------------------------------
// Saving and loading (ops#6, Task 1 PR 7)
// ---------------------------------------------------------------------------------------------

void NameTable::writeEntries(std::ostream& stream, const std::vector<std::string>& contents)
{
    stream << "NameTableStart v2 " << contents.size() << '\n';
    for (const auto& content : contents) {
        stream << content << '\n';
    }
}

NameId NameTable::indexStandIn(std::size_t index)
{
    return NameId::compute("no entry " + std::to_string(index), IdBits);
}

NameTable::LoadSummary NameTable::readEntries(std::istream& stream,
                                              std::vector<SavedEntry>* entries,
                                              std::vector<NameId>* byIndex)
{
    LoadSummary summary;
    std::string marker;
    std::string version;
    std::size_t count = 0;
    stream >> marker >> version >> count;
    if (marker != "NameTableStart" || version != "v2") {
        FC_ERR("Unknown name table format '" << marker << ' ' << version << "'");
        return summary;
    }
    std::vector<NameId> ids;
    std::string line;
    std::getline(stream, line);  // the rest of the first line
    for (std::size_t i = 0; i < count && std::getline(stream, line); ++i) {
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        if (line.empty() || line.find_first_of(" \t") != std::string::npos) {
            ++summary.malformed;
            ids.push_back(indexStandIn(i));
            continue;
        }
        // Dependencies come first: an entry refers only to the ones before it
        indicesToRefs(line, ids, i, '\0', &summary.malformed);
        // The ID is computed once: there is nothing to check it against
        NameId id = idOf(line);
        ids.push_back(id);
        bool hadIt = get(id) != nullptr;
        if (!intern(id, line, nullptr)) {
            summary.refused.emplace_back(id, line);
        }
        else if (hadIt) {
            ++summary.identical;
        }
        else {
            ++summary.inserted;
        }
        if (entries) {
            entries->emplace_back(id, std::move(line));
        }
    }
    if (summary.malformed != 0) {
        FC_ERR("Name table: " << summary.malformed << " malformed lines or references");
    }
    if (byIndex) {
        *byIndex = std::move(ids);
    }
    return summary;
}

namespace
{
thread_local NameRefCollector* activeCollector = nullptr;
thread_local const NameRefCollector* fileFormCollector = nullptr;
}  // namespace

NameRefCollector::NameRefCollector()
    : _previous(activeCollector)
{
    activeCollector = this;
}

NameRefCollector::~NameRefCollector()
{
    activeCollector = _previous;
}

NameRefCollector* NameRefCollector::active()
{
    return activeCollector;
}

void NameRefCollector::add(std::string_view text)
{
    for (std::size_t pos = text.find(NameTable::Marker);
         pos != std::string_view::npos && pos + NameTable::RefLength <= text.size();
         pos = text.find(NameTable::Marker, pos + 1)) {
        if (auto id = NameTable::parseRef(text.substr(pos, NameTable::RefLength))) {
            if (_refs.insert(*id).second) {
                _order.push_back(*id);
            }
        }
    }
}

void NameRefCollector::number(const NameId& root, const NameTable& table)
{
    // Iterative depth-first post-order: an entry gets its index after the ones it refers to,
    // so a file lists dependencies first (histories can be deep)
    struct Frame
    {
        NameId id;
        const std::string* content;
        std::vector<NameId> refs;
        std::size_t next = 0;
    };
    auto isDone = [this](const NameId& id) {
        return _index.count(id) != 0 || _unknown.count(id) != 0;
    };
    std::vector<Frame> stack;
    std::set<NameId> visiting;  // no content holds its own ID; a guard all the same
    auto push = [&](const NameId& id) {
        const NameTable::Entry* entry = table.get(id);
        if (!entry) {
            _unknown.insert(id);
            return;
        }
        visiting.insert(id);
        stack.push_back({id, &entry->content, refsIn(entry->content), 0});
    };
    if (isDone(root)) {
        return;
    }
    push(root);
    while (!stack.empty()) {
        Frame& frame = stack.back();
        if (frame.next < frame.refs.size()) {
            NameId ref = frame.refs[frame.next++];
            if (!isDone(ref) && visiting.count(ref) == 0) {
                push(ref);  // frame is invalid from here
            }
            continue;
        }
        _index.emplace(frame.id, _entries.size());
        _entries.emplace_back(frame.id, *frame.content);
        visiting.erase(frame.id);
        stack.pop_back();
    }
}

const std::vector<NameTable::SavedEntry>& NameRefCollector::entries(const NameTable& table,
                                                                    std::size_t* unknown)
{
    for (; _numbered < _order.size(); ++_numbered) {
        number(_order[_numbered], table);
    }
    if (unknown) {
        *unknown = _unknown.size();
    }
    return _entries;
}

std::vector<std::string> NameRefCollector::fileEntries(const NameTable& table,
                                                       std::size_t* unknown)
{
    entries(table, unknown);
    std::vector<std::string> contents;
    contents.reserve(_entries.size());
    for (const auto& entry : _entries) {
        contents.emplace_back();
        appendFileForm(contents.back(), entry.second);
    }
    return contents;
}

std::optional<std::size_t> NameRefCollector::indexOf(const NameId& id) const
{
    auto it = _index.find(id);
    if (it == _index.end()) {
        return std::nullopt;
    }
    return it->second;
}

void NameRefCollector::appendFileForm(std::string& out, std::string_view text, char next) const
{
    std::size_t done = 0;
    for (std::size_t pos = text.find(NameTable::Marker); pos != std::string_view::npos;
         pos = text.find(NameTable::Marker, pos + 1)) {
        std::size_t end = base32RunEnd(text, pos + 1);
        if (end - pos != NameTable::RefLength || (end == text.size() && isBase32Digit(next))) {
            continue;
        }
        auto id = NameTable::parseRef(text.substr(pos, NameTable::RefLength));
        if (!id) {
            continue;
        }
        auto it = _index.find(*id);
        if (it == _index.end()) {
            continue;  // not in the file's table: the hash form, unknown to a reader
        }
        out.append(text, done, pos - done);
        out += NameTable::Marker;
        char digits[24];
        auto [ptr, error] = std::to_chars(std::begin(digits), std::end(digits), it->second);
        out.append(digits, ptr);
        done = end;
        pos = end - 1;
    }
    out.append(text, done, std::string_view::npos);
}

void NameRefCollector::bind(const void* writer, const NameTable& table)
{
    entries(table);
    _writer = writer;
}

NameRefCollector::FileFormScope::FileFormScope(const void* writer)
    : _previous(fileFormCollector)
{
    const NameRefCollector* found = nullptr;
    for (const NameRefCollector* collector = activeCollector; collector && writer;
         collector = collector->_previous) {
        if (collector->_writer == writer) {
            found = collector;
            break;
        }
    }
    fileFormCollector = found;
}

NameRefCollector::FileFormScope::~FileFormScope()
{
    fileFormCollector = _previous;
}

const NameRefCollector* NameRefCollector::fileForm()
{
    return fileFormCollector;
}

NameRefScanBuffer::NameRefScanBuffer(std::streambuf* target, NameRefCollector& collector)
    : _target(target)
    , _collector(collector)
{}

void NameRefScanBuffer::scan(std::string_view data)
{
    constexpr std::size_t keep = NameTable::RefLength - 1;
    if (!_tail.empty()) {
        // A reference that starts in the tail ends in data
        std::string joined = _tail;
        joined.append(data.substr(0, keep));
        _collector.add(joined);
    }
    _collector.add(data);
    if (data.size() >= keep) {
        _tail.assign(data.substr(data.size() - keep));
    }
    else {
        _tail.append(data);
        if (_tail.size() > keep) {
            _tail.erase(0, _tail.size() - keep);
        }
    }
}

NameRefScanBuffer::int_type NameRefScanBuffer::overflow(int_type c)
{
    if (traits_type::eq_int_type(c, traits_type::eof())) {
        return traits_type::not_eof(c);
    }
    char ch = traits_type::to_char_type(c);
    scan(std::string_view(&ch, 1));
    return _target->sputc(ch);
}

std::streamsize NameRefScanBuffer::xsputn(const char* s, std::streamsize n)
{
    if (n > 0) {
        scan(std::string_view(s, static_cast<std::size_t>(n)));
    }
    return _target->sputn(s, n);
}

int NameRefScanBuffer::sync()
{
    return _target->pubsync();
}

// ---------------------------------------------------------------------------------------------
// Loading (ops#6, Task 1 PR 8)
// ---------------------------------------------------------------------------------------------

namespace
{
thread_local NameRemap* activeRemap = nullptr;
}  // namespace

NameRemap::NameRemap(NameTable& table)
    : _table(table)
    , _previous(activeRemap)
{
    activeRemap = this;
}

NameRemap::~NameRemap()
{
    _filter.reset();
    activeRemap = _previous;
}

NameRemap* NameRemap::active()
{
    return activeRemap;
}

NameTable::LoadSummary NameRemap::load(std::istream& stream)
{
    std::vector<NameTable::SavedEntry> entries;
    auto summary = _table.readEntries(stream, &entries, &_byIndex);
    for (auto& [id, content] : entries) {
        _file[id] = std::move(content);
    }
    std::set<NameId> refused;
    for (const auto& entry : summary.refused) {
        refused.insert(entry.first);
    }

    // Which entries are inline (refused, or referring to an inline one) and which incomplete
    // (referring to an ID the file lacks, or to an incomplete one): a depth-first walk over the
    // references, iterative, as histories can be deep. Incomplete wins: such a name can't be
    // written out in full.
    enum class State : char
    {
        Visiting,
        Plain,
        Inline,
        Incomplete,
    };
    struct Frame
    {
        NameId id;
        std::vector<NameId> refs;
        std::size_t next = 0;
        bool isInline = false;
        bool incomplete = false;
    };
    std::unordered_map<NameId, State, NameTable::IdHash> state;
    std::vector<Frame> stack;
    auto push = [&](const NameId& id, const std::string& content) {
        state[id] = State::Visiting;
        stack.push_back({id, refsIn(content), 0, refused.count(id) != 0, false});
    };
    for (const auto& [root, rootContent] : _file) {
        if (state.count(root) != 0) {
            continue;
        }
        push(root, rootContent);
        while (!stack.empty()) {
            Frame& frame = stack.back();
            if (frame.next < frame.refs.size()) {
                NameId ref = frame.refs[frame.next++];
                auto it = state.find(ref);
                if (it == state.end()) {
                    auto file = _file.find(ref);
                    if (file == _file.end()) {
                        frame.incomplete = true;
                    }
                    else {
                        push(ref, file->second);  // frame is invalid from here
                    }
                    continue;
                }
                switch (it->second) {
                    case State::Visiting:  // a cycle: no content can hold its own ID
                    case State::Incomplete:
                        frame.incomplete = true;
                        break;
                    case State::Inline:
                        frame.isInline = true;
                        break;
                    case State::Plain:
                        break;
                }
                continue;
            }
            State result = State::Plain;
            if (frame.incomplete) {
                result = State::Incomplete;
                _incomplete.insert(frame.id);
            }
            else if (frame.isInline) {
                result = State::Inline;
                _inlineIds.insert(frame.id);
            }
            state[frame.id] = result;
            stack.pop_back();
            if (!stack.empty()) {
                stack.back().incomplete |= result == State::Incomplete;
                stack.back().isInline |= result == State::Inline;
            }
        }
    }
    return summary;
}

void NameRemap::setNewerFormat()
{
    _newerFormat = true;
}

void NameRemap::filterAttributes(const Base::XMLReader& reader)
{
    if (_inlineIds.empty() || _newerFormat) {
        return;
    }
    _filter = std::make_unique<Base::XMLAttributeFilter>(reader, [this](std::string& value) {
        remapText(value);
    });
}

bool NameRemap::isUnknown(const NameId& id) const
{
    return _newerFormat || _file.count(id) == 0 || _incomplete.count(id) != 0;
}

bool NameRemap::isInline(const NameId& id) const
{
    return !_newerFormat && _inlineIds.count(id) != 0;
}

std::string NameRemap::inlineForm(const NameId& id) const
{
    std::string full = _table.toPlain(NameTable::makeRef(id), this);
    markUnknown(full);
    return full;
}

bool NameRemap::markUnknown(std::string& text) const
{
    bool changed = false;
    for (std::size_t pos = text.find(NameTable::Marker);
         pos != std::string::npos && pos + NameTable::RefLength <= text.size();
         pos = text.find(NameTable::Marker, pos + 1)) {
        auto id = NameTable::parseRef(std::string_view(text).substr(pos, NameTable::RefLength));
        if (id && isUnknown(*id)) {
            text.insert(pos + 1, 1, UnknownMark);
            _unknownSeen.insert(*id);
            changed = true;
        }
    }
    return changed;
}

void NameRemap::scan(std::string_view text, bool& hasInline, bool& hasUnknown) const
{
    for (const NameId& id : refsIn(text)) {
        if (isUnknown(id)) {
            hasUnknown = true;
        }
        else if (isInline(id)) {
            hasInline = true;
        }
    }
}

bool NameRemap::remapText(std::string& text) const
{
    if (_inlineIds.empty() || _newerFormat || text.find(NameTable::Marker) == std::string::npos) {
        return false;
    }
    std::string out;
    std::size_t done = 0;
    for (std::size_t pos = text.find(NameTable::Marker);
         pos != std::string::npos && pos + NameTable::RefLength <= text.size();
         pos = text.find(NameTable::Marker, pos + 1)) {
        auto id = NameTable::parseRef(std::string_view(text).substr(pos, NameTable::RefLength));
        if (!id || !isInline(*id)) {
            continue;
        }
        std::size_t end = pos + NameTable::RefLength;
        // A prefix is followed by the `|` before its name's last section; any other reference
        // in a name is an embedded name, one escape level down. This assumes every reference in
        // a file's text sits at depth 0 or 1, as a canonical name has them. One deeper, inside
        // an inline collision fallback left at save time (an embedded name in full form) whose
        // expansion kept an unknown reference, would need two levels; it takes a collision at
        // save time, an ID unknown under it and a collision on that ID at load (ops#97).
        bool prefix = end < text.size() && text[end] == nameDelimiter;
        out.append(text, done, pos - done);
        std::string full = inlineForm(*id);
        out += prefix ? full : escapeOnce(full);
        done = end;
        pos = end - 1;
    }
    if (done == 0) {
        return false;
    }
    out.append(text, done, std::string::npos);
    text = std::move(out);
    return true;
}

bool NameRemap::remapSubName(std::string& text)
{
    if (text.find(NameTable::Marker) == std::string::npos) {
        return false;
    }
    bool changed = remapText(text);
    return markUnknown(text) || changed;
}

NameRemap::MapName NameRemap::remapMapName(std::string& name)
{
    if (name.find(NameTable::Marker) == std::string::npos) {
        return MapName::Unchanged;
    }
    if (_newerFormat) {
        ++_dropped;
        return MapName::Dropped;
    }
    bool converted = fromFileForm(name);
    bool hasInline = false;
    bool hasUnknown = false;
    scan(name, hasInline, hasUnknown);
    if (hasInline) {
        // The file's name in full form, then canonical in this process: its colliding nodes
        // can't be interned and stay inline
        std::string plain = _table.toPlain(name, this);
        markUnknown(plain);
        name = _table.toInterned(plain);
        return MapName::Changed;
    }
    if (hasUnknown) {
        markUnknown(name);
        return MapName::Changed;
    }
    return converted ? MapName::Changed : MapName::Unchanged;
}

bool NameRemap::fromFileForm(std::string& text, char next) const
{
    return indicesToRefs(text, _byIndex, _byIndex.size(), next);
}
