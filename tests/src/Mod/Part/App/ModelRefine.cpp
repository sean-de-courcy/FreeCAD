// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <vector>

#include <BRepAlgoAPI_BuilderAlgo.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <ElSLib.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GProp_GProps.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_Plane.hxx>
#include <Geom_SphericalSurface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_Array1OfPnt2d.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec2d.hxx>

#include <Mod/Part/App/modelRefine.h>

namespace
{

double volumeOf(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape, props);
    return props.Mass();
}

TopoDS_Shape refine(const TopoDS_Shape& shape)
{
    Part::BRepBuilderAPI_RefineModel mkRefine(shape);
    return mkRefine.Shape();
}

/// A cylinder fused with a box flush to its top, so refine has a coplanar pair to merge.
///
/// Without a merge FaceUniter::process returns before it ever reaches BRepLib_FuseEdges,
/// and nothing below can happen.
TopoDS_Shape cylinderWithCoplanarBox()
{
    const TopoDS_Shape cylinder = BRepPrimAPI_MakeCylinder(5.0, 10.0).Shape();
    const TopoDS_Shape box = BRepPrimAPI_MakeBox(gp_Pnt(-3.0, 3.0, 6.0), 6.0, 5.0, 4.0).Shape();
    return BRepAlgoAPI_Fuse(cylinder, box).Shape();
}

/// <shape> with <point> imprinted onto it, splitting whichever edge it lands on.
TopoDS_Shape imprintVertex(const TopoDS_Shape& shape, const gp_Pnt& point)
{
    TopTools_ListOfShape arguments;
    arguments.Append(shape);
    arguments.Append(BRepBuilderAPI_MakeVertex(point).Shape());

    BRepAlgoAPI_BuilderAlgo builder;
    builder.SetArguments(arguments);
    builder.SetNonDestructive(Standard_True);
    builder.Build();

    for (TopExp_Explorer xp(builder.Shape(), TopAbs_SOLID); xp.More(); xp.Next()) {
        return xp.Current();
    }
    return {};
}

}  // namespace

class ModelRefineTest: public ::testing::Test
{
protected:
    /// The cylinder's seam runs up +X at y = 0, so this point lands on it two thirds up.
    /// The vertex subdivides the seam while belonging to nothing else - 2 edges, 1 face.
    static constexpr double seamX = 5.0;
    static constexpr double seamZ = 6.0;
};

TEST_F(ModelRefineTest, testRefineKeepsASolidValidWhenAVertexSplitsASeam)
{
    // Arrange
    const TopoDS_Shape solid = imprintVertex(cylinderWithCoplanarBox(), gp_Pnt(seamX, 0.0, seamZ));
    ASSERT_FALSE(solid.IsNull());
    ASSERT_TRUE(BRepCheck_Analyzer(solid).IsValid());

    // Act
    const TopoDS_Shape refined = refine(solid);

    // Assert - BRepLib_FuseEdges rejoins the two seam halves into one edge, but the face
    // walks its seam twice and needs a pcurve for each pass
    EXPECT_TRUE(BRepCheck_Analyzer(refined).IsValid());
}

TEST_F(ModelRefineTest, testRefinePreservesVolumeWhenAVertexSplitsASeam)
{
    // Refine only merges faces lying on the same surface, so volume is an invariant.
    const TopoDS_Shape solid = imprintVertex(cylinderWithCoplanarBox(), gp_Pnt(seamX, 0.0, seamZ));
    ASSERT_FALSE(solid.IsNull());

    EXPECT_NEAR(volumeOf(refine(solid)), volumeOf(solid), 1e-6);
}

TEST_F(ModelRefineTest, testRefineLeavesNoEmptyFaceWhenAVertexSplitsASeam)
{
    const TopoDS_Shape solid = imprintVertex(cylinderWithCoplanarBox(), gp_Pnt(seamX, 0.0, seamZ));
    ASSERT_FALSE(solid.IsNull());

    for (TopExp_Explorer xp(refine(solid), TopAbs_FACE); xp.More(); xp.Next()) {
        GProp_GProps props;
        BRepGProp::SurfaceProperties(xp.Current(), props);
        EXPECT_GT(props.Mass(), 0.0);
    }
}

TEST_F(ModelRefineTest, testRefineIsUnharmedByAVertexOffTheSeam)
{
    // The control: same construction, same imprint, only the angle differs. It is what
    // makes the tests above point at the seam rather than at imprinting in general.
    const TopoDS_Shape solid = imprintVertex(cylinderWithCoplanarBox(), gp_Pnt(0.0, seamX, seamZ));
    ASSERT_FALSE(solid.IsNull());

    const TopoDS_Shape refined = refine(solid);

    EXPECT_TRUE(BRepCheck_Analyzer(refined).IsValid());
    EXPECT_NEAR(volumeOf(refined), volumeOf(solid), 1e-6);
}

// The refine's fuse of edges, checked (FreeCAD-CH ops#640, Case Base's Finger Hole after an exact
// Finger Grip Overhang Fillet 2; modelRefine.cpp, "The fuse of edges, checked").
//
// Designed model: a prism 20 x 10 x 8 whose cap (the plane y = 0) has a parabola for its right
// side, from (10, 0, 0) to (10, 0, 10) through (9, 0, 5): chord 10, sagitta 1, so the cap is
// 20 * 10 - 2/3 * 10 * 1 = 193 1/3 mm2. The parabola edge is split into three spans, at
// parameters 0.3 and 0.7, by imprinted vertices: both its faces stay whole. A box fused beside
// the prism gives the refine two coplanar faces to merge, so that it fuses edges.
//
// What the exact construction of a round leaves on a wall is then written onto the spans with
// BRep_Builder: each span's 2D curve on the cap's plane, stored. The outer spans get a curve of
// their own, exactly their range; the middle one lies on a part of the whole parabola's. All
// three are exact: the shape is valid, with the cap's area as before.
//
// BRepLib_FuseEdges joins the 2D curves of the edges it fuses; where the first one's does not
// span the fused edge, it adds the others' whole, not over each edge's own range. Here the
// fused edge's curve on the cap ran along the whole parabola and back, millimetres from its 3D
// curve; the face fix raised the edge's and its vertices' tolerance to cover that, and the shape
// check passed (on Case Base: 7.98 mm on a side wall, and the next cut into the wall failed).
// Without the check, testSpansWithTheirOwnStoredCurvesFuseIntoOneEdgeOnItsFaces reads a
// tolerance of 8.11 mm, in the refined shape and in the shape refined, and a cap of 200.66 mm2.
namespace
{

constexpr double capArea = 20.0 * 10.0 - 2.0 / 3.0 * 10.0 * 1.0;
constexpr double boxVolume = 3.0 * 4.0 * 5.0;

Handle(Geom_BSplineCurve) parabola()
{
    TColgp_Array1OfPnt poles(1, 3);
    poles(1) = gp_Pnt(10.0, 0.0, 0.0);
    poles(2) = gp_Pnt(8.0, 0.0, 5.0);
    poles(3) = gp_Pnt(10.0, 0.0, 10.0);
    TColStd_Array1OfReal knots(1, 2);
    knots(1) = 0.0;
    knots(2) = 1.0;
    TColStd_Array1OfInteger mults(1, 2);
    mults(1) = 3;
    mults(2) = 3;
    return new Geom_BSplineCurve(poles, knots, mults, 2);
}

/// The prism with its parabola edge in three spans, fused with the box beside it (unrefined)
TopoDS_Shape prismWithThreeSpans(const Handle(Geom_BSplineCurve) & curve)
{
    BRepBuilderAPI_MakeWire outline;
    outline.Add(BRepBuilderAPI_MakeEdge(curve).Edge());
    outline.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(10.0, 0.0, 10.0), gp_Pnt(-10.0, 0.0, 10.0)).Edge());
    outline.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(-10.0, 0.0, 10.0), gp_Pnt(-10.0, 0.0, 0.0)).Edge());
    outline.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(-10.0, 0.0, 0.0), gp_Pnt(10.0, 0.0, 0.0)).Edge());
    const TopoDS_Face profile = BRepBuilderAPI_MakeFace(outline.Wire()).Face();
    TopoDS_Shape prism = BRepPrimAPI_MakePrism(profile, gp_Vec(0.0, 8.0, 0.0)).Shape();
    prism = imprintVertex(prism, curve->Value(0.7));
    prism = imprintVertex(prism, curve->Value(0.3));
    const TopoDS_Shape box = BRepPrimAPI_MakeBox(gp_Pnt(-13.0, 2.0, 0.0), 3.0, 4.0, 5.0).Shape();
    return BRepAlgoAPI_Fuse(prism, box).Shape();
}

struct Cap
{
    TopoDS_Face face;
    Handle(Geom_Plane) plane;
    std::vector<TopoDS_Edge> spans;  // its B-spline edges, in the order of their parameter
};

/// The face in the plane y = 0 and its parabola edges
Cap capOf(const TopoDS_Shape& shape)
{
    Cap cap;
    for (TopExp_Explorer faces(shape, TopAbs_FACE); faces.More(); faces.Next()) {
        const TopoDS_Face& face = TopoDS::Face(faces.Current());
        const Handle(Geom_Plane) plane = Handle(Geom_Plane)::DownCast(BRep_Tool::Surface(face));
        if (plane.IsNull() || std::abs(std::abs(plane->Axis().Direction().Y()) - 1.0) > 1e-9
            || std::abs(plane->Location().Y()) > 1e-9) {
            continue;
        }
        cap.face = face;
        cap.plane = plane;
        for (TopExp_Explorer edges(face, TopAbs_EDGE); edges.More(); edges.Next()) {
            double first = 0.0;
            double last = 0.0;
            const Handle(Geom_Curve) curve
                = BRep_Tool::Curve(TopoDS::Edge(edges.Current()), first, last);
            if (!Handle(Geom_BSplineCurve)::DownCast(curve).IsNull()) {
                cap.spans.push_back(TopoDS::Edge(edges.Current()));
            }
        }
    }
    std::sort(cap.spans.begin(), cap.spans.end(), [](const TopoDS_Edge& a, const TopoDS_Edge& b) {
        double first = 0.0;
        double last = 0.0;
        double otherFirst = 0.0;
        BRep_Tool::Range(a, first, last);
        BRep_Tool::Range(b, otherFirst, last);
        return first < otherFirst;
    });
    return cap;
}

/// The parabola on the cap's plane: a 2D B-spline with the same knots, so that at each parameter
/// it is where the 3D curve is
Handle(Geom2d_BSplineCurve) onPlane(
    const Handle(Geom_BSplineCurve) & curve,
    const Handle(Geom_Plane) & plane
)
{
    TColgp_Array1OfPnt2d poles(1, curve->NbPoles());
    for (int index = 1; index <= curve->NbPoles(); ++index) {
        double u = 0.0;
        double v = 0.0;
        ElSLib::Parameters(plane->Pln(), curve->Pole(index), u, v);
        poles(index) = gp_Pnt2d(u, v);
    }
    TColStd_Array1OfReal knots(1, curve->NbKnots());
    curve->Knots(knots);
    TColStd_Array1OfInteger mults(1, curve->NbKnots());
    curve->Multiplicities(mults);
    return new Geom2d_BSplineCurve(poles, knots, mults, curve->Degree());
}

/// Stores each span's 2D curve on the cap: the outer spans' exactly their range, the middle one's
/// the whole parabola's, moved by \a middleOff in the plane (0: exact)
void storeSpanCurves(
    const Cap& cap,
    const Handle(Geom_BSplineCurve) & curve,
    double middleOff = 0.0
)
{
    BRep_Builder builder;
    for (std::size_t index = 0; index < cap.spans.size(); ++index) {
        double first = 0.0;
        double last = 0.0;
        BRep_Tool::Range(cap.spans[index], first, last);
        const Handle(Geom2d_BSplineCurve) curve2d = onPlane(curve, cap.plane);
        if (index == 1) {
            curve2d->Translate(gp_Vec2d(middleOff, 0.0));
        }
        else {
            curve2d->Segment(first, last);
        }
        const TopoDS_Edge& span = cap.spans[index];
        builder.UpdateEdge(span, curve2d, cap.face, BRep_Tool::Tolerance(span));
    }
}

/// The largest distance of an edge's stored 2D curve on the cap from its 3D curve, at the same
/// parameter; -1 where it has none stored
double gapOnCap(const TopoDS_Edge& edge, const Cap& cap)
{
    double first = 0.0;
    double last = 0.0;
    const Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);
    bool stored = false;
    double first2d = 0.0;
    double last2d = 0.0;
    const Handle(Geom2d_Curve) curve2d
        = BRep_Tool::CurveOnSurface(edge, cap.face, first2d, last2d, &stored);
    if (curve2d.IsNull() || !stored) {
        return -1.0;
    }
    double gap = 0.0;
    for (int index = 0; index <= 40; ++index) {
        const double at = index / 40.0;
        const gp_Pnt2d uv = curve2d->Value(first2d + (last2d - first2d) * at);
        const gp_Pnt on3d = curve->Value(first + (last - first) * at);
        gap = std::max(gap, cap.plane->Value(uv.X(), uv.Y()).Distance(on3d));
    }
    return gap;
}

double areaOf(const TopoDS_Shape& face)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(face, props);
    return props.Mass();
}

double worstTolerance(const TopoDS_Shape& shape)
{
    double worst = 0.0;
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(shape, TopAbs_EDGE, edges);
    for (int index = 1; index <= edges.Extent(); ++index) {
        worst = std::max(worst, BRep_Tool::Tolerance(TopoDS::Edge(edges(index))));
    }
    TopTools_IndexedMapOfShape vertices;
    TopExp::MapShapes(shape, TopAbs_VERTEX, vertices);
    for (int index = 1; index <= vertices.Extent(); ++index) {
        worst = std::max(worst, BRep_Tool::Tolerance(TopoDS::Vertex(vertices(index))));
    }
    return worst;
}

int faceCount(const TopoDS_Shape& shape)
{
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    return faces.Extent();
}

}  // namespace

TEST(RefineFuseEdgesTest, testSpansWithNoStoredCurveFuseIntoOneEdge)
{
    // The control: the spans as a Boolean leaves them, with no 2D curve stored on the plane.
    // OCCT's fuse is right there
    const Handle(Geom_BSplineCurve) curve = parabola();
    const TopoDS_Shape solid = prismWithThreeSpans(curve);
    ASSERT_EQ(capOf(solid).spans.size(), 3U);
    ASSERT_TRUE(BRepCheck_Analyzer(solid).IsValid());

    const TopoDS_Shape refined = refine(solid);

    EXPECT_TRUE(BRepCheck_Analyzer(refined).IsValid());
    EXPECT_LT(faceCount(refined), faceCount(solid));
    const Cap cap = capOf(refined);
    ASSERT_EQ(cap.spans.size(), 1U);
    EXPECT_NEAR(areaOf(cap.face), capArea, 1e-6);
    EXPECT_NEAR(volumeOf(refined), capArea * 8.0 + boxVolume, 1e-6);
    EXPECT_LE(worstTolerance(refined), 1e-6);
}

TEST(RefineFuseEdgesTest, testSpansWithTheirOwnStoredCurvesFuseIntoOneEdgeOnItsFaces)
{
    // Arrange: the three spans with their stored 2D curves, all exact
    const Handle(Geom_BSplineCurve) curve = parabola();
    const TopoDS_Shape solid = prismWithThreeSpans(curve);
    const Cap before = capOf(solid);
    ASSERT_EQ(before.spans.size(), 3U);
    storeSpanCurves(before, curve);
    for (const TopoDS_Edge& span : before.spans) {
        const double gap = gapOnCap(span, before);
        ASSERT_GE(gap, 0.0);  // stored
        ASSERT_LE(gap, 1e-12);
    }
    ASSERT_TRUE(BRepCheck_Analyzer(solid).IsValid());
    ASSERT_NEAR(areaOf(before.face), capArea, 1e-9);
    ASSERT_LE(worstTolerance(solid), 1e-6);

    // Act
    const TopoDS_Shape refined = refine(solid);

    // Assert: one edge again, on its 3D curve on the cap, and no tolerance raised to hide a gap
    EXPECT_TRUE(BRepCheck_Analyzer(refined).IsValid());
    EXPECT_LT(faceCount(refined), faceCount(solid));
    EXPECT_LE(worstTolerance(refined), 1e-6);
    const Cap cap = capOf(refined);
    ASSERT_EQ(cap.spans.size(), 1U);
    double first = 0.0;
    double last = 0.0;
    BRep_Tool::Range(cap.spans[0], first, last);
    EXPECT_NEAR(first, 0.0, 1e-12);
    EXPECT_NEAR(last, 1.0, 1e-12);
    EXPECT_LE(gapOnCap(cap.spans[0], cap), 1e-9);
    EXPECT_NEAR(areaOf(cap.face), capArea, 1e-6);
    EXPECT_NEAR(volumeOf(refined), capArea * 8.0 + boxVolume, 1e-6);
    // nor in the shape refined: the fuse works on vertices the two share
    EXPECT_LE(worstTolerance(solid), 1e-6);
}

TEST(RefineFuseEdgesTest, testSpansWhoseStoredCurvesDoNotMeetStayApart)
{
    // A control: as above, but the middle span's 2D curve lies 1e-4 beside the others', within
    // the edges' tolerance of 1e-3: a valid shape whose 2D curves cannot be joined into one.
    // OCCT's fuse leaves such spans apart itself (it joins 2D curves only where their ends
    // coincide, which is why the whole curve added at the wrong end above goes unnoticed), and
    // the check changes nothing here
    const Handle(Geom_BSplineCurve) curve = parabola();
    const TopoDS_Shape solid = prismWithThreeSpans(curve);
    const Cap before = capOf(solid);
    ASSERT_EQ(before.spans.size(), 3U);
    storeSpanCurves(before, curve, 1e-4);
    BRep_Builder builder;
    for (const TopoDS_Edge& span : before.spans) {
        builder.UpdateEdge(span, 1e-3);
        for (TopExp_Explorer ends(span, TopAbs_VERTEX); ends.More(); ends.Next()) {
            builder.UpdateVertex(TopoDS::Vertex(ends.Current()), 1e-3);
        }
    }
    ASSERT_TRUE(BRepCheck_Analyzer(solid).IsValid());
    ASSERT_NEAR(worstTolerance(solid), 1e-3, 1e-12);

    // Act
    const TopoDS_Shape refined = refine(solid);

    // Assert: the faces merged, the spans were left as they were, and nothing grew
    EXPECT_TRUE(BRepCheck_Analyzer(refined).IsValid());
    EXPECT_LT(faceCount(refined), faceCount(solid));
    EXPECT_NEAR(worstTolerance(refined), 1e-3, 1e-12);
    const Cap cap = capOf(refined);
    EXPECT_EQ(cap.spans.size(), 3U);
    EXPECT_NEAR(areaOf(cap.face), capArea, 1e-3);
    EXPECT_NEAR(volumeOf(refined), capArea * 8.0 + boxVolume, 1e-2);
    EXPECT_NEAR(worstTolerance(solid), 1e-3, 1e-12);
}

// The same fuse on a round's cut edge (ops#640, Case Base 105's ends by the blend's continuation).
//
// Designed model: a block 20 x 10 x 10 whose edge along x at (y 0, z 10) is rounded with r 3 (a
// cylinder about the line y 3, z 7), cut at its end by a ball of radius 7 about (21, -1, 11). The
// round's cut edge is the cylinder's intersection with the ball: one B-spline edge between the
// round and the ball's face. A ruling of the cylinder, 30 degrees round from its top, is
// imprinted: the round is two faces of one cylinder that meet along that shared edge, and the
// cut edge two spans that meet at its end. The refine merges the two cylinder faces, so the two
// spans come to lie between the same two faces, and it fuses edges.
//
// The spans are then given what a construction may leave on them: both on one 3D curve, one of
// them with a 2D curve of its own on the ball's face and the other on a part of the whole cut
// edge's (the wrong join, as on the prism above); or each on a 3D curve of its own, as the exact
// construction builds a round's end from two tools (those are no one curve, and stay two edges).
// A refine changes no volume and no face's area that it doesn't merge: the expected values are
// the unrefined shape's own. Without the check, the span with a 2D curve of its own first gives
// a tolerance of millimetres (1.72 or 4.24, as the Boolean happens to run the cut edge) and a
// ball's face off by square millimetres.
namespace
{

constexpr double roundRadius = 3.0;

TopoDS_Shape imprint(const TopoDS_Shape& shape, const TopoDS_Shape& tool)
{
    TopTools_ListOfShape arguments;
    arguments.Append(shape);
    arguments.Append(tool);

    BRepAlgoAPI_BuilderAlgo builder;
    builder.SetArguments(arguments);
    builder.SetNonDestructive(Standard_True);
    builder.Build();

    for (TopExp_Explorer xp(builder.Shape(), TopAbs_SOLID); xp.More(); xp.Next()) {
        return xp.Current();
    }
    return {};
}

/// The rounded block cut by the ball, the round in two faces along one ruling
TopoDS_Shape roundCutByABall()
{
    const double r = roundRadius;
    const double c = r / std::sqrt(2.0);
    BRepBuilderAPI_MakeWire outline;
    outline.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(0, 10, 0)).Edge());
    outline.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 10, 0), gp_Pnt(0, 10, 10)).Edge());
    outline.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 10, 10), gp_Pnt(0, r, 10)).Edge());
    const gp_Pnt arcMiddle(0, r - c, 10 - r + c);
    const GC_MakeArcOfCircle arc(gp_Pnt(0, r, 10), arcMiddle, gp_Pnt(0, 0, 10 - r));
    outline.Add(BRepBuilderAPI_MakeEdge(arc.Value()).Edge());
    outline.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 10 - r), gp_Pnt(0, 0, 0)).Edge());
    const TopoDS_Face profile = BRepBuilderAPI_MakeFace(outline.Wire()).Face();
    const TopoDS_Shape block = BRepPrimAPI_MakePrism(profile, gp_Vec(20.0, 0.0, 0.0)).Shape();
    const TopoDS_Shape ball = BRepPrimAPI_MakeSphere(gp_Pnt(21.0, -1.0, 11.0), 7.0).Shape();
    const TopoDS_Shape pieces = BRepAlgoAPI_Cut(block, ball).Shape();
    TopoDS_Shape cut;
    for (TopExp_Explorer xp(pieces, TopAbs_SOLID); xp.More(); xp.Next()) {
        cut = xp.Current();
    }
    // the ruling 30 degrees round from the top of the round, run on past the ball's face
    const double y = r - r * 0.5;
    const double z = 10.0 - r + r * std::sqrt(3.0) / 2.0;
    return imprint(cut, BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, y, z), gp_Pnt(19.0, y, z)).Edge());
}

struct RoundEnd
{
    TopoDS_Face ball;                // the ball's face
    std::vector<TopoDS_Face> round;  // the round's cylinder faces
    std::vector<TopoDS_Edge> spans;  // the cut edge's spans, in the order of their parameter
};

RoundEnd roundEndOf(const TopoDS_Shape& shape)
{
    RoundEnd end;
    for (TopExp_Explorer faces(shape, TopAbs_FACE); faces.More(); faces.Next()) {
        const TopoDS_Face& face = TopoDS::Face(faces.Current());
        const Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
        if (!Handle(Geom_SphericalSurface)::DownCast(surface).IsNull()) {
            end.ball = face;
        }
        const Handle(Geom_CylindricalSurface) cylinder
            = Handle(Geom_CylindricalSurface)::DownCast(surface);
        if (!cylinder.IsNull() && std::abs(cylinder->Radius() - roundRadius) < 1e-9) {
            end.round.push_back(face);
        }
    }
    for (TopExp_Explorer edges(end.ball, TopAbs_EDGE); edges.More(); edges.Next()) {
        double first = 0.0;
        double last = 0.0;
        Handle(Geom_Curve) curve = BRep_Tool::Curve(TopoDS::Edge(edges.Current()), first, last);
        if (const auto trimmed = Handle(Geom_TrimmedCurve)::DownCast(curve); !trimmed.IsNull()) {
            curve = trimmed->BasisCurve();
        }
        if (!Handle(Geom_BSplineCurve)::DownCast(curve).IsNull()) {
            end.spans.push_back(TopoDS::Edge(edges.Current()));
        }
    }
    std::sort(end.spans.begin(), end.spans.end(), [](const TopoDS_Edge& a, const TopoDS_Edge& b) {
        double first = 0.0;
        double last = 0.0;
        double otherFirst = 0.0;
        BRep_Tool::Range(a, first, last);
        BRep_Tool::Range(b, otherFirst, last);
        return first < otherFirst;
    });
    return end;
}

/// A span's stored 2D curve on the ball's face as a B-spline of its own, exactly its range
Handle(Geom2d_BSplineCurve) ownCurveOnBall(const TopoDS_Edge& span, const TopoDS_Face& ball)
{
    double first = 0.0;
    double last = 0.0;
    bool stored = false;
    Handle(Geom2d_Curve) curve2d = BRep_Tool::CurveOnSurface(span, ball, first, last, &stored);
    if (curve2d.IsNull() || !stored) {
        return {};
    }
    if (const auto trimmed = Handle(Geom2d_TrimmedCurve)::DownCast(curve2d); !trimmed.IsNull()) {
        curve2d = trimmed->BasisCurve();
    }
    const Handle(Geom2d_BSplineCurve) whole = Handle(Geom2d_BSplineCurve)::DownCast(curve2d);
    if (whole.IsNull()) {
        return {};
    }
    const Handle(Geom2d_BSplineCurve) own = Handle(Geom2d_BSplineCurve)::DownCast(whole->Copy());
    own->Segment(first, last);
    return own;
}

/// The largest distance of an edge's stored 2D curve on a face from its 3D curve, at the same
/// parameter; -1 where it has none stored
double gapOnFace(const TopoDS_Edge& edge, const TopoDS_Face& face)
{
    double first = 0.0;
    double last = 0.0;
    const Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);
    bool stored = false;
    double first2d = 0.0;
    double last2d = 0.0;
    const Handle(Geom2d_Curve) curve2d
        = BRep_Tool::CurveOnSurface(edge, face, first2d, last2d, &stored);
    if (curve2d.IsNull() || !stored) {
        return -1.0;
    }
    const Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    double gap = 0.0;
    for (int index = 0; index <= 40; ++index) {
        const double at = index / 40.0;
        const gp_Pnt2d uv = curve2d->Value(first2d + (last2d - first2d) * at);
        const gp_Pnt on3d = curve->Value(first + (last - first) * at);
        gap = std::max(gap, surface->Value(uv.X(), uv.Y()).Distance(on3d));
    }
    return gap;
}

}  // namespace

TEST(RefineFuseEdgesTest, testARoundsCutEdgeInTwoSpansFusesOntoItsFaces)
{
    // which: -1 the spans as the imprint leaves them (both on the whole cut edge's 2D curve: the
    // control, right without the check too); 0 or 1: that span gets a 2D curve of its own on the
    // ball's face, the other stays on a part of the whole one (the wrong join for one of the two)
    for (int which : {-1, 0, 1}) {
        SCOPED_TRACE(which);
        // Arrange
        const TopoDS_Shape solid = roundCutByABall();
        ASSERT_FALSE(solid.IsNull());
        const RoundEnd before = roundEndOf(solid);
        ASSERT_EQ(before.round.size(), 2U);
        ASSERT_EQ(before.spans.size(), 2U);
        if (which >= 0) {
            const TopoDS_Edge& span = before.spans[which];
            const Handle(Geom2d_BSplineCurve) own = ownCurveOnBall(span, before.ball);
            ASSERT_FALSE(own.IsNull());
            BRep_Builder().UpdateEdge(span, own, before.ball, BRep_Tool::Tolerance(span));
        }
        ASSERT_TRUE(BRepCheck_Analyzer(solid).IsValid());
        const double tolerance = worstTolerance(solid);
        const double allowed = 10.0 * std::max(tolerance, 1e-6);
        for (const TopoDS_Edge& span : before.spans) {
            ASSERT_GE(gapOnFace(span, before.ball), 0.0);  // stored
            ASSERT_LE(gapOnFace(span, before.ball), tolerance);
        }
        const double ballArea = areaOf(before.ball);
        const double volume = volumeOf(solid);

        // Act
        const TopoDS_Shape refined = refine(solid);

        // Assert: one round face, the cut edge one edge on its 3D curve, nothing grown
        EXPECT_TRUE(BRepCheck_Analyzer(refined).IsValid());
        EXPECT_LE(worstTolerance(refined), allowed);
        EXPECT_LE(worstTolerance(solid), allowed);
        const RoundEnd end = roundEndOf(refined);
        EXPECT_EQ(end.round.size(), 1U);
        ASSERT_EQ(end.spans.size(), 1U);
        EXPECT_LE(gapOnFace(end.spans[0], end.ball), allowed);
        // to 1e-3: the merged round's new 2D curves move the numbers by 2e-5, with or without
        // the check; the wrong join moves the ball's face by 2.7 mm2 or more
        EXPECT_NEAR(areaOf(end.ball), ballArea, 1e-3);
        EXPECT_NEAR(volumeOf(refined), volume, 1e-3);
    }
}

TEST(RefineFuseEdgesTest, testARoundsCutEdgeOnTwoCurvesStaysTwoEdges)
{
    // Arrange: the second span on a 3D curve of its own (the same points, its own poles), as a
    // round's end built from two tools has them
    const TopoDS_Shape solid = roundCutByABall();
    ASSERT_FALSE(solid.IsNull());
    const RoundEnd before = roundEndOf(solid);
    ASSERT_EQ(before.round.size(), 2U);
    ASSERT_EQ(before.spans.size(), 2U);
    double first = 0.0;
    double last = 0.0;
    Handle(Geom_Curve) curve = BRep_Tool::Curve(before.spans[1], first, last);
    if (const auto trimmed = Handle(Geom_TrimmedCurve)::DownCast(curve); !trimmed.IsNull()) {
        curve = trimmed->BasisCurve();
    }
    const Handle(Geom_BSplineCurve) own = Handle(Geom_BSplineCurve)::DownCast(curve->Copy());
    ASSERT_FALSE(own.IsNull());
    own->Segment(first, last);
    BRep_Builder().UpdateEdge(before.spans[1], own, BRep_Tool::Tolerance(before.spans[1]));
    ASSERT_TRUE(BRepCheck_Analyzer(solid).IsValid());
    const double tolerance = worstTolerance(solid);
    const double ballArea = areaOf(before.ball);
    const double volume = volumeOf(solid);

    // Act
    const TopoDS_Shape refined = refine(solid);

    // Assert: the round is one face, the two spans are left as they were
    EXPECT_TRUE(BRepCheck_Analyzer(refined).IsValid());
    EXPECT_LE(worstTolerance(refined), 10.0 * std::max(tolerance, 1e-6));
    const RoundEnd end = roundEndOf(refined);
    EXPECT_EQ(end.round.size(), 1U);
    EXPECT_EQ(end.spans.size(), 2U);
    for (const TopoDS_Edge& span : end.spans) {
        EXPECT_LE(gapOnFace(span, end.ball), 10.0 * std::max(tolerance, 1e-6));
    }
    EXPECT_NEAR(areaOf(end.ball), ballArea, 1e-3);
    EXPECT_NEAR(volumeOf(refined), volume, 1e-3);
}
