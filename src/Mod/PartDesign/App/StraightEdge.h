// SPDX-License-Identifier: LGPL-2.1-or-later
// FreeCAD-CH (ops#640)

#pragma once

#include <algorithm>

#include <BRepAdaptor_Curve.hxx>
#include <BRep_Tool.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BezierCurve.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TColgp_Array1OfPnt.hxx>
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
/// start and direction. The bound is the poles of the edge's part of the curve: the curve lies in
/// their convex hull, so every pole within the tolerance of the chord means every point is (batch
/// 4's T4a: point samples could miss a bend between them).
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
    auto onChord = [&](const TColgp_Array1OfPnt& poles) {
        for (int i = poles.Lower(); i <= poles.Upper(); ++i) {
            if (chord.Distance(poles(i)) > tolerance) {
                return false;
            }
        }
        return true;
    };
    try {
        if (adapt.GetType() == GeomAbs_BSplineCurve) {
            Handle(Geom_BSplineCurve) curve
                = Handle(Geom_BSplineCurve)::DownCast(adapt.BSpline()->Copy());
            if (first > curve->FirstParameter() || last < curve->LastParameter()) {
                curve->Segment(first, last);
            }
            if (!onChord(curve->Poles())) {
                return false;
            }
        }
        else {
            Handle(Geom_BezierCurve) curve
                = Handle(Geom_BezierCurve)::DownCast(adapt.Bezier()->Copy());
            if (first > curve->FirstParameter() || last < curve->LastParameter()) {
                curve->Segment(first, last);
            }
            if (!onChord(curve->Poles())) {
                return false;
            }
        }
    }
    catch (const Standard_Failure&) {
        return false;
    }
    base = start;
    dir = chord.Direction();
    return true;
}

}  // namespace PartDesign
