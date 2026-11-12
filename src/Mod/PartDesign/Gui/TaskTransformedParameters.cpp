// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer <jrheinlaender@users.sourceforge.net> *
 *                                                                            *
 *   This file is part of the FreeCAD CAx development system.                 *
 *                                                                            *
 *   This library is free software; you can redistribute it and/or            *
 *   modify it under the terms of the GNU Library General Public              *
 *   License as published by the Free Software Foundation; either             *
 *   version 2 of the License, or (at your option) any later version.         *
 *                                                                            *
 *   This library  is distributed in the hope that it will be useful,         *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of           *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            *
 *   GNU Library General Public License for more details.                     *
 *                                                                            *
 *   You should have received a copy of the GNU Library General Public        *
 *   License along with this library; see the file COPYING.LIB. If not,       *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,            *
 *   Suite 330, Boston, MA  02111-1307, USA                                   *
 *                                                                            *
 ******************************************************************************/


#include <QAction>
#include <QListWidget>
#include <QTimer>

#include <BRepAdaptor_Surface.hxx>
#include <TopoDS.hxx>


#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/DocumentObserver.h>
#include <App/PropertyStandard.h>
#include <App/Transactions.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/Origin.h>
#include <App/Part.h>
#include <Base/Console.h>
#include <Gui/Document.h>
#include <Gui/BitmapFactory.h>
#include <Gui/ViewProvider.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Command.h>
#include <Gui/Tools.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureAddSub.h>
#include <Mod/PartDesign/App/FeatureTransformed.h>
#include <Mod/PartDesign/App/StudioList.h>
#include <Mod/Part/App/PartFeature.h>

#include "ui_TaskTransformedParameters.h"
#include "TaskTransformedParameters.h"
#include "TaskMultiTransformParameters.h"
#include "ReferenceField.h"
#include "ReferenceSelection.h"
#include "Utils.h"
#include "ViewProviderBody.h"


FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskTransformedParameters */

namespace
{
/// FreeCAD-CH ops#654 slice 8: the studio feature (owner) an original picked in a listed studio
/// stands for: an owner row, or a step of one (a face of the part maps to the step); null for any
/// other object
App::DocumentObject* studioOwnerOfPick(App::DocumentObject* obj)
{
    if (!obj) {
        return nullptr;
    }
    if (PartDesign::isStudioOwner(obj)) {
        return obj;
    }
    if (PartDesign::StudioList::isStep(obj)) {
        auto feature = freecad_cast<PartDesign::Feature*>(obj);
        return feature ? feature->StudioOwner.getValue() : nullptr;
    }
    return nullptr;
}

/// A pattern of studio features that can't copy one (ops#654 slice 8: an original acting on
/// other parts, an Up to next one...) says why in its Features field, in red until the next pick.
/// A pattern over parts (T1a, a studio feature): its own refusal, or else its first step's that
/// fails (the part it can't pattern)
void showStudioRefusal(ReferenceField* field, PartDesign::Transformed* pattern)
{
    if (!field || !pattern) {
        return;
    }
    if (PartDesign::isStudioOwner(pattern)) {
        const char* why = nullptr;
        if (pattern->isError()) {
            why = pattern->getStatusString();
        }
        else {
            for (auto obj : pattern->getDocument()->getObjectsOfType(
                     PartDesign::Body::getClassTypeId()
                 )) {
                auto step = PartDesign::StudioList::stepOf(pattern, static_cast<PartDesign::Body*>(obj));
                if (step && step->isError()) {
                    why = step->getStatusString();
                    break;
                }
            }
        }
        if (why) {
            field->setNote(QString::fromUtf8(why));
        }
        return;
    }
    if (!pattern->isError()) {
        return;
    }
    const auto& originals = pattern->Originals.getValues();
    if (std::ranges::any_of(originals, [](auto obj) { return studioOwnerOfPick(obj) != nullptr; })) {
        field->setNote(QString::fromUtf8(pattern->getStatusString()));
    }
}
}  // namespace

namespace PartDesign
{
// App/StudioList.cpp (ops#654 T1a; declared where used)
PartDesignExport bool isStudioFeaturePattern(const App::DocumentObject* obj);
}  // namespace PartDesign

namespace PartDesignGui
{
/// The origin a pattern's panel offers its references from: its Body's, or a studio feature's
/// (ops#654 T1a, outside every Body) its studio's own: Top, Front, Right (declared where used,
/// TaskMirroredParameters.cpp, TaskPatternParameters.cpp). Null when it has neither; throws as
/// getOrigin() does
App::Origin* transformedOrigin(App::DocumentObject* pattern)
{
    if (!pattern) {
        return nullptr;
    }
    if (PartDesign::Body* body = PartDesign::Body::findBodyOf(pattern)) {
        return body->getOrigin();
    }
    if (auto studio = freecad_cast<App::Part*>(App::GeoFeatureGroupExtension::getGroupOfObject(pattern))) {
        return studio->getOrigin();
    }
    return nullptr;
}
}  // namespace PartDesignGui

TaskTransformedParameters::TaskTransformedParameters(
    ViewProviderTransformed* TransformedView,
    QWidget* parent
)
    : TaskBox(
          Gui::BitmapFactory().pixmap(TransformedView->featureIcon().c_str()),
          TransformedView->menuName,
          true,
          parent
      )
    , TransformedView(TransformedView)
    , ui(new Ui_TaskTransformedParameters)
{
    Gui::Document* doc = TransformedView->getDocument();
    this->attachDocument(doc);
}

TaskTransformedParameters::TaskTransformedParameters(TaskMultiTransformParameters* parentTask)
    : TaskBox(QPixmap(), tr(""), true, parentTask)
    , parentTask(parentTask)
    , insideMultiTransform(true)
{}

TaskTransformedParameters::~TaskTransformedParameters()
{
    // make sure to remove selection gate in all cases
    Gui::Selection().rmvSelectionGate();

    delete proxy;
}

void TaskTransformedParameters::setupUI()
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    connect(ui->checkBoxUpdateView, &QCheckBox::toggled, this, &TaskTransformedParameters::onUpdateView);

    // Get the feature data
    auto pcTransformed = getObject<PartDesign::Transformed>();

    // The Originals: a pick of a feature in the tree adds it or takes it out, and so does a pick
    // of an element in the 3D view, for the feature that made the element (ops#184)
    // (ops#150 W4; B6: the entries are objects, not Labels)
    ReferenceField::Options options;
    options.kind = ReferenceField::Kind::Objects;
    options.target = [this]() { return getBaseObject(); };
    options.accept = [this](App::DocumentObject* obj, const char* /*sub*/, std::string& why) {
        return acceptOriginal(obj, why);
    };
    // A pattern over parts (ops#654 T1b): a face of any part of its studio stands for the
    // feature that made it, as one of the active part's does
    if (PartDesign::isStudioOwner(pcTransformed)) {
        App::DocumentObjectT patternT(pcTransformed);
        options.elementShapes = [patternT](const App::DocumentObject* obj) {
            auto pattern = patternT.getObject();
            const PartDesign::StudioList* list = pattern ? PartDesign::StudioList::holding(pattern) : nullptr;
            if (!list || !obj || !obj->isDerivedFrom<PartDesign::Feature>()) {
                return false;
            }
            PartDesign::Body* body = PartDesign::Body::findBodyOf(obj);
            App::Part* studio = nullptr;
            return body && Part::BodyBase::studioOf(body, studio) && studio == list->studio();
        };
        // Its deleted originals (fact U5): a "Missing feature" row each until taken out
        auto missingOf = [patternT]() -> App::PropertyStringList* {
            auto pattern = patternT.getObject();
            return pattern ? freecad_cast<App::PropertyStringList*>(
                                 pattern->getPropertyByName("StudioMissingOriginals")
                             )
                           : nullptr;
        };
        options.missingRows = [missingOf]() {
            auto missing = missingOf();
            return missing ? missing->getValues() : std::vector<std::string>();
        };
        options.removeMissing = [this, missingOf](int k) {
            auto missing = missingOf();
            if (!missing || k < 0 || k >= missing->getSize()) {
                return;
            }
            setupTransaction();
            std::vector<std::string> labels = missing->getValues();
            labels.erase(labels.begin() + k);
            missing->setValues(labels);
        };
    }
    // Not the pattern, nor a feature after it
    options.noDependents = true;
    options.kinds = tr("Features");
    options.label = tr("Features to transform");
    originalsField = new ReferenceField(
        pcTransformed,
        "Originals",
        std::move(options),
        ReferenceField::ObjectsWriter([this](const std::vector<App::DocumentObject*>& objs) {
            writeOriginals(objs);
        }),
        ui->groupFeatureList
    );
    originalsField->list()->setMaximumHeight(120);
    originalsField->takePlaceOf(ui->originalsPlaceholder);
    showStudioRefusal(originalsField, pcTransformed);
    connect(originalsField, &ReferenceField::arming, this, [this]() { endPickModes(); });

    using Mode = PartDesign::Transformed::Mode;

    ui->buttonGroupMode->setId(ui->radioTransformBody, static_cast<int>(Mode::WholeShape));
    ui->buttonGroupMode->setId(ui->radioTransformToolShapes, static_cast<int>(Mode::Features));

    connect(ui->buttonGroupMode, &QButtonGroup::idClicked, this, &TaskTransformedParameters::onModeChanged);

    auto const mode = static_cast<Mode>(pcTransformed->TransformMode.getValue());
    ui->groupFeatureList->setEnabled(mode == Mode::Features);
    switch (mode) {
        case Mode::WholeShape:
            ui->radioTransformBody->setChecked(true);
            break;
        case Mode::Features:
            ui->radioTransformToolShapes->setChecked(true);
            break;
    }

    setupParameterUI(ui->featureUI);  // create parameter UI widgets

    // FreeCAD-CH ops#654 T3: Onshape's "Reapply features" (a feature pattern's, off by default):
    // each instance re-runs its features there, against the part as it grows
    if (!insideMultiTransform) {
        auto reapply = new QCheckBox(tr("Reapply features"), proxy);
        reapply->setObjectName(QStringLiteral("checkBoxReapply"));
        reapply->setToolTip(
            tr("Recompute each feature at each instance, against the part there: its end "
               "conditions apply per instance")
        );
        reapply->setChecked(pcTransformed->Reapply.getValue());
        reapply->setEnabled(mode == Mode::Features);
        ui->verticalLayout->insertWidget(ui->verticalLayout->indexOf(ui->featureUI) + 1, reapply);
        connect(reapply, &QCheckBox::toggled, this, [this](bool on) {
            auto pattern = getObject<PartDesign::Transformed>();
            if (!pattern || pattern->Reapply.getValue() == on) {
                return;
            }
            setupTransaction();
            pattern->Reapply.setValue(on);
            recomputeFeature();
            if (originalsField) {
                originalsField->setNote(QString());
            }
            showStudioRefusal(originalsField, pattern);
        });
        connect(ui->buttonGroupMode, &QButtonGroup::idClicked, reapply, [reapply](int id) {
            reapply->setEnabled(id == static_cast<int>(Mode::Features));
        });
    }

    this->groupLayout()->addWidget(proxy);
}

void TaskTransformedParameters::slotDeletedObject(const Gui::ViewProviderDocumentObject& Obj)
{
    if (TransformedView == &Obj) {
        TransformedView = nullptr;
    }
}

void TaskTransformedParameters::changeEvent(QEvent* event)
{
    TaskBox::changeEvent(event);
    if (event->type() == QEvent::LanguageChange && proxy) {
        ui->retranslateUi(proxy);
        retranslateParameterUI(ui->featureUI);
    }
}

void TaskTransformedParameters::onSelectionChanged(const Gui::SelectionChanges& /*msg*/)
{
    // The Originals field takes its own picks; the subclasses take their references
}

int TaskTransformedParameters::getUpdateViewTimeout() const
{
    return 500;
}

std::vector<ReferenceField*> TaskTransformedParameters::referenceFields() const
{
    if (originalsField) {
        return {originalsField};
    }
    return {};
}


bool TaskTransformedParameters::acceptOriginal(App::DocumentObject* obj, std::string& why) const
{
    PartDesign::Transformed* pcTransformed = getObject();
    PartDesign::Body* body = pcTransformed ? pcTransformed->getFeatureBody() : nullptr;
    // A pattern over parts (ops#654 T1a, a studio feature): a studio feature or a member of any
    // part of its own studio (one it can't pattern, it takes and says why)
    if (pcTransformed && PartDesign::isStudioOwner(pcTransformed)) {
        const PartDesign::StudioList* list = PartDesign::StudioList::holding(pcTransformed);
        App::DocumentObject* owner = studioOwnerOfPick(obj);
        App::DocumentObject* entry = owner ? owner : obj;
        // A Parts-list row (ops#654 T1b): Onshape's feature pattern takes features and faces
        if (obj->isDerivedFrom<PartDesign::Body>()) {
            why = QT_TR_NOOP("Pick a feature or a face of a part, not a part.");
            return false;
        }
        if (!owner && !entry->isDerivedFrom<PartDesign::FeatureAddSub>()
            && !entry->isDerivedFrom<PartDesign::Transformed>()) {
            why = QT_TR_NOOP("Pick a feature that adds or removes material.");
            return false;
        }
        if (PartDesign::StudioList::holding(entry) != list) {
            why = QT_TR_NOOP("Pick a feature of the studio's parts.");
            return false;
        }
        return true;
    }
    // A studio feature whose step is in the pattern's part (ops#654 slice 8): its step is copied.
    // One acting on other parts too is taken, and the pattern says why it can't copy it
    if (App::DocumentObject* owner = studioOwnerOfPick(obj)) {
        if (body && !PartDesign::StudioList::stepOf(owner, body)) {
            why = QT_TR_NOOP("Pick a feature that acts on the pattern's part.");
            return false;
        }
        return true;
    }
    // A pattern or mirror brings its own instances (Onshape's pattern of a pattern)
    if (!obj->isDerivedFrom<PartDesign::FeatureAddSub>()
        && !obj->isDerivedFrom<PartDesign::Transformed>()) {
        why = QT_TR_NOOP("Pick a feature that adds or removes material.");
        return false;
    }
    if (body && PartDesign::Body::findBodyOf(obj) != body) {
        why = QT_TR_NOOP("Pick a feature of the pattern's body.");
        return false;
    }
    return true;
}

void TaskTransformedParameters::writeOriginals(const std::vector<App::DocumentObject*>& objs)
{
    PartDesign::Transformed* pcTransformed = getObject();
    if (!pcTransformed) {
        return;
    }
    // A step picked (a face of the part) stands for its studio feature; picked again, it takes
    // the feature out (ops#654 slice 8)
    std::vector<App::DocumentObject*> originals;
    for (App::DocumentObject* obj : objs) {
        App::DocumentObject* owner = studioOwnerOfPick(obj);
        App::DocumentObject* entry = owner ? owner : obj;
        if (auto found = std::ranges::find(originals, entry); found != originals.end()) {
            originals.erase(found);
        }
        else {
            originals.push_back(entry);
        }
    }
    // A pattern over parts (T1a): in the studio's list's order
    if (PartDesign::isStudioOwner(pcTransformed)) {
        const auto& entries = PartDesign::StudioList::holding(pcTransformed)->Entries.getValues();
        std::ranges::stable_sort(originals, {}, [&entries](App::DocumentObject* obj) {
            return std::ranges::find(entries, obj) - entries.begin();
        });
    }
    // In the body's order, as getSortedOriginals() gives them (a studio feature at its step)
    else if (PartDesign::Body* body = pcTransformed->getFeatureBody()) {
        const std::vector<App::DocumentObject*>& group = body->Group.getValues();
        std::ranges::stable_sort(originals, {}, [&group, body](App::DocumentObject* obj) {
            App::DocumentObject* inBody = obj;
            if (PartDesign::isStudioOwner(obj)) {
                if (auto step = PartDesign::StudioList::stepOf(obj, body)) {
                    inBody = step;
                }
            }
            return std::ranges::find(group, inBody) - group.begin();
        });
    }
    setupTransaction();
    pcTransformed->Originals.setValues(originals);
    recomputeFeature();
    showStudioRefusal(originalsField, pcTransformed);
}

void TaskTransformedParameters::setupTransaction()
{
    if (!isEnabledTransaction()) {
        return;
    }

    auto obj = getObject();
    if (!obj) {
        return;
    }

    int tid = obj->getDocument()->getBookedTransactionID();
    if (tid != App::NullTransaction) {
        return;
    }

    // open a transaction if none is active
    // where is this transaction committed - theo-vt?
    std::string name("Edit ");
    name += obj->Label.getValue();
    transactionID = obj->getDocument()->openTransaction(name.c_str());
}

void TaskTransformedParameters::setEnabledTransaction(bool on)
{
    enableTransaction = on;
}

bool TaskTransformedParameters::isEnabledTransaction() const
{
    return enableTransaction;
}

void TaskTransformedParameters::onModeChanged(int mode_id)
{
    if (mode_id < 0) {
        return;
    }

    // The transaction first, so that Cancel takes the switch back (PR 154 review)
    setupTransaction();
    auto pcTransformed = getObject<PartDesign::Transformed>();
    pcTransformed->TransformMode.setValue(mode_id);

    using Mode = PartDesign::Transformed::Mode;
    Mode const mode = static_cast<Mode>(mode_id);

    // The Originals field is greyed while the whole body is transformed; its entries stay, as the
    // property keeps them
    ui->groupFeatureList->setEnabled(mode == Mode::Features);
    recomputeFeature();
    // The tool shapes chosen with none listed: the field arms for the first pick
    if (mode == Mode::Features && originalsField && originalsField->entries().empty()) {
        QTimer::singleShot(0, originalsField, [field = originalsField]() {
            field->setArmed(true);
            if (field->isArmed()) {
                field->list()->setFocus(Qt::OtherFocusReason);
            }
        });
    }
}

void TaskTransformedParameters::fillAxisCombo(Gui::ComboLinks& combolinks, Part::Part2DObject* sketch)
{
    combolinks.clear();

    // add sketch axes
    if (sketch) {
        combolinks.addLink(sketch, "H_Axis", tr("Horizontal sketch axis"));
        combolinks.addLink(sketch, "V_Axis", tr("Vertical sketch axis"));
        combolinks.addLink(sketch, "N_Axis", tr("Normal sketch axis"));
        for (int i = 0; i < sketch->getAxisCount(); i++) {
            QString itemText = tr("Construction line %1").arg(i + 1);
            std::stringstream sub;
            sub << "Axis" << i;
            combolinks.addLink(sketch, sub.str(), itemText);
        }
    }

    // add part axes (a studio feature's: its studio's, ops#654 T1a)
    try {
        if (App::Origin* orig = transformedOrigin(getObject())) {
            combolinks.addLink(orig->getX(), "", tr("Base X-axis"));
            combolinks.addLink(orig->getY(), "", tr("Base Y-axis"));
            combolinks.addLink(orig->getZ(), "", tr("Base Z-axis"));
        }
    }
    catch (const Base::Exception& ex) {
        Base::Console().error("%s\n", ex.what());
    }

    // add "Select reference"
    combolinks.addLink(nullptr, std::string(), tr("Select reference…"));
}

void TaskTransformedParameters::fillPlanesCombo(Gui::ComboLinks& combolinks, Part::Part2DObject* sketch)
{
    combolinks.clear();

    // add sketch axes
    if (sketch) {
        combolinks.addLink(sketch, "V_Axis", QObject::tr("Vertical sketch axis"));
        combolinks.addLink(sketch, "H_Axis", QObject::tr("Horizontal sketch axis"));
        for (int i = 0; i < sketch->getAxisCount(); i++) {
            QString itemText = tr("Construction line %1").arg(i + 1);
            std::stringstream sub;
            sub << "Axis" << i;
            combolinks.addLink(sketch, sub.str(), itemText);
        }
    }

    // add part baseplanes (a studio feature's: its studio's, ops#654 T1a)
    try {
        if (App::Origin* orig = transformedOrigin(getObject())) {
            combolinks.addLink(orig->getXY(), "", tr("Base XY-plane"));
            combolinks.addLink(orig->getYZ(), "", tr("Base YZ-plane"));
            combolinks.addLink(orig->getXZ(), "", tr("Base XZ-plane"));
        }
    }
    catch (const Base::Exception& ex) {
        Base::Console().error("%s\n", ex.what());
    }

    // add "Select reference"
    combolinks.addLink(nullptr, std::string(), tr("Select reference…"));
}

void TaskTransformedParameters::recomputeFeature()
{
    getTopTransformedView()->recomputeFeature();
    // FreeCAD-CH ops#654 T1a: a pattern over parts (a studio feature) computes no shape; its
    // steps show the edit: reconcile in the dialog's transaction (an original added on another
    // part grows the scope, one taken out shrinks it; each step takes the owner's originals),
    // then the document recomputes (as the dress-up owner's picks do). A refusal is reported, not thrown into the dialog
    PartDesign::Transformed* pattern = getTopTransformedObject();
    if (!pattern || !PartDesign::isStudioOwner(pattern)) {
        return;
    }
    App::Document* doc = pattern->getDocument();
    if (!doc || doc->testStatus(App::Document::Recomputing)) {
        return;
    }
    try {
        std::string why;
        PartDesign::StudioList* list = PartDesign::StudioList::holding(pattern);
        if (list && !list->reconcile(&why)) {
            Base::Console().warning("%s\n", why.c_str());
        }
        // A part given a step (or that lost its step) rolls back to it again (T1b): it shows the
        // step, as the parts it had when the dialog opened do
        ViewProviderBody::followStudioEdit(pattern);
        doc->recompute();
    }
    catch (const Base::Exception& e) {
        Base::Console().error("%s\n", e.what());
    }
}

PartDesignGui::ViewProviderTransformed* TaskTransformedParameters::getTopTransformedView() const
{
    return insideMultiTransform ? parentTask->TransformedView : TransformedView;
}

PartDesign::Transformed* TaskTransformedParameters::getTopTransformedObject() const
{
    ViewProviderTransformed* vp = getTopTransformedView();
    if (!vp) {
        return nullptr;
    }

    App::DocumentObject* transform = vp->getObject();
    assert(transform->isDerivedFrom<PartDesign::Transformed>());
    return static_cast<PartDesign::Transformed*>(transform);
}

PartDesign::Transformed* TaskTransformedParameters::getObject() const
{
    if (insideMultiTransform) {
        return parentTask->getSubFeature();
    }
    if (TransformedView) {
        return TransformedView->getObject<PartDesign::Transformed>();
    }
    return nullptr;
}

App::DocumentObject* TaskTransformedParameters::getBaseObject() const
{
    PartDesign::Feature* feature = getTopTransformedObject();
    if (!feature) {
        return nullptr;
    }

    // A pattern over parts (ops#654 T1a) has no base: its field's element picks are made in the
    // active part, in the solid before its step there (the Tip while it has none)
    if (PartDesign::isStudioOwner(feature)) {
        PartDesign::Body* active = PartDesignGui::getBody(/*messageIfNot = */ false);
        if (!active) {
            return nullptr;
        }
        if (PartDesign::Feature* step = PartDesign::StudioList::stepOf(feature, active)) {
            return step->getBaseObject(true);
        }
        return active->Tip.getValue();
    }

    // NOTE: getBaseObject() throws if there is no base; shouldn't happen here.
    App::DocumentObject* base = feature->getBaseObject(true);
    if (!base) {
        auto body = feature->getFeatureBody();
        if (body) {
            base = body->getPrevSolidFeature(feature);
        }
    }
    return base;
}

App::DocumentObject* TaskTransformedParameters::getSketchObject() const
{
    PartDesign::Transformed* feature = getTopTransformedObject();
    return feature ? feature->getSketchObject() : nullptr;
}

void TaskTransformedParameters::hideObject()
{
    try {
        FCMD_OBJ_HIDE(getTopTransformedObject());
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

void TaskTransformedParameters::showObject()
{
    try {
        FCMD_OBJ_SHOW(getTopTransformedObject());
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

void TaskTransformedParameters::hideBase()
{
    try {
        FCMD_OBJ_HIDE(getBaseObject());
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

void TaskTransformedParameters::showBase()
{
    try {
        FCMD_OBJ_SHOW(getBaseObject());
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

void TaskTransformedParameters::exitSelectionMode()
{
    try {
        selectionMode = SelectionMode::None;
        Gui::Selection().rmvSelectionGate();
    }
    catch (Base::Exception& exc) {
        exc.reportException();
    }
}

void TaskTransformedParameters::addReferenceSelectionGate(AllowSelectionFlags allow)
{
    std::unique_ptr<Gui::SelectionFilterGate> gateRefPtr(
        new ReferenceSelection(getBaseObject(), allow)
    );
    std::unique_ptr<Gui::SelectionFilterGate> gateDepPtr(
        new NoDependentsSelection(getTopTransformedObject())
    );
    Gui::Selection().addSelectionGate(new CombineSelectionFilterGates(gateRefPtr, gateDepPtr));
}

namespace
{

/// What a ReferenceSelection with `allow` takes, or a cylindrical face it would take as a face of
/// any kind (FreeCAD-CH ops#640 rank 27)
class DirectionSelection: public Gui::SelectionFilterGate
{
    ReferenceSelection references;
    ReferenceSelection faces;

public:
    DirectionSelection(const App::DocumentObject* support, AllowSelectionFlags allow)
        : Gui::SelectionFilterGate(nullPointer())
        , references(support, allow)
        , faces(support, AllowSelection::FACE)
    {}

    bool allow(App::Document* pDoc, App::DocumentObject* pObj, const char* sSubName) override
    {
        if (references.allow(pDoc, pObj, sSubName)) {
            return true;
        }
        if (!pObj || !sSubName || !faces.allow(pDoc, pObj, sSubName)) {
            return false;
        }
        const Part::TopoShape shape = Part::Feature::getTopoShape(
            pObj,
            Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink,
            sSubName
        );
        if (shape.isNull() || shape.shapeType(true) != TopAbs_FACE) {
            return false;
        }
        BRepAdaptor_Surface adapt(TopoDS::Face(shape.getShape()));
        return adapt.GetType() == GeomAbs_Cylinder;
    }
};

}  // namespace

void TaskTransformedParameters::addDirectionSelectionGate(AllowSelectionFlags allow)
{
    std::unique_ptr<Gui::SelectionFilterGate> gateRefPtr(new DirectionSelection(getBaseObject(), allow));
    std::unique_ptr<Gui::SelectionFilterGate> gateDepPtr(
        new NoDependentsSelection(getTopTransformedObject())
    );
    Gui::Selection().addSelectionGate(new CombineSelectionFilterGates(gateRefPtr, gateDepPtr));
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgTransformedParameters::TaskDlgTransformedParameters(ViewProviderTransformed* viewProvider)
    : TaskDlgFeatureParameters(viewProvider)
{}

//==== calls from the TaskView ===============================================================

bool TaskDlgTransformedParameters::accept()
{
    // A pending "Select reference..." would leave its combo on the empty entry (ops#186)
    parameter->cancelReferencePick();
    parameter->apply();

    // FreeCAD-CH ops#654 T1b: a pattern over parts whose instances make parts or split one (an
    // Add over several parts, a New seed, a split seed): OK makes them in the dialog's own step,
    // so one undo takes the pattern and its parts back (the OK below, once the edit has closed
    // its step, makes what is left, nothing then, in a step of its own). A refusal is the OK
    // below's to report
    App::DocumentObject* obj = getObject();
    if (obj && PartDesign::isStudioFeaturePattern(obj) && obj->getDocument()->hasPendingTransaction()) {
        try {
            std::string why;
            PartDesign::StudioList* list = PartDesign::StudioList::holding(obj);
            if (list && list->reconcile(&why)) {
                Gui::Command::doCommand(
                    Gui::Command::Doc,
                    "import PartDesign\nPartDesign.studioMakePieces(%s)",
                    Gui::Command::getObjectCmd(obj).c_str()
                );
            }
        }
        catch (const Base::Exception& e) {
            Base::Console().log("%s\n", e.what());
        }
    }

    return TaskDlgFeatureParameters::accept();
}

bool TaskDlgTransformedParameters::reject()
{
    // ensure that we are not in selection mode
    parameter->exitSelectionMode();
    return TaskDlgFeatureParameters::reject();
}

void TaskDlgTransformedParameters::referencesRepaired()
{
    TaskDlgFeatureParameters::referencesRepaired();
    if (parameter) {
        parameter->onReferencesRepaired();
    }
}

std::vector<ReferenceField*> TaskDlgTransformedParameters::panelFields()
{
    std::vector<ReferenceField*> fields = TaskDlgFeatureParameters::panelFields();
    if (parameter) {
        for (ReferenceField* field : parameter->referenceFields()) {
            fields.push_back(field);
        }
    }
    return fields;
}

void TaskDlgTransformedParameters::referenceSelectionTaken()
{
    TaskDlgFeatureParameters::referenceSelectionTaken();
    if (parameter) {
        parameter->onReferenceSelectionTaken();
    }
}

#include "moc_TaskTransformedParameters.cpp"
