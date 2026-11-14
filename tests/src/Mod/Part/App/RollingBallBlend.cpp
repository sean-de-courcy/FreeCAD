// SPDX-License-Identifier: LGPL-2.1-or-later

// A constant-radius blend as a true rolling ball (ops#640, decision 425; design:
// notes/rolling-ball-blend.md in the ops repository). Designed models only. Every expectation is
// geometric: the ball of the fillet's radius touches both walls (the residual), and where the model
// has a closed form, the seam's place.

#include <array>
#include <cmath>
#include <numbers>
#include <set>
#include <string>
#include <vector>
#include <gtest/gtest.h>

#include "src/App/InitApplication.h"
#include <Base/Exception.h>
#include <Mod/Part/App/RollingBallBlend.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include <BRepAdaptor_Surface.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepTools_ReShape.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GProp_GProps.hxx>
#include <Geom_BSplineSurface.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Wire.hxx>

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

namespace
{
using namespace Part;
namespace RB = Part::RollingBallBlend;

enum class Lid
{
    Spline,   // z = 20 + twist x y, a B-spline (twist 0: a flat B-spline)
    TopPlane  // the prism's own top plane
};

Handle(Geom_BSplineSurface) lidSurface(double twist);

/// A stadium prism (two planes y = -10 and y = 10, two half cylinders of radius 10 about x = -20
/// and x = 20) under a lid. The plane and the cylinder walls meet along four vertical tangent lines
TopoDS_Shape stadiumBase(double twist, Lid kind, TopoDS_Face& lid)
{
    const gp_Pnt a1(-20, -10, 0);
    const gp_Pnt a2(20, -10, 0);
    const gp_Pnt a3(20, 10, 0);
    const gp_Pnt a4(-20, 10, 0);
    BRepBuilderAPI_MakeWire wire;
    wire.Add(BRepBuilderAPI_MakeEdge(a1, a2).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(a2, gp_Pnt(30, 0, 0), a3).Value()).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(a3, a4).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(a4, gp_Pnt(-30, 0, 0), a1).Value()).Edge());
    const TopoDS_Shape prism
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(wire.Wire()).Face(), gp_Vec(0, 0, 40)).Shape();
    if (kind == Lid::TopPlane) {
        for (TopExp_Explorer it(prism, TopAbs_FACE); it.More(); it.Next()) {
            GProp_GProps properties;
            BRepGProp::SurfaceProperties(it.Current(), properties);
            if (properties.CentreOfMass().Z() > 39.9) {
                lid = TopoDS::Face(it.Current());
            }
        }
        return prism;
    }
    const Handle(Geom_BSplineSurface) surface = lidSurface(twist);
    const TopoDS_Shape tool
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(surface, 1e-7).Face(), gp_Vec(0, 0, 60)).Shape();
    const TopoDS_Shape base = BRepAlgoAPI_Cut(prism, tool).Shape();
    for (TopExp_Explorer it(base, TopAbs_FACE); it.More(); it.Next()) {
        if (BRep_Tool::Surface(TopoDS::Face(it.Current()))->IsKind(STANDARD_TYPE(Geom_BSplineSurface))) {
            lid = TopoDS::Face(it.Current());
        }
    }
    return base;
}

/// The twisted lid's surface, z = 20 + twist x y, as a B-spline
Handle(Geom_BSplineSurface) lidSurface(double twist)
{
    TColgp_Array2OfPnt poles(1, 2, 1, 2);
    const double x = 45;
    const double y = 25;
    poles(1, 1) = gp_Pnt(-x, -y, 20 + twist * x * y);
    poles(2, 1) = gp_Pnt(x, -y, 20 - twist * x * y);
    poles(1, 2) = gp_Pnt(-x, y, 20 - twist * x * y);
    poles(2, 2) = gp_Pnt(x, y, 20 + twist * x * y);
    TColStd_Array1OfReal knots(1, 2);
    knots(1) = 0;
    knots(2) = 1;
    TColStd_Array1OfInteger multiplicities(1, 2);
    multiplicities(1) = 2;
    multiplicities(2) = 2;
    Handle(Geom_BSplineSurface) surface
        = new Geom_BSplineSurface(poles, knots, knots, multiplicities, multiplicities, 1, 1);
    surface->IncreaseDegree(3, 3);
    return surface;
}

/// A rounded-rectangle prism (four planes, four quarter cylinders of radius 5) under the twisted lid
TopoDS_Shape roundedBoxBase(double twist, TopoDS_Face& lid)
{
    const double a = 20;
    const double b = 12;
    const double c = 5;
    const double d = c * (1 - std::sqrt(0.5));
    const std::array<gp_Pnt, 8> corner = {
        gp_Pnt(-a + c, -b, 0), gp_Pnt(a - c, -b, 0), gp_Pnt(a, -b + c, 0), gp_Pnt(a, b - c, 0),
        gp_Pnt(a - c, b, 0),   gp_Pnt(-a + c, b, 0), gp_Pnt(-a, b - c, 0), gp_Pnt(-a, -b + c, 0)
    };
    const std::array<gp_Pnt, 4> middle = {
        gp_Pnt(a - d, -b + d, 0), gp_Pnt(a - d, b - d, 0), gp_Pnt(-a + d, b - d, 0), gp_Pnt(-a + d, -b + d, 0)
    };
    BRepBuilderAPI_MakeWire wire;
    for (int i = 0; i < 4; ++i) {
        wire.Add(BRepBuilderAPI_MakeEdge(corner[2 * i], corner[2 * i + 1]).Edge());
        wire.Add(
            BRepBuilderAPI_MakeEdge(
                GC_MakeArcOfCircle(corner[2 * i + 1], middle[i], corner[(2 * i + 2) % 8]).Value()
            ).Edge()
        );
    }
    const TopoDS_Shape prism
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(wire.Wire()).Face(), gp_Vec(0, 0, 40)).Shape();
    const TopoDS_Shape tool
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(lidSurface(twist), 1e-7).Face(), gp_Vec(0, 0, 60)).Shape();
    const TopoDS_Shape base = BRepAlgoAPI_Cut(prism, tool).Shape();
    for (TopExp_Explorer it(base, TopAbs_FACE); it.More(); it.Next()) {
        if (BRep_Tool::Surface(TopoDS::Face(it.Current()))->IsKind(STANDARD_TYPE(Geom_BSplineSurface))) {
            lid = TopoDS::Face(it.Current());
        }
    }
    return base;
}

/// Case Base #103's configuration, designed: the stadium under the twisted lid, cut off by the plane
/// x = 10. Rounding the lid's edges on the plane wall, the half cylinder and the other plane wall
/// gives a short blend, a long blend and a short blend; the short ones run out through the cut plane
TopoDS_Shape runOutBase(double twist, TopoDS_Face& lid)
{
    TopoDS_Face whole;
    TopoDS_Shape base = stadiumBase(twist, Lid::Spline, whole);
    base = BRepAlgoAPI_Cut(base, BRepPrimAPI_MakeBox(gp_Pnt(10, -50, -10), 60, 100, 100).Shape()).Shape();
    for (TopExp_Explorer it(base, TopAbs_FACE); it.More(); it.Next()) {
        if (BRep_Tool::Surface(TopoDS::Face(it.Current()))->IsKind(STANDARD_TYPE(Geom_BSplineSurface))) {
            lid = TopoDS::Face(it.Current());
        }
    }
    return base;
}

struct Filleted
{
    TopoDS_Shape shape;
    std::vector<TopoDS_Face> blends;
    TopoDS_Face lid;  // as it is in the result
};

/// OCCT's fillet of the lid's edges (those whose middle is at x below the limit), with the faces
/// it generated
Filleted occtFillet(const TopoDS_Shape& base, const TopoDS_Face& lid, double radius, double below = 1e9)
{
    Filleted result;
    BRepFilletAPI_MakeFillet maker(base);
    TopTools_IndexedMapOfShape all;
    TopExp::MapShapes(lid, TopAbs_EDGE, all);
    TopTools_IndexedMapOfShape edges;
    for (int i = 1; i <= all.Extent(); ++i) {
        GProp_GProps properties;
        BRepGProp::LinearProperties(all(i), properties);
        if (properties.CentreOfMass().X() < below) {
            edges.Add(all(i));
            maker.Add(radius, TopoDS::Edge(all(i)));
        }
    }
    maker.Build();
    if (!maker.IsDone()) {
        return result;
    }
    result.lid = TopoDS::Face(maker.Modified(lid).First());
    for (int i = 1; i <= edges.Extent(); ++i) {
        for (TopTools_ListOfShape::Iterator it(maker.Generated(edges(i))); it.More(); it.Next()) {
            // (a contour's edges each list the contour's faces: the unit takes each once)
            if (it.Value().ShapeType() == TopAbs_FACE) {
                result.blends.push_back(TopoDS::Face(it.Value()));
            }
        }
    }
    result.shape = maker.Shape();
    return result;
}

/// One contact edge on the lid, of a short blend, cut into four edges in a row (Case Base #103's
/// blends have their wall side in four edges)
void splitAContactEdge(Filleted& filleted)
{
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(filleted.shape, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    TopoDS_Edge target;
    for (const TopoDS_Face& blend : filleted.blends) {
        GProp_GProps properties;
        BRepGProp::SurfaceProperties(blend, properties);
        if (properties.CentreOfMass().X() < -15) {
            continue;  // the long one, round the cylinder
        }
        for (TopExp_Explorer it(blend, TopAbs_EDGE); it.More() && target.IsNull(); it.Next()) {
            for (TopTools_ListOfShape::Iterator face(edgeFaces.FindFromKey(it.Current())); face.More(); face.Next()) {
                if (face.Value().IsSame(filleted.lid)) {
                    target = TopoDS::Edge(it.Current());
                }
            }
        }
        if (!target.IsNull()) {
            break;
        }
    }
    ASSERT_FALSE(target.IsNull());
    double first {};
    double last {};
    const Handle(Geom_Curve) curve = BRep_Tool::Curve(target, first, last);
    const TopoDS_Edge forward = TopoDS::Edge(target.Oriented(TopAbs_FORWARD));
    TopoDS_Vertex start;
    TopoDS_Vertex end;
    TopExp::Vertices(forward, start, end);
    BRep_Builder builder;
    TopoDS_Wire wire;
    builder.MakeWire(wire);
    TopoDS_Vertex previous = start;
    double at = first;
    const int pieces = 4;
    for (int i = 1; i <= pieces; ++i) {
        const double parameter = first + (last - first) * i / pieces;
        TopoDS_Vertex next = end;
        if (i < pieces) {
            builder.MakeVertex(next, curve->Value(parameter), BRep_Tool::Tolerance(target));
        }
        TopoDS_Edge piece = TopoDS::Edge(forward.EmptyCopied());
        builder.Add(piece, previous.Oriented(TopAbs_FORWARD));
        builder.Add(piece, next.Oriented(TopAbs_REVERSED));
        builder.Range(piece, at, parameter);
        builder.Add(wire, piece);
        previous = next;
        at = parameter;
    }
    Handle(BRepTools_ReShape) reshape = new BRepTools_ReShape;
    reshape->Replace(forward, wire);
    filleted.shape = reshape->Apply(filleted.shape);
    for (TopoDS_Face& blend : filleted.blends) {
        blend = TopoDS::Face(reshape->Apply(blend));
    }
    ASSERT_TRUE(BRepCheck_Analyzer(filleted.shape).IsValid());
}

int count(const TopoDS_Shape& shape, TopAbs_ShapeEnum kind)
{
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, kind, map);
    return map.Extent();
}

double maxTolerance(const TopoDS_Shape& shape)
{
    double tolerance = 0.0;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Face(it.Current())));
    }
    for (TopExp_Explorer it(shape, TopAbs_EDGE); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Edge(it.Current())));
    }
    for (TopExp_Explorer it(shape, TopAbs_VERTEX); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Vertex(it.Current())));
    }
    return tolerance;
}

/// The distance from a point to the nearest vertex of the shape
double nearestVertex(const TopoDS_Shape& shape, const gp_Pnt& point)
{
    double nearest = 1e9;
    for (TopExp_Explorer it(shape, TopAbs_VERTEX); it.More(); it.Next()) {
        nearest = std::min(nearest, BRep_Tool::Pnt(TopoDS::Vertex(it.Current())).Distance(point));
    }
    return nearest;
}

std::set<std::pair<std::string, std::string>> elementNames(const TopoShape& shape)
{
    std::set<std::pair<std::string, std::string>> names;
    for (const auto& element : shape.getElementMap()) {
        names.emplace(element.index.toString(), element.name.toString());
    }
    return names;
}

class RollingBallBlendTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
};

// A closed chain of four blends (plane + lid, cylinder + lid) under a twisted lid. OCCT's faces are
// not a rolling ball (red); the corrected ones are, with the same topology and tighter tolerances
TEST_F(RollingBallBlendTest, closedChainOnTwistedLid)
{
    for (const double radius : {0.79375, 1.5, 3.0}) {
        TopoDS_Face lid;
        const TopoDS_Shape base = stadiumBase(0.02, Lid::Spline, lid);
        const Filleted occt = occtFillet(base, lid, radius);
        ASSERT_FALSE(occt.shape.IsNull());

        const RB::Report report = RB::correct(occt.shape, occt.blends, radius);

        ASSERT_EQ(report.outcome, RB::Outcome::Corrected) << report.reason;
        EXPECT_GT(report.residualBefore, 1e-4);  // OCCT's: red
        EXPECT_LT(report.residualAfter, 1e-6);   // green
        EXPECT_EQ(report.chains, 1);
        EXPECT_EQ(report.faces, 4);
        EXPECT_TRUE(BRepCheck_Analyzer(report.shape).IsValid());
        EXPECT_EQ(count(report.shape, TopAbs_FACE), count(occt.shape, TopAbs_FACE));
        EXPECT_EQ(count(report.shape, TopAbs_EDGE), count(occt.shape, TopAbs_EDGE));
        EXPECT_EQ(count(report.shape, TopAbs_VERTEX), count(occt.shape, TopAbs_VERTEX));
        EXPECT_LE(maxTolerance(report.shape), 1e-6);
        EXPECT_GT(report.seamMove, 0.01);  // the seams are elsewhere
    }
}

// Eight blends, eight seams, quarter cylinders of radius 5. At radius 3 OCCT's own sections stall and
// step back along two of the corner faces: the stations are spread along the centre curve instead
TEST_F(RollingBallBlendTest, closedChainRoundACornerOfSmallRadius)
{
    for (const double radius : {1.0, 3.0}) {
        TopoDS_Face lid;
        const TopoDS_Shape base = roundedBoxBase(0.02, lid);
        const Filleted occt = occtFillet(base, lid, radius);
        ASSERT_FALSE(occt.shape.IsNull());

        const RB::Report report = RB::correct(occt.shape, occt.blends, radius);

        ASSERT_EQ(report.outcome, RB::Outcome::Corrected) << report.reason;
        EXPECT_EQ(report.faces, 8);
        EXPECT_GT(report.residualBefore, 1e-3);
        EXPECT_LT(report.residualAfter, 1e-6);
        EXPECT_TRUE(BRepCheck_Analyzer(report.shape).IsValid());
        EXPECT_LE(maxTolerance(report.shape), 1e-6);
    }
}

// Closed form: under a flat lid the ball's seam is in the plane through the cylinder's axis and the
// tangent line, so the seam's lid vertex is at (+-20, +-(10 - r), 20). OCCT's is 0.07 mm away
TEST_F(RollingBallBlendTest, seamAtTheTangentLineUnderAFlatLid)
{
    const double radius = 1.5;
    TopoDS_Face lid;
    const TopoDS_Shape base = stadiumBase(0.0, Lid::Spline, lid);
    const Filleted occt = occtFillet(base, lid, radius);
    ASSERT_FALSE(occt.shape.IsNull());

    const RB::Report report = RB::correct(occt.shape, occt.blends, radius);

    ASSERT_EQ(report.outcome, RB::Outcome::Corrected) << report.reason;
    for (const double x : {-20.0, 20.0}) {
        for (const double y : {-8.5, 8.5}) {
            EXPECT_LT(nearestVertex(report.shape, gp_Pnt(x, y, 20)), 1e-9);
            // and on the wall: the tangent line at the lid's height less the radius
            EXPECT_LT(nearestVertex(report.shape, gp_Pnt(x, y < 0 ? -10 : 10, 20 - radius)), 1e-9);
        }
    }
    EXPECT_LT(report.residualAfter, 1e-6);
}

// Case Base #103's configuration: the two short blends run out through a plane of the base. The end
// edges are the ball's surface cut by that plane, and their vertices stay on the plane and on the
// base's edges between it and the walls
TEST_F(RollingBallBlendTest, blendsRunningOutThroughAPlane)
{
    for (const double radius : {0.79375, 1.5, 3.0}) {
        TopoDS_Face lid;
        const TopoDS_Shape base = runOutBase(0.02, lid);
        const Filleted occt = occtFillet(base, lid, radius, 9.9);
        ASSERT_FALSE(occt.shape.IsNull());

        const RB::Report report = RB::correct(occt.shape, occt.blends, radius);

        ASSERT_EQ(report.outcome, RB::Outcome::Corrected) << report.reason;
        EXPECT_EQ(report.faces, 3);
        EXPECT_GT(report.residualBefore, 1e-4);
        EXPECT_LT(report.residualAfter, 1e-6);
        EXPECT_TRUE(BRepCheck_Analyzer(report.shape).IsValid());
        EXPECT_EQ(count(report.shape, TopAbs_FACE), count(occt.shape, TopAbs_FACE));
        EXPECT_EQ(count(report.shape, TopAbs_EDGE), count(occt.shape, TopAbs_EDGE));
        EXPECT_EQ(count(report.shape, TopAbs_VERTEX), count(occt.shape, TopAbs_VERTEX));
        ASSERT_EQ(report.blendFaces.size(), occt.blends.size());
        // The vertices on the cut plane are on it still, and those on a plane wall too
        int onPlane = 0;
        for (TopExp_Explorer it(report.shape, TopAbs_VERTEX); it.More(); it.Next()) {
            const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(it.Current()));
            if (std::fabs(point.X() - 10) < 1e-2) {
                EXPECT_LT(std::fabs(point.X() - 10), 1e-9);
                ++onPlane;
            }
            if (std::fabs(std::fabs(point.Y()) - 10) < 1e-2 && point.X() > -19) {
                EXPECT_LT(std::fabs(std::fabs(point.Y()) - 10), 1e-9);
            }
        }
        EXPECT_GE(onPlane, 4);
    }
}

// A contact side in four edges in a row: the vertices between them slide onto the new contact curve
TEST_F(RollingBallBlendTest, contactSideInSeveralEdges)
{
    const double radius = 0.79375;
    TopoDS_Face lid;
    const TopoDS_Shape base = runOutBase(0.02, lid);
    Filleted occt = occtFillet(base, lid, radius, 9.9);
    ASSERT_FALSE(occt.shape.IsNull());
    splitAContactEdge(occt);

    const RB::Report report = RB::correct(occt.shape, occt.blends, radius);

    ASSERT_EQ(report.outcome, RB::Outcome::Corrected) << report.reason;
    EXPECT_EQ(report.faces, 3);
    EXPECT_LT(report.residualAfter, 1e-6);
    EXPECT_TRUE(BRepCheck_Analyzer(report.shape).IsValid());
    EXPECT_EQ(count(report.shape, TopAbs_EDGE), count(occt.shape, TopAbs_EDGE));
    EXPECT_EQ(count(report.shape, TopAbs_VERTEX), count(occt.shape, TopAbs_VERTEX));
}

// Blends of exact form (cylinders and tori between planes and cylinders) are rolling balls already
TEST_F(RollingBallBlendTest, exactFormsAreLeftAlone)
{
    TopoDS_Face lid;
    const TopoDS_Shape base = stadiumBase(0.0, Lid::TopPlane, lid);
    const Filleted occt = occtFillet(base, lid, 1.5);
    ASSERT_FALSE(occt.shape.IsNull());

    const RB::Report report = RB::correct(occt.shape, occt.blends, 1.5);

    EXPECT_EQ(report.outcome, RB::Outcome::NotMine);
    EXPECT_TRUE(report.shape.IsNull());
}

// A blend of exact form that ends on faces of the base (a cylinder between planes): OCCT's result stands
TEST_F(RollingBallBlendTest, aBlendEndingOnABaseFaceIsLeftAlone)
{
    const TopoDS_Shape box = BRepPrimAPI_MakeBox(20, 10, 5).Shape();
    BRepFilletAPI_MakeFillet maker(box);
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(box, TopAbs_EDGE, edges);
    maker.Add(1.0, TopoDS::Edge(edges(1)));
    maker.Build();
    ASSERT_TRUE(maker.IsDone());
    std::vector<TopoDS_Face> blends;
    for (TopTools_ListOfShape::Iterator it(maker.Generated(edges(1))); it.More(); it.Next()) {
        if (it.Value().ShapeType() == TopAbs_FACE) {
            blends.push_back(TopoDS::Face(it.Value()));
        }
    }

    const RB::Report report = RB::correct(maker.Shape(), blends, 1.0);

    EXPECT_EQ(report.outcome, RB::Outcome::NotMine);
}

// Through makeElementFillet: the blend is corrected and every element keeps the name OCCT's fillet
// alone gives it
TEST_F(RollingBallBlendTest, makeElementFilletKeepsTheNames)
{
    const double radius = 1.5;
    TopoDS_Face lid;
    TopoShape base(stadiumBase(0.02, Lid::Spline, lid), 1L);
    std::vector<TopoShape> edges;
    for (const auto& edge : base.getSubTopoShapes(TopAbs_EDGE)) {
        for (TopExp_Explorer it(lid, TopAbs_EDGE); it.More(); it.Next()) {
            if (it.Current().IsSame(edge.getShape())) {
                edges.push_back(edge);
                break;
            }
        }
    }
    ASSERT_EQ(edges.size(), 4U);

    TopoShape result(2L);
    result.makeElementFillet(base, edges, radius, radius);

    // OCCT's fillet alone, named the same way
    BRepFilletAPI_MakeFillet maker(base.getShape());
    for (const auto& edge : edges) {
        maker.Add(radius, TopoDS::Edge(edge.getShape()));
    }
    maker.Build();
    ASSERT_TRUE(maker.IsDone());
    TopoShape expected(2L);
    expected.makeElementShape(maker, base, OpCodes::Fillet);

    EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
    EXPECT_FALSE(elementNames(result).empty());
    EXPECT_EQ(elementNames(result), elementNames(expected));
    EXPECT_EQ(count(result.getShape(), TopAbs_FACE), count(expected.getShape(), TopAbs_FACE));
    // The blend faces are the ball's now: each B-spline face of the result against the two faces
    // it touches along its long edges is checked by the unit; here, the worst tolerance says the
    // geometry was replaced (OCCT's fillet leaves 1e-4)
    EXPECT_GT(maxTolerance(expected.getShape()), 1e-5);
    EXPECT_LE(maxTolerance(result.getShape()), 1e-6);
}

// A stadium whose walls lean: the stadium at the floor z = 5 (lines y = -10 and y = 10, half circles
// of radius 10 about x = -20 and x = 20) swept along (0.3, 0.2, 1), as a pocket cut into a block or as
// a boss on a slab. The edges at the floor are rounded. Under the leaning planes the round is a
// cylinder; under the leaning circles' walls (elliptic cylinders, not normal to the floor) it is
// OCCT's spline (Nest Insert #163's slot round)
const double pocketFloor = 5.0;
const gp_Vec pocketLean(0.3, 0.2, 1.0);

enum class Leaning
{
    Pocket,
    Boss
};

Filleted leaningStadium(Leaning kind, double radius)
{
    Filleted result;
    const gp_Pnt a1(-20, -10, pocketFloor);
    const gp_Pnt a2(20, -10, pocketFloor);
    const gp_Pnt a3(20, 10, pocketFloor);
    const gp_Pnt a4(-20, 10, pocketFloor);
    BRepBuilderAPI_MakeWire wire;
    wire.Add(BRepBuilderAPI_MakeEdge(a1, a2).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(a2, gp_Pnt(30, 0, pocketFloor), a3).Value()).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(a3, a4).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(a4, gp_Pnt(-30, 0, pocketFloor), a1).Value()).Edge());
    const TopoDS_Shape tool
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(wire.Wire()).Face(), pocketLean * 30.0).Shape();
    const TopoDS_Shape base = kind == Leaning::Pocket
        ? BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(gp_Pnt(-45, -30, 0), gp_Pnt(55, 40, 25)).Shape(), tool).Shape()
        : BRepAlgoAPI_Fuse(BRepPrimAPI_MakeBox(gp_Pnt(-45, -30, 0), gp_Pnt(55, 40, pocketFloor)).Shape(), tool)
              .Shape();
    // The rim: the edges at the floor's height along the stadium (not the block's own outline)
    TopTools_IndexedMapOfShape all;
    TopExp::MapShapes(base, TopAbs_EDGE, all);
    std::vector<TopoDS_Edge> rim;
    for (int i = 1; i <= all.Extent(); ++i) {
        const BRepAdaptor_Curve curve(TopoDS::Edge(all(i)));
        bool atFloor = true;
        for (int k = 0; k <= 4; ++k) {
            const double at = curve.FirstParameter() + (curve.LastParameter() - curve.FirstParameter()) * k / 4;
            atFloor = atFloor && std::fabs(curve.Value(at).Z() - pocketFloor) < 1e-7;
        }
        const gp_Pnt middle = curve.Value(0.5 * (curve.FirstParameter() + curve.LastParameter()));
        if (atFloor && std::fabs(middle.X()) < 41 && std::fabs(middle.Y()) < 11) {
            rim.push_back(TopoDS::Edge(all(i)));
        }
    }
    if (rim.size() != 4) {
        return result;
    }
    BRepFilletAPI_MakeFillet maker(base);
    for (const TopoDS_Edge& edge : rim) {
        maker.Add(radius, edge);
    }
    maker.Build();
    if (!maker.IsDone()) {
        return result;
    }
    TopTools_IndexedMapOfShape blends;
    for (const TopoDS_Edge& edge : rim) {
        for (TopTools_ListOfShape::Iterator it(maker.Generated(edge)); it.More(); it.Next()) {
            // (a contour's edges each list the contour's faces: each once)
            if (it.Value().ShapeType() == TopAbs_FACE && !blends.Contains(it.Value())) {
                blends.Add(it.Value());
                result.blends.push_back(TopoDS::Face(it.Value()));
            }
        }
    }
    result.shape = maker.Shape();
    return result;
}

/// The distance from a point to a leaning wall of the pocket: the circle of radius 10 about
/// (centreX, 0) at the floor, swept along the lean. Closed form but for one angle, found by search
double leaningWallDistance(const gp_Pnt& point, double centreX)
{
    const gp_Vec direction = pocketLean.Normalized();
    auto at = [&](double angle) {
        const gp_Vec offset(
            gp_Pnt(centreX + 10 * std::cos(angle), 10 * std::sin(angle), pocketFloor),
            point
        );
        return (offset - direction * offset.Dot(direction)).Magnitude();
    };
    const double step = std::numbers::pi / 360;
    double nearest = 1e9;
    double where = 0.0;
    for (int k = 0; k < 720; ++k) {
        if (at(k * step) < nearest) {
            nearest = at(k * step);
            where = k * step;
        }
    }
    double low = where - step;
    double high = where + step;
    for (int iteration = 0; iteration < 200; ++iteration) {
        const double m1 = low + (high - low) * 0.381966;
        const double m2 = low + (high - low) * 0.618034;
        (at(m1) < at(m2) ? high : low) = at(m1) < at(m2) ? m2 : m1;
    }
    return at(0.5 * (low + high));
}

/// How far a face of the pocket's round is from the ball's surface: over a grid, the ball's centre
/// (the point moved by the radius along the normal) must be the radius above the floor and the
/// radius from the leaning wall
double leaningPocketMiss(const TopoDS_Face& face, double radius)
{
    const BRepAdaptor_Surface surface(face);
    double worst = 0.0;
    for (int i = 1; i < 12; ++i) {
        for (int j = 1; j < 40; ++j) {
            const double u = surface.FirstUParameter()
                + (surface.LastUParameter() - surface.FirstUParameter()) * i / 12;
            const double v = surface.FirstVParameter()
                + (surface.LastVParameter() - surface.FirstVParameter()) * j / 40;
            gp_Pnt point;
            gp_Vec du;
            gp_Vec dv;
            surface.D1(u, v, point, du, dv);
            const gp_Vec normal = du.Crossed(dv).Normalized();
            gp_Pnt centre = point.Translated(normal * radius);
            const gp_Pnt other = point.Translated(normal * -radius);
            if (std::fabs(other.Z() - pocketFloor - radius) < std::fabs(centre.Z() - pocketFloor - radius)) {
                centre = other;
            }
            worst = std::max(
                {worst,
                 std::fabs(centre.Z() - pocketFloor - radius),
                 std::fabs(leaningWallDistance(centre, point.X() > 0 ? 20.0 : -20.0) - radius)}
            );
        }
    }
    return worst;
}

bool isSpline(const TopoDS_Face& face)
{
    return BRep_Tool::Surface(face)->IsKind(STANDARD_TYPE(Geom_BSplineSurface));
}

// A chain of cylinders and spline faces: the cylinders are the ball's already and stay as they are;
// the spline faces between them become the ball's. On the boss OCCT's seams are not where the ball
// crosses from a plane's wall to a circle's: they move, sliding along the cylinders' own contact lines
TEST_F(RollingBallBlendTest, exactFacesAmongSplineOnesStay)
{
    for (const Leaning kind : {Leaning::Pocket, Leaning::Boss}) {
        for (const double radius : {1.0, 2.0, 4.0}) {
            const std::string which
                = std::string(kind == Leaning::Pocket ? "pocket" : "boss") + ", radius " + std::to_string(radius);
            const Filleted occt = leaningStadium(kind, radius);
            ASSERT_FALSE(occt.shape.IsNull()) << which;
            int splines = 0;
            double occtMiss = 0.0;
            for (const TopoDS_Face& blend : occt.blends) {
                if (isSpline(blend)) {
                    ++splines;
                    occtMiss = std::max(occtMiss, leaningPocketMiss(blend, radius));
                }
            }
            ASSERT_EQ(occt.blends.size(), 4U) << which;
            ASSERT_EQ(splines, 2) << which;
            // The designed model has the defect: OCCT's section is in the plane normal to the edge
            EXPECT_GT(occtMiss, 5e-4) << which;

            const RB::Report report = RB::correct(occt.shape, occt.blends, radius);

            ASSERT_EQ(report.outcome, RB::Outcome::Corrected) << which << ": " << report.reason;
            EXPECT_EQ(report.faces, 2) << which;
            if (kind == Leaning::Boss) {
                EXPECT_GT(report.seamMove, 1e-3) << which;
            }
            EXPECT_TRUE(BRepCheck_Analyzer(report.shape).IsValid()) << which;
            // OCCT's fillet leaves 3e-3 and more on its blend's edges; what is left is the model's own
            // Boolean (5e-6 on the pocket)
            EXPECT_GT(maxTolerance(occt.shape), 1e-3) << which;
            EXPECT_LE(maxTolerance(report.shape), 1e-5) << which;
            for (const TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
                EXPECT_EQ(count(report.shape, type), count(occt.shape, type)) << which;
            }
            ASSERT_EQ(report.blendFaces.size(), occt.blends.size());
            for (size_t i = 0; i < occt.blends.size(); ++i) {
                if (isSpline(occt.blends[i])) {
                    EXPECT_LT(leaningPocketMiss(report.blendFaces[i], radius), 1e-6) << which;
                }
                else {
                    // The cylinder under a leaning plane: the same surface, a cylinder of the radius
                    const BRepAdaptor_Surface before(occt.blends[i]);
                    const BRepAdaptor_Surface after(report.blendFaces[i]);
                    ASSERT_EQ(after.GetType(), GeomAbs_Cylinder) << which;
                    EXPECT_NEAR(after.Cylinder().Radius(), radius, 1e-12) << which;
                    EXPECT_LT(after.Cylinder().Location().Distance(before.Cylinder().Location()), 1e-12) << which;
                    EXPECT_TRUE(after.Cylinder().Axis().IsParallel(before.Cylinder().Axis(), 1e-12)) << which;
                }
            }
        }
    }
}

}  // namespace

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
