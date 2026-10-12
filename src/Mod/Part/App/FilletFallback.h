// SPDX-License-Identifier: LGPL-2.1-or-later

/** The exact construction of fillets and chamfers that OCCT's ChFi3d refuses (ops#295, ops#300).
 *
 * OCCT fails, cleanly, whenever a fillet's or chamfer's new boundary edge would land exactly on an
 * existing edge, so that an adjacent face shrinks to zero width (a full round, a chamfer to an
 * edge). This unit builds those dress-ups as exact Booleans: per selected edge, the exact section
 * (two lines and a circular arc, or a triangle) is swept along the edge (a prism along a straight
 * edge between planes; a revolution about the axis of a circle between a plane and a coaxial
 * cylinder), bounded at the edge's ends, cut from the base (convex edge) or fused to it (concave
 * edge). The result is verified (valid, one solid, no zero-area face, every volume equal to its
 * closed form) and named through a composed history, as if the fillet had built it.
 *
 * TopoShape::makeElementFillet / makeElementChamfer try it only after OCCT has failed. Whenever
 * a configuration is outside the scope or a check fails, build() refuses and the caller raises
 * OCCT's original error: never a silent wrong solid.
 *
 * Design: notes/fillet-workarounds.md in the ops repository, sections 2a, 3, 4 and 5.6.
 */

#ifndef PART_FILLETFALLBACK_H
#define PART_FILLETFALLBACK_H

#include <string>
#include <vector>

#include <TopoDS_Shape.hxx>
#include <gp_Pnt.hxx>
#include <gp_Dir.hxx>

#include <Mod/Part/PartGlobal.h>
#include "TopoShape.h"

namespace Part::FilletFallback
{

enum class Kind
{
    Fillet,
    Chamfer
};

/// What the caller asked for, as passed to makeElementFillet / makeElementChamfer
struct Request
{
    Kind kind = Kind::Fillet;
    /// Fillet: the radius at both ends. Chamfer: the distance on the reference face
    double size1 = 0.0;
    /// Fillet: the end radius (variable radius is refused). Chamfer: the second distance, or
    /// the angle in degrees for ChamferType::distanceAngle
    double size2 = 0.0;
    ChamferType chamferType = ChamferType::equalDistance;
    Flip flipDirection = Flip::none;
};

/** How a selected edge ends at one of its vertices (5.6, interface point 1).
 *
 * S1 builds free ends and tangent continuations; the corner kinds are refused with their own
 * reason until the corner construction (S1c) handles them.
 */
enum class VertexClass
{
    /// No other selected edge at the vertex: the tool is bounded by the end face's plane
    FreeEnd,
    /// A selected edge continues this one tangentially: the two tools meet on the plane
    /// normal to the common tangent
    TangentContinuation,
    /// One other selected edge meets this one at an angle (a two-edge corner)
    Corner2,
    /// All three edges at the vertex are selected (a three-edge corner)
    Corner3,
    /// Outside the scope
    Refuse
};

/// A plane that bounds a tool: the tool keeps the side opposite to the normal
struct TrimPlane
{
    gp_Pnt point;
    gp_Dir normal;
};

/** One piece of material removed (cut) or added (fused) (5.6, interface point 2).
 *
 * The tools of one dress-up are interior-disjoint (interface point 7), so the volume of the
 * result must equal the base's minus the cut tools' closed-form volumes plus the fused ones'.
 */
struct Tool
{
    TopoDS_Shape solid;
    /// Cut from the base (a convex edge) or fused to it (a concave edge)
    bool cut = true;
    /// The selected edge (or, for corner pieces, the vertex) whose fillet the tool's faces are
    /// named after
    TopoDS_Shape source;
    /// The tool's volume in closed form, not measured
    double volume = 0.0;
    /// The faces of the tool that lie on the faces adjacent to the edge: the result must not
    /// keep any part of them (each tangent strip must be backed by material, or by air)
    std::vector<TopoDS_Shape> contactFaces;
    /// The planes that bound the tool at the edge's free ends: a face of the tool left in such
    /// a plane is merged into the base's coplanar face (interface point 4)
    std::vector<TrimPlane> caps;
};

/** Builds the dress-up by the exact construction.
 *
 * @param result Receives the shape and its element map (named with op, as through the fillet's
 *               own history) when the construction succeeds; untouched otherwise
 * @param base The shape being dressed up: one solid
 * @param edges The selected edges of the base
 * @param request The kind and sizes
 * @param op The op code to name with (Part::OpCodes::Fillet / Chamfer)
 * @param reason If not null, receives why the construction refused
 * @return Whether it succeeded and passed every check
 */
PartExport bool build(
    TopoShape& result,
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const Request& request,
    const char* op,
    std::string* reason = nullptr
);

}  // namespace Part::FilletFallback

#endif  // PART_FILLETFALLBACK_H
