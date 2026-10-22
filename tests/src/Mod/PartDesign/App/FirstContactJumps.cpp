// SPDX-License-Identifier: LGPL-2.1-or-later

// Where first contact jumps for a Revolution up to a face (ops#293 D2, the tracer):
// FirstContact::traceJumps() on designed walls, against the jump curves found independently of the
// tracer: from the wall's own curve (an extruded wall's fold is where its curve's radius is
// extremal, and its free edge is a vertical line), from the wall's level curves across the axis
// (a slanted fold), and from where a trimmed wall's edge crosses its folds.

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <numbers>
#include <vector>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <Geom2d_Line.hxx>
#include <Geom2dAPI_InterCurveCurve.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <GeomAPI_PointsToBSplineSurface.hxx>
#include <gp_Pln.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include <Base/Exception.h>
#include <Mod/PartDesign/App/FirstContactJumps.h>

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

namespace
{

using PartDesign::FirstContact::JumpPiece;
using PartDesign::FirstContact::JumpSource;
using PartDesign::FirstContact::JumpTrace;

// The trace, or a failure naming why it was refused
JumpTrace traceJumps(const TopoDS_Face& face, const TopoDS_Face& profile, const gp_Ax1& axis, double tolerance, double deviation)
{
    try {
        return PartDesign::FirstContact::traceJumps(face, profile, axis, tolerance, deviation);
    }
    catch (const Base::Exception& error) {
        ADD_FAILURE() << "refused: " << error.what();
        return {};
    }
}

constexpr double tolerance = 1e-6;
constexpr double deviation = 5e-7;

double radians(double degrees)
{
    return degrees * std::numbers::pi / 180.0;
}

// A B-spline through polar legs (the radius linear in the angle along each leg) at height z
Handle(Geom_BSplineCurve) polarCurve(
    const std::vector<double>& radii,
    const std::vector<double>& angles,
    double z,
    int perLeg = 60
)
{
    std::vector<gp_Pnt> points;
    for (std::size_t leg = 0; leg + 1 < radii.size(); ++leg) {
        const bool last = leg + 2 == radii.size();
        for (int k = 0; k < perLeg + (last ? 1 : 0); ++k) {
            const double s = static_cast<double>(k) / perLeg;
            const double radius = radii[leg] + (radii[leg + 1] - radii[leg]) * s;
            const double angle = radians(angles[leg] + (angles[leg + 1] - angles[leg]) * s);
            points.emplace_back(radius * std::cos(angle), radius * std::sin(angle), z);
        }
    }
    Handle(TColgp_HArray1OfPnt) through = new TColgp_HArray1OfPnt(1, static_cast<int>(points.size()));
    for (std::size_t i = 0; i < points.size(); ++i) {
        through->SetValue(static_cast<int>(i) + 1, points[i]);
    }
    GeomAPI_Interpolate interpolation(through, Standard_False, 1e-9);
    interpolation.Perform();
    return interpolation.Curve();
}

TopoDS_Face extruded(const Handle(Geom_BSplineCurve)& curve, double height = 4.0)
{
    const TopoDS_Shape prism
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeEdge(curve).Edge(), gp_Vec(0, 0, height)).Shape();
    return TopoDS::Face(TopExp_Explorer(prism, TopAbs_FACE).Current());
}

// q18's fold: out to r 1.65 (100 to 120 degrees), back in to 1.46 (to 200), out to 3.5 (to 220),
// from z = -1, 4 high
Handle(Geom_BSplineCurve) foldCurve()
{
    return polarCurve({0.5, 1.65, 1.46, 3.5}, {100, 120, 200, 220}, -1.0);
}

// The profile x in [1, 3], z in [0, 2] on the XZ plane
TopoDS_Face profile()
{
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(1, 0, 0),
        gp_Pnt(3, 0, 0),
        gp_Pnt(3, 0, 2),
        gp_Pnt(1, 0, 2),
        Standard_True
    );
    return BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
}

const gp_Ax1 forward(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1));
const gp_Ax1 reversed(gp_Pnt(0, 0, 0), gp_Dir(0, 0, -1));

// The parameter at which a curve's distance from the Z axis is extremal among its points at
// angles from `low` to `high` degrees about it: sampled finely, then refined by golden section
double extremum(const Handle(Geom_BSplineCurve)& curve, double low, double high, bool largest)
{
    auto angle = [&](double t) {
        const gp_Pnt point = curve->Value(t);
        const double degrees = std::atan2(point.Y(), point.X()) * 180.0 / std::numbers::pi;
        return degrees < 0.0 ? degrees + 360.0 : degrees;
    };
    auto radius = [&](double t) {
        const gp_Pnt point = curve->Value(t);
        return std::hypot(point.X(), point.Y());
    };
    const double first = curve->FirstParameter();
    const double last = curve->LastParameter();
    constexpr int samples = 20000;
    double best = 0.0;
    double bestValue = largest ? -1.0 : 1e9;
    for (int i = 0; i <= samples; ++i) {
        const double t = first + (last - first) * i / samples;
        const double r = radius(t);
        const double a = angle(t);
        if (a >= low && a <= high && (largest ? r > bestValue : r < bestValue)) {
            best = t;
            bestValue = r;
        }
    }
    double a = std::max(first, best - (last - first) / samples);
    double b = std::min(last, best + (last - first) / samples);
    const double ratio = (std::sqrt(5.0) - 1.0) / 2.0;
    for (int step = 0; step < 200 && b - a > 1e-15; ++step) {
        const double c = b - ratio * (b - a);
        const double d = a + ratio * (b - a);
        const bool keepLow = largest ? radius(c) > radius(d) : radius(c) < radius(d);
        (keepLow ? b : a) = keepLow ? d : c;
    }
    return (a + b) / 2.0;
}

// The extremal radius itself
double extremalRadius(const Handle(Geom_BSplineCurve)& curve, double low, double high, bool largest)
{
    const gp_Pnt point = curve->Value(extremum(curve, low, high, largest));
    return std::hypot(point.X(), point.Y());
}

std::vector<const JumpPiece*> kept(const JumpTrace& trace)
{
    std::vector<const JumpPiece*> result;
    for (const JumpPiece& piece : trace.pieces) {
        if (piece.meetsProfile && piece.jumps) {
            result.push_back(&piece);
        }
    }
    return result;
}

// The radial component of the normal pointing to the piece's side, at its middle point
double sideRadially(const JumpPiece& piece)
{
    const std::size_t k = piece.points.size() / 2;
    const gp_Pnt2d& a = piece.points[k > 0 ? k - 1 : 0];
    const gp_Pnt2d& b = piece.points[std::min(k + 1, piece.points.size() - 1)];
    // The left normal of (b - a) is (-(b - a).y, (b - a).x)
    return -(b.Y() - a.Y()) * piece.side;
}

// The fitted curve's radius at height y in the frame, or NaN
double radiusAt(const JumpPiece& piece, double y)
{
    Handle(Geom2d_Line) line = new Geom2d_Line(gp_Pnt2d(0, y), gp_Dir2d(1, 0));
    Geom2dAPI_InterCurveCurve intersection(piece.curve, line, 1e-12);
    for (int i = 1; i <= intersection.NbPoints(); ++i) {
        const gp_Pnt2d point = intersection.Point(i);
        return point.X();
    }
    return std::nan("");
}

// Every fitted point between first and last is at the given radius
void expectAtRadius(const JumpPiece& piece, double radius, double within)
{
    for (const gp_Pnt2d& point : piece.points) {
        EXPECT_NEAR(point.X(), radius, within);
    }
    for (int i = 0; i <= 50; ++i) {
        const double t = piece.first + (piece.last - piece.first) * i / 50;
        EXPECT_NEAR(piece.curve->Value(t).X(), radius, deviation + within);
    }
}

}  // namespace

// The hook: from r 2 at 100 degrees in to r 0.5 (130) and out to 3.5 (220), extruded. Circles
// inside r 2 meet its first leg near 100 to 130 degrees, those outside only its second leg past
// 160: first contact jumps along the free edge's image, the vertical line r = 2. The edge lies in
// a half-plane through the axis, so its image is the edge turned into the profile's plane,
// exactly, and the face lies inside r = 2 next to it.
TEST(FirstContactJumps, HookEdge)
{
    const TopoDS_Face face = extruded(polarCurve({2.0, 0.5, 3.5}, {100, 130, 220}, -1.0));
    const JumpTrace trace = traceJumps(face, profile(), forward, tolerance, deviation);
    const std::vector<const JumpPiece*> walls = kept(trace);
    ASSERT_EQ(walls.size(), 1U);
    const JumpPiece& wall = *walls.front();
    EXPECT_EQ(wall.source, JumpSource::Edge);
    EXPECT_TRUE(wall.exact);
    expectAtRadius(wall, 2.0, 1e-9);
    double low = 1e9;
    double high = -1e9;
    for (const gp_Pnt2d& point : wall.points) {
        low = std::min(low, point.Y());
        high = std::max(high, point.Y());
    }
    EXPECT_LE(low, 0.0);
    EXPECT_GE(high, 2.0);
    EXPECT_LT(sideRadially(wall), 0.0);
}

// q18's fold turning forward: circles of radius below the curve's largest radius near 120
// degrees meet it there; those above it pass and meet its third leg past 200. First contact
// jumps along the image of the fold at that radius, and the face lies inside it. The fold at the
// smallest radius near 200 degrees lies behind the first leg: no jump.
TEST(FirstContactJumps, FoldForward)
{
    const Handle(Geom_BSplineCurve) curve = foldCurve();
    const double outer = extremalRadius(curve, 105.0, 160.0, true);
    const double inner = extremalRadius(curve, 160.0, 215.0, false);
    const JumpTrace trace = traceJumps(extruded(curve), profile(), forward, tolerance, deviation);
    const std::vector<const JumpPiece*> walls = kept(trace);
    ASSERT_EQ(walls.size(), 1U);
    EXPECT_EQ(walls.front()->source, JumpSource::Silhouette);
    expectAtRadius(*walls.front(), outer, 1e-9);
    EXPECT_LT(sideRadially(*walls.front()), 0.0);
    // The other fold is traced, and pruned
    const bool innerTraced = std::ranges::any_of(trace.pieces, [&](const JumpPiece& piece) {
        return piece.source == JumpSource::Silhouette && piece.meetsProfile && !piece.jumps
            && std::abs(piece.points.front().X() - inner) < 1e-6;
    });
    EXPECT_TRUE(innerTraced);
}

// The same fold turning the other way: the third leg comes first for circles outside the
// smallest radius near 200 degrees, and those inside pass it and meet the first leg: the jump is
// along that fold, with the face outside it.
TEST(FirstContactJumps, FoldReversed)
{
    const Handle(Geom_BSplineCurve) curve = foldCurve();
    const double inner = extremalRadius(curve, 160.0, 215.0, false);
    const JumpTrace trace = traceJumps(extruded(curve), profile(), reversed, tolerance, deviation);
    const std::vector<const JumpPiece*> walls = kept(trace);
    ASSERT_EQ(walls.size(), 1U);
    EXPECT_EQ(walls.front()->source, JumpSource::Silhouette);
    expectAtRadius(*walls.front(), inner, 1e-9);
    EXPECT_GT(sideRadially(*walls.front()), 0.0);
}

// The fold with its radii scaled by 1 + 0.1 z, a B-spline surface through 17 rows: its fold's image
// is a slanted curve, near r = 1.65 (1 + 0.1 z). At each height the jump lies where the surface's
// level curve Z = z is farthest from the axis there (circles about the axis touch it), which the
// fitted curve must give within its deviation. The level curve is followed on the surface itself
// (Newton in u for each v): OCCT's section by the plane is an approximation whose radial error here
// (up to 7.5e-5) its edges' tolerances don't bound and which differs between platforms (macOS arm64
// missed the fold by 2.5e-5 at z = 1.4, with a tolerance of 1e-5).
TEST(FirstContactJumps, SlantedFold)
{
    TColgp_Array2OfPnt rows(1, 17, 1, 121);
    for (int j = 1; j <= 17; ++j) {
        const double z = -1.0 + 4.0 * (j - 1) / 16;
        const double scale = 1.0 + 0.1 * z;
        const Handle(Geom_BSplineCurve) row
            = polarCurve({0.5 * scale, 1.65 * scale, 1.46 * scale, 3.5 * scale}, {100, 120, 200, 220}, z, 40);
        for (int i = 1; i <= 121; ++i) {
            const double t = row->FirstParameter()
                + (row->LastParameter() - row->FirstParameter()) * (i - 1) / 120;
            rows(j, i) = row->Value(t);
        }
    }
    GeomAPI_PointsToBSplineSurface interpolation;
    interpolation.Interpolate(rows);
    const Handle(Geom_BSplineSurface) surface = interpolation.Surface();
    const TopoDS_Face face = BRepBuilderAPI_MakeFace(surface, 1e-7).Face();
    const JumpTrace trace = traceJumps(face, profile(), forward, tolerance, deviation);
    const std::vector<const JumpPiece*> walls = kept(trace);
    ASSERT_EQ(walls.size(), 1U);
    EXPECT_EQ(walls.front()->source, JumpSource::Silhouette);
    EXPECT_LT(sideRadially(*walls.front()), 0.0);
    double u1 {};
    double u2 {};
    double v1 {};
    double v2 {};
    surface->Bounds(u1, u2, v1, v2);
    for (double z : {0.1, 0.6, 1.0, 1.4, 1.9}) {
        // The rows run along u, so the level curve has one point per v
        const double start = u1 + (u2 - u1) * (z + 1.0) / 4.0;
        auto onLevel = [&](double v) {
            double u = start;
            for (int step = 0; step < 60; ++step) {
                gp_Pnt point;
                gp_Vec du;
                gp_Vec dv;
                surface->D1(u, v, point, du, dv);
                const double change = (point.Z() - z) / du.Z();
                u -= change;
                if (std::abs(change) < 1e-15) {
                    break;
                }
            }
            return surface->Value(u, v);
        };
        auto radius = [&](double v) {
            const gp_Pnt point = onLevel(v);
            return std::hypot(point.X(), point.Y());
        };
        const double around = 1.65 * (1.0 + 0.1 * z);
        double best = v1;
        double bestValue = -1.0;
        for (int i = 0; i <= 20000; ++i) {
            const double v = v1 + (v2 - v1) * i / 20000;
            const gp_Pnt point = onLevel(v);
            const double r = std::hypot(point.X(), point.Y());
            double degrees = std::atan2(point.Y(), point.X()) * 180.0 / std::numbers::pi;
            degrees += degrees < 0.0 ? 360.0 : 0.0;
            // The fold near 120 degrees, not the third leg passing the same radii
            if (degrees > 105.0 && degrees < 160.0 && std::abs(r - around) < 0.1 && r > bestValue) {
                best = v;
                bestValue = r;
            }
        }
        ASSERT_GT(bestValue, 0.0) << z;
        double a = std::max(v1, best - (v2 - v1) / 20000);
        double b = std::min(v2, best + (v2 - v1) / 20000);
        const double ratio = (std::sqrt(5.0) - 1.0) / 2.0;
        for (int step = 0; step < 200 && b - a > 1e-15; ++step) {
            const double c = b - ratio * (b - a);
            const double d = a + ratio * (b - a);
            const bool keepLow = radius(c) > radius(d);
            (keepLow ? b : a) = keepLow ? d : c;
        }
        const gp_Pnt farthest = onLevel((a + b) / 2.0);
        ASSERT_NEAR(farthest.Z(), z, 1e-12);
        const double exact = std::hypot(farthest.X(), farthest.Y());
        EXPECT_NEAR(radiusAt(*walls.front(), z), exact, deviation) << z;
    }
}

// q18's fold below the plane z = 1 - 0.12 x - 0.2 y: the wall's top edge crosses both folds
// inside the profile's turn, and there F's image changes sides along the edge's image (an edge
// crossing the silhouette). The edge's image is split exactly there: at the folds' radii, at the
// plane's height above the curve's extremal points. The fold's own image ends on the edge's.
TEST(FirstContactJumps, SideFlipsWhereTheEdgeCrossesTheFolds)
{
    const Handle(Geom_BSplineCurve) curve = foldCurve();
    const gp_Dir up(0.12, 0.2, 1.0);
    const TopoDS_Face slabBase
        = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 1), up), -40, 40, -40, 40).Face();
    const TopoDS_Shape slab = BRepPrimAPI_MakePrism(slabBase, gp_Vec(up) * 30.0).Shape();
    const TopoDS_Shape cut = BRepAlgoAPI_Cut(extruded(curve), slab).Shape();
    TopExp_Explorer faces(cut, TopAbs_FACE);
    ASSERT_TRUE(faces.More());
    const TopoDS_Face face = TopoDS::Face(faces.Current());
    faces.Next();
    ASSERT_FALSE(faces.More());
    // The top edge: the only one that isn't a line
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(face, TopAbs_EDGE, edges);
    int top = 0;
    for (int i = 1; i <= edges.Extent(); ++i) {
        BRepAdaptor_Curve along(TopoDS::Edge(edges(i)));
        const gp_Pnt middle = along.Value((along.FirstParameter() + along.LastParameter()) / 2.0);
        if (along.GetType() != GeomAbs_Line && middle.Z() > -0.5) {
            top = i;
        }
    }
    ASSERT_GT(top, 0);
    // The points of the curve at its extremal radii, and the plane's height above them
    std::vector<gp_Pnt2d> crossings;
    for (const auto& [low, high, largest] : {std::tuple {105.0, 160.0, true}, std::tuple {160.0, 215.0, false}}) {
        const gp_Pnt point = curve->Value(extremum(curve, low, high, largest));
        crossings.emplace_back(
            std::hypot(point.X(), point.Y()),
            1.0 - 0.12 * point.X() - 0.2 * point.Y()
        );
    }
    const JumpTrace trace = traceJumps(face, profile(), forward, tolerance, deviation);
    std::vector<gp_Pnt2d> flips;
    for (const JumpPiece& piece : trace.pieces) {
        if (piece.source == JumpSource::Edge && piece.edge == top && piece.continuesPrevious) {
            flips.push_back(piece.points.front());
        }
    }
    ASSERT_EQ(flips.size(), 2U);
    for (const gp_Pnt2d& expected : crossings) {
        const bool found = std::ranges::any_of(flips, [&](const gp_Pnt2d& flip) {
            return flip.Distance(expected) < 1e-5;
        });
        EXPECT_TRUE(found) << expected.X() << " " << expected.Y();
    }
    // Sides alternate along the edge
    int previous = 0;
    for (const JumpPiece& piece : trace.pieces) {
        if (piece.source == JumpSource::Edge && piece.edge == top) {
            if (piece.continuesPrevious) {
                EXPECT_EQ(piece.side, -previous);
            }
            previous = piece.side;
        }
    }
    // The outer fold's image runs up to the edge's, ending at the crossing
    const bool ends = std::ranges::any_of(trace.pieces, [&](const JumpPiece& piece) {
        if (piece.source != JumpSource::Silhouette || std::abs(piece.points.front().X() - crossings[0].X()) > 1e-6) {
            return false;
        }
        return piece.points.front().Distance(crossings[0]) < 1e-5
            || piece.points.back().Distance(crossings[0]) < 1e-5;
    });
    EXPECT_TRUE(ends);
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
