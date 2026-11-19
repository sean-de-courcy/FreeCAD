// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2024 Eric Price (CorvusCorax)                           *
 *                      <eric.price[at]tuebingen.mpg.de>                   *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#pragma once

#include <Mod/Part/PartGlobal.h>
#include <functional>

namespace Part
{

/**
 * @brief The FuzzyHelper provides helper functions to determine fuzzy value for a boolean operation
 */
namespace FuzzyHelper
{
double PartExport getBooleanFuzzy();
void PartExport setBooleanFuzzy(double base);
void PartExport withBooleanFuzzy(double base, std::function<void()> func);
/**
 * FreeCAD-CH ops#901: while \a func runs (process-wide, not per thread: the Boolean runs on
 * KernelBudget's worker), the fork's Booleans
 * (FCBRepAlgoAPI_BooleanOperation::Build) re-intersect the face pairs for which OCCT 8.0.1's
 * face/face step found nothing, on the part of each face where they can meet, and give the
 * crossings found to the same Boolean. Off otherwise. FREECAD_CH_CROSSING_RECOVERY = "on" turns it
 * on for every Boolean (tests only)
 */
bool PartExport getCrossingRecovery();
void PartExport withCrossingRecovery(const std::function<void()>& func);
}  // namespace FuzzyHelper

}  // namespace Part
