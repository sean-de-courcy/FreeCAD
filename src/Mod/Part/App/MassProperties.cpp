// SPDX-License-Identifier: LGPL-2.1-or-later

#include <vector>

#include <BRepBuilderAPI_NurbsConvert.hxx>
#include <BRepGProp.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_OffsetCurve.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_OffsetCurve.hxx>
#include <Geom_OffsetSurface.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom_SurfaceOfLinearExtrusion.hxx>
#include <Geom_SurfaceOfRevolution.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <gp_XYZ.hxx>

#include "MassProperties.h"

namespace Part::MassProperties
{

namespace
{

// The relative distance from their line within which poles are collinear
constexpr double straightTolerance = 1e-9;

// Whether the points lie on one line. Coincident points do too: their curve has no extent
bool straight(const std::vector<gp_XYZ>& points)
{
    const gp_XYZ& origin = points.front();
    gp_XYZ direction;
    double extent = 0.0;
    for (const auto& point : points) {
        const double distance = (point - origin).Modulus();
        if (distance > extent) {
            extent = distance;
            direction = point - origin;
        }
    }
    if (extent <= 0.0) {
        return true;
    }
    direction /= extent;
    for (const auto& point : points) {
        if ((point - origin).Crossed(direction).Modulus() > straightTolerance * extent) {
            return false;
        }
    }
    return true;
}

// The number of the curve's knot spans that [first, last] covers
template<class Curve>
int spansIn(const Curve& curve, double first, double last)
{
    int spans = 1;
    for (int i = 1; i <= curve.NbKnots(); ++i) {
        const double knot = curve.Knot(i);
        if (knot > first + Precision::PConfusion() && knot < last - Precision::PConfusion()) {
            ++spans;
        }
    }
    return spans;
}

std::vector<gp_XYZ> polesOf(const Geom_BSplineCurve& curve)
{
    std::vector<gp_XYZ> poles;
    for (int i = 1; i <= curve.NbPoles(); ++i) {
        poles.push_back(curve.Pole(i).XYZ());
    }
    return poles;
}

std::vector<gp_XYZ> polesOf(const Geom2d_BSplineCurve& curve)
{
    std::vector<gp_XYZ> poles;
    for (int i = 1; i <= curve.NbPoles(); ++i) {
        poles.emplace_back(curve.Pole(i).X(), curve.Pole(i).Y(), 0.0);
    }
    return poles;
}

// Whether the curve over [first, last] is a B-spline of more than spanThreshold spans that isn't
// straight. A straight one was exact at every span count (ops#414 note); a revolution's basis
// curve counts straight or not (\a exemptStraight false): the note didn't measure that case
bool needsCare(Handle(Geom_Curve) curve, double first, double last, bool exemptStraight = true)
{
    for (;;) {
        if (auto trimmed = Handle(Geom_TrimmedCurve)::DownCast(curve)) {
            curve = trimmed->BasisCurve();
        }
        else if (auto offset = Handle(Geom_OffsetCurve)::DownCast(curve)) {
            curve = offset->BasisCurve();
        }
        else {
            break;
        }
    }
    auto bspline = Handle(Geom_BSplineCurve)::DownCast(curve);
    return bspline && spansIn(*bspline, first, last) > spanThreshold
        && !(exemptStraight && straight(polesOf(*bspline)));
}

bool needsCare(Handle(Geom2d_Curve) curve, double first, double last)
{
    for (;;) {
        if (auto trimmed = Handle(Geom2d_TrimmedCurve)::DownCast(curve)) {
            curve = trimmed->BasisCurve();
        }
        else if (auto offset = Handle(Geom2d_OffsetCurve)::DownCast(curve)) {
            curve = offset->BasisCurve();
        }
        else {
            break;
        }
    }
    auto bspline = Handle(Geom2d_BSplineCurve)::DownCast(curve);
    return bspline && spansIn(*bspline, first, last) > spanThreshold
        && !straight(polesOf(*bspline));
}

// Whether the B-spline surface has more than spanThreshold spans in a direction along which a row
// of its poles isn't straight
bool needsCare(const Geom_BSplineSurface& surface)
{
    const auto curvedAlong = [&](bool alongU) {
        const int rows = alongU ? surface.NbVPoles() : surface.NbUPoles();
        const int length = alongU ? surface.NbUPoles() : surface.NbVPoles();
        for (int row = 1; row <= rows; ++row) {
            std::vector<gp_XYZ> poles;
            for (int i = 1; i <= length; ++i) {
                poles.push_back((alongU ? surface.Pole(i, row) : surface.Pole(row, i)).XYZ());
            }
            if (!straight(poles)) {
                return true;
            }
        }
        return false;
    };
    return (surface.NbUKnots() - 1 > spanThreshold && curvedAlong(true))
        || (surface.NbVKnots() - 1 > spanThreshold && curvedAlong(false));
}

// The surface inside its trimmed and offset wrappers
Handle(Geom_Surface) unwrapped(Handle(Geom_Surface) surface)
{
    for (;;) {
        if (auto trimmed = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface)) {
            surface = trimmed->BasisSurface();
        }
        else if (auto offset = Handle(Geom_OffsetSurface)::DownCast(surface)) {
            surface = offset->BasisSurface();
        }
        else {
            return surface;
        }
    }
}

bool needsCare(const Handle(Geom_Surface) & wrapped)
{
    const auto surface = unwrapped(wrapped);
    if (auto bspline = Handle(Geom_BSplineSurface)::DownCast(surface)) {
        return needsCare(*bspline);
    }
    if (auto extrusion = Handle(Geom_SurfaceOfLinearExtrusion)::DownCast(surface)) {
        const auto& basis = extrusion->BasisCurve();
        return needsCare(basis, basis->FirstParameter(), basis->LastParameter());
    }
    if (auto revolution = Handle(Geom_SurfaceOfRevolution)::DownCast(surface)) {
        const auto& basis = revolution->BasisCurve();
        return needsCare(basis, basis->FirstParameter(), basis->LastParameter(), false);
    }
    return false;
}

bool needsCare(const TopoDS_Face& face)
{
    TopLoc_Location location;
    const auto surface = BRep_Tool::Surface(face, location);
    if (surface && needsCare(surface)) {
        return true;
    }
    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        double first = 0.0;
        double last = 0.0;
        const auto curve = BRep_Tool::Curve(edge, first, last);
        if (curve && needsCare(curve, first, last)) {
            return true;
        }
        const auto pcurve = BRep_Tool::CurveOnSurface(edge, face, first, last);
        if (pcurve && needsCare(pcurve, first, last)) {
            return true;
        }
    }
    return false;
}

}  // namespace

bool needsAdaptive(const TopoDS_Shape& shape)
{
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    for (int i = 1; i <= faces.Extent(); ++i) {
        if (needsCare(TopoDS::Face(faces(i)))) {
            return true;
        }
    }
    return false;
}

namespace
{

// The volume properties, with the centre of mass and inertia when everything is set; the mass
// alone otherwise, which costs the adaptive method about a tenth (ops#414: 30-60 ms against
// 300-600 ms on prisms of 200-1000 spans)
void volumeProperties(const TopoDS_Shape& shape, GProp_GProps& props, bool everything)
{
    if (needsAdaptive(shape)) {
        GProp_GProps adaptive = props;
        const bool onlyClosed = false;
        // One integration per knot span. Without, the volume a cut removed from a 500- or
        // 1000-span prism, a difference of whole volumes, was off by 3e-6 and 3e-4 at any
        // tolerance, too much for FilletFallback's 1e-6 checks; and a 150 x 150-span face took
        // 46 s instead of 2 (ops#414)
        const bool useSpans = true;
        if (BRepGProp::VolumePropertiesGK(
                shape,
                adaptive,
                adaptiveTolerance,
                onlyClosed,
                useSpans,
                everything,
                everything
            )
            >= 0.0) {
            props = adaptive;
            return;
        }
        // The adaptive method failed: the default, as before
    }
    BRepGProp::VolumeProperties(shape, props);
}

}  // namespace

void volumeProperties(const TopoDS_Shape& shape, GProp_GProps& props)
{
    volumeProperties(shape, props, true);
}

namespace
{

bool onExtrusion(const TopoDS_Face& face)
{
    TopLoc_Location location;
    const auto surface = BRep_Tool::Surface(face, location);
    return surface && unwrapped(surface)->IsKind(STANDARD_TYPE(Geom_SurfaceOfLinearExtrusion));
}

// The shape's faces for the adaptive area: those on an extrusion (through trimmed and offset
// wrappers) converted to NURBS. OCCT's adaptive area is off on an extrusion of a long curved
// B-spline while its error estimate reports convergence (ops#414: 1.9 % on 41 spans, 4 to a
// wave; 1.3e-4 on 500), and right on the same face as a B-spline surface. The shape itself when
// it has no such face
TopoDS_Shape facesForArea(const TopoDS_Shape& shape)
{
    BRep_Builder builder;
    TopoDS_Compound faces;
    builder.MakeCompound(faces);
    bool converted = false;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face& face = TopoDS::Face(it.Current());
        if (onExtrusion(face)) {
            try {
                BRepBuilderAPI_NurbsConvert nurbs(face);
                if (nurbs.IsDone()) {
                    builder.Add(faces, nurbs.Shape());
                    converted = true;
                    continue;
                }
            }
            catch (const Standard_Failure&) {
                // The face as it is
            }
        }
        builder.Add(faces, face);
    }
    return converted ? TopoDS_Shape(faces) : shape;
}

}  // namespace

void surfaceProperties(const TopoDS_Shape& shape, GProp_GProps& props)
{
    if (needsAdaptive(shape)) {
        GProp_GProps adaptive = props;
        if (BRepGProp::SurfaceProperties(facesForArea(shape), adaptive, adaptiveTolerance) >= 0.0) {
            props = adaptive;
            return;
        }
    }
    BRepGProp::SurfaceProperties(shape, props);
}

double volume(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    volumeProperties(shape, props, false);
    return props.Mass();
}

double area(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    surfaceProperties(shape, props);
    return props.Mass();
}

}  // namespace Part::MassProperties
