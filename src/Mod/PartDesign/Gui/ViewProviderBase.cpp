// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2017 Stefan Tröger <stefantroeger@gmx.net>              *
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


#include <App/Document.h>
#include <Gui/CommandT.h>
#include <Gui/Control.h>
#include <Mod/Part/App/BodyBase.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/Derived.h>
#include <Mod/PartDesign/App/FeatureBase.h>

#include "TaskDerived.h"
#include "ViewProviderBase.h"


using namespace PartDesignGui;

PROPERTY_SOURCE(PartDesignGui::ViewProviderBase, PartDesignGui::ViewProvider)

ViewProviderBase::ViewProviderBase()
{
    sPixmap = "PartDesign_BaseFeature.svg";
}

ViewProviderBase::~ViewProviderBase() = default;

bool ViewProviderBase::doubleClicked()
{
    // A Derived feature's row reopens its dialog (FreeCAD-CH ops#640 round 6)
    if (PartDesign::FeatureBase* lead = PartDesign::derivedLead(getObject())) {
        if (Gui::Control().activeDialog()) {
            return true;
        }
        App::Part* studio = nullptr;
        if (Part::BodyBase::studioOf(PartDesign::Body::findBodyOf(lead), studio)) {
            Gui::Control().showDialog(new TaskDlgDerived(lead->getDocument(), studio, lead));
        }
        return true;
    }
    // If the Placement is mutable then open the transform panel.
    // If the Placement can't be modified then just do nothing on double-click.
    PartDesign::FeatureBase* base = getObject<PartDesign::FeatureBase>();
    if (!base->Placement.testStatus(App::Property::Immutable)
        && !base->Placement.testStatus(App::Property::ReadOnly)
        && !base->Placement.testStatus(App::Property::Hidden)) {

        try {
            std::string Msg("Edit ");
            Msg += base->Label.getValue();
            // FreeCAD-CH (ops#640): the open dialog stayed (as ViewProvider::doubleClicked)
            if (getDocument()->openCommand(Msg.c_str()) == 0
                && getDocument()->getDocument()->isStepLocked()) {
                return true;
            }
            Gui::cmdSetEdit(base, Gui::Application::Instance->getUserEditMode());
        }
        catch (const Base::Exception&) {
            getDocument()->commitCommand();
        }
        return true;
    }

    return false;
}

bool ViewProviderBase::onDelete(const std::vector<std::string>& subNames)
{
    // A Derived feature's lead (its row): its other members, the binders and the parts it made go
    // in the same step (FreeCAD-CH ops#640 round 6). Its Body, when the lead is all it holds, goes
    // too, which leaves the lead in no Body for Std_Delete to remove
    auto base = getObject<PartDesign::FeatureBase>();
    if (!isEditing() && base && PartDesign::derivedLead(base) == base) {
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "PartDesign.deleteDerivedParts(%s)",
            Gui::Command::getObjectCmd(base).c_str()
        );
        if (!PartDesign::Body::findBodyOf(base)) {
            return true;
        }
    }
    return ViewProvider::onDelete(subNames);
}

void ViewProviderBase::setupContextMenu(QMenu* menu, QObject* receiver, const char* member)
{
    // If the Placement is mutable then show the context-menu of the base class.
    PartDesign::FeatureBase* base = getObject<PartDesign::FeatureBase>();
    if (!base->Placement.testStatus(App::Property::Immutable)
        && !base->Placement.testStatus(App::Property::ReadOnly)
        && !base->Placement.testStatus(App::Property::Hidden)) {

        // Handling of the edge case where some base features are outside the body
        // that should not happen, but it was possible to do in older FreeCAD versions.
        // This ensures that for older files it still works correctly.
        if (!getBodyViewProvider()) {
            ViewProviderPartExt::setupContextMenu(menu, receiver, member);
        }

        ViewProvider::setupContextMenu(menu, receiver, member);
    }
}
Gui::ViewProvider* ViewProviderBase::startEditing(int ModNum)
{
    if (!getBodyViewProvider()) {
        return ViewProviderPartExt::startEditing(ModNum);
    }

    return ViewProvider::startEditing(ModNum);
}

bool ViewProviderBase::setEdit(int ModNum)
{
    PartDesign::FeatureBase* base = getObject<PartDesign::FeatureBase>();
    if (!base->Placement.testStatus(App::Property::Immutable)
        && !base->Placement.testStatus(App::Property::ReadOnly)
        && !base->Placement.testStatus(App::Property::Hidden)) {

        // same as in setupContextMenu
        if (!getBodyViewProvider()) {
            return ViewProviderPartExt::setEdit(ModNum);
        }

        return ViewProvider::setEdit(ModNum);
    }

    return false;
}
