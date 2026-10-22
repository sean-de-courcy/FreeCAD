// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <vector>

#include <Mod/Part/PartGlobal.h>

class BRepOffsetAPI_MakePipeShell;
class TopoDS_Shape;
class TopoDS_Wire;

/** A sweep's Frenet mode where OCCT's Frenet trihedron turns over (FreeCAD-CH, ops#421).
 *
 * OCCT's Frenet trihedron (GeomFill_Frenet) takes its normal towards the centre of curvature, so
 * where a spine edge's curvature passes through zero inside the edge (an inflection of a planar
 * wave), the normal and binormal turn over at once. MakePipeShell then builds a lateral face that
 * twists half a turn there: a circle profile's tube came out self-intersecting, still reported
 * valid, 1.3 to 1.9 mm off the tube, with volumes off by up to -58 % and, after a corner, edge
 * tolerances of 10 mm. Where the curvature only comes close to zero (a wave lifted out of its
 * plane), the frame turns half a turn within micrometres instead: a circle's tube can come out
 * right or 1.8 mm off, and any other profile folds. An inflection at a vertex between two edges is
 * harmless: OCCT makes the edges' trihedrons agree there.
 *
 * Where neighbouring samples' normals point more than a right angle apart:
 * - on a planar spine, corrected Frenet: a planar curve's Frenet frame doesn't turn about the
 *   tangent, so the rotation-minimizing frame is Frenet's own, kept continuous;
 * - on a spine planar within a thousandth of its size whose tangent stays close enough to the
 *   plane that no section tilts out of tolerance, the plane's normal as a constant binormal
 *   (corrected Frenet failed there, where this built the tube), refused after the build if its
 *   tolerances come out far above the pipe's;
 * - otherwise corrected Frenet if every section is round about the spine (the same surface in any
 *   frame), and a refusal if not.
 * Spines where the trihedron doesn't turn over keep OCCT's Frenet law, so their results don't
 * change. */
namespace Part::SweepFrenet
{

/// Samples per knot span (or per edge, for a curve without spans) when looking for a turn-over
constexpr int samplesPerSpan = 8;
/// At least this many samples per edge
constexpr int minSamples = 64;
/// A sample's normal counts only where the curvature times the edge's length is above this
constexpr double curvatureFloor = 1e-9;
/// A plane near the spine is looked for within this fraction of its bounding box's diagonal (lifts
/// of 5 um on a 60 mm wave are within it); whether its normal can be the binormal depends on how
/// far the tangent leaves it
constexpr double relativePlanarity = 1e-3;
/// With the plane's normal as binormal, vertex or edge tolerances above this many times the
/// pipe's 3D tolerance are refused: the binormal left vertices of 0.15 mm on ten waves lifted by
/// 75 nm, and up to 1.3e-4 where it built the tube; macOS's tolerances came out 16 times Windows'
/// on the corner spine
constexpr double maxToleranceRatio = 100;

/// The trihedron mode setMode() chose
enum class Mode
{
    /// The one asked for: OCCT's Frenet law, or corrected Frenet
    Asked,
    /// Corrected Frenet in place of Frenet
    CorrectedFrenet,
    /// The plane's normal as a constant binormal in place of Frenet
    PlaneNormal,
};

/// Sets the trihedron mode of \a pipe, built on \a spine for \a sections (wires or vertices):
/// corrected Frenet unless \a frenet, else Frenet, or the mode above where Frenet's trihedron
/// turns over. \a tolerance is the pipe's 3D tolerance. Throws Standard_Failure where it turns
/// over on a spine that isn't planar and a section isn't round about the spine.
PartExport Mode setMode(
    BRepOffsetAPI_MakePipeShell& pipe,
    const TopoDS_Wire& spine,
    const std::vector<TopoDS_Shape>& sections,
    bool frenet,
    double tolerance
);

/// Checks the pipe \a built after Build() in the \a mode setMode() chose: throws Standard_Failure
/// where that is the plane's normal and a vertex's or edge's tolerance is above maxToleranceRatio
/// times \a tolerance, the pipe's 3D tolerance
PartExport void checkBuilt(const TopoDS_Shape& built, Mode mode, double tolerance);

}  // namespace Part::SweepFrenet
