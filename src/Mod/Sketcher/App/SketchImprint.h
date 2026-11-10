// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Onshape's imprint (FreeCAD-CH, feat/profile-regions; notes/profile-regions.md): the model edges
// lying in a sketch's plane bound its regions without being projected one by one. They come from
// the objects the sketch is attached to (its links: the recompute orders them before the sketch),
// enter the arrangement of the sketch's regions (InternalShape) only, and never its geometry
// (Shape, the solver, the whole-sketch profile).

#include <Mod/Part/App/TopoShape.h>
#include <Mod/Sketcher/SketcherGlobal.h>

namespace Sketcher
{

class SketchObject;

/// The first value of SketchObject::_InternalFaceVersion whose regions take the imprint: new
/// sketches have it; sketches saved before keep their regions as they were
constexpr int ImprintInternalFaceVersion = 3;

/// The edges of faces of the sketch's attachment support objects (datums, origin features and
/// other sketches left out) that lie in the sketch's plane, as copies in the sketch's own
/// coordinates, named after the model's edges. Null when there are none, when the sketch's
/// regions predate the imprint, or when it makes no regions (MakeInternals off).
SketcherExport Part::TopoShape imprintEdges(const SketchObject& sketch);

}  // namespace Sketcher
