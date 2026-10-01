// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <App/ElementNamingUtils.h>
#include <App/ElementFingerprint.h>
#include <App/ElementSolver.h>
#include <App/ElementSolverBatch.h>
#include <App/PropertyLinks.h>
#include <App/ReferenceReport.h>
#include <App/MappedName.h>
#include <Base/Exception.h>

#include <algorithm>
#include <cmath>
#include <functional>
#include <map>
#include <numeric>
#include <random>
#include <set>
#include <string>
#include <vector>

using Data::MatchGraph;
using Data::MatchResult;
using Data::MatchStatus;
using Data::NameAncestry;

namespace
{

// Designed V2 names, built with the encoder as an operation builds them.

std::string section(
    const std::vector<std::string>& referenceIDs,
    const std::vector<std::string>& linkedNames,
    int tag,
    const char* opCode,
    int index,
    char elementType,
    const std::vector<std::string>& flags,
    const std::vector<std::string>& connected = {}
)
{
    return Data::MappedName::makeEncodedSection(
        referenceIDs,
        linkedNames,
        std::to_string(tag),
        opCode,
        std::to_string(index),
        elementType,
        "0",
        flags,
        connected
    );
}

// A sketch edge: `g<id>;_;<sketch tag>;SKT;0;E;0;SRC;_`.
std::string sketchEdge(int geoId, int sketchTag = 5)
{
    return section({"g" + std::to_string(geoId)}, {}, sketchTag, "SKT", 0, 'E', {"SRC"});
}

// A sketch vertex with the given Reference IDs, e.g. {"g1v2", "g2v1"}.
std::string sketchVertex(const std::vector<std::string>& ids, int sketchTag = 5)
{
    return section(ids, {}, sketchTag, "SKT", 0, 'V', {"SRC"});
}

// A sketch face: `_;<outer-wire edges>;<tag>;FAC;0;F;0;LOW;_`.
std::string lowFace(const std::vector<std::string>& edges, int tag = 5)
{
    return section({}, edges, tag, "FAC", 0, 'F', {"LOW"});
}

std::string generated(
    const std::vector<std::string>& sources,
    int tag,
    const char* opCode,
    char elementType,
    int index = 0
)
{
    return section({}, sources, tag, opCode, index, elementType, {"GEN"});
}

std::string upper(const std::vector<std::string>& faces, int tag, const char* opCode)
{
    return section({}, faces, tag, opCode, 0, 'E', {"UPP"});
}

// A split piece of \a incoming: a MOD section appended with `|`.
std::string piece(
    const std::string& incoming,
    int tag,
    const char* opCode,
    int index,
    char elementType,
    const std::vector<std::string>& connected = {}
)
{
    return incoming + "|" + section({}, {}, tag, opCode, index, elementType, {"MOD"}, connected);
}

}  // namespace

// ---------------------------------------------------------------------------------------------
// Ancestor sets

TEST(NameAncestry, sketchEdgeIsItsOwnAncestry)
{
    NameAncestry ancestry;
    const auto edge = sketchEdge(1);
    EXPECT_EQ(edge, "g1;_;5;SKT;0;E;0;SRC;_");
    EXPECT_EQ(ancestry.ancestorNames(edge), std::vector<std::string> {edge});
}

TEST(NameAncestry, faceHoldsItsLinkedEdges)
{
    NameAncestry ancestry;
    const auto e1 = sketchEdge(1);
    const auto e2 = sketchEdge(2);
    const auto e3 = sketchEdge(3);
    const auto face = lowFace({e1, e2, e3});

    std::vector<std::string> expected {face, e1, e2, e3};
    std::sort(expected.begin(), expected.end());
    //   the embedded names come back exactly as built: the decoder removed one escape level
    EXPECT_EQ(ancestry.ancestorNames(face), expected);
    EXPECT_TRUE(ancestry.contains(face, e2));
    EXPECT_FALSE(ancestry.contains(e2, face));
}

TEST(NameAncestry, sharedSubtreeCountsOnce)
{
    // Arrange
    //   an UPP edge between two faces; both faces hold sketch edge 2
    NameAncestry ancestry;
    const auto e1 = sketchEdge(1);
    const auto e2 = sketchEdge(2);
    const auto e3 = sketchEdge(3);
    const auto f1 = generated({e1, e2}, 7, "Extrude", 'F');
    const auto f2 = generated({e2, e3}, 7, "Extrude", 'F', 1);
    const auto edge = upper({f1, f2}, 9, "FLT");

    // Act
    const auto& keys = ancestry.ancestors(edge);

    // Assert
    std::vector<std::string> expected {edge, f1, f2, e1, e2, e3};
    std::sort(expected.begin(), expected.end());
    EXPECT_EQ(ancestry.ancestorNames(edge), expected);
    EXPECT_EQ(keys.size(), 6U);
    EXPECT_TRUE(std::is_sorted(keys.begin(), keys.end()));
    //   every node was interned and computed once: e2 is shared but has one set
    EXPECT_EQ(ancestry.nodeCount(), 6U);
    EXPECT_EQ(ancestry.computedCount(), 6U);
    //   a second query computes nothing
    ancestry.ancestors(f1);
    ancestry.ancestors(edge);
    EXPECT_EQ(ancestry.computedCount(), 6U);
}

TEST(NameAncestry, pieceHoldsItsPrefixesAndConnectedNames)
{
    // Arrange
    //   depth 4: a split piece of the UPP edge, bounded by a vertex (a Connected Name), split
    //   again
    NameAncestry ancestry;
    const auto e1 = sketchEdge(1);
    const auto e2 = sketchEdge(2);
    const auto f1 = generated({e1}, 7, "Extrude", 'F');
    const auto f2 = generated({e2}, 7, "Extrude", 'F', 1);
    const auto edge = upper({f1, f2}, 9, "FLT");
    const auto vertex = sketchVertex({"g1v2", "g2v1"});
    const auto first = piece(edge, 11, "CUT", 0, 'E', {vertex});
    const auto second = piece(first, 12, "CUT", 1, 'E');

    // Act
    const auto names = ancestry.ancestorNames(second);

    // Assert
    std::vector<std::string> expected {second, first, edge, f1, f2, e1, e2, vertex};
    std::sort(expected.begin(), expected.end());
    EXPECT_EQ(names, expected);
    EXPECT_TRUE(ancestry.contains(second, edge));
    EXPECT_TRUE(ancestry.contains(first, vertex));
    EXPECT_FALSE(ancestry.contains(edge, first));
}

TEST(NameAncestry, sectionsSplitOnlyAtTopLevel)
{
    const auto e1 = sketchEdge(1);
    const auto inner = piece(e1, 7, "CUT", 0, 'E');
    //   the piece is embedded in a face, so its `|` is escaped there
    const auto face = generated({inner}, 8, "Extrude", 'F');
    const auto split = piece(face, 9, "CUT", 0, 'F');

    EXPECT_EQ(NameAncestry::splitSections(e1).size(), 1U);
    EXPECT_EQ(NameAncestry::splitSections(inner).size(), 2U);
    EXPECT_EQ(NameAncestry::splitSections(face).size(), 1U);
    ASSERT_EQ(NameAncestry::splitSections(split).size(), 2U);
    EXPECT_EQ(NameAncestry::splitSections(split).front(), face);
    EXPECT_TRUE(NameAncestry::splitSections("").empty());

    NameAncestry ancestry;
    std::vector<std::string> expected {split, face, inner, e1};
    std::sort(expected.begin(), expected.end());
    EXPECT_EQ(ancestry.ancestorNames(split), expected);
}

TEST(NameAncestry, emptyName)
{
    NameAncestry ancestry;
    EXPECT_TRUE(ancestry.ancestors("").empty());
    EXPECT_EQ(ancestry.overlap("", sketchEdge(1)), 0.0);
    EXPECT_FALSE(ancestry.contains("", ""));
    EXPECT_FALSE(NameAncestry::topAgrees("", sketchEdge(1)));
}

// ---------------------------------------------------------------------------------------------
// Overlap, top agreement, tier 1's survivors

TEST(NameAncestry, overlapWhenTheOuterWireGainsAnEdge)
{
    // Arrange
    //   the design's example (naming-design.md section 5): a sketch's outer wire gains an edge,
    //   so the old top face's linked edges are a subset of the new top face's
    NameAncestry ancestry;
    std::vector<std::string> edges {sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)};
    const auto oldTop = lowFace(edges);
    edges.push_back(sketchEdge(5));
    const auto newTop = lowFace(edges);
    const auto side = generated({sketchEdge(1)}, 7, "Extrude", 'F');
    const auto unrelated = generated({sketchEdge(9, 6)}, 7, "Extrude", 'F', 1);

    // Act and assert
    //   A(old) = {old, e1..e4}: the new top face holds the four edges, the side face one
    EXPECT_DOUBLE_EQ(ancestry.overlap(oldTop, newTop), 4.0 / 5.0);
    EXPECT_DOUBLE_EQ(ancestry.overlap(oldTop, side), 1.0 / 5.0);
    EXPECT_DOUBLE_EQ(ancestry.overlap(oldTop, unrelated), 0.0);
    EXPECT_DOUBLE_EQ(ancestry.overlap(oldTop, oldTop), 1.0);
    //   the share is of the old name's set, so it is not symmetric
    EXPECT_DOUBLE_EQ(ancestry.overlap(newTop, oldTop), 4.0 / 6.0);

    EXPECT_TRUE(NameAncestry::topAgrees(oldTop, newTop));
    EXPECT_FALSE(NameAncestry::topAgrees(oldTop, side));
}

TEST(NameAncestry, survivorsWithinTheGap)
{
    NameAncestry ancestry;
    std::vector<std::string> edges {sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)};
    const auto oldTop = lowFace(edges);
    edges.push_back(sketchEdge(5));
    const std::vector<std::string> candidates {
        generated({sketchEdge(1)}, 7, "Extrude", 'F'),        // overlap 0.2, GEN
        lowFace(edges),                                       // overlap 0.8, LOW
        generated({sketchEdge(9, 6)}, 7, "Extrude", 'F', 1),  // overlap 0
    };

    //   g = 0.25: only the new top face is within the gap of the best
    EXPECT_EQ(ancestry.structuralSurvivors(oldTop, candidates, 0.25), std::vector<int> {1});
    //   a wide gap keeps the side face on overlap, and the top section drops it: the new top
    //   face agrees with the old one on opcode and flags, the side face doesn't
    EXPECT_EQ(ancestry.structuralSurvivors(oldTop, candidates, 1.0), std::vector<int> {1});
    //   with no candidate agreeing on the top section, overlap alone decides
    const std::vector<std::string> generatedOnly {candidates[0], candidates[2]};
    EXPECT_EQ(ancestry.structuralSurvivors(oldTop, generatedOnly, 1.0), std::vector<int> {0});
    //   no overlap at all: no survivor
    EXPECT_TRUE(ancestry.structuralSurvivors(oldTop, {candidates[2]}, 1.0).empty());
    //   a gap of 0 keeps the best only
    EXPECT_EQ(ancestry.structuralSurvivors(oldTop, generatedOnly, 0.0), std::vector<int> {0});
}

TEST(NameAncestry, survivorAtTheExactGapBoundary)
{
    // A(old) = {old, e1..e4}; candidates with overlaps 0.8 and 0.4: a gap of 0.4 keeps both.
    NameAncestry ancestry;
    std::vector<std::string> edges {sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)};
    const auto oldTop = lowFace(edges);
    const std::vector<std::string> candidates {
        lowFace({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4), sketchEdge(5)}),
        lowFace({sketchEdge(1), sketchEdge(2)}),
    };
    EXPECT_EQ(ancestry.structuralSurvivors(oldTop, candidates, 0.4), (std::vector<int> {0, 1}));
    EXPECT_EQ(ancestry.structuralSurvivors(oldTop, candidates, 0.39), std::vector<int> {0});
}

// ---------------------------------------------------------------------------------------------
// Pieces

TEST(NameAncestry, piecesAreTheOldNameWithModSections)
{
    const auto x = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    const auto y = generated({sketchEdge(2)}, 7, "Extrude", 'E', 1);
    const auto once = piece(x, 9, "CUT", 0, 'E');
    const auto twice = piece(once, 10, "FUS", 1, 'E');

    EXPECT_TRUE(NameAncestry::isPieceOf(once, x));
    EXPECT_TRUE(NameAncestry::isPieceOf(twice, x));
    EXPECT_TRUE(NameAncestry::isPieceOf(twice, once));
    //   not pieces
    EXPECT_FALSE(NameAncestry::isPieceOf(x, x));
    EXPECT_FALSE(NameAncestry::isPieceOf(x, once));
    EXPECT_FALSE(NameAncestry::isPieceOf(piece(y, 9, "CUT", 0, 'E'), x));
    const auto generatedAfter = x + "|" + section({}, {}, 9, "CUT", 0, 'E', {"GEN"});
    EXPECT_FALSE(NameAncestry::isPieceOf(generatedAfter, x));
    //   a MOD section followed by a GEN one: every added section must be MOD
    const auto thenGenerated = once + "|" + section({}, {}, 10, "FUS", 0, 'E', {"GEN"});
    EXPECT_FALSE(NameAncestry::isPieceOf(thenGenerated, x));
    //   a MOD section of another element type
    EXPECT_FALSE(NameAncestry::isPieceOf(piece(x, 9, "CUT", 0, 'F'), x));
    //   the old name must end at a section boundary
    const auto offBoundary = x + "0|" + section({}, {}, 9, "CUT", 0, 'E', {"MOD"});
    EXPECT_FALSE(NameAncestry::isPieceOf(offBoundary, x));
    EXPECT_FALSE(NameAncestry::isPieceOf(once, ""));
    //   a name holding the piece embedded is not a piece
    EXPECT_FALSE(NameAncestry::isPieceOf(generated({once}, 11, "FLT", 'E'), x));
}

TEST(NameAncestry, cornerEdgeAfterTheNotchIsNotAPiece)
{
    // ops#76: the vertical edge at the sketch corner (20, 0) comes from the vertex `g1v2,g2v1`.
    // After the front notch, the corner's vertex is `g12v2,g2v1`, and the notch's corner at
    // (8, 0) is `g1v2,g9v1`. Neither new edge is a piece of the old one, and nodes alone share
    // nothing with it (the Reference ID variant is PR 8's).
    NameAncestry ancestry;
    const auto oldEdge = generated({sketchVertex({"g1v2", "g2v1"})}, 7, "Extrude", 'E');
    const auto corner = generated({sketchVertex({"g12v2", "g2v1"})}, 7, "Extrude", 'E');
    const auto notch = generated({sketchVertex({"g1v2", "g9v1"})}, 7, "Extrude", 'E', 1);

    EXPECT_FALSE(NameAncestry::isPieceOf(corner, oldEdge));
    EXPECT_FALSE(NameAncestry::isPieceOf(notch, oldEdge));
    EXPECT_DOUBLE_EQ(ancestry.overlap(oldEdge, corner), 0.0);
    EXPECT_DOUBLE_EQ(ancestry.overlap(oldEdge, notch), 0.0);
    //   `g1;...` is a byte prefix of `g12;...` only up to the first field: no piece either
    const auto longerId = piece(sketchEdge(12), 9, "CUT", 0, 'E');
    EXPECT_FALSE(NameAncestry::isPieceOf(longerId, sketchEdge(1)));
}

// ---------------------------------------------------------------------------------------------
// Forced matching

namespace
{

MatchGraph graphWith(int entries, int candidates)
{
    MatchGraph graph;
    graph.entryCount = entries;
    for (int k = 0; k < candidates; ++k) {
        graph.addCandidate({k});
    }
    return graph;
}

std::vector<int> partners(const MatchResult& result)
{
    return result.partner;
}

}  // namespace

TEST(ForcedMatching, singleClearEdge)
{
    auto graph = graphWith(1, 1);
    graph.addEdge(0, 0);
    auto result = Data::forcedMatching(graph);
    EXPECT_EQ(partners(result), std::vector<int> {0});
    EXPECT_EQ(result.status[0], MatchStatus::Resolved);
}

TEST(ForcedMatching, entryWithoutCandidates)
{
    auto graph = graphWith(2, 1);
    graph.addEdge(1, 0);
    auto result = Data::forcedMatching(graph);
    EXPECT_EQ(partners(result), (std::vector<int> {-1, 0}));
    EXPECT_EQ(result.status[0], MatchStatus::NoCandidate);
    EXPECT_EQ(result.status[1], MatchStatus::Resolved);
}

TEST(ForcedMatching, symmetricSwapStaysBroken)
{
    // Two references, two symmetric candidates: each has a clear best on its own, but the
    // swapped assignment is just as good, so neither resolves.
    auto graph = graphWith(2, 2);
    graph.addEdge(0, 0);
    graph.addEdge(0, 1);
    graph.addEdge(1, 0);
    graph.addEdge(1, 1);
    auto result = Data::forcedMatching(graph);
    EXPECT_EQ(partners(result), (std::vector<int> {-1, -1}));
    EXPECT_EQ(result.status[0], MatchStatus::Ambiguous);
    EXPECT_EQ(result.status[1], MatchStatus::Ambiguous);
}

TEST(ForcedMatching, chainResolves)
{
    // A: {c}; B: {c, d}; C: {d, e}. Only A -> c, B -> d, C -> e matches all three.
    auto graph = graphWith(3, 3);
    graph.addEdge(0, 0);
    graph.addEdge(1, 0);
    graph.addEdge(1, 1);
    graph.addEdge(2, 1);
    graph.addEdge(2, 2);
    auto result = Data::forcedMatching(graph);
    EXPECT_EQ(partners(result), (std::vector<int> {0, 1, 2}));
}

TEST(ForcedMatching, oneCandidateTwoReferencesBreaksBoth)
{
    // An unproven many-to-one: two references, one candidate whose ancestry holds neither.
    auto graph = graphWith(2, 1);
    graph.addEdge(0, 0);
    graph.addEdge(1, 0);
    auto result = Data::forcedMatching(graph);
    EXPECT_EQ(partners(result), (std::vector<int> {-1, -1}));

    //   one proof is not a merge either
    auto half = graphWith(2, 1);
    half.addEdge(0, 0, true);
    half.addEdge(1, 0);
    EXPECT_EQ(partners(Data::forcedMatching(half)), (std::vector<int> {-1, -1}));
}

TEST(ForcedMatching, provenMergeMapsTwoToOne)
{
    // Two faces merged by a boolean: the merged face's ancestry holds both old names.
    auto graph = graphWith(2, 1);
    graph.addEdge(0, 0, true);
    graph.addEdge(1, 0, true);
    auto result = Data::forcedMatching(graph);
    EXPECT_EQ(partners(result), (std::vector<int> {0, 0}));

    //   three into one, with a fourth reference elsewhere
    auto three = graphWith(4, 2);
    three.addEdge(0, 0, true);
    three.addEdge(1, 0, true);
    three.addEdge(2, 0, true);
    three.addEdge(3, 1);
    EXPECT_EQ(partners(Data::forcedMatching(three)), (std::vector<int> {0, 0, 0, 1}));
}

TEST(ForcedMatching, mergeTakesNoUnprovenReference)
{
    // A and B are proven to have merged into c; B could also be d; E survived for c without
    // proof. A matching may use c for {A, B} or for one reference, never for E with A. The
    // maximum matchings {A c, B c}, {A c, B d} and {E c, B d} disagree on everyone: nothing
    // resolves, and in particular B is not sent to d.
    auto graph = graphWith(3, 2);
    graph.addEdge(0, 0, true);
    graph.addEdge(1, 0, true);
    graph.addEdge(1, 1);
    graph.addEdge(2, 0);
    auto result = Data::forcedMatching(graph);
    EXPECT_EQ(partners(result), (std::vector<int> {-1, -1, -1}));
}

TEST(ForcedMatching, pieceSetNodes)
{
    // Elements: pieces p1 = 1 and p2 = 2 of A's split element, and q = 3. A expands to the piece
    // set {p1, p2}; B survived for p1 and for q.
    MatchGraph graph;
    graph.entryCount = 2;
    int pieces = graph.addCandidate({1, 2});
    int p1 = graph.addCandidate({1});
    int q = graph.addCandidate({3});
    graph.addEdge(0, pieces, true);
    graph.addEdge(1, p1);
    graph.addEdge(1, q);
    auto result = Data::forcedMatching(graph);
    //   B on p1 would leave A without its pieces: A takes the set, B takes q
    EXPECT_EQ(partners(result), (std::vector<int> {pieces, q}));

    //   without q, A and B compete for p1: both break
    MatchGraph contested;
    contested.entryCount = 2;
    pieces = contested.addCandidate({1, 2});
    p1 = contested.addCandidate({1});
    contested.addEdge(0, pieces, true);
    contested.addEdge(1, p1);
    EXPECT_EQ(partners(Data::forcedMatching(contested)), (std::vector<int> {-1, -1}));
}

TEST(ForcedMatching, limits)
{
    //   more merge candidates in one component than allowed
    auto graph = graphWith(2, 1);
    graph.addEdge(0, 0, true);
    graph.addEdge(1, 0, true);
    auto result = Data::forcedMatching(graph, 0);
    EXPECT_EQ(partners(result), (std::vector<int> {-1, -1}));
    EXPECT_EQ(result.status[0], MatchStatus::TooLarge);

    //   an exhaustive search over its step budget
    MatchGraph shared;
    shared.entryCount = 2;
    int pieces = shared.addCandidate({1, 2});
    int q = shared.addCandidate({2});
    shared.addEdge(0, pieces);
    shared.addEdge(1, q);
    EXPECT_EQ(Data::forcedMatching(shared, 10, 2).status[1], MatchStatus::TooLarge);
    //   within the budget: the candidates share an element, so the two references compete
    EXPECT_EQ(partners(Data::forcedMatching(shared)), (std::vector<int> {-1, -1}));
}

TEST(ForcedMatching, badIndicesThrow)
{
    auto graph = graphWith(1, 1);
    graph.addEdge(1, 0);
    EXPECT_THROW(Data::forcedMatching(graph), Base::ValueError);
    auto other = graphWith(1, 1);
    other.addEdge(0, 1);
    EXPECT_THROW(Data::forcedMatching(other), Base::ValueError);
}

namespace
{

// The definition, by enumeration: every assignment of entries to candidates (or none) in which
// each candidate is used by one entry or only by entries with an inAncestry edge to it, and used
// candidates share no element. An entry is resolved when every maximum assignment gives it the
// same candidate.
std::vector<int> bruteForce(const MatchGraph& graph)
{
    const int n = graph.entryCount;
    std::map<std::pair<int, int>, bool> edges;
    for (const auto& edge : graph.edges) {
        edges[{edge.entry, edge.candidate}] |= edge.inAncestry;
    }
    std::vector<std::vector<int>> options(static_cast<std::size_t>(n), std::vector<int> {-1});
    for (const auto& [key, inAncestry] : edges) {
        options[key.first].push_back(key.second);
    }

    int best = -1;
    std::vector<int> seen(static_cast<std::size_t>(n), -2);
    std::vector<char> ambiguous(static_cast<std::size_t>(n), 0);
    std::vector<int> assignment(static_cast<std::size_t>(n), -1);

    auto valid = [&]() {
        std::map<int, std::vector<int>> users;
        for (int e = 0; e < n; ++e) {
            if (assignment[e] >= 0) {
                users[assignment[e]].push_back(e);
            }
        }
        std::set<int> taken;
        for (const auto& [candidate, list] : users) {
            if (list.size() > 1) {
                for (int e : list) {
                    if (!edges.at({e, candidate})) {
                        return false;
                    }
                }
            }
            const std::set<int> elements(
                graph.candidates[candidate].elements.begin(),
                graph.candidates[candidate].elements.end()
            );
            for (int element : elements) {
                if (!taken.insert(element).second) {
                    return false;
                }
            }
        }
        return true;
    };

    std::function<void(int)> enumerate = [&](int e) {
        if (e == n) {
            if (!valid()) {
                return;
            }
            int size = static_cast<int>(
                std::count_if(assignment.begin(), assignment.end(), [](int k) { return k >= 0; })
            );
            if (size > best) {
                best = size;
                std::fill(seen.begin(), seen.end(), -2);
                std::fill(ambiguous.begin(), ambiguous.end(), 0);
            }
            if (size == best) {
                for (int i = 0; i < n; ++i) {
                    if (seen[i] == -2) {
                        seen[i] = assignment[i];
                    }
                    else if (seen[i] != assignment[i]) {
                        ambiguous[i] = 1;
                    }
                }
            }
            return;
        }
        for (int option : options[e]) {
            assignment[e] = option;
            enumerate(e + 1);
        }
        assignment[e] = -1;
    };
    enumerate(0);

    std::vector<int> result(static_cast<std::size_t>(n), -1);
    for (int e = 0; e < n; ++e) {
        if (!ambiguous[e] && seen[e] >= 0) {
            result[e] = seen[e];
        }
    }
    return result;
}

MatchGraph randomGraph(std::mt19937& random, bool sharedElements)
{
    std::uniform_int_distribution<int> size(1, 5);
    std::uniform_int_distribution<int> coin(0, 1);
    std::uniform_int_distribution<int> percent(0, 99);
    MatchGraph graph;
    graph.entryCount = size(random);
    int candidates = size(random);
    for (int k = 0; k < candidates; ++k) {
        if (sharedElements) {
            // one or two elements out of six
            std::uniform_int_distribution<int> element(1, 6);
            std::vector<int> elements {element(random)};
            if (coin(random)) {
                elements.push_back(element(random));
            }
            graph.addCandidate(elements);
        }
        else {
            graph.addCandidate({100 + k});
        }
    }
    for (int e = 0; e < graph.entryCount; ++e) {
        for (int k = 0; k < candidates; ++k) {
            if (percent(random) < 45) {
                graph.addEdge(e, k, percent(random) < 40);
            }
        }
    }
    return graph;
}

}  // namespace

TEST(ForcedMatching, agreesWithEnumeration)
{
    // Random small graphs, both solvers (augmenting paths without shared elements, the
    // exhaustive search with them), against the definition.
    std::mt19937 random(20261001);
    int resolved = 0;
    int unresolved = 0;
    int merged = 0;
    for (int round = 0; round < 3000; ++round) {
        bool shared = round % 2 == 1;
        auto graph = randomGraph(random, shared);
        auto expected = bruteForce(graph);
        EXPECT_EQ(partners(Data::forcedMatching(graph)), expected)
            << "round " << round << (shared ? " (shared elements)" : "");
        std::map<int, int> users;
        for (int partner : expected) {
            (partner >= 0 ? resolved : unresolved) += 1;
            if (partner >= 0 && ++users[partner] == 2) {
                ++merged;
            }
        }
    }
    //   the random graphs cover resolved and broken entries, and proven merges
    EXPECT_GT(resolved, 1000);
    EXPECT_GT(unresolved, 1000);
    EXPECT_GT(merged, 50);
}

TEST(ForcedMatching, independentOfInputOrder)
{
    // Arrange
    //   one graph with a chain, a symmetric pair, a proven merge, a piece set and a lone entry
    MatchGraph graph;
    graph.entryCount = 9;
    for (int k = 0; k < 8; ++k) {
        graph.addCandidate({k});
    }
    int pieces = graph.addCandidate({20, 21});
    int piece = graph.addCandidate({20});
    int spare = graph.addCandidate({22});
    //   chain: 0 -> {0}, 1 -> {0, 1}, 2 -> {1, 2}
    graph.addEdge(0, 0);
    graph.addEdge(1, 0);
    graph.addEdge(1, 1);
    graph.addEdge(2, 1);
    graph.addEdge(2, 2);
    //   symmetric: 3, 4 -> {3, 4}
    graph.addEdge(3, 3);
    graph.addEdge(3, 4);
    graph.addEdge(4, 3);
    graph.addEdge(4, 4);
    //   proven merge: 5, 6 -> 5
    graph.addEdge(5, 5, true);
    graph.addEdge(6, 5, true);
    //   piece set: 7 -> pieces; 8 -> {piece, spare}
    graph.addEdge(7, pieces, true);
    graph.addEdge(8, piece);
    graph.addEdge(8, spare);
    //   candidates 6 and 7 have no edges
    const auto expected = Data::forcedMatching(graph);
    ASSERT_EQ(expected.partner, (std::vector<int> {0, 1, 2, -1, -1, 5, 5, pieces, spare}));

    // Act and assert
    std::mt19937 random(7);
    for (int round = 0; round < 100; ++round) {
        std::vector<int> entryOrder(graph.entryCount);
        std::iota(entryOrder.begin(), entryOrder.end(), 0);
        std::shuffle(entryOrder.begin(), entryOrder.end(), random);
        std::vector<int> candidateOrder(graph.candidates.size());
        std::iota(candidateOrder.begin(), candidateOrder.end(), 0);
        std::shuffle(candidateOrder.begin(), candidateOrder.end(), random);
        std::vector<int> elementLabels(30);
        std::iota(elementLabels.begin(), elementLabels.end(), 0);
        std::shuffle(elementLabels.begin(), elementLabels.end(), random);

        //   new index of old entry e: entryOrder[e]; of old candidate k: candidateOrder[k]
        MatchGraph permuted;
        permuted.entryCount = graph.entryCount;
        permuted.candidates.resize(graph.candidates.size());
        for (std::size_t k = 0; k < graph.candidates.size(); ++k) {
            auto elements = graph.candidates[k].elements;
            for (int& element : elements) {
                element = elementLabels[element];
            }
            std::shuffle(elements.begin(), elements.end(), random);
            permuted.candidates[candidateOrder[k]].elements = elements;
        }
        auto edges = graph.edges;
        std::shuffle(edges.begin(), edges.end(), random);
        for (const auto& edge : edges) {
            permuted.addEdge(entryOrder[edge.entry], candidateOrder[edge.candidate], edge.inAncestry);
        }

        auto result = Data::forcedMatching(permuted);
        for (int e = 0; e < graph.entryCount; ++e) {
            int partner = expected.partner[e];
            EXPECT_EQ(result.partner[entryOrder[e]], partner < 0 ? -1 : candidateOrder[partner])
                << "round " << round << ", entry " << e;
            EXPECT_EQ(result.status[entryOrder[e]], expected.status[e]);
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Equivalence groups

TEST(GroupEquivalent, representativeIsTheFirstNameByBytes)
{
    // b, a and c give the same result; d doesn't.
    const std::vector<std::string> names {"b", "a", "c", "d"};
    auto groups = Data::groupEquivalent(names, [](int i, int j) { return i != 3 && j != 3; });
    EXPECT_EQ(groups, (std::vector<std::vector<int>> {{1, 0, 2}, {3}}));
}

TEST(GroupEquivalent, toleranceChainIsNotAGroup)
{
    // Placements 0, 0.6 and 1.2 apart, tolerance 1: x ~ y and y ~ z, but not x ~ z. A tolerance
    // isn't transitive, so the chain stays apart: three candidates, not one.
    const std::vector<std::string> names {"x", "y", "z", "w"};
    const std::vector<double> values {0.0, 0.6, 1.2, 1.2 + 1e-9};
    auto groups = Data::groupEquivalent(names, [&](int i, int j) {
        return std::abs(values[i] - values[j]) <= 1.0;
    });
    //   x, y, z and w form one component: y-w is within 1, x-z and x-w are not
    EXPECT_EQ(groups, (std::vector<std::vector<int>> {{3}, {0}, {1}, {2}}));

    const std::vector<double> close {0.0, 1e-9, 5.0, 5.0 + 1e-9, 10.0};
    const std::vector<std::string> faces {"Face1", "Face2", "Face3", "Face4", "Face5"};
    auto pairs = Data::groupEquivalent(faces, [&](int i, int j) {
        return std::abs(close[i] - close[j]) <= 1e-6;
    });
    EXPECT_EQ(pairs, (std::vector<std::vector<int>> {{0, 1}, {2, 3}, {4}}));
}

TEST(GroupEquivalent, independentOfInputOrder)
{
    const std::vector<std::string> names {"Face7", "Face12", "Face3", "Face30", "Face1", "Face21"};
    // the planes: Face7, Face3 and Face1 on z = 0; Face12 and Face30 on z = 5; Face21 alone
    const std::map<std::string, int>
        plane {{"Face7", 0}, {"Face3", 0}, {"Face1", 0}, {"Face12", 5}, {"Face30", 5}, {"Face21", 9}};
    auto byName = [&](const std::vector<std::string>& list) {
        auto groups = Data::groupEquivalent(list, [&](int i, int j) {
            return plane.at(list[i]) == plane.at(list[j]);
        });
        std::vector<std::vector<std::string>> named;
        for (const auto& group : groups) {
            std::vector<std::string> members;
            for (int i : group) {
                members.push_back(list[i]);
            }
            named.push_back(members);
        }
        return named;
    };
    const std::vector<std::vector<std::string>> expected {
        {"Face1", "Face3", "Face7"},
        {"Face12", "Face30"},
        {"Face21"},
    };
    EXPECT_EQ(byName(names), expected);

    std::mt19937 random(11);
    auto shuffled = names;
    for (int round = 0; round < 100; ++round) {
        std::shuffle(shuffled.begin(), shuffled.end(), random);
        EXPECT_EQ(byName(shuffled), expected) << "round " << round;
    }
}

// ---------------------------------------------------------------------------------------------
// solveOwner: tiers 0 and 1 and forced matching for one owner (Task 2 PR 3)

namespace
{

using Data::SolveInput;
using Data::SolveOutcome;
using Data::SolveStatus;

SolveInput::Element element(const std::string& index, std::vector<std::string> names)
{
    return SolveInput::Element {index, std::move(names)};
}

SolveInput::Entry missing(
    const std::string& oldName,
    const std::string& type = "Face",
    std::vector<std::string> nameMatches = {}
)
{
    SolveInput::Entry entry;
    entry.oldName = oldName;
    entry.type = type;
    entry.nameMatches = std::move(nameMatches);
    return entry;
}

SolveInput::Entry exact(const std::string& index, const std::string& type = "Face")
{
    SolveInput::Entry entry;
    entry.type = type;
    entry.exact = true;
    entry.exactElement = index;
    return entry;
}

// One line per outcome, for comparisons.
std::string describe(const SolveOutcome& outcome)
{
    std::string text = outcome.status == SolveStatus::Exact ? "exact"
        : outcome.status == SolveStatus::Resolved           ? "resolved"
                                                            : "broken";
    text += " " + outcome.element + " " + std::to_string(outcome.tier) + " [";
    for (const auto& candidate : outcome.candidates) {
        text += candidate + " ";
    }
    return text + "] " + outcome.evidence;
}

// The design's outer-wire example: the old top face, the new one (a fifth edge), a side face
// and an unrelated face.
struct OuterWire
{
    std::string oldTop = lowFace({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)});
    std::string newTop = lowFace(
        {sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4), sketchEdge(5)}
    );
    std::string side = generated({sketchEdge(1)}, 7, "Extrude", 'F');
    std::string unrelated = generated({sketchEdge(9, 6)}, 7, "Extrude", 'F', 1);
};

}  // namespace

TEST(SolveOwner, uniqueOverlapSurvivorResolves)
{
    OuterWire names;
    SolveInput input;
    input.pool["Face"] = {
        element("Face1", {names.side}),
        element("Face2", {names.newTop}),
        element("Face3", {names.unrelated}),
    };
    input.entries = {missing(names.oldTop)};

    auto outcomes = Data::solveOwner(input);

    ASSERT_EQ(outcomes.size(), 1U);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face2");
    EXPECT_EQ(outcomes[0].name, names.newTop);
    EXPECT_EQ(outcomes[0].tier, 1);
    EXPECT_EQ(outcomes[0].evidence, "overlap 0.80, sources overlap");
}

TEST(SolveOwner, twoEqualSurvivorsBreak)
{
    OuterWire names;
    const auto otherTop = lowFace(
        {sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4), sketchEdge(6)}
    );
    SolveInput input;
    input.pool["Face"] = {
        element("Face2", {names.newTop}),
        element("Face10", {otherTop}),
        element("Face1", {names.side}),
    };
    input.entries = {missing(names.oldTop)};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].tier, -1);
    //   in index order, with their names
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Face2", "Face10"}));
    EXPECT_EQ(outcomes[0].candidateNames, (std::vector<std::string> {names.newTop, otherTop}));
    EXPECT_EQ(outcomes[0].evidence, "ambiguous");
}

TEST(SolveOwner, piecesBreakAtOnceUnderOne)
{
    // A face split in two by a slot; the name match also offers another face.
    const auto old = generated({sketchEdge(1)}, 7, "Extrude", 'F');
    const auto other = generated({sketchEdge(2)}, 7, "Extrude", 'F', 1);
    SolveInput input;
    input.pool["Face"] = {
        element("Face1", {other}),
        element("Face2", {piece(old, 9, "CUT", 0, 'F')}),
        element("Face3", {piece(old, 9, "CUT", 1, 'F')}),
    };
    input.entries = {missing(old, "Face", {other})};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    //   pieces first, then the other candidates
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Face2", "Face3", "Face1"}));
    EXPECT_EQ(outcomes[0].evidence, "split into 2 pieces");

    //   Expand and Equivalent are read as One until PRs 5 and 7
    input.entries[0].policy = Data::SolvePolicy::Expand;
    EXPECT_EQ(describe(Data::solveOwner(input)[0]), describe(outcomes[0]));
}

TEST(SolveOwner, tierZeroElementsLeaveTheOtherPools)
{
    OuterWire names;
    SolveInput input;
    input.pool["Face"] = {
        element("Face1", {names.newTop}),
        element("Face2", {names.unrelated}),
    };
    //   another reference of the owner resolved exactly to Face1
    input.entries = {exact("Face1"), missing(names.oldTop)};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Exact);
    EXPECT_EQ(outcomes[0].element, "Face1");
    EXPECT_EQ(outcomes[0].name, names.newTop);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Broken);
    EXPECT_TRUE(outcomes[1].candidates.empty());
    EXPECT_EQ(outcomes[1].evidence, "no candidate");

    //   unless tier 1 shows a merge: a name of Face1 has the old name in its ancestry
    const auto merged = generated({names.oldTop}, 9, "FUS", 'F');
    input.pool["Face"][0].names.push_back(merged);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Exact);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[1].element, "Face1");
    EXPECT_NE(outcomes[1].evidence.find("in ancestry"), std::string::npos);
}

TEST(SolveOwner, duplicateOldNamesSolveOnce)
{
    OuterWire names;
    SolveInput input;
    input.pool["Face"] = {element("Face2", {names.newTop}), element("Face1", {names.side})};
    //   two references with the same old name don't compete for the element
    input.entries = {missing(names.oldTop), missing(names.oldTop)};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face2");
    EXPECT_EQ(describe(outcomes[0]), describe(outcomes[1]));
}

TEST(SolveOwner, unionOfSourcesOnlyAddsCandidates)
{
    OuterWire names;
    SolveInput input;
    input.pool["Face"] = {
        element("Face1", {names.side}),
        element("Face2", {names.newTop}),
    };
    input.pool["Edge"] = {element("Edge1", {sketchEdge(1)})};
    //   the name match finds the side face too, and a name of another type, which is dropped
    input.entries = {missing(names.oldTop, "Face", {names.side, sketchEdge(1)})};

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Face1", "Face2"}));

    input.source = Data::Tier1Source::Overlap;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face2");

    //   the name match alone offers the side face, which doesn't agree on the top section
    input.source = Data::Tier1Source::Names;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Face1"});
    EXPECT_EQ(outcomes[0].evidence, "no top agreement");
}

TEST(SolveOwner, sharedAncestorAloneDoesNotResolve)
{
    // ChamferEdgeRemoved: the chamfered top edge of sketch line 1 is cut away. The only element
    // left that shares an ancestor with it is the cut's floor edge, whose name holds the
    // sketch's face, which holds line 1: overlap 1/2, the only survivor, forced. Nothing but
    // that one sketch edge relates them, and the top sections disagree: broken, not resolved.
    const std::vector<std::string> lines {
        sketchEdge(1),
        sketchEdge(2),
        sketchEdge(3),
        sketchEdge(4),
    };
    const auto topEdge = section({}, {sketchEdge(1)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto slotFace = generated({sketchEdge(3, 8)}, 9, "XTR", 'F');
    const auto floorEdge = section({}, {lowFace(lines), slotFace}, 9, "CUT", 0, 'E', {"GEN"});
    SolveInput input;
    input.pool["Edge"] = {element("Edge7", {floorEdge})};
    input.entries = {missing(topEdge, "Edge")};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Edge7"});
    EXPECT_EQ(outcomes[0].evidence, "no top agreement");

    //   the same survivor with an agreeing top section resolves (SketchNotch's top face)
    const auto otherTop = section({}, {sketchEdge(1), sketchEdge(5)}, 7, "XTR", 0, 'E', {"PRJ"});
    input.pool["Edge"] = {element("Edge7", {otherTop})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge7");
}

TEST(SolveOwner, patternSiblingNeverResolves)
{
    // A pattern of two: the referenced instance's top face is gone and the other instance's copy
    // is the only survivor. The copy's name is the old name with another duplicate count, so it
    // shares the old name's linked edges (overlap 0.80) and its top section: forced and
    // evidenced, but another element.
    const std::vector<std::string> edges {
        sketchEdge(1),
        sketchEdge(2),
        sketchEdge(3),
        sketchEdge(4),
    };
    auto top = [&](const char* opCode, const char* count) {
        return Data::MappedName::makeEncodedSection({}, edges, "5", opCode, "0", 'F', count, {"LOW"}, {});
    };
    const auto oldTop = top("FAC", "1");
    SolveInput input;
    input.entries = {missing(oldTop)};

    //   the count field differs
    input.pool["Face"] = {element("Face4", {top("FAC", "2")})};
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Face4"});
    EXPECT_EQ(outcomes[0].evidence, "pattern sibling");

    //   the counter written over the op code (ops#55)
    input.pool["Face"] = {element("Face4", {top("_3", "0")})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "pattern sibling");

    //   the counter in an inner section, which a later feature keeps
    const auto later = section({}, {}, 9, "XTR", 0, 'F', {"MOD"});
    input.entries = {missing(oldTop + "|" + later)};
    input.pool["Face"] = {element("Face4", {top("FAC", "2") + "|" + later})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "pattern sibling");

    //   a sibling among an element's several names (a refined face) is enough
    input.entries = {missing(oldTop)};
    input.pool["Face"] = {element("Face4", {top("FAC", "2"), top("FAC", "3")})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].evidence, "pattern sibling");

    //   another element with the counter equal still resolves: the outer wire gains an edge
    std::vector<std::string> fiveEdges = edges;
    fiveEdges.push_back(sketchEdge(5));
    const auto newTop
        = Data::MappedName::makeEncodedSection({}, fiveEdges, "5", "FAC", "0", 'F', "1", {"LOW"}, {});
    input.pool["Face"] = {element("Face4", {newTop})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face4");

    //   and so does a different op code that isn't a counter
    input.pool["Face"] = {element("Face4", {top("XTR", "2")})};
    outcomes = Data::solveOwner(input);
    EXPECT_NE(outcomes[0].evidence, "pattern sibling");
}

TEST(SolveOwner, patternSiblingThroughAnEmbeddedName)
{
    // The counter sits in an embedded name: a face built on instance 1's edge and the same face
    // built on instance 2's. Both edges hold sketch line 1, so the other instance's face is the
    // lone survivor (overlap 1/3), forced, and agrees on the top section.
    auto instanceEdge = [](const char* count) {
        return Data::MappedName::makeEncodedSection(
            {},
            std::vector<std::string> {sketchEdge(1)},
            "7",
            "XTR",
            "0",
            'E',
            count,
            {"PRJ"},
            std::vector<std::string> {}
        );
    };
    auto faceOn = [](const std::string& edge) {
        return generated({edge}, 9, "FUS", 'F');
    };
    SolveInput input;
    input.entries = {missing(faceOn(instanceEdge("1")))};

    //   in a Linked Name
    input.pool["Face"] = {element("Face4", {faceOn(instanceEdge("2"))})};
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Face4"});
    EXPECT_EQ(outcomes[0].evidence, "pattern sibling");

    //   two levels down, with the counter over the op code
    auto twice = [&](const char* opCode) {
        auto edge = Data::MappedName::makeEncodedSection(
            {},
            std::vector<std::string> {sketchEdge(1)},
            "7",
            opCode,
            "0",
            'E',
            "0",
            {"PRJ"},
            std::vector<std::string> {}
        );
        return faceOn(upper({edge}, 8, "CHF"));
    };
    input.entries = {missing(twice("XTR"))};
    input.pool["Face"] = {element("Face4", {twice("_2")})};
    EXPECT_EQ(Data::solveOwner(input)[0].evidence, "pattern sibling");

    //   in a Connected Name of a later section
    const auto base = generated({sketchEdge(1)}, 7, "XTR", 'F');
    auto cut = [&](const char* count) {
        return base + "|" + section({}, {}, 9, "CUT", 0, 'F', {"MOD"}, {instanceEdge(count)});
    };
    input.entries = {missing(cut("1"))};
    input.pool["Face"] = {element("Face4", {cut("2")})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "pattern sibling");

    //   an embedded name that differs in more than the counter is no sibling: it resolves
    input.entries = {missing(faceOn(instanceEdge("1")))};
    input.pool["Face"] = {element(
        "Face4",
        {faceOn(
            Data::MappedName::makeEncodedSection(
                {},
                std::vector<std::string> {sketchEdge(1)},
                "7",
                "XTR",
                "1",
                'E',
                "2",
                {"PRJ"},
                std::vector<std::string> {}
            )
        )}
    )};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face4");
}

TEST(SolveOwner, independentOfInputOrder)
{
    // Arrange
    //   an owner with an exact reference, a duplicate pair, a split face, a symmetric pair and
    //   a type without elements
    OuterWire names;
    const auto split = generated({sketchEdge(7)}, 7, "Extrude", 'F', 3);
    const auto twin = generated({sketchEdge(8)}, 7, "Extrude", 'F', 4);
    const auto edgeOld = upper({names.side, twin}, 9, "FLT");
    const auto edgeX = upper({names.side, twin}, 9, "CHF");
    const auto edgeY = upper({twin, names.side}, 10, "CHF");
    SolveInput input;
    input.pool["Face"] = {
        element("Face1", {names.side}),
        element("Face2", {names.newTop, generated({names.oldTop}, 11, "FUS", 'F')}),
        element("Face3", {piece(split, 9, "CUT", 0, 'F')}),
        element("Face4", {piece(split, 9, "CUT", 1, 'F')}),
        element("Face5", {names.unrelated}),
    };
    input.pool["Edge"] = {element("Edge1", {edgeX}), element("Edge2", {edgeY})};
    input.entries = {
        exact("Face5"),
        missing(names.oldTop),
        missing(split),
        missing(names.oldTop),
        missing(edgeOld, "Edge"),
        missing(sketchEdge(42), "Vertex"),
    };
    const auto expected = Data::solveOwner(input);
    std::vector<std::string> expectedText;
    for (const auto& outcome : expected) {
        expectedText.push_back(describe(outcome));
    }
    EXPECT_EQ(expected[1].status, SolveStatus::Resolved);
    EXPECT_EQ(expected[2].status, SolveStatus::Broken);
    EXPECT_EQ(expected[4].status, SolveStatus::Broken);
    EXPECT_EQ(expected[5].evidence, "no candidate");

    // Act and assert
    std::mt19937 random(7);
    for (int round = 0; round < 100; ++round) {
        SolveInput shuffled = input;
        std::vector<int> order(input.entries.size());
        std::iota(order.begin(), order.end(), 0);
        std::shuffle(order.begin(), order.end(), random);
        for (std::size_t i = 0; i < order.size(); ++i) {
            shuffled.entries[i] = input.entries[order[i]];
        }
        for (auto& [type, pool] : shuffled.pool) {
            std::shuffle(pool.begin(), pool.end(), random);
            for (auto& item : pool) {
                std::shuffle(item.names.begin(), item.names.end(), random);
            }
        }
        auto outcomes = Data::solveOwner(shuffled);
        for (std::size_t i = 0; i < order.size(); ++i) {
            EXPECT_EQ(describe(outcomes[i]), expectedText[order[i]])
                << "round " << round << ", entry " << order[i];
        }
    }
}

// ---------------------------------------------------------------------------------------------
// The report and the reverse update's fingerprint check

TEST(ReferenceReport, replacePerTargetAndClear)
{
    App::PropertyLinkSub prop;
    App::ReferenceReport::Entry broken;
    broken.index = 1;
    broken.candidates = {{"Edge7", "a"}, {"Edge12", "b"}};
    App::ReferenceReport::Entry resolved;
    resolved.index = 0;
    resolved.status = App::ReferenceReport::Status::Resolved;
    resolved.tier = 1;
    resolved.newIndex = "Face2";

    App::ReferenceReport::replace(&prop, "Doc#A", {broken});
    App::ReferenceReport::replace(&prop, "Doc#B", {resolved});
    auto entries = App::ReferenceReport::get(&prop);
    ASSERT_EQ(entries.size(), 2U);
    EXPECT_EQ(entries[0].newIndex, "Face2");  // sorted by index
    ASSERT_NE(App::ReferenceReport::find(&prop, 1), nullptr);
    EXPECT_EQ(App::ReferenceReport::find(&prop, 1)->candidates.size(), 2U);

    //   an update of target A with nothing to report drops only A's entries
    App::ReferenceReport::replace(&prop, "Doc#A", {});
    EXPECT_EQ(App::ReferenceReport::find(&prop, 1), nullptr);
    EXPECT_NE(App::ReferenceReport::find(&prop, 0), nullptr);

    //   unregistering (as every setter does) drops the rest
    prop.unregisterElementReference();
    EXPECT_TRUE(App::ReferenceReport::get(&prop).empty());

    //   so does destruction
    const App::PropertyLinkBase* gone = nullptr;
    {
        App::PropertyLinkSub temporary;
        gone = &temporary;
        App::ReferenceReport::replace(&temporary, "Doc#A", {broken});
        EXPECT_EQ(App::ReferenceReport::get(&temporary).size(), 1U);
    }
    EXPECT_TRUE(App::ReferenceReport::get(gone).empty());
    EXPECT_EQ(
        App::ReferenceReport::statusName(App::ReferenceReport::Status::Index),
        std::string("index")
    );
}

TEST(ReferenceReport, reverseCheckTolerances)
{
    auto saved = Data::ElementFingerprint::fromString("1|F|Plane|200|5,10,20|0,0,1|_");
    ASSERT_TRUE(saved.isValid());
    //   a re-serialized fingerprint agrees
    auto again = Data::ElementFingerprint::fromString(saved.toString());
    EXPECT_TRUE(App::fingerprintsAgree(saved, again, 50.0));
    //   a centre moved by more than 1e-7 of the diagonal doesn't
    auto moved = saved;
    moved.center = Base::Vector3d(5, 10, 20 + 1e-4);
    EXPECT_FALSE(App::fingerprintsAgree(saved, moved, 50.0));
    moved.center = Base::Vector3d(5, 10, 20 + 1e-7);
    EXPECT_TRUE(App::fingerprintsAgree(saved, moved, 50.0));
    //   another kind, size or direction doesn't
    auto other = saved;
    other.kind = "Cylinder";
    EXPECT_FALSE(App::fingerprintsAgree(saved, other, 50.0));
    other = saved;
    other.size = 200.001;
    EXPECT_FALSE(App::fingerprintsAgree(saved, other, 50.0));
    other = saved;
    other.direction = Base::Vector3d(0, 0, -1);
    EXPECT_FALSE(App::fingerprintsAgree(saved, other, 50.0));
    //   nor another radius
    auto circle = Data::ElementFingerprint::fromString("1|E|Circle|31.4159265359|0,0,0|0,0,1|5");
    ASSERT_TRUE(circle.isValid());
    auto bigger = circle;
    bigger.radii = {5.001};
    EXPECT_TRUE(App::fingerprintsAgree(circle, circle, 10.0));
    EXPECT_FALSE(App::fingerprintsAgree(circle, bigger, 10.0));
}
