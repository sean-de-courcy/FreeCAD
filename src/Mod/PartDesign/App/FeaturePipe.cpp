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
#include <cstdint>
#include <functional>
#include <limits>
#include <map>
#include <numbers>
#include <numeric>
#include <optional>
#include <queue>
#include <tuple>

#include <fmt/format.h>

#include <Mod/Part/App/FCBRepAlgoAPI_Cut.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <BRepAdaptor_Curve.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepLProp_CLProps.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepGProp.hxx>
#include <BRepGProp_Face.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepTools.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <ElCLib.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Surface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <GeomAdaptor_Curve.hxx>
#include <GeomConvert_BSplineCurveToBezierCurve.hxx>
#include <GeomFill_Frenet.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <gp.hxx>
#include <GProp_GProps.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Circ.hxx>
#include <gp_Elips.hxx>
#include <gp_Hypr.hxx>
#include <gp_Parab.hxx>
#include <gp_Quaternion.hxx>
#include <gp_Trsf.hxx>
#include <Law_Function.hxx>
#include <Precision.hxx>
#include <ShapeAnalysis_FreeBounds.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Wire.hxx>
#include <TopTools_DataMapOfShapeInteger.hxx>
#include <TopTools_DataMapOfShapeListOfShape.hxx>
#include <TopTools_DataMapOfShapeShape.hxx>
#include <TopTools_HSequenceOfShape.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>


#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/NameTable.h>
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
// may swap roles: the Pipe decides once which end carries the profile's names, and the mapper
// takes that decision (ops#379, Pipe::SpineEnds). A pipe that has recomputed before keeps the
// end it chose then; the first time, the sections decide (endsSwapped):
// - One profile: the ends swap when the profile lies nearer the spine's far end (a spine drawn
//   towards it), so the names go to the end at or nearest the profile's place.
// - Several sections: the first and last decide together, by the pairing of sections and ends
//   whose distances add up to less, each section's distance the mean over its vertices (so a
//   section weighs the same whatever its number of vertices); the ends follow the sections'
//   order along the spine.
// A tie keeps the start. A closed spine's ends are one place: the sections decide every time,
// and what is stored is its named start instead (Pipe::execute, ops#469).
// Each end element is found through the side face or edge its section element generated. A
// point section names only its end's vertex. Edges at a bend, a corner or a middle section have
// no section element of their own: they keep their `UPP` names.
// The spine is a source too, as in Part::Sweep's MapperSweepEnds (ops#415): MakePipeShell
// reports a leg's side faces as generated from its spine edge as well as from the profile's
// edge, so each is named from both, and the lateral edges that bound them are added to the
// spine edge's list, so each is named from its profile vertex and its leg. Named from the
// profile alone, a profile element's sides on every leg shared one name told apart by the legs'
// order, and an edit adding a segment at the spine's start or drawing it the other way moved
// references to another leg silently. The section copies MakePipeShell reports from the spine's
// vertices (at the corners and ends) are left out, and the ends are named from the sections. A
// joint, where a profile element's sides along two spine edges meet at their spine vertex, is
// named from that element and that corner, and so is a cap between a union's pieces (the same
// element's copy at a break): a joint that becomes a break, or a break that becomes a joint, keeps
// its name at its own corner. Named from the side faces they bound (`UPP`), a joint whose corner
// became a break took the next corner's joint, which shares a leg's side face (ops#415, round 4).
// The corner is a vertex of a third source (CornerSource), not the spine's own vertex: a sketch
// vertex's name is its lines' ends (`g1v2,g2v1`), which swap when a line is drawn the other way,
// and the next corner's shares one of them, so a joint's name went to the next corner's by the
// shared part (round 5). At a Round corner the round face lies between the legs' sides: its edges
// stay `UPP`. What OCCT reports the spine's vertex at a corner generated (a Round corner's round
// faces and sectors) and the lateral edges that bound them are generated from the corner's second
// vertex instead (CornerSource::rounds, ops#478), for the same reason. An element's round faces
// at one corner (a round hole's two) are told apart by their places on the legs' sides, as the
// joints are, and the edges and vertices named from them follow (placeRounds, round 9).
class MapperPipeShellEnds: public Part::MapperMaker
{
public:
    /// \a sections are the sections added to \a pipe, a wire or a vertex each, in order; \a
    /// point is the first when it is the profile's point, which the side shapes' history leaves
    /// out (it isn't otherwise a source). \a spine is the wire \a pipe sweeps along, a source of
    /// the shape too. \a reversed: the shell's end, not its start, carries the first section's
    /// names (ops#379). \a corners binds the spine's vertices to the corner source's
    /// (CornerSource::vertices), which name the joints.
    MapperPipeShellEnds(
        BRepOffsetAPI_MakePipeShell& pipe,
        const std::vector<Part::TopoShape>& sections,
        const TopoDS_Shape& point,
        const TopoDS_Shape& spine,
        bool reversed,
        const TopTools_DataMapOfShapeShape& corners,
        const TopTools_DataMapOfShapeShape& rounds
    )
        : MapperMaker(pipe)
        , point(point)
        , corners(corners)
    {
        useRounds(rounds);
        std::vector<TopoDS_Shape> swept;
        for (const Part::TopoShape& section : sections) {
            swept.push_back(section.getShape());
        }
        useSpine(pipe, spine, swept);
        bindJoints(pipe, spine, swept, nullptr);
        const TopoDS_Shape& first = swept.front();
        const TopoDS_Shape& last = swept.back();
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

    /// A piece of a union, swept from \a section at its start along \a spine, the piece's wire
    /// (ops#370). Its start keeps the section's names, or, with \a startProjects (the first
    /// piece, when the union's end carries the profile's names), projects them (ops#379). Its
    /// end is named as \a end says. \a origins, when given (a piece after the first), binds each
    /// element of \a section to the profile's element it was swept from: the profile, not the
    /// section, is the shape's source, and the side faces and edges are named from its elements
    /// and the spine's, as the one sweep's are (ops#415). Named from the section, the end wire of
    /// the piece before, they descended from that piece's names, the same at whichever corner
    /// the break between the pieces fell (ops#379, round 4). \a frontBreak and \a backBreak are
    /// the spine's vertices where the piece meets the one before and after it (null at the
    /// union's ends): the edges and vertices of the cap there are generated from that corner (its
    /// vertex in \a corners) and the profile's element each is a copy of, as Part::Sweep names
    /// its ends. Named from the one side face each bounds, which holds its leg but not the leg's
    /// end, a cap edge had the same name at either end of its leg, and a reference went to the
    /// other end by its exact name when an edit moved the break along the leg (ops#415, round 3).
    MapperPipeShellEnds(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& section,
        const TopoDS_Shape& spine,
        bool startProjects,
        PieceEnd end,
        const TopTools_DataMapOfShapeShape* origins,
        const TopoDS_Shape& frontBreak,
        const TopoDS_Shape& backBreak,
        const TopTools_DataMapOfShapeShape& corners,
        const TopTools_DataMapOfShapeShape& rounds
    )
        : MapperMaker(pipe)
        , corners(corners)
    {
        useRounds(rounds);
        useSpine(pipe, spine, {section});
        if (origins) {
            // In the section's order, not the map's, which follows the shapes' addresses: what a
            // profile's element generated is listed in this order (ops#479)
            TopTools_IndexedMapOfShape elements;
            TopExp::MapShapes(section, elements);
            for (int i = 1; i <= elements.Extent(); ++i) {
                const TopoDS_Shape* origin = origins->Seek(elements(i));
                if (!origin) {
                    continue;
                }
                if (!sweptFrom.IsBound(*origin)) {
                    sweptFrom.Bind(*origin, TopTools_ListOfShape());
                }
                sweptFrom.ChangeFind(*origin).Append(elements(i));
                sectionElements.Add(*origin);
            }
        }
        bindJoints(pipe, spine, {section}, origins);
        TopTools_IndexedMapOfShape startElements;
        TopTools_IndexedMapOfShape endElements;
        TopExp::MapShapes(pipe.FirstShape(), startElements);
        TopExp::MapShapes(pipe.LastShape(), endElements);
        TopTools_DataMapOfShapeListOfShape atStart;
        bindEnds(pipe, section, startElements, nullptr, atStart);
        bindEnds(pipe, section, endElements, &startElements, bound);
        (startProjects ? ends : starts) = atStart;
        bindBreak(frontBreak, section, atStart, origins);
        bindBreak(backBreak, section, bound, origins);
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
        if (const TopoDS_Shape* vertex = roundsOf.Seek(s)) {
            // A corner's second vertex: what its spine vertex generated
            return generatedFrom(*vertex);
        }
        if (rounded.Contains(s)) {
            _res.clear();
            return _res;
        }
        return generatedFrom(s);
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
    /// What \a s generates, a spine's vertex at a corner included
    const std::vector<TopoDS_Shape>& generatedFrom(const TopoDS_Shape& s) const
    {
        if (s.IsSame(point)) {
            _res.clear();
            return _res;
        }
        if (const TopTools_ListOfShape* elements = sweptFrom.Seek(s)) {
            // A profile's element: what the section's elements swept from it generated
            std::vector<TopoDS_Shape> made;
            for (const TopoDS_Shape& element : *elements) {
                for (const TopoDS_Shape& shape : MapperMaker::generated(element)) {
                    if (std::ranges::none_of(made, [&](const TopoDS_Shape& found) {
                            return found.IsSame(shape);
                        })) {
                        made.push_back(shape);
                    }
                }
            }
            _res = std::move(made);
        }
        else {
            MapperMaker::generated(s);
        }
        if (spineVertices.Contains(s) && !sectionElements.Contains(s)) {
            std::erase_if(_res, [](const TopoDS_Shape& element) {
                return element.ShapeType() == TopAbs_EDGE || element.ShapeType() == TopAbs_VERTEX;
            });
        }
        if (const TopTools_ListOfShape* bound = copies.Seek(s)) {
            // The joints and the edges and vertices of a cap between pieces: of a profile's
            // element, its copies there; of the spine's vertex, all of them there
            for (const TopoDS_Shape& copy : *bound) {
                if (std::ranges::none_of(_res, [&](const TopoDS_Shape& found) {
                        return found.IsSame(copy);
                    })) {
                    _res.push_back(copy);
                }
            }
        }
        if (spineVertices.Contains(s) || spineEdges.Contains(s)) {
            // The lateral edges that bound the side faces this spine element generated
            TopTools_IndexedMapOfShape bounding;
            for (const TopoDS_Shape& element : _res) {
                if (element.ShapeType() == TopAbs_FACE) {
                    TopExp::MapShapes(element, TopAbs_EDGE, bounding);
                }
            }
            for (int i = 1; i <= bounding.Extent(); ++i) {
                if (laterals.Contains(bounding(i))
                    && std::ranges::none_of(_res, [&](const TopoDS_Shape& found) {
                           return found.IsSame(bounding(i));
                       })) {
                    _res.push_back(bounding(i));
                }
            }
        }
        orderRounds(_res);
        return _res;
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

    /// The corner source's vertex for the spine's vertex \a vertex
    const TopoDS_Shape& cornerOf(const TopoDS_Shape& vertex) const
    {
        const TopoDS_Shape* corner = corners.Seek(vertex);
        return corner ? *corner : vertex;
    }

    /// Binds the corner at the spine's vertex \a vertex (none when null) and the profile's
    /// elements to the elements of the cap there, \a cap (by the elements of \a section, each the
    /// copy of the profile's element \a origins binds it to, or of itself without \a origins), in
    /// the section's order: the corner's copies are listed in it (ops#479)
    void bindBreak(
        const TopoDS_Shape& vertex,
        const TopoDS_Shape& section,
        const TopTools_DataMapOfShapeListOfShape& cap,
        const TopTools_DataMapOfShapeShape* origins
    )
    {
        if (vertex.IsNull()) {
            return;
        }
        TopTools_IndexedMapOfShape elements;
        TopExp::MapShapes(section, elements);
        for (int i = 1; i <= elements.Extent(); ++i) {
            const TopTools_ListOfShape* found = cap.Seek(elements(i));
            const TopoDS_Shape* origin = origins ? origins->Seek(elements(i)) : &elements(i);
            if (!found || !origin) {
                continue;
            }
            for (const TopoDS_Shape& copy : *found) {
                bindCopy(*origin, copy);
                bindCopy(cornerOf(vertex), copy);
            }
        }
    }

    /// Binds the corner at each of \a spine's vertices between two of its edges, and the profile's
    /// elements, to the joints there: the edges where the side faces a profile's edge sweeps
    /// along the two spine edges meet, and the vertices where the lateral edges of a profile's
    /// vertex do. The profile's element of each element of \a sections is the one \a origins
    /// binds it to, or itself without \a origins. The shell's end wires are left out: where a
    /// closed spine closes, the joint is the start, which keeps the section's names. A joint is
    /// bound to one corner, the one it lies at (round 6). The joints of one element at one corner
    /// share their two sources and are told apart by an index, which follows the order they are
    /// bound in: they are bound in the order of their places on the sides they bound (placeOn),
    /// not in the order OCCT stores them, which differs between Windows and macOS and changes
    /// with edits that keep the topology (a round hole's four bend arcs at a "Right corner": a
    /// reference went to the mirror arc, silently; round 7).
    void bindJoints(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& spine,
        const std::vector<TopoDS_Shape>& sections,
        const TopTools_DataMapOfShapeShape* origins
    )
    {
        TopTools_IndexedDataMapOfShapeListOfShape edgesAt;
        TopExp::MapShapesAndAncestors(spine, TopAbs_VERTEX, TopAbs_EDGE, edgesAt);
        TopTools_IndexedMapOfShape ends;
        TopExp::MapShapes(pipe.FirstShape(), ends);
        TopExp::MapShapes(pipe.LastShape(), ends);
        // The joints found, and each one's corner (by its index in edgesAt): where two corners lie
        // between the same two spine edges (a closed spine of two), a joint is found at both, and
        // is the nearer one's
        TopTools_IndexedMapOfShape joints;
        std::vector<int> cornerAt;
        // Each joint's profile element, the two sides it bounds, and whether the sides run
        // against the section's element (runsAgainst)
        std::vector<TopoDS_Shape> originOf;
        std::vector<std::pair<TopoDS_Shape, TopoDS_Shape>> sidesOf;
        std::vector<bool> againstOf;
        // Per spine edge (by its index in spineEdges): the side faces it sweeps and their edges
        std::vector<TopTools_IndexedMapOfShape> legFaces(spineEdges.Extent() + 1);
        std::vector<TopTools_IndexedMapOfShape> legEdges(spineEdges.Extent() + 1);
        for (int i = 1; i <= spineEdges.Extent(); ++i) {
            for (const TopoDS_Shape& face : pipe.Generated(spineEdges(i))) {
                if (face.ShapeType() == TopAbs_FACE) {
                    legFaces[i].Add(face);
                    TopExp::MapShapes(face, TopAbs_EDGE, legEdges[i]);
                }
            }
        }
        for (const TopoDS_Shape& section : sections) {
            if (section.IsNull()) {
                continue;
            }
            for (TopAbs_ShapeEnum type : {TopAbs_EDGE, TopAbs_VERTEX}) {
                const TopAbs_ShapeEnum sideType = type == TopAbs_EDGE ? TopAbs_FACE : TopAbs_EDGE;
                const std::vector<TopTools_IndexedMapOfShape>& legSides
                    = type == TopAbs_EDGE ? legFaces : legEdges;
                TopTools_IndexedMapOfShape elements;
                TopExp::MapShapes(section, type, elements);
                for (int k = 1; k <= elements.Extent(); ++k) {
                    const TopoDS_Shape* origin = origins ? origins->Seek(elements(k))
                                                         : &elements(k);
                    if (!origin) {
                        continue;
                    }
                    const bool against = type == TopAbs_EDGE
                        && runsAgainst(pipe, TopoDS::Edge(elements(k)), ends);
                    if (type == TopAbs_EDGE) {
                        placeRounds(pipe, elements(k), against, edgesAt, legFaces);
                    }
                    // The element's side along the spine edge \a i
                    auto sideOn = [&](int i) {
                        for (const TopoDS_Shape& side : pipe.Generated(elements(k))) {
                            if (side.ShapeType() == sideType && legSides[i].Contains(side)) {
                                return side;
                            }
                        }
                        return TopoDS_Shape();
                    };
                    for (int v = 1; v <= edgesAt.Extent(); ++v) {
                        const TopTools_ListOfShape& around = edgesAt(v);
                        if (around.Extent() != 2) {
                            continue;
                        }
                        const TopoDS_Shape before = sideOn(spineEdges.FindIndex(around.First()));
                        const TopoDS_Shape after = sideOn(spineEdges.FindIndex(around.Last()));
                        if (before.IsNull() || after.IsNull()) {
                            continue;
                        }
                        TopTools_IndexedMapOfShape bounding;
                        TopExp::MapShapes(before, type, bounding);
                        for (TopExp_Explorer it(after, type); it.More(); it.Next()) {
                            if (bounding.Contains(it.Current())
                                && !sectionElements.Contains(it.Current())
                                && !ends.Contains(it.Current())) {
                                const int found = joints.FindIndex(it.Current());
                                if (found == 0) {
                                    joints.Add(it.Current());
                                    cornerAt.push_back(v);
                                    originOf.push_back(*origin);
                                    sidesOf.emplace_back(before, after);
                                    againstOf.push_back(against);
                                }
                                else if (distanceTo(edgesAt.FindKey(v), it.Current())
                                         < distanceTo(edgesAt.FindKey(cornerAt[found - 1]), it.Current())) {
                                    cornerAt[found - 1] = v;
                                }
                            }
                        }
                    }
                }
            }
        }
        // The vertices between the edges of one element's joint at one corner (a round hole's
        // bend arcs) that no profile vertex's sides meet at: joints of that element and corner,
        // told apart by their places too. Named from the two sides they lie on (`UPP`), they were
        // told apart in the order OCCT stores them, which follows the sweep's direction: with the
        // spine's first line drawn the other way, each went to its mirror vertex (round 8). Only
        // where the joint is split, in more than one edge: the vertices of a single joint edge
        // would name it (its connected elements) instead of its index, a name it has at a "Right
        // corner" but not at a "Round corner", where its far end is the round face's (a reference
        // broke when the corner was made round: PipeLegsRoundCorner, V2)
        const int edgeJoints = joints.Extent();
        auto split = [&](int j) {
            int edges = 0;
            for (int k = 1; k <= edgeJoints; ++k) {
                if (joints(k).ShapeType() == TopAbs_EDGE && cornerAt[k - 1] == cornerAt[j - 1]
                    && originOf[k - 1].IsSame(originOf[j - 1])) {
                    ++edges;
                }
            }
            return edges > 1;
        };
        for (int j = 1; j <= edgeJoints; ++j) {
            if (joints(j).ShapeType() != TopAbs_EDGE || !split(j)) {
                continue;
            }
            const int corner = cornerAt[j - 1];
            const TopoDS_Shape origin = originOf[j - 1];
            const std::pair<TopoDS_Shape, TopoDS_Shape> sides = sidesOf[j - 1];
            const bool against = againstOf[j - 1];
            for (TopExp_Explorer it(joints(j), TopAbs_VERTEX); it.More(); it.Next()) {
                if (!joints.Contains(it.Current()) && !sectionElements.Contains(it.Current())
                    && !ends.Contains(it.Current())) {
                    joints.Add(it.Current());
                    cornerAt.push_back(corner);
                    originOf.push_back(origin);
                    sidesOf.push_back(sides);
                    againstOf.push_back(against);
                }
            }
        }
        // The joints by (element, corner), the pairs in the order they were first found, and
        // each pair's joints by their places
        std::vector<int> groupOf(joints.Extent());
        std::vector<std::array<double, 4>> placeOf(joints.Extent());
        for (int j = 0; j < joints.Extent(); ++j) {
            groupOf[j] = j;
            for (int k = 0; k < j; ++k) {
                if (cornerAt[k] == cornerAt[j] && originOf[k].IsSame(originOf[j])) {
                    groupOf[j] = groupOf[k];
                    break;
                }
            }
            placeOf[j] = placeOn(joints(j + 1), sidesOf[j], againstOf[j]);
        }
        std::vector<int> order(joints.Extent());
        std::iota(order.begin(), order.end(), 0);
        std::ranges::stable_sort(order, {}, [&](int j) {
            return std::make_pair(groupOf[j], placeOf[j]);
        });
        for (int j : order) {
            bindCopy(originOf[j], joints(j + 1));
        }
        for (int j : order) {
            bindCopy(cornerOf(edgesAt.FindKey(cornerAt[j])), joints(j + 1));
        }
    }

    /// Whether the side faces the section's edge \a element sweeps run their u, the parameter
    /// along the section, against the edge's own parameter. The faces' u follows the direction
    /// of the sweep, which follows the spine's: a spine whose first line is drawn the other way
    /// is swept from its other end, its sides' u runs the other way round a profile's circle,
    /// and a round hole's bend arcs, told apart by their places, swapped with their mirror arcs
    /// (ops#415, round 8). It is read on \a element itself, at its middle, on the side face
    /// through it (the sweep passes through the profile wherever along the spine it lies): the
    /// surface's u direction there against the element's tangent. Read only where the shell's
    /// end copy lay on \a element, it was missed for a profile drawn along the spine, away from
    /// its ends, and the arcs swapped silently (round 9). Else where a side
    /// meets the section's copy at the shell's end that lies on \a element (one of \a ends): the
    /// copy's pcurve and its curve against \a element's. False where neither is found, or where
    /// the element doesn't run along u.
    static bool runsAgainst(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Edge& element,
        const TopTools_IndexedMapOfShape& ends
    )
    {
        double first = 0;
        double last = 0;
        Handle(Geom_Curve) curve = BRep_Tool::Curve(element, first, last);
        if (curve.IsNull()) {
            return false;
        }
        gp_Pnt middle;
        gp_Vec tangent;
        curve->D1((first + last) / 2, middle, tangent);
        // The side through the element: the nearest within the tolerances, or within 1e-4 mm
        // (MakePipeShell's default) for an approximated surface
        std::optional<bool> nearest;
        double nearestDistance = std::numeric_limits<double>::infinity();
        for (const TopoDS_Shape& side : pipe.Generated(element)) {
            if (side.ShapeType() != TopAbs_FACE || tangent.SquareMagnitude() == 0) {
                continue;
            }
            const TopoDS_Face& face = TopoDS::Face(side);
            Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
            if (surface.IsNull()) {
                continue;
            }
            double uFirst = 0;
            double uLast = 0;
            double vFirst = 0;
            double vLast = 0;
            BRepTools::UVBounds(face, uFirst, uLast, vFirst, vLast);
            GeomAPI_ProjectPointOnSurf onSide(middle, surface, uFirst, uLast, vFirst, vLast);
            const double tolerance = std::max(
                1e-4,
                BRep_Tool::Tolerance(face) + BRep_Tool::Tolerance(element)
            );
            if (onSide.NbPoints() == 0 || onSide.LowerDistance() > tolerance
                || onSide.LowerDistance() >= nearestDistance) {
                continue;
            }
            double u = 0;
            double v = 0;
            onSide.LowerDistanceParameters(u, v);
            gp_Pnt found;
            gp_Vec alongU;
            gp_Vec alongV;
            surface->D1(u, v, found, alongU, alongV);
            const double across = 0.7 * tangent.Magnitude() * alongU.Magnitude();
            if (alongU.SquareMagnitude() == 0 || std::abs(tangent.Dot(alongU)) <= across) {
                continue;
            }
            nearest = tangent.Dot(alongU) < 0;
            nearestDistance = onSide.LowerDistance();
        }
        if (nearest) {
            return *nearest;
        }
        for (const TopoDS_Shape& side : pipe.Generated(element)) {
            if (side.ShapeType() != TopAbs_FACE) {
                continue;
            }
            for (TopExp_Explorer it(side, TopAbs_EDGE); it.More(); it.Next()) {
                const TopoDS_Edge& copy = TopoDS::Edge(it.Current());
                if (!ends.Contains(copy)) {
                    continue;
                }
                double from = 0;
                double to = 0;
                Handle(Geom2d_Curve) pcurve
                    = BRep_Tool::CurveOnSurface(copy, TopoDS::Face(side), from, to);
                Handle(Geom_Curve) copied = BRep_Tool::Curve(copy, from, to);
                if (pcurve.IsNull() || copied.IsNull()) {
                    continue;
                }
                const double at = (from + to) / 2;
                gp_Pnt point;
                gp_Vec along;
                copied->D1(at, point, along);
                gp_Pnt2d uv;
                gp_Vec2d alongUV;
                pcurve->D1(at, uv, alongUV);
                GeomAPI_ProjectPointOnCurve onElement(point, curve, first, last);
                const double tolerance = BRep_Tool::Tolerance(copy) + BRep_Tool::Tolerance(element);
                if (onElement.NbPoints() == 0 || onElement.LowerDistance() > tolerance
                    || std::abs(alongUV.X()) <= std::abs(alongUV.Y())) {
                    continue;
                }
                gp_Pnt found;
                gp_Vec own;
                curve->D1(onElement.LowerDistanceParameter(), found, own);
                return (along.Dot(own) > 0) != (alongUV.X() > 0);
            }
        }
        return false;
    }

    /// Where \a joint lies on the two sides it bounds, \a sides, each in its own parameters: an
    /// edge at its pcurve's midpoint on a face, a vertex at its parameters on a face or on an
    /// edge. A face's u is taken into the face's range (a pcurve may lie a period away), and,
    /// when the sides run \a against the section's element (runsAgainst), turned round within
    /// it, so that it runs with the profile element's own parameter whichever way the spine is
    /// drawn. The
    /// parameters follow the profile's element along the side, so a rigid motion, a dimension
    /// edit or another platform leaves the joints' order alone. The smaller pair comes first, so
    /// the sides' order doesn't count; infinite where none is found.
    static std::array<double, 4> placeOn(
        const TopoDS_Shape& joint,
        const std::pair<TopoDS_Shape, TopoDS_Shape>& sides,
        bool against
    )
    {
        auto on = [&joint, against](const TopoDS_Shape& side) {
            constexpr double none = std::numeric_limits<double>::infinity();
            if (side.ShapeType() == TopAbs_FACE
                && (joint.ShapeType() == TopAbs_EDGE || joint.ShapeType() == TopAbs_VERTEX)) {
                const TopoDS_Face& face = TopoDS::Face(side);
                std::optional<gp_Pnt2d> at;
                if (joint.ShapeType() == TopAbs_VERTEX) {
                    at = BRep_Tool::Parameters(TopoDS::Vertex(joint), face);
                }
                else {
                    double first = 0;
                    double last = 0;
                    Handle(Geom2d_Curve) pcurve
                        = BRep_Tool::CurveOnSurface(TopoDS::Edge(joint), face, first, last);
                    if (!pcurve.IsNull()) {
                        at = pcurve->Value((first + last) / 2);
                    }
                }
                if (at) {
                    double uFirst = 0;
                    double uLast = 0;
                    double vFirst = 0;
                    double vLast = 0;
                    BRepTools::UVBounds(face, uFirst, uLast, vFirst, vLast);
                    Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
                    // Into the face's range again after turning round: a place on the seam
                    // stays at its start
                    auto inRange = [&](double u) {
                        return !surface.IsNull() && surface->IsUPeriodic()
                            ? ElCLib::InPeriod(u, uFirst, uFirst + surface->UPeriod())
                            : u;
                    };
                    double u = inRange(at->X());
                    if (against) {
                        u = inRange(uFirst + uLast - u);
                    }
                    return std::make_pair(u, at->Y());
                }
            }
            else if (joint.ShapeType() == TopAbs_VERTEX && side.ShapeType() == TopAbs_EDGE) {
                return std::make_pair(
                    BRep_Tool::Parameter(TopoDS::Vertex(joint), TopoDS::Edge(side)),
                    0.0
                );
            }
            return std::make_pair(none, none);
        };
        auto lower = on(sides.first);
        auto upper = on(sides.second);
        if (upper < lower) {
            std::swap(lower, upper);
        }
        return {lower.first, lower.second, upper.first, upper.second};
    }

    /// Places the faces the section's edge \a element makes round each Round corner (what the
    /// corner's spine vertex generated, CornerSource::rounds): each at the first place (placeOn,
    /// with \a against) of its edges on the element's sides along the corner's two legs. Such
    /// faces share their two sources (the element, the corner's second vertex) and are told
    /// apart by an index, which followed OCCT's order: a round hole's two round faces at a
    /// left-turning Round corner, and with them the edges and vertices named from them (`UPP`),
    /// went to their mirrors across the bend when the spine's first line was drawn the other way,
    /// silently (round 9). Faces with no such edge keep OCCT's order, after the others
    void placeRounds(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& element,
        bool against,
        const TopTools_IndexedDataMapOfShapeListOfShape& edgesAt,
        const std::vector<TopTools_IndexedMapOfShape>& legFaces
    )
    {
        constexpr double none = std::numeric_limits<double>::infinity();
        // A copy: Generated() refills one list each call
        const TopTools_ListOfShape made = pipe.Generated(element);
        for (int v = 1; v <= edgesAt.Extent(); ++v) {
            if (!rounded.Contains(edgesAt.FindKey(v)) || edgesAt(v).Extent() != 2) {
                continue;
            }
            std::vector<TopoDS_Shape> sides;
            for (const TopoDS_Shape& edge : edgesAt(v)) {
                const int leg = spineEdges.FindIndex(edge);
                for (const TopoDS_Shape& side : made) {
                    if (leg > 0 && side.ShapeType() == TopAbs_FACE
                        && legFaces[leg].Contains(side)) {
                        sides.push_back(side);
                    }
                }
            }
            TopTools_IndexedMapOfShape atCorner;
            for (const TopoDS_Shape& shape : pipe.Generated(edgesAt.FindKey(v))) {
                atCorner.Add(shape);
            }
            const int group = roundCorners++;
            for (const TopoDS_Shape& face : made) {
                if (face.ShapeType() != TopAbs_FACE || !atCorner.Contains(face)
                    || roundAt.IsBound(face)) {
                    continue;
                }
                std::array<double, 4> place {none, none, none, none};
                for (const TopoDS_Shape& side : sides) {
                    TopTools_IndexedMapOfShape sideEdges;
                    TopExp::MapShapes(side, TopAbs_EDGE, sideEdges);
                    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
                        if (sideEdges.Contains(it.Current())) {
                            place = std::min(place, placeOn(it.Current(), {side, side}, against));
                        }
                    }
                }
                roundAt.Bind(face, static_cast<int>(roundPlaces.size()));
                roundPlaces.emplace_back(group, place);
            }
        }
    }

    /// Puts the faces placeRounds placed in \a made in the order of their places, each corner's
    /// faces of one element among their own positions in the list, so that the others keep theirs
    void orderRounds(std::vector<TopoDS_Shape>& made) const
    {
        std::map<int, std::vector<std::size_t>> positions;
        for (std::size_t i = 0; i < made.size(); ++i) {
            if (const int* at = roundAt.Seek(made[i])) {
                positions[roundPlaces[*at].first].push_back(i);
            }
        }
        for (const auto& [group, at] : positions) {
            std::vector<TopoDS_Shape> members;
            for (std::size_t i : at) {
                members.push_back(made[i]);
            }
            std::ranges::stable_sort(members, {}, [this](const TopoDS_Shape& member) {
                return roundPlaces[roundAt.Find(member)].second;
            });
            for (std::size_t j = 0; j < at.size(); ++j) {
                made[at[j]] = members[j];
            }
        }
    }

    /// Adds \a copy to what \a key generates (copies), once
    void bindCopy(const TopoDS_Shape& key, const TopoDS_Shape& copy)
    {
        if (!copies.IsBound(key)) {
            copies.Bind(key, TopTools_ListOfShape());
        }
        TopTools_ListOfShape& bound = copies.ChangeFind(key);
        for (const TopoDS_Shape& found : bound) {
            if (found.IsSame(copy)) {
                return;
            }
        }
        bound.Append(copy);
    }

    /// Takes \a rounds (CornerSource::rounds): what each of their spine vertices generates becomes
    /// its second corner vertex's
    void useRounds(const TopTools_DataMapOfShapeShape& rounds)
    {
        for (TopTools_DataMapIteratorOfDataMapOfShapeShape it(rounds); it.More(); it.Next()) {
            roundsOf.Bind(it.Value(), it.Key());
            rounded.Add(it.Key());
        }
    }

    /// Takes \a spine's vertices and edges, and the edges \a sections' vertices sweep
    void useSpine(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& spine,
        const std::vector<TopoDS_Shape>& sections
    )
    {
        TopExp::MapShapes(spine, TopAbs_VERTEX, spineVertices);
        TopExp::MapShapes(spine, TopAbs_EDGE, spineEdges);
        // A section's element keeps what it sweeps, should a section share it with the spine
        for (const TopoDS_Shape& section : sections) {
            if (!section.IsNull()) {
                TopExp::MapShapes(section, sectionElements);
            }
        }
        for (int i = 1; i <= sectionElements.Extent(); ++i) {
            if (sectionElements(i).ShapeType() != TopAbs_VERTEX) {
                continue;
            }
            for (const TopoDS_Shape& element : pipe.Generated(sectionElements(i))) {
                if (element.ShapeType() == TopAbs_EDGE) {
                    laterals.Add(element);
                }
            }
        }
    }

    TopoDS_Shape point;
    TopTools_DataMapOfShapeListOfShape starts;
    TopTools_DataMapOfShapeListOfShape bound;
    TopTools_DataMapOfShapeListOfShape ends;
    TopTools_IndexedMapOfShape spineVertices;
    TopTools_IndexedMapOfShape spineEdges;
    TopTools_IndexedMapOfShape sectionElements;
    /// The edges the sections' vertices sweep
    TopTools_IndexedMapOfShape laterals;
    /// A piece's profile elements and the elements of its section swept from each
    TopTools_DataMapOfShapeListOfShape sweptFrom;
    /// The corners' vertices and the profile's elements, and the joints and the edges and vertices
    /// of the caps between pieces they generate (bindJoints, bindBreak)
    TopTools_DataMapOfShapeListOfShape copies;
    /// The spine's vertices and the corner source's vertices that name the joints there
    TopTools_DataMapOfShapeShape corners;
    /// The corner source's second vertices (CornerSource::rounds) and the spine's vertices whose
    /// generated elements they take
    TopTools_DataMapOfShapeShape roundsOf;
    TopTools_IndexedMapOfShape rounded;
    /// The faces placed at the Round corners (placeRounds), by their index in roundPlaces: each
    /// one's (corner, element) group, counted in roundCorners, and its place
    TopTools_DataMapOfShapeInteger roundAt;
    std::vector<std::pair<int, std::array<double, 4>>> roundPlaces;
    int roundCorners = 0;
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

/// The V2 name \a name with the tags of its sections, and of the names in them, left out: what
/// it says without the IDs of the objects that made it. Any other name as it is.
std::string withoutTags(const std::string& name)
{
    const Data::DecodedMappedName& decoded = Data::MappedName::getDecodedMappedName(name);
    if (decoded.empty()) {
        return name;
    }
    std::string result;
    for (Data::DecodedMappedSection section : decoded) {
        for (std::string& linked : section.linkedNames) {
            linked = withoutTags(linked);
        }
        for (std::string& connected : section.connectedElements) {
            connected = withoutTags(connected);
        }
        section.iterationTag = Data::EMPTY_VALUE;
        if (!result.empty()) {
            result += Data::NAME_SECTION_DELIMINATOR;
        }
        result += Data::MappedName::makeEncodedSection(section);
    }
    return result;
}

/// The tag of the V2 name \a name's last section, the object that made it; 0 for any other name
long lastTag(const std::string& name)
{
    const Data::DecodedMappedName& decoded = Data::MappedName::getDecodedMappedName(name);
    if (decoded.empty()) {
        return 0;
    }
    try {
        return std::stol(decoded.back().iterationTag);
    }
    catch (const std::exception&) {
        return 0;
    }
}

/// \a element's mapped name in \a path, in full (not interned), the first in text order without
/// tags when it has several (so object IDs don't choose); without one, its type's letter and index
/// (`E<n>`, `V<n>`)
std::string firstName(const Part::TopoShape& path, const TopoDS_Shape& element)
{
    const int index = path.findShape(element);
    const std::string& typeName = Part::TopoShape::shapeName(element.ShapeType());
    std::vector<std::string> names;
    if (index > 0) {
        for (const auto& [name, sids] :
             path.getElementMappedNames(Data::IndexedName::fromConst(typeName.c_str(), index))) {
            names.push_back(Data::NameTable::instance().toPlain(name.toString()));
        }
    }
    if (names.empty()) {
        return typeName.substr(0, 1) + std::to_string(index);
    }
    return *std::ranges::min_element(names, {}, [](const std::string& name) {
        return std::make_pair(withoutTags(name), name);
    });
}

/// \a text as one field of a key: its length, then itself, so no two lists of fields make one text
std::string field(const std::string& text)
{
    return std::to_string(text.size()) + ":" + text;
}

/// The 64-bit FNV-1a hash of \a text, in hex: short, and the same on every platform
std::string hashed(const std::string& text)
{
    std::uint64_t hash = 14695981039346656037ULL;
    for (const unsigned char c : text) {
        hash ^= c;
        hash *= 1099511628211ULL;
    }
    return fmt::format("{:016x}", hash);
}

/// The corners of a pipe's spine, its vertices between two of its edges, as a source of the
/// pipe's names (ops#415, round 5): a new vertex at each (its own TShape, so the spine's names
/// for its vertex don't join in), named by hand as a source is (a sketch's vertex): the V2
/// section `<key>;_;<tag>;PCV;0;V;0;SRC;_`, the tag the spine's object's (its first edge's last).
/// V1 has none (its names hold their objects' tags and string IDs, which a key can't leave out):
/// its joints are named from the spine's vertex, as before (decision 58). The key hashes the first mapped names of the two spine edges there, without
/// their tags, in text order, so it stays the same for one corner while the lines are moved,
/// drawn the other way, a segment is added before them or the bend between them straightens,
/// and differs between corners (work\415\r5\probe_key.py); the objects' IDs stay out of it as
/// they stay out of a name's text (the tag is masked where names are compared, the interned
/// scenarios' oracle). The spine's vertex is no such key: a sketch names it from its lines' ends
/// (`g1v2,g2v1`), which swap when the lines are drawn the other way, and its next corner's name
/// shares one of them (`g2v1,g3v2`): a joint's name went there at the solver's tier 1. A name of
/// one part shares nothing with the next corner's. Two edges from two objects are told apart by
/// the second's tag. Each part is length-prefixed (field), since a name's sections are separated by
/// `|`. Spines without names are keyed by the edges' indices.
/// A closed spine of one profile, outside Auxiliary mode, has a named start (\a namedStart: where
/// the sweep starts, the start vertex stored at the last good recompute, paired with the spine's
/// nearest vertex; on a new pipe the vertex nearest the profile), whose key has `start` added
/// (ops#469). So a closed spine of two edges, whose two vertices lie between the same edges, has
/// the start and the other corner whatever the edges' directions, and a profile moved to the
/// other vertex leaves both their keys: taken from the profile's place each time, the two keys
/// traded vertices (`notes\naming-class-B.md` 3, M1 (a)). Told apart by which
/// end of each edge they are, as drawn, both broke when one line was drawn the other way, and
/// swapped silently when both were (round 6; decision 122 (3)); so they still are without a named
/// start (several sections, Auxiliary mode: on the known-issues list).
/// Each corner has a second vertex, `<key>;_;<tag>;PCR;0;V;0;SRC;_`, the source of what OCCT
/// reports its spine vertex generated: a Round corner's round faces and sectors, and the lateral
/// arcs that bound them (ops#478). Named from the spine's vertex, a round face went to the other
/// bend at the solver's tier 1 when the lines were drawn the other way, by the shared part of the
/// vertex's name; from the joints' corner vertex, it would join their group (round 4).
struct CornerSource
{
    /// A compound of the corners' vertices, named
    Part::TopoShape shape;
    /// Each corner's spine vertex and its vertex in shape
    TopTools_DataMapOfShapeShape vertices;
    /// Each corner's spine vertex and its second vertex in shape, for what the spine vertex
    /// generates
    TopTools_DataMapOfShapeShape rounds;
    /// Each corner's spine vertex and its key
    std::vector<std::pair<TopoDS_Shape, std::string>> keys;

    /// The key of the corner at the spine's vertex \a vertex, empty when it is none
    std::string keyOf(const TopoDS_Shape& vertex) const
    {
        for (const auto& [corner, key] : keys) {
            if (corner.IsSame(vertex)) {
                return key;
            }
        }
        return {};
    }
};

/// The corners of \a path; \a shape is the feature's shape to name them in; \a namedStart: a
/// closed spine's named start, a vertex of \a path (null without one)
CornerSource makeCornerSource(
    const Part::TopoShape& path,
    Part::TopoShape shape,
    const TopoDS_Shape& namedStart
)
{
    CornerSource source;
    if (shape.getHistoryAlgorithm() != App::HistoryAlgorithm::V2) {
        return source;
    }
    TopTools_IndexedDataMapOfShapeListOfShape edgesAt;
    TopExp::MapShapesAndAncestors(path.getShape(), TopAbs_VERTEX, TopAbs_EDGE, edgesAt);
    const bool closed = BRep_Tool::IsClosed(path.getShape());
    // Per corner, the tag its name carries; which end of each of its two edges (in the key's
    // order) it is, for a closed spine without a named start; and the names its key holds with
    // their tags
    std::vector<long> tags;
    std::vector<std::string> endsOf;
    std::vector<std::string> taggedNames;
    for (int v = 1; v <= edgesAt.Extent(); ++v) {
        TopTools_IndexedMapOfShape around;
        for (const TopoDS_Shape& edge : edgesAt(v)) {
            around.Add(edge);
        }
        if (around.Extent() != 2) {
            continue;
        }
        const TopoDS_Shape& vertex = edgesAt.FindKey(v);
        // Name without tags, tag, end (`s`tart or `e`nd, as the edge is drawn), name
        std::array<std::tuple<std::string, long, char, std::string>, 2> edges;
        for (int i = 0; i < 2; ++i) {
            const TopoDS_Edge& edge = TopoDS::Edge(around(i + 1));
            const std::string name = firstName(path, edge);
            const char end = TopExp::LastVertex(edge).IsSame(vertex) ? 'e' : 's';
            edges[i] = {withoutTags(name), lastTag(name), end, name};
        }
        std::ranges::sort(edges);
        const auto& [name0, tag0, end0, tagged0] = edges[0];
        const auto& [name1, tag1, end1, tagged1] = edges[1];
        std::string key = field(name0) + field(name1);
        if (tag1 != tag0) {
            key += field(std::to_string(tag1));
        }
        if (vertex.IsSame(namedStart)) {
            key += field("start");
        }
        source.keys.emplace_back(vertex, key);
        tags.push_back(tag0);
        endsOf.push_back(
            closed && namedStart.IsNull() ? field(std::string {end0, end1}) : std::string()
        );
        taggedNames.push_back(field(tagged0) + field(tagged1));
    }
    // Corners with the same key and tag (they'd have one name) get \a suffixes, each its own,
    // counted on the keys as they were, so no corner's key depends on the others' order
    auto tellApart = [&source, &tags](const std::vector<std::string>& suffixes) {
        const auto keys = source.keys;
        for (size_t i = 0; i < keys.size(); ++i) {
            for (size_t j = 0; j < keys.size(); ++j) {
                if (j != i && keys[j].second == keys[i].second && tags[j] == tags[i]) {
                    source.keys[i].second += suffixes[i];
                    break;
                }
            }
        }
    };
    // A closed spine of two edges without a named start (several sections, Auxiliary mode) has
    // two corners between them alike: which end of each edge the corner is tells them apart
    // (round 6), so one line drawn the other way breaks both (loud) and both drawn the other way
    // swap them (silent). Corners still alike lie between edges whose names differ only by their
    // tags (copies of one object): the tagged names tell them apart.
    tellApart(endsOf);
    tellApart(taggedNames);
    if (source.keys.empty()) {
        return source;
    }
    TopoDS_Compound compound;
    BRep_Builder builder;
    builder.MakeCompound(compound);
    for (const auto& [vertex, key] : source.keys) {
        const TopoDS_Vertex corner
            = BRepBuilderAPI_MakeVertex(BRep_Tool::Pnt(TopoDS::Vertex(vertex))).Vertex();
        builder.Add(compound, corner);
        source.vertices.Bind(vertex, corner);
        const TopoDS_Vertex round
            = BRepBuilderAPI_MakeVertex(BRep_Tool::Pnt(TopoDS::Vertex(vertex))).Vertex();
        builder.Add(compound, round);
        source.rounds.Bind(vertex, round);
    }
    shape.setShape(compound);
    for (size_t i = 0; i < source.keys.size(); ++i) {
        auto& [vertex, key] = source.keys[i];
        key = hashed(key);
        for (const auto& [op, of] :
             {std::pair {"PCV", &source.vertices}, std::pair {"PCR", &source.rounds}}) {
            shape.setElementName(
                Data::IndexedName::fromConst("Vertex", shape.findShape(of->Find(vertex))),
                Data::MappedName(Data::MappedName::makeEncodedSection(
                    {key},
                    {},
                    static_cast<int>(tags[i]),
                    op,
                    0,
                    'V',
                    0,
                    {Data::MAPPER_FLAG_SOURCE}
                )),
                shape.Tag
            );
        }
    }
    source.shape = shape;
    return source;
}

/// \a name marked with \a marker (`<name>;<marker>;...;MOD`), for an element of type \a type
Data::MappedName marked(const Data::MappedName& name, const std::string& marker, char type, long tag)
{
    Data::MappedName result = name;
    result.append(Data::NAME_SECTION_DELIMINATOR);
    result.append(
        Data::MappedName::makeEncodedSection(
            {},
            {},
            static_cast<int>(tag),
            marker.c_str(),
            0,
            type,
            0,
            {Data::MAPPER_FLAG_MODIFIED},
            {}
        )
            .c_str()
    );
    return result;
}

/// Marks the faces, edges and vertices the fuse of the union's pieces made, those of \a fused that
/// none of \a solids has, with the marker of the nearest break (\a breaks: the place and marker
/// of each, `PCU<key>`, the key of the break's corner, CornerSource), each of their names the
/// fuse gave them itself (`FUS`, not modified from a piece's). The fuse names them from the side
/// faces and vertices around them, the same at whichever corner the break is: the crease where
/// two pieces cut each other, its vertices, and the pieces of the faces in the planes both legs
/// share took the new break's when an edit moved it, and a reference went there with no warning
/// (ops#379, round 5). Marked, a reference to one goes missing then. Keyed by the spine vertex's
/// index, as they were in round 5, they moved with a segment added at the spine's start; marked
/// by their first name only, a fuse's own name behind another stayed unmarked (round 6, F3).
void markWhatTheFuseMade(
    Part::TopoShape& fused,
    const std::vector<Part::TopoShape>& solids,
    const std::vector<std::pair<gp_Pnt, std::string>>& breaks
)
{
    if (breaks.empty()) {
        return;
    }
    // What the fuse names itself, from the elements around it: one it only cut (a side face
    // trimmed where the other piece covers it) is named modified from its leg's, and follows
    // it; marked, a reference to it went missing when the pipe went back below 90 degrees
    auto ownName = [](const Data::MappedName& name) {
        const Data::DecodedMappedName& decoded = name.getDecodedMappedName();
        return !decoded.empty() && decoded.back().opCode == Part::OpCodes::Fuse
            && !decoded.back().hasMapperFlag(Data::MAPPER_FLAG_MODIFIED);
    };
    for (TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        TopTools_IndexedMapOfShape kept;
        for (const Part::TopoShape& solid : solids) {
            TopExp::MapShapes(solid.getShape(), type, kept);
        }
        const std::string& typeName = Part::TopoShape::shapeName(type);
        const int count = static_cast<int>(fused.countSubShapes(type));
        for (int k = 1; k <= count; ++k) {
            const TopoDS_Shape made = fused.getSubShape(type, k);
            if (kept.Contains(made)) {
                continue;
            }
            const Data::IndexedName element = Data::IndexedName::fromConst(typeName.c_str(), k);
            const auto names = fused.getElementMappedNames(element);
            if (std::ranges::none_of(names, [&](const auto& named) { return ownName(named.first); })) {
                continue;
            }
            gp_Pnt at;
            if (type == TopAbs_VERTEX) {
                at = BRep_Tool::Pnt(TopoDS::Vertex(made));
            }
            else {
                GProp_GProps props;
                if (type == TopAbs_FACE) {
                    BRepGProp::SurfaceProperties(made, props);
                }
                else {
                    BRepGProp::LinearProperties(made, props);
                }
                at = props.CentreOfMass();
            }
            const auto nearest
                = std::ranges::min_element(breaks, {}, [&at](const auto& place) {
                      return at.Distance(place.first);
                  });
            bool overwrite = true;
            for (const auto& [name, sids] : names) {
                fused.setElementName(
                    element,
                    ownName(name) ? marked(name, nearest->second, typeName[0], fused.Tag) : name,
                    fused.Tag,
                    &sids,
                    overwrite
                );
                overwrite = false;
            }
        }
    }
}

/// The union past 90 degrees: \a spine cut into pieces at \a pieceStarts, each piece swept with
/// "Transformed" (\a setup) from where the one before ends, closed with its caps and made a
/// solid, and the pieces fused. \a profiles are the sections the first piece starts from, one
/// per wire of the profile; \a make makes a shape named as this feature's. A null shape when a
/// piece isn't a valid solid (the profile folds over itself within it: a tight curve after a
/// corner of nearly 90 degrees, which no union mends); an exception when OCCT can't fuse the
/// pieces. \a namedStart: as makeCornerSource's.
/// Each later piece's section is added at the piece's first vertex: added plainly, a section
/// that doesn't lie on the piece's start plane (a profile behind the spine's start) was placed
/// where it lies nearest the piece, and the union came out wrong.
/// Names: the first piece's start keeps the profile's names, and the last piece's end projects
/// them, as the one sweep's ends do, so a reference to either end follows it when an edit takes
/// the pipe across 90 degrees. With \a profileAtEnd the two swap, as the one sweep's do when
/// its end carries the profile's names (ops#379): the first piece's start projects them, and the
/// last piece's end keeps them. Each piece's sources are the profile, \a spine, the path with
/// its names, and its corners, as the one sweep's (ops#415): its side faces and edges are named
/// from the profile's elements and their spine edges, the names the one sweep gives them, and
/// the edges where they meet (`UPP`) from those. The other pieces' ends aren't named from their
/// sections: the edges and vertices of a cap between pieces are generated from the corner at the
/// break and the profile's element each is a copy of (MapperPipeShellEnds), and the caps are told
/// apart as a piece's front (`PCF`) or back (`PCB`); what the fuse makes there is marked with
/// that corner's key (markWhatTheFuseMade). So every name at a break holds its corner:
/// one taken at a corner can't go to another when an edit moves the break, adds a segment before
/// it or draws the spine the other way. Keyed by the spine vertex's index, as they were (ops#379,
/// rounds 4 and 5), they moved with a segment added at the start; named from the side faces
/// alone (ops#415, round 1), a cap edge had the same name at either end of its leg.
Part::TopoShape sweepPiecesAndFuse(
    const Part::TopoShape& path,
    const std::vector<size_t>& pieceStarts,
    std::vector<Part::TopoShape> profiles,
    bool profileAtEnd,
    const TopoDS_Shape& namedStart,
    const std::function<void(BRepOffsetAPI_MakePipeShell&)>& setup,
    const std::function<Part::TopoShape(const TopoDS_Shape&)>& make
)
{
    const TopoDS_Wire spine = TopoDS::Wire(path.getShape());
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

    const CornerSource corners = makeCornerSource(path, make(TopoDS_Shape()), namedStart);
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
        std::vector<Part::TopoShape> aheads;
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
                pieces[index],
                first && profileAtEnd,
                end,
                first ? nullptr : &origins[i],
                first ? TopoDS_Shape() : pieceFirsts[index],
                last ? TopoDS_Shape() : pieceFirsts[index + 1],
                corners.vertices,
                corners.rounds
            );
            std::vector<Part::TopoShape> pieceSources {profiles[i], path};
            if (!corners.shape.isNull()) {
                pieceSources.push_back(corners.shape);
            }
            shell.makeShapeWithElementMap(built, mapper, pieceSources, Part::OpCodes::PipeShell);
            // In the section's order, not the map's (ops#479)
            TopTools_DataMapOfShapeShape next;
            TopTools_IndexedMapOfShape elements;
            TopExp::MapShapes(section.getShape(), elements);
            for (int k = 1; k <= elements.Extent(); ++k) {
                const TopTools_ListOfShape* found = mapper.endsOf().Seek(elements(k));
                if (!found) {
                    continue;
                }
                const TopoDS_Shape* origin = origins[i].Seek(elements(k));
                for (const TopoDS_Shape& element : *found) {
                    next.Bind(element, origin ? *origin : elements(k));
                }
            }
            Part::TopoShape ahead = make(mkPS.LastShape());
            ahead.mapSubElement(shell);
            origins[i] = next;
            Part::TopoShape front = make(mkPS.FirstShape());
            front.mapSubElement(shell);
            Part::TopoShape back = make(mkPS.LastShape());
            back.mapSubElement(shell);
            shells.push_back(shell);
            fronts.push_back(front);
            backs.push_back(back);
            aheads.push_back(ahead);
        }

        BRepBuilderAPI_Sewing sewer;
        sewer.SetTolerance(Precision::Confusion());
        for (const Part::TopoShape& shell : shells) {
            sewer.Add(shell.getShape());
        }
        // The pipe's own ends are named from their edges by the sewing, as the one sweep's; a cap
        // between pieces is named before, from its edges (which hold the break's corner),
        // the front and back told apart
        std::vector<Part::TopoShape> sources = shells;
        Part::TopoShape frontface;
        Part::TopoShape backface;
        if (first) {
            frontface.makeElementFace(fronts);
        }
        else {
            frontface = make(TopoDS_Shape());
            frontface.makeElementFace(fronts, "PCF");
            sources.push_back(frontface);
        }
        if (last) {
            backface.makeElementFace(backs, Part::OpCodes::Sewing);
        }
        else {
            backface = make(TopoDS_Shape());
            backface.makeElementFace(backs, "PCB");
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
        sections = aheads;
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
    if (fused.getHistoryAlgorithm() == App::HistoryAlgorithm::V2) {
        std::vector<std::pair<gp_Pnt, std::string>> breaks;
        for (size_t index = 1; index < pieces.size(); ++index) {
            breaks.emplace_back(
                BRep_Tool::Pnt(pieceFirsts[index]),
                "PCU" + corners.keyOf(pieceFirsts[index])
            );
        }
        markWhatTheFuseMade(fused, solids, breaks);
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

/// Binormal mode's binormal as the sweep gets it, in the pipe's own frame (\a pipe, its
/// Placement): the property is in the Body's coordinates, where the spine and the profile are
/// seen, and the sweep runs in the frame of the profile sketch's or the base feature's placement
/// (ops#458). None for a zero vector.
std::optional<gp_Dir> sweptBinormal(const Base::Vector3d& inBody, const TopLoc_Location& pipe)
{
    gp_Vec direction(inBody.x, inBody.y, inBody.z);
    if (direction.Magnitude() < gp::Resolution()) {
        return std::nullopt;
    }
    direction.Transform(pipe.Inverted().Transformation());
    return gp_Dir(direction);
}

/// Where Binormal mode's sections go wrong along a spine (binormalFolds)
struct BinormalFold
{
    enum class Kind
    {
        /// The spine's tangent runs along the binormal where the spine starts
        startSingular,
        /// It runs along the binormal further on: the section turns half a turn there at once
        cusp,
        /// At a corner where the section takes the law's frame again, that frame turns it nearer
        /// half a turn than none about the spine's tangent, beyond the corner's own turn
        cornerFlip,
        /// Every point of the section moves backwards through its plane
        turnBack,
        /// Some points of the section move backwards through its plane
        fold,
        /// Nothing found, but stretches where e turns more than the places resolve were left as
        /// sampled: the budget of halvings ran out first
        unchecked,
        /// An edge of a kind of curve whose turn of e the check can't bound (TurnBound), such as
        /// an offset curve: nothing else is looked for
        unbounded
    };
    Kind kind;
    /// Where on the spine: the first such place, or the largest fold's
    gp_Pnt at;
    /// The smallest angle between the spine's tangent and the binormal's line (degrees)
    double degrees;
    /// A fold's reach past the line where the section turns back, and its extent across that line
    Reach reach;
    /// A corner flip's turn of the section about the spine's tangent (cornerTwist, degrees)
    double twist;
    /// How many stretches were left unchecked (unchecked)
    int unchecked = 0;
};

/// How far Binormal mode's frame (e, B x e, B) turns the section about the spine's tangent at a
/// corner from \a into to \a out, beyond the corner's own turn (radians, 0 to pi), where "Right
/// corner" and "Round corner" give it the law's axis \a next in place of \a previous (e on either
/// side, square to \a b): the angle between B x previous carried round the corner (the shortest
/// turn from into to out) and B x next, both square to out. A spine in a plane square to B has
/// e = the tangent, and no such turn at any corner (a miter, ops#406 review pr380-r2); the corner
/// of (0, 0, 0), (10, 0, 10), (0, 0, 20) with B = Z turns it half a turn (e from +X to -X, where
/// the tangent turns 90 degrees). At a hairpin, with no shortest turn, e reversing counts as half
/// a turn.
double cornerTwist(
    const gp_Vec& into,
    const gp_Vec& out,
    const gp_Vec& b,
    const gp_Vec& previous,
    const gp_Vec& next
)
{
    if (into.Angle(out) > std::numbers::pi - tiltTolerance) {
        return previous.Dot(next) < 0 ? std::numbers::pi : 0;
    }
    const gp_Vec carried = gp_Quaternion(into, out).Multiply(b.Crossed(previous));
    return carried.Angle(b.Crossed(next));
}

/// \a n choose \a k, as a double (the degrees here stay under 100)
double binomial(int n, int k)
{
    double value = 1;
    for (int i = 1; i <= k; ++i) {
        value = value * (n - k + i) / i;
    }
    return value;
}

/// A bound on how far e, the spine's tangent made square to the binormal B, turns along a stretch
/// of an edge (radians). With q any vector along the tangent made square to B, e turns by the
/// integral of |q x q'| / |q|^2, at most sup |q x q'| / inf |q|^2 and sup |q'| / inf |q| over the
/// stretch, for the stretch's own parameter from 0 to 1 (decision 162; ops#406 cloud review of
/// 828d0d5f28, S1': a turn estimated at a stretch's three places missed two near-touches placed
/// symmetrically about its middle).
/// - Bezier and B-spline edges, cut into Bezier pieces: q comes from the hodograph (for a rational
///   piece, N'w - Nw', N the weighted poles' polynomial and w the weights'), cut to the stretch.
///   The convex hull of a polynomial's control points holds it: sup |q'| and sup |q x q'| are at
///   most their largest control point, and inf |q| at least the least extent of q's control
///   points along their sum. Where that reaches the origin there's no bound.
/// - Circles, ellipses, hyperbolas and parabolas: q x q' is constant along them, sup |q'| has a
///   closed form, and inf |q| is at least |q| at the middle less half the stretch times sup |q'|.
/// - Lines: e doesn't turn.
/// - Other curves (an offset curve, say): no bound (bounded() is false).
class TurnBound
{
public:
    TurnBound(const BRepAdaptor_Curve& curve, const gp_Vec& binormal)
        : b(binormal.XYZ())
    {
        try {
            setUp(curve);
        }
        catch (const Standard_Failure&) {
            kind = Kind::none;
        }
    }

    bool bounded() const
    {
        return kind != Kind::none;
    }

    /// The bound between the curve's parameters \a u0 and \a u1, infinite where there's none, and
    /// zero where the tangent runs along B throughout (e is undefined there, as in squareAxis)
    double operator()(double u0, double u1) const
    {
        const double low = std::min(u0, u1);
        const double high = std::max(u0, u1);
        switch (kind) {
            case Kind::line:
                return 0;
            case Kind::pieces:
                return acrossPieces(low, high);
            case Kind::ellipse:
            case Kind::hyperbola:
            case Kind::parabola:
                return acrossConic(low, high);
            case Kind::none:
                break;
        }
        return std::numeric_limits<double>::infinity();
    }

private:
    enum class Kind
    {
        none,
        line,
        pieces,
        ellipse,
        hyperbola,
        parabola
    };

    gp_XYZ square(const gp_XYZ& v) const
    {
        return v - b * v.Dot(b);
    }

    void setUp(const BRepAdaptor_Curve& curve)
    {
        switch (curve.GetType()) {
            case GeomAbs_Line:
                kind = Kind::line;
                return;
            case GeomAbs_BezierCurve:
                breaks = {0, 1};
                pieces.push_back(hodograph(*curve.Bezier()));
                kind = Kind::pieces;
                break;
            case GeomAbs_BSplineCurve: {
                GeomConvert_BSplineCurveToBezierCurve split(
                    curve.BSpline(),
                    curve.FirstParameter(),
                    curve.LastParameter(),
                    Precision::PConfusion()
                );
                NCollection_Array1<double> knots(1, split.NbArcs() + 1);
                split.Knots(knots);
                for (int i = 1; i <= split.NbArcs(); ++i) {
                    pieces.push_back(hodograph(*split.Arc(i)));
                }
                for (int i = knots.Lower(); i <= knots.Upper(); ++i) {
                    breaks.push_back(knots(i));
                }
                kind = Kind::pieces;
                break;
            }
            // q = x f(u) + y g(u), x and y the conic's axes, scaled, made square to B
            case GeomAbs_Circle: {
                const gp_Circ circle = curve.Circle();
                setConic(Kind::ellipse, circle.Position(), circle.Radius(), circle.Radius());
                return;
            }
            case GeomAbs_Ellipse: {
                const gp_Elips ellipse = curve.Ellipse();
                setConic(
                    Kind::ellipse,
                    ellipse.Position(),
                    ellipse.MajorRadius(),
                    ellipse.MinorRadius()
                );
                return;
            }
            case GeomAbs_Hyperbola: {
                const gp_Hypr hyperbola = curve.Hyperbola();
                setConic(
                    Kind::hyperbola,
                    hyperbola.Position(),
                    hyperbola.MajorRadius(),
                    hyperbola.MinorRadius()
                );
                return;
            }
            case GeomAbs_Parabola: {
                const gp_Parab parabola = curve.Parabola();
                setConic(Kind::parabola, parabola.Position(), 1 / (2 * parabola.Focal()), 1);
                return;
            }
            default:
                return;
        }
        // The pieces must give the edge's own tangent, in its own place and parameters: where
        // they don't (a curve OCCT hands over transformed or cut differently), no bound. Inside
        // the pieces, away from knots, where a C0 curve's tangent depends on the side.
        const size_t middle = pieces.size() / 2;
        for (const double u : {curve.FirstParameter(),
                               (breaks[middle] + breaks[middle + 1]) / 2,
                               curve.LastParameter()}) {
            gp_Pnt point;
            gp_Vec tangent;
            curve.D1(u, point, tangent);
            const gp_XYZ along = tangentAt(u);
            if (tangent.Magnitude() > gp::Resolution() && along.Modulus() > gp::Resolution()
                && tangent.Angle(gp_Vec(along)) > 1e-6) {
                kind = Kind::none;
                return;
            }
        }
    }

    void setConic(Kind conic, const gp_Ax2& axes, double alongX, double alongY)
    {
        kind = conic;
        x = square(axes.XDirection().XYZ() * alongX);
        y = square(axes.YDirection().XYZ() * alongY);
        cross = std::abs(x.Crossed(y).Dot(b));
    }

    /// A Bezier curve's hodograph, or for a rational one N'w - Nw', along its tangent
    static std::vector<gp_XYZ> hodograph(const Geom_BezierCurve& bezier)
    {
        const int n = bezier.Degree();
        std::vector<gp_XYZ> along;
        if (!bezier.IsRational()) {
            for (int i = 1; i <= n; ++i) {
                along.push_back(bezier.Pole(i + 1).XYZ() - bezier.Pole(i).XYZ());
            }
            return along;
        }
        // N' (degree n - 1) times w (degree n), less N times w', in Bernstein form of degree
        // 2n - 1 (the factor n dropped)
        along.assign(2 * n, gp_XYZ());
        for (int i = 0; i < n; ++i) {
            const gp_XYZ rise = bezier.Pole(i + 2).XYZ() * bezier.Weight(i + 2)
                - bezier.Pole(i + 1).XYZ() * bezier.Weight(i + 1);
            const double weightRise = bezier.Weight(i + 2) - bezier.Weight(i + 1);
            for (int j = 0; j <= n; ++j) {
                const double factor = binomial(n - 1, i) * binomial(n, j)
                    / binomial(2 * n - 1, i + j);
                const gp_XYZ weighted = bezier.Pole(j + 1).XYZ() * bezier.Weight(j + 1);
                along[i + j] += (rise * bezier.Weight(j + 1) - weighted * weightRise) * factor;
            }
        }
        return along;
    }

    /// The control points of a polynomial in Bernstein form cut to its parameters [s0, s1] of
    /// [0, 1] (de Casteljau)
    static std::vector<gp_XYZ> cut(std::vector<gp_XYZ> points, double s0, double s1)
    {
        const size_t n = points.size();
        if (s1 < 1) {
            for (size_t r = 1; r < n; ++r) {
                for (size_t i = n - 1; i >= r; --i) {
                    points[i] = points[i - 1] * (1 - s1) + points[i] * s1;
                }
            }
        }
        if (s0 > 0) {
            const double t = s0 / s1;
            for (size_t r = 1; r < n; ++r) {
                for (size_t i = 0; i + r < n; ++i) {
                    points[i] = points[i] * (1 - t) + points[i + 1] * t;
                }
            }
        }
        return points;
    }

    /// The pieces' vector along the tangent at the curve's parameter \a u (de Casteljau)
    gp_XYZ tangentAt(double u) const
    {
        const size_t i = pieceAt(u);
        const double s = std::clamp((u - breaks[i]) / (breaks[i + 1] - breaks[i]), 0.0, 1.0);
        std::vector<gp_XYZ> points = pieces[i];
        for (size_t r = points.size() - 1; r > 0; --r) {
            for (size_t k = 0; k < r; ++k) {
                points[k] = points[k] * (1 - s) + points[k + 1] * s;
            }
        }
        return points.front();
    }

    size_t pieceAt(double u) const
    {
        const auto after = std::upper_bound(breaks.begin(), breaks.end(), u);
        const size_t i = after == breaks.begin() ? 0 : size_t(after - breaks.begin()) - 1;
        return std::min(i, pieces.size() - 1);
    }

    /// Across several pieces (a look over a run of spans), e's jumps at the knots between them
    /// count too: none where the curve is G1 there
    double acrossPieces(double low, double high) const
    {
        double total = 0;
        const size_t start = pieceAt(low);
        for (size_t i = start; i < pieces.size() && breaks[i] < high; ++i) {
            const double from = std::max(low, breaks[i]);
            const double to = std::min(high, breaks[i + 1]);
            if (i > start) {
                const gp_XYZ into = square(pieces[i - 1].back());
                const gp_XYZ out = square(pieces[i].front());
                if (into.Modulus() <= gp::Resolution() || out.Modulus() <= gp::Resolution()) {
                    return std::numeric_limits<double>::infinity();
                }
                total += gp_Vec(into).Angle(gp_Vec(out));
            }
            if (to <= from) {
                continue;
            }
            const double span = breaks[i + 1] - breaks[i];
            total += onPiece(pieces[i], (from - breaks[i]) / span, (to - breaks[i]) / span);
        }
        return total;
    }

    double onPiece(const std::vector<gp_XYZ>& piece, double s0, double s1) const
    {
        const std::vector<gp_XYZ> points = cut(piece, s0, s1);
        std::vector<gp_XYZ> q;
        gp_XYZ sum;
        double widest = 0;
        double alongLeast = std::numeric_limits<double>::infinity();
        bool above = false;
        bool below = false;
        for (const gp_XYZ& point : points) {
            const double along = point.Dot(b);
            q.push_back(point - b * along);
            sum += q.back();
            widest = std::max(widest, q.back().Modulus());
            alongLeast = std::min(alongLeast, std::abs(along));
            above = above || along > 0;
            below = below || along < 0;
        }
        // The tangent within squareAxis' angle of B throughout, one way along it: e is undefined
        // there
        if (!(above && below) && widest < std::sin(1e-6) * alongLeast) {
            return 0;
        }
        const double length = sum.Modulus();
        if (length <= 0) {
            return std::numeric_limits<double>::infinity();
        }
        double shortest = std::numeric_limits<double>::infinity();
        for (const gp_XYZ& one : q) {
            shortest = std::min(shortest, one.Dot(sum) / length);
        }
        if (shortest <= 0) {
            return std::numeric_limits<double>::infinity();
        }
        const int degree = int(q.size()) - 1;
        double rate = 0;
        for (int i = 0; i < degree; ++i) {
            rate = std::max(rate, (q[i + 1] - q[i]).Modulus() * degree);
        }
        // q x q' along B, of degree 2 degree - 1
        std::vector<double> rows;
        for (int i = 0; i <= degree; ++i) {
            rows.push_back(binomial(degree, i));
        }
        std::vector<double> lower;
        for (int j = 0; j < degree; ++j) {
            lower.push_back(binomial(degree - 1, j));
        }
        double turning = 0;
        double whole = 1;  // binomial(2 degree - 1, l)
        for (int l = 0; l < 2 * degree; ++l) {
            if (l > 0) {
                whole = whole * (2 * degree - l) / l;
            }
            double coefficient = 0;
            for (int i = std::max(0, l - degree + 1); i <= std::min(l, degree); ++i) {
                const int j = l - i;
                coefficient += rows[i] * lower[j] * q[i].Crossed(q[j + 1] - q[j]).Dot(b);
            }
            turning = std::max(turning, std::abs(coefficient) * degree / whole);
        }
        return std::min(rate / shortest, turning / (shortest * shortest));
    }

    double acrossConic(double low, double high) const
    {
        const double middle = (low + high) / 2;
        const double half = (high - low) / 2;
        gp_XYZ q;
        double rate = 0;
        switch (kind) {
            case Kind::ellipse:
                q = x * -std::sin(middle) + y * std::cos(middle);
                rate = x.Modulus() + y.Modulus();
                break;
            case Kind::hyperbola:
                q = x * std::sinh(middle) + y * std::cosh(middle);
                rate = std::cosh(std::max(std::abs(low), std::abs(high)))
                    * (x.Modulus() + y.Modulus());
                break;
            default:
                q = x * middle + y;
                rate = x.Modulus();
                break;
        }
        const double shortest = q.Modulus() - half * rate;
        if (shortest <= 0) {
            return std::numeric_limits<double>::infinity();
        }
        return 2 * half * std::min(rate / shortest, cross / (shortest * shortest));
    }

    gp_XYZ b;
    Kind kind = Kind::none;
    /// Bezier pieces of the curve, from breaks[i] to breaks[i + 1], by their vectors along the
    /// tangent's control points
    std::vector<double> breaks;
    std::vector<std::vector<gp_XYZ>> pieces;
    /// A conic's q = x f(u) + y g(u), and |q x q'| along B, constant along it
    gp_XYZ x;
    gp_XYZ y;
    double cross = 0;
};

/// What Binormal mode (\a binormal) does wrong along \a spine, none when it does nothing wrong.
/// OCCT's law (GeomFill_ConstantBiNormal) carries the profile rigidly in the frame (e, B x e, B),
/// e the spine's tangent C' made square to the binormal B (measured, ops#406): every section lies
/// in a plane through B and keeps its normal's parts (alpha, beta, gamma) on that frame.
/// - Where the tangent runs along B, e is undefined, and where it passes B, e reverses: the
///   section turns half a turn about B at once and the pipe crosses itself (a cusp), for any
///   profile. No law of this mode avoids it: a frame that kept B x e continuous would run the
///   section backwards through its own plane instead. A tangent that only touches B keeps e on
///   both sides and sweeps correctly; one that reaches B at the spine's end or at a corner counts.
/// - A point of the section at (t, n) in the frame where the spine starts moves through the
///   section's plane at s = alpha v' + gamma (C'.B) + k' v' (beta t - alpha n), v' the length of
///   e's vector and k' the signed curvature of the spine's projection on the plane square to B.
///   Where s is negative for every point of the section (\a points, in the plane of \a normal,
///   where the sweep starts it) the pipe runs back through itself; where it is negative for some
///   points only, the section folds over itself, by the reach it has past the line where s is 0.
///
/// Without \a points only the cusps are looked for. With \a pastCorners false the section's
/// motion is followed only up to the first corner: "Transformed" tilts the section there, and
/// measureCorners measures what follows. A corner itself is measured there too. With it true
/// (Right and Round corner) the section takes the law's frame again after a corner, so a corner
/// where that frame turns it more than a quarter turn about the spine's tangent beyond the
/// corner's own turn (cornerTwist), nearer half a turn than none, fails there (cornerFlip). A
/// sharp corner of a spine in a plane square to B doesn't: e is the tangent. The places: 8 in
/// each C2 piece of a curve (16 to 1024) and 2 in each span of a B-spline (in each run of spans
/// past 2^16 of them, 2^17 at most), each interval halved
/// while e turns more than 2 degrees through its middle, or TurnBound can't keep e's turn across
/// it under 2 degrees (a swing of e within the interval that leaves its ends alike), 2^20
/// halvings for each edge (about 5800 turns of e); past them, while e turns more than 45
/// degrees, 2^20 more for the whole spine, so that e turning steadily round a long helix never
/// reads as a reversal (ops#406 review pr380-r3: a 300-turn helix failed as a cusp), and e
/// reversing still finds the cusp. Where the fold check had to leave stretches turning more than
/// 2 degrees and finds nothing, it says how many (unchecked), so the result isn't silent. An edge
/// TurnBound can't bound (an offset curve) is all it says (unbounded).
/// BRepCheck passes all of these pipes.
std::optional<BinormalFold> binormalFolds(
    const TopoDS_Wire& spine,
    const gp_Dir& binormal,
    const std::vector<gp_Pnt>& points,
    const std::optional<gp_Dir>& normal,
    bool pastCorners
)
{
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    if (edges.empty()) {
        return std::nullopt;
    }
    const gp_Vec b(binormal);
    std::vector<TurnBound> bounds;
    for (const TopoDS_Edge& edge : edges) {
        bounds.emplace_back(BRepAdaptor_Curve(edge), b);
        if (!bounds.back().bounded()) {
            return BinormalFold {
                BinormalFold::Kind::unbounded,
                BRep_Tool::Pnt(TopExp::FirstVertex(edge, true)),
                90,
                {},
                0
            };
        }
    }
    double closest = 90;
    auto degreesFromLine = [&](const gp_Vec& tangent) {
        const double cosine = std::min(1.0, std::abs(tangent.Dot(b)) / tangent.Magnitude());
        return std::acos(cosine) * 180 / std::numbers::pi;
    };
    // e: the tangent made square to the binormal, none where the tangent runs along it
    auto squareAxis = [&](const gp_Vec& tangent) -> std::optional<gp_Vec> {
        const gp_Vec square = tangent - b * tangent.Dot(b);
        if (square.Magnitude() < std::sin(1e-6) * tangent.Magnitude()) {
            return std::nullopt;
        }
        return square.Normalized();
    };

    // The frame where the spine starts, the section's coordinates in it, and its normal's parts
    const TopoDS_Edge& firstEdge = edges.front();
    const BRepAdaptor_Curve firstCurve(firstEdge);
    const bool firstReversed = firstEdge.Orientation() == TopAbs_REVERSED;
    gp_Pnt origin;
    gp_Vec startTangent;
    firstCurve.D1(
        firstReversed ? firstCurve.LastParameter() : firstCurve.FirstParameter(),
        origin,
        startTangent
    );
    if (firstReversed) {
        startTangent.Reverse();
    }
    if (startTangent.Magnitude() < gp::Resolution()) {
        return std::nullopt;
    }
    const std::optional<gp_Vec> e0 = squareAxis(startTangent);
    if (!e0) {
        return BinormalFold {
            BinormalFold::Kind::startSingular,
            origin,
            degreesFromLine(startTangent),
            {},
            0
        };
    }
    const gp_Vec n0 = b.Crossed(*e0);
    std::vector<std::pair<double, double>> local;
    double alpha = 0;
    double beta = 0;
    double gamma = 0;
    // A section facing backwards along the spine moves the other way through its plane
    double side = 1;
    bool follow = normal && !points.empty();
    if (follow) {
        for (const gp_Pnt& point : points) {
            const gp_Vec offset(origin, point);
            local.emplace_back(offset.Dot(*e0), offset.Dot(n0));
        }
        const gp_Vec m(*normal);
        alpha = m.Dot(*e0);
        beta = m.Dot(n0);
        gamma = m.Dot(b);
        side = m.Dot(startTangent) < 0 ? -1 : 1;
    }

    std::optional<gp_Pnt> cusp;
    std::optional<gp_Pnt> flip;
    double flipTwist = 0;
    // Where e was last undefined, until the next place where it is defined tells a pass from a touch
    std::optional<gp_Pnt> along;
    std::optional<gp_Pnt> back;
    std::optional<gp_Pnt> foldAt;
    Reach worst;
    std::optional<gp_Vec> previous = e0;
    // Halvings while e turns more than maxTurn, for each edge: a long edge before can't leave a
    // later one coarse (ops#406 review pr380-r4, "ellipse_after_helix")
    constexpr int budget = 1 << 20;
    constexpr double maxTurn = 2 * std::numbers::pi / 180;
    // Past the budget, places still come at most this far apart in e, so that e turning steadily
    // (a long helix) never reads as e reversing; up to a second budget, for the whole spine
    int coarseHalvings = 0;
    constexpr int coarseBudget = 1 << 20;
    constexpr double coarseTurn = std::numbers::pi / 4;
    // Stretches the fold check had to leave turning more than maxTurn, and the first of them
    int unchecked = 0;
    std::optional<gp_Pnt> uncheckedAt;
    constexpr double still = 1e-9;  // an edge-on end (s = 0 exactly) sweeps correctly
    for (size_t k = 0; k < edges.size(); ++k) {
        const TopoDS_Edge& edge = edges[k];
        const gp_Vec into = k > 0 ? gp_Vec(tangentAlong(edges[k - 1], false)) : gp_Vec();
        const gp_Vec out(tangentAlong(edge, true));
        if (k > 0 && into.Angle(out) > tiltTolerance) {
            // A corner: e jumps there, and corners are measureCorners'
            if (along && !cusp) {
                cusp = along;
            }
            along.reset();
            const std::optional<gp_Vec> next = squareAxis(out);
            if (pastCorners && previous && next && !flip) {
                const double twist = cornerTwist(into, out, b, *previous, *next);
                if (twist > std::numbers::pi / 2) {
                    flip = BRep_Tool::Pnt(TopExp::LastVertex(edges[k - 1], true));
                    flipTwist = twist * 180 / std::numbers::pi;
                }
            }
            previous.reset();
            follow = follow && pastCorners;
        }
        const BRepAdaptor_Curve curve(edge);
        const bool reversed = edge.Orientation() == TopAbs_REVERSED;
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        // t from 0 to 1 the way the wire runs
        auto parameter = [&](double t) {
            return reversed ? last - t * (last - first) : first + t * (last - first);
        };
        // e at t
        auto axisAt = [&](double t) -> std::optional<gp_Vec> {
            gp_Pnt point;
            gp_Vec tangent;
            curve.D1(parameter(t), point, tangent);
            if (tangent.Magnitude() < gp::Resolution()) {
                return std::nullopt;
            }
            return squareAxis(reversed ? tangent.Reversed() : tangent);
        };
        const TurnBound& bound = bounds[k];
        const bool line = isLine(edge);
        // Where the looks start (t): 8 in each C2 piece (16 to 1024), and 2 in each span of a
        // B-spline, so that a short stretch of a long C2 curve isn't left inside one look (ops#406
        // review pr380-r4, "wiggle_spline"); past 2^16 spans, 2 in each run of k spans, k the
        // fewest that keeps 2^16 runs at most (review pr380-r5, "wiggle_many_spans": none there
        // left a 77499-span curve's wiggle inside one look)
        std::vector<double> starts {0};
        if (!line) {
            const int even = std::clamp(8 * curve.NbIntervals(GeomAbs_C2), 16, 1024);
            for (int i = 1; i < even; ++i) {
                starts.push_back(static_cast<double>(i) / even);
            }
            const int spans = curve.NbIntervals(GeomAbs_CN);
            if (spans > 1) {
                constexpr int runs = 1 << 16;
                const int run = (spans + runs - 1) / runs;
                NCollection_Array1<double> knots(1, spans + 1);
                curve.Intervals(knots, GeomAbs_CN);
                for (int i = 1; i <= spans; i += run) {
                    const double end = knots(std::min(i + run, spans + 1));
                    for (const double u : {knots(i), (knots(i) + end) / 2}) {
                        const double t = (u - first) / (last - first);
                        starts.push_back(std::clamp(reversed ? 1 - t : t, 0.0, 1.0));
                    }
                }
            }
            std::sort(starts.begin(), starts.end());
            starts.erase(
                std::unique(
                    starts.begin(),
                    starts.end(),
                    [](double one, double other) { return other - one < 1e-12; }
                ),
                starts.end()
            );
            while (starts.size() > 1 && starts.back() > 1 - 1e-12) {
                starts.pop_back();
            }
        }
        starts.push_back(1);
        int halvings = 0;
        std::vector<double> places;
        for (size_t i = 0; i + 1 < starts.size(); ++i) {
            std::vector<std::pair<double, double>> stack {{starts[i], starts[i + 1]}};
            while (!stack.empty()) {
                const auto [from, to] = stack.back();
                stack.pop_back();
                const double middle = (from + to) / 2;
                // e's turn through the middle; where e is undefined at some of the three, the
                // edge of that is looked for
                const std::optional<gp_Vec> before = axisAt(from);
                const std::optional<gp_Vec> centre = line ? before : axisAt(middle);
                const std::optional<gp_Vec> after = axisAt(to);
                const int defined = int(before.has_value()) + int(centre.has_value())
                    + int(after.has_value());
                double turn = defined == 3 ? before->Angle(*centre) + centre->Angle(*after)
                                           : (defined == 0 ? 0 : std::numbers::pi);
                // ...and at least what e may turn within the stretch, which leaves the three
                // alike where e swings away and back between them (ops#406 cloud reviews of
                // 9234832ed3, S1, and 828d0d5f28, S1': near-touches of B between two looks, and
                // two placed symmetrically about a look's middle, folded unseen). Zero where the
                // tangent runs along B throughout, where e is undefined. Not needed where the
                // stretch is halved anyway.
                if (!line && !(turn > maxTurn && halvings < budget)) {
                    turn = std::max(turn, bound(parameter(from), parameter(to)));
                }
                const bool fine = turn > maxTurn && halvings < budget;
                const bool coarse = turn > coarseTurn && coarseHalvings < coarseBudget;
                if ((fine || coarse) && !line && to - from > 1e-12) {
                    ++(fine ? halvings : coarseHalvings);
                    stack.emplace_back(middle, to);
                    stack.emplace_back(from, middle);
                }
                else {
                    if (follow && turn > maxTurn && !line && to - from > 1e-12) {
                        ++unchecked;
                        if (!uncheckedAt) {
                            uncheckedAt = curve.Value(parameter(from));
                        }
                    }
                    places.push_back(from);
                }
            }
        }
        places.push_back(1);

        for (const double t : places) {
            gp_Pnt point;
            gp_Vec d1;
            gp_Vec d2;
            curve.D2(parameter(t), point, d1, d2);
            if (reversed) {
                d1.Reverse();
            }
            const double speed = d1.Magnitude();
            if (speed < gp::Resolution()) {
                continue;
            }
            closest = std::min(closest, degreesFromLine(d1));
            const std::optional<gp_Vec> e = squareAxis(d1);
            if (!e) {
                if (!along) {
                    along = point;
                }
                continue;
            }
            // Undefined right after a corner counts like at the spine's start
            if ((previous && e->Dot(*previous) < 0) || (along && !previous)) {
                if (!cusp) {
                    cusp = along ? *along : point;
                }
                previous = e;
                along.reset();
                continue;
            }
            along.reset();
            previous = e;
            if (!follow) {
                continue;
            }
            const double square = (d1 - b * d1.Dot(b)).Magnitude();
            const gp_Vec bend = d2 - b * d2.Dot(b);
            const double curvature = e->Crossed(bend).Dot(b) / (square * square);
            const double s0 = alpha * square + gamma * d1.Dot(b);
            const double gt = curvature * square * beta;
            const double gn = -curvature * square * alpha;
            double low = std::numeric_limits<double>::infinity();
            double high = -low;
            for (const auto& [onE, onN] : local) {
                const double s = side * (s0 + gt * onE + gn * onN) / speed;
                low = std::min(low, s);
                high = std::max(high, s);
            }
            const double slope = std::hypot(gt, gn) / speed;
            if (high < -still) {
                if (!back) {
                    back = point;
                }
            }
            else if (low < -still && slope > gp::Resolution()) {
                const double past = std::min(-low, high) / slope;
                if (past > worst.past) {
                    worst.past = past;
                    worst.across = (high - low) / slope;
                    foldAt = point;
                }
            }
        }
    }
    // A closed spine's end joins its start: a corner there is measured like the others (ops#406
    // cloud review of 9234832ed3, L1: the joint from the last edge to the first went unchecked).
    // Closed as sharpestCorner takes it, by its vertices, not by distance: a vertex
    // whose tolerance spans the gap closes it too (cloud review of 828d0d5f28, L3).
    const TopoDS_Vertex endVertex = TopExp::LastVertex(edges.back(), true);
    if (!endVertex.IsNull() && endVertex.IsSame(TopExp::FirstVertex(edges.front(), true))) {
        const gp_Pnt end = BRep_Tool::Pnt(endVertex);
        const gp_Vec into(tangentAlong(edges.back(), false));
        const gp_Vec out(tangentAlong(edges.front(), true));
        if (into.Angle(out) > tiltTolerance) {
            if (along && !cusp) {
                cusp = along;
            }
            along.reset();
            if (pastCorners && previous && !flip) {
                const double twist = cornerTwist(into, out, b, *previous, *e0);
                if (twist > std::numbers::pi / 2) {
                    flip = end;
                    flipTwist = twist * 180 / std::numbers::pi;
                }
            }
        }
    }
    if (along && !cusp) {
        cusp = along;
    }
    if (cusp) {
        return BinormalFold {BinormalFold::Kind::cusp, *cusp, closest, {}, 0};
    }
    if (flip) {
        return BinormalFold {BinormalFold::Kind::cornerFlip, *flip, closest, {}, flipTwist};
    }
    if (back) {
        return BinormalFold {BinormalFold::Kind::turnBack, *back, closest, {}, 0};
    }
    if (foldAt) {
        return BinormalFold {BinormalFold::Kind::fold, *foldAt, closest, worst, 0};
    }
    if (uncheckedAt) {
        return BinormalFold {
            BinormalFold::Kind::unchecked,
            *uncheckedAt,
            closest,
            {},
            0,
            unchecked
        };
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

/// The point of \a edge halfway along its parameter: a closed spine's stored way (SpineEnds)
gp_Pnt middleOf(const TopoDS_Edge& edge)
{
    const BRepAdaptor_Curve curve(edge);
    return curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
}

/// \a edges, those of \a path in a new order and orientation, made a wire as \a wire with their
/// names, or with \a names[k] for the edge k where it is given (its vertices' names kept); null
/// when it doesn't run through them in that order
Part::TopoShape wireAlong(
    const Part::TopoShape& path,
    const std::vector<TopoDS_Edge>& edges,
    Part::TopoShape wire,
    const std::vector<Data::MappedName>& names = {}
)
{
    std::vector<Part::TopoShape> named;
    for (size_t k = 0; k < edges.size(); ++k) {
        const int index = path.findShape(edges[k]);
        if (index <= 0) {
            return {};
        }
        named.push_back(path.getSubTopoShape(TopAbs_EDGE, index));
        named.back().setShape(edges[k], false);
        if (k < names.size() && names[k]) {
            // A new shape, with a map of its own (a sub-shape's may be the cache's): the edge's
            // new name, and its vertices' names as they were
            const Part::TopoShape& old = named.back();
            Part::TopoShape renamed(edges[k], old.Tag, old.Hasher, old.getHistoryAlgorithm());
            renamed.setElementName(Data::IndexedName::fromConst("Edge", 1), names[k], old.Tag);
            for (int v = 1; v <= static_cast<int>(old.countSubShapes(TopAbs_VERTEX)); ++v) {
                const int at = renamed.findShape(old.getSubShape(TopAbs_VERTEX, v));
                if (at <= 0) {
                    continue;
                }
                for (const auto& [name, sids] :
                     old.getElementMappedNames(Data::IndexedName::fromConst("Vertex", v))) {
                    renamed.setElementName(
                        Data::IndexedName::fromConst("Vertex", at),
                        name,
                        old.Tag,
                        &sids
                    );
                }
            }
            named.back() = renamed;
        }
    }
    wire.makeElementWires(named);
    if (wire.isNull() || wire.getShape().ShapeType() != TopAbs_WIRE) {
        return {};
    }
    auto startOf = [](const TopoDS_Edge& edge) {
        return BRep_Tool::Pnt(TopExp::FirstVertex(edge, true));
    };
    const std::vector<TopoDS_Edge> along = edgesInOrder(TopoDS::Wire(wire.getShape()));
    if (along.size() != edges.size()) {
        return {};
    }
    for (size_t k = 0; k < edges.size(); ++k) {
        if (startOf(along[k]).Distance(startOf(edges[k])) > Precision::Confusion()) {
            return {};
        }
    }
    return wire;
}

/// How far \a stored and \a middles, a closed spine's stored vertices (the start first) and its
/// edges' middles (startNearest), lie from \a edges (the spine's, in its order) started at the
/// vertex \a k and run \a forward (in the edges' order) or the other way, beyond one
/// translation: the root mean square of the pairs' displacements about their mean. Of as many
/// points as edges
double fromStoredAlong(
    const std::vector<gp_Pnt>& stored,
    const std::vector<gp_Pnt>& middles,
    const std::vector<TopoDS_Edge>& edges,
    size_t k,
    bool forward
)
{
    const size_t n = edges.size();
    auto startOf = [&edges, n](size_t at) {
        return BRep_Tool::Pnt(TopExp::FirstVertex(edges[at % n], true));
    };
    std::vector<gp_Vec> moves;
    for (size_t i = 0; i < n; ++i) {
        const size_t at = forward ? k + i : k + n - i;
        const size_t along = forward ? (k + i) % n : (k + 2 * n - 1 - i) % n;
        moves.emplace_back(stored[i], startOf(at));
        moves.emplace_back(middles[i], middleOf(edges[along]));
    }
    gp_Vec mean;
    for (const gp_Vec& move : moves) {
        mean += move;
    }
    mean /= static_cast<double>(moves.size());
    double sum = 0;
    for (const gp_Vec& move : moves) {
        sum += (move - mean).SquareMagnitude();
    }
    return std::sqrt(sum / static_cast<double>(moves.size()));
}

/// fromStoredAlong at the start \a k in either direction, the less; with another number of edges,
/// the stored start's distance alone
double fromStoredAt(
    const std::vector<gp_Pnt>& stored,
    const std::vector<gp_Pnt>& middles,
    const std::vector<TopoDS_Edge>& edges,
    size_t k
)
{
    const size_t n = edges.size();
    if (stored.size() != n || middles.size() != n) {
        return stored.front().Distance(BRep_Tool::Pnt(TopExp::FirstVertex(edges[k % n], true)));
    }
    return std::min(
        fromStoredAlong(stored, middles, edges, k, true),
        fromStoredAlong(stored, middles, edges, k, false)
    );
}

/// The start and the way (forward: in \a edges' order) where fromStoredAlong's fit of \a stored
/// and \a middles is least, where it is least by more than the rounding; none otherwise, or with
/// another number of points than edges
std::optional<std::pair<size_t, bool>> bestFitOf(
    const std::vector<gp_Pnt>& stored,
    const std::vector<gp_Pnt>& middles,
    const std::vector<TopoDS_Edge>& edges
)
{
    const size_t n = edges.size();
    if (n < 2 || stored.size() != n || middles.size() != n) {
        return std::nullopt;
    }
    std::optional<std::pair<size_t, bool>> best;
    double least = std::numeric_limits<double>::infinity();
    double next = least;
    for (size_t k = 0; k < n; ++k) {
        for (const bool forward : {true, false}) {
            const double residual = fromStoredAlong(stored, middles, edges, k, forward);
            if (residual < least) {
                next = least;
                least = residual;
                best = std::make_pair(k, forward);
            }
            else if (residual < next) {
                next = residual;
            }
        }
    }
    if (next - least <= Precision::Confusion()) {
        return std::nullopt;
    }
    return best;
}

/// Whether startNearest's fit (fromStoredAt) pairs \a stored and \a middles with \a edges, the
/// spine's, clearly: the least residual over the starts small beside the stored loop's size (the
/// root mean square distance of its vertices from their middle) and clearly below the next
/// start's (decision 171). A loop turned while something else changes in the same recompute
/// (a line moved, a face profile stretched) lies in no stored frame, and read in the body, its
/// best start was the vertex a translation fits least badly: the start moved to another corner
/// with the profile's names, silently (the post-push review of fork PR 383 round 5, T-A). A turn
/// leaves a residual of the order of the loop's size at every start (measured, the ring turned
/// 30 to 150 degrees: 0.37 to 1.0 of the size, 0.36 to 1.0 of the next start's); a line moved
/// by d, about d / 2.3 at the right start (a leg of the 30 x 20 ring moved by 4: 0.1 of the
/// size). A turn by the loop's own symmetry fits a translation exactly; the caller doesn't read the
/// fit where a frame of the profile turned (decision 180). True with nothing stored
bool fitIsClear(
    const std::vector<gp_Pnt>& stored,
    const std::vector<gp_Pnt>& middles,
    const std::vector<TopoDS_Edge>& edges
)
{
    constexpr double ofSize = 0.25;
    constexpr double ofNext = 0.5;
    const size_t n = edges.size();
    if (stored.empty() || n < 2) {
        return true;
    }
    gp_XYZ middle(0, 0, 0);
    for (const gp_Pnt& point : stored) {
        middle += point.XYZ();
    }
    middle /= static_cast<double>(stored.size());
    double spread = 0;
    for (const gp_Pnt& point : stored) {
        spread += point.SquareDistance(gp_Pnt(middle));
    }
    const double size = std::sqrt(spread / static_cast<double>(stored.size()));
    std::vector<double> residuals;
    for (size_t k = 0; k < n; ++k) {
        residuals.push_back(fromStoredAt(stored, middles, edges, k));
    }
    std::ranges::sort(residuals);
    return residuals[0] <= ofSize * size && residuals[0] <= ofNext * residuals[1];
}

/// \a path, a closed spine of more than one edge, restarted at its stored start, or on a new pipe
/// at its vertex nearest \a profile (the mean of the distances from the profile's vertices): its
/// edges in the same direction, rotated in its order, made a wire as \a wire with their names
/// (ops#469). The shell starts where the spine does, and its start keeps the profile's names;
/// built from the sketch's first line, the start followed that line's direction, and a line drawn
/// the other way moved the profile's names to the spine's other vertex, silently (the closed
/// spine's two ends tie, so the stored side can't keep them, ops#379). \a stored: the spine's
/// vertices at the last good recompute, its start first, then in the sweep's order, and \a
/// middles: its edges' middles (middleOf) in that order. They are paired with the spine's as a
/// whole, from the start (in either direction) where the pairs' displacements differ least from
/// one translation (their root mean square about their mean), so a spine moved whole keeps its
/// start: paired by the start alone, a closed spine of two edges moved by more than half the
/// distance between its vertices took the other vertex as its start, and the corners' keys passed
/// between them (the cloud reading review of fork PR 383, F1); by the distances' sum, two
/// vertices moved along their line by the distance between them tie. With another number of
/// edges than stored, the vertex nearest the stored start. The start is stored, not taken from the profile each time: a profile
/// moved along a leg past its middle moved the start to the leg's other vertex, and the profile's
/// names with it, to the elements there, silently, though the solid hadn't changed (the review of
/// fork PR 383, round 1). Starts that tie fall to the profile's place, and a tie left (a new
/// pipe's profile halfway along a leg) to the first of them in the wire's order, which is then
/// stored. \a path itself when it isn't such a spine, when it already starts there, or when the
/// new wire doesn't start there.
// anchor: rung 4 (the stored vertices), seeded by rung 3 (the profile's place)
Part::TopoShape startNearest(
    const Part::TopoShape& path,
    const TopoDS_Shape& profile,
    const Part::TopoShape& wire,
    const std::vector<gp_Pnt>& stored,
    const std::vector<gp_Pnt>& middles
)
{
    if (path.isNull() || path.getShape().ShapeType() != TopAbs_WIRE || profile.IsNull()) {
        return path;
    }
    const std::vector<TopoDS_Edge> edges = edgesInOrder(TopoDS::Wire(path.getShape()));
    TopTools_IndexedMapOfShape vertices;
    TopExp::MapShapes(profile, TopAbs_VERTEX, vertices);
    if (edges.size() < 2 || !BRep_Tool::IsClosed(path.getShape()) || vertices.IsEmpty()) {
        return path;
    }
    const size_t n = edges.size();
    auto startOf = [&edges, n](size_t k) {
        return BRep_Tool::Pnt(TopExp::FirstVertex(edges[k % n], true));
    };
    auto fromProfile = [&](size_t k) {
        double sum = 0;
        for (int i = 1; i <= vertices.Extent(); ++i) {
            sum += startOf(k).Distance(BRep_Tool::Pnt(TopoDS::Vertex(vertices(i))));
        }
        return sum / vertices.Extent();
    };
    // How far the stored vertices and middles lie from the spine's, started at the vertex k
    // (fromStoredAt; the caller reads them only where the fit is clear, fitIsClear)
    auto fromStored = [&](size_t k) {
        return fromStoredAt(stored, middles, edges, k);
    };
    // The edges, of \a candidates, whose starts lie nearest by \a distance
    auto nearestBy = [](const std::vector<size_t>& candidates, const auto& distance) {
        double least = std::numeric_limits<double>::infinity();
        for (size_t k : candidates) {
            least = std::min(least, distance(k));
        }
        std::vector<size_t> nearest;
        for (size_t k : candidates) {
            if (distance(k) < least + Precision::Confusion()) {
                nearest.push_back(k);
            }
        }
        return nearest;
    };
    std::vector<size_t> tied(n);
    std::iota(tied.begin(), tied.end(), size_t {0});
    if (!stored.empty()) {
        tied = nearestBy(tied, fromStored);
    }
    if (tied.size() > 1) {
        tied = nearestBy(tied, fromProfile);
    }
    const size_t nearest = tied.front();
    if (nearest == 0) {
        return path;
    }
    std::vector<TopoDS_Edge> rotated;
    for (size_t k = 0; k < n; ++k) {
        rotated.push_back(edges[(nearest + k) % n]);
    }
    const Part::TopoShape restarted = wireAlong(path, rotated, wire);
    if (restarted.isNull()) {
        FC_WARN("Pipe: the closed spine could not be restarted at its start; it is swept as drawn");
        return path;
    }
    return restarted;
}

/// \a path, a closed spine of more than one edge, run one way chosen from the profile, from the
/// same start (ops#469): the way whose first edge leaves the start more nearly along the normal of
/// the profile's plane, \a normal (either sense), so the profile lies across the first leg; where
/// both edges leave alike (or the profile has no plane), the way in which MakePipeShell puts the
/// profile itself at the shell's start (\a profileAtStart, a trial sweep). Run the way the sketch
/// draws it, a closed spine's solid followed the lines' directions with "Transformed", which
/// shears the section at the corners after the start in the order it meets them: the closed D
/// drawn the other way came out 201.38 instead of 221.38 mm^3, silently. And the sweep places the
/// profile where it lies nearest the spine, which at a closed spine's start is both the wire's
/// first and last parameter: when it takes the last, the shell starts with the profile turned to
/// the first edge's tangent (where the spine has a corner there), and the profile's names went to
/// that turned copy. Both ways leave alike within a band of 1e-6 of the cosine, not only where
/// the two computed cosines are equal: in a symmetric spine (a lens) they differ by rounding,
/// which an arc drawn the other way changes. Inside the band the way stored decides (\a stored, a
/// point of the first edge at the last good recompute: the way whose first edge passes nearer
/// it), then the trial sweep. \a path itself when it isn't such a spine or already runs the
/// chosen way.
// anchor: rung 3 (the profile's normal); a tie falls to rung 4 (the stored way)
Part::TopoShape profileFirst(
    const Part::TopoShape& path,
    const std::optional<gp_Dir>& normal,
    const std::function<bool(const TopoDS_Wire&)>& profileAtStart,
    const Part::TopoShape& wire,
    const std::optional<gp_Pnt>& stored
)
{
    if (path.isNull() || path.getShape().ShapeType() != TopAbs_WIRE
        || !BRep_Tool::IsClosed(path.getShape())) {
        return path;
    }
    const std::vector<TopoDS_Edge> edges = edgesInOrder(TopoDS::Wire(path.getShape()));
    if (edges.size() < 2) {
        return path;
    }
    std::vector<TopoDS_Edge> back;
    for (auto it = edges.rbegin(); it != edges.rend(); ++it) {
        back.push_back(TopoDS::Edge(it->Reversed()));
    }
    // How nearly an edge leaves the start along the profile's normal
    auto across = [&normal](const TopoDS_Edge& edge) {
        return std::abs(tangentAlong(edge, true).Dot(*normal));
    };
    constexpr double band = 1e-6;
    // How far the stored point lies from an edge's middle
    auto fromStored = [&stored](const TopoDS_Edge& edge) {
        return stored->Distance(middleOf(edge));
    };
    bool turn = false;
    if (normal && across(back.front()) > across(edges.front()) + band) {
        turn = true;
    }
    else if (normal && across(edges.front()) > across(back.front()) + band) {
        return path;
    }
    else if (stored
             && fromStored(back.front()) + Precision::Confusion() < fromStored(edges.front())) {
        turn = true;
    }
    else if (stored
             && fromStored(edges.front()) + Precision::Confusion() < fromStored(back.front())) {
        return path;
    }
    else if (profileAtStart(TopoDS::Wire(path.getShape()))) {
        return path;
    }
    const Part::TopoShape reversed = wireAlong(path, back, wire);
    if (reversed.isNull()) {
        if (turn) {
            FC_WARN("Pipe: the closed spine could not be run the other way; it is swept as drawn");
        }
        return path;
    }
    if (!(turn || profileAtStart(TopoDS::Wire(reversed.getShape())))) {
        return path;
    }
    return reversed;
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
        "Binormal vector for corresponding orientation mode, in the Body's coordinates"
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
    ADD_PROPERTY_TYPE(
        SpineEndsOf,
        (),
        "Sweep",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden),
        "The input SpineEnds was stored for: the spine's object and its elements' names"
    );
    ADD_PROPERTY_TYPE(
        SpineStart,
        (),
        "Sweep",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden),
        "A closed spine's start at the last successful recompute of it, with its way, its end and "
        "its other vertices and edges, where they lie in the body: the next recompute of a closed "
        "spine of the same input starts there (ops#469)"
    );
    ADD_PROPERTY_TYPE(
        SpineStartOf,
        (),
        "Sweep",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden),
        "The input SpineStart was stored for: the spine's object and its elements' names"
    );
    ADD_PROPERTY_TYPE(
        EarlierSpineStarts,
        (),
        "Sweep",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden),
        "SpineStart's records for the last earlier inputs of the spine, so that a spine set back "
        "to one of them starts where it did (ops#469)"
    );
    ADD_PROPERTY_TYPE(
        EarlierSpineStartsOf,
        (),
        "Sweep",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden),
        "The inputs EarlierSpineStarts was stored for, each followed by an empty string"
    );
    ADD_PROPERTY_TYPE(
        SpineStartNames,
        (),
        "Sweep",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden),
        "The name of the line at each place of SpineStart: a leg whose line came from another "
        "place is renamed (ops#469)"
    );
    ADD_PROPERTY_TYPE(
        EarlierSpineStartNames,
        (),
        "Sweep",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden),
        "SpineStartNames of EarlierSpineStarts' records, each followed by an empty string"
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

namespace
{
/// The spine's input, which the stored ends and start are kept for (SpineEndsOf, SpineStartOf):
/// \a object's name, `*` when the spine is the whole object (no \a subs), then the mapped names
/// in \a shape (its shape) of the edges the spine uses, sorted: \a subs, or with none every edge
/// of the shape. Compared by sameInput. Named with the index the refresh writes in the link, a
/// sketch's line deleted renumbered the input in the recompute that refreshed it; with the spine
/// moved in the same one, nothing matched the stored start, and the start was taken from the
/// profile again (the cloud reading review of fork PR 383 round 3, F2). An edge without a mapped
/// name is named by its index.
std::vector<std::string> spineIdentity(
    const App::DocumentObject* object,
    const Part::TopoShape& shape,
    const std::vector<std::string>& subs
)
{
    std::vector<std::string> edges;
    // A sub in the mapped style (`;g3;SKT.Edge3`, from a script) by its index part: with the
    // index kept in it, a renumber changed the input (the pre-push review of round 4)
    auto add = [&](const std::string& sub) {
        const std::string indexed = Data::oldElementName(sub.c_str());
        const Data::MappedName mapped = shape.getMappedName(Data::IndexedName(indexed.c_str()));
        edges.push_back(mapped ? mapped.toString() : indexed);
    };
    if (subs.empty()) {
        for (int i = 1; i <= static_cast<int>(shape.countSubShapes(TopAbs_EDGE)); ++i) {
            add("Edge" + std::to_string(i));
        }
    }
    for (const std::string& sub : subs) {
        add(sub);
    }
    std::ranges::sort(edges);
    std::vector<std::string> identity;
    identity.emplace_back(object && object->getNameInDocument() ? object->getNameInDocument() : "");
    if (subs.empty()) {
        identity.emplace_back("*");
    }
    identity.insert(identity.end(), edges.begin(), edges.end());
    return identity;
}

/// The edges' names of \a identity (spineIdentity), without its object and mark
std::vector<std::string> identityEdges(const std::vector<std::string>& identity)
{
    auto first = identity.begin() + std::min<long>(1, static_cast<long>(identity.size()));
    if (first != identity.end() && *first == "*") {
        ++first;
    }
    return {first, identity.end()};
}

/// Whether \a a and \a b (spineIdentity) are one input: the same object, and both the whole of it
/// or the same edges, in another order, listed or whole, and renumbered. The whole object is one
/// input whatever its edges: a sketch redrawn (its line deleted and drawn again, ops#379's spine
/// edits) keeps its stored ends and start, as before the input was stored (ops#435)
bool sameInput(const std::vector<std::string>& a, const std::vector<std::string>& b)
{
    if (a.empty() || b.empty() || a.front() != b.front()) {
        return false;
    }
    const bool wholeA = a.size() > 1 && a[1] == "*";
    const bool wholeB = b.size() > 1 && b[1] == "*";
    return (wholeA && wholeB) || identityEdges(a) == identityEdges(b);
}

/// A closed spine's stored start (SpineStart's form), the input it was stored for, and the names
/// of the lines at its places (SpineStartNames; empty when not stored)
struct StartRecord
{
    std::vector<std::string> of;
    std::vector<Base::Vector3d> points;
    std::vector<std::string> names;
};

/// The records of \a current (SpineStart, SpineStartOf, SpineStartNames) and of \a earlier
/// (EarlierSpineStarts, EarlierSpineStartsOf, EarlierSpineStartNames), the latest first; none for
/// an empty or malformed one, no names where those are malformed
std::vector<StartRecord> readStartRecords(
    const App::PropertyVectorList& current,
    const App::PropertyStringList& currentOf,
    const App::PropertyStringList& currentNames,
    const App::PropertyVectorList& earlier,
    const App::PropertyStringList& earlierOf,
    const App::PropertyStringList& earlierNames
)
{
    std::vector<StartRecord> records;
    if (!current.getValues().empty()) {
        records.push_back({currentOf.getValues(), current.getValues(), currentNames.getValues()});
    }
    // The next of \a lists, each followed by an empty string, from \a from
    auto next = [](const std::vector<std::string>& lists, size_t& from) {
        const auto start = lists.begin() + static_cast<long>(std::min(from, lists.size()));
        const auto end = std::ranges::find(start, lists.end(), "");
        from = static_cast<size_t>(end - lists.begin()) + 1;
        return end == lists.end() ? std::optional<std::vector<std::string>>()
                                  : std::vector<std::string>(start, end);
    };
    std::vector<StartRecord> before;
    const std::vector<Base::Vector3d>& points = earlier.getValues();
    size_t at = 0;
    size_t of = 0;
    size_t named = 0;
    while (at < points.size()) {
        const auto count = static_cast<size_t>(std::lround(points[at].x));
        const std::optional<std::vector<std::string>> input = next(earlierOf.getValues(), of);
        if (count == 0 || at + 1 + count > points.size() || !input) {
            return records;
        }
        before.push_back(
            {*input,
             {points.begin() + static_cast<long>(at + 1),
              points.begin() + static_cast<long>(at + 1 + count)},
             next(earlierNames.getValues(), named).value_or(std::vector<std::string>())}
        );
        at += 1 + count;
    }
    records.insert(records.end(), before.begin(), before.end());
    return records;
}

/// The places of a closed spine's stored record, \a vertices (the start first) and \a middles in
/// its order, paired with \a edges (the spine's, in the sweep's order) as startNearest pairs them:
/// from the start and way whose displacements differ least from one translation. For each place,
/// the index of its edge; empty with another number of edges
std::vector<size_t> placesOf(
    const std::vector<gp_Pnt>& vertices,
    const std::vector<gp_Pnt>& middles,
    const std::vector<TopoDS_Edge>& edges
)
{
    const size_t n = edges.size();
    if (n == 0 || vertices.size() != n || middles.size() != n) {
        return {};
    }
    std::vector<size_t> best;
    double least = std::numeric_limits<double>::infinity();
    for (size_t k = 0; k < n; ++k) {
        for (const bool forward : {true, false}) {
            std::vector<size_t> places;
            std::vector<gp_Vec> moves;
            for (size_t i = 0; i < n; ++i) {
                const size_t at = forward ? (k + i) % n : (k + n - i) % n;
                const size_t along = forward ? (k + i) % n : (k + 2 * n - 1 - i) % n;
                moves.emplace_back(vertices[i], BRep_Tool::Pnt(TopExp::FirstVertex(edges[at], true)));
                moves.emplace_back(middles[i], middleOf(edges[along]));
                places.push_back(along);
            }
            gp_Vec mean;
            for (const gp_Vec& move : moves) {
                mean += move;
            }
            mean /= static_cast<double>(moves.size());
            double sum = 0;
            for (const gp_Vec& move : moves) {
                sum += (move - mean).SquareMagnitude();
            }
            if (sum < least - Precision::Confusion()) {
                least = sum;
                best = places;
            }
        }
    }
    return best;
}

/// Whether \a stored, an open spine's stored ends, are \a ends, in either order
bool endsInPlace(const std::vector<Base::Vector3d>& stored, const std::array<gp_Pnt, 2>& ends)
{
    if (stored.size() != 2) {
        return false;
    }
    auto at = [](const Base::Vector3d& v, const gp_Pnt& p) {
        return p.Distance(gp_Pnt(v.x, v.y, v.z)) < Precision::Confusion();
    };
    return (at(stored[0], ends[0]) && at(stored[1], ends[1]))
        || (at(stored[0], ends[1]) && at(stored[1], ends[0]));
}

/// Whether \a vertices and \a middles, a closed spine's stored ones (startNearest), are those of
/// \a edges, from some start in either direction
bool closedInPlace(
    const std::vector<gp_Pnt>& vertices,
    const std::vector<gp_Pnt>& middles,
    const std::vector<TopoDS_Edge>& edges
)
{
    const size_t n = edges.size();
    if (n == 0 || vertices.size() != n || middles.size() != n) {
        return false;
    }
    auto startOf = [&](size_t k) {
        return BRep_Tool::Pnt(TopExp::FirstVertex(edges[k % n], true));
    };
    for (size_t k = 0; k < n; ++k) {
        for (const bool forward : {true, false}) {
            bool all = true;
            for (size_t i = 0; i < n && all; ++i) {
                const size_t at = forward ? k + i : k + n - i;
                const size_t along = forward ? (k + i) % n : (k + 2 * n - 1 - i) % n;
                all = vertices[i].Distance(startOf(at)) < Precision::Confusion()
                    && middles[i].Distance(middleOf(edges[along])) < Precision::Confusion();
            }
            if (all) {
                return true;
            }
        }
    }
    return false;
}

/// The frames of \a profile, each from its local coordinates into those it lies in:
/// - its shape's placement (a sketch's Placement, with its support and its offset), exact and
///   whatever its lines are: a sketch resized or redrawn as it turns;
/// - its geometry's: at the middle of its first wire's points (pointsAlong), the normal of their
///   plane, its x axis towards the first of them; the placement where they have no plane. A face
///   of a feature has the feature's placement, which doesn't turn when the feature's sketch turns
///   through its offset (the pre-push review of round 5, T1), nor does its plane's position. From
///   the middle, the frame stays as the profile grows about it, and its axis is as long as the
///   profile is wide: towards the next point, it moved with a line resized, and a short first
///   line rounded it out of place (the second pre-push review of round 5, F1, F3)
std::array<gp_Trsf, 2> profileFramesOf(const TopoDS_Shape& profile)
{
    const gp_Trsf placement = profile.Location().Transformation();
    const TopoDS_Wire wire = firstWire(profile);
    const std::vector<gp_Pnt> points = wire.IsNull() ? std::vector<gp_Pnt>() : pointsAlong(wire);
    if (const std::optional<gp_Dir> normal = planeNormal(points)) {
        gp_XYZ middle(0, 0, 0);
        for (const gp_Pnt& point : points) {
            middle += point.XYZ();
        }
        middle /= static_cast<double>(points.size());
        gp_Vec along(gp_Pnt(middle), points.front());
        along -= gp_Vec(normal->XYZ()) * along.Dot(gp_Vec(normal->XYZ()));
        if (along.Magnitude() > Precision::Confusion()) {
            gp_Trsf frame;
            frame.SetTransformation(gp_Ax3(gp_Pnt(middle), *normal, gp_Dir(along)));
            return {placement, frame.Inverted()};
        }
    }
    return {placement, placement};
}
}  // namespace

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

        // A closed spine starts at its stored start, at first its vertex nearest the profile, so
        // the profile's names stay there whichever way its lines are drawn and wherever the
        // profile moves along it (ops#469, startNearest). Not with several sections, which
        // MakePipeShell joins in their order from the spine's start, nor in Auxiliary mode, whose
        // spine is followed from its own start: either would change the result.
        const bool startAtProfile = (Transformation.getValue() != 1 || multisections.empty())
            && Mode.getValue() != 3 && profilePoint.isNull() && !wiresections.empty()
            && !wiresections.front().empty();
        // Such a closed spine of two edges or more as it was at the last good recompute of a
        // closed spine of this input (SpineStart, where they lie in the body; here in the pipe's
        // frame), 2n + 1 points for n edges: its start; its first edge's middle (middleOf: the way
        // it ran); whether its end carried the profile's names (a flag, 1 or 0 in x); its other
        // vertices in the sweep's order; their edges' middles. Kept while the spine is open or
        // in another mode: taken from the profile again after a recompute with the spine open,
        // or with an edge left out and picked again, the start moved to the leg's other vertex
        // where the profile had been moved, and the corners' names with it, silently (the review
        // of fork PR 383, round 2). One record per input, the last 4 inputs' (SpineStart and
        // EarlierSpineStarts): with one, a spine set to another closed spine and back found the
        // other's record, and took the start from the profile again (the cloud reading review of
        // round 3, F1). Read quietly for the input it was stored for (SpineStartOf), or where its
        // points still lie on the spine (an equal copy: the cloud reading review of round 2, N1).
        // Otherwise the start isn't known for certain, and the pipe warns: a record of the same
        // object sharing an edge with the spine (its edges picked again after a line was drawn
        // anew) is the spine edited, and is read; with none, the pipe decides as a new one does
        // (a spine re-picked elsewhere, ops#435).
        auto warn = [&](const std::string& text) {
            if (auto doc = getDocument()) {
                const char* previous = doc->getWarningDescription(this);
                doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + text : text);
            }
        };
        const std::vector<TopoDS_Edge> spineInOrder = edgesInOrder(TopoDS::Wire(path.getShape()));
        const bool startStored = startAtProfile && BRep_Tool::IsClosed(path.getShape())
            && spineInOrder.size() > 1;
        std::vector<gp_Pnt> storedVertices;  // the start first
        std::vector<gp_Pnt> storedMiddles;
        std::optional<gp_Pnt> storedWay;
        std::optional<bool> storedAtEnd;
        std::vector<std::string> storedNames;  // the lines at the stored places
        // The record of the same input read in the body, where its fit is not clear (fitIsClear) or
        // a frame of the profile turned (decision 180)
        bool unpaired = false;
        // Unpaired where no frame of the profile turned: the body's fit's best start and way
        // (bestFitOf); none where one turned
        std::vector<std::pair<size_t, bool>> readings;
        // A frame turned: far above a rounded coordinate's turn, far below an edit's
        constexpr double turnedBy = 1e-6;
        const std::vector<std::string> spineInput = spineIdentity(spine, shape, subedge);
        const std::vector<StartRecord> startRecords = readStartRecords(
            SpineStart,
            SpineStartOf,
            SpineStartNames,
            EarlierSpineStarts,
            EarlierSpineStartsOf,
            EarlierSpineStartNames
        );
        // The profile's frames, in the body (profileFramesOf)
        const std::array<gp_Trsf, 2> frames = profileFramesOf(profileShape.getShape());
        if (startStored) {
            const gp_Trsf inPipe = invObjLoc.Transformation();
            // The stored points of \a record, in the pipe's frame; false for a malformed one. The
            // record ends with the profile's frames at its recompute (each its origin and the ends
            // of its x and y axes, in the body): a loop not at its stored place in the body but at
            // it in one of them, turned or moved with the profile (the whole model turned, K4b's
            // `RingTurned`), is read in that frame for its own input. Read in the body, the turned
            // ring's start went to the vertex a translation fit least badly, and the start's key
            // and the legs' names with it (a rectangle turns onto itself four ways, so no fit
            // tells them apart). The profile's frame, not the pipe's: that is its base's
            // placement, or the profile's support's, and turns with the ring only for a first
            // pipe with an unattached profile (the review of round 4, R1). A loop turned in no
            // stored frame (its lines turned in their sketch) is read in the body, and every
            // leg whose line came from another place is renamed: loud (`RingTurned180InItsSketch`).
            // Not the spine's frame too: a profile attached normal to the ring's line turns half a
            // turn more than the ring does in its plane, and read in the spine's frame, all six
            // references broke where the body's read keeps five (`RingTurnedInPlaneProfileOnRing`)
            auto read = [&](const StartRecord& record) {
                std::vector<Base::Vector3d> stored = record.points;
                auto point = [&](size_t i) {
                    return gp_Pnt(stored[i].x, stored[i].y, stored[i].z);
                };
                auto fill = [&](const gp_Trsf& to) {
                    auto in = [&](size_t i) {
                        return gp_Pnt(stored[i].x, stored[i].y, stored[i].z).Transformed(to);
                    };
                    const size_t count = (stored.size() - 1) / 2;
                    storedVertices = {in(0)};
                    storedMiddles = {in(1)};
                    storedWay = in(1);
                    for (size_t i = 1; i < count; ++i) {
                        storedVertices.push_back(in(2 + i));
                    }
                    for (size_t i = 1; i < count; ++i) {
                        storedMiddles.push_back(in(1 + count + i));
                    }
                };
                storedVertices.clear();
                storedMiddles.clear();
                storedWay.reset();
                storedAtEnd.reset();
                storedNames.clear();
                unpaired = false;
                readings.clear();
                // 2n + 1 points and each frame's 3
                const size_t framed = 3 * frames.size();
                if (stored.size() < 5 + framed || stored.size() % 2 == 0) {
                    return false;
                }
                // From the body into each stored frame
                std::vector<gp_Trsf> into;
                for (size_t f = stored.size() - framed; f < stored.size(); f += 3) {
                    const gp_Vec x(point(f), point(f + 1));
                    const gp_Vec y(point(f), point(f + 2));
                    if (x.Crossed(y).Magnitude() <= Precision::Confusion()) {
                        return false;
                    }
                    into.emplace_back();
                    into.back().SetTransformation(gp_Ax3(point(f), gp_Dir(x.Crossed(y)), gp_Dir(x)));
                }
                stored.resize(stored.size() - framed);
                fill(inPipe);
                // In a frame only for its own input: another spine elsewhere, the profile moved
                // onto it, still decides as a new pipe (CC2)
                // anchor: rung 4 (the stored places), in the body, or exactly in place in one of
                // the profile's stored frames
                if (sameInput(record.of, spineInput)
                    && !closedInPlace(storedVertices, storedMiddles, spineInOrder)) {
                    bool inFrame = false;
                    for (size_t i = 0; i < frames.size() && !inFrame; ++i) {
                        fill(inPipe * frames[i] * into[i]);
                        inFrame = closedInPlace(storedVertices, storedMiddles, spineInOrder);
                    }
                    if (!inFrame) {
                        fill(inPipe);
                        // The fit is a translation's: with a stored frame of the profile turned
                        // since the record, the loop turned, and a turn that still fits by a
                        // translation is the loop's own symmetry (a rectangle turned half a
                        // turn, a square a quarter), whose twin start the fit called clear: the
                        // start moved to another corner with the profile's names, silently (the
                        // pre-push reviews of round 6, T-1 and T-C; decision 180)
                        bool turned = false;
                        for (size_t i = 0; i < frames.size(); ++i) {
                            const gp_Trsf moved = frames[i] * into[i];
                            turned = turned
                                || std::abs(moved.GetRotation().GetRotationAngle()) > turnedBy;
                        }
                        unpaired = turned
                            || !fitIsClear(storedVertices, storedMiddles, spineInOrder);
                        // Where no frame turned, the body's fit reads the start and way (decision
                        // 180). Where one turned, nothing does, and the pipe stops (decision 195's
                        // bound): every reading in a turned frame made a silent family in turn.
                        // The fit, translation-free: a profile turned half a turn on itself (or
                        // its lines cycled) read the stored ring onto its mirror image, the
                        // ring's lines mirrored in their sketch, and the names' start agreed with
                        // it (R-1); by absolute residual, the mirrored ring still fit best from
                        // its own start (decision 187 (2)). The frames' exact carry of the stored
                        // start and next vertex: it chose between two orders of the names on a
                        // spine of two edges (F-1, decision 190) and with two names left at
                        // opposite places (F-A, decision 192); where the frames disagreed, the
                        // names chose between them (a triangle mirrored under its lines' IDs);
                        // and where both frames turned alike, a triangle mirrored with its profile
                        // flipped half a turn took the mirrored order, and its legs traded places
                        // quietly (the reviews of round 6's third and fourth fixes)
                        if (unpaired && !turned) {
                            if (const auto best
                                = bestFitOf(storedVertices, storedMiddles, spineInOrder)) {
                                readings.push_back(*best);
                            }
                        }
                    }
                }
                storedAtEnd = stored[2].x > 0.5;
                if (record.names.size() == (stored.size() - 1) / 2) {
                    storedNames = record.names;
                }
                return true;
            };
            auto clear = [&]() {
                storedVertices.clear();
                storedMiddles.clear();
                storedWay.reset();
                storedAtEnd.reset();
                storedNames.clear();
                unpaired = false;
                readings.clear();
            };
            // Of the same object, with an edge of the spine
            // anchor: rung 4 (another sub-element set's record of the same object), warned
            const std::vector<std::string> spineEdgeNames = identityEdges(spineInput);
            auto sharesAnEdge = [&](const StartRecord& record) {
                return !record.of.empty() && record.of.front() == spineInput.front()
                    && std::ranges::any_of(identityEdges(record.of), [&](const auto& e) {
                           return std::ranges::binary_search(spineEdgeNames, e);
                       });
            };
            bool found = false;
            for (const StartRecord& record : startRecords) {
                if (!found && sameInput(record.of, spineInput)) {
                    found = read(record);
                }
            }
            for (const StartRecord& record : startRecords) {
                if (!found && read(record)) {
                    found = closedInPlace(storedVertices, storedMiddles, spineInOrder);
                }
            }
            for (const StartRecord& record : startRecords) {
                if (!found && sharesAnEdge(record) && read(record)) {
                    found = true;
                    warn(
                        "Pipe: the closed spine's edges aren't those its start was stored for; it "
                        "starts at the vertex that best matches the stored start. Check the "
                        "references to its corners"
                    );
                }
            }
            if (!found) {
                clear();
                if (std::ranges::any_of(startRecords, read)) {
                    clear();
                    warn(
                        "Pipe: the closed spine isn't one its start was stored for; it starts at "
                        "its vertex nearest the profile, as a new pipe does. Check the references "
                        "to its corners"
                    );
                }
            }
            // A record of this input that no stored frame puts in place and the body's fit
            // doesn't pair (a turn with another edit, decisions 171 and 180): the stored places
            // are those of the lines the record names, where the stored names on the spine (two at
            // least; a line drawn anew leaves its place to the others' order) lie in the stored
            // cyclic order or its reverse; the start is then the first place's line's and the way
            // the second's. Only where the body's fit reads the same start and way, where no frame
            // of the profile turned (readings): a redraw that shifts or reverses the lines' order
            // (their IDs kept) keeps their cyclic order, and by the names alone the start and the
            // legs' names followed the lines to other places, silently, as on integration
            // (`RingTurnedRedrawnAndWidened`). With a frame turned there is no reading, and the
            // pipe stops (decision 195). Otherwise the pipe stops (decision 150).
            // Taken at the profile, as a new pipe's, the start went to the profile's nearest
            // vertex: with the profile slid along a leg past its middle, another corner, and the
            // profile's own names at the start went with it, silently (the pre-push review of
            // round 6, T-B)
            // anchor: rung 1 (the lines' names) placing rung 4 (the stored places)
            if (unpaired) {
                const size_t n = spineInOrder.size();
                std::vector<std::string> names;
                if (makeTopoShape(false).getHistoryAlgorithm() == App::HistoryAlgorithm::V2) {
                    for (const TopoDS_Edge& edge : spineInOrder) {
                        names.push_back(firstName(path, edge));
                    }
                }
                std::vector<std::string> distinct = names;
                std::ranges::sort(distinct);
                const bool namesApart = std::ranges::adjacent_find(distinct) == distinct.end();
                // The stored names on the spine, each with its place; a line drawn anew (its
                // stored name gone) leaves its place to the order of the others
                std::vector<std::pair<size_t, size_t>> found;  // (stored place, edge)
                for (size_t i = 0; i < storedNames.size(); ++i) {
                    const auto at = std::ranges::find(names, storedNames[i]);
                    if (at != names.end()) {
                        found.emplace_back(i, static_cast<size_t>(at - names.begin()));
                    }
                }
                const bool paired = n > 1 && names.size() == n && storedNames.size() == n
                    && namesApart && found.size() >= 2;
                // The edge of the stored place 0 in one cyclic order or the other, where every
                // stored name found lies at the place it gives
                auto edgeOfFirst = [&](bool forward) -> std::optional<size_t> {
                    const auto [place, at] = found.front();
                    const size_t j = forward ? (at + n - place) % n : (at + place) % n;
                    for (const auto& [i, edge] : found) {
                        if (edge != (forward ? (j + i) % n : (j + n - i) % n)) {
                            return std::nullopt;
                        }
                    }
                    return j;
                };
                const std::optional<size_t> ahead = paired ? edgeOfFirst(true) : std::nullopt;
                const std::optional<size_t> back = paired ? edgeOfFirst(false) : std::nullopt;
                auto startOf = [&](size_t at) {
                    return BRep_Tool::Pnt(TopExp::FirstVertex(spineInOrder[at % n], true));
                };
                // The order the body's fit reads too (readings: its start k and way, the edge of
                // place 0 run backwards from its far end). Where both orders fit the names (a spine
                // of two edges, or the two found at opposite places), the fit tells them apart:
                // required to agree with one order alone, such a spine stopped (the review of round
                // 6's second fix, T-1 and T-3)
                auto agrees = [&](bool forward, const std::optional<size_t>& edge) {
                    return edge
                        && std::ranges::find(
                               readings,
                               std::make_pair((forward ? *edge : *edge + 1) % n, forward)
                           ) != readings.end();
                };
                const bool viaAhead = agrees(true, ahead);
                const bool viaBack = agrees(false, back);
                const bool forward = viaAhead;
                auto unmatched = []() {
                    return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Pipe: the closed spine's stored start can't be matched to its lines (a "
                        "turn, a redraw or another number of lines with another change in one "
                        "recompute); undo, and make the changes one at a time"
                    ));
                };
                if (viaAhead == viaBack) {
                    return unmatched();
                }
                const size_t j = forward ? *ahead : *back;
                // The stored points at the named lines' places, as fromStoredAt pairs them from
                // the start k: forward, edge k first; the other way, edge j first, run backwards
                // from its far end
                const size_t k = forward ? j : j + 1;
                storedVertices.clear();
                storedMiddles.clear();
                for (size_t i = 0; i < n; ++i) {
                    storedVertices.push_back(startOf(forward ? k + i : k + n - i));
                    storedMiddles.push_back(
                        middleOf(spineInOrder[forward ? (k + i) % n : (k + 2 * n - 1 - i) % n])
                    );
                }
                storedWay = storedMiddles.front();
            }
        }
        if (startAtProfile) {
            Part::TopoShape located = profileShape;
            located.move(invObjLoc);
            path = startNearest(
                path,
                located.getShape(),
                makeTopoShape(false),
                storedVertices,
                storedMiddles
            );
            // and runs the way that sweeps from the profile itself
            Part::TopoShape section = wiresections.front().front();
            section.move(invObjLoc);
            auto profileAtStart = [&](const TopoDS_Wire& spine) {
                try {
                    BRepOffsetAPI_MakePipeShell trial(spine);
                    setupAlgorithm(trial, auxpath.getShape());
                    trial.Add(section.getShape());
                    trial.Build();
                    return trial.IsDone()
                        && MapperPipeShellEnds::distanceTo(section.getShape(), trial.FirstShape())
                        < Precision::Confusion();
                }
                catch (const Standard_Failure&) {
                    return false;
                }
            };
            const TopoDS_Wire profileWire = firstWire(section.getShape());
            const std::optional<gp_Dir> normal = profileWire.IsNull()
                ? std::nullopt
                : planeNormal(pointsAlong(profileWire));
            path = profileFirst(path, normal, profileAtStart, makeTopoShape(false), storedWay);
        }
        // A closed spine's leg is its place, named by its line, and the two must agree
        // (`notes\naming-class-B.md` 9, I-B7). The record holds the name of the line at each place
        // (SpineStartNames). A line whose name another place held (a loop redrawn from another
        // start, the other way round, or two lines' points traded) renames its leg, through a
        // `PLM` section of the stored and the current name, so its faces, lateral edges and both
        // corners' keys change together, and the stored name stays: the names follow their line
        // to another place silently otherwise (K4b's ring cases, 21 of 24 references). A line no
        // place held (drawn anew, a copy's) is named from itself, and the record takes its name.
        // lineNames: what the record stores, in the sweep's order
        // anchor: rung 1 (the line's name) checked against rung 4 (the stored places)
        std::vector<std::string> lineNames;
        if (startStored && makeTopoShape(false).getHistoryAlgorithm() == App::HistoryAlgorithm::V2) {
            const std::vector<TopoDS_Edge> edges = edgesInOrder(TopoDS::Wire(path.getShape()));
            for (const TopoDS_Edge& edge : edges) {
                lineNames.push_back(firstName(path, edge));
            }
            const std::vector<std::string> current = lineNames;
            std::vector<size_t> places;
            if (!storedNames.empty()) {
                places = placesOf(storedVertices, storedMiddles, edges);
            }
            std::vector<Data::MappedName> renamed(edges.size());
            bool any = false;
            for (size_t k = 0; k < places.size(); ++k) {
                const size_t at = places[k];
                if (current[at] == storedNames[k]) {
                    continue;
                }
                if (std::ranges::find(storedNames, current[at]) == storedNames.end()) {
                    // The record keeps the line stored here while that line lies at another
                    // place, renamed by it there: taking the new line's name, it renamed that
                    // leg back to the plain name of this one on the next recompute with no edit
                    // (the pre-push review of round 4, T1)
                    if (std::ranges::find(current, storedNames[k]) != current.end()) {
                        lineNames[at] = storedNames[k];
                    }
                    continue;
                }
                const std::string key = hashed(
                    field(withoutTags(storedNames[k])) + field(withoutTags(current[at]))
                    + field("moved")
                );
                renamed[at] = Data::MappedName(
                    Data::MappedName::makeEncodedSection(
                        {key},
                        {},
                        static_cast<int>(lastTag(current[at])),
                        "PLM",
                        0,
                        'E',
                        0,
                        {Data::MAPPER_FLAG_SOURCE}
                    )
                );
                lineNames[at] = storedNames[k];
                any = true;
            }
            if (any) {
                const Part::TopoShape legsRenamed
                    = wireAlong(path, edges, makeTopoShape(false), renamed);
                if (legsRenamed.isNull()) {
                    return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Pipe: a leg of the closed spine whose line came from another place "
                        "could not be renamed"
                    ));
                }
                path = legsRenamed;
            }
        }
        // The named start, the corner keyed `start` (makeCornerSource): where the sweep starts, at
        // the stored start or on a new pipe (or one whose Spine is another input) at the
        // profile. Both come from storage, so a profile moved to another vertex hands no corner's
        // key, and no end's names, to another (`notes\naming-class-B.md` 3, M1 (a))
        TopoDS_Shape namedStart;
        const std::vector<TopoDS_Edge> pathEdges = edgesInOrder(TopoDS::Wire(path.getShape()));
        if (startStored && !pathEdges.empty()) {
            namedStart = TopExp::FirstVertex(pathEdges.front(), true);
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
        // "Binormal": the binormal as the sweep gets it, and before any sweep, where the spine's
        // tangent runs along it, which no profile survives (ops#406)
        std::optional<gp_Dir> binormal;
        auto binormalText = [&]() {
            Base::Vector3d direction = Binormal.getValue();
            direction.Normalize();
            return pointText(gp_Pnt(direction.x, direction.y, direction.z));
        };
        if (mode == 4) {
            binormal = sweptBinormal(Binormal.getValue(), getLocation());
            if (!binormal) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP(
                        "Exception",
                        "Pipe: 'Binormal' mode needs a non-zero binormal"
                    )
                );
            }
            const TopoDS_Wire& spineWire = TopoDS::Wire(path.getShape());
            const bool retakes = Transition.getValue() != 0;
            const auto along = binormalFolds(spineWire, *binormal, {}, {}, retakes);
            if (along && along->kind == BinormalFold::Kind::unbounded) {
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: in 'Binormal' mode every section lies in a plane through the binormal "
                    "{}, and the spine's edge that starts at {} is a kind of curve (an offset "
                    "curve, say) that can't be checked for the section folding over itself where "
                    "its tangent passes near the binormal. Make the spine of lines, arcs and "
                    "B-splines, or use 'Standard' mode.",
                    binormalText(),
                    inPlace(along->at)
                ));
            }
            if (along && along->kind == BinormalFold::Kind::cornerFlip) {
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: in 'Binormal' mode every section lies in a plane through the binormal "
                    "{}, and at the spine's corner at {} 'Right corner' and 'Round corner' turn "
                    "the section {:.3g} degrees about the spine's tangent beyond the corner's own "
                    "turn, nearer half a turn than none: the two sides can't be joined. Use "
                    "'Transformed', a binormal square to the spine (for a spine in one plane, "
                    "square to that plane), or 'Standard' mode.",
                    binormalText(),
                    inPlace(along->at),
                    along->twist
                ));
            }
            if (along) {
                const bool atStart = along->kind == BinormalFold::Kind::startSingular;
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: in 'Binormal' mode every section lies in a plane through the binormal, "
                    "and at {}{} the spine's tangent runs along the binormal {}: {}. Choose a "
                    "binormal the spine's tangent never reaches (for a spine in one plane, square "
                    "to that plane), or use 'Standard' mode.",
                    inPlace(along->at),
                    atStart ? ", where the spine starts," : "",
                    binormalText(),
                    atStart ? "the section has no plane there"
                            : "the section turns half a turn there and the pipe crosses itself"
                ));
            }
            // Several sections fold like one profile where the tangent passes near B, but OCCT
            // places them along the spine and blends them in the law's frame, which the fold
            // check doesn't follow: no check is sound there, so the pipe stops (ops#406 cloud
            // review of 9234832ed3, S2: a second square at the arc's end folded unseen)
            if (Transformation.getValue() == 1 && !multisections.empty()) {
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: in 'Binormal' mode every section lies in a plane through the binormal "
                    "{}, and with several sections the pipe can't be checked for folding over "
                    "itself where the spine's tangent passes near the binormal. Use one profile "
                    "in 'Binormal' mode, or another mode.",
                    binormalText()
                ));
            }
        }
        // ...and with one profile, where the profile turns about it faster than its width allows
        // (several sections stopped above; Sections without "Multisection" are left out of the sweep)
        const bool binormalSections = mode == 4 && profilePoint.isNull();
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
            // A closed spine with a named start: its ends are one place, which the pairing can't
            // tell apart, so the end it stored (ops#469); a new one's sections decide
            if (!namedStart.IsNull()) {
                reversed = storedAtEnd;
            }
            // Another input's ends seed nothing: re-picked to another L of the same sketch, the
            // stored ends paired with its own by distance and put 22 of 56 names at the end away
            // from the profile, silently (ops#435; the review of `notes\naming-class-B.md` round
            // 1, CC2). The same ends picked anew (the edges listed, an equal copy) are no other
            // input (the cloud reading review of fork PR 383 round 2, N1)
            else if (
                sameInput(SpineEndsOf.getValues(), spineInput)
                || endsInPlace(SpineEnds.getValues(), *spineEnds)
            ) {
                reversed = storedSideAtEnd(SpineEnds.getValues(), *spineEnds);
            }
        }
        // Once the pipe is good: the spine's ends the next recompute pairs with its own, written
        // only when they moved, so that a recompute that changes nothing leaves the file as it was;
        // and a closed spine with a named start, what the next recompute reads above (SpineStart)
        auto storeSpineEnds = [&]() {
            if (!spineEnds) {
                return;
            }
            const bool atEnd = reversed.value_or(false);
            auto storeIn = [](App::PropertyVectorList& property, const std::vector<gp_Pnt>& points) {
                std::vector<Base::Vector3d> values;
                for (const gp_Pnt& point : points) {
                    values.emplace_back(point.X(), point.Y(), point.Z());
                }
                const std::vector<Base::Vector3d>& current = property.getValues();
                const bool same = current.size() == values.size()
                    && std::ranges::equal(current, values, [](const auto& a, const auto& b) {
                           return a.IsEqual(b, Precision::Confusion());
                       });
                if (!same) {
                    property.setValues(values);
                }
            };
            storeIn(SpineEnds, {(*spineEnds)[atEnd ? 1 : 0], (*spineEnds)[atEnd ? 0 : 1]});
            if (SpineEndsOf.getValues() != spineInput) {
                SpineEndsOf.setValues(spineInput);
            }
            if (namedStart.IsNull()) {
                return;
            }
            const gp_Trsf inBody = invObjLoc.Inverted().Transformation();
            std::vector<gp_Pnt> points;
            points.push_back(BRep_Tool::Pnt(TopoDS::Vertex(namedStart)).Transformed(inBody));
            points.push_back(middleOf(pathEdges.front()).Transformed(inBody));
            points.emplace_back(atEnd ? 1 : 0, 0, 0);
            for (size_t k = 1; k < pathEdges.size(); ++k) {
                points.push_back(
                    BRep_Tool::Pnt(TopExp::FirstVertex(pathEdges[k], true)).Transformed(inBody)
                );
            }
            for (size_t k = 1; k < pathEdges.size(); ++k) {
                points.push_back(middleOf(pathEdges[k]).Transformed(inBody));
            }
            // and the profile's frames, each its origin and the ends of its x and y axes, in the
            // body
            for (const gp_Trsf& frame : frames) {
                for (const gp_Pnt& axis : {gp_Pnt(0, 0, 0), gp_Pnt(1, 0, 0), gp_Pnt(0, 1, 0)}) {
                    points.push_back(axis.Transformed(frame));
                }
            }
            // The other inputs' records stay, the latest first, at most 3 (F1)
            std::vector<Base::Vector3d> earlier;
            std::vector<std::string> earlierOf;
            std::vector<std::string> earlierNames;
            size_t kept = 0;
            for (const StartRecord& record : startRecords) {
                if (sameInput(record.of, spineInput) || kept == 3) {
                    continue;
                }
                earlier.emplace_back(static_cast<double>(record.points.size()), 0, 0);
                earlier.insert(earlier.end(), record.points.begin(), record.points.end());
                earlierOf.insert(earlierOf.end(), record.of.begin(), record.of.end());
                earlierOf.emplace_back();
                earlierNames.insert(earlierNames.end(), record.names.begin(), record.names.end());
                earlierNames.emplace_back();
                ++kept;
            }
            if (EarlierSpineStarts.getValues() != earlier) {
                EarlierSpineStarts.setValues(earlier);
            }
            if (EarlierSpineStartsOf.getValues() != earlierOf) {
                EarlierSpineStartsOf.setValues(earlierOf);
            }
            if (EarlierSpineStartNames.getValues() != earlierNames) {
                EarlierSpineStartNames.setValues(earlierNames);
            }
            storeIn(SpineStart, points);
            if (SpineStartOf.getValues() != spineInput) {
                SpineStartOf.setValues(spineInput);
            }
            if (SpineStartNames.getValues() != lineNames) {
                SpineStartNames.setValues(lineNames);
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
            // The spine is a source too, after the sections, so that the start keeps their
            // names, and its corners, which name the joints (ops#415)
            const CornerSource corners = makeCornerSource(path, makeTopoShape(), namedStart);
            std::vector<Part::TopoShape> sources = sections;
            sources.push_back(path);
            if (!corners.shape.isNull()) {
                sources.push_back(corners.shape);
            }
            shell.makeShapeWithElementMap(
                built,
                MapperPipeShellEnds(
                    mkPS,
                    sections,
                    copyProfilePoint.getShape(),
                    path.getShape(),
                    *reversed,
                    corners.vertices,
                    corners.rounds
                ),
                sources,
                Part::OpCodes::PipeShell
            );
            shells.push_back(shell);

            if (sheared || fixedMode || binormalSections) {
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

        // "Binormal" with one profile: where the spine's tangent passes near the binormal, the
        // section turns about it faster than the profile's width allows and folds over itself,
        // or all of it runs back through the pipe, solids that BRepCheck passes (ops#406). A fold
        // under smallFold of the profile's extent warns, as along an arc (ops#370). After a
        // corner "Transformed" tilts the section, and measureCorners measures the rest.
        if (binormalSections && !sweptStarts.empty()) {
            std::vector<gp_Pnt> points;
            for (const TopoDS_Shape& start : sweptStarts) {
                for (TopExp_Explorer it(start, TopAbs_WIRE); it.More(); it.Next()) {
                    const std::vector<gp_Pnt> along = pointsAlong(TopoDS::Wire(it.Current()));
                    points.insert(points.end(), along.begin(), along.end());
                }
            }
            const TopoDS_Wire start = firstWire(sweptStarts.front());
            const std::optional<gp_Dir> normal
                = start.IsNull() ? std::nullopt : planeNormal(pointsAlong(start));
            const std::optional<BinormalFold> fold = normal
                ? binormalFolds(
                      TopoDS::Wire(path.getShape()),
                      *binormal,
                      points,
                      normal,
                      Transition.getValue() != 0
                  )
                : std::nullopt;
            if (fold && fold->kind == BinormalFold::Kind::turnBack) {
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: in 'Binormal' mode every section lies in a plane through the binormal "
                    "{}, and at {} the spine turns edge-on to the section or past: the pipe would "
                    "run back through itself. Choose another binormal, or use 'Standard' mode.",
                    binormalText(),
                    inPlace(fold->at)
                ));
            }
            if (fold && fold->kind == BinormalFold::Kind::fold) {
                const Reach& reach = fold->reach;
                const bool slight = reach.past <= smallFold * reach.across;
                const std::string by = slight
                    ? fmt::format("by {:.2g} mm of its {:.2g} mm width", reach.past, reach.across)
                    : fmt::format("by {:.2g} mm", reach.past);
                const std::string text = fmt::format(
                    "Pipe: in 'Binormal' mode the profile folds {}over itself {} at {}, where the "
                    "spine's tangent comes within {:.3g} degrees of the binormal {}: the section "
                    "turns about the binormal faster than the profile's width allows{}. Choose a "
                    "binormal further from the spine's tangent, a smaller profile, or 'Standard' "
                    "mode{}.",
                    slight ? "slightly " : "",
                    by,
                    inPlace(fold->at),
                    fold->degrees,
                    binormalText(),
                    slight ? ", and the result may cross itself there" : "",
                    slight ? " to avoid it" : ""
                );
                if (!slight) {
                    return new App::DocumentObjectExecReturn(text);
                }
                warn(text);
            }
            // Neither silent nor a failure, as most such pipes are sound (as for 'Transformed')
            if (fold && fold->kind == BinormalFold::Kind::unchecked) {
                warn(fmt::format(
                    "Pipe: in 'Binormal' mode the section turns about the binormal {} too often "
                    "along the spine from {} to check it all for folds: {} stretch{} {} left "
                    "unchecked, and the result may cross itself there. Use 'Standard' mode, or "
                    "split the spine, to avoid it.",
                    binormalText(),
                    inPlace(fold->at),
                    fold->unchecked,
                    fold->unchecked == 1 ? "" : "es",
                    fold->unchecked == 1 ? "was" : "were"
                ));
            }
        }

        if (sheared) {
            // Every wire of the profile counts: a fold or a thin leg of any of them spoils the pipe
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
                path,
                tilts.pieceStarts,
                profiles,
                *reversed,
                namedStart,
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
        // Each shell named from the result itself: one taken through the result's cache of
        // sub-shapes (getSubTopoShapes) came back with every element an `IDX` index name once,
        // a closed spine restarted at the profile swept with "Right corner" (ops#469)
        std::vector<Part::TopoShape> shapes;
        for (const TopoDS_Shape& shell : result.getSubShapes(TopAbs_SHELL)) {
            shapes.push_back(makeTopoShape(shell));
            shapes.back().mapSubElement(result);
        }
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
            storeSpineEnds();
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
        storeSpineEnds();
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
            // In the Body's coordinates, turned into the frame the sweep runs in (ops#458)
            if (const std::optional<gp_Dir> binormal = sweptBinormal(bVec, getLocation())) {
                mkPipeShell.SetMode(*binormal);
            }
            else {
                throw Base::ValueError("Pipe: 'Binormal' mode needs a non-zero binormal");
            }
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
                // With its name: a pipe's legs are named from their spine edges (ops#415)
                path = path.makeElementWires(shape);
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
