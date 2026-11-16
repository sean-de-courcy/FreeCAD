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

    /** FreeCAD-CH (ops#723): the history position of each Part Studio variable of this set: the
     * name of the row of its part studio's history the variable follows. A variable without an
     * entry is at the start of the history, as every variable was before ops#723. Hidden; see
     * App/VariablePosition.h
     */
    PropertyMap VariablePositions;

    const char* getViewProviderName() const override;
};

}  // namespace App
