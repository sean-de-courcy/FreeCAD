// SPDX-License-Identifier: LGPL-2.1-or-later
/***************************************************************************
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
 ***************************************************************************/

#pragma once

#include <string>
#include <vector>

#include <fastsignals/signal.h>

#include "MDIView.h"
#include "Workbench.h"

namespace App
{
class DocumentObject;
}

namespace Gui
{

namespace DockWnd
{
class VariablesView;
}

/** A Variable Studio tab's window (FreeCAD-CH, ops#640, tabs slice 4;
 * notes/onshape-tabs-design.md "Slice 4"): the table of one Variable Studio's variables, with its
 * own toolbar, as Onshape's Variable Studio fills its tab. No 3D view. The table is the Variables
 * panel scoped to the studio (Gui/VariablesView.cpp): its edits, one undo step each, are the
 * panel's. The window closes when its studio is deleted.
 */
class GuiExport VariableStudioView: public MDIView
{
    Q_OBJECT

    TYPESYSTEM_HEADER_WITH_OVERRIDE();

public:
    VariableStudioView(Gui::Document* doc, App::DocumentObject* studio, QWidget* parent);
    ~VariableStudioView() override;

    const char* getName() const override
    {
        return "VariableStudioView";
    }

    bool onMsg(const char* pMsg) override;
    bool onHasMsg(const char* pMsg) const override;
    void onRelabel(Gui::Document* pDoc) override;

    /// The studio's internal name in the view's document
    const std::string& studioName() const
    {
        return studio;
    }

    /// The studio's window: the one already open, else a new one added to the main window
    static VariableStudioView* open(Gui::Document* doc, App::DocumentObject* studio);
    /// The studio's window if one is open, else nullptr
    static VariableStudioView* find(Gui::Document* doc, const App::DocumentObject* studio);

private:
    void updateTitle();

    std::string studio;
    DockWnd::VariablesView* table;
    std::vector<fastsignals::scoped_connection> connections;
};

/** The tools of a Variable Studio tab: the standard menus and the File, Edit and Workbench
 * toolbars only, so no Part Design toolbar or Features list shows (tabs slice 4).
 */
class GuiExport VariableStudioWorkbench: public StdWorkbench
{
    TYPESYSTEM_HEADER_WITH_OVERRIDE();

public:
    VariableStudioWorkbench();
    ~VariableStudioWorkbench() override;

protected:
    ToolBarItem* setupToolBars() const override;
    ToolBarItem* setupCommandBars() const override;
};

}  // namespace Gui
