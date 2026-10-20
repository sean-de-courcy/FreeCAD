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

#pragma once

#include <array>
#include <vector>

#include <Geom2d_Curve.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_BSplineSurface.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pnt2d.hxx>
#include <TopoDS_Face.hxx>

#include <Mod/PartDesign/PartDesignGlobal.h>

// Where first contact jumps for a Revolution or Groove up to a face (ops#293 D2;
// notes\revolution-upto-first-contact.md, section 15). A point x of the profile P first meets the
// up-to face F, turning about the axis, at an angle that jumps across two kinds of curve in P's
// plane: the images under Phi (x -> its radius from the axis and its height along it) of F's
// edges, and of F's silhouette under the rotation, where circles about the axis touch F (g = 0,
// g = n . (a x (S - c))). The construction (section 15.1) splits P along them; this file finds
// them. Both kinds are planar curves in P's half-plane: Rev(curve) = Rev(Phi(curve)).
namespace PartDesign::FirstContact
{

// The largest degree a silhouette polynomial takes: 5 p - 1 for a rational patch of degree p
constexpr int largestSilhouetteDegree = 64;

double binomial(int n, int k);

// A polynomial over [0, 1]^2 in the tensor Bernstein basis of degree (m, n), with each coefficient
// a bound on the absolute values summed into it: its rounding is a small multiple of that bound,
// however much the sum cancels.
struct Bernstein
{
    int m = 0;
    int n = 0;
    std::vector<double> value;
    std::vector<double> bound;

    Bernstein() = default;
    Bernstein(int uDegree, int vDegree)
        : m(uDegree)
        , n(vDegree)
        , value((uDegree + 1) * (vDegree + 1), 0.0)
        , bound((uDegree + 1) * (vDegree + 1), 0.0)
    {}
    int index(int i, int j) const
    {
        return i * (n + 1) + j;
    }
};

Bernstein product(const Bernstein& a, const Bernstein& b);
// a + sign b, of the same degree (every sum in the silhouette's polynomial is)
Bernstein sum(const Bernstein& a, const Bernstein& b, double sign = 1.0);
Bernstein scaled(const Bernstein& a, double factor);
Bernstein derivative(const Bernstein& a, bool alongU);
// The two halves of a polynomial split at the middle of u or v (de Casteljau)
std::pair<Bernstein, Bernstein> halves(const Bernstein& a, bool alongU);
// Whether a polynomial has one sign over its whole patch: every coefficient is of that sign by more
// than its rounding (the convex hull property)
bool oneSign(const Bernstein& a);
// The value of a polynomial at (s, t) (de Casteljau)
double valueAt(const Bernstein& a, double s, double t);
// Where a polynomial of one variable over [0, 1], in the Bernstein basis, can be zero: its roots
// to 1e-7, or its ends and middle when it is zero all along (within its rounding)
std::vector<double> bernsteinRoots(const std::vector<double>& value, const std::vector<double>& bound);

// A patch of the up-to face's surface (a rational Bezier patch, its poles taken about the axis
// location and weighted), and the polynomial G whose sign is that of g = n . (a x (S - c)), the
// face's normal against the circle's direction: G = ((N_u W - N W_u) x (N_v W - N W_v)) . (a x N)
// for S - c = N / W, or (N_u x N_v) . (a x N) when the weights are all one.
struct SilhouettePatch
{
    Bernstein g;
    std::array<Bernstein, 3> net;
    Bernstein weights;
};

SilhouettePatch silhouettePatch(const Handle(Geom_BezierSurface)& bezier, const gp_Ax1& axis);
// The two halves of a patch split at the middle of u or v
std::pair<SilhouettePatch, SilhouettePatch> halves(const SilhouettePatch& patch, bool alongU);

// The up-to face's surface as one B-spline over the face's range, the silhouette's carrier, and
// the face it bounds: the face converted to NURBS, whose parameters are the surface's
// (`sameParameters`), or, when the conversion fails, the face itself
struct SilhouetteSurface
{
    Handle(Geom_BSplineSurface) surface;
    TopoDS_Face carrier;
    bool sameParameters = true;
};

// Throws, saying why, for a surface the silhouette can't be computed on (an offset surface, a
// degree above largestSilhouetteDegree / 5, a conversion that fails)
SilhouetteSurface silhouetteSurface(const TopoDS_Face& face);

// Where a jump curve comes from
enum class JumpSource
{
    Edge,
    Silhouette
};

// A piece of a jump curve: the image under Phi of a stretch of F's edge or silhouette, along which
// F's image lies on one side. Points are in `frame` coordinates (JumpTrace): x the radius from the
// axis, y the height along it.
struct PartDesignExport JumpPiece
{
    JumpSource source = JumpSource::Edge;
    // For an edge, its index in TopExp::MapShapes(face, TopAbs_EDGE), from 1
    int edge = 0;
    // Images of points of the edge or of the silhouette (on g = 0 by Newton), in order
    std::vector<gp_Pnt2d> points;
    // +1 when F's image lies on the left of the points' direction next to the piece, -1 on the
    // right: the side whose circles meet that part of F, so the side of the earlier first contact
    // wherever the piece is a jump
    int side = 0;
    // A curve through the points, within the trace's deviation of the image everywhere along it
    // (checked between the points as well): for an edge in a half-plane through the axis, that
    // edge turned into the frame, exactly
    Handle(Geom2d_Curve) curve;
    double first = 0.0;
    double last = 0.0;
    bool exact = false;
    // Whether the piece goes on from the previous one: the curve was split where its side flips
    // (where F's edge crosses the silhouette, or at a cusp of the silhouette's image)
    bool continuesPrevious = false;
    // Whether part of the piece lies in the profile
    bool meetsProfile = false;
    // Whether first contact jumps across it somewhere in the profile (compared on both sides at up
    // to eight of its points in the profile, size / 1000 off it). False for a curve behind an
    // earlier part of F, which the construction doesn't need.
    bool jumps = false;
};

struct PartDesignExport JumpTrace
{
    // On the axis, normal to the profile's plane, x towards the profile: frame coordinates (x, y)
    // are the radius from the axis and the height along it of the profile's points
    gp_Ax2 frame;
    std::vector<JumpPiece> pieces;
};

// The pieces of the images of F's edges and silhouette that come near the profile (planar, in a
// plane through the axis, on one side of it). `tolerance` is that of the checks
// (profileCheckTolerance()); `deviation` bounds the fit's distance from the images. Throws
// Base::RuntimeError, saying why, where the curves can't be traced: silhouette points that don't
// join into curves in the profile (a branch, an isolated tangency, a coaxial patch where g = 0
// on an area), a fit beyond its deviation, a face too complex.
PartDesignExport JumpTrace traceJumps(
    const TopoDS_Face& face,
    const TopoDS_Face& profile,
    const gp_Ax1& axis,
    double tolerance,
    double deviation
);

}  // namespace PartDesign::FirstContact
