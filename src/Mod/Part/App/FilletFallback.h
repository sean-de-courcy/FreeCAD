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

#include <string>
#include <vector>

#include <TopoDS_Face.hxx>
#include <TopTools_DataMapOfShapeReal.hxx>

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

/** Copies of the shapes handed to one OCCT maker that raises its inputs' tolerances in place, as
 * makerInput() makes the base's: BRepFeat up to a face raises the face's edges and vertices and
 * the base's where the prism meets them (ops#347). The copies are made together, so a sub-shape
 * the shapes share (an up-to face of the base, the faces of a shell of the base's faces) is one
 * sub-shape of the copies too. Each copy keeps its shape's element map and Tag.
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

/** The first face of a dress-up's result, not a face of its base, that is too thin to be one: what
 * OCCT leaves of a face the dress-up consumes whole (the stadium's top, area 0, ops#298), or a
 * sliver near that limit narrower than its own tolerance. Its width, that of the rectangle with
 * its area and perimeter (a strip's width, a square's side), is below the largest tolerance of
 * its edges (at least Precision::Confusion()). A sliver wider than that is a face OCCT built
 * correctly (the rib's top at r = 2 - 1e-7 is 2e-7 wide), and is kept. Null if there is none.
 */
PartExport TopoDS_Face thinFace(const TopoDS_Shape& result, const TopoDS_Shape& base);

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
    static void add(int edges, int corners);

    /// Whether the construction built a result while this recorder collected
    bool built() const
    {
        return builds > 0;
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
};

}  // namespace Part::FilletFallback

#endif  // PART_FILLETFALLBACK_H
