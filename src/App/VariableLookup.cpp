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

#include "VariableLookup.h"

#include "Document.h"
#include "DocumentObject.h"
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
