// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 Stefan Tröger <stefantroeger@gmx.net>              *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdlib>
#include <functional>
#include <limits>
#include <optional>
#include <set>
#include <tuple>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <BRepTools_History.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GProp_GProps.hxx>
#include <GeomAPI_PointsToBSpline.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <GeomFill_Profiler.hxx>
#include <Geom_BSplineCurve.hxx>
#include <gp_Lin.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Surface.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Ax3.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt2d.hxx>
#include <Precision.hxx>


#include <boost/core/ignore_unused.hpp>

#include <App/Document.h>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Mod/Part/App/FaceMakerCheese.h>

#include "Mod/Part/App/TopoShapeMapper.h"
#include "Mod/Part/App/TopoShapeOpCode.h"

#include "FeatureLoft.h"
#include "ProfileRegions.h"
using namespace PartDesign;

namespace Part
{
/// FreeCAD-CH ops#963 B: a loft's flat B-spline faces as planes and straight edges as lines, the
/// topology, its order and so the names kept (TopoShapeExpansion.cpp, makeElementLoft's last step)
PartExport void makeLoftCanonical(TopoShape& loft);
}  // namespace Part

namespace
{
// ops#655: Onshape's loft start and end condition "Normal to profile" (notes/loft-options.md)

/// Onshape's tangent length per unit magnitude at one corner rail of a side face, from its point p
/// on the first profile to its point q on the last, at the end whose normal (towards the other
/// profile) is `normal`: 0.9 times the rail's reach along that normal plus 0.1 times its length.
/// Along a face between two corner rails it is linear between them; a face bounded by one closed
/// edge on each profile (a circle) has no corners, and each row takes the rule at its own rail
/// (oracle 18 Q10). Found from oracle 17's surfaces (LE2, LE4, LE9; notes/loft-end-conditions.md):
/// it gives Onshape's k to 1e-6 on squares, circles, offset rectangles and a tilted end, where each
/// end gets its own k.
double tangentLength(const gp_Pnt& p, const gp_Pnt& q, const gp_Dir& normal)
{
    const gp_Vec rail(p, q);
    return 0.9 * rail.Dot(gp_Vec(normal)) + 0.1 * rail.Magnitude();
}

/// fork-1.0.0's rule (TangentRule "Legacy", ops#855): k per unit magnitude as a multiple of the
/// distance between the profiles, from oracle fact GB12 (e) (k = 30.138 for profiles 30 apart)
constexpr double legacyTangentPerDistance = 30.138 / 30.0;

gp_Pnt wireCentre(const TopoDS_Shape& wire)
{
    GProp_GProps props;
    BRepGProp::LinearProperties(wire, props);
    return props.CentreOfMass();
}

/// The point at each arc-length fraction of `edge`, walking from the end nearer `start` (an
/// open edge) or in the direction whose quarter point is nearer `quarter` (a closed edge).
std::vector<gp_Pnt> byArcLength(
    const TopoDS_Edge& edge,
    const gp_Pnt& start,
    const gp_Pnt& quarter,
    const std::vector<double>& fractions
)
{
    BRepAdaptor_Curve curve(edge);
    const double first = curve.FirstParameter();
    const double last = curve.LastParameter();
    const double length = GCPnts_AbscissaPoint::Length(curve);
    auto at = [&](double fraction, bool forward) {
        if (fraction <= 0) {
            return curve.Value(forward ? first : last);
        }
        if (fraction >= 1) {
            return curve.Value(forward ? last : first);
        }
        GCPnts_AbscissaPoint point(
            curve,
            forward ? fraction * length : -fraction * length,
            forward ? first : last
        );
        if (!point.IsDone()) {
            throw Base::CADKernelError("Loft: failed to walk a profile edge");
        }
        return curve.Value(point.Parameter());
    };
    bool forward = true;
    if (BRep_Tool::IsClosed(edge) || curve.Value(first).Distance(curve.Value(last)) < 1e-7) {
        forward = at(0.25, true).Distance(quarter) <= at(0.25, false).Distance(quarter);
    }
    else {
        forward = curve.Value(first).Distance(start) <= curve.Value(last).Distance(start);
    }
    std::vector<gp_Pnt> points;
    points.reserve(fractions.size());
    for (double fraction : fractions) {
        points.push_back(at(fraction, forward));
    }
    return points;
}

Handle(Geom_BSplineCurve) fit(const std::vector<gp_Pnt>& points, const std::vector<double>& fractions)
{
    TColgp_Array1OfPnt poles(1, static_cast<int>(points.size()));
    TColStd_Array1OfReal params(1, static_cast<int>(fractions.size()));
    for (size_t i = 0; i < points.size(); ++i) {
        poles(static_cast<int>(i) + 1) = points[i];
        params(static_cast<int>(i) + 1) = fractions[i];
    }
    GeomAPI_PointsToBSpline approx(poles, params, 3, 8, GeomAbs_C2, 1e-9);
    if (!approx.IsDone()) {
        throw Base::CADKernelError("Loft: failed to fit a profile edge");
    }
    return approx.Curve();
}

/// The ruled loft `ruled` between the planar profiles `first` and `last`, with each side face
/// replaced by Onshape's cubic in the loft direction: it leaves the first profile along its normal
/// (a start condition) and/or reaches the last one along its normal (an end condition), with a
/// natural (zero second derivative) end where no condition is set. Each matched pair of profile
/// edges is parameterised by arc length, as Onshape's plain loft pairs them. The faces keep the
/// ruled loft's names.
Part::TopoShape withProfileConditions(
    const Part::TopoShape& ruled,
    const TopoDS_Shape& first,
    const TopoDS_Shape& last,
    bool start,
    double startMagnitude,
    bool end,
    double endMagnitude,
    bool legacy
)
{
    gp_Pln plane0;
    gp_Pln plane1;
    if (!Part::TopoShape(first).findPlane(plane0) || !Part::TopoShape(last).findPlane(plane1)) {
        throw Base::CADKernelError(
            QT_TRANSLATE_NOOP("Exception", "Loft: Normal to profile needs planar profiles")
        );
    }
    const gp_Vec across(wireCentre(first), wireCentre(last));
    gp_Dir normal0 = plane0.Axis().Direction();
    gp_Dir normal1 = plane1.Axis().Direction();
    if (across.Dot(normal0) < 0) {
        normal0.Reverse();
    }
    if (across.Dot(normal1) < 0) {
        normal1.Reverse();
    }
    const double distance0 = across.Dot(normal0);
    const double distance1 = across.Dot(normal1);
    if (distance0 < Precision::Confusion() || distance1 < Precision::Confusion()) {
        throw Base::CADKernelError(QT_TRANSLATE_NOOP(
            "Exception",
            "Loft: Normal to profile needs each profile's centre off the other profile's plane"
        ));
    }

    constexpr int samples = 101;
    std::vector<double> fractions(samples);
    for (int i = 0; i < samples; ++i) {
        fractions[i] = double(i) / (samples - 1);
    }
    auto onPlane = [](const gp_Pln& plane, const gp_Pnt& point) {
        return plane.Distance(point) < 1e-6;
    };

    std::vector<TopoDS_Face> oldFaces;
    std::vector<TopoDS_Face> newFaces;
    for (TopExp_Explorer x(ruled.getShape(), TopAbs_FACE); x.More(); x.Next()) {
        const TopoDS_Face& face = TopoDS::Face(x.Current());
        TopoDS_Edge edge0;
        TopoDS_Edge edge1;
        for (TopExp_Explorer e(face, TopAbs_EDGE); e.More(); e.Next()) {
            const TopoDS_Edge& edge = TopoDS::Edge(e.Current());
            if (BRep_Tool::Degenerated(edge)) {
                continue;
            }
            BRepAdaptor_Curve curve(edge);
            const gp_Pnt a = curve.Value(curve.FirstParameter());
            const gp_Pnt b = curve.Value(curve.LastParameter());
            const gp_Pnt m = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
            if (onPlane(plane0, a) && onPlane(plane0, b) && onPlane(plane0, m)) {
                edge0 = edge;
            }
            else if (onPlane(plane1, a) && onPlane(plane1, b) && onPlane(plane1, m)) {
                edge1 = edge;
            }
        }
        if (edge0.IsNull() || edge1.IsNull()) {
            throw Base::CADKernelError("Loft: a side face doesn't join the two profiles");
        }
        // the ruled face's rows on the two profiles give the matched ends and the direction
        Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
        double u0 = 0;
        double u1 = 0;
        double v0 = 0;
        double v1 = 0;
        BRepTools::UVBounds(face, u0, u1, v0, v1);
        const double um = (u0 + u1) / 2;
        const double vm = (v0 + v1) / 2;
        // a quarter along each profile row, for a closed edge's direction
        const double uq = u0 + (u1 - u0) / 4;
        const double vq = v0 + (v1 - v0) / 4;
        gp_Pnt start0;
        gp_Pnt middle0;
        gp_Pnt start1;
        gp_Pnt middle1;
        if (onPlane(plane0, surface->Value(um, v0)) || onPlane(plane0, surface->Value(um, v1))) {
            const bool low = onPlane(plane0, surface->Value(um, v0));
            start0 = surface->Value(u0, low ? v0 : v1);
            middle0 = surface->Value(uq, low ? v0 : v1);
            start1 = surface->Value(u0, low ? v1 : v0);
            middle1 = surface->Value(uq, low ? v1 : v0);
        }
        else {
            const bool low = onPlane(plane0, surface->Value(u0, vm));
            start0 = surface->Value(low ? u0 : u1, v0);
            middle0 = surface->Value(low ? u0 : u1, vq);
            start1 = surface->Value(low ? u1 : u0, v0);
            middle1 = surface->Value(low ? u1 : u0, vq);
        }
        // an open profile edge's matched ends are the ends of one rail, the side edge joining the
        // two profile edges: a flat side made canonical (`makeLoftCanonical`) is a plane whose frame
        // can be oblique to its edges, so its UV box doesn't pair the ends (ops#883)
        if (!legacy && !BRep_Tool::IsClosed(edge0)) {  // fork-1.0.0 paired by the UV box
            const TopoDS_Vertex first0 = TopExp::FirstVertex(edge0);
            TopoDS_Vertex partner;
            for (TopExp_Explorer e(face, TopAbs_EDGE); e.More() && partner.IsNull(); e.Next()) {
                const TopoDS_Edge& rail = TopoDS::Edge(e.Current());
                if (BRep_Tool::Degenerated(rail) || rail.IsSame(edge0) || rail.IsSame(edge1)) {
                    continue;
                }
                TopoDS_Vertex a;
                TopoDS_Vertex b;
                TopExp::Vertices(rail, a, b);
                if (a.IsSame(first0)) {
                    partner = b;
                }
                else if (b.IsSame(first0)) {
                    partner = a;
                }
            }
            if (partner.IsNull()) {
                throw Base::CADKernelError("Loft: a side face has no edge joining its profile edges");
            }
            start0 = BRep_Tool::Pnt(first0);
            start1 = BRep_Tool::Pnt(partner);
        }
        // both profile edges by arc length, walked from the ends nearest the face's first rows
        const std::vector<gp_Pnt> points0 = byArcLength(edge0, start0, middle0, fractions);
        const std::vector<gp_Pnt> points1 = byArcLength(edge1, start1, middle1, fractions);
        // the tangent lengths at the face's two corner rails (fraction 0 and 1), from the edges'
        // own end points: a planar side face's surface corners can lie off its edges
        const double startA
            = startMagnitude * tangentLength(points0.front(), points1.front(), normal0);
        const double startB = startMagnitude * tangentLength(points0.back(), points1.back(), normal0);
        const double endA = endMagnitude * tangentLength(points0.front(), points1.front(), normal1);
        const double endB = endMagnitude * tangentLength(points0.back(), points1.back(), normal1);
        // a closed profile edge (a circle) has no corner rails: each row takes the rule at its own
        // rail, the points at its fraction on the two edges (oracle 18 Q10: an off-centre circle's
        // rows each get their own value, not the seam rail's)
        const bool closed = BRep_Tool::IsClosed(edge0)
            || points0.front().Distance(points0.back()) < 1e-7;
        const Handle(Geom_BSplineCurve) curve0 = fit(points0, fractions);
        const Handle(Geom_BSplineCurve) curve1 = fit(points1, fractions);
        GeomFill_Profiler profiler;
        profiler.AddCurve(curve0);
        profiler.AddCurve(curve1);
        profiler.Perform(Precision::PConfusion());
        const int count = profiler.NbPoles();
        TColgp_Array1OfPnt row0(1, count);
        TColgp_Array1OfPnt row3(1, count);
        profiler.Poles(1, row0);
        profiler.Poles(2, row3);
        TColStd_Array1OfReal uKnots(1, profiler.NbKnots());
        TColStd_Array1OfInteger uMults(1, profiler.NbKnots());
        profiler.KnotsAndMults(uKnots, uMults);
        // each pole row's place along the face (Greville abscissa), so a tangent length linear in
        // the arc-length fraction is exactly linear along the surface
        const int degree = profiler.Degree();
        std::vector<double> flat;
        for (int i = uKnots.Lower(); i <= uKnots.Upper(); ++i) {
            flat.insert(flat.end(), uMults(i), uKnots(i));
        }
        if (static_cast<int>(flat.size()) != count + degree + 1) {
            throw Base::CADKernelError("Loft: unexpected knots on a profile edge");
        }
        const double span = flat.back() - flat.front();
        TColgp_Array2OfPnt poles(1, count, 1, 4);
        for (int j = 1; j <= count; ++j) {
            double greville = 0;
            for (int i = j; i < j + degree; ++i) {
                greville += flat[i];
            }
            const double fraction = (greville / degree - flat.front()) / span;
            double kStart = startA + (startB - startA) * fraction;
            double kEnd = endA + (endB - endA) * fraction;
            if (closed) {
                // the fitted edges are parameterised by the fractions, 0 to 1
                const gp_Pnt p = curve0->Value(fraction);
                const gp_Pnt q = curve1->Value(fraction);
                kStart = startMagnitude * tangentLength(p, q, normal0);
                kEnd = endMagnitude * tangentLength(p, q, normal1);
            }
            if (legacy) {
                kStart = startMagnitude * distance0 * legacyTangentPerDistance;
                kEnd = endMagnitude * distance1 * legacyTangentPerDistance;
            }
            const gp_XYZ tangent0 = gp_Vec(normal0).XYZ() * kStart;
            const gp_XYZ tangent1 = gp_Vec(normal1).XYZ() * kEnd;
            const gp_XYZ p0 = row0(j).XYZ();
            const gp_XYZ p3 = row3(j).XYZ();
            gp_XYZ p1;
            gp_XYZ p2;
            if (start && end) {
                p1 = p0 + tangent0 / 3;
                p2 = p3 - tangent1 / 3;
            }
            else if (start) {
                p1 = p0 + tangent0 / 3;
                p2 = (p1 + p3) / 2;
            }
            else {
                p2 = p3 - tangent1 / 3;
                p1 = (p0 + p2) / 2;
            }
            poles(j, 1) = gp_Pnt(p0);
            poles(j, 2) = gp_Pnt(p1);
            poles(j, 3) = gp_Pnt(p2);
            poles(j, 4) = gp_Pnt(p3);
        }
        TColStd_Array1OfReal vKnots(1, 2);
        TColStd_Array1OfInteger vMults(1, 2);
        vKnots(1) = 0;
        vKnots(2) = 1;
        vMults(1) = 4;
        vMults(2) = 4;
        Handle(Geom_BSplineSurface) side
            = new Geom_BSplineSurface(poles, uKnots, vKnots, uMults, vMults, profiler.Degree(), 3);
        BRepBuilderAPI_MakeFace maker(side, Precision::Confusion());
        if (!maker.IsDone()) {
            throw Base::CADKernelError("Loft: failed to make a side face");
        }
        oldFaces.push_back(face);
        newFaces.push_back(maker.Face());
    }

    BRepBuilderAPI_Sewing sewer(1e-6);
    for (const auto& face : newFaces) {
        sewer.Add(face);
    }
    sewer.Perform();
    const TopoDS_Shape sewn = sewer.SewedShape();

    // the names: each old face, edge and vertex is modified into its counterpart
    Handle(BRepTools_History) history = new BRepTools_History;
    for (size_t i = 0; i < oldFaces.size(); ++i) {
        TopoDS_Shape face = sewer.Modified(newFaces[i]);
        if (face.IsNull()) {
            face = newFaces[i];
        }
        history->AddModified(oldFaces[i], face);
    }
    auto ends = [](const TopoDS_Edge& edge) {
        BRepAdaptor_Curve curve(edge);
        return std::array<gp_Pnt, 3> {
            curve.Value(curve.FirstParameter()),
            curve.Value(curve.LastParameter()),
            curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2)
        };
    };
    TopTools_IndexedMapOfShape newEdges;
    TopExp::MapShapes(sewn, TopAbs_EDGE, newEdges);
    TopTools_IndexedMapOfShape oldEdges;
    TopExp::MapShapes(ruled.getShape(), TopAbs_EDGE, oldEdges);
    for (int i = 1; i <= oldEdges.Extent(); ++i) {
        const TopoDS_Edge& oldEdge = TopoDS::Edge(oldEdges(i));
        if (BRep_Tool::Degenerated(oldEdge)) {
            continue;
        }
        const auto o = ends(oldEdge);
        int best = 0;
        double bestMiddle = 0;
        for (int j = 1; j <= newEdges.Extent(); ++j) {
            const TopoDS_Edge& newEdge = TopoDS::Edge(newEdges(j));
            if (BRep_Tool::Degenerated(newEdge)) {
                continue;
            }
            const auto n = ends(newEdge);
            const bool same = (o[0].Distance(n[0]) < 1e-6 && o[1].Distance(n[1]) < 1e-6)
                || (o[0].Distance(n[1]) < 1e-6 && o[1].Distance(n[0]) < 1e-6);
            if (!same) {
                continue;
            }
            const double middle = o[2].Distance(n[2]);
            if (!best || middle < bestMiddle) {
                best = j;
                bestMiddle = middle;
            }
        }
        if (best) {
            history->AddModified(oldEdge, newEdges(best));
        }
    }
    TopTools_IndexedMapOfShape newVertices;
    TopExp::MapShapes(sewn, TopAbs_VERTEX, newVertices);
    TopTools_IndexedMapOfShape oldVertices;
    TopExp::MapShapes(ruled.getShape(), TopAbs_VERTEX, oldVertices);
    for (int i = 1; i <= oldVertices.Extent(); ++i) {
        const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(oldVertices(i)));
        for (int j = 1; j <= newVertices.Extent(); ++j) {
            if (BRep_Tool::Pnt(TopoDS::Vertex(newVertices(j))).Distance(point) < 1e-6) {
                history->AddModified(oldVertices(i), newVertices(j));
                break;
            }
        }
    }
    Part::TopoShape result(ruled.Tag, ruled.Hasher);
    result.makeShapeWithElementMap(sewn, Part::MapperHistory(history), {ruled});
    return result;
}

/// ops#640 (oracle 17 LE3): Onshape refuses a condition whose side face passes through a profile's
/// face (LOFT_INVALID, e.g. a negative magnitude on a narrowing loft). A side point behind a
/// profile's plane whose foot on that plane lies inside the cap there is such a crossing. A side
/// that only bulges past a plane outside its cap (a widening loft) is a valid solid and stays.
bool crossesACap(const TopoDS_Shape& solid, const TopoDS_Shape& first, const TopoDS_Shape& last)
{
    gp_Pln planes[2];
    if (!Part::TopoShape(first).findPlane(planes[0])
        || !Part::TopoShape(last).findPlane(planes[1])) {
        return false;
    }
    // each plane's inside: towards the other profile
    const gp_Vec across(wireCentre(first), wireCentre(last));
    gp_Dir inward[2] = {planes[0].Axis().Direction(), planes[1].Axis().Direction()};
    if (across.Dot(gp_Vec(inward[0])) < 0) {
        inward[0].Reverse();
    }
    if (across.Dot(gp_Vec(inward[1])) > 0) {
        inward[1].Reverse();
    }
    std::vector<TopoDS_Face> caps[2];
    std::vector<TopoDS_Face> sides;
    for (TopExp_Explorer x(solid, TopAbs_FACE); x.More(); x.Next()) {
        const TopoDS_Face& face = TopoDS::Face(x.Current());
        BRepAdaptor_Surface surface(face);
        bool cap = false;
        if (surface.GetType() == GeomAbs_Plane) {
            const gp_Pln plane = surface.Plane();
            for (int i = 0; i < 2 && !cap; ++i) {
                if (planes[i].Distance(plane.Location()) < 1e-6
                    && plane.Axis().Direction().IsParallel(planes[i].Axis().Direction(), 1e-7)) {
                    caps[i].push_back(face);
                    cap = true;
                }
            }
        }
        if (!cap) {
            sides.push_back(face);
        }
    }
    // across the faces: evenly, plus rows close to both ends, where a small negative magnitude's dip
    // behind a plane ends early (v ~ 2 |k| / 3 h)
    constexpr int rows = 24;
    std::vector<double> spans;
    for (int j = 0; j <= 48; ++j) {
        spans.push_back(j / 48.0);
    }
    for (double v : {1e-5, 1e-4, 1e-3, 3e-3, 1e-2}) {
        spans.push_back(v);
        spans.push_back(1 - v);
    }
    for (const auto& face : sides) {
        BRepAdaptor_Surface surface(face);
        double u0 = 0;
        double u1 = 0;
        double v0 = 0;
        double v1 = 0;
        BRepTools::UVBounds(face, u0, u1, v0, v1);
        // ops#963 B: a flat side is a plane (makeLoftCanonical), whose UV bounds are its
        // pcurves' box, not the face: only the samples on the face count there. A B-spline
        // side's domain is the face itself, as before
        const bool trimmed = surface.GetType() == GeomAbs_Plane;
        for (int i = 0; i <= rows; ++i) {
            for (double v : spans) {
                const gp_Pnt2d uv(u0 + (u1 - u0) * i / rows, v0 + (v1 - v0) * v);
                if (trimmed
                    && BRepClass_FaceClassifier(face, uv, Precision::Confusion()).State()
                        == TopAbs_OUT) {
                    continue;
                }
                const gp_Pnt point = surface.Value(uv.X(), uv.Y());
                for (int k = 0; k < 2; ++k) {
                    const double depth = gp_Vec(planes[k].Location(), point).Dot(gp_Vec(inward[k]));
                    if (depth > -1e-6) {
                        continue;  // on the inside of this profile's plane
                    }
                    const gp_Pnt foot = point.Translated(gp_Vec(inward[k]) * -depth);
                    for (const auto& cap : caps[k]) {
                        BRepClass_FaceClassifier classifier(cap, foot, 1e-7);
                        if (classifier.State() == TopAbs_IN) {
                            return true;
                        }
                    }
                }
            }
        }
    }
    return false;
}

/// ops#655: a profile that is one closed periodic edge (a circle, an ellipse) keeps its seam vertex
/// where the sketch put it, and ThruSections splits the other profile there too: an extra side face
/// (7 faces where Onshape has 6 for a square to a circle, GB12 (c)). Move the seam to where
/// ThruSections maps the neighbouring profile's first vertex onto it (the ray from this profile's
/// centre along that vertex's direction from its own centre), so the vertices pair up one to one.
/// The surface is the same; the old edge's and vertex's names carry over as modified.
Part::TopoShape reseamed(const Part::TopoShape& wire, const Part::TopoShape& neighbour)
{
    if (wire.isNull() || neighbour.isNull() || wire.getShape().ShapeType() != TopAbs_WIRE
        || neighbour.getShape().ShapeType() != TopAbs_WIRE) {
        return wire;
    }
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(wire.getShape(), TopAbs_EDGE, edges);
    TopTools_IndexedMapOfShape neighbourVertices;
    TopExp::MapShapes(neighbour.getShape(), TopAbs_VERTEX, neighbourVertices);
    if (edges.Extent() != 1 || neighbourVertices.Extent() < 2) {
        return wire;
    }
    TopoDS_Edge edge;
    for (TopExp_Explorer xp(wire.getShape(), TopAbs_EDGE); xp.More(); xp.Next()) {
        edge = TopoDS::Edge(xp.Current());  // with its orientation in the wire
        break;
    }
    const TopoDS_Vertex seam = TopExp::FirstVertex(edge);
    if (seam.IsNull() || !seam.IsSame(TopExp::LastVertex(edge))) {
        return wire;
    }
    double first = 0;
    double last = 0;
    TopLoc_Location location;
    Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, location, first, last);
    if (curve.IsNull() || !curve->IsPeriodic()) {
        return wire;
    }
    if (!location.IsIdentity()) {
        curve = Handle(Geom_Curve)::DownCast(curve->Transformed(location.Transformation()));
    }
    const double period = curve->Period();
    if (std::abs(last - first - period) > Precision::PConfusion()) {
        return wire;
    }

    // the profile's plane normal (Newell) and centre
    constexpr int samples = 360;
    std::vector<gp_Pnt> points;
    points.reserve(samples);
    for (int i = 0; i < samples; ++i) {
        points.push_back(curve->Value(first + period * i / samples));
    }
    gp_XYZ newell(0, 0, 0);
    for (int i = 0; i < samples; ++i) {
        newell += points[i].XYZ().Crossed(points[(i + 1) % samples].XYZ());
    }
    if (newell.Modulus() < Precision::Confusion()) {
        return wire;
    }
    const gp_Vec normal(newell.Normalized());
    const gp_Pnt centre = wireCentre(wire.getShape());

    gp_Vec direction(
        wireCentre(neighbour.getShape()),
        BRep_Tool::Pnt(TopoDS::Vertex(neighbourVertices(1)))
    );
    direction -= normal * direction.Dot(normal);
    if (direction.Magnitude() < Precision::Confusion()) {
        return wire;
    }
    direction.Normalize();

    // the crossing: the sample nearest the ray's direction, then bisect the side the ray is on
    auto side = [&](double u) {
        return normal.Dot(gp_Vec(centre, curve->Value(u)).Crossed(direction));
    };
    int best = 0;
    double bestCos = -2;
    for (int i = 0; i < samples; ++i) {
        gp_Vec radius(centre, points[i]);
        if (radius.Magnitude() < Precision::Confusion()) {
            continue;
        }
        const double c = radius.Normalized().Dot(direction);
        if (c > bestCos) {
            bestCos = c;
            best = i;
        }
    }
    if (bestCos < 0.5) {
        return wire;  // no crossing nearby: leave it
    }
    const double step = period / samples;
    double a = first + step * (best - 1);
    double b = first + step * (best + 1);
    double fa = side(a);
    if (fa * side(b) > 0) {
        return wire;
    }
    for (int i = 0; i < 100 && b - a > Precision::PConfusion() * 1e-3; ++i) {
        const double m = (a + b) / 2;
        const double fm = side(m);
        if ((fm < 0) == (fa < 0)) {
            a = m;
            fa = fm;
        }
        else {
            b = m;
        }
    }
    const double u = (a + b) / 2;
    if (curve->Value(u).Distance(BRep_Tool::Pnt(seam)) < Precision::Confusion()) {
        return wire;  // already there
    }

    TopoDS_Edge newEdge = BRepBuilderAPI_MakeEdge(curve, u, u + period).Edge();
    newEdge.Orientation(edge.Orientation());
    const TopoDS_Wire newWire = BRepBuilderAPI_MakeWire(newEdge).Wire();

    Part::ShapeMapper mapper;
    mapper.insert(Part::MappingStatus::Modified, edge, newEdge);
    mapper.insert(Part::MappingStatus::Modified, seam, TopExp::FirstVertex(newEdge));
    Part::TopoShape result(wire.Tag, wire.Hasher);
    result.makeShapeWithElementMap(newWire, mapper, {wire});
    return result;
}

/// Each one-edge closed profile in a loft's sections gets its seam at the nearest polygon-like
/// section's first vertex (previous one first); point sections and all-circle lofts are left as they are.
void reseamSections(std::vector<Part::TopoShape>& sections)
{
    auto isPolygonal = [](const Part::TopoShape& s) {
        if (s.isNull() || s.getShape().ShapeType() != TopAbs_WIRE) {
            return false;
        }
        TopTools_IndexedMapOfShape vertices;
        TopExp::MapShapes(s.getShape(), TopAbs_VERTEX, vertices);
        return vertices.Extent() >= 2;
    };
    const int count = static_cast<int>(sections.size());
    for (int i = 0; i < count; ++i) {
        if (isPolygonal(sections[i])) {
            continue;
        }
        for (int d = 1; d < count; ++d) {
            const int j = i - d >= 0 && isPolygonal(sections[i - d]) ? i - d
                : i + d < count && isPolygonal(sections[i + d])      ? i + d
                                                                      : -1;
            if (j >= 0) {
                sections[i] = reseamed(sections[i], sections[j]);
                break;
            }
        }
    }
}

// ops#640: Onshape's loft connections (notes/loft-connections.md). A connection joins one vertex of
// the profile to one vertex of the section. ThruSections' compatibility step picks the wires'
// origins itself, so a connected loft matches the two loops here and builds with the step off.

constexpr double connectionTolerance = 1e-6;

/// A loop's edges in traversal order, each oriented as traversed.
std::vector<TopoDS_Edge> loopEdges(const TopoDS_Shape& wire)
{
    std::vector<TopoDS_Edge> edges;
    for (BRepTools_WireExplorer x(TopoDS::Wire(wire)); x.More(); x.Next()) {
        edges.push_back(x.Current());
    }
    return edges;
}

gp_Pnt startPoint(const TopoDS_Edge& edge)
{
    return BRep_Tool::Pnt(TopExp::FirstVertex(edge, Standard_True));
}

double edgeLength(const TopoDS_Edge& edge)
{
    BRepAdaptor_Curve curve(edge);
    return GCPnts_AbscissaPoint::Length(curve);
}

/// Points along the loop in traversal order, 16 per edge.
std::vector<gp_Pnt> loopSamples(const std::vector<TopoDS_Edge>& edges)
{
    std::vector<gp_Pnt> points;
    constexpr int perEdge = 16;
    for (const auto& edge : edges) {
        BRepAdaptor_Curve curve(edge);
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        const bool reversed = edge.Orientation() == TopAbs_REVERSED;
        for (int k = 0; k < perEdge; ++k) {
            const double t = static_cast<double>(k) / perEdge;
            points.push_back(curve.Value(reversed ? last - t * (last - first) : first + t * (last - first)));
        }
    }
    return points;
}

/// Newell's area vector: its direction is the loop's normal by the right-hand rule.
gp_Vec areaVector(const std::vector<gp_Pnt>& points)
{
    gp_XYZ sum(0, 0, 0);
    for (size_t i = 0; i < points.size(); ++i) {
        sum += points[i].XYZ().Crossed(points[(i + 1) % points.size()].XYZ());
    }
    return gp_Vec(sum / 2);
}

gp_Pnt meanPoint(const std::vector<gp_Pnt>& points)
{
    gp_XYZ sum(0, 0, 0);
    for (const auto& p : points) {
        sum += p.XYZ();
    }
    return gp_Pnt(sum / std::max<size_t>(points.size(), 1));
}

std::vector<TopoDS_Edge> reversedLoop(const std::vector<TopoDS_Edge>& edges)
{
    std::vector<TopoDS_Edge> result;
    for (auto it = edges.rbegin(); it != edges.rend(); ++it) {
        result.push_back(TopoDS::Edge(it->Reversed()));
    }
    return result;
}

int vertexIndex(const std::vector<TopoDS_Edge>& edges, const gp_Pnt& point)
{
    for (size_t i = 0; i < edges.size(); ++i) {
        if (startPoint(edges[i]).Distance(point) < connectionTolerance) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

bool hasVertexAt(const Part::TopoShape& wire, const gp_Pnt& point)
{
    for (TopExp_Explorer x(wire.getShape(), TopAbs_VERTEX); x.More(); x.Next()) {
        if (BRep_Tool::Pnt(TopoDS::Vertex(x.Current())).Distance(point) < connectionTolerance) {
            return true;
        }
    }
    return false;
}

/// The edge cut at the given fractions of its length from where its traversal starts (sorted,
/// strictly inside 0..1). The pieces come in traversal order, oriented as traversed; each piece is
/// recorded as modified from the edge and each new vertex as generated from it.
std::vector<TopoDS_Edge> splitEdge(
    const TopoDS_Edge& edge,
    const std::vector<double>& fractions,
    Part::ShapeMapper& mapper
)
{
    if (fractions.empty()) {
        return {edge};
    }
    BRepAdaptor_Curve adaptor(edge);
    const bool reversed = edge.Orientation() == TopAbs_REVERSED;
    const double length = GCPnts_AbscissaPoint::Length(adaptor);
    std::vector<double> params;
    for (double t : fractions) {
        GCPnts_AbscissaPoint at(
            adaptor,
            reversed ? -t * length : t * length,
            reversed ? adaptor.LastParameter() : adaptor.FirstParameter()
        );
        if (!at.IsDone()) {
            throw Base::CADKernelError(
                QT_TRANSLATE_NOOP("Exception", "Loft: a profile edge could not be split for the connections")
            );
        }
        params.push_back(at.Parameter());
    }
    std::sort(params.begin(), params.end());

    double first = 0;
    double last = 0;
    const Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);  // located copy
    const auto forward = TopoDS::Edge(edge.Oriented(TopAbs_FORWARD));
    std::vector<TopoDS_Vertex> vertices {TopExp::FirstVertex(forward)};
    std::vector<double> us {first};
    for (double u : params) {
        TopoDS_Vertex vertex = BRepBuilderAPI_MakeVertex(curve->Value(u)).Vertex();
        mapper.insert(Part::MappingStatus::Generated, edge, vertex);
        vertices.push_back(vertex);
        us.push_back(u);
    }
    vertices.push_back(TopExp::LastVertex(forward));
    us.push_back(last);

    std::vector<TopoDS_Edge> pieces;
    for (size_t k = 0; k + 1 < vertices.size(); ++k) {
        BRepBuilderAPI_MakeEdge make(curve, vertices[k], vertices[k + 1], us[k], us[k + 1]);
        if (!make.IsDone()) {
            throw Base::CADKernelError(
                QT_TRANSLATE_NOOP("Exception", "Loft: a profile edge could not be split for the connections")
            );
        }
        mapper.insert(Part::MappingStatus::Modified, edge, make.Edge());
        pieces.push_back(make.Edge());
    }
    if (reversed) {
        pieces = reversedLoop(pieces);
    }
    return pieces;
}

/// Each inner vertex's arc length from the chain's start, over the chain's length.
std::vector<double> innerFractions(const std::vector<TopoDS_Edge>& chain, double& total)
{
    std::vector<double> lengths;
    total = 0;
    for (const auto& edge : chain) {
        lengths.push_back(edgeLength(edge));
        total += lengths.back();
    }
    std::vector<double> fractions;
    double sum = 0;
    for (size_t k = 0; k + 1 < chain.size(); ++k) {
        sum += lengths[k];
        fractions.push_back(sum / total);
    }
    return fractions;
}

/// The chain with new vertices at the given fractions of its arc length (sorted, each strictly
/// between two of its vertices). `origins` and `fresh`, when given, get each piece's chain edge and
/// whether the piece starts at a new vertex.
std::vector<TopoDS_Edge> chainWithVertices(
    const std::vector<TopoDS_Edge>& chain,
    const std::vector<double>& at,
    Part::ShapeMapper& mapper,
    std::vector<TopoDS_Edge>* origins = nullptr,
    std::vector<bool>* fresh = nullptr
)
{
    std::vector<double> lengths;
    double total = 0;
    for (const auto& edge : chain) {
        lengths.push_back(edgeLength(edge));
        total += lengths.back();
    }
    std::vector<TopoDS_Edge> result;
    double start = 0;
    size_t next = 0;
    for (size_t k = 0; k < chain.size(); ++k) {
        const double end = start + lengths[k];
        std::vector<double> local;
        while (next < at.size() && (at[next] * total < end || k + 1 == chain.size())) {
            local.push_back(std::clamp((at[next] * total - start) / lengths[k], 1e-9, 1 - 1e-9));
            ++next;
        }
        bool first = true;
        for (const auto& piece : splitEdge(chain[k], local, mapper)) {
            result.push_back(piece);
            if (origins) {
                origins->push_back(chain[k]);
            }
            if (fresh) {
                fresh->push_back(!first);
            }
            first = false;
        }
        start = end;
    }
    return result;
}

/// Pairs a chain of fewer vertices with one of more (both from one connection to the next): the
/// fewer side's inner vertices match the nearest of the other's in order (least total difference of
/// arc-length fractions), and the unmatched vertices between two matched pairs get partners that
/// divide the fewer side's span between those pairs into equal parts by count (Onshape, oracle 14
/// LC1-LC2: thirds, midpoints). `partnersOf` gives each of the more side's inner vertices its partner
/// on the fewer side, or -1; `partnerFractions` the fewer side's new vertex fractions. Every
/// fewer-side vertex is matched, so each such span is one fewer-side edge.
std::vector<int> partnersOf(const std::vector<double>& fewer, const std::vector<double>& more)
{
    const size_t m = fewer.size();
    const size_t n = more.size();
    const double inf = std::numeric_limits<double>::infinity();
    std::vector<std::vector<double>> cost(m + 1, std::vector<double>(n + 1, inf));
    for (size_t j = 0; j <= n; ++j) {
        cost[0][j] = 0;
    }
    for (size_t i = 1; i <= m; ++i) {
        for (size_t j = i; j <= n; ++j) {
            cost[i][j] = std::min(cost[i][j - 1], cost[i - 1][j - 1] + std::abs(fewer[i - 1] - more[j - 1]));
        }
    }
    std::vector<int> partner(n, -1);  // more's vertex -> fewer's, or -1
    for (size_t i = m, j = n; i > 0 && j > 0;) {
        if (cost[i][j] == cost[i][j - 1] && j > i) {
            --j;
        }
        else {
            partner[j - 1] = static_cast<int>(i - 1);
            --i;
            --j;
        }
    }
    return partner;
}

std::vector<double> partnerFractions(const std::vector<double>& fewer, const std::vector<double>& more)
{
    const size_t n = more.size();
    const std::vector<int> partner = partnersOf(fewer, more);
    std::vector<double> added;
    double g0 = 0;  // the fewer side's fraction at the last matched pair (the chain's start first)
    std::vector<size_t> gap;  // the unmatched vertices since then
    auto divide = [&](double g1) {
        for (size_t i = 0; i < gap.size(); ++i) {
            added.push_back(g0 + (g1 - g0) * static_cast<double>(i + 1) / static_cast<double>(gap.size() + 1));
        }
        gap.clear();
        g0 = g1;
    };
    for (size_t j = 0; j < n; ++j) {
        if (partner[j] >= 0) {
            divide(fewer[partner[j]]);
        }
        else {
            gap.push_back(j);
        }
    }
    divide(1.0);
    return added;
}

[[noreturn]] void connectionsCantMatch()
{
    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
        "Exception",
        "Loft: the connections can't be matched (a vertex has two connections, or they cross)"
    ));
}

/// Whether the closed polygon blended index by index from `pa` (t = 0) to `pb` (t = 1), seen along
/// `normal`, crosses itself for some t in (0, 1): crossed connections make two side edges or faces
/// meet (oracle 14 LC4). Each orientation test of two blended segments is quadratic in t, so its
/// roots cut (0, 1) into intervals of constant sign and one test per interval is exact.
bool blendCrossesItself(const std::vector<gp_Pnt>& pa, const std::vector<gp_Pnt>& pb, const gp_Vec& normal)
{
    const size_t n = std::min(pa.size(), pb.size());
    if (n < 4) {
        return false;
    }
    const gp_Ax3 frame(gp::Origin(), gp_Dir(normal));
    const gp_XYZ ux = frame.XDirection().XYZ();
    const gp_XYZ uy = frame.YDirection().XYZ();
    std::vector<gp_XY> a(n), d(n);
    double size = 0;
    for (size_t i = 0; i < n; ++i) {
        a[i] = gp_XY(pa[i].XYZ().Dot(ux), pa[i].XYZ().Dot(uy));
        const gp_XY b(pb[i].XYZ().Dot(ux), pb[i].XYZ().Dot(uy));
        d[i] = b - a[i];
        size = std::max({size, std::abs(a[i].X() - a[0].X()), std::abs(a[i].Y() - a[0].Y()),
                         std::abs(b.X() - a[0].X()), std::abs(b.Y() - a[0].Y())});
    }
    const double tol = 1e-9 * size * size;
    // orient(p, q, r)(t) = (q - p) x (r - p), as c0 + c1 t + c2 t^2
    auto orient = [&](size_t p, size_t q, size_t r) {
        const gp_XY u0 = a[q] - a[p], u1 = d[q] - d[p];
        const gp_XY w0 = a[r] - a[p], w1 = d[r] - d[p];
        return std::array<double, 3> {u0 ^ w0, (u0 ^ w1) + (u1 ^ w0), u1 ^ w1};
    };
    auto value = [](const std::array<double, 3>& c, double t) {
        return c[0] + t * (c[1] + t * c[2]);
    };
    auto roots = [](const std::array<double, 3>& c, std::vector<double>& out) {
        const double scale = std::max({std::abs(c[0]), std::abs(c[1]), std::abs(c[2])});
        if (scale == 0) {
            return;
        }
        if (std::abs(c[2]) < 1e-12 * scale) {
            if (std::abs(c[1]) >= 1e-12 * scale) {
                out.push_back(-c[0] / c[1]);
            }
            return;
        }
        const double disc = c[1] * c[1] - 4 * c[2] * c[0];
        if (disc < 0) {
            return;
        }
        const double s = std::sqrt(disc);
        out.push_back((-c[1] - s) / (2 * c[2]));
        out.push_back((-c[1] + s) / (2 * c[2]));
    };
    auto opposite = [tol](double x, double y) {
        return (x > tol && y < -tol) || (x < -tol && y > tol);
    };
    for (size_t i = 0; i < n; ++i) {
        const size_t i1 = (i + 1) % n;
        for (size_t j = i + 2; j < n; ++j) {
            const size_t j1 = (j + 1) % n;
            if (j1 == i) {
                continue;  // the segments share a vertex
            }
            const std::array<std::array<double, 3>, 4> o {
                orient(i, i1, j), orient(i, i1, j1), orient(j, j1, i), orient(j, j1, i1)};
            std::vector<double> cuts {0.0, 1.0};
            for (const auto& c : o) {
                roots(c, cuts);
            }
            std::sort(cuts.begin(), cuts.end());
            for (size_t k = 0; k + 1 < cuts.size(); ++k) {
                const double t0 = std::max(cuts[k], 0.0), t1 = std::min(cuts[k + 1], 1.0);
                if (t1 - t0 < 1e-12) {
                    continue;
                }
                const double t = (t0 + t1) / 2;
                if (opposite(value(o[0], t), value(o[1], t)) && opposite(value(o[2], t), value(o[3], t))) {
                    return true;
                }
            }
        }
    }
    return false;
}

/// Whether the joint where `in` ends and `out` starts (both in traversal order) is tangent (G1).
bool tangentJoint(const TopoDS_Edge& in, const TopoDS_Edge& out)
{
    auto direction = [](const TopoDS_Edge& edge, bool atEnd) {
        BRepAdaptor_Curve curve(edge);
        const bool reversed = edge.Orientation() == TopAbs_REVERSED;
        const double u = (atEnd != reversed) ? curve.LastParameter() : curve.FirstParameter();
        gp_Pnt p;
        gp_Vec d;
        curve.D1(u, p, d);
        return reversed ? -d : d;
    };
    const gp_Vec a = direction(in, true);
    const gp_Vec b = direction(out, false);
    if (a.Magnitude() < Precision::Confusion() || b.Magnitude() < Precision::Confusion()) {
        return false;
    }
    return a.Angle(b) < 1e-4;
}

/// Whether a chain pair of different edge counts has a tangent joint where ops#729's exact part
/// applies (the shorter chain's inner joints, or the longer's when the shorter is one edge): the
/// gate for `splitLinesMatch`, whose results stay as they were (ops#1046 A).
bool tangentJointsBlock(const std::vector<TopoDS_Edge>& shorter, const std::vector<TopoDS_Edge>& longer)
{
    const auto& inner = shorter.size() > 1 ? shorter : longer;
    for (size_t k = 1; k < inner.size(); ++k) {
        if (tangentJoint(inner[k - 1], inner[k])) {
            return true;
        }
    }
    return false;
}

/// ops#1046 D: the case the matching rule doesn't reproduce (oracle 14 LC3 with two connections:
/// Onshape's answer isn't half-turn symmetric, so no rule that decides a chain from that chain alone
/// gives it). 2+ connections on the loop, the shorter chain of a pair has inner joints and all are
/// tangent, and 2+ tangent joints of the longer chain stay unmatched: a stop until the oracle rows
/// settle it (notes/loft-tangent-joints-1046.md).
bool tangentRunUnmatched(
    const std::vector<TopoDS_Edge>& shorter,
    const std::vector<TopoDS_Edge>& longer,
    const std::vector<double>& shorterFractions,
    const std::vector<double>& longerFractions,
    size_t connections
)
{
    if (connections < 2 || shorter.size() < 2) {
        return false;
    }
    for (size_t k = 1; k < shorter.size(); ++k) {
        if (!tangentJoint(shorter[k - 1], shorter[k])) {
            return false;
        }
    }
    const std::vector<int> partner = partnersOf(shorterFractions, longerFractions);
    int unmatched = 0;
    for (size_t j = 0; j < partner.size(); ++j) {
        if (partner[j] < 0 && tangentJoint(longer[j], longer[j + 1])) {
            ++unmatched;
        }
    }
    return unmatched >= 2;
}

bool isLine(const TopoDS_Edge& edge)
{
    return BRepAdaptor_Curve(edge).GetType() == GeomAbs_Line;
}

/// Whether the edge is straight whatever its curve type: a line, or a B-spline or Bezier whose
/// poles all lie on the line through the edge's ends (relative to its length). The curve lies in
/// its poles' hull, so collinear poles bound it to that line.
bool isStraight(const TopoDS_Edge& edge)
{
    BRepAdaptor_Curve curve(edge);
    std::vector<gp_Pnt> poles;
    switch (curve.GetType()) {
        case GeomAbs_Line:
            return true;
        case GeomAbs_BSplineCurve: {
            const Handle(Geom_BSplineCurve) spline = curve.BSpline();
            for (int i = 1; i <= spline->NbPoles(); ++i) {
                poles.push_back(spline->Pole(i));
            }
            break;
        }
        case GeomAbs_BezierCurve: {
            const Handle(Geom_BezierCurve) bezier = curve.Bezier();
            for (int i = 1; i <= bezier->NbPoles(); ++i) {
                poles.push_back(bezier->Pole(i));
            }
            break;
        }
        default:
            return false;
    }
    const gp_Pnt p0 = BRep_Tool::Pnt(TopExp::FirstVertex(edge));
    const gp_Pnt p1 = BRep_Tool::Pnt(TopExp::LastVertex(edge));
    const double length = p0.Distance(p1);
    if (length < Precision::Confusion()) {
        return false;
    }
    const gp_Lin line(p0, gp_Dir(gp_Vec(p0, p1)));
    const double tolerance = std::max(Precision::Confusion(), 1e-9 * length);
    return std::ranges::all_of(poles, [&](const gp_Pnt& pole) { return line.Distance(pole) <= tolerance; });
}

gp_Pnt endPoint(const TopoDS_Edge& edge)
{
    return BRep_Tool::Pnt(TopExp::LastVertex(edge, Standard_True));
}

/// ops#729, the exact part of option (a): a vertex that only splits a straight line in two (the
/// lines on either side collinear) is no corner to match. Between two connections, the chains with
/// such runs of lines merged must have as many edges; each merged run must pair with a straight
/// line (or a run) in one plane with it, so the side face between them is that plane wherever the
/// split vertices pair. Then each such pair takes every split vertex of either side at the same
/// fraction of its length, and the chains pair edge i with edge i. Returns false, the chains as
/// they were, when that doesn't hold (Onshape's rule for tangent joints is the open part of ops#729).
bool splitLinesMatch(
    std::vector<TopoDS_Edge>& chainA,
    std::vector<TopoDS_Edge>& chainB,
    Part::ShapeMapper& mapperA,
    Part::ShapeMapper& mapperB,
    std::vector<TopoDS_Edge>& originsA,
    std::vector<TopoDS_Edge>& originsB,
    std::vector<bool>& freshA,
    std::vector<bool>& freshB
)
{
    auto runsOf = [](const std::vector<TopoDS_Edge>& chain) {
        std::vector<std::vector<TopoDS_Edge>> runs;
        for (size_t k = 0; k < chain.size(); ++k) {
            const bool splitsALine = k > 0 && isLine(chain[k - 1]) && isLine(chain[k])
                && tangentJoint(chain[k - 1], chain[k]);
            if (!splitsALine) {
                runs.emplace_back();
            }
            runs.back().push_back(chain[k]);
        }
        return runs;
    };
    const auto runsA = runsOf(chainA);
    const auto runsB = runsOf(chainB);
    if (runsA.size() != runsB.size() || (runsA.size() == chainA.size() && runsB.size() == chainB.size())) {
        return false;
    }
    auto allLines = [](const std::vector<TopoDS_Edge>& run) {
        return std::ranges::all_of(run, isLine);
    };
    for (size_t k = 0; k < runsA.size(); ++k) {
        const auto& ra = runsA[k];
        const auto& rb = runsB[k];
        if (ra.size() == 1 && rb.size() == 1) {
            continue;
        }
        if (!allLines(ra) || !allLines(rb)) {
            return false;
        }
        // the two lines in one plane
        const gp_Pnt p0 = startPoint(ra.front());
        const gp_Vec u(p0, endPoint(ra.back()));
        const gp_Vec w0(p0, startPoint(rb.front()));
        const gp_Vec w1(p0, endPoint(rb.back()));
        const double spread = std::max(u.Crossed(w0).Magnitude(), u.Crossed(w1).Magnitude());
        if (spread > Precision::Confusion() * Precision::Confusion()
            && std::abs(u.Dot(w0.Crossed(w1))) / spread > Precision::Confusion()) {
            return false;
        }
    }
    std::vector<TopoDS_Edge> edgesA, edgesB, oA, oB;
    std::vector<bool> fA, fB;
    for (size_t k = 0; k < runsA.size(); ++k) {
        const auto& ra = runsA[k];
        const auto& rb = runsB[k];
        if (ra.size() == 1 && rb.size() == 1) {
            edgesA.push_back(ra.front());
            edgesB.push_back(rb.front());
            oA.push_back(ra.front());
            oB.push_back(rb.front());
            fA.push_back(false);
            fB.push_back(false);
            continue;
        }
        double lengthA = 0, lengthB = 0;
        const auto fa = innerFractions(ra, lengthA);
        const auto fb = innerFractions(rb, lengthB);
        // the other side's split fractions that this side lacks
        auto lacking = [](const std::vector<double>& own, const std::vector<double>& other) {
            std::vector<double> added;
            for (double f : other) {
                if (std::ranges::none_of(own, [f](double g) { return std::abs(f - g) < 1e-9; })) {
                    added.push_back(f);
                }
            }
            return added;
        };
        for (const auto& edge : chainWithVertices(ra, lacking(fa, fb), mapperA, &oA, &fA)) {
            edgesA.push_back(edge);
        }
        for (const auto& edge : chainWithVertices(rb, lacking(fb, fa), mapperB, &oB, &fB)) {
            edgesB.push_back(edge);
        }
    }
    if (edgesA.size() != edgesB.size()) {
        return false;
    }
    chainA = std::move(edgesA);
    chainB = std::move(edgesB);
    originsA = std::move(oA);
    originsB = std::move(oB);
    freshA = std::move(fA);
    freshB = std::move(fB);
    return true;
}

/// Whether the section's loop runs the profile's way round (> 0) or must be reversed (< 0); 0 when
/// that can't be told. Profiles at a right angle (an elbow) compare their normals along the line
/// between their centres.
double loopSense(
    const std::vector<gp_Pnt>& samplesA,
    const std::vector<gp_Pnt>& samplesB,
    const gp_Vec& na,
    const gp_Vec& nb
)
{
    double sense = na.Dot(nb) / (na.Magnitude() * nb.Magnitude());
    if (std::abs(sense) < 1e-3) {
        const gp_Vec d(meanPoint(samplesA), meanPoint(samplesB));
        sense = na.Dot(d) * nb.Dot(d);
        if (std::abs(sense) < Precision::Confusion()) {
            return 0;
        }
    }
    return sense;
}

/// Whether the loops paired edge i to edge i (the section's already run the profile's way round,
/// `sense` < 0 when it was reversed for that) turn the loft through itself.
// Onshape's LOFT_INVALID (oracle 14 LC1, LC4): pairs that turn the loft through itself, a half
// turn or crossed connections. The ruled section between paired points, seen along the normal
// halfway between the profiles' (so an elbow's profiles both stay open), must keep the profiles'
// sense, its area above 1 % of the smaller profile's, and must never cross itself.
bool turnsThroughItself(
    const std::vector<TopoDS_Edge>& edgesA,
    const std::vector<TopoDS_Edge>& edgesB,
    const gp_Vec& na,
    const gp_Vec& nb,
    double sense
)
{
    auto sampled = [](const std::vector<TopoDS_Edge>& edges) {
        std::vector<gp_Pnt> points;
        constexpr int perEdge = 8;
        for (const auto& edge : edges) {
            BRepAdaptor_Curve curve(edge);
            const bool reversed = edge.Orientation() == TopAbs_REVERSED;
            const double length = GCPnts_AbscissaPoint::Length(curve);
            const double from = reversed ? curve.LastParameter() : curve.FirstParameter();
            for (int k = 0; k < perEdge; ++k) {
                const double s = length * k / perEdge;
                GCPnts_AbscissaPoint at(curve, reversed ? -s : s, from);
                points.push_back(curve.Value(at.IsDone() ? at.Parameter() : from));
            }
        }
        return points;
    };
    const auto pa = sampled(edgesA);
    const auto pb = sampled(edgesB);
    const gp_Vec normal = (na.Normalized() + (sense < 0 ? -nb : nb).Normalized()).Normalized();
    const double smaller = std::min(std::abs(na.Dot(normal)), std::abs(nb.Dot(normal)));
    // Newell's area of the blended polygon is exactly quadratic in t (each p_i x p_i+1 is), so
    // three samples give it everywhere and its minimum over [0, 1] is exact: a half turn between
    // profiles of different size only touches zero, between any fixed samples.
    auto areaAt = [&](double t) {
        std::vector<gp_Pnt> section;
        for (size_t i = 0; i < pa.size() && i < pb.size(); ++i) {
            section.emplace_back(pa[i].XYZ() * (1 - t) + pb[i].XYZ() * t);
        }
        return areaVector(section).Dot(normal);
    };
    const double a0 = areaAt(0.0);
    const double a1 = areaAt(1.0);
    const double mid = 2 * areaAt(0.5) - (a0 + a1) / 2;  // Bernstein middle coefficient
    // The ends are the profiles; a dip below them has its vertex inside (0, 1).
    double lowest = std::numeric_limits<double>::infinity();
    const double curvature = a0 - 2 * mid + a1;
    if (curvature > 0) {
        const double t = (a0 - mid) / curvature;
        if (t > 0 && t < 1) {
            lowest = (1 - t) * (1 - t) * a0 + 2 * t * (1 - t) * mid + t * t * a1;
        }
    }
    return lowest < 0.01 * smaller || blendCrossesItself(pa, pb, normal);
}

/// A closed wire of the loop's edges, named from `source` (split pieces through `mapper`)
Part::TopoShape loopWire(
    const std::vector<TopoDS_Edge>& edges,
    const Part::ShapeMapper& mapper,
    const Part::TopoShape& source
)
{
    BRep_Builder builder;
    TopoDS_Wire wire;
    builder.MakeWire(wire);
    for (const auto& edge : edges) {
        builder.Add(wire, edge);
    }
    wire.Closed(Standard_True);
    Part::TopoShape result(source.Tag, source.Hasher);
    result.makeShapeWithElementMap(wire, mapper, {source});
    return result;
}

/// Two loops matched for the connections: edge i of one pairs with edge i of the other, and side
/// edge i joins their start vertices. Each edge's origin is the profile edge it is a piece of
/// (itself when not split), and `fresh` says whether its start vertex is a new one.
struct LoopMatch
{
    Part::TopoShape wireA, wireB;
    std::vector<TopoDS_Edge> edgesA, edgesB, originA, originB;
    std::vector<bool> freshA, freshB;
    bool fractionVertices = false;  // vertices added by arc-length fraction (ops#1046 A)
    Part::ShapeMapper mapperA, mapperB;
    Part::TopoShape profile, section;
};

/// The two loops matched for the connections (points in the loops' frame, profile first): the
/// section runs the profile's way round, both start at a connection, and between consecutive
/// connections both have the same number of edges. Edge i of one pairs with edge i of the other.
LoopMatch connectedLoops(
    const Part::TopoShape& profile,
    const Part::TopoShape& section,
    std::vector<std::pair<gp_Pnt, gp_Pnt>> connections
)
{
    auto a = loopEdges(profile.getShape());
    auto b = loopEdges(section.getShape());
    if (a.empty() || b.empty() || !BRep_Tool::IsClosed(profile.getShape())
        || !BRep_Tool::IsClosed(section.getShape())) {
        throw Base::CADKernelError(
            QT_TRANSLATE_NOOP("Exception", "Loft: connections need closed profiles")
        );
    }

    // the section's loop runs the profile's way round
    const auto samplesA = loopSamples(a);
    const auto samplesB = loopSamples(b);
    const gp_Vec na = areaVector(samplesA);
    const gp_Vec nb = areaVector(samplesB);
    if (na.Magnitude() < Precision::Confusion() || nb.Magnitude() < Precision::Confusion()) {
        throw Base::CADKernelError(
            QT_TRANSLATE_NOOP("Exception", "Loft: connections need profiles that enclose an area")
        );
    }
    const double sense = loopSense(samplesA, samplesB, na, nb);
    if (sense == 0) {
        connectionsCantMatch();
    }
    if (sense < 0) {
        b = reversedLoop(b);
    }

    // each connection's vertices, at most one connection per vertex, in the same order round both
    std::vector<std::pair<int, int>> indices;
    std::set<int> usedA, usedB;
    for (const auto& [p, q] : connections) {
        const int i = vertexIndex(a, p);
        const int j = vertexIndex(b, q);
        if (i < 0 || j < 0) {
            throw Base::CADKernelError(
                QT_TRANSLATE_NOOP("Exception", "Loft: a connection's vertex is not on its profile")
            );
        }
        if (!usedA.insert(i).second || !usedB.insert(j).second) {
            connectionsCantMatch();
        }
        indices.emplace_back(i, j);
    }
    std::sort(indices.begin(), indices.end());
    const int na0 = static_cast<int>(a.size());
    const int nb0 = static_cast<int>(b.size());
    const auto [i0, j0] = indices.front();
    std::rotate(a.begin(), a.begin() + i0, a.end());
    std::rotate(b.begin(), b.begin() + j0, b.end());
    std::vector<int> cutsA, cutsB;
    for (const auto& [i, j] : indices) {
        cutsA.push_back((i - i0 + na0) % na0);
        cutsB.push_back((j - j0 + nb0) % nb0);
    }
    for (size_t k = 1; k < cutsB.size(); ++k) {
        if (cutsB[k] <= cutsB[k - 1]) {
            connectionsCantMatch();
        }
    }
    cutsA.push_back(na0);
    cutsB.push_back(nb0);

    // chain by chain, the same number of edges
    LoopMatch match;
    match.profile = profile;
    match.section = section;
    for (size_t k = 0; k + 1 < cutsA.size(); ++k) {
        std::vector<TopoDS_Edge> chainA(a.begin() + cutsA[k], a.begin() + cutsA[k + 1]);
        std::vector<TopoDS_Edge> chainB(b.begin() + cutsB[k], b.begin() + cutsB[k + 1]);
        std::vector<TopoDS_Edge> originsA = chainA, originsB = chainB;
        std::vector<bool> freshA(chainA.size(), false), freshB(chainB.size(), false);
        const bool blocked = chainA.size() != chainB.size()
            && (chainA.size() < chainB.size() ? tangentJointsBlock(chainA, chainB)
                                              : tangentJointsBlock(chainB, chainA));
        if (blocked
            && splitLinesMatch(
                chainA, chainB, match.mapperA, match.mapperB, originsA, originsB, freshA, freshB
            )) {
            // ops#729: split straight lines matched; edge i pairs with edge i
        }
        else if (chainA.size() != chainB.size()) {
            double lengthA = 0, lengthB = 0;
            const auto fa = innerFractions(chainA, lengthA);
            const auto fb = innerFractions(chainB, lengthB);
            const bool aShorter = chainA.size() < chainB.size();
            if (aShorter ? tangentRunUnmatched(chainA, chainB, fa, fb, connections.size())
                         : tangentRunUnmatched(chainB, chainA, fb, fa, connections.size())) {
                throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Loft: between two connections a run of tangent joints faces one with more "
                    "tangent joints; connections can't match these as Onshape does yet"
                ));
            }
            // ops#1046 A: the vertices match by arc-length fraction whatever the joints (Onshape,
            // RB44/RB47); which side edges stay is decided after the loft (`mergeSmoothRuns`)
            if (aShorter) {
                originsA.clear();
                freshA.clear();
                chainA = chainWithVertices(chainA, partnerFractions(fa, fb), match.mapperA, &originsA, &freshA);
            }
            else {
                originsB.clear();
                freshB.clear();
                chainB = chainWithVertices(chainB, partnerFractions(fb, fa), match.mapperB, &originsB, &freshB);
            }
            match.fractionVertices = match.fractionVertices
                || std::ranges::find(aShorter ? freshA : freshB, true) != (aShorter ? freshA : freshB).end();
        }
        match.edgesA.insert(match.edgesA.end(), chainA.begin(), chainA.end());
        match.edgesB.insert(match.edgesB.end(), chainB.begin(), chainB.end());
        match.originA.insert(match.originA.end(), originsA.begin(), originsA.end());
        match.originB.insert(match.originB.end(), originsB.begin(), originsB.end());
        match.freshA.insert(match.freshA.end(), freshA.begin(), freshA.end());
        match.freshB.insert(match.freshB.end(), freshB.begin(), freshB.end());
    }

    if (turnsThroughItself(match.edgesA, match.edgesB, na, nb, sense)) {
        throw Base::CADKernelError(QT_TRANSLATE_NOOP(
            "Exception",
            "Loft: the connections turn the loft through itself (a half turn, or crossed connections)"
        ));
    }

    match.wireA = loopWire(match.edgesA, match.mapperA, profile);
    match.wireB = loopWire(match.edgesB, match.mapperB, section);
    return match;
}

// ops#1071 (notes/loft-unconnected-design-1071.md): Onshape pairs an unconnected two-profile loft
// with different vertex counts as one chain from a start pair (RB47, RB54, RB124, RB130), where
// OCCT's compatibility step casts polar rays. The start keeps the corners' positions: a pair is
// admitted when the section vertex is the one nearest the profile vertex, each taken from its own
// loop's centre; among those, the least arc-length mismatch of the chain started there, then the
// nearest in space, then the indices.

/// The length-weighted centre of a loop's edges.
gp_Pnt loopCentre(const std::vector<TopoDS_Edge>& edges)
{
    gp_XYZ sum(0, 0, 0);
    double mass = 0;
    for (const auto& edge : edges) {
        GProp_GProps props;
        BRepGProp::LinearProperties(edge, props);
        sum += props.CentreOfMass().XYZ() * props.Mass();
        mass += props.Mass();
    }
    return gp_Pnt(mass > 0 ? sum / mass : sum);
}

/// The sum of |fraction - partner's fraction| over the fewer side's vertices `partnersOf` matches:
/// the cost its table minimises.
double partnerCost(const std::vector<double>& fewer, const std::vector<double>& more)
{
    const std::vector<int> partner = partnersOf(fewer, more);
    double cost = 0;
    for (size_t j = 0; j < partner.size(); ++j) {
        if (partner[j] >= 0) {
            cost += std::abs(fewer[partner[j]] - more[j]);
        }
    }
    return cost;
}

/// The start pairs to try for an unconnected loop pair, best first, one per distinct chain and at
/// most `limit`: (profile vertex, section vertex) in the loops' frame, for `connectedLoops`. Empty
/// when the loops can't be told the same way round.
std::vector<std::pair<gp_Pnt, gp_Pnt>> unconnectedStarts(
    const Part::TopoShape& profile,
    const Part::TopoShape& section,
    size_t limit
)
{
    auto a = loopEdges(profile.getShape());
    auto b = loopEdges(section.getShape());
    if (a.size() < 2 || b.size() < 2 || a.size() == b.size()) {
        return {};
    }
    const auto samplesA = loopSamples(a);
    const auto samplesB = loopSamples(b);
    const gp_Vec na = areaVector(samplesA);
    const gp_Vec nb = areaVector(samplesB);
    if (na.Magnitude() < Precision::Confusion() || nb.Magnitude() < Precision::Confusion()) {
        return {};
    }
    const double sense = loopSense(samplesA, samplesB, na, nb);
    if (sense == 0) {
        return {};
    }
    if (sense < 0) {
        b = reversedLoop(b);
    }
    const int na0 = static_cast<int>(a.size());
    const int nb0 = static_cast<int>(b.size());
    double lengthA = 0, lengthB = 0;
    for (const auto& e : a) {
        lengthA += edgeLength(e);
    }
    for (const auto& e : b) {
        lengthB += edgeLength(e);
    }
    const double size = std::max(lengthA, lengthB);
    const gp_Pnt ca = loopCentre(a);
    const gp_Pnt cb = loopCentre(b);

    struct Candidate
    {
        int i, j;
        double mismatch, distance;
        std::set<std::pair<int, int>> chain;  // the vertex pairs the chain matches
        int mismatchGroup = 0, distanceGroup = 0;
    };
    std::vector<Candidate> candidates;
    for (int i = 0; i < na0; ++i) {
        const gp_Vec ra(ca, startPoint(a[i]));
        std::vector<double> offsets;
        for (int j = 0; j < nb0; ++j) {
            offsets.push_back(ra.Subtracted(gp_Vec(cb, startPoint(b[j]))).Magnitude());
        }
        const double nearest = *std::ranges::min_element(offsets);
        for (int j = 0; j < nb0; ++j) {
            if (offsets[j] > nearest + 1e-7 * size) {
                continue;
            }
            std::vector<TopoDS_Edge> ra0(a), rb0(b);
            std::rotate(ra0.begin(), ra0.begin() + i, ra0.end());
            std::rotate(rb0.begin(), rb0.begin() + j, rb0.end());
            double la = 0, lb = 0;
            const auto fa = innerFractions(ra0, la);
            const auto fb = innerFractions(rb0, lb);
            const bool aFewer = fa.size() < fb.size();
            const auto& fewer = aFewer ? fa : fb;
            const auto& more = aFewer ? fb : fa;
            Candidate c {i, j, partnerCost(fewer, more), startPoint(a[i]).Distance(startPoint(b[j])), {}};
            c.chain.emplace(i, j);
            const std::vector<int> partner = partnersOf(fewer, more);
            for (size_t k = 0; k < partner.size(); ++k) {
                if (partner[k] >= 0) {
                    const int kf = partner[k] + 1;  // inner vertex k of a chain is its vertex k + 1
                    const int km = static_cast<int>(k) + 1;
                    const int ia = (i + (aFewer ? kf : km)) % na0;
                    const int jb = (j + (aFewer ? km : kf)) % nb0;
                    c.chain.emplace(ia, jb);
                }
            }
            candidates.push_back(std::move(c));
        }
    }
    // groups of equal mismatch, inside them of equal distance; then the indices (no tolerant comparator)
    std::ranges::sort(candidates, {}, &Candidate::mismatch);
    for (size_t k = 1, first = 0; k < candidates.size(); ++k) {
        if (candidates[k].mismatch - candidates[first].mismatch > 1e-9) {
            first = k;
            candidates[k].mismatchGroup = candidates[k - 1].mismatchGroup + 1;
        }
        else {
            candidates[k].mismatchGroup = candidates[first].mismatchGroup;
        }
    }
    std::ranges::sort(candidates, [](const Candidate& x, const Candidate& y) {
        return std::tie(x.mismatchGroup, x.distance) < std::tie(y.mismatchGroup, y.distance);
    });
    for (size_t k = 1, first = 0; k < candidates.size(); ++k) {
        if (candidates[k].mismatchGroup != candidates[first].mismatchGroup) {
            first = k;
            continue;
        }
        if (candidates[k].distance - candidates[first].distance > 1e-7 * size) {
            first = k;
            candidates[k].distanceGroup = candidates[k - 1].distanceGroup + 1;
        }
        else {
            candidates[k].distanceGroup = candidates[first].distanceGroup;
        }
    }
    std::ranges::sort(candidates, [](const Candidate& x, const Candidate& y) {
        return std::tie(x.mismatchGroup, x.distanceGroup, x.i, x.j)
            < std::tie(y.mismatchGroup, y.distanceGroup, y.i, y.j);
    });

    std::vector<std::pair<gp_Pnt, gp_Pnt>> starts;
    std::vector<const std::set<std::pair<int, int>>*> chains;
    for (const auto& c : candidates) {
        if (starts.size() >= limit) {
            break;
        }
        if (std::ranges::any_of(chains, [&](const auto* seen) { return *seen == c.chain; })) {
            continue;
        }
        chains.push_back(&c.chain);
        starts.emplace_back(startPoint(a[c.i]), startPoint(b[c.j]));
    }
    return starts;
}

/// The tests' hook: FREECAD_CH_LOFT_START_TEST=throw makes a run that took an automatic start fail.
bool startTestHook()
{
#ifdef _MSC_VER
    char* value = nullptr;
    size_t size = 0;
    if (_dupenv_s(&value, &size, "FREECAD_CH_LOFT_START_TEST") != 0 || !value) {
        return false;
    }
    const bool on = std::string(value) == "throw";
    std::free(value);
    return on;
#else
    const char* value = std::getenv("FREECAD_CH_LOFT_START_TEST");
    return value && std::string(value) == "throw";
#endif
}

/// The loops of an unconnected loft matched from the first start pair whose chain builds
/// (`unconnectedStarts`), or nothing.
std::optional<LoopMatch> unconnectedMatch(const Part::TopoShape& profile, const Part::TopoShape& section)
{
    constexpr size_t maxChains = 12;
    for (const auto& start : unconnectedStarts(profile, section, maxChains)) {
        try {
            return connectedLoops(profile, section, {start});
        }
        catch (const Base::Exception&) {
        }
        catch (const Standard_Failure&) {
        }
    }
    return std::nullopt;
}

// ops#1046 B + C (notes/loft-tangent-joints-1046.md): Onshape keeps a side edge whose ends are both
// smooth (a tangent joint, or a new vertex inside an edge) only where a planar side face ends on it;
// elsewhere one side face spans the run, and a new vertex there doesn't survive (RB44, RB47). The
// merged face is C1 along the profile: each rail is fitted piece by piece and joined with a knot at
// each joint, and the two runs pair through a C1 monotone map through the matched joints (the spike,
// scripts/spike_1046_c1.py: Onshape's F, V within 0.005 %).

constexpr int railDegree = 6;

/// An edge measured by arc length from where its traversal starts, to a tight tolerance (the
/// default one leaves a B-spline's samples too noisy to fit a rail through).
class ArcLength
{
public:
    explicit ArcLength(const TopoDS_Edge& edge)
        : curve(edge)
        , reversed(edge.Orientation() == TopAbs_REVERSED)
    {
        // the curve's C3 interval ends (a B-spline's knots) with the arc length up to each: a
        // point is then measured from the end just before it, not from the curve's start
        const int n = curve.NbIntervals(GeomAbs_C3);
        TColStd_Array1OfReal ends(1, n + 1);
        curve.Intervals(ends, GeomAbs_C3);
        params.push_back(curve.FirstParameter());
        lengths.push_back(0);
        for (int i = 2; i <= n + 1; ++i) {
            const double u = i == n + 1 ? curve.LastParameter() : ends(i);
            if (u <= params.back()) {
                continue;
            }
            lengths.push_back(lengths.back() + GCPnts_AbscissaPoint::Length(curve, params.back(), u, tolerance));
            params.push_back(u);
        }
        length = lengths.back();
    }
    /// The point at fraction t of the arc length from where the edge's traversal starts.
    gp_Pnt at(double t) const
    {
        t = std::clamp(t, 0.0, 1.0);
        const double d = reversed ? (1 - t) * length : t * length;  // from the curve's first parameter
        const auto k = std::clamp<std::ptrdiff_t>(
            std::upper_bound(lengths.begin(), lengths.end(), d) - lengths.begin() - 1,
            0,
            static_cast<std::ptrdiff_t>(lengths.size()) - 2
        );
        GCPnts_AbscissaPoint point(tolerance, curve, d - lengths[k], params[k]);
        if (!point.IsDone()) {
            throw Base::CADKernelError("Loft: a profile edge could not be measured");
        }
        return curve.Value(point.Parameter());
    }
    /// The arc-length fractions, ascending, where the curve's third derivative may jump (a
    /// B-spline's knots): a rail fitted across one oscillates, so the fit breaks there.
    std::vector<double> breaks() const
    {
        std::vector<double> fractions;
        if (length <= 0) {
            return fractions;
        }
        for (size_t i = 1; i + 1 < lengths.size(); ++i) {
            const double t = reversed ? 1 - lengths[i] / length : lengths[i] / length;
            if (t > 1e-9 && t < 1 - 1e-9) {
                fractions.push_back(t);
            }
        }
        std::ranges::sort(fractions);
        return fractions;
    }

private:
    static constexpr double tolerance = 1e-12;
    BRepAdaptor_Curve curve;
    bool reversed;
    std::vector<double> params;   // ascending curve parameters: first, interval ends, last
    std::vector<double> lengths;  // arc length from the first parameter to each
    double length = 0;
};

/// The point at fraction t of the edge's arc length from where its traversal starts (OCCT's
/// default precision: enough to find a face by its edge's midpoint).
gp_Pnt pointAtFraction(const TopoDS_Edge& edge, double t)
{
    BRepAdaptor_Curve curve(edge);
    const bool reversed = edge.Orientation() == TopAbs_REVERSED;
    const double length = GCPnts_AbscissaPoint::Length(curve);
    t = std::clamp(t, 0.0, 1.0);
    const double from = reversed ? curve.LastParameter() : curve.FirstParameter();
    GCPnts_AbscissaPoint at(curve, reversed ? -t * length : t * length, from);
    if (!at.IsDone()) {
        throw Base::CADKernelError("Loft: a profile edge could not be measured");
    }
    return curve.Value(at.Parameter());
}

/// A C1 monotone cubic (Fritsch-Carlson, Fritsch-Butland slopes) through (xs, ys), both increasing.
struct MonotoneCubic
{
    std::vector<double> xs, ys, slopes;

    MonotoneCubic(std::vector<double> x, std::vector<double> y)
        : xs(std::move(x))
        , ys(std::move(y))
    {
        const size_t n = xs.size();
        std::vector<double> d(n - 1);
        for (size_t i = 0; i + 1 < n; ++i) {
            d[i] = (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]);
        }
        slopes.assign(n, 0.0);
        slopes.front() = d.front();
        slopes.back() = d.back();
        for (size_t i = 1; i + 1 < n; ++i) {
            if (d[i - 1] * d[i] > 0) {
                slopes[i] = 3 * (d[i - 1] + d[i])
                    / ((2 * d[i] + d[i - 1]) / d[i - 1] + (d[i] + 2 * d[i - 1]) / d[i]);
            }
        }
    }

    double operator()(double x) const
    {
        size_t i = 0;
        while (i + 2 < xs.size() && x > xs[i + 1]) {
            ++i;
        }
        const double h = xs[i + 1] - xs[i];
        const double s = (x - xs[i]) / h;
        const double s2 = s * s;
        const double s3 = s2 * s;
        return (2 * s3 - 3 * s2 + 1) * ys[i] + (s3 - 2 * s2 + s) * h * slopes[i]
            + (-2 * s3 + 3 * s2) * ys[i + 1] + (s3 - s2) * h * slopes[i + 1];
    }
};

/// One piece of a rail: `at` on [u0, u1] fitted C2 (it is smooth there), raised to `railDegree`.
/// The samples double (from `first`, up to 1281) until the fit is within `target` of `at` at three
/// points between each two samples (a wide arc needs more than 41; a span between a B-spline's
/// knots needs few); `error` gets the largest distance.
Handle(Geom_BSplineCurve) fitRailPiece(
    const std::function<gp_Pnt(double)>& at,
    double u0,
    double u1,
    double target,
    int first,
    double& error
)
{
    Handle(Geom_BSplineCurve) curve;
    double worst = 0;
    for (int count = first; count <= 1281; count = 2 * count - 1) {
        TColgp_Array1OfPnt points(1, count);
        TColStd_Array1OfReal params(1, count);
        for (int i = 0; i < count; ++i) {
            const double u = u0 + (u1 - u0) * i / (count - 1);
            points(i + 1) = at(u);
            params(i + 1) = u;
        }
        GeomAPI_PointsToBSpline approx(points, params, 3, railDegree, GeomAbs_C2, 1e-9);
        if (!approx.IsDone()) {
            continue;
        }
        curve = approx.Curve();
        worst = 0;
        for (int i = 0; i + 1 < count; ++i) {
            for (double f : {0.25, 0.5, 0.75}) {
                const double u = u0 + (u1 - u0) * (i + f) / (count - 1);
                worst = std::max(worst, curve->Value(u).Distance(at(u)));
            }
        }
        if (worst < target) {
            break;
        }
    }
    if (curve.IsNull()) {
        throw Base::CADKernelError("Loft: failed to fit a side face over tangent joints");
    }
    curve->IncreaseDegree(railDegree);
    error = std::max(error, worst);
    return curve;
}

/// The pieces joined into one rail, with a knot at each joint, made C1 there where the pieces'
/// derivatives agree (they do: both runs are walked C1 through a tangent joint).
Handle(Geom_BSplineCurve) joinRail(const std::vector<Handle(Geom_BSplineCurve)>& pieces, double tolerance)
{
    const int degree = railDegree;
    std::vector<gp_Pnt> poles;
    std::vector<double> knots;
    std::vector<int> mults;
    std::vector<int> joints;
    for (size_t i = 0; i < pieces.size(); ++i) {
        const auto& c = pieces[i];
        if (i > 0) {
            mults.back() = degree;
            joints.push_back(static_cast<int>(knots.size()));
        }
        for (int j = (i == 0 ? 1 : 2); j <= c->NbPoles(); ++j) {
            poles.push_back(c->Pole(j));
        }
        for (int j = (i == 0 ? 1 : 2); j <= c->NbKnots(); ++j) {
            knots.push_back(c->Knot(j));
            mults.push_back(c->Multiplicity(j));
        }
    }
    TColgp_Array1OfPnt p(1, static_cast<int>(poles.size()));
    for (size_t i = 0; i < poles.size(); ++i) {
        p(static_cast<int>(i) + 1) = poles[i];
    }
    TColStd_Array1OfReal k(1, static_cast<int>(knots.size()));
    TColStd_Array1OfInteger m(1, static_cast<int>(mults.size()));
    for (size_t i = 0; i < knots.size(); ++i) {
        k(static_cast<int>(i) + 1) = knots[i];
        m(static_cast<int>(i) + 1) = mults[i];
    }
    Handle(Geom_BSplineCurve) rail = new Geom_BSplineCurve(p, k, m, degree);
    for (int joint : joints) {
        rail->RemoveKnot(joint, degree - 1, tolerance);
    }
    return rail;
}

/// The two rails on one knot vector (union of both, each knot at its larger multiplicity).
void makeRailsCompatible(Handle(Geom_BSplineCurve)& a, Handle(Geom_BSplineCurve)& b)
{
    const int degree = std::max(a->Degree(), b->Degree());
    a->IncreaseDegree(degree);
    b->IncreaseDegree(degree);
    std::vector<std::pair<double, int>> target;
    for (const auto* c : {&a, &b}) {
        for (int j = 2; j < (*c)->NbKnots(); ++j) {
            const double u = (*c)->Knot(j);
            const int mult = (*c)->Multiplicity(j);
            auto it = std::ranges::find_if(target, [u](const auto& t) { return std::abs(t.first - u) < 1e-10; });
            if (it == target.end()) {
                target.emplace_back(u, mult);
            }
            else {
                it->second = std::max(it->second, mult);
            }
        }
    }
    for (auto* c : {&a, &b}) {
        for (const auto& [u, mult] : target) {
            (*c)->InsertKnot(u, mult, 1e-10, Standard_False);
        }
    }
    if (a->NbPoles() != b->NbPoles() || a->NbKnots() != b->NbKnots()) {
        throw Base::CADKernelError("Loft: failed to fit a side face over tangent joints");
    }
}

/// The profiles' normals, each turned towards the other profile (as `withProfileConditions`).
void profileNormals(const TopoDS_Shape& first, const TopoDS_Shape& last, gp_Dir& normal0, gp_Dir& normal1)
{
    gp_Pln plane0;
    gp_Pln plane1;
    if (!Part::TopoShape(first).findPlane(plane0) || !Part::TopoShape(last).findPlane(plane1)) {
        throw Base::CADKernelError(
            QT_TRANSLATE_NOOP("Exception", "Loft: Normal to profile needs planar profiles")
        );
    }
    const gp_Vec across(wireCentre(first), wireCentre(last));
    normal0 = plane0.Axis().Direction();
    normal1 = plane1.Axis().Direction();
    if (across.Dot(normal0) < 0) {
        normal0.Reverse();
    }
    if (across.Dot(normal1) < 0) {
        normal1.Reverse();
    }
}

struct SideConditions
{
    bool start = false;
    double startMagnitude = 0;
    bool end = false;
    double endMagnitude = 0;
    gp_Dir normal0;
    gp_Dir normal1;
};

/// One side face over the paired runs `ea` (first profile) and `eb` (last profile), edge i with
/// edge i: u is the arc-length fraction along `ea`, `eb` is walked at t = f(u), f the monotone cubic
/// through the runs' joints. In the loft's direction it is linear, or the conditions' cubic.
TopoDS_Face mergedSideFace(
    const std::vector<TopoDS_Edge>& ea,
    const std::vector<TopoDS_Edge>& eb,
    const SideConditions& conditions
)
{
    const size_t count = ea.size();
    std::vector<double> us {0.0};
    std::vector<double> ts {0.0};
    double totalA = 0;
    double totalB = 0;
    std::vector<double> lengthsA, lengthsB;
    for (size_t i = 0; i < count; ++i) {
        lengthsA.push_back(edgeLength(ea[i]));
        lengthsB.push_back(edgeLength(eb[i]));
        totalA += lengthsA.back();
        totalB += lengthsB.back();
    }
    for (size_t i = 0; i < count; ++i) {
        us.push_back(i + 1 == count ? 1.0 : us.back() + lengthsA[i] / totalA);
        ts.push_back(i + 1 == count ? 1.0 : ts.back() + lengthsB[i] / totalB);
    }
    const MonotoneCubic f(us, ts);
    // the fit's target and limit relative to the run's length (a model's size doesn't change them)
    const double size = std::max(totalA, totalB);
    const double target = std::max(1e-8, 1e-10 * size);
    const double limit = std::max(1e-7, 1e-9 * size);
    double error = 0;
    std::vector<Handle(Geom_BSplineCurve)> piecesA, piecesB;
    // u where f reaches t, inside [lo, hi] (f is monotone)
    const auto inverse = [&f](double t, double lo, double hi) {
        for (int k = 0; k < 100 && hi - lo > 1e-15; ++k) {
            const double mid = (lo + hi) / 2;
            (f(mid) < t ? lo : hi) = mid;
        }
        return (lo + hi) / 2;
    };
    // a piece is fitted span by span between its curve's breaks; `joinRail` joins the spans C1
    const auto fitSpans = [&](const std::function<gp_Pnt(double)>& at, std::vector<double> cuts,
                              std::vector<Handle(Geom_BSplineCurve)>& pieces) {
        for (size_t k = 0; k + 1 < cuts.size(); ++k) {
            const int first = cuts.size() > 2 ? 9 : 41;
            pieces.push_back(fitRailPiece(at, cuts[k], cuts[k + 1], target, first, error));
        }
    };
    for (size_t i = 0; i < count; ++i) {
        const double u0 = us[i], u1 = us[i + 1], t0 = ts[i], t1 = ts[i + 1];
        const ArcLength a(ea[i]);
        const ArcLength b(eb[i]);
        std::vector<double> cutsA {u0}, cutsB {u0};
        for (double t : a.breaks()) {
            cutsA.push_back(u0 + t * (u1 - u0));
        }
        for (double t : b.breaks()) {
            cutsB.push_back(inverse(t0 + t * (t1 - t0), u0, u1));
        }
        for (auto* cuts : {&cutsA, &cutsB}) {
            // no span shorter than 1e-9 of the run (a break at a piece's end)
            std::vector<double> kept {u0};
            for (size_t k = 1; k < cuts->size(); ++k) {
                if ((*cuts)[k] > kept.back() + 1e-9 && (*cuts)[k] < u1 - 1e-9) {
                    kept.push_back((*cuts)[k]);
                }
            }
            kept.push_back(u1);
            *cuts = std::move(kept);
        }
        fitSpans([&](double u) { return a.at((u - u0) / (u1 - u0)); }, cutsA, piecesA);
        fitSpans([&](double u) { return b.at((f(u) - t0) / (t1 - t0)); }, cutsB, piecesB);
    }
    if (error > limit) {
        throw Base::CADKernelError(QT_TRANSLATE_NOOP(
            "Exception",
            "Loft: the side face over tangent joints could not be fitted to the profiles"
        ));
    }
    Handle(Geom_BSplineCurve) railA = joinRail(piecesA, 1e-7);
    Handle(Geom_BSplineCurve) railB = joinRail(piecesB, 1e-7);
    makeRailsCompatible(railA, railB);

    const int degree = railA->Degree();
    const int poles = railA->NbPoles();
    std::vector<double> flat;
    for (int i = 1; i <= railA->NbKnots(); ++i) {
        flat.insert(flat.end(), railA->Multiplicity(i), railA->Knot(i));
    }
    const gp_Pnt a0 = railA->Value(0.0), a1 = railA->Value(1.0);
    const gp_Pnt b0 = railB->Value(0.0), b1 = railB->Value(1.0);
    const double startA = conditions.startMagnitude * tangentLength(a0, b0, conditions.normal0);
    const double startB = conditions.startMagnitude * tangentLength(a1, b1, conditions.normal0);
    const double endA = conditions.endMagnitude * tangentLength(a0, b0, conditions.normal1);
    const double endB = conditions.endMagnitude * tangentLength(a1, b1, conditions.normal1);
    TColgp_Array2OfPnt net(1, poles, 1, 4);
    for (int j = 1; j <= poles; ++j) {
        double greville = 0;
        for (int i = j; i < j + degree; ++i) {
            greville += flat[i];
        }
        const double fraction = greville / degree;
        const gp_XYZ p0 = railA->Pole(j).XYZ();
        const gp_XYZ p3 = railB->Pole(j).XYZ();
        gp_XYZ p1 = p0 + (p3 - p0) / 3;
        gp_XYZ p2 = p0 + (p3 - p0) * 2 / 3;
        const gp_XYZ tangent0 = gp_Vec(conditions.normal0).XYZ() * (startA + (startB - startA) * fraction);
        const gp_XYZ tangent1 = gp_Vec(conditions.normal1).XYZ() * (endA + (endB - endA) * fraction);
        if (conditions.start && conditions.end) {
            p1 = p0 + tangent0 / 3;
            p2 = p3 - tangent1 / 3;
        }
        else if (conditions.start) {
            p1 = p0 + tangent0 / 3;
            p2 = (p1 + p3) / 2;
        }
        else if (conditions.end) {
            p2 = p3 - tangent1 / 3;
            p1 = (p0 + p2) / 2;
        }
        net(j, 1) = gp_Pnt(p0);
        net(j, 2) = gp_Pnt(p1);
        net(j, 3) = gp_Pnt(p2);
        net(j, 4) = gp_Pnt(p3);
    }
    TColStd_Array1OfReal uKnots(1, railA->NbKnots());
    TColStd_Array1OfInteger uMults(1, railA->NbKnots());
    railA->Knots(uKnots);
    railA->Multiplicities(uMults);
    TColStd_Array1OfReal vKnots(1, 2);
    TColStd_Array1OfInteger vMults(1, 2);
    vKnots(1) = 0;
    vKnots(2) = 1;
    vMults(1) = 4;
    vMults(2) = 4;
    Handle(Geom_BSplineSurface) surface
        = new Geom_BSplineSurface(net, uKnots, vKnots, uMults, vMults, degree, 3);
    BRepBuilderAPI_MakeFace maker(surface, Precision::Confusion());
    if (!maker.IsDone()) {
        throw Base::CADKernelError("Loft: failed to make a side face over tangent joints");
    }
    return maker.Face();
}

/// The part of the profile edge `origin` from the start vertex of `from` to the end vertex of `to`
/// (pieces of it, in traversal order), oriented as traversed; recorded as modified from `origin`.
TopoDS_Edge edgeBetween(
    const TopoDS_Edge& origin,
    const TopoDS_Edge& from,
    const TopoDS_Edge& to,
    Part::ShapeMapper& mapper
)
{
    // the pieces lie on the origin's curve with its parameters (`splitEdge`): the span runs from
    // where `from`'s traversal starts to where `to`'s ends
    double first = 0;
    double last = 0;
    const Handle(Geom_Curve) curve = BRep_Tool::Curve(from, first, last);
    const double u0 = from.Orientation() == TopAbs_REVERSED ? last : first;
    BRep_Tool::Curve(to, first, last);
    const double u1 = to.Orientation() == TopAbs_REVERSED ? first : last;
    const TopoDS_Vertex v0 = TopExp::FirstVertex(from, Standard_True);
    const TopoDS_Vertex v1 = TopExp::LastVertex(to, Standard_True);
    TopoDS_Edge edge;
    if (u0 < u1) {
        BRepBuilderAPI_MakeEdge make(curve, v0, v1, u0, u1);
        if (!make.IsDone()) {
            throw Base::CADKernelError("Loft: a profile edge could not be joined again");
        }
        edge = make.Edge();
    }
    else {
        BRepBuilderAPI_MakeEdge make(curve, v1, v0, u1, u0);
        if (!make.IsDone()) {
            throw Base::CADKernelError("Loft: a profile edge could not be joined again");
        }
        edge = TopoDS::Edge(make.Edge().Reversed());
    }
    mapper.insert(Part::MappingStatus::Modified, origin, edge);
    return edge;
}

/// Whether the side face between the paired pieces `a` and `b` is flat: both straight, the four
/// ends in one plane (relative to the face's size, so a model's scale doesn't change the answer),
/// and that plane holds the normal of each profile that has a condition.
bool flatSide(const TopoDS_Edge& a, const TopoDS_Edge& b, const SideConditions& conditions)
{
    if (!isStraight(a) || !isStraight(b)) {
        return false;
    }
    const gp_Pnt p0 = startPoint(a);
    const gp_Vec u(p0, endPoint(a));
    const gp_Vec w0(p0, startPoint(b));
    const gp_Vec w1(p0, endPoint(b));
    const double size = std::max({u.Magnitude(), w0.Magnitude(), w1.Magnitude()});
    gp_Vec normal = u.Crossed(w0).Magnitude() > u.Crossed(w1).Magnitude() ? u.Crossed(w0) : u.Crossed(w1);
    if (normal.Magnitude() < 1e-12 * size * size) {
        return true;  // the four ends on one line
    }
    normal.Normalize();
    const double tolerance = std::max(Precision::Confusion(), 1e-9 * size);
    if (std::abs(normal.Dot(w0)) > tolerance || std::abs(normal.Dot(w1)) > tolerance) {
        return false;
    }
    constexpr double angle = 1e-7;
    if (conditions.start && std::abs(normal.Dot(gp_Vec(conditions.normal0))) > angle) {
        return false;
    }
    if (conditions.end && std::abs(normal.Dot(gp_Vec(conditions.normal1))) > angle) {
        return false;
    }
    return true;
}

/// Whether the face has an edge through the point.
bool hasEdgeThrough(const TopoDS_Face& face, const gp_Pnt& point)
{
    for (TopExp_Explorer x(face, TopAbs_EDGE); x.More(); x.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(x.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        double first = 0;
        double last = 0;
        const Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);
        if (curve.IsNull()) {
            continue;
        }
        GeomAPI_ProjectPointOnCurve projection(point, curve, first, last);
        if (projection.NbPoints() > 0 && projection.LowerDistance() < 1e-6) {
            return true;
        }
    }
    return false;
}

/// The loft `shell` of a connected loop pair (its side faces) with Onshape's side edges: a side
/// edge whose ends are smooth on both profiles goes where neither side face beside it is flat, and
/// the faces it separated become one. A new vertex whose side edge goes is joined back into its
/// profile edge in `match`'s wires. Unchanged when every side edge stays.
Part::TopoShape mergeSmoothRuns(Part::TopoShape shell, LoopMatch& match, SideConditions conditions)
{
    const size_t n = match.edgesA.size();
    if (n < 2 || match.edgesB.size() != n) {
        return shell;
    }
    TopTools_IndexedMapOfShape shellFaces;
    TopExp::MapShapes(shell.getShape(), TopAbs_FACE, shellFaces);
    std::vector<TopoDS_Face> faces(n);
    std::vector<bool> flat(n);
    for (size_t k = 0; k < n; ++k) {
        const gp_Pnt pa = pointAtFraction(match.edgesA[k], 0.5);
        const gp_Pnt pb = pointAtFraction(match.edgesB[k], 0.5);
        for (int i = 1; i <= shellFaces.Extent() && faces[k].IsNull(); ++i) {
            const TopoDS_Face& face = TopoDS::Face(shellFaces(i));
            if (hasEdgeThrough(face, pa) && hasEdgeThrough(face, pb)) {
                faces[k] = face;
            }
        }
        if (faces[k].IsNull()) {
            throw Base::CADKernelError("Loft: a side face of the connected loft was not found");
        }
    }
    if (conditions.start || conditions.end) {
        profileNormals(match.wireA.getShape(), match.wireB.getShape(), conditions.normal0, conditions.normal1);
    }
    for (size_t k = 0; k < n; ++k) {
        flat[k] = flatSide(match.edgesA[k], match.edgesB[k], conditions);
    }
    std::vector<bool> drop(n);
    size_t dropped = 0;
    for (size_t k = 0; k < n; ++k) {
        const size_t prev = (k + n - 1) % n;
        drop[k] = tangentJoint(match.edgesA[prev], match.edgesA[k])
            && tangentJoint(match.edgesB[prev], match.edgesB[k]) && !flat[prev] && !flat[k];
        dropped += drop[k] ? 1 : 0;
    }
    if (dropped == 0) {
        return shell;
    }
    if (dropped == n) {
        // Onshape: one closed side face with the first connection's edge as its seam (rule 5). Without
        // vertices matched by fraction the loft builds as it did before ops#1046, with every side
        // edge (debt; ops#729's split-line vertices included); with them it stops
        if (!match.fractionVertices) {
            return shell;
        }
        throw Base::CADKernelError(QT_TRANSLATE_NOOP(
            "Exception",
            "Loft: every side joint of the connected loop is tangent with no flat side beside it; "
            "that single side face can't be built yet"
        ));
    }

    // the runs between the side edges that stay, from the first that stays
    size_t k0 = 0;
    while (drop[k0]) {
        ++k0;
    }
    std::vector<std::vector<size_t>> groups {{k0}};
    for (size_t step = 1; step < n; ++step) {
        const size_t k = (k0 + step) % n;
        if (drop[k]) {
            groups.back().push_back(k);
        }
        else {
            groups.push_back({k});
        }
    }
    BRepBuilderAPI_Sewing sewer(1e-6);
    std::vector<TopoDS_Face> kept;
    std::vector<std::pair<std::vector<TopoDS_Face>, TopoDS_Face>> merged;
    for (const auto& group : groups) {
        if (group.size() == 1) {
            kept.push_back(faces[group.front()]);
            sewer.Add(kept.back());
            continue;
        }
        std::vector<TopoDS_Edge> ea, eb;
        std::vector<TopoDS_Face> old;
        for (size_t k : group) {
            ea.push_back(match.edgesA[k]);
            eb.push_back(match.edgesB[k]);
            old.push_back(faces[k]);
        }
        merged.emplace_back(old, mergedSideFace(ea, eb, conditions));
        sewer.Add(merged.back().second);
    }
    sewer.Perform();
    const TopoDS_Shape sewn = sewer.SewedShape();

    // the names: the merged faces from the faces they replace, the rest as they were
    Handle(BRepTools_History) history = new BRepTools_History;
    for (const auto& face : kept) {
        const TopoDS_Shape now = sewer.Modified(face);
        if (!now.IsNull() && !now.IsSame(face)) {
            history->AddModified(face, now);
        }
    }
    for (const auto& [old, face] : merged) {
        TopoDS_Shape now = sewer.Modified(face);
        if (now.IsNull()) {
            now = face;
        }
        for (const auto& o : old) {
            history->AddModified(o, now);
        }
    }
    auto ends = [](const TopoDS_Edge& edge) {
        BRepAdaptor_Curve curve(edge);
        return std::array<gp_Pnt, 3> {
            curve.Value(curve.FirstParameter()),
            curve.Value(curve.LastParameter()),
            curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2)
        };
    };
    TopTools_IndexedMapOfShape newEdges;
    TopExp::MapShapes(sewn, TopAbs_EDGE, newEdges);
    TopTools_IndexedMapOfShape oldEdges;
    TopExp::MapShapes(shell.getShape(), TopAbs_EDGE, oldEdges);
    for (int i = 1; i <= oldEdges.Extent(); ++i) {
        const TopoDS_Edge& oldEdge = TopoDS::Edge(oldEdges(i));
        if (BRep_Tool::Degenerated(oldEdge) || newEdges.Contains(oldEdge)) {
            continue;
        }
        const auto o = ends(oldEdge);
        int best = 0;
        double bestMiddle = 0;
        for (int j = 1; j <= newEdges.Extent(); ++j) {
            const TopoDS_Edge& newEdge = TopoDS::Edge(newEdges(j));
            if (BRep_Tool::Degenerated(newEdge)) {
                continue;
            }
            const auto e = ends(newEdge);
            const bool same = (o[0].Distance(e[0]) < 1e-6 && o[1].Distance(e[1]) < 1e-6)
                || (o[0].Distance(e[1]) < 1e-6 && o[1].Distance(e[0]) < 1e-6);
            if (!same) {
                continue;
            }
            const double middle = o[2].Distance(e[2]);
            if (!best || middle < bestMiddle) {
                best = j;
                bestMiddle = middle;
            }
        }
        if (best) {
            history->AddModified(oldEdge, newEdges(best));
        }
    }
    TopTools_IndexedMapOfShape newVertices;
    TopExp::MapShapes(sewn, TopAbs_VERTEX, newVertices);
    TopTools_IndexedMapOfShape oldVertices;
    TopExp::MapShapes(shell.getShape(), TopAbs_VERTEX, oldVertices);
    for (int i = 1; i <= oldVertices.Extent(); ++i) {
        if (newVertices.Contains(oldVertices(i))) {
            continue;
        }
        const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(oldVertices(i)));
        for (int j = 1; j <= newVertices.Extent(); ++j) {
            if (BRep_Tool::Pnt(TopoDS::Vertex(newVertices(j))).Distance(point) < 1e-6) {
                history->AddModified(oldVertices(i), newVertices(j));
                break;
            }
        }
    }
    Part::TopoShape result(shell.Tag, shell.Hasher);
    result.makeShapeWithElementMap(sewn, Part::MapperHistory(history), {shell});

    // a new vertex whose side edge went is joined back into its profile edge (Onshape has none)
    auto rejoin = [&](const std::vector<TopoDS_Edge>& edges,
                      const std::vector<TopoDS_Edge>& origins,
                      const std::vector<bool>& fresh,
                      Part::ShapeMapper& mapper,
                      const Part::TopoShape& source,
                      Part::TopoShape& wire) {
        std::vector<TopoDS_Edge> joined;
        bool changed = false;
        for (size_t k = 0; k < n;) {
            size_t e = k;
            while (e + 1 < n && drop[e + 1] && fresh[e + 1] && origins[e + 1].IsSame(origins[k])) {
                ++e;
            }
            if (e == k) {
                joined.push_back(edges[k]);
                ++k;
                continue;
            }
            changed = true;
            const bool whole = !fresh[k]
                && (e + 1 == n || !fresh[e + 1] || !origins[e + 1].IsSame(origins[k]));
            joined.push_back(whole ? origins[k] : edgeBetween(origins[k], edges[k], edges[e], mapper));
            k = e + 1;
        }
        if (changed) {
            wire = loopWire(joined, mapper, source);
        }
    };
    rejoin(match.edgesA, match.originA, match.freshA, match.mapperA, match.profile, match.wireA);
    rejoin(match.edgesB, match.originB, match.freshB, match.mapperB, match.section, match.wireB);
    return result;
}

/// ops#933: two polygon loops lofted without connections pair as ThruSections' compatibility step
/// picks, and that depends on the sketches' vertex order: between planes that are not parallel (an
/// elbow) it can pair them half a turn apart, so the side faces cross (a solid turned inside out,
/// or an invalid shell after a boolean). Onshape builds the loft that doesn't turn. Reads the
/// pairing ThruSections took from the shell's side edges and, when that pairing turns the loft
/// through itself (the test connections use), returns the section's loop paired anew: run the
/// profile's way round, as for connections, and started at the vertex that gives the shortest
/// side edges in total among the pairings that don't turn. Empty when the pairing taken is kept:
/// it doesn't turn, it can't be read, the loops aren't polygons of as many edges, or no single
/// pairing is shortest.
std::optional<Part::TopoShape> unturnedSection(
    const Part::TopoShape& shell,
    const Part::TopoShape& profile,
    const Part::TopoShape& section
)
{
    if (profile.isNull() || section.isNull() || profile.shapeType() != TopAbs_WIRE
        || section.shapeType() != TopAbs_WIRE || !BRep_Tool::IsClosed(profile.getShape())
        || !BRep_Tool::IsClosed(section.getShape())) {
        return std::nullopt;
    }
    const auto a = loopEdges(profile.getShape());
    const auto b = loopEdges(section.getShape());
    const size_t n = a.size();
    auto straight = [](const std::vector<TopoDS_Edge>& edges) {
        return std::ranges::all_of(edges, [](const TopoDS_Edge& edge) {
            return BRepAdaptor_Curve(edge).GetType() == GeomAbs_Line;
        });
    };
    if (n < 3 || b.size() != n || !straight(a) || !straight(b)) {
        return std::nullopt;
    }

    // The pairing taken: each side edge joins a profile vertex to a section vertex
    std::vector<int> partner(n, -1);
    for (TopExp_Explorer x(shell.getShape(), TopAbs_EDGE); x.More(); x.Next()) {
        TopoDS_Vertex v1, v2;
        TopExp::Vertices(TopoDS::Edge(x.Current()), v1, v2);
        if (v1.IsNull() || v2.IsNull()) {
            continue;
        }
        gp_Pnt p = BRep_Tool::Pnt(v1);
        gp_Pnt q = BRep_Tool::Pnt(v2);
        for (int k = 0; k < 2; ++k, std::swap(p, q)) {
            const int i = vertexIndex(a, p);
            const int j = vertexIndex(b, q);
            if (i >= 0 && j >= 0) {
                if (partner[i] >= 0 && partner[i] != j) {
                    return std::nullopt;
                }
                partner[i] = j;
            }
        }
    }
    if (std::ranges::find(partner, -1) != partner.end()) {
        return std::nullopt;
    }
    const int nn = static_cast<int>(n);
    const int step = (partner[1] - partner[0] + nn) % nn == 1 ? 1 : -1;
    for (int i = 0; i < nn; ++i) {
        if (partner[i] != ((partner[0] + step * i) % nn + nn) % nn) {
            return std::nullopt;
        }
    }
    // The section's loop as taken: its edge i starts at profile edge i's partner. Reversed, the
    // loop's edge k starts at the vertex that began edge (n - k) % n.
    auto rotated = [](std::vector<TopoDS_Edge> edges, int by) {
        std::rotate(edges.begin(), edges.begin() + by, edges.end());
        return edges;
    };
    const auto taken = step > 0 ? rotated(b, partner[0])
                                : rotated(reversedLoop(b), (nn - partner[0]) % nn);

    const auto samplesA = loopSamples(a);
    const gp_Vec na = areaVector(samplesA);
    const auto samplesTaken = loopSamples(taken);
    const gp_Vec nt = areaVector(samplesTaken);
    if (na.Magnitude() < Precision::Confusion() || nt.Magnitude() < Precision::Confusion()) {
        return std::nullopt;
    }
    const double takenSense = loopSense(samplesA, samplesTaken, na, nt);
    if (takenSense == 0) {
        return std::nullopt;
    }
    if (takenSense > 0 && !turnsThroughItself(a, taken, na, nt, 1)) {
        return std::nullopt;  // the pairing taken doesn't turn: kept
    }

    // Paired anew: the profile's way round, the shortest side edges among those that don't turn
    const auto samplesB = loopSamples(b);
    const gp_Vec nb = areaVector(samplesB);
    const double sense = loopSense(samplesA, samplesB, na, nb);
    if (sense == 0) {
        return std::nullopt;
    }
    const auto way = sense < 0 ? reversedLoop(b) : b;
    const gp_Vec nw = sense < 0 ? -nb : nb;
    double best = std::numeric_limits<double>::infinity();
    double next = best;
    std::vector<TopoDS_Edge> chosen;
    for (int r = 0; r < nn; ++r) {
        auto candidate = rotated(way, r);
        if (turnsThroughItself(a, candidate, na, nw, 1)) {
            continue;
        }
        double length = 0;
        for (size_t i = 0; i < n; ++i) {
            length += startPoint(a[i]).Distance(startPoint(candidate[i]));
        }
        if (length < best) {
            next = best;
            best = length;
            chosen = std::move(candidate);
        }
        else {
            next = std::min(next, length);
        }
    }
    if (chosen.empty() || next - best <= 1e-9 * best) {
        return std::nullopt;
    }
    return loopWire(chosen, Part::ShapeMapper(), section);
}

/// The connections' vertex pairs (profile first, global coordinates). Entries 2k and 2k+1 of
/// `Connections` form one pair, in either order.
std::vector<std::pair<gp_Pnt, gp_Pnt>> connectionPoints(const PartDesign::Loft& loft)
{
    const auto& objects = loft.Connections.getValues();
    const auto subs = loft.Connections.getSubValues();
    if (objects.empty()) {
        return {};
    }
    if (objects.size() % 2 != 0 || subs.size() != objects.size()) {
        throw Base::CADKernelError(QT_TRANSLATE_NOOP(
            "Exception",
            "Loft: each connection needs one vertex on each profile"
        ));
    }
    const auto& sections = loft.Sections.getValues();
    if (sections.size() != 1) {
        throw Base::CADKernelError(
            QT_TRANSLATE_NOOP("Exception", "Loft: connections need exactly two profiles")
        );
    }
    const App::DocumentObject* profile = loft.Profile.getValue();
    const App::DocumentObject* section = sections.front();
    auto point = [](App::DocumentObject* object, const std::string& sub) {
        const auto vertex = Part::Feature::getTopoShape(
            object,
            Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                | Part::ShapeOption::Transform,
            sub.c_str()
        );
        if (vertex.isNull() || vertex.getShape().ShapeType() != TopAbs_VERTEX) {
            throw Base::CADKernelError(
                QT_TRANSLATE_NOOP("Exception", "Loft: a connection must join two vertices")
            );
        }
        return BRep_Tool::Pnt(TopoDS::Vertex(vertex.getShape()));
    };
    std::vector<std::pair<gp_Pnt, gp_Pnt>> result;
    for (size_t k = 0; k + 1 < objects.size(); k += 2) {
        size_t p = k;
        size_t s = k + 1;
        if (objects[p] == section && objects[s] == profile) {
            std::swap(p, s);
        }
        if (objects[p] != profile || objects[s] != section || profile == section) {
            throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                "Exception",
                "Loft: a connection needs one vertex on the profile and one on the section"
            ));
        }
        result.emplace_back(point(objects[p], subs[p]), point(objects[s], subs[s]));
    }
    return result;
}

}  // namespace

PROPERTY_SOURCE(PartDesign::Loft, PartDesign::ProfileBased)

Loft::Loft()
{
    ADD_PROPERTY_TYPE(Sections, (nullptr), "Loft", App::Prop_None, "List of sections");
    Sections.setValue(nullptr);
    ADD_PROPERTY_TYPE(Ruled, (false), "Loft", App::Prop_None, "Create ruled surface");
    ADD_PROPERTY_TYPE(Closed, (false), "Loft", App::Prop_None, "Close Last to First Profile");
    ADD_PROPERTY_TYPE(
        StartCondition,
        (0L),
        "Loft",
        App::Prop_None,
        "How the loft leaves the first profile: None, or Normal to profile (two planar profiles)"
    );
    StartCondition.setEnums(ConditionEnums);
    ADD_PROPERTY_TYPE(
        StartMagnitude,
        (1.0),
        "Loft",
        App::Prop_None,
        "Scale of the start condition's tangent (0: no condition, as Onshape; a Legacy loft: a "
        "tangent of length 0)"
    );
    ADD_PROPERTY_TYPE(
        EndCondition,
        (0L),
        "Loft",
        App::Prop_None,
        "How the loft reaches the last profile: None, or Normal to profile (two planar profiles)"
    );
    EndCondition.setEnums(ConditionEnums);
    ADD_PROPERTY_TYPE(
        EndMagnitude,
        (1.0),
        "Loft",
        App::Prop_None,
        "Scale of the end condition's tangent (0: no condition, as Onshape; a Legacy loft: a tangent "
        "of length 0)"
    );
    ADD_PROPERTY_TYPE(
        Connections,
        (nullptr),
        "Loft",
        App::Prop_None,
        "Vertex pairs the loft joins, one vertex on the profile and one on the section (two profiles)"
    );
    Connections.setValue(nullptr);
    ADD_PROPERTY_TYPE(
        TangentRule,
        (0L),
        "Loft",
        App::Prop_Hidden,
        "Normal to profile's tangent length: Onshape (per rail), or Legacy (fork-1.0.0's k * distance, "
        "kept for lofts from files saved by fork-1.0.0 and older)"
    );
    TangentRule.setEnums(TangentRuleEnums);
}

const char* Loft::ConditionEnums[] = {"None", "Normal to profile", nullptr};
const char* Loft::TangentRuleEnums[] = {"Onshape", "Legacy", nullptr};

void Loft::Restore(Base::XMLReader& reader)
{
    // ops#855 (R3): a file without TangentRule was saved before fork-1.0.1 (ForkRelease 12 or older),
    // whose Normal to profile took fork-1.0.0's tangent rule; a file that has it overwrites this
    TangentRule.setValue(1L);
    ProfileBased::Restore(reader);
}

short Loft::mustExecute() const
{
    if (Sections.isTouched()) {
        return 1;
    }
    if (Ruled.isTouched()) {
        return 1;
    }
    if (Closed.isTouched() || StartCondition.isTouched() || StartMagnitude.isTouched()
        || EndCondition.isTouched() || EndMagnitude.isTouched() || Connections.isTouched()
        || TangentRule.isTouched()) {
        return 1;
    }

    return ProfileBased::mustExecute();
}

std::vector<Part::TopoShape> Loft::getSectionShape(
    const char* name,
    App::DocumentObject* obj,
    const std::vector<std::string>& subs,
    size_t expected_size
)
{
    auto useSketch = [](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        // Be smart. If part of a sketch is selected, use the entire sketch unless it is a single
        // vertex - backward compatibility (#16630)
        if (!obj) {
            return false;
        }

        auto subName = subs.empty() ? "" : subs.front();
        return obj->isDerivedFrom<Part::Part2DObject>() && subName.find("Vertex") != 0;
    };

    // A sketch vertex that no longer exists ("?Vertex1") fails the vertex test above, so the
    // whole sketch would be used in its place (ops#71)
    if (auto missing = missingElements(obj, {subs.empty() ? std::string() : subs.front()}, true);
        !missing.empty()) {
        FC_THROWM(Part::NullShapeException, "Missing element in " << name << ": " << missing);
    }

    std::vector<TopoShape> shapes;
    auto useEntireSketch = useSketch(obj, subs);
    if (subs.empty() || std::ranges::find(subs, std::string()) != subs.end() || useEntireSketch) {
        shapes.push_back(
            Part::Feature::getTopoShape(obj, Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform)
        );
        if (shapes.back().isNull()) {
            std::stringstream str;
            str << "Failed to get shape of " << name;
            if (obj) {
                auto doc = obj->getDocument();
                str << " " << App::SubObjectT(obj, "").getSubObjectFullName(doc->getName());
            }
            THROWM(Part::NullShapeException, str.str());
        }
    }
    else {
        for (const auto& sub : subs) {
            shapes.push_back(
                Part::Feature::getTopoShape(
                    obj,
                    Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                        | Part::ShapeOption::Transform,
                    sub.c_str()
                )
            );
            if (shapes.back().isNull()) {
                std::stringstream str;
                str << "Failed to get shape of " << name;
                if (obj) {
                    auto doc = obj->getDocument();
                    App::SubObjectT subObj(obj, sub.c_str());
                    str << " " << subObj.getSubObjectFullName(doc->getName());
                }
                THROWM(Part::NullShapeException, str.str());
            }
        }
    }
    auto compound = Feature::makeTopoShape(obj, TopoDS_Shape(), 0, false)
                        .makeElementCompound(
                            shapes,
                            "",
                            TopoShape::SingleShapeCompoundCreationPolicy::returnShape
                        );
    // A whole sketch gives its closed loops; open curves are ignored, as in Onshape (ops#631).
    // With no loop left, the open wires stay, and the loft refuses them as before.
    // Loops from regions come outer wire first; the loft pairs every section's loops by role
    // (outerLoopsFirst below), and stops where regions leave more than one hole to pair
    bool fromRegions = false;
    if (useEntireSketch && picksRegions(subs)) {
        fromRegions = true;
        // Picked regions (they were left for the whole sketch before): their faces' wires,
        // adjacent regions merged, in the picks' order (feat/profile-regions)
        std::vector<TopoShape> faces;
        for (const auto& sub : subs) {
            auto face = Part::Feature::getTopoShape(
                obj,
                Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                    | Part::ShapeOption::Transform,
                sub.c_str()
            );
            if (face.isNull() || !face.hasSubShape(TopAbs_FACE)) {
                FC_THROWM(Part::NullShapeException, "Failed to get the region " << sub << " of " << name);
            }
            faces.push_back(face);
        }
        auto picked = Feature::makeTopoShape(obj, TopoDS_Shape(), 0, false).makeElementCompound(faces);
        auto merged = mergeAdjacentRegions(obj, subs, picked);
        // Several regions would pair in the picks' order with another section's sketch order:
        // a second silent find of the pairing (review r2), so the literal rule: one region
        if (merged.countSubShapes(TopAbs_FACE) > 1) {
            FC_THROWM(Base::CADKernelError, name << ": " << SectionRegionsMessage);
        }
        compound = wiresOfFaces(merged);
    }
    else if (useEntireSketch) {
        WholeSketchRegions rule(obj, compound);
        bool loopsDone = false;
        if (rule.sameAsLoops()) {
            try {
                if (auto loops = withoutOpenCurves(compound); !loops.isNull()) {
                    compound = loops;
                }
                loopsDone = true;
            }
            catch (const Base::Exception&) {
                // Onshape's regions below
            }
        }
        if (!loopsDone) {
            // Loops that overlap, touch or nest deeper: Onshape's regions, which pair with
            // another section's only as one loop
            if (auto faces = rule.faces(); !faces.isNull()) {
                fromRegions = true;
                compound = wiresOfFaces(faces);
                // One region with at most one hole pairs as the old loops do (outer to outer,
                // hole to hole); more, and the face maker's order isn't the sketch's
                if (faces.countSubShapes(TopAbs_FACE) > 1
                    || compound.countSubShapes(TopAbs_WIRE) > 2) {
                    FC_THROWM(Base::CADKernelError, name << ": " << SectionRegionsMessage);
                }
            }
        }
    }
    auto wires = compound.getSubTopoShapes(TopAbs_WIRE);
    auto edges = compound.getSubTopoShapes(TopAbs_EDGE, TopAbs_WIRE);  // get free edges and make
                                                                       // wires from it
    if (!edges.empty()) {
        auto extra = Feature::makeTopoShape(obj, TopoDS_Shape(), 0, false)
                         .makeElementWires(edges)
                         .getSubTopoShapes(TopAbs_WIRE);
        wires.insert(wires.end(), extra.begin(), extra.end());
    }
    const char* msg
        = "Sections need to have the same amount of wires or vertices as the base section";
    if (!wires.empty()) {
        if (expected_size && expected_size != wires.size()) {
            FC_THROWM(Base::CADKernelError, msg);
        }
        // Outer loops first, then holes, in every section: a section of regions (outer wire
        // first) pairs with one in the sketch's own order (feat/profile-regions review r1)
        std::size_t holes = 0;
        wires = outerLoopsFirst(wires, &holes);
        if (fromRegions && holes > 1) {
            FC_THROWM(Base::CADKernelError, name << ": " << SectionRegionsMessage);
        }
        return wires;
    }
    auto vertices = compound.getSubTopoShapes(TopAbs_VERTEX);
    if (vertices.empty()) {
        FC_THROWM(
            Base::CADKernelError,
            "Invalid " << name << " shape, expecting either wires or vertices"
        );
    }
    if (expected_size && expected_size != vertices.size()) {
        FC_THROWM(Base::CADKernelError, msg);
    }
    return vertices;
}

App::DocumentObjectExecReturn* Loft::execute()
{
    // ops#1071: an automatic start pair that fails anywhere after the match (the merge, the loft,
    // the solid) gives way to the old pairing, OCCT's, with a warning; never for a loft with
    // connections (they turn the automatic path off)
    bool automaticUsed = false;
    App::DocumentObjectExecReturn* ret = executeLoft(true, automaticUsed);
    if (!ret || !automaticUsed) {
        return ret;
    }
    std::string why = ret->Why;
    delete ret;
    bool unused = false;
    ret = executeLoft(false, unused);
    if (!ret) {
        if (auto doc = getDocument()) {
            std::string lower = why;
            std::ranges::transform(lower, lower.begin(), [](unsigned char ch) { return std::tolower(ch); });
            std::string text = "Loft: the profiles' vertices were paired the old way (OCCT's polar method), "
                               "not by corner position as Onshape's";
            if (!why.empty() && lower.find("connection") == std::string::npos) {
                text += ": " + why;
            }
            const char* previous = doc->getWarningDescription(this);
            doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + text : text);
        }
    }
    return ret;
}

App::DocumentObjectExecReturn* Loft::executeLoft(bool automaticStarts, bool& automaticUsed)
{
    automaticUsed = false;
    if (onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    std::vector<TopoShape> wires;
    try {
        wires = getSectionShape("Profile", Profile.getValue(), Profile.getSubValues());
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }

    // if the Base property has a valid shape, fuse the pipe into it
    TopoShape base;
    try {
        base = getBaseTopoShape();
    }
    catch (const Base::Exception&) {
    }

    auto hasher = getDocument()->getStringHasher();

    try {
        // setup the location
        this->positionByPrevious();
        auto invObjLoc = getInverseLocation(base);
        if (!base.isNull()) {
            base.move(invObjLoc);
        }

        // build up multisections
        auto multisections = Sections.getSubListValues();
        if (multisections.empty()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Loft: At least one section is needed")
            );
        }

        std::vector<std::vector<TopoShape>> wiresections;
        wiresections.reserve(wires.size());
        for (auto& wire : wires) {
            wiresections.emplace_back(1, wire);
        }

        for (const auto& subSet : multisections) {
            int i = 0;
            for (const auto& s :
                 getSectionShape("Section", subSet.first, subSet.second, wiresections.size())) {
                wiresections[i++].push_back(s);
            }
        }

        bool closed = Closed.getValue();
        // invalid for less then 3 sections
        if (multisections.size() < 2) {
            closed = false;
        }

        TopoShape result = makeTopoShape();
        std::vector<TopoShape> shapes;

        // ops#640: Onshape's connections, in the wires' frame; each goes to the loop pair that
        // holds both its vertices
        auto connections = connectionPoints(*this);
        for (auto& [p, q] : connections) {
            p.Transform(invObjLoc.Transformation());
            q.Transform(invObjLoc.Transformation());
        }
        std::vector<bool> placed(connections.size(), false);

        // ops#655: Onshape's profile conditions. A magnitude of 0 is no condition at that end:
        // Onshape builds the plain loft for it (oracle 17 LE3), never a tangent of length 0
        // fork-1.0.0's rule (Legacy, ops#855) took a magnitude of 0 as a tangent of length 0
        const bool legacy = TangentRule.getValue() == 1;
        const bool startSet = StartCondition.getValue() != 0
            && (legacy || StartMagnitude.getValue() != 0.0);
        const bool endSet = EndCondition.getValue() != 0 && (legacy || EndMagnitude.getValue() != 0.0);

        // build all shells
        std::vector<TopoShape> shells;
        bool frontReseamed = false;
        for (auto& sectionWires : wiresections) {
            for (auto& wire : sectionWires) {
                wire.move(invObjLoc);
            }
            const TopoDS_Shape unseamed = sectionWires.front().getShape();
            std::vector<std::pair<gp_Pnt, gp_Pnt>> loopConnections;
            if (!connections.empty()) {
                if (sectionWires.size() != 2 || closed) {
                    throw Base::CADKernelError(
                        QT_TRANSLATE_NOOP("Exception", "Loft: connections need exactly two profiles")
                    );
                }
                if (sectionWires.front().shapeType() == TopAbs_VERTEX
                    || sectionWires.back().shapeType() == TopAbs_VERTEX) {
                    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Loft: connections need two profiles with vertices, not a point profile"
                    ));
                }
                for (size_t c = 0; c < connections.size(); ++c) {
                    if (!placed[c] && hasVertexAt(sectionWires.front(), connections[c].first)
                        && hasVertexAt(sectionWires.back(), connections[c].second)) {
                        loopConnections.push_back(connections[c]);
                        placed[c] = true;
                    }
                }
            }
            std::optional<LoopMatch> match;
            if (!loopConnections.empty()) {
                match = connectedLoops(sectionWires.front(), sectionWires.back(), loopConnections);
            }
            // ops#1071: an unconnected two-profile loop pair with different vertex counts is paired
            // as Onshape's, one chain from a start pair, and then lofts as a connected one
            else if (automaticStarts && connections.empty() && sectionWires.size() == 2 && !closed
                     && !legacy && sectionWires.front().shapeType() == TopAbs_WIRE
                     && sectionWires.back().shapeType() == TopAbs_WIRE
                     && BRep_Tool::IsClosed(sectionWires.front().getShape())
                     && BRep_Tool::IsClosed(sectionWires.back().getShape())) {
                match = unconnectedMatch(sectionWires.front(), sectionWires.back());
                if (match) {
                    automaticUsed = true;
                    if (startTestHook()) {
                        throw Base::CADKernelError("Loft: test hook, the automatic start fails");
                    }
                }
            }
            const bool connected = match.has_value();
            if (connected) {
                sectionWires.front() = match->wireA;
                sectionWires.back() = match->wireB;
            }
            // ops#655: vertices pair up as Onshape's. Only where the surface stays the same: two
            // profiles, or ruled; a smooth loft through 3+ sections would move (deferred issue)
            else if (sectionWires.size() == 2 || Ruled.getValue()) {
                reseamSections(sectionWires);
            }
            frontReseamed = frontReseamed || !unseamed.IsSame(sectionWires.front().getShape());
            // ops#655: a profile condition rebuilds the ruled loft's side faces
            const bool conditioned = startSet || endSet;
            if (conditioned) {
                if (sectionWires.size() != 2 || closed) {
                    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Loft: Normal to profile needs exactly two profiles"
                    ));
                }
                if (sectionWires.front().shapeType() == TopAbs_VERTEX
                    || sectionWires.back().shapeType() == TopAbs_VERTEX) {
                    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Loft: Normal to profile needs two planar profiles, not a point profile"
                    ));
                }
            }
            auto shell = makeTopoShape().makeElementLoft(
                sectionWires,
                Part::IsSolid::notSolid,
                Ruled.getValue() || conditioned ? Part::IsRuled::ruled : Part::IsRuled::notRuled,
                closed ? Part::IsClosed::closed : Part::IsClosed::notClosed,
                5,
                nullptr,
                !connected  // ops#640: connected loops are matched already
            );
            // ops#933: two polygons the compatibility step paired half a turn apart, paired anew
            if (!connected && !conditioned && !closed && sectionWires.size() == 2) {
                if (auto unturned
                    = unturnedSection(shell, sectionWires.front(), sectionWires.back())) {
                    sectionWires.back() = *unturned;
                    shell = makeTopoShape().makeElementLoft(
                        sectionWires,
                        Part::IsSolid::notSolid,
                        Ruled.getValue() ? Part::IsRuled::ruled : Part::IsRuled::notRuled,
                        Part::IsClosed::notClosed,
                        5,
                        nullptr,
                        false
                    );
                }
            }
            if (conditioned) {
                shell = withProfileConditions(
                    shell,
                    sectionWires.front().getShape(),
                    sectionWires.back().getShape(),
                    startSet,
                    StartMagnitude.getValue(),
                    endSet,
                    EndMagnitude.getValue(),
                    legacy
                );
                // ops#963 B: the conditions rebuild every side as a B-spline; a flat one is a plane
                // again, as makeElementLoft left it and as Onshape's is, so refine merges it with
                // the faces in its plane (a circular pattern's copies of it)
                Part::makeLoftCanonical(shell);
            }
            // ops#1046 B + C: Onshape's side edges between smooth joints (fork-1.0.0's Legacy
            // conditions stay as they were)
            if (match && !legacy && !closed) {
                SideConditions sides;
                sides.start = startSet;
                sides.startMagnitude = StartMagnitude.getValue();
                sides.end = endSet;
                sides.endMagnitude = EndMagnitude.getValue();
                shell = mergeSmoothRuns(shell, *match, sides);
                sectionWires.front() = match->wireA;
                sectionWires.back() = match->wireB;
                frontReseamed = frontReseamed || !unseamed.IsSame(sectionWires.front().getShape());
            }
            shells.push_back(shell);
        }
        if (std::find(placed.begin(), placed.end(), false) != placed.end()) {
            throw Base::CADKernelError(
                QT_TRANSLATE_NOOP("Exception", "Loft: a connection's vertex is not on its profile")
            );
        }

        // build the top and bottom face, sew the shell and build the final solid
        auto capFace = [&](const std::vector<TopoShape>& capWires) {
            const char* faceMaker[] = {
                "Part::FaceMakerBullseye",
                "Part::FaceMakerCheese",
                "Part::FaceMakerSimple",
                "Part::FaceMakerUnified",
            };
            TopoShape face;
            for (size_t i = 0; i < std::size(faceMaker); i++) {
                try {
                    face = makeTopoShape(false).makeElementFace(capWires, nullptr, faceMaker[i]);
                    break;
                }
                catch (...) {
                    if (i == std::size(faceMaker) - 1) {
                        throw;
                    }
                    continue;
                }
            }
            return face;
        };

        TopoShape front;
        if (wiresections[0].front().shapeType() != TopAbs_VERTEX) {
            if (frontReseamed) {
                // ops#655: the cap takes the moved seam too, or the sketch's seam vertex comes back
                std::vector<TopoShape> frontwires;
                for (auto& sectionWires : wiresections) {
                    frontwires.push_back(sectionWires.front());
                }
                front = capFace(frontwires);
            }
            else {
                front = getTopoShapeVerifiedFace();
                if (front.isNull()) {
                    return new App::DocumentObjectExecReturn(
                        QT_TRANSLATE_NOOP("Exception", "Loft: Creating a face from sketch failed")
                    );
                }
                front.move(invObjLoc);
            }
        }

        TopoShape back;
        if (wiresections[0].back().shapeType() != TopAbs_VERTEX) {
            std::vector<TopoShape> backwires;
            for (auto& sectionWires : wiresections) {
                backwires.push_back(sectionWires.back());
            }
            back = capFace(backwires);
        }

        if (!front.isNull() || !back.isNull()) {
            BRepBuilderAPI_Sewing sewer;
            sewer.SetTolerance(Precision::Confusion());
            if (!front.isNull()) {
                sewer.Add(front.getShape());
            }
            if (!back.isNull()) {
                sewer.Add(back.getShape());
            }
            for (auto& s : shells) {
                sewer.Add(s.getShape());
            }

            sewer.Perform();

            if (!front.isNull()) {
                shells.push_back(front);
            }
            if (!back.isNull()) {
                shells.push_back(back);
            }
            // equivalent of the removed: result = result.makeElementShape(sewer,shells);
            result = result.makeShapeWithElementMap(
                sewer.SewedShape(),
                Part::MapperSewing(sewer),
                shells,
                Part::OpCodes::Sewing
            );
        }

        if (!result.countSubShapes(TopAbs_SHELL)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Loft: Failed to create shell")
            );
        }
        shapes = result.getSubTopoShapes(TopAbs_SHELL);

        for (auto& s : shapes) {
            // build the solid
            s = s.makeElementSolid();
            BRepClass3d_SolidClassifier SC(s.getShape());
            SC.PerformInfinitePoint(Precision::Confusion());
            if (SC.State() == TopAbs_IN) {
                s.setShape(s.getShape().Reversed(), false);
            }
            if ((startSet || endSet) && !legacy  // fork-1.0.0 built these
                && crossesACap(
                    s.getShape(),
                    wiresections.front().front().getShape(),
                    wiresections.front().back().getShape()
                )) {
                throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Loft: the side crosses a profile's face (Onshape: LOFT_INVALID); change the "
                    "condition's magnitude"
                ));
            }
        }

        AddSubShape.setValue(result.makeElementCompound(
            shapes,
            nullptr,
            Part::TopoShape::SingleShapeCompoundCreationPolicy::returnShape
        ));

        if (shapes.size() > 1) {
            result.makeElementFuse(shapes);
        }
        else {
            result = shapes.front();
        }

        if (base.isNull()) {
            // A Remove or an Intersect with nothing before it makes nothing, never its tool as
            // material, as an Extrude's (ops#640 rank 20, H3): FeatureAddSub::recompute fails it,
            // "Nothing to cut"
            if (getAddSubType() == FeatureAddSub::Type::Subtractive) {
                this->rawShape = TopoShape();  // a Refine-only change recomputes fully
                Shape.setValue(TopoShape());
                return App::DocumentObject::StdReturn;
            }
            if (!isSingleSolidRuleSatisfied(result.getShape())) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Result has multiple solids: enable 'Allow Compound' in the active body."
                ));
            }
            Shape.setValue(getSolid(result));
            return App::DocumentObject::StdReturn;
        }

        result.Tag = -getID();

        TopoShape boolOp = makeTopoShape();
        try {
            boolOp.makeElementBoolean(
                getBooleanMaker(),
                {base, result},
                nullptr,
                FuzzyTolerance.getValue(),
                Part::ElementMapPolicy::Propagate,
                booleanInputCheck(),
                &booleanInputsValid
            );
        }
        catch (Standard_Failure&) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Failed to perform boolean operation")
            );
        }
        // An Intersect that shares no volume with its base leaves the base as it was, healthy, with
        // Onshape's info, as a Revolve's and an Extrude's (hands-on R7, ops#640 rank 20, H3)
        if (getBooleanOperation() == BooleanOperation::Common
            && (boolOp.isNull() || !boolOp.hasSubShape(TopAbs_SOLID))) {
            if (auto doc = getDocument(); doc && !SiblingOf.getValue()) {
                static const std::string text = "Selected tools and targets do not intersect";
                const char* previous = doc->getWarningDescription(this);
                doc->setWarning(
                    this,
                    previous && *previous ? std::string(previous) + "\n" + text : text
                );
            }
            this->rawShape = TopoShape();
            Shape.setValue(base);
            return App::DocumentObject::StdReturn;
        }
        TopoShape solid = getSolid(boolOp);
        // lets check if the result is a solid
        if (solid.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is not a solid")
            );
        }
        // store shape before refinement
        this->rawShape = boolOp;
        boolOp = refineShapeIfActive(boolOp);
        if (!isSingleSolidRuleSatisfied(boolOp.getShape())) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Result has multiple solids: enable 'Allow Compound' in the active body."
            ));
        }
        boolOp = getSolid(boolOp);
        Shape.setValue(boolOp);
        return App::DocumentObject::StdReturn;
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (...) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Loft: A fatal error occurred when making the loft")
        );
    }
}

PROPERTY_SOURCE(PartDesign::AdditiveLoft, PartDesign::Loft)
AdditiveLoft::AdditiveLoft()
{
    defineAdditive();
    // New / Add / Remove / Intersect on one Loft (FreeCAD-CH ops#640 rank 20)
    allowAllOperations();
}

PROPERTY_SOURCE(PartDesign::SubtractiveLoft, PartDesign::Loft)
SubtractiveLoft::SubtractiveLoft()
{
    defineSubtractive();
    allowAllOperations();
}

void Loft::handleChangedPropertyType(Base::XMLReader& reader, const char* TypeName, App::Property* prop)
{
    // property Sections had the App::PropertyLinkList and was changed to App::PropertyXLinkSubList
    if (prop == &Sections && strcmp(TypeName, "App::PropertyLinkList") == 0) {
        Sections.upgrade(reader, TypeName);
    }
    else {
        ProfileBased::handleChangedPropertyType(reader, TypeName, prop);
    }
}
