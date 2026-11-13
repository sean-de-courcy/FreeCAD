// SPDX-License-Identifier: LGPL-2.1-or-later

/** A constant-radius blend as a true rolling ball where OCCT's fillet is not one (ops#640, decision 425).
 *
 * A constant-radius edge blend is the surface a ball of radius r sweeps while it touches both walls.
 * OCCT's fillet builds a circle of radius r in the plane normal to the edge instead; the two agree
 * only where the walls' normals at the contact points lie in that plane (planes, coaxial cylinders).
 * On a twisted wall OCCT's surface is off by r (1 - cos alpha) and each seam between two blend faces
 * lands r sin alpha away (Case Base #103: 1e-3 mm and 0.03 mm against Onshape, whose faces are a
 * rolling ball to 1e-13).
 *
 * correct() keeps OCCT's fillet for the topology and replaces the geometry of its blend faces: per
 * chain of blend faces, every ball position is solved by Newton from OCCT's own section (the centre
 * at distance r from both untrimmed walls), the seam between two blend faces is the ball's circle
 * where a contact point crosses from one wall face to the next, and the new surfaces, curves,
 * pcurves and vertices go into the body through one BRepTools_Modification. Faces, edges and
 * vertices stay the same in number and in order, so element names stay as they are.
 *
 * Plain shapes only: no TopoShape, no document, no console.
 *
 * Design and tests: notes/rolling-ball-blend.md and notes/rolling-ball-killtests.md (ops repository).
 */

#ifndef PART_ROLLINGBALLBLEND_H
#define PART_ROLLINGBALLBLEND_H

#include <string>
#include <vector>

#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>

#ifdef ROLLINGBALL_STANDALONE
# define PartExport
#else
# include <Mod/Part/PartGlobal.h>
#endif

namespace Part::RollingBallBlend
{

enum class Outcome
{
    /// Nothing recognised: the shape is OCCT's, untouched (the reason says why)
    NotMine,
    /// Every recognised chain is corrected and checked
    Corrected,
    /// A recognised chain could not be built or failed a check: the caller must fail the fillet
    Refused
};

struct Report
{
    Outcome outcome = Outcome::NotMine;
    /// Why nothing was done, or what was refused
    std::string reason;
    /// Corrected chains, and their blend faces
    int chains = 0;
    int faces = 0;
    /// Stations per face in the last (accepted) pass, the largest
    int stations = 0;
    /// The worst ball residual |dist(centre, wall) - r| over the recognised chains, OCCT's and ours
    double residualBefore = 0.0;
    double residualAfter = 0.0;
    /// The largest move of a seam vertex
    double seamMove = 0.0;
    /// Corrected: the same topology in the same order, with the new geometry
    TopoDS_Shape shape;
};

/** Correct the blend faces of a constant-radius fillet.
 *
 * @param shape the fillet's result
 * @param blendFaces the faces of @p shape that the fillet generated from its edges
 * @param radius the fillet's radius
 */
PartExport Report correct(const TopoDS_Shape& shape, const std::vector<TopoDS_Face>& blendFaces, double radius);

/// The ball residual of one blend face against its two walls' untrimmed surfaces (a grid of points)
PartExport double ballResidual(
    const TopoDS_Face& blend,
    const TopoDS_Face& wall1,
    const TopoDS_Face& wall2,
    double radius
);

}  // namespace Part::RollingBallBlend

#endif  // PART_ROLLINGBALLBLEND_H
