// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>
#include "PartTestHelpers.h"
#include <Mod/Part/App/TopoShape.h>
#include "src/App/InitApplication.h"

#include <App/ElementMap.h>
#include <BRepPrimAPI_MakeBox.hxx>
#include <cstring>
#include <new>


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
