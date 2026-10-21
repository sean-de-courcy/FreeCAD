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

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <Geom2d_BSplineCurve.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include <Mod/PartDesign/PartDesignGlobal.h>

#include "FirstContactJumps.h"

// The solid of a Revolution or Groove up to a face where first contact jumps inside the profile
// (ops#293 D2; notes\revolution-upto-first-contact.md, sections 15.1, 15.2 and 15.8). The profile is
// split along the jump curves (traceJumps()), each curve pushed a little to the side of the earlier
// first contact; each cell is swept up to the face on its own, where first contact doesn't jump,
// and the pieces are fused. Each cell's piece and the fuse are checked; a wall whose cells refuse
// is pushed farther, twice at most.
namespace PartDesign::FirstContact
{

// The first push, absolute: ten times Precision::Confusion(). Nearer than about 3e-7 to the jump,
// OCCT can't tell on which side of the wall the face lies (section 15.2).
constexpr double firstPush = 1e-6;

// A jump curve as the construction places it: pushed `push` towards the earlier first contact, in
// the trace's frame
struct PartDesignExport Wall
{
    // The index of the piece in the trace
    std::size_t piece = 0;
    double push = 0.0;
    Handle(Geom2d_BSplineCurve) curve;
};

// A piece of the trace as a wall: its curve moved `push` along its normal towards its side, within a
// tenth of `push`. Throws Base::RuntimeError where that fails.
PartDesignExport Wall pushedWall(const JumpTrace& trace, std::size_t piece, double push);

// The bands of the walls on a cell's boundary (section 15.8): the points of the turn whose image
// in the frame's half-plane (x the distance from the axis, y the height along it) lies within a
// part's width of one of the parts' curves. A wall's parts are its pushed curve, its connectors
// and its carried ends, each with twice the wall's push.
class PartDesignExport Band
{
public:
    // `frame` as JumpTrace's: the axis through its location along its y direction
    explicit Band(const gp_Ax2& frame);

    // A bounded curve in frame coordinates. Throws Base::RuntimeError where its net can't bound
    // its second derivative.
    void add(const Handle(Geom2d_Curve)& curve, double width);

    // The point's image within the band, pointwise
    bool contains(const gp_Pnt& point) const;

    // Nothing when the edge's image, widened by the edge's tolerance, is certified within the band:
    // between two samples t0, t1 whose images lie within d0, d1 of points W(u0), W(u1) of one part,
    // the image stays within max(d0, d1) + (|S''| dt^2 + |W''| du^2) / 8 of that part, with
    // |S''| <= |c''| + |c'|^2 / radius and the derivatives bounded from the B-spline nets (the
    // convex hull property). Intervals that don't hold are halved, to a floor. Otherwise the first
    // point found out of the band, or where it couldn't be certified.
    std::optional<gp_Pnt> outside(const TopoDS_Edge& edge) const;
    // The same with `tolerance` for the edge's (a piece of an edge cut by a boolean keeps its
    // curve, but its tolerance grows with its new vertices')
    std::optional<gp_Pnt> outside(const TopoDS_Edge& edge, double tolerance) const;

    // Nothing when the face's image, widened by its tolerance, is certified within the band
    // (section 15.8, 2b). The band is simply connected, so the image is in it when the images of
    // the face's edges and of its silhouette (where circles about the axis touch it) are: the edges
    // by the curve bound, the silhouette by the leaves of a tree over the face's surface that hold
    // g = 0 and reach the face. Over a leaf, with S bilinearly interpolated between the corners'
    // nearest points of one part, the image stays within the corners' largest distance plus
    // (|(Phi S)_ss| + |W''| du_s^2 + |(Phi S)_tt| + |W''| du_t^2) / 8, where |(Phi S)_ss| <=
    // |S_ss| + |S_s|^2 / radius, bounded from the leaf's net. Leaves that don't hold are halved,
    // to a floor and a budget. Otherwise a point of the face out of the band, or where it couldn't
    // be certified.
    std::optional<gp_Pnt> outside(const TopoDS_Face& face) const;

    // C4 and C5 with the exemption: nothing when every point of the face (a part on a piece's
    // boundary, oriented as there) where the circles about the axis meet it from behind or touch it
    // (g <= 0 against its outward normal) is certified within the band, by the same leaves: those
    // where g changes sign or is of the wrong sign. A fold's silhouette lies in the exit face near
    // its edge on the wall, and the face beyond it turns back, all within the band. Otherwise a
    // point out of the band, or where it couldn't be certified.
    std::optional<gp_Pnt> behind(const TopoDS_Face& face) const;

private:
    // A span of a part's curve between two knots, and the box of its poles, which holds it (the
    // convex hull property)
    struct Span
    {
        double first = 0.0;
        double last = 0.0;
        double xLow = 0.0;
        double xHigh = 0.0;
        double yLow = 0.0;
        double yHigh = 0.0;
    };
    struct Part
    {
        Handle(Geom2d_BSplineCurve) curve;
        double width = 0.0;
        // A bound of |W''| over the curve
        double bend = 0.0;
        std::vector<Span> spans;
        // The box of all the spans
        Span box;
    };
    gp_Ax2 frame;
    std::vector<Part> parts;

    gp_Pnt2d image(const gp_Pnt& point) const;
    // The parameter of the part's nearest point to `point`, and the distance; or, where the point
    // is farther than the part's width from every span's box, NaN and a lower bound of the
    // distance (more than the width, so the part holds nothing near the point)
    static std::pair<double, double> nearest(const Part& part, const gp_Pnt2d& point);
    // `whole`: the silhouette's leaves, and any point of the face found out of the band ends the
    // check; otherwise behind()'s leaves
    std::optional<gp_Pnt> leavesOutside(const TopoDS_Face& face, bool whole) const;
};

// C2, a sheet of the face lost in a cell's split (section 15.10): `piece` is the solid at the
// cell's start cap, `sections` the edges where the face cut the turn's faces, `faceParts` the
// face's pieces. Every section edge in the piece must bound a piece of the face there (the exit,
// or a flap), unless the face's material through it stays in a wall's band: the edge certified in
// the band (Band::outside()), and from the edge's middle, both ways across it along the face in
// steps of `step`, until the face ends or the point maps out of the band. A point out of the band
// strictly inside the piece is the lost sheet. Returns why it refuses, or an empty string.
PartDesignExport std::string lostSheet(
    const TopoDS_Shape& piece,
    const TopoDS_Face& face,
    const TopTools_IndexedMapOfShape& sections,
    const TopTools_IndexedMapOfShape& faceParts,
    const Band& band,
    double step,
    double tolerance
);

struct PartDesignExport FirstContactSolid
{
    TopoDS_Shape shape;
    JumpTrace trace;
    std::vector<Wall> walls;
    // The profile's cells between the walls, in the profile's place
    std::vector<TopoDS_Face> cells;
    // Each cell's piece: its turn up to the face, before the fuse
    std::vector<TopoDS_Shape> pieces;
    // How many times the construction was built: 1, or 2 or 3 when walls were pushed farther
    int builds = 0;
};

// The tool up to `face` where first contact jumps inside `profile`: what each of its points sweeps,
// turning about `axis`, until it first meets the face, within the walls' pushes. `tolerance` is that
// of the checks (profileCheckTolerance()). Throws Base::RuntimeError, saying why, where the jumps
// can't be traced or the construction doesn't check.
PartDesignExport FirstContactSolid constructFirstContact(
    const TopoDS_Face& face,
    const TopoDS_Face& profile,
    const gp_Ax1& axis,
    double tolerance
);

}  // namespace PartDesign::FirstContact
