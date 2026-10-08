// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 Stefan Tröger <stefantroeger@gmx.net>              *
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


#include <QAction>
#include <QMessageBox>
#include <QMetaObject>


#include <cstring>
#include <map>
#include <memory>

#include <QPointer>
#include <QTimer>

#include <boost/algorithm/string/predicate.hpp>

#include <App/Application.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <App/Origin.h>
#include <Base/Tools.h>
#include <Gui/CommandT.h>
#include <Gui/Document.h>
#include <Gui/MainWindow.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Tools.h>
#include <Gui/ViewProvider.h>
#include <Gui/Widgets.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeaturePipe.h>

#include "ui_TaskPipeParameters.h"
#include "ui_TaskPipeOrientation.h"
#include "ui_TaskPipeScaling.h"
#include <ui_DlgReference.h>

#include "TaskPipeParameters.h"
#include "TaskFeaturePick.h"
#include "TaskReferences.h"
#include "TaskSketchBasedParameters.h"
#include "Utils.h"


Q_DECLARE_METATYPE(App::PropertyLinkSubList::SubSet)

using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskPipeParameters */

namespace
{
bool isSubtractivePipe(ViewProviderPipe* view)
{
    auto* pipe = view->getObject<PartDesign::Pipe>();
    return pipe->getAddSubType() == PartDesign::FeatureAddSub::Type::Subtractive;
}

std::string pipeTaskIconName(ViewProviderPipe* view)
{
    return isSubtractivePipe(view) ? "PartDesign_SubtractivePipe" : "PartDesign_AdditivePipe";
}

QString pipeTaskTitle(ViewProviderPipe* view)
{
    return isSubtractivePipe(view) ? TaskPipeParameters::tr("Subtractive Pipe Parameters")
                                   : TaskPipeParameters::tr("Additive Pipe Parameters");
}

QString pipeOrientationTitle(ViewProviderPipe* view)
{
    return isSubtractivePipe(view) ? TaskPipeOrientation::tr("Subtractive Pipe Section Orientation")
                                   : TaskPipeOrientation::tr("Additive Pipe Section Orientation");
}

QString pipeScalingTitle(ViewProviderPipe* view)
{
    return isSubtractivePipe(view) ? TaskPipeScaling::tr("Subtractive Pipe Section Transformation")
                                   : TaskPipeScaling::tr("Additive Pipe Section Transformation");
}

// A sketch is taken whole, unless one of its points is picked: the pipe takes the whole sketch
// for any other element of it (as the loft, Loft::getSectionShape)
std::string sectionElement(App::DocumentObject* obj, const char* sub)
{
    std::string element = Base::Tools::isNullOrEmpty(sub) ? std::string() : std::string(sub);
    if (obj && obj->isDerivedFrom<Part::Part2DObject>()
        && ReferenceActions::subElementType(element) != "Vertex") {
        element.clear();
    }
    return element;
}

// An element's name, old style, in whichever form it is stored (`;g3;SKT.Edge3`, `Edge3`)
std::string bareElement(const std::string& sub)
{
    const char* element = Data::findElementName(sub.c_str());
    return Data::oldElementName(element ? element : sub.c_str());
}

// Whether \a obj with \a element (empty: whole) is what \a linked and its \a used elements
// already give the pipe: the object whole on both sides, or the same element. Other uses of one
// object stay allowed, as in stock: a face of a solid as the profile and that solid's edges as
// the path (PR 166 review, Medium 2)
bool usedAlike(App::DocumentObject* obj,
               const std::string& element,
               App::DocumentObject* linked,
               const std::vector<std::string>& used)
{
    if (!obj || obj != linked) {
        return false;
    }
    std::vector<std::string> elements;
    for (const std::string& sub : used) {
        if (!sub.empty()) {
            elements.push_back(bareElement(sub));
        }
    }
    if (element.empty()) {
        return elements.empty();
    }
    return std::ranges::find(elements, bareElement(element)) != elements.end();
}

// The profile or a section as the pipe takes it: a sketch whole unless a point
std::vector<std::string> sectionElements(App::DocumentObject* obj,
                                         const std::vector<std::string>& subs)
{
    std::vector<std::string> elements;
    for (const std::string& sub : subs) {
        elements.push_back(sectionElement(obj, sub.c_str()));
    }
    return elements;
}

bool usedAsProfile(PartDesign::Pipe* pipe, App::DocumentObject* obj, const std::string& element)
{
    if (!pipe) {
        return false;
    }
    App::DocumentObject* profile = pipe->Profile.getValue();
    return usedAlike(obj, element, profile, sectionElements(profile, pipe->Profile.getSubValues()));
}

bool usedAsSection(PartDesign::Pipe* pipe, App::DocumentObject* obj, const std::string& element)
{
    if (!pipe) {
        return false;
    }
    for (const auto& [section, subs] : pipe->Sections.getSubListValues()) {
        if (usedAlike(obj, element, section, sectionElements(section, subs))) {
            return true;
        }
    }
    return false;
}

bool usedAsPath(PartDesign::Pipe* pipe, App::DocumentObject* obj, const std::string& element)
{
    if (!pipe) {
        return false;
    }
    if (usedAlike(obj, element, pipe->Spine.getValue(), pipe->Spine.getSubValues())) {
        return true;
    }
    // The auxiliary path counts in Mode Auxiliary only: in another mode it is a leftover the pipe
    // doesn't use
    return std::strcmp(pipe->Mode.getValueAsString(), "Auxiliary") == 0
        && usedAlike(obj,
                     element,
                     pipe->AuxiliarySpine.getValue(),
                     pipe->AuxiliarySpine.getSubValues());
}

// The pipe takes a whole object as its profile or a section only when it is a sketch
// (Pipe::execute; PR 166 review, Medium 1): a wire or a datum point whole would break it
bool takesWhole(App::DocumentObject* obj, const char* sub, std::string& why)
{
    if (Base::Tools::isNullOrEmpty(sub) && !obj->isDerivedFrom<Part::Part2DObject>()) {
        why = QT_TR_NOOP("A pipe takes a whole object only when it is a sketch: pick a point or a "
                         "face of it.");
        return false;
    }
    return true;
}

// A path: edges, or a whole object of edges or wires (a sketch, a wire), whose edges the pipe
// joins into one wire (Pipe::buildPipePath); not what the pipe's profile or a section already
// uses
bool acceptPath(const App::DocumentObjectT& pipeT,
                App::DocumentObject* obj,
                const char* sub,
                std::string& why)
{
    if (!obj || !obj->isDerivedFrom<Part::Feature>()) {
        why = QT_TR_NOOP("Pick an edge, or a sketch or a wire whole.");
        return false;
    }
    auto pipe = freecad_cast<PartDesign::Pipe*>(pipeT.getObject());
    const std::string element = Base::Tools::isNullOrEmpty(sub) ? std::string() : std::string(sub);
    if (usedAsProfile(pipe, obj, element)) {
        why = QT_TR_NOOP("This is the pipe's profile: it can't be its path too.");
        return false;
    }
    if (usedAsSection(pipe, obj, element)) {
        why = QT_TR_NOOP("This is a section of the pipe: it can't be its path too.");
        return false;
    }
    if (!Base::Tools::isNullOrEmpty(sub)) {
        if (ReferenceActions::subElementType(sub) != "Edge") {
            why = QT_TR_NOOP("A path is made of edges: pick an edge.");
            return false;
        }
        return true;
    }
    try {
        Part::TopoShape shape = Part::Feature::getTopoShape(
            obj,
            Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
        );
        if (!shape.isNull() && shape.hasSubShape(TopAbs_EDGE) && !shape.hasSubShape(TopAbs_FACE)) {
            return true;
        }
    }
    catch (const Base::Exception&) {
    }
    why = QT_TR_NOOP("A whole object is a path only when it is edges or wires: pick its edges.");
    return false;
}

// The path and the auxiliary path: Profile fields of edges (ops#150 W8)
ReferenceField::Options pathOptions(const App::DocumentObjectT& pipeT)
{
    ReferenceField::Options options;
    options.kind = ReferenceField::Kind::Profile;
    options.use = ReferenceField::ProfileUse::Path;
    options.noDependents = true;
    options.kinds = TaskPipeParameters::tr("Edges, or a sketch or a wire whole");
    options.accept = [pipeT](App::DocumentObject* obj, const char* sub, std::string& why) {
        return acceptPath(pipeT, obj, sub, why);
    };
    return options;
}
}  // namespace


//**************************************************************************
//**************************************************************************
// Task Parameter
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskPipeParameters::TaskPipeParameters(ViewProviderPipe* PipeView, bool /*newObj*/, QWidget* parent)
    : TaskSketchBasedParameters(PipeView, parent, pipeTaskIconName(PipeView), pipeTaskTitle(PipeView))
    , ui(new Ui_TaskPipeParameters)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);

    QMetaObject::connectSlotsByName(this);

    connect(
        ui->comboBoxTransition,
        qOverload<int>(&QComboBox::currentIndexChanged),
        this,
        &TaskPipeParameters::onTransitionChanged
    );

    this->groupLayout()->addWidget(proxy);

    PartDesign::Pipe* pipe = PipeView->getObject<PartDesign::Pipe>();

    // make sure the user sees all important things; what is shown goes back as it was when the
    // dialog closes, on OK and Cancel (ops#162 B13)
    shown.show(pipe->Spine.getValue());
    shown.show(pipe->Profile.getValue());
    shown.show(pipe->AuxiliarySpine.getValue());
    if (!pipe->Spine.getSubValues().empty()) {
        PipeView->makeTemporaryVisible(true);
    }

    ui->comboBoxTransition->setCurrentIndex(pipe->Transition.getValue());
    createFields();

    this->blockSelection(false);
}

void TaskPipeParameters::createFields()
{
    App::DocumentObjectT pipeT(getObject());

    // The profile: one sketch, sketch point or face (ops#150 W8, as the loft's)
    ReferenceField::Options profile;
    profile.kind = ReferenceField::Kind::SingleElement;
    profile.acceptOnly = true;
    profile.noDependents = true;
    profile.removable = false;
    profile.label = tr("Profile");
    profile.kinds = tr("A sketch, a sketch point or a face");
    profile.accept = [pipeT](App::DocumentObject* obj, const char* sub, std::string& why) {
        if (!obj || !obj->isDerivedFrom<Part::Feature>()) {
            why = QT_TR_NOOP("Pick a sketch, a sketch point or a face.");
            return false;
        }
        if (!takesWhole(obj, sub, why)) {
            return false;
        }
        auto pipe = freecad_cast<PartDesign::Pipe*>(pipeT.getObject());
        const std::string element = sectionElement(obj, sub);
        if (usedAsPath(pipe, obj, element)) {
            why = QT_TR_NOOP("This is the pipe's path: it can't be its profile too.");
            return false;
        }
        if (usedAsSection(pipe, obj, element)) {
            why = QT_TR_NOOP("This is a section of the pipe: the profile can't be one too.");
            return false;
        }
        return true;
    };
    profile.resolve = [](const Gui::SelectionChanges& msg,
                         App::DocumentObject*& obj,
                         std::vector<std::string>& subs) {
        subs.clear();
        if (std::string element = sectionElement(obj, msg.pSubName); !element.empty()) {
            subs.push_back(element);
        }
        return obj != nullptr;
    };
    auto profileSelf = std::make_shared<QPointer<ReferenceField>>();
    auto writeProfile = [this, profileSelf](App::DocumentObject* obj,
                                            const std::vector<std::string>& subs) {
        if (*profileSelf) {
            (*profileSelf)->assign(obj, subs);
        }
        shown.show(obj);
        recomputeFeature();
    };
    profileField = new ReferenceField(getObject(), "Profile", profile, writeProfile, proxy);
    *profileSelf = profileField;
    profileField->takePlaceOf(ui->profileFieldPlaceholder);

    // The path: its edges, or a sketch or wire whole; a pick of another object starts the path
    // on it, a pick in the tree takes it whole (ops#162 B9, B10)
    ReferenceField::Options spine = pathOptions(pipeT);
    spine.label = tr("Path to sweep along");
    auto spineSelf = std::make_shared<QPointer<ReferenceField>>();
    auto writeSpine = [this, spineSelf](App::DocumentObject* obj,
                                        const std::vector<std::string>& subs) {
        if (*spineSelf) {
            (*spineSelf)->assign(obj, subs);
        }
        shown.show(obj);
        recomputeFeature();
    };
    spineField = new ReferenceField(getObject(), "Spine", spine, writeSpine, proxy);
    *spineSelf = spineField;
    spineField->takePlaceOf(ui->spineFieldPlaceholder);
}

std::vector<ReferenceField*> TaskPipeParameters::referenceFields() const
{
    return {profileField, spineField};
}

TaskPipeParameters::~TaskPipeParameters()
{
    try {
        if (auto pipe = getObject<PartDesign::Pipe>()) {
            // setting visibility to true is needed when preselecting profile and path prior to
            // invoking sweep
            Gui::cmdGuiObject(pipe, "Visibility = True");
        }
    }
    catch (const Standard_OutOfRange&) {
    }
    catch (const Base::Exception& e) {
        // getDocument() may raise an exception
        e.reportException();
    }
    catch (const Py::Exception&) {
        Base::PyException e;  // extract the Python error text
        e.reportException();
    }
}

void TaskPipeParameters::onSelectionChanged(const Gui::SelectionChanges& /*msg*/)
{
    // The fields take the picks
}

void TaskPipeParameters::onTransitionChanged(int idx)
{
    if (auto pipe = getObject<PartDesign::Pipe>()) {
        pipe->Transition.setValue(idx);
        recomputeFeature();
    }
}

void TaskPipeParameters::onTangentChanged(bool checked)
{
    if (auto pipe = getObject<PartDesign::Pipe>()) {
        pipe->SpineTangent.setValue(checked);
        recomputeFeature();
    }
}

void TaskPipeParameters::onReferenceSelectionTaken()
{
    // The dialog's group disarms the fields
}

void TaskPipeParameters::setVisibilityOfSpineAndProfile()
{
    // As when the pipe was opened; the sections are the Scaling panel's (ops#162 B13: they took the
    // profile's state)
    shown.restore();
}

bool TaskPipeParameters::accept()
{
    // see what to do with external references
    // check the prerequisites for the selected objects
    // the user has to decide which option we should take if external references are used
    auto pipe = getObject<PartDesign::Pipe>();
    auto pcActiveBody = PartDesignGui::getBodyFor(pipe, false);
    if (!pcActiveBody) {
        QMessageBox::warning(this, tr("Input Error"), tr("No active body"));
        return false;
    }
    // auto pcActivePart = PartDesignGui::getPartFor (pcActiveBody, false);
    std::vector<App::DocumentObject*> copies;

    bool extReference = false;
    App::DocumentObject* spine = pipe->Spine.getValue();
    App::DocumentObject* auxSpine = pipe->AuxiliarySpine.getValue();

    // Outside the body and its origin; a missing link isn't (ops#170)
    auto outside = [pcActiveBody](App::DocumentObject* obj) {
        return obj && !pcActiveBody->hasObject(obj) && !pcActiveBody->getOrigin()->hasObject(obj);
    };
    if (outside(spine) || outside(auxSpine)) {
        extReference = true;
    }
    else {
        for (App::DocumentObject* obj : pipe->Sections.getValues()) {
            if (outside(obj)) {
                extReference = true;
                break;
            }
        }
    }

    if (extReference) {
        QDialog dia(Gui::getMainWindow());
        Ui_DlgReference dlg;
        dlg.setupUi(&dia);
        dia.setModal(true);
        int result = dia.exec();
        if (result == QDialog::DialogCode::Rejected) {
            return false;
        }

        if (!dlg.radioXRef->isChecked()) {
            // FreeCAD-CH (ops#170, ops#180): each spine on its own (both can be outside the body),
            // neither when missing (makeCopy(nullptr) put a null into the body after the commit),
            // one copy of an object used twice (the spine as the auxiliary spine too), and the
            // original kept where makeCopy makes none (an App::Link)
            const bool independent = dlg.radioIndependent->isChecked();
            std::map<App::DocumentObject*, App::DocumentObject*> copyOf;
            auto copied = [&](App::DocumentObject* obj) {
                auto [it, added] = copyOf.try_emplace(obj, nullptr);
                if (added) {
                    it->second = PartDesignGui::TaskFeaturePick::makeCopy(obj, "", independent);
                    if (it->second) {
                        copies.push_back(it->second);
                    }
                }
                return it->second ? it->second : obj;
            };
            if (outside(spine)) {
                pipe->Spine.setValue(copied(spine), pipe->Spine.getSubValues());
            }
            if (outside(auxSpine)) {
                pipe->AuxiliarySpine.setValue(
                    copied(auxSpine),
                    pipe->AuxiliarySpine.getSubValues()
                );
            }

            std::vector<App::PropertyLinkSubList::SubSet> subSets;
            for (auto& subSet : pipe->Sections.getSubListValues()) {
                if (outside(subSet.first)) {
                    subSets.emplace_back(copied(subSet.first), subSet.second);
                }
                else {
                    subSets.push_back(subSet);
                }
            }

            pipe->Sections.setSubListValues(subSets);
        }
    }

    try {
        setVisibilityOfSpineAndProfile();

        // Spine isn't written again here: the dialog sets it at selection time, and written
        // again with plain names it would lose its guess record and warning (ops#127).

        Gui::cmdAppDocument(pipe, "recompute()");
        if (!getObject()->isValid()) {
            throw Base::RuntimeError(getObject()->getStatusString());
        }
        Gui::cmdGuiDocument(pipe, "resetEdit()");
        pipe->getDocument()->commitTransaction();

        // we need to add the copied features to the body after the command action, as otherwise
        // FreeCAD crashes unexplainably (copies holds no null, ops#180)
        for (auto obj : copies) {
            pcActiveBody->addObject(obj);
        }
    }
    catch (const Base::Exception& e) {
        pipe->getDocument()->abortTransaction();
        QMessageBox::warning(this, tr("Input Error"), QApplication::translate("Exception", e.what()));
        return false;
    }

    return true;
}


//**************************************************************************
//**************************************************************************
// Task Orientation
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskPipeOrientation::TaskPipeOrientation(ViewProviderPipe* PipeView, bool /*newObj*/, QWidget* parent)
    : TaskSketchBasedParameters(PipeView, parent, pipeTaskIconName(PipeView), pipeOrientationTitle(PipeView))
    , ui(new Ui_TaskPipeOrientation)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    // clang-format off
    connect(ui->comboBoxMode, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskPipeOrientation::onOrientationChanged);
    connect(ui->buttonProfileClear, &QToolButton::clicked,
            this, &TaskPipeOrientation::onClearButton);
    connect(ui->stackedWidget, &QStackedWidget::currentChanged,
            this, &TaskPipeOrientation::updateUI);
    connect(ui->curvilinear, &QCheckBox::toggled,
            this, &TaskPipeOrientation::onCurvilinearChanged);
    connect(ui->doubleSpinBoxX, qOverload<double>(&QDoubleSpinBox::valueChanged),
            this, &TaskPipeOrientation::onBinormalChanged);
    connect(ui->doubleSpinBoxY, qOverload<double>(&QDoubleSpinBox::valueChanged),
            this, &TaskPipeOrientation::onBinormalChanged);
    connect(ui->doubleSpinBoxZ, qOverload<double>(&QDoubleSpinBox::valueChanged),
            this, &TaskPipeOrientation::onBinormalChanged);
    // clang-format on

    this->groupLayout()->addWidget(proxy);

    PartDesign::Pipe* pipe = PipeView->getObject<PartDesign::Pipe>();

    {
        // FreeCAD-CH (ops#180): loading writes nothing and recomputes nothing. The mode and the
        // curvilinear box (checked by default in the pipe, not in the .ui) wrote their value back
        // and recomputed the pipe at every open. The blocked combo doesn't turn the page (its .ui
        // connection), so the page is set here.
        QSignalBlocker blockMode(ui->comboBoxMode);
        QSignalBlocker blockCurvilinear(ui->curvilinear);
        ui->comboBoxMode->setCurrentIndex(pipe->Mode.getValue());
        ui->stackedWidget->setCurrentIndex(pipe->Mode.getValue());
        ui->curvilinear->setChecked(pipe->AuxiliaryCurvilinear.getValue());
    }
    {
        // FreeCAD-CH (ops#170): the binormal as stored. The boxes kept their 0, and editing one
        // wrote all three. Loading writes nothing. Six decimals (ops#180): with the .ui's two,
        // (1/3, ...) showed rounded, and editing one box wrote the other two rounded.
        const Base::Vector3d& binormal = pipe->Binormal.getValue();
        QSignalBlocker blockX(ui->doubleSpinBoxX);
        QSignalBlocker blockY(ui->doubleSpinBoxY);
        QSignalBlocker blockZ(ui->doubleSpinBoxZ);
        for (QDoubleSpinBox* box : {ui->doubleSpinBoxX, ui->doubleSpinBoxY, ui->doubleSpinBoxZ}) {
            box->setDecimals(6);
        }
        ui->doubleSpinBoxX->setValue(binormal.x);
        ui->doubleSpinBoxY->setValue(binormal.y);
        ui->doubleSpinBoxZ->setValue(binormal.z);
    }
    createAuxiliarySpineField();

    // should be called after panel has become visible
    QMetaObject::invokeMethod(this, "updateUI", Qt::QueuedConnection, Q_ARG(int, pipe->Mode.getValue()));
    this->blockSelection(false);
}

void TaskPipeOrientation::createAuxiliarySpineField()
{
    // Used in Mode Auxiliary only, and shown only there (its page); optional, so Delete on the
    // whole object clears it (ops#150 W8)
    ReferenceField::Options options = pathOptions(App::DocumentObjectT(getObject()));
    options.label = tr("Auxiliary path");
    options.required = false;
    auto self = std::make_shared<QPointer<ReferenceField>>();
    auto write = [this, self](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        if (*self) {
            (*self)->assign(obj, subs);
        }
        shown.show(obj);
        recomputeFeature();
    };
    auxiliarySpineField = new ReferenceField(getObject(), "AuxiliarySpine", options, write, proxy);
    *self = auxiliarySpineField;
    auxiliarySpineField->takePlaceOf(ui->auxiliarySpineFieldPlaceholder);
}

std::vector<ReferenceField*> TaskPipeOrientation::referenceFields() const
{
    return {auxiliarySpineField};
}

TaskPipeOrientation::~TaskPipeOrientation() = default;

void TaskPipeOrientation::onOrientationChanged(int idx)
{
    if (auto pipe = getObject<PartDesign::Pipe>()) {
        pipe->Mode.setValue(idx);
        recomputeFeature();
    }
    // Its page hides: an armed auxiliary path would take picks out of sight (PR 166 review). The
    // constructor sets the mode before the field exists
    if (idx != 3 && auxiliarySpineField) {
        auxiliarySpineField->setArmed(false);
    }
}

void TaskPipeOrientation::onReferenceSelectionTaken()
{
    // The dialog's group disarms the fields
}

void TaskPipeOrientation::onClearButton()
{
    // Through the field, as a step of its undo (PR 166 review); its writer recomputes (ops#170)
    auxiliarySpineField->setArmed(false);
    auxiliarySpineField->clear();
}

void TaskPipeOrientation::onCurvilinearChanged(bool checked)
{
    if (auto pipe = getObject<PartDesign::Pipe>()) {
        pipe->AuxiliaryCurvilinear.setValue(checked);
        recomputeFeature();
    }
}

void TaskPipeOrientation::onBinormalChanged(double)
{
    if (auto pipe = getObject<PartDesign::Pipe>()) {
        Base::Vector3d vec(
            ui->doubleSpinBoxX->value(),
            ui->doubleSpinBoxY->value(),
            ui->doubleSpinBoxZ->value()
        );

        pipe->Binormal.setValue(vec);
        recomputeFeature();
    }
}

void TaskPipeOrientation::onSelectionChanged(const SelectionChanges& /*msg*/)
{
    // The auxiliary path field takes the picks
}

void TaskPipeOrientation::updateUI(int idx)
{
    // make sure we resize to the size of the current page
    for (int i = 0; i < ui->stackedWidget->count(); ++i) {
        ui->stackedWidget->widget(i)->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Ignored);
    }

    if (idx < ui->stackedWidget->count()) {
        ui->stackedWidget->widget(idx)->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    }
}


//**************************************************************************
//**************************************************************************
// Task Scaling
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
TaskPipeScaling::TaskPipeScaling(ViewProviderPipe* PipeView, bool /*newObj*/, QWidget* parent)
    : TaskSketchBasedParameters(PipeView, parent, pipeTaskIconName(PipeView), pipeScalingTitle(PipeView))
    , ui(new Ui_TaskPipeScaling)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    // some buttons are handled in a buttongroup
    connect(
        ui->comboBoxScaling,
        qOverload<int>(&QComboBox::currentIndexChanged),
        this,
        &TaskPipeScaling::onScalingChanged
    );
    connect(ui->stackedWidget, &QStackedWidget::currentChanged, this, &TaskPipeScaling::updateUI);

    this->groupLayout()->addWidget(proxy);

    // The sections show for the edit, each put back as it was when the dialog closes (ops#162 B13)
    PartDesign::Pipe* pipe = PipeView->getObject<PartDesign::Pipe>();
    for (App::DocumentObject* obj : pipe->Sections.getValues()) {
        shown.show(obj);
    }

    {
        // Loading writes nothing (the slot recomputes, ops#170); updateUI is queued below
        QSignalBlocker block(ui->comboBoxScaling);
        ui->comboBoxScaling->setCurrentIndex(pipe->Transformation.getValue());
    }
    // The blocked box doesn't turn the page (its .ui connection): a multisection pipe opened on
    // the Constant page, its sections out of sight (ops#150)
    ui->stackedWidget->setCurrentIndex(pipe->Transformation.getValue());
    createSectionsField();

    // should be called after panel has become visible
    QMetaObject::invokeMethod(
        this,
        "updateUI",
        Qt::QueuedConnection,
        Q_ARG(int, pipe->Transformation.getValue())
    );
}

TaskPipeScaling::~TaskPipeScaling() = default;

void TaskPipeScaling::createSectionsField()
{
    App::DocumentObjectT pipeT(getObject());
    ReferenceField::Options options;
    options.kind = ReferenceField::Kind::Sections;
    options.noDependents = true;
    options.label = tr("Sections");
    options.kinds = tr("Sketches, sketch points or faces");
    options.accept = [pipeT](App::DocumentObject* obj, const char* sub, std::string& why) {
        if (!obj || !obj->isDerivedFrom<Part::Feature>()) {
            why = QT_TR_NOOP("Pick a sketch, a sketch point or a face.");
            return false;
        }
        if (!takesWhole(obj, sub, why)) {
            return false;
        }
        auto pipe = freecad_cast<PartDesign::Pipe*>(pipeT.getObject());
        const std::string element = sectionElement(obj, sub);
        if (usedAsProfile(pipe, obj, element)) {
            why = QT_TR_NOOP("This is the pipe's profile: it can't be a section too.");
            return false;
        }
        if (usedAsPath(pipe, obj, element)) {
            why = QT_TR_NOOP("This is the pipe's path: it can't be a section too.");
            return false;
        }
        return true;
    };
    // Only the last section can be a point (Pipe::execute)
    options.checkSections = [](const std::vector<App::PropertyLinkSubList::SubSet>& sections,
                               std::string& why) {
        for (std::size_t i = 0; i + 1 < sections.size(); ++i) {
            if (isPointSection(sections[i])) {
                why = QT_TR_NOOP("Only the last section can be a point.");
                return false;
            }
        }
        return true;
    };
    auto self = std::make_shared<QPointer<ReferenceField>>();
    auto write = [this, self](const std::vector<App::PropertyLinkSubList::SubSet>& list) {
        if (*self) {
            (*self)->assign(list);
        }
        for (const auto& section : list) {
            shown.show(section.first);
        }
        recomputeFeature();
    };
    sectionsField = new ReferenceField(
        getObject(),
        "Sections",
        options,
        ReferenceField::SectionsWriter(write),
        proxy
    );
    *self = sectionsField;
    sectionsField->takePlaceOf(ui->sectionsFieldPlaceholder);
    auto pipe = getObject<PartDesign::Pipe>();
    sectionsField->setRequired(pipe && pipe->Transformation.getValue() == 1);
}

bool TaskPipeScaling::isPointSection(const App::PropertyLinkSubList::SubSet& section)
{
    // A point of a sketch, or a shape of points only; a sub may be mapped or missing
    for (const auto& sub : section.second) {
        if (ReferenceActions::subElementType(sub) == "Vertex") {
            return true;
        }
    }
    try {
        std::vector<std::string> subs = section.second;
        std::erase(subs, std::string());
        if (!subs.empty() || !section.first) {
            return false;
        }
        Part::TopoShape shape = Part::Feature::getTopoShape(
            section.first,
            Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
        );
        return !shape.isNull() && !shape.hasSubShape(TopAbs_EDGE)
            && shape.hasSubShape(TopAbs_VERTEX);
    }
    catch (const Base::Exception&) {
        return false;
    }
}

std::vector<ReferenceField*> TaskPipeScaling::referenceFields() const
{
    return {sectionsField};
}

void TaskPipeScaling::onScalingChanged(int idx)
{
    if (auto pipe = getObject<PartDesign::Pipe>()) {
        updateUI(idx);
        pipe->Transformation.setValue(idx);
        recomputeFeature();  // FreeCAD-CH (ops#170): it waited for OK
    }
    // Multisection with no sections: the field takes the next pick, once its page shows
    const bool multisection = idx == 1;
    sectionsField->setRequired(multisection);
    if (!multisection) {
        sectionsField->setArmed(false);
        return;
    }
    QTimer::singleShot(0, sectionsField, [field = QPointer<ReferenceField>(sectionsField)]() {
        if (field && field->isVisible() && field->entries().empty()) {
            field->setArmed(true);
            if (field->isArmed()) {
                field->list()->setFocus(Qt::OtherFocusReason);
            }
        }
    });
}

void TaskPipeScaling::onSelectionChanged(const SelectionChanges& /*msg*/)
{
    // The sections field takes the picks
}

void TaskPipeScaling::updateUI(int idx)
{
    // make sure we resize to the size of the current page
    for (int i = 0; i < ui->stackedWidget->count(); ++i) {
        ui->stackedWidget->widget(i)->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Ignored);
    }

    if (idx < ui->stackedWidget->count()) {
        ui->stackedWidget->widget(idx)->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    }
}


//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgPipeParameters::TaskDlgPipeParameters(ViewProviderPipe* PipeView, bool newObj)
    : TaskDlgSketchBasedParameters(PipeView)
{
    assert(PipeView);
    parameter = new TaskPipeParameters(PipeView, newObj);
    orientation = new TaskPipeOrientation(PipeView, newObj);
    scaling = new TaskPipeScaling(PipeView, newObj);

    Content.push_back(parameter);
    Content.push_back(orientation);
    Content.push_back(scaling);
    Content.push_back(preview);
    // The fields of the three panels share the dialog's group: one armed at a time (ops#150 W8)
}

TaskDlgPipeParameters::~TaskDlgPipeParameters() = default;

//==== calls from the TaskView ===============================================================


bool TaskDlgPipeParameters::accept()
{
    // As the base dialog's OK does first: no field or Re-pick takes a pick past this point
    fieldGroup->disarm();
    if (references) {
        references->stopPick();
    }
    if (!parameter->accept()) {
        return false;
    }
    // What the edit showed goes back as it was, then the sections the pipe uses are hidden, as
    // the loft's are (the user's answer to PR 163's review, Low 2; ops#150); a constant pipe's
    // leftover sections stay as they were
    orientation->shown.restore();
    scaling->shown.restore();
    auto pipe = getObject<PartDesign::Pipe>();
    if (pipe && pipe->Transformation.getValue() == 1) {
        for (App::DocumentObject* obj : pipe->Sections.getValues()) {
            Gui::cmdAppObjectHide(obj);
        }
    }
    return true;
}

bool TaskDlgPipeParameters::reject()
{
    // What the edit showed goes back first: the abort that follows shows a new pipe's profile
    // again, and a restore after it (the panels' destructors) would hide it (ops#150)
    parameter->shown.restore();
    orientation->shown.restore();
    scaling->shown.restore();
    return TaskDlgSketchBasedParameters::reject();
}


#include "moc_TaskPipeParameters.cpp"
