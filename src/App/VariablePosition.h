// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <functional>
#include <string>

#include <FCGlobal.h>

#include "VariableLookup.h"

namespace App
{

class DocumentObject;
class Expression;

/** FreeCAD-CH (ops#723): the history position of a Part Studio variable, Onshape's Variable
 * feature (notes/variable-history-position.md; DV1 and DV4 in notes/onshape-facts.md).
 *
 * A variable of a VarSet inside a part studio (an App::Part) has a place in that studio's
 * history: right after one of its rows, saved by name in the set's VariablePositions. A row at or
 * above that place comes before the variable: there `#name` doesn't see it (an outer variable of
 * the same name is used instead, the Variable Studio's: DV1), and an expression of the row that
 * uses it fails (DV4). A variable without a saved place is at the start of the history, seen by
 * every row, as all variables were before ops#723.
 *
 * App knows no history: PartDesign registers the function that places a row against a variable
 * (setOrder()). Without it every place is Unknown and nothing is checked.
 */
class AppExport VariablePosition
{
public:
    /// Where a row is, against a variable's place
    enum class Place
    {
        Unknown,  ///< not a row of the variable's part studio, or no place to compare with
        Before,   ///< at or above the variable's place: the variable isn't set there yet
        After,    ///< below it: the variable is seen
        Lost,     ///< the row the variable follows is no row of the studio any more
    };

    /// Places user against the variable that follows the row named anchor (never empty) of
    /// holder's part studio
    using OrderFunction = std::function<
        Place(const DocumentObject* user, const DocumentObject* holder, const std::string& anchor)>;

    static void setOrder(OrderFunction order);

    /// The saved place of a variable placed at the start of the history. Unlike a variable with
    /// no saved place (a file from before ops#723), it shadows outer variables of its name
    static constexpr const char* atStart = "<start>";

    /// The row the variable follows, atStart, or "" when no place is saved
    static std::string anchorOf(const DocumentObject* holder, const std::string& name);

    /// Saves the variable's place: after the row anchor, or at the start (atStart) for "";
    /// holder must be a VarSet. No recompute
    static void setAnchor(DocumentObject* holder, const std::string& name, const std::string& anchor);

    /// Forgets the variable's saved place (a removed variable)
    static void clearAnchor(DocumentObject* holder, const std::string& name);

    /// Where user is against the variable ref
    static Place placeOf(const DocumentObject* user, const VariableRef& ref);

    /** Why the expression of user can't be evaluated at user's place in the history, or "":
     * it uses a variable set after user (DV4), a variable whose place is lost, or an outer
     * variable that a variable of user's own studio of the same name shadows at user's place
     * (DV1: written before the studio's was set, or the row moved below it since)
     */
    static std::string checkExpression(const DocumentObject* user, const Expression& expression);
};

}  // namespace App
