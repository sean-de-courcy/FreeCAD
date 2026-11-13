// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <numbers>
#include <set>
#include <string>
#include <utility>

#include <BRepBuilderAPI_MakeShape.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepCheck_Result.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <BRepTools_Modification.hxx>
#include <BRepTools_Modifier.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <ElCLib.hxx>
#include <ElSLib.hxx>
#include <GProp_GProps.hxx>
#include <Geom2d_Curve.hxx>
#include <GeomConvert_CurveToAnaCurve.hxx>
#include <GeomConvert_SurfToAnaSurf.hxx>
#include <GeomProjLib.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_Circle.hxx>
#include <Geom_ConicalSurface.hxx>
#include <Geom_Curve.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_ElementarySurface.hxx>
#include <Geom_Ellipse.hxx>
#include <Geom_Line.hxx>
#include <Geom_Plane.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom_SphericalSurface.hxx>
#include <Geom_Surface.hxx>
#include <Geom_ToroidalSurface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <NCollection_DataMap.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopTools_MapOfShape.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Circ.hxx>
#include <gp_Dir.hxx>
#include <gp_Elips.hxx>
#include <gp_Lin.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Vec.hxx>
#include <gp_Vec2d.hxx>

#include "CanonicalFaces.h"

namespace Part::CanonicalFaces
{

namespace
{

constexpr double twoPi = 2.0 * std::numbers::pi;
/// The grid over a face's UV box and the points along a curve that the checks measure
constexpr int gridSize = 12;
constexpr int edgePoints = 9;
constexpr int curvePoints = 17;
constexpr int pcurvePoints = 65;

Handle(Geom_Surface) basisSurface(Handle(Geom_Surface) surface)
{
    while (auto trimmed = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface)) {
        surface = trimmed->BasisSurface();
    }
    return surface;
}

Handle(Geom_Curve) basisCurve(Handle(Geom_Curve) curve)
{
    while (auto trimmed = Handle(Geom_TrimmedCurve)::DownCast(curve)) {
        curve = trimmed->BasisCurve();
    }
    return curve;
}

bool isSpline(const Handle(Geom_Surface)& surface)
{
    return !Handle(Geom_BSplineSurface)::DownCast(surface).IsNull()
        || !Handle(Geom_BezierSurface)::DownCast(surface).IsNull();
}

bool isSpline(const Handle(Geom_Curve)& curve)
{
    return !Handle(Geom_BSplineCurve)::DownCast(curve).IsNull()
        || !Handle(Geom_BezierCurve)::DownCast(curve).IsNull();
}

/// The parameters of the surface's point nearest to p, in closed form: false for an unknown kind
bool parameters(const Handle(Geom_ElementarySurface)& surface, const gp_Pnt& p, double& u, double& v)
{
    if (auto plane = Handle(Geom_Plane)::DownCast(surface)) {
        ElSLib::Parameters(plane->Pln(), p, u, v);
    }
    else if (auto cylinder = Handle(Geom_CylindricalSurface)::DownCast(surface)) {
        ElSLib::Parameters(cylinder->Cylinder(), p, u, v);
    }
    else if (auto cone = Handle(Geom_ConicalSurface)::DownCast(surface)) {
        ElSLib::Parameters(cone->Cone(), p, u, v);
    }
    else if (auto sphere = Handle(Geom_SphericalSurface)::DownCast(surface)) {
        ElSLib::Parameters(sphere->Sphere(), p, u, v);
    }
    else if (auto torus = Handle(Geom_ToroidalSurface)::DownCast(surface)) {
        ElSLib::Parameters(torus->Torus(), p, u, v);
    }
    else {
        return false;
    }
    return true;
}

double distance(const Handle(Geom_ElementarySurface)& surface, const gp_Pnt& p)
{
    double u = 0.0;
    double v = 0.0;
    if (!parameters(surface, p, u, v)) {
        return std::numeric_limits<double>::infinity();
    }
    return surface->Value(u, v).Distance(p);
}

/// The parameter on a line, circle or ellipse of its point at p's angle or foot
double parameter(const Handle(Geom_Curve)& curve, const gp_Pnt& p)
{
    if (auto line = Handle(Geom_Line)::DownCast(curve)) {
        return ElCLib::Parameter(line->Lin(), p);
    }
    if (auto circle = Handle(Geom_Circle)::DownCast(curve)) {
        return ElCLib::Parameter(circle->Circ(), p);
    }
    return ElCLib::Parameter(Handle(Geom_Ellipse)::DownCast(curve)->Elips(), p);
}

/// An angle in [0, 2 pi), with what is within 1e-9 below a whole turn taken as 0
double turn(double angle)
{
    angle -= twoPi * std::floor(angle / twoPi);
    return angle > twoPi - 1e-9 ? 0.0 : angle;
}

/** The elementary surface again, placed so that the patch about `middle` is away from its seam: a
 * cylinder's, cone's or torus's X axis points away from the patch's middle (u = pi there), and a
 * sphere's as well, with its poles square to the middle (v = 0 there). Null if the middle is on
 * the axis.
 */
Handle(Geom_ElementarySurface) placed(const Handle(Geom_ElementarySurface)& surface, const gp_Pnt& middle)
{
    if (!Handle(Geom_Plane)::DownCast(surface).IsNull()) {
        return surface;
    }
    const gp_Ax3 position = surface->Position();
    gp_Vec out(position.Location(), middle);
    if (auto sphere = Handle(Geom_SphericalSurface)::DownCast(surface)) {
        if (out.Magnitude() < Precision::Confusion()) {
            return {};
        }
        const gp_Dir x = gp_Dir(out).Reversed();
        const gp_Dir z = gp_Ax2(position.Location(), x).XDirection();
        return new Geom_SphericalSurface(gp_Ax3(position.Location(), z, x), sphere->Radius());
    }
    const gp_Dir z = position.Direction();
    out -= gp_Vec(z) * out.Dot(gp_Vec(z));
    if (out.Magnitude() < Precision::Confusion()) {
        return {};
    }
    const gp_Ax3 axes(position.Location(), z, gp_Dir(out).Reversed());
    if (auto cylinder = Handle(Geom_CylindricalSurface)::DownCast(surface)) {
        return new Geom_CylindricalSurface(axes, cylinder->Radius());
    }
    if (auto cone = Handle(Geom_ConicalSurface)::DownCast(surface)) {
        return new Geom_ConicalSurface(axes, cone->SemiAngle(), cone->RefRadius());
    }
    if (auto torus = Handle(Geom_ToroidalSurface)::DownCast(surface)) {
        return new Geom_ToroidalSurface(axes, torus->MajorRadius(), torus->MinorRadius());
    }
    return {};
}

/// OCCT's recognition of a surface over a UV box, placed for the patch: null if none
Handle(Geom_ElementarySurface) recognise(
    const Handle(Geom_Surface)& surface,
    double u1,
    double u2,
    double v1,
    double v2,
    double within
)
{
    try {
        GeomConvert_SurfToAnaSurf converter(surface);
        const Handle(Geom_Surface) found = converter.ConvertToAnalytical(within, u1, u2, v1, v2);
        if (found.IsNull()) {
            return {};
        }
        const auto elementary = Handle(Geom_ElementarySurface)::DownCast(basisSurface(found));
        if (elementary.IsNull() || !elementary->Position().Direct()) {
            return {};
        }
        return placed(elementary, surface->Value((u1 + u2) / 2.0, (v1 + v2) / 2.0));
    }
    catch (const Standard_Failure&) {
        return {};
    }
}

/// The largest distance from a grid over the surface's UV box to the elementary surface
double deviation(
    const Handle(Geom_Surface)& surface,
    double u1,
    double u2,
    double v1,
    double v2,
    const Handle(Geom_ElementarySurface)& elementary
)
{
    double worst = 0.0;
    for (int i = 0; i <= gridSize; ++i) {
        for (int j = 0; j <= gridSize; ++j) {
            const gp_Pnt p
                = surface->Value(u1 + (u2 - u1) * i / gridSize, v1 + (v2 - v1) * j / gridSize);
            worst = std::max(worst, distance(elementary, p));
        }
    }
    return worst;
}

struct FacePlan
{
    Handle(Geom_ElementarySurface) surface;
    /// The new surface's normal is opposite to the old one's
    bool reversed {false};
    double tol {0.0};
    /// The new surface's parameters at the patch's middle: the period window of its pcurves
    double u0 {0.0};
    double v0 {0.0};
    double gap {0.0};
};

struct EdgePlan
{
    /// The edge's curve from now on: a line, circle or ellipse where `renewed`, else the curve it has
    Handle(Geom_Curve) curve;
    bool renewed {false};
    double first {0.0};
    double last {0.0};
    double tol {0.0};
    double gap {0.0};
};

struct Pcurve
{
    Handle(Geom2d_Curve) curve;
    double tol {0.0};
};

using FacePlans = NCollection_DataMap<TopoDS_Shape, FacePlan, TopTools_ShapeMapHasher>;
using EdgePlans = NCollection_DataMap<TopoDS_Shape, EdgePlan, TopTools_ShapeMapHasher>;
using PcurveKey = std::pair<const TopoDS_TShape*, const TopoDS_TShape*>;

struct Plan
{
    FacePlans faces;
    EdgePlans edges;
    std::map<PcurveKey, Pcurve> pcurves;
};

/// Whether the edge is anything but a curve between two different vertices, one at each end
bool closedEdge(const TopoDS_Edge& edge)
{
    TopoDS_Vertex first;
    TopoDS_Vertex last;
    TopExp::Vertices(edge, first, last);
    int vertices = 0;
    for (TopoDS_Iterator it(edge, false); it.More(); it.Next()) {
        ++vertices;
    }
    return first.IsNull() || last.IsNull() || first.IsSame(last) || vertices != 2;
}

/// Whether the face is the dress-up's own B-spline face of an elementary surface: its plan
bool planFace(
    const TopoDS_Face& face,
    const TopTools_MapOfShape& baseFaces,
    const std::set<const Geom_Surface*>& baseSurfaces,
    FacePlan& plan
)
{
    if (baseFaces.Contains(face) || !face.Location().IsIdentity()) {
        return false;
    }
    TopLoc_Location location;
    const Handle(Geom_Surface) stored = BRep_Tool::Surface(face, location);
    if (stored.IsNull() || !location.IsIdentity()) {
        return false;
    }
    const Handle(Geom_Surface) surface = basisSurface(stored);
    // A base face the dress-up trimmed keeps its surface: the user's own B-spline is never touched
    if (!isSpline(surface) || baseSurfaces.contains(stored.get())
        || baseSurfaces.contains(surface.get())) {
        return false;
    }
    TopTools_MapOfShape seen;
    for (TopExp_Explorer it(face.Oriented(TopAbs_FORWARD), TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge edge = TopoDS::Edge(it.Current());
        if (edge.Orientation() != TopAbs_FORWARD && edge.Orientation() != TopAbs_REVERSED) {
            return false;
        }
        // No seam, no pole, no closed edge: their pcurves come in pairs or end on themselves
        if (!seen.Add(edge) || BRep_Tool::Degenerated(edge) || BRep_Tool::IsClosed(edge, face)
            || closedEdge(edge) || !edge.Location().IsIdentity()) {
            return false;
        }
    }
    if (seen.IsEmpty()) {
        return false;
    }
    double u1 = 0.0;
    double u2 = 0.0;
    double v1 = 0.0;
    double v2 = 0.0;
    BRepTools::UVBounds(face, u1, u2, v1, v2);
    if (!(u2 > u1) || !(v2 > v1) || Precision::IsInfinite(u1) || Precision::IsInfinite(u2)
        || Precision::IsInfinite(v1) || Precision::IsInfinite(v2)) {
        return false;
    }
    plan.surface = recognise(surface, u1, u2, v1, v2, tolerance);
    if (plan.surface.IsNull()) {
        return false;
    }
    // The fork's own check, not OCCT's gap: the grid over the UV box and points on every edge
    plan.gap = deviation(surface, u1, u2, v1, v2, plan.surface);
    for (TopTools_MapOfShape::Iterator it(seen); it.More() && plan.gap <= tolerance; it.Next()) {
        double first = 0.0;
        double last = 0.0;
        TopLoc_Location where;
        const Handle(Geom_Curve) curve = BRep_Tool::Curve(TopoDS::Edge(it.Key()), where, first, last);
        if (curve.IsNull() || !where.IsIdentity()) {
            return false;
        }
        for (int i = 0; i < edgePoints; ++i) {
            const gp_Pnt p = curve->Value(first + (last - first) * i / (edgePoints - 1));
            plan.gap = std::max(plan.gap, distance(plan.surface, p));
        }
    }
    if (!(plan.gap <= tolerance)) {
        return false;
    }
    // Which side the new normal is on, at the patch's middle
    gp_Pnt middle;
    gp_Vec du;
    gp_Vec dv;
    surface->D1((u1 + u2) / 2.0, (v1 + v2) / 2.0, middle, du, dv);
    if (!parameters(plan.surface, middle, plan.u0, plan.v0)) {
        return false;
    }
    gp_Pnt at;
    gp_Vec nu;
    gp_Vec nv;
    plan.surface->D1(plan.u0, plan.v0, at, nu, nv);
    const gp_Vec before = du.Crossed(dv);
    const gp_Vec after = nu.Crossed(nv);
    if (before.Magnitude() < gp::Resolution() || after.Magnitude() < gp::Resolution()) {
        return false;
    }
    const double cosine = before.Normalized().Dot(after.Normalized());
    if (std::abs(cosine) < 0.9) {
        return false;
    }
    plan.reversed = cosine < 0.0;
    plan.tol = std::max(BRep_Tool::Tolerance(face), 1.2 * plan.gap);
    return true;
}

/** The line, circle or ellipse that a B-spline curve is within tolerance, running the same way
 * over [first, last] of its own parameter: false if it is none, or a check fails.
 */
bool recogniseCurve(const Handle(Geom_Curve)& old, double f, double l, EdgePlan& plan)
{
    Handle(Geom_Curve) found;
    try {
        GeomConvert_CurveToAnaCurve converter(old);
        double newFirst = 0.0;
        double newLast = 0.0;
        if (!converter.ConvertToAnalytical(tolerance, found, f, l, newFirst, newLast) || found.IsNull()) {
            return false;
        }
    }
    catch (const Standard_Failure&) {
        return false;
    }
    found = basisCurve(found);
    const gp_Pnt start = old->Value(f);
    const gp_Pnt middle = old->Value((f + l) / 2.0);
    const gp_Pnt end = old->Value(l);
    const double shortest = 10.0 * tolerance;
    bool periodic = true;
    if (!Handle(Geom_Line)::DownCast(found).IsNull()) {
        const gp_Vec along(start, end);
        if (along.Magnitude() < shortest) {
            return false;
        }
        plan.curve = new Geom_Line(start, gp_Dir(along));
        plan.first = 0.0;
        plan.last = along.Magnitude();
        periodic = false;
    }
    else if (auto circle = Handle(Geom_Circle)::DownCast(found)) {
        const gp_Circ circ = circle->Circ();
        gp_Dir normal = circ.Axis().Direction();
        gp_Vec out(circ.Location(), start);
        out -= gp_Vec(normal) * out.Dot(gp_Vec(normal));
        if (out.Magnitude() < shortest) {
            return false;
        }
        // The circle starts at the edge's start and turns the way the edge runs
        for (int pass = 0; pass < 2 && plan.curve.IsNull(); ++pass) {
            const gp_Circ turned(gp_Ax2(circ.Location(), normal, gp_Dir(out)), circ.Radius());
            const double toMiddle = turn(ElCLib::Parameter(turned, middle));
            const double toEnd = turn(ElCLib::Parameter(turned, end));
            if (toMiddle > 0.0 && toMiddle < toEnd) {
                plan.curve = new Geom_Circle(turned);
                plan.first = 0.0;
                plan.last = toEnd;
            }
            normal.Reverse();
        }
    }
    else if (auto ellipse = Handle(Geom_Ellipse)::DownCast(found)) {
        const gp_Elips elips = ellipse->Elips();
        gp_Dir normal = elips.Axis().Direction();
        for (int pass = 0; pass < 2 && plan.curve.IsNull(); ++pass) {
            const gp_Elips turned(
                gp_Ax2(elips.Location(), normal, elips.XAxis().Direction()),
                elips.MajorRadius(),
                elips.MinorRadius()
            );
            const double from = ElCLib::Parameter(turned, start);
            const double toMiddle = turn(ElCLib::Parameter(turned, middle) - from);
            const double toEnd = turn(ElCLib::Parameter(turned, end) - from);
            if (toMiddle > 0.0 && toMiddle < toEnd) {
                plan.curve = new Geom_Ellipse(turned);
                plan.first = from;
                plan.last = from + toEnd;
            }
            normal.Reverse();
        }
    }
    if (plan.curve.IsNull()) {
        return false;
    }
    // The fork's own check: every point within tolerance, and in order along the new curve
    plan.gap = 0.0;
    double before = plan.first;
    for (int i = 0; i < curvePoints; ++i) {
        const gp_Pnt p = old->Value(f + (l - f) * i / (curvePoints - 1));
        double at = parameter(plan.curve, p);
        if (periodic) {
            at = plan.first + turn(at - plan.first);
        }
        if (i == 0) {
            at = plan.first;
        }
        if (at < before - Precision::PConfusion() || at > plan.last + Precision::PConfusion()) {
            return false;
        }
        before = at;
        plan.gap = std::max(plan.gap, plan.curve->Value(at).Distance(p));
    }
    return plan.gap <= tolerance;
}

/** The pcurve of a curve over [first, last] on a surface, in the period window about (uRef, vRef),
 * checked against the curve: false when there is none within `allowed`.
 */
bool project(
    const Handle(Geom_Curve)& curve,
    double first,
    double last,
    const Handle(Geom_Surface)& surface,
    double uRef,
    double vRef,
    double allowed,
    Pcurve& out,
    std::string& trail
)
{
    Handle(Geom2d_Curve) flat;
    try {
        double reached = Precision::Confusion();
        flat = GeomProjLib::Curve2d(curve, first, last, surface, reached);
    }
    catch (const Standard_Failure&) {
        trail += "; a projection raised an error";
        return false;
    }
    if (flat.IsNull() || flat->FirstParameter() > first + Precision::PConfusion()
        || flat->LastParameter() < last - Precision::PConfusion()) {
        trail += flat.IsNull() ? "; a curve has no projection" : "; a projection is shorter than its curve";
        return false;
    }
    const gp_Pnt2d middle = flat->Value((first + last) / 2.0);
    double du = 0.0;
    double dv = 0.0;
    if (surface->IsUPeriodic()) {
        du = std::round((uRef - middle.X()) / surface->UPeriod()) * surface->UPeriod();
    }
    if (surface->IsVPeriodic()) {
        dv = std::round((vRef - middle.Y()) / surface->VPeriod()) * surface->VPeriod();
    }
    if (du != 0.0 || dv != 0.0) {
        flat = Handle(Geom2d_Curve)::DownCast(flat->Translated(gp_Vec2d(du, dv)));
    }
    // Measured densely: an approximated pcurve is furthest off between the points it was fitted at
    double worst = 0.0;
    for (int i = 0; i < pcurvePoints; ++i) {
        const double t = first + (last - first) * i / (pcurvePoints - 1);
        const gp_Pnt2d uv = flat->Value(t);
        worst = std::max(worst, surface->Value(uv.X(), uv.Y()).Distance(curve->Value(t)));
    }
    if (!(worst <= allowed)) {
        trail += "; a projection is " + std::to_string(worst) + " off its curve";
        return false;
    }
    out.curve = flat;
    out.tol = worst;
    return true;
}

/// Whether a face that stays as it is has an elementary surface: the surface where the face is (a
/// moved face's, or one whose surface is stored moved, as a mirror's, is a copy in place; a pcurve
/// on the copy is one on the face)
bool elementaryFace(const TopoDS_Face& face, Handle(Geom_Surface)& surface)
{
    surface = BRep_Tool::Surface(face);
    return !surface.IsNull()
        && !Handle(Geom_ElementarySurface)::DownCast(basisSurface(surface)).IsNull();
}

/// What to convert, with every new surface, curve and pcurve made and checked: false if nothing
bool makePlan(const TopoDS_Shape& result, const TopoDS_Shape& base, Plan& plan, std::string& trail)
{
    TopTools_MapOfShape baseFaces;
    std::set<const Geom_Surface*> baseSurfaces;
    for (TopExp_Explorer it(base, TopAbs_FACE); it.More(); it.Next()) {
        baseFaces.Add(it.Current());
        TopLoc_Location location;
        const Handle(Geom_Surface) surface = BRep_Tool::Surface(TopoDS::Face(it.Current()), location);
        if (!surface.IsNull()) {
            baseSurfaces.insert(surface.get());
            baseSurfaces.insert(basisSurface(surface).get());
        }
    }
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(result, TopAbs_FACE, faces);
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(result, TopAbs_EDGE, TopAbs_FACE, edgeFaces);

    FacePlans recognised;
    for (int i = 1; i <= faces.Extent(); ++i) {
        FacePlan facePlan;
        if (planFace(TopoDS::Face(faces(i)), baseFaces, baseSurfaces, facePlan)) {
            recognised.Bind(faces(i), facePlan);
        }
    }
    // Edges whose new curve had no pcurve on a neighbour: they keep their curve
    TopTools_MapOfShape keptCurves;
    const int rounds = faces.Extent() + edgeFaces.Extent() + 1;
    for (int round = 0; round < rounds && !recognised.IsEmpty(); ++round) {
        plan = Plan();
        plan.faces = recognised;
        TopTools_IndexedMapOfShape edges;
        for (FacePlans::Iterator it(recognised); it.More(); it.Next()) {
            TopExp::MapShapes(it.Key(), TopAbs_EDGE, edges);
        }
        bool again = false;
        for (int i = 1; i <= edges.Extent() && !again; ++i) {
            const TopoDS_Edge edge = TopoDS::Edge(edges(i));
            const TopTools_ListOfShape& on = edgeFaces.FindFromKey(edge);
            TopLoc_Location location;
            double first = 0.0;
            double last = 0.0;
            const Handle(Geom_Curve) old = BRep_Tool::Curve(edge, location, first, last);
            if (old.IsNull() || !location.IsIdentity()) {
                // No curve to project: its faces stay as they are
                for (const TopoDS_Shape& face : on) {
                    recognised.UnBind(face);
                }
                again = true;
                break;
            }
            // A new curve only when every face on the edge gets or has an elementary surface: a
            // B-spline neighbour's pcurve belongs to the old parametrization
            bool renew = !keptCurves.Contains(edge) && isSpline(basisCurve(old)) && !closedEdge(edge);
            for (const TopoDS_Shape& face : on) {
                Handle(Geom_Surface) surface;
                if (!renew) {
                    break;
                }
                if (!recognised.IsBound(face)
                    && (!elementaryFace(TopoDS::Face(face), surface)
                        || BRep_Tool::IsClosed(edge, TopoDS::Face(face)))) {
                    renew = false;
                }
            }
            EdgePlan edgePlan;
            if (renew && !recogniseCurve(old, first, last, edgePlan)) {
                renew = false;
            }
            const Handle(Geom_Curve) curve = renew ? edgePlan.curve : old;
            const double from = renew ? edgePlan.first : first;
            const double to = renew ? edgePlan.last : last;
            double worst = renew ? edgePlan.gap : 0.0;
            TopTools_MapOfShape done;
            for (const TopoDS_Shape& shape : on) {
                const TopoDS_Face face = TopoDS::Face(shape);
                const bool planned = recognised.IsBound(face);
                if (!done.Add(face) || (!planned && !renew)) {
                    continue;
                }
                Handle(Geom_Surface) surface;
                double uRef = 0.0;
                double vRef = 0.0;
                bool ready = true;
                if (planned) {
                    const FacePlan& facePlan = recognised.Find(face);
                    surface = facePlan.surface;
                    uRef = facePlan.u0;
                    vRef = facePlan.v0;
                }
                else {
                    // An elementary neighbour: the new pcurve stays in the old one's period window
                    double f2 = 0.0;
                    double l2 = 0.0;
                    const Handle(Geom2d_Curve) before = BRep_Tool::CurveOnSurface(edge, face, f2, l2);
                    ready = elementaryFace(face, surface) && !before.IsNull();
                    if (ready) {
                        const gp_Pnt2d at = before->Value((f2 + l2) / 2.0);
                        uRef = at.X();
                        vRef = at.Y();
                    }
                }
                Pcurve pcurve;
                const double allowed = BRep_Tool::Tolerance(edge) + 2.0 * tolerance;
                if (!ready || !project(curve, from, to, surface, uRef, vRef, allowed, pcurve, trail)) {
                    if (renew) {
                        keptCurves.Add(edge);
                    }
                    else {
                        recognised.UnBind(face);
                    }
                    again = true;
                    break;
                }
                worst = std::max(worst, pcurve.tol);
                plan.pcurves[{edge.TShape().get(), face.TShape().get()}] = pcurve;
            }
            if (again) {
                break;
            }
            const double tol = std::max(BRep_Tool::Tolerance(edge), 1.5 * worst);
            for (const TopoDS_Shape& shape : on) {
                auto found = plan.pcurves.find({edge.TShape().get(), shape.TShape().get()});
                if (found != plan.pcurves.end()) {
                    found->second.tol = tol;
                }
            }
            // An edge that keeps its curve is planned too, with that curve: the modifier copies only
            // the edges it is given a curve for, and puts the new pcurves on its copies
            edgePlan.curve = curve;
            edgePlan.renewed = renew;
            edgePlan.first = from;
            edgePlan.last = to;
            edgePlan.tol = tol;
            plan.edges.Bind(edge, edgePlan);
        }
        if (!again) {
            return true;
        }
    }
    return false;
}

/// The plan as BRepTools_Modifier's modification
class Canonical: public BRepTools_Modification
{
public:
    explicit Canonical(const Plan& plan)
        : plan(plan)
    {}

    bool NewSurface(
        const TopoDS_Face& face,
        Handle(Geom_Surface) & surface,
        TopLoc_Location& location,
        double& tol,
        bool& revWires,
        bool& revFace
    ) override
    {
        const FacePlan* found = plan.faces.Seek(face);
        if (!found) {
            return false;
        }
        surface = found->surface;
        location = TopLoc_Location();
        tol = found->tol;
        // The same side of the face is material: with the normal turned, the face turns in its
        // shell and its wires with it
        revWires = found->reversed;
        revFace = found->reversed;
        return true;
    }

    bool NewCurve(
        const TopoDS_Edge& edge,
        Handle(Geom_Curve) & curve,
        TopLoc_Location& location,
        double& tol
    ) override
    {
        const EdgePlan* found = plan.edges.Seek(edge);
        if (!found) {
            return false;
        }
        curve = found->curve;
        location = TopLoc_Location();
        tol = found->tol;
        return true;
    }

    bool NewPoint(const TopoDS_Vertex& /*vertex*/, gp_Pnt& /*point*/, double& /*tol*/) override
    {
        return false;
    }

    bool NewCurve2d(
        const TopoDS_Edge& edge,
        const TopoDS_Face& face,
        const TopoDS_Edge& /*newEdge*/,
        const TopoDS_Face& /*newFace*/,
        Handle(Geom2d_Curve) & curve,
        double& tol
    ) override
    {
        const auto found = plan.pcurves.find({edge.TShape().get(), face.TShape().get()});
        if (found != plan.pcurves.end()) {
            curve = found->second.curve;
            tol = found->second.tol;
            return true;
        }
        // The modifier makes a planned edge anew, without its pcurves. One that keeps its curve
        // keeps its pcurve on a face that stays as it is (the edge as passed: a seam's two sides)
        const EdgePlan* kept = plan.edges.Seek(edge);
        if (!kept || kept->renewed) {
            return false;
        }
        double first = 0.0;
        double last = 0.0;
        curve = BRep_Tool::CurveOnSurface(edge, face, first, last);
        tol = kept->tol;
        return !curve.IsNull();
    }

    bool NewParameter(const TopoDS_Vertex& vertex, const TopoDS_Edge& edge, double& at, double& tol) override
    {
        const EdgePlan* found = plan.edges.Seek(edge);
        if (!found) {
            return false;
        }
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopExp::Vertices(TopoDS::Edge(edge.Oriented(TopAbs_FORWARD)), first, last);
        at = vertex.IsSame(first) ? found->first : found->last;
        const double off = BRep_Tool::Pnt(vertex).Distance(found->curve->Value(at));
        tol = std::max(BRep_Tool::Tolerance(vertex), 1.2 * off);
        return true;
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

    DEFINE_STANDARD_RTTI_INLINE(Canonical, BRepTools_Modification)

private:
    const Plan& plan;
};

int count(const TopoDS_Shape& shape, TopAbs_ShapeEnum type)
{
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, type, map);
    return map.Extent();
}

double area(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(shape, props);
    return props.Mass();
}

double volume(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape, props);
    return props.Mass();
}

/// The defects BRepCheck found (the first six), as " (<shape type> <index>: status <BRepCheck_Status>, ...)"
std::string defects(const BRepCheck_Analyzer& check, const TopoDS_Shape& shape)
{
    std::string all;
    int found = 0;
    const auto add = [&](const std::string& name, BRepCheck_Status status) {
        if (status != BRepCheck_NoError && ++found <= 6) {
            all += (all.empty() ? " (" : ", ") + name + ": status " + std::to_string(static_cast<int>(status));
        }
    };
    for (TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        TopTools_IndexedMapOfShape map;
        TopExp::MapShapes(shape, type, map);
        for (int i = 1; i <= map.Extent(); ++i) {
            const Handle(BRepCheck_Result)& result = check.Result(map(i));
            if (result.IsNull()) {
                continue;
            }
            const std::string name
                = std::string(type == TopAbs_FACE ? "face " : type == TopAbs_EDGE ? "edge " : "vertex ")
                + std::to_string(i);
            for (const BRepCheck_Status status : result->Status()) {
                add(name, status);
            }
            // The sub-shape's defects in each shape that holds it (an edge on a face)
            for (result->InitContextIterator(); result->MoreShapeInContext(); result->NextShapeInContext()) {
                for (const BRepCheck_Status status : result->StatusOnShape()) {
                    add(name + " in its holder", status);
                }
            }
        }
    }
    return all.empty() ? all : all + ")";
}

bool refuse(std::string* why, const char* reason)
{
    if (why) {
        *why = reason;
    }
    return false;
}

}  // namespace

TopoDS_Shape Conversion::image(const TopoDS_Shape& subShape) const
{
    if (!modifier) {
        return subShape;
    }
    try {
        return modifier->ModifiedShape(subShape);
    }
    catch (const Standard_Failure&) {
        return subShape;
    }
}

bool convert(const TopoDS_Shape& result, const TopoDS_Shape& base, Conversion& out, std::string* why)
{
    try {
        if (result.IsNull() || base.IsNull()) {
            return refuse(why, "no shape");
        }
        Plan plan;
        std::string trail;
        if (!makePlan(result, base, plan, trail)) {
            trail = "no B-spline face of the dress-up is an elementary surface" + trail;
            return refuse(why, trail.c_str());
        }
        auto modifier = std::make_shared<BRepTools_Modifier>(result);
        const Handle(Canonical) modification = new Canonical(plan);
        modifier->Perform(modification);
        if (!modifier->IsDone()) {
            return refuse(why, "the modifier did not finish");
        }
        const TopoDS_Shape shape = modifier->ModifiedShape(result);
        // The new curves' ranges, on the curve and its pcurves alike
        BRep_Builder builder;
        for (EdgePlans::Iterator it(plan.edges); it.More(); it.Next()) {
            const TopoDS_Edge edge = TopoDS::Edge(modifier->ModifiedShape(it.Key()));
            builder.Range(edge, it.Value().first, it.Value().last);
        }
        // The whole, or nothing: valid, the same topology, the same solid within tolerance
        if (count(shape, TopAbs_FACE) != count(result, TopAbs_FACE)
            || count(shape, TopAbs_EDGE) != count(result, TopAbs_EDGE)
            || count(shape, TopAbs_VERTEX) != count(result, TopAbs_VERTEX)) {
            return refuse(why, "the converted shape has other counts of faces, edges or vertices");
        }
        const BRepCheck_Analyzer check(shape);
        if (!check.IsValid()) {
            const std::string what = "the converted shape is not valid" + defects(check, shape);
            return refuse(why, what.c_str());
        }
        double converted = 0.0;
        double gap = 0.0;
        for (FacePlans::Iterator it(plan.faces); it.More(); it.Next()) {
            const double before = area(it.Key());
            const double after = area(modifier->ModifiedShape(it.Key()));
            if (!(std::abs(after - before) <= 1e-5 * (1.0 + before))) {
                return refuse(why, "a converted face has another area");
            }
            converted += before;
            gap = std::max(gap, it.Value().gap);
        }
        for (EdgePlans::Iterator it(plan.edges); it.More(); it.Next()) {
            gap = std::max(gap, it.Value().gap);
        }
        const double before = volume(result);
        const double after = volume(shape);
        if (!(std::abs(after - before) <= 2.0 * tolerance * converted + 1e-9 * std::abs(before) + 1e-9)) {
            return refuse(why, "the converted shape has another volume");
        }
        out.shape = shape;
        out.modifier = modifier;
        out.faces = plan.faces.Extent();
        out.edges = 0;
        for (EdgePlans::Iterator it(plan.edges); it.More(); it.Next()) {
            out.edges += it.Value().renewed ? 1 : 0;
        }
        out.gap = gap;
        return true;
    }
    catch (const Standard_Failure& e) {
        const std::string what = std::string("OCCT: ") + e.GetMessageString();
        return refuse(why, what.c_str());
    }
}

double measure(const TopoDS_Face& face, std::string* kind)
{
    TopLoc_Location location;
    const Handle(Geom_Surface) surface = basisSurface(BRep_Tool::Surface(face, location));
    if (surface.IsNull() || !location.IsIdentity() || !isSpline(surface)) {
        return -1.0;
    }
    double u1 = 0.0;
    double u2 = 0.0;
    double v1 = 0.0;
    double v2 = 0.0;
    BRepTools::UVBounds(face, u1, u2, v1, v2);
    const Handle(Geom_ElementarySurface) found = recognise(surface, u1, u2, v1, v2, 1e-2);
    if (found.IsNull()) {
        return -1.0;
    }
    if (kind) {
        *kind = !Handle(Geom_Plane)::DownCast(found).IsNull()                ? "plane"
            : !Handle(Geom_CylindricalSurface)::DownCast(found).IsNull() ? "cylinder"
            : !Handle(Geom_ConicalSurface)::DownCast(found).IsNull()     ? "cone"
            : !Handle(Geom_SphericalSurface)::DownCast(found).IsNull()   ? "sphere"
                                                                           : "torus";
    }
    return deviation(surface, u1, u2, v1, v2, found);
}

const std::vector<TopoDS_Shape>& Mapper::modified(const TopoDS_Shape& s) const
{
    MapperMaker::modified(s);
    for (TopoDS_Shape& shape : _res) {
        shape = conversion.image(shape);
    }
    return _res;
}

const std::vector<TopoDS_Shape>& Mapper::generated(const TopoDS_Shape& s) const
{
    MapperMaker::generated(s);
    for (TopoDS_Shape& shape : _res) {
        shape = conversion.image(shape);
    }
    return _res;
}

}  // namespace Part::CanonicalFaces
