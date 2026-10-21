// SPDX-License-Identifier: LGPL-2.1-or-later

// The solid up to a face where first contact jumps (ops#293 D2, the construction):
// FirstContact::constructFirstContact() on designed walls, against the volume first contact gives,
// integrated from the wall's own curve: a circle of radius r about the axis first meets an
// extruded wall at the smallest angle, from the profile's plane in the turning direction, where the
// wall's curve has radius r; a wall trimmed by a plane holds that point only below the plane.

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <numbers>
#include <optional>
#include <string>
#include <vector>

#include <BRep_TEdge.hxx>
#include <BRep_Tool.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepTools.hxx>
#include <GCE2d_MakeSegment.hxx>
#include <Geom2d_Circle.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Geom2dConvert.hxx>
#include <Geom_BSplineCurve.hxx>
#include <GeomAPI.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <GProp_GProps.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax2d.hxx>
#include <gp_Ax3.hxx>
#include <gp_Pln.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>

#include <Base/Exception.h>
#include <Mod/PartDesign/App/FirstContactConstruction.h>

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

namespace
{

using PartDesign::FirstContact::FirstContactSolid;

constexpr double tolerance = 1e-6;

double radians(double degrees)
{
    return degrees * std::numbers::pi / 180.0;
}

// A B-spline through polar legs (the radius linear in the angle along each leg) at height z
Handle(Geom_BSplineCurve) polarCurve(const std::vector<double>& radii, const std::vector<double>& angles, double z)
{
    constexpr int perLeg = 60;
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

Handle(Geom_BSplineCurve) hookCurve()
{
    return polarCurve({2.0, 0.5, 3.5}, {100, 130, 220}, -1.0);
}

// q18's fold: out to r 1.65 (100 to 120 degrees), back in to 1.46 (to 200), out to 3.5 (to 220)
Handle(Geom_BSplineCurve) foldCurve()
{
    return polarCurve({0.5, 1.65, 1.46, 3.5}, {100, 120, 200, 220}, -1.0);
}

// The profile x in [x0, x1], z in [z0, z1] on the XZ plane
TopoDS_Face profile(double x0 = 1.0, double x1 = 3.0, double z0 = 0.0, double z1 = 2.0)
{
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(x0, 0, z0),
        gp_Pnt(x1, 0, z0),
        gp_Pnt(x1, 0, z1),
        gp_Pnt(x0, 0, z1),
        Standard_True
    );
    return BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
}

const gp_Ax1 forward(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1));
// The trace's frame for `forward`: x radial in y = 0, y along the axis
const gp_Ax2 frame(gp_Pnt(0, 0, 0), gp_Dir(0, -1, 0), gp_Dir(1, 0, 0));
const gp_Ax1 reversed(gp_Pnt(0, 0, 0), gp_Dir(0, 0, -1));

// Where a circle of radius r about the Z axis crosses the wall's curve (seen from above): the
// points, and their angles from the XZ plane's +X side in the turning direction
class Crossings
{
public:
    Crossings(const Handle(Geom_BSplineCurve)& curve, bool turningForward)
        : curve(curve)
        , turningForward(turningForward)
    {
        constexpr int samples = 20000;
        for (int i = 0; i <= samples; ++i) {
            const double t = curve->FirstParameter()
                + (curve->LastParameter() - curve->FirstParameter()) * i / samples;
            parameters.push_back(t);
            radii.push_back(radius(t));
        }
    }

    struct Crossing
    {
        double angle;
        gp_Pnt point;
    };

    std::vector<Crossing> at(double r) const
    {
        std::vector<Crossing> result;
        for (std::size_t i = 0; i + 1 < parameters.size(); ++i) {
            if ((radii[i] - r) * (radii[i + 1] - r) > 0.0 || radii[i] == radii[i + 1]) {
                continue;
            }
            double a = parameters[i];
            double b = parameters[i + 1];
            const bool rising = radii[i + 1] > radii[i];
            for (int step = 0; step < 80; ++step) {
                const double c = (a + b) / 2.0;
                ((radius(c) < r) == rising ? a : b) = c;
            }
            const gp_Pnt point = curve->Value((a + b) / 2.0);
            double angle = std::atan2(point.Y(), point.X());
            angle += angle < 0.0 ? 2.0 * std::numbers::pi : 0.0;
            if (!turningForward) {
                angle = 2.0 * std::numbers::pi - angle;
            }
            result.push_back({angle, point});
        }
        return result;
    }

private:
    double radius(double t) const
    {
        const gp_Pnt point = curve->Value(t);
        return std::hypot(point.X(), point.Y());
    }

    Handle(Geom_BSplineCurve) curve;
    bool turningForward;
    std::vector<double> parameters;
    std::vector<double> radii;
};

// The integral of f over [a, b], Gauss-Legendre with 8 points on each of `pieces` parts, the
// parts split at `breaks`
double integral(const std::function<double(double)>& f, double a, double b, std::vector<double> breaks, int pieces)
{
    static const double nodes[] = {-0.9602898564975363, -0.7966664774136267, -0.5255324099163290,
                                   -0.1834346424956498, 0.1834346424956498,  0.5255324099163290,
                                   0.7966664774136267,  0.9602898564975363};
    static const double weights[] = {0.1012285362903763, 0.2223810344533745, 0.3137066458778873,
                                     0.3626837833783620, 0.3626837833783620, 0.3137066458778873,
                                     0.2223810344533745, 0.1012285362903763};
    breaks.push_back(a);
    breaks.push_back(b);
    std::ranges::sort(breaks);
    double sum = 0.0;
    for (std::size_t k = 0; k + 1 < breaks.size(); ++k) {
        const double low = std::max(a, breaks[k]);
        const double high = std::min(b, breaks[k + 1]);
        if (high <= low) {
            continue;
        }
        const double step = (high - low) / pieces;
        for (int i = 0; i < pieces; ++i) {
            const double middle = low + step * (i + 0.5);
            for (int j = 0; j < 8; ++j) {
                sum += weights[j] * step / 2.0 * f(middle + nodes[j] * step / 2.0);
            }
        }
    }
    return sum;
}

// The volume first contact gives for the profile [x0, x1] x [z0, z1] and an extruded wall
double extrudedVolume(const Crossings& crossings, double x0, double x1, double z0, double z1, std::vector<double> breaks)
{
    auto swept = [&](double r) {
        double first = 2.0 * std::numbers::pi;
        for (const auto& crossing : crossings.at(r)) {
            first = std::min(first, crossing.angle);
        }
        return first * r;
    };
    return (z1 - z0) * integral(swept, x0, x1, std::move(breaks), 64);
}

// The largest or smallest radius of a curve between two angles (degrees, counterclockwise)
double extremalRadius(const Handle(Geom_BSplineCurve)& curve, double low, double high, bool largest)
{
    constexpr int samples = 20000;
    double best = largest ? 0.0 : 1e9;
    double bestT = 0.0;
    auto radius = [&](double t) {
        const gp_Pnt point = curve->Value(t);
        return std::hypot(point.X(), point.Y());
    };
    const double first = curve->FirstParameter();
    const double last = curve->LastParameter();
    for (int i = 0; i <= samples; ++i) {
        const double t = first + (last - first) * i / samples;
        const gp_Pnt point = curve->Value(t);
        double degrees = std::atan2(point.Y(), point.X()) * 180.0 / std::numbers::pi;
        degrees += degrees < 0.0 ? 360.0 : 0.0;
        if (degrees >= low && degrees <= high && (largest ? radius(t) > best : radius(t) < best)) {
            best = radius(t);
            bestT = t;
        }
    }
    double a = std::max(first, bestT - (last - first) / samples);
    double b = std::min(last, bestT + (last - first) / samples);
    const double ratio = (std::sqrt(5.0) - 1.0) / 2.0;
    for (int step = 0; step < 200 && b - a > 1e-15; ++step) {
        const double c = b - ratio * (b - a);
        const double d = a + ratio * (b - a);
        const bool keepLow = largest ? radius(c) > radius(d) : radius(c) < radius(d);
        (keepLow ? b : a) = keepLow ? d : c;
    }
    return radius((a + b) / 2.0);
}

// The tolerances of a shape's vertices, edges and faces, and with `curves` the count of each
// edge's curves (a destructive boolean raises its arguments' tolerances in place and adds pcurves
// to their edges)
std::vector<double> state(const TopoDS_Shape& shape, bool curves)
{
    std::vector<double> values;
    for (const TopAbs_ShapeEnum type : {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE}) {
        TopTools_IndexedMapOfShape map;
        TopExp::MapShapes(shape, type, map);
        for (int k = 1; k <= map.Extent(); ++k) {
            const TopoDS_Shape& sub = map(k);
            if (type == TopAbs_VERTEX) {
                values.push_back(BRep_Tool::Tolerance(TopoDS::Vertex(sub)));
            }
            else if (type == TopAbs_EDGE) {
                values.push_back(BRep_Tool::Tolerance(TopoDS::Edge(sub)));
                if (curves) {
                    values.push_back(Handle(BRep_TEdge)::DownCast(sub.TShape())->Curves().Extent());
                }
            }
            else {
                values.push_back(BRep_Tool::Tolerance(TopoDS::Face(sub)));
            }
        }
    }
    return values;
}

// The construction, or a failure naming why it refused. It leaves its inputs alone: the up-to
// face, the user's, keeps every tolerance and curve over all cells and builds, and the profile
// its tolerances (the cells' turns add pcurves to its edges, as today's turn of the profile does).
std::optional<FirstContactSolid> construct(const TopoDS_Face& face, const TopoDS_Face& profile, const gp_Ax1& axis)
{
    const std::vector<double> faceBefore = state(face, true);
    const std::vector<double> profileBefore = state(profile, false);
    struct Check
    {
        const TopoDS_Face& face;
        const TopoDS_Face& profile;
        const std::vector<double>& faceBefore;
        const std::vector<double>& profileBefore;
        ~Check()
        {
            EXPECT_EQ(state(face, true), faceBefore) << "the construction changed the up-to face";
            EXPECT_EQ(state(profile, false), profileBefore) << "the construction changed the profile";
        }
    } check {face, profile, faceBefore, profileBefore};
    try {
        return PartDesign::FirstContact::constructFirstContact(face, profile, axis, tolerance);
    }
    catch (const Base::Exception& error) {
        ADD_FAILURE() << "refused: " << error.what();
        return std::nullopt;
    }
}

double volume(const TopoDS_Shape& shape)
{
    GProp_GProps properties;
    // Gauss-Kronrod over the spans: the adaptive VolumeProperties() was 3e-4 off on these solids
    BRepGProp::VolumePropertiesGK(shape, properties, 1e-9, Standard_True, Standard_True);
    return properties.Mass();
}

int solids(const TopoDS_Shape& shape)
{
    int count = 0;
    for (TopExp_Explorer explorer(shape, TopAbs_SOLID); explorer.More(); explorer.Next()) {
        ++count;
    }
    return count;
}

// One valid solid of the expected volume: the walls' pushes and the booleans' tolerance make up
// the difference (section 15.2: 1.4e-5 on the hook at the first push)
void expectSolid(const FirstContactSolid& solid, double expected)
{
    EXPECT_TRUE(BRepCheck_Analyzer(solid.shape).IsValid());
    EXPECT_EQ(solids(solid.shape), 1);
    EXPECT_NEAR(volume(solid.shape), expected, 1e-5 * expected);
}

}  // namespace

// The hook: from r 2 at 100 degrees in to r 0.5 (130) and out to 3.5 (220), extruded. Circles
// inside r 2 meet its first leg, those outside only its second leg, half a turn later.
TEST(FirstContactConstruction, Hook)
{
    const Handle(Geom_BSplineCurve) curve = hookCurve();
    const auto solid = construct(extruded(curve), profile(), forward);
    ASSERT_TRUE(solid);
    EXPECT_EQ(solid->walls.size(), 1U);
    EXPECT_EQ(solid->cells.size(), 2U);
    // A section edge at the profile's top lies on the wall with a tolerance of 5e-6, wider than
    // the first push's band (2e-6): it can't be certified there, and the wall is raised once
    EXPECT_EQ(solid->builds, 2);
    expectSolid(*solid, extrudedVolume(Crossings(curve, true), 1.0, 3.0, 0.0, 2.0, {2.0}));
}

// q18's fold, turning forward: the jump is along the fold at the curve's largest radius near 120
// degrees; the fold at its smallest radius near 200 lies behind the first leg
TEST(FirstContactConstruction, FoldForward)
{
    const Handle(Geom_BSplineCurve) curve = foldCurve();
    const double outer = extremalRadius(curve, 105.0, 160.0, true);
    const auto solid = construct(extruded(curve), profile(), forward);
    ASSERT_TRUE(solid);
    EXPECT_EQ(solid->walls.size(), 1U);
    EXPECT_EQ(solid->cells.size(), 2U);
    expectSolid(*solid, extrudedVolume(Crossings(curve, true), 1.0, 3.0, 0.0, 2.0, {outer}));
}

// The same fold turning the other way: the jump is along the fold at its smallest radius near 200
TEST(FirstContactConstruction, FoldReversed)
{
    const Handle(Geom_BSplineCurve) curve = foldCurve();
    const double inner = extremalRadius(curve, 160.0, 215.0, false);
    const auto solid = construct(extruded(curve), profile(), reversed);
    ASSERT_TRUE(solid);
    EXPECT_EQ(solid->walls.size(), 1U);
    EXPECT_EQ(solid->cells.size(), 2U);
    expectSolid(*solid, extrudedVolume(Crossings(curve, false), 1.0, 3.0, 0.0, 2.0, {inner}));
}

// q18's fold below the plane z = 1 - 0.12 x - 0.2 y. The profile, x in [1.5, 3] and z in [0, 1.2],
// holds where the wall's top edge crosses the outer fold: below the edge the jump is the fold's,
// above it the edge's. A point of the curve at angle a meets the circle at height z when z lies
// below the plane there, so first contact at (r, z) is the smallest angle of a crossing at radius
// r whose plane height is above z.
TEST(FirstContactConstruction, TrimmedFold)
{
    const Handle(Geom_BSplineCurve) curve = foldCurve();
    const gp_Dir up(0.12, 0.2, 1.0);
    const TopoDS_Face slabBase = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 1), up), -40, 40, -40, 40).Face();
    const TopoDS_Shape slab = BRepPrimAPI_MakePrism(slabBase, gp_Vec(up) * 30.0).Shape();
    const TopoDS_Shape cut = BRepAlgoAPI_Cut(extruded(curve), slab).Shape();
    TopExp_Explorer faces(cut, TopAbs_FACE);
    ASSERT_TRUE(faces.More());
    const TopoDS_Face face = TopoDS::Face(faces.Current());
    const Crossings crossings(curve, true);
    constexpr double z0 = 0.0;
    constexpr double z1 = 1.2;
    auto swept = [&](double r) {
        const std::vector<Crossings::Crossing> all = crossings.at(r);
        // First contact is piecewise constant in z, changing where a crossing's plane height is
        std::vector<double> heights {z0, z1};
        for (const auto& crossing : all) {
            const double height = 1.0 - 0.12 * crossing.point.X() - 0.2 * crossing.point.Y();
            if (height > z0 && height < z1) {
                heights.push_back(height);
            }
        }
        std::ranges::sort(heights);
        double sum = 0.0;
        for (std::size_t k = 0; k + 1 < heights.size(); ++k) {
            const double z = (heights[k] + heights[k + 1]) / 2.0;
            double first = 2.0 * std::numbers::pi;
            for (const auto& crossing : all) {
                if (1.0 - 0.12 * crossing.point.X() - 0.2 * crossing.point.Y() >= z) {
                    first = std::min(first, crossing.angle);
                }
            }
            sum += first * (heights[k + 1] - heights[k]);
        }
        return sum * r;
    };
    const double outer = extremalRadius(curve, 105.0, 160.0, true);
    const double expected = integral(swept, 1.5, 3.0, {outer}, 128);
    // Three walls meeting at the flip in one junction (section 15.10): the fold below the edge,
    // continued by the edge's leg-2 image above it, and the leg-1 image cut where it crosses the
    // fold's wall. Three cells: below the leg-1 image left of the fold, between the edge's two
    // images, and right of the fold and the leg-2 image.
    const auto solid = construct(face, profile(1.5, 3.0, z0, z1), forward);
    ASSERT_TRUE(solid);
    EXPECT_EQ(solid->walls.size(), 3U);
    EXPECT_EQ(solid->cells.size(), 3U);
    // One build: the junction's push covers the edge's tolerance from the start
    EXPECT_EQ(solid->builds, 1);
    expectSolid(*solid, expected);
}

// The lost-sheet check (C2) on a turn deliberately left unsplit, every section edge in a band: the
// hook extruded from z 0.5 to 1.5 only, so its top and bottom are its own edges and the face cuts
// the turn's cylinders only, which the band covers as if they were walls.
namespace
{

// The profile's turn, F's section edges with it, and the check's verdict with that band
std::string unsplitTurn(double x0, double x1)
{
    const TopoDS_Face face = extruded(polarCurve({2.0, 0.5, 3.5}, {100, 130, 220}, 0.5), 1.0);
    const TopoDS_Shape turn = BRepPrimAPI_MakeRevol(profile(x0, x1, 0.0, 2.0), forward, 2.0 * std::numbers::pi - 1e-3).Shape();
    BRepAlgoAPI_Section section(turn, face);
    TopTools_IndexedMapOfShape sections;
    for (TopExp_Explorer edges(section.Shape(), TopAbs_EDGE); edges.More(); edges.Next()) {
        sections.Add(edges.Current());
    }
    // The check needs those edges in the solid: the turn split by its own section edges
    BRepAlgoAPI_Splitter splitter;
    TopTools_ListOfShape arguments;
    arguments.Append(turn);
    TopTools_ListOfShape tools;
    for (int k = 1; k <= sections.Extent(); ++k) {
        tools.Append(sections.FindKey(k));
    }
    splitter.SetArguments(arguments);
    splitter.SetTools(tools);
    splitter.Build();
    TopTools_IndexedMapOfShape cut;
    for (int k = 1; k <= sections.Extent(); ++k) {
        for (const TopoDS_Shape& edge : splitter.Modified(sections.FindKey(k))) {
            cut.Add(edge);
        }
        if (splitter.Modified(sections.FindKey(k)).IsEmpty()) {
            cut.Add(sections.FindKey(k));
        }
    }
    // As if the turn's cylinders were walls at r 2 and 2.5
    PartDesign::FirstContact::Band band(frame);
    band.add(GCE2d_MakeSegment(gp_Pnt2d(2.0, -1.0), gp_Pnt2d(2.0, 3.0)).Value(), 3e-4);
    band.add(GCE2d_MakeSegment(gp_Pnt2d(2.5, -1.0), gp_Pnt2d(2.5, 3.0)).Value(), 3e-4);
    const TopoDS_Shape solid = TopExp_Explorer(splitter.Shape(), TopAbs_SOLID).Current();
    return PartDesign::FirstContact::lostSheet(solid, face, cut, {}, band, 1e-3, tolerance);
}

// An edge in the half-plane y = 0 whose image waves about the wall r = 2 with `amplitude`, 16 waves
// over its height of 1; the waves' nodes fall near the band's first samples (every eighth of the
// curve), so a check by samples alone sees the image on the wall
TopoDS_Edge wave(double amplitude)
{
    constexpr int count = 257;
    Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, count);
    for (int k = 0; k < count; ++k) {
        const double s = static_cast<double>(k) / (count - 1);
        points->SetValue(k + 1, gp_Pnt(2.0 + amplitude * std::sin(32.0 * std::numbers::pi * s), 0.0, s));
    }
    GeomAPI_Interpolate interpolate(points, false, 1e-9);
    interpolate.Perform();
    return BRepBuilderAPI_MakeEdge(interpolate.Curve()).Edge();
}

PartDesign::FirstContact::Band waveBand()
{
    PartDesign::FirstContact::Band band(frame);
    band.add(GCE2d_MakeSegment(gp_Pnt2d(2.0, -1.0), gp_Pnt2d(2.0, 2.0)).Value(), 2e-6);
    return band;
}

// The plane x = 2 over y in [-half, half], z in [0, 1]: its silhouette is the line y = 0, where
// the circles about z touch it, and its image is r in [2, sqrt(4 + half^2)]
TopoDS_Face tangentPlane(double half)
{
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(2.0, -half, 0.0),
        gp_Pnt(2.0, half, 0.0),
        gp_Pnt(2.0, half, 1.0),
        gp_Pnt(2.0, -half, 1.0),
        Standard_True
    );
    return BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
}

}  // namespace

// A wide turn, x in [2.0001, 2.4999]: the second leg crosses it at about 175 degrees, unsplit
TEST(FirstContactConstruction, LostSheetSeen)
{
    const std::string why = unsplitTurn(2.0001, 2.4999);
    EXPECT_NE(why.find("runs through the cell's piece unsplit"), std::string::npos) << why;
}

// A sliver turn about the free edge's radius, x in [1.9999, 2.0001]: the face's material through
// its section edges leaves the turn before it leaves the band
TEST(FirstContactConstruction, DroppedFlapPasses)
{
    EXPECT_EQ(unsplitTurn(1.9999, 2.0001), "");
}

// The band's curve bound (section 15.8): a wave of 1e-5 about the wall leaves the band of 2e-6
// between the samples where it crosses the wall; one of 1e-7 stays in it, with the edge's
// tolerance
TEST(FirstContactConstruction, BandFindsWaveBetweenSamples)
{
    const auto out = waveBand().outside(wave(1e-5));
    ASSERT_TRUE(out.has_value());
    EXPECT_GT(std::fabs(std::hypot(out->X(), out->Y()) - 2.0), 1.8e-6);
}

TEST(FirstContactConstruction, BandHoldsSmallWave)
{
    const auto band = waveBand();
    EXPECT_FALSE(band.outside(wave(1e-7)).has_value());
    EXPECT_TRUE(band.contains(gp_Pnt(2.0 + 1.9e-6, 0.0, 0.5)));
    EXPECT_FALSE(band.contains(gp_Pnt(2.0 + 2.1e-6, 0.0, 0.5)));
}

// The band's face bound (section 15.8, 2b): a band shaped as a C about the tangent plane's image,
// open at r = 2, holds the images of all four of its edges but not its silhouette's
TEST(FirstContactConstruction, BandFindsSilhouetteOut)
{
    const TopoDS_Face face = tangentPlane(0.5);
    const double outer = std::sqrt(4.25);
    PartDesign::FirstContact::Band band(frame);
    band.add(GCE2d_MakeSegment(gp_Pnt2d(outer, -0.1), gp_Pnt2d(outer, 1.1)).Value(), 1e-3);
    band.add(GCE2d_MakeSegment(gp_Pnt2d(1.99, 0.0), gp_Pnt2d(outer + 0.01, 0.0)).Value(), 1e-3);
    band.add(GCE2d_MakeSegment(gp_Pnt2d(1.99, 1.0), gp_Pnt2d(outer + 0.01, 1.0)).Value(), 1e-3);
    for (TopExp_Explorer edges(face, TopAbs_EDGE); edges.More(); edges.Next()) {
        EXPECT_FALSE(band.outside(TopoDS::Edge(edges.Current())).has_value());
    }
    const auto out = band.outside(face);
    ASSERT_TRUE(out.has_value());
    EXPECT_NEAR(std::hypot(out->X(), out->Y()), 2.0, 1e-9);
    EXPECT_GT(out->Z(), 1e-3);
    EXPECT_LT(out->Z(), 1.0 - 1e-3);
}

// A strip of the tangent plane 2e-3 wide maps within 2.5e-7 of r = 2: certified in a band of 2e-6
TEST(FirstContactConstruction, BandHoldsSilhouette)
{
    EXPECT_FALSE(waveBand().outside(tangentPlane(1e-3)).has_value());
}

// The band's nearest point over a wall of many spans, found among the spans whose pole boxes can
// hold a nearer one: an arc of 300 degrees of the unit circle about (5, 0), rational, in 60 spans.
// A point within 0.9 of the width of the circle is in the band, one 1.1 of it out, all around the
// arc and from either side. Past an end, the end is the nearest point.
TEST(FirstContactConstruction, BandNearestOverManySpans)
{
    constexpr double width = 1e-3;
    constexpr double gap = std::numbers::pi / 3.0;
    const gp_Pnt2d centre(5.0, 0.0);
    const Handle(Geom2d_Circle) circle = new Geom2d_Circle(gp_Ax2d(centre, gp_Dir2d(1, 0)), 1.0);
    const Handle(Geom2d_BSplineCurve) arc
        = Geom2dConvert::CurveToBSplineCurve(new Geom2d_TrimmedCurve(circle, gap / 2.0, 2.0 * std::numbers::pi - gap / 2.0));
    const double first = arc->FirstParameter();
    const double last = arc->LastParameter();
    for (int k = 1; k < 60; ++k) {
        arc->InsertKnot(first + (last - first) * k / 60.0);
    }
    ASSERT_GE(arc->NbKnots(), 60);
    PartDesign::FirstContact::Band band(frame);
    band.add(arc, width);
    auto at = [&](double angle, double radius) {
        return gp_Pnt(centre.X() + radius * std::cos(angle), 0.0, centre.Y() + radius * std::sin(angle));
    };
    for (int k = 0; k <= 200; ++k) {
        const double angle = gap / 2.0 + (2.0 * std::numbers::pi - gap) * k / 200.0;
        EXPECT_TRUE(band.contains(at(angle, 1.0 + 0.9 * width))) << angle;
        EXPECT_TRUE(band.contains(at(angle, 1.0 - 0.9 * width))) << angle;
        EXPECT_FALSE(band.contains(at(angle, 1.0 + 1.1 * width))) << angle;
        EXPECT_FALSE(band.contains(at(angle, 1.0 - 1.1 * width))) << angle;
    }
    // Past an end along its tangent; the gap's middle and the circle's centre
    const gp_Pnt2d end = arc->StartPoint();
    const gp_Vec2d back(std::sin(gap / 2.0), -std::cos(gap / 2.0));
    EXPECT_TRUE(band.contains(gp_Pnt(end.X() + 0.9 * width * back.X(), 0.0, end.Y() + 0.9 * width * back.Y())));
    EXPECT_FALSE(band.contains(gp_Pnt(end.X() + 1.1 * width * back.X(), 0.0, end.Y() + 1.1 * width * back.Y())));
    EXPECT_FALSE(band.contains(at(0.0, 1.0)));
    EXPECT_FALSE(band.contains(at(0.0, 0.0)));
}

// TEMPORARY (ops#293 D2 session 5): TrimmedFold's face, profile, cells, walls and pieces as BREP files
// in FC_D2_DUMP, for probes
TEST(FirstContactConstruction, DumpTrimmedFold)
{
    const char* folder = std::getenv("FC_D2_DUMP");
    if (!folder) {
        GTEST_SKIP();
    }
    const std::string base(folder);
    const Handle(Geom_BSplineCurve) curve = foldCurve();
    const gp_Dir up(0.12, 0.2, 1.0);
    const TopoDS_Face slabBase = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 1), up), -40, 40, -40, 40).Face();
    const TopoDS_Shape slab = BRepPrimAPI_MakePrism(slabBase, gp_Vec(up) * 30.0).Shape();
    const TopoDS_Shape cut = BRepAlgoAPI_Cut(extruded(curve), slab).Shape();
    const TopoDS_Face face = TopoDS::Face(TopExp_Explorer(cut, TopAbs_FACE).Current());
    const TopoDS_Face prof = profile(1.5, 3.0, 0.0, 1.2);
    BRepTools::Write(face, (base + "/face.brep").c_str());
    BRepTools::Write(prof, (base + "/profile.brep").c_str());
    const FirstContactSolid solid
        = PartDesign::FirstContact::constructFirstContact(face, prof, forward, tolerance);
    std::ofstream info(base + "/info.txt");
    info << "builds " << solid.builds << "\n";
    for (std::size_t k = 0; k < solid.trace.pieces.size(); ++k) {
        const auto& piece = solid.trace.pieces[k];
        info << "piece " << k << " source " << static_cast<int>(piece.source) << " edge " << piece.edge
             << " side " << piece.side << " continues " << piece.continuesPrevious << " meets "
             << piece.meetsProfile << " jumps " << piece.jumps << " points " << piece.points.size();
        if (!piece.points.empty()) {
            info << " from " << piece.points.front().X() << "," << piece.points.front().Y() << " to "
                 << piece.points.back().X() << "," << piece.points.back().Y();
        }
        info << "\n";
    }
    for (std::size_t w = 0; w < solid.walls.size(); ++w) {
        const auto& wall = solid.walls[w];
        info << "wall " << w << " piece " << wall.piece << " push " << wall.push << "\n";
        BRepTools::Write(
            BRepBuilderAPI_MakeEdge(GeomAPI::To3d(wall.curve, gp_Pln(gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(0, -1, 0), gp_Dir(1, 0, 0)))))
                .Edge(),
            (base + "/wall" + std::to_string(w) + ".brep").c_str()
        );
    }
    for (std::size_t c = 0; c < solid.cells.size(); ++c) {
        BRepTools::Write(solid.cells[c], (base + "/cell" + std::to_string(c) + ".brep").c_str());
    }
    for (std::size_t c = 0; c < solid.pieces.size(); ++c) {
        BRepTools::Write(solid.pieces[c], (base + "/piece" + std::to_string(c) + ".brep").c_str());
    }
    BRepTools::Write(solid.shape, (base + "/solid.brep").c_str());
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
