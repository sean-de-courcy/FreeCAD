// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <utility>
#include <vector>

#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepGProp.hxx>
#include <BRepLib.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepTools.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_BezierCurve.hxx>
#include <Geom2d_Line.hxx>
#include <Geom2d_OffsetCurve.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_OffsetCurve.hxx>
#include <Geom_OffsetSurface.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom_SurfaceOfLinearExtrusion.hxx>
#include <Geom_SurfaceOfRevolution.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <Precision.hxx>
#include <Bnd_Box.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp.hxx>
#include <gp_Mat.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <gp_Vec2d.hxx>
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

// The curve inside its trimmed and offset wrappers, which keep its parameter
Handle(Geom_Curve) innermost(Handle(Geom_Curve) curve)
{
    for (;;) {
        if (auto trimmed = Handle(Geom_TrimmedCurve)::DownCast(curve)) {
            curve = trimmed->BasisCurve();
        }
        else if (auto offset = Handle(Geom_OffsetCurve)::DownCast(curve)) {
            curve = offset->BasisCurve();
        }
        else {
            return curve;
        }
    }
}

Handle(Geom2d_Curve) innermost(Handle(Geom2d_Curve) curve)
{
    for (;;) {
        if (auto trimmed = Handle(Geom2d_TrimmedCurve)::DownCast(curve)) {
            curve = trimmed->BasisCurve();
        }
        else if (auto offset = Handle(Geom2d_OffsetCurve)::DownCast(curve)) {
            curve = offset->BasisCurve();
        }
        else {
            return curve;
        }
    }
}

// Whether the curve over [first, last] is a B-spline of more than spanThreshold spans that isn't
// straight. A straight one was exact at every span count (ops#414 note); a revolution's basis
// curve counts straight or not (\a exemptStraight false): the note didn't measure that case
bool needsCare(const Handle(Geom_Curve) & curve, double first, double last, bool exemptStraight = true)
{
    auto bspline = Handle(Geom_BSplineCurve)::DownCast(innermost(curve));
    return bspline && spansIn(*bspline, first, last) > spanThreshold
        && !(exemptStraight && straight(polesOf(*bspline)));
}

bool needsCare(const Handle(Geom2d_Curve) & curve, double first, double last)
{
    auto bspline = Handle(Geom2d_BSplineCurve)::DownCast(innermost(curve));
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

// Whether a face's parameters leave its surface's own range: a face across a periodic surface's
// seam, whose pcurves lie a period over (a Pad up to a loft's periodic B-spline side: u -0.34 to
// 0.34 on a surface of 0 to 2 pi)
bool outsideItsSurface(const TopoDS_Face& face)
{
    TopLoc_Location location;
    const auto surface = BRep_Tool::Surface(face, location);
    if (surface.IsNull()) {
        return false;
    }
    double u0 = 0.0;
    double u1 = 0.0;
    double v0 = 0.0;
    double v1 = 0.0;
    surface->Bounds(u0, u1, v0, v1);
    double a0 = 0.0;
    double a1 = 0.0;
    double b0 = 0.0;
    double b1 = 0.0;
    BRepTools::UVBounds(face, a0, a1, b0, b1);
    const double margin = Precision::PConfusion();
    auto past = [margin](double low, double high, double first, double last) {
        return (!Precision::IsInfinite(low) && first < low - margin)
            || (!Precision::IsInfinite(high) && last > high + margin);
    };
    return past(u0, u1, a0, a1) || past(v0, v1, b0, b1);
}

bool anyOutsideItsSurface(const TopoDS_Shape& shape)
{
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    for (int i = 1; i <= faces.Extent(); ++i) {
        if (outsideItsSurface(TopoDS::Face(faces(i)))) {
            return true;
        }
    }
    return false;
}

// The reference point of OCCT 8.0.1's volume integrations (BRepGProp's roughBaryCenter): the mean
// of the shape's vertices, each counted as often as an explorer visits it
gp_XYZ vertexMean(const TopoDS_Shape& shape, int& count)
{
    gp_XYZ sum(0.0, 0.0, 0.0);
    count = 0;
    for (TopExp_Explorer it(shape, TopAbs_VERTEX); it.More(); it.Next()) {
        sum += BRep_Tool::Pnt(TopoDS::Vertex(it.Current())).XYZ();
        ++count;
    }
    return count > 0 ? sum / count : sum;
}

struct SurfaceSample
{
    gp_XYZ point;
    gp_XYZ normal;
};

// Each face's surface points and unit normals on a 3 x 3 grid over the face's parameter range
std::vector<std::vector<SurfaceSample>> faceSamples(const TopoDS_Shape& shape)
{
    std::vector<std::vector<SurfaceSample>> all;
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    for (int i = 1; i <= faces.Extent(); ++i) {
        const TopoDS_Face& face = TopoDS::Face(faces(i));
        std::vector<SurfaceSample> samples;
        try {
            double u0 = 0.0;
            double u1 = 0.0;
            double v0 = 0.0;
            double v1 = 0.0;
            BRepTools::UVBounds(face, u0, u1, v0, v1);
            if (Precision::IsInfinite(u0) || Precision::IsInfinite(u1) || Precision::IsInfinite(v0)
                || Precision::IsInfinite(v1)) {
                continue;
            }
            const BRepAdaptor_Surface surface(face, false);
            for (const double a : {0.1, 0.5, 0.9}) {
                for (const double b : {0.1, 0.5, 0.9}) {
                    gp_Pnt point;
                    gp_Vec alongU;
                    gp_Vec alongV;
                    surface.D1(u0 + a * (u1 - u0), v0 + b * (v1 - v0), point, alongU, alongV);
                    const gp_Vec normal = alongU.Crossed(alongV);
                    if (normal.Magnitude() > gp::Resolution()) {
                        samples.push_back({point.XYZ(), normal.Normalized().XYZ()});
                    }
                }
            }
        }
        catch (const Standard_Failure&) {
            samples.clear();
        }
        if (!samples.empty()) {
            all.push_back(std::move(samples));
        }
    }
    return all;
}

// The least, over the faces, of the largest |(x - point).n| at a face's samples: about 0 when a
// face lies on a plane or a cone through the point
double clearance(const std::vector<std::vector<SurfaceSample>>& faces, const gp_XYZ& point)
{
    double least = std::numeric_limits<double>::infinity();
    for (const auto& samples : faces) {
        double most = 0.0;
        for (const auto& sample : samples) {
            most = std::max(most, std::abs((sample.point - point).Dot(sample.normal)));
        }
        least = std::min(least, most);
    }
    return least;
}

// Fixed general directions for moving OCCT's reference point
const std::array<gp_XYZ, 6> referenceDirections {
    gp_XYZ(0.31, 0.27, 0.16),
    gp_XYZ(-0.23, 0.41, -0.12),
    gp_XYZ(0.17, -0.29, 0.37),
    gp_XYZ(-0.37, -0.11, 0.25),
    gp_XYZ(0.13, 0.33, -0.39),
    gp_XYZ(-0.19, -0.36, -0.28)
};

// The shape and one isolated vertex that bring the mean of its count vertices (mean) plus that
// one to target: OCCT's reference point for the volume integrals. A vertex holds no volume
TopoDS_Shape withVertexMeanAt(const TopoDS_Shape& shape, const gp_XYZ& target, const gp_XYZ& mean, int count)
{
    const gp_XYZ position = target * (count + 1) - mean * count;
    BRep_Builder builder;
    TopoDS_Vertex vertex;
    builder.MakeVertex(vertex, gp_Pnt(position), Precision::Confusion());
    TopoDS_Compound compound;
    builder.MakeCompound(compound);
    builder.Add(compound, shape);
    builder.Add(compound, vertex);
    return compound;
}

// The shape whose volume to integrate adaptively: the shape itself, or, when a face lies on a
// plane (or a cone) through OCCT's reference point, the shape and one isolated vertex that move
// that point clear of every face (a vertex holds no volume, and a closed shell's integral is the
// same from any point). That face's term is ~0 there, its relative error never converges, and
// the volume of a centred cut of a rotated NURBS torus took over 10 minutes for 5 ms (SC7, ops#640)
TopoDS_Shape withClearReference(const TopoDS_Shape& shape)
{
    int count = 0;
    const gp_XYZ mean = vertexMean(shape, count);
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    if (count == 0 || box.IsVoid()) {
        return shape;
    }
    const gp_XYZ low = box.CornerMin().XYZ();
    const gp_XYZ high = box.CornerMax().XYZ();
    const double size = (high - low).Modulus();
    const double needed = 1e-3 * size;
    const auto faces = faceSamples(shape);
    if (!(size > 0.0) || faces.empty() || clearance(faces, mean) >= needed) {
        return shape;
    }
    // The box's centre, else points around it in fixed general directions
    const gp_XYZ centre = (low + high) / 2.0;
    const auto& directions = referenceDirections;
    gp_XYZ best = centre;
    double bestClearance = clearance(faces, centre);
    for (const double fraction : {0.05, 0.13}) {
        for (const auto& direction : directions) {
            if (bestClearance >= needed) {
                break;
            }
            const gp_XYZ candidate = centre + direction * (fraction * size / direction.Modulus());
            const double candidateClearance = clearance(faces, candidate);
            if (candidateClearance > bestClearance) {
                best = candidate;
                bestClearance = candidateClearance;
            }
        }
    }
    return withVertexMeanAt(shape, best, mean, count);
}

// The shape and one isolated vertex that put OCCT's reference point 0.02 box diagonals off the
// box centre, clear of every face where it can: the centre and inertia readouts' integration
// (ops#680). About a point at the centre a face's first moments can be 0 (the one face of SC7's
// scaled sphere), their relative error never converges, and the adaptive centre took 92 s; 0.02
// off, 0.03 s within 5e-10 mm. The centre's error grows with the distance, about the tolerance
// times it (a cylinder drilled by 60 holes: 5.7e-5 mm at 0.02, 8.7e-5 at 0.1, 1e-3 at 2 diagonals
// with momentsTolerance), hence a small one. OCCT has no absolute error bound: this is one
TopoDS_Shape offCentreReference(const TopoDS_Shape& shape)
{
    int count = 0;
    const gp_XYZ mean = vertexMean(shape, count);
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    if (count == 0 || box.IsVoid()) {
        return shape;
    }
    const gp_XYZ low = box.CornerMin().XYZ();
    const gp_XYZ high = box.CornerMax().XYZ();
    const double size = (high - low).Modulus();
    if (!(size > 0.0)) {
        return shape;
    }
    const double needed = 1e-3 * size;
    const auto faces = faceSamples(shape);
    const gp_XYZ centre = (low + high) / 2.0;
    gp_XYZ best = centre;
    double bestClearance = -1.0;
    for (const auto& direction : referenceDirections) {
        const gp_XYZ candidate = centre + direction * (0.02 * size / direction.Modulus());
        const double candidateClearance = faces.empty() ? needed : clearance(faces, candidate);
        if (candidateClearance > bestClearance) {
            best = candidate;
            bestClearance = candidateClearance;
        }
        if (bestClearance >= needed) {
            break;
        }
    }
    return withVertexMeanAt(shape, best, mean, count);
}

// The adaptive volume properties into props, with the centre of mass and inertia when everything
// is set; false, with props unchanged, when the integration failed
bool adaptiveVolume(
    const TopoDS_Shape& shape,
    GProp_GProps& props,
    bool everything,
    double tolerance = adaptiveTolerance,
    bool offCentre = false
)
{
    GProp_GProps adaptive = props;
    const bool onlyClosed = false;
    // One integration per knot span. Without, the volume a cut removed from a 500- or 1000-span
    // prism, a difference of whole volumes, was off by 3e-6 and 3e-4 at any tolerance, too much
    // for FilletFallback's 1e-6 checks; and a 150 x 150-span face took 46 s instead of 2 (ops#414)
    // Not where a face lies across its surface's seam: the spans are the surface's knots, and
    // OCCT 8.0.1's integration by spans then read the Pad's prism 156.716 for 167.266 (6 %; its
    // area right): the integration over the whole face is within 1e-8 there (SC7, ops#640)
    const bool useSpans = !anyOutsideItsSurface(shape);
    if (BRepGProp::VolumePropertiesGK(
            offCentre ? offCentreReference(shape) : withClearReference(shape),
            adaptive,
            tolerance,
            onlyClosed,
            useSpans,
            everything,
            everything
        )
        < 0.0) {
        return false;
    }
    props = adaptive;
    return true;
}

// The volume properties, with the centre of mass and inertia when everything is set; the mass
// alone otherwise, which costs the adaptive method about a tenth (ops#414: 30-60 ms against
// 300-600 ms on prisms of 200-1000 spans). Adaptive when forceAdaptive or needsAdaptive()
void integrateVolume(
    const TopoDS_Shape& shape,
    GProp_GProps& props,
    bool everything,
    bool forceAdaptive,
    double tolerance = adaptiveTolerance
)
{
    if ((forceAdaptive || needsAdaptive(shape)) && adaptiveVolume(shape, props, everything, tolerance)) {
        return;
    }
    // Not screened, or the adaptive method failed: the default, as before
    BRepGProp::VolumeProperties(shape, props);
}

}  // namespace

void volumeProperties(const TopoDS_Shape& shape, GProp_GProps& props)
{
    integrateVolume(shape, props, true, false);
}

void volumeProperties(const TopoDS_Shape& shape, GProp_GProps& props, bool forceAdaptive)
{
    integrateVolume(shape, props, true, forceAdaptive);
}

namespace
{

// A face's area, its first moments and its second moments about the origin: a, x, y, z, xx, yy,
// zz, xy, xz, yz
using Moments = std::array<double, 10>;

Moments& operator+=(Moments& sum, const Moments& term)
{
    for (std::size_t i = 0; i < sum.size(); ++i) {
        sum[i] += term[i];
    }
    return sum;
}

// The knots of a curve, where its derivatives may jump; a periodic curve's repeat with its period
class Breaks
{
public:
    explicit Breaks(const Handle(Geom_Curve) & curve)
    {
        if (auto bspline = Handle(Geom_BSplineCurve)::DownCast(innermost(curve))) {
            for (int i = 1; i <= bspline->NbKnots(); ++i) {
                knots.push_back(bspline->Knot(i));
            }
            if (bspline->IsPeriodic()) {
                period = bspline->Period();
            }
        }
    }

    explicit Breaks(const Handle(Geom2d_Curve) & curve)
    {
        if (auto bspline = Handle(Geom2d_BSplineCurve)::DownCast(innermost(curve))) {
            for (int i = 1; i <= bspline->NbKnots(); ++i) {
                knots.push_back(bspline->Knot(i));
            }
            if (bspline->IsPeriodic()) {
                period = bspline->Period();
            }
        }
    }

    // The breaks strictly between a and b (a < b), in increasing order
    std::vector<double> between(double a, double b) const
    {
        std::vector<double> result;
        if (knots.empty()) {
            return result;
        }
        int first = 0;
        int last = 0;
        if (period > 0.0) {
            first = static_cast<int>(std::floor((a - knots.back()) / period));
            last = static_cast<int>(std::ceil((b - knots.front()) / period));
        }
        for (int shift = first; shift <= last; ++shift) {
            for (std::size_t i = 0; i < knots.size(); ++i) {
                // A periodic curve's last knot is its first one period on
                if (period > 0.0 && i + 1 == knots.size()) {
                    break;
                }
                const double knot = knots[i] + shift * period;
                if (knot > a + Precision::PConfusion() && knot < b - Precision::PConfusion()) {
                    result.push_back(knot);
                }
            }
        }
        return result;
    }

    // A surface's knots in one parameter, with their period when periodic
    Breaks(std::vector<double> theKnots, double thePeriod)
        : knots(std::move(theKnots))
        , period(thePeriod)
    {}

private:
    std::vector<double> knots;
    double period = 0.0;
};

// The integrand along a pcurve of a face on S(u, v) = f(u) + v d: an extrusion, or an offset
// surface of one (f = c + r N, N the normal, a function of u alone). For g a function of the
// point, the integral of g |S_u x d| over the face's domain is, by Green's theorem in (u, v), the
// integral of -G |S_u x d| du along its boundary, G the integral of g along v from v0. With s = v -
// v0 and b the point at v0 on the same ruling: G = s for the area, s b + s^2 / 2 d for the first
// moments, s b b^T + s^2 / 2 (b d^T + d b^T) + s^3 / 3 d d^T for the second
struct Integrand
{
    Handle(Geom_Surface) surface;
    gp_Trsf transformation;
    gp_XYZ direction;
    double v0 = 0.0;
    Handle(Geom2d_Curve) pcurve;

    Moments operator()(double t) const
    {
        Moments moments {};
        gp_Pnt2d uv;
        gp_Vec2d tangent;
        pcurve->D1(t, uv, tangent);
        if (tangent.X() == 0.0) {
            return moments;
        }
        gp_Pnt point;
        gp_Vec alongU;
        gp_Vec alongV;
        surface->D1(uv.X(), uv.Y(), point, alongU, alongV);
        point.Transform(transformation);
        alongU.Transform(transformation);
        const double s = uv.Y() - v0;
        const gp_XYZ& d = direction;
        const gp_XYZ b = point.XYZ() - s * d;
        const double w = -alongU.XYZ().Crossed(d).Modulus() * tangent.X();
        const double s2 = s * s / 2;
        const double s3 = s * s * s / 3;
        moments[0] = w * s;
        moments[1] = w * (s * b.X() + s2 * d.X());
        moments[2] = w * (s * b.Y() + s2 * d.Y());
        moments[3] = w * (s * b.Z() + s2 * d.Z());
        const auto second = [&](double bi, double bj, double di, double dj) {
            return w * (s * bi * bj + s2 * (bi * dj + di * bj) + s3 * di * dj);
        };
        moments[4] = second(b.X(), b.X(), d.X(), d.X());
        moments[5] = second(b.Y(), b.Y(), d.Y(), d.Y());
        moments[6] = second(b.Z(), b.Z(), d.Z(), d.Z());
        moments[7] = second(b.X(), b.Y(), d.X(), d.Y());
        moments[8] = second(b.X(), b.Z(), d.X(), d.Z());
        moments[9] = second(b.Y(), b.Z(), d.Y(), d.Z());
        return moments;
    }
};

// 8-point Gauss-Legendre on [-1, 1]
constexpr double gaussNodes[] = {
    -0.9602898564975363,
    -0.7966664774136267,
    -0.5255324099163290,
    -0.1834346424956498,
    0.1834346424956498,
    0.5255324099163290,
    0.7966664774136267,
    0.9602898564975363
};
constexpr double gaussWeights[] = {
    0.1012285362903763,
    0.2223810344533745,
    0.3137066458778873,
    0.3626837833783620,
    0.3626837833783620,
    0.3137066458778873,
    0.2223810344533745,
    0.1012285362903763
};

// The halves of an interval agree with the whole within this part of the sum of their terms'
// magnitudes, or of this part of the face's (an integrand of rounding noise never agrees with
// itself: an edge along v0, whose s is zero up to rounding)
constexpr double agreement = 1e-11;
constexpr double faceAgreement = 1e-14;
// Integrand evaluations per face before the boundary integral gives up for OCCT's adaptive area
constexpr long evaluationBudget = 2000000;

// Gauss-Legendre on intervals over which the integrand is smooth: first on each interval, which
// gives the face's magnitude, then on the halves of each, halving further where they disagree
class BoundaryIntegral
{
public:
    explicit BoundaryIntegral(const Integrand& integrand)
        : f(integrand)
    {}

    // The first estimate over [a, b], its terms' magnitudes added to the face's
    Moments first(double a, double b)
    {
        return gauss(a, b, faceSize);
    }

    // The integral over [a, b], refined from its first estimate
    Moments refined(double a, double b, const Moments& whole)
    {
        return refined(a, b, whole, 0);
    }

    bool withinBudget() const
    {
        return evaluations <= evaluationBudget;
    }

private:
    Moments gauss(double a, double b, Moments& size)
    {
        Moments sum {};
        const double middle = (a + b) / 2;
        const double half = (b - a) / 2;
        for (int k = 0; k < 8; ++k) {
            Moments term = f(middle + half * gaussNodes[k]);
            for (std::size_t i = 0; i < term.size(); ++i) {
                term[i] *= gaussWeights[k] * half;
                sum[i] += term[i];
                size[i] += std::abs(term[i]);
            }
        }
        evaluations += 8;
        return sum;
    }

    Moments refined(double a, double b, const Moments& whole, int depth)
    {
        const double middle = (a + b) / 2;
        Moments size {};
        const Moments left = gauss(a, middle, size);
        const Moments right = gauss(middle, b, size);
        Moments halves = left;
        halves += right;
        bool agree = true;
        for (std::size_t i = 0; i < halves.size(); ++i) {
            const double tolerance = std::max(agreement * size[i], faceAgreement * faceSize[i]);
            if (std::abs(halves[i] - whole[i]) > tolerance) {
                agree = false;
            }
        }
        if (agree || depth >= 30 || !withinBudget()) {
            return halves;
        }
        Moments result = refined(a, middle, left, depth + 1);
        result += refined(middle, b, right, depth + 1);
        return result;
    }

    const Integrand& f;
    Moments faceSize {};
    long evaluations = 0;
};

// The parameters in [a, b] where the pcurve's u crosses a break of the extrusion's basis curve,
// with a and b. Each span of the pcurve is searched in pieces, along which u is taken as monotonic
std::vector<double> pieces(const Handle(Geom2d_Curve) & pcurve, double a, double b, const Breaks& basisBreaks)
{
    std::vector<double> spans {a};
    for (double knot : Breaks(pcurve).between(a, b)) {
        spans.push_back(knot);
    }
    spans.push_back(b);
    const int divisions = innermost(pcurve)->IsKind(STANDARD_TYPE(Geom2d_Line)) ? 1 : 4;
    std::vector<double> result {a};
    for (std::size_t i = 0; i + 1 < spans.size(); ++i) {
        for (int j = 0; j < divisions; ++j) {
            const double p = spans[i] + (spans[i + 1] - spans[i]) * j / divisions;
            const double q = j + 1 == divisions
                ? spans[i + 1]
                : spans[i] + (spans[i + 1] - spans[i]) * (j + 1) / divisions;
            const double up = pcurve->Value(p).X();
            const double uq = pcurve->Value(q).X();
            if (up == uq) {
                result.push_back(q);
                continue;
            }
            const bool rising = uq > up;
            auto crossings = basisBreaks.between(std::min(up, uq), std::max(up, uq));
            if (!rising) {
                std::reverse(crossings.begin(), crossings.end());
            }
            double low = p;
            for (double knot : crossings) {
                // Bisection for u(t) = knot in [low, q]
                double lo = low;
                double hi = q;
                for (int k = 0; k < 100 && hi - lo > 1e-15 * std::max(1.0, std::abs(hi)); ++k) {
                    const double mid = (lo + hi) / 2;
                    if ((pcurve->Value(mid).X() < knot) == rising) {
                        lo = mid;
                    }
                    else {
                        hi = mid;
                    }
                }
                const double t = (lo + hi) / 2;
                if (t > result.back()) {
                    result.push_back(t);
                }
                low = t;
            }
            if (q > result.back()) {
                result.push_back(q);
            }
        }
    }
    return result;
}

// The moments of a face on an extrusion or on an offset surface of one, exact for any basis curve
// up to the integration's tolerance; false when the face has an edge without a pcurve, or its
// boundary integral isn't positive or takes too long
bool extrusionMoments(const TopoDS_Face& face, Moments& moments)
{
    TopLoc_Location location;
    const auto surface = BRep_Tool::Surface(face, location);
    if (!surface) {
        return false;
    }
    auto extrusion = Handle(Geom_SurfaceOfLinearExtrusion)::DownCast(unwrapped(surface));
    if (!extrusion) {
        return false;
    }
    Integrand integrand;
    integrand.surface = surface;
    integrand.transformation = location.Transformation();
    gp_Vec direction(extrusion->Direction());
    direction.Transform(integrand.transformation);
    integrand.direction = direction.XYZ();
    const Breaks basisBreaks(extrusion->BasisCurve());

    // Along the edges of the face taken forward, their pcurves bound its domain anticlockwise
    struct Boundary
    {
        Handle(Geom2d_Curve) pcurve;
        double sense = 1.0;
        std::vector<double> ts;
        std::vector<Moments> estimates;
    };
    std::vector<Boundary> boundaries;
    const TopoDS_Face forward = TopoDS::Face(face.Oriented(TopAbs_FORWARD));
    for (TopExp_Explorer it(forward, TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        if (edge.Orientation() != TopAbs_FORWARD && edge.Orientation() != TopAbs_REVERSED) {
            // An internal or external edge bounds nothing
            continue;
        }
        Boundary boundary;
        double a = 0.0;
        double b = 0.0;
        boundary.pcurve = BRep_Tool::CurveOnSurface(edge, forward, a, b);
        if (!boundary.pcurve) {
            return false;
        }
        if (boundaries.empty()) {
            integrand.v0 = boundary.pcurve->Value(a).Y();
        }
        boundary.sense = edge.Orientation() == TopAbs_REVERSED ? -1.0 : 1.0;
        boundary.ts = pieces(boundary.pcurve, a, b, basisBreaks);
        boundaries.push_back(std::move(boundary));
    }
    BoundaryIntegral integral(integrand);
    for (auto& boundary : boundaries) {
        integrand.pcurve = boundary.pcurve;
        for (std::size_t i = 0; i + 1 < boundary.ts.size(); ++i) {
            boundary.estimates.push_back(integral.first(boundary.ts[i], boundary.ts[i + 1]));
        }
    }
    Moments total {};
    for (const auto& boundary : boundaries) {
        integrand.pcurve = boundary.pcurve;
        for (std::size_t i = 0; i + 1 < boundary.ts.size(); ++i) {
            const Moments part
                = integral.refined(boundary.ts[i], boundary.ts[i + 1], boundary.estimates[i]);
            for (std::size_t j = 0; j < total.size(); ++j) {
                total[j] += boundary.sense * part[j];
            }
        }
        if (!integral.withinBudget()) {
            return false;
        }
    }
    if (!(total[0] > 0.0)) {
        return false;
    }
    moments = total;
    return true;
}

// The breaks of a free-form surface in one parameter strictly between a and b, with a and b: the
// knots of a B-spline surface, of a revolution's basis curve along v; none for a Bezier surface. An
// empty list for other surfaces
std::vector<double> surfaceBreaks(const Handle(Geom_Surface) & wrapped, bool alongU, double a, double b)
{
    const auto surface = unwrapped(wrapped);
    std::vector<double> inside;
    if (auto bspline = Handle(Geom_BSplineSurface)::DownCast(surface)) {
        std::vector<double> knots;
        const int count = alongU ? bspline->NbUKnots() : bspline->NbVKnots();
        for (int i = 1; i <= count; ++i) {
            knots.push_back(alongU ? bspline->UKnot(i) : bspline->VKnot(i));
        }
        const bool periodic = alongU ? bspline->IsUPeriodic() : bspline->IsVPeriodic();
        const double period = periodic ? (alongU ? bspline->UPeriod() : bspline->VPeriod()) : 0.0;
        inside = Breaks(std::move(knots), period).between(a, b);
    }
    else if (auto revolution = Handle(Geom_SurfaceOfRevolution)::DownCast(surface)) {
        const auto basis = innermost(revolution->BasisCurve());
        if (!Handle(Geom_BSplineCurve)::DownCast(basis) && !Handle(Geom_BezierCurve)::DownCast(basis)) {
            return {};
        }
        if (!alongU) {
            inside = Breaks(revolution->BasisCurve()).between(a, b);
        }
    }
    else if (!Handle(Geom_BezierSurface)::DownCast(surface)) {
        return {};
    }
    std::vector<double> all {a};
    all.insert(all.end(), inside.begin(), inside.end());
    all.push_back(b);
    return all;
}

// Whether the face is the whole rectangle of its parameter bounds: one wire, every edge's pcurve
// on one side of the rectangle (a loft's, a sweep's or a converted solid's faces, before a cut)
bool natural(const TopoDS_Face& face, double& u0, double& u1, double& v0, double& v1)
{
    BRepTools::UVBounds(face, u0, u1, v0, v1);
    if (Precision::IsInfinite(u0) || Precision::IsInfinite(u1) || Precision::IsInfinite(v0)
        || Precision::IsInfinite(v1) || !(u1 > u0) || !(v1 > v0)) {
        return false;
    }
    int wires = 0;
    for (TopExp_Explorer it(face, TopAbs_WIRE); it.More(); it.Next()) {
        ++wires;
    }
    if (wires != 1) {
        return false;
    }
    const double du = 1e-9 * (u1 - u0);
    const double dv = 1e-9 * (v1 - v0);
    const TopoDS_Face forward = TopoDS::Face(face.Oriented(TopAbs_FORWARD));
    for (TopExp_Explorer it(forward, TopAbs_EDGE); it.More(); it.Next()) {
        double a = 0.0;
        double b = 0.0;
        const auto pcurve = BRep_Tool::CurveOnSurface(TopoDS::Edge(it.Current()), forward, a, b);
        if (!pcurve) {
            return false;
        }
        bool onU0 = true;
        bool onU1 = true;
        bool onV0 = true;
        bool onV1 = true;
        for (int k = 0; k <= 4; ++k) {
            const gp_Pnt2d p = pcurve->Value(a + (b - a) * k / 4.0);
            onU0 = onU0 && std::abs(p.X() - u0) <= du;
            onU1 = onU1 && std::abs(p.X() - u1) <= du;
            onV0 = onV0 && std::abs(p.Y() - v0) <= dv;
            onV1 = onV1 && std::abs(p.Y() - v1) <= dv;
        }
        if (!(onU0 || onU1 || onV0 || onV1)) {
            return false;
        }
    }
    return true;
}

// The moments of a natural free-form face (above) by 8-point Gauss-Legendre on its knot spans, each
// split into 2^level panels a side, from level 0 until two levels agree within 1e-12 on the area.
// OCCT's adaptive area doesn't converge on such faces and its error estimate is no guide: a twisted
// ruled loft's bilinear face 5.2e-6 off at 1e-9 (estimate 5e-14) and 2.9e-7 at 1e-12, where OCCT's
// default is 2.8e-11 off (SC7, ops#640). False on other faces, or past the budget of surface
// evaluations (OCCT's adaptive integration then)
bool naturalMoments(const TopoDS_Face& face, Moments& moments)
{
    double u0 = 0.0;
    double u1 = 0.0;
    double v0 = 0.0;
    double v1 = 0.0;
    TopLoc_Location location;
    const auto surface = BRep_Tool::Surface(face, location);
    if (!surface || !natural(face, u0, u1, v0, v1)) {
        return false;
    }
    const auto us = surfaceBreaks(surface, true, u0, u1);
    const auto vs = surfaceBreaks(surface, false, v0, v1);
    if (us.size() < 2 || vs.size() < 2) {
        return false;
    }
    static constexpr std::array<double, 8> nodes {
        -0.9602898564975363,
        -0.7966664774136267,
        -0.5255324099163290,
        -0.1834346424956498,
        0.1834346424956498,
        0.5255324099163290,
        0.7966664774136267,
        0.9602898564975363
    };
    static constexpr std::array<double, 8> weights {
        0.1012285362903763,
        0.2223810344533745,
        0.3137066458778873,
        0.3626837833783620,
        0.3626837833783620,
        0.3137066458778873,
        0.2223810344533745,
        0.1012285362903763
    };
    const BRepAdaptor_Surface adaptor(face, false);
    const double cells = double(us.size() - 1) * double(vs.size() - 1);
    constexpr double budget = 4e6;
    const auto at = [&](int level) {
        const int panels = 1 << level;
        Moments total {};
        for (std::size_t i = 0; i + 1 < us.size(); ++i) {
            for (std::size_t j = 0; j + 1 < vs.size(); ++j) {
                const double hu = (us[i + 1] - us[i]) / panels;
                const double hv = (vs[j + 1] - vs[j]) / panels;
                for (int p = 0; p < panels; ++p) {
                    for (int q = 0; q < panels; ++q) {
                        for (std::size_t a = 0; a < nodes.size(); ++a) {
                            for (std::size_t b = 0; b < nodes.size(); ++b) {
                                const double u = us[i] + hu * (p + (nodes[a] + 1.0) / 2.0);
                                const double v = vs[j] + hv * (q + (nodes[b] + 1.0) / 2.0);
                                gp_Pnt point;
                                gp_Vec alongU;
                                gp_Vec alongV;
                                adaptor.D1(u, v, point, alongU, alongV);
                                const double w = alongU.Crossed(alongV).Magnitude() * weights[a]
                                    * weights[b] * hu * hv / 4.0;
                                const double x = point.X();
                                const double y = point.Y();
                                const double z = point.Z();
                                total += Moments {
                                    w,
                                    w * x,
                                    w * y,
                                    w * z,
                                    w * x * x,
                                    w * y * y,
                                    w * z * z,
                                    w * x * y,
                                    w * x * z,
                                    w * y * z
                                };
                            }
                        }
                    }
                }
            }
        }
        return total;
    };
    Moments previous = at(0);
    for (int level = 1; level <= 4; ++level) {
        if (cells * double(1 << (2 * level)) * 64.0 > budget) {
            return false;
        }
        const Moments next = at(level);
        if (std::abs(next[0] - previous[0]) <= 1e-12 * std::abs(next[0])) {
            if (!(next[0] > 0.0)) {
                return false;
            }
            moments = next;
            return true;
        }
        previous = next;
    }
    return false;
}

// A face's properties from its moments, stored as OCCT's own integrations store them: the centre
// of mass absolute, the matrix of inertia about the location, here the origin
class FaceProps: public GProp_GProps
{
public:
    explicit FaceProps(const Moments& m)
    {
        dim = m[0];
        g.SetXYZ(gp_XYZ(m[1], m[2], m[3]) / m[0]);
        inertia = gp_Mat(
            gp_XYZ(m[5] + m[6], -m[7], -m[8]),
            gp_XYZ(-m[7], m[4] + m[6], -m[9]),
            gp_XYZ(-m[8], -m[9], m[4] + m[5])
        );
    }
};

// The adaptive surface properties: the faces on extrusions (through trimmed and offset wrappers)
// exactly by their boundary integrals, the others by OCCT's adaptive integration. OCCT's adaptive
// area is off on an extrusion of a long curved B-spline while its error estimate reports
// convergence (ops#414: 1.9 % on 41 spans, 4 to a wave; 1.3e-4 on 500), and a NURBS conversion of
// such a face was approximate (offset curves) or slow to integrate (trimmed faces). False when the
// adaptive integration fails
bool adaptiveSurfaceProperties(
    const TopoDS_Shape& shape,
    GProp_GProps& props,
    double tolerance = adaptiveTolerance
)
{
    BRep_Builder builder;
    TopoDS_Compound others;
    builder.MakeCompound(others);
    GProp_GProps exact;
    bool anyExact = false;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face& face = TopoDS::Face(it.Current());
        Moments moments {};
        bool done = false;
        try {
            done = extrusionMoments(face, moments) || naturalMoments(face, moments);
        }
        catch (const Standard_Failure&) {
            // OCCT's adaptive area for this face
        }
        if (done) {
            exact.Add(FaceProps(moments));
            anyExact = true;
        }
        else {
            builder.Add(others, face);
        }
    }
    if (!anyExact) {
        return BRepGProp::SurfaceProperties(shape, props, tolerance) >= 0.0;
    }
    GProp_GProps rest;
    if (BRepGProp::SurfaceProperties(others, rest, tolerance) < 0.0) {
        return false;
    }
    if (rest.Mass() > 0.0) {
        exact.Add(rest);
    }
    props = exact;
    return true;
}

}  // namespace

namespace
{

void integrateSurface(
    const TopoDS_Shape& shape,
    GProp_GProps& props,
    bool forceAdaptive,
    double tolerance = adaptiveTolerance
)
{
    if (forceAdaptive || needsAdaptive(shape)) {
        GProp_GProps adaptive = props;
        if (adaptiveSurfaceProperties(shape, adaptive, tolerance)) {
            props = adaptive;
            return;
        }
    }
    BRepGProp::SurfaceProperties(shape, props);
}

}  // namespace

void surfaceProperties(const TopoDS_Shape& shape, GProp_GProps& props)
{
    integrateSurface(shape, props, false);
}

double volume(const TopoDS_Shape& shape)
{
    return volume(shape, false);
}

double area(const TopoDS_Shape& shape)
{
    return area(shape, false);
}

double volume(const TopoDS_Shape& shape, bool forceAdaptive)
{
    GProp_GProps props;
    integrateVolume(shape, props, false, forceAdaptive);
    return props.Mass();
}

double area(const TopoDS_Shape& shape, bool forceAdaptive)
{
    GProp_GProps props;
    integrateSurface(shape, props, forceAdaptive);
    return props.Mass();
}

namespace
{

// Whether the curve, inside its trimmed and offset wrappers, is a Bezier curve or a B-spline whose
// poles aren't on one line (OCCT's default integration is exact on straight ones)
bool freeForm(const Handle(Geom_Curve) & curve)
{
    const auto inner = innermost(curve);
    if (inner.IsNull()) {
        return false;
    }
    if (auto bspline = Handle(Geom_BSplineCurve)::DownCast(inner)) {
        return !straight(polesOf(*bspline));
    }
    return inner->IsKind(STANDARD_TYPE(Geom_BezierCurve));
}

bool freeForm(const Handle(Geom2d_Curve) & curve)
{
    const auto inner = innermost(curve);
    if (inner.IsNull()) {
        return false;
    }
    if (auto bspline = Handle(Geom2d_BSplineCurve)::DownCast(inner)) {
        return !straight(polesOf(*bspline));
    }
    return inner->IsKind(STANDARD_TYPE(Geom2d_BezierCurve));
}

bool freeForm(const TopoDS_Face& face)
{
    TopLoc_Location location;
    const auto surface = unwrapped(BRep_Tool::Surface(face, location));
    if (surface.IsNull()) {
        return false;
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_BSplineSurface))
        || surface->IsKind(STANDARD_TYPE(Geom_BezierSurface))) {
        return true;
    }
    if (auto extrusion = Handle(Geom_SurfaceOfLinearExtrusion)::DownCast(surface)) {
        if (freeForm(extrusion->BasisCurve())) {
            return true;
        }
    }
    if (auto revolution = Handle(Geom_SurfaceOfRevolution)::DownCast(surface)) {
        if (freeForm(revolution->BasisCurve())) {
            return true;
        }
    }
    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        double first = 0.0;
        double last = 0.0;
        if (freeForm(BRep_Tool::Curve(edge, first, last))
            || freeForm(BRep_Tool::CurveOnSurface(edge, face, first, last))) {
            return true;
        }
    }
    return false;
}

}  // namespace

bool hasFreeForm(const TopoDS_Shape& shape)
{
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    for (int i = 1; i <= faces.Extent(); ++i) {
        if (freeForm(TopoDS::Face(faces(i)))) {
            return true;
        }
    }
    return false;
}

// The area readouts' relative error per face on free-form faces: OCCT's adaptive area at 1e-6
// was 2.9e-6 off on SC7's scaled sphere, its error estimate being optimistic, and 1e-9 costs
// little (0.17 s on 100 scaled spheres). Volumes keep adaptiveTolerance: at 1e-9 a volume with
// its inertia took 82 s on one scaled sphere (Onshape's volumes are within 2e-5)
constexpr double readoutTolerance = 1e-9;

// The centre and inertia readouts' relative tolerance, the mass keeping adaptiveTolerance (SC7 b,
// ops#640). On a cylinder drilled by 60 holes the centre took 6.5 s at 1e-6, 3.8 s at 1e-5,
// 1.8 s at 1e-4 (5e-5 mm from a 1e-8 run; the inertia 7e-7 relative) and 0.7 s at 1e-3: OCCT's
// error estimate covers every moment, the near-zero ones too
constexpr double momentsTolerance = 1e-4;

namespace
{

// Props with its mass replaced by a more accurate one, the inertia (about the location) scaled
// alike and the centre kept
class WithMass: public GProp_GProps
{
public:
    WithMass(const GProp_GProps& props, double mass)
        : GProp_GProps(props)
    {
        if (dim != 0.0) {
            inertia *= mass / dim;
        }
        dim = mass;
    }
};

}  // namespace

void readoutVolumeProperties(const TopoDS_Shape& shape, GProp_GProps& props)
{
    // Adaptive on free-form faces too, about a point off the centre (offCentreReference, ops#680):
    // the default integration put a symmetric drilled cylinder's centre 6.8e-4 mm off its axis
    // (4.6e-5 mm adaptive, 2.6 s), and SC7's scaled sphere's 2.2e-3 mm (5e-10, 0.03 s)
    if (!needsAdaptive(shape) && !hasFreeForm(shape)) {
        integrateVolume(shape, props, true, false);
        return;
    }
    GProp_GProps moments = props;
    if (!adaptiveVolume(shape, moments, true, momentsTolerance, true)) {
        BRepGProp::VolumeProperties(shape, props);
        return;
    }
    props = WithMass(moments, volume(shape, true));
}

void readoutSurfaceProperties(const TopoDS_Shape& shape, GProp_GProps& props)
{
    const bool freeForm = hasFreeForm(shape);
    integrateSurface(shape, props, freeForm, freeForm ? readoutTolerance : adaptiveTolerance);
}

double readoutVolume(const TopoDS_Shape& shape)
{
    return volume(shape, hasFreeForm(shape));
}

double readoutArea(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    readoutSurfaceProperties(shape, props);
    return props.Mass();
}

bool centreOfMass(const TopoDS_Shape& shape, gp_Pnt& centre)
{
    if (shape.IsNull()) {
        return false;
    }
    GProp_GProps props;
    if (TopExp_Explorer(shape, TopAbs_SOLID).More()) {
        volumeProperties(shape, props);
    }
    else if (TopExp_Explorer(shape, TopAbs_FACE).More()) {
        surfaceProperties(shape, props);
    }
    else if (TopExp_Explorer(shape, TopAbs_EDGE).More()) {
        BRepGProp::LinearProperties(shape, props);
    }
    else {
        gp_XYZ sum;
        int count = 0;
        for (TopExp_Explorer it(shape, TopAbs_VERTEX); it.More(); it.Next()) {
            sum += BRep_Tool::Pnt(TopoDS::Vertex(it.Current())).XYZ();
            ++count;
        }
        if (count == 0) {
            return false;
        }
        centre.SetXYZ(sum / count);
        return true;
    }
    if (props.Mass() > Precision::Infinite()) {
        return false;
    }
    centre = props.CentreOfMass();
    return true;
}

bool orientClosedSolid(TopoDS_Solid& solid)
{
    // The sign from the adaptive integration alone: the default one is the integration that is
    // wrong on these solids, and volume() falls back to it when the adaptive one fails
    GProp_GProps props;
    if (needsAdaptive(solid) && adaptiveVolume(solid, props, false)) {
        const double signedVolume = props.Mass();
        if (std::isfinite(signedVolume) && signedVolume != 0.0) {
            if (signedVolume < 0.0) {
                solid.Reverse();
            }
            return true;
        }
    }
    // Not screened, or no sign to go by: the classifier, as before
    return BRepLib::OrientClosedSolid(solid);
}

}  // namespace Part::MassProperties
