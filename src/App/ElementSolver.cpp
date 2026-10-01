// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ElementSolver.h"

#include <algorithm>
#include <cmath>
#include <locale>
#include <map>
#include <numeric>
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
    std::vector<std::string> children;
    {
        const std::string& node = _names[key];
        auto sections = splitSections(node);
        if (sections.size() > 1) {
            // Everything before the last top-level delimiter.
            auto prefixSize = static_cast<std::size_t>(sections.back().data() - node.data()) - 1;
            children.emplace_back(node.substr(0, prefixSize));
        }
        if (!sections.empty()) {
            const auto& last = decodeSection(sections.back());
            for (const auto& embedded : last.linkedNames) {
                children.push_back(embedded);
            }
            for (const auto& embedded : last.connectedElements) {
                children.push_back(embedded);
            }
        }
    }

    KeySet result {key};
    for (const auto& child : children) {
        if (child.empty()) {
            continue;
        }
        Key childKey = intern(child);
        if (childKey == key) {
            continue;  // not possible for a well-formed name, which is longer than its parts
        }
        const KeySet& childSet = ancestorsOf(childKey);
        result.insert(result.end(), childSet.begin(), childSet.end());
    }
    std::sort(result.begin(), result.end());
    result.erase(std::unique(result.begin(), result.end()), result.end());

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
        if (!decoded.hasMapperFlag(MAPPER_FLAG_MODIFIED) || decoded.elementType != elementType) {
            return false;
        }
    }
    return true;
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

    std::vector<double> overlaps;
    overlaps.reserve(candidates.size());
    double best = 0.0;
    for (const auto& candidate : candidates) {
        overlaps.push_back(overlap(oldName, candidate));
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

// The duplicate counter written over the op code from count 2 on: `_2`, `_3`, ... (ops#55).
bool isCounterOpCode(const std::string& opCode)
{
    return opCode.size() > 1 && opCode[0] == '_'
        && std::all_of(opCode.begin() + 1, opCode.end(), [](char c) {
               return c >= '0' && c <= '9';
           });
}

/* True if \a a and \a b are the same name up to the duplicate counter of any section, at any
 * depth: the sections of the embedded Linked and Connected Names are compared the same way, so a
 * face built on instance 1's edges and one built on instance 2's are equal up to the counter.
 * Both forms of the counter are ignored, as harness.py's withoutCounter() does: the duplicate
 * count field, and a counter written over the op code, which then matches any op code. A section
 * that doesn't decode must be equal as text.
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
        if (!opCodesAgree || x.referenceIDs != y.referenceIDs || x.iterationTag != y.iterationTag
            || x.index != y.index || x.elementType != y.elementType
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

}  // namespace

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
    NameAncestry ancestry;
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
    for (const auto& [type, elements] : input.pool) {
        std::map<std::string, std::vector<std::string>> merged;
        for (const auto& element : elements) {
            auto& names = merged[element.index];
            names.insert(names.end(), element.names.begin(), element.names.end());
        }
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

    // Missing entries, grouped: one solve per (old name, type, policy).
    std::map<std::tuple<std::string, std::string, int>, std::vector<int>> groups;
    for (std::size_t i = 0; i < input.entries.size(); ++i) {
        const auto& entry = input.entries[i];
        if (!entry.exact) {
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
    };

    // The pool elements' current fingerprints, measured on first use.
    std::map<std::string, ElementFingerprint> measured;
    auto fingerprintOf = [&](const SolveInput::Element& element) -> const ElementFingerprint& {
        auto it = measured.find(element.index);
        if (it == measured.end()) {
            ElementFingerprint fingerprint;
            if (input.fingerprintOf) {
                fingerprint = input.fingerprintOf(element.index);
            }
            it = measured.emplace(element.index, std::move(fingerprint)).first;
        }
        return it->second;
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

    auto listCandidates = [](GroupState& state, const std::vector<int>& positions) {
        for (int k : positions) {
            const auto& element = state.pool->elements[k];
            state.outcome.candidates.push_back(element.index);
            state.outcome.candidateNames.push_back(
                element.names.empty() ? std::string() : element.names.front()
            );
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
        state.candidates.assign(all.begin(), all.end());

        // Pieces. Under One (and Expand, read as One until PR 7) they break the entry at once.
        // Under Equivalent they resolve as one candidate if every piece gives the consumer the
        // same result, represented by the piece whose first name sorts first; otherwise the
        // entry breaks. The other survivors don't count: the pieces are what is left of the old
        // element. Equivalent without pieces is One (see solveOwner()'s comment).
        std::vector<int> pieces;
        std::vector<int> others;
        for (int k : state.candidates) {
            const auto& names = pool.elements[k].names;
            bool piece = std::any_of(names.begin(), names.end(), [&](const auto& n) {
                return NameAncestry::isPieceOf(n, oldName);
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

        // Tiers 2 and 3, for a reference with a saved fingerprint.
        const ElementFingerprint* saved = savedFingerprint(members);
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
                    listCandidates(state, agree);
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
            bool sibling = k >= 0
                && std::any_of(
                    state.pool->elements[k].names.begin(),
                    state.pool->elements[k].names.end(),
                    [&](const auto& n) { return isCounterSibling(n, state.oldName); }
                );
            // A partner from tier 1 must agree with the old name on the top section, or hold the
            // old name in its ancestry: an ancestor shared with the old name alone (e.g. a sketch
            // edge that many elements embed through a face) doesn't show it is the same element.
            // A partner that only geometry found passed both geometric tiers.
            bool evidenced = k >= 0
                && (state.geometric || state.inAncestry.count(k) > 0
                    || std::any_of(
                        state.pool->elements[k].names.begin(),
                        state.pool->elements[k].names.end(),
                        [&](const auto& n) { return NameAncestry::topAgrees(state.oldName, n); }
                    ));
            if (status == MatchStatus::Resolved && sibling) {
                state.outcome.evidence = "pattern sibling";
                listCandidates(state, state.listed);
            }
            else if (status == MatchStatus::Resolved && !evidenced) {
                state.outcome.evidence = "no top agreement";
                listCandidates(state, state.listed);
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
                listCandidates(state, state.listed);
            }
        }
        for (int member : *state.members) {
            outcomes[member] = state.outcome;
        }
    }
    return outcomes;
}

}  // namespace Data
