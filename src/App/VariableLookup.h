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

#include <functional>
#include <string>
#include <vector>

#include <Base/Type.h>
#include <FCGlobal.h>

namespace App
{

class Document;
class DocumentObject;

/// A named variable of a document: a VarSet property or a Spreadsheet alias (FreeCAD-CH, ops#152).
struct AppExport VariableRef
{
    const DocumentObject* holder = nullptr;
    std::string name;

    /// The full path an expression uses for it, e.g. "VarSet.Width" or "Sheet.Depth".
    std::string path() const;
};

/** The objects that hold variables for `#name` in expressions (FreeCAD-CH, ops#152).
 *
 * A provider is a type and two functions: whether an object of that type holds a variable of
 * a given name, and the names it holds. App::VarSet is built in; other modules register their
 * own (Spreadsheet: aliases).
 */
class AppExport VariableLookup
{
public:
    using HasFunction = std::function<bool(const DocumentObject*, const std::string&)>;
    using ListFunction = std::function<std::vector<std::string>(const DocumentObject*)>;

    static void registerProvider(Base::Type type, HasFunction has, ListFunction list);

    /// Every variable named @a name in @a doc, in the document's object order.
    static std::vector<VariableRef> find(const Document* doc, const std::string& name);

    /// Every variable of @a doc, per object in the document's object order.
    static std::vector<VariableRef> listVariables(const Document* doc);
};

}  // namespace App
