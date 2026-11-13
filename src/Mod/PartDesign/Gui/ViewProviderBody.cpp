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
#include <set>
#include <sstream>
#include <map>
#include <memory>
#include <unordered_map>
#include <unordered_set>

#include <Inventor/actions/SoGetBoundingBoxAction.h>
#include <Inventor/nodes/SoGroup.h>
#include <Inventor/nodes/SoSeparator.h>
#include <Inventor/nodes/SoSwitch.h>
#include <QApplication>
#include <QMenu>

#include <App/Application.h>
#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/Origin.h>
#include <App/Datums.h>
#include <App/GroupExtension.h>
#include <App/Part.h>
#include <App/VarSet.h>
#include <Base/Console.h>
#include <Gui/ActionFunction.h>
#include <Gui/Application.h>
#include <Gui/Command.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/ForkKeymap.h>
#include <Gui/MainWindow.h>
#include <Gui/MDIView.h>
#include <Gui/Selection/Selection.h>
#include <Gui/ViewProviderDatum.h>
#include <Mod/Part/App/DatumFeature.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/PropertyTopoShape.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureBoolean.h>
#include <Mod/PartDesign/App/FeatureDeletePart.h>
#include <Mod/PartDesign/App/FeatureTransformed.h>
#include <Mod/PartDesign/App/FeatureSketchBased.h>
#include <Mod/PartDesign/App/FeatureBase.h>
#include <Mod/PartDesign/App/FeatureMultiTransform.h>
#include <Mod/PartDesign/App/ShapeBinder.h>
#include <Mod/PartDesign/App/Studio.h>
#include <Mod/PartDesign/App/StudioList.h>

#include "ViewProviderBody.h"
#include "RollbackView.h"
#include "TaskDeletePart.h"
#include "Utils.h"
#include "ViewProvider.h"


using namespace PartDesignGui;
namespace sp = std::placeholders;

namespace PartDesign
{
// App/StudioList.cpp (ops#654 T1a; declared where used)
PartDesignExport bool isStudioFeaturePattern(const App::DocumentObject* obj);
}  // namespace PartDesign

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

// Recomputes objs (none: every touched object), reporting an exception instead of throwing it
void recomputeReporting(App::Document* doc, const std::vector<App::DocumentObject*>& objs = {})
{
    try {
        doc->recompute(objs);
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
    catch (const std::exception& e) {
        Base::Console().error("%s\n", e.what());
    }
}

// Why a move of the bar or a reorder is refused during an edit (ViewProviderBody::isEditLocked)
constexpr const char* editLockedMessage =
    QT_TRANSLATE_NOOP("Exception", "The body can't change order or roll back while a dialog or an edit is open");

// Why an own solid isn't dropped on its Body in a copy drag or with other objects (dropObject)
constexpr const char* dragAloneMessage =
    QT_TRANSLATE_NOOP("Exception", "Drag the feature alone, without Ctrl, to reorder it");

/** FreeCAD-CH (ops#640 rank 32, lists plan 8): while member, a member of another Body of other's
 * part studio, is edited, other is rolled back to it as Onshape rolls every part back to the
 * feature edited: the edit roll point after other's last solid feature at or above member in the
 * studio's history (studioSequence(), as rollStudioTo() puts the bar), or at its top the member
 * just before its first solid feature. Null when that holds nothing its bar doesn't hold already
 * (never forward: a held feature may not be computed), or it can't be held (other's first member
 * is a solid feature), or other isn't in member's studio
 */
/** FreeCAD-CH (ops#654 S4): while owner, a studio feature (outside every Body), is edited, other
 * is rolled back to the owner's place in the studio's list: after other's last solid feature
 * before it (a step of an earlier owner, or a member), the owner's own step held, or at its top
 * the member just before its first solid feature. Unlike a member's edit the point is kept when it
 * holds nothing yet: a part ticked in the dialog gets its step after it, held too. Null when
 * other isn't in the owner's studio, its first member is a solid feature, or its saved bar holds
 * as much already. A pattern over parts (ops#654 T1a) shows what it makes: its steps are
 * above the point (an in-Body pattern's edit point is the pattern itself)
 */
App::DocumentObject* studioOwnerEditPointFor(const PartDesign::Body* other, const App::DocumentObject* owner)
{
    const PartDesign::StudioList* list = PartDesign::StudioList::holding(owner);
    App::Part* otherStudio = nullptr;
    if (!list || !other || other->getDocument() != owner->getDocument()
        || !Part::BodyBase::studioOf(other, otherStudio) || otherStudio != list->studio()) {
        return nullptr;
    }
    std::unordered_set<const App::DocumentObject*> above;
    bool found = false;
    for (auto entry : list->Entries.getValues()) {
        if (entry == owner) {
            found = true;
            if (PartDesign::isStudioFeaturePattern(owner)) {
                for (auto step : PartDesign::StudioList::stepsOf(owner)) {
                    above.insert(step);
                }
            }
            break;
        }
        if (!entry) {
            continue;
        }
        above.insert(entry);
        for (auto step : PartDesign::StudioList::stepsOf(entry)) {
            above.insert(step);
        }
    }
    if (!found) {
        return nullptr;
    }
    const auto& group = other->Group.getValues();
    auto indexOf = [&group](const App::DocumentObject* obj) {
        return static_cast<std::size_t>(std::ranges::find(group, obj) - group.begin());
    };
    App::DocumentObject* point = nullptr;
    for (auto obj : group) {
        if (above.count(obj) && PartDesign::Body::isSolidFeature(obj)) {
            point = obj;
        }
    }
    if (!point) {
        auto first = std::ranges::find_if(group, PartDesign::Body::isSolidFeature);
        if (first == group.begin() || first == group.end()) {
            return nullptr;
        }
        point = *(first - 1);
    }
    if (other->isRolledBack()) {
        App::DocumentObject* tip = other->Tip.getValue();
        if (!tip || indexOf(tip) <= indexOf(point)) {
            return nullptr;
        }
    }
    return point;
}

App::DocumentObject* studioEditPointFor(const PartDesign::Body* other, const App::DocumentObject* member)
{
    if (member && PartDesign::isStudioOwner(member)) {
        return studioOwnerEditPointFor(other, member);
    }
    auto body = member ? PartDesign::Body::findBodyOf(member) : nullptr;
    if (!other || !body || body == other || body->getDocument() != other->getDocument()) {
        return nullptr;
    }
    App::Part* studio = nullptr;
    App::Part* otherStudio = nullptr;
    if (!Part::BodyBase::studioOf(body, studio) || !Part::BodyBase::studioOf(other, otherStudio)
        || studio != otherStudio) {
        return nullptr;
    }
    const auto sequence = PartDesign::studioSequence(body->getDocument(), studio);
    auto at = std::ranges::find(sequence, member);
    if (at == sequence.end()) {
        return nullptr;
    }
    const std::unordered_set<const App::DocumentObject*> above(sequence.begin(), at);
    const auto& group = other->Group.getValues();
    auto indexOf = [&group](const App::DocumentObject* obj) {
        return static_cast<std::size_t>(std::ranges::find(group, obj) - group.begin());
    };
    App::DocumentObject* point = nullptr;
    for (auto obj : group) {
        if (above.count(obj) && PartDesign::Body::isSolidFeature(obj)) {
            point = obj;
        }
    }
    if (point && point == other->lastSolidFeature()) {
        return nullptr;
    }
    if (!point) {
        auto first = std::ranges::find_if(group, PartDesign::Body::isSolidFeature);
        if (first == group.begin() || first == group.end()) {
            return nullptr;
        }
        point = *(first - 1);
    }
    // Rolled back already at or above the point: the saved bar holds as much
    if (other->isRolledBack()) {
        App::DocumentObject* tip = other->Tip.getValue();
        if (!tip || indexOf(tip) <= indexOf(point)) {
            return nullptr;
        }
    }
    return point;
}

/// The scene of each Body rolled back with its studio's edit (studioEditPointFor()), by its view
/// provider; never destroyed (a view at exit would restore view providers already gone)
std::map<const PartDesignGui::ViewProviderBody*, std::unique_ptr<PartDesignGui::RollbackView>>& studioRollbacks()
{
    static auto* views =
        new std::map<const PartDesignGui::ViewProviderBody*, std::unique_ptr<PartDesignGui::RollbackView>>();
    return *views;
}

/// Shows body at its edit roll point in the scene (RollbackView::showBodyAt()): the point's solid,
/// or nothing of it at its top
void showStudioRollback(const PartDesignGui::ViewProviderBody* vpb, PartDesign::Body* body)
{
    App::DocumentObject* point = body->getEditRollPoint();
    if (!point || !vpb->isShow()) {
        studioRollbacks().erase(vpb);
        return;
    }
    auto& view = studioRollbacks()[vpb];
    if (!view) {
        view = std::make_unique<PartDesignGui::RollbackView>();
    }
    view->showBodyAt(body, PartDesign::Body::isSolidFeature(point) ? point : nullptr);
}

/// A dialog of a solid feature starts in Final as its preview group's parameter says
/// (TaskPreviewParameters, ViewProviderBody::onInEdit())
bool editStartsFinal(const App::DocumentObject* obj)
{
    return PartDesign::Body::isSolidFeature(obj)
        && App::GetApplication()
               .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/PartDesign/Preview")
               ->GetBool("ShowFinal", false);
}

/* FreeCAD-CH (ops#654 P3a, report 20, notes/parts-design.md 3.4): in Onshape a part studio's
 * sketches and planes belong to the studio, so hiding a part leaves them shown. A Body still
 * claims its sketches and datums (in the tree and in 3D: their selection paths stay
 * Studio.Body.Sketch.), and while the Body is hidden in a part studio a switch after its mode
 * switch shows their root nodes: each shows as its own Visibility says, the sketch a feature uses
 * hidden as before. Gui::ViewProviderDocumentObject picks and highlights a child through it
 * (shownOutsideSwitch there). Nothing is saved: the switch is rebuilt from the Body's state.
 */
constexpr const char* studioShownName = "StudioShown";

/// The switch of the Body's root that shows its sketches and datums while it is hidden, or null
SoSwitch* studioShownSwitch(SoSeparator* root)
{
    for (int i = 0, count = root ? root->getNumChildren() : 0; i < count; ++i) {
        SoNode* node = root->getChild(i);
        if (node->isOfType(SoSwitch::getClassTypeId()) && node->getName() == studioShownName) {
            return static_cast<SoSwitch*>(node);
        }
    }
    return nullptr;
}

/// A member that belongs to the part studio, not to the part: a sketch, a datum, a coordinate
/// system (the Body's Origin included)
bool isStudioOwned(const App::DocumentObject* obj)
{
    return obj
        && (obj->isDerivedFrom<Part::Part2DObject>() || obj->isDerivedFrom<Part::Datum>()
            || obj->isDerivedFrom<App::DatumElement>()
            || obj->isDerivedFrom<App::LocalCoordinateSystem>());
}

/// Shows the Body's studio-owned members (isStudioOwned) while the Body is hidden in a part
/// studio, in "Through" (its members shown one by one); shows none otherwise
void updateStudioShown(PartDesignGui::ViewProviderBody* vpb)
{
    SoSwitch* shown = studioShownSwitch(vpb->getRoot());
    auto body = vpb->getObject<PartDesign::Body>();
    if (!shown || shown->getNumChildren() != 1 || !body) {
        return;
    }
    auto group = static_cast<SoGroup*>(shown->getChild(0));
    std::vector<SoNode*> roots;
    App::Part* studio = nullptr;
    Gui::Document* gdoc = vpb->getDocument();
    if (gdoc && !vpb->isRestoring() && !vpb->Visibility.getValue() && !vpb->isShow()
        && body->isAttachedToDocument() && !body->isRemoving() && vpb->showsThrough()
        && Part::BodyBase::studioOf(body, studio)) {
        std::vector<App::DocumentObject*> members = body->Group.getValues();
        members.push_back(body->Origin.getValue());
        for (auto obj : members) {
            if (!isStudioOwned(obj) || !obj->isAttachedToDocument() || obj->isRemoving()) {
                continue;
            }
            auto vp = gdoc->getViewProvider(obj);
            if (vp && vp->getRoot()) {
                roots.push_back(vp->getRoot());
            }
        }
    }
    // Touch the scene only on a change: each one notifies every view
    bool same = group->getNumChildren() == static_cast<int>(roots.size());
    for (int i = 0; same && i < group->getNumChildren(); ++i) {
        same = group->getChild(i) == roots[i];
    }
    if (!same) {
        Gui::coinRemoveAllChildren(group);
        for (auto root : roots) {
            group->addChild(root);
        }
    }
    int which = roots.empty() ? SO_SWITCH_NONE : 0;
    if (shown->whichChild.getValue() != which) {
        shown->whichChild = which;
    }
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

ViewProviderBody::~ViewProviderBody()
{
    // A studio roll-back of this Body's scene goes with it, putting nothing back: the view
    // providers it would restore may be gone already (ops#640 rank 32)
    auto& views = studioRollbacks();
    if (auto it = views.find(this); it != views.end()) {
        static_cast<void>(it->second.release());
        views.erase(it);
    }
}

void ViewProviderBody::attach(App::DocumentObject* pcFeat)
{
    // call parent attach method
    ViewProviderPart::attach(pcFeat);

    // The sketches and datums shown while the Body is hidden in a part studio (ops#654 P3a,
    // updateStudioShown): after the mode switch, under the Body's placement
    auto shown = new SoSwitch();
    shown->setName(studioShownName);
    shown->addChild(new SoGroup());
    shown->whichChild = SO_SWITCH_NONE;
    pcRoot->addChild(shown);

    // set default display mode
    onChanged(&DisplayModeBody);

    if (App::Document* doc = pcFeat->getDocument()) {
        m_RecomputedConn = doc->signalRecomputed.connect(
            [this](const App::Document& doc, const std::vector<App::DocumentObject*>& recomputedObjs) {
                this->afterRecompute(doc, recomputedObjs);
            }
        );
        // After the step's regeneration (ops#640: App::Document regenerates before it signals)
        m_UndoConn = doc->signalUndo.connect([this](const App::Document& doc) {
            this->afterUndoRedo(doc);
        });
        m_RedoConn = doc->signalRedo.connect([this](const App::Document& doc) {
            this->afterUndoRedo(doc);
        });
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

void ViewProviderBody::afterUndoRedo(const App::Document& doc)
{
    // FreeCAD-CH (ops#640, F35): an undo or a redo restores the features' Visibility as the step
    // recorded it: a Body that then shows none of its features shows its Tip, so no step leaves
    // the view empty (as showTipIfNoneShown() at a dialog's close, ops#212). Not while an edit
    // owns the display, nor for a hidden Body or one rolled back to the top (no Tip). Only when
    // the step changed what the Body shows (its Group, Tip or a member's Visibility): an
    // unrelated undo doesn't show a Tip the user hid, as Onshape's undo doesn't touch hide/show
    bool changedShown = undoChangedShown;
    undoChangedShown = false;
    auto body = getObject<PartDesign::Body>();
    if (!body || !body->isAttachedToDocument() || body->getDocument() != &doc) {
        return;
    }
    // The step's regeneration may have stopped or repaired the Body (F37)
    updateStoppedDisplay();
    if (!changedShown || !body->Visibility.getValue()) {
        return;
    }
    auto gdoc = Gui::Application::Instance->getDocument(body->getDocument());
    if (gdoc && gdoc->getInEdit()) {
        return;
    }
    App::DocumentObject* tip = body->Tip.getValue();
    if (!tip || !body->hasObject(tip)) {
        return;
    }
    bool shown = std::ranges::any_of(body->Group.getValues(), [](App::DocumentObject* obj) {
        return obj && obj->isDerivedFrom<PartDesign::Feature>() && obj->Visibility.getValue();
    });
    if (!shown) {
        tip->Visibility.setValue(true);
    }
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
        if (body->getDocument() && body->getDocument()->isPerformingTransaction()) {
            undoChangedShown = true;
        }
        refreshOverlays();
    }
}

void ViewProviderBody::afterRecompute(const App::Document& /* doc */, const std::vector<App::DocumentObject*>& /* recomputedObjs */)
{
    updateStoppedDisplay();
    refreshOverlays();
}

bool ViewProviderBody::isStopped() const
{
    // F37 (ops#640): stopped by the recompute, the Body has written the empty Shape and is in
    // error (Body::writeStoppedShape). Not while rolled back (the bar's feature shows, Through)
    // nor while a member's dialog or edit is open: the edit's display and preview stay
    auto body = getObject<PartDesign::Body>();
    return body && !editedMember && body->isError() && body->Shape.getShape().isNull()
        && !body->isRolledBack();
}

void ViewProviderBody::updateStoppedDisplay()
{
    if (!isRestoring() && showsThrough() != displayedThrough) {
        applyBodyDisplay();
    }
}

void ViewProviderBody::finishRestoring()
{
    PartGui::ViewProviderPart::finishRestoring();
    // A file saved with a stopped Body (its error and empty Shape saved) opens showing nothing
    updateStoppedDisplay();
    // A file saved with the Body hidden opens with its studio's sketches and datums shown
    updateStudioShown(this);
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
    // A part of a studio: deleting it is a feature in its history, Onshape's Delete part (ops#635,
    // notes/part-history-design.md 3.2). Its features stay; rolling above the feature, deleting it
    // or undo brings the part back. A Body in no studio (an Assembly's), one that is no part (no
    // solid feature above its bar), or one deleted as a part already, is deleted with its features
    auto body = getObject<PartDesign::Body>();
    App::Part* studio = nullptr;
    // Std_Delete asked "the referencing objects might break" about this Body (a binder or link
    // reads it whole, an expression reads it): its Yes removes the Body whatever this returns, so
    // the Body's features go with it, as before; a Delete part there would be left in no Body
    // (reviews prs464e2-r1 T2/T5, r2 R2-1, r3 R3-1). Its test: a parent not being deleted (not
    // selected; one deleted already has left the in-list) whose view provider refuses
    auto selected = Gui::Selection().getObjectsOfType(App::DocumentObject::getClassTypeId());
    std::set<const App::DocumentObject*> deleting(selected.begin(), selected.end());
    bool forced = body && std::ranges::any_of(body->getInList(), [&](App::DocumentObject* parent) {
        if (!parent || deleting.count(parent) != 0) {
            return false;
        }
        auto vp = Gui::Application::Instance->getViewProvider(parent);
        return vp && !vp->canDelete(body);
    });
    // Every feature of the Body is deleted with it (a range in the tree, Ctrl+A): nothing is left
    // for a Delete part to keep, so the Body goes too, in either selection order (review s33e2
    // F1). A MultiTransform's steps go with their MultiTransform
    bool everyMember = body && std::ranges::all_of(body->Group.getValues(), [&](App::DocumentObject* obj) {
        auto step = freecad_cast<PartDesign::Transformed*>(obj);
        return !obj || deleting.count(obj) != 0 || (step && step->isOutOfChain());
    });
    // A part deleted already, deleted again: the Body goes with its features (review s33e2 F2)
    bool deleted = body && PartDesign::DeletePart::deleterOf(body);
    if (body && !forced && !everyMember && !deleted && Part::BodyBase::studioOf(body, studio)
        && body->Tip.getValue() && !PartDesign::Boolean::mergeOf(body)) {
        // Under the Onshape keymap, its dialog, prefilled with the part (with the other parts of
        // the same Delete): OK makes the feature (ops#640 rank 30, blind test F48)
        if (Gui::ForkKeymap::isOnshape()) {
            TaskDlgDeletePart::openFor(body);
            return false;
        }
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "PartDesign.deletePart(%s)",
            Gui::Command::getObjectCmd(body).c_str()
        );
        // Std_Delete recomputes only where it removed something
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.getDocument('%s').recompute()",
            body->getDocument()->getName()
        );
        return false;
    }
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
    // F37 (ops#640): a repair writes the Body's Shape again; show its members at once
    if (prop == &body->Shape) {
        updateStoppedDisplay();
    }
    // An undo or a redo that restores or removes a member, or moves the Tip (afterUndoRedo)
    if ((prop == &body->Tip || prop == &body->Group) && body->getDocument()
        && body->getDocument()->isPerformingTransaction()) {
        undoChangedShown = true;
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

    // A member added or removed, while hidden: before a removed member's view provider goes
    // (ops#654 P3a)
    if (prop == &body->Group || prop == &body->Origin) {
        updateStudioShown(this);
    }
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

    // Hidden or shown, or "Through" on or off (applyBodyDisplay touches Visibility): the studio's
    // sketches and datums stay shown while the Body is hidden (ops#654 P3a)
    if (prop == &Visibility || prop == &DisplayModeBody) {
        updateStudioShown(this);
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
    auto body = getObject<PartDesign::Body>();
    if (body && body->isRolledBack()) {
        return true;
    }
    // F37 (ops#640): a stopped Body shows its own Shape, the empty one, in place of its members,
    // whose last shapes would show a part the model no longer makes (Onshape shows none)
    return DisplayModeBody.getValue() == 0 && !isStopped();
}

bool ViewProviderBody::isEditLocked(App::Document* doc)
{
    auto gdoc = doc ? Gui::Application::Instance->getDocument(doc) : nullptr;
    return gdoc && (gdoc->getEditViewProvider() || !Gui::Control().isAllowedAlterDocument(doc));
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
    // While a dialog or an edit is open (the edit roll-back's row shows the edit's point, not the
    // Tip these moves step from) rollBar() refuses; the tree refuses first (ops#127, N1 5.4)
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
    // Its transaction would commit an open edit's: Cancel couldn't take the edit back
    if (isEditLocked(body->getDocument())) {
        throw Base::RuntimeError(editLockedMessage);
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
    // A pattern of features with no originals yet isn't a solid feature (it looks like a
    // MultiTransform's step), but it becomes one when the edit adds them: the point is the
    // pattern itself, or the edit would hold it until it ends (ops#182). A MultiTransform's step
    // keeps the rule below.
    if (auto pattern = freecad_cast<PartDesign::Transformed*>(member)) {
        auto stepOf = [pattern](App::DocumentObject* obj) {
            auto multi = freecad_cast<PartDesign::MultiTransform*>(obj);
            return multi && std::ranges::find(multi->Transformations.getValues(), pattern)
                != multi->Transformations.getValues().end();
        };
        if (!PartDesign::Body::isSolidFeature(member) && std::ranges::none_of(member->getInList(), stepOf)) {
            return member;
        }
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
    // the held look follows (the tree's status pass asks holds()). Other observers of
    // signalChangedObject, Python ones too, see it as a change of the Tip that leaves its value
    if (auto gdoc = getDocument()) {
        gdoc->signalChangedObject(*this, body->Tip);
    }
}

void ViewProviderBody::onInEdit(const Gui::ViewProviderDocumentObject& vp)
{
    auto body = getObject<PartDesign::Body>();
    auto obj = vp.getObject();
    if (!body || !obj || obj == body) {
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
    if (!body->hasObject(obj)) {
        // FreeCAD-CH (ops#640 rank 32, lists plan 8): a member of another Body of this Body's
        // part studio is edited; this Body rolls back to it too, unless the dialog starts in Final
        if (!editStartsFinal(obj)) {
            if (auto point = studioEditPointFor(body, obj)) {
                setEditRoll(point);
                showStudioRollback(this, body);
            }
        }
        return;
    }
    editedMember = obj;
    // A feature's dialog starts with its preview group's "Show final result" as this parameter
    // says (TaskPreviewParameters)
    editFinal = editStartsFinal(obj);
    setEditRoll(editFinal ? finalPointFor(obj) : editRollPointFor(body, obj));
    // A stopped Body shows its members again while the edit is open (isStopped)
    updateStoppedDisplay();
}

void ViewProviderBody::onResetEdit(const Gui::ViewProviderDocumentObject& vp)
{
    auto body = getObject<PartDesign::Body>();
    if (!body) {
        return;
    }
    // Rolled back with another Body's edit (ops#640 rank 32): only this Body has an edit roll
    // point without a member of its own in edit
    if (!editedMember && body->getEditRollPoint()) {
        studioRollbacks().erase(this);
        setEditRoll(nullptr);
        App::Document* doc = body->getDocument();
        if (!doc || doc->isPerformingTransaction() || doc->testStatus(App::Document::Recomputing)
            || doc->testStatus(App::Document::Restoring) || body->isRemoving()) {
            return;
        }
        // What was held and touched computes now, as for the edited Body below
        auto touched = [](const App::DocumentObject* obj) {
            return obj->isTouched() || obj->mustRecompute();
        };
        if (touched(body) || std::ranges::any_of(body->Group.getValues(), touched)) {
            recomputeReporting(doc);
        }
        return;
    }
    if (!editedMember || vp.getObject() != editedMember) {
        return;
    }
    App::DocumentObject* member = editedMember;
    editedMember = nullptr;
    editFinal = false;
    setEditRoll(nullptr);
    updateStoppedDisplay();

    // What the edit touched after the point computes now, in the edit's transaction (_resetEdit
    // commits after this signal). A sketch has committed its own "Sketch recompute" step by
    // then (ViewProviderSketch::unsetEdit), so this recompute records no undo step: undoing the
    // sketch's steps touches the sketch, and the next recompute computes the tail again. Not
    // inside an undo or a recompute, nor while the member or the Body is being removed: then the
    // held features stay touched for the next recompute
    App::Document* doc = body->getDocument();
    if (!doc || doc->isPerformingTransaction() || doc->testStatus(App::Document::Recomputing)
        || doc->testStatus(App::Document::Restoring) || member->isRemoving() || body->isRemoving()) {
        return;
    }
    auto touched = [](const App::DocumentObject* obj) {
        return obj->isTouched() || obj->mustRecompute();
    };
    if (touched(body) || std::ranges::any_of(body->Group.getValues(), touched)) {
        // An exception must not leave the document in edit (_resetEdit goes on after this)
        recomputeReporting(doc);
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
    // The studio's other Bodies follow (ops#640 rank 32): Final shows every part's end result,
    // and leaving it rolls them back to member again
    App::Part* studio = nullptr;
    if (Part::BodyBase::studioOf(body, studio)) {
        for (auto other : PartDesign::studioBodies(body->getDocument(), studio)) {
            auto ovpb = other == body ? nullptr
                                      : freecad_cast<ViewProviderBody*>(
                                            Gui::Application::Instance->getViewProvider(other)
                                        );
            if (!ovpb || ovpb->editedMember) {
                continue;
            }
            ovpb->setEditRoll(final ? nullptr : studioEditPointFor(other, member));
            showStudioRollback(ovpb, other);
        }
    }
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

void ViewProviderBody::followStudioEdit(App::DocumentObject* edited)
{
    const PartDesign::StudioList* list = edited ? PartDesign::StudioList::holding(edited) : nullptr;
    if (!list || !list->studio() || !PartDesign::isStudioOwner(edited)) {
        return;
    }
    // Only while its dialog's edit is open
    auto gdoc = Gui::Application::Instance->getDocument(edited->getDocument());
    auto inEdit = gdoc ? freecad_cast<Gui::ViewProviderDocumentObject*>(gdoc->getInEdit()) : nullptr;
    if (!inEdit || inEdit->getObject() != edited) {
        return;
    }
    for (auto other : PartDesign::studioBodies(edited->getDocument(), list->studio())) {
        auto ovpb = freecad_cast<ViewProviderBody*>(Gui::Application::Instance->getViewProvider(other));
        if (!ovpb || ovpb->editedMember) {
            continue;
        }
        App::DocumentObject* point = studioEditPointFor(other, edited);
        if (point == other->getEditRollPoint()) {
            continue;
        }
        ovpb->setEditRoll(point);
        showStudioRollback(ovpb, other);
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
    // (Document::recomputeFeature): touch its users, as OK does, and compute the Body's tail (the
    // users outside the Body compute on OK). A failure is reported, not thrown into the dialog
    for (auto user : member->getInList()) {
        user->touch();
    }
    recomputeReporting(doc, {body});
}

bool ViewProviderBody::reorderObjects(const std::vector<App::DocumentObject*>& dropped,
                                      App::DocumentObject* target,
                                      bool after)
{
    auto body = getObject<PartDesign::Body>();
    if (!body || dropped.empty()) {
        return false;
    }
    // The Origin and its features (hasObject() counts them) have no place in the Group, which
    // Body.reorderObject refuses (ops#597): dragged along with features, they stay where they are
    const auto& members = body->Group.getValues();
    std::vector<App::DocumentObject*> objs;
    for (auto obj : dropped) {
        if (!body->hasObject(obj)) {
            return false;
        }
        if (std::ranges::find(members, obj) != members.end()) {
            objs.push_back(obj);
        }
    }
    if (objs.empty()) {
        return true;  // nothing to move
    }
    // canDropObject() refuses the drag first; the drop's transaction has committed the edit's
    if (isEditLocked(body->getDocument())) {
        throw Base::RuntimeError(editLockedMessage);
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
    else if (std::ranges::find(members, target) == members.end()) {
        // A row that isn't in the Group (the Origin, which hasObject() counts, ops#597) is above
        // every feature: the start
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
    // Nothing is dropped on the Body during an edit, its own members (a reorder, ops#127) or
    // another body's (ops#139): the drop's transaction would commit the edit's
    auto body = getObject<PartDesign::Body>();
    if (isEditLocked(body->getDocument())) {
        Gui::getMainWindow()->showMessage(QCoreApplication::translate("Exception", editLockedMessage), 5000);
        return false;
    }
    // The Body's own members are dropped among its rows to reorder them (ops#127). An own solid
    // in a copy drag, or dragged with objects from outside the Body (ops#135; the tree drags its
    // selection), isn't reordered but dropped, which dropObject() refuses: the cursor refuses it
    if (body->hasObject(obj)) {
        if (!PartDesign::Body::isSolidFeature(obj)) {
            return true;
        }
#ifdef Q_OS_MACOS
        constexpr auto copyModifier = Qt::AltModifier;
#else
        constexpr auto copyModifier = Qt::ControlModifier;
#endif
        auto selection = Gui::Selection().getCompleteSelection();
        bool mixed = std::ranges::any_of(selection, [body](const Gui::SelectionSingleton::SelObj& sel) {
            return sel.pObject && !body->hasObject(sel.pObject);
        });
        if (mixed || (QApplication::queryKeyboardModifiers() & copyModifier)) {
            Gui::getMainWindow()->showMessage(QCoreApplication::translate("Exception", dragAloneMessage), 5000);
            return false;
        }
        return true;
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
        throw Base::RuntimeError(dragAloneMessage);
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
    // Shown again: its members show through the mode switch, not the studio's switch (ops#654)
    updateStudioShown(this);

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
