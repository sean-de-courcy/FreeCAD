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

#include <functional>
#include <string>
#include <vector>

#include <Geom2d_BSplineCurve.hxx>
#include <gp_Ax1.hxx>
#include <gp_Pnt.hxx>
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

// C2, a sheet of the face lost in a cell's split (section 15.10): `piece` is the solid at the
// cell's start cap, `sections` the edges where the face cut the turn's faces, `faceParts` the
// face's pieces. Every section edge in the piece must bound a piece of the face there (the exit,
// or a flap), unless the face's material through it stays in a wall's band (`inBand`, of a point
// of the turn): from the edge's middle, both ways across it along the face in steps of `step`,
// until the face ends or the point maps out of the band. A point out of the band strictly inside
// the piece is the lost sheet. Returns why it refuses, or an empty string.
PartDesignExport std::string lostSheet(
    const TopoDS_Shape& piece,
    const TopoDS_Face& face,
    const TopTools_IndexedMapOfShape& sections,
    const TopTools_IndexedMapOfShape& faceParts,
    const std::function<bool(const gp_Pnt&)>& inBand,
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
