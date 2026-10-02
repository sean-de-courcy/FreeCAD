// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <App/MappedName.h>
#include <App/NameId.h>
#include <App/NameTable.h>

#include "InitApplication.h"

#include <algorithm>
#include <atomic>
#include <map>
#include <random>
#include <set>
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
