// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <chrono>
#include <cmath>
#include <iostream>
#include <numbers>

#include <BRepAdaptor_CompCurve.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepOffsetAPI_MakePipe.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GProp_GProps.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <Precision.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>

#include <Mod/Part/App/MassProperties.h>

// Designed geometry for ops#414: a cosine wave x = a (1 - cos(2 pi y / 20)), interpolated by one
// cubic B-spline through points 1 mm apart (20 spans per wave). Over whole waves its mean is a and
// its mean square 1.5 a^2.

namespace
{

constexpr double pi = std::numbers::pi;
constexpr int period = 20;

TopoDS_Edge waveEdge(int waves, double amplitude)
{
    const int length = period * waves;
    Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, length + 1);
    for (int y = 0; y <= length; ++y) {
        points->SetValue(y + 1, gp_Pnt(amplitude * (1 - std::cos(2 * pi * y / period)), y, 0));
    }
    GeomAPI_Interpolate interpolate(points, false, Precision::Confusion());
    interpolate.Perform();
    return BRepBuilderAPI_MakeEdge(interpolate.Curve()).Edge();
}

/// The wave closed by lines at x = -5: its area is (5 + a) times its length
TopoDS_Face waveFace(int waves, double amplitude = 1.5)
{
    const double length = period * waves;
    BRepBuilderAPI_MakeWire wire;
    wire.Add(waveEdge(waves, amplitude));
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, length, 0), gp_Pnt(-5, length, 0)).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(-5, length, 0), gp_Pnt(-5, 0, 0)).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(-5, 0, 0), gp_Pnt(0, 0, 0)).Edge());
    return BRepBuilderAPI_MakeFace(wire.Wire(), true).Face();
}

/// The wave face extruded 10 along z
TopoDS_Shape wavePrism(int waves, double amplitude = 1.5)
{
    return BRepPrimAPI_MakePrism(waveFace(waves, amplitude), gp_Vec(0, 0, 10)).Shape();
}

/// A tube of radius 2 along the wave (its least radius of curvature is 6.1), and the wave's length
std::pair<TopoDS_Shape, double> wavePipe(int waves)
{
    const TopoDS_Wire spine = BRepBuilderAPI_MakeWire(waveEdge(waves, 1.5)).Wire();
    const gp_Circ section(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)), 2.0);
    const TopoDS_Wire circle =
        BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(section).Edge()).Wire();
    BRepOffsetAPI_MakePipe pipe(spine, BRepBuilderAPI_MakeFace(circle, true).Face());
    pipe.Build();
    return {pipe.Shape(), GCPnts_AbscissaPoint::Length(BRepAdaptor_CompCurve(spine))};
}

double defaultVolume(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape, props);
    return props.Mass();
}

double relativeError(double value, double expected)
{
    return std::abs(value - expected) / std::abs(expected);
}

void expectSameProps(const GProp_GProps& a, const GProp_GProps& b)
{
    EXPECT_EQ(a.Mass(), b.Mass());
    EXPECT_EQ(a.CentreOfMass().X(), b.CentreOfMass().X());
    EXPECT_EQ(a.CentreOfMass().Y(), b.CentreOfMass().Y());
    EXPECT_EQ(a.CentreOfMass().Z(), b.CentreOfMass().Z());
    for (int i = 1; i <= 3; ++i) {
        for (int j = 1; j <= 3; ++j) {
            EXPECT_EQ(a.MatrixOfInertia().Value(i, j), b.MatrixOfInertia().Value(i, j));
        }
    }
}

/// The helper's volume and surface properties equal OCCT's default bit for bit
void expectDefault(const TopoDS_Shape& shape)
{
    EXPECT_FALSE(Part::MassProperties::needsAdaptive(shape));
    GProp_GProps helper;
    GProp_GProps reference;
    Part::MassProperties::volumeProperties(shape, helper);
    BRepGProp::VolumeProperties(shape, reference);
    expectSameProps(helper, reference);
    GProp_GProps helperArea;
    GProp_GProps referenceArea;
    Part::MassProperties::surfaceProperties(shape, helperArea);
    BRepGProp::SurfaceProperties(shape, referenceArea);
    expectSameProps(helperArea, referenceArea);
}

TopoDS_Shape filletedBox()
{
    const TopoDS_Shape box = BRepPrimAPI_MakeBox(20, 10, 5).Shape();
    BRepFilletAPI_MakeFillet fillet(box);
    for (TopExp_Explorer it(box, TopAbs_EDGE); it.More(); it.Next()) {
        fillet.Add(1.0, TopoDS::Edge(it.Current()));
    }
    return fillet.Shape();
}

/// A plate 100 x 100 x 10 with 100 holes of radius 2
TopoDS_Shape boxWithHoles()
{
    TopTools_ListOfShape arguments;
    arguments.Append(BRepPrimAPI_MakeBox(100, 100, 10).Shape());
    TopTools_ListOfShape tools;
    for (int i = 0; i < 10; ++i) {
        for (int j = 0; j < 10; ++j) {
            const gp_Ax2 axis(gp_Pnt(5 + 10 * i, 5 + 10 * j, -1), gp_Dir(0, 0, 1));
            tools.Append(BRepPrimAPI_MakeCylinder(axis, 2, 12).Shape());
        }
    }
    BRepAlgoAPI_Cut cut;
    cut.SetArguments(arguments);
    cut.SetTools(tools);
    cut.Build();
    return cut.Shape();
}

template<class Function>
double millisecondsPerCall(int calls, Function function)
{
    const auto start = std::chrono::steady_clock::now();
    for (int i = 0; i < calls; ++i) {
        function();
    }
    const std::chrono::duration<double, std::milli> elapsed =
        std::chrono::steady_clock::now() - start;
    return elapsed.count() / calls;
}

}  // namespace

// The default integration is wrong on the long wave prisms; the helper is right
TEST(MassProperties, longWavePrismVolume)
{
    for (int waves : {10, 25, 50}) {
        SCOPED_TRACE(waves);
        const TopoDS_Shape prism = wavePrism(waves);
        const double exact = 10 * 6.5 * period * waves;
        EXPECT_TRUE(Part::MassProperties::needsAdaptive(prism));
        EXPECT_LT(relativeError(Part::MassProperties::volume(prism), exact), 1e-4);
        if (waves >= 25) {
            // the defect the helper is for: off by tens of per cent
            EXPECT_GT(relativeError(defaultVolume(prism), exact), 1e-2);
        }
    }
}

// The planar face whose edge is the wave: the default area is wrong too
TEST(MassProperties, longWaveFaceArea)
{
    for (int waves : {25, 50}) {
        SCOPED_TRACE(waves);
        const TopoDS_Face face = waveFace(waves);
        const double exact = 6.5 * period * waves;
        EXPECT_TRUE(Part::MassProperties::needsAdaptive(face));
        GProp_GProps props;
        Part::MassProperties::surfaceProperties(face, props);
        EXPECT_LT(relativeError(props.Mass(), exact), 1e-4);
        // the centre as the prism's below
        EXPECT_NEAR(props.CentreOfMass().X(), (1.5 * 1.5 * 1.5 - 25) / (2 * 6.5), 1e-3);
        EXPECT_NEAR(props.CentreOfMass().Y(), period * waves / 2.0, 1e-3);
    }
}

// The centre of the prism over whole waves: x is the mean of (x^2 - 25) / 2 over the section,
// (1.5 a^2 - 25) / (2 (5 + a)); y half its length, z half its height
TEST(MassProperties, longWavePrismCentreOfMass)
{
    const int waves = 25;
    GProp_GProps props;
    Part::MassProperties::volumeProperties(wavePrism(waves), props);
    const gp_Pnt centre = props.CentreOfMass();
    EXPECT_NEAR(centre.X(), (1.5 * 1.5 * 1.5 - 25) / (2 * 6.5), 1e-3);
    EXPECT_NEAR(centre.Y(), period * waves / 2.0, 1e-3);
    EXPECT_NEAR(centre.Z(), 5.0, 1e-3);

    // The moment about the vertical axis through the centre: per unit height, the integral over y
    // of ((w - cx)^3 - (-5 - cx)^3) / 3 + (5 + w) (y - cy)^2, by Simpson's rule on the cosine
    const double length = period * waves;
    const double cx = (1.5 * 1.5 * 1.5 - 25) / (2 * 6.5);
    const auto integrand = [&](double y) {
        const double w = 1.5 * (1 - std::cos(2 * pi * y / period));
        return (std::pow(w - cx, 3) - std::pow(-5 - cx, 3)) / 3
            + (5 + w) * (y - length / 2) * (y - length / 2);
    };
    const int steps = 100000;
    const double h = length / steps;
    double sum = integrand(0) + integrand(length);
    for (int i = 1; i < steps; ++i) {
        sum += (i % 2 ? 4 : 2) * integrand(i * h);
    }
    const double izz = 10 * sum * h / 3;
    EXPECT_LT(relativeError(props.MatrixOfInertia().Value(3, 3), izz), 1e-4);
}

// A pipe along the wave: its lateral face is a B-spline surface of many spans. Its volume is the
// circle's area times the spine's length (Pappus: the section is normal to the spine)
TEST(MassProperties, longWavePipeVolume)
{
    const auto [pipe, length] = wavePipe(25);
    ASSERT_FALSE(pipe.IsNull());
    EXPECT_TRUE(Part::MassProperties::needsAdaptive(pipe));
    EXPECT_LT(relativeError(std::abs(Part::MassProperties::volume(pipe)), pi * 4 * length), 1e-4);
}

// Amplitude 0: a straight B-spline of as many spans, which the default integrates exactly. The
// screen passes it through, and the numbers are the default's
TEST(MassProperties, straightSplineUnchanged)
{
    const TopoDS_Shape prism = wavePrism(50, 0.0);
    expectDefault(prism);
    EXPECT_LT(relativeError(Part::MassProperties::volume(prism), 10 * 5 * period * 50), 1e-9);
}

// Ordinary shapes: the screen doesn't trigger, and every number is the default's bit for bit
TEST(MassProperties, ordinaryShapesUnchanged)
{
    {
        SCOPED_TRACE("filleted box");
        expectDefault(filletedBox());
    }
    {
        SCOPED_TRACE("box with 100 holes");
        expectDefault(boxWithHoles());
    }
    {
        SCOPED_TRACE("torus");
        expectDefault(BRepPrimAPI_MakeTorus(10, 3).Shape());
    }
    {
        SCOPED_TRACE("sphere cut by a box");
        const TopoDS_Shape sphere = BRepPrimAPI_MakeSphere(10).Shape();
        const TopoDS_Shape box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 20, 20, 20).Shape();
        expectDefault(BRepAlgoAPI_Cut(sphere, box).Shape());
    }
    for (int waves : {1, 2}) {
        // 20 and 40 spans: at most the threshold
        SCOPED_TRACE(waves);
        expectDefault(wavePrism(waves));
    }
}

// The screen costs a small part of the default integration on an ordinary shape of many faces.
// The times are printed for the record (ops#414)
TEST(MassProperties, screenIsCheap)
{
    const TopoDS_Shape plate = boxWithHoles();
    const double screen = millisecondsPerCall(200, [&] {
        EXPECT_FALSE(Part::MassProperties::needsAdaptive(plate));
    });
    const double integration = millisecondsPerCall(20, [&] {
        defaultVolume(plate);
    });
    std::cout << "box with 100 holes: screen " << screen << " ms, default volume " << integration
              << " ms" << std::endl;
    EXPECT_LT(screen, integration / 4);

    for (int waves : {10, 25, 50}) {
        const TopoDS_Shape prism = wavePrism(waves);
        const double adaptive = millisecondsPerCall(3, [&] {
            Part::MassProperties::volume(prism);
        });
        const double plain = millisecondsPerCall(3, [&] {
            defaultVolume(prism);
        });
        std::cout << period * waves << "-span prism: helper " << adaptive << " ms, default "
                  << plain << " ms" << std::endl;
    }
}
