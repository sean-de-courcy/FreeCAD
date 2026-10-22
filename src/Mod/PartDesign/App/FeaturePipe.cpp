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
#include <cmath>
#include <functional>
#include <limits>
#include <numbers>
#include <optional>
#include <queue>

#include <fmt/format.h>

#include <Mod/Part/App/FCBRepAlgoAPI_Cut.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <BRepAdaptor_Curve.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepLProp_CLProps.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepGProp_Face.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Tool.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_Curve.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <GeomAdaptor_Curve.hxx>
#include <GeomFill_Frenet.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <gp.hxx>
#include <GProp_GProps.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Quaternion.hxx>
#include <gp_Trsf.hxx>
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
// may swap roles: the Pipe decides once which end carries the profile's names, and the mapper
// takes that decision (ops#379, Pipe::SpineEnds). A pipe that has recomputed before keeps the
// end it chose then; the first time, the sections decide (endsSwapped):
// - One profile: the ends swap when the profile lies nearer the spine's far end (a spine drawn
//   towards it), so the names go to the end at or nearest the profile's place.
// - Several sections: the first and last decide together, by the pairing of sections and ends
//   whose distances add up to less, each section's distance the mean over its vertices (so a
//   section weighs the same whatever its number of vertices); the ends follow the sections'
//   order along the spine.
// A tie (a closed spine) keeps the start.
// Each end element is found through the side face or edge its section element generated. A
// point section names only its end's vertex. Edges at a bend, a corner or a middle section have
// no section element of their own: they keep their `UPP` names.
class MapperPipeShellEnds: public Part::MapperMaker
{
public:
    /// \a first and \a last are the first and last sections added to \a pipe, a wire or a
    /// vertex each (the same for a pipe of one profile); \a point is \a first when it is the
    /// profile's point, which the side shapes' history leaves out (it isn't otherwise a source).
    /// \a reversed: the shell's end, not its start, carries \a first's names (ops#379).
    MapperPipeShellEnds(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& first,
        const TopoDS_Shape& last,
        const TopoDS_Shape& point,
        bool reversed
    )
        : MapperMaker(pipe)
        , point(point)
    {
        TopTools_IndexedMapOfShape startElements;
        TopTools_IndexedMapOfShape endElements;
        TopExp::MapShapes(pipe.FirstShape(), startElements);
        TopExp::MapShapes(pipe.LastShape(), endElements);
        const TopTools_IndexedMapOfShape& own = reversed ? endElements : startElements;
        const TopTools_IndexedMapOfShape& other = reversed ? startElements : endElements;
        bindEnds(pipe, first, own, nullptr, starts);
        // With a closed spine the shell ends where it starts: those elements keep the first
        // section's names
        bindEnds(pipe, last, other, &own, bound);
        ends = bound;
    }

    /// How a piece of a union (sweepPiecesAndFuse) names its end
    enum class PieceEnd
    {
        /// Not from its section: a piece before the last
        None,
        /// Projecting the profile's names: the last piece, when the union's start has them
        Projected,
        /// With the profile's own names: the last piece, when the union's end has them
        Own,
    };

    /// A piece of a union, swept from \a section at its start (ops#370). Its start keeps the
    /// section's names, or, with \a startProjects (the first piece, when the union's end carries
    /// the profile's names), projects them (ops#379). Its end is named as \a end says; \a
    /// origins, when given, binds each element of \a section to the profile's element it was
    /// swept from, and the end is named from those instead (a source of the shape too).
    MapperPipeShellEnds(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& section,
        bool startProjects,
        PieceEnd end,
        const TopTools_DataMapOfShapeShape* origins
    )
        : MapperMaker(pipe)
    {
        TopTools_IndexedMapOfShape startElements;
        TopTools_IndexedMapOfShape endElements;
        TopExp::MapShapes(pipe.FirstShape(), startElements);
        TopExp::MapShapes(pipe.LastShape(), endElements);
        TopTools_DataMapOfShapeListOfShape atStart;
        bindEnds(pipe, section, startElements, nullptr, atStart);
        bindEnds(pipe, section, endElements, &startElements, bound);
        (startProjects ? ends : starts) = atStart;
        if (end == PieceEnd::None) {
            return;
        }
        TopTools_DataMapOfShapeListOfShape& named = end == PieceEnd::Own ? starts : ends;
        for (TopTools_DataMapIteratorOfDataMapOfShapeListOfShape it(bound); it.More(); it.Next()) {
            const TopoDS_Shape* origin = origins ? origins->Seek(it.Key()) : &it.Key();
            if (origin) {
                named.Bind(*origin, it.Value());
            }
        }
    }

    /// Whether \a first, the first section added to \a pipe, lies nearer the shell's end than
    /// its start; with several sections, \a last with it, by the pairing of sections and ends
    /// whose distances add up to less
    static bool endsSwapped(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& first,
        const TopoDS_Shape& last
    )
    {
        double kept = distanceTo(first, pipe.FirstShape());
        double swapped = distanceTo(first, pipe.LastShape());
        // One profile: its distances alone (the two sections' terms would be the same on both
        // sides, and nothing would ever swap)
        if (!last.IsSame(first)) {
            kept += distanceTo(last, pipe.LastShape());
            swapped += distanceTo(last, pipe.FirstShape());
        }
        return swapped + Precision::Confusion() < kept;
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

/// A curved edge of the spine along which the section folds back over itself
struct Fold
{
    /// Where the edge starts
    gp_Pnt at;
    /// Whether the edge is an arc
    bool arc;
    /// Whether the section is tilted to it there, by the corners before it or its own slant
    bool tilted;
    /// How far the section reaches past the line where it turns back (mm)
    double reach;
    /// The section's extent across that line (mm)
    double across;
};

/// What "Transformed" does at a spine's corners
struct CornerTilts
{
    /// The edges where the union's pieces after the first start
    std::vector<size_t> pieceStarts;
    /// The first stretch with no thickness
    std::optional<Corner> collapsed;
    /// The stretches within 1 degree of the collapse
    std::vector<Corner> nearCollapse;
    /// The first curve along which the section folds over itself
    std::optional<Fold> folded;
    /// The first curve along which it folds only a little, which passes with a warning
    std::optional<Fold> smallFold;
    /// The first curve with stretches where the section could fold that the budget of places
    /// left unchecked, and how many, which passes with a warning
    std::optional<std::pair<gp_Pnt, int>> unchecked;
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

/// A section of the sweep where a spine's edge starts: its normal, and points along all its wires
struct Section
{
    gp_Dir normal;
    std::vector<gp_Pnt> points;
};

/// Within this angle (radians) the section counts as square to the spine, and a turn of the
/// spine as no corner, when the folds along curves are looked for: a smooth chain of curves
/// doesn't tilt the section, and the sections the sweep reports are that far off square
constexpr double tiltTolerance = 1e-3;

/// How far a section reaches past the line where it turns back, and its extent across that line
/// (mm); both 0 when it doesn't fold
struct Reach
{
    double past = 0;
    double across = 0;
    /// Stretches where the section could fold that weren't looked at closely (refinedMotions)
    int unchecked = 0;
};

/// A fold that reaches back less than this part of the section's extent passes, with a warning: a
/// sliver of about 1e-3 mm^3 for a round profile of radius 2 reaching 0.10 mm past the line along
/// an arc. A larger fold fails. The fold's measure alone decides, so a file gives the same result
/// on every platform and machine: the boolean self-interference check found some small folds and
/// not others, found a 0.10 mm one on macOS that it passed on Windows, and takes many minutes on
/// a long B-spline spine (ops#370).
constexpr double smallFold = 0.05;

/// Where the section could fold along a curve, foldAlongCurve's samples are this close (radians
/// of the section's turn): a bend shorter than their spacing would fall between them (ops#370)
constexpr double sampleTurn = std::numbers::pi / 180;

/// The angle between the section's \a normal and the spine's \a tangent, either way along it
double tiltTo(const gp_Dir& normal, const gp_Dir& tangent)
{
    return std::acos(std::min(1.0, std::abs(normal.Dot(tangent))));
}

/// How far the section (\a normal, \a points) reaches back over itself along the arc \a edge,
/// none when it doesn't fold. It turns about the arc's axis, each point at the speed of its distance
/// from the axis, so its points move through its plane one way on one side of the line where
/// that plane meets the plane through the axis, and the other way beyond: the sweep folds where
/// the section reaches across that line (ops#370). A section in the arc's plane only turns
/// within it: no fold here. Exact where the sweep turns the section about the arc's axis: every
/// mode but Binormal, and Binormal along an arc about the binormal.
Reach foldAlongArc(const TopoDS_Edge& edge, const gp_Dir& normal, const std::vector<gp_Pnt>& points)
{
    const gp_Ax1 axis = BRepAdaptor_Curve(edge).Circle().Axis();
    const gp_Vec across = gp_Vec(normal).Crossed(gp_Vec(axis.Direction()));
    if (across.Magnitude() < gp::Resolution()) {
        return {};
    }
    const gp_Dir side(across);
    double low = std::numeric_limits<double>::infinity();
    double high = -low;
    for (const gp_Pnt& point : points) {
        const double at = gp_Vec(axis.Location(), point).Dot(gp_Vec(side));
        low = std::min(low, at);
        high = std::max(high, at);
    }
    if (low < 0 && high > 0) {
        return {std::min(-low, high), high - low};
    }
    return {};
}

/// The rigid motions that carry a section from the start of \a wire to \a count places along it,
/// both ends included, as a sweep set up by \a setup moves it. A triangle in the plane of \a frame,
/// with a corner at its origin on the wire's first vertex, is swept in the section's place and
/// found again in each place. None when OCCT can't sweep it.
std::optional<std::vector<gp_Trsf>> motionsAlong(
    const TopoDS_Wire& wire,
    const gp_Ax2& frame,
    int count,
    const std::function<void(BRepOffsetAPI_MakePipeShell&)>& setup
)
{
    // Its sides 10, 20 and 22.4 (mm): a scalene triangle, so its corners are told apart
    constexpr double size = 10;
    const gp_Pnt a = frame.Location();
    const gp_Pnt b = a.Translated(gp_Vec(frame.XDirection()) * size);
    const gp_Pnt c = a.Translated(gp_Vec(frame.YDirection()) * 2 * size);
    const gp_Ax3 from(a, frame.Direction(), frame.XDirection());
    std::vector<gp_Trsf> motions;
    try {
        const std::vector<TopoDS_Edge> edges = edgesInOrder(wire);
        if (edges.empty()) {
            return std::nullopt;
        }
        BRepOffsetAPI_MakePipeShell sweep(wire);
        setup(sweep);
        sweep.Add(
            BRepBuilderAPI_MakePolygon(a, b, c, true).Wire(),
            TopExp::FirstVertex(edges.front(), true)
        );
        if (!sweep.IsReady()) {
            return std::nullopt;
        }
        TopTools_ListOfShape placed;
        sweep.Simulate(count, placed);
        for (const TopoDS_Shape& triangle : placed) {
            TopTools_IndexedMapOfShape vertices;
            TopExp::MapShapes(triangle, TopAbs_VERTEX, vertices);
            if (vertices.Extent() != 3) {
                return std::nullopt;
            }
            std::array<gp_Pnt, 3> at;
            for (int i = 0; i < 3; ++i) {
                at[i] = BRep_Tool::Pnt(TopoDS::Vertex(vertices(i + 1)));
            }
            // a lies across from the longest side, b nearer to it than c
            int across = 0;
            for (int i = 1; i < 3; ++i) {
                if (at[(i + 1) % 3].Distance(at[(i + 2) % 3])
                    > at[(across + 1) % 3].Distance(at[(across + 2) % 3])) {
                    across = i;
                }
            }
            const gp_Pnt& there = at[across];
            gp_Pnt nearer = at[(across + 1) % 3];
            gp_Pnt further = at[(across + 2) % 3];
            if (there.Distance(nearer) > there.Distance(further)) {
                std::swap(nearer, further);
            }
            const gp_Vec x(there, nearer);
            const gp_Vec y(there, further);
            gp_Trsf motion;
            motion.SetDisplacement(from, gp_Ax3(there, gp_Dir(x.Crossed(y)), gp_Dir(x)));
            motions.push_back(motion);
        }
    }
    catch (const Standard_Failure&) {
        return std::nullopt;
    }
    if (motions.size() < 2) {
        return std::nullopt;
    }
    return motions;
}

/// The angle (radians) the section turns by from \a here to \a next
double turnBetween(const gp_Trsf& here, const gp_Trsf& next)
{
    gp_Quaternion turn = next.GetRotation() * here.GetRotation().Inverted();
    turn.Normalize();
    return 2 * std::acos(std::min(1.0, std::abs(turn.W())));
}

/// The section's motions along a curve, in runs (refinedMotions)
struct Refined
{
    std::vector<std::vector<gp_Trsf>> runs;
    /// Stretches between two places where the section could fold that were left as sampled:
    /// the budget of places ran out first
    int unchecked = 0;
};

/// The places between two places of the sweep along the curve of \a adaptor (\a here at its
/// parameter \a from, \a next at \a to), \a count steps apart, both included: at each the section
/// lies where the curve does, turned with the sweep frame's axis along the curve from the step
/// before by the least rotation, and twisted about that axis by a part (as far along) of what
/// the sweep's own law adds between the two. The axis is the curve's tangent, or in Binormal mode
/// (\a binormal) the tangent made square to the binormal, as OCCT's frame has it (that frame
/// turns about the binormal only, so the places are exact). Exact for the curve's position and
/// the axis; the sweep's twist is spread evenly over the step (none in Standard mode, in the
/// probes). The first place is \a here and the last \a next. Empty where there is no axis.
std::vector<gp_Trsf> placesBetween(
    const BRepAdaptor_Curve& adaptor,
    bool reversed,
    const std::optional<gp_Dir>& binormal,
    const gp_Pnt& origin,
    const gp_Trsf& here,
    const gp_Trsf& next,
    double from,
    double to,
    int count
)
{
    std::vector<gp_Pnt> at(count + 1);
    std::vector<gp_Vec> tangents(count + 1);
    std::vector<double> along(count + 1, 0);
    for (int k = 0; k <= count; ++k) {
        adaptor.D1(from + (to - from) * k / count, at[k], tangents[k]);
        if (binormal) {
            const gp_Vec across(*binormal);
            tangents[k] -= across * tangents[k].Dot(across);
        }
        if (tangents[k].Magnitude() < gp::Resolution()) {
            return {};
        }
        tangents[k].Normalize();
        if (reversed) {
            tangents[k].Reverse();
        }
        if (k > 0) {
            along[k] = along[k - 1] + at[k].Distance(at[k - 1]);
        }
    }
    // The least rotation from tangent to tangent, then what the sweep's law turns more
    const gp_Quaternion start = here.GetRotation();
    std::vector<gp_Quaternion> turns {start};
    for (int k = 1; k <= count; ++k) {
        turns.push_back(gp_Quaternion(tangents[k - 1], tangents[k]) * turns.back());
    }
    gp_Quaternion rest = next.GetRotation() * turns.back().Inverted();
    rest.Normalize();
    gp_Vec axis;
    double angle = 0;
    rest.GetVectorAndAngle(axis, angle);
    if (angle > std::numbers::pi) {
        angle -= 2 * std::numbers::pi;
    }
    const double twist = axis.Dot(tangents.back()) < 0 ? -angle : angle;

    const gp_Pnt first = origin.Transformed(here);
    gp_Trsf back;
    back.SetTranslation(gp_Vec(first, gp::Origin()));
    std::vector<gp_Trsf> places {here};
    for (int k = 1; k < count; ++k) {
        const double part = along.back() > 0 ? along[k] / along.back() : 0;
        gp_Quaternion turn = gp_Quaternion(tangents[k], twist * part) * turns[k] * start.Inverted();
        turn.Normalize();
        gp_Trsf rotation;
        rotation.SetRotation(turn);
        gp_Trsf there;
        there.SetTranslation(gp_Vec(gp::Origin(), first.Translated(gp_Vec(at[0], at[k]))));
        places.push_back(there * rotation * back * here);
    }
    places.push_back(next);
    return places;
}

/// \a sampled, the motions of the section (\a frame, \a points) to places along the curve \a edge
/// as OCCT's sweep has them, with more places between two of them where the section could fold:
/// there it turns at most sampleTurn from one to the next, and each of the curve's pieces (a
/// B-spline's spans) has two places at least. In every mode measured here the sweep's frame keeps
/// the tangent as an axis (Binormal mode: the tangent's part square to the binormal), so the
/// section's tilt to it stays as it starts, and its speed
/// through its own plane changes across it at the rate it turns: it can fold only where it turns
/// faster than |cos tilt| over its reach from the spine, per mm along the curve. That is judged
/// from how far it turns between the two places and how tightly the curve bends between them,
/// looked at within each piece of the curve: an S-bend that turns back to where it started,
/// shorter than the places' spacing, turns the section by nothing between two of them (ops#370).
/// The places between are computed (placesBetween), not swept: OCCT's sweep of a piece of the
/// curve can turn the section otherwise than its sweep of the whole curve (by 180 degrees across
/// a short S-bend, by none along a straight end that the whole sweep twists by 55 degrees a
/// step). The most fold-prone stretches (where the curve bends fastest beside the turn a fold
/// needs) are subdivided first, and their new places again where needed, until the budget runs
/// out: those left are counted. The result is one run (the places are the sweep's own at the
/// samples, so a fold is measured between any two in a row).
Refined refinedMotions(
    const TopoDS_Edge& edge,
    const gp_Ax2& frame,
    const std::vector<gp_Pnt>& points,
    const std::vector<gp_Trsf>& sampled,
    const std::optional<gp_Dir>& binormal
)
{
    // At most this many places more (each costs some 20 microseconds), and so many between two
    constexpr int budget = 1 << 14;
    constexpr int mostBetween = 1024;
    // Where the curvature is looked at between two of the sweep's places (between two computed
    // ones, a step of at most sampleTurn, fewer), and within each piece of the curve between them
    constexpr int looks = 16;
    constexpr int looksBetweenComputed = 4;
    constexpr int looksInPiece = 4;
    const gp_Pnt origin = frame.Location();
    double reachFromSpine = Precision::Confusion();
    for (const gp_Pnt& point : points) {
        reachFromSpine = std::max(reachFromSpine, point.Distance(origin));
    }
    // A margin of 2 below the turn a fold needs (radians per mm)
    const double foldingRate = 0.5 * std::abs(frame.Direction().Dot(tangentAlong(edge, true)))
        / reachFromSpine;

    double first = 0;
    double last = 0;
    const Handle(Geom_Curve) geometry = BRep_Tool::Curve(edge, first, last);
    if (geometry.IsNull()) {
        return {{sampled}};
    }
    const bool reversed = edge.Orientation() == TopAbs_REVERSED;
    // Where each place lies on the curve
    std::vector<double> at;
    for (size_t i = 0; i < sampled.size(); ++i) {
        if (i == 0 || i + 1 == sampled.size()) {
            at.push_back((i == 0) != reversed ? first : last);
            continue;
        }
        GeomAPI_ProjectPointOnCurve onCurve(origin.Transformed(sampled[i]), geometry, first, last);
        if (onCurve.NbPoints() == 0) {
            return {{sampled}};
        }
        at.push_back(onCurve.LowerDistanceParameter());
    }

    // Where the curve's pieces meet (a B-spline's knots), its ends included
    const BRepAdaptor_Curve adaptor(edge);
    std::vector<double> knots {first};
    if (adaptor.GetType() == GeomAbs_BSplineCurve) {
        const Handle(Geom_BSplineCurve) spline = adaptor.BSpline();
        for (int i = spline->FirstUKnotIndex(); i <= spline->LastUKnotIndex(); ++i) {
            const double knot = spline->Knot(i);
            if (knot > first + Precision::PConfusion() && knot < last - Precision::PConfusion()) {
                knots.push_back(knot);
            }
        }
    }
    knots.push_back(last);
    BRepLProp_CLProps properties(adaptor, 2, Precision::Confusion());
    // How tightly the curve bends between two of its parameters, and its shortest piece there
    auto bending = [&](double from, double to, int times) {
        const double low = std::min(from, to);
        const double high = std::max(from, to);
        double curvature = 0;
        auto look = [&](double parameter) {
            properties.SetParameter(parameter);
            if (properties.IsTangentDefined()) {
                curvature = std::max(curvature, properties.Curvature());
            }
        };
        for (int j = 0; j <= times; ++j) {
            look(low + (high - low) * j / times);
        }
        double shortest = std::numeric_limits<double>::infinity();
        // The piece where low lies, and those after it up to high
        const auto after = std::upper_bound(knots.begin(), knots.end(), low);
        size_t k = after == knots.begin() ? 0 : after - knots.begin() - 1;
        for (; k + 1 < knots.size() && knots[k] < high; ++k) {
            shortest = std::min(shortest, knots[k + 1] - knots[k]);
            const double start = std::max(low, knots[k]);
            const double end = std::min(high, knots[k + 1]);
            for (int j = 0; j <= looksInPiece; ++j) {
                look(start + (end - start) * j / looksInPiece);
            }
        }
        return std::pair {curvature, shortest};
    };

    // The places in runs; a step between two places may be refined by another run, whose first
    // and last places are the step's ends
    struct Run
    {
        std::vector<gp_Trsf> motions;
        std::vector<double> at;
        std::vector<int> finer;
    };
    std::vector<Run> runs {{sampled, at, std::vector<int>(sampled.size() - 1, -1)}};
    // A step to refine: how fold-prone it is (how fast the section turns beside the turn a fold
    // needs), and how many places it needs between its ends
    struct Step
    {
        double proneness;
        int order;
        size_t run;
        size_t index;
        int needed;
    };
    auto later = [](const Step& a, const Step& b) {
        return a.proneness != b.proneness ? a.proneness < b.proneness : a.order > b.order;
    };
    std::priority_queue<Step, std::vector<Step>, decltype(later)> steps(later);
    int order = 0;
    auto examine = [&](size_t r) {
        const Run& run = runs[r];
        for (size_t i = 0; i + 1 < run.motions.size(); ++i) {
            const gp_Trsf& here = run.motions[i];
            const gp_Trsf& next = run.motions[i + 1];
            const double length = origin.Transformed(here).Distance(origin.Transformed(next));
            if (length < 100 * Precision::Confusion()) {
                continue;
            }
            const int count = r == 0 ? looks : looksBetweenComputed;
            const auto [curvature, shortest] = bending(run.at[i], run.at[i + 1], count);
            const double turn = std::max(turnBetween(here, next), curvature * length);
            if (turn <= foldingRate * length) {
                continue;
            }
            const double span = std::abs(run.at[i + 1] - run.at[i]);
            const double needed = std::max(turn / sampleTurn, 2 * span / shortest);
            if (needed > 1) {
                const double proneness = turn / length / foldingRate;
                steps.push({proneness, order++, r, i, static_cast<int>(std::ceil(needed))});
            }
        }
    };
    examine(0);

    Refined refined;
    int added = 0;
    while (!steps.empty()) {
        const Step step = steps.top();
        steps.pop();
        const int count = std::min({mostBetween, step.needed, budget - added});
        if (count < 2) {
            refined.unchecked += 1 + static_cast<int>(steps.size());
            break;
        }
        const Run& run = runs[step.run];
        const double from = run.at[step.index];
        const double to = run.at[step.index + 1];
        std::vector<gp_Trsf> places = placesBetween(
            adaptor,
            reversed,
            binormal,
            origin,
            run.motions[step.index],
            run.motions[step.index + 1],
            from,
            to,
            count
        );
        if (places.empty()) {
            ++refined.unchecked;
            continue;
        }
        std::vector<double> parameters;
        for (int k = 0; k <= count; ++k) {
            parameters.push_back(from + (to - from) * k / count);
        }
        runs[step.run].finer[step.index] = static_cast<int>(runs.size());
        runs.push_back({std::move(places), std::move(parameters), std::vector<int>(count, -1)});
        added += count;
        examine(runs.size() - 1);
    }

    // In order along the curve: a refined step's places in place of the step
    std::vector<gp_Trsf> motions {sampled.front()};
    std::function<void(size_t)> flatten = [&](size_t r) {
        const Run& run = runs[r];
        for (size_t i = 0; i + 1 < run.motions.size(); ++i) {
            if (run.finer[i] < 0) {
                motions.push_back(run.motions[i + 1]);
            }
            else {
                flatten(run.finer[i]);
            }
        }
    };
    flatten(0);
    refined.runs.push_back(std::move(motions));
    return refined;
}

/// The corners of the convex hull of \a points, which lie in the plane of \a frame: an affine
/// function of a point takes its least and greatest values over the points at these (a polygon's
/// sampled sides add none), so foldAlongCurve measures the fold at these only
std::vector<gp_Pnt> hullOf(const std::vector<gp_Pnt>& points, const gp_Ax2& frame)
{
    struct Corner
    {
        double x;
        double y;
        gp_Pnt point;
    };
    std::vector<Corner> corners;
    const gp_Vec alongX(frame.XDirection());
    const gp_Vec alongY(frame.YDirection());
    for (const gp_Pnt& point : points) {
        const gp_Vec from(frame.Location(), point);
        corners.push_back({from.Dot(alongX), from.Dot(alongY), point});
    }
    std::sort(corners.begin(), corners.end(), [](const Corner& a, const Corner& b) {
        return a.x != b.x ? a.x < b.x : a.y < b.y;
    });
    if (corners.size() < 3) {
        return points;
    }
    auto turn = [](const Corner& o, const Corner& a, const Corner& b) {
        return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    };
    // Andrew's monotone chain: the lower side, then the upper
    std::vector<Corner> hull;
    for (int side = 0; side < 2; ++side) {
        const size_t start = hull.size();
        for (size_t i = 0; i < corners.size(); ++i) {
            const Corner& next = side == 0 ? corners[i] : corners[corners.size() - 1 - i];
            // Drop the last corner while it doesn't turn left on the way to next
            auto straight = [&]() {
                return turn(hull[hull.size() - 2], hull.back(), next) <= 0;
            };
            while (hull.size() >= start + 2 && straight()) {
                hull.pop_back();
            }
            hull.push_back(next);
        }
        hull.pop_back();
    }
    std::vector<gp_Pnt> result;
    for (const Corner& corner : hull) {
        result.push_back(corner.point);
    }
    return result.size() < 3 ? points : result;
}

/// How far the section (\a normal, \a points) reaches back over itself along the curve \a edge,
/// as a sweep set up by \a setup moves it, none when it doesn't fold (or OCCT can't sweep it). The
/// arc's test for any curve and mode, from the section's motion sampled along the curve: between
/// two samples each point moves through the section's plane at a speed that changes linearly
/// across it, and where that is forward on one side and backward on the other the sweep folds;
/// the reach is measured from the line where it is zero (ops#370), at the place it is largest.
/// The samples follow the curve's pieces (a long B-spline gets more), and between two of them
/// where the section could fold, they are subdivided until it turns at most sampleTurn between
/// two: a short bend in a B-spline of few pieces fell between them. \a binormal: Binormal mode's.
Reach foldAlongCurve(
    const TopoDS_Edge& edge,
    const gp_Dir& normal,
    const std::vector<gp_Pnt>& points,
    const std::function<void(BRepOffsetAPI_MakePipeShell&)>& setup,
    const std::optional<gp_Dir>& binormal
)
{
    const BRepAdaptor_Curve curve(edge);
    // Each place costs about 1 ms (Simulate builds it)
    const int count = std::clamp(2 * curve.NbIntervals(GeomAbs_C3), 32, 256);
    const gp_Ax2 frame(BRep_Tool::Pnt(TopExp::FirstVertex(edge, true)), normal);
    const std::optional<std::vector<gp_Trsf>> sampled
        = motionsAlong(BRepBuilderAPI_MakeWire(edge).Wire(), frame, count, setup);
    if (!sampled) {
        return {};
    }
    const gp_Pnt origin = frame.Location();
    const std::vector<gp_Pnt> corners = hullOf(points, frame);
    const Refined refined = refinedMotions(edge, frame, corners, *sampled, binormal);
    const gp_Pnt alongX = origin.Translated(gp_Vec(frame.XDirection()));
    const gp_Pnt alongY = origin.Translated(gp_Vec(frame.YDirection()));
    Reach reach;
    reach.unchecked = refined.unchecked;
    for (const std::vector<gp_Trsf>& motions : refined.runs) {
        for (size_t i = 0; i + 1 < motions.size(); ++i) {
            const gp_Trsf& here = motions[i];
            const gp_Trsf& next = motions[i + 1];
            // Simulate can give the last place twice: no motion, only rounding noise
            if (std::max(
                    {origin.Transformed(here).Distance(origin.Transformed(next)),
                     alongX.Transformed(here).Distance(alongX.Transformed(next)),
                     alongY.Transformed(here).Distance(alongY.Transformed(next))}
                )
                < Precision::Confusion()) {
                continue;
            }
            gp_XYZ through = normal.Transformed(here).XYZ() + normal.Transformed(next).XYZ();
            if (through.Modulus() < gp::Resolution()) {
                continue;
            }
            through.Normalize();
            auto speed = [&](const gp_Pnt& point) {
                return (point.Transformed(next).XYZ() - point.Transformed(here).XYZ()).Dot(through);
            };
            const double atOrigin = speed(origin);
            const double slope = std::hypot(speed(alongX) - atOrigin, speed(alongY) - atOrigin);
            if (slope < 1e-9) {  // no turn: the section only moves
                continue;
            }
            double low = std::numeric_limits<double>::infinity();
            double high = -low;
            for (const gp_Pnt& point : corners) {
                const double at = speed(point);
                low = std::min(low, at);
                high = std::max(high, at);
            }
            if (low < 0 && high > 0 && std::min(-low, high) / slope > reach.past) {
                reach.past = std::min(-low, high) / slope;
                reach.across = (high - low) / slope;
            }
        }
    }
    return reach;
}

/// The tilt at each corner of \a spine where "Transformed" keeps the section's orientation, and
/// the folds along its curves, from \a starts, the sections where the sweep of each wire of the
/// profile starts, set up by \a setup (with \a binormal, the binormal of Binormal mode). Along
/// straight edges the section only moves; elsewhere a sweep of the spine up to the corner gives
/// the motion that carries the section there, as the whole sweep has it (its law is made
/// continuous edge after edge). A profile that isn't closed planar wires, or lies along the
/// spine at its start, gives nothing.
/// The folds: along an arc, exactly, where the section turns about its axis. Along another curve
/// (or an arc in Binormal mode about another axis), only where a corner or the profile's own
/// slant tilted the section to it, from its sampled motion; a smooth spine with the section square
/// to it folds as before this test, with every transition alike.
CornerTilts measureCorners(
    const std::vector<TopoDS_Shape>& starts,
    const TopoDS_Wire& spine,
    const std::function<void(BRepOffsetAPI_MakePipeShell&)>& setup,
    const std::optional<gp_Dir>& binormal
)
{
    CornerTilts tilts;
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    if (edges.size() < 2 || starts.empty()) {
        return tilts;
    }
    const TopoDS_Wire start = firstWire(starts.front());
    if (start.IsNull() || !BRep_Tool::IsClosed(start)) {
        return tilts;
    }
    std::vector<gp_Pnt> startPoints;
    for (const TopoDS_Shape& shape : starts) {
        for (TopExp_Explorer it(shape, TopAbs_WIRE); it.More(); it.Next()) {
            const std::vector<gp_Pnt> points = pointsAlong(TopoDS::Wire(it.Current()));
            startPoints.insert(startPoints.end(), points.begin(), points.end());
        }
    }
    const std::optional<gp_Dir> startNormal = planeNormal(pointsAlong(start));
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
    // Whether a corner or the profile's slant has tilted the section to the spine
    bool tilted = tiltTo(*startNormal, tangentAlong(edges.front(), true)) > tiltTolerance;
    // An arc the section turns about the axis of
    auto turnsAboutAxis = [&](const TopoDS_Edge& edge) {
        BRepAdaptor_Curve curve(edge);
        return curve.GetType() == GeomAbs_Circle
            && (!binormal
                || std::abs(curve.Circle().Axis().Direction().Dot(*binormal))
                    > std::cos(tiltTolerance));
    };

    const gp_Pnt spineStart = BRep_Tool::Pnt(TopExp::FirstVertex(edges.front(), true));
    // The section where edge k starts: on a straight run the start's, moved there; after a
    // curve, carried there by the sweep of the spine up to there
    auto sectionAt = [&](size_t k, bool straightBefore) -> std::optional<Section> {
        gp_Trsf motion;
        if (straightBefore) {
            motion.SetTranslation(spineStart, BRep_Tool::Pnt(TopExp::FirstVertex(edges[k], true)));
        }
        else {
            BRepBuilderAPI_MakeWire upTo;
            for (size_t i = 0; i < k; ++i) {
                upTo.Add(edges[i]);
            }
            const std::optional<std::vector<gp_Trsf>> motions
                = motionsAlong(upTo.Wire(), gp_Ax2(spineStart, *startNormal), 2, setup);
            if (!motions) {
                return std::nullopt;
            }
            motion = motions->back();
        }
        Section section {startNormal->Transformed(motion), {}};
        for (const gp_Pnt& point : startPoints) {
            section.points.push_back(point.Transformed(motion));
        }
        return section;
    };
    // Whether the section folds along the curved edge k: after a small fold, which only warns,
    // the next curves are still looked at
    auto checkCurve = [&](size_t k, const Section& section) {
        if (tilts.folded || isLine(edges[k])) {
            return;
        }
        Reach reach;
        if (turnsAboutAxis(edges[k])) {
            reach = foldAlongArc(edges[k], section.normal, section.points);
        }
        else if (tilted && tiltTo(section.normal, tangentAlong(edges[k], true)) > tiltTolerance) {
            reach = foldAlongCurve(edges[k], section.normal, section.points, setup, binormal);
        }
        if (reach.unchecked > 0 && !tilts.unchecked) {
            const gp_Pnt start = BRep_Tool::Pnt(TopExp::FirstVertex(edges[k], true));
            tilts.unchecked = {start, reach.unchecked};
        }
        if (reach.past < Precision::Confusion()) {
            return;
        }
        const Fold fold {
            BRep_Tool::Pnt(TopExp::FirstVertex(edges[k], true)),
            BRepAdaptor_Curve(edges[k]).GetType() == GeomAbs_Circle,
            tilted,
            reach.past,
            reach.across
        };
        if (reach.past > smallFold * reach.across) {
            tilts.folded = fold;
        }
        else if (!tilts.smallFold) {
            tilts.smallFold = fold;
        }
    };
    checkCurve(0, Section {*startNormal, startPoints});

    bool straight = isLine(edges.front());
    double previous = 1;
    for (size_t k = 1; k < edges.size(); ++k) {
        const gp_Dir out = tangentAlong(edges[k], true);
        const double turn = tangentAlong(edges[k - 1], false).Angle(out);
        const bool corner = turn > Precision::Angular();
        const bool straightBefore = straight;
        straight = straight && isLine(edges[k]);
        // A straight run goes on, or a curve that needs no test: nothing changes
        if (!corner && (isLine(edges[k]) || (!turnsAboutAxis(edges[k]) && !tilted) || tilts.folded)) {
            continue;
        }
        const std::optional<Section> section = sectionAt(k, straightBefore);
        if (!section) {
            return {};
        }
        // By the section's own tilt there: many small corners add up to a large one
        tilted = tilted || tiltTo(section->normal, out) > tiltTolerance;
        checkCurve(k, *section);
        if (!corner) {
            continue;
        }
        const gp_Dir& normal = section->normal;
        Corner bend {
            BRep_Tool::Pnt(TopExp::LastVertex(edges[k - 1], true)),
            side * normal.Dot(out),
            std::numeric_limits<double>::infinity()
        };
        const gp_Vec across = gp_Vec(out) - gp_Vec(normal) * normal.Dot(out);
        if (across.Magnitude() > gp::Resolution()) {
            bend.thickness = extentAlong(section->points, gp_Dir(across)) * std::abs(bend.cosine);
        }
        if (bend.thickness < thinnest) {
            tilts.collapsed = bend;
            return tilts;
        }
        if (std::abs(bend.cosine) < nearLimit) {
            tilts.nearCollapse.push_back(bend);
        }
        if ((bend.cosine > 0) != (previous > 0)) {
            tilts.pieceStarts.push_back(k);
        }
        previous = bend.cosine;
    }
    return tilts;
}

/// Whether \a shape holds a solid that passes BRepCheck, each of its solids turned outward (a point
/// at infinity lies outside it): an inside-out one passes BRepCheck (a multisection Pipe on macOS,
/// ops#396). Not by the volume's sign: OCCT's default volume integration is badly wrong on faces
/// with many curved B-spline spans, negative for a correct pipe along 1000 of them (ops#414).
bool isValidSolid(const Part::TopoShape& shape)
{
    if (!shape.countSubShapes(TopAbs_SOLID) || !BRepCheck_Analyzer(shape.getShape()).IsValid()) {
        return false;
    }
    for (TopExp_Explorer it(shape.getShape(), TopAbs_SOLID); it.More(); it.Next()) {
        BRepClass3d_SolidClassifier classifier(it.Current());
        classifier.PerformInfinitePoint(Precision::Confusion());
        if (classifier.State() != TopAbs_OUT) {
            return false;
        }
    }
    return true;
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
/// the pipe across 90 degrees. With \a profileAtEnd the two swap, as the one sweep's do when
/// its end carries the profile's names (ops#379): the first piece's start projects them, and the
/// last piece's end keeps them. The other pieces' ends aren't named from their sections (their
/// edges are named from the side faces, `UPP`), each later piece sweeps the end wire of the
/// piece before, so its side faces are named from that wire's edges, and the caps between the
/// pieces carry their piece's index (`PCE<n>`).
Part::TopoShape sweepPiecesAndFuse(
    const TopoDS_Wire& spine,
    const std::vector<size_t>& pieceStarts,
    std::vector<Part::TopoShape> profiles,
    bool profileAtEnd,
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
            using PieceEnd = MapperPipeShellEnds::PieceEnd;
            const PieceEnd end = !last ? PieceEnd::None
                : profileAtEnd         ? PieceEnd::Own
                                       : PieceEnd::Projected;
            const MapperPipeShellEnds mapper(
                mkPS,
                section.getShape(),
                first && profileAtEnd,
                end,
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
        Part::TopoShape sewn = make(TopoDS_Shape());
        sewn.makeShapeWithElementMap(
            sewer.SewedShape(),
            Part::MapperSewing(sewer),
            sources,
            Part::OpCodes::Sewing
        );
        // A shell for each separate wire of the profile (two squares side by side), each a
        // solid: made one solid, the two shells gave an invalid one. A hole's shell is joined to
        // its outer wire's by the caps.
        const std::vector<Part::TopoShape> sewnShells = sewn.getSubTopoShapes(TopAbs_SHELL);
        if (sewnShells.empty()) {
            return {};
        }
        for (Part::TopoShape solid : sewnShells) {
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
        }
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
/// on a smooth spine, turning \a degrees) tell
std::string whyInvalid(
    int mode,
    int transition,
    bool multisection,
    const std::optional<std::string>& corner,
    double degrees
)
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
            " Where the spine curves tightly after a corner (the sharpest, {:.3g} degrees, is at "
            "{}), 'Transformed' may fold the profile over itself: try 'Right corner' or 'Round "
            "corner'.",
            degrees,
            *corner
        );
    }
    else if (degrees >= 150) {
        text += fmt::format(
            " 'Right corner' and 'Round corner' can't join a corner that turns nearly back on "
            "itself (the sharpest, {:.3g} degrees, is at {}): try 'Transformed' there.",
            degrees,
            *corner
        );
    }
    else {
        text += fmt::format(
            " 'Right corner' and 'Round corner' couldn't join the sweep at the spine's corners "
            "into one solid (the sharpest, {:.3g} degrees, is at {}): try 'Transformed'.",
            degrees,
            *corner
        );
    }
    return text;
}

/// A spine's vertex where it turns, and by how much
struct SpineCorner
{
    gp_Pnt at;
    double degrees;
};

/// OCCT's Frenet law, which counts how deep it calls itself and stops past a limit
/// (frenetRunsAway)
class BoundedFrenet: public GeomFill_Frenet
{
public:
    bool D0(const double param, gp_Vec& tangent, gp_Vec& normal, gp_Vec& binormal) override
    {
        // At a singular point it evaluates itself once more nearby, and rarely again from there
        if (depth >= 16) {
            runaway = true;
            return false;
        }
        // Back up a level however this one ends (OCCT throws when a deeper one refused)
        struct Level
        {
            int& depth;
            ~Level()
            {
                --depth;
            }
        } level {++depth};
        return GeomFill_Frenet::D0(param, tangent, normal, binormal);
    }
    int depth = 0;
    bool runaway = false;
};

/// Where OCCT's sweep would crash along \a spine in Standard, Frenet or Binormal mode (ops#413).
/// Each mode's law uses OCCT's Frenet law (GeomFill_Frenet), which at a point where the curve
/// doesn't bend (a singular point) evaluates itself again a little further on, by twice the width
/// it gives that point. Where the curve's bend reverses abruptly (an S-bend of a tenth of a
/// millimetre in a B-spline), that width is so small that the parameter doesn't change in floating
/// point: the law calls itself for ever, and the stack overflows. It happens where the law is
/// evaluated at such a point itself, as the end of one of its pieces: in Standard mode (\a
/// corrected, OCCT's corrected Frenet law) the start of each C0 piece, and in every mode the ends
/// of the finer pieces, unless the point was merged into a knot beside it. Whether OCCT's search
/// finds the point at all depends on the last bits of the numbers: on macOS, the 1-degree S-bend
/// over 0.07 mm of testShortSBendFolds; on Windows, over 0.105 mm. So this evaluates the law at
/// those ends, set up as the sweep has it (BRepFill_Edge3DLaw: each edge's curve, reversed for a
/// reversed edge), with its depth bounded. The point where it runs away; none where it doesn't.
std::optional<gp_Pnt> frenetRunsAway(const TopoDS_Wire& spine, bool corrected)
{
    for (BRepTools_WireExplorer it(spine); it.More(); it.Next()) {
        const TopoDS_Edge& edge = it.Current();
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        double first = 0;
        double last = 0;
        Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);
        if (curve.IsNull()) {
            continue;
        }
        if (edge.Orientation() == TopAbs_REVERSED) {
            Handle(Geom_TrimmedCurve) reversed = new Geom_TrimmedCurve(curve, first, last);
            reversed->Reverse();
            curve = reversed;
            first = curve->FirstParameter();
            last = curve->LastParameter();
        }
        Handle(BoundedFrenet) law = new BoundedFrenet();
        law->SetCurve(new GeomAdaptor_Curve(curve, first, last));
        // The ends of the law's pieces: its C0 pieces' starts, where the corrected law begins
        // each of its own (GeomFill_CorrectedFrenet::Init), and every end of its finer pieces,
        // which the sweep's approximation evaluates in every mode (they all give the curve's
        // knots joined with the singular points)
        std::vector<GeomAbs_Shape> shapes {GeomAbs_CN};
        if (corrected) {
            shapes.insert(shapes.begin(), GeomAbs_C0);
        }
        for (const GeomAbs_Shape shape : shapes) {
            const int count = law->NbIntervals(shape);
            NCollection_Array1<double> pieces(1, count + 1);
            law->Intervals(pieces, shape);
            for (int i = 1; i <= count; ++i) {
                law->SetInterval(pieces(i), pieces(i + 1));
                for (const double at : {pieces(i), pieces(i + 1)}) {
                    if (shape == GeomAbs_C0 && at != pieces(i)) {
                        continue;
                    }
                    gp_Vec tangent;
                    gp_Vec normal;
                    gp_Vec binormal;
                    try {
                        law->D0(at, tangent, normal, binormal);
                    }
                    catch (const Standard_Failure&) {
                        // What a deeper level refused leaves unset: the runaway is the answer
                    }
                    if (law->runaway) {
                        return curve->Value(at);
                    }
                }
            }
        }
    }
    return std::nullopt;
}

/// Where "Fixed" mode, which keeps the section's orientation (\a normal) all along, turns the
/// spine edge-on to it or past: the first point of \a spine where the tangent lies in the
/// section's plane or on its other side than at the start. From there the sweep runs back
/// through itself, a solid that BRepCheck passes, of the wrong volume (ops#370). None when it
/// doesn't.
std::optional<gp_Pnt> fixedTurnsBack(const TopoDS_Wire& spine, const gp_Dir& normal)
{
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    if (edges.empty()) {
        return std::nullopt;
    }
    const double start = normal.Dot(tangentAlong(edges.front(), true));
    if (std::abs(start) < Precision::Angular()) {
        return std::nullopt;
    }
    const double side = start > 0 ? 1 : -1;
    for (const TopoDS_Edge& edge : edges) {
        const BRepAdaptor_Curve curve(edge);
        // A line's two ends; along a curve, 8 places in each of its pieces
        const int pieces = curve.NbIntervals(GeomAbs_C2);
        const int looks = isLine(edge) ? 1 : std::clamp(8 * pieces, 16, 1024);
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        for (int i = 0; i <= looks; ++i) {
            gp_Pnt point;
            gp_Vec tangent;
            curve.D1(first + (last - first) * i / looks, point, tangent);
            if (tangent.Magnitude() < gp::Resolution()) {
                continue;
            }
            if (edge.Orientation() == TopAbs_REVERSED) {
                tangent.Reverse();
            }
            if (side * normal.Dot(gp_Dir(tangent)) < 1e-9) {
                return point;
            }
        }
    }
    return std::nullopt;
}

/// Where \a spine turns most sharply, none when it turns nowhere
std::optional<SpineCorner> sharpestCorner(const TopoDS_Wire& spine)
{
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    std::optional<SpineCorner> sharpest;
    double most = Precision::Angular();
    const size_t joints = BRep_Tool::IsClosed(spine) ? edges.size() : edges.size() - 1;
    for (size_t k = 0; edges.size() > 1 && k < joints; ++k) {
        const TopoDS_Edge& before = edges[k];
        const TopoDS_Edge& after = edges[(k + 1) % edges.size()];
        const double angle = tangentAlong(before, false).Angle(tangentAlong(after, true));
        if (angle > most) {
            most = angle;
            sharpest = SpineCorner {
                BRep_Tool::Pnt(TopExp::LastVertex(before, true)),
                angle * 180 / std::numbers::pi
            };
        }
    }
    return sharpest;
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

/// Where \a wire starts and ends along its order, which is where the pipe's shell starts and
/// ends; none for a wire without edges
std::optional<std::array<gp_Pnt, 2>> wireEnds(const TopoDS_Wire& wire)
{
    const std::vector<TopoDS_Edge> edges = edgesInOrder(wire);
    if (edges.empty()) {
        return std::nullopt;
    }
    return std::array<gp_Pnt, 2> {
        BRep_Tool::Pnt(TopExp::FirstVertex(edges.front(), true)),
        BRep_Tool::Pnt(TopExp::LastVertex(edges.back(), true))
    };
}

/// Whether the profile's names go to the spine's end, \a ends[1], rather than its start
/// (ops#379): \a stored are the spine's ends at the last good recompute, the side that carried
/// the names first, and they pair with the new ends the way whose distances add up to less (a
/// tie keeps the start). None when nothing is stored: a new pipe, or one saved before.
std::optional<bool> storedSideAtEnd(
    const std::vector<Base::Vector3d>& stored,
    const std::array<gp_Pnt, 2>& ends
)
{
    if (stored.size() != 2) {
        return std::nullopt;
    }
    const gp_Pnt profileSide(stored[0].x, stored[0].y, stored[0].z);
    const gp_Pnt other(stored[1].x, stored[1].y, stored[1].z);
    const double kept = ends[0].Distance(profileSide) + ends[1].Distance(other);
    const double swapped = ends[1].Distance(profileSide) + ends[0].Distance(other);
    return swapped + Precision::Confusion() < kept;
}
}  // namespace

PipeCapFacing PartDesign::pipeCapsFacing(
    const TopoDS_Shape& solid,
    const TopoDS_Wire& spine,
    const std::vector<TopoDS_Shape>& starts,
    const std::vector<TopoDS_Shape>& ends,
    bool turning
)
{
    PipeCapFacing facing;
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    if (solid.IsNull() || edges.empty()) {
        return facing;
    }
    // An end of the spine: its sections' vertices, and how a point there moves along the spine
    // (per mm), the tangent plus the frame's turn about the bend's axis (Darboux: curvature times
    // binormal, C' x C'' / |C'|^3, turned with the wire's direction)
    struct End
    {
        std::vector<gp_Pnt> vertices;
        gp_Pnt at;
        gp_Vec tangent;
        gp_Vec turn;
        // Which way an outward cap faces against the motion: back at the start, on at the end
        double side;
    };
    auto endOf = [&](const TopoDS_Edge& edge, bool atStart, const std::vector<TopoDS_Shape>& sections) {
        End end {{}, {}, gp_Vec(tangentAlong(edge, atStart)), gp_Vec(0, 0, 0), atStart ? -1.0 : 1.0};
        for (const TopoDS_Shape& section : sections) {
            for (TopExp_Explorer it(section, TopAbs_VERTEX); !section.IsNull() && it.More();
                 it.Next()) {
                end.vertices.push_back(BRep_Tool::Pnt(TopoDS::Vertex(it.Current())));
            }
        }
        const BRepAdaptor_Curve curve(edge);
        const bool reversed = edge.Orientation() == TopAbs_REVERSED;
        gp_Vec d1;
        gp_Vec d2;
        curve.D2(atStart != reversed ? curve.FirstParameter() : curve.LastParameter(), end.at, d1, d2);
        const double speed = d1.Magnitude();
        if (turning && speed > gp::Resolution()) {
            end.turn = d1.Crossed(d2) / (speed * speed * speed);
            if (reversed) {
                end.turn.Reverse();
            }
        }
        return end;
    };
    std::vector<End> bothEnds;
    if (!starts.empty()) {
        bothEnds.push_back(endOf(edges.front(), true, starts));
    }
    if (!ends.empty()) {
        bothEnds.push_back(endOf(edges.back(), false, ends));
    }
    const double edgeOn = std::sin(3 * std::numbers::pi / 180);
    const double sameVertex = 100 * Precision::Confusion();
    for (TopExp_Explorer it(solid, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face& face = TopoDS::Face(it.Current());
        std::vector<gp_Pnt> corners;
        for (TopExp_Explorer vertex(face, TopAbs_VERTEX); vertex.More(); vertex.Next()) {
            corners.push_back(BRep_Tool::Pnt(TopoDS::Vertex(vertex.Current())));
        }
        for (const End& end : bothEnds) {
            // A cap: every vertex of the face is one of the end's sections'
            const bool cap = !corners.empty()
                && std::all_of(corners.begin(), corners.end(), [&](const gp_Pnt& corner) {
                       return std::any_of(
                           end.vertices.begin(),
                           end.vertices.end(),
                           [&](const gp_Pnt& vertex) { return vertex.Distance(corner) < sameVertex; }
                       );
                   });
            if (!cap) {
                continue;
            }
            // The face's outward normal, by its orientation in the solid
            BRepGProp_Face surface(face);
            double u0 = 0;
            double u1 = 0;
            double v0 = 0;
            double v1 = 0;
            surface.Bounds(u0, u1, v0, v1);
            gp_Pnt middle;
            gp_Vec normal;
            surface.Normal((u0 + u1) / 2, (v0 + v1) / 2, middle, normal);
            if (normal.Magnitude() < gp::Resolution()) {
                break;
            }
            normal.Normalize();
            int out = 0;
            int in = 0;
            for (const gp_Pnt& corner : corners) {
                const gp_Vec motion = end.tangent + end.turn.Crossed(gp_Vec(end.at, corner));
                if (motion.Magnitude() < gp::Resolution()) {
                    continue;
                }
                const double cosine = end.side * normal.Dot(motion) / motion.Magnitude();
                out += cosine > edgeOn ? 1 : 0;
                in += cosine < -edgeOn ? 1 : 0;
            }
            const int all = static_cast<int>(corners.size());
            facing.outward += out == all ? 1 : 0;
            facing.inward += in == all ? 1 : 0;
            break;
        }
    }
    return facing;
}

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
    ADD_PROPERTY_TYPE(
        SpineEnds,
        (),
        "Sweep",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden),
        "Where the spine started and ended at the last successful recompute, the end with the "
        "profile's names first, where they lie in the body: the next recompute keeps the names "
        "on the matching end (ops#379)"
    );
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
        // "Fixed" with one profile: the spine mustn't turn edge-on to it or past
        const bool fixedMode = mode == 1 && profilePoint.isNull() && multisections.empty();
        auto setup = [&](BRepOffsetAPI_MakePipeShell& pipe) {
            setupAlgorithm(pipe, auxpath.getShape());
        };
        auto inPlace = [&](const gp_Pnt& point) {
            return pointText(point.Transformed(invObjLoc.Inverted().Transformation()));
        };
        // Before any sweep: the modes that orient the profile by the curve's bend crash OCCT
        // along some curves (ops#413), and so does Auxiliary mode without curvilinear
        // equivalence, whose law holds the same Frenet law of the spine. Along a long smooth
        // B-spline edge the bend needn't reverse abruptly: the curve's parameter there is large,
        // and the same curve split into shorter edges sweeps.
        const bool auxiliaryFrenet = mode == 3 && !AuxiliaryCurvilinear.getValue();
        if (mode == 0 || mode == 2 || mode == 4 || auxiliaryFrenet) {
            if (const auto at = frenetRunsAway(TopoDS::Wire(path.getShape()), mode == 0)) {
                return new App::DocumentObjectExecReturn(
                    fmt::format(
                        "Pipe: OCCT's sweep would crash at {} on the spine, where the curve's bend "
                        "reverses too abruptly for OCCT to orient the profile in '{}' mode{}. "
                        "Smooth the curve there, split it into shorter edges, {}or use another "
                        "mode ('Fixed' isn't affected).",
                        inPlace(*at),
                        Mode.getValueAsString(),
                        auxiliaryFrenet ? " without curvilinear equivalence" : "",
                        auxiliaryFrenet ? "turn on 'Curvilinear equivalence', " : ""
                    )
                );
            }
        }
        const std::optional<SpineCorner> sharpest = sharpestCorner(TopoDS::Wire(path.getShape()));
        // A fold fails the pipe; a small one (under smallFold of the section's extent) warns
        auto foldText = [&](const Fold& fold, bool small) {
            const std::string by = small
                ? fmt::format("by {:.2g} mm of its {:.2g} mm width", fold.reach, fold.across)
                : fmt::format("by {:.2g} mm", fold.reach);
            if (!fold.tilted) {
                return fmt::format(
                    "Pipe: the profile folds {}over itself along the arc from {} ({}): the arc's "
                    "axis passes through it{}. Use a larger radius or a smaller profile{}.",
                    small ? "slightly " : "",
                    inPlace(fold.at),
                    by,
                    small ? ", and the result may cross itself there" : "",
                    small ? " to avoid it" : ""
                );
            }
            // Frenet mode turns the profile with the curve's bend, over at each place where the
            // bend reverses; "Round corner" crashes OCCT on such curves after a corner (ops#370)
            if (mode == 2 && !fold.arc) {
                return fmt::format(
                    "Pipe: 'Frenet' mode folds the profile {}over itself along the curve from {} "
                    "({}): it turns the profile with the curve's bend, over where the bend "
                    "reverses, and the corners before it (or the profile's own slant) tilt the "
                    "profile to it{}. Use 'Standard' or 'Binormal' mode, or a gentler curve{}.",
                    small ? "slightly " : "",
                    inPlace(fold.at),
                    by,
                    small ? ": the result may cross itself there" : "",
                    small ? ", to avoid it" : ""
                );
            }
            return fmt::format(
                "Pipe: 'Transformed' folds the profile {}over itself along the {} from {} ({}), as "
                "the corners before it (or the profile's own slant) tilt the profile to it{}. Use "
                "'Right corner' or 'Round corner', or a gentler {}{}.",
                small ? "slightly " : "",
                fold.arc ? "arc" : "curve",
                inPlace(fold.at),
                by,
                small ? ": the result may cross itself there" : "",
                fold.arc ? "arc" : "curve",
                small ? ", to avoid it" : ""
            );
        };
        CornerTilts tilts;
        auto invalidPipe = [&]() {
            // A small fold that BRepCheck refuses (a square profile's): the fold is the reason
            if (const auto& fold = tilts.smallFold) {
                return "Pipe: the result isn't a valid solid: " + foldText(*fold, false).substr(6);
            }
            return whyInvalid(
                mode,
                Transition.getValue(),
                Transformation.getValue() == 1,
                sharpest ? std::optional<std::string>(inPlace(sharpest->at)) : std::nullopt,
                sharpest ? sharpest->degrees : 0
            );
        };
        auto warn = [&](const std::string& text) {
            if (auto doc = getDocument()) {
                const char* previous = doc->getWarningDescription(this);
                doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + text : text);
            }
        };
        std::vector<TopoDS_Shape> sweptStarts;

        // build all shells
        std::vector<Part::TopoShape> shells;

        Part::TopoShape copyProfilePoint(profilePoint);
        if (!profilePoint.isNull()) {
            copyProfilePoint.move(invObjLoc);
        }

        // Which end of the shell carries the profile's names, decided once for every wire: the
        // end the names were on at the last good recompute, so that no edit moves them, or the
        // first wire's sections when nothing is stored (ops#379). The spine's ends are paired
        // and stored where they lie in the body, not in the pipe's own frame: that frame is the
        // profile sketch's or the base feature's, and moves with them while the spine stays.
        std::optional<std::array<gp_Pnt, 2>> spineEnds = wireEnds(TopoDS::Wire(path.getShape()));
        std::optional<bool> reversed;
        if (spineEnds) {
            const gp_Trsf inBody = invObjLoc.Inverted().Transformation();
            for (gp_Pnt& end : *spineEnds) {
                end.Transform(inBody);
            }
            reversed = storedSideAtEnd(SpineEnds.getValues(), *spineEnds);
        }
        // Once the pipe is good: the spine's ends the next recompute pairs with its own, written
        // only when they moved, so that a recompute that changes nothing leaves the file as it was
        auto storeSpineEnds = [&]() {
            if (!spineEnds) {
                return;
            }
            const bool atEnd = reversed.value_or(false);
            const gp_Pnt& profileSide = (*spineEnds)[atEnd ? 1 : 0];
            const gp_Pnt& other = (*spineEnds)[atEnd ? 0 : 1];
            const std::vector<Base::Vector3d> values {
                Base::Vector3d(profileSide.X(), profileSide.Y(), profileSide.Z()),
                Base::Vector3d(other.X(), other.Y(), other.Z())
            };
            const std::vector<Base::Vector3d>& stored = SpineEnds.getValues();
            const bool same = stored.size() == values.size()
                && stored[0].IsEqual(values[0], Precision::Confusion())
                && stored[1].IsEqual(values[1], Precision::Confusion());
            if (!same) {
                SpineEnds.setValues(values);
            }
        };

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
            if (!reversed) {
                reversed = MapperPipeShellEnds::endsSwapped(
                    mkPS,
                    sections.front().getShape(),
                    sections.back().getShape()
                );
            }
            shell.makeShapeWithElementMap(
                built,
                MapperPipeShellEnds(
                    mkPS,
                    sections.front().getShape(),
                    sections.back().getShape(),
                    copyProfilePoint.getShape(),
                    *reversed
                ),
                sections,
                Part::OpCodes::PipeShell
            );
            shells.push_back(shell);

            if (sheared || fixedMode) {
                TopTools_ListOfShape simulated;
                mkPS.Simulate(2, simulated);
                sweptStarts.push_back(simulated.First());
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

        // "Fixed" mode keeps the profile's orientation: where the spine turns past square to it,
        // the sweep runs back through itself, a solid that BRepCheck passes, of the wrong volume
        // (an L at 120 degrees: 320 for its legs' 621.5, and nothing in common with them).
        // Refine, which left an invalid solid there, keeps the unrefined shape since ops#389.
        if (fixedMode && !sweptStarts.empty()) {
            const TopoDS_Wire start = firstWire(sweptStarts.front());
            const std::optional<gp_Dir> normal
                = start.IsNull() ? std::nullopt : planeNormal(pointsAlong(start));
            const std::optional<gp_Pnt> turn
                = normal ? fixedTurnsBack(TopoDS::Wire(path.getShape()), *normal) : std::nullopt;
            if (turn) {
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: 'Fixed' mode keeps the profile's orientation, and at {} the spine turns "
                    "edge-on to it or past: the pipe would run back through itself. Use 'Standard' "
                    "mode, or change the spine.",
                    inPlace(*turn)
                ));
            }
        }

        if (sheared) {
            // Every wire of the profile counts: a fold or a thin leg of any of them spoils the pipe
            std::optional<gp_Dir> binormal;
            if (mode == 4) {
                const Base::Vector3d& direction = Binormal.getValue();
                binormal = gp_Dir(direction.x, direction.y, direction.z);
            }
            tilts = measureCorners(sweptStarts, TopoDS::Wire(path.getShape()), setup, binormal);
            if (const auto& corner = tilts.collapsed) {
                return new App::DocumentObjectExecReturn(
                    fmt::format(
                        "Pipe: 'Transformed' leaves the stretch after the spine's corner at {} no "
                        "thickness: the profile meets it edge-on ({:.4f} degrees). Use 'Right "
                        "corner' or 'Round corner', or change the corner.",
                        inPlace(corner->at),
                        tiltDegrees(*corner)
                    )
                );
            }
            if (const auto& fold = tilts.folded) {
                return new App::DocumentObjectExecReturn(foldText(*fold, false));
            }
            for (const Corner& corner : tilts.nearCollapse) {
                const std::string text = fmt::format(
                    "Pipe: the stretch after the corner at {} is nearly edge-on to the profile "
                    "({:.3f} degrees, {:.2g} % of its thickness). A small change makes it fail.",
                    inPlace(corner.at),
                    tiltDegrees(corner),
                    std::abs(corner.cosine) * 100
                );
                warn(text);
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
            // The end stored at the last good recompute keeps the names, as in the one sweep, so
            // that an edit across 90 degrees and back leaves them where they were; with nothing
            // stored, the one sweep's sections decided above (the end nearest the profile)
            result = sweepPiecesAndFuse(
                TopoDS::Wire(path.getShape()),
                tilts.pieceStarts,
                profiles,
                *reversed,
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

        // Each solid turned outward by its caps where they tell (pipeCapsFacing), else by
        // classifying a point at infinity (a closed spine has no caps). Not by the classifier
        // alone: on macOS it took ops#396's inside-out multisection solid for an outward one, and
        // the result gate below, which asked it again, passed it.
        std::vector<TopoDS_Shape> startSections;
        std::vector<TopoDS_Shape> endSections;
        for (const Part::TopoShape& wire : frontwires) {
            startSections.push_back(wire.getShape());
        }
        for (const Part::TopoShape& wire : backwires) {
            endSections.push_back(wire.getShape());
        }
        auto capsFacing = [&](const Part::TopoShape& solid) {
            return pipeCapsFacing(
                solid.getShape(),
                TopoDS::Wire(path.getShape()),
                startSections,
                endSections,
                mode != 1
            );
        };
        auto shapes = result.getSubTopoShapes(TopAbs_SHELL);
        for (auto& s : shapes) {
            // build the solid
            s = s.makeElementSolid();
            const PipeCapFacing caps = capsFacing(s);
            bool inward = caps.inward > 0 && caps.outward == 0;
            if (caps.inward == 0 && caps.outward == 0) {
                BRepClass3d_SolidClassifier SC(s.getShape());
                SC.PerformInfinitePoint(Precision::Confusion());
                inward = SC.State() == TopAbs_IN;
            }
            if (inward) {
                s.setShape(s.getShape().Reversed(), false);
            }
        }

        // Every pipe is a valid solid with a positive volume, whatever its transition (ops#381):
        // "Right corner" and "Round corner" gave no solid, or an invalid one, at the corners of
        // a pipe with several sections and at hairpins, and "Transformed" an invalid one where
        // a tight curve follows a corner of nearly 90 degrees; a multisection pipe on macOS an
        // inside-out one (ops#396). A self-intersection that only the boolean check finds
        // passes: that check takes seconds to many minutes on a long B-spline spine, and reports
        // valid ones (C0 continuity). measureCorners finds the folds of a tilted section along
        // curves instead. The caps and the classifier must both find the solid turned outward:
        // caps that disagree with each other, or with the classifier, show a solid turned
        // inside out in part (or the classifier's error).
        for (const auto& s : shapes) {
            if (!isValidSolid(s) || capsFacing(s).inward > 0) {
                return new App::DocumentObjectExecReturn(invalidPipe());
            }
        }
        // A small fold passes, with a warning: its measure decides, not the boolean check, so
        // the same file gives the same result on every platform (smallFold)
        if (const auto& fold = tilts.smallFold) {
            warn(foldText(*fold, true));
        }
        // A curve where the budget of places ran out before every stretch where the profile could
        // fold was looked at closely: neither silent nor a failure, as most such pipes are sound
        if (const auto& unchecked = tilts.unchecked) {
            warn(fmt::format(
                "Pipe: the curve from {} bends in too many places to check them all for folds: "
                "{} stretch{} where 'Transformed' could fold the profile over itself {} left "
                "unchecked, and the result may cross itself there. Use 'Right corner' or 'Round "
                "corner' to avoid it.",
                inPlace(unchecked->first),
                unchecked->second,
                unchecked->second == 1 ? "" : "es",
                unchecked->second == 1 ? "was" : "were"
            ));
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
            storeSpineEnds();
            return App::DocumentObject::StdReturn;
        }

        Part::TopoShape boolOp = makeResultShape(base);

        result.Tag = -getID();  // invert tag to differentiate the pre-boolean pipe
        //                        from the post-boolean pipe
        //                        setting result to the negative tag is a bit confusing,
        //                        because you would expect this to be set to the feature's shape,
        //                        but boolOp is the topoShape that is actually being copied

        boolOp.makeElementBoolean(getBooleanMaker(), {base, result}, nullptr, FuzzyTolerance.getValue());

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
        storeSpineEnds();
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
