// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
 *                                                                          *
 *   This file is part of the FreeCAD CAx development system.               *
 *                                                                          *
 *   This library is free software; you can redistribute it and/or          *
 *   modify it under the terms of the GNU Library General Public            *
 *   License as published by the Free Software Foundation; either           *
 *   version 2 of the License, or (at your option) any later version.       *
 *                                                                          *
 *   This library  is distributed in the hope that it will be useful,       *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of         *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          *
 *   GNU Library General Public License for more details.                   *
 *                                                                          *
 *   You should have received a copy of the GNU Library General Public      *
 *   License along with this library; see the file COPYING.LIB. If not,     *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,          *
 *   Suite 330, Boston, MA  02111-1307, USA                                 *
 *                                                                          *
 ****************************************************************************/

#pragma once

#include <string>
#include <vector>

#include <FCGlobal.h>

#include "VariableLookup.h"

namespace App
{

class DocumentObject;

/** The variable `#name` means when several sets of a document define the name, by the choice
 * recorded on the copies (FreeCAD-CH, ops#640, decision 317), or nullptr: `#name` stays ambiguous.
 *
 * A local variable (a plain VarSet's) and an imported one (an App::VarSetCopy's) of the same name
 * make `#name` ambiguous for new expressions. The user's choice of which one it means is kept in
 * each copy's `Bindings` under the key `#name`, as the full path of the chosen variable
 * (`Variables.Width`, or the copy's own `Studio_A.Width`); `freecad.variables.copies` writes it.
 * It counts only when every copy among @a refs has the same record, it names one of @a refs, and
 * no other set has the name unchosen: the chosen one if it isn't a copy, else at most one set
 * that isn't a copy (the local one it was chosen over). Anything else stays ambiguous, as without
 * a choice. Stored expressions hold full paths and never depend on it.
 *
 * @a refs: VariableLookup::find() for one name.
 */
AppExport const DocumentObject* chosenVariableHolder(const std::vector<VariableRef>& refs);

}  // namespace App
