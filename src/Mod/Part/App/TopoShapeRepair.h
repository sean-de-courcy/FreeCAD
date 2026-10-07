// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <Mod/Part/PartGlobal.h>

namespace Part
{

class TopoShape;

/** TopoShape::fix(), keeping the names of the elements the repair didn't change (FreeCAD-CH,
 * ops#168).
 *
 * fix() names its result through ShapeFix's history, which has no record of an element the repair
 * rebuilt as a new shape, so the generic passes name it anew from its neighbours (`MAK`), even
 * where nothing about it changed: a dress-up repaired at a tangency renamed every face of the
 * solid, and a reference to one went missing once the tangency went away. Here an element of the
 * result takes the names of the one element of the shape before the repair that matches it, and
 * that no other element of the result matches:
 * - the same type, geometry and vertices (TopoShape::findSubShapesWithSharedVertex()); or
 * - a face only: the same surface and area (the repair split one of its edges at a new vertex).
 *
 * Elements the repair changed keep their new names. V2 element maps only, as
 * TopoShape::appendElementSection(). For a feature that repairs its own result (PartDesign's
 * Fillet and Chamfer); TopoShape::makeElementWires() and the boolean maker's invalid inputs call
 * fix() as it is.
 *
 * @return fix()'s result: true if the shape was repaired.
 */
PartExport bool fixKeepingNames(TopoShape& shape);

}  // namespace Part
