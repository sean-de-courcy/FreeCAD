// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#include <algorithm>
#include <sstream>

#include <QCoreApplication>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <Base/Exception.h>
#include <Gui/Application.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>
#include <Gui/ViewProvider.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/PartDesign/App/Body.h>

#include "ReferenceActions.h"
#include "ViewProviderBody.h"

using namespace PartDesignGui;

namespace
{

// The Python string literal of an ASCII name.
std::string quoted(const std::string& name)
{
    std::string text = "'";
    for (char c : name) {
        if (c == '\'' || c == '\\') {
            text += '\\';
        }
        text += c;
    }
    return text + "'";
}

std::string call(const char* function,
                 const App::DocumentObject* owner,
                 const std::string& property,
                 int index,
                 const std::string& tail = std::string())
{
    std::ostringstream str;
    str << "App." << function << "(" << Gui::Command::getObjectCmd(owner) << ", "
        << quoted(property) << ", " << index << tail << ")";
    return str.str();
}

}  // namespace

std::string ReferenceActions::acceptCommand(const App::DocumentObject* owner,
                                            const std::string& property,
                                            int index)
{
    return call("acceptReference", owner, property, index);
}

std::string ReferenceActions::useCommand(const App::DocumentObject* owner,
                                         const std::string& property,
                                         int index,
                                         const std::string& element)
{
    return call("repairReference", owner, property, index, ", " + quoted(element));
}

std::string ReferenceActions::markBrokenCommand(const App::DocumentObject* owner,
                                                const std::string& property,
                                                int index)
{
    return call("markReferenceBroken", owner, property, index);
}

std::string ReferenceActions::repickCommand(const App::DocumentObject* owner,
                                            const std::string& property,
                                            int index,
                                            const std::string& element)
{
    return call("repairReference", owner, property, index, ", " + quoted(element) + ", True");
}

bool ReferenceActions::run(App::DocumentObject* owner, const std::string& command, QString* error)
{
    if (!owner || !owner->isAttachedToDocument()) {
        return false;
    }
    App::Document* doc = owner->getDocument();
    if (!doc->hasPendingTransaction() && doc->getBookedTransactionID() == App::NullTransaction) {
        doc->openTransaction(QT_TRANSLATE_NOOP("Command", "Repair references"));
    }
    try {
        Gui::Command::runCommand(Gui::Command::Doc, command.c_str());
    }
    catch (const Base::Exception& e) {
        if (error) {
            *error = QString::fromUtf8(e.what());
        }
        return false;
    }
    try {
        Gui::cmdAppDocument(doc, "recompute()");
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
    return true;
}

bool ReferenceActions::hasGuess(const App::ReferenceRow& row)
{
    return !row.guessKind.empty() && row.guessKind != "rejected";
}

std::string ReferenceActions::heldElement(const App::ReferenceRow& row)
{
    const char* element = Data::findElementName(row.sub.c_str());
    if (!element || !element[0] || Data::hasMissingElement(element)) {
        return {};
    }
    return element;
}

std::string ReferenceActions::elementType(const std::string& name)
{
    std::string type;
    for (char c : name) {
        if (c == '?') {
            continue;
        }
        if (c >= '0' && c <= '9') {
            break;
        }
        type += c;
    }
    return type;
}

std::string ReferenceActions::subElementType(const std::string& sub)
{
    const char* element = Data::findElementName(sub.c_str());
    return elementType(Data::oldElementName(element ? element : sub.c_str()));
}

TargetDisplay::~TargetDisplay()
{
    restore();
}

void TargetDisplay::show(App::DocumentObject* target)
{
    if (shownTarget.getObject() == target) {
        return;
    }
    restore();
    Gui::ViewProvider* vp = Gui::Application::Instance->getViewProvider(target);
    if (!vp || vp->isShow()) {
        return;
    }
    // In a body only one solid shows: hide it while its predecessor is shown.
    if (auto body = PartDesign::Body::findBodyOf(target)) {
        auto bodyVp = Gui::Application::Instance->getViewProvider<ViewProviderBody>(body);
        if (Gui::ViewProvider* shownVp = bodyVp ? bodyVp->getShownViewProvider() : nullptr) {
            if (auto docVp = freecad_cast<Gui::ViewProviderDocumentObject*>(shownVp)) {
                hiddenFeature = docVp->getObject();
                shownVp->hide();
            }
        }
    }
    vp->show();
    shownTarget = target;
}

void TargetDisplay::restore()
{
    if (auto target = shownTarget.getObject()) {
        if (auto vp = Gui::Application::Instance->getViewProvider(target)) {
            vp->hide();
        }
    }
    if (auto feature = hiddenFeature.getObject()) {
        if (auto vp = Gui::Application::Instance->getViewProvider(feature)) {
            vp->show();
        }
    }
    forget();
}

void TargetDisplay::forget()
{
    shownTarget = App::DocumentObjectT();
    hiddenFeature = App::DocumentObjectT();
}

EditVisibility::~EditVisibility()
{
    restore();
}

void EditVisibility::show(App::DocumentObject* obj)
{
    Gui::ViewProvider* vp = obj ? Gui::Application::Instance->getViewProvider(obj) : nullptr;
    if (!vp) {
        return;
    }
    const bool known = std::ranges::any_of(shown, [obj](const auto& entry) {
        return entry.first.getObject() == obj;
    });
    if (!known) {
        shown.emplace_back(obj, vp->isShow());
    }
    vp->show();
}

void EditVisibility::restore()
{
    // An object gone with the edit (Cancel undid its creation) is skipped
    for (const auto& [objT, visible] : shown) {
        App::DocumentObject* obj = objT.getObject();
        Gui::ViewProvider* vp = obj ? Gui::Application::Instance->getViewProvider(obj) : nullptr;
        if (vp) {
            vp->setVisible(visible);
        }
    }
    shown.clear();
}
