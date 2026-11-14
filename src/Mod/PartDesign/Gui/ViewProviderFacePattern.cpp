// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD project.

/******************************************************************************
 *                                                                            *
 *   FreeCAD is free software: you can redistribute it and/or modify          *
 *   it under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1            *
 *   of the License, or (at your option) any later version.                   *
 *                                                                            *
 *   FreeCAD is distributed in the hope that it will be useful,               *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty              *
 *   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                  *
 *   See the GNU Lesser General Public License for more details.              *
 *                                                                            *
 *   You should have received a copy of the GNU Lesser General Public         *
 *   License along with FreeCAD. If not, see https://www.gnu.org/licenses     *
 *                                                                            *
 ******************************************************************************/


#include <Mod/PartDesign/App/FeatureFacePattern.h>

#include "TaskFacePatternParameters.h"
#include "ViewProviderFacePattern.h"

using namespace PartDesignGui;

PROPERTY_SOURCE(PartDesignGui::ViewProviderFacePattern, PartDesignGui::ViewProviderDressUp)


void ViewProviderFacePattern::attach(App::DocumentObject* pcObject)
{
    ViewProviderDressUp::attach(pcObject);
    if (pcObject->isDerivedFrom<PartDesign::FacePolarPattern>()) {
        sPixmap = "PartDesign_PolarPattern.svg";
    }
    else if (pcObject->isDerivedFrom<PartDesign::FaceMirrored>()) {
        sPixmap = "PartDesign_Mirrored.svg";
    }
}

const std::string& ViewProviderFacePattern::featureName() const
{
    static const std::string linear = "LinearPattern";
    static const std::string polar = "PolarPattern";
    static const std::string mirrored = "Mirrored";
    auto object = getObject();
    if (object && object->isDerivedFrom<PartDesign::FacePolarPattern>()) {
        return polar;
    }
    if (object && object->isDerivedFrom<PartDesign::FaceMirrored>()) {
        return mirrored;
    }
    return linear;
}

void ViewProviderFacePattern::setupContextMenu(QMenu* menu, QObject* receiver, const char* member)
{
    addDefaultAction(menu, QObject::tr("Edit Face pattern"));
    PartDesignGui::ViewProvider::setupContextMenu(menu, receiver, member);
}

TaskDlgFeatureParameters* ViewProviderFacePattern::getEditDialog()
{
    return new TaskDlgFacePatternParameters(this);
}
