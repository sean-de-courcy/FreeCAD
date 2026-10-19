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
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
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
/// shape's faces (a closed B-spline face's): they are one cap, which a refine makes one face
bool joinedAtSeams(const TopTools_ListOfShape& pieces, const TopTools_MapOfShape& seams)
{
    std::vector<TopoDS_Shape> left;
    for (const TopoDS_Shape& piece : pieces) {
        left.push_back(piece);
    }
    TopTools_MapOfShape reached;
    auto join = [&](const TopoDS_Shape& piece) {
        for (TopExp_Explorer edges(piece, TopAbs_EDGE); edges.More(); edges.Next()) {
            if (seams.Contains(edges.Current())) {
                reached.Add(edges.Current());
            }
        }
    };
    join(left.front());
    left.erase(left.begin());
    for (bool grew = true; grew && !left.empty();) {
        grew = false;
        for (auto it = left.begin(); it != left.end();) {
            bool meets = false;
            for (TopExp_Explorer edges(*it, TopAbs_EDGE); edges.More() && !meets; edges.Next()) {
                meets = reached.Contains(edges.Current());
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
}  // namespace

UpToSplitMapper::UpToSplitMapper(
    BRepAlgoAPI_Splitter& splitter,
    BRepBuilderAPI_MakeShape& sweep,
    const std::function<TopoDS_Shape(const TopoDS_Shape&)>& firstShape,
    const TopoDS_Shape& profile,
    const TopoDS_Shape& result,
    const TopoDS_Shape& upTo
)
    : MapperMaker(splitter)
{
    for (TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        TopExp::MapShapes(result, type, kept);
    }
    // In the profile's order (ops#19: names are written in a defined order)
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
                        if (type == TopAbs_EDGE) {
                            farSources.Bind(meeting, firstShape(element));
                        }
                    }
                }
            }
            if (!farEnds.IsEmpty()) {
                projections.Bind(firstShape(element), farEnds);
            }
        }
    }
    if (!upTo.IsNull()) {
        bindFarCaps(splitter, firstShape, profile, result, upTo);
    }
}

void UpToSplitMapper::bindFarCaps(
    BRepAlgoAPI_Splitter& splitter,
    const std::function<TopoDS_Shape(const TopoDS_Shape&)>& firstShape,
    const TopoDS_Shape& profile,
    const TopoDS_Shape& result,
    const TopoDS_Shape& upTo
)
{
    // The far caps (ops#360): for each face of the profile, in its order, the pieces of `upTo`
    // in the kept solids that start at the face's start cap, in `upTo`'s face order, a face of
    // `upTo` the split leaves whole included. A cap that spans several faces of `upTo`, or that a
    // hole in one cuts, has several pieces, each marked by what bounds it; pieces that meet only
    // along the seam of a face of `upTo` are one cap. A piece of the start cap is left out: where
    // the profile lies on `upTo`, the splitter makes the two one face
    const TopTools_IndexedMapOfShape upToPieces = piecesOf(splitter, upTo);
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
    // Marked once every far cap is known: a piece's marks depend on the other caps on its face
    if (!severalPieces.empty()) {
        markCaps(splitter, upTo, severalPieces);
    }
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

/// True if `a`'s centre comes before `b`'s along x, then y, then z, a difference within the
/// tolerance counting as none
bool comesBefore(const gp_Pnt& a, const gp_Pnt& b)
{
    constexpr double tie = 100 * Precision::Confusion();
    for (int k = 1; k <= 3; ++k) {
        const double difference = a.Coord(k) - b.Coord(k);
        if (std::abs(difference) > tie) {
            return difference < 0;
        }
    }
    return false;
}
}  // namespace

void UpToSplitMapper::markCaps(
    BRepAlgoAPI_Splitter& splitter,
    const TopoDS_Shape& upTo,
    const std::vector<TopTools_ListOfShape>& severalPieces
)
{
    // What each piece of `upTo` is a piece of: its face, or for an edge every edge of `upTo` it
    // lies on (a shell's faces that meet along a line each bring their edge)
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
    struct Piece
    {
        TopoDS_Shape cap;
        TopTools_IndexedMapOfShape faces;
        TopTools_IndexedMapOfShape upToEdges;
        TopTools_IndexedMapOfShape startEdges;
        TopTools_IndexedMapOfShape marks;
    };
    for (const TopTools_ListOfShape& caps : severalPieces) {
        std::vector<Piece> pieces;
        for (const TopoDS_Shape& cap : caps) {
            Piece piece;
            piece.cap = cap;
            if (const TopTools_ListOfShape* faces = sources.Seek(cap)) {
                for (const TopoDS_Shape& face : *faces) {
                    piece.faces.Add(face);
                }
            }
            TopTools_IndexedMapOfShape edges;
            TopExp::MapShapes(cap, TopAbs_EDGE, edges);
            for (int i = 1; i <= edges.Extent(); ++i) {
                if (const TopoDS_Shape* source = farSources.Seek(edges(i))) {
                    piece.startEdges.Add(*source);
                }
                if (const TopTools_ListOfShape* pieceOf = sources.Seek(edges(i))) {
                    for (const TopoDS_Shape& source : *pieceOf) {
                        piece.upToEdges.Add(source);
                    }
                }
            }
            pieces.push_back(std::move(piece));
        }
        // The marks (PR 340 round 2): the face of `upTo` a piece lies on, alone where it is the
        // only far cap there, so that a change of its bounds keeps its name; with the edges of
        // `upTo` that bound it where other caps lie on that face; with the start cap's edges
        // whose projections bound it among pieces those don't tell apart. A sketch edit that
        // splits or redraws a profile edge changes the marks only where they are needed
        for (Piece& piece : pieces) {
            bool alone = true;
            for (int i = 1; i <= piece.faces.Extent(); ++i) {
                piece.marks.Add(piece.faces(i));
                const int* count = capsOnFace.Seek(piece.faces(i));
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
            for (int k = 1; !told[i] && k <= pieces[i].startEdges.Extent(); ++k) {
                pieces[i].marks.Add(pieces[i].startEdges(k));
            }
            TopTools_ListOfShape list;
            for (int k = 1; k <= pieces[i].marks.Extent(); ++k) {
                list.Append(pieces[i].marks(k));
            }
            capMarks.Bind(pieces[i].cap, list);
        }
        // Pieces with the same marks still (a circle across an elliptic hole: the pieces on
        // either side are bounded by the circle and the ellipse alone) are told apart by the
        // duplicate counter, which the solver reads as "a sibling, never the element itself": a
        // reference that lands on another of them breaks instead of following it. The counter
        // holds how many share the marks, so that one going or coming renames them all, and
        // each one's place among them, by their centres, so that a change of the splitter's
        // order (the up-to face rebuilt with another parametrization) renames none
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
            std::vector<std::pair<gp_Pnt, std::size_t>> placed;
            for (std::size_t twin : twins) {
                GProp_GProps props;
                BRepGProp::SurfaceProperties(pieces[twin].cap, props);
                placed.emplace_back(props.CentreOfMass(), twin);
            }
            // Insertion sort: the tolerance makes the order no strict weak one
            for (std::size_t j = 1; j < placed.size(); ++j) {
                for (std::size_t k = j; k > 0 && comesBefore(placed[k].first, placed[k - 1].first);
                     --k) {
                    std::swap(placed[k], placed[k - 1]);
                }
            }
            const int count = static_cast<int>(placed.size());
            for (int position = 0; position < count; ++position) {
                // One number for the pair: count (count - 1) / 2 + position, 1 and 2 for two
                // pieces, 3 to 5 for three; 0 is a piece with marks of its own
                const int counter = count * (count - 1) / 2 + position;
                capCounters.Bind(pieces[placed[position].second].cap, counter);
            }
        }
    }
}

bool UpToSplitMapper::isFarCap(const TopoDS_Shape& shape) const
{
    return farCaps.Contains(shape);
}

int UpToSplitMapper::counterOf(const TopoDS_Shape& cap) const
{
    const int* counter = capCounters.Seek(cap);
    return counter ? *counter : 0;
}

std::vector<TopoDS_Shape> UpToSplitMapper::marksOf(const TopoDS_Shape& cap) const
{
    std::vector<TopoDS_Shape> marks;
    if (const TopTools_ListOfShape* found = capMarks.Seek(cap)) {
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
