// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// FreeCAD-CH (ops#723): the history position of Part Studio variables, Onshape's Variable feature
// (notes/variable-history-position.md, App/VariablePosition.h). A variable of a VarSet inside a
// part studio (an App::Part) sits right after one row of the studio's history (studioSequence()).

#include <string>

#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class DocumentObject;
}  // namespace App

namespace PartDesign
{

/** Module start-up: places rows against variables for App (App::VariablePosition::setOrder());
 * gives a variable added to a part studio's VarSet the place the studio's bar is at
 * (studioBarAfter(): the end of the history, or the rolled-back bar, as Onshape inserts a
 * Variable feature); keeps the places through a rename or removal of the variable and a delete of
 * the row it follows (it then follows the row before); drops them from an imported VarSet (a copy,
 * a paste: its rows' names mean nothing there). Undo and redo restore places as they were
 */
PartDesignExport void registerStudioVariables();

/// The row of its part studio's history the variable name of holder follows, or null at the start
/// (also when that row is gone: App::VariablePosition::Place::Lost)
PartDesignExport App::DocumentObject* variablePosition(const App::DocumentObject* holder,
                                                       const std::string& name);

/** Places the variable name of holder (a VarSet in a part studio) right after the row after of
 * the studio's history (studioSequence()), or at its start for null. Throws Base::ValueError,
 * before anything is written, for a holder in no part studio, an unknown name, or an after that
 * is no row of the studio. Opens no transaction and doesn't recompute: the users of the set are
 * touched (the set changes), and a row now above the variable fails at the recompute (DV4)
 */
PartDesignExport void setVariablePosition(App::DocumentObject* holder,
                                          const std::string& name,
                                          App::DocumentObject* after);

}  // namespace PartDesign
