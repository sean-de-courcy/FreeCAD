// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ElementSolver.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <locale>
#include <map>
#include <numeric>
#include <optional>
#include <set>
#include <sstream>
#include <tuple>
#include <utility>

#include <Base/Exception.h>

#include "ElementNamingUtils.h"
#include "MappedName.h"

namespace Data
{

namespace
{

// The single section \a section decoded. The decode cache keeps its entries for the whole
// process, so the reference stays valid.
const DecodedMappedSection& decodeSection(std::string_view section)
{
    static const DecodedMappedSection empty;
    const auto& decoded = MappedName::getDecodedMappedName(std::string(section));
    return decoded.empty() ? empty : decoded.front();
}

std::vector<std::string> sortedFlags(const DecodedMappedSection& section)
{
    std::vector<std::string> flags = section.mapperFlags;
    std::sort(flags.begin(), flags.end());
    flags.erase(std::unique(flags.begin(), flags.end()), flags.end());
    return flags;
}

// An index suffix as the op code: `_2`, `_3`, ... (`Data::indexSuffix`). PartDesign's patterns
// gave it to their instances before ops#55; the solver still treats it as a counter.
bool isCounterOpCode(const std::string& opCode)
{
    return opCode.size() > 1 && opCode[0] == '_'
        && std::all_of(opCode.begin() + 1, opCode.end(), [](char c) {
               return c >= '0' && c <= '9';
           });
}

// The op code of a pattern instance's section, `_;_;<pattern>;TRF;<k>;<type>;0;MOD;_` (Part's
// OpCodes::Transformed, ops#55). It carries the MOD flag, but it's no split: it says which
// instance of which pattern the element is in.
constexpr const char* patternInstanceOpCode = "TRF";

// Starts and ends a pattern instance's context in a node of NameAncestry: `\x1e<tag>;<k>\x1e`
// before a name (see NameAncestry::ancestorsOf()). A control character starts no mapped name.
constexpr char contextMark = '\x1e';

// The pattern instances a name is in: (pattern, k) of each of its top-level TRF sections.
std::vector<std::pair<std::string, std::string>> patternInstances(std::string_view name)
{
    std::vector<std::pair<std::string, std::string>> instances;
    for (auto section : NameAncestry::splitSections(name)) {
        const auto& decoded = decodeSection(section);
        if (decoded.opCode == patternInstanceOpCode) {
            instances.emplace_back(decoded.iterationTag, decoded.index);
        }
    }
    return instances;
}

}  // namespace

// ---------------------------------------------------------------------------------------------
// NameAncestry

NameAncestry::Key NameAncestry::intern(std::string_view name)
{
    auto it = _keys.find(name);
    if (it != _keys.end()) {
        return it->second;
    }
    auto key = static_cast<Key>(_names.size());
    const std::string& stored = _names.emplace_back(name);
    _sets.emplace_back();
    _children.emplace_back();
    _done.push_back(0);
    _keys.emplace(std::string_view(stored), key);
    return key;
}

const std::string& NameAncestry::name(Key key) const
{
    if (key >= _names.size()) {
        throw Base::ValueError("NameAncestry: unknown key");
    }
    return _names[key];
}

std::vector<std::string_view> NameAncestry::splitSections(std::string_view name)
{
    std::vector<std::string_view> sections;
    if (name.empty()) {
        return sections;
    }
    const char delimiter = *NAME_SECTION_DELIMINATOR;
    const char escape = *SUB_SECTION_ESCAPE_CHAR;
    std::size_t start = 0;
    for (std::size_t i = 0; i < name.size(); ++i) {
        // A delimiter after a caret belongs to an embedded name, at any depth.
        if (name[i] == delimiter && (i == 0 || name[i - 1] != escape)) {
            sections.push_back(name.substr(start, i - start));
            start = i + 1;
        }
    }
    sections.push_back(name.substr(start));
    return sections;
}

const NameAncestry::KeySet& NameAncestry::ancestorsOf(Key key)
{
    if (_done[key]) {
        return _sets[key];
    }

    // The children: the prefix, and the names embedded in the last section. Copied, since the
    // recursion below interns more nodes.
    //
    // A pattern instance's name `P|<TRF;k>` is a copy of P, made by the pattern: P's ancestry is
    // the support's history, and the copy's is that history in instance k (ops#91). So the
    // prefix of a TRF section is a node in the instance's context, `\x1e<tag>;<k>\x1e<P>`, and so
    // is every node below it. The support's elements and instance k's copies of them then share
    // no ancestor, also where a name embeds an instance's name (a fusion's face bounded by an
    // edge of each of two instances); two names of one instance share the copies' ancestors.
    // A node in a context has the children of the name it stands for, in the same context.
    std::vector<std::string> children;
    std::vector<std::pair<std::string, std::string>> referenceIds;  // (ID, tag) of a leaf
    std::string context;  // the node's contexts, outermost first, for a node in a context
    {
        std::string_view node = _names[key];
        while (!node.empty() && node.front() == contextMark) {
            auto end = node.find(contextMark, 1);
            if (end == std::string_view::npos) {
                break;  // no closing mark: not a context (only a caller's string can be one)
            }
            context.append(node.substr(0, end + 1));
            node.remove_prefix(end + 1);
        }
        auto sections = splitSections(node);
        const auto& last = decodeSection(sections.empty() ? std::string_view() : sections.back());
        if (sections.size() > 1) {
            // Everything before the last top-level delimiter.
            auto prefixSize = static_cast<std::size_t>(sections.back().data() - node.data()) - 1;
            std::string prefix(node.substr(0, prefixSize));
            if (last.opCode == patternInstanceOpCode) {
                prefix = contextMark + last.iterationTag + ";" + last.index + contextMark + prefix;
            }
            children.push_back(std::move(prefix));
        }
        if (!sections.empty()) {
            for (const auto& embedded : last.linkedNames) {
                children.push_back(embedded);
            }
            for (const auto& embedded : last.connectedElements) {
                children.push_back(embedded);
            }
            if (_measure == OverlapMeasure::ReferenceIds && sections.size() == 1) {
                for (const auto& id : last.referenceIDs) {
                    if (!id.empty() && id != Data::EMPTY_VALUE) {
                        referenceIds.emplace_back(id, last.iterationTag);
                    }
                }
            }
        }
    }

    KeySet result {key};
    std::vector<Key> childKeys;
    for (const auto& child : children) {
        if (child.empty()) {
            continue;
        }
        Key childKey = intern(context + child);
        if (childKey == key) {
            continue;  // not possible for a well-formed name, which is longer than its parts
        }
        childKeys.push_back(childKey);
        const KeySet& childSet = ancestorsOf(childKey);
        result.insert(result.end(), childSet.begin(), childSet.end());
    }
    for (const auto& [id, tag] : referenceIds) {
        // In a context, the leaf is the context's copy of it: another leaf.
        Key idKey = internReferenceId(context + id, tag);
        childKeys.push_back(idKey);
        result.push_back(idKey);
    }
    std::sort(result.begin(), result.end());
    result.erase(std::unique(result.begin(), result.end()), result.end());

    _children[key] = std::move(childKeys);
    _sets[key] = std::move(result);
    _done[key] = 1;
    ++_computed;
    return _sets[key];
}

const NameAncestry::KeySet& NameAncestry::ancestors(std::string_view name)
{
    static const KeySet empty;
    if (name.empty()) {
        return empty;
    }
    return ancestorsOf(intern(name));
}

std::vector<std::string> NameAncestry::ancestorNames(std::string_view name)
{
    std::vector<std::string> names;
    for (Key key : ancestors(name)) {
        names.push_back(_names[key]);
    }
    std::sort(names.begin(), names.end());
    return names;
}

bool NameAncestry::contains(std::string_view name, std::string_view ancestor)
{
    if (name.empty() || ancestor.empty()) {
        return false;
    }
    auto it = _keys.find(ancestor);
    if (it == _keys.end()) {
        // Not seen yet: it can still be in the set, which interns every node it holds.
        const KeySet& set = ancestors(name);
        it = _keys.find(ancestor);
        return it != _keys.end() && std::binary_search(set.begin(), set.end(), it->second);
    }
    Key ancestorKey = it->second;
    const KeySet& set = ancestors(name);
    return std::binary_search(set.begin(), set.end(), ancestorKey);
}

double NameAncestry::overlap(std::string_view oldName, std::string_view candidate)
{
    if (oldName.empty()) {
        return 0.0;
    }
    // Computing the candidate's set may intern nodes; the deques keep oldSet valid.
    const KeySet& oldSet = ancestors(oldName);
    const KeySet& candidateSet = ancestors(candidate);
    if (_measure == OverlapMeasure::DepthWeighted) {
        return weightedOverlap(intern(oldName), candidateSet);
    }
    std::size_t common = 0;
    auto a = oldSet.begin();
    auto b = candidateSet.begin();
    while (a != oldSet.end() && b != candidateSet.end()) {
        if (*a < *b) {
            ++a;
        }
        else if (*b < *a) {
            ++b;
        }
        else {
            ++common;
            ++a;
            ++b;
        }
    }
    return static_cast<double>(common) / static_cast<double>(oldSet.size());
}

NameAncestry::Key NameAncestry::internReferenceId(const std::string& id, const std::string& tag)
{
    // A control character starts no mapped name, so no name interns the same string.
    Key key = intern("\x1f" + id + "@" + tag);
    if (!_done[key]) {
        _sets[key] = {key};
        _done[key] = 1;
        ++_computed;
    }
    return key;
}

double NameAncestry::weightedOverlap(Key oldKey, const KeySet& candidateSet)
{
    auto it = _weights.find(oldKey);
    if (it == _weights.end()) {
        // Shortest depths below the old name, breadth first over the children ancestorsOf()
        // recorded (the old name's set is computed, so every node in it has its children).
        std::map<Key, int> depth {{oldKey, 0}};
        std::vector<Key> level {oldKey};
        for (int d = 1; !level.empty(); ++d) {
            std::vector<Key> next;
            for (Key node : level) {
                for (Key child : _children[node]) {
                    if (depth.emplace(child, d).second) {
                        next.push_back(child);
                    }
                }
            }
            level = std::move(next);
        }
        std::vector<std::pair<Key, double>> weights;
        double total = 0.0;
        for (const auto& [node, d] : depth) {
            double weight = std::ldexp(1.0, -d);
            weights.emplace_back(node, weight);
            total += weight;
        }
        it = _weights.emplace(oldKey, std::make_pair(std::move(weights), total)).first;
    }
    const auto& [weights, total] = it->second;
    double common = 0.0;
    for (const auto& [node, weight] : weights) {
        if (std::binary_search(candidateSet.begin(), candidateSet.end(), node)) {
            common += weight;
        }
    }
    return total > 0.0 ? common / total : 0.0;
}

bool NameAncestry::topAgrees(std::string_view oldName, std::string_view candidate)
{
    auto oldSections = splitSections(oldName);
    auto candidateSections = splitSections(candidate);
    if (oldSections.empty() || candidateSections.empty()) {
        return false;
    }
    const auto& oldTop = decodeSection(oldSections.back());
    const auto& candidateTop = decodeSection(candidateSections.back());
    return oldTop.opCode == candidateTop.opCode && sortedFlags(oldTop) == sortedFlags(candidateTop);
}

bool NameAncestry::isPieceOf(std::string_view name, std::string_view oldName)
{
    // A split made before a pattern instance's section (WholeShape mode, or an edit upstream of
    // the pattern): the instance's piece is `X|<split>|<TRF>`, its element `X|<TRF>`. They are
    // compared without the chain of TRF sections both end in.
    {
        auto nameSections = splitSections(name);
        auto oldSections = splitSections(oldName);
        std::size_t common = 0;
        while (common < nameSections.size() && common < oldSections.size()) {
            auto section = nameSections[nameSections.size() - 1 - common];
            if (section != oldSections[oldSections.size() - 1 - common]
                || decodeSection(section).opCode != patternInstanceOpCode) {
                break;
            }
            ++common;
        }
        if (common > 0 && common < nameSections.size() && common < oldSections.size()) {
            // Each head ends before the delimiter of its first TRF section.
            auto head = [](std::string_view whole, std::string_view firstStripped) {
                return whole.substr(0, firstStripped.data() - whole.data() - 1);
            };
            return isPieceOf(
                head(name, nameSections[nameSections.size() - common]),
                head(oldName, oldSections[oldSections.size() - common])
            );
        }
    }
    if (oldName.empty() || name.size() <= oldName.size() + 1
        || name.substr(0, oldName.size()) != oldName) {
        return false;
    }
    // The old name must end at a top-level delimiter of the piece.
    if (name[oldName.size()] != *NAME_SECTION_DELIMINATOR
        || oldName.back() == *SUB_SECTION_ESCAPE_CHAR) {
        return false;
    }
    auto oldSections = splitSections(oldName);
    char elementType = decodeSection(oldSections.back()).elementType;
    auto added = splitSections(name.substr(oldName.size() + 1));
    if (added.empty()) {
        return false;
    }
    for (auto section : added) {
        const auto& decoded = decodeSection(section);
        if (!decoded.hasMapperFlag(MAPPER_FLAG_MODIFIED) || decoded.elementType != elementType
            || decoded.opCode == patternInstanceOpCode) {
            return false;
        }
    }
    return true;
}

namespace
{

// The decoded section if \a name is one section carrying the IDX flag, with a real op code.
const DecodedMappedSection* indexSection(std::string_view name)
{
    if (name.empty() || NameAncestry::splitSections(name).size() != 1) {
        return nullptr;
    }
    const auto& decoded = decodeSection(name);
    if (!decoded.hasMapperFlag(MAPPER_FLAG_INDEX) || decoded.opCode.empty()
        || isCounterOpCode(decoded.opCode)) {
        return nullptr;
    }
    return &decoded;
}

}  // namespace

bool NameAncestry::sameIndexSource(std::string_view a, std::string_view b)
{
    const DecodedMappedSection* x = indexSection(a);
    const DecodedMappedSection* y = indexSection(b);  // the cache's nodes don't move
    if (!x || !y) {
        return false;
    }
    return x->referenceIDs == y->referenceIDs && x->linkedNames == y->linkedNames
        && x->iterationTag == y->iterationTag && x->index == y->index
        && x->elementType == y->elementType && x->duplicateCount == y->duplicateCount
        && sortedFlags(*x) == sortedFlags(*y) && x->connectedElements == y->connectedElements;
}

std::string_view NameAncestry::indexSource(std::string_view name)
{
    if (indexSection(name)) {
        return name;
    }
    auto sections = splitSections(name);
    if (sections.size() < 2 || !indexSection(sections.front())
        || !isPieceOf(name, sections.front())) {
        return {};
    }
    return sections.front();
}

bool NameAncestry::isIndexPieceOf(std::string_view name, std::string_view oldName)
{
    if (!indexSection(oldName)) {
        return false;
    }
    auto sections = splitSections(name);
    if (sections.size() < 2 || sections.front() == oldName
        || !sameIndexSource(sections.front(), oldName)) {
        return false;
    }
    return isPieceOf(name, sections.front());
}

std::vector<int> NameAncestry::structuralSurvivors(
    std::string_view oldName,
    const std::vector<std::string>& candidates,
    double gap
)
{
    // Overlaps are ratios of small integers; the slack keeps best - gap from excluding a
    // candidate exactly at the boundary through rounding.
    constexpr double slack = 1e-12;

    // The top-level TRF sections say which instance an element is in: an element of another
    // instance, or of the original, is another element (ops#55), even where a later section
    // embeds names of the old name's instance (a fusion's piece of instance 3 bounded by an
    // edge of instance 2, which ancestorsOf()'s contexts alone would relate, ops#91).
    const auto oldInstances = patternInstances(oldName);
    std::vector<double> overlaps;
    overlaps.reserve(candidates.size());
    double best = 0.0;
    for (const auto& candidate : candidates) {
        overlaps.push_back(
            patternInstances(candidate) == oldInstances ? overlap(oldName, candidate) : 0.0
        );
        best = std::max(best, overlaps.back());
    }
    std::vector<int> survivors;
    if (best <= 0.0) {
        return survivors;
    }
    for (std::size_t i = 0; i < candidates.size(); ++i) {
        if (overlaps[i] > 0.0 && overlaps[i] >= best - gap - slack) {
            survivors.push_back(static_cast<int>(i));
        }
    }
    std::vector<int> agreeing;
    for (int i : survivors) {
        if (topAgrees(oldName, candidates[i])) {
            agreeing.push_back(i);
        }
    }
    return agreeing.empty() ? survivors : agreeing;
}

// ---------------------------------------------------------------------------------------------
// MatchGraph and forcedMatching

int MatchGraph::addCandidate(std::vector<int> elements)
{
    candidates.push_back(Candidate {std::move(elements)});
    return static_cast<int>(candidates.size()) - 1;
}

void MatchGraph::addEdge(int entry, int candidate, bool inAncestry)
{
    edges.push_back(Edge {entry, candidate, inAncestry});
}

namespace
{

struct UnionFind
{
    explicit UnionFind(int size)
        : parent(static_cast<std::size_t>(size))
    {
        std::iota(parent.begin(), parent.end(), 0);
    }
    int find(int i)
    {
        while (parent[i] != i) {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        return i;
    }
    void unite(int a, int b)
    {
        a = find(a);
        b = find(b);
        if (a != b) {
            parent[std::max(a, b)] = std::min(a, b);
        }
    }
    std::vector<int> parent;
};

// One component of the graph, with local indices.
struct Component
{
    std::vector<int> entries;     // global entry indices
    std::vector<int> candidates;  // global candidate indices
    // Per local entry: (local candidate, inAncestry), sorted, unique.
    std::vector<std::vector<std::pair<int, bool>>> edges;
    // Per local candidate: its elements, sorted, unique.
    std::vector<std::vector<int>> elements;
    // Per local candidate: the number of inAncestry edges.
    std::vector<int> ancestral;
};

struct ComponentResult
{
    std::vector<int> partner;  // per local entry: local candidate, or -1
    std::vector<MatchStatus> status;
};

// Maximum b-matching by augmenting paths (Kuhn's algorithm with capacities).
class BMatching
{
public:
    BMatching(const Component& c, const std::vector<char>& mergeMode)
        : _c(c)
        , _mergeMode(mergeMode)
    {}

    // The size of a maximum matching without the edge (excludedEntry, excludedCandidate), and
    // the matching (per local entry: local candidate or -1).
    int solve(int excludedEntry, int excludedCandidate, std::vector<int>* matching = nullptr)
    {
        _excludedEntry = excludedEntry;
        _excludedCandidate = excludedCandidate;
        std::size_t entries = _c.entries.size();
        std::size_t candidates = _c.candidates.size();
        _assigned.assign(entries, -1);
        _users.assign(candidates, {});
        int size = 0;
        for (std::size_t e = 0; e < entries; ++e) {
            _visited.assign(candidates, 0);
            if (augment(static_cast<int>(e))) {
                ++size;
            }
        }
        if (matching) {
            *matching = _assigned;
        }
        return size;
    }

private:
    int capacity(int candidate) const
    {
        return _mergeMode[candidate] ? _c.ancestral[candidate] : 1;
    }

    bool allowed(int entry, int candidate, bool inAncestry) const
    {
        if (entry == _excludedEntry && candidate == _excludedCandidate) {
            return false;
        }
        // A candidate used as a merge takes only the entries whose old names it holds.
        return !_mergeMode[candidate] || inAncestry;
    }

    bool augment(int entry)
    {
        for (const auto& [candidate, inAncestry] : _c.edges[entry]) {
            if (!allowed(entry, candidate, inAncestry) || _visited[candidate]) {
                continue;
            }
            _visited[candidate] = 1;
            auto& users = _users[candidate];
            if (static_cast<int>(users.size()) < capacity(candidate)) {
                users.push_back(entry);
                _assigned[entry] = candidate;
                return true;
            }
            for (int& user : users) {
                int displaced = user;
                if (augment(displaced)) {
                    // augment() gave the displaced entry another candidate.
                    user = entry;
                    _assigned[entry] = candidate;
                    return true;
                }
            }
        }
        return false;
    }

    const Component& _c;
    const std::vector<char>& _mergeMode;
    int _excludedEntry = -1;
    int _excludedCandidate = -1;
    std::vector<int> _assigned;
    std::vector<std::vector<int>> _users;
    std::vector<char> _visited;
};

ComponentResult solveByAugmenting(const Component& c, int maxMerges)
{
    std::size_t entries = c.entries.size();
    ComponentResult result {std::vector<int>(entries, -1), {}};

    std::vector<int> merges;
    for (std::size_t k = 0; k < c.candidates.size(); ++k) {
        if (c.ancestral[k] >= 2) {
            merges.push_back(static_cast<int>(k));
        }
    }
    if (static_cast<int>(merges.size()) > maxMerges) {
        result.status.assign(entries, MatchStatus::TooLarge);
        return result;
    }

    // Per mode combination: its maximum and the edges forced within it.
    int best = -1;
    std::vector<std::vector<int>> forcedPerMode;
    std::vector<char> mergeMode(c.candidates.size(), 0);
    for (unsigned long mask = 0; mask < (1UL << merges.size()); ++mask) {
        for (std::size_t m = 0; m < merges.size(); ++m) {
            mergeMode[merges[m]] = (mask >> m) & 1UL ? 1 : 0;
        }
        BMatching matcher(c, mergeMode);
        std::vector<int> matching;
        int size = matcher.solve(-1, -1, &matching);
        if (size < best) {
            continue;
        }
        if (size > best) {
            best = size;
            forcedPerMode.clear();
        }
        std::vector<int> forced(entries, -1);
        for (std::size_t e = 0; e < entries; ++e) {
            if (matching[e] >= 0
                && matcher.solve(static_cast<int>(e), matching[e]) < size) {
                forced[e] = matching[e];
            }
        }
        forcedPerMode.push_back(std::move(forced));
    }

    result.status.assign(entries, MatchStatus::Ambiguous);
    for (std::size_t e = 0; e < entries; ++e) {
        int partner = forcedPerMode.front()[e];
        bool agreed = partner >= 0;
        for (const auto& forced : forcedPerMode) {
            agreed = agreed && forced[e] == partner;
        }
        if (agreed) {
            result.partner[e] = partner;
            result.status[e] = MatchStatus::Resolved;
        }
    }
    return result;
}

// Exhaustive search over every matching, for components whose candidates share elements.
class ExhaustiveSearch
{
public:
    ExhaustiveSearch(const Component& c, long maxSteps)
        : _c(c)
        , _maxSteps(maxSteps)
    {}

    ComponentResult run()
    {
        std::size_t entries = _c.entries.size();
        _assigned.assign(entries, -1);
        _users.assign(_c.candidates.size(), {});
        _elementUser.clear();
        _seen.assign(entries, -2);
        _ambiguous.assign(entries, 0);
        search(0, 0);

        ComponentResult result {std::vector<int>(entries, -1), {}};
        if (_aborted) {
            result.status.assign(entries, MatchStatus::TooLarge);
            return result;
        }
        result.status.assign(entries, MatchStatus::Ambiguous);
        for (std::size_t e = 0; e < entries; ++e) {
            if (!_ambiguous[e] && _seen[e] >= 0) {
                result.partner[e] = _seen[e];
                result.status[e] = MatchStatus::Resolved;
            }
        }
        return result;
    }

private:
    bool canUse(int candidate, bool inAncestry) const
    {
        const auto& users = _users[candidate];
        if (users.empty()) {
            for (int element : _c.elements[candidate]) {
                auto it = _elementUser.find(element);
                if (it != _elementUser.end() && it->second != candidate) {
                    return false;
                }
            }
            return true;
        }
        // Sharing a candidate is a merge: every user's old name must be in its ancestry.
        if (!inAncestry) {
            return false;
        }
        for (int user : users) {
            if (!ancestral(user, candidate)) {
                return false;
            }
        }
        return true;
    }

    bool ancestral(int entry, int candidate) const
    {
        for (const auto& [k, inAncestry] : _c.edges[entry]) {
            if (k == candidate) {
                return inAncestry;
            }
        }
        return false;
    }

    void use(int entry, int candidate)
    {
        if (_users[candidate].empty()) {
            for (int element : _c.elements[candidate]) {
                _elementUser[element] = candidate;
            }
        }
        _users[candidate].push_back(entry);
        _assigned[entry] = candidate;
    }

    void release(int entry, int candidate)
    {
        _users[candidate].pop_back();
        if (_users[candidate].empty()) {
            for (int element : _c.elements[candidate]) {
                _elementUser.erase(element);
            }
        }
        _assigned[entry] = -1;
    }

    void record(int size)
    {
        if (size > _best) {
            _best = size;
            std::fill(_seen.begin(), _seen.end(), -2);
            std::fill(_ambiguous.begin(), _ambiguous.end(), 0);
        }
        for (std::size_t e = 0; e < _assigned.size(); ++e) {
            if (_seen[e] == -2) {
                _seen[e] = _assigned[e];
            }
            else if (_seen[e] != _assigned[e]) {
                _ambiguous[e] = 1;
            }
        }
    }

    void search(std::size_t entry, int size)
    {
        if (_aborted || ++_steps > _maxSteps) {
            _aborted = true;
            return;
        }
        int remaining = static_cast<int>(_assigned.size() - entry);
        if (size + remaining < _best) {
            return;
        }
        if (entry == _assigned.size()) {
            record(size);
            return;
        }
        int e = static_cast<int>(entry);
        for (const auto& [candidate, inAncestry] : _c.edges[entry]) {
            if (canUse(candidate, inAncestry)) {
                use(e, candidate);
                search(entry + 1, size + 1);
                release(e, candidate);
            }
        }
        search(entry + 1, size);
    }

    const Component& _c;
    long _maxSteps;
    long _steps = 0;
    bool _aborted = false;
    int _best = -1;
    std::vector<int> _assigned;
    std::vector<std::vector<int>> _users;
    std::map<int, int> _elementUser;
    std::vector<int> _seen;  // per entry: its partner in the maximum matchings so far, -2 none yet
    std::vector<char> _ambiguous;
};

}  // namespace

MatchResult forcedMatching(const MatchGraph& graph, int maxMerges, long maxSteps)
{
    const int entryCount = graph.entryCount;
    const int candidateCount = static_cast<int>(graph.candidates.size());
    if (entryCount < 0) {
        throw Base::ValueError("forcedMatching: negative entry count");
    }

    // Edges, deduplicated; a duplicate with inAncestry set keeps it.
    std::map<std::pair<int, int>, bool> edges;
    for (const auto& edge : graph.edges) {
        if (edge.entry < 0 || edge.entry >= entryCount || edge.candidate < 0
            || edge.candidate >= candidateCount) {
            throw Base::ValueError("forcedMatching: edge index out of range");
        }
        edges[{edge.entry, edge.candidate}] |= edge.inAncestry;
    }

    // Components over entries [0, entryCount) and candidates [entryCount, ...), joined by edges
    // and by shared elements. Candidates without edges take no part.
    std::vector<char> used(static_cast<std::size_t>(candidateCount), 0);
    UnionFind sets(entryCount + candidateCount);
    for (const auto& [key, inAncestry] : edges) {
        sets.unite(key.first, entryCount + key.second);
        used[key.second] = 1;
    }
    std::vector<std::vector<int>> elements(static_cast<std::size_t>(candidateCount));
    std::map<int, int> firstWithElement;
    for (int k = 0; k < candidateCount; ++k) {
        auto& list = elements[k];
        list = graph.candidates[k].elements;
        std::sort(list.begin(), list.end());
        list.erase(std::unique(list.begin(), list.end()), list.end());
        if (!used[k]) {
            continue;
        }
        for (int element : list) {
            auto [it, inserted] = firstWithElement.emplace(element, k);
            if (!inserted) {
                sets.unite(entryCount + it->second, entryCount + k);
            }
        }
    }
    MatchResult result;
    result.partner.assign(static_cast<std::size_t>(entryCount), -1);
    result.status.assign(static_cast<std::size_t>(entryCount), MatchStatus::NoCandidate);

    // Components by their root, in increasing order of the root (the lowest node index).
    std::map<int, Component> components;
    std::vector<int> localIndex(static_cast<std::size_t>(entryCount + candidateCount), -1);
    for (int e = 0; e < entryCount; ++e) {
        auto& c = components[sets.find(e)];
        localIndex[e] = static_cast<int>(c.entries.size());
        c.entries.push_back(e);
        c.edges.emplace_back();
    }
    for (int k = 0; k < candidateCount; ++k) {
        if (!used[k]) {
            continue;
        }
        auto& c = components[sets.find(entryCount + k)];
        localIndex[entryCount + k] = static_cast<int>(c.candidates.size());
        c.candidates.push_back(k);
        c.elements.push_back(elements[k]);
        c.ancestral.push_back(0);
    }
    for (const auto& [key, inAncestry] : edges) {
        auto& c = components[sets.find(key.first)];
        int localEntry = localIndex[key.first];
        int localCandidate = localIndex[entryCount + key.second];
        c.edges[localEntry].emplace_back(localCandidate, inAncestry);
        if (inAncestry) {
            ++c.ancestral[localCandidate];
        }
    }

    for (auto& [root, c] : components) {
        if (c.candidates.empty()) {
            continue;  // lone entries without candidates
        }
        for (auto& list : c.edges) {
            std::sort(list.begin(), list.end());
        }
        bool sharesElements = false;
        std::map<int, int> count;
        for (const auto& list : c.elements) {
            for (int element : list) {
                sharesElements = sharesElements || ++count[element] > 1;
            }
        }
        ComponentResult solved = sharesElements ? ExhaustiveSearch(c, maxSteps).run()
                                                : solveByAugmenting(c, maxMerges);
        for (std::size_t e = 0; e < c.entries.size(); ++e) {
            int global = c.entries[e];
            if (c.edges[e].empty()) {
                continue;  // NoCandidate
            }
            result.status[global] = solved.status[e];
            result.partner[global] = solved.partner[e] >= 0 ? c.candidates[solved.partner[e]] : -1;
        }
    }
    return result;
}

// ---------------------------------------------------------------------------------------------
// groupEquivalent

std::vector<std::vector<int>> groupEquivalent(
    const std::vector<std::string>& names,
    const std::function<bool(int, int)>& equivalent
)
{
    const int count = static_cast<int>(names.size());
    UnionFind sets(count);
    std::vector<char> pair(static_cast<std::size_t>(count) * count, 0);
    for (int i = 0; i < count; ++i) {
        for (int j = i + 1; j < count; ++j) {
            if (equivalent(i, j)) {
                pair[static_cast<std::size_t>(i) * count + j] = 1;
                sets.unite(i, j);
            }
        }
    }

    std::map<int, std::vector<int>> components;
    for (int i = 0; i < count; ++i) {
        components[sets.find(i)].push_back(i);
    }

    auto byName = [&names](int a, int b) {
        return names[a] != names[b] ? names[a] < names[b] : a < b;
    };
    std::vector<std::vector<int>> groups;
    for (auto& [root, members] : components) {
        bool clique = true;
        for (std::size_t a = 0; clique && a < members.size(); ++a) {
            for (std::size_t b = a + 1; clique && b < members.size(); ++b) {
                // members are in increasing index order
                clique = pair[static_cast<std::size_t>(members[a]) * count + members[b]] != 0;
            }
        }
        if (clique) {
            std::sort(members.begin(), members.end(), byName);
            groups.push_back(std::move(members));
        }
        else {
            for (int member : members) {
                groups.push_back({member});
            }
        }
    }
    std::sort(groups.begin(), groups.end(), [&](const auto& a, const auto& b) {
        return byName(a.front(), b.front());
    });
    return groups;
}

// ---------------------------------------------------------------------------------------------
// solveOwner

namespace
{

// The number at the end of an index name (`Face12` -> 12), or -1.
long indexNumber(const std::string& index)
{
    std::size_t pos = index.size();
    while (pos > 0 && index[pos - 1] >= '0' && index[pos - 1] <= '9') {
        --pos;
    }
    if (pos == index.size() || index.size() - pos > 9) {
        return -1;
    }
    return std::stol(index.substr(pos));
}

bool byIndex(const SolveInput::Element& a, const SolveInput::Element& b)
{
    long na = indexNumber(a.index);
    long nb = indexNumber(b.index);
    return na != nb ? na < nb : a.index < b.index;
}

std::string formatOverlap(double value)
{
    std::ostringstream ss;
    ss.imbue(std::locale::classic());
    ss.precision(2);
    ss << std::fixed << value;
    return ss.str();
}

/* True if \a a and \a b are the same name up to the duplicate counter of any section, at any
 * depth: the sections of the embedded Linked and Connected Names are compared the same way, so a
 * face built on instance 1's edges and one built on instance 2's are equal up to the counter.
 * Both forms of the counter are ignored, as harness.py's withoutCounter() does: the duplicate
 * count field, and a counter written over the op code, which then matches any op code. So is the
 * instance number of a pattern instance's TRF section: two instances of one pattern are siblings.
 * A section that doesn't decode must be equal as text.
 */
bool sameUpToCounter(std::string_view a, std::string_view b)
{
    if (a == b) {
        return true;
    }
    auto sectionsA = NameAncestry::splitSections(a);
    auto sectionsB = NameAncestry::splitSections(b);
    if (sectionsA.empty() || sectionsA.size() != sectionsB.size()) {
        return false;
    }
    for (std::size_t i = 0; i < sectionsA.size(); ++i) {
        if (sectionsA[i] == sectionsB[i]) {
            continue;
        }
        // Copies: the recursion below decodes more names.
        DecodedMappedName decodedA = MappedName::getDecodedMappedName(std::string(sectionsA[i]));
        DecodedMappedName decodedB = MappedName::getDecodedMappedName(std::string(sectionsB[i]));
        if (decodedA.size() != 1 || decodedB.size() != 1) {
            return false;
        }
        const DecodedMappedSection& x = decodedA.front();
        const DecodedMappedSection& y = decodedB.front();
        bool opCodesAgree = x.opCode == y.opCode || isCounterOpCode(x.opCode)
            || isCounterOpCode(y.opCode);
        // The copies of an element in two instances of one pattern are siblings: the instance
        // number in a TRF section's index counts as a counter here (ops#55).
        bool instanceSections
            = x.opCode == patternInstanceOpCode && y.opCode == patternInstanceOpCode;
        if (!opCodesAgree || x.referenceIDs != y.referenceIDs || x.iterationTag != y.iterationTag
            || (x.index != y.index && !instanceSections) || x.elementType != y.elementType
            || x.mapperFlags != y.mapperFlags || x.linkedNames.size() != y.linkedNames.size()
            || x.connectedElements.size() != y.connectedElements.size()) {
            return false;
        }
        for (std::size_t j = 0; j < x.linkedNames.size(); ++j) {
            if (!sameUpToCounter(x.linkedNames[j], y.linkedNames[j])) {
                return false;
            }
        }
        for (std::size_t j = 0; j < x.connectedElements.size(); ++j) {
            if (!sameUpToCounter(x.connectedElements[j], y.connectedElements[j])) {
                return false;
            }
        }
    }
    return true;
}

/* True if \a name is \a oldName up to the duplicate counter (sameUpToCounter()), and not
 * \a oldName itself: a pattern instance's copy of the old element, or another element the
 * element map told apart only by the counter.
 */
bool isCounterSibling(std::string_view name, std::string_view oldName)
{
    return name != oldName && sameUpToCounter(name, oldName);
}

// The element of a target without an element map that the IDX section \a section names, when it
// carries the target's tag \a tag (Q5): the section's index name (`Edge11`), if it is of type
// \a type; otherwise empty.
std::string maplessElement(
    std::string_view section,
    const std::string& tag,
    const std::string& type
)
{
    if (tag.empty() || section.empty()) {
        return {};
    }
    const auto& decoded = decodeSection(section);
    if (decoded.iterationTag != tag || decoded.referenceIDs.size() != 1) {
        return {};
    }
    const std::string& index = decoded.referenceIDs.front();
    std::size_t end = index.size();
    while (end > 0 && index[end - 1] >= '0' && index[end - 1] <= '9') {
        --end;
    }
    if (end == index.size() || end != type.size() || index.compare(0, end, type) != 0) {
        return {};
    }
    return index;
}

std::string formatDistance(double value)
{
    std::ostringstream ss;
    ss.imbue(std::locale::classic());
    ss.precision(3);
    ss << std::fixed << value;
    return ss.str();
}

bool relativelyEqual(double a, double b, double tolerance)
{
    return std::abs(a - b) <= tolerance * std::max({std::abs(a), std::abs(b), 1e-12});
}

struct Nearest
{
    int index = -1;
    double nearest = 0.0;
    double second = -1.0;  // -1: no other candidate
    double dMax = 0.0;
};

Nearest findNearest(
    const ElementFingerprint& saved,
    const std::vector<ElementFingerprint>& candidates,
    double diagonal,
    const GeometryTolerances& tolerances
)
{
    Nearest result;
    result.dMax = tolerances.distance * diagonal;
    if (!saved.center || !(diagonal > 0.0)) {
        return result;
    }
    int best = -1;
    double bestDistance = 0.0;
    double secondDistance = -1.0;
    for (std::size_t i = 0; i < candidates.size(); ++i) {
        if (!candidates[i].center) {
            continue;
        }
        double distance = Base::Distance(*saved.center, *candidates[i].center);
        if (best < 0 || distance < bestDistance) {
            secondDistance = best < 0 ? secondDistance : bestDistance;
            best = static_cast<int>(i);
            bestDistance = distance;
        }
        else if (secondDistance < 0.0 || distance < secondDistance) {
            secondDistance = distance;
        }
    }
    result.nearest = bestDistance;
    result.second = secondDistance;
    if (best < 0 || bestDistance > result.dMax) {
        return result;
    }
    if (secondDistance >= 0.0
        && (secondDistance < tolerances.gapFactor * bestDistance || secondDistance < result.dMax)) {
        return result;
    }
    const auto& candidate = candidates[best];
    if (saved.size.has_value() != candidate.size.has_value()
        || (saved.size && !relativelyEqual(*saved.size, *candidate.size, tolerances.size))) {
        return result;
    }
    result.index = best;
    return result;
}

std::string describeNearest(const Nearest& nearest)
{
    std::string text = "nearest " + formatDistance(nearest.nearest);
    if (nearest.second >= 0.0) {
        text += ", second " + formatDistance(nearest.second);
    }
    return text + ", d_max " + formatDistance(nearest.dMax);
}

// The angle between two directions, either sense, as intrinsicAgrees() measures it.
double lineAngle(Base::Vector3d a, Base::Vector3d b)
{
    a.Normalize();
    b.Normalize();
    return std::atan2((a % b).Length(), std::abs(a * b));
}

constexpr double Pi = 3.14159265358979323846;

/* Where an edge was, from the fingerprint saved with its reference (the continuation, Task 2 PR
 * 7): an extent of arc length [0, length] along the old curve, a line or (PR 7b) a circle. A
 * piece of the target lies on the old curve when interval() gives its extent there; everything
 * after that (containment, a run-past, the overlap check) compares intervals.
 */
struct OldExtent
{
    bool circle = false;
    // A line: from origin along the unit direction axis. A circle: centre origin, unit axis,
    // radius, and arc length s = radius * (theta + alpha), theta being the angle from the old
    // arc's bisector towards axis x bisector, alpha half the old arc's angle.
    Base::Vector3d origin;
    Base::Vector3d axis;
    Base::Vector3d bisector;
    double radius = 0.0;
    double alpha = 0.0;
    double length = 0.0;
    // A full circle: intervals wrap at length, and s starts opposite the hit's middle.
    bool cyclic = false;
    double eps = 0.0;
    double angle = 0.0;

    // \a hit, the exact element, places a full circle's start of s.
    static std::optional<OldExtent> of(
        const ElementFingerprint& saved,
        double eps,
        const GeometryTolerances& tolerances,
        const ElementFingerprint* hit = nullptr
    )
    {
        if (!saved.isValid() || saved.type != 'E' || !saved.size || !saved.center
            || !saved.direction || saved.direction->Length() <= 0.0 || !(*saved.size > eps)) {
            return std::nullopt;
        }
        OldExtent extent;
        extent.axis = *saved.direction;
        extent.axis.Normalize();
        extent.length = *saved.size;
        extent.eps = eps;
        extent.angle = tolerances.angle;
        if (saved.kind == "Line") {
            // A line edge's centre of mass is its midpoint.
            extent.origin = *saved.center - extent.axis * (extent.length / 2.0);
            return extent;
        }
        if (saved.kind != "Circle" || !saved.location || saved.radii.size() != 1
            || !(saved.radii.front() > eps)) {
            return std::nullopt;  // another curve, or a version-1 circle: not locatable
        }
        extent.circle = true;
        extent.origin = *saved.location;
        extent.radius = saved.radii.front();
        const double full = 2.0 * Pi * extent.radius;
        if (extent.length >= full - eps) {
            // A full circle: s starts opposite the hit's middle, so the hit is one interval.
            // Without a hit that shows one (a collapse checks containment only), any start does.
            extent.cyclic = true;
            extent.length = full;
            extent.alpha = Pi;
            Base::Vector3d toward;
            if (hit && hit->center) {
                toward = extent.inPlane(*hit->center - extent.origin);
            }
            if (toward.Length() < 1e-6 * extent.radius) {
                toward = extent.inPlane(std::abs(extent.axis.x) < 0.9 ? Base::Vector3d(1, 0, 0)
                                                                      : Base::Vector3d(0, 1, 0));
            }
            extent.bisector = toward;
            extent.bisector.Normalize();
            return extent;
        }
        // The centre of mass lies on the arc's bisector, r sin(alpha) / alpha from the centre.
        extent.alpha = extent.length / (2.0 * extent.radius);
        Base::Vector3d toward = extent.inPlane(*saved.center - extent.origin);
        if (toward.Length() < 1e-6 * extent.radius) {
            // Nearly a full circle: its bisector isn't reliable.
            return std::nullopt;
        }
        extent.bisector = toward;
        extent.bisector.Normalize();
        return extent;
    }

    Base::Vector3d inPlane(const Base::Vector3d& v) const
    {
        return v - axis * (v * axis);
    }

    // The piece's extent along the old curve, sorted; nothing if it doesn't lie on that curve. A
    // line: the same direction within the angle, both ends within eps of the line. A circle: a
    // circle of the same axis (within the angle), radius, centre and plane (within eps).
    std::optional<std::pair<double, double>> interval(const ElementFingerprint& piece) const
    {
        if (!piece.isValid() || piece.type != 'E' || !piece.size || !piece.center
            || !piece.direction || piece.direction->Length() <= 0.0
            || lineAngle(axis, *piece.direction) > angle) {
            return std::nullopt;
        }
        if (circle) {
            return arcInterval(piece);
        }
        if (piece.kind != "Line") {
            return std::nullopt;
        }
        Base::Vector3d direction = *piece.direction;
        direction.Normalize();
        std::pair<double, double> range;
        for (int end = 0; end < 2; ++end) {
            Base::Vector3d point = *piece.center
                + direction * ((end == 0 ? -0.5 : 0.5) * *piece.size);
            Base::Vector3d offset = point - origin;
            double t = offset * axis;
            if ((offset - axis * t).Length() > eps) {
                return std::nullopt;
            }
            (end == 0 ? range.first : range.second) = t;
        }
        if (range.first > range.second) {
            std::swap(range.first, range.second);
        }
        return range;
    }

    std::optional<std::pair<double, double>> arcInterval(const ElementFingerprint& piece) const
    {
        if (piece.kind != "Circle" || !piece.location || piece.radii.size() != 1
            || std::abs(piece.radii.front() - radius) > eps
            || Base::Distance(*piece.location, origin) > eps) {
            return std::nullopt;
        }
        Base::Vector3d offset = *piece.center - origin;
        if (std::abs(offset * axis) > eps) {
            return std::nullopt;
        }
        const double full = 2.0 * Pi * radius;
        Base::Vector3d toward = inPlane(offset);
        if (toward.Length() < 1e-6 * radius) {
            // A whole circle, or nearly: all of it.
            return std::make_pair(radius * (alpha - Pi), radius * (alpha + Pi));
        }
        const double half = *piece.size / (2.0 * radius);
        const double beta = std::atan2(toward * (axis % bisector), toward * bisector);
        std::pair<double, double> range {radius * (beta - half + alpha),
                                         radius * (beta + half + alpha)};
        if (cyclic) {
            // Starting within one turn; it may end past length (wrapping).
            double shift = std::floor(range.first / full) * full;
            range.first -= shift;
            range.second -= shift;
            return range;
        }
        // The turn that overlaps the old arc most.
        std::pair<double, double> best = range;
        for (double shift : {-full, full}) {
            std::pair<double, double> moved {range.first + shift, range.second + shift};
            if (overlap(moved) > overlap(best)) {
                best = moved;
            }
        }
        return best;
    }

    bool within(const std::pair<double, double>& range) const
    {
        if (cyclic) {
            return range.second - range.first <= length + eps;
        }
        return range.first >= -eps && range.second <= length + eps;
    }

    // The length the range shares with [0, length].
    double overlap(const std::pair<double, double>& range) const
    {
        if (cyclic) {
            return std::min(range.second - range.first, length);
        }
        return std::min(range.second, length) - std::max(range.first, 0.0);
    }

    // Whether two of \a ranges (the pieces of one edge) overlap by more than eps.
    bool overlapping(std::vector<std::pair<double, double>> ranges) const
    {
        std::sort(ranges.begin(), ranges.end());
        for (std::size_t r = 1; r < ranges.size(); ++r) {
            if (ranges[r - 1].second - ranges[r].first > eps) {
                return true;
            }
        }
        // Around a full circle, the last piece may wrap onto the first.
        return cyclic && !ranges.empty()
            && ranges.back().second - length - ranges.front().first > eps;
    }
};

}  // namespace

bool hitWithinOldEdge(
    const ElementFingerprint& saved,
    const ElementFingerprint& now,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    const double eps = distance * std::max(1.0, diagonal);
    auto extent = OldExtent::of(saved, eps, tolerances, &now);
    if (!extent) {
        return false;
    }
    auto range = extent->interval(now);
    return range && extent->within(*range)
        && range->second - range->first < extent->length - eps;
}

namespace
{

bool isPlane(const ElementFingerprint& fp)
{
    return fp.isValid() && fp.type == 'F' && fp.kind == "Plane" && fp.size && fp.center
        && fp.direction && fp.direction->Length() > 0.0;
}

}  // namespace

bool planeAgrees(
    const ElementFingerprint& saved,
    const ElementFingerprint& face,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    if (!isPlane(saved) || !isPlane(face)) {
        return false;
    }
    Base::Vector3d normal = *saved.direction;
    Base::Vector3d other = *face.direction;
    normal.Normalize();
    other.Normalize();
    // A plane's normal keeps its sense: a face of the opposite side isn't in this plane.
    if (std::atan2((normal % other).Length(), normal * other) > tolerances.angle) {
        return false;
    }
    const double eps = distance * std::max(1.0, diagonal);
    return std::abs((*face.center - *saved.center) * normal) <= eps;
}

ExtentRelation faceExtentRelation(
    const ElementFingerprint& saved,
    const ElementFingerprint& face,
    double diagonal,
    double distance
)
{
    if (!saved.extentMin || !saved.extentMax || !face.extentMin || !face.extentMax) {
        return ExtentRelation::Unknown;
    }
    const double eps = distance * std::max(1.0, diagonal);
    bool inside = true;
    for (int axis = 0; axis < 3; ++axis) {
        const double oldLow = (*saved.extentMin)[axis];
        const double oldHigh = (*saved.extentMax)[axis];
        const double low = (*face.extentMin)[axis];
        const double high = (*face.extentMax)[axis];
        const double overlap = std::min(oldHigh, high) - std::max(oldLow, low);
        if (overlap < -eps || (overlap <= eps && oldHigh - oldLow > eps && high - low > eps)) {
            return ExtentRelation::Outside;
        }
        if (low < oldLow - eps || high > oldHigh + eps) {
            inside = false;
        }
    }
    return inside ? ExtentRelation::Inside : ExtentRelation::Overlapping;
}

bool faceWithinOldPlane(
    const ElementFingerprint& saved,
    const ElementFingerprint& now,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    return planeAgrees(saved, now, diagonal, tolerances, distance)
        && *now.size < *saved.size * (1.0 - distance);
}

bool intrinsicAgrees(
    const ElementFingerprint& saved,
    const ElementFingerprint& candidate,
    const GeometryTolerances& tolerances
)
{
    if (!saved.isValid() || !candidate.isValid() || saved.type != candidate.type
        || saved.kind != candidate.kind) {
        return false;
    }
    if (saved.direction.has_value() != candidate.direction.has_value()) {
        return false;
    }
    if (saved.direction) {
        Base::Vector3d a = *saved.direction;
        Base::Vector3d b = *candidate.direction;
        if (a.Length() <= 0.0 || b.Length() <= 0.0) {
            return false;
        }
        a.Normalize();
        b.Normalize();
        double cosine = a * b;
        // A plane's normal carries the face's orientation; an axis or a line has no sense (the
        // producer normalizes its sign, which a component near 0 can flip).
        if (!(saved.type == 'F' && saved.kind == "Plane")) {
            cosine = std::abs(cosine);
        }
        // The angle from the cross product: acos loses precision near 0.
        double angle = std::atan2((a % b).Length(), cosine);
        if (angle > tolerances.angle) {
            return false;
        }
    }
    if (saved.radii.size() != candidate.radii.size()) {
        return false;
    }
    for (std::size_t i = 0; i < saved.radii.size(); ++i) {
        if (!relativelyEqual(saved.radii[i], candidate.radii[i], tolerances.radius)) {
            return false;
        }
    }
    return true;
}

bool atSamePlace(
    const ElementFingerprint& saved,
    const ElementFingerprint& now,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    // The kind, direction and radii as tier 2 compares them.
    if (!intrinsicAgrees(saved, now, tolerances)) {
        return false;
    }
    const double eps = distance * std::max(1.0, diagonal);
    if (saved.size.has_value() != now.size.has_value()
        || (saved.size
            && std::abs(*saved.size - *now.size)
                > tolerances.placeSize
                    * std::max({std::abs(*saved.size), std::abs(*now.size), eps}))) {
        return false;
    }
    if (saved.center.has_value() != now.center.has_value()
        || (saved.center && Base::Distance(*saved.center, *now.center) > eps)) {
        return false;
    }
    if (saved.location && now.location && Base::Distance(*saved.location, *now.location) > eps) {
        return false;
    }
    if (saved.extentMin && saved.extentMax && now.extentMin && now.extentMax
        && (Base::Distance(*saved.extentMin, *now.extentMin) > eps
            || Base::Distance(*saved.extentMax, *now.extentMax) > eps)) {
        return false;
    }
    return true;
}

bool mayBeAtPlace(
    const ElementFingerprint& saved,
    const ElementFingerprint& intrinsic,
    const std::optional<Base::Vector3d>& anchor,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    // What atSamePlace() compares first, measured the same way.
    if (!intrinsicAgrees(saved, intrinsic, tolerances)) {
        return false;
    }
    const double eps = distance * std::max(1.0, diagonal);
    if (saved.location && intrinsic.location
        && Base::Distance(*saved.location, *intrinsic.location) > eps) {
        return false;
    }
    if (!anchor || !saved.center) {
        return true;
    }
    // The element's centre lies on its vertex, line or plane, and atSamePlace() wants the saved
    // centre within eps of it: 2 eps leaves room for the centre's integration.
    const Base::Vector3d offset = *saved.center - *anchor;
    if (saved.type == 'V') {
        return offset.Length() <= 2 * eps;
    }
    if (!intrinsic.direction || intrinsic.direction->Length() <= 0.0) {
        return true;
    }
    Base::Vector3d axis = *intrinsic.direction;
    axis.Normalize();
    if (saved.type == 'F' && saved.kind == "Plane") {
        return std::abs(offset * axis) <= 2 * eps;
    }
    if (saved.type == 'E' && saved.kind == "Line") {
        return (offset - axis * (offset * axis)).Length() <= 2 * eps;
    }
    return true;
}

int extrinsicNearest(
    const ElementFingerprint& saved,
    const std::vector<ElementFingerprint>& candidates,
    double diagonal,
    const GeometryTolerances& tolerances
)
{
    return findNearest(saved, candidates, diagonal, tolerances).index;
}

std::vector<SolveOutcome> solveOwner(const SolveInput& input)
{
    NameAncestry ancestry(input.measure);
    std::vector<SolveOutcome> outcomes(input.entries.size());

    // Pools in index order, names sorted by bytes, duplicates merged; a dense element ID over
    // all types for the graph.
    struct Pool
    {
        std::vector<SolveInput::Element> elements;
        std::vector<int> ids;
        std::map<std::string, int> byName;  // name -> position in elements
        std::set<std::string> exact;        // index names resolved at tier 0
    };
    std::map<std::string, Pool> pools;
    std::vector<std::pair<std::string, int>> elementOfId;  // ID -> (type, position)
    std::map<std::string, std::map<std::string, std::vector<std::string>>> mergedByType;
    for (const auto& [type, elements] : input.pool) {
        auto& merged = mergedByType[type];
        for (const auto& element : elements) {
            auto& names = merged[element.index];
            names.insert(names.end(), element.names.begin(), element.names.end());
        }
    }
    // A target without an element map: the elements its IDX names point to, without names (Q5).
    for (const auto& entry : input.entries) {
        if (entry.exact) {
            continue;
        }
        std::string index = maplessElement(NameAncestry::indexSource(entry.oldName),
                                           input.maplessTag,
                                           entry.type);
        if (!index.empty()) {
            mergedByType[entry.type][index];
        }
    }
    for (auto& [type, merged] : mergedByType) {
        Pool& pool = pools[type];
        for (auto& [index, names] : merged) {
            std::sort(names.begin(), names.end());
            names.erase(std::unique(names.begin(), names.end()), names.end());
            pool.elements.push_back({index, std::move(names)});
        }
        std::sort(pool.elements.begin(), pool.elements.end(), byIndex);
        for (std::size_t k = 0; k < pool.elements.size(); ++k) {
            pool.ids.push_back(static_cast<int>(elementOfId.size()));
            elementOfId.emplace_back(type, static_cast<int>(k));
            for (const auto& name : pool.elements[k].names) {
                // A name names one element; keep the first by index if a map is inconsistent.
                pool.byName.emplace(name, static_cast<int>(k));
            }
        }
    }

    auto firstName = [](const SolveInput::Element& element) {
        return element.names.empty() ? std::string() : element.names.front();
    };

    // The pool elements' current fingerprints, measured on first use.
    std::map<std::string, ElementFingerprint> measured;
    auto fingerprintOfIndex = [&](const std::string& index) -> const ElementFingerprint& {
        auto it = measured.find(index);
        if (it == measured.end()) {
            ElementFingerprint fingerprint;
            if (input.fingerprintOf) {
                fingerprint = input.fingerprintOf(index);
            }
            it = measured.emplace(index, std::move(fingerprint)).first;
        }
        return it->second;
    };
    auto fingerprintOf = [&](const SolveInput::Element& element) -> const ElementFingerprint& {
        return fingerprintOfIndex(element.index);
    };
    auto positionOf = [](const Pool& pool, const std::string& index) {
        for (std::size_t k = 0; k < pool.elements.size(); ++k) {
            if (pool.elements[k].index == index) {
                return static_cast<int>(k);
            }
        }
        return -1;
    };

    // Tier 0.
    for (std::size_t i = 0; i < input.entries.size(); ++i) {
        const auto& entry = input.entries[i];
        if (!entry.exact) {
            continue;
        }
        auto& outcome = outcomes[i];
        outcome.status = SolveStatus::Exact;
        outcome.tier = 0;
        outcome.element = entry.exactElement;
        pools[entry.type].exact.insert(entry.exactElement);
        auto& pool = pools[entry.type];
        for (const auto& element : pool.elements) {
            if (element.index == entry.exactElement) {
                outcome.name = firstName(element);
            }
        }
    }

    // Entries decided before the graph: moved, collapsing and continued exact entries.
    std::vector<char> decidedEntry(input.entries.size(), 0);
    const double nan = std::numeric_limits<double>::quiet_NaN();

    // Moved (ops#105): an exact element that no longer sits where its saved fingerprint was,
    // while another element of its type sits there now. The name says one, the geometry the
    // other: never a pick. Moved alone (nothing at the old place), the name stands.
    {
        std::map<std::string, std::set<std::string>> reserved;  // by type: the places taken
        struct Hint
        {
            bool valid = false;
            ElementFingerprint intrinsic;
            std::optional<Base::Vector3d> anchor;
        };
        std::map<std::string, Hint> hints;  // by index, on first use
        for (std::size_t i = 0; i < input.entries.size(); ++i) {
            const auto& entry = input.entries[i];
            const ElementFingerprint& saved = entry.fingerprint;
            if (!entry.exact || !saved.isValid()) {
                continue;
            }
            Pool& pool = pools[entry.type];
            const std::string& hit = entry.exactElement;
            const int hitPosition = positionOf(pool, hit);
            auto here = [&](const ElementFingerprint& now) {
                return atSamePlace(saved,
                                   now,
                                   input.diagonal,
                                   input.tolerances,
                                   input.continuationDistance);
            };
            const ElementFingerprint& now = fingerprintOfIndex(hit);
            if (hitPosition < 0 || !now.isValid() || here(now)) {
                continue;  // unmoved, or nothing to compare
            }
            // The elements there: a cheap hint first rules most out, so that only the rest are
            // fingerprinted.
            auto mayBeHere = [&](const std::string& index) {
                if (!input.hintOf) {
                    return true;
                }
                auto it = hints.find(index);
                if (it == hints.end()) {
                    Hint hint;
                    hint.valid = input.hintOf(index, hint.intrinsic, hint.anchor);
                    it = hints.emplace(index, std::move(hint)).first;
                }
                const Hint& hint = it->second;
                return !hint.valid
                    || mayBeAtPlace(saved,
                                    hint.intrinsic,
                                    hint.anchor,
                                    input.diagonal,
                                    input.tolerances,
                                    input.continuationDistance);
            };
            std::vector<int> place;
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& index = pool.elements[k].index;
                if (static_cast<int>(k) != hitPosition && mayBeHere(index)
                    && here(fingerprintOfIndex(index))) {
                    place.push_back(static_cast<int>(k));
                }
            }
            if (place.empty()) {
                continue;  // moved alone
            }
            if (entry.policy == SolvePolicy::Equivalent && entry.equivalent
                && std::all_of(place.begin(), place.end(), [&](int k) {
                       return entry.equivalent(hit, pool.elements[k].index);
                   })) {
                // Every element there gives the consumer the hit's result: the entry is exact,
                // as if unmoved, and reserves nothing.
                continue;
            }
            decidedEntry[i] = 1;
            for (int k : place) {
                reserved[entry.type].insert(pool.elements[k].index);
            }
            auto distanceOf = [&](const ElementFingerprint& fp) {
                return saved.center && fp.center ? Base::Distance(*saved.center, *fp.center) : nan;
            };
            auto& outcome = outcomes[i];
            outcome = SolveOutcome();
            std::string there;
            auto list = [&](int k, const char* role) {
                const auto& element = pool.elements[k];
                outcome.candidates.push_back(element.index);
                outcome.candidateNames.push_back(firstName(element));
                outcome.candidateRoles.emplace_back(role);
                outcome.candidateDistances.push_back(distanceOf(fingerprintOf(element)));
            };
            for (int k : place) {
                list(k, "place");
                there += (there.empty() ? "" : ", ") + pool.elements[k].index;
            }
            list(hitPosition, "name");
            const double moved = distanceOf(now);
            const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
            outcome.evidence = (std::isnan(moved) || moved <= eps
                                    ? std::string("changed")
                                    : "moved " + formatDistance(moved) + " mm")
                + "; " + there + (place.size() > 1 ? " sit" : " sits") + " where it was";
        }
        // The elements at an old place are as ambiguous as the moved one: no other entry of the
        // owner takes them.
        for (const auto& [type, indexes] : reserved) {
            pools[type].exact.insert(indexes.begin(), indexes.end());
        }
    }

    // Collapse: a group of references expanded from one name (the same scope and `from`) merges
    // back when that name is found exactly and no member holds another element.
    std::map<std::pair<std::string, std::string>, std::vector<int>> fromGroups;
    for (std::size_t i = 0; i < input.entries.size(); ++i) {
        const auto& entry = input.entries[i];
        if (!entry.from.empty()) {
            fromGroups[{entry.scope, entry.from}].push_back(static_cast<int>(i));
        }
    }
    for (const auto& [key, members] : fromGroups) {
        const std::string& type = input.entries[members.front()].type;
        if (std::any_of(members.begin(), members.end(), [&](int i) {
                return input.entries[i].type != type || decidedEntry[i];
            })) {
            continue;
        }
        Pool& pool = pools[type];
        auto found = pool.byName.find(key.second);
        if (found == pool.byName.end()) {
            continue;
        }
        const auto& element = pool.elements[found->second];
        // A missing member merged back only if it is a structural piece of the `from` element,
        // or its saved geometry lies on that element as it is now (a continuation that the
        // element covers again). A member gone elsewhere (its line redrawn with a new ID) is
        // solved on its own.
        const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
        const ElementFingerprint& now = fingerprintOfIndex(element.index);
        auto extent = OldExtent::of(now, eps, input.tolerances);
        auto mergedBack = [&](const SolveInput::Entry& entry) {
            if (NameAncestry::isPieceOf(entry.oldName, key.second)
                || NameAncestry::isIndexPieceOf(entry.oldName, key.second)) {
                return true;
            }
            auto range = extent ? extent->interval(entry.fingerprint) : std::nullopt;
            return range && extent->within(*range);
        };
        bool merged = std::all_of(members.begin(), members.end(), [&](int i) {
            const auto& entry = input.entries[i];
            return entry.exact ? entry.exactElement == element.index : mergedBack(entry);
        });
        if (!merged) {
            continue;
        }
        int keep = *std::min_element(members.begin(), members.end(), [&](int a, int b) {
            return input.entries[a].position < input.entries[b].position;
        });
        for (int i : members) {
            auto& outcome = outcomes[i];
            outcome = SolveOutcome();
            outcome.element = element.index;
            outcome.name = firstName(element);
            if (i == keep) {
                outcome.status = SolveStatus::Resolved;
                outcome.tier = 0;
                outcome.collapsed = true;
                outcome.evidence = "pieces merged back: " + key.second + " found exactly";
            }
            else {
                outcome.status = SolveStatus::Removed;
                outcome.evidence = "pieces merged back";
            }
            decidedEntry[i] = 1;
        }
        pool.exact.insert(element.index);
    }

    // Continuation: an exact line edge that is now a strict part of the edge its fingerprint
    // was saved for, and the other line edges on the old edge that bound a face it bounds.
    {
        const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
        Pool& pool = pools["Edge"];
        const std::set<std::string> held = pool.exact;  // before any continuation is taken
        std::map<std::string, std::set<std::string>> facesByEdge;
        auto facesOf = [&](const std::string& index) -> const std::set<std::string>& {
            auto it = facesByEdge.find(index);
            if (it == facesByEdge.end()) {
                std::set<std::string> faces;
                if (input.facesOf) {
                    for (auto& face : input.facesOf(index)) {
                        faces.insert(std::move(face));
                    }
                }
                it = facesByEdge.emplace(index, std::move(faces)).first;
            }
            return it->second;
        };
        std::vector<int> taken;
        for (std::size_t i = 0; i < input.entries.size(); ++i) {
            const auto& entry = input.entries[i];
            if (!entry.exact || decidedEntry[i] || entry.type != "Edge"
                || !entry.fingerprint.isValid()) {
                continue;
            }
            const std::string& hit = entry.exactElement;
            const int hitPosition = positionOf(pool, hit);
            const ElementFingerprint& now = fingerprintOfIndex(hit);
            if (hitPosition < 0
                || !hitWithinOldEdge(entry.fingerprint,
                                  now,
                                  input.diagonal,
                                  input.tolerances,
                                  input.continuationDistance)) {
                continue;
            }
            auto extent = OldExtent::of(entry.fingerprint, eps, input.tolerances, &now);
            auto hitRange = extent->interval(now);
            const auto& hitFaces = facesOf(hit);
            std::vector<std::pair<int, std::pair<double, double>>> continued;  // position, range
            std::vector<int> pastEnd;
            std::string sharedFace;
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& index = pool.elements[k].index;
                if (index == hit || held.count(index)) {
                    continue;
                }
                auto range = extent->interval(fingerprintOf(pool.elements[k]));
                if (!range) {
                    continue;
                }
                bool within = extent->within(*range);
                if (!within && extent->overlap(*range) <= eps) {
                    continue;  // beyond the old ends, at most touching one
                }
                const auto& faces = facesOf(index);
                auto shared = std::find_if(faces.begin(), faces.end(), [&](const auto& face) {
                    return hitFaces.count(face) > 0;
                });
                if (shared == faces.end()) {
                    continue;
                }
                if (within) {
                    continued.emplace_back(static_cast<int>(k), *range);
                    if (sharedFace.empty()) {
                        sharedFace = *shared;
                    }
                }
                else {
                    pastEnd.push_back(static_cast<int>(k));
                }
            }
            if (continued.empty() && pastEnd.empty()) {
                continue;  // only shortened
            }
            // Pieces of one edge are disjoint; overlapping ones are something else.
            std::vector<std::pair<double, double>> ranges {*hitRange};
            for (const auto& [k, range] : continued) {
                ranges.push_back(range);
            }
            const bool overlapping = extent->overlapping(ranges);

            std::vector<int> positions {hitPosition};
            std::string continuations;
            for (const auto& [k, range] : continued) {
                positions.push_back(k);
                continuations += (continuations.empty() ? "" : ", ") + pool.elements[k].index;
            }
            auto& outcome = outcomes[i];
            auto breakWith = [&](std::vector<int> listed, std::string evidence) {
                std::sort(listed.begin(), listed.end());
                outcome = SolveOutcome();
                outcome.evidence = std::move(evidence);
                for (int k : listed) {
                    outcome.candidates.push_back(pool.elements[k].index);
                    outcome.candidateNames.push_back(firstName(pool.elements[k]));
                    outcome.candidateRoles.emplace_back(k == hitPosition ? "name" : "piece");
                    outcome.candidateDistances.push_back(nan);
                }
            };
            if (!pastEnd.empty() || overlapping) {
                std::vector<int> listed = positions;
                listed.insert(listed.end(), pastEnd.begin(), pastEnd.end());
                std::string evidence = "pieces overlap";
                if (!pastEnd.empty()) {
                    evidence = "continued past the old edge by "
                        + pool.elements[pastEnd.front()].index;
                    for (std::size_t p = 1; p < pastEnd.size(); ++p) {
                        evidence += ", " + pool.elements[pastEnd[p]].index;
                    }
                }
                breakWith(listed, evidence);
            }
            else if (entry.policy == SolvePolicy::Expand) {
                std::sort(positions.begin(), positions.end());
                outcome.status = SolveStatus::Resolved;
                outcome.tier = 4;
                for (int k : positions) {
                    outcome.elements.push_back(pool.elements[k].index);
                    outcome.names.push_back(firstName(pool.elements[k]));
                }
                outcome.element = outcome.elements.front();
                outcome.name = outcome.names.front();
                outcome.from = entry.from.empty() ? entry.exactName : entry.from;
                outcome.evidence = "continued by " + continuations
                    + (extent->circle ? " (arc" : " (line") + (continued.size() > 1 ? "s" : "")
                    + " within the old edge, shares "
                    + sharedFace + ")";
                for (const auto& [k, range] : continued) {
                    taken.push_back(k);
                }
            }
            else if (entry.policy == SolvePolicy::Equivalent && entry.equivalent
                     && std::all_of(continued.begin(), continued.end(), [&](const auto& c) {
                            return entry.equivalent(hit, pool.elements[c.first].index);
                        })) {
                // Every piece gives the consumer the same result: the hit stands.
            }
            else {
                breakWith(positions, "split: the old edge continues in " + continuations);
            }
            decidedEntry[i] = 1;
        }
        for (int k : taken) {
            pool.exact.insert(pool.elements[k].index);
        }
    }

    // A planar face split by a coplanar one (Q3 (b)): a face's fingerprint doesn't bound its
    // region, so the rest of the old face can't be told from a coplanar neighbour. Detected and
    // broken, never taken.
    {
        Pool& pool = pools["Face"];
        auto inPlane = [&](const ElementFingerprint& saved, const ElementFingerprint& face) {
            return planeAgrees(saved,
                               face,
                               input.diagonal,
                               input.tolerances,
                               input.continuationDistance);
        };
        std::map<std::string, std::set<std::string>> neighbours;
        auto neighboursOf = [&](const std::string& index) -> const std::set<std::string>& {
            auto it = neighbours.find(index);
            if (it == neighbours.end()) {
                std::set<std::string> faces;
                if (input.neighboursOf) {
                    for (auto& face : input.neighboursOf(index)) {
                        faces.insert(std::move(face));
                    }
                }
                faces.erase(index);
                it = neighbours.emplace(index, std::move(faces)).first;
            }
            return it->second;
        };
        for (std::size_t i = 0; i < input.entries.size(); ++i) {
            const auto& entry = input.entries[i];
            const ElementFingerprint& saved = entry.fingerprint;
            if (!entry.exact || decidedEntry[i] || entry.type != "Face" || !isPlane(saved)) {
                continue;
            }
            const std::string& hit = entry.exactElement;
            const int hitPosition = positionOf(pool, hit);
            if (hitPosition < 0
                || !faceWithinOldPlane(saved,
                                       fingerprintOfIndex(hit),
                                       input.diagonal,
                                       input.tolerances,
                                       input.continuationDistance)) {
                continue;
            }
            const auto& hitNeighbours = neighboursOf(hit);
            std::vector<int> listed {hitPosition};
            std::string beside;
            std::string pastEnd;  // faces that run past the old face's extent
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& index = pool.elements[k].index;
                if (index == hit || pool.exact.count(index)
                    || !inPlane(saved, fingerprintOf(pool.elements[k]))) {
                    continue;
                }
                // Outside the old face's extent, a face holds no point of it (PR 8).
                ExtentRelation relation = faceExtentRelation(saved,
                                                             fingerprintOf(pool.elements[k]),
                                                             input.diagonal,
                                                             input.continuationDistance);
                if (relation == ExtentRelation::Outside) {
                    continue;
                }
                const auto& faces = neighboursOf(index);
                bool related = hitNeighbours.count(index) > 0
                    || std::any_of(faces.begin(), faces.end(), [&](const auto& face) {
                           return hitNeighbours.count(face) > 0;
                       });
                if (related) {
                    listed.push_back(static_cast<int>(k));
                    beside += (beside.empty() ? "" : ", ") + index;
                    if (relation == ExtentRelation::Overlapping) {
                        pastEnd += (pastEnd.empty() ? "" : ", ") + index;
                    }
                }
            }
            if (listed.size() == 1) {
                continue;  // only shrunk
            }
            // Equivalent (the coordinator's decision on the review): the hit stands if every
            // coplanar face beside it gives the consumer the same result, as for edges.
            // A face that runs past the old one breaks the entry under every policy, as an edge
            // that runs past the old end does.
            if (pastEnd.empty() && entry.policy == SolvePolicy::Equivalent && entry.equivalent
                && std::all_of(listed.begin(), listed.end(), [&](int k) {
                       return k == hitPosition
                           || entry.equivalent(hit, pool.elements[k].index);
                   })) {
                decidedEntry[i] = 1;
                continue;
            }
            std::sort(listed.begin(), listed.end());
            auto& outcome = outcomes[i];
            outcome = SolveOutcome();
            outcome.evidence = pastEnd.empty()
                ? "split: a coplanar face beside it, " + beside
                : "split: a coplanar face beside it runs past the old face, " + pastEnd;
            for (int k : listed) {
                outcome.candidates.push_back(pool.elements[k].index);
                outcome.candidateNames.push_back(firstName(pool.elements[k]));
                outcome.candidateRoles.emplace_back(k == hitPosition ? "name" : "piece");
                outcome.candidateDistances.push_back(nan);
            }
            decidedEntry[i] = 1;
        }
    }

    // Missing entries, grouped: one solve per (old name, type, policy).
    std::map<std::tuple<std::string, std::string, int>, std::vector<int>> groups;
    for (std::size_t i = 0; i < input.entries.size(); ++i) {
        const auto& entry = input.entries[i];
        if (!entry.exact && !decidedEntry[i]) {
            groups[{entry.oldName, entry.type, static_cast<int>(entry.policy)}].push_back(
                static_cast<int>(i)
            );
        }
    }

    struct GroupState
    {
        const std::vector<int>* members = nullptr;
        Pool* pool = nullptr;
        std::string oldName;
        std::vector<int> candidates;  // positions in the pool, in index order
        std::set<int> fromOverlap;
        std::set<int> fromNames;
        std::set<int> inAncestry;
        // The IDX source's elements, and whether they replaced the other candidates (tier 2
        // agreed with one of them at least).
        std::set<int> fromIndex;
        bool indexed = false;
        SolveOutcome outcome;
        bool decided = false;
        int graphEntry = -1;
        // Tiers 2-3: the survivors of tier 1 before geometry narrowed them (what a broken entry
        // lists), the tier that narrowed them (0: none), whether geometry alone found the
        // candidate, and what it found.
        std::vector<int> listed;
        int geometryTier = 0;
        bool geometric = false;
        std::string geometryEvidence;
        // Equivalent: the pieces that resolve as one, their representative being the only
        // entry of `candidates`.
        std::vector<int> equivalent;
        // Expand: the pieces that resolve together, the first being the only entry of
        // `candidates`.
        std::vector<int> expanded;
        // The members' saved fingerprint, if they all hold the same valid one.
        const ElementFingerprint* saved = nullptr;
    };

    // The members' saved fingerprint, if they all hold the same valid one.
    auto savedFingerprint = [&](const std::vector<int>& members) -> const ElementFingerprint* {
        const ElementFingerprint& first = input.entries[members.front()].fingerprint;
        if (!first.isValid()) {
            return nullptr;
        }
        for (int member : members) {
            if (input.entries[member].fingerprint != first) {
                return nullptr;
            }
        }
        return &first;
    };
    std::vector<GroupState> states;
    states.reserve(groups.size());

    // \a role: the candidates' role, or empty for a structural survivor's or a piece's, as the
    // group shows it.
    auto listCandidates = [nan](GroupState& state,
                                const std::vector<int>& positions,
                                const char* role = nullptr) {
        auto isPiece = [&](int k) {
            const auto& names = state.pool->elements[k].names;
            return std::any_of(names.begin(), names.end(), [&](const auto& n) {
                return NameAncestry::isPieceOf(n, state.oldName)
                    || NameAncestry::isIndexPieceOf(n, state.oldName);
            });
        };
        for (int k : positions) {
            const auto& element = state.pool->elements[k];
            state.outcome.candidates.push_back(element.index);
            state.outcome.candidateNames.push_back(
                element.names.empty() ? std::string() : element.names.front()
            );
            state.outcome.candidateRoles.emplace_back(role ? role
                                                      : isPiece(k) ? "piece"
                                                                   : "structural");
            state.outcome.candidateDistances.push_back(nan);
        }
    };

    MatchGraph graph;
    std::map<int, int> nodeOfId;              // element ID -> graph candidate
    std::map<int, int> representativeOfNode;  // equivalent candidates -> representative's ID

    for (auto& [key, members] : groups) {
        GroupState& state = states.emplace_back();
        state.members = &members;
        state.oldName = std::get<0>(key);
        state.pool = &pools[std::get<1>(key)];
        Pool& pool = *state.pool;
        const std::string& oldName = state.oldName;

        // The pool for this entry: tier-0 elements only as proven merges.
        std::vector<std::string> flatNames;
        std::vector<int> flatElements;
        std::vector<char> allowed(pool.elements.size(), 0);
        for (std::size_t k = 0; k < pool.elements.size(); ++k) {
            const auto& element = pool.elements[k];
            bool contains = !oldName.empty()
                && std::any_of(element.names.begin(), element.names.end(), [&](const auto& n) {
                                return ancestry.contains(n, oldName);
                            });
            if (pool.exact.count(element.index) && !contains) {
                continue;
            }
            allowed[k] = 1;
            if (contains) {
                state.inAncestry.insert(static_cast<int>(k));
            }
            for (const auto& name : element.names) {
                flatNames.push_back(name);
                flatElements.push_back(static_cast<int>(k));
            }
        }

        if (!oldName.empty() && input.source != Tier1Source::Names) {
            for (int i : ancestry.structuralSurvivors(oldName, flatNames, input.gap)) {
                state.fromOverlap.insert(flatElements[i]);
            }
        }
        if (input.source != Tier1Source::Overlap) {
            for (int member : members) {
                for (const auto& name : input.entries[member].nameMatches) {
                    auto it = pool.byName.find(name);
                    if (it != pool.byName.end() && allowed[it->second]) {
                        state.fromNames.insert(it->second);
                    }
                }
            }
        }
        std::set<int> all(state.fromOverlap);
        all.insert(state.fromNames.begin(), state.fromNames.end());

        // The IDX source: the elements named by the old name's IDX section under any op code,
        // or by its index on a map-less target (Q5); and the old IDX element's pieces under
        // another op code, which join the candidates as pieces.
        std::string_view indexSource = NameAncestry::indexSource(oldName);
        if (!indexSource.empty()) {
            std::string maplessIndex =
                maplessElement(indexSource, input.maplessTag, std::get<1>(key));
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                if (!allowed[k]) {
                    continue;
                }
                const auto& names = pool.elements[k].names;
                if (pool.elements[k].index == maplessIndex
                    || std::any_of(names.begin(), names.end(), [&](const auto& n) {
                           return NameAncestry::sameIndexSource(n, indexSource);
                       })) {
                    state.fromIndex.insert(static_cast<int>(k));
                }
                else if (std::any_of(names.begin(), names.end(), [&](const auto& n) {
                             return NameAncestry::isIndexPieceOf(n, oldName);
                         })) {
                    all.insert(static_cast<int>(k));
                }
            }
        }
        // The old element's pieces, wherever tier 1's filters left them: a piece's top section
        // is its cutter's, so the top agreement among the overlap survivors can drop every
        // piece in favour of an element generated from the old one (Task 2 PR 7's review).
        if (!oldName.empty()) {
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& names = pool.elements[k].names;
                if (allowed[k] && std::any_of(names.begin(), names.end(), [&](const auto& n) {
                        return NameAncestry::isPieceOf(n, oldName);
                    })) {
                    all.insert(static_cast<int>(k));
                }
            }
        }
        state.candidates.assign(all.begin(), all.end());

        // Tiers 2 and 3 and the IDX source, for a reference with a saved fingerprint.
        const ElementFingerprint* saved = savedFingerprint(members);
        state.saved = saved;
        auto intrinsicSurvivors = [&](const std::vector<int>& positions) {
            std::vector<int> agree;
            for (int k : positions) {
                if (intrinsicAgrees(*saved, fingerprintOf(pool.elements[k]), input.tolerances)) {
                    agree.push_back(k);
                }
            }
            return agree;
        };
        auto nearestOf = [&](const std::vector<int>& positions) {
            std::vector<ElementFingerprint> fingerprints;
            for (int k : positions) {
                fingerprints.push_back(fingerprintOf(pool.elements[k]));
            }
            return findNearest(*saved, fingerprints, input.diagonal, input.tolerances);
        };

        // Pieces. Under One they break the entry at once. Under Expand they resolve together.
        // Under Equivalent they resolve as one candidate if every piece gives the consumer the
        // same result, represented by the piece whose first name sorts first; otherwise the
        // entry breaks. The other survivors don't count: the pieces are what is left of the old
        // element. Equivalent without pieces is One (see solveOwner()'s comment).
        std::vector<int> pieces;
        std::vector<int> others;
        for (int k : state.candidates) {
            const auto& names = pool.elements[k].names;
            bool piece = std::any_of(names.begin(), names.end(), [&](const auto& n) {
                return NameAncestry::isPieceOf(n, oldName)
                    || NameAncestry::isIndexPieceOf(n, oldName);
            });
            (piece ? pieces : others).push_back(k);
        }
        const bool equivalentPolicy = std::get<2>(key) == static_cast<int>(SolvePolicy::Equivalent);
        if (!pieces.empty() && equivalentPolicy) {
            std::vector<std::string> indexes;
            for (int k : pieces) {
                indexes.push_back(pool.elements[k].index);
            }
            auto results = groupEquivalent(indexes, [&](int a, int b) {
                return std::all_of(members.begin(), members.end(), [&](int member) {
                    const auto& equivalent = input.entries[member].equivalent;
                    return equivalent && equivalent(indexes[a], indexes[b]);
                });
            });
            if (results.size() != 1) {
                state.decided = true;
                state.outcome.evidence = "split into " + std::to_string(pieces.size())
                    + " pieces, " + std::to_string(results.size())
                    + " different results for the consumer";
                listCandidates(state, pieces);
                listCandidates(state, others);
                continue;
            }
            int representative = *std::min_element(pieces.begin(), pieces.end(), [&](int a, int b) {
                const std::string na = firstName(pool.elements[a]);
                const std::string nb = firstName(pool.elements[b]);
                return na != nb ? na < nb : a < b;
            });
            state.equivalent = pieces;
            state.candidates = {representative};
            state.listed = pieces;
        }
        else if (!pieces.empty() && std::get<2>(key) == static_cast<int>(SolvePolicy::Expand)) {
            // Structural evidence, as for Equivalent: no geometry runs.
            state.expanded = pieces;
            state.candidates = {pieces.front()};
            state.listed = pieces;
        }
        else if (!pieces.empty()) {
            state.decided = true;
            state.outcome.evidence = "split into " + std::to_string(pieces.size()) + " pieces";
            listCandidates(state, pieces);
            listCandidates(state, others);
            continue;
        }
        else {
            state.listed = state.candidates;
        }

        // The IDX source decides among its elements when tier 2 agrees with one: it names the
        // old element itself (or the whole it was a piece of), under the op code of whatever
        // last touched it. The other survivors don't count then.
        if (saved && pieces.empty() && !state.fromIndex.empty()) {
            std::vector<int> agree = intrinsicSurvivors(
                std::vector<int>(state.fromIndex.begin(), state.fromIndex.end())
            );
            if (!agree.empty()) {
                state.indexed = true;
                state.candidates = agree;
                state.listed = agree;
            }
        }

        if (saved && state.candidates.size() > 1) {
            // Geometry breaks ties among tier 1's survivors; it never replaces them.
            std::vector<int> agree = intrinsicSurvivors(state.candidates);
            if (agree.size() == 1) {
                state.geometryTier = 2;
                state.geometryEvidence = "tier 2: 1 of " + std::to_string(state.candidates.size());
                state.candidates = agree;
            }
            else if (agree.size() > 1) {
                Nearest nearest = nearestOf(agree);
                if (nearest.index >= 0) {
                    state.geometryTier = 3;
                    state.geometryEvidence = "tier 3: " + describeNearest(nearest);
                    state.candidates = {agree[nearest.index]};
                }
                else if (agree.size() < state.candidates.size()) {
                    state.geometryTier = 2;
                    state.geometryEvidence = "tier 2: " + std::to_string(agree.size()) + " of "
                        + std::to_string(state.candidates.size());
                    state.candidates = agree;
                }
            }
        }
        else if (saved && state.candidates.empty()) {
            // Nothing structural: both geometric tiers must pass, on every element of the type
            // that no other reference of the owner holds exactly.
            std::vector<int> open;
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                if (allowed[k]) {
                    open.push_back(static_cast<int>(k));
                }
            }
            std::vector<int> agree = intrinsicSurvivors(open);
            if (!agree.empty()) {
                Nearest nearest = nearestOf(agree);
                if (nearest.index >= 0) {
                    state.geometric = true;
                    state.geometryEvidence = "no structural candidate, tier 3: "
                        + describeNearest(nearest);
                    state.candidates = {agree[nearest.index]};
                    state.listed = state.candidates;
                }
                else {
                    state.decided = true;
                    state.outcome.evidence = "no structural candidate, tier 3 found none: "
                        + describeNearest(nearest);
                    listCandidates(state, agree, "geometric");
                    continue;
                }
            }
        }

        if (state.candidates.empty()) {
            state.decided = true;
            state.outcome.evidence = "no candidate";
            continue;
        }

        state.graphEntry = graph.entryCount++;
        if (!state.equivalent.empty()) {
            // One candidate holding every equivalent element, so that no other entry takes one
            // of them; it stands for its representative.
            std::vector<int> ids;
            for (int k : state.equivalent) {
                ids.push_back(pool.ids[k]);
            }
            int representative = state.candidates.front();
            int node = graph.addCandidate(std::move(ids));
            representativeOfNode[node] = pool.ids[representative];
            graph.addEdge(state.graphEntry, node, state.inAncestry.count(representative) > 0);
            continue;
        }
        if (!state.expanded.empty()) {
            // One candidate holding every piece: the pieces are matched as a set. They hold the
            // old name in their ancestry.
            std::vector<int> ids;
            for (int k : state.expanded) {
                ids.push_back(pool.ids[k]);
            }
            int node = graph.addCandidate(std::move(ids));
            representativeOfNode[node] = pool.ids[state.expanded.front()];
            graph.addEdge(state.graphEntry, node, true);
            continue;
        }
        for (int k : state.candidates) {
            int id = pool.ids[k];
            auto [it, inserted] = nodeOfId.emplace(id, 0);
            if (inserted) {
                it->second = graph.addCandidate({id});
            }
            graph.addEdge(state.graphEntry, it->second, state.inAncestry.count(k) > 0);
        }
    }

    MatchResult matched = forcedMatching(graph);
    std::map<int, int> idOfNode(representativeOfNode);
    for (const auto& [id, node] : nodeOfId) {
        idOfNode[node] = id;
    }

    for (auto& state : states) {
        if (!state.decided) {
            int e = state.graphEntry;
            MatchStatus status = matched.status[e];
            int k = status == MatchStatus::Resolved
                ? elementOfId[idOfNode[matched.partner[e]]].second
                : -1;
            // A partner named as the old element up to the duplicate counter is a sibling (a
            // pattern instance's copy of it), never the element itself: its ancestry and its top
            // section are the old element's, so the evidence below can't tell them apart.
            auto siblingElement = [&](int position) {
                const auto& names = state.pool->elements[position].names;
                return std::any_of(names.begin(), names.end(), [&](const auto& n) {
                    return isCounterSibling(n, state.oldName);
                });
            };
            bool sibling = k >= 0
                && (state.expanded.empty() ? siblingElement(k)
                                           : std::any_of(state.expanded.begin(),
                                                         state.expanded.end(),
                                                         siblingElement));
            // A partner from tier 1 must agree with the old name on the top section, or hold the
            // old name in its ancestry: an ancestor shared with the old name alone (e.g. a sketch
            // edge that many elements embed through a face) doesn't show it is the same element.
            // A partner that only geometry found passed both geometric tiers. The IDX source and
            // the old element's pieces (an IDX element's pieces under another op code don't hold
            // the old name) are evidence of their own.
            bool evidenced = k >= 0
                && (state.geometric || state.inAncestry.count(k) > 0
                    || (state.indexed && state.fromIndex.count(k) > 0) || !state.equivalent.empty()
                    || !state.expanded.empty()
                    || std::any_of(
                        state.pool->elements[k].names.begin(),
                        state.pool->elements[k].names.end(),
                        [&](const auto& n) { return NameAncestry::topAgrees(state.oldName, n); }
                    ));
            // A partner that tier 1 alone found must not contradict the saved geometry (ops#87:
            // a thread's B-spline edge resolved to a circle with which it shares sources). The
            // geometric tiers, the IDX source and pieces checked or need no check.
            bool contradicts = false;
            if (k >= 0 && state.saved && input.check != Tier1Check::None && !state.geometric
                && state.geometryTier == 0 && !state.indexed && state.equivalent.empty()
                && state.expanded.empty()) {
                const ElementFingerprint& now = fingerprintOf(state.pool->elements[k]);
                contradicts = input.check == Tier1Check::Kind
                    ? !(now.isValid() && now.type == state.saved->type
                        && now.kind == state.saved->kind)
                    : !intrinsicAgrees(*state.saved, now, input.tolerances);
            }
            if (status == MatchStatus::Resolved && sibling) {
                state.outcome.evidence = "pattern sibling";
                listCandidates(state, state.listed, state.geometric ? "geometric" : nullptr);
            }
            else if (status == MatchStatus::Resolved && !evidenced) {
                state.outcome.evidence = "no top agreement";
                listCandidates(state, state.listed, state.geometric ? "geometric" : nullptr);
            }
            else if (status == MatchStatus::Resolved && contradicts) {
                state.outcome.evidence = "tier 2 disagrees with "
                    + state.pool->elements[k].index;
                listCandidates(state, state.listed, state.geometric ? "geometric" : nullptr);
            }
            else if (status == MatchStatus::Resolved && !state.expanded.empty()) {
                state.outcome.status = SolveStatus::Resolved;
                state.outcome.tier = 1;
                for (int piece : state.expanded) {
                    state.outcome.elements.push_back(state.pool->elements[piece].index);
                    state.outcome.names.push_back(firstName(state.pool->elements[piece]));
                }
                state.outcome.element = state.outcome.elements.front();
                state.outcome.name = state.outcome.names.front();
                state.outcome.evidence = "split into " + std::to_string(state.expanded.size())
                    + " pieces, expanded";
            }
            else if (status == MatchStatus::Resolved) {
                const auto& element = state.pool->elements[k];
                double best = 0.0;
                for (const auto& name : element.names) {
                    best = std::max(best, ancestry.overlap(state.oldName, name));
                }
                std::string sources;
                if (state.fromOverlap.count(k)) {
                    sources = "overlap";
                }
                if (state.fromNames.count(k)) {
                    sources += sources.empty() ? "names" : "+names";
                }
                if (state.indexed && state.fromIndex.count(k)) {
                    sources += sources.empty() ? "index" : "+index";
                }
                state.outcome.status = SolveStatus::Resolved;
                state.outcome.tier = state.geometric ? 3 : state.geometryTier ? state.geometryTier : 1;
                state.outcome.element = element.index;
                state.outcome.name = firstName(element);
                if (state.geometric) {
                    state.outcome.evidence = state.geometryEvidence;
                }
                else {
                    state.outcome.evidence = "overlap " + formatOverlap(best) + ", sources "
                        + sources + (state.inAncestry.count(k) ? ", in ancestry" : "")
                        + (state.indexed ? ", tier 2 agrees" : "")
                        + (state.geometryEvidence.empty() ? "" : ", " + state.geometryEvidence)
                        + (state.equivalent.empty()
                               ? ""
                               : ", " + std::to_string(state.equivalent.size())
                                   + " pieces equivalent for the consumer");
                }
            }
            else {
                state.outcome.evidence = status == MatchStatus::TooLarge ? "too large to solve"
                    : status == MatchStatus::NoCandidate                 ? "no candidate"
                                                                         : "ambiguous";
                if (!state.geometryEvidence.empty()) {
                    state.outcome.evidence += ", " + state.geometryEvidence;
                }
                listCandidates(state, state.listed, state.geometric ? "geometric" : nullptr);
            }
        }
        for (int member : *state.members) {
            outcomes[member] = state.outcome;
            if (!state.outcome.elements.empty()) {
                // Expanded: a member that was a piece already passes its `from` on.
                const auto& from = input.entries[member].from;
                outcomes[member].from = from.empty() ? state.oldName : from;
            }
        }
    }
    return outcomes;
}

}  // namespace Data
