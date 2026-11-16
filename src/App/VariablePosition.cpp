// SPDX-License-Identifier: LGPL-2.1-or-later

#include <fmt/format.h>

#include <Base/Exception.h>

#include "VariablePosition.h"
#include "Document.h"
#include "DocumentObject.h"
#include "Expression.h"
#include "ObjectIdentifier.h"
#include "Part.h"
#include "VarSet.h"

using namespace App;

namespace
{

VariablePosition::OrderFunction& orderFunction()
{
    static VariablePosition::OrderFunction order;
    return order;
}

const VarSet* setOf(const DocumentObject* holder)
{
    return freecad_cast<const VarSet*>(holder);
}

}  // namespace

void VariablePosition::setOrder(OrderFunction order)
{
    orderFunction() = std::move(order);
}

std::string VariablePosition::anchorOf(const DocumentObject* holder, const std::string& name)
{
    const VarSet* set = setOf(holder);
    if (!set) {
        return {};
    }
    const auto& values = set->VariablePositions.getValues();
    auto it = values.find(name);
    return it == values.end() ? std::string() : it->second;
}

void VariablePosition::setAnchor(DocumentObject* holder, const std::string& name, const std::string& anchor)
{
    auto set = freecad_cast<VarSet*>(holder);
    if (!set) {
        throw Base::TypeError("only a VarSet's variables have a history position");
    }
    const std::string value = anchor.empty() ? std::string(atStart) : anchor;
    const auto& values = set->VariablePositions.getValues();
    auto it = values.find(name);
    if (it == values.end() || it->second != value) {
        set->VariablePositions.setValue(name, value);
    }
}

void VariablePosition::clearAnchor(DocumentObject* holder, const std::string& name)
{
    auto set = freecad_cast<VarSet*>(holder);
    if (set && set->VariablePositions.getValues().count(name) != 0) {
        set->VariablePositions.deleteValue(name);
    }
}

VariablePosition::Place VariablePosition::placeOf(const DocumentObject* user, const VariableRef& ref)
{
    if (!user || !ref.holder || user == ref.holder || !orderFunction()) {
        return Place::Unknown;
    }
    const std::string anchor = anchorOf(ref.holder, ref.name);
    if (anchor.empty()) {
        // No place saved (a file from before ops#723): every row of the studio sees it
        return Place::Unknown;
    }
    return orderFunction()(user, ref.holder, anchor);
}

std::string VariablePosition::checkExpression(const DocumentObject* user, const Expression& expression)
{
    if (!user || !user->getDocument() || !orderFunction()) {
        return {};
    }
    const App::Part* userStudio = nullptr;
    bool studioRead = false;
    for (const auto& [id, hidden] : expression.getIdentifiers()) {
        (void)hidden;
        const DocumentObject* holder = id.getDocumentObject();
        if (!holder || holder->getDocument() != user->getDocument()
            || !holder->isDerivedFrom<VarSet>()) {
            continue;
        }
        const std::string name = id.getPropertyName();
        if (name.empty() || !VariableLookup::isVariable(holder, name)) {
            continue;
        }
        const VariableRef ref {holder, name};
        switch (placeOf(user, ref)) {
            case Place::Before:
                return fmt::format(
                    "#{} ({}) is set after {} in the part studio's history: it can't be used "
                    "before it is set (move the variable up, or the feature down)",
                    name,
                    ref.path(),
                    user->Label.getValue()
                );
            case Place::Lost:
                return fmt::format(
                    "#{} ({}) has lost its place in the part studio's history (the feature it "
                    "followed, {}, is gone): set its place again",
                    name,
                    ref.path(),
                    anchorOf(holder, name)
                );
            default:
                break;
        }
        // An outer variable (a Variable Studio's, no part studio's) that a variable of the user's
        // own studio of the same name shadows here (DV1). Only a variable with a saved place can:
        // one at the start was preferred to the outer one when the expression was entered. The
        // studio's sets are members of its App::Part
        if (!studioRead) {
            userStudio = App::Part::getPartOfObject(user, true);
            studioRead = true;
        }
        if (!userStudio || App::Part::getPartOfObject(holder, true)) {
            continue;
        }
        for (const DocumentObject* member : userStudio->Group.getValues()) {
            if (member == holder || !member || !member->isDerivedFrom<VarSet>()
                || anchorOf(member, name).empty() || !VariableLookup::isVariable(member, name)) {
                continue;
            }
            const VariableRef other {member, name};
            if (placeOf(user, other) == Place::After) {
                return fmt::format(
                    "#{} here is the part studio's variable {} (set before {} in the history), "
                    "but the expression uses {}: enter #{} again",
                    name,
                    other.path(),
                    user->Label.getValue(),
                    ref.path(),
                    name
                );
            }
        }
    }
    return {};
}
