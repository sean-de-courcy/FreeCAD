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
 * A pattern instance's copy `X|<tag>;TRF;<k>...` is the exception (ops#91): its prefix X stands for
 * the support's element, and the copy's history is X's history in instance k. So the prefix is
 * the node X in the context of instance k, and so is every node of A*(X) below it: the support's
 * elements and their copies share no ancestor, nor do two instances' copies, also where a name
 * embeds copies (a fusion's face bounded by an edge of each of two overlapping instances).
 *
 * Names are bare mapped names, as an element map stores them: no `;` prefix and no `.Edge1`
 * suffix. Each distinct node string gets a dense key on first sight, valid for the life of the
 * object (one solve), and each node's set is computed once, on its first query, as a sorted
 * vector of keys. Shared subtrees are computed once. The keys depend on the order of the queries,
 * the results never do: every function below answers the same whatever was asked before.
 */
/// How NameAncestry::overlap() measures shared ancestry (tier 1's variants, Task 2 PR 8).
enum class OverlapMeasure
{
    /// The share of the old name's ancestors that the candidate has.
    Plain,
    /// The same, each ancestor weighted by 2^-d, d its shortest depth below the old name (the
    /// name itself 0, its prefix and embedded names 1, ...).
    DepthWeighted,
    /// Plain, with every first section's Reference IDs as leaves of their own, qualified by the
    /// section's tag (`g2v1@<sketch tag>`): a vertex named by `g1v2,g2v1` and one renamed to
    /// `g12v2,g2v1` share `g2v1` (ops#76).
    ReferenceIds,
};

class AppExport NameAncestry
{
public:
    using Key = std::uint32_t;
    /// Sorted, unique keys.
    using KeySet = std::vector<Key>;

    explicit NameAncestry(OverlapMeasure measure = OverlapMeasure::Plain)
        : _measure(measure)
    {}

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

    /** True if \a a and \a b are single sections naming the same element of a source shape by
     * its index (the IDX flag, e.g. `Face6;_;<tag>;MKR;0;F;0;IDX,SRC;_`): equal in every field
     * but the op code, the flags compared as sets. A shape without an element map gives its
     * elements such names, and their op code follows what last touched them (MKR whole, FUS or
     * CUT as a modified face's prefix), so the op code isn't part of the element's identity.
     * A duplicate counter written over the op code (`_2`) is: such a section relates to no
     * other. False for a name that isn't one IDX section.
     */
    static bool sameIndexSource(std::string_view a, std::string_view b);

    /** The IDX section \a name stands for: \a name itself if it is a single IDX section, or its
     * first section if that is an IDX section and \a name is a split piece of it (isPieceOf());
     * otherwise empty. A view into \a name.
     */
    static std::string_view indexSource(std::string_view name);

    /** True if \a name is a split piece of an IDX section of the same source as \a oldName
     * (sameIndexSource()), but under another op code: isPieceOf() up to the op code of the
     * first section. \a oldName must be a single IDX section.
     */
    static bool isIndexPieceOf(std::string_view name, std::string_view oldName);

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
    // A Reference ID leaf (OverlapMeasure::ReferenceIds): a node that no name can be, whose set
    // is itself.
    Key internReferenceId(const std::string& id, const std::string& tag);
    // The depth-weighted share (OverlapMeasure::DepthWeighted).
    double weightedOverlap(Key oldKey, const KeySet& candidateSet);

    OverlapMeasure _measure;
    // By key. Deques, so that interning a node keeps the views in _keys and the references to
    // computed sets valid.
    std::deque<std::string> _names;
    std::deque<KeySet> _sets;
    std::deque<std::vector<Key>> _children;  // the prefix and embedded names, once computed
    std::deque<char> _done;  // _sets[key] is computed
    std::unordered_map<std::string_view, Key> _keys;
    std::size_t _computed = 0;
    // Per old name: its ancestors' weights (DepthWeighted), sorted by key, and their sum.
    std::unordered_map<Key, std::pair<std::vector<std::pair<Key, double>>, double>> _weights;
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

/// The geometric check of a partner that tier 1 alone found (Task 2 PR 8, ops#87), for a
/// reference with a saved fingerprint: none, the same element type and kind, or intrinsicAgrees().
enum class Tier1Check
{
    None,
    Kind,
    Intrinsic,
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
    /// atSamePlace(): the largest relative difference of sizes (ops#105).
    double placeSize = 1e-6;
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

/** The geometric continuation's trigger (Task 2 PR 7): true if \a saved, the fingerprint saved
 * with a reference, is a line edge, or (PR 7b) an arc with its circle's centre, and \a now, its
 * exact element's current fingerprint, lies within it and is shorter by more than ε. A line
 * within a line: the same line within \a tolerances.angle and ε, both ends within the old ends'
 * ε. An arc within an arc: the same circle (axis within the angle; radius, centre and plane
 * within ε), its arc-length extent within the old arc's. ε is \a distance times
 * max(1, \a diagonal). A version-1 circle (no centre) and a nearly full arc aren't located.
 */
AppExport bool hitWithinOldEdge(
    const ElementFingerprint& saved,
    const ElementFingerprint& now,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
);

/** The split face's trigger (Task 2 PR 7, Q3 (b)): true if \a saved, the fingerprint saved with
 * a reference, is a plane, and \a now, its exact element's current fingerprint, is a plane in
 * the same plane (planeAgrees()) with an area smaller by more than \a distance relative.
 */
AppExport bool faceWithinOldPlane(
    const ElementFingerprint& saved,
    const ElementFingerprint& now,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
);

/** True if \a face is a plane in the plane of \a saved (a plane): its normal within
 * \a tolerances.angle with its sense, its centre within ε of that plane (ε is \a distance times
 * max(1, \a diagonal)).
 */
AppExport bool planeAgrees(
    const ElementFingerprint& saved,
    const ElementFingerprint& face,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
);

/** "Sits where it was" (ops#105): true if \a now coincides with \a saved, the fingerprint saved
 * with a reference. The same element type and kind; size, centre, direction and radii present in
 * both or in neither; the direction within \a tolerances.angle (a plane's normal with its sense,
 * an axis or a line's direction either way, as intrinsicAgrees()); radii within
 * \a tolerances.radius relative; the size within \a tolerances.placeSize relative; the centre,
 * and a circle's centre and a plane's extent corners when both have them, within ε (\a distance
 * times max(1, \a diagonal)). These are coincidence tolerances, far tighter than tier 3's: an
 * element 0.1 mm away isn't at the place. False if either fingerprint is invalid.
 */
AppExport bool atSamePlace(
    const ElementFingerprint& saved,
    const ElementFingerprint& now,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
);

/** A cheap necessary condition for atSamePlace(\a saved, the element's fingerprint), from the
 * element's \a intrinsic part (type, kind, direction, radii and a circle's centre, measured as
 * its fingerprint measures them) and \a anchor, a point of its plane (a plane face), its line (a
 * line edge) or the vertex itself. False only if atSamePlace() would be false: the intrinsic parts
 * disagree (intrinsicAgrees()), the circles' centres are apart by more than ε, or the saved centre
 * lies farther than 2ε from the plane, the line or the vertex (ε as in atSamePlace()).
 */
AppExport bool mayBeAtPlace(
    const ElementFingerprint& saved,
    const ElementFingerprint& intrinsic,
    const std::optional<Base::Vector3d>& anchor,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
);

/// Where a face lies against an old face's extent (fingerprint version 3, Task 2 PR 8).
enum class ExtentRelation
{
    /// A fingerprint has no extent: nothing is known.
    Unknown,
    /// Within the old face's bounding box (ε): it may be a piece of the old face.
    Inside,
    /// Partly within and partly outside it: a piece of the old face that runs past it, or not.
    Overlapping,
    /// Apart from it, or touching it only: it holds no point of the old face.
    Outside,
};

/** \a face's bounding box against \a saved's, both from version-3 fingerprints, with ε
 * (\a distance times max(1, \a diagonal)). On an axis the boxes are apart when their intervals
 * overlap by less than -ε, or touch (overlap within ε) while both are longer than ε there; a
 * degenerate interval (the normal's axis of an axis-aligned plane) never separates. The line
 * rule's within-the-old-ends test (hitWithinOldEdge()), for faces.
 */
AppExport ExtentRelation faceExtentRelation(
    const ElementFingerprint& saved,
    const ElementFingerprint& face,
    double diagonal,
    double distance
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
        /// Resolved exactly (tier 0) to exactElement, e.g. `Face3`, whose mapped name is
        /// exactName (the name the reference holds).
        bool exact = false;
        std::string exactElement;
        std::string exactName;
        /// The target's findSimilarNames() result for oldName, of any type.
        std::vector<std::string> nameMatches;
        /// The fingerprint saved with the reference, before this update; invalid if none (tiers
        /// 2 and 3 then don't run for it, and an exact entry doesn't continue).
        ElementFingerprint fingerprint;
        /// Equivalent: whether the consumer would get the same result from either of two
        /// elements of the target (index names, e.g. `Face7`). Unset: no two are equivalent.
        std::function<bool(const std::string&, const std::string&)> equivalent;
        /// The bare mapped name the reference named before it was expanded (Task 2 PR 7), or
        /// empty. References with the same scope and `from` are one group.
        std::string from;
        /// An opaque key of the reference's property and sub-object prefix.
        std::string scope;
        /// The reference's position in its property; a collapsing group keeps its lowest.
        int position = 0;
        /// Elements the user rejected for this reference (ops#127, App::markReferenceBroken()):
        /// never its candidates, at any tier.
        std::vector<std::string> excluded;
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
    OverlapMeasure measure = OverlapMeasure::Plain;
    Tier1Check check = Tier1Check::Intrinsic;
    /// Tiers 2 and 3.
    GeometryTolerances tolerances;
    /// The target's bounding-box diagonal, the scale of tier 3's d_max.
    double diagonal = 0.0;
    /// The target's tag as names write it (decimal), if the target has no element map; empty
    /// otherwise. An entry whose IDX source (NameAncestry::indexSource()) carries this tag
    /// names the target's element by that index, which needs no pool entry (Q5).
    std::string maplessTag;
    /// The current fingerprint of the target's element \a index (e.g. `Face7`); invalid if it
    /// can't be measured. Called at most once per element, only when tiers 2 and 3 run. Unset:
    /// no element has a fingerprint.
    std::function<ElementFingerprint(const std::string& index)> fingerprintOf;
    /// The element \a index's cheap description for mayBeAtPlace(): false if there is none.
    /// Unset: none. The moved-element check fingerprints only the elements it doesn't rule out.
    std::function<bool(const std::string& index,
                       ElementFingerprint& intrinsic,
                       std::optional<Base::Vector3d>& anchor)>
        hintOf;
    /// The faces of the target that the edge \a index bounds (index names). Unset: none, so
    /// no edge continues.
    std::function<std::vector<std::string>(const std::string& index)> facesOf;
    /// The faces of the target that share an edge with the face \a index (index names). Unset:
    /// none, so no face is split by a coplanar one.
    std::function<std::vector<std::string>(const std::string& index)> neighboursOf;
    /// The continuation's distance ε, as a share of max(1, diagonal) (hitWithinOldEdge()).
    double continuationDistance = 1e-7;
};

enum class SolveStatus
{
    /// Resolved by the exact lookup (tier 0), before the solver.
    Exact,
    /// Resolved by the solver.
    Resolved,
    /// Not resolved: the reference stays missing (an exact one becomes missing).
    Broken,
    /// A member of a collapsing group other than the one that stays: the reference goes.
    Removed,
    /// Resolved provisionally by a guess rule (ops#127, design note N2 section 5): the reference
    /// takes the element with a warning and a record of the original. Not produced yet (P6).
    Guessed,
};

struct AppExport SolveOutcome
{
    SolveStatus status = SolveStatus::Broken;
    /// Exact and Resolved: the element, e.g. `Face7`, and its mapped name (the first of its
    /// names by bytes; empty if it has none).
    std::string element;
    std::string name;
    /// 0 for Exact; for Resolved the tier that decided: 0 (a collapse, the `from` name found
    /// exactly), 1 (structure; an expansion to the pieces), 2 (intrinsic geometry narrowed tier
    /// 1's survivors to one), 3 (extrinsic geometry did, or found the element when tier 1 found
    /// nothing), 4 (the geometric continuation of a tier-0 hit); -1 for Broken.
    int tier = -1;
    /// An expansion (Expand): every element, in index order, with its mapped name; element
    /// and name are the first. Empty otherwise.
    std::vector<std::string> elements;
    std::vector<std::string> names;
    /// The expansion's `from`: the entry's own, or the name it expands.
    std::string from;
    /// Resolved by a collapse: the group's `from` is cleared.
    bool collapsed = false;
    /// Broken: the candidates the user may choose from, pieces first, each part in index order,
    /// with their mapped names (parallel). Resolved by tier 2 or 3 (ops#127): the other
    /// candidates tier 1 found, which the user may prefer to the one geometry chose.
    std::vector<std::string> candidates;
    std::vector<std::string> candidateNames;
    /// Parallel to candidates: why each is one (ops#105): `place` (it sits where the element
    /// was), `name` (the element the reference's name holds), `piece` (a piece of the old
    /// element), `structural` (tier 1's survivor), `geometric` (tiers 2-3 found it); and its
    /// centre's distance from the saved centre, NaN where unknown.
    std::vector<std::string> candidateRoles;
    std::vector<double> candidateDistances;
    /// The evidence, for the log and the report: overlap and sources, or why it broke.
    std::string evidence;
};

/** Tiers 0-4 and forced matching for one owner's references to one target (Task 2 PRs 3-7).
 *
 * - Exact entries keep their element, and it leaves the other entries' pools unless one of its
 *   names has the entry's old name in its ancestry (a proven merge, an inAncestry edge). Exact
 *   entries never enter the graph.
 * - Moved (ops#105): an exact entry whose element no longer sits where its saved fingerprint was
 *   (atSamePlace()), while other elements of its type do, is ambiguous: its name says one
 *   element, geometry the others. It breaks under One and Expand, with those elements first
 *   (role `place`) and the named one last (`name`); under Equivalent the hit stands if each of
 *   them gives the consumer the hit's result. Those elements leave the other entries' pools, as
 *   tier-0 elements do. An element that moved with nothing at its old place keeps its reference.
 * - Collapse (PR 7): the entries with the same scope and `from` are a group. When `from` names
 *   an element of the target exactly and every member is exact on that element or missing and
 *   merged back into it (a structural piece of `from`, or saved geometry lying on the element
 *   as it is now), the member with the lowest position resolves to it (tier 0, `collapsed`)
 *   and the others are Removed. Otherwise the members are solved one by one.
 * - Candidates include every element with a structural piece of the old name, whatever tier 1's
 *   filters keep.
 * - Continuation (PR 7, tier 4): an exact `Edge` entry whose saved fingerprint is a line or an
 *   arc that its element now lies strictly within (hitWithinOldEdge()). The other edges of the
 *   type, not held exactly by the owner, that lie on the old edge within its ends and bound a
 *   face the hit bounds (facesOf) are its continuations. Expand takes them (Resolved, every
 *   element); One breaks the entry with the hit and them as candidates; Equivalent keeps the
 *   hit if every continuation is equivalent to it, and breaks otherwise. Such an edge that runs
 *   past the old end, or pieces that overlap, break the entry under every policy. The
 *   continuations taken leave the other entries' pools, as tier-0 elements do.
 * - A split face (PR 7, detected, never taken): an exact planar `Face` entry whose element
 *   still lies in the plane of its saved fingerprint (the normal with its sense, the centre
 *   within ε of the plane) but is smaller. Another planar face of that plane, not held exactly
 *   by the owner, that shares an edge or a neighbouring face with it may be the rest of the old
 *   face: the entry breaks, with both, under One and Expand, and under Equivalent unless every
 *   such face gives the consumer the hit's result. With the old face's extent (PR 8,
 *   faceExtentRelation()), a face outside it is no piece and doesn't count, and one that runs
 *   past it breaks the entry under every policy; without, every such face counts.
 * - Expand (PR 7), with pieces among the candidates: the pieces resolve together, as one graph
 *   node (tier 1, every element); the other survivors don't count.
 * - Missing entries with the same old name, type and policy are solved once and get the same
 *   outcome. Geometry runs for them only if they all hold the same valid fingerprint.
 * - Candidates: the overlap survivors (NameAncestry::structuralSurvivors() over every name of
 *   every pool element of the entry's type) and the name matches of that type, by \a source.
 * - The IDX source (Task 2 PR 6): when the old name stands for an IDX section
 *   (NameAncestry::indexSource()), the elements named by a section of the same source under any
 *   op code (NameAncestry::sameIndexSource()), and, for a target without an element map whose
 *   tag the section carries, the target's element of that index (Q5). Those whose intrinsic
 *   geometry agrees with the saved fingerprint (tier 2) replace the other candidates; without
 *   a fingerprint, or if none agrees, they don't count. Split pieces of the old IDX element
 *   under another op code (NameAncestry::isIndexPieceOf()) are pieces like any other.
 * - One: a candidate that is a piece of the old element breaks the entry at once, with the
 *   pieces as candidates.
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
 *   on the top section (NameAncestry::topAgrees()), has the old name in its ancestry, comes
 *   from the IDX source, or stands for equivalent pieces; otherwise the entry is broken, with
 *   its candidates ("no top agreement"). A partner that only tiers 2 and 3 found needs both to
 *   have passed.
 *
 * The result depends only on the input as a set (pool order, name order, entry order).
 */
AppExport std::vector<SolveOutcome> solveOwner(const SolveInput& input);

}  // namespace Data
