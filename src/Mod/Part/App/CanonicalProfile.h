// SPDX-License-Identifier: LGPL-2.1-or-later

/** Canonical curves on a profile before a sweep (ops#640, FreeCAD-CH).
 *
 * OCCT's prism and revolution build an analytic face only from an analytic curve: it reads the
 * curve's class, never its shape. A profile edge that is a B-spline or Bezier curve lying on a line
 * or a circle (a trace of an earlier spline blend, an approximated or converted arc) sweeps into a
 * surface of extrusion or revolution where Onshape has a plane, cylinder, cone or torus, and every
 * later step that reads the face by class (dress-ups, refine, OCCT's closed-form fillets) misses it.
 *
 * canonicalProfile() gives such an edge its line or circle before the sweep, so OCCT builds the
 * analytic face itself. The contract:
 * - Recognition is OCCT's own (GeomConvert_CurveToAnaCurve, line then circle) at kTolerance.
 *   An edge it doesn't recognise, an edge on a face that is not a plane, and, for a revolution,
 *   a circle whose centre is within its radius of the axis (a horn or spindle torus, which OCCT
 *   refuses by rule) are left as they are: today's path.
 * - A recognised edge must pass an independent check (checkCanonicalEdge()): the old curve within
 *   kTolerance of the new one at every sample, the same ends and the same sense. The result must be
 *   valid, with the same sub-shapes in the same order (so the profile keeps its names). A failed
 *   check throws: never a silent different profile.
 */

#ifndef PART_CANONICALPROFILE_H
#define PART_CANONICALPROFILE_H

#include <Geom_Curve.hxx>
#include <gp_Ax1.hxx>

#include <Mod/Part/PartGlobal.h>

namespace Part
{
class TopoShape;

/// How far a profile edge may be from its line or circle (and the check's bound)
constexpr double kCanonicalProfileTolerance = 1e-7;

/** Replaces the profile's spline edges that are lines or circles by those curves, in place,
 * keeping the element map (same sub-shapes, same order). `revolveAxis`: the axis of the
 * revolution the profile is for, or null for a prism. Throws Base::CADKernelError when a
 * recognised edge fails the check. Returns the number of edges converted. */
PartExport int canonicalProfile(TopoShape& profile, const gp_Ax1* revolveAxis = nullptr);

/** The check of one conversion: `newCurve` on [newFirst, newLast] traces `oldCurve` on
 * [first, last] within `tolerance`, from the same start to the same end in the same sense.
 * Throws Base::CADKernelError naming the largest deviation when it doesn't. */
PartExport void checkCanonicalEdge(
    const Handle(Geom_Curve) & oldCurve,
    double first,
    double last,
    const Handle(Geom_Curve) & newCurve,
    double newFirst,
    double newLast,
    double tolerance = kCanonicalProfileTolerance
);

}  // namespace Part

#endif  // PART_CANONICALPROFILE_H
