// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <Base/Vector3D.h>

namespace Data
{

/** The geometry of one element, saved next to a reference's shadow (ops#7, the solver's tiers 2
 * and 3).
 *
 * It is taken in the target shape's coordinates without the shape's own placement, so moving a
 * feature changes no fingerprint. It is the only source of geometric evidence: the old shape is
 * gone when a reference is retried.
 *
 * Text form, version 1 (the `fp` attribute of a link's `<Sub>`):
 *
 *     1|<type>|<kind>|<size>|<cx>,<cy>,<cz>|<dx>,<dy>,<dz>|<r1>[,<r2>]
 *
 * with `_` for an empty field.
 * - type: `F`, `E` or `V`.
 * - kind: faces `Plane Cylinder Cone Sphere Torus Revolution Extrusion Bezier BSpline Offset
 *   Other`; edges `Line Circle Ellipse Hyperbola Parabola Bezier BSpline Offset Other`; vertices
 *   `Point`.
 * - size: area of a face, length of an edge; empty for a vertex.
 * - c: the centre of mass, or the point of a vertex.
 * - d: a plane's normal (with the face's orientation), the axis of a cylinder, cone, torus or
 *   revolution, a line's direction, the axis of a circle or ellipse. Axes and line directions are
 *   sign-normalized by the producer; empty for anything else.
 * - r: a cylinder's, sphere's or circle's radius; a cone's semi-angle; a torus's or ellipse's
 *   major and minor radii; empty otherwise.
 *
 * Version 2 (Task 2 PR 7b), written only for a circle edge, which has a location:
 *
 *     2|E|Circle|<size>|<cx>,<cy>,<cz>|<dx>,<dy>,<dz>|<r>|<ox>,<oy>,<oz>
 *
 * - o: the circle's centre. Without it an arc can't be placed on its circle (the centre of mass
 *   lies anywhere on a circle around it), which the solver's continuation needs.
 *
 * Version 3 (Task 2 PR 8), written only for a planar face, which has an extent:
 *
 *     3|F|Plane|<size>|<cx>,<cy>,<cz>|<dx>,<dy>,<dz>|_|<x0>,<y0>,<z0>,<x1>,<y1>,<z1>
 *
 * - x0..z1: the face's bounding box (lower and upper corners), in the frame of c. Without it a
 *   face's region can't be bounded, so a coplanar face beside a shrunk one can't be told from
 *   the rest of it; with it, a face outside the old box can't hold a point of the old face.
 *
 * Numbers have 12 significant digits, in the classic locale, so the text is the same on every
 * platform and in every locale. A reader takes a version it doesn't know as no fingerprint.
 */
struct AppExport ElementFingerprint
{
    static constexpr int Version = 1;
    /// The text form of a fingerprint with a location (Task 2 PR 7b): an eighth field. Only
    /// circle edges have one, so every other fingerprint's text is version 1, as before.
    static constexpr int VersionWithLocation = 2;
    /// The text form of a fingerprint with an extent (Task 2 PR 8): an eighth field. Only planar
    /// faces have one.
    static constexpr int VersionWithExtent = 3;

    /// `F`, `E` or `V`; 0 for no fingerprint.
    char type = 0;
    std::string kind;
    std::optional<double> size;
    std::optional<Base::Vector3d> center;
    std::optional<Base::Vector3d> direction;
    std::vector<double> radii;
    /// The centre of a circle edge (in the frame of `center`); empty otherwise.
    std::optional<Base::Vector3d> location;
    /// The bounding box of a planar face, its lower and upper corners (in the frame of
    /// `center`); both empty otherwise.
    std::optional<Base::Vector3d> extentMin;
    std::optional<Base::Vector3d> extentMax;

    bool isValid() const
    {
        return type != 0;
    }

    /// The text form; empty for an invalid fingerprint.
    std::string toString() const;

    /** Parses the text form. An empty text, an unknown version or a malformed field gives an
     * invalid fingerprint (no fingerprint), never an exception.
     */
    static ElementFingerprint fromString(std::string_view text);

    /// Formats one number as the text form does: 12 significant digits, classic locale, and 0
    /// for magnitudes below 1e-12 (numerical noise) and for -0.
    static std::string formatNumber(double value);

    friend bool operator==(const ElementFingerprint& a, const ElementFingerprint& b)
    {
        return a.type == b.type && a.kind == b.kind && a.size == b.size && a.center == b.center
            && a.direction == b.direction && a.radii == b.radii && a.location == b.location
            && a.extentMin == b.extentMin && a.extentMax == b.extentMax;
    }
    friend bool operator!=(const ElementFingerprint& a, const ElementFingerprint& b)
    {
        return !(a == b);
    }
};

}  // namespace Data
