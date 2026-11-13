// SPDX-License-Identifier: LGPL-2.1-or-later

// Canonical faces after OCCT's fillet or chamfer (ops#640, Case Base #105; design:
// notes/canonical-faces-after-fillet.md in the ops repository). Designed models only; every
// expectation is a closed form, or OCCT's own unconverted result.

#include <cmath>
#include <iostream>
#include <numbers>
#include <string>
#include <vector>
#include <gtest/gtest.h>

#include "src/App/InitApplication.h"
#include <App/ElementNamingUtils.h>
#include <Mod/Part/App/CanonicalFaces.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_NurbsConvert.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <Geom_BSplineCurve.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>

using namespace Part;
namespace CF = Part::CanonicalFaces;

namespace
{

constexpr double pi = std::numbers::pi;
// The lens: the common part of two cylinders of radius R whose axes are 2 d apart, h high. Its two
// straight edges, at (0, +-8), lie between the two cylinders, along both
constexpr double R = 10.0;
constexpr double d = 6.0;
constexpr double h = 0.5;

double volume(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape, props);
    return props.Mass();
}

double area(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(shape, props);
    return props.Mass();
}

TopoDS_Shape cylinderAt(double x, double radius, double height)
{
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, 0, 0), gp::DZ()), radius, height).Shape();
}

TopoDS_Shape lens()
{
    return BRepAlgoAPI_Common(cylinderAt(-d, R, h), cylinderAt(d, R, h)).Shape();
}

/// Two cylinders fused: the straight edges at (0, +-8) are concave
TopoDS_Shape twoDiscs()
{
    return BRepAlgoAPI_Fuse(cylinderAt(-d, R, h), cylinderAt(d, R, h)).Shape();
}

/// The area and outline length of a lens of radius rho (axes 2 d apart)
double lensArea(double rho)
{
    const double a = std::acos(d / rho);
    return 2 * rho * rho * a - 2 * d * rho * std::sin(a);
}

double lensLength(double rho)
{
    return 4 * rho * std::acos(d / rho);
}

/// The lens with both corners rounded r: the lens opened by a disc (eroded, then dilated)
double roundedLensArea(double r)
{
    return lensArea(R - r) + r * lensLength(R - r) + pi * r * r;
}

double roundedLensLength(double r)
{
    return lensLength(R - r) + 2 * pi * r;
}

/// What a round r of one concave corner of the two fused discs adds in plan: the triangle of the
/// three centres less the two big sectors (their overlap, half the lens, counted once) and the
/// round's own sector
double concaveCornerArea(double r)
{
    const double height = std::sqrt((R + r) * (R + r) - d * d);
    const double beta = std::acos(d / (R + r));
    return d * height - (beta * R * R - lensArea(R) / 2) - (pi - 2 * beta) * r * r / 2;
}

/// The straight edges on the plane x = 0
std::vector<TopoShape> uprightEdges(const TopoShape& shape)
{
    std::vector<TopoShape> edges;
    for (const auto& edge : shape.getSubTopoShapes(TopAbs_EDGE)) {
        BRepAdaptor_Curve curve(TopoDS::Edge(edge.getShape()));
        if (curve.GetType() == GeomAbs_Line && std::abs(curve.Value(curve.FirstParameter()).X()) < 1e-6
            && std::abs(curve.Value(curve.LastParameter()).X()) < 1e-6) {
            edges.push_back(edge);
        }
    }
    return edges;
}

/// The edges that lie in the plane z = height
std::vector<TopoShape> rimEdges(const TopoShape& shape, double height)
{
    std::vector<TopoShape> edges;
    for (const auto& edge : shape.getSubTopoShapes(TopAbs_EDGE)) {
        BRepAdaptor_Curve curve(TopoDS::Edge(edge.getShape()));
        bool on = true;
        for (int i = 0; i <= 4; ++i) {
            const double t = curve.FirstParameter()
                + (curve.LastParameter() - curve.FirstParameter()) * i / 4;
            on = on && std::abs(curve.Value(t).Z() - height) < 1e-7;
        }
        if (on) {
            edges.push_back(edge);
        }
    }
    return edges;
}

int surfaces(const TopoDS_Shape& shape, GeomAbs_SurfaceType type)
{
    int n = 0;
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    for (int i = 1; i <= faces.Extent(); ++i) {
        n += BRepAdaptor_Surface(TopoDS::Face(faces(i))).GetType() == type ? 1 : 0;
    }
    return n;
}

int curves(const TopoDS_Shape& shape, GeomAbs_CurveType type)
{
    int n = 0;
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(shape, TopAbs_EDGE, edges);
    for (int i = 1; i <= edges.Extent(); ++i) {
        n += BRepAdaptor_Curve(TopoDS::Edge(edges(i))).GetType() == type ? 1 : 0;
    }
    return n;
}

/// OCCT's fillet alone, as its maker builds it
TopoDS_Shape occtFillet(const TopoShape& base, const std::vector<TopoShape>& edges, double r)
{
    BRepFilletAPI_MakeFillet maker(base.getShape());
    for (const auto& edge : edges) {
        maker.Add(r, TopoDS::Edge(edge.getShape()));
    }
    maker.Build();
    return maker.IsDone() ? maker.Shape() : TopoDS_Shape();
}

TopoShape filleted(const TopoShape& base, const std::vector<TopoShape>& edges, double r)
{
    TopoShape result(2L);
    result.makeElementFillet(base, edges, r, r);
    return result;
}

/// The largest gap of the shape's B-spline faces to the elementary surface OCCT recognises loosely
/// (-1: none recognised), printed for the design note's tolerance band
double printGaps(const char* what, const TopoDS_Shape& shape)
{
    double worst = -1.0;
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    for (int i = 1; i <= faces.Extent(); ++i) {
        const TopoDS_Face face = TopoDS::Face(faces(i));
        if (BRepAdaptor_Surface(face).GetType() != GeomAbs_BSplineSurface) {
            continue;
        }
        std::string kind = "none";
        const double gap = CF::measure(face, &kind);
        std::cout << "MEASURE " << what << ": B-spline face " << i << " area " << area(face)
                  << " nearest " << kind << " gap " << gap << std::endl;
        worst = std::max(worst, gap);
    }
    return worst;
}

std::vector<std::string> names(const TopoShape& shape, const char* type)
{
    std::vector<std::string> all;
    const int n = static_cast<int>(shape.countSubShapes(type));
    for (int i = 1; i <= n; ++i) {
        all.push_back(shape.getMappedName(Data::IndexedName::fromConst(type, i)).toString());
    }
    return all;
}

/// A plate whose front wall is wavy: the profile's front is a B-spline through points off the line
/// y = 0 by `wave` (0: straight but still a B-spline), extruded 5 along z; 20 x 10 in plan
TopoDS_Shape wavyPlate(double wave)
{
    Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, 9);
    for (int i = 1; i <= 9; ++i) {
        points->SetValue(i, gp_Pnt(2.5 * (i - 1), wave * std::sin(pi * (i - 1) / 2.0), 0));
    }
    GeomAPI_Interpolate through(points, false, 1e-9);
    through.Perform();
    BRepBuilderAPI_MakeWire wire;
    wire.Add(BRepBuilderAPI_MakeEdge(through.Curve()).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(20, 0, 0), gp_Pnt(20, 10, 0)).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(20, 10, 0), gp_Pnt(0, 10, 0)).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 10, 0), gp_Pnt(0, 0, 0)).Edge());
    TopoDS_Face face = BRepBuilderAPI_MakeFace(wire.Wire(), Standard_True).Face();
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, 5)).Shape();
}

}  // namespace

class CanonicalFacesTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
};

TEST_F(CanonicalFacesTest, aRoundBetweenTwoCylindersIsACylinder)
{
    // Case Base #104's picks: a straight edge between two cylinders along it. OCCT has no closed
    // form for the pair and returns the round as a B-spline within 1e-7 of the exact cylinder
    TopoShape base(lens(), 1L);
    const auto edges = uprightEdges(base);
    ASSERT_EQ(edges.size(), 2);
    const TopoDS_Shape occt = occtFillet(base, edges, 1.0);
    ASSERT_FALSE(occt.IsNull());
    ASSERT_EQ(surfaces(occt, GeomAbs_BSplineSurface), 2);
    const double gap = printGaps("lens r 1", occt);
    ASSERT_GE(gap, 0.0);
    ASSERT_LT(gap, CF::tolerance);

    const TopoShape result = filleted(base, edges, 1.0);
    EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
    EXPECT_EQ(surfaces(result.getShape(), GeomAbs_BSplineSurface), 0);
    EXPECT_EQ(curves(result.getShape(), GeomAbs_BSplineCurve), 0);
    EXPECT_EQ(result.countSubShapes(TopAbs_FACE), 7);
    // The two rounds: cylinders of radius 1 about (0, +-sqrt(9^2 - 6^2)), upright
    int rounds = 0;
    for (const auto& face : result.getSubTopoShapes(TopAbs_FACE)) {
        BRepAdaptor_Surface surface(TopoDS::Face(face.getShape()));
        if (surface.GetType() == GeomAbs_Cylinder && std::abs(surface.Cylinder().Radius() - 1.0) < 1e-6) {
            ++rounds;
            const gp_Ax1 axis = surface.Cylinder().Axis();
            EXPECT_NEAR(std::abs(axis.Direction().Z()), 1.0, 1e-9);
            EXPECT_NEAR(axis.Location().X(), 0.0, 1e-6);
            EXPECT_NEAR(std::abs(axis.Location().Y()), std::sqrt(81.0 - 36.0), 1e-6);
            // Its edges: two arcs of radius 1 and two lines h long
            EXPECT_EQ(curves(face.getShape(), GeomAbs_Circle), 2);
            EXPECT_EQ(curves(face.getShape(), GeomAbs_Line), 2);
        }
    }
    EXPECT_EQ(rounds, 2);
    // Closed form, and OCCT's own result within the conversion's tolerance
    EXPECT_NEAR(volume(result.getShape()), roundedLensArea(1.0) * h, 1e-6);
    EXPECT_NEAR(volume(result.getShape()), volume(occt), 1e-5);
    EXPECT_NEAR(area(result.getShape()), area(occt), 1e-5);
    EXPECT_NEAR(
        area(result.getShape()),
        2 * roundedLensArea(1.0) + roundedLensLength(1.0) * h,
        1e-6
    );
}

TEST_F(CanonicalFacesTest, aConcaveRoundBetweenTwoCylindersIsACylinder)
{
    // The same pair fused: the edges are concave, and the round adds material
    TopoShape base(twoDiscs(), 1L);
    const auto edges = uprightEdges(base);
    ASSERT_EQ(edges.size(), 2);
    const TopoDS_Shape occt = occtFillet(base, edges, 1.0);
    ASSERT_FALSE(occt.IsNull());
    ASSERT_EQ(surfaces(occt, GeomAbs_BSplineSurface), 2);
    ASSERT_LT(printGaps("two discs r 1", occt), CF::tolerance);

    const TopoShape result = filleted(base, edges, 1.0);
    EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
    EXPECT_EQ(surfaces(result.getShape(), GeomAbs_BSplineSurface), 0);
    EXPECT_EQ(curves(result.getShape(), GeomAbs_BSplineCurve), 0);
    const double plan = 2 * pi * R * R - lensArea(R) + 2 * concaveCornerArea(1.0);
    EXPECT_NEAR(volume(result.getShape()), plan * h, 1e-6);
    EXPECT_NEAR(volume(result.getShape()), volume(occt), 1e-5);
    EXPECT_NEAR(area(result.getShape()), area(occt), 1e-5);
}

TEST_F(CanonicalFacesTest, aRoundBesideMovedFacesIsACylinder)
{
    // Case Base #104's body: the faces beside the rounds are stored moved (a mirror's faces). The
    // lens turned and shifted as a located shape: its faces' surfaces are where the faces are only
    // through the location. The rounds are cylinders with arcs and lines all the same
    gp_Trsf move;
    move.SetRotation(gp_Ax1(gp_Pnt(1, 2, 3), gp_Dir(1, 1, 1)), 0.7);
    move.SetTranslationPart(gp_Vec(30, -20, 10));
    TopoShape base(lens().Moved(TopLoc_Location(move)), 1L);
    // The picks: the straight edges on the lens's plane x = 0, found where the lens was built
    std::vector<TopoShape> edges;
    for (const auto& edge : base.getSubTopoShapes(TopAbs_EDGE)) {
        BRepAdaptor_Curve curve(TopoDS::Edge(edge.getShape()));
        const gp_Pnt a = curve.Value(curve.FirstParameter()).Transformed(move.Inverted());
        const gp_Pnt b = curve.Value(curve.LastParameter()).Transformed(move.Inverted());
        if (curve.GetType() == GeomAbs_Line && std::abs(a.X()) < 1e-6 && std::abs(b.X()) < 1e-6) {
            edges.push_back(edge);
        }
    }
    ASSERT_EQ(edges.size(), 2);
    const TopoDS_Shape occt = occtFillet(base, edges, 1.0);
    ASSERT_FALSE(occt.IsNull());
    ASSERT_EQ(surfaces(occt, GeomAbs_BSplineSurface), 2);
    const TopoShape result = filleted(base, edges, 1.0);
    EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
    EXPECT_EQ(surfaces(result.getShape(), GeomAbs_BSplineSurface), 0);
    EXPECT_EQ(curves(result.getShape(), GeomAbs_BSplineCurve), 0);
    EXPECT_NEAR(volume(result.getShape()), roundedLensArea(1.0) * h, 1e-6);
    EXPECT_NEAR(area(result.getShape()), 2 * roundedLensArea(1.0) + roundedLensLength(1.0) * h, 1e-6);
}

TEST_F(CanonicalFacesTest, theNamesAreTheMakersOwn)
{
    // The conversion keeps the topology one to one and names through the maker's history: every
    // element has the name it has without the conversion
    TopoShape base(lens(), 1L);
    const auto edges = uprightEdges(base);
    ASSERT_EQ(edges.size(), 2);
    BRepFilletAPI_MakeFillet maker(base.getShape());
    for (const auto& edge : edges) {
        maker.Add(1.0, TopoDS::Edge(edge.getShape()));
    }
    maker.Build();
    ASSERT_TRUE(maker.IsDone());
    TopoShape plain(2L);
    plain.makeElementShape(maker, base, Part::OpCodes::Fillet);
    ASSERT_EQ(surfaces(plain.getShape(), GeomAbs_BSplineSurface), 2);

    const TopoShape result = filleted(base, edges, 1.0);
    ASSERT_EQ(surfaces(result.getShape(), GeomAbs_BSplineSurface), 0);
    for (const char* type : {"Face", "Edge", "Vertex"}) {
        const auto before = names(plain, type);
        const auto after = names(result, type);
        ASSERT_FALSE(before.empty());
        EXPECT_EQ(before, after) << type;
    }
}

TEST_F(CanonicalFacesTest, aRoundOverTheRoundsBuildsAtTheLimit)
{
    // Case Base #105: a round as high as the plate over the rim, whose chain runs over the ends
    // of the first rounds. OCCT refuses at the limit; the exact construction read "a selected edge
    // that is neither a line nor a circle" while those ends were B-splines
    TopoShape base(lens(), 1L);
    const TopoShape first = filleted(base, uprightEdges(base), 1.0);
    const auto rim = rimEdges(first, h);
    ASSERT_EQ(rim.size(), 5);  // the far cylinder's arc is in two, at its seam
    const TopoShape second = filleted(first, rim, h);
    EXPECT_TRUE(BRepCheck_Analyzer(second.getShape()).IsValid());
    EXPECT_EQ(second.countSubShapes(TopAbs_SOLID), 1);
    EXPECT_EQ(surfaces(second.getShape(), GeomAbs_BSplineSurface), 0);
    // The plate less the round's section along the outline's inner parallels:
    // int_0^r (r - sqrt(r^2 - t^2)) (P - 2 pi (r - t)) dt
    const double removed = (roundedLensLength(1.0) - 2 * pi * h) * h * h * (1 - pi / 4)
        + pi * h * h * h / 3;
    EXPECT_NEAR(volume(second.getShape()), roundedLensArea(1.0) * h - removed, 1e-5);
}

TEST_F(CanonicalFacesTest, aTrueSplineBlendIsLeft)
{
    // A round along the wavy top edge of a wavy wall: a true spline blend. Nothing is recognised,
    // and the result is OCCT's own
    TopoShape base(wavyPlate(0.5), 1L);
    std::vector<TopoShape> edges;
    for (const auto& edge : rimEdges(base, 5.0)) {
        if (BRepAdaptor_Curve(TopoDS::Edge(edge.getShape())).GetType() == GeomAbs_BSplineCurve) {
            edges.push_back(edge);
        }
    }
    ASSERT_EQ(edges.size(), 1);
    const TopoDS_Shape occt = occtFillet(base, edges, 1.0);
    ASSERT_FALSE(occt.IsNull());
    const int splines = surfaces(occt, GeomAbs_BSplineSurface);
    ASSERT_GE(splines, 1);
    printGaps("wavy wall, wave 0.5", occt);
    CF::Conversion conversion;
    EXPECT_FALSE(CF::convert(occt, base.getShape(), conversion));

    const TopoShape result = filleted(base, edges, 1.0);
    EXPECT_EQ(surfaces(result.getShape(), GeomAbs_BSplineSurface), splines);
    EXPECT_EQ(curves(result.getShape(), GeomAbs_BSplineCurve), curves(occt, GeomAbs_BSplineCurve));
    EXPECT_DOUBLE_EQ(volume(result.getShape()), volume(occt));
}

TEST_F(CanonicalFacesTest, aBlendNearlyACylinderIsLeft)
{
    // The same wall 1e-3 off straight: the round is within 1e-3 of a cylinder, not within 1e-6.
    // Where recognition is unsure, the face stays
    TopoShape base(wavyPlate(1e-3), 1L);
    std::vector<TopoShape> edges;
    for (const auto& edge : rimEdges(base, 5.0)) {
        if (BRepAdaptor_Curve(TopoDS::Edge(edge.getShape())).GetType() == GeomAbs_BSplineCurve) {
            edges.push_back(edge);
        }
    }
    ASSERT_EQ(edges.size(), 1);
    const TopoDS_Shape occt = occtFillet(base, edges, 1.0);
    ASSERT_FALSE(occt.IsNull());
    const int splines = surfaces(occt, GeomAbs_BSplineSurface);
    ASSERT_GE(splines, 1);
    const double gap = printGaps("wavy wall, wave 1e-3", occt);
    EXPECT_GT(gap, CF::tolerance);
    const TopoShape result = filleted(base, edges, 1.0);
    EXPECT_EQ(surfaces(result.getShape(), GeomAbs_BSplineSurface), splines);
    EXPECT_DOUBLE_EQ(volume(result.getShape()), volume(occt));
}

TEST_F(CanonicalFacesTest, aBaseSplineFaceIsNeverTouched)
{
    // The lens with every face stored as a B-spline (the user's own splines): the rounds between
    // them are the dress-up's and become cylinders; the base's faces keep their surfaces, and the
    // rounds' edges on them keep their curves
    TopoShape base(BRepBuilderAPI_NurbsConvert(lens()).Shape(), 1L);
    const int baseSplines = surfaces(base.getShape(), GeomAbs_BSplineSurface);
    ASSERT_EQ(baseSplines, static_cast<int>(base.countSubShapes(TopAbs_FACE)));
    std::vector<TopoShape> edges;
    for (const auto& edge : base.getSubTopoShapes(TopAbs_EDGE)) {
        BRepAdaptor_Curve curve(TopoDS::Edge(edge.getShape()));
        const gp_Pnt a = curve.Value(curve.FirstParameter());
        const gp_Pnt b = curve.Value(curve.LastParameter());
        if (std::abs(a.X()) < 1e-6 && std::abs(b.X()) < 1e-6 && std::abs(a.Z() - b.Z()) > h / 2) {
            edges.push_back(edge);
        }
    }
    ASSERT_EQ(edges.size(), 2);
    const TopoDS_Shape occt = occtFillet(base, edges, 1.0);
    ASSERT_FALSE(occt.IsNull());
    const int occtSplines = surfaces(occt, GeomAbs_BSplineSurface);
    printGaps("spline lens r 1", occt);
    std::cout << "MEASURE spline lens: base valid " << BRepCheck_Analyzer(base.getShape()).IsValid()
              << ", OCCT's fillet valid " << BRepCheck_Analyzer(occt).IsValid() << std::endl;
    CF::Conversion conversion;
    std::string why;
    EXPECT_TRUE(CF::convert(occt, base.getShape(), conversion, &why)) << why;
    const TopoShape result = filleted(base, edges, 1.0);
    EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
    EXPECT_EQ(surfaces(result.getShape(), GeomAbs_BSplineSurface), occtSplines - 2);
    EXPECT_EQ(surfaces(result.getShape(), GeomAbs_Cylinder), 2);
    EXPECT_NEAR(volume(result.getShape()), volume(occt), 1e-5);
    EXPECT_NEAR(volume(result.getShape()), roundedLensArea(1.0) * h, 1e-5);
}

TEST_F(CanonicalFacesTest, measuredGapsOfOtherPairs)
{
    // Not a pass or fail of the conversion: what OCCT's walker leaves for other pairs, for the
    // design note's tolerance band. Each result must be valid whether converted or not
    {
        // A circle between a cylinder and a coaxial cone: the exact round is a torus
        const TopoDS_Shape body = BRepAlgoAPI_Fuse(
                                      BRepPrimAPI_MakeCylinder(10, 10).Shape(),
                                      BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(0, 0, 10), gp::DZ()), 10, 4, 6).Shape()
        )
                                      .Shape();
        TopoShape base(body, 1L);
        std::vector<TopoShape> edges;
        for (const auto& edge : rimEdges(base, 10.0)) {
            edges.push_back(edge);
        }
        ASSERT_FALSE(edges.empty());
        const TopoDS_Shape occt = occtFillet(base, edges, 1.0);
        if (!occt.IsNull()) {
            printGaps("cylinder and cone, circle, r 1", occt);
            const TopoShape result = filleted(base, edges, 1.0);
            std::cout << "MEASURE cylinder and cone: B-spline faces " << surfaces(occt, GeomAbs_BSplineSurface)
                      << " -> " << surfaces(result.getShape(), GeomAbs_BSplineSurface) << ", tori "
                      << surfaces(result.getShape(), GeomAbs_Torus) << std::endl;
            EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
            EXPECT_NEAR(volume(result.getShape()), volume(occt), 1e-4);
        }
    }
    {
        // A chamfer of the lens's straight edges: the exact face is a plane
        TopoShape base(lens(), 1L);
        const auto edges = uprightEdges(base);
        BRepFilletAPI_MakeChamfer maker(base.getShape());
        for (const auto& edge : edges) {
            maker.Add(1.0, TopoDS::Edge(edge.getShape()));
        }
        maker.Build();
        if (maker.IsDone()) {
            printGaps("lens chamfer 1", maker.Shape());
            TopoShape result(2L);
            result.makeElementChamfer(base, edges, ChamferType::equalDistance, 1.0, 1.0);
            std::cout << "MEASURE lens chamfer: B-spline faces "
                      << surfaces(maker.Shape(), GeomAbs_BSplineSurface) << " -> "
                      << surfaces(result.getShape(), GeomAbs_BSplineSurface) << ", planes "
                      << surfaces(maker.Shape(), GeomAbs_Plane) << " -> "
                      << surfaces(result.getShape(), GeomAbs_Plane) << std::endl;
            EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
            EXPECT_NEAR(volume(result.getShape()), volume(maker.Shape()), 1e-5);
        }
    }
}
