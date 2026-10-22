// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <map>
#include <numbers>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include <Bnd_Box.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_NurbsConvert.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <BRepTopAdaptor_FClass2d.hxx>
#include <ElSLib.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GCPnts_UniformAbscissa.hxx>
#include <Geom_Circle.hxx>
#include <Geom_Curve.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Geom2dAPI_Interpolate.hxx>
#include <Geom2dAPI_PointsToBSpline.hxx>
#include <Geom2dAPI_ProjectPointOnCurve.hxx>
#include <Geom2dConvert_CompCurveToBSplineCurve.hxx>
#include <GeomAdaptor_Curve.hxx>
#include <GeomAPI.hxx>
#include <GeomConvert.hxx>
#include <GeomConvert_BSplineSurfaceToBezierSurface.hxx>
#include <GProp_GProps.hxx>
#include <gp_Ax3.hxx>
#include <gp_Circ.hxx>
#include <gp_Pln.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec2d.hxx>
#include <IntCurvesFace_Intersector.hxx>
#include <Precision.hxx>
#include <TColGeom_Array2OfBezierSurface.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColgp_HArray1OfPnt2d.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <TColStd_HArray1OfReal.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <QtGlobal>

#include <Base/Exception.h>
#include <Base/Tools.h>

#include "FirstContactJumps.h"

namespace PartDesign::FirstContact
{

double binomial(int n, int k)
{
    static const std::vector<double> table = [] {
        constexpr int size = largestSilhouetteDegree + 1;
        std::vector<double> rows(size * size, 0.0);
        for (int i = 0; i < size; ++i) {
            rows[i * size] = 1.0;
            for (int j = 1; j <= i; ++j) {
                rows[i * size + j] = rows[(i - 1) * size + j - 1] + rows[(i - 1) * size + j];
            }
        }
        return rows;
    }();
    return table[n * (largestSilhouetteDegree + 1) + k];
}

Bernstein product(const Bernstein& a, const Bernstein& b)
{
    Bernstein c(a.m + b.m, a.n + b.n);
    for (int i = 0; i <= a.m; ++i) {
        for (int j = 0; j <= a.n; ++j) {
            const double scale = binomial(a.m, i) * binomial(a.n, j);
            const double value = a.value[a.index(i, j)] * scale;
            const double bound = a.bound[a.index(i, j)] * scale;
            if (bound == 0.0) {
                continue;
            }
            for (int k = 0; k <= b.m; ++k) {
                for (int l = 0; l <= b.n; ++l) {
                    const double other = binomial(b.m, k) * binomial(b.n, l);
                    c.value[c.index(i + k, j + l)] += value * b.value[b.index(k, l)] * other;
                    c.bound[c.index(i + k, j + l)] += bound * b.bound[b.index(k, l)] * other;
                }
            }
        }
    }
    for (int i = 0; i <= c.m; ++i) {
        for (int j = 0; j <= c.n; ++j) {
            const double scale = binomial(c.m, i) * binomial(c.n, j);
            c.value[c.index(i, j)] /= scale;
            c.bound[c.index(i, j)] /= scale;
        }
    }
    return c;
}

// a + sign b, of the same degree (every sum in the silhouette's polynomial is)
Bernstein sum(const Bernstein& a, const Bernstein& b, double sign)
{
    if (a.m != b.m || a.n != b.n) {
        throw Base::RuntimeError("Revolution: Internal error: Bernstein degrees differ");
    }
    Bernstein c = a;
    for (std::size_t k = 0; k < c.value.size(); ++k) {
        c.value[k] += sign * b.value[k];
        c.bound[k] += b.bound[k];
    }
    return c;
}

Bernstein scaled(const Bernstein& a, double factor)
{
    Bernstein c = a;
    for (std::size_t k = 0; k < c.value.size(); ++k) {
        c.value[k] *= factor;
        c.bound[k] *= std::abs(factor);
    }
    return c;
}

Bernstein derivative(const Bernstein& a, bool alongU)
{
    const int degree = alongU ? a.m : a.n;
    Bernstein d(alongU ? std::max(a.m - 1, 0) : a.m, alongU ? a.n : std::max(a.n - 1, 0));
    if (degree == 0) {
        return d;
    }
    for (int i = 0; i <= d.m; ++i) {
        for (int j = 0; j <= d.n; ++j) {
            const int next = alongU ? a.index(i + 1, j) : a.index(i, j + 1);
            d.value[d.index(i, j)] = degree * (a.value[next] - a.value[a.index(i, j)]);
            d.bound[d.index(i, j)] = degree * (a.bound[next] + a.bound[a.index(i, j)]);
        }
    }
    return d;
}

// The two halves of a polynomial split at the middle of u or v (de Casteljau)
std::pair<Bernstein, Bernstein> halves(const Bernstein& a, bool alongU)
{
    Bernstein low(a.m, a.n);
    Bernstein high(a.m, a.n);
    const int degree = alongU ? a.m : a.n;
    const int lines = alongU ? a.n + 1 : a.m + 1;
    std::vector<double> value(degree + 1);
    std::vector<double> bound(degree + 1);
    for (int line = 0; line < lines; ++line) {
        auto at = [&](int k) {
            return alongU ? a.index(k, line) : a.index(line, k);
        };
        for (int k = 0; k <= degree; ++k) {
            value[k] = a.value[at(k)];
            bound[k] = a.bound[at(k)];
        }
        for (int step = 0; step <= degree; ++step) {
            low.value[at(step)] = value[0];
            low.bound[at(step)] = bound[0];
            high.value[at(degree - step)] = value[degree - step];
            high.bound[at(degree - step)] = bound[degree - step];
            for (int k = 0; k < degree - step; ++k) {
                value[k] = (value[k] + value[k + 1]) / 2.0;
                bound[k] = (bound[k] + bound[k + 1]) / 2.0;
            }
        }
    }
    return {low, high};
}

// Whether a polynomial has one sign over its whole patch: every coefficient is of that sign by more
// than its rounding (the convex hull property)
bool oneSign(const Bernstein& a)
{
    bool positive = true;
    bool negative = true;
    for (std::size_t k = 0; k < a.value.size(); ++k) {
        const double margin = 1e-10 * a.bound[k];
        positive = positive && a.value[k] > margin;
        negative = negative && a.value[k] < -margin;
    }
    return positive || negative;
}

SilhouettePatch silhouettePatch(const Handle(Geom_BezierSurface)& bezier, const gp_Ax1& axis)
{
    const int p = bezier->UDegree();
    const int q = bezier->VDegree();
    TColgp_Array2OfPnt poles(1, p + 1, 1, q + 1);
    bezier->Poles(poles);
    TColStd_Array2OfReal weights(1, p + 1, 1, q + 1);
    weights.Init(1.0);
    if (bezier->IsURational() || bezier->IsVRational()) {
        bezier->Weights(weights);
    }
    double lightest = std::numeric_limits<double>::max();
    double heaviest = 0.0;
    for (int i = 1; i <= p + 1; ++i) {
        for (int j = 1; j <= q + 1; ++j) {
            lightest = std::min(lightest, weights(i, j));
            heaviest = std::max(heaviest, weights(i, j));
        }
    }
    const bool rational = heaviest - lightest > 1e-12 * heaviest;
    SilhouettePatch patch;
    patch.net = {Bernstein(p, q), Bernstein(p, q), Bernstein(p, q)};
    patch.weights = Bernstein(p, q);
    const gp_XYZ center = axis.Location().XYZ();
    for (int i = 0; i <= p; ++i) {
        for (int j = 0; j <= q; ++j) {
            const double weight = rational ? weights(i + 1, j + 1) : 1.0;
            const gp_XYZ offset = poles(i + 1, j + 1).XYZ() - center;
            for (int k = 0; k < 3; ++k) {
                patch.net[k].value[patch.net[k].index(i, j)] = weight * offset.Coord(k + 1);
                patch.net[k].bound[patch.net[k].index(i, j)] = std::abs(weight * offset.Coord(k + 1));
            }
            patch.weights.value[patch.weights.index(i, j)] = weight;
            patch.weights.bound[patch.weights.index(i, j)] = weight;
        }
    }
    // The tangents, up to the positive factor W^2
    std::array<Bernstein, 3> alongU;
    std::array<Bernstein, 3> alongV;
    for (int k = 0; k < 3; ++k) {
        if (rational) {
            alongU[k] = sum(
                product(derivative(patch.net[k], true), patch.weights),
                product(patch.net[k], derivative(patch.weights, true)),
                -1.0
            );
            alongV[k] = sum(
                product(derivative(patch.net[k], false), patch.weights),
                product(patch.net[k], derivative(patch.weights, false)),
                -1.0
            );
        }
        else {
            alongU[k] = derivative(patch.net[k], true);
            alongV[k] = derivative(patch.net[k], false);
        }
    }
    auto cross = [](const std::array<Bernstein, 3>& u, const std::array<Bernstein, 3>& v) {
        return std::array<Bernstein, 3> {
            sum(product(u[1], v[2]), product(u[2], v[1]), -1.0),
            sum(product(u[2], v[0]), product(u[0], v[2]), -1.0),
            sum(product(u[0], v[1]), product(u[1], v[0]), -1.0)
        };
    };
    const std::array<Bernstein, 3> normal = cross(alongU, alongV);
    const gp_XYZ a = axis.Direction().XYZ();
    const std::array<Bernstein, 3> turning {
        sum(scaled(patch.net[2], a.Y()), scaled(patch.net[1], a.Z()), -1.0),
        sum(scaled(patch.net[0], a.Z()), scaled(patch.net[2], a.X()), -1.0),
        sum(scaled(patch.net[1], a.X()), scaled(patch.net[0], a.Y()), -1.0)
    };
    patch.g = sum(
        sum(product(normal[0], turning[0]), product(normal[1], turning[1])),
        product(normal[2], turning[2])
    );
    return patch;
}

// The value of a polynomial at (s, t) (de Casteljau)
double valueAt(const Bernstein& a, double s, double t)
{
    auto reduce = [](std::vector<double> values, double x) {
        for (std::size_t k = 1; k < values.size(); ++k) {
            for (std::size_t i = 0; i + k < values.size(); ++i) {
                values[i] = (1.0 - x) * values[i] + x * values[i + 1];
            }
        }
        return values.front();
    };
    std::vector<double> rows(a.m + 1);
    std::vector<double> line(a.n + 1);
    for (int i = 0; i <= a.m; ++i) {
        for (int j = 0; j <= a.n; ++j) {
            line[j] = a.value[a.index(i, j)];
        }
        rows[i] = reduce(line, t);
    }
    return reduce(rows, s);
}

// Where a polynomial of one variable over [0, 1], in the Bernstein basis, can be zero: its roots
// to 1e-7, or its ends and middle when it is zero all along (within its rounding)
std::vector<double> bernsteinRoots(const std::vector<double>& value, const std::vector<double>& bound)
{
    auto oneSignAlong = [](const std::vector<double>& values, const std::vector<double>& bounds) {
        bool positive = true;
        bool negative = true;
        for (std::size_t k = 0; k < values.size(); ++k) {
            positive = positive && values[k] > 1e-10 * bounds[k];
            negative = negative && values[k] < -1e-10 * bounds[k];
        }
        return positive || negative;
    };
    bool zero = true;
    for (std::size_t k = 0; k < value.size(); ++k) {
        zero = zero && std::abs(value[k]) <= 1e-10 * bound[k];
    }
    if (zero) {
        return {0.0, 0.5, 1.0};
    }
    struct Piece
    {
        std::vector<double> value;
        std::vector<double> bound;
        double low;
        double high;
    };
    std::vector<double> roots;
    std::vector<Piece> stack {{value, bound, 0.0, 1.0}};
    constexpr double precision = 1e-7;
    while (!stack.empty()) {
        Piece piece = std::move(stack.back());
        stack.pop_back();
        if (oneSignAlong(piece.value, piece.bound)) {
            continue;
        }
        if (piece.high - piece.low < precision) {
            const double middle = (piece.low + piece.high) / 2.0;
            if (roots.empty() || middle - roots.back() > 2.0 * precision) {
                roots.push_back(middle);
            }
            continue;
        }
        const std::size_t degree = piece.value.size() - 1;
        Piece left {piece.value, piece.bound, piece.low, (piece.low + piece.high) / 2.0};
        Piece right {piece.value, piece.bound, left.high, piece.high};
        std::vector<double> values = piece.value;
        std::vector<double> bounds = piece.bound;
        for (std::size_t step = 0; step <= degree; ++step) {
            left.value[step] = values[0];
            left.bound[step] = bounds[0];
            right.value[degree - step] = values[degree - step];
            right.bound[degree - step] = bounds[degree - step];
            for (std::size_t k = 0; k + step < degree; ++k) {
                values[k] = (values[k] + values[k + 1]) / 2.0;
                bounds[k] = (bounds[k] + bounds[k + 1]) / 2.0;
            }
        }
        stack.push_back(std::move(right));
        stack.push_back(std::move(left));
    }
    return roots;
}

std::pair<SilhouettePatch, SilhouettePatch> halves(const SilhouettePatch& patch, bool alongU)
{
    auto [gLow, gHigh] = halves(patch.g, alongU);
    auto [wLow, wHigh] = halves(patch.weights, alongU);
    SilhouettePatch first {std::move(gLow), {}, std::move(wLow)};
    SilhouettePatch second {std::move(gHigh), {}, std::move(wHigh)};
    for (int k = 0; k < 3; ++k) {
        auto [netLow, netHigh] = halves(patch.net[k], alongU);
        first.net[k] = std::move(netLow);
        second.net[k] = std::move(netHigh);
    }
    return {std::move(first), std::move(second)};
}

SilhouetteSurface silhouetteSurface(const TopoDS_Face& face)
{
    auto tooComplex = []() {
        return Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Could not revolve up to the face: it is too complex to check within the profile's turn"
        ));
    };
    auto checkFailed = []() {
        return Base::RuntimeError(
            QT_TRANSLATE_NOOP("Exception", "Could not check the revolution up to the face")
        );
    };
    const GeomAbs_SurfaceType kind = BRepAdaptor_Surface(face).GetType();
    if (kind == GeomAbs_OffsetSurface || kind == GeomAbs_OtherSurface) {
        throw Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Could not revolve up to the face: its kind of surface (an offset surface, as a "
            "Thickness leaves) can't be checked"
        ));
    }
    Handle(Geom_BSplineSurface) surface;
    TopoDS_Face nurbs;
    try {
        BRepBuilderAPI_NurbsConvert convert(face, Standard_True);
        TopExp_Explorer converted(convert.Shape(), TopAbs_FACE);
        if (converted.More()) {
            nurbs = TopoDS::Face(converted.Current());
            surface = Handle(Geom_BSplineSurface)::DownCast(BRep_Tool::Surface(nurbs));
        }
    }
    catch (const Standard_Failure&) {
        surface.Nullify();
    }
    SilhouetteSurface result;
    try {
        Standard_Real uLow = 0.0;
        Standard_Real uHigh = 0.0;
        Standard_Real vLow = 0.0;
        Standard_Real vHigh = 0.0;
        if (surface.IsNull()) {
            // The face's surface alone, trimmed to the face's range, is all the check needs. The
            // face's conversion failed on a whole torus face whose minor range is [-pi, pi]
            // ("Knots interval values too close"; Part.makeTorus from -180 to 180 degrees), and
            // every Revolution up to it failed as unchecked (ops#293, q4).
            BRepTools::UVBounds(face, uLow, uHigh, vLow, vHigh);
            surface = GeomConvert::SurfaceToBSplineSurface(new Geom_RectangularTrimmedSurface(
                BRep_Tool::Surface(face),
                uLow,
                uHigh,
                vLow,
                vHigh
            ));
            if (surface.IsNull()) {
                throw checkFailed();
            }
            // The conversion's parameters aren't the face's (a circle's rational parameter isn't
            // its angle): points are found on the face by projection
            result.carrier = face;
            result.sameParameters = false;
        }
        else {
            surface = Handle(Geom_BSplineSurface)::DownCast(surface->Copy());
            // Only the face's range: a whole cylinder or torus for a part of it costs patches
            BRepTools::UVBounds(nurbs, uLow, uHigh, vLow, vHigh);
            Standard_Real uFirst = 0.0;
            Standard_Real uLast = 0.0;
            Standard_Real vFirst = 0.0;
            Standard_Real vLast = 0.0;
            surface->Bounds(uFirst, uLast, vFirst, vLast);
            if (!surface->IsUPeriodic()) {
                uLow = std::max(uLow, uFirst);
                uHigh = std::min(uHigh, uLast);
            }
            if (!surface->IsVPeriodic()) {
                vLow = std::max(vLow, vFirst);
                vHigh = std::min(vHigh, vLast);
            }
            if (uHigh - uLow > Precision::PConfusion()
                && vHigh - vLow > Precision::PConfusion()) {
                surface->Segment(uLow, uHigh, vLow, vHigh);
            }
            result.carrier = nurbs;
            result.sameParameters = true;
        }
        if (surface->IsUPeriodic()) {
            surface->SetUNotPeriodic();
        }
        if (surface->IsVPeriodic()) {
            surface->SetVNotPeriodic();
        }
    }
    catch (const Standard_Failure&) {
        throw checkFailed();
    }
    if (5 * std::max(surface->UDegree(), surface->VDegree()) > largestSilhouetteDegree) {
        throw tooComplex();
    }
    result.surface = surface;
    return result;
}

namespace
{

Base::RuntimeError untraceable(const std::string& why)
{
    return Base::RuntimeError("Could not trace where first contact jumps: " + why);
}

// Phi in the frame: a point's radius from the axis and height along it, and its derivatives
struct Phi
{
    gp_XYZ center;
    gp_XYZ axis;
    gp_XYZ radial;
    gp_XYZ normal;

    gp_Pnt2d operator()(const gp_XYZ& point) const
    {
        const gp_XYZ offset = point - center;
        const double height = offset.Dot(axis);
        return {(offset - axis * height).Modulus(), height};
    }
    // The point of the frame's plane, on the profile's side of the axis, at (radius, height)
    gp_Pnt point(const gp_Pnt2d& image) const
    {
        return gp_Pnt(center + radial * image.X() + axis * image.Y());
    }
    // The unit vector away from the axis at a point, or a null vector on the axis
    gp_XYZ away(const gp_XYZ& point) const
    {
        const gp_XYZ offset = point - center;
        const gp_XYZ perpendicular = offset - axis * offset.Dot(axis);
        const double radius = perpendicular.Modulus();
        return radius > 0.0 ? perpendicular / radius : gp_XYZ();
    }
    // DPhi(v) at a point: (v . e_r, v . a)
    gp_Vec2d first(const gp_XYZ& point, const gp_XYZ& vector) const
    {
        return {vector.Dot(away(point)), vector.Dot(axis)};
    }
    // The second-order term of Phi(S(uv + e w)), times 2 / e^2: DPhi(S_ww) + D^2 Phi(S_w, S_w),
    // where D^2 radius (v, v) = (v . t_c)^2 / radius, t_c = a x e_r, and the height is linear
    gp_Vec2d second(const gp_XYZ& point, const gp_XYZ& alongW, const gp_XYZ& alongWW) const
    {
        const gp_XYZ out = away(point);
        const gp_XYZ offset = point - center;
        const double radius = (offset - axis * offset.Dot(axis)).Modulus();
        const double turning = alongW.Dot(axis.Crossed(out));
        return {
            alongWW.Dot(out) + (radius > 0.0 ? turning * turning / radius : 0.0),
            alongWW.Dot(axis)
        };
    }
};

double cross(const gp_Vec2d& a, const gp_Vec2d& b)
{
    return a.X() * b.Y() - a.Y() * b.X();
}

int sign(double value, double scale)
{
    if (std::abs(value) <= 1e-12 * scale) {
        return 0;
    }
    return value > 0.0 ? 1 : -1;
}

// A point along a jump curve: its parameters on F (u, v for the silhouette; the edge's parameter
// in u for an edge) and its image
struct Sample
{
    double u = 0.0;
    double v = 0.0;
    gp_Pnt2d image;
};

// A stretch of one jump curve, traced: its samples in order, how to find a point between two of
// them, and on which side of its direction F's image lies at a point
struct Track
{
    JumpSource source = JumpSource::Edge;
    int edge = 0;
    std::vector<Sample> samples;
    std::function<Sample(const Sample&, const Sample&, double)> between;
    std::function<int(const Sample&, const Sample&, const Sample&)> sideAt;
    // For an edge in a half-plane through the axis: the edge turned into the frame, parametrized
    // like the edge
    Handle(Geom2d_Curve) exactCurve;
    // For an edge: the parameters where its curve is less than C2 (a section's approximation is
    // C1 at its knots), each one a sample's; the fit is split there
    std::vector<double> breaks;
};

// The profile in the frame: its image box, and whether an image point lies in it
class Profile
{
public:
    Profile(const TopoDS_Face& profile, const Phi& phi, const gp_Ax2& frame, double tolerance)
        : classifier(profile, tolerance)
        , plane(BRepAdaptor_Surface(profile).Plane())
        , phi(phi)
    {
        gp_Trsf toFrame;
        toFrame.SetTransformation(gp_Ax3(frame));
        const TopoDS_Shape local = BRepBuilderAPI_Transform(profile, toFrame, Standard_True).Shape();
        Bnd_Box box;
        BRepBndLib::AddOptimal(local, box, Standard_False, Standard_False);
        if (box.IsVoid()) {
            throw untraceable("the profile has no extent");
        }
        Standard_Real zLow = 0.0;
        Standard_Real zHigh = 0.0;
        box.Get(radiusLow, heightLow, zLow, radiusHigh, heightHigh, zHigh);
    }

    bool contains(const gp_Pnt2d& image)
    {
        Standard_Real u = 0.0;
        Standard_Real v = 0.0;
        ElSLib::Parameters(plane, phi.point(image), u, v);
        const TopAbs_State state = classifier.Perform(gp_Pnt2d(u, v));
        return state == TopAbs_IN || state == TopAbs_ON;
    }
    // The distance from the image box, enlarged by `margin`, or 0 within it
    double fromBox(const gp_Pnt2d& image, double margin) const
    {
        const double x = std::max({radiusLow - margin - image.X(), image.X() - radiusHigh - margin, 0.0});
        const double y = std::max({heightLow - margin - image.Y(), image.Y() - heightHigh - margin, 0.0});
        return std::hypot(x, y);
    }
    // Whether radii [nearest, farthest] at heights [low, high] can reach the box, enlarged
    bool reaches(double nearest, double farthest, double low, double high, double margin) const
    {
        return high >= heightLow - margin && low <= heightHigh + margin
            && farthest >= radiusLow - margin && nearest <= radiusHigh + margin;
    }

    Standard_Real radiusLow = 0.0;
    Standard_Real radiusHigh = 0.0;
    Standard_Real heightLow = 0.0;
    Standard_Real heightHigh = 0.0;

private:
    BRepTopAdaptor_FClass2d classifier;
    gp_Pln plane;
    Phi phi;
};

// g = (S_u x S_v) . (a x (S - c)) and its derivatives on the silhouette's surface
struct GValue
{
    double g = 0.0;
    double gu = 0.0;
    double gv = 0.0;
    gp_XYZ point;
    gp_XYZ alongU;
    gp_XYZ alongV;
    gp_XYZ alongUU;
    gp_XYZ alongUV;
    gp_XYZ alongVV;
};

GValue gValue(const Handle(Geom_BSplineSurface)& surface, const Phi& phi, double u, double v)
{
    gp_Pnt point;
    gp_Vec su;
    gp_Vec sv;
    gp_Vec suu;
    gp_Vec svv;
    gp_Vec suv;
    surface->D2(u, v, point, su, sv, suu, svv, suv);
    GValue value;
    value.point = point.XYZ();
    value.alongU = su.XYZ();
    value.alongV = sv.XYZ();
    value.alongUU = suu.XYZ();
    value.alongUV = suv.XYZ();
    value.alongVV = svv.XYZ();
    const gp_XYZ turning = phi.axis.Crossed(value.point - phi.center);
    const gp_XYZ normal = value.alongU.Crossed(value.alongV);
    value.g = normal.Dot(turning);
    value.gu = (value.alongUU.Crossed(value.alongV) + value.alongU.Crossed(value.alongUV)).Dot(turning)
        + normal.Dot(phi.axis.Crossed(value.alongU));
    value.gv = (value.alongUV.Crossed(value.alongV) + value.alongU.Crossed(value.alongVV)).Dot(turning)
        + normal.Dot(phi.axis.Crossed(value.alongV));
    return value;
}

// The point near (u, v) where g = 0, by Newton along g's gradient; (u, v) itself when Newton
// doesn't bring g down
std::pair<double, double> ontoSilhouette(
    const Handle(Geom_BSplineSurface)& surface,
    const Phi& phi,
    double u,
    double v,
    double reach
)
{
    const GValue start = gValue(surface, phi, u, v);
    double bestU = u;
    double bestV = v;
    double best = std::abs(start.g);
    GValue value = start;
    for (int step = 0; step < 8 && best > 0.0; ++step) {
        const double gradient = value.gu * value.gu + value.gv * value.gv;
        if (gradient <= 0.0) {
            break;
        }
        double du = -value.g * value.gu / gradient;
        double dv = -value.g * value.gv / gradient;
        const double length = std::hypot(du, dv);
        if (length > reach) {
            du *= reach / length;
            dv *= reach / length;
        }
        u += du;
        v += dv;
        value = gValue(surface, phi, u, v);
        if (std::abs(value.g) < best) {
            best = std::abs(value.g);
            bestU = u;
            bestV = v;
        }
        else {
            break;
        }
    }
    return {bestU, bestV};
}

// On which side of the silhouette's image F's image lies at a point of the silhouette, against
// the image's direction from `from` to `to`: Phi is stationary across the fold, so the side is
// that of the second-order term along w, the direction on F whose tangent is the circle's
// (both sheets of a fold map to one side)
int silhouetteSide(
    const Handle(Geom_BSplineSurface)& surface,
    const Phi& phi,
    const Sample& at,
    const Sample& from,
    const Sample& to
)
{
    const GValue value = gValue(surface, phi, at.u, at.v);
    // The silhouette's direction on F: across g's gradient, along the samples' order
    double du = -value.gv;
    double dv = value.gu;
    if (du * (to.u - from.u) + dv * (to.v - from.v) < 0.0) {
        du = -du;
        dv = -dv;
    }
    const gp_Vec2d tangent = phi.first(value.point, value.alongU * du + value.alongV * dv);
    // w: S_u w_u + S_v w_v closest to the circle's direction
    const gp_XYZ circle = phi.axis.Crossed(phi.away(value.point));
    const double uu = value.alongU.Dot(value.alongU);
    const double uv = value.alongU.Dot(value.alongV);
    const double vv = value.alongV.Dot(value.alongV);
    const double cu = value.alongU.Dot(circle);
    const double cv = value.alongV.Dot(circle);
    const double determinant = uu * vv - uv * uv;
    if (determinant <= 0.0) {
        return 0;
    }
    const double wu = (cu * vv - cv * uv) / determinant;
    const double wv = (cv * uu - cu * uv) / determinant;
    const gp_XYZ alongW = value.alongU * wu + value.alongV * wv;
    const gp_XYZ alongWW = value.alongUU * (wu * wu) + value.alongUV * (2.0 * wu * wv)
        + value.alongVV * (wv * wv);
    const gp_Vec2d offset = phi.second(value.point, alongW, alongWW);
    return sign(cross(tangent, offset), tangent.Magnitude() * offset.Magnitude());
}

// The angle at which the circle of the frame point `image` about the axis, turning from the
// profile's plane, first meets F; none when it doesn't
std::optional<double> firstContact(IntCurvesFace_Intersector& intersector, const Phi& phi, const gp_Pnt2d& image)
{
    if (image.X() <= 0.0) {
        return std::nullopt;
    }
    const gp_Ax2 plane(gp_Pnt(phi.center + phi.axis * image.Y()), gp_Dir(phi.axis), gp_Dir(phi.radial));
    Handle(Geom_Circle) circle = new Geom_Circle(gp_Circ(plane, image.X()));
    Handle(GeomAdaptor_Curve) adaptor = new GeomAdaptor_Curve(circle);
    intersector.Perform(adaptor, 1e-9, 2.0 * std::numbers::pi - 1e-9);
    if (!intersector.IsDone()) {
        throw untraceable("a circle's intersection with the face failed");
    }
    std::optional<double> first;
    for (int i = 1; i <= intersector.NbPnt(); ++i) {
        const double angle = intersector.WParameter(i);
        if (!first || angle < *first) {
            first = angle;
        }
    }
    return first;
}

// A curve through a run of samples, within `deviation` of the image at each sample and at the
// images halfway between them (`middles`), checked by projection within the neighbouring
// parameters; null when neither an approximation nor the interpolation fits, with `worst` the
// largest distance found
Handle(Geom2d_BSplineCurve) fitThrough(
    const std::vector<Sample>& samples,
    const std::vector<Sample>& middles,
    double deviation,
    double& worst
)
{
    const int n = static_cast<int>(samples.size());
    // Chord-length parameters
    std::vector<double> parameters(n, 0.0);
    for (int i = 1; i < n; ++i) {
        parameters[i] = parameters[i - 1] + samples[i].image.Distance(samples[i - 1].image);
    }
    if (n < 2 || parameters.back() <= 0.0) {
        return {};
    }
    auto within = [&](const Handle(Geom2d_Curve)& curve) {
        Geom2dAPI_ProjectPointOnCurve projection;
        auto distance = [&](const gp_Pnt2d& point, double low, double high) {
            projection.Init(point, curve, low, high);
            if (projection.NbPoints() == 0) {
                // At an end of the window: the nearer end
                return std::min(point.Distance(curve->Value(low)), point.Distance(curve->Value(high)));
            }
            return projection.LowerDistance();
        };
        for (int i = 0; i < n; ++i) {
            const double low = parameters[std::max(i - 1, 0)];
            const double high = parameters[std::min(i + 1, n - 1)];
            worst = std::max(worst, distance(samples[i].image, low, high));
            if (worst > deviation) {
                return false;
            }
        }
        for (int i = 0; i + 1 < n; ++i) {
            worst = std::max(worst, distance(middles[i].image, parameters[i], parameters[i + 1]));
            if (worst > deviation) {
                return false;
            }
        }
        return true;
    };
    try {
        TColgp_Array1OfPnt2d points(1, n);
        TColStd_Array1OfReal knots(1, n);
        for (int i = 0; i < n; ++i) {
            points(i + 1) = samples[i].image;
            knots(i + 1) = parameters[i];
        }
        worst = 0.0;
        Geom2dAPI_PointsToBSpline approximation(points, knots, 3, 8, GeomAbs_C2, deviation / 4.0);
        if (approximation.IsDone() && within(approximation.Curve())) {
            return approximation.Curve();
        }
        Handle(TColgp_HArray1OfPnt2d) through = new TColgp_HArray1OfPnt2d(1, n);
        Handle(TColStd_HArray1OfReal) at = new TColStd_HArray1OfReal(1, n);
        for (int i = 0; i < n; ++i) {
            through->SetValue(i + 1, samples[i].image);
            at->SetValue(i + 1, parameters[i]);
        }
        Geom2dAPI_Interpolate interpolation(through, at, Standard_False, Precision::Confusion() * 1e-3);
        interpolation.Perform();
        worst = 0.0;
        if (interpolation.IsDone() && within(interpolation.Curve())) {
            return interpolation.Curve();
        }
    }
    catch (const Standard_Failure&) {
    }
    return {};
}

// Fits a run of a track's samples into `curves`, in order: whole; where no curve fits it, in two
// halves; a short run with its samples doubled (an edge's own curve can bend between them), up to
// three times along any stretch. False when that fails.
bool fitRuns(
    const Track& track,
    const std::vector<Sample>& samples,
    const std::vector<Sample>& middles,
    double deviation,
    int doublings,
    std::vector<Handle(Geom2d_BSplineCurve)>& curves,
    double& worst
)
{
    double off = 0.0;
    if (Handle(Geom2d_BSplineCurve) curve = fitThrough(samples, middles, deviation, off); !curve.IsNull()) {
        curves.push_back(curve);
        return true;
    }
    worst = std::max(worst, off);
    constexpr std::size_t shortRun = 16;
    if (samples.size() > shortRun) {
        const std::size_t half = samples.size() / 2;
        return fitRuns(
                   track,
                   std::vector<Sample>(samples.begin(), samples.begin() + half + 1),
                   std::vector<Sample>(middles.begin(), middles.begin() + half),
                   deviation,
                   doublings,
                   curves,
                   worst
               )
            && fitRuns(
                   track,
                   std::vector<Sample>(samples.begin() + half, samples.end()),
                   std::vector<Sample>(middles.begin() + half, middles.end()),
                   deviation,
                   doublings,
                   curves,
                   worst
               );
    }
    if (doublings >= 3) {
        return false;
    }
    std::vector<Sample> doubled {samples.front()};
    std::vector<Sample> doubledMiddles;
    for (std::size_t i = 0; i + 1 < samples.size(); ++i) {
        doubledMiddles.push_back(track.between(doubled.back(), middles[i], 0.5));
        doubled.push_back(middles[i]);
        doubledMiddles.push_back(track.between(middles[i], samples[i + 1], 0.5));
        doubled.push_back(samples[i + 1]);
    }
    return fitRuns(track, doubled, doubledMiddles, deviation, doublings + 1, curves, worst);
}

// The track's pieces: split where its side flips, each fitted within `deviation`
std::vector<JumpPiece> piecesOf(Track& track, double deviation)
{
    std::vector<JumpPiece> pieces;
    // Samples that coincide (a chain's end found on F's boundary at a node) are dropped
    std::vector<Sample> samples;
    for (const Sample& sample : track.samples) {
        if (samples.empty() || samples.back().image.Distance(sample.image) > deviation * 1e-3) {
            samples.push_back(sample);
        }
    }
    if (samples.size() < 2) {
        return pieces;
    }
    const std::size_t count = samples.size() - 1;
    std::vector<Sample> middles(count);
    std::vector<int> sides(count);
    for (std::size_t j = 0; j < count; ++j) {
        middles[j] = track.between(samples[j], samples[j + 1], 0.5);
        sides[j] = track.sideAt(middles[j], samples[j], samples[j + 1]);
    }
    // A segment on the fence takes its neighbour's side
    for (std::size_t j = 1; j < count; ++j) {
        if (sides[j] == 0) {
            sides[j] = sides[j - 1];
        }
    }
    for (std::size_t j = count - 1; j-- > 0;) {
        if (sides[j] == 0) {
            sides[j] = sides[j + 1];
        }
    }
    if (sides.front() == 0) {
        throw untraceable("the side of the face's image along a curve can't be decided");
    }
    struct Stretch
    {
        std::vector<Sample> samples;
        std::vector<Sample> middles;
        int side = 0;
    };
    std::vector<Stretch> stretches;
    stretches.push_back({{samples.front()}, {}, sides.front()});
    // Whether the current stretch ends at samples[j], so that segment j is whole
    bool whole = true;
    for (std::size_t j = 0; j < count; ++j) {
        auto add = [&](const Sample& to, bool wholeSegment) {
            Stretch& current = stretches.back();
            current.middles.push_back(
                wholeSegment ? middles[j] : track.between(current.samples.back(), to, 0.5)
            );
            current.samples.push_back(to);
        };
        if (j + 1 == count || sides[j + 1] == sides[j]) {
            add(samples[j + 1], whole);
            whole = true;
            continue;
        }
        // The side flips between the two segments' middles: bisection on s, from the middle of
        // segment j (0) through sample j + 1 (0.5) to the middle of segment j + 1 (1)
        auto along = [&](double s) {
            return s <= 0.5 ? track.between(middles[j], samples[j + 1], 2.0 * s)
                            : track.between(samples[j + 1], middles[j + 1], 2.0 * s - 1.0);
        };
        double low = 0.0;
        double high = 1.0;
        for (int step = 0; step < 60; ++step) {
            if (along(low).image.Distance(along(high).image) <= deviation / 4.0) {
                break;
            }
            const double middle = (low + high) / 2.0;
            const Sample& from = middle <= 0.5 ? samples[j] : samples[j + 1];
            const Sample& to = middle <= 0.5 ? samples[j + 1] : samples[j + 2];
            const int side = track.sideAt(along(middle), from, to);
            if (side == sides[j]) {
                low = middle;
            }
            else if (side == sides[j + 1]) {
                high = middle;
            }
            else {
                break;
            }
        }
        const double at = (low + high) / 2.0;
        const Sample flip = along(at);
        if (at > 0.5) {
            // In segment j + 1: this stretch takes sample j + 1, the next starts at the flip
            add(samples[j + 1], whole);
            add(flip, false);
            stretches.push_back({{flip}, {}, sides[j + 1]});
            whole = false;
        }
        else {
            // In segment j: the next stretch starts at the flip and takes sample j + 1
            add(flip, false);
            stretches.push_back({{flip}, {}, sides[j + 1]});
            add(samples[j + 1], false);
            whole = true;
        }
    }
    for (std::size_t k = 0; k < stretches.size(); ++k) {
        Stretch& stretch = stretches[k];
        if (stretch.samples.size() < 2) {
            continue;
        }
        JumpPiece piece;
        piece.source = track.source;
        piece.edge = track.edge;
        piece.side = stretch.side;
        piece.continuesPrevious = k > 0;
        for (const Sample& sample : stretch.samples) {
            piece.points.push_back(sample.image);
        }
        if (!track.exactCurve.IsNull()) {
            piece.curve = track.exactCurve;
            piece.first = stretch.samples.front().u;
            piece.last = stretch.samples.back().u;
            piece.exact = true;
            pieces.push_back(std::move(piece));
            continue;
        }
        // Fitted run by run: split where the edge's curve is less than C2 and every `longestRun`
        // samples, so that each fit stays small (one fit through the 7,000 samples of a section's
        // edge took most of a minute), then joined end to end
        constexpr std::size_t longestRun = 128;
        std::vector<Handle(Geom2d_BSplineCurve)> curves;
        double worst = 0.0;
        bool fitted = true;
        std::size_t begin = 0;
        const std::size_t n = stretch.samples.size();
        for (std::size_t i = 1; i < n && fitted; ++i) {
            const bool atBreak = std::ranges::binary_search(track.breaks, stretch.samples[i].u);
            if (i + 1 == n || atBreak || i - begin == longestRun) {
                fitted = fitRuns(
                    track,
                    std::vector<Sample>(stretch.samples.begin() + begin, stretch.samples.begin() + i + 1),
                    std::vector<Sample>(stretch.middles.begin() + begin, stretch.middles.begin() + i),
                    deviation,
                    0,
                    curves,
                    worst
                );
                begin = i;
            }
        }
        // The fits pass through their end samples, which neighbouring runs share
        Handle(Geom2d_BSplineCurve) curve;
        if (fitted && !curves.empty()) {
            Geom2dConvert_CompCurveToBSplineCurve joined(curves.front());
            for (std::size_t k = 1; k < curves.size() && fitted; ++k) {
                fitted = curves[k - 1]->EndPoint().Distance(curves[k]->StartPoint()) <= deviation * 1e-3
                    && joined.Add(curves[k], deviation * 1e-3, Standard_True);
            }
            if (fitted) {
                curve = joined.BSplineCurve();
            }
        }
        if (curve.IsNull()) {
            throw untraceable(
                std::string("no curve fits a jump within its deviation (")
                + (track.source == JumpSource::Edge ? "edge " + std::to_string(track.edge) : std::string("silhouette"))
                + ", " + std::to_string(n) + " points from (" + std::to_string(piece.points.front().X()) + ", "
                + std::to_string(piece.points.front().Y()) + ") to (" + std::to_string(piece.points.back().X())
                + ", " + std::to_string(piece.points.back().Y()) + "), off by " + std::to_string(worst) + ")"
            );
        }
        piece.curve = curve;
        piece.first = curve->FirstParameter();
        piece.last = curve->LastParameter();
        pieces.push_back(std::move(piece));
    }
    return pieces;
}

}  // namespace

JumpTrace traceJumps(
    const TopoDS_Face& face,
    const TopoDS_Face& profile,
    const gp_Ax1& axis,
    double tolerance,
    double deviation
)
{
    auto tooComplex = []() {
        return Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Could not revolve up to the face: it is too complex to check within the profile's turn"
        ));
    };
    // The frame: the profile's plane holds the axis, and the profile lies on one side of it
    BRepAdaptor_Surface profileSurface(profile);
    if (profileSurface.GetType() != GeomAbs_Plane) {
        throw untraceable("the profile isn't planar");
    }
    const gp_Pln profilePlane = profileSurface.Plane();
    const gp_Dir axisDirection = axis.Direction();
    if (std::abs(profilePlane.Axis().Direction().Dot(axisDirection)) > 1e-9
        || profilePlane.Distance(axis.Location()) > tolerance) {
        throw untraceable("the axis isn't in the profile's plane");
    }
    GProp_GProps properties;
    BRepGProp::SurfaceProperties(profile, properties);
    Phi phi;
    phi.center = axis.Location().XYZ();
    phi.axis = axisDirection.XYZ();
    phi.radial = phi.away(properties.CentreOfMass().XYZ());
    if (phi.radial.Modulus() < 0.5) {
        throw untraceable("the profile's centre lies on the axis");
    }
    phi.normal = phi.radial.Crossed(phi.axis);
    JumpTrace trace;
    trace.frame = gp_Ax2(axis.Location(), gp_Dir(phi.normal), gp_Dir(phi.radial));
    Profile inProfile(profile, phi, trace.frame, tolerance);
    if (inProfile.radiusLow < -tolerance) {
        throw untraceable("the profile crosses the axis");
    }
    const double size = std::hypot(
        inProfile.radiusHigh - inProfile.radiusLow,
        inProfile.heightHigh - inProfile.heightLow
    );
    const double fine = std::max(size / 1024.0, 2.0 * tolerance);
    // Curves are traced this far past the profile, so that they cross its boundary
    const double margin = size / 8.0;

    std::vector<Track> tracks;

    // The silhouette: the tree's leaves down to `fine`, joined leaf to leaf through the roots of g
    // on their sides
    const SilhouetteSurface silhouette = silhouetteSurface(face);
    const Handle(Geom_BSplineSurface)& surface = silhouette.surface;
    {
        struct Leaf
        {
            SilhouettePatch patch;
            double u0;
            double u1;
            double v0;
            double v1;
            int extra = 0;
        };
        GeomConvert_BSplineSurfaceToBezierSurface pieces(surface);
        TColGeom_Array2OfBezierSurface patches(1, pieces.NbUPatches(), 1, pieces.NbVPatches());
        pieces.Patches(patches);
        if (pieces.NbUPatches() != surface->NbUKnots() - 1 || pieces.NbVPatches() != surface->NbVKnots() - 1) {
            throw untraceable("the face's patches don't match its knots");
        }
        std::vector<Leaf> stack;
        for (int i = patches.LowerRow(); i <= patches.UpperRow(); ++i) {
            for (int j = patches.LowerCol(); j <= patches.UpperCol(); ++j) {
                stack.push_back(
                    {silhouettePatch(patches(i, j), axis),
                     surface->UKnot(i),
                     surface->UKnot(i + 1),
                     surface->VKnot(j),
                     surface->VKnot(j + 1),
                     0}
                );
            }
        }
        // The graph: nodes are roots of g on leaves' sides, shared by the leaves on both sides;
        // a leaf with two roots joins them
        struct Node
        {
            double u;
            double v;
            std::vector<int> edges;
        };
        struct Edge
        {
            int from;
            int to;
            double u0;
            double u1;
            double v0;
            double v1;
        };
        std::vector<Node> nodes;
        std::vector<Edge> edges;
        std::map<std::pair<double, double>, int> corners;
        struct OnSide
        {
            double free;
            double width;
            int node;
        };
        // Roots on a side, keyed by which parameter is fixed (0: u, 1: v) and its value: a side
        // shared by two leaves has the same fixed value in both, the split's own double
        std::map<std::pair<int, double>, std::vector<OnSide>> sides;
        auto nodeAt = [&](int fixedKind, double fixed, double free, double width) {
            std::vector<OnSide>& line = sides[{fixedKind, fixed}];
            for (const OnSide& entry : line) {
                if (std::abs(entry.free - free) <= 1e-6 * std::max(width, entry.width)) {
                    return entry.node;
                }
            }
            const int index = static_cast<int>(nodes.size());
            nodes.push_back(fixedKind == 0 ? Node {fixed, free, {}} : Node {free, fixed, {}});
            line.push_back({free, width, index});
            return index;
        };
        auto cornerAt = [&](double u, double v) {
            auto [it, added] = corners.try_emplace({u, v}, static_cast<int>(nodes.size()));
            if (added) {
                nodes.push_back({u, v, {}});
            }
            return it->second;
        };
        constexpr int budget = 200000;
        constexpr int extraLevels = 8;
        int visited = 0;
        while (!stack.empty()) {
            Leaf leaf = std::move(stack.back());
            stack.pop_back();
            if (++visited > budget) {
                throw tooComplex();
            }
            const SilhouettePatch& patch = leaf.patch;
            if (oneSign(patch.g)) {
                continue;
            }
            const int m = patch.weights.m;
            const int n = patch.weights.n;
            Bnd_Box box;
            double low = std::numeric_limits<double>::max();
            double high = std::numeric_limits<double>::lowest();
            double farthest = 0.0;
            double lengthU = 0.0;
            double lengthV = 0.0;
            auto pole = [&](int i, int j) {
                const int k = patch.weights.index(i, j);
                return gp_XYZ(patch.net[0].value[k], patch.net[1].value[k], patch.net[2].value[k])
                    / patch.weights.value[k];
            };
            for (int i = 0; i <= m; ++i) {
                double along = 0.0;
                for (int j = 0; j <= n; ++j) {
                    const gp_XYZ offset = pole(i, j);
                    box.Add(gp_Pnt(offset));
                    const gp_Pnt2d image = phi(offset + phi.center);
                    low = std::min(low, image.Y());
                    high = std::max(high, image.Y());
                    farthest = std::max(farthest, image.X());
                    if (j > 0) {
                        along += (offset - pole(i, j - 1)).Modulus();
                    }
                }
                lengthV = std::max(lengthV, along);
            }
            for (int j = 0; j <= n; ++j) {
                double along = 0.0;
                for (int i = 1; i <= m; ++i) {
                    along += (pole(i, j) - pole(i - 1, j)).Modulus();
                }
                lengthU = std::max(lengthU, along);
            }
            const double diagonal = std::sqrt(box.SquareExtent());
            const gp_XYZ middle = (box.CornerMin().XYZ() + box.CornerMax().XYZ()) / 2.0;
            const double nearest = std::max(0.0, phi(middle + phi.center).X() - diagonal / 2.0);
            if (!inProfile.reaches(nearest, farthest, low, high, margin + tolerance)) {
                continue;
            }
            auto split = [&]() {
                const bool alongU = lengthU >= lengthV;
                auto [first, second] = halves(patch, alongU);
                Leaf lowLeaf {std::move(first), leaf.u0, leaf.u1, leaf.v0, leaf.v1, leaf.extra};
                Leaf highLeaf {std::move(second), leaf.u0, leaf.u1, leaf.v0, leaf.v1, leaf.extra};
                if (alongU) {
                    const double at = (leaf.u0 + leaf.u1) / 2.0;
                    lowLeaf.u1 = at;
                    highLeaf.u0 = at;
                }
                else {
                    const double at = (leaf.v0 + leaf.v1) / 2.0;
                    lowLeaf.v1 = at;
                    highLeaf.v0 = at;
                }
                if (diagonal <= fine) {
                    ++lowLeaf.extra;
                    ++highLeaf.extra;
                }
                stack.push_back(std::move(highLeaf));
                stack.push_back(std::move(lowLeaf));
            };
            if (diagonal > fine) {
                split();
                continue;
            }
            // The roots of g on the leaf's sides: (kind of side, fixed value, free value, width)
            struct Root
            {
                int fixedKind;
                double fixed;
                double free;
                double width;
                bool corner;
                double u;
                double v;
            };
            std::vector<Root> roots;
            const Bernstein& g = patch.g;
            for (int side = 0; side < 4; ++side) {
                const bool alongV = side < 2;
                const int fixedIndex = side % 2 == 0 ? 0 : (alongV ? g.m : g.n);
                const int count = alongV ? g.n + 1 : g.m + 1;
                std::vector<double> value(count);
                std::vector<double> bound(count);
                for (int k = 0; k < count; ++k) {
                    const int index = alongV ? g.index(fixedIndex, k) : g.index(k, fixedIndex);
                    value[k] = g.value[index];
                    bound[k] = g.bound[index];
                }
                // Roots closer than 1e-3 of the side are one crossing: where g stays within its
                // rounding along a stretch of the side, the roots come every 2e-7 of it
                std::vector<double> crossings;
                std::vector<double> run;
                for (double root : bernsteinRoots(value, bound)) {
                    if (!run.empty() && root - run.back() > 1e-3) {
                        crossings.push_back((run.front() + run.back()) / 2.0);
                        run.clear();
                    }
                    run.push_back(root);
                }
                if (!run.empty()) {
                    crossings.push_back((run.front() + run.back()) / 2.0);
                }
                for (double root : crossings) {
                    Root entry {};
                    const bool atStart = root <= 1e-6;
                    const bool atEnd = root >= 1.0 - 1e-6;
                    entry.corner = atStart || atEnd;
                    if (alongV) {
                        entry.fixedKind = 0;
                        entry.fixed = side == 0 ? leaf.u0 : leaf.u1;
                        entry.width = leaf.v1 - leaf.v0;
                        entry.free = leaf.v0 + root * entry.width;
                        entry.u = entry.fixed;
                        entry.v = atStart ? leaf.v0 : (atEnd ? leaf.v1 : entry.free);
                    }
                    else {
                        entry.fixedKind = 1;
                        entry.fixed = side == 2 ? leaf.v0 : leaf.v1;
                        entry.width = leaf.u1 - leaf.u0;
                        entry.free = leaf.u0 + root * entry.width;
                        entry.v = entry.fixed;
                        entry.u = atStart ? leaf.u0 : (atEnd ? leaf.u1 : entry.free);
                    }
                    const bool seen = std::ranges::any_of(roots, [&](const Root& other) {
                        return entry.corner && other.corner && other.u == entry.u && other.v == entry.v;
                    });
                    if (!seen) {
                        roots.push_back(entry);
                    }
                }
            }
            if (roots.size() != 2) {
                if (leaf.extra < extraLevels) {
                    split();
                    continue;
                }
                // A branch, an isolated tangency, a loop smaller than a leaf, or g = 0 all along a
                // side (a coaxial patch): refused where it can reach the profile
                if (inProfile.reaches(nearest, farthest, low, high, tolerance)) {
                    const gp_Pnt2d image = phi(middle + phi.center);
                    throw untraceable(
                        "the face's silhouette has points that don't join into curves ("
                        + std::to_string(roots.size()) + " on a leaf's sides at u "
                        + std::to_string(leaf.u0) + ".." + std::to_string(leaf.u1) + ", v "
                        + std::to_string(leaf.v0) + ".." + std::to_string(leaf.v1) + ", radius "
                        + std::to_string(image.X()) + ", height " + std::to_string(image.Y()) + ")"
                    );
                }
                continue;
            }
            int ends[2];
            for (int k = 0; k < 2; ++k) {
                const Root& root = roots[k];
                ends[k] = root.corner ? cornerAt(root.u, root.v)
                                      : nodeAt(root.fixedKind, root.fixed, root.free, root.width);
            }
            if (ends[0] == ends[1]) {
                continue;
            }
            const int index = static_cast<int>(edges.size());
            edges.push_back({ends[0], ends[1], leaf.u0, leaf.u1, leaf.v0, leaf.v1});
            nodes[ends[0]].edges.push_back(index);
            nodes[ends[1]].edges.push_back(index);
        }

        // Newton onto g = 0 from each node, by at most half its smallest leaf
        for (Node& node : nodes) {
            double reach = std::numeric_limits<double>::max();
            for (int index : node.edges) {
                const Edge& edge = edges[index];
                reach = std::min({reach, (edge.u1 - edge.u0) / 2.0, (edge.v1 - edge.v0) / 2.0});
            }
            if (node.edges.empty()) {
                continue;
            }
            const auto [u, v] = ontoSilhouette(surface, phi, node.u, node.v, reach);
            node.u = u;
            node.v = v;
        }
        // Whether a point of the surface lies on F
        BRepTopAdaptor_FClass2d inFace(silhouette.carrier, Precision::PConfusion());
        auto onFace = [&](double u, double v) {
            if (silhouette.sameParameters) {
                const TopAbs_State state = inFace.Perform(gp_Pnt2d(u, v));
                return state == TopAbs_IN || state == TopAbs_ON;
            }
            BRepClass_FaceClassifier classifier(face, surface->Value(u, v), tolerance);
            return classifier.State() == TopAbs_IN || classifier.State() == TopAbs_ON;
        };
        auto sample = [&](double u, double v) {
            return Sample {u, v, phi(surface->Value(u, v).XYZ())};
        };
        // Walks: from each end (a node of degree 1, or of more than 2 outside the profile), then
        // the loops
        std::vector<bool> walked(edges.size(), false);
        auto degree = [&](int node) {
            return nodes[node].edges.size();
        };
        for (std::size_t k = 0; k < nodes.size(); ++k) {
            if (degree(static_cast<int>(k)) > 2) {
                const gp_Pnt2d image = sample(nodes[k].u, nodes[k].v).image;
                if (inProfile.fromBox(image, tolerance) <= 0.0) {
                    throw untraceable("the face's silhouette branches in the profile's way");
                }
            }
        }
        std::vector<std::vector<int>> chains;
        auto walk = [&](int start, int edge) {
            std::vector<int> chain {start};
            int at = start;
            while (edge >= 0 && !walked[edge]) {
                walked[edge] = true;
                const Edge& e = edges[edge];
                at = e.from == at ? e.to : e.from;
                chain.push_back(at);
                edge = -1;
                if (degree(at) == 2) {
                    for (int next : nodes[at].edges) {
                        if (!walked[next]) {
                            edge = next;
                        }
                    }
                }
            }
            chains.push_back(std::move(chain));
        };
        for (std::size_t k = 0; k < nodes.size(); ++k) {
            if (degree(static_cast<int>(k)) != 2) {
                for (int edge : nodes[k].edges) {
                    if (!walked[edge]) {
                        walk(static_cast<int>(k), edge);
                    }
                }
            }
        }
        for (std::size_t k = 0; k < edges.size(); ++k) {
            if (!walked[k]) {
                walk(edges[k].from, static_cast<int>(k));
            }
        }
        // Each chain clipped to F, as tracks
        auto between = [&surface, &phi](const Sample& a, const Sample& b, double lambda) {
            const double u = a.u + (b.u - a.u) * lambda;
            const double v = a.v + (b.v - a.v) * lambda;
            const double reach = std::max(std::hypot(b.u - a.u, b.v - a.v), 1e-12);
            const auto [onU, onV] = ontoSilhouette(surface, phi, u, v, reach);
            return Sample {onU, onV, phi(surface->Value(onU, onV).XYZ())};
        };
        auto sideAt = [&surface, &phi](const Sample& at, const Sample& from, const Sample& to) {
            return silhouetteSide(surface, phi, at, from, to);
        };
        for (const std::vector<int>& chain : chains) {
            std::vector<Sample> run;
            bool inside = false;
            auto flush = [&]() {
                if (run.size() >= 2) {
                    Track track;
                    track.source = JumpSource::Silhouette;
                    track.samples = std::move(run);
                    track.between = between;
                    track.sideAt = sideAt;
                    tracks.push_back(std::move(track));
                }
                run.clear();
            };
            for (std::size_t k = 0; k < chain.size(); ++k) {
                const Node& node = nodes[chain[k]];
                const Sample here = sample(node.u, node.v);
                const bool on = onFace(node.u, node.v);
                if (k > 0 && on != inside) {
                    // Where the chain crosses F's boundary, by bisection
                    Sample in = inside ? run.back() : here;
                    Sample out = inside ? here : sample(nodes[chain[k - 1]].u, nodes[chain[k - 1]].v);
                    for (int step = 0; step < 50 && in.image.Distance(out.image) > tolerance; ++step) {
                        const Sample middle = between(in, out, 0.5);
                        if (onFace(middle.u, middle.v)) {
                            in = middle;
                        }
                        else {
                            out = middle;
                        }
                    }
                    if (inside) {
                        run.push_back(in);
                        flush();
                    }
                    else {
                        run.push_back(in);
                    }
                }
                inside = on;
                if (on) {
                    run.push_back(here);
                }
            }
            flush();
        }
    }

    // F's edges: their images, sampled every `fine` near the profile
    {
        TopTools_IndexedMapOfShape edgeMap;
        TopExp::MapShapes(face, TopAbs_EDGE, edgeMap);
        const TopoDS_Face forward = TopoDS::Face(face.Oriented(TopAbs_FORWARD));
        BRepAdaptor_Surface faceSurface(forward);
        BRepTopAdaptor_FClass2d inFace(forward, Precision::PConfusion());
        for (TopExp_Explorer explorer(forward, TopAbs_EDGE); explorer.More(); explorer.Next()) {
            const TopoDS_Edge& edge = TopoDS::Edge(explorer.Current());
            if (BRep_Tool::Degenerated(edge) || BRep_Tool::IsClosed(edge, forward)) {
                continue;
            }
            const int index = edgeMap.FindIndex(edge);
            auto curve = std::make_shared<BRepAdaptor_Curve>(edge);
            const double first = curve->FirstParameter();
            const double last = curve->LastParameter();
            Standard_Real pFirst = 0.0;
            Standard_Real pLast = 0.0;
            Handle(Geom2d_Curve) onSurface = BRep_Tool::CurveOnSurface(edge, forward, pFirst, pLast);
            if (onSurface.IsNull()) {
                throw untraceable("an edge of the face has no curve on it");
            }
            const double length = GCPnts_AbscissaPoint::Length(*curve);
            const double coarse = size / 16.0;
            const int segments = std::max(8, static_cast<int>(std::ceil(length / coarse)));
            if (segments > 1000000) {
                throw tooComplex();
            }
            std::vector<double> parameters;
            GCPnts_UniformAbscissa uniform(*curve, segments + 1, first, last);
            if (uniform.IsDone() && uniform.NbPoints() == segments + 1) {
                for (int i = 1; i <= uniform.NbPoints(); ++i) {
                    parameters.push_back(uniform.Parameter(i));
                }
            }
            else {
                for (int i = 0; i <= segments; ++i) {
                    parameters.push_back(first + (last - first) * i / segments);
                }
            }
            // A sample at each place where the curve is less than C2, and the fit split there
            std::vector<double> breaks;
            if (const int intervals = curve->NbIntervals(GeomAbs_C2); intervals > 1) {
                TColStd_Array1OfReal bounds(1, intervals + 1);
                curve->Intervals(bounds, GeomAbs_C2);
                for (int i = 2; i <= intervals; ++i) {
                    if (bounds(i) > first && bounds(i) < last) {
                        breaks.push_back(bounds(i));
                    }
                }
                parameters.insert(parameters.end(), breaks.begin(), breaks.end());
                std::ranges::sort(parameters);
                parameters.erase(std::ranges::unique(parameters).begin(), parameters.end());
            }
            const double step = length / segments;
            // By value: the tracks outlive this loop's locals
            auto imageAt = [curve, &phi](double t) {
                return phi(curve->Value(t).XYZ());
            };
            // The material's side in F's parameters: on the left of the edge's curve on F when the
            // edge is forward in F; checked at the edge's middle
            double inward = edge.Orientation() == TopAbs_REVERSED ? -1.0 : 1.0;
            {
                const double t = (first + last) / 2.0;
                gp_Pnt2d uv;
                gp_Vec2d d;
                onSurface->D1(t, uv, d);
                for (double reach : {1e-6, 1e-4, 1e-2}) {
                    const gp_Vec2d left = gp_Vec2d(-d.Y(), d.X()).Normalized() * reach;
                    const TopAbs_State plus = inFace.Perform(gp_Pnt2d(uv.XY() + left.XY() * inward));
                    const TopAbs_State minus = inFace.Perform(gp_Pnt2d(uv.XY() - left.XY() * inward));
                    if (plus == TopAbs_OUT && minus == TopAbs_IN) {
                        inward = -inward;
                        break;
                    }
                    if (plus == TopAbs_IN && minus == TopAbs_OUT) {
                        break;
                    }
                }
            }
            auto sideAt = [curve, onSurface, faceSurface, inward, phi](const Sample& at, const Sample&, const Sample&) {
                const double t = at.u;
                gp_Pnt2d uv;
                gp_Vec2d d;
                onSurface->D1(t, uv, d);
                const gp_Vec2d w = gp_Vec2d(-d.Y(), d.X()) * inward;
                gp_Pnt point;
                gp_Vec su;
                gp_Vec sv;
                gp_Vec suu;
                gp_Vec svv;
                gp_Vec suv;
                faceSurface.D2(uv.X(), uv.Y(), point, su, sv, suu, svv, suv);
                gp_Pnt onEdge;
                gp_Vec tangent3d;
                curve->D1(t, onEdge, tangent3d);
                const gp_Vec2d tangent = phi.first(onEdge.XYZ(), tangent3d.XYZ());
                const gp_XYZ alongW = su.XYZ() * w.X() + sv.XYZ() * w.Y();
                const gp_Vec2d image = phi.first(point.XYZ(), alongW);
                const int first = sign(cross(tangent, image), tangent.Magnitude() * image.Magnitude());
                if (first != 0) {
                    return first;
                }
                const gp_XYZ alongWW = suu.XYZ() * (w.X() * w.X()) + suv.XYZ() * (2.0 * w.X() * w.Y())
                    + svv.XYZ() * (w.Y() * w.Y());
                const gp_Vec2d second = phi.second(point.XYZ(), alongW, alongWW);
                return sign(cross(tangent, second), tangent.Magnitude() * second.Magnitude());
            };
            auto between = [imageAt](const Sample& a, const Sample& b, double lambda) {
                const double t = a.u + (b.u - a.u) * lambda;
                return Sample {t, 0.0, imageAt(t)};
            };
            // Exact for an edge in a half-plane through the axis: the edge turned into the frame
            Handle(Geom2d_Curve) exact;
            {
                const gp_XYZ middle = curve->Value((first + last) / 2.0).XYZ();
                const gp_XYZ out = phi.away(middle);
                bool meridian = out.Modulus() > 0.5;
                const gp_XYZ across = phi.axis.Crossed(out);
                for (int i = 0; meridian && i <= 32; ++i) {
                    const gp_XYZ offset = curve->Value(first + (last - first) * i / 32).XYZ() - phi.center;
                    meridian = std::abs(offset.Dot(across)) <= 1e-12 * std::max(size, 1.0)
                        && offset.Dot(out) >= -1e-12 * std::max(size, 1.0);
                }
                if (meridian) {
                    Standard_Real cFirst = 0.0;
                    Standard_Real cLast = 0.0;
                    Handle(Geom_Curve) geometry = BRep_Tool::Curve(edge, cFirst, cLast);
                    if (!geometry.IsNull()) {
                        // Turned from its half-plane to the profile's about the axis
                        const double angle
                            = std::atan2(phi.radial.Crossed(out).Dot(phi.axis), phi.radial.Dot(out));
                        gp_Trsf turn;
                        turn.SetRotation(axis, -angle);
                        Handle(Geom_Curve) turned
                            = Handle(Geom_Curve)::DownCast(geometry->Transformed(turn));
                        exact = GeomAPI::To2d(turned, gp_Pln(gp_Ax3(trace.frame)));
                        // The curve's parameters are the edge's, and its points the edge's images
                        for (int i = 0; !exact.IsNull() && i <= 8; ++i) {
                            const double t = first + (last - first) * i / 8;
                            if (exact->Value(t).Distance(imageAt(t)) > 1e-9 * std::max(size, 1.0)) {
                                exact.Nullify();
                            }
                        }
                    }
                }
            }
            // Runs of segments near the profile, refined to `fine`
            std::vector<Sample> run;
            auto flush = [&]() {
                if (run.size() >= 2) {
                    Track track;
                    track.source = JumpSource::Edge;
                    track.edge = index;
                    track.samples = std::move(run);
                    track.between = between;
                    track.sideAt = sideAt;
                    track.exactCurve = exact;
                    track.breaks = breaks;
                    tracks.push_back(std::move(track));
                }
                run.clear();
            };
            std::function<void(double, double, const gp_Pnt2d&, const gp_Pnt2d&, int)> refine;
            refine = [&](double t0, double t1, const gp_Pnt2d& a, const gp_Pnt2d& b, int depth) {
                if (a.Distance(b) > fine && depth < 40) {
                    const double t = (t0 + t1) / 2.0;
                    const gp_Pnt2d middle = imageAt(t);
                    refine(t0, t, a, middle, depth + 1);
                    refine(t, t1, middle, b, depth + 1);
                    return;
                }
                run.push_back({t1, 0.0, b});
            };
            for (std::size_t i = 0; i + 1 < parameters.size(); ++i) {
                const gp_Pnt2d a = imageAt(parameters[i]);
                const gp_Pnt2d b = imageAt(parameters[i + 1]);
                // The segment's image lies within its length of its ends (Phi is 1-Lipschitz)
                const bool close = inProfile.fromBox(a, margin) <= step || inProfile.fromBox(b, margin) <= step;
                if (!close) {
                    flush();
                    continue;
                }
                if (run.empty()) {
                    run.push_back({parameters[i], 0.0, a});
                }
                refine(parameters[i], parameters[i + 1], a, b, 0);
            }
            flush();
        }
    }

    // The pieces, where they meet the profile and whether first contact jumps across them
    IntCurvesFace_Intersector intersector(face, Precision::Confusion());
    const double offset = 1e-3 * size;
    for (Track& track : tracks) {
        for (JumpPiece& piece : piecesOf(track, deviation)) {
            std::vector<std::size_t> inside;
            for (std::size_t k = 0; k < piece.points.size(); ++k) {
                if (inProfile.contains(piece.points[k])) {
                    inside.push_back(k);
                }
            }
            piece.meetsProfile = !inside.empty();
            constexpr std::size_t tests = 8;
            for (std::size_t t = 0; t < std::min(tests, inside.size()) && !piece.jumps; ++t) {
                const std::size_t k = inside[t * inside.size() / std::min(tests, inside.size())];
                const gp_Pnt2d& at = piece.points[k];
                const gp_Pnt2d& before = piece.points[k > 0 ? k - 1 : k];
                const gp_Pnt2d& after = piece.points[std::min(k + 1, piece.points.size() - 1)];
                gp_Vec2d direction(before, after);
                if (direction.Magnitude() <= 0.0) {
                    continue;
                }
                direction.Normalize();
                const gp_Vec2d left(-direction.Y(), direction.X());
                const std::optional<double> onLeft
                    = firstContact(intersector, phi, gp_Pnt2d(at.XY() + left.XY() * offset));
                const std::optional<double> onRight
                    = firstContact(intersector, phi, gp_Pnt2d(at.XY() - left.XY() * offset));
                piece.jumps = onLeft.has_value() != onRight.has_value()
                    || (onLeft && std::abs(*onLeft - *onRight) > 1e-2);
            }
            trace.pieces.push_back(std::move(piece));
        }
    }
    constexpr std::size_t largestPieces = 64;
    if (std::ranges::count_if(trace.pieces, [](const JumpPiece& piece) {
            return piece.meetsProfile && piece.jumps;
        }) > static_cast<std::ptrdiff_t>(largestPieces)) {
        throw tooComplex();
    }
    return trace;
}

}  // namespace PartDesign::FirstContact
