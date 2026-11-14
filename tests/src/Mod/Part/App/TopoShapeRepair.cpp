// SPDX-License-Identifier: LGPL-2.1-or-later

// What checkDressUp() never drops from a repair: faces outside its solids that enclose a volume
// (ops#297). Designed shapes only.

#include <gtest/gtest.h>

#include <cmath>
#include <numbers>
#include <sstream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include "src/App/InitApplication.h"
#include <App/Application.h>
#include <Base/Parameter.h>
#include <Mod/Part/App/MassProperties.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeOpCode.h>
#include <Mod/Part/App/TopoShapeRepair.h>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRep_Builder.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepTools.hxx>
#include <Geom2d_Curve.hxx>
#include <ShapeFix_ShapeTolerance.hxx>
#include <ShapeUpgrade_RemoveLocations.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <gp_Circ.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Lin.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRep_Tool.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <gp.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>

namespace
{

// A square face in the plane z = 0, open on its own
TopoDS_Face square(double x)
{
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(x, 0, 0),
        gp_Pnt(x + 10, 0, 0),
        gp_Pnt(x + 10, 10, 0),
        gp_Pnt(x, 10, 0),
        true
    );
    return BRepBuilderAPI_MakeFace(polygon.Wire()).Face();
}

TopoDS_Shape box(double x)
{
    return BRepPrimAPI_MakeBox(gp_Pnt(x, 0, 0), 10, 10, 10).Shape();
}

TopoDS_Shape shellOf(const TopoDS_Shape& solid)
{
    return TopExp_Explorer(solid, TopAbs_SHELL).Current();
}

TopoDS_Compound compound(std::initializer_list<TopoDS_Shape> shapes)
{
    TopoDS_Compound res;
    BRep_Builder builder;
    builder.MakeCompound(res);
    for (const auto& shape : shapes) {
        builder.Add(res, shape);
    }
    return res;
}

}  // namespace

TEST(TopoShapeRepair, solidAloneEnclosesNothingOutside)
{
    EXPECT_FALSE(Part::enclosesOutsideSolids(box(0)));
    EXPECT_FALSE(Part::enclosesOutsideSolids(compound({box(0), box(20)})));
}

TEST(TopoShapeRepair, openFaceBesideTheSolidEnclosesNothing)
{
    // The fin, moved out of the solid by ShapeFix
    EXPECT_FALSE(Part::enclosesOutsideSolids(compound({box(0), square(20)})));
    // An open shell of five faces of a box
    TopoDS_Compound fiveFaces;
    BRep_Builder builder;
    builder.MakeCompound(fiveFaces);
    TopExp_Explorer it(box(20), TopAbs_FACE);
    for (it.Next(); it.More(); it.Next()) {
        builder.Add(fiveFaces, it.Current());
    }
    EXPECT_FALSE(Part::enclosesOutsideSolids(compound({box(0), fiveFaces})));
}

TEST(TopoShapeRepair, closedShellBesideAnOpenFaceEncloses)
{
    // Taken together the faces outside have the open face's free edges; the shell alone is closed
    EXPECT_TRUE(Part::enclosesOutsideSolids(compound({box(0), shellOf(box(20)), square(40)})));
    EXPECT_TRUE(Part::enclosesOutsideSolids(compound({box(0), square(40), shellOf(box(20))})));
}

TEST(TopoShapeRepair, closedFacesBesideAnOpenFaceEnclose)
{
    // A box's six faces outside any shell, and a sphere's single face
    TopoDS_Compound sixFaces;
    BRep_Builder builder;
    builder.MakeCompound(sixFaces);
    for (TopExp_Explorer it(box(20), TopAbs_FACE); it.More(); it.Next()) {
        builder.Add(sixFaces, it.Current());
    }
    EXPECT_TRUE(Part::enclosesOutsideSolids(compound({box(0), sixFaces, square(40)})));
    const auto sphere = BRepPrimAPI_MakeSphere(gp_Pnt(60, 0, 0), 5).Shape();
    const auto sphereFace = TopExp_Explorer(sphere, TopAbs_FACE).Current();
    EXPECT_TRUE(Part::enclosesOutsideSolids(compound({box(0), sphereFace, square(40)})));
}

class CheckDressUpTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
};

TEST_F(CheckDressUpTest, internalFacesOfAValidResultOnAnInvalidBaseStay)
{
    // A box holding a square inside it on purpose, in a shell oriented INTERNAL: an open shell
    // that is no defect. On an invalid base (a vertex 0.01 off its edges) the valid result is
    // kept as it is; the repair would drop the square with the shell (PR 314 review, item 5)
    gp_Trsf halfway;
    halfway.SetTranslation(gp_Vec(0, 0, 5));
    TopoDS_Shape inside = BRepBuilderAPI_Transform(square(0), halfway, true).Shape();
    BRep_Builder builder;
    TopoDS_Shell internal;
    builder.MakeShell(internal);
    builder.Add(internal, inside);
    internal.Orientation(TopAbs_INTERNAL);
    TopoDS_Solid solid;
    builder.MakeSolid(solid);
    builder.Add(solid, shellOf(box(0)));
    builder.Add(solid, internal);
    Part::TopoShape result(solid, 1L);
    ASSERT_TRUE(result.isValid());
    ASSERT_EQ(result.countSubShapes(TopAbs_FACE), 7U);

    TopoDS_Shape base = box(0);
    TopoDS_Vertex corner = TopoDS::Vertex(TopExp_Explorer(base, TopAbs_VERTEX).Current());
    gp_Pnt off = BRep_Tool::Pnt(corner).Translated(gp_Vec(0.01, 0, 0));
    builder.UpdateVertex(corner, off, 1e-7);
    Part::TopoShape invalidBase(base, 1L);
    ASSERT_FALSE(invalidBase.isValid());

    EXPECT_TRUE(Part::checkDressUp(result, invalidBase));
    EXPECT_EQ(result.countSubShapes(TopAbs_FACE), 7U);
    EXPECT_EQ(result.countSubShapes(TopAbs_SHELL), 2U);
}

TEST_F(CheckDressUpTest, aChangedVoidBesideAVoidRemovedWithItsMaterialStays)
{
    // The base: the 10 mm box with a 2 mm void A and a 4 x 0.5 x 0.5 void B under its front top
    // edge. The result, made by Booleans: the box less the wedge z > 7 + y (a chamfer of 3, which
    // removes B), with A 0.5 lower, as if the dress-up had rounded A's top edges. A is changed,
    // not lost, and holds material of the result where it was; only the lost B is checked, and
    // its space holds none (PR 341 review)
    const auto cut = [](const TopoDS_Shape& a, const TopoDS_Shape& b) {
        return BRepAlgoAPI_Cut(a, b).Shape();
    };
    const TopoDS_Shape voidA = BRepPrimAPI_MakeBox(gp_Pnt(4, 4, 2), 2, 2, 2).Shape();
    const TopoDS_Shape voidB = BRepPrimAPI_MakeBox(gp_Pnt(3, 0.2, 9.3), 4, 0.5, 0.5).Shape();
    Part::TopoShape base(cut(cut(box(0), voidA), voidB), 1L);
    BRepBuilderAPI_MakePolygon
        triangle(gp_Pnt(-1, -1, 6), gp_Pnt(-1, 4, 11), gp_Pnt(-1, -1, 11), true);
    const TopoDS_Shape wedge
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(triangle.Wire()).Face(), gp_Vec(12, 0, 0))
              .Shape();
    const TopoDS_Shape lowerA = BRepPrimAPI_MakeBox(gp_Pnt(4, 4, 2), 2, 2, 1.5).Shape();
    Part::TopoShape result(cut(cut(box(0), wedge), lowerA), 1L);
    ASSERT_TRUE(result.isValid());
    ASSERT_EQ(base.countSubShapes(TopAbs_SHELL), 3U);
    ASSERT_EQ(result.countSubShapes(TopAbs_SHELL), 2U);

    EXPECT_TRUE(Part::checkDressUp(result, base));
    EXPECT_EQ(result.countSubShapes(TopAbs_SHELL), 2U);
}

// A block 20 mm with a blind pocket 10 x 1.5 x 15 open at the top (x 5..15, y 5..6.5, floor
// z 5), and the floor's concave edge along the wall y 5: a round of 2 on it is wider than the
// floor, so its strip runs onto the opposite wall y 6.5. Returns the base and that edge
std::pair<Part::TopoShape, Part::TopoShape> narrowPocket()
{
    const TopoDS_Shape block = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 20, 20, 20).Shape();
    const TopoDS_Shape pocket = BRepPrimAPI_MakeBox(gp_Pnt(5, 5, 5), 10, 1.5, 15).Shape();
    const TopoDS_Shape base = BRepAlgoAPI_Cut(block, pocket).Shape();
    TopoDS_Shape edge;
    for (TopExp_Explorer it(base, TopAbs_EDGE); it.More(); it.Next()) {
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopExp::Vertices(TopoDS::Edge(it.Current()), first, last);
        const gp_Pnt a = BRep_Tool::Pnt(first);
        const gp_Pnt b = BRep_Tool::Pnt(last);
        if (std::abs(a.Y() - 5) < 1e-9 && std::abs(b.Y() - 5) < 1e-9 && std::abs(a.Z() - 5) < 1e-9
            && std::abs(b.Z() - 5) < 1e-9 && std::abs(std::abs(a.X() - b.X()) - 10) < 1e-9) {
            edge = it.Current();
        }
    }
    return {Part::TopoShape(base, 1L), Part::TopoShape(edge)};
}

TEST_F(CheckDressUpTest, aRoundClippedByTheOppositeWallFillsNothing)
{
    // The round of 2 as Onshape clips it by the wall its strip reaches (ops#640, Case Base #46):
    // the corner y 5..6.5, z 5..7 less the round's cylinder. It lies on the opposite wall, beside
    // the floor across a concave edge, within the round's reach: no recess is filled. Without the
    // size, the check can't bound it and refuses it
    const auto [base, edge] = narrowPocket();
    ASSERT_FALSE(edge.isNull());
    const TopoDS_Shape corner = BRepPrimAPI_MakeBox(gp_Pnt(5, 5, 5), 10, 1.5, 2).Shape();
    const TopoDS_Shape cylinder
        = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(4, 7, 7), gp::DX()), 2, 12).Shape();
    const TopoDS_Shape round = BRepAlgoAPI_Cut(corner, cylinder).Shape();
    Part::TopoShape result(BRepAlgoAPI_Fuse(base.getShape(), round).Shape(), 1L);
    ASSERT_TRUE(result.isValid());

    EXPECT_EQ(Part::filledPocket(result, base, {edge}, 2.0), "");
    EXPECT_NE(Part::filledPocket(result, base, {edge}), "");
}

TEST_F(CheckDressUpTest, aBlindPocketFilledWholeFillsARecess)
{
    // The same pocket filled whole up to its top, as OCCT fills a recess whose opening it covers
    // (ops#393): the fill lies on the opposite wall beside the floor too, but reaches 15 up it,
    // past the round's reach (PR review r2 of the clip, the blind pocket)
    const auto [base, edge] = narrowPocket();
    ASSERT_FALSE(edge.isNull());
    const TopoDS_Shape fill = BRepPrimAPI_MakeBox(gp_Pnt(5, 5, 5), 10, 1.5, 15).Shape();
    Part::TopoShape result(BRepAlgoAPI_Fuse(base.getShape(), fill).Shape(), 1L);
    ASSERT_TRUE(result.isValid());

    const std::string why = Part::filledPocket(result, base, {edge}, 2.0);
    EXPECT_EQ(why.rfind("fills a recess of the base next to Edge", 0), 0U) << why;
}
// ---------------------------------------------------------------------------------------------
// healSliverCorners(): the corners a Boolean leaves open beside a sliver (ops#640, FSLC rb50/51).
// Designed shapes only: a wheel in the proportions of FSLC's grip ring, whose closed form is its
// outline's arcs.

namespace
{

constexpr double wheelRoot = 82.345905;
constexpr double wheelFlank = 0.4;
constexpr double wheelHalf = 0.068 * std::numbers::pi / 180;
constexpr double wheelPitch = 2 * std::numbers::pi / 229;

gp_Pnt wheelAt(double radius, double angle, double z = 0.0)
{
    return gp_Pnt(radius * std::cos(angle), radius * std::sin(angle), z);
}

double wheelReach()
{
    return 2 * std::asin(wheelFlank / 2 / wheelRoot);
}

/// The wheel of the fillet's gtest (gripWheel() in FilletFallback.cpp): a prism of an outline of
/// arcs, root R 82.345905, and per grip two flanks of radius 0.4 centred on the root circle under
/// a tip arc. With a slip, each root corner's vertex stands on the root circle that far beyond the
/// flank's circle, with the tolerance: the root arc ends at the vertex, the flank arc beside it,
/// and the prism's vertical edge stands the slip off the flank's cylinder, as a pad's fuse leaves
/// FSLC's grips
TopoDS_Shape slippedWheel(int grips, double height, double slip, double tolerance)
{
    auto corner = [tolerance](const gp_Pnt& point) {
        TopoDS_Vertex vertex;
        BRep_Builder().MakeVertex(vertex, point, tolerance);
        return vertex;
    };
    auto arc = [](const gp_Pnt& centre,
                  double radius,
                  const TopoDS_Vertex& from,
                  const TopoDS_Vertex& to) {
        return BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(centre, gp::DZ()), radius), from, to).Edge();
    };
    const double reach = wheelReach();
    const double turned = slip / wheelRoot;
    const TopoDS_Vertex first = corner(wheelAt(wheelRoot, -wheelHalf - reach - turned));
    TopoDS_Vertex foot = first;
    BRepBuilderAPI_MakeWire wire;
    for (int k = 0; k < grips; ++k) {
        const double a = k * wheelPitch;
        const TopoDS_Vertex rise = corner(wheelAt(wheelRoot + wheelFlank, a - wheelHalf));
        const TopoDS_Vertex fall = corner(wheelAt(wheelRoot + wheelFlank, a + wheelHalf));
        const TopoDS_Vertex land = corner(wheelAt(wheelRoot, a + wheelHalf + reach + turned));
        const TopoDS_Vertex next = k + 1 == grips
            ? first
            : corner(wheelAt(wheelRoot, a + wheelPitch - wheelHalf - reach - turned));
        wire.Add(arc(wheelAt(wheelRoot, a - wheelHalf), wheelFlank, foot, rise));
        wire.Add(arc(gp_Pnt(), wheelRoot + wheelFlank, rise, fall));
        wire.Add(arc(wheelAt(wheelRoot, a + wheelHalf), wheelFlank, fall, land));
        wire.Add(arc(gp_Pnt(), wheelRoot, land, next));
        foot = next;
    }
    const TopoDS_Face face = BRepBuilderAPI_MakeFace(wire.Wire()).Face();
    // Without locations: a sweep uses one vertex and one arc for the bottom and the top
    ShapeUpgrade_RemoveLocations unshared;
    unshared.Remove(BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, height)).Shape());
    return unshared.GetResult();
}

/// Twice the area an arc sweeps about the origin, counter-clockwise from one point to the other
double sweptTwice(const gp_Pnt& centre, double radius, const gp_Pnt& from, const gp_Pnt& to)
{
    double turn = std::atan2(to.Y() - centre.Y(), to.X() - centre.X())
        - std::atan2(from.Y() - centre.Y(), from.X() - centre.X());
    while (turn <= 0) {
        turn += 2 * std::numbers::pi;
    }
    return radius * radius * turn + centre.X() * (to.Y() - from.Y())
        - centre.Y() * (to.X() - from.X());
}

/// The wheel's outline's area in closed form: its arcs between the corners where their circles
/// cross
double wheelArea(int grips)
{
    const double reach = wheelReach();
    double twice = 0.0;
    for (int k = 0; k < grips; ++k) {
        const double a = k * wheelPitch;
        const gp_Pnt foot = wheelAt(wheelRoot, a - wheelHalf - reach);
        const gp_Pnt rise = wheelAt(wheelRoot + wheelFlank, a - wheelHalf);
        const gp_Pnt fall = wheelAt(wheelRoot + wheelFlank, a + wheelHalf);
        const gp_Pnt land = wheelAt(wheelRoot, a + wheelHalf + reach);
        const gp_Pnt next = wheelAt(
            wheelRoot,
            (k + 1 == grips ? 0.0 : a + wheelPitch) - wheelHalf - reach
        );
        twice += sweptTwice(wheelAt(wheelRoot, a - wheelHalf), wheelFlank, foot, rise);
        twice += sweptTwice(gp_Pnt(), wheelRoot + wheelFlank, rise, fall);
        twice += sweptTwice(wheelAt(wheelRoot, a + wheelHalf), wheelFlank, fall, land);
        twice += sweptTwice(gp_Pnt(), wheelRoot, land, next);
    }
    return twice / 2;
}

TopoDS_Face faceAtHeight(const TopoDS_Shape& shape, double height)
{
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        BRepAdaptor_Surface surface(TopoDS::Face(it.Current()));
        if (surface.GetType() == GeomAbs_Plane
            && std::abs(surface.Plane().Location().Z() - height) < 1e-9) {
            return TopoDS::Face(it.Current());
        }
    }
    return {};
}

/// The area the face's edges bound, as OCCT's measures read it: along each edge's circle between
/// its range's ends (exact for arcs; a gap between two edges' ends is left out)
double areaAlongEdges(const TopoDS_Face& face)
{
    double twice = 0.0;
    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge edge = TopoDS::Edge(it.Current());
        BRepAdaptor_Curve curve(edge);
        if (curve.GetType() != GeomAbs_Circle) {
            ADD_FAILURE() << "an edge that is no arc";
            return 0.0;
        }
        const gp_Circ circle = curve.Circle();
        const gp_Pnt from = curve.Value(curve.FirstParameter());
        const gp_Pnt to = curve.Value(curve.LastParameter());
        const double swept = sweptTwice(circle.Location(), circle.Radius(), from, to);
        twice += edge.Orientation() == TopAbs_REVERSED ? -swept : swept;
    }
    return std::abs(twice) / 2;
}

/// The farthest any edge's end stands from its vertex, in space and on each of its faces (of
/// one kind of surface, if given)
double widestGap(const TopoDS_Shape& shape, GeomAbs_SurfaceType only = GeomAbs_OtherSurface)
{
    double widest = 0.0;
    for (TopExp_Explorer faces(shape, TopAbs_FACE); faces.More(); faces.Next()) {
        const TopoDS_Face face = TopoDS::Face(faces.Current());
        BRepAdaptor_Surface surface(face, false);
        if (only != GeomAbs_OtherSurface && surface.GetType() != only) {
            continue;
        }
        for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
            const TopoDS_Edge edge = TopoDS::Edge(it.Current().Oriented(TopAbs_FORWARD));
            if (BRep_Tool::Degenerated(edge)) {
                continue;
            }
            TopoDS_Vertex from;
            TopoDS_Vertex to;
            TopExp::Vertices(edge, from, to);
            BRepAdaptor_Curve curve(edge);
            double first = 0.0;
            double last = 0.0;
            const Handle(Geom2d_Curve) onFace = BRep_Tool::CurveOnSurface(edge, face, first, last);
            const gp_Pnt2d uvFrom = onFace->Value(first);
            const gp_Pnt2d uvTo = onFace->Value(last);
            for (const auto& [vertex, inSpace, uv] :
                 {std::make_tuple(from, curve.Value(curve.FirstParameter()), uvFrom),
                  std::make_tuple(to, curve.Value(curve.LastParameter()), uvTo)}) {
                const gp_Pnt point = BRep_Tool::Pnt(vertex);
                widest = std::max(widest, point.Distance(inSpace));
                widest = std::max(widest, point.Distance(surface.Value(uv.X(), uv.Y())));
            }
        }
    }
    return widest;
}

/// The farthest a straight edge between two cylinders stands from either
double widestStandOff(const TopoDS_Shape& shape)
{
    TopTools_IndexedDataMapOfShapeListOfShape facesOf;
    TopExp::MapShapesAndUniqueAncestors(shape, TopAbs_EDGE, TopAbs_FACE, facesOf);
    double widest = 0.0;
    for (int i = 1; i <= facesOf.Extent(); ++i) {
        BRepAdaptor_Curve curve(TopoDS::Edge(facesOf.FindKey(i)));
        if (curve.GetType() != GeomAbs_Line) {
            continue;
        }
        const gp_Pnt point = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
        for (const auto& face : facesOf(i)) {
            BRepAdaptor_Surface surface(TopoDS::Face(face), false);
            if (surface.GetType() == GeomAbs_Cylinder) {
                const gp_Cylinder cylinder = surface.Cylinder();
                widest = std::max(
                    widest,
                    std::abs(gp_Lin(cylinder.Axis()).Distance(point) - cylinder.Radius())
                );
            }
        }
    }
    return widest;
}

std::string written(const TopoDS_Shape& shape)
{
    std::ostringstream out;
    BRepTools::Write(shape, out);
    return out.str();
}

}  // namespace

class SliverCornersTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    static constexpr int grips = 4;
    static constexpr double height = 3.0;
    static constexpr double slip = 1.2e-6;
    static constexpr double tolerance = 1.3e-6;
};

TEST_F(SliverCornersTest, aSlippedCornerIsClosedAtItsCirclesCrossing)
{
    const TopoDS_Shape wheel = slippedWheel(grips, height, slip, tolerance);
    ASSERT_TRUE(BRepCheck_Analyzer(wheel).IsValid());
    const double area = wheelArea(grips);

    // As built: each of the 8 root corners is open by the slip, on both rims, and its vertical
    // edge stands the slip off the flank's cylinder. Along its edges the top face is short of the
    // outline by half the root radius times the slip at each corner
    EXPECT_GT(widestGap(wheel), 0.9 * slip);
    EXPECT_GT(widestStandOff(wheel), 0.9 * slip);
    const double shortBy = area - areaAlongEdges(faceAtHeight(wheel, height));
    EXPECT_NEAR(shortBy, 2 * grips * wheelRoot * slip / 2, 0.1 * 2 * grips * wheelRoot * slip / 2);

    const Part::SliverHeal heal = Part::healSliverCorners(wheel, {});
    EXPECT_FALSE(heal.undone);
    EXPECT_EQ(heal.edges, 2 * grips);          // each root corner's vertical edge
    EXPECT_EQ(heal.vertices, 2 * 2 * grips);   // its vertex on each rim
    EXPECT_TRUE(BRepCheck_Analyzer(wheel).IsValid());

    // Healed: no edge end further than 1e-7 from its vertex, no vertical edge off its cylinders,
    // the vertices at the corners in closed form, and the area and volume at the closed form
    EXPECT_LT(widestGap(wheel), 1e-7);
    EXPECT_LT(widestStandOff(wheel), 1e-9);
    for (double z : {0.0, height}) {
        EXPECT_NEAR(areaAlongEdges(faceAtHeight(wheel, z)), area, 1e-9);
    }
    const double reach = wheelReach();
    for (int k = 0; k < grips; ++k) {
        for (double side : {-1.0, 1.0}) {
            const gp_Pnt corner
                = wheelAt(wheelRoot, k * wheelPitch + side * (wheelHalf + reach), height);
            double nearest = 1.0;
            double itsTolerance = 0.0;
            for (TopExp_Explorer it(wheel, TopAbs_VERTEX); it.More(); it.Next()) {
                const TopoDS_Vertex vertex = TopoDS::Vertex(it.Current());
                const double away = BRep_Tool::Pnt(vertex).Distance(corner);
                if (away < nearest) {
                    nearest = away;
                    itsTolerance = BRep_Tool::Tolerance(vertex);
                }
            }
            EXPECT_LT(nearest, 1e-9);
            EXPECT_LE(itsTolerance, 1.01e-7);  // down to what its edges need
        }
    }
    EXPECT_NEAR(Part::MassProperties::area(faceAtHeight(wheel, height), true), area, 1e-6);
    EXPECT_NEAR(Part::MassProperties::volume(wheel, true), area * height, 1e-5);
}

TEST_F(SliverCornersTest, aGapWiderThanItsToleranceIsNotClosed)
{
    // Must-fail control: the same wheel, one corner's vertical edge and its vertices claiming
    // 1e-7. That corner is beyond its tolerance: the shape was invalid there before, the heal
    // doesn't read it, and the faces it shares with its neighbours still fail the check. So
    // nothing is closed silently: the whole heal is undone
    const TopoDS_Shape wheel = slippedWheel(grips, height, slip, tolerance);
    TopoDS_Edge claimed;
    for (TopExp_Explorer it(wheel, TopAbs_EDGE); it.More() && claimed.IsNull(); it.Next()) {
        BRepAdaptor_Curve curve(TopoDS::Edge(it.Current()));
        if (curve.GetType() == GeomAbs_Line) {
            claimed = TopoDS::Edge(it.Current());
        }
    }
    ASSERT_FALSE(claimed.IsNull());
    ShapeFix_ShapeTolerance().SetTolerance(claimed, 1e-7);
    ASSERT_FALSE(BRepCheck_Analyzer(wheel).IsValid());
    const std::string before = written(wheel);

    const Part::SliverHeal heal = Part::healSliverCorners(wheel, {});
    EXPECT_TRUE(heal.undone);
    EXPECT_EQ(heal.edges, 0);
    EXPECT_EQ(heal.vertices, 0);
    EXPECT_EQ(written(wheel), before);
    EXPECT_GT(widestGap(wheel), 0.9 * slip);
    EXPECT_GT(widestStandOff(wheel), 0.9 * slip);
}

TEST_F(SliverCornersTest, aSubShapeUsedAtTwoPlacesStays)
{
    // A sweep's prism uses one vertex and one arc for its bottom and its top, under two
    // locations: a change to one would change the other, so neither is changed
    auto corner = [](const gp_Pnt& point) {
        TopoDS_Vertex vertex;
        BRep_Builder().MakeVertex(vertex, point, tolerance);
        return vertex;
    };
    // a quarter disc whose arc's first vertex stands the slip beyond the arc's end on the x axis
    const double radius = 10.0;
    const TopoDS_Vertex centre = corner(gp_Pnt());
    const TopoDS_Vertex onX = corner(gp_Pnt(radius + slip, 0, 0));
    const TopoDS_Vertex onY = corner(gp_Pnt(0, radius, 0));
    BRepBuilderAPI_MakeWire wire;
    wire.Add(BRepBuilderAPI_MakeEdge(centre, onX).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Circ(gp::XOY(), radius), onX, onY).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(onY, centre).Edge());
    const TopoDS_Shape swept
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(wire.Wire()).Face(), gp_Vec(0, 0, height))
              .Shape();
    ASSERT_GT(widestStandOff(swept), 0.9 * slip);
    ShapeFix_ShapeTolerance().SetTolerance(swept, tolerance);  // every edge may move, by its tolerance
    const std::string before = written(swept);
    const Part::SliverHeal heal = Part::healSliverCorners(swept, {});
    EXPECT_EQ(heal.vertices, 0);
    EXPECT_FALSE(heal.undone);
    EXPECT_GT(widestGap(swept), 0.9 * slip);
    // its wall edge is its own, and moves onto the cylinder; the shared vertices and arcs stay
    EXPECT_EQ(heal.edges, 1);
    EXPECT_LT(widestStandOff(swept), 1e-9);
    EXPECT_NE(written(swept), before);
    EXPECT_TRUE(BRepCheck_Analyzer(swept).IsValid());
}

TEST_F(SliverCornersTest, aSlipBeyondEveryToleranceStaysOpen)
{
    // Must-fail control: vertices and edges that claim 1e-7 over a slip of 1.2e-6
    const TopoDS_Shape wheel = slippedWheel(grips, height, slip, tolerance);
    ShapeFix_ShapeTolerance().SetTolerance(wheel, 1e-7);
    const std::string before = written(wheel);
    const Part::SliverHeal heal = Part::healSliverCorners(wheel, {});
    EXPECT_EQ(heal.edges, 0);
    EXPECT_EQ(heal.vertices, 0);
    EXPECT_EQ(written(wheel), before);
}

TEST_F(SliverCornersTest, aCleanShapeIsLeftBitForBit)
{
    const TopoDS_Shape wheel = slippedWheel(grips, height, 0.0, 1e-7);
    const std::string before = written(wheel);
    const Part::SliverHeal heal = Part::healSliverCorners(wheel, {});
    EXPECT_EQ(heal.edges, 0);
    EXPECT_EQ(heal.vertices, 0);
    EXPECT_FALSE(heal.undone);
    EXPECT_EQ(written(wheel), before);
}

TEST_F(SliverCornersTest, anInputsOwnGapStays)
{
    // The Boolean reuses the inputs' untouched edges and vertices: what is also in an input is
    // never changed
    const TopoDS_Shape wheel = slippedWheel(grips, height, slip, tolerance);
    const std::string before = written(wheel);
    const Part::SliverHeal heal = Part::healSliverCorners(wheel, {Part::TopoShape(wheel)});
    EXPECT_EQ(heal.edges, 0);
    EXPECT_EQ(heal.vertices, 0);
    EXPECT_EQ(written(wheel), before);
}

TEST_F(SliverCornersTest, aHealThatFailsTheCheckIsUndoneWhole)
{
    // The check's verdict stood in for: with a "no", every range, curve, point and tolerance is
    // put back, and the shape is the Boolean's bit for bit
    const TopoDS_Shape wheel = slippedWheel(grips, height, slip, tolerance);
    const std::string before = written(wheel);
    int faces = 0;
    const Part::SliverHeal heal
        = Part::healSliverCorners(wheel, {}, [&faces](const TopoDS_Shape& touched) {
              for (TopExp_Explorer it(touched, TopAbs_FACE); it.More(); it.Next()) {
                  ++faces;
              }
              return false;
          });
    EXPECT_TRUE(heal.undone);
    EXPECT_EQ(heal.edges, 0);
    EXPECT_EQ(heal.vertices, 0);
    EXPECT_GT(faces, 0);
    EXPECT_EQ(written(wheel), before);
    EXPECT_GT(widestGap(wheel), 0.9 * slip);
}

namespace
{

/// A grip cell as FSLC's sketch has it (gap.py of mitre 4): its base arc on the root circle, at
/// each foot a radial line `dip` long inwards, and the flank arc from the line's inner end, so
/// that the flank's circle crosses the root circle a hair beside the line: the sliver
TopoDS_Shape gripCell(int k, double cellHeight, double dip, double gap)
{
    const double a = k * wheelPitch;
    const double reach = wheelReach();
    auto inner = [dip](double centreAngle, double side) {
        const double rho = wheelRoot - dip;
        const double x = (wheelRoot * wheelRoot + rho * rho - wheelFlank * wheelFlank)
            / (2 * wheelRoot);
        const double up = std::sqrt(rho * rho - x * x);
        const gp_Vec u(std::cos(centreAngle), std::sin(centreAngle), 0);
        const gp_Vec t(-u.Y(), u.X(), 0);
        return gp_Pnt((u * x + t * (side * up)).XYZ());
    };
    const gp_Pnt c1 = wheelAt(wheelRoot, a - wheelHalf);
    const gp_Pnt c2 = wheelAt(wheelRoot, a + wheelHalf);
    const gp_Pnt s1 = inner(a - wheelHalf, -1);
    const gp_Pnt s2 = inner(a + wheelHalf, 1);
    const gp_Pnt l1 = wheelAt(wheelRoot, a - wheelHalf - reach + gap / wheelRoot);
    const gp_Pnt l2 = wheelAt(wheelRoot, a + wheelHalf + reach - gap / wheelRoot);
    const gp_Pnt rise = wheelAt(wheelRoot + wheelFlank, a - wheelHalf);
    const gp_Pnt fall = wheelAt(wheelRoot + wheelFlank, a + wheelHalf);
    auto arc = [](const gp_Pnt& centre, double radius, const gp_Pnt& from, const gp_Pnt& to) {
        return BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(centre, gp::DZ()), radius), from, to).Edge();
    };
    BRepBuilderAPI_MakeWire wire;
    wire.Add(arc(gp_Pnt(), wheelRoot, l1, l2));
    wire.Add(BRepBuilderAPI_MakeEdge(l2, s2).Edge());
    wire.Add(TopoDS::Edge(arc(c2, wheelFlank, fall, s2).Reversed()));   // s2 -> fall, clockwise about c2
    wire.Add(TopoDS::Edge(arc(gp_Pnt(), wheelRoot + wheelFlank, rise, fall).Reversed()));
    wire.Add(TopoDS::Edge(arc(c1, wheelFlank, s1, rise).Reversed()));
    wire.Add(BRepBuilderAPI_MakeEdge(s1, l1).Edge());
    const TopoDS_Face face = BRepBuilderAPI_MakeFace(wire.Wire()).Face();
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, cellHeight)).Shape();
}

}  // namespace

TEST_F(SliverCornersTest, aFuseThatLeavesSliverGapsIsClosedOnlyWithTheSwitchOn)
{
    // A disc fused with four grip cells, as FSLC's pad fuses its 229: each cell's foot line stands
    // 1.2e-6 beside where its flank's circle crosses the root circle, and the fuse merges the two
    // into one vertex at the line's end. The closed form: the disc, and the wheel's outline
    // beyond it, times the height
    const double cellHeight = 7.55;
    const double gap = 1.2e-6;
    const double disc = std::numbers::pi * wheelRoot * wheelRoot;
    const double expected = wheelArea(grips) * cellHeight;
    ASSERT_GT(expected, disc * cellHeight);
    auto fuse = [&]() {
        std::vector<Part::TopoShape> shapes;
        shapes.emplace_back(BRepPrimAPI_MakeCylinder(wheelRoot, cellHeight).Shape());
        for (int k = 0; k < grips; ++k) {
            shapes.emplace_back(gripCell(k, cellHeight, 1e-3, gap));
            EXPECT_TRUE(BRepCheck_Analyzer(shapes.back().getShape()).IsValid());
        }
        Part::TopoShape fused;
        fused.makeElementBoolean(Part::OpCodes::Fuse, shapes, nullptr, -1.0);  // the pad's fuzzy
        return fused.getShape();
    };
    const auto group = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Part/Boolean"
    );
    struct Restore
    {
        ParameterGrp::handle group;
        ~Restore()
        {
            group->RemoveBool("HealSliverCorners");
        }
    } restore {group};

    // Off (the default; skipped where the environment switches it on for a whole run): the walls'
    // edges stand the gap off the flanks' cylinders, and the body measures short by the walls'
    // strips: 8 corners of half the root radius times the gap, over the height, two thirds of it
    group->RemoveBool("HealSliverCorners");
    if (!Part::healSliverCornersEnabled()) {
        const TopoDS_Shape open = fuse();
        EXPECT_TRUE(BRepCheck_Analyzer(open).IsValid());
        EXPECT_GT(widestStandOff(open), 0.9 * gap);
        EXPECT_GT(widestGap(open, GeomAbs_Cylinder), 0.9 * gap);
        const double strips = 2 * grips * (wheelRoot * gap / 2) * cellHeight * 2 / 3;
        EXPECT_NEAR(Part::MassProperties::volume(open, true) - expected, -strips, 0.05 * strips);
    }

    // On: every wall edge on its two cylinders, every wall and rim corner closed, the body valid
    // and at the closed form. (The sliver's own line, inside the top and bottom faces, still ends
    // at the old corner, under the vertex's tolerance: it bounds nothing)
    group->SetBool("HealSliverCorners", true);
    if (Part::healSliverCornersEnabled()) {
        const TopoDS_Shape closed = fuse();
        EXPECT_TRUE(BRepCheck_Analyzer(closed).IsValid());
        EXPECT_LT(widestStandOff(closed), 1e-9);
        EXPECT_LT(widestGap(closed, GeomAbs_Cylinder), 1e-7);
        EXPECT_NEAR(Part::MassProperties::volume(closed, true), expected, 1e-6);
        EXPECT_NEAR(Part::MassProperties::volume(closed), expected, 1e-6);
    }
}
