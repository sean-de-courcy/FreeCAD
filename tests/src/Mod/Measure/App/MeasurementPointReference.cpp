// SPDX-License-Identifier: LGPL-2.1-or-later
// FreeCAD-CH (ops#673, selection parity 11): a reference standing for a point. In the 3D view an
// edge picked at its middle (the midpoint marker showing) measures as that point, as in Onshape
// (SP10-Q9: the readout says "Point", and with a corner vertex "Min dist" 10 mm).

#include <cmath>
#include <optional>
#include <string>
#include <vector>

#include <gtest/gtest.h>

#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRep_Tool.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>

#include <App/Document.h>
#include <Base/Vector3D.h>
#include <Mod/Measure/App/Measurement.h>
#include <Mod/Part/App/PartFeature.h>
#include <src/App/InitApplication.h>

namespace
{

// The box of SP10-Q9: x 40..60, y 0..20, z 0..10; its top edge on y = 0 runs from (40,0,10)
// to (60,0,10), middle (50,0,10); the corner vertex (40,0,10) is 10 mm from it.
const gp_Pnt edgeStart(40.0, 0.0, 10.0);
const gp_Pnt edgeEnd(60.0, 0.0, 10.0);
const Base::Vector3d middle(50.0, 0.0, 10.0);

/// the name of the box's element of the given type whose vertices are the given points
std::string elementName(const TopoDS_Shape& shape,
                        TopAbs_ShapeEnum type,
                        const std::vector<gp_Pnt>& points)
{
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, type, map);
    for (int i = 1; i <= map.Extent(); ++i) {
        TopTools_IndexedMapOfShape vertices;
        TopExp::MapShapes(map(i), TopAbs_VERTEX, vertices);
        if (vertices.Extent() != static_cast<int>(points.size())) {
            continue;
        }
        bool all = true;
        for (const gp_Pnt& point : points) {
            bool found = false;
            for (int j = 1; j <= vertices.Extent(); ++j) {
                found = found
                    || BRep_Tool::Pnt(TopoDS::Vertex(vertices(j))).Distance(point) < 1e-9;
            }
            all = all && found;
        }
        if (all) {
            return (type == TopAbs_EDGE ? "Edge" : "Vertex") + std::to_string(i);
        }
    }
    return {};
}

}  // namespace

class MeasurementPointReference: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        document = App::GetApplication().newDocument("MeasurementPointReference");
        box = document->addObject<Part::Feature>("Box");
        const TopoDS_Shape shape = BRepPrimAPI_MakeBox(gp_Pnt(40, 0, 0), 20, 20, 10).Solid();
        box->Shape.setValue(shape);
        edge = elementName(shape, TopAbs_EDGE, {edgeStart, edgeEnd});
        corner = elementName(shape, TopAbs_VERTEX, {edgeStart});
        parallelEdge = elementName(shape, TopAbs_EDGE, {gp_Pnt(40, 20, 0), gp_Pnt(60, 20, 0)});
        document->recompute();
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(document->getName());
    }

    App::Document* document {};
    Part::Feature* box {};
    std::string edge;
    std::string corner;
    std::string parallelEdge;
};

// NOLINTBEGIN
TEST_F(MeasurementPointReference, edgeMiddleAloneIsAPoint)
{
    ASSERT_FALSE(edge.empty());
    Measure::Measurement measurement;
    measurement.setReferences3D({box}, {edge}, {middle});
    EXPECT_EQ(measurement.getType(), Measure::MeasureType::Points);
}

TEST_F(MeasurementPointReference, edgeMiddleAndCornerArePointToPoint)
{
    ASSERT_FALSE(corner.empty());
    Measure::Measurement measurement;
    measurement.setReferences3D({box, box}, {edge, corner}, {middle, std::nullopt});
    EXPECT_EQ(measurement.getType(), Measure::MeasureType::PointToPoint);
    EXPECT_NEAR(measurement.length(), 10.0, 1e-9);
    const Base::Vector3d delta = measurement.delta();
    EXPECT_NEAR(std::abs(delta.x), 10.0, 1e-9);
    EXPECT_NEAR(delta.y, 0.0, 1e-9);
    EXPECT_NEAR(delta.z, 0.0, 1e-9);
}

TEST_F(MeasurementPointReference, edgeMiddleToAnotherEdgeMeasuresFromThePoint)
{
    // the edge y 20, z 0 is parallel to the picked one: from the middle (50,0,10) its nearest
    // point is (50,20,0), sqrt(500) away, the same as the edges' own distance; the far end
    // (40,20,0) is sqrt(600) away, where the whole edge's farthest pair is sqrt(800)
    ASSERT_FALSE(parallelEdge.empty());
    Measure::Measurement measurement;
    measurement.setReferences3D({box, box}, {edge, parallelEdge}, {middle, std::nullopt});
    EXPECT_EQ(measurement.getType(), Measure::MeasureType::PointToEdge);
    const Measure::DistanceResult result = measurement.distances(1000);
    ASSERT_TRUE(result.hasMin);
    EXPECT_NEAR(result.min, std::sqrt(500.0), 1e-6);
    ASSERT_TRUE(result.hasMax);
    EXPECT_NEAR(result.max, std::sqrt(600.0), 1e-6);
}

TEST_F(MeasurementPointReference, withoutPointTheEdgeIsMeasured)
{
    Measure::Measurement measurement;
    measurement.setReferences3D({box, box}, {edge, corner}, {middle, std::nullopt});
    measurement.setReferences3D({box, box}, {edge, corner});
    EXPECT_EQ(measurement.getType(), Measure::MeasureType::PointToEdge);
    measurement.clear();
    measurement.setReferences3D({box}, {edge}, {std::nullopt});
    EXPECT_EQ(measurement.getType(), Measure::MeasureType::Line);
}
// NOLINTEND
