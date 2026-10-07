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
#include <map>
#include <string>
#include <utility>
#include <vector>

#include <Base/Type.h>
#include <FCGlobal.h>

#include "ObjectIdentifier.h"

namespace App
{

class Document;
class DocumentObject;
class Expression;
class Property;

/// A named variable of a document: a VarSet property or a Spreadsheet alias (FreeCAD-CH, ops#152).
struct AppExport VariableRef
{
    const DocumentObject* holder = nullptr;
    std::string name;

    /// The full path an expression uses for it, e.g. "VarSet.Width" or "Sheet.Depth".
    std::string path() const;
};

/** An expression that uses a variable: @a path is a property of @a user, or a cell of a sheet.
 *
 * It holds plain pointers: use it right away and drop it before the next document change, since
 * deleting @a user (or closing its document) leaves it dangling. Detaching @a user (removed in a
 * transaction) is fine: toString() then gives only the path.
 */
struct AppExport VariableUse
{
    const DocumentObject* user = nullptr;
    ObjectIdentifier path;

    /** E.g. "Box.Length" or "Sheet.B1", and "Other#Box.Length" for a user outside @a home
     * (no @a home: always with the document). A user detached since uses() gives only the path.
     */
    std::string toString(const Document* home = nullptr) const;
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

    /// Whether @a obj holds a variable named @a name.
    static bool isVariable(const DocumentObject* obj, const std::string& name);

    /// Every expression that uses @a prop: properties' expressions and Spreadsheet cells alike
    /// (DocumentObject::getPropertyUses misses the cells), of its object and its InList, other
    /// documents included. A use through an App::Link to the holder isn't found: the Link, not
    /// the user, is in the InList.
    static std::vector<VariableUse> uses(const Property* prop);
};

/** While alive, Expression::toString(persistent = false) on this thread writes a reference to a
 * variable as `#Name` (FreeCAD-CH, ops#152, notes/variables-design.md section 8).
 *
 * A reference is shortened when it names a variable of the owner's document whose name is unique
 * there, names no other document and no sub-object, and has an object part (`VarSet.Width`,
 * `<<Variables>>.Width`, `.Width`). A bare name is kept as written, except in the VarSet itself,
 * where `#Width` is stored as `Width`. Everything else is written as today, and
 * toString(persistent = true) never shortens. Scopes nest; each restores the previous one.
 *
 * Keep a scope short-lived, around one display call: the name counts are taken at the first
 * variable reference and kept for the scope's life, keyed by Document*, so a scope held across
 * document changes would judge uniqueness on stale counts.
 */
class AppExport VariableDisplayScope
{
public:
    VariableDisplayScope();
    ~VariableDisplayScope();
    VariableDisplayScope(const VariableDisplayScope&) = delete;
    VariableDisplayScope& operator=(const VariableDisplayScope&) = delete;

    /// The innermost scope of this thread, or nullptr.
    static VariableDisplayScope* current();

    /// `#Name` plus sub-path for @a var in an expression owned by @a owner, or empty to keep it.
    std::string shortForm(const DocumentObject* owner, const ObjectIdentifier& var);

    /// The (#Name, full path) pairs shortened so far, each once, in order.
    const std::vector<std::pair<std::string, std::string>>& shortened() const
    {
        return _shortened;
    }

private:
    VariableDisplayScope* _previous;
    std::map<const Document*, std::map<std::string, int>> _counts;
    std::vector<std::pair<std::string, std::string>> _shortened;
};

/// @a e as text for display, in a scope of its own; @a shortened gets the (#Name, path) pairs.
AppExport std::string toDisplayString(
    const Expression* e,
    std::vector<std::pair<std::string, std::string>>* shortened = nullptr
);

}  // namespace App
