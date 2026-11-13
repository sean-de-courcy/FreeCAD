// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <cmath>
#include <functional>
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
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <BRepTools.hxx>
#include <BRepTools_History.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>
#include <BRepLib.hxx>
#include <ElCLib.hxx>
#include <ElSLib.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <Geom2d_Curve.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Circle.hxx>
#include <GeomLib.hxx>
#include <Geom_BoundedSurface.hxx>
#include <Geom_Surface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <GProp_GProps.hxx>
#include <IntCurvesFace_ShapeIntersector.hxx>
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
#include <TopoDS_Compound.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <TColStd_HArray1OfReal.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <gp.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Circ.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Dir.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <gp_XY.hxx>

#include <Base/Console.h>
#include <Base/Exception.h>

#include "FilletFallback.h"
#include "MassProperties.h"
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
    return MassProperties::volume(shape);
}

double areaOf(const TopoDS_Shape& shape)
{
    return MassProperties::area(shape);
}

/** The volume after holds over before's, integrated over the faces that differ only: a face both
 * hold (the same face, placed and oriented the same) adds the same to both volumes about any one
 * point, so it is left out, and the faces after adds count less those before loses, reversed. The
 * error of a whole-body difference grows with the body (with its free-form faces, about 1e-9 of
 * it even adaptively); this one's with the faces a stage rebuilt. Each face is taken once
 * (MapShapes): a face two solids of one shape share would count once, so it serves one solid */
double changedVolume(const TopoDS_Shape& before, const TopoDS_Shape& after)
{
    TopTools_IndexedMapOfShape old;
    TopTools_IndexedMapOfShape now;
    TopExp::MapShapes(before, TopAbs_FACE, old);
    TopExp::MapShapes(after, TopAbs_FACE, now);
    BRep_Builder builder;
    TopoDS_Compound changed;
    builder.MakeCompound(changed);
    auto addUnshared = [&](const TopTools_IndexedMapOfShape& faces,
                           const TopTools_IndexedMapOfShape& others,
                           bool reversed) {
        for (int i = 1; i <= faces.Extent(); ++i) {
            const TopoDS_Shape& face = faces(i);
            int j = others.FindIndex(face);
            if (j > 0 && others(j).IsEqual(face)) {
                continue;
            }
            builder.Add(changed, reversed ? face.Reversed() : face);
        }
    };
    addUnshared(now, old, false);
    addUnshared(old, now, true);
    return MassProperties::volume(changed, true);
}

/** How far a Boolean opened the faces' loops: the sum, over the result's vertices that none of its
 * inputs holds, of their tolerances past linearTolerance. OCCT integrates a face's volume over its
 * pcurve loop, and where a Boolean leaves a vertex off its edges (two rims' rounds meeting the top
 * face nearly tangentially at their lens tips: tolerances up to 4e-5) the loop is open by that
 * much and the measured volume is off by up to 30 times this sum times the tools' size squared,
 * far more than volumeTolerance of the tools (ops#669: 1.3e-4 relative; macOS's cut is a
 * different such variant than Windows'). The error is the same wherever OCCT's reference point
 * lies, and can be as large as the lens two tools share: the lenses are checked by points
 * (materialIn)
 */
double raisedTolerance(const TopoDS_Shape& result, const std::vector<TopoDS_Shape>& inputs)
{
    TopTools_IndexedMapOfShape old;
    for (const auto& input : inputs) {
        TopExp::MapShapes(input, TopAbs_VERTEX, old);
    }
    TopTools_IndexedMapOfShape now;
    TopExp::MapShapes(result, TopAbs_VERTEX, now);
    double excess = 0.0;
    for (int i = 1; i <= now.Extent(); ++i) {
        if (!old.Contains(now(i))) {
            excess += std::max(0.0, BRep_Tool::Tolerance(TopoDS::Vertex(now(i))) - linearTolerance);
        }
    }
    return excess;
}

/// The square of a shape's bounding box's diagonal
double squareSize(const TopoDS_Shape& shape)
{
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    return box.IsVoid() ? 0.0 : box.SquareExtent();
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
    /// A two-edge corner where an edge is a circle (ops#640, #15, fillet-parity L8): convex
    /// edges at a convex vertex, on a plane both side faces are normal to. Each tool ends on the
    /// plane through the vertex normal to its own edge, and the result is the base minus their
    /// union, as Onshape's miter: where both tools reach, the one nearer its edge removes more,
    /// so the union is the lower of the two rounds (or chamfers); the wedge behind both planes
    /// lies opposite the material. Nothing of either end face may be left. Also a chamfer's
    /// concave edges at a vertex convex in the material (ops#640, #15): the tools are fused, and
    /// the wedge of air between their end planes takes the miter piece (miterTool), as Onshape's
    /// sharp miter
    Corner2Union,
    /// All three edges at the vertex are selected (a three-edge corner): the edge tools end
    /// where a corner tool (a sphere patch, or a chamfer's corner triangle) begins
    Corner3,
    /// A chamfer's edge that ends in a cusp: an unselected edge of one of its faces leaves the
    /// vertex the way it does, on an end face that holds both (Case Base #76). The tool ends on
    /// the plane through the vertex normal to the edge, as Onshape's; nothing caps it there
    CuspEnd,
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
    /// The surfaces (not planes) of the end faces that bound the tool at free ends (Case Base #105),
    /// as the faces the tool was split by carry them: its faces on them are capFaces too, and
    /// merge into the end face where they lie on its own surface
    std::vector<std::pair<Handle(Geom_Surface), TopLoc_Location>> capSurfaces;
    /// The planes of its ends at two-edge corners with unequal dihedral angles: the other edge's
    /// side face, which its faces there lie on. They join contactFaces: nothing of them may be
    /// left (the side face covers them, or the other edge's tool removes them)
    std::vector<TrimPlane> openEnds;
    /// The planes of its ends at two-edge corners with a circle (Corner2Union), and its faces in
    /// them: the other tool covers them, so nothing of them may be left once both are cut
    std::vector<TrimPlane> unionEnds;
    std::vector<TopoDS_Shape> unionEndFaces;
    /// A fused tool's volume inside the base's material: none, unless its strip runs off its face
    /// over a concave edge into the material there, which absorbs it (ops#640, #15 past the limit)
    double inBase = 0.0;
    /// The miter piece at a concave corner with a circle: its faces merge into the tools' faces
    /// they continue (one cone, one plane, as Onshape's sharp miter)
    bool miter = false;
    /// A concave edge's round rolled on over a tangent edge onto the next face (rollOn): it fills
    /// air only, as its construction assumes
    bool rolled = false;
    /// No closed-form volume (a tight wall arc's canal-surface tool, C4 shape A): checked by its
    /// own construction instead, cut in a stage of its own before the others, and its volume
    /// set to what that stage measures
    bool measured = false;
    /// A measured tool's wedge: the region between its two fans from inside the material out to
    /// its outer surface. Every other cut tool is trimmed by it before the cuts, so that the
    /// neighbours' rounds end on the fans (which cross them at right angles) instead of meeting
    /// the canal patch tangentially inside a face, which leaves sliver faces (C4 shape A3)
    TopoDS_Shape wedge;
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
    /// A straight edge with a cylinder parallel to it among its faces (a curved wall's end,
    /// ops#640, #150): its round is a plane fillet of the faces' traces, swept along the edge
    bool ruled = false;
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
        gp_Dir along = curve.Line().Direction();
        auto parallelFace = [&](const BRepAdaptor_Surface& surface) {
            if (surface.GetType() == GeomAbs_Plane) {
                return true;
            }
            if (surface.GetType() != GeomAbs_Cylinder
                || !parallel(surface.Cylinder().Axis().Direction(), along)) {
                return false;
            }
            data.ruled = true;
            return true;
        };
        bool both = parallelFace(s0);
        both = parallelFace(s1) && both;
        if (!both) {
            refuse("a straight edge between faces that are not planes or cylinders along it");
        }
        if (data.ruled && ctx.request.kind != Kind::Fillet) {
            refuse("a chamfer of a straight edge on a cylinder");
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

/// Whether two faces through the point are pieces of one surface with the material on the same
/// side: coplanar planes, or one cylinder. The edge between such faces is a split that a refine
/// removes and Onshape's bodies never have (ops#640 F1: a wall flush with its base's end)
bool oneSurface(const TopoDS_Face& a, const TopoDS_Face& b, const gp_Pnt& point)
{
    BRepAdaptor_Surface first(a, Standard_False);
    BRepAdaptor_Surface second(b, Standard_False);
    if (first.GetType() != second.GetType()) {
        return false;
    }
    if (first.GetType() == GeomAbs_Cylinder) {
        gp_Cylinder one = first.Cylinder();
        gp_Cylinder other = second.Cylinder();
        if (std::abs(one.Radius() - other.Radius()) > linearTolerance
            || !parallel(one.Axis().Direction(), other.Axis().Direction())
            || gp_Lin(one.Axis()).Distance(other.Location()) > linearTolerance) {
            return false;
        }
    }
    else if (first.GetType() != GeomAbs_Plane) {
        return false;
    }
    // Both pass through the point, so planes with parallel normals are one plane
    gp_Dir na = outwardNormal(a, point);
    gp_Dir nb = outwardNormal(b, point);
    return parallel(na, nb) && na.Dot(nb) > 0;
}

/// The vertex's edges and faces with its splits folded: an unselected edge between two pieces of
/// one surface is left out, and each such piece is counted once, by the selected edge's own face
/// where it is one of them. A body without splits is returned as it is.
void foldSplits(const Context& ctx,
                const EdgeData& data,
                const TopoDS_Vertex& vertex,
                std::vector<TopoDS_Shape>& edges,
                std::vector<TopoDS_Shape>& faces)
{
    gp_Pnt point = BRep_Tool::Pnt(vertex);
    auto indexOf = [&](const TopoDS_Shape& face) {
        for (size_t i = 0; i < faces.size(); ++i) {
            if (faces[i].IsSame(face)) {
                return static_cast<int>(i);
            }
        }
        return -1;
    };
    std::vector<int> group(faces.size());
    for (size_t i = 0; i < faces.size(); ++i) {
        group[i] = static_cast<int>(i);
    }
    std::function<int(int)> root = [&](int i) {
        return group[i] == i ? i : group[i] = root(group[i]);
    };
    std::vector<TopoDS_Shape> kept;
    for (const auto& shape : edges) {
        if (!shape.IsSame(data.edge) && !ctx.selected.Contains(shape)) {
            auto ofEdge = ctx.list(ctx.edgeFaces, shape);
            if (ofEdge.size() == 2 && !ofEdge[0].IsSame(ofEdge[1])) {
                int i = indexOf(ofEdge[0]);
                int j = indexOf(ofEdge[1]);
                if (i >= 0 && j >= 0
                    && oneSurface(TopoDS::Face(ofEdge[0]), TopoDS::Face(ofEdge[1]), point)) {
                    group[root(i)] = root(j);
                    continue;
                }
            }
        }
        kept.push_back(shape);
    }
    if (kept.size() == edges.size()) {
        return;
    }
    int own0 = indexOf(data.faces[0]);
    int own1 = indexOf(data.faces[1]);
    if (own0 >= 0 && own1 >= 0 && root(own0) == root(own1)) {
        return;  // the selected edge itself is between pieces of one surface: no fold
    }
    std::vector<TopoDS_Shape> folded;
    for (size_t i = 0; i < faces.size(); ++i) {
        int r = root(static_cast<int>(i));
        bool own = static_cast<int>(i) == own0 || static_cast<int>(i) == own1;
        bool groupHasOwn = (own0 >= 0 && root(own0) == r) || (own1 >= 0 && root(own1) == r);
        bool first = true;
        for (size_t j = 0; j < i; ++j) {
            if (root(static_cast<int>(j)) == r) {
                first = false;
            }
        }
        if (groupHasOwn ? own : first) {
            folded.push_back(faces[i]);
        }
    }
    edges = std::move(kept);
    faces = std::move(folded);
}

/// Whether the edge lies in the plane: a line with its ends in it, or a circle or an ellipse in
/// it. Any other curve is not counted, so a fold that needs it stays refused
bool edgeInPlane(const TopoDS_Edge& edge, const gp_Pln& plane)
{
    for (TopExp_Explorer it(edge, TopAbs_VERTEX); it.More(); it.Next()) {
        if (plane.Distance(BRep_Tool::Pnt(TopoDS::Vertex(it.Current()))) > linearTolerance) {
            return false;
        }
    }
    BRepAdaptor_Curve curve(edge);
    const gp_Dir& normal = plane.Axis().Direction();
    switch (curve.GetType()) {
        case GeomAbs_Line:
            return true;
        case GeomAbs_Circle:
            return parallel(curve.Circle().Axis().Direction(), normal)
                && plane.Distance(curve.Circle().Location()) <= linearTolerance;
        case GeomAbs_Ellipse:
            return parallel(curve.Ellipse().Axis().Direction(), normal)
                && plane.Distance(curve.Ellipse().Location()) <= linearTolerance;
        default:
            return false;
    }
}

/// Whether the face lies wholly on the far side of the plane through the point, the side away from
/// the direction. A bound, not a sample: the face's box is taken from its surface over its
/// parameter range (no triangulation), so it holds the face, and each of its corners must lie
/// beyond the plane within the box's own enlargement
bool whollyBeyond(const TopoDS_Face& face, const gp_Pnt& point, const gp_Dir& toward)
{
    Bnd_Box box;
    BRepBndLib::Add(face, box, Standard_False);
    if (box.IsVoid() || box.IsOpen()) {
        return false;
    }
    double x[2];
    double y[2];
    double z[2];
    box.Get(x[0], y[0], z[0], x[1], y[1], z[1]);
    double slack = linearTolerance
        + box.GetGap() * (std::abs(toward.X()) + std::abs(toward.Y()) + std::abs(toward.Z()));
    for (double cx : x) {
        for (double cy : y) {
            for (double cz : z) {
                if (gp_Vec(point, gp_Pnt(cx, cy, cz)).Dot(gp_Vec(toward)) > slack) {
                    return false;
                }
            }
        }
    }
    return true;
}

/// ops#640, the replica's #150 (a round at the end of a wall that stands flush on a chamfered
/// rim): besides the selected edge's two faces and one plane P, the vertex has faces that lie
/// wholly beyond P from the selected edge and meet the vertex only through edges in P. The tool,
/// bounded by P, never reaches them: they are left out, P counts as the end face, and their edges
/// at the vertex count as one (the rim). Called only for a vertex that would be refused; the fold
/// is taken only when it leaves three edges and three faces and exactly one plane qualifies, so
/// anything less clear-cut stays refused
void foldFarFaces(const Context& ctx,
                  const EdgeData& data,
                  const TopoDS_Vertex& vertex,
                  std::vector<TopoDS_Shape>& edges,
                  std::vector<TopoDS_Shape>& faces)
{
    gp_Pnt point = BRep_Tool::Pnt(vertex);
    gp_Dir away = awayFrom(data.edge, vertex);
    auto own = [&](const TopoDS_Shape& face) {
        return face.IsSame(data.faces[0]) || face.IsSame(data.faces[1]);
    };
    auto touches = [&](const TopoDS_Shape& edge, const std::vector<TopoDS_Shape>& among) {
        for (const auto& face : ctx.list(ctx.edgeFaces, edge)) {
            for (const auto& other : among) {
                if (face.IsSame(other)) {
                    return true;
                }
            }
        }
        return false;
    };
    std::vector<TopoDS_Shape> foldedEdges;
    std::vector<TopoDS_Shape> foldedFaces;
    int found = 0;
    for (const auto& candidate : faces) {
        if (own(candidate)) {
            continue;
        }
        BRepAdaptor_Surface surface(TopoDS::Face(candidate), Standard_False);
        if (surface.GetType() != GeomAbs_Plane) {
            continue;
        }
        gp_Pln plane = surface.Plane();
        gp_Dir toward = plane.Axis().Direction();
        double side = toward.Dot(away);
        if (std::abs(side) < 1e-6 || plane.Distance(point) > linearTolerance) {
            continue;
        }
        if (side < 0) {
            toward.Reverse();
        }
        std::vector<TopoDS_Shape> beyondFaces;
        std::vector<TopoDS_Shape> keptFaces;
        bool holds = true;
        for (const auto& face : faces) {
            if (own(face) || face.IsSame(candidate)) {
                keptFaces.push_back(face);
            }
            else if (whollyBeyond(TopoDS::Face(face), point, toward)) {
                beyondFaces.push_back(face);
            }
            else {
                holds = false;
                break;
            }
        }
        if (!holds || beyondFaces.empty()) {
            continue;
        }
        std::vector<TopoDS_Shape> keptEdges;
        bool rim = false;
        for (const auto& edge : edges) {
            if (!touches(edge, beyondFaces)) {
                keptEdges.push_back(edge);
                continue;
            }
            if (edge.IsSame(data.edge) || ctx.selected.Contains(edge)
                || !edgeInPlane(TopoDS::Edge(edge), plane)) {
                holds = false;
                break;
            }
            if (!rim) {
                rim = true;
                keptEdges.push_back(edge);
            }
        }
        if (!holds || keptEdges.size() != 3 || keptFaces.size() != 3) {
            continue;
        }
        ++found;
        foldedEdges = std::move(keptEdges);
        foldedFaces = std::move(keptFaces);
    }
    if (found == 1) {
        edges = std::move(foldedEdges);
        faces = std::move(foldedFaces);
    }
}

struct VertexEnd
{
    VertexClass kind = VertexClass::Refuse;
    /// The planes that bound the tool here: one, but two at a chamfer's three-edge corner
    std::vector<TrimPlane> trims;
    /// FreeEnd: an end face that is not a plane, whose surface bounds the tool (Case Base #105);
    /// trims then holds its tangent plane at the vertex
    TopoDS_Face surfaceEnd;
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
/// Whether a chamfer's two distances are equal (or it is by equal distances)
bool equalDistances(const Request& request)
{
    return request.chamferType == ChamferType::equalDistance
        || (request.chamferType == ChamferType::twoDistances
            && std::abs(request.size1 - request.size2)
                <= linearTolerance * std::max(1.0, request.size1));
}

/// A two-edge corner where an edge is a circle (VertexClass::Corner2Union), or the reason why not
VertexEnd classifyUnionCorner(
    const Context& ctx,
    const std::vector<EdgeData>& all,
    const EdgeData& data,
    const TopoDS_Vertex& vertex,
    const std::vector<TopoDS_Edge>& otherSelected,
    VertexEnd end
)
{
    if (otherSelected.size() != 1) {
        end.reason = "a corner of three edges with an edge that is not straight";
        return end;
    }
    auto other = std::find_if(all.begin(), all.end(), [&](const EdgeData& d) {
        return d.edge.IsSame(otherSelected.front());
    });
    if (other == all.end()) {
        end.reason = "a corner edge that was not analysed";
        return end;
    }
    if (data.convex != other->convex) {
        end.reason = "a corner with a circle whose edges are not both convex";
        return end;
    }
    // Concave edges (ops#640, #15): a chamfer's, at a corner convex in the material (oracle 9d's
    // keyhole groove: a sharp miter); Onshape's concave fillets there are not known yet
    const bool concave = !data.convex;
    if (concave && ctx.request.kind != Kind::Chamfer) {
        end.reason = "a concave fillet at a corner with a circle";
        return end;
    }
    if (ctx.request.kind == Kind::Chamfer && !equalDistances(ctx.request)) {
        end.reason = "a two-distance or distance-angle chamfer at a corner";
        return end;
    }
    TopoDS_Face shared;
    for (const auto& mine : data.faces) {
        for (const auto& theirs : other->faces) {
            if (mine.IsSame(theirs)) {
                shared = mine;
            }
        }
    }
    if (shared.IsNull() || BRepAdaptor_Surface(shared, Standard_False).GetType() != GeomAbs_Plane) {
        end.reason = "a corner with a circle whose edges share no plane";
        return end;
    }
    double here = 0.0;
    double there = 0.0;
    gp_Dir away = awayFrom(data.edge, vertex, &here);
    gp_Dir otherAway = awayFrom(other->edge, vertex, &there);
    if (std::abs(dihedralAt(data, here) - pi / 2) > angularTolerance
        || std::abs(dihedralAt(*other, there) - pi / 2) > angularTolerance) {
        end.reason = "a corner with a circle whose side faces are not normal to its face";
        return end;
    }
    // Convex edges at a convex vertex: each edge leaves the vertex into the face's side of the
    // other. Concave edges at a vertex convex in the material (reflex in the shared face): each
    // leaves it away from the face's side of the other, and the tools, fused, leave a wedge of air
    // between their end planes that the miter piece fills (miterTool)
    double sign = concave ? -1.0 : 1.0;
    if (sign * inwardIn(shared, data.edge, here).Dot(otherAway) < angularTolerance
        || sign * inwardIn(shared, other->edge, there).Dot(away) < angularTolerance) {
        end.reason = concave ? "a concave corner with a circle that is not convex in the material"
                             : "a corner with a circle that is not convex";
        return end;
    }
    end.kind = VertexClass::Corner2Union;
    end.trims = {{BRepAdaptor_Curve(data.edge).Value(here), away.Reversed()}};
    return end;
}

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
    bool curved = !data.line;
    bool ruled = data.ruled;
    for (const auto& edge : otherSelected) {
        auto other = std::find_if(all.begin(), all.end(), [&](const EdgeData& d) {
            return d.edge.IsSame(edge);
        });
        curved = curved || (other != all.end() && !other->line);
        ruled = ruled || (other != all.end() && other->ruled);
    }
    if (ruled) {
        end.reason = "a corner with a straight edge on a cylinder";
        return end;
    }
    if (curved) {
        return classifyUnionCorner(ctx, all, data, vertex, otherSelected, std::move(end));
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
        if (!equalDistances(request)) {
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
    // An unselected seam, or a degenerate edge, bounds nothing here: left out (Case Base #76, a
    // tunnel's seam on the cusp where its upper half circle meets a slot's wall)
    edges.erase(
        std::remove_if(
            edges.begin(),
            edges.end(),
            [&](const TopoDS_Shape& shape) {
                const TopoDS_Edge& edge = TopoDS::Edge(shape);
                if (edge.IsSame(data.edge) || ctx.selected.Contains(edge)) {
                    return false;
                }
                if (BRep_Tool::Degenerated(edge)) {
                    return true;
                }
                // A seam: one face on both sides (an edge between the face and another can carry
                // two curves on it too, where the seam's line goes on past the face)
                auto ofEdge = ctx.list(ctx.edgeFaces, edge);
                return ofEdge.size() == 1 && BRep_Tool::IsClosed(edge, TopoDS::Face(ofEdge.front()));
            }
        ),
        edges.end()
    );
    foldSplits(ctx, data, vertex, edges, faces);
    if (!(edges.size() == 2 && faces.size() == 2) && (edges.size() != 3 || faces.size() != 3)) {
        foldFarFaces(ctx, data, vertex, edges, faces);
    }
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
        // A round ending against a curved face (Case Base #105: a lip's round at its limit, cut
        // off by an end blend's B-spline face, as Onshape's): the face's surface, extended past
        // the face, bounds the tool, as OCCT's own fillet ends there below the limit (lineTool)
        if (ctx.request.kind != Kind::Fillet) {
            end.reason = "a chamfer's end face that is not a plane";
            return end;
        }
        gp_Pnt2d uv = BRep_Tool::Parameters(vertex, endFace);
        gp_Pnt onSurface;
        gp_Vec du;
        gp_Vec dv;
        surface.D1(uv.X(), uv.Y(), onSurface, du, dv);
        gp_Vec tangentNormal = du.Crossed(dv);
        if (tangentNormal.Magnitude() < linearTolerance) {
            end.reason = "an end face that is not a plane, degenerate at the vertex";
            return end;
        }
        gp_Dir normal(tangentNormal);
        if (std::abs(normal.Dot(away)) < 1e-6) {
            end.reason = "an end face that is not a plane, tangent to the edge";
            return end;
        }
        if (normal.Dot(away) > 0) {
            normal.Reverse();
        }
        end.kind = VertexClass::FreeEnd;
        end.trims = {{point, normal}};
        end.surfaceEnd = endFace;
        return end;
    }
    gp_Dir normal = surface.Plane().Axis().Direction();
    if (std::abs(normal.Dot(away)) < 1e-6) {
        // A cusp: an unselected edge of one of this edge's faces leaves the vertex the way this
        // edge does (Case Base #76: a tunnel's upper half circle on a slot's end wall, the slot's
        // walls tangent to the tunnel). Onshape ends a chamfer there on the plane through the
        // vertex normal to the edge, and the walls trim it as walls behind a strip that runs off
        // its face. A fillet there isn't known from Onshape: refused
        bool cusp = std::any_of(edges.begin(), edges.end(), [&](const TopoDS_Shape& shape) {
            const TopoDS_Edge& other = TopoDS::Edge(shape);
            if (other.IsSame(data.edge)) {
                return false;
            }
            auto ofOther = ctx.list(ctx.edgeFaces, other);
            bool onOwnFace = std::any_of(ofOther.begin(), ofOther.end(), [&](const TopoDS_Shape& f) {
                return f.IsSame(data.faces[0]) || f.IsSame(data.faces[1]);
            });
            return onOwnFace && awayFrom(other, vertex).Dot(away) > 1 - angularTolerance;
        });
        if (cusp && ctx.request.kind == Kind::Chamfer) {
            end.kind = VertexClass::CuspEnd;
            end.trims = {{point, away.Reversed()}};
            return end;
        }
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

/// Faces that meet tangentially along an edge (G1) have outward normals this close there
constexpr double tangentTolerance = 1e-6;

/** The round of a straight edge with a cylinder parallel to it among its faces (EdgeData::ruled):
 * in the plane normal to the edge, each face is a line or a circle, and the round's arc of radius
 * r is tangent to both, on the side of the ball (in the material for a convex edge, in the air for
 * a concave one); the tool is the region between the corner, the two traces and the arc, swept
 * along the edge, whose ends must be square to it (a curved wall's end, rounded on both edges:
 * Onshape's FR1, exact). Its area in closed form: the triangle of the corner and the tangent
 * points, plus or minus the circles' segments over the chords, less the arc's segment.
 *
 * A concave edge whose ball can't touch one of its faces, where that face ends in a tangent edge
 * along the edge onto a face that is a prism along it, rolls on onto that face (rolledTool)
 */
struct RuledTrace
{
    bool circle = false;
    gp_Pnt origin;      // a point of the trace: where it starts
    gp_Dir inward;      // along the face, away from where it starts
    gp_Dir toCentre;    // line: the normal toward the ball's centre
    gp_Pnt centre;      // circle
    double radius = 0;  // circle
    double offset = 0;  // circle: the radius of the locus of the ball's centre
};

/// The trace of the face in the section plane through the corner, starting at the point
RuledTrace ruledTrace(
    const EdgeData& data,
    const TopoDS_Face& face,
    const gp_Pnt& corner,
    const gp_Pnt& at,
    const gp_Dir& inward,
    double r
)
{
    gp_Vec z(gp_Vec(data.start, data.end).Normalized());
    RuledTrace t;
    t.origin = at;
    t.inward = inward;
    gp_Dir outward = outwardNormal(face, at);
    BRepAdaptor_Surface surface(face, Standard_False);
    if (surface.GetType() == GeomAbs_Cylinder) {
        gp_Cylinder cylinder = surface.Cylinder();
        const gp_Pnt& a = cylinder.Location();
        t.circle = true;
        t.centre = a.Translated(z * gp_Vec(a, corner).Dot(z));
        t.radius = cylinder.Radius();
        // The ball is in the material at a convex edge, in the air at a concave one
        bool materialInside = gp_Vec(t.centre, at).Dot(gp_Vec(outward)) > 0;
        bool ballInside = data.convex == materialInside;
        t.offset = ballInside ? t.radius - r : t.radius + r;
        if (t.offset <= linearTolerance) {
            refuse("a round as big as the cylinder it rolls inside");
        }
    }
    else if (surface.GetType() == GeomAbs_Plane) {
        t.toCentre = data.convex ? outward.Reversed() : outward;
    }
    else {
        refuse("a round of a straight edge on a face that is not a plane or a cylinder");
    }
    return t;
}

/// The centres of the balls of radius r tangent to both traces, on the ball's side of each
std::vector<gp_Pnt> ruledCentres(const RuledTrace& a, const RuledTrace& b, const gp_Dir& direction, double r)
{
    std::vector<gp_Pnt> found;
    gp_Vec z(direction);
    auto lineAndCircle = [&](const RuledTrace& line, const RuledTrace& circle) {
        gp_Pnt q = line.origin.Translated(gp_Vec(line.toCentre) * r);
        gp_Vec u(line.inward);
        gp_Vec qc(circle.centre, q);
        double half = u.Dot(qc);
        double c = qc.SquareMagnitude() - circle.offset * circle.offset;
        double discriminant = half * half - c;
        if (discriminant < 0) {
            return;
        }
        for (double sign : {-1.0, 1.0}) {
            found.push_back(q.Translated(u * (-half + sign * std::sqrt(discriminant))));
        }
    };
    if (a.circle && b.circle) {
        gp_Vec between(a.centre, b.centre);
        double d = between.Magnitude();
        if (d <= linearTolerance) {
            refuse("a round between coaxial cylinders");
        }
        double r0 = a.offset;
        double r1 = b.offset;
        double along = (r0 * r0 - r1 * r1 + d * d) / (2 * d);
        double h2 = r0 * r0 - along * along;
        if (h2 >= 0) {
            gp_Vec x = between / d;
            gp_Vec y = z.Crossed(x);
            gp_Pnt middle = a.centre.Translated(x * along);
            found.push_back(middle.Translated(y * std::sqrt(h2)));
            found.push_back(middle.Translated(y * -std::sqrt(h2)));
        }
    }
    else if (a.circle) {
        lineAndCircle(b, a);
    }
    else if (b.circle) {
        lineAndCircle(a, b);
    }
    else {
        // Two lines: where the lines offset by r cross
        gp_Pnt qa = a.origin.Translated(gp_Vec(a.toCentre) * r);
        gp_Pnt qb = b.origin.Translated(gp_Vec(b.toCentre) * r);
        gp_Vec ua(a.inward);
        gp_Vec ub(b.inward);
        double denominator = ua.Crossed(ub).Dot(z);
        if (std::abs(denominator) > angularTolerance) {
            double s = gp_Vec(qa, qb).Crossed(ub).Dot(z) / denominator;
            found.push_back(qa.Translated(ua * s));
        }
    }
    return found;
}

/// Where the ball about the centre touches the trace
gp_Pnt ruledTouch(const RuledTrace& t, const gp_Pnt& centre)
{
    if (t.circle) {
        gp_Vec radial(t.centre, centre);
        if (radial.Magnitude() <= linearTolerance) {
            refuse("a round centred on the axis of a cylinder it rolls on");
        }
        return t.centre.Translated(radial.Normalized() * t.radius);
    }
    double along = gp_Vec(t.origin, centre).Dot(gp_Vec(t.inward));
    return t.origin.Translated(gp_Vec(t.inward) * along);
}

/// The ball touches the trace past its start, on the face's side
bool ruledTouches(const RuledTrace& t, const gp_Pnt& touch, const gp_Pnt& centre, double r)
{
    return gp_Vec(t.origin, touch).Dot(gp_Vec(t.inward)) > linearTolerance
        && std::abs(touch.Distance(centre) - r) <= linearTolerance;
}

/** A piece of a section's boundary in the section plane: a line, or an arc of a circle about the
 * centre by the signed angle (counterclockwise about the edge's direction positive)
 */
struct RuledPiece
{
    gp_Pnt from;
    gp_Pnt to;
    bool arc = false;
    gp_Pnt centre;
    double angle = 0.0;
};

/// The signed angle from a to b about the axis, turning the way of the sense (+1 or -1)
double turnedAngle(const gp_Vec& a, const gp_Vec& b, const gp_Vec& axis, double sense)
{
    double raw = std::atan2(a.Crossed(b).Dot(axis), a.Dot(b));
    if (sense > 0 && raw <= 0) {
        raw += 2 * pi;
    }
    else if (sense < 0 && raw >= 0) {
        raw -= 2 * pi;
    }
    return raw;
}

/// The trace's piece from its start to the point, along the face
RuledPiece tracePiece(const RuledTrace& t, const gp_Pnt& to, const gp_Vec& z)
{
    RuledPiece piece;
    piece.from = t.origin;
    piece.to = to;
    if (t.circle) {
        piece.arc = true;
        piece.centre = t.centre;
        gp_Vec radial(t.centre, t.origin);
        double sense = radial.Crossed(gp_Vec(t.inward)).Dot(z) > 0 ? 1.0 : -1.0;
        piece.angle = turnedAngle(radial, gp_Vec(t.centre, to), z, sense);
    }
    return piece;
}

/** The signed area of the closed boundary (counterclockwise about z positive): the polygon of the
 * pieces' ends, plus each arc's segment, r^2 (theta - sin theta) / 2 with the signed angle
 */
double boundaryArea(const std::vector<RuledPiece>& pieces, const gp_Vec& z)
{
    const gp_Pnt& o = pieces.front().from;
    double area = 0.0;
    for (const auto& piece : pieces) {
        area += gp_Vec(o, piece.from).Crossed(gp_Vec(o, piece.to)).Dot(z) / 2;
        if (piece.arc) {
            double radius = piece.centre.Distance(piece.from);
            area += radius * radius * (piece.angle - std::sin(piece.angle)) / 2;
        }
    }
    return area;
}

/// The middle of the piece: of its chord, or of its arc
gp_Pnt pieceMiddle(const RuledPiece& piece, const gp_Vec& z)
{
    if (!piece.arc) {
        return gp_Pnt((piece.from.XYZ() + piece.to.XYZ()) / 2);
    }
    gp_Trsf turn;
    turn.SetRotation(gp_Ax1(piece.centre, gp_Dir(z)), piece.angle / 2);
    return piece.from.Transformed(turn);
}

/// The edges of the boundary, in order
TopoDS_Wire boundaryWire(const std::vector<RuledPiece>& pieces, const gp_Vec& z)
{
    BRepBuilderAPI_MakeWire wire;
    for (const auto& piece : pieces) {
        if (!piece.arc) {
            wire.Add(BRepBuilderAPI_MakeEdge(piece.from, piece.to).Edge());
            continue;
        }
        gp_Pnt middle = pieceMiddle(piece, z);
        wire.Add(
            BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(piece.from, middle, piece.to).Value()).Edge()
        );
    }
    if (!wire.IsDone()) {
        refuse("building a round's section failed");
    }
    return wire.Wire();
}

/// The point lies on the face (inside it, or on its boundary)
bool onFace(const TopoDS_Face& face, const gp_Pnt& point)
{
    BRepClass_FaceClassifier classifier(face, point, 1000 * linearTolerance);
    return classifier.State() == TopAbs_IN || classifier.State() == TopAbs_ON;
}

/** A concave edge's ball that can't touch the face k (Case Base #47, ops#640): where that face
 * ends, away from the corner, in a tangent (G1) edge along the edge onto a face that is a prism
 * along it (a plane through its direction, or a cylinder about it), the ball rolls on onto that
 * face, as Onshape's does: one round tangent to the next face and the other face, which covers
 * face k there. The section is the corner, face k's trace to the tangent edge, the next face's
 * trace to the round, the round's arc, and the other face's trace back to the corner; its area in
 * closed form is the polygon of those points plus each arc's signed segment. Empty when face k
 * has no such edge, or the ball doesn't fit there either
 */
struct Rolled
{
    TopoDS_Face next;
    gp_Pnt tangentPoint;
    gp_Pnt centre;
    gp_Pnt touchNext;
    gp_Pnt touchOther;
    RuledTrace traceNext;
};

std::optional<Rolled> rollOn(
    const Context& ctx,
    const EdgeData& data,
    const RuledTrace traces[2],
    int k,
    double r
)
{
    gp_Dir direction(gp_Vec(data.start, data.end));
    gp_Vec z(direction);
    double length = data.start.Distance(data.end);
    const gp_Pnt& corner = data.start;
    const TopoDS_Face& face = data.faces[k];
    const RuledTrace& mine = traces[k];
    const RuledTrace& other = traces[1 - k];
    // The face's tangent edges along the edge: the first one its trace reaches from the corner
    std::optional<Rolled> rolled;
    double travel = std::numeric_limits<double>::infinity();
    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        if (edge.IsSame(data.edge) || BRep_Tool::IsClosed(edge, face)) {
            continue;
        }
        BRepAdaptor_Curve curve(edge);
        if (curve.GetType() != GeomAbs_Line || !parallel(curve.Line().Direction(), direction)) {
            continue;
        }
        const auto* faces = ctx.edgeFaces.Seek(edge);
        if (!faces || faces->Size() != 2) {
            continue;
        }
        TopoDS_Face next;
        for (const auto& f : *faces) {
            if (!f.IsSame(face)) {
                next = TopoDS::Face(f);
            }
        }
        if (next.IsNull()) {
            continue;
        }
        gp_Pnt middle = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
        if (gp_Vec(outwardNormal(face, middle)).Crossed(gp_Vec(outwardNormal(next, middle))).Magnitude()
                > tangentTolerance
            || outwardNormal(face, middle).Dot(outwardNormal(next, middle)) <= 0) {
            continue;
        }
        BRepAdaptor_Surface surface(next, Standard_False);
        bool prism = surface.GetType() == GeomAbs_Plane
            || (surface.GetType() == GeomAbs_Cylinder
                && parallel(surface.Cylinder().Axis().Direction(), direction));
        if (!prism) {
            continue;
        }
        // The tangent edge must run the edge's whole length
        gp_Pnt a = curve.Value(curve.FirstParameter());
        gp_Pnt b = curve.Value(curve.LastParameter());
        double sa = gp_Vec(corner, a).Dot(z);
        double sb = gp_Vec(corner, b).Dot(z);
        double tolerance = std::max(linearTolerance, BRep_Tool::Tolerance(edge));
        if (std::min(sa, sb) > tolerance || std::max(sa, sb) < length - tolerance) {
            continue;
        }
        gp_Pnt point = a.Translated(z * -sa);
        // How far along the trace, from the corner in its sense
        double here = 0.0;
        if (mine.circle) {
            if (std::abs(point.Distance(mine.centre) - mine.radius) > tolerance) {
                continue;
            }
            here = std::abs(tracePiece(mine, point, z).angle);
        }
        else {
            if (gp_Lin(corner, mine.inward).Distance(point) > tolerance) {
                continue;
            }
            here = gp_Vec(corner, point).Dot(gp_Vec(mine.inward));
        }
        if (here <= linearTolerance || here >= travel) {
            continue;
        }
        Rolled candidate;
        candidate.next = next;
        candidate.tangentPoint = point;
        travel = here;
        rolled = candidate;
    }
    if (!rolled) {
        return std::nullopt;
    }
    const gp_Pnt& tangentPoint = rolled->tangentPoint;
    RuledPiece first = tracePiece(mine, tangentPoint, z);
    // The face holds its trace up to the tangent edge: nothing else bounds it first
    if (!onFace(face, pieceMiddle(first, z).Translated(z * (length / 2)))) {
        refuse("a round rolled on over a tangent edge along a face cut short before it");
    }
    // The next face's trace, on from the tangent point the way the first one runs there
    gp_Dir onward = mine.inward;
    if (mine.circle) {
        gp_Vec radial(mine.centre, tangentPoint);
        onward = gp_Dir(z.Crossed(radial) * (first.angle > 0 ? 1.0 : -1.0));
    }
    RuledTrace next = ruledTrace(data, rolled->next, corner, tangentPoint, onward, r);
    std::optional<gp_Pnt> best;
    for (const auto& centre : ruledCentres(next, other, direction, r)) {
        gp_Pnt touchNext = ruledTouch(next, centre);
        gp_Pnt touchOther = ruledTouch(other, centre);
        if (!ruledTouches(next, touchNext, centre, r) || !ruledTouches(other, touchOther, centre, r)) {
            continue;
        }
        // The ball stays clear of face k's trace, which it rolled over
        double clearance = std::min(centre.Distance(corner), centre.Distance(tangentPoint));
        if (mine.circle) {
            gp_Vec radial(mine.centre, centre);
            if (radial.Magnitude() > linearTolerance) {
                double angle = turnedAngle(gp_Vec(mine.centre, corner), radial, z, first.angle);
                if (std::abs(angle) < std::abs(first.angle)) {
                    clearance = std::min(clearance, std::abs(radial.Magnitude() - mine.radius));
                }
            }
        }
        else {
            double along = gp_Vec(corner, centre).Dot(gp_Vec(mine.inward));
            if (along > 0 && along < travel) {
                clearance = std::min(clearance, gp_Lin(corner, mine.inward).Distance(centre));
            }
        }
        if (clearance < r - linearTolerance) {
            continue;
        }
        if (!best || centre.Distance(corner) < best->Distance(corner)) {
            best = centre;
        }
    }
    if (!best) {
        return std::nullopt;
    }
    rolled->centre = *best;
    rolled->touchNext = ruledTouch(next, *best);
    // The next face holds its trace up to the round
    RuledPiece onNext = tracePiece(next, rolled->touchNext, z);
    if (!onFace(rolled->next, pieceMiddle(onNext, z).Translated(z * (length / 2)))
        || !onFace(rolled->next, rolled->touchNext.Translated(z * (length / 2)))) {
        refuse("a round rolled on over a tangent edge onto a face cut short before it");
    }
    rolled->touchOther = ruledTouch(other, *best);
    rolled->traceNext = next;
    return rolled;
}

/// The tool of a round rolled on over the tangent edge at the end of face k (rollOn)
Tool rolledTool(
    const EdgeData& data,
    const VertexEnd ends[2],
    const RuledTrace traces[2],
    int k,
    const Rolled& rolled,
    double r
)
{
    gp_Dir direction(gp_Vec(data.start, data.end));
    gp_Vec z(direction);
    double length = data.start.Distance(data.end);
    const gp_Pnt& corner = data.start;
    const RuledTrace& mine = traces[k];
    const RuledTrace& other = traces[1 - k];
    std::vector<RuledPiece> pieces;
    pieces.push_back(tracePiece(mine, rolled.tangentPoint, z));
    pieces.push_back(tracePiece(rolled.traceNext, rolled.touchNext, z));
    // The round's arc: the shorter one between its touch points, toward the corner
    gp_Vec toNext(rolled.centre, rolled.touchNext);
    gp_Vec toOther(rolled.centre, rolled.touchOther);
    gp_Vec bisector = toNext.Normalized() + toOther.Normalized();
    if (bisector.Magnitude() <= 1e-6) {
        refuse("a round rolled on over a tangent edge across a half circle");
    }
    gp_Pnt arcMiddle = rolled.centre.Translated(bisector.Normalized() * r);
    auto side = [&](const gp_Pnt& a, const gp_Pnt& b, const gp_Pnt& p) {
        return gp_Vec(a, b).Crossed(gp_Vec(a, p)).Dot(z);
    };
    if (side(rolled.touchNext, rolled.touchOther, arcMiddle)
            * side(rolled.touchNext, rolled.touchOther, corner)
        <= 0) {
        refuse("a round rolled on over a tangent edge that bulges away from its corner");
    }
    RuledPiece arc;
    arc.from = rolled.touchNext;
    arc.to = rolled.touchOther;
    arc.arc = true;
    arc.centre = rolled.centre;
    arc.angle = std::atan2(toNext.Crossed(toOther).Dot(z), toNext.Dot(toOther));
    pieces.push_back(arc);
    // The other face's trace, back from the round to the corner
    RuledPiece back = tracePiece(other, rolled.touchOther, z);
    std::swap(back.from, back.to);
    back.angle = -back.angle;
    pieces.push_back(back);
    double signedArea = boundaryArea(pieces, z);
    double area = std::abs(signedArea);
    if (area <= linearTolerance * r) {
        refuse("a round rolled on over a tangent edge has no section");
    }
    TopoDS_Face face = BRepBuilderAPI_MakeFace(boundaryWire(pieces, z), Standard_True).Face();
    Tool tool;
    tool.source = data.edge;
    tool.cut = data.convex;
    tool.rolled = true;
    tool.volume = area * length;
    tool.solid = BRepPrimAPI_MakePrism(face, z * length, Standard_True).Shape();
    tool.strips.resize(3);
    tool.strips[k].face = data.faces[k];
    tool.strips[k].width = corner.Distance(rolled.tangentPoint);
    tool.strips[k].farSide.valid = true;
    tool.strips[k].farSide.lin = gp_Lin(rolled.tangentPoint, direction);
    tool.strips[1 - k].face = data.faces[1 - k];
    tool.strips[1 - k].width = corner.Distance(rolled.touchOther);
    tool.strips[1 - k].farSide.valid = true;
    tool.strips[1 - k].farSide.lin = gp_Lin(rolled.touchOther, direction);
    tool.strips[2].face = rolled.next;
    tool.strips[2].width = rolled.tangentPoint.Distance(rolled.touchNext);
    tool.strips[2].farSide.valid = true;
    tool.strips[2].farSide.lin = gp_Lin(rolled.touchNext, direction);
    for (int i = 0; i < 2; ++i) {
        tool.caps.push_back(ends[i].trims.front());
    }
    return tool;
}

Tool ruledTool(const Context& ctx, const EdgeData& data, const VertexEnd ends[2], double r)
{
    gp_Dir direction(gp_Vec(data.start, data.end));
    double length = data.start.Distance(data.end);
    for (int i = 0; i < 2; ++i) {
        if (!ends[i].surfaceEnd.IsNull()) {
            refuse("a round of a straight edge on a cylinder that ends on a face that is not a plane");
        }
        if (ends[i].kind != VertexClass::FreeEnd || ends[i].trims.size() != 1
            || !parallel(ends[i].trims.front().normal, direction)) {
            refuse("a round of a straight edge on a cylinder that does not end square to it");
        }
    }
    const gp_Pnt& corner = data.start;
    // Each face's trace in the section plane: a line or a circle
    RuledTrace traces[2];
    for (int k = 0; k < 2; ++k) {
        traces[k] = ruledTrace(
            data,
            data.faces[k],
            corner,
            corner,
            inwardIn(data.faces[k], data.edge, data.first),
            r
        );
    }
    // The arc's centre: on the line, or the circle, offset by r from each trace; of the two
    // solutions the one nearer the corner
    std::vector<gp_Pnt> candidates = ruledCentres(traces[0], traces[1], direction, r);
    gp_Pnt centre;
    gp_Pnt touches[2];
    std::string reason;
    if (candidates.empty()) {
        reason = "no round of the radius fits between a straight edge's faces";
    }
    else {
        centre = candidates.front();
        for (const auto& p : candidates) {
            if (p.Distance(corner) < centre.Distance(corner)) {
                centre = p;
            }
        }
        // The tangent points, on each face's side of the corner
        for (int k = 0; k < 2 && reason.empty(); ++k) {
            touches[k] = ruledTouch(traces[k], centre);
            if (!ruledTouches(traces[k], touches[k], centre, r)) {
                reason = "a round of a straight edge on a cylinder that does not touch its faces";
            }
        }
    }
    if (!reason.empty()) {
        // A concave edge's ball rolls on over a face's tangent edge onto the next face
        if (data.convex) {
            refuse(reason);
        }
        std::optional<Rolled> rolled[2];
        for (int k = 0; k < 2; ++k) {
            rolled[k] = rollOn(ctx, data, traces, k, r);
        }
        if (rolled[0] && rolled[1]) {
            refuse("a round that rolls on over the tangent edges of both its faces");
        }
        for (int k = 0; k < 2; ++k) {
            if (rolled[k]) {
                return rolledTool(data, ends, traces, k, *rolled[k], r);
            }
        }
        refuse(reason);
    }
    // The section's boundary, and its area
    auto side = [&](const gp_Pnt& a, const gp_Pnt& b, const gp_Pnt& p) {
        return gp_Vec(a, b).Crossed(gp_Vec(a, p)).Dot(gp_Vec(direction));
    };
    double area = std::abs(side(corner, touches[0], touches[1])) / 2;
    TopoDS_Edge walls[2];
    for (int k = 0; k < 2; ++k) {
        const RuledTrace& t = traces[k];
        if (!t.circle) {
            walls[k] = BRepBuilderAPI_MakeEdge(corner, touches[k]).Edge();
            continue;
        }
        gp_Pnt chordMiddle((corner.XYZ() + touches[k].XYZ()) / 2);
        gp_Vec out(t.centre, chordMiddle);
        if (out.Magnitude() <= linearTolerance) {
            refuse("a round across a half cylinder");
        }
        gp_Pnt middle = t.centre.Translated(out.Normalized() * t.radius);
        walls[k]
            = BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(corner, middle, touches[k]).Value()).Edge();
        double chord = corner.Distance(touches[k]);
        double theta = 2 * std::asin(std::min(1.0, chord / (2 * t.radius)));
        double segment = t.radius * t.radius * (theta - std::sin(theta)) / 2;
        // Bulging away from the triangle adds the segment, into it takes it away
        bool bulges = side(corner, touches[k], middle) * side(corner, touches[k], touches[1 - k]) < 0;
        area += bulges ? segment : -segment;
    }
    gp_Vec toCorner(centre, corner);
    gp_Pnt arcMiddle = centre.Translated(toCorner.Normalized() * r);
    if (side(touches[0], touches[1], arcMiddle) * side(touches[0], touches[1], corner) <= 0) {
        refuse("a round of a straight edge on a cylinder that bulges away from its corner");
    }
    double chord = touches[0].Distance(touches[1]);
    double phi = 2 * std::asin(std::min(1.0, chord / (2 * r)));
    area -= r * r * (phi - std::sin(phi)) / 2;
    TopoDS_Edge arc
        = BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(touches[0], arcMiddle, touches[1]).Value())
              .Edge();
    BRepBuilderAPI_MakeWire wire(walls[0], arc, walls[1]);
    if (!wire.IsDone()) {
        refuse("building a round's section failed");
    }
    TopoDS_Face face = BRepBuilderAPI_MakeFace(wire.Wire(), Standard_True).Face();
    Tool tool;
    tool.source = data.edge;
    tool.cut = data.convex;
    tool.volume = area * length;
    tool.solid = BRepPrimAPI_MakePrism(face, gp_Vec(direction) * length, Standard_True).Shape();
    tool.strips.resize(2);
    for (int k = 0; k < 2; ++k) {
        tool.strips[k].face = data.faces[k];
        tool.strips[k].width = corner.Distance(touches[k]);
        tool.strips[k].farSide.valid = true;
        tool.strips[k].farSide.lin = gp_Lin(touches[k], direction);
    }
    for (int i = 0; i < 2; ++i) {
        tool.caps.push_back(ends[i].trims.front());
    }
    return tool;
}

bool inPlane(const TopoDS_Shape& shape, const TrimPlane& plane);
TopoDS_Shape commonOf(const TopoDS_Shape& shape, const TopoDS_Shape& other);

/** The end face's surface as a face reaching past the face (Case Base #105): the surface's natural
 * bounds where they are finite, else the face's own bounds run on by the reach. With extend, a
 * bounded surface is first extended by the reach on each side where it is not closed
 * (GeomLib::ExtendSurfByLength); null when there is nothing to extend
 */
TopoDS_Face surfaceFace(
    const TopoDS_Face& face,
    double reach,
    bool extend,
    Handle(Geom_Surface)& surface,
    TopLoc_Location& location
)
{
    surface = BRep_Tool::Surface(face, location);
    if (surface.IsNull()) {
        refuse("an end face without a surface");
    }
    if (extend) {
        Handle(Geom_BoundedSurface) bounded
            = Handle(Geom_BoundedSurface)::DownCast(surface->Copy());
        if (bounded.IsNull()) {
            return {};
        }
        bool extended = false;
        for (bool inU : {true, false}) {
            if (inU ? bounded->IsUClosed() : bounded->IsVClosed()) {
                continue;
            }
            for (bool after : {false, true}) {
                GeomLib::ExtendSurfByLength(bounded, reach, 1, inU, after);
                extended = true;
            }
        }
        if (!extended || bounded.IsNull()) {
            return {};
        }
        surface = bounded;
    }
    double u0 = 0.0;
    double u1 = 0.0;
    double v0 = 0.0;
    double v1 = 0.0;
    surface->Bounds(u0, u1, v0, v1);
    double fu0 = 0.0;
    double fu1 = 0.0;
    double fv0 = 0.0;
    double fv1 = 0.0;
    BRepTools::UVBounds(face, fu0, fu1, fv0, fv1);
    if (Precision::IsInfinite(u0)) {
        u0 = fu0 - reach;
    }
    if (Precision::IsInfinite(u1)) {
        u1 = fu1 + reach;
    }
    if (Precision::IsInfinite(v0)) {
        v0 = fv0 - reach;
    }
    if (Precision::IsInfinite(v1)) {
        v1 = fv1 + reach;
    }
    BRepBuilderAPI_MakeFace make(surface, u0, u1, v0, v1, Precision::Confusion());
    if (!make.IsDone()) {
        refuse("extending an end face's surface failed");
    }
    return TopoDS::Face(make.Face().Moved(location));
}

/** A prism's end trimmed by the end face's surface, not its plane (Case Base #105). A box over the
 * end's half of the prism and its run on is split by the surface, extended past the face, and the
 * pieces that don't hold the prism beside the edge are cut from it. The prism must come out closed
 * there (its run on's end gone), and untouched at the box's inner end, where the surface would
 * cross the tool further in than a box over the end can see. The section's parameters along the
 * edge run from its corner: inner, the box's inner end; outer, the prism's end. Returns the volume
 * cut away
 */
double trimBySurface(
    TopoDS_Shape& solid,
    Tool& tool,
    const TopoDS_Face& endFace,
    const Section& section,
    const gp_Dir& direction,
    double inner,
    double outer
)
{
    const double sign = outer > inner ? 1.0 : -1.0;
    const double span = std::abs(outer - inner);
    gp_Dir x = section.inward[0];
    gp_Dir y = direction.Crossed(x);
    // The box: around the section (within the triangle of its corner and ends) by a tenth of its
    // size, so that a surface ending not far past the face still splits it; along the edge from
    // inner to past outer
    const double margin = 0.1 * std::max(section.length[0], section.length[1]);
    double x0 = 0.0;
    double x1 = 0.0;
    double y0 = 0.0;
    double y1 = 0.0;
    for (const auto& p : section.ends) {
        gp_Vec v(section.corner, p);
        x0 = std::min(x0, v.Dot(gp_Vec(x)));
        x1 = std::max(x1, v.Dot(gp_Vec(x)));
        y0 = std::min(y0, v.Dot(gp_Vec(y)));
        y1 = std::max(y1, v.Dot(gp_Vec(y)));
    }
    double low = std::min(inner, outer + sign * margin);
    double high = std::max(inner, outer + sign * margin);
    gp_Pnt origin = section.corner.Translated(
        gp_Vec(direction) * low + gp_Vec(x) * (x0 - margin) + gp_Vec(y) * (y0 - margin)
    );
    TopoDS_Shape box = BRepPrimAPI_MakeBox(
                           gp_Ax2(origin, direction, x),
                           x1 - x0 + 2 * margin,
                           y1 - y0 + 2 * margin,
                           high - low
    )
                           .Shape();
    // Inside the tool beside the edge, near the box's inner end; and at the run on's end
    double offset = 0.05 * std::min(section.length[0], section.length[1]);
    gp_Pnt beside = section.corner.Translated(
        (gp_Vec(section.inward[0]) + gp_Vec(section.inward[1])) * offset
    );
    gp_Pnt kept = beside.Translated(gp_Vec(direction) * (inner + sign * 0.01 * span));
    gp_Pnt runOn = beside.Translated(gp_Vec(direction) * (outer - sign * 0.01 * span));
    auto holds = [](const TopoDS_Shape& piece, const gp_Pnt& point) {
        BRepClass3d_SolidClassifier classifier(piece, point, linearTolerance);
        return classifier.State() == TopAbs_IN;
    };
    const double reach = 2 * (span + margin + x1 - x0 + y1 - y0);
    for (bool extend : {false, true}) {
        Handle(Geom_Surface) surface;
        TopLoc_Location location;
        TopoDS_Face face = surfaceFace(endFace, reach, extend, surface, location);
        if (face.IsNull()) {
            break;
        }
        TopTools_ListOfShape arguments;
        arguments.Append(box);
        TopTools_ListOfShape tools;
        tools.Append(face);
        BRepAlgoAPI_Splitter splitter;
        splitter.SetArguments(arguments);
        splitter.SetTools(tools);
        splitter.SetRunParallel(Standard_False);
        splitter.Build();
        if (!splitter.IsDone() || splitter.HasErrors()) {
            refuse("splitting by an end face's surface failed");
        }
        std::vector<TopoDS_Shape> pieces;
        for (TopExp_Explorer it(splitter.Shape(), TopAbs_SOLID); it.More(); it.Next()) {
            pieces.push_back(it.Current());
        }
        int holding = 0;
        BRep_Builder builder;
        TopoDS_Compound away;
        builder.MakeCompound(away);
        bool closed = true;
        for (const auto& piece : pieces) {
            if (holds(piece, kept)) {
                ++holding;
                closed = !holds(piece, runOn);
            }
            else {
                builder.Add(away, piece);
            }
        }
        if (holding != 1) {
            refuse(
                "the surface of an end face that is not a plane leaves "
                + std::to_string(holding) + " pieces beside its edge"
            );
        }
        if (pieces.size() < 2 || !closed) {
            continue;  // the surface ends before it closes the tool: extended, once
        }
        TopoDS_Shape removed = commonOf(solid, away);
        TrimPlane innerEnd {section.corner.Translated(gp_Vec(direction) * inner), direction};
        for (TopExp_Explorer it(removed, TopAbs_FACE); it.More(); it.Next()) {
            if (inPlane(it.Current(), innerEnd)) {
                refuse("the surface of an end face crosses its tool away from the end");
            }
        }
        BRepAlgoAPI_Cut cut(solid, away);
        if (!cut.IsDone() || cut.HasErrors()) {
            refuse("trimming a tool by an end face's surface failed");
        }
        solid = cut.Shape();
        tool.capSurfaces.emplace_back(surface, location);
        return volumeOf(removed);
    }
    refuse("the surface of an end face that is not a plane does not close its tool");
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
    // An end bounded by one plane normal to the edge needs no trim: the prism ends there. An end
    // on a face that is not a plane is trimmed by its surface, past its tangent plane
    const bool curved = !ends[0].surfaceEnd.IsNull() || !ends[1].surfaceEnd.IsNull();
    bool trim[2];
    for (int i = 0; i < 2; ++i) {
        trim[i] = !ends[i].surfaceEnd.IsNull() || ends[i].trims.size() != 1
            || !parallel(ends[i].trims.front().normal, direction);
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
    // With a curved end the tool's volume is measured: the prism's, in closed form, must be what is
    // left plus what each trim cut away
    const double prism = section.area * (finish - begin);
    double removed = 0.0;
    for (int i = 0; i < 2; ++i) {
        if (!trim[i]) {
            continue;
        }
        if (!ends[i].surfaceEnd.IsNull()) {
            removed += trimBySurface(
                solid,
                tool,
                ends[i].surfaceEnd,
                section,
                direction,
                length / 2,
                i == 0 ? begin : finish
            );
            continue;
        }
        for (const auto& plane : ends[i].trims) {
            TopoDS_Shape beyond = halfSpaceBeyond(plane, 4 * ctx.scale + 4 * margin);
            if (curved) {
                removed += volumeOf(commonOf(solid, beyond));
            }
            BRepAlgoAPI_Cut cut(solid, beyond);
            if (!cut.IsDone() || cut.HasErrors()) {
                refuse("trimming a tool failed");
            }
            solid = cut.Shape();
        }
    }
    if (curved) {
        double measured = volumeOf(solid);
        if (std::abs(measured + removed - prism) > volumeTolerance * prism) {
            refuse("a tool trimmed by an end face's surface: " + describe(measured) + " left and "
                   + describe(removed) + " cut away of " + describe(prism));
        }
        tool.volume = measured;
    }
    tool.solid = solid;
    for (int i = 0; i < 2; ++i) {
        if (ends[i].kind == VertexClass::FreeEnd && ends[i].surfaceEnd.IsNull()) {
            tool.caps.push_back(ends[i].trims.front());
        }
        else if (ends[i].kind == VertexClass::Corner2Unequal) {
            tool.openEnds.push_back(ends[i].trims.front());
        }
        else if (ends[i].kind == VertexClass::Corner2Union) {
            tool.unionEnds.push_back(ends[i].trims.front());
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
        if (!ends[i].surfaceEnd.IsNull()) {
            refuse("an arc that ends on a face that is not a plane");
        }
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
        // (a spindle or horn torus: the section revolved instead, below)
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
        else if (major < 0) {
            // The centre's circle is on the other side of the axis: no ball of the radius fits
            // against the arc (cause C4, shape A)
            refuse("a fillet whose torus crosses its axis");
        }
        else if (major < section.radius + linearTolerance) {
            // A spindle or horn torus (cause C4, shapes B and C): the round uses only the part of
            // it between the radii major and major + radius, which never reaches the axis, but
            // BRepPrimAPI_MakeTorus needs major > minor. Revolve the section itself instead; its
            // volume is the closed form's (Pappus), and OCCT stores the round as a surface of
            // revolution rather than a torus
            solid = BRepPrimAPI_MakeRevol(section.face(), axis, span, Standard_True).Shape();
        }
        else {
            round = BRepPrimAPI_MakeTorus(frame, major, section.radius).Shape();
        }
        if (solid.IsNull()) {
            BRepAlgoAPI_Cut cut(ring, round);
            if (!cut.IsDone() || cut.HasErrors()) {
                refuse("building a revolved tool failed");
            }
            solid = cut.Shape();
        }
    }
    tool.solid = solid;
    for (int i = 0; i < 2 && !data.closed; ++i) {
        if (ends[i].kind == VertexClass::FreeEnd) {
            tool.caps.push_back(ends[i].trims.front());
        }
        else if (ends[i].kind == VertexClass::Corner2Union) {
            tool.unionEnds.push_back(ends[i].trims.front());
        }
    }
    return tool;
}

/** A wall next to a rim edge, seen in the plane of the rim's top face (ops#640, C4 shape A;
 * notes/fillet-tight-arc.md): a plane or a cylinder normal to the top face. depth() is the inward
 * depth into the material, gradient() its unit gradient (into the material).
 */
struct PlanWall
{
    bool line = true;
    gp_XY point;   // line: a point on the wall
    gp_XY normal;  // line: inward
    gp_XY centre;  // cylinder: its axis
    double radius = 0.0;
    /// +1: the material lies outside the cylinder (a hollow wall), -1: inside (a bulging wall)
    double sign = 1.0;

    double depth(const gp_XY& q) const
    {
        return line ? normal.Dot(q - point) : sign * ((q - centre).Modulus() - radius);
    }

    gp_XY gradient(const gp_XY& q) const
    {
        if (line) {
            return normal;
        }
        gp_XY v = q - centre;
        double length = v.Modulus();
        if (length < linearTolerance) {
            refuse("a tight corner's centre on a wall cylinder's axis");
        }
        return v * (sign / length);
    }
};

/// The frame of a tight wall arc: origin at the arc's centre, z the top face's outward normal
struct TightFrame
{
    gp_Pnt origin;
    gp_Dir x;
    gp_Dir y;
    gp_Dir z;

    gp_XY plan(const gp_Vec& v) const
    {
        return gp_XY(v.Dot(gp_Vec(x)), v.Dot(gp_Vec(y)));
    }

    gp_XY plan(const gp_Pnt& p) const
    {
        return plan(gp_Vec(origin, p));
    }

    gp_Pnt point(const gp_XY& q, double height) const
    {
        return origin.Translated(gp_Vec(x) * q.X() + gp_Vec(y) * q.Y() + gp_Vec(z) * height);
    }

    gp_Vec vector(const gp_XY& q, double height) const
    {
        return gp_Vec(x) * q.X() + gp_Vec(y) * q.Y() + gp_Vec(z) * height;
    }
};

/// The wall of a rim edge whose other face is the top, in plan; empty when it is not a plane or
/// a cylinder normal to the top
std::optional<PlanWall> planWall(const TightFrame& frame, const EdgeData& data, const TopoDS_Face& top)
{
    int k = 0;
    if (data.faces[0].IsSame(top)) {
        k = 1;
    }
    else if (!data.faces[1].IsSame(top)) {
        return std::nullopt;
    }
    const TopoDS_Face& wall = data.faces[k];
    BRepAdaptor_Curve curve(data.edge);
    gp_Pnt middle = curve.Value((data.first + data.last) / 2);
    gp_Dir out = outwardNormal(wall, middle);
    if (std::abs(out.Dot(frame.z)) > 1e-9) {
        return std::nullopt;
    }
    gp_XY outPlan = frame.plan(gp_Vec(out));
    BRepAdaptor_Surface surface(wall, Standard_False);
    PlanWall result;
    if (surface.GetType() == GeomAbs_Plane) {
        result.line = true;
        result.point = frame.plan(middle);
        result.normal = -outPlan.Normalized();
        return result;
    }
    if (surface.GetType() == GeomAbs_Cylinder) {
        gp_Cylinder cylinder = surface.Cylinder();
        if (std::abs(cylinder.Axis().Direction().Dot(frame.z)) < 1 - 1e-9) {
            return std::nullopt;
        }
        result.line = false;
        result.centre = frame.plan(cylinder.Location());
        result.radius = cylinder.Radius();
        gp_XY radial = frame.plan(middle) - result.centre;
        result.sign = outPlan.Dot(radial) < 0 ? 1.0 : -1.0;
        return result;
    }
    return std::nullopt;
}

/** A convex rim arc on a bulging wall whose radius is below the round's (C4 shape A): its round
 * would be a spindle torus, and Onshape's corner is a canal surface instead (tightTool).
 */
bool tightArc(const Context& ctx, const EdgeData& data)
{
    if (data.line || data.ruled || !data.convex || ctx.request.kind != Kind::Fillet) {
        return false;
    }
    double r = ctx.request.size1;
    if (data.circle.Radius() >= r - linearTolerance) {
        return false;
    }
    const TopoDS_Face& top = data.faces[data.planeFace];
    const TopoDS_Face& wall = data.faces[1 - data.planeFace];
    BRepAdaptor_Surface surface(wall, Standard_False);
    if (surface.GetType() != GeomAbs_Cylinder) {
        return false;
    }
    TightFrame frame;
    frame.origin = data.circle.Location();
    frame.z = outwardNormal(top, data.start);
    frame.x = data.circle.XAxis().Direction();
    frame.y = frame.z.Crossed(frame.x);
    auto plan = planWall(frame, data, top);
    return plan && !plan->line && plan->sign < 0;
}

/// The plan point at the same inward depth from both walls, by Newton from q
gp_XY solveCentre(const PlanWall walls[2], gp_XY q, double depth)
{
    for (int iteration = 0; iteration < 60; ++iteration) {
        double f1 = walls[0].depth(q) - depth;
        double f2 = walls[1].depth(q) - depth;
        gp_XY a = walls[0].gradient(q);
        gp_XY b = walls[1].gradient(q);
        double det = a.X() * b.Y() - a.Y() * b.X();
        if (std::abs(det) < 1e-14) {
            refuse("the walls at a tight corner are parallel");
        }
        double dx = (f1 * b.Y() - f2 * a.Y()) / det;
        double dy = (a.X() * f2 - b.X() * f1) / det;
        q.SetCoord(q.X() - dx, q.Y() - dy);
        if (std::abs(dx) + std::abs(dy) < 1e-14) {
            break;
        }
    }
    if (std::abs(walls[0].depth(q) - depth) + std::abs(walls[1].depth(q) - depth) > 1e-9) {
        refuse("a tight corner's centre curve did not converge");
    }
    return q;
}

/// Interpolates the points at the parameters with a cubic B-spline curve
Handle(Geom_BSplineCurve) interpolated(
    const std::vector<gp_Pnt>& points,
    const Handle(TColStd_HArray1OfReal) & parameters
)
{
    Handle(TColgp_HArray1OfPnt) array = new TColgp_HArray1OfPnt(1, static_cast<int>(points.size()));
    for (std::size_t i = 0; i < points.size(); ++i) {
        array->SetValue(static_cast<int>(i) + 1, points[i]);
    }
    GeomAPI_Interpolate interpolate(array, parameters, Standard_False, linearTolerance);
    interpolate.Perform();
    if (!interpolate.IsDone()) {
        refuse("interpolating a tight corner's surface failed");
    }
    return interpolate.Curve();
}

/** The tool of a tight wall arc (C4 shape A, notes/fillet-tight-arc.md, a port of
 * probes/c4/tight.py): Onshape's corner face is the canal surface of a ball of radius rho (the
 * arc's) whose centre S(theta) lies at d = r - rho from both neighbouring rounds' spines, in plan
 * at the inward depth r - d cos(theta) from both neighbour walls, at the height z0 + d sin(theta)
 * (z0 = top - r), theta from 0 (S at the arc's centre) to 90 deg (under the point where the two
 * rounds' top edges cross). The tool is everything beyond that canal patch between the two fans
 * that leave the neighbouring rounds along their normals: five B-spline faces sharing their
 * boundary poles, sewn into one solid. With the neighbours' tools unchanged, base - their tools -
 * this one is Onshape's solid. It has no closed-form volume: it is measured (Tool::measured), and
 * checked instead by the patch's distance from S and the solid's validity.
 */
Tool tightTool(
    const Context& ctx,
    const EdgeData& data,
    const VertexEnd ends[2],
    const std::vector<EdgeData>& all
)
{
    const gp_Circ& circle = data.circle;
    const TopoDS_Face& top = data.faces[data.planeFace];
    double r = ctx.request.size1;
    double rho = circle.Radius();
    double d = r - rho;
    TightFrame frame;
    frame.origin = circle.Location();
    frame.z = outwardNormal(top, data.start);
    frame.x = circle.XAxis().Direction();
    frame.y = frame.z.Crossed(frame.x);
    if (data.closed) {
        refuse("a closed wall arc tighter than the round");
    }
    PlanWall walls[2];
    for (int i = 0; i < 2; ++i) {
        if (ends[i].kind != VertexClass::TangentContinuation) {
            refuse("a wall arc tighter than the round that does not continue tangentially at both ends");
        }
        auto other = std::find_if(all.begin(), all.end(), [&](const EdgeData& e) {
            return e.edge.IsSame(ends[i].continuation);
        });
        if (other == all.end()) {
            refuse("a tangent edge that was not analysed");
        }
        if (tightArc(ctx, *other)) {
            refuse("two wall arcs tighter than the round in a row");
        }
        auto wall = planWall(frame, *other, top);
        if (!wall) {
            refuse("a tight wall arc's neighbour is not a plane or a cylinder normal to the top face");
        }
        walls[i] = *wall;
    }

    // The centre curve S, its plan points and heights
    constexpr int intervals = 96;
    double z0 = -r;
    std::vector<double> theta(intervals + 1);
    std::vector<gp_XY> plan(intervals + 1);
    std::vector<gp_Pnt> spine(intervals + 1);
    gp_XY q(0.0, 0.0);
    for (int i = 0; i <= intervals; ++i) {
        theta[i] = pi / 2 * i / intervals;
        q = solveCentre(walls, q, r - d * std::cos(theta[i]));
        plan[i] = q;
        spine[i] = frame.point(q, z0 + d * std::sin(theta[i]));
    }

    // Per theta, at the distance lambda from S: the contact points along the two directions from
    // the neighbours' spines through S, and the rational middle pole between them
    struct Columns
    {
        std::vector<gp_Pnt> side[2];
        std::vector<gp_Pnt> homogeneous;
        std::vector<gp_Pnt> weight;
    };
    auto columns = [&](double lambda) {
        Columns c;
        for (int i = 0; i <= intervals; ++i) {
            double t = theta[i];
            gp_Vec u[2];
            for (int k = 0; k < 2; ++k) {
                gp_XY n = walls[k].gradient(plan[i]);
                u[k] = frame.vector(n * -std::cos(t), std::sin(t));
            }
            gp_Vec m = u[0] + u[1];
            if (m.Magnitude() < 1e-9) {
                refuse("the rounds at a tight corner meet head on");
            }
            m.Normalize();
            double ch = std::max(-1.0, std::min(1.0, m.Dot(u[0])));  // cos(alpha / 2)
            if (ch < 1e-6) {
                refuse("the rounds at a tight corner meet at a straight angle or more");
            }
            for (int k = 0; k < 2; ++k) {
                c.side[k].push_back(spine[i].Translated(u[k] * lambda));
            }
            gp_XYZ middle = spine[i].Translated(m * (lambda / ch)).XYZ() * ch;
            c.homogeneous.emplace_back(middle);
            c.weight.emplace_back(ch, 0.0, 0.0);
        }
        return c;
    };
    Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, intervals + 1);
    for (int i = 0; i <= intervals; ++i) {
        parameters->SetValue(i + 1, theta[i]);
    }
    struct Row
    {
        std::vector<gp_Pnt> poles[3];  // side 0, middle, side 1
        std::vector<double> weights;
    };
    Handle(Geom_BSplineCurve) model;
    auto sameKnots = [&](const Handle(Geom_BSplineCurve)& curve) {
        if (model.IsNull()) {
            model = curve;
            return;
        }
        if (curve->NbKnots() != model->NbKnots() || curve->NbPoles() != model->NbPoles()
            || curve->Degree() != model->Degree()) {
            refuse("a tight corner's columns have different knots");
        }
        for (int i = 1; i <= curve->NbKnots(); ++i) {
            if (std::abs(curve->Knot(i) - model->Knot(i)) > 1e-12
                || curve->Multiplicity(i) != model->Multiplicity(i)) {
                refuse("a tight corner's columns have different knots");
            }
        }
    };
    auto polesOf = [&](const std::vector<gp_Pnt>& points) {
        Handle(Geom_BSplineCurve) curve = interpolated(points, parameters);
        sameKnots(curve);
        std::vector<gp_Pnt> poles;
        for (int i = 1; i <= curve->NbPoles(); ++i) {
            poles.push_back(curve->Pole(i));
        }
        return poles;
    };
    double outer = 2.0 * r;
    // The wedge's inner surface, inside both neighbours' balls (so clear of their tools)
    double inner = rho / 4;
    Row rows[3];  // at rho (the patch), at the outer radius, at the inner radius
    for (int j = 0; j < 3; ++j) {
        Columns c = columns(j == 0 ? rho : j == 1 ? outer : inner);
        rows[j].poles[0] = polesOf(c.side[0]);
        rows[j].poles[2] = polesOf(c.side[1]);
        std::vector<gp_Pnt> homogeneous = polesOf(c.homogeneous);
        std::vector<gp_Pnt> weight = polesOf(c.weight);
        for (std::size_t i = 0; i < homogeneous.size(); ++i) {
            double w = weight[i].X();
            if (w <= 1e-9) {
                refuse("a tight corner's surface has a weight that is not positive");
            }
            rows[j].poles[1].emplace_back(homogeneous[i].XYZ() / w);
            rows[j].weights.push_back(w);
        }
    }
    int poleCount = model->NbPoles();
    int knotCount = model->NbKnots();
    TColStd_Array1OfReal uKnots(1, knotCount);
    TColStd_Array1OfInteger uMults(1, knotCount);
    for (int i = 1; i <= knotCount; ++i) {
        uKnots.SetValue(i, model->Knot(i));
        uMults.SetValue(i, model->Multiplicity(i));
    }
    TColStd_Array1OfReal vKnots(1, 2);
    vKnots.SetValue(1, 0.0);
    vKnots.SetValue(2, 1.0);
    // Along theta (u) the columns' degree, across (v) degree 2 rational (the canal patch and its
    // copy at the outer radius) or 1 (the fans)
    auto surface = [&](const std::vector<std::vector<gp_Pnt>>& across,
                       const std::vector<std::vector<double>>& weights,
                       int vDegree) -> Handle(Geom_BSplineSurface) {
        int nv = static_cast<int>(across.size());
        TColgp_Array2OfPnt poles(1, poleCount, 1, nv);
        TColStd_Array2OfReal w(1, poleCount, 1, nv);
        for (int i = 1; i <= poleCount; ++i) {
            for (int k = 1; k <= nv; ++k) {
                poles.SetValue(i, k, across[k - 1][i - 1]);
                w.SetValue(i, k, weights[k - 1][i - 1]);
            }
        }
        TColStd_Array1OfInteger vMults(1, 2);
        vMults.SetValue(1, vDegree + 1);
        vMults.SetValue(2, vDegree + 1);
        return new Geom_BSplineSurface(poles, w, uKnots, vKnots, uMults, vMults, model->Degree(), vDegree);
    };
    std::vector<double> ones(poleCount, 1.0);
    std::vector<Handle(Geom_Surface)> surfaces;
    for (int j = 0; j < 2; ++j) {
        surfaces.push_back(surface(
            {rows[j].poles[0], rows[j].poles[1], rows[j].poles[2]},
            {ones, rows[j].weights, ones},
            2
        ));
    }
    // The fans run from the inner radius to the outer one, the tool's faces on them from rho:
    // the columns are linear in lambda, so the fans hold the patch's sides exactly
    for (int k : {0, 2}) {
        surfaces.push_back(surface({rows[2].poles[k], rows[1].poles[k]}, {ones, ones}, 1));
    }
    const double fanFrom = (rho - inner) / (outer - inner);
    // The flat end in the z0 plane, at theta = 0: degree 1 from row `from` to the outer radius,
    // degree 2 rational across
    auto endSurface = [&](int from) -> Handle(Geom_Surface) {
        TColgp_Array2OfPnt poles(1, 2, 1, 3);
        TColStd_Array2OfReal w(1, 2, 1, 3);
        for (int jj = 0; jj < 2; ++jj) {
            int j = jj == 0 ? from : 1;
            for (int k = 0; k < 3; ++k) {
                poles.SetValue(jj + 1, k + 1, rows[j].poles[k].front());
                w.SetValue(jj + 1, k + 1, k == 1 ? rows[j].weights.front() : 1.0);
            }
        }
        TColStd_Array1OfReal knots(1, 2);
        knots.SetValue(1, 0.0);
        knots.SetValue(2, 1.0);
        TColStd_Array1OfInteger uM(1, 2);
        uM.SetValue(1, 2);
        uM.SetValue(2, 2);
        TColStd_Array1OfInteger vM(1, 2);
        vM.SetValue(1, 3);
        vM.SetValue(2, 3);
        return new Geom_BSplineSurface(poles, w, knots, knots, uM, vM, 1, 2);
    };
    surfaces.push_back(endSurface(0));

    // Each sewn into one closed shell, one valid solid
    auto sewnSolid = [&](const std::vector<TopoDS_Face>& faces) {
        BRepBuilderAPI_Sewing sewing(1e-6);
        for (const auto& face : faces) {
            sewing.Add(face);
        }
        sewing.Perform();
        TopoDS_Shape sewn = sewing.SewedShape();
        TopoDS_Shell shell;
        int shells = 0;
        for (TopExp_Explorer it(sewn, TopAbs_SHELL); it.More(); it.Next()) {
            shell = TopoDS::Shell(it.Current());
            ++shells;
        }
        if (shells != 1 || !BRep_Tool::IsClosed(shell)) {
            refuse("a tight corner's faces do not sew into one closed shell");
        }
        BRepBuilderAPI_MakeSolid makeSolid(shell);
        if (!makeSolid.IsDone()) {
            refuse("building a tight corner's solid failed");
        }
        TopoDS_Solid built = makeSolid.Solid();
        BRepLib::OrientClosedSolid(built);
        return built;
    };
    // vFrom: a fan's face starts at rho, not at the inner radius
    auto faceOf = [&](const Handle(Geom_Surface)& s, double vFrom = -1.0) {
        double u0 = 0.0;
        double u1 = 0.0;
        double v0 = 0.0;
        double v1 = 0.0;
        s->Bounds(u0, u1, v0, v1);
        BRepBuilderAPI_MakeFace face(s, u0, u1, vFrom < 0 ? v0 : vFrom, v1, Precision::Confusion());
        if (!face.IsDone()) {
            refuse("building a tight corner's face failed");
        }
        return face.Face();
    };
    TopoDS_Solid solid = sewnSolid(
        {faceOf(surfaces[0]),
         faceOf(surfaces[1]),
         faceOf(surfaces[2], fanFrom),
         faceOf(surfaces[3], fanFrom),
         faceOf(surfaces[4])}
    );
    TopoDS_Solid wedge = sewnSolid(
        {faceOf(surface({rows[2].poles[0], rows[2].poles[1], rows[2].poles[2]}, {ones, rows[2].weights, ones}, 2)),
         faceOf(surfaces[1]),
         faceOf(surfaces[2]),
         faceOf(surfaces[3]),
         faceOf(endSurface(2))}
    );
    if (!BRepCheck_Analyzer(wedge).IsValid() || volumeOf(wedge) <= volumeOf(solid)) {
        refuse("a tight corner's wedge is not a valid solid around its tool");
    }
    // The patch's edge at theta = 0 is the wall arc at depth r, exactly a circle: given as one, so
    // that the result keeps the wall's own arc where the patch meets the wall (as Onshape does)
    {
        gp_Circ wallArc(gp_Ax2(frame.point(gp_XY(0.0, 0.0), z0), frame.z, frame.x), rho);
        auto onArc = [&](const gp_Pnt& p) {
            gp_Vec v(frame.point(gp_XY(0.0, 0.0), z0), p);
            double height = v.Dot(gp_Vec(frame.z));
            double radial = (v - gp_Vec(frame.z) * height).Magnitude();
            return std::abs(height) < 1e-7 * std::max(1.0, r) && std::abs(radial - rho) < 1e-7 * std::max(1.0, r);
        };
        int replaced = 0;
        BRep_Builder builder;
        for (TopExp_Explorer it(solid, TopAbs_EDGE); it.More(); it.Next()) {
            TopoDS_Edge edge = TopoDS::Edge(it.Current());
            double first = 0.0;
            double last = 0.0;
            Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);
            if (curve.IsNull() || curve->IsKind(STANDARD_TYPE(Geom_Circle))) {
                continue;
            }
            gp_Pnt a = curve->Value(first);
            gp_Pnt b = curve->Value(last);
            gp_Pnt m = curve->Value((first + last) / 2);
            if (!onArc(a) || !onArc(b) || !onArc(m) || a.Distance(b) < linearTolerance) {
                continue;
            }
            // Counterclockwise about z from a to b through m, or the reversed circle
            gp_Circ c = wallArc;
            double ua = ElCLib::Parameter(c, a);
            double ub = ElCLib::Parameter(c, b);
            double um = ElCLib::Parameter(c, m);
            auto inRange = [](double u0, double u1, double u) {
                while (u1 < u0) {
                    u1 += 2 * pi;
                }
                while (u < u0) {
                    u += 2 * pi;
                }
                return u <= u1;
            };
            if (!inRange(ua, ub, um)) {
                c = gp_Circ(gp_Ax2(c.Location(), c.Axis().Direction().Reversed(), c.XAxis().Direction()), rho);
                ua = ElCLib::Parameter(c, a);
                ub = ElCLib::Parameter(c, b);
            }
            while (ub < ua) {
                ub += 2 * pi;
            }
            builder.UpdateEdge(edge, new Geom_Circle(c), BRep_Tool::Tolerance(edge));
            builder.Range(edge, ua, ub, Standard_True);
            builder.SameRange(edge, Standard_False);
            builder.SameParameter(edge, Standard_False);
            BRepLib::SameParameter(edge, 1e-7);
            if (!BRep_Tool::SameParameter(edge) || BRep_Tool::Tolerance(edge) > 1e-6) {
                refuse("a tight corner's wall arc could not be given as a circle");
            }
            ++replaced;
        }
        if (replaced != 1) {
            refuse("a tight corner's tool has no single edge on the wall arc");
        }
    }
    if (!BRepCheck_Analyzer(solid).IsValid() || volumeOf(solid) <= 0.0) {
        refuse("a tight corner's tool is not a valid solid");
    }

    // The patch lies at rho from S: sampled against a dense S
    std::vector<gp_Pnt> dense;
    {
        constexpr int denseIntervals = 4000;
        gp_XY p(0.0, 0.0);
        for (int i = 0; i <= denseIntervals; ++i) {
            double t = pi / 2 * i / denseIntervals;
            p = solveCentre(walls, p, r - d * std::cos(t));
            dense.push_back(frame.point(p, z0 + d * std::sin(t)));
        }
    }
    auto distanceToSpine = [&](const gp_Pnt& point) {
        double best = std::numeric_limits<double>::max();
        for (std::size_t i = 0; i + 1 < dense.size(); ++i) {
            gp_Vec segment(dense[i], dense[i + 1]);
            gp_Vec to(dense[i], point);
            double length2 = segment.SquareMagnitude();
            double s = length2 > 0 ? std::clamp(to.Dot(segment) / length2, 0.0, 1.0) : 0.0;
            best = std::min(best, point.Distance(dense[i].Translated(segment * s)));
        }
        return best;
    };
    const Handle(Geom_Surface)& patch = surfaces.front();
    double worst = 0.0;
    for (int i = 0; i < intervals; ++i) {
        double u = (theta[i] + theta[i + 1]) / 2;
        for (double v : {0.0, 0.25, 0.5, 0.75, 1.0}) {
            worst = std::max(worst, std::abs(distanceToSpine(patch->Value(u, v)) - rho));
        }
    }
    if (worst > 1e-5 * std::max(1.0, r)) {
        refuse("a tight corner's surface strays " + describe(worst) + " from its canal surface");
    }

    Tool tool;
    tool.solid = solid;
    tool.source = data.edge;
    tool.cut = true;
    tool.measured = true;
    tool.wedge = wedge;
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
        if (!tool.capSurfaces.empty()) {
            TopLoc_Location location;
            const Handle(Geom_Surface)& surface = BRep_Tool::Surface(face, location);
            for (const auto& [capSurface, capLocation] : tool.capSurfaces) {
                if (surface == capSurface && location.IsEqual(capLocation)) {
                    tool.capFaces.push_back(face);
                    break;
                }
            }
        }
        for (const auto& end : tool.openEnds) {
            if (inPlane(face, end)) {
                tool.contactFaces.push_back(face);
                break;
            }
        }
        for (const auto& end : tool.unionEnds) {
            if (inPlane(face, end)) {
                tool.unionEndFaces.push_back(face);
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

/// Two faces touch: they come within the linear tolerance of each other
bool touch(const TopoDS_Shape& face, const TopoDS_Shape& other)
{
    BRepExtrema_DistShapeShape distance(face, other);
    return distance.IsDone() && distance.Value() <= 10 * linearTolerance;
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

/// Whether the two tools' sources (edges, or a corner piece's vertex) share a vertex
bool neighbours(const TopoDS_Shape& a, const TopoDS_Shape& b)
{
    TopTools_IndexedMapOfShape vertices;
    TopExp::MapShapes(a, TopAbs_VERTEX, vertices);
    for (TopExp_Explorer it(b, TopAbs_VERTEX); it.More(); it.Next()) {
        if (vertices.Contains(it.Current())) {
            return true;
        }
    }
    return false;
}

/** How long a stretch of the edge the part of a strip off its face runs along: the edge's
 * common part with it (a Boolean of mixed dimensions keeps the edge's pieces on it). A strip that
 * only grazes the edge at a point (at a vertex where it runs off over another edge) has none
 */
double lengthAlong(const TopoDS_Edge& edge, const TopoDS_Shape& off)
{
    TopTools_ListOfShape arguments;
    arguments.Append(edge);
    TopTools_ListOfShape tools;
    tools.Append(off);
    BRepAlgoAPI_Common common;
    common.SetArguments(arguments);
    common.SetTools(tools);
    common.SetNonDestructive(Standard_True);
    common.SetRunParallel(Standard_False);
    common.Build();
    if (!common.IsDone() || common.HasErrors()) {
        refuse("finding where a tangent strip runs off its face failed");
    }
    double length = 0.0;
    for (TopExp_Explorer it(common.Shape(), TopAbs_EDGE); it.More(); it.Next()) {
        length += perimeterOf(it.Current());
    }
    return length;
}

/** The wall runs straight back from the planar face: a plane whose normal is square to the face's,
 * or a cylinder whose axis is the face's normal (a groove's floor, behind the groove's wall).
 * Behind the face, such a wall's surface is the base's section in front of the face swept back
 * (behindWalls), the region that Onshape's trim of a chamfer there leaves to the material
 */
bool wallAlongNormal(const TopoDS_Face& face, const TopoDS_Face& wall)
{
    BRepAdaptor_Surface surface(face, Standard_False);
    if (surface.GetType() != GeomAbs_Plane) {
        return false;
    }
    const gp_Dir normal = surface.Plane().Axis().Direction();
    BRepAdaptor_Surface other(wall, Standard_False);
    switch (other.GetType()) {
        case GeomAbs_Plane:
            return std::abs(other.Plane().Axis().Direction().Dot(normal)) < angularTolerance;
        case GeomAbs_Cylinder:
            return parallel(other.Cylinder().Axis().Direction(), normal);
        default:
            return false;
    }
}

/** A cut tool's strip that runs off its face (ops#640, S3) across a convex edge, onto a face that
 * turns away from the face's outward side, is trimmed by the air beyond (Onshape's KP1-KP4).
 *
 * Across a concave edge, into a wall that rises from the face, Onshape trims the tool by the
 * wall's surface run on behind the face: the wall's face grows under the dress-up and no step is
 * left (Q-LEDGE LD1-LD3: a step's top edge chamfered or rounded 1.0 over a wall 0.963 or 0.5
 * high; Case Base row 15, a keyhole groove's lip chamfered 1.0 over a groove wall 0.963 to 1.0
 * wide). The fallback builds that where the wall runs straight back from a planar face
 * (wallAlongNormal), listing the wall in walls for the caller's trim (clipTool), and refuses any
 * other wall.
 *
 * Returns whether it runs off across an edge that is not selected, along a stretch of it: past
 * the face's far side (a keyhole wall's top, its outer loop), not over a neighbouring selected
 * edge (a lens's tips, where each arc's strip runs over the other arc)
 */
bool checkRunOff(
    const TopoDS_Face& face,
    const TopoDS_Shape& contact,
    const TopoDS_Shape& source,
    const TopTools_IndexedDataMapOfShapeListOfShape& edgeFaces,
    const TopTools_IndexedMapOfShape& selected,
    std::vector<TopoDS_Face>& walls
)
{
    BRepAlgoAPI_Cut outside(contact, face);
    if (!outside.IsDone() || outside.HasErrors()) {
        refuse("finding where a tangent strip runs off its face failed");
    }
    const TopoDS_Shape off = outside.Shape();
    bool pastUnselected = false;
    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        // A seam (a cylinder's) stays on the face
        if (edge.IsSame(source) || BRep_Tool::IsClosed(edge, face) || !touch(edge, off)) {
            continue;
        }
        const auto* faces = edgeFaces.Seek(edge);
        TopoDS_Face next;
        if (faces) {
            for (const auto& other : *faces) {
                if (!other.IsSame(face)) {
                    next = TopoDS::Face(other);
                }
            }
        }
        if (next.IsNull()) {
            refuse("a tangent strip runs off its face over an edge with one face");
        }
        BRepAdaptor_Curve curve(edge);
        double middle = (curve.FirstParameter() + curve.LastParameter()) / 2;
        gp_Dir away = inwardIn(next, edge, middle);
        if (away.Dot(outwardNormal(face, curve.Value(middle))) > -1e-6) {
            if (!wallAlongNormal(face, next)) {
                refuse("a tangent strip runs off its face into a wall");
            }
            if (std::none_of(walls.begin(), walls.end(), [&](const TopoDS_Face& wall) {
                    return wall.IsSame(next);
                })) {
                walls.push_back(next);
            }
        }
        // Along more than the tolerance of a grazing contact, by a margin
        if (!pastUnselected && !selected.Contains(edge)
            && lengthAlong(edge, off) > 1000 * linearTolerance) {
            pastUnselected = true;
        }
    }
    return pastUnselected;
}

/** A fused tool's strip that runs off its face (ops#640, #15 past the limit) must run into the
 * base's material, which absorbs the tool there: the groove's chamfer past its wall, clipped by
 * the groove's opposite face (Onshape's, oracle 9d). Into the air, nothing would trim it
 */
void checkFusedRunOff(const TopoDS_Face& face, const TopoDS_Shape& contact, const TopoDS_Shape& base)
{
    BRepAlgoAPI_Cut outside(contact, face);
    if (!outside.IsDone() || outside.HasErrors()) {
        refuse("finding where a tangent strip runs off its face failed");
    }
    BRepClass3d_SolidClassifier inBase(base);
    bool any = false;
    for (TopExp_Explorer it(outside.Shape(), TopAbs_FACE); it.More(); it.Next()) {
        BRepAdaptor_Surface surface(TopoDS::Face(it.Current()));
        double u = (surface.FirstUParameter() + surface.LastUParameter()) / 2;
        double v = (surface.FirstVParameter() + surface.LastVParameter()) / 2;
        inBase.Perform(surface.Value(u, v), linearTolerance);
        if (inBase.State() != TopAbs_IN) {
            refuse("a concave dress-up runs past its face into the air");
        }
        any = true;
    }
    if (!any) {
        refuse("finding where a tangent strip runs off its face failed");
    }
}

/// A fused tool's strip that runs off its face: the face's edges it runs over, each with the face
/// beyond it (for trimFusedTool)
struct FusedRun
{
    const Tool* tool = nullptr;
    TopoDS_Face face;
    std::vector<std::pair<TopoDS_Edge, TopoDS_Face>> edges;
};

/// The edges of the face that the contact runs over, off the face, each with the face beyond it
std::vector<std::pair<TopoDS_Edge, TopoDS_Face>> fusedRunOffEdges(
    const TopoDS_Face& face,
    const TopoDS_Shape& contact,
    const TopoDS_Shape& source,
    const TopTools_IndexedDataMapOfShapeListOfShape& edgeFaces
)
{
    BRepAlgoAPI_Cut outside(contact, face);
    if (!outside.IsDone() || outside.HasErrors()) {
        refuse("finding where a tangent strip runs off its face failed");
    }
    const TopoDS_Shape off = outside.Shape();
    std::vector<std::pair<TopoDS_Edge, TopoDS_Face>> edges;
    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        // Along a stretch of it, as checkRunOff's: an edge the off part only touches at a point
        // is not run over
        if (edge.IsSame(source) || BRep_Tool::IsClosed(edge, face) || !touch(edge, off)
            || lengthAlong(edge, off) <= 1000 * linearTolerance) {
            continue;
        }
        const auto* faces = edgeFaces.Seek(edge);
        if (!faces) {
            continue;
        }
        for (const auto& other : *faces) {
            if (!other.IsSame(face)) {
                edges.emplace_back(edge, TopoDS::Face(other));
            }
        }
    }
    return edges;
}

/// Adds the edges a fused tool's contact runs over, off the face, to the tool's run on that face
void noteFusedRun(
    std::vector<FusedRun>& runs,
    const Tool* tool,
    const TopoDS_Face& face,
    const TopoDS_Shape& contact,
    const TopTools_IndexedDataMapOfShapeListOfShape& edgeFaces
)
{
    auto run = std::find_if(runs.begin(), runs.end(), [&](const FusedRun& r) {
        return r.tool == tool && r.face.IsSame(face);
    });
    if (run == runs.end()) {
        runs.push_back({tool, face, {}});
        run = std::prev(runs.end());
    }
    for (auto& edge : fusedRunOffEdges(face, contact, tool->source, edgeFaces)) {
        if (std::none_of(run->edges.begin(), run->edges.end(), [&](const auto& e) {
                return e.first.IsSame(edge.first) && e.second.IsSame(edge.second);
            })) {
            run->edges.push_back(std::move(edge));
        }
    }
}

/** The miter piece at a chamfer's concave corner with a circle (ops#640, #15): the two tools end
 * on the planes through the vertex normal to their edges, and leave a wedge of air between those
 * planes, where Onshape's chamfers meet in a sharp miter (oracle 9d: no patch, at and past the
 * limit). The piece is the common part of the two tools run on past the vertex: each tool's end
 * face there swept on (an arc's revolved further about its axis, a line's extruded further).
 * Each sweep lies beyond its tool's end plane, so the piece is interior-disjoint from both tools.
 * Swept twice as far, the piece must not change: the miter ends inside the sweeps
 */
Tool miterTool(
    const std::vector<Tool>& tools,
    const std::vector<EdgeData>& data,
    const TopoDS_Vertex& vertex
)
{
    struct Side
    {
        const EdgeData* data = nullptr;
        const Tool* tool = nullptr;
        TopoDS_Face end;
        TrimPlane plane;
    };
    std::vector<Side> sides;
    double reach = 1.0;
    for (const auto& d : data) {
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopExp::Vertices(d.edge, first, last);
        if (!first.IsSame(vertex) && !last.IsSame(vertex)) {
            continue;
        }
        Side side;
        side.data = &d;
        for (const auto& tool : tools) {
            if (tool.source.IsSame(d.edge)) {
                side.tool = &tool;
            }
        }
        if (!side.tool) {
            refuse("a tool at a concave corner with a circle has no length");
        }
        double parameter = 0.0;
        gp_Dir away = awayFrom(d.edge, vertex, &parameter);
        side.plane = {BRepAdaptor_Curve(d.edge).Value(parameter), away.Reversed()};
        for (const auto& face : side.tool->unionEndFaces) {
            if (inPlane(face, side.plane)) {
                if (!side.end.IsNull()) {
                    refuse("a tool with two end faces at a concave corner with a circle");
                }
                side.end = TopoDS::Face(face);
            }
        }
        if (side.end.IsNull()) {
            refuse("a tool without its end face at a concave corner with a circle");
        }
        Bnd_Box box;
        BRepBndLib::Add(side.end, box);
        reach = std::max(reach, 1.0 + 2 * std::sqrt(box.SquareExtent()));
        sides.push_back(side);
    }
    if (sides.size() != 2) {
        refuse("a concave corner with a circle without two selected edges");
    }
    auto sweep = [&](const Side& side, double length) {
        const gp_Dir& beyond = side.plane.normal;
        TopoDS_Shape solid;
        if (side.data->line) {
            solid = BRepPrimAPI_MakePrism(side.end, gp_Vec(beyond) * length, Standard_True).Shape();
        }
        else {
            // The tool itself turned on about its axis, beyond its end plane: its faces keep the
            // tool's surfaces (a cone revolved from the end face would be the same cone with
            // another apex parametrisation, which UnifySameDomain does not merge)
            gp_Ax1 axis = side.data->circle.Axis();
            gp_Vec radius(side.data->circle.Location(), side.plane.point);
            if (gp_Vec(axis.Direction()).Crossed(radius).Dot(gp_Vec(beyond)) < 0) {
                axis.Reverse();
            }
            double span = side.data->closed ? 2 * pi : side.data->last - side.data->first;
            double angle = std::min(length / side.data->circle.Radius(), 0.45 * span);
            gp_Trsf turn;
            turn.SetRotation(axis, angle);
            solid = commonOf(
                side.tool->solid.Moved(TopLoc_Location(turn)),
                halfSpaceBeyond(side.plane, 4 * length)
            );
        }
        if (volumeOf(solid) < 0) {
            solid.Reverse();
        }
        return solid;
    };
    auto pieceOf = [&](double length) {
        return commonOf(sweep(sides[0], length), sweep(sides[1], length));
    };
    Tool tool;
    tool.solid = pieceOf(reach);
    tool.cut = false;
    tool.source = vertex;
    tool.miter = true;
    tool.volume = volumeOf(tool.solid);
    if (tool.volume <= linearTolerance * reach * reach) {
        refuse("no miter at a concave corner with a circle");
    }
    double further = volumeOf(pieceOf(2 * reach));
    if (std::abs(further - tool.volume) > volumeTolerance * tool.volume) {
        refuse("the miter at a concave corner with a circle runs past its sweeps");
    }
    return tool;
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
 *
 * Past the limit (ops#640, S3): a cut tool's strip may run off its face, and two cut tools' strips
 * may overlap or touch, as Onshape's dress-ups do: the result is the base minus the union of the
 * full tools, trimmed by the base's own faces (notes/onshape-facts.md KP1-KP4, K2A-K2E). Returns
 * whether that happened (the tools are then "trimmed": their volumes are no longer their closed
 * forms). A fused tool (a concave edge) that overlaps another is refused; one whose strip runs
 * off its face is listed in fusedOff, and the edges it runs over go in fusedRuns: the caller trims
 * it by the faces beyond them (trimFusedTool), then checks that what is still off its face runs
 * into the base's material (checkFusedRunOff): the air beyond the face would have nothing to trim
 * it. A cut tool's strip that runs off its face
 * across an edge that is not selected (checkRunOff) is listed in pastLoop. A cut tool's strip that
 * runs off into a wall straight back from its face lists that face in walled, each tool's own walls
 * there in wallsOf (the same index), and every walled face's walls in wallFaces: the caller trims
 * the tools there by the walls' surfaces (clipTool).
 */
bool checkStrips(
    const std::vector<Tool>& tools,
    const std::vector<Overlap>& overlaps,
    bool limitOnly,
    const TopTools_IndexedDataMapOfShapeListOfShape& edgeFaces,
    const TopTools_IndexedMapOfShape& selected,
    std::vector<const Tool*>& fusedOff,
    std::vector<const Strip*>& pastLoop,
    std::vector<TopoDS_Face>& walled,
    std::vector<std::vector<std::pair<const Tool*, std::vector<TopoDS_Face>>>>& wallsOf,
    std::vector<TopoDS_Face>& wallFaces,
    std::vector<FusedRun>& fusedRuns
)
{
    bool trimmed = false;
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
    // The tools whose strip runs off its face: a tool with every strip off its face touches none
    // of them, and no round or chamfer exists (a fillet of r 30 on a 10 x 20 pad's edge);
    // Onshape's dress-ups past their faces all keep a strip on one (KP1-KP4, K2A-K2E)
    std::vector<const Strip*> offTheFace;
    for (const auto& group : faces) {
        double covered = 0.0;
        for (size_t k = 0; k < group.strips.size(); ++k) {
            const auto* strip = group.strips[k];
            if (strip->contacts.empty()) {
                refuse("a tool has no face on a face next to its edge");
            }
            for (const auto& contact : strip->contacts) {
                double area = areaOf(contact);
                double tolerance = areaToleranceOf(contact, *strip);
                if (area - areaOf(commonOf(group.face, contact)) > tolerance) {
                    if (!group.owners[k]->cut) {
                        // checkFusedRunOff runs once the caller has trimmed the tool
                        // (trimFusedTool): the face beyond may clip the part off the face
                        if (std::find(fusedOff.begin(), fusedOff.end(), group.owners[k])
                            == fusedOff.end()) {
                            fusedOff.push_back(group.owners[k]);
                        }
                        noteFusedRun(fusedRuns, group.owners[k], group.face, contact, edgeFaces);
                    }
                    else {
                        std::vector<TopoDS_Face> walls;
                        if (checkRunOff(
                                group.face,
                                contact,
                                group.owners[k]->source,
                                edgeFaces,
                                selected,
                                walls
                            )
                            && std::find(pastLoop.begin(), pastLoop.end(), strip)
                                == pastLoop.end()) {
                            pastLoop.push_back(strip);
                        }
                        auto isFace = [&](const TopoDS_Face& f) {
                            return f.IsSame(group.face);
                        };
                        auto at = std::find_if(walled.begin(), walled.end(), isFace);
                        if (!walls.empty() && at == walled.end()) {
                            walled.push_back(group.face);
                            wallsOf.emplace_back();
                            at = walled.end() - 1;
                        }
                        for (const auto& wall : walls) {
                            auto isWall = [&](const TopoDS_Face& f) {
                                return f.IsSame(wall);
                            };
                            if (std::none_of(wallFaces.begin(), wallFaces.end(), isWall)) {
                                wallFaces.push_back(wall);
                            }
                            auto& runs = wallsOf[at - walled.begin()];
                            auto run = std::find_if(runs.begin(), runs.end(), [&](const auto& r) {
                                return r.first == group.owners[k];
                            });
                            if (run == runs.end()) {
                                runs.push_back({group.owners[k], {}});
                                run = std::prev(runs.end());
                            }
                            if (std::none_of(run->second.begin(), run->second.end(), isWall)) {
                                run->second.push_back(wall);
                            }
                        }
                    }
                    offTheFace.push_back(strip);
                    trimmed = true;
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
                            if (!group.owners[i]->cut || !group.owners[j]->cut) {
                                refuse("two tangent strips of a concave dress-up overlap");
                            }
                            trimmed = true;
                        }
                        // Two bands that meet exactly (their far sides touch): at the limit. The
                        // strips of neighbours at a corner touch along their common side anyway
                        if (expected == 0.0 && !atLimit && area <= tolerance
                            && !neighbours(group.owners[i]->source, group.owners[j]->source)
                            && touch(mine, theirs)) {
                            atLimit = true;
                        }
                        common += area;
                        summedTolerance += tolerance;
                    }
                }
                if (expected == 0.0 && trimmed) {
                    continue;
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
    for (const auto& tool : tools) {
        bool onAFace = tool.strips.empty();
        for (const auto& strip : tool.strips) {
            onAFace = onAFace
                || std::find(offTheFace.begin(), offTheFace.end(), &strip) == offTheFace.end();
        }
        if (!onAFace) {
            refuse("a dress-up runs past both its faces");
        }
    }
    if (limitOnly && !atLimit && !trimmed) {
        refuse("not at the limit: no new edge lands on an existing one, and no face vanishes");
    }
    return trimmed;
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

/** The material behind a planar face's walls (wallAlongNormal), near the tool: the base's section
 * in the plane in front of the face by offset (in the air the face bounds), swept back through
 * the tool. Behind the face it is bounded by the walls' surfaces run on (a groove's floor under
 * the groove's wall); in front of the face's own area there is no material to sweep
 */
TopoDS_Shape behindWalls(
    const TopoDS_Face& face,
    const TopoDS_Shape& base,
    const TopoDS_Shape& tool,
    double offset
)
{
    BRepAdaptor_Surface surface(face, Standard_False);
    const gp_Pln plane = surface.Plane();
    const gp_Dir outward = outwardNormal(face, plane.Location());
    Bnd_Box box;
    BRepBndLib::Add(tool, box);
    const double size = std::sqrt(box.SquareExtent());
    double xMin = 0.0;
    double yMin = 0.0;
    double zMin = 0.0;
    double xMax = 0.0;
    double yMax = 0.0;
    double zMax = 0.0;
    box.Get(xMin, yMin, zMin, xMax, yMax, zMax);
    gp_Pnt centre((xMin + xMax) / 2, (yMin + yMax) / 2, (zMin + zMax) / 2);
    double u = 0.0;
    double v = 0.0;
    ElSLib::Parameters(plane, centre, u, v);
    gp_Pnt origin = ElSLib::Value(u, v, plane).Translated(gp_Vec(outward) * offset);
    gp_Pln front(gp_Ax3(origin, outward, plane.Position().XDirection()));
    TopoDS_Face sheet = BRepBuilderAPI_MakeFace(front, -2 * size, 2 * size, -2 * size, 2 * size);
    TopoDS_Shape section = commonOf(base, sheet);
    if (TopExp_Explorer(section, TopAbs_FACE).More() == Standard_False) {
        return {};
    }
    BRepPrimAPI_MakePrism sweep(section, gp_Vec(outward) * -(offset + 2 * size), Standard_True);
    if (!sweep.IsDone()) {
        refuse("sweeping the walls behind a tangent strip failed");
    }
    return sweep.Shape();
}

/** A cut tool trimmed by the material behind walls (Onshape's chamfer past a concave edge, Case
 * Base row 15): its solid becomes the cut's result, and the faces it keeps for the checks become
 * their images. Its volume is then measured, as every trimmed tool's is
 */
void clipTool(Tool& tool, const TopoDS_Shape& behind)
{
    TopTools_ListOfShape arguments;
    arguments.Append(tool.solid);
    TopTools_ListOfShape tools;
    tools.Append(behind);
    BRepAlgoAPI_Cut cut;
    cut.SetArguments(arguments);
    cut.SetTools(tools);
    cut.SetNonDestructive(Standard_True);
    cut.SetRunParallel(Standard_False);
    cut.Build();
    if (!cut.IsDone() || cut.HasErrors()) {
        refuse("trimming a tool by the walls behind its strip failed");
    }
    TopoDS_Shape solid = cut.Shape();
    if (countSolids(solid) != 1) {
        refuse("a tool trimmed by the walls behind its strip is not one solid");
    }
    if (solid.ShapeType() != TopAbs_SOLID) {
        solid = TopExp_Explorer(solid, TopAbs_SOLID).Current();
    }
    const Stage stage(cut.History(), solid);
    auto remap = [&](std::vector<TopoDS_Shape>& shapes) {
        std::vector<TopoDS_Shape> images;
        for (const auto& shape : shapes) {
            for (const auto& image : stage.images(shape)) {
                images.push_back(image);
            }
        }
        shapes = std::move(images);
    };
    remap(tool.contactFaces);
    remap(tool.capFaces);
    remap(tool.unionEndFaces);
    for (auto& strip : tool.strips) {
        remap(strip.contacts);
    }
    tool.solid = solid;
    tool.volume = volumeOf(solid);
}

/** A fused tool whose strip runs off its face (ops#640, the native replica's Case Base #46):
 * Onshape clips the dress-up by the surface of the face its strip reaches first beyond each edge it
 * runs over, run on, and adds nothing past it. Over a ledge that is a ring's outer wall, under the
 * ring the ring's well: nothing is added in the well, where the whole tool would leave a fin. (Into
 * a wall that is material beyond, the clip changes nothing: the material absorbs the tool there.)
 *
 * Built where the tool runs along a line and the face beyond is a prism along it, a plane through
 * the line's direction or a cylinder about it, over the stretch of an edge along the line: there
 * the trim is the same in every section. Other edges (a ledge's, across the line) are left to the
 * checks, as is the case where the tool is no edge's. A trim that would remove only the base's
 * material changes nothing and is left out. The tool's volume in the base is measured again
 */
bool trimFusedTool(
    Tool& tool,
    const FusedRun& run,
    const TopoDS_Shape& base,
    std::vector<TopoDS_Face>& wallFaces
)
{
    if (tool.source.ShapeType() != TopAbs_EDGE) {
        return false;
    }
    BRepAdaptor_Curve line(TopoDS::Edge(tool.source));
    if (line.GetType() != GeomAbs_Line) {
        return false;
    }
    const gp_Dir along = line.Line().Direction();
    const gp_Pnt origin = line.Line().Location();
    const double size = 4 * std::sqrt(squareSize(tool.solid)) + 1;
    bool clipped = false;
    for (const auto& [edge, beyond] : run.edges) {
        BRepAdaptor_Curve curve(edge);
        if (curve.GetType() != GeomAbs_Line || !parallel(curve.Line().Direction(), along)) {
            continue;
        }
        double from = gp_Vec(origin, curve.Value(curve.FirstParameter())).Dot(gp_Vec(along));
        double to = gp_Vec(origin, curve.Value(curve.LastParameter())).Dot(gp_Vec(along));
        if (from > to) {
            std::swap(from, to);
        }
        if (to - from <= 1000 * linearTolerance) {
            continue;
        }
        const double middle = (curve.FirstParameter() + curve.LastParameter()) / 2;
        const gp_Pnt point = curve.Value(middle);
        // Off the face across the edge, as the strip runs on
        const gp_Vec off = -gp_Vec(inwardIn(run.face, edge, middle));
        const gp_Pnt start = origin.Translated(gp_Vec(along) * from);
        BRepAdaptor_Surface surface(beyond, Standard_False);
        TopoDS_Shape trim;
        if (surface.GetType() == GeomAbs_Plane) {
            gp_Dir normal = surface.Plane().Axis().Direction();
            if (std::abs(normal.Dot(along)) > angularTolerance) {
                continue;
            }
            const double across = off.Dot(gp_Vec(normal));
            // A face that continues the strip's face (tangent) is no wall
            if (std::abs(across) < 1e-3) {
                continue;
            }
            if (across < 0) {
                normal.Reverse();
            }
            // The slab beyond the plane over the edge's stretch
            const gp_Pnt corner = start.Translated(
                -gp_Vec(normal) * gp_Vec(surface.Plane().Location(), start).Dot(gp_Vec(normal))
            );
            const gp_Pln plane(gp_Ax3(corner, normal, along));
            TopoDS_Face sheet = BRepBuilderAPI_MakeFace(plane, 0, to - from, -size, size);
            trim = BRepPrimAPI_MakePrism(sheet, gp_Vec(normal) * size).Shape();
        }
        else if (surface.GetType() == GeomAbs_Cylinder) {
            const gp_Cylinder cylinder = surface.Cylinder();
            if (!parallel(cylinder.Axis().Direction(), along)) {
                continue;
            }
            const gp_Pnt centre = cylinder.Location();
            // The point of the axis level with p along the line
            auto onAxis = [&](const gp_Pnt& p) {
                return centre.Translated(gp_Vec(along) * gp_Vec(centre, p).Dot(gp_Vec(along)));
            };
            const gp_Vec radial(onAxis(point), point);
            if (radial.Magnitude() < linearTolerance) {
                continue;
            }
            const double across = off.Dot(radial.Normalized());
            if (std::abs(across) < 1e-3) {
                continue;
            }
            const gp_Ax2 axis(onAxis(start), along);
            const double radius = cylinder.Radius();
            TopoDS_Shape inside = BRepPrimAPI_MakeCylinder(axis, radius, to - from).Shape();
            if (across < 0) {
                trim = inside;
            }
            else {
                // Beyond is outside the cylinder: a block about it, less the cylinder
                const double half = size + radius;
                const gp_Pnt low = axis.Location().Translated(
                    -gp_Vec(axis.XDirection()) * half - gp_Vec(axis.YDirection()) * half
                );
                const gp_Ax2 frame(low, along, axis.XDirection());
                TopoDS_Shape block
                    = BRepPrimAPI_MakeBox(frame, 2 * half, 2 * half, to - from).Shape();
                BRepAlgoAPI_Cut ring(block, inside);
                if (!ring.IsDone() || ring.HasErrors()) {
                    refuse("trimming a fused tool by the face beyond its strip failed");
                }
                trim = ring.Shape();
            }
        }
        else {
            continue;
        }
        TopoDS_Shape piece = commonOf(tool.solid, trim);
        if (!TopExp_Explorer(piece, TopAbs_SOLID).More()) {
            continue;
        }
        if (volumeOf(piece) - volumeOf(commonOf(piece, base)) <= volumeTolerance * tool.volume) {
            continue;
        }
        // The face beyond must lie past the strip, away from the edge and the other faces: a trim
        // that reaches them (a face leaning back over the tool) would take the dress-up itself,
        // and the volume checks, measured on the trimmed tool, could not tell
        BRepClass3d_SolidClassifier atEdge(trim);
        atEdge.Perform(origin.Translated(gp_Vec(along) * ((from + to) / 2)), linearTolerance);
        bool reachesBack = atEdge.State() != TopAbs_OUT;
        for (const auto& strip : tool.strips) {
            if (strip.face.IsSame(run.face)) {
                continue;
            }
            for (const auto& contact : strip.contacts) {
                reachesBack = reachesBack || touch(contact, piece);
            }
        }
        if (reachesBack) {
            refuse("the face beyond a fused tool's strip reaches back to the dress-up");
        }
        clipTool(tool, trim);
        clipped = true;
        // The tool's face on its surface merges into it: Onshape's face grows there (#46's
        // well, under the ring)
        if (std::none_of(wallFaces.begin(), wallFaces.end(), [&](const TopoDS_Face& wall) {
                return wall.IsSame(beyond);
            })) {
            wallFaces.push_back(beyond);
        }
    }
    if (clipped) {
        for (const auto& strip : tool.strips) {
            if (strip.contacts.empty()) {
                refuse("a fused tool trimmed by the face beyond its strip has no face on a face "
                       "next to its edge");
            }
        }
        double inBase = volumeOf(commonOf(base, tool.solid));
        tool.inBase = inBase > volumeTolerance * tool.volume ? inBase : 0.0;
    }
    return clipped;
}

/** Trims a cut tool by a tight wall arc's wedge (Tool::wedge, C4 shape A): what lies in the wedge
 * is the tight tool's to remove. Of what is left, the solids in the base's material are kept;
 * the tool's faces are mapped onto them, and its volume is measured.
 */
void trimByWedge(Tool& tool, const TopoDS_Shape& wedge, const TopoDS_Shape& base)
{
    TopTools_ListOfShape arguments;
    arguments.Append(tool.solid);
    TopTools_ListOfShape tools;
    tools.Append(wedge);
    BRepAlgoAPI_Cut cut;
    cut.SetArguments(arguments);
    cut.SetTools(tools);
    cut.SetNonDestructive(Standard_True);
    cut.SetRunParallel(Standard_False);
    cut.Build();
    if (!cut.IsDone() || cut.HasErrors()) {
        refuse("trimming a tool by a tight corner's wedge failed");
    }
    // Every piece in the material is cut (a crumb where the wedge's end meets the tool's own is
    // material the round removes); pieces in the air are dropped
    TopoDS_Compound kept;
    BRep_Builder builder;
    builder.MakeCompound(kept);
    int inMaterial = 0;
    for (TopExp_Explorer it(cut.Shape(), TopAbs_SOLID); it.More(); it.Next()) {
        if (volumeOf(commonOf(base, it.Current())) > volumeTolerance * tool.volume) {
            builder.Add(kept, it.Current());
            ++inMaterial;
        }
    }
    if (inMaterial == 0) {
        refuse("a tool trimmed by a tight corner's wedge leaves nothing in the material");
    }
    const Stage stage(cut.History(), kept);
    auto remap = [&](std::vector<TopoDS_Shape>& shapes) {
        std::vector<TopoDS_Shape> images;
        for (const auto& shape : shapes) {
            for (const auto& image : stage.images(shape)) {
                images.push_back(image);
            }
        }
        shapes = std::move(images);
    };
    remap(tool.contactFaces);
    remap(tool.capFaces);
    remap(tool.unionEndFaces);
    for (auto& strip : tool.strips) {
        remap(strip.contacts);
    }
    tool.solid = kept;
    tool.volume = volumeOf(kept);
}

/** One Boolean stage, and its checks (5.6, interface point 5). The volume it must remove or add is
 * the caller's: the tools' closed forms less the overlaps at unequal corners, or, for a trimmed
 * tool, its common part with the shape. The tolerance scales with the tools' closed forms, and
 * grows only by what the Booleans' raised tolerances can cost the measurement (raisedTolerance):
 * the stage's own and the caller's (expectedAllowance, for a measured expectation)
 */
TopoDS_Shape applyTools(
    const TopoDS_Shape& shape,
    const std::vector<const Tool*>& tools,
    double expected,
    bool cut,
    std::vector<Stage>& stages,
    double expectedAllowance = 0.0
)
{
    TopTools_ListOfShape arguments;
    arguments.Append(shape);
    TopTools_ListOfShape toolShapes;
    double scale = 0.0;
    double size = 0.0;
    for (const auto* tool : tools) {
        toolShapes.Append(tool->solid);
        scale += tool->volume;
        size = std::max(size, squareSize(tool->solid));
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
    std::vector<TopoDS_Shape> inputs {shape};
    for (const auto* tool : tools) {
        inputs.push_back(tool->solid);
    }
    double raised = raisedTolerance(result, inputs);
    double bound = volumeTolerance * scale + raised * size + expectedAllowance;
    if (std::abs(change - expected) > bound) {
        // OCCT's default integration is not exact on free-form faces, and its error there moves
        // with the shape it integrates (about a point it takes from the shape): the faces the stage
        // left alone then don't cancel. On the replica's Case Base (#108) the body measures 0.43
        // over, and a cut that rebuilt only analytic faces 2.45e-4 short of its closed form, eight
        // times the bound. Measured adaptively, the change is right to 7e-7
        change = MassProperties::volume(result, true) - MassProperties::volume(shape, true);
        if (cut) {
            change = -change;
        }
    }
    if (std::abs(change - expected) > bound) {
        // A whole-body difference can't meet the bound on a large body with free-form faces, even
        // adaptively (Case Base #108 on Onshape's own input: 29.32171848 for 29.32153143, about
        // 1e-9 of 191 000 mm3): over the faces the stage changed only
        change = changedVolume(shape, result);
        if (cut) {
            change = -change;
        }
    }
    if (std::abs(change - expected) > bound) {
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

/// The construction, of plain shapes (kernel safety S1: it may run on a worker thread): the result
/// and its history from the base in mapper; cornerCount receives how many corners it built
TopoDS_Shape constructShape(
    const TopoDS_Shape& baseShape,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    ShapeMapper& mapper,
    int& cornerCount
)
{
    // Its own TopoShape: no element map, no hasher, a cache of its own
    const TopoShape base(baseShape);
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
        if (edge.IsNull() || edge.ShapeType() != TopAbs_EDGE) {
            refuse("not an edge");
        }
        if (ctx.selected.Contains(edge)) {
            continue;
        }
        ctx.selected.Add(edge);
    }
    // Per-edge setbacks (chainSetbacks()): a chain's first edge keeps size1, and a setback changes
    // only at a vertex where two of the chain's contours meet. The construction builds one size,
    // so any setback other than size1 means such a corner: OCCT's own result or error stands
    if (!request.setbacks.empty()) {
        if (request.setbacks.size() != edges.size()) {
            refuse("a setback per edge that doesn't match the edges");
        }
        for (double setback : request.setbacks) {
            if (setback != request.size1) {
                refuse("a corner between chamfer widths that differ");
            }
        }
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
        if (!tool.measured && std::abs(measured - tool.volume) > volumeTolerance * tool.volume) {
            refuse("a tool's volume " + describe(measured) + " differs from its closed form "
                   + describe(tool.volume));
        }
        findContactFaces(tool);
        // A fused tool fills air only: material under it would be fused twice, and the volume
        // checks after the cut could not tell (5.6, interface point 7). Unless its strip runs
        // off its face into the material, which absorbs it (checked after checkStrips)
        if (!tool.cut) {
            double inBase = volumeOf(commonOf(base.getShape(), tool.solid));
            tool.inBase = inBase > volumeTolerance * tool.volume ? inBase : 0.0;
            if (tool.rolled && tool.inBase > 0.0) {
                refuse("a round rolled on over a tangent edge runs into the material");
            }
        }
        tools.push_back(std::move(tool));
    };
    // The three-edge corners, each with its piece, of the convexity of its edges
    std::vector<std::pair<TopoDS_Vertex, bool>> corners;
    // The two-edge corners with unequal dihedral angles
    std::vector<TopoDS_Vertex> unequalCorners;
    // Every corner, for the Report-view line
    TopTools_IndexedMapOfShape cornerVertices;
    // Whether a two-edge corner with a circle makes two tools overlap (Corner2Union)
    bool unionCorners = false;
    // The concave ones, each with its miter piece
    std::vector<TopoDS_Vertex> miterCorners;
    // The two-edge corners of convex edges at a vertex convex in the material (Corner2,
    // Corner2Union), and the selected edges that continue one another tangentially
    std::vector<TopoDS_Vertex> convexCorners;
    std::vector<std::pair<TopoDS_Shape, TopoDS_Shape>> continuations;
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
                    || kind == VertexClass::Corner2Union || kind == VertexClass::Corner3) {
                    cornerVertices.Add(vertices[i]);
                }
                unionCorners = unionCorners || kind == VertexClass::Corner2Union;
                auto known = [&](const TopoDS_Vertex& v) {
                    return v.IsSame(vertices[i]);
                };
                if (edgeData.convex
                    && (kind == VertexClass::Corner2Union || kind == VertexClass::Corner2)
                    && std::none_of(convexCorners.begin(), convexCorners.end(), known)) {
                    // A Corner2Union of convex edges is convex (classifyUnionCorner); a Corner2
                    // may be concave (a U's inner corners)
                    bool convexVertex = kind == VertexClass::Corner2Union;
                    if (!convexVertex) {
                        std::string unused;
                        auto corner = cornerAt(ctx, vertices[i], unused);
                        convexVertex = corner && corner->convex;
                    }
                    if (convexVertex) {
                        convexCorners.push_back(vertices[i]);
                    }
                }
                if (kind == VertexClass::TangentContinuation) {
                    continuations.emplace_back(edgeData.edge, ends[slot].continuation);
                }
                if (kind == VertexClass::Corner2Union && !edgeData.convex
                    && std::none_of(miterCorners.begin(), miterCorners.end(), known)) {
                    miterCorners.push_back(vertices[i]);
                }
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
                    if (edgeData.ruled || other->ruled) {
                        refuse("a tangent continuation of a straight edge on a cylinder");
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
        if (edgeData.ruled) {
            admit(ruledTool(ctx, edgeData, ends, request.size1));
        }
        else if (edgeData.line) {
            if (auto tool = lineTool(ctx, edgeData, ends)) {
                admit(std::move(*tool));
            }
        }
        else if (tightArc(ctx, edgeData)) {
            admit(tightTool(ctx, edgeData, ends, data));
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
    for (const auto& vertex : miterCorners) {
        admit(miterTool(tools, data, vertex));
    }
    // A tight wall arc's wedge is its own tool's: the others are trimmed by it (Tool::wedge)
    for (const auto& tight : tools) {
        if (tight.wedge.IsNull()) {
            continue;
        }
        Bnd_Box wedgeBox;
        BRepBndLib::Add(tight.wedge, wedgeBox);
        for (auto& tool : tools) {
            if (&tool == &tight || !tool.wedge.IsNull()) {
                continue;
            }
            Bnd_Box box;
            BRepBndLib::Add(tool.solid, box);
            if (box.IsOut(wedgeBox)
                || volumeOf(commonOf(tool.solid, tight.wedge)) <= volumeTolerance * tool.volume) {
                continue;
            }
            if (!tool.cut) {
                refuse("a fused tool reaches into a tight corner");
            }
            trimByWedge(tool, tight.wedge, base.getShape());
        }
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
    // The tools at a corner with a circle overlap: their volumes are measured, as past the limit
    std::vector<const Tool*> fusedOff;
    std::vector<const Strip*> pastLoop;
    std::vector<TopoDS_Face> walled;
    std::vector<std::vector<std::pair<const Tool*, std::vector<TopoDS_Face>>>> wallsOf;
    std::vector<TopoDS_Face> wallFaces;
    std::vector<FusedRun> fusedRuns;
    const bool trimmed = checkStrips(
                             tools,
                             overlaps,
                             request.limitOnly,
                             ctx.edgeFaces,
                             ctx.selected,
                             fusedOff,
                             pastLoop,
                             walled,
                             wallsOf,
                             wallFaces,
                             fusedRuns
                         )
        || unionCorners;
    // A dress-up past a concave edge into a wall straight back from its face: Onshape trims the
    // tools on that face by the wall's surface run on behind the face (Q-LEDGE, Case Base row
    // 15). The section in front of the face is taken at a tenth of the strip's width there, and
    // again at a twentieth: anything else in front of the face within that would change the trim
    for (size_t w = 0; w < walled.size(); ++w) {
        const TopoDS_Face& face = walled[w];
        for (auto& tool : tools) {
            const auto strip
                = std::find_if(tool.strips.begin(), tool.strips.end(), [&](const Strip& s) {
                      return s.face.IsSame(face);
                  });
            if (!tool.cut || strip == tool.strips.end()) {
                continue;
            }
            // The walls this tool's own strip runs into (review r2): a fin in the plane of another
            // strip's wall is not this tool's wall. A tool whose strip runs into no wall here has
            // none. (A fin in the plane of another of this strip's own walls still passes: debt,
            // review r2's T2, rare; Replica #15's lip runs into walls on several surfaces)
            static const std::vector<TopoDS_Face> none;
            const auto run = std::find_if(wallsOf[w].begin(), wallsOf[w].end(), [&](const auto& r) {
                return r.first == &tool;
            });
            const std::vector<TopoDS_Face>& own = run == wallsOf[w].end() ? none : run->second;
            const double offset = 0.1 * strip->width;
            if (offset <= 1000 * linearTolerance) {
                refuse("a tangent strip into a wall has no width");
            }
            TopoDS_Shape behind = behindWalls(face, base.getShape(), tool.solid, offset);
            if (behind.IsNull()) {
                continue;
            }
            // Any piece behind the walls, however thin (a round 0.01 past the wall: about 1e-6 of
            // a 215 tool), would leave the tool's contact face standing beside the wall
            TopoDS_Shape piece = commonOf(tool.solid, behind);
            if (!TopExp_Explorer(piece, TopAbs_SOLID).More()) {
                continue;
            }
            double clipped = volumeOf(piece);
            TopoDS_Shape nearer = behindWalls(face, base.getShape(), tool.solid, offset / 2);
            double again = nearer.IsNull() ? 0.0 : volumeOf(commonOf(tool.solid, nearer));
            if (std::abs(again - clipped) > volumeTolerance * tool.volume) {
                refuse("the walls behind a tangent strip don't run straight back from its face ("
                       + describe(clipped) + " behind them at " + describe(offset) + ", "
                       + describe(again) + " at " + describe(offset / 2) + ")");
            }
            // The piece is bounded by the tool's own surfaces and the walls' run on, and by nothing
            // else: material in front of the face that isn't the wall (a fin on a ledge, closer to
            // the wall than both offsets) would trim the tool at its own height (review r1)
            std::vector<Handle(Geom_Surface)> toolSurfaces;
            for (TopExp_Explorer it(tool.solid, TopAbs_FACE); it.More(); it.Next()) {
                TopLoc_Location location;
                toolSurfaces.push_back(BRep_Tool::Surface(TopoDS::Face(it.Current()), location));
            }
            for (TopExp_Explorer it(piece, TopAbs_FACE); it.More(); it.Next()) {
                const TopoDS_Face& side = TopoDS::Face(it.Current());
                TopLoc_Location location;
                Handle(Geom_Surface) surface = BRep_Tool::Surface(side, location);
                bool ofTool = std::any_of(toolSurfaces.begin(), toolSurfaces.end(), [&](const auto& s) {
                    return s == surface;
                });
                bool ofWall = std::any_of(own.begin(), own.end(), [&](const TopoDS_Face& wall) {
                    return sameDomain(side, wall);
                });
                if (!ofTool && !ofWall) {
                    refuse("material in front of a tangent strip's face that is not the wall would trim "
                           "the dress-up");
                }
            }
            clipTool(tool, behind);
        }
    }
    // A fused tool past its face: clipped by the face beyond each edge its strip runs over (Case
    // Base #46), so it adds nothing past it
    for (const auto& run : fusedRuns) {
        for (auto& tool : tools) {
            if (&tool != run.tool) {
                continue;
            }
            // A miter piece continues its tools' faces past the corner: it has no strips to trim
            if (trimFusedTool(tool, run, base.getShape(), wallFaces)
                && std::any_of(tools.begin(), tools.end(), [](const Tool& t) {
                       return t.miter;
                   })) {
                refuse("a fused tool clipped by the face beyond its strip at a concave corner "
                       "with a circle");
            }
            // What is still off its face must run into the material, which absorbs it
            for (const auto& strip : tool.strips) {
                if (!strip.face.IsSame(run.face)) {
                    continue;
                }
                for (const auto& contact : strip.contacts) {
                    if (areaOf(contact) - areaOf(commonOf(run.face, contact))
                        > areaToleranceOf(contact, strip)) {
                        checkFusedRunOff(run.face, contact, base.getShape());
                    }
                }
            }
        }
    }
    // Onshape, oracle 9e (ops#640, K1): CHAMFER/FILLET_OVERLAPS_EDGE_LOOP. Where two selected
    // edges meet at a corner convex in the material and the strips on both sides of it, on the
    // face that holds both edges, run past that face's outer loop (a keyhole wall's top chamfered
    // wider than the wall at the arc and along the slot), Onshape refuses. One side past it builds
    // (the arc exactly as wide as the wall), and so do strips past it with no such corner between
    // them (the arc alone, both legs) or at a concave one (a U). An edge's strip is past it where
    // a strip of its tangent chain on that face is: the arc in pieces is Onshape's one edge
    auto pastOuterLoop = [&](const TopoDS_Shape& edge, const TopoDS_Face& face) {
        std::vector<TopoDS_Shape> chain {edge};
        auto inChain = [&](const TopoDS_Shape& shape) {
            return std::any_of(chain.begin(), chain.end(), [&](const TopoDS_Shape& c) {
                return c.IsSame(shape);
            });
        };
        for (size_t i = 0; i < chain.size(); ++i) {
            for (const auto& link : continuations) {
                const TopoDS_Shape current = chain[i];
                if (link.first.IsSame(current) && !inChain(link.second)) {
                    chain.push_back(link.second);
                }
                else if (link.second.IsSame(current) && !inChain(link.first)) {
                    chain.push_back(link.first);
                }
            }
        }
        for (const auto& tool : tools) {
            if (!tool.cut || !inChain(tool.source)) {
                continue;
            }
            for (const auto& strip : tool.strips) {
                if (strip.face.IsSame(face)
                    && std::find(pastLoop.begin(), pastLoop.end(), &strip) != pastLoop.end()) {
                    return true;
                }
            }
        }
        return false;
    };
    for (const auto& vertex : convexCorners) {
        std::vector<const EdgeData*> pair;
        for (const auto& shape : ctx.list(ctx.vertexEdges, vertex)) {
            auto it = std::find_if(data.begin(), data.end(), [&](const EdgeData& d) {
                return d.edge.IsSame(shape);
            });
            if (it != data.end()) {
                pair.push_back(&*it);
            }
        }
        if (pair.size() != 2) {
            continue;
        }
        TopoDS_Face shared;
        for (const auto& mine : pair[0]->faces) {
            for (const auto& theirs : pair[1]->faces) {
                if (mine.IsSame(theirs)) {
                    shared = mine;
                }
            }
        }
        if (!shared.IsNull() && pastOuterLoop(pair[0]->edge, shared)
            && pastOuterLoop(pair[1]->edge, shared)) {
            refuse("two picked edges meet at a corner convex in the material, and both their strips "
                   "run past the face's outer loop");
        }
    }
    // A fused tool in the base's material: only where its strip ran off its face into it, and a
    // miter piece only beside such tools (its own faces are the tools' run on)
    for (const auto& tool : tools) {
        if (tool.cut || tool.inBase == 0.0) {
            continue;
        }
        bool ranOff = std::find(fusedOff.begin(), fusedOff.end(), &tool) != fusedOff.end()
            || (tool.miter && !fusedOff.empty());
        if (!ranOff) {
            refuse("a fused tool overlaps the base's material");
        }
    }
    // Past the limit, the cut tools' volumes in the base, by inclusion and exclusion: each tool's
    // common part with the base, less the pairs' common parts. Measured, not closed forms, but by
    // other Booleans than the cut's: OCCT 8.0.1's cut by two barely overlapping tori (two rims'
    // fillets 1.56 on rims 3.1 apart) leaves more than either tool alone does
    double trimmedVolume = 0.0;
    double trimmedAllowance = 0.0;  // what raised tolerances can cost trimmedVolume's measurements
    std::vector<TopoDS_Shape> lenses;  // the pairs' common parts in the base: the cut removes them
    if (trimmed) {
        if (!overlaps.empty()) {
            refuse("a dress-up past its face at a corner with unequal angles");
        }
        // At a three-edge corner the edge tools end on planes through the corner piece's centre:
        // run past the vertex (an oblique slab's obtuse corners), they leave the material there
        // in a way the union doesn't model (5.3)
        if (!corners.empty()) {
            refuse("a tangent strip runs off its face at a three-edge corner");
        }
        std::vector<const Tool*> cutTools;
        std::vector<TopoDS_Shape> inside;
        std::vector<Bnd_Box> boxes;
        for (const auto& tool : tools) {
            if (!tool.cut) {
                continue;
            }
            cutTools.push_back(&tool);
            inside.push_back(commonOf(base.getShape(), tool.solid));
            trimmedVolume += volumeOf(inside.back());
            trimmedAllowance += raisedTolerance(inside.back(), {base.getShape(), tool.solid})
                * squareSize(tool.solid);
            boxes.emplace_back();
            BRepBndLib::Add(tool.solid, boxes.back());
        }
        auto overlapTolerance = [&](size_t i, size_t j) {
            return volumeTolerance * std::min(cutTools[i]->volume, cutTools[j]->volume);
        };
        std::vector<std::vector<bool>> pairs(cutTools.size(), std::vector<bool>(cutTools.size()));
        std::vector<std::vector<TopoDS_Shape>> pairCommons(
            cutTools.size(),
            std::vector<TopoDS_Shape>(cutTools.size())
        );
        for (size_t i = 0; i < cutTools.size(); ++i) {
            for (size_t j = i + 1; j < cutTools.size(); ++j) {
                if (boxes[i].IsOut(boxes[j])) {
                    continue;
                }
                TopoDS_Shape common = commonOf(inside[i], cutTools[j]->solid);
                double both = volumeOf(common);
                if (both > overlapTolerance(i, j)) {
                    pairs[i][j] = true;
                    pairCommons[i][j] = common;
                    lenses.push_back(common);
                    trimmedVolume -= both;
                    trimmedAllowance += raisedTolerance(common, {inside[i], cutTools[j]->solid})
                        * std::min(squareSize(cutTools[i]->solid), squareSize(cutTools[j]->solid));
                }
            }
        }
        // Three tools overlapping in one place would be subtracted once too often. A tight wall
        // arc's tool (measured) overlaps both neighbours' tools, whose strips overlap each other
        // on the top (C4 shape A): the three's common part is measured and added back, the third
        // term of the inclusion and exclusion. Four tools in one place are refused
        for (size_t i = 0; i < cutTools.size(); ++i) {
            for (size_t j = i + 1; j < cutTools.size(); ++j) {
                for (size_t k = j + 1; k < cutTools.size(); ++k) {
                    if (!pairs[i][j] || !pairs[i][k] || !pairs[j][k]) {
                        continue;
                    }
                    if (!cutTools[i]->measured && !cutTools[j]->measured
                        && !cutTools[k]->measured) {
                        refuse("three tools of a dress-up past its faces overlap");
                    }
                    for (size_t l = k + 1; l < cutTools.size(); ++l) {
                        if (pairs[i][l] && pairs[j][l] && pairs[k][l]) {
                            refuse("four tools of a dress-up past its faces overlap");
                        }
                    }
                    TopoDS_Shape triple = commonOf(pairCommons[i][j], cutTools[k]->solid);
                    trimmedVolume += volumeOf(triple);
                    trimmedAllowance += raisedTolerance(triple, {pairCommons[i][j], cutTools[k]->solid})
                        * std::min(
                              {squareSize(cutTools[i]->solid),
                               squareSize(cutTools[j]->solid),
                               squareSize(cutTools[k]->solid)}
                        );
                }
            }
        }
    }

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
    // The measured tools (a tight wall arc's, C4 shape A) first, each on its own: cut after the
    // others they remove nothing, their patch tangent to the neighbouring rounds already made
    // (work/c4 probe A3). What one removes is measured; the part of it that the other cut tools'
    // closed forms count as well is taken off the grouped cut's expectation and off the measured
    // tool's volume, so the final sum holds
    double measuredOverlap = 0.0;
    for (size_t i = 0; i < tools.size(); ++i) {
        if (!tools[i].measured) {
            continue;
        }
        TopoDS_Shape common = commonOf(shape, tools[i].solid);
        double removal = volumeOf(common);
        double overlap = 0.0;
        for (size_t j = 0; j < tools.size(); ++j) {
            if (tools[j].cut && !tools[j].measured) {
                overlap += volumeOf(commonOf(common, tools[j].solid));
            }
        }
        double allowance = raisedTolerance(common, {shape, tools[i].solid})
            * squareSize(tools[i].solid);
        toolStage[i] = stages.size();
        tools[i].volume = removal;
        shape = applyTools(shape, {&tools[i]}, removal, true, stages, allowance);
        tools[i].volume = removal - overlap;
        measuredOverlap += overlap;
    }
    for (bool cut : {true, false}) {
        if (cut && trimmed) {
            // One cut per tool, each checked against its common part with the shape it cuts
            for (size_t i = 0; i < tools.size(); ++i) {
                if (tools[i].cut && !tools[i].measured) {
                    toolStage[i] = stages.size();
                    TopoDS_Shape common = commonOf(shape, tools[i].solid);
                    double expected = volumeOf(common);
                    double allowance = raisedTolerance(common, {shape, tools[i].solid})
                        * squareSize(tools[i].solid);
                    shape = applyTools(shape, {&tools[i]}, expected, true, stages, allowance);
                }
            }
            continue;
        }
        std::vector<const Tool*> group;
        double expected = cut ? -overlapVolume - measuredOverlap : 0.0;
        for (size_t i = 0; i < tools.size(); ++i) {
            if (tools[i].cut == cut && !tools[i].measured) {
                group.push_back(&tools[i]);
                toolStage[i] = stages.size();
                // A fused tool adds only what lies outside the material (inBase: none, or past
                // its face)
                expected += tools[i].volume - tools[i].inBase;
            }
        }
        if (!group.empty()) {
            shape = applyTools(shape, group, expected, cut, stages);
        }
    }
    // At a corner with a circle each tool's end face lies inside the other tool: nothing of it may
    // be left (else the union would not be the miter)
    for (size_t i = 0; i < tools.size(); ++i) {
        for (const auto& face : tools[i].unionEndFaces) {
            if (!imagesThrough(stages, toolStage[i], face).empty()) {
                refuse("a tool's end at a corner with a circle is left in the result");
            }
        }
    }
    // A trimmed tool may cut the faces next to its edge's faces, which trim it, and nothing beyond
    if (trimmed) {
        TopTools_IndexedMapOfShape allowed;
        TopTools_IndexedDataMapOfShapeListOfShape facesOfEdges;
        TopExp::MapShapesAndAncestors(base.getShape(), TopAbs_EDGE, TopAbs_FACE, facesOfEdges);
        for (const auto& tool : tools) {
            for (const auto& strip : tool.strips) {
                allowed.Add(strip.face);
                for (TopExp_Explorer it(strip.face, TopAbs_EDGE); it.More(); it.Next()) {
                    if (const auto* next = facesOfEdges.Seek(it.Current())) {
                        for (const auto& face : *next) {
                            allowed.Add(face);
                        }
                    }
                }
            }
        }
        for (TopExp_Explorer it(base.getShape(), TopAbs_FACE); it.More(); it.Next()) {
            auto images = imagesThrough(stages, 0, it.Current());
            bool kept = images.size() == 1 && images.front().IsSame(it.Current());
            // A face the tool only touches along an edge is modified, not cut: its edge gains the
            // tool's vertices (Case Base #76: a chamfer's strip ending exactly on the tangent edge
            // into an elbow). One image on its own surface with its own area is the face kept
            if (!kept && images.size() == 1 && images.front().ShapeType() == TopAbs_FACE) {
                const TopoDS_Face& face = TopoDS::Face(it.Current());
                const TopoDS_Face& image = TopoDS::Face(images.front());
                TopLoc_Location here;
                TopLoc_Location there;
                bool sameSurface = BRep_Tool::Surface(face, here) == BRep_Tool::Surface(image, there)
                    || sameDomain(face, image);
                kept = sameSurface
                    && std::abs(areaOf(image) - areaOf(face)) <= areaToleranceOf(face);
            }
            if (!kept && !allowed.Contains(it.Current())) {
                refuse("a dress-up past its face cuts a face beyond the faces next to it");
            }
        }
    }

    // The faces of the tools left in the planes of free ends merge into the base's coplanar
    // faces, as OCCT's fillet extends those (5.6, interface point 4)
    std::vector<TrimPlane> caps;
    std::vector<std::pair<Handle(Geom_Surface), TopLoc_Location>> capSurfaces;
    for (const auto& tool : tools) {
        caps.insert(caps.end(), tool.caps.begin(), tool.caps.end());
        capSurfaces.insert(capSurfaces.end(), tool.capSurfaces.begin(), tool.capSurfaces.end());
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
    const bool miters = std::any_of(tools.begin(), tools.end(), [](const Tool& tool) {
        return tool.miter;
    });
    if (!caps.empty() || !capSurfaces.empty() || miters || !wallFaces.empty()) {
        collectBaseImages();
        NCollection_Map<TopoDS_Shape, TopTools_ShapeMapHasher> keep;
        TopTools_IndexedMapOfShape unlocked;
        // A miter piece's faces continue its tools' chamfer faces: Onshape's sharp miter has one
        // cone and one plane there (#15, dF +0 at the limit)
        for (size_t i = 0; i < tools.size(); ++i) {
            if (!tools[i].miter) {
                continue;
            }
            for (TopExp_Explorer it(tools[i].solid, TopAbs_FACE); it.More(); it.Next()) {
                for (const auto& image : imagesThrough(stages, toolStage[i], it.Current())) {
                    if (!baseImages.Contains(image)) {
                        TopExp::MapShapes(image, TopAbs_EDGE, unlocked);
                    }
                }
            }
        }
        // A fused tool's end that runs on into the base's material past its free end (#15 past
        // the limit: a leg's end triangle rises above the groove's top) leaves the overlap as a
        // piece of the base's face: the edges its outline cut into that face are new, and must
        // not keep the piece apart from the rest of the face
        for (size_t i = 0; i < tools.size(); ++i) {
            if (tools[i].cut) {
                continue;
            }
            for (const auto& cap : tools[i].capFaces) {
                for (const auto& image : imagesThrough(stages, toolStage[i], cap)) {
                    if (image.ShapeType() != TopAbs_FACE || !baseImages.Contains(image)) {
                        continue;
                    }
                    for (TopExp_Explorer edge(image, TopAbs_EDGE); edge.More(); edge.Next()) {
                        if (!baseImages.Contains(edge.Current())) {
                            unlocked.Add(edge.Current());
                        }
                    }
                }
            }
        }
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
            // A tool's face on a curved end face's surface merges into that face: the end face
            // grows by the dress-up's section where the surface cuts it off (Case Base #105)
            if (!capSurfaces.empty() && face.ShapeType() == TopAbs_FACE) {
                TopLoc_Location location;
                const Handle(Geom_Surface)& surface = BRep_Tool::Surface(TopoDS::Face(face), location);
                for (const auto& [capSurface, capLocation] : capSurfaces) {
                    if (surface == capSurface && location.IsEqual(capLocation)) {
                        TopExp::MapShapes(face, TopAbs_EDGE, unlocked);
                        break;
                    }
                }
            }
            // A trimmed tool's face on a wall's surface, run on under the dress-up, merges into
            // the wall: Onshape's wall grows there (Q-LEDGE LD1-LD3, F unchanged)
            for (const auto& wall : wallFaces) {
                if (face.ShapeType() == TopAbs_FACE && sameDomain(TopoDS::Face(face), wall)) {
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
    double scale = cutVolume + fusedVolume;
    for (const auto& tool : tools) {
        fusedVolume -= tool.inBase;  // what the material absorbs (none for a cut tool)
    }
    cutVolume = trimmed ? trimmedVolume : cutVolume - overlapVolume;
    double expected = baseVolume - cutVolume + fusedVolume;
    double measured = volumeOf(shape);
    std::vector<TopoDS_Shape> inputs {base.getShape()};
    double size = 0.0;
    for (const auto& tool : tools) {
        inputs.push_back(tool.solid);
        size = std::max(size, squareSize(tool.solid));
    }
    double allowance = raisedTolerance(shape, inputs) * size + (trimmed ? trimmedAllowance : 0.0);
    if (std::abs(measured - expected) > volumeTolerance * scale + allowance) {
        // As in applyTools: OCCT's default integration of free-form faces doesn't cancel between
        // the base and the result; both again, adaptively
        measured = MassProperties::volume(shape, true);
        expected = MassProperties::volume(base.getShape(), true) - cutVolume + fusedVolume;
    }
    if (std::abs(measured - expected) > volumeTolerance * scale + allowance) {
        // And over the faces that changed only, as in applyTools: the base's adaptive volume
        // plus the change
        measured = expected + cutVolume - fusedVolume + changedVolume(base.getShape(), shape);
    }
    if (std::abs(measured - expected) > volumeTolerance * scale + allowance) {
        refuse("the result's volume " + describe(measured) + " differs from its closed form "
               + describe(expected));
    }
    // The allowance can be as large as a lens two tools share, and the measurement off by as much
    // (ops#669: two rims' fillets 1.6 on holes 120 apart at 20x scale measure 0.099 off against a
    // lens of 0.105, the shape right): that the cut removed each lens is checked by points instead
    for (const auto& lens : lenses) {
        if (materialIn(shape, lens)) {
            refuse("the cut left material where two tools overlap");
        }
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

namespace
{

/** At the parameter of an edge of the face: the direction in the face square to the edge, away
 * from it (inwardIn()'s), and the face's outward normal. Any surface, through the edge's curve on
 * the face. False where either is degenerate or the edge has no curve on the face.
 */
bool inwardAt(
    const TopoDS_Face& face,
    const TopoDS_Edge& edge,
    double parameter,
    gp_Dir& inward,
    gp_Dir& normal
)
{
    double first = 0.0;
    double last = 0.0;
    Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, face, first, last);
    if (pcurve.IsNull()) {
        return false;
    }
    const gp_Pnt2d uv = pcurve->Value(parameter);
    BRepAdaptor_Surface surface(face, Standard_False);
    gp_Pnt onSurface;
    gp_Vec du;
    gp_Vec dv;
    surface.D1(uv.X(), uv.Y(), onSurface, du, dv);
    gp_Vec outward = du.Crossed(dv);
    if (outward.Magnitude() < linearTolerance) {
        return false;
    }
    if (face.Orientation() == TopAbs_REVERSED) {
        outward.Reverse();
    }
    gp_Pnt point;
    gp_Vec tangent;
    BRepAdaptor_Curve(edge).D1(parameter, point, tangent);
    if (orientationIn(face, edge) == TopAbs_REVERSED) {
        tangent.Reverse();
    }
    gp_Vec left = outward.Crossed(tangent);
    if (left.Magnitude() < linearTolerance) {
        return false;
    }
    inward = gp_Dir(left);
    normal = gp_Dir(outward);
    return true;
}

/// A contour's wedge angle, constant along it, or why not
struct Wedge
{
    double angle = 0.0;
    bool convex = true;
    std::string fault;
};

/** The wedge angle of OCCT's contour ic, the construction's Section::alpha (acos of the two
 * inward directions: the material angle at a convex edge, the air-side one at a concave edge),
 * sampled at 0.1 .. 0.9 of each of its edges (notes/chamfer-chain-setbacks.md section 3)
 */
Wedge wedgeOf(
    const BRepFilletAPI_MakeChamfer& maker,
    int ic,
    const TopTools_IndexedDataMapOfShapeListOfShape& edgeFaces
)
{
    Wedge wedge;
    double low = std::numeric_limits<double>::max();
    double high = -low;
    int convex = 0;
    int concave = 0;
    for (int j = 1; j <= maker.NbEdges(ic); ++j) {
        const TopoDS_Edge& edge = maker.Edge(ic, j);
        const int index = edgeFaces.FindIndex(edge);
        if (index == 0 || edgeFaces.FindFromIndex(index).Extent() != 2) {
            wedge.fault = "an edge without two faces";
            return wedge;
        }
        const TopoDS_Face& face0 = TopoDS::Face(edgeFaces.FindFromIndex(index).First());
        const TopoDS_Face& face1 = TopoDS::Face(edgeFaces.FindFromIndex(index).Last());
        BRepAdaptor_Curve curve(edge);
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        double edgeLow = std::numeric_limits<double>::max();
        double edgeHigh = -edgeLow;
        for (double fraction : {0.1, 0.3, 0.5, 0.7, 0.9}) {
            const double parameter = first + fraction * (last - first);
            gp_Dir inward0;
            gp_Dir inward1;
            gp_Dir normal0;
            gp_Dir normal1;
            if (!inwardAt(face0, edge, parameter, inward0, normal0)
                || !inwardAt(face1, edge, parameter, inward1, normal1)) {
                wedge.fault = "a degenerate face or edge";
                return wedge;
            }
            const double angle = std::acos(std::clamp(inward0.Dot(inward1), -1.0, 1.0));
            edgeLow = std::min(edgeLow, angle);
            edgeHigh = std::max(edgeHigh, angle);
            ++(inward1.Dot(normal0) < 0 ? convex : concave);
        }
        if (edgeHigh - edgeLow > 1e-7) {
            wedge.fault = "the angle varies along an edge";
            return wedge;
        }
        low = std::min(low, edgeLow);
        high = std::max(high, edgeHigh);
    }
    if (high - low > 1e-7) {
        wedge.fault = "the contour's edges have different angles";
    }
    else if (convex > 0 && concave > 0) {
        wedge.fault = "the contour mixes convex and concave edges";
    }
    wedge.angle = (low + high) / 2;
    wedge.convex = concave == 0;
    return wedge;
}

/// chainSetbacks() inside one try: OCCT's or the construction's exceptions keep the width
std::vector<double> setbacksOf(
    const TopoDS_Shape& shape,
    const std::vector<TopoShape>& edges,
    double width
)
{
    std::vector<double> setbacks(edges.size(), width);
    // OCCT's own contours: the listed edges, and the edges its tangent propagation adds. A
    // contour has one distance in OCCT. The maker is never built
    BRepFilletAPI_MakeChamfer maker(shape);
    for (const auto& edge : edges) {
        const TopoDS_Shape& e = edge.getShape();
        if (e.IsNull() || e.ShapeType() != TopAbs_EDGE || BRep_Tool::Degenerated(TopoDS::Edge(e))) {
            return setbacks;
        }
        maker.Add(TopoDS::Edge(e));
    }
    std::vector<int> contourOf(edges.size(), 0);
    for (std::size_t i = 0; i < edges.size(); ++i) {
        contourOf[i] = maker.Contour(TopoDS::Edge(edges[i].getShape()));
    }
    const int contours = maker.NbContours();

    // Contours that share a vertex are one chain: union-find over the contours
    std::vector<int> parent(contours + 1);
    for (int ic = 0; ic <= contours; ++ic) {
        parent[ic] = ic;
    }
    auto find = [&parent](int ic) {
        while (parent[ic] != ic) {
            parent[ic] = parent[parent[ic]];
            ic = parent[ic];
        }
        return ic;
    };
    TopTools_IndexedMapOfShape vertices;
    std::vector<int> contourAt;  // per vertex, the first contour seen there
    for (int ic = 1; ic <= contours; ++ic) {
        for (int j = 1; j <= maker.NbEdges(ic); ++j) {
            for (TopExp_Explorer it(maker.Edge(ic, j), TopAbs_VERTEX); it.More(); it.Next()) {
                const int index = vertices.Add(it.Current());
                if (index > static_cast<int>(contourAt.size())) {
                    contourAt.push_back(ic);
                }
                else {
                    parent[find(contourAt[index - 1])] = find(ic);
                }
            }
        }
    }

    // Each chain's first edge: the lowest index among the listed edges in it (section 5)
    std::vector<int> firstOf(contours + 1, -1);
    std::vector<int> size(contours + 1, 0);
    for (int ic = 1; ic <= contours; ++ic) {
        ++size[find(ic)];
    }
    for (std::size_t i = 0; i < edges.size(); ++i) {
        if (contourOf[i] > 0 && firstOf[find(contourOf[i])] < 0) {
            firstOf[find(contourOf[i])] = static_cast<int>(i);
        }
    }
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndUniqueAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    std::vector<double> setbackOf(contours + 1, width);
    for (int root = 1; root <= contours; ++root) {
        // A lone contour keeps the width (CT1)
        if (firstOf[root] < 0 || size[root] < 2) {
            continue;
        }
        const Wedge head = wedgeOf(maker, contourOf[firstOf[root]], edgeFaces);
        std::string fault = head.fault;
        for (int ic = 1; ic <= contours && fault.empty(); ++ic) {
            if (find(ic) != root) {
                continue;
            }
            const Wedge wedge = wedgeOf(maker, ic, edgeFaces);
            if (!wedge.fault.empty()) {
                fault = wedge.fault;
            }
            else if (wedge.convex != head.convex) {
                fault = "the chain mixes convex and concave edges";
            }
            else if (std::abs(wedge.angle - head.angle) > 1e-9) {
                // A concave chain by the air-side angle (Q-CC1's likely answer: the same ball)
                const double setback
                    = width * std::tan(head.angle / 2) / std::tan(wedge.angle / 2);
                if (!std::isfinite(setback) || setback <= linearTolerance) {
                    fault = "a setback that isn't finite";
                }
                setbackOf[ic] = setback;
            }
        }
        if (!fault.empty()) {
            FC_LOG("chamfer chain from edge " << firstOf[root] + 1 << " keeps the width: " << fault);
            for (int ic = 1; ic <= contours; ++ic) {
                if (find(ic) == root) {
                    setbackOf[ic] = width;
                }
            }
        }
    }
    for (std::size_t i = 0; i < edges.size(); ++i) {
        if (contourOf[i] > 0) {
            setbacks[i] = setbackOf[contourOf[i]];
        }
    }
    return setbacks;
}

}  // namespace

std::vector<double> chainSetbacks(
    const TopoShape& input,
    const std::vector<TopoShape>& edges,
    double width
)
{
    if (edges.size() < 2 || !(width > linearTolerance) || input.isNull()) {
        return std::vector<double>(edges.size(), width);
    }
    try {
        return setbacksOf(input.getShape(), edges, width);
    }
    catch (const Refusal& refusal) {
        FC_LOG("chamfer chains keep the width: " << refusal.reason);
    }
    catch (const Standard_Failure& e) {
        FC_LOG("chamfer chains keep the width: " << e.GetMessageString());
    }
    return std::vector<double>(edges.size(), width);
}

std::vector<TopoShape> makerInputs(const std::vector<TopoShape>& shapes)
{
    TopoDS_Compound compound;
    BRep_Builder builder;
    builder.MakeCompound(compound);
    for (const auto& shape : shapes) {
        if (!shape.isNull()) {
            builder.Add(compound, shape.getShape());
        }
    }
    // The topology alone, as makerInput()'s: one copy of them all keeps what they share shared
    const TopoDS_Shape copied = BRepBuilderAPI_Copy(compound, false).Shape();
    std::vector<TopoShape> copies;
    TopoDS_Iterator it(copied);
    for (const auto& shape : shapes) {
        TopoShape copy(shape);
        if (!shape.isNull()) {
            // As makeElementCopy() keeps a copy's names: its sub-shapes come in the same order
            copy.setShape(it.Value(), false);
            it.Next();
        }
        copies.push_back(copy);
    }
    return copies;
}

bool endsInCusp(const TopoDS_Shape& base, const std::vector<TopoDS_Shape>& edges)
{
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
    TopExp::MapShapesAndUniqueAncestors(base, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    TopExp::MapShapesAndUniqueAncestors(base, TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
    auto selected = [&](const TopoDS_Shape& edge) {
        return std::any_of(edges.begin(), edges.end(), [&](const TopoDS_Shape& e) {
            return e.IsSame(edge);
        });
    };
    for (const auto& shape : edges) {
        if (shape.ShapeType() != TopAbs_EDGE || !edgeFaces.Contains(shape)) {
            continue;
        }
        const TopoDS_Edge& edge = TopoDS::Edge(shape);
        const auto& faces = edgeFaces.FindFromKey(edge);
        if (faces.Extent() != 2 || BRep_Tool::Degenerated(edge)) {
            continue;
        }
        TopoDS_Vertex ends[2];
        TopExp::Vertices(edge, ends[0], ends[1]);
        if (ends[0].IsNull() || ends[1].IsNull() || ends[0].IsSame(ends[1])) {
            continue;
        }
        for (const auto& vertex : ends) {
            if (!vertexEdges.Contains(vertex)) {
                continue;
            }
            // awayFrom refuses a null tangent: outside the construction that would escape as an
            // unknown exception on a chamfer OCCT built (review r5); such an edge is no cusp
            auto direction = [&](const TopoDS_Edge& e, gp_Dir& out) {
                try {
                    out = awayFrom(e, vertex);
                    return true;
                }
                catch (const Refusal&) {
                    return false;
                }
            };
            gp_Dir away;
            if (!direction(edge, away)) {
                continue;
            }
            for (const auto& item : vertexEdges.FindFromKey(vertex)) {
                if (item.IsSame(edge) || selected(item) || !edgeFaces.Contains(item)
                    || BRep_Tool::Degenerated(TopoDS::Edge(item))) {
                    continue;
                }
                const auto& ofOther = edgeFaces.FindFromKey(item);
                bool onOwnFace = std::any_of(ofOther.begin(), ofOther.end(), [&](const TopoDS_Shape& f) {
                    return f.IsSame(faces.First()) || f.IsSame(faces.Last());
                });
                gp_Dir otherAway;
                if (onOwnFace && direction(TopoDS::Edge(item), otherAway)
                    && otherAway.Dot(away) > 1 - angularTolerance) {
                    return true;
                }
            }
        }
    }
    return false;
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

bool construct(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    Construction& out,
    std::string* reason
)
{
    std::string why;
    try {
        auto mapper = std::make_shared<ShapeMapper>();
        int corners = 0;
        TopoDS_Shape shape = constructShape(base, edges, request, *mapper, corners);
        TopTools_IndexedMapOfShape selected;
        for (const auto& edge : edges) {
            selected.Add(edge);
        }
        out.shape = shape;
        out.mapper = mapper;
        out.edges = selected.Extent();
        out.corners = corners;
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
    if (reason) {
        *reason = why;
    }
    return false;
}

bool preferConstruction(
    const TopoDS_Shape& baseShape,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
)
{
    if (request.kind != Kind::Fillet || request.size1 <= 0) {
        return false;
    }
    try {
        const TopoShape base(baseShape);
        Context ctx(base, request);
        for (const auto& edge : edges) {
            if (edge.IsNull() || edge.ShapeType() != TopAbs_EDGE) {
                continue;
            }
            try {
                if (tightArc(ctx, analyse(ctx, TopoDS::Edge(edge)))) {
                    return true;
                }
            }
            catch (const Refusal&) {
                // Not analysable: not a tight arc
            }
        }
    }
    catch (const Standard_Failure&) {
    }
    catch (const Base::Exception&) {
    }
    return false;
}

void finish(TopoShape& result, const Construction& construction, const TopoShape& base, const char* op)
{
    // A copy keeps the result's tag, hasher and history algorithm, which name the elements
    TopoShape built(result);
    built.makeShapeWithElementMap(construction.shape, *construction.mapper, {base}, op);
    result = built;
    FC_LOG("built exactly: " << construction.edges << " edges, " << construction.corners << " corners");
    Recorder::add(construction.edges, construction.corners);
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
    std::vector<TopoDS_Shape> edgeShapes;
    edgeShapes.reserve(edges.size());
    for (const auto& edge : edges) {
        edgeShapes.push_back(edge.getShape());
    }
    Construction construction;
    std::string why;
    if (!construct(base.getShape(), edgeShapes, request, construction, &why)) {
        FC_LOG("exact construction refused: " << why);
        if (reason) {
            *reason = why;
        }
        return false;
    }
    try {
        finish(result, construction, base, op);
        return true;
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
    FC_LOG("exact construction refused: " << why);
    if (reason) {
        *reason = why;
    }
    return false;
}

std::optional<gp_Pnt> materialIn(const TopoDS_Shape& result, const TopoDS_Shape& region)
{
    Bnd_Box box;
    BRepBndLib::Add(region, box);
    if (box.IsVoid()) {
        return std::nullopt;
    }
    double lo[3];
    double hi[3];
    box.Get(lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]);
    const double tolerance = std::max(largestTolerance(result), largestTolerance(region));
    IntCurvesFace_ShapeIntersector crossings;
    crossings.Load(region, tolerance);
    BRepClass3d_SolidClassifier inRegion(region);
    BRepClass3d_SolidClassifier inResult(result);
    // A point is reported only where the region is thicker than 20 tolerances along every axis
    // through it: a sheet thinner than that is noise, whichever way the lines run
    auto deepIn = [&](const gp_Pnt& point) {
        for (int axis = 0; axis < 3; ++axis) {
            const gp_Lin line(point, axis == 0 ? gp::DX() : axis == 1 ? gp::DY() : gp::DZ());
            crossings.Perform(line, -Precision::Infinite(), Precision::Infinite());
            if (!crossings.IsDone()) {
                return false;
            }
            double below = -Precision::Infinite();
            double above = Precision::Infinite();
            for (int k = 1; k <= crossings.NbPnt(); ++k) {
                const double w = crossings.WParameter(k);
                if (w <= 0.0) {
                    below = std::max(below, w);
                }
                else {
                    above = std::min(above, w);
                }
            }
            if (above - below <= 20.0 * tolerance) {
                return false;
            }
        }
        return true;
    };
    constexpr int lines = 9;
    for (int axis = 0; axis < 3; ++axis) {
        const int u = (axis + 1) % 3;
        const int v = (axis + 2) % 3;
        double direction[3] = {0.0, 0.0, 0.0};
        direction[axis] = 1.0;
        for (int i = 0; i < lines; ++i) {
            for (int j = 0; j < lines; ++j) {
                double origin[3];
                origin[axis] = lo[axis];
                origin[u] = lo[u] + (hi[u] - lo[u]) * (i + 0.5) / lines;
                origin[v] = lo[v] + (hi[v] - lo[v]) * (j + 0.5) / lines;
                const gp_Lin line(
                    gp_Pnt(origin[0], origin[1], origin[2]),
                    gp_Dir(direction[0], direction[1], direction[2])
                );
                crossings.Perform(line, -Precision::Infinite(), Precision::Infinite());
                if (!crossings.IsDone()) {
                    continue;
                }
                std::vector<double> at;
                for (int k = 1; k <= crossings.NbPnt(); ++k) {
                    at.push_back(crossings.WParameter(k));
                }
                std::sort(at.begin(), at.end());
                for (size_t k = 1; k < at.size(); ++k) {
                    if (at[k] - at[k - 1] <= 20.0 * tolerance) {
                        continue;
                    }
                    const gp_Pnt point = ElCLib::Value((at[k] + at[k - 1]) / 2.0, line);
                    inRegion.Perform(point, tolerance);
                    if (inRegion.State() != TopAbs_IN) {
                        continue;
                    }
                    inResult.Perform(point, tolerance);
                    if (inResult.State() == TopAbs_IN && deepIn(point)) {
                        return point;
                    }
                }
            }
        }
    }
    return std::nullopt;
}

}  // namespace Part::FilletFallback
