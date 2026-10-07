// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
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

#include <algorithm>

#include "VariableLookup.h"

#include "Document.h"
#include "DocumentObject.h"
#include "Expression.h"
#include "ObjectIdentifier.h"
#include "PropertyExpressionEngine.h"
#include "VarSet.h"

using namespace App;

namespace
{

struct Provider
{
    Base::Type type;
    VariableLookup::HasFunction has;
    VariableLookup::ListFunction list;
};

std::vector<Provider>& providers()
{
    // Built on first use, after the type system is up.
    static std::vector<Provider> list {{
        VarSet::getClassTypeId(),
        [](const DocumentObject* obj, const std::string& name) {
            return obj->getDynamicPropertyByName(name.c_str()) != nullptr;
        },
        [](const DocumentObject* obj) {
            return obj->getDynamicPropertyNames();
        },
    }};
    return list;
}

}  // namespace

std::string VariableRef::path() const
{
    return std::string(holder->getNameInDocument()) + "." + name;
}

void VariableLookup::registerProvider(Base::Type type, HasFunction has, ListFunction list)
{
    providers().push_back({type, std::move(has), std::move(list)});
}

std::vector<VariableRef> VariableLookup::find(const Document* doc, const std::string& name)
{
    std::vector<VariableRef> result;
    if (!doc || name.empty()) {
        return result;
    }
    for (auto obj : doc->getObjects()) {
        for (const auto& provider : providers()) {
            if (obj->isDerivedFrom(provider.type) && provider.has(obj, name)) {
                result.push_back({obj, name});
                break;
            }
        }
    }
    return result;
}

std::vector<VariableRef> VariableLookup::listVariables(const Document* doc)
{
    std::vector<VariableRef> result;
    if (!doc) {
        return result;
    }
    for (auto obj : doc->getObjects()) {
        for (const auto& provider : providers()) {
            if (obj->isDerivedFrom(provider.type)) {
                for (auto& name : provider.list(obj)) {
                    result.push_back({obj, std::move(name)});
                }
                break;
            }
        }
    }
    return result;
}

bool VariableLookup::isVariable(const DocumentObject* obj, const std::string& name)
{
    if (!obj || name.empty()) {
        return false;
    }
    for (const auto& provider : providers()) {
        if (obj->isDerivedFrom(provider.type)) {
            return provider.has(obj, name);
        }
    }
    return false;
}

std::vector<VariableUse> VariableLookup::uses(const Property* prop)
{
    std::vector<VariableUse> result;
    auto holder = prop ? freecad_cast<DocumentObject*>(prop->getContainer()) : nullptr;
    if (!holder || !holder->isAttachedToDocument()) {
        return result;
    }
    auto usesProp = [prop](const Expression* expr) {
        if (!expr) {
            return false;
        }
        for (const auto& [id, hidden] : expr->getIdentifiers()) {
            if (id.getProperty() == prop) {
                return true;
            }
        }
        return false;
    };
    std::vector<DocumentObject*> users {holder};
    for (auto obj : holder->getInList()) {
        if (std::find(users.begin(), users.end(), obj) == users.end()) {
            users.push_back(obj);
        }
    }
    for (auto user : users) {
        if (!user || !user->isAttachedToDocument()) {
            continue;
        }
        std::vector<Property*> props;
        user->getPropertyList(props);
        for (auto userProp : props) {
            // The ExpressionEngine, and a sheet's cells.
            auto container = freecad_cast<PropertyExpressionContainer*>(userProp);
            if (!container) {
                continue;
            }
            for (const auto& [id, expr] : container->getExpressions()) {
                if (usesProp(expr)) {
                    result.push_back({user, id});
                }
            }
        }
    }
    return result;
}

std::string VariableUse::toString(const Document* home) const
{
    if (!user || !user->isAttachedToDocument()) {
        return path.toString();
    }
    const std::string name = user->getDocument() == home ? std::string(user->getNameInDocument())
                                                          : user->getFullName();
    return name + "." + path.toString();
}

namespace
{
thread_local VariableDisplayScope* currentScope = nullptr;

// Whether an identifier's text names a document: a `#` outside `<<...>>` (a label may hold one).
bool namesDocument(const std::string& text)
{
    for (std::size_t i = 0; i < text.size(); ++i) {
        if (text[i] == '#') {
            return true;
        }
        if (text.compare(i, 2, "<<") == 0) {
            for (i += 2; i < text.size() && text.compare(i, 2, ">>") != 0; ++i) {
                if (text[i] == '\\') {
                    ++i;
                }
            }
            ++i;  // the second `>`
        }
    }
    return false;
}
}  // namespace

VariableDisplayScope::VariableDisplayScope()
    : _previous(currentScope)
{
    currentScope = this;
}

VariableDisplayScope::~VariableDisplayScope()
{
    currentScope = _previous;
}

VariableDisplayScope* VariableDisplayScope::current()
{
    return currentScope;
}

std::string VariableDisplayScope::shortForm(const DocumentObject* owner, const ObjectIdentifier& var)
{
    if (!owner || !owner->getDocument() || !var.getSubObjectName().empty()) {
        return {};
    }
    const std::string& text = var.toString();
    // getDocumentName() can't tell: it falls back to the owner's document.
    if (namesDocument(text)) {
        return {};
    }
    auto holder = var.getDocumentObject();
    if (!holder || holder->getDocument() != owner->getDocument()) {
        return {};
    }
    std::string name = var.getPropertyName();
    if (!VariableLookup::isVariable(holder, name)) {
        return {};
    }
    std::string subPath = var.getSubPathStr();
    // A bare name is the user's own way of naming a property of the owner; in the VarSet itself it
    // is also what `#Name` is stored as.
    if (text == name + subPath
        && !(holder == owner && holder->isDerivedFrom(VarSet::getClassTypeId()))) {
        return {};
    }
    const Document* doc = owner->getDocument();
    auto counts = _counts.find(doc);
    if (counts == _counts.end()) {
        counts = _counts.emplace(doc, std::map<std::string, int>()).first;
        for (const auto& ref : VariableLookup::listVariables(doc)) {
            ++counts->second[ref.name];
        }
    }
    auto count = counts->second.find(name);
    if (count == counts->second.end() || count->second != 1) {
        return {};
    }
    std::pair<std::string, std::string> entry("#" + name, VariableRef {holder, name}.path());
    if (std::find(_shortened.begin(), _shortened.end(), entry) == _shortened.end()) {
        _shortened.push_back(entry);
    }
    return entry.first + subPath;
}

std::string App::toDisplayString(
    const Expression* e,
    std::vector<std::pair<std::string, std::string>>* shortened
)
{
    if (!e) {
        return {};
    }
    VariableDisplayScope scope;
    std::string text = e->toString();
    if (shortened) {
        *shortened = scope.shortened();
    }
    return text;
}
