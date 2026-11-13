// SPDX-License-Identifier: LGPL-2.1-or-later

// Canonical curves on a profile before a sweep (ops#640; CanonicalProfile.h). Designed geometry:
// every expectation is the surface class OCCT builds from a line or circle, or the control
// profile's own solid (the same profile drawn with the circle itself).

#include <cmath>
#include <numbers>
#include <string>
#include <vector>
#include <gtest/gtest.h>

#include "src/App/InitApplication.h"
#include <Base/Exception.h>
#include <Mod/Part/App/CanonicalProfile.h>
#include <Mod/Part/App/TopoShape.h>

#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepGProp.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <GeomConvert.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_Circle.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_Line.hxx>
#include <Geom_SurfaceOfLinearExtrusion.hxx>
#include <Geom_SurfaceOfRevolution.hxx>
#include <Geom_ToroidalSurface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>

namespace
{
using std::numbers::pi;

enum class Arc
{
    Circle,      // the control: the arc as a circle
    Nurbs,       // the same arc as an exact rational B-spline (on the circle to round-off)
    Off          // that B-spline with its middle pole moved by 1e-4: not a circle
};

Handle(Geom_TrimmedCurve) circleArc(const gp_Pnt& centre, const gp_Dir& normal, const gp_Dir& xAxis,
                                    double radius, double a0, double a1)
{
    Handle(Geom_Circle) circle = new Geom_Circle(gp_Ax2(centre, normal, xAxis), radius);
    return new Geom_TrimmedCurve(circle, a0, a1);
}

Handle(Geom_Curve) arcAs(const Handle(Geom_TrimmedCurve) & arc, Arc kind)
{
    if (kind == Arc::Circle) {
        return arc;
    }
    Handle(Geom_BSplineCurve) spline = GeomConvert::CurveToBSplineCurve(arc);
    if (kind == Arc::Off) {
        const int middle = (spline->NbPoles() + 1) / 2;
        gp_Pnt pole = spline->Pole(middle);
        pole.SetX(pole.X() + 1e-4);  // in the plane: the profile stays planar
        spline->SetPole(middle, pole);
    }
    return spline;
}

TopoDS_Edge edge(const Handle(Geom_Curve) & curve)
{
    return BRepBuilderAPI_MakeEdge(curve).Edge();
}

TopoDS_Edge segment(double x0, double y0, double x1, double y1)
{
    return BRepBuilderAPI_MakeEdge(gp_Pnt(x0, y0, 0), gp_Pnt(x1, y1, 0)).Edge();
}

// spline_wall.py's A1 plate profile (30 x 20, corners rounded 4, 1, 4, 4); the arc of radius 1
// about (29, 1) given as `kind`
TopoDS_Face plateProfile(Arc kind)
{
    const gp_Dir z(0, 0, 1), x(1, 0, 0);
    auto round = [&](double cx, double cy, double r, double a0, double a1) {
        return edge(circleArc(gp_Pnt(cx, cy, 0), z, x, r, a0 * pi / 180, a1 * pi / 180));
    };
    BRepBuilderAPI_MakeWire wire;
    wire.Add(segment(4, 0, 29, 0));
    wire.Add(edge(arcAs(circleArc(gp_Pnt(29, 1, 0), z, x, 1, -pi / 2, 0), kind)));
    wire.Add(segment(30, 1, 30, 16));
    wire.Add(round(26, 16, 4, 0, 90));
    wire.Add(segment(26, 20, 4, 20));
    wire.Add(round(4, 16, 4, 90, 180));
    wire.Add(segment(0, 16, 0, 4));
    wire.Add(round(4, 4, 4, 180, 270));
    return BRepBuilderAPI_MakeFace(wire.Wire(), Standard_True).Face();
}

// The surface classes of the faces whose box lies in the tight corner (x > 29, y < 1)
std::vector<std::string> cornerSurfaces(const TopoDS_Shape& solid)
{
    std::vector<std::string> kinds;
    for (TopExp_Explorer faces(solid, TopAbs_FACE); faces.More(); faces.Next()) {
        const TopoDS_Face& face = TopoDS::Face(faces.Current());
        GProp_GProps props;
        BRepGProp::SurfaceProperties(face, props);
        const gp_Pnt c = props.CentreOfMass();
        if (c.X() > 29 && c.Y() < 1 && c.Z() > 0.1 && c.Z() < 4.9) {
            kinds.emplace_back(BRep_Tool::Surface(face)->DynamicType()->Name());
        }
    }
    return kinds;
}

double volume(const TopoDS_Shape& solid)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(solid, props);
    return props.Mass();
}

class CanonicalProfileTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
};

}  // namespace

// The red case of spline_wall.py: the wall of the arc as a B-spline is a cylinder, as the
// control's, and the solid and its names are the control's
TEST_F(CanonicalProfileTest, prismOfSplineArcIsCylinder)
{
    Part::TopoShape control(1);
    control.makeElementPrism(Part::TopoShape(plateProfile(Arc::Circle)), gp_Vec(0, 0, 5));
    Part::TopoShape nurbs(1);
    nurbs.makeElementPrism(Part::TopoShape(plateProfile(Arc::Nurbs)), gp_Vec(0, 0, 5));

    EXPECT_EQ(cornerSurfaces(control.getShape()), std::vector<std::string> {"Geom_CylindricalSurface"});
    EXPECT_EQ(cornerSurfaces(nurbs.getShape()), std::vector<std::string> {"Geom_CylindricalSurface"});
    EXPECT_NEAR(volume(nurbs.getShape()), volume(control.getShape()), 1e-9);
    EXPECT_NEAR(volume(control.getShape()), 5 * (600 - 3 * (16 - 4 * pi) - (4 - pi) / 4 * 1), 1e-9);
    EXPECT_EQ(nurbs.getElementMap(), control.getElementMap());
}

// An edge that is not a circle within 1e-7 takes today's path: a surface of extrusion, no error
TEST_F(CanonicalProfileTest, prismOfNonCircularSplineIsUnchanged)
{
    Part::TopoShape off(1);
    EXPECT_NO_THROW(off.makeElementPrism(Part::TopoShape(plateProfile(Arc::Off)), gp_Vec(0, 0, 5)));
    EXPECT_EQ(cornerSurfaces(off.getShape()),
              std::vector<std::string> {"Geom_SurfaceOfLinearExtrusion"});
}

// Revolutions: a spline line gives a cylinder, a spline circle a ring torus; a circle about a
// centre within its radius of the axis (a horn torus) is left as OCCT makes it
TEST_F(CanonicalProfileTest, revolveOfSplineCurves)
{
    const gp_Ax1 zAxis(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1));
    auto surfaceOf = [&](const Handle(Geom_Curve) & curve) {
        Part::TopoShape result(1);
        result.makeElementRevolve(Part::TopoShape(edge(curve)), zAxis, 2 * pi);
        TopExp_Explorer faces(result.getShape(), TopAbs_FACE);
        return std::string(BRep_Tool::Surface(TopoDS::Face(faces.Current()))->DynamicType()->Name());
    };
    Handle(Geom_TrimmedCurve) line =
        new Geom_TrimmedCurve(new Geom_Line(gp_Pnt(4, 0, 0), gp_Dir(0, 0, 1)), 0, 3);
    EXPECT_EQ(surfaceOf(GeomConvert::CurveToBSplineCurve(line)), "Geom_CylindricalSurface");

    const gp_Dir y(0, 1, 0), x(1, 0, 0);
    // In the XZ plane, about (3, 0, 0), radius 1: a ring torus
    EXPECT_EQ(surfaceOf(arcAs(circleArc(gp_Pnt(3, 0, 0), y, x, 1, 0, pi), Arc::Nurbs)),
              "Geom_ToroidalSurface");
    // About (0.5, 0, 0), radius 1: a horn torus, never converted
    EXPECT_EQ(surfaceOf(arcAs(circleArc(gp_Pnt(0.5, 0, 0), y, x, 1, 0, pi / 2), Arc::Nurbs)),
              "Geom_SurfaceOfRevolution");
}

// The refusal: a canonical curve that is not within the tolerance, or runs the other way, is
// refused loudly (the must-fail of decision 418's contract); the right one passes
TEST_F(CanonicalProfileTest, checkRefusesWrongCurve)
{
    const gp_Dir z(0, 0, 1), x(1, 0, 0);
    Handle(Geom_TrimmedCurve) arc = circleArc(gp_Pnt(29, 1, 0), z, x, 1, -pi / 2, 0);
    Handle(Geom_Curve) spline = arcAs(arc, Arc::Nurbs);
    const double f = spline->FirstParameter(), l = spline->LastParameter();

    Handle(Geom_Circle) right = new Geom_Circle(gp_Ax2(gp_Pnt(29, 1, 0), z, x), 1);
    EXPECT_NO_THROW(Part::checkCanonicalEdge(spline, f, l, right, -pi / 2, 0));

    Handle(Geom_Circle) wider = new Geom_Circle(gp_Ax2(gp_Pnt(29, 1, 0), z, x), 1 + 1e-6);
    EXPECT_THROW(Part::checkCanonicalEdge(spline, f, l, wider, -pi / 2, 0), Base::CADKernelError);

    Handle(Geom_Circle) reversed = new Geom_Circle(gp_Ax2(gp_Pnt(29, 1, 0), z.Reversed(), x), 1);
    EXPECT_THROW(Part::checkCanonicalEdge(spline, f, l, reversed, 0, pi / 2), Base::CADKernelError);

    Handle(Geom_Line) chord = new Geom_Line(gp_Pnt(29, 0, 0), gp_Dir(1, 1, 0));
    EXPECT_THROW(Part::checkCanonicalEdge(spline, f, l, chord, 0, std::sqrt(2.0)),
                 Base::CADKernelError);
}
