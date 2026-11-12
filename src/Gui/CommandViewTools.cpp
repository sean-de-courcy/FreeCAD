// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 Crawlspace Habitats LLC                            *
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

// FreeCAD-CH (ops#640): the view tools of Onshape's View menu: section view, named views,
// display styles, camera.

#include <algorithm>
#include <vector>

#include <Inventor/SbVec3f.h>
#include <QPointer>

#include "Action.h"
#include "Application.h"
#include "Command.h"
#include "MainWindow.h"
#include "SectionView.h"
#include "View3DInventor.h"
#include "View3DInventorViewer.h"

using namespace Gui;

namespace
{
View3DInventor* activeView3D()
{
    return qobject_cast<View3DInventor*>(getMainWindow()->activeWindow());
}
}  // namespace

//===========================================================================
// Std_SectionView
//===========================================================================

DEF_STD_CMD_AC(StdCmdSectionView)

namespace
{
std::vector<QPointer<Gui::Dialog::SectionViewPanel>> sectionPanels;
}

StdCmdSectionView::StdCmdSectionView()
    : Command("Std_SectionView")
{
    sGroup = "Standard-View";
    sMenuText = QT_TR_NOOP("&Section view");
    sToolTipText = QT_TR_NOOP(
        "Hides one side of a plane and fills the cut, so the model looks solid. Only the view "
        "changes, not the document"
    );
    sWhatsThis = "Std_SectionView";
    sStatusTip = sToolTipText;
    sPixmap = "Std_ToggleClipPlane";
    eType = Alter3DView;
}

Action* StdCmdSectionView::createAction()
{
    Action* pcAction = Command::createAction();
    pcAction->setCheckable(true);
    return pcAction;
}

void StdCmdSectionView::activated(int iMsg)
{
    View3DInventor* view = activeView3D();
    if (!view) {
        return;
    }

    // forget the panels that are gone
    sectionPanels.erase(
        std::remove_if(
            sectionPanels.begin(),
            sectionPanels.end(),
            [](const QPointer<Gui::Dialog::SectionViewPanel>& panel) { return panel.isNull(); }
        ),
        sectionPanels.end()
    );
    auto panelOfView = std::find_if(
        sectionPanels.begin(),
        sectionPanels.end(),
        [view](const QPointer<Gui::Dialog::SectionViewPanel>& panel) {
            return panel->getView() == view;
        }
    );

    if (iMsg == 1) {
        if (panelOfView == sectionPanels.end()) {
            sectionPanels.emplace_back(Gui::Dialog::SectionViewPanel::makeDockWidget(view));
        }
    }
    else {
        if (panelOfView != sectionPanels.end()) {
            (*panelOfView)->closePanel();
            sectionPanels.erase(panelOfView);
        }
        // a section that was set without the panel (Python)
        SectionView::clear(view->getViewer());
    }

    SbVec3f origin;
    SbVec3f cut;
    if (_pcAction) {
        _pcAction->setChecked(SectionView::get(view->getViewer(), origin, cut));
    }
}

bool StdCmdSectionView::isActive()
{
    View3DInventor* view = activeView3D();
    if (!view) {
        return false;
    }
    SbVec3f origin;
    SbVec3f cut;
    const bool on = SectionView::get(view->getViewer(), origin, cut);
    if (_pcAction && _pcAction->isChecked() != on) {
        _pcAction->setChecked(on);
    }
    return true;
}

//===========================================================================
// registration
//===========================================================================

namespace Gui
{
void CreateViewToolCommands()
{
    CommandManager& rcCmdMgr = Application::Instance->commandManager();
    rcCmdMgr.addCommand(new StdCmdSectionView());
}
}  // namespace Gui
