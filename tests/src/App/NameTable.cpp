// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <App/MappedName.h>
#include <App/NameId.h>
#include <App/NameTable.h>
#include <Base/Reader.h>

#include "InitApplication.h"

#include <algorithm>
#include <atomic>
#include <map>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

// Task 1 PR 3 (ops#6): the name table, interning and expansion. Names are built with
// makeEncodedSection, as the V2 builders do. The golden interned forms below come from an
// independent Python interner over scripts/name_id_ref.py (ops repo), not from this code.

using Data::MappedName;
using Data::NameId;
using Data::NameTable;

namespace
{

using Strings = std::vector<std::string>;

std::string section(
    const Strings& referenceIds,
    const Strings& linked,
    const std::string& tag,
    const char* op,
    const std::string& index,
    char type,
    const Strings& flags,
    const Strings& connected
)
{
    return MappedName::makeEncodedSection(referenceIds, linked, tag, op, index, type, "0", flags, connected);
}

// The worked example of notes/naming-v2.md: a box edge, a fillet face on it, an edge bounded by
// that face (UPP), and a split piece of the face whose Connected Names hold that edge.
struct Example
{
    std::string edge = section({"Edge1"}, {}, "5", "FLT", "0", 'E', {"IDX", "SRC"}, {});
    std::string face = section({}, {edge}, "7", "FLT", "0", 'F', {"GEN"}, {});
    std::string upper = section({}, {face}, "9", "CUT", "0", 'E', {"UPP"}, {});
    std::string piece = face + "|" + section({}, {}, "23", "CUT", "0", 'F', {"MOD"}, {upper});
};

// Hand-built names of depth 1-4 with `,`, `;` and `|` at every depth.
Strings handBuiltNames()
{
    std::string a = section({"g1"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    std::string b = section({"g2", "e2"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    std::string face = section({}, {a, b}, "4", "FAC", "0", 'F', {"LOW"}, {b});
    std::string piece = face + "|" + section({}, {}, "6", "CUT", "1", 'F', {"MOD"}, {a, face});
    std::string upper = section({}, {piece, face}, "8", "FLT", "2", 'E', {"UPP", "GEN"}, {piece});
    std::string chain = upper + "|" + section({}, {}, "9", "CUT", "0", 'E', {"MOD"}, {upper}) + "|"
        + section({}, {}, "11", "CUT", "0", 'E', {"MOD"}, {piece, upper});
    std::string generated = section({}, {chain}, "-12", "XTR", "0", 'F', {"GEN"}, {face, chain});
    return {a, b, face, piece, upper, chain, generated};
}

std::string interned(const char* id)
{
    return std::string("~") + id;
}

NameId idFromText(const char* text)
{
    auto id = NameId::fromBase32(text);
    EXPECT_TRUE(id.has_value()) << text;
    return id.value_or(NameId());
}

int sign(int value)
{
    return (value > 0) - (value < 0);
}

// Names of random shape over a pool of earlier names, so that subtrees are shared and pairs
// often differ deep inside (seeded).
class NameGenerator
{
public:
    explicit NameGenerator(unsigned seed)
        : _random(seed)
    {}

    std::string next()
    {
        int kind = pick(4);
        std::string name;
        if (_pool.empty() || kind == 0) {
            name = section(
                {"g" + std::to_string(pick(5))},
                {},
                std::to_string(pick(3)),
                "SKT",
                "0",
                'E',
                {"SRC"},
                {}
            );
        }
        else if (kind == 1) {
            name = std::string(pickFromPool()) + "|"
                + section(
                       {},
                       {},
                       std::to_string(pick(4)),
                       "CUT",
                       std::to_string(pick(3)),
                       'F',
                       {"MOD"},
                       names(pick(3))
                );
        }
        else {
            name = section(
                {},
                names(1 + pick(3)),
                std::to_string(pick(6) - 2),
                kind == 2 ? "FLT" : "XTR",
                "0",
                "EFV" [pick(3)],
                { kind == 2 ? "GEN" : "UPP" },
                names(pick(2))
            );
        }
        if (name.size() > maxSize) {
            return next();  // full V2 names grow with depth; real ones stay below about 25 kB
        }
        if (_pool.size() < 400) {
            _pool.push_back(name);
        }
        else {
            _pool[pick(static_cast<int>(_pool.size()))] = name;
        }
        return name;
    }

private:
    int pick(int count)
    {
        return std::uniform_int_distribution<int>(0, count - 1)(_random);
    }
    const std::string& pickFromPool()
    {
        return _pool[pick(static_cast<int>(_pool.size()))];
    }
    Strings names(int count)
    {
        std::set<std::string> chosen;  // sorted and unique, as the builders keep these lists
        for (int i = 0; i < count && !_pool.empty(); ++i) {
            chosen.insert(pickFromPool());
        }
        return {chosen.begin(), chosen.end()};
    }

    static constexpr std::size_t maxSize = 30000;
    std::mt19937 _random;
    Strings _pool;
};

}  // namespace

class NameTableTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();  // collisions are logged
    }
};

// ---------------------------------------------------------------------------------------------
// Interned forms and IDs

TEST_F(NameTableTest, goldenInternedForms)
{
    // Arrange
    NameTable table;
    Example example;

    // Act
    std::string face = table.toInterned(example.face);
    std::string upper = table.toInterned(example.upper);
    std::string piece = table.toInterned(example.piece);

    // Assert
    EXPECT_EQ(example.face, "_;Edge1^;_^;5^;FLT^;0^;E^;0^;IDX^,SRC^;_;7;FLT;0;F;0;GEN;_");
    EXPECT_EQ(table.toInterned(example.edge), example.edge);
    EXPECT_EQ(face, "_;~0baii9v1kj6bk;7;FLT;0;F;0;GEN;_");
    EXPECT_EQ(upper, "_;~bvlrp12o22fv0;9;CUT;0;E;0;UPP;_");
    EXPECT_EQ(piece, "~bvlrp12o22fv0|_;_;23;CUT;0;F;0;MOD;~uevcr4g23biai");
    EXPECT_EQ(table.size(), 3U);
    EXPECT_EQ(table.lookup(idFromText("0baii9v1kj6bk")), example.edge);
    EXPECT_EQ(table.lookup(idFromText("bvlrp12o22fv0")), face);
    EXPECT_EQ(table.lookup(idFromText("uevcr4g23biai")), upper);
    EXPECT_EQ(table.idOf(face), idFromText("bvlrp12o22fv0"));
    EXPECT_EQ(table.collisions(), 0U);
}

TEST_F(NameTableTest, namesWithoutEmbeddedNamesStayTheSame)
{
    // Arrange
    NameTable table;
    std::string sketchEdge = section({"g1", "e2"}, {}, "9", "SKT", "0", 'E', {"SRC"}, {});
    std::string unmapped = MappedName::makeUnmappedName({"Edge3"}, 12, "CUT", 'E').toString();

    // Act and assert
    EXPECT_EQ(table.toInterned(sketchEdge), sketchEdge);
    EXPECT_EQ(table.toInterned(unmapped), unmapped);
    EXPECT_EQ(table.toInterned("Edge1"), "Edge1");
    EXPECT_EQ(table.toInterned(""), "");
    EXPECT_EQ(table.size(), 0U);
    EXPECT_EQ(table.toPlain(sketchEdge), sketchEdge);
}

TEST_F(NameTableTest, internedFormsHaveNoCaretsAndAreIdempotent)
{
    NameTable table;
    for (const auto& name : handBuiltNames()) {
        std::string form = table.toInterned(name);
        EXPECT_EQ(form.find('^'), std::string::npos) << form;
        EXPECT_EQ(table.toInterned(form), form) << name;
        EXPECT_LE(form.size(), name.size()) << name;
    }
}

TEST_F(NameTableTest, mixedFormsGiveTheSameInternedForm)
{
    // Arrange: the example's piece with only its prefix interned, and with only its
    // Connected Name interned
    NameTable table;
    Example example;
    std::string full = table.toInterned(example.piece);
    std::string prefixOnly = NameTable::makeRef(*table.internName(example.face)) + "|"
        + section({}, {}, "23", "CUT", "0", 'F', {"MOD"}, {example.upper});
    std::string connectedOnly = example.face + "|"
        + section({},
                  {},
                  "23",
                  "CUT",
                  "0",
                  'F',
                  {"MOD"},
                  {NameTable::makeRef(*table.internName(example.upper))});

    // Act and assert
    EXPECT_EQ(table.toInterned(prefixOnly), full);
    EXPECT_EQ(table.toInterned(connectedOnly), full);
    EXPECT_EQ(table.toPlain(prefixOnly), example.piece);
    EXPECT_EQ(table.toPlain(connectedOnly), example.piece);
}

TEST_F(NameTableTest, bareReferences)
{
    NameTable table;
    Example example;
    auto id = table.internName(example.face);
    ASSERT_TRUE(id);
    std::string ref = NameTable::makeRef(*id);

    EXPECT_EQ(ref.size(), NameTable::RefLength);
    EXPECT_EQ(NameTable::parseRef(ref), id);
    EXPECT_EQ(table.internName(ref), id);
    // a whole name that is one reference has the entry's canonical form
    EXPECT_EQ(table.toInterned(ref), table.toInterned(example.face));
    EXPECT_EQ(table.toPlain(ref), example.face);
    EXPECT_EQ(table.expand(*id), example.face);
    EXPECT_FALSE(NameTable::parseRef(ref.substr(1)));
    EXPECT_FALSE(NameTable::parseRef(ref + "0"));
    EXPECT_FALSE(NameTable::parseRef("~vvvvvvvvvvvvv"));  // nonzero padding bits
    EXPECT_FALSE(NameTable::parseRef("#" + ref.substr(1)));
}

TEST_F(NameTableTest, unknownReferencesStayUnresolved)
{
    NameTable table;
    std::string unknown = "~0123456789abc";
    ASSERT_TRUE(NameTable::parseRef(unknown));
    std::string name = unknown + "|" + section({}, {}, "5", "CUT", "0", 'E', {"MOD"}, {unknown});

    EXPECT_EQ(table.toPlain(name), name);
    EXPECT_EQ(table.toInterned(name), name);
    EXPECT_EQ(table.toInterned(unknown), unknown);
    EXPECT_FALSE(table.expand(*NameTable::parseRef(unknown)));
    EXPECT_EQ(table.depth(*NameTable::parseRef(unknown)), 0);
}

// ---------------------------------------------------------------------------------------------
// Expansion and the decoder

TEST_F(NameTableTest, expansionRoundTrips)
{
    NameTable table;
    for (const auto& name : handBuiltNames()) {
        EXPECT_EQ(table.toPlain(table.toInterned(name)), name);
    }
    NameGenerator generator(20261002);
    for (int i = 0; i < 2000; ++i) {
        std::string name = generator.next();
        ASSERT_EQ(table.toPlain(table.toInterned(name)), name) << i;
    }
    EXPECT_EQ(table.collisions(), 0U);
}

TEST_F(NameTableTest, decoderGivesTheSameSectionsForBothForms)
{
    // The decoder uses the process's table
    auto& table = NameTable::instance();
    for (const auto& name : handBuiltNames()) {
        // Arrange
        std::string form = table.toInterned(name);

        // Act
        const auto& full = MappedName::getDecodedMappedName(name);
        const auto& compact = MappedName::getDecodedMappedName(form);

        // Assert: the same sections, and the embedded names expand to the full form's
        ASSERT_EQ(compact.size(), full.size()) << form;
        auto expanded = [&](const Strings& names) {
            Strings result;
            for (const auto& entry : names) {
                EXPECT_TRUE(NameTable::parseRef(entry)) << entry;
                result.push_back(table.toPlain(entry));
            }
            return result;
        };
        for (std::size_t i = 0; i < full.size(); ++i) {
            EXPECT_EQ(compact[i].referenceIDs, full[i].referenceIDs);
            EXPECT_EQ(expanded(compact[i].linkedNames), full[i].linkedNames);
            EXPECT_EQ(compact[i].iterationTag, full[i].iterationTag);
            EXPECT_EQ(compact[i].opCode, full[i].opCode);
            EXPECT_EQ(compact[i].index, full[i].index);
            EXPECT_EQ(compact[i].elementType, full[i].elementType);
            EXPECT_EQ(compact[i].duplicateCount, full[i].duplicateCount);
            EXPECT_EQ(compact[i].mapperFlags, full[i].mapperFlags);
            EXPECT_EQ(expanded(compact[i].connectedElements), full[i].connectedElements);
        }
        // a caller recursing into an embedded name decodes `~<ID>` as that name
        if (!compact.back().linkedNames.empty()) {
            const auto& linked = compact.back().linkedNames.front();
            EXPECT_EQ(
                MappedName::getDecodedMappedName(linked).size(),
                MappedName::getDecodedMappedName(table.toPlain(linked)).size()
            );
        }
    }
}

TEST_F(NameTableTest, decoderLeavesUnknownReferencesUnresolvedUntilLoaded)
{
    // Arrange: a node no other test interns
    auto& table = NameTable::instance();
    std::string content = section({"g424242"}, {}, "424242", "SKT", "0", 'E', {"SRC"}, {});
    NameId id = table.idOf(content);
    ASSERT_FALSE(table.lookup(id));
    std::string name = NameTable::makeRef(id) + "|"
        + section({}, {}, "424243", "CUT", "0", 'E', {"MOD"}, {});

    // Act and assert: nothing while unknown, and the result isn't cached
    EXPECT_TRUE(MappedName::getDecodedMappedName(name).empty());
    EXPECT_EQ(table.insertLoaded(id, content), NameTable::LoadResult::Inserted);
    const auto& decoded = MappedName::getDecodedMappedName(name);
    ASSERT_EQ(decoded.size(), 2U);
    EXPECT_EQ(decoded[0].referenceIDs, Strings {"g424242"});
    EXPECT_EQ(decoded[1].iterationTag, "424243");
}

// ---------------------------------------------------------------------------------------------
// compareExpanded

TEST_F(NameTableTest, compareExpandedAgreesWithBytes)
{
    // Arrange
    NameTable table;
    NameGenerator generator(4711);
    Strings names;
    for (int i = 0; i < 600; ++i) {
        names.push_back(generator.next());
    }
    Strings forms;
    for (const auto& name : names) {
        forms.push_back(table.toInterned(name));
    }
    std::mt19937 random(99);
    std::uniform_int_distribution<std::size_t> anyName(0, names.size() - 1);

    // Act and assert: random pairs, neighbours (often sharing a prefix or subtrees) and
    // each name against itself, in interned, plain and mixed forms
    int compared = 0;
    auto check = [&](std::size_t i, std::size_t j) {
        int expected = sign(names[i].compare(names[j]));
        ASSERT_EQ(sign(table.compareExpanded(forms[i], forms[j])), expected) << names[i] << "\n"
                                                                             << names[j];
        ASSERT_EQ(sign(table.compareExpanded(forms[i], names[j])), expected);
        ASSERT_EQ(sign(table.compareExpanded(names[i], forms[j])), expected);
        ++compared;
    };
    for (int k = 0; k < 3000; ++k) {
        check(anyName(random), anyName(random));
    }
    for (std::size_t i = 0; i + 1 < names.size(); ++i) {
        check(i, i + 1);
        check(i, i);
    }
    std::vector<std::size_t> order(names.size());
    for (std::size_t i = 0; i < order.size(); ++i) {
        order[i] = i;
    }
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        return table.compareExpanded(forms[a], forms[b]) < 0;
    });
    for (std::size_t i = 0; i + 1 < order.size(); ++i) {
        EXPECT_LE(names[order[i]], names[order[i + 1]]);
    }
    EXPECT_GT(compared, 4000);
}

TEST_F(NameTableTest, compareExpandedOnEscapedDepths)
{
    // `~X` as a prefix and `~X` as an embedded name expand at different escape depths
    NameTable table;
    Example example;
    std::string ref = NameTable::makeRef(*table.internName(example.face));
    std::string asPrefix = ref + "|" + section({}, {}, "1", "CUT", "0", 'F', {"MOD"}, {});
    std::string asLinked = section({}, {ref}, "1", "CUT", "0", 'F', {"MOD"}, {});
    std::string plainLinked = section({}, {example.face}, "1", "CUT", "0", 'F', {"MOD"}, {});
    std::string plainPrefix = example.face + "|" + section({}, {}, "1", "CUT", "0", 'F', {"MOD"}, {});

    EXPECT_EQ(table.compareExpanded(asLinked, plainLinked), 0);
    EXPECT_EQ(table.compareExpanded(asPrefix, plainPrefix), 0);
    EXPECT_EQ(sign(table.compareExpanded(asPrefix, asLinked)), sign(plainPrefix.compare(plainLinked)));
    EXPECT_EQ(sign(table.compareExpanded(asLinked, asPrefix)), sign(plainLinked.compare(plainPrefix)));
    // a name against its own prefix: the shorter is less
    EXPECT_LT(table.compareExpanded(ref, asPrefix), 0);
    EXPECT_GT(table.compareExpanded(asPrefix, ref), 0);
}

// ---------------------------------------------------------------------------------------------
// Collisions

TEST_F(NameTableTest, collisionsAreDetected)
{
    // Arrange: the hook puts a second content on the first one's ID
    NameTable table;
    std::string first = section({"g1"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    std::string second = section({"g2"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    NameId taken = table.idOf(first);
    table.setIdHookForTesting([&](std::string_view content) -> std::optional<NameId> {
        if (content == second) {
            return taken;
        }
        return std::nullopt;
    });

    // Act
    auto firstId = table.intern(first);
    auto secondId = table.intern(second);
    auto again = table.intern(first);

    // Assert
    EXPECT_EQ(firstId, taken);
    EXPECT_FALSE(secondId);
    EXPECT_EQ(again, taken);
    EXPECT_EQ(table.collisions(), 1U);
    EXPECT_EQ(table.lookup(taken), first);
    EXPECT_EQ(table.size(), 1U);
}

TEST_F(NameTableTest, forcedCollisionFallsBackToTheFullForm)
{
    // Arrange: the face's node collides with a node already in the table
    NameTable table;
    Example example;
    std::string other = section({"g7"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    ASSERT_TRUE(table.intern(other));
    std::string faceForm = "_;~0baii9v1kj6bk;7;FLT;0;F;0;GEN;_";  // goldenInternedForms
    table.setIdHookForTesting([&](std::string_view content) -> std::optional<NameId> {
        if (content == faceForm) {
            return table.idOf(other);  // the hook doesn't apply to `other` itself
        }
        return std::nullopt;
    });

    // Act
    std::string upper = table.toInterned(example.upper);
    std::string piece = table.toInterned(example.piece);

    // Assert: the face stays inline in full V2 form wherever it is embedded or a prefix
    EXPECT_GE(table.collisions(), 1U);
    EXPECT_EQ(upper, example.upper);  // its only embedded name is the face
    EXPECT_EQ(piece.substr(0, example.face.size() + 1), example.face + "|");
    EXPECT_NE(piece.find(";MOD;~"), std::string::npos) << piece;  // the edge is interned
    // the decoder reads the fallback, and expansion is byte-identical
    const auto& decoded = MappedName::getDecodedMappedName(upper);
    ASSERT_EQ(decoded.size(), 1U);
    EXPECT_EQ(decoded[0].linkedNames, Strings {example.face});
    EXPECT_EQ(table.toPlain(upper), example.upper);
    EXPECT_EQ(table.toPlain(piece), example.piece);
    EXPECT_EQ(table.compareExpanded(piece, example.piece), 0);
    EXPECT_EQ(table.compareExpanded(piece, upper), sign(example.piece.compare(example.upper)));
    // a node holding an inline name still expands and compares exactly
    auto pieceEdgeRef = piece.substr(piece.rfind('~'));
    EXPECT_EQ(table.toPlain(pieceEdgeRef), example.upper);
    std::string plainLinkedPiece = section({}, {example.piece}, "30", "FLT", "0", 'F', {"GEN"}, {});
    std::string linkedPiece = table.toInterned(plainLinkedPiece);
    EXPECT_EQ(table.toPlain(linkedPiece), plainLinkedPiece);
    EXPECT_EQ(table.compareExpanded(linkedPiece, plainLinkedPiece), 0);
}

TEST_F(NameTableTest, toInternedIfKnownInsertsNothing)
{
    // Arrange
    NameTable table;
    Example example;

    // Act and assert: nothing known yet, so no interned name can hold the face's edge
    EXPECT_FALSE(table.toInternedIfKnown(example.face));
    EXPECT_FALSE(table.toInternedIfKnown(example.piece));
    EXPECT_EQ(table.toInternedIfKnown(example.edge), example.edge);  // no node to refer to
    EXPECT_EQ(table.size(), 0U);

    // Act and assert: once interned, every form of the name gives the interned form
    std::string piece = table.toInterned(example.piece);
    std::string face = table.toInterned(example.face);
    std::size_t size = table.size();
    EXPECT_EQ(table.toInternedIfKnown(example.piece), piece);
    EXPECT_EQ(table.toInternedIfKnown(piece), piece);
    EXPECT_EQ(table.toInternedIfKnown(face + "|" + piece.substr(piece.find('|') + 1)), piece);
    // a name with a known prefix but a new embedded name is still unknown
    std::string other = section({"g7"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    std::string newer = section({}, {other}, "31", "FLT", "0", 'F', {"GEN"}, {});
    EXPECT_FALSE(table.toInternedIfKnown(piece.substr(0, piece.find('|') + 1) + newer));
    EXPECT_EQ(table.size(), size);
    EXPECT_EQ(table.collisions(), 0U);
}

TEST_F(NameTableTest, toInternedIfKnownKeepsACollisionInlineWithoutCountingIt)
{
    // Arrange: the face's node collides, as in forcedCollisionFallsBackToTheFullForm
    NameTable table;
    Example example;
    std::string other = section({"g7"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    ASSERT_TRUE(table.intern(other));
    std::string faceForm = "_;~0baii9v1kj6bk;7;FLT;0;F;0;GEN;_";  // goldenInternedForms
    table.setIdHookForTesting([&](std::string_view content) -> std::optional<NameId> {
        if (content == faceForm) {
            return table.idOf(other);
        }
        return std::nullopt;
    });
    std::string piece = table.toInterned(example.piece);
    ASSERT_NE(piece.find('^'), std::string::npos) << piece;  // the face inline
    std::size_t collisions = table.collisions();
    std::size_t size = table.size();

    // Act
    auto known = table.toInternedIfKnown(piece);
    auto fromPlain = table.toInternedIfKnown(example.piece);

    // Assert: the canonical name of a collision gives itself back, so it isn't "another form"
    EXPECT_EQ(known, piece);
    EXPECT_EQ(fromPlain, piece);
    EXPECT_EQ(table.collisions(), collisions);
    EXPECT_EQ(table.size(), size);
    // an insert meets the collision again and counts it (logged once per ID)
    EXPECT_EQ(table.toInterned(piece), piece);
    EXPECT_GT(table.collisions(), collisions);
}

// ---------------------------------------------------------------------------------------------
// Loaded entries and depth

TEST_F(NameTableTest, insertLoaded)
{
    // Arrange: the entries of the hand-built names, in ID order (as a file has them), so
    // nodes can come before the nodes they refer to
    NameTable source;
    Strings forms;
    for (const auto& name : handBuiltNames()) {
        forms.push_back(source.toInterned(name));
    }
    std::map<std::string, std::string> entries;  // base32 ID -> content
    for (const auto& form : forms) {
        for (std::size_t pos = form.find('~'); pos != std::string::npos;
             pos = form.find('~', pos + 1)) {
            auto id = NameTable::parseRef(form.substr(pos, NameTable::RefLength));
            ASSERT_TRUE(id);
            entries[id->toBase32()] = *source.lookup(*id);
        }
    }
    // and the entries those refer to
    for (bool grew = true; grew;) {
        grew = false;
        auto snapshot = entries;
        for (const auto& [id, content] : snapshot) {
            for (std::size_t pos = content.find('~'); pos != std::string::npos;
                 pos = content.find('~', pos + 1)) {
                auto ref = NameTable::parseRef(content.substr(pos, NameTable::RefLength));
                if (ref && !entries.count(ref->toBase32())) {
                    entries[ref->toBase32()] = *source.lookup(*ref);
                    grew = true;
                }
            }
        }
    }
    ASSERT_EQ(entries.size(), source.size());
    NameTable loaded;

    // Act
    std::vector<NameTable::LoadResult> results;
    for (const auto& [id, content] : entries) {
        results.push_back(loaded.insertLoaded(idFromText(id.c_str()), content));
    }
    auto repeated
        = loaded.insertLoaded(idFromText(entries.begin()->first.c_str()), entries.begin()->second);

    // Assert
    for (auto result : results) {
        EXPECT_EQ(result, NameTable::LoadResult::Inserted);
    }
    EXPECT_EQ(repeated, NameTable::LoadResult::Identical);
    EXPECT_EQ(loaded.size(), source.size());
    for (std::size_t i = 0; i < forms.size(); ++i) {
        EXPECT_EQ(loaded.toPlain(forms[i]), handBuiltNames()[i]);
    }
    for (const auto& [id, content] : entries) {
        EXPECT_EQ(loaded.depth(idFromText(id.c_str())), source.depth(idFromText(id.c_str()))) << id;
    }
    EXPECT_EQ(loaded.collisions(), 0U);
}

TEST_F(NameTableTest, insertLoadedRefusesWrongAndCollidingEntries)
{
    // Arrange
    NameTable table;
    std::string first = section({"g1"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    std::string second = section({"g2"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    NameId firstId = table.idOf(first);
    ASSERT_EQ(table.insertLoaded(firstId, first), NameTable::LoadResult::Inserted);

    // Act and assert: an ID that isn't its content's
    EXPECT_EQ(table.insertLoaded(firstId, second), NameTable::LoadResult::WrongId);
    // a file from a process where `second` has `first`'s ID (forced here)
    table.setIdHookForTesting([&](std::string_view content) -> std::optional<NameId> {
        if (content == second) {
            return firstId;
        }
        return std::nullopt;
    });
    EXPECT_EQ(table.insertLoaded(firstId, second), NameTable::LoadResult::Collision);
    EXPECT_EQ(table.lookup(firstId), first);
    EXPECT_EQ(table.collisions(), 2U);
}

TEST_F(NameTableTest, depth)
{
    NameTable table;
    Example example;
    table.toInterned(example.piece);

    EXPECT_EQ(table.depth(idFromText("0baii9v1kj6bk")), 1);  // the box edge
    EXPECT_EQ(table.depth(idFromText("bvlrp12o22fv0")), 2);  // the fillet face
    EXPECT_EQ(table.depth(idFromText("uevcr4g23biai")), 3);  // the edge bounded by it
    auto pieceId = table.internName(example.piece);
    ASSERT_TRUE(pieceId);
    EXPECT_EQ(table.depth(*pieceId), 4);  // the piece: its prefix is 2, its Connected Name 3
}

// ---------------------------------------------------------------------------------------------
// Threads

TEST_F(NameTableTest, parallelInsertsGiveOneEntryPerContent)
{
    // Arrange: the same names in a different order per thread
    NameGenerator generator(31337);
    Strings names;
    for (int i = 0; i < 400; ++i) {
        names.push_back(generator.next());
    }
    NameTable reference;
    Strings expected;
    for (const auto& name : names) {
        expected.push_back(reference.toInterned(name));
    }
    NameTable table;
    constexpr int threadCount = 8;
    std::atomic<int> mismatches {0};

    // Act
    std::vector<std::thread> threads;
    for (int t = 0; t < threadCount; ++t) {
        threads.emplace_back([&, t] {
            std::vector<std::size_t> order(names.size());
            for (std::size_t i = 0; i < order.size(); ++i) {
                order[i] = i;
            }
            std::shuffle(order.begin(), order.end(), std::mt19937(t));
            for (std::size_t i : order) {
                std::string form = table.toInterned(names[i]);
                if (form != expected[i] || table.toPlain(form) != names[i]) {
                    ++mismatches;
                }
            }
        });
    }
    for (auto& thread : threads) {
        thread.join();
    }

    // Assert
    EXPECT_EQ(mismatches, 0);
    EXPECT_EQ(table.size(), reference.size());
    EXPECT_EQ(table.collisions(), 0U);
}

// ---------------------------------------------------------------------------------------------
// Saving and loading (Task 1 PR 7)

namespace
{

// The interned forms of the hand-built names in \a table, and every reference they hold.
Strings internAll(NameTable& table)
{
    Strings forms;
    for (const auto& name : handBuiltNames()) {
        forms.push_back(table.toInterned(name));
    }
    return forms;
}

}  // namespace

namespace
{

Strings exampleNames();  // below

// The references in hash form (`~` and 13 base32hex characters) in \a text.
std::size_t hashRefCount(const std::string& text)
{
    std::size_t count = 0;
    for (std::size_t pos = text.find('~'); pos != std::string::npos;
         pos = text.find('~', pos + 1)) {
        if (NameTable::parseRef(text.substr(pos, NameTable::RefLength))) {
            ++count;
        }
    }
    return count;
}

// \a text in the file form of \a collector.
std::string fileForm(const Data::NameRefCollector& collector,
                     const std::string& text,
                     char next = '\0')
{
    std::string out;
    collector.appendFileForm(out, text, next);
    return out;
}

}  // namespace

TEST_F(NameTableTest, savedEntriesAreClosedInIndexOrderAndLoadElsewhere)
{
    // Arrange: a "saved document" that holds the interned names; its collector sees them
    NameTable source;
    Strings forms = internAll(source);
    Data::NameRefCollector collector;
    for (const auto& form : forms) {
        collector.add(form);
    }

    // Act
    std::size_t unknown = 1;
    auto entries = collector.entries(source, &unknown);
    auto contents = collector.fileEntries(source);
    std::stringstream file;
    NameTable::writeEntries(file, contents);
    std::string text = file.str();
    NameTable loaded;  // another process
    std::vector<NameTable::SavedEntry> read;
    std::vector<NameId> byIndex;
    auto summary = loaded.readEntries(file, &read, &byIndex);

    // Assert: every node of the names, and nothing else (the table holds only theirs)
    EXPECT_EQ(unknown, 0U);
    EXPECT_EQ(entries.size(), source.size());
    EXPECT_EQ(contents.size(), entries.size());
    for (std::size_t i = 0; i < entries.size(); ++i) {
        const auto& [id, content] = entries[i];
        EXPECT_EQ(source.lookup(id), content);
        EXPECT_EQ(collector.indexOf(id).value_or(entries.size()), i);
        // dependencies first: an entry refers only to lower indices
        for (std::size_t pos = content.find('~'); pos != std::string::npos;
             pos = content.find('~', pos + 1)) {
            auto ref = NameTable::parseRef(content.substr(pos, NameTable::RefLength));
            ASSERT_TRUE(ref);
            EXPECT_LT(collector.indexOf(*ref).value_or(i), i) << content;
        }
        EXPECT_EQ(hashRefCount(contents[i]), 0U) << contents[i];
    }
    //   the file: a v2 header, then the contents in file form, no IDs
    EXPECT_EQ(text.rfind("NameTableStart v2 " + std::to_string(entries.size()) + "\n", 0), 0U);
    EXPECT_EQ(hashRefCount(text), 0U);
    EXPECT_EQ(text.find(entries[0].first.toBase32()), std::string::npos);
    //   and it reads back as the source has it
    EXPECT_EQ(summary.inserted, entries.size());
    EXPECT_EQ(summary.identical, 0U);
    EXPECT_TRUE(summary.refused.empty());
    EXPECT_EQ(summary.malformed, 0U);
    EXPECT_EQ(read, entries);
    ASSERT_EQ(byIndex.size(), entries.size());
    for (std::size_t i = 0; i < entries.size(); ++i) {
        EXPECT_EQ(byIndex[i], entries[i].first);
    }
    for (std::size_t i = 0; i < forms.size(); ++i) {
        EXPECT_EQ(loaded.toPlain(forms[i]), handBuiltNames()[i]);
    }
}

TEST_F(NameTableTest, savedEntriesOfSomeNamesOnly)
{
    // Arrange: the table holds more than the saved names need
    NameTable table;
    Example example;
    std::string piece = table.toInterned(example.piece);
    std::string edge = table.toInterned(example.edge);  // one section, no embedded names
    internAll(table);
    Data::NameRefCollector collector;
    collector.add(piece);
    collector.add(edge);

    // Act
    auto contents = collector.fileEntries(table);
    std::stringstream file;
    NameTable::writeEntries(file, contents);
    NameTable loaded;
    loaded.readEntries(file);

    // Assert: the piece's prefix (the face), the face's edge, the piece's upper edge, and that
    // edge's face again: 3 nodes
    EXPECT_EQ(edge, example.edge);
    EXPECT_EQ(contents.size(), 3U);
    EXPECT_LT(contents.size(), table.size());
    EXPECT_EQ(loaded.toPlain(piece), example.piece);
}

TEST_F(NameTableTest, savedEntriesCountUnknownReferences)
{
    // Arrange
    NameTable table;
    std::string face = table.toInterned(Example().face);
    Data::NameRefCollector collector;
    collector.add(face);
    std::string unknownRef = "~vvvvvvvvvvvvu";
    collector.add("Sub.;" + unknownRef + "|_;_;3;CUT;0;F;0;MOD;_.Face1");  // not in the table
    collector.add("~notanidatall ~0123 ~");  // not references

    // Act
    std::size_t unknown = 0;
    auto entries = collector.entries(table, &unknown);

    // Assert: the unknown reference has no index and keeps its hash form in the file
    EXPECT_EQ(collector.refs().size(), 2U);
    EXPECT_EQ(unknown, 1U);
    EXPECT_EQ(entries.size(), 1U);
    EXPECT_EQ(fileForm(collector, unknownRef + "|x"), unknownRef + "|x");
}

TEST_F(NameTableTest, collectorNumbersTheMapsFirstAndTheRestAfter)
{
    // ops#6 T2: a save numbers the references of its maps (bind()) before the XML's
    // Arrange
    NameTable table;
    Example example;
    std::string upper = table.toInterned(example.upper);  // refers to the face, which to the edge
    std::string other = table.toInterned(handBuiltNames()[4]);
    Data::NameRefCollector collector;
    collector.add(upper);
    int writer = 0;

    // Act
    collector.bind(&writer, table);
    auto numbered = collector.entries(table).size();
    collector.add(other);
    auto entries = collector.entries(table);

    // Assert: the edge, then the face; the other name's nodes after them, the first ones kept
    EXPECT_TRUE(collector.isBound());
    ASSERT_EQ(numbered, 2U);
    EXPECT_EQ(entries[0].first, *table.internName(example.edge));
    EXPECT_EQ(entries[1].first, *table.internName(example.face));
    EXPECT_GT(entries.size(), numbered);
    std::string expected = upper;
    expected.replace(upper.find('~'), NameTable::RefLength, "~1");
    EXPECT_EQ(fileForm(collector, upper), expected);
}

TEST_F(NameTableTest, fileFormWritesIndicesAndTheRemapReadsThemBack)
{
    // Arrange: the example's names saved through a collector, read by another process
    NameTable source;
    Strings forms;
    Data::NameRefCollector collector;
    for (const auto& name : exampleNames()) {
        forms.push_back(source.toInterned(name));
        collector.add(forms.back());
    }
    std::stringstream file;
    NameTable::writeEntries(file, collector.fileEntries(source));
    NameTable process;
    Data::NameRemap remap(process);
    remap.load(file);

    for (std::size_t i = 0; i < forms.size(); ++i) {
        // Act
        std::string saved = fileForm(collector, forms[i]);
        std::string name = saved;
        std::string text = saved;
        auto result = remap.remapMapName(name);
        bool changed = remap.fromFileForm(text);

        // Assert
        EXPECT_EQ(hashRefCount(saved), 0U) << saved;
        EXPECT_LT(saved.size(), forms[i].size());
        EXPECT_EQ(result, Data::NameRemap::MapName::Changed);
        EXPECT_EQ(name, forms[i]);
        EXPECT_TRUE(changed);
        EXPECT_EQ(text, forms[i]);
        EXPECT_EQ(process.toPlain(name), exampleNames()[i]);
        //   hash forms are kept as they are
        std::string hashForm = forms[i];
        EXPECT_FALSE(remap.fromFileForm(hashForm));
        EXPECT_EQ(remap.remapMapName(hashForm), Data::NameRemap::MapName::Unchanged);
    }
    EXPECT_EQ(remap.unknownCount(), 0U);
}

TEST_F(NameTableTest, fileFormNeverPutsAnIndexBeforeADigit)
{
    // A name's data is written apart from its postfix: a reference that ends the data and is
    // followed by a base32hex character in the name stays in hash form, and the reader leaves
    // a run followed by one alone
    // Arrange
    NameTable table;
    std::string face = table.toInterned(Example().face);  // `_;~<edge>;7;...`
    std::string data = face.substr(0, 2 + NameTable::RefLength);  // `_;~<edge>`
    Data::NameRefCollector collector;
    collector.add(face);
    collector.entries(table);
    std::stringstream file;
    NameTable::writeEntries(file, collector.fileEntries(table));
    Data::NameRemap remap(table);
    remap.load(file);

    // Act and assert
    EXPECT_EQ(fileForm(collector, data, ';'), "_;~0");
    EXPECT_EQ(fileForm(collector, data), "_;~0");
    for (char next : {'0', '7', 'a', 'v'}) {
        EXPECT_EQ(fileForm(collector, data, next), data) << next;
        std::string indexed = "_;~0";
        EXPECT_FALSE(remap.fromFileForm(indexed, next)) << next;
    }
    std::string indexed = "_;~0";
    EXPECT_TRUE(remap.fromFileForm(indexed, ';'));
    EXPECT_EQ(indexed, data);
    //   a run with letters, or of 13 characters, is no index
    for (std::string text : {"~0a;", "~0123456789012;", "~!0;", "~;"}) {
        EXPECT_FALSE(remap.fromFileForm(text)) << text;
    }
}

TEST_F(NameTableTest, readEntriesTakesWindowsLineEndsAndCountsMalformedLines)
{
    // Arrange: entry 0 is the edge, 1 the face (refers to 0); 2 is empty, 3 has a space, 4
    // refers to itself, 5 to the empty line, 6 to an index past the end
    Example example;
    NameTable source;
    std::string face = source.toInterned(example.face);
    std::string upper = source.toInterned(example.upper);
    NameId edgeId = *source.internName(example.edge);
    NameId faceId = *source.internName(example.face);
    std::string faceFile = face;
    faceFile.replace(face.find('~'), NameTable::RefLength, "~0");
    std::string other = section({"g2"}, {}, "3", "SKT", "0", 'E', {"SRC"}, {});
    std::stringstream file;
    file << "NameTableStart v2 7\r\n"  // a file with Windows line ends reads the same
         << example.edge << "\r\n"
         << faceFile << "\r\n"
         << "\r\n"
         << other << " x\n"
         << "_;~4;1;CUT;0;E;0;MOD;_\n"
         << "_;~2;2;CUT;0;E;0;MOD;_\n"
         << "_;~99;3;CUT;0;E;0;MOD;_\n";

    // Act
    NameTable loaded;
    Data::NameRemap remap(loaded);
    auto summary = remap.load(file);

    // Assert: five entries load; the two bad lines and the references to the entry itself and
    // past the end count (the one to the empty line refers to its stand-in)
    EXPECT_EQ(summary.inserted, 5U);
    EXPECT_TRUE(summary.refused.empty());
    EXPECT_EQ(summary.malformed, 4U);
    EXPECT_EQ(loaded.lookup(faceId), face);
    EXPECT_EQ(loaded.toPlain(face), example.face);
    EXPECT_FALSE(remap.isUnknown(edgeId));
    EXPECT_FALSE(remap.isUnknown(faceId));
    //   a map name using a bad line or index is unknown: missing, never another name
    for (std::string name : {"~2|_;_;1;X;0;F;0;Y;_",
                             "_;~4;9;FLT;0;F;0;GEN;_",
                             "_;~7;1;FLT;0;F;0;GEN;_",
                             "_;~6;1;FLT;0;F;0;GEN;_"}) {
        EXPECT_EQ(remap.remapMapName(name), Data::NameRemap::MapName::Changed);
        EXPECT_NE(name.find("~!"), std::string::npos) << name;
    }
    std::string good = upper;
    good.replace(good.find('~'), NameTable::RefLength, "~1");
    EXPECT_EQ(remap.remapMapName(good), Data::NameRemap::MapName::Changed);
    EXPECT_EQ(loaded.toPlain(good), example.upper);
}

TEST_F(NameTableTest, readEntriesOfAnotherFormatReadsNothing)
{
    NameTable table;
    std::stringstream file("NameTableStart v1 1\n0123456789abc x\n");
    auto summary = table.readEntries(file);
    EXPECT_EQ(summary.inserted, 0U);
    EXPECT_EQ(table.size(), 0U);
}

TEST_F(NameTableTest, fileFormScopeFindsTheCollectorBoundToItsWriter)
{
    int first = 0;
    int second = 0;
    EXPECT_EQ(Data::NameRefCollector::fileForm(), nullptr);
    Data::NameRefCollector outer;
    {
        Data::NameRefCollector::FileFormScope scope(&first);
        EXPECT_EQ(Data::NameRefCollector::fileForm(), nullptr) << "not bound";
    }
    NameTable table;
    outer.bind(&first, table);
    {
        Data::NameRefCollector inner;  // another document's save, inside this one
        inner.bind(&second, table);
        Data::NameRefCollector::FileFormScope scope(&first);
        EXPECT_EQ(Data::NameRefCollector::fileForm(), &outer);
        {
            Data::NameRefCollector::FileFormScope innerScope(&second);
            EXPECT_EQ(Data::NameRefCollector::fileForm(), &inner);
        }
        EXPECT_EQ(Data::NameRefCollector::fileForm(), &outer);
    }
    {
        Data::NameRefCollector::FileFormScope scope(&second);
        EXPECT_EQ(Data::NameRefCollector::fileForm(), nullptr) << "inner is gone";
    }
    EXPECT_EQ(Data::NameRefCollector::fileForm(), nullptr);
}

TEST_F(NameTableTest, collectorIsActiveWhileItLives)
{
    EXPECT_EQ(Data::NameRefCollector::active(), nullptr);
    {
        Data::NameRefCollector outer;
        EXPECT_EQ(Data::NameRefCollector::active(), &outer);
        {
            Data::NameRefCollector inner;
            EXPECT_EQ(Data::NameRefCollector::active(), &inner);
        }
        EXPECT_EQ(Data::NameRefCollector::active(), &outer);
    }
    EXPECT_EQ(Data::NameRefCollector::active(), nullptr);
}

TEST_F(NameTableTest, scanBufferPassesEverythingOnAndFindsSplitReferences)
{
    // Arrange: references at the start, in the middle and at the end, written in pieces of
    // every size, so that each is split at every position across writes
    NameTable table;
    Example example;
    std::string piece = table.toInterned(example.piece);
    std::string text = "<Sub value=\"Pad.;" + piece + ".Face3\" shadow=\"" + piece + "\"/>"
        + piece.substr(0, NameTable::RefLength);
    std::set<NameId> expected;
    for (std::size_t pos = text.find('~'); pos != std::string::npos; pos = text.find('~', pos + 1)) {
        expected.insert(*NameTable::parseRef(text.substr(pos, NameTable::RefLength)));
    }
    ASSERT_EQ(expected.size(), 2U);

    for (std::size_t chunk = 1; chunk <= text.size(); ++chunk) {
        Data::NameRefCollector collector;
        std::stringbuf target;
        std::ostream stream(&target);
        Data::NameRefScanBuffer buffer(&target, collector);
        stream.rdbuf(&buffer);

        // Act
        for (std::size_t pos = 0; pos < text.size(); pos += chunk) {
            if (chunk == 1) {
                stream.put(text[pos]);
            }
            else {
                stream << text.substr(pos, chunk);
            }
        }
        stream.flush();

        // Assert
        EXPECT_EQ(target.str(), text) << chunk;
        EXPECT_EQ(collector.refs(), expected) << chunk;
    }
}

// ---------------------------------------------------------------------------------------------
// Loading: the remap of a file's names (Task 1 PR 8)

namespace
{

// A file's entries for the interned forms of \a names in \a source; \a forms gets the forms.
std::string savedFile(NameTable& source, const Strings& names, Strings& forms)
{
    Data::NameRefCollector collector;
    for (const auto& name : names) {
        forms.push_back(source.toInterned(name));
        collector.add(forms.back());
    }
    std::stringstream file;
    NameTable::writeEntries(file, collector.fileEntries(source));
    return file.str();
}

// The example's face, its upper edge and its split piece: each embeds the edge.
Strings exampleNames()
{
    Example example;
    return {example.face, example.upper, example.piece};
}

// The ID of the example's edge, the node the other names embed.
NameId edgeId(NameTable& table)
{
    return *table.internName(Example().edge);
}

bool refersTo(const std::string& text, const NameId& id)
{
    return text.find(NameTable::makeRef(id)) != std::string::npos;
}

// The mapped name in a subname `<path>.;<mapped>.<element>`.
std::string mappedPart(const std::string& subname, const std::string& element)
{
    auto start = subname.find(';') + 1;
    return subname.substr(start, subname.size() - start - element.size() - 1);
}

}  // namespace

TEST_F(NameTableTest, remapLeavesNamesAloneWithoutCollisions)
{
    // Arrange
    NameTable source;
    Strings forms;
    std::stringstream file(savedFile(source, exampleNames(), forms));
    NameTable process;

    // Act
    Data::NameRemap remap(process);
    auto summary = remap.load(file);

    // Assert
    EXPECT_TRUE(summary.refused.empty());
    EXPECT_EQ(remap.inlineCount(), 0U);
    for (std::size_t i = 0; i < forms.size(); ++i) {
        std::string name = forms[i];
        std::string subname = "Body.Pad.;" + forms[i] + ".Face1";
        EXPECT_EQ(remap.remapMapName(name), Data::NameRemap::MapName::Unchanged);
        EXPECT_FALSE(remap.remapText(subname));
        EXPECT_FALSE(remap.remapSubName(subname));
        EXPECT_EQ(process.toPlain(name), exampleNames()[i]);
    }
    EXPECT_EQ(remap.unknownCount(), 0U);
    EXPECT_EQ(Data::NameRemap::active(), &remap);
}

TEST_F(NameTableTest, remapKeepsCollidingNamesInlineAsTheFileMeansThem)
{
    // Arrange: this process holds other content under the ID of the file's edge
    NameTable source;
    Strings forms;
    std::stringstream file(savedFile(source, exampleNames(), forms));
    NameTable process;
    NameId edge = edgeId(source);
    ASSERT_TRUE(process.insertForTesting(edge, "Other;_;1;XYZ;0;E;0;_;_"));

    // Act
    Data::NameRemap remap(process);
    auto summary = remap.load(file);

    // Assert: the edge is refused, and every entry above it (face, upper edge) is inline
    ASSERT_EQ(summary.refused.size(), 1U);
    EXPECT_EQ(summary.refused[0].first, edge);
    EXPECT_TRUE(remap.isInline(edge));
    EXPECT_EQ(remap.inlineCount(), 3U);  // edge, face, upper edge
    NameId face = *source.internName(Example().face);
    std::string faceName = forms[0];
    remap.remapMapName(faceName);
    EXPECT_NE(faceName.find('^'), std::string::npos) << "the edge inline: " << faceName;
    Strings plains = exampleNames();
    for (std::size_t i = 0; i < forms.size(); ++i) {
        const std::string& plain = plains[i];
        EXPECT_NE(process.toPlain(forms[i]), plain) << "without the remap, another name";

        std::string name = forms[i];
        EXPECT_EQ(remap.remapMapName(name), Data::NameRemap::MapName::Changed);
        EXPECT_EQ(process.toPlain(name), plain);
        EXPECT_FALSE(refersTo(name, edge)) << name;
        EXPECT_FALSE(refersTo(name, face)) << name;

        std::string subname = "Body.Pad.;" + forms[i] + ".Face1";
        EXPECT_TRUE(remap.remapText(subname));
        EXPECT_EQ(process.toPlain(mappedPart(subname, "Face1")), plain);
        EXPECT_FALSE(refersTo(subname, edge));
        EXPECT_FALSE(remap.remapSubName(subname)) << "nothing left to remap";
    }
    EXPECT_EQ(remap.unknownCount(), 0U);
}

TEST_F(NameTableTest, remapMakesReferencesTheFileLacksUnresolvable)
{
    // Arrange: the file lacks the edge's entry, which this process knows, with its real content:
    // the saving process had every entry but the edge (its references to it stay in hash form)
    NameTable source;
    Strings forms;
    for (const auto& name : exampleNames()) {
        forms.push_back(source.toInterned(name));
    }
    NameId edge = edgeId(source);
    NameTable saving;
    Data::NameRefCollector collector;
    for (const auto& form : forms) {
        collector.add(form);
        for (std::size_t pos = form.find('~'); pos != std::string::npos;
             pos = form.find('~', pos + 1)) {
            NameId id = *NameTable::parseRef(form.substr(pos, NameTable::RefLength));
            if (id != edge) {
                saving.insertForTesting(id, *source.lookup(id));
            }
        }
    }
    std::size_t unknown = 0;
    std::stringstream file;
    NameTable::writeEntries(file, collector.fileEntries(saving, &unknown));
    ASSERT_EQ(unknown, 1U);
    NameTable process;
    ASSERT_TRUE(process.insertForTesting(edge, *source.lookup(edge)));

    // Act
    Data::NameRemap remap(process);
    remap.load(file);

    // Assert: the edge and the entries above it are unknown; names that use them don't resolve
    EXPECT_TRUE(remap.isUnknown(edge));
    NameId face = *source.internName(Example().face);
    EXPECT_TRUE(remap.isUnknown(face)) << "it refers to the edge";
    for (std::size_t i = 0; i < forms.size(); ++i) {
        std::string subname = "Body.Pad.;" + forms[i] + ".Face1";
        EXPECT_TRUE(remap.remapSubName(subname));
        EXPECT_NE(subname.find("~!"), std::string::npos);
        EXPECT_NE(process.toPlain(mappedPart(subname, "Face1")), exampleNames()[i]);

        std::string name = forms[i];
        EXPECT_EQ(remap.remapMapName(name), Data::NameRemap::MapName::Changed);
        EXPECT_NE(process.toPlain(name), exampleNames()[i]);
        EXPECT_NE(name.find("~!"), std::string::npos);
    }
    EXPECT_GE(remap.unknownCount(), 1U);
    // Text that isn't a name keeps what looks like a reference
    std::string label = "Note " + NameTable::makeRef(edge);
    EXPECT_FALSE(remap.remapText(label));
}

TEST_F(NameTableTest, remapOfANewerFormatDropsMapsAndKnowsNoReference)
{
    // Arrange
    NameTable source;
    Strings forms;
    std::stringstream file(savedFile(source, exampleNames(), forms));
    NameTable process;
    Data::NameRemap remap(process);
    remap.load(file);

    // Act
    remap.setNewerFormat();

    // Assert
    std::string name = forms[0];
    EXPECT_EQ(remap.remapMapName(name), Data::NameRemap::MapName::Dropped);
    EXPECT_EQ(remap.droppedCount(), 1U);
    std::string plain = Example().edge;
    EXPECT_EQ(remap.remapMapName(plain), Data::NameRemap::MapName::Unchanged);
    std::string subname = "Body.Pad.;" + forms[0] + ".Face1";
    EXPECT_TRUE(remap.remapSubName(subname));
    EXPECT_EQ(subname.find(forms[0].substr(2, NameTable::RefLength)), std::string::npos);
}

TEST_F(NameTableTest, remapIsActiveWhileItLivesAndInnerOnesWin)
{
    EXPECT_EQ(Data::NameRemap::active(), nullptr);
    {
        Data::NameRemap outer;
        {
            Data::NameRemap inner;
            EXPECT_EQ(Data::NameRemap::active(), &inner);
        }
        EXPECT_EQ(Data::NameRemap::active(), &outer);
    }
    EXPECT_EQ(Data::NameRemap::active(), nullptr);
}

TEST_F(NameTableTest, attributeFilterRemapsWhatItsReaderReadsAfterwards)
{
    // Arrange: a collision as above, and an XML text holding the face as a subname twice
    NameTable source;
    Strings forms;
    std::stringstream file(savedFile(source, exampleNames(), forms));
    NameTable process;
    ASSERT_TRUE(process.insertForTesting(edgeId(source), "Other;_;1;XYZ;0;E;0;_;_"));
    Data::NameRemap remap(process);
    remap.load(file);
    std::string subname = "Body.Pad.;" + forms[0] + ".Face1";
    std::string xml = "<?xml version='1.0' encoding='utf-8'?>\n<Document><A v=\"" + subname
        + "\"/><B v=\"" + subname + "\"/></Document>\n";
    std::istringstream stream(xml);
    std::istringstream otherStream(xml);
    Base::XMLReader reader("<memory>", stream);
    Base::XMLReader other("<memory>", otherStream);

    // Act
    reader.readElement("A");
    std::string before = reader.getAttribute<const char*>("v");
    remap.filterAttributes(reader);
    reader.readElement("B");
    std::string after = reader.getAttribute<const char*>("v");
    other.readElement("B");
    std::string unfiltered = other.getAttribute<const char*>("v");

    // Assert
    std::string expected = subname;
    remap.remapText(expected);
    EXPECT_EQ(before, subname);
    EXPECT_EQ(after, expected);
    EXPECT_NE(after, subname);
    EXPECT_EQ(unfiltered, subname) << "only the remap's reader is filtered";
}
