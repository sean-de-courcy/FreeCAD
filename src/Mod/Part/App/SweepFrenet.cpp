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
#include <Geom_Plane.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Circ.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

#include <Base/Console.h>

#include "SweepFrenet.h"

FC_LOG_LEVEL_INIT("Part", true, true)

namespace
{

/// The law's unit normal at \a u, where the curvature is clearly above zero (at least
/// SweepFrenet::curvatureFloor over the edge's length): where it is zero the law's normal is
/// whatever OCCT makes of a singular point, and a flat point that doesn't reverse the normal was
/// taken for a turn-over when it fell on a sample (fork PR 358 round 1, R1)
std::optional<gp_Vec> normalAt(GeomFill_Frenet& law, const BRepAdaptor_Curve& curve, double u, double length)
{
    gp_Pnt point;
    gp_Vec d1, d2;
    curve.D2(u, point, d1, d2);
    const double speed = d1.Magnitude();
    if (speed <= 0
        || d1.Crossed(d2).Magnitude() / (speed * speed * speed) * length
            <= Part::SweepFrenet::curvatureFloor) {
        return std::nullopt;
    }
    gp_Vec tangent, normal, binormal;
    if (!law.D0(u, tangent, normal, binormal) || normal.SquareMagnitude() < 0.25) {
        return std::nullopt;
    }
    return normal;
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

/// A point of \a edge where OCCT's Frenet trihedron turns over: two samples at most two apart, with
/// the curvature clearly above zero, whose normals point more than a right angle apart. Within a
/// quarter of a knot span the frame turns by more than a right angle about the tangent there: a
/// section that isn't a circle about the spine folds, whether OCCT's surface follows the turn or
/// not. A turn completed within one sample interval holds at most one sample, whose normal can be
/// half-way round (fork PR 358 round 2's verification, finding 2), so it is found wherever the
/// samples fall; a half turn spread evenly over four intervals or more (half a knot span) is not.
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
    const int samples = sampleCount(*curve);
    const double first = curve->FirstParameter();
    const double last = curve->LastParameter();
    std::optional<gp_Vec> previous;
    std::optional<gp_Vec> beforePrevious;
    double previousU = first;
    for (int i = 0; i <= samples; ++i) {
        const double u = first + (last - first) * i / samples;
        const std::optional<gp_Vec> normal = normalAt(*law, *curve, u, length);
        if (!normal) {
            continue;
        }
        if (previous && previous->Dot(*normal) < 0) {
            return curve->Value(u);
        }
        if (beforePrevious && beforePrevious->Dot(*normal) < 0) {
            return curve->Value(previousU);
        }
        beforePrevious = previous;
        previous = normal;
        previousU = u;
    }
    return std::nullopt;
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

/// The normal of the plane holding \a spine within \a tolerance, if there is one
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
    return plane->Position().Direction();
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
    // the plane. checkBuilt() then refuses tolerances far above the pipe's.
    Bnd_Box box;
    BRepBndLib::Add(spine, box);
    const double size = box.IsVoid() ? 0 : std::sqrt(box.SquareExtent());
    const auto normal = planeNormal(spine, std::max(tolerance, relativePlanarity * size));
    if (normal && tiltWithin(spine, *normal, sections, tolerance)) {
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
            << ", where its curvature passes through zero, and a profile that isn't a circle "
               "about the spine would twist through itself there. Turn Frenet off";
    throw Standard_Failure(message.str().c_str());
}

void Part::SweepFrenet::checkBuilt(const TopoDS_Shape& built, Mode mode, double tolerance)
{
    if (mode != Mode::PlaneNormal) {
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
    message << "Sweep: the spine's Frenet frame turns over on a spine that is only nearly planar, "
               "and sweeping with its plane's normal as binormal left a tolerance of "
            << largest << " mm. Make the spine planar, or turn Frenet off";
    throw Standard_Failure(message.str().c_str());
}
