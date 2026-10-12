// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <cmath>
#include <memory>
#include <numbers>
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
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <TopoDS.hxx>
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
/// A face of the result with a smaller area is degenerate
constexpr double areaTolerance = 1e-7;

/// Thrown inside the construction when it refuses; caught by build()
struct Refusal
{
    std::string reason;
};

[[noreturn]] void refuse(const std::string& reason)
{
    throw Refusal {reason};
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
 * S1 builds free ends and tangent continuations; the corner kinds are refused with their own
 * reason until the corner construction (S1c) handles them.
 */
enum class VertexClass
{
    /// No other selected edge at the vertex: the tool is bounded by the end face's plane
    FreeEnd,
    /// A selected edge continues this one tangentially: the two tools meet on the plane
    /// normal to the common tangent
    TangentContinuation,
    /// One other selected edge meets this one at an angle (a two-edge corner)
    Corner2,
    /// All three edges at the vertex are selected (a three-edge corner)
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
    /// named after
    TopoDS_Shape source;
    /// The tool's volume in closed form, not measured
    double volume = 0.0;
    /// On the edge's two faces, in the order of EdgeData::faces
    Strip strips[2];
    /// The faces of the tool that lie on the faces adjacent to the edge: the result must not
    /// keep any part of them (each tangent strip must be backed by material, or by air)
    std::vector<TopoDS_Shape> contactFaces;
    /// The planes that bound the tool at the edge's free ends: a face of the tool left in such
    /// a plane is merged into the base's coplanar face (interface point 4)
    std::vector<TrimPlane> caps;
    /// The tool's faces in those planes: whatever they become must be the end face's image (the
    /// end face covers them, or they merge into it)
    std::vector<TopoDS_Shape> capFaces;
};

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
    TrimPlane trim;
    TopoDS_Edge continuation;  // TangentContinuation: the other selected edge
    std::string reason;
};

/// 5.6, interface point 1: how the selected edge ends at the vertex
VertexEnd classify(const Context& ctx, const EdgeData& data, const TopoDS_Vertex& vertex)
{
    VertexEnd end;
    auto edges = ctx.list(ctx.vertexEdges, vertex);
    auto faces = ctx.list(ctx.vertexFaces, vertex);
    if (edges.size() != 3 || faces.size() != 3) {
        end.reason = "a vertex where " + std::to_string(edges.size()) + " edges meet";
        return end;
    }
    gp_Dir away = awayFrom(data.edge, vertex);
    gp_Pnt point = BRep_Tool::Pnt(vertex);
    int otherSelected = 0;
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
            end.trim = {point, away.Reversed()};
        }
        else if (isSelected) {
            ++otherSelected;
        }
    }
    if (otherSelected == 1) {
        end.kind = VertexClass::Corner2;
        end.reason = "a corner where two selected edges meet";
        return end;
    }
    if (otherSelected == 2) {
        end.kind = VertexClass::Corner3;
        end.reason = "a corner where three selected edges meet";
        return end;
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
    end.trim = {point, normal};
    return end;
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

/// A prism along a straight edge, bounded by the planes at its ends
Tool lineTool(const Context& ctx, const EdgeData& data, const VertexEnd ends[2])
{
    gp_Dir direction(gp_Vec(data.start, data.end));
    double length = data.start.Distance(data.end);
    Section section = sectionAt(ctx, data, data.first);
    // Each plane at the parameter where the section's corners and its centroid cross it
    std::vector<gp_Pnt> hull = {section.corner, section.ends[0], section.ends[1]};
    gp_Pnt centroid = section.corner.Translated(section.centroid);
    auto range = [&](const TrimPlane& plane, const gp_Pnt& p) {
        return crossing(plane, p, direction);
    };
    double from = 0.0;
    double to = length;
    bool trimStart = !parallel(ends[0].trim.normal, direction);
    bool trimEnd = !parallel(ends[1].trim.normal, direction);
    for (const auto& p : hull) {
        double s0 = range(ends[0].trim, p);
        double s1 = range(ends[1].trim, p);
        if (s1 - s0 <= linearTolerance) {
            refuse("the planes at the ends of an edge cross inside its tool");
        }
        from = std::min(from, s0);
        to = std::max(to, s1);
    }
    Tool tool;
    tool.source = data.edge;
    tool.cut = data.convex;
    tool.volume = section.area * (range(ends[1].trim, centroid) - range(ends[0].trim, centroid));
    for (int k = 0; k < 2; ++k) {
        tool.strips[k].face = data.faces[k];
        tool.strips[k].width = section.length[k];
        tool.strips[k].farSide.valid = true;
        tool.strips[k].farSide.lin = gp_Lin(section.ends[k], direction);
    }
    double margin = 1.0 + section.length[0] + section.length[1];
    double begin = trimStart ? from - margin : 0.0;
    double finish = trimEnd ? to + margin : length;
    gp_Vec step(direction);
    TopoDS_Face face = section.face();
    gp_Trsf move;
    move.SetTranslation(step * begin);
    face = TopoDS::Face(face.Moved(TopLoc_Location(move)));
    TopoDS_Shape solid
        = BRepPrimAPI_MakePrism(face, step * (finish - begin), Standard_True).Shape();
    for (int i = 0; i < 2; ++i) {
        if ((i == 0 && !trimStart) || (i == 1 && !trimEnd)) {
            continue;
        }
        BRepAlgoAPI_Cut trim(solid, halfSpaceBeyond(ends[i].trim, 4 * ctx.scale + 4 * margin));
        if (!trim.IsDone() || trim.HasErrors()) {
            refuse("trimming a tool failed");
        }
        solid = trim.Shape();
    }
    tool.solid = solid;
    for (int i = 0; i < 2; ++i) {
        if (ends[i].kind == VertexClass::FreeEnd) {
            tool.caps.push_back(ends[i].trim);
        }
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
        const TrimPlane& plane = ends[i].trim;
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
            tool.caps.push_back(ends[i].trim);
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

/// The tool's faces on the faces next to its edge, and in the planes of its caps
void findContactFaces(Tool& tool, const EdgeData& data)
{
    for (TopExp_Explorer it(tool.solid, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face& face = TopoDS::Face(it.Current());
        for (int k = 0; k < 2; ++k) {
            if (sameDomain(face, data.faces[k])) {
                tool.contactFaces.push_back(face);
                tool.strips[k].contacts.push_back(face);
            }
        }
        for (const auto& cap : tool.caps) {
            if (inPlane(face, cap)) {
                tool.capFaces.push_back(face);
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
 */
void checkStrips(const std::vector<Tool>& tools, bool limitOnly)
{
    struct OnFace
    {
        TopoDS_Face face;
        std::vector<const Strip*> strips;
    };
    std::vector<OnFace> faces;
    for (const auto& tool : tools) {
        for (const auto& strip : tool.strips) {
            auto group = std::find_if(faces.begin(), faces.end(), [&](const OnFace& f) {
                return f.face.IsSame(strip.face);
            });
            if (group == faces.end()) {
                faces.push_back({strip.face, {}});
                group = std::prev(faces.end());
            }
            group->strips.push_back(&strip);
        }
    }
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
                for (const auto& mine : group.strips[i]->contacts) {
                    for (const auto& theirs : group.strips[j]->contacts) {
                        double tolerance = std::min(
                            areaToleranceOf(mine, *group.strips[i]),
                            areaToleranceOf(theirs, *group.strips[j])
                        );
                        if (areaOf(commonOf(mine, theirs)) > tolerance) {
                            refuse("two tangent strips overlap");
                        }
                    }
                }
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

std::string describe(double value)
{
    std::ostringstream ss;
    ss.precision(10);
    ss << value;
    return ss.str();
}

/// One Boolean stage, and its checks (5.6, interface point 5)
TopoDS_Shape applyTools(
    const TopoDS_Shape& shape,
    const std::vector<const Tool*>& tools,
    bool cut,
    std::vector<Stage>& stages
)
{
    TopTools_ListOfShape arguments;
    arguments.Append(shape);
    TopTools_ListOfShape toolShapes;
    double expected = 0.0;
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

TopoDS_Shape construct(
    TopoShape& result,
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const Request& request,
    const char* op
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
                ends[slot] = classify(ctx, edgeData, vertices[i]);
                VertexClass kind = ends[slot].kind;
                if (kind == VertexClass::Refuse || kind == VertexClass::Corner2
                    || kind == VertexClass::Corner3) {
                    refuse(ends[slot].reason);
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
        Tool tool = edgeData.line ? lineTool(ctx, edgeData, ends) : circleTool(ctx, edgeData, ends);
        if (countSolids(tool.solid) != 1) {
            refuse("a tool is not one solid");
        }
        double measured = volumeOf(tool.solid);
        if (std::abs(measured - tool.volume) > volumeTolerance * tool.volume) {
            refuse("a tool's volume " + describe(measured) + " differs from its closed form "
                   + describe(tool.volume));
        }
        findContactFaces(tool, edgeData);
        // A fused tool fills air only: material under it would be fused twice, and the volume
        // checks after the cut could not tell (5.6, interface point 7)
        if (!tool.cut
            && volumeOf(commonOf(base.getShape(), tool.solid)) > volumeTolerance * tool.volume) {
            refuse("a fused tool overlaps the base's material");
        }
        tools.push_back(std::move(tool));
    }
    checkStrips(tools, request.limitOnly);

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
            shape = applyTools(shape, group, cut, stages);
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
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        if (areaOf(it.Current()) < areaTolerance) {
            refuse("the result has a face of zero area");
        }
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
    return shape;
}

}  // namespace

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
        construct(built, base, edges, request, op);
        result = built;
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
