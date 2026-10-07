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
 * result takes the names of the element of the shape before the repair that it is, one to one
 * (checked from both sides: an element two others match is neither's):
 * - the same type, geometry and vertices (TopoShape::findSubShapesWithSharedVertex()); or
 * - for the faces left over: the same kind of surface, area and centre (the repair split one of
 *   its edges at a new vertex), within tolerances relative to the face's size.
 * A matched element keeps the repair's names where the names it would take are already another,
 * unmatched element's, and so does every element if renaming fails (with a warning).
 *
 * Elements the repair changed keep their new names. V2 element maps only, as
 * TopoShape::appendElementSection(). For a feature that repairs its own result (PartDesign's
 * Fillet and Chamfer); TopoShape::makeElementWires() and the boolean maker's invalid inputs call
 * fix() as it is.
 *
 * @return fix()'s result: true if the shape was repaired.
 */
PartExport bool fixKeepingNames(TopoShape& shape);

/** fixKeepingNames() for a caller that holds the shape as it was before the repair: \a before,
 * names included, sharing no sub-shapes with \a shape (TopoShape::makeElementCopy()), since
 * fix() changes them in place. It saves the copy the other overload makes.
 */
PartExport bool fixKeepingNames(TopoShape& shape, const TopoShape& before);

}  // namespace Part
