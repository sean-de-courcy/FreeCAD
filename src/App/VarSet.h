// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
 *   Copyright (c) 2024 Ondsel <development@ondsel.com>                     *
 *                                                                          *
 *   This file is part of the FreeCAD CAx development system.               *
 *                                                                          *
 *   This library is free software; you can redistribute it and/or          *
 *   modify it under the terms of the GNU Library General Public            *
 *   License as published by the Free Software Foundation; either           *
 *   version 2 of the License, or (at your option) any later version.       *
 *                                                                          *
 *   This library  is distributed in the hope that it will be useful,       *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of         *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          *
 *   GNU Library General Public License for more details.                   *
 *                                                                          *
 *   You should have received a copy of the GNU Library General Public      *
 *   License along with this library; see the file COPYING.LIB. If not,     *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,          *
 *   Suite 330, Boston, MA  02111-1307, USA                                 *
 *                                                                          *
 ****************************************************************************/

#pragma once

#include <string>

#include "DocumentObject.h"
#include "PropertyStandard.h"

namespace App
{

/** A DocumentObject class with the purpose to store variables
 */
class AppExport VarSet: public App::DocumentObject
{
    PROPERTY_HEADER_WITH_OVERRIDE(App::VarSet);

public:
    VarSet();
    ~VarSet() override = default;

    const char* getViewProviderName() const override;

    /** FreeCAD-CH (ops#640, polish 13 P17): the variables' order, Onshape's rows (hidden). A
     * VarSet's dynamic properties have no order of their own (hashed): getDynamicPropertyNames()
     * lists those named here first, in this order, then the others. A variable added is appended,
     * a renamed one keeps its place; Move up / Move down rewrite it (freecad.variables.order).
     */
    PropertyStringList VariableOrder;

    std::vector<std::string> getDynamicPropertyNames() const override;
    Property* addDynamicProperty(
        std::string_view type,
        const char* name = nullptr,
        const char* group = nullptr,
        const char* doc = nullptr,
        short attr = 0,
        bool ro = false,
        bool hidden = false
    ) override;
    bool renameDynamicProperty(Property* prop, const char* name) override;

    /** FreeCAD-CH (ops#640, polish 13 P17): Onshape's order rule in a Variable Studio (VS Q5): a
     * variable may use only those above it, so one that uses a variable below it fails the
     * studio, naming both, and the features using the studio fail with it (Onshape: the variable
     * is invalid and an extrude using it fails). Move up / Move down heals it.
     */
    DocumentObjectExecReturn* execute() override;

    /// The order rule's breach in a Variable Studio: "#h uses #w, which is below it ...", or ""
    std::string orderError() const;
};

}  // namespace App
