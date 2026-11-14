// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <limits>
#include <map>
#include <numbers>
#include <utility>

#include <BRepBuilderAPI_ModifyShape.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepLib.hxx>
#include <BRepTools.hxx>
#include <BRepTools_Modification.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Geom2dAPI_Interpolate.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2dAPI_PointsToBSpline.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <GeomAPI_PointsToBSpline.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <TColStd_HArray1OfReal.hxx>
#include <TColgp_Array1OfPnt2d.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TColgp_HArray1OfPnt2d.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Mat.hxx>

#include "RollingBallBlend.h"

namespace Part::RollingBallBlend
{
namespace
{

// A blend face whose ball residual is below this is a rolling ball already (a cylinder between planes, a torus)
constexpr double alreadyBall = 1e-6;
// The new surface between its stations: the stations are doubled until the residual is below this
constexpr double surfaceBound = 2e-7;
// The checks on the result
constexpr double resultBound = 1e-6;
// The tolerance the new geometry is handed over with
constexpr double newTolerance = 1e-7;
constexpr int firstStations = 31;
// The degree the surface's rows and the walls' pcurves are fitted with lengthwise: at 14 a face of 30 mm takes one
// to four spans at 1e-8 (measured: degree 8 takes 17 knots, degree 5 does not get there)
constexpr int fitDegree = 14;
constexpr int maxDoublings = 5;

struct NotRecognised
{
    std::string why;
};
struct Refusal
{
    std::string why;
};

Handle(Geom_Surface) untrimmed(Handle(Geom_Surface) surface)
{
    while (!surface.IsNull() && surface->IsKind(STANDARD_TYPE(Geom_RectangularTrimmedSurface))) {
        surface = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface)->BasisSurface();
    }
    return surface;
}

struct Foot
{
    gp_Pnt point;
    double u = 0.0;
    double v = 0.0;
    double distance = 0.0;
    gp_Vec normal;  // unit, from the foot to the point
    bool ok = false;
};

// The foot of a point on the untrimmed surface: Newton on (u, v) with second derivatives
Foot foot(const Handle(Geom_Surface)& surface, const gp_Pnt& from, const Foot* hint = nullptr)
{
    Foot result;
    if (hint && hint->ok) {
        result.u = hint->u;
        result.v = hint->v;
    }
    else {
        GeomAPI_ProjectPointOnSurf projection(from, surface);
        if (projection.NbPoints() < 1) {
            return result;
        }
        projection.LowerDistanceParameters(result.u, result.v);
    }
    gp_Pnt point;
    gp_Vec su, sv, suu, svv, suv;
    for (int iteration = 0; iteration < 40; ++iteration) {
        surface->D2(result.u, result.v, point, su, sv, suu, svv, suv);
        const gp_Vec r(from, point);
        const double f1 = r.Dot(su);
        const double f2 = r.Dot(sv);
        const double a = su.Dot(su) + r.Dot(suu);
        const double b = su.Dot(sv) + r.Dot(suv);
        const double d = sv.Dot(sv) + r.Dot(svv);
        const double det = a * d - b * b;
        if (std::fabs(det) < 1e-300) {
            return result;
        }
        const double du = (-f1 * d + f2 * b) / det;
        const double dv = (-f2 * a + f1 * b) / det;
        result.u += du;
        result.v += dv;
        if (std::fabs(du) * su.Magnitude() + std::fabs(dv) * sv.Magnitude() < 1e-14) {
            break;
        }
    }
    result.point = surface->Value(result.u, result.v);
    result.normal = gp_Vec(result.point, from);
    result.distance = result.normal.Magnitude();
    if (result.distance < 1e-12) {
        // On the surface: a foot without a direction
        result.normal = gp_Vec(0.0, 0.0, 0.0);
        result.ok = true;
        return result;
    }
    result.normal /= result.distance;
    result.ok = true;
    return result;
}

// The parameters of a point that lies on the surface (Gauss-Newton; exact at a zero residual)
bool parametersOf(const Handle(Geom_Surface)& surface, const gp_Pnt& on, double& u, double& v, bool hinted)
{
    if (!hinted) {
        GeomAPI_ProjectPointOnSurf projection(on, surface);
        if (projection.NbPoints() < 1) {
            return false;
        }
        projection.LowerDistanceParameters(u, v);
    }
    gp_Pnt point;
    gp_Vec su, sv;
    for (int iteration = 0; iteration < 40; ++iteration) {
        surface->D1(u, v, point, su, sv);
        const gp_Vec r(on, point);
        const double a = su.Dot(su);
        const double b = su.Dot(sv);
        const double d = sv.Dot(sv);
        const double det = a * d - b * b;
        if (std::fabs(det) < 1e-300) {
            return false;
        }
        const double f1 = r.Dot(su);
        const double f2 = r.Dot(sv);
        const double du = (-f1 * d + f2 * b) / det;
        const double dv = (-f2 * a + f1 * b) / det;
        u += du;
        v += dv;
        if (std::fabs(du) * su.Magnitude() + std::fabs(dv) * sv.Magnitude() < 1e-14) {
            break;
        }
    }
    return surface->Value(u, v).Distance(on) < 1e-7;
}

gp_Vec surfaceNormal(const Handle(Geom_Surface)& surface, double u, double v)
{
    gp_Pnt point;
    gp_Vec du, dv;
    surface->D1(u, v, point, du, dv);
    return du.Crossed(dv).Normalized();
}

// How near r a distance can be brought at a place: 3e-13, or what double precision leaves of it far from the origin
// (a wall 500 mm out has its points to 1e-13 at best)
double reachable(const gp_Pnt& at, double radius)
{
    const double size = std::max({std::fabs(at.X()), std::fabs(at.Y()), std::fabs(at.Z())}) + radius;
    return std::max(3e-13, 64.0 * std::numeric_limits<double>::epsilon() * size);

}

// Where Newton stops improving above reachable() it has still settled when it is within this: the
// noise of a wall's own evaluation is not known in advance (a 1000 mm wave prism stalls at 1e-11 on one
// platform and under it on another), the surface is judged at 1e-7 between stations and the result at
// 1e-6, and a refusal here would turn a fillet OCCT built into an error
constexpr double settled = 1e-9;

// One ball position: the centre and its two feet (on the face's side 0 and side 1 walls)
struct Station
{
    gp_Pnt centre;
    std::array<Foot, 2> feet;
    double t = 0.0;  // the lengthwise parameter of the new surface
    double residual = 0.0;
    bool ok = false;
};

// Newton for the centre: |c - S0| = r, |c - S1| = r, and no step along the centre curve (the step
// stays in the plane of the two contact normals), so the centre lands on the curve beside its start
Station solveStation(
    gp_Pnt centre,
    const std::array<Handle(Geom_Surface), 2>& walls,
    double radius,
    const Station* warm = nullptr
)
{
    Station station;
    if (warm) {
        station.feet = warm->feet;
    }
    // The best position so far, and how often in a row a step did not halve its residual
    Station best;
    best.residual = Precision::Infinite();
    int stalled = 0;
    auto settle = [&]() {
        if (best.residual < settled) {
            best.ok = true;
            return best;
        }
        station.centre = centre;
        return station;
    };
    for (int iteration = 0; iteration <= 40; ++iteration) {
        for (int side = 0; side < 2; ++side) {
            station.feet[side] = foot(walls[side], centre, &station.feet[side]);
            if (!station.feet[side].ok) {
                return settle();
            }
        }
        const std::array<double, 2> f = {station.feet[0].distance - radius, station.feet[1].distance - radius};
        station.residual = std::max(std::fabs(f[0]), std::fabs(f[1]));
        if (station.residual < reachable(centre, radius)) {
            station.ok = true;
            break;
        }
        stalled = station.residual < 0.5 * best.residual ? 0 : stalled + 1;
        if (station.residual < best.residual) {
            best = station;
            best.centre = centre;
        }
        if (stalled >= 3) {
            return settle();
        }
        const gp_Vec& g0 = station.feet[0].normal;
        const gp_Vec& g1 = station.feet[1].normal;
        gp_Vec tangent = g0.Crossed(g1);
        if (tangent.Magnitude() < 1e-9) {
            return station;
        }
        tangent.Normalize();
        gp_Mat jacobian(g0.X(), g0.Y(), g0.Z(), g1.X(), g1.Y(), g1.Z(), tangent.X(), tangent.Y(), tangent.Z());
        if (std::fabs(jacobian.Determinant()) < 1e-12) {
            return station;
        }
        centre.SetXYZ(centre.XYZ() + jacobian.Inverted() * gp_XYZ(-f[0], -f[1], 0.0));
    }
    if (!station.ok) {
        return settle();
    }
    station.centre = centre;
    return station;
}

// The circle through three points: its centre and its plane's normal
bool circleThrough(const gp_Pnt& p0, const gp_Pnt& p1, const gp_Pnt& p2, gp_Pnt& centre, gp_Vec& normal)
{
    const gp_Vec a(p0, p1);
    const gp_Vec b(p0, p2);
    const gp_Vec n = a.Crossed(b);
    const double nn = n.SquareMagnitude();
    if (nn < 1e-24) {
        return false;
    }
    const gp_Vec offset = (n.Crossed(a) * b.SquareMagnitude() + b.Crossed(n) * a.SquareMagnitude()) / (2.0 * nn);
    centre = p0.Translated(offset);
    normal = n / std::sqrt(nn);
    return true;
}

Handle(Geom2d_BSplineCurve) segment2d(const gp_Pnt2d& p0, const gp_Pnt2d& p1, double first, double last)
{
    TColgp_Array1OfPnt2d poles(1, 2);
    poles(1) = p0;
    poles(2) = p1;
    TColStd_Array1OfReal knots(1, 2);
    knots(1) = first;
    knots(2) = last;
    TColStd_Array1OfInteger multiplicities(1, 2);
    multiplicities(1) = 2;
    multiplicities(2) = 2;
    return new Geom2d_BSplineCurve(poles, knots, multiplicities, 1);
}

struct Side
{
    TopoDS_Face wall;
    Handle(Geom_Surface) surface;       // untrimmed
    std::vector<TopoDS_Edge> contacts;  // one edge, or several in a row
};

// A blend face's end on a face of the base (where the other end kind is a seam to the next blend face)
struct FaceEnd
{
    bool present = false;
    TopoDS_Edge edge;
    TopoDS_Face face;
    Handle(Geom_Surface) surface;           // untrimmed
    std::array<TopoDS_Vertex, 2> vertices;  // on side 0 and on side 1
    std::array<TopoDS_Edge, 2> slides;      // the base's edge between each wall and the end face
    double sign = 1.0;                      // times the distance to the end face: negative on the blend face's side
    // The end edge on the new surface, per arc fraction: the lengthwise parameter, the point, the end face's parameters
    std::vector<double> across;
    std::vector<double> along;
    std::vector<gp_Pnt> points;
    std::vector<gp_Pnt2d> onFace;
};

struct Blend
{
    TopoDS_Face face;
    Handle(Geom_Surface) old;
    std::array<Side, 2> sides;
    std::array<TopoDS_Edge, 2> cross;  // at the start and at the end of the lengthwise parameter: a seam or an end edge
    std::array<int, 2> seams = {-1, -1};
    std::array<FaceEnd, 2> ends;
    // OCCT's surface: across from side 0 (0) to side 1 (1), lengthwise from lengthFirst to lengthLast
    bool lengthIsV = true;
    double acrossAt0 = 0.0;
    double acrossAt1 = 0.0;
    double lengthFirst = 0.0;
    double lengthLast = 0.0;
    int chain = -1;
    // A face of exact form (a cylinder between planes, a torus) beside a spline face of its chain: a rolling ball
    // by form. Its surface and its contact edges stay; only its seam to the spline face takes the ball's arc
    bool kept = false;
    std::vector<Station> stations;
    Handle(Geom_BSplineSurface) surface;
    double length = 0.0;
    // Places on each wall along OCCT's contact edges: where a foot is looked for first. (A projection
    // onto a whole free-form wall costs a thousand times a Newton step from nearby)
    std::array<std::vector<Foot>, 2> seeds;

    const Foot* seed(int side, const gp_Pnt& beside) const
    {
        const Foot* nearest = nullptr;
        double least = Precision::Infinite();
        for (const Foot& candidate : seeds[side]) {
            const double distance = candidate.point.SquareDistance(beside);
            if (distance < least) {
                least = distance;
                nearest = &candidate;
            }
        }
        return nearest;
    }

    gp_Pnt oldPoint(double across, double lengthwise) const
    {
        const double a = acrossAt0 + (acrossAt1 - acrossAt0) * across;
        return lengthIsV ? old->Value(a, lengthwise) : old->Value(lengthwise, a);
    }
    // OCCT's section at a lengthwise parameter: its circle's centre and plane
    bool oldSection(double lengthwise, gp_Pnt& centre, gp_Vec& normal) const
    {
        return circleThrough(oldPoint(0.0, lengthwise), oldPoint(0.5, lengthwise), oldPoint(1.0, lengthwise), centre, normal);
    }
    std::array<Handle(Geom_Surface), 2> walls() const
    {
        return {sides[0].surface, sides[1].surface};
    }
};

struct Seam
{
    TopoDS_Edge edge;
    std::array<int, 2> blends = {-1, -1};
    std::array<TopoDS_Vertex, 2> vertices;
    std::array<gp_Pnt, 2> points;  // the vertices' new points
    gp_Pnt centre;
    TopoDS_Edge tangentEdge;  // K: between the two wall faces the contact crosses
    int sliding = -1;         // which vertex lies on K
    double parameterOnK = 0.0;
    // Beside a face of exact form: its contact edges, which vertex of the seam slides along each, and to where
    struct KeptSlide
    {
        TopoDS_Edge edge;
        int vertex = 0;
        double parameter = 0.0;
    };
    std::vector<KeptSlide> keptSlides;
};

struct EdgeNew
{
    Handle(Geom_Curve) curve;
    TopoDS_Vertex forward;
    double first = 0.0;
    double last = 0.0;
};

class Modification: public BRepTools_Modification
{
public:
    std::map<const TopoDS_TShape*, Handle(Geom_Surface)> surfaces;
    std::map<const TopoDS_TShape*, EdgeNew> curves;
    std::map<const TopoDS_TShape*, EdgeNew> slides;  // untouched edges whose vertex slides
    std::map<std::pair<const TopoDS_TShape*, const TopoDS_TShape*>, Handle(Geom2d_Curve)> pcurves;
    std::map<const TopoDS_TShape*, gp_Pnt> points;
    std::map<const TopoDS_TShape*, double> pointTolerances;  // where not the default

    Standard_Boolean NewSurface(
        const TopoDS_Face& face,
        Handle(Geom_Surface)& surface,
        TopLoc_Location& location,
        Standard_Real& tolerance,
        Standard_Boolean& reverseWires,
        Standard_Boolean& reverseFace
    ) override
    {
        const auto found = surfaces.find(face.TShape().get());
        if (found == surfaces.end()) {
            return Standard_False;
        }
        surface = found->second;
        location = TopLoc_Location();
        tolerance = newTolerance;
        reverseWires = Standard_False;
        reverseFace = Standard_False;
        return Standard_True;
    }

    Standard_Boolean NewCurve(
        const TopoDS_Edge& edge,
        Handle(Geom_Curve)& curve,
        TopLoc_Location& location,
        Standard_Real& tolerance
    ) override
    {
        const auto found = curves.find(edge.TShape().get());
        if (found == curves.end()) {
            return Standard_False;
        }
        curve = found->second.curve;
        location = TopLoc_Location();
        tolerance = newTolerance;
        return Standard_True;
    }

    Standard_Boolean NewPoint(const TopoDS_Vertex& vertex, gp_Pnt& point, Standard_Real& tolerance) override
    {
        const auto found = points.find(vertex.TShape().get());
        if (found == points.end()) {
            return Standard_False;
        }
        point = found->second;
        const auto wider = pointTolerances.find(vertex.TShape().get());
        tolerance = wider == pointTolerances.end() ? newTolerance : wider->second;
        return Standard_True;
    }

    Standard_Boolean NewCurve2d(
        const TopoDS_Edge& edge,
        const TopoDS_Face& face,
        const TopoDS_Edge& /*newEdge*/,
        const TopoDS_Face& /*newFace*/,
        Handle(Geom2d_Curve)& curve,
        Standard_Real& tolerance
    ) override
    {
        const auto found = pcurves.find({edge.TShape().get(), face.TShape().get()});
        if (found == pcurves.end()) {
            return Standard_False;
        }
        curve = found->second;
        tolerance = newTolerance;
        return Standard_True;
    }

    Standard_Boolean NewParameter(
        const TopoDS_Vertex& vertex,
        const TopoDS_Edge& edge,
        Standard_Real& parameter,
        Standard_Real& tolerance
    ) override
    {
        auto found = curves.find(edge.TShape().get());
        if (found == curves.end()) {
            found = slides.find(edge.TShape().get());
            if (found == slides.end()) {
                return Standard_False;
            }
        }
        parameter = vertex.IsSame(found->second.forward) ? found->second.first : found->second.last;
        tolerance = newTolerance;
        return Standard_True;
    }

    GeomAbs_Shape Continuity(
        const TopoDS_Edge& edge,
        const TopoDS_Face& face1,
        const TopoDS_Face& face2,
        const TopoDS_Edge& /*newEdge*/,
        const TopoDS_Face& /*newFace1*/,
        const TopoDS_Face& /*newFace2*/
    ) override
    {
        return BRep_Tool::Continuity(edge, face1, face2);
    }
};

class Maker: public BRepBuilderAPI_ModifyShape
{
public:
    Maker(const TopoDS_Shape& shape, const Handle(BRepTools_Modification)& modification)
    {
        myModification = modification;
        DoModif(shape);
    }
};

// The ball residual of a surface patch against two walls: centre = point -/+ r normal at distance r from both
double residualOfSurface(
    const Handle(Geom_Surface)& surface,
    double u0,
    double u1,
    double v0,
    double v1,
    const std::array<Handle(Geom_Surface), 2>& walls,
    double radius,
    int acrossCount,
    int lengthCount,
    const Blend* seeds = nullptr
)
{
    auto first = [&](int side, const gp_Pnt& centre) {
        return foot(walls[side], centre, seeds ? seeds->seed(side, centre) : nullptr);
    };
    // The side of the ball: once, at the middle
    double sign = 0.0;
    {
        const double u = 0.5 * (u0 + u1);
        const double v = 0.5 * (v0 + v1);
        const gp_Pnt point = surface->Value(u, v);
        const gp_Vec normal = surfaceNormal(surface, u, v);
        double best = Precision::Infinite();
        for (const double candidate : {-1.0, 1.0}) {
            const gp_Pnt centre = point.Translated(normal * (candidate * radius));
            const Foot f0 = first(0, centre);
            const Foot f1 = first(1, centre);
            if (f0.ok && f1.ok) {
                const double r = std::max(std::fabs(f0.distance - radius), std::fabs(f1.distance - radius));
                if (r < best) {
                    best = r;
                    sign = candidate;
                }
            }
        }
        if (sign == 0.0) {
            return Precision::Infinite();
        }
    }
    double worst = 0.0;
    for (int i = 0; i < acrossCount; ++i) {
        // Along a row the feet follow each other: each starts from the one before
        std::array<Foot, 2> feet;
        for (int j = 0; j < lengthCount; ++j) {
            const double u = u0 + (u1 - u0) * (i + 0.5) / acrossCount;
            const double v = v0 + (v1 - v0) * (j + 0.5) / lengthCount;
            const gp_Pnt point = surface->Value(u, v);
            const gp_Pnt centre = point.Translated(surfaceNormal(surface, u, v) * (sign * radius));
            for (int side = 0; side < 2; ++side) {
                feet[side] = feet[side].ok ? foot(walls[side], centre, &feet[side]) : first(side, centre);
                if (!feet[side].ok) {
                    return Precision::Infinite();
                }
                worst = std::max(worst, std::fabs(feet[side].distance - radius));
            }
        }
    }
    return worst;
}

struct Context
{
    TopoDS_Shape shape;
    double radius = 0.0;
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
    std::vector<Blend> blends;
    std::vector<Seam> seams;

    int blendOf(const TopoDS_Shape& face) const
    {
        for (size_t i = 0; i < blends.size(); ++i) {
            if (blends[i].face.IsSame(face)) {
                return static_cast<int>(i);
            }
        }
        return -1;
    }
};

bool identity(const TopoDS_Shape& shape)
{
    return shape.Location().IsIdentity();
}

// Is a pcurve an iso line of its surface? which = 0: u constant, 1: v constant
bool isoLine(const Handle(Geom2d_Curve)& pcurve, double first, double last, int which, double& value)
{
    const gp_Pnt2d p0 = pcurve->Value(first);
    double spread = 0.0;
    for (int k = 1; k <= 8; ++k) {
        const gp_Pnt2d p = pcurve->Value(first + (last - first) * k / 8.0);
        spread = std::max(spread, std::fabs((which == 0 ? p.X() : p.Y()) - (which == 0 ? p0.X() : p0.Y())));
    }
    value = which == 0 ? p0.X() : p0.Y();
    return spread < 1e-7;
}

// The edges of a blend face sorted into contact edges (iso lines of OCCT's surface along the face; the other face is a
// wall), and at each end of the face a seam (the other face is a blend) or an end edge (the other face is the base's)
void classify(Context& context, Blend& blend)
{
    if (!identity(blend.face)) {
        throw NotRecognised {"a blend face with a location"};
    }
    blend.old = BRep_Tool::Surface(blend.face);
    double u0 {}, u1 {}, v0 {}, v1 {};
    BRepTools::UVBounds(blend.face, u0, u1, v0, v1);
    const std::array<double, 2> low = {u0, v0};
    const std::array<double, 2> high = {u1, v1};
    struct Info
    {
        TopoDS_Edge edge;
        TopoDS_Face other;
        bool blend = false;
        std::array<bool, 2> iso = {false, false};
        std::array<double, 2> value = {0.0, 0.0};
        gp_Pnt2d middle;
    };
    std::vector<Info> infos;
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(blend.face, TopAbs_EDGE, edges);
    for (int i = 1; i <= edges.Extent(); ++i) {
        Info info;
        info.edge = TopoDS::Edge(edges(i));
        if (BRep_Tool::Degenerated(info.edge)) {
            throw NotRecognised {"a blend face with a degenerate edge"};
        }
        if (!identity(info.edge)) {
            throw NotRecognised {"a blend face's edge with a location"};
        }
        const TopTools_ListOfShape& faces = context.edgeFaces.FindFromKey(info.edge);
        int count = 0;
        for (TopTools_ListOfShape::Iterator it(faces); it.More(); it.Next()) {
            ++count;
            if (!it.Value().IsSame(blend.face)) {
                info.other = TopoDS::Face(it.Value());
            }
        }
        if (count != 2 || info.other.IsNull()) {
            throw NotRecognised {"a blend face closed on itself or with a free edge"};
        }
        info.blend = context.blendOf(info.other) >= 0;
        double first {}, last {};
        const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(info.edge, blend.face, first, last);
        if (pcurve.IsNull()) {
            throw NotRecognised {"a blend face's edge without a pcurve"};
        }
        for (int which = 0; which < 2; ++which) {
            info.iso[which] = isoLine(pcurve, first, last, which, info.value[which]);
        }
        info.middle = pcurve->Value(0.5 * (first + last));
        infos.push_back(info);
    }
    auto at = [&](const Info& info, int which, double bound) {
        return info.iso[which] && std::fabs(info.value[which] - bound) < 1e-7 * std::max(1.0, high[which] - low[which]);
    };
    // Across is the parameter in which the walls' edges are the surface's two bounds and the seams are not iso lines
    auto fits = [&](int across) {
        bool atLow = false;
        bool atHigh = false;
        for (const Info& info : infos) {
            if (info.blend) {
                if (!at(info, 1 - across, low[1 - across]) && !at(info, 1 - across, high[1 - across])) {
                    return false;
                }
            }
            else {
                atLow = atLow || at(info, across, low[across]);
                atHigh = atHigh || at(info, across, high[across]);
            }
        }
        return atLow && atHigh;
    };
    bool fitsU = fits(0);
    bool fitsV = fits(1);
    if (fitsU && fitsV) {
        // An end edge that is an iso line too: OCCT's blend is of degree 2 with three poles across
        const Handle(Geom_BSplineSurface) spline = Handle(Geom_BSplineSurface)::DownCast(blend.old);
        const bool arcU = !spline.IsNull() && spline->UDegree() == 2 && spline->NbUPoles() == 3;
        const bool arcV = !spline.IsNull() && spline->VDegree() == 2 && spline->NbVPoles() == 3;
        if (arcU == arcV) {
            throw NotRecognised {"a blend surface whose direction across is not clear"};
        }
        fitsU = arcU;
        fitsV = arcV;
    }
    if (!fitsU && !fitsV) {
        throw NotRecognised {"contact edges that are not the blend surface's bounds"};
    }
    const int across = fitsU ? 0 : 1;
    blend.lengthIsV = across == 0;
    blend.acrossAt0 = low[across];
    blend.acrossAt1 = high[across];
    blend.lengthFirst = low[1 - across];
    blend.lengthLast = high[1 - across];
    if (blend.acrossAt1 - blend.acrossAt0 < 1e-9 || blend.lengthLast - blend.lengthFirst < 1e-9) {
        throw NotRecognised {"a blend surface of no width or length"};
    }
    const double middle = 0.5 * (blend.lengthFirst + blend.lengthLast);
    for (const Info& info : infos) {
        int side = -1;
        if (!info.blend && at(info, across, low[across])) {
            side = 0;
        }
        else if (!info.blend && at(info, across, high[across])) {
            side = 1;
        }
        if (side >= 0) {
            Side& s = blend.sides[side];
            if (!s.contacts.empty() && !s.wall.IsSame(info.other)) {
                throw NotRecognised {"a wall that changes face along a blend face"};
            }
            s.wall = info.other;
            s.surface = untrimmed(BRep_Tool::Surface(info.other));
            s.contacts.push_back(info.edge);
            continue;
        }
        const int end = (across == 0 ? info.middle.Y() : info.middle.X()) < middle ? 0 : 1;
        if (!blend.cross[end].IsNull()) {
            // Several faces of the base at one end, or a corner patch
            throw NotRecognised {"a blend face that ends in several edges"};
        }
        blend.cross[end] = info.edge;
        if (info.blend) {
            if (!at(info, 1 - across, end == 0 ? blend.lengthFirst : blend.lengthLast)) {
                throw NotRecognised {"a seam that is not the blend surface's end"};
            }
        }
        else {
            FaceEnd& faceEnd = blend.ends[end];
            faceEnd.present = true;
            faceEnd.edge = info.edge;
            faceEnd.face = info.other;
            faceEnd.surface = untrimmed(BRep_Tool::Surface(info.other));
        }
    }
    if (blend.cross[0].IsNull() || blend.cross[1].IsNull()) {
        throw NotRecognised {"a blend face without an edge at one of its ends"};
    }
    if (blend.sides[0].contacts.empty() || blend.sides[1].contacts.empty()
        || blend.sides[0].wall.IsSame(blend.sides[1].wall)) {
        throw NotRecognised {"a blend face without two walls"};
    }
    // A contact side in several edges: the vertices between them belong to those edges only
    for (const Side& s : blend.sides) {
        if (s.contacts.size() < 2) {
            continue;
        }
        TopTools_IndexedDataMapOfShapeListOfShape own;
        for (const TopoDS_Edge& edge : s.contacts) {
            TopExp::MapShapesAndAncestors(edge, TopAbs_VERTEX, TopAbs_EDGE, own);
        }
        for (int i = 1; i <= own.Extent(); ++i) {
            if (own(i).Extent() != 2) {
                continue;
            }
            // (the shape's map lists an edge once per face it is found through)
            TopTools_IndexedMapOfShape arriving;
            for (TopTools_ListOfShape::Iterator it(context.vertexEdges.FindFromKey(own.FindKey(i))); it.More(); it.Next()) {
                arriving.Add(it.Value());
            }
            if (arriving.Extent() != 2) {
                throw NotRecognised {"a contact edge split at a vertex where another edge arrives"};
            }
        }
    }
    // The new surface runs across from side 0 to side 1 and lengthwise as OCCT's does. Its normal
    // must point as the old surface's (the face keeps its orientation): otherwise the sides swap
    const double a = 0.5 * (blend.acrossAt0 + blend.acrossAt1);
    gp_Pnt point;
    gp_Vec du, dv;
    blend.lengthIsV ? blend.old->D1(a, middle, point, du, dv) : blend.old->D1(middle, a, point, du, dv);
    const gp_Vec along = blend.lengthIsV ? dv : du;
    const gp_Vec acrossVector(blend.oldPoint(0.0, middle), blend.oldPoint(1.0, middle));
    if (acrossVector.Crossed(along).Dot(du.Crossed(dv)) < 0.0) {
        std::swap(blend.sides[0], blend.sides[1]);
        std::swap(blend.acrossAt0, blend.acrossAt1);
    }
    for (int side = 0; side < 2; ++side) {
        const Side& s = blend.sides[side];
        for (const TopoDS_Edge& edge : s.contacts) {
            double first {}, last {};
            const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, s.wall, first, last);
            if (pcurve.IsNull()) {
                throw NotRecognised {"a contact edge without a pcurve on its wall"};
            }
            for (int k = 0; k <= 8; ++k) {
                const gp_Pnt2d at = pcurve->Value(first + (last - first) * k / 8.0);
                Foot seed;
                seed.u = at.X();
                seed.v = at.Y();
                seed.point = s.surface->Value(seed.u, seed.v);
                seed.ok = true;
                blend.seeds[side].push_back(seed);
            }
        }
    }
}

// A blend face of exact form beside a spline face: its two walls and its contact edges on them. Its other ends are
// its own (a seam to the next exact face, a mitre: none of them changes), so nothing is asked of them
void classifyKept(const Context& context, Blend& blend)
{
    if (!identity(blend.face)) {
        throw NotRecognised {"a blend face with a location"};
    }
    blend.old = BRep_Tool::Surface(blend.face);
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(blend.face, TopAbs_EDGE, edges);
    for (int i = 1; i <= edges.Extent(); ++i) {
        const TopoDS_Edge edge = TopoDS::Edge(edges(i));
        if (BRep_Tool::Degenerated(edge)) {
            throw NotRecognised {"a blend face with a degenerate edge"};
        }
        TopoDS_Face other;
        int count = 0;
        for (TopTools_ListOfShape::Iterator it(context.edgeFaces.FindFromKey(edge)); it.More(); it.Next()) {
            ++count;
            if (!it.Value().IsSame(blend.face)) {
                other = TopoDS::Face(it.Value());
            }
        }
        if (count != 2 || other.IsNull()) {
            throw NotRecognised {"a blend face closed on itself or with a free edge"};
        }
        if (context.blendOf(other) >= 0) {
            continue;
        }
        Side* side = nullptr;
        for (Side& s : blend.sides) {
            if (side == nullptr && (s.contacts.empty() || s.wall.IsSame(other))) {
                side = &s;
            }
        }
        if (side == nullptr) {
            throw NotRecognised {"a blend face of exact form with more than two walls"};
        }
        side->wall = other;
        side->surface = untrimmed(BRep_Tool::Surface(other));
        side->contacts.push_back(edge);
        double first {}, last {};
        const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, other, first, last);
        if (pcurve.IsNull()) {
            throw NotRecognised {"a contact edge without a pcurve on its wall"};
        }
        for (int k = 0; k <= 8; ++k) {
            const gp_Pnt2d at = pcurve->Value(first + (last - first) * k / 8.0);
            Foot seed;
            seed.u = at.X();
            seed.v = at.Y();
            seed.point = side->surface->Value(seed.u, seed.v);
            seed.ok = true;
            blend.seeds[side == &blend.sides[0] ? 0 : 1].push_back(seed);
        }
    }
    if (blend.sides[0].contacts.empty() || blend.sides[1].contacts.empty()) {
        throw NotRecognised {"a blend face without two walls"};
    }
}

int sideAt(const Blend& blend, const TopoDS_Vertex& vertex)
{
    for (int side = 0; side < 2; ++side) {
        for (const TopoDS_Edge& edge : blend.sides[side].contacts) {
            TopoDS_Vertex v1, v2;
            TopExp::Vertices(edge, v1, v2);
            if (v1.IsSame(vertex) || v2.IsSame(vertex)) {
                return side;
            }
        }
    }
    return -1;
}

// The split station of a seam: the ball where a contact point crosses the tangent edge K between two wall faces
void solveSeam(Context& context, Seam& seam)
{
    const Blend& blendA = context.blends[seam.blends[0]];
    const Blend& blendB = context.blends[seam.blends[1]];
    TopExp::Vertices(seam.edge, seam.vertices[0], seam.vertices[1]);
    if (seam.vertices[0].IsSame(seam.vertices[1])) {
        throw NotRecognised {"a closed seam"};
    }
    std::array<int, 2> sideA {};
    std::array<int, 2> sideB {};
    for (int i = 0; i < 2; ++i) {
        sideA[i] = sideAt(blendA, seam.vertices[i]);
        sideB[i] = sideAt(blendB, seam.vertices[i]);
        if (sideA[i] < 0 || sideB[i] < 0) {
            throw NotRecognised {"a seam whose vertex is on no contact edge"};
        }
        const TopoDS_Face& wallA = blendA.sides[sideA[i]].wall;
        const TopoDS_Face& wallB = blendB.sides[sideB[i]].wall;
        if (wallA.IsSame(wallB)) {
            continue;
        }
        if (seam.sliding >= 0) {
            throw NotRecognised {"a seam where both walls change face"};
        }
        const TopTools_ListOfShape& edges = context.vertexEdges.FindFromKey(seam.vertices[i]);
        for (TopTools_ListOfShape::Iterator it(edges); it.More(); it.Next()) {
            const TopTools_ListOfShape& faces = context.edgeFaces.FindFromKey(it.Value());
            bool a = false;
            bool b = false;
            for (TopTools_ListOfShape::Iterator jt(faces); jt.More(); jt.Next()) {
                a = a || jt.Value().IsSame(wallA);
                b = b || jt.Value().IsSame(wallB);
            }
            if (a && b) {
                seam.tangentEdge = TopoDS::Edge(it.Value());
            }
        }
        if (seam.tangentEdge.IsNull()) {
            throw NotRecognised {"a seam whose two walls share no edge"};
        }
        seam.sliding = i;
    }
    if (seam.sliding < 0) {
        throw NotRecognised {"a seam with the same two walls on both sides"};
    }
    const int i = seam.sliding;
    const Handle(Geom_Surface) wallA = blendA.sides[sideA[i]].surface;
    const Handle(Geom_Surface) wallB = blendB.sides[sideB[i]].surface;
    const Handle(Geom_Surface) common = blendA.sides[1 - sideA[i]].surface;
    double first {}, last {};
    const Handle(Geom_Curve) curve = BRep_Tool::Curve(seam.tangentEdge, first, last);
    if (curve.IsNull()) {
        throw NotRecognised {"a wall edge without a curve"};
    }
    const double old = BRep_Tool::Parameter(seam.vertices[i], seam.tangentEdge);
    // OCCT's section at this end of the face says on which side of the wall the ball is
    const bool atStart = blendA.cross[0].IsSame(seam.edge);
    gp_Pnt start;
    gp_Vec plane;
    if (!blendA.oldSection(atStart ? blendA.lengthFirst : blendA.lengthLast, start, plane)) {
        throw NotRecognised {"a section of the blend that is no circle"};
    }
    double uA = 0.0;
    double vA = 0.0;
    bool hinted = false;
    Foot hintCommon;
    if (const Foot* seed = blendA.seed(sideA[i], start)) {
        uA = seed->u;
        vA = seed->v;
        hinted = true;
    }
    if (const Foot* seed = blendA.seed(1 - sideA[i], start)) {
        hintCommon = *seed;
    }
    double sign = 0.0;
    gp_Pnt centre;
    auto residual = [&](double parameter) {
        const gp_Pnt onK = curve->Value(parameter);
        if (!parametersOf(wallA, onK, uA, vA, hinted)) {
            throw NotRecognised {"a wall edge that does not lie on its wall"};
        }
        hinted = true;
        const gp_Vec normal = surfaceNormal(wallA, uA, vA);
        if (sign == 0.0) {
            sign = gp_Vec(onK, start).Dot(normal) > 0.0 ? 1.0 : -1.0;
        }
        centre = onK.Translated(normal * (sign * context.radius));
        hintCommon = foot(common, centre, &hintCommon);
        if (!hintCommon.ok) {
            throw Refusal {"the wall under a seam has no foot"};
        }
        return hintCommon.distance - context.radius;
    };
    double s0 = old;
    double f0 = residual(s0);
    double s1 = old + 1e-4 * (last - first) * (old > 0.5 * (first + last) ? -1.0 : 1.0);
    double f1 = residual(s1);
    const double within = reachable(start, context.radius);
    bool converged = std::fabs(f0) < within;
    if (converged) {
        s1 = s0;
        f1 = residual(s1);
    }
    // The best place so far: where the secant stops improving above `within`, it has settled there
    double sBest = std::fabs(f0) < std::fabs(f1) ? s0 : s1;
    double fBest = std::min(std::fabs(f0), std::fabs(f1));
    for (int iteration = 0; iteration < 60 && !converged; ++iteration) {
        if (std::fabs(f1 - f0) < 1e-300) {
            break;
        }
        const double s2 = s1 - f1 * (s1 - s0) / (f1 - f0);
        s0 = s1;
        f0 = f1;
        s1 = s2;
        f1 = residual(s1);
        converged = std::fabs(f1) < within;
        if (std::fabs(f1) < fBest) {
            fBest = std::fabs(f1);
            sBest = s1;
        }
    }
    if (!converged) {
        if (fBest >= settled) {
            throw Refusal {"a seam's ball position did not converge"};
        }
        s1 = sBest;
        f1 = residual(s1);
    }
    // The ball must touch the next wall face at the same point: K is a tangent edge
    const gp_Pnt onK = curve->Value(s1);
    const Foot other = foot(wallB, centre, blendB.seed(sideB[i], centre));
    if (!other.ok || std::fabs(other.distance - context.radius) > 1e-9 || other.point.Distance(onK) > 1e-7) {
        throw NotRecognised {"walls that are not tangent along their common edge"};
    }
    // The vertex slides along K. It may not pass K's other vertex or leave K's curve
    const double otherEnd = std::fabs(old - first) < std::fabs(old - last) ? last : first;
    if ((s1 - otherEnd) * (old - otherEnd) <= 0.0 || s1 < curve->FirstParameter() || s1 > curve->LastParameter()) {
        throw Refusal {"a seam crosses a vertex of the wall"};
    }
    seam.centre = centre;
    seam.parameterOnK = s1;
    seam.points[i] = onK;
    seam.points[1 - i] = hintCommon.point;
    // A face of exact form beside the seam stays as it is: the ball's arc must lie on it, and the arc's ends on its
    // contact edges, which the seam's vertices slide along
    if (blendB.kept) {
        const double within = std::max(1e-9, 1e3 * reachable(centre, context.radius));
        const gp_Vec e0(centre, seam.points[0]);
        const gp_Vec e1(centre, seam.points[1]);
        const double angle = e0.Angle(e1);
        Foot onKept;
        for (int k = 0; k <= 8; ++k) {
            const double fraction = k / 8.0;
            const gp_Vec direction = e0 * std::sin((1.0 - fraction) * angle) + e1 * std::sin(fraction * angle);
            const gp_Pnt point = centre.Translated(direction.Normalized() * context.radius);
            onKept = foot(blendB.old, point, onKept.ok ? &onKept : nullptr);
            if (!onKept.ok || onKept.distance > within) {
                throw NotRecognised {"a blend face of exact form that is not the ball's surface at its seam to a spline face"};
            }
        }
        for (int v = 0; v < 2; ++v) {
            for (const TopoDS_Edge& edge : blendB.sides[sideB[v]].contacts) {
                TopoDS_Vertex v1, v2;
                TopExp::Vertices(edge, v1, v2);
                if (!v1.IsSame(seam.vertices[v]) && !v2.IsSame(seam.vertices[v])) {
                    continue;
                }
                if (v1.IsSame(v2)) {
                    throw NotRecognised {"a closed contact edge on a blend face of exact form"};
                }
                double edgeFirst {}, edgeLast {};
                const Handle(Geom_Curve) along = BRep_Tool::Curve(edge, edgeFirst, edgeLast);
                if (along.IsNull() || !identity(edge)) {
                    throw NotRecognised {"a contact edge of a blend face of exact form without a curve in place"};
                }
                GeomAPI_ProjectPointOnCurve projection(seam.points[v], along);
                if (projection.NbPoints() < 1 || projection.LowerDistance() > within) {
                    throw NotRecognised {"a blend face of exact form whose contact edge is not the ball's"};
                }
                double at = projection.LowerDistanceParameter();
                const double was = BRep_Tool::Parameter(seam.vertices[v], edge);
                if (along->IsPeriodic()) {
                    at += along->Period() * std::round((was - at) / along->Period());
                }
                // It may not pass the edge's other vertex
                const double otherEnd = std::fabs(was - edgeFirst) < std::fabs(was - edgeLast) ? edgeLast : edgeFirst;
                if ((at - otherEnd) * (was - otherEnd) <= 0.0) {
                    throw Refusal {"a seam crosses a vertex of the wall"};
                }
                seam.keptSlides.push_back({edge, v, at});
            }
        }
        if (seam.keptSlides.size() != 2) {
            throw NotRecognised {"a seam whose vertices are not the ends of the exact face's two contact edges"};
        }
    }
}

gp_Vec tangentAt(const Station& station)
{
    gp_Vec tangent = station.feet[0].normal.Crossed(station.feet[1].normal);
    if (tangent.Magnitude() < 1e-9) {
        throw Refusal {"walls that are tangent under the ball"};
    }
    return tangent.Normalized();
}

// A point of a station's arc: 0 at its foot on side 0, 1 at its foot on side 1
gp_Pnt arcPoint(const Station& station, double fraction)
{
    const gp_Vec e0(station.centre, station.feet[0].point);
    const gp_Vec e1(station.centre, station.feet[1].point);
    const double angle = e0.Angle(e1);
    const gp_Vec direction = e0 * std::sin((1.0 - fraction) * angle) + e1 * std::sin(fraction * angle);
    return station.centre.Translated(direction.Normalized() * e0.Magnitude());
}

// The signed distance from a point to an end face's surface: negative on the blend face's side
double endDistance(const FaceEnd& end, const gp_Pnt& point, Foot& hint)
{
    hint = foot(end.surface, point, &hint);
    if (!hint.ok) {
        throw Refusal {"an end face has no foot"};
    }
    return end.sign * gp_Vec(hint.point, point).Dot(surfaceNormal(end.surface, hint.u, hint.v));
}

// Does a foot lie on the wall's own surface (a spline wall has bounds; beyond them it is only extrapolated)
bool onWall(const Handle(Geom_Surface)& wall, const Foot& at)
{
    if (!wall->IsKind(STANDARD_TYPE(Geom_BSplineSurface)) && !wall->IsKind(STANDARD_TYPE(Geom_BezierSurface))) {
        return true;
    }
    double u0 {}, u1 {}, v0 {}, v1 {};
    wall->Bounds(u0, u1, v0, v1);
    return (wall->IsUPeriodic() || (at.u >= u0 - 1e-9 && at.u <= u1 + 1e-9))
        && (wall->IsVPeriodic() || (at.v >= v0 - 1e-9 && at.v <= v1 + 1e-9));
}

// The stations of a face. OCCT's sections, each brought onto the centre curve, say where the curve runs; a seam's
// split station ends it exactly; past an end on a face of the base the curve is marched on until the ball's arc
// has left that face. The stations are then spread evenly along the curve
void solveStations(const Context& context, Blend& blend, int interior)
{
    const auto walls = blend.walls();
    const double radius = context.radius;
    std::vector<Station> sections;
    {
        Station previous;
        for (int k = 0; k <= interior + 1; ++k) {
            const double lengthwise = blend.lengthFirst + (blend.lengthLast - blend.lengthFirst) * k / (interior + 1);
            gp_Pnt centre;
            gp_Vec normal;
            if (!blend.oldSection(lengthwise, centre, normal)) {
                throw NotRecognised {"a section of the blend that is no circle"};
            }
            Station seeded;
            if (!previous.ok) {
                for (int side = 0; side < 2; ++side) {
                    if (const Foot* seed = blend.seed(side, centre)) {
                        seeded.feet[side] = *seed;
                    }
                }
            }
            const Station station = solveStation(centre, walls, radius, previous.ok ? &previous : &seeded);
            if (!station.ok) {
                if (k == 0 || k == interior + 1) {
                    continue;  // OCCT's very end may lie off the walls
                }
                throw Refusal {"a ball position did not converge"};
            }
            sections.push_back(station);
            previous = station;
        }
    }
    const size_t count = sections.size();
    if (count < 8) {
        throw Refusal {"too few ball positions on a blend face"};
    }
    const size_t middle = count / 2;
    double spacing = 0.0;
    for (size_t k = 1; k < count; ++k) {
        spacing += sections[k - 1].centre.Distance(sections[k].centre);
    }
    spacing /= static_cast<double>(count - 1);
    // OCCT's sections are not evenly spread and can stall or step back where its surface's parameter
    // does: from the middle outwards, only those that advance along the centre curve are kept
    gp_Vec forwardMiddle = tangentAt(sections[middle]);
    if (forwardMiddle.Dot(gp_Vec(sections[count / 4].centre, sections[(3 * count) / 4].centre)) < 0.0) {
        forwardMiddle.Reverse();
    }
    auto walk = [&](bool forwards, gp_Vec& direction) {
        std::vector<Station> kept;
        const Station* last = &sections[middle];
        direction = forwards ? forwardMiddle : forwardMiddle.Reversed();
        for (size_t step = 1; forwards ? middle + step < count : step <= middle; ++step) {
            const Station& candidate = sections[forwards ? middle + step : middle - step];
            if (gp_Vec(last->centre, candidate.centre).Dot(direction) > 0.05 * spacing) {
                kept.push_back(candidate);
                last = &candidate;
                const gp_Vec tangent = tangentAt(candidate);
                direction = tangent.Dot(direction) < 0.0 ? tangent.Reversed() : tangent;
            }
        }
        return kept;
    };
    std::array<gp_Vec, 2> outward;  // the curve's direction out of the face at its start and at its end
    const std::vector<Station> backwards = walk(false, outward[0]);
    const std::vector<Station> forwards = walk(true, outward[1]);
    std::vector<Station> path(backwards.rbegin(), backwards.rend());
    path.push_back(sections[middle]);
    path.insert(path.end(), forwards.begin(), forwards.end());

    for (int end = 0; end < 2; ++end) {
        auto outermost = [&]() -> Station& {
            return end == 0 ? path.front() : path.back();
        };
        auto add = [&](const Station& station) {
            if (end == 0) {
                path.insert(path.begin(), station);
            }
            else {
                path.push_back(station);
            }
        };
        if (!blend.ends[end].present) {
            // A seam: its split station is the end. Sections past it, or too near it, go
            const Seam& seam = context.seams[blend.seams[end]];
            Station anchor;
            anchor.centre = seam.centre;
            for (int side = 0; side < 2; ++side) {
                anchor.feet[side] = foot(walls[side], seam.centre, blend.seed(side, seam.centre));
                if (!anchor.feet[side].ok || std::fabs(anchor.feet[side].distance - radius) > 1e-9) {
                    throw Refusal {"a seam's ball does not touch a wall"};
                }
            }
            anchor.ok = true;
            gp_Vec out = tangentAt(anchor);
            if (out.Dot(outward[end]) < 0.0) {
                out.Reverse();
            }
            while (path.size() > 2 && gp_Vec(outermost().centre, anchor.centre).Dot(out) < 0.3 * spacing) {
                if (end == 0) {
                    path.erase(path.begin());
                }
                else {
                    path.pop_back();
                }
            }
            add(anchor);
            continue;
        }
        // An end on a face of the base: on along the centre curve until the whole arc is clear of that face
        FaceEnd& faceEnd = blend.ends[end];
        Foot hint;
        faceEnd.sign = 1.0;
        if (endDistance(faceEnd, arcPoint(sections[middle], 0.5), hint) > 0.0) {
            faceEnd.sign = -1.0;
        }
        auto clearance = [&](const Station& station) {
            double least = Precision::Infinite();
            for (const double fraction : {0.0, 0.25, 0.5, 0.75, 1.0}) {
                least = std::min(least, endDistance(faceEnd, arcPoint(station, fraction), hint));
            }
            return least;
        };
        // ... and on by twice the radius where the walls reach that far: a later round that runs past
        // this end is cut by this surface (FilletFallback's blendBeyond uses a blend's surface as far
        // as it is still the ball's), and ends in this one face instead of a continuation face
        gp_Vec out = outward[end];
        const double runOn = std::max(2.0 * spacing, 2.0 * radius);
        int beyond = 0;
        for (int steps = 0;; ++steps) {
            const double clear = clearance(outermost());
            if (clear > 2.0 * spacing) {
                ++beyond;
            }
            if (beyond >= 2 && clear > runOn) {
                break;
            }
            if (steps > 4000) {
                throw NotRecognised {"walls that stop at the blend's end"};
            }
            const Station from = outermost();
            const Station next = solveStation(from.centre.Translated(out * spacing), walls, radius, &from);
            if (!next.ok || !onWall(walls[0], next.feet[0]) || !onWall(walls[1], next.feet[1])) {
                if (beyond >= 2) {
                    break;  // the walls end before the run-on does: as far as they reach
                }
                throw NotRecognised {"walls that stop at the blend's end"};
            }
            const gp_Vec tangent = tangentAt(next);
            out = tangent.Dot(out) < 0.0 ? tangent.Reversed() : tangent;
            add(next);
        }
    }

    // The stations, spread evenly along the path: each by Newton from between two of its points
    std::vector<double> along(path.size(), 0.0);
    for (size_t k = 1; k < path.size(); ++k) {
        along[k] = along[k - 1] + path[k - 1].centre.Distance(path[k].centre);
    }
    std::vector<Station> stations;
    stations.push_back(path.front());
    size_t segment = 0;
    for (int k = 1; k <= interior; ++k) {
        const double target = along.back() * k / (interior + 1);
        while (segment + 2 < path.size() && along[segment + 1] < target) {
            ++segment;
        }
        const double span = along[segment + 1] - along[segment];
        const double fraction = span > 0.0 ? (target - along[segment]) / span : 0.0;
        const gp_Pnt start(path[segment].centre.XYZ() * (1.0 - fraction) + path[segment + 1].centre.XYZ() * fraction);
        const Station station = solveStation(start, walls, radius, &path[fraction < 0.5 ? segment : segment + 1]);
        if (!station.ok) {
            throw Refusal {"a ball position did not converge"};
        }
        stations.push_back(station);
    }
    stations.push_back(path.back());
    // In order along the centre curve: a step back would fold the surface
    for (size_t k = 1; k + 1 < stations.size(); ++k) {
        const gp_Vec before(stations[k - 1].centre, stations[k].centre);
        const gp_Vec after(stations[k].centre, stations[k + 1].centre);
        if (before.Dot(after) <= 0.0) {
            throw Refusal {"ball positions out of order along a blend face"};
        }
    }
    // One branch of a periodic wall's parameters along the face
    for (int side = 0; side < 2; ++side) {
        const Handle(Geom_Surface)& wall = walls[side];
        for (size_t k = 1; k < stations.size(); ++k) {
            Foot& f = stations[k].feet[side];
            const Foot& previous = stations[k - 1].feet[side];
            if (wall->IsUPeriodic()) {
                f.u += wall->UPeriod() * std::round((previous.u - f.u) / wall->UPeriod());
            }
            if (wall->IsVPeriodic()) {
                f.v += wall->VPeriod() * std::round((previous.v - f.v) / wall->VPeriod());
            }
        }
    }
    stations[0].t = 0.0;
    for (size_t k = 1; k < stations.size(); ++k) {
        stations[k].t = stations[k - 1].t + stations[k - 1].centre.Distance(stations[k].centre);
    }
    blend.length = stations.back().t;
    blend.stations = std::move(stations);
}

// The end edge on a face of the base: where the new surface is cut by that face, per arc fraction
void solveEnd(Blend& blend, int which)
{
    FaceEnd& end = blend.ends[which];
    const int count = 32;
    end.across.clear();
    end.along.clear();
    end.points.clear();
    end.onFace.clear();
    // The stations' parameters from the outer end inwards
    std::vector<double> parameters;
    for (const Station& station : blend.stations) {
        parameters.push_back(station.t);
    }
    if (which == 1) {
        std::reverse(parameters.begin(), parameters.end());
    }
    Foot hint;
    for (int j = 0; j <= count; ++j) {
        const double u = static_cast<double>(j) / count;
        auto distance = [&](double t) {
            return endDistance(end, blend.surface->Value(u, t), hint);
        };
        double outer = parameters.front();
        if (distance(outer) <= 0.0) {
            throw Refusal {"the blend surface does not reach past its end"};
        }
        double inner = outer;
        bool found = false;
        for (size_t k = 1; k < parameters.size() && !found; ++k) {
            inner = parameters[k];
            if (distance(inner) <= 0.0) {
                found = true;
            }
            else {
                outer = inner;
            }
        }
        if (!found) {
            throw Refusal {"the blend's end face does not cut the blend"};
        }
        for (int iteration = 0; iteration < 100 && std::fabs(outer - inner) > 1e-13; ++iteration) {
            const double t = 0.5 * (outer + inner);
            (distance(t) > 0.0 ? outer : inner) = t;
        }
        const double t = 0.5 * (outer + inner);
        const gp_Pnt point = blend.surface->Value(u, t);
        hint = foot(end.surface, point, &hint);
        if (!hint.ok) {
            throw Refusal {"an end face has no foot"};
        }
        gp_Pnt2d onFace(hint.u, hint.v);
        if (!end.onFace.empty()) {
            if (end.surface->IsUPeriodic()) {
                onFace.SetX(onFace.X() + end.surface->UPeriod() * std::round((end.onFace.back().X() - onFace.X()) / end.surface->UPeriod()));
            }
            if (end.surface->IsVPeriodic()) {
                onFace.SetY(onFace.Y() + end.surface->VPeriod() * std::round((end.onFace.back().Y() - onFace.Y()) / end.surface->VPeriod()));
            }
        }
        end.across.push_back(u);
        end.along.push_back(t);
        end.points.push_back(point);
        end.onFace.push_back(onFace);
    }
}

// A curve through points at given parameters: fitted to 1e-8 with few spans, or the cubic through every point
Handle(Geom_BSplineCurve) fitted(
    const Handle(TColgp_HArray1OfPnt)& points,
    const Handle(TColStd_HArray1OfReal)& parameters,
    bool compact
)
{
    if (compact) try {
        GeomAPI_PointsToBSpline fit(points->Array1(), parameters->Array1(), fitDegree, fitDegree, GeomAbs_C2, 1e-8);
        if (fit.IsDone() && !fit.Curve().IsNull()
            && std::fabs(fit.Curve()->FirstParameter() - parameters->First()) < 1e-12
            && std::fabs(fit.Curve()->LastParameter() - parameters->Last()) < 1e-12) {
            return fit.Curve();
        }
    }
    catch (const Standard_Failure&) {
        // the cubic below
    }
    GeomAPI_Interpolate interpolate(points, parameters, Standard_False, 1e-12);
    interpolate.Perform();
    if (!interpolate.IsDone()) {
        throw Refusal {"the blend surface could not be interpolated"};
    }
    return interpolate.Curve();
}

// The surface: across, the ball's arc as a rational quadratic; lengthwise, a cubic through the stations in homogeneous coordinates
void buildSurface(Blend& blend, double radius, bool compact = true)
{
    const int count = static_cast<int>(blend.stations.size());
    Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, count);
    std::array<Handle(TColgp_HArray1OfPnt), 4> rows;
    for (auto& row : rows) {
        row = new TColgp_HArray1OfPnt(1, count);
    }
    for (int k = 0; k < count; ++k) {
        const Station& station = blend.stations[k];
        parameters->SetValue(k + 1, station.t);
        const gp_Vec e0(station.centre, station.feet[0].point);
        const gp_Vec e1(station.centre, station.feet[1].point);
        const double half = 0.5 * e0.Angle(e1);
        if (half < 1e-6 || half > 0.5 * std::numbers::pi - 1e-3) {
            throw Refusal {"a ball's arc of no span or of half a turn"};
        }
        const double weight = std::cos(half);
        const gp_Pnt pole = station.centre.Translated((e0 + e1).Normalized() * (radius / weight));
        rows[0]->SetValue(k + 1, station.feet[0].point);
        rows[1]->SetValue(k + 1, gp_Pnt(pole.XYZ() * weight));
        rows[2]->SetValue(k + 1, station.feet[1].point);
        // (the parameter rides along: equal weights would be coincident points to the interpolation)
        rows[3]->SetValue(k + 1, gp_Pnt(weight, station.t, 0.0));
    }
    // Each row as a compact curve over the stations' parameters (a few spans of high degree, as OCCT's own blend
    // is: a Boolean's edge/face step costs by the knot, and a cubic through every station made Case Base #103
    // six times slower), then all four on one knot vector, which changes no curve
    std::array<Handle(Geom_BSplineCurve), 4> curves;
    int degree = 0;
    for (int i = 0; i < 4; ++i) {
        curves[i] = fitted(rows[i], parameters, compact);
        degree = std::max(degree, curves[i]->Degree());
    }
    // A row the compact fit could not take (a contact curve on a wall of many spans: Nest Insert #163's elliptic
    // wall) is the cubic through every station. Raised to the others' degree it would carry each of its knots at
    // that degree (771 poles for 67), so then every row is the cubic
    if (std::any_of(curves.begin(), curves.end(), [&](const Handle(Geom_BSplineCurve)& curve) {
            return curve->Degree() != degree;
        })) {
        degree = 0;
        for (int i = 0; i < 4; ++i) {
            curves[i] = fitted(rows[i], parameters, false);
            degree = std::max(degree, curves[i]->Degree());
        }
    }
    for (int i = 0; i < 4; ++i) {
        curves[i]->IncreaseDegree(degree);
    }
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) {
            if (i == j) {
                continue;
            }
            TColStd_Array1OfReal knots(1, curves[j]->NbKnots());
            TColStd_Array1OfInteger multiplicities(1, curves[j]->NbKnots());
            curves[j]->Knots(knots);
            curves[j]->Multiplicities(multiplicities);
            curves[i]->InsertKnots(knots, multiplicities, 1e-10, Standard_False);
        }
    }
    for (int i = 1; i < 4; ++i) {
        if (curves[i]->NbPoles() != curves[0]->NbPoles() || curves[i]->NbKnots() != curves[0]->NbKnots()) {
            throw Refusal {"the blend surface's rows could not be brought onto one knot vector"};
        }
    }
    const int poleCount = curves[0]->NbPoles();
    TColgp_Array2OfPnt poles(1, 3, 1, poleCount);
    TColStd_Array2OfReal weights(1, 3, 1, poleCount);
    for (int j = 1; j <= poleCount; ++j) {
        const double weight = curves[3]->Pole(j).X();
        if (weight < 1e-6) {
            throw Refusal {"the blend surface has a weight that is not positive"};
        }
        poles(1, j) = curves[0]->Pole(j);
        poles(2, j) = gp_Pnt(curves[1]->Pole(j).XYZ() / weight);
        poles(3, j) = curves[2]->Pole(j);
        weights(1, j) = 1.0;
        weights(2, j) = weight;
        weights(3, j) = 1.0;
    }
    TColStd_Array1OfReal acrossKnots(1, 2);
    acrossKnots(1) = 0.0;
    acrossKnots(2) = 1.0;
    TColStd_Array1OfInteger acrossMultiplicities(1, 2);
    acrossMultiplicities(1) = 3;
    acrossMultiplicities(2) = 3;
    TColStd_Array1OfReal knots(1, curves[0]->NbKnots());
    TColStd_Array1OfInteger multiplicities(1, curves[0]->NbKnots());
    curves[0]->Knots(knots);
    curves[0]->Multiplicities(multiplicities);
    blend.surface
        = new Geom_BSplineSurface(poles, weights, acrossKnots, knots, acrossMultiplicities, multiplicities, 2, curves[0]->Degree());
}

// The new surface between its stations, against the walls
double residualBetweenStations(const Blend& blend, double radius)
{
    const auto walls = blend.walls();
    double worst = 0.0;
    for (size_t k = 0; k + 1 < blend.stations.size(); ++k) {
        const double t = 0.5 * (blend.stations[k].t + blend.stations[k + 1].t);
        for (const double u : {0.1, 0.5, 0.9}) {
            const gp_Pnt point = blend.surface->Value(u, t);
            const gp_Vec normal = surfaceNormal(blend.surface, u, t);
            // The centre is on the side of the stations' centres
            const double sign = gp_Vec(point, blend.stations[k].centre).Dot(normal) > 0.0 ? 1.0 : -1.0;
            const gp_Pnt centre = point.Translated(normal * (sign * radius));
            const Foot f0 = foot(walls[0], centre, &blend.stations[k].feet[0]);
            const Foot f1 = foot(walls[1], centre, &blend.stations[k].feet[1]);
            if (!f0.ok || !f1.ok) {
                return Precision::Infinite();
            }
            worst = std::max({worst, std::fabs(f0.distance - radius), std::fabs(f1.distance - radius)});
        }
    }
    return worst;
}

// An edge's new curve and pcurves. parameter gives each of the edge's two vertices its place on the curve
void addEdge(
    Modification& modification,
    const TopoDS_Edge& edge,
    Handle(Geom_Curve) curve,
    const std::vector<std::pair<TopoDS_Face, Handle(Geom2d_Curve)>>& pcurves,
    const std::function<double(const TopoDS_Vertex&)>& parameter
)
{
    const double first = curve->FirstParameter();
    const double last = curve->LastParameter();
    TopoDS_Vertex forward, reversed;
    TopExp::Vertices(TopoDS::Edge(edge.Oriented(TopAbs_FORWARD)), forward, reversed);
    if (forward.IsSame(reversed)) {
        throw Refusal {"a closed edge on a blend face"};
    }
    double atForward = parameter(forward);
    double atReversed = parameter(reversed);
    // The modifier keeps the vertices' orientation in the edge: the new curve must run the way the old one does
    const bool flip = atForward > atReversed;
    if (flip) {
        curve = curve->Reversed();
        atForward = first + last - atForward;
        atReversed = first + last - atReversed;
    }
    if (atReversed - atForward < 1e-9) {
        throw Refusal {"an edge of a blend face would have no length"};
    }
    EdgeNew entry;
    entry.curve = curve;
    entry.forward = forward;
    entry.first = atForward;
    entry.last = atReversed;
    modification.curves[edge.TShape().get()] = entry;
    for (const auto& pcurve : pcurves) {
        modification.pcurves[{edge.TShape().get(), pcurve.first.TShape().get()}]
            = flip ? pcurve.second->Reversed() : pcurve.second;
    }
}

// A contact edge's pcurve on its wall: through the stations' feet, on the old pcurve's branch of a periodic wall
Handle(Geom2d_Curve) wallPcurve(const Blend& blend, int side)
{
    const Side& s = blend.sides[side];
    const int count = static_cast<int>(blend.stations.size());
    double first {}, last {};
    const Handle(Geom2d_Curve) old = BRep_Tool::CurveOnSurface(s.contacts.front(), s.wall, first, last);
    if (old.IsNull()) {
        throw Refusal {"a contact edge without a pcurve on its wall"};
    }
    const gp_Pnt2d oldMiddle = old->Value(0.5 * (first + last));
    const Foot& middle = blend.stations[count / 2].feet[side];
    double shiftU = 0.0;
    double shiftV = 0.0;
    if (s.surface->IsUPeriodic()) {
        shiftU = s.surface->UPeriod() * std::round((oldMiddle.X() - middle.u) / s.surface->UPeriod());
    }
    if (s.surface->IsVPeriodic()) {
        shiftV = s.surface->VPeriod() * std::round((oldMiddle.Y() - middle.v) / s.surface->VPeriod());
    }
    Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, count);
    Handle(TColgp_HArray1OfPnt2d) points = new TColgp_HArray1OfPnt2d(1, count);
    for (int k = 0; k < count; ++k) {
        const Foot& f = blend.stations[k].feet[side];
        parameters->SetValue(k + 1, blend.stations[k].t);
        points->SetValue(k + 1, gp_Pnt2d(f.u + shiftU, f.v + shiftV));
    }
    try {
        Geom2dAPI_PointsToBSpline fit(points->Array1(), parameters->Array1(), fitDegree, fitDegree, GeomAbs_C2, 1e-10);
        if (fit.IsDone() && !fit.Curve().IsNull()
            && std::fabs(fit.Curve()->FirstParameter() - parameters->First()) < 1e-12
            && std::fabs(fit.Curve()->LastParameter() - parameters->Last()) < 1e-12) {
            return fit.Curve();
        }
    }
    catch (const Standard_Failure&) {
        // the cubic below
    }
    Geom2dAPI_Interpolate interpolate(points, parameters, Standard_False, 1e-12);
    interpolate.Perform();
    if (!interpolate.IsDone()) {
        throw Refusal {"a contact edge's pcurve could not be interpolated"};
    }
    return interpolate.Curve();
}

struct Tolerances
{
    std::map<const TopoDS_TShape*, double> of;
};

double toleranceOf(const TopoDS_Shape& shape)
{
    switch (shape.ShapeType()) {
        case TopAbs_FACE:
            return BRep_Tool::Tolerance(TopoDS::Face(shape));
        case TopAbs_EDGE:
            return BRep_Tool::Tolerance(TopoDS::Edge(shape));
        case TopAbs_VERTEX:
            return BRep_Tool::Tolerance(TopoDS::Vertex(shape));
        default:
            return 0.0;
    }
}

// A chain's seams, and its ends on faces of the base
void recogniseChain(Context& context, const std::vector<int>& chain, std::vector<int>& chainSeams)
{
    for (const int index : chain) {
        Blend& blend = context.blends[index];
        for (int end = 0; end < 2; ++end) {
            if (blend.ends[end].present) {
                FaceEnd& faceEnd = blend.ends[end];
                TopoDS_Vertex v1, v2;
                TopExp::Vertices(faceEnd.edge, v1, v2);
                for (const TopoDS_Vertex& vertex : {v1, v2}) {
                    const int side = sideAt(blend, vertex);
                    if (side >= 0) {
                        faceEnd.vertices[side] = vertex;
                    }
                }
                if (v1.IsSame(v2) || faceEnd.vertices[0].IsNull() || faceEnd.vertices[1].IsNull()) {
                    throw NotRecognised {"an end edge that does not join the two contact edges"};
                }
                for (int side = 0; side < 2; ++side) {
                    const TopTools_ListOfShape& edges = context.vertexEdges.FindFromKey(faceEnd.vertices[side]);
                    for (TopTools_ListOfShape::Iterator it(edges); it.More(); it.Next()) {
                        const TopTools_ListOfShape& faces = context.edgeFaces.FindFromKey(it.Value());
                        bool wall = false;
                        bool base = false;
                        for (TopTools_ListOfShape::Iterator jt(faces); jt.More(); jt.Next()) {
                            wall = wall || jt.Value().IsSame(blend.sides[side].wall);
                            base = base || jt.Value().IsSame(faceEnd.face);
                        }
                        if (wall && base) {
                            faceEnd.slides[side] = TopoDS::Edge(it.Value());
                        }
                    }
                    if (faceEnd.slides[side].IsNull()) {
                        throw NotRecognised {"an end where a wall and the end face share no edge"};
                    }
                }
                continue;
            }
            int found = -1;
            for (size_t k = 0; k < context.seams.size(); ++k) {
                if (context.seams[k].edge.IsSame(blend.cross[end])) {
                    found = static_cast<int>(k);
                }
            }
            if (found < 0) {
                Seam seam;
                seam.edge = blend.cross[end];
                seam.blends[0] = index;
                context.seams.push_back(seam);
                found = static_cast<int>(context.seams.size()) - 1;
                chainSeams.push_back(found);
            }
            else {
                context.seams[found].blends[1] = index;
            }
            blend.seams[end] = found;
        }
        if (blend.seams[0] >= 0 && blend.seams[0] == blend.seams[1]) {
            throw NotRecognised {"a blend face whose two ends are one seam"};
        }
    }
    for (const int k : chainSeams) {
        Seam& seam = context.seams[k];
        if (seam.blends[1] >= 0) {
            continue;
        }
        // The other face is of exact form: it is classified here, and keeps everything but this seam
        const Blend& first = context.blends[seam.blends[0]];
        int other = -1;
        for (TopTools_ListOfShape::Iterator it(context.edgeFaces.FindFromKey(seam.edge)); it.More(); it.Next()) {
            if (!it.Value().IsSame(first.face)) {
                other = context.blendOf(it.Value());
            }
        }
        if (other < 0 || !context.blends[other].kept) {
            throw NotRecognised {"a seam with one blend face"};
        }
        if (context.blends[other].old.IsNull()) {
            classifyKept(context, context.blends[other]);
        }
        seam.blends[1] = other;
    }
}

}  // namespace

double ballResidual(const TopoDS_Face& blend, const TopoDS_Face& wall1, const TopoDS_Face& wall2, double radius)
{
    double u0 {}, u1 {}, v0 {}, v1 {};
    BRepTools::UVBounds(blend, u0, u1, v0, v1);
    return residualOfSurface(
        BRep_Tool::Surface(blend),
        u0,
        u1,
        v0,
        v1,
        {untrimmed(BRep_Tool::Surface(wall1)), untrimmed(BRep_Tool::Surface(wall2))},
        radius,
        5,
        25
    );
}

namespace
{
Report correctNow(const TopoDS_Shape& shape, const std::vector<TopoDS_Face>& blendFaces, double radius);
}

Report correct(const TopoDS_Shape& shape, const std::vector<TopoDS_Face>& blendFaces, double radius)
{
    // FREECAD_CH_ROLLINGBALL=off leaves every fillet as OCCT built it; =trace reports each call on
    // stderr. For measuring and bisecting only
#ifdef _MSC_VER
    std::string mode;
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, "FREECAD_CH_ROLLINGBALL") == 0 && value) {
        mode = value;
        std::free(value);
    }
#else
    const char* value = std::getenv("FREECAD_CH_ROLLINGBALL");
    const std::string mode = value ? value : "";
#endif
    if (mode == "off") {
        Report report;
        report.reason = "switched off";
        return report;
    }
    if (mode != "trace") {
        return correctNow(shape, blendFaces, radius);
    }
    const auto start = std::chrono::steady_clock::now();
    const Report report = correctNow(shape, blendFaces, radius);
    const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    std::fprintf(
        stderr,
        "ROLLINGBALL %s: %zu faces passed, r %.6g, chains %d, faces %d, stations %d, poles %d, residual %.3g -> %.3g, moved %.3g, %.3f s%s%s\n",
        report.outcome == Outcome::Corrected ? "Corrected" : report.outcome == Outcome::Refused ? "Refused" : "NotMine",
        blendFaces.size(),
        radius,
        report.chains,
        report.faces,
        report.stations,
        report.poles,
        report.residualBefore,
        report.residualAfter,
        report.seamMove,
        seconds,
        report.reason.empty() ? "" : " | ",
        report.reason.c_str()
    );
    return report;
}

namespace
{
Report correctNow(const TopoDS_Shape& shape, const std::vector<TopoDS_Face>& blendFaces, double radius)
{
    Report report;
    if (shape.IsNull() || blendFaces.empty() || radius <= Precision::Confusion()) {
        report.reason = "nothing to look at";
        return report;
    }
    try {
        Context context;
        context.shape = shape;
        context.radius = radius;
        TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, context.edgeFaces);
        TopExp::MapShapesAndAncestors(shape, TopAbs_VERTEX, TopAbs_EDGE, context.vertexEdges);
        TopTools_IndexedMapOfShape allFaces;
        TopExp::MapShapes(shape, TopAbs_FACE, allFaces);
        for (const TopoDS_Face& face : blendFaces) {
            if (face.IsNull() || !allFaces.Contains(face) || context.blendOf(face) >= 0) {
                continue;
            }
            Blend blend;
            blend.face = face;
            context.blends.push_back(blend);
        }
        if (context.blends.empty()) {
            report.reason = "no blend face in the shape";
            return report;
        }

        // The chains: blend faces connected through common edges
        std::vector<std::vector<int>> chains;
        for (size_t i = 0; i < context.blends.size(); ++i) {
            if (context.blends[i].chain >= 0) {
                continue;
            }
            std::vector<int> chain {static_cast<int>(i)};
            context.blends[i].chain = static_cast<int>(chains.size());
            for (size_t next = 0; next < chain.size(); ++next) {
                for (TopExp_Explorer it(context.blends[chain[next]].face, TopAbs_EDGE); it.More(); it.Next()) {
                    const TopTools_ListOfShape& faces = context.edgeFaces.FindFromKey(it.Current());
                    for (TopTools_ListOfShape::Iterator jt(faces); jt.More(); jt.Next()) {
                        const int other = context.blendOf(jt.Value());
                        if (other >= 0 && context.blends[other].chain < 0) {
                            context.blends[other].chain = context.blends[chain[next]].chain;
                            chain.push_back(other);
                        }
                    }
                }
            }
            chains.push_back(chain);
        }

        Handle(Modification) modification = new Modification;
        std::vector<int> corrected;  // blend indices
        std::vector<int> correctedSeams;
        for (const auto& chain : chains) {
            std::vector<int> chainSeams;
            std::vector<int> ball;  // the chain's faces that take new geometry
            try {
                // A chain of exact forms (cylinders between planes, tori) is a rolling ball by form. Among
                // spline faces such faces stay as they are (Nest Insert #163: a slot's round is cylinders and
                // tori, and two spline faces where it passes under an oblique elliptic wall); only the spline
                // faces, and their seams, take the ball's geometry
                for (const int index : chain) {
                    const Handle(Geom_Surface) surface = untrimmed(BRep_Tool::Surface(context.blends[index].face));
                    if (surface->IsKind(STANDARD_TYPE(Geom_BSplineSurface))
                        || surface->IsKind(STANDARD_TYPE(Geom_BezierSurface))) {
                        ball.push_back(index);
                    }
                    else {
                        context.blends[index].kept = true;
                    }
                }
                if (ball.empty()) {
                    throw NotRecognised {"a rolling ball already"};
                }
                for (const int index : ball) {
                    classify(context, context.blends[index]);
                }
                double before = 0.0;
                int exact = 0;
                for (const int index : ball) {
                    const Blend& blend = context.blends[index];
                    double u0 {}, u1 {}, v0 {}, v1 {};
                    BRepTools::UVBounds(blend.face, u0, u1, v0, v1);
                    const double r = residualOfSurface(blend.old, u0, u1, v0, v1, blend.walls(), radius, 5, 25, &blend);
                    before = std::max(before, r);
                    exact += r < alreadyBall ? 1 : 0;
                }
                if (before < alreadyBall) {
                    throw NotRecognised {"a rolling ball already"};
                }
                if (exact > 0) {
                    throw NotRecognised {"a chain with faces that are a rolling ball already and faces that are not"};
                }
                recogniseChain(context, ball, chainSeams);
                for (const int k : chainSeams) {
                    solveSeam(context, context.seams[k]);
                }
                report.residualBefore = std::max(report.residualBefore, before);
            }
            catch (const NotRecognised& e) {
                if (!report.reason.empty()) {
                    report.reason += "; ";
                }
                report.reason += e.why;
                continue;
            }
            catch (const Standard_Failure& e) {
                // The kernel failed while looking: nothing was changed, the chain stays OCCT's
                if (!report.reason.empty()) {
                    report.reason += "; ";
                }
                report.reason += std::string("not recognised, the kernel failed: ") + e.what();
                continue;
            }
            // Recognised: from here on a failure refuses
            int interior = firstStations;
            for (int pass = 0;; ++pass) {
                double worst = 0.0;
                for (const int index : ball) {
                    Blend& blend = context.blends[index];
                    solveStations(context, blend, interior);
                    buildSurface(blend, radius);
                    double between = residualBetweenStations(blend, radius);
                    if (between > surfaceBound) {
                        // The compact fit did not get there: the cubic through every station
                        buildSurface(blend, radius, false);
                        between = residualBetweenStations(blend, radius);
                    }
                    worst = std::max(worst, between);
                }
                if (worst <= surfaceBound) {
                    break;
                }
                if (pass == maxDoublings) {
                    throw Refusal {"the blend surface does not reach its bound"};
                }
                interior = 2 * interior + 1;
            }
            for (const int index : ball) {
                report.stations = std::max(report.stations, static_cast<int>(context.blends[index].stations.size()));
                report.poles = std::max(report.poles, context.blends[index].surface->NbVPoles());
                for (int end = 0; end < 2; ++end) {
                    if (context.blends[index].ends[end].present) {
                        solveEnd(context.blends[index], end);
                    }
                }
            }
            corrected.insert(corrected.end(), ball.begin(), ball.end());
            correctedSeams.insert(correctedSeams.end(), chainSeams.begin(), chainSeams.end());
            ++report.chains;
        }
        if (corrected.empty()) {
            return report;
        }

        // The modification
        Tolerances before;
        auto movePoint = [&](const TopoDS_Vertex& vertex, const gp_Pnt& point, double tolerance) {
            modification->points[vertex.TShape().get()] = point;
            if (tolerance > newTolerance) {
                modification->pointTolerances[vertex.TShape().get()] = tolerance;
            }
            before.of[vertex.TShape().get()] = toleranceOf(vertex);
            report.seamMove = std::max(report.seamMove, BRep_Tool::Pnt(vertex).Distance(point));
        };
        // An untouched edge of the base keeps its curve; one of its vertices slides along it
        auto slideAlong = [&](const TopoDS_Edge& edge, const TopoDS_Vertex& vertex, double parameter) {
            const TopoDS_TShape* key = edge.TShape().get();
            auto slide = modification->slides.find(key);
            if (slide == modification->slides.end()) {
                EdgeNew entry;
                double first {}, last {};
                entry.curve = BRep_Tool::Curve(edge, first, last);
                TopoDS_Vertex forward, reversed;
                TopExp::Vertices(TopoDS::Edge(edge.Oriented(TopAbs_FORWARD)), forward, reversed);
                entry.forward = forward;
                entry.first = first;
                entry.last = last;
                slide = modification->slides.emplace(key, entry).first;
            }
            (vertex.IsSame(slide->second.forward) ? slide->second.first : slide->second.last) = parameter;
            if (slide->second.last - slide->second.first < Precision::Confusion()) {
                throw Refusal {"a seam or an end crosses a vertex of the wall"};
            }
        };
        for (const int index : corrected) {
            const Blend& blend = context.blends[index];
            modification->surfaces[blend.face.TShape().get()] = blend.surface;
            before.of[blend.face.TShape().get()] = toleranceOf(blend.face);
            for (int side = 0; side < 2; ++side) {
                const Side& s = blend.sides[side];
                const double across = side == 0 ? 0.0 : 1.0;
                const Handle(Geom_Curve) curve = blend.surface->UIso(across);
                const Handle(Geom2d_Curve) onBlend
                    = segment2d(gp_Pnt2d(across, 0.0), gp_Pnt2d(across, blend.length), 0.0, blend.length);
                const Handle(Geom2d_Curve) onWall = wallPcurve(blend, side);
                // Where each vertex of the side lies on the contact curve
                auto parameter = [&](const TopoDS_Vertex& vertex) {
                    for (int end = 0; end < 2; ++end) {
                        if (blend.ends[end].present) {
                            if (blend.ends[end].vertices[side].IsSame(vertex)) {
                                return side == 0 ? blend.ends[end].along.front() : blend.ends[end].along.back();
                            }
                        }
                        else {
                            const Seam& seam = context.seams[blend.seams[end]];
                            if (seam.vertices[0].IsSame(vertex) || seam.vertices[1].IsSame(vertex)) {
                                return end == 0 ? 0.0 : blend.length;
                            }
                        }
                    }
                    // A vertex between two edges of the side: it slides to the new curve
                    GeomAPI_ProjectPointOnCurve projection(BRep_Tool::Pnt(vertex), curve);
                    if (projection.NbPoints() < 1) {
                        throw Refusal {"a vertex of a contact edge has no place on the new one"};
                    }
                    const double at = projection.LowerDistanceParameter();
                    movePoint(vertex, curve->Value(at), newTolerance);
                    return at;
                };
                for (const TopoDS_Edge& edge : s.contacts) {
                    before.of[edge.TShape().get()] = toleranceOf(edge);
                    addEdge(*modification, edge, curve, {{blend.face, onBlend}, {s.wall, onWall}}, parameter);
                }
            }
            for (int which = 0; which < 2; ++which) {
                if (!blend.ends[which].present) {
                    continue;
                }
                // The end edge: the new surface cut by the end face, through its points per arc fraction
                const FaceEnd& end = blend.ends[which];
                const int count = static_cast<int>(end.across.size());
                Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, count);
                Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, count);
                Handle(TColgp_HArray1OfPnt2d) onBlend = new TColgp_HArray1OfPnt2d(1, count);
                Handle(TColgp_HArray1OfPnt2d) onFace = new TColgp_HArray1OfPnt2d(1, count);
                double first {}, last {};
                const Handle(Geom2d_Curve) old = BRep_Tool::CurveOnSurface(end.edge, end.face, first, last);
                if (old.IsNull()) {
                    throw Refusal {"an end edge without a pcurve on its face"};
                }
                const gp_Pnt2d oldMiddle = old->Value(0.5 * (first + last));
                const gp_Pnt2d& middle = end.onFace[count / 2];
                const double shiftU = end.surface->IsUPeriodic()
                    ? end.surface->UPeriod() * std::round((oldMiddle.X() - middle.X()) / end.surface->UPeriod())
                    : 0.0;
                const double shiftV = end.surface->IsVPeriodic()
                    ? end.surface->VPeriod() * std::round((oldMiddle.Y() - middle.Y()) / end.surface->VPeriod())
                    : 0.0;
                for (int j = 0; j < count; ++j) {
                    parameters->SetValue(j + 1, end.across[j]);
                    points->SetValue(j + 1, end.points[j]);
                    onBlend->SetValue(j + 1, gp_Pnt2d(end.across[j], end.along[j]));
                    onFace->SetValue(j + 1, gp_Pnt2d(end.onFace[j].X() + shiftU, end.onFace[j].Y() + shiftV));
                }
                GeomAPI_Interpolate curve(points, parameters, Standard_False, 1e-12);
                Geom2dAPI_Interpolate pcurveBlend(onBlend, parameters, Standard_False, 1e-12);
                Geom2dAPI_Interpolate pcurveFace(onFace, parameters, Standard_False, 1e-12);
                curve.Perform();
                pcurveBlend.Perform();
                pcurveFace.Perform();
                if (!curve.IsDone() || !pcurveBlend.IsDone() || !pcurveFace.IsDone()) {
                    throw Refusal {"an end edge could not be interpolated"};
                }
                before.of[end.edge.TShape().get()] = toleranceOf(end.edge);
                addEdge(
                    *modification,
                    end.edge,
                    curve.Curve(),
                    {{blend.face, pcurveBlend.Curve()}, {end.face, pcurveFace.Curve()}},
                    [&](const TopoDS_Vertex& vertex) {
                        return vertex.IsSame(end.vertices[0]) ? 0.0 : 1.0;
                    }
                );
                // Its two vertices slide along the base's edges between each wall and the end face
                for (int side = 0; side < 2; ++side) {
                    const gp_Pnt point = side == 0 ? end.points.front() : end.points.back();
                    double edgeFirst {}, edgeLast {};
                    const Handle(Geom_Curve) along = BRep_Tool::Curve(end.slides[side], edgeFirst, edgeLast);
                    if (along.IsNull()) {
                        throw Refusal {"an edge of the base without a curve"};
                    }
                    GeomAPI_ProjectPointOnCurve projection(point, along);
                    if (projection.NbPoints() < 1) {
                        throw Refusal {"an end vertex has no place on the base's edge"};
                    }
                    double at = projection.LowerDistanceParameter();
                    if (along->IsPeriodic()) {
                        const double was = BRep_Tool::Parameter(end.vertices[side], end.slides[side]);
                        at += along->Period() * std::round((was - at) / along->Period());
                    }
                    movePoint(end.vertices[side], point, std::max(newTolerance, 1.5 * projection.LowerDistance()));
                    slideAlong(end.slides[side], end.vertices[side], at);
                }
            }
        }
        for (const int k : correctedSeams) {
            const Seam& seam = context.seams[k];
            before.of[seam.edge.TShape().get()] = toleranceOf(seam.edge);
            // The seam is the ball's arc at the split station: the end iso line of both faces. It runs
            // from the first face's side 0 to its side 1; on the second face the same points
            const Blend& firstBlend = context.blends[seam.blends[0]];
            const double vFirst = firstBlend.seams[0] == k ? 0.0 : firstBlend.length;
            const Handle(Geom_Curve) curve = firstBlend.surface->VIso(vFirst);
            std::vector<std::pair<TopoDS_Face, Handle(Geom2d_Curve)>> pcurves;
            pcurves.emplace_back(firstBlend.face, segment2d(gp_Pnt2d(0.0, vFirst), gp_Pnt2d(1.0, vFirst), 0.0, 1.0));
            const Blend& secondBlend = context.blends[seam.blends[1]];
            if (secondBlend.kept) {
                // On the face of exact form: the arc's points in its parameters, on the old pcurve's branch
                double first {}, last {};
                const Handle(Geom2d_Curve) old = BRep_Tool::CurveOnSurface(seam.edge, secondBlend.face, first, last);
                if (old.IsNull()) {
                    throw Refusal {"a seam without a pcurve on the exact face beside it"};
                }
                const gp_Pnt start = curve->Value(0.0);
                const gp_Pnt2d hint = secondBlend.old->Value(old->Value(first).X(), old->Value(first).Y()).Distance(start)
                        < secondBlend.old->Value(old->Value(last).X(), old->Value(last).Y()).Distance(start)
                    ? old->Value(first)
                    : old->Value(last);
                double u = hint.X();
                double v = hint.Y();
                const int count = 33;
                Handle(TColStd_HArray1OfReal) parameters = new TColStd_HArray1OfReal(1, count);
                Handle(TColgp_HArray1OfPnt2d) points = new TColgp_HArray1OfPnt2d(1, count);
                for (int j = 0; j < count; ++j) {
                    const double t = static_cast<double>(j) / (count - 1);
                    if (!parametersOf(secondBlend.old, curve->Value(t), u, v, true)) {
                        throw Refusal {"a seam's arc does not lie on the exact face beside it"};
                    }
                    parameters->SetValue(j + 1, t);
                    points->SetValue(j + 1, gp_Pnt2d(u, v));
                }
                Geom2dAPI_Interpolate onKept(points, parameters, Standard_False, 1e-12);
                onKept.Perform();
                if (!onKept.IsDone()) {
                    throw Refusal {"a seam's pcurve on the exact face beside it could not be interpolated"};
                }
                pcurves.emplace_back(secondBlend.face, onKept.Curve());
            }
            else {
                const double vSecond = secondBlend.seams[0] == k ? 0.0 : secondBlend.length;
                const bool sameWay = secondBlend.surface->Value(0.0, vSecond).Distance(curve->Value(0.0))
                    < secondBlend.surface->Value(1.0, vSecond).Distance(curve->Value(0.0));
                pcurves.emplace_back(
                    secondBlend.face,
                    segment2d(gp_Pnt2d(sameWay ? 0.0 : 1.0, vSecond), gp_Pnt2d(sameWay ? 1.0 : 0.0, vSecond), 0.0, 1.0)
                );
            }
            addEdge(*modification, seam.edge, curve, pcurves, [&](const TopoDS_Vertex& vertex) {
                return sideAt(firstBlend, vertex) == 0 ? 0.0 : 1.0;
            });
            for (int i = 0; i < 2; ++i) {
                movePoint(seam.vertices[i], seam.points[i], newTolerance);
            }
            slideAlong(seam.tangentEdge, seam.vertices[seam.sliding], seam.parameterOnK);
            for (const Seam::KeptSlide& slide : seam.keptSlides) {
                before.of[slide.edge.TShape().get()] = toleranceOf(slide.edge);
                slideAlong(slide.edge, seam.vertices[slide.vertex], slide.parameter);
            }
        }

        Maker maker(shape, modification);
        if (!maker.IsDone()) {
            throw Refusal {"the new geometry could not be put into the body"};
        }
        TopoDS_Shape result = maker.Shape();
        if (result.IsNull()) {
            throw Refusal {"the new geometry could not be put into the body"};
        }
        // Same parameter on the edges with new geometry only, then their tolerances
        BRep_Builder builder;
        TopTools_IndexedMapOfShape oldEdges;
        TopExp::MapShapes(shape, TopAbs_EDGE, oldEdges);
        for (int i = 1; i <= oldEdges.Extent(); ++i) {
            const TopoDS_TShape* key = oldEdges(i).TShape().get();
            if (!modification->curves.count(key) && !modification->slides.count(key)) {
                continue;
            }
            const TopoDS_Edge edge = TopoDS::Edge(maker.ModifiedShape(oldEdges(i)));
            builder.SameParameter(edge, Standard_False);
            BRepLib::SameParameter(edge, newTolerance);
            TopoDS_Vertex v1, v2;
            TopExp::Vertices(edge, v1, v2);
            builder.UpdateVertex(v1, BRep_Tool::Tolerance(edge));
            builder.UpdateVertex(v2, BRep_Tool::Tolerance(edge));
        }

        // The checks
        if (!BRepCheck_Analyzer(result).IsValid()) {
            throw Refusal {"the corrected body is not valid"};
        }
        for (const TopAbs_ShapeEnum kind : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
            TopTools_IndexedMapOfShape was;
            TopTools_IndexedMapOfShape is;
            TopExp::MapShapes(shape, kind, was);
            TopExp::MapShapes(result, kind, is);
            if (was.Extent() != is.Extent()) {
                throw Refusal {"the corrected body has another topology"};
            }
            for (int i = 1; i <= was.Extent(); ++i) {
                const TopoDS_Shape now = maker.ModifiedShape(was(i));
                if (!now.IsSame(is(i))) {
                    throw Refusal {"the corrected body has its topology in another order"};
                }
                const auto old = before.of.find(was(i).TShape().get());
                if (old != before.of.end() && toleranceOf(now) > std::max(resultBound, old->second)) {
                    throw Refusal {"the corrected body has a tolerance above its bound"};
                }
            }
        }
        for (const int index : corrected) {
            const Blend& blend = context.blends[index];
            const double r = residualOfSurface(blend.surface, 0.0, 1.0, 0.0, blend.length, blend.walls(), radius, 7, 61, &blend);
            report.residualAfter = std::max(report.residualAfter, r);
        }
        if (report.residualAfter > resultBound) {
            throw Refusal {"the corrected blend is not a rolling ball"};
        }
        for (const TopoDS_Face& face : blendFaces) {
            report.blendFaces.push_back(
                !face.IsNull() && allFaces.Contains(face) ? TopoDS::Face(maker.ModifiedShape(face)) : face
            );
        }
        report.faces = static_cast<int>(corrected.size());
        report.outcome = Outcome::Corrected;
        report.shape = result;
        return report;
    }
    catch (const Refusal& e) {
        report.outcome = Outcome::Refused;
        report.reason = e.why;
    }
    catch (const NotRecognised& e) {
        report.outcome = Outcome::NotMine;
        report.reason = e.why;
    }
    catch (const Standard_Failure& e) {
        report.outcome = Outcome::Refused;
        report.reason = std::string("the kernel failed: ") + e.what();
    }
    report.shape.Nullify();
    report.blendFaces.clear();
    return report;
}

}  // namespace

}  // namespace Part::RollingBallBlend
