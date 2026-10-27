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
#include <limits>
#include <map>
#include <numbers>
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

// Instance \a number of pattern \a tag, with the number as text: one number per step of a
// multi-step pattern (`2:2`, ops#6).
std::string stepInstance(
    const std::string& incoming,
    int tag,
    const std::string& number,
    char elementType = 'F'
)
{
    return incoming + "|"
        + Data::MappedName::makeEncodedSection(
               std::vector<std::string> {},
               std::vector<std::string> {},
               std::to_string(tag),
               "TRF",
               number,
               elementType,
               "0",
               {"MOD"},
               std::vector<std::string> {}
        );
}

// A copy of \a incoming by copy maker \a tag, `_;_;<tag>;CPY;<index>;<type>;0;MOD;_`: a link's
// (`L`, a link array element's `L<n>`; ops#523), a Scale's or Reverse's (`1`), a second side's (`2`)
std::string copied(
    const std::string& incoming,
    int tag,
    const std::string& index,
    char elementType = 'F'
)
{
    return incoming + "|"
        + Data::MappedName::makeEncodedSection(
               std::vector<std::string> {},
               std::vector<std::string> {},
               std::to_string(tag),
               "CPY",
               index,
               elementType,
               "0",
               {"MOD"},
               std::vector<std::string> {}
        );
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

TEST(NameAncestry, patternInstancesAreNeitherPiecesNorPartners)
{
    // ops#55: a pattern's instance k is a copy of the support's element with a section
    // `_;_;<pattern>;TRF;<k>;<type>;0;MOD;_` appended. It has the MOD flag, but the instance is
    // another element: neither a piece of the support's element nor a tier-1 partner of another
    // instance's, of this pattern or another.
    NameAncestry ancestry;
    const auto support = generated({sketchEdge(1)}, 7, "Extrude", 'F');
    const auto instance = [&](int pattern, int k) {
        return piece(support, pattern, "TRF", k, 'F');
    };
    const auto x3 = instance(9, 3);
    const auto y3 = instance(8, 3);

    EXPECT_FALSE(NameAncestry::isPieceOf(x3, support));
    //   a split piece of an instance is still a piece of it
    EXPECT_TRUE(NameAncestry::isPieceOf(piece(x3, 10, "FUS", 0, 'F'), x3));
    //   so is a piece of a split made before the pattern (WholeShape mode): `X|<cut>|TRF;3` of
    //   `X|TRF;3`, but not of another instance, nor of the support
    const auto cutThenX3 = piece(piece(support, 6, "CUT", 0, 'F'), 9, "TRF", 3, 'F');
    EXPECT_TRUE(NameAncestry::isPieceOf(cutThenX3, x3));
    EXPECT_FALSE(NameAncestry::isPieceOf(cutThenX3, instance(9, 2)));
    EXPECT_FALSE(NameAncestry::isPieceOf(cutThenX3, support));
    EXPECT_FALSE(NameAncestry::isPieceOf(x3, x3));
    //   only the same instance survives tier 1, whatever its overlap with the others
    const std::vector<std::string> candidates {support, instance(9, 2), x3, instance(8, 2)};
    EXPECT_EQ(ancestry.structuralSurvivors(y3, candidates, 1.0), std::vector<int> {});
    EXPECT_EQ(ancestry.structuralSurvivors(x3, candidates, 1.0), std::vector<int> {2});
    EXPECT_EQ(
        ancestry.structuralSurvivors(support, {support, x3, y3}, 1.0),
        std::vector<int> {0}
    );
}

TEST(NameAncestry, patternStepNumbersAreOneField)
{
    // ops#6: a multi-step pattern numbers its instances per step, `2:2` for instance (2, 2), and
    // `2` for (2, 1) (the trailing 1s are left out). The TRF readers take the number as one field
    // and compare it as text, so each number is its own instance.
    NameAncestry ancestry;
    const auto support = generated({sketchEdge(1)}, 7, "Extrude", 'F');
    const auto x2y2 = stepInstance(support, 9, "2:2");
    const auto x2 = stepInstance(support, 9, "2");
    const auto x1y2 = stepInstance(support, 9, "1:2");
    const auto x3y2 = stepInstance(support, 9, "3:2");
    //   one index field
    const auto& decoded = Data::MappedName::getDecodedMappedName(x2y2);
    ASSERT_EQ(decoded.size(), 2U);
    EXPECT_EQ(decoded.back().opCode, "TRF");
    EXPECT_EQ(decoded.back().index, "2:2");
    //   an instance is a piece of nothing; its split pieces, and those of a split made before the
    //   pattern (isPieceOf's TRF tail), are pieces of that instance only
    EXPECT_FALSE(NameAncestry::isPieceOf(x2y2, support));
    EXPECT_FALSE(NameAncestry::isPieceOf(x2y2, x2));
    EXPECT_TRUE(NameAncestry::isPieceOf(piece(x2y2, 10, "FUS", 0, 'F'), x2y2));
    const auto cutThenX2Y2 = stepInstance(piece(support, 6, "CUT", 0, 'F'), 9, "2:2");
    EXPECT_TRUE(NameAncestry::isPieceOf(cutThenX2Y2, x2y2));
    EXPECT_FALSE(NameAncestry::isPieceOf(cutThenX2Y2, x2));
    EXPECT_FALSE(NameAncestry::isPieceOf(cutThenX2Y2, x3y2));
    EXPECT_FALSE(NameAncestry::isPieceOf(cutThenX2Y2, support));
    //   tier 1 keeps only the same instance; a lost instance has no structural candidate
    const std::vector<std::string> candidates {support, x2, x1y2, x2y2, x3y2};
    EXPECT_EQ(ancestry.structuralSurvivors(x2y2, candidates, 1.0), std::vector<int> {3});
    EXPECT_EQ(
        ancestry.structuralSurvivors(stepInstance(support, 9, "3:3"), candidates, 1.0),
        std::vector<int> {}
    );
}

TEST(NameAncestry, instanceCopiesHaveTheirOwnAncestry)
{
    // ops#91: instance k's copy of an element, `X|TRF;k`, has X as its prefix, but its history
    // is X's history in instance k: the support's names aren't its ancestors. Names that embed
    // instances' names (a fusion's face bounded by an edge of each of two overlapping blocks)
    // relate to the support's names only through what they embed of the support itself.
    NameAncestry ancestry;
    const auto right = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto left = section({}, {sketchEdge(4)}, 7, "XTR", 0, 'E', {"PRJ"});
    auto instance = [](const std::string& name, int k, char type = 'E', int pattern = 9) {
        return piece(name, pattern, "TRF", k, type);
    };
    // OverlappingInstances: the tops of the overlaps of the support and instance 2, and of
    // instances 2 and 3
    const auto top12 = section({}, {right, instance(left, 2)}, 9, "FUS", 0, 'F', {"LOW"});
    const auto top23 = section(
        {},
        {instance(right, 2), instance(left, 3)},
        9,
        "FUS",
        0,
        'F',
        {"LOW"}
    );

    EXPECT_FALSE(ancestry.contains(instance(right, 2), right));
    EXPECT_TRUE(ancestry.contains(top12, right));
    EXPECT_TRUE(ancestry.contains(top23, instance(right, 2)));
    EXPECT_FALSE(ancestry.contains(top23, right));
    //   through the instances' sections alone they shared 4 of top23's 7 ancestors, and the
    //   support's edge was wholly in top23's ancestry
    EXPECT_EQ(ancestry.overlap(top23, top12), 0.0);
    EXPECT_EQ(ancestry.overlap(right, top23), 0.0);
    EXPECT_EQ(ancestry.structuralSurvivors(top23, {top12}, 1.0), std::vector<int> {});
    //   the instance's own names: as many ancestors as before, the prefix's in its context
    const auto names = ancestry.ancestorNames(instance(right, 2));
    EXPECT_EQ(names.size(), 3U);
    EXPECT_EQ(std::count(names.begin(), names.end(), right), 0);
    EXPECT_EQ(std::count(names.begin(), names.end(), instance(right, 2)), 1);

    //   two names of one instance share the copies' ancestors as before: the top face gains an
    //   edge in the original, and in each instance
    const auto oldTop = lowFace({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)});
    const auto newTop = lowFace(
        {sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4), sketchEdge(5)}
    );
    const auto oldTop2 = instance(oldTop, 2, 'F');
    EXPECT_DOUBLE_EQ(ancestry.overlap(oldTop2, instance(newTop, 2, 'F')), 4.0 / 6.0);
    EXPECT_EQ(ancestry.overlap(oldTop2, instance(newTop, 3, 'F')), 0.0);
    EXPECT_EQ(ancestry.overlap(oldTop2, instance(newTop, 2, 'F', 8)), 0.0);
    EXPECT_EQ(ancestry.overlap(oldTop2, newTop), 0.0);
    //   a piece of an instance's element holds it, and a split piece's split pieces too
    const auto split = piece(oldTop2, 10, "FUS", 0, 'F');
    EXPECT_TRUE(ancestry.contains(split, oldTop2));
    EXPECT_TRUE(ancestry.contains(piece(split, 11, "CUT", 0, 'F'), oldTop2));
    //   a pattern of a pattern: pattern 8's copy of instance 2 of pattern 9 is another element
    //   again, and its ancestry is 2's in that copy
    const auto copyOfCopy = instance(instance(right, 2), 3, 'E', 8);
    EXPECT_FALSE(ancestry.contains(copyOfCopy, instance(right, 2)));
    EXPECT_FALSE(ancestry.contains(copyOfCopy, right));
    EXPECT_EQ(ancestry.ancestorNames(copyOfCopy).size(), 4U);
    EXPECT_EQ(ancestry.overlap(instance(right, 2), copyOfCopy), 0.0);
    EXPECT_DOUBLE_EQ(ancestry.overlap(copyOfCopy, instance(instance(right, 2), 3, 'E', 8)), 1.0);

    //   Reference IDs as leaves (Task 2 PR 8's variant): an instance's leaves are its own
    NameAncestry ids(Data::OverlapMeasure::ReferenceIds);
    EXPECT_EQ(ids.overlap(instance(right, 2), right), 0.0);
    EXPECT_EQ(ids.overlap(top23, top12), 0.0);
    EXPECT_GT(ids.overlap(oldTop2, instance(newTop, 2, 'F')), 0.0);
    //   and depth-weighted
    NameAncestry weighted(Data::OverlapMeasure::DepthWeighted);
    EXPECT_EQ(weighted.overlap(top23, top12), 0.0);
    EXPECT_GT(weighted.overlap(oldTop2, instance(newTop, 2, 'F')), 0.0);
}

TEST(NameAncestry, instanceCopiesKeepWhatTheyShare)
{
    // ops#91's review: the contexts take away only what relates different elements (the support
    // and a copy, two instances' copies). Two names of one instance keep what they shared.
    NameAncestry ancestry;
    const auto right = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto left = section({}, {sketchEdge(4)}, 7, "XTR", 0, 'E', {"PRJ"});
    auto instance = [](const std::string& name, int k, char type = 'E') {
        return piece(name, 9, "TRF", k, type);
    };
    //   a split made before the pattern (WholeShape mode): `X|CUT|TRF;2` is a piece of
    //   `X|TRF;2`, which doesn't contain it, and the overlap is X's copy and its sketch edge, 2 of
    //   3, as without the contexts
    const auto side = generated({sketchEdge(1)}, 7, "XTR", 'F');
    const auto side2 = instance(side, 2, 'F');
    const auto cutThenSide2 = instance(piece(side, 6, "CUT", 0, 'F'), 2, 'F');
    EXPECT_TRUE(NameAncestry::isPieceOf(cutThenSide2, side2));
    EXPECT_FALSE(ancestry.contains(cutThenSide2, side2));
    EXPECT_DOUBLE_EQ(ancestry.overlap(side2, cutThenSide2), 2.0 / 3.0);
    //   a fusion's face bounded by copies of two instances, after a sketch edit renamed the one
    //   of instance 2: the copies of instance 3 are the same, 3 of 7
    auto lowOf = [](const std::string& a, const std::string& b) {
        return section({}, {a, b}, 9, "FUS", 0, 'F', {"LOW"});
    };
    const auto renamed = section({}, {sketchEdge(6)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto top23 = lowOf(instance(right, 2), instance(left, 3));
    const auto newTop23 = lowOf(instance(renamed, 2), instance(left, 3));
    EXPECT_DOUBLE_EQ(ancestry.overlap(top23, newTop23), 3.0 / 7.0);
    EXPECT_EQ(ancestry.structuralSurvivors(top23, {newTop23}, 0.25), std::vector<int> {0});
}

TEST(NameAncestry, linkCopiesHaveTheirOwnAncestry)
{
    // ops#56: an element brought in from another document through a Link (or a binder) ends in
    // a boundary section, `X|_;_;<link>;EXT;0;<type>;0;_;_`. X is the other document's name; the
    // copy is another element, as a pattern instance's is (ops#91): X's history is its ancestry
    // only in that Link's context, so the copies through two Links share no ancestor.
    NameAncestry ancestry;
    auto through = [](const std::string& name, int link, char type = 'F') {
        return name + "|" + section({}, {}, link, "EXT", 0, type, {});
    };
    const auto boxFace = section({"Face6"}, {}, 1, "MKR", 0, 'F', {"IDX", "SRC"});
    const auto in7 = through(boxFace, 7);
    const auto in8 = through(boxFace, 8);

    //   a copy is no piece of the element, and holds neither it nor the other Link's copy
    EXPECT_FALSE(NameAncestry::isPieceOf(in7, boxFace));
    EXPECT_FALSE(ancestry.contains(in7, boxFace));
    EXPECT_EQ(ancestry.overlap(in7, in8), 0.0);
    EXPECT_EQ(ancestry.overlap(boxFace, in7), 0.0);
    const auto names = ancestry.ancestorNames(in7);
    EXPECT_EQ(names.size(), 2U);
    EXPECT_EQ(std::count(names.begin(), names.end(), boxFace), 0);
    //   tier 1 keeps only the same Link's copies, whatever they share below the boundary
    const auto cutThere = piece(boxFace, 4, "CUT", 0, 'F');  // a split in the other document
    const std::vector<std::string> candidates {boxFace, in8, through(cutThere, 7)};
    EXPECT_EQ(ancestry.structuralSurvivors(in7, candidates, 1.0), std::vector<int> {2});
    EXPECT_EQ(
        ancestry.structuralSurvivors(through(boxFace, 9), candidates, 1.0),
        std::vector<int> {}
    );

    //   pieces: one made here is a piece of the copy; one made in the other document before
    //   the boundary (isPieceOf's tail) is a piece of that Link's copy only
    const auto fusedHere = piece(in7, 10, "FUS", 0, 'F');
    EXPECT_TRUE(NameAncestry::isPieceOf(fusedHere, in7));
    EXPECT_TRUE(ancestry.contains(fusedHere, in7));
    EXPECT_TRUE(NameAncestry::isPieceOf(through(cutThere, 7), in7));
    EXPECT_FALSE(NameAncestry::isPieceOf(through(cutThere, 8), in7));
    EXPECT_FALSE(NameAncestry::isPieceOf(through(cutThere, 7), boxFace));
    EXPECT_FALSE(NameAncestry::isPieceOf(through(cutThere, 7), through(cutThere, 7)));

    //   names made here from the copies: an extrusion of the box's edge through each Link.
    //   Without the contexts they shared the edge, 1 of 3
    const auto edge = section({"Edge3"}, {}, 1, "MKR", 0, 'E', {"IDX", "SRC"});
    const auto from7 = generated({through(edge, 7, 'E')}, 10, "XTR", 'F');
    const auto from8 = generated({through(edge, 8, 'E')}, 11, "XTR", 'F');
    EXPECT_EQ(ancestry.overlap(from7, from8), 0.0);
    EXPECT_FALSE(ancestry.contains(from7, edge));
    EXPECT_TRUE(ancestry.contains(from7, through(edge, 7, 'E')));

    //   two names of one copy share the copies' ancestors as before: the top face gains an
    //   edge in the other document
    const auto oldTop = lowFace({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)});
    const auto newTop = lowFace(
        {sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4), sketchEdge(5)}
    );
    EXPECT_DOUBLE_EQ(ancestry.overlap(through(oldTop, 7), through(newTop, 7)), 4.0 / 6.0);
    EXPECT_EQ(ancestry.overlap(through(oldTop, 7), through(newTop, 8)), 0.0);

    //   two boundaries (a Link 9 to Link 7 in a third document): a copy of the copy, with 7's
    //   context inside 9's
    const auto twice = through(in7, 9);
    EXPECT_FALSE(ancestry.contains(twice, in7));
    EXPECT_FALSE(ancestry.contains(twice, boxFace));
    EXPECT_EQ(ancestry.ancestorNames(twice).size(), 3U);
    EXPECT_EQ(ancestry.overlap(in7, twice), 0.0);
    EXPECT_DOUBLE_EQ(ancestry.overlap(twice, through(through(boxFace, 7), 9)), 1.0);
    EXPECT_EQ(
        ancestry.structuralSurvivors(twice, {in7, through(in8, 9)}, 1.0),
        std::vector<int> {}
    );

    //   a pattern instance's copy and a boundary's copy with the same tag are other contexts
    EXPECT_EQ(ancestry.overlap(in7, piece(boxFace, 7, "TRF", 0, 'F')), 0.0);

    //   Reference IDs as leaves, and depth-weighted: the copies' leaves are their own
    NameAncestry ids(Data::OverlapMeasure::ReferenceIds);
    EXPECT_EQ(ids.overlap(in7, in8), 0.0);
    EXPECT_EQ(ids.overlap(in7, boxFace), 0.0);
    EXPECT_GT(ids.overlap(through(oldTop, 7), through(newTop, 7)), 0.0);
    NameAncestry weighted(Data::OverlapMeasure::DepthWeighted);
    EXPECT_EQ(weighted.overlap(from7, from8), 0.0);
    EXPECT_GT(weighted.overlap(through(oldTop, 7), through(newTop, 7)), 0.0);
}

TEST(NameAncestry, secondSidesAreCopies)
{
    // ops#255, PR 243 round 2: a two-sided Pad's second side is built from the profile again,
    // and its names are the first side's, X, followed by `_;_;<pad>;CPY;2;<type>;0;MOD;_`. The
    // MOD flag makes no piece: the second side is a copy, with X's history in its own context.
    NameAncestry ancestry;
    const auto x = generated({sketchEdge(1)}, 7, "XTR", 'E');
    const auto sideTwo = piece(x, 7, "CPY", 2, 'E');

    EXPECT_FALSE(NameAncestry::isPieceOf(sideTwo, x));
    EXPECT_FALSE(NameAncestry::isPieceOf(x, sideTwo));
    //   a split before the copy (the tapered side's draft) is a piece of the second side only
    const auto splitThenCopy = piece(piece(x, 7, "DFT", 0, 'E'), 7, "CPY", 2, 'E');
    EXPECT_TRUE(NameAncestry::isPieceOf(splitThenCopy, sideTwo));
    EXPECT_FALSE(NameAncestry::isPieceOf(splitThenCopy, x));
    //   and a split after it too
    EXPECT_TRUE(NameAncestry::isPieceOf(piece(sideTwo, 9, "CUT", 0, 'E'), sideTwo));
    EXPECT_FALSE(NameAncestry::isPieceOf(piece(sideTwo, 9, "CUT", 0, 'E'), x));
    //   the two sides share no ancestor
    EXPECT_EQ(ancestry.overlap(x, sideTwo), 0.0);
    EXPECT_FALSE(ancestry.contains(sideTwo, x));
    //   tier 1 keeps neither side for the other
    EXPECT_EQ(ancestry.structuralSurvivors(x, {sideTwo}, 1.0), std::vector<int> {});
    EXPECT_EQ(ancestry.structuralSurvivors(sideTwo, {x}, 1.0), std::vector<int> {});
    EXPECT_EQ(ancestry.structuralSurvivors(x, {sideTwo, x}, 1.0), std::vector<int> {1});
    //   a Revolution's second side: the CPY is on the profile's edge inside the face's name
    const auto faceOne = generated({sketchEdge(1)}, 7, "RVL", 'F');
    const auto faceTwo = generated({piece(sketchEdge(1), 7, "CPY", 2, 'E')}, 7, "RVL", 'F');
    EXPECT_EQ(ancestry.overlap(faceOne, faceTwo), 0.0);
    EXPECT_EQ(ancestry.structuralSurvivors(faceOne, {faceTwo}, 1.0), std::vector<int> {});
}

TEST(NameAncestry, patternInstanceWithoutNumberIsACopy)
{
    // PR 243 round 3 (Sonnet L1): a TRF section is a copy section by its op code, even with an
    // empty instance number, as before round 2.
    const auto x = generated({sketchEdge(1)}, 7, "XTR", 'F');
    const auto unnumbered = x + "|"
        + Data::MappedName::makeEncodedSection(
                            std::vector<std::string> {},
                            std::vector<std::string> {},
                            "9",
                            "TRF",
                            "",
                            'F',
                            "0",
                            {"MOD"},
                            std::vector<std::string> {}
        );
    EXPECT_FALSE(NameAncestry::isPieceOf(unnumbered, x));
}

TEST(NameAncestry, binderSupportsFromTwinFilesHaveTheirOwnAncestry)
{
    // ops#112: a binder's supports from copies of one file (equal IDs, so equal names) end in
    // boundary sections with the binder's tag and, in the index, the key of each support's file:
    // `X|_;_;<binder>;EXT;<key>;<type>;0;_;_`. The two are copies of X in two files, so other
    // elements, as the copies through two Links are.
    NameAncestry ancestry;
    auto through = [](const std::string& name, int binder, int key) {
        return name + "|" + section({}, {}, binder, "EXT", key, 'F', {});
    };
    const auto boxFace = section({"Face6"}, {}, 1, "MKR", 0, 'F', {"IDX", "SRC"});
    const auto fromP1 = through(boxFace, 7, 111);
    const auto fromP2 = through(boxFace, 7, 222);

    //   no shared ancestry, and neither holds the other
    EXPECT_EQ(ancestry.overlap(fromP1, fromP2), 0.0);
    EXPECT_FALSE(ancestry.contains(fromP1, fromP2));
    EXPECT_FALSE(ancestry.contains(fromP2, fromP1));
    EXPECT_FALSE(NameAncestry::isPieceOf(fromP2, fromP1));
    //   a split made in the source document is a piece of that file's copy only
    const auto cutThere = piece(boxFace, 4, "CUT", 0, 'F');
    EXPECT_TRUE(NameAncestry::isPieceOf(through(cutThere, 7, 111), fromP1));
    EXPECT_FALSE(NameAncestry::isPieceOf(through(cutThere, 7, 222), fromP1));
    //   tier 1 keeps only the same file's copies
    const std::vector<std::string> candidates {fromP2, through(cutThere, 7, 111)};
    EXPECT_EQ(ancestry.structuralSurvivors(fromP1, candidates, 1.0), std::vector<int> {1});
    EXPECT_EQ(
        ancestry.structuralSurvivors(fromP1, {fromP2, through(cutThere, 7, 222)}, 1.0),
        std::vector<int> {}
    );
    //   the same file's copy is the same element
    EXPECT_DOUBLE_EQ(ancestry.overlap(fromP1, through(boxFace, 7, 111)), 1.0);
}

TEST(NameAncestry, unclosedContextMarkIsAName)
{
    // A string that starts with the context mark and doesn't close it (only a caller, e.g.
    // App.getNameAncestors, can pass one) is a name like any other, decoded as such, not an
    // endless context (the call returns).
    NameAncestry ancestry;
    const std::string odd = "\x1e" "9;2";
    const auto names = ancestry.ancestorNames(odd);
    EXPECT_EQ(std::count(names.begin(), names.end(), odd), 1);
    EXPECT_TRUE(ancestry.contains(odd, odd));
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

    //   unless tier 1 shows a merge: a name of Face1 has the old name in its ancestry (a MOD
    //   section that holds it; through a GEN section it would be a source, ops#358)
    const auto merged = section({}, {names.oldTop}, 9, "FUS", 0, 'F', {"MOD"});
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

TEST(SolveOwner, nameMatchOnTheOtherSideIsNotTaken)
{
    // PR 243 round 3: a Two-sides Revolution's side 1 changed from Angle to Up to face, so its
    // end face's edge under a fillet is gone. Side 2's edge agrees on the top section and the
    // name matcher returned it (the CPY is on the profile's name inside it): another element.
    const auto profileEdge = sketchEdge(1);
    const auto sideOne = generated({profileEdge}, 7, "RVL", 'E');
    const auto sideTwo = generated({piece(profileEdge, 7, "CPY", 2, 'E')}, 7, "RVL", 'E');
    SolveInput input;
    input.source = Data::Tier1Source::Names;
    input.pool["Edge"] = {element("Edge4", {sideTwo})};
    input.entries = {missing(sideOne, "Edge", {sideTwo})};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken) << outcomes[0].evidence;

    //   a name match on the same side is still taken
    const auto sideOneAgain = generated({profileEdge, sketchEdge(5)}, 7, "RVL", 'E');
    input.pool["Edge"] = {element("Edge4", {sideTwo}), element("Edge5", {sideOneAgain})};
    input.entries = {missing(sideOne, "Edge", {sideTwo, sideOneAgain})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].element, "Edge5");

    //   one told from the old name by its Index alone is its twin (ops#503 D1): no evidence, and
    //   without a saved fingerprint nothing else decides
    const auto twin = generated({profileEdge}, 7, "RVL", 'E', 1);
    input.pool["Edge"] = {element("Edge4", {sideTwo}), element("Edge5", {twin})};
    input.entries = {missing(sideOne, "Edge", {sideTwo, twin})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken) << outcomes[0].evidence;
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

    //   the floor edge is the cut's (tag 9), not the pad's: no structural candidate (T1,
    //   ops#167), listed last for the user's pick (ops#174)
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Edge7"});
    EXPECT_EQ(outcomes[0].candidateRoles, std::vector<std::string> {"other maker"});
    EXPECT_EQ(outcomes[0].evidence, "no candidate; tier 1's 1 survivor has another maker");

    //   without T1, the top sections decide
    input.sameMaker = false;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Edge7"});
    EXPECT_EQ(outcomes[0].evidence, "no top agreement");
    input.sameMaker = true;

    //   the same survivor with an agreeing top section resolves (SketchNotch's top face)
    const auto otherTop = section({}, {sketchEdge(1), sketchEdge(5)}, 7, "XTR", 0, 'E', {"PRJ"});
    input.pool["Edge"] = {element("Edge7", {otherTop})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge7");
}

TEST(SolveOwner, topAgreementOfAnUnrelatedNameIsNoEvidence)
{
    // PR 243 round 6: a Pad's start cap edge (the profile's line 4, sketch 13) is gone. Side 1's
    // far cap edge holds it through its PRJ name, and lies on a base block's edge, so it also
    // holds the block sketch's line 4 (sketch 11), plain: that name's top section agrees with
    // the old name's (SKT), but it shares nothing with it. Tier 1 resolved the reference there,
    // 8 mm away, with no warning.
    const auto oldEdge = sketchEdge(4, 13);
    const auto farCapEdge = section({}, {oldEdge}, 14, "XTR", 0, 'E', {"PRJ"});
    SolveInput input;
    input.pool["Edge"] = {element("Edge28", {farCapEdge, sketchEdge(4, 11)})};
    input.entries = {missing(oldEdge, "Edge")};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Edge28"});
    EXPECT_EQ(outcomes[0].evidence, "no top agreement");

    //   a name that agrees on the top section and shares an ancestor with the old one is still
    //   evidence
    const auto oldSide = generated({sketchEdge(1), sketchEdge(2)}, 7, "XTR", 'F');
    const auto newSide = generated({sketchEdge(1), sketchEdge(3)}, 7, "XTR", 'F');
    input.pool.clear();
    input.pool["Face"] = {element("Face3", {newSide})};
    input.entries = {missing(oldSide, "Face")};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].element, "Face3");

    //   and so is the name the name match returned, though it shares none (overlap 0, sources
    //   names: random sequence 9, a boss's vertical edge after its back line is redrawn)
    const auto oldGenerated = generated({sketchVertex({"g2v2", "g3v1"})}, 7, "XTR", 'E');
    const auto renamed = generated({sketchVertex({"g2v2", "g5v1"})}, 7, "XTR", 'E');
    input.pool.clear();
    input.pool["Edge"] = {element("Edge20", {renamed})};
    input.entries = {missing(oldGenerated, "Edge", {renamed})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].element, "Edge20");
}

TEST(SolveOwner, sharedTopThroughAProjectionIsNoEvidence)
{
    // PR 243 round 7 (Fable review 6, M2): the Pad's start cap edge lay on a pedestal, split by
    // its edge (the profile's line 4, sketch 13, then FUS;MOD). Built as two sides apart, the
    // start cap is off the pedestal, and side 1's far cap edge is split by a block's edge: its
    // PRJ name, then FUS;MOD, besides the block sketch's plain line 4. Both names are topped by
    // FUS;MOD, and the PRJ name embeds the old one: that ancestry is the partner's, not the
    // element's own.
    const auto startCapEdge = sketchEdge(4, 13);
    const auto oldPiece = piece(startCapEdge, 15, "FUS", 0, 'E');
    const auto farCapEdge = section({}, {startCapEdge}, 14, "XTR", 0, 'E', {"PRJ"});
    const auto farCapPiece = piece(farCapEdge, 16, "FUS", 0, 'E');
    SolveInput input;
    input.pool["Edge"] = {element("Edge28", {farCapPiece, sketchEdge(4, 11)})};
    input.entries = {missing(oldPiece, "Edge")};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Edge28"});

    //   nor the other way: a reference to the far cap's piece doesn't move to the start cap's
    input.pool["Edge"] = {element("Edge24", {piece(startCapEdge, 16, "FUS", 0, 'E')})};
    input.entries = {missing(piece(farCapEdge, 15, "FUS", 0, 'E'), "Edge")};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Edge24"});
}

TEST(SolveOwner, connectedElementIsNotAncestry)
{
    // PR 243 round 7 (Fable review 6, M1): a base block's edge, split where side 1's far cap
    // meets it, lists among its piece's connected elements a face of the Pad holding an end
    // vertex: the profile's line 4's extruded face. The old start cap edge (line 4) is in that
    // neighbour's ancestry, not in the piece's: no evidence, though the top sections differ.
    const auto startCapEdge = sketchEdge(4, 13);
    const auto lineFace = generated({startCapEdge}, 14, "XTR", 'F');
    const auto blockPiece = piece(sketchEdge(4, 11), 15, "FUS", 1, 'E', {lineFace});
    SolveInput input;
    input.pool["Edge"] = {element("Edge32", {blockPiece})};
    input.entries = {missing(startCapEdge, "Edge")};

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Edge32"});

    //   nor when the top sections agree: the old edge, then FUS;MOD, and the block's piece with
    //   that neighbour among its connected elements (PR 243 round 7, Fable review 7)
    input.pool["Edge"] = {element("Edge32", {piece(sketchEdge(4, 11), 16, "FUS", 0, 'E', {lineFace})})};
    input.entries = {missing(piece(startCapEdge, 15, "FUS", 0, 'E'), "Edge")};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Edge32"});
}

TEST(SolveOwner, partnersOfOneProfileElementRelate)
{
    // PR 243 round 7 (Fable review 7): relating names only outside projections still relates
    // two partners of the same profile element. A far cap edge's piece (its PRJ name of the
    // profile's line 4, then FUS;MOD) is gone, and the far cap edge after the edit holds the
    // line's partner under another index: same profile element, same projection.
    const auto startCapEdge = sketchEdge(4, 13);
    const auto oldPartner = section({}, {startCapEdge}, 14, "XTR", 0, 'E', {"PRJ"});
    const auto newPartner = section({}, {startCapEdge}, 14, "XTR", 1, 'E', {"PRJ"});
    SolveInput input;
    input.pool["Edge"] = {element("Edge28", {piece(newPartner, 16, "FUS", 0, 'E')})};
    input.entries = {missing(piece(oldPartner, 15, "FUS", 0, 'E'), "Edge")};

    const auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].element, "Edge28");
    EXPECT_EQ(outcomes[0].tier, 1);
}

TEST(SolveOwner, patternSiblingNeverResolves)
{
    // A pattern of two: the referenced instance's top face is gone and the other instance's copy
    // is the only survivor. The copy's name is the old name with another duplicate count, so it
    // shares the old name's linked edges (overlap 0.80) and its top section: forced and
    // evidenced, but another element. Since ops#503 D1 the copy is the old name's twin, which
    // the twin clause hands to geometry; without a saved fingerprint, nothing decides.
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
    const std::string twinOnly =
        "tier 1's one survivor is the old element's twin (Face4); geometry decides; no candidate";

    //   the count field differs
    input.pool["Face"] = {element("Face4", {top("FAC", "2")})};
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Face4"});
    EXPECT_EQ(outcomes[0].evidence, twinOnly);

    //   the counter written over the op code (ops#55)
    input.pool["Face"] = {element("Face4", {top("_3", "0")})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, twinOnly);

    //   the counter in an inner section, which a later feature keeps
    const auto later = section({}, {}, 9, "XTR", 0, 'F', {"MOD"});
    input.entries = {missing(oldTop + "|" + later)};
    input.pool["Face"] = {element("Face4", {top("FAC", "2") + "|" + later})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, twinOnly);

    //   a sibling among an element's several names (a refined face) is enough
    input.entries = {missing(oldTop)};
    input.pool["Face"] = {element("Face4", {top("FAC", "2"), top("FAC", "3")})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].evidence, twinOnly);

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
    // lone survivor (overlap 1/3), forced, and agrees on the top section. Since ops#503 D1 it is
    // the old name's twin, which the twin clause hands to geometry; without a saved
    // fingerprint, nothing decides.
    const std::string twinOnly =
        "tier 1's one survivor is the old element's twin (Face4); geometry decides; no candidate";
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
    EXPECT_EQ(outcomes[0].evidence, twinOnly);

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
    EXPECT_EQ(Data::solveOwner(input)[0].evidence, twinOnly);

    //   in a Connected Name of a later section
    const auto base = generated({sketchEdge(1)}, 7, "XTR", 'F');
    auto cut = [&](const char* count) {
        return base + "|" + section({}, {}, 9, "CUT", 0, 'F', {"MOD"}, {instanceEdge(count)});
    };
    input.entries = {missing(cut("1"))};
    input.pool["Face"] = {element("Face4", {cut("2")})};
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, twinOnly);

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
        element("Face2", {names.newTop, section({}, {names.oldTop}, 11, "FUS", 0, 'F', {"MOD"})}),
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
    // edit did. Tier 1's one survivor resolves; tiers 2 and 3 don't run. Since Task 2 PR 8 the
    // partner is measured once, for the tier-1 check (still a plane, the same normal: ops#87).
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
    EXPECT_EQ(calls, 1);
}

TEST(SolveOwner, patternInstanceSiblingNeverResolves)
{
    // ops#55, a LinearPattern in Extent mode: 3 occurrences -> 2 moves instance 2 onto instance
    // 3's place. The reference to instance 3's top face (`X|TRF;3`) has no structural candidate,
    // and geometry alone finds instance 2's copy (`X|TRF;2`) in place: another element.
    Placed p;
    const auto x = p.names.oldTop;
    auto instance = [&](const std::string& name, int k) {
        return piece(name, 9, "TRF", k, 'F');
    };
    SolveInput input;
    input.diagonal = 30.0;
    input.entries = {missing(instance(x, 3))};
    input.entries[0].fingerprint = p.top;
    input.pool["Face"] = {element("Face4", {instance(x, 2)}), element("Face9", {x})};
    measure(input, {{"Face4", p.top}, {"Face9", p.topAt(-20)}}, nullptr);

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    const auto& candidates = outcomes[0].candidates;
    EXPECT_NE(std::find(candidates.begin(), candidates.end(), "Face4"), candidates.end());
    EXPECT_EQ(outcomes[0].evidence, "pattern sibling");

    //   the same through an embedded name: a face generated from instance 3's edge, and the one
    //   from instance 2's. An instance's number inside a linked name is an order key to the twin
    //   test (ops#503 D1): geometry's pick is the old name's twin, and without the twins' record
    //   it breaks
    const auto edge = generated({sketchEdge(1)}, 7, "XTR", 'E');
    auto faceOn = [&](int k) {
        return generated({piece(edge, 9, "TRF", k, 'E')}, 10, "FLT", 'F');
    };
    input.entries = {missing(faceOn(3))};
    input.entries[0].fingerprint = p.top;
    input.pool["Face"] = {element("Face4", {faceOn(2)})};
    measure(input, {{"Face4", p.top}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence,
              "ambiguous: Face4 is the old element's twin (no twin record, 1 now)");
}

TEST(SolveOwner, copySiblingsAreCounterSiblings)
{
    // ops#523, decision 157 (S1): copies of one element by copy makers of one kind are counter
    // siblings whatever their tags, and so are an element and its copy
    const auto x = generated({sketchEdge(1)}, 7, "XTR", 'E');
    auto ext = [](const std::string& name, int link, int index) {
        return name + "|" + section({}, {}, link, "EXT", index, 'E', {});
    };
    //   (a) two copy sections of any index, two boundary sections of one index
    EXPECT_TRUE(Data::isCounterSiblingName(copied(x, 11, "L", 'E'), copied(x, 12, "L", 'E')));
    EXPECT_TRUE(Data::isCounterSiblingName(copied(x, 11, "L1", 'E'), copied(x, 11, "L2", 'E')));
    EXPECT_TRUE(Data::isCounterSiblingName(copied(x, 11, "L1", 'E'), copied(x, 12, "L0", 'E')));
    EXPECT_TRUE(Data::isCounterSiblingName(ext(x, 11, 0), ext(x, 12, 0)));
    EXPECT_TRUE(Data::isCounterSiblingName(copied(x, 11, "1", 'E'), copied(x, 12, "1", 'E')));
    EXPECT_TRUE(Data::isCounterSiblingName(copied(x, 11, "L", 'E'), copied(x, 12, "1", 'E')));
    EXPECT_FALSE(Data::isCounterSiblingName(ext(x, 11, 0), ext(x, 12, 3)));
    EXPECT_FALSE(Data::isCounterSiblingName(ext(x, 11, 0), copied(x, 12, "L", 'E')));
    //   (b) the original and its copy by a link or a Scale; not by a pattern or a second side
    EXPECT_TRUE(Data::isCounterSiblingName(x, copied(x, 11, "L", 'E')));
    EXPECT_TRUE(Data::isCounterSiblingName(copied(x, 11, "L3", 'E'), x));
    EXPECT_TRUE(Data::isCounterSiblingName(x, copied(x, 11, "1", 'E')));
    EXPECT_FALSE(Data::isCounterSiblingName(x, copied(x, 11, "2", 'E')));
    EXPECT_FALSE(Data::isCounterSiblingName(x, piece(x, 9, "TRF", 1, 'E')));
    EXPECT_FALSE(Data::isCounterSiblingName(x, x));
    //   ... also inside the names made from them: a fuse's piece of each, a face on each
    const auto fusedOriginal = piece(x, 20, "FUS", 0, 'E');
    const auto fusedCopy = piece(copied(x, 11, "L", 'E'), 20, "FUS", 0, 'E');
    EXPECT_TRUE(Data::isCounterSiblingName(fusedOriginal, fusedCopy));
    EXPECT_TRUE(Data::isCounterSiblingName(
        generated({copied(x, 11, "L", 'E')}, 30, "FLT", 'F'),
        generated({copied(x, 12, "L", 'E')}, 30, "FLT", 'F')
    ));
    //   but not two copies of different elements, nor a copy with two more sections
    const auto y = generated({sketchEdge(2)}, 7, "XTR", 'E');
    EXPECT_FALSE(Data::isCounterSiblingName(copied(x, 11, "L", 'E'), copied(y, 12, "L", 'E')));
    EXPECT_FALSE(Data::isCounterSiblingName(x, copied(copied(x, 11, "L", 'E'), 12, "L", 'E')));
    EXPECT_FALSE(Data::isCounterSiblingName(y, copied(x, 11, "L", 'E')));
    //   the twin sites (copySiblings false; the A3 pre-push review's T1): another copy's twins
    //   are no twins of this one, but one copy's own counter siblings still are
    EXPECT_FALSE(
        Data::isCounterSiblingName(copied(x, 11, "L", 'E'), copied(x, 12, "L", 'E'), false)
    );
    EXPECT_FALSE(Data::isCounterSiblingName(ext(x, 11, 0), ext(x, 12, 0), false));
    EXPECT_FALSE(Data::isCounterSiblingName(x, copied(x, 11, "1", 'E'), false));
    const auto twin0 = section({}, {sketchEdge(1)}, 7, "XTR", 0, 'E', {"GEN"});
    const auto twin1 = Data::MappedName::makeEncodedSection(
        std::vector<std::string> {},
        std::vector<std::string> {sketchEdge(1)},
        "7",
        "XTR",
        "0",
        'E',
        "1",
        {"GEN"},
        std::vector<std::string> {}
    );
    EXPECT_TRUE(Data::isCounterSiblingName(
        copied(twin0, 11, "L", 'E'),
        copied(twin1, 11, "L", 'E'),
        false
    ));
    EXPECT_TRUE(Data::isCounterSiblingName(ext(twin0, 11, 0), ext(twin1, 11, 0), false));
    //   ... also inside the names made from them (the flag goes down into linked names)
    EXPECT_FALSE(Data::isCounterSiblingName(
        generated({copied(x, 11, "L", 'E')}, 30, "FLT", 'F'),
        generated({copied(x, 12, "L", 'E')}, 30, "FLT", 'F'),
        false
    ));
}

TEST(SolveOwner, linkCopySiblingNeverResolves)
{
    // ops#523: two links to one object in a fuse; copy 0 removed and copy 1 moved onto its place.
    // The reference to copy 0's top face (`X|CPY;L{11}`) has no structural candidate, and
    // geometry alone finds copy 1's (`X|CPY;L{12}`) in place: another element. The same when the
    // original itself is gone and its link copy moved onto its place (Fable review finding 1).
    Placed p;
    const auto x = p.names.oldTop;
    SolveInput input;
    input.diagonal = 30.0;
    input.entries = {missing(copied(x, 11, "L"))};
    input.entries[0].fingerprint = p.top;
    input.pool["Face"] = {element("Face4", {copied(x, 12, "L")})};
    measure(input, {{"Face4", p.top}}, nullptr);

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "pattern sibling");

    //   the original gone, its copy in its place
    input.entries = {missing(x)};
    input.entries[0].fingerprint = p.top;
    input.pool["Face"] = {element("Face4", {copied(x, 12, "L")})};
    measure(input, {{"Face4", p.top}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "pattern sibling");
}

TEST(SolveOwner, patternStepSiblingNeverResolves)
{
    // ops#6, a two-step pattern: the reference to instance (3, 2)'s top face is missing, and
    // geometry alone finds another instance's copy in place, (2, 2) or (2, 1). The sibling guard
    // takes any two numbers of one pattern's TRF sections as siblings, multi-step ones too.
    Placed p;
    const auto x = p.names.oldTop;
    SolveInput input;
    input.diagonal = 30.0;
    for (const char* sibling : {"2:2", "2"}) {
        input.entries = {missing(stepInstance(x, 9, "3:2"))};
        input.entries[0].fingerprint = p.top;
        input.pool["Face"] = {
            element("Face4", {stepInstance(x, 9, sibling)}),
            element("Face9", {x}),
        };
        measure(input, {{"Face4", p.top}, {"Face9", p.topAt(-20)}}, nullptr);

        auto outcomes = Data::solveOwner(input);

        EXPECT_EQ(outcomes[0].status, SolveStatus::Broken) << sibling;
        EXPECT_EQ(outcomes[0].evidence, "pattern sibling") << sibling;
    }
}

TEST(SolveOwner, lostOverlapOfInstancesHasNoPartnerThroughTheSupport)
{
    // ops#91, OverlappingInstances: blocks x 0..8, 5..13 and 10..18 overlap, and the top is
    // split where they do. Instance 3 is removed: the piece over instances 2 and 3 (x 10..13) is
    // gone. The piece over the support and instance 2 (x 5..8) shared most of its ancestry
    // through the instances' sections alone: tier 1's one survivor, coplanar, so the tier-1
    // check agreed, and the sketch moved there. Now nothing structural survives, and geometry
    // finds no piece in place: broken.
    const auto right = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto left = section({}, {sketchEdge(4)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto top = lowFace({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)});
    auto instance = [](const std::string& name, int k, char type) {
        return piece(name, 9, "TRF", k, type);
    };
    const auto top12 = section({}, {right, instance(left, 2, 'E')}, 9, "FUS", 0, 'F', {"LOW"});
    const auto top23 = section(
        {},
        {instance(right, 2, 'E'), instance(left, 3, 'E')},
        9,
        "FUS",
        0,
        'F',
        {"LOW"}
    );
    auto at = [](double x, double length) {
        Base::Vector3d up(0, 0, 1);
        return fingerprint('F', "Plane", 4 * length, Base::Vector3d(x, 2, 4), up);
    };
    SolveInput input;
    input.diagonal = 19.3;
    input.pool["Face"] = {
        element("Face4", {piece(top, 9, "FUS", 0, 'F')}),
        element("Face9", {top12}),
        element("Face13", {piece(instance(top, 2, 'F'), 9, "FUS", 0, 'F')}),
    };
    measure(
        input,
        {{"Face4", at(2.5, 5)}, {"Face9", at(6.5, 3)}, {"Face13", at(10.5, 5)}},
        nullptr
    );
    input.entries = {missing(top23)};
    input.entries[0].fingerprint = at(11.5, 3);

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U);
}

TEST(SolveOwner, supportReferenceHasNoPartnerAmongInstanceCopies)
{
    // ops#91, the review's case: the support's top right edge is gone, and the edges left that
    // embed instance 2's copy of it (a fusion's edges where instances 2 and 3 overlap) held it
    // wholly in their ancestry (overlap 1, in ancestry) through the instance's section. They
    // are other elements.
    const auto right = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto left = section({}, {sketchEdge(4)}, 7, "XTR", 0, 'E', {"PRJ"});
    auto instance = [](const std::string& name, int k) {
        return piece(name, 9, "TRF", k, 'E');
    };
    const auto top23 = section(
        {},
        {instance(right, 2), instance(left, 3)},
        9,
        "FUS",
        0,
        'F',
        {"LOW"}
    );
    const auto front23 = generated({instance(right, 2)}, 9, "FUS", 'F', 1);
    auto lineAlong = [](Base::Vector3d direction, double x) {
        return fingerprint('E', "Line", 3, Base::Vector3d(x, 0, 4), direction);
    };
    SolveInput input;
    input.diagonal = 19.3;
    // the edge between the overlap's top and front, along X, and a seam along Y
    input.pool["Edge"] = {
        element("Edge5", {upper({top23, front23}, 9, "FUS")}),
        element("Edge6", {section({}, {top23}, 9, "FUS", 0, 'E', {"GEN"})}),
    };
    measure(
        input,
        {{"Edge5", lineAlong(Base::Vector3d(1, 0, 0), 11.5)},
         {"Edge6", lineAlong(Base::Vector3d(0, 1, 0), 13)}},
        nullptr
    );
    input.entries = {missing(right, "Edge")};

    //   without a fingerprint: no structural candidate (before, both, in ancestry)
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(describe(outcomes[0]), "broken  -1 [] no candidate");
    //   with one: the seam along Y agrees in kind and direction, as a copy's edge does, which
    //   the tier-1 check let through; it isn't in place
    input.entries[0].fingerprint = lineAlong(Base::Vector3d(0, 1, 0), 8);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, std::vector<std::string> {"Edge6"});
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U);
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

    //   redrawn 5 mm over: tier 2 agrees on four edges, tier 3 on none; they're listed, the
    //   nearest the saved centre first (N3 5.3)
    input.entries[0].fingerprint = line(25, 10);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge4", "Edge2", "Edge3", "Edge1"}));
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
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge2", "Edge3", "Edge1"}));
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

    //   without a fingerprint the IDX source doesn't count: Face12 alone, which lost the old
    //   face's source (T1', ops#173)
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "no candidate; tier 1's 1 survivor lost the old element's source");
    EXPECT_EQ(outcomes[0].candidateRoles, std::vector<std::string> {"other source"});

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
    // can't both be used, so neither is forced. (Its old face has the pieces' source, line 1, or
    // T1' wouldn't keep the piece for it, ops#173.)
    SplitFace names;
    auto input = names.input({});
    input.entries[0].policy = Data::SolvePolicy::Expand;
    const auto otherOld = generated({sketchEdge(1)}, 7, "Extrude", 'F', 2);
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

// ops#284: a fillet (tag 9) on the edge beyond the old edge's end leaves a line on the top face,
// collinear with the old edge; when the old edge shortens, that line lies on its old place. It is
// the fillet's edge, made from the top face and the side face, and the side face puts the old
// edge's maker (tag 7) in its lineage: no piece. Another feature's MOD piece of the old edge
// keeps its maker and is one.
TEST(Continuation, anotherMakersEdgeIsNoPiece)
{
    Notch notch;
    const std::string topFace = generated({sketchEdge(4)}, 7, "Extrude", 'F', 1);
    const std::string sideFace = generated({sketchEdge(1)}, 7, "Extrude", 'F', 2);
    const std::string filletEnd = upper({topFace, sideFace}, 9, "FLT");
    ASSERT_EQ(NameAncestry::makerTag(filletEnd), "9");
    ASSERT_TRUE(NameAncestry::hasLineageTag(filletEnd, "7"));
    const std::string kept = "exact Edge1 0 [] ";
    for (auto policy :
         {Data::SolvePolicy::Expand, Data::SolvePolicy::One, Data::SolvePolicy::Equivalent}) {
        auto input = notch.input(policy);
        input.pool["Edge"][1].names = {filletEnd};
        EXPECT_EQ(describe(Data::solveOwner(input)[0]), kept) << static_cast<int>(policy);

        //   past the old end too: no run-past break
        auto fps = notch.fingerprints;
        fps["Edge2"] = lineX(12, 26);
        measure(input, fps, nullptr);
        EXPECT_EQ(describe(Data::solveOwner(input)[0]), kept) << static_cast<int>(policy);
    }

    //   a later feature's piece of the old edge (MOD) keeps its maker
    auto input = notch.input(Data::SolvePolicy::Expand);
    input.pool["Edge"][1].names = {piece(notch.hitName, 9, "FLT", 1, 'E')};
    EXPECT_EQ(Data::solveOwner(input)[0].elements, (std::vector<std::string> {"Edge1", "Edge2"}));

    //   one of its names with the maker is enough
    input.pool["Edge"][1].names = {filletEnd, notch.pieceName};
    EXPECT_EQ(Data::solveOwner(input)[0].elements, (std::vector<std::string> {"Edge1", "Edge2"}));

    //   without sameMaker, as before
    input.pool["Edge"][1].names = {filletEnd};
    input.sameMaker = false;
    EXPECT_EQ(Data::solveOwner(input)[0].elements, (std::vector<std::string> {"Edge1", "Edge2"}));

    //   a mixed pool: the piece (Edge2) is taken; another maker's edge on the shared face is
    //   skipped, named in the evidence when it lies within the old edge (Edge3, 9..11), and no
    //   run-past break when it runs past the end (14..26)
    input = notch.input(Data::SolvePolicy::Expand);
    input.pool["Edge"][2].names = {filletEnd};
    auto fps = notch.fingerprints;
    fps["Edge3"] = lineX(9, 11);
    measure(input, fps, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.tier, 4);
    EXPECT_EQ(outcome.elements, (std::vector<std::string> {"Edge1", "Edge2"}));
    EXPECT_EQ(
        outcome.evidence,
        "continued by Edge2 (line within the old edge, shares Face1), skipped Edge3 "
        "(another maker)"
    );
    fps["Edge3"] = lineX(14, 26);
    measure(input, fps, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
    EXPECT_EQ(outcome.elements, (std::vector<std::string> {"Edge1", "Edge2"}));
    EXPECT_EQ(outcome.evidence, "continued by Edge2 (line within the old edge, shares Face1)");
}

TEST(Continuation, piecesLeaveOtherPools)
{
    // A missing reference whose only candidate (a name match) is the piece taken: broken, unless
    // the piece holds its old name in its ancestry (a proven merge: a MOD section that holds
    // it; through a GEN section the old name would be a source, ops#358).
    Notch notch;
    const auto old = generated({sketchEdge(5)}, 7, "Extrude", 'E', 4);
    auto input = notch.input(Data::SolvePolicy::Expand);
    input.entries.push_back(missing(old, "Edge", {notch.pieceName}));

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].tier, 4);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Broken) << describe(outcomes[1]);

    //   (made by the hit's maker: another feature's edge is no piece of the hit, ops#284)
    notch.pieceName = section({}, {old}, 7, "FUS", 0, 'E', {"MOD"});
    input = notch.input(Data::SolvePolicy::Expand);
    input.entries.push_back(missing(old, "Edge", {notch.pieceName}));
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].tier, 4);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Resolved) << describe(outcomes[1]);
    EXPECT_EQ(outcomes[1].element, "Edge2");

    //   made by another feature (tag 9; the review of fork PR 257: no boolean names a merged
    //   piece so, it reports pieces as modified): no piece of the hit, which stays exact, and
    //   the missing reference follows its merge
    notch.pieceName = section({}, {old}, 9, "FUS", 0, 'E', {"MOD"});
    input = notch.input(Data::SolvePolicy::Expand);
    input.entries.push_back(missing(old, "Edge", {notch.pieceName}));
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(describe(outcomes[0]), "exact Edge1 0 [] ");
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

// Arcs (Task 2 PR 7b): the continuation along a circle, located by its centre.

namespace
{

constexpr double Pi = 3.14159265358979323846;

// An arc of the circle of radius r around \a centre (axis +Z) from \a from to \a to degrees
// (counter-clockwise), as a version-2 fingerprint.
ElementFingerprint arcOf(
    double r,
    double from,
    double to,
    Base::Vector3d centre = Base::Vector3d(10, 5, 10),
    Base::Vector3d axis = Base::Vector3d(0, 0, 1)
)
{
    const double a0 = from * Pi / 180;
    const double a1 = to * Pi / 180;
    const double half = (a1 - a0) / 2;
    const double middle = (a0 + a1) / 2;
    // The centre of mass: on the bisector, r sin(half) / half from the centre.
    const double distance = r * std::sin(half) / half;
    auto fp = fingerprint('E',
                          "Circle",
                          r * (a1 - a0),
                          centre + Base::Vector3d(std::cos(middle), std::sin(middle), 0) * distance,
                          axis,
                          {r});
    fp.location = centre;
    return fp;
}

// An arc of radius 5, -60..60 degrees, whose reference holds its fingerprint; a notch leaves
// the hit (Edge1, -60..-10) and a piece (Edge2, 10..60), both on the pad's top face (Face1).
struct ArcNotch
{
    const double diagonal = std::sqrt(20.0 * 20 + 10 * 10 + 10 * 10);
    const double eps = 1e-7 * diagonal;
    ElementFingerprint old = arcOf(5, -60, 60);
    std::map<std::string, ElementFingerprint> fingerprints {
        {"Edge1", arcOf(5, -60, -10)},
        {"Edge2", arcOf(5, 10, 60)},
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
            element("Edge1", {"a1"}),
            element("Edge2", {"a2"}),
            element("Edge3", {"a3"}),
        };
        auto hit = exact("Edge1", "Edge");
        hit.exactName = "a1";
        hit.fingerprint = old;
        hit.policy = policy;
        input.entries = {hit};
        measure(input, fingerprints, nullptr);
        input.facesOf = [map = faces](const std::string& index) {
            auto it = map.find(index);
            return it == map.end() ? std::vector<std::string>() : it->second;
        };
        return input;
    }
};

}  // namespace

TEST(Continuation, arcOnTheSameCircleIsTaken)
{
    ArcNotch notch;
    GeometryTolerances tolerances;
    auto within = [&](const ElementFingerprint& now) {
        return Data::hitWithinOldEdge(notch.old, now, notch.diagonal, tolerances, 1e-7);
    };
    EXPECT_TRUE(within(arcOf(5, -60, -10)));
    EXPECT_FALSE(within(arcOf(5, -60, 60)));
    EXPECT_FALSE(within(arcOf(5, -70, 0)));

    auto outcome = Data::solveOwner(notch.input(Data::SolvePolicy::Expand))[0];

    EXPECT_EQ(outcome.status, SolveStatus::Resolved);
    EXPECT_EQ(outcome.tier, 4);
    EXPECT_EQ(outcome.elements, (std::vector<std::string> {"Edge1", "Edge2"}));
    EXPECT_EQ(outcome.evidence, "continued by Edge2 (arc within the old edge, shares Face1)");

    //   One breaks
    auto one = Data::solveOwner(notch.input(Data::SolvePolicy::One))[0];
    EXPECT_EQ(one.status, SolveStatus::Broken);
    EXPECT_EQ(one.candidates, (std::vector<std::string> {"Edge1", "Edge2"}));
}

TEST(Continuation, arcMustNotTake)
{
    ArcNotch notch;
    const double eps = notch.eps;
    const std::string kept = "exact Edge1 0 [] ";
    struct Case
    {
        const char* what;
        std::function<void(SolveInput&, std::map<std::string, ElementFingerprint>&)> change;
    };
    std::vector<Case> cases {
        {"concentric, another radius",
         [](auto&, auto& fps) { fps["Edge2"] = arcOf(3, 10, 60); }},
        {"the same circle beyond the old ends",
         [](auto&, auto& fps) { fps["Edge2"] = arcOf(5, 120, 240); }},
        {"the centre moved by 2 eps",
         [&](auto&, auto& fps) {
             fps["Edge2"] = arcOf(5, 10, 60, Base::Vector3d(10 + 2 * eps, 5, 10));
         }},
        {"the axis tilted by 2 x the angle",
         [](auto&, auto& fps) {
             fps["Edge2"].direction = Base::Vector3d(std::sin(2e-6), 0, std::cos(2e-6));
         }},
        {"a version-1 saved fingerprint",
         [](auto& input, auto&) { input.entries[0].fingerprint.location.reset(); }},
        {"no shared face",
         [](auto& input, auto&) {
             input.facesOf = [](const std::string& index) {
                 return index == "Edge1" ? std::vector<std::string> {"Face1"}
                                         : std::vector<std::string> {"Face9"};
             };
         }},
    };
    for (const auto& c : cases) {
        auto input = notch.input(Data::SolvePolicy::Expand);
        auto fps = notch.fingerprints;
        c.change(input, fps);
        measure(input, fps, nullptr);
        EXPECT_EQ(describe(Data::solveOwner(input)[0]), kept) << c.what;
    }
}

TEST(Continuation, arcRunPastBreaks)
{
    ArcNotch notch;
    auto input = notch.input(Data::SolvePolicy::Expand);
    auto fps = notch.fingerprints;
    fps["Edge2"] = arcOf(5, 10, 80);
    measure(input, fps, nullptr);

    auto outcome = Data::solveOwner(input)[0];

    EXPECT_EQ(outcome.status, SolveStatus::Broken);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge1", "Edge2"}));
    EXPECT_EQ(outcome.evidence, "continued past the old edge by Edge2");
}

TEST(Continuation, fullCircleSplit)
{
    // A whole circle, split: the hit 0..150, the rest 210..360.
    ArcNotch notch;
    auto input = notch.input(Data::SolvePolicy::Expand);
    input.entries[0].fingerprint = arcOf(5, 0, 360);
    auto fps = notch.fingerprints;
    fps["Edge1"] = arcOf(5, 0, 150);
    fps["Edge2"] = arcOf(5, 210, 360);
    measure(input, fps, nullptr);

    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.tier, 4) << describe(outcome);
    EXPECT_EQ(outcome.elements, (std::vector<std::string> {"Edge1", "Edge2"}));

    //   a third piece overlapping the hit: broken
    fps["Edge3"] = arcOf(5, 140, 200);
    measure(input, fps, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken);
    EXPECT_EQ(outcome.evidence, "pieces overlap");

    //   a piece across the start of the circle, as seen from the hit, is still on it
    fps = notch.fingerprints;
    fps["Edge1"] = arcOf(5, 90, 180);
    fps["Edge2"] = arcOf(5, 200, 420);
    measure(input, fps, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].tier, 4);
}

TEST(Continuation, wholeCircleCollapses)
{
    // A notch in a whole circle, filled in again: the kept piece is the whole circle once more,
    // and the missing rest's saved arc lies on it, so the group collapses.
    ArcNotch notch;
    const auto x = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    const auto y = generated({sketchEdge(9)}, 7, "Extrude", 'E', 1);
    SolveInput input;
    input.diagonal = notch.diagonal;
    input.pool["Edge"] = {element("Edge1", {x})};
    measure(input, {{"Edge1", arcOf(5, 0, 360)}}, nullptr);
    auto rest = missing(y, "Edge");
    rest.fingerprint = arcOf(5, 210, 360);
    input.entries = {member(exact("Edge1", "Edge"), x, "a", 0), member(rest, x, "a", 1)};

    auto outcomes = Data::solveOwner(input);

    EXPECT_TRUE(outcomes[0].collapsed) << describe(outcomes[0]);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Removed);

    //   a rest on another circle didn't merge back
    input.entries[1].fingerprint = arcOf(3, 210, 360);
    outcomes = Data::solveOwner(input);
    EXPECT_FALSE(outcomes[0].collapsed);
    EXPECT_NE(outcomes[1].status, SolveStatus::Removed);
}

TEST(Continuation, nearlyFullArcIsNotLocatable)
{
    // Its centre of mass is within 1e-6 r of the circle's centre: the bisector isn't reliable.
    ArcNotch notch;
    auto input = notch.input(Data::SolvePolicy::Expand);
    input.entries[0].fingerprint = arcOf(5, -179.9999, 179.9999);
    auto fps = notch.fingerprints;
    fps["Edge1"] = arcOf(5, 0, 150);
    fps["Edge2"] = arcOf(5, 170, 300);
    measure(input, fps, nullptr);

    EXPECT_EQ(describe(Data::solveOwner(input)[0]), "exact Edge1 0 [] ");
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

// With the old face's extent (fingerprint version 3, Task 2 PR 8)

namespace
{

// frontFace() with its bounding box.
ElementFingerprint boxedFront(double x0, double x1, double y = 0.0)
{
    auto fp = frontFace(x0, x1, y);
    fp.extentMin = Base::Vector3d(x0, y, 0);
    fp.extentMax = Base::Vector3d(x1, y, 10);
    return fp;
}

}  // namespace

TEST(SplitFace, faceExtentRelation)
{
    const double diagonal = 24.5;
    const double eps = 1e-7 * diagonal;
    auto old = boxedFront(0, 20);
    auto relation = [&](const ElementFingerprint& face) {
        return Data::faceExtentRelation(old, face, diagonal, 1e-7);
    };
    using Data::ExtentRelation;
    EXPECT_EQ(relation(boxedFront(12, 20)), ExtentRelation::Inside);
    EXPECT_EQ(relation(boxedFront(0, 20 + 0.5 * eps)), ExtentRelation::Inside);
    EXPECT_EQ(relation(boxedFront(12, 26)), ExtentRelation::Overlapping);
    EXPECT_EQ(relation(boxedFront(0, 20 + 2 * eps)), ExtentRelation::Overlapping);
    EXPECT_EQ(relation(boxedFront(24, 30)), ExtentRelation::Outside);
    //   touching the old face's end only: no point of it
    EXPECT_EQ(relation(boxedFront(20, 26)), ExtentRelation::Outside);
    EXPECT_EQ(relation(boxedFront(20 - 0.5 * eps, 26)), ExtentRelation::Outside);
    EXPECT_EQ(relation(boxedFront(20 - 2 * eps, 26)), ExtentRelation::Overlapping);
    //   the axis of the normal is degenerate in both boxes, and doesn't separate them
    EXPECT_EQ(relation(boxedFront(4, 8, 0.5 * eps)), ExtentRelation::Inside);
    //   without an extent, nothing is known
    EXPECT_EQ(relation(frontFace(24, 30)), ExtentRelation::Unknown);
    EXPECT_EQ(Data::faceExtentRelation(frontFace(0, 20), boxedFront(24, 30), diagonal, 1e-7),
              ExtentRelation::Unknown);
}

TEST(SplitFace, extentInsideBreaks)
{
    // The notch, with boxes: the rest (x 12..20) lies within the old face (x 0..20).
    FrontNotch notch;
    for (auto policy : {Data::SolvePolicy::Expand, Data::SolvePolicy::One}) {
        auto input = notch.input(policy);
        auto fps = notch.fingerprints;
        fps["Face1"] = boxedFront(0, 8);
        fps["Face2"] = boxedFront(12, 20);
        input.entries[0].fingerprint = boxedFront(0, 20);
        measure(input, fps, nullptr);
        auto outcome = Data::solveOwner(input)[0];
        EXPECT_EQ(outcome.status, SolveStatus::Broken) << static_cast<int>(policy);
        EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face1", "Face2"}));
        EXPECT_EQ(outcome.evidence, "split: a coplanar face beside it, Face2");
    }
}

TEST(SplitFace, extentOverlappingBreaksUnderEveryPolicy)
{
    // The notch with the right side moved out to x = 26: the rest runs past the old face's end.
    // Even an Equivalent reference whose probe agrees breaks.
    FrontNotch notch;
    for (auto policy :
         {Data::SolvePolicy::Expand, Data::SolvePolicy::One, Data::SolvePolicy::Equivalent}) {
        auto input = notch.input(policy);
        auto fps = notch.fingerprints;
        fps["Face1"] = boxedFront(0, 8);
        fps["Face2"] = boxedFront(12, 26);
        input.entries[0].fingerprint = boxedFront(0, 20);
        measure(input, fps, nullptr);
        auto outcome = Data::solveOwner(input)[0];
        EXPECT_EQ(outcome.status, SolveStatus::Broken) << static_cast<int>(policy);
        EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face1", "Face2"}));
        EXPECT_EQ(outcome.evidence,
                  "split: a coplanar face beside it runs past the old face, Face2");
    }
}

TEST(SplitFace, extentOutsideIsIgnored)
{
    // A U's prong narrowed (DraftUProngNarrowed): the old end face was x 0..6, now 0..4; the
    // other prong's end face (x 14..20) is coplanar and shares the top and bottom faces, but
    // lies outside the old face. The hit stands.
    FrontNotch notch;
    for (auto policy :
         {Data::SolvePolicy::Expand, Data::SolvePolicy::One, Data::SolvePolicy::Equivalent}) {
        auto input = notch.input(policy);
        auto fps = notch.fingerprints;
        fps["Face1"] = boxedFront(0, 4);
        fps["Face2"] = boxedFront(14, 20);
        input.entries[0].fingerprint = boxedFront(0, 6);
        measure(input, fps, nullptr);
        EXPECT_EQ(describe(Data::solveOwner(input)[0]), "exact Face1 0 [] ")
            << static_cast<int>(policy);
    }
    //   with a version-1 saved fingerprint, the other face still counts: broken
    auto input = notch.input(Data::SolvePolicy::Expand);
    auto fps = notch.fingerprints;
    fps["Face1"] = boxedFront(0, 4);
    fps["Face2"] = boxedFront(14, 20);
    input.entries[0].fingerprint = frontFace(0, 6);
    measure(input, fps, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
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

TEST(RebuildSubList, guessedSetsTheRecord)
{
    // ops#127: a provisional pick writes its sub as Resolved does (its fingerprint is measured
    // anew) and gets the record; Resolved and Broken clear a record; untouched references keep
    // theirs.
    using Status = App::SolverResolution::Status;
    std::vector<std::string> subs {"?Edge5", "Edge7", "Edge8", "Edge9"};
    std::vector<App::PropertyLinkBase::ShadowSub> shadows {
        shadowOf("?Edge5", ";e.Edge5"),
        shadowOf("Edge7", ";g.Edge7"),
        shadowOf("Edge8", ";k.Edge8"),
        shadowOf("Edge9", ";m.Edge9"),
    };
    std::vector<std::string> fingerprints {"f5", "f7", "f8", "f9"};
    std::vector<std::string> froms {"", "", "", ""};
    App::GuessRecord kept;
    kept.kind = "tier3";
    kept.origName = "z";
    kept.origIndex = "Edge2";
    App::GuessRecord old;
    old.kind = "tier2";
    old.origName = "y";
    old.origIndex = "Edge1";
    std::vector<App::ElementRecords> records {{}, {old, {}}, {old, {}}, {kept, {}}};

    //   index 0 is guessed as Edge6
    auto guessed = resolution(Status::Guessed, 0);
    guessed.sub = "Edge6";
    guessed.shadow = shadowOf("Edge6", ";f.Edge6");
    guessed.guess.kind = "tier3";
    guessed.guess.origName = "e";
    guessed.guess.origIndex = "Edge5";
    guessed.guess.alternatives = {{"Edge4", "structural", 1.5}};
    //   index 1 snaps back (Resolved), index 2 breaks
    auto resolved = resolution(Status::Resolved, 1);
    resolved.sub = "Edge1";
    resolved.shadow = shadowOf("Edge1", ";y.Edge1");
    auto broken = resolution(Status::Broken, 2);
    broken.sub = "?Edge1";
    broken.shadow = shadowOf("?Edge1", ";y.Edge1");

    std::vector<int> firstNew;
    std::vector<int> countNew;
    std::vector<App::SolverResolution> resolutions {guessed, resolved, broken};
    EXPECT_TRUE(App::rebuildSubList(resolutions,
                                    subs,
                                    shadows,
                                    fingerprints,
                                    froms,
                                    firstNew,
                                    countNew,
                                    &records));

    EXPECT_EQ(subs, (std::vector<std::string> {"Edge6", "Edge1", "?Edge1", "Edge9"}));
    //   the broken reference keeps its fingerprint for a retry
    EXPECT_EQ(fingerprints, (std::vector<std::string> {"", "", "f8", "f9"}));
    ASSERT_EQ(records.size(), 4U);
    EXPECT_EQ(records[0].guess, guessed.guess);
    EXPECT_TRUE(records[1].guess.empty());
    EXPECT_TRUE(records[2].guess.empty());
    EXPECT_EQ(records[3].guess, kept);
}

TEST(RebuildSubList, guessedPiecesCarryTheRecord)
{
    // ops#127: a split or continuation expanded gives every piece the record; a piece another
    // reference holds already is skipped.
    using Status = App::SolverResolution::Status;
    std::vector<std::string> subs {"Edge3", "Edge4"};
    std::vector<App::PropertyLinkBase::ShadowSub> shadows {
        shadowOf("Edge3", ";a.Edge3"),
        shadowOf("Edge4"),
    };
    std::vector<std::string> fingerprints {"f3", "f4"};
    std::vector<std::string> froms {"", ""};
    std::vector<App::ElementRecords> records;

    auto expanded = resolution(Status::Guessed, 0);
    expanded.from = "a";
    expanded.guess.kind = "continued";
    expanded.guess.origName = "a";
    expanded.guess.origIndex = "Edge3";
    expanded.pieces = {
        {"Edge3", shadowOf("Edge3", ";a.Edge3")},
        {"Edge4", shadowOf("Edge4", ";b.Edge4")},
        {"Edge6", shadowOf("Edge6", ";c.Edge6")},
    };
    std::vector<int> firstNew;
    std::vector<int> countNew;
    std::vector<App::SolverResolution> resolutions {expanded};
    EXPECT_TRUE(App::rebuildSubList(resolutions,
                                    subs,
                                    shadows,
                                    fingerprints,
                                    froms,
                                    firstNew,
                                    countNew,
                                    &records));

    EXPECT_EQ(subs, (std::vector<std::string> {"Edge3", "Edge6", "Edge4"}));
    EXPECT_EQ(fingerprints, (std::vector<std::string> {"", "", "f4"}));
    EXPECT_EQ(froms, (std::vector<std::string> {"a", "a", ""}));
    ASSERT_EQ(records.size(), 3U);
    EXPECT_EQ(records[0].guess, expanded.guess);
    EXPECT_EQ(records[1].guess, expanded.guess);
    EXPECT_TRUE(records[2].guess.empty());
    EXPECT_EQ(countNew, (std::vector<int> {2, 1}));
}

TEST(RebuildSubList, guessedOntoAHeldElementWritesNoSecondSub)
{
    // ops#138, the Opus verification of fork PR 249 round 1, finding 3: a guess whose element
    // another reference holds already (untouched, or written before it) adds no second sub.
    using Status = App::SolverResolution::Status;
    std::vector<std::string> subs {"Edge3", "?Edge5", "?Edge7"};
    std::vector<App::PropertyLinkBase::ShadowSub> shadows {
        shadowOf("Edge3", ";a.Edge3"),
        shadowOf("?Edge5", ";b.Edge5"),
        shadowOf("?Edge7", ";c.Edge7"),
    };
    std::vector<std::string> fingerprints {"f3", "f5", "f7"};
    std::vector<std::string> froms {"", "", ""};
    std::vector<App::ElementRecords> records;

    //   index 1 is guessed onto Edge3, which index 0 holds; index 2 onto Edge9, new
    auto held = resolution(Status::Guessed, 1);
    held.sub = "Edge3";
    held.shadow = shadowOf("Edge3", ";a.Edge3");
    held.guess.kind = "piece";
    held.guess.origName = "b";
    held.guess.origIndex = "Edge5";
    auto fresh = resolution(Status::Guessed, 2);
    fresh.sub = "Edge9";
    fresh.shadow = shadowOf("Edge9", ";d.Edge9");
    fresh.guess.kind = "piece";
    fresh.guess.origName = "c";
    fresh.guess.origIndex = "Edge7";
    std::vector<int> firstNew;
    std::vector<int> countNew;
    std::vector<App::SolverResolution> resolutions {held, fresh};
    EXPECT_TRUE(App::rebuildSubList(resolutions,
                                    subs,
                                    shadows,
                                    fingerprints,
                                    froms,
                                    firstNew,
                                    countNew,
                                    &records));

    EXPECT_EQ(subs, (std::vector<std::string> {"Edge3", "Edge9"}));
    EXPECT_EQ(countNew, (std::vector<int> {1, 0, 1}));
    ASSERT_EQ(records.size(), 2U);
    EXPECT_TRUE(records[0].guess.empty());
    EXPECT_EQ(records[1].guess, fresh.guess);
}

namespace
{

Data::ElementFingerprint lineFingerprint(double x0, double x1)
{
    Data::ElementFingerprint fp;
    fp.type = 'E';
    fp.kind = "Line";
    fp.size = x1 - x0;
    fp.center = Base::Vector3d((x0 + x1) / 2, 0, 0);
    fp.direction = Base::Vector3d(1, 0, 0);
    return fp;
}

Data::ElementFingerprint planeFingerprint(double x0, double x1, double z1)
{
    Data::ElementFingerprint fp;
    fp.type = 'F';
    fp.kind = "Plane";
    fp.size = (x1 - x0) * z1;
    fp.center = Base::Vector3d((x0 + x1) / 2, 0, z1 / 2);
    fp.direction = Base::Vector3d(0, -1, 0);
    fp.extentMin = Base::Vector3d(x0, 0, 0);
    fp.extentMax = Base::Vector3d(x1, 0, z1);
    return fp;
}

Data::ElementFingerprint arcFingerprint(double from, double to)
{
    // An arc of the unit circle about the origin in z = 0, from angle \a from to \a to
    const double mid = (from + to) / 2;
    Data::ElementFingerprint fp;
    fp.type = 'E';
    fp.kind = "Circle";
    fp.size = to - from;
    fp.center = Base::Vector3d(std::cos(mid), std::sin(mid), 0);  // on the bisector
    fp.direction = Base::Vector3d(0, 0, 1);
    fp.radii = {1};
    fp.location = Base::Vector3d(0, 0, 0);
    return fp;
}

}  // namespace

TEST(CoversExtent, aLineCoversTheSavedSegment)
{
    // ops#138 (PR 249 verification, finding 1): a piece holding the saved centre isn't enough
    const auto saved = lineFingerprint(0, 20);
    EXPECT_TRUE(Data::coversExtent(saved, lineFingerprint(0, 20), 20, 1e-7));
    EXPECT_TRUE(Data::coversExtent(saved, lineFingerprint(-2, 26), 20, 1e-7));
    EXPECT_TRUE(Data::holdsCentre(saved, lineFingerprint(0, 12), 20, 1e-7));
    EXPECT_FALSE(Data::coversExtent(saved, lineFingerprint(0, 12), 20, 1e-7));
    EXPECT_FALSE(Data::coversExtent(saved, lineFingerprint(8, 20), 20, 1e-7));
}

TEST(CoversExtent, aPlaneCoversTheSavedBoxAndArea)
{
    const auto saved = planeFingerprint(0, 20, 10);
    //   the ops#138 scenario's merged face, 12 high, covers the saved 10 high
    EXPECT_TRUE(Data::coversExtent(saved, planeFingerprint(0, 20, 12), 20, 1e-7));
    //   the named piece x 0..12 holds the centre (x = 10) but not the extent
    EXPECT_TRUE(Data::holdsCentre(saved, planeFingerprint(0, 12, 10), 20, 1e-7));
    EXPECT_FALSE(Data::coversExtent(saved, planeFingerprint(0, 12, 10), 20, 1e-7));
    //   a piece whose box spans the saved box but lost a part inside it (a U): its area
    auto u = planeFingerprint(0, 20, 10);
    u.size = 160;
    EXPECT_FALSE(Data::coversExtent(saved, u, 20, 1e-7));
}

TEST(CoversExtent, anArcCoversTheSavedRange)
{
    const double pi = std::numbers::pi;
    const auto saved = arcFingerprint(0, pi / 2);
    EXPECT_TRUE(Data::coversExtent(saved, arcFingerprint(0, pi / 2), 2, 1e-7));
    EXPECT_TRUE(Data::coversExtent(saved, arcFingerprint(-pi / 4, pi), 2, 1e-7));
    EXPECT_TRUE(Data::holdsCentre(saved, arcFingerprint(pi / 8, pi / 2), 2, 1e-7));
    EXPECT_FALSE(Data::coversExtent(saved, arcFingerprint(pi / 8, pi / 2), 2, 1e-7));
    //   another circle
    auto bigger = arcFingerprint(0, pi / 2);
    bigger.radii = {2};
    EXPECT_FALSE(Data::coversExtent(saved, bigger, 2, 1e-7));
}

TEST(CoversExtent, otherKindsNeverCover)
{
    // Curved faces, B-splines, vertices, and a saved record without a fingerprint
    Data::ElementFingerprint cylinder;
    cylinder.type = 'F';
    cylinder.kind = "Cylinder";
    cylinder.size = 10;
    cylinder.center = Base::Vector3d(0, 0, 0);
    EXPECT_FALSE(Data::coversExtent(cylinder, cylinder, 20, 1e-7));
    Data::ElementFingerprint vertex;
    vertex.type = 'V';
    vertex.kind = "Vertex";
    vertex.center = Base::Vector3d(0, 0, 0);
    EXPECT_FALSE(Data::coversExtent(vertex, vertex, 20, 1e-7));
    EXPECT_FALSE(Data::coversExtent(Data::ElementFingerprint(), lineFingerprint(0, 20), 20, 1e-7));
}

TEST(GuessRecord, attributesRoundTrip)
{
    App::GuessRecord record;
    record.kind = "tier3";
    record.origName = ";g3;SKT;:H1:7,E";
    record.origIndex = "Edge5";
    record.alternatives = {{"Edge9", "structural", 1.2},
                           {"Edge11", "geometric", std::numeric_limits<double>::quiet_NaN()}};
    EXPECT_EQ(record.origText(), ";;g3;SKT;:H1:7,E.Edge5");
    EXPECT_EQ(record.altText(), "Edge9|structural|1.2,Edge11|geometric|");

    auto back = App::GuessRecord::fromAttributes(record.kind, record.origText(), record.altText());
    EXPECT_EQ(back, record);

    //   an original without a name: its index alone
    App::GuessRecord indexOnly;
    indexOnly.kind = "index";
    indexOnly.origIndex = "Face6";
    EXPECT_EQ(indexOnly.origText(), "Face6");
    EXPECT_EQ(App::GuessRecord::fromAttributes("index", "Face6", ""), indexOnly);

    //   no kind: no record
    EXPECT_TRUE(App::GuessRecord::fromAttributes("", "Edge5", "").empty());
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
    //   circles' centres (version 2, Task 2 PR 7b): compared only when both have one
    auto located = circle;
    located.location = Base::Vector3d(0, 0, 0);
    EXPECT_TRUE(App::fingerprintsAgree(circle, located, 10.0));
    EXPECT_TRUE(App::fingerprintsAgree(located, circle, 10.0));
    EXPECT_TRUE(App::fingerprintsAgree(located, located, 10.0));
    auto shifted = located;
    shifted.location = Base::Vector3d(1e-3, 0, 0);
    EXPECT_FALSE(App::fingerprintsAgree(located, shifted, 10.0));
    //   planes' extents (version 3, Task 2 PR 8): the same
    auto boxed = saved;
    boxed.extentMin = Base::Vector3d(0, 5, 20);
    boxed.extentMax = Base::Vector3d(10, 15, 20);
    EXPECT_TRUE(App::fingerprintsAgree(saved, boxed, 50.0));
    EXPECT_TRUE(App::fingerprintsAgree(boxed, saved, 50.0));
    auto wider = boxed;
    wider.extentMax = Base::Vector3d(10, 15.001, 20);
    EXPECT_FALSE(App::fingerprintsAgree(boxed, wider, 50.0));
}

// ---------------------------------------------------------------------------------------------
// Tier 1's variants (Task 2 PR 8)

TEST(NameAncestry, referenceIdsWidenLeaves)
{
    // ops#76: a sketch corner's vertex `g1v2,g2v1` renamed `g12v2,g2v1`. As nodes the two
    // vertices share nothing; their Reference ID g2v1 of sketch 5 is shared.
    const auto oldEdge = generated({sketchVertex({"g1v2", "g2v1"})}, 6, "XTR", 'E');
    const auto renamed = generated({sketchVertex({"g12v2", "g2v1"})}, 6, "XTR", 'E');
    const auto otherSketch = generated({sketchVertex({"g12v2", "g2v1"}, 7)}, 6, "XTR", 'E');
    NameAncestry plain;
    EXPECT_EQ(plain.overlap(oldEdge, renamed), 0.0);
    NameAncestry widened(Data::OverlapMeasure::ReferenceIds);
    //   A*(old) = {old, the vertex, g1v2@5, g2v1@5}; the renamed edge shares g2v1@5
    EXPECT_DOUBLE_EQ(widened.overlap(oldEdge, renamed), 0.25);
    EXPECT_EQ(widened.overlap(oldEdge, otherSketch), 0.0);
    //   the leaves widen the overlap, never the ancestry itself
    EXPECT_TRUE(widened.contains(renamed, sketchVertex({"g12v2", "g2v1"})));
    EXPECT_FALSE(widened.contains(renamed, sketchVertex({"g1v2", "g2v1"})));
}

TEST(NameAncestry, depthWeightedOverlap)
{
    // old -> its face (depth 1) -> the face's two sketch edges (depth 2): weights 1, 1/2, 1/4,
    // 1/4, total 2. A candidate embedding one edge shares 1/4 of 2; plainly 1 of 4.
    const auto face = lowFace({sketchEdge(1), sketchEdge(2)});
    const auto oldName = generated({face}, 6, "XTR", 'E');
    const auto oneEdge = generated({sketchEdge(1)}, 7, "XTR", 'E');
    const auto sameFace = generated({face}, 7, "XTR", 'E');
    NameAncestry plain;
    EXPECT_DOUBLE_EQ(plain.overlap(oldName, oneEdge), 0.25);
    NameAncestry weighted(Data::OverlapMeasure::DepthWeighted);
    EXPECT_DOUBLE_EQ(weighted.overlap(oldName, oneEdge), 0.125);
    EXPECT_DOUBLE_EQ(weighted.overlap(oldName, sameFace), 0.5);
    EXPECT_DOUBLE_EQ(weighted.overlap(oldName, oldName), 1.0);
    //   the same result whatever was asked first
    NameAncestry again(Data::OverlapMeasure::DepthWeighted);
    EXPECT_DOUBLE_EQ(again.overlap(oldName, sameFace), 0.5);
    EXPECT_DOUBLE_EQ(again.overlap(oldName, oneEdge), 0.125);
}

TEST(SolveOwner, tier1CheckBreaksAPartnerOfAnotherGeometry)
{
    // ops#87: the reference's element (a B-spline edge) is gone; the only tier-1 survivor
    // shares its sources and its top section, but is a circle. (Not its Index twin, which the
    // twin clause hands to geometry, ops#503 D1.)
    const auto oldName = generated({sketchEdge(1)}, 6, "XTR", 'E');
    const auto survivor = generated({sketchEdge(1), sketchEdge(2)}, 6, "XTR", 'E');
    SolveInput input;
    input.diagonal = 30.0;
    input.pool["Edge"] = {element("Edge4", {survivor})};
    auto entry = missing(oldName, "Edge");
    entry.fingerprint = fingerprint('E', "BSpline", 20, Base::Vector3d(0, 0, 5));
    input.entries = {entry};
    auto circle = fingerprint('E', "Circle", 6, Base::Vector3d(0, 0, 0), Base::Vector3d(0, 0, 1),
                              {1});
    measure(input, {{"Edge4", circle}}, nullptr);

    //   without the check: resolved at tier 1 (the wrong verdict)
    input.check = Data::Tier1Check::None;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Resolved);
    //   with it, broken, with the survivor as the candidate
    for (auto check : {Data::Tier1Check::Kind, Data::Tier1Check::Intrinsic}) {
        input.check = check;
        EXPECT_EQ(describe(Data::solveOwner(input)[0]),
                  "broken  -1 [Edge4 ] tier 2 disagrees with Edge4")
            << static_cast<int>(check);
    }
    //   a survivor of the saved kind resolves under Kind; under Intrinsic its direction and
    //   radii must agree too
    auto bspline = fingerprint('E', "BSpline", 18, Base::Vector3d(1, 0, 5));
    measure(input, {{"Edge4", bspline}}, nullptr);
    for (auto check : {Data::Tier1Check::Kind, Data::Tier1Check::Intrinsic}) {
        input.check = check;
        EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Resolved)
            << static_cast<int>(check);
    }
    auto tilted = fingerprint('E', "Line", 20, Base::Vector3d(0, 0, 5), Base::Vector3d(0, 0, 1));
    entry.fingerprint = tilted;
    input.entries = {entry};
    auto line = fingerprint('E', "Line", 20, Base::Vector3d(0, 0, 5), Base::Vector3d(0, 1, 0));
    measure(input, {{"Edge4", line}}, nullptr);
    input.check = Data::Tier1Check::Kind;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Resolved);
    input.check = Data::Tier1Check::Intrinsic;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    //   without a saved fingerprint there is nothing to check: resolved
    input.entries[0].fingerprint = ElementFingerprint();
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Resolved);
}

// ---------------------------------------------------------------------------------------------
// Moved exact elements (ops#105): another element sits where the named one was

namespace
{

// A boss's top circle edge of radius \a r, centred at (x, y, 10), as a version-2 fingerprint.
ElementFingerprint circleAt(double x, double y, double r = 3.0)
{
    auto fp = fingerprint('E',
                          "Circle",
                          2 * Pi * r,
                          Base::Vector3d(x, y, 10),
                          Base::Vector3d(0, 0, 1),
                          {r});
    fp.location = Base::Vector3d(x, y, 10);
    return fp;
}

// Two bosses' top edges on a 30 x 30 plate, Edge1 at (10, 15) and Edge2 at (20, 15) when the
// references were saved; Edge3 is a plate edge. `now` sets where they are.
struct Bosses
{
    const double diagonal = std::sqrt(30.0 * 30 + 30 * 30 + 10 * 10);
    std::map<std::string, ElementFingerprint> now {
        {"Edge1", circleAt(10, 15)},
        {"Edge2", circleAt(20, 15)},
        {"Edge3", lineX(0, 30)},
    };

    SolveInput input(std::vector<SolveInput::Entry> entries, int* calls = nullptr) const
    {
        SolveInput input;
        input.diagonal = diagonal;
        input.pool["Edge"] = {
            element("Edge1", {"a"}),
            element("Edge2", {"b"}),
            element("Edge3", {"p"}),
        };
        input.entries = std::move(entries);
        measure(input, now, calls);
        return input;
    }

    // The exact reference to the edge \a index named \a name, saved at (x, 15).
    static SolveInput::Entry boss(const std::string& index, const std::string& name, double x)
    {
        auto entry = exact(index, "Edge");
        entry.exactName = name;
        entry.fingerprint = circleAt(x, 15);
        return entry;
    }
};

}  // namespace

TEST(Moved, atSamePlace)
{
    GeometryTolerances tolerances;
    const double diagonal = 43.6;
    const double eps = 1e-7 * diagonal;
    auto here = [&](const ElementFingerprint& saved, const ElementFingerprint& now) {
        return Data::atSamePlace(saved, now, diagonal, tolerances, 1e-7);
    };
    const auto saved = circleAt(10, 15);

    EXPECT_TRUE(here(saved, saved));
    //   the size within 1e-6 relative, not 1e-5
    auto size = saved;
    *size.size *= 1 + 0.9e-6;
    EXPECT_TRUE(here(saved, size));
    *size.size = *saved.size * (1 + 1e-5);
    EXPECT_FALSE(here(saved, size));
    //   the centre within eps, not 2 eps
    auto centre = saved;
    centre.center = *saved.center + Base::Vector3d(0.5 * eps, 0, 0);
    EXPECT_TRUE(here(saved, centre));
    centre.center = *saved.center + Base::Vector3d(2 * eps, 0, 0);
    EXPECT_FALSE(here(saved, centre));
    //   a circle's centre (version 2) apart, its centre of mass not
    auto location = saved;
    location.location = *saved.location + Base::Vector3d(0, 2 * eps, 0);
    EXPECT_FALSE(here(saved, location));
    //   another radius, kind or type
    EXPECT_FALSE(here(saved, circleAt(10, 15, 3.001)));
    auto line = saved;
    line.kind = "Line";
    line.radii.clear();
    EXPECT_FALSE(here(saved, line));
    //   a size on one side only
    auto noSize = saved;
    noSize.size.reset();
    EXPECT_FALSE(here(saved, noSize));
    EXPECT_FALSE(here(noSize, saved));
    //   invalid
    EXPECT_FALSE(here(saved, ElementFingerprint()));
    EXPECT_FALSE(here(ElementFingerprint(), saved));

    // A plane keeps the sense of its normal, and its extent counts when both have one.
    auto top = fingerprint('F', "Plane", 200, Base::Vector3d(10, 5, 10), Base::Vector3d(0, 0, 1));
    top.extentMin = Base::Vector3d(0, 0, 10);
    top.extentMax = Base::Vector3d(20, 10, 10);
    EXPECT_TRUE(here(top, top));
    auto flipped = top;
    flipped.direction = Base::Vector3d(0, 0, -1);
    EXPECT_FALSE(here(top, flipped));
    auto wider = top;
    wider.extentMax = Base::Vector3d(20, 10 + 2 * eps, 10);
    EXPECT_FALSE(here(top, wider));
    auto noExtent = top;
    noExtent.extentMin.reset();
    noExtent.extentMax.reset();
    EXPECT_TRUE(here(top, noExtent));
    // A vertex: the point.
    auto vertex = fingerprint('V', "Point", {}, Base::Vector3d(1, 2, 3));
    EXPECT_TRUE(here(vertex, vertex));
    auto movedVertex = vertex;
    movedVertex.center = Base::Vector3d(1, 2, 3 + 2 * eps);
    EXPECT_FALSE(here(vertex, movedVertex));
}

TEST(Moved, movedAloneKeepsItsName)
{
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(10, 25);
    auto outcomes = Data::solveOwner(bosses.input({Bosses::boss("Edge1", "a", 10)}));
    EXPECT_EQ(describe(outcomes[0]), "exact Edge1 0 [] ");
}

TEST(Moved, anotherElementAtTheOldPlaceBreaks)
{
    // Boss a moved to (20, 25), boss b to (10, 15), a's old place.
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(20, 25);
    bosses.now["Edge2"] = circleAt(10, 15);
    auto outcome = Data::solveOwner(bosses.input({Bosses::boss("Edge1", "a", 10)}))[0];

    EXPECT_EQ(describe(outcome),
              "broken  -1 [Edge2 Edge1 ] moved 14.142 mm; Edge2 sits where it was");
    EXPECT_EQ(outcome.candidateNames, (std::vector<std::string> {"b", "a"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "name"}));
    ASSERT_EQ(outcome.candidateDistances.size(), 2U);
    EXPECT_NEAR(outcome.candidateDistances[0], 0.0, 1e-12);
    EXPECT_NEAR(outcome.candidateDistances[1], std::sqrt(200.0), 1e-9);
}

TEST(Moved, tradingPlacesBreaksBoth)
{
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(20, 15);
    bosses.now["Edge2"] = circleAt(10, 15);
    auto outcomes = Data::solveOwner(
        bosses.input({Bosses::boss("Edge1", "a", 10), Bosses::boss("Edge2", "b", 20)})
    );

    EXPECT_EQ(describe(outcomes[0]),
              "broken  -1 [Edge2 Edge1 ] moved 10.000 mm; Edge2 sits where it was");
    EXPECT_EQ(describe(outcomes[1]),
              "broken  -1 [Edge1 Edge2 ] moved 10.000 mm; Edge1 sits where it was");

    // Traded back: both sit where they were, exact.
    Bosses back;
    outcomes = Data::solveOwner(
        back.input({Bosses::boss("Edge1", "a", 10), Bosses::boss("Edge2", "b", 20)})
    );
    EXPECT_EQ(describe(outcomes[0]), "exact Edge1 0 [] ");
    EXPECT_EQ(describe(outcomes[1]), "exact Edge2 0 [] ");
}

TEST(Moved, symmetricMoveKeepsBoth)
{
    // (10, 15), (20, 15) -> (15, 10), (15, 20): nothing sits at either old place (Q1).
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(15, 10);
    bosses.now["Edge2"] = circleAt(15, 20);
    auto outcomes = Data::solveOwner(
        bosses.input({Bosses::boss("Edge1", "a", 10), Bosses::boss("Edge2", "b", 20)})
    );
    EXPECT_EQ(describe(outcomes[0]), "exact Edge1 0 [] ");
    EXPECT_EQ(describe(outcomes[1]), "exact Edge2 0 [] ");
}

TEST(Moved, severalElementsAtTheOldPlace)
{
    // Overlapping instances: two edges where a's was, listed in index order before a's.
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(20, 25);
    bosses.now["Edge2"] = circleAt(10, 15);
    bosses.now["Edge4"] = circleAt(10, 15);
    auto input = bosses.input({Bosses::boss("Edge1", "a", 10)});
    input.pool["Edge"].push_back(element("Edge4", {"c"}));
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(describe(outcome),
              "broken  -1 [Edge2 Edge4 Edge1 ] moved 14.142 mm; Edge2, Edge4 sit where it was");
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "place", "name"}));
}

TEST(Moved, changedInPlaceIsNotMoved)
{
    // The same centre, a larger radius, and another circle at the old place: "changed".
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(10, 15, 4);
    bosses.now["Edge2"] = circleAt(10, 15);
    auto outcome = Data::solveOwner(bosses.input({Bosses::boss("Edge1", "a", 10)}))[0];
    EXPECT_EQ(describe(outcome), "broken  -1 [Edge2 Edge1 ] changed; Edge2 sits where it was");
}

TEST(Moved, shortenedHitStillContinues)
{
    // Nothing equals the whole old edge: the continuation decides, as before.
    Notch notch;
    auto outcome = Data::solveOwner(notch.input(Data::SolvePolicy::One))[0];
    EXPECT_EQ(outcome.evidence, "split: the old edge continues in Edge2");
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"name", "piece"}));
}

TEST(Moved, nothingToCompare)
{
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(20, 25);
    bosses.now["Edge2"] = circleAt(10, 15);
    // No saved fingerprint: no check, nothing measured.
    int calls = 0;
    auto entry = Bosses::boss("Edge1", "a", 10);
    entry.fingerprint = ElementFingerprint();
    EXPECT_EQ(describe(Data::solveOwner(bosses.input({entry}, &calls))[0]), "exact Edge1 0 [] ");
    EXPECT_EQ(calls, 0);
    // Unmoved: only the hit is measured.
    Bosses still;
    calls = 0;
    auto outcome = Data::solveOwner(still.input({Bosses::boss("Edge1", "a", 10)}, &calls))[0];
    EXPECT_EQ(describe(outcome), "exact Edge1 0 [] ");
    EXPECT_EQ(calls, 1);
    // A hit that can't be measured stands.
    bosses.now.erase("Edge1");
    outcome = Data::solveOwner(bosses.input({Bosses::boss("Edge1", "a", 10)}))[0];
    EXPECT_EQ(describe(outcome), "exact Edge1 0 [] ");
}

TEST(Moved, equivalentKeepsTheHitWhenTheProbeAgrees)
{
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(20, 15);
    bosses.now["Edge2"] = circleAt(10, 15);
    auto entry = Bosses::boss("Edge1", "a", 10);
    entry.policy = Data::SolvePolicy::Equivalent;
    entry.equivalent = [](const std::string&, const std::string&) { return true; };
    EXPECT_EQ(describe(Data::solveOwner(bosses.input({entry}))[0]), "exact Edge1 0 [] ");

    entry.equivalent = [](const std::string&, const std::string&) { return false; };
    EXPECT_EQ(Data::solveOwner(bosses.input({entry}))[0].status, SolveStatus::Broken);
    //   no probe is no equivalence
    entry.equivalent = {};
    EXPECT_EQ(Data::solveOwner(bosses.input({entry}))[0].status, SolveStatus::Broken);
    //   Expand breaks as One does
    entry.policy = Data::SolvePolicy::Expand;
    EXPECT_EQ(Data::solveOwner(bosses.input({entry}))[0].status, SolveStatus::Broken);
}

TEST(Moved, ambiguousElementsLeaveTheOtherPools)
{
    // A missing reference saved where Edge2 now is would take it by geometry (tiers 2 and 3)...
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(20, 25);
    bosses.now["Edge2"] = circleAt(10, 15);
    auto gone = missing("gone", "Edge");
    gone.fingerprint = circleAt(10, 15);
    EXPECT_EQ(Data::solveOwner(bosses.input({gone}))[0].element, "Edge2");
    // ... but not while a moved exact reference of the owner has it at its old place.
    auto outcomes = Data::solveOwner(bosses.input({Bosses::boss("Edge1", "a", 10), gone}));
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[1].evidence, "no candidate");
}

TEST(Moved, patternSiblingAtTheOldPlaceBreaks)
{
    // Q3 (a), the uniform rule: a pitch change puts instance 4's copy of the edge where
    // instance 3's was. The names are siblings, and the reference still breaks.
    const std::string base = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    SolveInput input;
    input.diagonal = 60;
    input.pool["Edge"] = {
        element("Edge1", {stepInstance(base, 8, "3", 'E')}),
        element("Edge2", {stepInstance(base, 8, "4", 'E')}),
    };
    auto entry = exact("Edge1", "Edge");
    entry.exactName = stepInstance(base, 8, "3", 'E');
    entry.fingerprint = circleAt(26, 0);
    input.entries = {entry};
    measure(input, {{"Edge1", circleAt(20, 0)}, {"Edge2", circleAt(26, 0)}}, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(describe(outcome),
              "broken  -1 [Edge2 Edge1 ] moved 6.000 mm; Edge2 sits where it was");
}

namespace
{

// ops#168's seed 267: a boss (tag 7) padded from sketch line g2 (sketch 5) on a block; a
// chamfer names its top right edge, Edge33, the line's `XTR;PRJ` copy at z = 15. The block is
// raised by the boss's height, 2.5: Edge33 is at z = 17.5, and the boss's bottom edge Edge22,
// the sketch line verbatim, sits where Edge33 was. \a atOldPlace names Edge22.
SolveInput liftedBoss(const std::string& atOldPlace)
{
    const auto top = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    SolveInput input;
    input.diagonal = 40;
    input.pool["Edge"] = {
        element("Edge22", {atOldPlace}),
        element("Edge33", {top}),
        element("Edge40", {sketchEdge(4)}),
    };
    auto entry = exact("Edge33", "Edge");
    entry.exactName = top;
    entry.fingerprint = lineX(10, 18, 3.25, 15);
    input.entries = {entry};
    measure(input,
            {{"Edge22", lineX(10, 18, 3.25, 15)},
             {"Edge33", lineX(10, 18, 3.25, 17.5)},
             {"Edge40", lineX(10, 18, 9.25, 15)}},
            nullptr);
    return input;
}

}  // namespace

TEST(Moved, liftedOntoItsOwnTwinKeepsItsName)
{
    // The element at the old place is the hit's own other copy of line g2: the name stands.
    auto outcome = Data::solveOwner(liftedBoss(sketchEdge(2)))[0];
    EXPECT_EQ(describe(outcome),
              "exact Edge33 0 [] moved 2.500 mm; its own twin Edge22 sits where it was");
    EXPECT_TRUE(outcome.candidates.empty());
}

TEST(Moved, anotherLineOfTheSketchAtTheOldPlaceBreaks)
{
    // Line g3 of the same sketch there (a profile shifted by its width): the rule as before.
    auto outcome = Data::solveOwner(liftedBoss(sketchEdge(3)))[0];
    EXPECT_EQ(describe(outcome),
              "broken  -1 [Edge22 Edge33 ] moved 2.500 mm; Edge22 sits where it was");
}

TEST(Moved, ownTwinAndAnotherAtTheOldPlaceBreaks)
{
    // Every element there must be an own twin: with another line there too, it breaks.
    auto input = liftedBoss(sketchEdge(2));
    input.pool["Edge"].push_back(element("Edge50", {sketchEdge(3, 6)}));
    auto fingerprints = std::map<std::string, ElementFingerprint> {
        {"Edge22", lineX(10, 18, 3.25, 15)},
        {"Edge33", lineX(10, 18, 3.25, 17.5)},
        {"Edge40", lineX(10, 18, 9.25, 15)},
        {"Edge50", lineX(10, 18, 3.25, 15)},
    };
    measure(input, fingerprints, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(describe(outcome),
              "broken  -1 [Edge22 Edge50 Edge33 ] moved 2.500 mm; Edge22, Edge50 sit where it was");
}

TEST(Moved, ownTwinOfAnotherInstanceBreaks)
{
    // The same source in another pattern instance is a pattern sibling, not an own twin.
    const auto top = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    auto input = liftedBoss(stepInstance(sketchEdge(2), 8, "2", 'E'));
    input.pool["Edge"][1] = element("Edge33", {stepInstance(top, 8, "1", 'E')});
    input.entries[0].exactName = stepInstance(top, 8, "1", 'E');
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(describe(outcome),
              "broken  -1 [Edge22 Edge33 ] moved 2.500 mm; Edge22 sits where it was");
    //   in the same instance, it is the own twin
    input.pool["Edge"][0] = element("Edge22", {stepInstance(sketchEdge(2), 8, "1", 'E')});
    EXPECT_EQ(describe(Data::solveOwner(input)[0]),
              "exact Edge33 0 [] moved 2.500 mm; its own twin Edge22 sits where it was");
}

TEST(Moved, laterFeaturesEdgeOfAMirroredCopyIsNoTwin)
{
    // The PR 143 review's finding 1 (MirroredBossesTradePlaces): a pocket (tag 9) slices the
    // top off a boss and its Mirrored copy (tag 8, instance 2), and its edges carry the copy only
    // inside the linked face. The copy's edge at the boss's old place is no own twin of the
    // boss's, so the reference breaks, as two copies trading places do.
    const auto side = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'F', {"GEN"});
    const auto floor = section({}, {sketchEdge(4, 6)}, 9, "XTR", 0, 'F', {"PRJ"});
    auto sliced = [&](const std::string& face) {
        return generated({floor, face}, 9, "CUT", 'E');
    };
    auto input = liftedBoss(sliced(stepInstance(side, 8, "2", 'F')));
    input.pool["Edge"][1] = element("Edge33", {sliced(side)});
    input.entries[0].exactName = sliced(side);
    EXPECT_EQ(describe(Data::solveOwner(input)[0]),
              "broken  -1 [Edge22 Edge33 ] moved 2.500 mm; Edge22 sits where it was");
    //   two instances of a pattern, the same
    input.pool["Edge"][1] = element("Edge33", {sliced(stepInstance(side, 8, "3", 'F'))});
    input.entries[0].exactName = sliced(stepInstance(side, 8, "3", 'F'));
    EXPECT_EQ(describe(Data::solveOwner(input)[0]),
              "broken  -1 [Edge22 Edge33 ] moved 2.500 mm; Edge22 sits where it was");
    //   the hit's own copy in the same instance is its twin
    const auto bottom = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'F', {"PRJ"});
    input.pool["Edge"][0] = element("Edge22", {sliced(stepInstance(bottom, 8, "3", 'F'))});
    EXPECT_EQ(describe(Data::solveOwner(input)[0]),
              "exact Edge33 0 [] moved 2.500 mm; its own twin Edge22 sits where it was");
}

TEST(Moved, twoPiecesOfOneEdgeAreNoTwins)
{
    // The PR 143 review's finding 2 (EdgePiecesTradePlaces): a notch (tag 9) splits the boss's
    // top edge into two equal pieces, told apart by their neighbours; a move puts one where the
    // other was. They share every source, but two pieces of one edge are no twins: it breaks.
    const auto top = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto held = piece(top, 9, "CUT", 0, 'E', {"Face3"});
    auto input = liftedBoss(piece(top, 9, "CUT", 0, 'E', {"Face5"}));
    input.pool["Edge"][1] = element("Edge33", {held});
    input.entries[0].exactName = held;
    EXPECT_EQ(describe(Data::solveOwner(input)[0]),
              "broken  -1 [Edge22 Edge33 ] moved 2.500 mm; Edge22 sits where it was");
}

TEST(Moved, twoPiecesOfOneEdgeInACopyAreNoTwins)
{
    // The PR 143 verification's finding A: the split made before a pattern instance (8, instance
    // 2) copies both pieces, `X|<split>|<TRF;2>`. Compared without the copy chain they share,
    // they are two pieces of one edge, no twins: it breaks.
    const auto top = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto held = stepInstance(piece(top, 9, "CUT", 0, 'E', {"Face3"}), 8, "2", 'E');
    auto input = liftedBoss(stepInstance(piece(top, 9, "CUT", 0, 'E', {"Face5"}), 8, "2", 'E'));
    input.pool["Edge"][1] = element("Edge33", {held});
    input.entries[0].exactName = held;
    EXPECT_EQ(describe(Data::solveOwner(input)[0]),
              "broken  -1 [Edge22 Edge33 ] moved 2.500 mm; Edge22 sits where it was");
}

TEST(Moved, onlyTheHeldNameOfTheHitMakesATwin)
{
    // The PR 143 review's finding 3: the hit also has a name made from line g3, the element at
    // the old place's source. The reference holds the g2 name, so that one decides: no twin.
    auto input = liftedBoss(sketchEdge(3));
    const auto top = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    input.pool["Edge"][1] =
        element("Edge33", {top, section({}, {sketchEdge(3, 6)}, 7, "XTR", 0, 'E', {"PRJ"})});
    input.pool["Edge"][0] = element("Edge22", {sketchEdge(3, 6)});
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(describe(outcome),
              "broken  -1 [Edge22 Edge33 ] moved 2.500 mm; Edge22 sits where it was");
}

TEST(Moved, independentOfInputOrder)
{
    // Two traded bosses, a third moved alone, a missing reference and a plate edge, shuffled.
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(20, 15);
    bosses.now["Edge2"] = circleAt(10, 15);
    bosses.now["Edge4"] = circleAt(5, 5);
    bosses.now["Edge5"] = circleAt(25, 25);
    auto c = Bosses::boss("Edge4", "c", 0);
    c.fingerprint = circleAt(5, 25);
    auto gone = missing("gone", "Edge");
    gone.fingerprint = circleAt(25, 25);
    gone.position = 3;
    auto input = bosses.input(
        {Bosses::boss("Edge1", "a", 10), Bosses::boss("Edge2", "b", 20), c, gone}
    );
    input.pool["Edge"].push_back(element("Edge4", {"c"}));
    input.pool["Edge"].push_back(element("Edge5", {"d", "d2"}));

    const auto expected = Data::solveOwner(input);
    std::vector<std::string> expectedText;
    for (const auto& outcome : expected) {
        expectedText.push_back(describe(outcome));
    }
    EXPECT_EQ(expected[0].status, SolveStatus::Broken);
    EXPECT_EQ(expected[1].status, SolveStatus::Broken);
    EXPECT_EQ(expectedText[2], "exact Edge4 0 [] ");
    EXPECT_EQ(expected[3].element, "Edge5");

    std::mt19937 random(105);
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
            for (auto& element : pool) {
                std::shuffle(element.names.begin(), element.names.end(), random);
            }
        }
        auto outcomes = Data::solveOwner(shuffled);
        for (std::size_t i = 0; i < order.size(); ++i) {
            EXPECT_EQ(describe(outcomes[i]), expectedText[order[i]])
                << "round " << round << ", entry " << order[i];
            EXPECT_EQ(outcomes[i].candidateRoles, expected[order[i]].candidateRoles);
        }
    }
}

TEST(Moved, equivalentKeepReservesNothing)
{
    // The review's finding 1: an attachment keeps its moved hit (the probe agrees), so the
    // element at its old place stays open to the owner's other references: a missing one saved
    // there resolves to it.
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(20, 15);
    bosses.now["Edge2"] = circleAt(10, 15);
    auto kept = Bosses::boss("Edge1", "a", 10);
    kept.policy = Data::SolvePolicy::Equivalent;
    kept.equivalent = [](const std::string&, const std::string&) { return true; };
    auto gone = missing("gone", "Edge");
    gone.policy = Data::SolvePolicy::Equivalent;
    gone.equivalent = kept.equivalent;
    gone.fingerprint = circleAt(10, 15);
    auto outcomes = Data::solveOwner(bosses.input({kept, gone}));
    EXPECT_EQ(describe(outcomes[0]), "exact Edge1 0 [] ");
    EXPECT_EQ(outcomes[1].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[1].element, "Edge2");
}

TEST(Moved, decidedMemberStopsTheCollapse)
{
    // A group expanded from `whole` (Edge1's name): one member exact on Edge1, one missing piece
    // of it, which would merge back. Edge1 moved and Edge2 sits at the place the exact member
    // saved: that member breaks, and the group doesn't collapse over it.
    const std::string whole = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    Bosses bosses;
    bosses.now["Edge1"] = circleAt(20, 15);
    bosses.now["Edge2"] = circleAt(10, 15);
    auto exactMember = Bosses::boss("Edge1", whole, 10);
    auto pieceMember = missing(piece(whole, 9, "CUT", 0, 'E'), "Edge");
    auto input = bosses.input(
        {member(exactMember, whole, "s", 0), member(pieceMember, whole, "s", 1)}
    );
    input.pool["Edge"][0].names = {whole};
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidateRoles, (std::vector<std::string> {"place", "name"}));
    EXPECT_FALSE(outcomes[0].collapsed);
    EXPECT_NE(outcomes[1].status, SolveStatus::Removed);
    EXPECT_FALSE(outcomes[1].collapsed);

    // Unmoved, the same group collapses onto Edge1.
    Bosses still;
    input = still.input({member(exactMember, whole, "s", 0), member(pieceMember, whole, "s", 1)});
    input.pool["Edge"][0].names = {whole};
    outcomes = Data::solveOwner(input);
    EXPECT_TRUE(outcomes[0].collapsed);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Removed);
}

TEST(Moved, faceUnderOneBreaks)
{
    // Square bosses' top faces (6 x 6 at z = 10), a at (10, 15) and b at (20, 15), trade places.
    auto top = [](double x) {
        auto fp = fingerprint('F', "Plane", 36, Base::Vector3d(x, 15, 10), Base::Vector3d(0, 0, 1));
        fp.extentMin = Base::Vector3d(x - 3, 12, 10);
        fp.extentMax = Base::Vector3d(x + 3, 18, 10);
        return fp;
    };
    SolveInput input;
    input.diagonal = std::sqrt(30.0 * 30 + 30 * 30 + 10 * 10);
    input.pool["Face"] = {element("Face1", {"a"}), element("Face2", {"b"})};
    auto entry = exact("Face1", "Face");
    entry.exactName = "a";
    entry.fingerprint = top(10);
    input.entries = {entry};
    measure(input, {{"Face1", top(20)}, {"Face2", top(10)}}, nullptr);
    EXPECT_EQ(describe(Data::solveOwner(input)[0]),
              "broken  -1 [Face2 Face1 ] moved 10.000 mm; Face2 sits where it was");
    // Untraded: exact.
    measure(input, {{"Face1", top(10)}, {"Face2", top(20)}}, nullptr);
    EXPECT_EQ(describe(Data::solveOwner(input)[0]), "exact Face1 0 [] ");
}

namespace
{

// An element's hint, as Part gives it: its fingerprint without size, centre and extent, and a
// point of its plane, line or vertex away from its centre.
struct Hinted
{
    ElementFingerprint intrinsic;
    std::optional<Base::Vector3d> anchor;
};

Hinted hintOf(const ElementFingerprint& fp)
{
    Hinted hint;
    hint.intrinsic = fp;
    hint.intrinsic.size.reset();
    hint.intrinsic.center.reset();
    hint.intrinsic.extentMin.reset();
    hint.intrinsic.extentMax.reset();
    if (fp.type == 'V') {
        hint.anchor = fp.center;
    }
    else if (fp.direction && fp.kind == "Line") {
        hint.anchor = *fp.center + *fp.direction * 7.0;
    }
    else if (fp.direction && fp.kind == "Plane") {
        // a point of the plane: the centre moved along a direction in it
        Base::Vector3d inPlane = *fp.direction % Base::Vector3d(0.3, 0.5, 0.7);
        hint.anchor = *fp.center + inPlane * 5.0;
    }
    return hint;
}

}  // namespace

TEST(Moved, hintRulesOutOnlyWhatIsNotThere)
{
    GeometryTolerances tolerances;
    const double diagonal = 43.6;
    const double eps = 1e-7 * diagonal;
    auto top = fingerprint('F', "Plane", 36, Base::Vector3d(10, 15, 10), Base::Vector3d(0, 0, 1));
    auto side = fingerprint('F', "Plane", 30, Base::Vector3d(13, 15, 7.5), Base::Vector3d(1, 0, 0));
    auto vertex = fingerprint('V', "Point", {}, Base::Vector3d(13, 12, 10));
    auto shifted = [](ElementFingerprint fp, Base::Vector3d by) {
        if (fp.center) {
            fp.center = *fp.center + by;
        }
        if (fp.location) {
            fp.location = *fp.location + by;
        }
        return fp;
    };
    const std::vector<ElementFingerprint> saved {
        circleAt(10, 15), lineX(0, 20), lineX(0, 20, 10, 0), top, side, vertex,
    };
    std::vector<ElementFingerprint> elements = saved;
    for (const auto& fp : saved) {
        for (Base::Vector3d by : {Base::Vector3d(0.5 * eps, 0, 0),
                                  Base::Vector3d(0, 0, 0.5 * eps),
                                  Base::Vector3d(2 * eps, 0, 0),
                                  Base::Vector3d(0, 0, 3 * eps),
                                  Base::Vector3d(10, 0, 0),
                                  Base::Vector3d(0, 0, 1)}) {
            elements.push_back(shifted(fp, by));
        }
    }
    int ruledOut = 0;
    for (const auto& s : saved) {
        for (const auto& element : elements) {
            const Hinted hint = hintOf(element);
            const bool maybe = Data::mayBeAtPlace(s, hint.intrinsic, hint.anchor, diagonal,
                                                  tolerances, 1e-7);
            // Never ruled out when it is there.
            if (Data::atSamePlace(s, element, diagonal, tolerances, 1e-7)) {
                EXPECT_TRUE(maybe);
            }
            ruledOut += maybe ? 0 : 1;
        }
    }
    EXPECT_GT(ruledOut, 0);

    // What the hint rules out: another kind, a parallel plane or line, another circle centre,
    // a vertex elsewhere.
    auto may = [&](const ElementFingerprint& s, const ElementFingerprint& element) {
        const Hinted hint = hintOf(element);
        return Data::mayBeAtPlace(s, hint.intrinsic, hint.anchor, diagonal, tolerances, 1e-7);
    };
    EXPECT_FALSE(may(circleAt(10, 15), lineX(0, 20)));
    EXPECT_FALSE(may(top, shifted(top, Base::Vector3d(0, 0, 1))));
    EXPECT_FALSE(may(lineX(0, 20), lineX(0, 20, 1)));
    EXPECT_FALSE(may(circleAt(10, 15), circleAt(20, 15)));
    EXPECT_FALSE(may(vertex, shifted(vertex, Base::Vector3d(1, 0, 0))));
    //   in the same plane or on the same line elsewhere: only the fingerprint tells
    EXPECT_TRUE(may(top, shifted(top, Base::Vector3d(10, 0, 0))));
    EXPECT_TRUE(may(lineX(0, 20), lineX(30, 50)));
    //   no anchor: the intrinsic part alone
    Hinted bare = hintOf(top);
    bare.anchor.reset();
    EXPECT_TRUE(Data::mayBeAtPlace(top, bare.intrinsic, bare.anchor, diagonal, tolerances, 1e-7));
}

TEST(Moved, hintsSaveMeasurements)
{
    // The traded bosses with a plate edge: the hint rules out the line edge, so only the hit and
    // the circle at its place are measured; the outcome is the same.
    for (bool hinted : {false, true}) {
        Bosses bosses;
        bosses.now["Edge1"] = circleAt(20, 15);
        bosses.now["Edge2"] = circleAt(10, 15);
        int calls = 0;
        auto input = bosses.input({Bosses::boss("Edge1", "a", 10)}, &calls);
        int hints = 0;
        if (hinted) {
            input.hintOf = [now = bosses.now, &hints](const std::string& index,
                                                      ElementFingerprint& intrinsic,
                                                      std::optional<Base::Vector3d>& anchor) {
                ++hints;
                auto it = now.find(index);
                if (it == now.end()) {
                    return false;
                }
                Hinted hint = hintOf(it->second);
                intrinsic = hint.intrinsic;
                anchor = hint.anchor;
                return true;
            };
        }
        auto outcome = Data::solveOwner(input)[0];
        EXPECT_EQ(describe(outcome),
                  "broken  -1 [Edge2 Edge1 ] moved 10.000 mm; Edge2 sits where it was")
            << hinted;
        EXPECT_EQ(calls, hinted ? 2 : 3) << hinted;
        EXPECT_EQ(hints, hinted ? 2 : 0) << hinted;
    }
}

namespace
{

// PR 340 round 3: a piece of the far cap of the Pad (tag 7) from profile face A (sketch 5's
// lines 1-8), up to a plate: A's start cap's projection, `<start cap>;7;XTR;0;F;<counter>;
// <flags>;<marks>`.
std::string farPiece(
    const std::vector<std::string>& marks,
    int counter = 0,
    const std::vector<std::string>& flags = {"PRJ", "MOD"}
)
{
    std::vector<std::string> edges;
    for (int geoId = 1; geoId <= 8; ++geoId) {
        edges.push_back(sketchEdge(geoId));
    }
    return Data::MappedName::makeEncodedSection(
        {},
        {lowFace(edges)},
        "7",
        "XTR",
        "0",
        'F',
        std::to_string(counter),
        flags,
        marks
    );
}

// An element of the up-to plate (Part feature, tag 3), as a mark.
std::string plateElement(const char* id, char elementType)
{
    return section({id}, {}, 3, "SRC", 0, elementType, {"SRC"});
}

// A far cap's piece at (x, y) on the plate at z = 10.
ElementFingerprint capAt(double x, double y)
{
    return fingerprint('F', "Plane", 5, Base::Vector3d(x, y, 10), Base::Vector3d(0, 0, 1));
}

// A far cap's piece from (x0, y0) to (x1, y1) on the plate at z = 10, with its box.
ElementFingerprint capBox(double x0, double x1, double y0, double y1)
{
    ElementFingerprint fp = fingerprint(
        'F',
        "Plane",
        (x1 - x0) * (y1 - y0),
        Base::Vector3d((x0 + x1) / 2, (y0 + y1) / 2, 10),
        Base::Vector3d(0, 0, 1)
    );
    fp.extentMin = Base::Vector3d(x0, y0, 10);
    fp.extentMax = Base::Vector3d(x1, y1, 10);
    return fp;
}

// A disc's pieces either side of an elliptic hole, both bounded by the plate, the ellipse and the
// circle alone: told apart only by their order (the duplicate counter), with the ORD flag, or
// without it in \a flags. Face1 holds counter \a bottom and sits at (3.1, 0.6), Face2 the other
// at (3.1, 5.6); the reference was saved on counter 2, the top piece, at (3, 5.5).
SolveInput twinPieces(int bottom, const std::vector<std::string>& flags = {"PRJ", "MOD", "ORD"})
{
    const std::vector<std::string> marks {
        plateElement("plate", 'F'),
        plateElement("ellipse", 'E'),
        plateElement("circle", 'E')
    };
    SolveInput input;
    input.diagonal = 40;
    input.pool["Face"] = {
        element("Face1", {farPiece(marks, bottom, flags)}),
        element("Face2", {farPiece(marks, 3 - bottom, flags)}),
        element("Face3", {farPiece({plateElement("fill", 'F')})}),
    };
    auto entry = exact(bottom == 2 ? "Face1" : "Face2");
    entry.exactName = farPiece(marks, 2, flags);
    entry.fingerprint = capAt(3, 5.5);
    input.entries = {entry};
    measure(
        input,
        {{"Face1", capAt(3.1, 0.6)}, {"Face2", capAt(3.1, 5.6)}, {"Face3", capAt(3, 3)}},
        nullptr
    );
    return input;
}

}  // namespace

TEST(Moved, twinsThatTradedNamesBreak)
{
    // An edit moved both twins a little and traded their order: the top's name holds the bottom
    // piece, and nothing sits at the old place. The top piece, the name's counter sibling, lies
    // nearer it than the hit: broken, the twin first (PR 340 round 3).
    auto outcome = Data::solveOwner(twinPieces(2))[0];
    EXPECT_EQ(
        describe(outcome),
        "broken  -1 [Face2 Face1 ] moved 4.901 mm; its twin Face2 sits nearer where it was"
    );
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "name"}));
}

TEST(Moved, twinsInTheirOrderKeepTheirNames)
{
    // Moved the same, in their order: the name holds the top piece, the nearer one.
    EXPECT_EQ(describe(Data::solveOwner(twinPieces(1))[0]), "exact Face2 0 [] ");
}

TEST(Moved, counterSiblingsWithoutTheOrderFlagMoveAlone)
{
    // Elements told apart by the duplicate counter without the ORD flag go by no twins' places:
    // moved with nothing at the old place, the name stands while it overlaps its old place. These
    // are marked pieces 4.9 mm off, past it (PR 366 round 3): broken, the hit its one candidate.
    EXPECT_EQ(
        describe(Data::solveOwner(twinPieces(2, {"PRJ", "MOD"}))[0]),
        "broken  -1 [Face1 ] moved 4.901 mm off where it was, and nothing sits there"
    );
}

namespace
{

// PR 340 round 4: twins of one far cap (the ORD flag), told apart by the duplicate counter
// `count (count - 1) / 2 + place`, each at its place now; the reference was saved on the twin
// with counter \a savedCounter at \a saved, and its name now holds the twin with that counter.
// Round 5: the saved fingerprint holds the twins' centroid then, \a savedCentroid, and their
// number, \a savedCount (0: an older record, without them).
SolveInput placedTwins(
    const std::vector<Base::Vector3d>& places,
    int savedCounter,
    const Base::Vector3d& saved,
    std::optional<Base::Vector3d> savedCentroid = std::nullopt,
    int savedCount = 0
)
{
    const std::vector<std::string> marks {
        plateElement("plate", 'F'),
        plateElement("hole", 'E'),
        plateElement("circle", 'E')
    };
    const int count = static_cast<int>(places.size());
    SolveInput input;
    input.diagonal = 40;
    std::map<std::string, ElementFingerprint> fingerprints;
    std::string hit;
    for (int place = 0; place < count; ++place) {
        const int counter = count * (count - 1) / 2 + place;
        const std::string index = "Face" + std::to_string(place + 1);
        input.pool["Face"].push_back(element(index, {farPiece(marks, counter, {"PRJ", "MOD", "ORD"})}));
        fingerprints[index] = capAt(places[place].x, places[place].y);
        if (counter == savedCounter) {
            hit = index;
        }
    }
    auto entry = exact(hit);
    entry.exactName = farPiece(marks, savedCounter, {"PRJ", "MOD", "ORD"});
    entry.fingerprint = capAt(saved.x, saved.y);
    entry.fingerprint.twinCentroid = savedCentroid;
    entry.fingerprint.twinCount = savedCount;
    input.entries = {entry};
    measure(input, fingerprints, nullptr);
    return input;
}

// The pair's centroid when the reference was saved: the top twin at (3, 5.5), the bottom one at
// (3, 0.5)
const Base::Vector3d pairCentroid(3, 3, 10);

}  // namespace

TEST(Moved, twinsMovedTogetherKeepTheirNames)
{
    // PR 340 round 4 (N2): the pair one above the other (spacing 5) moved up 3 mm together, in
    // their order. The bottom twin now lies nearer the top one's old place (2 mm) than the top
    // twin does (3 mm), which round 3 took for a trade. Round 5: the top twin's offset from the
    // pair's centroid is the saved one. The name stands.
    EXPECT_EQ(
        describe(
            Data::solveOwner(placedTwins(
                {Base::Vector3d(3, 3.5, 10), Base::Vector3d(3, 8.5, 10)},
                2,
                Base::Vector3d(3, 5.5, 10),
                pairCentroid,
                2
            ))[0]
        ),
        "exact Face2 0 [] "
    );
    // Round 5 (N6): moved up 4.5, 1.8 half-spacings, the bottom twin 0.5 from the old place,
    // which round 4's band took for a turn. The offsets are the same: the name stands.
    EXPECT_EQ(
        describe(
            Data::solveOwner(placedTwins(
                {Base::Vector3d(3, 5, 10), Base::Vector3d(3, 10, 10)},
                2,
                Base::Vector3d(3, 5.5, 10),
                pairCentroid,
                2
            ))[0]
        ),
        "exact Face2 0 [] "
    );
    // One twin grown a lot, the other where it was (the top one's centre 7 mm up): the bottom
    // twin is nearer, 5 mm, but the top twin's offset (0, 6) is nearer the saved one (0, 2.5)
    // than the bottom twin's (0, -6).
    EXPECT_EQ(
        describe(
            Data::solveOwner(placedTwins(
                {Base::Vector3d(3, 0.5, 10), Base::Vector3d(3, 12.5, 10)},
                2,
                Base::Vector3d(3, 5.5, 10),
                pairCentroid,
                2
            ))[0]
        ),
        "exact Face2 0 [] "
    );
}

TEST(Moved, twinsThatLeftTogetherBreak)
{
    // PR 366 round 5b: the pair one above the other (spacing 5) moved together, in their order,
    // each piece 2 x 2 with its outline (version 5), their area 10 % smaller. Their offsets from
    // the pair's centroid are the saved ones, so the twins' places keep the name. Moved 6 mm
    // sideways, no twin's outline shares an area with the old place, and the set changed shape:
    // it left together, as when a reordered shell's pieces slid onto the next plate, which cuts
    // them elsewhere. Broken, the hit its one candidate.
    auto squareAround = [](const Base::Vector3d& centre) {
        return std::vector<Base::Vector3d> {
            Base::Vector3d(centre.x - 1, centre.y - 1, 10),
            Base::Vector3d(centre.x + 1, centre.y - 1, 10),
            Base::Vector3d(centre.x + 1, centre.y + 1, 10),
            Base::Vector3d(centre.x - 1, centre.y + 1, 10)
        };
    };
    auto moved = [&](double dx, double dy, bool outlines, double scale = 0.9) {
        SolveInput input = placedTwins(
            {Base::Vector3d(3 + dx, 0.5 + dy, 10), Base::Vector3d(3 + dx, 5.5 + dy, 10)},
            2,
            Base::Vector3d(3, 5.5, 10),
            pairCentroid,
            2
        );
        if (outlines) {
            input.entries[0].fingerprint.outline = squareAround(Base::Vector3d(3, 5.5, 10));
        }
        auto measured = input.fingerprintOf;
        input.fingerprintOf = [measured, squareAround, outlines, scale](const std::string& index) {
            ElementFingerprint fp = measured(index);
            if (fp.size) {
                *fp.size *= scale;
            }
            if (outlines && fp.center) {
                fp.outline = squareAround(*fp.center);
            }
            return fp;
        };
        return Data::solveOwner(input)[0];
    };
    auto outcome = moved(6, 0, true);
    EXPECT_EQ(
        describe(outcome),
        "broken  -1 [Face2 ] moved 6.000 mm off where it was, and nothing sits there"
    );
    // Moved 6 mm in one piece, of one shape as before (a hole moved with its disc): the twins'
    // places decide, and the name stands
    EXPECT_EQ(describe(moved(6, 0, true, 1.0)), "exact Face2 0 [] ");
    // Moved 1 mm, the hit's outline still shares an area with the old one: the name stands
    EXPECT_EQ(describe(moved(1, 0, true)), "exact Face2 0 [] ");
    // Moved up 4 mm: the hit left, but the bottom twin overlaps the old place (y 3.5..5.5
    // against 4.5..6.5). Not the whole set: the twins' places decide, and the name stands
    EXPECT_EQ(describe(moved(0, 4, true)), "exact Face2 0 [] ");
    // A record without an outline: the twins' places alone, the name stands
    EXPECT_EQ(describe(moved(6, 0, false)), "exact Face2 0 [] ");
}

TEST(Moved, twinsTurnedOffTheirCentreBreak)
{
    // PR 340 round 4: the hole turned 60 degrees about a point off the twins' centre, so the
    // twins changed shape and their centroid moved a little. Round 5: the twin where the old
    // piece went has the offset (-2.15, 1.25), 2.49 from the saved one, (0, 2.5); the hit's lies
    // 4.32 from it. A trade: broken.
    auto outcome = Data::solveOwner(placedTwins(
        {Base::Vector3d(0.9, 4.4, 10), Base::Vector3d(5.2, 1.9, 10)},
        2,
        Base::Vector3d(3, 5.5, 10),
        pairCentroid,
        2
    ))[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face1", "Face2"}));
}

TEST(Moved, unequalTwinsTurnedBreak)
{
    // PR 340 round 5 (N5): the disc 1 mm off the hole's centre along the twins' axis, the hole
    // turned 60 degrees about its own centre: the twins (centres (3, 5.25) and (3, 1.55) then,
    // centroid (3, 3.4)) changed shape and traded names. Round 4's band wanted the sibling as far
    // from the twins' centroid now as the saved centre (1.80 against 1.38, 23 % apart) and let
    // the name stand on the other twin's piece. The offsets: the sibling's (-1.565, 0.89) lies
    // 1.84 from the saved (0, 1.85), the hit's (1.565, -0.89) 3.15. Broken, the twin first.
    auto outcome = Data::solveOwner(placedTwins(
        {Base::Vector3d(1.71, 4.79, 10), Base::Vector3d(4.84, 3.01, 10)},
        2,
        Base::Vector3d(3, 5.25, 10),
        Base::Vector3d(3, 3.4, 10),
        2
    ))[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face1", "Face2"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "name"}));
    // Turned 30 degrees, in their order: the hit's offset is the nearer, the name stands.
    EXPECT_EQ(
        describe(
            Data::solveOwner(placedTwins(
                {Base::Vector3d(3.6, 1.7, 10), Base::Vector3d(2.2, 4.95, 10)},
                2,
                Base::Vector3d(3, 5.25, 10),
                Base::Vector3d(3, 3.4, 10),
                2
            ))[0]
        ),
        "exact Face2 0 [] "
    );
}

TEST(Moved, twinsInAnOlderRecordCompareTheirCentres)
{
    // PR 340 round 5: a fingerprint saved without the twins' centroid (an older build), or with
    // another number of twins than the name has now, compares the centres themselves (round 3):
    // the pair moved up 3 mm together, the bottom twin nearer the old place than the top one,
    // breaks. Loud, never a pick.
    const std::vector<std::pair<std::optional<Base::Vector3d>, int>> records {
        {std::nullopt, 0},
        {pairCentroid, 3},
    };
    for (const auto& [centroid, count] : records) {
        auto outcome = Data::solveOwner(placedTwins(
            {Base::Vector3d(3, 3.5, 10), Base::Vector3d(3, 8.5, 10)},
            2,
            Base::Vector3d(3, 5.5, 10),
            centroid,
            count
        ))[0];
        EXPECT_EQ(outcome.status, SolveStatus::Broken) << count << describe(outcome);
        EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face1", "Face2"})) << count;
    }
    // Turned 60 degrees and traded, as in unequalTwinsTurnedBreak: broken too.
    auto outcome = Data::solveOwner(placedTwins(
        {Base::Vector3d(1.71, 4.79, 10), Base::Vector3d(4.84, 3.01, 10)},
        2,
        Base::Vector3d(3, 5.25, 10)
    ))[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    // In their order, turned a little: the name stands.
    EXPECT_EQ(
        describe(
            Data::solveOwner(placedTwins(
                {Base::Vector3d(3.2, 0.5, 10), Base::Vector3d(2.8, 5.5, 10)},
                2,
                Base::Vector3d(3, 5.5, 10)
            ))[0]
        ),
        "exact Face2 0 [] "
    );
}

TEST(Moved, tiedTwinsBreak)
{
    // PR 340 round 4 (N3): three twins at radius 2 about (3, 3), turned 60 degrees so that
    // they traded names: the reference saved on the twin at 300 degrees now names the piece at
    // 240, as far from the saved centre (2 mm) as the piece at 0, where the twin went (here a
    // hair farther, 0.1 um, which round 3's strict comparison let stand). A tie is a trade too:
    // broken, the twin first. The same with the twins' centroid in the saved fingerprint
    // (round 5) as without it.
    const double s = std::sqrt(3.0);
    for (int count : {3, 0}) {
        auto outcome = Data::solveOwner(placedTwins(
            {Base::Vector3d(2, 3 - s, 10), Base::Vector3d(2, 3 + s, 10), Base::Vector3d(5.0001, 3, 10)},
            3,
            Base::Vector3d(4, 3 - s, 10),
            count ? std::optional<Base::Vector3d>(Base::Vector3d(3, 3, 10)) : std::nullopt,
            count
        ))[0];
        EXPECT_EQ(outcome.status, SolveStatus::Broken) << count << " " << describe(outcome);
        EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face3", "Face1"})) << count;
        EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "name"})) << count;
    }
}

TEST(Moved, twinsTurnedBySymmetryOffCentreBreak)
{
    // PR 340 round 6 (N9): four twins of a disc 0.3 mm off the centre of a hole of four lobes,
    // the hole turned exactly 45 degrees, its symmetry angle. The reference saved on the twin
    // at 225 degrees, (1.806, 1.735), offset (-1.333, -1.265) from the twins' centroid then,
    // now names the piece at 180, offset (-1.828, 0), 1.36 from the old offset; the piece at
    // 270, where the material went, has (-0.038, -1.87), 1.43 from it: 5 % farther, past the
    // 2 % tie. Both offsets lie about 45 degrees from the old one (43.5 and 45.4): an angular
    // tie, broken, the twin first.
    auto outcome = Data::solveOwner(placedTwins(
        {Base::Vector3d(1.31, 3, 10),
         Base::Vector3d(3.10, 1.13, 10),
         Base::Vector3d(3.10, 4.87, 10),
         Base::Vector3d(5.04, 3, 10)},
        6,
        Base::Vector3d(1.806, 1.735, 10),
        Base::Vector3d(3.1385, 3, 10),
        4
    ))[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face2", "Face1"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "name"}));
}

TEST(Moved, twinsTurnedBySymmetryFarOffCentreBreak)
{
    // PR 340 round 7 (N12): as above, a disc of radius 2 0.75 mm off the hole's centre. The
    // twin at 225 degrees, (2.095, 2.026), offset (-1.242, -0.974) from the twins' centroid
    // then, now names the piece at 180, offset (-1.538, 0): 38 degrees from the old offset and
    // 1.02 from it. The piece at 270, where the material went, has (-0.138, -1.65): 47 degrees
    // and 1.30, 27 % farther. The angles lie 9 degrees apart, past round 6's 5-degree band:
    // within the 12-degree band, a tie, broken, the twin first.
    auto outcome = Data::solveOwner(placedTwins(
        {Base::Vector3d(1.77, 3, 10),
         Base::Vector3d(3.17, 1.35, 10),
         Base::Vector3d(3.17, 4.65, 10),
         Base::Vector3d(5.12, 3, 10)},
        6,
        Base::Vector3d(2.095, 2.026, 10),
        Base::Vector3d(3.337, 3, 10),
        4
    ))[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face2", "Face1"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "name"}));
}

TEST(Moved, eighteenTwinsTurnedBySymmetryBreak)
{
    // PR 340 round 7: the move guard (a hit within 5 degrees of the old offset has no angular
    // tie) is not the band (12 degrees). Eighteen twins 20 degrees apart on a ring of radius 3
    // about (10, 10), the reference saved on the one at 0 degrees, turned exactly 10 degrees:
    // the name now holds the twin at -10, and the material went to the one at +10, an
    // irregular piece whose centre lies 3.3 out. Both offsets lie 10 degrees from the old
    // one, but the +10 one is 19 % farther from it: no 2 % tie. A guard as wide as the band
    // would take the hit for a move; at 5 degrees it ties, broken, the twin first.
    auto at = [](double degrees, double radius) {
        const double a = degrees * std::numbers::pi / 180.0;
        return Base::Vector3d(10 + radius * std::cos(a), 10 + radius * std::sin(a), 10);
    };
    std::vector<Base::Vector3d> places {at(-10, 3), at(10, 3.3)};
    for (int k = 2; k < 18; ++k) {
        places.push_back(at(-10 + 20 * k, 3));
    }
    auto outcome = Data::solveOwner(
        placedTwins(places, 18 * 17 / 2, at(0, 3), Base::Vector3d(10, 10, 10), 18)
    )[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face2", "Face1"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "name"}));
}

TEST(Moved, twinsInARowKeepTheirNamesUnderTheAngularTie)
{
    // PR 340 round 6: the angular tie needs the two offsets about as long. Four twins in a row
    // through (3, 3), the reference saved on the outer right one at (6, 3), turned 10 degrees
    // about (3, 3): the twin next to it lies on the same ray from the centroid, at the same
    // angle from the old offset, but a third as far out. No tie: the name stands. Moved
    // without a turn, the hit's offset is the old one: no angular tie either.
    const double c = std::cos(10.0 * std::numbers::pi / 180.0);
    const double s = std::sin(10.0 * std::numbers::pi / 180.0);
    std::vector<Base::Vector3d> turned;
    std::vector<Base::Vector3d> moved;
    for (double x : {-3.0, -1.0, 1.0, 3.0}) {
        turned.emplace_back(3 + x * c, 3 + x * s, 10);
        moved.emplace_back(3.5 + x, 7, 10);
    }
    for (const auto& places : {turned, moved}) {
        EXPECT_EQ(
            describe(
                Data::solveOwner(
                    placedTwins(places, 9, Base::Vector3d(6, 3, 10), Base::Vector3d(3, 3, 10), 4)
                )[0]
            ),
            "exact Face4 0 [] "
        );
    }
}

TEST(SolveOwner, mergedFarCapPieceAloneOnItsFaceNeedsTheCentre)
{
    // PR 340 round 4 (N1): A's pieces either side of a hole in the plate (marks: the plate and
    // the hole's left or right edge) became one ring around it, the only far cap on the plate,
    // so its marks are the plate alone and don't hold the old ones. The one candidate marked by
    // the old piece's face alone takes it when the saved centre lies over it.
    const auto plate = plateElement("plate", 'F');
    const auto oldLeft = farPiece({plate, plateElement("left", 'E')});
    const auto oldRight = farPiece({plate, plateElement("right", 'E')});
    SolveInput input;
    input.pool["Face"] = {
        element("Face4", {farPiece({plate})}),
        element("Face7", {farPiece({plateElement("fill", 'F')})}),
        element("Face9", {sketchEdge(9)}),
    };
    auto entryAt = [](const std::string& name, double x) {
        auto entry = missing(name);
        entry.fingerprint = capAt(x, 0);
        return entry;
    };
    input.entries = {entryAt(oldLeft, -2), entryAt(oldRight, 2)};
    measure(input, {{"Face4", capAt(0, 0)}, {"Face7", capAt(0, 0)}}, nullptr);
    std::vector<std::string> asked;
    input.holdsPoint = [&](const std::string& index, const Base::Vector3d&, double) {
        asked.push_back(index);
        return index == "Face4";
    };
    for (const auto& outcome : Data::solveOwner(input)) {
        EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
        EXPECT_EQ(outcome.element, "Face4") << describe(outcome);
    }
    EXPECT_FALSE(asked.empty());
    EXPECT_TRUE(std::all_of(asked.begin(), asked.end(), [](const auto& index) {
        return index == "Face4";
    }));

    // The saved centre not over it (a face renamed by a reordered up-to shell): broken.
    input.holdsPoint = [](const std::string&, const Base::Vector3d&, double) {
        return false;
    };
    for (const auto& outcome : Data::solveOwner(input)) {
        EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    }
    // No geometry to ask: broken.
    input.holdsPoint = nullptr;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);

    // Marked by another face than the old piece's: broken, whatever the geometry says.
    input.holdsPoint = [](const std::string&, const Base::Vector3d&, double) {
        return true;
    };
    input.pool["Face"][0] = element("Face4", {farPiece({plateElement("other", 'F')})});
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

namespace
{

// ops#386: a piece of the far edge of the Pad (tag 7) from sketch 5's line 1, up to a plate:
// `<line 1>;7;XTR;0;E;<counter>;<flags>;<marks>`. With flags {"PRJ"} and no marks, the far edge
// in one piece.
std::string farEdgePiece(
    const std::vector<std::string>& marks,
    int counter = 0,
    const std::vector<std::string>& flags = {"PRJ", "MOD"},
    int geoId = 1
)
{
    return Data::MappedName::makeEncodedSection(
        {},
        {sketchEdge(geoId)},
        "7",
        "XTR",
        "0",
        'E',
        std::to_string(counter),
        flags,
        marks
    );
}

// A far edge along x from \a x0 to \a x1 at y = \a y on the plate at z = 10.
ElementFingerprint farEdgeAt(double x0, double x1, double y)
{
    return fingerprint(
        'E',
        "Line",
        x1 - x0,
        Base::Vector3d((x0 + x1) / 2, y, 10),
        Base::Vector3d(1, 0, 0)
    );
}

// Whether a point lies within the distance of the far edge along x from \a x0 to \a x1 at y = 1
// (geometry for holdsPoint).
bool onEdgeAt(const Base::Vector3d& point, double distance, double x0, double x1)
{
    const double x = std::clamp(point.x, x0, x1);
    return (point - Base::Vector3d(x, 1, 10)).Length() <= distance;
}

}  // namespace

TEST(SolveOwner, markedEdgePieceAloneOnItsFaceNeedsItsPlace)
{
    // ops#386: A's far bottom edge across a hole in the plate, three pieces: left and right on
    // the plate (marks: the plate and the hole's left or right edge, through their ends) and
    // the middle on the fill. A moved right so that the left piece went: the right piece is
    // alone on the plate, marked by it alone. The one candidate marked by the old piece's face
    // alone takes it when the saved centre lies on it, within a hundredth of the edge's length
    // (not a face's quarter side): the right piece's reference resolves, the left one's breaks.
    const auto plate = plateElement("plate", 'F');
    const auto oldLeft = farEdgePiece({plate, plateElement("left", 'E')});
    const auto oldRight = farEdgePiece({plate, plateElement("right", 'E')});
    SolveInput input;
    input.diagonal = 30;
    input.pool["Edge"] = {
        element("Edge4", {farEdgePiece({plate})}),
        element("Edge7", {farEdgePiece({plateElement("fill", 'F')})}),
        element("Edge9", {sketchEdge(9)}),
    };
    measure(input, {{"Edge4", farEdgeAt(1, 3, 1)}, {"Edge7", farEdgeAt(-0.5, 1, 1)}}, nullptr);
    std::vector<double> distances;
    input.holdsPoint = [&](const std::string& index, const Base::Vector3d& point, double distance) {
        distances.push_back(distance);
        return index == "Edge4" && onEdgeAt(point, distance, 1, 3);
    };
    auto entryAt = [](const std::string& name, double x0, double x1) {
        auto entry = missing(name, "Edge");
        entry.fingerprint = farEdgeAt(x0, x1, 1);
        return entry;
    };
    input.entries = {entryAt(oldRight, 1, 3)};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
    EXPECT_EQ(outcome.element, "Edge4") << describe(outcome);
    ASSERT_FALSE(distances.empty());
    for (double distance : distances) {
        EXPECT_LT(distance, 0.05);
    }

    // The left piece's centre isn't on it: broken.
    input.entries = {entryAt(oldLeft, -3, -1)};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    // Its centre a tenth of a millimetre past the right piece's end, past a hundredth of its
    // length (a face's reach, a quarter of the square root of 2, would take it): broken too.
    input.entries = {entryAt(oldRight, 2.1, 4.1)};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, gonePieceBreaksOnTheSingleProjection)
{
    // ops#386: A's far top edge in two pieces on a shell's two faces, each marked by its face.
    // A moved off the seam onto the right face: the edge is one piece, its name the projection
    // unmarked (PRJ alone). PR 366 rounds 1-8 took the right piece's reference, its centre on
    // the edge, to it. Round 9 (PLAN decision 152): the edge made whole is no evidence, since the
    // plates may have moved under a profile that stayed (in the target's frame), the whole edge on
    // another plate than the piece's: broken, as on integration. The left piece's, its centre
    // off the edge, breaks as before. B's far edge, another projection, doesn't count.
    const auto left = farEdgePiece({plateElement("left", 'F')});
    const auto right = farEdgePiece({plateElement("right", 'F')});
    SolveInput input;
    input.diagonal = 30;
    input.pool["Edge"] = {
        element("Edge3", {farEdgePiece({}, 0, {"PRJ"})}),
        element("Edge5", {farEdgePiece({}, 0, {"PRJ"}, 10)}),
    };
    measure(input, {{"Edge3", farEdgeAt(1.5, 3.5, 1)}, {"Edge5", farEdgeAt(5, 8, 1)}}, nullptr);
    input.holdsPoint = [](const std::string& index, const Base::Vector3d& point, double distance) {
        return (index == "Edge3" && onEdgeAt(point, distance, 1.5, 3.5))
            || (index == "Edge5" && onEdgeAt(point, distance, 5, 8));
    };
    auto entryAt = [](const std::string& name, double x0, double x1) {
        auto entry = missing(name, "Edge");
        entry.fingerprint = farEdgeAt(x0, x1, 1);
        return entry;
    };
    input.entries = {entryAt(right, 1, 2)};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);

    // The left piece's centre is off the edge.
    input.entries = {entryAt(left, 0, 1)};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    // No geometry to ask: broken.
    input.holdsPoint = nullptr;
    input.entries = {entryAt(right, 1, 2)};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(Moved, markedEdgePiecesThatTradedMarksBreak)
{
    // ops#386: A's far top edge in two pieces on a nameless shell's two faces, each marked by its
    // face's index name. The shell rebuilt with its faces in the other order trades the names:
    // the left piece's name now holds the right piece, and the left piece, marked by the other
    // face, sits where it was. The two share every source but are no own twins (ops#168, a copy
    // lifted by its feature): broken, the piece at the old place first. Without it there, the
    // hit moved alone and stands while it overlaps its old place; past it, broken (round 3).
    SolveInput input;
    input.diagonal = 30;
    const auto first = farEdgePiece({plateElement("Face1", 'F')});
    const auto second = farEdgePiece({plateElement("Face2", 'F')});
    input.pool["Edge"] = {
        element("Edge24", {first}),
        element("Edge26", {second}),
    };
    auto entry = exact("Edge24", "Edge");
    entry.exactName = first;
    entry.fingerprint = farEdgeAt(0, 1, 2);
    input.entries = {entry};
    measure(input, {{"Edge24", farEdgeAt(1, 2, 2)}, {"Edge26", farEdgeAt(0, 1, 2)}}, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge26", "Edge24"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "name"}));

    measure(input, {{"Edge24", farEdgeAt(0.5, 1.5, 2)}, {"Edge26", farEdgeAt(5, 6, 2)}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    measure(input, {{"Edge24", farEdgeAt(1, 2, 2)}, {"Edge26", farEdgeAt(5, 6, 2)}}, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge24"}));
    // Moved 2 mm across itself (A grown taller), its old span along the line held: stands.
    measure(input, {{"Edge24", farEdgeAt(0, 1, 4)}, {"Edge26", farEdgeAt(5, 6, 2)}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    // The same for curves (a B-spline plate's far edges), with no direction of their own: along
    // the way to the edge's other piece. Slid past the old place that way: broken.
    auto curve = [](ElementFingerprint fp) {
        fp.kind = "BSpline";
        fp.direction.reset();
        return fp;
    };
    input.entries[0].fingerprint = curve(farEdgeAt(0, 1, 2));
    measure(
        input,
        {{"Edge24", curve(farEdgeAt(0, 1, 4))}, {"Edge26", curve(farEdgeAt(5, 6, 2))}},
        nullptr
    );
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    measure(
        input,
        {{"Edge24", curve(farEdgeAt(2.5, 3, 2))}, {"Edge26", curve(farEdgeAt(3, 4.5, 2))}},
        nullptr
    );
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(Moved, markedCapOffItsOldCentreBreaks)
{
    // PR 366 round 2: A's cap in two pieces on a nameless shell's two faces, the left one marked
    // by its face's index name, Face1. The shell rebuilt with a third face first, under A's
    // middle: Face1 is that face now, and the left piece's name holds the middle piece, which
    // moved, with nothing at the old place (the left piece shrank). The hit doesn't hold the
    // saved centre and the left piece, marked by Face2 now, does: broken, it first. A hit that
    // holds its old centre (A grew) stands. Round 3: one that holds nothing of its old place
    // breaks even with nothing else there (the pieces slid onto the next face).
    SolveInput input;
    const auto first = farPiece({plateElement("Face1", 'F')});
    const auto second = farPiece({plateElement("Face2", 'F')});
    input.pool["Face"] = {
        element("Face11", {first}),
        element("Face12", {second}),
    };
    auto entry = exact("Face11");
    entry.exactName = first;
    entry.fingerprint = capAt(0.5, 1);
    input.entries = {entry};
    measure(input, {{"Face11", capAt(1, 1)}, {"Face12", capAt(0.35, 1)}}, nullptr);
    std::set<std::string> holders {"Face12"};
    input.holdsPoint = [&](const std::string& index, const Base::Vector3d&, double) {
        return holders.count(index) > 0;
    };
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face12", "Face11"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "name"}));

    holders = {"Face11"};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    // Nothing holds the centre, and the hit, 0.5 mm off, still overlaps its old place: stands
    holders.clear();
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    // The piece holding the centre marked by more than a face (a twin, bounded by the hole's
    // edge), as when the disc and the hole moved together: no trade of a face's index, stands
    holders = {"Face12"};
    input.pool["Face"][1].names = {
        farPiece({plateElement("plate", 'F'), plateElement("ellipse", 'E')}, 1, {"PRJ", "MOD"})
    };
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);

    // Round 3: the hit 4.5 mm off, past its old place (the pieces slid onto the next face), with
    // nothing there: broken, the hit its one candidate. A twin (ORD) without twins and an
    // unmarked name: the first breaks the same way, the second moved alone and stands.
    holders.clear();
    input.pool["Face"][1].names = {second};
    measure(input, {{"Face11", capAt(5, 1)}, {"Face12", capAt(0.35, 1)}}, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face11"}));
    const auto ordered = farPiece({plateElement("Face1", 'F')}, 1, {"PRJ", "MOD", "ORD"});
    input.pool["Face"][0].names = {ordered};
    input.entries[0].exactName = ordered;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    input.pool["Face"][0].names = {sketchEdge(9)};
    input.entries[0].exactName = sketchEdge(9);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    // No other piece marked by a face alone (the other bounded by the hole's edge, as the twins
    // around a hole's fill): the piece on the fill when the disc and the hole moved together
    // further than its size, or A's left piece slid onto the next plate, whose other piece
    // shares its plate with B's cap. The two can't be told apart: broken.
    input.pool["Face"][0].names = {first};
    input.entries[0].exactName = first;
    input.pool["Face"][1].names = {
        farPiece({plateElement("plate", 'F'), plateElement("ellipse", 'E')}, 1, {"PRJ", "MOD"})
    };
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(Moved, markedPiecesThatLeftTheirOutlineBreak)
{
    // PR 366 round 5: every face and edge fingerprint has an outline (version 5). A marked piece
    // that moved, with nothing at its old place, stands while its outline shares an area with the
    // old one seen along the old one's normal (a cap), or a length seen along the edge (an edge
    // piece). A record without one (round 4's box alone, or older) keeps round 3's tests.
    SolveInput input;
    input.diagonal = 30;
    const auto first = farPiece({plateElement("Face1", 'F')});
    const auto second = farPiece({plateElement("Face2", 'F')});
    input.pool["Face"] = {
        element("Face11", {first}),
        element("Face12", {second}),
    };
    // The outline's points, and the box round them
    auto outlined = [](ElementFingerprint fp, std::vector<Base::Vector3d> points) {
        Base::Vector3d low = points.front();
        Base::Vector3d high = points.front();
        for (const auto& point : points) {
            low = Base::Vector3d(
                std::min(low.x, point.x),
                std::min(low.y, point.y),
                std::min(low.z, point.z)
            );
            high = Base::Vector3d(
                std::max(high.x, point.x),
                std::max(high.y, point.y),
                std::max(high.z, point.z)
            );
        }
        fp.extentMin = low;
        fp.extentMax = high;
        fp.outline = std::move(points);
        return fp;
    };
    // A tall B-spline cap's left piece, 1 x 8 (x 0..1), slid by 2 onto the next plate of a
    // reordered nameless shell, the model turned by `turn` degrees about Z. Its centre moved 2,
    // under half the two pieces' sides together (2.8), which an older record takes for an
    // overlap: it stands. The outlines share no area: broken, the hit its one candidate.
    auto tall = [&](double x0, double z, double turn = 0.0) {
        const double angle = turn * std::numbers::pi / 180.0;
        auto turned = [&](double x, double y) {
            return Base::Vector3d(
                x * std::cos(angle) - y * std::sin(angle),
                x * std::sin(angle) + y * std::cos(angle),
                z
            );
        };
        return outlined(
            fingerprint('F', "BSpline", 8, turned(x0 + 0.5, 4)),
            {turned(x0, 0), turned(x0 + 1, 0), turned(x0 + 1, 8), turned(x0, 8)}
        );
    };
    auto entry = exact("Face11");
    entry.exactName = first;
    entry.fingerprint = tall(0, 10);
    entry.fingerprint.extentMin.reset();
    entry.fingerprint.extentMax.reset();
    entry.fingerprint.outline.clear();
    input.entries = {entry};
    measure(input, {{"Face11", tall(2, 10)}, {"Face12", tall(3, 10)}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    //   round 4's record, a box without an outline: round 3's test too
    input.entries[0].fingerprint = tall(0, 10);
    input.entries[0].fingerprint.outline.clear();
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    input.entries[0].fingerprint = tall(0, 10);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face11"}));
    // Shifted within its old place (0.5), it stands; lifted 0.5 with its plate, the outlines
    // seen along the normal still overlap: it stands too.
    measure(input, {{"Face11", tall(0.5, 10)}, {"Face12", tall(3, 10)}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    measure(input, {{"Face11", tall(0, 10.5)}, {"Face12", tall(1, 10.5)}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    // Turned by 30 degrees: the boxes in the world's axes, 4.87 by 7.43, still share 3.1 on x and
    // 6.4 on y after the slide (round 4 kept the hit), the outlines share nothing: broken. A
    // shift of 0.5 within the turned place stands.
    input.entries[0].fingerprint = tall(0, 10, 30);
    measure(input, {{"Face11", tall(2, 10, 30)}, {"Face12", tall(3, 10, 30)}}, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face11"}));
    measure(input, {{"Face11", tall(0.5, 10, 30)}, {"Face12", tall(3, 10, 30)}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);

    // A disc's far circle in two arcs (radius 1, centre (1, 1)), the left one x 0..1, slid by 2
    // with the shell reordered: the left arc's name on the next plate's arc, x 2..3. Along the
    // way to the other arc (x), the centres moved 2, under half the arcs' lengths together (pi),
    // which the older record takes for an overlap; the arcs' points seen along it share
    // nothing: broken.
    input.pool["Edge"] = {
        element("Edge24", {farEdgePiece({plateElement("Face1", 'F')})}),
        element("Edge26", {farEdgePiece({plateElement("Face2", 'F')})}),
    };
    auto arc = [&](double cx, double cy, bool left) {
        const double offset = 2.0 / std::numbers::pi;
        ElementFingerprint fp = fingerprint(
            'E',
            "Circle",
            std::numbers::pi,
            Base::Vector3d(left ? cx - offset : cx + offset, cy, 10),
            Base::Vector3d(0, 0, 1),
            {1}
        );
        fp.location = Base::Vector3d(cx, cy, 10);
        std::vector<Base::Vector3d> points;
        for (int i = 0; i <= 16; ++i) {
            const double angle = (left ? 0.5 : -0.5) * std::numbers::pi + std::numbers::pi * i / 16;
            points.emplace_back(cx + std::cos(angle), cy + std::sin(angle), 10);
        }
        return outlined(fp, points);
    };
    auto edgeEntry = exact("Edge24", "Edge");
    edgeEntry.exactName = input.pool["Edge"][0].names[0];
    edgeEntry.fingerprint = arc(1, 1, true);
    edgeEntry.fingerprint.extentMin.reset();
    edgeEntry.fingerprint.extentMax.reset();
    edgeEntry.fingerprint.outline.clear();
    input.entries = {edgeEntry};
    measure(input, {{"Edge24", arc(3, 1, true)}, {"Edge26", arc(3, 1, false)}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    input.entries[0].fingerprint = arc(1, 1, true);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge24"}));
    // The disc moved 3 across the edge (y), its arcs beside each other as before: along the
    // edge the arcs still share the old span, it stands.
    measure(input, {{"Edge24", arc(1, 4, true)}, {"Edge26", arc(1, 4, false)}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
}

TEST(Moved, markedCapOnASeamMovedStands)
{
    // PR 366 round 3: A's cap (x 0..5) in pieces on a nameless three-plate shell, the left one
    // (x 0..1) marked by Face1's index name. The first seam moved from 1 to 0.2, the order the
    // same: the left piece shrank to x 0..0.2, and the middle one, marked by Face2, grew over
    // the old centre. It reaches out of the left piece's old place, so it took ground, not the
    // name: the hit stands. The control (round 2): the piece holding the old centre lies within
    // the old place, the hit off it (a face added first under A's middle took Face1's index):
    // broken, the piece at the old centre first.
    SolveInput input;
    const auto first = farPiece({plateElement("Face1", 'F')});
    const auto second = farPiece({plateElement("Face2", 'F')});
    input.pool["Face"] = {
        element("Face11", {first}),
        element("Face12", {second}),
    };
    auto entry = exact("Face11");
    entry.exactName = first;
    entry.fingerprint = capBox(0, 1, 0, 2);
    input.entries = {entry};
    input.holdsPoint = [](const std::string& index, const Base::Vector3d&, double) {
        return index == "Face12";
    };
    measure(input, {{"Face11", capBox(0, 0.2, 0, 2)}, {"Face12", capBox(0.2, 3, 0, 2)}}, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Exact) << describe(outcome);

    measure(input, {{"Face11", capBox(0.7, 1.3, 0, 2)}, {"Face12", capBox(0, 0.7, 0, 2)}}, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face12", "Face11"}));

    // Faces without a box (a B-spline plate's caps): the neighbour larger than the old piece
    // grew over it, stands; smaller, it shrank around the old centre, broken.
    auto boxless = [](ElementFingerprint fp) {
        fp.kind = "BSpline";
        fp.extentMin.reset();
        fp.extentMax.reset();
        return fp;
    };
    input.entries[0].fingerprint = boxless(capBox(0, 1, 0, 2));
    measure(
        input,
        {{"Face11", boxless(capBox(0, 0.2, 0, 2))}, {"Face12", boxless(capBox(0.2, 3, 0, 2))}},
        nullptr
    );
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Exact);
    measure(
        input,
        {{"Face11", boxless(capBox(0.7, 1.3, 0, 2))}, {"Face12", boxless(capBox(0, 0.7, 0, 2))}},
        nullptr
    );
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(Moved, orderedEdgePiecesMovedTogetherStand)
{
    // PR 366 round 2: A's far top edge in two pieces on a shell's two faces, each marked by its
    // face and counted by its place along the edge (ORD). A moved half a millimetre along the
    // seam: both pieces moved, nothing sits at either old place, and the pieces' marks differ,
    // so they are no twins: each name stands.
    SolveInput input;
    input.diagonal = 30;
    const auto left = farEdgePiece({plateElement("Face1", 'F')}, 1, {"PRJ", "MOD", "ORD"});
    const auto right = farEdgePiece({plateElement("Face2", 'F')}, 2, {"PRJ", "MOD", "ORD"});
    input.pool["Edge"] = {
        element("Edge24", {left}),
        element("Edge26", {right}),
    };
    measure(input, {{"Edge24", farEdgeAt(0.5, 1, 2)}, {"Edge26", farEdgeAt(1, 2.5, 2)}}, nullptr);
    auto entryOn = [](const std::string& index, const std::string& name, double x0, double x1) {
        auto entry = exact(index, "Edge");
        entry.exactName = name;
        entry.fingerprint = farEdgeAt(x0, x1, 2);
        return entry;
    };
    input.entries = {entryOn("Edge24", left, 0, 1), entryOn("Edge26", right, 1, 2)};
    for (const auto& outcome : Data::solveOwner(input)) {
        EXPECT_EQ(outcome.status, SolveStatus::Exact) << describe(outcome);
    }
}

TEST(SolveOwner, otherCopysOrderedPieceIsNoRenumbering)
{
    // ops#523 (the A3 pre-push review's T2): renumberedEdgePieceInItsPlaceResolves's right piece
    // inside link copies. In the same copy (link 11) it is still the old piece renumbered; but
    // copy 11 gone and copy 12's piece at its place is another copy's: a pattern sibling, broken.
    const auto plate3 = plateElement("Face3", 'F');
    const auto oldPiece = copied(farEdgePiece({plate3}, 5, {"PRJ", "MOD", "ORD"}), 11, "L", 'E');
    SolveInput input;
    input.diagonal = 30;
    auto entry = missing(oldPiece, "Edge");
    entry.fingerprint = farEdgeAt(3, 5, 1);
    input.entries = {entry};
    for (int link : {11, 12}) {
        const auto copyPiece
            = copied(farEdgePiece({plate3}, 2, {"PRJ", "MOD", "ORD"}), link, "L", 'E');
        input.pool["Edge"] = {element("Edge12", {copyPiece})};
        measure(input, {{"Edge12", farEdgeAt(3, 5, 1)}}, nullptr);
        const auto outcome = Data::solveOwner(input)[0];
        if (link == 11) {
            EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
            EXPECT_EQ(outcome.element, "Edge12") << describe(outcome);
        }
        else {
            EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
            EXPECT_EQ(outcome.evidence, "pattern sibling") << describe(outcome);
        }
    }
}

TEST(SolveOwner, renumberedEdgePieceInItsPlaceResolves)
{
    // PR 366 round 2: A's far top edge in three pieces on three plates, the right one (x 3..5)
    // third of three (counter 3 + 2). A shortened from the left so that the left piece went:
    // the right piece is second of two now (counter 1 + 1), its marks the same. Its name differs
    // from the old one by the counter alone, which reads as a pattern's copy, never the element
    // itself; but it sits where the old piece was, which a copy never does: resolved. The
    // middle piece, shortened (x 1.5..3, was 1..3), is no longer where it was: broken.
    const auto plate3 = plateElement("Face3", 'F');
    const auto plate2 = plateElement("Face2", 'F');
    SolveInput input;
    input.diagonal = 30;
    input.pool["Edge"] = {
        element("Edge12", {farEdgePiece({plate3}, 2, {"PRJ", "MOD", "ORD"})}),
        element("Edge14", {farEdgePiece({plate2}, 1, {"PRJ", "MOD", "ORD"})}),
    };
    measure(input, {{"Edge12", farEdgeAt(3, 5, 1)}, {"Edge14", farEdgeAt(1.5, 3, 1)}}, nullptr);
    auto entryAt = [](const std::string& name, double x0, double x1) {
        auto entry = missing(name, "Edge");
        entry.fingerprint = farEdgeAt(x0, x1, 1);
        return entry;
    };
    input.entries = {entryAt(farEdgePiece({plate3}, 5, {"PRJ", "MOD", "ORD"}), 3, 5)};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
    EXPECT_EQ(outcome.element, "Edge12") << describe(outcome);

    input.entries = {entryAt(farEdgePiece({plate2}, 4, {"PRJ", "MOD", "ORD"}), 1, 3)};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);

    // Round 3: with geometry to ask, the middle piece, the only one marked by plate 2, fewer
    // pieces counted (two of two, was three) and the saved centre (x 2) on it, is the element.
    input.holdsPoint = [](const std::string& index, const Base::Vector3d& point, double distance) {
        return (index == "Edge12" && onEdgeAt(point, distance, 3, 5))
            || (index == "Edge14" && onEdgeAt(point, distance, 1.5, 3));
    };
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
    EXPECT_EQ(outcome.element, "Edge14") << describe(outcome);
    // Its centre off the piece (x 0.5): broken.
    input.entries = {entryAt(farEdgePiece({plate2}, 4, {"PRJ", "MOD", "ORD"}), 0, 1)};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    // Pieces coming (second of three now, was first of two): a face added to the shell may
    // have taken plate 2's index, so broken.
    input.entries = {entryAt(farEdgePiece({plate2}, 1, {"PRJ", "MOD", "ORD"}), 1, 3)};
    input.pool["Edge"][1].names = {farEdgePiece({plate2}, 4, {"PRJ", "MOD", "ORD"})};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    // Another piece marked by plate 2 too: broken.
    input.entries = {entryAt(farEdgePiece({plate2}, 4, {"PRJ", "MOD", "ORD"}), 1, 3)};
    input.pool["Edge"][1].names = {farEdgePiece({plate2}, 1, {"PRJ", "MOD", "ORD"})};
    input.pool["Edge"][0].names = {farEdgePiece({plate2}, 2, {"PRJ", "MOD", "ORD"})};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, mergedFarCapPiecesResolveToTheirWhole)
{
    // PR 340 round 3: A's pieces either side of a hole in the plate (marks: the plate and the
    // hole's left or right edge) became one ring around it (the plate and the hole's four
    // edges). The piece on the hole's fill shares their start cap as fully, and survives tier 1
    // beside the ring; the ring's name holds each old piece's, so it takes them, together.
    const auto plate = plateElement("plate", 'F');
    const auto left = plateElement("left", 'E');
    const auto right = plateElement("right", 'E');
    const auto oldLeft = farPiece({plate, left});
    const auto oldRight = farPiece({plate, right});
    SolveInput input;
    input.pool["Face"] = {
        element(
            "Face4",
            {farPiece({plate, left, plateElement("top", 'E'), right, plateElement("bottom", 'E')})}
        ),
        element("Face7", {farPiece({plateElement("fill", 'F')})}),
        element("Face9", {sketchEdge(9)}),
    };
    input.entries = {missing(oldLeft), missing(oldRight)};
    auto outcomes = Data::solveOwner(input);
    for (const auto& outcome : outcomes) {
        EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
        EXPECT_EQ(outcome.element, "Face4") << describe(outcome);
    }
    //   one of them alone
    input.entries = {missing(oldLeft)};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
    EXPECT_EQ(outcome.element, "Face4");

    // A piece marked by its face alone is no evidence: a renumbered up-to shell gives the face's
    // name to another face, whose pieces then hold it (the probe's seam/reorder).
    input.entries = {missing(farPiece({plate}))};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    input.entries = {missing(oldLeft)};

    // Two candidates that hold the old piece: no evidence, as before.
    input.pool["Face"].push_back(element("Face5", {farPiece({plate, left, plateElement("top", 'E')})}));
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
    // A projection that isn't a marked piece (PRJ alone) gets no such evidence either.
    input.pool["Face"].pop_back();
    input.pool["Face"][0] = element("Face4", {farPiece({plate, left, right}, 0, {"PRJ"})});
    input.pool["Face"][1] = element("Face7", {farPiece({plateElement("fill", 'F')}, 0, {"PRJ"})});
    input.entries = {missing(farPiece({plate, left}, 0, {"PRJ"}))};
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, twinCapPiecesBreakWhenTheirCapIsMadeWhole)
{
    // PR 366 round 2, PLAN decision 122 (2): A's cap across an elliptic hole in the plate, two
    // twins (the plate, the ellipse and A's circle; ORD) at (3, 5.5) and (3, 0.5). The hole moved
    // away from under A: A's cap is one face again, the projection unmarked (PRJ alone), and it
    // holds both old centres. Round 9 (decision 152): a far cap made whole is no evidence, since
    // the plates may have moved under a profile that stayed (in the target's frame), the whole
    // cap on another plate than the pieces'. Both references break, as without the rule.
    const std::vector<std::string> marks {
        plateElement("plate", 'F'),
        plateElement("ellipse", 'E'),
        plateElement("circle", 'E')
    };
    SolveInput input;
    input.diagonal = 40;
    input.pool["Face"] = {
        element("Face4", {farPiece({}, 0, {"PRJ"})}),
        element("Face9", {sketchEdge(9)}),
    };
    // The whole cap: the disc, centred between the pieces
    const auto whole = fingerprint('F', "Plane", 28, Base::Vector3d(3, 3, 10), Base::Vector3d(0, 0, 1));
    measure(input, {{"Face4", whole}, {"Face9", capAt(20, 3)}}, nullptr);
    std::set<std::string> holders {"Face4"};
    input.holdsPoint = [&](const std::string& index, const Base::Vector3d&, double) {
        return holders.count(index) > 0;
    };
    auto entryAt = [&](int counter, double y) {
        auto entry = missing(farPiece(marks, counter, {"PRJ", "MOD", "ORD"}));
        entry.fingerprint = capAt(3, y);
        return entry;
    };
    input.entries = {entryAt(1, 0.5), entryAt(2, 5.5)};
    for (const auto& outcome : Data::solveOwner(input)) {
        EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    }

    // Nor when the whole cap doesn't hold the old centre (A moved away): broken.
    holders.clear();
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, pieceAloneOnItsFaceIsSeenAlongTheSweep)
{
    // PR 366 round 8, round 9: a Pad from below up to a B-spline plate. A's strip on it (marks:
    // the plate and a seam edge, centre (-0.25, 4, 9.5)) went, and the only far cap on the plate
    // left, marked by the plate alone (the alone rule), lies beside it: its nearest point to the
    // strip's centre lies inside it, but seen along the sweep (z) the centre lies beside it. The
    // strip's reference breaks. A piece whose centre is held seen along the sweep takes the cap
    const auto plate = plateElement("plate", 'F');
    const auto seam = plateElement("seam", 'E');
    SolveInput input;
    input.diagonal = 40;
    // Another far cap, on another face: structure alone doesn't decide
    input.pool["Face"] = {
        element("Face4", {farPiece({plate})}),
        element("Face7", {farPiece({plateElement("other", 'F')})}),
        element("Face9", {sketchEdge(9)}),
    };
    const auto cap = fingerprint('F', "BSplineSurface", 62.6, Base::Vector3d(1.85, 4, 6.3));
    const auto other = fingerprint('F', "BSplineSurface", 62.6, Base::Vector3d(12, 4, 6.3));
    measure(input, {{"Face4", cap}, {"Face7", other}, {"Face9", capAt(20, 3)}}, nullptr);
    input.sweep = Base::Vector3d(0, 0, 1);
    // The cap's nearest point to either old centre lies inside it
    input.holdsPoint = [](const std::string& index, const Base::Vector3d&, double) {
        return index == "Face4";
    };
    // Seen along the sweep: only a centre at x > 0.6 lies over it
    std::vector<Base::Vector3d> seenAlong;
    input.holdsPointAlong = [&](const std::string& index,
                                const Base::Vector3d& point,
                                const Base::Vector3d& along,
                                double) {
        seenAlong.push_back(along);
        return index == "Face4" && point.x > 0.6;
    };
    // The strip x -0.5..0, y 0..8, its outline bounding it closely
    auto strip = missing(farPiece({plate, seam}));
    strip.fingerprint = fingerprint('F', "BSplineSurface", 8.94, Base::Vector3d(-0.25, 4, 9.5));
    strip.fingerprint.outline = {Base::Vector3d(-0.5, 0, 9),
                                 Base::Vector3d(0, 0, 10),
                                 Base::Vector3d(0, 8, 10),
                                 Base::Vector3d(-0.5, 8, 9)};
    input.entries = {strip};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    ASSERT_FALSE(seenAlong.empty());
    EXPECT_EQ(seenAlong.front(), Base::Vector3d(0, 0, 1));

    // A piece x 0..3: on the cap, quietly
    auto piece = missing(farPiece({plate, seam}));
    piece.fingerprint = fingerprint('F', "BSplineSurface", 53.67, Base::Vector3d(1.5, 4, 7));
    piece.fingerprint.outline = {Base::Vector3d(0, 0, 10),
                                 Base::Vector3d(3, 0, 4),
                                 Base::Vector3d(3, 8, 4),
                                 Base::Vector3d(0, 8, 10)};
    input.entries = {piece};
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
    EXPECT_EQ(outcome.element, "Face4") << describe(outcome);

    // Round 7 (I-S9): a piece whose area (0.39 here) falls short of its outline's, saved with no
    // point inside it, may have its centre outside it: broken although held; with the point
    // saved, it takes the cap again
    input.entries = {piece};
    input.entries[0].fingerprint.size = 0.39;
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    input.entries[0].fingerprint.inside = Base::Vector3d(2.5, 4, 5);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);

    // Round 9 (decision 152): the same piece and a far cap made whole (the projection unmarked)
    // that holds its centre: broken, a far cap made whole being no evidence
    // (the other plate's cap left out: the only structural survivor then)
    const auto pool = input.pool["Face"];
    input.pool["Face"] = {element("Face4", {farPiece({}, 0, {"PRJ"})}), pool[2]};
    input.entries = {piece};
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << describe(outcome);
    input.pool["Face"] = pool;

    // An old face along the sweep (its outline a wall) is seen as before, by its nearest point,
    // and so is any face without a sweep (another feature): the strip takes the cap
    seenAlong.clear();
    input.entries = {strip};
    input.entries[0].fingerprint.outline = {Base::Vector3d(-0.5, 0, 0),
                                            Base::Vector3d(-0.5, 8, 0),
                                            Base::Vector3d(-0.5, 8, 9),
                                            Base::Vector3d(-0.5, 0, 9)};
    input.entries[0].fingerprint.size = 72;
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
    EXPECT_TRUE(seenAlong.empty());
    input.entries = {strip};
    input.sweep.reset();
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << describe(outcome);
    EXPECT_TRUE(seenAlong.empty());
}

TEST(Moved, hintKeepsATwinAtTheToleranceEdge)
{
    // Twins as far from the saved element as atSamePlace() allows (just inside every
    // tolerance), and BSplines (no direction, no anchor): the hint must leave them all to the
    // fingerprint.
    GeometryTolerances tolerances;
    const double diagonal = 43.6;
    const double eps = 1e-7 * diagonal;
    const double edge = 0.999;  // a hair inside
    auto moved = [](ElementFingerprint fp, Base::Vector3d by) {
        fp.center = *fp.center + by;
        if (fp.location) {
            fp.location = *fp.location + by;
        }
        return fp;
    };
    auto tilt = [](ElementFingerprint fp, double angle) {
        Base::Vector3d d = *fp.direction;
        Base::Vector3d side = std::abs(d.x) < 0.9 ? Base::Vector3d(1, 0, 0) : Base::Vector3d(0, 1, 0);
        side = side - d * (side * d);
        side.Normalize();
        fp.direction = d * std::cos(angle) + side * std::sin(angle);
        return fp;
    };
    auto top = fingerprint('F', "Plane", 36, Base::Vector3d(10, 15, 10), Base::Vector3d(0, 0, 1));
    auto bspline = fingerprint('E', "BSpline", 12, Base::Vector3d(3, 4, 5));
    auto bsplineFace = fingerprint('F', "BSpline", 40, Base::Vector3d(3, 4, 5));
    auto vertex = fingerprint('V', "Point", {}, Base::Vector3d(13, 12, 10));
    struct Case
    {
        const char* what;
        ElementFingerprint saved;
        ElementFingerprint twin;
    };
    const std::vector<Case> cases {
        {"plane, centre off its plane", top, moved(top, Base::Vector3d(0, 0, edge * eps))},
        {"plane, centre in its plane", top, moved(top, Base::Vector3d(edge * eps, 0, 0))},
        {"plane, tilted", top, tilt(top, edge * tolerances.angle)},
        {"line, off its line", lineX(0, 20), moved(lineX(0, 20), Base::Vector3d(0, edge * eps, 0))},
        {"line, along it", lineX(0, 20), moved(lineX(0, 20), Base::Vector3d(edge * eps, 0, 0))},
        {"line, tilted", lineX(0, 20), tilt(lineX(0, 20), edge * tolerances.angle)},
        {"circle, centre", circleAt(10, 15), moved(circleAt(10, 15), Base::Vector3d(edge * eps, 0, 0))},
        {"circle, radius", circleAt(10, 15), circleAt(10, 15, 3 * (1 + edge * tolerances.radius))},
        {"vertex", vertex, moved(vertex, Base::Vector3d(0, 0, edge * eps))},
        {"bspline edge", bspline, moved(bspline, Base::Vector3d(edge * eps, 0, 0))},
        {"bspline face", bsplineFace, moved(bsplineFace, Base::Vector3d(0, edge * eps, 0))},
    };
    for (const auto& c : cases) {
        const auto& twin = c.twin;
        ASSERT_TRUE(Data::atSamePlace(c.saved, twin, diagonal, tolerances, 1e-7)) << c.what;
        const Hinted hint = hintOf(twin);
        EXPECT_TRUE(Data::mayBeAtPlace(c.saved, hint.intrinsic, hint.anchor, diagonal, tolerances,
                                       1e-7))
            << c.what;
    }
}

// The guess rules (ops#127, design note N2 section 5). Off by default in SolveInput; the batch
// turns them on from the NamingSolver parameters.

TEST(SolveOwner, guessNearestAmongStructuralSurvivors)
{
    // G1: two structural survivors that tier 2 keeps; neither within tier 3's strict d_max (0.3
    // of a 30 diagonal), the nearest within the wide one (1.5) and the second at least twice as
    // far and beyond it.
    Placed p;
    SolveInput input;
    input.diagonal = 30.0;
    input.pool["Face"] = {
        element("Face2", {p.names.newTop}),
        element("Face10", {p.otherTop}),
    };
    input.entries = {missing(p.names.oldTop)};
    input.entries[0].fingerprint = p.top;
    measure(input, {{"Face2", p.topAt(11)}, {"Face10", p.topAt(12.5)}}, nullptr);

    //   without the rule: ambiguous, as before
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "ambiguous");

    input.guess = true;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Face2");
    EXPECT_EQ(outcomes[0].tier, 3);
    EXPECT_EQ(outcomes[0].guessKind, "nearest");
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Face2", "Face10"}));
    EXPECT_EQ(outcomes[0].candidateRoles, (std::vector<std::string> {"guess", "structural"}));
    ASSERT_EQ(outcomes[0].candidateDistances.size(), 2U);
    EXPECT_NEAR(outcomes[0].candidateDistances[0], 1.0, 1e-9);
    EXPECT_NEAR(outcomes[0].candidateDistances[1], 2.5, 1e-9);
    EXPECT_EQ(outcomes[0].evidence.rfind("guess: tier 3 wide: nearest 1.000, second 2.500", 0), 0U);

    //   a true tie (N8): the second within twice the nearest
    measure(input, {{"Face2", p.topAt(11)}, {"Face10", p.topAt(11.8)}}, nullptr);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);

    //   never against a failed target (N10)
    measure(input, {{"Face2", p.topAt(11)}, {"Face10", p.topAt(12.5)}}, nullptr);
    input.targetFailed = true;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, guessGeometricWithoutStructure)
{
    // G2: SketchRedraw's edges with the edge redrawn 0.5 over in the same sketch (new geometry
    // IDs, the same sketch tag): no structural candidate, tier 3's strict d_max (0.245) misses
    // it, the wide one (1.225) takes it, the next edge is 10 away.
    const auto oldEdge = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    auto line = [](double x, double z) {
        return fingerprint('E', "Line", 10, Base::Vector3d(x, 5, z), Base::Vector3d(0, 1, 0));
    };
    SolveInput input;
    input.diagonal = 24.5;
    input.pool["Edge"] = {
        element("Edge1", {section({}, {sketchEdge(12)}, 7, "XTR", 0, 'E', {"PRJ"})}),
        element("Edge2", {section({}, {sketchEdge(13)}, 7, "XTR", 0, 'E', {"PRJ"})}),
        element("Edge3", {section({}, {sketchEdge(12)}, 7, "XTR", 1, 'E', {"PRJ"})}),
        element("Edge4", {section({}, {sketchEdge(13)}, 7, "XTR", 1, 'E', {"PRJ"})}),
    };
    measure(
        input,
        {{"Edge1", line(0, 0)},
         {"Edge2", line(20, 0)},
         {"Edge3", line(0, 10)},
         {"Edge4", line(20, 10)}},
        nullptr
    );
    input.entries = {missing(oldEdge, "Edge")};
    input.entries[0].fingerprint = line(20.5, 10);

    //   G1 alone doesn't guess without structure
    input.guess = true;
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U);

    input.guessNoStructure = true;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Edge4");
    EXPECT_EQ(outcomes[0].tier, 3);
    EXPECT_EQ(outcomes[0].guessKind, "geometric");
    //   the alternatives in rank order, nearest first
    EXPECT_EQ(outcomes[0].candidates,
              (std::vector<std::string> {"Edge4", "Edge2", "Edge3", "Edge1"}));
    EXPECT_EQ(outcomes[0].candidateRoles[1], "geometric");
    EXPECT_EQ(
        outcomes[0].evidence.rfind(
            "guess: no structural candidate, redrawn in the same source, tier 3 wide",
            0
        ),
        0U
    );

    //   5 over: beyond the wide d_max too (N7/N8)
    input.entries[0].fingerprint = line(25, 10);
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, guessGeometricNeedsTheSameSource)
{
    // Policy D (ops#127, N3 4.4): guessGeometricWithoutStructure's redraw, but the edges come
    // from another sketch (tag 6), as when the line is drawn again as a new sketch object or
    // the original is deleted beside a neighbour: no guess. The reference breaks with the
    // agreeing edges nearest the saved centre first, with their distances (N3 5.3).
    // NamingSolver/GuessAnySource (SolveInput::guessAnySource) guesses as before.
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
    };
    measure(
        input,
        {{"Edge1", line(0, 0)}, {"Edge2", line(20, 0)}, {"Edge3", line(0, 10)}, {"Edge4", line(20, 10)}},
        nullptr
    );
    input.entries = {missing(oldEdge, "Edge")};
    input.entries[0].fingerprint = line(20.5, 10);
    input.guess = true;
    input.guessNoStructure = true;

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U);
    EXPECT_NE(outcomes[0].evidence.find("the wide reach's Edge4 has another source"), std::string::npos);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge4", "Edge2", "Edge3", "Edge1"}));
    ASSERT_EQ(outcomes[0].candidateDistances.size(), 4U);
    EXPECT_NEAR(outcomes[0].candidateDistances[0], 0.5, 1e-9);
    EXPECT_NEAR(outcomes[0].candidateDistances[1], std::hypot(0.5, 10.0), 1e-9);
    EXPECT_NEAR(outcomes[0].candidateDistances[2], 20.5, 1e-9);
    EXPECT_NEAR(outcomes[0].candidateDistances[3], std::hypot(20.5, 10.0), 1e-9);
    EXPECT_EQ(
        outcomes[0].candidateRoles,
        (std::vector<std::string> {"geometric", "geometric", "geometric", "geometric"})
    );

    //   any source
    input.guessAnySource = true;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Edge4");
    EXPECT_EQ(outcomes[0].evidence.rfind("guess: no structural candidate, tier 3 wide", 0), 0U);

    //   an index-only reference (no name, no source) breaks, and is guessed with any source
    input.guessAnySource = false;
    input.entries[0].oldName.clear();
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates.front(), "Edge4");
    input.guessAnySource = true;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Guessed);
}

TEST(NameAncestry, sourceTags)
{
    // The innermost sources of V2 names (ops#127, N3 5.1), in the pattern of
    // NamingGolden/Refine.V2.txt: sketch Profile is tag 5, the pad 7, a second sketch 6.
    auto padEdge = [](int geoId, int sketchTag) {
        return section({}, {sketchEdge(geoId, sketchTag)}, 7, "XTR", 0, 'E', {"PRJ"});
    };
    const std::vector<std::string> profile {"5"};
    //   a pad edge from sketch Profile; the same edge redrawn (a new ID, the same sketch)
    EXPECT_EQ(NameAncestry::sourceTags(padEdge(1, 5)), profile);
    EXPECT_EQ(NameAncestry::sourceTags(padEdge(9, 5)), profile);
    //   an edge from a second sketch
    EXPECT_EQ(NameAncestry::sourceTags(padEdge(1, 6)), (std::vector<std::string> {"6"}));
    //   a vertical edge, generated from a sketch vertex (two IDs, one sketch)
    const auto vertical = section({}, {sketchVertex({"g1v1", "g4v2"})}, 7, "XTR", 0, 'E', {"GEN"});
    EXPECT_EQ(NameAncestry::sourceTags(vertical), profile);
    //   the sketch's own edge: a section made from no name
    EXPECT_EQ(NameAncestry::sourceTags(sketchEdge(1)), profile);
    //   a face made from the edges of two sketches has both
    EXPECT_EQ(
        NameAncestry::sourceTags(lowFace({sketchEdge(1, 5), sketchEdge(2, 6)}, 8)),
        (std::vector<std::string> {"5", "6"})
    );
    //   a split piece (MOD) and its connected elements add no source
    const auto split = piece(padEdge(1, 5), 9, "FUS", 1, 'E', {padEdge(2, 6)});
    EXPECT_EQ(NameAncestry::sourceTags(split), profile);
    //   FilletDeleteNearStep's step (StepSketch, tag 8) padded (tag 9) onto the block: its front
    //   vertical edge keeps its pad's name through the fusion, `_;g1v2^,g2v1^;_^;<StepSketch>^;
    //   SKT^;0^;V^;0^;SRC^;_;<Step>;XTR;0;E;0;GEN;_` (a FreeCADCmd probe, ops#127 P8a), so its
    //   source is the step's sketch alone, and the block's corner edge beside it shares none
    const auto stepEdge = section({}, {sketchVertex({"g1v2", "g2v1"}, 8)}, 9, "XTR", 0, 'E', {"GEN"});
    EXPECT_EQ(NameAncestry::sourceTags(stepEdge), (std::vector<std::string> {"8"}));
    const auto blockCorner
        = section({}, {sketchVertex({"g1v2", "g2v1"}, 5)}, 7, "XTR", 0, 'E', {"GEN"});
    EXPECT_EQ(NameAncestry::sourceTags(blockCorner), profile);
    EXPECT_TRUE(NameAncestry::sourceTags("").empty());
}

TEST(NameAncestry, sourceSections)
{
    // The innermost source sections (ops#168): tag, type and reference IDs. Profile is tag 5,
    // the pad 7, a second sketch 6.
    auto padEdge = [](int geoId, int sketchTag) {
        return section({}, {sketchEdge(geoId, sketchTag)}, 7, "XTR", 0, 'E', {"PRJ"});
    };
    const std::vector<std::string> line2 {"5;E;g2,"};
    //   the pad's top edge (PRJ) and its bottom edge (the sketch line verbatim): one source
    EXPECT_EQ(NameAncestry::sourceSections(padEdge(2, 5)), line2);
    EXPECT_EQ(NameAncestry::sourceSections(sketchEdge(2)), line2);
    //   another line of the sketch, the line redrawn (a new ID), another sketch: other sources
    EXPECT_NE(NameAncestry::sourceSections(padEdge(3, 5)), line2);
    EXPECT_NE(NameAncestry::sourceSections(padEdge(9, 5)), line2);
    EXPECT_NE(NameAncestry::sourceSections(padEdge(2, 6)), line2);
    //   a vertical edge from a sketch vertex: the vertex's IDs
    const auto vertical = section({}, {sketchVertex({"g1v1", "g4v2"})}, 7, "XTR", 0, 'E', {"GEN"});
    EXPECT_EQ(NameAncestry::sourceSections(vertical), (std::vector<std::string> {"5;V;g1v1,g4v2,"}));
    //   a face of two sketches' edges has both; a split piece and its neighbours add none
    EXPECT_EQ(
        NameAncestry::sourceSections(lowFace({sketchEdge(2, 5), sketchEdge(1, 6)}, 8)),
        (std::vector<std::string> {"5;E;g2,", "6;E;g1,"})
    );
    EXPECT_EQ(NameAncestry::sourceSections(piece(padEdge(2, 5), 9, "FUS", 1, 'E', {padEdge(1, 6)})),
              line2);
    //   a source without a reference ID or a tag is unknown: no sources at all
    EXPECT_TRUE(NameAncestry::sourceSections(section({}, {}, 7, "XTR", 0, 'E', {})).empty());
    EXPECT_TRUE(
        NameAncestry::sourceSections(lowFace({sketchEdge(2), section({}, {}, 7, "XTR", 0, 'E', {})}))
            .empty()
    );
    EXPECT_TRUE(NameAncestry::sourceSections("").empty());
}

namespace
{

// ops#167's seed (272, gap 1, step 9): a hole's bottom circle, generated by the hole's cut (tag
// \a hole) from the block's bottom face (sketch 5) and the hole's own cylinder (extruded from
// edge \a geoId of the hole's sketch \a holeSketch). Every hole through that face embeds it.
std::string holeBottomCircle(int holeSketch, int hole, int geoId = 1)
{
    return generated(
        {lowFace({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)}),
         generated({sketchEdge(geoId, holeSketch)}, hole, "XTR", 'F')},
        hole,
        "CUT",
        'E'
    );
}

}  // namespace

TEST(NameAncestry, makerAndLineage)
{
    // ops#167: the maker is the first section's tag; the lineage is that tag and, recursively,
    // every tag of every section of the names it links.
    const auto f1 = holeBottomCircle(40, 41);
    const auto f7 = holeBottomCircle(70, 71);
    EXPECT_EQ(NameAncestry::makerTag(f1), "41");
    EXPECT_EQ(NameAncestry::makerTag(f7), "71");
    //   F1's circle: F1Hole, the block's sketch (through the face cut), F1's sketch
    for (const char* tag : {"41", "5", "40"}) {
        EXPECT_TRUE(NameAncestry::hasLineageTag(f1, tag)) << tag;
    }
    //   F7's circle shares the face, not the maker
    EXPECT_FALSE(NameAncestry::hasLineageTag(f7, "41"));
    EXPECT_TRUE(NameAncestry::hasLineageTag(f7, "5"));
    //   a piece keeps the maker; the cutter's section isn't lineage, nor are connected elements
    const auto split = piece(f1, 90, "FUS", 1, 'E', {f7});
    EXPECT_EQ(NameAncestry::makerTag(split), "41");
    EXPECT_TRUE(NameAncestry::hasLineageTag(split, "41"));
    EXPECT_FALSE(NameAncestry::hasLineageTag(split, "90"));
    EXPECT_FALSE(NameAncestry::hasLineageTag(split, "71"));
    //   a pattern instance keeps it too
    const auto copy = stepInstance(f1, 95, "2", 'E');
    EXPECT_EQ(NameAncestry::makerTag(copy), "41");
    EXPECT_FALSE(NameAncestry::hasLineageTag(copy, "95"));
    //   a name made from a split piece: every section of the linked name is lineage
    const auto merged = generated({piece(f7, 90, "FUS", 1, 'E')}, 99, "RFI", 'E');
    EXPECT_EQ(NameAncestry::makerTag(merged), "99");
    EXPECT_TRUE(NameAncestry::hasLineageTag(merged, "90"));
    EXPECT_TRUE(NameAncestry::hasLineageTag(merged, "71"));
    EXPECT_FALSE(NameAncestry::hasLineageTag(merged, "41"));
    //   an empty name has neither; an empty tag is in no lineage
    EXPECT_TRUE(NameAncestry::makerTag("").empty());
    EXPECT_FALSE(NameAncestry::hasLineageTag("", "41"));
    EXPECT_FALSE(NameAncestry::hasLineageTag(f1, ""));
}

TEST(SolveOwner, anotherMakersElementIsNoStructuralCandidate)
{
    // ops#167: F1Hole is deleted; F7Hole's bottom circle (r 2) and F2Hole's (r 1.25) share the
    // block's bottom face with F1's old circle, overlap 0.62, so tier 1 kept both and tier 2
    // took F7's, 8.46 mm away. T1 drops them: another maker's element is no structural
    // candidate, and the reference breaks with the agreeing circles by distance.
    auto circle = [](double x, double y, double r) {
        const Base::Vector3d axis(0, 0, 1);
        const double length = 2 * std::numbers::pi * r;
        return fingerprint('E', "Circle", length, Base::Vector3d(x, y, 0), axis, {r});
    };
    SolveInput input;
    input.diagonal = 40.0;  // strict reach 0.4, wide 2
    input.pool["Edge"] = {
        element("Edge3", {holeBottomCircle(70, 71)}),
        element("Edge9", {holeBottomCircle(80, 81)}),
    };
    measure(input, {{"Edge3", circle(22.96, 15, 2)}, {"Edge9", circle(5, 5, 1.25)}}, nullptr);
    input.entries = {missing(holeBottomCircle(40, 41), "Edge")};
    input.entries[0].fingerprint = circle(14.5, 15, 2);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U)
        << outcomes[0].evidence;
    EXPECT_NE(outcomes[0].evidence.find("tier 1's 2 survivors have another maker"),
              std::string::npos)
        << outcomes[0].evidence;
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates.front(), "Edge3");
    EXPECT_NEAR(outcomes[0].candidateDistances.front(), 8.46, 1e-9);

    //   without T1 (and T1', ops#173): ops#167's before, tier 2 among the two survivors
    input.sameMaker = false;
    input.sameSource = false;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge3");
    EXPECT_EQ(outcomes[0].tier, 2);
    EXPECT_EQ(outcomes[0].evidence, "overlap 0.62, sources overlap, tier 2: 1 of 2");

    //   one survivor alone resolves silently at tier 1 without T1, and breaks with it
    input.pool["Edge"].pop_back();
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge3");
    EXPECT_EQ(outcomes[0].tier, 1);
    input.sameMaker = true;
    input.sameSource = true;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_NE(outcomes[0].evidence.find("tier 1's 1 survivor has another maker"), std::string::npos)
        << outcomes[0].evidence;

    //   G2': the circle 1.5 mm away is within the wide reach and shares a source (the block's
    //   sketch, through the face), but not the maker: no guess
    measure(input, {{"Edge3", circle(16, 15, 2)}}, nullptr);
    input.guess = true;
    input.guessNoStructure = true;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_NE(outcomes[0].evidence.find("the wide reach's Edge3 has another maker"),
              std::string::npos)
        << outcomes[0].evidence;
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates.front(), "Edge3");
    EXPECT_NEAR(outcomes[0].candidateDistances.front(), 1.5, 1e-9);
    //   any source: guessed
    input.guessAnySource = true;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Edge3");
    EXPECT_EQ(outcomes[0].guessKind, "geometric");
}

TEST(SolveOwner, redrawnCircleIsFoundByGeometry)
{
    // ops#167's control: the hole's circle redrawn in its own sketch (a new geometry ID, the
    // same sketch and hole) keeps the maker, so T1 keeps it. It lost the old circle's source
    // (g1), so T1' (ops#173) drops it: geometry decides, as for another hole's circle.
    auto circle = [](double x) {
        const Base::Vector3d axis(0, 0, 1);
        const double length = 4 * std::numbers::pi;
        return fingerprint('E', "Circle", length, Base::Vector3d(x, 10, 0), axis, {2.0});
    };
    SolveInput input;
    input.diagonal = 40.0;  // strict reach 0.4, wide 2
    input.pool["Edge"] = {element("Edge3", {holeBottomCircle(40, 41, 2)})};
    measure(input, {{"Edge3", circle(8.5)}}, nullptr);
    input.entries = {missing(holeBottomCircle(40, 41), "Edge")};
    input.entries[0].fingerprint = circle(8);

    //   0.5 mm over, beyond the strict reach: broken with it as the candidate...
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_NE(outcomes[0].evidence.find("tier 1's 1 survivor lost the old element's source"),
              std::string::npos)
        << outcomes[0].evidence;
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates.front(), "Edge3");
    EXPECT_NEAR(outcomes[0].candidateDistances.front(), 0.5, 1e-9);
    //   ... and, with the guess rules, G2's warned pick (the same sketch and hole, policy D)
    input.guess = true;
    input.guessNoStructure = true;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Edge3");
    EXPECT_EQ(outcomes[0].guessKind, "geometric");
    //   redrawn at its place: tier 3 takes it
    measure(input, {{"Edge3", circle(8.2)}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge3");
    EXPECT_EQ(outcomes[0].tier, 3);
    //   without T1': tier 1 takes it, as after ops#167
    measure(input, {{"Edge3", circle(8.5)}}, nullptr);
    input.sameSource = false;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge3");
    EXPECT_EQ(outcomes[0].tier, 1);
}

TEST(SolveOwner, anotherCircleOfTheSameSketchIsNoStructuralCandidate)
{
    // ops#173: one pocket (41) cut two holes from circles g1 and g2 of its sketch (40); g1 is
    // deleted. Hole 2's bottom circle, 14 mm away, has the maker and shares the block's face, so
    // it was tier 1's only survivor and resolved silently. It lost the old circle's source:
    // broken, with it ranked.
    auto circle = [](double x) {
        const Base::Vector3d axis(0, 0, 1);
        const double length = 4 * std::numbers::pi;
        return fingerprint('E', "Circle", length, Base::Vector3d(x, 10, 0), axis, {2.0});
    };
    SolveInput input;
    input.diagonal = 40.0;
    input.guess = true;
    input.guessNoStructure = true;
    input.pool["Edge"] = {element("Edge12", {holeBottomCircle(40, 41, 2)})};
    measure(input, {{"Edge12", circle(22)}}, nullptr);
    input.entries = {missing(holeBottomCircle(40, 41, 1), "Edge")};
    input.entries[0].fingerprint = circle(8);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U)
        << outcomes[0].evidence;
    EXPECT_NE(outcomes[0].evidence.find("tier 1's 1 survivor lost the old element's source"),
              std::string::npos)
        << outcomes[0].evidence;
    ASSERT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge12"}));
    EXPECT_NEAR(outcomes[0].candidateDistances.front(), 14.0, 1e-9);
    //   without a saved fingerprint: no candidate, never resolved
    input.entries[0].fingerprint = ElementFingerprint();
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "no candidate; tier 1's 1 survivor lost the old element's source");
    //   without T1': the silent tier-1 resolution onto the other hole
    input.entries[0].fingerprint = circle(8);
    input.sameSource = false;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge12");
    EXPECT_EQ(outcomes[0].tier, 1);
    //   within G2's reach (1.5 mm), the same sketch and maker: policy D's warned guess
    input.sameSource = true;
    measure(input, {{"Edge12", circle(9.5)}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].guessKind, "geometric");
}

TEST(SolveOwner, keptSourcesStayStructural)
{
    // T1' keeps what still has the old element's sources: a piece of the old circle (a later
    // section on the same name), whatever its sources. The keep path of lostASource() is
    // blockProfileRedrawnKeepsTheHoleCircle's.
    const auto old = holeBottomCircle(40, 41, 1);
    auto circle = [](double x) {
        const Base::Vector3d axis(0, 0, 1);
        return fingerprint('E', "Circle", 4 * std::numbers::pi, Base::Vector3d(x, 10, 0), axis, {2.0});
    };
    SolveInput input;
    input.diagonal = 40.0;
    input.pool["Edge"] = {
        element("Edge5", {piece(old, 90, "FUS", 1, 'E', {sketchEdge(9)})}),
        element("Edge12", {holeBottomCircle(40, 41, 2)}),
    };
    measure(input, {{"Edge5", circle(8)}, {"Edge12", circle(22)}}, nullptr);
    input.entries = {missing(old, "Edge")};
    input.entries[0].fingerprint = circle(8);
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);  // a split under One
    EXPECT_EQ(outcomes[0].evidence.rfind("split into 1 pieces", 0), 0U) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].candidates.front(), "Edge5");
}

namespace
{

// A hole's bottom circle as holeBottomCircle(), cut from a block face drawn by \a blockLines of
// sketch 5 and the cylinder of edge \a geoId of sketch 40 (\a cylinderSources added).
std::string holeCircleOn(const std::vector<int>& blockLines,
                         int geoId,
                         const std::vector<std::string>& cylinderSources = {})
{
    std::vector<std::string> edges;
    for (int line : blockLines) {
        edges.push_back(sketchEdge(line));
    }
    std::vector<std::string> sources {sketchEdge(geoId, 40)};
    sources.insert(sources.end(), cylinderSources.begin(), cylinderSources.end());
    return generated({lowFace(edges), generated(sources, 41, "XTR", 'F')}, 41, "CUT", 'E');
}

}  // namespace

TEST(SolveOwner, blockProfileRedrawnKeepsTheHoleCircle)
{
    // PR 149's review (Medium 1): T1' asks only for the sources of the inputs the old element's
    // maker made itself, the hole's cylinder (41, from g1 of the hole's sketch 40), not those of
    // the block's face it cut. The block's profile redrawn, one line (g9 for g1) or all of them
    // (g9..g12), the hole's circle keeps g1 and stays tier 1's; the other hole's (g2) doesn't.
    // Requiring the face's sources too dropped the circle after a full redraw: geometry's warned
    // pick, or a break without a fingerprint.
    for (const std::vector<int>& lines : {std::vector<int> {9, 2, 3, 4}, {9, 10, 11, 12}}) {
        SolveInput input;
        input.pool["Edge"] = {
            element("Edge7", {holeCircleOn(lines, 1)}),
            element("Edge12", {holeCircleOn(lines, 2)}),
        };
        input.entries = {missing(holeCircleOn({1, 2, 3, 4}, 1), "Edge")};
        auto outcome = Data::solveOwner(input)[0];
        EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
        EXPECT_EQ(outcome.element, "Edge7");
        EXPECT_EQ(outcome.tier, 1);
    }
}

TEST(SolveOwner, unknownSourceKeepsTheOthersRequired)
{
    // PR 149's review (Medium 2): a source without a reference ID beside the hole's circle is
    // left out; the circle (g1) is still required. Before, one unknown source turned T1' off and
    // the other hole's circle (g2) was tier 1's silently.
    const auto unknown = section({}, {}, 7, "XTR", 0, 'E', {});
    SolveInput input;
    input.pool["Edge"] = {element("Edge12", {holeCircleOn({1, 2, 3, 4}, 2, {unknown})})};
    input.entries = {missing(holeCircleOn({1, 2, 3, 4}, 1, {unknown}), "Edge")};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken);
    EXPECT_EQ(outcome.evidence, "no candidate; tier 1's 1 survivor lost the old element's source");
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge12"}));
    //   only unknown sources on the old name: T1' can't judge, tier 1 decides. Deliberate
    //   (ops#183): the silent tier-1 resolution is the behaviour before T1', which can only drop
    //   a candidate for a source the old name is known to have.
    auto onUnknownFace = [&](const std::string& cylinderSource) {
        return generated({lowFace({unknown}), generated({cylinderSource}, 41, "XTR", 'F')},
                         41,
                         "CUT",
                         'E');
    };
    input.pool["Edge"] = {element("Edge12", {onUnknownFace(sketchEdge(2, 40))})};
    input.entries = {missing(onUnknownFace(unknown), "Edge")};
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge12");
}

TEST(SolveOwner, anotherMakerBelowTheBandIsNotListed)
{
    // PR 149's review (Medium 3): another maker's elements are measured against the band of the
    // best of both sets, as before T1 left them out. The pad's bottom edge (7) shares only a
    // sketch line with the old circle, far below the other hole's circle: it is no tier-1
    // survivor, so it is neither evidence nor listed. Measured against its own set's best, it
    // was both.
    SolveInput input;
    input.pool["Edge"] = {
        element("Edge1", {generated({sketchEdge(1)}, 7, "XTR", 'E')}),
        element("Edge12", {holeBottomCircle(40, 41, 2)}),
    };
    input.entries = {missing(holeBottomCircle(40, 41, 1), "Edge")};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken);
    EXPECT_EQ(outcome.evidence, "no candidate; tier 1's 1 survivor lost the old element's source");
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge12"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"other source"}));
}

TEST(SolveOwner, anotherMakerEvictsNoSameMakerSurvivor)
{
    // ops#174: T1 runs before tier 1's band. The old circle (maker 41) is cut from a face three
    // features deep; Edge8, another maker's (71), shares that whole face (overlap 0.9), Edge5,
    // the maker's own, only the face's sketch lines and the hole's cylinder (0.6). With the band
    // first, Edge8 evicted Edge5 and T1 then dropped Edge8: no candidate. Now Edge5 is tier 1's.
    std::string face = lowFace({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)});
    for (int tag : {6, 7, 8}) {
        face = generated({face}, tag, "XTR", 'F');
    }
    const auto cylinder = generated({sketchEdge(1, 40)}, 41, "XTR", 'F');
    const auto old = generated({face, cylinder}, 41, "CUT", 'E');
    SolveInput input;
    input.pool["Edge"] = {
        element("Edge5",
                {generated({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4), cylinder},
                           41,
                           "CUT",
                           'E')}),
        element("Edge8",
                {generated({face, generated({sketchEdge(1, 40)}, 71, "XTR", 'F')}, 71, "CUT", 'E')}),
    };
    input.entries = {missing(old, "Edge")};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge5");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, makerChangedByAReorderStaysInTheLineage)
{
    // ops#174: two pads' junction edge, generated by Pad2 (21) from both pads' faces; a reorder
    // makes Pad1 (11) generate it. The maker changed, but the old one is in its lineage, through
    // Pad2's face, and the sources are the same: tier 1 takes it.
    const auto face1 = generated({sketchEdge(1, 10)}, 11, "XTR", 'F');
    const auto face2 = generated({sketchEdge(1, 20)}, 21, "XTR", 'F');
    SolveInput input;
    input.pool["Edge"] = {element("Edge4", {generated({face2, face1}, 11, "FUS", 'E')})};
    input.entries = {missing(generated({face1, face2}, 21, "FUS", 'E'), "Edge")};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge4");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, featureInsertedUpstreamKeepsTheMakerAndSources)
{
    // ops#174: a feature (9) inserted before Pad2 modifies Pad1's face, so Pad2's junction edge
    // links the modified face: the same maker and sources, a later section inside a linked name.
    const auto face1 = generated({sketchEdge(1, 10)}, 11, "XTR", 'F');
    const auto face2 = generated({sketchEdge(1, 20)}, 21, "XTR", 'F');
    SolveInput input;
    input.pool["Edge"] = {
        element("Edge4", {generated({piece(face1, 9, "CUT", 0, 'F'), face2}, 21, "FUS", 'E')})};
    input.entries = {missing(generated({face1, face2}, 21, "FUS", 'E'), "Edge")};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge4");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, guessThePieceAtTheSavedCentre)
{
    // G3: an edge 0..20 along X split under One. Off centre (pieces 0..6 and 8..20) the saved
    // centre x = 10 lies on the long piece: guessed, tier 1. Centred (0..9 and 11..20) it lies on
    // neither: broken (N5).
    const auto old = generated({sketchEdge(1)}, 7, "Extrude", 'E');
    auto lineX = [](double from, double to) {
        return fingerprint('E',
                           "Line",
                           to - from,
                           Base::Vector3d((from + to) / 2, 0, 10),
                           Base::Vector3d(1, 0, 0));
    };
    SolveInput input;
    input.diagonal = 30.0;
    input.guess = true;
    input.pool["Edge"] = {
        element("Edge2", {piece(old, 9, "CUT", 0, 'E')}),
        element("Edge3", {piece(old, 9, "CUT", 1, 'E')}),
    };
    input.entries = {missing(old, "Edge")};
    input.entries[0].fingerprint = lineX(0, 20);

    measure(input, {{"Edge2", lineX(0, 6)}, {"Edge3", lineX(8, 20)}}, nullptr);
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Edge3");
    EXPECT_EQ(outcomes[0].tier, 1);
    EXPECT_EQ(outcomes[0].guessKind, "piece");
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge3", "Edge2"}));
    EXPECT_EQ(outcomes[0].candidateRoles, (std::vector<std::string> {"guess", "piece"}));

    measure(input, {{"Edge2", lineX(0, 9)}, {"Edge3", lineX(11, 20)}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "split into 2 pieces");

    //   without the rule: broken at once, as before
    measure(input, {{"Edge2", lineX(0, 6)}, {"Edge3", lineX(8, 20)}}, nullptr);
    input.guess = false;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, guessThePieceOfASplitFace)
{
    // G3 on planar faces: a top face 0..20 x 0..10 split at x = 8; the saved centre (10, 5)
    // lies in the box of the piece 8..20.
    const auto old = generated({sketchEdge(1)}, 7, "Extrude", 'F');
    auto top = [](double from, double to) {
        auto fp = fingerprint('F',
                              "Plane",
                              (to - from) * 10,
                              Base::Vector3d((from + to) / 2, 5, 10),
                              Base::Vector3d(0, 0, 1));
        fp.extentMin = Base::Vector3d(from, 0, 10);
        fp.extentMax = Base::Vector3d(to, 10, 10);
        return fp;
    };
    SolveInput input;
    input.diagonal = 30.0;
    input.guess = true;
    input.pool["Face"] = {
        element("Face2", {piece(old, 9, "CUT", 0, 'F')}),
        element("Face3", {piece(old, 9, "CUT", 1, 'F')}),
    };
    input.entries = {missing(old, "Face")};
    input.entries[0].fingerprint = top(0, 20);
    measure(input, {{"Face2", top(0, 8)}, {"Face3", top(8, 20)}}, nullptr);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Face3");
    EXPECT_EQ(outcomes[0].guessKind, "piece");
}

// ---------------------------------------------------------------------------------------------
// Derived survivors (ops#335, PLAN decision 81): a candidate that holds the old name only through
// a node of another element type is geometric evidence, not tier 1's.

TEST(NameAncestry, reachClassifiesThePathTypes)
{
    using Reach = NameAncestry::Reach;
    const auto g2 = sketchEdge(2);
    const auto wallFace = generated({g2}, 7, "XTR", 'F');
    //   a section edge on the face the edge g2 generated: E<F<E
    const auto sectionEdge = generated({wallFace}, 9, "CUT", 'E');
    EXPECT_EQ(NameAncestry::reaches(sectionEdge, g2), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(sectionEdge, g2), "E<F<E");

    //   a section vertex on the edge a sketch vertex generated: V<E<V
    const auto corner = sketchVertex({"g1v2", "g2v1"});
    const auto sweptEdge = generated({corner}, 7, "XTR", 'E');
    const auto sectionVertex = section({}, {sweptEdge}, 9, "CUT", 0, 'V', {"GEN"});
    EXPECT_EQ(NameAncestry::reaches(sectionVertex, corner), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(sectionVertex, corner), "V<E<V");

    //   a pipe's cap embedding the UPP edges that bound it, which embed the profile face: F<E<F
    const auto profileFace = lowFace({sketchEdge(1), g2, sketchEdge(3), sketchEdge(4)});
    const auto capEdge = upper({profileFace}, 8, "PSH");
    const auto cap = section({}, {capEdge}, 8, "SEW", 0, 'F', {"LOW"});
    EXPECT_EQ(NameAncestry::reaches(cap, profileFace), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(cap, profileFace), "F<E<F");

    //   a Thickness's inner edge: E<F<F<E, the same-type step through the Thickness's GEN
    //   section named (ops#358)
    const auto innerFace = generated({wallFace}, 11, "THK", 'F');
    const auto innerEdge = generated({innerFace}, 11, "THK", 'E');
    EXPECT_EQ(NameAncestry::reaches(innerEdge, g2), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(innerEdge, g2), "E<F<F (THK)<E");

    //   a far-end partner: projected
    const auto topEdge = section({}, {g2}, 7, "XTR", 0, 'E', {"PRJ"});
    EXPECT_EQ(NameAncestry::reaches(topEdge, g2), Reach::Projected);
    EXPECT_EQ(NameAncestry::derivedPath(topEdge, g2), "");

    //   a piece of the edge: same-type; an edge generated from the edge, a copy at another
    //   place (an offset): derived (ops#358)
    EXPECT_EQ(NameAncestry::reaches(piece(g2, 9, "CUT", 0, 'E'), g2), Reach::SameType);
    EXPECT_EQ(NameAncestry::derivedPath(piece(g2, 9, "CUT", 0, 'E'), g2), "");
    EXPECT_EQ(NameAncestry::reaches(generated({g2}, 7, "OFF", 'E'), g2), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(generated({g2}, 7, "OFF", 'E'), g2), "E<E (OFF)");
    //   a piece of the section edge still reaches g2 only through the face
    EXPECT_EQ(NameAncestry::reaches(piece(sectionEdge, 12, "CUT", 1, 'E'), g2), Reach::Derived);

    //   a pattern copy lives in its own context: not the bare name
    EXPECT_EQ(NameAncestry::reaches(stepInstance(g2, 9, "2", 'E'), g2), Reach::None);

    //   reached both ways (a section that embeds names without generating from them, e.g. a
    //   bounding face's UPP edge): same-type wins, whichever path the walk meets first
    EXPECT_EQ(NameAncestry::reaches(section({}, {wallFace, g2}, 9, "XXX", 0, 'E', {"UPP"}), g2),
              Reach::SameType);
    EXPECT_EQ(NameAncestry::reaches(section({}, {g2, wallFace}, 9, "XXX", 0, 'E', {"UPP"}), g2),
              Reach::SameType);
    //   through a GEN section, both ways are a source: derived
    EXPECT_EQ(NameAncestry::reaches(generated({wallFace, g2}, 9, "CUT", 'E'), g2), Reach::Derived);
    //   derived and projected (a pad's section edge on its bottom: the cut face's PRJ name and
    //   the wall face): derived
    const auto farFace = section({}, {profileFace}, 7, "XTR", 0, 'F', {"PRJ"});
    EXPECT_EQ(NameAncestry::reaches(generated({farFace, wallFace}, 9, "CUT", 'E'), g2),
              Reach::Derived);
    EXPECT_EQ(NameAncestry::reaches(generated({farFace}, 9, "CUT", 'E'), g2), Reach::Projected);

    //   unrelated
    EXPECT_EQ(NameAncestry::reaches(sketchEdge(3), g2), Reach::None);
}

namespace
{

// A straight loft's bottom edge g2 (a line along Y at x = 20, z = 0, 10 long) and what a pocket
// from below leaves: the section edge on the wall face g2 made (E<F<E), the wall section of the
// opposite side (from g4), and the far cap's edge from the second profile (another sketch).
struct Loft
{
    std::string g2 = sketchEdge(2);
    std::string section2 = generated({generated({sketchEdge(2)}, 7, "LFT", 'F')}, 9, "CUT", 'E');
    std::string section4 =
        generated({generated({sketchEdge(4)}, 7, "LFT", 'F', 1)}, 9, "CUT", 'E', 1);
    std::string farEdge = generated({sketchEdge(2, 6)}, 7, "LFT", 'E', 2);
    double diagonal = 27.0;  // strict d_max 0.27, wide 1.35

    static ElementFingerprint line(double x, double z)
    {
        return fingerprint('E', "Line", 10, Base::Vector3d(x, 5, z), Base::Vector3d(0, 1, 0));
    }

    // The pool after the cut, the section edge \a z above the old edge
    SolveInput input(double z) const
    {
        SolveInput in;
        in.diagonal = diagonal;
        in.guess = true;
        in.guessNoStructure = true;
        in.pool["Edge"] = {
            element("Edge1", {section2}),
            element("Edge2", {farEdge}),
            element("Edge3", {section4}),
        };
        measure(in,
                {{"Edge1", line(20, z)}, {"Edge2", line(20, 15)}, {"Edge3", line(0, z)}},
                nullptr);
        in.entries = {missing(g2, "Edge")};
        in.entries[0].fingerprint = line(20, 0);
        return in;
    }
};

}  // namespace

TEST(SolveOwner, derivedSurvivorFarFromTheOldPlaceBreaks)
{
    // L2: the pocket cuts 8 mm: the derived edge alone survives tier 1, 8 mm up. Before ops#335
    // it was taken at tier 1 (the fillet moved 8 mm, silently).
    Loft loft;
    auto input = loft.input(8);

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    EXPECT_NEAR(outcomes[0].candidateDistances[0], 8.0, 1e-9);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U)
        << outcomes[0].evidence;
    EXPECT_NE(outcomes[0].evidence.find(
                  "tier 1's 1 survivor is in ancestry through another type (E<F<E), not at the "
                  "old place"
              ),
              std::string::npos)
        << outcomes[0].evidence;
    //   listed once
    EXPECT_EQ(std::count(outcomes[0].candidates.begin(), outcomes[0].candidates.end(), "Edge1"), 1);

    //   NamingSolver/Tier1Derived = ancestry: as before
    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    EXPECT_EQ(outcomes[0].tier, 1);
    EXPECT_NE(outcomes[0].evidence.find(", in ancestry"), std::string::npos);
}

TEST(SolveOwner, derivedSurvivorAtTheOldPlaceResolvesByGeometry)
{
    // L3: the cut 0.1 mm deep: the derived edge is within tier 3's strict d_max, resolved by
    // geometry (warned, with a record, by the batch), where it was silent before.
    Loft loft;
    auto input = loft.input(0.1);

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    EXPECT_EQ(outcomes[0].tier, 3);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3: ", 0), 0U);
    EXPECT_NE(outcomes[0].evidence.find("in ancestry through another type (E<F<E)"),
              std::string::npos);

    //   no saved fingerprint: nothing can place it; broken, the derived edge listed
    input.entries[0].fingerprint = ElementFingerprint();
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge1"}));
    EXPECT_EQ(outcomes[0].candidateRoles, (std::vector<std::string> {"derived"}));
    EXPECT_EQ(outcomes[0].evidence,
              "no candidate; tier 1's 1 survivor is in ancestry through another type (E<F<E), "
              "no saved fingerprint");
}

TEST(SolveOwner, derivedSurvivorWithinTheGuessWidthIsAGuess)
{
    // A loft cut 1 mm deep: beyond the strict d_max (0.27), within G2's (1.35), the next line
    // far: a warned guess under policy D (the derived edge shares the old edge's source).
    Loft loft;
    auto input = loft.input(1.0);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    EXPECT_EQ(outcomes[0].guessKind, "geometric");
    EXPECT_EQ(outcomes[0].tier, 3);

    //   G2 off: broken
    input.guessNoStructure = false;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");

    //   guessing off: broken
    input.guessNoStructure = true;
    input.guess = false;
    EXPECT_EQ(Data::solveOwner(input)[0].status, SolveStatus::Broken);
}

TEST(SolveOwner, derivedSurvivorTiesWithANearerUnrelatedElement)
{
    // The whole pool ranks (N8): an unrelated line 1.5 mm below the old edge ties with the
    // derived edge 1 mm above it (within G2's gap factor 2): broken, the derived edge first.
    Loft loft;
    auto input = loft.input(1.0);
    input.pool["Edge"].push_back(element("Edge4", {sketchEdge(7, 6)}));
    measure(input,
            {{"Edge1", Loft::line(20, 1)},
             {"Edge2", Loft::line(20, 15)},
             {"Edge3", Loft::line(0, 1)},
             {"Edge4", Loft::line(20, -1.5)}},
            nullptr);

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    ASSERT_GE(outcomes[0].candidates.size(), 2U);
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidates[1], "Edge4");
    EXPECT_EQ(outcomes[0].candidateRoles[1], "geometric");
}

TEST(SolveOwner, derivedSurvivorOfAnotherKindBreaks)
{
    // L1, a tapered loft: the section of the ruled face is a B-spline, the old edge a line.
    Loft loft;
    auto input = loft.input(0.1);
    auto bspline = Loft::line(20, 0.1);
    bspline.kind = "BSpline";
    bspline.direction.reset();
    measure(input, {{"Edge1", bspline}, {"Edge2", Loft::line(20, 15)}}, nullptr);
    input.pool["Edge"].pop_back();  // no other wall section

    auto outcomes = Data::solveOwner(input);

    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    EXPECT_NE(outcomes[0].evidence.find("(E<F<E), tier 2 disagrees with it"), std::string::npos)
        << outcomes[0].evidence;
}

TEST(SolveOwner, derivedVertexFarFromTheOldPlaceBreaks)
{
    // L4: a tapered loft's bottom corner (20, 0, 0), the cut 8 mm deep: the new corner on the
    // swept edge (V<E<V) is the only survivor. A vertex has no intrinsic geometry to check;
    // before ops#335 an attached sketch moved there.
    const auto corner = sketchVertex({"g1v2", "g2v1"});
    const auto sweptEdge = generated({corner}, 7, "LFT", 'E');
    const auto newCorner = section({}, {sweptEdge}, 9, "CUT", 0, 'V', {"GEN"});
    const auto otherEdge = generated({sketchVertex({"g2v2", "g3v1"})}, 7, "LFT", 'E', 1);
    const auto otherCorner = section({}, {otherEdge}, 9, "CUT", 1, 'V', {"GEN"});
    auto point = [](double x, double y, double z) {
        return fingerprint('V', "Point", {}, Base::Vector3d(x, y, z));
    };
    SolveInput input;
    input.diagonal = 27.0;
    input.guess = true;
    input.guessNoStructure = true;
    input.pool["Vertex"] = {element("Vertex1", {newCorner}), element("Vertex2", {otherCorner})};
    measure(input, {{"Vertex1", point(18.9, 0.53, 8)}, {"Vertex2", point(18.9, 9.47, 8)}}, nullptr);
    input.entries = {missing(corner, "Vertex")};
    input.entries[0].fingerprint = point(20, 0, 0);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].candidates[0], "Vertex1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    EXPECT_NE(outcomes[0].evidence.find("(V<E<V)"), std::string::npos) << outcomes[0].evidence;

    //   L5, the cut 0.1 mm deep: resolved by geometry
    measure(input, {{"Vertex1", point(20, 0.01, 0.1)}, {"Vertex2", point(20, 10, 0.1)}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Vertex1");
    EXPECT_EQ(outcomes[0].tier, 3);

    //   ancestry: tier 1, as before
    measure(input, {{"Vertex1", point(18.9, 0.53, 8)}, {"Vertex2", point(18.9, 9.47, 8)}}, nullptr);
    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Vertex1");
    EXPECT_EQ(outcomes[0].tier, 1);
}

TEST(SolveOwner, derivedElementHeldExactlyIsNotAdmitted)
{
    // Another reference holds the section edge exactly: only same-type ancestry admits it to a
    // missing entry's pool.
    Loft loft;
    auto input = loft.input(0.1);
    input.entries.push_back(exact("Edge1", "Edge"));

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[1].status, SolveStatus::Exact);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    const auto& candidates = outcomes[0].candidates;
    EXPECT_EQ(std::find(candidates.begin(), candidates.end(), "Edge1"), candidates.end());

    //   ancestry: admitted, and the merge with the exact entry resolves it
    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge1");
}

TEST(SolveOwner, derivedFromEveryProfileEdgeMergesNothing)
{
    // A section edge on a pad's start face (`FAC;F;LOW` embeds every profile edge) is derived
    // from each of them: two references to two cut-away profile edges don't both take it.
    const auto startFace = lowFace({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)});
    const auto onStart = generated({startFace}, 9, "CUT", 'E');
    SolveInput input;
    input.diagonal = 27.0;
    input.pool["Edge"] = {element("Edge1", {onStart})};
    input.entries = {missing(sketchEdge(1), "Edge"), missing(sketchEdge(2), "Edge")};

    auto outcomes = Data::solveOwner(input);
    for (const auto& outcome : outcomes) {
        EXPECT_EQ(outcome.status, SolveStatus::Broken);
        EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge1"}));
        EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"derived"}));
    }
}

TEST(SolveOwner, derivedAmongOtherSurvivorsNeedsTier3)
{
    // S5, a pad 20 x 10 x 10 whose bottom slab a pocket cuts 1 mm deep: the section edge (E<F<E)
    // and the top edge (the PRJ partner) survive tier 1; G1 picks the section edge, 1 mm away,
    // the top edge 9 mm: a guess, as before ops#335.
    Loft loft;
    const auto topEdge = section({}, {loft.g2}, 7, "XTR", 0, 'E', {"PRJ"});
    SolveInput input;
    input.diagonal = 24.5;  // strict 0.245, wide 1.225
    input.guess = true;
    input.guessNoStructure = true;
    input.pool["Edge"] = {element("Edge7", {loft.section2}), element("Edge9", {topEdge})};
    measure(input, {{"Edge7", Loft::line(20, 1)}, {"Edge9", Loft::line(20, 10)}}, nullptr);
    input.entries = {missing(loft.g2, "Edge")};
    input.entries[0].fingerprint = Loft::line(20, 0);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Edge7");
    EXPECT_EQ(outcomes[0].guessKind, "nearest");
    EXPECT_EQ(outcomes[0].candidateRoles, (std::vector<std::string> {"guess", "structural"}));

    //   S1, the slab 8 mm: ambiguous, the section edge marked
    measure(input, {{"Edge7", Loft::line(20, 8)}, {"Edge9", Loft::line(20, 10)}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "ambiguous");
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge7", "Edge9"}));
    EXPECT_EQ(outcomes[0].candidateRoles, (std::vector<std::string> {"derived", "structural"}));

    //   tier 2 alone narrowing to the section edge isn't enough: the top edge is a circle here,
    //   the section edge 8 mm away: broken
    auto circle =
        fingerprint('E', "Circle", 10, Base::Vector3d(20, 5, 10), Base::Vector3d(0, 0, 1), {2.0});
    measure(input, {{"Edge7", Loft::line(20, 8)}, {"Edge9", circle}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence,
              "Edge7 is in ancestry through another type (E<F<E), tier 3 didn't choose it, tier 2: "
              "1 of 2");
    //   ... and 0.1 mm away: tier 3 chooses it
    measure(input, {{"Edge7", Loft::line(20, 0.1)}, {"Edge9", circle}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge7");
    EXPECT_EQ(outcomes[0].tier, 3);

    //   ancestry: tier 2 took it at 8 mm
    measure(input, {{"Edge7", Loft::line(20, 8)}, {"Edge9", circle}}, nullptr);
    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge7");
    EXPECT_EQ(outcomes[0].tier, 2);
}

TEST(SolveOwner, derivedSharedByTwoMixedSetsMergesNothing)
{
    // Two references to the opposite sides g2 (x = 20) and g4 (x = 0) of a pad's profile, both
    // cut away. Each keeps its top edge (the PRJ partner) and the section edge on the start face
    // (`FAC;F;LOW` embeds every profile edge: E<F<E from each). The top edges are B-splines here,
    // so tier 2 keeps only the section edge for both, 10 mm from either old edge. A derived
    // survivor is no proven merge: the two references compete for it in the match graph, and
    // both break as ambiguous. Under ancestry the section edge was in both old names' ancestry,
    // and both merged onto it.
    const auto g2 = sketchEdge(2);
    const auto g4 = sketchEdge(4);
    const auto startFace = lowFace({sketchEdge(1), g2, sketchEdge(3), g4});
    const auto onStart = generated({startFace}, 9, "CUT", 'E');
    auto bspline = [](double x) {
        auto fp = Loft::line(x, 10);
        fp.kind = "BSpline";
        return fp;
    };
    SolveInput input;
    input.diagonal = 24.5;
    input.pool["Edge"] = {
        element("Edge1", {onStart}),
        element("Edge2", {section({}, {g2}, 7, "XTR", 0, 'E', {"PRJ"})}),
        element("Edge3", {section({}, {g4}, 7, "XTR", 0, 'E', {"PRJ"})}),
    };
    measure(input, {{"Edge1", Loft::line(10, 1)}, {"Edge2", bspline(20)}, {"Edge3", bspline(0)}}, nullptr);
    input.entries = {missing(g2, "Edge"), missing(g4, "Edge")};
    input.entries[0].fingerprint = Loft::line(20, 0);
    input.entries[1].fingerprint = Loft::line(0, 0);

    auto outcomes = Data::solveOwner(input);
    ASSERT_EQ(outcomes.size(), 2U);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "ambiguous, tier 2: 1 of 2");
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge1", "Edge2"}));
    EXPECT_EQ(outcomes[0].candidateRoles, (std::vector<std::string> {"derived", "structural"}));
    EXPECT_EQ(outcomes[1].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[1].evidence, "ambiguous, tier 2: 1 of 2");
    EXPECT_EQ(outcomes[1].candidates, (std::vector<std::string> {"Edge1", "Edge3"}));
    EXPECT_EQ(outcomes[1].candidateRoles, (std::vector<std::string> {"derived", "structural"}));

    //   ancestry: both merged onto the section edge
    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    for (const auto& outcome : outcomes) {
        EXPECT_EQ(outcome.status, SolveStatus::Resolved);
        EXPECT_EQ(outcome.element, "Edge1");
    }
}

namespace
{

// An edge whose name holds the loft's wall face (the face g2 generated) only in a later section
// (`<base>|<a MOD section embedding the face>`, e.g. where a later feature joined it to that
// face): it reaches g2 through the face (E<F<E), and its lineage and its sources are \a base's.
std::string modifiedAlongTheWall(const std::string& base)
{
    const auto wallFace = generated({sketchEdge(2)}, 7, "LFT", 'F');
    return base + "|" + section({}, {wallFace}, 9, "FUS", 0, 'E', {"MOD"});
}

}  // namespace

TEST(SolveOwner, derivedSurvivorOfAnotherMakerIsDroppedByT1)
{
    // A derived element gets no T1 exemption (PR 327's Sonnet review, 1): another sketch's edge
    // (tag 6), joined to the loft's wall face later, lacks g2's maker in its lineage. T1 drops it,
    // and the no-candidate branch decides over the whole pool: 8 mm up, broken, the evidence
    // naming another maker's survivor (not a derived one), the edge ranked with the others by
    // distance.
    Loft loft;
    auto input = loft.input(8);
    const auto joined = modifiedAlongTheWall(generated({sketchEdge(3, 6)}, 8, "XTR", 'E'));
    EXPECT_EQ(NameAncestry::reaches(joined, loft.g2), NameAncestry::Reach::Derived);
    input.pool["Edge"][0] = element("Edge1", {joined});

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U)
        << outcomes[0].evidence;
    EXPECT_NE(outcomes[0].evidence.find("; tier 1's 1 survivor has another maker"), std::string::npos)
        << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].evidence.find("through another type"), std::string::npos)
        << outcomes[0].evidence;
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "geometric");

    //   0.1 mm up: tier 3 over the pool takes it (warned, with a record, by the batch)
    measure(
        input,
        {{"Edge1", Loft::line(20, 0.1)}, {"Edge2", Loft::line(20, 15)}, {"Edge3", Loft::line(0, 0.1)}},
        nullptr
    );
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    EXPECT_EQ(outcomes[0].tier, 3);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3: ", 0), 0U)
        << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].evidence.find("through another type"), std::string::npos)
        << outcomes[0].evidence;

    //   ancestry: in the old name's ancestry, so exempt from T1: tier 1, as before ops#335
    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    EXPECT_EQ(outcomes[0].tier, 1);
}

TEST(SolveOwner, derivedSurvivorThatLostTheSourceIsDroppedByT1Prime)
{
    // ... nor a T1' exemption: an edge the loft made from g3, g2's sketch (so the maker is in its
    // lineage), joined to the wall face later, lost g2 as a source. T1' drops it: broken 8 mm up,
    // tier 3 at 0.1 mm, the evidence naming a survivor that lost the source.
    Loft loft;
    auto input = loft.input(8);
    const auto joined = modifiedAlongTheWall(generated({sketchEdge(3)}, 7, "LFT", 'E', 3));
    EXPECT_EQ(NameAncestry::reaches(joined, loft.g2), NameAncestry::Reach::Derived);
    input.pool["Edge"][0] = element("Edge1", {joined});

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3 found none", 0), 0U)
        << outcomes[0].evidence;
    EXPECT_NE(
        outcomes[0].evidence.find("; tier 1's 1 survivor lost the old element's source"),
        std::string::npos
    ) << outcomes[0].evidence;
    EXPECT_EQ(outcomes[0].evidence.find("through another type"), std::string::npos)
        << outcomes[0].evidence;
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "geometric");

    measure(
        input,
        {{"Edge1", Loft::line(20, 0.1)}, {"Edge2", Loft::line(20, 15)}, {"Edge3", Loft::line(0, 0.1)}},
        nullptr
    );
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    EXPECT_EQ(outcomes[0].tier, 3);
    EXPECT_EQ(outcomes[0].evidence.find("through another type"), std::string::npos)
        << outcomes[0].evidence;

    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    EXPECT_EQ(outcomes[0].tier, 1);
}

TEST(SolveOwner, derivedSurvivorThatIsTheIndexSource)
{
    // An edge of a map-less shape, referenced by its IDX name (`Edge3;...;MKR;...;IDX,SRC`): the
    // element still named by that IDX section under another op code also holds a section edge's
    // name on a face generated from the old edge (E<F<E). Every survivor is derived, but the IDX
    // source is evidence of its own: confirmed when tier 2 agrees, at tier 1.
    const auto oldEdge = indexed("Edge3", 4, "MKR", 'E');
    const auto onWall = generated({generated({oldEdge}, 7, "XTR", 'F')}, 9, "CUT", 'E');
    SolveInput input;
    input.diagonal = 27.0;
    input.pool["Edge"] = {
        element("Edge1", {indexed("Edge3", 4, "FUS", 'E'), onWall}),
        element("Edge2", {sketchEdge(7, 6)}),
    };
    measure(input, {{"Edge1", Loft::line(20, 0)}, {"Edge2", Loft::line(0, 0)}}, nullptr);
    input.entries = {missing(oldEdge, "Edge")};
    input.entries[0].fingerprint = Loft::line(20, 0);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    EXPECT_EQ(outcomes[0].tier, 1);
    EXPECT_NE(outcomes[0].evidence.find("index"), std::string::npos) << outcomes[0].evidence;
    EXPECT_NE(outcomes[0].evidence.find("tier 2 agrees"), std::string::npos) << outcomes[0].evidence;

    //   tier 2 disagrees (a B-spline now): the IDX source confirms nothing, and the derived
    //   element goes to the no-candidate branch: broken, listed first
    auto bspline = Loft::line(20, 0);
    bspline.kind = "BSpline";
    bspline.direction.reset();
    measure(input, {{"Edge1", bspline}, {"Edge2", Loft::line(0, 0)}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    EXPECT_NE(outcomes[0].evidence.find("(E<F<E), tier 2 disagrees with it"), std::string::npos)
        << outcomes[0].evidence;
}

TEST(SolveOwner, derivedSurvivorBesideThePiecesDoesNotCount)
{
    // The cut splits the old edge g2 in two (pieces, `g2|CUT;MOD`) and leaves a section edge on
    // the wall face (E<F<E) 8 mm up: the pieces are what is left of the old edge, under every
    // policy, and the derived edge is listed after them, as derived.
    Loft loft;
    auto half = [](double y) {
        return fingerprint('E', "Line", 5, Base::Vector3d(20, y, 0), Base::Vector3d(0, 1, 0));
    };
    SolveInput input;
    input.diagonal = loft.diagonal;
    input.pool["Edge"] = {
        element("Edge1", {piece(loft.g2, 9, "CUT", 0, 'E')}),
        element("Edge2", {piece(loft.g2, 9, "CUT", 1, 'E')}),
        element("Edge3", {loft.section2}),
    };
    measure(input, {{"Edge1", half(2.5)}, {"Edge2", half(7.5)}, {"Edge3", Loft::line(20, 8)}}, nullptr);
    input.entries = {missing(loft.g2, "Edge")};
    input.entries[0].fingerprint = Loft::line(20, 0);
    const std::vector<std::string> listed {"Edge1", "Edge2", "Edge3"};
    const std::vector<std::string> roles {"piece", "piece", "derived"};

    //   One: broken, split
    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "split into 2 pieces");
    EXPECT_EQ(outcomes[0].candidates, listed);
    EXPECT_EQ(outcomes[0].candidateRoles, roles);

    //   Expand: both pieces
    input.entries[0].policy = Data::SolvePolicy::Expand;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].elements, (std::vector<std::string> {"Edge1", "Edge2"}));
    EXPECT_EQ(outcomes[0].evidence, "split into 2 pieces, expanded");

    //   Equivalent, the pieces the same for the consumer: one of them
    input.entries[0].policy = Data::SolvePolicy::Equivalent;
    input.entries[0].equivalent = [](const std::string& a, const std::string& b) {
        return a != "Edge3" && b != "Edge3";
    };
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_TRUE(outcomes[0].element == "Edge1" || outcomes[0].element == "Edge2")
        << outcomes[0].element;
    EXPECT_NE(outcomes[0].evidence.find("2 pieces equivalent for the consumer"), std::string::npos)
        << outcomes[0].evidence;

    //   ... and not the same: broken
    input.entries[0].equivalent = [](const std::string&, const std::string&) {
        return false;
    };
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(outcomes[0].evidence, "split into 2 pieces, 2 different results for the consumer");
    EXPECT_EQ(outcomes[0].candidates, listed);
    EXPECT_EQ(outcomes[0].candidateRoles, roles);

    //   Expand and Equivalent without pieces are One: the derived edge alone breaks (L2)
    for (auto policy : {Data::SolvePolicy::Expand, Data::SolvePolicy::Equivalent}) {
        auto alone = loft.input(8);
        alone.entries[0].policy = policy;
        outcomes = Data::solveOwner(alone);
        EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
        ASSERT_FALSE(outcomes[0].candidates.empty());
        EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
        EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    }
}

TEST(SolveOwner, derivedSurvivorsInThePlural)
{
    // A stepped cut leaves two section edges on the wall face, 8 and 9 mm up: both derived
    // (E<F<E), neither at the old place.
    Loft loft;
    const auto wallFace = generated({loft.g2}, 7, "LFT", 'F');
    SolveInput input = loft.input(8);
    input.pool["Edge"] = {
        element("Edge1", {generated({wallFace}, 9, "CUT", 'E')}),
        element("Edge2", {loft.farEdge}),
        element("Edge3", {loft.section4}),
        element("Edge4", {generated({wallFace}, 9, "CUT", 'E', 1)}),
    };
    auto heights = [&input](double z1, double z4, const char* kind = "Line") {
        auto at = [kind](double z) {
            auto fp = Loft::line(20, z);
            fp.kind = kind;
            return fp;
        };
        measure(
            input,
            {{"Edge1", at(z1)},
             {"Edge2", Loft::line(20, 15)},
             {"Edge3", Loft::line(0, z1)},
             {"Edge4", at(z4)}},
            nullptr
        );
    };
    heights(8, 9);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_NE(
        outcomes[0].evidence.find(
            "; tier 1's 2 survivors are in ancestry through another "
            "type (E<F<E), none at the old place"
        ),
        std::string::npos
    ) << outcomes[0].evidence;
    ASSERT_GE(outcomes[0].candidates.size(), 2U);
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidates[1], "Edge4");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    EXPECT_EQ(outcomes[0].candidateRoles[1], "derived");

    //   both B-splines: tier 2 disagrees with them
    heights(8, 9, "BSpline");
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_NE(outcomes[0].evidence.find("(E<F<E), tier 2 disagrees with them"), std::string::npos)
        << outcomes[0].evidence;

    //   the lower one 1 mm up, within the guess width: a guess, the other listed as derived
    heights(1, 9);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    ASSERT_GE(outcomes[0].candidates.size(), 2U);
    EXPECT_EQ(outcomes[0].candidateRoles[0], "guess");
    EXPECT_EQ(outcomes[0].candidates[1], "Edge4");
    EXPECT_EQ(outcomes[0].candidateRoles[1], "derived");

    //   no saved fingerprint
    input.entries[0].fingerprint = ElementFingerprint();
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(
        outcomes[0].evidence,
        "no candidate; tier 1's 2 survivors are in ancestry through another type (E<F<E), "
        "no saved fingerprint"
    );
    EXPECT_EQ(outcomes[0].candidates, (std::vector<std::string> {"Edge1", "Edge4"}));
}

TEST(NameAncestry, reachFromATopSectionWithoutAType)
{
    // A name whose top section carries no V/E/F type (none of the fork's operations writes one;
    // designed). Without the element's type, each branch takes the type of its first typed node,
    // for the classification and for the path text alike (PR 327's Opus review, F4).
    using Reach = NameAncestry::Reach;
    // The untyped section and the edge below it generate nothing (no GEN), so the walk's type
    // alone decides between same-type and derived (a GEN section would make every node below it
    // a source, ops#358).
    const auto g2 = sketchEdge(2);
    const auto otherFace = generated({sketchEdge(7, 6)}, 7, "XTR", 'F');
    const auto fromG2 = piece(g2, 7, "CUT", 0, 'E');
    const auto untyped = [](const std::vector<std::string>& embedded) {
        return section({}, embedded, 9, "XXX", 0, '_', {"MOD"});
    };
    //   a piece of g2 below it: same-type, whatever another branch's type is
    EXPECT_EQ(NameAncestry::reaches(untyped({fromG2}), g2), Reach::SameType);
    EXPECT_EQ(NameAncestry::reaches(untyped({otherFace, fromG2}), g2), Reach::SameType);
    EXPECT_EQ(NameAncestry::derivedPath(untyped({otherFace, fromG2}), g2), "");
    //   a section edge on the face g2 generated: derived, the path from its own edge
    const auto sectionEdge = generated({generated({g2}, 7, "XTR", 'F')}, 9, "CUT", 'E');
    EXPECT_EQ(NameAncestry::reaches(untyped({otherFace, sectionEdge}), g2), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(untyped({otherFace, sectionEdge}), g2), "?<E<F<E");
    //   a face bounded by g2 (LOW, no GEN) right below the untyped top: the face's type would be
    //   the start's, and g2 below it same-type; given the element's type (an edge), derived
    const auto boundedFace = lowFace({g2, sketchEdge(3)});
    EXPECT_EQ(NameAncestry::reaches(untyped({boundedFace}), g2), Reach::SameType);
    EXPECT_EQ(NameAncestry::reaches(untyped({boundedFace}), g2, 'E'), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(untyped({boundedFace}), g2, 'E'), "?<F<E");
    EXPECT_EQ(NameAncestry::reaches(untyped({fromG2}), g2, 'E'), Reach::SameType);
    EXPECT_EQ(NameAncestry::reaches(untyped({otherFace, sectionEdge}), g2, 'E'), Reach::Derived);
}

TEST(SolveOwner, derivedSurvivorUnderATopSectionWithoutAType)
{
    // ops#359: an edge whose name's top section has no type embeds a face bounded by g2 (E<F<E
    // through an untyped section; neither section generates, so no GEN makes the path derived,
    // ops#358). The walk takes the edge type from the pool, so the edge is derived: 8 mm up,
    // broken, listed first. Before, the walk took the face's type for the start, the path
    // counted as same-type, and tier 1 took the edge silently. No fork operation is known to
    // write such a name.
    Loft loft;
    auto input = loft.input(8);
    const auto boundedFace = section({}, {loft.g2}, 7, "LFT", 0, 'F', {"LOW"});
    input.pool["Edge"][0] =
        element("Edge1", {section({}, {boundedFace}, 9, "XXX", 0, '_', {"MOD"})});

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    EXPECT_NE(
        outcomes[0].evidence.find(
            "in ancestry through another type (?<F<E), not at the "
            "old place"
        ),
        std::string::npos
    ) << outcomes[0].evidence;
}

// ---------------------------------------------------------------------------------------------
// Offset copies (ops#358, PLAN decision 86): a Thickness's or an offset's copy of an element is a
// same-type GEN of it at a distance. Below a GEN section a name is a source, so the copy is
// geometric evidence like ops#335's derived survivors, not tier 1's.

TEST(NameAncestry, reachThroughAGenSectionIsDerived)
{
    using Reach = NameAncestry::Reach;
    const auto corner = sketchVertex({"g1v2", "g2v1"});
    //   a pad's top corner and rim edge (PRJ) and wall (GEN from the profile edge)
    const auto topCorner = section({}, {corner}, 7, "XTR", 0, 'V', {"PRJ"});
    const auto rimEdge = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto wall = generated({sketchEdge(2)}, 7, "XTR", 'F');
    //   a Thickness's copies of them: V<V, E<E, F<F through the THK GEN section
    const auto innerCorner = generated({topCorner}, 11, "THK", 'V');
    const auto innerRim = generated({rimEdge}, 11, "THK", 'E');
    const auto innerWall = generated({wall}, 11, "THK", 'F');
    EXPECT_EQ(NameAncestry::reaches(innerCorner, topCorner), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(innerCorner, topCorner), "V<V (THK)");
    EXPECT_EQ(NameAncestry::reaches(innerRim, rimEdge), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(innerRim, rimEdge), "E<E (THK)");
    EXPECT_EQ(NameAncestry::reaches(innerWall, wall), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(innerWall, wall), "F<F (THK)");
    //   the copy reaches the sketch vertex below the top corner through the projection only
    EXPECT_EQ(NameAncestry::reaches(innerCorner, corner), Reach::Projected);

    //   Part::Offset (OFS) and Offset2D (OFF), and a copy of a copy
    EXPECT_EQ(NameAncestry::derivedPath(generated({topCorner}, 13, "OFS", 'V'), topCorner),
              "V<V (OFS)");
    EXPECT_EQ(NameAncestry::derivedPath(generated({sketchEdge(2)}, 9, "OFF", 'E'), sketchEdge(2)),
              "E<E (OFF)");
    EXPECT_EQ(NameAncestry::derivedPath(generated({innerCorner}, 13, "OFS", 'V'), topCorner),
              "V<V (OFS)<V (THK)");

    //   a piece of the copy: still derived; a piece of the old element: same-type
    EXPECT_EQ(NameAncestry::reaches(piece(innerRim, 12, "CUT", 0, 'E'), rimEdge), Reach::Derived);
    EXPECT_EQ(NameAncestry::reaches(piece(innerRim, 12, "CUT", 0, 'E'), innerRim),
              Reach::SameType);
    EXPECT_EQ(NameAncestry::reaches(piece(rimEdge, 12, "CUT", 0, 'E'), rimEdge), Reach::SameType);
    //   a GEN section with a prefix (written after the source's own sections): the prefix is a
    //   source too; with MOD it stays an earlier state
    const auto prefixed = rimEdge + "|" + section({}, {}, 11, "THK", 0, 'E', {"GEN"});
    EXPECT_EQ(NameAncestry::reaches(prefixed, rimEdge), Reach::Derived);
    EXPECT_EQ(NameAncestry::derivedPath(prefixed, rimEdge), "E<E (THK)");
    EXPECT_EQ(NameAncestry::reaches(piece(rimEdge, 11, "THK", 0, 'E'), rimEdge), Reach::SameType);
    //   reached both ways, as a source and as itself: same-type wins
    EXPECT_EQ(
        NameAncestry::reaches(section({}, {innerRim, rimEdge}, 12, "XXX", 0, 'E', {"UPP"}), rimEdge),
        Reach::SameType
    );
}

namespace
{

// A pad 20 x 10 x 10 from a sketch rectangle (tag 5), a Thickness 2 mm inward with the top open
// (tag 11), and a pocket (tag 12, its sketch tag 8) that shaves the wall x = 20: the reference is
// the outer top corner (20, 0, 10), which the shave removes; the Thickness's inner corner
// (18, 2, 10) survives, 2.83 mm away (`ThicknessCornerShaved358`). Diagonal 24.5: tier 3's strict
// d_max 0.245, the guess width 1.225.
struct ThickCorner
{
    std::string corner = sketchVertex({"g1v2", "g2v1"});
    std::string topCorner = section({}, {corner}, 7, "XTR", 0, 'V', {"PRJ"});
    std::string innerCorner = generated({topCorner}, 11, "THK", 'V');
    //   the shave's corner: on the pad's wall y = 0 (from g1) and the pocket's wall
    std::string shaveCorner = section({},
                                      {generated({sketchEdge(1)}, 7, "XTR", 'F'),
                                       generated({sketchEdge(1, 8)}, 12, "XTR", 'F')},
                                      12,
                                      "CUT",
                                      0,
                                      'V',
                                      {"GEN"});
    //   an unrelated corner far away
    std::string farCorner =
        section({}, {sketchVertex({"g3v2", "g4v1"})}, 7, "XTR", 0, 'V', {"PRJ"});
    double diagonal = 24.5;

    static ElementFingerprint point(const Base::Vector3d& at)
    {
        return fingerprint('V', "Point", {}, at);
    }

    // The pool after the shave: the inner corner at \a inner, the shave's corner at \a shave
    // (none if null).
    SolveInput input(const Base::Vector3d& inner, const Base::Vector3d* shave) const
    {
        SolveInput in;
        in.diagonal = diagonal;
        in.guess = true;
        in.guessNoStructure = true;
        in.pool["Vertex"] = {element("Vertex1", {innerCorner}), element("Vertex2", {farCorner})};
        std::map<std::string, ElementFingerprint> at {
            {"Vertex1", point(inner)},
            {"Vertex2", point(Base::Vector3d(0, 10, 10))},
        };
        if (shave) {
            in.pool["Vertex"].push_back(element("Vertex3", {shaveCorner}));
            at["Vertex3"] = point(*shave);
        }
        measure(in, at, nullptr);
        in.entries = {missing(topCorner, "Vertex")};
        in.entries[0].fingerprint = point(Base::Vector3d(20, 0, 10));
        return in;
    }
};

// The role \a outcome lists \a element with, or empty.
std::string roleOf(const Data::SolveOutcome& outcome, const std::string& element)
{
    for (std::size_t i = 0; i < outcome.candidates.size(); ++i) {
        if (outcome.candidates[i] == element && i < outcome.candidateRoles.size()) {
            return outcome.candidateRoles[i];
        }
    }
    return {};
}

}  // namespace

TEST(SolveOwner, offsetCopyOfAVertexAloneFarAwayBreaks)
{
    // ops#358's repro without the shave's corner: the Thickness's inner corner, 2.83 mm away, is
    // the only survivor of tier 1. Before, tier 1 took it silently ("in ancestry").
    ThickCorner model;
    auto input = model.input(Base::Vector3d(18, 2, 10), nullptr);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates[0], "Vertex1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    EXPECT_NEAR(outcomes[0].candidateDistances[0], std::sqrt(8.0), 1e-9);
    EXPECT_NE(outcomes[0].evidence.find(
                  "tier 1's 1 survivor is in ancestry through a generated copy (V<V (THK)), not "
                  "at the old place"
              ),
              std::string::npos)
        << outcomes[0].evidence;

    //   NamingSolver/Tier1Derived = ancestry: tier 1 takes the copy, as before
    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Vertex1");
    EXPECT_EQ(outcomes[0].tier, 1);
}

TEST(SolveOwner, offsetCopyOfAVertexWithTheShaveCornerNearIsAGuess)
{
    // ops#358's repro (decision 86 Q2): the shave's own corner 0.5 mm away, within the guess
    // width, shares the profile sketch as a source and the pad as the maker: policy D's warned
    // guess; the inner corner listed as derived.
    ThickCorner model;
    const Base::Vector3d shave(19.5, 0, 10);
    auto input = model.input(Base::Vector3d(18, 2, 10), &shave);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Vertex3");
    EXPECT_EQ(outcomes[0].tier, 3);
    EXPECT_EQ(roleOf(outcomes[0], "Vertex1"), "derived");

    //   the shave from x = 18.5 (`...Wide`): its corner 1.5 mm away, beyond the width: broken,
    //   the inner corner first
    const Base::Vector3d wide(18.5, 0, 10);
    input = model.input(Base::Vector3d(18, 2, 10), &wide);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates[0], "Vertex1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");

    //   a 0.5 mm wall (`...Half`): the copy 0.71 mm away and the shave's corner 0.5 mm, both
    //   within the width and within the gap factor: broken
    input = model.input(Base::Vector3d(19.5, 0.5, 10), &shave);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    EXPECT_EQ(roleOf(outcomes[0], "Vertex1"), "derived");

    //   ancestry: tier 1 takes the copy, as before
    input = model.input(Base::Vector3d(18, 2, 10), &shave);
    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Vertex1");
    EXPECT_EQ(outcomes[0].tier, 1);
}

TEST(SolveOwner, offsetCopyWithinTheStrictDistanceResolvesByGeometry)
{
    // A thin wall (decision 86 Q3): the copy 0.14 mm away, within the strict d_max (0.245),
    // nothing else near: resolved at tier 3 (warned, with a record, by the batch).
    ThickCorner model;
    auto input = model.input(Base::Vector3d(19.9, 0.1, 10), nullptr);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Vertex1");
    EXPECT_EQ(outcomes[0].tier, 3);
    EXPECT_EQ(outcomes[0].evidence.rfind("no structural candidate, tier 3: ", 0), 0U)
        << outcomes[0].evidence;
    EXPECT_NE(outcomes[0].evidence.find("in ancestry through a generated copy (V<V (THK))"),
              std::string::npos)
        << outcomes[0].evidence;
}

TEST(SolveOwner, offsetCopyOfALineEdge)
{
    // The rim edge x = 20 (a line along Y at z = 10) and its Thickness copy x = 18: parallel, so
    // intrinsically alike. Alone: broken (before: tier 1, silently). With the shave's edge
    // x = 19.5 near: a guess to it. Beside a piece of the old edge itself: the piece (the copy
    // is no tier-1 evidence).
    const auto rimEdge = section({}, {sketchEdge(2)}, 7, "XTR", 0, 'E', {"PRJ"});
    const auto innerRim = generated({rimEdge}, 11, "THK", 'E');
    const auto shaveEdge = section({},
                                   {generated({sketchEdge(2)}, 7, "XTR", 'F'),
                                    generated({sketchEdge(4, 8)}, 12, "XTR", 'F')},
                                   12,
                                   "CUT",
                                   0,
                                   'E',
                                   {"GEN"});
    auto line = [](double x) {
        return fingerprint('E', "Line", 10, Base::Vector3d(x, 5, 10), Base::Vector3d(0, 1, 0));
    };
    SolveInput input;
    input.diagonal = 24.5;
    input.guess = true;
    input.guessNoStructure = true;
    input.pool["Edge"] = {element("Edge1", {innerRim})};
    measure(input, {{"Edge1", line(18)}}, nullptr);
    input.entries = {missing(rimEdge, "Edge")};
    input.entries[0].fingerprint = line(20);

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates[0], "Edge1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    EXPECT_NE(outcomes[0].evidence.find("(E<E (THK))"), std::string::npos) << outcomes[0].evidence;

    //   the shave's edge 0.5 mm away: a guess to it
    input.pool["Edge"].push_back(element("Edge2", {shaveEdge}));
    measure(input, {{"Edge1", line(18)}, {"Edge2", line(19.5)}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Guessed);
    EXPECT_EQ(outcomes[0].element, "Edge2");
    EXPECT_EQ(roleOf(outcomes[0], "Edge1"), "derived");

    //   a piece of the old edge at its place, beside the copy: the piece
    input.pool["Edge"] = {element("Edge1", {innerRim}),
                          element("Edge3", {piece(rimEdge, 12, "CUT", 0, 'E')})};
    measure(input, {{"Edge1", line(18)}, {"Edge3", line(20)}}, nullptr);
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].element, "Edge3");
    EXPECT_NE(outcomes[0].status, SolveStatus::Broken);

    //   ancestry: the lone copy at tier 1, as before
    input.pool["Edge"] = {element("Edge1", {innerRim})};
    measure(input, {{"Edge1", line(18)}}, nullptr);
    input.derived = Data::Tier1Derived::Ancestry;
    outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Resolved);
    EXPECT_EQ(outcomes[0].element, "Edge1");
    EXPECT_EQ(outcomes[0].tier, 1);
}

TEST(SolveOwner, offsetCopyOfAFaceFacingAwayBreaks)
{
    // The wall x = 20 and its Thickness copy x = 18: the plane's normal carries its sense, so
    // tier 2 disagrees (broken before as well, as tier 1's contradicted partner); now the copy
    // is listed as derived.
    const auto wall = generated({sketchEdge(2)}, 7, "XTR", 'F');
    const auto innerWall = generated({wall}, 11, "THK", 'F');
    SolveInput input;
    input.diagonal = 24.5;
    input.guess = true;
    input.guessNoStructure = true;
    input.pool["Face"] = {element("Face1", {innerWall})};
    measure(input,
            {{"Face1",
              fingerprint('F', "Plane", 80, Base::Vector3d(18, 5, 6), Base::Vector3d(-1, 0, 0))}},
            nullptr);
    input.entries = {missing(wall, "Face")};
    input.entries[0].fingerprint =
        fingerprint('F', "Plane", 100, Base::Vector3d(20, 5, 5), Base::Vector3d(1, 0, 0));

    auto outcomes = Data::solveOwner(input);
    EXPECT_EQ(outcomes[0].status, SolveStatus::Broken);
    ASSERT_FALSE(outcomes[0].candidates.empty());
    EXPECT_EQ(outcomes[0].candidates[0], "Face1");
    EXPECT_EQ(outcomes[0].candidateRoles[0], "derived");
    EXPECT_NE(outcomes[0].evidence.find("(F<F (THK)), tier 2 disagrees with it"),
              std::string::npos)
        << outcomes[0].evidence;
}

// ---------------------------------------------------------------------------------------------
// Merged neighbours (ops#446)

namespace
{

// A refined "Transformed" pipe (tag 9) of a square (sketch 5) along a U, as TestPipe's
// testJointOfARefinedPipe builds it: each leg's side faces are generated from a profile edge
// (leg 0's carries it as its connected element, the start), and the joints at the bends are named
// after the side faces they lie on (UPP). The first bend straightened: refine merged legs 0 and 1
// into one face, which holds both names, and the first bend's joints are gone.
struct RefinedBend
{
    // The x = +2 sides (profile edge g2) and the y = -2 sides (g1) of the three legs
    std::string x0 = side(2, 0, true);
    std::string x1 = side(2, 0);
    std::string x2 = side(2, 1);
    std::string y0 = side(1, 0, true);
    std::string y1 = side(1, 0);
    std::string y2 = side(1, 1);
    // The joints at the first bend (the old names) and at the second
    std::string edge1 = upper({x1, x0}, 9, "PSH");
    std::string edge2 = upper({x1, x2}, 9, "PSH");
    std::string vertex1 = joint({x1, x0, y1, y0});
    std::string vertex2 = joint({x1, x2, y1, y2});
    // The cap edge g2 at the start
    std::string cap = sketchEdge(2);

    static std::string side(int geoId, int index, bool start = false)
    {
        const auto edge = sketchEdge(geoId);
        std::vector<std::string> connected;
        if (start) {
            connected.push_back(edge);
        }
        return section({}, {edge}, 9, "PSH", index, 'F', {"GEN"}, connected);
    }
    static std::string joint(const std::vector<std::string>& faces)
    {
        return section({}, faces, 9, "PSH", 0, 'V', {"UPP"});
    }

    // Face6 is legs 0 and 1's x = +2 side, Face3 leg 2's, Face9 the y = -2 side of all three
    // (one plane), Face4 the start cap.
    std::vector<SolveInput::Element> faces() const
    {
        return {element("Face3", {x2}),
                element("Face4", {lowFace({sketchEdge(1), cap, sketchEdge(3), sketchEdge(4)})}),
                element("Face6", {x0, x1}),
                element("Face9", {y0, y1, y2})};
    }

    // The faces each edge or vertex lies on
    static void lieOn(SolveInput& input, std::map<std::string, std::vector<std::string>> faces)
    {
        input.facesOf = [faces = std::move(faces)](const std::string& index) {
            auto it = faces.find(index);
            return it == faces.end() ? std::vector<std::string>() : it->second;
        };
    }

    // The second bend's joint edge (Edge7) and the cap edge (Edge2), with their faces; the
    // first bend's joint edge missing
    SolveInput edgeInput() const
    {
        SolveInput input;
        input.diagonal = 60.0;
        input.pool["Edge"] = {element("Edge2", {cap}), element("Edge7", {edge2})};
        input.faces = faces();
        lieOn(input, {{"Edge2", {"Face4", "Face6"}}, {"Edge7", {"Face3", "Face6"}}});
        input.entries = {missing(edge1, "Edge")};
        return input;
    }
};

// A line along y, 4 long, centred at x = 2, y = 0 and \a z
ElementFingerprint jointLine(double z)
{
    return fingerprint('E', "Line", 4, Base::Vector3d(2, 0, z), Base::Vector3d(0, 1, 0));
}

}  // namespace

TEST(SolveOwner, mergedNeighboursDropTheOtherBendsJoint)
{
    // The first bend's joint is gone: Face6 holds both of its faces. The second bend's joint
    // shares Face6 (x1) and the profile edge with it (overlap 0.50) and keeps its maker and
    // sources, so tier 1 took it, 20 mm away and silently. It lies on Face3 too, which holds
    // none of the old joint's faces: it is dropped and listed last, before the cap edge (the
    // sketch's, another maker).
    RefinedBend b;
    auto input = b.edgeInput();
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence,
              "no candidate; tier 1's 1 survivor has another maker; tier 1's 1 survivor lies off "
              "the old element's faces (Face6 holds 2 of them)");
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge7", "Edge2"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"other faces", "other maker"}));

    //   with the saved line: tier 3 finds nothing at its place, the break says why
    input.entries[0].fingerprint = jointLine(30);
    measure(input, {{"Edge2", jointLine(0)}, {"Edge7", jointLine(50)}}, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3 found none", 0), 0U)
        << outcome.evidence;
    EXPECT_NE(outcome.evidence.find("(Face6 holds 2 of them)"), std::string::npos)
        << outcome.evidence;

    //   without the target's faces (the test off): tier 1's pick, as before ops#446
    input.faces.clear();
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge7");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, mergedNeighboursDropTheOtherBendsJointVertex)
{
    // The joint vertex on four faces, merged pairwise (Face6, and Face9 which was one plane
    // already): the second bend's vertex shares Face6 and Face9 but lies on Face3 as well.
    RefinedBend b;
    SolveInput input;
    input.diagonal = 60.0;
    input.pool["Vertex"] = {element("Vertex5", {b.vertex2})};
    input.faces = b.faces();
    RefinedBend::lieOn(input, {{"Vertex5", {"Face3", "Face6", "Face9"}}});
    input.entries = {missing(b.vertex1, "Vertex")};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence,
              "no candidate; tier 1's 1 survivor lies off the old element's faces (Face6 holds 2 "
              "of them, Face9 holds 2 of them)");
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"other faces"}));

    input.faces.clear();
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex5");
}

TEST(SolveOwner, mergedNeighboursKeepTheVertexAtTheMergedCorner)
{
    // A vertex of four faces A, B, C, D, of which A and B became one face (Face6): the vertex
    // still sits at the corner of {AB, C, D}, now named after A, C and D. It lies on old faces
    // only, so it stays tier 1's, silently, as before.
    auto face = [](int geoId) {
        return generated({sketchEdge(geoId)}, 9, "XTR", 'F');
    };
    const auto a = face(1);
    const auto b = face(2);
    const auto c = face(3);
    const auto d = face(4);
    SolveInput input;
    input.diagonal = 60.0;
    input.pool["Vertex"] = {element("Vertex2", {RefinedBend::joint({a, c, d})})};
    input.faces = {element("Face6", {a, b}), element("Face7", {c}), element("Face8", {d})};
    RefinedBend::lieOn(input, {{"Vertex2", {"Face6", "Face7", "Face8"}}});
    input.entries = {missing(RefinedBend::joint({a, b, c, d}), "Vertex")};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex2");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, mergedNeighboursChangeNothingWithoutAMerge)
{
    // The old joint's faces are two faces still (Face5 and Face6): whatever made its name go
    // missing, the test doesn't apply, and the outcome is the one without the target's faces.
    RefinedBend b;
    auto input = b.edgeInput();
    input.faces = {element("Face3", {b.x2}), element("Face5", {b.x0}), element("Face6", {b.x1})};
    input.entries[0].fingerprint = jointLine(30);
    measure(input, {{"Edge2", jointLine(0)}, {"Edge7", jointLine(50)}}, nullptr);
    const auto with = Data::solveOwner(input)[0];
    input.faces.clear();
    const auto without = Data::solveOwner(input)[0];
    EXPECT_EQ(describe(with), describe(without));
    EXPECT_EQ(with.candidateRoles, without.candidateRoles);
    EXPECT_EQ(with.status, SolveStatus::Resolved);
    EXPECT_EQ(with.element, "Edge7");
}

TEST(SolveOwner, mergedNeighboursKeepAPiece)
{
    // A piece of the old joint (split by a later cut, tag 12) lies on Face6 and the cut's face
    // (Face20): it is still a piece, and an expanding reference takes it; the other bend's joint
    // doesn't count beside it.
    RefinedBend b;
    auto input = b.edgeInput();
    input.pool["Edge"].push_back(element("Edge11", {piece(b.edge1, 12, "CUT", 0, 'E')}));
    RefinedBend::lieOn(input,
                       {{"Edge2", {"Face4", "Face6"}},
                        {"Edge7", {"Face3", "Face6"}},
                        {"Edge11", {"Face6", "Face20"}}});
    input.entries[0].policy = Data::SolvePolicy::Expand;
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge11");
    EXPECT_EQ(outcome.elements, (std::vector<std::string> {"Edge11"}));
}

TEST(SolveOwner, mergedNeighboursDropASeam)
{
    // All three legs' x = +2 sides are one face (Face6): the second bend's joint survives as a
    // seam of it, on Face6 alone. An edge on one face is no element between two: dropped.
    RefinedBend b;
    auto input = b.edgeInput();
    input.faces = {element("Face6", {b.x0, b.x1, b.x2})};
    RefinedBend::lieOn(input, {{"Edge2", {"Face4", "Face6"}}, {"Edge7", {"Face6"}}});
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"other faces", "other maker"}));
}

TEST(SolveOwner, mergedNeighboursLeavePolicyD)
{
    // A short middle leg: the other bend's joint 2 mm away, within G2's reach (5 % of the
    // 60 mm diagonal) but not tier 3's (1 %). It is dropped from tier 1, and G2 takes it as a
    // warned guess, the same source and maker (policy D, decision 20, unchanged).
    RefinedBend b;
    auto input = b.edgeInput();
    input.guess = true;
    input.guessNoStructure = true;
    input.entries[0].fingerprint = jointLine(30);
    measure(input, {{"Edge2", jointLine(0)}, {"Edge7", jointLine(32)}}, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Guessed) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge7");
    EXPECT_EQ(outcome.guessKind, "geometric");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_EQ(outcome.evidence.rfind("guess: no structural candidate, redrawn in the same source", 0),
              0U)
        << outcome.evidence;
}

TEST(SolveOwner, mergedNeighboursNeverNarrowToAPick)
{
    // Fork PR 361 round 2 (a Round corner pipe): the y = -2 side was one plane when the pipe was
    // saved (Face9 holds y0, y1, y2), so the test is armed whatever the edit. Two survivors share
    // x1 and y1 with the old joint vertex. One lies on Face3 too (x2: not the old vertex's), the
    // other on Face6 and Face9 only, both holders: it fits. Narrowing to it would make tier 1's
    // pick of what is a tie (round 1: Vertex8, 20 mm away, silently). Both stay: ambiguous.
    RefinedBend b;
    const std::string x3 = RefinedBend::side(2, 2);
    const std::string y3 = RefinedBend::side(1, 2);
    SolveInput input;
    input.diagonal = 60.0;
    input.pool["Vertex"] = {element("Vertex5", {b.vertex2}),
                            element("Vertex8", {RefinedBend::joint({b.x1, x3, b.y1, y3})})};
    input.faces = {element("Face3", {b.x2}),
                   element("Face6", {b.x0, b.x1}),
                   element("Face9", {b.y0, b.y1, b.y2})};
    RefinedBend::lieOn(input,
                       {{"Vertex5", {"Face3", "Face6", "Face9"}}, {"Vertex8", {"Face6", "Face9"}}});
    input.entries = {missing(b.vertex1, "Vertex")};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("ambiguous", 0), 0U) << outcome.evidence;
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Vertex5", "Vertex8"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"structural", "structural"}));

    //   the same without the target's faces
    input.faces.clear();
    const auto without = Data::solveOwner(input)[0];
    EXPECT_EQ(describe(outcome), describe(without));
}

TEST(SolveOwner, mergedNeighboursArmedByAFaceNoneHolds)
{
    // Fork PR 361 round 2 (a round profile): the legs' cylinders merged into one that keeps leg
    // 0's name only (Face6 holds x0); leg 1's name x1 is on no face. The other bend's joint
    // circle shares x1 with the old one and lies on Face6 and leg 2's Face3, which holds none of
    // the old joint's faces: dropped.
    RefinedBend b;
    auto input = b.edgeInput();
    input.faces = {element("Face3", {b.x2}), element("Face6", {b.x0})};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence,
              "no candidate; tier 1's 1 survivor has another maker; tier 1's 1 survivor lies off "
              "the old element's faces (1 of them is on no face)");
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge7", "Edge2"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"other faces", "other maker"}));

    //   both faces held, one each: not armed, tier 1's pick as before
    input.faces = {element("Face3", {b.x2}), element("Face5", {b.x0}), element("Face6", {b.x1})};
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge7");
}

TEST(SolveOwner, mergedNeighboursSamePlaceAmongTheDropped)
{
    // Fork PR 361 round 2 (a Round corner pipe's last leg dropped and put back: the counter
    // names move): the only survivor lies off the old element's faces but sits where it sat.
    // Over the whole pool tier 3 finds nothing (another element 0.4 mm away, within d_max);
    // among the dropped it takes the survivor, as tier 3 does, with its warning.
    RefinedBend b;
    auto input = b.edgeInput();
    input.pool["Edge"].push_back(element("Edge9", {sketchEdge(7)}));
    input.entries[0].fingerprint = jointLine(30);
    measure(input,
            {{"Edge2", jointLine(0)}, {"Edge7", jointLine(30)}, {"Edge9", jointLine(30.4)}},
            nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge7");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3 among tier 1's survivors "
                                     "off the old element's faces: nearest 0.000",
                                     0),
              0U)
        << outcome.evidence;

    //   the survivor 20 mm away: the whole pool decides, as before (the other element, alone
    //   within d_max now)
    measure(input,
            {{"Edge2", jointLine(0)}, {"Edge7", jointLine(50)}, {"Edge9", jointLine(30.4)}},
            nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge9");
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3: nearest 0.400", 0), 0U)
        << outcome.evidence;
}

TEST(SolveOwner, mergedNeighboursReadATrimmedJoint)
{
    // ops#454 step 0: the old joint trimmed by a later Pocket (tag 11), its name the joint's
    // with a MOD section after it. The test reads the making section, so the other bend's
    // trimmed joint, which lies on Face3 too, is dropped as the untrimmed one is.
    RefinedBend b;
    auto input = b.edgeInput();
    input.pool["Edge"] = {element("Edge2", {b.cap}),
                          element("Edge7", {piece(b.edge2, 11, "CUT", 0, 'E')})};
    input.entries = {missing(piece(b.edge1, 11, "CUT", 0, 'E'), "Edge")};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    ASSERT_FALSE(outcome.candidateRoles.empty());
    EXPECT_EQ(outcome.candidates.front(), "Edge7");
    EXPECT_EQ(outcome.candidateRoles.front(), "other faces");

    //   without the target's faces: tier 1's pick, 20 mm away
    input.faces.clear();
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge7");
    EXPECT_EQ(outcome.tier, 1);
}

// ---------------------------------------------------------------------------------------------
// A missing generator (ops#454)

namespace
{

// RefinedBend with a refined Pocket (tag 11) of a circle (sketch 7, g1) whose centre is on the
// first bend's joint edge: the hole's vertices on the joint are generated from the joint edge
// and the hole's cylinder, the seam vertices from the cylinder's seam (refine names it after
// its face) and the joint edge. The first bend straightened: the joint is gone, and the hole on
// the merged face (Face6) is one circle (Edge12) with one vertex, the seam vertex (Vertex10).
struct HoledBend: RefinedBend
{
    std::string cyl = generated({sketchEdge(1, 7)}, 11, "XTR", 'F');
    std::string seam = section({}, {cyl}, 0, "RFI", 0, 'E', {"UPP"});
    // The old hole vertex and seam vertex on the joint, and the seam vertex now
    std::string hole1 = generated({edge1, cyl}, 11, "CUT", 'V');
    std::string seam1 = generated({seam, edge1}, 11, "CUT", 'V');
    std::string seamNow = generated({seam, x0}, 11, "CUT", 'V');

    // The faces, the hole's cylinder (Face10) among them, and the edges: the circle on the
    // merged face and the seam; no edge holds the joint
    SolveInput input(const std::string& oldName) const
    {
        SolveInput input;
        input.diagonal = 60.0;
        input.faces = faces();
        input.faces.push_back(element("Face10", {cyl}));
        input.pool["Edge"] = {element("Edge12", {generated({cyl, x0}, 11, "CUT", 'E')}),
                              element("Edge21", {seam})};
        input.pool["Vertex"] = {element("Vertex10", {seamNow})};
        lieOn(input, {{"Vertex10", {"Face6", "Face10"}}});
        input.entries = {missing(oldName, "Vertex")};
        return input;
    }
    // Another vertex nearby, of a later feature (tag 13): no survivor of tier 1
    static SolveInput::Element other()
    {
        return element("Vertex15", {generated({sketchVertex({"g1v1"}, 8)}, 13, "XTR", 'V')});
    }
};

ElementFingerprint point(double x, double y, double z)
{
    return fingerprint('V', "Point", {}, Base::Vector3d(x, y, z));
}

}  // namespace

TEST(SolveOwner, missingGeneratorDropsTheHoleVertex)
{
    // The hole vertex was the point where the joint edge entered the hole. The seam vertex
    // shares the merged face, the cylinder and their sources with it (overlap 0.57), the maker
    // and the hole's circle, so tier 1 took it, 1 mm away and silently. The joint's faces are
    // one face and no edge holds the joint: no vertex can be that point.
    HoledBend h;
    auto input = h.input(h.hole1);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence,
              "no candidate; tier 1's 1 survivor lacks the old element's generator (an edge named "
              "after its faces, which no edge holds; Face6 holds 2 of them)");
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Vertex10"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"other generator"}));

    //   without the target's faces, or without its edges (the test off): tier 1's pick
    input.faces.clear();
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.tier, 1);
    input = h.input(h.hole1);
    input.pool.erase("Edge");
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
}

TEST(SolveOwner, missingGeneratorNeedsTheBoundaryChanged)
{
    // The joint's faces are two faces still (Face5, Face6): its boundary is there, whatever
    // made the edge go missing. Not armed: tier 1's pick, as before.
    HoledBend h;
    auto input = h.input(h.hole1);
    input.faces = {element("Face3", {h.x2}),
                   element("Face5", {h.x1}),
                   element("Face6", {h.x0}),
                   element("Face10", {h.cyl})};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, missingGeneratorLeavesAHeldGenerator)
{
    // The faces merged, but an edge holds the joint, trimmed by a later cut (tag 12): the
    // generator is there, so MG leaves it. The seam vertex isn't made from it: the held-generator
    // test drops it (ops#467), with its own evidence.
    HoledBend h;
    auto input = h.input(h.hole1);
    input.pool["Edge"].push_back(element("Edge4", {piece(h.edge1, 12, "CUT", 0, 'E')}));
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence,
              "no candidate; tier 1's 1 survivor isn't made from the old element's generator (an "
              "edge, which Edge4 holds)");
}

TEST(SolveOwner, missingGeneratorThenTier3InPlace)
{
    // The old seam vertex on the joint: the seam vertex now sits where it sat (the circle's
    // seam, by the sketch's parametrisation), and another vertex 1 mm off. Tier 1 took the
    // seam vertex silently, right by coincidence; now tier 3 at the same place takes it, which
    // the batch warns of: the element exists for another reason now.
    HoledBend h;
    auto input = h.input(h.seam1);
    input.pool["Vertex"].push_back(h.other());
    input.entries[0].fingerprint = point(2, 0.5, 30);
    measure(input, {{"Vertex10", point(2, 0.5, 30)}, {"Vertex15", point(2, -0.5, 30)}}, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.tier, 3) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3: nearest 0.000", 0), 0U)
        << outcome.evidence;
}

TEST(SolveOwner, missingGeneratorThenPolicyD)
{
    // The old hole vertex with its saved place: the seam vertex 1 mm off, beyond tier 3's
    // reach (1 % of the 60 mm diagonal), within G2's (5 %). Another vertex 2.2 mm off: not 3
    // times the nearest, so no guess; the entry breaks with the candidates by distance, the
    // dropped survivor listed once.
    HoledBend h;
    auto input = h.input(h.hole1);
    input.guess = true;
    input.guessNoStructure = true;
    input.pool["Vertex"].push_back(h.other());
    input.entries[0].fingerprint = point(2, -0.5, 30);
    measure(input, {{"Vertex10", point(2, 0.5, 30)}, {"Vertex15", point(2, -0.5, 32.2)}}, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3 found none: ", 0), 0U)
        << outcome.evidence;
    EXPECT_NE(outcome.evidence.find("lacks the old element's generator"), std::string::npos)
        << outcome.evidence;
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Vertex10", "Vertex15"}));
    ASSERT_EQ(outcome.candidateDistances.size(), 2U);
    EXPECT_NEAR(outcome.candidateDistances[0], 1.0, 1e-9);
    EXPECT_NEAR(outcome.candidateDistances[1], 2.2, 1e-9);

    //   the other vertex 4 mm off: G2's warned pick, the same source and maker (policy D)
    measure(input, {{"Vertex10", point(2, 0.5, 30)}, {"Vertex15", point(2, -0.5, 34)}}, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Guessed) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.guessKind, "geometric");
}

TEST(SolveOwner, missingGeneratorKeepsAPiece)
{
    // A piece of the old hole vertex (a later Fillet's, tag 12) is no survivor the test drops:
    // an expanding reference takes it, and the seam vertex doesn't count beside it.
    HoledBend h;
    auto input = h.input(h.hole1);
    input.pool["Vertex"].push_back(element("Vertex20", {piece(h.hole1, 12, "FLT", 0, 'V')}));
    input.entries[0].policy = Data::SolvePolicy::Expand;
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex20");
    EXPECT_EQ(outcome.elements, (std::vector<std::string> {"Vertex20"}));
}

// ---------------------------------------------------------------------------------------------
// The exact place (ops#394) and a held generator (ops#467)

namespace
{

// A long board's top edges (ops#394): 3600 along x, 45 apart in y, at z = 235, the target's
// diagonal 5000 (d_max 50). The old edge's sketch line was deleted and drawn again, so no name
// relates it to the pool (another geometry ID in its sketch). Drawn in another sketch instead,
// it comes from another source (ops#503 D1: XP's source condition).
struct LongBoard
{
    std::string oldEdge = section({}, {sketchEdge(1)}, 7, "XTR", 0, 'E', {"PRJ"});
    std::string redrawn = section({}, {sketchEdge(9)}, 7, "XTR", 0, 'E', {"PRJ"});
    std::string otherSide = section({}, {sketchEdge(3)}, 7, "XTR", 0, 'E', {"PRJ"});
    std::string otherSketch = section({}, {sketchEdge(9, 6)}, 7, "XTR", 0, 'E', {"PRJ"});

    static ElementFingerprint edgeAt(double y, double length = 3600, double x = 1800)
    {
        return fingerprint('E', "Line", length, Base::Vector3d(x, y, 235), Base::Vector3d(1, 0, 0));
    }

    // The redrawn edge (Edge2) and the board's other top edge (Edge3), measured as given
    SolveInput input(const ElementFingerprint& edge2, const ElementFingerprint& edge3) const
    {
        SolveInput input;
        input.diagonal = 5000.0;
        input.pool["Edge"] = {element("Edge2", {redrawn}), element("Edge3", {otherSide})};
        measure(input, {{"Edge2", edge2}, {"Edge3", edge3}}, nullptr);
        input.entries = {missing(oldEdge, "Edge")};
        input.entries[0].fingerprint = edgeAt(0);
        return input;
    }
};

}  // namespace

TEST(SolveOwner, exactPlaceBeatsTheGapTest)
{
    // The board's top edge drawn again where it was: the other top edge lies 45 mm away, within
    // d_max, and tier 3's gap test broke the reference. The one element at the saved place, with
    // the saved size, is the element.
    LongBoard b;
    auto input = b.input(LongBoard::edgeAt(0), LongBoard::edgeAt(45));
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge2");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_EQ(outcome.evidence,
              "no structural candidate, at the same place: nearest 0.000, second 45.000, d_max "
              "50.000");

    //   the switch off: tier 3's gap test alone, as before
    input.exactPlace = false;
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3 found none: nearest 0.000, "
                                     "second 45.000, d_max 50.000",
                                     0),
              0U)
        << outcome.evidence;
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge2", "Edge3"}));
}

TEST(SolveOwner, exactPlaceNeedsTheSize)
{
    // At the saved centre but 1 % longer: not the element as it was; the gap test decides, and
    // breaks as before.
    LongBoard b;
    auto input = b.input(LongBoard::edgeAt(0, 3636), LongBoard::edgeAt(45));
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3 found none", 0), 0U)
        << outcome.evidence;
}

TEST(SolveOwner, exactPlaceLeavesTheGapTestAlone)
{
    // 0.3 mm from the saved centre: near, not at the place; the gap test breaks it as before.
    LongBoard b;
    auto input = b.input(LongBoard::edgeAt(0.3), LongBoard::edgeAt(45));
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3 found none", 0), 0U)
        << outcome.evidence;
}

TEST(SolveOwner, exactPlaceTieBreaks)
{
    // Two elements at the saved place with the saved size (coincident twins of a compound):
    // ambiguous, both listed as at the place.
    LongBoard b;
    auto input = b.input(LongBoard::edgeAt(0), LongBoard::edgeAt(0));
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence, "ambiguous: 2 elements at the saved place");
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge2", "Edge3"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "place"}));
}

TEST(SolveOwner, exactPlaceAmongTies)
{
    // Two survivors of tier 1 (the same sources), one at the saved place, the other 45 mm off,
    // within d_max: tier 3's gap test left them ambiguous; the one at the place is the element.
    Placed p;
    SolveInput input;
    input.diagonal = 5000.0;
    input.pool["Face"] = {
        element("Face2", {p.names.newTop}),
        element("Face10", {p.otherTop}),
    };
    input.entries = {missing(p.names.oldTop)};
    input.entries[0].fingerprint = p.top;
    measure(input, {{"Face2", p.topAt(55)}, {"Face10", p.top}}, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Face10");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_NE(outcome.evidence.find(
                  "tier 3, at the same place: nearest 0.000, second 45.000, d_max 50.000"
              ),
              std::string::npos)
        << outcome.evidence;
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Face2"}));

    //   the other 500 mm off, beyond the gap: tier 3 decides as before, with its own text
    measure(input, {{"Face2", p.topAt(510)}, {"Face10", p.top}}, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Face10");
    EXPECT_NE(outcome.evidence.find("tier 3: nearest 0.000, second 500.000"), std::string::npos)
        << outcome.evidence;

    //   both at the place: ambiguous, both listed as at the place
    measure(input, {{"Face2", p.top}, {"Face10", p.top}}, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence, "ambiguous: 2 elements at the saved place");
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "place"}));
}

TEST(SolveOwner, exactPlaceAmongTheMergedNeighbours)
{
    // Tier 3 among the survivors the merged-neighbour test dropped: the second bend's joint at
    // the saved place and a third bend's 0.4 mm off, within d_max (0.6): the one at the place.
    RefinedBend b;
    auto input = b.edgeInput();
    const auto thirdJoint = upper({b.x1, RefinedBend::side(2, 2)}, 9, "PSH");
    input.pool["Edge"].push_back(element("Edge8", {thirdJoint}));
    RefinedBend::lieOn(input,
                       {{"Edge2", {"Face4", "Face6"}},
                        {"Edge7", {"Face3", "Face6"}},
                        {"Edge8", {"Face3", "Face6"}}});
    input.entries[0].fingerprint = jointLine(30);
    measure(input,
            {{"Edge2", jointLine(0)}, {"Edge7", jointLine(30)}, {"Edge8", jointLine(30.4)}},
            nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge7");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3 among tier 1's survivors "
                                     "off the old element's faces, at the same place: nearest "
                                     "0.000, second 0.400",
                                     0),
              0U)
        << outcome.evidence;
}

TEST(SolveOwner, heldGeneratorDropsTheSeamVertex)
{
    // ops#467: the joint moved off the hole (a leg made longer) and is held, exactly, by Edge3;
    // its faces are as they were for MG's purpose. The hole vertex was where the joint entered
    // the hole; the seam vertex shares the cylinder, the merged face and their sources, the
    // maker and the circle, so tier 1 took it, 1 mm away and silently. The joint didn't
    // generate it: it is no structural candidate.
    HoledBend h;
    auto input = h.input(h.hole1);
    input.pool["Edge"].push_back(element("Edge3", {h.edge1}));
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence,
              "no candidate; tier 1's 1 survivor isn't made from the old element's generator (an "
              "edge, which Edge3 holds)");
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Vertex10"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"other generator"}));

    //   the cylinder held too (the target's faces as a pool): both generators named
    input.pool["Face"] = input.faces;
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence,
              "no candidate; tier 1's 1 survivor isn't made from the old element's generators (an "
              "edge, which Edge3 holds; a face, which Face10 holds)");

    //   without the target's edges (the test off for the joint): tier 1's pick, as before
    input = h.input(h.hole1);
    input.pool.erase("Edge");
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, heldGeneratorNeedsEveryHeldGenerator)
{
    // The old seam vertex on the joint, generated from the seam and the joint, both held. The
    // seam vertex now links the seam but not the joint: dropped, and geometry decides. It sits
    // where the old one sat (by coincidence: the seam's end is where the seam met the joint),
    // so tier 3 takes it, with the quieter warning, instead of tier 1 silently; one that had
    // moved with the seam would break (a straightened bend, ops#467's second case).
    HoledBend h;
    auto input = h.input(h.seam1);
    input.pool["Edge"].push_back(element("Edge3", {h.edge1}));
    input.pool["Vertex"].push_back(h.other());
    input.entries[0].fingerprint = point(2, 0.5, 30);
    measure(input, {{"Vertex10", point(2, 0.5, 30)}, {"Vertex15", point(2, -1.3, 30)}}, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3: nearest 0.000, second "
                                     "1.800",
                                     0),
              0U)
        << outcome.evidence;

    //   the other vertex within d_max: at the same place still
    measure(input, {{"Vertex10", point(2, 0.5, 30)}, {"Vertex15", point(2, 0.1, 30)}}, nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, at the same place: nearest 0.000",
                                     0),
              0U)
        << outcome.evidence;

    //   the seam vertex moved off with the seam, 12.9 mm: nothing at the place, a break
    measure(input,
            {{"Vertex10", point(14.9, 0.5, 30)}, {"Vertex15", point(2, -1.3, 30)}},
            nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
}

TEST(SolveOwner, heldGeneratorKeepsAContinuation)
{
    // The joint trimmed by a later cut (tag 12) is held by its piece, and the new hole vertex
    // is generated from that piece: it fits, and tier 1 takes it, not the seam vertex.
    HoledBend h;
    auto input = h.input(h.hole1);
    const auto trimmed = piece(h.edge1, 12, "CUT", 0, 'E');
    input.pool["Edge"].push_back(element("Edge4", {trimmed}));
    input.pool["Vertex"] = {element("Vertex11", {generated({trimmed, h.cyl}, 11, "CUT", 'V')})};
    RefinedBend::lieOn(input, {{"Vertex11", {"Face6", "Face10"}}});
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex11");
    EXPECT_EQ(outcome.tier, 1);

    //   beside the seam vertex: it alone is dropped
    input.pool["Vertex"].push_back(element("Vertex10", {h.seamNow}));
    RefinedBend::lieOn(input,
                       {{"Vertex10", {"Face6", "Face10"}}, {"Vertex11", {"Face6", "Face10"}}});
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex11");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, heldGeneratorKeepsAHoldersOtherName)
{
    // The merged arc (policy D's C3): the hole's arc on leg 1's side, generated from the
    // cylinder and x1, is the whole circle on the merged face now, generated from the cylinder
    // and x0. Face6 holds both legs' names, so the circle fits x1 through its holder's other
    // name, and tier 1 takes it as before.
    HoledBend h;
    auto input = h.input(generated({h.cyl, h.x1}, 11, "CUT", 'E'));
    input.entries[0].type = "Edge";
    input.pool["Face"] = input.faces;
    input.pool.erase("Vertex");
    input.pool["Edge"] = {element("Edge12", {generated({h.cyl, h.x0}, 11, "CUT", 'E')})};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge12");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, heldGeneratorLeavesAGoneGenerator)
{
    // No edge holds the joint and its faces are two faces still (MG off): nothing is held, so
    // the test doesn't act and tier 1 decides as before.
    HoledBend h;
    auto input = h.input(h.hole1);
    input.faces = {element("Face3", {h.x2}),
                   element("Face5", {h.x1}),
                   element("Face6", {h.x0}),
                   element("Face10", {h.cyl})};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(SolveOwner, heldGeneratorKeepsAPiece)
{
    // A piece of the old hole vertex (a later Fillet's) is exempt, as for MG: an expanding
    // reference takes it, and the seam vertex doesn't count beside it.
    HoledBend h;
    auto input = h.input(h.hole1);
    input.pool["Edge"].push_back(element("Edge3", {h.edge1}));
    input.pool["Vertex"].push_back(element("Vertex20", {piece(h.hole1, 12, "FLT", 0, 'V')}));
    input.entries[0].policy = Data::SolvePolicy::Expand;
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex20");
    EXPECT_EQ(outcome.elements, (std::vector<std::string> {"Vertex20"}));
}

TEST(SolveOwner, heldGeneratorSkipsPatternInstances)
{
    // In a pattern's instance the names aren't the plain linked names: the test doesn't act.
    HoledBend h;
    auto input = h.input(stepInstance(h.hole1, 14, "2", 'V'));
    input.pool["Edge"].push_back(element("Edge3", {stepInstance(h.edge1, 14, "2", 'E')}));
    input.pool["Vertex"] = {element("Vertex10", {stepInstance(h.seamNow, 14, "2", 'V')})};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.tier, 1);
}

// ---------------------------------------------------------------------------------------------
// Twins (ops#503 class D, D1): the twin clause, the twin-pick rule and the face-generator net

namespace
{

// HoledBend's hole as it crosses an edge twice (ops#503 round 2's model): the left crossing
// (hole1, Index 0) and the right one (Index 1), told apart by their place along the edge only;
// the seam vertex beside them. The places are the model's: the crossings at x = 10 -+ 0.866 on
// the edge y = 0, z = 5, their centroid at x = 10.
struct CrossedEdge: HoledBend
{
    std::string right = generated({edge1, cyl}, 11, "CUT", 'V', 1);

    static ElementFingerprint at(double x)
    {
        return point(x, 0, 5);
    }
    // The right crossing's saved fingerprint, with the twins' record: \a count twins (0: no
    // record), their centroid when there are two or more
    static ElementFingerprint saved(int count)
    {
        ElementFingerprint fp = at(10.866);
        fp.twinCount = count;
        if (count >= 2) {
            fp.twinCentroid = Base::Vector3d(10, 0, 5);
        }
        return fp;
    }
    // CC1: the right crossing's name missing, its twin (the left crossing's name, Vertex11) at
    // its saved place, the seam vertex (Vertex10) 2 mm further. No edge holds the joint, so MG
    // drops tier 1's survivors and geometry decides.
    SolveInput landed(int count) const
    {
        auto input = this->input(right);
        input.pool["Vertex"].push_back(element("Vertex11", {hole1}));
        input.entries[0].fingerprint = saved(count);
        measure(input, {{"Vertex10", at(12.866)}, {"Vertex11", at(10.866)}}, nullptr);
        return input;
    }
};

// A Pad (tag 6) of a sketch face with a through hole (tag 11) whose cylinder crosses the top cap,
// then tapered (class B's review, CC3): the draft names the caps by index (IDX names of the
// offset wire), and its seam splits the top rim arc in two. The fillet's top rim arc was
// generated from the old top cap and the cylinder; no face holds that cap now.
struct TaperedPad
{
    std::string profile = lowFace({sketchEdge(1), sketchEdge(2), sketchEdge(3), sketchEdge(4)});
    std::string capOld = section({}, {profile}, 6, "XTR", 0, 'F', {"PRJ"});
    std::string capBottom = generated({profile}, 6, "XTR", 'F');
    std::string capIndex = section({"Face6"}, {}, 6, "MKR", 0, 'F', {"IDX", "SRC"});
    std::string cyl = generated({sketchEdge(1, 7)}, 11, "XTR", 'F');
    std::string topArc = generated({capOld, cyl}, 11, "CUT", 'E');
    std::string bottomArc = generated({capBottom, cyl}, 11, "CUT", 'E');

    // A piece of the top rim on the draft's cap
    std::string onIndexCap(int index) const
    {
        return generated({capIndex, cyl}, 11, "CUT", 'E', index);
    }
    // An arc of the hole's circle (radius 2, axis z), \a length long, its centre at \a centre
    static ElementFingerprint arc(double length, const Base::Vector3d& centre)
    {
        return fingerprint('E', "Circle", length, centre, Base::Vector3d(0, 0, 1), {2.0});
    }
    static constexpr double rim = 2 * std::numbers::pi;  // the rim's half circle

    // The faces (the bottom cap, the draft's top cap, the cylinder) and the edges: the bottom
    // rim arc (Edge5) and the top rim's two pieces (Edge6, nearly all of it, 0.03 mm from the
    // saved centre; Edge7, the short rest)
    SolveInput input() const
    {
        SolveInput input;
        input.diagonal = 22.9;
        input.pool["Face"] = {element("Face1", {capBottom}),
                              element("Face2", {capIndex}),
                              element("Face3", {cyl})};
        input.pool["Edge"] = {element("Edge5", {bottomArc}),
                              element("Edge6", {onIndexCap(0)}),
                              element("Edge7", {onIndexCap(1)})};
        input.entries = {missing(topArc, "Edge")};
        input.entries[0].fingerprint = arc(rim, Base::Vector3d(10, 1.273, 5));
        measure(input,
                {{"Edge5", arc(rim, Base::Vector3d(10, 1.273, 0))},
                 {"Edge6", arc(6.0, Base::Vector3d(10.03, 1.273, 5))},
                 {"Edge7", arc(rim - 6.0, Base::Vector3d(11.99, 0.14, 5))}},
                nullptr);
        return input;
    }
};

}  // namespace

TEST(SolveOwner, twinSurvivorGoesToGeometry)
{
    // The hole's centre moved onto the edge, which made one crossing the seam vertex: here the
    // left crossing (hole1) is gone, the seam vertex 0.134 mm from its place, and its twin
    // (Index 1) 1.866 mm away is tier 1's one survivor once HG dropped the seam vertex (the
    // joint is held and didn't generate it). Tier 1 took the twin silently. A twin is no
    // structural evidence: geometry decides over the whole pool, and the seam vertex is no twin.
    CrossedEdge c;
    auto input = c.input(c.hole1);
    input.pool["Edge"].push_back(element("Edge3", {c.edge1}));
    input.pool["Vertex"].push_back(element("Vertex11", {c.right}));
    input.entries[0].fingerprint = CrossedEdge::saved(2);
    measure(input, {{"Vertex10", CrossedEdge::at(11)}, {"Vertex11", CrossedEdge::at(9)}}, nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex10");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_EQ(outcome.evidence.rfind("tier 1's one survivor is the old element's twin (Vertex11); "
                                     "geometry decides; no structural candidate, tier 3: nearest "
                                     "0.134",
                                     0),
              0U)
        << outcome.evidence;
}

TEST(SolveOwner, twinSurvivorThenASiblingCirclesCrossingBreaks)
{
    // PR 379 round 2's cloud review (F1): another circle of the hole's sketch (g2 of sketch 7),
    // cut by the same Pocket (tag 11), crosses the edge too, its left crossing (Vertex20) exactly
    // at the saved place now. Tier 1's one survivor is the old element's twin (Vertex11), so
    // geometry decides over the whole pool, and tier 3's nearest is Vertex20: it shares the old
    // name's sketch and maker, so the origin gate passed it, and it was taken at the same place
    // (the batch's quiet level). It lost the hole's circle (T1''s test): the entry breaks, the
    // pick first, then the twin.
    CrossedEdge c;
    const auto cylB = generated({sketchEdge(2, 7)}, 11, "XTR", 'F');
    const auto leftB = generated({c.edge1, cylB}, 11, "CUT", 'V');
    auto input = c.input(c.hole1);
    input.pool["Edge"].push_back(element("Edge3", {c.edge1}));
    input.pool["Vertex"].push_back(element("Vertex11", {c.right}));
    input.pool["Vertex"].push_back(element("Vertex20", {leftB}));
    input.pool["Vertex"].push_back(
        element("Vertex21", {generated({c.edge1, cylB}, 11, "CUT", 'V', 1)})
    );
    input.entries[0].fingerprint = CrossedEdge::saved(2);
    measure(input,
            {{"Vertex10", CrossedEdge::at(40)},
             {"Vertex11", CrossedEdge::at(1.866)},
             {"Vertex20", CrossedEdge::at(10.866)},
             {"Vertex21", CrossedEdge::at(12.598)}},
            nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_NE(outcome.evidence.find("; the pick Vertex20 has another source element"),
              std::string::npos)
        << outcome.evidence;
    ASSERT_GE(outcome.candidates.size(), 2U);
    EXPECT_EQ(outcome.candidates[0], "Vertex20");
    EXPECT_EQ(outcome.candidates[1], "Vertex11");
    EXPECT_EQ(outcome.candidateRoles[1], "structural");

    //   R1 (round 1), the other hole cut by another Pocket (tag 12) from the same sketch: the
    //   origin gate's maker test breaks it first (F2: the evidence R1's Python test gets)
    const auto cylC = generated({sketchEdge(2, 7)}, 12, "XTR", 'F');
    input.pool["Vertex"][input.pool["Vertex"].size() - 2].names = {
        generated({c.edge1, cylC}, 12, "CUT", 'V')
    };
    input.pool["Vertex"].back().names = {generated({c.edge1, cylC}, 12, "CUT", 'V', 1)};
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_NE(outcome.evidence.find("; the pick Vertex20 has another maker"), std::string::npos)
        << outcome.evidence;

    //   T1''s test as the batch asks it: the sibling's crossing lost the hole's circle; the twin
    //   and the seam vertex keep it (the seam is named after the hole's cylinder)
    EXPECT_TRUE(Data::lostOldSources({leftB}, c.hole1));
    EXPECT_FALSE(Data::lostOldSources({c.right}, c.hole1));
    EXPECT_FALSE(Data::lostOldSources({c.seamNow}, c.hole1));
}

TEST(SolveOwner, twinAtTheSavedPlaceBreaks)
{
    // CC1 (ops#503 round 2): the circle moved so that the left crossing lands exactly where the
    // right one was, and the right one became the seam vertex 2 mm further. The right crossing's
    // name misses; its twin sits at its saved place, and tier 3 took it, quietly. The record
    // says 2 twins and the pool holds 1: the set shrank, so the pick is a trade, never quiet.
    CrossedEdge c;
    auto outcome = Data::solveOwner(c.landed(2))[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("ambiguous: Vertex11 is the old element's twin (2 twins "
                                     "saved, 1 now)",
                                     0),
              0U)
        << outcome.evidence;
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Vertex11", "Vertex10"}));
    EXPECT_EQ(outcome.candidateRoles, (std::vector<std::string> {"place", "geometric"}));
}

TEST(SolveOwner, twinWithoutARecordBreaks)
{
    // CC1 with a record saved before D1, without the twins' number: the rule needs it and the
    // pick is a twin, so the entry breaks, the twin first (I-S9: a missing field is a loud
    // result, never a keep).
    CrossedEdge c;
    auto outcome = Data::solveOwner(c.landed(0))[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("ambiguous: Vertex11 is the old element's twin (no twin "
                                     "record, 1 now)",
                                     0),
              0U)
        << outcome.evidence;
    ASSERT_FALSE(outcome.candidates.empty());
    EXPECT_EQ(outcome.candidates.front(), "Vertex11");
}

TEST(SolveOwner, twinRenumberedIsWarned)
{
    // Both crossings unmoved, their Index values swapped: the left crossing's name (Index 0) at
    // the right one's old place. Tier 3 picks it among tier 1's survivors; the record's two
    // twins are there and its offset from their centroid is the saved one: a pure renumbering,
    // resolved with its own clause and warned (the faces apart, so MG and HG don't act).
    CrossedEdge c;
    auto input = c.input(c.right);
    input.faces = {element("Face3", {c.x2}),
                   element("Face5", {c.x1}),
                   element("Face6", {c.x0}),
                   element("Face10", {c.cyl})};
    input.pool["Vertex"] = {element("Vertex3", {c.hole1}), element("Vertex13", {c.right})};
    input.entries[0].fingerprint = CrossedEdge::saved(2);
    measure(input,
            {{"Vertex3", CrossedEdge::at(10.866)}, {"Vertex13", CrossedEdge::at(9.134)}},
            nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex3");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_NE(outcome.evidence.find("; twin renumbered: Vertex3 at its place among 2"),
              std::string::npos)
        << outcome.evidence;
    //   the batch's level: never the quieter same-place one for a twin, at its place or not
    EXPECT_FALSE(Data::mayBeQuietAtPlace({c.hole1}, c.right, true));
    EXPECT_TRUE(Data::mayBeQuietAtPlace({c.right}, c.right, true));
}

TEST(SolveOwner, loneTwinRenumberedResolves)
{
    // The record of a lone order-keyed name (Index 1, saved alone: 1 twin, no centroid), the name
    // missing, the element named Index 0 now alone at its place: a lone member renumbered, taken
    // as the branch takes it.
    CrossedEdge c;
    auto outcome = Data::solveOwner(c.landed(1))[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Vertex11");
    EXPECT_EQ(outcome.tier, 3);

    //   3 twins saved, 2 now (an Index 2 twin elsewhere): the set shrank, a trade
    auto input = c.landed(3);
    input.pool["Vertex"].push_back(
        element("Vertex12", {generated({c.edge1, c.cyl}, 11, "CUT", 'V', 2)})
    );
    measure(input,
            {{"Vertex10", CrossedEdge::at(12.866)},
             {"Vertex11", CrossedEdge::at(10.866)},
             {"Vertex12", CrossedEdge::at(9.134)}},
            nullptr);
    outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("ambiguous: Vertex11 is the old element's twin (3 twins "
                                     "saved, 2 now)",
                                     0),
              0U)
        << outcome.evidence;
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Vertex11", "Vertex12", "Vertex10"}));
    EXPECT_EQ(outcome.candidateRoles,
              (std::vector<std::string> {"place", "geometric", "geometric"}));
}

TEST(SolveOwner, exactPlaceAnotherSourceIsWarned)
{
    // The board's top edge at its saved place, but from another sketch (a new sketch object,
    // policy D's case): the exact place takes it, warned at the normal level, never the quieter
    // same-place one (I-S6), and the evidence says so.
    LongBoard b;
    auto input = b.input(LongBoard::edgeAt(0), LongBoard::edgeAt(45));
    input.pool["Edge"][0].names = {b.otherSketch};
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge2");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_EQ(outcome.evidence,
              "no structural candidate, at the same place, another source: nearest 0.000, second "
              "45.000, d_max 50.000");
    //   the batch's level: normal for the other sketch's edge, the quieter one for a redraw in
    //   the old edge's sketch
    EXPECT_FALSE(Data::mayBeQuietAtPlace({b.otherSketch}, b.oldEdge, true));
    EXPECT_TRUE(Data::mayBeQuietAtPlace({b.redrawn}, b.oldEdge, true));
    //   the redraw lost the old line's ID (T1''s test): the batch keeps the quieter level only
    //   while no element holds that ID (App::reboundInPlace())
    EXPECT_TRUE(Data::lostOldSources({b.redrawn}, b.oldEdge));
    EXPECT_FALSE(Data::lostOldSources({b.oldEdge}, b.oldEdge));
}

TEST(SolveOwner, faceGeneratorGoneDropsTheSurvivor)
{
    // CC3: the taper renamed the top cap, so no face holds the top rim arc's face generator, and
    // the bottom rim arc (from the bottom cap and the cylinder, overlap 0.70) was tier 1's one
    // survivor, 5 mm down, silently. Made from a cap that is gone, the old arc can't be one that a
    // held cap made: the survivors are dropped and geometry decides. The top rim is two pieces
    // now, neither of the old arc's size: nothing is at the place, and the entry breaks, the
    // nearest first.
    TaperedPad t;
    auto outcome = Data::solveOwner(t.input())[0];
    EXPECT_EQ(outcome.status, SolveStatus::Broken) << outcome.evidence;
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3 found none", 0), 0U)
        << outcome.evidence;
    EXPECT_NE(outcome.evidence.find("; tier 1's 1 survivor lacks the old element's face generator "
                                    "(a face, which no face holds)"),
              std::string::npos)
        << outcome.evidence;
    EXPECT_EQ(outcome.candidates, (std::vector<std::string> {"Edge6", "Edge7", "Edge5"}));
}

TEST(SolveOwner, faceGeneratorGoneThenTheWholeArcInPlace)
{
    // The control: the taper left the top rim whole (on the draft's cap): tier 3 takes it at its
    // place.
    TaperedPad t;
    auto input = t.input();
    input.pool["Edge"].pop_back();
    measure(input,
            {{"Edge5", TaperedPad::arc(TaperedPad::rim, Base::Vector3d(10, 1.273, 0))},
             {"Edge6", TaperedPad::arc(TaperedPad::rim, Base::Vector3d(10, 1.273, 5))}},
            nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge6");
    EXPECT_EQ(outcome.tier, 3);
    EXPECT_EQ(outcome.evidence.rfind("no structural candidate, tier 3: nearest 0.000", 0), 0U)
        << outcome.evidence;
}

TEST(SolveOwner, faceGeneratorHeldByADescendantKeepsTheSurvivor)
{
    // The control: a later feature (tag 12) modified the top cap, which a face holds as its piece,
    // and the top rim arc is made from that piece: the cap is held, the net stays off. HG drops
    // the bottom rim arc (not made from the cap), and tier 1 keeps the arc made from it.
    TaperedPad t;
    auto input = t.input();
    const auto capPiece = piece(t.capOld, 12, "FUS", 0, 'F');
    input.pool["Face"].push_back(element("Face4", {capPiece}));
    input.pool["Edge"] = {element("Edge5", {t.bottomArc}),
                          element("Edge8", {generated({capPiece, t.cyl}, 11, "CUT", 'E')})};
    measure(input,
            {{"Edge5", TaperedPad::arc(TaperedPad::rim, Base::Vector3d(10, 1.273, 0))},
             {"Edge8", TaperedPad::arc(TaperedPad::rim, Base::Vector3d(10, 1.273, 5))}},
            nullptr);
    auto outcome = Data::solveOwner(input)[0];
    EXPECT_EQ(outcome.status, SolveStatus::Resolved) << outcome.evidence;
    EXPECT_EQ(outcome.element, "Edge8");
    EXPECT_EQ(outcome.tier, 1);
}

TEST(NameAncestry, twinNames)
{
    // The twin test (ops#503 D1): names equal up to an order key
    HoledBend h;
    const auto rank = [&](int index, const std::vector<std::string>& flags) {
        return section({}, {h.edge1, h.cyl}, 11, "CUT", index, 'V', flags);
    };
    const auto role = [&](const char* value) {
        return Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            std::vector<std::string> {h.edge1, h.cyl},
            "11",
            "CUT",
            value,
            'V',
            "0",
            {"PRJ"},
            std::vector<std::string> {}
        );
    };
    //   the bare ranks of a counter section, the ORD flag ignored, roles
    EXPECT_TRUE(Data::isTwinName(rank(1, {"GEN"}), rank(0, {"GEN"})));
    EXPECT_TRUE(Data::isTwinName(rank(1, {"GEN", "ORD"}), rank(0, {"GEN"})));
    EXPECT_TRUE(Data::isTwinName(role("in"), role("out")));
    EXPECT_FALSE(Data::isTwinName(rank(0, {"GEN"}), rank(0, {"GEN"})));
    //   no rank of a projection's section, of a marked piece's, of another op's
    EXPECT_FALSE(Data::isTwinName(rank(1, {"PRJ"}), rank(0, {"PRJ"})));
    EXPECT_FALSE(Data::isTwinName(section({}, {h.cyl}, 11, "CUT", 1, 'V', {"GEN"}, {h.x0}),
                                  section({}, {h.cyl}, 11, "CUT", 0, 'V', {"GEN"}, {h.x0})));
    EXPECT_FALSE(Data::isTwinName(rank(1, {"GEN"}), section({}, {h.edge1, h.cyl}, 12, "CUT", 0, 'V', {"GEN"})));
    //   a pattern instance's number is its identity at the top level (the pattern sibling
    //   guard's), a counter in the names a section links
    EXPECT_FALSE(Data::isTwinName(stepInstance(h.hole1, 14, "1", 'V'), stepInstance(h.hole1, 14, "2", 'V')));
    EXPECT_TRUE(Data::isCounterSiblingName(stepInstance(h.hole1, 14, "1", 'V'),
                                           stepInstance(h.hole1, 14, "2", 'V')));
    EXPECT_TRUE(Data::isTwinName(generated({stepInstance(h.edge1, 14, "1", 'E')}, 15, "FLT", 'V', 1),
                                 generated({stepInstance(h.edge1, 14, "2", 'E')}, 15, "FLT", 'V', 0)));
    //   keyed by order: a non-zero rank, ORD, a role; not rank 0 alone
    EXPECT_TRUE(Data::isOrderKeyedName(rank(1, {"GEN"})));
    EXPECT_TRUE(Data::isOrderKeyedName(rank(0, {"GEN", "ORD"})));
    EXPECT_TRUE(Data::isOrderKeyedName(role("out")));
    EXPECT_FALSE(Data::isOrderKeyedName(rank(0, {"GEN"})));
    EXPECT_FALSE(Data::isOrderKeyedName(rank(1, {"PRJ"})));
}
