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
#include <sstream>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <numbers>
#include <numeric>
#include <optional>
#include <queue>
#include <string_view>
#include <tuple>
#include <unordered_map>

#include <fmt/format.h>

#include <Mod/Part/App/FCBRepAlgoAPI_Cut.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>
#include <BOPAlgo_Alerts.hxx>
#include <BOPAlgo_ArgumentAnalyzer.hxx>
#include <BOPAlgo_BuilderSolid.hxx>
#include <BOPAlgo_MakerVolume.hxx>
#include <BOPTools_AlgoTools3D.hxx>
#include <BRepTools_History.hxx>
#include <Message_Report.hxx>
#include <TopoDS_AlertWithShape.hxx>
#include <IntTools_Context.hxx>
#include <gp_Pnt2d.hxx>
#include <BRepLib.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <TopTools_ListOfShape.hxx>
#include <Geom_Plane.hxx>
#include <BRepOffsetAPI_MakeOffset.hxx>
#include <BRepLib.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
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
#include <Extrema_ExtPC.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom2d_Line.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_Curve.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom_SurfaceOfRevolution.hxx>
#include <Geom_Surface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <GeomAdaptor_Curve.hxx>
#include <GeomConvert_BSplineCurveToBezierCurve.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <GeomFill_Frenet.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <gp.hxx>
#include <GProp_GProps.hxx>
#include <GProp_PEquation.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp.hxx>
#include <gp_Circ.hxx>
#include <gp_Elips.hxx>
#include <gp_Hypr.hxx>
#include <gp_Lin.hxx>
#include <gp_Parab.hxx>
#include <gp_Quaternion.hxx>
#include <gp_Trsf.hxx>
#include <Law_Function.hxx>
#include <Law_Linear.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <Precision.hxx>
#include <ShapeAnalysis_Edge.hxx>
#include <ShapeAnalysis_FreeBounds.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <TColgp_Array1OfPnt.hxx>
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
#include <TopTools_MapOfShape.hxx>


#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/NameTable.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Base/Tools.h>
#include <Mod/Part/App/FaceMakerCheese.h>
#include <Mod/Part/App/KernelBudget.h>
#include <Mod/Part/App/PipeShellApproximation.h>
#include <Mod/Part/App/SweepFrenet.h>

#include "FeaturePipe.h"
#include "Mod/Part/App/TopoShapeOpCode.h"
#include "Mod/Part/App/TopoShapeMapper.h"
#include "FeatureLoft.h"
#include "ProfileRegions.h"

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

/// A Part helix's edge that winds more than one turn: a line on a cylinder (makeHelix) or on a
/// surface of revolution (makeSpiralHelix, Part::Helix's) keeping its distance from the axis, its
/// 3D curve built from that line. Conical helices and spirals aren't (their turns change radius).
struct HelixWinding
{
    gp_Ax1 axis;         ///< where the edge is
    double pitch = 0.0;  ///< the advance along the axis per turn
    double span = 0.0;   ///< the angle wound, more than one turn (any, with partTurn)
    double first = 0.0;  ///< the edge's parameters (its 2D and 3D curves share them)
    double last = 0.0;
};

/// \a edge's winding, if it is one (HelixWinding). With \a partTurn, an edge that winds one turn
/// or less is one too, its pitch the advance a whole turn would make: withHelixTurns names it
/// turn 1, so a reference on turn 1 holds when an edit leaves one turn (2 -> 1).
std::optional<HelixWinding> helixWinding(const TopoDS_Edge& edge, bool partTurn = false)
{
    Handle(Geom2d_Curve) curve2d;
    Handle(Geom_Surface) surface;
    TopLoc_Location surfaceLocation;
    double first = 0.0;
    double last = 0.0;
    BRep_Tool::CurveOnSurface(edge, curve2d, surface, surfaceLocation, first, last);
    if (curve2d.IsNull() || surface.IsNull() || !BRep_Tool::SameParameter(edge)) {
        return {};
    }
    Handle(Geom_Surface) basis = surface;
    if (auto trimmed = Handle(Geom_RectangularTrimmedSurface)::DownCast(basis)) {
        basis = trimmed->BasisSurface();
    }
    Handle(Geom2d_Curve) line = curve2d;
    if (auto trimmed = Handle(Geom2d_TrimmedCurve)::DownCast(line)) {
        line = trimmed->BasisCurve();
    }
    std::optional<gp_Ax1> axis;
    if (auto cylinder = Handle(Geom_CylindricalSurface)::DownCast(basis)) {
        axis = cylinder->Axis();
    }
    else if (auto revolution = Handle(Geom_SurfaceOfRevolution)::DownCast(basis)) {
        axis = revolution->Axis();
    }
    if (!axis || Handle(Geom2d_Line)::DownCast(line).IsNull()) {
        return {};
    }
    // The edge keeps its distance from the axis (a 2D line on the surface, so the distance
    // changes linearly along it if at all)
    const gp_Trsf placement = surfaceLocation.Transformation();
    const gp_Ax1 placed = axis->Transformed(placement);
    const gp_Lin axisLine(placed);
    auto pointAt = [&](double t) {
        const gp_Pnt2d uv = curve2d->Value(t);
        return surface->Value(uv.X(), uv.Y()).Transformed(placement);
    };
    const double radius = axisLine.Distance(pointAt(first));
    if (radius < Precision::Confusion()
        || std::fabs(axisLine.Distance(pointAt(last)) - radius) > Precision::Confusion()
        || std::fabs(axisLine.Distance(pointAt((first + last) / 2)) - radius)
            > Precision::Confusion()) {
        return {};
    }
    constexpr double turn = 2.0 * std::numbers::pi;
    const double span = std::fabs(curve2d->Value(last).X() - curve2d->Value(first).X());
    if ((span <= turn * (1.0 + 1e-6) && !partTurn) || span < Precision::Angular()) {
        return {};
    }
    const gp_Vec advance(pointAt(first), pointAt(first + (last - first) * turn / span));
    return HelixWinding {placed, std::fabs(advance.Dot(gp_Vec(placed.Direction()))), span, first, last};
}

/// The extent of \a shape along \a axis's direction
double extentAlong(const TopoDS_Shape& shape, const gp_Ax1& axis)
{
    gp_Trsf toAxis;
    toAxis.SetTransformation(gp_Ax3(axis.Location(), axis.Direction()));
    Bnd_Box box;
    BRepBndLib::AddOptimal(shape.Moved(TopLoc_Location(toAxis)), box, false, false);
    if (box.IsVoid()) {
        return 0.0;
    }
    double xMin, yMin, zMin, xMax, yMax, zMax;
    box.Get(xMin, yMin, zMin, xMax, yMax, zMax);
    return zMax - zMin;
}

/// A helix in \a path whose turns \a profile, swept along it, overlaps from one turn to the next:
/// the profile's extent along the axis beyond the pitch (Onshape refuses it, SWEEP_FAILED; ops#660).
/// Turns that only touch sweep. The helix's pitch and the profile's extent, or none. \a scale:
/// the largest the scale law makes the profile (1 without one): a profile scaled up along the
/// helix overlaps the turn before where it grows past the pitch (it swept a self-intersecting
/// solid, Up-to-date, before the ops#666 skeptic's review). Taking the largest size, the check
/// refuses a few scales whose turns would only nearly overlap: loud, never silent.
std::optional<std::pair<double, double>> overlappingTurns(
    const TopoDS_Shape& path,
    const TopoDS_Shape& profile,
    double scale = 1.0
)
{
    for (TopExp_Explorer it(path, TopAbs_EDGE); it.More(); it.Next()) {
        if (const auto winding = helixWinding(TopoDS::Edge(it.Current()))) {
            const double extent = extentAlong(profile, winding->axis) * std::max(1.0, scale);
            if (extent > winding->pitch + 1e-6) {
                return std::make_pair(winding->pitch, extent);
            }
        }
    }
    return {};
}

/// A helix edge (\a winding its winding) cut at each whole turn from its start, as AdditiveHelix
/// breaks its path at each turn: a sweep along one edge of five turns, its profile's base on the
/// cylinder, fused with the cylinder into 2 solids with BOP errors, where Onshape (and the broken
/// path) gives one part (ops#665). Empty when it can't be cut.
std::vector<TopoDS_Edge> helixTurns(const TopoDS_Edge& edge, const HelixWinding& winding)
{
    constexpr double turn = 2.0 * std::numbers::pi;
    const double first = winding.first;
    const double last = winding.last;
    const double span = winding.span;
    // A piece shorter than this at the end would be a sliver: the last turn takes it
    const double sliver = 1e-6 * turn;
    TopLoc_Location location;
    double first3d = 0.0;
    double last3d = 0.0;
    Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, location, first3d, last3d);
    if (curve.IsNull() || std::fabs(first3d - first) > Precision::PConfusion()
        || std::fabs(last3d - last) > Precision::PConfusion()) {
        return {};
    }
    if (!location.IsIdentity()) {
        curve = Handle(Geom_Curve)::DownCast(curve->Transformed(location.Transformation()));
    }
    TopoDS_Vertex start;
    TopoDS_Vertex end;
    TopExp::Vertices(edge, start, end);  // by parameter, whatever the edge's orientation
    std::vector<double> at {first};
    for (int k = 1; k * turn < span - sliver; ++k) {
        at.push_back(first + (last - first) * (k * turn / span));
    }
    at.push_back(last);
    const double tolerance = BRep_Tool::Tolerance(edge);
    std::vector<TopoDS_Edge> pieces;
    TopoDS_Vertex from = start;
    BRep_Builder builder;
    for (size_t k = 1; k < at.size(); ++k) {
        TopoDS_Vertex to = end;
        if (k + 1 < at.size()) {
            to = BRepBuilderAPI_MakeVertex(curve->Value(at[k])).Vertex();
            builder.UpdateVertex(to, tolerance);
        }
        BRepBuilderAPI_MakeEdge piece(curve, from, to, at[k - 1], at[k]);
        if (!piece.IsDone()) {
            return {};
        }
        TopoDS_Edge made = piece.Edge();
        builder.UpdateEdge(made, tolerance);
        pieces.push_back(made);
        from = to;
    }
    return pieces;
}

std::string withoutTags(const std::string& name);
long lastTag(const std::string& name);
std::string firstName(const Part::TopoShape& path, const TopoDS_Shape& element);
std::string field(const std::string& text);
std::string hashed(const std::string& text);

/// \a path with every helix edge cut at its turns (helixTurns), made a wire as \a wire; \a path
/// itself when no edge is cut or renamed. A helix whose turns \a profile makes touch stays whole: OCCT's
/// sweep along its pieces fails (FindFromKey), along the one edge it builds, as Onshape does.
/// Turn k (counted from the helix's start, by parameter) is named by its edge's name and k, `TRN`,
/// and the vertex k turns from the start by the edge's name and k, `TRV`; the helix's own ends
/// keep their names. Named as pieces modified from the edge (batch 6's R1, ops#640), the turns
/// were twins and the last was told apart by the end vertex alone, so a reference on turn 2 of 2
/// followed the end piece when an edit added turns. By its place from the start, turn k keeps
/// its name whatever the number of turns, and a turn that goes takes its name with it.
/// A helix kept whole because its turns touch is named as its turns merged (`TRN` with each
/// turn's name linked, MOD; turn 1's own name for one turn): Onshape's side face is one face either
/// way, so a reference on turn k's face follows the one face when an edit makes the turns touch,
/// and the one face's reference is found among the turns' when they part (sweeps 15). Named by the
/// edge's own name, the one face shared no source with any turn's, and references broke both ways.
Part::TopoShape withHelixTurns(
    const Part::TopoShape& path,
    Part::TopoShape wire,
    const TopoDS_Shape& profile
)
{
    std::vector<Part::TopoShape> edges;
    bool cut = false;
    for (const Part::TopoShape& edge : path.getSubTopoShapes(TopAbs_EDGE)) {
        const TopoDS_Edge& whole = TopoDS::Edge(edge.getShape());
        const std::optional<HelixWinding> winding = helixWinding(whole, true);
        std::vector<TopoDS_Edge> pieces;
        bool touching = false;
        if (winding) {
            // Cut even when the turns touch: the pieces count the turns the merged name lists
            pieces = helixTurns(whole, *winding);
            touching = extentAlong(profile, winding->axis) >= winding->pitch * (1.0 - 1e-4);
        }
        if (pieces.empty()) {
            edges.push_back(edge);
            continue;
        }
        cut = true;
        const std::string name = firstName(path, whole);
        const std::string bare = withoutTags(name);
        const long tag = lastTag(name);
        auto turnName = [&](const char* op, char type, size_t k) {
            return Data::MappedName(Data::MappedName::makeEncodedSection(
                {hashed(field(bare) + field(op) + field(std::to_string(k)))},
                {},
                static_cast<int>(tag),
                op,
                0,
                type,
                0,
                {Data::MAPPER_FLAG_SOURCE}
            ));
        };
        std::optional<Data::MappedName> merged;
        if (touching) {
            std::vector<Data::MappedName> turns;
            for (size_t k = 0; k < pieces.size(); ++k) {
                turns.push_back(turnName("TRN", 'E', k + 1));
            }
            merged = turns.size() == 1 ? turns.front()
                                       : Data::MappedName(Data::MappedName::makeEncodedSection(
                                             std::vector<std::string> {},
                                             turns,
                                             static_cast<int>(tag),
                                             "TRN",
                                             0,
                                             'E',
                                             0,
                                             {Data::MAPPER_FLAG_MODIFIED}
                                         ));
            pieces = {whole};
        }
        TopoDS_Vertex start;
        TopoDS_Vertex end;
        TopExp::Vertices(whole, start, end);  // by parameter, as helixTurns cuts
        for (size_t k = 0; k < pieces.size(); ++k) {
            Part::TopoShape named(pieces[k], edge.Tag, edge.Hasher, edge.getHistoryAlgorithm());
            named.setElementName(
                Data::IndexedName::fromConst("Edge", 1),
                merged ? *merged : turnName("TRN", 'E', k + 1),
                edge.Tag
            );
            TopoDS_Vertex from;
            TopoDS_Vertex to;
            TopExp::Vertices(pieces[k], from, to);
            for (const auto& [vertex, cutAt] : {std::pair {from, k}, std::pair {to, k + 1}}) {
                const int at = named.findShape(vertex);
                if (at <= 0) {
                    continue;
                }
                const Data::IndexedName element = Data::IndexedName::fromConst("Vertex", at);
                const TopoDS_Vertex& own = cutAt == 0 ? start : end;
                if (cutAt == 0 || cutAt == pieces.size()) {
                    // The helix's own end: its name as it was
                    const int index = path.findShape(own);
                    if (index <= 0) {
                        continue;
                    }
                    for (const auto& [mapped, sids] :
                         path.getElementMappedNames(Data::IndexedName::fromConst("Vertex", index))) {
                        named.setElementName(element, mapped, edge.Tag, &sids);
                    }
                    continue;
                }
                named.setElementName(element, turnName("TRV", 'V', cutAt), edge.Tag);
            }
            edges.push_back(named);
        }
    }
    if (!cut) {
        return path;
    }
    wire.makeElementWires(edges);
    if (wire.isNull() || wire.getShape().ShapeType() != TopAbs_WIRE) {
        return path;
    }
    return wire;
}

/// Pairs of \a wire's edges, adjacent or not, by the points where adjacent ones meet: \a visit
/// gets the two edges, whether they follow each other along the wire, and the ends they share
/// (within \a tolerance), for the pairs whose boxes come within \a reach of each other. Stops at
/// the first visit that returns a point.
template<typename Visit>
std::optional<gp_Pnt> edgePairs(const TopoDS_Wire& wire, double reach, Visit visit)
{
    const std::vector<TopoDS_Edge> edges = edgesInOrder(wire);
    const size_t n = edges.size();
    std::vector<Bnd_Box> boxes(n);
    std::vector<std::array<gp_Pnt, 2>> ends(n);
    for (size_t i = 0; i < n; ++i) {
        BRepBndLib::Add(edges[i], boxes[i]);
        boxes[i].Enlarge(reach / 2);
        ends[i] = {
            BRep_Tool::Pnt(TopExp::FirstVertex(edges[i], true)),
            BRep_Tool::Pnt(TopExp::LastVertex(edges[i], true))
        };
    }
    const bool closed = n > 1 && ends[0][0].Distance(ends[n - 1][1]) <= Precision::Confusion();
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = i + 1; j < n; ++j) {
            if (boxes[i].IsOut(boxes[j])) {
                continue;
            }
            const bool adjacent = j == i + 1 || (closed && i == 0 && j == n - 1);
            std::vector<gp_Pnt> shared;
            if (adjacent) {
                for (const gp_Pnt& a : ends[i]) {
                    for (const gp_Pnt& b : ends[j]) {
                        if (a.Distance(b) <= Precision::Confusion()) {
                            shared.push_back(a);
                        }
                    }
                }
            }
            if (std::optional<gp_Pnt> found = visit(edges[i], edges[j], adjacent, shared)) {
                return found;
            }
        }
    }
    return {};
}

/// Where \a wire touches or crosses itself: two edges meeting other than at the ends where
/// adjacent edges join, or an edge turning straight back along the one before. Onshape refuses
/// such a path (SWEEP_PATH_FAILED; oracle 9, ops#660). One edge crossing itself isn't looked for.
std::optional<gp_Pnt> pathTouchesItself(const TopoDS_Wire& wire)
{
    constexpr double tolerance = 1e-6;
    return edgePairs(
        wire,
        2 * tolerance,
        [](const TopoDS_Edge& a, const TopoDS_Edge& b, bool adjacent, const std::vector<gp_Pnt>& shared
        ) -> std::optional<gp_Pnt> {
            BRepExtrema_DistShapeShape distance(a, b);
            if (!distance.IsDone() || distance.Value() > tolerance) {
                return {};
            }
            for (int k = 1; k <= distance.NbSolution(); ++k) {
                const gp_Pnt at = distance.PointOnShape1(k);
                if (std::ranges::none_of(shared, [&](const gp_Pnt& p) {
                        return p.Distance(at) <= tolerance;
                    })) {
                    return at;
                }
            }
            // Straight back: at a joint, the second edge leaves along the first's way in
            if (adjacent && shared.size() == 1) {
                const bool aEndsThere = BRep_Tool::Pnt(TopExp::LastVertex(a, true)).Distance(shared[0])
                    <= Precision::Confusion();
                const bool bStartsThere
                    = BRep_Tool::Pnt(TopExp::FirstVertex(b, true)).Distance(shared[0])
                    <= Precision::Confusion();
                const gp_Dir in = tangentAlong(a, !aEndsThere);
                const gp_Dir out = tangentAlong(b, bStartsThere);
                // Along the wire, the first edge runs into the joint and the second away from it
                const double turn = (aEndsThere ? 1.0 : -1.0) * (bStartsThere ? 1.0 : -1.0)
                    * in.Dot(out);
                if (turn < -1.0 + 1e-9) {
                    return shared[0];
                }
            }
            return {};
        }
    );
}

/// Where non-adjacent edges of \a wire pass within twice \a reach of each other (the profile's
/// reach about the path), and how near: tubes swept along them may overlap there
std::optional<std::pair<gp_Pnt, double>> pathPassesNearItself(const TopoDS_Wire& wire, double reach)
{
    double nearest = 0.0;
    const std::optional<gp_Pnt> at = edgePairs(
        wire,
        2 * reach,
        [&](const TopoDS_Edge& a, const TopoDS_Edge& b, bool adjacent, const std::vector<gp_Pnt>&
        ) -> std::optional<gp_Pnt> {
            if (adjacent) {
                return {};
            }
            BRepExtrema_DistShapeShape distance(a, b);
            if (!distance.IsDone() || distance.Value() >= 2 * reach || distance.NbSolution() < 1) {
                return {};
            }
            nearest = distance.Value();
            return distance.PointOnShape1(1);
        }
    );
    if (!at) {
        return {};
    }
    return std::make_pair(*at, nearest);
}

/// Whether \a shape intersects itself, by OCCT's self-interference check
bool intersectsItself(const TopoDS_Shape& shape)
{
    BOPAlgo_ArgumentAnalyzer check;
    check.SetShape1(BRepBuilderAPI_Copy(shape).Shape());
    check.SelfInterMode() = true;
    check.Perform();
    return check.HasFaulty();
}

/// The union of a sweep's tubes where they overlap (ops#666, `notes\sweep-design.md` 13): the solid
/// and the history from the sweep's faces, or why it couldn't be built (any doubt is an error, never a
/// guess), or neither when the faces don't touch each other (the sweep stays as it is)
struct SweepUnion
{
    TopoDS_Shape solid;
    occ::handle<BRepTools_History> history;
    std::string error;
    bool unusedFaces = false;  // the maker left faces out of every cell
    // No face split another: the tubes don't meet, or they overlap within one face, which the maker
    // never checks against itself (a looping edge); OCCT's self-interference check decides then
    bool untouched = false;
};

/// A shape's volume, integrated adaptively (the default integration is badly wrong on faces of many
/// B-spline spans, ops#414)
double volumeOf(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape, props, 1e-7, true);
    return props.Mass();
}

/// Faces across the sweep at the joints of its \a spine, each bounded by the swept edges lying in the
/// plane that bisects the joint (a mitre's section, or a smooth joint's). The union's volume maker
/// takes them as faces of no winding step: they cut the tubes into a cell per stretch between joints
/// and leave the union's faces as they are. OCCT's maker builds no cell that meets itself along an
/// edge where its boundary also reaches that edge's other side another way: a ring along S2's path,
/// whose wall of legs 1 to 4 meets itself where leg 4 runs into leg 1 and runs on round leg 4's bore,
/// left every face unused (sweeps 15). A joint whose edges don't close stays uncut.
std::vector<TopoDS_Face> jointSections(const std::vector<TopoDS_Shape>& solids, const TopoDS_Wire& spine)
{
    std::vector<TopoDS_Face> sections;
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    if (edges.size() < 2) {
        return sections;
    }
    const bool closed = BRep_Tool::Pnt(TopExp::FirstVertex(edges.front(), true))
                            .Distance(BRep_Tool::Pnt(TopExp::LastVertex(edges.back(), true)))
        <= Precision::Confusion();
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    for (const TopoDS_Shape& solid : solids) {
        TopExp::MapShapesAndAncestors(solid, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    }
    TopTools_MapOfShape used;
    for (size_t k = closed ? 0 : 1; k < edges.size(); ++k) {
        const TopoDS_Edge& before = edges[(k + edges.size() - 1) % edges.size()];
        const TopoDS_Edge& after = edges[k];
        const gp_Vec normal = gp_Vec(tangentAlong(before, false)) + gp_Vec(tangentAlong(after, true));
        if (normal.Magnitude() < 1e-6) {
            continue;  // a hairpin
        }
        const gp_Pln plane(BRep_Tool::Pnt(TopExp::FirstVertex(after, true)), gp_Dir(normal));
        // The swept edges in that plane, other than a face's lying in it (a cap's)
        occ::handle<TopTools_HSequenceOfShape> found = new TopTools_HSequenceOfShape();
        for (int i = 1; i <= edgeFaces.Extent(); ++i) {
            const TopoDS_Edge& edge = TopoDS::Edge(edgeFaces.FindKey(i));
            if (BRep_Tool::Degenerated(edge) || used.Contains(edge)) {
                continue;
            }
            const double tolerance = std::max(1e-6, 10 * BRep_Tool::Tolerance(edge));
            BRepAdaptor_Curve curve(edge);
            bool inPlane = true;
            for (int s = 0; s <= 8 && inPlane; ++s) {
                const double t = curve.FirstParameter()
                    + s * (curve.LastParameter() - curve.FirstParameter()) / 8;
                inPlane = plane.Distance(curve.Value(t)) <= tolerance;
            }
            bool onFaceInPlane = false;
            for (const TopoDS_Shape& face : edgeFaces(i)) {
                BRepAdaptor_Surface surface(TopoDS::Face(face), false);
                onFaceInPlane = onFaceInPlane
                    || (surface.GetType() == GeomAbs_Plane
                        && surface.Plane().Axis().IsParallel(plane.Axis(), 1e-9));
            }
            if (inPlane && !onFaceInPlane) {
                found->Append(edge);
            }
        }
        if (found->IsEmpty()) {
            continue;
        }
        occ::handle<TopTools_HSequenceOfShape> wires;
        ShapeAnalysis_FreeBounds::ConnectEdgesToWires(found, Precision::Confusion(), true, wires);
        // Each wire's disk, and how many other disks hold it: an even count bounds a face, an odd
        // one is a hole in the smallest disk holding it
        std::vector<TopoDS_Face> disks;
        bool closes = !wires.IsNull() && !wires->IsEmpty();
        for (int w = 1; closes && w <= wires->Length(); ++w) {
            const TopoDS_Wire& wire = TopoDS::Wire(wires->Value(w));
            BRepBuilderAPI_MakeFace disk(plane, wire, true);
            closes = BRep_Tool::IsClosed(wire) && disk.IsDone();
            if (closes) {
                disks.push_back(disk.Face());
            }
        }
        if (!closes) {
            continue;
        }
        std::vector<double> areas;
        for (const TopoDS_Face& disk : disks) {
            GProp_GProps props;
            BRepGProp::SurfaceProperties(disk, props);
            areas.push_back(props.Mass());
        }
        auto holds = [&](size_t outer, size_t inner) {
            if (outer == inner || areas[outer] <= areas[inner]) {
                return false;
            }
            TopExp_Explorer vertex(disks[inner], TopAbs_VERTEX);
            BRepClass_FaceClassifier classifier(
                disks[outer],
                BRep_Tool::Pnt(TopoDS::Vertex(vertex.Current())),
                Precision::Confusion()
            );
            return classifier.State() == TopAbs_IN;
        };
        auto depthOf = [&](size_t d) {
            int depth = 0;
            for (size_t e = 0; e < disks.size(); ++e) {
                depth += holds(e, d) ? 1 : 0;
            }
            return depth;
        };
        for (size_t d = 0; d < disks.size(); ++d) {
            const int depth = depthOf(d);
            if (depth % 2) {
                continue;
            }
            BRepBuilderAPI_MakeFace face(disks[d]);
            for (size_t e = 0; e < disks.size(); ++e) {
                if (holds(d, e) && depthOf(e) == depth + 1) {
                    face.Add(TopoDS::Wire(BRepTools::OuterWire(disks[e]).Reversed()));
                }
            }
            if (face.IsDone() && BRepCheck_Analyzer(face.Face()).IsValid()) {
                sections.push_back(face.Face());
            }
        }
        for (int i = 1; i <= found->Length(); ++i) {
            used.Add(found->Value(i));
        }
    }
    return sections;
}

/// The union of the swept \a solids (each turned outward), each counted +1, or -1 at an odd \a depth
/// (a hole's shell of a closed spine's holed profile). The faces split one another
/// (BOPAlgo_MakerVolume, each face an argument of its own: an argument isn't checked against
/// itself), the cells they bound are numbered by their winding number from the exterior (0), and the
/// cells of number >= 1 are kept, as Onshape keeps a point in some section's area. The \a cuts
/// (jointSections) are arguments of no step.
SweepUnion unionOfOverlaps(
    const std::vector<TopoDS_Shape>& solids,
    const std::vector<int>& depths,
    const std::vector<TopoDS_Face>& cuts = {}
)
{
    SweepUnion out;
    struct Original
    {
        TopoDS_Face face;  // oriented as in its solid: its normal points out of the solid
        int sign;
    };
    std::vector<Original> originals;
    NCollection_List<TopoDS_Shape> arguments;
    double fuzzy = 0.0;
    double naive = 0.0;
    for (size_t i = 0; i < solids.size(); ++i) {
        const int sign = depths[i] % 2 ? -1 : 1;
        naive += sign * volumeOf(solids[i]);
        for (TopExp_Explorer it(solids[i], TopAbs_FACE); it.More(); it.Next()) {
            const TopoDS_Face& face = TopoDS::Face(it.Current());
            originals.push_back({face, sign});
            arguments.Append(face);
            fuzzy = std::max(fuzzy, BRep_Tool::Tolerance(face));
        }
    }
    for (const TopoDS_Face& cut : cuts) {
        originals.push_back({cut, 0});
        arguments.Append(cut);
    }
    BOPAlgo_MakerVolume maker;
    maker.SetArguments(arguments);
    maker.SetIntersect(true);
    maker.SetNonDestructive(true);  // the start cap shares the sketch's edges
    maker.SetToFillHistory(true);
    maker.SetFuzzyValue(fuzzy);  // a loose sweep (ops#448)
    maker.Perform();
    // OCCT couldn't tell whether a split piece faces as its face does (a Round corner's sphere
    // wedges, tangent to the legs they join: sweeps 17). Nothing below reads a piece's orientation
    // from its face: each cell gives its pieces theirs, and the volume checks hold the result
    bool otherWarnings = false;
    for (const occ::handle<Message_Alert>& alert : maker.GetReport()->GetAlerts(Message_Warning)) {
        otherWarnings = otherWarnings
            || !alert->IsKind(STANDARD_TYPE(BOPAlgo_AlertUnableToOrientTheShape));
    }
    if (maker.HasErrors() || otherWarnings) {
        std::ostringstream alerts;
        maker.DumpErrors(alerts);
        maker.DumpWarnings(alerts);
        std::string text = alerts.str();
        std::replace(text.begin(), text.end(), '\n', ' ');
        // How many faces an alert names (a holed profile's tube left all of its faces unused)
        int named = 0;
        for (const occ::handle<Message_Alert>& alert :
             maker.GetReport()->GetAlerts(Message_Warning)) {
            out.unusedFaces = out.unusedFaces
                || alert->IsKind(STANDARD_TYPE(BOPAlgo_AlertSolidBuilderUnusedFaces));
            const auto withShape = occ::down_cast<TopoDS_AlertWithShape>(alert);
            for (TopExp_Explorer it(withShape.IsNull() ? TopoDS_Shape() : withShape->GetShape(),
                                    TopAbs_FACE);
                 it.More();
                 it.Next()) {
                ++named;
            }
        }
        out.error = fmt::format("OCCT's volume maker: {}, {} faces", text, named);
        return out;
    }
    const occ::handle<BRepTools_History> history = maker.History();
    if (history.IsNull()) {
        out.error = "no history";
        return out;
    }
    if (!history->HasModified() && !history->HasGenerated()) {
        out.untouched = true;
        return out;
    }

    // The pieces: each original face's images, or the face itself when left whole
    TopTools_IndexedMapOfShape pieces;
    std::vector<std::vector<size_t>> sources;  // per piece, the originals it lies on
    for (size_t k = 0; k < originals.size(); ++k) {
        const TopoDS_Face& face = originals[k].face;
        if (history->IsRemoved(face)) {
            out.error = "a face of the sweep was removed";
            return out;
        }
        NCollection_List<TopoDS_Shape> images = history->Modified(face);
        if (images.IsEmpty()) {
            images.Append(face);
        }
        for (const TopoDS_Shape& image : images) {
            if (image.ShapeType() != TopAbs_FACE) {
                out.error = "a face's image isn't a face";
                return out;
            }
            const int index = pieces.Add(image);
            if (index > static_cast<int>(sources.size())) {
                sources.emplace_back();
            }
            sources[index - 1].push_back(k);
        }
    }

    // The cells and the pieces bounding them, each with the orientation its cell gives it
    std::vector<TopoDS_Shape> cells;
    for (TopExp_Explorer it(maker.Shape(), TopAbs_SOLID); it.More(); it.Next()) {
        cells.push_back(it.Current());
    }
    struct Side
    {
        size_t cell;
        TopoDS_Face face;  // its normal points out of the cell
    };
    std::vector<std::vector<Side>> sides(pieces.Extent());
    std::vector<std::optional<Side>> inner(pieces.Extent());
    for (size_t c = 0; c < cells.size(); ++c) {
        for (TopExp_Explorer it(cells[c], TopAbs_FACE); it.More(); it.Next()) {
            const TopoDS_Face& face = TopoDS::Face(it.Current());
            const int index = pieces.FindIndex(face);
            if (index == 0) {
                GProp_GProps props;
                BRepGProp::SurfaceProperties(face, props);
                const gp_Pnt at = props.CentreOfMass();
                out.error = fmt::format(
                    "a cell is bounded by a face that isn't a piece of the sweep (area {:.6g} at "
                    "({:.4g}, {:.4g}, {:.4g}))",
                    props.Mass(), at.X(), at.Y(), at.Z());
                return out;
            }
            // A piece inside its cell (OCCT's maker leaves an end cap flush on another tube's side
            // inside the one cell of both): the same number on both sides, so a step of 0 (below)
            std::vector<Side>& found = sides[index - 1];
            const auto same = std::find_if(found.begin(), found.end(), [&](const Side& side) {
                return side.cell == c;
            });
            if (face.Orientation() == TopAbs_INTERNAL || face.Orientation() == TopAbs_EXTERNAL
                || same != found.end()) {
                if (inner[index - 1] || (same == found.end() && !found.empty())) {
                    out.error = "a piece lies inside a cell and bounds another";
                    return out;
                }
                if (same != found.end()) {
                    found.erase(same);
                }
                inner[index - 1] = Side {c, face};
                continue;
            }
            if (inner[index - 1]) {
                out.error = "a piece lies inside a cell and bounds another";
                return out;
            }
            found.push_back({c, face});
        }
    }

    // A piece's winding step seen from one of its cells: the sum over the originals it lies on of
    // +1 where the original's normal agrees with the cell's outward one (crossing out of the cell
    // leaves that tube), -1 where it doesn't; signed by the original's depth
    const occ::handle<IntTools_Context> context = new IntTools_Context();
    auto stepOf = [&](size_t piece, const Side& side) -> std::optional<int> {
        gp_Pnt point;
        gp_Pnt2d uv;
        if (BOPTools_AlgoTools3D::PointInFace(side.face, point, uv, context) != 0) {
            return {};
        }
        gp_Pnt on;
        gp_Vec normal;
        BRepGProp_Face(side.face).Normal(uv.X(), uv.Y(), on, normal);
        if (normal.Magnitude() < Precision::Confusion()) {
            return {};
        }
        int step = 0;
        for (const size_t k : sources[piece]) {
            const TopoDS_Face& face = originals[k].face;
            GeomAPI_ProjectPointOnSurf projection(point, BRep_Tool::Surface(face));
            if (!projection.IsDone() || projection.NbPoints() < 1
                || projection.LowerDistance() > std::max(1e-6, 10 * BRep_Tool::Tolerance(face))) {
                return {};
            }
            double u = 0.0;
            double v = 0.0;
            projection.LowerDistanceParameters(u, v);
            gp_Vec outward;
            BRepGProp_Face(face).Normal(u, v, on, outward);
            if (outward.Magnitude() < Precision::Confusion()) {
                return {};
            }
            const double cosine = normal.Normalized().Dot(outward.Normalized());
            if (std::abs(cosine) < 0.99) {
                return {};  // a piece lies on its originals; their normals agree or oppose
            }
            step += (cosine > 0 ? 1 : -1) * originals[k].sign;
        }
        return step;
    };

    // Number the cells from the exterior, breadth first
    std::vector<std::optional<int>> number(cells.size());
    std::vector<size_t> queue;
    auto assign = [&](size_t cell, int value) {
        if (value < 0 || (number[cell] && *number[cell] != value)) {
            return false;
        }
        if (!number[cell]) {
            number[cell] = value;
            queue.push_back(cell);
        }
        return true;
    };
    std::vector<std::vector<int>> steps(pieces.Extent());
    for (size_t p = 0; p < sides.size(); ++p) {
        if (inner[p]) {
            if (!sides[p].empty() || stepOf(p, *inner[p]) != std::optional<int>(0)) {
                out.error = "a piece inside a cell changes the winding number";
                return out;
            }
            continue;
        }
        if (sides[p].empty() || sides[p].size() > 2) {
            out.error = "a piece bounds no cell, or more than two";
            return out;
        }
        for (const Side& side : sides[p]) {
            const std::optional<int> step = stepOf(p, side);
            if (!step) {
                out.error = "a piece's normal couldn't be compared with its faces'";
                return out;
            }
            steps[p].push_back(*step);
        }
        if (sides[p].size() == 2 && steps[p][0] != -steps[p][1]) {
            out.error = "a piece's two sides disagree";
            return out;
        }
        // The exterior (0) beyond a piece of one cell: the cell's number is its step
        if (sides[p].size() == 1 && !assign(sides[p][0].cell, steps[p][0])) {
            out.error = "a cell numbered twice, or below 0";
            return out;
        }
    }
    for (size_t next = 0; next < queue.size(); ++next) {
        const size_t cell = queue[next];
        for (size_t p = 0; p < sides.size(); ++p) {
            if (sides[p].size() != 2) {
                continue;
            }
            for (size_t s = 0; s < 2; ++s) {
                if (sides[p][s].cell == cell
                    && !assign(sides[p][1 - s].cell, *number[cell] - steps[p][s])) {
                    out.error = "a cell numbered twice, or below 0";
                    return out;
                }
            }
        }
    }
    double counted = 0.0;
    double kept = 0.0;
    std::vector<double> volumes(cells.size());
    for (size_t c = 0; c < cells.size(); ++c) {
        if (!number[c]) {
            out.error = "a cell left unnumbered";
            return out;
        }
        volumes[c] = volumeOf(cells[c]);
        counted += *number[c] * volumes[c];
        kept += *number[c] >= 1 ? volumes[c] : 0.0;
    }
    // The winding number integrates to the naive sweep's volume (the divergence theorem)
    auto agrees = [](double a, double b) {
        return std::abs(a - b) <= 1e-5 * std::max(std::abs(a), std::abs(b)) + 1e-7;
    };
    if (!agrees(counted, naive)) {
        out.error = fmt::format("the cells' volumes, {:.9g}, don't add up to the sweep's, {:.9g}",
                                counted, naive);
        return out;
    }

    // The union's boundary: the pieces between a kept cell and one of number 0 or the exterior,
    // oriented out of the kept cell
    NCollection_List<TopoDS_Shape> boundary;
    for (size_t p = 0; p < sides.size(); ++p) {
        std::vector<size_t> inKept;
        for (size_t s = 0; s < sides[p].size(); ++s) {
            if (*number[sides[p][s].cell] >= 1) {
                inKept.push_back(s);
            }
        }
        if (inKept.size() == 1) {
            boundary.Append(sides[p][inKept.front()].face);
        }
    }
    BOPAlgo_BuilderSolid builder;
    builder.SetShapes(boundary);
    builder.SetContext(context);
    builder.Perform();
    if (builder.HasErrors() || builder.HasWarnings() || builder.Areas().Extent() != 1) {
        out.error = "the union's faces don't make one solid";
        return out;
    }
    out.solid = builder.Areas().First();
    if (!agrees(volumeOf(out.solid), kept)) {
        out.error = "the union's volume isn't its cells'";
        out.solid.Nullify();
        return out;
    }
    // The history as a fuse's: only the images in the union (the maker's lists every cell's pieces),
    // so a face whose one piece is kept keeps its name, as a face a fuse notches does
    TopTools_IndexedMapOfShape inUnion;
    TopExp::MapShapes(out.solid, inUnion);
    out.history = new BRepTools_History();
    for (const TopoDS_Shape& solid : solids) {
        for (const TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
            TopTools_IndexedMapOfShape elements;
            TopExp::MapShapes(solid, type, elements);
            for (int i = 1; i <= elements.Extent(); ++i) {
                const TopoDS_Shape& element = elements(i);
                for (const TopoDS_Shape& image : history->Modified(element)) {
                    if (inUnion.Contains(image)) {
                        out.history->AddModified(element, image);
                    }
                }
                for (const TopoDS_Shape& image : history->Generated(element)) {
                    if (inUnion.Contains(image)) {
                        out.history->AddGenerated(element, image);
                    }
                }
            }
        }
    }
    return out;
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

/// How far the multisection pipe's \a sections reach about the path \a wire: for each, the largest
/// distance from its points (each wire's, or its vertices') to its own path point, the point of the
/// path nearest their middle. A section's box diagonal reaches 2.6 times a hexagon's circumradius
/// and armed the overlap check on multisection helix pipes whose tubes stay clear (sweeps 11).
double sectionsReach(const TopoDS_Wire& wire, const std::vector<TopoDS_Shape>& sections)
{
    double reach = 0.0;
    for (const TopoDS_Shape& section : sections) {
        std::vector<gp_Pnt> points;
        for (TopExp_Explorer it(section, TopAbs_WIRE); it.More(); it.Next()) {
            const std::vector<gp_Pnt> along = pointsAlong(TopoDS::Wire(it.Current()));
            points.insert(points.end(), along.begin(), along.end());
        }
        if (points.empty()) {
            for (TopExp_Explorer it(section, TopAbs_VERTEX); it.More(); it.Next()) {
                points.push_back(BRep_Tool::Pnt(TopoDS::Vertex(it.Current())));
            }
        }
        if (points.empty()) {
            continue;
        }
        gp_XYZ sum(0, 0, 0);
        for (const gp_Pnt& point : points) {
            sum += point.XYZ();
        }
        const gp_Pnt middle(sum / static_cast<double>(points.size()));
        BRepExtrema_DistShapeShape nearest(BRepBuilderAPI_MakeVertex(middle).Vertex(), wire);
        if (!nearest.IsDone() || nearest.NbSolution() < 1) {
            continue;
        }
        const gp_Pnt onPath = nearest.PointOnShape2(1);
        for (const gp_Pnt& point : points) {
            reach = std::max(reach, onPath.Distance(point));
        }
    }
    return reach;
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

/// The direction of \a spine (its edges in order) where it passes nearest \a point, the way it
/// runs: none at a corner, where its edges' directions differ
std::optional<gp_Dir> spineDirectionNear(const std::vector<TopoDS_Edge>& spine, const gp_Pnt& point)
{
    std::vector<std::pair<double, gp_Dir>> candidates;  // distance, direction
    for (const TopoDS_Edge& edge : spine) {
        BRepAdaptor_Curve curve(edge);
        const bool reversed = edge.Orientation() == TopAbs_REVERSED;
        auto add = [&](double at) {
            gp_Pnt on;
            gp_Vec tangent;
            curve.D1(at, on, tangent);
            if (tangent.Magnitude() > gp::Resolution()) {
                candidates.emplace_back(on.Distance(point), reversed ? -tangent : tangent);
            }
        };
        add(curve.FirstParameter());
        add(curve.LastParameter());
        Extrema_ExtPC extrema(point, curve);
        for (int i = 1; extrema.IsDone() && i <= extrema.NbExt(); ++i) {
            if (extrema.IsMin(i)) {
                add(extrema.Point(i).Parameter());
            }
        }
    }
    if (candidates.empty()) {
        return std::nullopt;
    }
    const auto nearest = std::ranges::min_element(candidates, {}, [](const auto& c) { return c.first; });
    for (const auto& [distance, direction] : candidates) {
        if (distance < nearest->first + Precision::Confusion()
            && direction.Angle(nearest->second) > 1e-6) {
            return std::nullopt;
        }
    }
    return nearest->second;
}

/// Where \a spine (its edges in order) passes nearest \a point, as the edge's index plus the
/// fraction of its parameter range covered the way the spine runs, so a corner is one place: none
/// where two places along it are as near (the start and end of a closed spine)
std::optional<double> positionAlong(const std::vector<TopoDS_Edge>& spine, const gp_Pnt& point)
{
    std::vector<std::pair<double, double>> candidates;  // distance, position
    for (size_t i = 0; i < spine.size(); ++i) {
        BRepAdaptor_Curve curve(spine[i]);
        const bool reversed = spine[i].Orientation() == TopAbs_REVERSED;
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        if (last - first < gp::Resolution()) {
            continue;
        }
        auto add = [&](double at) {
            const double fraction = (reversed ? last - at : at - first) / (last - first);
            candidates.emplace_back(
                curve.Value(at).Distance(point),
                static_cast<double>(i) + fraction
            );
        };
        add(first);
        add(last);
        Extrema_ExtPC extrema(point, curve);
        for (int j = 1; extrema.IsDone() && j <= extrema.NbExt(); ++j) {
            if (extrema.IsMin(j)) {
                add(extrema.Point(j).Parameter());
            }
        }
    }
    if (candidates.empty()) {
        return std::nullopt;
    }
    const auto nearest =
        std::ranges::min_element(candidates, {}, [](const auto& c) { return c.first; });
    for (const auto& [distance, position] : candidates) {
        if (distance < nearest->first + Precision::Confusion()
            && std::abs(position - nearest->second) > 1e-6) {
            return std::nullopt;
        }
    }
    return nearest->second;
}

/// ops#396: the turn of each section of a pipe with several (\a sections, the first the profile,
/// as they are swept along \a spine) that decides how OCCT matches it with the one before, where
/// rounding would. OCCT pairs each section's vertices with the previous section's by the least sum
/// of their distances, in the sweep's frame, and looks at neither one's facing
/// (BRepFill_CompatibleWires::ComputeOrigin). Along lines joined "Transformed" that frame doesn't
/// turn, so two sections in perpendicular planes, each symmetric about the line they share
/// (squares, rectangles), give two pairings with exactly the same sum: the section turned with the
/// spine (the corner's limit from below 90 degrees), or against it, an inside-out solid. Rounding
/// chose, and Windows and macOS built different solids from one file. Such a section, facing the
/// spine's way, at most 1e-8 mm the far side of perpendicular to the one before (at its farthest
/// point, both as placed) and less than 1e-9 mm past perpendicular towards that one as it was
/// turned, is turned towards that one as turned until its farthest point is 1e-9 mm past
/// perpendicular, the pairing then as at a corner slightly under 90 degrees on every system, for
/// each pair of a chain in the sections' order along the spine. Beyond the far side, the pairing
/// against the spine is the only one OCCT finds, and the result gate stops the pipe. None for the
/// others. Sections turned about axes more than 1e-6 rad apart (right angles along a spine not in
/// one plane, or a section tilted out of a planar spine's plane while at a right angle to the one
/// before, review pr404-r6) set \a outOfPlane to the centre of the first turned about another:
/// there OCCT changes its pairing by itself within about 1e-7 rad under 90 degrees, so no turn
/// decides it (review pr404-r3: a valid solid 9 % short; with "Round corner" too, review
/// pr404-r4s), and the pipe stops (decision 228), whatever the transition and the spine's mode.
/// So it does with no corner between the sections: along a smooth spine out of one plane OCCT
/// gave a valid solid up to 2.8 % off in every mode, depending on the scale (review pr404-r5s,
/// hexagons the last turned 30 degrees), and with a corner then an arc 0.3 % off ("Round
/// corner", squares).
std::vector<std::optional<gp_Trsf>> sectionTiltsAlong(
    const std::vector<TopoDS_Shape>& sections,
    const TopoDS_Wire& spine,
    std::optional<gp_Pnt>& outOfPlane
)
{
    constexpr double past = 1e-9;   // mm, at the section's farthest point
    constexpr double reach = 1e-8;  // mm: within it the two sections are perpendicular
    struct Facing
    {
        gp_Dir placed;  // the spine's way, as the section is placed
        gp_Dir normal;  // the same once the section is turned
        gp_Pnt centre;
        double radius;
    };
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    auto facingOf = [&](const TopoDS_Shape& section) -> std::optional<Facing> {
        if (section.IsNull() || section.ShapeType() != TopAbs_WIRE) {
            return std::nullopt;
        }
        const std::vector<gp_Pnt> points = pointsAlong(TopoDS::Wire(section));
        if (points.empty()) {
            return std::nullopt;
        }
        gp_XYZ centre(0, 0, 0);
        for (const gp_Pnt& point : points) {
            centre += point.XYZ();
        }
        centre /= static_cast<double>(points.size());
        // about the centre, so the normal's rounding doesn't grow with the section's distance
        // from the origin, against the absolute reach and margin
        std::vector<gp_Pnt> centred;
        centred.reserve(points.size());
        for (const gp_Pnt& point : points) {
            centred.emplace_back(point.XYZ() - centre);
        }
        const std::optional<gp_Dir> normal = planeNormal(centred);
        if (!normal) {
            return std::nullopt;
        }
        double radius = 0;
        for (const gp_Pnt& point : points) {
            radius = std::max(radius, point.Distance(gp_Pnt(centre)));
        }
        const std::optional<gp_Dir> along = spineDirectionNear(edges, gp_Pnt(centre));
        // edge-on to the spine, or at its corner, the section's facing isn't known
        if (!along || std::abs(normal->Dot(*along)) < 1e-6 || radius < Precision::Confusion()) {
            return std::nullopt;
        }
        const gp_Dir facing = normal->Dot(*along) > 0 ? *normal : normal->Reversed();
        return Facing {facing, facing, gp_Pnt(centre), radius};
    };
    std::vector<std::optional<gp_Trsf>> tilts(sections.size());
    // OCCT sweeps the sections in their order along the spine, whatever their order in the list,
    // and pairs each with the one before it there; where that order can't be told (a section
    // that isn't a wire, one as near two places of the spine, two at one place) none is turned
    std::vector<std::pair<double, size_t>> order;  // position along the spine, index
    for (size_t i = 0; i < sections.size(); ++i) {
        if (sections[i].IsNull() || sections[i].ShapeType() != TopAbs_WIRE) {
            return tilts;
        }
        const std::vector<gp_Pnt> points = pointsAlong(TopoDS::Wire(sections[i]));
        if (points.empty()) {
            return tilts;
        }
        gp_XYZ centre(0, 0, 0);
        for (const gp_Pnt& point : points) {
            centre += point.XYZ();
        }
        const std::optional<double> position =
            positionAlong(edges, gp_Pnt(centre / static_cast<double>(points.size())));
        if (!position) {
            return tilts;
        }
        order.emplace_back(*position, i);
    }
    std::ranges::sort(order);
    for (size_t k = 1; k < order.size(); ++k) {
        if (order[k].first - order[k - 1].first < 1e-6) {
            return tilts;
        }
    }
    std::optional<Facing> previous;
    std::optional<gp_Dir> turnedAbout;  // the axis of the latest turn
    for (const auto& [position, i] : order) {
        std::optional<Facing> current = facingOf(sections[i]);
        if (previous && current) {
            // whether the two are perpendicular is read from the sections as placed, so the band
            // doesn't move with the previous one's turn; how far to turn this one is measured
            // against the previous one as turned: against its plane before the turn, a section as
            // large or larger would be on its far side, and one placed less than the margin past
            // perpendicular can be short of it against the previous one as turned (review
            // pr404-r3s T1)
            const double placedOffset = current->placed.Dot(previous->placed) * current->radius;
            const double offset = current->placed.Dot(previous->normal) * current->radius;
            const double angle = (past - offset) / current->radius;
            if (placedOffset > -reach && offset < past && angle < 1e-6) {
                // turning the normal about (normal x previous) turns it towards the previous
                const gp_Dir axis = current->placed.Crossed(previous->normal);
                // in one plane the turns' axes are parallel, either way; within the bound of
                // the turns themselves (1e-6 rad), so a section tilted out of the plane by
                // rounding of its placement (5e-9 rad for a sketch turned about a leg nearly
                // along -Z) still counts as in it
                if (turnedAbout && !axis.IsParallel(*turnedAbout, 1e-6)) {
                    outOfPlane = current->centre;
                    return tilts;
                }
                turnedAbout = axis;
                gp_Trsf tilt;
                tilt.SetRotation(gp_Ax1(current->centre, axis), angle);
                tilts[i] = tilt;
                current->normal.Transform(tilt);
            }
        }
        previous = current;
    }
    return tilts;
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

/// What a name says, in three numbers taken from the name's own text and the name table's nodes,
/// without writing the name out (NameDigester)
struct NameDigest
{
    /// Of the name without the tags of its sections and of the names in them, at every depth
    std::uint64_t bare = 0;
    /// Of the name as it is
    std::uint64_t tagged = 0;
    /// The length of the name in full form, each tag one character; at most sizeCap
    std::uint64_t size = 0;
    /// The delimiters in that form: each takes one more character where the name is linked
    std::uint64_t delimiters = 0;
    /// Whether every node the name refers to is in the name table
    bool whole = true;
};

/** The digests of names (ops#640).
 *
 * A name in full form holds the names it links in full, and a split piece its whole history, so
 * one name can be gigabytes long while the name table holds it in a few dozen nodes
 * (`notes\name-growth.md`). Written out with NameTable::toPlain(), a Pipe's spine edges' names
 * cost minutes and kept gigabytes (`notes\pipe-corner-names-memory.md`). The digest of a name is
 * made from its sections' fields and the digests of the names in them, each node of the table
 * once, so its cost follows the number of nodes and not the name's length. It is the same for
 * the full, the interned and any mixed form of one name (the digest of a name is that of its
 * sections in turn, so a prefix's digest is where its piece's starts), and the same on every
 * platform.
 *
 * A node's digest is kept for the process's life: an entry of the table never changes or goes.
 * One that refers to a node the table doesn't have (the entry may still be loaded) isn't kept.
 */
class NameDigester
{
public:
    static constexpr std::uint64_t sizeCap = std::uint64_t {1} << 62U;

    /// The digest of \a name, a name in any form
    NameDigest of(std::string_view name)
    {
        NameDigest result = empty();
        bool first = true;
        forEachTopLevel(name, *Data::NAME_SECTION_DELIMINATOR, [&](std::string_view section) {
            const auto prefix = first ? Data::NameTable::parseRef(section) : std::nullopt;
            first = false;
            result = prefix ? ofNode(*prefix) : extended(result, ofSection(section));
        });
        return result;
    }

private:
    struct IdHash
    {
        std::size_t operator()(const Data::NameId& id) const
        {
            std::size_t value = 0;
            std::memcpy(&value, id.bytes().data(), sizeof(value));
            return value;
        }
    };

    /// FNV-1a, 64 bits: fed bytes, and numbers as their eight bytes from the lowest
    struct Hash
    {
        std::uint64_t value = 14695981039346656037ULL;

        void add(unsigned char byte)
        {
            value ^= byte;
            value *= 1099511628211ULL;
        }
        void add(std::string_view text)
        {
            for (const char c : text) {
                add(static_cast<unsigned char>(c));
            }
        }
        void add(std::uint64_t number)
        {
            for (int k = 0; k < 8; ++k) {
                add(static_cast<unsigned char>(number >> (8U * static_cast<unsigned>(k))));
            }
        }
    };

    /// Calls \a visit with each part of \a text between top-level \a delimiter characters: one
    /// inside an embedded name is escaped, so it has a `^` right before it (NameTable.cpp)
    template<typename Visit>
    static void forEachTopLevel(std::string_view text, char delimiter, Visit visit)
    {
        std::size_t start = 0;
        for (std::size_t i = 0; i < text.size(); ++i) {
            if (text[i] == delimiter && (i == 0 || text[i - 1] != *Data::SUB_SECTION_ESCAPE_CHAR)) {
                visit(text.substr(start, i - start));
                start = i + 1;
            }
        }
        visit(text.substr(start));
    }

    /// One level of unescaping, as the decoder does it: the first `^` of each run goes
    static std::string unescapedOnce(std::string_view text)
    {
        std::string result;
        result.reserve(text.size());
        bool afterCaret = false;
        for (const char c : text) {
            if (c == *Data::SUB_SECTION_ESCAPE_CHAR && !afterCaret) {
                afterCaret = true;
                continue;
            }
            afterCaret = c == *Data::SUB_SECTION_ESCAPE_CHAR;
            result += c;
        }
        return result;
    }

    static std::uint64_t capped(std::uint64_t size)
    {
        return std::min(size, sizeCap);
    }

    /// The delimiters in  text, a field that holds no names
    static std::uint64_t delimitersIn(std::string_view text)
    {
        return static_cast<std::uint64_t>(std::ranges::count_if(text, [](char c) {
            return c == *Data::NAME_SECTION_DELIMINATOR || c == *Data::SECTION_SUB_DELIMINATOR
                || c == *Data::SUB_SECTION_LIST_DELIMINATOR;
        }));
    }

    /// The digest of a name of no section
    static NameDigest empty()
    {
        return {Hash().value, Hash().value, 0, 0, true};
    }

    /// The digest of the name of digest \a name with the section of digest \a section added
    static NameDigest extended(const NameDigest& name, const NameDigest& section)
    {
        Hash bare {name.bare};
        bare.add(section.bare);
        Hash tagged {name.tagged};
        tagged.add(section.tagged);
        // The `|` between them, but for a name's first section
        const std::uint64_t bar = name.size > 0 ? 1 : 0;
        return {
            bare.value,
            tagged.value,
            capped(capped(name.size + section.size) + bar),
            capped(capped(name.delimiters + section.delimiters) + bar),
            name.whole && section.whole
        };
    }

    /// The digest of the section \a section. A text that isn't a V2 section (a sketch's name, an
    /// element's index) is taken as it is.
    NameDigest ofSection(std::string_view section)
    {
        int count = 0;
        forEachTopLevel(section, *Data::SECTION_SUB_DELIMINATOR, [&count](std::string_view) {
            ++count;
        });
        Hash bare;
        Hash tagged;
        if (count <= Data::SECTION_CONNECTED_ELEMENTS_INDEX) {
            bare.add(section);
            return {bare.value, bare.value, capped(section.size()), delimitersIn(section), true};
        }
        // The fields' delimiters, and the tag's one character
        std::uint64_t size = static_cast<std::uint64_t>(count);
        std::uint64_t delimiters = static_cast<std::uint64_t>(count) - 1;
        bool whole = true;
        int field = 0;
        forEachTopLevel(section, *Data::SECTION_SUB_DELIMINATOR, [&](std::string_view text) {
            const int at = field++;
            bare.add(static_cast<unsigned char>(*Data::SECTION_SUB_DELIMINATOR));
            tagged.add(static_cast<unsigned char>(*Data::SECTION_SUB_DELIMINATOR));
            if (at == Data::SECTION_ITERATION_TAG_INDEX) {
                tagged.add(text);
                return;
            }
            const bool names = at == Data::SECTION_LINKED_NAME_INDEX
                || at == Data::SECTION_CONNECTED_ELEMENTS_INDEX;
            if (!names || text.empty() || text == Data::EMPTY_VALUE) {
                bare.add(text);
                tagged.add(text);
                size = capped(size + text.size());
                delimiters = capped(delimiters + delimitersIn(text));
                return;
            }
            bool first = true;
            forEachTopLevel(text, *Data::SUB_SECTION_LIST_DELIMINATOR, [&](std::string_view entry) {
                // An entry without a caret is its own unescaped form
                const NameDigest name = entry.find(*Data::SUB_SECTION_ESCAPE_CHAR)
                        == std::string_view::npos
                    ? of(entry)
                    : of(unescapedOnce(entry));
                bare.add(static_cast<unsigned char>(*Data::SUB_SECTION_LIST_DELIMINATOR));
                bare.add(name.bare);
                tagged.add(static_cast<unsigned char>(*Data::SUB_SECTION_LIST_DELIMINATOR));
                tagged.add(name.tagged);
                // The name, a caret before each of its delimiters, and the `,` before it
                const std::uint64_t comma = first ? 0 : 1;
                first = false;
                size = capped(capped(capped(size + name.size) + name.delimiters) + comma);
                delimiters = capped(capped(delimiters + name.delimiters) + comma);
                whole = whole && name.whole;
            });
        });
        return {bare.value, tagged.value, size, delimiters, whole};
    }

    /// The digest of the name of the table's node \a id. A split piece's node refers to its
    /// prefix's, as deep as the element's history is long: the chain is walked in a loop.
    NameDigest ofNode(const Data::NameId& id)
    {
        const Data::NameTable& table = Data::NameTable::instance();
        // The nodes from \a id down its prefixes whose digests aren't known, each with its last
        // section; the last of them with its whole content when no prefix is below it
        std::vector<std::pair<Data::NameId, std::string>> chain;
        NameDigest name = empty();
        bool below = false;
        for (Data::NameId at = id;;) {
            if (const auto it = known.find(at); it != known.end()) {
                name = it->second;
                below = true;
                break;
            }
            std::optional<std::string> content = table.lookup(at);
            if (!content) {
                // An unknown node: its reference stands for it
                Hash hash;
                hash.add(Data::NameTable::makeRef(at));
                name = {hash.value, hash.value, Data::NameTable::RefLength, 0, false};
                below = true;
                break;
            }
            const std::size_t bar = Data::NameTable::lastTopLevelBar(*content);
            const auto prefix = bar == std::string::npos
                ? std::nullopt
                : Data::NameTable::parseRef(std::string_view(*content).substr(0, bar));
            if (!prefix) {
                chain.emplace_back(at, std::move(*content));
                break;
            }
            chain.emplace_back(at, content->substr(bar + 1));
            at = *prefix;
        }
        for (auto it = chain.rbegin(); it != chain.rend(); ++it) {
            name = below ? extended(name, ofSection(it->second)) : of(it->second);
            below = true;
            if (name.whole) {
                known.emplace(it->first, name);
            }
        }
        return name;
    }

    std::unordered_map<Data::NameId, NameDigest, IdHash> known;
};

/// The digest of \a name, a name in any form (NameDigester)
NameDigest digestOf(std::string_view name)
{
    static std::mutex guard;
    static NameDigester digester;
    const std::scoped_lock lock(guard);
    return digester.of(name);
}

/// The length in full form (NameDigest::size) up to which a spine edge's name is keyed by its
/// text, as it always was; a longer one is keyed by its digest (firstName). Its text costs about
/// 5 microseconds a byte to key and stays in the decoder's cache, so at this length a corner
/// costs a tenth of a second.
constexpr std::uint64_t textKeyLimit = 16384;

/// What starts the token that stands for a name too long to write out (firstName):
/// `#pcd;<the name's digest without tags>;<its last tag>;<its digest with tags>`, the digests
/// 16 hex digits each. No name starts so: a V2 name starts with an element's reference, `_` or
/// `~`, and a V1 name's `#` is followed by hex digits.
constexpr std::string_view digestMark = "#pcd;";
constexpr std::size_t digestDigits = 16;

/// The tag of the last section of \a name, a V2 name in any form; 0 for any other name. Only
/// the last section is read.
long lastSectionTag(std::string_view name)
{
    std::optional<std::string> content;
    if (const auto ref = Data::NameTable::parseRef(name)) {
        content = Data::NameTable::instance().lookup(*ref);
        if (!content) {
            return 0;
        }
        name = *content;
    }
    const std::size_t bar = Data::NameTable::lastTopLevelBar(name);
    const std::string_view section = bar == std::string_view::npos ? name : name.substr(bar + 1);
    std::vector<std::string_view> fields;
    std::size_t start = 0;
    for (std::size_t i = 0; i <= section.size(); ++i) {
        if (i == section.size()
            || (section[i] == *Data::SECTION_SUB_DELIMINATOR
                && (i == 0 || section[i - 1] != *Data::SUB_SECTION_ESCAPE_CHAR))) {
            fields.push_back(section.substr(start, i - start));
            start = i + 1;
        }
    }
    if (static_cast<int>(fields.size()) <= Data::SECTION_CONNECTED_ELEMENTS_INDEX) {
        return 0;
    }
    try {
        return std::stol(std::string(fields[Data::SECTION_ITERATION_TAG_INDEX]));
    }
    catch (const std::exception&) {
        return 0;
    }
}

/// The V2 name \a name with the tags of its sections, and of the names in them, left out: what
/// it says without the IDs of the objects that made it; of a long name's token (digestMark),
/// its part without tags. Any other name as it is.
std::string withoutTags(const std::string& name)
{
    if (name.starts_with(digestMark)) {
        return name.substr(0, digestMark.size() + digestDigits);
    }
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

/// The tag of the V2 name \a name's last section, the object that made it, also from a long
/// name's token (digestMark); 0 for any other name
long lastTag(const std::string& name)
{
    if (name.starts_with(digestMark)) {
        try {
            return std::stol(name.substr(digestMark.size() + digestDigits + 1));
        }
        catch (const std::exception&) {
            return 0;
        }
    }
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
/// (`E<n>`, `V<n>`).
/// A name longer than textKeyLimit isn't written out: its token stands for it (digestMark), the
/// same text for the same name and another for another, which withoutTags() and lastTag() read
/// as they read a name (ops#640). In full, a name of 2.5 MB cost 11 s a corner and kept 45 MB,
/// and a real document's names reach half a gigabyte (`notes\pipe-corner-names-memory.md`). The
/// names the callers key, compare and store stay what they were up to the limit, so no corner's
/// key changes there.
std::string firstName(const Part::TopoShape& path, const TopoDS_Shape& element)
{
    const int index = path.findShape(element);
    const std::string& typeName = Part::TopoShape::shapeName(element.ShapeType());
    std::vector<std::string> names;
    if (index > 0) {
        for (const auto& [name, sids] :
             path.getElementMappedNames(Data::IndexedName::fromConst(typeName.c_str(), index))) {
            const std::string text = name.toString();
            const NameDigest digest = digestOf(text);
            if (digest.size <= textKeyLimit) {
                names.push_back(Data::NameTable::instance().toPlain(text));
                continue;
            }
            Base::Console().log(
                "Pipe: a spine name of about %llu bytes is keyed by its digest\n",
                static_cast<unsigned long long>(digest.size)
            );
            names.push_back(
                fmt::format(
                    "{}{:016x};{};{:016x}",
                    digestMark,
                    digest.bare,
                    lastSectionTag(text),
                    digest.tagged
                )
            );
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
            const double along = side * normal.Dot(gp_Dir(tangent));
            // Edge-on at the spine's very end, not past: sound (Onshape, SW2: Keep orientation
            // along a quarter arc that ends edge-on, 251.326)
            const bool reversed = edge.Orientation() == TopAbs_REVERSED;
            const bool atEnd = &edge == &edges.back() && i == (reversed ? 0 : looks);
            if (along < 1e-9 && !(atEnd && along > -1e-9)) {
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

/// The gap of a path whose edges make several wires: the two nearest ends of different wires (or
/// free edges). None when it is one wire.
std::optional<std::pair<gp_Pnt, gp_Pnt>> pathGap(const TopoDS_Shape& path)
{
    std::vector<std::vector<gp_Pnt>> ends;
    for (TopExp_Explorer it(path, TopAbs_WIRE); it.More(); it.Next()) {
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopExp::Vertices(TopoDS::Wire(it.Current()), first, last);
        std::vector<gp_Pnt> points;
        for (const TopoDS_Vertex& vertex : {first, last}) {
            if (!vertex.IsNull()) {
                points.push_back(BRep_Tool::Pnt(vertex));
            }
        }
        ends.push_back(points);
    }
    for (TopExp_Explorer it(path, TopAbs_EDGE, TopAbs_WIRE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        ends.push_back(
            {BRep_Tool::Pnt(TopExp::FirstVertex(edge)), BRep_Tool::Pnt(TopExp::LastVertex(edge))}
        );
    }
    std::optional<std::pair<gp_Pnt, gp_Pnt>> gap;
    double nearest = std::numeric_limits<double>::infinity();
    for (size_t i = 0; i < ends.size(); ++i) {
        for (size_t j = i + 1; j < ends.size(); ++j) {
            for (const gp_Pnt& a : ends[i]) {
                for (const gp_Pnt& b : ends[j]) {
                    if (a.Distance(b) < nearest) {
                        nearest = a.Distance(b);
                        gap = std::make_pair(a, b);
                    }
                }
            }
        }
    }
    return gap;
}

/// Where a profile lies against its path (Onshape's Sweep, notes\sweep-design.md; skeptic c721,
/// finding 3): the path's point nearest the profile's centre, and whether another point lies as
/// near
struct ProfileFoot
{
    /// The profile's centre: its wires' centre of mass, by length
    gp_Pnt centre;
    /// The path's point nearest it
    gp_Pnt at;
    double distance = 0;
    /// Another point of the path as near, apart from `at`: the foot point is ambiguous
    std::optional<gp_Pnt> tie;
    /// The profile's largest extent along the axes
    double size = 0;
    /// Whether `at` is an end of the path (always, for a closed path)
    bool atEnd = true;
};

/// Equal distances of a tie: rounding noise only (a profile at the centre of an arc is the same
/// distance from all of it, within 1e-15 mm)
constexpr double tieTolerance = 10 * Precision::Confusion();

/// Where the profile of \a wires lies against \a path (ProfileFoot)
ProfileFoot profileFoot(const std::vector<TopoDS_Shape>& wires, const TopoDS_Wire& path)
{
    ProfileFoot foot;
    GProp_GProps lengths;
    Bnd_Box box;
    for (const TopoDS_Shape& wire : wires) {
        GProp_GProps one;
        BRepGProp::LinearProperties(wire, one);
        lengths.Add(one);
        BRepBndLib::Add(wire, box);
    }
    foot.centre = lengths.CentreOfMass();
    if (!box.IsVoid()) {
        double x0 = 0, y0 = 0, z0 = 0, x1 = 0, y1 = 0, z1 = 0;
        box.Get(x0, y0, z0, x1, y1, z1);
        foot.size = std::max({x1 - x0, y1 - y0, z1 - z0});
    }
    // The candidates: every vertex (the ends of an arc about the centre, which is as near
    // everywhere, among them) and each edge's nearest points
    std::vector<std::pair<gp_Pnt, double>> candidates;
    for (TopExp_Explorer it(path, TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        for (const TopoDS_Vertex& vertex : {TopExp::FirstVertex(edge), TopExp::LastVertex(edge)}) {
            const gp_Pnt point = BRep_Tool::Pnt(vertex);
            candidates.emplace_back(point, point.Distance(foot.centre));
        }
        const BRepAdaptor_Curve curve(edge);
        Extrema_ExtPC extrema(foot.centre, curve);
        if (extrema.IsDone()) {
            for (int i = 1; i <= extrema.NbExt(); ++i) {
                if (extrema.IsMin(i)) {
                    candidates.emplace_back(
                        extrema.Point(i).Value(),
                        std::sqrt(extrema.SquareDistance(i))
                    );
                }
            }
        }
    }
    if (candidates.empty()) {
        return foot;
    }
    auto nearest = candidates.begin();
    for (auto it = candidates.begin(); it != candidates.end(); ++it) {
        if (it->second < nearest->second) {
            nearest = it;
        }
    }
    foot.at = nearest->first;
    foot.distance = nearest->second;
    for (const auto& [point, distance] : candidates) {
        if (distance < foot.distance + tieTolerance && point.Distance(foot.at) > tieTolerance) {
            foot.tie = point;
            break;
        }
    }
    if (!BRep_Tool::IsClosed(path)) {
        if (const std::optional<std::array<gp_Pnt, 2>> ends = wireEnds(path)) {
            foot.atEnd = foot.at.Distance((*ends)[0]) < tieTolerance
                || foot.at.Distance((*ends)[1]) < tieTolerance;
        }
    }
    return foot;
}

/// The path from the profile's foot point one way (Extend to full path off)
struct OneWay
{
    Part::TopoShape path;
};

/// \a path from \a at, which lies on it, to the end that runs against \a normal (with \a
/// reversed, along it): the edges past it whole, with their names, and the edge it lies on cut
/// there. None where the path runs edge-on to \a normal at \a at.
std::optional<OneWay> oneWayFrom(
    const Part::TopoShape& path,
    const gp_Pnt& at,
    const gp_Dir& normal,
    bool reversed
)
{
    const std::vector<TopoDS_Edge> edges = edgesInOrder(TopoDS::Wire(path.getShape()));
    for (size_t k = 0; k < edges.size(); ++k) {
        const TopoDS_Edge& edge = edges[k];
        double first = 0;
        double last = 0;
        const Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);
        if (curve.IsNull()) {
            continue;
        }
        GeomAPI_ProjectPointOnCurve projection(at, curve, first, last);
        if (projection.NbPoints() == 0 || projection.LowerDistance() > tieTolerance) {
            continue;
        }
        const double u = projection.LowerDistanceParameter();
        const bool forward = edge.Orientation() != TopAbs_REVERSED;
        gp_Pnt point;
        gp_Vec tangent;
        curve->D1(u, point, tangent);
        if (!forward) {
            tangent.Reverse();
        }
        if (tangent.Magnitude() < gp::Resolution()
            || std::abs(gp_Dir(tangent).Dot(normal)) < std::sin(std::numbers::pi / 180)) {
            return std::nullopt;
        }
        // Along the path's order where its tangent runs against the normal
        const bool ahead = (gp_Dir(tangent).Dot(normal) < 0) != reversed;
        std::vector<Part::TopoShape> kept;
        auto whole = [&](size_t i) {
            const int index = path.findShape(edges[i]);
            kept.push_back(index > 0 ? path.getSubTopoShape(TopAbs_EDGE, index) : Part::TopoShape(edges[i]));
        };
        // The cut edge's part on the kept side, in its curve's parameters
        const double from = ahead == forward ? u : first;
        const double to = ahead == forward ? last : u;
        if (to - from > Precision::PConfusion()
            && BRepAdaptor_Curve(edge).Value(from).Distance(BRepAdaptor_Curve(edge).Value(to))
                > Precision::Confusion()) {
            kept.emplace_back(BRepBuilderAPI_MakeEdge(curve, from, to).Edge());
        }
        if (ahead) {
            for (size_t i = k + 1; i < edges.size(); ++i) {
                whole(i);
            }
        }
        else {
            for (size_t i = 0; i < k; ++i) {
                whole(i);
            }
        }
        if (kept.empty()) {
            return std::nullopt;
        }
        OneWay result;
        result.path = Part::TopoShape(0, path.Hasher).makeElementWires(kept);
        if (result.path.isNull() || result.path.shapeType() != TopAbs_WIRE) {
            return std::nullopt;
        }
        return result;
    }
    return std::nullopt;
}

/// Whether \a path lies in a plane, or on a line, within a micrometre
bool isPlanarPath(const TopoDS_Wire& path)
{
    const std::vector<gp_Pnt> points = pointsAlong(path);
    if (points.size() < 4) {
        return true;
    }
    TColgp_Array1OfPnt array(1, static_cast<int>(points.size()));
    for (size_t i = 0; i < points.size(); ++i) {
        array.SetValue(static_cast<int>(i) + 1, points[i]);
    }
    const GProp_PEquation equation(array, 1e-3);
    return equation.IsPlanar() || equation.IsLinear() || equation.IsPoint();
}

/// The largest curvature of \a curve: an arc's, or sampled at least 64 times, 8 times a C2 piece
double largestCurvature(const BRepAdaptor_Curve& curve)
{
    if (curve.GetType() == GeomAbs_Line) {
        return 0;
    }
    if (curve.GetType() == GeomAbs_Circle) {
        return 1 / curve.Circle().Radius();
    }
    const int count = std::clamp(8 * curve.NbIntervals(GeomAbs_C2), 64, 1024);
    const double first = curve.FirstParameter();
    const double last = curve.LastParameter();
    double largest = 0;
    for (int i = 0; i <= count; ++i) {
        BRepLProp_CLProps props(curve, first + (last - first) * i / count, 2, Precision::Confusion());
        if (props.IsTangentDefined()) {
            largest = std::max(largest, props.Curvature());
        }
    }
    return largest;
}

/// The folds along the curved edges of \a spine of a section that no corner tilted, for the
/// sweeps measureCorners doesn't look at ("Right corner", "Round corner", or one edge): where the
/// path bends tighter than the profile reaches from it, the sweep runs back through itself, a
/// solid that BRepCheck passes, of negative volume (skeptic c721, finding 1; Onshape refuses a
/// self-intersecting sweep). Along an arc the section turns about, exact (foldAlongArc); along
/// another curve, from the section's sampled motion (foldAlongCurve), only where its sharpest
/// bend reaches the section at all: its curvature times the section's farthest point from the
/// spine at least 1. \a starts, \a setup, \a binormal: as measureCorners'.
CornerTilts foldsAlongCurves(
    const std::vector<TopoDS_Shape>& starts,
    const TopoDS_Wire& spine,
    const std::function<void(BRepOffsetAPI_MakePipeShell&)>& setup,
    const std::optional<gp_Dir>& binormal
)
{
    CornerTilts tilts;
    const std::vector<TopoDS_Edge> edges = edgesInOrder(spine);
    if (edges.empty() || starts.empty()) {
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
    const gp_Pnt spineStart = BRep_Tool::Pnt(TopExp::FirstVertex(edges.front(), true));
    double reach = 0;
    for (const gp_Pnt& point : startPoints) {
        reach = std::max(reach, point.Distance(spineStart));
    }
    for (size_t k = 0; k < edges.size(); ++k) {
        if (isLine(edges[k])) {
            continue;
        }
        const BRepAdaptor_Curve curve(edges[k]);
        if (largestCurvature(curve) * reach < 1 - 1e-9) {
            continue;
        }
        gp_Trsf motion;
        if (k > 0) {
            BRepBuilderAPI_MakeWire upTo;
            for (size_t i = 0; i < k; ++i) {
                upTo.Add(edges[i]);
            }
            const std::optional<std::vector<gp_Trsf>> motions
                = motionsAlong(upTo.Wire(), gp_Ax2(spineStart, *startNormal), 2, setup);
            if (!motions) {
                continue;
            }
            motion = motions->back();
        }
        const gp_Dir normal = startNormal->Transformed(motion);
        std::vector<gp_Pnt> points;
        for (const gp_Pnt& point : startPoints) {
            points.push_back(point.Transformed(motion));
        }
        const bool arc = curve.GetType() == GeomAbs_Circle;
        const bool aboutAxis = arc
            && (!binormal
                || std::abs(curve.Circle().Axis().Direction().Dot(*binormal))
                    > std::cos(tiltTolerance));
        const Reach found = aboutAxis ? foldAlongArc(edges[k], normal, points)
                                      : foldAlongCurve(edges[k], normal, points, setup, binormal);
        const gp_Pnt at = BRep_Tool::Pnt(TopExp::FirstVertex(edges[k], true));
        if (found.unchecked > 0 && !tilts.unchecked) {
            tilts.unchecked = {at, found.unchecked};
        }
        if (found.past < Precision::Confusion()) {
            continue;
        }
        const Fold fold {at, arc, false, found.past, found.across};
        if (found.past > smallFold * found.across) {
            tilts.folded = fold;
            return tilts;
        }
        if (!tilts.smallFold) {
            tilts.smallFold = fold;
        }
    }
    return tilts;
}
// Onshape's Sweep, slice 3 (notes\sweep-design.md 3): twist, scale and lock faces

/// A place on a path, its edges in order: the point, the tangent the way the path runs, the
/// second derivative there (by the arc length's direction, not normalized) and the length from
/// the path's start
struct PathSample
{
    gp_Pnt point;
    gp_Dir tangent;
    gp_Vec second;
    double length = 0.0;
};

/// Samples of \a edges (a wire's, in order), at least \a perEdge each and one per \a turn radians
/// of the edge's bend and \a perLength per unit of its length; each joint once
std::vector<PathSample> samplesAlong(
    const std::vector<TopoDS_Edge>& edges,
    int perEdge,
    double turn,
    double perLength = 0.0
)
{
    std::vector<PathSample> samples;
    double done = 0.0;
    for (const TopoDS_Edge& edge : edges) {
        BRepAdaptor_Curve curve(edge);
        const bool reversed = edge.Orientation() == TopAbs_REVERSED;
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        const double length = GCPnts_AbscissaPoint::Length(curve, first, last);
        int count = std::max(perEdge, static_cast<int>(std::ceil(length * perLength)));
        if (curve.GetType() != GeomAbs_Line) {
            // The bend: the tangent's turn summed over a fine sampling
            double bend = 0.0;
            gp_Pnt p;
            gp_Vec before;
            curve.D1(first, p, before);
            for (int i = 1; i <= 64; ++i) {
                gp_Vec now;
                curve.D1(first + (last - first) * i / 64, p, now);
                if (before.Magnitude() > gp::Resolution() && now.Magnitude() > gp::Resolution()) {
                    bend += before.Angle(now);
                }
                before = now;
            }
            count = std::max(count, static_cast<int>(std::ceil(bend / turn)));
        }
        const size_t from = samples.empty() ? 0 : 1;
        for (int i = static_cast<int>(from); i <= count; ++i) {
            const double t = static_cast<double>(i) / count;
            const double at = reversed ? last - t * (last - first) : first + t * (last - first);
            gp_Pnt point;
            gp_Vec d1, d2;
            curve.D2(at, point, d1, d2);
            if (reversed) {
                d1.Reverse();
            }
            if (d1.Magnitude() < gp::Resolution()) {
                continue;
            }
            PathSample sample;
            sample.point = point;
            sample.tangent = gp_Dir(d1);
            // The curvature vector: d2 less its part along d1, over |d1|^2
            const double speed2 = d1.SquareMagnitude();
            sample.second = (d2 - d1 * (d2.Dot(d1) / speed2)) / speed2;
            sample.length = done
                + (reversed ? GCPnts_AbscissaPoint::Length(curve, at, last)
                            : GCPnts_AbscissaPoint::Length(curve, first, at));
            samples.push_back(sample);
        }
        done += length;
    }
    return samples;
}

/// Where \a edges (in order) turn at a joint by more than a hundredth of a degree: the joint
std::optional<gp_Pnt> sharpJoint(const std::vector<TopoDS_Edge>& edges, bool closed)
{
    for (size_t i = 0; i < edges.size(); ++i) {
        if (i + 1 == edges.size() && !closed) {
            break;
        }
        const TopoDS_Edge& next = edges[(i + 1) % edges.size()];
        if (tangentAlong(edges[i], false).Angle(tangentAlong(next, true)) > 1.0e-2 * M_PI / 180.0) {
            return BRep_Tool::Pnt(TopExp::FirstVertex(next, true));
        }
    }
    return std::nullopt;
}

/// The frame's normal before the twist, one per sample, from \a normalAt where given, else
/// rotation-minimizing: carried from the start with the least turn (double reflection), which
/// on a plane is the plane's normal crossed with the tangent, as OCCT's corrected Frenet frame
std::vector<gp_Dir> carriedNormals(const std::vector<PathSample>& samples)
{
    std::vector<gp_Dir> normals;
    if (samples.empty()) {
        return normals;
    }
    const gp_Dir& t0 = samples.front().tangent;
    gp_Vec start = gp_Vec(t0).Crossed(gp_Vec(0, 0, 1));
    if (start.Magnitude() < 1.0e-3) {
        start = gp_Vec(t0).Crossed(gp_Vec(1, 0, 0));
    }
    normals.emplace_back(start);
    for (size_t i = 1; i < samples.size(); ++i) {
        const gp_Vec v1(samples[i - 1].point, samples[i].point);
        const double c1 = v1.SquareMagnitude();
        gp_Vec r = gp_Vec(normals.back());
        gp_Vec t = gp_Vec(samples[i - 1].tangent);
        if (c1 > gp::Resolution()) {
            r -= v1 * (2.0 / c1 * v1.Dot(r));
            t -= v1 * (2.0 / c1 * v1.Dot(t));
        }
        const gp_Vec v2 = gp_Vec(samples[i].tangent) - t;
        const double c2 = v2.SquareMagnitude();
        if (c2 > gp::Resolution()) {
            r -= v2 * (2.0 / c2 * v2.Dot(r));
        }
        // Square to the tangent again, against rounding
        r -= gp_Vec(samples[i].tangent) * r.Dot(gp_Vec(samples[i].tangent));
        normals.emplace_back(r);
    }
    return normals;
}

/// A guide through each sample at \a reach along its normal \a normals[i] turned by \a angles[i]
/// about the tangent: one B-spline edge through them all
std::optional<TopoDS_Wire> guideThrough(
    const std::vector<PathSample>& samples,
    const std::vector<gp_Dir>& normals,
    const std::vector<double>& angles,
    double reach
)
{
    if (samples.size() < 2) {
        return std::nullopt;
    }
    Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, static_cast<int>(samples.size()));
    for (size_t i = 0; i < samples.size(); ++i) {
        const gp_Vec n(normals[i]);
        const gp_Vec b = gp_Vec(samples[i].tangent).Crossed(n);
        const gp_Vec offset = (n * std::cos(angles[i]) + b * std::sin(angles[i])) * reach;
        points->SetValue(static_cast<int>(i) + 1, samples[i].point.Translated(offset));
    }
    GeomAPI_Interpolate interpolate(points, false, Precision::Confusion());
    interpolate.Perform();
    if (!interpolate.IsDone()) {
        return std::nullopt;
    }
    BRepBuilderAPI_MakeEdge edge(interpolate.Curve());
    if (!edge.IsDone()) {
        return std::nullopt;
    }
    return BRepBuilderAPI_MakeWire(edge.Edge()).Wire();
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
const char* Pipe::ProfileControlEnums[]
    = {"None", "Keep orientation", "Advanced", "Lock faces", "Lock direction", nullptr};
const char* Pipe::TwistTypeEnums[] = {"Turns", "Angle", "Pitch", nullptr};
const char* Pipe::BodyTypeEnums[] = {"Solid", "Thin", nullptr};


PROPERTY_SOURCE(PartDesign::Pipe, PartDesign::ProfileBased)

Pipe::Pipe()
{
    settingMode = true;
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
    // Onshape's Sweep (notes\sweep-design.md, decision 344)
    ADD_PROPERTY_TYPE(
        ProfileControl,
        (long(0)),
        "Sweep",
        App::Prop_None,
        "How the profile is carried along the path: None (it turns with the path), Keep "
        "orientation (it keeps its orientation), Advanced (the Mode property decides)"
    );
    ADD_PROPERTY_TYPE(
        ExtendToFullPath,
        (false),
        "Sweep",
        App::Prop_None,
        "A profile in the middle of the path sweeps both ways along all of it"
    );
    ADD_PROPERTY_TYPE(
        PathReversed,
        (false),
        "Sweep",
        App::Prop_None,
        "With 'Extend to full path' off, sweep the other way along the path from the profile"
    );
    ADD_PROPERTY_TYPE(
        SpineMore,
        (nullptr),
        "Sweep",
        App::Prop_None,
        "More path edges, from other objects: joined with the Spine's in any order"
    );
    // Slice 3 (notes\sweep-design.md 3; Onshape's defaults where known)
    ADD_PROPERTY_TYPE(
        LockFaces,
        (nullptr),
        "Sweep",
        App::Prop_None,
        "Faces the path lies on: with 'Lock faces' the profile keeps its angle to their normal"
    );
    ADD_PROPERTY_TYPE(
        LockDirection,
        (nullptr),
        "Sweep",
        App::Prop_None,
        "A plane, planar face or straight edge: with 'Lock direction' the profile's plane keeps containing its direction"
    );
    ADD_PROPERTY_TYPE(
        HasTwist,
        (false),
        "Sweep",
        App::Prop_None,
        "The profile turns about the path, linearly in its length"
    );
    ADD_PROPERTY_TYPE(
        TwistType,
        (long(1)),
        "Sweep",
        App::Prop_None,
        "The twist given as Turns, an Angle, or a Pitch (the length of one turn)"
    );
    ADD_PROPERTY_TYPE(
        Turns,
        (1.0),
        "Sweep",
        App::Prop_None,
        "The twist's turns from the profile to the path's end"
    );
    ADD_PROPERTY_TYPE(
        TwistAngle,
        (30.0),
        "Sweep",
        App::Prop_None,
        "The twist's angle from the profile to the path's end"
    );
    ADD_PROPERTY_TYPE(
        TwistPitch,
        (10.0),
        "Sweep",
        App::Prop_None,
        "The path's length for one turn of the twist"
    );
    ADD_PROPERTY_TYPE(
        TwistCCW,
        (false),
        "Sweep",
        App::Prop_None,
        "Counter-clockwise about the path's direction (off: clockwise)"
    );
    ADD_PROPERTY_TYPE(
        HasScale,
        (false),
        "Sweep",
        App::Prop_None,
        "The profile scales linearly in the path's length"
    );
    ADD_PROPERTY_TYPE(
        ScaleFactor,
        (1.0),
        "Sweep",
        App::Prop_None,
        "The profile's scale at the path's end"
    );
    ADD_PROPERTY_TYPE(
        BodyType,
        (long(0)),
        "Sweep",
        App::Prop_None,
        "Solid, or Thin: a wall around the profile's curves"
    );
    ADD_PROPERTY_TYPE(
        Thickness1,
        (1.0),
        "Sweep",
        App::Prop_None,
        "The thin wall's thickness"
    );
    ADD_PROPERTY_TYPE(
        Thickness2,
        (0.0),
        "Sweep",
        App::Prop_None,
        "The thin wall's thickness on the other side"
    );
    // The thin wall centred on the profile's curves: ProfileBased's Midplane (FeaturePipe.h)
    ADD_PROPERTY_TYPE(
        FlipWall,
        (false),
        "Sweep",
        App::Prop_None,
        "The thin wall on the other side of the profile's curves"
    );
    ADD_PROPERTY_TYPE(
        TrimEnds,
        (true),
        "Sweep",
        App::Prop_None,
        "Onshape's Thin option: no effect, as in Onshape"
    );
    TwistType.setEnums(TwistTypeEnums);
    BodyType.setEnums(BodyTypeEnums);
    Mode.setEnums(ModeEnums);
    Transition.setEnums(TransitionEnums);
    Transformation.setEnums(TransformEnums);
    ProfileControl.setEnums(ProfileControlEnums);
    settingMode = false;
}

void Pipe::onChanged(const App::Property* prop)
{
    const App::Document* doc = getDocument();
    const bool replaying = isRestoring() || (doc && doc->isPerformingTransaction());
    if (!settingMode && !replaying) {
        if (prop == &ProfileControl) {
            // None sweeps in Standard (with Frenet's frame where it is steady off a plane), Keep
            // orientation in Fixed: a translation, whatever the profile's plane
            // Lock faces sweeps in Standard along a guide (execute), Lock direction in Binormal
            static const long modes[] = {0, 1, -1, 0, 4};
            const long control = ProfileControl.getValue();
            const long mode = control >= 0 && control < 5 ? modes[control] : -1;
            if (mode >= 0 && Mode.getValue() != mode) {
                settingMode = true;
                Mode.setValue(mode);
                settingMode = false;
            }
        }
        else if (prop == &Mode && ProfileControl.getValue() != 2) {
            settingMode = true;
            ProfileControl.setValue(long(2));
            settingMode = false;
        }
    }
    ProfileBased::onChanged(prop);
}

std::optional<gp_Dir> Pipe::profileNormal(const TopLoc_Location& invObjLoc) const
{
    // A sketch's normal is its placement's Z, whichever way its curves run; a face's, its own
    gp_Dir normal;
    App::DocumentObject* profile = Profile.getValue();
    if (auto sketch = freecad_cast<Part::Part2DObject*>(profile)) {
        const Base::Vector3d z = sketch->Placement.getValue().getRotation().multVec(Base::Vector3d(0, 0, 1));
        normal = gp_Dir(z.x, z.y, z.z);
    }
    else if (auto feature = freecad_cast<Part::Feature*>(profile)) {
        const std::vector<std::string>& subs = Profile.getSubValues();
        if (subs.empty()) {
            return std::nullopt;
        }
        const Part::TopoShape face = feature->Shape.getShape().getSubTopoShape(subs.front().c_str(), true);
        if (face.isNull() || face.shapeType() != TopAbs_FACE) {
            return std::nullopt;
        }
        BRepAdaptor_Surface surface(TopoDS::Face(face.getShape()));
        if (surface.GetType() != GeomAbs_Plane) {
            return std::nullopt;
        }
        normal = surface.Plane().Axis().Direction();
        if (face.getShape().Orientation() == TopAbs_REVERSED) {
            normal.Reverse();
        }
    }
    else {
        return std::nullopt;
    }
    return normal.Transformed(invObjLoc.Transformation());
}

namespace
{
/// The shape of \a object's \a sub (all of it when empty), in the Body's coordinates
Part::TopoShape linkedShape(App::DocumentObject* object, const std::string& sub)
{
    if (!object) {
        return {};
    }
    return Part::Feature::getTopoShape(
        object,
        Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
            | Part::ShapeOption::NeedSubElement,
        sub.empty() ? nullptr : sub.c_str()
    );
}

/// LockDirection's direction: a plane's or planar face's normal, a straight edge's direction
std::optional<gp_Dir> directionOf(const Part::TopoShape& shape)
{
    if (shape.isNull()) {
        return std::nullopt;
    }
    TopExp_Explorer faces(shape.getShape(), TopAbs_FACE);
    if (faces.More()) {
        BRepAdaptor_Surface surface(TopoDS::Face(faces.Current()));
        if (surface.GetType() == GeomAbs_Plane) {
            return surface.Plane().Axis().Direction();
        }
        return std::nullopt;
    }
    TopExp_Explorer edges(shape.getShape(), TopAbs_EDGE);
    if (edges.More()) {
        BRepAdaptor_Curve curve(TopoDS::Edge(edges.Current()));
        if (curve.GetType() == GeomAbs_Line) {
            return curve.Line().Direction();
        }
    }
    return std::nullopt;
}

/// The surface normal of the nearest of \a faces at \a point, with its distance
std::pair<double, gp_Vec> nearestNormal(const std::vector<TopoDS_Face>& faces, const gp_Pnt& point)
{
    const TopoDS_Vertex vertex = BRepBuilderAPI_MakeVertex(point);
    double best = std::numeric_limits<double>::max();
    gp_Vec normal;
    for (const TopoDS_Face& face : faces) {
        BRepExtrema_DistShapeShape distance(vertex, face);
        if (!distance.IsDone() || distance.NbSolution() < 1 || distance.Value() >= best) {
            continue;
        }
        GeomAPI_ProjectPointOnSurf onSurface(distance.PointOnShape2(1), BRep_Tool::Surface(face));
        if (onSurface.NbPoints() < 1) {
            continue;
        }
        double u = 0, v = 0;
        onSurface.LowerDistanceParameters(u, v);
        gp_Pnt at;
        gp_Vec du, dv;
        BRep_Tool::Surface(face)->D1(u, v, at, du, dv);
        gp_Vec n = du.Crossed(dv);
        if (n.Magnitude() < gp::Resolution()) {
            continue;
        }
        if (face.Orientation() == TopAbs_REVERSED) {
            n.Reverse();
        }
        best = distance.Value();
        normal = n;
    }
    return {best, normal};
}
}  // namespace

std::optional<std::string> Pipe::prepareSlice3(
    const Part::TopoShape& path,
    const std::vector<TopoDS_Shape>& profileWires,
    const TopLoc_Location& invObjLoc,
    Handle(Law_Function)& scale
)
{
    frameGuide.Nullify();
    const long control = ProfileControl.getValue();
    // Onshape offers twist only with None and Keep orientation (SW0): the lock modes ignore it
    const bool twist = HasTwist.getValue() && control != 3 && control != 4;
    const bool scaled = HasScale.getValue();
    const bool lockFaces = control == 3;
    if (!twist && !scaled && !lockFaces) {
        return std::nullopt;
    }
    const gp_Trsf toBody = invObjLoc.Inverted().Transformation();
    auto inPlace = [&](const gp_Pnt& point) {
        return pointText(point.Transformed(toBody));
    };
    if (path.shapeType() != TopAbs_WIRE || profileWires.empty()) {
        return std::string(
            "Pipe: twist, scale and 'Lock faces' sweep one profile along a path, without Sections"
        );
    }
    const TopoDS_Wire& wire = TopoDS::Wire(path.getShape());
    const bool closed = BRep_Tool::IsClosed(wire);
    if ((twist || scaled) && closed) {
        return std::string(
            "Pipe: twist and scale run from the profile to the path's end, and this path is "
            "closed. Open the path, or turn twist and scale off."
        );
    }
    if (twist && control != 0 && control != 3 && control != 4) {
        return std::string(
            "Pipe: twist turns the profile about the path from the frame it is carried in: use "
            "the profile control None, Lock faces or Lock direction ('Keep orientation' and "
            "'Advanced' have no such frame)."
        );
    }
    const std::vector<TopoDS_Edge> edges = edgesInOrder(wire);
    if (twist || lockFaces) {
        if (const std::optional<gp_Pnt> joint = sharpJoint(edges, closed)) {
            const char* what = twist ? "twist" : "'Lock faces'";
            return fmt::format(
                "Pipe: {} needs a smooth path, and the path turns sharply at {}. Round the corner, "
                "or turn {} off.",
                what,
                inPlace(*joint),
                what
            );
        }
    }
    std::vector<PathSample> samples = samplesAlong(edges, 16, M_PI / 32);
    if (samples.size() < 2) {
        return std::string("Pipe: the path has no length");
    }
    const double total = samples.back().length;

    // Where the profile lies along the path, and the end the scale and twist reach their values
    // at: the far end from a profile at one end; from one in the middle (Extend to full path
    // on), the end it would sweep to with the option off, and they go on linearly past the
    // profile the other way (Onshape, SW12)
    const ProfileFoot foot = profileFoot(profileWires, wire);
    size_t nearest = 0;
    for (size_t i = 1; i < samples.size(); ++i) {
        if (samples[i].point.Distance(foot.at) < samples[nearest].point.Distance(foot.at)) {
            nearest = i;
        }
    }
    double from = samples[nearest].length;
    double before = 0.0;
    for (const TopoDS_Edge& edge : edges) {
        // The foot's own place, more exactly than the nearest sample
        BRepAdaptor_Curve curve(edge);
        const double length = GCPnts_AbscissaPoint::Length(curve);
        Extrema_ExtPC extrema(foot.at, curve);
        if (extrema.IsDone()) {
            for (int i = 1; i <= extrema.NbExt(); ++i) {
                if (extrema.SquareDistance(i) > tieTolerance * tieTolerance) {
                    continue;
                }
                const double at = extrema.Point(i).Parameter();
                from = before
                    + (edge.Orientation() == TopAbs_REVERSED
                           ? GCPnts_AbscissaPoint::Length(curve, at, curve.LastParameter())
                           : GCPnts_AbscissaPoint::Length(curve, curve.FirstParameter(), at));
            }
        }
        before += length;
    }
    if (foot.atEnd) {
        from = from < total / 2 ? 0.0 : total;
    }
    double to = from < total / 2 ? total : 0.0;
    if (!foot.atEnd) {
        // Twist too (SW17): reached at the one-way end, going on past the profile the other way
        const std::optional<gp_Dir> normal = profileNormal(invObjLoc);
        if (!normal) {
            return std::string(
                "Pipe: twist and scale with the profile in the middle of the path run to the end "
                "the profile's plane faces away from, and this profile has no plane"
            );
        }
        to = samples[nearest].tangent.Dot(*normal) > 0 ? 0.0 : total;
    }
    const double span = std::abs(to - from);
    if (span < Precision::Confusion()) {
        return std::string("Pipe: the profile lies at the path's end it would sweep to");
    }

    // The twist's rate in radians per unit of length, and samples to follow it, 64 a turn
    double rate = 0.0;
    if (twist) {
        switch (TwistType.getValue()) {
            case 0:  // Turns
                rate = 2 * M_PI * Turns.getValue() / span;
                break;
            case 1:  // Angle
                rate = Base::toRadians(TwistAngle.getValue()) / span;
                break;
            default:  // Pitch: the length of one turn
                if (TwistPitch.getValue() < Precision::Confusion()) {
                    return std::string("Pipe: the twist's pitch must be more than zero");
                }
                rate = 2 * M_PI / TwistPitch.getValue();
                break;
        }
        rate *= TwistCCW.getValue() ? 1.0 : -1.0;
        samples = samplesAlong(edges, 16, M_PI / 32, std::abs(rate) / (M_PI / 32));
    }

    if (scaled) {
        const double factor = ScaleFactor.getValue();
        auto at = [&](double length) {
            return 1.0 + (factor - 1.0) * (length - from) / (to - from);
        };
        const double first = at(0.0);
        const double last = at(total);
        if (factor <= 0.0 || first <= Precision::Confusion() || last <= Precision::Confusion()) {
            return fmt::format(
                "Pipe: the scale reaches zero or less along the path (from {:.6g} to {:.6g}), and "
                "Onshape refuses this too. Use a scale factor nearer 1, or move the profile.",
                first,
                last
            );
        }
        Handle(Law_Linear) law = new Law_Linear();
        law->Set(0.0, first, 1.0, last);
        scale = law;
    }

    if (!twist && !lockFaces) {
        return std::nullopt;
    }
    std::vector<gp_Dir> normals;
    if (lockFaces) {
        std::vector<TopoDS_Face> faces;
        for (const auto& [object, subs] : LockFaces.getSubListValues()) {
            const std::vector<std::string> names = subs.empty() ? std::vector<std::string> {""} : subs;
            for (const std::string& sub : names) {
                Part::TopoShape shape = linkedShape(object, sub);
                if (shape.isNull()) {
                    continue;
                }
                shape.move(invObjLoc);
                for (TopExp_Explorer it(shape.getShape(), TopAbs_FACE); it.More(); it.Next()) {
                    faces.push_back(TopoDS::Face(it.Current()));
                }
            }
        }
        if (faces.empty()) {
            return std::string("Pipe: 'Lock faces' needs the faces the path lies on");
        }
        for (const PathSample& sample : samples) {
            auto [distance, normal] = nearestNormal(faces, sample.point);
            if (distance > 1.0e-4) {
                return fmt::format(
                    "Pipe: the path leaves the lock faces at {} ({:.3g} mm off them). The path "
                    "must lie on the faces picked for 'Lock faces'.",
                    inPlace(sample.point),
                    distance
                );
            }
            normal -= gp_Vec(sample.tangent) * normal.Dot(gp_Vec(sample.tangent));
            if (normal.Magnitude() < 1.0e-6) {
                return fmt::format(
                    "Pipe: at {} the path runs along the lock face's normal",
                    inPlace(sample.point)
                );
            }
            normals.emplace_back(normal);
        }
    }
    else if (control == 4) {
        const std::optional<gp_Dir> binormal = sweptBinormal(binormalInBody, getLocation());
        for (const PathSample& sample : samples) {
            const gp_Vec n = binormal ? gp_Vec(*binormal).Crossed(gp_Vec(sample.tangent)) : gp_Vec();
            if (n.Magnitude() < 1.0e-6) {
                return fmt::format(
                    "Pipe: at {} the path runs along the lock direction",
                    inPlace(sample.point)
                );
            }
            normals.emplace_back(n);
        }
    }
    else if (frenetForNone) {
        // A helix: its profile stays square to its axis, in Frenet's frame
        for (const PathSample& sample : samples) {
            if (sample.second.Magnitude() < gp::Resolution()) {
                normals.clear();
                break;
            }
            normals.emplace_back(sample.second);
        }
    }
    if (normals.empty()) {
        normals = carriedNormals(samples);
    }

    // About the path's tangent the way it runs: a twist's hand doesn't depend on the way the
    // profile sweeps (SW11: clockwise about the path's direction is Onshape's default)
    std::vector<double> angles(samples.size(), 0.0);
    for (size_t i = 0; i < samples.size(); ++i) {
        angles[i] = rate * (samples[i].length - from);
    }
    double curvature = 0.0;
    for (const PathSample& sample : samples) {
        curvature = std::max(curvature, sample.second.Magnitude());
    }
    const double reach
        = 0.2 * std::min(total, curvature > gp::Resolution() ? 1.0 / curvature : total);
    const std::optional<TopoDS_Wire> guide = guideThrough(samples, normals, angles, reach);
    if (!guide) {
        return std::string("Pipe: the profile's frame along the path couldn't be built");
    }
    frameGuide = *guide;
    return std::nullopt;
}

void Pipe::Restore(Base::XMLReader& reader)
{
    settingMode = true;
    ProfileControl.setValue(long(2));
    settingMode = false;
    ExtendToFullPath.setValue(true);
    ProfileBased::Restore(reader);
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
    if (ProfileControl.isTouched() || ExtendToFullPath.isTouched() || PathReversed.isTouched()
        || SpineMore.isTouched()) {
        return 1;
    }
    if (LockFaces.isTouched() || LockDirection.isTouched() || HasTwist.isTouched()
        || TwistType.isTouched() || Turns.isTouched() || TwistAngle.isTouched()
        || TwistPitch.isTouched() || TwistCCW.isTouched() || HasScale.isTouched()
        || ScaleFactor.isTouched() || BodyType.isTouched() || Thickness1.isTouched()
        || Thickness2.isTouched() || FlipWall.isTouched() || TrimEnds.isTouched()) {
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

/// Where an open wire starts or ends in its own order, and its direction of travel there
std::pair<gp_Pnt, gp_Vec> wireEnd(const TopoDS_Wire& wire, bool atEnd)
{
    std::vector<TopoDS_Edge> edges;
    for (BRepTools_WireExplorer it(wire); it.More(); it.Next()) {
        edges.push_back(it.Current());
    }
    if (edges.empty()) {
        throw Base::ValueError("Pipe: an empty curve in the thin profile");
    }
    const TopoDS_Edge& edge = atEnd ? edges.back() : edges.front();
    BRepAdaptor_Curve curve(edge);
    const bool forward = edge.Orientation() != TopAbs_REVERSED;
    const double u = (forward != atEnd) ? curve.FirstParameter() : curve.LastParameter();
    gp_Pnt point;
    gp_Vec tangent;
    curve.D1(u, point, tangent);
    if (!forward) {
        tangent.Reverse();
    }
    return {point, tangent};
}

/// \a wire, open and in \a plane, offset by \a distance to its right seen from the plane's normal
/// (to its left when negative): its edges, its start and its end
struct OffsetCurve
{
    std::vector<TopoDS_Edge> edges;
    gp_Pnt start;
    gp_Pnt end;
};

OffsetCurve offsetOpenWire(const TopoDS_Wire& wire, const gp_Pln& plane, double distance, GeomAbs_JoinType join)
{
    const auto [start, startTangent] = wireEnd(wire, false);
    const auto [end, endTangent] = wireEnd(wire, true);
    OffsetCurve result;
    if (std::abs(distance) < Precision::Confusion()) {
        // A copy, not the wire's own edges: the wall's names come from its history alone
        // (`MapperThinWall`, sweeps 20), never from sharing the profile's shapes
        const TopoDS_Shape copy = BRepBuilderAPI_Copy(wire).Shape();
        for (TopExp_Explorer it(copy, TopAbs_EDGE); it.More(); it.Next()) {
            result.edges.push_back(TopoDS::Edge(it.Current()));
        }
        result.start = start;
        result.end = end;
        return result;
    }
    const gp_Vec normal(plane.Axis().Direction());
    auto rightOf = [&](const gp_Vec& tangent) {
        gp_Vec right = tangent.Crossed(normal);
        if (right.Magnitude() < Precision::Confusion()) {
            throw Base::ValueError("Pipe: a thin profile's curve leaves its plane");
        }
        return right.Normalized();
    };
    const gp_Pnt wantStart = start.Translated(rightOf(startTangent) * distance);
    const gp_Pnt wantEnd = end.Translated(rightOf(endTangent) * distance);
    // OCCT finds no plane for a straight wire: give it the profile's, as its own open-wire case does
    BRep_Builder builder;
    TopoDS_Face face;
    builder.MakeFace(face, new Geom_Plane(plane), Precision::Confusion());
    builder.Add(face, wire);
    TopTools_ListOfShape edges;
    for (TopExp_Explorer it(wire, TopAbs_EDGE); it.More(); it.Next()) {
        edges.Append(it.Current());
    }
    BRepLib::BuildPCurveForEdgesOnPlane(edges, face);
    // OCCT's sign for an open wire's side: try one, check it against the right, else the other
    for (const double sign : {1.0, -1.0}) {
        BRepOffsetAPI_MakeOffset offset(face, join, true);
        try {
            offset.Perform(sign * distance);
        }
        catch (const Standard_Failure&) {
            continue;
        }
        if (!offset.IsDone() || offset.Shape().IsNull()) {
            continue;
        }
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopoDS_Wire built;
        for (TopExp_Explorer it(offset.Shape(), TopAbs_WIRE); it.More(); it.Next()) {
            if (!built.IsNull()) {
                built.Nullify();  // more than one wire: not a plain parallel
                break;
            }
            built = TopoDS::Wire(it.Current());
        }
        if (built.IsNull()) {
            continue;
        }
        TopExp::Vertices(built, first, last);
        if (first.IsNull() || last.IsNull()) {
            continue;
        }
        gp_Pnt a = BRep_Tool::Pnt(first);
        gp_Pnt b = BRep_Tool::Pnt(last);
        if (a.Distance(wantEnd) < b.Distance(wantEnd) && b.Distance(wantStart) < a.Distance(wantStart)) {
            std::swap(a, b);
        }
        const double tolerance = 1e-6 * std::max(1.0, std::abs(distance));
        if (a.Distance(wantStart) > tolerance || b.Distance(wantEnd) > tolerance) {
            continue;
        }
        for (TopExp_Explorer it(built, TopAbs_EDGE); it.More(); it.Next()) {
            result.edges.push_back(TopoDS::Edge(it.Current()));
        }
        result.start = a;
        result.end = b;
        return result;
    }
    throw Base::CADKernelError("Pipe: the thin wall's offset of an open curve failed");
}

/// The thin wall of \a curves in \a plane (SW14): around each open wire, a strip from \a left to its
/// left to \a right to its right (seen from the plane's normal); each region of the closed wires,
/// a ring from \a right outward to \a left inward. Faces, in a compound. \a sides, if given, gets
/// the curves of the wall's boundary on each side, left then right (the strips' offsets; the
/// rings' inner and outer boundaries), to tell the sides apart where both are offsets of one curve.
TopoDS_Shape thinWall(
    const TopoDS_Shape& curves,
    const gp_Pln& plane,
    double right,
    double left,
    GeomAbs_JoinType join,
    std::array<TopoDS_Compound, 2>* sides = nullptr
)
{
    BRep_Builder builder;
    TopoDS_Compound wall;
    builder.MakeCompound(wall);
    if (sides) {
        builder.MakeCompound((*sides)[0]);
        builder.MakeCompound((*sides)[1]);
    }
    std::vector<Part::TopoShape> closed;
    for (TopExp_Explorer it(curves, TopAbs_WIRE); it.More(); it.Next()) {
        const TopoDS_Wire& wire = TopoDS::Wire(it.Current());
        if (BRep_Tool::IsClosed(wire)) {
            closed.emplace_back(wire);
            continue;
        }
        const OffsetCurve a = offsetOpenWire(wire, plane, -left, join);
        const OffsetCurve b = offsetOpenWire(wire, plane, right, join);
        std::vector<Part::TopoShape> edges;
        for (const TopoDS_Edge& edge : a.edges) {
            edges.emplace_back(edge);
            if (sides) {
                builder.Add((*sides)[0], edge);
            }
        }
        for (const TopoDS_Edge& edge : b.edges) {
            edges.emplace_back(edge);
            if (sides) {
                builder.Add((*sides)[1], edge);
            }
        }
        edges.emplace_back(BRepBuilderAPI_MakeEdge(a.start, b.start).Edge());
        edges.emplace_back(BRepBuilderAPI_MakeEdge(a.end, b.end).Edge());
        const Part::TopoShape joined = Part::TopoShape(-1).makeElementWires(edges);
        if (joined.isNull() || joined.shapeType() != TopAbs_WIRE || !BRep_Tool::IsClosed(TopoDS::Wire(joined.getShape()))) {
            throw Base::CADKernelError("Pipe: the thin wall of an open curve doesn't close");
        }
        BRepBuilderAPI_MakeFace face(plane, TopoDS::Wire(joined.getShape()), true);
        if (!face.IsDone()) {
            throw Base::CADKernelError("Pipe: the thin wall of an open curve has no face");
        }
        // OCCT's offset of an open wire splits the offset of its last edge at the middle (sweeps 19):
        // two pieces of one side would be twins, renamed when a curve follows. Join a side's pieces
        // where they meet away from the profile's vertices; a vertex within the wall's thickness of
        // one (the offsets of a joint between collinear curves, or the curves themselves) is kept, so
        // each side stays one edge per curve
        ShapeUpgrade_UnifySameDomain unify(face.Face(), true, false, false);
        const double reach = std::max(right, left) + 1e-6 * std::max(1.0, right + left);
        for (TopExp_Explorer v(face.Face(), TopAbs_VERTEX); v.More(); v.Next()) {
            const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(v.Current()));
            for (TopExp_Explorer p(wire, TopAbs_VERTEX); p.More(); p.Next()) {
                if (point.Distance(BRep_Tool::Pnt(TopoDS::Vertex(p.Current()))) <= reach) {
                    unify.KeepShape(v.Current());
                    break;
                }
            }
        }
        unify.Build();
        int faces = 0;
        for (TopExp_Explorer it(unify.Shape(), TopAbs_FACE); it.More(); it.Next()) {
            builder.Add(wall, it.Current());
            ++faces;
        }
        if (faces != 1) {
            throw Base::CADKernelError("Pipe: the thin wall of an open curve has no face");
        }
    }
    if (!closed.empty()) {
        const Part::TopoShape regions = Part::TopoShape(-1).makeElementFace(closed);
        const Part::JoinType joinType = join == GeomAbs_Arc ? Part::JoinType::arc : Part::JoinType::intersection;
        auto grown = [&](double distance) {
            if (std::abs(distance) < Precision::Confusion()) {
                // A copy, as an open wire's (`offsetOpenWire`)
                return Part::TopoShape(BRepBuilderAPI_Copy(regions.getShape()).Shape());
            }
            return regions.makeElementOffset2D(
                distance,
                joinType,
                Part::FillType::noFill,
                Part::OpenResult::noOpenResult
            );
        };
        const Part::TopoShape outer = grown(right);
        const Part::TopoShape inner = grown(-left);
        if (outer.isNull() || inner.isNull() || inner.countSubShapes(TopAbs_FACE) == 0) {
            throw Base::ValueError("Pipe: the thin wall is thicker than the region it goes into");
        }
        if (sides) {
            for (TopExp_Explorer it(inner.getShape(), TopAbs_EDGE); it.More(); it.Next()) {
                builder.Add((*sides)[0], it.Current());
            }
            for (TopExp_Explorer it(outer.getShape(), TopAbs_EDGE); it.More(); it.Next()) {
                builder.Add((*sides)[1], it.Current());
            }
        }
        FCBRepAlgoAPI_Cut ring(outer.getShape(), inner.getShape());
        if (!ring.IsDone()) {
            throw Base::CADKernelError("Pipe: the thin wall's ring failed");
        }
        for (TopExp_Explorer it(ring.Shape(), TopAbs_FACE); it.More(); it.Next()) {
            builder.Add(wall, it.Current());
        }
    }
    return wall;
}

double areaOf(const TopoDS_Shape& faces)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(faces, props);
    return std::abs(props.Mass());
}

/// The thin wall's history (sweeps 16): the wall is built from OCCT offsets, which keep none, so each
/// of its edges is related to the profile's by geometry. Each side of the wall is named from the
/// profile curve it runs along (its midpoint at that side's thickness from it, the nearest curve), by
/// the side it lies on (sweeps 20, oracle 12's THM1): an edge on the left side (\a leftSides: an open
/// curve's left, a region's inner boundary) is modified from the curve, one on the right side
/// (\a rightSides: the right, the outer boundary) generated from it, whether that side lies on the
/// curve or is its offset. So the two sides of one curve are never twins told apart by rank (which an
/// added curve changes, sweeps 17), and Midplane and FlipWall, which only move the wall across the
/// curve, leave every side's name alone, as Onshape keeps each reference on its own side in every
/// (Midplane, Flip) state. An edge through a profile vertex (an open curve's end) is generated from
/// that vertex. An edge on neither side (none is known) falls back to the geometry alone: on a curve,
/// modified from it; at a thickness from the nearest, generated from it.
class MapperThinWall: public Part::TopoShape::Mapper
{
public:
    MapperThinWall(
        const TopoDS_Shape& wall,
        const TopoDS_Shape& profile,
        double right,
        double left,
        const TopoDS_Shape& leftSides,
        const TopoDS_Shape& rightSides
    )
    {
        TopTools_IndexedMapOfShape edges;
        TopTools_IndexedMapOfShape vertices;
        TopExp::MapShapes(profile, TopAbs_EDGE, edges);
        TopExp::MapShapes(profile, TopAbs_VERTEX, vertices);
        sourceEdges.reserve(edges.Extent());
        for (int i = 1; i <= edges.Extent(); ++i) {
            sourceEdges.push_back(edges(i));
        }
        for (int i = 1; i <= vertices.Extent(); ++i) {
            sourceVertices.push_back(vertices(i));
        }
        modifiedOf.resize(sourceEdges.size());
        generatedOf.resize(sourceEdges.size());
        modifiedOfVertex.resize(sourceVertices.size());
        generatedOfVertex.resize(sourceVertices.size());
        const double tolerance = 1e-7 + 1e-6 * std::max(1.0, right + left);
        auto distance = [](const TopoDS_Shape& a, const gp_Pnt& p) {
            BRepExtrema_DistShapeShape measure(a, BRepBuilderAPI_MakeVertex(p).Vertex());
            return measure.IsDone() ? measure.Value() : std::numeric_limits<double>::max();
        };
        auto nearestCurve = [&](const gp_Pnt& p, double& best) {
            std::size_t nearest = sourceEdges.size();
            best = std::numeric_limits<double>::max();
            for (std::size_t s = 0; s < sourceEdges.size(); ++s) {
                const double d = distance(sourceEdges[s], p);
                if (d < best) {
                    best = d;
                    nearest = s;
                }
            }
            return nearest;
        };
        TopTools_IndexedMapOfShape wallEdges;
        TopExp::MapShapes(wall, TopAbs_EDGE, wallEdges);
        // Each wall edge's source: the curve it runs along, or the vertex an end goes through
        std::vector<std::size_t> curveOf(wallEdges.Extent() + 1, sourceEdges.size());
        std::vector<std::size_t> endOf(wallEdges.Extent() + 1, sourceVertices.size());
        for (int w = 1; w <= wallEdges.Extent(); ++w) {
            const TopoDS_Edge& edge = TopoDS::Edge(wallEdges(w));
            BRepAdaptor_Curve curve(edge);
            const double u0 = curve.FirstParameter();
            const double u1 = curve.LastParameter();
            const gp_Pnt middle = curve.Value((u0 + u1) / 2);
            const std::array<gp_Pnt, 3> samples {curve.Value(u0 + (u1 - u0) / 4), middle, curve.Value(u1 - (u1 - u0) / 4)};
            auto lies = [&](const TopoDS_Shape& on) {
                return !on.IsNull() && std::all_of(samples.begin(), samples.end(), [&](const gp_Pnt& p) {
                    return distance(on, p) < tolerance;
                });
            };
            // A side of the wall: named from its curve by the side, wherever the curve is
            bool named = false;
            for (int side = 0; side < 2 && !named; ++side) {
                if (!lies(side == 0 ? leftSides : rightSides)) {
                    continue;
                }
                double best = 0;
                const std::size_t nearest = nearestCurve(middle, best);
                if (nearest < sourceEdges.size() && std::abs(best - (side == 0 ? left : right)) < tolerance) {
                    (side == 0 ? modifiedOf : generatedOf)[nearest].push_back(edge);
                    curveOf[w] = nearest;
                    named = true;
                }
            }
            for (std::size_t s = 0; s < sourceEdges.size() && !named; ++s) {
                if (std::all_of(samples.begin(), samples.end(), [&](const gp_Pnt& p) {
                        return distance(sourceEdges[s], p) < tolerance;
                    })) {
                    modifiedOf[s].push_back(edge);
                    curveOf[w] = s;
                    named = true;
                }
            }
            for (std::size_t v = 0; v < sourceVertices.size() && !named; ++v) {
                BRepExtrema_DistShapeShape measure(edge, sourceVertices[v]);
                if (measure.IsDone() && measure.Value() < tolerance) {
                    generatedOfVertex[v].push_back(edge);
                    endOf[w] = v;
                    named = true;
                }
            }
            if (named) {
                continue;
            }
            double best = 0;
            const std::size_t nearest = nearestCurve(middle, best);
            if (nearest < sourceEdges.size()
                && ((right > tolerance && std::abs(best - right) < tolerance)
                    || (left > tolerance && std::abs(best - left) < tolerance))) {
                generatedOf[nearest].push_back(edge);
                curveOf[w] = nearest;
            }
        }
        // The wall's corners (sweeps 20): named from the profile vertex they stand for, by the side
        // they lie on, as the sides are, so the edges a sweep makes of them keep their names too. A
        // corner where a side meets an end stands for the end's vertex; one where the sides of two
        // curves meet, for the vertex the two curves share
        TopTools_IndexedDataMapOfShapeListOfShape edgesOfVertex;
        TopExp::MapShapesAndAncestors(wall, TopAbs_VERTEX, TopAbs_EDGE, edgesOfVertex);
        for (int i = 1; i <= edgesOfVertex.Extent(); ++i) {
            const TopoDS_Shape& corner = edgesOfVertex.FindKey(i);
            const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(corner));
            const int side = !leftSides.IsNull() && distance(leftSides, point) < tolerance ? 0
                : !rightSides.IsNull() && distance(rightSides, point) < tolerance       ? 1
                                                                                        : -1;
            if (side < 0) {
                continue;
            }
            std::size_t from = sourceVertices.size();
            std::vector<std::size_t> curves;
            for (const TopoDS_Shape& e : edgesOfVertex(i)) {
                const int w = wallEdges.FindIndex(e);
                if (w > 0 && endOf[w] < sourceVertices.size()) {
                    from = endOf[w];
                    break;
                }
                if (w > 0 && curveOf[w] < sourceEdges.size()
                    && std::find(curves.begin(), curves.end(), curveOf[w]) == curves.end()) {
                    curves.push_back(curveOf[w]);
                }
            }
            if (from == sourceVertices.size() && curves.size() == 2) {
                for (std::size_t v = 0; v < sourceVertices.size(); ++v) {
                    const gp_Pnt at = BRep_Tool::Pnt(TopoDS::Vertex(sourceVertices[v]));
                    if (distance(sourceEdges[curves[0]], at) < tolerance
                        && distance(sourceEdges[curves[1]], at) < tolerance) {
                        if (from < sourceVertices.size()) {
                            from = sourceVertices.size();  // two: the curves meet twice, say nothing
                            break;
                        }
                        from = v;
                    }
                }
            }
            if (from < sourceVertices.size()) {
                (side == 0 ? modifiedOfVertex : generatedOfVertex)[from].push_back(corner);
            }
        }
    }

    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& s) const override
    {
        return lookUp(s, generatedOf, generatedOfVertex);
    }

    const std::vector<TopoDS_Shape>& modified(const TopoDS_Shape& s) const override
    {
        return lookUp(s, modifiedOf, modifiedOfVertex);
    }

private:
    const std::vector<TopoDS_Shape>& lookUp(
        const TopoDS_Shape& s,
        const std::vector<std::vector<TopoDS_Shape>>& ofEdges,
        const std::vector<std::vector<TopoDS_Shape>>& ofVertices
    ) const
    {
        _res.clear();
        if (s.ShapeType() == TopAbs_EDGE) {
            for (std::size_t i = 0; i < sourceEdges.size(); ++i) {
                if (sourceEdges[i].IsSame(s)) {
                    _res = ofEdges[i];
                    break;
                }
            }
        }
        else if (s.ShapeType() == TopAbs_VERTEX && !ofVertices.empty()) {
            for (std::size_t i = 0; i < sourceVertices.size(); ++i) {
                if (sourceVertices[i].IsSame(s)) {
                    _res = ofVertices[i];
                    break;
                }
            }
        }
        return _res;
    }

    std::vector<TopoDS_Shape> sourceEdges;
    std::vector<TopoDS_Shape> sourceVertices;
    std::vector<std::vector<TopoDS_Shape>> modifiedOf;
    std::vector<std::vector<TopoDS_Shape>> generatedOf;
    std::vector<std::vector<TopoDS_Shape>> modifiedOfVertex;
    std::vector<std::vector<TopoDS_Shape>> generatedOfVertex;
};

/// The thin wall of \a pipe's profile (SW14), in place of its curves, its corners mitred (SW18)
Part::TopoShape thinProfileOf(const Pipe& pipe)
{
    App::DocumentObject* profile = pipe.Profile.getValue();
    const std::vector<std::string>& subs = pipe.Profile.getSubValues();
    TopoDS_Shape curves;
    gp_Pln plane;
    TopLoc_Location location;
    Part::TopoShape named;  // the profile's curves with their names, where the wall is
    if (auto sketch = freecad_cast<Part::Part2DObject*>(profile)) {
        // All the sketch's curves, open ones included: in the sketch's own plane
        named = sketch->Shape.getShape();
        location = sketch->Shape.getShape().getShape().Location();
        curves = sketch->Shape.getShape().getShape().Located(TopLoc_Location());
        plane = gp_Pln(gp::XOY());
    }
    else if (auto feature = freecad_cast<Part::Feature*>(profile)) {
        if (subs.empty() || subs.front().empty()) {
            throw Base::ValueError("Pipe: a thin profile needs a sketch or a planar face");
        }
        const Part::TopoShape face = feature->Shape.getShape().getSubTopoShape(subs.front().c_str(), true);
        if (face.isNull() || face.shapeType() != TopAbs_FACE) {
            throw Base::ValueError("Pipe: a thin profile needs a sketch or a planar face");
        }
        BRepAdaptor_Surface surface(TopoDS::Face(face.getShape()));
        if (surface.GetType() != GeomAbs_Plane) {
            throw Base::ValueError("Pipe: a thin profile needs a sketch or a planar face");
        }
        plane = surface.Plane();
        curves = face.getShape();
        named = face;
    }
    else {
        throw Base::TypeError("Pipe: Invalid profile/section");
    }
    const double thickness1 = pipe.Thickness1.getValue();
    const double thickness2 = pipe.Thickness2.getValue();
    if (thickness1 <= Precision::Confusion() || thickness2 < 0.0) {
        throw Base::ValueError("Pipe: the thin wall's thickness must be more than zero");
    }
    // To the right (an open curve) or outward (a region) by default
    double right = pipe.Midplane.getValue() ? thickness1 / 2 : thickness1;
    double left = pipe.Midplane.getValue() ? thickness1 / 2 : thickness2;
    if (pipe.FlipWall.getValue()) {
        std::swap(right, left);
    }
    // SW18: Onshape mitres the wall's corners, the outside of a corner included; never rounds them
    std::array<TopoDS_Compound, 2> sides;
    const TopoDS_Shape wall = thinWall(curves, plane, right, left, GeomAbs_Intersection, &sides);
    if (areaOf(wall) < Precision::Confusion()) {
        throw Base::ValueError("Pipe: the thin profile has no curves to put a wall around");
    }
    const TopoDS_Shape placed = wall.Located(location);
    Part::TopoShape result(0, pipe.getDocument()->getStringHasher());
    result.makeShapeWithElementMap(
        placed,
        MapperThinWall(placed, named.getShape(), right, left, sides[0].Located(location), sides[1].Located(location)),
        {named},
        Part::OpCodes::Offset2D
    );
    return result;
}

// Whether every section is one circle centred on a one-edge spine with its axis along the spine's
// tangent there: a solid of revolution about the spine, the same whatever the frame law turns
// the sections by
bool circlesAboutSpine(const std::vector<Part::TopoShape>& sections, const TopoDS_Shape& spine)
{
    TopTools_IndexedMapOfShape spineEdges;
    TopExp::MapShapes(spine, TopAbs_EDGE, spineEdges);
    if (spineEdges.Extent() != 1 || sections.empty()) {
        return false;
    }
    const TopoDS_Edge& path = TopoDS::Edge(spineEdges(1));
    const BRepAdaptor_Curve along(path);
    for (const Part::TopoShape& section : sections) {
        TopTools_IndexedMapOfShape edges;
        TopExp::MapShapes(section.getShape(), TopAbs_EDGE, edges);
        if (edges.Extent() != 1) {
            return false;
        }
        const BRepAdaptor_Curve curve(TopoDS::Edge(edges(1)));
        if (curve.GetType() != GeomAbs_Circle) {
            return false;
        }
        const gp_Circ circle = curve.Circle();
        BRepExtrema_DistShapeShape distance(
            BRepBuilderAPI_MakeVertex(circle.Location()).Vertex(),
            path
        );
        if (!distance.IsDone() || distance.NbSolution() < 1
            || distance.Value() > Precision::Confusion()
            || (distance.SupportTypeShape2(1) == BRepExtrema_IsVertex
                && !(distance.SupportOnShape2(1).IsSame(TopExp::FirstVertex(path))
                     || distance.SupportOnShape2(1).IsSame(TopExp::LastVertex(path))))) {
            return false;
        }
        double parameter = 0.0;
        if (distance.SupportTypeShape2(1) == BRepExtrema_IsOnEdge) {
            distance.ParOnEdgeS2(1, parameter);
        }
        else {
            parameter = distance.SupportOnShape2(1).IsSame(TopExp::FirstVertex(path))
                ? along.FirstParameter()
                : along.LastParameter();
        }
        gp_Pnt point;
        gp_Vec tangent;
        along.D1(parameter, point, tangent);
        if (tangent.Magnitude() < gp::Resolution()
            || !circle.Axis().Direction().IsParallel(gp_Dir(tangent), Precision::Angular())) {
            return false;
        }
    }
    return true;
}

// Honest edge tolerances (ops#667). OCCT's sweep stores an edge's tolerance from the deviation of
// its curves on the faces as it measured them, with little margin: the end circles of a long
// B-spline pipe had 3.36e-6 against a deviation of 3.20e-6 on Windows, and the slightly different
// approximation of macOS's build went past it, failing the face's check there alone (decision
// 181). Each edge whose tolerance is under twice its measured deviation gets twice that, on a
// topology-only copy (the caps' edges are the profile's own) that keeps the element names; then
// the vertices follow. Geometry unchanged. Returns the number of edges raised.
int raiseTightEdgeTolerances(Part::TopoShape& shape)
{
    constexpr double margin = 2.0;
    constexpr int controlPoints = 101;
    auto tight = [&](const TopoDS_Edge& edge, double& wanted) {
        if (BRep_Tool::Degenerated(edge)) {
            return false;
        }
        double deviation = 0.0;
        ShapeAnalysis_Edge analysis;
        analysis.CheckSameParameter(edge, deviation, controlPoints);
        wanted = margin * deviation;
        return wanted > BRep_Tool::Tolerance(edge);
    };
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(shape.getShape(), TopAbs_EDGE, edges);
    std::vector<std::pair<int, double>> raise;
    for (int i = 1; i <= edges.Extent(); ++i) {
        double wanted = 0.0;
        if (tight(TopoDS::Edge(edges(i)), wanted)) {
            raise.emplace_back(i, wanted);
        }
    }
    if (raise.empty()) {
        return 0;
    }
    Part::TopoShape copy(shape);
    copy.setShape(BRepBuilderAPI_Copy(shape.getShape(), false).Shape(), false);
    TopTools_IndexedMapOfShape copied;
    TopExp::MapShapes(copy.getShape(), TopAbs_EDGE, copied);
    if (copied.Extent() != edges.Extent()) {
        return 0;
    }
    BRep_Builder builder;
    for (const auto& [index, tolerance] : raise) {
        builder.UpdateEdge(TopoDS::Edge(copied(index)), tolerance);
    }
    BRepLib::UpdateTolerances(copy.getShape(), Standard_False);
    shape = copy;
    return static_cast<int>(raise.size());
}
}  // namespace

App::DocumentObjectExecReturn* Pipe::execute()
{
    frenetForNone = false;
    frameGuide.Nullify();
    binormalInBody = Binormal.getValue();
    if (ProfileControl.getValue() == 4) {
        // Lock direction: Binormal mode with the picked direction, in the Body's coordinates
        const std::vector<std::string>& subs = LockDirection.getSubValues();
        const std::optional<gp_Dir> direction = directionOf(
            linkedShape(LockDirection.getValue(), subs.empty() ? std::string() : subs.front())
        );
        if (!direction) {
            return new App::DocumentObjectExecReturn(
                "Pipe: 'Lock direction' needs a plane, a planar face or a straight edge"
            );
        }
        binormalInBody = Base::Vector3d(direction->X(), direction->Y(), direction->Z());
    }
    if (BodyType.getValue() == 1 && !Sections.getValues().empty()) {
        return new App::DocumentObjectExecReturn(
            "Pipe: a thin sweep takes no sections; Onshape's Sweep has none either"
        );
    }
    if (onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    // Sections are paired with the profile wire by wire, in order
    const bool ordered = !Sections.getValues().empty();
    auto getSectionShape = [this, ordered](const char* name,
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
            // Picked regions: their faces' wires, adjacent regions merged (feat/profile-regions)
            if (picksRegions(subs)) {
                return wiresOfFaces(getTopoShapeVerifiedFace(false, false, feature, subs));
            }
            // Its closed loops; open curves are ignored, as in Onshape (ops#631). With no loop
            // left, the open wires stay, and the pipe refuses them as before.
            const auto& shape = static_cast<Part::Part2DObject*>(feature)->Shape.getShape();
            WholeSketchRegions rule(feature, shape);
            if (rule.sameAsLoops()) {
                try {
                    auto loops = withoutOpenCurves(shape);
                    return loops.isNull() ? shape : loops;
                }
                catch (const Base::Exception&) {
                    // Onshape's regions below
                }
            }
            // Loops that overlap, touch or nest deeper: Onshape's regions of the whole sketch
            auto faces = rule.faces();
            if (faces.isNull()) {
                return shape;  // the pipe refuses the open wires as before
            }
            auto wires = wiresOfFaces(faces);
            // One region with at most one hole pairs as the old loops do (outer to outer, hole
            // to hole); more, and the face maker's order isn't the sketch's
            if (ordered
                && (faces.countSubShapes(TopAbs_FACE) > 1 || wires.countSubShapes(TopAbs_WIRE) > 2)) {
                FC_THROWM(Base::CADKernelError, name << ": " << SectionRegionsMessage);
            }
            return wires;
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
        // Thin: the wall around the profile's curves, open ones included, swept as a solid profile
        Part::TopoShape profileShape = BodyType.getValue() == 1
            ? thinProfileOf(*this)
            : getSectionShape("Profile", Profile.getValue(), Profile.getSubValues());
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
        // More path edges from other objects (Onshape picks path edges one by one): joined with
        // the Spine's in any order. Without them the path is built as before, names and all.
        std::vector<std::vector<std::string>> moreIdentities;
        if (SpineMore.getValues().empty()) {
            buildPipePath(shape, subedge, path);
        }
        else {
            Part::TopoShape piece = makeTopoShape(false);
            buildPipePath(shape, subedge, piece);
            std::vector<Part::TopoShape> edges = piece.getSubTopoShapes(TopAbs_EDGE);
            for (auto [object, subs] : SpineMore.getSubListValues()) {
                // (object, "") stands for the whole object: Python's (object, []) adds no entry
                std::erase(subs, std::string());
                if (!(object && object->isDerivedFrom<Part::Feature>())) {
                    return new App::DocumentObjectExecReturn(
                        "Pipe: a path object in SpineMore isn't a shape"
                    );
                }
                if (auto missing = missingElements(object, subs); !missing.empty()) {
                    return new App::DocumentObjectExecReturn(
                        "Missing element in SpineMore: " + missing
                    );
                }
                const Part::TopoShape& more = static_cast<Part::Feature*>(object)->Shape.getShape();
                Part::TopoShape morePiece = makeTopoShape(false);
                buildPipePath(more, subs, morePiece);
                for (const Part::TopoShape& edge : morePiece.getSubTopoShapes(TopAbs_EDGE)) {
                    edges.push_back(edge);
                }
                moreIdentities.push_back(spineIdentity(object, more, subs));
            }
            path = path.makeElementWires(edges);
        }
        path.move(invObjLoc);
        // A path whose edges don't all join into one wire: the gap, by the two nearest ends of
        // different wires (before, OCCT's cast reported "TopoDS::Wire")
        if (!path.isNull() && path.shapeType() != TopAbs_WIRE) {
            if (const std::optional<std::pair<gp_Pnt, gp_Pnt>> gap = pathGap(path.getShape())) {
                const gp_Trsf toBody = invObjLoc.Inverted().Transformation();
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: the path's edges don't meet at {}: the nearest other end is {}, {:.6g} "
                    "mm away. Join them, or pick edges that meet.",
                    pointText(gap->first.Transformed(toBody)),
                    pointText(gap->second.Transformed(toBody)),
                    gap->first.Distance(gap->second)
                ));
            }
        }
        // Paths Onshape refuses (oracle 9, ops#660), and where the tubes may overlap
        std::optional<std::pair<gp_Pnt, double>> passesNear;
        if (!path.isNull() && path.shapeType() == TopAbs_WIRE) {
            const gp_Trsf toBody = invObjLoc.Inverted().Transformation();
            const TopoDS_Wire& wire = TopoDS::Wire(path.getShape());
            if (const std::optional<gp_Pnt> at = pathTouchesItself(wire)) {
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: the path crosses or touches itself at {}; Onshape refuses such a path "
                    "too. Move its edges apart.",
                    pointText(at->Transformed(toBody))
                ));
            }
            const TopoDS_Shape placedProfile = profileShape.getShape().Moved(invObjLoc);
            if (const auto turns = overlappingTurns(
                    wire,
                    placedProfile,
                    HasScale.getValue() ? ScaleFactor.getValue() : 1.0
                )) {
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: the helix's turns overlap: its pitch, {:.6g} mm, is less than the "
                    "profile's {:.6g} mm along its axis. Make the pitch larger or the profile "
                    "smaller.",
                    turns->first,
                    turns->second
                ));
            }
            // The profile's reach about the path's start: tubes along edges nearer each other than
            // twice that may overlap
            Bnd_Box box;
            BRepBndLib::Add(placedProfile, box);
            if (!box.IsVoid()) {
                const gp_Pnt start = BRep_Tool::Pnt(TopExp::FirstVertex(edgesInOrder(wire).front(), true));
                double xMin, yMin, zMin, xMax, yMax, zMax;
                box.Get(xMin, yMin, zMin, xMax, yMax, zMax);
                double reach = 0.0;
                for (const double x : {xMin, xMax}) {
                    for (const double y : {yMin, yMax}) {
                        for (const double z : {zMin, zMax}) {
                            reach = std::max(reach, start.Distance(gp_Pnt(x, y, z)));
                        }
                    }
                }
                // A profile scaled up along the path reaches further than the start profile does
                // (the ops#666 skeptic's silent path A): its reach grows with the factor
                if (HasScale.getValue()) {
                    reach *= std::max(1.0, ScaleFactor.getValue());
                }
                // So does a larger section further on: a U path whose last section grows to r 5.5
                // swept a self-overlapping solid, Up-to-date. Its reach is the largest distance
                // from its points to its own path point (the path's point nearest their middle),
                // not its box's diagonal: that one armed the check on multisection helix pipes
                // whose tubes stay clear (sweeps 11)
                if (Transformation.getValue() == 1) {
                    std::vector<TopoDS_Shape> sections;
                    for (const auto& subSet : Sections.getSubListValues()) {
                        try {
                            const Part::TopoShape section
                                = getSectionShape("Section", subSet.first, subSet.second);
                            if (!section.isNull()) {
                                sections.push_back(section.getShape().Moved(invObjLoc));
                            }
                        }
                        catch (const Standard_Failure&) {
                        }
                        catch (const Base::Exception&) {
                            // the sections' own checks below say what's wrong with it
                        }
                    }
                    reach = std::max(reach, sectionsReach(wire, sections));
                }
                passesNear = pathPassesNearItself(wire, reach);
            }
            // A helix of several turns sweeps turn by turn, as AdditiveHelix's (ops#665)
            path = withHelixTurns(path, makeTopoShape(false), placedProfile);
        }

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

        // Onshape's Sweep (notes\sweep-design.md): where one profile lies against the path, and
        // the frame of ProfileControl "None"
        frenetForNone = false;
        if (multisections.empty() && profilePoint.isNull() && !wiresections.empty()
            && path.shapeType() == TopAbs_WIRE) {
            std::vector<TopoDS_Shape> profileWires;
            for (const auto& wires : wiresections) {
                if (!wires.empty()) {
                    Part::TopoShape wire = wires.front();
                    wire.move(invObjLoc);
                    profileWires.push_back(wire.getShape());
                }
            }
            const ProfileFoot foot = profileFoot(profileWires, TopoDS::Wire(path.getShape()));
            const gp_Trsf toBody = invObjLoc.Inverted().Transformation();
            // A profile off the path keeps its offset, as in Onshape (SW5: 5 below, or 5 beside, a
            // circle r 2); one as near to two places of the path is loud (skeptic c721, finding
            // 3): at the centre of an arc it swept nothing, "valid"
            if (foot.tie) {
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: the profile's nearest point on the path isn't one place: it lies as near "
                    "to {} as to {} ({:.6g} mm). Move the profile onto the path, or nearer one "
                    "place of it.",
                    pointText(foot.at.Transformed(toBody)),
                    pointText(foot.tie->Transformed(toBody)),
                    foot.distance
                ));
            }
            // A profile in the middle with the option off sweeps one way from its foot point:
            // against the profile's normal (Onshape, SW1: a Top circle on a line along Z sweeps
            // -Z whichever way the line is drawn; at a joint, the segment below it), the other way
            // with PathReversed. SW1b: against the normal whatever the pick order or the lines' way.
            if (!ExtendToFullPath.getValue() && !foot.atEnd) {
                const std::optional<gp_Dir> normal = profileNormal(invObjLoc);
                if (!normal) {
                    return new App::DocumentObjectExecReturn(
                        "Pipe: with 'Extend to full path' off, the profile's plane decides which way "
                        "the sweep runs from it, and this profile has none. Turn 'Extend to full "
                        "path' on."
                    );
                }
                const std::optional<OneWay> oneWay
                    = oneWayFrom(path, foot.at, *normal, PathReversed.getValue());
                if (!oneWay) {
                    return new App::DocumentObjectExecReturn(fmt::format(
                        "Pipe: with 'Extend to full path' off, the path runs edge-on to the profile "
                        "at {}, so neither way from the profile is the one it faces. Turn 'Extend "
                        "to full path' on, or turn the profile.",
                        pointText(foot.at.Transformed(toBody))
                    ));
                }
                path = oneWay->path;
            }
            // None off a plane: Frenet's frame where it neither turns over nor jumps (a helix's
            // profile stays square to its axis; corrected Frenet rolls it), else corrected Frenet.
            // On a plane both are the same, so planar paths sweep exactly as Standard did.
            const TopoDS_Wire spineWire = TopoDS::Wire(path.getShape());
            if (ProfileControl.getValue() == 0 && Mode.getValue() == 0
                && !isPlanarPath(spineWire)) {
                try {
                    BRepOffsetAPI_MakePipeShell trial(spineWire);
                    frenetForNone = Part::SweepFrenet::setMode(
                                        trial,
                                        spineWire,
                                        profileWires,
                                        true,
                                        Precision::Confusion()
                                    )
                        == Part::SweepFrenet::Mode::Asked;
                }
                catch (Standard_Failure&) {
                    frenetForNone = false;
                }
            }
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
        const std::vector<std::string> spineInput = [&]() {
            std::vector<std::string> input = spineIdentity(spine, shape, subedge);
            // SpineMore's objects, each after a "+" with its own name and edges
            for (const std::vector<std::string>& more : moreIdentities) {
                input.emplace_back("+");
                input.insert(input.end(), more.begin(), more.end());
            }
            return input;
        }();
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
        // The spine object's placement, in the body: with the profile's geometry frame, it tells
        // the whole model turned from the profile turned alone about a symmetric ring's centre,
        // where both read the stored places onto the ring (ops#546)
        const gp_Trsf spineFrame = shape.getShape().Location().Transformation();
        if (startStored) {
            const gp_Trsf inPipe = invObjLoc.Transformation();
            // The stored points of \a record, in the pipe's frame; false for a malformed one. The
            // record ends with the profile's frames at its recompute (each its origin and the ends
            // of its x and y axes, in the body): a loop not at its stored place in the body but at
            // it in one of them, moved with the profile (the whole model moved), is read in that
            // frame for its own input; where a frame of the profile turned, the pipe stops
            // (decision 195's bound), unless the whole model turned as one piece (K4b's
            // `RingTurned`), which the spine's stored frame tells (turnedWhole, ops#546). Read in the
            // body, the turned ring's start went to the vertex a translation fit least badly, and
            // the start's key and the legs' names with it (a rectangle turns onto itself four
            // ways, so no fit tells them apart). The profile's frame, not the pipe's: that is its
            // base's placement, or the profile's support's, and turns with the ring only for a first
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
                // 2n + 1 points, each frame's 3 and, an even count, the spine's frame's 3 (none
                // in a record from before ops#546)
                const bool spineFramed = stored.size() % 2 == 0;
                const size_t framed = 3 * (frames.size() + (spineFramed ? 1 : 0));
                if (stored.size() < 5 + framed) {
                    return false;
                }
                // From the body into each stored frame, the profile's, then the spine's
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
                // The whole model turned as one piece (decision 212): the turn of the profile's
                // geometry frame (a face's placement is its feature's, which stays as the
                // feature's sketch turns through its offset) moves the stored spine frame onto
                // the spine object's placement and the stored places exactly onto the spine, and
                // every stored line still on the spine lies at its turned place (two lines traded
                // as the model turns, `RingTurnedAndSwapped`; none left to check, decision 150).
                // The record is then read turned, quietly. Before the in-place test: a ring
                // turned onto itself lies in place in the body, and read there its legs were
                // renamed (`notes\naming-class-D.md` 11.2, 11.9 F3). Not where the spine's frame
                // stays (a mirror in the spine's sketch with the profile turned, R6J-1: the spine
                // object didn't turn), nor where the profile's first point moved otherwise
                // anchor: rung 4 (the stored places), moved with the whole model
                auto turnedWhole = [&]() {
                    const gp_Trsf motion = frames[1] * into[1];
                    if (!spineFramed || !sameInput(record.of, spineInput)
                        || std::abs(motion.GetRotation().GetRotationAngle()) <= turnedBy) {
                        return false;
                    }
                    // The spine's turn since the record, less the profile's: none
                    const gp_Trsf spineLess = spineFrame * into.back() * motion.Inverted();
                    const gp_Pnt spineOrigin = gp_Pnt().Transformed(spineFrame);
                    if (spineOrigin.Transformed(spineLess).Distance(spineOrigin)
                            >= Precision::Confusion()
                        || std::abs(spineLess.GetRotation().GetRotationAngle()) > turnedBy) {
                        return false;
                    }
                    fill(inPipe * motion);
                    const size_t n = spineInOrder.size();
                    bool rigid = closedInPlace(storedVertices, storedMiddles, spineInOrder)
                        && record.names.size() == n
                        && makeTopoShape(false).getHistoryAlgorithm() == App::HistoryAlgorithm::V2;
                    std::vector<std::string> names;
                    for (size_t i = 0; rigid && i < n; ++i) {
                        names.push_back(firstName(path, spineInOrder[i]));
                    }
                    bool checked = false;
                    for (size_t i = 0; rigid && i < n; ++i) {
                        if (std::ranges::find(names, record.names[i]) == names.end()) {
                            continue;
                        }
                        const auto at = std::ranges::find_if(spineInOrder, [&](const TopoDS_Edge& e) {
                            return middleOf(e).Distance(storedMiddles[i]) < Precision::Confusion();
                        });
                        rigid = at != spineInOrder.end()
                            && names[static_cast<size_t>(at - spineInOrder.begin())]
                                == record.names[i];
                        checked = true;
                    }
                    if (!rigid || !checked) {
                        fill(inPipe);
                        return false;
                    }
                    return true;
                };
                // In a frame only for its own input: another spine elsewhere, the profile moved
                // onto it, still decides as a new pipe (CC2)
                // anchor: rung 4 (the stored places), in the body, or exactly in place in one of
                // the profile's stored frames
                if (!turnedWhole() && sameInput(record.of, spineInput)
                    && !closedInPlace(storedVertices, storedMiddles, spineInOrder)) {
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
                    // Read in a stored frame only where no frame of the profile turned (the whole
                    // model moved): with one turned, the pipe stops, as below (decision 195's
                    // bound). The loop in place in a turned frame stood for other reasons than the
                    // loop's motion: a scalene triangle mirrored, each line keeping its side, with
                    // its profile reparameterised half a turn, lies exactly in place in the
                    // placement frame turned half a turn, and two legs' faces went to their mirror
                    // places, silently (R6J-1, decision 198); required to agree with the lines'
                    // names, the same mirror with every line drawn anew left no name to check, and
                    // the legs' references went to their back faces (the pre-push review of round
                    // 6's sixth fix): the whole model turned stops too
                    bool inFrame = false;
                    for (size_t i = 0; i < frames.size() && !inFrame && !turned; ++i) {
                        fill(inPipe * frames[i] * into[i]);
                        inFrame = closedInPlace(storedVertices, storedMiddles, spineInOrder);
                    }
                    if (!inFrame) {
                        fill(inPipe);
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
                        "Pipe: the closed spine's stored start can't be matched to its lines (its "
                        "profile turned, or a redraw or another number of lines with another "
                        "change in one recompute); undo, or make the changes one at a time"
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
        // ProfileControl "None" with Frenet's frame sweeps and is checked as Frenet mode
        const int mode = frenetForNone ? 2 : Mode.getValue();
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
            Base::Vector3d direction = binormalInBody;
            direction.Normalize();
            return pointText(gp_Pnt(direction.x, direction.y, direction.z));
        };
        if (mode == 4) {
            binormal = sweptBinormal(binormalInBody, getLocation());
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
            if (!fold.tilted && !fold.arc) {
                // A curve tighter than the profile reaches from it (foldsAlongCurves)
                return fmt::format(
                    "Pipe: the profile folds {}over itself along the curve from {} ({}): the curve "
                    "bends tighter than the profile reaches from the path{}. Use a gentler curve or "
                    "a smaller profile{}.",
                    small ? "slightly " : "",
                    inPlace(fold.at),
                    by,
                    small ? ", and the result may cross itself there" : "",
                    small ? " to avoid it" : ""
                );
            }
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
            // and the profile's frames and the spine's, each its origin and the ends of its x and
            // y axes, in the body
            for (const gp_Trsf& frame : {frames[0], frames[1], spineFrame}) {
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

        // Each section in perpendicular planes with the one before turned the least that decides
        // OCCT's pairing as rounding would (ops#396, sectionTiltsAlong); its outer wire's turn
        // for its inner wires too, which stay in its plane
        std::vector<std::optional<gp_Trsf>> sectionTilts;
        if (!wiresections.empty() && wiresections.front().size() > 1) {
            std::vector<TopoDS_Shape> placed;
            for (const Part::TopoShape& wire : wiresections.front()) {
                placed.push_back(wire.getShape().Moved(invObjLoc));
            }
            std::optional<gp_Pnt> outOfPlane;
            sectionTilts = sectionTiltsAlong(placed, TopoDS::Wire(path.getShape()), outOfPlane);
            if (outOfPlane) {
                return new App::DocumentObjectExecReturn(fmt::format(
                    "Pipe: the section at {} lies at a right angle to the one before it, as "
                    "another section does to its own, but about another axis. Sections at right "
                    "angles to the ones before them about different axes aren't supported: the "
                    "solid would depend on rounding. Turn the sections there away from 90 degrees "
                    "to each other, or keep the spine and its sections' right angles in one plane.",
                    inPlace(*outOfPlane)
                ));
            }
        }
        auto place = [&](Part::TopoShape& wire, size_t index) {
            wire.move(invObjLoc);
            if (index < sectionTilts.size() && sectionTilts[index]) {
                wire.move(*sectionTilts[index]);
            }
        };

        // Slice 3: twist, scale, lock faces (the frame's guide and the scale's law)
        if (HasTwist.getValue() || HasScale.getValue() || ProfileControl.getValue() == 3) {
            if (!profilePoint.isNull() || (Transformation.getValue() == 1 && !multisections.empty())
                || Transformation.getValue() > 1) {
                return new App::DocumentObjectExecReturn(
                    "Pipe: twist, scale and 'Lock faces' sweep one profile, without Sections or "
                    "a section transformation"
                );
            }
            std::vector<TopoDS_Shape> profileWires;
            for (const auto& wires : wiresections) {
                if (!wires.empty()) {
                    profileWires.push_back(wires.front().getShape().Moved(invObjLoc));
                }
            }
            if (const std::optional<std::string> error
                = prepareSlice3(path, profileWires, invObjLoc, scalinglaw)) {
                return new App::DocumentObjectExecReturn(*error);
            }
        }

        std::vector<Part::TopoShape> frontwires, backwires;
        for (auto& wires : wiresections) {
            for (size_t i = 0; i < wires.size(); ++i) {
                place(wires[i], i);
            }
            auto addSections = [&](BRepOffsetAPI_MakePipeShell& pipe) {
                if (!scalinglaw) {
                    if (!profilePoint.isNull()) {
                        pipe.Add(copyProfilePoint.getShape());
                    }
                    for (const auto& wire : wires) {
                        pipe.Add(wire.getShape());
                    }
                }
                else {
                    if (!profilePoint.isNull()) {
                        pipe.SetLaw(copyProfilePoint.getShape(), scalinglaw);
                    }
                    for (const auto& wire : wires) {
                        pipe.SetLaw(wire.getShape(), scalinglaw);
                    }
                }
            };
            auto standard
                = std::make_unique<BRepOffsetAPI_MakePipeShell>(TopoDS::Wire(path.getShape()));
            setupAlgorithm(*standard, auxpath.getShape());
            addSections(*standard);
            // A loose Standard sweep of circles about the spine is built again with the Frenet
            // frame, the same solid (ops#667): OCCT's corrected Frenet law drifts along a long 3D
            // spine (a circle of radius 0.5 along a 50-turn spiral of 1000 points: 0.4 mm off the
            // tube, tolerances of 2 mm, and one face that failed the shape check on macOS alone),
            // where the Frenet frame built it 6e-6 off with tolerances of 5e-5. Taken only when
            // valid and no longer loose; other sweeps are unchanged
            if (mode == 0 && !scalinglaw && profilePoint.isNull()
                && circlesAboutSpine(wires, path.getShape())) {
                const auto tolerance = [](const TopoDS_Shape& shape) {
                    return ShapeAnalysis_ShapeTolerance().Tolerance(shape, 1);
                };
                try {
                    standard->Build();
                    if (standard->IsDone()
                        && tolerance(standard->Shape())
                            > Part::PipeShellApproximation::warningTolerance) {
                        auto frenet = std::make_unique<BRepOffsetAPI_MakePipeShell>(
                            TopoDS::Wire(path.getShape())
                        );
                        setupAlgorithm(*frenet, auxpath.getShape());
                        frenet->SetMode(true);
                        addSections(*frenet);
                        frenet->Build();
                        if (frenet->IsDone()
                            && tolerance(frenet->Shape())
                                <= Part::PipeShellApproximation::warningTolerance
                            && Part::KernelBudget::checkValid(frenet->Shape())) {
                            standard = std::move(frenet);
                        }
                    }
                }
                catch (const Standard_Failure&) {
                    // The Standard sweep as it builds below, with its own errors
                }
            }
            BRepOffsetAPI_MakePipeShell& mkPS = *standard;

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

            // Standard and Frenet with one profile too: the fold check along curves needs it
            if (sheared || fixedMode || binormalSections
                || ((mode == 0 || mode == 2) && profilePoint.isNull() && multisections.empty())) {
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
        // One profile in Standard or Frenet mode (ProfileControl None): a path that bends tighter
        // than the profile reaches from it folds the sweep back through itself, which BRepCheck
        // and the classifier pass (skeptic c721, finding 1). A small fold warns, as above.
        if ((mode == 0 || mode == 2) && profilePoint.isNull() && multisections.empty()
            && !tilts.folded && !sweptStarts.empty()) {
            const CornerTilts curves
                = foldsAlongCurves(sweptStarts, TopoDS::Wire(path.getShape()), setup, binormal);
            if (const auto& fold = curves.folded) {
                return new App::DocumentObjectExecReturn(foldText(*fold, false));
            }
            if (curves.smallFold && !tilts.smallFold) {
                tilts.smallFold = curves.smallFold;
            }
            if (const auto& unchecked = curves.unchecked) {
                warn(fmt::format(
                    "Pipe: the curve from {} bends in too many places to check them all for "
                    "folds: {} stretch{} where the profile could fold over itself {} left "
                    "unchecked, and the result may cross itself there.",
                    inPlace(unchecked->first),
                    unchecked->second,
                    unchecked->second == 1 ? "" : "es",
                    unchecked->second == 1 ? "was" : "were"
                ));
            }
        }

        Part::TopoShape result = makeTopoShape();

        if (!tilts.pieceStarts.empty() && (!frameGuide.IsNull() || scalinglaw)) {
            return new App::DocumentObjectExecReturn(
                "Pipe: with twist, scale or 'Lock faces' the path's corners must turn the profile "
                "less than 90 degrees in 'Transformed' (it would be swept in pieces). Use 'Right "
                "corner' or 'Round corner'."
            );
        }
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
            // Before any check reads them: the same verdicts on every platform (ops#667)
            raiseTightEdgeTolerances(s);
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

        // Tubes overlapping where the path passes near itself (oracle 9, ops#660, ops#666): Onshape
        // builds their exact union, and so does FreeCAD-CH, from the sweep's cells numbered by their
        // winding number (unionOfOverlaps), before the holes' shells are cut (a cut of solids that
        // interfere with themselves is unpredictable). Named from the sweep through the history, as
        // a fuse is: a face the overlap doesn't reach keeps its name. Thin keeps the stop below.
        bool united = false;
        std::string notUnited;
        if (passesNear && BodyType.getValue() != 1) {
            std::vector<TopoDS_Shape> solids;
            for (const auto& s : shapes) {
                solids.push_back(s.getShape());
            }
            SweepUnion overlap = unionOfOverlaps(solids, depths);
            // A cell OCCT's maker couldn't build (a holed profile's wall meeting itself): again
            // with the tubes cut at the spine's joints. Only then, so every union the maker builds
            // uncut keeps its cells and its faces' names as they were
            bool roundUncut = false;
            if (overlap.unusedFaces) {
                const std::vector<TopoDS_Face> cuts
                    = jointSections(solids, TopoDS::Wire(path.getShape()));
                if (!cuts.empty()) {
                    overlap = unionOfOverlaps(solids, depths, cuts);
                }
                // A Round corner's joint has no planar edges to cut at (its sphere wedge spans
                // the bisecting plane): said, so the stop names the option (sweeps 18). Onshape
                // has no Round corner; it mitres every sharp corner, as Right corner does
                roundUncut = cuts.empty() && Transition.getValue() == 2;
            }
            notUnited = overlap.untouched ? std::string("the overlap lies within one of its faces")
                                          : overlap.error;
            if (roundUncut && !notUnited.empty()) {
                notUnited += "; a Round corner's joint can't be cut there, Right corner (Onshape's "
                             "mitre) can";
            }
            if (!overlap.solid.IsNull()) {
                Part::TopoShape naive = makeTopoShape();
                naive.makeElementCompound(
                    shapes,
                    nullptr,
                    Part::TopoShape::SingleShapeCompoundCreationPolicy::returnShape
                );
                Part::TopoShape unionShape = makeTopoShape();
                unionShape.makeShapeWithElementMap(
                    overlap.solid,
                    Part::MapperHistory(overlap.history),
                    {naive},
                    Part::OpCodes::Fuse
                );
                if (!isValidSolid(unionShape)) {
                    return new App::DocumentObjectExecReturn(invalidPipe());
                }
                result = unionShape;
                AddSubShape.setValue(result);
                united = true;
            }
        }
        if (united) {
            // The union replaces the fuse and the holes' cut
        }
        else if (deepest == 0) {
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

        // Where the union couldn't be built, or for Thin, the sweep counts an overlap twice: a stop
        // when OCCT's check finds one
        if (passesNear && !united && (BodyType.getValue() == 1 || !notUnited.empty())
            && intersectsItself(result.getShape())) {
            return new App::DocumentObjectExecReturn(fmt::format(
                "Pipe: the swept body overlaps itself where the path passes {:.6g} mm from itself "
                "near {}. Onshape builds the union there; FreeCAD-CH {}. Move the path's edges "
                "apart or make the profile smaller.",
                passesNear->second,
                pointText(passesNear->first.Transformed(invObjLoc.Inverted().Transformation())),
                notUnited.empty() ? std::string("doesn't for a thin body")
                                  : "couldn't build it (" + notUnited + ")"
            ));
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
            storeSpineEnds();  // the sweep itself is good
            warnIfLoose();
            return App::DocumentObject::StdReturn;
        }

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

    // Twist and lock faces: the guide orients the frame, its normal pointing from the path to
    // the guide in each plane square to the path (OCCT's guide in a plane is exact here, where
    // the curvilinear equivalence approximated the twisted faces to 1e-2 mm)
    if (!frameGuide.IsNull()) {
        mkPipeShell.SetMode(frameGuide, false, BRepFill_NoContact);
        return;
    }

    bool auxiliary = false;
    const Base::Vector3d& bVec = binormalInBody;
    switch (Mode.getValue()) {
        case 0:
            // ProfileControl "None" off a plane, where Frenet's frame is steady (execute)
            if (frenetForNone) {
                mkPipeShell.SetMode(true);
            }
            break;
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
    // New / Add / Remove / Intersect on one Sweep (FreeCAD-CH ops#640 rank 20)
    allowAllOperations();
}

PROPERTY_SOURCE(PartDesign::SubtractivePipe, PartDesign::Pipe)
SubtractivePipe::SubtractivePipe()
{
    defineSubtractive();
    allowAllOperations();
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
