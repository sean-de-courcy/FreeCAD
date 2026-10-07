// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 Stefan Tröger <stefantroeger@gmx.net>              *
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


#include <QMenu>


#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Mod/PartDesign/App/FeatureLoft.h>

#include "ViewProviderLoft.h"
#include "TaskLoftParameters.h"

using namespace PartDesignGui;

PROPERTY_SOURCE(PartDesignGui::ViewProviderLoft, PartDesignGui::ViewProvider)

ViewProviderLoft::ViewProviderLoft() = default;

ViewProviderLoft::~ViewProviderLoft() = default;

std::vector<App::DocumentObject*> ViewProviderLoft::claimChildren() const
{
    std::vector<App::DocumentObject*> temp;

    PartDesign::Loft* pcLoft = getObject<PartDesign::Loft>();

    App::DocumentObject* sketch = pcLoft->getVerifiedSketch(true);
    if (sketch) {
        temp.push_back(sketch);
    }

    for (App::DocumentObject* obj : pcLoft->Sections.getValues()) {
        if (obj && obj->isDerivedFrom<Part::Part2DObject>()) {
            temp.push_back(obj);
        }
    }

    return temp;
}

void ViewProviderLoft::setupContextMenu(QMenu* menu, QObject* receiver, const char* member)
{
    addDefaultAction(menu, QObject::tr("Edit Loft"));
    ViewProvider::setupContextMenu(menu, receiver, member);
}

TaskDlgFeatureParameters* ViewProviderLoft::getEditDialog()
{
    return new TaskDlgLoftParameters(this);
}

QIcon ViewProviderLoft::getIcon() const
{
    QString str = QStringLiteral("PartDesign_");
    auto* prim = getObject<PartDesign::Loft>();
    if (prim->getAddSubType() == PartDesign::FeatureAddSub::Type::Additive) {
        str += QStringLiteral("Additive");
    }
    else {
        str += QStringLiteral("Subtractive");
    }

    str += QStringLiteral("Loft.svg");
    return PartDesignGui::ViewProvider::mergeGreyableOverlayIcons(
        Gui::BitmapFactory().pixmap(str.toStdString().c_str())
    );
}
