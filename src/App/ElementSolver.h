// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace Data
{

/** The ancestry of V2 mapped names: the structural evidence of the reference solver (ops#7).
 *
 * A node is a V2 name: a whole name, a prefix of one before a top-level `|`, or a Linked or
 * Connected Name embedded in a section, recursively. A node's ancestor set A*(n) is
 *
 *     {n} + A*(prefix of n) + A*(e) for every name e embedded in n's last section,
 *
 * so it holds n itself, every prefix of n, and every name embedded at any depth in any of n's
 * sections: the closure over the provenance DAG. A split piece `X|...;MOD;...` therefore has X in
 * its set.
 *
 * Names are bare mapped names, as an element map stores them: no `;` prefix and no `.Edge1`
 * suffix. Each distinct node string gets a dense key on first sight, valid for the life of the
 * object (one solve), and each node's set is computed once, on its first query, as a sorted
 * vector of keys. Shared subtrees are computed once. The keys depend on the order of the queries,
 * the results never do: every function below answers the same whatever was asked before.
 */
class AppExport NameAncestry
{
public:
    using Key = std::uint32_t;
    /// Sorted, unique keys.
    using KeySet = std::vector<Key>;

    /// The key of \a name, interned on first sight.
    Key intern(std::string_view name);
    /// The node string of a key returned by intern() or ancestors().
    const std::string& name(Key key) const;
    /// The number of distinct nodes seen so far.
    std::size_t nodeCount() const
    {
        return _names.size();
    }
    /// The number of nodes whose ancestor set has been computed.
    std::size_t computedCount() const
    {
        return _computed;
    }

    /// A*(name). Empty only for an empty name.
    const KeySet& ancestors(std::string_view name);
    /// A*(name) as node strings, sorted by bytes.
    std::vector<std::string> ancestorNames(std::string_view name);
    /// True if \a ancestor is in A*(name), \a name itself included.
    bool contains(std::string_view name, std::string_view ancestor);
    /// |A*(oldName) ∩ A*(candidate)| / |A*(oldName)|, in [0, 1]; 0 for an empty old name.
    double overlap(std::string_view oldName, std::string_view candidate);

    /// True if the last sections of both names have the same opcode and the same mapper flags
    /// (as sets). False if either name is empty.
    static bool topAgrees(std::string_view oldName, std::string_view candidate);

    /** True if \a name is a split piece of \a oldName: \a oldName followed by one or more
     * sections, each carrying the MOD flag and the element type of \a oldName's last section.
     * A name is not a piece of itself.
     */
    static bool isPieceOf(std::string_view name, std::string_view oldName);

    /// The top-level sections of \a name, split at every `|` that no `^` escapes. Views into
    /// \a name. An empty name has none.
    static std::vector<std::string_view> splitSections(std::string_view name);

    /** Tier 1's survivors among \a candidates, as indices into it, in increasing order.
     *
     * A candidate survives if its overlap with \a oldName is at least best - \a gap, where best is
     * the highest overlap and is above 0. If some survivors agree with \a oldName on the top
     * section (topAgrees()), those that don't are dropped. No survivors when best is 0.
     */
    std::vector<int> structuralSurvivors(
        std::string_view oldName,
        const std::vector<std::string>& candidates,
        double gap
    );

private:
    const KeySet& ancestorsOf(Key key);

    // By key. Deques, so that interning a node keeps the views in _keys and the references to
    // computed sets valid.
    std::deque<std::string> _names;
    std::deque<KeySet> _sets;
    std::deque<char> _done;  // _sets[key] is computed
    std::unordered_map<std::string_view, Key> _keys;
    std::size_t _computed = 0;
};

/** One owner's references and their surviving candidates, for forcedMatching().
 *
 * Entries are the owner's unresolved references, 0 to entryCount - 1. A candidate is what an
 * entry would resolve to: one element, a piece set (all pieces of a split element, for an
 * expanding reference) or an equivalence group's representative. Its elements are the element
 * IDs it takes, chosen by the caller; two candidates that share an element are never both used.
 *
 * An edge says that a candidate survived for an entry. inAncestry says that the entry's old
 * name is in the candidate's ancestry (NameAncestry::contains()): the evidence that the entry's
 * element became that candidate. A candidate that is in the ancestry of two or more entries
 * (a proven merge) may take any number of those entries together; otherwise it takes at most
 * one entry.
 */
struct AppExport MatchGraph
{
    struct Candidate
    {
        std::vector<int> elements;
    };
    struct Edge
    {
        int entry = 0;
        int candidate = 0;
        bool inAncestry = false;
    };

    int entryCount = 0;
    std::vector<Candidate> candidates;
    std::vector<Edge> edges;

    /// Adds a candidate taking \a elements, and returns its index.
    int addCandidate(std::vector<int> elements);
    void addEdge(int entry, int candidate, bool inAncestry = false);
};

enum class MatchStatus
{
    /// The entry has the same partner in every maximum matching.
    Resolved,
    /// The entry has no candidate.
    NoCandidate,
    /// Maximum matchings disagree on the entry: a different partner, or none.
    Ambiguous,
    /// The entry's component was too large to solve exactly; nothing in it resolves.
    TooLarge,
};

struct AppExport MatchResult
{
    /// Per entry: the candidate it resolves to, or -1.
    std::vector<int> partner;
    std::vector<MatchStatus> status;
};

/** Forced matching: an entry resolves only to the partner it has in every maximum matching.
 *
 * A matching gives each entry at most one candidate, and uses each candidate either for one
 * entry or, for a proven merge, for any number of the entries whose old names are in its
 * ancestry (MatchGraph). Two candidates that share an element are never both used.
 *
 * The graph is split into components (connected through edges and shared elements). A component
 * whose candidates share no elements is solved as a b-matching by augmenting paths: for each edge
 * of one maximum matching, the edge is forced when removing it lowers the maximum. A proven merge
 * is either used as a merge or as a single candidate, and every combination of these modes is
 * tried (at most maxMerges merge candidates per component). A component with shared elements is
 * searched exhaustively, within maxSteps steps. A component over either limit is TooLarge.
 *
 * The result depends only on the graph as a set: not on the order of entries, candidates, edges
 * or elements (the gtests check this under permutations). Bad indices throw Base::ValueError.
 */
AppExport MatchResult forcedMatching(
    const MatchGraph& graph,
    int maxMerges = 10,
    long maxSteps = 1000000
);

/** Groups items that are equivalent under \a equivalent, a symmetric predicate called once per
 * pair (i, j) with i < j.
 *
 * The groups are the connected components of the equivalence graph (a union-find in index
 * order). A tolerance predicate need not be transitive, so a component in which some pair is
 * not equivalent is not a group: its items stay apart, one group each, which keeps them as
 * separate candidates (broken rather than wrong).
 *
 * Each group lists its items' indices sorted by \a names (by bytes, then by index), so its
 * representative, the first, is the item whose name sorts first. Groups are sorted by their
 * representative. For distinct names, the result doesn't depend on the order of the items.
 */
AppExport std::vector<std::vector<int>> groupEquivalent(
    const std::vector<std::string>& names,
    const std::function<bool(int, int)>& equivalent
);

}  // namespace Data
