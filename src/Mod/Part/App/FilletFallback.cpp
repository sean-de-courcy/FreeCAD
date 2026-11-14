// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <cmath>
#include <functional>
#include <memory>
#include <numbers>
#include <limits>
#include <optional>
#include <sstream>

#include <BOPTools_AlgoTools.hxx>
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
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepCheck_Result.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepLib.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
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
#include <ChFi3d.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>
#include <BRepLib.hxx>
#include <ElCLib.hxx>
#include <ElSLib.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <Geom2d_Curve.hxx>
#include <GeomAPI_IntSS.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GeomAPI.hxx>
#include <Geom2dAPI_Interpolate.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_Line.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_Line.hxx>
#include <Geom_ToroidalSurface.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <TColgp_HArray1OfPnt2d.hxx>
#include <TopAbs.hxx>
#include <TopTools_DataMapOfShapeShape.hxx>
#include <gp_Dir2d.hxx>
#include <gp_Vec2d.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Circle.hxx>
#include <Geom_Curve.hxx>
#include <GeomAdaptor_Curve.hxx>
#include <Geom_OffsetSurface.hxx>
#include <Geom_Plane.hxx>
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
#include <gce_MakeCirc.hxx>
#include <gp.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Circ.hxx>
#include <gp_Cone.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Dir.hxx>
#include <gp_Elips.hxx>
#include <gp_Hypr.hxx>
#include <gp_Lin.hxx>
#include <gp_Parab.hxx>
#include <gp_Pln.hxx>
#include <gp_Sphere.hxx>
#include <gp_Torus.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <gp_XY.hxx>

#include <Base/Console.h>
#include <Base/Exception.h>

#include "FilletFallback.h"
#include "MassProperties.h"
#include "RollingBallBlend.h"
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

/// The refusal where OCCT's contour runs on past the selection (constructShape()): where a narrow
/// strip explains the failure (narrowStrip()), the user is told that instead
const char* const tangentChainRefusal
    = "OCCT's contour runs on along a tangent chain onto an unselected edge";

/// Thrown inside the construction when it refuses; caught by build()
struct Refusal
{
    std::string reason;
};

[[noreturn]] void refuse(const std::string& reason)
{
    throw Refusal {reason};
}

/// The kind of an edge's curve, for a refusal's text
std::string curveKind(GeomAbs_CurveType type)
{
    switch (type) {
        case GeomAbs_Ellipse:
            return "an ellipse";
        case GeomAbs_Hyperbola:
            return "a hyperbola";
        case GeomAbs_Parabola:
            return "a parabola";
        case GeomAbs_BezierCurve:
            return "a Bezier";
        case GeomAbs_BSplineCurve:
            return "a B-spline";
        case GeomAbs_OffsetCurve:
            return "an offset curve's";
        default:
            return "a free-form";
    }
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
        case GeomAbs_Cone:
            // The face beyond an overflowing end (VertexClass::Overflow): Nest Cover's chamfer cone
            ElSLib::Parameters(surface.Cone(), point, u, v);
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

/// The face's outward normal at a point on it, on any surface: the point projected on it
gp_Dir outwardNormalAny(const TopoDS_Face& face, const gp_Pnt& point)
{
    BRepAdaptor_Surface adaptor(face, Standard_False);
    // The surfaces outwardNormal knows, in closed form (a cone: the face beyond an overflowing end)
    if (adaptor.GetType() == GeomAbs_Plane || adaptor.GetType() == GeomAbs_Cylinder
        || adaptor.GetType() == GeomAbs_Cone) {
        return outwardNormal(face, point);
    }
    Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    if (surface.IsNull()) {
        refuse("a face without a surface");
    }
    GeomAPI_ProjectPointOnSurf projection(point, surface);
    if (projection.NbPoints() == 0 || projection.LowerDistance() > 1000 * linearTolerance) {
        refuse("a point of an edge is not on its face's surface");
    }
    double u = 0.0;
    double v = 0.0;
    projection.LowerDistanceParameters(u, v);
    gp_Pnt onSurface;
    gp_Vec du;
    gp_Vec dv;
    surface->D1(u, v, onSurface, du, dv);
    gp_Vec normal = du.Crossed(dv);
    if (normal.Magnitude() < linearTolerance) {
        refuse("degenerate face normal");
    }
    if (face.Orientation() == TopAbs_REVERSED) {
        normal.Reverse();
    }
    return gp_Dir(normal);
}

/// inwardIn, on any surface (outwardNormalAny)
gp_Dir inwardInAny(const TopoDS_Face& face, const TopoDS_Edge& edge, double parameter)
{
    BRepAdaptor_Curve curve(edge);
    gp_Pnt point;
    gp_Vec tangent;
    curve.D1(parameter, point, tangent);
    if (orientationIn(face, edge) == TopAbs_REVERSED) {
        tangent.Reverse();
    }
    gp_Vec left = gp_Vec(outwardNormalAny(face, point)).Crossed(tangent);
    if (left.Magnitude() < linearTolerance) {
        refuse("degenerate edge tangent");
    }
    return gp_Dir(left);
}

/// Faces of the same plane, or of the same cylinder
bool sameDomain(const TopoDS_Face& face, const TopoDS_Face& other)
{
    // One surface (an overflowing end's trim, built on the face beyond's own cone)
    TopLoc_Location faceLocation;
    TopLoc_Location otherLocation;
    if (BRep_Tool::Surface(face, faceLocation) == BRep_Tool::Surface(other, otherLocation)
        && faceLocation.IsEqual(otherLocation)) {
        return true;
    }
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
    /// Two convex edges at a vertex reflex in the plane face they share, where an edge is a
    /// circle (FSLC #50; fillet-tight-arc 8): Onshape's mitre, the higher round kept where both
    /// reach. Each tool runs on past the vertex (VertexEnd::runOn) and ends on the mitre, the
    /// vertical cylinder over the two walls' bisector. No face of the corner's own
    Corner2Reflex,
    /// All three edges at the vertex are selected (a three-edge corner): the edge tools end
    /// where a corner tool (a sphere patch, or a chamfer's corner triangle) begins
    Corner3,
    /// A chamfer's edge that ends in a cusp: an unselected edge of one of its faces leaves the
    /// vertex the way it does, on an end face that holds both (Case Base #76). The tool ends on
    /// the plane through the vertex normal to the edge, as Onshape's; nothing caps it there
    CuspEnd,
    /// A concave fillet's circle whose chain turns convex here (Nest Cover #151; oracle 17 Q-OVF,
    /// onshape-facts OV3, TP1-TP2): a vertex of 4 edges where the circle's cylinder carries on
    /// tangentially into a wall, and an unselected convex edge between that wall and the face
    /// beyond the circle's plane face carries the circle on tangentially (the floor's rim leaves
    /// the vertex the circle's way, between the plane face and the face beyond). Onshape's tangent
    /// propagation stops here, and its end round rolls on past the vertex (allowEdgeOverflow),
    /// trimmed by the surface of the face beyond: the tool turns on a quarter turn past the
    /// vertex, into the material behind the wall, and keeps the material's side of that surface
    Overflow,
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
    /// On the faces next to the source: an edge tool's two, in the order of EdgeData::faces (and a
    /// third on the face a rolled round rolls onto, rollOn); a corner piece's three
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
    /// A curved end's surface that runs on across the tool's other end, where a selected edge
    /// continues it tangentially: that edge's tool is trimmed by it too (Case Base #105, a round cut
    /// off along a short last edge and into the one before it)
    struct PassOn
    {
        TopoDS_Face face;  // the surface, as the tool was split by it
        TopoDS_Face endFace;  // the end face it is the surface of
        TopoDS_Edge edge;  // the continuing edge
        gp_Pnt vertex;     // where they meet
        bool cap = false;  // the face is on the end face's own surface (capSurfaces)
        TopoDS_Face beyond;  // a blend's continuation past its end, split by with the face (blendBeyond)
    };
    std::vector<PassOn> passOn;
    /// The end faces (not planes) whose surfaces trim the tool: a strip that runs off its face
    /// over an edge onto one of them runs into the surface that cut it off, by construction
    std::vector<TopoDS_Face> surfaceEnds;
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
    /// The faces whose surfaces trim the tool past its overflowing ends (VertexClass::Overflow):
    /// its strips run off both faces there, into the material, and its faces on those surfaces
    /// merge into them. Its volume is then measured, after the revolution's closed form is checked
    std::vector<TopoDS_Face> overflowFaces;
    /// The miter piece at a concave corner with a circle: its faces merge into the tools' faces
    /// they continue (one cone, one plane, as Onshape's sharp miter)
    bool miter = false;
    /// A round rolled on over a tangent edge onto the next face (rollOn): a concave edge's fills
    /// air only, a convex edge's removes material only, as its construction assumes
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
    /// The relative tolerance of the volume check: the closed forms' own, or a quadrature's
    /// (a reflex corner's cut tools, Corner2Reflex)
    double relTolerance = volumeTolerance;
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
/** A rolling-ball blend's continuation past its own face (Case Base #105's ends, notes
 * r105-curved-end-trim). An OCCT fillet stores a blend as a B-spline surface that is the blend
 * inside its face and for a short run past it, and then continues the spine straight: a tool cut
 * by that surface's natural bounds is cut wrongly (#105: 3.5e-3 at a round 1 high). Onshape
 * continues the rolling ball: the ball's centre runs on along the intersection of the two
 * supports' offsets by the radius, and the blend is the canal surface about that spine, each
 * section the arc between the ball's two contact points.
 *
 * alongV, atUpper, bound: the direction the blend runs in the surface's parameters, and the face's
 * own bound at the end nearest the point; the surface is used up to that bound only. beyond: the
 * canal surface from that bound on, its first section the surface's own.
 */
struct BlendBeyond
{
    bool alongV = true;
    bool atUpper = false;
    double bound = 0.0;
    TopoDS_Face beyond;
};

struct Context
{
    const TopoShape& base;
    const Request& request;
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
    TopTools_IndexedDataMapOfShapeListOfShape vertexFaces;
    TopTools_IndexedMapOfShape selected;
    double scale = 1.0;  // the base's size, for the half-spaces
    /// The blends' continuations built so far, by wall and end (blendBeyond): one per end, so that
    /// every tool cut by it is cut by the same surface
    struct KnownBlend
    {
        TopoDS_Face wall;
        bool alongV = true;
        bool atUpper = false;
        double reach = 0.0;  // how far past the end it was asked to go
        std::optional<BlendBeyond> beyond;
    };
    mutable std::vector<KnownBlend> blends;

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
        // OCCT's own round is the one along any other curve (notes/fillet-spline-edge.md): the
        // refusal says that OCCT failed there, not that the edge isn't allowed (NEW-165, ops#640)
        refuse(
            std::string("the exact construction covers lines and circles; OCCT failed on a ")
            + (ctx.request.kind == Kind::Chamfer ? "chamfer" : "round") + " along "
            + curveKind(curve.GetType()) + " edge"
        );
    }
    // Convex when the second face turns away from the first's outward normal
    double middle = (data.first + data.last) / 2;
    gp_Pnt point = curve.Value(middle);
    gp_Dir inward1 = inwardIn(data.faces[1], edge, middle);
    data.convex = inward1.Dot(outwardNormal(data.faces[0], point)) < 0;
    return data;
}

/** A straight edge between two cylinders along it (Case Base #104, ops#640). OCCT's round there is
 * valid, but a B-spline face between B-spline edges, where the exact round is a cylinder
 * (Onshape's); a later dress-up over an end of it then meets an edge that is neither a line nor a
 * circle (#105). Between a plane and a cylinder OCCT's round is a cylinder already
 */
bool betweenCylinders(const EdgeData& data)
{
    auto onCylinder = [](const TopoDS_Face& face) {
        return BRepAdaptor_Surface(face, Standard_False).GetType() == GeomAbs_Cylinder;
    };
    return data.ruled && onCylinder(data.faces[0]) && onCylinder(data.faces[1]);
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
    TopoDS_Face beyond;        // Overflow: the face whose surface trims the end round
    std::string reason;
    /// Corner2Reflex: the other selected edge, and how far the tool runs on past the vertex (an
    /// angle about a circle's axis, a length along a line), set before the tool is built
    TopoDS_Edge other;
    double runOn = 0.0;
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
    // Convex edges at a vertex reflex in the shared face: each edge leaves the vertex away from
    // the face's side of the other (FSLC #50): Onshape's mitre (Corner2Reflex)
    if (!concave && inwardIn(shared, data.edge, here).Dot(otherAway) < -angularTolerance
        && inwardIn(shared, other->edge, there).Dot(away) < -angularTolerance) {
        if (ctx.request.kind != Kind::Fillet) {
            end.reason = "a chamfer at a reflex corner with a circle";
            return end;
        }
        end.kind = VertexClass::Corner2Reflex;
        end.other = other->edge;
        end.trims = {{BRepAdaptor_Curve(data.edge).Value(here), away.Reversed()}};
        return end;
    }
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

/** The end of a concave fillet's circle at a vertex of 4 edges where its chain turns convex
 * (VertexClass::Overflow), or none, with why not in why. The edges and faces are the vertex's.
 */
std::optional<VertexEnd> overflowEnd(
    const Context& ctx,
    const EdgeData& data,
    const TopoDS_Vertex& vertex,
    const std::vector<TopoDS_Shape>& edges,
    const std::vector<TopoDS_Shape>& faces,
    std::string& why
)
{
    if (ctx.request.kind != Kind::Fillet || data.line || data.convex || data.ruled || data.closed) {
        why = "not a concave fillet's arc";
        return std::nullopt;
    }
    const TopoDS_Face& plane = data.faces[data.planeFace];
    const TopoDS_Face& cylinder = data.faces[1 - data.planeFace];
    if (ChFi3d::DefineConnectType(data.edge, data.faces[0], data.faces[1], Precision::Angular(), Standard_False)
        != ChFiDS_Concave) {
        why = "OCCT does not read the arc as concave";
        return std::nullopt;
    }
    gp_Dir away = awayFrom(data.edge, vertex);
    TopoDS_Edge continuation;
    std::vector<TopoDS_Edge> others;
    for (const auto& shape : edges) {
        const TopoDS_Edge& other = TopoDS::Edge(shape);
        if (other.IsSame(data.edge)) {
            continue;
        }
        if (ctx.selected.Contains(other)) {
            why = "another selected edge there";
            return std::nullopt;
        }
        if (awayFrom(other, vertex).Dot(away) < -1 + angularTolerance) {
            if (!continuation.IsNull()) {
                why = "two tangent continuations";
                return std::nullopt;
            }
            continuation = other;
        }
        else {
            others.push_back(other);
        }
    }
    if (continuation.IsNull() || others.size() != 2) {
        why = "no tangent continuation";
        return std::nullopt;
    }
    // The continuation runs between the face beyond and the wall the arc's cylinder carries on
    // into (Q-OVF: the bevel/wall edge under the wall); of the other two edges, one leaves the
    // vertex the arc's way between the arc's plane face and the face beyond (the floor's rim), and
    // one runs between the arc's cylinder and the wall, tangent there
    auto ofContinuation = ctx.list(ctx.edgeFaces, continuation);
    if (ofContinuation.size() != 2) {
        why = "the tangent continuation is not between two faces";
        return std::nullopt;
    }
    for (const auto& face : ofContinuation) {
        if (face.IsSame(plane) || face.IsSame(cylinder)) {
            why = "the tangent continuation lies on the arc's own face";
            return std::nullopt;
        }
    }
    if (ChFi3d::DefineConnectType(
            continuation,
            TopoDS::Face(ofContinuation[0]),
            TopoDS::Face(ofContinuation[1]),
            Precision::Angular(),
            Standard_False
        )
        != ChFiDS_Convex) {
        why = "the tangent continuation is not convex";
        return std::nullopt;
    }
    TopoDS_Face beyond;
    TopoDS_Face wall;
    bool tangentWall = false;
    for (const auto& other : others) {
        auto of = ctx.list(ctx.edgeFaces, other);
        if (of.size() != 2) {
            why = "an edge at the vertex is not between two faces";
            return std::nullopt;
        }
        auto has = [&](const TopoDS_Shape& face) {
            return of[0].IsSame(face) || of[1].IsSame(face);
        };
        for (int k = 0; k < 2; ++k) {
            const TopoDS_Face candidate = TopoDS::Face(ofContinuation[k]);
            const TopoDS_Face opposite = TopoDS::Face(ofContinuation[1 - k]);
            if (has(plane) && has(candidate)
                && awayFrom(other, vertex).Dot(away) > 1 - angularTolerance) {
                beyond = candidate;
            }
            else if (has(cylinder) && has(opposite)) {
                wall = opposite;
                tangentWall = ChFi3d::IsTangentFaces(other, TopoDS::Face(of[0]), TopoDS::Face(of[1]));
            }
        }
    }
    if (beyond.IsNull() || wall.IsNull() || beyond.IsSame(wall) || !tangentWall) {
        why = "the arc's cylinder does not carry on tangentially into a wall on the face beyond its "
              "plane face";
        return std::nullopt;
    }
    BRepAdaptor_Surface beyondSurface(beyond, Standard_False);
    if (beyondSurface.GetType() != GeomAbs_Plane && beyondSurface.GetType() != GeomAbs_Cone) {
        why = "the face beyond is neither a plane nor a cone";
        return std::nullopt;
    }
    for (const auto& face : faces) {
        if (!face.IsSame(plane) && !face.IsSame(cylinder) && !face.IsSame(beyond) && !face.IsSame(wall)) {
            why = "a fifth face at the vertex";
            return std::nullopt;
        }
    }
    VertexEnd end;
    end.kind = VertexClass::Overflow;
    end.beyond = beyond;
    end.trims = {{BRep_Tool::Pnt(vertex), away.Reversed()}};
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
    if (edges.size() == 4 && faces.size() == 4) {
        std::string why;
        if (auto overflow = overflowEnd(ctx, data, vertex, edges, faces, why)) {
            return *overflow;
        }
        end.reason = "a vertex where 4 edges meet (" + why + ")";
        return end;
    }
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
            // The end face is tangent to the edge at the vertex: a blend that runs out tangent to
            // one of the edge's faces, which is what Case Base #105's ends are (the fork's own
            // blend gives 0 here; Onshape's STEP body 1.8e-6, which passed by its noise). The
            // tangent plane bounds nothing there, and nothing reads it: the tool is bounded by
            // the surface, from the vertex (lineTool, trimBySurface). The plane kept is the one
            // through the vertex square to the edge
            normal = away.Reversed();
        }
        else if (normal.Dot(away) > 0) {
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
 * An edge whose ball can't touch one of its faces, where that face ends in a tangent edge along
 * the edge onto a face that is a prism along it, rolls on onto that face (rolledTool)
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
    /// A circle the ball rolls inside and is as big as: it touches it nowhere (it may roll on over
    /// the face's tangent edge, rollOn)
    bool tooSmall = false;
};

const char* const tooSmallReason = "a round as big as the cylinder it rolls inside";

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
        t.tooSmall = t.offset <= linearTolerance;
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
    if (a.tooSmall || b.tooSmall) {
        return found;
    }
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

/** A ball that can't touch the face k (Case Base #47, ops#640; a concave edge's ball in the air,
 * or a convex edge's in the material, its mirror image): where that face
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
    /// How far along face k's trace from the corner the tangent point lies (traceTravel)
    double travel = 0.0;
};

/// How far along the trace from its start the point lies: a length on a line, an angle on a circle
double traceTravel(const RuledTrace& t, const gp_Pnt& point, const gp_Vec& z)
{
    if (t.circle) {
        return std::abs(tracePiece(t, point, z).angle);
    }
    return gp_Vec(t.origin, point).Dot(gp_Vec(t.inward));
}

/** Face k's tangent edge along the edge onto a prism along it that runs the edge's whole length,
 * the first its trace reaches from the corner (rollOn), with the face beyond and the tangent point;
 * empty if it has none. Not strict: any straight edge along the edge on the trace, where the face
 * beyond is tangent to it or is neither a plane nor a cylinder (review r3 of #47: a touch past such
 * an edge must roll on, or refuse)
 */
std::optional<Rolled> tangentEdgeOf(
    const Context& ctx,
    const EdgeData& data,
    const RuledTrace traces[2],
    int k,
    bool strict = true
)
{
    gp_Dir direction(gp_Vec(data.start, data.end));
    gp_Vec z(direction);
    double length = data.start.Distance(data.end);
    const gp_Pnt& corner = data.start;
    const TopoDS_Face& face = data.faces[k];
    const RuledTrace& mine = traces[k];
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
        BRepAdaptor_Surface surface(next, Standard_False);
        bool known = surface.GetType() == GeomAbs_Plane || surface.GetType() == GeomAbs_Cylinder;
        if (!known && strict) {
            continue;
        }
        if (known
            && (gp_Vec(outwardNormal(face, middle)).Crossed(gp_Vec(outwardNormal(next, middle))).Magnitude()
                    > tangentTolerance
                || outwardNormal(face, middle).Dot(outwardNormal(next, middle)) <= 0)) {
            continue;
        }
        bool prism = surface.GetType() == GeomAbs_Plane
            || (surface.GetType() == GeomAbs_Cylinder
                && parallel(surface.Cylinder().Axis().Direction(), direction));
        if (!prism && strict) {
            continue;
        }
        // The tangent edge must run the edge's whole length
        gp_Pnt a = curve.Value(curve.FirstParameter());
        gp_Pnt b = curve.Value(curve.LastParameter());
        double sa = gp_Vec(corner, a).Dot(z);
        double sb = gp_Vec(corner, b).Dot(z);
        double tolerance = std::max(linearTolerance, BRep_Tool::Tolerance(edge));
        if (strict && (std::min(sa, sb) > tolerance || std::max(sa, sb) < length - tolerance)) {
            continue;
        }
        gp_Pnt point = a.Translated(z * -sa);
        // How far along the trace, from the corner in its sense
        bool onTrace = mine.circle
            ? std::abs(point.Distance(mine.centre) - mine.radius) <= tolerance
            : gp_Lin(corner, mine.inward).Distance(point) <= tolerance;
        if (!onTrace) {
            continue;
        }
        double here = traceTravel(mine, point, z);
        if (here <= linearTolerance || here >= travel) {
            continue;
        }
        Rolled candidate;
        candidate.next = next;
        candidate.tangentPoint = point;
        candidate.travel = here;
        travel = here;
        rolled = candidate;
    }
    return rolled;
}

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
    std::optional<Rolled> rolled = tangentEdgeOf(ctx, data, traces, k);
    if (!rolled) {
        return std::nullopt;
    }
    const double travel = rolled->travel;
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
    if (next.tooSmall || other.tooSmall) {
        return std::nullopt;
    }
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
    // And the other face holds its trace up to the round
    if (!onFace(data.faces[1 - k], rolled->touchOther.Translated(z * (length / 2)))) {
        refuse("a round rolled on over a tangent edge that runs off its other face");
    }
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
    bool convexPastTangent = false;
    if (traces[0].tooSmall || traces[1].tooSmall) {
        reason = tooSmallReason;
    }
    else if (candidates.empty()) {
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
            // A concave round's touch past its face's tangent edge (onto a round beyond, review r1
            // of #47) would leave the tool's strip in the material there, absorbed, and the round
            // not tangent to the face beyond: Onshape's ball rolls on over that edge instead. A
            // touch past any other end of the face is left to the run-off rules (#46: over a
            // concave edge into a wall, the material absorbs it; into the air, it refuses).
            // A convex round's touch past its face's tangent edge is the mirror image (Case Base
            // #104, ops#640: a sliver of a corner's cylinder, tangent to the wall beyond; the round
            // between the two cylinders would touch the sliver's cylinder past that edge, inside
            // the wall). Onshape's ball rolls on there too: the round is tangent to the wall, and
            // the sliver vanishes. Tried first; where the ball doesn't roll on, the run-off rules
            // as before
            else if (!onFace(data.faces[k], touches[k].Translated(gp_Vec(direction) * (length / 2)))) {
                auto tangent = tangentEdgeOf(ctx, data, traces, k, false);
                if (tangent
                    && tangent->travel <= traceTravel(traces[k], touches[k], gp_Vec(direction))) {
                    if (data.convex) {
                        convexPastTangent = true;
                    }
                    else {
                        reason = "a concave round of a straight edge on a cylinder that runs off its "
                                 "face over its tangent edge";
                    }
                }
            }
        }
    }
    if (!reason.empty() || convexPastTangent) {
        // The ball rolls on over a face's tangent edge onto the next face: a concave edge's in the
        // air, a convex edge's in the material (the mirror image; Onshape builds both, oracle 18's
        // FR3)
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
        if (!reason.empty()) {
            refuse(reason);
        }
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
TopoDS_Face sheetOf(
    const Handle(Geom_Surface)& surface,
    const TopLoc_Location& location,
    const TopoDS_Face& face,
    double reach
);

/// The iso line of the surface on that side of its bounds lies on one of the faces
bool sideOnFaces(
    const Handle(Geom_Surface)& surface,
    bool inU,
    bool after,
    const TopoDS_Face (&faces)[2]
)
{
    double u0 = 0.0;
    double u1 = 0.0;
    double v0 = 0.0;
    double v1 = 0.0;
    surface->Bounds(u0, u1, v0, v1);
    for (const auto& face : faces) {
        Handle(Geom_Surface) other = BRep_Tool::Surface(face);
        bool on = true;
        for (int k = 0; k <= 4 && on; ++k) {
            double t = k / 4.0;
            gp_Pnt point = inU ? surface->Value(after ? u1 : u0, v0 + (v1 - v0) * t)
                               : surface->Value(u0 + (u1 - u0) * t, after ? v1 : v0);
            GeomAPI_ProjectPointOnSurf projection(point, other);
            on = projection.NbPoints() > 0 && projection.LowerDistance() < 1e-6;
        }
        if (on) {
            return true;
        }
    }
    return false;
}

/** The continuation of the wall's surface past the wall's end nearest the point, where the wall is a
 * rolling-ball blend: a B-spline face whose sections across it are circles of one radius, the
 * centres one radius from the surfaces of two of its neighbours. None for any other face (its
 * surface's own bounds or extension are used, as before). A blend whose continuation can't be
 * built refuses: the surface's own run on is not the blend
 */
std::optional<BlendBeyond> blendBeyond(
    const Context& ctx,
    const TopoDS_Face& wall,
    const gp_Pnt& nearPoint,
    double reach
)
{
    TopLoc_Location location;
    Handle(Geom_BSplineSurface) blend
        = Handle(Geom_BSplineSurface)::DownCast(BRep_Tool::Surface(wall, location));
    if (blend.IsNull()) {
        return std::nullopt;
    }
    const gp_Trsf toLocal = location.Inverted().Transformation();
    const gp_Pnt nearLocal = nearPoint.Transformed(toLocal);
    double natural[4] = {0.0, 0.0, 0.0, 0.0};
    blend->Bounds(natural[0], natural[1], natural[2], natural[3]);
    double own[4] = {0.0, 0.0, 0.0, 0.0};
    BRepTools::UVBounds(wall, own[0], own[1], own[2], own[3]);
    GeomAPI_ProjectPointOnSurf onBlend(nearLocal, blend);
    if (onBlend.NbPoints() == 0) {
        return std::nullopt;
    }
    double nearU = 0.0;
    double nearV = 0.0;
    onBlend.LowerDistanceParameters(nearU, nearV);

    struct Ring
    {
        gp_Pnt centre;
        double radius = 0.0;
        gp_Pnt ends[2];
    };
    // The section across the blend at a parameter along it: a circle through five of its points
    auto ringAt = [&](bool alongV, double along) -> std::optional<Ring> {
        const double from = alongV ? natural[0] : natural[2];
        const double to = alongV ? natural[1] : natural[3];
        gp_Pnt points[5];
        for (int k = 0; k < 5; ++k) {
            const double across = from + (to - from) * k / 4.0;
            points[k] = alongV ? blend->Value(across, along) : blend->Value(along, across);
        }
        if (points[0].Distance(points[2]) < linearTolerance
            || points[2].Distance(points[4]) < linearTolerance
            || points[0].Distance(points[4]) < linearTolerance) {
            return std::nullopt;
        }
        gce_MakeCirc make(points[0], points[2], points[4]);
        if (!make.IsDone()) {
            return std::nullopt;
        }
        const gp_Circ circle = make.Value();
        const double allowed = 1e-6 * std::max(1.0, circle.Radius());
        if (circle.Distance(points[1]) > allowed || circle.Distance(points[3]) > allowed) {
            return std::nullopt;
        }
        Ring ring;
        ring.centre = circle.Location();
        ring.radius = circle.Radius();
        ring.ends[0] = points[0];
        ring.ends[1] = points[4];
        return ring;
    };
    std::optional<BlendBeyond> found;
    std::vector<Ring> rings;
    for (bool alongV : {true, false}) {
        const double first = alongV ? own[2] : own[0];
        const double last = alongV ? own[3] : own[1];
        if (last - first < Precision::PConfusion()) {
            continue;
        }
        const double nearAlong = alongV ? nearV : nearU;
        const bool atUpper = std::abs(nearAlong - last) < std::abs(nearAlong - first);
        const double bound = atUpper ? last : first;
        // Five sections in the face's last quarter towards that end
        std::vector<Ring> candidate;
        for (int k = 0; k < 5; ++k) {
            auto ring = ringAt(alongV, bound + (atUpper ? -1.0 : 1.0) * (last - first) * k / 16.0);
            if (!ring
                || (k > 0
                    && std::abs(ring->radius - candidate[0].radius)
                        > 1e-5 * std::max(1.0, candidate[0].radius))) {
                candidate.clear();
                break;
            }
            candidate.push_back(*ring);
        }
        if (candidate.empty()) {
            continue;
        }
        if (!found || candidate[0].radius < rings[0].radius) {
            found = BlendBeyond {alongV, atUpper, bound, {}};
            rings = candidate;
        }
    }
    if (!found) {
        return std::nullopt;
    }
    // One continuation per end, as long as the longest reach asked of it: a tool with a longer
    // reach gets a new one (its faces then don't merge with the earlier tools')
    size_t slot = ctx.blends.size();
    for (size_t i = 0; i < ctx.blends.size(); ++i) {
        const auto& known = ctx.blends[i];
        if (known.wall.IsSame(wall) && known.alongV == found->alongV
            && known.atUpper == found->atUpper) {
            if (!known.beyond || known.reach >= reach) {
                return known.beyond;
            }
            slot = i;
        }
    }
    if (slot == ctx.blends.size()) {
        ctx.blends.push_back({wall, found->alongV, found->atUpper, reach, std::nullopt});
    }
    else {
        ctx.blends[slot].reach = reach;
        ctx.blends[slot].beyond.reset();
    }
    const double radius = rings[0].radius;
    const double rolled = 2e-5 * std::max(1.0, radius);
    // The supports: the neighbours whose surfaces the ball's centre stays one radius from
    std::vector<Handle(Geom_Surface)> supports;
    TopTools_IndexedMapOfShape seen;
    for (TopExp_Explorer edge(wall, TopAbs_EDGE); edge.More(); edge.Next()) {
        for (const auto& shape : ctx.list(ctx.edgeFaces, edge.Current())) {
            if (shape.IsSame(wall) || seen.Contains(shape)) {
                continue;
            }
            seen.Add(shape);
            Handle(Geom_Surface) surface = BRep_Tool::Surface(TopoDS::Face(shape));
            if (surface.IsNull()) {
                continue;
            }
            if (!location.IsIdentity()) {
                surface = Handle(Geom_Surface)::DownCast(surface->Transformed(toLocal));
            }
            bool rolls = true;
            for (const auto& ring : rings) {
                GeomAPI_ProjectPointOnSurf onSupport(ring.centre, surface);
                rolls = onSupport.NbPoints() > 0
                    && std::abs(onSupport.LowerDistance() - radius) < rolled;
                if (!rolls) {
                    break;
                }
            }
            if (rolls
                && std::find(supports.begin(), supports.end(), surface) == supports.end()) {
                supports.push_back(surface);
            }
        }
    }
    if (supports.size() != 2) {
        return std::nullopt;
    }
    // The surface is still the blend for some way past the face (OCCT's fillet runs its end on as
    // far as it needed), and only then leaves it: the surface is used as far as its section's
    // centre stays one radius from both supports, so that a small tool is cut by the surface
    // alone, on the wall's own surface
    {
        const double limit = found->alongV ? (found->atUpper ? natural[3] : natural[2])
                                           : (found->atUpper ? natural[1] : natural[0]);
        const double exact = 5e-6 * std::max(1.0, radius);
        const int steps = 64;
        int good = 0;
        for (int k = 1; k <= steps; ++k) {
            const double along = found->bound + (limit - found->bound) * k / steps;
            auto ring = ringAt(found->alongV, along);
            bool rolls = ring && std::abs(ring->radius - radius) < exact;
            for (size_t i = 0; i < supports.size() && rolls; ++i) {
                GeomAPI_ProjectPointOnSurf onSupport(ring->centre, supports[i]);
                rolls = onSupport.NbPoints() > 0
                    && std::abs(onSupport.LowerDistance() - radius) < exact;
            }
            if (!rolls) {
                break;
            }
            // rings[0] becomes the last section that is the blend's, rings[1] the one before it
            rings.insert(rings.begin(), *ring);
            good = k;
        }
        found->bound += (limit - found->bound) * good / steps;
    }

    // A rolling-ball blend from here on: its continuation is built, or the dress-up is refused
    gp_Pnt contact[2];
    Handle(Geom_Surface) offsets[2];
    for (int i = 0; i < 2; ++i) {
        GeomAPI_ProjectPointOnSurf onSupport(rings[0].centre, supports[i]);
        if (onSupport.NbPoints() == 0) {
            refuse("a blend's support is not under the blend's end");
        }
        double u = 0.0;
        double v = 0.0;
        onSupport.LowerDistanceParameters(u, v);
        gp_Vec du;
        gp_Vec dv;
        supports[i]->D1(u, v, contact[i], du, dv);
        gp_Vec normal = du.Crossed(dv);
        if (normal.Magnitude() < gp::Resolution()) {
            refuse("a blend's support has no normal at the blend's end");
        }
        normal.Normalize();
        const double side = gp_Vec(contact[i], rings[0].centre).Dot(normal) > 0 ? 1.0 : -1.0;
        if (Handle(Geom_Plane) plane = Handle(Geom_Plane)::DownCast(supports[i])) {
            offsets[i] = Handle(Geom_Surface)::DownCast(plane->Translated(normal * (side * radius)));
        }
        else {
            try {
                offsets[i] = new Geom_OffsetSurface(supports[i], side * radius);
            }
            catch (const Standard_Failure&) {
                refuse("a blend's support can't be offset by the blend's radius");
            }
        }
    }
    // Which end of the section lies on which support
    if (rings[0].ends[0].Distance(contact[0]) > rings[0].ends[0].Distance(contact[1])) {
        std::swap(supports[0], supports[1]);
        std::swap(contact[0], contact[1]);
    }
    // Past its face the surface's section may end a little off the contact lines (its arc is run on
    // too): the continuation's sections keep those two overhangs, so that it joins the surface's
    // last section along its whole length
    double overhang[2] = {0.0, 0.0};
    {
        gp_Vec toContact[2] = {gp_Vec(rings[0].centre, contact[0]), gp_Vec(rings[0].centre, contact[1])};
        gp_Vec axis = toContact[0].Crossed(toContact[1]);
        if (axis.Magnitude() < gp::Resolution()) {
            refuse("a blend's section at its end is not an arc");
        }
        for (int i = 0; i < 2; ++i) {
            overhang[i] = toContact[i].AngleWithRef(gp_Vec(rings[0].centre, rings[0].ends[i]), axis);
            if (std::abs(overhang[i]) > 0.2) {
                refuse("a blend's section does not end on its supports");
            }
        }
    }
    const double onSpine = 1e-4 * std::max(1.0, radius);
    Handle(Geom_Curve) spine;
    double start = 0.0;
    try {
        GeomAPI_IntSS intersection(offsets[0], offsets[1], 1e-7);
        if (!intersection.IsDone()) {
            refuse("a blend's spine past its end: intersecting its supports' offsets failed");
        }
        double best = onSpine;
        for (int i = 1; i <= intersection.NbLines(); ++i) {
            GeomAPI_ProjectPointOnCurve onLine(rings[0].centre, intersection.Line(i));
            if (onLine.NbPoints() > 0 && onLine.LowerDistance() < best) {
                best = onLine.LowerDistance();
                spine = intersection.Line(i);
                start = onLine.LowerDistanceParameter();
            }
        }
    }
    catch (const Standard_Failure&) {
        refuse("a blend's spine past its end: intersecting its supports' offsets failed");
    }
    if (spine.IsNull()) {
        refuse("a blend's spine past its end was not found");
    }
    double inside = 0.0;
    {
        GeomAPI_ProjectPointOnCurve onLine(rings[1].centre, spine);
        if (onLine.NbPoints() == 0 || onLine.LowerDistance() > onSpine) {
            refuse("a blend's spine past its end does not follow the blend");
        }
        inside = onLine.LowerDistanceParameter();
    }
    const double first = spine->FirstParameter();
    const double last = spine->LastParameter();
    double step = start - inside;
    if (spine->IsPeriodic() && std::abs(step) > (last - first) / 2) {
        step -= std::copysign(last - first, step);
    }
    if (std::abs(step) < Precision::PConfusion()) {
        refuse("a blend's spine past its end has no direction");
    }
    const double outward = step > 0 ? 1.0 : -1.0;
    GeomAdaptor_Curve adaptor(spine);
    const double total = GCPnts_AbscissaPoint::Length(adaptor, first, last);
    const double length = std::min(reach, 0.45 * total);
    double finish = outward > 0 ? last : first;
    {
        GCPnts_AbscissaPoint at(adaptor, outward * length, start);
        if (at.IsDone()) {
            finish = at.Parameter();
        }
    }
    if (!spine->IsPeriodic()) {
        finish = std::clamp(finish, first, last);
    }
    // No further than a quarter turn of the spine: on a closed spine the continuation would come
    // back to the blend's other end, or to another blend on the same supports (a wall's two
    // blends on a sphere are one torus), and cut the tool there
    {
        gp_Pnt at;
        gp_Vec leaving;
        spine->D1(start, at, leaving);
        const int probes = 64;
        for (int k = 1; k <= probes; ++k) {
            const double parameter = start + (finish - start) * k / probes;
            gp_Vec tangent;
            spine->D1(parameter, at, tangent);
            if (leaving.Magnitude() < gp::Resolution() || tangent.Magnitude() < gp::Resolution()
                || leaving.Angle(tangent) > std::numbers::pi / 2) {
                finish = start + (finish - start) * (k - 1) / probes;
                break;
            }
        }
        if (std::abs(finish - start) < Precision::PConfusion()) {
            refuse("a blend's spine past its end turns back at once");
        }
    }
    // The sections: at the blend's end the surface's own, then the ball's on the spine. As many as
    // keep the surface through them within 1e-8 of the canal surface: a cubic through sections a
    // step h apart is off by about h^4 / (384 R^3) where the spine's radius of curvature is R. No
    // more: every Boolean with a tool cut by this surface pays for its control points (#105: 161
    // sections over a quarter turn cost 68 s)
    int count = 9;
    {
        double tightest = Precision::Infinite();
        for (int k = 0; k <= 16; ++k) {
            gp_Pnt at;
            gp_Vec d1;
            gp_Vec d2;
            spine->D2(start + (finish - start) * k / 16.0, at, d1, d2);
            const double cross = d1.Crossed(d2).Magnitude();
            if (cross > gp::Resolution()) {
                tightest = std::min(tightest, std::pow(d1.Magnitude(), 3) / cross);
            }
        }
        tightest = std::max(tightest, radius);
        const double run = std::abs(GCPnts_AbscissaPoint::Length(adaptor, start, finish));
        const double step = std::pow(384 * 1e-8 * std::pow(tightest, 3), 0.25);
        count = std::clamp(int(std::ceil(run / step)) + 1, 9, 161);
    }
    std::vector<gp_Pnt> rows[4];
    for (int k = 0; k < count; ++k) {
        gp_Pnt centre = rings[0].centre;
        gp_Pnt ends[2] = {rings[0].ends[0], rings[0].ends[1]};
        if (k > 0) {
            centre = spine->Value(start + (finish - start) * k / (count - 1.0));
            bool rolls = true;
            for (int i = 0; i < 2 && rolls; ++i) {
                GeomAPI_ProjectPointOnSurf onSupport(centre, supports[i]);
                rolls = onSupport.NbPoints() > 0
                    && std::abs(onSupport.LowerDistance() - radius) < rolled;
                if (rolls) {
                    gp_Vec to(centre, onSupport.NearestPoint());
                    ends[i] = centre.Translated(to.Normalized() * radius);
                }
            }
            if (!rolls) {
                break;  // a support ends here: the continuation goes no further
            }
            gp_Vec toContact[2] = {gp_Vec(centre, ends[0]), gp_Vec(centre, ends[1])};
            gp_Vec axis = toContact[0].Crossed(toContact[1]);
            if (axis.Magnitude() < gp::Resolution()) {
                refuse("a blend's section past its end is not an arc");
            }
            for (int i = 0; i < 2; ++i) {
                ends[i] = centre.Translated(toContact[i].Rotated(gp_Ax1(centre, gp_Dir(axis)), overhang[i]));
            }
        }
        gp_Vec arms[2] = {gp_Vec(centre, ends[0]), gp_Vec(centre, ends[1])};
        const double turn = arms[0].Angle(arms[1]);
        if (turn < 1e-3 || turn > 2.9) {
            refuse("a blend's section past its end is not an arc under 166 degrees");
        }
        const double weight = std::cos(turn / 2);
        gp_Vec bisector = arms[0].Normalized() + arms[1].Normalized();
        gp_Pnt middle = centre.Translated(bisector.Normalized() * (arms[0].Magnitude() / weight));
        rows[0].push_back(ends[0]);
        rows[1].emplace_back(middle.XYZ() * weight);
        rows[2].push_back(ends[1]);
        rows[3].emplace_back(weight, double(k), 0.0);
    }
    const int stations = int(rows[0].size());
    if (stations < 9) {
        refuse("a blend's supports end where the blend does: it has no continuation");
    }
    // Through the sections' control points, in homogeneous coordinates for the middle row
    Handle(Geom_BSplineCurve) through[4];
    for (int row = 0; row < 4; ++row) {
        Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, stations);
        Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, stations);
        for (int k = 0; k < stations; ++k) {
            points->SetValue(k + 1, rows[row][k]);
            parameters->SetValue(k + 1, double(k));
        }
        try {
            GeomAPI_Interpolate interpolate(points, parameters, false, 1e-9);
            interpolate.Perform();
            if (interpolate.IsDone()) {
                through[row] = interpolate.Curve();
            }
        }
        catch (const Standard_Failure&) {
        }
        if (through[row].IsNull() || through[row]->NbPoles() != through[0]->NbPoles()
            || through[row]->NbKnots() != through[0]->NbKnots()) {
            refuse("interpolating a blend's continuation failed");
        }
    }
    const int poleCount = through[0]->NbPoles();
    TColgp_Array2OfPnt poles(1, 3, 1, poleCount);
    TColStd_Array2OfReal weights(1, 3, 1, poleCount);
    for (int j = 1; j <= poleCount; ++j) {
        const double weight = through[3]->Pole(j).X();
        if (weight < 0.05) {
            refuse("a blend's continuation has a section that is not an arc");
        }
        poles.SetValue(1, j, through[0]->Pole(j));
        poles.SetValue(2, j, gp_Pnt(through[1]->Pole(j).XYZ() / weight));
        poles.SetValue(3, j, through[2]->Pole(j));
        weights.SetValue(1, j, 1.0);
        weights.SetValue(2, j, weight);
        weights.SetValue(3, j, 1.0);
    }
    TColStd_Array1OfReal acrossKnots(1, 2);
    acrossKnots.SetValue(1, 0.0);
    acrossKnots.SetValue(2, 1.0);
    TColStd_Array1OfInteger acrossMults(1, 2);
    acrossMults.SetValue(1, 3);
    acrossMults.SetValue(2, 3);
    TColStd_Array1OfReal alongKnots(1, through[0]->NbKnots());
    through[0]->Knots(alongKnots);
    TColStd_Array1OfInteger alongMults(1, through[0]->NbKnots());
    through[0]->Multiplicities(alongMults);
    TopoDS_Face canal;
    try {
        Handle(Geom_BSplineSurface) surface = new Geom_BSplineSurface(
            poles,
            weights,
            acrossKnots,
            alongKnots,
            acrossMults,
            alongMults,
            2,
            through[0]->Degree()
        );
        BRepBuilderAPI_MakeFace make(surface, Precision::Confusion());
        if (make.IsDone()) {
            canal = make.Face();
        }
    }
    catch (const Standard_Failure&) {
    }
    if (canal.IsNull()) {
        refuse("building a blend's continuation failed");
    }
    found->beyond = TopoDS::Face(canal.Moved(location));
    ctx.blends[slot].beyond = found;
    return found;
}

/** The sheet of a wall's or an end face's surface: where the face is a rolling-ball blend, the surface
 * only up to the face's own bound along the blend (past it the canal surface continues it,
 * blendBeyond), else sheetOf
 */
TopoDS_Face sheetUpTo(
    const Handle(Geom_Surface)& surface,
    const TopLoc_Location& location,
    const TopoDS_Face& face,
    double reach,
    const std::optional<BlendBeyond>& blend
)
{
    if (!blend) {
        return sheetOf(surface, location, face, reach);
    }
    // An extended copy must still be the face's surface in the face's parameters
    {
        TopLoc_Location ownLocation;
        const Handle(Geom_Surface)& ownSurface = BRep_Tool::Surface(face, ownLocation);
        double u0 = 0.0;
        double u1 = 0.0;
        double v0 = 0.0;
        double v1 = 0.0;
        BRepTools::UVBounds(face, u0, u1, v0, v1);
        if (ownSurface->Value((u0 + u1) / 2, (v0 + v1) / 2)
                .Distance(surface->Value((u0 + u1) / 2, (v0 + v1) / 2))
            > linearTolerance) {
            refuse("a blend's extended surface is not the blend in its own parameters");
        }
    }
    double u0 = 0.0;
    double u1 = 0.0;
    double v0 = 0.0;
    double v1 = 0.0;
    surface->Bounds(u0, u1, v0, v1);
    (blend->alongV ? (blend->atUpper ? v1 : v0) : (blend->atUpper ? u1 : u0)) = blend->bound;
    BRepBuilderAPI_MakeFace make(surface, u0, u1, v0, v1, Precision::Confusion());
    if (!make.IsDone()) {
        refuse("a blend's surface up to its end can't be made a face");
    }
    return TopoDS::Face(make.Face().Moved(location));
}

/** A sheet and a blend's continuation past it as one splitting tool: sewn along the section they
 * share (the surface's own at the face's bound, and the canal's first), so that a cut that
 * crosses from one to the other closes. Apart, the two sections agree only to about 1e-7, and a cut
 * that runs a short way onto the continuation was left open
 */
TopoDS_Shape sheetWith(const TopoDS_Face& sheet, const TopoDS_Face& beyond)
{
    if (beyond.IsNull()) {
        return sheet;
    }
    BRepBuilderAPI_Sewing sewing(1e-6);
    sewing.Add(sheet);
    sewing.Add(beyond);
    sewing.Perform();
    const TopoDS_Shape sewn = sewing.SewedShape();
    int faces = 0;
    for (TopExp_Explorer it(sewn, TopAbs_FACE); it.More(); it.Next()) {
        ++faces;
    }
    if (sewn.IsNull() || sewn.ShapeType() != TopAbs_SHELL || faces != 2) {
        refuse("a blend's continuation does not join the blend's surface");
    }
    return sewn;
}

/** The end face's surface as a face reaching past the face (Case Base #105): the surface's natural
 * bounds where they are finite, else the face's own bounds run on by the reach. With extend, a
 * bounded surface is first extended by the reach (GeomLib::ExtendSurfByLength) on each side through
 * the vertex that is not closed and does not lie on one of the edge's faces (a blend's tangent line
 * on the face: run on past it, the surface would lie along the face); null when there is nothing to
 * extend
 */
TopoDS_Face surfaceFace(
    const Context& ctx,
    const TopoDS_Face& face,
    const TopoDS_Face (&faces)[2],
    const gp_Pnt& vertex,
    double reach,
    bool extend,
    Handle(Geom_Surface)& surface,
    TopLoc_Location& location,
    TopoDS_Face& beyond
)
{
    surface = BRep_Tool::Surface(face, location);
    if (surface.IsNull()) {
        refuse("an end face without a surface");
    }
    // A rolling-ball blend is continued past its end by the canal surface, at every level
    const std::optional<BlendBeyond> blend = blendBeyond(ctx, face, vertex, reach);
    beyond = blend ? blend->beyond : TopoDS_Face();
    if (extend) {
        Handle(Geom_BoundedSurface) bounded
            = Handle(Geom_BoundedSurface)::DownCast(surface->Copy());
        if (bounded.IsNull()) {
            return {};
        }
        // The edge's faces where the surface is: the end face's location applies to both
        TopoDS_Face here[2] = {
            TopoDS::Face(faces[0].Moved(location.Inverted())),
            TopoDS::Face(faces[1].Moved(location.Inverted()))
        };
        std::vector<std::pair<bool, bool>> sides;
        gp_Pnt at = vertex.Transformed(location.Inverted().Transformation());
        double u0 = 0.0;
        double u1 = 0.0;
        double v0 = 0.0;
        double v1 = 0.0;
        bounded->Bounds(u0, u1, v0, v1);
        for (bool inU : {true, false}) {
            if (inU ? bounded->IsUClosed() : bounded->IsVClosed()) {
                continue;
            }
            for (bool after : {false, true}) {
                // Only the sides through the vertex: past them the round runs on past the face. A
                // run on past any other side would reach along the tool, not across it
                Handle(Geom_Curve) iso = inU ? bounded->UIso(after ? u1 : u0)
                                             : bounded->VIso(after ? v1 : v0);
                GeomAPI_ProjectPointOnCurve onIso(at, iso);
                bool throughVertex = onIso.NbPoints() > 0 && onIso.LowerDistance() < 0.05 * reach;
                if (throughVertex && !sideOnFaces(bounded, inU, after, here)) {
                    sides.emplace_back(inU, after);
                }
            }
        }
        if (sides.empty()) {
            return {};
        }
        for (const auto& [inU, after] : sides) {
            GeomLib::ExtendSurfByLength(bounded, reach, 1, inU, after);
            if (bounded.IsNull()) {
                return {};
            }
        }
        surface = bounded;
    }
    return sheetUpTo(surface, location, face, reach, blend);
}

/** A wall's surface as a face reaching past the wall, under the strip's face (Case Base #105, a
 * round's strip that runs into a blend): the surface's natural bounds where they are finite, else
 * the wall's own bounds run on by the reach. With extend, a bounded surface is first extended by
 * the reach on each side that the wall's foot runs along (within a twentieth of the wall's own
 * parameter range): past the foot the surface must run on behind the face (the opposite of
 * surfaceFace's rule, which is for a surface that ends the tool across its edge). #105's blends
 * end 0 to 0.07 past their feet, less than the round is high there. With extend 2, also on each
 * side that an end of the foot lies on: #105's short blend ends where its foot does, 4e-4 inside
 * the R 1 arc's tool, which is 2.5e-4 high there, and the cut can't close. Null when there is
 * nothing to extend
 */
TopoDS_Face wallSheet(
    const Context& ctx,
    const TopoDS_Face& wall,
    const TopoDS_Edge& foot,
    double reach,
    int extend,
    Handle(Geom_Surface)& surface,
    TopLoc_Location& location,
    TopoDS_Face& beyond
)
{
    surface = BRep_Tool::Surface(wall, location);
    if (surface.IsNull()) {
        refuse("a wall without a surface");
    }
    // A rolling-ball blend is continued past its end nearest the foot by the canal surface
    std::optional<BlendBeyond> blend;
    {
        BRepAdaptor_Curve along(foot);
        blend = blendBeyond(
            ctx,
            wall,
            along.Value((along.FirstParameter() + along.LastParameter()) / 2),
            reach
        );
    }
    beyond = blend ? blend->beyond : TopoDS_Face();
    if (extend) {
        Handle(Geom_BoundedSurface) bounded
            = Handle(Geom_BoundedSurface)::DownCast(surface->Copy());
        if (bounded.IsNull()) {
            return {};
        }
        // The foot in the wall's parameters, and the wall's own range
        double fu0 = 0.0;
        double fu1 = 0.0;
        double fv0 = 0.0;
        double fv1 = 0.0;
        BRepTools::UVBounds(wall, fu0, fu1, fv0, fv1);
        BRepAdaptor_Curve curve(foot);
        std::vector<gp_Pnt2d> along;
        for (int k = 0; k <= 4; ++k) {
            gp_Pnt point = curve.Value(
                curve.FirstParameter() + (curve.LastParameter() - curve.FirstParameter()) * k / 4.0
            );
            point.Transform(location.Inverted().Transformation());
            GeomAPI_ProjectPointOnSurf projection(point, bounded);
            if (projection.NbPoints() == 0) {
                return {};
            }
            double u = 0.0;
            double v = 0.0;
            projection.LowerDistanceParameters(u, v);
            along.emplace_back(u, v);
        }
        std::vector<std::pair<bool, bool>> sides;
        for (bool inU : {true, false}) {
            if (inU ? bounded->IsUClosed() : bounded->IsVClosed()) {
                continue;
            }
            for (bool after : {false, true}) {
                const double bound = inU ? (after ? fu1 : fu0) : (after ? fv1 : fv0);
                const double range = inU ? fu1 - fu0 : fv1 - fv0;
                auto onSide = [&](const gp_Pnt2d& uv) {
                    return std::abs((inU ? uv.X() : uv.Y()) - bound) <= 0.05 * range;
                };
                if (std::all_of(along.begin(), along.end(), onSide)
                    || (extend > 1 && (onSide(along.front()) || onSide(along.back())))) {
                    sides.emplace_back(inU, after);
                }
            }
        }
        if (sides.empty()) {
            return {};
        }
        for (const auto& [inU, after] : sides) {
            GeomLib::ExtendSurfByLength(bounded, reach, 1, inU, after);
            if (bounded.IsNull()) {
                return {};
            }
        }
        surface = bounded;
    }
    return sheetUpTo(surface, location, wall, reach, blend);
}

/// The surface as a face: its natural bounds where finite, else the face's own run on by the reach
TopoDS_Face sheetOf(
    const Handle(Geom_Surface)& surface,
    const TopLoc_Location& location,
    const TopoDS_Face& face,
    double reach
)
{
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

/** A prism's end trimmed by the end face's surface, not its plane (Case Base #105). The prism's
 * part past its inner end (the edge's middle, or its other end) is split by the surface, run on past the face, and
 * the pieces that don't hold the prism beside the edge are cut from it. The prism must come out
 * closed there (its run on's end gone), and nothing may go at the inner end, where the surface
 * would cross the tool further in than the end's half. The parameters along the edge run from the
 * section's corner: inner, the split's inner end; outer, the prism's end. Returns the volume cut
 * away. Where the surface had to be extended, the tool's face on it is no cap: it can't merge into
 * the end face, and stays a face of the dress-up's (Onshape's end face grows instead: one face)
 */
double trimBySurface(
    const Context& ctx,
    TopoDS_Shape& solid,
    Tool& tool,
    const EdgeData& data,
    const TopoDS_Face& endFace,
    const Section& section,
    const gp_Dir& direction,
    double inner,
    double outer,
    const gp_Pnt& vertex,
    const TopoDS_Edge& continuation
)
{
    const double sign = outer > inner ? 1.0 : -1.0;
    const double span = std::abs(outer - inner);
    const double size = section.length[0] + section.length[1];
    gp_Dir towards = sign > 0 ? direction : direction.Reversed();
    TrimPlane innerEnd {section.corner.Translated(gp_Vec(direction) * inner), towards};
    // The prism past the inner end
    TopoDS_Shape endPart = commonOf(solid, halfSpaceBeyond(innerEnd, 4 * (span + size) + 4));
    // Inside the tool beside the edge, near the inner end; and at the run on's end
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
    for (bool extend : {false, true}) {
        Handle(Geom_Surface) surface;
        TopLoc_Location location;
        TopoDS_Face beyond;
        TopoDS_Face face = surfaceFace(
            ctx,
            endFace,
            data.faces,
            vertex,
            2 * size,
            extend,
            surface,
            location,
            beyond
        );
        if (face.IsNull()) {
            break;
        }
        TopTools_ListOfShape arguments;
        arguments.Append(endPart);
        TopTools_ListOfShape tools;
        tools.Append(sheetWith(face, beyond));
        BRepAlgoAPI_Splitter splitter;
        splitter.SetArguments(arguments);
        splitter.SetTools(tools);
        splitter.SetRunParallel(Standard_False);
        splitter.SetNonDestructive(Standard_True);
    splitter.SetNonDestructive(Standard_True);
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
        double removed = 0.0;
        bool closed = true;
        bool atInnerEnd = false;
        // The prism's end, past the run on: the kept piece must not reach it (review: a surface
        // that covers the corner line but not the whole section leaves a groove along the run on)
        TrimPlane outerEnd {section.corner.Translated(gp_Vec(direction) * outer), towards};
        for (const auto& piece : pieces) {
            if (holds(piece, kept)) {
                ++holding;
                closed = !holds(piece, runOn);
                for (TopExp_Explorer it(piece, TopAbs_FACE); it.More() && closed; it.Next()) {
                    closed = !inPlane(it.Current(), outerEnd);
                }
                continue;
            }
            builder.Add(away, piece);
            removed += volumeOf(piece);
            for (TopExp_Explorer it(piece, TopAbs_FACE); it.More(); it.Next()) {
                atInnerEnd = atInnerEnd || inPlane(it.Current(), innerEnd);
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
        if (atInnerEnd) {
            if (continuation.IsNull()) {
                refuse("the surface of an end face crosses its tool away from the end");
            }
            tool.passOn.push_back({face, endFace, continuation, innerEnd.point, !extend, beyond});
        }
        BRepAlgoAPI_Cut cut(solid, away);
        if (!cut.IsDone() || cut.HasErrors()) {
            refuse("trimming a tool by an end face's surface failed");
        }
        solid = cut.Shape();
        tool.surfaceEnds.push_back(endFace);
        if (!extend) {
            tool.capSurfaces.emplace_back(surface, location);
        }
        return removed;
    }
    refuse("the surface of an end face that is not a plane does not close its tool");
}

/** The tool of an edge that a curved end's surface reaches into across the vertex where the
 * edge continues the trimmed one (Tool::PassOn): split by the same surface, the pieces that don't
 * hold the tool beside the edge near its far end go. Nothing may go at the far end, and the tool's
 * volume must be what is left plus what went
 */
void trimContinuation(const Context& ctx, Tool& tool, const EdgeData& data, const Tool::PassOn& pass)
{
    if (data.closed) {
        refuse("the surface of an end face reaches a closed edge");
    }
    BRepAdaptor_Curve curve(data.edge);
    bool sharedAtFirst
        = pass.vertex.Distance(curve.Value(data.first)) < pass.vertex.Distance(curve.Value(data.last));
    double farAt = sharedAtFirst ? data.last : data.first;
    double sharedAt = sharedAtFirst ? data.first : data.last;
    // Inside the tool beside the edge, a hundredth of the edge from its far end
    Section section = sectionAt(ctx, data, farAt + 0.01 * (sharedAt - farAt));
    double offset = 0.05 * std::min(section.length[0], section.length[1]);
    gp_Pnt kept = section.corner.Translated(
        (gp_Vec(section.inward[0]) + gp_Vec(section.inward[1])) * offset
    );
    // The plane normal to the edge at its far end, the tool's end there for a line or an arc
    gp_Pnt farPoint;
    gp_Vec tangent;
    curve.D1(farAt, farPoint, tangent);
    if (tangent.Magnitude() < linearTolerance) {
        refuse("degenerate edge tangent");
    }
    gp_Dir outward(sharedAtFirst ? tangent : tangent.Reversed());
    TrimPlane farEnd {farPoint, outward};
    TopTools_ListOfShape arguments;
    arguments.Append(tool.solid);
    TopTools_ListOfShape tools;
    tools.Append(sheetWith(pass.face, pass.beyond));
    BRepAlgoAPI_Splitter splitter;
    splitter.SetArguments(arguments);
    splitter.SetTools(tools);
    splitter.SetRunParallel(Standard_False);
    splitter.SetNonDestructive(Standard_True);
    splitter.Build();
    if (!splitter.IsDone() || splitter.HasErrors()) {
        refuse("splitting by an end face's surface failed");
    }
    int holding = 0;
    int count = 0;
    double removed = 0.0;
    BRep_Builder builder;
    TopoDS_Compound away;
    builder.MakeCompound(away);
    for (TopExp_Explorer it(splitter.Shape(), TopAbs_SOLID); it.More(); it.Next()) {
        ++count;
        BRepClass3d_SolidClassifier classifier(it.Current(), kept, linearTolerance);
        if (classifier.State() == TopAbs_IN) {
            ++holding;
            continue;
        }
        builder.Add(away, it.Current());
        removed += volumeOf(it.Current());
        for (TopExp_Explorer face(it.Current(), TopAbs_FACE); face.More(); face.Next()) {
            if (inPlane(face.Current(), farEnd)) {
                refuse("the surface of an end face crosses a tangent edge's tool to its far end");
            }
        }
    }
    if (holding != 1) {
        refuse(
            "the surface of an end face leaves " + std::to_string(holding)
            + " pieces beside a tangent edge"
        );
    }
    if (count < 2) {
        // The surface passes the vertex only: the tool is not cut by it. A strip of it that runs off
        // into that end face is then a strip into a wall (checkRunOff; #105's R 1 arcs, 0.02 past
        // the blend's foot beside the vertex), and a touch at the vertex alone is passed there
        return;
    }
    tool.surfaceEnds.push_back(pass.endFace);
    BRepAlgoAPI_Cut cut(tool.solid, away);
    if (!cut.IsDone() || cut.HasErrors()) {
        refuse("trimming a tangent edge's tool by an end face's surface failed");
    }
    double measured = volumeOf(cut.Shape());
    // As its siblings (trimBySurface, trimByWall): what the split's raised tolerances can cost
    const double allowance = raisedTolerance(cut.Shape(), {}) * squareSize(cut.Shape());
    if (std::abs(measured + removed - tool.volume) > volumeTolerance * tool.volume + allowance) {
        refuse("a tangent edge's tool trimmed by an end face's surface: " + describe(measured)
               + " left and " + describe(removed) + " cut away of " + describe(tool.volume));
    }
    tool.solid = cut.Shape();
    tool.volume = measured;
    if (pass.cap) {
        TopLoc_Location location;
        const Handle(Geom_Surface)& surface = BRep_Tool::Surface(pass.face, location);
        tool.capSurfaces.emplace_back(surface, location);
    }
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
    // An end on a face that is not a plane is bounded by its surface, not its tangent plane
    // (trimBySurface): here it is the vertex, and the run on reaches past it
    auto beginAt = [&](const gp_Pnt& p) {
        if (!ends[0].surfaceEnd.IsNull()) {
            return 0.0;
        }
        double s = -std::numeric_limits<double>::infinity();
        for (const auto& plane : ends[0].trims) {
            s = std::max(s, crossing(plane, p, direction));
        }
        return s;
    };
    auto finishAt = [&](const gp_Pnt& p) {
        if (!ends[1].surfaceEnd.IsNull()) {
            return length;
        }
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
                ctx,
                solid,
                tool,
                data,
                ends[i].surfaceEnd,
                section,
                direction,
                // The split's inner end: the edge's middle when both ends are curved, else its
                // other end (a round cut off along most of a short edge, as #105's 0.74 line)
                ends[1 - i].surfaceEnd.IsNull() ? (i == 0 ? length : 0.0) : length / 2,
                i == 0 ? begin : finish,
                i == 0 ? data.start : data.end,
                ends[1 - i].surfaceEnd.IsNull() && ends[1 - i].kind == VertexClass::TangentContinuation
                    ? ends[1 - i].continuation
                    : TopoDS_Edge()
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
        // With what the split's own tolerances allow, as admit() and trimByWall() do: an end
        // surface tangent to the prism's side (a blend running out of it) splits it less sharply
        double allowance = raisedTolerance(solid, {}) * squareSize(solid);
        if (std::abs(measured + removed - prism) > volumeTolerance * prism + allowance) {
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

/** The tool cut back to the material's side of the surface of the face beyond an overflowing end
 * (VertexClass::Overflow), near the vertex at point; size bounds the tool around it. A plane cuts by
 * its half-space; a cone by a solid bounded by the face's own surface, between two planes normal to
 * its axis, so that the tool's faces there lie on that surface and merge into the face.
 */
TopoDS_Shape trimBeyond(
    const TopoDS_Shape& tool,
    const TopoDS_Face& beyond,
    const gp_Pnt& point,
    double size,
    double radius
)
{
    gp_Dir outward = outwardNormal(beyond, point);
    BRepAdaptor_Surface surface(beyond, Standard_False);
    if (surface.GetType() == GeomAbs_Plane) {
        BRepAlgoAPI_Cut cut(tool, halfSpaceBeyond({point, outward}, size));
        if (!cut.IsDone() || cut.HasErrors()) {
            refuse("trimming an overflowing tool by the face beyond failed");
        }
        return cut.Shape();
    }
    if (surface.GetType() != GeomAbs_Cone) {
        refuse("the face beyond an overflowing end is neither a plane nor a cone");
    }
    gp_Cone cone = surface.Cone();
    double u = 0.0;
    double v = 0.0;
    ElSLib::Parameters(cone, point, u, v);
    double sine = std::sin(cone.SemiAngle());
    if (std::abs(sine) < 1e-6) {
        refuse("a degenerate cone beyond an overflowing end");
    }
    // Along the generatrix, size either way of the vertex, short of the apex
    double apex = -cone.RefRadius() / sine;
    double low = v - size;
    double high = v + size;
    if (apex > low && apex < high) {
        if (std::abs(v - apex) < 2 * size / 3) {
            refuse("the apex of the cone beyond an overflowing end is too near it");
        }
        (apex < v ? low : high) = (v + apex) / 2;
    }
    TopLoc_Location location;
    Handle(Geom_Surface) geometry = BRep_Tool::Surface(beyond, location);
    BRepBuilderAPI_MakeFace lateral(geometry, 0.0, 2 * pi, low, high, Precision::Confusion());
    if (!lateral.IsDone()) {
        refuse("building the cone beyond an overflowing end failed");
    }
    BRepBuilderAPI_Sewing sewing(Precision::Confusion());
    sewing.Add(lateral.Face());
    for (TopExp_Explorer it(lateral.Face(), TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        if (BRep_Tool::IsClosed(edge, lateral.Face())) {
            continue;  // the seam
        }
        BRepBuilderAPI_MakeFace cap(BRepBuilderAPI_MakeWire(edge).Wire(), Standard_True);
        if (!cap.IsDone()) {
            refuse("capping the cone beyond an overflowing end failed");
        }
        sewing.Add(cap.Face());
    }
    sewing.Perform();
    TopExp_Explorer shells(sewing.SewedShape(), TopAbs_SHELL);
    if (!shells.More()) {
        refuse("closing the cone beyond an overflowing end failed");
    }
    BRepBuilderAPI_MakeSolid makeSolid(TopoDS::Shell(shells.Current()));
    if (!makeSolid.IsDone()) {
        refuse("closing the cone beyond an overflowing end failed");
    }
    TopoDS_Solid solid = makeSolid.Solid();
    BRepLib::OrientClosedSolid(solid);
    TopoDS_Shape trim = solid.Moved(location);
    if (volumeOf(trim) <= 0.0 || !BRepCheck_Analyzer(trim).IsValid()) {
        refuse("the cone beyond an overflowing end is not a valid solid");
    }
    // The material lies opposite the face's outward normal
    BRepClass3d_SolidClassifier side(
        trim,
        point.Translated(gp_Vec(outward) * (-0.01 * radius)),
        linearTolerance
    );
    if (side.State() == TopAbs_IN) {
        BRepAlgoAPI_Common common(tool, trim);
        if (!common.IsDone() || common.HasErrors()) {
            refuse("trimming an overflowing tool by the cone beyond failed");
        }
        return common.Shape();
    }
    if (side.State() != TopAbs_OUT) {
        refuse("the material's side of the cone beyond an overflowing end is unclear");
    }
    BRepAlgoAPI_Cut cut(tool, trim);
    if (!cut.IsDone() || cut.HasErrors()) {
        refuse("trimming an overflowing tool by the cone beyond failed");
    }
    return cut.Shape();
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
    // An overflowing end (VertexClass::Overflow) turns the tool on a quarter turn past its vertex,
    // into the material behind the wall its cylinder carries on into
    const double pre = !data.closed && ends[0].kind == VertexClass::Overflow ? pi / 2 : 0.0;
    const double post = !data.closed && ends[1].kind == VertexClass::Overflow ? pi / 2 : 0.0;
    // Run on past reflex corners (Corner2Reflex): the section is taken that much before the first
    // end (on the circle run on: a moved copy of the section would revolve into a surface of
    // revolution, not a torus), and the revolution is that much longer; a whole turn is a ring
    double runBefore = 0.0;
    double runAfter = 0.0;
    if (!data.closed) {
        runBefore = ends[0].kind == VertexClass::Corner2Reflex ? ends[0].runOn : 0.0;
        runAfter = ends[1].kind == VertexClass::Corner2Reflex ? ends[1].runOn : 0.0;
    }
    double turn = span + pre + post + runBefore + runAfter;
    if (pre + post > 0.0 && turn > 2 * pi - angularTolerance) {
        refuse("an arc that runs on past its ends would turn into itself");
    }
    if (pre + post > 0.0 && runBefore + runAfter > 0.0) {
        refuse("an arc with an overflowing end and a reflex corner");
    }
    if (turn > 2 * pi - angularTolerance) {
        turn = 2 * pi;
    }
    gp_Trsf startTurn;
    startTurn.SetRotation(axis, -pre);
    const TopLoc_Location atStart(startTurn);
    for (int i = 0; i < 2 && !data.closed; ++i) {
        if (ends[i].kind == VertexClass::Corner2Reflex) {
            continue;
        }
        if (!ends[i].surfaceEnd.IsNull()) {
            refuse("an arc that ends on a face that is not a plane");
        }
        const TrimPlane& plane = ends[i].trims.front();
        if (std::abs(plane.normal.Dot(z)) > angularTolerance
            || gp_Pln(plane.point, plane.normal).Distance(circle.Location()) > linearTolerance) {
            refuse("the plane at the end of an arc does not contain its axis");
        }
    }
    Section section = sectionAt(ctx, data, data.first - runBefore);
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
    tool.volume = section.area * centroidRadius * turn;
    tool.strips.resize(2);
    for (int k = 0; k < 2; ++k) {
        tool.strips[k].face = data.faces[k];
        tool.strips[k].width = section.length[k];
        tool.strips[k].farSide = circleAbout(axis, section.ends[k]);
    }
    TopoDS_Shape solid;
    if (!section.fillet) {
        solid = BRepPrimAPI_MakeRevol(section.face().Moved(atStart), axis, turn, Standard_True)
                    .Shape();
    }
    else {
        // The square corner, end, centre, end revolved, minus the torus (or sphere) about the
        // centre's circle: the round face is analytic (a spindle or horn torus: the section
        // revolved instead, below). Its seam is where the circle's is on a closed edge, and
        // opposite the middle of the tool's turn on an open one: an arc across the seam would get
        // its round in two faces, and OCCT 8.0.1's cut of Case Base #105's body by such a tool (an
        // R 1 arc rounded at r 1: a sphere) leaves an invalid face, where the same tool on the
        // three mirrored arcs, off the seam, cuts cleanly
        BRepBuilderAPI_MakePolygon square(
            section.corner,
            section.ends[0],
            section.centre,
            section.ends[1],
            Standard_True
        );
        TopoDS_Face face = BRepBuilderAPI_MakeFace(square.Wire(), Standard_True).Face();
        TopoDS_Shape ring
            = BRepPrimAPI_MakeRevol(face.Moved(atStart), axis, turn, Standard_True).Shape();
        double major = gp_Vec(circle.Location(), section.centre).Dot(gp_Vec(radial));
        gp_Pnt axisPoint = circle.Location().Translated(
            gp_Vec(z) * gp_Vec(circle.Location(), section.centre).Dot(gp_Vec(z))
        );
        // The middle is the turn's, not the arc's: a tool turned on past its ends (Nest Cover
        // #151) would have the seam opposite the arc's middle inside its turn (its face in two
        // pieces). The turn is short of a whole one (above), so the seam is outside it
        gp_Dir seam = circle.XAxis().Direction();
        if (!data.closed) {
            seam.Rotate(axis, (data.first - pre + data.last + post) / 2 + pi);
        }
        gp_Ax2 frame(axisPoint, z, seam);
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
            // volume is the closed form's (Pappus), and OCCT stores a spindle's round as a surface
            // of revolution rather than a torus.
            // A horn torus (major = minor) it stores as either, by the last digit of major as it
            // comes out at the tool's place: a torus where major is above the radius, a surface of
            // revolution where not (two teeth of one wheel differed), and its Booleans are wrong on
            // the latter at a reflex corner (the fuse of two such tools gained 3e-3 of volume). So
            // a horn's section is stepped out, by the last digit, until the round is a torus
            const bool horn = major > section.radius - linearTolerance;
            auto isTorus = [](const TopoDS_Shape& shape) {
                for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
                    if (BRepAdaptor_Surface(TopoDS::Face(it.Current()), Standard_False).GetType()
                        == GeomAbs_Torus) {
                        return true;
                    }
                }
                return false;
            };
            const double step = 4 * std::numeric_limits<double>::epsilon()
                * (gp_Vec(gp::Origin(), section.centre).Magnitude() + section.radius);
            for (int k = 0; k < (horn ? 64 : 1); ++k) {
                Section revolved = section;
                if (k > 0) {
                    revolved = makeSection(
                        section.corner.Translated(gp_Vec(radial) * (k * step)),
                        section.inward[0],
                        section.inward[1],
                        ctx.request
                    );
                }
                TopoDS_Shape start = revolved.face();
                if (pre > 0.0) {
                    start.Move(atStart);
                }
                solid = BRepPrimAPI_MakeRevol(start, axis, turn, Standard_True).Shape();
                if (!horn || isTorus(solid)) {
                    break;
                }
            }
        }
        else {
            round = BRepPrimAPI_MakeTorus(frame, major, section.radius).Shape();
        }
        if (solid.IsNull()) {
            // The section itself revolved, as for a spindle: OCCT's sweep stores the round as a
            // torus, or as a sphere where the centre is on the axis, with no seam inside the turn
            // and no Boolean. The cut of the ring by a sphere returned the ring whole, without an
            // error, where the arc's radius was the round's plus 7e-15 (Case Base #105 on the
            // fork's own #104: the helper square's corner that far off the axis); so a sphere's
            // section is set on the axis first. Taken only if the round came out as that surface
            // and the volume is the closed form's; the cut stays the fallback
            const bool sphere = std::abs(major) <= linearTolerance;
            const GeomAbs_SurfaceType kind = sphere ? GeomAbs_Sphere : GeomAbs_Torus;
            try {
                Section revolved = section;
                if (sphere && major != 0.0) {
                    revolved = makeSection(
                        section.corner.Translated(gp_Vec(radial) * (-major)),
                        section.inward[0],
                        section.inward[1],
                        ctx.request
                    );
                }
                TopoDS_Shape direct
                    = BRepPrimAPI_MakeRevol(revolved.face().Moved(atStart), axis, turn, Standard_True)
                          .Shape();
                bool analytic = false;
                for (TopExp_Explorer it(direct, TopAbs_FACE); it.More(); it.Next()) {
                    analytic = analytic
                        || BRepAdaptor_Surface(TopoDS::Face(it.Current()), Standard_False).GetType()
                            == kind;
                }
                if (analytic && direct.ShapeType() == TopAbs_SOLID
                    && std::abs(volumeOf(direct) - tool.volume) <= volumeTolerance * tool.volume
                    && BRepCheck_Analyzer(direct).IsValid()) {
                    solid = direct;
                }
            }
            catch (const Standard_Failure&) {
                solid.Nullify();
            }
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
    if (pre + post > 0.0) {
        // Checked against its closed form before the trim, then measured: the trim by the face
        // beyond has none
        double measured = volumeOf(solid);
        if (std::abs(measured - tool.volume) > volumeTolerance * tool.volume) {
            refuse("an overflowing tool's volume " + describe(measured)
                   + " differs from its closed form " + describe(tool.volume));
        }
        if (!section.fillet) {
            refuse("an overflowing end of a chamfer");
        }
        BRepClass3d_SolidClassifier inBase(ctx.base.getShape());
        // A point inside the section (a quarter of the way from the square corner to the
        // round's centre), at each overflowing end of the turn: buried in the material
        gp_Pnt inSection = section.corner.Translated(gp_Vec(section.corner, section.centre) * 0.25);
        double size = 4 * (circle.Radius() + 2 * section.radius);
        for (int i = 0; i < 2; ++i) {
            if (ends[i].kind != VertexClass::Overflow) {
                continue;
            }
            gp_Trsf toEnd;
            toEnd.SetRotation(axis, i == 0 ? -pre : span + post);
            inBase.Perform(inSection.Transformed(toEnd), linearTolerance);
            if (inBase.State() != TopAbs_IN) {
                refuse("an end round past its vertex does not run on into the material");
            }
            tool.solid = trimBeyond(
                tool.solid,
                ends[i].beyond,
                ends[i].trims.front().point,
                size,
                section.radius
            );
            tool.overflowFaces.push_back(ends[i].beyond);
        }
        if (countSolids(tool.solid) != 1) {
            refuse("an overflowing tool trimmed by the face beyond is not one solid");
        }
        tool.solid = TopExp_Explorer(tool.solid, TopAbs_SOLID).Current();
        tool.volume = volumeOf(tool.solid);
    }
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
    // The patch spans the arc through the short-way bisector of its two ends' normals: past a half
    // circle (a keyhole's lobe) it would land on the other side, in the material (review)
    if (std::abs(data.last - data.first) >= pi - 1e-9) {
        refuse("a wall arc tighter than the round spanning a half circle or more");
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
    // Until the measured stage replaces it: the overlap tolerances of the inclusion and exclusion
    // past the limit scale with it (review)
    tool.volume = volumeOf(solid);
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
 * (wallAlongNormal), listing the wall in walls for the caller's trim (clipTool). Any other wall
 * (a plane that leans, a blend: Case Base #105, a round's strip on the underside running into
 * #103's blend, which rises from it at 87 degrees) is listed in surfaceWalls with its foot, the
 * edge the strip runs off over: the caller trims the tool by the wall's own surface (trimByWall).
 * Onto a face that is neither a plane nor a cylinder and is no wall, it refuses.
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
    const std::vector<TopoDS_Face>& surfaceEnds,
    std::vector<TopoDS_Face>& walls,
    std::vector<std::pair<TopoDS_Face, TopoDS_Edge>>& surfaceWalls
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
        bool trimmedBy = std::any_of(surfaceEnds.begin(), surfaceEnds.end(), [&](const TopoDS_Face& f) {
            return f.IsSame(next);
        });
        if (trimmedBy) {
            continue;  // onto a curved end face, whose surface trims the tool (Case Base #105)
        }
        BRepAdaptor_Surface nextSurface(next, Standard_False);
        // The surfaces outwardNormal knows: a cone too (Nest Cover #151's chamfer cone)
        const bool known = nextSurface.GetType() == GeomAbs_Plane
            || nextSurface.GetType() == GeomAbs_Cylinder || nextSurface.GetType() == GeomAbs_Cone;
        if (!known && lengthAlong(edge, off) <= 1000 * linearTolerance) {
            continue;  // a touch at a vertex, where a curved end face meets the strip's face (#105)
        }
        BRepAdaptor_Curve curve(edge);
        double middle = (curve.FirstParameter() + curve.LastParameter()) / 2;
        gp_Dir away = inwardInAny(next, edge, middle);
        if (away.Dot(outwardNormal(face, curve.Value(middle))) > -1e-6) {
            if (!wallAlongNormal(face, next)) {
                if (std::none_of(surfaceWalls.begin(), surfaceWalls.end(), [&](const auto& wall) {
                        return wall.first.IsSame(next) && wall.second.IsSame(edge);
                    })) {
                    surfaceWalls.emplace_back(next, edge);
                }
            }
            else if (std::none_of(walls.begin(), walls.end(), [&](const TopoDS_Face& wall) {
                         return wall.IsSame(next);
                     })) {
                walls.push_back(next);
            }
        }
        else if (!known) {
            // As before the walls' surfaces were read: only planes, cylinders and cones are known
            // here (outwardNormal's refusal)
            refuse("a face next to a selected edge is neither a plane nor a cylinder");
        }
        // Along more than the tolerance of a grazing contact, by a margin
        if (!pastUnselected && !selected.Contains(edge)
            && lengthAlong(edge, off) > 1000 * linearTolerance) {
            pastUnselected = true;
        }
    }
    return pastUnselected;
}

/// A cut tool's strip on the face that runs off over the foot into a wall whose own surface trims
/// the tool (checkRunOff's surfaceWalls)
struct SurfaceWall
{
    const Tool* tool = nullptr;
    TopoDS_Face face;
    TopoDS_Face wall;
    TopoDS_Edge foot;
};

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
 * the tools there by the walls' surfaces (clipTool). A wall that does not run straight back is
 * listed in surfaceWalls with its tool: the caller trims that tool by the wall's own surface
 * (trimByWall).
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
    std::vector<FusedRun>& fusedRuns,
    std::vector<SurfaceWall>& surfaceWalls
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
                if (group.owners[k]->relTolerance > volumeTolerance) {
                    // A tool cut by a reflex corner's mitre: its contact ends on a conic, and OCCT
                    // measures it and its part in the face 2e-6 of the area apart (a 2-tooth
                    // wheel: 0.663398705 and 0.663397377), which is not a strip off its face
                    tolerance = std::max(tolerance, 1e-5 * area);
                }
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
                        std::vector<std::pair<TopoDS_Face, TopoDS_Edge>> leaning;
                        if (checkRunOff(
                                group.face,
                                contact,
                                group.owners[k]->source,
                                edgeFaces,
                                selected,
                                group.owners[k]->surfaceEnds,
                                walls,
                                leaning
                            )
                            && std::find(pastLoop.begin(), pastLoop.end(), strip)
                                == pastLoop.end()) {
                            pastLoop.push_back(strip);
                        }
                        for (const auto& [wall, foot] : leaning) {
                            const Tool* owner = group.owners[k];
                            if (std::none_of(
                                    surfaceWalls.begin(),
                                    surfaceWalls.end(),
                                    [&](const SurfaceWall& known) {
                                        return known.tool == owner && known.face.IsSame(group.face)
                                            && known.wall.IsSame(wall) && known.foot.IsSame(foot);
                                    }
                                )) {
                                surfaceWalls.push_back({owner, group.face, wall, foot});
                            }
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
        // An overflowing end's strips run off both faces past its vertex, into the material
        if (!onAFace && tool.overflowFaces.empty()) {
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

/** A cut tool trimmed by a wall that does not run straight back from its strip's face (Case Base
 * #105: a round's strip on the underside runs off over a concave edge into #103's blend). Onshape
 * cuts the round off by the wall there, as by a wall straight back (Q-LEDGE): the wall's face
 * grows under the dress-up. The tool is split by the wall's surface, run on behind the face past
 * the wall's foot (wallSheet), and keeps the piece that holds its edge at the edge's middle. Each piece that goes
 * must lie behind the wall: it holds part of the strip that ran off the face, and none of the
 * strip on the face (but for what the foot's own tolerance leaves undecided). What is left must
 * no longer run off over the wall's foot, and with what went it must make up the tool's volume.
 * Else it refuses. It also refuses (review r1) where a piece that goes holds part of the tool's
 * other strip (a steep wall that cuts the whole round or chamfer away and narrows the other face's
 * strip: no oracle says what Onshape builds), or runs along the foot of another wall on another
 * surface (otherFeet: the first wall's surface would cut the dress-up off in front of the second).
 *
 * The kept piece is found by its boundary, not by a point inside it: on #105 the piece that goes
 * is a sliver 3e-4 thick (the round is tangent to the face where the wall cuts it), and OCCT's
 * solid classifier takes a point 0.9 away from it for inside it.
 *
 * Returns whether the tool's face on the wall's surface can merge into the wall: it lies on the
 * wall's own surface (listed in the tool's capSurfaces), not on an extension of it, where it
 * stays a face of the dress-up's
 */
bool trimByWall(
    const Context& ctx,
    Tool& tool,
    const EdgeData& data,
    const SurfaceWall& at,
    const std::vector<TopoDS_Edge>& otherFeet
)
{
    const auto strip = std::find_if(tool.strips.begin(), tool.strips.end(), [&](const Strip& s) {
        return s.face.IsSame(at.face);
    });
    if (strip == tool.strips.end()) {
        refuse("a tool has no strip on the face it runs off into a wall");
    }
    // On the tool's edge, at the selected edge's middle
    const gp_Pnt beside = sectionAt(ctx, data, (data.first + data.last) / 2).corner;
    const TopoDS_Vertex onEdge = BRepBuilderAPI_MakeVertex(beside);
    auto holds = [&](const TopoDS_Shape& piece) {
        for (TopExp_Explorer it(piece, TopAbs_SHELL); it.More(); it.Next()) {
            if (touch(onEdge, it.Current())) {
                return true;
            }
        }
        return false;
    };
    // The face's boundary at the foot is known only to the foot's tolerance
    double footTolerance = BRep_Tool::Tolerance(at.foot);
    for (TopExp_Explorer it(at.foot, TopAbs_VERTEX); it.More(); it.Next()) {
        footTolerance = std::max(footTolerance, BRep_Tool::Tolerance(TopoDS::Vertex(it.Current())));
    }
    const double undecided = 2 * footTolerance * perimeterOf(at.foot);
    // Whether a face of the strip runs off its face over the wall's foot, along a stretch of it
    auto pastFoot = [&](const TopoDS_Shape& contact) {
        BRepAlgoAPI_Cut outside(contact, at.face);
        if (!outside.IsDone() || outside.HasErrors()) {
            refuse("finding where a tangent strip runs off its face failed");
        }
        const TopoDS_Shape off = outside.Shape();
        // A part off the face is behind this wall where the foot bounds it along a stretch that
        // counts against its own size. Case Base #105 natively: an R 1 arc's strip is off its
        // face by 0.018 behind the short blend, and the long blend's foot, which ends 4e-4 inside
        // that tool, bounds that part along 4e-4. The long blend's surface is no wall there (run
        // on, it crosses the face in front of the short blend); a STEP's foot, with a tolerance
        // of 4e-3, hid it
        for (TopExp_Explorer it(off, TopAbs_FACE); it.More(); it.Next()) {
            const TopoDS_Shape& part = it.Current();
            if (touch(at.foot, part)
                && lengthAlong(at.foot, part)
                    > std::max(1000 * linearTolerance, 0.02 * std::sqrt(areaOf(part)))) {
                return true;
            }
        }
        return false;
    };
    if (std::none_of(strip->contacts.begin(), strip->contacts.end(), pastFoot)) {
        // Nothing runs past this foot along a stretch: the strip only touches it, or the same
        // surface cut the tool off here already (one wall with two feet, two walls on one surface)
        return false;
    }
    Bnd_Box box;
    BRepBndLib::Add(tool.solid, box);
    const double reach = 2 * std::sqrt(box.SquareExtent());
    const double before = tool.volume;
    for (int extend : {0, 1, 2}) {
        Handle(Geom_Surface) surface;
        TopLoc_Location location;
        TopoDS_Face beyond;
        TopoDS_Face sheet
            = wallSheet(ctx, at.wall, at.foot, reach, extend, surface, location, beyond);
        if (sheet.IsNull()) {
            break;
        }
        TopTools_ListOfShape arguments;
        arguments.Append(tool.solid);
        TopTools_ListOfShape tools;
        tools.Append(sheetWith(sheet, beyond));
        BRepAlgoAPI_Splitter splitter;
        splitter.SetArguments(arguments);
        splitter.SetTools(tools);
        splitter.SetRunParallel(Standard_False);
        splitter.SetNonDestructive(Standard_True);
        splitter.Build();
        if (!splitter.IsDone() || splitter.HasErrors()) {
            refuse("splitting a tool by a wall's surface failed");
        }
        std::vector<TopoDS_Shape> pieces;
        for (TopExp_Explorer it(splitter.Shape(), TopAbs_SOLID); it.More(); it.Next()) {
            pieces.push_back(it.Current());
        }
        if (pieces.size() < 2) {
            continue;  // the surface ends at the wall's foot: extended behind the face
        }
        const Stage stage(splitter.History(), splitter.Shape());
        // The strip's part in a piece: its area on the face, and off it
        auto stripIn = [&](const TopoDS_Shape& piece, double& on, double& off, double& tolerance) {
            TopTools_IndexedMapOfShape faces;
            TopExp::MapShapes(piece, TopAbs_FACE, faces);
            for (const auto& contact : strip->contacts) {
                for (const auto& image : stage.images(contact)) {
                    if (!faces.Contains(image)) {
                        continue;
                    }
                    double area = areaOf(image);
                    double inside = areaOf(commonOf(at.face, image));
                    on += inside;
                    off += area - inside;
                    tolerance += areaToleranceOf(image, *strip);
                }
            }
        };
        int holding = 0;
        TopoDS_Shape kept;
        BRep_Builder builder;
        TopoDS_Compound away;
        builder.MakeCompound(away);
        double removed = 0.0;
        for (const auto& piece : pieces) {
            if (holds(piece)) {
                ++holding;
                kept = piece;
                continue;
            }
            double on = 0.0;
            double off = 0.0;
            double tolerance = 0.0;
            stripIn(piece, on, off, tolerance);
            if (on > tolerance + undecided) {
                refuse("a wall's surface cuts a dress-up off on its own face");
            }
            if (off <= tolerance) {
                refuse("a wall's surface cuts a piece off a dress-up that is not behind the wall");
            }
            // Nothing of the tool's other strips: the wall would cut the dress-up's own face away
            {
                TopTools_IndexedMapOfShape faces;
                TopExp::MapShapes(piece, TopAbs_FACE, faces);
                for (const auto& other : tool.strips) {
                    if (&other == &*strip) {
                        continue;
                    }
                    for (const auto& contact : other.contacts) {
                        for (const auto& image : stage.images(contact)) {
                            if (faces.Contains(image)
                                && areaOf(image) > areaToleranceOf(image, other)) {
                                refuse("a wall's surface cuts a dress-up off on its other face");
                            }
                        }
                    }
                }
            }
            // Nor in front of another wall: its own surface cuts the dress-up off there
            // Along a stretch that counts against the piece's own size, as in pastFoot: #105's
            // piece behind the short blend touches the long blend's foot along 4e-4
            const double stretch
                = std::max(1000 * linearTolerance, 0.02 * std::cbrt(volumeOf(piece)));
            for (const auto& foot : otherFeet) {
                for (TopExp_Explorer it(piece, TopAbs_SHELL); it.More(); it.Next()) {
                    if (touch(foot, it.Current()) && lengthAlong(foot, it.Current()) > stretch) {
                        refuse("a wall's surface cuts a dress-up off in front of another wall");
                    }
                }
            }
            builder.Add(away, piece);
            removed += volumeOf(piece);
        }
        if (holding != 1) {
            refuse(
                "a wall's surface leaves " + std::to_string(holding)
                + " pieces of a dress-up on its edge"
            );
        }
        // What is left no longer runs off over the wall's foot
        bool stillPast = false;
        {
            TopTools_IndexedMapOfShape faces;
            TopExp::MapShapes(kept, TopAbs_FACE, faces);
            for (const auto& contact : strip->contacts) {
                for (const auto& image : stage.images(contact)) {
                    stillPast = stillPast || (faces.Contains(image) && pastFoot(image));
                }
            }
        }
        if (stillPast) {
            if (extend < 2) {
                continue;  // the surface ends before the strip does: extended
            }
            refuse("a wall's surface leaves a dress-up's strip past the wall's foot");
        }
        clipTool(tool, away);
        double allowance = raisedTolerance(tool.solid, {}) * squareSize(tool.solid);
        if (std::abs(tool.volume + removed - before) > volumeTolerance * before + allowance) {
            refuse("a dress-up trimmed by a wall's surface: " + describe(tool.volume) + " left and "
                   + describe(removed) + " cut away of " + describe(before));
        }
        if (extend == 0) {
            tool.capSurfaces.emplace_back(surface, location);
        }
        return extend == 0;
    }
    refuse("a wall's surface does not cut off the dress-up that runs into it");
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
        // Each tool to its own tolerance: the closed forms', or a reflex corner's quadrature's
        scale += tool->relTolerance * tool->volume;
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
    double bound = scale + raised * size + expectedAllowance;
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
/* Reflex corners with a circle (VertexClass::Corner2Reflex; fillet-tight-arc 8, FSLC #50).
 *
 * Near a vertex where two convex rims meet and the outline is reflex, the material is M1 u M2,
 * M_i the material side of wall i run on past the vertex, and Onshape's result is
 * (M1 - T1) u (M2 - T2), T_i the round's tool along wall i run on: each round runs on past the
 * vertex, and where both reach the higher one is kept. With one radius that is the round of the
 * wall the point lies deeper behind, so each edge's tool runs on (prepareReflexEnd) and is cut by
 * the mitre: the vertical cylinder over the walls' bisector (mitreRegions), of which it keeps the
 * side where its own wall is the deeper one. The cut tools have no closed form: their volumes are
 * quadratures over the round's section of path lengths (sweptInside), checked against the solids
 * OCCT builds.
 */

/// A tool as a sweep of its section, for the quadratures
struct Sweep
{
    bool line = true;
    gp_Ax2 frame;     // circle: Z the axis, X towards the start section's corner
    double total = 0.0;  // circle: the angle of the revolution
    gp_Dir direction;    // line
    std::vector<TrimPlane> begin;  // line: the planes at its start and at its end
    std::vector<TrimPlane> finish;
    gp_Pnt corner;  // the section where the sweep starts
    gp_Dir in0;
    gp_Dir in1;
    double r = 0.0;

    bool closed() const
    {
        return !line && total >= 2 * pi - angularTolerance;
    }
    /// Where the path of the section's point X0 runs: [from, to], and the length per parameter
    void range(const gp_Pnt& x0, double& from, double& to, double& speed) const
    {
        if (line) {
            from = -std::numeric_limits<double>::infinity();
            to = std::numeric_limits<double>::infinity();
            for (const auto& plane : begin) {
                from = std::max(from, crossing(plane, x0, direction));
            }
            for (const auto& plane : finish) {
                to = std::min(to, crossing(plane, x0, direction));
            }
            speed = 1.0;
            return;
        }
        from = 0.0;
        to = total;
        gp_Vec w(frame.Location(), x0);
        speed = (w - gp_Vec(frame.Direction()) * w.Dot(gp_Vec(frame.Direction()))).Magnitude();
    }
    gp_Pnt at(const gp_Pnt& x0, double t) const
    {
        if (line) {
            return x0.Translated(gp_Vec(direction) * t);
        }
        gp_Vec w(frame.Location(), x0);
        double z = w.Dot(gp_Vec(frame.Direction()));
        double x = w.Dot(gp_Vec(frame.XDirection()));
        double y = w.Dot(gp_Vec(frame.YDirection()));
        double c = std::cos(t);
        double s = std::sin(t);
        return frame.Location().Translated(
            gp_Vec(frame.Direction()) * z + gp_Vec(frame.XDirection()) * (x * c - y * s)
            + gp_Vec(frame.YDirection()) * (x * s + y * c)
        );
    }
    /// The section's point (u along in0, v along in1 from the corner)
    gp_Pnt node(double u, double v) const
    {
        return corner.Translated(gp_Vec(in0) * u + gp_Vec(in1) * v);
    }
};

/// The vertex at an end of a selected edge (slot 0: at its first parameter)
TopoDS_Vertex vertexAt(const EdgeData& data, int slot)
{
    TopoDS_Vertex vertices[2];
    TopExp::Vertices(data.edge, vertices[0], vertices[1]);
    const gp_Pnt& at = slot == 0 ? data.start : data.end;
    return BRep_Tool::Pnt(vertices[0]).Distance(at) <= BRep_Tool::Pnt(vertices[1]).Distance(at)
        ? vertices[0]
        : vertices[1];
}

const EdgeData& edgeDataOf(const std::vector<EdgeData>& all, const TopoDS_Shape& edge)
{
    auto it = std::find_if(all.begin(), all.end(), [&](const EdgeData& d) {
        return d.edge.IsSame(edge);
    });
    if (it == all.end()) {
        refuse("a reflex corner's edge that was not analysed");
    }
    return *it;
}

/// The plane face the two edges at a reflex corner share
TopoDS_Face sharedFace(const EdgeData& a, const EdgeData& b)
{
    for (const auto& mine : a.faces) {
        for (const auto& theirs : b.faces) {
            if (mine.IsSame(theirs)) {
                return mine;
            }
        }
    }
    refuse("a reflex corner whose edges share no face");
    return {};
}

/** How far a tool runs on past a reflex corner: an angle for a circle, a length for a line. Up to
 * the middle of the stretch its edge's curve spends inside the other wall's material side (the
 * mirror plane of that stretch: beyond it lies the mirror image of this corner, another corner's
 * or none), and no further than a few radii
 */
double runOnOf(
    const Context& ctx,
    const std::vector<EdgeData>& /*all*/,
    const EdgeData& data,
    const TopoDS_Vertex& vertex,
    const EdgeData& other
)
{
    double r = ctx.request.size1;
    gp_Pnt v = BRep_Tool::Pnt(vertex);
    gp_Dir away = awayFrom(data.edge, vertex);
    double otherParameter = 0.0;
    gp_Dir otherAway = awayFrom(other.edge, vertex, &otherParameter);
    double sine = gp_Vec(away).Crossed(gp_Vec(otherAway)).Magnitude();
    if (sine < 0.1) {
        refuse("a reflex corner whose edges are nearly tangent");
    }
    // The other wall's material side in the shared face
    TopoDS_Face shared = sharedFace(data, other);
    gp_Dir otherInward = inwardIn(shared, other.edge, otherParameter);
    bool otherBulges = false;
    gp_Pnt otherCentre;
    if (!other.line) {
        gp_Dir z = other.circle.Axis().Direction();
        gp_Vec pc(other.circle.Location(), v);
        pc -= gp_Vec(z) * pc.Dot(gp_Vec(z));
        otherCentre = v.Translated(-pc);
        otherBulges = otherInward.Dot(gp_Dir(pc)) < 0;
    }
    if (data.line) {
        double length = 4 * r / sine;
        if (otherBulges) {
            // Half the chord of the other's circle
            double half = gp_Vec(v, otherCentre).Dot(gp_Vec(away.Reversed()));
            if (half > linearTolerance) {
                length = std::min(length, half);
            }
        }
        return length;
    }
    gp_Dir z = data.circle.Axis().Direction();
    gp_Vec cv(data.circle.Location(), v);
    cv -= gp_Vec(z) * cv.Dot(gp_Vec(z));
    gp_Pnt centre = v.Translated(-cv);
    double radius = data.circle.Radius();
    double span = data.last - data.first;
    double angle = std::min(4 * r / (sine * radius), 2 * pi - span - 0.05);
    // The middle of the stretch inside the other wall's side: on the line through this circle's
    // centre square to a straight wall, or through both centres
    gp_Vec across;
    if (other.line) {
        across = gp_Vec(otherInward);
    }
    else {
        across = gp_Vec(centre, otherCentre);
        if (across.Magnitude() < linearTolerance) {
            refuse("a reflex corner of two coaxial circles");
        }
        across.Normalize();
        if (!otherBulges) {
            across.Reverse();
        }
    }
    // (towards the other's centre if it bulges, away from it if it is hollow, into a half-space)
    double cosine = std::clamp(gp_Vec(gp_Dir(cv)).Dot(across), -1.0, 1.0);
    double middle = std::acos(cosine);
    if (middle > 1e-6) {
        angle = std::min(angle, middle);
    }
    if (angle <= 1e-6) {
        refuse("no room to run a round on past a reflex corner");
    }
    return angle;
}

/// How far from the vertex a run-on tool reaches, in the shared face
double reachOf(const EdgeData& data, double runOn)
{
    if (data.line) {
        return runOn;
    }
    double radius = data.circle.Radius();
    return runOn >= pi ? 2 * radius : 2 * radius * std::sin(runOn / 2);
}

/// Sets up a reflex end before its tool is built: its run on, and for a line its end plane
void prepareReflexEnd(
    const Context& ctx,
    const std::vector<EdgeData>& all,
    const EdgeData& data,
    VertexEnd ends[2],
    int slot
)
{
    TopoDS_Vertex vertex = vertexAt(data, slot);
    const EdgeData& other = edgeDataOf(all, ends[slot].other);
    ends[slot].runOn = runOnOf(ctx, all, data, vertex, other);
    if (data.line) {
        gp_Dir away = awayFrom(data.edge, vertex);
        gp_Pnt v = BRep_Tool::Pnt(vertex);
        ends[slot].trims = {{v.Translated(-gp_Vec(away) * ends[slot].runOn), away.Reversed()}};
    }
}

/// The sweep of a tool built by circleTool or lineTool with these ends
Sweep sweepOf(const Context& ctx, const EdgeData& data, const VertexEnd ends[2])
{
    Sweep sweep;
    double runBefore = 0.0;
    if (!data.line && ends[0].kind == VertexClass::Corner2Reflex) {
        runBefore = ends[0].runOn;
    }
    Section section = sectionAt(ctx, data, data.first - runBefore);
    if (data.line) {
        sweep.line = true;
        sweep.direction = gp_Dir(gp_Vec(data.start, data.end));
        sweep.begin = ends[0].trims;
        sweep.finish = ends[1].trims;
        sweep.corner = section.corner;
        sweep.in0 = section.inward[0];
        sweep.in1 = section.inward[1];
        sweep.r = section.radius;
        return sweep;
    }
    const gp_Circ& circle = data.circle;
    gp_Ax1 axis = circle.Axis();
    const gp_Dir& z = axis.Direction();
    gp_Dir radial(gp_Vec(circle.Location(), section.corner));
    for (auto& d : section.inward) {
        double rr = d.Dot(radial);
        if (std::abs(rr) > 0.5) {
            d = rr > 0 ? radial : radial.Reversed();
        }
        else {
            d = d.Dot(z) > 0 ? z : z.Reversed();
        }
    }
    double runAfter = ends[1].kind == VertexClass::Corner2Reflex ? ends[1].runOn : 0.0;
    sweep.line = false;
    sweep.total = std::min(2 * pi, data.last - data.first + runBefore + runAfter);
    if (sweep.total > 2 * pi - angularTolerance) {
        sweep.total = 2 * pi;
    }
    sweep.corner = section.corner;
    sweep.in0 = section.inward[0];
    sweep.in1 = section.inward[1];
    sweep.r = section.radius;
    gp_Vec toCorner(circle.Location(), sweep.corner);
    gp_Vec across = toCorner - gp_Vec(z) * toCorner.Dot(gp_Vec(z));
    sweep.frame = gp_Ax2(circle.Location(), z, gp_Dir(across));
    return sweep;
}

/// The 8-point Gauss-Legendre rule on [-1, 1]
constexpr double gaussNodes[8] = {-0.9602898564975363, -0.7966664774136267, -0.5255324099163290,
                                  -0.1834346424956498, 0.1834346424956498,  0.5255324099163290,
                                  0.7966664774136267,  0.9602898564975363};
constexpr double gaussWeights[8] = {0.1012285362903763, 0.2223810344533745, 0.3137066458778873,
                                    0.3626837833783620, 0.3626837833783620, 0.3137066458778873,
                                    0.2223810344533745, 0.1012285362903763};

/** Calls f(u, v, weight) at the quadrature nodes of a round's section: the square [0, r]^2 less
 * the disc of radius r about (r, r), in polar coordinates about that centre
 */
template<class F>
void sectionNodes(double r, F f)
{
    const int panels = 4;
    for (int half = 0; half < 2; ++half) {
        for (int pa = 0; pa < panels; ++pa) {
            double a0 = pi + half * pi / 4 + pa * (pi / 4) / panels;
            double a1 = a0 + (pi / 4) / panels;
            for (int i = 0; i < 8; ++i) {
                double phi = (a0 + a1) / 2 + (a1 - a0) / 2 * gaussNodes[i];
                double wphi = (a1 - a0) / 2 * gaussWeights[i];
                double rhoMax = r / std::max(-std::cos(phi), -std::sin(phi));
                for (int pr = 0; pr < panels; ++pr) {
                    double b0 = r + (rhoMax - r) * pr / panels;
                    double b1 = r + (rhoMax - r) * (pr + 1) / panels;
                    for (int j = 0; j < 8; ++j) {
                        double rho = (b0 + b1) / 2 + (b1 - b0) / 2 * gaussNodes[j];
                        double w = wphi * (b1 - b0) / 2 * gaussWeights[j] * rho;
                        f(r + rho * std::cos(phi), r + rho * std::sin(phi), w);
                    }
                }
            }
        }
    }
}

/** Where a condition may change along the path of one point of a sweep's section: the path is a
 * circle about the sweep's axis or a line along it, and the conditions of a reflex corner are
 * distances from vertical axes and from vertical planes, so the changes are roots of
 * a + b cos(t - c) or of a quadratic, in closed form
 */
struct PathChanges
{
    const Sweep& sweep;
    gp_Dir up;  // the shared face's normal: the conditions are taken in the plane square to it
    gp_Pnt x0;
    double from = 0.0;
    double to = 0.0;
    double rho = 0.0;  // circle: the path's radius, and the angle of x0 in the sweep's frame
    double theta0 = 0.0;
    std::vector<double>& changes;

    PathChanges(
        const Sweep& sweep,
        const gp_Dir& up,
        const gp_Pnt& x0,
        double from,
        double to,
        std::vector<double>& changes
    )
        : sweep(sweep)
        , up(up)
        , x0(x0)
        , from(from)
        , to(to)
        , changes(changes)
    {
        if (!sweep.line) {
            gp_Vec w(sweep.frame.Location(), x0);
            double x = w.Dot(gp_Vec(sweep.frame.XDirection()));
            double y = w.Dot(gp_Vec(sweep.frame.YDirection()));
            rho = std::hypot(x, y);
            theta0 = std::atan2(y, x);
        }
    }

    void add(double t)
    {
        if (t > from && t < to) {
            changes.push_back(t);
        }
    }
    /// rho * amplitude * cos(t + theta0 - phase) = value
    void cosine(double amplitude, double phase, double value)
    {
        double scale = rho * amplitude;
        if (scale < 1e-12 || std::abs(value) > scale) {
            return;
        }
        double angle = std::acos(value / scale);
        for (int k = -2; k <= 2; ++k) {
            add(phase - theta0 + angle + 2 * pi * k);
            add(phase - theta0 - angle + 2 * pi * k);
        }
    }
    /// The path's point is at the distance from the vertical axis through the point
    void distance(const gp_Pnt& axisPoint, double radius)
    {
        if (radius <= 0) {
            return;
        }
        if (sweep.line) {
            gp_Vec w(axisPoint, x0);
            w -= gp_Vec(up) * w.Dot(gp_Vec(up));
            double half = w.Dot(gp_Vec(sweep.direction));
            double rest = half * half - (w.Dot(w) - radius * radius);
            if (rest >= 0) {
                add(-half + std::sqrt(rest));
                add(-half - std::sqrt(rest));
            }
            return;
        }
        gp_Vec a(sweep.frame.Location(), axisPoint);
        double ax = a.Dot(gp_Vec(sweep.frame.XDirection()));
        double ay = a.Dot(gp_Vec(sweep.frame.YDirection()));
        double d = std::hypot(ax, ay);
        // |p - a|^2 = rho^2 + d^2 - 2 rho d cos(t + theta0 - alpha)
        cosine(2 * d, std::atan2(ay, ax), rho * rho + d * d - radius * radius);
    }
    /// The path's point is at the (signed) offset from the vertical plane through the point
    void offset(const gp_Pnt& planePoint, const gp_Dir& normal, double value)
    {
        if (sweep.line) {
            double along = gp_Vec(normal).Dot(gp_Vec(sweep.direction));
            if (std::abs(along) > 1e-12) {
                add((value - gp_Vec(planePoint, x0).Dot(gp_Vec(normal))) / along);
            }
            return;
        }
        double nx = gp_Vec(normal).Dot(gp_Vec(sweep.frame.XDirection()));
        double ny = gp_Vec(normal).Dot(gp_Vec(sweep.frame.YDirection()));
        double base = gp_Vec(planePoint, sweep.frame.Location()).Dot(gp_Vec(normal));
        // n . (p - p0) = base + rho |n| cos(t + theta0 - beta)
        cosine(std::hypot(nx, ny), std::atan2(ny, nx), value - base);
    }
};

/** The volume of the part of the sweep where inside(point) holds: over the section, the length of
 * each point's path inside. changes(point, from, to, list) lists where inside() may change along
 * the path (PathChanges); between two of them it is taken at the middle
 */
template<class In, class Changes>
double sweptInside(const Sweep& sweep, In inside, Changes changes)
{
    double volume = 0.0;
    std::vector<double> at;
    sectionNodes(sweep.r, [&](double u, double v, double w) {
        gp_Pnt x0 = sweep.node(u, v);
        double from = 0.0;
        double to = 0.0;
        double speed = 1.0;
        sweep.range(x0, from, to, speed);
        if (!(to > from)) {
            return;
        }
        at.clear();
        changes(x0, from, to, at);
        at.push_back(from);
        at.push_back(to);
        std::sort(at.begin(), at.end());
        double length = 0.0;
        for (size_t i = 0; i + 1 < at.size(); ++i) {
            if (at[i + 1] - at[i] > 1e-14 && inside(sweep.at(x0, (at[i] + at[i + 1]) / 2))) {
                length += at[i + 1] - at[i];
            }
        }
        volume += w * length * speed;
    });
    return volume;
}

/// Calls f(point) at the run-on end of the sweep's path for each node (slot 0: its start)
template<class F>
void runOnEnds(const Sweep& sweep, int slot, F f)
{
    if (sweep.closed()) {
        return;
    }
    sectionNodes(sweep.r, [&](double u, double v, double) {
        gp_Pnt x0 = sweep.node(u, v);
        double from = 0.0;
        double to = 0.0;
        double speed = 1.0;
        sweep.range(x0, from, to, speed);
        f(sweep.at(x0, slot == 0 ? from : to));
    });
}

/// The material side of a wall (the face of the edge that is not the shared face), near a vertex
struct WallSide
{
    bool line = true;
    gp_Pnt point;   // line: on the wall; circle: on the axis
    gp_Dir inward;  // line: into the material; circle: the axis
    double radius = 0.0;
    bool insideCircle = true;
    gp_Pnt vertex;
    gp_Dir normal;  // the shared face's
    double reach = 0.0;
    /// The corner's mirror plane (cornerDomain): a point on it, and its normal away from the vertex
    gp_Pnt mirrorPoint;
    gp_Dir mirrorNormal;

    /// In the corner's domain: within reach of the vertex, on its side of the mirror plane
    bool local(const gp_Pnt& p) const
    {
        gp_Vec w(vertex, p);
        w -= gp_Vec(normal) * w.Dot(gp_Vec(normal));
        return w.Magnitude() < reach && gp_Vec(mirrorPoint, p).Dot(gp_Vec(mirrorNormal)) < 0;
    }
    /// How deep the point lies behind the wall, in its material side (negative: in front of it)
    double depth(const gp_Pnt& p) const
    {
        if (line) {
            return gp_Vec(point, p).Dot(gp_Vec(inward));
        }
        gp_Vec w(point, p);
        w -= gp_Vec(inward) * w.Dot(gp_Vec(inward));
        double d = w.Magnitude();
        return insideCircle ? radius - d : d - radius;
    }
    /// The direction in which the depth grows fastest (a unit vector, in the shared face)
    gp_Vec gradient(const gp_Pnt& p) const
    {
        if (line) {
            return gp_Vec(inward);
        }
        gp_Vec w(point, p);
        w -= gp_Vec(inward) * w.Dot(gp_Vec(inward));
        w.Normalize();
        return insideCircle ? -w : w;
    }
};

WallSide wallSideOf(
    const EdgeData& wall,
    const TopoDS_Face& shared,
    const TopoDS_Vertex& vertex,
    double reach
)
{
    WallSide side;
    double parameter = 0.0;
    awayFrom(wall.edge, vertex, &parameter);
    side.vertex = BRep_Tool::Pnt(vertex);
    side.normal = outwardNormal(shared, side.vertex);
    side.reach = reach;
    gp_Dir inward = inwardIn(shared, wall.edge, parameter);
    if (wall.line) {
        side.line = true;
        side.point = side.vertex;
        side.inward = inward;
        return side;
    }
    side.line = false;
    side.point = wall.circle.Location();
    side.inward = wall.circle.Axis().Direction();
    side.radius = wall.circle.Radius();
    gp_Vec radial(side.point, side.vertex);
    radial -= gp_Vec(side.inward) * radial.Dot(gp_Vec(side.inward));
    side.insideCircle = inward.Dot(gp_Dir(radial)) < 0;
    return side;
}

/** Sets the mirror plane of a reflex corner on both its walls' sides. Each wall's side is only
 * known near the vertex: a straight wall's half-space, or a hollow wall's outside, says nothing
 * of where its body ends (a box's far side, hidden in the disc fused to it). The corner's model
 * holds up to the plane about which its two walls' curves mirror each other's crossings: through
 * both circles' axes, or through a circle's axis square to a straight wall. Beyond it lies the
 * mirror image of the corner, another corner's domain or none; the run on ends there too
 */
void cornerDomain(WallSide& a, WallSide& b)
{
    gp_Pnt on;
    gp_Vec normal;
    if (a.line && b.line) {
        refuse("a reflex corner of two straight edges");
    }
    if (a.line != b.line) {
        const WallSide& circle = a.line ? b : a;
        const WallSide& line = a.line ? a : b;
        on = circle.point;
        normal = gp_Vec(a.normal).Crossed(gp_Vec(line.inward));
    }
    else {
        on = a.point;
        gp_Vec between(a.point, b.point);
        between -= gp_Vec(a.normal) * between.Dot(gp_Vec(a.normal));
        if (between.Magnitude() < 1e3 * linearTolerance) {
            refuse("a reflex corner of two coaxial circles");
        }
        normal = gp_Vec(a.normal).Crossed(between);
    }
    normal.Normalize();
    double side = gp_Vec(on, a.vertex).Dot(normal);
    if (std::abs(side) < 1e3 * linearTolerance) {
        refuse("a reflex corner on its own mirror plane");
    }
    if (side > 0) {
        normal.Reverse();
    }
    a.mirrorPoint = b.mirrorPoint = on;
    a.mirrorNormal = b.mirrorNormal = gp_Dir(normal);
}

/** The two regions a reflex corner's mitre parts the neighbourhood of its vertex into (within the
 * cylinder of radius reach about the vertex): where a point lies deeper behind wall a than behind
 * wall b, and the rest. Both rounds have the same radius, so they are equally high exactly where a
 * point is equally deep behind both walls: the mitre lies on the vertical cylinder over that
 * bisector, a conic in the shared face (two circles that both bulge or are both hollow: a
 * hyperbola about their centres, or their centres' bisecting line when the radii are equal; a
 * bulging and a hollow circle: an ellipse; a circle and a line: a parabola about the centre).
 * The tools are cut by that cylinder, which crosses both rounds squarely all the way: OCCT's
 * common part of the two tori themselves is wrong where they touch (a horn torus)
 */
struct MitreRegions
{
    TopoDS_Shape deeperA;  // depth behind a >= depth behind b
    TopoDS_Shape deeperB;
};

MitreRegions mitreRegions(const WallSide& a, const WallSide& b, double r, double scale)
{
    const gp_Dir& up = a.normal;
    const double reach = a.reach;
    const double height = 5 * r;
    gp_Pnt bottom = a.vertex.Translated(-gp_Vec(up) * (4 * r));
    auto flat = [&](const gp_Pnt& p) {
        gp_Vec w(bottom, p);
        return p.Translated(-gp_Vec(up) * w.Dot(gp_Vec(up)));
    };
    TopoDS_Shape local = BRepPrimAPI_MakeCylinder(gp_Ax2(bottom, up), reach, height).Shape();
    {
        // The corner's domain (cornerDomain): the vertex's side of the mirror plane
        gp_Pnt on = flat(a.mirrorPoint).Translated(gp_Vec(up) * (height / 2));
        BRepAlgoAPI_Cut domain(local, halfSpaceBeyond({on, a.mirrorNormal}, 4 * scale + 4 * reach));
        if (!domain.IsDone() || domain.HasErrors() || countSolids(domain.Shape()) != 1) {
            refuse("building a reflex corner's domain failed");
        }
        local = domain.Shape();
    }
    // The side of the bisector that holds its focus (its convex side), as a solid
    TopoDS_Shape convex;
    auto prismOf = [&](const TopoDS_Edge& arc,
                       const gp_Dir& axis,
                       const gp_Dir& across,
                       double level) {
        // The arc, closed along its axis at the level (measured from the bottom point along axis)
        BRepAdaptor_Curve curve(arc);
        gp_Pnt first = curve.Value(curve.FirstParameter());
        gp_Pnt last = curve.Value(curve.LastParameter());
        auto atLevel = [&](const gp_Pnt& p) {
            gp_Vec w(bottom, p);
            return bottom.Translated(gp_Vec(across) * w.Dot(gp_Vec(across)) + gp_Vec(axis) * level);
        };
        BRepBuilderAPI_MakeWire wire(
            arc,
            BRepBuilderAPI_MakeEdge(last, atLevel(last)).Edge(),
            BRepBuilderAPI_MakeEdge(atLevel(last), atLevel(first)).Edge(),
            BRepBuilderAPI_MakeEdge(atLevel(first), first).Edge()
        );
        if (!wire.IsDone()) {
            refuse("building a reflex corner's mitre failed");
        }
        TopoDS_Face face = BRepBuilderAPI_MakeFace(wire.Wire(), Standard_True).Face();
        return BRepPrimAPI_MakePrism(face, gp_Vec(up) * height, Standard_True).Shape();
    };
    auto axial = [&](const gp_Pnt& p, const gp_Dir& axis) {
        return gp_Vec(bottom, p).Dot(gp_Vec(axis));
    };
    const double width = 2 * reach + r;  // how far the arc runs to either side of the vertex
    if (a.line != b.line) {
        // A parabola: its focus the circle's centre, its directrix the line moved by the radius
        // (into the line's material for a bulging circle, out of it for a hollow one)
        const WallSide& circle = a.line ? b : a;
        const WallSide& line = a.line ? a : b;
        gp_Pnt focus = flat(circle.point);
        double s = gp_Vec(flat(line.point), focus).Dot(gp_Vec(line.inward));
        double p = circle.insideCircle ? circle.radius - s : circle.radius + s;
        if (p <= 1e3 * linearTolerance) {
            refuse("a reflex corner whose mitre has no room");
        }
        gp_Dir axis = circle.insideCircle ? line.inward.Reversed() : line.inward;  // apex to focus
        gp_Pnt apex = focus.Translated(-gp_Vec(axis) * (p / 2));
        gp_Ax2 frame(apex, up, axis);
        gp_Parab parabola(frame, p / 2);
        double at = gp_Vec(apex, flat(a.vertex)).Dot(gp_Vec(frame.YDirection()));
        TopoDS_Edge arc = BRepBuilderAPI_MakeEdge(parabola, at - width, at + width).Edge();
        double widest = std::max(std::abs(at - width), std::abs(at + width));
        double level = axial(apex, axis) + widest * widest / (2 * p) + 2 * reach;
        convex = prismOf(arc, axis, frame.YDirection(), level);
    }
    else if (a.line) {
        refuse("a reflex corner of two straight edges");
    }
    else {
        gp_Pnt ca = flat(a.point);
        gp_Pnt cb = flat(b.point);
        double between = ca.Distance(cb);
        if (between < 1e3 * linearTolerance) {
            refuse("a reflex corner of two coaxial circles");
        }
        gp_Pnt middle((ca.XYZ() + cb.XYZ()) / 2);
        if (a.insideCircle == b.insideCircle) {
            // |P ca| - |P cb| = ra - rb: a hyperbola's branch about the centre of the smaller
            // circle; a line when the radii are equal
            double difference = a.radius - b.radius;
            if (std::abs(difference) < 1e-9 * between) {
                gp_Dir normal(gp_Vec(ca, cb));
                gp_Pnt on = middle.Translated(gp_Vec(up) * (height / 2));
                convex = halfSpaceBeyond({on, normal}, 4 * scale);
            }
            else {
                gp_Dir axis(difference > 0 ? gp_Vec(ca, cb) : gp_Vec(cb, ca));
                double major = std::abs(difference) / 2;
                double focal = between / 2;
                if (focal <= major + 1e3 * linearTolerance) {
                    refuse("a reflex corner whose mitre has no room");
                }
                double minor = std::sqrt(focal * focal - major * major);
                gp_Ax2 frame(middle, up, axis);
                gp_Hypr hyperbola(frame, major, minor);
                double at = gp_Vec(middle, flat(a.vertex)).Dot(gp_Vec(frame.YDirection()));
                double u0 = std::asinh((at - width) / minor);
                double u1 = std::asinh((at + width) / minor);
                TopoDS_Edge arc = BRepBuilderAPI_MakeEdge(hyperbola, u0, u1).Edge();
                double level = axial(middle, axis)
                    + major * std::cosh(std::max(std::abs(u0), std::abs(u1))) + 2 * reach;
                convex = prismOf(arc, axis, frame.YDirection(), level);
            }
        }
        else {
            // |P ca| + |P cb| = ra + rb: an ellipse about both centres
            double major = (a.radius + b.radius) / 2;
            double focal = between / 2;
            if (major <= focal + 1e3 * linearTolerance) {
                refuse("a reflex corner whose mitre has no room");
            }
            double minor = std::sqrt(major * major - focal * focal);
            gp_Elips ellipse(gp_Ax2(middle, up, gp_Dir(gp_Vec(ca, cb))), major, minor);
            BRepBuilderAPI_MakeWire wire(BRepBuilderAPI_MakeEdge(ellipse).Edge());
            TopoDS_Face face = BRepBuilderAPI_MakeFace(wire.Wire(), Standard_True).Face();
            convex = BRepPrimAPI_MakePrism(face, gp_Vec(up) * height, Standard_True).Shape();
        }
    }
    if (convex.IsNull() || countSolids(convex) != 1) {
        refuse("building a reflex corner's mitre failed");
    }
    if (volumeOf(convex) < 0) {
        convex.Reverse();
    }
    // Which side is deeper behind a: a point a little off the vertex, along the depths' gradient
    gp_Vec gradient = a.gradient(a.vertex) - b.gradient(a.vertex);
    if (gradient.Magnitude() < 0.1) {
        refuse("a reflex corner whose edges are nearly tangent");
    }
    gp_Pnt probe = a.vertex.Translated(gradient.Normalized() * (r / 4) - gp_Vec(up) * (r / 2));
    BRepClass3d_SolidClassifier classifier(convex, probe, linearTolerance);
    const bool inConvex = classifier.State() == TopAbs_IN;
    if (!inConvex && classifier.State() != TopAbs_OUT) {
        refuse("a reflex corner's mitre passes through its probe point");
    }
    BRepAlgoAPI_Common common(local, convex);
    BRepAlgoAPI_Cut cut(local, convex);
    if (!common.IsDone() || common.HasErrors() || !cut.IsDone() || cut.HasErrors()) {
        refuse("building a reflex corner's mitre failed");
    }
    MitreRegions regions;
    regions.deeperA = inConvex ? common.Shape() : cut.Shape();
    regions.deeperB = inConvex ? cut.Shape() : common.Shape();
    return regions;
}

/// The reflex corners' run-on tools
struct ReflexCorners
{
    struct Corner
    {
        TopoDS_Vertex vertex;
        TopoDS_Shape first;  // the edge whose tool was built first
        MitreRegions regions;  // a: the first edge's wall
    };
    std::vector<Corner> corners;
    bool found = false;

    bool any() const
    {
        return found;
    }

    /// The reach of the cylinder about the vertex that bounds the corner's cuts
    static double reachAt(
        const Context& ctx,
        const std::vector<EdgeData>& all,
        const EdgeData& a,
        const EdgeData& b,
        const TopoDS_Vertex& vertex
    )
    {
        double r = ctx.request.size1;
        return std::max(
                   reachOf(a, runOnOf(ctx, all, a, vertex, b)),
                   reachOf(b, runOnOf(ctx, all, b, vertex, a))
               )
            + 2 * r;
    }

    /// The edge's tool, run on: cut away what lies deeper behind the other wall at each reflex
    /// end, and its closed form less that part's quadrature becomes its volume
    void add(
        const Context& ctx,
        const std::vector<EdgeData>& all,
        const EdgeData& data,
        const VertexEnd ends[2],
        Tool& tool
    )
    {
        found = true;
        double r = ctx.request.size1;
        Sweep sweep = sweepOf(ctx, data, ends);
        std::vector<Handle(Geom_Surface)> regionSurfaces;
        struct Sides
        {
            WallSide own;
            WallSide other;
        };
        std::vector<Sides> sides;
        for (int slot = 0; slot < 2; ++slot) {
            if (ends[slot].kind != VertexClass::Corner2Reflex) {
                continue;
            }
            TopoDS_Vertex vertex = vertexAt(data, slot);
            const EdgeData& other = edgeDataOf(all, ends[slot].other);
            TopoDS_Face shared = sharedFace(data, other);
            double reach = reachAt(ctx, all, data, other, vertex);
            Sides pair {
                wallSideOf(data, shared, vertex, reach),
                wallSideOf(other, shared, vertex, reach)
            };
            cornerDomain(pair.own, pair.other);
            auto corner = std::find_if(corners.begin(), corners.end(), [&](const Corner& c) {
                return c.vertex.IsSame(vertex);
            });
            if (corner == corners.end()) {
                corners.push_back(
                    {vertex, data.edge, mitreRegions(pair.own, pair.other, r, ctx.scale)}
                );
                corner = std::prev(corners.end());
            }
            const TopoDS_Shape& beyond = corner->first.IsSame(data.edge) ? corner->regions.deeperB
                                                                          : corner->regions.deeperA;
            BRepAlgoAPI_Cut cut(tool.solid, beyond);
            if (!cut.IsDone() || cut.HasErrors()) {
                refuse("cutting a tool at a reflex corner failed");
            }
            tool.solid = cut.Shape();
            for (TopExp_Explorer it(beyond, TopAbs_FACE); it.More(); it.Next()) {
                TopLoc_Location location;
                regionSurfaces.push_back(BRep_Tool::Surface(TopoDS::Face(it.Current()), location));
            }
            // The run on ends beyond the mitre, where it is cut away: the rounds close within it
            // (a spindle round's do not: its mitre runs on to the corner's mirror image)
            // (it may end on the mirror plane itself)
            runOnEnds(sweep, slot, [&](const gp_Pnt& p) {
                gp_Vec fromVertex(pair.own.vertex, p);
                fromVertex -= gp_Vec(pair.own.normal) * fromVertex.Dot(gp_Vec(pair.own.normal));
                gp_Vec fromMirror(pair.own.mirrorPoint, p);
                if (fromVertex.Magnitude() >= pair.own.reach
                    || fromMirror.Dot(gp_Vec(pair.own.mirrorNormal)) > 1e-6 * r
                    || pair.other.depth(p) - pair.own.depth(p) < 1e-9 * r) {
                    refuse("the rounds at a reflex corner do not close within their run on");
                }
            });
            sides.push_back(pair);
        }
        double removed = sweptInside(
            sweep,
            [&](const gp_Pnt& p) {
                return std::any_of(sides.begin(), sides.end(), [&](const Sides& s) {
                    return s.own.local(p) && s.other.depth(p) > s.own.depth(p);
                });
            },
            [&](const gp_Pnt& x0, double from, double to, std::vector<double>& list) {
                for (const auto& s : sides) {
                    PathChanges path(sweep, s.own.normal, x0, from, to, list);
                    // The own wall's depth is the same all along the path
                    double depth = s.own.depth(x0);
                    if (s.other.line) {
                        path.offset(s.other.point, s.other.inward, depth);
                    }
                    else {
                        path.distance(
                            s.other.point,
                            s.other.insideCircle ? s.other.radius - depth : s.other.radius + depth
                        );
                    }
                    path.distance(s.own.vertex, s.own.reach);
                    path.offset(s.own.mirrorPoint, s.own.mirrorNormal, 0.0);
                }
            }
        );
        tool.volume -= removed;
        tool.relTolerance = 1e-4;
        // The tool's faces on the regions' surfaces: the mitre, which the other edge's tool ends on
        // too, so that nothing of it is left once both are cut. A face left on it, or on the
        // domain's own boundary, means the corner's model does not hold there (unionEndFaces'
        // check refuses)
        for (TopExp_Explorer it(tool.solid, TopAbs_FACE); it.More(); it.Next()) {
            TopLoc_Location location;
            Handle(Geom_Surface) surface = BRep_Tool::Surface(TopoDS::Face(it.Current()), location);
            if (std::find(regionSurfaces.begin(), regionSurfaces.end(), surface)
                != regionSurfaces.end()) {
                tool.unionEndFaces.push_back(it.Current());
            }
        }
    }
};

TopoDS_Shape constructShape(
    const TopoDS_Shape& baseShape,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    ShapeMapper& mapper,
    int& cornerCount,
    bool& rolledOn
)
{
    rolledOn = false;
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
            refuse(tangentChainRefusal);
        }
    }
    for (int i = 1; i <= ctx.selected.Extent(); ++i) {
        data.push_back(analyse(ctx, TopoDS::Edge(ctx.selected(i))));
    }

    std::vector<Tool> tools;
    ReflexCorners reflex;
    // Each tool's checks before any Boolean
    auto admit = [&](Tool&& tool) {
        if (countSolids(tool.solid) != 1) {
            refuse("a tool is not one solid");
        }
        double measured = volumeOf(tool.solid);
        // A Boolean that built the tool may leave a vertex off its edges, and the measured volume
        // off by as much as raisedTolerance says (Case Base #105's fourth grip: 1.35e-6, the
        // volume 1.7e-6 relative off)
        double allowance = raisedTolerance(tool.solid, {}) * squareSize(tool.solid);
        if (!tool.measured
            && std::abs(measured - tool.volume) > tool.relTolerance * tool.volume + allowance) {
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
        else if (tool.rolled) {
            // And a convex edge's rolled tool removes material only, all of its section
            double inBase = volumeOf(commonOf(base.getShape(), tool.solid));
            if (std::abs(inBase - tool.volume) > volumeTolerance * tool.volume) {
                refuse("a round rolled on over a tangent edge runs out of the material");
            }
        }
        tools.push_back(std::move(tool));
    };
    // The edges' tools, admitted once a curved end has trimmed the tools it reaches into
    std::vector<Tool> edgeTools;
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
                // (a reflex corner's tools are interior-disjoint, with volumes of their own: they
                // are cut together, not one by one as overlapping tools are)
                unionCorners = unionCorners || kind == VertexClass::Corner2Union;
                if (kind == VertexClass::Corner2Reflex) {
                    cornerVertices.Add(vertices[i]);
                }
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
        bool reflexEnd = false;
        for (int slot = 0; slot < 2 && !edgeData.closed; ++slot) {
            if (ends[slot].kind == VertexClass::Corner2Reflex) {
                reflexEnd = true;
                prepareReflexEnd(ctx, data, edgeData, ends, slot);
            }
        }
        if (edgeData.ruled) {
            if (reflexEnd) {
                refuse("a reflex corner with a straight edge on a cylinder");
            }
            edgeTools.push_back(ruledTool(ctx, edgeData, ends, request.size1));
        }
        else if (edgeData.line) {
            if (auto tool = lineTool(ctx, edgeData, ends)) {
                if (reflexEnd) {
                    reflex.add(ctx, data, edgeData, ends, *tool);
                }
                edgeTools.push_back(std::move(*tool));
            }
            else if (reflexEnd) {
                refuse("a tool at a reflex corner has no length");
            }
        }
        else if (tightArc(ctx, edgeData)) {
            edgeTools.push_back(tightTool(ctx, edgeData, ends, data));
        }
        else {
            Tool tool = circleTool(ctx, edgeData, ends);
            if (reflexEnd) {
                reflex.add(ctx, data, edgeData, ends, tool);
            }
            edgeTools.push_back(std::move(tool));
        }
    }
    // A curved end's surface that runs on past a short edge trims the tool it continues into
    for (const auto& tool : edgeTools) {
        for (const auto& pass : tool.passOn) {
            auto next = std::find_if(edgeTools.begin(), edgeTools.end(), [&](const Tool& t) {
                return t.source.IsSame(pass.edge);
            });
            auto nextData = std::find_if(data.begin(), data.end(), [&](const EdgeData& d) {
                return d.edge.IsSame(pass.edge);
            });
            if (next == edgeTools.end() || nextData == data.end()) {
                refuse("the surface of an end face reaches a tangent edge without a tool");
            }
            if (!next->passOn.empty()) {
                refuse("the surface of an end face reaches past two edges");
            }
            if (next->measured) {
                refuse("the surface of an end face reaches a tight wall arc's tool");
            }
            // An arc turned on past its far end has no end face there: the check that nothing
            // goes at the far end (trimContinuation) would hold of itself
            if (!next->overflowFaces.empty()) {
                refuse("the surface of an end face reaches an overflowing arc's tool");
            }
            trimContinuation(ctx, *next, *nextData, pass);
        }
    }
    for (auto& tool : edgeTools) {
        admit(std::move(tool));
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
    // Rounds between two cylinders are built wherever they fit, not only at the limit: OCCT's own
    // are B-spline faces there (preferConstruction())
    const bool limitOnly = request.limitOnly
        && !(!data.empty() && std::all_of(data.begin(), data.end(), betweenCylinders));
    std::vector<SurfaceWall> surfaceWalls;
    const bool trimmed = checkStrips(
                             tools,
                             overlaps,
                             limitOnly && !reflex.any(),
                             ctx.edgeFaces,
                             ctx.selected,
                             fusedOff,
                             pastLoop,
                             walled,
                             wallsOf,
                             wallFaces,
                             fusedRuns,
                             surfaceWalls
                         )
        || unionCorners;
    // The faces beyond overflowing ends grow by the tools' faces on their surfaces (Onshape's
    // chamfer cone and bevel under #151's end tori), as walls a trimmed tool runs on under
    for (const auto& tool : tools) {
        for (const auto& face : tool.overflowFaces) {
            if (std::none_of(wallFaces.begin(), wallFaces.end(), [&](const TopoDS_Face& f) {
                    return f.IsSame(face);
                })) {
                wallFaces.push_back(face);
            }
        }
    }
    // A convex edge's rolled round trimmed like a direct one (past a ledge on the face it rolls
    // onto, or overlapping another round): the rules for that (Q-LEDGE, K2) are Onshape's for
    // direct dress-ups only, and the rolled tool was admitted as all material (review of the
    // convex roll-on). A concave edge's rolled tool refuses there by the fused tools' rules
    if (trimmed && std::any_of(tools.begin(), tools.end(), [](const Tool& t) {
            return t.rolled && t.cut;
        })) {
        refuse("a round rolled on over a tangent edge runs past its faces or overlaps another");
    }
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
    // Into a wall that does not run straight back from the face (it leans, or it is a blend: Case
    // Base #105): each such tool is trimmed by the wall's own surface, run on behind the face
    for (const auto& at : surfaceWalls) {
        const auto tool = std::find_if(tools.begin(), tools.end(), [&](const Tool& t) {
            return &t == at.tool;
        });
        const auto edge = std::find_if(data.begin(), data.end(), [&](const EdgeData& d) {
            return tool != tools.end() && d.edge.IsSame(tool->source);
        });
        if (tool == tools.end() || edge == data.end()) {
            refuse("a corner piece's strip runs off its face into a wall");
        }
        // The same tool against walls straight back too (behindWalls cut it above): the two trims
        // are not checked against each other
        for (const auto& runs : wallsOf) {
            if (std::any_of(runs.begin(), runs.end(), [&](const auto& run) {
                    return run.first == at.tool;
                })) {
                refuse("a dress-up runs into a wall straight back from its face and into one that "
                       "is not");
            }
        }
        // The feet of this tool's other walls, on other surfaces
        std::vector<TopoDS_Edge> otherFeet;
        for (const auto& other : surfaceWalls) {
            if (other.tool != at.tool || other.wall.IsSame(at.wall)
                || sameDomain(other.wall, at.wall)) {
                continue;
            }
            TopLoc_Location mine;
            TopLoc_Location theirs;
            if (BRep_Tool::Surface(at.wall, mine) == BRep_Tool::Surface(other.wall, theirs)
                && mine.IsEqual(theirs)) {
                continue;
            }
            otherFeet.push_back(other.foot);
        }
        if (trimByWall(ctx, *tool, *edge, at, otherFeet)
            && std::none_of(wallFaces.begin(), wallFaces.end(), [&](const TopoDS_Face& wall) {
                   return wall.IsSame(at.wall);
               })) {
            wallFaces.push_back(at.wall);
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
            // At a horn round's reflex corner the rounds' pieces meet in a point: merged into one
            // face across it, the face is not orientable. Then they stay apart (no face of the
            // corner's own either way: the pieces lie on the rounds' surfaces)
            if (!reflex.any() || BRepCheck_Analyzer(unify.Shape()).IsValid()) {
                shape = unify.Shape();
                stages.emplace_back(unify.History(), shape);
            }
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
    rolledOn = std::any_of(tools.begin(), tools.end(), [](const Tool& t) { return t.rolled; });
    return shape;
}

/// Thrown where the construction below an overhang does not apply at all: the first refusal stands
struct NoOverhang
{};

/** A round whose edge ends against a planar face that faces it, such as under an overhang (ops#640,
 * the replica's Case Base #103: a scoop's edge with a rounded corner ends under a 1 mm lip, 0.024
 * from the corner cylinder's tangent line, and r 0.79375 on it). OCCT builds the blend faces
 * there and leaves the corner's two side planes with open boundaries; the exact construction has
 * no free-form edges. Onshape's round is the round of the body without what lies behind that
 * face's plane, cut off by the plane: the lip's underside grows over what the round removes.
 *
 * So the round is OCCT's own, built on a piece of the base: the base within a box around the
 * edges (their extent and four radii more), less what lies behind the plane of every such face;
 * one piece for each connected group of edges (two grips' edges are two rounds).
 * What the round removes from the piece is the tool, and the result is the whole base less the
 * tool. The tool must stay a radius clear of the box's walls (OCCT's round on the piece is then
 * the base's round, which depends only on the faces near it), nothing of it may be left in the
 * result, and the result's volume must have changed by the tool's, within the base's own measure
 * (a whole-body difference: 1e-6 of the base, not of the tool; the cut itself is OCCT's).
 */
TopoDS_Shape constructUnderOverhang(
    const TopoDS_Shape& baseShape,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    ShapeMapper& mapper
)
{
    if (request.kind != Kind::Fillet || request.size1 <= 0
        || std::abs(request.size1 - request.size2) > linearTolerance || edges.empty()
        || countSolids(baseShape) != 1) {
        throw NoOverhang {};
    }
    const double radius = request.size1;
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopTools_IndexedDataMapOfShapeListOfShape vertexFaces;
    TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
    TopExp::MapShapesAndAncestors(baseShape, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    TopExp::MapShapesAndAncestors(baseShape, TopAbs_VERTEX, TopAbs_FACE, vertexFaces);
    TopExp::MapShapesAndAncestors(baseShape, TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
    // The edges OCCT rounds: the selected ones, and what its contours add along tangent chains
    TopTools_IndexedMapOfShape chain;
    for (const auto& edge : edges) {
        if (edge.ShapeType() != TopAbs_EDGE || !edgeFaces.Contains(edge)) {
            throw NoOverhang {};
        }
        chain.Add(edge);
    }
    for (const auto& edge : request.contour) {
        if (edgeFaces.Contains(edge)) {
            chain.Add(edge);
        }
    }
    // The edges in connected groups (two grips' edges are two rounds, each on its own piece)
    std::vector<int> root(chain.Extent() + 1);
    for (int i = 1; i <= chain.Extent(); ++i) {
        root[i] = i;
    }
    auto find = [&](int i) {
        while (root[i] != i) {
            i = root[i] = root[root[i]];
        }
        return i;
    };
    for (int i = 1; i <= chain.Extent(); ++i) {
        for (TopExp_Explorer it(chain(i), TopAbs_VERTEX); it.More(); it.Next()) {
            const auto* around = vertexEdges.Seek(it.Current());
            if (!around) {
                continue;
            }
            for (const auto& other : *around) {
                int j = chain.FindIndex(other);
                if (j > 0) {
                    root[find(i)] = find(j);
                }
            }
        }
    }
    struct Overhang
    {
        gp_Pnt point;
        gp_Dir outward;
    };
    struct Group
    {
        std::vector<TopoDS_Shape> selected;
        std::vector<gp_Pnt> samples;
        std::vector<Overhang> overhangs;
        // What its round removes, and where the tool's faces come from
        TopoDS_Shape tool;
        TopTools_IndexedMapOfShape ofPiece;
        std::vector<std::pair<TopoDS_Shape, TopoDS_Shape>> blends;  // (selected edge, tool face)
    };
    std::vector<Group> groups;
    // Every group must end under an overhang: a group that doesn't is no case of this
    // construction, and OCCT's round on a piece of the base isn't known to be right for it
    bool allOverhang = true;
    for (int r = 1; r <= chain.Extent(); ++r) {
        if (find(r) != r) {
            continue;
        }
        Group group;
        TopTools_IndexedMapOfShape members;
        TopTools_IndexedMapOfShape ownFaces;
        for (int i = 1; i <= chain.Extent(); ++i) {
            if (find(i) != r) {
                continue;
            }
            members.Add(chain(i));
            for (const auto& face : edgeFaces.FindFromKey(chain(i))) {
                ownFaces.Add(face);
            }
            BRepAdaptor_Curve curve(TopoDS::Edge(chain(i)));
            const int steps = 16;
            for (int k = 0; k <= steps; ++k) {
                group.samples.push_back(curve.Value(
                    curve.FirstParameter()
                    + (curve.LastParameter() - curve.FirstParameter()) * k / steps
                ));
            }
        }
        for (const auto& edge : edges) {
            if (members.Contains(edge)) {
                group.selected.push_back(edge);
            }
        }
        if (group.selected.empty()) {
            continue;
        }
        // The planar faces at the group's vertices, not next to its edges, that face them:
        // every sample in front of the face, and the edges a radius or more out from it
        for (int i = 1; i <= members.Extent(); ++i) {
            for (TopExp_Explorer it(members(i), TopAbs_VERTEX); it.More(); it.Next()) {
                const auto* faces = vertexFaces.Seek(it.Current());
                if (!faces) {
                    continue;
                }
                const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(it.Current()));
                for (const auto& shape : *faces) {
                    if (ownFaces.Contains(shape)) {
                        continue;
                    }
                    const TopoDS_Face& face = TopoDS::Face(shape);
                    if (BRepAdaptor_Surface(face, Standard_False).GetType() != GeomAbs_Plane) {
                        continue;
                    }
                    const gp_Dir outward = outwardNormal(face, point);
                    double most = 0.0;
                    bool behind = false;
                    for (const auto& sample : group.samples) {
                        double distance = gp_Vec(point, sample).Dot(gp_Vec(outward));
                        if (distance < -100 * linearTolerance) {
                            behind = true;
                            break;
                        }
                        most = std::max(most, distance);
                    }
                    if (behind || most < radius) {
                        continue;
                    }
                    bool known = std::any_of(
                        group.overhangs.begin(),
                        group.overhangs.end(),
                        [&](const Overhang& o) {
                            return o.outward.Dot(outward) > 1 - angularTolerance
                                && std::abs(gp_Vec(o.point, point).Dot(gp_Vec(outward)))
                                    < linearTolerance;
                        }
                    );
                    if (!known) {
                        group.overhangs.push_back({point, outward});
                    }
                }
            }
        }
        allOverhang = allOverhang && !group.overhangs.empty();
        groups.push_back(std::move(group));
    }
    if (groups.empty() || !allOverhang) {
        throw NoOverhang {};
    }
    auto boolean = [](BRepAlgoAPI_BooleanOperation& operation,
                      const TopoDS_Shape& argument,
                      const TopoDS_Shape& tool,
                      const char* failure) {
        TopTools_ListOfShape arguments;
        arguments.Append(argument);
        TopTools_ListOfShape tools;
        tools.Append(tool);
        operation.SetArguments(arguments);
        operation.SetTools(tools);
        operation.SetNonDestructive(Standard_True);
        operation.SetRunParallel(Standard_False);
        operation.Build();
        if (!operation.IsDone() || operation.HasErrors()) {
            refuse(failure);
        }
        return operation.Shape();
    };
    double toolVolume = 0.0;
    TopoDS_Compound allTools;
    BRep_Builder builder;
    builder.MakeCompound(allTools);
    for (auto& group : groups) {
        // The piece: the base within a box around the group, less what lies behind each
        // overhang's plane
        Bnd_Box bounds;
        for (const auto& sample : group.samples) {
            bounds.Add(sample);
        }
        bounds.Enlarge(4 * radius);
        const gp_Pnt low = bounds.CornerMin();
        const gp_Pnt high = bounds.CornerMax();
        std::vector<Stage> toPiece;
        BRepAlgoAPI_Common within;
        TopoDS_Shape piece = boolean(
            within,
            baseShape,
            BRepPrimAPI_MakeBox(low, high).Shape(),
            "cutting the piece of the base around a round under an overhang failed"
        );
        toPiece.emplace_back(within.History(), piece);
        const double reach = 2 * low.Distance(high) + 1;
        for (const auto& overhang : group.overhangs) {
            gp_Ax2 axes(overhang.point, overhang.outward.Reversed());
            axes.SetLocation(overhang.point.Translated(
                gp_Vec(axes.XDirection()) * -reach + gp_Vec(axes.YDirection()) * -reach
            ));
            BRepAlgoAPI_Cut behind;
            piece = boolean(
                behind,
                piece,
                BRepPrimAPI_MakeBox(axes, 2 * reach, 2 * reach, reach).Shape(),
                "cutting the piece of the base around a round under an overhang failed"
            );
            toPiece.emplace_back(behind.History(), piece);
        }
        // The selected edges in the piece, whole, and the one solid of it that holds them
        std::vector<std::pair<TopoDS_Shape, TopoDS_Edge>> inPiece;
        for (const auto& edge : group.selected) {
            auto images = imagesThrough(toPiece, 0, edge);
            if (images.size() != 1 || images.front().ShapeType() != TopAbs_EDGE) {
                refuse("a selected edge is not whole in front of the face it ends against");
            }
            inPiece.emplace_back(edge, TopoDS::Edge(images.front()));
        }
        TopoDS_Shape solid;
        for (TopExp_Explorer it(piece, TopAbs_SOLID); it.More() && solid.IsNull(); it.Next()) {
            TopTools_IndexedMapOfShape held;
            TopExp::MapShapes(it.Current(), TopAbs_EDGE, held);
            if (std::all_of(inPiece.begin(), inPiece.end(), [&](const auto& pair) {
                    return held.Contains(pair.second);
                })) {
                solid = it.Current();
            }
        }
        if (solid.IsNull()) {
            refuse("the selected edges are not on one solid in front of the face they end against");
        }
        BRepFilletAPI_MakeFillet maker(solid);
        for (const auto& pair : inPiece) {
            maker.Add(radius, pair.second);
        }
        try {
            maker.Build();
        }
        catch (const Standard_Failure&) {
            refuse("OCCT's round in front of the face its edge ends against failed");
        }
        if (!maker.IsDone()) {
            refuse("OCCT's round in front of the face its edge ends against failed");
        }
        TopoDS_Shape rounded = maker.Shape();
        // OCCT's round can leave an edge it kept (here a STEP edge at 5.148e-3) a few microns out
        // of tolerance on its trimmed face; the Boolean below would raise it in place anyway. Raise
        // it first, up to the piece's own largest tolerance plus 1e-4, so the check sees the result
        // that is cut.
        if (!BRepCheck_Analyzer(rounded).IsValid()) {
            double largest = Precision::Confusion();
            for (TopExp_Explorer it(solid, TopAbs_VERTEX); it.More(); it.Next()) {
                largest = std::max(largest, BRep_Tool::Tolerance(TopoDS::Vertex(it.Current())));
            }
            for (TopExp_Explorer it(solid, TopAbs_EDGE); it.More(); it.Next()) {
                largest = std::max(largest, BRep_Tool::Tolerance(TopoDS::Edge(it.Current())));
            }
            BOPTools_AlgoTools::CorrectTolerances(rounded, TopTools_IndexedMapOfShape(), largest + 1e-4);
        }
        if (countSolids(rounded) != 1 || !BRepCheck_Analyzer(rounded).IsValid()) {
            refuse("OCCT's round in front of the face its edge ends against is not a valid solid");
        }
        // OCCT's blend is not a rolling ball where a wall is twisted (ops#640, decision 425): the
        // piece's blend faces get the ball's geometry before the round becomes a tool, so what is
        // cut from the base is the ball's. A recognised chain that cannot be corrected refuses.
        std::vector<std::pair<TopoDS_Shape, TopoDS_Shape>> asBall;
        {
            std::vector<TopoDS_Face> faces;
            for (const auto& pair : inPiece) {
                for (const auto& blend : maker.Generated(pair.second)) {
                    if (blend.ShapeType() == TopAbs_FACE) {
                        faces.push_back(TopoDS::Face(blend));
                    }
                }
            }
            const RollingBallBlend::Report ball = RollingBallBlend::correct(rounded, faces, radius);
            if (ball.outcome == RollingBallBlend::Outcome::Refused) {
                refuse("a round's blend is not the surface of a rolling ball and its correction refused: " + ball.reason);
            }
            if (ball.outcome == RollingBallBlend::Outcome::Corrected) {
                rounded = ball.shape;
                for (size_t i = 0; i < faces.size(); ++i) {
                    asBall.emplace_back(faces[i], ball.blendFaces[i]);
                }
            }
        }
        // What the round removes from the piece: the tool
        BRepAlgoAPI_Cut removal;
        group.tool = boolean(
            removal,
            solid,
            rounded,
            "finding what a round under an overhang removes failed"
        );
        const Stage removed(removal.History(), group.tool);
        if (countSolids(group.tool) < 1 || !BRepCheck_Analyzer(group.tool).IsValid()) {
            refuse("a round under an overhang removes no valid solid");
        }
        // Adaptively: the tool is a sliver between free-form faces, and OCCT's default
        // integration of it is off by more than a percent (16.863 for 16.665 on the designed case)
        const double volume = MassProperties::volume(group.tool, true);
        if (volume <= 0) {
            refuse("a round under an overhang removes no valid solid");
        }
        // The tool is only what the round removes: a round that also adds material (a concave
        // edge in the group) would lose the addition, so the piece's volumes must balance
        const double before = MassProperties::volume(solid, true);
        const double after = MassProperties::volume(rounded, true);
        if (std::abs(before - after - volume) > 1e-2 * volume + 1e-6 * std::abs(before)) {
            refuse("a round under an overhang adds material (a concave edge)");
        }
        toolVolume += volume;
        Bnd_Box toolBounds;
        BRepBndLib::AddOptimal(group.tool, toolBounds, Standard_False, Standard_False);
        const gp_Pnt toolLow = toolBounds.CornerMin();
        const gp_Pnt toolHigh = toolBounds.CornerMax();
        if (toolLow.X() < low.X() + radius || toolLow.Y() < low.Y() + radius
            || toolLow.Z() < low.Z() + radius || toolHigh.X() > high.X() - radius
            || toolHigh.Y() > high.Y() - radius || toolHigh.Z() > high.Z() - radius) {
            refuse("a round under an overhang reaches the walls of the piece it is built on");
        }
        for (TopExp_Explorer it(solid, TopAbs_FACE); it.More(); it.Next()) {
            for (const auto& image : removed.images(it.Current())) {
                group.ofPiece.Add(image);
            }
        }
        for (const auto& pair : inPiece) {
            for (const auto& blend : maker.Generated(pair.second)) {
                TopoDS_Shape now = blend;
                for (const auto& corrected : asBall) {
                    if (corrected.first.IsSame(blend)) {
                        now = corrected.second;
                    }
                }
                for (const auto& face : removed.images(now)) {
                    group.blends.emplace_back(pair.first, face);
                }
            }
        }
        for (TopExp_Explorer it(group.tool, TopAbs_SOLID); it.More(); it.Next()) {
            builder.Add(allTools, it.Current());
        }
    }
    // The whole base less the tools
    BRepAlgoAPI_Cut whole;
    TopoDS_Shape shape = boolean(
        whole,
        baseShape,
        allTools,
        "cutting a round under an overhang from the base failed"
    );
    std::vector<Stage> stages;
    stages.emplace_back(whole.History(), shape);
    // The tools' faces on their pieces' own faces: of those only the caps in the overhangs' planes
    // are left in the result, each beside the face that hangs over it. Their edges alone are
    // free to go, so that the face grows over what the round removed (Onshape's, no step)
    TopTools_IndexedMapOfShape unlocked;
    for (const auto& group : groups) {
        for (int i = 1; i <= group.ofPiece.Extent(); ++i) {
            for (const auto& image : stages.front().images(group.ofPiece(i))) {
                if (image.ShapeType() == TopAbs_FACE) {
                    TopExp::MapShapes(image, TopAbs_EDGE, unlocked);
                }
            }
        }
    }
    if (!unlocked.IsEmpty()) {
        NCollection_Map<TopoDS_Shape, TopTools_ShapeMapHasher> keep;
        TopTools_IndexedMapOfShape allEdges;
        TopExp::MapShapes(shape, TopAbs_EDGE, allEdges);
        for (int i = 1; i <= allEdges.Extent(); ++i) {
            if (!unlocked.Contains(allEdges(i))) {
                keep.Add(allEdges(i));
            }
        }
        ShapeUpgrade_UnifySameDomain unify(shape, false, true, false);
        unify.KeepShapes(keep);
        unify.Build();
        shape = unify.Shape();
        stages.emplace_back(unify.History(), shape);
    }
    // The checks of the result
    if (countSolids(shape) != 1) {
        refuse("the result is not one solid");
    }
    if (!BRepCheck_Analyzer(shape).IsValid()) {
        refuse("the result is not valid");
    }
    if (!thinFace(shape, baseShape).IsNull()) {
        refuse("the result has a face of zero width");
    }
    for (TopExp_Explorer it(allTools, TopAbs_SOLID); it.More(); it.Next()) {
        if (materialIn(shape, it.Current())) {
            refuse("the cut left material of a round under an overhang");
        }
    }
    const double baseVolume = volumeOf(baseShape);
    const double bound = volumeTolerance * (baseVolume + toolVolume);
    double change = baseVolume - volumeOf(shape);
    if (std::abs(change - toolVolume) > bound) {
        change = MassProperties::volume(baseShape, true) - MassProperties::volume(shape, true);
    }
    if (std::abs(change - toolVolume) > bound) {
        refuse("the cut removed " + describe(change) + " instead of " + describe(toolVolume));
    }
    // The history: the base's elements are modified into their images; the tools' other faces
    // are generated by the edge whose blend they are (OCCT's own Generated), else by the first
    // selected edge of their group
    TopTools_IndexedMapOfShape baseImages;
    for (auto type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        for (TopExp_Explorer it(baseShape, type); it.More(); it.Next()) {
            const TopoDS_Shape& element = it.Current();
            auto images = imagesThrough(stages, 0, element);
            for (const auto& image : images) {
                baseImages.Add(image);
            }
            if (images.size() == 1 && images.front().IsSame(element)) {
                continue;
            }
            for (const auto& image : images) {
                mapper.insert(MappingStatus::Modified, element, image);
            }
        }
    }
    TopTools_IndexedMapOfShape named;
    auto generate = [&](const TopoDS_Shape& source, const TopoDS_Shape& toolFace) {
        for (const auto& image : imagesThrough(stages, 0, toolFace)) {
            if (image.ShapeType() == TopAbs_FACE && !baseImages.Contains(image)
                && !named.Contains(image)) {
                named.Add(image);
                mapper.insert(MappingStatus::Generated, source, image);
            }
        }
    };
    for (const auto& group : groups) {
        for (const auto& blend : group.blends) {
            generate(blend.first, blend.second);
        }
    }
    for (const auto& group : groups) {
        for (TopExp_Explorer it(group.tool, TopAbs_FACE); it.More(); it.Next()) {
            generate(group.selected.front(), it.Current());
        }
    }
    return shape;
}

thread_local Recorder* innermostRecorder = nullptr;

}  // namespace

bool reflexCircleCorner(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    gp_Pnt* corner
)
{
    try {
        TopTools_IndexedMapOfShape selected;
        for (const auto& edge : edges) {
            if (!edge.IsNull() && edge.ShapeType() == TopAbs_EDGE) {
                selected.Add(edge);
            }
        }
        TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
        TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
        TopExp::MapShapesAndUniqueAncestors(base, TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
        TopExp::MapShapesAndUniqueAncestors(base, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
        for (int i = 1; i <= vertexEdges.Extent(); ++i) {
            const TopoDS_Vertex& vertex = TopoDS::Vertex(vertexEdges.FindKey(i));
            const auto& around = vertexEdges(i);
            if (around.Extent() != 3) {
                continue;
            }
            std::vector<TopoDS_Edge> picked;
            for (const auto& edge : around) {
                if (selected.Contains(edge)) {
                    picked.push_back(TopoDS::Edge(edge));
                }
            }
            if (picked.size() != 2) {
                continue;
            }
            bool circle = false;
            for (const auto& edge : picked) {
                circle = circle || BRepAdaptor_Curve(edge).GetType() == GeomAbs_Circle;
            }
            if (!circle) {
                continue;
            }
            const auto* faces0 = edgeFaces.Seek(picked[0]);
            const auto* faces1 = edgeFaces.Seek(picked[1]);
            if (!faces0 || !faces1 || faces0->Extent() != 2 || faces1->Extent() != 2) {
                continue;
            }
            // Each edge's wall: its face that the other edge does not border
            TopoDS_Face walls[2];
            for (int k = 0; k < 2; ++k) {
                const auto* mine = k == 0 ? faces0 : faces1;
                const auto* theirs = k == 0 ? faces1 : faces0;
                for (const auto& face : *mine) {
                    bool sharedFace = false;
                    for (const auto& other : *theirs) {
                        sharedFace = sharedFace || other.IsSame(face);
                    }
                    if (!sharedFace) {
                        walls[k] = TopoDS::Face(face);
                    }
                }
            }
            if (walls[0].IsNull() || walls[1].IsNull()) {
                continue;
            }
            gp_Pnt point = BRep_Tool::Pnt(vertex);
            BRepAdaptor_Surface s0(walls[0], Standard_False);
            BRepAdaptor_Surface s1(walls[1], Standard_False);
            auto planeOrCylinder = [](const BRepAdaptor_Surface& s) {
                return s.GetType() == GeomAbs_Plane || s.GetType() == GeomAbs_Cylinder;
            };
            if (!planeOrCylinder(s0) || !planeOrCylinder(s1)) {
                continue;
            }
            gp_Dir away0 = awayFrom(picked[0], vertex);
            gp_Dir away1 = awayFrom(picked[1], vertex);
            if (away0.Dot(outwardNormal(walls[1], point)) > 1e-6
                && away1.Dot(outwardNormal(walls[0], point)) > 1e-6) {
                if (corner) {
                    *corner = point;
                }
                return true;
            }
        }
    }
    catch (const Refusal&) {
    }
    catch (const Standard_Failure&) {
    }
    return false;
}

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

bool endsInOverflow(
    const TopoDS_Shape& baseShape,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
)
{
    if (request.kind != Kind::Fillet) {
        return false;
    }
    try {
        const TopoShape base(baseShape);
        Context ctx(base, request);
        // With the edges OCCT's contour runs on to (request.contour): its fillet ends where they do
        for (const auto* list : {&edges, &request.contour}) {
            for (const auto& edge : *list) {
                if (!edge.IsNull() && edge.ShapeType() == TopAbs_EDGE) {
                    ctx.selected.Add(edge);
                }
            }
        }
        std::vector<EdgeData> data;
        for (int i = 1; i <= ctx.selected.Extent(); ++i) {
            // An edge the construction doesn't know is no overflowing end
            try {
                data.push_back(analyse(ctx, TopoDS::Edge(ctx.selected(i))));
            }
            catch (const Refusal&) {
            }
        }
        for (const auto& edgeData : data) {
            if (edgeData.closed) {
                continue;
            }
            TopoDS_Vertex vertices[2];
            TopExp::Vertices(edgeData.edge, vertices[0], vertices[1]);
            for (const auto& vertex : vertices) {
                try {
                    if (classify(ctx, data, edgeData, vertex).kind == VertexClass::Overflow) {
                        return true;
                    }
                }
                catch (const Refusal&) {
                }
            }
        }
    }
    catch (const Refusal&) {
    }
    catch (const Standard_Failure&) {
    }
    return false;
}

bool endsInCusp(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    std::vector<std::size_t>* which
)
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
    // Whether this edge ends in a cusp at one of its vertices
    auto cuspAtAnEnd = [&](const TopoDS_Shape& shape) {
        if (shape.ShapeType() != TopAbs_EDGE || !edgeFaces.Contains(shape)) {
            return false;
        }
        const TopoDS_Edge& edge = TopoDS::Edge(shape);
        const auto& faces = edgeFaces.FindFromKey(edge);
        if (faces.Extent() != 2 || BRep_Tool::Degenerated(edge)) {
            return false;
        }
        TopoDS_Vertex ends[2];
        TopExp::Vertices(edge, ends[0], ends[1]);
        if (ends[0].IsNull() || ends[1].IsNull() || ends[0].IsSame(ends[1])) {
            return false;
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
        return false;
    };
    bool any = false;
    for (std::size_t i = 0; i < edges.size(); ++i) {
        if (!cuspAtAnEnd(edges[i])) {
            continue;
        }
        if (!which) {
            return true;
        }
        which->push_back(i);
        any = true;
    }
    return any;
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

namespace
{
thread_local std::string invalidResultReason;
}

void noteInvalidResult(const std::string& reason)
{
    invalidResultReason = reason.empty() ? std::string("no reason given") : reason;
}

std::string takeInvalidResult()
{
    std::string reason;
    reason.swap(invalidResultReason);
    return reason;
}

namespace
{
/// +1 for an edge convex along its whole length, -1 for a concave one, 0 where it can't be told
/// (not between two faces, faces tangent there, or the sign changes along it)
int convexity(const TopTools_IndexedDataMapOfShapeListOfShape& edgeFaces, const TopoDS_Shape& shape)
{
    if (shape.ShapeType() != TopAbs_EDGE || !edgeFaces.Contains(shape)) {
        return 0;
    }
    const TopoDS_Edge& edge = TopoDS::Edge(shape);
    const auto& faces = edgeFaces.FindFromKey(edge);
    if (faces.Extent() != 2 || BRep_Tool::Degenerated(edge)) {
        return 0;
    }
    const TopoDS_Face& first = TopoDS::Face(faces.First());
    const TopoDS_Face& second = TopoDS::Face(faces.Last());
    BRepAdaptor_Curve curve(edge);
    int sign = 0;
    for (double at : {0.25, 0.5, 0.75}) {
        const double parameter
            = curve.FirstParameter() + at * (curve.LastParameter() - curve.FirstParameter());
        double turn = 0.0;
        try {
            turn = gp_Vec(inwardIn(second, edge, parameter))
                       .Dot(gp_Vec(outwardNormal(first, curve.Value(parameter))));
        }
        catch (const Refusal&) {
            return 0;
        }
        catch (const Standard_Failure&) {
            return 0;
        }
        if (std::abs(turn) < angularTolerance) {
            return 0;
        }
        const int here = turn < 0 ? 1 : -1;
        if (sign != 0 && here != sign) {
            return 0;
        }
        sign = here;
    }
    return sign;
}

/// Whether the face lies on a plane, cylinder, cone, sphere or torus: its volume integral is exact
bool analyticFace(const TopoDS_Shape& face)
{
    switch (BRepAdaptor_Surface(TopoDS::Face(face), Standard_False).GetType()) {
        case GeomAbs_Plane:
        case GeomAbs_Cylinder:
        case GeomAbs_Cone:
        case GeomAbs_Sphere:
        case GeomAbs_Torus:
            return true;
        default:
            return false;
    }
}

/// changedVolume() by the default integration, or the adaptive one. \a analytic: whether every
/// face that differs is analytic (analyticFace())
double changedVolumeBy(
    const TopoDS_Shape& before,
    const TopoDS_Shape& after,
    bool adaptive,
    bool& analytic
)
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
            const int j = others.FindIndex(face);
            if (j > 0 && others(j).IsEqual(face)) {
                continue;
            }
            analytic = analytic && analyticFace(face);
            builder.Add(changed, reversed ? face.Reversed() : face);
        }
    };
    analytic = true;
    addUnshared(now, old, false);
    addUnshared(old, now, true);
    if (!analytic) {
        return 0.0;
    }
    return adaptive ? MassProperties::volume(changed, true) : MassProperties::volume(changed);
}
}  // namespace

std::string wrongWay(
    const TopoDS_Shape& result,
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
)
{
    try {
        // One solid and nothing else: solids that share a face would count it from both sides,
        // and OCCT drops a base's faces outside its solids, which is no change of volume
        if (countSolids(base) != 1 || TopExp_Explorer(base, TopAbs_COMPSOLID).More()
            || TopExp_Explorer(base, TopAbs_FACE, TopAbs_SOLID).More()
            || countSolids(result) != 1
            || TopExp_Explorer(result, TopAbs_FACE, TopAbs_SOLID).More()) {
            return {};
        }
        TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
        TopExp::MapShapesAndUniqueAncestors(base, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
        int sign = 0;
        for (const auto* list : {&edges, &request.contour}) {
            for (const auto& edge : *list) {
                const int here = convexity(edgeFaces, edge);
                if (here == 0 || (sign != 0 && here != sign)) {
                    return {};
                }
                sign = here;
            }
        }
        if (sign == 0) {
            return {};
        }
        // A change smaller than the integration's error on the changed faces says nothing: a
        // billionth of the result's box, and 1e-6 mm3
        Bnd_Box box;
        BRepBndLib::Add(result, box);
        if (box.IsVoid()) {
            return {};
        }
        const double diagonal = std::sqrt(box.SquareExtent());
        const double tolerance = 1e-6 + 1e-9 * diagonal * diagonal * diagonal;
        // Convex edges (sign +1): the change must not be positive; concave: not negative
        auto wrong = [&](double change) {
            return sign * change > tolerance;
        };
        // Only where every face that differs is analytic: a free-form face's integral is off by
        // more than a small dress-up changes (MassProperties.h), a false alarm and seconds of time
        bool analytic = true;
        double change = changedVolumeBy(base, result, false, analytic);
        if (!analytic || !wrong(change)) {
            return {};
        }
        change = changedVolumeBy(base, result, true, analytic);
        if (!wrong(change)) {
            return {};
        }
        std::ostringstream text;
        text << (sign > 0 ? "adds" : "removes") << " material (volume " << (change > 0 ? "+" : "")
             << change << " mm3) where a dress-up of " << (sign > 0 ? "convex" : "concave")
             << " edges only " << (sign > 0 ? "removes" : "adds") << " it";
        return text.str();
    }
    catch (const Standard_Failure&) {
        return {};
    }
    catch (const Base::Exception&) {
        return {};
    }
    catch (const std::exception&) {
        return {};
    }
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

void Recorder::add(int edges, int corners, bool rolledOn)
{
    if (Recorder* recorder = innermostRecorder) {
        recorder->rolled = recorder->rolled || rolledOn;
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

/* Rim rounds built directly (ops#640, notes/boolean-free-mitre.md in the ops repository).
 *
 * Where the selection is whole loops of lines and circles on plane faces whose walls stand square
 * to them (planes and cylinders), the round is known without a Boolean. Each edge's round is a
 * torus about its arc's axis or a cylinder along its line. Two neighbours meet on the mitre: the
 * curve of points equally deep behind both walls, whose plan point at the depth d is the crossing
 * of the two walls' offsets at d and whose height above the round's centres is
 * sqrt(r^2 - (r - d)^2). Convex, reflex and tangent corners are that one formula: at a reflex
 * corner the offsets cross past the vertex, which is Onshape's run-on (fillet-tight-arc 8).
 *
 * The faces are assembled with shared edges and closed-form pcurves; the plane face and the walls
 * keep their surfaces and get their rim edges replaced. The result is then held to what the
 * definition gives by quadrature of closed forms (the removed volume, the rounds' area, the plane
 * face's area) and to BRepCheck. Any refusal sends the selection to the construction by Booleans.
 */
namespace
{

constexpr double rimTolerance = 1e-7;
/// The refusal of a rim whose rounds would meet another part of the body (Construction::rimBlocked)
const char* const rimReachRefusal
    = "a face that is neither the rim's plane face nor a wall within the round's reach";

/// A wall's outline in the plane face's own coordinates, in the loop's direction
struct RimCurve
{
    bool line = false;
    gp_XY point;  // a line: a point of it
    gp_XY direction;  // a line: along the loop
    gp_XY inward;  // a line: into the material
    gp_XY centre;  // a circle
    double rho = 0.0;
    int convex = 1;  // a circle: 1 where the material is on the centre's side, -1 where not
    int sense = 1;  // a circle: 1 where the loop runs counter-clockwise about the face's normal

    /// The radius of the offset at the depth d
    double radius(double d) const
    {
        return rho - convex * d;
    }
    gp_XY inwardAt(const gp_XY& p) const
    {
        if (line) {
            return inward;
        }
        gp_XY out = p - centre;
        out /= out.Modulus();
        return out * (-convex);
    }
    gp_XY tangentAt(const gp_XY& p) const
    {
        if (line) {
            return direction;
        }
        gp_XY out = p - centre;
        out /= out.Modulus();
        return gp_XY(-out.Y(), out.X()) * sense;
    }
    /// The curve's point next to p
    gp_XY nearest(const gp_XY& p) const
    {
        if (line) {
            gp_XY along = direction / direction.Modulus();
            return point + along * (p - point).Dot(along);
        }
        gp_XY out = p - centre;
        out /= out.Modulus();
        return centre + out * rho;
    }
};

/** A wall arc of a loop tighter than the round (C4 shape A, notes/fillet-tight-arc.md): its round
 * would be a spindle torus, and the corner's face is the canal surface of a ball of the arc's
 * radius rho whose centre S(theta) lies at r - rho from both neighbouring rounds' spines: in plan
 * at the inward depth r - (r - rho) cos(theta) from both neighbours' walls, at the height
 * (r - rho) sin(theta) above the rounds' centres, theta from 0 (S at the arc's centre) to 90 deg
 * (under the point where the neighbours' top edges cross). The patch's two sides are the
 * neighbouring rounds' ends: side k at theta is S + rho u_k, u_k the direction from neighbour k's
 * spine through S, which is that round's section at the angle theta (as tightTool(), whose tool
 * the construction by Booleans cuts with).
 */
struct RimTight
{
    PlanWall walls[2];  // the neighbours before and after, in the loop's plan
    double r = 0.0;
    double rho = 0.0;
    std::vector<gp_XY> table;  // S's plan points at even steps of theta, for the solver's start

    /// S's plan point at theta
    gp_XY spine(double theta) const
    {
        const int last = static_cast<int>(table.size()) - 1;
        int i = static_cast<int>(std::lround(theta / (pi / 2) * last));
        i = std::max(0, std::min(last, i));
        return solveCentre(walls, table[i], r - (r - rho) * std::cos(theta));
    }
    /// Side k's plan point at theta: on neighbour k's wall offset at the depth r (1 - cos(theta))
    gp_XY side(int k, double theta) const
    {
        gp_XY q = spine(theta);
        return q - walls[k].gradient(q) * (rho * std::cos(theta));
    }
    /// Side k's plan point at the depth d
    gp_XY sideAt(int k, double d) const
    {
        return side(k, std::acos(std::max(-1.0, std::min(1.0, 1.0 - d / r))));
    }
    void prepare(const gp_XY& centre, int intervals = 96)
    {
        table.resize(intervals + 1);
        gp_XY q = centre;
        for (int i = 0; i <= intervals; ++i) {
            q = solveCentre(walls, q, r - (r - rho) * std::cos(pi / 2 * i / intervals));
            table[i] = q;
        }
    }
};

/// A corner between two walls of a loop
struct RimCorner
{
    const RimCurve* before = nullptr;
    const RimCurve* after = nullptr;
    gp_XY vertex;
    bool tangent = false;
    gp_XY inward;
    // At an end of a tight wall arc: the neighbouring round ends on the corner patch's side
    const RimTight* tight = nullptr;
    int side = 0;

    /// Where the two walls' offsets at the depth d cross, on the branch through hint
    gp_XY at(double d, const gp_XY& hint) const
    {
        if (d < 0.0) {
            return vertex;
        }
        if (tight) {
            return tight->sideAt(side, d);
        }
        if (tangent) {
            return vertex + inward * d;
        }
        std::vector<gp_XY> found;
        auto offsetLine = [&](const RimCurve& c) {
            return c.point + c.inward * d;
        };
        if (before->line && after->line) {
            gp_XY p1 = offsetLine(*before);
            gp_XY p2 = offsetLine(*after);
            double den = before->direction.Crossed(after->direction);
            if (std::abs(den) < 1e-12) {
                refuse("a rim corner of parallel lines");
            }
            double k = (p2 - p1).Crossed(after->direction) / den;
            found.push_back(p1 + before->direction * k);
        }
        else if (before->line != after->line) {
            const RimCurve& l = before->line ? *before : *after;
            const RimCurve& c = before->line ? *after : *before;
            gp_XY p = offsetLine(l);
            double radius = c.radius(d);
            gp_XY w = p - c.centre;
            double b = w.Dot(l.direction);
            double disc = b * b - (w.SquareModulus() - radius * radius);
            if (radius <= 0.0 || disc < -1e-9 * std::max(1.0, radius * radius)) {
                refuse("rim offsets that do not cross");
            }
            double root = std::sqrt(std::max(disc, 0.0));
            found.push_back(p + l.direction * (-b + root));
            found.push_back(p + l.direction * (-b - root));
        }
        else {
            double r1 = before->radius(d);
            double r2 = after->radius(d);
            gp_XY w = after->centre - before->centre;
            double dist = w.Modulus();
            if (dist < 1e-12 || r1 <= 0.0 || r2 <= 0.0) {
                refuse("rim offsets that do not cross");
            }
            double a = (dist * dist + r1 * r1 - r2 * r2) / (2 * dist);
            double h2 = r1 * r1 - a * a;
            if (h2 < -1e-9 * std::max(1.0, r1 * r1)) {
                refuse("rim offsets that do not cross");
            }
            double h = std::sqrt(std::max(h2, 0.0));
            gp_XY u = w / dist;
            gp_XY n(-u.Y(), u.X());
            gp_XY foot = before->centre + u * a;
            found.push_back(foot + n * h);
            found.push_back(foot - n * h);
        }
        gp_XY best = found.front();
        for (const auto& q : found) {
            if ((q - hint).SquareModulus() < (best - hint).SquareModulus()) {
                best = q;
            }
        }
        return best;
    }
};

/// One rim edge of the base in its loop
struct RimMember
{
    TopoDS_Edge edge;  // as the base holds it, forward
    TopoDS_Face wall;
    TopoDS_Vertex start;  // in the loop's direction
    TopoDS_Vertex end;
    int along = 1;  // 1 where the loop runs with the edge's parameter
    double first = 0.0;
    double last = 0.0;
    TopoDS_Edge lowered;  // its curve r lower, on the wall and on the round
};

/// One round: consecutive rim edges on one circle or one line
struct RimRound
{
    RimCurve curve;
    std::vector<RimMember> members;
    gp_XY start;  // plan points of its ends on the wall
    gp_XY end;
    double sweep = 0.0;  // a circle: the wall arc's angle
    Handle(Geom_Surface) surface;
    // a circle: its torus's frame in the plan; a line: the cylinder's
    gp_XY xAxis;
    gp_Pnt origin;
    gp_Dir zAxis;
    TopoDS_Edge top;
    double topFirst = 0.0;
    double topLast = 0.0;
    TopoDS_Face face;
    // A wall arc tighter than the round: its face is a canal patch, and it has no top edge
    std::shared_ptr<RimTight> tight;
    // The top edge in pieces, in its parameter's order: cut where another loop of the plane face
    // touches it
    std::vector<TopoDS_Edge> tops;

    /// A plan point's angle about the torus's axis, pi at the middle of the wall arc
    double angle(const gp_XY& p) const
    {
        gp_XY w = p - curve.centre;
        gp_XY yAxis(-xAxis.Y(), xAxis.X());
        double a = std::atan2(w.Dot(yAxis), w.Dot(xAxis));
        return a < 0.0 ? a + 2 * pi : a;
    }
};

/// A vertex of a loop: lowered by r; a corner between two rounds also has a mitre
struct RimVertex
{
    TopoDS_Vertex vertex;
    gp_XY plan;
    double moved = 0.0;  // from the base's vertex to where its edges cross
    bool corner = false;
    RimCorner geometry;
    TopoDS_Edge upright;  // the base's edge down from it
    TopoDS_Edge shortened;
    TopoDS_Vertex lowered;
    TopoDS_Vertex onTop;
    gp_XY topPlan;
    TopoDS_Edge mitre;
};

struct RimLoop
{
    TopoDS_Face face;  // the plane face, as the base holds it
    TopoDS_Wire wire;
    gp_Pnt origin;
    gp_Dir normal;  // out of the material
    gp_Dir xDir;
    gp_Dir yDir;
    std::vector<RimRound> rounds;
    // rounds[i] runs from corners[i] to corners[i + 1]; inner[i]: the vertices within rounds[i]
    std::vector<RimVertex> corners;
    std::vector<std::vector<RimVertex>> inner;
    // How far the base's own data is from the loop the rounds follow: the sum over the corners of
    // the vertex's distance from its edges' crossing and, where the edges are tangent, of the
    // distance between them there (a Boolean leaves both at about 1e-6; a designed body at none)
    double slack = 0.0;
    double reach = 0.0;  // the corners' largest distance from their middle
    double height = 0.0;  // the longest edge down from a vertex

    gp_XY plan(const gp_Pnt& p) const
    {
        gp_Vec v(origin, p);
        return gp_XY(v.Dot(gp_Vec(xDir)), v.Dot(gp_Vec(yDir)));
    }
    gp_Pnt point(const gp_XY& p, double height) const
    {
        return origin.Translated(
            gp_Vec(xDir) * p.X() + gp_Vec(yDir) * p.Y() + gp_Vec(normal) * height
        );
    }
    gp_Vec vector(const gp_XY& p) const
    {
        return gp_Vec(xDir) * p.X() + gp_Vec(yDir) * p.Y();
    }
};

/// The parameter of the mitre's samples: the depth is r (1 - cos t)
double mitreAngle(double u, bool touching)
{
    // Where the offsets touch at the depth r (a horn round's spines), the plan point moves as the
    // square root of r - d: there r - d is made quadratic in the parameter at the end
    return (pi / 2) * (touching ? u * (2 - u) : u);
}

/// What the definition gives for one loop, by Simpson's rule over the depth of closed forms
struct RimExpected
{
    double volume = 0.0;  // removed
    double roundArea = 0.0;
    double band = 0.0;  // the plane face's loss
    // What the base's own data leaves open in the band and the volume (RimLoop::slack): the
    // loop's corners are that far from its curves, each with the loop's reach as its lever, and
    // OCCT's volume of a face whose loop is open by that much is off by as much times its height
    double bandSlack = 0.0;
    double volumeSlack = 0.0;
};

void rimTightMeasures(const RimLoop& loop, const RimRound& round, double r, double& area, double& lens);

RimExpected rimExpected(const RimLoop& loop, double r)
{
    const int steps = 512;
    const size_t n = loop.rounds.size();
    std::vector<gp_XY> hints(n);
    for (size_t i = 0; i < n; ++i) {
        hints[i] = loop.corners[i].plan;
    }
    // About the corners' middle: a corner beside its curve by e leaves the loop open by e, and
    // the area off by e times its distance from the point the area is taken about
    gp_XY middle(0.0, 0.0);
    for (size_t i = 0; i < n; ++i) {
        middle += loop.corners[i].plan / double(n);
    }
    auto measure = [&](double d, double& area, double& perimeter) {
        area = 0.0;
        perimeter = 0.0;
        std::vector<gp_XY> at(n);
        for (size_t i = 0; i < n; ++i) {
            at[i] = loop.corners[i].geometry.at(d, hints[i]);
            hints[i] = at[i];
        }
        for (size_t i = 0; i < n; ++i) {
            const RimRound& round = loop.rounds[i];
            const gp_XY& p = at[i];
            const gp_XY& q = at[(i + 1) % n];
            if (round.tight) {
                // The flat chord from one side of the patch to the other at this height; what
                // lies between the chords and the patch is measured on the patch below
                area += 0.5 * (p - middle).Crossed(q - middle);
                continue;
            }
            if (round.curve.line) {
                if ((q - p).Dot(round.curve.direction) <= rimTolerance) {
                    refuse("a rim round with no length");
                }
                area += 0.5 * (p - middle).Crossed(q - middle);
                perimeter += (q - p).Modulus();
                continue;
            }
            const gp_XY& c = round.curve.centre;
            double radius = round.curve.radius(d);
            double a1 = std::atan2(p.Y() - c.Y(), p.X() - c.X());
            double a2 = std::atan2(q.Y() - c.Y(), q.X() - c.X());
            // The offset's arc, the one next to the wall's
            double sweep = round.curve.sense * (a2 - a1);
            sweep -= 2 * pi * std::round((sweep - round.sweep) / (2 * pi));
            if (sweep <= 1e-9 || sweep >= 2 * pi - 1e-6 || radius <= 0.0) {
                refuse("a rim round with no length");
            }
            area += 0.5
                * (radius * radius * round.curve.sense * sweep + (c - middle).Crossed(q - p));
            perimeter += radius * sweep;
        }
    };
    double wallArea = 0.0;
    double wallPerimeter = 0.0;
    measure(0.0, wallArea, wallPerimeter);
    RimExpected expected;
    double volume = 0.0;
    double last = 0.0;
    for (int k = 0; k <= steps; ++k) {
        // In the parameter of the mitres where the offsets touch at the depth r: the perimeter
        // goes as the square root of r - d there, which Simpson's rule in t would not take
        double u = double(k) / steps;
        double t = mitreAngle(u, true);
        double dt = (pi / 2) * 2 * (1 - u);
        double d = r * (1 - std::cos(t));
        double area = 0.0;
        double perimeter = 0.0;
        if (k == 0) {
            area = wallArea;
            perimeter = wallPerimeter;
        }
        else {
            measure(d, area, perimeter);
        }
        double weight = (k == 0 || k == steps) ? 1.0 : (k % 2 == 1 ? 4.0 : 2.0);
        // A slice at the height r sin t loses the band between the wall and its offset
        volume += weight * (wallArea - area) * r * std::cos(t) * dt;
        expected.roundArea += weight * perimeter * r * dt;
        last = wallArea - area;
    }
    double h = 1.0 / steps / 3.0;
    expected.volume = std::abs(volume * h);
    expected.roundArea *= h;
    expected.band = std::abs(last);
    for (const auto& round : loop.rounds) {
        if (!round.tight) {
            continue;
        }
        // Beyond the chords: the wall arc's segment over the round's height, less what stays
        // between the chords and the patch
        const double rho = round.curve.rho;
        const double segment = 0.5 * rho * rho * (round.sweep - std::sin(round.sweep));
        double area = 0.0;
        double lens = 0.0;
        rimTightMeasures(loop, round, r, area, lens);
        expected.band += segment;
        expected.volume += r * segment - lens;
        expected.roundArea += area;
    }
    expected.bandSlack = loop.slack * loop.reach;
    expected.volumeSlack = loop.slack * loop.reach * (r + loop.height);
    return expected;
}

/// A round's top edge in the plan: a segment or an arc from p to q
struct RimPiece
{
    bool line = false;
    gp_XY p;
    gp_XY q;
    gp_XY centre;
    double radius = 0.0;
    int sense = 1;
    double sweep = 0.0;

    bool holds(const gp_XY& x) const
    {
        const double slack = 1e-7;
        if (line) {
            gp_XY d = q - p;
            double length = d.Modulus();
            double along = (x - p).Dot(d) / length;
            return std::abs((x - p).Crossed(d)) / length < slack && along > -slack
                && along < length + slack;
        }
        gp_XY w = x - centre;
        if (std::abs(w.Modulus() - radius) > slack) {
            return false;
        }
        double from = std::atan2(p.Y() - centre.Y(), p.X() - centre.X());
        double turn = sense * (std::atan2(w.Y(), w.X()) - from);
        turn -= 2 * pi * std::floor(turn / (2 * pi));
        double slackAngle = slack / radius;
        return turn < sweep + slackAngle || turn > 2 * pi - slackAngle;
    }
    /// Whether a point beside the piece's curve lies between its ends
    bool spans(const gp_XY& x) const
    {
        const double slack = 1e-7;
        if (line) {
            gp_XY d = q - p;
            double length = d.Modulus();
            double along = (x - p).Dot(d) / length;
            return along > -slack && along < length + slack;
        }
        gp_XY w = x - centre;
        double from = std::atan2(p.Y() - centre.Y(), p.X() - centre.X());
        double turn = sense * (std::atan2(w.Y(), w.X()) - from);
        turn -= 2 * pi * std::floor(turn / (2 * pi));
        double slackAngle = slack / radius;
        return turn < sweep + slackAngle || turn > 2 * pi - slackAngle;
    }
    bool endsAt(const gp_XY& x) const
    {
        return (x - p).Modulus() < 1e-6 || (x - q).Modulus() < 1e-6;
    }
};

/// Whether two top edges meet anywhere but at an end they share
bool rimPiecesCross(const RimPiece& a, const RimPiece& b)
{
    const double slack = 1e-7;
    std::vector<gp_XY> found;
    if (a.line && b.line) {
        gp_XY da = a.q - a.p;
        gp_XY db = b.q - b.p;
        double den = da.Crossed(db);
        if (std::abs(den) < 1e-12 * da.Modulus() * db.Modulus()) {
            if (std::abs((b.p - a.p).Crossed(da)) / da.Modulus() > slack) {
                return false;
            }
            // On one line: they may share an end, no more
            double length = da.Modulus();
            double from = (b.p - a.p).Dot(da) / length;
            double to = (b.q - a.p).Dot(da) / length;
            double overlap = std::min(std::max(from, to), length) - std::max(std::min(from, to), 0.0);
            return overlap > 1e-6;
        }
        found.push_back(a.p + da * ((b.p - a.p).Crossed(db) / den));
    }
    else if (a.line != b.line) {
        const RimPiece& l = a.line ? a : b;
        const RimPiece& c = a.line ? b : a;
        gp_XY d = l.q - l.p;
        d /= d.Modulus();
        gp_XY w = l.p - c.centre;
        double half = w.Dot(d);
        double disc = half * half - (w.SquareModulus() - c.radius * c.radius);
        if (disc < -2 * slack * c.radius) {
            return false;
        }
        double root = std::sqrt(std::max(disc, 0.0));
        found.push_back(l.p + d * (-half + root));
        found.push_back(l.p + d * (-half - root));
    }
    else {
        gp_XY w = b.centre - a.centre;
        double dist = w.Modulus();
        if (dist < slack) {
            if (std::abs(a.radius - b.radius) > slack) {
                return false;
            }
            // On one circle: they may share an end, no more
            for (const auto& x : {b.p, b.q}) {
                if (a.holds(x) && !a.endsAt(x)) {
                    return true;
                }
            }
            for (const auto& x : {a.p, a.q}) {
                if (b.holds(x) && !b.endsAt(x)) {
                    return true;
                }
            }
            return a.endsAt(b.p) && a.endsAt(b.q) && a.sense == b.sense;
        }
        double along = (dist * dist + a.radius * a.radius - b.radius * b.radius) / (2 * dist);
        double h2 = a.radius * a.radius - along * along;
        if (h2 < -2 * slack * a.radius) {
            return false;
        }
        double h = std::sqrt(std::max(h2, 0.0));
        gp_XY u = w / dist;
        gp_XY n(-u.Y(), u.X());
        gp_XY foot = a.centre + u * along;
        found.push_back(foot + n * h);
        found.push_back(foot - n * h);
    }
    for (const auto& x : found) {
        if (!a.holds(x) || !b.holds(x) || (a.endsAt(x) && b.endsAt(x))) {
            continue;
        }
        // Pieces that touch at an end they share (a horn round's top edge and its neighbour's)
        // may cross once more beside it by the last digits of their data: no crossing while they
        // stay within the tolerance of each other from that end to there (the sagitta of both)
        bool grazing = false;
        for (const auto& end : {a.p, a.q}) {
            if (!b.endsAt(end)) {
                continue;
            }
            // (an arc of less than three quarters of a turn does not come back to its start)
            double chord = (x - end).Modulus();
            double bend = (a.line ? 0.0 : 1 / a.radius) + (b.line ? 0.0 : 1 / b.radius);
            grazing = grazing
                || ((a.line || a.sweep < 1.5 * pi) && (b.line || b.sweep < 1.5 * pi)
                    && chord * chord / 8 * bend < slack);
        }
        if (!grazing) {
            return true;
        }
    }
    return false;
}

/// Where a round's top edge meets an edge of another loop of its plane face: the points where
/// they touch (tangent within 1e-6); true where they cross or run along each other
bool rimContacts(const RimPiece& a, const RimPiece& b, std::vector<gp_XY>& touching)
{
    const double touch = 1e-6;
    auto both = [&](const gp_XY& x) {
        return a.spans(x) && b.spans(x);
    };
    if (a.line && b.line) {
        gp_XY da = a.q - a.p;
        gp_XY db = b.q - b.p;
        double den = da.Crossed(db);
        if (std::abs(den) < 1e-12 * da.Modulus() * db.Modulus()) {
            if (std::abs((b.p - a.p).Crossed(da)) / da.Modulus() > touch) {
                return false;
            }
            double length = da.Modulus();
            double from = (b.p - a.p).Dot(da) / length;
            double to = (b.q - a.p).Dot(da) / length;
            return std::min(std::max(from, to), length) - std::max(std::min(from, to), 0.0) > -touch;
        }
        return both(a.p + da * ((b.p - a.p).Crossed(db) / den));
    }
    if (a.line != b.line) {
        const RimPiece& l = a.line ? a : b;
        const RimPiece& c = a.line ? b : a;
        gp_XY d = l.q - l.p;
        d /= d.Modulus();
        gp_XY foot = l.p - d * (l.p - c.centre).Dot(d);
        double dist = (foot - c.centre).Modulus();
        if (std::abs(dist - c.radius) <= touch) {
            if (both(foot)) {
                touching.push_back(foot);
            }
            return false;
        }
        if (dist > c.radius) {
            return false;
        }
        double root = std::sqrt(c.radius * c.radius - dist * dist);
        return both(foot + d * root) || both(foot - d * root);
    }
    gp_XY w = b.centre - a.centre;
    double dist = w.Modulus();
    if (dist < touch) {
        return std::abs(a.radius - b.radius) <= touch
            && (b.spans(a.p) || b.spans(a.q) || a.spans(b.p) || a.spans(b.q));
    }
    gp_XY u = w / dist;
    if (std::abs(dist - (a.radius + b.radius)) <= touch) {
        gp_XY x = a.centre + u * a.radius;
        if (both(x)) {
            touching.push_back(x);
        }
        return false;
    }
    if (std::abs(dist - std::abs(a.radius - b.radius)) <= touch) {
        gp_XY x = a.centre + u * (a.radius > b.radius ? a.radius : -a.radius);
        if (both(x)) {
            touching.push_back(x);
        }
        return false;
    }
    if (dist > a.radius + b.radius || dist < std::abs(a.radius - b.radius)) {
        return false;
    }
    double along = (dist * dist + a.radius * a.radius - b.radius * b.radius) / (2 * dist);
    double h = std::sqrt(std::max(a.radius * a.radius - along * along, 0.0));
    gp_XY n(-u.Y(), u.X());
    gp_XY foot = a.centre + u * along;
    return both(foot + n * h) || both(foot - n * h);
}

/// An edge of another loop of a rim's plane face (a hole's rim that is not rounded), in the plan
struct RimOther
{
    TopoDS_Edge edge;  // as the base holds it, forward
    TopoDS_Wire wire;
    RimPiece piece;
    double first = 0.0;
    double last = 0.0;
    gp_Circ circle;
    gp_Lin line;

    /// The edge's parameter at a point of it
    double parameter(const gp_Pnt& point) const
    {
        if (piece.line) {
            return ElCLib::Parameter(line, point);
        }
        double u = ElCLib::Parameter(circle, point);
        return u + 2 * pi * std::round(((first + last) / 2 - u) / (2 * pi));
    }
    double scale() const
    {
        return piece.line ? 1.0 : piece.radius;
    }
};

/// Where a round's top edge touches another loop of its plane face: one vertex of both
struct RimPinch
{
    TopoDS_Edge edge;  // the other loop's
    TopoDS_Wire wire;
    double onEdge = 0.0;
    bool atEnd = false;  // at a vertex the edge has
    TopoDS_Vertex vertex;
};

Handle(Geom2d_Curve) uvLine(double u, double v, double du, double dv)
{
    return new Geom2d_Line(gp_Pnt2d(u, v), gp_Dir2d(du, dv));
}

TopoDS_Vertex rimVertex(const gp_Pnt& p, double tolerance = Precision::Confusion())
{
    TopoDS_Vertex vertex;
    BRep_Builder().MakeVertex(vertex, p, std::max(tolerance, Precision::Confusion()));
    return vertex;
}

/// An edge on a curve between two vertices, the first at the lower parameter
TopoDS_Edge rimEdge(
    const Handle(Geom_Curve)& curve,
    double first,
    double last,
    const TopoDS_Vertex& atFirst,
    const TopoDS_Vertex& atLast,
    double tolerance = Precision::Confusion()
)
{
    BRep_Builder builder;
    TopoDS_Edge edge;
    builder.MakeEdge(edge, curve, tolerance);
    builder.Add(edge, atFirst.Oriented(TopAbs_FORWARD));
    builder.Add(edge, atLast.Oriented(TopAbs_REVERSED));
    builder.Range(edge, first, last);
    return edge;
}

PlanWall rimPlanWall(const RimCurve& curve);

/// The loops of the selection, or a refusal where it is not whole loops on plane faces
std::vector<RimLoop> rimLoops(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    double r,
    const TopTools_IndexedDataMapOfShapeListOfShape& edgeFaces,
    const TopTools_IndexedDataMapOfShapeListOfShape& vertexEdges
)
{
    TopTools_IndexedMapOfShape selected;
    for (const auto& edge : edges) {
        if (edge.IsNull() || edge.ShapeType() != TopAbs_EDGE) {
            refuse("a selection that is not an edge");
        }
        selected.Add(edge);
    }
    TopTools_IndexedMapOfShape covered;
    TopTools_IndexedMapOfShape cornerVertices;
    std::vector<RimLoop> loops;
    for (TopExp_Explorer faces(base, TopAbs_FACE); faces.More(); faces.Next()) {
        const TopoDS_Face& face = TopoDS::Face(faces.Current());
        BRepAdaptor_Surface surface(face);
        if (surface.GetType() != GeomAbs_Plane) {
            continue;
        }
        for (TopoDS_Iterator wires(face); wires.More(); wires.Next()) {
            if (wires.Value().ShapeType() != TopAbs_WIRE) {
                continue;
            }
            const TopoDS_Wire& wire = TopoDS::Wire(wires.Value());
            int all = 0;
            int picked = 0;
            for (TopoDS_Iterator it(wire); it.More(); it.Next()) {
                ++all;
                picked += selected.Contains(it.Value()) ? 1 : 0;
            }
            if (picked == 0 || picked != all) {
                continue;
            }
            RimLoop loop;
            loop.face = face;
            loop.wire = wire;
            gp_Pln plane = surface.Plane();
            loop.origin = plane.Location();
            loop.normal = plane.Axis().Direction();
            if (face.Orientation() == TopAbs_REVERSED) {
                loop.normal.Reverse();
            }
            gp_Ax3 frame(loop.origin, loop.normal);
            loop.xDir = frame.XDirection();
            loop.yDir = frame.YDirection();
            // The members, in the loop's order
            std::vector<RimMember> members;
            std::vector<RimCurve> curves;
            for (BRepTools_WireExplorer it(wire, face); it.More(); it.Next()) {
                RimMember member;
                member.edge = TopoDS::Edge(it.Current().Oriented(TopAbs_FORWARD));
                if (covered.Contains(member.edge)) {
                    refuse("a rim edge on two selected loops");
                }
                covered.Add(member.edge);
                TopoDS_Vertex forward;
                TopoDS_Vertex reversed;
                TopExp::Vertices(member.edge, forward, reversed);
                if (forward.IsNull() || reversed.IsNull() || forward.IsSame(reversed)) {
                    refuse("a closed rim edge");
                }
                member.start = it.CurrentVertex();
                if (member.start.IsSame(forward)) {
                    member.along = 1;
                    member.end = reversed;
                }
                else if (member.start.IsSame(reversed)) {
                    member.along = -1;
                    member.end = forward;
                }
                else {
                    refuse("a rim loop that does not chain");
                }
                const TopTools_ListOfShape& owners = edgeFaces.FindFromKey(member.edge);
                if (owners.Extent() != 2) {
                    refuse("a rim edge without two faces");
                }
                for (const auto& owner : owners) {
                    if (!owner.IsSame(face)) {
                        member.wall = TopoDS::Face(owner);
                    }
                }
                if (member.wall.IsNull()) {
                    refuse("a rim edge whose faces are one");
                }
                BRepAdaptor_Curve curve(member.edge);
                member.first = curve.FirstParameter();
                member.last = curve.LastParameter();
                gp_Pnt mid = curve.Value((member.first + member.last) / 2);
                // The wall stands square to the plane face; its outward normal at the edge's
                // middle points away from the material
                BRepAdaptor_Surface wall(member.wall);
                double f = 0.0;
                double l = 0.0;
                Handle(Geom2d_Curve) onWall
                    = BRep_Tool::CurveOnSurface(member.edge, member.wall, f, l);
                if (onWall.IsNull()) {
                    refuse("a rim edge without a curve on its wall");
                }
                gp_Pnt2d uv = onWall->Value((f + l) / 2);
                gp_Pnt at;
                gp_Vec du;
                gp_Vec dv;
                wall.D1(uv.X(), uv.Y(), at, du, dv);
                gp_Vec outward = du.Crossed(dv);
                if (outward.Magnitude() < 1e-12) {
                    refuse("a wall without a normal");
                }
                outward.Normalize();
                if (member.wall.Orientation() == TopAbs_REVERSED) {
                    outward.Reverse();
                }
                if (std::abs(outward.Dot(gp_Vec(loop.normal))) > angularTolerance) {
                    refuse("a rim wall that is not square to its plane face");
                }
                RimCurve c;
                gp_XY inward(-outward.Dot(gp_Vec(loop.xDir)), -outward.Dot(gp_Vec(loop.yDir)));
                if (curve.GetType() == GeomAbs_Line && wall.GetType() == GeomAbs_Plane) {
                    gp_Lin line = curve.Line();
                    c.line = true;
                    c.point = loop.plan(line.Location());
                    gp_Vec d(line.Direction());
                    c.direction = gp_XY(d.Dot(gp_Vec(loop.xDir)), d.Dot(gp_Vec(loop.yDir)))
                        * member.along;
                    c.inward = inward;
                }
                else if (curve.GetType() == GeomAbs_Circle && wall.GetType() == GeomAbs_Cylinder) {
                    gp_Circ circle = curve.Circle();
                    if (!parallel(circle.Axis().Direction(), loop.normal)
                        || !parallel(wall.Cylinder().Axis().Direction(), loop.normal)) {
                        refuse("a rim arc whose axis is not the plane face's normal");
                    }
                    c.centre = loop.plan(circle.Location());
                    c.rho = circle.Radius();
                    gp_XY toCentre = c.centre - loop.plan(mid);
                    c.convex = toCentre.Dot(inward) > 0 ? 1 : -1;
                    double turn = circle.Axis().Direction().Dot(loop.normal) > 0 ? 1.0 : -1.0;
                    c.sense = turn * member.along > 0 ? 1 : -1;
                }
                else {
                    refuse("a rim edge that is neither a line on a plane nor a circle on a cylinder");
                }
                members.push_back(member);
                curves.push_back(c);
            }
            const size_t count = members.size();
            if (count < 2) {
                refuse("a rim loop of one edge");
            }
            // Consecutive edges on one circle or line are one round (a circle split at a seam)
            auto same = [&](const RimCurve& a, const RimCurve& b) {
                if (a.line != b.line) {
                    return false;
                }
                if (a.line) {
                    return std::abs(a.direction.Crossed(b.direction)) < angularTolerance
                        && a.direction.Dot(b.direction) > 0
                        && std::abs((b.point - a.point).Crossed(a.direction)) < rimTolerance;
                }
                return (a.centre - b.centre).Modulus() < rimTolerance
                    && std::abs(a.rho - b.rho) < rimTolerance && a.convex == b.convex
                    && a.sense == b.sense;
            };
            size_t begin = count;
            for (size_t i = 0; i < count; ++i) {
                if (!same(curves[(i + count - 1) % count], curves[i])) {
                    begin = i;
                    break;
                }
            }
            if (begin == count) {
                refuse("a rim loop on one circle");
            }
            for (size_t k = 0; k < count; ++k) {
                size_t i = (begin + k) % count;
                RimVertex vertex;
                vertex.vertex = members[i].start;
                vertex.plan = loop.plan(BRep_Tool::Pnt(vertex.vertex));
                if (cornerVertices.Contains(vertex.vertex)) {
                    refuse("a vertex on two rim loops");
                }
                cornerVertices.Add(vertex.vertex);
                if (k == 0 || !same(curves[(i + count - 1) % count], curves[i])) {
                    RimRound round;
                    round.curve = curves[i];
                    round.start = vertex.plan;
                    loop.rounds.push_back(round);
                    vertex.corner = true;
                    loop.corners.push_back(vertex);
                    loop.inner.emplace_back();
                }
                else {
                    loop.inner.back().push_back(vertex);
                }
                RimRound& round = loop.rounds.back();
                round.members.push_back(members[i]);
                round.end = loop.plan(BRep_Tool::Pnt(members[i].end));
                if (!round.curve.line) {
                    round.sweep += std::abs(members[i].last - members[i].first);
                }
            }
            if (loop.rounds.size() < 2) {
                refuse("a rim loop on one circle");
            }
            for (size_t i = 0; i < loop.rounds.size(); ++i) {
                RimRound& round = loop.rounds[i];
                if (!round.curve.line) {
                    if (round.sweep >= 2 * pi - 1e-6) {
                        refuse("a rim arc of a full turn");
                    }
                    // A spindle torus (the wall arc tighter than twice the round) crosses itself.
                    // Tighter than the round itself (tightArc()): a canal patch instead
                    if (round.curve.convex > 0 && round.curve.rho - r < r - 1e-9 * r) {
                        if (round.curve.rho >= r - linearTolerance) {
                            refuse("a rim arc tighter than twice the round");
                        }
                        if (round.sweep >= pi - 1e-9) {
                            refuse("a wall arc tighter than the round spanning a half circle or more");
                        }
                        round.tight = std::make_shared<RimTight>();
                    }
                }
                RimVertex& corner = loop.corners[i];
                const RimRound& before
                    = loop.rounds[(i + loop.rounds.size() - 1) % loop.rounds.size()];
                gp_XY t1 = before.curve.tangentAt(corner.plan);
                gp_XY t2 = round.curve.tangentAt(corner.plan);
                corner.geometry.vertex = corner.plan;
                if (std::abs(t1.Crossed(t2)) < 1e-7) {
                    gp_XY n1 = before.curve.inwardAt(corner.plan);
                    gp_XY n2 = round.curve.inwardAt(corner.plan);
                    if (t1.Dot(t2) < 0 || n1.Dot(n2) < 0) {
                        refuse("a rim corner that is a cusp");
                    }
                    corner.geometry.tangent = true;
                    corner.geometry.inward = n1;
                }
            }
            for (size_t i = 0; i < loop.rounds.size(); ++i) {
                if (!loop.rounds[i].tight) {
                    continue;
                }
                const size_t n = loop.rounds.size();
                if (n < 3 || !loop.corners[i].geometry.tangent
                    || !loop.corners[(i + 1) % n].geometry.tangent) {
                    refuse("a wall arc tighter than the round that does not continue tangentially "
                           "at both ends");
                }
                if (loop.rounds[(i + n - 1) % n].tight || loop.rounds[(i + 1) % n].tight) {
                    refuse("two wall arcs tighter than the round in a row");
                }
            }
            loops.push_back(std::move(loop));
        }
    }
    if (loops.empty() || covered.Extent() != selected.Extent()) {
        refuse("a selection that is not whole loops on plane faces");
    }
    // The corners' geometry points into the rounds, which no longer move
    for (auto& loop : loops) {
        const size_t n = loop.rounds.size();
        for (size_t i = 0; i < n; ++i) {
            loop.corners[i].geometry.before = &loop.rounds[(i + n - 1) % n].curve;
            loop.corners[i].geometry.after = &loop.rounds[i].curve;
        }
    }
    // A corner is where its two edges cross: a vertex may stand beside that by its tolerance (a
    // Boolean's by 1e-6), and the rounds and their mitres follow the edges
    for (auto& loop : loops) {
        const size_t n = loop.rounds.size();
        for (size_t i = 0; i < n; ++i) {
            RimVertex& corner = loop.corners[i];
            RimCorner& g = corner.geometry;
            gp_XY exact = g.tangent ? g.after->nearest(corner.plan) : g.at(0.0, corner.plan);
            double moved = (exact - corner.plan).Modulus();
            if (!(moved <= 10 * rimTolerance)) {
                refuse("a rim vertex away from where its edges cross");
            }
            corner.moved = moved;
            corner.plan = exact;
            g.vertex = exact;
            loop.rounds[i].start = exact;
            loop.rounds[(i + n - 1) % n].end = exact;
            loop.slack += moved + (g.tangent ? (g.before->nearest(exact) - exact).Modulus() : 0.0);
        }
        gp_XY middle(0.0, 0.0);
        for (size_t i = 0; i < n; ++i) {
            middle += loop.corners[i].plan / double(n);
        }
        for (size_t i = 0; i < n; ++i) {
            loop.reach = std::max(loop.reach, (loop.corners[i].plan - middle).Modulus());
        }
        // The tight wall arcs' centre curves, between their neighbours' walls
        for (size_t i = 0; i < n; ++i) {
            RimRound& round = loop.rounds[i];
            if (!round.tight) {
                continue;
            }
            RimTight& tight = *round.tight;
            tight.walls[0] = rimPlanWall(loop.rounds[(i + n - 1) % n].curve);
            tight.walls[1] = rimPlanWall(loop.rounds[(i + 1) % n].curve);
            tight.r = r;
            tight.rho = round.curve.rho;
            tight.prepare(round.curve.centre);
            loop.corners[i].geometry.tight = &tight;
            loop.corners[i].geometry.side = 0;
            loop.corners[(i + 1) % n].geometry.tight = &tight;
            loop.corners[(i + 1) % n].geometry.side = 1;
        }
    }
    // Each vertex: three edges, the third straight down from the plane face and longer than r,
    // its other end not a rim vertex. A vertex within one round may have its two rim edges alone
    // (an arc a Boolean left in two pieces on one wall): it is lowered, and nothing goes down
    auto upright = [&](RimLoop& loop, RimVertex& vertex, bool within) {
        const TopTools_ListOfShape& around = vertexEdges.FindFromKey(vertex.vertex);
        if (within && around.Extent() == 2) {
            for (const auto& edge : around) {
                if (!selected.Contains(edge)) {
                    refuse("a rim vertex with an unselected rim edge");
                }
            }
            vertex.lowered
                = rimVertex(
            loop.point(vertex.plan, -r),
            std::max(BRep_Tool::Tolerance(vertex.vertex), 2 * vertex.moved)
        );
            return;
        }
        if (around.Extent() != 3) {
            refuse("a rim vertex without three edges");
        }
        for (const auto& edge : around) {
            if (selected.Contains(edge)) {
                continue;
            }
            if (!vertex.upright.IsNull()) {
                refuse("a rim vertex with an unselected rim edge");
            }
            vertex.upright = TopoDS::Edge(edge.Oriented(TopAbs_FORWARD));
        }
        if (vertex.upright.IsNull()) {
            refuse("a rim vertex without an edge down from it");
        }
        BRepAdaptor_Curve curve(vertex.upright);
        if (curve.GetType() != GeomAbs_Line || !parallel(curve.Line().Direction(), loop.normal)) {
            refuse("the edge down from a rim vertex is not square to the plane face");
        }
        TopoDS_Vertex forward;
        TopoDS_Vertex reversed;
        TopExp::Vertices(vertex.upright, forward, reversed);
        if (forward.IsNull() || reversed.IsNull() || forward.IsSame(reversed)) {
            refuse("the edge down from a rim vertex is closed");
        }
        const TopoDS_Vertex& other = forward.IsSame(vertex.vertex) ? reversed : forward;
        if (cornerVertices.Contains(other)) {
            refuse("an edge between two rim loops");
        }
        if (gp_Vec(BRep_Tool::Pnt(vertex.vertex), BRep_Tool::Pnt(other)).Dot(gp_Vec(loop.normal))
            >= 0) {
            refuse("a rim whose walls rise from its plane face");
        }
        double length = curve.LastParameter() - curve.FirstParameter();
        if (length < r + 1000 * rimTolerance) {
            refuse("a wall no higher than the round");
        }
        loop.height = std::max(loop.height, length);
        bool atFirst = forward.IsSame(vertex.vertex);
        double keepFirst = atFirst ? curve.FirstParameter() + r : curve.FirstParameter();
        double keepLast = atFirst ? curve.LastParameter() : curve.LastParameter() - r;
        // (with the base vertex's tolerance: its edges' curves end within that of it)
        vertex.lowered = rimVertex(
            loop.point(vertex.plan, -r),
            std::max(BRep_Tool::Tolerance(vertex.vertex), 2 * vertex.moved)
        );
        BRep_Builder builder;
        TopoDS_Edge shorter = TopoDS::Edge(vertex.upright.EmptyCopied());
        shorter.Orientation(TopAbs_FORWARD);
        builder.Add(shorter, (atFirst ? vertex.lowered : forward).Oriented(TopAbs_FORWARD));
        builder.Add(shorter, (atFirst ? reversed : vertex.lowered).Oriented(TopAbs_REVERSED));
        builder.Range(shorter, keepFirst, keepLast);
        vertex.shortened = shorter;
    };
    for (auto& loop : loops) {
        for (auto& corner : loop.corners) {
            upright(loop, corner, false);
        }
        for (auto& list : loop.inner) {
            for (auto& vertex : list) {
                upright(loop, vertex, true);
            }
        }
    }
    return loops;
}

/// Whether some corner of the loops is a reflex corner with a circle (reflexCircleCorner())
bool rimReflexCircle(const std::vector<RimLoop>& loops)
{
    for (const auto& loop : loops) {
        for (const auto& corner : loop.corners) {
            const RimCorner& g = corner.geometry;
            if (!g.tangent && (!g.before->line || !g.after->line)
                && g.after->tangentAt(g.vertex).Dot(g.before->inwardAt(g.vertex)) < 0) {
                return true;
            }
        }
    }
    return false;
}

/// Whether some round of the loops is a wall arc tighter than the round (preferConstruction())
bool rimTightArc(const std::vector<RimLoop>& loops)
{
    for (const auto& loop : loops) {
        for (const auto& round : loop.rounds) {
            if (round.tight) {
                return true;
            }
        }
    }
    return false;
}

/// A mitre's edge with its curves on both rounds, held to the formula between its samples
void rimMitre(RimLoop& loop, size_t index, double r)
{
    const size_t n = loop.rounds.size();
    RimVertex& corner = loop.corners[index];
    const RimRound* rounds[2] = {&loop.rounds[(index + n - 1) % n], &loop.rounds[index]};
    // Whether the offsets touch where they reach the plane face
    bool touching = false;
    {
        gp_XY hint = corner.plan;
        gp_XY top = corner.plan;
        for (int k = 1; k <= 64; ++k) {
            top = corner.geometry.at(r * (1 - std::cos((pi / 2) * k / 64)), hint);
            hint = top;
        }
        corner.topPlan = top;
        if (!corner.geometry.tangent) {
            gp_XY t1 = rounds[0]->curve.tangentAt(top);
            gp_XY t2 = rounds[1]->curve.tangentAt(top);
            touching = std::abs(t1.Crossed(t2)) < 0.3;
        }
    }
    auto uvOn = [&](const RimRound& round, const gp_XY& p, double t) {
        if (round.curve.line) {
            gp_Pnt at = loop.point(p, 0.0);
            return gp_Pnt2d(t, gp_Vec(round.origin, at).Dot(gp_Vec(round.zAxis)));
        }
        return gp_Pnt2d(round.angle(p), round.curve.convex > 0 ? t : pi - t);
    };
    double least = std::numeric_limits<double>::max();
    // Finer until the curve is within the tolerance; where the offsets nearly touch it converges
    // slowly, and the finest is taken within ten times that, the edge's tolerance saying so
    const std::pair<int, double> tries[]
        = {{49, rimTolerance}, {97, rimTolerance}, {193, rimTolerance}, {385, rimTolerance}, {769, 10 * rimTolerance}};
    for (const auto& [samples, allowed] : tries) {
        Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, samples);
        Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, samples);
        Handle(TColgp_HArray1OfPnt2d) uv[2] = {
            new TColgp_HArray1OfPnt2d(1, samples),
            new TColgp_HArray1OfPnt2d(1, samples)
        };
        std::vector<gp_XY> plan(samples);
        gp_XY hint = corner.plan;
        for (int k = 0; k < samples; ++k) {
            double u = double(k) / (samples - 1);
            double t = mitreAngle(u, touching);
            gp_XY p = corner.geometry.at(r * (1 - std::cos(t)), hint);
            hint = p;
            plan[k] = p;
            parameters->SetValue(k + 1, u);
            points->SetValue(k + 1, loop.point(p, -r + r * std::sin(t)));
            for (int side = 0; side < 2; ++side) {
                uv[side]->SetValue(k + 1, uvOn(*rounds[side], p, t));
            }
        }
        GeomAPI_Interpolate interpolate(points, parameters, false, Precision::Confusion());
        interpolate.Perform();
        if (!interpolate.IsDone()) {
            refuse("a mitre's curve could not be interpolated");
        }
        Handle(Geom_Curve) curve = interpolate.Curve();
        Handle(Geom2d_Curve) onRound[2];
        for (int side = 0; side < 2; ++side) {
            Geom2dAPI_Interpolate flat(uv[side], parameters, false, Precision::Confusion());
            flat.Perform();
            if (!flat.IsDone()) {
                refuse("a mitre's curve on its round could not be interpolated");
            }
            onRound[side] = flat.Curve();
        }
        // Between the samples and at both ends: the curve and its images on both rounds against
        // the formula
        double deviation = 0.0;
        for (int k = -1; k <= samples; ++k) {
            double u = k < 0 ? 0.0 : k == samples ? 1.0 : (k + 0.5) / (samples - 1);
            if (k == samples - 1) {
                continue;
            }
            double t = mitreAngle(u, touching);
            gp_XY p = corner.geometry.at(
                r * (1 - std::cos(t)),
                plan[std::min(std::max(k, 0), samples - 1)]
            );
            gp_Pnt exact = loop.point(p, -r + r * std::sin(t));
            deviation = std::max(deviation, curve->Value(u).Distance(exact));
            for (int side = 0; side < 2; ++side) {
                gp_Pnt2d at = onRound[side]->Value(u);
                deviation
                    = std::max(deviation, rounds[side]->surface->Value(at.X(), at.Y()).Distance(exact));
            }
        }
        if (deviation > allowed) {
            least = std::min(least, deviation);
            continue;
        }
        corner.onTop = rimVertex(loop.point(corner.topPlan, 0.0));
        double tolerance = std::max(Precision::Confusion(), 2 * deviation);
        corner.mitre = rimEdge(curve, 0.0, 1.0, corner.lowered, corner.onTop, tolerance);
        BRep_Builder builder;
        for (int side = 0; side < 2; ++side) {
            builder.UpdateEdge(
                corner.mitre,
                onRound[side],
                rounds[side]->surface,
                TopLoc_Location(),
                tolerance
            );
        }
        return;
    }
    refuse("a mitre's curve is " + describe(least) + " from its definition"
           + (touching ? " (offsets that touch)" : ""));
}

/// A loop curve as a wall of a tight corner
PlanWall rimPlanWall(const RimCurve& curve)
{
    PlanWall wall;
    wall.line = curve.line;
    if (curve.line) {
        wall.point = curve.point;
        wall.normal = curve.inward / curve.inward.Modulus();
    }
    else {
        wall.centre = curve.centre;
        wall.radius = curve.rho;
        wall.sign = -curve.convex;
    }
    return wall;
}

/// The canal patch of a tight wall arc: along theta (u) a cubic through 97 sections, across (v)
/// each section's arc of the ball's great circle between the two sides, rational of degree 2
void rimTightPatch(RimLoop& loop, size_t index, double r)
{
    RimRound& round = loop.rounds[index];
    const RimTight& tight = *round.tight;
    const int intervals = static_cast<int>(tight.table.size()) - 1;
    const double rho = tight.rho;
    const double d = r - rho;
    Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, intervals + 1);
    std::vector<gp_Pnt> side[2];
    std::vector<gp_Pnt> homogeneous;
    std::vector<gp_Pnt> weight;
    for (int i = 0; i <= intervals; ++i) {
        const double t = pi / 2 * i / intervals;
        parameters->SetValue(i + 1, t);
        const gp_XY& q = tight.table[i];
        gp_Pnt spine = loop.point(q, -r + d * std::sin(t));
        gp_Vec u[2];
        for (int k = 0; k < 2; ++k) {
            gp_XY n = tight.walls[k].gradient(q);
            u[k] = loop.vector(n * -std::cos(t)) + gp_Vec(loop.normal) * std::sin(t);
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
            side[k].push_back(spine.Translated(u[k] * rho));
        }
        homogeneous.emplace_back(spine.Translated(m * (rho / ch)).XYZ() * ch);
        weight.emplace_back(ch, 0.0, 0.0);
    }
    Handle(Geom_BSplineCurve) columns[4] = {
        interpolated(side[0], parameters),
        interpolated(homogeneous, parameters),
        interpolated(side[1], parameters),
        interpolated(weight, parameters)
    };
    const Handle(Geom_BSplineCurve)& model = columns[0];
    for (int c = 1; c < 4; ++c) {
        bool same = columns[c]->NbKnots() == model->NbKnots()
            && columns[c]->NbPoles() == model->NbPoles() && columns[c]->Degree() == model->Degree();
        for (int i = 1; same && i <= model->NbKnots(); ++i) {
            same = std::abs(columns[c]->Knot(i) - model->Knot(i)) <= 1e-12
                && columns[c]->Multiplicity(i) == model->Multiplicity(i);
        }
        if (!same) {
            refuse("a tight corner's columns have different knots");
        }
    }
    const int poleCount = model->NbPoles();
    const int knotCount = model->NbKnots();
    TColgp_Array2OfPnt poles(1, poleCount, 1, 3);
    TColStd_Array2OfReal weights(1, poleCount, 1, 3);
    for (int i = 1; i <= poleCount; ++i) {
        const double w = columns[3]->Pole(i).X();
        if (w <= 1e-9) {
            refuse("a tight corner's surface has a weight that is not positive");
        }
        poles.SetValue(i, 1, columns[0]->Pole(i));
        poles.SetValue(i, 2, gp_Pnt(columns[1]->Pole(i).XYZ() / w));
        poles.SetValue(i, 3, columns[2]->Pole(i));
        weights.SetValue(i, 1, 1.0);
        weights.SetValue(i, 2, w);
        weights.SetValue(i, 3, 1.0);
    }
    TColStd_Array1OfReal uKnots(1, knotCount);
    TColStd_Array1OfInteger uMults(1, knotCount);
    for (int i = 1; i <= knotCount; ++i) {
        uKnots.SetValue(i, model->Knot(i));
        uMults.SetValue(i, model->Multiplicity(i));
    }
    TColStd_Array1OfReal vKnots(1, 2);
    vKnots.SetValue(1, 0.0);
    vKnots.SetValue(2, 1.0);
    TColStd_Array1OfInteger vMults(1, 2);
    vMults.SetValue(1, 3);
    vMults.SetValue(2, 3);
    Handle(Geom_BSplineSurface) patch
        = new Geom_BSplineSurface(poles, weights, uKnots, vKnots, uMults, vMults, model->Degree(), 2);
    // Between the sections: every point of the patch at the ball's radius from its centre
    double deviation = 0.0;
    for (int i = 0; i < intervals; ++i) {
        const double t = pi / 2 * (i + 0.5) / intervals;
        gp_Pnt centre = loop.point(tight.spine(t), -r + d * std::sin(t));
        for (double v : {0.0, 0.25, 0.5, 0.75, 1.0}) {
            deviation = std::max(deviation, std::abs(patch->Value(t, v).Distance(centre) - rho));
        }
    }
    if (deviation > rimTolerance * std::max(1.0, r)) {
        if (intervals < 384) {
            // A wide arc: finer sections
            round.tight->prepare(round.curve.centre, 2 * intervals);
            rimTightPatch(loop, index, r);
            return;
        }
        refuse("a tight corner's face is " + describe(deviation) + " from its canal surface");
    }
    round.surface = patch;
}

/// The two sides of a tight wall arc's patch, each the end of the neighbouring round: an edge on
/// the patch's boundary with its curve on that round, held to the formula between its samples.
/// They meet in one vertex on the plane face, where the neighbours' top edges cross
void rimTightSides(RimLoop& loop, size_t index, double r)
{
    const size_t n = loop.rounds.size();
    RimRound& round = loop.rounds[index];
    const RimTight& tight = *round.tight;
    Handle(Geom_BSplineSurface) patch = Handle(Geom_BSplineSurface)::DownCast(round.surface);
    const int samples = static_cast<int>(tight.table.size());
    const gp_XY topPlan = tight.table.back();
    TopoDS_Vertex top = rimVertex(loop.point(topPlan, 0.0));
    BRep_Builder builder;
    for (int k = 0; k < 2; ++k) {
        RimVertex& corner = loop.corners[k == 0 ? index : (index + 1) % n];
        const RimRound& neighbour = loop.rounds[k == 0 ? (index + n - 1) % n : (index + 1) % n];
        auto uvOn = [&](const gp_XY& p, double t) {
            if (neighbour.curve.line) {
                gp_Pnt at = loop.point(p, 0.0);
                return gp_Pnt2d(t, gp_Vec(neighbour.origin, at).Dot(gp_Vec(neighbour.zAxis)));
            }
            return gp_Pnt2d(neighbour.angle(p), neighbour.curve.convex > 0 ? t : pi - t);
        };
        Handle(TColgp_HArray1OfPnt2d) uv = new TColgp_HArray1OfPnt2d(1, samples);
        Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, samples);
        for (int i = 0; i < samples; ++i) {
            const double t = pi / 2 * i / (samples - 1);
            parameters->SetValue(i + 1, t);
            uv->SetValue(i + 1, uvOn(tight.side(k, t), t));
        }
        Geom2dAPI_Interpolate flat(uv, parameters, false, Precision::Confusion());
        flat.Perform();
        if (!flat.IsDone()) {
            refuse("a tight corner's side on its round could not be interpolated");
        }
        Handle(Geom2d_Curve) onNeighbour = flat.Curve();
        Handle(Geom_Curve) curve = patch->VIso(double(k));
        double deviation = 0.0;
        for (int i = -1; i <= samples - 1; ++i) {
            const double t = i < 0 ? 0.0
                : i == samples - 1 ? pi / 2
                                   : pi / 2 * (i + 0.5) / (samples - 1);
            gp_Pnt exact = loop.point(tight.side(k, t), -r + r * std::sin(t));
            gp_Pnt2d at = onNeighbour->Value(t);
            deviation = std::max(deviation, curve->Value(t).Distance(exact));
            deviation
                = std::max(deviation, neighbour.surface->Value(at.X(), at.Y()).Distance(exact));
        }
        if (deviation > 10 * rimTolerance) {
            refuse("a tight corner's side is " + describe(deviation) + " from its definition");
        }
        const double tolerance = std::max(Precision::Confusion(), 2 * deviation);
        corner.topPlan = topPlan;
        corner.onTop = top;
        corner.mitre = rimEdge(curve, 0.0, pi / 2, corner.lowered, top, tolerance);
        builder.UpdateEdge(
            corner.mitre,
            uvLine(0.0, double(k), 1.0, 0.0),
            round.surface,
            TopLoc_Location(),
            tolerance
        );
        builder.UpdateEdge(corner.mitre, onNeighbour, neighbour.surface, TopLoc_Location(), tolerance);
    }
}

/// A lowered wall arc's curve on its tight corner's patch: the patch's edge at theta = 0, whose
/// parameter is not the arc's angle
Handle(Geom2d_Curve) rimArcOnPatch(
    const Handle(Geom_Curve)& arc,
    double first,
    double last,
    const Handle(Geom_BSplineSurface)& patch
)
{
    double u0 = 0.0;
    double u1 = 0.0;
    double v0 = 0.0;
    double v1 = 0.0;
    patch->Bounds(u0, u1, v0, v1);
    Handle(Geom_Curve) edge = patch->UIso(u0);
    double least = std::numeric_limits<double>::max();
    for (int samples : {33, 65, 129}) {
        Handle(TColgp_HArray1OfPnt2d) uv = new TColgp_HArray1OfPnt2d(1, samples);
        Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, samples);
        for (int i = 0; i < samples; ++i) {
            const double s = first + (last - first) * i / (samples - 1);
            GeomAPI_ProjectPointOnCurve projection(arc->Value(s), edge, v0, v1);
            if (projection.NbPoints() < 1) {
                refuse("a tight wall arc is not on its corner's face");
            }
            parameters->SetValue(i + 1, s);
            uv->SetValue(i + 1, gp_Pnt2d(u0, projection.LowerDistanceParameter()));
        }
        Geom2dAPI_Interpolate flat(uv, parameters, false, Precision::Confusion());
        flat.Perform();
        if (!flat.IsDone()) {
            refuse("a tight wall arc's curve on its corner's face could not be interpolated");
        }
        Handle(Geom2d_Curve) curve = flat.Curve();
        double deviation = 0.0;
        for (int i = 0; i <= 2 * (samples - 1); ++i) {
            const double s = first + (last - first) * i / (2 * (samples - 1));
            gp_Pnt2d at = curve->Value(s);
            deviation = std::max(deviation, patch->Value(at.X(), at.Y()).Distance(arc->Value(s)));
        }
        if (deviation <= rimTolerance) {
            return curve;
        }
        least = std::min(least, deviation);
    }
    refuse("a tight wall arc's curve on its corner's face is " + describe(least) + " off");
}

/// A tight corner's patch measured: its area, and the volume between it and the flat chords from
/// one side to the other at each height (down to the wall arc's segment at the rounds' centres)
void rimTightMeasures(const RimLoop& loop, const RimRound& round, double r, double& area, double& lens)
{
    Handle(Geom_BSplineSurface) patch = Handle(Geom_BSplineSurface)::DownCast(round.surface);
    double u0 = 0.0;
    double u1 = 0.0;
    double v0 = 0.0;
    double v1 = 0.0;
    patch->Bounds(u0, u1, v0, v1);
    const double node[3] = {-std::sqrt(0.6), 0.0, std::sqrt(0.6)};
    const double weight[3] = {5.0 / 9, 8.0 / 9, 5.0 / 9};
    const int uCells = 96;
    const int vCells = 8;
    const gp_Vec up(loop.normal);
    auto height = [&](const gp_Pnt& p) {
        return gp_Vec(loop.origin, p).Dot(up) + r;
    };
    area = 0.0;
    double onPatch = 0.0;
    double onChords = 0.0;
    for (int i = 0; i < uCells; ++i) {
        for (int a = 0; a < 3; ++a) {
            const double du = (u1 - u0) / uCells;
            const double u = u0 + du * (i + 0.5 + node[a] / 2);
            for (int j = 0; j < vCells; ++j) {
                for (int b = 0; b < 3; ++b) {
                    const double dv = (v1 - v0) / vCells;
                    const double v = v0 + dv * (j + 0.5 + node[b] / 2);
                    gp_Pnt p;
                    gp_Vec pu;
                    gp_Vec pv;
                    patch->D1(u, v, p, pu, pv);
                    gp_Vec normal = pu.Crossed(pv);
                    const double w = weight[a] * weight[b] * du * dv / 4;
                    area += w * normal.Magnitude();
                    onPatch += w * height(p) * normal.Dot(up);
                }
            }
            // The chords at this theta, from side 0 to side 1: over the chord, the flux is half
            // the sum of the two ends' speeds crossed with the chord
            gp_Pnt p0;
            gp_Pnt p1;
            gp_Vec s0;
            gp_Vec s1;
            gp_Vec unused;
            patch->D1(u, v0, p0, s0, unused);
            patch->D1(u, v1, p1, s1, unused);
            onChords += weight[a] * du / 2 * height(p0) * 0.5
                * (s0 + s1).Crossed(gp_Vec(p0, p1)).Dot(up);
        }
    }
    lens = std::abs(onPatch - onChords);
}

/// The wires of a face with its edges replaced; onTop: the loops whose wires become their rounds'
/// top edges
TopoDS_Face rimRebuilt(
    const TopoDS_Face& face,
    const TopTools_DataMapOfShapeShape& replaced,
    const TopTools_DataMapOfShapeListOfShape& split,
    const std::vector<const RimLoop*>& onTop
)
{
    BRep_Builder builder;
    TopoDS_Face rebuilt = TopoDS::Face(face.EmptyCopied());
    rebuilt.Orientation(TopAbs_FORWARD);
    for (TopoDS_Iterator wires(face.Oriented(TopAbs_FORWARD)); wires.More(); wires.Next()) {
        if (wires.Value().ShapeType() != TopAbs_WIRE) {
            builder.Add(rebuilt, wires.Value());
            continue;
        }
        const TopoDS_Wire& wire = TopoDS::Wire(wires.Value());
        TopoDS_Wire made;
        builder.MakeWire(made);
        const RimLoop* loop = nullptr;
        for (const auto* candidate : onTop) {
            if (candidate->wire.IsSame(wire)) {
                loop = candidate;
            }
        }
        if (loop) {
            for (const auto& round : loop->rounds) {
                if (round.tight) {
                    continue;
                }
                // The top edge runs with its own parameter; the loop's first member's orientation
                // in the wire says which way the wire held that member
                const RimMember& member = round.members.front();
                TopAbs_Orientation held = TopAbs_FORWARD;
                for (TopoDS_Iterator it(wire.Oriented(TopAbs_FORWARD)); it.More(); it.Next()) {
                    if (it.Value().IsSame(member.edge)) {
                        held = it.Value().Orientation();
                    }
                }
                // Whether the top edge's parameter runs with the loop
                bool topAlong = round.curve.line ? round.topFirst < round.topLast
                                                 : round.curve.sense > 0;
                bool sameWay = topAlong == (member.along > 0);
                for (const auto& piece : round.tops) {
                    builder.Add(made, piece.Oriented(sameWay ? held : TopAbs::Reverse(held)));
                }
            }
        }
        else {
            for (TopoDS_Iterator it(wire.Oriented(TopAbs_FORWARD)); it.More(); it.Next()) {
                if (replaced.IsBound(it.Value())) {
                    builder.Add(made, replaced.Find(it.Value()).Oriented(it.Value().Orientation()));
                }
                else if (split.IsBound(it.Value())) {
                    for (const auto& piece : split.Find(it.Value())) {
                        builder.Add(made, piece.Oriented(it.Value().Orientation()));
                    }
                }
                else {
                    builder.Add(made, it.Value());
                }
            }
        }
        made.Closed(true);
        builder.Add(rebuilt, made.Oriented(wire.Orientation()));
    }
    return TopoDS::Face(rebuilt.Oriented(face.Orientation()));
}

/** A plane face whose rounds' top edges touch another of its loops (a hole tangent to the rails):
 * the loops are cut at the vertices where they touch, and the face comes out in the pieces those
 * vertices pinch off, as Onshape has it. With the material on the left of every edge, the outline
 * of a piece that arrives at such a vertex along one loop leaves it along the other.
 */
std::vector<TopoDS_Face> rimPinched(
    const TopoDS_Face& face,
    const TopTools_DataMapOfShapeListOfShape& split,
    const std::vector<const RimLoop*>& onTop
)
{
    struct Directed
    {
        TopoDS_Edge edge;
        int wire = 0;
        TopoDS_Vertex from;
        TopoDS_Vertex to;
        bool used = false;
    };
    std::vector<Directed> edges;
    int wireIndex = 0;
    TopAbs_Orientation wireWay = TopAbs_FORWARD;
    auto add = [&](const TopoDS_Shape& edge) {
        Directed d;
        d.edge = TopoDS::Edge(edge.Oriented(TopAbs::Compose(wireWay, edge.Orientation())));
        d.wire = wireIndex;
        TopExp::Vertices(d.edge, d.from, d.to, true);
        if (d.from.IsNull() || d.to.IsNull()) {
            refuse("a plane face with an edge without vertices");
        }
        edges.push_back(d);
    };
    for (TopoDS_Iterator wires(face.Oriented(TopAbs_FORWARD)); wires.More(); wires.Next()) {
        if (wires.Value().ShapeType() != TopAbs_WIRE) {
            refuse("a plane face with a loose vertex whose loops touch");
        }
        const TopoDS_Wire& wire = TopoDS::Wire(wires.Value());
        wireWay = wire.Orientation();
        const RimLoop* loop = nullptr;
        for (const auto* candidate : onTop) {
            if (candidate->wire.IsSame(wire)) {
                loop = candidate;
            }
        }
        if (loop) {
            for (const auto& round : loop->rounds) {
                if (round.tight) {
                    continue;
                }
                // As rimRebuilt()
                const RimMember& member = round.members.front();
                TopAbs_Orientation held = TopAbs_FORWARD;
                for (TopoDS_Iterator it(wire.Oriented(TopAbs_FORWARD)); it.More(); it.Next()) {
                    if (it.Value().IsSame(member.edge)) {
                        held = it.Value().Orientation();
                    }
                }
                bool topAlong = round.curve.line ? round.topFirst < round.topLast
                                                 : round.curve.sense > 0;
                bool sameWay = topAlong == (member.along > 0);
                for (const auto& piece : round.tops) {
                    add(piece.Oriented(sameWay ? held : TopAbs::Reverse(held)));
                }
            }
        }
        else {
            for (TopoDS_Iterator it(wire.Oriented(TopAbs_FORWARD)); it.More(); it.Next()) {
                if (split.IsBound(it.Value())) {
                    for (const auto& piece : split.Find(it.Value())) {
                        add(piece.Oriented(it.Value().Orientation()));
                    }
                }
                else {
                    add(it.Value());
                }
            }
        }
        ++wireIndex;
    }
    // The outlines
    const size_t none = edges.size();
    std::vector<std::vector<size_t>> cycles;
    for (size_t start = 0; start < edges.size(); ++start) {
        if (edges[start].used) {
            continue;
        }
        std::vector<size_t> cycle;
        size_t at = start;
        while (!edges[at].used) {
            edges[at].used = true;
            cycle.push_back(at);
            size_t chosen = none;
            int found = 0;
            int others = 0;
            for (size_t k = 0; k < edges.size(); ++k) {
                if (!edges[k].from.IsSame(edges[at].to)) {
                    continue;
                }
                ++found;
                if (edges[k].wire != edges[at].wire) {
                    ++others;
                    chosen = k;
                }
                else if (chosen == none) {
                    chosen = k;
                }
            }
            if (found < 1 || found > 2 || (found == 2 && others != 1)) {
                refuse("a plane face's loops do not chain where they touch");
            }
            at = chosen;
        }
        if (at != start) {
            refuse("a plane face's loops do not chain where they touch");
        }
        cycles.push_back(cycle);
    }
    // Each outline's turn about the face's own normal: the material inside (a piece's outer
    // loop) or outside (a hole)
    const RimLoop& frame = *onTop.front();
    const double way = face.Orientation() == TopAbs_REVERSED ? -1.0 : 1.0;
    BRep_Builder builder;
    std::vector<TopoDS_Face> pieces;
    std::vector<TopoDS_Wire> holes;
    std::vector<gp_Pnt> holePoints;
    for (const auto& cycle : cycles) {
        TopoDS_Wire wire;
        builder.MakeWire(wire);
        double area = 0.0;
        gp_Pnt some;
        for (size_t k : cycle) {
            builder.Add(wire, edges[k].edge);
            BRepAdaptor_Curve curve(edges[k].edge);
            const bool reversed = edges[k].edge.Orientation() == TopAbs_REVERSED;
            const int steps = 16;
            gp_XY last;
            for (int i = 0; i <= steps; ++i) {
                double u = double(reversed ? steps - i : i) / steps;
                gp_Pnt point = curve.Value(
                    curve.FirstParameter() + (curve.LastParameter() - curve.FirstParameter()) * u
                );
                gp_XY p = frame.plan(point);
                if (i > 0) {
                    area += 0.5 * last.Crossed(p);
                }
                if (i == steps / 2) {
                    some = point;
                }
                last = p;
            }
        }
        wire.Closed(true);
        if (way * area > 0) {
            TopoDS_Face piece = TopoDS::Face(face.EmptyCopied());
            piece.Orientation(TopAbs_FORWARD);
            builder.Add(piece, wire);
            pieces.push_back(piece);
        }
        else {
            holes.push_back(wire);
            holePoints.push_back(some);
        }
    }
    if (pieces.empty()) {
        refuse("a plane face without an outer loop");
    }
    for (size_t h = 0; h < holes.size(); ++h) {
        size_t owner = pieces.size();
        for (size_t i = 0; owner == pieces.size() && i < pieces.size(); ++i) {
            BRepClass_FaceClassifier classifier(pieces[i], holePoints[h], 1e-7);
            if (classifier.State() == TopAbs_IN) {
                owner = i;
            }
        }
        if (owner == pieces.size()) {
            refuse("a hole of a plane face that lies in none of its pieces");
        }
        builder.Add(pieces[owner], holes[h]);
    }
    for (auto& piece : pieces) {
        piece.Orientation(face.Orientation());
    }
    return pieces;
}

/// The distance from p to the whole surface of a face, for the surfaces that have it in closed
/// form (no more than the distance to the face itself); negative for any other surface
double rimSurfaceDistance(const BRepAdaptor_Surface& surface, const gp_Pnt& p)
{
    auto polar = [&p](const gp_Ax1& axis, double& along, double& radial) {
        gp_Vec v(axis.Location(), p);
        along = v.Dot(gp_Vec(axis.Direction()));
        radial = std::sqrt(std::max(v.SquareMagnitude() - along * along, 0.0));
    };
    double along = 0.0;
    double radial = 0.0;
    switch (surface.GetType()) {
        case GeomAbs_Plane:
            return surface.Plane().Distance(p);
        case GeomAbs_Cylinder: {
            polar(surface.Cylinder().Axis(), along, radial);
            return std::abs(radial - surface.Cylinder().Radius());
        }
        case GeomAbs_Sphere:
            return std::abs(surface.Sphere().Location().Distance(p) - surface.Sphere().Radius());
        case GeomAbs_Torus: {
            polar(surface.Torus().Axis(), along, radial);
            return std::abs(std::hypot(radial - surface.Torus().MajorRadius(), along)
                            - surface.Torus().MinorRadius());
        }
        case GeomAbs_Cone: {
            // Both nappes: in the half plane through the axis, two rays from the apex
            const gp_Cone cone = surface.Cone();
            polar(gp_Ax1(cone.Apex(), cone.Axis().Direction()), along, radial);
            const double angle = std::abs(cone.SemiAngle());
            double best = std::hypot(along, radial);
            for (double side : {1.0, -1.0}) {
                const double onRay = side * along * std::cos(angle) + radial * std::sin(angle);
                if (onRay > 0.0) {
                    best = std::min(
                        best,
                        std::abs(side * along * std::sin(angle) - radial * std::cos(angle))
                    );
                }
            }
            return best;
        }
        default:
            return -1.0;
    }
}

TopoDS_Shape rimRounds(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    ShapeMapper& mapper,
    int& cornerCount
)
{
    if (request.kind != Kind::Fillet || request.size1 <= 0
        || std::abs(request.size1 - request.size2) > linearTolerance * std::max(1.0, request.size1)) {
        refuse("not a round of one radius");
    }
    const double r = request.size1;
    // One solid and nothing beside it: the fillet's input may hold it in a compound
    int baseFaces = 0;
    int solidFaces = 0;
    if (!base.IsNull()) {
        for (TopExp_Explorer it(base, TopAbs_FACE); it.More(); it.Next()) {
            ++baseFaces;
        }
        for (TopExp_Explorer it(base, TopAbs_SOLID); it.More(); it.Next()) {
            for (TopExp_Explorer face(it.Current(), TopAbs_FACE); face.More(); face.Next()) {
                ++solidFaces;
            }
        }
    }
    if (base.IsNull() || countSolids(base) != 1 || baseFaces != solidFaces) {
        refuse("the base is not one solid");
    }
    int shells = 0;
    for (TopExp_Explorer it(base, TopAbs_SHELL); it.More(); it.Next()) {
        ++shells;
    }
    if (shells != 1) {
        refuse("a base with a void");
    }
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
    TopExp::MapShapesAndUniqueAncestors(base, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    TopExp::MapShapesAndUniqueAncestors(base, TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
    std::vector<RimLoop> loops = rimLoops(base, edges, r, edgeFaces, vertexEdges);
    // Below the limit OCCT's own result stands, except where it is known to be wrong: a reflex
    // corner with a circle (reflexCircleCorner(), where the fillet asks the construction first)
    if (request.limitOnly && !rimReflexCircle(loops) && !rimTightArc(loops)) {
        refuse("no reflex corner with a circle");
    }
    // The plan knows the plane faces and the walls only. What the rounds remove lies within r of
    // the rim's edges, so no other face of the body may come that near: a cavity or a blind hole
    // under the rim (a shelled plate with a thin wall) would be met by the round, which is then
    // not the body assembled here (valid, with the right counts, areas and volume, and wrong).
    // A hole's wall touching a top edge is at r (the pinch)
    {
        TopTools_IndexedMapOfShape planned;
        std::vector<std::pair<TopoDS_Shape, Bnd_Box>> reach;
        for (const auto& edge : edges) {
            if (!edgeFaces.Contains(edge)) {
                refuse("a rim edge without two faces");
            }
            for (const auto& face : edgeFaces.FindFromKey(edge)) {
                planned.Add(face);
            }
            Bnd_Box box;
            BRepBndLib::Add(edge, box, false);
            box.Enlarge(r);
            reach.emplace_back(edge, box);
        }
        const double margin = 1e-5;
        for (TopExp_Explorer it(base, TopAbs_FACE); it.More(); it.Next()) {
            if (planned.Contains(it.Current())) {
                continue;
            }
            const TopoDS_Face face = TopoDS::Face(it.Current());
            Bnd_Box box;
            BRepBndLib::Add(face, box, false);
            const BRepAdaptor_Surface surface(face);
            for (const auto& [edge, edgeBox] : reach) {
                if (box.IsOut(edgeBox)) {
                    continue;
                }
                // Along the rim edge (a line or a circle: its points move evenly with the
                // parameter), the distance to the face's whole surface, which is no more than
                // the distance to the face: where that is d, the next d - r of the edge on
                // either side is farther than r. The exact distance to the face only where the
                // surface comes within r or has no closed form (large rims: FSLC #50's 916
                // edges beside a cone)
                bool exact = false;
                try {
                    BRepAdaptor_Curve curve(TopoDS::Edge(edge));
                    const double first = curve.FirstParameter();
                    const double last = curve.LastParameter();
                    gp_Pnt at;
                    gp_Vec speed;
                    curve.D1(first, at, speed);
                    const double perUnit = speed.Magnitude();
                    if (perUnit < 1e-12 || last <= first) {
                        exact = true;
                    }
                    for (double t = first; !exact;) {
                        const double clear = rimSurfaceDistance(surface, curve.Value(t)) - (r - margin);
                        if (clear < 0.05 * r) {
                            exact = true;
                            break;
                        }
                        if (t >= last) {
                            break;
                        }
                        t = std::min(last, t + 2 * clear / perUnit);
                    }
                }
                catch (const Standard_Failure&) {
                    exact = true;
                }
                if (!exact) {
                    continue;
                }
                BRepExtrema_DistShapeShape distance(edge, face);
                if (!distance.IsDone() || distance.Value() < r - margin) {
                    refuse(rimReachRefusal);
                }
            }
        }
    }

    BRep_Builder builder;
    TopTools_DataMapOfShapeShape replaced;  // in the walls: rim edges and the edges down
    TopTools_IndexedMapOfShape rimEdges;
    TopTools_IndexedMapOfShape uprights;
    std::vector<TopoDS_Face> roundFaces;
    RimExpected expected;
    cornerCount = 0;
    // Where a top edge touches another loop of its plane face
    std::vector<RimPinch> pinches;
    TopTools_IndexedMapOfShape pinchedFaces;
    TopTools_DataMapOfShapeListOfShape splitInto;
    for (auto& loop : loops) {
        const size_t n = loop.rounds.size();
        // The plane face's loops that are not rounded: lines and circles (anything else is left
        // to the body's validity and the plane face's area)
        std::vector<RimOther> others;
        for (TopoDS_Iterator wires(loop.face); wires.More(); wires.Next()) {
            if (wires.Value().ShapeType() != TopAbs_WIRE) {
                continue;
            }
            bool rounded = false;
            for (const auto& candidate : loops) {
                rounded = rounded || candidate.wire.IsSame(wires.Value());
            }
            if (rounded) {
                continue;
            }
            for (TopoDS_Iterator it(wires.Value()); it.More(); it.Next()) {
                RimOther other;
                other.edge = TopoDS::Edge(it.Value().Oriented(TopAbs_FORWARD));
                other.wire = TopoDS::Wire(wires.Value());
                BRepAdaptor_Curve curve(other.edge);
                other.first = curve.FirstParameter();
                other.last = curve.LastParameter();
                other.piece.p = loop.plan(curve.Value(other.first));
                other.piece.q = loop.plan(curve.Value(other.last));
                if (curve.GetType() == GeomAbs_Line) {
                    if ((other.piece.q - other.piece.p).Modulus() < 1e-9) {
                        continue;
                    }
                    other.piece.line = true;
                    other.line = curve.Line();
                }
                else if (curve.GetType() == GeomAbs_Circle
                         && parallel(curve.Circle().Axis().Direction(), loop.normal)) {
                    other.circle = curve.Circle();
                    other.piece.centre = loop.plan(other.circle.Location());
                    other.piece.radius = other.circle.Radius();
                    other.piece.sense = other.circle.Axis().Direction().Dot(loop.normal) > 0 ? 1 : -1;
                    other.piece.sweep = other.last - other.first;
                }
                else {
                    continue;
                }
                others.push_back(other);
            }
        }
        for (auto& corner : loop.corners) {
            replaced.Bind(corner.upright, corner.shortened);
            uprights.Add(corner.upright);
            cornerCount += corner.geometry.tangent ? 0 : 1;
        }
        for (auto& list : loop.inner) {
            for (auto& vertex : list) {
                if (!vertex.upright.IsNull()) {
                    replaced.Bind(vertex.upright, vertex.shortened);
                    uprights.Add(vertex.upright);
                }
            }
        }
        // Each round's surface and frame
        for (size_t i = 0; i < n; ++i) {
            RimRound& round = loop.rounds[i];
            if (round.tight) {
                rimTightPatch(loop, i, r);
                continue;
            }
            if (round.curve.line) {
                gp_XY spine = round.start + round.curve.inward * r;
                round.origin = loop.point(spine, -r);
                gp_Dir x(loop.vector(round.curve.inward).Reversed());
                round.zAxis = x.Crossed(loop.normal);
                round.surface = new Geom_CylindricalSurface(gp_Ax3(round.origin, round.zAxis, x), r);
            }
            else {
                gp_XY out = round.start - round.curve.centre;
                double a = std::atan2(out.Y(), out.X()) + round.curve.sense * round.sweep / 2;
                round.xAxis = gp_XY(-std::cos(a), -std::sin(a));
                round.origin = loop.point(round.curve.centre, -r);
                round.zAxis = loop.normal;
                double major = round.curve.radius(r);
                if (major < r) {
                    // A horn torus, to the last digit (the spindle was refused)
                    major = r;
                }
                round.surface = new Geom_ToroidalSurface(
                    gp_Ax3(round.origin, loop.normal, gp_Dir(loop.vector(round.xAxis))),
                    major,
                    r
                );
            }
        }
        for (size_t i = 0; i < n; ++i) {
            if (loop.rounds[i].tight) {
                rimTightSides(loop, i, r);
            }
            else if (!loop.rounds[(i + n - 1) % n].tight) {
                rimMitre(loop, i, r);
            }
        }
        RimExpected own = rimExpected(loop, r);
        expected.volume += own.volume;
        expected.roundArea += own.roundArea;
        expected.band += own.band;
        expected.bandSlack += own.bandSlack;
        expected.volumeSlack += own.volumeSlack;
        for (size_t i = 0; i < n; ++i) {
            RimRound& round = loop.rounds[i];
            const RimVertex& from = loop.corners[i];
            const RimVertex& to = loop.corners[(i + 1) % n];
            const bool convex = round.curve.line || round.curve.convex > 0;
            // The lowered rim edges: the base's curves moved down by r, so that their curves on
            // the walls are the base's moved too
            auto loweredOf = [&](const TopoDS_Vertex& vertex) -> const TopoDS_Vertex& {
                if (vertex.IsSame(from.vertex)) {
                    return from.lowered;
                }
                if (vertex.IsSame(to.vertex)) {
                    return to.lowered;
                }
                for (const auto& inner : loop.inner[i]) {
                    if (vertex.IsSame(inner.vertex)) {
                        return inner.lowered;
                    }
                }
                refuse("a rim vertex that was not prepared");
            };
            gp_Vec down = gp_Vec(loop.normal) * (-r);
            for (auto& member : round.members) {
                double f = 0.0;
                double l = 0.0;
                Handle(Geom_Curve) curve = BRep_Tool::Curve(member.edge, f, l);
                Handle(Geom2d_Curve) onWall
                    = BRep_Tool::CurveOnSurface(member.edge, member.wall, f, l);
                if (curve.IsNull() || onWall.IsNull()) {
                    refuse("a rim edge without its curves");
                }
                Handle(Geom_Curve) moved = Handle(Geom_Curve)::DownCast(curve->Translated(down));
                BRepAdaptor_Surface wall(member.wall);
                gp_Vec2d shift;
                if (wall.GetType() == GeomAbs_Plane) {
                    gp_Pln plane = wall.Plane();
                    shift = gp_Vec2d(
                        down.Dot(gp_Vec(plane.XAxis().Direction())),
                        down.Dot(gp_Vec(plane.YAxis().Direction()))
                    );
                }
                else {
                    shift = gp_Vec2d(0.0, down.Dot(gp_Vec(wall.Cylinder().Axis().Direction())));
                }
                Handle(Geom2d_Curve) movedOnWall
                    = Handle(Geom2d_Curve)::DownCast(onWall->Translated(shift));
                TopoDS_Vertex forward;
                TopoDS_Vertex reversed;
                TopExp::Vertices(member.edge, forward, reversed);
                const double tolerance
                    = std::max(BRep_Tool::Tolerance(member.edge), Precision::Confusion());
                member.lowered
                    = rimEdge(moved, f, l, loweredOf(forward), loweredOf(reversed), tolerance);
                builder.UpdateEdge(member.lowered, movedOnWall, member.wall, tolerance);
                // And on the round: a line of its parameters, running with the edge's own
                BRepAdaptor_Curve own(member.edge);
                Handle(Geom2d_Curve) onRound;
                double middle = (f + l) / 2;
                if (round.tight) {
                    onRound = rimArcOnPatch(
                        moved,
                        f,
                        l,
                        Handle(Geom_BSplineSurface)::DownCast(round.surface)
                    );
                }
                else if (round.curve.line) {
                    gp_Lin line = own.Line();
                    double way = gp_Vec(line.Direction()).Dot(gp_Vec(round.zAxis)) > 0 ? 1.0 : -1.0;
                    double v = gp_Vec(round.origin, own.Value(middle).Translated(down))
                                   .Dot(gp_Vec(round.zAxis));
                    onRound = uvLine(0.0, v - way * middle, 0.0, way);
                }
                else {
                    double way = own.Circle().Axis().Direction().Dot(loop.normal) > 0 ? 1.0 : -1.0;
                    double u = round.angle(loop.plan(own.Value(middle)));
                    onRound = uvLine(u - way * middle, convex ? 0.0 : pi, way, 0.0);
                }
                builder.UpdateEdge(member.lowered, onRound, round.surface, TopLoc_Location(), tolerance);
                replaced.Bind(member.edge, member.lowered);
                rimEdges.Add(member.edge);
            }
            if (round.tight) {
                // The patch's face: in its own parameters, counter-clockwise, side 0 up (theta),
                // the point on the plane face (a degenerated edge), side 1 down, the wall arc back
                TopoDS_Edge apex;
                builder.MakeEdge(apex);
                builder.Degenerated(apex, true);
                builder.Add(apex, from.onTop.Oriented(TopAbs_FORWARD));
                builder.Add(apex, from.onTop.Oriented(TopAbs_REVERSED));
                builder.UpdateEdge(
                    apex,
                    uvLine(pi / 2, 0.0, 0.0, 1.0),
                    round.surface,
                    TopLoc_Location(),
                    Precision::Confusion()
                );
                builder.Range(apex, 0.0, 1.0);
                TopoDS_Wire wire;
                builder.MakeWire(wire);
                builder.Add(wire, from.mitre.Oriented(TopAbs_FORWARD));
                builder.Add(wire, apex.Oriented(TopAbs_FORWARD));
                builder.Add(wire, to.mitre.Oriented(TopAbs_REVERSED));
                for (const auto& member : round.members) {
                    builder.Add(
                        wire,
                        member.lowered.Oriented(member.along > 0 ? TopAbs_REVERSED : TopAbs_FORWARD)
                    );
                }
                wire.Closed(true);
                builder.MakeFace(round.face, round.surface, Precision::Confusion());
                builder.Add(round.face, wire);
                // Its natural normal points out of the material where it points away from the
                // ball's centre
                gp_Pnt at;
                gp_Vec du;
                gp_Vec dv;
                round.surface->D1(pi / 4, 0.5, at, du, dv);
                gp_Pnt centre = loop.point(
                    round.tight->spine(pi / 4),
                    -r + (r - round.tight->rho) * std::sin(pi / 4)
                );
                if (du.Crossed(dv).Dot(gp_Vec(centre, at)) < 0) {
                    round.face.Reverse();
                }
                roundFaces.push_back(round.face);
                for (const auto& member : round.members) {
                    mapper.insert(MappingStatus::Generated, member.edge, round.face);
                }
                continue;
            }
            // The top edge, on the plane face at the depth r
            Handle(Geom_Curve) topCurve;
            Handle(Geom2d_Curve) topOnRound;
            double atFrom = 0.0;
            double atTo = 0.0;
            if (round.curve.line) {
                topCurve = new Geom_Line(
                    round.origin.Translated(gp_Vec(loop.normal) * r),
                    round.zAxis
                );
                auto along = [&](const gp_XY& p) {
                    return gp_Vec(round.origin, loop.point(p, 0.0)).Dot(gp_Vec(round.zAxis));
                };
                atFrom = along(from.topPlan);
                atTo = along(to.topPlan);
                topOnRound = uvLine(pi / 2, 0.0, 0.0, 1.0);
                if ((to.topPlan - from.topPlan).Dot(round.curve.direction) <= rimTolerance) {
                    refuse("a rim round with no length");
                }
            }
            else {
                double radius = round.curve.radius(r);
                if (radius <= rimTolerance) {
                    refuse("a rim round with no length");
                }
                topCurve = new Geom_Circle(
                    gp_Ax2(
                        loop.point(round.curve.centre, 0.0),
                        loop.normal,
                        gp_Dir(loop.vector(round.xAxis))
                    ),
                    radius
                );
                atFrom = round.angle(from.topPlan);
                atTo = round.angle(to.topPlan);
                topOnRound = uvLine(0.0, pi / 2, 1.0, 0.0);
                // Within one turn about the middle of the wall arc, and running the loop's way
                double low = std::min(atFrom, atTo);
                double high = std::max(atFrom, atTo);
                if (low < 1e-6 || high > 2 * pi - 1e-6
                    || round.curve.sense * (atTo - atFrom) <= 1e-9) {
                    refuse("a rim round with no length");
                }
            }
            round.topFirst = atFrom;
            round.topLast = atTo;
            const bool rising = atFrom < atTo;
            // Where another loop of the plane face touches the top edge, both get a vertex
            std::vector<std::pair<double, TopoDS_Vertex>> cuts;
            {
                RimPiece own;
                own.line = round.curve.line;
                own.p = from.topPlan;
                own.q = to.topPlan;
                if (!own.line) {
                    own.centre = round.curve.centre;
                    own.radius = round.curve.radius(r);
                    own.sense = round.curve.sense;
                    own.sweep = std::abs(atTo - atFrom);
                }
                const double scale = own.line ? 1.0 : own.radius;
                for (const auto& other : others) {
                    std::vector<gp_XY> touching;
                    if (rimContacts(own, other.piece, touching)) {
                        refuse("a rim round that runs into another loop of its plane face");
                    }
                    for (const auto& x : touching) {
                        gp_Pnt point = loop.point(x, 0.0);
                        double at = own.line
                            ? gp_Vec(round.origin, point).Dot(gp_Vec(round.zAxis))
                            : round.angle(x);
                        if ((at - std::min(atFrom, atTo)) * scale < 1e-6
                            || (std::max(atFrom, atTo) - at) * scale < 1e-6) {
                            refuse("another loop of the plane face touches a rim round's top edge "
                                   "at its end");
                        }
                        RimPinch pinch;
                        pinch.edge = other.edge;
                        pinch.wire = other.wire;
                        pinch.onEdge = other.parameter(point);
                        // The other loop stays on the plane face's side of the top edge: beside
                        // the touch it is deeper behind this round's wall than r. From the
                        // removed side (a hole in the band, at a reflex corner's run-on) its wall
                        // would stand in the rounds, and no measure below would tell
                        {
                            BRepAdaptor_Curve curve(other.edge);
                            const double step = 0.1 * (other.last - other.first);
                            for (double beside : {pinch.onEdge - step, pinch.onEdge + step}) {
                                if (beside < other.first || beside > other.last) {
                                    continue;
                                }
                                gp_XY q = loop.plan(curve.Value(beside));
                                const RimCurve& wall = round.curve;
                                double depth = wall.line
                                    ? (q - wall.point).Dot(wall.inward) / wall.inward.Modulus()
                                    : -wall.convex * ((q - wall.centre).Modulus() - wall.rho);
                                if (depth < r - 1e-6) {
                                    refuse("another loop of the plane face touches a rim round's "
                                           "top edge from the round's side");
                                }
                            }
                        }
                        TopoDS_Vertex forward;
                        TopoDS_Vertex reversed;
                        TopExp::Vertices(other.edge, forward, reversed);
                        if ((pinch.onEdge - other.first) * other.scale() < 1e-6) {
                            pinch.atEnd = true;
                            pinch.vertex = forward;
                        }
                        else if ((other.last - pinch.onEdge) * other.scale() < 1e-6) {
                            pinch.atEnd = true;
                            pinch.vertex = reversed;
                        }
                        if (pinch.atEnd
                            && (pinch.vertex.IsNull()
                                || BRep_Tool::Pnt(pinch.vertex).Distance(point)
                                    > BRep_Tool::Tolerance(pinch.vertex))) {
                            refuse("another loop's vertex beside the top edge it touches");
                        }
                        // One vertex for one place: two edges of the other loop meet there
                        bool known = false;
                        for (const auto& cut : cuts) {
                            if (std::abs(cut.first - at) * scale < 1e-6) {
                                if (!pinch.atEnd || !cut.second.IsSame(pinch.vertex)) {
                                    refuse("two loops of the plane face touch a rim round's top "
                                           "edge in one place");
                                }
                                known = true;
                            }
                        }
                        if (!pinch.atEnd) {
                            for (const auto& earlier : pinches) {
                                if (earlier.edge.IsSame(pinch.edge)
                                    && std::abs(earlier.onEdge - pinch.onEdge) * other.scale() < 1e-6) {
                                    refuse("two rim rounds' top edges touch another loop in one "
                                           "place");
                                }
                            }
                            pinch.vertex = rimVertex(point, 2e-6);
                        }
                        pinches.push_back(pinch);
                        pinchedFaces.Add(loop.face);
                        if (!known) {
                            cuts.emplace_back(at, pinch.vertex);
                        }
                    }
                }
                std::sort(cuts.begin(), cuts.end(), [](const auto& a, const auto& b) {
                    return a.first < b.first;
                });
            }
            BRepAdaptor_Surface top(loop.face);
            Handle(Geom2d_Curve) topOnFace = GeomAPI::To2d(topCurve, top.Plane());
            {
                double low = std::min(atFrom, atTo);
                TopoDS_Vertex lowVertex = rising ? from.onTop : to.onTop;
                cuts.emplace_back(std::max(atFrom, atTo), rising ? to.onTop : from.onTop);
                for (const auto& cut : cuts) {
                    TopoDS_Edge piece = rimEdge(topCurve, low, cut.first, lowVertex, cut.second);
                    builder.UpdateEdge(
                        piece,
                        topOnRound,
                        round.surface,
                        TopLoc_Location(),
                        Precision::Confusion()
                    );
                    builder.UpdateEdge(piece, topOnFace, loop.face, Precision::Confusion());
                    round.tops.push_back(piece);
                    low = cut.first;
                    lowVertex = cut.second;
                }
                round.top = round.tops.front();
            }
            // The round's face: its natural normal points out of the material, so its wire runs
            // counter-clockwise in its parameters. In the loop's direction: the lowered edges,
            // the mitre at the round's end up, the top edge back, the mitre at its start down
            auto cornerUV = [&](const RimVertex& corner, bool onTop) {
                const gp_XY& p = onTop ? corner.topPlan : corner.plan;
                double t = onTop ? pi / 2 : 0.0;
                if (round.curve.line) {
                    return gp_XY(
                        t,
                        gp_Vec(round.origin, loop.point(p, 0.0)).Dot(gp_Vec(round.zAxis))
                    );
                }
                return gp_XY(round.angle(p), convex ? t : pi - t);
            };
            gp_XY quad[4]
                = {cornerUV(from, false), cornerUV(to, false), cornerUV(to, true), cornerUV(from, true)};
            double turn = 0.0;
            for (int k = 0; k < 4; ++k) {
                turn += quad[k].Crossed(quad[(k + 1) % 4]);
            }
            if (std::abs(turn) < 1e-12) {
                refuse("a rim round with no area");
            }
            const bool flip = turn < 0;
            auto oriented = [&](const TopoDS_Edge& edge, bool withLoop) {
                return edge.Oriented(withLoop != flip ? TopAbs_FORWARD : TopAbs_REVERSED);
            };
            TopoDS_Wire wire;
            builder.MakeWire(wire);
            for (const auto& member : round.members) {
                builder.Add(wire, oriented(member.lowered, member.along > 0));
            }
            builder.Add(wire, oriented(to.mitre, true));
            for (const auto& piece : round.tops) {
                builder.Add(wire, oriented(piece, !rising));
            }
            builder.Add(wire, oriented(from.mitre, false));
            wire.Closed(true);
            builder.MakeFace(round.face, round.surface, Precision::Confusion());
            builder.Add(round.face, wire);
            roundFaces.push_back(round.face);
            for (const auto& member : round.members) {
                mapper.insert(MappingStatus::Generated, member.edge, round.face);
            }
        }
    }

    // The other loops' edges, cut at the vertices where a top edge touches them. A loop touched
    // in one place only would leave its plane face in one piece that meets itself there
    for (size_t i = 0; i < pinches.size(); ++i) {
        int places = 0;
        for (size_t k = 0; k < pinches.size(); ++k) {
            if (!pinches[k].wire.IsSame(pinches[i].wire)) {
                continue;
            }
            bool repeated = false;
            for (size_t j = 0; j < k; ++j) {
                repeated = repeated
                    || (pinches[j].wire.IsSame(pinches[i].wire)
                        && pinches[j].vertex.IsSame(pinches[k].vertex));
            }
            places += repeated ? 0 : 1;
        }
        if (places < 2) {
            refuse("another loop of the plane face touches the rim rounds' top edges in one place");
        }
        if (pinches[i].atEnd || splitInto.IsBound(pinches[i].edge)) {
            continue;
        }
        const TopoDS_Edge& edge = pinches[i].edge;
        std::vector<std::pair<double, TopoDS_Vertex>> cuts;
        for (const auto& pinch : pinches) {
            if (!pinch.atEnd && pinch.edge.IsSame(edge)) {
                cuts.emplace_back(pinch.onEdge, pinch.vertex);
            }
        }
        std::sort(cuts.begin(), cuts.end(), [](const auto& a, const auto& b) {
            return a.first < b.first;
        });
        TopoDS_Vertex forward;
        TopoDS_Vertex reversed;
        TopExp::Vertices(edge, forward, reversed);
        BRepAdaptor_Curve curve(edge);
        cuts.emplace_back(curve.LastParameter(), reversed);
        double low = curve.FirstParameter();
        TopoDS_Vertex lowVertex = forward;
        TopTools_ListOfShape made;
        for (const auto& cut : cuts) {
            TopoDS_Edge piece = TopoDS::Edge(edge.EmptyCopied());
            piece.Orientation(TopAbs_FORWARD);
            builder.Add(piece, lowVertex.Oriented(TopAbs_FORWARD));
            builder.Add(piece, cut.second.Oriented(TopAbs_REVERSED));
            builder.Range(piece, low, cut.first);
            made.Append(piece);
            mapper.insert(MappingStatus::Modified, edge, piece);
            low = cut.first;
            lowVertex = cut.second;
        }
        splitInto.Bind(edge, made);
    }

    // No two top edges on one plane face meet but at an end they share: rounds of walls that are
    // not neighbours would run through each other, and the measures below, which follow the same
    // offsets, could not tell
    TopTools_IndexedMapOfShape crossChecked;
    for (const auto& first : loops) {
        if (crossChecked.Contains(first.face)) {
            continue;
        }
        crossChecked.Add(first.face);
        std::vector<RimPiece> pieces;
        for (const auto& loop : loops) {
            if (!loop.face.IsSame(first.face)) {
                continue;
            }
            const size_t n = loop.rounds.size();
            for (size_t i = 0; i < n; ++i) {
                const RimRound& round = loop.rounds[i];
                if (round.tight) {
                    continue;
                }
                RimPiece piece;
                piece.line = round.curve.line;
                piece.p = loop.corners[i].topPlan;
                piece.q = loop.corners[(i + 1) % n].topPlan;
                if (!piece.line) {
                    piece.centre = round.curve.centre;
                    piece.radius = round.curve.radius(r);
                    piece.sense = round.curve.sense;
                    piece.sweep = std::abs(round.topLast - round.topFirst);
                }
                pieces.push_back(piece);
            }
        }
        for (size_t a = 0; a < pieces.size(); ++a) {
            for (size_t b = a + 1; b < pieces.size(); ++b) {
                if (rimPiecesCross(pieces[a], pieces[b])) {
                    auto show = [](const RimPiece& piece) {
                        return std::string(piece.line ? "line" : "arc R " + describe(piece.radius))
                            + " (" + describe(piece.p.X()) + ", " + describe(piece.p.Y()) + ") to ("
                            + describe(piece.q.X()) + ", " + describe(piece.q.Y()) + ")";
                    };
                    refuse("rim rounds that run into each other: " + show(pieces[a]) + " and "
                           + show(pieces[b]));
                }
            }
        }
    }

    // The base's faces: the plane faces and the walls rebuilt, the rest as they are
    TopoDS_Shell shell;
    builder.MakeShell(shell);
    double topArea = 0.0;
    double topAreaBefore = 0.0;
    int faceCount = 0;
    int pinchedPieces = 0;
    for (TopExp_Explorer it(base, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face& face = TopoDS::Face(it.Current());
        ++faceCount;
        std::vector<const RimLoop*> onTop;
        for (const auto& loop : loops) {
            if (loop.face.IsSame(face)) {
                onTop.push_back(&loop);
            }
        }
        bool touched = !onTop.empty();
        for (TopExp_Explorer sub(face, TopAbs_EDGE); sub.More() && !touched; sub.Next()) {
            touched = replaced.IsBound(sub.Current()) || splitInto.IsBound(sub.Current());
        }
        if (!onTop.empty()) {
            // A plane face with a loop of its own is no other loop's wall
            for (TopExp_Explorer sub(face, TopAbs_EDGE); sub.More(); sub.Next()) {
                if (uprights.Contains(sub.Current())) {
                    refuse("a plane face that is a rim and a wall");
                }
            }
        }
        if (!touched) {
            builder.Add(shell, face);
            continue;
        }
        if (onTop.empty()) {
            // A wall: nothing else of it may reach into the round's height
            for (const auto& loop : loops) {
                bool mine = false;
                for (TopExp_Explorer sub(face, TopAbs_EDGE); sub.More() && !mine; sub.Next()) {
                    for (const auto& round : loop.rounds) {
                        for (const auto& member : round.members) {
                            mine = mine || member.edge.IsSame(sub.Current());
                        }
                    }
                }
                if (!mine) {
                    continue;
                }
                for (TopExp_Explorer sub(face, TopAbs_EDGE); sub.More(); sub.Next()) {
                    if (rimEdges.Contains(sub.Current()) || uprights.Contains(sub.Current())) {
                        continue;
                    }
                    // (the edge's own points: its box's corners rise above an edge of a rim
                    // whose plane is off the axes. Between 64 samples a circle or an ellipse
                    // rises above the highest by under a hundredth of the samples' span)
                    BRepAdaptor_Curve curve(TopoDS::Edge(sub.Current()));
                    const bool straight = curve.GetType() == GeomAbs_Line;
                    const int steps = straight ? 1 : 64;
                    double highest = -std::numeric_limits<double>::max();
                    double lowest = std::numeric_limits<double>::max();
                    for (int k = 0; k <= steps; ++k) {
                        gp_Pnt p = curve.Value(
                            curve.FirstParameter()
                            + (curve.LastParameter() - curve.FirstParameter()) * k / steps
                        );
                        const double height = gp_Vec(loop.origin, p).Dot(gp_Vec(loop.normal));
                        highest = std::max(highest, height);
                        lowest = std::min(lowest, height);
                    }
                    if (highest + (straight ? 0.0 : 0.01 * (highest - lowest))
                        > -r - 1000 * rimTolerance) {
                        refuse("a wall with an edge within the round's height");
                    }
                }
            }
        }
        if (pinchedFaces.Contains(face)) {
            // In the pieces its loops pinch off where they touch
            std::vector<TopoDS_Face> pieces = rimPinched(face, splitInto, onTop);
            topAreaBefore += areaOf(face);
            for (const auto& piece : pieces) {
                topArea += areaOf(piece);
                mapper.insert(MappingStatus::Modified, face, piece);
                builder.Add(shell, piece);
            }
            pinchedPieces += int(pieces.size()) - 1;
            continue;
        }
        TopoDS_Face rebuilt = rimRebuilt(face, replaced, splitInto, onTop);
        if (!onTop.empty()) {
            topArea += areaOf(rebuilt);
            topAreaBefore += areaOf(face);
        }
        mapper.insert(MappingStatus::Modified, face, rebuilt);
        builder.Add(shell, rebuilt);
    }
    for (const auto& face : roundFaces) {
        builder.Add(shell, face);
    }
    shell.Closed(true);
    TopoDS_Solid solid;
    builder.MakeSolid(solid);
    builder.Add(solid, shell);
    for (TopTools_DataMapOfShapeShape::Iterator it(replaced); it.More(); it.Next()) {
        if (uprights.Contains(it.Key())) {
            mapper.insert(MappingStatus::Modified, it.Key(), it.Value());
        }
    }

    // The post-conditions: valid; as many faces as the base's and the rounds; the plane faces',
    // the rounds' and the body's measures as the definition gives them
    BRepCheck_Analyzer check(solid);
    if (!check.IsValid()) {
        // What fails, for the reason: each kind of sub-shape with its first status
        std::string what;
        for (TopAbs_ShapeEnum kind : {TopAbs_SHELL, TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE, TopAbs_VERTEX}) {
            TopTools_IndexedMapOfShape subs;
            TopExp::MapShapes(solid, kind, subs);
            int bad = 0;
            int status = 0;
            for (int i = 1; i <= subs.Extent(); ++i) {
                const Handle(BRepCheck_Result)& result = check.Result(subs(i));
                if (result.IsNull()) {
                    continue;
                }
                bool failed = false;
                for (const auto& one : result->Status()) {
                    if (one != BRepCheck_NoError) {
                        failed = true;
                        status = status ? status : int(one);
                    }
                }
                for (result->InitContextIterator(); result->MoreShapeInContext();
                     result->NextShapeInContext()) {
                    for (const auto& one : result->StatusOnShape()) {
                        if (one != BRepCheck_NoError) {
                            if (!status && kind == TopAbs_EDGE
                                && result->ContextualShape().ShapeType() == TopAbs_FACE) {
                                BRepAdaptor_Curve c(TopoDS::Edge(subs(i)));
                                BRepAdaptor_Surface f(TopoDS::Face(result->ContextualShape()));
                                double f2 = 0.0;
                                double l2 = 0.0;
                                Handle(Geom2d_Curve) pc = BRep_Tool::CurveOnSurface(
                                    TopoDS::Edge(subs(i)),
                                    TopoDS::Face(result->ContextualShape()),
                                    f2,
                                    l2
                                );
                                what += " [edge curve " + std::to_string(int(c.GetType())) + " "
                                    + describe(c.FirstParameter()) + ".." + describe(c.LastParameter())
                                    + " on surface " + std::to_string(int(f.GetType()));
                                if (!pc.IsNull()) {
                                    gp_Pnt2d a = pc->Value(f2);
                                    gp_Pnt2d b = pc->Value(l2);
                                    what += " pcurve " + describe(f2) + ".." + describe(l2) + " ("
                                        + describe(a.X()) + ", " + describe(a.Y()) + ") to ("
                                        + describe(b.X()) + ", " + describe(b.Y()) + ") off "
                                        + describe(f.Value(a.X(), a.Y()).Distance(c.Value(c.FirstParameter())))
                                        + " / "
                                        + describe(f.Value(b.X(), b.Y()).Distance(c.Value(c.LastParameter())));
                                }
                                what += "]";
                            }
                            failed = true;
                            status = status ? status : int(one);
                        }
                    }
                }
                bad += failed ? 1 : 0;
            }
            if (bad) {
                what += " " + std::to_string(bad) + " of kind " + std::to_string(int(kind))
                    + " (status " + std::to_string(status) + ")";
            }
        }
        refuse("the rim rounds' body is not valid:" + what);
    }
    int made = 0;
    for (TopExp_Explorer it(solid, TopAbs_FACE); it.More(); it.Next()) {
        ++made;
    }
    if (countSolids(solid) != 1 || made != faceCount + int(roundFaces.size()) + pinchedPieces) {
        refuse("the rim rounds' body has the wrong faces");
    }
    double roundArea = 0.0;
    for (const auto& face : roundFaces) {
        double area = areaOf(face);
        if (area <= 0.0) {
            refuse("a rim round with no area");
        }
        roundArea += area;
    }
    if (std::abs(roundArea - expected.roundArea) > 1e-5 * expected.roundArea) {
        refuse("the rim rounds' area " + describe(roundArea) + " differs from its closed form "
               + describe(expected.roundArea));
    }
    // (the band is the difference of two measured areas, each good to about 1e-6 of itself: a
    // rim of 916 arcs about a face of 21000 read 4e-7 of the face off)
    if (std::abs((topAreaBefore - topArea) - expected.band)
        > 1e-5 * expected.band + 1e-6 * topAreaBefore + expected.bandSlack) {
        refuse("the plane faces lost " + describe(topAreaBefore - topArea) + " instead of "
               + describe(expected.band));
    }
    double removed = -changedVolume(base, solid);
    if (std::abs(removed - expected.volume) > 2e-4 * expected.volume + expected.volumeSlack) {
        removed = volumeOf(base) - volumeOf(solid);
    }
    if (std::abs(removed - expected.volume) > 2e-4 * expected.volume + expected.volumeSlack) {
        refuse("the rim rounds removed " + describe(removed) + " instead of "
               + describe(expected.volume));
    }
    return solid;
}

}  // namespace

bool constructRims(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    Construction& out,
    std::vector<TopoDS_Shape>& rest
)
{
    rest.clear();
    try {
        if (request.kind != Kind::Fillet || request.size1 <= 0 || base.IsNull()) {
            return false;
        }
        const double r = request.size1;
        TopTools_IndexedMapOfShape selected;
        for (const auto& edge : edges) {
            selected.Add(edge);
        }
        // The wires of plane faces whose edges are all selected, each edge in one of them
        TopTools_IndexedMapOfShape grouped;
        std::vector<std::vector<TopoDS_Shape>> groups;
        for (TopExp_Explorer faces(base, TopAbs_FACE); faces.More(); faces.Next()) {
            if (BRepAdaptor_Surface(TopoDS::Face(faces.Current())).GetType() != GeomAbs_Plane) {
                continue;
            }
            for (TopoDS_Iterator wires(faces.Current()); wires.More(); wires.Next()) {
                if (wires.Value().ShapeType() != TopAbs_WIRE) {
                    continue;
                }
                std::vector<TopoDS_Shape> group;
                bool whole = true;
                for (TopoDS_Iterator it(wires.Value()); it.More() && whole; it.Next()) {
                    whole = selected.Contains(it.Value()) && !grouped.Contains(it.Value());
                    group.push_back(it.Value());
                }
                if (!whole || group.empty()) {
                    continue;
                }
                for (const auto& edge : group) {
                    grouped.Add(edge);
                }
                groups.push_back(std::move(group));
            }
        }
        const size_t most = 64;
        if (groups.empty() || groups.size() > most) {
            return false;
        }
        TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
        TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
        TopExp::MapShapesAndUniqueAncestors(base, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
        TopExp::MapShapesAndUniqueAncestors(base, TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
        // Each loop that is in the builder's scope alone and with those taken before it; at the
        // limit only (Request::limitOnly), those with a reflex corner with a circle
        std::vector<TopoDS_Shape> taken;
        std::vector<const std::vector<TopoDS_Shape>*> takenGroups;
        size_t alone = 0;
        for (const auto& group : groups) {
            try {
                std::vector<RimLoop> own = rimLoops(base, group, r, edgeFaces, vertexEdges);
                if (request.limitOnly && !rimReflexCircle(own) && !rimTightArc(own)) {
                    continue;
                }
                ++alone;
                std::vector<TopoDS_Shape> trial = taken;
                trial.insert(trial.end(), group.begin(), group.end());
                rimLoops(base, trial, r, edgeFaces, vertexEdges);
                taken = std::move(trial);
                takenGroups.push_back(&group);
            }
            catch (const Refusal& refusal) {
                FC_LOG("rim loop of " << group.size() << " edges not built directly: " << refusal.reason);
            }
            catch (const Standard_Failure&) {
            }
        }
        if (taken.empty()) {
            return false;
        }
        auto mapper = std::make_shared<ShapeMapper>();
        int corners = 0;
        Request direct = request;
        direct.limitOnly = false;
        TopoDS_Shape shape;
        try {
            shape = rimRounds(base, taken, direct, *mapper, corners);
        }
        catch (const Refusal& refusal) {
            out.rimRefusal = refusal.reason;
        }
        catch (const Standard_Failure& e) {
            out.rimRefusal = std::string("OCCT: ") + e.GetMessageString();
        }
        catch (const Base::Exception& e) {
            out.rimRefusal = e.what();
        }
        catch (const std::exception& e) {
            out.rimRefusal = e.what();
        }
        const size_t fewLoops = 8;
        if (shape.IsNull() && takenGroups.size() > 1 && takenGroups.size() <= fewLoops) {
            // A loop that only the building refuses (its rounds, its mitres, its measures) does
            // not take the others with it: the loops one after the other, each kept if the body
            // with it is built
            taken.clear();
            for (const auto* group : takenGroups) {
                std::vector<TopoDS_Shape> trial = taken;
                trial.insert(trial.end(), group->begin(), group->end());
                try {
                    auto trialMapper = std::make_shared<ShapeMapper>();
                    int trialCorners = 0;
                    TopoDS_Shape built = rimRounds(base, trial, direct, *trialMapper, trialCorners);
                    shape = built;
                    mapper = trialMapper;
                    corners = trialCorners;
                    taken = std::move(trial);
                }
                catch (const Refusal&) {
                }
                catch (const Standard_Failure&) {
                }
            }
        }
        // Every loop that is in scope alone is in the body: one that is not (its rounds meet
        // another loop's, or share a wall's edge with it) would be rounded on the body without
        // the check of the rounds against each other, so the selection is then not split
        size_t held = 0;
        TopTools_IndexedMapOfShape inBody;
        for (const auto& edge : taken) {
            inBody.Add(edge);
        }
        for (const auto* group : takenGroups) {
            held += inBody.Contains(group->front()) ? 1 : 0;
        }
        if (shape.IsNull() || held != alone) {
            if (out.rimRefusal.empty()) {
                out.rimRefusal = "rim loops that are not built together";
            }
            return false;
        }
        out.rimRefusal.clear();
        TopTools_IndexedMapOfShape built;
        for (const auto& edge : taken) {
            built.Add(edge);
        }
        // The rest are edges of the body built: one that a round shortened (the edge down from a
        // rim vertex) is not, and the selection is then not split
        TopTools_IndexedMapOfShape kept;
        TopExp::MapShapes(shape, TopAbs_EDGE, kept);
        for (const auto& edge : edges) {
            if (built.Contains(edge)) {
                continue;
            }
            if (!kept.Contains(edge)) {
                rest.clear();
                out.rimRefusal = "a selected edge that a rim round shortens";
                return false;
            }
            rest.push_back(edge);
        }
        out.shape = shape;
        out.mapper = mapper;
        out.edges = built.Extent();
        out.corners = corners;
        return true;
    }
    catch (const Refusal& refusal) {
        out.rimRefusal = refusal.reason;
    }
    catch (const Standard_Failure& e) {
        out.rimRefusal = std::string("OCCT: ") + e.GetMessageString();
    }
    catch (const Base::Exception& e) {
        out.rimRefusal = e.what();
    }
    catch (const std::exception& e) {
        out.rimRefusal = e.what();
    }
    rest.clear();
    return false;
}

namespace
{

/** Where a selected edge's round or chamfer, with OCCT's tangent chain, would run across a strip of
 * face narrower than its setback, onto the face beyond: the user's reason when the dress-up fails
 * (ops#640; a 0.06 mm strip between a hole's round and the plate's outer round). The strip is the
 * shortest distance, on a face of a chain edge, from that edge to an edge of the face that is not
 * in the chain and touches none of it. Empty where every strip is wide enough */
std::string narrowStrip(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request
)
{
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndUniqueAncestors(base, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    TopTools_IndexedMapOfShape chain;
    auto addEdges = [&](const std::vector<TopoDS_Shape>& shapes) {
        for (const auto& edge : shapes) {
            if (!edge.IsNull() && edge.ShapeType() == TopAbs_EDGE) {
                chain.Add(edge);
            }
        }
    };
    addEdges(edges);
    addEdges(request.contour);
    TopTools_IndexedMapOfShape chainVertices;
    for (int i = 1; i <= chain.Extent(); ++i) {
        TopExp::MapShapes(chain(i), TopAbs_VERTEX, chainVertices);
    }
    auto touchesChain = [&](const TopoDS_Shape& edge) {
        for (TopExp_Explorer it(edge, TopAbs_VERTEX); it.More(); it.Next()) {
            if (chainVertices.Contains(it.Current())) {
                return true;
            }
        }
        return false;
    };
    double size = request.size1;
    if (request.kind == Kind::Chamfer && request.chamferType == ChamferType::twoDistances) {
        size = std::max(request.size1, request.size2);
    }
    double width = std::numeric_limits<double>::infinity();
    TopoDS_Face beyond;
    for (int i = 1; i <= chain.Extent(); ++i) {
        const TopoDS_Edge& edge = TopoDS::Edge(chain(i));
        if (BRep_Tool::Degenerated(edge) || !edgeFaces.Contains(edge)) {
            continue;
        }
        const TopTools_ListOfShape& faces = edgeFaces.FindFromKey(edge);
        if (faces.Extent() != 2) {
            continue;
        }
        // The setback on the faces: a round's contact line lies r tan(a/2) from the edge, a the
        // angle between the faces' normals at the edge's middle (r on a right angle)
        double setback = size;
        if (request.kind == Kind::Fillet) {
            BRepAdaptor_Curve curve(edge);
            gp_Pnt middle = curve.Value(0.5 * (curve.FirstParameter() + curve.LastParameter()));
            try {
                gp_Dir n1 = outwardNormalAny(TopoDS::Face(faces.First()), middle);
                gp_Dir n2 = outwardNormalAny(TopoDS::Face(faces.Last()), middle);
                double angle = n1.Angle(n2);
                if (angle < 1e-3) {
                    continue;
                }
                setback = size * std::tan(0.5 * angle);
            }
            catch (const Refusal&) {
                // No normal there: a right angle's setback
            }
            catch (const Standard_Failure&) {
            }
        }
        for (const auto& faceShape : faces) {
            const TopoDS_Face& face = TopoDS::Face(faceShape);
            for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
                const TopoDS_Edge& other = TopoDS::Edge(it.Current());
                if (chain.Contains(other) || BRep_Tool::Degenerated(other) || touchesChain(other)) {
                    continue;
                }
                BRepExtrema_DistShapeShape distance(edge, other);
                if (!distance.IsDone() || distance.Value() >= setback - linearTolerance
                    || distance.Value() >= width) {
                    continue;
                }
                width = distance.Value();
                beyond = face;
                for (const auto& across : edgeFaces.FindFromKey(other)) {
                    if (!across.IsSame(face)) {
                        beyond = TopoDS::Face(across);
                    }
                }
            }
        }
    }
    if (beyond.IsNull()) {
        return {};
    }
    auto shortly = [](double value) {
        std::ostringstream ss;
        ss.precision(4);
        ss << value;
        return ss.str();
    };
    GeomAbs_SurfaceType type = BRepAdaptor_Surface(beyond, Standard_False).GetType();
    bool round = type == GeomAbs_Cylinder || type == GeomAbs_Torus || type == GeomAbs_Sphere
        || type == GeomAbs_BSplineSurface || type == GeomAbs_SurfaceOfRevolution;
    std::string what = request.kind == Kind::Fillet ? "the round of radius " + shortly(request.size1)
                                                    : "the chamfer of size " + shortly(size);
    return what + " mm would overflow a strip of face " + shortly(width)
        + " mm wide onto the neighbouring " + (round ? "round" : "face")
        + ", which is not built";
}

}  // namespace

bool construct(
    const TopoDS_Shape& base,
    const std::vector<TopoDS_Shape>& edges,
    const Request& request,
    Construction& out,
    std::string* reason
)
{
    // Whole rim loops on plane faces are built directly, without a Boolean; whatever that
    // refuses, or fails a check of its result, goes to the construction by Booleans below
    try {
        auto mapper = std::make_shared<ShapeMapper>();
        int corners = 0;
        TopoDS_Shape shape = rimRounds(base, edges, request, *mapper, corners);
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
        out.rimRefusal = refusal.reason;
        out.rimBlocked = refusal.reason == rimReachRefusal;
    }
    catch (const Standard_Failure& e) {
        out.rimRefusal = std::string("OCCT: ") + e.GetMessageString();
    }
    catch (const Base::Exception& e) {
        out.rimRefusal = e.what();
    }
    catch (const std::exception& e) {
        out.rimRefusal = e.what();
    }
    // (Now, not with the result: the construction by Booleans below can take very long)
    FC_LOG("rim rounds not built directly: " << out.rimRefusal);
    std::string why;
    try {
        auto mapper = std::make_shared<ShapeMapper>();
        int corners = 0;
        bool rolledOn = false;
        TopoDS_Shape shape = constructShape(base, edges, request, *mapper, corners, rolledOn);
        TopTools_IndexedMapOfShape selected;
        for (const auto& edge : edges) {
            selected.Add(edge);
        }
        out.shape = shape;
        out.mapper = mapper;
        out.edges = selected.Extent();
        out.corners = corners;
        out.rolledOn = rolledOn;
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
    // A round that ends against a planar face facing it (under an overhang): OCCT's own round on
    // the piece of the base in front of that face. Where it doesn't apply, the reason above stands
    std::string second;
    try {
        auto mapper = std::make_shared<ShapeMapper>();
        TopoDS_Shape shape = constructUnderOverhang(base, edges, request, *mapper);
        TopTools_IndexedMapOfShape selected;
        for (const auto& edge : edges) {
            selected.Add(edge);
        }
        out.shape = shape;
        out.mapper = mapper;
        out.edges = selected.Extent();
        out.corners = 0;
        return true;
    }
    catch (const NoOverhang&) {
    }
    catch (const Refusal& refusal) {
        second = refusal.reason;
    }
    catch (const Standard_Failure& e) {
        second = std::string("OCCT: ") + e.GetMessageString();
    }
    catch (const Base::Exception& e) {
        second = e.what();
    }
    catch (const std::exception& e) {
        second = e.what();
    }
    catch (...) {
        second = "an unknown exception";
    }
    if (!second.empty()) {
        why += "; built in front of the face its edge ends against: " + second;
    }
    // The cause the user can act on first, where there is one (ops#640)
    std::string strip;
    try {
        strip = narrowStrip(base, edges, request);
    }
    catch (const Standard_Failure&) {
    }
    if (!strip.empty()) {
        // The tangent chain is OCCT's propagation, not the cause: dropped (ops#640)
        why = why.rfind(tangentChainRefusal, 0) == 0 ? strip : strip + " (" + why + ")";
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
    // A selection with an edge along another curve stays OCCT's first: the construction would
    // refuse it there anyway (NEW-165, notes/fillet-spline-edge.md)
    for (const auto& edge : edges) {
        if (!edge.IsNull() && edge.ShapeType() == TopAbs_EDGE
            && !BRep_Tool::Degenerated(TopoDS::Edge(edge))) {
            const GeomAbs_CurveType type = BRepAdaptor_Curve(TopoDS::Edge(edge)).GetType();
            if (type != GeomAbs_Line && type != GeomAbs_Circle) {
                return false;
            }
        }
    }
    try {
        const TopoShape base(baseShape);
        Context ctx(base, request);
        // Every selected edge straight between two cylinders along it (betweenCylinders()): the
        // construction builds the round as a cylinder, below the limit too (constructShape())
        int picked = 0;
        int ruledOnCylinders = 0;
        for (const auto& edge : edges) {
            if (edge.IsNull() || edge.ShapeType() != TopAbs_EDGE) {
                continue;
            }
            ++picked;
            try {
                const EdgeData data = analyse(ctx, TopoDS::Edge(edge));
                if (tightArc(ctx, data)) {
                    return true;
                }
                if (betweenCylinders(data)) {
                    ++ruledOnCylinders;
                }
            }
            catch (const Refusal&) {
                // Not analysable: neither a tight arc nor a straight edge between cylinders
            }
        }
        return picked > 0 && ruledOnCylinders == picked;
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
    if (!construction.rimRefusal.empty()) {
        FC_LOG("rim rounds not built directly: " << construction.rimRefusal);
    }
    FC_LOG("built exactly: " << construction.edges << " edges, " << construction.corners << " corners");
    Recorder::add(construction.edges, construction.corners, construction.rolledOn);
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
