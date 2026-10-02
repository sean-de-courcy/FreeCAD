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
#include <optional>
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
        : outcome.status == SolveStatus::Removed            ? "removed"
                                                            : "broken";
    text += " " + outcome.element + " " + std::to_string(outcome.tier) + " [";
    for (const auto& candidate : outcome.candidates) {
        text += candidate + " ";
    }
    text += "] " + outcome.evidence;
    if (!outcome.elements.empty()) {
        text += " {";
        for (const auto& element : outcome.elements) {
            text += element + " ";
        }
        text += "} from " + outcome.from;
    }
    return text + (outcome.collapsed ? " collapsed" : "");
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
}

// Equivalent (Task 2 PR 5): a face split in two by a slot, referenced by a consumer that may get
// the same result from either half; the name match also offers another face.
namespace
{
struct SplitFace
{
    std::string old = generated({sketchEdge(1)}, 7, "Extrude", 'F');
    std::string other = generated({sketchEdge(2)}, 7, "Extrude", 'F', 1);
    std::string first = piece(old, 9, "CUT", 0, 'F');
    std::string second = piece(old, 9, "CUT", 1, 'F');

    SolveInput input(std::function<bool(const std::string&, const std::string&)> equivalent) const
    {
        SolveInput input;
        input.pool["Face"] = {
            element("Face1", {other}),
            element("Face2", {second}),
            element("Face3", {first}),
        };
        auto entry = missing(old, "Face", {other});
        entry.policy = Data::SolvePolicy::Equivalent;
        entry.equivalent = std::move(equivalent);
        input.entries = {entry};
        return input;
    }
};
}  // namespace

TEST(SolveOwner, equivalentPiecesResolveToTheFirstPiece)
{
    SplitFace names;
    auto input = names.input([](const std::string&, const std::string&) { return true; });

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    //   the piece whose name sorts first by bytes, never the other face
    const bool firstSortsFirst = names.first < names.second;
    EXPECT_EQ(outcomes[0].element, firstSortsFirst ? "Face3" : "Face2");
    EXPECT_EQ(outcomes[0].name, firstSortsFirst ? names.first : names.second);
    EXPECT_EQ(outcomes[0].tier, 1);
    EXPECT_NE(outcomes[0].evidence.find("2 pieces equivalent for the consumer"), std::string::npos)
        << outcomes[0].evidence;
}

TEST(SolveOwner, equivalentPiecesWithDifferentResultsBreak)
{
    SplitFace names;
    //   the other face agrees with one half, the halves don't agree
    auto input = names.input([](const std::string& a, const std::string& b) {
        return (a == "Face1") != (b == "Face1");
    });

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Face2", "Face3", "Face1"}));
    EXPECT_EQ(outcomes[0].evidence, "split into 2 pieces, 2 different results for the consumer");

    //   no probe: nothing is equivalent
    input.entries[0].equivalent = nullptr;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "split into 2 pieces, 2 different results for the consumer");
}

TEST(SolveOwner, equivalentPiecesIgnoreTheOtherSurvivors)
{
    // The halves agree; the other face (a name match, not a piece) gives another result.
    SplitFace names;
    auto input = names.input([](const std::string& a, const std::string& b) {
        return a != "Face1" && b != "Face1";
    });

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_NE(outcomes[0].element, "Face1");
}

TEST(SolveOwner, equivalenceNeedsEveryReferenceWithTheOldName)
{
    // Two references of the owner to the same old face, solved together: one consumer gets the
    // same result from either half, the other doesn't.
    SplitFace names;
    auto input = names.input([](const std::string&, const std::string&) { return true; });
    auto second = input.entries[0];
    second.equivalent = [](const std::string&, const std::string&) {
        return false;
    };
    input.entries.push_back(second);

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Broken);
}

TEST(SolveOwner, equivalentWithoutPiecesIsOne)
{
    // Two survivors that aren't pieces of the old face: even if the consumer would get the same
    // result from either (the coplanar neighbour of a gone face, ops#68), nothing shows that one
    // of them is the old face.
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
    auto entry = missing(names.oldTop);
    entry.policy = Data::SolvePolicy::Equivalent;
    entry.equivalent = [](const std::string&, const std::string&) {
        return true;
    };
    input.entries = {entry};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "ambiguous");
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
// Tiers 2 and 3: geometry against the saved fingerprint (Task 2 PR 4)

namespace
{

using Data::ElementFingerprint;
using Data::GeometryTolerances;

ElementFingerprint fingerprint(
    char type,
    const char* kind,
    std::optional<double> size,
    Base::Vector3d center,
    std::optional<Base::Vector3d> direction = {},
    std::vector<double> radii = {}
)
{
    ElementFingerprint fp;
    fp.type = type;
    fp.kind = kind;
    fp.size = size;
    fp.center = center;
    fp.direction = direction;
    fp.radii = std::move(radii);
    return fp;
}

// A direction turned from +Z towards +X by \a angle.
Base::Vector3d tilted(double angle)
{
    return Base::Vector3d(std::sin(angle), 0, std::cos(angle));
}

}  // namespace

TEST(Tier2, directionsWithinTheAngle)
{
    GeometryTolerances tol;
    const auto top = fingerprint('F', "Plane", 100, Base::Vector3d(5, 5, 10), Base::Vector3d(0, 0, 1));
    auto other = top;

    other.direction = tilted(0.5e-6);
    EXPECT_TRUE(Data::intrinsicAgrees(top, other, tol));
    other.direction = tilted(2e-6);
    EXPECT_FALSE(Data::intrinsicAgrees(top, other, tol));

    //   a plane's normal has a sense: the bottom face doesn't agree with the top
    other.direction = Base::Vector3d(0, 0, -1);
    EXPECT_FALSE(Data::intrinsicAgrees(top, other, tol));

    //   a line's direction has none (the producer's sign normalization can flip near 0)
    const auto line = fingerprint('E', "Line", 10, Base::Vector3d(0, 5, 10), Base::Vector3d(0, 1, 0));
    auto reversed = line;
    reversed.direction = Base::Vector3d(0, -1, 0);
    EXPECT_TRUE(Data::intrinsicAgrees(line, reversed, tol));

    //   size and position are tier 3's: they don't matter here
    other = top;
    other.size = 400;
    other.center = Base::Vector3d(50, 50, 10);
    EXPECT_TRUE(Data::intrinsicAgrees(top, other, tol));

    //   the angle is a parameter
    other.direction = tilted(2e-6);
    tol.angle = 3e-6;
    EXPECT_TRUE(Data::intrinsicAgrees(top, other, tol));
}

TEST(Tier2, kindTypeAndRadii)
{
    GeometryTolerances tol;
    const auto cylinder
        = fingerprint('F', "Cylinder", 62.8, Base::Vector3d(0, 0, 5), Base::Vector3d(0, 0, 1), {2.0});
    auto other = cylinder;

    other.radii = {2.0 * (1 + 0.5e-6)};
    EXPECT_TRUE(Data::intrinsicAgrees(cylinder, other, tol));
    other.radii = {2.0 * (1 + 2e-6)};
    EXPECT_FALSE(Data::intrinsicAgrees(cylinder, other, tol));
    other.radii = {2.0, 1.0};
    EXPECT_FALSE(Data::intrinsicAgrees(cylinder, other, tol));

    other = cylinder;
    other.kind = "Cone";
    EXPECT_FALSE(Data::intrinsicAgrees(cylinder, other, tol));
    other = cylinder;
    other.type = 'E';
    EXPECT_FALSE(Data::intrinsicAgrees(cylinder, other, tol));
    other = cylinder;
    other.direction.reset();
    EXPECT_FALSE(Data::intrinsicAgrees(cylinder, other, tol));
    EXPECT_FALSE(Data::intrinsicAgrees(cylinder, ElementFingerprint(), tol));
    EXPECT_FALSE(Data::intrinsicAgrees(ElementFingerprint(), cylinder, tol));
}

TEST(Tier3, nearestWithAGap)
{
    GeometryTolerances tol;        // d_max 1 % of the diagonal, gap 3x, size 1 %
    const double diagonal = 30.0;  // d_max 0.3
    const auto saved = fingerprint('E', "Line", 10, Base::Vector3d(20, 5, 10), Base::Vector3d(0, 1, 0));
    auto at = [&](double x, double size = 10) {
        auto fp = saved;
        fp.center = Base::Vector3d(x, 5, 10);
        fp.size = size;
        return fp;
    };

    //   in place, the next one far
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(0), at(20)}, diagonal, tol), 1);
    //   just inside and just outside d_max
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(20.29), at(0)}, diagonal, tol), 0);
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(20.31), at(0)}, diagonal, tol), -1);
    //   the second nearest within 3x the nearest, or within d_max
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(20.1), at(19.75)}, diagonal, tol), -1);
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(20.0), at(20.2)}, diagonal, tol), -1);
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(20.05), at(19.65)}, diagonal, tol), 0);
    //   two in the same place
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(20), at(20)}, diagonal, tol), -1);
    //   the size within 1 %
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(20, 10.09)}, diagonal, tol), 0);
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(20, 10.11)}, diagonal, tol), -1);
    //   no scale, no candidate
    EXPECT_EQ(Data::extrinsicNearest(saved, {at(20)}, 0.0, tol), -1);
    EXPECT_EQ(Data::extrinsicNearest(saved, {}, diagonal, tol), -1);
}

namespace
{

// The outer-wire names, with fingerprints: the top face 20 x 10 at z = 10, a side face at
// x = 20, and the top face moved along X.
struct Placed
{
    OuterWire names;
    std::string otherTop = lowFace(
        {sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4), sketchEdge(6)}
    );
    ElementFingerprint top
        = fingerprint('F', "Plane", 200, Base::Vector3d(10, 5, 10), Base::Vector3d(0, 0, 1));
    ElementFingerprint side
        = fingerprint('F', "Plane", 100, Base::Vector3d(20, 5, 5), Base::Vector3d(1, 0, 0));

    ElementFingerprint topAt(double x) const
    {
        auto fp = top;
        fp.center = Base::Vector3d(x, 5, 10);
        return fp;
    }
};

// Gives the pool these fingerprints, and counts the measurements in \a calls if set.
void measure(SolveInput& input, std::map<std::string, ElementFingerprint> fingerprints, int* calls)
{
    input.fingerprintOf = [fingerprints, calls](const std::string& index) {
        if (calls) {
            ++*calls;
        }
        auto it = fingerprints.find(index);
        return it == fingerprints.end() ? ElementFingerprint() : it->second;
    };
}

}  // namespace

TEST(SolveOwner, geometryBreaksTiesAmongSurvivors)
{
    Placed p;
    SolveInput input;
    input.diagonal = 30.0;
    input.pool["Face"] = {
        element("Face2", {p.names.newTop}),
        element("Face10", {p.otherTop}),
    };
    input.entries = {missing(p.names.oldTop)};

    //   without a fingerprint: two equal survivors, broken (PR 3), nothing measured
    int calls = 0;
    measure(input, {{"Face2", p.top}, {"Face10", p.side}}, &calls);
    EXPECT_EQ(describe(Data::solveOwner(input)[0]), "broken  -1 [Face2 Face10 ] ambiguous");
    EXPECT_EQ(calls, 0);

    //   tier 2: only one agrees in kind and direction
    input.entries[0].fingerprint = p.top;
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face2");
    EXPECT_EQ(outcomes[0].tier, 2);
    EXPECT_EQ(outcomes[0].evidence, "overlap 0.80, sources overlap, tier 2: 1 of 2");

    //   tier 3: both agree, one is in place and the other far
    measure(input, {{"Face2", p.topAt(30)}, {"Face10", p.top}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face10");
    EXPECT_EQ(outcomes[0].tier, 3);
    EXPECT_NE(outcomes[0].evidence.find("tier 3: nearest 0.000, second 20.000"), std::string::npos);

    //   both agree and neither is in place: broken, both listed
    measure(input, {{"Face2", p.topAt(15)}, {"Face10", p.topAt(5)}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Face2", "Face10"}));
    EXPECT_EQ(outcomes[0].evidence, "ambiguous");

    //   neither agrees: geometry doesn't replace tier 1, both still listed
    measure(input, {{"Face2", p.side}, {"Face10", p.side}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Face2", "Face10"}));
}

TEST(SolveOwner, geometryNeverOverridesASingleSurvivor)
{
    // The outer wire gains an edge: the top face changed size and centre, which is what the
    // edit did. Tier 1's one survivor resolves; geometry doesn't run.
    Placed p;
    SolveInput input;
    input.diagonal = 30.0;
    input.pool["Face"] = {element("Face1", {p.names.side}), element("Face2", {p.names.newTop})};
    input.entries = {missing(p.names.oldTop)};
    input.entries[0].fingerprint = p.top;
    int calls = 0;
    measure(input, {{"Face1", p.side}, {"Face2", p.topAt(9)}}, &calls);

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face2");
    EXPECT_EQ(outcomes[0].tier, 1);
    EXPECT_EQ(calls, 0);
}

TEST(SolveOwner, geometryAloneNeedsBothTiers)
{
    // SketchRedraw: every sketch line drawn again, so no name relates the old right top edge to
    // anything. Four edges along Y; the one in place resolves at tier 3.
    const auto oldEdge = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    auto line = [](double x, double z) {
        return fingerprint('E', "Line", 10, Base::Vector3d(x, 5, z), Base::Vector3d(0, 1, 0));
    };
    SolveInput input;
    input.diagonal = 24.5;
    input.pool["Edge"] = {
        element("Edge1", {section({}, {sketchEdge(12, 6)}, 7, "XTR", 0, 'E', {"PRJ"})}),
        element("Edge2", {section({}, {sketchEdge(13, 6)}, 7, "XTR", 0, 'E', {"PRJ"})}),
        element("Edge3", {section({}, {sketchEdge(12, 6)}, 7, "XTR", 1, 'E', {"PRJ"})}),
        element("Edge4", {section({}, {sketchEdge(13, 6)}, 7, "XTR", 1, 'E', {"PRJ"})}),
        element("Edge5", {section({}, {sketchEdge(14, 6)}, 7, "XTR", 0, 'E', {"PRJ"})}),
    };
    measure(
        input,
        {
            {"Edge1", line(0, 0)},
            {"Edge2", line(20, 0)},
            {"Edge3", line(0, 10)},
            {"Edge4", line(20, 10)},
            {"Edge5",
             fingerprint('E', "Line", 20, Base::Vector3d(10, 0, 10), Base::Vector3d(1, 0, 0))},
        },
        nullptr
    );
    input.entries = {missing(oldEdge, "Edge")};

    //   no fingerprint: nothing to go on
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "no candidate");

    input.entries[0].fingerprint = line(20, 10);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge4");
    EXPECT_EQ(outcomes[0].tier, 3);
    EXPECT_EQ(
        outcomes[0].evidence,
        "no structural candidate, tier 3: nearest 0.000, second 10.000, d_max 0.245"
    );

    //   redrawn 5 mm over: tier 2 agrees on four edges, tier 3 on none; they're listed
    input.entries[0].fingerprint = line(25, 10);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge1", "Edge2", "Edge3", "Edge4"}));
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U);

    //   the size must agree too
    input.entries[0].fingerprint = line(20, 10);
    input.entries[0].fingerprint.size = 12;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);

    //   another reference of the owner holds the edge in place exactly: it isn't offered
    input.entries[0].fingerprint = line(20, 10);
    input.entries.push_back(exact("Edge4", "Edge"));
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge1", "Edge2", "Edge3"}));
}

TEST(SolveOwner, geometryAloneTwinsSwapStaysBroken)
{
    // SolverTwinRotate: two bosses at (+-5, 0) become two at (0, +-5), every name new. Each old
    // circle has two circles of its radius and axis, neither in place.
    auto circle = [](double x, double y) {
        return fingerprint('E', "Circle", 12.566, Base::Vector3d(x, y, 10), Base::Vector3d(0, 0, 1), {2.0});
    };
    SolveInput input;
    input.diagonal = 30.0;
    input.pool["Edge"] = {
        element("Edge1", {section({}, {sketchEdge(21, 6)}, 7, "XTR", 0, 'E', {"PRJ"})}),
        element("Edge2", {section({}, {sketchEdge(22, 6)}, 7, "XTR", 0, 'E', {"PRJ"})}),
    };
    measure(input, {{"Edge1", circle(0, 5)}, {"Edge2", circle(0, -5)}}, nullptr);
    input.entries = {
        missing(section({}, {sketchEdge(1)}, 7, "XTR", 0, 'E', {"PRJ"}), "Edge"),
        missing(section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"}), "Edge"),
    };
    input.entries[0].fingerprint = circle(5, 0);
    input.entries[1].fingerprint = circle(-5, 0);

    auto outcomes = Data::solveOwner(input);

    for (const auto& outcome : outcomes) {
        EXPECT_EQ(outcome.status, SolveStatus::Broken);
        EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge1", "Edge2"}));
    }
}

TEST(SolveOwner, geometryNeedsOneFingerprintForSameNamedReferences)
{
    // Two references with the same old name but different saved fingerprints: no geometry.
    Placed p;
    SolveInput input;
    input.diagonal = 30.0;
    input.pool["Face"] = {
        element("Face2", {p.names.newTop}),
        element("Face10", {p.otherTop}),
    };
    measure(input, {{"Face2", p.top}, {"Face10", p.side}}, nullptr);
    input.entries = {missing(p.names.oldTop), missing(p.names.oldTop)};
    input.entries[0].fingerprint = p.top;
    input.entries[1].fingerprint = p.topAt(11);

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].evidence, "ambiguous");
    EXPECT_EQ(describe(outcomes[0]), describe(outcomes[1]));

    input.entries[1].fingerprint = p.top;
    EXPECT_EQ(Data::solveOwner(input)[1].element, "Face2");
}

// ---------------------------------------------------------------------------------------------
// The IDX source (Task 2 PR 6): an element of a shape without an element map, named by its index

namespace
{

// `<index>;_;<tag>;<op>;0;<type>;0;IDX,SRC;_`, as a map-less shape's element is named.
std::string indexed(const char* index, int tag, const char* opCode, char elementType = 'F')
{
    return section({index}, {}, tag, opCode, 0, elementType, {"IDX", "SRC"});
}

}  // namespace

TEST(NameAncestry, indexSourceIgnoresTheOpCodeOnly)
{
    const auto whole = indexed("Face6", 4, "MKR");
    EXPECT_TRUE(NameAncestry::sameIndexSource(whole, indexed("Face6", 4, "FUS")));
    EXPECT_TRUE(NameAncestry::sameIndexSource(whole, whole));
    //   flags as a set
    EXPECT_TRUE(NameAncestry::sameIndexSource(
        whole,
        section({"Face6"}, {}, 4, "CUT", 0, 'F', {"SRC", "IDX"})
    ));
    //   another index, tag or type, or a duplicate counter, is another element
    EXPECT_FALSE(NameAncestry::sameIndexSource(whole, indexed("Face5", 4, "FUS")));
    EXPECT_FALSE(NameAncestry::sameIndexSource(whole, indexed("Face6", 3, "FUS")));
    EXPECT_FALSE(NameAncestry::sameIndexSource(whole, indexed("Face6", 4, "FUS", 'E')));
    EXPECT_FALSE(NameAncestry::sameIndexSource(
        whole,
        Data::MappedName::makeEncodedSection(
            std::vector<std::string> {"Face6"},
            std::vector<std::string> {},
            "4",
            "FUS",
            "0",
            'F',
            "1",
            {"IDX", "SRC"},
            {}
        )
    ));
    //   a counter written over the op code relates to nothing else
    EXPECT_FALSE(NameAncestry::sameIndexSource(whole, indexed("Face6", 4, "_2")));
    //   only single IDX sections
    EXPECT_FALSE(NameAncestry::sameIndexSource(
        section({"Face6"}, {}, 4, "MKR", 0, 'F', {"SRC"}),
        section({"Face6"}, {}, 4, "FUS", 0, 'F', {"SRC"})
    ));
    const auto split = piece(indexed("Face6", 4, "FUS"), 9, "FUS", 0, 'F');
    EXPECT_FALSE(NameAncestry::sameIndexSource(whole, split));
}

TEST(NameAncestry, indexSourceOfANameAndOfItsPieces)
{
    const auto whole = indexed("Face6", 4, "FUS");
    EXPECT_EQ(NameAncestry::indexSource(whole), whole);
    const auto split = piece(whole, 9, "FUS", 0, 'F', {indexed("Edge2", 4, "MKR", 'E')});
    EXPECT_EQ(NameAncestry::indexSource(split), whole);
    EXPECT_EQ(NameAncestry::indexSource(piece(split, 11, "CUT", 1, 'F')), whole);
    //   an element generated from an IDX element isn't it
    EXPECT_EQ(NameAncestry::indexSource(whole + "|" + generated({}, 9, "FUS", 'F')), "");
    EXPECT_EQ(NameAncestry::indexSource(generated({whole}, 9, "Extrude", 'F')), "");
    EXPECT_EQ(NameAncestry::indexSource(sketchEdge(1)), "");
    EXPECT_EQ(NameAncestry::indexSource(""), "");
}

TEST(NameAncestry, indexPiecesUnderAnotherOpCode)
{
    const auto old = indexed("Face6", 4, "MKR");
    const auto split = piece(indexed("Face6", 4, "FUS"), 9, "FUS", 0, 'F');
    EXPECT_TRUE(NameAncestry::isIndexPieceOf(split, old));
    EXPECT_FALSE(NameAncestry::isPieceOf(split, old));
    //   a piece under the same op code is a plain piece
    const auto samePiece = piece(old, 9, "FUS", 0, 'F');
    EXPECT_FALSE(NameAncestry::isIndexPieceOf(samePiece, old));
    EXPECT_TRUE(NameAncestry::isPieceOf(samePiece, old));
    //   another element's pieces, a non-MOD section, an old name that isn't one IDX section
    const auto otherFace = piece(indexed("Face5", 4, "FUS"), 9, "FUS", 0, 'F');
    EXPECT_FALSE(NameAncestry::isIndexPieceOf(otherFace, old));
    const auto notModified = indexed("Face6", 4, "FUS") + "|" + generated({}, 9, "FUS", 'F');
    EXPECT_FALSE(NameAncestry::isIndexPieceOf(notModified, old));
    const auto pieceOfPiece = piece(piece(old, 9, "FUS", 0, 'F'), 11, "CUT", 0, 'F');
    EXPECT_FALSE(NameAncestry::isIndexPieceOf(pieceOfPiece, split));
}

namespace
{

// PartFuseLift's model: the top face of a map-less box (tag 4) was split by a bar (tag 9); the
// reference held the left piece, whose prefix is the face under FUS. The bar is lifted: the face
// is whole again, under MKR. Face12 embeds one of the piece's bounding edges.
struct MergeBack
{
    std::string edge2 = indexed("Edge2", 4, "MKR", 'E');
    std::string old = piece(indexed("Face6", 4, "FUS"), 9, "FUS", 0, 'F', {edge2});
    std::string whole = indexed("Face6", 4, "MKR");
    std::string beside = generated({edge2}, 9, "FUS", 'F');
    ElementFingerprint pieceFp
        = fingerprint('F', "Plane", 32, Base::Vector3d(4, 10, 10), Base::Vector3d(0, 0, 1));
    ElementFingerprint wholeFp
        = fingerprint('F', "Plane", 400, Base::Vector3d(10, 10, 10), Base::Vector3d(0, 0, 1));

    SolveInput input() const
    {
        SolveInput input;
        input.diagonal = 30.0;
        input.pool["Face"] = {element("Face6", {whole}), element("Face12", {beside})};
        input.entries = {missing(old)};
        return input;
    }
};

}  // namespace

TEST(SolveOwner, indexSourceAcrossOpCodes)
{
    MergeBack m;
    auto input = m.input();
    const auto otherTop
        = fingerprint('F', "Plane", 40, Base::Vector3d(10, 30, 10), Base::Vector3d(0, 0, 1));
    measure(input, {{"Face6", m.wholeFp}, {"Face12", otherTop}}, nullptr);

    //   without a fingerprint the IDX source doesn't count: Face12 alone, without evidence
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "no top agreement");

    //   tier 2 agrees with the whole face: it replaces the other survivor, at tier 1, although
    //   its size and centre changed (tier 3 would reject it)
    input.entries[0].fingerprint = m.pieceFp;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face6");
    EXPECT_EQ(outcomes[0].name, m.whole);
    EXPECT_EQ(outcomes[0].tier, 1);
    EXPECT_EQ(outcomes[0].evidence, "overlap 0.00, sources index, tier 2 agrees");

    //   tier 2 disagrees (the face turned): the IDX source doesn't count
    const auto turned
        = fingerprint('F', "Plane", 400, Base::Vector3d(10, 10, 10), Base::Vector3d(1, 0, 0));
    measure(input, {{"Face6", turned}, {"Face12", otherTop}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);

    //   the old name the whole face itself (SolverMergeTwo's A): the merged face carries it
    //   under FUS among its names
    measure(input, {{"Face4", m.wholeFp}}, nullptr);
    input.pool["Face"] = {
        element("Face4", {indexed("Face6", 4, "FUS"), indexed("Face6", 5, "FUS")}),
    };
    input.entries[0].oldName = indexed("Face6", 4, "MKR");
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Face4");
    EXPECT_EQ(outcomes[0].tier, 1);
}

TEST(SolveOwner, indexSourceNeedsTheSameElement)
{
    MergeBack m;
    auto input = m.input();
    input.entries[0].fingerprint = m.pieceFp;
    //   two elements of the same source (a compound of two copies): tier 3 can't choose
    //   between them, so the reference breaks with both
    input.pool["Face"] = {
        element("Face6", {m.whole}),
        element("Face16", {indexed("Face6", 4, "CUT")}),
    };
    measure(input, {{"Face6", m.wholeFp}, {"Face16", m.wholeFp}}, nullptr);
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Face6", "Face16"}));

    //   a tier-0 element of the same owner isn't offered
    input.pool["Face"] = {element("Face6", {m.whole}), element("Face12", {m.beside})};
    input.entries.push_back(exact("Face6"));
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Exact);
}

TEST(SolveOwner, indexSourceOnAMaplessTarget)
{
    // FilletDeleteBaseBox: the fillet's Base moved to the box (tag 4), which has no element map;
    // the old name is the box's Edge11 by index.
    const auto old = indexed("Edge11", 4, "MKR", 'E');
    const auto line
        = fingerprint('E', "Line", 10, Base::Vector3d(5, 10, 0), Base::Vector3d(1, 0, 0));
    SolveInput input;
    input.diagonal = 17.3;
    input.pool["Edge"] = {};
    input.entries = {missing(old, "Edge")};
    input.entries[0].fingerprint = line;
    input.maplessTag = "4";
    measure(input, {{"Edge11", line}, {"Edge3", line}}, nullptr);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge11");
    EXPECT_EQ(outcomes[0].name, "");
    EXPECT_EQ(outcomes[0].tier, 1);
    EXPECT_EQ(outcomes[0].evidence, "overlap 0.00, sources index, tier 2 agrees");

    //   a piece of it (a trimmed edge's whole on the box)
    input.entries[0].oldName = piece(indexed("Edge11", 4, "FUS", 'E'), 9, "FUS", 0, 'E');
    EXPECT_EQ(Data::solveOwner(input)[0].element, "Edge11");
    input.entries[0].oldName = old;

    //   another target's tag, or a target with a map: nothing names the element
    input.maplessTag = "5";
    EXPECT_EQ(describe(Data::solveOwner(input)[0]), "broken  -1 [] no candidate");
    input.maplessTag.clear();
    EXPECT_EQ(describe(Data::solveOwner(input)[0]), "broken  -1 [] no candidate");
    input.maplessTag = "4";

    //   tier 2 must agree; an element that doesn't exist has no fingerprint
    const auto across
        = fingerprint('E', "Line", 10, Base::Vector3d(0, 5, 0), Base::Vector3d(0, 1, 0));
    measure(input, {{"Edge11", across}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    measure(input, {}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    //   without a saved fingerprint
    measure(input, {{"Edge11", line}}, nullptr);
    input.entries[0].fingerprint = ElementFingerprint();
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    //   the index names an element of the entry's type only
    input.entries[0].fingerprint = line;
    input.entries[0].type = "Face";
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, indexPiecesAreFoundAsPieces)
{
    // PartFuseDrop: the whole top face (MKR) is split by the bar; the pieces carry it under FUS.
    // No name match offers them: the IDX source does.
    const auto old = indexed("Face6", 4, "MKR");
    const auto left = piece(indexed("Face6", 4, "FUS"), 9, "FUS", 0, 'F');
    const auto right = piece(indexed("Face6", 4, "FUS"), 9, "FUS", 1, 'F');
    SolveInput input;
    input.pool["Face"] = {element("Face3", {left}), element("Face7", {right})};
    input.entries = {missing(old)};

    EXPECT_EQ(
        describe(Data::solveOwner(input)[0]),
        "broken  -1 [Face3 Face7 ] split into 2 pieces"
    );

    input.entries[0].policy = Data::SolvePolicy::Equivalent;
    input.entries[0].equivalent = [](const std::string&, const std::string&) { return true; };
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, left < right ? "Face3" : "Face7");
    EXPECT_NE(outcomes[0].evidence.find("2 pieces equivalent for the consumer"), std::string::npos);
}

// ---------------------------------------------------------------------------------------------
// Splits (Task 2 PR 7): Expand, collapse and the geometric continuation

TEST(SolveOwner, expandTakesEveryPiece)
{
    SplitFace names;
    auto input = names.input({});
    input.entries[0].policy = Data::SolvePolicy::Expand;

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].tier, 1);
    //   both pieces in index order, never the other face
    EXPECT_EQ(outcomes[0].elements, (std::vector<std::string> {"Face2", "Face3"}));
    EXPECT_EQ(outcomes[0].names, (std::vector<std::string> {names.second, names.first}));
    EXPECT_EQ(outcomes[0].element, "Face2");
    EXPECT_EQ(outcomes[0].name, names.second);
    EXPECT_EQ(outcomes[0].from, names.old);
    EXPECT_EQ(outcomes[0].evidence, "split into 2 pieces, expanded");
}

TEST(SolveOwner, expandOnePieceIsAnExpansion)
{
    SplitFace names;
    SolveInput input;
    input.pool["Face"] = {element("Face1", {names.other}), element("Face3", {names.first})};
    auto entry = missing(names.old, "Face", {names.other});
    entry.policy = Data::SolvePolicy::Expand;
    input.entries = {entry};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].elements, (std::vector<std::string> {"Face3"}));
    EXPECT_EQ(outcomes[0].from, names.old);

    //   One still breaks on a single piece
    input.entries[0].policy = Data::SolvePolicy::One;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, expandedPiecesAreOneNode)
{
    // Another reference whose only candidate is one of the pieces: the piece set and that piece
    // can't both be used, so neither is forced.
    SplitFace names;
    auto input = names.input({});
    input.entries[0].policy = Data::SolvePolicy::Expand;
    const auto otherOld = generated({sketchEdge(3)}, 7, "Extrude", 'F', 2);
    input.entries.push_back(missing(otherOld, "Face", {names.first}));

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken) << describe(outcomes[0]);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Broken) << describe(outcomes[1]);
    EXPECT_EQ(outcomes[0].evidence, "ambiguous");
}

TEST(SolveOwner, expandInheritsFrom)
{
    // A piece that is split again passes its own `from` on.
    SplitFace names;
    auto input = names.input({});
    input.entries[0].policy = Data::SolvePolicy::Expand;
    input.entries[0].from = "F";

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].from, "F");
}

namespace
{

// A line edge from (x0, y, z) to (x1, y, z), as a fingerprint.
ElementFingerprint lineX(double x0, double x1, double y = 0.0, double z = 10.0)
{
    return fingerprint('E',
                       "Line",
                       std::abs(x1 - x0),
                       Base::Vector3d((x0 + x1) / 2, y, z),
                       Base::Vector3d(1, 0, 0));
}

SolveInput::Entry member(
    SolveInput::Entry entry,
    const std::string& from,
    const char* scope,
    int position
)
{
    entry.from = from;
    entry.scope = scope;
    entry.position = position;
    return entry;
}

}  // namespace

TEST(SolveOwner, collapseWhenTheOthersAreGone)
{
    // A continuation group {F exact, P missing} (the notch filled in: F is whole again, 0..20,
    // and covers P's saved 12..20), and a structural group {P1 missing, P2 missing} whose `from`
    // is back (the rib moved away).
    const auto f = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    const auto p = generated({sketchEdge(9)}, 7, "Extrude", 'E');
    const auto g = generated({sketchEdge(2)}, 7, "Extrude", 'E', 1);
    SolveInput input;
    input.diagonal = 24.5;
    input.pool["Edge"] = {element("Edge1", {f}), element("Edge4", {g})};
    measure(input, {{"Edge1", lineX(0, 20)}}, nullptr);
    auto rest = missing(p, "Edge");
    rest.fingerprint = lineX(12, 20);
    input.entries = {
        member(exact("Edge1", "Edge"), f, "a", 0),
        member(rest, f, "a", 1),
        member(missing(piece(g, 9, "FUS", 0, 'E'), "Edge"), g, "a", 3),
        member(missing(piece(g, 9, "FUS", 1, 'E'), "Edge"), g, "a", 2),
    };

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(
        describe(outcomes[0]),
        "resolved Edge1 0 [] pieces merged back: " + f + " found exactly collapsed"
    );
    EXPECT_EQ(outcomes[1].status, SolveStatus::Removed);
    //   the lowest position stays
    EXPECT_EQ(outcomes[3].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[3].element, "Edge4");
    EXPECT_TRUE(outcomes[3].collapsed);
    EXPECT_EQ(outcomes[2].status, SolveStatus::Removed);
}

TEST(SolveOwner, noCollapseWhenAMissingMemberLiesElsewhere)
{
    // After a notch, {X exact (0..8), Y missing, saved 12..20}: Y's line was drawn again with a
    // new ID, so its edge (Edge5, 12..20) has another name. X doesn't cover 12..20, so the
    // group doesn't collapse (it would keep 0..8 alone, a silent partial): Y is solved on its
    // own, and tier 3 finds its edge in place.
    const auto x = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    const auto y = generated({sketchEdge(9)}, 7, "Extrude", 'E', 1);
    const auto redrawn = generated({sketchEdge(12)}, 7, "Extrude", 'E', 2);
    SolveInput input;
    input.diagonal = 24.5;
    input.pool["Edge"] = {element("Edge1", {x}), element("Edge5", {redrawn})};
    measure(input, {{"Edge1", lineX(0, 8)}, {"Edge5", lineX(12, 20)}}, nullptr);
    auto rest = missing(y, "Edge");
    rest.fingerprint = lineX(12, 20);
    input.entries = {member(exact("Edge1", "Edge"), x, "a", 0), member(rest, x, "a", 1)};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Exact);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Resolved) << describe(outcomes[1]);
    EXPECT_EQ(outcomes[1].element, "Edge5");
    EXPECT_EQ(outcomes[1].tier, 3);

    //   without a saved fingerprint, nothing shows it merged back either: broken, not removed
    input.entries[1].fingerprint = ElementFingerprint();
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Exact);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Broken);
}

TEST(SolveOwner, piecesAreFoundBeyondTheTopAgreement)
{
    // Two pieces of X, and Z, generated from X with X's op code and flags: all three hold X in
    // their ancestry, but only Z agrees with X on the top section, so tier 1's filter keeps Z
    // alone. The pieces are still found: Expand takes them, One breaks with them.
    const auto x = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    const auto z = generated({x}, 8, "Extrude", 'E', 1);
    SolveInput input;
    input.pool["Edge"] = {
        element("Edge1", {piece(x, 9, "CUT", 0, 'E')}),
        element("Edge2", {z}),
        element("Edge3", {piece(x, 9, "CUT", 1, 'E')}),
    };
    auto entry = missing(x, "Edge");
    entry.policy = Data::SolvePolicy::Expand;
    input.entries = {entry};

    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved);
    EXPECT_EQ(outcome.elements, (std::vector<std::string> {"Edge1", "Edge3"}));

    input.entries[0].policy = Data::SolvePolicy::One;
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge1", "Edge3", "Edge2"}));
}

TEST(SolveOwner, noCollapseWhileAPieceRemains)
{
    const auto f = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    const auto c = generated({sketchEdge(9)}, 7, "Extrude", 'E', 1);
    SolveInput input;
    input.pool["Edge"] = {element("Edge1", {f}), element("Edge2", {c})};
    input.entries = {
        member(exact("Edge1", "Edge"), f, "a", 0),
        member(exact("Edge2", "Edge"), f, "a", 1),
    };

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Exact);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Exact);
}

TEST(SolveOwner, collapseNeedsTheSameScope)
{
    // The same `from` in two properties: one group still has a piece, the other collapses.
    const auto f = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    const auto c = generated({sketchEdge(9)}, 7, "Extrude", 'E', 1);
    const auto gone = generated({sketchEdge(8)}, 7, "Extrude", 'E', 2);
    SolveInput input;
    input.diagonal = 24.5;
    input.pool["Edge"] = {element("Edge1", {f}), element("Edge2", {c})};
    measure(input, {{"Edge1", lineX(0, 20)}}, nullptr);
    auto rest = missing(gone, "Edge");
    rest.fingerprint = lineX(12, 20);
    input.entries = {
        member(exact("Edge1", "Edge"), f, "a", 0),
        member(exact("Edge2", "Edge"), f, "a", 1),
        member(exact("Edge1", "Edge"), f, "b", 0),
        member(rest, f, "b", 1),
    };

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Exact);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Exact);
    EXPECT_EQ(outcomes[2].status, SolveStatus::Resolved);
    EXPECT_TRUE(outcomes[2].collapsed);
    EXPECT_EQ(outcomes[3].status, SolveStatus::Removed);
}

namespace
{

// The 20 x 10 x 10 block's front top edge, 0..20 along X at y = 0, z = 10, whose reference holds
// its fingerprint; a notch now leaves the hit (Edge1, 0..8) and a piece (Edge2, 12..20). Both
// bound the top face (Face1); Edge3 is elsewhere.
struct Notch
{
    const double diagonal = std::sqrt(20.0 * 20 + 10 * 10 + 10 * 10);
    const double eps = 1e-7 * diagonal;
    std::string hitName = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    std::string pieceName = generated({sketchEdge(9)}, 7, "Extrude", 'E', 1);
    std::string otherName = generated({sketchEdge(2)}, 7, "Extrude", 'E', 2);
    std::map<std::string, ElementFingerprint> fingerprints {
        {"Edge1", lineX(0, 8)},
        {"Edge2", lineX(12, 20)},
        {"Edge3", lineX(0, 20, 10)},
    };
    std::map<std::string, std::vector<std::string>> faces {
        {"Edge1", {"Face1", "Face2"}},
        {"Edge2", {"Face1", "Face3"}},
        {"Edge3", {"Face1", "Face4"}},
    };

    SolveInput input(Data::SolvePolicy policy) const
    {
        SolveInput input;
        input.diagonal = diagonal;
        input.pool["Edge"] = {
            element("Edge1", {hitName}),
            element("Edge2", {pieceName}),
            element("Edge3", {otherName}),
        };
        auto hit = exact("Edge1", "Edge");
        hit.exactName = hitName;
        hit.fingerprint = lineX(0, 20);
        hit.policy = policy;
        input.entries = {hit};
        input.fingerprintOf = [fps = fingerprints](const std::string& index) {
            auto it = fps.find(index);
            return it == fps.end() ? ElementFingerprint() : it->second;
        };
        input.facesOf = [map = faces](const std::string& index) {
            auto it = map.find(index);
            return it == map.end() ? std::vector<std::string>() : it->second;
        };
        return input;
    }
};

}  // namespace

TEST(Continuation, hitWithinOldEdge)
{
    GeometryTolerances tolerances;
    const double diagonal = 24.5;
    const double eps = 1e-7 * diagonal;
    auto old = lineX(0, 20);
    auto within = [&](const ElementFingerprint& now) {
        return Data::hitWithinOldEdge(old, now, diagonal, tolerances, 1e-7);
    };

    EXPECT_TRUE(within(lineX(0, 8)));
    EXPECT_TRUE(within(lineX(12, 20)));
    //   the same length, grown, moved off the line, beyond the end, tilted, another kind
    EXPECT_FALSE(within(lineX(0, 20)));
    EXPECT_FALSE(within(lineX(0, 24)));
    EXPECT_FALSE(within(lineX(0, 8, 2 * eps)));
    EXPECT_TRUE(within(lineX(0, 8, 0.5 * eps)));
    EXPECT_FALSE(within(lineX(-1, 7)));
    auto tilted = lineX(0, 8);
    tilted.direction = Base::Vector3d(std::cos(2e-6), std::sin(2e-6), 0);
    EXPECT_FALSE(within(tilted));
    auto circle = lineX(0, 8);
    circle.kind = "Circle";
    circle.radii = {4};
    EXPECT_FALSE(within(circle));
    //   no saved size, or a saved arc: nothing to locate
    auto noSize = old;
    noSize.size.reset();
    EXPECT_FALSE(Data::hitWithinOldEdge(noSize, lineX(0, 8), diagonal, tolerances, 1e-7));
    auto savedCircle = old;
    savedCircle.kind = "Circle";
    savedCircle.radii = {10};
    EXPECT_FALSE(Data::hitWithinOldEdge(savedCircle, lineX(0, 8), diagonal, tolerances, 1e-7));
}

TEST(Continuation, takesACollinearPieceOnASharedFace)
{
    Notch notch;
    auto outcomes = Data::solveOwner(notch.input(Data::SolvePolicy::Expand));

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].tier, 4);
    EXPECT_EQ(outcomes[0].elements, (std::vector<std::string> {"Edge1", "Edge2"}));
    EXPECT_EQ(outcomes[0].names, (std::vector<std::string> {notch.hitName, notch.pieceName}));
    EXPECT_EQ(outcomes[0].from, notch.hitName);
    EXPECT_EQ(outcomes[0].evidence, "continued by Edge2 (line within the old edge, shares Face1)");
}

TEST(Continuation, breaksOne)
{
    Notch notch;
    auto outcomes = Data::solveOwner(notch.input(Data::SolvePolicy::One));

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge1", "Edge2"}));
    EXPECT_EQ(outcomes[0].candidateNames,
              (std::vector<std::string> {notch.hitName, notch.pieceName}));
    EXPECT_EQ(outcomes[0].evidence, "split: the old edge continues in Edge2");
}

TEST(Continuation, equivalentKeepsTheHitOnlyWhenThePiecesAgree)
{
    Notch notch;
    auto input = notch.input(Data::SolvePolicy::Equivalent);
    input.entries[0].equivalent = [](const std::string&, const std::string&) { return true; };
    EXPECT_EQ(describe(Data::solveOwner(input)[0]), "exact Edge1 0 [] ");

    input.entries[0].equivalent = [](const std::string&, const std::string&) { return false; };
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge1", "Edge2"}));

    //   no probe is no equivalence
    input.entries[0].equivalent = {};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(Continuation, notTaken)
{
    Notch notch;
    const double eps = notch.eps;
    const std::string kept = "exact Edge1 0 [] ";
    struct Case
    {
        const char* what;
        std::function<void(SolveInput&, std::map<std::string, ElementFingerprint>&)> change;
        bool taken;
    };
    std::vector<Case> cases {
        {"offset by 2 eps",
         [&](auto&, auto& fps) { fps["Edge2"] = lineX(12, 20, 2 * eps); },
         false},
        {"offset by eps / 2",
         [&](auto&, auto& fps) { fps["Edge2"] = lineX(12, 20, 0.5 * eps); },
         true},
        {"tilted by 2 x the angle",
         [&](auto&, auto& fps) {
             fps["Edge2"].direction = Base::Vector3d(std::cos(2e-6), 0, std::sin(2e-6));
         },
         false},
        {"beyond the end, touching it",
         [&](auto&, auto& fps) { fps["Edge2"] = lineX(20, 26); },
         false},
        {"no shared face",
         [&](auto& input, auto&) {
             input.facesOf = [](const std::string& index) {
                 return index == "Edge1" ? std::vector<std::string> {"Face1"}
                                         : std::vector<std::string> {"Face9"};
             };
         },
         false},
        {"held exactly by the owner",
         [&](auto& input, auto&) { input.entries.push_back(exact("Edge2", "Edge")); },
         false},
        {"a circle piece",
         [&](auto&, auto& fps) {
             fps["Edge2"].kind = "Circle";
             fps["Edge2"].radii = {4};
         },
         false},
        {"an InternalEdge hit",
         [&](auto& input, auto&) { input.entries[0].type = "InternalEdge"; },
         false},
        {"no saved fingerprint",
         [&](auto& input, auto&) { input.entries[0].fingerprint = ElementFingerprint(); },
         false},
        {"a saved circle",
         [&](auto& input, auto&) {
             input.entries[0].fingerprint.kind = "Circle";
             input.entries[0].fingerprint.radii = {10};
         },
         false},
    };
    for (const auto& c : cases) {
        auto input = notch.input(Data::SolvePolicy::Expand);
        auto fps = notch.fingerprints;
        c.change(input, fps);
        input.fingerprintOf = [fps](const std::string& index) {
            auto it = fps.find(index);
            return it == fps.end() ? ElementFingerprint() : it->second;
        };
        auto outcome = Data::solveOwner(input)[0];
        if (c.taken) {
            EXPECT_EQ(outcome.tier, 4) << c.what << ": " << describe(outcome);
            EXPECT_EQ(outcome.elements, (std::vector<std::string> {"Edge1", "Edge2"})) << c.what;
        }
        else {
            EXPECT_EQ(describe(outcome), kept) << c.what;
        }
    }
}

TEST(Continuation, runPastBreaks)
{
    Notch notch;
    const double eps = notch.eps;
    for (auto policy :
         {Data::SolvePolicy::Expand, Data::SolvePolicy::One, Data::SolvePolicy::Equivalent}) {
        auto input = notch.input(policy);
        input.entries[0].equivalent = [](const std::string&, const std::string&) { return true; };
        auto fps = notch.fingerprints;
        fps["Edge2"] = lineX(12, 26);
        measure(input, fps, nullptr);
        auto outcome = Data::solveOwner(input)[0];
        EXPECT_EQ(outcome.status, SolveStatus::Broken) << static_cast<int>(policy);
        EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge1", "Edge2"}));
        EXPECT_EQ(outcome.evidence, "continued past the old edge by Edge2");
    }

    //   within eps of the old end is within; beyond it runs past
    auto input = notch.input(Data::SolvePolicy::Expand);
    auto fps = notch.fingerprints;
    fps["Edge2"] = lineX(12, 20 + 0.5 * eps);
    measure(input, fps, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].tier, 4);
    fps["Edge2"] = lineX(12, 20 + 2 * eps);
    measure(input, fps, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(Continuation, overlappingPiecesBreak)
{
    Notch notch;
    auto input = notch.input(Data::SolvePolicy::Expand);
    auto fps = notch.fingerprints;
    fps["Edge2"] = lineX(10, 15);
    fps["Edge3"] = lineX(15 - 2 * notch.eps, 20);
    measure(input, fps, nullptr);

    auto outcome = Data::solveOwner(input)[0];

    EXPECT_EQ(outcome.status, SolveStatus::Broken);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge1", "Edge2", "Edge3"}));
    EXPECT_EQ(outcome.evidence, "pieces overlap");

    //   touching pieces don't overlap
    fps["Edge3"] = lineX(15, 20);
    measure(input, fps, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].elements,
              (std::vector<std::string> {"Edge1", "Edge2", "Edge3"}));
}

TEST(Continuation, piecesLeaveOtherPools)
{
    // A missing reference whose only candidate (a name match) is the piece taken: broken, unless
    // the piece holds its old name in its ancestry (a proven merge).
    Notch notch;
    const auto old = generated({sketchEdge(5)}, 7, "Extrude", 'E', 4);
    auto input = notch.input(Data::SolvePolicy::Expand);
    input.entries.push_back(missing(old, "Edge", {notch.pieceName}));

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].tier, 4);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Broken) << describe(outcomes[1]);

    notch.pieceName = generated({old}, 9, "FUS", 'E');
    input = notch.input(Data::SolvePolicy::Expand);
    input.entries.push_back(missing(old, "Edge", {notch.pieceName}));
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].tier, 4);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Resolved) << describe(outcomes[1]);
    EXPECT_EQ(outcomes[1].element, "Edge2");
}

TEST(Continuation, independentOfInputOrder)
{
    // An owner with a continued exact edge, an Expand reference to a split face, a collapsing
    // group and a broken continuation, shuffled.
    Notch notch;
    SplitFace split;
    const auto f = generated({sketchEdge(31)}, 7, "Extrude", 'V');
    auto input = notch.input(Data::SolvePolicy::Expand);
    auto one = exact("Edge4", "Edge");
    one.exactName = "e4";
    one.fingerprint = lineX(0, 20, 10, 0);
    one.position = 1;
    input.pool["Edge"].push_back(element("Edge4", {"e4"}));
    input.pool["Edge"].push_back(element("Edge5", {"e5"}));
    auto fps = notch.fingerprints;
    fps["Edge4"] = lineX(0, 5, 10, 0);
    fps["Edge5"] = lineX(7, 20, 10, 0);
    auto faces = notch.faces;
    faces["Edge4"] = {"Face7"};
    faces["Edge5"] = {"Face7"};
    input.facesOf = [faces](const std::string& index) {
        auto it = faces.find(index);
        return it == faces.end() ? std::vector<std::string>() : it->second;
    };
    measure(input, fps, nullptr);
    input.entries.push_back(one);
    auto face = split.input({}).entries[0];
    face.policy = Data::SolvePolicy::Expand;
    input.pool["Face"] = split.input({}).pool["Face"];
    input.entries.push_back(face);
    input.pool["Vertex"] = {element("Vertex1", {f})};
    input.entries.push_back(member(missing(piece(f, 9, "CUT", 0, 'V'), "Vertex"), f, "s", 3));
    input.entries.push_back(member(missing(piece(f, 9, "CUT", 1, 'V'), "Vertex"), f, "s", 2));

    const auto expected = Data::solveOwner(input);
    std::vector<std::string> expectedText;
    for (const auto& outcome : expected) {
        expectedText.push_back(describe(outcome));
    }
    EXPECT_EQ(expected[0].tier, 4);
    EXPECT_EQ(expected[1].status, SolveStatus::Broken);
    EXPECT_EQ(expected[2].elements.size(), 2U);
    EXPECT_EQ(expected[3].status, SolveStatus::Removed);
    EXPECT_TRUE(expected[4].collapsed);

    std::mt19937 random(11);
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

// A split face (Task 2 PR 7, Q3 (b)): detected and broken, never taken.

namespace
{

// A face in the plane y = 0 (normal -Y), x from x0 to x1, z 0..10, as a fingerprint.
ElementFingerprint frontFace(double x0, double x1, double y = 0.0)
{
    return fingerprint('F',
                       "Plane",
                       (x1 - x0) * 10,
                       Base::Vector3d((x0 + x1) / 2, y, 5),
                       Base::Vector3d(0, -1, 0));
}

// The block's front face (x 0..20), which a notch splits into the hit (Face1, x 0..8) and
// Face2 (x 12..20); both bound the top and bottom faces (Face3, Face4). Face5 is the back.
struct FrontNotch
{
    const double diagonal = std::sqrt(20.0 * 20 + 10 * 10 + 10 * 10);
    const double eps = 1e-7 * diagonal;
    std::map<std::string, ElementFingerprint> fingerprints {
        {"Face1", frontFace(0, 8)},
        {"Face2", frontFace(12, 20)},
        {"Face3",
         fingerprint('F', "Plane", 200, Base::Vector3d(10, 5, 10), Base::Vector3d(0, 0, 1))},
        {"Face4",
         fingerprint('F', "Plane", 200, Base::Vector3d(10, 5, 0), Base::Vector3d(0, 0, -1))},
        {"Face5", frontFace(0, 20, 10)},
    };
    std::map<std::string, std::vector<std::string>> neighbours {
        {"Face1", {"Face3", "Face4"}},
        {"Face2", {"Face3", "Face4"}},
        {"Face3", {"Face1", "Face2", "Face5"}},
        {"Face4", {"Face1", "Face2", "Face5"}},
        {"Face5", {"Face3", "Face4"}},
    };

    SolveInput input(Data::SolvePolicy policy) const
    {
        SolveInput input;
        input.diagonal = diagonal;
        for (const auto& [index, fp] : fingerprints) {
            input.pool["Face"].push_back(element(index, {"n" + index}));
        }
        auto hit = exact("Face1", "Face");
        hit.exactName = "nFace1";
        hit.fingerprint = frontFace(0, 20);
        hit.policy = policy;
        hit.equivalent = [](const std::string&, const std::string&) { return true; };
        input.entries = {hit};
        measure(input, fingerprints, nullptr);
        input.neighboursOf = [map = neighbours](const std::string& index) {
            auto it = map.find(index);
            return it == map.end() ? std::vector<std::string>() : it->second;
        };
        return input;
    }
};

}  // namespace

TEST(SplitFace, faceWithinOldPlane)
{
    GeometryTolerances tolerances;
    const double diagonal = 24.5;
    const double eps = 1e-7 * diagonal;
    auto old = frontFace(0, 20);
    auto within = [&](const ElementFingerprint& now) {
        return Data::faceWithinOldPlane(old, now, diagonal, tolerances, 1e-7);
    };
    EXPECT_TRUE(within(frontFace(0, 8)));
    EXPECT_TRUE(within(frontFace(0, 8, 0.5 * eps)));
    //   the same area, off the plane, the other side, not a plane
    EXPECT_FALSE(within(frontFace(0, 20)));
    EXPECT_FALSE(within(frontFace(0, 8, 2 * eps)));
    auto flipped = frontFace(0, 8);
    flipped.direction = Base::Vector3d(0, 1, 0);
    EXPECT_FALSE(within(flipped));
    auto cylinder = frontFace(0, 8);
    cylinder.kind = "Cylinder";
    EXPECT_FALSE(within(cylinder));
}

TEST(SplitFace, breaksUnderOneAndExpand)
{
    FrontNotch notch;
    for (auto policy : {Data::SolvePolicy::Expand, Data::SolvePolicy::One}) {
        auto outcome = Data::solveOwner(notch.input(policy))[0];
        EXPECT_EQ(outcome.status, SolveStatus::Broken) << static_cast<int>(policy);
        EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face1", "Face2"}));
        EXPECT_EQ(outcome.evidence, "split: a coplanar face beside it, Face2");
    }
}

TEST(SplitFace, equivalentKeepsTheHitWhenTheProbeAgrees)
{
    // An attachment to the notched face: the coplanar rest gives it the same placement.
    FrontNotch notch;
    auto input = notch.input(Data::SolvePolicy::Equivalent);
    EXPECT_EQ(describe(Data::solveOwner(input)[0]), "exact Face1 0 [] ");

    input.entries[0].equivalent = [](const std::string&, const std::string&) { return false; };
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    input.entries[0].equivalent = {};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SplitFace, notBroken)
{
    FrontNotch notch;
    const std::string kept = "exact Face1 0 [] ";
    struct Case
    {
        const char* what;
        std::function<void(SolveInput&, std::map<std::string, ElementFingerprint>&)> change;
    };
    std::vector<Case> cases {
        {"no shared neighbour",
         [](auto& input, auto&) {
             input.neighboursOf = [](const std::string& index) {
                 return index == "Face1" ? std::vector<std::string> {"Face3"}
                                         : std::vector<std::string> {"Face9"};
             };
         }},
        {"off the plane by 2 eps",
         [&](auto&, auto& fps) { fps["Face2"] = frontFace(12, 20, 2 * notch.eps); }},
        {"held exactly by the owner",
         [](auto& input, auto&) { input.entries.push_back(exact("Face2", "Face")); }},
        {"the hit didn't shrink",
         [](auto&, auto& fps) { fps["Face1"] = frontFace(0, 20); }},
        {"no saved fingerprint",
         [](auto& input, auto&) { input.entries[0].fingerprint = ElementFingerprint(); }},
    };
    for (const auto& c : cases) {
        auto input = notch.input(Data::SolvePolicy::Expand);
        auto fps = notch.fingerprints;
        c.change(input, fps);
        measure(input, fps, nullptr);
        EXPECT_EQ(describe(Data::solveOwner(input)[0]), kept) << c.what;
    }
}

// ---------------------------------------------------------------------------------------------
// The write-back of a PropertyLinkSub (Task 2 PR 7)

TEST(RemapSubIndices, shiftsAndDrops)
{
    // Index 1 expanded to 3, index 2 removed.
    std::vector<int> firstNew {0, 1, 4, 4};
    std::vector<int> countNew {1, 3, 0, 1};
    EXPECT_EQ(App::remapSubIndices({0, 2, 3}, firstNew, countNew), (std::vector<int> {0, 4}));
    EXPECT_EQ(App::remapSubIndices({1}, firstNew, countNew), (std::vector<int> {1, 2, 3}));
    //   out of range: dropped
    EXPECT_TRUE(App::remapSubIndices({7}, firstNew, countNew).empty());
}

namespace
{

App::PropertyLinkBase::ShadowSub shadowOf(
    const std::string& oldName,
    const std::string& newName = {}
)
{
    App::PropertyLinkBase::ShadowSub shadow;
    shadow.oldName = oldName;
    shadow.newName = newName;
    return shadow;
}

App::SolverResolution resolution(App::SolverResolution::Status status, int index)
{
    App::SolverResolution item;
    item.status = status;
    item.index = index;
    return item;
}

}  // namespace

TEST(RebuildSubList, expandsRemovesAndKeepsSizesEqual)
{
    using Status = App::SolverResolution::Status;
    std::vector<std::string> subs {"Edge1", "?Edge2", "Edge3", "Edge4"};
    std::vector<App::PropertyLinkBase::ShadowSub> shadows {
        shadowOf("Edge1"),
        shadowOf("?Edge2", ";a.Edge2"),
        shadowOf("Edge3"),
        shadowOf("Edge4"),
    };
    std::vector<std::string> fingerprints {"f1", "f2", "f3", "f4"};
    std::vector<std::string> froms {"", "", "x", "x"};

    std::vector<App::SolverResolution> resolutions {resolution(Status::None, -1)};
    //   index 1 expands to Edge5, Edge3 (held by an untouched reference: skipped) and Edge6
    auto expanded = resolution(Status::Expanded, 1);
    expanded.from = "a";
    expanded.pieces = {
        {"Edge5", shadowOf("Edge5", ";p.Edge5")},
        {"Edge3", shadowOf("Edge3", ";q.Edge3")},
        {"Edge6", shadowOf("Edge6", ";r.Edge6")},
    };
    resolutions.push_back(expanded);
    //   index 3 is removed
    resolutions.push_back(resolution(Status::Removed, 3));

    std::vector<int> firstNew;
    std::vector<int> countNew;
    EXPECT_TRUE(
        App::rebuildSubList(resolutions, subs, shadows, fingerprints, froms, firstNew, countNew)
    );

    EXPECT_EQ(subs, (std::vector<std::string> {"Edge1", "Edge5", "Edge6", "Edge3"}));
    EXPECT_EQ(shadows.size(), subs.size());
    EXPECT_EQ(fingerprints, (std::vector<std::string> {"f1", "", "", "f3"}));
    EXPECT_EQ(froms, (std::vector<std::string> {"", "a", "a", "x"}));
    EXPECT_EQ(firstNew, (std::vector<int> {0, 1, 3, 4}));
    EXPECT_EQ(countNew, (std::vector<int> {1, 2, 1, 0}));
}

TEST(RebuildSubList, collapseBrokenAndDuplicates)
{
    using Status = App::SolverResolution::Status;
    std::vector<std::string> subs {"?Edge7", "Edge2", "Edge4"};
    std::vector<App::PropertyLinkBase::ShadowSub> shadows {
        shadowOf("?Edge7", ";c.Edge7"),
        shadowOf("Edge2", ";h.Edge2"),
        shadowOf("Edge4"),
    };
    std::vector<std::string> fingerprints {"f7", "f2", "f4"};
    std::vector<std::string> froms {"h", "h", ""};

    //   index 0 collapses to Edge4, which index 2 holds untouched: one sub stays
    auto collapsed = resolution(Status::Resolved, 0);
    collapsed.sub = "Edge4";
    collapsed.shadow = shadowOf("Edge4", ";h.Edge4");
    collapsed.clearFrom = true;
    //   index 1 breaks: it keeps its fingerprint and `from`
    auto broken = resolution(Status::Broken, 1);
    broken.sub = "?Edge2";
    broken.shadow = shadowOf("?Edge2", ";h.Edge2");

    std::vector<int> firstNew;
    std::vector<int> countNew;
    std::vector<App::SolverResolution> resolutions {collapsed, broken};
    EXPECT_TRUE(
        App::rebuildSubList(resolutions, subs, shadows, fingerprints, froms, firstNew, countNew)
    );

    EXPECT_EQ(subs, (std::vector<std::string> {"?Edge2", "Edge4"}));
    EXPECT_EQ(fingerprints, (std::vector<std::string> {"f2", "f4"}));
    EXPECT_EQ(froms, (std::vector<std::string> {"h", ""}));
    EXPECT_EQ(countNew, (std::vector<int> {0, 1, 1}));

    //   nothing to write: unchanged, one each
    resolutions = {resolution(Status::None, -1)};
    EXPECT_FALSE(
        App::rebuildSubList(resolutions, subs, shadows, fingerprints, froms, firstNew, countNew)
    );
    EXPECT_EQ(countNew, (std::vector<int> {1, 1}));
}

TEST(ReferenceReport, remapFollowsTheRebuild)
{
    App::PropertyLinkSub prop;
    App::ReferenceReport::Entry first;
    first.index = 1;
    App::ReferenceReport::Entry second;
    second.index = 2;
    App::ReferenceReport::replace(&prop, "Doc#A", {first, second});

    //   index 0 expanded to 3, index 1 removed
    App::ReferenceReport::remap(&prop, {0, 3, 3}, {3, 0, 1});

    auto entries = App::ReferenceReport::get(&prop);
    ASSERT_EQ(entries.size(), 1U);
    EXPECT_EQ(entries[0].index, 3);
    prop.unregisterElementReference();
    EXPECT_EQ(
        App::ReferenceReport::statusName(App::ReferenceReport::Status::Expanded),
        std::string("expanded")
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
