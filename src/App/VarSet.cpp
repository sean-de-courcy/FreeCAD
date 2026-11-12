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
        // A change touches the studio, an undo's or redo's too: the order rule is checked again
        // (review polish13-r1 T-B)
        PropertyType(Prop_Hidden),
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
        // A new variable goes last, also under a name a removed one left in the order (review
        // polish13-r1 T3); a type change puts it back in its place itself
        std::vector<std::string> order = VariableOrder.getValues();
        if (order.empty()) {
            // A studio from before the order (review r2 R2-2): its rows as listed now, then the new
            order = getDynamicPropertyNames();
        }
        std::erase(order, std::string(prop->getName()));
        order.emplace_back(prop->getName());
        if (order != VariableOrder.getValues()) {
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
        // The new name keeps the old one's place, and only that one (review T-A)
        const std::string renamed = name;
        *it = renamed;
        std::vector<std::string> kept;
        for (std::size_t i = 0; i < order.size(); ++i) {
            if (order[i] != renamed || order.begin() + std::ptrdiff_t(i) == it) {
                kept.push_back(order[i]);
            }
        }
        VariableOrder.setValues(kept);
    }
    return true;
}

bool VarSet::removeDynamicProperty(const char* name)
{
    const std::string removed = name ? name : "";
    if (!DocumentObject::removeDynamicProperty(name)) {
        return false;
    }
    // Its place goes with it, in the same transaction (review T-A): a later variable of that
    // name is a new one, last
    std::vector<std::string> order = VariableOrder.getValues();
    if (!removed.empty() && isUserChange(this)
        && std::find(order.begin(), order.end(), removed) != order.end()) {
        std::erase(order, removed);
        VariableOrder.setValues(order);
    }
    return true;
}

Property* VarSet::moveDynamicProperty(Property* prop, DocumentObject* targetObj)
{
    const std::string name = prop && prop->getName() ? prop->getName() : "";
    Property* moved = DocumentObject::moveDynamicProperty(prop, targetObj);
    if (!moved || name.empty() || !isUserChange(this)) {
        return moved;
    }
    // Out of this order, last in the target's (review T-C)
    std::vector<std::string> order = VariableOrder.getValues();
    if (std::find(order.begin(), order.end(), name) != order.end()) {
        std::erase(order, name);
        VariableOrder.setValues(order);
    }
    if (auto target = freecad_cast<VarSet*>(targetObj)) {
        std::vector<std::string> theirs = target->VariableOrder.getValues();
        std::erase(theirs, name);
        theirs.push_back(name);
        target->VariableOrder.setValues(theirs);
    }
    return moved;
}

const char* VarSet::getViewProviderName() const
{
    return "Gui::ViewProviderVarSet";
}

std::string VarSet::orderError() const
{
    if (!DocumentTabs::isVariableStudio(this) || VariableOrder.getValues().empty()) {
        // A studio with no order written (from before polish 13) has none to break (review T4)
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
