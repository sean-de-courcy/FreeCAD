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
 * harmless: OCCT makes the edges' trihedrons agree there. Along a straight stretch inside an edge
 * (a B-spline span with collinear poles) Frenet's frame isn't defined, and OCCT's takes a normal
 * of its own there: turned over from the curve's on both sides of the stretch, the rectangle
 * beside a planar spine turned over and back; 26.6 to 90 degrees from the curve's where it bends
 * next, the frame jumps there, and a circle's tube came out 2.4e-2 to 0.28 mm off (ops#465,
 * ops#439).
 *
 * Where the frame turns by more than a right angle about the tangent between nearby samples and
 * the curvature dips there, or the normal reverses at a knot where the curve is only C1 (a steep
 * helix's frame turns about the tangent all along, with its curvature steady; where the samples
 * are too far apart to follow such a twist, the edge is sampled again more densely), or where
 * OCCT's frame turns by more than a right angle among samples without a frame of their own (the
 * curvature at the floor), or jumps by more than jumpCosine's angle where a straight stretch
 * ends:
 * - on a planar spine, corrected Frenet: a planar curve's Frenet frame doesn't turn about the
 *   tangent, so the rotation-minimizing frame is Frenet's own, kept continuous;
 * - on a spine planar within a thousandth of its size whose tangent stays close enough to the
 *   plane that no section tilts out of tolerance, and whose Frenet binormal stays close to the
 *   plane's normal, the plane's normal as a constant binormal (corrected Frenet failed there, where
 *   this built the tube);
 * - otherwise corrected Frenet if every section is round about the spine (the same surface in any
 *   frame), and a refusal if not.
 * With the plane's normal, checkBuilt() refuses the result where its tolerances come out far above
 * the pipe's.
 * Spines where the trihedron doesn't turn over or jump keep OCCT's Frenet law, so their results
 * don't change. */
namespace Part::SweepFrenet
{

/// Samples per knot span (or per edge, for a curve without spans) when looking for a turn-over
constexpr int samplesPerSpan = 8;
/// At least this many samples per edge
constexpr int minSamples = 64;
/// A sample's normal counts only where the curvature times the edge's length is above this
constexpr double curvatureFloor = 1e-9;
/// A point is on a straight stretch, where Frenet's frame isn't defined and OCCT's takes a normal
/// of its own, where the curvature times the edge's length is at most this. OCCT's frame was the
/// curve's at 3.75e-12 (y = 1e-8 x^3 near its inflection); on spans with collinear poles the
/// curvature came out 0
constexpr double straightFloor = 1e-12;
/// Among samples without a frame, OCCT's frame is read this fraction of the edge's parameter range
/// from each, towards the middle of their run: at a flat point it was a quarter turn off at the
/// point and 1e-12 from it, and the curve's own 1e-9 from it (fork PR 358 round 1, R1)
constexpr double runOffset = 1e-6;
/// OCCT's frame on a straight stretch is read at the middles of this many even parts of it
constexpr int stretchPoints = 8;
/// The cosine of 1 degree: OCCT's frame on a straight stretch, against the curve's where it bends
/// next, counts as a jump where they are further apart. Where OCCT kept the normal from before the
/// stretch, they were 1e-7 degrees apart; elsewhere 26.6, 63.4, 90 or 180 degrees (ops#439,
/// ops#465)
constexpr double jumpCosine = 0.9998476951563913;
/// A sample interval across which the tangent turns by more than 45 degrees is halved, at most this
/// many times (a helix sampled 6.4 times a turn, as Part.makeHelix's curves were before ops#447:
/// its tangent turns 56 degrees between samples)
constexpr int maxHalvings = 6;
/// A turn of the frame counts as a turn-over only where the curvature dips: its lowest value
/// between the samples is at most this fraction of the median over the samples on either side.
/// Inflections and narrow turns measured 0 to 0.26 (0.29 at worst where an inflection's sample is
/// skipped); helices, conical ones included, and a makeHelix knot where the frame jumped by 47
/// degrees (until ops#447): 0.74 to 1
constexpr double curvatureDip = 0.5;
/// The medians of curvatureDip are taken over this many counted samples on either side
constexpr int curvatureWindow = 4;
/// The lowest curvature between two samples is also looked for at this many even steps: an S-curve
/// interpolated through 300 points crossed zero between two samples with 0.0714 and 0.0585 on
/// either side, against a median of 0.0503 after them
constexpr int curvatureRefinement = 32;
/// The point where the frame turns over between two samples is found by this many halvings, and
/// the curvature there counts towards the lowest: an inflection within a 64th of a sample interval
/// from an edge's end sample has that sample as the nearest of the even steps
constexpr int turnBisections = 50;
/// The cosine of 30 degrees: where the frame's median turn about the tangent between neighbouring
/// samples is larger, the samples are too far apart to tell a twist from a turn-over (a
/// Part.makeHelix helix with a pitch of 6 times its radius: 41 to 56 degrees, two apart 92 to 112)
/// and the edge is sampled again twice as densely
constexpr double steadyTwistCosine = 0.8660254037844386;
/// At most this many doublings of an edge's samples for a steady twist (16 times the samples)
constexpr int maxDoublings = 4;
/// The cosine of 30 degrees: the plane's normal is taken as Frenet's binormal where it is within
/// this angle of it at all but binormalOffShare of the samples
constexpr double binormalCosine = 0.8660254037844386;
/// See binormalCosine
constexpr double binormalOffShare = 0.1;
/// A plane near the spine is looked for within this fraction of its bounding box's diagonal (lifts
/// of 5 um on a 60 mm wave are within it); whether its normal can be the binormal depends on how
/// far the tangent leaves it
constexpr double relativePlanarity = 1e-3;
/// With the plane's normal as binormal in place of Frenet, vertex or edge tolerances above this
/// many times the pipe's 3D tolerance are refused: the binormal left vertices of 0.15 mm on ten
/// waves lifted by 75 nm, and up to 1.3e-4 where it built the tube; macOS's tolerances came out 16
/// times Windows' on the corner spine (1.6e-3), and results passing at 100 were within 4.7e-4 of
/// the tube
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
/// turns over or jumps. \a tolerance is the pipe's 3D tolerance. Throws Standard_Failure where it
/// does on a spine that isn't planar and a section isn't round about the spine.
PartExport Mode setMode(
    BRepOffsetAPI_MakePipeShell& pipe,
    const TopoDS_Wire& spine,
    const std::vector<TopoDS_Shape>& sections,
    bool frenet,
    double tolerance
);

/// Checks the pipe \a built after Build() in the \a mode setMode() chose: throws Standard_Failure
/// where that is the plane's normal and a vertex's or edge's tolerance is above maxToleranceRatio
/// times \a tolerance, the pipe's 3D tolerance. Corrected Frenet is what Frenet off sweeps, so
/// its results are left to the loose-result warning, as Frenet off's (ops#465: correct tilted
/// waves were refused for vertex tolerances of 0.010 to 0.020 mm, OCCT's estimate, the tube
/// within 1.7e-6)
PartExport void checkBuilt(const TopoDS_Shape& built, Mode mode, double tolerance);

}  // namespace Part::SweepFrenet
