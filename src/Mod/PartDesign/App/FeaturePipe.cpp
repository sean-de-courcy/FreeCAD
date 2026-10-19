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
#include <cmath>
#include <functional>
#include <limits>
#include <numbers>
#include <optional>

#include <fmt/format.h>

#include <Mod/Part/App/FCBRepAlgoAPI_Cut.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <BOPAlgo_ArgumentAnalyzer.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Tool.hxx>
#include <gp.hxx>
#include <GProp_GProps.hxx>
#include <gp_Ax2.hxx>
#include <Law_Function.hxx>
#include <Precision.hxx>
#include <ShapeAnalysis_FreeBounds.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Wire.hxx>
#include <TopTools_DataMapOfShapeListOfShape.hxx>
#include <TopTools_DataMapOfShapeShape.hxx>
#include <TopTools_HSequenceOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>


#include <App/Document.h>
#include <App/DocumentObject.h>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Mod/Part/App/FaceMakerCheese.h>
#include <Mod/Part/App/PipeShellApproximation.h>

#include "FeaturePipe.h"
#include "Mod/Part/App/TopoShapeOpCode.h"
#include "Mod/Part/App/TopoShapeMapper.h"
#include "FeatureLoft.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true);

using namespace PartDesign;

namespace
{
// The pipe shell's history, plus the wires where it starts and ends (ops#351). MakePipeShell
// reports the side faces and edges that the sections' edges and vertices generate, but nothing
// for its end wires, so those were named `UPP` from the side faces, and a start edge's name had
// the same shape as a bend edge's beside it. As in a Pad, and Helix's caps: the start wire's
// edges and vertices are the first section's modified, so they keep its names (the sketch's
// own), and the end wire's are the last section's projected (`PRJ`): for a pipe of one profile,
// the profile moved to the end of the sweep. The shell starts where the spine does, and the ends
// may swap roles, so the names stay with the end the sections say; a tie (a closed spine) keeps
// the start.
// - One profile: the ends swap when the profile lies nearer the spine's far end (a spine drawn
//   towards it, perhaps extended past it), so the names stay with the end at or nearest the
//   profile's place. The switch point is the spine's middle: an edit that moves the profile (or
//   the spine's nearer end) across it moves the profile's names, and whatever references them,
//   to the other end.
// - Several sections: the first and last decide together, by the pairing of sections and ends
//   whose distances add up to less, each section's distance the mean over its vertices (so a
//   section weighs the same whatever its number of vertices). There is no middle switch: the
//   ends follow the sections' order along the spine (on a straight one, they swap when the
//   profile lies beyond the last section). Each wire of a holed section decides alone.
// Each end element is found through the side face or edge its section element generated. A
// point section names only its end's vertex. Edges at a bend, a corner or a middle section have
// no section element of their own: they keep their `UPP` names.
class MapperPipeShellEnds: public Part::MapperMaker
{
public:
    /// \a first and \a last are the first and last sections added to \a pipe, a wire or a
    /// vertex each (the same for a pipe of one profile); \a point is \a first when it is the
    /// profile's point, which the side shapes' history leaves out (it isn't otherwise a source).
    /// A piece of a union (sweepPiecesAndFuse) names its end only when it is the last, with
    /// \a projectEnd; \a origins, when given, binds each element of \a last to the profile's
    /// element it was swept from, and the end projects those instead (a source of the shape too).
    MapperPipeShellEnds(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& first,
        const TopoDS_Shape& last,
        const TopoDS_Shape& point,
        bool projectEnd = true,
        const TopTools_DataMapOfShapeShape* origins = nullptr
    )
        : MapperMaker(pipe)
        , point(point)
    {
        TopTools_IndexedMapOfShape startElements;
        TopTools_IndexedMapOfShape endElements;
        TopExp::MapShapes(pipe.FirstShape(), startElements);
        TopExp::MapShapes(pipe.LastShape(), endElements);
        double kept = distanceTo(first, pipe.FirstShape());
        double swapped = distanceTo(first, pipe.LastShape());
        // One profile: its distances alone (the two sections' terms would be the same on both
        // sides, and nothing would ever swap)
        if (!last.IsSame(first)) {
            kept += distanceTo(last, pipe.LastShape());
            swapped += distanceTo(last, pipe.FirstShape());
        }
        const bool reversed = swapped + Precision::Confusion() < kept;
        const TopTools_IndexedMapOfShape& own = reversed ? endElements : startElements;
        const TopTools_IndexedMapOfShape& other = reversed ? startElements : endElements;
        bindEnds(pipe, first, own, nullptr, starts);
        // With a closed spine the shell ends where it starts: those elements keep the first
        // section's names
        bindEnds(pipe, last, other, &own, bound);
        if (!projectEnd) {
            return;
        }
        if (!origins) {
            ends = bound;
            return;
        }
        for (TopTools_DataMapIteratorOfDataMapOfShapeListOfShape it(bound); it.More(); it.Next()) {
            if (const TopoDS_Shape* origin = origins->Seek(it.Key())) {
                ends.Bind(*origin, it.Value());
            }
        }
    }

    /// Each element of the last section and the elements of the shell's end it became, whether
    /// or not the end is named from them
    const TopTools_DataMapOfShapeListOfShape& endsOf() const
    {
        return bound;
    }

    const std::vector<TopoDS_Shape>& modified(const TopoDS_Shape& s) const override
    {
        if (s.IsSame(point)) {
            _res.clear();
        }
        else {
            MapperMaker::modified(s);
        }
        if (const TopTools_ListOfShape* elements = starts.Seek(s)) {
            for (const TopoDS_Shape& element : *elements) {
                _res.push_back(element);
            }
        }
        return _res;
    }

    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& s) const override
    {
        if (s.IsSame(point)) {
            _res.clear();
            return _res;
        }
        return MapperMaker::generated(s);
    }

    const std::vector<TopoDS_Shape>& projected(const TopoDS_Shape& s) const override
    {
        _res.clear();
        if (const TopTools_ListOfShape* elements = ends.Seek(s)) {
            for (const TopoDS_Shape& element : *elements) {
                _res.push_back(element);
            }
        }
        return _res;
    }

private:
    /// How far \a section lies from the shell's end \a end: the mean over its vertices of the
    /// distance to the nearest vertex of the end, so that each section weighs the same whatever
    /// its number of vertices; infinite when either has none
    static double distanceTo(const TopoDS_Shape& section, const TopoDS_Shape& end)
    {
        constexpr double none = std::numeric_limits<double>::infinity();
        if (section.IsNull() || end.IsNull()) {
            return none;
        }
        TopTools_IndexedMapOfShape sectionVertices;
        TopTools_IndexedMapOfShape endVertices;
        TopExp::MapShapes(section, TopAbs_VERTEX, sectionVertices);
        TopExp::MapShapes(end, TopAbs_VERTEX, endVertices);
        if (sectionVertices.IsEmpty() || endVertices.IsEmpty()) {
            return none;
        }
        double sum = 0;
        for (int i = 1; i <= sectionVertices.Extent(); ++i) {
            const gp_Pnt at = BRep_Tool::Pnt(TopoDS::Vertex(sectionVertices(i)));
            double nearest = none;
            for (int j = 1; j <= endVertices.Extent(); ++j) {
                nearest = std::min(
                    nearest,
                    at.Distance(BRep_Tool::Pnt(TopoDS::Vertex(endVertices(j))))
                );
            }
            sum += nearest;
        }
        return sum / sectionVertices.Extent();
    }

    /// Binds each edge and vertex of \a section (in its order) to the elements of one end of
    /// the shell, \a endElements, that the side faces or edges it generated hold; a point
    /// section to the end's vertex
    static void bindEnds(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& section,
        const TopTools_IndexedMapOfShape& endElements,
        const TopTools_IndexedMapOfShape* skip,
        TopTools_DataMapOfShapeListOfShape& bound
    )
    {
        if (section.IsNull()) {
            return;
        }
        auto take = [&](const TopoDS_Shape& element, TopTools_ListOfShape& found) {
            if (endElements.Contains(element) && !(skip && skip->Contains(element))) {
                found.Append(element);
            }
        };
        if (section.ShapeType() == TopAbs_VERTEX) {
            TopTools_ListOfShape found;
            for (int i = 1; i <= endElements.Extent(); ++i) {
                if (endElements(i).ShapeType() == TopAbs_VERTEX) {
                    take(endElements(i), found);
                }
            }
            if (found.Extent() == 1) {
                bound.Bind(section, found);
            }
            return;
        }
        for (TopAbs_ShapeEnum type : {TopAbs_EDGE, TopAbs_VERTEX}) {
            TopTools_IndexedMapOfShape elements;
            TopExp::MapShapes(section, type, elements);
            for (int i = 1; i <= elements.Extent(); ++i) {
                TopTools_IndexedMapOfShape candidates;
                for (const TopoDS_Shape& side : pipe.Generated(elements(i))) {
                    TopExp::MapShapes(side, type, candidates);
                }
                TopTools_ListOfShape found;
                for (int j = 1; j <= candidates.Extent(); ++j) {
                    take(candidates(j), found);
                }
                if (!found.IsEmpty()) {
                    bound.Bind(elements(i), found);
                }
            }
        }
    }

    TopoDS_Shape point;
    TopTools_DataMapOfShapeListOfShape starts;
    TopTools_DataMapOfShapeListOfShape bound;
    TopTools_DataMapOfShapeListOfShape ends;
};

// "Transformed" at the spine's corners (ops#370). It doesn't turn the profile at a corner: the
// section keeps its orientation, and the stretch after the corner is a sheared sweep, as thick
// as the section's extent across the stretch times the cosine of its tilt (the angle between the
// section's normal and the stretch). The tilt adds up over the corners. Near 90 degrees the
// stretch has no thickness; past 90 it runs back through the section's other side, and the one
// sweep crosses itself while BRepCheck still passes it. So:
// - a stretch thinner than 1e-5 mm fails the Pipe, naming the corner (the right-angle case);
// - a stretch past 90 degrees makes the Pipe the union of the pieces between the corners where
//   the tilt crosses 90 degrees, each swept from where the one before ends (on a polyline, the
//   union of the profile's extrusions along the segments);
// - a stretch within 1 degree of the collapse warns: a small change makes the Pipe fail.
// A pipe whose tilt never crosses 90 degrees is one piece, built as before.

/// A spine's vertex where the sweep turns, and the stretch after it
struct Corner
{
    gp_Pnt at;
    /// The cosine of the stretch's tilt, positive while the pipe runs on from the profile's
    /// side it started from, negative once it runs back
    double cosine;
    /// The section's extent across the stretch times |cosine|
    double thickness;
};

/// The stretch's tilt in degrees, past 90 when it runs back
double tiltDegrees(const Corner& corner)
{
    return std::acos(std::clamp(corner.cosine, -1.0, 1.0)) * 180 / std::numbers::pi;
}

/// What "Transformed" does at a spine's corners
struct CornerTilts
{
    /// The edges where the union's pieces after the first start
    std::vector<size_t> pieceStarts;
    /// The first stretch with no thickness
    std::optional<Corner> collapsed;
    /// The stretches within 1 degree of the collapse
    std::vector<Corner> nearCollapse;
    /// Where the first arc starts along which the section folds over itself
    std::optional<gp_Pnt> foldedArc;
    /// Whether a curve other than an arc follows a corner that tilted the section: whether it
    /// folds takes the boolean check
    bool tiltedCurve = false;
};

/// The edges of \a wire in their order along it
std::vector<TopoDS_Edge> edgesInOrder(const TopoDS_Wire& wire)
{
    std::vector<TopoDS_Edge> edges;
    for (BRepTools_WireExplorer it(wire); it.More(); it.Next()) {
        edges.push_back(it.Current());
    }
    return edges;
}

/// The tangent of \a edge in the direction its wire runs, where it starts or ends there
gp_Dir tangentAlong(const TopoDS_Edge& edge, bool atStart)
{
    BRepAdaptor_Curve curve(edge);
    const bool reversed = edge.Orientation() == TopAbs_REVERSED;
    const double at = atStart != reversed ? curve.FirstParameter() : curve.LastParameter();
    gp_Pnt point;
    gp_Vec tangent;
    curve.D1(at, point, tangent);
    if (reversed) {
        tangent.Reverse();
    }
    return gp_Dir(tangent);
}

bool isLine(const TopoDS_Edge& edge)
{
    return BRepAdaptor_Curve(edge).GetType() == GeomAbs_Line;
}

/// The first wire of \a shape (a section the sweep reports), or a null one
TopoDS_Wire firstWire(const TopoDS_Shape& shape)
{
    if (shape.IsNull()) {
        return {};
    }
    if (shape.ShapeType() == TopAbs_WIRE) {
        return TopoDS::Wire(shape);
    }
    TopExp_Explorer it(shape, TopAbs_WIRE);
    return it.More() ? TopoDS::Wire(it.Current()) : TopoDS_Wire();
}

/// Points along \a wire in its order: each edge's start and points inside it
std::vector<gp_Pnt> pointsAlong(const TopoDS_Wire& wire)
{
    constexpr int steps = 64;  // a circle's extent within 0.12 % of its radius
    std::vector<gp_Pnt> points;
    for (BRepTools_WireExplorer it(wire); it.More(); it.Next()) {
        BRepAdaptor_Curve curve(it.Current());
        const bool reversed = it.Current().Orientation() == TopAbs_REVERSED;
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        for (int i = 0; i < steps; ++i) {
            const double t = static_cast<double>(i) / steps;
            const double at = reversed ? last - t * (last - first) : first + t * (last - first);
            points.push_back(curve.Value(at));
        }
    }
    return points;
}

/// The normal of the plane of \a points, oriented by their order around it (Newell's method):
/// none when they enclose no area or don't lie in one plane
std::optional<gp_Dir> planeNormal(const std::vector<gp_Pnt>& points)
{
    gp_XYZ sum(0, 0, 0);
    gp_XYZ centre(0, 0, 0);
    for (size_t i = 0; i < points.size(); ++i) {
        sum += points[i].XYZ().Crossed(points[(i + 1) % points.size()].XYZ());
        centre += points[i].XYZ();
    }
    if (points.empty() || sum.Modulus() < gp::Resolution()) {
        return std::nullopt;
    }
    const gp_Dir normal(sum);
    centre /= static_cast<double>(points.size());
    for (const gp_Pnt& point : points) {
        if (std::abs((point.XYZ() - centre).Dot(normal.XYZ())) > 100 * Precision::Confusion()) {
            return std::nullopt;
        }
    }
    return normal;
}

/// How far \a points reach along \a direction
double extentAlong(const std::vector<gp_Pnt>& points, const gp_Dir& direction)
{
    double low = std::numeric_limits<double>::infinity();
    double high = -low;
    for (const gp_Pnt& point : points) {
        const double at = point.XYZ().Dot(direction.XYZ());
        low = std::min(low, at);
        high = std::max(high, at);
    }
    return high - low;
}

/// A section of the sweep where a spine's edge starts
struct Section
{
    gp_Dir normal;
    std::vector<gp_Pnt> points;
};

/// Whether the section (\a normal, \a points) folds back over itself along the arc \a edge. It
/// turns about the arc's axis, each point at the speed of its distance from the axis, so its
/// points move through its plane one way on one side of the line where that plane meets the
/// plane through the axis, and the other way beyond: the sweep folds where the section reaches
/// across that line (ops#370). A section in the arc's plane only turns within it: no fold here.
bool foldsAlongArc(const TopoDS_Edge& edge, const gp_Dir& normal, const std::vector<gp_Pnt>& points)
{
    const gp_Ax1 axis = BRepAdaptor_Curve(edge).Circle().Axis();
    const gp_Vec across = gp_Vec(normal).Crossed(gp_Vec(axis.Direction()));
    if (across.Magnitude() < gp::Resolution()) {
        return false;
    }
    const gp_Dir side(across);
    double low = std::numeric_limits<double>::infinity();
    double high = -low;
    for (const gp_Pnt& point : points) {
        const double at = gp_Vec(axis.Location(), point).Dot(gp_Vec(side));
        low = std::min(low, at);
        high = std::max(high, at);
    }
    return low < -Precision::Confusion() && high > Precision::Confusion();
}

/// The tilt at each corner of \a spine where "Transformed" keeps the section's orientation,
/// from \a pipe, its sweep of one wire of the profile, set up by \a setup. Along straight edges
/// the section only moves, so its normal is the start's; after a curved one, the sweep of the
/// spine up to the corner gives the section there, as the whole sweep has it (its law is made
/// continuous edge after edge). A profile that isn't one closed planar wire, or lies along the
/// spine at its start, gives nothing.
CornerTilts measureCorners(
    BRepOffsetAPI_MakePipeShell& pipe,
    const TopoDS_Wire& spine,
    const std::function<void(BRepOffsetAPI_MakePipeShell&)>& setup
)
{
    CornerTilts tilts;
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    if (edges.size() < 2) {
        return tilts;
    }
    TopTools_ListOfShape simulated;
    pipe.Simulate(2, simulated);
    const TopoDS_Wire start = firstWire(simulated.First());
    if (start.IsNull() || !BRep_Tool::IsClosed(start)) {
        return tilts;
    }
    const std::vector<gp_Pnt> startPoints = pointsAlong(start);
    const std::optional<gp_Dir> startNormal = planeNormal(startPoints);
    if (!startNormal) {
        return tilts;
    }
    const double startCosine = startNormal->Dot(tangentAlong(edges.front(), true));
    if (std::abs(startCosine) < Precision::Angular()) {
        return tilts;
    }
    const double side = startCosine > 0 ? 1 : -1;
    const double nearLimit = std::sin(std::numbers::pi / 180);
    const double thinnest = 100 * Precision::Confusion();

    const gp_Pnt spineStart = BRep_Tool::Pnt(TopExp::FirstVertex(edges.front(), true));
    // The section where edge k starts, its normal and points: on a straight run the start's,
    // moved there; after a curve, the end of the sweep of the spine up to there
    auto sectionAt = [&](size_t k, bool straightBefore) -> std::optional<Section> {
        if (straightBefore) {
            const gp_Vec move(spineStart, BRep_Tool::Pnt(TopExp::FirstVertex(edges[k], true)));
            std::vector<gp_Pnt> points;
            for (const gp_Pnt& point : startPoints) {
                points.push_back(point.Translated(move));
            }
            return Section {*startNormal, points};
        }
        BRepBuilderAPI_MakeWire upTo;
        for (size_t i = 0; i < k; ++i) {
            upTo.Add(edges[i]);
        }
        BRepOffsetAPI_MakePipeShell part(upTo.Wire());
        setup(part);
        part.Add(start);
        TopTools_ListOfShape ends;
        part.Simulate(2, ends);
        std::vector<gp_Pnt> points = pointsAlong(firstWire(ends.Last()));
        const std::optional<gp_Dir> normal = planeNormal(points);
        if (!normal) {
            return std::nullopt;
        }
        return Section {*normal, points};
    };
    // A curved edge: an arc folds the section where its axis meets it; another curve is left to
    // the boolean check, when the section is tilted to it
    auto checkCurve = [&](size_t k, const Section& section) {
        if (isLine(edges[k])) {
            return;
        }
        if (BRepAdaptor_Curve(edges[k]).GetType() == GeomAbs_Circle) {
            if (!tilts.foldedArc && foldsAlongArc(edges[k], section.normal, section.points)) {
                tilts.foldedArc = BRep_Tool::Pnt(TopExp::FirstVertex(edges[k], true));
            }
        }
        else if (std::abs(section.normal.Dot(tangentAlong(edges[k], true))) < 1 - 1e-9) {
            tilts.tiltedCurve = true;
        }
    };
    checkCurve(0, Section {*startNormal, startPoints});

    bool straight = isLine(edges.front());
    double previous = 1;
    for (size_t k = 1; k < edges.size(); ++k) {
        const gp_Dir out = tangentAlong(edges[k], true);
        const bool corner = tangentAlong(edges[k - 1], false).Angle(out) > Precision::Angular();
        if (!corner && isLine(edges[k])) {
            continue;  // a straight run goes on: nothing changes
        }
        const std::optional<Section> section = sectionAt(k, straight);
        if (!section) {
            return {};
        }
        straight = straight && isLine(edges[k]);
        checkCurve(k, *section);
        if (!corner) {
            continue;
        }
        const gp_Dir& normal = section->normal;
        Corner turn {
            BRep_Tool::Pnt(TopExp::LastVertex(edges[k - 1], true)),
            side * normal.Dot(out),
            std::numeric_limits<double>::infinity()
        };
        const gp_Vec across = gp_Vec(out) - gp_Vec(normal) * normal.Dot(out);
        if (across.Magnitude() > gp::Resolution()) {
            turn.thickness = extentAlong(section->points, gp_Dir(across)) * std::abs(turn.cosine);
        }
        if (turn.thickness < thinnest) {
            tilts.collapsed = turn;
            return tilts;
        }
        if (std::abs(turn.cosine) < nearLimit) {
            tilts.nearCollapse.push_back(turn);
        }
        if ((turn.cosine > 0) != (previous > 0)) {
            tilts.pieceStarts.push_back(k);
        }
        previous = turn.cosine;
    }
    return tilts;
}

/// Whether \a shape holds a solid that passes BRepCheck and encloses a positive volume once
/// oriented (an inside-out one passes BRepCheck: a multisection Pipe on macOS, ops#396)
bool isValidSolid(const Part::TopoShape& shape)
{
    if (!shape.countSubShapes(TopAbs_SOLID) || !BRepCheck_Analyzer(shape.getShape()).IsValid()) {
        return false;
    }
    GProp_GProps properties;
    BRepGProp::VolumeProperties(shape.getShape(), properties);
    return properties.Mass() > Precision::Confusion();
}

/// The union past 90 degrees: \a spine cut into pieces at \a pieceStarts, each piece swept with
/// "Transformed" (\a setup) from where the one before ends, closed with its caps and made a
/// solid, and the pieces fused. \a profiles are the sections the first piece starts from, one
/// per wire of the profile; \a make makes a shape named as this feature's. A null shape when a
/// piece isn't a valid solid (the profile folds over itself within it: a tight curve after a
/// corner of nearly 90 degrees, which no union mends); an exception when OCCT can't fuse the
/// pieces.
/// Each later piece's section is added at the piece's first vertex: added plainly, a section
/// that doesn't lie on the piece's start plane (a profile behind the spine's start) was placed
/// where it lies nearest the piece, and the union came out wrong.
/// Names: the first piece's start keeps the profile's names, and the last piece's end projects
/// them, as the one sweep's ends do, so a reference to either end follows it when an edit takes
/// the pipe across 90 degrees. The other pieces' ends aren't named from their sections (their
/// edges are named from the side faces, `UPP`), each later piece sweeps the end wire of the
/// piece before, so its side faces are named from that wire's edges, and the caps between the
/// pieces carry their piece's index (`PCE<n>`).
Part::TopoShape sweepPiecesAndFuse(
    const TopoDS_Wire& spine,
    const std::vector<size_t>& pieceStarts,
    std::vector<Part::TopoShape> profiles,
    const std::function<void(BRepOffsetAPI_MakePipeShell&)>& setup,
    const std::function<Part::TopoShape(const TopoDS_Shape&)>& make
)
{
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    std::vector<size_t> ends = pieceStarts;
    ends.push_back(edges.size());
    std::vector<TopoDS_Wire> pieces;
    std::vector<TopoDS_Vertex> pieceFirsts;
    size_t begin = 0;
    for (size_t end : ends) {
        BRepBuilderAPI_MakeWire wire;
        for (size_t k = begin; k < end; ++k) {
            wire.Add(edges[k]);
        }
        pieces.push_back(wire.Wire());
        pieceFirsts.push_back(TopExp::FirstVertex(edges[begin], true));
        begin = end;
    }

    std::vector<Part::TopoShape> solids;
    std::vector<Part::TopoShape> sections = profiles;
    // Per wire: each element of the current section, and the profile's element it was swept from
    std::vector<TopTools_DataMapOfShapeShape> origins(sections.size());
    for (size_t index = 0; index < pieces.size(); ++index) {
        const bool first = index == 0;
        const bool last = index + 1 == pieces.size();
        std::vector<Part::TopoShape> shells;
        std::vector<Part::TopoShape> fronts;
        std::vector<Part::TopoShape> backs;
        for (size_t i = 0; i < sections.size(); ++i) {
            const Part::TopoShape& section = sections[i];
            BRepOffsetAPI_MakePipeShell mkPS(pieces[index]);
            setup(mkPS);
            if (first) {
                mkPS.Add(section.getShape());
            }
            else {
                mkPS.Add(section.getShape(), pieceFirsts[index]);
            }
            if (!mkPS.IsReady()) {
                throw Base::CADKernelError("Pipe could not be built");
            }
            const TopoDS_Shape built = mkPS.Shape();
            Part::TopoShape shell = make(TopoDS_Shape());
            const MapperPipeShellEnds mapper(
                mkPS,
                section.getShape(),
                section.getShape(),
                TopoDS_Shape(),
                last,
                first ? nullptr : &origins[i]
            );
            std::vector<Part::TopoShape> sources {section};
            if (last && !first) {
                sources.push_back(profiles[i]);
            }
            shell.makeShapeWithElementMap(built, mapper, sources, Part::OpCodes::PipeShell);
            TopTools_DataMapOfShapeShape next;
            for (TopTools_DataMapIteratorOfDataMapOfShapeListOfShape it(mapper.endsOf()); it.More();
                 it.Next()) {
                const TopoDS_Shape* origin = origins[i].Seek(it.Key());
                for (const TopoDS_Shape& element : it.Value()) {
                    next.Bind(element, origin ? *origin : it.Key());
                }
            }
            origins[i] = next;
            Part::TopoShape front = make(mkPS.FirstShape());
            front.mapSubElement(shell);
            Part::TopoShape back = make(mkPS.LastShape());
            back.mapSubElement(shell);
            shells.push_back(shell);
            fronts.push_back(front);
            backs.push_back(back);
        }

        BRepBuilderAPI_Sewing sewer;
        sewer.SetTolerance(Precision::Confusion());
        for (const Part::TopoShape& shell : shells) {
            sewer.Add(shell.getShape());
        }
        // The pipe's own ends are named from their edges by the sewing, as the one sweep's; a cap
        // between pieces is named, and marked with its piece, before
        std::vector<Part::TopoShape> sources = shells;
        const std::string between = "PCE" + std::to_string(index);
        Part::TopoShape frontface;
        Part::TopoShape backface;
        if (first) {
            frontface.makeElementFace(fronts);
        }
        else {
            frontface = make(TopoDS_Shape());
            frontface.makeElementFace(fronts, between.c_str());
            sources.push_back(frontface);
        }
        if (last) {
            backface.makeElementFace(backs, Part::OpCodes::Sewing);
        }
        else {
            backface = make(TopoDS_Shape());
            backface.makeElementFace(backs, between.c_str());
            sources.push_back(backface);
        }
        sewer.Add(frontface.getShape());
        sewer.Add(backface.getShape());
        sewer.Perform();
        Part::TopoShape solid = make(TopoDS_Shape());
        solid.makeShapeWithElementMap(
            sewer.SewedShape(),
            Part::MapperSewing(sewer),
            sources,
            Part::OpCodes::Sewing
        );
        solid = solid.makeElementSolid();
        BRepClass3d_SolidClassifier classifier(solid.getShape());
        classifier.PerformInfinitePoint(Precision::Confusion());
        if (classifier.State() == TopAbs_IN) {
            solid.setShape(solid.getShape().Reversed(), false);
        }
        if (!isValidSolid(solid)) {
            return {};
        }
        solids.push_back(solid);
        sections = backs;
    }
    // OCCT fails to fuse some pieces (a round profile along an arc after the corner): say so,
    // not with its "Null shape"
    const char* unfused = "Pipe: the pieces of this 'Transformed' pipe past 90 degrees can't be "
                          "fused into a valid solid: try 'Right corner' or 'Round corner'.";
    Part::TopoShape fused = make(TopoDS_Shape());
    try {
        fused.makeElementFuse(solids);
    }
    catch (const Base::Exception&) {
        throw Base::CADKernelError(unfused);
    }
    catch (const Standard_Failure&) {
        throw Base::CADKernelError(unfused);
    }
    if (fused.isNull() || !isValidSolid(fused)) {
        throw Base::CADKernelError(unfused);
    }
    return fused;
}

/// Whether \a a and \a b have their vertices at the same places
bool samePlace(const TopoDS_Shape& a, const TopoDS_Shape& b)
{
    TopTools_IndexedMapOfShape these;
    TopTools_IndexedMapOfShape those;
    TopExp::MapShapes(a, TopAbs_VERTEX, these);
    TopExp::MapShapes(b, TopAbs_VERTEX, those);
    if (these.Extent() != those.Extent()) {
        return false;
    }
    for (int i = 1; i <= these.Extent(); ++i) {
        const gp_Pnt at = BRep_Tool::Pnt(TopoDS::Vertex(these(i)));
        bool found = false;
        for (int j = 1; j <= those.Extent() && !found; ++j) {
            found = at.Distance(BRep_Tool::Pnt(TopoDS::Vertex(those(j)))) < Precision::Confusion();
        }
        if (!found) {
            return false;
        }
    }
    return true;
}

/// Why a pipe's result isn't a valid solid, as far as its \a mode, its \a transition, whether
/// it has several sections (\a multisection) and its spine's sharpest corner (\a corner, none
/// on a smooth spine) tell
std::string whyInvalid(int mode, int transition, bool multisection, const std::optional<std::string>& corner)
{
    std::string text = "Pipe: the result isn't a valid solid.";
    if (mode == 1) {
        text += " 'Fixed' mode keeps the profile's orientation: the spine may turn edge-on to it.";
    }
    else if (mode == 3) {
        text += " 'Auxiliary' mode turns the profile to follow the auxiliary spine: it may turn "
                "it edge-on to the spine, or fold it over itself.";
    }
    else if (!corner) {
        text += " Where the spine curves more tightly than the profile is wide, the sweep folds "
                "over itself.";
    }
    else if (multisection && transition != 0) {
        text += fmt::format(
            " 'Right corner' and 'Round corner' can't join the corners of a pipe with several "
            "sections (the corner at {}): try 'Transformed'.",
            *corner
        );
    }
    else if (multisection) {
        text += fmt::format(
            " The sections may twist or cross over each other along the spine, or at its corner "
            "at {}.",
            *corner
        );
    }
    else if (transition == 0) {
        text += fmt::format(
            " Where the spine curves tightly after a corner of nearly 90 degrees (the sharpest is "
            "at {}), 'Transformed' folds the profile over itself: try 'Right corner' or 'Round "
            "corner'.",
            *corner
        );
    }
    else {
        text += fmt::format(
            " 'Right corner' and 'Round corner' can't join a corner that turns nearly back on "
            "itself (the sharpest is at {}): try 'Transformed' there.",
            *corner
        );
    }
    return text;
}

/// Where \a spine turns most sharply, none when it turns nowhere
std::optional<gp_Pnt> sharpestCorner(const TopoDS_Wire& spine)
{
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    std::optional<gp_Pnt> sharpest;
    double most = Precision::Angular();
    const size_t joints = BRep_Tool::IsClosed(spine) ? edges.size() : edges.size() - 1;
    for (size_t k = 0; edges.size() > 1 && k < joints; ++k) {
        const TopoDS_Edge& before = edges[k];
        const TopoDS_Edge& after = edges[(k + 1) % edges.size()];
        const double angle = tangentAlong(before, false).Angle(tangentAlong(after, true));
        if (angle > most) {
            most = angle;
            sharpest = BRep_Tool::Pnt(TopExp::LastVertex(before, true));
        }
    }
    return sharpest;
}

/// Whether the boolean check finds no self-intersection in \a shapes
bool selfIntersectionFree(const std::vector<Part::TopoShape>& shapes)
{
    for (const Part::TopoShape& shape : shapes) {
        BOPAlgo_ArgumentAnalyzer check;
        check.SetShape1(shape.getShape());
        check.ArgumentTypeMode() = false;
        check.SelfInterMode() = true;
        check.SmallEdgeMode() = false;
        check.RebuildFaceMode() = false;
        check.TangentMode() = false;
        check.MergeVertexMode() = false;
        check.MergeEdgeMode() = false;
        check.ContinuityMode() = false;
        check.CurveOnSurfaceMode() = false;
        check.Perform();
        if (check.HasFaulty()) {
            return false;
        }
    }
    return true;
}

/// \a point as text, "(x, y, z)", without rounding noise
std::string pointText(const gp_Pnt& point)
{
    auto coordinate = [](double value) {
        return std::abs(value) < 1e-9 ? 0.0 : value;
    };
    return fmt::format(
        "({:.6g}, {:.6g}, {:.6g})",
        coordinate(point.X()),
        coordinate(point.Y()),
        coordinate(point.Z())
    );
}
}  // namespace

const char* Pipe::TypeEnums[] = {"FullPath", "UpToFace", nullptr};
const char* Pipe::TransitionEnums[] = {"Transformed", "Right corner", "Round corner", nullptr};
const char* Pipe::ModeEnums[] = {"Standard", "Fixed", "Frenet", "Auxiliary", "Binormal", nullptr};
const char* Pipe::TransformEnums[]
    = {"Constant", "Multisection", "Linear", "S-shape", "Interpolation", nullptr};


PROPERTY_SOURCE(PartDesign::Pipe, PartDesign::ProfileBased)

Pipe::Pipe()
{
    ADD_PROPERTY_TYPE(Sections, (nullptr), "Sweep", App::Prop_None, "List of sections");
    Sections.setValue(nullptr);
    ADD_PROPERTY_TYPE(Spine, (nullptr), "Sweep", App::Prop_None, "Path to sweep along");
    ADD_PROPERTY_TYPE(SpineTangent, (false), "Sweep", App::Prop_None, "Include tangent edges into path");
    ADD_PROPERTY_TYPE(AuxiliarySpine, (nullptr), "Sweep", App::Prop_None, "Secondary path to orient sweep");
    ADD_PROPERTY_TYPE(
        AuxiliarySpineTangent,
        (false),
        "Sweep",
        App::Prop_None,
        "Include tangent edges into secondary path"
    );
    ADD_PROPERTY_TYPE(
        AuxiliaryCurvilinear,
        (true),
        "Sweep",
        App::Prop_None,
        "Calculate normal between equidistant points on both spines"
    );
    ADD_PROPERTY_TYPE(Mode, (long(0)), "Sweep", App::Prop_None, "Profile mode");
    ADD_PROPERTY_TYPE(
        Binormal,
        (Base::Vector3d()),
        "Sweep",
        App::Prop_None,
        "Binormal vector for corresponding orientation mode"
    );
    // New pipes join the spine's corners as "Right corner", as Part's Sweep does: "Transformed"
    // shears the pipe after a corner (ops#370). A saved pipe keeps its value: an enumeration is
    // always saved.
    ADD_PROPERTY_TYPE(Transition, (long(1)), "Sweep", App::Prop_None, "Transition mode");
    ADD_PROPERTY_TYPE(Transformation, (long(0)), "Sweep", App::Prop_None, "Section transformation mode");
    Mode.setEnums(ModeEnums);
    Transition.setEnums(TransitionEnums);
    Transformation.setEnums(TransformEnums);
}

short Pipe::mustExecute() const
{
    if (Sections.isTouched()) {
        return 1;
    }
    if (Spine.isTouched()) {
        return 1;
    }
    if (Mode.isTouched()) {
        return 1;
    }
    if (Transition.isTouched()) {
        return 1;
    }
    return ProfileBased::mustExecute();
}

App::DocumentObjectExecReturn* Pipe::execute()
{
    if (onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    auto getSectionShape = [](const char* name,
                              App::DocumentObject* feature,
                              const std::vector<std::string>& subs) -> Part::TopoShape {
        if (!feature || !feature->isDerivedFrom<Part::Feature>()) {
            throw Base::TypeError("Pipe: Invalid profile/section");
        }

        auto subName = subs.empty() ? "" : subs.front();

        // An element that no longer exists ("?Vertex1"): a sketch's would fail the vertex test
        // below and give the whole sketch; a feature's would fail without naming it (ops#71)
        if (auto missing = missingElements(feature, {subName}, true); !missing.empty()) {
            FC_THROWM(Part::NullShapeException, "Missing element in " << name << ": " << missing);
        }

        // only take the entire shape when we have a sketch selected, but
        // not a point of the sketch
        if (feature->isDerivedFrom<Part::Part2DObject>() && subName.compare(0, 6, "Vertex") != 0) {
            return static_cast<Part::Part2DObject*>(feature)->Shape.getShape();
        }
        else {
            if (subName.empty()) {
                throw Base::ValueError("Pipe: No valid subelement linked in Part::Feature");
            }
            return static_cast<Part::Feature*>(feature)->Shape.getShape().getSubTopoShape(
                subName.c_str()
            );
        }
    };


    std::vector<std::vector<Part::TopoShape>> wiresections;

    auto addWiresToWireSections = [](TopoShape& section,
                                     std::vector<std::vector<TopoShape>>& wiresections) -> size_t {
        std::vector<Part::TopoShape> subs = section.getSubTopoShapes(TopAbs_WIRE);
        bool initialWireSectionsEmpty = wiresections.empty();
        size_t i = 0;
        for (const auto& sub : subs) {
            if (i >= wiresections.size()) {
                if (initialWireSectionsEmpty) {
                    wiresections.emplace_back(1, sub);
                }
                else {
                    throw Base::ValueError(
                        "Pipe: Sections need to have the same amount of inner wires (except "
                        "profile and last section, which can be points)"
                    );
                }
            }
            else {
                wiresections[i].push_back(sub);
            }
            ++i;
        }
        return i;
    };

    // TODO: currently we can only allow planar faces, so add that check.
    // The reason for this is that with other faces in front, we could not use the
    // current simulate approach and build the start and end face from the wires.
    // As the shell begins always at the spine and not the profile, the sketchshape
    // cannot be used directly as front face. We would need a method to translate
    // the front shape to match the shell starting position somehow...
    std::vector<TopoShape> wires;
    Part::TopoShape profilePoint = makeTopoShape(false);

    // if the Base property has a valid shape, fuse the pipe into it
    Part::TopoShape base = makeTopoShape();
    try {
        base = getBaseTopoShape();
    }
    catch (const Base::Exception&) {
    }

    auto hasher = getDocument()->getStringHasher();

    try {
        // setup the location
        this->positionByPrevious();
        TopLoc_Location invObjLoc = getInverseLocation(base);
        if (!base.isNull()) {
            base.move(invObjLoc);
        }

        // setup the profile section
        Part::TopoShape profileShape
            = getSectionShape("Profile", Profile.getValue(), Profile.getSubValues());
        if (profileShape.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Pipe: Could not obtain profile shape")
            );
        }

        // build the paths
        App::DocumentObject* spine = Spine.getValue();
        if (!(spine && spine->isDerivedFrom<Part::Feature>())) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP("Exception", "No spine linked"));
        }

        std::vector<std::string> subedge = Spine.getSubValues();
        if (auto missing = missingElements(spine, subedge); !missing.empty()) {
            return new App::DocumentObjectExecReturn("Missing element in Spine: " + missing);
        }
        Part::TopoShape path = makeTopoShape(false);
        const Part::TopoShape& shape = static_cast<Part::Feature*>(spine)->Shape.getShape();
        buildPipePath(shape, subedge, path);
        path.move(invObjLoc);

        // auxiliary
        Part::TopoShape auxpath = makeTopoShape(false);
        if (Mode.getValue() == 3) {
            App::DocumentObject* auxspine = AuxiliarySpine.getValue();
            if (!(auxspine && auxspine->isDerivedFrom<Part::Feature>())) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "No auxiliary spine linked.")
                );
            }
            std::vector<std::string> auxsubedge = AuxiliarySpine.getSubValues();
            if (auto missing = missingElements(auxspine, auxsubedge); !missing.empty()) {
                return new App::DocumentObjectExecReturn(
                    "Missing element in AuxiliarySpine: " + missing
                );
            }

            const Part::TopoShape& auxshape = static_cast<Part::Feature*>(auxspine)->Shape.getValue();
            buildPipePath(auxshape, auxsubedge, auxpath);
            auxpath.move(invObjLoc);
        }

        // build up multisections
        auto multisections = Sections.getSubListValues();
        std::vector<std::vector<TopoShape>> wiresections;

        size_t numWires = addWiresToWireSections(profileShape, wiresections);
        if (numWires == 0) {
            // profileShape had no wires so only other valid option is single point section
            size_t i = 0;
            for (auto& vertex : profileShape.getSubTopoShapes(TopAbs_VERTEX)) {
                profilePoint = vertex;
            }
            if (i > 1) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Pipe: Only one isolated point is needed if using a sketch with isolated "
                    "points for section"
                ));
            }
        }

        if (!profilePoint.isNull() && (Transformation.getValue() != 1 || multisections.empty())) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Pipe: At least one section is needed when using a single point for profile"
            ));
        }

        // maybe we need a scaling law
        Handle(Law_Function) scalinglaw;

        bool isLastSectionVertex = false;

        // see if we shall use multiple sections
        if (Transformation.getValue() == 1) {
            // TODO: we need to order the sections to prevent occ from crashing,
            // as makepipeshell connects the sections in the order of adding
            for (auto& subSet : multisections) {
                if (!subSet.first->isDerivedFrom<Part::Feature>()) {
                    return new App::DocumentObjectExecReturn(
                        QT_TRANSLATE_NOOP("Exception", "Pipe: All sections need to be Part features")
                    );
                }

                // if the section is an object's face then take just the face
                Part::TopoShape shape = getSectionShape("Section", subSet.first, subSet.second);
                if (shape.isNull()) {
                    return new App::DocumentObjectExecReturn(
                        QT_TRANSLATE_NOOP("Exception", "Pipe: Could not obtain section shape")
                    );
                }

                size_t nWiresAdded = addWiresToWireSections(shape, wiresections);
                if (nWiresAdded == 0) {
                    for (auto& vertex : shape.getSubTopoShapes(TopAbs_VERTEX)) {
                        if (isLastSectionVertex) {
                            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                                "Exception",
                                "Pipe: Only the profile and last section can be vertices"
                            ));
                        }
                        isLastSectionVertex = true;
                        for (auto& wires : wiresections) {
                            wires.push_back(vertex);
                        }
                    }
                }

                if (!isLastSectionVertex && nWiresAdded < wiresections.size()) {
                    return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Multisections need to have the same amount of inner wires as the base "
                        "section"
                    ));
                }
            }
        }
        /*//build the law functions instead
        else if (Transformation.getValue() == 2) {
            if (ScalingData.getValues().size()<1)
                return new App::DocumentObjectExecReturn("No valid data given for linear scaling
        mode");

            Handle(Law_Linear) lin = new Law_Linear();
            lin->Set(0, 1, 1, ScalingData[0].x);

            scalinglaw = lin;
        }
        else if (Transformation.getValue() == 3) {
            if (ScalingData.getValues().size()<1)
                return new App::DocumentObjectExecReturn("No valid data given for S-shape scaling
        mode");

            Handle(Law_S) s = new Law_S();
            s->Set(0, 1, ScalingData[0].y, 1, ScalingData[0].x, ScalingData[0].z);

            scalinglaw = s;
        }*/

        // Verify that path is not a null shape
        if (path.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Path must not be a null shape")
            );
        }

        // "Transformed" with one profile, in a mode that turns it along the spine: the tilt at the
        // corners chooses between the one sweep, the union of pieces and an error (ops#370).
        // Fixed mode never turns the profile; it, Auxiliary and Multisection meet the result
        // gate only.
        const int mode = Mode.getValue();
        const bool sheared = Transition.getValue() == 0 && Transformation.getValue() != 1
            && profilePoint.isNull() && (mode == 0 || mode == 2 || mode == 4);
        auto setup = [&](BRepOffsetAPI_MakePipeShell& pipe) {
            setupAlgorithm(pipe, auxpath.getShape());
        };
        auto inPlace = [&](const gp_Pnt& point) {
            return pointText(point.Transformed(invObjLoc.Inverted().Transformation()));
        };
        const std::optional<gp_Pnt> sharpest = sharpestCorner(TopoDS::Wire(path.getShape()));
        auto invalidPipe = [&]() {
            return whyInvalid(
                mode,
                Transition.getValue(),
                Transformation.getValue() == 1,
                sharpest ? std::optional<std::string>(inPlace(*sharpest)) : std::nullopt
            );
        };
        CornerTilts tilts;
        std::vector<TopoDS_Shape> sweptStarts;

        // build all shells
        std::vector<Part::TopoShape> shells;

        Part::TopoShape copyProfilePoint(profilePoint);
        if (!profilePoint.isNull()) {
            copyProfilePoint.move(invObjLoc);
        }

        std::vector<Part::TopoShape> frontwires, backwires;
        for (auto& wires : wiresections) {
            BRepOffsetAPI_MakePipeShell mkPS(TopoDS::Wire(path.getShape()));
            setupAlgorithm(mkPS, auxpath.getShape());

            if (!scalinglaw) {
                if (!profilePoint.isNull()) {
                    mkPS.Add(copyProfilePoint.getShape());
                }

                for (auto& wire : wires) {
                    wire.move(invObjLoc);
                    mkPS.Add(wire.getShape());
                }
            }
            else {
                if (!profilePoint.isNull()) {
                    mkPS.SetLaw(copyProfilePoint.getShape(), scalinglaw);
                }

                for (auto& wire : wires) {
                    wire.move(invObjLoc);
                    mkPS.SetLaw(wire.getShape(), scalinglaw);
                }
            }

            if (!mkPS.IsReady()) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Pipe could not be built")
                );
            }

            // The profile's point, when it is one, names the shell's start vertex
            std::vector<Part::TopoShape> sections;
            if (!profilePoint.isNull()) {
                sections.push_back(copyProfilePoint);
            }
            sections.insert(sections.end(), wires.begin(), wires.end());
            Part::TopoShape shell = makeTopoShape();
            // Shape() builds the pipe, which the mapper's FirstShape() and LastShape() need
            const TopoDS_Shape built = mkPS.Shape();
            shell.makeShapeWithElementMap(
                built,
                MapperPipeShellEnds(
                    mkPS,
                    sections.front().getShape(),
                    sections.back().getShape(),
                    copyProfilePoint.getShape()
                ),
                sections,
                Part::OpCodes::PipeShell
            );
            shells.push_back(shell);

            if (sheared) {
                TopTools_ListOfShape simulated;
                mkPS.Simulate(2, simulated);
                sweptStarts.push_back(simulated.First());
                if (shells.size() == 1) {
                    tilts = measureCorners(mkPS, TopoDS::Wire(path.getShape()), setup);
                    if (const auto& corner = tilts.collapsed) {
                        return new App::DocumentObjectExecReturn(fmt::format(
                            "Pipe: 'Transformed' leaves the stretch after the spine's corner at "
                            "{} no thickness: the profile meets it edge-on ({:.4f} degrees). "
                            "Use 'Right corner' or 'Round corner', or change the corner.",
                            inPlace(corner->at),
                            tiltDegrees(*corner)
                        ));
                    }
                    if (const auto& at = tilts.foldedArc) {
                        const std::string text = fmt::format(
                            "Pipe: 'Transformed' folds the profile over itself along the arc "
                            "from {}: the arc's axis passes through the profile, as the corners "
                            "before it tilt it. Use 'Right corner' or 'Round corner', or a "
                            "larger radius.",
                            inPlace(*at)
                        );
                        return new App::DocumentObjectExecReturn(text);
                    }
                    for (const Corner& corner : tilts.nearCollapse) {
                        const std::string text = fmt::format(
                            "Pipe: the stretch after the corner at {} is nearly edge-on to the "
                            "profile ({:.3f} degrees, {:.2g} % of its thickness). A small "
                            "change makes it fail.",
                            inPlace(corner.at),
                            tiltDegrees(corner),
                            std::abs(corner.cosine) * 100
                        );
                        if (auto doc = getDocument()) {
                            const char* previous = doc->getWarningDescription(this);
                            doc->setWarning(
                                this,
                                previous && *previous ? std::string(previous) + "\n" + text : text
                            );
                        }
                    }
                }
            }

            if (!shell.isClosed()) {
                // shell is not closed - use simulate to get the end wires
                TopTools_ListOfShape sim;
                mkPS.Simulate(2, sim);

                if (wires.front().shapeType() != TopAbs_VERTEX) {
                    TopoShape front = makeTopoShape(sim.First());
                    if (front.countSubShapes(TopAbs_EDGE)
                        == wires.front().countSubShapes(TopAbs_EDGE)) {
                        front = wires.front();
                        front.setShape(sim.First(), false);
                    }
                    else {
                        front.Tag = -wires.front().Tag;
                    }
                    frontwires.push_back(front);
                }

                if (wires.back().shapeType() != TopAbs_VERTEX) {
                    TopoShape back = makeTopoShape(sim.Last());
                    if (back.countSubShapes(TopAbs_EDGE) == wires.back().countSubShapes(TopAbs_EDGE)) {
                        back = wires.back();
                        back.setShape(sim.Last(), false);
                    }
                    else {
                        back.Tag = -wires.back().Tag;
                    }
                    backwires.push_back(back);
                }
            }
        }

        Part::TopoShape result = makeTopoShape();

        if (!tilts.pieceStarts.empty()) {
            // Past 90 degrees: the union. The first piece starts from the profile where it lies
            // at the spine's start, or else from the one sweep's start section with its names.
            std::vector<Part::TopoShape> profiles;
            for (size_t i = 0; i < wiresections.size(); ++i) {
                Part::TopoShape profile = wiresections[i].front();
                if (!samePlace(profile.getShape(), sweptStarts[i])) {
                    if (makeTopoShape(sweptStarts[i]).countSubShapes(TopAbs_EDGE)
                        == profile.countSubShapes(TopAbs_EDGE)) {
                        profile.setShape(sweptStarts[i], false);
                    }
                    else {
                        profile = makeTopoShape(sweptStarts[i]);
                    }
                }
                profiles.push_back(profile);
            }
            result = sweepPiecesAndFuse(
                TopoDS::Wire(path.getShape()),
                tilts.pieceStarts,
                profiles,
                setup,
                [this](const TopoDS_Shape& shape) { return makeTopoShape(shape); }
            );
            if (result.isNull()) {
                return new App::DocumentObjectExecReturn(invalidPipe());
            }
        }
        else if (!frontwires.empty() || !backwires.empty()) {
            BRepBuilderAPI_Sewing sewer;
            sewer.SetTolerance(Precision::Confusion());
            for (auto& s : shells) {
                sewer.Add(s.getShape());
            }

            Part::TopoShape frontface, backface;
            gp_Pln pln;

            if (!frontwires.empty() && frontwires.front().hasSubShape(TopAbs_EDGE)) {
                if (!TopoShape(-1).makeElementCompound(frontwires).findPlane(pln)) {
                    try {
                        frontface.makeElementBSplineFace(frontwires);
                    }
                    catch (Base::Exception&) {
                        frontface.makeElementFilledFace(
                            frontwires,
                            Part::TopoShape::BRepFillingParams()
                        );
                    }
                }
                else {
                    frontface.makeElementFace(frontwires);
                }
                sewer.Add(frontface.getShape());
            }

            if (!backwires.empty() && backwires.front().hasSubShape(TopAbs_EDGE)) {
                // Explicitly set op code when making face to generate different
                // topo name than the front face.
                if (!Part::TopoShape(-1).makeElementCompound(backwires).findPlane(pln)) {
                    try {
                        backface.makeElementBSplineFace(
                            backwires,
                            Part::FillingStyle::stretch,
                            false,
                            Part::OpCodes::Sewing
                        );
                    }
                    catch (Base::Exception&) {
                        backface.makeElementFilledFace(
                            backwires,
                            TopoShape::BRepFillingParams(),
                            Part::OpCodes::Sewing
                        );
                    }
                }
                else {
                    backface.makeElementFace(backwires, Part::OpCodes::Sewing);
                }
                sewer.Add(backface.getShape());
            }

            sewer.Perform();
            result = result
                         .makeShapeWithElementMap(
                             sewer.SewedShape(),
                             Part::MapperSewing(sewer),
                             shells,
                             Part::OpCodes::Sewing
                         )
                         .makeElementSolid();
        }
        else {
            // shells are already closed - add them directly
            Part::TopoShape partCompound = makeTopoShape();
            partCompound.makeElementCompound(shells);

            result.makeElementSolid(partCompound);
        }

        if (!result.countSubShapes(TopAbs_SHELL)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Loft: Failed to create shell")  // isn't the prefix
                                                                                // supposed to be "Pipe:"
            );
        }

        auto shapes = result.getSubTopoShapes(TopAbs_SHELL);
        for (auto& s : shapes) {
            // build the solid
            s = s.makeElementSolid();
            BRepClass3d_SolidClassifier SC(s.getShape());
            SC.PerformInfinitePoint(Precision::Confusion());
            if (SC.State() == TopAbs_IN) {
                s.setShape(s.getShape().Reversed(), false);
            }
        }

        // Every pipe is a valid solid with a positive volume, whatever its transition (ops#381):
        // "Right corner" and "Round corner" gave no solid, or an invalid one, at the corners of
        // a pipe with several sections and at hairpins, and "Transformed" an invalid one where
        // a tight curve follows a corner of nearly 90 degrees; a multisection pipe on macOS an
        // inside-out one (ops#396). A self-intersection that only the boolean check finds
        // passes, but after a corner that tilts the profile onto a curve (other than an arc,
        // which measureCorners tests exactly): that check takes up to a second on a helix
        // sweep, and reports valid ones (C0 continuity).
        for (const auto& s : shapes) {
            if (!isValidSolid(s)) {
                return new App::DocumentObjectExecReturn(invalidPipe());
            }
        }
        if (tilts.tiltedCurve && !selfIntersectionFree(shapes)) {
            const std::string text = fmt::format(
                "Pipe: the result crosses itself: 'Transformed' folds the profile over itself "
                "along a curve that a corner tilted it onto (the sharpest is at {}). Use 'Right "
                "corner' or 'Round corner', or a gentler curve.",
                sharpest ? inPlace(*sharpest) : std::string("the start")
            );
            return new App::DocumentObjectExecReturn(text);
        }

        // A closed spine sweeps a closed shell for each wire of a holed profile, and a closed
        // spine's union keeps one for each hole too: a shell inside another is a void cut from
        // it, not a solid fused back in, which filled the hole (ops#370); one inside that again
        // is a solid
        std::vector<int> depths(shapes.size(), 0);
        for (size_t i = 0; i < shapes.size(); ++i) {
            TopExp_Explorer vertex(shapes[i].getShape(), TopAbs_VERTEX);
            if (!vertex.More()) {
                continue;
            }
            const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(vertex.Current()));
            for (size_t j = 0; j < shapes.size(); ++j) {
                BRepClass3d_SolidClassifier inside;
                if (j != i) {
                    inside.Load(shapes[j].getShape());
                    inside.Perform(point, Precision::Confusion());
                    depths[i] += inside.State() == TopAbs_IN ? 1 : 0;
                }
            }
        }
        const int deepest = shapes.empty() ? 0 : *std::max_element(depths.begin(), depths.end());
        if (deepest == 0) {
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
        }
        else {
            auto atDepth = [&](int depth) {
                std::vector<Part::TopoShape> found;
                for (size_t i = 0; i < shapes.size(); ++i) {
                    if (depths[i] == depth) {
                        found.push_back(shapes[i]);
                    }
                }
                return found;
            };
            std::vector<Part::TopoShape> outer = atDepth(0);
            if (outer.size() > 1) {
                result.makeElementFuse(outer);
            }
            else {
                result = outer.front();
            }
            for (int depth = 1; depth <= deepest; ++depth) {
                std::vector<Part::TopoShape> level = atDepth(depth);
                if (level.empty()) {
                    continue;
                }
                level.insert(level.begin(), result);
                Part::TopoShape next = makeTopoShape();
                if (depth % 2) {
                    next.makeElementCut(level);
                }
                else {
                    next.makeElementFuse(level);
                }
                result = next;
            }
            if (!isValidSolid(result)) {
                return new App::DocumentObjectExecReturn(invalidPipe());
            }
            AddSubShape.setValue(result);
        }

        // A loose pipe may be a poor approximation of the swept surface, which OCCT reports only
        // through tolerances (ops#448)
        const std::string loose
            = Part::PipeShellApproximation::looseWarning(result.getShape(), "pipe");
        auto warnIfLoose = [&]() {
            auto doc = getDocument();
            if (doc && !loose.empty()) {
                const char* previous = doc->getWarningDescription(this);
                doc->setWarning(
                    this,
                    previous && *previous ? std::string(previous) + "\n" + loose : loose
                );
            }
        };

        if (base.isNull()) {
            if (getAddSubType() == FeatureAddSub::Type::Subtractive) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Pipe: There is nothing to subtract from")
                );
            }

            if (!isSingleSolidRuleSatisfied(result.getShape())) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Result has multiple solids: enable 'Allow Compound' in the active body."
                ));
            }

            // store shape before refinement
            this->rawShape = result;

            result = refineShapeIfActive(result);
            // Refine can leave an invalid solid of a valid one ('Fixed' mode past 90 degrees)
            if (!isValidSolid(result)) {
                return new App::DocumentObjectExecReturn(invalidPipe());
            }
            Shape.setValue(getSolid(result));
            warnIfLoose();
            return App::DocumentObject::StdReturn;
        }

        Part::TopoShape boolOp = makeResultShape(base);

        result.Tag = -getID();  // invert tag to differentiate the pre-boolean pipe
        //                        from the post-boolean pipe
        //                        setting result to the negative tag is a bit confusing,
        //                        because you would expect this to be set to the feature's shape,
        //                        but boolOp is the topoShape that is actually being copied

        boolOp.makeElementBoolean(
            getBooleanMaker(),
            {base, result},
            nullptr,
            FuzzyTolerance.getValue(),
            Part::ElementMapPolicy::Propagate,
            booleanInputCheck(),
            &booleanInputsValid
        );

        if (!isSingleSolidRuleSatisfied(boolOp.getShape())) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Result has multiple solids: enable 'Allow Compound' in the active body."
            ));
        }

        TopoShape solid = getSolid(boolOp);
        // lets check if the result is a solid
        if (solid.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is not a solid")
            );
        }

        // store shape before refinement
        this->rawShape = solid;
        solid = refineShapeIfActive(solid);
        if (!isSingleSolidRuleSatisfied(solid.getShape())) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Result has multiple solids: enable 'Allow Compound' in the active body."
            ));
        }

        // As above, after the boolean too, unless the base was invalid already
        if (!isValidSolid(solid) && BRepCheck_Analyzer(base.getShape()).IsValid()) {
            return new App::DocumentObjectExecReturn(invalidPipe());
        }
        Shape.setValue(solid);
        warnIfLoose();
        return App::DocumentObject::StdReturn;
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
    catch (const Base::Exception& e) {  // e.g. a missing element (ops#71)
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (...) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "A fatal error occurred when making the pipe")
        );
    }
}

void Pipe::setupAlgorithm(BRepOffsetAPI_MakePipeShell& mkPipeShell, const TopoDS_Shape& auxshape)
{

    mkPipeShell.SetTolerance(Precision::Confusion());
    // As Part::Sweep (ops#448): at OCCT's default caps, Standard mode swept a circle along ten
    // planar waves sketched on a plane turned 45 degrees about X 1.9e-2 mm off the tube
    Part::PipeShellApproximation::set(mkPipeShell);

    switch (Transition.getValue()) {
        case 0:
            mkPipeShell.SetTransitionMode(BRepBuilderAPI_Transformed);
            break;
        case 1:
            mkPipeShell.SetTransitionMode(BRepBuilderAPI_RightCorner);
            break;
        case 2:
            mkPipeShell.SetTransitionMode(BRepBuilderAPI_RoundCorner);
            break;
    }

    bool auxiliary = false;
    const Base::Vector3d& bVec = Binormal.getValue();
    switch (Mode.getValue()) {
        case 1:
            mkPipeShell.SetMode(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1), gp_Dir(1, 0, 0)));
            break;
        case 2:
            mkPipeShell.SetMode(true);
            break;
        case 3:
            auxiliary = true;
            break;
        case 4:
            mkPipeShell.SetMode(gp_Dir(bVec.x, bVec.y, bVec.z));
            break;
    }

    if (auxiliary) {
        mkPipeShell.SetMode(TopoDS::Wire(auxshape), AuxiliaryCurvilinear.getValue());
        // mkPipeShell.SetMode(TopoDS::Wire(auxshape), AuxiliaryCurvilinear.getValue(),
        // BRepFill_ContactOnBorder);
    }
}


void Pipe::getContinuousEdges(Part::TopoShape /*TopShape*/, std::vector<std::string>& /*SubNames*/)
{
    /*
    TopTools_IndexedMapOfShape mapOfEdges;
    TopTools_IndexedDataMapOfShapeListOfShape mapEdgeEdge;
    TopExp::MapShapesAndAncestors(TopShape.getShape(), TopAbs_EDGE, TopAbs_EDGE, mapEdgeEdge);
    TopExp::MapShapes(TopShape.getShape(), TopAbs_EDGE, mapOfEdges);

    Base::Console().message("Initial edges:\n");
    for (int i=0; i<SubNames.size(); ++i)
        Base::Console().message("Subname: %s\n", SubNames[i].c_str());

    unsigned int i = 0;
    while(i < SubNames.size())
    {
        std::string aSubName = static_cast<std::string>(SubNames.at(i));

        if (aSubName.compare(0, 4, "Edge") == 0) {
            TopoDS_Edge edge = TopoDS::Edge(TopShape.getSubShape(aSubName.c_str()));
            const TopTools_ListOfShape& los = mapEdgeEdge.FindFromKey(edge);

            if (los.Extent() != 2)
            {
                SubNames.erase(SubNames.begin()+i);
                continue;
            }

            const TopoDS_Shape& face1 = los.First();
            const TopoDS_Shape& face2 = los.Last();
            GeomAbs_Shape cont = BRep_Tool::Continuity(TopoDS::Edge(edge),
                                                       TopoDS::Face(face1),
                                                       TopoDS::Face(face2));
            if (cont != GeomAbs_C0) {
                SubNames.erase(SubNames.begin()+i);
                continue;
            }

            i++;
        }
        // empty name or any other sub-element
        else {
            SubNames.erase(SubNames.begin()+i);
        }
    }

    Base::Console().message("Final edges:\n");
    for (int i=0; i<SubNames.size(); ++i)
        Base::Console().message("Subname: %s\n", SubNames[i].c_str());
    */
}

void Pipe::buildPipePath(
    const Part::TopoShape& shape,
    const std::vector<std::string>& subedge,
    Part::TopoShape& path
)
{
    if (!shape.isNull()) {
        try {
            if (!subedge.empty()) {
                // if (SpineTangent.getValue())
                // getContinuousEdges(shape, subedge);

                std::vector<Part::TopoShape> shapes;
                for (const auto& it : subedge) {
                    shapes.push_back(shape.getSubTopoShape(it.c_str()));
                }
                path = path.makeElementWires(shapes);
            }
            else if (shape.shapeType() == TopAbs_EDGE) {
                path = shape.getShape();
            }
            else if (shape.shapeType() == TopAbs_WIRE) {
                path = path.makeElementWires(shape);
            }
            else if (shape.shapeType() == TopAbs_COMPOUND) {
                TopoDS_Iterator it(shape.getShape());
                for (; it.More(); it.Next()) {
                    if (it.Value().IsNull()) {
                        throw Base::ValueError(
                            QT_TRANSLATE_NOOP("Exception", "Invalid element in spine.")
                        );
                    }
                    if ((it.Value().ShapeType() != TopAbs_EDGE)
                        && (it.Value().ShapeType() != TopAbs_WIRE)) {
                        throw Base::TypeError(QT_TRANSLATE_NOOP(
                            "Exception",
                            "Element in spine is neither an edge nor a wire."
                        ));
                    }
                }

                std::vector<Part::TopoShape> edges = shape.getSubTopoShapes(TopAbs_EDGE);

                path = path.makeElementWires(edges);
            }
            else {
                throw Base::TypeError(
                    QT_TRANSLATE_NOOP("Exception", "Spine is neither an edge nor a wire.")
                );
            }
        }
        catch (Standard_Failure&) {
            throw Base::CADKernelError(QT_TRANSLATE_NOOP("Exception", "Invalid spine."));
        }
    }
}
PROPERTY_SOURCE(PartDesign::AdditivePipe, PartDesign::Pipe)
AdditivePipe::AdditivePipe()
{
    defineAdditive();
}

PROPERTY_SOURCE(PartDesign::SubtractivePipe, PartDesign::Pipe)
SubtractivePipe::SubtractivePipe()
{
    defineSubtractive();
}

void Pipe::handleChangedPropertyType(Base::XMLReader& reader, const char* TypeName, App::Property* prop)
{
    // property Sections had the App::PropertyLinkList and was changed to App::PropertyXLinkSubList
    if (prop == &Sections && strcmp(TypeName, "App::PropertyLinkList") == 0) {
        Sections.upgrade(reader, TypeName);
    }
    else {
        ProfileBased::handleChangedPropertyType(reader, TypeName, prop);
    }
}

void Pipe::handleChangedPropertyName(Base::XMLReader& reader, const char* TypeName, const char* PropName)
{
    // The AuxiliarySpine property was AuxillerySpine in the past
    std::string strAuxillerySpine("AuxillerySpine");
    // The AuxiliarySpineTangent property was AuxillerySpineTangent in the past
    std::string strAuxillerySpineTangent("AuxillerySpineTangent");
    // The AuxiliaryCurvilinear property was AuxilleryCurvelinear in the past
    std::string strAuxilleryCurvelinear("AuxilleryCurvelinear");
    Base::Type type = Base::Type::fromName(TypeName);
    if (AuxiliarySpine.getClassTypeId() == type && strAuxillerySpine == PropName) {
        AuxiliarySpine.Restore(reader);
    }
    else if (AuxiliarySpineTangent.getClassTypeId() == type && strAuxillerySpineTangent == PropName) {
        AuxiliarySpineTangent.Restore(reader);
    }
    else if (AuxiliaryCurvilinear.getClassTypeId() == type && strAuxilleryCurvelinear == PropName) {
        AuxiliaryCurvilinear.Restore(reader);
    }
    else {
        ProfileBased::handleChangedPropertyName(reader, TypeName, PropName);
    }
}
