// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <map>

#include <Mod/Part/PartGlobal.h>

class TopoDS_Shape;

namespace Part
{

class TopoShape;

/** Element ids of a result without history, by a verified match against the result it replaces
 * (MLN, FreeCAD-CH, ops#502; the design: the ops repo's `notes/naming-class-C.md` sections 1.2 and
 * 2, invariant I-C1).
 *
 * A history-less result (a primitive, a Python feature's shape, a script shape) has no element
 * map: its consumers named its elements by index, and an index means another element whenever the
 * producer's topology order changes. Here each element of the new result takes the id of an
 * element of the old one by the first of these rungs that holds, one to one from both sides (an
 * old element two new ones match is neither's, and the reverse), and a fresh id otherwise:
 * 1. a vertex at the identical place; it anchors rung 2 only when corroborated (an edge joins it
 *    to another such vertex, as before);
 * 2. a vertex whose matched neighbours are exactly an old vertex's: the same degree, unmatched
 *    neighbours and faces, each edge from a matched neighbour keeping its direction, and a run of
 *    unmatched neighbours of the same size between the same anchors, matched all or nothing;
 *    iterated, at most maxVertexPasses times;
 * 3. a face whose vertices all matched and bound exactly one old face; an edge whose vertices
 *    matched and bound exactly one old edge of the same curve kind (its midpoint telling two
 *    apart); then a face of the same surface with its vertices at the old face's places;
 * 4. a face whose inner point lies on an old face whose inner point lies on it, neither holding
 *    another face's inner point, and whose old and new pieces (solid, else shell, else face) a
 *    match of rungs 1-3 links;
 * 5. an edge of a matched face lying within one edge of the old face (the same curve kind, its
 *    midpoint and vertices on it), which holds no other edge of the face;
 * 6. with \a fixedOrder (a primitive, whose builder is deterministic for a topology): every element
 *    by index, when the counts, the vertices of each edge and the edges of each face are the same
 *    under the index map and every face keeps its surface kind and side.
 * Every face match compares the surface kind and the oriented normals at the inner points (dot >
 * 0). Rung 6 is the only one that matches by position. Matches are by index from 1.
 */
struct PartExport ElementMatches
{
    std::map<int, int> vertexes;
    std::map<int, int> edges;
    std::map<int, int> faces;
    /// Whether rung 6 matched every element
    bool byIndex = false;
};

/// The rung-2 passes after which the vertices left unmatched take fresh ids
constexpr int maxVertexPasses = 64;

/** The elements of \a after that are elements of \a before (see ElementMatches), compared in
 * their own frames: their locations are left out.
 */
PartExport ElementMatches matchElements(
    const TopoDS_Shape& before,
    const TopoDS_Shape& after,
    bool fixedOrder
);

/// The op code of a name given by nameByMatch()
constexpr const char* matchOpCode = "MLN";

/** The id nameByMatch() gave the element \a element of \a shape, or 0 if it has none.
 * @param element e.g. "Face3"
 */
PartExport long matchedId(const TopoShape& shape, const char* element);

/** Names every element of \a shape, a result without an element map, by its id: the id of the
 * element of \a previous it matches (matchElements()), or a fresh one from \a counter, which only
 * grows. If \a previous carries no ids (null, unnamed, or named otherwise), every element takes a
 * fresh id, in index order. A name is one section `_;_;<tag>;MLN;<id>;<type>;0;_;_` (no IDX flag:
 * the match was verified), with \a tag the shape's new Tag. \a counter is raised past every id of
 * \a previous too.
 */
PartExport void nameByMatch(
    TopoShape& shape,
    const TopoShape& previous,
    long tag,
    long& counter,
    bool fixedOrder
);

}  // namespace Part
