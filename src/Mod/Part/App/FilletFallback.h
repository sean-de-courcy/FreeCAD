// SPDX-License-Identifier: LGPL-2.1-or-later

/** The exact construction of fillets and chamfers that OCCT's ChFi3d refuses (ops#295, ops#300).
 *
 * OCCT fails, cleanly, whenever a fillet's or chamfer's new boundary edge would land exactly on an
 * existing edge, so that an adjacent face shrinks to zero width (a full round, a chamfer to an
 * edge). This unit builds those dress-ups as exact Booleans: per selected edge, the exact section
 * (two lines and a circular arc, or a triangle) is swept along the edge (a prism along a straight
 * edge between planes; a revolution about the axis of a circle between a plane and a coaxial
 * cylinder), bounded at the edge's ends, cut from the base (convex edge) or fused to it (concave
 * edge). It is verified (at the limit; each tangent strip on its face and none overlapping; the
 * ends covered by the end faces; OCCT's contour no longer than the selection; valid, one solid, no
 * zero-area face, every volume equal to its closed form) and named through a composed history,
 * as if the fillet had built it.
 *
 * TopoShape::makeElementFillet / makeElementChamfer try it only after OCCT has failed, has built
 * an invalid result without an error (ops#297), or has left a face of zero width (thinFace(),
 * ops#298), and, for a fillet with a reflex corner with a circle (reflexCircleCorner(), ops#640),
 * where OCCT's valid result is not Onshape's: there the fillet fails if the construction refuses.
 * Whenever a configuration is outside the scope or a check fails, build() refuses and
 * the caller raises OCCT's original error or one for the thin face, or returns OCCT's invalid
 * result for the feature's check (Part::checkDressUp()): never a silent wrong solid.
 *
 * Design: notes/fillet-workarounds.md in the ops repository, sections 2a, 3, 4 and 5.6.
 */

#ifndef PART_FILLETFALLBACK_H
#define PART_FILLETFALLBACK_H

#include <algorithm>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <TopoDS_Face.hxx>
#include <TopTools_DataMapOfShapeReal.hxx>

#include <Mod/Part/PartGlobal.h>
#include "TopoShape.h"

namespace Part
{
struct ShapeMapper;
}

namespace Part::FilletFallback
{

enum class Kind
{
    Fillet,
    Chamfer
};

/** Where a chamfer by equal distances along a closed edge whose faces' angle varies takes its width
 * (notes/chamfer-varying-angle-942.md section 4; PartDesign::Chamfer's WidthAt, by its index).
 * The chamfer is one ball's (both faces offset by one distance d) and d = w tan(a / 2), a the angle
 * between the faces on the ball's side at the reference station: the narrowest angle (the width
 * is the chamfer's longest leg), the widest (its shortest), or the station of a reference point.
 */
enum class WidthAt
{
    narrowest,
    widest,
    atPoint
};

/// The width rule of one chamfer, as PartDesign::Chamfer passes it (ChamferWidthScope)
struct ChamferWidth
{
    WidthAt at = WidthAt::narrowest;
    /// WidthAt::atPoint: one point per picked edge, in the base shape's coordinates
    std::vector<gp_Pnt> points;
};

/** Sets, for its own life, the width rule makeElementChamfer reads on this thread
 * (chamferWidth()): PartDesign::Chamfer's WidthAt and WidthPoints, without a change to
 * makeElementChamfer's signature. Scopes nest; the outer one's rule comes back at the end.
 */
class PartExport ChamferWidthScope
{
public:
    explicit ChamferWidthScope(ChamferWidth width);
    ~ChamferWidthScope();
    ChamferWidthScope(const ChamferWidthScope&) = delete;
    ChamferWidthScope& operator=(const ChamferWidthScope&) = delete;

private:
    ChamferWidth previous;
};

/// The width rule set on this thread (ChamferWidthScope): the narrowest angle outside any scope
PartExport const ChamferWidth& chamferWidth();

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
    /// The edges of OCCT's contours, as the maker reports them after Add(): every one must be
    /// selected, or OCCT would have run the dress-up on along a tangent chain. Empty: not checked
    std::vector<TopoDS_Shape> contour;
    /// Build only at the limit, where a new edge lands on an existing one or a face vanishes:
    /// the failures the construction is for. Off only to compare with OCCT below the limit
    bool limitOnly = true;
    /// Each base face's largest tolerance, with its edges and vertices (faceTolerances()), taken
    /// before OCCT's maker ran: the maker raises the base's tolerances in place (to 1e-4 where a
    /// round ends against a wall), and the check for merged faces compares with these. Empty:
    /// read from the base when the construction runs
    TopTools_DataMapOfShapeReal faceTolerances;
    /// ChamferType::equalDistance: each edge's setback on both faces, in the order of the edges
    /// passed in (chainSetbacks()). Empty: size1 on every edge
    std::vector<double> setbacks;
    /// The scope that builds only what OCCT refuses (ops#888): set by the dress-up only where OCCT
    /// failed or left a face of zero width, so that nothing OCCT builds today, valid or not, moves.
    /// It lets an arc's tool run on past an end plane that does not contain its axis
    bool widerScope = false;
    /// A chamfer's or round's tool may run off both its faces (ops#888 A1: a dress-up wider than a
    /// rail's top and taller than its wall; Onshape's DU1, DU4), where each run-off is one the
    /// construction resolves and one of them runs into a wall that trims the tool. Set by the
    /// caller only where OCCT failed or left a face of zero width, so that nothing OCCT builds
    /// changes
    bool pastBothFaces = false;
    /// The fillet's mitre corners only (ops#941, notes/fillet-corner-mitre-941.md section 4): no
    /// rim route and no route under an overhang, the strips checked below the limit too, and a
    /// refusal before any Boolean unless every selected edge ends at two corners of
    /// mitreCircleCorner() (closed loops of that corner kind)
    bool mitreOnly = false;
    /// A chamfer by equal distances whose every edge is a closed contour of its own, one of them
    /// of varying angle (variesAlongLoneEdge()): the construction takes a closed ellipse between
    /// a plane and a cylinder (ops#942). Set by makeElementChamfer only for the construction it
    /// runs before OCCT; every other caller of the analysis keeps today's refusal there
    bool varyingAngle = false;
    /// Where such a chamfer takes its width (WidthAt; ChamferWidth::points for atPoint)
    WidthAt widthAt = WidthAt::narrowest;
    std::vector<gp_Pnt> widthPoints;
};

/// Each face's largest tolerance, with its edges and vertices: Request::faceTolerances
PartExport TopTools_DataMapOfShapeReal faceTolerances(const TopoDS_Shape& shape);

/** A copy of a dress-up's base for OCCT's fillet or chamfer maker, which raises its input's
 * tolerances in place (to 1e-4 at the vertices where a round or chamfer ends against a wall): the
 * base shares its TShapes with the base feature's stored Shape, which would keep them (ops#345).
 * The copy has new TShapes with the base's tolerances, shares its geometry, and keeps its element
 * map and Tag, so the result is named as from the base. The result's own sub-shapes keep what the
 * maker raised.
 *
 * @param base The shape being dressed up
 * @param edges The selected edges of the base: replaced by the same edges of the copy, in order
 * @return The copy, for the maker and the exact construction
 */
PartExport TopoShape makerInput(const TopoShape& base, std::vector<TopoShape>& edges);

/** The setbacks of a chamfer by equal distances, as Onshape's (notes/chamfer-chain-setbacks.md,
 * oracle 14 CT1-CT3): the chamfer's edges that meet at vertices form a chain; the chain's first
 * edge in the list gets the width, and every other edge of it gets
 * s = width tan(a1 / 2) / tan(a / 2), a the edge's wedge angle between its faces, a1 the first
 * edge's: the chords of one rolling ball. Exactly the width where the angles are equal (to 1e-9).
 *
 * The edges are OCCT's contours after Add() (tangent propagation included), read from a maker
 * that is never built; contours that share a vertex form a chain. A chain keeps the width on every
 * edge where an angle varies along a contour, a contour's edges have different angles, convex and
 * concave edges mix, or a setback isn't finite. A concave chain takes the air-side angle.
 *
 * @param input The shape the chamfer is made on (the makerInput() copy)
 * @param edges The listed edges of input, in the dress-up's order
 * @param width The chamfer's distance
 * @return One setback per listed edge, in order
 */
PartExport std::vector<double> chainSetbacks(
    const TopoShape& input,
    const std::vector<TopoShape>& edges,
    double width
);

/** Copies of the shapes handed to one OCCT maker that raises its inputs' tolerances in place, as
 * makerInput() makes the base's: BRepFeat up to a face raises the face's edges and vertices and
 * the base's where the prism meets them (ops#347). The copies are made together, so a sub-shape
 * the shapes share (an up-to face of the base, the faces of a shell of the base's faces) is one
 * sub-shape of the copies too. Each copy keeps its shape's element map and Tag.
 *
 * Used by Pad and Pocket up to a face, the first or last face or a shape
 * (TopoShape::makeElementPrismUntil(): the base, the profile, the support face, the up-to shape)
 * and by Revolution and Groove up to a face (FeatureRevolved: the base, the chosen faces and the
 * profile).
 * Pad and Pocket make their fuse or cut with the original base: the contact with the prism is
 * found by geometry, not by shared TShapes. Revolution and Groove make theirs with the base's
 * copy, whose faces are the ones their tool's face parts share.
 *
 * @param shapes The maker's inputs; a null one stays null
 * @return The copies, in the order of the shapes
 */
PartExport std::vector<TopoShape> makerInputs(const std::vector<TopoShape>& shapes);

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

/** Whether the selection has a reflex corner with a circle (fillet-tight-arc 8, FSLC #50): a
 * vertex where exactly two selected edges meet, at least one of them a circle, the third edge
 * unselected, and each selected edge leaves the vertex towards the outer side of the other's wall
 * (the outline is reflex there). OCCT's round there can be valid and still wrong (a patch, or a
 * misplaced mitre with a ring torus), so makeElementFillet asks the exact construction, and fails
 * where it refuses. corner, if not null, receives the first such vertex.
 */
PartExport bool reflexCircleCorner(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    gp_Pnt* corner = nullptr
);

/** Where the construction merged its own faces met on one surface (ops#900): the result before the
 * merge, with its history from the base, and each element of the result that comes from elements
 * of the result before the merge, with those elements. finish() names such an element as the
 * result before the merge names its first source, and gives it each other source's names too. So
 * the names of the result before the merge stay, a reference to either of two merged rounds holds
 * by its name, and one made to the merged face goes back to the first round below the limit.
 * The first source is the round of the edge first in the body's history (Onshape's, R1-R8 and R8
 * by order of ops#900): `origins` gives the base edges each source comes from, which finish()
 * ranks by their names (the feature, then the sketch geometry); the sources come ranked by the
 * base's edge index, where the names say neither
 */
struct PartExport MergedNames
{
    TopoDS_Shape unmerged;
    std::shared_ptr<ShapeMapper> mapper;
    std::vector<std::pair<TopoDS_Shape, std::vector<TopoDS_Shape>>> sources;
    std::vector<std::pair<TopoDS_Shape, std::vector<TopoDS_Shape>>> origins;
};

/// A fillet's mitre corner (mitreCircleCorner()): the vertex, on the plane face the two edges
/// share, and the mitre's top, r up the corner's third edge, where the rounds' mitre starts
struct MitreCorner
{
    gp_Pnt at;
    gp_Pnt top;
};

/** Whether the selection has a fillet's mitre corner (ops#941): a vertex of 3 edges, two of them
 * selected, concave, a line and a circle on a plane face both walls are square to, convex in the
 * material, the line normal to the arc within 1e-6 rad, R > 2 r on an inner arc, and the mitre's
 * foot inside both sweeps of the construction's piece. OCCT builds the mitre there, but in narrow
 * bands of radius inexactly or invalidly. corners, if not null, receives every such corner.
 * Reads only plain shapes, as construct().
 */
PartExport bool mitreCircleCorner(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    std::vector<MitreCorner>* corners = nullptr
);

/// How far a result's mitres are off (mitreOff()): negative where a corner has no mitre edge
struct MitreOff
{
    /// The largest distance of a mitre edge's points from its two rounds
    double rounds {-1.0};
    /// The largest distance of a mitre edge's ends from its vertices (a mitre cut short)
    double ends {-1.0};
    bool found() const
    {
        return rounds >= 0.0 && ends >= 0.0;
    }
    double worst() const
    {
        return found() ? std::max(rounds, ends) : -1.0;
    }
};

/** How far OCCT's (or the construction's) mitres at the corners are off (ops#941 section 4): per
 * corner, the result's edges not of the base between a cylinder face of radius r and a torus face
 * of minor radius r, one end at the corner's top (within r / 10); at 8 points of each, the distance
 * to both surfaces in closed form, and at its ends the distance to its vertices. Not found (a
 * patch, or the mitre missing or cut short at its top) where a corner has no such edge.
 */
PartExport MitreOff mitreOff(
    const TopoDS_Shape& result,
    const TopoDS_Shape& base,
    const std::vector<MitreCorner>& corners,
    double radius
);

/// The most mitre corners a valid fillet asks the construction for (ops#941 section 4): more are
/// left to OCCT, so that the ask stays well within the feature's time
constexpr std::size_t mitreCap = 64;

/// How far the construction's own mitre may be off (both of mitreOff()), for a radius: five times
/// its worst as measured, never under 1e-5
PartExport double mitreThreshold(double radius);

/** Whether OCCT's valid mitre is off by enough to ask the construction (ops#941 section 4, the
 * visible floor, coordinator c784): not found, its ends off their vertices by over
 * max(mitreThreshold(), 1e-5 r) (a band's mitre, cut short or misplaced: 2.6e-5 r and more as
 * measured, against at most 1.4e-7 r elsewhere), or its points off its rounds by over
 * max(mitreThreshold(), 1e-3 r) (OCCT's approximation of the curve is a continuum up to 7.5e-4 r
 * at 20 deg and 100x; its worst band, 4.1e-3 r). Elsewhere OCCT's result stands.
 */
PartExport bool mitreAsks(const MitreOff& occt, double radius);

/// What construct() makes: a shape and its history from the base, without names (kernel safety S1)
struct PartExport Construction
{
    TopoDS_Shape shape;
    std::shared_ptr<ShapeMapper> mapper;
    /// Set where the construction merged its own faces (constructShape())
    MergedNames merged;
    int edges {0};
    int corners {0};
    /// Whether a round rolled on over a tangent edge onto the next face (rollOn)
    bool rolledOn {false};
    /// Whether a chamfer's wedge ran on along its edge's line through the whole part
    /// (constructThroughWedge(), ops#936)
    bool ranThrough {false};
    /// Why the rim rounds were not built directly, where the construction by Booleans ran
    std::string rimRefusal;
    /// The rim rounds were not built directly because a part of the body that is neither their
    /// plane face nor a wall lies within their reach (a cavity or a blind hole under the rim):
    /// OCCT's own round runs through that part as well, valid and wrong
    bool rimBlocked {false};
    /// Built by a rule that refused before ops#898: a fill kept over its face (cause A), and a
    /// concave arc's end at a cusp of its floor (cause B), which leads to it. Where a route that
    /// came after the construction's refusal builds the dress-up, it did so before, and its
    /// result stands (review of PR 484, S5)
    bool newRule {false};
};

/** build() in two steps, so that the long one can run on a worker thread (KernelBudget::run()):
 * construct() reads only plain shapes and touches no element map or hasher; finish() names the
 * result on the caller's thread.
 *
 * @param base The shape being dressed up: one solid (the makerInput() copy's shape)
 * @param edges The selected edges of the base
 * @param out Receives the construction when it succeeds and passes every check
 * @param reason If not null, receives why the construction refused
 * @return Whether it succeeded
 */
PartExport bool construct(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    Construction& out,
    std::string* reason = nullptr
);

/** What a rim round removes, measured on its face alone: the volume between the face and the plane
 * face it rounds, which is the integral over the face of its depth under the plane times its
 * normal's part along the plane's (the rounds' plans fill the band between the walls and the top
 * edges). On a torus about the plane's normal that integrand depends on v alone, on a cylinder
 * along the plane on u alone, so the integral is one along the face's edges' curves on the surface:
 * no lever arm, and no other face in it. OCCT's volume of the changed faces is good to 1e-6 of
 * each face's own term about a point of the body, which for a large rim's walls and plane face is
 * more than its rounds remove (FSLC #50's rim at z 14.15: 0.325 for 0.335 at r 0.05).
 *
 * @param round The round's face: on a torus about the plane's normal, or a cylinder along the plane
 * @param onPlane A point of the plane face's plane
 * @param normal The plane's normal
 * @param volume Receives the volume, positive
 * @return False for any other surface, or an edge without its curve on the face
 */
PartExport bool roundUnderPlane(
    const TopoDS_Face& round,
    const gp_Pnt& onPlane,
    const gp_Dir& normal,
    double& volume
);

/** Whether the volume a rim's rounds removed passes the direct builder's check (ops#640).
 *
 * The slack is what the base's own measure may be off where its vertices stand beside their edges'
 * crossings (a Boolean's by 1e-6): wide enough there to hide a wrong round. So:
 * - the bodies' measure (the changed faces', or the whole bodies' difference) passes alone only
 *   where it agrees within 2e-4 of the expected volume, without the slack;
 * - else the rounds' own measure (roundUnderPlane(), summed) must agree within 2e-4, without the
 *   slack (it follows the plan, not the base's vertices), while the bodies' agrees within
 *   rimVolumeCoarse(): the rounds' measure alone is blind to a wrong wall;
 * - where the rounds have no measure ( rounds null), the bodies' passes within the slack.
 */
PartExport bool rimVolumeAccepted(
    double expected,
    double slack,
    double whole,
    double bodies,
    const double* rounds
);

/// How far the bodies' measure may be off beside the rounds' own: OCCT's accuracy on the whole
/// body (1e-6 of its volume), 2e-4 of the expected volume, and the slack
PartExport double rimVolumeCoarse(double expected, double slack, double whole);

/** The part of a fillet that is whole rim loops of plane faces with walls square to them, lines
 * and circles, built directly without a Boolean (notes/boolean-free-mitre.md); the caller rounds
 * the rest of the selection on the result. At the limit only (Request::limitOnly): the loops with
 * a reflex corner with a circle. Checked as construct()'s direct rim rounds are.
 *
 * @param base The shape being dressed up: one solid (the makerInput() copy's shape)
 * @param edges The selected edges of the base
 * @param out Receives the body with the loops' rounds
 * @param rest Receives the selected edges that are in no loop built: edges of out's shape
 * @return Whether some loop was built, and every other selected edge is still an edge of the body
 */
PartExport bool constructRims(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    Construction& out,
    std::vector<TopoDS_Shape>& rest
);

/** ops#918: every picked line whose end runs into the mitre of two earlier rounds of a smaller
 * radius (the mitre picked, or in the line's tangent chain), its round run on to the earlier
 * rounds' plane with a torus at its foot, as Onshape builds it (notes/fillet-mitre-runon-918.md).
 * Built in one Boolean on the base; rest is the selection less the lines and mitres. False, with
 * the reason, when no corner passes the rule
 */
PartExport bool constructMitreRunOns(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    Construction& out,
    std::vector<TopoDS_Shape>& rest,
    std::string* reason
);

/** Whether a chamfer by equal distances is one the construction builds before OCCT because a
 * picked edge's faces meet at an angle that varies along it (ops#942,
 * notes/chamfer-varying-angle-942.md section 3 c and section 4 point 12): every picked edge is a
 * closed contour of its own (no two share a vertex) of a covered kind, a closed ellipse between a
 * plane and a cylinder it is not square to, or a closed circle between a plane and its cylinder,
 * and at least one of them varies in angle (anglesVary()). Reads only plain shapes and runs no
 * Boolean. False for any other chamfer.
 */
PartExport bool variesAlongLoneEdge(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
);

/** Whether the angle between the faces of some edge varies along it, sampled at stations along
 * each edge (by more than 1e-7 rad): the edges where WidthAt matters. Edges without two faces
 * count as not varying.
 */
PartExport bool anglesVary(const TopoDS_Shape& base, const std::vector<TopoDS_Shape>& edges);

/** The longest leg of the chamfer variesAlongLoneEdge() builds, over its edges: the width w with
 * WidthAt::narrowest, w (1 + sin t) / (1 - sin t) with WidthAt::widest on an edge of tilt t
 * (PartDesign::Chamfer's reach). The width where an edge can't be analysed.
 */
PartExport double longestLeg(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
);

/** Whether the construction should run before OCCT, whose own checks never ask it where its
 * result is valid. Either some selected edge is a convex rim arc on a bulging wall tighter than
 * the round (ops#640, C4 shape A), where OCCT's result is wrong (notes/fillet-tight-arc.md); or
 * every selected edge is a straight edge between two cylinders along it (Case Base #104), where
 * OCCT's round is a B-spline face between B-spline edges and the exact round is a cylinder
 * (notes/fillet-fallback.md). Reads only plain shapes, as construct(). False for a chamfer, and
 * when an edge can't be analysed.
 */
PartExport bool preferConstruction(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
);

/** For each of the edges, whether the construction's analysis of a single edge takes it (a line
 * between planes or cylinders along it, a circle between a plane and a coaxial cylinder or cone):
 * the edges it could build, as against those only OCCT builds (ops#952). Reads only plain
 * shapes; false where the analysis refuses or throws.
 */
PartExport std::vector<bool> coveredEdges(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
);

/** Whether a fillet's contact line on a face next to a selected edge runs along part of that face's
 * own boundary, and on across the face beyond it (ops#806): a step in the face exactly at the
 * round's tangent line, as a rib in a slot whose top is level with the rim round's lower tangent
 * line. OCCT 8.0.1's fillet walks along that boundary there and can read an edge's curve that is
 * not set (BRepBlend_SurfRstConstRad::Values): the process dies with SIGSEGV, which no handler on
 * the budget's worker thread can turn into an error. The construction is for exactly this case (a
 * new edge landing on an existing one), so the fillet runs it alone, without OCCT, and fails with
 * an error where it refuses.
 *
 * Only lines between planes and circles between a plane and their cylinder are read (analyse());
 * the contact line is the section's end on the face swept along the edge. A boundary that covers
 * the whole contact line (a face exactly as wide as the round, which OCCT builds or refuses
 * cleanly) does not count. Reads only plain shapes, as construct(). False for a chamfer, a
 * variable radius, and when an edge can't be analysed.
 *
 * @param where If not null and the answer is true, receives where, for the error message
 */
PartExport bool contactOnPartOfAnEdge(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    std::string* where = nullptr
);

/** Whether one of OCCT's contours runs through a kink: two consecutive edges of it whose directions
 * at their common vertex differ by more than 1e-4 rad (ops#762). OCCT 8.0.1 carries a contour on
 * past a vertex wherever the faces at the vertex's other edges meet within 0.1 rad
 * (ChFi3d's FaceTangency(), which reads ChFi3d::IsTangentFaces() with its fixed 0.1 rad), with no
 * test of the two edges' own directions short of a turn-back. Its round or chamfer then ends each
 * edge's strip in a cross-section at the vertex and closes the wedge between the two
 * cross-sections with planes: a valid solid with a tooth left at the kink, where the exact result
 * is the two strips meeting in a mitre (as OCCT itself builds from 0.1 rad on). A regular polygon's
 * rim does it from 63 sides on. The dress-up runs the exact construction alone there, below the
 * limit too, and fails with an error where it refuses.
 *
 * @param contours OCCT's contours as the maker reports them after Add(), each in its order
 * @param where If not null and the answer is true, receives where, for the error message
 * @param runs If not null, receives the contours cut at their kinks of more than 0.01 rad (OCCT's
 * own tolerance for edges that carry on): the tangent chains proper, each in its order (a closed
 * contour's last and first edges in one run where they carry on)
 */
PartExport bool kinkedContour(
    const std::vector<std::vector<TopoDS_Shape>>& contours,
    std::string* where = nullptr,
    std::vector<std::vector<TopoDS_Shape>>* runs = nullptr
);

/// Names a construction as through the fillet's own history (op), from base, into result
PartExport void finish(
    TopoShape& result,
    const Construction& construction,
    const TopoShape& base,
    const char* op
);

/** The first face of a dress-up's result, not a face of its base, that is too thin to be one: what
 * OCCT leaves of a face the dress-up consumes whole (the stadium's top, area 0, ops#298), or a
 * sliver near that limit narrower than its own tolerance. Its width, that of the rectangle with
 * its area and perimeter (a strip's width, a square's side), is below the largest tolerance of
 * its edges (at least Precision::Confusion()). A sliver wider than that is a face OCCT built
 * correctly (the rib's top at r = 2 - 1e-7 is 2e-7 wide), and is kept. Null if there is none.
 */
PartExport TopoDS_Face thinFace(const TopoDS_Shape& result, const TopoDS_Shape& base);

/** Whether one of the edges ends in a cusp: an unselected edge of one of its faces leaves the
 * vertex the way it does (Case Base #76, a tunnel's half circle on a slot's end wall, the slot's
 * walls tangent to the tunnel). OCCT's chamfer there can be valid and wrong (a face running out
 * of the body), so the exact construction builds it first, and the chamfer fails where it refuses
 * (kernel layer step 1, ops#640). With \a which, the indices in \a edges of every edge that ends
 * in a cusp, for the error that names them.
 */
PartExport bool endsInCusp(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    std::vector<std::size_t>* which = nullptr
);

/** The volume-sign post-condition of a dress-up (kernel layer, notes/kernel-layer.md section 1;
 * ops#762): a fillet or chamfer of convex edges only removes material, one of concave edges only
 * adds it. Empty where \a result changes \a base's volume that way, or where the edges (the
 * selected ones and OCCT's contours, request.contour) aren't all convex or all concave, each
 * judged at three points along it, or can't be judged. Else what is wrong, with the numbers:
 * OCCT's round of a regular 100-gon's rim (sides 2, r 0.2) passes BRepCheck with untrimmed faces
 * and 5.39 mm3 added where 1.714 is removed. The change is integrated over the faces that differ
 * only, and a wrong sign is confirmed by the adaptive integration before it counts. Checked only
 * for a base and result of one solid and nothing else, and where every face that differs lies on
 * a plane, cylinder, cone, sphere or torus (exact integrals): a free-form face's error can exceed a small
 * dress-up's change. Cost: the volume integrals of the analytic faces the dress-up made or changed.
 */
PartExport std::string wrongWay(
    const TopoDS_Shape& result,
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
);

/** Whether one of a fillet's edges is a concave arc ending at a vertex of 4 edges where its tangent
 * chain turns convex (Nest Cover #151; the construction's VertexClass::Overflow). OCCT stops its
 * contour there and builds ends Onshape doesn't (oracle 17 Q-OVF: a valid solid, 2 faces too many,
 * 29 mm3 short), so the exact construction builds it, or the fillet fails. The edges of OCCT's
 * contours (request.contour) count with the selected ones: its fillet ends where they end.
 */
PartExport bool endsInOverflow(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
);

/** Whether one of a dress-up's edges is an arc whose two ends lie on one plane that misses its
 * axis, with a section that reaches inside the plane's distance from the axis (ops#888 A2: a boss
 * cut by a chord plane, its top arc chamfered or rounded by at least R - c). Onshape's cone or
 * torus runs on across the plane, which cuts it (oracle s8ecd DU2: the top a whole disc); OCCT's
 * ends there are not that (a valid solid, 3 faces too many, 17.9 mm3 short on DU2's chamfer 4), so
 * the exact construction builds it, or the dress-up fails. The edges of OCCT's contours
 * (request.contour) count with the selected ones.
 */
PartExport bool endsInRing(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
);

/** A point well inside the solid `region` that `result` holds, found without integrating a face:
 * the midpoints of the intervals that lines across region's box (9 x 9 along each axis) spend
 * inside it, kept when longer than 20 times the shapes' largest tolerance and classified IN
 * region, then classified against result. None if result holds no such point (or region is too
 * thin for one). The check that a cut removed where two tools overlap: there the volume check's
 * allowance for raised tolerances can be as large as the overlap itself (ops#669).
 */
PartExport std::optional<gp_Pnt> materialIn(const TopoDS_Shape& result, const TopoDS_Shape& region);

/** Notes on this thread that a dress-up returns OCCT's result although it is not a valid shape,
 * with why the exact construction refused (decision 418, ops#640). A feature checks its result
 * itself (Part::checkDressUp() repairs it or fails); the Python API raises with this reason, and
 * never returns the invalid shape (takeInvalidResult()).
 */
PartExport void noteInvalidResult(const std::string& reason);

/** Within its scope, on this thread, a fillet treats OCCT's valid result as refused (ops#990): the
 * exact construction is asked, with its wider scope, and its result stands where it builds;
 * where it refuses, OCCT's result is returned as before. Set by a feature whose own check of
 * OCCT's result refused it (Part::lostMaterial(): OCCT rolled the ball on over a dip no ball fits
 * into and bridged it, where Onshape builds the plain round), for one more build of the same
 * selection, so that nothing that builds today moves.
 */
class PartExport RefusedResultScope
{
public:
    RefusedResultScope();
    ~RefusedResultScope();
    RefusedResultScope(const RefusedResultScope&) = delete;
    RefusedResultScope& operator=(const RefusedResultScope&) = delete;
    /// Whether a scope is open on this thread
    static bool active();

private:
    bool outer;
};

/// The reason noted on this thread since the last call (empty if none), which it clears
PartExport std::string takeInvalidResult();

/** Collects what the exact construction builds on this thread while it exists, for the feature's
 * Report-view line (decision 54). Recorders nest; the innermost collects.
 */
class PartExport Recorder
{
public:
    Recorder();
    ~Recorder();
    Recorder(const Recorder&) = delete;
    Recorder& operator=(const Recorder&) = delete;

    /// Adds one construction's result to the innermost recorder, if there is one
    static void add(int edges, int corners, bool rolledOn = false, bool ranThrough = false);

    /// Whether the construction built a result while this recorder collected
    bool built() const
    {
        return builds > 0;
    }

    /// Whether a round it built rolled on over a tangent edge onto the next face: such a round
    /// covers its face beyond the band of a direct round (Part::lostMaterial()'s reach), and its
    /// tool is one closed form the construction measured its result against
    bool rolledOn() const
    {
        return rolled;
    }

    /// Whether a chamfer it built is the plain wedge run on along its edge's line through the
    /// whole part (ops#936): it cuts faces beyond the band of a direct chamfer
    /// (Part::lostMaterial()'s reach), a far leg across a bore included, and the construction
    /// checked what it removed against the wedge
    bool ranThrough() const
    {
        return ran;
    }

    /// Prints the Report-view line if it did, and returns it (else empty):
    /// "<name>: built by the exact construction where OCCT failed: N edges, M corners" (OCCT
    /// refused, or left a face of zero width or an invalid result)
    std::string report(const std::string& name) const;

private:
    Recorder* outer;
    int builds = 0;
    int edges = 0;
    int corners = 0;
    bool rolled = false;
    bool ran = false;
};

/** What the feature that calls the fillet knows of its feature list, for the names of a merged
 * full round (ops#951, notes/fullround-name-order-900.md 3c): Onshape names the merged face after
 * the round of the edge whose making feature comes first in the list. A PartDesign dress-up sets
 * one around makeElementFillet(); finish() asks the innermost one on its thread. Places count from
 * 0, the first feature of the dress-up's BaseFeature chain; -1 is unknown.
 */
class PartExport FeatureOrder
{
public:
    FeatureOrder();
    virtual ~FeatureOrder();
    FeatureOrder(const FeatureOrder&) = delete;
    FeatureOrder& operator=(const FeatureOrder&) = delete;

    /// The place of the feature whose id or naming tag is \a tag
    virtual int place(long tag) const = 0;
    /// The place of the first feature that reads the sketch \a sketch and whose result holds an
    /// element whose name starts with the top-level section \a section (the sketch's own edge)
    virtual int sketchMaker(long sketch, const std::string& section) const = 0;
    /// The tags of the sketches the feature at \a place reads
    virtual std::vector<long> sketchesAt(int place) const = 0;
    /// The place of the last feature, from \a place on, that changed the edge named \a name in
    /// the base (oracle900b row c: Onshape ranks an edge a later cut shortened at the cut's
    /// place). The fork's names don't say it: a shortened edge keeps its name, so the edge of
    /// that name is compared feature by feature
    virtual int lastChange(const Data::MappedName& name, int place) const = 0;

    /// The innermost on this thread, or null
    static const FeatureOrder* current();

private:
    FeatureOrder* outer;
};

/** Notes, once per feature, that a merged full round's first name was taken by the solid's edge
 * order because the edges' history does not say which was made first (fullround-name-order-900.md
 * section 5). The feature takes it after makeElementFillet() and shows it as its warning.
 */
PartExport void noteNamingOrder(const std::string& warning);

/// The note made on this thread since the last call (empty if none), which it clears
PartExport std::string takeNamingOrder();

}  // namespace Part::FilletFallback

#endif  // PART_FILLETFALLBACK_H
