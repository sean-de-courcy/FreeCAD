// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Onshape's imprint (FreeCAD-CH, feat/profile-regions; notes/profile-regions.md): the model edges
// lying in a sketch's plane bound its regions without being projected one by one. They come from
// the objects the sketch is attached to (its links: the recompute orders them before the sketch),
// enter the arrangement of the sketch's regions (InternalShape) only, and never its geometry
// (Shape, the solver, the whole-sketch profile).

#include <string>
#include <vector>

#include <Mod/Part/App/TopoShape.h>
#include <Mod/Sketcher/SketcherGlobal.h>

namespace Sketcher
{

class SketchObject;

/// The first value of SketchObject::_InternalFaceVersion whose regions take the imprint: new
/// sketches have it; sketches saved before keep their regions as they were
constexpr int ImprintInternalFaceVersion = 3;

/// The edges of the faces the sketch is attached to (AttachmentSupport's faces of model objects:
/// datums, origin features and other sketches left out) when they lie in the sketch's plane, as
/// copies in the sketch's own coordinates, named after the model's edges. Null when there are
/// none, when the sketch's regions predate the imprint, when it makes no regions (MakeInternals
/// off), or when DisableImprinting is on. Only that face's edges: another face's or another part's coplanar edges don't split the
/// sketch's regions, nor does a face under a sketch on a plane (Onshape, notes/onshape-facts.md R4).
SketcherExport Part::TopoShape imprintEdges(const SketchObject& sketch);

/// Whether imprintEdges() has an edge, without copying any
SketcherExport bool hasImprint(const SketchObject& sketch);

/** The imprint's edges that can reach the sketch's regions (perf profile 2b, ops#640: a sketch on a
 * face with thousands of edges made and checked every cell of the face's arrangement, then dropped
 * all but its own): the edges, in the imprint's order, of every group whose box meets the box of
 * the sketch's edges. A group is the edges joined by overlapping boxes, a superset of those joined
 * at a vertex or a crossing, so a loop of model edges is kept or left out whole and the arrangement
 * keeps the cells of the sketch's regions as they were. \a leftOutLoop: a group left out holds a
 * closed loop, which would have made a cell of its own (withinSketchRegions() then returns a new
 * compound, as it does when it drops one). All the edges where the sketch has none, or with
 * `FREECAD_CH_IMPRINT_NEAR=off`.
 */
SketcherExport std::vector<Part::TopoShape> nearImprintEdges(
    const Part::TopoShape& imprint,
    const Part::TopoShape& sketchEdges,
    bool& leftOutLoop
);

/// FREECAD_CH_IMPRINT_NEAR: "off" (every imprint edge), "verify" (both ways, an error where the
/// regions differ) or empty
SketcherExport std::string imprintNearMode();

/// Where two arrangements of regions differ (their BRep text, or an element's name), or empty
SketcherExport std::string regionsDifference(const Part::TopoShape& a, const Part::TopoShape& b);

/// The faces of an arrangement of a sketch's curves and its imprint edges that lie in the
/// regions of the sketch's curves alone: model edges split the sketch's regions and never make one
/// of their own (Onshape, R4 and R5). sketchEdges: the sketch's own wires, in the arrangement's
/// coordinates. Returns arrangement itself when every face is kept, unless \a rebuild (a cell of
/// model edges alone was left out before the arrangement: nearImprintEdges()).
SketcherExport Part::TopoShape withinSketchRegions(
    const Part::TopoShape& arrangement,
    const Part::TopoShape& sketchEdges,
    bool rebuild = false
);

}  // namespace Sketcher
