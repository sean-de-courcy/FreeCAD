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
#include <limits>
#include <set>

#include <BRepAdaptor_Curve.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <BRepTools_History.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GProp_GProps.hxx>
#include <GeomAPI_PointsToBSpline.hxx>
#include <GeomFill_Profiler.hxx>
#include <Geom_BSplineCurve.hxx>
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
#include <gp_Pln.hxx>
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

namespace
{
// ops#655: Onshape's loft start and end condition "Normal to profile" (notes/loft-options.md)

/// k per unit magnitude, as a multiple of the distance between the profiles. Oracle fact GB12 (e)
/// fits k = 30.138 for profiles 30 apart; the rule behind it is asked of the oracle (ops#675), and
/// this is the one place to change when it answers.
constexpr double tangentPerDistance = 30.138 / 30.0;

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
    double endMagnitude
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
    const gp_Vec tangent0 = gp_Vec(normal0) * (startMagnitude * distance0 * tangentPerDistance);
    const gp_Vec tangent1 = gp_Vec(normal1) * (endMagnitude * distance1 * tangentPerDistance);

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
        GeomFill_Profiler profiler;
        profiler.AddCurve(fit(byArcLength(edge0, start0, middle0, fractions), fractions));
        profiler.AddCurve(fit(byArcLength(edge1, start1, middle1, fractions), fractions));
        profiler.Perform(Precision::PConfusion());
        const int count = profiler.NbPoles();
        TColgp_Array1OfPnt row0(1, count);
        TColgp_Array1OfPnt row3(1, count);
        profiler.Poles(1, row0);
        profiler.Poles(2, row3);
        TColgp_Array2OfPnt poles(1, count, 1, 4);
        for (int j = 1; j <= count; ++j) {
            const gp_XYZ p0 = row0(j).XYZ();
            const gp_XYZ p3 = row3(j).XYZ();
            gp_XYZ p1;
            gp_XYZ p2;
            if (start && end) {
                p1 = p0 + tangent0.XYZ() / 3;
                p2 = p3 - tangent1.XYZ() / 3;
            }
            else if (start) {
                p1 = p0 + tangent0.XYZ() / 3;
                p2 = (p1 + p3) / 2;
            }
            else {
                p2 = p3 - tangent1.XYZ() / 3;
                p1 = (p0 + p2) / 2;
            }
            poles(j, 1) = gp_Pnt(p0);
            poles(j, 2) = gp_Pnt(p1);
            poles(j, 3) = gp_Pnt(p2);
            poles(j, 4) = gp_Pnt(p3);
        }
        TColStd_Array1OfReal uKnots(1, profiler.NbKnots());
        TColStd_Array1OfInteger uMults(1, profiler.NbKnots());
        profiler.KnotsAndMults(uKnots, uMults);
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
/// between two of its vertices).
std::vector<TopoDS_Edge> chainWithVertices(
    const std::vector<TopoDS_Edge>& chain,
    const std::vector<double>& at,
    Part::ShapeMapper& mapper
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
        for (const auto& piece : splitEdge(chain[k], local, mapper)) {
            result.push_back(piece);
        }
        start = end;
    }
    return result;
}

/// Pairs a chain of fewer vertices with one of more (both from one connection to the next): the
/// fewer side's inner vertices match the nearest of the other's in order (least total difference of
/// arc-length fractions), and the unmatched vertices between two matched pairs get partners that
/// divide the fewer side's span between those pairs into equal parts by count (Onshape, oracle 14
/// LC1-LC2: thirds, midpoints). Returns the fewer side's new vertex fractions. Every fewer-side
/// vertex is matched, so each such span is one fewer-side edge.
std::vector<double> partnerFractions(const std::vector<double>& fewer, const std::vector<double>& more)
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

/// Onshape leaves tangent (G1) joints unmatched (oracle 14 LC3: a slot to a rounded rectangle builds
/// 4 side faces, a side face spanning several edges). Edge i must pair with edge i here, so a chain
/// pair that needs new vertices while the shorter chain has a tangent inner joint stops (decision
/// 150; merging such runs into one edge is a later step).
void tangentJointsStop(const std::vector<TopoDS_Edge>& shorter)
{
    for (size_t k = 1; k < shorter.size(); ++k) {
        if (tangentJoint(shorter[k - 1], shorter[k])) {
            throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                "Exception",
                "Loft: between two connections the profiles have different edge counts and a tangent "
                "joint; connections can't match tangent joints yet"
            ));
        }
    }
}

/// The two loops matched for the connections (points in the loops' frame, profile first): the
/// section runs the profile's way round, both start at a connection, and between consecutive
/// connections both have the same number of edges. Edge i of one pairs with edge i of the other.
std::pair<Part::TopoShape, Part::TopoShape> connectedLoops(
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
    double sense = na.Dot(nb) / (na.Magnitude() * nb.Magnitude());
    if (std::abs(sense) < 1e-3) {
        const gp_Vec d(meanPoint(samplesA), meanPoint(samplesB));
        sense = na.Dot(d) * nb.Dot(d);
        if (std::abs(sense) < Precision::Confusion()) {
            connectionsCantMatch();
        }
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
    Part::ShapeMapper mapperA, mapperB;
    std::vector<TopoDS_Edge> edgesA, edgesB;
    for (size_t k = 0; k + 1 < cutsA.size(); ++k) {
        std::vector<TopoDS_Edge> chainA(a.begin() + cutsA[k], a.begin() + cutsA[k + 1]);
        std::vector<TopoDS_Edge> chainB(b.begin() + cutsB[k], b.begin() + cutsB[k + 1]);
        if (chainA.size() != chainB.size()) {
            double lengthA = 0, lengthB = 0;
            const auto fa = innerFractions(chainA, lengthA);
            const auto fb = innerFractions(chainB, lengthB);
            tangentJointsStop(chainA.size() < chainB.size() ? chainA : chainB);
            if (chainA.size() < chainB.size()) {
                chainA = chainWithVertices(chainA, partnerFractions(fa, fb), mapperA);
            }
            else {
                chainB = chainWithVertices(chainB, partnerFractions(fb, fa), mapperB);
            }
        }
        edgesA.insert(edgesA.end(), chainA.begin(), chainA.end());
        edgesB.insert(edgesB.end(), chainB.begin(), chainB.end());
    }

    // Onshape's LOFT_INVALID (oracle 14 LC1, LC4): pairs that turn the loft through itself, a half
    // turn or crossed connections. The ruled section between paired points must keep the profiles'
    // sense: its area along the profile's normal stays above 1 % of the smaller profile's.
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
        const gp_Vec normal = na.Normalized();
        const double smaller = std::min(na.Magnitude(), std::abs(nb.Dot(normal)));
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
        if (lowest < 0.01 * smaller) {
            throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                "Exception",
                "Loft: the connections turn the loft through itself (a half turn, or crossed connections)"
            ));
        }
    }

    auto wireOf = [](const std::vector<TopoDS_Edge>& edges,
                     const Part::ShapeMapper& mapper,
                     const Part::TopoShape& source) {
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
    };
    return {wireOf(edgesA, mapperA, profile), wireOf(edgesB, mapperB, section)};
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
        "Scale of the start condition's tangent"
    );
    ADD_PROPERTY_TYPE(
        EndCondition,
        (0L),
        "Loft",
        App::Prop_None,
        "How the loft reaches the last profile: None, or Normal to profile (two planar profiles)"
    );
    EndCondition.setEnums(ConditionEnums);
    ADD_PROPERTY_TYPE(EndMagnitude, (1.0), "Loft", App::Prop_None, "Scale of the end condition's tangent");
    ADD_PROPERTY_TYPE(
        Connections,
        (nullptr),
        "Loft",
        App::Prop_None,
        "Vertex pairs the loft joins, one vertex on the profile and one on the section (two profiles)"
    );
    Connections.setValue(nullptr);
}

const char* Loft::ConditionEnums[] = {"None", "Normal to profile", nullptr};

short Loft::mustExecute() const
{
    if (Sections.isTouched()) {
        return 1;
    }
    if (Ruled.isTouched()) {
        return 1;
    }
    if (Closed.isTouched() || StartCondition.isTouched() || StartMagnitude.isTouched()
        || EndCondition.isTouched() || EndMagnitude.isTouched() || Connections.isTouched()) {
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
            const bool connected = !loopConnections.empty();
            if (connected) {
                auto matched = connectedLoops(sectionWires.front(), sectionWires.back(), loopConnections);
                sectionWires.front() = matched.first;
                sectionWires.back() = matched.second;
            }
            // ops#655: vertices pair up as Onshape's. Only where the surface stays the same: two
            // profiles, or ruled; a smooth loft through 3+ sections would move (deferred issue)
            else if (sectionWires.size() == 2 || Ruled.getValue()) {
                reseamSections(sectionWires);
            }
            frontReseamed = frontReseamed || !unseamed.IsSame(sectionWires.front().getShape());
            // ops#655: a profile condition rebuilds the ruled loft's side faces
            const bool conditioned = StartCondition.getValue() != 0 || EndCondition.getValue() != 0;
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
            if (conditioned) {
                shell = withProfileConditions(
                    shell,
                    sectionWires.front().getShape(),
                    sectionWires.back().getShape(),
                    StartCondition.getValue() != 0,
                    StartMagnitude.getValue(),
                    EndCondition.getValue() != 0,
                    EndMagnitude.getValue()
                );
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
