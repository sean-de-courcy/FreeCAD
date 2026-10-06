// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/


#include <algorithm>
#include <sstream>
#include <unordered_map>

#include <Inventor/actions/SoGetBoundingBoxAction.h>
#include <QApplication>
#include <QMenu>

#include <App/Application.h>
#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/Origin.h>
#include <App/Part.h>
#include <App/VarSet.h>
#include <Base/Console.h>
#include <Gui/ActionFunction.h>
#include <Gui/Application.h>
#include <Gui/Command.h>
#include <Gui/Document.h>
#include <Gui/MDIView.h>
#include <Gui/ViewProviderDatum.h>
#include <Mod/Part/App/PropertyTopoShape.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureSketchBased.h>
#include <Mod/PartDesign/App/FeatureBase.h>
#include <Mod/PartDesign/App/ShapeBinder.h>

#include "ViewProviderBody.h"
#include "Utils.h"
#include "ViewProvider.h"


using namespace PartDesignGui;
namespace sp = std::placeholders;

const char* PartDesignGui::ViewProviderBody::BodyModeEnum[] = {"Through", "Tip", nullptr};

namespace
{

bool hasBaseFeatureShape(const App::DocumentObject* object)
{
    if (!Part::Feature::getTopoShape(object, Part::ShapeOption::ResolveLink).isNull()) {
        return true;
    }
    auto* shapeProperty = freecad_cast<const Part::PropertyPartShape*>(
        App::GeoFeature::getPropertyOfGeometry(object)
    );
    if (shapeProperty) {
        return !shapeProperty->getShape().isNull();
    }
    return false;
}

}  // namespace

PROPERTY_SOURCE_WITH_EXTENSIONS(PartDesignGui::ViewProviderBody, PartGui::ViewProviderPart)

ViewProviderBody::ViewProviderBody()
{
    ADD_PROPERTY(DisplayModeBody, ((long)0));
    DisplayModeBody.setEnums(BodyModeEnum);

    sPixmap = "PartDesign_Body.svg";

    Gui::ViewProviderOriginGroupExtension::initExtension(this);
}

ViewProviderBody::~ViewProviderBody() = default;

void ViewProviderBody::attach(App::DocumentObject* pcFeat)
{
    // call parent attach method
    ViewProviderPart::attach(pcFeat);

    // set default display mode
    onChanged(&DisplayModeBody);

    if (App::Document* doc = pcFeat->getDocument()) {
        m_RecomputedConn = doc->signalRecomputed.connect(
            [this](const App::Document& doc, const std::vector<App::DocumentObject*>& recomputedObjs) {
                this->afterRecompute(doc, recomputedObjs);
            }
        );
    }
    m_ChangedConn = Gui::Application::Instance->signalChangedObject.connect(
        [this](const Gui::ViewProvider& vp, const App::Property& prop) {
            this->onChangedObject(vp, prop);
        }
    );
    // The edit roll-back (ops#127): every edit, of a feature, datum, binder or sketch, starts with
    // signalInEdit and ends with signalResetEdit
    m_InEditConn = Gui::Application::Instance->signalInEdit.connect(
        [this](const Gui::ViewProviderDocumentObject& vp) { this->onInEdit(vp); }
    );
    m_ResetEditConn = Gui::Application::Instance->signalResetEdit.connect(
        [this](const Gui::ViewProviderDocumentObject& vp) { this->onResetEdit(vp); }
    );
}

void ViewProviderBody::onChangedObject(const Gui::ViewProvider& vp, const App::Property& prop)
{
    static const std::unordered_set<std::string> watchedProps {"Visibility"};
    if (!watchedProps.contains(prop.getName())) {
        return;
    }
    auto* vpd = dynamic_cast<const Gui::ViewProviderDocumentObject*>(&vp);
    if (!vpd) {
        return;
    }
    auto* changedObj = vpd->getObject();
    if (!changedObj) {
        return;
    }

    auto* body = this->getObject<PartDesign::Body>();
    if (!body) {
        return;
    }
    const auto& features = body->Group.getValues();
    bool isRelevantChange = (changedObj == body)
        || (std::ranges::find(features, changedObj) != features.end());

    if (isRelevantChange) {
        refreshOverlays();
    }
}

void ViewProviderBody::afterRecompute(const App::Document& /* doc */, const std::vector<App::DocumentObject*>& /* recomputedObjs */)
{
    refreshOverlays();
}

void ViewProviderBody::refreshOverlays()
{
    auto* body = getObject<PartDesign::Body>();
    if (!body) {
        return;
    }
    for (auto* obj : body->Group.getValues()) {
        Gui::ViewProvider* vpBase = Gui::Application::Instance->getViewProvider(obj);
        if (auto* vpPartDesign = dynamic_cast<PartDesignGui::ViewProvider*>(vpBase)) {
            vpPartDesign->updateOverlay();
        }
    }
}

// TODO on activating the body switch to the "Through" mode (2015-09-05, Fat-Zer)
// TODO different icon in tree if mode is Through (2015-09-05, Fat-Zer)
// TODO drag&drop (2015-09-05, Fat-Zer)
// TODO Add activate () call (2015-09-08, Fat-Zer)

void ViewProviderBody::setDisplayMode(const char* ModeName)
{

    // if we show "Through" we must avoid to set the display mask modes, as this would result
    // in going into "tip" mode. When through is chosen the child features are displayed, and all
    // we need to ensure is that the display mode change is propagated to them from within the
    // onChanged() method.
    if (!showsThrough()) {
        PartGui::ViewProviderPartExt::setDisplayMode(ModeName);
    }
}

void ViewProviderBody::setOverrideMode(const std::string& mode)
{

    // if we are in through mode, we need to ensure that the override mode is not set for the body
    //(as this would result in "tip" mode), it is enough when the children are set to the correct
    // override mode.

    if (!showsThrough()) {
        Gui::ViewProvider::setOverrideMode(mode);
    }
    else {
        overrideMode = mode;

        // Propagate the override mode to child features.
        // When the Body is an external link, the global viewport loop
        // won't reach these children automatically.
        if (pcObject && !isRestoring()) {
            Gui::Document* gdoc = Gui::Application::Instance->getDocument(pcObject->getDocument());
            if (gdoc) {
                PartDesign::Body* body = static_cast<PartDesign::Body*>(getObject());
                auto features = body->Group.getValues();
                for (auto feature : features) {
                    if (feature && feature->isDerivedFrom<PartDesign::Feature>()) {
                        if (Gui::ViewProvider* vp = gdoc->getViewProvider(feature)) {
                            vp->setOverrideMode(mode);
                        }
                    }
                }
                if (App::DocumentObject* base = body->BaseFeature.getValue()) {
                    if (Gui::ViewProvider* vp = gdoc->getViewProvider(base)) {
                        vp->setOverrideMode(mode);
                    }
                }
            }
        }
    }
}

void ViewProviderBody::setupContextMenu(QMenu* menu, QObject* receiver, const char* member)
{
    Q_UNUSED(receiver);
    Q_UNUSED(member);
    Gui::ActionFunction* func = new Gui::ActionFunction(menu);

    QAction* act = menu->addAction(tr("Active Body"));
    act->setCheckable(true);
    act->setChecked(isActiveBody());
    func->trigger(act, [this]() { this->toggleActiveBody(); });

    Gui::ViewProviderGeometryObject::setupContextMenu(menu, receiver, member);  // clazy:exclude=skipped-base-method
}

bool ViewProviderBody::isActiveBody()
{
    auto activeDoc = Gui::Application::Instance->activeDocument();
    if (!activeDoc) {
        activeDoc = getDocument();
    }
    auto activeView = activeDoc->setActiveView(this);
    if (!activeView) {
        return false;
    }

    if (activeView->isActiveObject(getObject(), PDBODYKEY)) {
        return true;
    }
    else {
        return false;
    }
}

void ViewProviderBody::toggleActiveBody()
{
    if (isActiveBody()) {
        // active body double-clicked. Deactivate.
        Gui::Command::doCommand(
            Gui::Command::Gui,
            "Gui.ActiveDocument.ActiveView.setActiveObject('%s', None)",
            PDBODYKEY
        );
    }
    else {

        // assure the PartDesign workbench
        if (App::GetApplication()
                .GetUserParameter()
                .GetGroup("BaseApp")
                ->GetGroup("Preferences")
                ->GetGroup("Mod/PartDesign")
                ->GetBool("SwitchToWB", true)) {
            Gui::Command::assureWorkbench("PartDesignWorkbench");
        }

        // and set correct active objects
        auto* part = App::Part::getPartOfObject(getObject());
        if (part && !isActiveBody()) {
            Gui::Command::doCommand(
                Gui::Command::Gui,
                "Gui.ActiveDocument.ActiveView.setActiveObject('%s',%s)",
                PARTKEY,
                Gui::Command::getObjectCmd(part).c_str()
            );
        }

        Gui::Command::doCommand(
            Gui::Command::Gui,
            "Gui.ActiveDocument.ActiveView.setActiveObject('%s',%s)",
            PDBODYKEY,
            Gui::Command::getObjectCmd(getObject()).c_str()
        );
    }
}

bool ViewProviderBody::doubleClicked()
{
    toggleActiveBody();
    return true;
}

// TODO To be deleted (2015-09-08, Fat-Zer)
// void ViewProviderBody::updateTree()
//{
//    if (ActiveGuiDoc == NULL) return;
//
//    // Highlight active body and all its features
//    //Base::Console().error("ViewProviderBody::updateTree()\n");
//    PartDesign::Body* body = getObject<PartDesign::Body>();
//    bool active = body->IsActive.getValue();
//    //Base::Console().error("Body is %s\n", active ? "active" : "inactive");
//    ActiveGuiDoc->signalHighlightObject(*this, Gui::Blue, active);
//    std::vector<App::DocumentObject*> features = body->Group.getValues();
//    bool highlight = true;
//    App::DocumentObject* tip = body->Tip.getValue();
//    for (std::vector<App::DocumentObject*>::const_iterator f = features.begin(); f !=
//    features.end(); f++) {
//        //Base::Console().error("Highlighting %s: %s\n", (*f)->getNameInDocument(), highlight ?
//        "true" : "false"); Gui::ViewProviderDocumentObject* vp =
//        dynamic_cast<Gui::ViewProviderDocumentObject*>(Gui::Application::Instance->getViewProvider(*f));
//        if (vp != NULL)
//            ActiveGuiDoc->signalHighlightObject(*vp, Gui::LightBlue, active ? highlight : false);
//        if (highlight && (tip == *f))
//            highlight = false;
//    }
//}

bool ViewProviderBody::onDelete(const std::vector<std::string>&)
{
    // TODO May be do it conditionally? (2015-09-05, Fat-Zer)
    FCMD_OBJ_CMD(getObject(), "removeObjectsFromDocument()");
    return true;
}

void ViewProviderBody::updateData(const App::Property* prop)
{
    PartDesign::Body* body = getObject<PartDesign::Body>();

    if (prop == &body->Group || prop == &body->BaseFeature) {
        // ensure all model features are in visual body mode
        setVisualBodyMode(true);
    }

    // Rolled back, the Body shows the feature its bar follows, as in "Through" mode (ops#127)
    if ((prop == &body->Tip || prop == &body->Group) && !isRestoring()
        && showsThrough() != displayedThrough) {
        applyBodyDisplay();
    }

    if (prop == &body->Tip) {
        // We changed Tip
        App::DocumentObject* tip = body->Tip.getValue();

        auto features = body->Group.getValues();

        // restore icons
        for (auto feature : features) {
            Gui::ViewProvider* vp = Gui::Application::Instance->getViewProvider(feature);
            if (vp && vp->isDerivedFrom<PartDesignGui::ViewProvider>()) {
                static_cast<PartDesignGui::ViewProvider*>(vp)->setTipIcon(feature == tip);
            }
        }
    }

    PartGui::ViewProviderPart::updateData(prop);
}

void ViewProviderBody::onChanged(const App::Property* prop)
{

    if (prop == &DisplayModeBody) {
        applyBodyDisplay();
    }
    else {
        unifyVisualProperty(prop);
    }

    // When changing transparency then adjust the ShapeAppearance inside onChanged()
    // of the base class but don't notify its container again. This breaks the chain of
    // notification and avoids the call of onChanged() with the ShapeAppearance as argument
    // This fixes issue https://github.com/FreeCAD/FreeCAD/issues/18075
    if (prop == &Transparency) {
        ShapeAppearance.enableNotify(false);
    }

    PartGui::ViewProviderPartExt::onChanged(prop);

    if (prop == &Transparency) {
        ShapeAppearance.enableNotify(true);
    }
}

void ViewProviderBody::applyBodyDisplay()
{
    auto body = getObject<PartDesign::Body>();
    displayedThrough = showsThrough();

    if (displayedThrough) {
        // if we are in an override mode we need to make sure to come out, because
        // otherwise the maskmode is blocked and won't go into "through"
        if (getOverrideMode() != "As Is") {
            auto mode = getOverrideMode();
            ViewProvider::setOverrideMode("As Is");
            overrideMode = mode;
        }
        setDisplayMaskMode("Group");
        if (body) {
            body->setShowTip(false);
        }
    }
    else {
        if (body) {
            body->setShowTip(true);
        }
        if (getOverrideMode() == "As Is") {
            setDisplayMaskMode(DisplayMode.getValueAsString());
        }
        else {
            Base::Console().message("Set override mode: %s\n", getOverrideMode().c_str());
            setDisplayMaskMode(getOverrideMode().c_str());
        }
    }

    // #0002559: Body becomes visible upon changing DisplayModeBody
    Visibility.touch();
}

bool ViewProviderBody::showsThrough() const
{
    if (DisplayModeBody.getValue() == 0) {
        return true;
    }
    auto body = getObject<PartDesign::Body>();
    return body && body->isRolledBack();
}

int ViewProviderBody::treeBarIndex(const std::vector<App::DocumentObject*>& children) const
{
    auto body = getObject<PartDesign::Body>();
    if (!body) {
        return -1;
    }
    // Not rolled back: the bar is at the end, after every row
    if (!body->isRolledBack()) {
        return static_cast<int>(children.size());
    }
    // Rolled back: the bar sits before the first row after the bar's feature in Group (with no
    // bar feature, before the first solid feature)
    const auto& group = body->Group.getValues();
    std::size_t first = group.size();
    auto bar = body->effectiveBar();
    auto it = bar ? std::ranges::find(group, bar) : group.end();
    if (it != group.end()) {
        first = static_cast<std::size_t>(it - group.begin()) + 1;
    }
    else {
        auto solid = std::ranges::find_if(group, PartDesign::Body::isSolidFeature);
        first = static_cast<std::size_t>(solid - group.begin());
    }
    std::unordered_map<const App::DocumentObject*, std::size_t> position;
    for (std::size_t i = 0; i < group.size(); ++i) {
        position.emplace(group[i], i);
    }
    for (std::size_t i = 0; i < children.size(); ++i) {
        auto pos = position.find(children[i]);
        if (pos != position.end() && pos->second >= first) {
            return static_cast<int>(i);
        }
    }
    return static_cast<int>(children.size());
}

bool ViewProviderBody::moveTreeBar(TreeBarMove move, App::DocumentObject* child)
{
    auto body = getObject<PartDesign::Body>();
    if (!body) {
        return false;
    }
    // While a dialog holds the edit roll-back, the row shows the edit's point, not the Tip that
    // these moves step from: the bar stays put until the dialog closes (ops#127, N1 5.4)
    if (body->getEditRollPoint()) {
        return true;
    }
    const auto& group = body->Group.getValues();
    auto indexOf = [&group](const App::DocumentObject* obj) {
        return static_cast<std::size_t>(std::ranges::find(group, obj) - group.begin());
    };
    // The last solid feature before position end, or null
    auto lastSolidBefore = [&group](std::size_t end) -> App::DocumentObject* {
        for (std::size_t i = std::min(end, group.size()); i-- > 0;) {
            if (PartDesign::Body::isSolidFeature(group[i])) {
                return group[i];
            }
        }
        return nullptr;
    };

    App::DocumentObject* tip = body->Tip.getValue();
    std::size_t tipPos = indexOf(tip);
    switch (move) {
        case TreeBarMove::Before:
        case TreeBarMove::After: {
            // A row that isn't a member (the Origin) is above every feature: the top
            std::size_t pos = indexOf(child);
            if (pos >= group.size()) {
                rollBar(nullptr);
            }
            else {
                rollBar(lastSolidBefore(move == TreeBarMove::After ? pos + 1 : pos));
            }
            break;
        }
        case TreeBarMove::Up:
            if (tip && tipPos < group.size()) {
                rollBar(lastSolidBefore(tipPos));
            }
            break;
        case TreeBarMove::Down: {
            std::size_t start = tip && tipPos < group.size() ? tipPos + 1 : 0;
            for (std::size_t i = start; i < group.size(); ++i) {
                if (PartDesign::Body::isSolidFeature(group[i])) {
                    rollBar(group[i]);
                    break;
                }
            }
            break;
        }
        case TreeBarMove::Top:
            rollBar(nullptr);
            break;
        case TreeBarMove::End:
            rollBar(nullptr, true);
            break;
    }
    return true;
}

void ViewProviderBody::rollBar(App::DocumentObject* feature, bool toEnd)
{
    auto body = getObject<PartDesign::Body>();
    if (!body) {
        return;
    }
    App::DocumentObject* oldTip = body->Tip.getValue();
    int tid = body->getDocument()->openTransaction(
        toEnd ? QT_TRANSLATE_NOOP("Command", "Roll to end") : QT_TRANSLATE_NOOP("Command", "Roll to here")
    );
    try {
        if (toEnd) {
            FCMD_OBJ_CMD(body, "rollToEnd()");
        }
        else if (feature) {
            FCMD_OBJ_CMD(body, "rollTo(" << Gui::Command::getObjectCmd(feature) << ")");
        }
        else {
            FCMD_OBJ_CMD(body, "rollTo(None)");
        }
        App::DocumentObject* tip = body->Tip.getValue();
        if (tip == oldTip) {
            App::GetApplication().abortTransaction(tid);
            return;
        }
        // Show the feature the bar follows (which hides the Body's other features), or none at
        // the very top
        if (tip) {
            FCMD_OBJ_SHOW(tip);
        }
        else {
            for (auto obj : body->Group.getValues()) {
                if (PartDesign::Body::isSolidFeature(obj) && obj->Visibility.getValue()) {
                    FCMD_OBJ_HIDE(obj);
                }
            }
        }
        Gui::Command::updateActive();
        App::GetApplication().commitTransaction(tid);
    }
    catch (const Base::Exception&) {
        App::GetApplication().abortTransaction(tid);
        throw;
    }
}

App::DocumentObject* ViewProviderBody::barFeatureFor(const PartDesign::Body* body,
                                                     App::DocumentObject* member)
{
    if (PartDesign::Body::isSolidFeature(member)) {
        return member;
    }
    const auto& group = body->Group.getValues();
    std::size_t end = static_cast<std::size_t>(std::ranges::find(group, member) - group.begin());
    // The first solid feature after member that uses it, directly or through other objects
    auto users = member->getInListRecursive();
    for (std::size_t i = end + 1; i < group.size(); ++i) {
        if (PartDesign::Body::isSolidFeature(group[i]) && std::ranges::find(users, group[i]) != users.end()) {
            end = i;
            break;
        }
    }
    for (std::size_t i = std::min(end, group.size()); i-- > 0;) {
        if (PartDesign::Body::isSolidFeature(group[i])) {
            return group[i];
        }
    }
    return nullptr;
}

// The edit roll-back (ops#127, notes/reorder-rollback-design.md 5.4)

App::DocumentObject* ViewProviderBody::editRollPointFor(const PartDesign::Body* body,
                                                        App::DocumentObject* member)
{
    if (!body || !member || !body->hasObject(member)) {
        return nullptr;
    }
    if (auto feature = barFeatureFor(body, member)) {
        return feature;
    }
    // The top: the point can't be null (that is no point), so it is the member just before the
    // first solid feature, which holds every solid feature
    const auto& group = body->Group.getValues();
    auto first = std::ranges::find_if(group, PartDesign::Body::isSolidFeature);
    if (first == group.begin() || first == group.end()) {
        return nullptr;
    }
    return *(first - 1);
}

App::DocumentObject* ViewProviderBody::finalPointFor(App::DocumentObject* member) const
{
    auto body = getObject<PartDesign::Body>();
    if (!body || !PartDesign::Body::isSolidFeature(member)) {
        return nullptr;
    }
    // Would the saved bar hold member? Then Final rolls forward to it, as the edit does (N1 5.4,
    // M1 (2)); the point touches nothing, so asking holds() without it is safe
    auto saved = body->getEditRollPoint();
    body->setEditRollPoint(nullptr);
    bool held = body->holds(member);
    body->setEditRollPoint(saved);
    return held ? member : nullptr;
}

void ViewProviderBody::setEditRoll(App::DocumentObject* point)
{
    auto body = getObject<PartDesign::Body>();
    if (!body) {
        return;
    }
    auto old = body->getEditRollPoint();
    body->setEditRollPoint(point);
    if (old == body->getEditRollPoint()) {
        return;
    }
    if (showsThrough() != displayedThrough) {
        applyBodyDisplay();
    }
    // The point changes no property: tell the tree as for a Tip change, so the bar row moves and
    // the held look follows (the tree's status pass asks holds())
    if (auto gdoc = getDocument()) {
        gdoc->signalChangedObject(*this, body->Tip);
    }
}

void ViewProviderBody::onInEdit(const Gui::ViewProviderDocumentObject& vp)
{
    auto body = getObject<PartDesign::Body>();
    auto obj = vp.getObject();
    if (!body || !obj || obj == body || !body->hasObject(obj)) {
        return;
    }
    // A dialog's edit, not a transform (forwarded to the Body) or the face colours
    int mode = -1;
    if (auto gdoc = vp.getDocument()) {
        gdoc->getInEdit(nullptr, nullptr, &mode);
    }
    if (mode != Gui::ViewProvider::Default) {
        return;
    }
    editedMember = obj;
    // A feature's dialog starts with its preview group's "Show final result" as this parameter
    // says (TaskPreviewParameters)
    editFinal = PartDesign::Body::isSolidFeature(obj)
        && App::GetApplication()
               .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/PartDesign/Preview")
               ->GetBool("ShowFinal", false);
    setEditRoll(editFinal ? finalPointFor(obj) : editRollPointFor(body, obj));
}

void ViewProviderBody::onResetEdit(const Gui::ViewProviderDocumentObject& vp)
{
    auto body = getObject<PartDesign::Body>();
    if (!body || !editedMember || vp.getObject() != editedMember) {
        return;
    }
    App::DocumentObject* member = editedMember;
    editedMember = nullptr;
    editFinal = false;
    setEditRoll(nullptr);

    // What the edit touched after the point computes now, in the edit's transaction (_resetEdit
    // commits after this signal). Not inside an undo or a recompute, nor while the member or the
    // Body is being removed: then the held features stay touched for the next recompute
    App::Document* doc = body->getDocument();
    if (!doc || doc->isPerformingTransaction() || doc->testStatus(App::Document::Recomputing)
        || doc->testStatus(App::Document::Restoring) || member->isRemoving() || body->isRemoving()) {
        return;
    }
    auto touched = [](const App::DocumentObject* obj) {
        return obj->isTouched() || obj->mustRecompute();
    };
    if (touched(body) || std::ranges::any_of(body->Group.getValues(), touched)) {
        doc->recompute();
    }
}

void ViewProviderBody::setEditFinal(App::DocumentObject* member, bool final)
{
    auto body = PartDesign::Body::findBodyOf(member);
    auto vpb = body ? freecad_cast<ViewProviderBody*>(Gui::Application::Instance->getViewProvider(body))
                    : nullptr;
    if (!vpb || vpb->editedMember != member || vpb->editFinal == final) {
        return;
    }
    vpb->editFinal = final;
    vpb->setEditRoll(final ? vpb->finalPointFor(member) : editRollPointFor(body, member));
    if (!final || body->getEditRollPoint()) {
        return;
    }
    recomputeEditTail(member);
    // Show the end result: the feature the saved bar follows
    App::DocumentObject* tip = body->Tip.getValue();
    if (tip && tip != member) {
        if (auto vp = Gui::Application::Instance->getViewProvider(tip)) {
            vp->show();
        }
    }
}

void ViewProviderBody::recomputeEditTail(App::DocumentObject* member)
{
    auto body = PartDesign::Body::findBodyOf(member);
    auto vpb = body ? freecad_cast<ViewProviderBody*>(Gui::Application::Instance->getViewProvider(body))
                    : nullptr;
    if (!vpb || vpb->editedMember != member || !vpb->editFinal || body->getEditRollPoint()) {
        return;
    }
    App::Document* doc = member->getDocument();
    if (!doc || doc->testStatus(App::Document::Recomputing)) {
        return;
    }
    // The dialog recomputed member alone, which touches nothing after it
    // (Document::recomputeFeature): touch its users, as OK does, and compute the tail
    for (auto user : member->getInList()) {
        user->touch();
    }
    doc->recompute();
}

bool ViewProviderBody::reorderObjects(const std::vector<App::DocumentObject*>& objs,
                                      App::DocumentObject* target,
                                      bool after)
{
    auto body = getObject<PartDesign::Body>();
    if (!body || objs.empty()) {
        return false;
    }
    for (auto obj : objs) {
        if (!body->hasObject(obj)) {
            return false;
        }
    }
    // Dropped on the Body itself: at the bar, as a new feature is inserted (after the Tip; the
    // bar then follows the last solid dropped), or to the end when the Tip is among them
    App::DocumentObject* tip = body->Tip.getValue();
    bool atBar = !target && (!tip || body->hasObject(tip)) && std::ranges::find(objs, tip) == objs.end();
    App::DocumentObject* lastSolid = nullptr;
    if (atBar) {
        for (auto obj : body->Group.getValues()) {
            if (PartDesign::Body::isSolidFeature(obj) && std::ranges::find(objs, obj) != objs.end()) {
                lastSolid = obj;
            }
        }
        target = tip;  // null: the top (after the base feature)
        after = true;
    }
    else if (!target) {
        const auto& group = body->Group.getValues();
        auto last = std::find_if(group.rbegin(), group.rend(), [&objs](App::DocumentObject* obj) {
            return std::ranges::find(objs, obj) == objs.end();
        });
        if (last == group.rend()) {
            return true;  // nothing else to move past
        }
        target = *last;
        after = true;
    }
    else if (!body->hasObject(target)) {
        // A row that isn't a member (the Origin) is above every feature: the start
        target = nullptr;
        after = true;
    }

    std::ostringstream list;
    list << "[";
    for (auto obj : objs) {
        list << Gui::Command::getObjectCmd(obj) << ", ";
    }
    list << "]";
    FCMD_OBJ_CMD(
        body,
        "reorderObject(" << list.str() << ", "
                         << (target ? Gui::Command::getObjectCmd(target) : std::string("None"))
                         << ", " << (after ? "True" : "False") << ")"
    );
    if (atBar && lastSolid) {
        FCMD_OBJ_CMD(body, "rollTo(" << Gui::Command::getObjectCmd(lastSolid) << ")");
    }
    return true;
}

void ViewProviderBody::unifyVisualProperty(const App::Property* prop)
{

    if (!pcObject || isRestoring()) {
        return;
    }

    if (prop == &Visibility || prop == &Selectable || prop == &DisplayModeBody
        || prop == &PointColorArray || prop == &ShowPlacement || prop == &LineColorArray) {
        return;
    }

    // Fixes issue 11197. In case of affected projects where the bounding box of a sub-feature
    // is shown allow it to hide it
    if (prop == &BoundingBox) {
        if (BoundingBox.getValue()) {
            return;
        }
    }

    Gui::Document* gdoc = Gui::Application::Instance->getDocument(pcObject->getDocument());

    PartDesign::Body* body = static_cast<PartDesign::Body*>(getObject());
    auto features = body->Group.getValues();
    for (auto feature : features) {

        if (!feature->isDerivedFrom<PartDesign::Feature>()) {
            continue;
        }

        // copy over the properties data
        if (Gui::ViewProvider* vp = gdoc->getViewProvider(feature)) {
            if (auto fprop = vp->getPropertyByName(prop->getName())) {
                fprop->Paste(*prop);
            }
        }
    }
}

std::map<std::string, Base::Color> ViewProviderBody::getElementColors(const char* element) const
{
    // A PartDesign Body doesn't really have element colors on its own: it's a sort of container,
    // and its subshapes are the ones that have actual colors. If you query a body's ViewProvider
    // for its element colors, what you are really asking for is the element colors of its tip.
    PartDesign::Body* body = static_cast<PartDesign::Body*>(getObject());
    if (App::DocumentObject* tip = body->Tip.getValue()) {
        Gui::Document* guiDoc = Gui::Application::Instance->getDocument(tip->getDocument());
        Gui::ViewProvider* vp = guiDoc->getViewProvider(tip);
        return vp->getElementColors(element);
    }
    return ViewProviderPart::getElementColors(element);
}


void ViewProviderBody::setVisualBodyMode(bool bodymode)
{

    Gui::Document* gdoc = Gui::Application::Instance->getDocument(pcObject->getDocument());

    PartDesign::Body* body = static_cast<PartDesign::Body*>(getObject());
    auto features = body->Group.getValues();
    for (auto feature : features) {

        if (!feature->isDerivedFrom<PartDesign::Feature>()) {
            continue;
        }

        auto* vp = static_cast<PartDesignGui::ViewProvider*>(gdoc->getViewProvider(feature));
        if (vp) {
            vp->setBodyMode(bodymode);
        }
    }
}

std::vector<std::string> ViewProviderBody::getDisplayModes() const
{

    // we get all display modes and remove the "Group" mode, as this is what we use for "Through"
    // body display mode
    std::vector<std::string> modes = ViewProviderPart::getDisplayModes();
    modes.erase(modes.begin());
    return modes;
}

PartDesign::Feature* ViewProviderBody::getShownFeature() const
{
    auto body = static_cast<PartDesign::Body*>(getObject());
    auto features = body->Group.getValues();

    for (auto feature : features) {
        if (!feature->isDerivedFrom<PartDesign::Feature>()) {
            continue;
        }

        if (feature->Visibility.getValue()) {
            return static_cast<PartDesign::Feature*>(feature);
        }
    }

    return nullptr;
}

Gui::ViewProvider* ViewProviderBody::getShownViewProvider() const
{
    if (const auto* feature = getShownFeature()) {
        return Gui::Application::Instance->getViewProvider(feature);
    }

    return nullptr;
}

bool ViewProviderBody::canDropObjects() const
{
    // if the BaseFeature property is marked as hidden or read-only then
    // it's not allowed to modify it.
    auto* body = getObject<PartDesign::Body>();
    if (body->BaseFeature.testStatus(App::Property::Status::Hidden)
        || body->BaseFeature.testStatus(App::Property::Status::ReadOnly)) {
        return false;
    }
    return true;
}

bool ViewProviderBody::canDropObject(App::DocumentObject* obj) const
{
    // The Body's own members are dropped among its rows to reorder them (ops#127). A copy
    // drag of an own solid can't be done (dropObject() refuses it), so the cursor refuses it too
    if (getObject<PartDesign::Body>()->hasObject(obj)) {
#ifdef Q_OS_MACOS
        constexpr auto copyModifier = Qt::AltModifier;
#else
        constexpr auto copyModifier = Qt::ControlModifier;
#endif
        return !PartDesign::Body::isSolidFeature(obj)
            || !(QApplication::queryKeyboardModifiers() & copyModifier);
    }
    if (obj->isDerivedFrom<App::VarSet>()) {
        return true;
    }
    else if (obj->isDerivedFrom<App::DatumElement>()) {
        // accept only datums that are not part of a LCS.
        auto* lcs = static_cast<App::DatumElement*>(obj)->getLCS();
        return !lcs;
    }
    else if (obj->isDerivedFrom<App::LocalCoordinateSystem>()) {
        return !obj->isDerivedFrom<App::Origin>();
    }
    else if (obj->isDerivedFrom<PartDesign::SubShapeBinder>()) {
        return true;
    }
    else if (obj->isDerivedFrom<Part::Part2DObject>()) {
        return true;
    }
    else if (!hasBaseFeatureShape(obj)) {
        return false;
    }
    else if (PartDesign::Body::findBodyOf(obj)) {
        return false;
    }
    else if (obj->isDerivedFrom(Part::BodyBase::getClassTypeId())) {
        return false;
    }

    return true;
}

void ViewProviderBody::dropObject(App::DocumentObject* obj)
{
    auto* body = getObject<PartDesign::Body>();
    // An own solid reaches here only from a copy drag or a drag mixed with other objects; a
    // reorder is a plain drag of the Body's own rows (ops#127)
    if (body->hasObject(obj) && PartDesign::Body::isSolidFeature(obj)) {
        throw Base::RuntimeError(
            QT_TRANSLATE_NOOP("Exception", "Drag the feature alone, without Ctrl, to reorder it")
        );
    }
    if (obj->isDerivedFrom<Part::Part2DObject>() || obj->isDerivedFrom<App::DatumElement>()
        || obj->isDerivedFrom<App::LocalCoordinateSystem>()) {
        body->addObject(obj);
    }
    else if (PartDesign::Body::isAllowed(obj) && PartDesignGui::isFeatureMovable(obj)) {
        std::vector<App::DocumentObject*> move;
        move.push_back(obj);
        std::vector<App::DocumentObject*> deps = PartDesignGui::collectMovableDependencies(move);
        move.insert(std::end(move), std::begin(deps), std::end(deps));

        PartDesign::Body* source = PartDesign::Body::findBodyOf(obj);
        if (source) {
            source->removeObjects(move);
        }
        try {
            body->addObjects(move);
        }
        catch (const Base::Exception& e) {
            e.reportException();
        }
    }
    else if (!body->BaseFeature.getValue()) {
        body->BaseFeature.setValue(obj);
    }

    App::Document* doc = body->getDocument();
    doc->recompute();

    // check if a proxy object has been created for the base feature
    std::vector<App::DocumentObject*> links = body->Group.getValues();
    for (auto it : links) {
        if (it->isDerivedFrom<PartDesign::FeatureBase>()) {
            PartDesign::FeatureBase* base = static_cast<PartDesign::FeatureBase*>(it);
            if (base && base->BaseFeature.getValue() == obj) {
                Gui::Application::Instance->hideViewProvider(obj);
                break;
            }
        }
    }
}

bool ViewProviderBody::canDragObjectToTarget(App::DocumentObject* obj, App::DocumentObject* target) const
{
    if (obj->isDerivedFrom<PartDesign::Feature>()) {
        return target && target->is<PartDesign::Body>();
    }

    return ViewProviderPart::canDragObjectToTarget(obj, target);
}

void ViewProviderBody::show()
{
    // Call the base version first to ensure normal behavior
    PartGui::ViewProviderPart::show();

    auto* body = static_cast<PartDesign::Body*>(getObject());

    auto tip = body->Tip.getValue();
    if (!tip || tip->Visibility.getValue()) {
        return;
    }

    auto features = body->Group.getValues();
    if (features.empty()) {
        return;
    }

    bool foundVisible = false;
    for (const auto feature : features) {
        if (!feature) {
            continue;
        }

        auto vp = Gui::Application::Instance->getViewProvider(feature);
        if (!vp) {
            continue;
        }

        if (vp->isDerivedFrom(PartDesignGui::ViewProvider::getClassTypeId())) {
            if (feature->Visibility.getValue()) {
                foundVisible = true;
                break;
            }
        }
    }

    if (!foundVisible) {
        tip->Visibility.setValue(true);
    }
}
