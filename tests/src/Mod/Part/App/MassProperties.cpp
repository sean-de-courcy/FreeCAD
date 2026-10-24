// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <chrono>
#include <cmath>
#include <iostream>
#include <numbers>
#include <utility>

#include <BRepAdaptor_CompCurve.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepLib.hxx>
#include <BRepOffsetAPI_MakePipe.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GCE2d_MakeSegment.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GProp_GProps.hxx>
#include <Geom2dAPI_Interpolate.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_Line.hxx>
#include <Geom_Ellipse.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_OffsetCurve.hxx>
#include <Geom_OffsetSurface.hxx>
#include <Geom_Plane.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom_SurfaceOfLinearExtrusion.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <Precision.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TColgp_HArray1OfPnt2d.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>
#include <gp_Dir2d.hxx>
#include <gp_Elips.hxx>
#include <gp_Mat.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Vec2d.hxx>

#include <Mod/Part/App/MassProperties.h>

// Designed geometry for ops#414: a cosine wave x = a (1 - cos(2 pi y / 20)), interpolated by one
// cubic B-spline through points 1 mm apart (20 spans per wave). Over whole waves its mean is a and
// its mean square 1.5 a^2.

namespace
{

constexpr double pi = std::numbers::pi;
constexpr int period = 20;

/// x = base + amplitude (1 - cos(2 pi y / wavePeriod)) through the points y = 0, 1, ..., spans
Handle(
    Geom_BSplineCurve
) waveSpline(int spans, int wavePeriod = period, double amplitude = 1.5, double base = 0.0)
{
    Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, spans + 1);
    for (int y = 0; y <= spans; ++y) {
        const double x = base + amplitude * (1 - std::cos(2 * pi * y / wavePeriod));
        points->SetValue(y + 1, gp_Pnt(x, y, 0));
    }
    GeomAPI_Interpolate interpolate(points, false, Precision::Confusion());
    interpolate.Perform();
    return interpolate.Curve();
}

TopoDS_Edge waveEdge(int waves, double amplitude)
{
    return BRepBuilderAPI_MakeEdge(waveSpline(period * waves, period, amplitude)).Edge();
}

/// The integral of f over the curve's parameter range: 5-point Gauss-Legendre on 8 pieces of each
/// knot span. Exact for an integrand that is a polynomial of degree 9 or less on each span; to
/// rounding for the smooth ones below
template<class Curve, class Function>
double overSpans(const Curve& curve, Function f)
{
    constexpr double nodes[]
        = {0.0, -0.5384693101056831, 0.5384693101056831, -0.9061798459386640, 0.9061798459386640};
    constexpr double weights[] = {
        0.5688888888888889,
        0.4786286704993665,
        0.4786286704993665,
        0.2369268850561891,
        0.2369268850561891
    };
    constexpr int pieces = 8;
    double total = 0.0;
    for (int i = 1; i < curve.NbKnots(); ++i) {
        const double h = (curve.Knot(i + 1) - curve.Knot(i)) / pieces;
        for (int piece = 0; piece < pieces; ++piece) {
            const double middle = curve.Knot(i) + (piece + 0.5) * h;
            for (int k = 0; k < 5; ++k) {
                total += weights[k] * f(middle + nodes[k] * h / 2) * h / 2;
            }
        }
    }
    return total;
}

double arcLength(const Handle(Geom_BSplineCurve) & curve)
{
    return overSpans(*curve, [&](double t) { return curve->DN(t, 1).Magnitude(); });
}

/// The area between the curve, rising in y, and the line x = -5: the integral of (x + 5) dy,
/// a polynomial of degree 5 on each span
template<class Curve>
double areaBehind(const Curve& curve)
{
    return overSpans(curve, [&](double t) {
        const auto point = curve.Value(t);
        const auto tangent = curve.DN(t, 1);
        return (point.X() + 5) * tangent.Y();
    });
}

/// The region between the curve, rising in y from y = 0, and the line x = -5
TopoDS_Face faceBehind(const Handle(Geom_BSplineCurve) & curve)
{
    const gp_Pnt start = curve->StartPoint();
    const gp_Pnt end = curve->EndPoint();
    BRepBuilderAPI_MakeWire wire;
    wire.Add(BRepBuilderAPI_MakeEdge(curve).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(end, gp_Pnt(-5, end.Y(), 0)).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(-5, end.Y(), 0), gp_Pnt(-5, start.Y(), 0)).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(-5, start.Y(), 0), start).Edge());
    return BRepBuilderAPI_MakeFace(wire.Wire(), true).Face();
}

/// The curve extruded 10 along z
Handle(Geom_SurfaceOfLinearExtrusion) extrusionOf(const Handle(Geom_Curve) & curve)
{
    return new Geom_SurfaceOfLinearExtrusion(curve, gp_Dir(0, 0, 1));
}

/// The face of the curve's extrusion over the curve's range and z in [0, 10]: area 10 times the
/// curve's length
TopoDS_Face sideFace(const Handle(Geom_BSplineCurve) & curve)
{
    return BRepBuilderAPI_MakeFace(
               extrusionOf(curve),
               curve->FirstParameter(),
               curve->LastParameter(),
               0.0,
               10.0,
               Precision::Confusion()
    )
        .Face();
}

/// A face on the surface over [u0, u1] x [v0, v1], its edges made on that very surface. A trimmed
/// surface stays the face's surface this way; BRepBuilderAPI_MakeFace takes its basis instead
TopoDS_Face faceOn(const Handle(Geom_Surface) & surface, double u0, double u1, double v0, double v1)
{
    const double tolerance = Precision::Confusion();
    BRep_Builder builder;
    const gp_Pnt2d corners[] = {{u0, v0}, {u1, v0}, {u1, v1}, {u0, v1}};
    TopoDS_Vertex vertices[4];
    for (int i = 0; i < 4; ++i) {
        builder.MakeVertex(vertices[i], surface->Value(corners[i].X(), corners[i].Y()), tolerance);
    }
    TopoDS_Face face;
    builder.MakeFace(face, surface, tolerance);
    TopoDS_Wire wire;
    builder.MakeWire(wire);
    for (int i = 0; i < 4; ++i) {
        const gp_Pnt2d& start = corners[i];
        const gp_Pnt2d& end = corners[(i + 1) % 4];
        TopoDS_Edge edge;
        builder.MakeEdge(edge);
        builder.UpdateEdge(edge, new Geom2d_Line(start, gp_Dir2d(gp_Vec2d(start, end))), face, tolerance);
        builder.Range(edge, 0.0, start.Distance(end));
        builder.Add(edge, vertices[i].Oriented(TopAbs_FORWARD));
        builder.Add(edge, vertices[(i + 1) % 4].Oriented(TopAbs_REVERSED));
        BRepLib::BuildCurve3d(edge);
        builder.Add(wire, edge);
    }
    builder.Add(face, wire);
    return face;
}

double defaultArea(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(shape, props);
    return props.Mass();
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

// The face of an extrusion of the wave over z in [0, 10]. With ds the wave's arc length, its area
// is 10 times the wave's length, its first moments 10 times the integrals of x ds and y ds and 50
// times its length, its second moments 10 times those of x^2, y^2 and x y, 1000 / 3 times its
// length for z^2, and 50 times the integrals of x ds and y ds for x z and y z. OCCT's adaptive area
// on the extrusion was off by 1.3e-4 (500 spans), 2.9e-4 (1000) and 1.9 % (41 spans, 4 to a wave);
// the helper's boundary integral is exact up to its tolerance (ops#414)
TEST(MassProperties, extrusionFaceArea)
{
    const std::pair<int, int> cases[] = {{500, 20}, {1000, 20}, {41, 4}};
    for (const auto& [spans, wavePeriod] : cases) {
        SCOPED_TRACE(spans);
        const auto wave = waveSpline(spans, wavePeriod);
        const TopoDS_Face side = sideFace(wave);
        EXPECT_TRUE(Part::MassProperties::needsAdaptive(side));
        GProp_GProps props;
        Part::MassProperties::surfaceProperties(side, props);

        const auto along = [&](auto g) {
            return overSpans(*wave, [&](double t) {
                return g(wave->Value(t)) * wave->DN(t, 1).Magnitude();
            });
        };
        const double length = arcLength(wave);
        const double area = 10 * length;
        const double x = 10 * along([](const gp_Pnt& p) { return p.X(); }) / area;
        const double y = 10 * along([](const gp_Pnt& p) { return p.Y(); }) / area;
        const double z = 5.0;
        // The second moments about the centre
        const double xx = 10 * along([](const gp_Pnt& p) { return p.X() * p.X(); }) - area * x * x;
        const double yy = 10 * along([](const gp_Pnt& p) { return p.Y() * p.Y(); }) - area * y * y;
        const double zz = 1000.0 / 3 * length - area * z * z;
        const double xy = 10 * along([](const gp_Pnt& p) { return p.X() * p.Y(); }) - area * x * y;
        const double xz = 50 * along([](const gp_Pnt& p) { return p.X(); }) - area * x * z;
        const double yz = 50 * along([](const gp_Pnt& p) { return p.Y(); }) - area * y * z;
        const gp_Mat inertia(
            gp_XYZ(yy + zz, -xy, -xz),
            gp_XYZ(-xy, xx + zz, -yz),
            gp_XYZ(-xz, -yz, xx + yy)
        );

        EXPECT_LT(relativeError(props.Mass(), area), 1e-9);
        const gp_Pnt centre = props.CentreOfMass();
        EXPECT_NEAR(centre.X(), x, 1e-9 * spans);
        EXPECT_NEAR(centre.Y(), y, 1e-9 * spans);
        EXPECT_NEAR(centre.Z(), z, 1e-9 * spans);
        const double scale = inertia.Value(3, 3);
        for (int i = 1; i <= 3; ++i) {
            for (int j = 1; j <= 3; ++j) {
                SCOPED_TRACE(10 * i + j);
                EXPECT_NEAR(props.MatrixOfInertia().Value(i, j), inertia.Value(i, j), 1e-9 * scale);
            }
        }
    }
}

// The extrusion of an offset curve of the wave, the basis of an offset of the extrusion's face:
// its area is 10 times the offset curve's length. Round 2 converted it to NURBS, an approximation
// 2.2 mm off at 500 spans and 5.4 at 1000 that OCCT reports as done: -3.4 % and -3.9 % (ops#414)
TEST(MassProperties, offsetCurveExtrusion)
{
    for (int spans : {500, 1000}) {
        const auto wave = waveSpline(spans);
        for (double distance : {1.0, -1.0}) {
            SCOPED_TRACE(spans * distance);
            Handle(Geom_OffsetCurve) curve = new Geom_OffsetCurve(wave, distance, gp_Dir(0, 0, 1));
            const TopoDS_Face face = BRepBuilderAPI_MakeFace(
                                         extrusionOf(curve),
                                         wave->FirstParameter(),
                                         wave->LastParameter(),
                                         0.0,
                                         10.0,
                                         Precision::Confusion()
            )
                                         .Face();
            const double length = overSpans(*wave, [&](double t) {
                return curve->DN(t, 1).Magnitude();
            });
            EXPECT_TRUE(Part::MassProperties::needsAdaptive(face));
            EXPECT_LT(relativeError(Part::MassProperties::area(face), 10 * length), 1e-9);
        }
    }
}

// The wave's side trimmed by a Boolean to z in [2, 5]: its edges at z = 2 and 5 are intersection
// curves, B-splines of their own spans in the face's parameters. Its area is 3 times the wave's
// length. Round 2's NURBS conversion was exact here, but OCCT's adaptive area on it took 7.6 s at
// 500 spans and 58 s at 1000, and FilletFallback reads the area of every new face of a fillet or
// chamfer (ops#414)
TEST(MassProperties, trimmedSideFaceIsFast)
{
    for (int waves : {25, 50}) {
        SCOPED_TRACE(waves);
        const double length = period * waves;
        const auto wave = waveSpline(period * waves);
        const TopoDS_Shape slab = BRepAlgoAPI_Common(
                                      wavePrism(waves),
                                      BRepPrimAPI_MakeBox(gp_Pnt(-10, -1, 2), 20, length + 2, 3).Shape()
        )
                                      .Shape();
        TopoDS_Face side;
        for (TopExp_Explorer it(slab, TopAbs_FACE); it.More(); it.Next()) {
            TopLoc_Location location;
            if (BRep_Tool::Surface(TopoDS::Face(it.Current()), location)
                    ->IsKind(STANDARD_TYPE(Geom_SurfaceOfLinearExtrusion))) {
                side = TopoDS::Face(it.Current());
            }
        }
        ASSERT_FALSE(side.IsNull());
        bool splineBoundary = false;
        for (TopExp_Explorer it(side, TopAbs_EDGE); it.More(); it.Next()) {
            double first = 0.0;
            double last = 0.0;
            const auto pcurve
                = BRep_Tool::CurveOnSurface(TopoDS::Edge(it.Current()), side, first, last);
            splineBoundary = splineBoundary || pcurve->IsKind(STANDARD_TYPE(Geom2d_BSplineCurve));
        }
        EXPECT_TRUE(splineBoundary);
        EXPECT_TRUE(Part::MassProperties::needsAdaptive(side));
        double area = 0.0;
        const double milliseconds = millisecondsPerCall(1, [&] {
            area = Part::MassProperties::area(side);
        });
        std::cout << period * waves << " spans, side trimmed to z in [2, 5]: " << milliseconds
                  << " ms" << std::endl;
        EXPECT_LT(relativeError(area, 3 * arcLength(wave)), 1e-9);
        EXPECT_LT(milliseconds, 500.0);
    }
}

// An elliptic prism in a shape the screen sends to the adaptive methods: its side, an extrusion of
// the ellipse, by its boundary integral too. Round 2 converted it to a rational B-spline surface,
// on which OCCT's adaptive area was 0.86 % off for 20 x 2 (ops#414). The ellipse's perimeter by the
// trapezoidal rule, exact to rounding for a periodic integrand
TEST(MassProperties, ellipseInAScreenedShape)
{
    for (const auto& [a, b] : {std::pair {5.0, 3.0}, std::pair {20.0, 2.0}}) {
        SCOPED_TRACE(a);
        const gp_Elips ellipse(gp_Ax2(gp_Pnt(0, -50, 0), gp_Dir(0, 0, 1)), a, b);
        const TopoDS_Wire outline
            = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(ellipse).Edge()).Wire();
        const TopoDS_Shape elliptic
            = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(outline, true).Face(), gp_Vec(0, 0, 10))
                  .Shape();
        const int steps = 4000;
        double perimeter = 0.0;
        for (int i = 0; i < steps; ++i) {
            const double t = 2 * pi * i / steps;
            perimeter += std::hypot(a * std::sin(t), b * std::cos(t)) * 2 * pi / steps;
        }
        const double ellipticArea = 10 * perimeter + 2 * pi * a * b;

        const int waves = 25;
        const auto wave = waveSpline(period * waves);
        const double section = areaBehind(*wave);
        const double waveArea = 10 * arcLength(wave) + 2 * section + 10 * period * waves + 2 * 50;

        BRep_Builder builder;
        TopoDS_Compound both;
        builder.MakeCompound(both);
        builder.Add(both, elliptic);
        builder.Add(both, wavePrism(waves));
        EXPECT_TRUE(Part::MassProperties::needsAdaptive(both));
        EXPECT_LT(relativeError(Part::MassProperties::area(both), ellipticArea + waveArea), 1e-9);
    }
}

// Just past the screen's threshold: 41 spans, 4 to a wave, so curved that OCCT's default volume
// is off by 6 %. The prism's volume is 10 times its section's area; its area is the side's (10
// times the wave's length), the top's and bottom's, the back's (10 x 41) and the two ends'
TEST(MassProperties, justPastTheThreshold)
{
    const auto wave = waveSpline(41, 4);
    const TopoDS_Shape prism = BRepPrimAPI_MakePrism(faceBehind(wave), gp_Vec(0, 0, 10)).Shape();
    EXPECT_TRUE(Part::MassProperties::needsAdaptive(prism));
    const double section = areaBehind(*wave);
    const double volume = 10 * section;
    EXPECT_GT(relativeError(defaultVolume(prism), volume), 1e-2);
    EXPECT_LT(relativeError(Part::MassProperties::volume(prism), volume), 1e-7);
    const double ends = 10 * (wave->StartPoint().X() + 5) + 10 * (wave->EndPoint().X() + 5);
    const double area = 10 * arcLength(wave) + 2 * section + 10 * 41 + ends;
    // 1.2e-6 off; 0.8 % with the adaptive area on the extrusion itself
    EXPECT_LT(relativeError(Part::MassProperties::area(prism), area), 1e-5);
}

// The screen sees a long B-spline through the wrappers OCCT puts around it, and the helper's
// numbers are right through them
TEST(MassProperties, wrappedSplines)
{
    const auto wave = waveSpline(500);
    const double first = wave->FirstParameter();
    const double last = wave->LastParameter();
    {
        // The extrusion's surface in a rectangular trim: area 10 times the wave's length
        SCOPED_TRACE("trimmed surface");
        Handle(Geom_Surface)
            trimmed = new Geom_RectangularTrimmedSurface(extrusionOf(wave), first, last, 0.0, 10.0);
        const TopoDS_Face face = faceOn(trimmed, first, last, 0.0, 10.0);
        TopLoc_Location location;
        ASSERT_TRUE(
            BRep_Tool::Surface(face, location)->IsKind(STANDARD_TYPE(Geom_RectangularTrimmedSurface))
        );
        EXPECT_TRUE(Part::MassProperties::needsAdaptive(face));
        EXPECT_LT(relativeError(Part::MassProperties::area(face), 10 * arcLength(wave)), 1e-9);
    }
    {
        // An extrusion of the wave trimmed to its middle 250 spans, as a trimmed curve: area 10
        // times the length of those spans
        SCOPED_TRACE("trimmed basis curve");
        const double a = wave->Knot(126);
        const double b = wave->Knot(376);
        Handle(Geom_Curve) half = new Geom_TrimmedCurve(wave, a, b);
        const TopoDS_Face face
            = BRepBuilderAPI_MakeFace(extrusionOf(half), a, b, 0.0, 10.0, Precision::Confusion()).Face();
        const double length = overSpans(*wave, [&](double t) {
            return t > a && t < b ? wave->DN(t, 1).Magnitude() : 0.0;
        });
        EXPECT_TRUE(Part::MassProperties::needsAdaptive(face));
        EXPECT_LT(relativeError(Part::MassProperties::area(face), 10 * length), 1e-9);
    }
    {
        // The extrusion offset by 1 along its normal, the wave's tangent crossed with z: the
        // extrusion of the wave's offset curve, area 10 times that curve's length
        SCOPED_TRACE("offset surface");
        Handle(Geom_Surface) offset = new Geom_OffsetSurface(extrusionOf(wave), 1.0);
        const TopoDS_Face face
            = BRepBuilderAPI_MakeFace(offset, first, last, 0.0, 10.0, Precision::Confusion()).Face();
        Handle(Geom_OffsetCurve) curve = new Geom_OffsetCurve(wave, 1.0, gp_Dir(0, 0, 1));
        const double length = overSpans(*wave, [&](double t) { return curve->DN(t, 1).Magnitude(); });
        EXPECT_TRUE(Part::MassProperties::needsAdaptive(face));
        EXPECT_LT(relativeError(Part::MassProperties::area(face), 10 * length), 1e-9);
    }
    {
        // The region between the cylinder r = 5 and the wave x = 10 + 1.5 (1 - cos(2 pi y / 20)),
        // turned about the y axis: volume pi times the integral of (x^2 - 25) dy, and area the
        // wave's surface, 2 pi times the integral of x ds, the cylinder's 2 pi 5 L and the two
        // rings pi (10^2 - 5^2) at its ends
        SCOPED_TRACE("revolution");
        const auto profile = waveSpline(500, period, 1.5, 10.0);
        BRepBuilderAPI_MakeWire wire;
        wire.Add(BRepBuilderAPI_MakeEdge(profile).Edge());
        wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(10, 500, 0), gp_Pnt(5, 500, 0)).Edge());
        wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(5, 500, 0), gp_Pnt(5, 0, 0)).Edge());
        wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(5, 0, 0), gp_Pnt(10, 0, 0)).Edge());
        const TopoDS_Face section = BRepBuilderAPI_MakeFace(wire.Wire(), true).Face();
        const TopoDS_Shape solid
            = BRepPrimAPI_MakeRevol(section, gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0))).Shape();
        const double volume = pi * overSpans(*profile, [&](double t) {
                                  return (std::pow(profile->Value(t).X(), 2) - 25)
                                      * profile->DN(t, 1).Y();
                              });
        const double wavy = 2 * pi * overSpans(*profile, [&](double t) {
                                return profile->Value(t).X() * profile->DN(t, 1).Magnitude();
                            });
        const double area = wavy + 2 * pi * 5 * 500 + 2 * pi * (100 - 25);
        EXPECT_TRUE(Part::MassProperties::needsAdaptive(solid));
        EXPECT_GT(relativeError(defaultVolume(solid), volume), 1e-2);
        EXPECT_LT(relativeError(Part::MassProperties::volume(solid), volume), 1e-6);
        EXPECT_LT(relativeError(Part::MassProperties::area(solid), area), 1e-5);
    }
}

// An edge with only a pcurve, here on a plane: the screen reads the pcurve, and the area, which
// OCCT integrates along the pcurves, is right (the default's is off by 0.13 %)
TEST(MassProperties, pcurveAlone)
{
    Handle(TColgp_HArray1OfPnt2d) points = new TColgp_HArray1OfPnt2d(1, 501);
    for (int y = 0; y <= 500; ++y) {
        points->SetValue(y + 1, gp_Pnt2d(1.5 * (1 - std::cos(2 * pi * y / period)), y));
    }
    Geom2dAPI_Interpolate interpolate(points, false, Precision::Confusion());
    interpolate.Perform();
    const Handle(Geom2d_BSplineCurve) wave = interpolate.Curve();
    // The plane z = 0 with u along x and v along y, so the pcurves are the section's own lines
    Handle(Geom_Surface) plane = new Geom_Plane(gp_Pln());
    const gp_Pnt2d corners[] = {{0, 500}, {-5, 500}, {-5, 0}, {0, 0}};
    BRepBuilderAPI_MakeWire wire;
    const TopoDS_Edge spline = BRepBuilderAPI_MakeEdge(wave, plane).Edge();
    wire.Add(spline);
    for (int i = 0; i < 3; ++i) {
        wire.Add(
            BRepBuilderAPI_MakeEdge(GCE2d_MakeSegment(corners[i], corners[i + 1]).Value(), plane).Edge()
        );
    }
    const TopoDS_Face face = BRepBuilderAPI_MakeFace(plane, wire.Wire(), true).Face();
    double first = 0.0;
    double last = 0.0;
    ASSERT_TRUE(BRep_Tool::Curve(spline, first, last).IsNull());
    EXPECT_TRUE(Part::MassProperties::needsAdaptive(face));
    const double area = areaBehind(*wave);
    EXPECT_GT(relativeError(defaultArea(face), area), 1e-4);
    EXPECT_LT(relativeError(Part::MassProperties::area(face), area), 1e-6);
}

// ops#426: a prism over a steep wave (period 10, amplitude 4) of 1000 spans, which Refine's
// orientation step (BRepLib::OrientClosedSolid's classifier) turned inside out, and its reversal:
// both come out outward, the volume positive. Over whole waves the wave's mean is its amplitude
TEST(MassProperties, orientClosedSolidByTheVolumesSign)
{
    const int spans = 1000;
    BRepBuilderAPI_MakeWire wire;
    wire.Add(BRepBuilderAPI_MakeEdge(waveSpline(spans, 10, 4.0)).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, spans, 0), gp_Pnt(-5, spans, 0)).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(-5, spans, 0), gp_Pnt(-5, 0, 0)).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(-5, 0, 0), gp_Pnt(0, 0, 0)).Edge());
    const TopoDS_Face face = BRepBuilderAPI_MakeFace(wire.Wire(), true).Face();
    const TopoDS_Solid prism
        = TopoDS::Solid(BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, 10)).Shape());
    EXPECT_TRUE(Part::MassProperties::needsAdaptive(prism));
    const double expected = 10.0 * (5 + 4) * spans;
    for (bool reversed : {false, true}) {
        SCOPED_TRACE(reversed);
        TopoDS_Solid solid = reversed ? TopoDS::Solid(prism.Reversed()) : prism;
        EXPECT_TRUE(Part::MassProperties::orientClosedSolid(solid));
        EXPECT_EQ(solid.Orientation(), prism.Orientation());
        EXPECT_LT(relativeError(Part::MassProperties::volume(solid), expected), 1e-3);
    }
}

// Shapes the screen passes are oriented by OCCT's classifier, as before
TEST(MassProperties, orientClosedSolidUnscreenedAsOCCT)
{
    for (const TopoDS_Shape& shape : {BRepPrimAPI_MakeBox(20, 10, 5).Shape(), filletedBox()}) {
        // the shape's solid: TopoDS::Solid() of the shape itself threw for one of them
        const TopoDS_Solid solid = TopoDS::Solid(TopExp_Explorer(shape, TopAbs_SOLID).Current());
        EXPECT_FALSE(Part::MassProperties::needsAdaptive(solid));
        for (bool reversed : {false, true}) {
            SCOPED_TRACE(reversed);
            TopoDS_Solid ours = reversed ? TopoDS::Solid(solid.Reversed()) : solid;
            TopoDS_Solid occt = ours;
            EXPECT_EQ(
                Part::MassProperties::orientClosedSolid(ours),
                BRepLib::OrientClosedSolid(occt)
            );
            EXPECT_EQ(ours.Orientation(), occt.Orientation());
            EXPECT_EQ(ours.Orientation(), solid.Orientation());
        }
    }
}

// The centre of the solids, else the faces, else the edges, else the vertices' mean, as
// TopoShape::getCenterOfGravity() chooses; screened like the volumes and areas (the long wave
// prism's and face's centres as in longWavePrismCentreOfMass)
TEST(MassProperties, centreOfMassByDimension)
{
    const double centreX = (1.5 * 1.5 * 1.5 - 25) / (2 * 6.5);
    gp_Pnt centre;
    ASSERT_TRUE(Part::MassProperties::centreOfMass(wavePrism(25), centre));
    EXPECT_NEAR(centre.X(), centreX, 1e-3);
    EXPECT_NEAR(centre.Z(), 5.0, 1e-3);
    ASSERT_TRUE(Part::MassProperties::centreOfMass(waveFace(25), centre));
    EXPECT_NEAR(centre.X(), centreX, 1e-3);
    EXPECT_NEAR(centre.Z(), 0.0, 1e-9);
    ASSERT_TRUE(Part::MassProperties::centreOfMass(
        BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(2, 4, 6)).Edge(),
        centre
    ));
    EXPECT_LT(centre.Distance(gp_Pnt(1, 2, 3)), 1e-12);
    BRep_Builder builder;
    TopoDS_Compound vertices;
    builder.MakeCompound(vertices);
    builder.Add(vertices, BRepBuilderAPI_MakeVertex(gp_Pnt(0, 0, 0)).Vertex());
    builder.Add(vertices, BRepBuilderAPI_MakeVertex(gp_Pnt(2, 4, 6)).Vertex());
    ASSERT_TRUE(Part::MassProperties::centreOfMass(vertices, centre));
    EXPECT_LT(centre.Distance(gp_Pnt(1, 2, 3)), 1e-12);
    EXPECT_FALSE(Part::MassProperties::centreOfMass(TopoDS_Shape(), centre));
}

// forceAdaptive integrates an unscreened shape adaptively, still right; without it, the default
TEST(MassProperties, forceAdaptive)
{
    const TopoDS_Shape box = BRepPrimAPI_MakeBox(20, 10, 5).Shape();
    EXPECT_EQ(Part::MassProperties::volume(box, false), defaultVolume(box));
    EXPECT_EQ(Part::MassProperties::area(box, false), defaultArea(box));
    EXPECT_LT(relativeError(Part::MassProperties::volume(box, true), 1000.0), 1e-9);
    EXPECT_LT(relativeError(Part::MassProperties::area(box, true), 700.0), 1e-9);
    GProp_GProps props;
    Part::MassProperties::volumeProperties(box, props, true);
    EXPECT_LT(props.CentreOfMass().Distance(gp_Pnt(10, 5, 2.5)), 1e-9);
}
