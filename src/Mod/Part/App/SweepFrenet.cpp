// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <optional>
#include <sstream>

#include <BRepAdaptor_Curve.hxx>
#include <BRepLib_FindSurface.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRep_Tool.hxx>
#include <GeomFill_Frenet.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

#include <Base/Console.h>

#include "SweepFrenet.h"

FC_LOG_LEVEL_INIT("Part", true, true)

namespace
{

/// The law's unit normal at \a u, if it has one
std::optional<gp_Vec> normalAt(GeomFill_Frenet& law, double u)
{
    gp_Vec tangent, normal, binormal;
    if (!law.D0(u, tangent, normal, binormal) || normal.SquareMagnitude() < 0.25) {
        return std::nullopt;
    }
    return normal;
}

/// Whether the normals at \a a and \a b, more than a right angle apart, stay so however close the
/// parameters get: the trihedron jumps between them. Where the curvature only comes close to zero
/// (a curve leaving its plane there), the normal turns fast but continuously, the turn spreads over
/// both halves, and MakePipeShell follows it (ops#421).
bool jumps(GeomFill_Frenet& law, double a, double b, gp_Vec normalA, gp_Vec normalB)
{
    for (int i = 0; i < Part::SweepFrenet::bisections; ++i) {
        const double middle = (a + b) / 2;
        const std::optional<gp_Vec> normal = normalAt(law, middle);
        if (!normal) {
            return true;
        }
        if (normalA.Dot(*normal) < 0) {
            b = middle;
            normalB = *normal;
        }
        else if (normal->Dot(normalB) < 0) {
            a = middle;
            normalA = *normal;
        }
        else {
            return false;
        }
    }
    return true;
}

/// A point of \a edge where OCCT's Frenet trihedron turns over: two neighbouring samples whose
/// normals point more than a right angle apart, and stay so as they close in
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
    const int spans = curve->NbIntervals(GeomAbs_C3);
    const int samples
        = std::max(Part::SweepFrenet::minSamples, Part::SweepFrenet::samplesPerSpan * spans);
    const double first = curve->FirstParameter();
    const double last = curve->LastParameter();
    std::optional<gp_Vec> previous;
    double previousU = first;
    for (int i = 0; i <= samples; ++i) {
        const double u = first + (last - first) * i / samples;
        const std::optional<gp_Vec> normal = normalAt(*law, u);
        if (!normal) {
            continue;
        }
        if (previous && previous->Dot(*normal) < 0 && jumps(*law, previousU, u, *previous, *normal)) {
            return curve->Value(u);
        }
        previous = normal;
        previousU = u;
    }
    return std::nullopt;
}

}  // namespace

void Part::SweepFrenet::setMode(BRepOffsetAPI_MakePipeShell& pipe, const TopoDS_Wire& spine, bool frenet)
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
    BRepLib_FindSurface plane(spine, Precision::Confusion(), Standard_True);
    if (!plane.Found()) {
        // A Standard_Failure, whose message Part::Sweep reports (it turns other exceptions into
        // "A fatal error occurred when making the sweep")
        std::ostringstream message;
        message << "Sweep: the spine's Frenet frame turns over at (" << where->X() << ", "
                << where->Y() << ", " << where->Z()
                << "), where its curvature passes through zero, and the sweep would twist through "
                   "itself there. Turn Frenet off, or split the spine at that point";
        throw Standard_Failure(message.str().c_str());
    }
    FC_LOG(
        "Sweep: the spine's Frenet frame turns over at ("
        << where->X() << ", " << where->Y() << ", " << where->Z() << "): sweeping with corrected Frenet"
    );
    // On a planar curve the Frenet frame doesn't turn about the tangent (no torsion), so the
    // rotation-minimizing frame of corrected Frenet is Frenet's own, kept continuous. A constant
    // binormal (the plane's normal) is the same frame, but MakePipeShell approximated it worse:
    // edge tolerances of 0.16 mm at 200 spans and 2 mm at 1000, against 1e-4 (ops#421)
    pipe.SetMode(false);
}
