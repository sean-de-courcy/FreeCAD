// SPDX-License-Identifier: LGPL-2.1-or-later

// Tests for the makeShape methods, extracted from the main set of tests for TopoShape
// due to length and complexity.

#include <gtest/gtest.h>
#include "src/App/InitApplication.h"
#include "PartTestHelpers.h"
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

using namespace Data;
using namespace Part;
using namespace PartTestHelpers;

class TopoShapeMakeShapeTests: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("test");
        App::GetApplication().newDocument(_docName.c_str(), "testUser");
        _sids = &_sid;
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    Part::TopoShape* Shape()
    {
        return &_shape;
    }

    Part::TopoShape::Mapper* Mapper()
    {
        return &_mapper;
    }

private:
    std::string _docName;
    Data::ElementIDRefs _sid;
    QVector<App::StringIDRef>* _sids = nullptr;
    Part::TopoShape _shape;
    Part::TopoShape::Mapper _mapper;
};

TEST_F(TopoShapeMakeShapeTests, nullShapeThrows)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    std::vector<Part::TopoShape> sources {cube1, cube2};
    TopoDS_Vertex nullShape;

    // Act and assert
    EXPECT_THROW(
        Shape()->makeShapeWithElementMap(nullShape, *Mapper(), sources),
        Part::NullShapeException
    );
}

TEST_F(TopoShapeMakeShapeTests, shapeVertex)
{
    // Arrange
    BRepBuilderAPI_MakeVertex vertexMaker = BRepBuilderAPI_MakeVertex(gp_Pnt(10, 10, 10));
    TopoShape topoShape(vertexMaker.Vertex(), 1L);
    // Act
    TopoShape& result = topoShape.makeElementShape(vertexMaker, topoShape);
    // Assert
    EXPECT_EQ(result.getElementMap().size(), 1);  // Changed with PR#12471. Probably will change
                                                  // again after importing other TopoNaming logics
    EXPECT_EQ(result.countSubElements("Vertex"), 1);
    EXPECT_EQ(result.countSubShapes("Vertex"), 1);
}

TEST_F(TopoShapeMakeShapeTests, thruSections)
{
    // Arrange
    auto [face1, wire1, edge1, edge2, edge3, edge4] = CreateRectFace();
    TopoDS_Wire wire2 = wire1;
    auto transform {gp_Trsf()};
    transform.SetTranslation(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(0.0, 0.5, 1.0));
    wire2.Move(TopLoc_Location(transform));
    TopoShape wire1ts {wire1, 1L};
    TopoShape wire2ts {wire2, 2L};
    BRepOffsetAPI_ThruSections thruMaker;
    thruMaker.AddWire(wire1);
    thruMaker.AddWire(wire2);
    TopoShape topoShape {};
    // Act
    TopoShape& result
        = topoShape.makeElementShape(thruMaker, {wire1ts, wire2ts}, OpCodes::ThruSections);
    auto elements = elementMap(result);
    // Assert
    EXPECT_EQ(elements.size(), 24);
    EXPECT_EQ(elements.count(IndexedName("Vertex", 1)), 1);
    EXPECT_EQ(getVolume(result.getShape()), 4);
    //   the wires (tags 1 and 2) have no names, and the result has no tag, so its sections take
    //   the first input's (1). The wires' edges and vertices are kept; each side face is
    //   generated from an edge of each wire, and each edge between the wires from a vertex of
    //   each (op TRU)
    TopoShape wireOne {wire1};
    TopoShape wireTwo {wire2};
    for (const char* type : {"Vertex", "Edge"}) {
        const char* made = std::string(type) == "Vertex" ? "Edge" : "Face";
        for (int index = 1; index <= static_cast<int>(wireOne.countSubElements(type)); ++index) {
            auto element = type + std::to_string(index);
            auto one = wireOne.getSubShape(element.c_str());
            auto two = wireTwo.getSubShape(element.c_str());
            EXPECT_TRUE(elementHasNames(
                result,
                (type + std::to_string(result.findShape(one))).c_str(),
                {unmappedName(element, 1)}
            ));
            EXPECT_TRUE(elementHasNames(
                result,
                (type + std::to_string(result.findShape(two))).c_str(),
                {unmappedName(element, 2)}
            ));
            std::string between;
            for (int other = 1; other <= static_cast<int>(result.countSubElements(made)); ++other) {
                auto candidate = made + std::to_string(other);
                auto shape = result.getSubShape(candidate.c_str());
                if (liesOn(one, shape) && liesOn(two, shape) && !shape.IsSame(one)) {
                    between = candidate;
                }
            }
            EXPECT_TRUE(elementHasNames(
                result,
                between.c_str(),
                {linkingName(
                    {unmappedName(element, 1, "TRU"), unmappedName(element, 2, "TRU")},
                    1,
                    "TRU",
                    made[0],
                    MAPPER_FLAG_GENERATED
                )}
            ));
        }
    }
}

TEST_F(TopoShapeMakeShapeTests, sewing)
{
    // Arrange
    auto [face1, wire1, edge1, edge2, edge3, edge4] = CreateRectFace();
    auto face2 = face1;
    auto transform {gp_Trsf()};
    transform.SetTranslation(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(0.5, 0.5, 0.0));
    face2.Move(TopLoc_Location(transform));
    BRepBuilderAPI_Sewing sewer;
    sewer.Add(face1);
    sewer.Add(face2);
    sewer.Perform();
    std::vector<TopoShape> sources {{face1, 1L}, {face2, 2L}};
    TopoShape topoShape {};
    // Act
    TopoShape& result = topoShape.makeShapeWithElementMap(
        sewer.SewedShape(),
        MapperSewing(sewer),
        sources,
        OpCodes::Sewing
    );

    auto elements = elementMap(result);
    // Assert
    EXPECT_EQ(&result, &topoShape);
    EXPECT_EQ(elements.size(), 18);  // Now a single cube
    EXPECT_EQ(elements.count(IndexedName("Vertex", 1)), 1);
    EXPECT_EQ(getArea(result.getShape()), 12);
    //   the faces overlap but share no edge, so nothing is sewn: every element is one of the
    //   faces', kept, and has its unmapped name under that face's tag, without the op
    EXPECT_TRUE(namedAsBoolean(result, {{1, TopoShape(face1)}, {2, TopoShape(face2)}}, "SEW"));
}
