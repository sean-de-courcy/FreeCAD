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
 * ops#298). Whenever a configuration is outside the scope or a check fails, build() refuses and
 * the caller raises OCCT's original error or one for the thin face, or returns OCCT's invalid
 * result for the feature's check (Part::checkDressUp()): never a silent wrong solid.
 *
 * Design: notes/fillet-workarounds.md in the ops repository, sections 2a, 3, 4 and 5.6.
 */

#ifndef PART_FILLETFALLBACK_H
#define PART_FILLETFALLBACK_H

#include <memory>
#include <optional>
#include <string>
#include <vector>

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

/// What construct() makes: a shape and its history from the base, without names (kernel safety S1)
struct PartExport Construction
{
    TopoDS_Shape shape;
    std::shared_ptr<ShapeMapper> mapper;
    int edges {0};
    int corners {0};
    /// Whether a round rolled on over a tangent edge onto the next face (rollOn)
    bool rolledOn {false};
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

/** Whether the construction should run before OCCT: some selected edge is a convex rim arc on a
 * bulging wall tighter than the round (ops#640, C4 shape A), where OCCT's result is valid but
 * wrong (notes/fillet-tight-arc.md), so its own checks never ask the construction. Reads only
 * plain shapes, as construct(). False for a chamfer, and when an edge can't be analysed.
 */
PartExport bool preferConstruction(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
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
    static void add(int edges, int corners, bool rolledOn = false);

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
};

}  // namespace Part::FilletFallback

#endif  // PART_FILLETFALLBACK_H
