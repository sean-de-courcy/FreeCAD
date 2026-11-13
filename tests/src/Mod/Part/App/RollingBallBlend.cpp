// SPDX-License-Identifier: LGPL-2.1-or-later

// A constant-radius blend as a true rolling ball (ops#640, decision 425; design:
// notes/rolling-ball-blend.md in the ops repository). Designed models only. Every expectation is
// geometric: the ball of the fillet's radius touches both walls (the residual), and where the model
// has a closed form, the seam's place.

#include <array>
#include <cmath>
#include <set>
#include <string>
#include <vector>
#include <gtest/gtest.h>

#include "src/App/InitApplication.h"
#include <Base/Exception.h>
#include <Mod/Part/App/RollingBallBlend.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include <BRepAlgoAPI_Cut.hxx>
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

}  // namespace

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
