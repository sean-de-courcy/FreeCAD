// SPDX-License-Identifier: LGPL-2.1-or-later

// Chamfers by equal distances over chains of edges at different angles: Onshape's setbacks
// (FilletFallback::chainSetbacks(); design: notes/chamfer-chain-setbacks.md in the ops repository,
// Onshape's facts CT1-CT3 in notes/onshape-facts.md). The chain's first edge in the list gets the
// width w, every other edge s = w tan(a1 / 2) / tan(a / 2). Designed models only; every
// expectation follows from the geometry.

#include <cmath>
#include <numbers>
#include <vector>
#include <gtest/gtest.h>

#include "src/App/InitApplication.h"
#include <Mod/Part/App/FilletFallback.h>
#include <Mod/Part/App/TopoShape.h>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <gp_Lin.hxx>

using namespace Part;
namespace FF = Part::FilletFallback;

namespace
{

constexpr double pi = std::numbers::pi;
constexpr double w = 0.5;

double radians(double degrees)
{
    return degrees * pi / 180;
}

/// The rule: the setback of an edge at wedge angle a in a chain whose first edge is at a1 (degrees)
double rule(double a1, double a)
{
    return w * std::tan(radians(a1) / 2) / std::tan(radians(a) / 2);
}

int count(const TopoDS_Shape& shape, TopAbs_ShapeEnum type)
{
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, type, map);
    return map.Extent();
}

double area(const TopoDS_Shape& face)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(face, props);
    return props.Mass();
}

TopoDS_Shape solidOf(const TopoDS_Shape& shape)
{
    TopExp_Explorer it(shape, TopAbs_SOLID);
    return it.More() ? it.Current() : shape;
}

/// A box filling the side of the plane the normal points to (within size of the point)
TopoDS_Shape beyondPlane(const gp_Pnt& point, const gp_Dir& normal, double size)
{
    gp_Ax2 frame(point, normal);
    gp_Vec diagonal = gp_Vec(frame.XDirection()) + gp_Vec(frame.YDirection());
    gp_Ax2 corner(point.Translated(diagonal * -size), normal, frame.XDirection());
    return BRepPrimAPI_MakeBox(corner, 2 * size, 2 * size, size).Shape();
}

/// The edge of the shape between the two points
TopoShape edgeBetween(const TopoShape& shape, gp_Pnt p, gp_Pnt q)
{
    for (const auto& edge : shape.getSubTopoShapes(TopAbs_EDGE)) {
        TopoDS_Vertex v1, v2;
        TopExp::Vertices(TopoDS::Edge(edge.getShape()), v1, v2);
        gp_Pnt a = BRep_Tool::Pnt(v1);
        gp_Pnt b = BRep_Tool::Pnt(v2);
        if ((a.Distance(p) < 1e-7 && b.Distance(q) < 1e-7)
            || (a.Distance(q) < 1e-7 && b.Distance(p) < 1e-7)) {
            return edge;
        }
    }
    ADD_FAILURE() << "no edge between the points";
    return {};
}

std::vector<gp_Pnt> vertices(const TopoDS_Shape& shape)
{
    std::vector<gp_Pnt> points;
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, TopAbs_VERTEX, map);
    for (int i = 1; i <= map.Extent(); ++i) {
        points.push_back(BRep_Tool::Pnt(TopoDS::Vertex(map(i))));
    }
    return points;
}

/// The plane faces whose normal is parallel to the direction (either way)
std::vector<TopoDS_Face> planesAlong(const TopoDS_Shape& shape, const gp_Dir& normal)
{
    std::vector<TopoDS_Face> faces;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        BRepAdaptor_Surface surface(TopoDS::Face(it.Current()));
        if (surface.GetType() == GeomAbs_Plane
            && surface.Plane().Axis().Direction().IsParallel(normal, 1e-9)) {
            faces.push_back(TopoDS::Face(it.Current()));
        }
    }
    return faces;
}

/// The plane face at z = 0 (the bottom), or a null face
TopoDS_Face bottomOf(const TopoDS_Shape& shape)
{
    for (const auto& face : planesAlong(shape, gp::DZ())) {
        bool atZero = true;
        for (const auto& p : vertices(face)) {
            atZero = atZero && std::abs(p.Z()) < 1e-7;
        }
        if (atZero) {
            return face;
        }
    }
    ADD_FAILURE() << "no bottom face";
    return {};
}

bool contains(const std::vector<gp_Pnt>& points, const gp_Pnt& point)
{
    for (const auto& p : points) {
        if (p.Distance(point) < 1e-7) {
            return true;
        }
    }
    return false;
}

// Q-TAPER: box x 0..20, y -10..10, z 0..5, minus a pocket open at z = 0. Its end walls x = 5 and
// x = 15 are square to the bottom; its side walls run from y = +-3 at z = 0 to y = +-(3 - 3 tan t)
// at z = 3, so their bottom edges have the wedge angle 90 + t.
TopoShape taper(double t)
{
    const double k = std::tan(radians(t));
    TopoDS_Shape block = BRepPrimAPI_MakeBox(gp_Pnt(0, -10, 0), 20, 20, 5).Shape();
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(5, -3 - k, -1),
        gp_Pnt(5, 3 + k, -1),
        gp_Pnt(5, 3 - 3 * k, 3),
        gp_Pnt(5, -3 + 3 * k, 3),
        true
    );
    TopoDS_Face section = BRepBuilderAPI_MakeFace(polygon.Wire(), true).Face();
    TopoDS_Shape pocket = BRepPrimAPI_MakePrism(section, gp_Vec(10, 0, 0)).Shape();
    return TopoShape(solidOf(BRepAlgoAPI_Cut(block, pocket).Shape()), 1L);
}

struct TaperEdges
{
    TopoShape end5, end15, sidePlus, sideMinus;
};

TaperEdges taperEdges(const TopoShape& base)
{
    return {
        edgeBetween(base, {5, -3, 0}, {5, 3, 0}),
        edgeBetween(base, {15, -3, 0}, {15, 3, 0}),
        edgeBetween(base, {5, 3, 0}, {15, 3, 0}),
        edgeBetween(base, {5, -3, 0}, {15, -3, 0}),
    };
}

TopoShape chamfered(const TopoShape& base, const std::vector<TopoShape>& edges, double size)
{
    TopoShape result(2L);
    result.makeElementChamfer(base, edges, ChamferType::equalDistance, size, size);
    return result;
}

/// The chamfered Q-TAPER: the bottom face's hole is the rectangle x 5 - end .. 15 + end,
/// |y| <= 3 + side, its area 400 less the hole's, the trace on the y > 0 side wall at
/// z = side cos t, and 15 faces
void expectTaper(const TopoShape& result, double t, double end, double side)
{
    const TopoDS_Shape& shape = result.getShape();
    ASSERT_FALSE(shape.IsNull());
    EXPECT_TRUE(BRepCheck_Analyzer(shape).IsValid());
    EXPECT_EQ(count(shape, TopAbs_SOLID), 1);
    EXPECT_EQ(count(shape, TopAbs_FACE), 15);
    TopoDS_Face bottom = bottomOf(shape);
    ASSERT_FALSE(bottom.IsNull());
    std::vector<gp_Pnt> hole;
    for (const auto& p : vertices(bottom)) {
        if (p.X() > 1 && p.X() < 19 && std::abs(p.Y()) < 9) {
            hole.push_back(p);
        }
    }
    EXPECT_EQ(hole.size(), 4U);
    for (double x : {5 - end, 15 + end}) {
        for (double y : {-3 - side, 3 + side}) {
            EXPECT_TRUE(contains(hole, gp_Pnt(x, y, 0))) << "no hole corner at " << x << ", " << y;
        }
    }
    EXPECT_NEAR(area(bottom), 400 - (10 + 2 * end) * (6 + 2 * side), 1e-7);
    // The y > 0 side wall: the plane y + z tan t = 3
    const double tilt = radians(t);
    bool found = false;
    for (const auto& face : planesAlong(shape, gp_Dir(0, std::cos(tilt), std::sin(tilt)))) {
        auto points = vertices(face);
        double low = 1e9;
        bool onWall = true;
        for (const auto& p : points) {
            low = std::min(low, p.Z());
            onWall = onWall && std::abs(p.Y() + p.Z() * std::tan(tilt) - 3) < 1e-7;
        }
        if (onWall) {
            found = true;
            EXPECT_NEAR(low, side * std::cos(tilt), 1e-7);
        }
    }
    EXPECT_TRUE(found) << "no side wall";
}

// Q-OCT: a block whose bottom face is the rectangle x 0..20, y 0..12 at z = 0, 5 high, all four
// walls drafted outward by t going up, its 4 drafted corner edges chamfered by 2 (lone edges: 2 on
// both faces). Its bottom face's 8 edges: 4 along the walls at the wedge angle 90 + t, 4 along the
// corner faces at 90 + t', tan t' = sqrt 2 tan t (the corner face's normal is the sum of the two
// walls' unit normals).
TopoShape octagon(double t)
{
    const double c = std::cos(radians(t));
    const double s = std::sin(radians(t));
    TopoDS_Shape shape = BRepPrimAPI_MakeBox(gp_Pnt(-10, -10, 0), 40, 32, 5).Shape();
    const std::pair<gp_Pnt, gp_Dir> walls[] = {
        {{0, 6, 0}, {-c, 0, -s}},
        {{20, 6, 0}, {c, 0, -s}},
        {{10, 0, 0}, {0, -c, -s}},
        {{10, 12, 0}, {0, c, -s}},
    };
    for (const auto& [point, normal] : walls) {
        shape = solidOf(BRepAlgoAPI_Cut(shape, beyondPlane(point, normal, 100)).Shape());
    }
    TopoShape block(shape, 1L);
    std::vector<TopoShape> corners;
    for (const auto& edge : block.getSubTopoShapes(TopAbs_EDGE)) {
        auto points = vertices(edge.getShape());
        if (points.size() == 2 && std::abs(std::abs(points[0].Z() - points[1].Z()) - 5) < 1e-7) {
            corners.push_back(edge);
        }
    }
    EXPECT_EQ(corners.size(), 4U);
    TopoShape result(3L);
    result.makeElementChamfer(block, corners, ChamferType::equalDistance, 2, 2);
    return result;
}

/// The bottom face's 8 edges: the wall edges (along x or y) and the corner-face edges
void octagonEdges(const TopoShape& base, std::vector<TopoShape>& walls, std::vector<TopoShape>& corners)
{
    for (const auto& edge : base.getSubTopoShapes(TopAbs_EDGE)) {
        auto points = vertices(edge.getShape());
        if (points.size() != 2 || std::abs(points[0].Z()) > 1e-7 || std::abs(points[1].Z()) > 1e-7) {
            continue;
        }
        gp_Vec along(points[0], points[1]);
        bool axial = std::abs(along.X()) < 1e-9 || std::abs(along.Y()) < 1e-9;
        (axial ? walls : corners).push_back(edge);
    }
    EXPECT_EQ(walls.size(), 4U);
    EXPECT_EQ(corners.size(), 4U);
}

/// In the bottom plane, each bottom edge of the base moves in by its setback: the result's
/// bottom edge parallel to it lies at that distance from its line
void expectOctagon(const TopoShape& result, const std::vector<TopoShape>& edges,
                   const std::vector<double>& setbacks)
{
    const TopoDS_Shape& shape = result.getShape();
    ASSERT_FALSE(shape.IsNull());
    EXPECT_TRUE(BRepCheck_Analyzer(shape).IsValid());
    EXPECT_EQ(count(shape, TopAbs_SOLID), 1);
    TopoDS_Face bottom = bottomOf(shape);
    ASSERT_FALSE(bottom.IsNull());
    std::vector<TopoDS_Edge> bottomEdges;
    for (TopExp_Explorer it(bottom, TopAbs_EDGE); it.More(); it.Next()) {
        bottomEdges.push_back(TopoDS::Edge(it.Current()));
    }
    EXPECT_EQ(bottomEdges.size(), 8U);
    for (std::size_t i = 0; i < edges.size(); ++i) {
        auto ends = vertices(edges[i].getShape());
        gp_Lin line(ends[0], gp_Dir(gp_Vec(ends[0], ends[1])));
        int matches = 0;
        for (const auto& edge : bottomEdges) {
            auto points = vertices(edge);
            gp_Vec along(points[0], points[1]);
            if (along.Magnitude() < 1e-7 || !along.IsParallel(gp_Vec(line.Direction()), 1e-9)) {
                continue;
            }
            gp_Pnt middle((points[0].XYZ() + points[1].XYZ()) / 2);
            // the parallel edge on the same side of the bottom (the nearest one)
            if (line.Distance(middle) < 2) {
                ++matches;
                EXPECT_NEAR(line.Distance(points[0]), setbacks[i], 1e-7) << "edge " << i;
                EXPECT_NEAR(line.Distance(points[1]), setbacks[i], 1e-7) << "edge " << i;
            }
        }
        EXPECT_EQ(matches, 1) << "edge " << i;
    }
}

/// A tilted angle: box 0..20 x 0..20 x 0..10 minus a cylinder of radius 8 tilted 20 degrees in
/// x z through (25, 10, 0): the top face's edge on the cylinder has a wedge angle that varies
/// along it, between the top face's straight edges at 90 degrees
TopoShape tiltedWall()
{
    TopoDS_Shape block = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 20, 20, 10).Shape();
    gp_Dir axis(-std::sin(radians(20)), 0, std::cos(radians(20)));
    gp_Pnt start = gp_Pnt(25, 10, 0).Translated(gp_Vec(axis) * -15);
    TopoDS_Shape cylinder = BRepPrimAPI_MakeCylinder(gp_Ax2(start, axis), 8, 40).Shape();
    return TopoShape(solidOf(BRepAlgoAPI_Cut(block, cylinder).Shape()), 1L);
}

}  // namespace

class FilletFallbackChainTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
};

// C1, the control: square side walls, all four edges at 90 degrees: the width exactly, as today
TEST_F(FilletFallbackChainTest, equalAnglesKeepTheWidthExactly)
{
    TopoShape base = taper(0);
    auto e = taperEdges(base);
    std::vector<TopoShape> edges {e.end5, e.sidePlus, e.end15, e.sideMinus};
    auto setbacks = FF::chainSetbacks(base, edges, w);
    ASSERT_EQ(setbacks.size(), 4U);
    for (double setback : setbacks) {
        EXPECT_EQ(setback, w);
    }
    expectTaper(chamfered(base, edges, w), 0, w, w);
    EXPECT_NEAR(area(bottomOf(chamfered(base, edges, w).getShape())), 323, 1e-7);
}

// C2: t 6, a square end edge first: the tapered sides (96 degrees) get 0.5 tan 45 / tan 48
TEST_F(FilletFallbackChainTest, squareEdgeFirst)
{
    TopoShape base = taper(6);
    auto e = taperEdges(base);
    std::vector<TopoShape> edges {e.end5, e.sidePlus, e.end15, e.sideMinus};
    const double side = rule(90, 96);
    EXPECT_NEAR(side, 0.450202, 1e-6);
    auto setbacks = FF::chainSetbacks(base, edges, w);
    ASSERT_EQ(setbacks.size(), 4U);
    EXPECT_EQ(setbacks[0], w);
    EXPECT_NEAR(setbacks[1], side, 1e-9);
    EXPECT_EQ(setbacks[2], w);
    EXPECT_NEAR(setbacks[3], side, 1e-9);
    TopoShape result = chamfered(base, edges, w);
    expectTaper(result, 6, w, side);
    EXPECT_NEAR(area(bottomOf(result.getShape())), 324.095556, 1e-6);
}

// C3: t 6, a tapered side edge first: the square ends get 0.5 tan 48 / tan 45
TEST_F(FilletFallbackChainTest, taperedEdgeFirst)
{
    TopoShape base = taper(6);
    auto e = taperEdges(base);
    std::vector<TopoShape> edges {e.sidePlus, e.end5, e.sideMinus, e.end15};
    const double end = rule(96, 90);
    EXPECT_NEAR(end, 0.555306, 1e-6);
    auto setbacks = FF::chainSetbacks(base, edges, w);
    ASSERT_EQ(setbacks.size(), 4U);
    EXPECT_EQ(setbacks[0], w);
    EXPECT_NEAR(setbacks[1], end, 1e-9);
    EXPECT_EQ(setbacks[2], w);
    EXPECT_NEAR(setbacks[3], end, 1e-9);
    TopoShape result = chamfered(base, edges, w);
    expectTaper(result, 6, end, w);
    EXPECT_NEAR(area(bottomOf(result.getShape())), 322.225712, 1e-6);
}

// C4: the order after the first edge doesn't matter (CT2): as C2
TEST_F(FilletFallbackChainTest, orderAfterTheFirstEdgeDoesNotMatter)
{
    TopoShape base = taper(6);
    auto e = taperEdges(base);
    std::vector<TopoShape> edges {e.end5, e.sideMinus, e.end15, e.sidePlus};
    const double side = rule(90, 96);
    auto setbacks = FF::chainSetbacks(base, edges, w);
    ASSERT_EQ(setbacks.size(), 4U);
    EXPECT_EQ(setbacks[0], w);
    EXPECT_NEAR(setbacks[1], side, 1e-9);
    EXPECT_EQ(setbacks[2], w);
    EXPECT_NEAR(setbacks[3], side, 1e-9);
    expectTaper(chamfered(base, edges, w), 6, w, side);
}

// C5: the two end edges share no vertex: lone edges, the width on each (CT1)
TEST_F(FilletFallbackChainTest, loneEdgesKeepTheWidth)
{
    TopoShape base = taper(6);
    auto e = taperEdges(base);
    auto setbacks = FF::chainSetbacks(base, {e.end5, e.end15}, w);
    ASSERT_EQ(setbacks.size(), 2U);
    EXPECT_EQ(setbacks[0], w);
    EXPECT_EQ(setbacks[1], w);
    setbacks = FF::chainSetbacks(base, {e.sidePlus}, w);
    ASSERT_EQ(setbacks.size(), 1U);
    EXPECT_EQ(setbacks[0], w);
}

// C6: t 20, a 110-degree side edge first: the square ends get 0.5 tan 55 / tan 45, more than w
TEST_F(FilletFallbackChainTest, steepEdgeFirstGivesMoreThanTheWidth)
{
    TopoShape base = taper(20);
    auto e = taperEdges(base);
    std::vector<TopoShape> edges {e.sidePlus, e.end15, e.sideMinus, e.end5};
    const double end = rule(110, 90);
    EXPECT_NEAR(end, 0.714074, 1e-6);
    auto setbacks = FF::chainSetbacks(base, edges, w);
    ASSERT_EQ(setbacks.size(), 4U);
    EXPECT_EQ(setbacks[0], w);
    EXPECT_NEAR(setbacks[1], end, 1e-9);
    EXPECT_EQ(setbacks[2], w);
    EXPECT_NEAR(setbacks[3], end, 1e-9);
    expectTaper(chamfered(base, edges, w), 20, end, w);
}

// The fallback: a contour whose angle varies along it (a tilted cylinder) keeps the width on its
// whole chain
TEST_F(FilletFallbackChainTest, varyingAngleKeepsTheWidth)
{
    TopoShape base = tiltedWall();
    std::vector<TopoShape> top;
    TopoShape curved;
    for (const auto& edge : base.getSubTopoShapes(TopAbs_EDGE)) {
        bool atTop = true;
        for (const auto& p : vertices(edge.getShape())) {
            atTop = atTop && std::abs(p.Z() - 10) < 1e-7;
        }
        if (!atTop) {
            continue;
        }
        if (BRepAdaptor_Curve(TopoDS::Edge(edge.getShape())).GetType() == GeomAbs_Line) {
            top.push_back(edge);
        }
        else {
            curved = edge;
        }
    }
    ASSERT_EQ(top.size(), 5U);
    ASSERT_FALSE(curved.isNull());
    top.push_back(curved);  // the straight edges first: without the fallback the arc would differ
    auto setbacks = FF::chainSetbacks(base, top, w);
    ASSERT_EQ(setbacks.size(), 6U);
    for (double setback : setbacks) {
        EXPECT_EQ(setback, w);
    }
}

// Q-OCT D1, the control: t 0, every bottom edge at 90 degrees: the width exactly
TEST_F(FilletFallbackChainTest, octagonControl)
{
    TopoShape base = octagon(0);
    std::vector<TopoShape> walls, corners;
    octagonEdges(base, walls, corners);
    std::vector<TopoShape> edges = walls;
    edges.insert(edges.end(), corners.begin(), corners.end());
    auto setbacks = FF::chainSetbacks(base, edges, w);
    ASSERT_EQ(setbacks.size(), 8U);
    for (double setback : setbacks) {
        EXPECT_EQ(setback, w);
    }
    expectOctagon(chamfered(base, edges, w), edges, setbacks);
}

/// D2-D4: the bottom loop of Q-OCT at t, a wall edge or a corner-face edge first
void octagonCase(double t, bool wallFirst, double expectedWall, double expectedCorner)
{
    TopoShape base = octagon(t);
    std::vector<TopoShape> walls, corners;
    octagonEdges(base, walls, corners);
    std::vector<TopoShape> edges;
    const auto& first = wallFirst ? walls : corners;
    const auto& second = wallFirst ? corners : walls;
    edges.insert(edges.end(), first.begin(), first.end());
    edges.insert(edges.end(), second.begin(), second.end());
    std::vector<double> expected;
    for (std::size_t i = 0; i < edges.size(); ++i) {
        expected.push_back((i < 4) == wallFirst ? expectedWall : expectedCorner);
    }
    auto setbacks = FF::chainSetbacks(base, edges, w);
    ASSERT_EQ(setbacks.size(), 8U);
    EXPECT_EQ(setbacks[0], w);
    for (std::size_t i = 0; i < edges.size(); ++i) {
        EXPECT_NEAR(setbacks[i], expected[i], 1e-9) << "edge " << i;
    }
    TopoShape result = chamfered(base, edges, w);
    expectOctagon(result, edges, expected);
    // Each corner's uncut edge between a wall and a corner face carries two traces at different
    // heights: one more vertex and edge per corner than the control's (TEST's 40 -> 48)
    TopoShape control = octagon(0);
    std::vector<TopoShape> controlWalls, controlCorners;
    octagonEdges(control, controlWalls, controlCorners);
    std::vector<TopoShape> controlEdges = controlWalls;
    controlEdges.insert(controlEdges.end(), controlCorners.begin(), controlCorners.end());
    TopoShape plain = chamfered(control, controlEdges, w);
    EXPECT_EQ(count(result.getShape(), TopAbs_FACE), count(plain.getShape(), TopAbs_FACE));
    EXPECT_EQ(count(result.getShape(), TopAbs_EDGE), count(plain.getShape(), TopAbs_EDGE) + 8);
    EXPECT_EQ(count(result.getShape(), TopAbs_VERTEX), count(plain.getShape(), TopAbs_VERTEX) + 8);
}

double draftOfCorner(double t)
{
    return std::atan(std::sqrt(2.0) * std::tan(radians(t))) * 180 / pi;
}

// D2: t 6, a wall edge first: the corner-face edges (t' 8.454534) get 0.478867
TEST_F(FilletFallbackChainTest, octagonWallFirst)
{
    EXPECT_NEAR(draftOfCorner(6), 8.454534, 1e-6);
    const double corner = rule(96, 90 + draftOfCorner(6));
    EXPECT_NEAR(corner, 0.478867, 1e-6);
    octagonCase(6, true, w, corner);
}

// D3: t 6, a corner-face edge first: the wall edges get 0.522066
TEST_F(FilletFallbackChainTest, octagonCornerFirst)
{
    const double wall = rule(90 + draftOfCorner(6), 96);
    EXPECT_NEAR(wall, 0.522066, 1e-6);
    octagonCase(6, false, wall, w);
}

// D4: t 12, a wall edge first: the corner-face edges (t' 16.730798) get 0.459137
TEST_F(FilletFallbackChainTest, octagonSteeperWallFirst)
{
    EXPECT_NEAR(draftOfCorner(12), 16.730798, 1e-6);
    const double corner = rule(102, 90 + draftOfCorner(12));
    EXPECT_NEAR(corner, 0.459137, 1e-6);
    octagonCase(12, true, w, corner);
}
