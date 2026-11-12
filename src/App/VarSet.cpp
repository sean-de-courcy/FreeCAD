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
#include "Document.h"
#include "DocumentObject.h"
#include "DocumentTabs.h"
#include "Expression.h"
#include "ObjectIdentifier.h"

using namespace App;

PROPERTY_SOURCE(App::VarSet, App::DocumentObject)

VarSet::VarSet()
{
    ADD_PROPERTY_TYPE(
        VariableOrder,
        (),
        "",
        PropertyType(Prop_Hidden | Prop_NoRecompute),
        "The order of the variables (FreeCAD-CH)"
    );
}

std::vector<std::string> VarSet::getDynamicPropertyNames() const
{
    std::vector<std::string> names = DocumentObject::getDynamicPropertyNames();
    std::vector<std::string> ordered;
    ordered.reserve(names.size());
    for (const auto& name : VariableOrder.getValues()) {
        if (std::find(names.begin(), names.end(), name) != names.end()
            && std::find(ordered.begin(), ordered.end(), name) == ordered.end()) {
            ordered.push_back(name);
        }
    }
    for (const auto& name : names) {
        if (std::find(ordered.begin(), ordered.end(), name) == ordered.end()) {
            ordered.push_back(name);
        }
    }
    return ordered;
}

namespace
{
/// Whether a change of the variables is the user's, not a file being read or an undo replayed
bool isUserChange(const VarSet* obj)
{
    const Document* doc = obj->getDocument();
    return !obj->isRestoring() && !obj->testStatus(ObjectStatus::Remove)
        && !(doc && (doc->isPerformingTransaction() || doc->testStatus(Document::Restoring)));
}
}  // namespace

Property* VarSet::addDynamicProperty(
    std::string_view type,
    const char* name,
    const char* group,
    const char* doc,
    short attr,
    bool ro,
    bool hidden
)
{
    Property* prop = DocumentObject::addDynamicProperty(type, name, group, doc, attr, ro, hidden);
    if (prop && prop->getName() && isUserChange(this)) {
        std::vector<std::string> order = VariableOrder.getValues();
        if (std::find(order.begin(), order.end(), prop->getName()) == order.end()) {
            order.emplace_back(prop->getName());
            VariableOrder.setValues(order);
        }
    }
    return prop;
}

bool VarSet::renameDynamicProperty(Property* prop, const char* name)
{
    const std::string old = prop && prop->getName() ? prop->getName() : "";
    if (!DocumentObject::renameDynamicProperty(prop, name)) {
        return false;
    }
    std::vector<std::string> order = VariableOrder.getValues();
    auto it = std::find(order.begin(), order.end(), old);
    if (!old.empty() && name && it != order.end() && isUserChange(this)) {
        *it = name;
        VariableOrder.setValues(order);
    }
    return true;
}

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
