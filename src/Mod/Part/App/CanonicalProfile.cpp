// SPDX-License-Identifier: LGPL-2.1-or-later

// Canonical curves on a profile before a sweep (ops#640). See CanonicalProfile.h.

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <sstream>

#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepTools_ReShape.hxx>
#include <BRep_Tool.hxx>
#include <ElCLib.hxx>
#include <GeomConvert_CurveToAnaCurve.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_Circle.hxx>
#include <Geom_Line.hxx>
#include <Geom_Plane.hxx>
#include <Geom_Surface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Lin.hxx>

#include <Base/Exception.h>

#include "CanonicalProfile.h"
#include "TopoShape.h"

namespace Part
{
namespace
{
std::string number(double value)
{
    std::ostringstream text;
    text << std::setprecision(3) << value;
    return text.str();
}

[[noreturn]] void refuse(const std::string& why)
{
    throw Base::CADKernelError("Canonical profile curves (ops#640): " + why);
}

bool isSpline(Handle(Geom_Curve) curve)
{
    while (!curve.IsNull() && curve->IsKind(STANDARD_TYPE(Geom_TrimmedCurve))) {
        curve = Handle(Geom_TrimmedCurve)::DownCast(curve)->BasisCurve();
    }
    return !curve.IsNull()
        && (curve->IsKind(STANDARD_TYPE(Geom_BSplineCurve))
            || curve->IsKind(STANDARD_TYPE(Geom_BezierCurve)));
}

// Whether every face on the edge lies on a plane: OCCT reads an edge's curve on a plane from its
// 3D curve, so the new edge needs no curve on the face
bool onPlanesOnly(const TopTools_ListOfShape& faces)
{
    for (const TopoDS_Shape& face : faces) {
        TopLoc_Location location;
        const Handle(Geom_Surface) surface = BRep_Tool::Surface(TopoDS::Face(face), location);
        if (surface.IsNull() || !surface->IsKind(STANDARD_TYPE(Geom_Plane))) {
            return false;
        }
    }
    return true;
}
}  // namespace

void checkCanonicalEdge(
    const Handle(Geom_Curve) & oldCurve,
    double first,
    double last,
    const Handle(Geom_Curve) & newCurve,
    double newFirst,
    double newLast,
    double tolerance
)
{
    const Handle(Geom_Line) line = Handle(Geom_Line)::DownCast(newCurve);
    const Handle(Geom_Circle) circle = Handle(Geom_Circle)::DownCast(newCurve);
    if (oldCurve.IsNull() || (line.IsNull() && circle.IsNull()) || !(newLast > newFirst)) {
        refuse("the canonical curve is not a line or a circle with a range");
    }
    // The tolerance in the new curve's parameter: length along a line, angle on a circle
    const double slack = circle.IsNull() ? tolerance : tolerance / circle->Radius();
    const bool closed = !circle.IsNull() && newLast - newFirst > 2 * M_PI - slack;
    constexpr int samples = 64;
    double worst = 0;
    double previous = newFirst - slack;
    for (int k = 0; k <= samples; ++k) {
        const gp_Pnt point = oldCurve->Value(first + (last - first) * k / samples);
        double parameter {};
        gp_Pnt onNew;
        if (!line.IsNull()) {
            parameter = ElCLib::Parameter(line->Lin(), point);
            onNew = ElCLib::Value(parameter, line->Lin());
        }
        else {
            parameter = ElCLib::InPeriod(
                ElCLib::Parameter(circle->Circ(), point),
                newFirst - slack,
                newFirst - slack + 2 * M_PI
            );
            if (closed && k == samples && parameter < previous) {
                parameter += 2 * M_PI;  // a whole circle ends where it starts
            }
            onNew = ElCLib::Value(parameter, circle->Circ());
        }
        worst = std::max(worst, point.Distance(onNew));
        if (parameter < previous - slack || parameter > newLast + slack) {
            refuse(
                "the line or circle runs another way than the edge (sample " + std::to_string(k)
                + " of " + std::to_string(samples) + ")"
            );
        }
        previous = parameter;
    }
    const double startGap = oldCurve->Value(first).Distance(newCurve->Value(newFirst));
    const double endGap = oldCurve->Value(last).Distance(newCurve->Value(newLast));
    worst = std::max({worst, startGap, endGap});
    if (!(worst <= tolerance)) {
        refuse(
            "the edge is " + number(worst) + " from its " + (line.IsNull() ? "circle" : "line")
            + ", more than " + number(tolerance)
        );
    }
}

int canonicalProfile(TopoShape& profile, const gp_Ax1* revolveAxis)
{
    const TopoDS_Shape shape = profile.getShape();
    if (shape.IsNull()) {
        return 0;
    }
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    BRepTools_ReShape reshape;
    int converted = 0;
    for (int i = 1; i <= edgeFaces.Extent(); ++i) {
        const TopoDS_Edge edge = TopoDS::Edge(edgeFaces.FindKey(i).Oriented(TopAbs_FORWARD));
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        double first {}, last {};
        const Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);  // located
        if (!isSpline(curve) || !onPlanesOnly(edgeFaces(i))) {
            continue;
        }
        const double tolerance = kCanonicalProfileTolerance;
        double newFirst {}, newLast {}, deviation {};
        Handle(Geom_Curve) canonical;
        try {
            canonical = GeomConvert_CurveToAnaCurve::ComputeLine(
                curve,
                tolerance,
                first,
                last,
                newFirst,
                newLast,
                deviation
            );
            if (canonical.IsNull()) {
                canonical = GeomConvert_CurveToAnaCurve::ComputeCircle(
                    curve,
                    tolerance,
                    first,
                    last,
                    newFirst,
                    newLast,
                    deviation
                );
            }
        }
        catch (const Standard_Failure&) {
            canonical.Nullify();  // not recognised: today's path
        }
        if (canonical.IsNull()) {
            continue;
        }
        const Handle(Geom_Circle) circle = Handle(Geom_Circle)::DownCast(canonical);
        if (revolveAxis && !circle.IsNull()
            && gp_Lin(*revolveAxis).Distance(circle->Location()) <= circle->Radius() + tolerance) {
            continue;  // a horn or spindle torus: OCCT refuses it by rule (ops#640, scout 5)
        }
        checkCanonicalEdge(curve, first, last, canonical, newFirst, newLast, tolerance);
        TopoDS_Vertex start, end;
        TopExp::Vertices(edge, start, end);
        BRepBuilderAPI_MakeEdge maker(canonical, start, end, newFirst, newLast);
        if (!maker.IsDone()) {
            refuse(
                "OCCT made no edge on the edge's " + std::string(circle.IsNull() ? "line" : "circle")
                + " (error " + std::to_string(static_cast<int>(maker.Error())) + ")"
            );
        }
        reshape.Replace(edge, maker.Edge().Oriented(TopAbs_FORWARD));
        ++converted;
    }
    if (converted == 0) {
        return 0;
    }
    const TopoDS_Shape result = reshape.Apply(shape);
    if (result.IsNull() || !BRepCheck_Analyzer(result).IsValid()) {
        refuse("the profile with its lines and circles is not valid");
    }
    // The same sub-shapes in the same order, so the element map still holds: vertices kept,
    // each edge kept or replaced by its own line or circle
    for (const TopAbs_ShapeEnum kind : {TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE, TopAbs_VERTEX}) {
        TopTools_IndexedMapOfShape before;
        TopTools_IndexedMapOfShape after;
        TopExp::MapShapes(shape, kind, before);
        TopExp::MapShapes(result, kind, after);
        if (before.Extent() != after.Extent()) {
            refuse("the profile's sub-shapes changed in number");
        }
        for (int i = 1; i <= before.Extent(); ++i) {
            const bool kept = before(i).IsSame(after(i))
                || reshape.Value(before(i)).IsSame(after(i));
            if (kind == TopAbs_VERTEX && !before(i).IsSame(after(i))) {
                refuse("a vertex of the profile changed");
            }
            if (kind == TopAbs_EDGE && !kept) {
                refuse("the profile's edges changed order");
            }
        }
    }
    profile.setShape(result, false);
    return converted;
}

}  // namespace Part
