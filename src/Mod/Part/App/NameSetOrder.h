// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/

#pragma once

#include <string>
#include <vector>

#include <Mod/Part/PartGlobal.h>

namespace Data
{
class MappedName;
}

namespace Part
{

/** Orders a list field that holds a set of V2 names (Linked Names, Connected Names; ops#19).
 *
 * The names end up sorted by the bytes of their expansions, without duplicates. Plain names
 * are their own expansion, so they are sorted by bytes as before. Interned names (ops#6) are
 * compared through Data::NameTable::compareExpanded, so a list holds its names in the same
 * order whether they are interned or not, and an interned name expands to the plain one.
 */
PartExport void sortNameSet(std::vector<Data::MappedName>& names);
PartExport void sortNameSet(std::vector<std::string>& names);

}  // namespace Part
