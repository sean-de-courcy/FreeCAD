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
 * Version 4 (ops#360, PR 340 round 5), written only for an element told apart from its twins
 * only by its place among them (the ORD flag: a piece of a far cap; since ops#503 D1, any twins
 * by the solver's twin test, Data::isTwinName()):
 *
 *     4|<type>|<kind>|<size>|<c>|<d>|<r>|<o or x0..z1 or _>|<tx>,<ty>,<tz>,<n>
 *     4|<type>|<kind>|<size>|<c>|<d>|<r>|<o or x0..z1 or _>|_,1
 *
 * - the eighth field: what versions 2 and 3 have there, or `_`.
 * - t: the mean of the centres of the n twins, the element's included (n >= 2), in the frame of
 *   c. An edit can trade twins' names; the element's offset from it tells the solver which twin
 *   went where, under a move or a turn of them all. `_` with n = 1: a lone element whose name
 *   is keyed by its order (Data::isOrderKeyedName()), so that a later pick of its renumbered
 *   self is told from a trade (ops#503 D1, the twin-pick rule).
 *
 * Version 5 (ops#386, PR 366 round 4), written for every face and edge with an extent, which
 * every one but a degenerated edge has:
 *
 *     5|<type>|<kind>|<size>|<c>|<d>|<r>|<o or _>|<x0>,<y0>,<z0>,<x1>,<y1>,<z1>|<t,n or _>|<p or _>
 *
 * and, for a face with a point inside it (round 6), a twelfth field: `|<i>`.
 *
 * - o: a circle's centre, as in version 2; `_` for anything else.
 * - x0..z1: the element's bounding box, as in version 3, for any kind of face or edge. Without it
 *   a curved or thin piece's place can't be bounded: whether a piece that moved still overlaps
 *   its old place was guessed from its size.
 * - t, n: the twins' centroid and number, as in version 4, or `_`.
 * - p: the element's outline (round 5), the points' coordinates one after another: an edge's
 *   points along it, a face's convex outer boundary in its plane. A box is bounded along the
 *   world's axes only: a turned piece's box is wider than the piece, and an arc's corners seen
 *   along a slanted direction reach past the arc. At most 256 points: a longer outline keeps
 *   every k-th point (round 6), still convex.
 * - i: a point inside the face (round 6), only for a face whose area falls short of its outline's
 *   (an L, a ring): its centre may lie outside it.
 * Versions 3 and 4 are still read; an element with an extent is written as version 5.
 *
 * Version 6 (ops#522, PLAN decision 168), written for a far piece of a Pad up to a face or a
 * shape (a marked projection) whose point lies over an up-to face:
 *
 *     6|<type>|<kind>|<size>|<c>|<d>|<r>|<o or _>|<x0..z1>|<t,n or _>|<p or _>|<i or _>|<u>
 *
 * - i: the inside point, as in version 5, or `_`.
 * - u: the up-to faces that the line along the sweep through the piece's point (its inside
 *   point, else its centre) meets, one or two (a seam), separated by `;`. Each is
 *   `<owner>,<x0>,<y0>,<z0>,<x1>,<y1>,<z1>,<a>,<nx>,<ny>,<nz>,<wx>,<wy>,<wz>`: the name of the
 *   object that owns the face, the face's bounding box and area in that object's own frame (its
 *   placement removed), the face's unit normal there at the point, and the centre of mass of its
 *   outer wire (holes left out). The solver lets a far cap or edge made whole again take the
 *   piece only when the same faces lie under the point now, each the only up-to face like it.
 *
 * Version 7 (ops#526 D2, PLAN decisions 207 and 208), written for any element with sides or marks,
 * a vertex included:
 *
 *     7|<type>|<kind>|<size>|<c>|<d>|<r>|<o or _>|<x0..z1 or _>|<t,n or _>|<p or _>|<i or _>|<u or _>|<s or _>|<m or _>
 *
 * - the fields up to u: version 6's, each of them `_` where the element has none (a vertex's box
 *   and outline; the up-to faces of anything but a far piece).
 * - s: the element's sides, separated by `/`, in no order: an edge's planar faces' and straight
 *   edge's analytic curved faces' outward normals at its middle (`x,y,z`), a curved edge's curved
 *   faces by the side of its principal normal they lie on (`c+`: the face's normal points along
 *   it, a hole's cylinder at its rim; `c-`, a boss's; `c0` within the angle tolerance, a tangent
 *   face), a vertex's edges' directions away from it (both of a closed edge's), a cylinder's,
 *   cone's, sphere's or torus's own side (`c+` when its normal at its middle points away from the
 *   axis or centre, `c-` toward it). The solver tells another element of the same size at the same
 *   place by them (another edge of a member drawn again beside itself, a hole's other crossing).
 * - m: the marks of the objects the target is built from, separated by `/`: `<tag>:<mark>`, the
 *   object's ID as the names carry it and its highest geometry ID when the record was taken (a
 *   sketch's), or `_` for an object without geometry IDs. Only a reference's record has them. The
 *   solver tells an element drawn again at a vacated place (its sources new) from a sibling moved
 *   there (its sources were in the model before) by them.
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
    /// The text form of a fingerprint with its twins' centroid (ops#360, PR 340 round 5): a
    /// ninth field. Only ordered twins have one.
    static constexpr int VersionWithTwins = 4;
    /// The text form of a fingerprint with an extent of any kind (ops#386, PR 366 round 4): the
    /// location, the extent and the twins in fields eight to ten. Every face and edge has one.
    static constexpr int VersionWithBox = 5;
    /// The text form of a far piece's fingerprint with the up-to faces under it (ops#522, PLAN
    /// decision 168): version 5's fields, the inside point or `_`, and the up-to faces.
    static constexpr int VersionWithUpTo = 6;
    /// The text form of a fingerprint with the element's sides and its sources' marks (ops#526
    /// D2): version 6's fields, each of them `_` where empty, then the sides and the marks.
    static constexpr int VersionWithSides = 7;

    /// An up-to face a far piece lies on (version 6): the object that owns it, by its name in its
    /// document, the face's bounding box and area in that object's own frame (its placement
    /// removed), its unit normal there at the piece's point, and the centre of mass of its outer
    /// wire there (the two halves of a square split along a diagonal have the same box, area and
    /// normal; a plate whose hole moved keeps its outer wire).
    struct UpToFace
    {
        std::string owner;
        Base::Vector3d boxMin;
        Base::Vector3d boxMax;
        double area = 0.0;
        Base::Vector3d normal;
        Base::Vector3d wireCentre;

        friend bool operator==(const UpToFace& a, const UpToFace& b)
        {
            return a.owner == b.owner && a.boxMin == b.boxMin && a.boxMax == b.boxMax
                && a.area == b.area && a.normal == b.normal && a.wireCentre == b.wireCentre;
        }
    };

    /// `F`, `E` or `V`; 0 for no fingerprint.
    char type = 0;
    std::string kind;
    std::optional<double> size;
    std::optional<Base::Vector3d> center;
    std::optional<Base::Vector3d> direction;
    std::vector<double> radii;
    /// The centre of a circle edge (in the frame of `center`); empty otherwise.
    std::optional<Base::Vector3d> location;
    /// The bounding box of a face or an edge, its lower and upper corners (in the frame of
    /// `center`); both empty for a vertex and in an older fingerprint of anything but a planar
    /// face (versions 1, 2 and 4).
    std::optional<Base::Vector3d> extentMin;
    std::optional<Base::Vector3d> extentMax;
    /// The mean of the centres of the element's twins, its own included (in the frame of
    /// `center`), and their number; 1 without a centroid for a lone order-keyed element (ops#503
    /// D1); empty and 0 otherwise.
    std::optional<Base::Vector3d> twinCentroid;
    int twinCount = 0;
    /// The element's outline (version 5, PR 366 round 5; in the frame of `center`): a line's two
    /// ends, a curve's points along it from end to end, a face's outer boundary convex about its
    /// plane, in order round it. Empty for a vertex and in an older fingerprint.
    std::vector<Base::Vector3d> outline;
    /// A point inside the face (version 5's twelfth field, PR 366 round 6; in the frame of
    /// `center`), for a face its outline doesn't bound closely (an L, a ring), whose centre may
    /// lie outside it. Empty otherwise.
    std::optional<Base::Vector3d> inside;
    /// The up-to faces under a far piece's point (version 6, ops#522): one, or two on a seam.
    /// Empty otherwise, and for an element without an extent.
    std::vector<UpToFace> upToFaces;

    /// One side of an element (version 7, ops#526 D2), in the frame of `center`.
    struct Side
    {
        /// 0 for a direction; `+`, `-` or `0` for a curved side (`c+`, `c-`, `c0`).
        char curve = 0;
        /// A unit direction when `curve` is 0.
        Base::Vector3d direction;

        friend bool operator==(const Side& a, const Side& b)
        {
            return a.curve == b.curve && a.direction == b.direction;
        }
    };
    /// The element's sides (version 7): empty for an element whose sides tell nothing (a plane, a
    /// free wire's edge) and in an older fingerprint.
    std::vector<Side> sides;

    /// An object the target is built from and its highest geometry ID when the record was taken
    /// (version 7, ops#526 D2).
    struct Mark
    {
        /// The object's ID, as a name's sections carry it.
        long tag = 0;
        /// Its highest geometry ID (App::DocumentObject::elementIdMark()); -1 for an object
        /// without geometry IDs.
        long mark = -1;
        /// The object's output was its base, passed through while suppressed, when the record was
        /// taken (App::DocumentObject::passesBaseThrough()): the record's world (ops#549 PS).
        /// Written `<tag>:<mark>:s`.
        bool suppressed = false;

        friend bool operator==(const Mark& a, const Mark& b)
        {
            return a.tag == b.tag && a.mark == b.mark && a.suppressed == b.suppressed;
        }
    };
    /// The marks of the target's closure (version 7): only a reference's record has them; empty
    /// otherwise and in an older fingerprint.
    std::vector<Mark> marks;

    /// At most this many points in an outline: the reader takes more as a malformed field.
    static constexpr std::size_t MaxOutline = 256;
    /// At most this many up-to faces: the reader takes more as a malformed field.
    static constexpr std::size_t MaxUpToFaces = 2;
    /// At most this many sides and marks (version 7): the reader takes more as a malformed field.
    static constexpr std::size_t MaxSides = 64;
    static constexpr std::size_t MaxMarks = 4096;

    /** \a points with every k-th kept, k the least that leaves at most MaxOutline (PR 366 round 6):
     * a convex outline stays convex, in its order. At most MaxOutline points are returned as
     * they are.
     */
    static std::vector<Base::Vector3d> thinOutline(const std::vector<Base::Vector3d>& points);

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

    /** The convex hull of \a points seen along \a normal (PR 366 round 5): the points on it, in
     * order round it, without those on a straight run between two others. Fewer than three points,
     * or all in a row, give the two ends of the row.
     */
    static std::vector<Base::Vector3d> convexOutline(
        const std::vector<Base::Vector3d>& points,
        const Base::Vector3d& normal
    );

    friend bool operator==(const ElementFingerprint& a, const ElementFingerprint& b)
    {
        return a.type == b.type && a.kind == b.kind && a.size == b.size && a.center == b.center
            && a.direction == b.direction && a.radii == b.radii && a.location == b.location
            && a.extentMin == b.extentMin && a.extentMax == b.extentMax
            && a.twinCentroid == b.twinCentroid && a.twinCount == b.twinCount
            && a.outline == b.outline && a.inside == b.inside && a.upToFaces == b.upToFaces
            && a.sides == b.sides && a.marks == b.marks;
    }
    friend bool operator!=(const ElementFingerprint& a, const ElementFingerprint& b)
    {
        return !(a == b);
    }
};

}  // namespace Data
