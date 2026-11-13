// SPDX-License-Identifier: LGPL-2.1-or-later

/** Canonical faces after OCCT's fillet or chamfer (ops#640, Case Base #105).
 *
 * OCCT's fillet has closed forms for a plane beside a plane, a cylinder or a cone. Every other pair
 * goes to its walker, which returns the round as a B-spline surface with B-spline boundary curves,
 * even where the exact round is a cylinder, a torus or a sphere (a straight edge between two
 * cylinders along it: a B-spline within 3e-8 of the exact cylinder). The exact construction
 * (FilletFallback) reads lines, circles and elementary surfaces only, so a later dress-up over an
 * edge of such a round was refused.
 *
 * convert() replaces the maker's own B-spline faces that are a plane, cylinder, cone, sphere or
 * torus within tolerance by that surface, and their B-spline edges that are a line, circle or
 * ellipse by that curve, through BRepTools_Modifier: the topology is kept one to one, so the
 * result is named exactly as OCCT's result would be (Mapper). Where recognition or any check is
 * unsure, the face stays as it is; if the converted shape as a whole fails its checks, OCCT's
 * result stands unchanged.
 *
 * Design: notes/canonical-faces-after-fillet.md in the ops repository.
 */

#ifndef PART_CANONICALFACES_H
#define PART_CANONICALFACES_H

#include <memory>
#include <string>
#include <vector>

#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>

#include <Mod/Part/PartGlobal.h>
#include "TopoShape.h"

class BRepTools_Modifier;

namespace Part::CanonicalFaces
{

/// The recognition tolerance, for surfaces and curves: ten times Precision::Confusion()
constexpr double tolerance = 1e-6;

/// What convert() makes: the converted shape and its one-to-one history from the input
struct PartExport Conversion
{
    TopoDS_Shape shape;
    std::shared_ptr<BRepTools_Modifier> modifier;
    /// Faces that got an elementary surface, edges that got a line, circle or ellipse
    int faces {0};
    int edges {0};
    /// The largest distance between an old surface or curve and its replacement
    double gap {0.0};

    /// The converted shape's counterpart of a sub-shape of the input: itself where nothing of it changed
    TopoDS_Shape image(const TopoDS_Shape& subShape) const;
};

/** Replaces the dress-up's own B-spline faces that are elementary surfaces within tolerance.
 *
 * Reads only plain shapes (it runs on the dress-up's worker thread), and leaves result untouched.
 * Never converted: a face of the base, or one on a base face's surface (a base face the dress-up
 * trimmed); a face with a seam, a degenerate or a closed edge; anything further than tolerance
 * from its elementary surface. An edge beside a face that stays a B-spline keeps its curve.
 *
 * @param result OCCT's fillet or chamfer, valid
 * @param base The shape that was dressed up
 * @param out Receives the conversion when at least one face was converted and every check passed
 * @param why If not null, receives why nothing was converted
 * @return Whether out holds a converted shape
 */
PartExport bool convert(
    const TopoDS_Shape& result,
    const TopoDS_Shape& base,
    Conversion& out,
    std::string* why = nullptr
);

/** The distance between a face's surface and the elementary surface nearest to it over the face,
 * as recognised with a loose tolerance (1e-2), and that surface's kind ("plane", "cylinder",
 * "cone", "sphere", "torus"): a measurement for the design's tolerance band and the tests.
 * Negative when the surface is no B-spline or nothing is recognised.
 */
PartExport double measure(const TopoDS_Face& face, std::string* kind = nullptr);

/// The maker's history with each output passed through a conversion: names as the maker's own
struct PartExport Mapper: MapperMaker
{
    const Conversion& conversion;
    Mapper(BRepBuilderAPI_MakeShape& maker, const Conversion& conversion)
        : MapperMaker(maker)
        , conversion(conversion)
    {}
    const std::vector<TopoDS_Shape>& modified(const TopoDS_Shape& s) const override;
    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& s) const override;
};

}  // namespace Part::CanonicalFaces

#endif  // PART_CANONICALFACES_H
