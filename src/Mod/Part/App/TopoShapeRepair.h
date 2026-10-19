// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <Mod/Part/PartGlobal.h>

class TopoDS_Shape;

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
 * \a before is the shape as it was before the repair, names included. It must share no
 * sub-shapes with \a shape (make it with TopoShape::makeElementCopy()), since fix() changes them
 * in place; passing a shape that does, or \a shape itself, is undefined (the same object
 * asserts).
 *
 * @return fix()'s result: true if the shape was repaired.
 */
PartExport bool fixKeepingNames(TopoShape& shape, const TopoShape& before);

/// What checkDressUp() does with the base's faces, wires, edges and vertices outside its shells
enum class LooseParts
{
    keep,
    drop
};

/** Checks a fillet's or chamfer's result, which OCCT sometimes returns invalid without an error
 * (FreeCAD-CH, ops#297).
 *
 * A valid result passes as it is. An invalid one fails if it doesn't have the base's number of
 * solids (an overlong full round splits the solid in two, with 75 % more volume), and is otherwise
 * repaired on a copy with fixKeepingNames(). The repair is kept only if it has the base's number of
 * solids and, if the base is valid, the same number of faces with the same areas, face by face: a
 * repair may reorient faces and fix wires and tolerances, but one that changes the surface
 * (ShapeFix splitting the self-intersecting face of two overlapping fillets into more faces) would
 * be a valid, wrong solid. An invalid base passes its defects on to the result, and their repair
 * may remove faces and area (a fin), but not add any. A repair that moves faces out of the solids
 * of a solids-only result (ShapeFix putting a fin into an open shell beside the solid, whose
 * compound has the wrong volume) is cut down to its solids if the base is invalid and the faces
 * dropped don't enclose a volume, and fails otherwise. A result with faces outside its solids may
 * not have more of them after the repair. A failure is logged with its reason.
 *
 * OCCT also drops parts of the base it leaves alone (ops#303). A result that lost a closed shell of
 * the base's solids fails if the shell bounds material (a second outer shell, an invalid base), or
 * if it is a void whose space now holds material of the result (a chamfer cutting into it); a void
 * removed with its material stays removed. With LooseParts::keep, the base's faces, wires, edges
 * and vertices outside its shells are put back into the result, which then is a compound; a result
 * that has such parts of its own fails.
 *
 * @param shape The result; replaced by the repaired shape if the repair is kept, and holding the
 * base's loose parts if they are kept
 * @param base The shape that was dressed up
 * @param looseParts Whether the result keeps the base's loose parts: Part's features do,
 * PartDesign's keep solids and shells only, as OCCT returns them
 * @return false if the result is invalid and wasn't repaired: the feature must fail
 */
PartExport bool checkDressUp(
    TopoShape& shape,
    const TopoShape& base,
    LooseParts looseParts = LooseParts::keep
);

/** Whether faces outside the shape's solids enclose a volume, which checkDressUp() never drops: a
 * closed shell, or faces that close up among themselves (a sphere's face), each judged on its own,
 * so that an open face beside them doesn't hide them (FreeCAD-CH, ops#297).
 */
PartExport bool enclosesOutsideSolids(const TopoDS_Shape& shape);

}  // namespace Part
