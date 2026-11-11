// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                               *
 *                                                                            *
 *   This file is part of the FreeCAD CAx development system.                 *
 *                                                                            *
 *   This library is free software; you can redistribute it and/or            *
 *   modify it under the terms of the GNU Library General Public              *
 *   License as published by the Free Software Foundation; either             *
 *   version 2 of the License, or (at your option) any later version.         *
 *                                                                            *
 *   This library  is distributed in the hope that it will be useful,         *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of           *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            *
 *   GNU Library General Public License for more details.                     *
 *                                                                            *
 *   You should have received a copy of the GNU Library General Public        *
 *   License along with this library; see the file COPYING.LIB. If not,       *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,            *
 *   Suite 330, Boston, MA  02111-1307, USA                                   *
 *                                                                            *
 ******************************************************************************/

#include <algorithm>
#include <cmath>
#include <limits>

#include <BRepAdaptor_Curve.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepLib_FindSurface.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <Geom_Plane.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Quaternion.hxx>
#include <gp_Vec.hxx>

#include <Base/Exception.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/TopoShape.h>

#include "FeatureCurvePattern.h"

using namespace PartDesign;

namespace PartDesign
{

PROPERTY_SOURCE(PartDesign::CurvePattern, PartDesign::Transformed)

const App::PropertyIntegerConstraint::Constraints CurvePattern::intOccurrences = {
    1,
    std::numeric_limits<int>::max(),
    1
};

const char* CurvePattern::OrientationEnums[] = {"Follow path", "Keep orientation", nullptr};

CurvePattern::CurvePattern()
{
    ADD_PROPERTY_TYPE(Path, (nullptr), "CurvePattern", App::Prop_None, "The path: a connected chain of edges");
    ADD_PROPERTY_TYPE(
        Occurrences,
        (3),
        "CurvePattern",
        App::Prop_None,
        "The number of instances, the original included"
    );
    Occurrences.setConstraints(&intOccurrences);
    ADD_PROPERTY_TYPE(Reversed, (false), "CurvePattern", App::Prop_None, "Run from the path's other end");
    ADD_PROPERTY_TYPE(
        Orientation,
        (0L),
        "CurvePattern",
        App::Prop_None,
        "Follow path: the instances turn with the path's tangent. Keep orientation: they are only moved"
    );
    Orientation.setEnums(OrientationEnums);
    ADD_PROPERTY_TYPE(
        SkippedInstances,
        (),
        "Skip",
        App::Prop_None,
        "Instances not made: indexes counted from 0 at the original"
    );
}

short CurvePattern::mustExecute() const
{
    if (Path.isTouched() || Occurrences.isTouched() || Reversed.isTouched() || Orientation.isTouched()
        || SkippedInstances.isTouched()) {
        return 1;
    }
    return Transformed::mustExecute();
}

namespace
{

bool hasEdge(const std::vector<TopoDS_Edge>& edges, const TopoDS_Edge& edge)
{
    return std::ranges::any_of(edges, [&edge](const TopoDS_Edge& e) { return e.IsSame(edge); });
}

/// An edge's start or end point as the edge runs (its orientation applied)
gp_Pnt endPoint(const TopoDS_Edge& edge, bool last)
{
    TopoDS_Vertex first;
    TopoDS_Vertex end;
    TopExp::Vertices(edge, first, end, /*CumOri=*/true);
    return BRep_Tool::Pnt(last ? end : first);
}

/// The unit tangent of `curve` at `u`, along the edge's run (reversed for a reversed edge)
gp_Vec tangentAt(const BRepAdaptor_Curve& curve, double u, bool reversed)
{
    gp_Pnt p;
    gp_Vec v;
    curve.D1(u, p, v);
    if (v.Magnitude() < Precision::Confusion()) {
        // A degenerate point of the parametrization: the chord to a point just past it
        const double span = curve.LastParameter() - curve.FirstParameter();
        const double step = span * 1e-6 * (u + span * 1e-6 > curve.LastParameter() ? -1.0 : 1.0);
        v = gp_Vec(p, curve.Value(u + step));
        if (step < 0) {
            v.Reverse();
        }
        if (v.Magnitude() < Precision::Confusion()) {
            throw Base::ValueError("The path has a point with no direction");
        }
    }
    v.Normalize();
    return reversed ? v.Reversed() : v;
}

/// A vector of `normal` made perpendicular to `tangent` and unit; or any perpendicular
gp_Vec perpendicular(const gp_Vec& tangent, const gp_Vec& normal)
{
    gp_Vec r = normal - tangent * normal.Dot(tangent);
    if (r.Magnitude() < 1e-9) {
        // any direction across the tangent: the axis it has least of
        const double ax = std::fabs(tangent.X());
        const double ay = std::fabs(tangent.Y());
        const double az = std::fabs(tangent.Z());
        gp_Vec axis = ax <= ay && ax <= az ? gp_Vec(1, 0, 0) : (ay <= az ? gp_Vec(0, 1, 0) : gp_Vec(0, 0, 1));
        r = tangent.Crossed(axis);
    }
    r.Normalize();
    return r;
}

}  // namespace

TopoDS_Wire CurvePattern::getPathWire() const
{
    App::DocumentObject* obj = Path.getValue();
    if (!obj) {
        throw Base::ValueError("Select a path");
    }
    auto feature = freecad_cast<Part::Feature*>(obj);
    if (!feature) {
        throw Base::ValueError("The path must be edges of a sketch or a feature");
    }
    const TopLoc_Location toHere = getLocation().Inverted();
    const Part::TopoShape shape = feature->Shape.getShape();

    std::vector<TopoDS_Edge> edges;
    auto add = [&](const TopoDS_Shape& s) {
        if (s.IsNull() || s.ShapeType() != TopAbs_EDGE) {
            throw Base::ValueError("The path must be edges");
        }
        TopoDS_Edge edge = TopoDS::Edge(s.Moved(toHere));
        if (!BRep_Tool::Degenerated(edge) && !hasEdge(edges, edge)) {
            edges.push_back(edge);
        }
    };
    std::vector<std::string> subs;
    for (const auto& sub : Path.getSubValues()) {
        if (!sub.empty()) {
            subs.push_back(sub);
        }
    }
    if (subs.empty()) {
        // Whole: all its edges
        for (TopExp_Explorer xp(shape.getShape(), TopAbs_EDGE); xp.More(); xp.Next()) {
            add(xp.Current());
        }
    }
    for (const auto& sub : subs) {
        TopoDS_Shape s;
        try {
            s = shape.getSubShape(sub.c_str());
        }
        catch (const Standard_Failure&) {
        }
        catch (const Base::Exception&) {
        }
        if (s.IsNull()) {
            throw Base::ValueError("A path edge is missing: " + sub);
        }
        add(s);
    }
    if (edges.empty()) {
        throw Base::ValueError("Select a path");
    }

    // One connected chain, in any pick order
    TopTools_ListOfShape list;
    for (const auto& edge : edges) {
        list.Append(edge);
    }
    BRepBuilderAPI_MakeWire maker;
    maker.Add(list);
    if (!maker.IsDone()) {
        throw Base::ValueError("The path's edges must form one connected chain");
    }
    TopoDS_Wire wire = maker.Wire();
    // A branch (three edges at a point) or a second chain: the walk doesn't reach every edge
    std::vector<TopoDS_Edge> ordered;
    for (BRepTools_WireExplorer xp(wire); xp.More(); xp.Next()) {
        ordered.push_back(xp.Current());
    }
    int count = 0;
    for (TopExp_Explorer xp(wire, TopAbs_EDGE); xp.More(); xp.Next()) {
        ++count;
    }
    if (ordered.size() != edges.size() || count != static_cast<int>(edges.size())) {
        throw Base::ValueError("The path's edges must form one connected chain");
    }
    // The chain's own direction runs as its first edge does: a sketch's edge from its start
    if (Reversed.getValue()) {
        std::ranges::reverse(ordered);
        for (auto& edge : ordered) {
            edge.Reverse();
        }
    }
    TopoDS_Wire result;
    BRep_Builder builder;
    builder.MakeWire(result);
    for (const auto& edge : ordered) {
        builder.Add(result, edge);
    }
    result.Closed(BRep_Tool::IsClosed(wire));
    return result;
}

std::vector<CurvePattern::Frame> CurvePattern::framesAlong(
    const TopoDS_Wire& wire,
    const std::vector<double>& lengths
)
{
    std::vector<TopoDS_Edge> edges;
    for (BRepTools_WireExplorer xp(wire); xp.More(); xp.Next()) {
        edges.push_back(xp.Current());
    }
    if (edges.empty()) {
        throw Base::ValueError("Select a path");
    }

    // The start normal: the plane's for a planar path, else any across the start tangent
    gp_Vec normal0(0, 0, 1);
    BRepLib_FindSurface plane(wire, Precision::Confusion(), /*OnlyPlane=*/true);
    if (plane.Found()) {
        auto surface = Handle(Geom_Plane)::DownCast(plane.Surface());
        if (!surface.IsNull()) {
            normal0 = gp_Vec(surface->Axis().Direction());
        }
    }

    std::vector<Frame> frames(lengths.size());
    std::size_t next = 0;  // the next length to place
    double done = 0.0;     // the arc length up to the current edge
    bool started = false;
    gp_Pnt x;  // the walk's point, tangent and normal
    gp_Vec t;
    gp_Vec r;

    auto store = [&](std::size_t index) {
        frames[index] = Frame {x, gp_Dir(t), gp_Dir(r)};
    };
    // Double reflection (Wang et al. 2008) to the point p with tangent tn
    auto stepTo = [&](const gp_Pnt& p, const gp_Vec& tn) {
        const gp_Vec v1(x, p);
        const double c1 = v1.SquareMagnitude();
        gp_Vec rL = r;
        gp_Vec tL = t;
        if (c1 > Precision::SquareConfusion() * 1e-4) {
            rL = r - v1 * (2.0 / c1 * v1.Dot(r));
            tL = t - v1 * (2.0 / c1 * v1.Dot(t));
        }
        const gp_Vec v2 = tn - tL;
        const double c2 = v2.SquareMagnitude();
        gp_Vec rn = rL;
        if (c2 > 1e-24) {
            rn = rL - v2 * (2.0 / c2 * v2.Dot(rL));
        }
        x = p;
        t = tn;
        r = perpendicular(t, rn);
    };

    for (std::size_t e = 0; e < edges.size(); ++e) {
        const TopoDS_Edge& edge = edges[e];
        const bool reversed = edge.Orientation() == TopAbs_REVERSED;
        BRepAdaptor_Curve curve(edge);
        const double u0 = reversed ? curve.LastParameter() : curve.FirstParameter();
        const double u1 = reversed ? curve.FirstParameter() : curve.LastParameter();
        const double length = GCPnts_AbscissaPoint::Length(curve);
        const gp_Vec tStart = tangentAt(curve, u0, reversed);

        if (!started) {
            x = curve.Value(u0);
            t = tStart;
            r = perpendicular(t, normal0);
            started = true;
        }
        else {
            // A corner: the smallest turn from the last tangent to this edge's first
            x = curve.Value(u0);
            if (t.Angle(tStart) > Precision::Angular()) {
                gp_Quaternion turn(t, tStart);
                r = perpendicular(tStart, turn.Multiply(r));
            }
            t = tStart;
        }

        // The walk's stops on this edge: even steps, and the lengths that fall on it
        constexpr int steps = 64;
        struct Stop
        {
            double s;  // arc length from the edge's start
            long index;  // the length's index, or -1 for a step
        };
        std::vector<Stop> stops;
        for (int i = 1; i <= steps; ++i) {
            stops.push_back({length * i / steps, -1});
        }
        const bool lastEdge = e + 1 == edges.size();
        while (next < lengths.size() && (lengths[next] <= done + length || lastEdge)) {
            stops.push_back({std::clamp(lengths[next] - done, 0.0, length), static_cast<long>(next)});
            ++next;
        }
        std::ranges::stable_sort(stops, [](const Stop& a, const Stop& b) { return a.s < b.s; });

        double at = 0.0;  // the walk's arc length on this edge
        for (const auto& stop : stops) {
            if (stop.s > at + Precision::Confusion()) {
                double u = u1;
                if (stop.s < length - Precision::Confusion()) {
                    GCPnts_AbscissaPoint point(curve, reversed ? -stop.s : stop.s, u0);
                    if (!point.IsDone()) {
                        throw Base::ValueError("The path can't be measured");
                    }
                    u = point.Parameter();
                }
                stepTo(curve.Value(u), tangentAt(curve, u, reversed));
                at = stop.s;
            }
            if (stop.index >= 0) {
                store(static_cast<std::size_t>(stop.index));
            }
        }
        done += length;
    }
    return frames;
}

gp_Trsf CurvePattern::motion(const Frame& from, const Frame& to, bool keepOrientation)
{
    gp_Trsf trsf;
    if (keepOrientation) {
        trsf.SetTranslation(from.point, to.point);
        return trsf;
    }
    const gp_Ax3 a(from.point, from.tangent.Crossed(from.normal), from.tangent);
    const gp_Ax3 b(to.point, to.tangent.Crossed(to.normal), to.tangent);
    trsf.SetDisplacement(a, b);
    return trsf;
}

const std::list<gp_Trsf> CurvePattern::getTransformations(const std::vector<App::DocumentObject*>)
{
    const int count = std::max(static_cast<int>(Occurrences.getValue()), 1);
    const TopoDS_Wire wire = getPathWire();
    if (count == 1) {
        return {gp_Trsf()};
    }

    double total = 0.0;
    for (BRepTools_WireExplorer xp(wire); xp.More(); xp.Next()) {
        BRepAdaptor_Curve curve(xp.Current());
        total += GCPnts_AbscissaPoint::Length(curve);
    }
    if (total < Precision::Confusion()) {
        throw Base::ValueError("The path has no length");
    }

    // Closed: the instances share the whole loop, none on the original. A chain whose ends meet
    // is closed even when its vertices weren't merged
    bool closed = BRep_Tool::IsClosed(wire);
    if (!closed) {
        std::vector<TopoDS_Edge> edges;
        for (BRepTools_WireExplorer xp(wire); xp.More(); xp.Next()) {
            edges.push_back(xp.Current());
        }
        closed = endPoint(edges.front(), false).Distance(endPoint(edges.back(), true))
            < Precision::Confusion();
    }
    const double spacing = total / (closed ? count : count - 1);
    std::vector<double> lengths;
    lengths.reserve(count);
    for (int i = 0; i < count; ++i) {
        lengths.push_back(std::min(spacing * i, total));
    }

    const auto frames = framesAlong(wire, lengths);
    const bool keep = Orientation.getValue() == 1;
    std::list<gp_Trsf> transformations;
    transformations.emplace_back();
    for (int i = 1; i < count; ++i) {
        transformations.push_back(motion(frames.front(), frames[i], keep));
    }
    return transformations;
}

std::vector<std::size_t> CurvePattern::getSkippedPositions() const
{
    const int count = std::max(static_cast<int>(Occurrences.getValue()), 1);
    std::vector<std::size_t> positions;
    for (long index : SkippedInstances.getValues()) {
        if (index > 0 && index < count) {
            positions.push_back(static_cast<std::size_t>(index));
        }
    }
    return positions;
}

}  // namespace PartDesign
