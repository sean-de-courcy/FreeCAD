// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <Mod/Part/PartGlobal.h>

class BRepOffsetAPI_MakePipeShell;
class TopoDS_Wire;

/** A sweep's Frenet mode where OCCT's Frenet trihedron turns over (FreeCAD-CH, ops#421).
 *
 * OCCT's Frenet trihedron (GeomFill_Frenet) takes its normal towards the centre of curvature, so
 * where a spine edge's curvature passes through zero inside the edge (an inflection of a planar
 * wave), the normal and binormal turn over at once. MakePipeShell then builds a lateral face that
 * twists half a turn there: a circle profile's tube came out self-intersecting, still reported
 * valid, 1.3 to 1.9 mm off the tube, with volumes off by up to -58 % and, after a corner, edge
 * tolerances of 10 mm. An inflection at a vertex between two edges is harmless: OCCT makes the
 * edges' trihedrons agree there.
 *
 * A planar curve's Frenet frame doesn't turn about the tangent (its binormal is the plane's normal
 * wherever the curvature isn't zero, up to its sign), so on a planar spine the sweep there takes
 * corrected Frenet, the rotation-minimizing frame: Frenet's own, kept continuous through the
 * inflections. A spine that isn't planar has no such frame, and its sweep is refused. Spines where
 * the trihedron doesn't turn over keep OCCT's Frenet law, so their results don't change. */
namespace Part::SweepFrenet
{

/// Samples per knot span (or per edge, for a curve without spans) when looking for a turn-over
constexpr int samplesPerSpan = 8;
/// At least this many samples per edge
constexpr int minSamples = 64;
/// Halvings of an interval whose ends' normals are more than a right angle apart, before the
/// turn counts as a jump: 2^-40 of a sample interval, where a continuous turn has spread out
constexpr int bisections = 40;

/// Sets the trihedron mode of \a pipe, built on \a spine: corrected Frenet unless \a frenet, else
/// Frenet, or corrected Frenet on a planar spine where Frenet's trihedron turns over. Throws
/// Standard_Failure where it turns over on a spine that isn't planar.
PartExport void setMode(BRepOffsetAPI_MakePipeShell& pipe, const TopoDS_Wire& spine, bool frenet);

}  // namespace Part::SweepFrenet
