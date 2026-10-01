// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include "ElementFingerprint.h"

#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <map>
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

/// What a reference's owner wants when its element became several candidates. Mirrors
/// App::PropertyLinkBase::ElementPolicy, which this file doesn't include.
enum class SolvePolicy
{
    One,
    Expand,
    Equivalent,
};

/// The candidate sources of tier 1 (the NamingSolver/Tier1Source parameter, for PR 8's
/// comparison): ancestry overlap, findSimilarNames, or both.
enum class Tier1Source
{
    Union,
    Overlap,
    Names,
};

/** The tolerances of tiers 2 and 3 (the NamingSolver parameters; conservative starts, changed
 * only on the scorecard's evidence).
 */
struct AppExport GeometryTolerances
{
    /// Tier 2: the largest angle between directions, in radians.
    double angle = 1e-6;
    /// Tier 2: the largest relative difference of radii (and a cone's semi-angle).
    double radius = 1e-6;
    /// Tier 3: d_max, the largest distance of the nearest centre, as a share of the target's
    /// bounding-box diagonal.
    double distance = 0.01;
    /// Tier 3: the second nearest centre must be at least this many times the nearest's
    /// distance away, and at least d_max.
    double gapFactor = 3.0;
    /// Tier 3: the largest relative difference of sizes (area or length).
    double size = 0.01;
};

/** Tier 2, intrinsic geometry: the same element type and surface or curve kind, directions
 * within \a tolerances.angle (a plane's normal with its sense, an axis or a line's direction
 * either way), and the same number of radii, each within \a tolerances.radius relative.
 * False if either fingerprint is invalid.
 */
AppExport bool intrinsicAgrees(
    const ElementFingerprint& saved,
    const ElementFingerprint& candidate,
    const GeometryTolerances& tolerances
);

/** Tier 3, extrinsic geometry: the one of \a candidates whose centre is nearest \a saved's,
 * within d_max (tolerances.distance times \a diagonal), with every other candidate at least
 * gapFactor times as far and at least d_max away, and with a size within tolerances.size
 * relative. Returns its index in \a candidates, or -1. A candidate without a centre is never
 * chosen; it doesn't count as a competitor either (callers pass tier 2's survivors, which have
 * centres when \a saved has one).
 */
AppExport int extrinsicNearest(
    const ElementFingerprint& saved,
    const std::vector<ElementFingerprint>& candidates,
    double diagonal,
    const GeometryTolerances& tolerances
);

/** One owner's references to one target, for solveOwner(): plain data, no document.
 *
 * Names are bare mapped names. Element types are those of the stored index names: `Face`,
 * `Edge`, `Vertex`, or a sketch's `InternalEdge`.
 */
struct AppExport SolveInput
{
    struct Entry
    {
        /// The old mapped name; unused for an exact entry.
        std::string oldName;
        /// The element type of the reference.
        std::string type;
        SolvePolicy policy = SolvePolicy::One;
        /// Resolved exactly (tier 0) to exactElement, e.g. `Face3`.
        bool exact = false;
        std::string exactElement;
        /// The target's findSimilarNames() result for oldName, of any type.
        std::vector<std::string> nameMatches;
        /// The fingerprint saved with the reference; invalid if none (tiers 2 and 3 then don't
        /// run for it).
        ElementFingerprint fingerprint;
        /// Equivalent: whether the consumer would get the same result from either of two
        /// elements of the target (index names, e.g. `Face7`). Unset: no two are equivalent.
        std::function<bool(const std::string&, const std::string&)> equivalent;
    };
    /// An element of the target with all its mapped names.
    struct Element
    {
        std::string index;
        std::vector<std::string> names;
    };

    std::vector<Entry> entries;
    /// The target's named elements, by type.
    std::map<std::string, std::vector<Element>> pool;
    /// Tier 1's overlap gap (NameAncestry::structuralSurvivors()).
    double gap = 0.25;
    Tier1Source source = Tier1Source::Union;
    /// Tiers 2 and 3.
    GeometryTolerances tolerances;
    /// The target's bounding-box diagonal, the scale of tier 3's d_max.
    double diagonal = 0.0;
    /// The current fingerprint of the target's element \a index (e.g. `Face7`); invalid if it
    /// can't be measured. Called at most once per element, only when tiers 2 and 3 run. Unset:
    /// no element has a fingerprint.
    std::function<ElementFingerprint(const std::string& index)> fingerprintOf;
};

enum class SolveStatus
{
    /// Resolved by the exact lookup (tier 0), before the solver.
    Exact,
    /// Resolved by the solver.
    Resolved,
    /// Not resolved: the reference stays missing.
    Broken,
};

struct AppExport SolveOutcome
{
    SolveStatus status = SolveStatus::Broken;
    /// Exact and Resolved: the element, e.g. `Face7`, and its mapped name (the first of its
    /// names by bytes; empty if it has none).
    std::string element;
    std::string name;
    /// 0 for Exact; for Resolved the tier that decided: 1 (structure), 2 (intrinsic geometry
    /// narrowed tier 1's survivors to one), 3 (extrinsic geometry did, or found the element
    /// when tier 1 found nothing); -1 for Broken.
    int tier = -1;
    /// Broken: the candidates the user may choose from, pieces first, each part in index order,
    /// with their mapped names (parallel).
    std::vector<std::string> candidates;
    std::vector<std::string> candidateNames;
    /// The evidence, for the log and the report: overlap and sources, or why it broke.
    std::string evidence;
};

/** Tiers 0-3 and forced matching for one owner's references to one target (Task 2 PRs 3-4).
 *
 * - Exact entries keep their element, and it leaves the other entries' pools unless one of its
 *   names has the entry's old name in its ancestry (a proven merge, an inAncestry edge). Exact
 *   entries never enter the graph.
 * - Missing entries with the same old name, type and policy are solved once and get the same
 *   outcome. Geometry runs for them only if they all hold the same valid fingerprint.
 * - Candidates: the overlap survivors (NameAncestry::structuralSurvivors() over every name of
 *   every pool element of the entry's type) and the name matches of that type, by \a source.
 * - One (and, until PR 7, Expand): a candidate that is a piece of the old element breaks the
 *   entry at once, with the pieces as candidates.
 * - Equivalent, with pieces among the candidates: when every piece gives the consumer the same
 *   result (Entry::equivalent, for every member), the pieces are one candidate, represented by
 *   the one whose first name sorts first by bytes, and geometry doesn't run; other survivors
 *   don't count. Otherwise the entry breaks, with the pieces as candidates. Without pieces,
 *   Equivalent is One: a gone element's coplanar neighbour gives an attachment the same
 *   placement too (ops#68), so equivalence among unrelated survivors is no evidence.
 * - Several candidates: tier 2 keeps those whose intrinsic geometry agrees with the saved
 *   fingerprint (intrinsicAgrees()), if any do; among several of those, tier 3 keeps the one
 *   extrinsicNearest() chooses, if it chooses one. Geometry only narrows tier 1's survivors,
 *   never replaces them.
 * - No candidates: tiers 2 and 3 run on every pool element of the type (tier-0 elements
 *   excluded), and both must pass: the element extrinsicNearest() chooses among those tier 2
 *   keeps, or nothing ("no candidate").
 * - The entry then goes into one MatchGraph per owner, one candidate per element, and
 *   forcedMatching() decides.
 * - A partner one of whose names equals the old name up to the duplicate counter of any section
 *   (a pattern sibling) never resolves the entry: broken, with its candidates ("pattern
 *   sibling").
 * - A partner from tier 1 resolves the entry only if one of its names agrees with the old name
 *   on the top section (NameAncestry::topAgrees()) or has the old name in its ancestry;
 *   otherwise the entry is broken, with its candidates ("no top agreement"). A partner that
 *   only tiers 2 and 3 found needs both to have passed.
 *
 * The result depends only on the input as a set (pool order, name order, entry order).
 */
AppExport std::vector<SolveOutcome> solveOwner(const SolveInput& input);

}  // namespace Data
