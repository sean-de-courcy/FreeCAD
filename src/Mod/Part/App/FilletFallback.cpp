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
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
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
    BRepAdaptor_Surface surface(endFace, Standard_False);
    if (endFace.IsNull() || surface.GetType() != GeomAbs_Plane) {
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

/// The tool's faces on the faces next to its edge
void findContactFaces(Tool& tool, const EdgeData& data)
{
    for (TopExp_Explorer it(tool.solid, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face& face = TopoDS::Face(it.Current());
        if (sameDomain(face, data.faces[0]) || sameDomain(face, data.faces[1])) {
            tool.contactFaces.push_back(face);
        }
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
    for (int i = 1; i <= ctx.selected.Extent(); ++i) {
        data.push_back(analyse(ctx, TopoDS::Edge(ctx.selected(i))));
    }

    std::vector<Tool> tools;
    for (const auto& edgeData : data) {
        VertexEnd ends[2];
        if (!edgeData.closed) {
            TopoDS_Vertex vertices[2];
            TopExp::Vertices(edgeData.edge, vertices[0], vertices[1]);
            for (int i = 0; i < 2; ++i) {
                // ends[0] at the first parameter
                double parameter = 0.0;
                awayFrom(edgeData.edge, vertices[i], &parameter);
                bool atFirst
                    = std::abs(parameter - edgeData.first) < std::abs(parameter - edgeData.last);
                int slot = atFirst ? 0 : 1;
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
        tools.push_back(std::move(tool));
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

    // The fillet's history, composed from the stages' (section 3): the base's elements are
    // modified into their images; whatever else a tool's faces become is generated by its edge
    collectBaseImages();
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
    FC_LOG("exact construction refused: " << why);
    if (reason) {
        *reason = why;
    }
    return false;
}

}  // namespace Part::FilletFallback
