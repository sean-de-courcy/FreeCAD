// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <sstream>

#include <BRepAdaptor_Curve.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepLib_FindSurface.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GeomFill_Frenet.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_Plane.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <gp.hxx>
#include <gp_Circ.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

#include <Base/Console.h>

#include "SweepFrenet.h"

FC_LOG_LEVEL_INIT("Part", true, true)

namespace
{

/// The law's unit tangent and normal at a sample
struct Frame
{
    gp_Vec tangent;
    gp_Vec normal;
};

/// The curvature of \a curve at \a u
double curvatureAt(const BRepAdaptor_Curve& curve, double u)
{
    gp_Pnt point;
    gp_Vec d1, d2;
    curve.D2(u, point, d1, d2);
    const double speed = d1.Magnitude();
    return speed > 0 ? d1.Crossed(d2).Magnitude() / (speed * speed * speed) : 0;
}

/// The law's frame at \a u, where the \a curvature is clearly above zero (at least
/// SweepFrenet::curvatureFloor over the edge's \a length): where it is zero the law's normal is
/// whatever OCCT makes of a singular point, and a flat point that doesn't reverse the normal was
/// taken for a turn-over when it fell on a sample (fork PR 358 round 1, R1)
std::optional<Frame> frameAt(GeomFill_Frenet& law, double u, double curvature, double length)
{
    if (curvature * length <= Part::SweepFrenet::curvatureFloor) {
        return std::nullopt;
    }
    gp_Vec tangent, normal, binormal;
    if (!law.D0(u, tangent, normal, binormal) || normal.SquareMagnitude() < 0.25
        || tangent.SquareMagnitude() < 0.25) {
        return std::nullopt;
    }
    return Frame {tangent.Normalized(), normal.Normalized()};
}

/// The cosine of the angle by which the frame turns about the tangent from \a from to \a to: the
/// normal of \a from carried by the smallest rotation that takes its tangent to \a to's, against
/// \a to's normal. Comparing the normals themselves counts the tangent's own turn as well: along a
/// helix sampled 6.4 times a turn, neighbouring normals were 56 degrees apart and two apart 113,
/// where the frame turns by 2 to 6 degrees about the tangent (fork PR 358 round 3's verification,
/// finding 2)
double turnCosine(const Frame& from, const Frame& to)
{
    const double cosine = from.tangent.Dot(to.tangent);
    if (cosine <= 0) {
        // The tangent turns by a right angle or more between the samples, which sampleParameters()
        // avoids where it can: compare the normals themselves
        return from.normal.Dot(to.normal);
    }
    // Rodrigues' formula with the axis scaled by the sine: v cos + a x v + a (a . v) / (1 + cos)
    const gp_Vec axis = from.tangent.Crossed(to.tangent);
    const gp_Vec carried = from.normal * cosine + axis.Crossed(from.normal)
        + axis * (axis.Dot(from.normal) / (1 + cosine));
    return carried.Dot(to.normal);
}

/// The number of sample intervals along \a curve: samplesPerSpan per knot span, at least minSamples
int sampleCount(const BRepAdaptor_Curve& curve)
{
    if (curve.GetType() == GeomAbs_Line) {
        return 1;
    }
    return std::max(
        Part::SweepFrenet::minSamples,
        Part::SweepFrenet::samplesPerSpan * curve.NbIntervals(GeomAbs_C3)
    );
}

/// Appends to \a parameters the sample parameters after \a u0 up to \a u1: \a u1, after those
/// of the halves of the interval while the curve's tangent turns by more than 45 degrees across it
/// (at most SweepFrenet::maxHalvings times), so that turnCosine() compares nearby tangents
void addSamples(
    const BRepAdaptor_Curve& curve,
    double u0,
    const gp_Vec& d0,
    double u1,
    const gp_Vec& d1,
    int halvings,
    std::vector<double>& parameters
)
{
    if (halvings < Part::SweepFrenet::maxHalvings
        && d0.Dot(d1) < std::sqrt(0.5) * d0.Magnitude() * d1.Magnitude()) {
        const double middle = (u0 + u1) / 2;
        gp_Pnt point;
        gp_Vec dm;
        curve.D1(middle, point, dm);
        addSamples(curve, u0, d0, middle, dm, halvings + 1, parameters);
        addSamples(curve, middle, dm, u1, d1, halvings + 1, parameters);
        return;
    }
    parameters.push_back(u1);
}

/// The parameters of the samples along \a curve: \a factor times sampleCount() even intervals,
/// halved where the tangent turns fast (addSamples())
std::vector<double> sampleParameters(const BRepAdaptor_Curve& curve, int factor)
{
    const int samples = factor * sampleCount(curve);
    const double first = curve.FirstParameter();
    const double last = curve.LastParameter();
    std::vector<double> parameters {first};
    gp_Pnt point;
    gp_Vec previous;
    curve.D1(first, point, previous);
    for (int i = 1; i <= samples; ++i) {
        const double u = first + (last - first) * i / samples;
        gp_Vec tangent;
        curve.D1(u, point, tangent);
        addSamples(curve, parameters.back(), previous, u, tangent, 0, parameters);
        previous = tangent;
    }
    return parameters;
}

/// What scanTurns() found along an edge
struct Scan
{
    /// The first sample where the frame turns over, if any
    std::optional<gp_Pnt> where;
    /// The median of turnCosine() between neighbouring counted samples (1 with fewer than two)
    double medianCosine;
};

/// The middle of \a values (the upper one of an even count)
double median(std::vector<double> values)
{
    const auto middle = values.begin() + static_cast<std::ptrdiff_t>(values.size() / 2);
    std::nth_element(values.begin(), middle, values.end());
    return *middle;
}

/// The unit principal normal of \a curve at \a u, where the curve bends
std::optional<gp_Vec> principalNormal(const BRepAdaptor_Curve& curve, double u)
{
    gp_Pnt point;
    gp_Vec d1, d2;
    curve.D2(u, point, d1, d2);
    const double speed2 = d1.SquareMagnitude();
    if (speed2 <= 0) {
        return std::nullopt;
    }
    const gp_Vec normal = d2 - d1 * (d1.Dot(d2) / speed2);
    if (normal.Magnitude() <= gp::Resolution()) {
        return std::nullopt;
    }
    return normal.Normalized();
}

/// Whether the normal of \a curve reverses at a knot strictly between \a u0 and \a u1 where the
/// curve is continuous only up to C1: its normals just before and just after the knot are more than
/// a right angle apart. The curvature jumps there instead of dipping (two tangent arcs bending
/// opposite ways, joined into one B-spline: fork PR 358 round 6's verification, finding 2); a long
/// Part.makeHelix curve's frame jumped by 47 degrees at such a knot (until ops#447).
bool knotReverses(const BRepAdaptor_Curve& curve, double u0, double u1)
{
    if (curve.GetType() != GeomAbs_BSplineCurve) {
        return false;
    }
    const Handle(Geom_BSplineCurve) spline = curve.BSpline();
    const double step = 1e-7 * (curve.LastParameter() - curve.FirstParameter());
    for (int i = spline->FirstUKnotIndex() + 1; i < spline->LastUKnotIndex(); ++i) {
        const double knot = spline->Knot(i);
        if (knot <= u0 || knot >= u1 || spline->Degree() - spline->Multiplicity(i) >= 2) {
            continue;
        }
        const std::optional<gp_Vec> before = principalNormal(curve, knot - step);
        const std::optional<gp_Vec> after = principalNormal(curve, knot + step);
        if (before && after && before->Dot(*after) < 0) {
            return true;
        }
    }
    return false;
}

/// The curvature of \a curve where \a law's frame turns over between \a u0 and \a u1, where the
/// frame at \a u1 has turned by more than a right angle about the tangent from the one at \a u0:
/// the last point turned by less and the first by more, found by SweepFrenet::turnBisections
/// halvings, give the lower of their curvatures. A point without a frame (the curvature at the
/// floor or below) gives 0.
double turnOverCurvature(
    GeomFill_Frenet& law,
    const BRepAdaptor_Curve& curve,
    double length,
    double u0,
    double u1
)
{
    const std::optional<Frame> start = frameAt(law, u0, curvatureAt(curve, u0), length);
    if (!start) {
        return 0;
    }
    double below = u0;
    double above = u1;
    for (int i = 0; i < Part::SweepFrenet::turnBisections; ++i) {
        const double middle = (below + above) / 2;
        const std::optional<Frame> frame = frameAt(law, middle, curvatureAt(curve, middle), length);
        if (!frame) {
            return 0;
        }
        if (turnCosine(*start, *frame) < 0) {
            above = middle;
        }
        else {
            below = middle;
        }
    }
    return std::min(curvatureAt(curve, below), curvatureAt(curve, above));
}

/// Whether the curvature of \a curve dips between the counted samples \a first and \a last
/// (indices into \a counted, the indices of the samples with a frame; \a parameters and
/// \a curvatures hold every sample's): its lowest value there, over the samples between them,
/// SweepFrenet::curvatureRefinement even steps (it can cross zero between two samples: fork PR 358
/// round 6's verification, finding 1) and the point where \a law's frame turns over
/// (turnOverCurvature(): an inflection within a 64th of a step from an end sample, round 7's
/// verification, findings 1 and 2), is at most SweepFrenet::curvatureDip times the median over
/// SweepFrenet::curvatureWindow counted samples on either side, on both sides. Where a side has no
/// samples, the lowest value must also be below the curvature at the end next to it: a curvature
/// rising along the edge from its start, as along a steep conical helix, isn't a dip (round 6's
/// verification, finding 3).
bool curvatureDips(
    GeomFill_Frenet& law,
    const BRepAdaptor_Curve& curve,
    double length,
    const std::vector<double>& parameters,
    const std::vector<double>& curvatures,
    const std::vector<std::size_t>& counted,
    std::size_t first,
    std::size_t last
)
{
    double lowest = *std::min_element(
        curvatures.begin() + static_cast<std::ptrdiff_t>(counted[first]),
        curvatures.begin() + static_cast<std::ptrdiff_t>(counted[last]) + 1
    );
    const double u0 = parameters[counted[first]];
    const double u1 = parameters[counted[last]];
    for (int i = 1; i < Part::SweepFrenet::curvatureRefinement; ++i) {
        lowest = std::min(
            lowest,
            curvatureAt(curve, u0 + (u1 - u0) * i / Part::SweepFrenet::curvatureRefinement)
        );
    }
    lowest = std::min(lowest, turnOverCurvature(law, curve, length, u0, u1));
    const auto window = static_cast<std::size_t>(Part::SweepFrenet::curvatureWindow);
    std::vector<double> before;
    for (std::size_t i = first - std::min(first, window); i < first; ++i) {
        before.push_back(curvatures[counted[i]]);
    }
    std::vector<double> after;
    for (std::size_t i = last + 1; i < counted.size() && i <= last + window; ++i) {
        after.push_back(curvatures[counted[i]]);
    }
    if (before.empty() || after.empty()) {
        // 0.999: the lowest value is never above the end's, and equal where it is the end's
        const double end = curvatures[counted[before.empty() ? first : last]];
        if (lowest >= 0.999 * end) {
            return false;
        }
    }
    return (before.empty() || lowest <= Part::SweepFrenet::curvatureDip * median(before))
        && (after.empty() || lowest <= Part::SweepFrenet::curvatureDip * median(after));
}

/// Samples \a law along \a curve, \a factor times sampleParameters()'s even intervals, for
/// turnOver(): the first point where the frame turns by more than a right angle about the tangent
/// between two counted samples at most two apart, where the curvature dips (curvatureDips()) or the
/// normal reverses at a knot (knotReverses()), and the median turn between neighbours
Scan scanTurns(GeomFill_Frenet& law, const BRepAdaptor_Curve& curve, double length, int factor)
{
    Scan scan {std::nullopt, 1};
    const std::vector<double> parameters = sampleParameters(curve, factor);
    std::vector<double> curvatures;
    std::vector<std::size_t> counted;
    std::vector<double> cosines;
    // A turn between two counted samples: the first and last of them
    std::vector<std::pair<std::size_t, std::size_t>> turns;
    std::optional<Frame> previous;
    std::optional<Frame> beforePrevious;
    for (std::size_t i = 0; i < parameters.size(); ++i) {
        curvatures.push_back(curvatureAt(curve, parameters[i]));
        const std::optional<Frame> frame = frameAt(law, parameters[i], curvatures.back(), length);
        if (!frame) {
            continue;
        }
        if (previous) {
            cosines.push_back(turnCosine(*previous, *frame));
            if (cosines.back() < 0) {
                turns.emplace_back(counted.size() - 1, counted.size());
            }
        }
        if (beforePrevious && turnCosine(*beforePrevious, *frame) < 0) {
            turns.emplace_back(counted.size() - 2, counted.size());
        }
        counted.push_back(i);
        beforePrevious = previous;
        previous = frame;
    }
    for (const auto& [first, last] : turns) {
        if (knotReverses(curve, parameters[counted[first]], parameters[counted[last]])
            || curvatureDips(law, curve, length, parameters, curvatures, counted, first, last)) {
            // Between neighbours the later sample, two apart the one between them
            scan.where = curve.Value(parameters[counted[last - (last - first) / 2]]);
            break;
        }
    }
    if (!cosines.empty()) {
        scan.medianCosine = median(cosines);
    }
    return scan;
}

/// A point of \a edge where OCCT's Frenet trihedron turns over: two samples at most two apart, with
/// the curvature clearly above zero, between which the frame turns by more than a right angle
/// about the tangent (turnCosine()). Within a quarter of a knot span the frame turns by more than a
/// right angle about the tangent there: a section that isn't a circle about the spine folds,
/// whether OCCT's surface follows the turn or not. A turn completed within one sample interval
/// holds at most one sample, whose normal can be half-way round (fork PR 358 round 2's
/// verification, finding 2), so it is found wherever the samples fall; a half turn spread evenly
/// over four intervals or more (half a knot span) is not.
/// The frame turns over where the normal reverses, which it does where the curvature passes through
/// or near zero: only a turn where the curvature dips counts (scanTurns()). Elsewhere the frame
/// turns about the tangent by the curve's torsion, which a helix has all along (249 degrees a turn
/// at a pitch of 6 times the radius), steep conical helices fast where they are narrow and slowly
/// where they are wide, and which jumped at a knot of a long Part.makeHelix curve continuous only
/// in its tangent (47 degrees, until ops#447): such turns were refused as turn-overs or swept in
/// another frame (fork PR 358 round 5's verification, findings 1 and 2). Where the median turn
/// between neighbours is above SweepFrenet::steadyTwistCosine's angle, the samples are too far
/// apart to tell a twist from a turn-over, so the edge is sampled again twice as densely, at most
/// SweepFrenet::maxDoublings times, and a turn-over counts only if it is still found where the
/// median is below that angle or at the last doubling. Planar spines don't turn about the tangent
/// (median 0 at the inflections seen), so their samples don't change.
std::optional<gp_Pnt> turnOver(const TopoDS_Edge& edge)
{
    if (BRep_Tool::Degenerated(edge)) {
        return std::nullopt;
    }
    Handle(BRepAdaptor_Curve) curve = new BRepAdaptor_Curve(edge);
    switch (curve->GetType()) {
        case GeomAbs_Line:
        case GeomAbs_Circle:
        case GeomAbs_Ellipse:
        case GeomAbs_Hyperbola:
        case GeomAbs_Parabola:
            // no inflections
            return std::nullopt;
        default:
            break;
    }
    Handle(GeomFill_Frenet) law = new GeomFill_Frenet();
    if (!law->SetCurve(curve)) {
        return std::nullopt;
    }
    const double length = GCPnts_AbscissaPoint::Length(*curve);
    for (int doublings = 0;; ++doublings) {
        const Scan scan = scanTurns(*law, *curve, length, 1 << doublings);
        if (!scan.where || scan.medianCosine >= Part::SweepFrenet::steadyTwistCosine
            || doublings == Part::SweepFrenet::maxDoublings) {
            return scan.where;
        }
    }
}

/// The spine's tangent at its point nearest to \a point, and the distance to it
std::optional<std::pair<gp_Vec, double>> nearestTangent(const TopoDS_Wire& spine, const gp_Pnt& point)
{
    BRepExtrema_DistShapeShape distance(BRepBuilderAPI_MakeVertex(point).Vertex(), spine);
    if (!distance.IsDone() || distance.NbSolution() < 1) {
        return std::nullopt;
    }
    TopoDS_Edge edge;
    double u = 0;
    const TopoDS_Shape support = distance.SupportOnShape2(1);
    if (distance.SupportTypeShape2(1) == BRepExtrema_IsOnEdge) {
        edge = TopoDS::Edge(support);
        distance.ParOnEdgeS2(1, u);
    }
    else if (distance.SupportTypeShape2(1) == BRepExtrema_IsVertex) {
        for (TopExp_Explorer xp(spine, TopAbs_EDGE); xp.More() && edge.IsNull(); xp.Next()) {
            const TopoDS_Edge candidate = TopoDS::Edge(xp.Current());
            for (TopExp_Explorer xv(candidate, TopAbs_VERTEX); xv.More(); xv.Next()) {
                if (xv.Current().IsSame(support)) {
                    edge = candidate;
                    u = BRep_Tool::Parameter(TopoDS::Vertex(support), candidate);
                    break;
                }
            }
        }
    }
    if (edge.IsNull()) {
        return std::nullopt;
    }
    gp_Pnt onSpine;
    gp_Vec tangent;
    BRepAdaptor_Curve(edge).D1(u, onSpine, tangent);
    return std::make_pair(tangent, distance.Value());
}

/// Whether turning \a section about the spine's tangent leaves it the same within \a tolerance: a
/// vertex on the spine, or a wire of one circle centred on the spine, in the plane normal to the
/// spine there. Such a section sweeps the same surface in any frame, so the frame's turn-over
/// can't fold it. (A circle normal to Z at the start of an interpolated wave, whose start tangent
/// is 3.9 mrad off Z, moves by 8 um in a half turn: not round.)
bool roundAboutSpine(const TopoDS_Shape& section, const TopoDS_Wire& spine, double tolerance)
{
    if (section.ShapeType() == TopAbs_VERTEX) {
        const auto nearest = nearestTangent(spine, BRep_Tool::Pnt(TopoDS::Vertex(section)));
        return nearest && nearest->second <= tolerance;
    }
    TopExp_Explorer xp(section, TopAbs_EDGE);
    if (!xp.More()) {
        return false;
    }
    const BRepAdaptor_Curve curve(TopoDS::Edge(xp.Current()));
    xp.Next();
    if (xp.More() || curve.GetType() != GeomAbs_Circle) {
        return false;
    }
    const gp_Circ circle = curve.Circle();
    const auto nearest = nearestTangent(spine, circle.Location());
    if (!nearest || nearest->second > tolerance || nearest->first.Magnitude() <= 0) {
        return false;
    }
    // Tilted by an angle a out of the plane normal to the spine, a turn of the frame about the
    // tangent moves the circle's points by up to 2 r sin a
    const gp_Vec axis(circle.Axis().Direction());
    return 2 * circle.Radius() * axis.Crossed(nearest->first.Normalized()).Magnitude() <= tolerance;
}

/// How far the points of \a section reach from the spine, at most: the distance of its bounding
/// box's centre from the spine plus half the box's diagonal
double reach(const TopoDS_Shape& section, const TopoDS_Wire& spine)
{
    Bnd_Box box;
    BRepBndLib::Add(section, box);
    if (box.IsVoid()) {
        return 0;
    }
    double x0 = 0, y0 = 0, z0 = 0, x1 = 0, y1 = 0, z1 = 0;
    box.Get(x0, y0, z0, x1, y1, z1);
    const auto nearest = nearestTangent(spine, gp_Pnt((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2));
    if (!nearest) {
        return std::numeric_limits<double>::infinity();
    }
    return nearest->second + std::sqrt(box.SquareExtent()) / 2;
}

/// Whether \a normal, the normal of a plane near \a spine, can be the sweep's constant binormal.
/// OCCT's constant binormal law puts each section in the plane through the binormal, tilted from
/// the plane normal to the spine by the angle a by which the spine's tangent leaves the plane, so
/// a section's points reaching r from the spine move by up to r (1 / cos a - 1). Within a
/// thousandth of its size of a plane, a spine's tangent can still leave it by 10 degrees: a circle
/// of radius 1 came out 1.5e-2 mm out of round (fork PR 358 round 2's verification, finding 1).
bool tiltWithin(
    const TopoDS_Wire& spine,
    const gp_Dir& normal,
    const std::vector<TopoDS_Shape>& sections,
    double tolerance
)
{
    // The largest sine of the angle between the tangent and the plane, over the samples
    double slope = 0;
    for (TopExp_Explorer xp(spine, TopAbs_EDGE); xp.More(); xp.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(xp.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        const BRepAdaptor_Curve curve(edge);
        const int samples = sampleCount(curve);
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        for (int i = 0; i <= samples; ++i) {
            gp_Pnt point;
            gp_Vec tangent;
            curve.D1(first + (last - first) * i / samples, point, tangent);
            const double speed = tangent.Magnitude();
            if (speed > 0) {
                slope = std::max(slope, std::abs(tangent.Dot(gp_Vec(normal))) / speed);
            }
        }
    }
    if (slope >= 1) {
        return false;
    }
    const double cosine = std::sqrt(1 - slope * slope);
    // 1 / cos a - 1, without the cancellation for small angles
    const double tilt = slope * slope / (cosine * (1 + cosine));
    return std::all_of(sections.begin(), sections.end(), [&](const TopoDS_Shape& section) {
        return reach(section, spine) * tilt <= tolerance;
    });
}

/// Whether \a normal, the normal of a plane near \a spine, is Frenet's binormal up to its sign:
/// within SweepFrenet::binormalCosine's angle of it at all but SweepFrenet::binormalOffShare of the
/// samples where the curvature is clearly above zero (a sample inside a narrow turn-over has its
/// binormal half-way round). Near a plane, a spine can still twist: a 100-turn helix of radius 0.1
/// and height 1000 is within a thousandth of its size of the plane through its axis, its binormal
/// turns all round, and the plane's normal as binormal swept a triangle beside it in a fixed
/// direction (fork PR 358 round 5's verification, finding 1).
bool binormalWithin(const TopoDS_Wire& spine, const gp_Dir& normal)
{
    int samples = 0;
    int off = 0;
    for (TopExp_Explorer xp(spine, TopAbs_EDGE); xp.More(); xp.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(xp.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        Handle(BRepAdaptor_Curve) curve = new BRepAdaptor_Curve(edge);
        Handle(GeomFill_Frenet) law = new GeomFill_Frenet();
        if (curve->GetType() == GeomAbs_Line || !law->SetCurve(curve)) {
            continue;
        }
        const double length = GCPnts_AbscissaPoint::Length(*curve);
        for (const double u : sampleParameters(*curve, 1)) {
            const std::optional<Frame> frame = frameAt(*law, u, curvatureAt(*curve, u), length);
            if (!frame) {
                continue;
            }
            ++samples;
            if (std::abs(frame->tangent.Crossed(frame->normal).Dot(gp_Vec(normal)))
                < Part::SweepFrenet::binormalCosine) {
                ++off;
            }
        }
    }
    return off <= Part::SweepFrenet::binormalOffShare * samples;
}

/// The normal of the plane holding \a spine within \a tolerance, if there is one. The plane
/// BRepLib_FindSurface finds is checked against the spine's points at sampleCount()'s even samples:
/// it also found one for a 100-turn helix of radius 0.1 (fork PR 358 round 5's verification,
/// finding 1).
std::optional<gp_Dir> planeNormal(const TopoDS_Wire& spine, double tolerance)
{
    BRepLib_FindSurface finder(spine, tolerance, Standard_True);
    if (!finder.Found()) {
        return std::nullopt;
    }
    Handle(Geom_Plane) plane = Handle(Geom_Plane)::DownCast(finder.Surface());
    if (plane.IsNull()) {
        return std::nullopt;
    }
    const gp_Pln pln = plane->Pln();
    for (TopExp_Explorer xp(spine, TopAbs_EDGE); xp.More(); xp.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(xp.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        const BRepAdaptor_Curve curve(edge);
        const int samples = sampleCount(curve);
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        for (int i = 0; i <= samples; ++i) {
            const double distance = pln.Distance(curve.Value(first + (last - first) * i / samples));
            if (distance > tolerance) {
                FC_LOG(
                    "Sweep: the spine's plane within " << tolerance << " (found within "
                                                       << finder.ToleranceReached()
                                                       << ") is " << distance << " from its points"
                );
                return std::nullopt;
            }
        }
    }
    return pln.Axis().Direction();
}

}  // namespace

Part::SweepFrenet::Mode Part::SweepFrenet::setMode(
    BRepOffsetAPI_MakePipeShell& pipe,
    const TopoDS_Wire& spine,
    const std::vector<TopoDS_Shape>& sections,
    bool frenet,
    double tolerance
)
{
    pipe.SetMode(frenet);
    if (!frenet) {
        return Mode::Asked;
    }
    std::optional<gp_Pnt> where;
    for (TopExp_Explorer xp(spine, TopAbs_EDGE); xp.More() && !where; xp.Next()) {
        where = turnOver(TopoDS::Edge(xp.Current()));
    }
    if (!where) {
        return Mode::Asked;
    }
    std::ostringstream at;
    at << "(" << where->X() << ", " << where->Y() << ", " << where->Z() << ")";

    // A planar curve's Frenet frame doesn't turn about the tangent (its binormal is the plane's
    // normal up to its sign), so on a planar spine the rotation-minimizing frame of corrected
    // Frenet is Frenet's own, kept continuous. A constant binormal, the plane's normal, is the same
    // frame, but MakePipeShell approximated it worse: edge tolerances of 0.16 mm at 200 spans and
    // 2 mm at 1000, against 1e-4 (ops#421)
    if (planeNormal(spine, Precision::Confusion())) {
        FC_LOG("Sweep: the spine's Frenet frame turns over at " << at.str() << ": corrected Frenet");
        pipe.SetMode(false);
        return Mode::CorrectedFrenet;
    }
    // A spine planar to a fraction of its size: corrected Frenet failed there ("command not done"
    // with lifts of 1e-10 to 1e-5 mm of a planar wave) while the plane's normal as a constant
    // binormal built the tube (fork PR 358 round 2, R2), where the tangent stays close enough to
    // the plane and Frenet's binormal close to its normal. checkBuilt() then refuses tolerances
    // far above the pipe's.
    Bnd_Box box;
    BRepBndLib::Add(spine, box);
    const double size = box.IsVoid() ? 0 : std::sqrt(box.SquareExtent());
    const auto normal = planeNormal(spine, std::max(tolerance, relativePlanarity * size));
    if (normal && tiltWithin(spine, *normal, sections, tolerance)
        && binormalWithin(spine, *normal)) {
        FC_LOG(
            "Sweep: the spine's Frenet frame turns over at " << at.str()
                                                             << ": its plane's normal as binormal"
        );
        pipe.SetMode(*normal);
        return Mode::PlaneNormal;
    }
    // Not planar: no frame keeps Frenet's meaning. A section round about the spine sweeps the same
    // surface in any frame, so corrected Frenet, which doesn't turn over, gives Frenet's tube
    // (OCCT's Frenet followed a fast turn there but not a jump: 0.41 mm off on a spine planar
    // around its inflections and rising after them); any other section folds.
    if (std::all_of(sections.begin(), sections.end(), [&](const TopoDS_Shape& section) {
            return roundAboutSpine(section, spine, tolerance);
        })) {
        FC_LOG(
            "Sweep: the spine's Frenet frame turns over at " << at.str()
                                                             << ": round sections, "
                                                                "corrected Frenet"
        );
        pipe.SetMode(false);
        return Mode::CorrectedFrenet;
    }
    // A Standard_Failure, whose message Part::Sweep reports (it turns other exceptions into
    // "A fatal error occurred when making the sweep")
    std::ostringstream message;
    message << "Sweep: the spine's Frenet frame turns over at " << at.str()
            << ", turning by more than a right angle about the spine within a short stretch (as "
               "where a wave's curvature passes through zero), and a profile that isn't a circle "
               "about the spine would twist through itself there. Turn Frenet off";
    throw Standard_Failure(message.str().c_str());
}

void Part::SweepFrenet::checkBuilt(const TopoDS_Shape& built, Mode mode, double tolerance)
{
    // Corrected Frenet too: on ten exactly planar waves turned 45 degrees about X (a sketch on a
    // tilted plane) it left vertices of 0.15 mm and the tube 1.6e-2 mm off, where the same waves
    // in XZ came out within 5e-5 (fork PR 358 round 3's verification, finding 1)
    if (mode == Mode::Asked) {
        return;
    }
    double largest = 0;
    for (TopExp_Explorer xp(built, TopAbs_VERTEX); xp.More(); xp.Next()) {
        largest = std::max(largest, BRep_Tool::Tolerance(TopoDS::Vertex(xp.Current())));
    }
    for (TopExp_Explorer xp(built, TopAbs_EDGE); xp.More(); xp.Next()) {
        largest = std::max(largest, BRep_Tool::Tolerance(TopoDS::Edge(xp.Current())));
    }
    if (largest <= maxToleranceRatio * tolerance) {
        return;
    }
    std::ostringstream message;
    if (mode == Mode::PlaneNormal) {
        message << "Sweep: the spine's Frenet frame turns over on a spine that is only nearly "
                   "planar, and sweeping with its plane's normal as binormal left a tolerance of "
                << largest << " mm. Make the spine planar, or turn Frenet off";
    }
    else {
        // Frenet off is corrected Frenet as well, so it isn't suggested
        message << "Sweep: the spine's Frenet frame turns over, and sweeping with corrected Frenet "
                   "in its place left a tolerance of "
                << largest << " mm, more than " << maxToleranceRatio
                << " times the sweep's own";
    }
    throw Standard_Failure(message.str().c_str());
}
