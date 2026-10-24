// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *                                                                          *
 *   Copyright (c) 2002 Jürgen Riegel <juergen.riegel@web.de>               *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/


#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepGProp.hxx>
#include <Geom_Plane.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <GeomProjLib.hxx>
#include <GProp_GProps.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <gp.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <algorithm>
#include <array>


#include "TopoShapeMapper.h"
#include "Geometry.h"

namespace Part
{

void ShapeMapper::expand(const TopoDS_Shape& d, std::vector<TopoDS_Shape>& shapes)
{
    if (d.IsNull()) {
        return;
    }
    for (TopExp_Explorer xp(d, TopAbs_FACE); xp.More(); xp.Next()) {
        shapes.push_back(xp.Current());
    }
    for (TopExp_Explorer xp(d, TopAbs_EDGE, TopAbs_FACE); xp.More(); xp.Next()) {
        shapes.push_back(xp.Current());
    }
    for (TopExp_Explorer xp(d, TopAbs_VERTEX, TopAbs_EDGE); xp.More(); xp.Next()) {
        shapes.push_back(xp.Current());
    }
}

void ShapeMapper::populate(
    MappingStatus status,
    const TopTools_ListOfShape& src,
    const TopTools_ListOfShape& dst
)
{
    for (TopTools_ListIteratorOfListOfShape it(src); it.More(); it.Next()) {
        populate(status, it.Value(), dst);
    }
}

void ShapeMapper::populate(MappingStatus status, const TopoShape& src, const TopTools_ListOfShape& dst)
{
    if (src.isNull()) {
        return;
    }
    std::vector<TopoDS_Shape> dstShapes;
    for (TopTools_ListIteratorOfListOfShape it(dst); it.More(); it.Next()) {
        expand(it.Value(), dstShapes);
    }
    insert(status, src.getShape(), dstShapes);
    if (shapeSet.insert(src.getShape()).second) {
        shapes.push_back(src);
    }
}

void ShapeMapper::insert(MappingStatus status, const TopoDS_Shape& s, const TopoDS_Shape& d)
{
    if (s.IsNull() || d.IsNull()) {
        return;
    }

    ShapeValue* entry = nullptr;

    // Prevent an element shape from being both generated and modified
    if (status == MappingStatus::Generated) {
        if (_modifiedShapes.count(d) || _projectedShapes.count(d)) {
            return;
        }
        _generatedShapes.insert(d);
        entry = &_generated[s];
    }
    else if (status == MappingStatus::Modified) {
        if (_generatedShapes.count(d) || _projectedShapes.count(d)) {
            return;
        }
        _modifiedShapes.insert(d);
        entry = &_modified[s];
    }
    else if (status == MappingStatus::Projected) {
        if (_generatedShapes.count(d) || _modifiedShapes.count(d)) {
            return;
        }
        _projectedShapes.insert(d);
        entry = &_projected[s];
    }

    if (entry != nullptr && entry->shapeSet.insert(d).second) {
        entry->shapes.push_back(d);
    }
};

void ShapeMapper::insert(MappingStatus status, const TopoDS_Shape& s, const std::vector<TopoDS_Shape>& d)
{
    if (s.IsNull() || d.empty()) {
        return;
    }
    ShapeValue* entry = nullptr;
    for (auto& shape : d) {
        // Prevent an element shape from being both generated and modified
        if (status == MappingStatus::Generated) {
            if (_modifiedShapes.count(shape) || _projectedShapes.count(shape)) {
                continue;
            }
            _generatedShapes.insert(shape);
            entry = &_generated[s];
        }
        else if (status == MappingStatus::Modified) {
            if (_generatedShapes.count(shape) || _projectedShapes.count(shape)) {
                continue;
            }
            _modifiedShapes.insert(shape);
            entry = &_modified[s];
        }
        else if (status == MappingStatus::Projected) {
            if (_generatedShapes.count(shape) || _modifiedShapes.count(shape)) {
                continue;
            }
            _projectedShapes.insert(shape);
            entry = &_projected[s];
        }
        if (entry != nullptr && entry->shapeSet.insert(shape).second) {
            entry->shapes.push_back(shape);
        }
    }
};

void GenericShapeMapper::init(const TopoShape& src, const TopoDS_Shape& dst)
{
    for (TopExp_Explorer exp(dst, TopAbs_FACE); exp.More(); exp.Next()) {
        const TopoDS_Shape& dstFace = exp.Current();
        if (src.findShape(dstFace)) {
            continue;
        }
#if OCC_VERSION_HEX < 0x070800
        struct TopoDS_ShapeHasher
        {
            std::size_t operator()(const TopoDS_Shape& key) const
            {
                return key.HashCode(IntegerLast());
            }
        };
        std::unordered_map<TopoDS_Shape, int, TopoDS_ShapeHasher> map;
#else
        std::unordered_map<TopoDS_Shape, int> map;
#endif
        bool found = false;

        // Try to find a face in the src that shares at least two edges (or one
        // closed edge) with dstFace.
        // TODO: consider degenerative cases of two or more edges on the same line.
        for (TopExp_Explorer it(dstFace, TopAbs_EDGE); it.More(); it.Next()) {
            int idx = src.findShape(it.Current());
            if (!idx) {
                continue;
            }
            TopoDS_Edge e = TopoDS::Edge(it.Current());
            if (BRep_Tool::IsClosed(e)) {
                // closed edge, one face is enough
                TopoDS_Shape face
                    = src.findAncestorShape(src.getSubShape(TopAbs_EDGE, idx), TopAbs_FACE);
                if (!face.IsNull()) {
                    this->insert(MappingStatus::Generated, face, dstFace);
                    found = true;
                    break;
                }
                continue;
            }
            for (auto& face :
                 src.findAncestorsShapes(src.getSubShape(TopAbs_EDGE, idx), TopAbs_FACE)) {
                int& cnt = map[face];
                if (++cnt == 2) {
                    this->insert(MappingStatus::Generated, face, dstFace);
                    found = true;
                    break;
                }
                if (found) {
                    break;
                }
            }
        }

        if (found) {
            continue;
        }

        // if no face matches, try search by geometry surface
        std::unique_ptr<Geometry> g(Geometry::fromShape(dstFace));
        if (!g) {
            continue;
        }

        for (auto& v : map) {
            std::unique_ptr<Geometry> g2(Geometry::fromShape(v.first));
            if (g2 && g2->isSame(*g, 1e-7, 1e-12)) {
                this->insert(MappingStatus::Generated, v.first, dstFace);
                break;
            }
        }
    }
}

namespace
{
/// True if the pieces of a cap meet one another along `seams` alone, the seams of the up-to
/// shape's faces (a closed B-spline face's): they are one cap, which a refine makes one face.
/// The pieces of a far edge meet at `seams`' vertices (`along` TopAbs_VERTEX)
bool joinedAtSeams(
    const TopTools_ListOfShape& pieces,
    const TopTools_MapOfShape& seams,
    TopAbs_ShapeEnum along = TopAbs_EDGE
)
{
    std::vector<TopoDS_Shape> left;
    for (const TopoDS_Shape& piece : pieces) {
        left.push_back(piece);
    }
    TopTools_MapOfShape reached;
    auto join = [&](const TopoDS_Shape& piece) {
        for (TopExp_Explorer joints(piece, along); joints.More(); joints.Next()) {
            if (seams.Contains(joints.Current())) {
                reached.Add(joints.Current());
            }
        }
    };
    join(left.front());
    left.erase(left.begin());
    for (bool grew = true; grew && !left.empty();) {
        grew = false;
        for (auto it = left.begin(); it != left.end();) {
            bool meets = false;
            for (TopExp_Explorer joints(*it, along); joints.More() && !meets; joints.Next()) {
                meets = reached.Contains(joints.Current());
            }
            if (!meets) {
                ++it;
                continue;
            }
            join(*it);
            it = left.erase(it);
            grew = true;
        }
    }
    return left.empty();
}

/// The seams of `upTo`'s faces, as the split leaves them
TopTools_MapOfShape seamsOf(BRepAlgoAPI_Splitter& splitter, const TopoDS_Shape& upTo)
{
    TopTools_MapOfShape seams;
    for (TopExp_Explorer faces(upTo, TopAbs_FACE); faces.More(); faces.Next()) {
        const TopoDS_Face& face = TopoDS::Face(faces.Current());
        for (TopExp_Explorer edges(face, TopAbs_EDGE); edges.More(); edges.Next()) {
            const TopoDS_Edge& edge = TopoDS::Edge(edges.Current());
            if (!BRep_Tool::IsClosed(edge, face)) {
                continue;
            }
            const TopTools_ListOfShape& pieces = splitter.Modified(edge);
            if (pieces.IsEmpty()) {
                seams.Add(edge);
            }
            for (const TopoDS_Shape& piece : pieces) {
                seams.Add(piece);
            }
        }
    }
    return seams;
}

/// What each piece of `upTo` is a piece of: its face, or for an edge every edge of `upTo` it
/// lies on (a shell's faces that meet along a line each bring their edge)
TopTools_DataMapOfShapeListOfShape sourcesOf(BRepAlgoAPI_Splitter& splitter, const TopoDS_Shape& upTo)
{
    TopTools_DataMapOfShapeListOfShape sources;
    for (TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_EDGE}) {
        TopTools_IndexedMapOfShape elements;
        TopExp::MapShapes(upTo, type, elements);
        for (int i = 1; i <= elements.Extent(); ++i) {
            TopTools_ListOfShape pieces = splitter.Modified(elements(i));
            if (pieces.IsEmpty()) {
                pieces.Append(elements(i));
            }
            for (const TopoDS_Shape& piece : pieces) {
                if (!sources.IsBound(piece)) {
                    sources.Bind(piece, TopTools_ListOfShape());
                }
                sources.ChangeFind(piece).Append(elements(i));
            }
        }
    }
    return sources;
}
}  // namespace

UpToSplitMapper::UpToSplitMapper(
    BRepAlgoAPI_Splitter& splitter,
    BRepBuilderAPI_MakeShape& sweep,
    const std::function<TopoDS_Shape(const TopoDS_Shape&)>& firstShape,
    const TopoDS_Shape& profile,
    const TopoDS_Shape& result,
    const TopoDS_Shape& upTo,
    const std::optional<gp_Dir>& along
)
    : MapperMaker(splitter)
    , along(along)
{
    for (TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        TopExp::MapShapes(result, type, kept);
    }
    // In the profile's order (ops#19: names are written in a defined order)
    std::vector<TopTools_ListOfShape> severalEdgePieces;
    for (TopAbs_ShapeEnum type : {TopAbs_EDGE, TopAbs_VERTEX}) {
        TopTools_IndexedMapOfShape elements;
        TopExp::MapShapes(profile, type, elements);
        for (int i = 1; i <= elements.Extent(); ++i) {
            const TopoDS_Shape& element = elements(i);
            TopTools_ListOfShape farEnds;
            for (const TopoDS_Shape& side : sweep.Generated(element)) {
                for (const TopoDS_Shape& meeting : splitter.Generated(side)) {
                    if (meeting.ShapeType() == type && kept.Contains(meeting)
                        && farEnd.Add(meeting)) {
                        farEnds.Append(meeting);
                        farSources.Bind(meeting, firstShape(element));
                    }
                }
            }
            if (!farEnds.IsEmpty()) {
                projections.Bind(firstShape(element), farEnds);
            }
            if (type == TopAbs_EDGE && farEnds.Extent() > 1) {
                severalEdgePieces.push_back(farEnds);
            }
        }
    }
    if (upTo.IsNull()) {
        return;
    }
    const TopTools_MapOfShape seams = seamsOf(splitter, upTo);
    const std::vector<TopTools_ListOfShape> severalCaps
        = bindFarCaps(splitter, firstShape, profile, result, upTo, seams);
    // A far edge's pieces that meet only at the seam of a face of `upTo` are one edge, as for caps
    TopTools_MapOfShape seamVertices;
    for (TopTools_MapOfShape::Iterator seam(seams); seam.More(); seam.Next()) {
        for (TopExp_Explorer vertices(seam.Key(), TopAbs_VERTEX); vertices.More(); vertices.Next()) {
            seamVertices.Add(vertices.Current());
        }
    }
    std::erase_if(severalEdgePieces, [&seamVertices](const TopTools_ListOfShape& pieces) {
        return joinedAtSeams(pieces, seamVertices, TopAbs_VERTEX);
    });
    // Marked once every far cap is known: a piece's marks depend on the other caps on its face
    if (!severalCaps.empty() || !severalEdgePieces.empty()) {
        const TopTools_DataMapOfShapeListOfShape sources = sourcesOf(splitter, upTo);
        markCaps(severalCaps, sources);
        markFarEdges(splitter, upTo, severalEdgePieces, sources);
    }
}

std::vector<TopTools_ListOfShape> UpToSplitMapper::bindFarCaps(
    BRepAlgoAPI_Splitter& splitter,
    const std::function<TopoDS_Shape(const TopoDS_Shape&)>& firstShape,
    const TopoDS_Shape& profile,
    const TopoDS_Shape& result,
    const TopoDS_Shape& upTo,
    const TopTools_MapOfShape& seams
)
{
    // The far caps (ops#360): for each face of the profile, in its order, the pieces of `upTo`
    // in the kept solids that start at the face's start cap, in `upTo`'s face order, a face of
    // `upTo` the split leaves whole included. A cap that spans several faces of `upTo`, or that a
    // hole in one cuts, has several pieces, each marked by what bounds it; pieces that meet only
    // along the seam of a face of `upTo` are one cap. A piece of the start cap is left out: where
    // the profile lies on `upTo`, the splitter makes the two one face
    const TopTools_IndexedMapOfShape upToPieces = piecesOf(splitter, upTo);
    TopTools_IndexedMapOfShape solids;
    TopExp::MapShapes(result, TopAbs_SOLID, solids);
    TopTools_IndexedMapOfShape profileFaces;
    TopExp::MapShapes(profile, TopAbs_FACE, profileFaces);
    std::vector<TopTools_ListOfShape> severalPieces;
    for (int i = 1; i <= profileFaces.Extent(); ++i) {
        const TopoDS_Shape startCap = firstShape(profileFaces(i));
        const TopTools_IndexedMapOfShape startPieces = piecesOf(splitter, startCap);
        TopTools_MapOfShape facesOfItsSolids;
        for (int j = 1; j <= solids.Extent(); ++j) {
            TopTools_IndexedMapOfShape solidFaces;
            TopExp::MapShapes(solids(j), TopAbs_FACE, solidFaces);
            bool startsHere = false;
            for (int k = 1; k <= solidFaces.Extent() && !startsHere; ++k) {
                startsHere = startPieces.Contains(solidFaces(k));
            }
            for (int k = 1; startsHere && k <= solidFaces.Extent(); ++k) {
                facesOfItsSolids.Add(solidFaces(k));
            }
        }
        TopTools_ListOfShape caps;
        for (int k = 1; k <= upToPieces.Extent(); ++k) {
            const TopoDS_Shape& piece = upToPieces(k);
            if (facesOfItsSolids.Contains(piece) && !startPieces.Contains(piece)
                && farCaps.Add(piece)) {
                caps.Append(piece);
            }
        }
        if (!caps.IsEmpty()) {
            projections.Bind(startCap, caps);
        }
        if (caps.Extent() > 1 && !joinedAtSeams(caps, seams)) {
            severalPieces.push_back(caps);
        }
    }
    return severalPieces;
}

namespace
{
/// True if `a` and `b` hold the same shapes
bool sameShapes(const TopTools_IndexedMapOfShape& a, const TopTools_IndexedMapOfShape& b)
{
    if (a.Extent() != b.Extent()) {
        return false;
    }
    for (int i = 1; i <= a.Extent(); ++i) {
        if (!b.Contains(a(i))) {
            return false;
        }
    }
    return true;
}

using PlacedTwins = std::vector<std::pair<gp_Pnt, std::size_t>>;

/// How far `placed`'s centres spread along `axis` (1 x, 2 y, 3 z)
double spreadAlong(const PlacedTwins& placed, int axis)
{
    double low = placed.front().first.Coord(axis);
    double high = low;
    for (const auto& [centre, twin] : placed) {
        low = std::min(low, centre.Coord(axis));
        high = std::max(high, centre.Coord(axis));
    }
    return high - low;
}

/// Orders twins by their centres (PR 340 round 3): along the one of `axes` in which they spread
/// most, an earlier axis unless a later one spreads more by a margin. Centres closer along it
/// than a quarter of the even step (the spread over the gaps) are a run, ordered the same way
/// along the other axes. Two twins then keep their order until the pair turns by about 45 degrees
/// from an axis. Ordered by x first, a pair one above the other swapped on any tilt that moved
/// one ahead in x: the elliptic hole turned 0.0003 degrees moved a reference to the other twin.
/// Where a turn does swap them, the solver's moved check breaks the reference
void orderTwins(PlacedTwins& placed, std::vector<int> axes)
{
    if (placed.size() < 2 || axes.empty()) {
        return;
    }
    // Symmetric twins (four lobes) spread as much along x as along y whatever their turn: the
    // margin keeps their axis from following rounding
    constexpr double margin = 1.01;
    int axis = axes.front();
    double spread = spreadAlong(placed, axis);
    for (int other : axes) {
        const double otherSpread = spreadAlong(placed, other);
        if (otherSpread > margin * spread) {
            axis = other;
            spread = otherSpread;
        }
    }
    std::stable_sort(placed.begin(), placed.end(), [axis](const auto& a, const auto& b) {
        return a.first.Coord(axis) < b.first.Coord(axis);
    });
    axes.erase(std::find(axes.begin(), axes.end(), axis));
    const double step = spread / static_cast<double>(placed.size() - 1);
    const double tie = std::max(step / 4, 100 * Precision::Confusion());
    for (auto run = placed.begin(); run != placed.end();) {
        auto end = std::next(run);
        while (end != placed.end()
               && end->first.Coord(axis) - std::prev(end)->first.Coord(axis) <= tie) {
            ++end;
        }
        PlacedTwins part(run, end);
        orderTwins(part, axes);
        std::copy(part.begin(), part.end(), run);
        run = end;
    }
}

/// The pieces of a far edge in their order along it (PR 366 round 2): by the parameter on
/// `profileEdge` of each piece's middle taken back onto it along `along`, the prism's direction,
/// so that a change of the splitter's order (the up-to shell rebuilt with its faces in another
/// order) or a move of where the pieces meet keeps it. By their centres (orderTwins()) where
/// that can't be measured. Indexes into `pieces`
std::vector<std::size_t> orderAlong(
    const std::vector<TopoDS_Shape>& pieces,
    const TopoDS_Shape& profileEdge,
    const std::optional<gp_Dir>& along
)
{
    std::vector<std::pair<double, std::size_t>> placed;
    std::vector<gp_Pnt> middles(pieces.size());
    if (along && !profileEdge.IsNull() && profileEdge.ShapeType() == TopAbs_EDGE) {
        try {
            double first = 0.0;
            double last = 0.0;
            const Handle(Geom_Curve) curve = BRep_Tool::Curve(TopoDS::Edge(profileEdge), first, last);
            if (!curve.IsNull()) {
                // The edge seen along the direction: a plane across it, the parametrization kept
                const Handle(Geom_Plane) across = new Geom_Plane(gp::Origin(), *along);
                const Handle(Geom_Curve)
                    seen = GeomProjLib::ProjectOnPlane(curve, across, *along, Standard_True);
                const gp_Vec direction(*along);
                for (std::size_t i = 0; i < pieces.size(); ++i) {
                    const BRepAdaptor_Curve piece(TopoDS::Edge(pieces[i]));
                    gp_Pnt middle = piece.Value((piece.FirstParameter() + piece.LastParameter()) / 2);
                    middles[i] = middle;
                    middle.Translate(-direction * gp_Vec(middle.XYZ()).Dot(direction));
                    GeomAPI_ProjectPointOnCurve onEdge(middle, seen, first, last);
                    if (onEdge.NbPoints() == 0) {
                        placed.clear();
                        break;
                    }
                    placed.emplace_back(onEdge.LowerDistanceParameter(), i);
                }
            }
        }
        catch (const Standard_Failure&) {
            placed.clear();
        }
    }
    std::vector<std::size_t> order;
    if (placed.size() == pieces.size()) {
        std::stable_sort(placed.begin(), placed.end(), [](const auto& a, const auto& b) {
            return a.first < b.first;
        });
        for (const auto& [parameter, piece] : placed) {
            order.push_back(piece);
        }
        // Round 3: the same order whichever way the profile edge runs (a rectangle drawn from its
        // other corner reverses its edges, the geometry unchanged): an open edge's pieces go from
        // the first piece towards the last along the largest coordinate of their middles' offset
        if (order.size() > 1 && !BRep_Tool::IsClosed(TopoDS::Edge(profileEdge))) {
            const gp_XYZ offset = middles[order.back()].XYZ() - middles[order.front()].XYZ();
            double largest = offset.X();
            for (double c : {offset.Y(), offset.Z()}) {
                if (std::abs(c) > std::abs(largest)) {
                    largest = c;
                }
            }
            if (largest < 0.0) {
                std::reverse(order.begin(), order.end());
            }
        }
        return order;
    }
    PlacedTwins centres;
    for (std::size_t i = 0; i < pieces.size(); ++i) {
        GProp_GProps props;
        BRepGProp::LinearProperties(pieces[i], props);
        centres.emplace_back(props.CentreOfMass(), i);
    }
    orderTwins(centres, {1, 2, 3});
    for (const auto& [centre, piece] : centres) {
        order.push_back(piece);
    }
    return order;
}

/// A far cap, or a piece of a far edge, among the pieces of its profile face's cap or of its
/// profile edge's far edge
struct Piece
{
    TopoDS_Shape shape;
    /// The faces of `upTo` it lies on
    TopTools_IndexedMapOfShape faces;
    /// The edges of `upTo` that bound it: a cap's edges are pieces of them, a far edge's ends
    /// lie on them
    TopTools_IndexedMapOfShape upToEdges;
    /// The start cap's elements whose projections bound it: a cap's edges, a far edge's vertices
    TopTools_IndexedMapOfShape startBounds;
    TopTools_IndexedMapOfShape marks;
};

/// Marks the pieces of one cap or far edge, into `marks` and `counters` (PR 340 round 2):
/// `onFace` counts the pieces, of whatever the pieces are told apart from, on each face of `upTo`
void markPieces(
    std::vector<Piece>& pieces,
    const TopTools_DataMapOfShapeInteger& onFace,
    TopTools_DataMapOfShapeListOfShape& marks,
    TopTools_DataMapOfShapeInteger& counters
)
{
    // The face of `upTo` a piece lies on, alone where it is the only piece there, so that a
    // change of its bounds keeps its name; with the edges of `upTo` that bound it where other
    // pieces lie on that face; with the start cap's elements whose projections bound it among
    // pieces those don't tell apart. A sketch edit that splits or redraws a profile edge changes
    // the marks only where they are needed
    for (Piece& piece : pieces) {
        bool alone = true;
        for (int i = 1; i <= piece.faces.Extent(); ++i) {
            piece.marks.Add(piece.faces(i));
            const int* count = onFace.Seek(piece.faces(i));
            alone = alone && count && *count == 1;
        }
        for (int i = 1; !alone && i <= piece.upToEdges.Extent(); ++i) {
            piece.marks.Add(piece.upToEdges(i));
        }
    }
    std::vector<bool> told(pieces.size(), true);
    for (std::size_t i = 0; i < pieces.size(); ++i) {
        for (std::size_t j = i + 1; j < pieces.size(); ++j) {
            if (sameShapes(pieces[i].marks, pieces[j].marks)) {
                told[i] = told[j] = false;
            }
        }
    }
    for (std::size_t i = 0; i < pieces.size(); ++i) {
        for (int k = 1; !told[i] && k <= pieces[i].startBounds.Extent(); ++k) {
            pieces[i].marks.Add(pieces[i].startBounds(k));
        }
        TopTools_ListOfShape list;
        for (int k = 1; k <= pieces[i].marks.Extent(); ++k) {
            list.Append(pieces[i].marks(k));
        }
        marks.Bind(pieces[i].shape, list);
    }
    // Pieces with the same marks still (a circle across an elliptic hole: the pieces on either
    // side are bounded by the circle and the ellipse alone) are told apart by the duplicate
    // counter, which the solver reads as "a sibling, never the element itself": a reference that
    // lands on another of them breaks instead of following it. The counter holds how many share
    // the marks, so that one going or coming renames them all, and each one's place among them,
    // by their centres (orderTwins()), so that a change of the splitter's order (the up-to face
    // rebuilt with another parametrization) renames none
    std::vector<bool> counted(pieces.size(), false);
    for (std::size_t i = 0; i < pieces.size(); ++i) {
        if (counted[i]) {
            continue;
        }
        std::vector<std::size_t> twins {i};
        for (std::size_t j = i + 1; j < pieces.size(); ++j) {
            if (!counted[j] && sameShapes(pieces[i].marks, pieces[j].marks)) {
                twins.push_back(j);
                counted[j] = true;
            }
        }
        if (twins.size() < 2) {
            continue;
        }
        PlacedTwins placed;
        for (std::size_t twin : twins) {
            GProp_GProps props;
            if (pieces[twin].shape.ShapeType() == TopAbs_EDGE) {
                BRepGProp::LinearProperties(pieces[twin].shape, props);
            }
            else {
                BRepGProp::SurfaceProperties(pieces[twin].shape, props);
            }
            placed.emplace_back(props.CentreOfMass(), twin);
        }
        orderTwins(placed, {1, 2, 3});
        const int count = static_cast<int>(placed.size());
        for (int position = 0; position < count; ++position) {
            // One number for the pair: count (count - 1) / 2 + position, 1 and 2 for two
            // pieces, 3 to 5 for three; 0 is a piece with marks of its own
            const int counter = count * (count - 1) / 2 + position;
            counters.Bind(pieces[placed[position].second].shape, counter);
        }
    }
}
}  // namespace

void UpToSplitMapper::markCaps(
    const std::vector<TopTools_ListOfShape>& severalPieces,
    const TopTools_DataMapOfShapeListOfShape& sources
)
{
    // How many far caps, of any profile face, lie on each face of `upTo` (a count: the map's
    // order doesn't matter)
    TopTools_DataMapOfShapeInteger capsOnFace;
    for (TopTools_MapOfShape::Iterator cap(farCaps); cap.More(); cap.Next()) {
        if (const TopTools_ListOfShape* faces = sources.Seek(cap.Key())) {
            for (const TopoDS_Shape& face : *faces) {
                if (int* count = capsOnFace.ChangeSeek(face)) {
                    ++*count;
                }
                else {
                    capsOnFace.Bind(face, 1);
                }
            }
        }
    }
    for (const TopTools_ListOfShape& caps : severalPieces) {
        std::vector<Piece> pieces;
        for (const TopoDS_Shape& cap : caps) {
            Piece piece;
            piece.shape = cap;
            if (const TopTools_ListOfShape* faces = sources.Seek(cap)) {
                for (const TopoDS_Shape& face : *faces) {
                    piece.faces.Add(face);
                }
            }
            TopTools_IndexedMapOfShape edges;
            TopExp::MapShapes(cap, TopAbs_EDGE, edges);
            for (int i = 1; i <= edges.Extent(); ++i) {
                if (const TopoDS_Shape* source = farSources.Seek(edges(i))) {
                    piece.startBounds.Add(*source);
                }
                if (const TopTools_ListOfShape* pieceOf = sources.Seek(edges(i))) {
                    for (const TopoDS_Shape& source : *pieceOf) {
                        piece.upToEdges.Add(source);
                    }
                }
            }
            pieces.push_back(std::move(piece));
        }
        markPieces(pieces, capsOnFace, pieceMarks, pieceCounters);
    }
}

void UpToSplitMapper::markFarEdges(
    BRepAlgoAPI_Splitter& splitter,
    const TopoDS_Shape& upTo,
    const std::vector<TopTools_ListOfShape>& severalPieces,
    const TopTools_DataMapOfShapeListOfShape& sources
)
{
    // A far edge cut into several pieces (ops#386), by the faces of `upTo` meeting under it or a
    // hole it crosses, as a cap is: each piece is marked by the face of `upTo` it lies on, where
    // other pieces of the edge lie on that face by the edges of `upTo` through its ends, and
    // among pieces those don't tell apart by the start cap's vertices whose projections end it.
    // The faces each edge of the pieces of `upTo` bounds:
    TopoDS_Compound upToPieces;
    BRep_Builder builder;
    builder.MakeCompound(upToPieces);
    const TopTools_IndexedMapOfShape faces = piecesOf(splitter, upTo);
    for (int i = 1; i <= faces.Extent(); ++i) {
        builder.Add(upToPieces, faces(i));
    }
    TopTools_IndexedDataMapOfShapeListOfShape facesOfEdge;
    TopExp::MapShapesAndAncestors(upToPieces, TopAbs_EDGE, TopAbs_FACE, facesOfEdge);
    // The edges of `upTo` through each vertex of their pieces
    TopTools_DataMapOfShapeListOfShape edgesAtVertex;
    for (TopTools_DataMapOfShapeListOfShape::Iterator it(sources); it.More(); it.Next()) {
        if (it.Key().ShapeType() != TopAbs_EDGE) {
            continue;
        }
        for (TopExp_Explorer vertices(it.Key(), TopAbs_VERTEX); vertices.More(); vertices.Next()) {
            if (!edgesAtVertex.IsBound(vertices.Current())) {
                edgesAtVertex.Bind(vertices.Current(), TopTools_ListOfShape());
            }
            for (const TopoDS_Shape& edge : it.Value()) {
                edgesAtVertex.ChangeFind(vertices.Current()).Append(edge);
            }
        }
    }
    for (const TopTools_ListOfShape& edges : severalPieces) {
        std::vector<Piece> pieces;
        // How many pieces of this edge lie on each face of `upTo`: the other far edges have
        // other names
        TopTools_DataMapOfShapeInteger piecesOnFace;
        for (const TopoDS_Shape& edge : edges) {
            Piece piece;
            piece.shape = edge;
            if (const TopTools_ListOfShape* holders = facesOfEdge.Seek(edge)) {
                for (const TopoDS_Shape& holder : *holders) {
                    if (const TopTools_ListOfShape* pieceOf = sources.Seek(holder)) {
                        for (const TopoDS_Shape& face : *pieceOf) {
                            piece.faces.Add(face);
                        }
                    }
                }
            }
            for (int i = 1; i <= piece.faces.Extent(); ++i) {
                if (int* count = piecesOnFace.ChangeSeek(piece.faces(i))) {
                    ++*count;
                }
                else {
                    piecesOnFace.Bind(piece.faces(i), 1);
                }
            }
            for (TopExp_Explorer vertices(edge, TopAbs_VERTEX); vertices.More(); vertices.Next()) {
                if (const TopTools_ListOfShape* through = edgesAtVertex.Seek(vertices.Current())) {
                    for (const TopoDS_Shape& upToEdge : *through) {
                        piece.upToEdges.Add(upToEdge);
                    }
                }
                if (const TopoDS_Shape* source = farSources.Seek(vertices.Current())) {
                    piece.startBounds.Add(*source);
                }
            }
            pieces.push_back(std::move(piece));
        }
        markPieces(pieces, piecesOnFace, pieceMarks, pieceCounters);
        // And each piece's place along the edge among how many there are, in the duplicate
        // counter as for twins (PR 366 round 2). The marks of an up-to shape without names are
        // its faces' and edges' indexes: rebuilt with its faces in another order, it gives a
        // piece's marks to another piece, and a reference followed that one silently when the
        // pieces moved too, or one went. With its place and the count, the name is no piece's
        // then, or the piece's in the same place. A piece going or coming renames them all
        std::vector<TopoDS_Shape> shapes;
        for (const Piece& piece : pieces) {
            shapes.push_back(piece.shape);
        }
        const TopoDS_Shape* profileEdge = farSources.Seek(edges.First());
        const std::vector<std::size_t> order
            = orderAlong(shapes, profileEdge ? *profileEdge : TopoDS_Shape(), along);
        const int count = static_cast<int>(order.size());
        for (int position = 0; position < count; ++position) {
            pieceCounters.Bind(shapes[order[position]], count * (count - 1) / 2 + position);
        }
    }
}

bool UpToSplitMapper::isFarCap(const TopoDS_Shape& shape) const
{
    return farCaps.Contains(shape);
}

int UpToSplitMapper::counterOf(const TopoDS_Shape& piece) const
{
    const int* counter = pieceCounters.Seek(piece);
    return counter ? *counter : 0;
}

std::vector<TopoDS_Shape> UpToSplitMapper::marksOf(const TopoDS_Shape& piece) const
{
    std::vector<TopoDS_Shape> marks;
    if (const TopTools_ListOfShape* found = pieceMarks.Seek(piece)) {
        for (const TopoDS_Shape& mark : *found) {
            marks.push_back(mark);
        }
    }
    return marks;
}

const std::vector<TopoDS_Shape>& UpToSplitMapper::modified(const TopoDS_Shape& s) const
{
    MapperMaker::modified(s);
    // A far cap is its profile face's projection, not a second name from the up-to shape
    std::erase_if(_res, [this](const TopoDS_Shape& piece) {
        return !kept.Contains(piece) || farCaps.Contains(piece);
    });
    return _res;
}

const std::vector<TopoDS_Shape>& UpToSplitMapper::generated(const TopoDS_Shape& s) const
{
    MapperMaker::generated(s);
    std::erase_if(_res, [this](const TopoDS_Shape& shape) {
        return !kept.Contains(shape) || farEnd.Contains(shape);
    });
    return _res;
}

const std::vector<TopoDS_Shape>& UpToSplitMapper::projected(const TopoDS_Shape& s) const
{
    _res.clear();
    if (const TopTools_ListOfShape* farEnds = projections.Seek(s)) {
        for (const TopoDS_Shape& shape : *farEnds) {
            _res.push_back(shape);
        }
    }
    return _res;
}

TopTools_IndexedMapOfShape UpToSplitMapper::piecesOf(
    BRepAlgoAPI_Splitter& splitter,
    const TopoDS_Shape& shape
)
{
    TopTools_IndexedMapOfShape pieces;
    for (TopExp_Explorer faces(shape, TopAbs_FACE); faces.More(); faces.Next()) {
        const TopTools_ListOfShape& modified = splitter.Modified(faces.Current());
        if (modified.IsEmpty()) {
            pieces.Add(faces.Current());
        }
        for (const TopoDS_Shape& piece : modified) {
            pieces.Add(piece);
        }
    }
    return pieces;
}

TopoDS_Shape UpToSplitMapper::keptShape(const std::vector<TopoDS_Shape>& solids)
{
    if (solids.size() == 1) {
        return solids.front();
    }
    TopoDS_Compound compound;
    BRep_Builder builder;
    builder.MakeCompound(compound);
    for (const TopoDS_Shape& solid : solids) {
        builder.Add(compound, solid);
    }
    return compound;
}

}  // namespace Part
