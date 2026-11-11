// SPDX-License-Identifier: LGPL-2.1-or-later
// FreeCAD-CH (ops#640)

#pragma once

#include <algorithm>

#include <BRepAdaptor_Curve.hxx>
#include <BRep_Tool.hxx>
#include <Precision.hxx>
#include <TopoDS_Edge.hxx>
#include <gp_Dir.hxx>
#include <gp_Lin.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

namespace PartDesign
{

/// Whether \a edge is straight: a line, or a curve whose points lie on its chord within the
/// edge's tolerance (a sweep's end edge is a B-spline, straight only by its shape: the end edge of
/// a thread that stops between whole turns, the axis of its revolved cap; Onshape takes it as an
/// axis, SW7, ops#640). \a base and \a dir then give the line: a line's own, else the chord's
/// start and direction. 64 samples, as the edge's own tolerance is what makes it straight.
inline bool straightEdge(const TopoDS_Edge& edge, gp_Pnt& base, gp_Dir& dir)
{
    if (edge.IsNull()) {
        return false;
    }
    BRepAdaptor_Curve adapt(edge);
    if (adapt.GetType() == GeomAbs_Line) {
        base = adapt.Line().Location();
        dir = adapt.Line().Direction();
        return true;
    }
    if (adapt.GetType() != GeomAbs_BSplineCurve && adapt.GetType() != GeomAbs_BezierCurve) {
        return false;
    }
    const double first = adapt.FirstParameter();
    const double last = adapt.LastParameter();
    const gp_Pnt start = adapt.Value(first);
    const gp_Pnt end = adapt.Value(last);
    const double tolerance = std::max(Precision::Confusion(), BRep_Tool::Tolerance(edge));
    if (start.Distance(end) <= 10 * tolerance) {
        return false;
    }
    const gp_Lin chord(start, gp_Dir(gp_Vec(start, end)));
    constexpr int samples = 64;
    for (int i = 1; i < samples; ++i) {
        if (chord.Distance(adapt.Value(first + (last - first) * i / samples)) > tolerance) {
            return false;
        }
    }
    base = start;
    dir = chord.Direction();
    return true;
}

}  // namespace PartDesign
