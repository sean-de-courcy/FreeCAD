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


#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Transactions.h>
#include <App/Origin.h>
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

#include "ui_TaskTransformedParameters.h"
#include "TaskTransformedParameters.h"
#include "TaskMultiTransformParameters.h"
#include "ReferenceField.h"
#include "ReferenceSelection.h"


FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskTransformedParameters */

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

    // The Originals: a pick of a feature in the tree adds it or takes it out (a pick in the 3D
    // view takes the base feature shown there)
    // (ops#150 W4; B6: the entries are objects, not Labels)
    ReferenceField::Options options;
    options.kind = ReferenceField::Kind::Objects;
    options.target = [this]() { return getBaseObject(); };
    options.accept = [this](App::DocumentObject* obj, const char* /*sub*/, std::string& why) {
        return acceptOriginal(obj, why);
    };
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
    if (!obj->isDerivedFrom<PartDesign::FeatureAddSub>()) {
        why = QT_TR_NOOP("Pick a feature that adds or removes material.");
        return false;
    }
    PartDesign::Transformed* pcTransformed = getObject();
    PartDesign::Body* body = pcTransformed ? pcTransformed->getFeatureBody() : nullptr;
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
    // In the body's order, as getSortedOriginals() gives them
    std::vector<App::DocumentObject*> originals = objs;
    if (PartDesign::Body* body = pcTransformed->getFeatureBody()) {
        const std::vector<App::DocumentObject*>& group = body->Group.getValues();
        std::ranges::stable_sort(originals, {}, [&group](App::DocumentObject* obj) {
            return std::ranges::find(group, obj) - group.begin();
        });
    }
    setupTransaction();
    pcTransformed->Originals.setValues(originals);
    recomputeFeature();
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

    // add part axes
    App::DocumentObject* obj = getObject();
    PartDesign::Body* body = PartDesign::Body::findBodyOf(obj);

    if (body) {
        try {
            App::Origin* orig = body->getOrigin();
            combolinks.addLink(orig->getX(), "", tr("Base X-axis"));
            combolinks.addLink(orig->getY(), "", tr("Base Y-axis"));
            combolinks.addLink(orig->getZ(), "", tr("Base Z-axis"));
        }
        catch (const Base::Exception& ex) {
            Base::Console().error("%s\n", ex.what());
        }
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

    // add part baseplanes
    App::DocumentObject* obj = getObject();
    PartDesign::Body* body = PartDesign::Body::findBodyOf(obj);

    if (body) {
        try {
            App::Origin* orig = body->getOrigin();
            combolinks.addLink(orig->getXY(), "", tr("Base XY-plane"));
            combolinks.addLink(orig->getYZ(), "", tr("Base YZ-plane"));
            combolinks.addLink(orig->getXZ(), "", tr("Base XZ-plane"));
        }
        catch (const Base::Exception& ex) {
            Base::Console().error("%s\n", ex.what());
        }
    }

    // add "Select reference"
    combolinks.addLink(nullptr, std::string(), tr("Select reference…"));
}

void TaskTransformedParameters::recomputeFeature()
{
    getTopTransformedView()->recomputeFeature();
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
