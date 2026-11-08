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
 **************************************************************************/

#include <Base/Exception.h>
#include <Gui/Application.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/Feature.h>

#include "RollbackView.h"
#include "ViewProvider.h"

using namespace PartDesignGui;

namespace
{
PartDesignGui::ViewProvider* featureViewProvider(App::DocumentObject* obj)
{
    return obj && Gui::Application::Instance ? freecad_cast<PartDesignGui::ViewProvider*>(
                     Gui::Application::Instance->getViewProvider(obj)
                 )
               : nullptr;
}
}  // namespace

RollbackView::~RollbackView()
{
    try {
        restore();
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

void RollbackView::rollBackTo(App::DocumentObject* feature)
{
    restore();
    PartDesign::Body* body = feature ? PartDesign::Body::findBodyOf(feature) : nullptr;
    if (!body) {
        return;
    }
    App::DocumentObject* before = body->getPrevSolidFeature(feature);

    // Every solid after the feature that is still shown goes from the scene: the Tip, and any
    // other one a sketch's own visibility automation showed (ShowSupport shows the feature the
    // sketch sits on, which may itself come after the solid before the sketch)
    bool afterFeature = false;
    for (App::DocumentObject* obj : body->Group.getValues()) {
        if (obj == feature) {
            afterFeature = true;
            continue;
        }
        if (!afterFeature || obj == before || !obj->isDerivedFrom<PartDesign::Feature>()) {
            continue;
        }
        if (auto vp = featureViewProvider(obj); vp && vp->isShow()) {
            vp->makeTemporaryVisible(false);
            hidden.emplace_back(obj);
        }
    }
    // The solid before it comes into the scene
    if (auto vp = featureViewProvider(before); vp && !vp->isShow()) {
        vp->makeTemporaryVisible(true);
        base = before;
    }
}

void RollbackView::showBodyAt(PartDesign::Body* body, App::DocumentObject* solid)
{
    restore();
    if (!body) {
        return;
    }
    // Every solid after solid (each one, at the top) that is still shown goes from the scene
    bool afterSolid = !solid;
    for (App::DocumentObject* obj : body->Group.getValues()) {
        if (obj == solid) {
            afterSolid = true;
            continue;
        }
        if (!afterSolid || !obj->isDerivedFrom<PartDesign::Feature>()) {
            continue;
        }
        if (auto vp = featureViewProvider(obj); vp && vp->isShow()) {
            vp->makeTemporaryVisible(false);
            hidden.emplace_back(obj);
        }
    }
    // The solid it is at comes into the scene
    if (auto vp = featureViewProvider(solid); vp && !vp->isShow()) {
        vp->makeTemporaryVisible(true);
        base = solid;
    }
}

void RollbackView::restore()
{
    // Only what is still as the roll-back left it: an object the user showed or hid since (its
    // Visibility changed) keeps what the user chose
    if (auto vp = featureViewProvider(base.getObject()); vp && !vp->Visibility.getValue()) {
        vp->makeTemporaryVisible(false);
    }
    for (const App::DocumentObjectT& objT : hidden) {
        if (auto vp = featureViewProvider(objT.getObject()); vp && vp->Visibility.getValue()) {
            vp->makeTemporaryVisible(true);
        }
    }
    base = App::DocumentObjectT();
    hidden.clear();
}
