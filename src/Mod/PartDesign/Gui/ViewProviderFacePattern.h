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


#pragma once

#include "ViewProviderDressUp.h"


namespace PartDesignGui
{

/// FreeCAD-CH (ops#655 T8): the view provider of the face patterns (PartDesign::FaceLinearPattern,
/// FacePolarPattern and FaceMirrored)
class PartDesignGuiExport ViewProviderFacePattern: public ViewProviderDressUp
{
    Q_DECLARE_TR_FUNCTIONS(PartDesignGui::ViewProviderFacePattern)
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesignGui::ViewProviderFacePattern);

public:
    ViewProviderFacePattern()
    {
        sPixmap = "PartDesign_LinearPattern.svg";
        menuName = tr("Face pattern");
    }

    void attach(App::DocumentObject* pcObject) override;
    /// The name of the pattern's own icon (PartDesign_<name>): the object's type decides
    const std::string& featureName() const override;
    void setupContextMenu(QMenu*, QObject*, const char*) override;

protected:
    TaskDlgFeatureParameters* getEditDialog() override;
};

}  // namespace PartDesignGui
