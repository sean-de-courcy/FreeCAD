// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2024 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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


#include <cstring>
#include <initializer_list>

#include "WorkbenchManipulator.h"
#include <Gui/ForkKeymap.h>
#include <Gui/MenuManager.h>
#include <Gui/ToolBarManager.h>

using namespace MatGui;

namespace
{

/// Inserts the commands, in their order, after the menu's entry reference (at any depth), if
/// the menu has it
void insertAfter(
    Gui::MenuItem* menuBar,
    const char* reference,
    std::initializer_list<const char*> commands
)
{
    Gui::MenuItem* par = menuBar->findParentOf(reference);
    if (!par) {
        return;
    }
    Gui::MenuItem* before = par->afterItem(par->findItem(reference));
    for (const char* command : commands) {
        auto item = new Gui::MenuItem();
        item->setCommand(command);
        if (before) {
            par->insertItem(before, item);
        }
        else {
            par->appendItem(item);
        }
    }
}

}  // namespace

void WorkbenchManipulator::modifyMenuBar([[maybe_unused]] Gui::MenuItem* menuBar)
{
    addCommands(menuBar, "Std_ToggleNavigation");
}

void WorkbenchManipulator::modifyContextMenu(const char* recipient, Gui::MenuItem* menuBar)
{
    if (strcmp(recipient, "View") == 0) {
        if (Gui::ForkKeymap::isOnshape()) {
            // Onshape's menu of the 3D view (FreeCAD-CH, ops#640): Edit appearance, then Assign
            // material, after Make transparent. Std_TreeSelection lies under its More submenu,
            // where these don't go; its empty-space menu has no Make transparent, so nothing
            insertAfter(
                menuBar,
                "Std_ToggleTransparency",
                {"Std_SetAppearance", "Std_SetMaterial"}
            );
        }
        else {
            addCommands(menuBar, "Std_TreeSelection");
        }
    }
    else if (strcmp(recipient, "Tree") == 0) {
        addCommandsToTree(menuBar);
    }
}

void WorkbenchManipulator::addCommands(Gui::MenuItem* menuBar, const char* reference)
{
    insertAfter(menuBar, reference, {"Std_SetMaterial", "Std_SetAppearance"});
}

void WorkbenchManipulator::addCommandsToTree(Gui::MenuItem* menuBar)
{
    const char* randomColor = "Std_RandomColor";
    auto par = menuBar->findParentOf(randomColor);
    if (par) {
        auto item = par->findItem(randomColor);

        auto cmd1 = new Gui::MenuItem();
        cmd1->setCommand("Std_SetMaterial");
        par->insertItem(item, cmd1);
        auto cmd2 = new Gui::MenuItem();
        cmd2->setCommand("Std_SetAppearance");
        par->insertItem(item, cmd2);
    }
}
