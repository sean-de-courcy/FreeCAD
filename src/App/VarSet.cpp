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

#include <iostream>

#include <algorithm>

#include "VarSet.h"
#include "DocumentObject.h"
#include "DocumentTabs.h"
#include "Expression.h"
#include "ObjectIdentifier.h"

using namespace App;

PROPERTY_SOURCE(App::VarSet, App::DocumentObject)

const char* VarSet::getViewProviderName() const
{
    return "Gui::ViewProviderVarSet";
}

std::string VarSet::orderError() const
{
    if (!DocumentTabs::isVariableStudio(this)) {
        return {};
    }
    const std::vector<std::string> names = getDynamicPropertyNames();
    for (std::size_t i = 0; i < names.size(); ++i) {
        const Property* prop = getPropertyByName(names[i].c_str());
        if (!prop) {
            continue;
        }
        auto info = getExpression(ObjectIdentifier(*prop));
        if (!info.expression) {
            continue;
        }
        ExpressionDeps deps = info.expression->getDeps();
        auto own = deps.find(const_cast<VarSet*>(this));
        if (own == deps.end()) {
            continue;
        }
        for (const auto& [used, paths] : own->second) {
            auto at = std::find(names.begin(), names.end(), used);
            if (at != names.end() && std::size_t(at - names.begin()) >= i) {
                return "#" + names[i] + " uses #" + used + ", which is below it in "
                    + Label.getValue() + ": a variable uses only those above it (move #" + used
                    + " up)";
            }
        }
    }
    return {};
}

DocumentObjectExecReturn* VarSet::execute()
{
    std::string why = orderError();
    if (!why.empty()) {
        return new DocumentObjectExecReturn(why, this);
    }
    return DocumentObject::execute();
}
