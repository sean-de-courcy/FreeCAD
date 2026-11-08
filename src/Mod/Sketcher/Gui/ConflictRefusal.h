// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                            *
 *                                                                         *
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

namespace Sketcher
{
class Constraint;
}

namespace SketcherGui
{

class ViewProviderSketch;

/** FreeCAD-CH (ops#640, rank 45): a conflicting constraint is refused, not solved by collapsing
 * geometry and called "Redundant" (gap S9). Under Onshape's keymap, in the sketch editor, a
 * geometric constraint added on its own (a constraint command's one addConstraint) whose solve
 * conflicts with it, or shrinks a line or an arc to nothing that had a size, is undone with its
 * command (one undo step, so a model pick's link goes with it) and an error says why. Dimensions
 * are left alone: one that would overdefine the sketch is made driven (EditDatumDialog), and
 * redundant constraints are kept (rank 51 colours them). [guess: Onshape's exact reaction to a
 * conflicting constraint is hands-on G13; its help shows the conflict red]
 */

/// ViewProviderSketch::slotConstraintAdded: notes the sketch as it was before the addition
void noteConstraintAdded(ViewProviderSketch& viewProvider, const Sketcher::Constraint& constraint);

/// ViewProviderSketch::slotSolverUpdate, before the solver information is shown: the check
void checkAddedConstraint(ViewProviderSketch& viewProvider);

/// the edit ends: nothing pending for this view provider
void forgetAddedConstraint(const ViewProviderSketch& viewProvider);

}  // namespace SketcherGui
