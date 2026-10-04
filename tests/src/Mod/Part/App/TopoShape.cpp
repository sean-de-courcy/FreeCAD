// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>
#include "PartTestHelpers.h"
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/NameSetOrder.h>
#include <Mod/Part/App/TopoShapeOpCode.h>
#include "src/App/InitApplication.h"

#include <App/ElementMap.h>
#include <App/NameTable.h>
#include <BRepPrimAPI_MakeBox.hxx>
#include <algorithm>
#include <random>
#include <type_traits>
#include <cstring>
#include <new>
#include <set>


class TopoShapeTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        Base::Interpreter().runString("import Part");
        _docName = App::GetApplication().getUniqueDocumentName("test");
        App::GetApplication().newDocument(_docName.c_str(), "testUser");
        _hasher = Base::Reference<App::StringHasher>(new App::StringHasher);
        ASSERT_EQ(_hasher.getRefCount(), 1);
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }


private:
    std::string _docName;
    Data::ElementIDRefs _sid;
    App::StringHasherRef _hasher;
};

// clang-format off
TEST_F(TopoShapeTest, TestElementTypeFace1)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Face1"),
              std::make_pair(std::string("Face"), 1UL));
}

TEST_F(TopoShapeTest, TestElementTypeEdge12)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Edge12"),
              std::make_pair(std::string("Edge"), 12UL));
}

TEST_F(TopoShapeTest, TestElementTypeVertex3)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Vertex3"),
              std::make_pair(std::string("Vertex"), 3UL));
}

TEST_F(TopoShapeTest, TestElementTypeFacer)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Facer"),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeVertex)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Vertex"),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeEmpty)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex(""),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeNull)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex(nullptr),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeWithHash)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex(";#7:1;:G0;XTR;:H11a6:8,F.Face3"),
              std::make_pair(std::string("Face"), 3UL));
}

TEST_F(TopoShapeTest, TestElementTypeWithSubelements)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Part.Body.Pad.Face3"),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeNonMatching)
{
    for (std::array elements = {"Face0", "Face01", "XFace3", "Face3extra"};
         const auto& element : elements) {
        EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex(element),
                  std::make_pair(std::string(), 0UL));
    }
}

TEST_F(TopoShapeTest, TestTypeFace1)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Face1"),
              std::make_pair(std::string("Face"), 1UL));
}

TEST_F(TopoShapeTest, TestTypeEdge12)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Edge12"),
              std::make_pair(std::string("Edge"), 12UL));
}

TEST_F(TopoShapeTest, TestTypeVertex3)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Vertex3"),
              std::make_pair(std::string("Vertex"), 3UL));
}

TEST_F(TopoShapeTest, TestTypeFacer)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Facer"),
              std::make_pair(std::string("Facer"), 0UL));
}

TEST_F(TopoShapeTest, TestTypeVertex)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Vertex"),
              std::make_pair(std::string("Vertex"), 0UL));
}

TEST_F(TopoShapeTest, TestTypeEmpty)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex(""),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestTypeNull)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex(nullptr),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestGetSubshape)
{
    // Arrange
    auto [cube1, cube2] = PartTestHelpers::CreateTwoTopoShapeCubes();
    // Act
    auto face = cube1.getSubShape("Face2");
    auto vertex = cube2.getSubShape(TopAbs_VERTEX,2);
    auto silentFail = cube1.getSubShape("NotThere", true);
    // Assert
    EXPECT_EQ(face.ShapeType(), TopAbs_FACE);
    EXPECT_EQ(vertex.ShapeType(), TopAbs_VERTEX);
    EXPECT_TRUE(silentFail.IsNull());
    EXPECT_THROW(cube1.getSubShape("Face7"), Base::IndexError);          // Out of range
    EXPECT_THROW(cube1.getSubShape("WOOHOO", false), Base::ValueError);  // Invalid
}

// clang-format on

// The element map works by the algorithm of the shape that holds it, however many copies of
// the shape come and go (ops#17). The tests name a box's faces; the names are made up. What
// shows the algorithm: V1 renames a second element given an existing name ("D1", the first
// duplicate), V2 does it another way.

namespace
{
const Data::IndexedName face1("Face", 1);
const Data::IndexedName face2("Face", 2);
}  // namespace

TEST_F(TopoShapeTest, duplicateNameV1)
{
    // Arrange
    Part::TopoShape shape(App::HistoryAlgorithm::V1, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
    shape.setElementName(face1, Data::MappedName("A"), shape.Tag);

    // Act
    shape.setElementName(face2, Data::MappedName("A"), shape.Tag);

    // Assert
    EXPECT_EQ(shape.getMappedName(face1).toString(), "A");
    EXPECT_EQ(shape.getMappedName(face2).toString(), "A;D1");
}

TEST_F(TopoShapeTest, mapKeepsV1WhenACopyDies)
{
    // Arrange
    Part::TopoShape shape(App::HistoryAlgorithm::V1, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
    shape.setElementName(face1, Data::MappedName("A"), shape.Tag);

    // Act
    //   a copy shares the map, and dies
    {
        Part::TopoShape copy(shape);
    }
    shape.setElementName(face2, Data::MappedName("A"), shape.Tag);

    // Assert
    EXPECT_EQ(shape.getMappedName(face2).toString(), "A;D1");
}

TEST_F(TopoShapeTest, mapKeepsV1WhenASubShapeDies)
{
    // Arrange
    Part::TopoShape shape(App::HistoryAlgorithm::V1, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
    shape.setElementName(face1, Data::MappedName("A"), shape.Tag);

    // Act
    //   a sub-shape gets its names through the shape's map, and dies
    EXPECT_TRUE(shape.getSubTopoShape(TopAbs_FACE, 1).getMappedName(face1));
    shape.setElementName(face2, Data::MappedName("A"), shape.Tag);

    // Assert
    EXPECT_EQ(shape.getMappedName(face2).toString(), "A;D1");
}

TEST_F(TopoShapeTest, mapKeepsV1WhenAnotherShapeLetsItGo)
{
    // Arrange
    Part::TopoShape shape(App::HistoryAlgorithm::V1, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
    shape.setElementName(face1, Data::MappedName("A"), shape.Tag);
    //   another shape, in storage the test controls
    alignas(Part::TopoShape) unsigned char storage[sizeof(Part::TopoShape)];
    auto* other = new (storage) Part::TopoShape(App::HistoryAlgorithm::V2);

    // Act
    //   the other shape takes the map, lets it go again and dies; its storage is reused
    *other = shape;
    *other = Part::TopoShape(App::HistoryAlgorithm::V2);
    other->~TopoShape();
    std::memset(storage, 0xFF, sizeof(storage));
    shape.setElementName(face2, Data::MappedName("A"), shape.Tag);

    // Assert
    EXPECT_EQ(shape.getMappedName(face2).toString(), "A;D1");
}

TEST_F(TopoShapeTest, setElementMapUsesTheShapesAlgorithm)
{
    // Arrange: the shape's element map is made from a list with a duplicate name
    Part::TopoShape shape(App::HistoryAlgorithm::V1, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
    std::vector<Data::MappedElement> names {
        {Data::MappedName("A"), face1},
        {Data::MappedName("A"), face2},
    };

    // Act
    shape.setElementMap(names);

    // Assert
    EXPECT_EQ(shape.getMappedName(face1).toString(), "A");
    EXPECT_EQ(shape.getMappedName(face2).toString(), "A;D1");
}

TEST_F(TopoShapeTest, retagAfterCopyDiesV2)
{
    // Arrange
    //   pattern: code builds a face without a tag from a wire (tag 7); an object (tag 21) takes
    //   it. The face is new (last section's tag 0, not yet tagged); its edge keeps the wire's name.
    Part::TopoShape shape(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 0L);
    Data::IndexedName edge1("Edge", 1);
    auto edgeName = Data::MappedName::makeUnmappedName({"Edge1"}, 7, "RTG", 'E');
    auto faceName = Data::MappedName::makeEncodedSection(
        std::vector<std::string> {},
        std::vector<Data::MappedName> {edgeName},
        0,
        "RTG",
        0,
        'F',
        0,
        {Data::MAPPER_FLAG_GENERATED},
        std::vector<Data::MappedName> {}
    );
    shape.setElementName(edge1, edgeName, 0);
    shape.setElementName(face1, Data::MappedName(faceName), 0);

    // Act
    //   a copy shares the map, and dies before the retag
    { Part::TopoShape copy(shape); }
    shape.reTagElementMap(21, nullptr);

    // Assert
    EXPECT_EQ(faceName, "_;Edge1^;_^;7^;RTG^;0^;E^;0^;IDX^,SRC^;_;0;RTG;0;F;0;GEN;_");
    EXPECT_EQ(shape.getMappedName(face1).toString(),
              "_;Edge1^;_^;7^;RTG^;0^;E^;0^;IDX^,SRC^;_;21;RTG;0;F;0;GEN;_");
    //   the edge is the wire's, not new: it keeps its name
    EXPECT_EQ(shape.getMappedName(edge1), edgeName);
}

TEST_F(TopoShapeTest, retagLeavesTheCopiesNamesV2)
{
    // Arrange
    //   pattern: code builds a face without a tag from a wire (tag 7), and two objects (tags 21
    //   and 22) take copies of it. The copies share the face's element map (ops#34).
    Part::TopoShape shape(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 0L);
    Data::IndexedName edge1("Edge", 1);
    auto edgeName = Data::MappedName::makeUnmappedName({"Edge1"}, 7, "RTG", 'E');
    auto faceNameWithTag = [&](long tag) {
        return Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            std::vector<Data::MappedName> {edgeName},
            tag,
            "RTG",
            0,
            'F',
            0,
            {Data::MAPPER_FLAG_GENERATED},
            std::vector<Data::MappedName> {}
        );
    };
    shape.setElementName(edge1, edgeName, 0);
    shape.setElementName(face1, Data::MappedName(faceNameWithTag(0)), 0);
    Part::TopoShape first(shape);
    Part::TopoShape second(shape);

    // Act
    first.reTagElementMap(21, nullptr);
    second.reTagElementMap(22, nullptr);

    // Assert
    //   each copy has its own tag, and the shape they were copied from is still untagged
    EXPECT_EQ(first.getMappedName(face1).toString(), faceNameWithTag(21));
    EXPECT_EQ(first.getIndexedName(Data::MappedName(faceNameWithTag(21))), face1);
    EXPECT_EQ(second.getMappedName(face1).toString(), faceNameWithTag(22));
    EXPECT_EQ(shape.getMappedName(face1).toString(), faceNameWithTag(0));
    EXPECT_EQ(shape.getIndexedName(Data::MappedName(faceNameWithTag(0))), face1);
    //   the edge is the wire's, not new: it keeps its name everywhere
    EXPECT_EQ(first.getMappedName(edge1), edgeName);
    EXPECT_EQ(second.getMappedName(edge1), edgeName);
    EXPECT_EQ(shape.getMappedName(edge1), edgeName);
}

TEST_F(TopoShapeTest, retagNamesAShapeWithoutMapUnderItsOldTagV1)
{
    // Arrange
    //   pattern: an object (tag 21) takes another object's shape (tag 7) that has no element map,
    //   as a Body takes its tip's. V1 names its elements as children of the old tag (ops#35).
    Part::TopoShape shape(App::HistoryAlgorithm::V1, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    ASSERT_EQ(shape.getElementMapSize(), 0);

    // Act
    shape.reTagElementMap(21, nullptr);

    // Assert
    //   every element is named '<element>;:H<old tag, hex>,<type>', as FreeCAD 1.1.3 names it
    EXPECT_EQ(shape.Tag, 21);
    for (const char* type : {"Face", "Edge", "Vertex"}) {
        const auto count = static_cast<int>(shape.countSubElements(type));
        for (int index = 1; index <= count; ++index) {
            Data::IndexedName element(type, index);
            EXPECT_EQ(shape.getMappedName(element).toString(),
                      element.toString() + ";:H7," + type[0]);
        }
    }
    EXPECT_EQ(shape.getElementMapSize(), 26);
}

TEST_F(TopoShapeTest, retagNamesAShapeWithoutMapV2)
{
    // Arrange
    //   pattern: a Link in another document (tag 2) takes an object's shape (tag 1) that has no
    //   element map, e.g. a Part primitive's (ops#41)
    Part::TopoShape shape(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
    ASSERT_EQ(shape.getElementMapSize(), 0);

    // Act
    shape.reTagElementMap(2, nullptr);

    // Assert
    //   every element is named as mapSubElement() names a single shape's:
    //   '<element>;_;<old tag>;MKR;0;<type>;0;IDX,SRC;_', as a Body names a map-less tip's (ops#35)
    EXPECT_EQ(shape.Tag, 2);
    std::set<std::string> names;
    for (const char* type : {"Face", "Edge", "Vertex"}) {
        const auto count = static_cast<int>(shape.countSubElements(type));
        for (int index = 1; index <= count; ++index) {
            Data::IndexedName element(type, index);
            const auto name = shape.getMappedName(element).toString();
            EXPECT_EQ(name,
                      Data::MappedName::makeEncodedSection(
                          {element.toString()}, std::vector<Data::MappedName> {}, 1, "MKR", 0,
                          type[0], 0, {"IDX", "SRC"}));
            names.insert(name);
        }
    }
    EXPECT_EQ(shape.getElementMapSize(), 26);
    EXPECT_EQ(names.size(), 26);
}

TEST_F(TopoShapeTest, retagAppendsBoundarySectionV2)
{
    // ops#56: a shape that crosses into another document (the external postfix, as an App::Link,
    // a path hop or a SubShapeBinder there passes it) gets a boundary section on every name,
    // tagged with the local object: `<name>|_;_;<tag>;EXT;0;<type>;0;_;_`
    auto boundary = [](long tag, char type) {
        return std::string(Data::NAME_SECTION_DELIMINATOR) + "_;_;" + std::to_string(tag)
            + ";EXT;0;" + type + ";0;_;_";
    };
    auto unmapped = [](const Data::IndexedName& element, long tag) {
        return Data::MappedName::makeEncodedSection(
            {element.toString()}, std::vector<Data::MappedName> {}, static_cast<int>(tag), "MKR",
            0, element.getType()[0], 0, {"IDX", "SRC"});
    };
    //   a shape with a map (tag 5): its face's name, and a second name of the same face
    Part::TopoShape mapped(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 5L);
    auto name = Data::MappedName::makeUnmappedName({"Face1"}, 5, "XTR", 'F');
    auto second = Data::MappedName::makeUnmappedName({"Face1"}, 5, "PSM", 'F');
    mapped.setElementName(face1, name, 5);
    mapped.setElementName(face1, second, 5);

    // Act and assert
    //   across documents: every name gets the section, in the element's order
    Part::TopoShape linked(mapped);
    linked.reTagElementMap(7, nullptr, Data::POSTFIX_EXTERNAL_TAG);
    EXPECT_EQ(linked.Tag, 7);
    auto names = linked.getElementMappedNames(face1);
    ASSERT_EQ(names.size(), 2);
    EXPECT_EQ(names[0].first.toString(), name.toString() + boundary(7, 'F'));
    EXPECT_EQ(names[1].first.toString(), second.toString() + boundary(7, 'F'));
    //   the shape it was copied from keeps its names
    EXPECT_EQ(mapped.getMappedName(face1), name);
    //   with a link array's postfix after the external one, as a Link passes it
    Part::TopoShape element(mapped);
    const std::string arrayPostfix =
        std::string(Data::POSTFIX_EXTERNAL_TAG) + Data::ELEMENT_MAP_PREFIX + ":I2";
    element.reTagElementMap(7, nullptr, arrayPostfix.c_str());
    EXPECT_EQ(element.getMappedName(face1).toString(), name.toString() + boundary(7, 'F'));
    //   within a document, without a postfix or with a link array's: unchanged
    Part::TopoShape local(mapped);
    local.reTagElementMap(7, nullptr);
    EXPECT_EQ(local.getMappedName(face1), name);
    Part::TopoShape arrayElement(mapped);
    arrayElement.reTagElementMap(7, nullptr, ";:I2");
    EXPECT_EQ(arrayElement.getMappedName(face1), name);

    //   a shape without a map (tag 1): named as mapSubElement() names it, then the section
    for (long linkTag : {7L, 1L}) {
        // tag 1 to tag 1: the same form, so the names don't depend on the two IDs being equal
        Part::TopoShape box(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
        ASSERT_EQ(box.getElementMapSize(), 0);
        box.reTagElementMap(linkTag, nullptr, Data::POSTFIX_EXTERNAL_TAG);
        EXPECT_EQ(box.Tag, linkTag);
        std::set<std::string> boxNames;
        for (const char* type : {"Face", "Edge", "Vertex"}) {
            const auto count = static_cast<int>(box.countSubElements(type));
            for (int index = 1; index <= count; ++index) {
                Data::IndexedName boxElement(type, index);
                const auto boxName = box.getMappedName(boxElement).toString();
                EXPECT_EQ(boxName, unmapped(boxElement, 1) + boundary(linkTag, type[0]));
                EXPECT_EQ(box.getIndexedName(Data::MappedName(boxName)), boxElement);
                boxNames.insert(boxName);
            }
        }
        EXPECT_EQ(box.getElementMapSize(), 26);
        EXPECT_EQ(boxNames.size(), 26);
    }
    //   within a document, tag 1 to tag 1 names nothing, as before
    Part::TopoShape own(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
    own.reTagElementMap(1, nullptr);
    EXPECT_EQ(own.getElementMapSize(), 0);
    //   V1 keeps its own form: the postfix, no section
    Part::TopoShape v1(App::HistoryAlgorithm::V1, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
    v1.reTagElementMap(7, nullptr, Data::POSTFIX_EXTERNAL_TAG);
    EXPECT_EQ(v1.getMappedName(face1).toString().find("EXT"), std::string::npos);
}

TEST_F(TopoShapeTest, retagWritesTheBoundaryIndexV2)
{
    // ops#112: a SubShapeBinder passes the key of its support's file in the postfix
    // (Part::boundaryPostfix()), and the boundary section carries it as its index, so supports
    // from copies of one file get distinct names. An App::Link's postfix gives index 0.
    auto boundary = [](long tag, const std::string& index, char type) {
        return std::string(Data::NAME_SECTION_DELIMINATOR) + "_;_;" + std::to_string(tag)
            + ";EXT;" + index + ";" + type + ";0;_;_";
    };
    //   the postfix
    const std::string external(Data::POSTFIX_EXTERNAL_TAG);
    EXPECT_EQ(Part::boundaryPostfix("123"), external + ":123");
    EXPECT_EQ(Part::boundaryIndexOf(Part::boundaryPostfix("123").c_str()), "123");
    EXPECT_EQ(Part::boundaryIndexOf(external.c_str()), "0");
    EXPECT_EQ(Part::boundaryIndexOf((external + Data::ELEMENT_MAP_PREFIX + ":I2").c_str()), "0");
    EXPECT_EQ(Part::boundaryIndexOf((external + ":").c_str()), "0");
    EXPECT_EQ(Part::boundaryIndexOf((external + ":12a").c_str()), "0");
    EXPECT_EQ(Part::boundaryIndexOf(";:I2"), "0");
    EXPECT_EQ(Part::boundaryIndexOf(nullptr), "0");

    //   a shape with a map (tag 5), bound from two files
    const auto cube = BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape();
    Part::TopoShape mapped(App::HistoryAlgorithm::V2, cube, 5L);
    auto name = Data::MappedName::makeUnmappedName({"Face1"}, 5, "XTR", 'F');
    mapped.setElementName(face1, name, 5);
    Part::TopoShape fromP1(mapped);
    fromP1.reTagElementMap(7, nullptr, Part::boundaryPostfix("111").c_str());
    Part::TopoShape fromP2(mapped);
    fromP2.reTagElementMap(7, nullptr, Part::boundaryPostfix("222").c_str());
    EXPECT_EQ(fromP1.getMappedName(face1).toString(), name.toString() + boundary(7, "111", 'F'));
    EXPECT_EQ(fromP2.getMappedName(face1).toString(), name.toString() + boundary(7, "222", 'F'));
    //   a shape without a map: named first, then the section with the index
    Part::TopoShape box(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 1L);
    box.reTagElementMap(7, nullptr, Part::boundaryPostfix("111").c_str());
    EXPECT_EQ(box.getElementMapSize(), 26);
    const auto boxName = box.getMappedName(face1).toString();
    EXPECT_TRUE(boxName.ends_with(boundary(7, "111", 'F'))) << boxName;
    EXPECT_EQ(box.getIndexedName(Data::MappedName(boxName)), face1);
    //   the external postfix alone, as a Link passes it: index 0
    Part::TopoShape linked(mapped);
    linked.reTagElementMap(7, nullptr, Data::POSTFIX_EXTERNAL_TAG);
    EXPECT_EQ(linked.getMappedName(face1).toString(), name.toString() + boundary(7, "0", 'F'));
}

TEST_F(TopoShapeTest, internNamesFollowCopiesAndTheMap)
{
    // ops#6, Task 1 PR 4: the interned flag sits next to the shape's algorithm. PR 5: taking an
    // interned map interns the shape, and never clears the map's flag.
    // Arrange
    Part::TopoShape shape(1L);
    auto map = std::make_shared<Data::ElementMap>();
    shape.resetElementMap(map);

    // Act
    shape.setInternNames(true);
    Part::TopoShape copied(shape);
    Part::TopoShape assigned;
    assigned = shape;

    // Assert
    EXPECT_FALSE(Part::TopoShape().getInternNames());
    EXPECT_TRUE(map->isInterned());
    EXPECT_TRUE(copied.getInternNames());
    EXPECT_TRUE(assigned.getInternNames());
    Part::TopoShape plain;
    plain.resetElementMap(map);
    EXPECT_TRUE(map->isInterned());
    EXPECT_TRUE(plain.getInternNames());
    // Only setInternNames() turns a shape and its map plain
    plain.setInternNames(false);
    EXPECT_FALSE(map->isInterned());
    EXPECT_FALSE(plain.getInternNames());
}

namespace
{
/// Plain V2 names of depth 1 to 3, some with split pieces (seeded)
std::vector<std::string> generatedPlainNames(std::mt19937& random)
{
    std::vector<std::string> pool {"g1;SKT", "g2;SKT", "g10;SKT", "Edge3", "Face1"};
    const std::vector<const char*> ops {"FUS", "CUT", "FLT", "XTR"};
    for (int i = 0; i < 300; ++i) {
        auto pick = [&]() {
            return Data::MappedName(pool[random() % pool.size()]);
        };
        std::vector<Data::MappedName> linked;
        std::vector<Data::MappedName> connected;
        for (unsigned k = random() % 3 + 1; k > 0; --k) {
            linked.push_back(pick());
        }
        if (random() % 3 == 0) {
            connected.push_back(pick());
        }
        std::string name = Data::MappedName::makeEncodedSection(
            {},
            linked,
            static_cast<int>(random() % 7) - 2,
            ops[random() % ops.size()],
            static_cast<int>(random() % 3),
            "VEF" [random() % 3],
            0,
            { random() % 2 ? "GEN" : "MOD" },
            connected
        );
        if (random() % 4 == 0) {
            name = pool[random() % pool.size()] + "|" + name;  // a split piece
        }
        if (name.size() < 2000) {  // names that embed long names grow fast
            pool.push_back(name);
        }
    }
    return pool;
}
}  // namespace

TEST_F(TopoShapeTest, sortNameSetOrdersInternedNamesAsTheirExpansions)
{
    // ops#6, Task 1 PR 5: a list field of interned names is in the order of the plain names, so
    // the name holding it expands to the plain one. Mixed forms too; equal expansions are one.
    // Arrange
    std::mt19937 random(20261002);
    const auto plainNames = generatedPlainNames(random);
    auto& table = Data::NameTable::instance();
    std::vector<std::string> internedNames;
    for (const auto& name : plainNames) {
        internedNames.push_back(table.toInterned(name));
    }
    for (int round = 0; round < 500; ++round) {
        std::vector<Data::MappedName> plain;
        std::vector<Data::MappedName> interned;
        std::vector<Data::MappedName> mixed;
        std::vector<std::string> internedText;
        for (unsigned k = random() % 6 + 2; k > 0; --k) {
            auto pick = random() % plainNames.size();
            plain.emplace_back(plainNames[pick]);
            interned.emplace_back(internedNames[pick]);
            internedText.push_back(internedNames[pick]);
            mixed.emplace_back(random() % 2 ? plainNames[pick] : internedNames[pick]);
        }

        // Act
        Part::sortNameSet(plain);
        Part::sortNameSet(interned);
        Part::sortNameSet(mixed);
        Part::sortNameSet(internedText);

        // Assert
        auto expanded = [&table](const auto& names) {
            std::vector<std::string> result;
            for (const auto& name : names) {
                if constexpr (std::is_same_v<std::decay_t<decltype(name)>, std::string>) {
                    result.push_back(table.toPlain(name));
                }
                else {
                    result.push_back(table.toPlain(name.toString()));
                }
            }
            return result;
        };
        std::vector<std::string> expected;
        for (const auto& name : plain) {
            expected.push_back(name.toString());
        }
        EXPECT_TRUE(std::is_sorted(expected.begin(), expected.end()));
        EXPECT_EQ(expanded(interned), expected);
        EXPECT_EQ(expanded(mixed), expected);
        EXPECT_EQ(expanded(internedText), expected);
    }
}
