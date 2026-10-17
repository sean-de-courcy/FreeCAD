// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <cmath>
#include <memory>
#include <numbers>
#include <limits>
#include <optional>
#include <sstream>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_BooleanOperation.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <BRepTools_History.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>
#include <ElCLib.hxx>
#include <ElSLib.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <GProp_GProps.hxx>
#include <Precision.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <NCollection_Map.hxx>
#include <Standard_Failure.hxx>
#include <TopLoc_Location.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_DataMapOfShapeReal.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <TopoDS.hxx>
#include <gp.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Dir.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>

#include <Base/Console.h>
#include <Base/Exception.h>

#include "FilletFallback.h"
#include "TopoShapeMapper.h"

FC_LOG_LEVEL_INIT("FilletFallback", true, true)

namespace Part::FilletFallback
{

namespace
{

constexpr double pi = std::numbers::pi;
/// Lengths: points that are this close coincide
constexpr double linearTolerance = 1e-7;  // Precision::Confusion()
/// Directions whose cross product is this small are parallel
constexpr double angularTolerance = 1e-9;
/// Every measured volume must equal its closed form to this, relative to the tool volumes
constexpr double volumeTolerance = 1e-6;

/// Thrown inside the construction when it refuses; caught by build()
struct Refusal
{
    std::string reason;
};

[[noreturn]] void refuse(const std::string& reason)
{
    throw Refusal {reason};
}

std::string describe(double value)
{
    std::ostringstream ss;
    ss.precision(10);
    ss << value;
    return ss.str();
}

bool parallel(const gp_Dir& a, const gp_Dir& b)
{
    return gp_Vec(a).Crossed(gp_Vec(b)).Magnitude() < angularTolerance;
}

double volumeOf(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape, props);
    return props.Mass();
}

double areaOf(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(shape, props);
    return props.Mass();
}

int countSolids(const TopoDS_Shape& shape)
{
    int count = 0;
    for (TopExp_Explorer it(shape, TopAbs_SOLID); it.More(); it.Next()) {
        ++count;
    }
    return count;
}

/// The face's outward normal at a point on it (planes and cylinders)
gp_Dir outwardNormal(const TopoDS_Face& face, const gp_Pnt& point)
{
    BRepAdaptor_Surface surface(face, Standard_False);
    double u = 0.0;
    double v = 0.0;
    switch (surface.GetType()) {
        case GeomAbs_Plane:
            ElSLib::Parameters(surface.Plane(), point, u, v);
            break;
        case GeomAbs_Cylinder:
            ElSLib::Parameters(surface.Cylinder(), point, u, v);
            break;
        default:
            refuse("a face next to a selected edge is neither a plane nor a cylinder");
    }
    gp_Pnt onSurface;
    gp_Vec du;
    gp_Vec dv;
    surface.D1(u, v, onSurface, du, dv);
    gp_Vec normal = du.Crossed(dv);
    if (normal.Magnitude() < linearTolerance) {
        refuse("degenerate face normal");
    }
    if (face.Orientation() == TopAbs_REVERSED) {
        normal.Reverse();
    }
    return gp_Dir(normal);
}

/// The edge's orientation in the face, composed with the face's own
TopAbs_Orientation orientationIn(const TopoDS_Face& face, const TopoDS_Edge& edge)
{
    std::optional<TopAbs_Orientation> found;
    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
        if (it.Current().IsSame(edge)) {
            if (found && *found != it.Current().Orientation()) {
                refuse("a seam edge");
            }
            found = it.Current().Orientation();
        }
    }
    if (!found) {
        refuse("an edge is not on its face");
    }
    return *found;
}

/** The direction in the face, perpendicular to the edge at the parameter, into the face
 *
 * The face's material lies to the left of its edges, seen from its outward normal, when they
 * are walked in their orientation in the face.
 */
gp_Dir inwardIn(const TopoDS_Face& face, const TopoDS_Edge& edge, double parameter)
{
    BRepAdaptor_Curve curve(edge);
    gp_Pnt point;
    gp_Vec tangent;
    curve.D1(parameter, point, tangent);
    if (orientationIn(face, edge) == TopAbs_REVERSED) {
        tangent.Reverse();
    }
    gp_Vec left = gp_Vec(outwardNormal(face, point)).Crossed(tangent);
    if (left.Magnitude() < linearTolerance) {
        refuse("degenerate edge tangent");
    }
    return gp_Dir(left);
}

/// Faces of the same plane, or of the same cylinder
bool sameDomain(const TopoDS_Face& face, const TopoDS_Face& other)
{
    BRepAdaptor_Surface a(face, Standard_False);
    BRepAdaptor_Surface b(other, Standard_False);
    if (a.GetType() != b.GetType()) {
        return false;
    }
    if (a.GetType() == GeomAbs_Plane) {
        gp_Pln pa = a.Plane();
        gp_Pln pb = b.Plane();
        return parallel(pa.Axis().Direction(), pb.Axis().Direction())
            && pa.Distance(pb.Location()) < linearTolerance;
    }
    if (a.GetType() == GeomAbs_Cylinder) {
        gp_Cylinder ca = a.Cylinder();
        gp_Cylinder cb = b.Cylinder();
        return parallel(ca.Axis().Direction(), cb.Axis().Direction())
            && gp_Lin(ca.Axis()).Distance(cb.Location()) < linearTolerance
            && std::abs(ca.Radius() - cb.Radius()) < linearTolerance;
    }
    return false;
}

/// The exact section of a fillet or chamfer in the plane normal to the edge at a point
struct Section
{
    gp_Pnt corner;  // M, on the edge
    gp_Dir inward[2];
    double alpha = 0.0;  // the angle between the inward directions
    bool fillet = true;
    double radius = 0.0;
    double length[2] = {0.0, 0.0};  // the section's extent along each face
    gp_Pnt ends[2];                 // where it meets each face
    gp_Pnt centre;                  // fillet: the arc's centre
    double area = 0.0;
    gp_Vec centroid;  // from the corner

    TopoDS_Face face() const
    {
        if (!fillet) {
            BRepBuilderAPI_MakePolygon polygon(corner, ends[0], ends[1], Standard_True);
            return BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
        }
        gp_Vec bisector = gp_Vec(inward[0]) + gp_Vec(inward[1]);
        bisector.Normalize();
        gp_Pnt middle = centre.Translated(-bisector * radius);
        Handle(Geom_TrimmedCurve) arc = GC_MakeArcOfCircle(ends[0], middle, ends[1]).Value();
        BRepBuilderAPI_MakeWire wire(
            BRepBuilderAPI_MakeEdge(corner, ends[0]).Edge(),
            BRepBuilderAPI_MakeEdge(arc).Edge(),
            BRepBuilderAPI_MakeEdge(ends[1], corner).Edge()
        );
        return BRepBuilderAPI_MakeFace(wire.Wire(), Standard_True).Face();
    }
};

Section makeSection(
    const gp_Pnt& corner,
    const gp_Dir& inward0,
    const gp_Dir& inward1,
    const Request& request
)
{
    Section s;
    s.corner = corner;
    s.inward[0] = inward0;
    s.inward[1] = inward1;
    s.alpha = std::acos(std::clamp(inward0.Dot(inward1), -1.0, 1.0));
    if (s.alpha < 1e-6 || s.alpha > pi - 1e-6) {
        refuse("the faces at a selected edge are tangent");
    }
    s.fillet = request.kind == Kind::Fillet;
    gp_Vec d0(inward0);
    gp_Vec d1(inward1);
    if (s.fillet) {
        s.radius = request.size1;
        double tangentLength = s.radius / std::tan(s.alpha / 2);
        s.length[0] = s.length[1] = tangentLength;
        gp_Vec bisector = d0 + d1;
        bisector.Normalize();
        s.centre = corner.Translated(bisector * (s.radius / std::sin(s.alpha / 2)));
        // The kite corner, end, centre, end, minus the circular sector at the centre
        double kiteArea = s.radius * tangentLength;
        gp_Vec toCentre(corner, s.centre);
        gp_Vec kiteCentroid = (d0 * tangentLength + d1 * tangentLength + toCentre * 2) / 6;
        double theta = pi - s.alpha;
        double sectorArea = s.radius * s.radius * theta / 2;
        double sectorOffset = 4 * s.radius * std::sin(theta / 2) / (3 * theta);
        gp_Vec sectorCentroid = toCentre - bisector * sectorOffset;
        s.area = kiteArea - sectorArea;
        s.centroid = (kiteCentroid * kiteArea - sectorCentroid * sectorArea) / s.area;
    }
    else {
        s.length[0] = request.size1;
        switch (request.chamferType) {
            case ChamferType::equalDistance:
                s.length[1] = request.size1;
                break;
            case ChamferType::twoDistances:
                s.length[1] = request.size2;
                break;
            case ChamferType::distanceAngle: {
                // The angle is the one between the reference face and the chamfer's face
                double phi = request.size2 * pi / 180;
                double opposite = pi - s.alpha - phi;
                if (phi <= 0 || opposite <= 1e-6) {
                    refuse("chamfer angle out of range");
                }
                s.length[1] = request.size1 * std::sin(phi) / std::sin(opposite);
                break;
            }
        }
        s.area = s.length[0] * s.length[1] * std::sin(s.alpha) / 2;
        s.centroid = (d0 * s.length[0] + d1 * s.length[1]) / 3;
    }
    if (s.length[0] <= linearTolerance || s.length[1] <= linearTolerance
        || s.area <= linearTolerance * linearTolerance) {
        refuse("zero size");
    }
    s.ends[0] = corner.Translated(d0 * s.length[0]);
    s.ends[1] = corner.Translated(d1 * s.length[1]);
    return s;
}

/** How a selected edge ends at one of its vertices (5.6, interface point 1).
 *
 * Corners (section 5.3) are built where the sizes and, at a two-edge corner, the dihedral angles
 * are equal: there OCCT builds a miter, a sphere patch or a corner triangle, which the tools
 * reproduce exactly. Two-edge corners with unequal dihedral angles have their own class: there
 * OCCT's result is the union of the two tools, each run on to the other edge's side face.
 */
enum class VertexClass
{
    /// No other selected edge at the vertex: the tool is bounded by the end face's plane
    FreeEnd,
    /// A selected edge continues this one tangentially: the two tools meet on the plane
    /// normal to the common tangent
    TangentContinuation,
    /// One other selected edge meets this one at an angle (a two-edge corner), with the same
    /// dihedral angle: the two tools meet on the bisector plane of the faces they don't share
    Corner2,
    /// A two-edge corner whose edges have different dihedral angles, convex edges at a convex
    /// vertex: OCCT's rounds meet where the two tools cross (equal radii: in a planar ellipse, on
    /// the plane bisecting the two axes), not on the bisector plane of the faces. Each tool ends
    /// on the plane of the other edge's side face, and the two overlap near the vertex (S1c-b)
    Corner2Unequal,
    /// All three edges at the vertex are selected (a three-edge corner): the edge tools end
    /// where a corner tool (a sphere patch, or a chamfer's corner triangle) begins
    Corner3,
    /// Outside the scope
    Refuse
};

/// A plane that bounds a tool: the tool keeps the side opposite to the normal
struct TrimPlane
{
    gp_Pnt point;
    gp_Dir normal;
};

/** A convex polyhedron, the intersection of the half-spaces the planes keep: its vertices, and
 * its volume in closed form (from the vertices, not measured)
 */
struct Polytope
{
    std::vector<gp_Pnt> vertices;
    double volume = 0.0;
};

Polytope polytopeOf(const std::vector<TrimPlane>& planes)
{
    // Points on a plane, and points that are the same vertex, to this
    constexpr double tolerance = 1e-8;
    auto side = [](const TrimPlane& plane, const gp_Pnt& p) {
        return gp_Vec(plane.point, p).Dot(gp_Vec(plane.normal));
    };
    Polytope result;
    const size_t n = planes.size();
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = i + 1; j < n; ++j) {
            for (size_t k = j + 1; k < n; ++k) {
                gp_XYZ a = planes[i].normal.XYZ();
                gp_XYZ b = planes[j].normal.XYZ();
                gp_XYZ c = planes[k].normal.XYZ();
                double det = a.Dot(b.Crossed(c));
                if (std::abs(det) < 1e-12) {
                    continue;
                }
                double da = a.Dot(planes[i].point.XYZ());
                double db = b.Dot(planes[j].point.XYZ());
                double dc = c.Dot(planes[k].point.XYZ());
                gp_Pnt p((b.Crossed(c) * da + c.Crossed(a) * db + a.Crossed(b) * dc) / det);
                bool inside = std::all_of(planes.begin(), planes.end(), [&](const TrimPlane& q) {
                    return side(q, p) <= tolerance;
                });
                bool known = std::any_of(
                    result.vertices.begin(),
                    result.vertices.end(),
                    [&](const gp_Pnt& v) { return v.Distance(p) <= tolerance; }
                );
                if (inside && !known) {
                    result.vertices.push_back(p);
                }
            }
        }
    }
    if (result.vertices.size() < 4) {
        refuse("a degenerate corner piece");
    }
    gp_XYZ sum;
    for (const auto& v : result.vertices) {
        sum += v.XYZ();
    }
    gp_Pnt inner(sum / static_cast<double>(result.vertices.size()));
    // Each face's area times its distance from an inner point, over three
    for (const auto& plane : planes) {
        std::vector<gp_Pnt> onFace;
        gp_XYZ faceSum;
        for (const auto& v : result.vertices) {
            if (std::abs(side(plane, v)) <= tolerance) {
                onFace.push_back(v);
                faceSum += v.XYZ();
            }
        }
        if (onFace.size() < 3) {
            continue;
        }
        gp_Pnt centre(faceSum / static_cast<double>(onFace.size()));
        gp_Ax2 frame(centre, plane.normal);
        auto angle = [&](const gp_Pnt& v) {
            gp_Vec d(centre, v);
            return std::atan2(d.Dot(gp_Vec(frame.YDirection())), d.Dot(gp_Vec(frame.XDirection())));
        };
        std::sort(onFace.begin(), onFace.end(), [&](const gp_Pnt& p, const gp_Pnt& q) {
            return angle(p) < angle(q);
        });
        double area = 0.0;
        for (size_t m = 0; m < onFace.size(); ++m) {
            gp_Vec p(centre, onFace[m]);
            gp_Vec q(centre, onFace[(m + 1) % onFace.size()]);
            area += p.Crossed(q).Dot(gp_Vec(plane.normal)) / 2;
        }
        result.volume += area * -side(plane, inner) / 3;
    }
    return result;
}

/// A big box on the far side of the plane, i.e. the half-space the tool must not reach into
TopoDS_Shape halfSpaceBeyond(const TrimPlane& plane, double size)
{
    gp_Ax2 frame(plane.point, plane.normal);
    gp_Vec x(frame.XDirection());
    gp_Vec y(frame.YDirection());
    gp_Pnt origin = plane.point.Translated(-x * size - y * size);
    gp_Ax2 corner(origin, plane.normal, frame.XDirection());
    return BRepPrimAPI_MakeBox(corner, 2 * size, 2 * size, size).Shape();
}

/// The polytope as a solid: a box around its vertices with the half-spaces cut away
TopoDS_Shape solidOf(const Polytope& polytope, const std::vector<TrimPlane>& planes)
{
    Bnd_Box box;
    for (const auto& v : polytope.vertices) {
        box.Add(v);
    }
    box.Enlarge(1.0);
    double xmin = 0, ymin = 0, zmin = 0, xmax = 0, ymax = 0, zmax = 0;
    box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
    gp_Pnt low(xmin, ymin, zmin);
    gp_Pnt high(xmax, ymax, zmax);
    TopTools_ListOfShape arguments;
    arguments.Append(BRepPrimAPI_MakeBox(low, high).Shape());
    TopTools_ListOfShape beyond;
    for (const auto& plane : planes) {
        double size = 4 * (low.Distance(high) + plane.point.Distance(low)) + 4;
        beyond.Append(halfSpaceBeyond(plane, size));
    }
    BRepAlgoAPI_Cut cut;
    cut.SetArguments(arguments);
    cut.SetTools(beyond);
    cut.SetRunParallel(Standard_False);
    cut.Build();
    if (!cut.IsDone() || cut.HasErrors()) {
        refuse("building a corner piece failed");
    }
    return cut.Shape();
}

/** A vertex where selected edges meet at an angle (section 5.3): three straight edges and three
 * planar faces. faces[k] is the face that doesn't hold edges[k], and normals[k] its normal
 * pointing into the trihedral the edges span (the material at a convex corner, the air at a
 * concave one), so that normals[k] . away[k] > 0.
 */
struct Corner
{
    TopoDS_Vertex vertex;
    gp_Pnt point;
    TopoDS_Edge edges[3];
    gp_Dir away[3];  // along each edge, away from the vertex
    TopoDS_Face faces[3];
    gp_Dir normals[3];
    /// The material is the trihedral: every face's outward normal points away from it
    bool convex = true;

    int indexOf(const TopoDS_Shape& edge) const
    {
        for (int k = 0; k < 3; ++k) {
            if (edges[k].IsSame(edge)) {
                return k;
            }
        }
        return -1;
    }

    /** Where the tool of edges[k] meets the tool of edges[j] when their sizes and dihedral angles
     * are equal: the bisector plane of the faces they don't share (it holds the third edge). On
     * edges[k]'s side a point is nearer to its own side face, so outside one round means outside
     * the other: the two tools are OCCT's miter
     */
    TrimPlane miter(int k, int j) const
    {
        gp_Vec m = gp_Vec(normals[j]) - gp_Vec(normals[k]);
        return {point, gp_Dir(m)};
    }

    /// The centre of the sphere of radius r tangent to the three faces, inside the trihedral
    gp_Pnt sphereCentre(double r) const
    {
        gp_XYZ a = normals[0].XYZ();
        gp_XYZ b = normals[1].XYZ();
        gp_XYZ c = normals[2].XYZ();
        double det = a.Dot(b.Crossed(c));
        gp_XYZ offset = (b.Crossed(c) + c.Crossed(a) + a.Crossed(b)) * (r / det);
        return gp_Pnt(point.XYZ() + offset);
    }
};

/** Where a section ends on one of the faces, swept along the edge: the line or circle on which
 * the dress-up's new edge lies. Not valid when the circle shrinks to a point on its axis.
 */
struct FarSide
{
    bool valid = false;
    bool line = true;
    gp_Lin lin;
    gp_Circ circ;

    double distance(const gp_Pnt& point) const
    {
        return line ? lin.Distance(point) : circ.Distance(point);
    }
};

/// The tangent strip of a tool on one of the faces next to its edge
struct Strip
{
    TopoDS_Face face;
    /// The tool's faces on it
    std::vector<TopoDS_Shape> contacts;
    FarSide farSide;
    /// The section's extent on the face, across the edge
    double width = 0.0;
};

/** One piece of material removed (cut) or added (fused) (5.6, interface point 2).
 *
 * The tools of one dress-up are interior-disjoint (interface point 7), so the volume of the
 * result must equal the base's minus the cut tools' closed-form volumes plus the fused ones'.
 */
struct Tool
{
    TopoDS_Shape solid;
    /// Cut from the base (a convex edge) or fused to it (a concave edge)
    bool cut = true;
    /// The selected edge (or, for corner pieces, the vertex) whose fillet the tool's faces are
    /// named after: a corner piece's faces are generated by the vertex, as OCCT's are (5.5)
    TopoDS_Shape source;
    /// The tool's volume in closed form, not measured
    double volume = 0.0;
    /// On the faces next to the source: an edge tool's two, in the order of EdgeData::faces; a
    /// corner piece's three
    std::vector<Strip> strips;
    /// The faces of the tool that lie on the faces adjacent to the edge: the result must not
    /// keep any part of them (each tangent strip must be backed by material, or by air)
    std::vector<TopoDS_Shape> contactFaces;
    /// The planes that bound the tool at the edge's free ends: a face of the tool left in such
    /// a plane is merged into the base's coplanar face (interface point 4)
    std::vector<TrimPlane> caps;
    /// The tool's faces in those planes: whatever they become must be the end face's image (the
    /// end face covers them, or they merge into it)
    std::vector<TopoDS_Shape> capFaces;
    /// The planes of its ends at two-edge corners with unequal dihedral angles: the other edge's
    /// side face, which its faces there lie on. They join contactFaces: nothing of them may be
    /// left (the side face covers them, or the other edge's tool removes them)
    std::vector<TrimPlane> openEnds;
};

/** The common part of the two tools at a two-edge corner with unequal dihedral angles (convex
 * edges at a convex vertex), in closed form: its volume, and its area on the face that holds both
 * edges (where their tangent strips overlap).
 *
 * Both edges lie in that face, and each tool is a prism along its edge, so a slice parallel to the
 * face at the depth z cuts each tool in a band along its edge: from the trace of its side face to
 * the round (or the chamfer), w(z) wide. Two bands crossing at the plan angle phi share a
 * parallelogram of w_a w_b / sin phi, and the volume is its integral over the depth while both
 * bands are there:
 * - fillet, z = r (1 - cos theta): w = t - r sin theta - r (1 - cos theta) cot alpha, from the
 *   tangent length t at theta = 0 to 0 at the tangent line on the side face, theta = pi - alpha
 * - chamfer by equal distances d: w = d - z / sin alpha, from d at z = 0 to 0 at z = d sin alpha
 */
struct Overlap
{
    TopoDS_Shape edges[2];
    TopoDS_Face face;
    double area = 0.0;
    double volume = 0.0;
};

Overlap overlapOf(
    bool fillet,
    double size,
    const double alpha[2],
    const double width[2],
    double phi
)
{
    Overlap overlap;
    double sinPhi = std::sin(phi);
    overlap.area = width[0] * width[1] / sinPhi;
    if (fillet) {
        // w = A + B sin theta + C cos theta; the integral of w_a w_b sin theta, term by term
        double a[2], b[2], c[2];
        for (int i = 0; i < 2; ++i) {
            a[i] = width[i] - size / std::tan(alpha[i]);
            b[i] = -size;
            c[i] = size / std::tan(alpha[i]);
        }
        auto antiderivative = [&](double theta) {
            double s = std::sin(theta);
            double co = std::cos(theta);
            return -a[0] * a[1] * co
                + (a[0] * b[1] + b[0] * a[1]) * (theta / 2 - std::sin(2 * theta) / 4)
                + (a[0] * c[1] + c[0] * a[1]) * s * s / 2
                + b[0] * b[1] * (co * co * co / 3 - co)
                + (b[0] * c[1] + c[0] * b[1]) * s * s * s / 3 - c[0] * c[1] * co * co * co / 3;
        };
        double top = std::min(pi - alpha[0], pi - alpha[1]);
        overlap.volume = size * (antiderivative(top) - antiderivative(0.0)) / sinPhi;
    }
    else {
        double k0 = 1 / std::sin(alpha[0]);
        double k1 = 1 / std::sin(alpha[1]);
        double z = std::min(size * std::sin(alpha[0]), size * std::sin(alpha[1]));
        overlap.volume
            = (size * size * z - size * (k0 + k1) * z * z / 2 + k0 * k1 * z * z * z / 3) / sinPhi;
    }
    return overlap;
}

/// A selected edge, analysed
struct EdgeData
{
    TopoDS_Edge edge;
    TopoDS_Face faces[2];  // faces[0] carries the chamfer's first distance
    bool line = true;
    double first = 0.0;
    double last = 0.0;
    bool closed = false;
    gp_Pnt start;  // the points at first and last
    gp_Pnt end;
    gp_Circ circle;
    int planeFace = 0;  // circle: which of faces is the plane
    bool convex = true;
};

/// The maps the construction reads, built once
struct Context
{
    const TopoShape& base;
    const Request& request;
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
    TopTools_IndexedDataMapOfShapeListOfShape vertexFaces;
    TopTools_IndexedMapOfShape selected;
    double scale = 1.0;  // the base's size, for the half-spaces

    Context(const TopoShape& base, const Request& request)
        : base(base)
        , request(request)
    {
        const TopoDS_Shape& shape = base.getShape();
        TopExp::MapShapesAndUniqueAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
        TopExp::MapShapesAndUniqueAncestors(shape, TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
        TopExp::MapShapesAndUniqueAncestors(shape, TopAbs_VERTEX, TopAbs_FACE, vertexFaces);
        Bnd_Box box;
        BRepBndLib::Add(base.getShape(), box);
        if (!box.IsVoid()) {
            scale = std::sqrt(box.SquareExtent()) + 1.0;
        }
    }

    std::vector<TopoDS_Shape> list(const TopTools_IndexedDataMapOfShapeListOfShape& map,
                                   const TopoDS_Shape& key) const
    {
        std::vector<TopoDS_Shape> result;
        int index = map.FindIndex(key);
        if (index == 0) {
            return result;
        }
        for (const auto& shape : map.FindFromIndex(index)) {
            result.push_back(shape);
        }
        return result;
    }
};

EdgeData analyse(const Context& ctx, const TopoDS_Edge& edge)
{
    EdgeData data;
    data.edge = edge;
    auto faces = ctx.list(ctx.edgeFaces, edge);
    if (faces.size() != 2) {
        refuse("a selected edge has " + std::to_string(faces.size()) + " faces");
    }
    data.faces[0] = TopoDS::Face(faces[0]);
    data.faces[1] = TopoDS::Face(faces[1]);
    if (ctx.request.kind == Kind::Chamfer) {
        // The same reference face as makeElementChamfer gives OCCT
        TopoDS_Shape reference;
        if (ctx.request.flipDirection == Flip::flip) {
            auto ancestors = ctx.base.findAncestorsShapes(edge, TopAbs_FACE);
            if (!ancestors.empty()) {
                reference = ancestors.back();
            }
        }
        else {
            reference = ctx.base.findAncestorShape(edge, TopAbs_FACE);
        }
        if (reference.IsNull()) {
            refuse("no chamfer reference face");
        }
        if (reference.IsSame(data.faces[1])) {
            std::swap(data.faces[0], data.faces[1]);
        }
        else if (!reference.IsSame(data.faces[0])) {
            refuse("the chamfer reference face is not next to the edge");
        }
    }
    TopoDS_Vertex firstVertex;
    TopoDS_Vertex lastVertex;
    TopExp::Vertices(edge, firstVertex, lastVertex);
    data.closed = !firstVertex.IsNull() && firstVertex.IsSame(lastVertex);

    BRepAdaptor_Curve curve(edge);
    data.first = curve.FirstParameter();
    data.last = curve.LastParameter();
    data.start = curve.Value(data.first);
    data.end = curve.Value(data.last);
    BRepAdaptor_Surface s0(data.faces[0], Standard_False);
    BRepAdaptor_Surface s1(data.faces[1], Standard_False);
    if (curve.GetType() == GeomAbs_Line) {
        data.line = true;
        if (s0.GetType() != GeomAbs_Plane || s1.GetType() != GeomAbs_Plane) {
            refuse("a straight edge between faces that are not both planes");
        }
        if (data.start.Distance(data.end) < linearTolerance) {
            refuse("a degenerate edge");
        }
    }
    else if (curve.GetType() == GeomAbs_Circle) {
        data.line = false;
        data.circle = curve.Circle();
        auto countOf = [&](GeomAbs_SurfaceType type) {
            return (s0.GetType() == type ? 1 : 0) + (s1.GetType() == type ? 1 : 0);
        };
        int planes = countOf(GeomAbs_Plane);
        int cylinders = countOf(GeomAbs_Cylinder);
        if (planes != 1 || cylinders != 1) {
            refuse("a circular edge not between a plane and a cylinder");
        }
        data.planeFace = s0.GetType() == GeomAbs_Plane ? 0 : 1;
        const gp_Dir& axis = data.circle.Axis().Direction();
        gp_Pln plane = (data.planeFace == 0 ? s0 : s1).Plane();
        gp_Cylinder cylinder = (data.planeFace == 0 ? s1 : s0).Cylinder();
        if (!parallel(plane.Axis().Direction(), axis)
            || plane.Distance(data.circle.Location()) > linearTolerance) {
            refuse("a circular edge on a plane not normal to its axis");
        }
        if (!parallel(cylinder.Axis().Direction(), axis)
            || gp_Lin(cylinder.Axis()).Distance(data.circle.Location()) > linearTolerance
            || std::abs(cylinder.Radius() - data.circle.Radius()) > linearTolerance) {
            refuse("a circular edge on a cylinder that is not coaxial");
        }
    }
    else {
        refuse("a selected edge that is neither a line nor a circle");
    }
    // Convex when the second face turns away from the first's outward normal
    double middle = (data.first + data.last) / 2;
    gp_Pnt point = curve.Value(middle);
    gp_Dir inward1 = inwardIn(data.faces[1], edge, middle);
    data.convex = inward1.Dot(outwardNormal(data.faces[0], point)) < 0;
    return data;
}

/// The direction along the edge away from the vertex, and the vertex's parameter
gp_Dir awayFrom(const TopoDS_Edge& edge, const TopoDS_Vertex& vertex, double* parameter = nullptr)
{
    BRepAdaptor_Curve curve(edge);
    gp_Pnt at = BRep_Tool::Pnt(vertex);
    gp_Pnt point;
    gp_Vec tangent;
    double t = curve.FirstParameter();
    curve.D1(t, point, tangent);
    if (point.Distance(at) > BRep_Tool::Tolerance(vertex) + linearTolerance) {
        t = curve.LastParameter();
        curve.D1(t, point, tangent);
        tangent.Reverse();
    }
    if (parameter) {
        *parameter = t;
    }
    if (tangent.Magnitude() < linearTolerance) {
        refuse("degenerate edge tangent");
    }
    return gp_Dir(tangent);
}

struct VertexEnd
{
    VertexClass kind = VertexClass::Refuse;
    /// The planes that bound the tool here: one, but two at a chamfer's three-edge corner
    std::vector<TrimPlane> trims;
    TopoDS_Edge continuation;  // TangentContinuation: the other selected edge
    std::string reason;
};

/// The angle between the faces at the edge, through the material, at the parameter
double dihedralAt(const EdgeData& data, double parameter)
{
    gp_Dir a = inwardIn(data.faces[0], data.edge, parameter);
    gp_Dir b = inwardIn(data.faces[1], data.edge, parameter);
    return std::acos(std::clamp(a.Dot(b), -1.0, 1.0));
}

/// The corner at the vertex, or a reason why it is outside the scope (section 5.3)
std::optional<Corner> cornerAt(const Context& ctx, const TopoDS_Vertex& vertex, std::string& reason)
{
    auto edges = ctx.list(ctx.vertexEdges, vertex);
    auto faces = ctx.list(ctx.vertexFaces, vertex);
    if (edges.size() != 3 || faces.size() != 3) {
        reason = "a corner where " + std::to_string(edges.size()) + " edges meet";
        return std::nullopt;
    }
    Corner corner;
    corner.vertex = vertex;
    corner.point = BRep_Tool::Pnt(vertex);
    for (int k = 0; k < 3; ++k) {
        corner.edges[k] = TopoDS::Edge(edges[k]);
        if (BRepAdaptor_Curve(corner.edges[k]).GetType() != GeomAbs_Line) {
            reason = "a corner with an edge that is not straight";
            return std::nullopt;
        }
        corner.away[k] = awayFrom(corner.edges[k], vertex);
    }
    for (const auto& shape : faces) {
        const TopoDS_Face& face = TopoDS::Face(shape);
        BRepAdaptor_Surface surface(face, Standard_False);
        if (surface.GetType() != GeomAbs_Plane) {
            reason = "a corner with a face that is not a plane";
            return std::nullopt;
        }
        // The face holds two of the edges: it is the one opposite the third
        int opposite = -1;
        for (int k = 0; k < 3; ++k) {
            auto ofEdge = ctx.list(ctx.edgeFaces, corner.edges[k]);
            bool holds = std::any_of(ofEdge.begin(), ofEdge.end(), [&](const TopoDS_Shape& f) {
                return f.IsSame(face);
            });
            if (!holds) {
                if (opposite != -1) {
                    reason = "a corner face that holds one edge";
                    return std::nullopt;
                }
                opposite = k;
            }
        }
        if (opposite == -1 || !corner.faces[opposite].IsNull()) {
            reason = "a corner whose faces don't match its edges";
            return std::nullopt;
        }
        gp_Dir normal = surface.Plane().Axis().Direction();
        double along = normal.Dot(corner.away[opposite]);
        if (std::abs(along) < 1e-6) {
            reason = "a flat corner";
            return std::nullopt;
        }
        corner.faces[opposite] = face;
        corner.normals[opposite] = along > 0 ? normal : normal.Reversed();
        corner.convex = corner.convex
            && outwardNormal(face, corner.point).Dot(corner.normals[opposite]) < 0;
    }
    return corner;
}

/** The corner kinds of section 5.3, at a vertex where other selected edges meet the edge at an
 * angle: equal sizes (one size per dress-up; chamfers by equal distances) and one convexity; at a
 * two-edge corner equal dihedral angles; at a chamfer's three-edge corner a box corner. Anything
 * else keeps OCCT's error, since OCCT builds patches there (torus, B-spline) the tools don't
 */
VertexEnd classifyCorner(
    const Context& ctx,
    const std::vector<EdgeData>& all,
    const EdgeData& data,
    const TopoDS_Vertex& vertex,
    const std::vector<TopoDS_Edge>& otherSelected,
    VertexEnd end
)
{
    bool continued = end.kind == VertexClass::TangentContinuation;
    end.kind = VertexClass::Refuse;
    end.trims.clear();
    if (continued) {
        end.reason = "a corner at a tangent continuation";
        return end;
    }
    auto corner = cornerAt(ctx, vertex, end.reason);
    if (!corner) {
        return end;
    }
    std::vector<const EdgeData*> others;
    for (const auto& edge : otherSelected) {
        auto other = std::find_if(all.begin(), all.end(), [&](const EdgeData& d) {
            return d.edge.IsSame(edge);
        });
        if (other == all.end() || corner->indexOf(edge) < 0) {
            end.reason = "a corner edge that was not analysed";
            return end;
        }
        if (other->convex != data.convex) {
            end.reason = "a corner of mixed convexity";
            return end;
        }
        others.push_back(&*other);
    }
    const Request& request = ctx.request;
    bool chamfer = request.kind == Kind::Chamfer;
    if (chamfer) {
        bool equal = request.chamferType == ChamferType::equalDistance
            || (request.chamferType == ChamferType::twoDistances
                && std::abs(request.size1 - request.size2)
                    <= linearTolerance * std::max(1.0, request.size1));
        if (!equal) {
            end.reason = "a two-distance or distance-angle chamfer at a corner";
            return end;
        }
    }
    int k = corner->indexOf(data.edge);
    if (k < 0) {
        end.reason = "a corner without its edge";
        return end;
    }
    if (others.size() == 1) {
        double here = 0.0;
        double there = 0.0;
        awayFrom(data.edge, vertex, &here);
        awayFrom(others.front()->edge, vertex, &there);
        if (std::abs(dihedralAt(data, here) - dihedralAt(*others.front(), there))
            > angularTolerance) {
            // Where the edges or the vertex are concave, OCCT's rounds don't meet as the union
            // of the two tools (5.6, "Corner classes left out")
            if (!data.convex || !corner->convex) {
                end.reason = "a two-edge corner with unequal dihedral angles that is not convex";
                return end;
            }
            // The tool runs on to the plane of the face that holds the other edge, not this one
            end.kind = VertexClass::Corner2Unequal;
            end.trims = {{corner->point, corner->normals[k].Reversed()}};
            return end;
        }
        end.kind = VertexClass::Corner2;
        end.trims = {corner->miter(k, corner->indexOf(others.front()->edge))};
        return end;
    }
    if (!chamfer) {
        // The round ends where it meets the sphere: on the plane through the sphere's centre,
        // normal to the edge
        gp_Pnt centre = corner->sphereCentre(request.size1);
        end.kind = VertexClass::Corner3;
        end.trims = {{centre, corner->away[k].Reversed()}};
        return end;
    }
    // OCCT's corner triangle is reproduced at a box corner only (A15: other patches elsewhere)
    if (!data.convex) {
        end.reason = "a chamfer at a concave three-edge corner";
        return end;
    }
    for (int i = 0; i < 3; ++i) {
        if (std::abs(corner->normals[i].Dot(corner->normals[(i + 1) % 3])) > angularTolerance) {
            end.reason = "a chamfer at a three-edge corner that is not square";
            return end;
        }
    }
    end.kind = VertexClass::Corner3;
    for (int j = 0; j < 3; ++j) {
        if (j != k) {
            end.trims.push_back(corner->miter(k, j));
        }
    }
    return end;
}

/// 5.6, interface point 1: how the selected edge ends at the vertex
VertexEnd classify(
    const Context& ctx,
    const std::vector<EdgeData>& all,
    const EdgeData& data,
    const TopoDS_Vertex& vertex
)
{
    VertexEnd end;
    auto edges = ctx.list(ctx.vertexEdges, vertex);
    auto faces = ctx.list(ctx.vertexFaces, vertex);
    // A vertex inside a curve, between two edges on the same two faces (a circle split at its
    // cylinder's seam, as a fused stadium's half circle): only a tangent continuation
    bool insideCurve = edges.size() == 2 && faces.size() == 2;
    if (!insideCurve && (edges.size() != 3 || faces.size() != 3)) {
        end.reason = "a vertex where " + std::to_string(edges.size()) + " edges meet";
        return end;
    }
    gp_Dir away = awayFrom(data.edge, vertex);
    gp_Pnt point = BRep_Tool::Pnt(vertex);
    std::vector<TopoDS_Edge> otherSelected;
    for (const auto& shape : edges) {
        const TopoDS_Edge& other = TopoDS::Edge(shape);
        if (other.IsSame(data.edge)) {
            continue;
        }
        bool isSelected = ctx.selected.Contains(other);
        gp_Dir otherAway = awayFrom(other, vertex);
        if (otherAway.Dot(away) < -1 + angularTolerance) {
            if (!isSelected) {
                // OCCT would run the fillet on along the tangent chain
                end.reason = "a tangent chain onto an unselected edge";
                return end;
            }
            end.kind = VertexClass::TangentContinuation;
            end.continuation = other;
            end.trims = {{point, away.Reversed()}};
        }
        else if (isSelected) {
            otherSelected.push_back(other);
        }
    }
    if (insideCurve && end.kind != VertexClass::TangentContinuation) {
        end.reason = "a vertex where 2 edges meet at an angle";
        return end;
    }
    if (!otherSelected.empty()) {
        return classifyCorner(ctx, all, data, vertex, otherSelected, end);
    }
    if (end.kind == VertexClass::TangentContinuation) {
        return end;
    }
    // A free end, or an end against a wall: bounded by the plane of the end face
    TopoDS_Face endFace;
    for (const auto& shape : faces) {
        if (!shape.IsSame(data.faces[0]) && !shape.IsSame(data.faces[1])) {
            endFace = TopoDS::Face(shape);
        }
    }
    if (endFace.IsNull()) {
        end.reason = "no end face";
        return end;
    }
    BRepAdaptor_Surface surface(endFace, Standard_False);
    if (surface.GetType() != GeomAbs_Plane) {
        end.reason = "an end face that is not a plane";
        return end;
    }
    gp_Dir normal = surface.Plane().Axis().Direction();
    if (std::abs(normal.Dot(away)) < 1e-6) {
        end.reason = "an end face parallel to the edge";
        return end;
    }
    if (normal.Dot(away) > 0) {
        normal.Reverse();
    }
    end.kind = VertexClass::FreeEnd;
    end.trims = {{point, normal}};
    return end;
}

/// Where the line through the point along the direction meets the plane, as a parameter
double crossing(const TrimPlane& plane, const gp_Pnt& point, const gp_Dir& direction)
{
    gp_Vec normal(plane.normal);
    return gp_Vec(point, plane.point).Dot(normal) / gp_Vec(direction).Dot(normal);
}

Section sectionAt(const Context& ctx, const EdgeData& data, double parameter)
{
    gp_Pnt point = BRepAdaptor_Curve(data.edge).Value(parameter);
    return makeSection(
        point,
        inwardIn(data.faces[0], data.edge, parameter),
        inwardIn(data.faces[1], data.edge, parameter),
        ctx.request
    );
}

/// The circle about the axis through the point
FarSide circleAbout(const gp_Ax1& axis, const gp_Pnt& point)
{
    FarSide side;
    side.line = false;
    gp_Vec z(axis.Direction());
    gp_Pnt centre = axis.Location().Translated(z * gp_Vec(axis.Location(), point).Dot(z));
    double radius = centre.Distance(point);
    if (radius > linearTolerance) {
        side.valid = true;
        side.circ = gp_Circ(gp_Ax2(centre, axis.Direction()), radius);
    }
    return side;
}

/** A prism along a straight edge, bounded by the planes at its ends. None where those planes
 * leave it no length (the rounds of a slab's vertical edges at r = t / 2 vanish into the sphere
 * patches): the tool is dropped, so that the result gets no degenerate face (5.2)
 */
std::optional<Tool> lineTool(const Context& ctx, const EdgeData& data, const VertexEnd ends[2])
{
    gp_Dir direction(gp_Vec(data.start, data.end));
    double length = data.start.Distance(data.end);
    Section section = sectionAt(ctx, data, data.first);
    // Where the tool begins and ends along the edge, at a point of the section: at the last of
    // the planes at its start, and the first of those at its end
    auto beginAt = [&](const gp_Pnt& p) {
        double s = -std::numeric_limits<double>::infinity();
        for (const auto& plane : ends[0].trims) {
            s = std::max(s, crossing(plane, p, direction));
        }
        return s;
    };
    auto finishAt = [&](const gp_Pnt& p) {
        double s = std::numeric_limits<double>::infinity();
        for (const auto& plane : ends[1].trims) {
            s = std::min(s, crossing(plane, p, direction));
        }
        return s;
    };
    // The length is concave over the section (a minimum minus a maximum of linear functions),
    // so its least value is at a corner of the section's hull, whose corners are its own
    std::vector<gp_Pnt> hull = {section.corner, section.ends[0], section.ends[1]};
    double from = 0.0;
    double to = length;
    double longest = 0.0;
    for (const auto& p : hull) {
        double s0 = beginAt(p);
        double s1 = finishAt(p);
        if (s1 - s0 < -linearTolerance) {
            refuse("the planes at the ends of an edge cross inside its tool");
        }
        longest = std::max(longest, s1 - s0);
        from = std::min(from, s0);
        to = std::max(to, s1);
    }
    if (longest <= linearTolerance) {
        return std::nullopt;
    }
    Tool tool;
    tool.source = data.edge;
    tool.cut = data.convex;
    if (ends[0].trims.size() == 1 && ends[1].trims.size() == 1) {
        // Each plane at the parameter where the section's centroid crosses it: exact for a prism
        // cut by two planes that don't cross inside it
        gp_Pnt centroid = section.corner.Translated(section.centroid);
        tool.volume = section.area * (finishAt(centroid) - beginAt(centroid));
    }
    else if (!section.fillet) {
        // A chamfer's tool at a box corner: a convex polyhedron, between the faces, the chamfer's
        // plane and the planes at its ends
        auto away = [&](const gp_Pnt& on, const gp_Vec& along, const gp_Pnt& inside) {
            gp_Dir normal(gp_Vec(direction).Crossed(along));
            return gp_Vec(on, inside).Dot(gp_Vec(normal)) > 0 ? TrimPlane {on, normal.Reversed()}
                                                              : TrimPlane {on, normal};
        };
        std::vector<TrimPlane> planes {
            away(section.corner, gp_Vec(section.inward[0]), section.ends[1]),
            away(section.corner, gp_Vec(section.inward[1]), section.ends[0]),
            away(section.ends[0], gp_Vec(section.ends[0], section.ends[1]), section.corner)
        };
        for (int i = 0; i < 2; ++i) {
            planes.insert(planes.end(), ends[i].trims.begin(), ends[i].trims.end());
        }
        // A second closed form, independent of the planes: the prism from the vertex at each
        // box corner (the only three-edge chamfer corner accepted), less d^3 / 4 there, or from
        // where the centroid crosses a single plane
        gp_Pnt centroid = section.corner.Translated(section.centroid);
        double begin = ends[0].trims.size() == 2 ? 0.0 : beginAt(centroid);
        double finish = ends[1].trims.size() == 2 ? length : finishAt(centroid);
        double d = section.length[0];
        int boxCorners = (ends[0].trims.size() == 2 ? 1 : 0) + (ends[1].trims.size() == 2 ? 1 : 0);
        tool.volume = section.area * (finish - begin) - boxCorners * d * d * d / 4;
        double polytope = polytopeOf(planes).volume;
        if (std::abs(polytope - tool.volume) > volumeTolerance * tool.volume) {
            refuse("a chamfer's tool at a corner differs from its closed form");
        }
    }
    else {
        refuse("a round bounded by two planes at an end");
    }
    tool.strips.resize(2);
    for (int k = 0; k < 2; ++k) {
        tool.strips[k].face = data.faces[k];
        tool.strips[k].width = section.length[k];
        tool.strips[k].farSide.valid = true;
        tool.strips[k].farSide.lin = gp_Lin(section.ends[k], direction);
    }
    // An end bounded by one plane normal to the edge needs no trim: the prism ends there
    bool trim[2];
    for (int i = 0; i < 2; ++i) {
        trim[i] = ends[i].trims.size() != 1 || !parallel(ends[i].trims.front().normal, direction);
    }
    double margin = 1.0 + section.length[0] + section.length[1];
    double begin = trim[0] ? from - margin : beginAt(section.corner);
    double finish = trim[1] ? to + margin : finishAt(section.corner);
    if (!trim[0] && std::abs(begin) <= linearTolerance) {
        begin = 0.0;
    }
    if (!trim[1] && std::abs(finish - length) <= linearTolerance) {
        finish = length;
    }
    gp_Vec step(direction);
    TopoDS_Face face = section.face();
    gp_Trsf move;
    move.SetTranslation(step * begin);
    face = TopoDS::Face(face.Moved(TopLoc_Location(move)));
    TopoDS_Shape solid
        = BRepPrimAPI_MakePrism(face, step * (finish - begin), Standard_True).Shape();
    for (int i = 0; i < 2; ++i) {
        if (!trim[i]) {
            continue;
        }
        for (const auto& plane : ends[i].trims) {
            BRepAlgoAPI_Cut cut(solid, halfSpaceBeyond(plane, 4 * ctx.scale + 4 * margin));
            if (!cut.IsDone() || cut.HasErrors()) {
                refuse("trimming a tool failed");
            }
            solid = cut.Shape();
        }
    }
    tool.solid = solid;
    for (int i = 0; i < 2; ++i) {
        if (ends[i].kind == VertexClass::FreeEnd) {
            tool.caps.push_back(ends[i].trims.front());
        }
        else if (ends[i].kind == VertexClass::Corner2Unequal) {
            tool.openEnds.push_back(ends[i].trims.front());
        }
    }
    return tool;
}

/** The piece at a three-edge corner (5.2), between the ends of the three edge tools, its faces
 * generated by the vertex:
 * - a fillet's corner cell: the trihedral cut by the three planes through the sphere's centre
 *   normal to the edges, minus the ball; its volume is the polyhedron's minus Omega r^3 / 3, with
 *   Omega = 2 pi - (the sum of the face angles at the vertex) the solid angle at the centre (5.4)
 * - a chamfer's corner tetrahedron at a box corner: between the three chamfer planes and the
 *   plane through the points where the chamfer lines meet on each face (OCCT's corner triangle)
 */
Tool cornerTool(const Context& ctx, const Corner& corner, bool cut)
{
    double size = ctx.request.size1;
    const gp_Pnt& p = corner.point;
    std::vector<TrimPlane> planes;
    Tool tool;
    tool.source = corner.vertex;
    tool.cut = cut;
    if (ctx.request.kind == Kind::Fillet) {
        gp_Pnt centre = corner.sphereCentre(size);
        for (int k = 0; k < 3; ++k) {
            planes.push_back({p, corner.normals[k].Reversed()});
        }
        for (int k = 0; k < 3; ++k) {
            planes.push_back({centre, corner.away[k]});
        }
        Polytope cell = polytopeOf(planes);
        double faceAngles = 0.0;
        for (int k = 0; k < 3; ++k) {
            faceAngles += corner.away[k].Angle(corner.away[(k + 1) % 3]);
        }
        double omega = 2 * pi - faceAngles;
        tool.volume = cell.volume - omega * size * size * size / 3;
        // The sphere's poles and seam away from the patch, so that its face isn't split (5.2)
        gp_Dir w(gp_Vec(centre, p));
        gp_Dir axis = std::abs(w.X()) < 0.9 ? w.Crossed(gp::DX()) : w.Crossed(gp::DY());
        TopoDS_Shape ball = BRepPrimAPI_MakeSphere(gp_Ax2(centre, axis, w.Reversed()), size).Shape();
        BRepAlgoAPI_Cut minus(solidOf(cell, planes), ball);
        if (!minus.IsDone() || minus.HasErrors()) {
            refuse("building a corner cell failed");
        }
        tool.solid = minus.Shape();
        // Its faces on the corner's faces, which the result must not keep
        tool.strips.resize(3);
        for (int k = 0; k < 3; ++k) {
            tool.strips[k].face = corner.faces[k];
            tool.strips[k].width = size;
        }
    }
    else {
        // The tetrahedron touches the corner's faces at its corners only: no strips
        // The edges of a box corner are square to each other
        gp_Vec a[3] = {gp_Vec(corner.away[0]), gp_Vec(corner.away[1]), gp_Vec(corner.away[2])};
        for (int k = 0; k < 3; ++k) {
            const gp_Vec& i = a[(k + 1) % 3];
            const gp_Vec& j = a[(k + 2) % 3];
            planes.push_back({p.Translated(i * size), gp_Dir(-(i + j))});
        }
        planes.push_back({p.Translated((a[0] + a[1]) * size), gp_Dir(a[0] + a[1] + a[2])});
        Polytope tetrahedron = polytopeOf(planes);
        // A second closed form, independent of the planes: the tetrahedron with the corners
        // d (1, 1, 0), d (1, 0, 1), d (0, 1, 1) and d (1, 1, 1) / 2 in the box corner's frame
        tool.volume = size * size * size / 12;
        if (std::abs(tetrahedron.volume - tool.volume) > volumeTolerance * tool.volume) {
            refuse("a corner tetrahedron differs from its closed form");
        }
        tool.solid = solidOf(tetrahedron, planes);
    }
    return tool;
}

/// A revolution about the axis of a circular edge, between the meridian planes at its ends
Tool circleTool(const Context& ctx, const EdgeData& data, const VertexEnd ends[2])
{
    const gp_Circ& circle = data.circle;
    gp_Ax1 axis = circle.Axis();
    const gp_Dir& z = axis.Direction();
    double span = data.closed ? 2 * pi : data.last - data.first;
    if (span <= angularTolerance || span > 2 * pi + angularTolerance) {
        refuse("a degenerate arc");
    }
    for (int i = 0; i < 2 && !data.closed; ++i) {
        const TrimPlane& plane = ends[i].trims.front();
        if (std::abs(plane.normal.Dot(z)) > angularTolerance
            || gp_Pln(plane.point, plane.normal).Distance(circle.Location()) > linearTolerance) {
            refuse("the plane at the end of an arc does not contain its axis");
        }
    }
    Section section = sectionAt(ctx, data, data.first);
    // The inward directions are radial and axial: snap them
    gp_Dir radial(gp_Vec(circle.Location(), section.corner));
    for (auto& d : section.inward) {
        double r = d.Dot(radial);
        double a = d.Dot(z);
        if (std::abs(r) > 1 - 1e-6) {
            d = r > 0 ? radial : radial.Reversed();
        }
        else if (std::abs(a) > 1 - 1e-6) {
            d = a > 0 ? z : z.Reversed();
        }
        else {
            refuse("the faces at a circular edge are not normal to each other");
        }
    }
    section = makeSection(section.corner, section.inward[0], section.inward[1], ctx.request);
    gp_Vec toCorner(circle.Location(), section.corner);
    double centroidRadius = toCorner.Dot(gp_Vec(radial)) + section.centroid.Dot(gp_Vec(radial));
    Tool tool;
    tool.source = data.edge;
    tool.cut = data.convex;
    tool.volume = section.area * centroidRadius * span;
    tool.strips.resize(2);
    for (int k = 0; k < 2; ++k) {
        tool.strips[k].face = data.faces[k];
        tool.strips[k].width = section.length[k];
        tool.strips[k].farSide = circleAbout(axis, section.ends[k]);
    }
    TopoDS_Shape solid;
    if (!section.fillet) {
        solid = BRepPrimAPI_MakeRevol(section.face(), axis, span, Standard_True).Shape();
    }
    else {
        // The square corner, end, centre, end revolved, minus the torus (or sphere) about the
        // centre's circle: the round face is analytic, with its seam where the circle's is
        BRepBuilderAPI_MakePolygon square(
            section.corner,
            section.ends[0],
            section.centre,
            section.ends[1],
            Standard_True
        );
        TopoDS_Face face = BRepBuilderAPI_MakeFace(square.Wire(), Standard_True).Face();
        TopoDS_Shape ring = BRepPrimAPI_MakeRevol(face, axis, span, Standard_True).Shape();
        double major = gp_Vec(circle.Location(), section.centre).Dot(gp_Vec(radial));
        gp_Pnt axisPoint = circle.Location().Translated(
            gp_Vec(z) * gp_Vec(circle.Location(), section.centre).Dot(gp_Vec(z))
        );
        gp_Ax2 frame(axisPoint, z, circle.XAxis().Direction());
        TopoDS_Shape round;
        if (std::abs(major) <= linearTolerance) {
            round = BRepPrimAPI_MakeSphere(frame, section.radius).Shape();
        }
        else if (major < section.radius + linearTolerance) {
            // A spindle torus: not built yet
            refuse("a fillet whose torus crosses its axis");
        }
        else {
            round = BRepPrimAPI_MakeTorus(frame, major, section.radius).Shape();
        }
        BRepAlgoAPI_Cut cut(ring, round);
        if (!cut.IsDone() || cut.HasErrors()) {
            refuse("building a revolved tool failed");
        }
        solid = cut.Shape();
    }
    tool.solid = solid;
    for (int i = 0; i < 2 && !data.closed; ++i) {
        if (ends[i].kind == VertexClass::FreeEnd) {
            tool.caps.push_back(ends[i].trims.front());
        }
    }
    return tool;
}

bool inPlane(const TopoDS_Shape& shape, const TrimPlane& plane)
{
    gp_Pln pln(plane.point, plane.normal);
    for (TopExp_Explorer it(shape, TopAbs_VERTEX); it.More(); it.Next()) {
        if (pln.Distance(BRep_Tool::Pnt(TopoDS::Vertex(it.Current()))) > linearTolerance) {
            return false;
        }
    }
    if (shape.ShapeType() == TopAbs_FACE) {
        BRepAdaptor_Surface surface(TopoDS::Face(shape), Standard_False);
        return surface.GetType() == GeomAbs_Plane
            && parallel(surface.Plane().Axis().Direction(), plane.normal);
    }
    return true;
}

/// The tool's faces on the faces next to its source, and in the planes of its caps
void findContactFaces(Tool& tool)
{
    for (TopExp_Explorer it(tool.solid, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face& face = TopoDS::Face(it.Current());
        for (auto& strip : tool.strips) {
            if (sameDomain(face, strip.face)) {
                tool.contactFaces.push_back(face);
                strip.contacts.push_back(face);
            }
        }
        for (const auto& cap : tool.caps) {
            if (inPlane(face, cap)) {
                tool.capFaces.push_back(face);
                break;
            }
        }
        for (const auto& end : tool.openEnds) {
            if (inPlane(face, end)) {
                tool.contactFaces.push_back(face);
                break;
            }
        }
    }
}

/// The common part of two shapes (faces, or solids), without changing either
TopoDS_Shape commonOf(const TopoDS_Shape& shape, const TopoDS_Shape& other)
{
    TopTools_ListOfShape arguments;
    arguments.Append(shape);
    TopTools_ListOfShape tools;
    tools.Append(other);
    BRepAlgoAPI_Common common;
    common.SetArguments(arguments);
    common.SetTools(tools);
    common.SetNonDestructive(Standard_True);
    common.SetRunParallel(Standard_False);
    common.Build();
    if (!common.IsDone() || common.HasErrors()) {
        refuse("intersecting a tool with the base failed");
    }
    return common.Shape();
}

double perimeterOf(const TopoDS_Shape& face)
{
    GProp_GProps props;
    BRepGProp::LinearProperties(face, props);
    return props.Mass();
}

/// Areas this close are equal: the boundary moved by a little over the linear tolerance
double areaToleranceOf(const TopoDS_Shape& face)
{
    return 10 * linearTolerance * perimeterOf(face);
}

/** A strip's areas this close are equal: its far side moved by a little over the linear
 * tolerance, i.e. along its length on the edge (area over width). Not the perimeter, which on a
 * short edge is mostly the strip's width and would let a far side run off its face unseen
 */
double areaToleranceOf(const TopoDS_Shape& contact, const Strip& strip)
{
    return 10 * linearTolerance * areaOf(contact) / strip.width;
}

/// The edge lies on the line or circle (exact for lines and circles: three points decide)
bool liesOn(const TopoDS_Edge& edge, const FarSide& side)
{
    BRepAdaptor_Curve curve(edge);
    if (curve.GetType() != GeomAbs_Line && curve.GetType() != GeomAbs_Circle) {
        return false;
    }
    double tolerance = std::max(linearTolerance, BRep_Tool::Tolerance(edge));
    double first = curve.FirstParameter();
    double last = curve.LastParameter();
    for (double t : {first, (first + last) / 2, last}) {
        if (side.distance(curve.Value(t)) > tolerance) {
            return false;
        }
    }
    return true;
}

bool coincide(const FarSide& a, const FarSide& b)
{
    if (a.line != b.line) {
        return false;
    }
    if (a.line) {
        return parallel(a.lin.Direction(), b.lin.Direction())
            && a.lin.Distance(b.lin.Location()) < linearTolerance;
    }
    return parallel(a.circ.Axis().Direction(), b.circ.Axis().Direction())
        && a.circ.Location().Distance(b.circ.Location()) < linearTolerance
        && std::abs(a.circ.Radius() - b.circ.Radius()) < linearTolerance;
}

/** The tangent strips (section 2a), checked before any Boolean, with errors linear in the size:
 * each lies on its face, and no two overlap. A dress-up slightly too big for its faces passes the
 * volume checks, whose error grows with the square or cube of the excess.
 *
 * At the limit (Request::limitOnly) one strip's far side must also land on an edge of its face or
 * on another strip's far side, or the strips must cover a face whole: the dress-ups OCCT refuses
 * and the construction is for. Anything else OCCT refuses keeps OCCT's error.
 *
 * The strips of the two tools at a two-edge corner with unequal dihedral angles overlap on the face
 * that holds both edges by the closed form's parallelogram, and by nothing else.
 */
void checkStrips(
    const std::vector<Tool>& tools,
    const std::vector<Overlap>& overlaps,
    bool limitOnly
)
{
    struct OnFace
    {
        TopoDS_Face face;
        std::vector<const Strip*> strips;
        std::vector<const Tool*> owners;
    };
    std::vector<OnFace> faces;
    for (const auto& tool : tools) {
        for (const auto& strip : tool.strips) {
            auto group = std::find_if(faces.begin(), faces.end(), [&](const OnFace& f) {
                return f.face.IsSame(strip.face);
            });
            if (group == faces.end()) {
                faces.push_back({strip.face, {}, {}});
                group = std::prev(faces.end());
            }
            group->strips.push_back(&strip);
            group->owners.push_back(&tool);
        }
    }
    // The expected overlap of two tools' strips on the face
    auto expectedOverlap = [&](const Tool* a, const Tool* b, const TopoDS_Face& face) {
        for (const auto& overlap : overlaps) {
            bool pair = (overlap.edges[0].IsSame(a->source) && overlap.edges[1].IsSame(b->source))
                || (overlap.edges[0].IsSame(b->source) && overlap.edges[1].IsSame(a->source));
            if (pair && overlap.face.IsSame(face)) {
                return overlap.area;
            }
        }
        return 0.0;
    };
    bool atLimit = false;
    for (const auto& group : faces) {
        double covered = 0.0;
        for (const auto* strip : group.strips) {
            if (strip->contacts.empty()) {
                refuse("a tool has no face on a face next to its edge");
            }
            for (const auto& contact : strip->contacts) {
                double area = areaOf(contact);
                double tolerance = areaToleranceOf(contact, *strip);
                if (area - areaOf(commonOf(group.face, contact)) > tolerance) {
                    refuse("a tangent strip runs off its face");
                }
                covered += area;
            }
        }
        for (size_t i = 0; i < group.strips.size(); ++i) {
            for (size_t j = i + 1; j < group.strips.size(); ++j) {
                double expected = expectedOverlap(group.owners[i], group.owners[j], group.face);
                double common = 0.0;
                double summedTolerance = 0.0;
                for (const auto& mine : group.strips[i]->contacts) {
                    for (const auto& theirs : group.strips[j]->contacts) {
                        double tolerance = std::min(
                            areaToleranceOf(mine, *group.strips[i]),
                            areaToleranceOf(theirs, *group.strips[j])
                        );
                        double area = areaOf(commonOf(mine, theirs));
                        if (expected == 0.0 && area > tolerance) {
                            refuse("two tangent strips overlap");
                        }
                        common += area;
                        summedTolerance += tolerance;
                    }
                }
                if (std::abs(common - expected) > summedTolerance) {
                    refuse("two tangent strips at a corner overlap by " + describe(common)
                           + " instead of " + describe(expected));
                }
                covered -= expected;
            }
        }
        if (!limitOnly || atLimit) {
            continue;
        }
        if (areaOf(group.face) - covered <= areaToleranceOf(group.face)) {
            atLimit = true;
            continue;
        }
        for (const auto* strip : group.strips) {
            if (!strip->farSide.valid) {
                continue;
            }
            for (TopExp_Explorer it(group.face, TopAbs_EDGE); it.More() && !atLimit; it.Next()) {
                atLimit = liesOn(TopoDS::Edge(it.Current()), strip->farSide);
            }
            for (const auto* other : group.strips) {
                if (other != strip && other->farSide.valid
                    && coincide(strip->farSide, other->farSide)) {
                    atLimit = true;
                }
            }
        }
    }
    if (limitOnly && !atLimit) {
        refuse("not at the limit: no new edge lands on an existing one, and no face vanishes");
    }
}

/// One step of the construction and its history
struct Stage
{
    Handle(BRepTools_History) history;
    TopTools_IndexedMapOfShape present;  // the vertices, edges and faces of its result

    Stage(const Handle(BRepTools_History) & history, const TopoDS_Shape& result)
        : history(history)
    {
        TopExp::MapShapes(result, TopAbs_VERTEX, present);
        TopExp::MapShapes(result, TopAbs_EDGE, present);
        TopExp::MapShapes(result, TopAbs_FACE, present);
    }

    std::vector<TopoDS_Shape> images(const TopoDS_Shape& shape) const
    {
        std::vector<TopoDS_Shape> result;
        if (!history.IsNull() && BRepTools_History::IsSupportedType(shape)) {
            if (history->IsRemoved(shape)) {
                return result;
            }
            for (const auto& modified : history->Modified(shape)) {
                if (present.Contains(modified)) {
                    result.push_back(modified);
                }
            }
            if (!result.empty()) {
                return result;
            }
        }
        if (present.Contains(shape)) {
            result.push_back(shape);
        }
        return result;
    }
};

/// The shapes that the stages, from the first one given, turn the shape into
std::vector<TopoDS_Shape> imagesThrough(
    const std::vector<Stage>& stages,
    size_t from,
    const TopoDS_Shape& shape
)
{
    std::vector<TopoDS_Shape> current = {shape};
    for (size_t i = from; i < stages.size(); ++i) {
        std::vector<TopoDS_Shape> next;
        for (const auto& s : current) {
            for (const auto& image : stages[i].images(s)) {
                if (std::none_of(next.begin(), next.end(), [&](const TopoDS_Shape& n) {
                        return n.IsSame(image);
                    })) {
                    next.push_back(image);
                }
            }
        }
        current = std::move(next);
    }
    return current;
}

/** One Boolean stage, and its checks (5.6, interface point 5). The tools are interior-disjoint but
 * for the overlaps at unequal corners, counted once
 */
TopoDS_Shape applyTools(
    const TopoDS_Shape& shape,
    const std::vector<const Tool*>& tools,
    double overlaps,
    bool cut,
    std::vector<Stage>& stages
)
{
    TopTools_ListOfShape arguments;
    arguments.Append(shape);
    TopTools_ListOfShape toolShapes;
    double expected = -overlaps;
    for (const auto* tool : tools) {
        toolShapes.Append(tool->solid);
        expected += tool->volume;
    }
    std::unique_ptr<BRepAlgoAPI_BooleanOperation> operation;
    if (cut) {
        operation = std::make_unique<BRepAlgoAPI_Cut>();
    }
    else {
        operation = std::make_unique<BRepAlgoAPI_Fuse>();
    }
    operation->SetArguments(arguments);
    operation->SetTools(toolShapes);
    // The first stage's argument is the caller's base. (OCCT 8.0.1 then leaves the sphere of a
    // cylinder's top rounded at r = R invalid, which the checks refuse)
    operation->SetNonDestructive(Standard_True);
    operation->SetRunParallel(Standard_False);
    operation->Build();
    if (!operation->IsDone() || operation->HasErrors()) {
        refuse(cut ? "the cut failed" : "the fuse failed");
    }
    TopoDS_Shape result = operation->Shape();
    double change = volumeOf(result) - volumeOf(shape);
    if (cut) {
        change = -change;
    }
    if (std::abs(change - expected) > volumeTolerance * expected) {
        refuse(std::string(cut ? "the cut removed " : "the fuse added ") + describe(change)
               + " instead of " + describe(expected));
    }
    stages.emplace_back(operation->History(), result);
    for (const auto* tool : tools) {
        for (const auto& contact : tool->contactFaces) {
            if (!stages.back().images(contact).empty()) {
                refuse("a tool's face on a face next to its edge is left in the result");
            }
        }
    }
    return result;
}

/// The largest tolerance of the shape and its sub-shapes, at least linearTolerance
double largestTolerance(const TopoDS_Shape& shape)
{
    double tolerance = linearTolerance;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Face(it.Current())));
    }
    for (TopExp_Explorer it(shape, TopAbs_EDGE); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Edge(it.Current())));
    }
    for (TopExp_Explorer it(shape, TopAbs_VERTEX); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Vertex(it.Current())));
    }
    return tolerance;
}

/// Whether the edge is an exact section of its two faces: a line, circle or ellipse between
/// planes, cylinders and cones, which OCCT intersects analytically
bool exactSection(const TopoDS_Edge& edge, const TopTools_ListOfShape& faces)
{
    if (faces.Extent() != 2) {
        return false;
    }
    switch (BRepAdaptor_Curve(edge).GetType()) {
        case GeomAbs_Line:
        case GeomAbs_Circle:
        case GeomAbs_Ellipse:
            break;
        default:
            return false;
    }
    return std::all_of(faces.begin(), faces.end(), [](const TopoDS_Shape& face) {
        switch (BRepAdaptor_Surface(TopoDS::Face(face)).GetType()) {
            case GeomAbs_Plane:
            case GeomAbs_Cylinder:
            case GeomAbs_Cone:
                return true;
            default:
                return false;
        }
    });
}

/// A new edge, an exact section of its faces, whose tolerance grew past twice that of the faces
/// next to it, or null. A Boolean that merges a strip narrower than its fuzzy reach away (a
/// chamfer's top strip just under the limit, 2 (2 - d) wide; the tube's top ring between its
/// chamfered rims, two cones) raises the tolerance of the edge the strip collapses into, and the
/// result is then off by the strip's volume (ops#300, PR 286 verification, finding 1; ops#315).
/// An exact section keeps its faces' tolerance, so a grown one there is such a merge; the
/// sections of spheres and tori with other faces are approximated and grow legitimately (3e-7 to
/// 4e-7 on the stadium and the hexagon's corners). The faces' tolerance is that of each base or
/// tool face the face is an image of, with its edges and vertices, before the Booleans: a tolerance
/// elsewhere in the base (an earlier rounded corner, an imported part's edge) doesn't hide a merge,
/// nor does the merge's own raising of its faces'
TopoDS_Edge grownEdge(
    const TopoDS_Shape& result,
    const TopoDS_Shape& base,
    const TopTools_DataMapOfShapeReal& faceTolerances
)
{
    TopTools_IndexedMapOfShape baseEdges;
    TopExp::MapShapes(base, TopAbs_EDGE, baseEdges);
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(result, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    for (int i = 1; i <= edgeFaces.Extent(); ++i) {
        const TopoDS_Edge& edge = TopoDS::Edge(edgeFaces.FindKey(i));
        if (baseEdges.Contains(edge) || !exactSection(edge, edgeFaces(i))) {
            continue;
        }
        double faceTolerance = linearTolerance;
        for (const auto& face : edgeFaces(i)) {
            const double* tolerance = faceTolerances.Seek(face);
            faceTolerance = std::max(
                faceTolerance,
                tolerance ? *tolerance : BRep_Tool::Tolerance(TopoDS::Face(face))
            );
        }
        if (BRep_Tool::Tolerance(edge) > 2 * faceTolerance) {
            return edge;
        }
    }
    return {};
}

/// The construction; cornerCount receives how many corners it built
TopoDS_Shape construct(
    TopoShape& result,
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const Request& request,
    const char* op,
    int& cornerCount
)
{
    if (base.isNull() || countSolids(base.getShape()) != 1) {
        refuse("the base is not one solid");
    }
    double baseVolume = volumeOf(base.getShape());
    if (baseVolume <= 0) {
        refuse("the base has no volume");
    }
    if (request.size1 <= 0) {
        refuse("zero size");
    }
    double radiusTolerance = linearTolerance * std::max(1.0, request.size1);
    if (request.kind == Kind::Fillet && std::abs(request.size1 - request.size2) > radiusTolerance) {
        refuse("variable radius");
    }
    Context ctx(base, request);
    std::vector<EdgeData> data;
    for (const auto& edge : edges) {
        if (edge.isNull() || edge.getShape().ShapeType() != TopAbs_EDGE) {
            refuse("not an edge");
        }
        if (ctx.selected.Contains(edge.getShape())) {
            continue;
        }
        ctx.selected.Add(edge.getShape());
    }
    // OCCT runs a dress-up on along tangent chains, by its own angular tolerance: where it would
    // have reached an unselected edge, the construction (which stops there) differs from it
    for (const auto& edge : request.contour) {
        if (!ctx.selected.Contains(edge)) {
            refuse("OCCT's contour runs on along a tangent chain onto an unselected edge");
        }
    }
    for (int i = 1; i <= ctx.selected.Extent(); ++i) {
        data.push_back(analyse(ctx, TopoDS::Edge(ctx.selected(i))));
    }

    std::vector<Tool> tools;
    // Each tool's checks before any Boolean
    auto admit = [&](Tool&& tool) {
        if (countSolids(tool.solid) != 1) {
            refuse("a tool is not one solid");
        }
        double measured = volumeOf(tool.solid);
        if (std::abs(measured - tool.volume) > volumeTolerance * tool.volume) {
            refuse("a tool's volume " + describe(measured) + " differs from its closed form "
                   + describe(tool.volume));
        }
        findContactFaces(tool);
        // A fused tool fills air only: material under it would be fused twice, and the volume
        // checks after the cut could not tell (5.6, interface point 7)
        if (!tool.cut
            && volumeOf(commonOf(base.getShape(), tool.solid)) > volumeTolerance * tool.volume) {
            refuse("a fused tool overlaps the base's material");
        }
        tools.push_back(std::move(tool));
    };
    // The three-edge corners, each with its piece, of the convexity of its edges
    std::vector<std::pair<TopoDS_Vertex, bool>> corners;
    // The two-edge corners with unequal dihedral angles
    std::vector<TopoDS_Vertex> unequalCorners;
    // Every corner, for the Report-view line
    TopTools_IndexedMapOfShape cornerVertices;
    for (const auto& edgeData : data) {
        VertexEnd ends[2];
        if (!edgeData.closed) {
            TopoDS_Vertex vertices[2];
            TopExp::Vertices(edgeData.edge, vertices[0], vertices[1]);
            bool classified[2] = {false, false};
            for (int i = 0; i < 2; ++i) {
                // ends[0] at the first parameter
                double parameter = 0.0;
                awayFrom(edgeData.edge, vertices[i], &parameter);
                bool atFirst
                    = std::abs(parameter - edgeData.first) < std::abs(parameter - edgeData.last);
                int slot = atFirst ? 0 : 1;
                if (classified[slot]) {
                    refuse("the ends of a selected edge could not be told apart");
                }
                classified[slot] = true;
                ends[slot] = classify(ctx, data, edgeData, vertices[i]);
                VertexClass kind = ends[slot].kind;
                if (kind == VertexClass::Refuse) {
                    refuse(ends[slot].reason);
                }
                if (kind == VertexClass::Corner2 || kind == VertexClass::Corner2Unequal
                    || kind == VertexClass::Corner3) {
                    cornerVertices.Add(vertices[i]);
                }
                auto known = [&](const TopoDS_Vertex& v) {
                    return v.IsSame(vertices[i]);
                };
                if (kind == VertexClass::Corner2Unequal
                    && std::none_of(unequalCorners.begin(), unequalCorners.end(), known)) {
                    unequalCorners.push_back(vertices[i]);
                }
                if (kind == VertexClass::Corner3
                    && std::none_of(corners.begin(), corners.end(), [&](const auto& c) {
                           return c.first.IsSame(vertices[i]);
                       })) {
                    corners.emplace_back(vertices[i], edgeData.convex);
                }
                if (ends[slot].kind == VertexClass::TangentContinuation) {
                    // The two tools meet on one plane only if their sections there agree
                    auto other = std::find_if(data.begin(), data.end(), [&](const EdgeData& d) {
                        return d.edge.IsSame(ends[slot].continuation);
                    });
                    if (other == data.end()) {
                        refuse("a tangent edge that was not analysed");
                    }
                    double here = 0.0;
                    double there = 0.0;
                    awayFrom(edgeData.edge, vertices[i], &here);
                    awayFrom(other->edge, vertices[i], &there);
                    Section mine = sectionAt(ctx, edgeData, here);
                    Section theirs = sectionAt(ctx, *other, there);
                    double same = mine.ends[0].Distance(theirs.ends[0])
                        + mine.ends[1].Distance(theirs.ends[1]);
                    double swapped = mine.ends[0].Distance(theirs.ends[1])
                        + mine.ends[1].Distance(theirs.ends[0]);
                    if (other->convex != edgeData.convex
                        || std::min(same, swapped) > linearTolerance) {
                        refuse("tangent edges whose sections differ");
                    }
                }
            }
        }
        if (edgeData.line) {
            if (auto tool = lineTool(ctx, edgeData, ends)) {
                admit(std::move(*tool));
            }
        }
        else {
            admit(circleTool(ctx, edgeData, ends));
        }
    }
    for (const auto& [vertex, convex] : corners) {
        std::string reason;
        auto corner = cornerAt(ctx, vertex, reason);
        if (!corner) {
            refuse(reason);
        }
        admit(cornerTool(ctx, *corner, convex));
    }
    // The two tools at each unequal corner overlap there; both are cut (convex edges)
    std::vector<Overlap> overlaps;
    for (const auto& vertex : unequalCorners) {
        std::string reason;
        auto corner = cornerAt(ctx, vertex, reason);
        if (!corner) {
            refuse(reason);
        }
        const EdgeData* pair[2] = {nullptr, nullptr};
        int third = -1;
        for (int k = 0; k < 3; ++k) {
            auto it = std::find_if(data.begin(), data.end(), [&](const EdgeData& d) {
                return d.edge.IsSame(corner->edges[k]);
            });
            if (it == data.end()) {
                third = k;
            }
            else {
                (pair[0] ? pair[1] : pair[0]) = &*it;
            }
        }
        if (third < 0 || !pair[0] || !pair[1]) {
            refuse("an unequal corner without two selected edges");
        }
        for (const auto* edgeData : pair) {
            if (std::none_of(tools.begin(), tools.end(), [&](const Tool& t) {
                    return t.source.IsSame(edgeData->edge);
                })) {
                refuse("a tool at an unequal corner has no length");
            }
        }
        const TopoDS_Face& shared = corner->faces[third];
        double alpha[2];
        double width[2];
        for (int i = 0; i < 2; ++i) {
            double parameter = 0.0;
            awayFrom(pair[i]->edge, vertex, &parameter);
            alpha[i] = dihedralAt(*pair[i], parameter);
            Section section = sectionAt(ctx, *pair[i], parameter);
            width[i] = section.length[pair[i]->faces[0].IsSame(shared) ? 0 : 1];
        }
        double phi = corner->away[corner->indexOf(pair[0]->edge)].Angle(
            corner->away[corner->indexOf(pair[1]->edge)]
        );
        Overlap overlap
            = overlapOf(request.kind == Kind::Fillet, request.size1, alpha, width, phi);
        overlap.edges[0] = pair[0]->edge;
        overlap.edges[1] = pair[1]->edge;
        overlap.face = shared;
        overlaps.push_back(overlap);
    }
    double overlapVolume = 0.0;
    for (const auto& overlap : overlaps) {
        overlapVolume += overlap.volume;
    }
    checkStrips(tools, overlaps, request.limitOnly);

    // The tools' faces' tolerances before the Booleans, for the check for merged faces: a merge
    // raises those of its images
    std::vector<std::vector<std::pair<TopoDS_Shape, double>>> toolFaceTolerances(tools.size());
    for (size_t i = 0; i < tools.size(); ++i) {
        for (TopExp_Explorer it(tools[i].solid, TopAbs_FACE); it.More(); it.Next()) {
            toolFaceTolerances[i].emplace_back(it.Current(), largestTolerance(it.Current()));
        }
    }

    std::vector<Stage> stages;
    std::vector<size_t> toolStage(tools.size(), 0);
    TopoDS_Shape shape = base.getShape();
    for (bool cut : {true, false}) {
        std::vector<const Tool*> group;
        for (size_t i = 0; i < tools.size(); ++i) {
            if (tools[i].cut == cut) {
                group.push_back(&tools[i]);
                toolStage[i] = stages.size();
            }
        }
        if (!group.empty()) {
            shape = applyTools(shape, group, cut ? overlapVolume : 0.0, cut, stages);
        }
    }

    // The faces of the tools left in the planes of free ends merge into the base's coplanar
    // faces, as OCCT's fillet extends those (5.6, interface point 4)
    std::vector<TrimPlane> caps;
    for (const auto& tool : tools) {
        caps.insert(caps.end(), tool.caps.begin(), tool.caps.end());
    }
    TopTools_IndexedMapOfShape baseImages;
    auto collectBaseImages = [&]() {
        baseImages.Clear();
        for (auto type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
            for (TopExp_Explorer it(base.getShape(), type); it.More(); it.Next()) {
                for (const auto& image : imagesThrough(stages, 0, it.Current())) {
                    baseImages.Add(image);
                }
            }
        }
    };
    if (!caps.empty()) {
        collectBaseImages();
        NCollection_Map<TopoDS_Shape, TopTools_ShapeMapHasher> keep;
        TopTools_IndexedMapOfShape unlocked;
        for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
            const TopoDS_Shape& face = it.Current();
            if (baseImages.Contains(face)) {
                continue;
            }
            for (const auto& cap : caps) {
                if (inPlane(face, cap)) {
                    TopExp::MapShapes(face, TopAbs_EDGE, unlocked);
                    break;
                }
            }
        }
        if (!unlocked.IsEmpty()) {
            TopTools_IndexedMapOfShape allEdges;
            TopExp::MapShapes(shape, TopAbs_EDGE, allEdges);
            for (int i = 1; i <= allEdges.Extent(); ++i) {
                if (!unlocked.Contains(allEdges(i))) {
                    keep.Add(allEdges(i));
                }
            }
            // Faces only: merging edges could also merge edges the base keeps apart
            ShapeUpgrade_UnifySameDomain unify(shape, false, true, false);
            unify.KeepShapes(keep);
            unify.Build();
            shape = unify.Shape();
            stages.emplace_back(unify.History(), shape);
        }
    }

    // The checks of the result
    if (countSolids(shape) != 1) {
        refuse("the result is not one solid");
    }
    if (!BRepCheck_Analyzer(shape).IsValid()) {
        refuse("the result is not valid");
    }
    if (!thinFace(shape, base.getShape()).IsNull()) {
        refuse("the result has a face of zero width");
    }
    TopTools_DataMapOfShapeReal faceTolerances;
    auto bindImages = [&](size_t from, const TopoDS_Shape& face, double tolerance) {
        for (const auto& image : imagesThrough(stages, from, face)) {
            if (double* known = faceTolerances.ChangeSeek(image)) {
                *known = std::max(*known, tolerance);
            }
            else {
                faceTolerances.Bind(image, tolerance);
            }
        }
    };
    // The base's as before OCCT's maker, which raises them in place
    for (TopExp_Explorer it(base.getShape(), TopAbs_FACE); it.More(); it.Next()) {
        const double* before = request.faceTolerances.Seek(it.Current());
        bindImages(0, it.Current(), before ? *before : largestTolerance(it.Current()));
    }
    for (size_t i = 0; i < tools.size(); ++i) {
        for (const auto& [face, tolerance] : toolFaceTolerances[i]) {
            bindImages(toolStage[i], face, tolerance);
        }
    }
    if (TopoDS_Edge grown = grownEdge(shape, base.getShape(), faceTolerances);
        !grown.IsNull()) {
        refuse("an edge's tolerance grew to " + describe(BRep_Tool::Tolerance(grown))
               + ": a face was merged away");
    }
    // One solid, as OCCT's fillet returns, not a compound holding it
    if (shape.ShapeType() != TopAbs_SOLID) {
        TopoDS_Shape solid = TopExp_Explorer(shape, TopAbs_SOLID).Current();
        TopTools_IndexedMapOfShape inShape;
        TopTools_IndexedMapOfShape inSolid;
        for (auto type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
            TopExp::MapShapes(shape, type, inShape);
            TopExp::MapShapes(solid, type, inSolid);
        }
        if (inShape.Extent() != inSolid.Extent()) {
            refuse("the result holds more than its solid");
        }
        shape = solid;
    }
    // The stages' checks don't cover the unification
    double cutVolume = 0.0;
    double fusedVolume = 0.0;
    for (const auto& tool : tools) {
        (tool.cut ? cutVolume : fusedVolume) += tool.volume;
    }
    cutVolume -= overlapVolume;
    double expected = baseVolume - cutVolume + fusedVolume;
    double measured = volumeOf(shape);
    if (std::abs(measured - expected) > volumeTolerance * (cutVolume + fusedVolume)) {
        refuse("the result's volume " + describe(measured) + " differs from its closed form "
               + describe(expected));
    }

    // The fillet's history, composed from the stages' (section 3): the base's elements are
    // modified into their images; whatever else a tool's faces become is generated by its edge
    collectBaseImages();
    // A tool's end in a free end's plane is covered by the end face (a cut leaves nothing of it),
    // or merges into it (a fused tool, or a cut against a wall); else it is a step or a notch
    for (size_t i = 0; i < tools.size(); ++i) {
        for (const auto& cap : tools[i].capFaces) {
            for (const auto& image : imagesThrough(stages, toolStage[i], cap)) {
                if (!baseImages.Contains(image)) {
                    refuse("the end face of a selected edge does not cover the end of its tool");
                }
            }
        }
    }
    ShapeMapper mapper;
    for (auto type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        for (TopExp_Explorer it(base.getShape(), type); it.More(); it.Next()) {
            const TopoDS_Shape& element = it.Current();
            auto images = imagesThrough(stages, 0, element);
            if (images.size() == 1 && images.front().IsSame(element)) {
                continue;
            }
            for (const auto& image : images) {
                mapper.insert(MappingStatus::Modified, element, image);
            }
        }
    }
    for (size_t i = 0; i < tools.size(); ++i) {
        for (TopExp_Explorer it(tools[i].solid, TopAbs_FACE); it.More(); it.Next()) {
            for (const auto& image : imagesThrough(stages, toolStage[i], it.Current())) {
                if (image.ShapeType() == TopAbs_FACE && !baseImages.Contains(image)) {
                    mapper.insert(MappingStatus::Generated, tools[i].source, image);
                }
            }
        }
    }
    result.makeShapeWithElementMap(shape, mapper, {base}, op);
    cornerCount = cornerVertices.Extent();
    return shape;
}

thread_local Recorder* innermostRecorder = nullptr;

}  // namespace

TopTools_DataMapOfShapeReal faceTolerances(const TopoDS_Shape& shape)
{
    TopTools_DataMapOfShapeReal tolerances;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        if (!tolerances.IsBound(it.Current())) {
            tolerances.Bind(it.Current(), largestTolerance(it.Current()));
        }
    }
    return tolerances;
}

TopoShape makerInput(const TopoShape& base, std::vector<TopoShape>& edges)
{
    TopoShape input(base.Tag, base.Hasher, base.getHistoryAlgorithm());
    // The topology alone: tolerances and curve representations live in the TShapes, and the
    // maker leaves the geometry alone
    input.makeElementCopy(base, nullptr, false);
    for (auto& edge : edges) {
        const int index = base.findShape(edge.getShape());
        if (index <= 0 || edge.getShape().ShapeType() != TopAbs_EDGE) {
            FC_THROWM(Base::CADKernelError, "edge does not belong to the shape");
        }
        edge = input.getSubTopoShape(TopAbs_EDGE, index);
    }
    return input;
}

TopoDS_Face thinFace(const TopoDS_Shape& result, const TopoDS_Shape& base)
{
    TopTools_IndexedMapOfShape baseFaces;
    TopExp::MapShapes(base, TopAbs_FACE, baseFaces);
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(result, TopAbs_FACE, faces);
    for (int i = 1; i <= faces.Extent(); ++i) {
        const TopoDS_Face& face = TopoDS::Face(faces(i));
        if (baseFaces.Contains(face)) {
            continue;
        }
        double tolerance = linearTolerance;
        for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
            tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Edge(it.Current())));
        }
        // The width w of the rectangle with the face's area A and perimeter P, the smaller root
        // of w^2 - P w / 2 + A = 0 (a strip's width, a square's side), in the form that doesn't
        // cancel (a face rounder than a square: A / (P / 4), a disc's diameter)
        double area = std::abs(areaOf(face));
        double quarter = perimeterOf(face) / 4;
        double width = area / (quarter + std::sqrt(std::max(0.0, quarter * quarter - area)));
        if (!(width >= tolerance)) {
            return face;
        }
    }
    return {};
}

Recorder::Recorder()
    : outer(innermostRecorder)
{
    innermostRecorder = this;
}

Recorder::~Recorder()
{
    innermostRecorder = outer;
}

void Recorder::add(int edges, int corners)
{
    if (Recorder* recorder = innermostRecorder) {
        ++recorder->builds;
        recorder->edges += edges;
        recorder->corners += corners;
    }
}

std::string Recorder::report(const std::string& name) const
{
    if (builds == 0) {
        return {};
    }
    std::ostringstream line;
    line << name << ": built by the exact construction where OCCT failed: " << edges
         << (edges == 1 ? " edge, " : " edges, ") << corners
         << (corners == 1 ? " corner" : " corners");
    Base::Console().message("%s\n", line.str().c_str());
    return line.str();
}

bool build(
    TopoShape& result,
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const Request& request,
    const char* op,
    std::string* reason
)
{
    std::string why;
    try {
        // A copy keeps the result's tag, hasher and history algorithm, which name the elements
        TopoShape built(result);
        int corners = 0;
        construct(built, base, edges, request, op, corners);
        result = built;
        TopTools_IndexedMapOfShape selected;
        for (const auto& edge : edges) {
            selected.Add(edge.getShape());
        }
        FC_LOG("built exactly: " << selected.Extent() << " edges, " << corners << " corners");
        Recorder::add(selected.Extent(), corners);
        return true;
    }
    catch (const Refusal& refusal) {
        why = refusal.reason;
    }
    catch (const Standard_Failure& e) {
        why = std::string("OCCT: ") + e.GetMessageString();
    }
    catch (const Base::Exception& e) {
        why = e.what();
    }
    catch (const std::exception& e) {
        why = e.what();
    }
    catch (...) {
        why = "an unknown exception";
    }
    FC_LOG("exact construction refused: " << why);
    if (reason) {
        *reason = why;
    }
    return false;
}

}  // namespace Part::FilletFallback
