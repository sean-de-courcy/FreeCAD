// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <cmath>
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

/// A point of \a edge where OCCT's Frenet trihedron turns over: two neighbouring samples, with the
/// curvature clearly above zero, whose normals point more than a right angle apart. Within an eighth
/// of a knot span the frame turns by more than a right angle about the tangent there: a section
/// that isn't a circle about the spine folds, whether OCCT's surface follows the turn or not.
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
    const int spans = curve->NbIntervals(GeomAbs_C3);
    const int samples
        = std::max(Part::SweepFrenet::minSamples, Part::SweepFrenet::samplesPerSpan * spans);
    const double first = curve->FirstParameter();
    const double last = curve->LastParameter();
    std::optional<gp_Vec> previous;
    for (int i = 0; i <= samples; ++i) {
        const double u = first + (last - first) * i / samples;
        const std::optional<gp_Vec> normal = normalAt(*law, *curve, u, length);
        if (!normal) {
            continue;
        }
        if (previous && previous->Dot(*normal) < 0) {
            return curve->Value(u);
        }
        previous = normal;
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

void Part::SweepFrenet::setMode(
    BRepOffsetAPI_MakePipeShell& pipe,
    const TopoDS_Wire& spine,
    const std::vector<TopoDS_Shape>& sections,
    bool frenet,
    double tolerance
)
{
    pipe.SetMode(frenet);
    if (!frenet) {
        return;
    }
    std::optional<gp_Pnt> where;
    for (TopExp_Explorer xp(spine, TopAbs_EDGE); xp.More() && !where; xp.Next()) {
        where = turnOver(TopoDS::Edge(xp.Current()));
    }
    if (!where) {
        return;
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
        return;
    }
    // A spine planar to a fraction of its size: corrected Frenet failed there ("command not done"
    // with lifts of 1e-10 to 1e-5 mm of a planar wave) while the plane's normal as a constant
    // binormal built the tube (fork PR 358 round 2, R2)
    Bnd_Box box;
    BRepBndLib::Add(spine, box);
    const double size = box.IsVoid() ? 0 : std::sqrt(box.SquareExtent());
    if (const auto normal = planeNormal(spine, std::max(tolerance, relativePlanarity * size))) {
        FC_LOG(
            "Sweep: the spine's Frenet frame turns over at " << at.str()
                                                             << ": its plane's normal as binormal"
        );
        pipe.SetMode(*normal);
        return;
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
        return;
    }
    // A Standard_Failure, whose message Part::Sweep reports (it turns other exceptions into
    // "A fatal error occurred when making the sweep")
    std::ostringstream message;
    message << "Sweep: the spine's Frenet frame turns over at " << at.str()
            << ", where its curvature passes through zero, and a profile that isn't a circle "
               "about the spine would twist through itself there. Turn Frenet off";
    throw Standard_Failure(message.str().c_str());
}
