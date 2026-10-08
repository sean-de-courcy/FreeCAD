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

#include <cstring>
#include <QAbstractButton>
#include <QSignalBlocker>
#include <QTimer>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Origin.h>
#include <Base/Console.h>
#include <Base/Converter.h>
#include <Base/Rotation.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/CommandT.h>
#include <Gui/Selection/Selection.h>
#include <Gui/ViewProvider.h>
#include <Gui/ViewProviderCoordinateSystem.h>
#include <Gui/Inventor/Draggers/Gizmo.h>
#include <Gui/Utilities.h>
#include <Gui/Inventor/Draggers/SoRotationDragger.h>
#include <Mod/PartDesign/App/FeatureRevolved.h>
#include <Mod/PartDesign/App/Body.h>

#include "ui_TaskRevolutionParameters.h"
#include "TaskRevolutionParameters.h"
#include "ViewProviderGroove.h"
#include "ViewProviderRevolution.h"
#include "ReferenceSelection.h"

using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskRevolutionParameters */

namespace
{

bool isLegacyTwoAngles(const std::string& method)
{
    return method == "?TwoAngles" || method == "TwoAngles";
}

}  // namespace

TaskRevolutionParameters::TaskRevolutionParameters(
    PartDesignGui::ViewProvider* RevolutionView,
    const char* pixname,
    const QString& title,
    QWidget* parent
)
    : TaskSketchBasedParameters(RevolutionView, parent, pixname, title)
    , ui(new Ui_TaskRevolutionParameters)
    , proxy(new QWidget(this))
    , isGroove(false)
{
    // we need a separate container widget to add all controls to
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);
    this->groupLayout()->addWidget(proxy);

    // bind property mirrors
    if (auto rev = getObject<PartDesign::Revolved>()) {
        isGroove = rev->getAddSubType() == PartDesign::Revolved::Type::Subtractive;
        this->propSideType = &(rev->SideType);
        this->propReferenceAxis = &(rev->ReferenceAxis);
        this->propReversed = &(rev->Reversed);
    }
    else {
        throw Base::TypeError("The object is neither a groove nor a revolution.");
    }

    setupDialog();

    setUpdateBlocked(false);
    updateUI(Side::First);
    connectSignals();

    setFocus();

    // show the parts coordinate system axis for selection
    try {
        if (auto vpOrigin = getOriginView()) {
            vpOrigin->setTemporaryVisibility(Gui::DatumElement::Axes);
        }
    }
    catch (const Base::Exception& ex) {
        ex.reportException();
    }

    setupGizmos(RevolutionView);
}

Gui::ViewProviderCoordinateSystem* TaskRevolutionParameters::getOriginView() const
{
    // show the parts coordinate system axis for selection
    PartDesign::Body* body = PartDesign::Body::findBodyOf(getObject());
    if (body) {
        App::Origin* origin = body->getOrigin();
        return freecad_cast<ViewProviderCoordinateSystem*>(
            Gui::Application::Instance->getViewProvider(origin)
        );
    }

    return nullptr;
}

void TaskRevolutionParameters::setupDialog()
{
    createSideControllers();
    createFields();

    auto revolved = getObject<PartDesign::Revolved>();
    ui->checkBoxMidplane->hide();
    ui->checkBoxReversed->setChecked(propReversed->getValue());
    ui->startOffsetEdit->setToolTip(tr("Angular offset from the profile or selected start reference"));
    ui->startMode->setCurrentIndex(revolved->StartType.getValue());
    ui->startOffsetEdit->setValue(revolved->StartOffset.getValue());
    ui->startOffsetEdit->setMinimum(revolved->StartOffset.getMinimum());
    ui->startOffsetEdit->setMaximum(revolved->StartOffset.getMaximum());
    ui->startOffsetEdit->setSingleStep(revolved->StartOffset.getStepSize());
    ui->startOffsetEdit->bind(revolved->StartOffset);

    setupSideDialog(m_side1);
    setupSideDialog(m_side2);

    translateSidesList(propSideType->getValue());
    updateStartUI();
}

void TaskRevolutionParameters::createFields()
{
    auto baseSolid = [this]() -> App::DocumentObject* {
        auto revolved = getObject<PartDesign::ProfileBased>();
        return revolved ? revolved->getBaseObject(/*silent=*/true) : nullptr;
    };
    // The start reference and the up-to-faces: a face or a plane (ops#150 W6). Only an
    // up-to-face refuses a sketch whole (B20): a start reference takes the sketch's plane.
    auto faceField = [this, baseSolid](QWidget* placeholder,
                                       const char* property,
                                       const QString& label,
                                       bool refuseWholeSketch) {
        auto self = std::make_shared<QPointer<ReferenceField>>();
        auto write = [this, self](App::DocumentObject* obj, const std::vector<std::string>& subs) {
            if (*self) {
                (*self)->assign(obj, subs);
            }
            recomputeFeature();
            setGizmoPositions();
        };
        auto options = faceFieldOptions(label, baseSolid, refuseWholeSketch);
        auto field = new ReferenceField(getObject(), property, options, write, proxy);
        *self = field;
        field->takePlaceOf(placeholder);
        return field;
    };
    startField = faceField(ui->startReferenceFieldPlaceholder,
                           "StartReference",
                           tr("Start reference"),
                           /*refuseWholeSketch=*/false);
    m_side1.faceField = faceField(ui->faceFieldPlaceholder, "UpToFace", tr("Face"), true);
    m_side2.faceField = faceField(ui->faceFieldPlaceholder2, "UpToFace2", tr("Face"), true);

    // The axis: the box's choices, and a picked edge or line in the row under it, through the
    // cross-body question as before
    ReferenceField::Options axis;
    axis.kind = ReferenceField::Kind::SingleElement;
    axis.flags = AllowSelection::EDGE | AllowSelection::PLANAR | AllowSelection::CIRCLE;
    axis.target = baseSolid;
    axis.required = false;
    axis.removable = false;
    axis.once = true;
    axis.label = tr("Picked axis");
    axis.kinds = tr("A straight or circular edge, or a line");
    axis.resolve = [this](const Gui::SelectionChanges& msg,
                          App::DocumentObject*& obj,
                          std::vector<std::string>& subs) {
        obj = nullptr;
        return getReferencedSelection(getObject(), msg, obj, subs) && obj;
    };
    auto axisSelf = std::make_shared<QPointer<ReferenceField>>();
    auto writeField = [this, axisSelf](App::DocumentObject* obj,
                                       const std::vector<std::string>& picked) {
        // A line or an origin axis is linked whole as {""}: getAxis() takes no axis from no subs
        const std::vector<std::string> subs =
            picked.empty() ? std::vector<std::string> {""} : picked;
        if (*axisSelf) {
            (*axisSelf)->assign(obj, subs);
        }
        writeAxis(obj, subs);
    };
    // The box is filled by fillAxisCombo (the .ui's entries are placeholders)
    ui->axis->clear();
    auto axisField = new ReferenceField(getObject(), "ReferenceAxis", axis, writeField, proxy);
    *axisSelf = axisField;
    axisField->takePlaceOf(ui->axisFieldPlaceholder);
    axisField->hide();
    axisCombo = new ReferenceCombo(ui->axis, axisField, propReferenceAxis, writeField, this);
    // The profile's lines can be picked while the row is armed
    showProfileWhileArmed(axisField);
}

std::vector<ReferenceField*> TaskRevolutionParameters::referenceFields() const
{
    std::vector<ReferenceField*> fields;
    ReferenceField* axisField = axisCombo ? axisCombo->field() : nullptr;
    for (ReferenceField* field : {startField, m_side1.faceField, m_side2.faceField, axisField}) {
        if (field) {
            fields.push_back(field);
        }
    }
    return fields;
}

void TaskRevolutionParameters::onReferenceSelectionTaken()
{
    // The fields disarm through their group (B15)
}

void TaskRevolutionParameters::armField(ReferenceField* field)
{
    if (!field) {
        return;
    }
    // After the mode's widgets are shown
    QTimer::singleShot(0, field, [field]() {
        if (field->isVisible() && field->entries().empty()) {
            field->setArmed(true);
            if (field->isArmed()) {
                field->list()->setFocus(Qt::OtherFocusReason);
            }
        }
    });
}

void TaskRevolutionParameters::updateStartUI()
{
    const auto mode = static_cast<StartMode>(ui->startMode->currentIndex());
    const bool hasOffset = mode != StartMode::ProfilePlane;
    const bool hasReference = mode == StartMode::Reference;

    ui->labelStartOffset->setVisible(hasOffset);
    ui->startOffsetEdit->setVisible(hasOffset);
    if (startField) {
        startField->setVisible(hasReference);
        startField->setRequired(hasReference);
        if (!hasReference) {
            startField->setArmed(false);
        }
    }
}

void TaskRevolutionParameters::createSideControllers()
{
    auto rev = getObject<PartDesign::Revolved>();

    m_side1.changeMode = ui->changeMode;
    m_side1.labelAngle = ui->labelAngle;
    m_side1.angleEdit = ui->revolveAngle;
    m_side1.Type = &rev->Type;
    m_side1.Angle = &rev->Angle;
    m_side1.UpToFace = &rev->UpToFace;

    m_side2.changeMode = ui->changeMode2;
    m_side2.labelAngle = ui->labelAngle2;
    m_side2.angleEdit = ui->revolveAngle2;
    m_side2.Type = &rev->Type2;
    m_side2.Angle = &rev->Angle2;
    m_side2.UpToFace = &rev->UpToFace2;
}

void TaskRevolutionParameters::setupSideDialog(SideController& side)
{
    side.angleEdit->setValue(side.Angle->getValue());
    side.angleEdit->setMaximum(side.Angle->getMaximum());
    side.angleEdit->setMinimum(side.Angle->getMinimum());
    side.angleEdit->bind(*side.Angle);

    int index = int(side.Type->getValue());
    if (static_cast<Mode>(index) == Mode::TwoAngles) {
        index = static_cast<int>(Mode::Angle);
    }
    translateModeList(side.changeMode, index);
}

void TaskRevolutionParameters::onReferencesRepaired()
{
    fillAxisCombo(false);
}

void TaskRevolutionParameters::translateModeList(QComboBox* box, int index)
{
    box->clear();
    box->addItem(tr("Angle"));
    if (!isGroove) {
        box->addItem(tr("To last"));
    }
    else {
        box->addItem(tr("Through all"));
    }
    box->addItem(tr("To first"));
    box->addItem(tr("Up to face"));
    box->setCurrentIndex(index);
}

void TaskRevolutionParameters::translateSidesList(int index)
{
    ui->sidesMode->clear();
    ui->sidesMode->addItem(tr("One sided"));
    ui->sidesMode->addItem(tr("Two sided"));
    ui->sidesMode->addItem(tr("Symmetric"));
    ui->sidesMode->setCurrentIndex(index);
}

void TaskRevolutionParameters::fillAxisCombo(bool forceRefill)
{
    if (!axisCombo) {
        return;
    }
    Base::StateLocker lock(getUpdateBlockRef(), true);

    // not filled yet: full refill
    if (!forceRefill && ui->axis->count() > 0) {
        axisCombo->refresh();
        return;
    }

    auto* pcFeat = getObject<PartDesign::ProfileBased>();
    if (!pcFeat) {
        throw Base::TypeError("The object is not profile-based.");
    }

    std::vector<ReferenceCombo::Choice> choices;
    // add sketch axes
    if (auto* pcSketch = dynamic_cast<Part::Part2DObject*>(pcFeat->Profile.getValue())) {
        choices.push_back({QObject::tr("Vertical sketch axis"), pcSketch, "V_Axis"});
        choices.push_back({QObject::tr("Horizontal sketch axis"), pcSketch, "H_Axis"});
        for (int i = 0; i < pcSketch->getAxisCount(); i++) {
            choices.push_back({QObject::tr("Construction line %1").arg(i + 1),
                               pcSketch,
                               "Axis" + std::to_string(i)});
        }
    }

    // add origin axes
    if (PartDesign::Body* body = PartDesign::Body::findBodyOf(pcFeat)) {
        try {
            App::Origin* orig = body->getOrigin();
            choices.push_back({tr("Base X-axis"), orig->getX(), std::string()});
            choices.push_back({tr("Base Y-axis"), orig->getY(), std::string()});
            choices.push_back({tr("Base Z-axis"), orig->getZ(), std::string()});
        }
        catch (const Base::Exception& ex) {
            ex.reportException();
        }
    }

    // A link that is none of these shows in the row under the box (B19)
    axisCombo->setChoices(choices, tr("Select reference…"));
}

void TaskRevolutionParameters::updateSideUI(
    const SideController& side,
    Mode mode,
    bool isParentVisible,
    bool setFocus
)
{
    bool isAngleVisible = false;
    bool isFaceVisible = false;

    if (mode == Mode::Angle) {
        isAngleVisible = true;
        if (setFocus) {
            side.angleEdit->selectNumber();
            QMetaObject::invokeMethod(side.angleEdit, "setFocus", Qt::QueuedConnection);
        }
    }
    else if (mode == Mode::ToFace) {
        isFaceVisible = true;
    }

    const bool finalAngleVisible = isParentVisible && isAngleVisible;
    side.angleEdit->setVisible(finalAngleVisible);
    side.angleEdit->setEnabled(finalAngleVisible);
    side.labelAngle->setVisible(finalAngleVisible);

    const bool finalFaceVisible = isParentVisible && isFaceVisible;
    side.faceField->setVisible(finalFaceVisible);
    side.faceField->setRequired(finalFaceVisible);
    if (!finalFaceVisible) {
        side.faceField->setArmed(false);
    }
}

void TaskRevolutionParameters::updateWholeUI(Side side)
{
    SidesMode sidesMode = static_cast<SidesMode>(ui->sidesMode->currentIndex());
    Mode mode1 = static_cast<Mode>(ui->changeMode->currentIndex());
    Mode mode2 = static_cast<Mode>(ui->changeMode2->currentIndex());

    const bool isSide2Visible = sidesMode == SidesMode::TwoSides;
    ui->side1Label->setVisible(isSide2Visible);
    ui->line1->setVisible(isSide2Visible);
    ui->side2Label->setVisible(isSide2Visible);
    ui->line2->setVisible(isSide2Visible);
    ui->typeLabel2->setVisible(isSide2Visible);
    ui->changeMode2->setVisible(isSide2Visible);

    updateSideUI(m_side1, mode1, true, side == Side::First);
    updateSideUI(m_side2, mode2, isSide2Visible, side == Side::Second);

    const bool symmetricAngleLike = sidesMode == SidesMode::Symmetric
        && (mode1 == Mode::Angle || (isGroove && mode1 == Mode::ThroughAll));
    ui->checkBoxReversed->setEnabled(!symmetricAngleLike);
}

void TaskRevolutionParameters::connectSignals()
{
    // clang-format off
    connect(ui->revolveAngle, qOverload<double>(&Gui::QuantitySpinBox::valueChanged),
            this, &TaskRevolutionParameters::onAngleChanged);
    connect(ui->revolveAngle2, qOverload<double>(&Gui::QuantitySpinBox::valueChanged),
            this, &TaskRevolutionParameters::onAngle2Changed);
    connect(ui->checkBoxReversed, &QCheckBox::toggled,
            this, &TaskRevolutionParameters::onReversed);
    connect(ui->startMode, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskRevolutionParameters::onStartModeChanged);
    connect(ui->startOffsetEdit, qOverload<double>(&Gui::PrefQuantitySpinBox::valueChanged),
            this, &TaskRevolutionParameters::onStartOffsetChanged);
    connect(ui->checkBoxUpdateView, &QCheckBox::toggled,
            this, &TaskRevolutionParameters::onUpdateView);
    connect(ui->changeMode, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskRevolutionParameters::onModeChangedSide1);
    connect(ui->changeMode2, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskRevolutionParameters::onModeChangedSide2);
    connect(ui->sidesMode, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskRevolutionParameters::onSidesModeChanged);
    // clang-format on
}

void TaskRevolutionParameters::updateUI(Side side)
{
    // The mode's widgets follow the Type whatever "Update view" says (blockUpdate); only the
    // recompute waits (ops#193)
    if (updatingUI) {
        return;
    }

    Base::StateLocker updating(updatingUI, true);
    Base::StateLocker lock(getUpdateBlockRef(), true);
    fillAxisCombo();
    updateWholeUI(side);
}

void TaskRevolutionParameters::onSelectionChanged(const Gui::SelectionChanges& /*msg*/)
{}
void TaskRevolutionParameters::onAngleChanged(double len)
{
    if (getObject()) {
        m_side1.Angle->setValue(len);
        recomputeFeature();

        setGizmoPositions();
    }
}

void TaskRevolutionParameters::onAngle2Changed(double len)
{
    if (getObject()) {
        m_side2.Angle->setValue(len);
        recomputeFeature();

        setGizmoPositions();
    }
}

void TaskRevolutionParameters::onStartModeChanged(int type)
{
    auto revolved = getObject<PartDesign::Revolved>();
    const auto mode = static_cast<StartMode>(type);
    revolved->StartType.setValue(type);

    updateStartUI();
    if (mode == StartMode::Reference) {
        armField(startField);
    }
    recomputeFeature();
    setGizmoPositions();
}

void TaskRevolutionParameters::onStartOffsetChanged(double angle)
{
    getObject<PartDesign::Revolved>()->StartOffset.setValue(angle);
    recomputeFeature();
    setGizmoPositions();
}

void TaskRevolutionParameters::writeAxis(
    App::DocumentObject* obj,
    const std::vector<std::string>& subs
)
{
    auto pcRevolution = getObject<PartDesign::ProfileBased>();
    if (!pcRevolution) {
        return;
    }
    // The field's writer has assigned it (with its records); a choice of the box is set here
    if (propReferenceAxis->getValue() != obj || propReferenceAxis->getSubValues() != subs) {
        propReferenceAxis->setValue(obj, subs);
    }

    try {
        // A picked axis turns the revolution as a chosen one does
        bool reversed = propReversed->getValue();
        if (auto revolved = freecad_cast<PartDesign::Revolved*>(pcRevolution)) {
            reversed = revolved->suggestReversed();
        }
        if (reversed != propReversed->getValue()) {
            propReversed->setValue(reversed);
            QSignalBlocker block(ui->checkBoxReversed);
            ui->checkBoxReversed->setChecked(reversed);
        }

        recomputeFeature();
        setGizmoPositions();
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

void TaskRevolutionParameters::onModeChangedSide1(int index)
{
    onModeChanged(index, Side::First);
}

void TaskRevolutionParameters::onModeChangedSide2(int index)
{
    onModeChanged(index, Side::Second);
}

void TaskRevolutionParameters::onModeChanged(int index, Side side)
{
    auto& sideCtrl = getSideController(side);

    switch (static_cast<Mode>(index)) {
        case Mode::Angle:
            sideCtrl.Type->setValue("Angle");
            break;
        case Mode::ToLast:
            sideCtrl.Type->setValue(isGroove ? "ThroughAll" : "UpToLast");
            break;
        case Mode::ToFirst:
            sideCtrl.Type->setValue("UpToFirst");
            break;
        case Mode::ToFace:
            sideCtrl.Type->setValue("UpToFace");
            break;
        case Mode::TwoAngles:
            break;
    }

    updateUI(side);
    // Up to a face with none yet: its field takes the next pick
    if (static_cast<Mode>(index) == Mode::ToFace) {
        armField(sideCtrl.faceField);
    }
    recomputeFeature();

    setGizmoPositions();
}

void TaskRevolutionParameters::onSidesModeChanged(int index)
{
    switch (static_cast<SidesMode>(index)) {
        case SidesMode::OneSide:
            propSideType->setValue("One side");
            updateUI(Side::First);
            break;
        case SidesMode::TwoSides:
            propSideType->setValue("Two sides");
            updateUI(Side::Second);
            break;
        case SidesMode::Symmetric:
            propSideType->setValue("Symmetric");
            updateUI(Side::First);
            break;
    }

    recomputeFeature();
    setGizmoPositions();
}

void TaskRevolutionParameters::onReversed(bool on)
{
    if (getObject()) {
        propReversed->setValue(on);
        recomputeFeature();

        setGizmoPositions();
    }
}

bool TaskRevolutionParameters::getReversed() const
{
    return ui->checkBoxReversed->isChecked();
}

int TaskRevolutionParameters::getMode() const
{
    return ui->changeMode->currentIndex();
}

int TaskRevolutionParameters::getMode2() const
{
    return ui->changeMode2->currentIndex();
}

int TaskRevolutionParameters::getSidesMode() const
{
    return ui->sidesMode->currentIndex();
}

TaskRevolutionParameters::~TaskRevolutionParameters()
{
    // hide the parts coordinate system axis for selection
    try {
        if (auto vpOrigin = getOriginView()) {
            vpOrigin->resetTemporaryVisibility();
        }
    }
    catch (const Base::Exception& ex) {
        ex.reportException();
    }
}

void TaskRevolutionParameters::changeEvent(QEvent* event)
{
    TaskBox::changeEvent(event);
    if (event->type() == QEvent::LanguageChange) {
        QSignalBlocker startMode(ui->startMode);
        QSignalBlocker startOffset(ui->startOffsetEdit);
        QSignalBlocker angle(ui->revolveAngle);
        QSignalBlocker angle2(ui->revolveAngle2);
        QSignalBlocker mode(ui->changeMode);
        QSignalBlocker mode2(ui->changeMode2);
        QSignalBlocker sidesMode(ui->sidesMode);

        ui->retranslateUi(proxy);

        // Translate mode items
        translateModeList(ui->changeMode, ui->changeMode->currentIndex());
        translateModeList(ui->changeMode2, ui->changeMode2->currentIndex());
        translateSidesList(ui->sidesMode->currentIndex());
        fillAxisCombo(true);
    }
}

void TaskRevolutionParameters::apply()
{
    // Gui::Command::openCommand(QT_TRANSLATE_NOOP("Command", "Revolution changed"));
    ui->startOffsetEdit->apply();
    ui->revolveAngle->apply();
    ui->revolveAngle2->apply();
    auto tobj = getObject();
    auto revolved = getObject<PartDesign::Revolved>();

    // The axis, the start reference and the faces were written as picked or chosen (ops#150:
    // the fields write references, not commands; written again with plain names a link would
    // drop its guess record, ops#127)
    FCMD_OBJ_CMD(tobj, "SideType = " << getSidesMode());
    FCMD_OBJ_CMD(tobj, "Reversed = " << (getReversed() ? 1 : 0));
    FCMD_OBJ_CMD(tobj, "Type = " << getMode());
    FCMD_OBJ_CMD(tobj, "Type2 = " << getMode2());
    FCMD_OBJ_CMD(tobj, "StartOffset = " << ui->startOffsetEdit->value().getValue());
    FCMD_OBJ_CMD(tobj, "StartType = " << ui->startMode->currentIndex());

    // A side that doesn't go up to a face keeps none
    if (static_cast<Mode>(getMode()) != Mode::ToFace && revolved->UpToFace.getValue()) {
        FCMD_OBJ_CMD(tobj, "UpToFace = None");
    }
    if (static_cast<Mode>(getMode2()) != Mode::ToFace && revolved->UpToFace2.getValue()) {
        FCMD_OBJ_CMD(tobj, "UpToFace2 = None");
    }
}

void TaskRevolutionParameters::setupGizmos(ViewProvider* vp)
{
    if (!GizmoContainer::isEnabled()) {
        return;
    }

    const auto toggleReversed = [this] {
        if (ui->checkBoxReversed->isEnabled()) {
            ui->checkBoxReversed->setChecked(!ui->checkBoxReversed->isChecked());
        }
    };

    rotationGizmo = new Gui::RadialGizmo(ui->revolveAngle);
    rotationGizmo->setClickCallback(toggleReversed);
    rotationGizmo2 = new Gui::RadialGizmo(ui->revolveAngle2);
    rotationGizmo2->setClickCallback(toggleReversed);
    startOffsetGizmo = new Gui::RotationGizmo(ui->startOffsetEdit);

    gizmoContainer = GizmoContainer::create({rotationGizmo, rotationGizmo2, startOffsetGizmo}, vp);
    rotationGizmo->flipArrow();
    rotationGizmo2->flipArrow();

    defaultGizmoMultFactor = rotationGizmo->getMultFactor();

    setGizmoPositions();
    showDraggerHints();
}

void TaskRevolutionParameters::setGizmoPositions()
{
    if (!gizmoContainer) {
        return;
    }

    Base::Vector3d profileCog;
    Base::Vector3d basePos;
    Base::Vector3d axisDir;
    bool reversed = false;
    bool symmetric = false;
    std::string sideType;
    std::string revolutionType;
    std::string revolutionType2;

    auto getFeatureProps = [&](auto* feature) {
        if (!feature || feature->isError()) {
            return false;
        }
        Part::TopoShape profile = feature->getProfileShape();

        profile.getCenterOfGravity(profileCog);
        basePos = feature->Base.getValue();
        axisDir = feature->Axis.getValue();
        reversed = feature->Reversed.getValue();
        sideType = std::string(feature->SideType.getValueAsString());
        symmetric = sideType == "Symmetric";
        revolutionType = std::string(feature->Type.getValueAsString());
        revolutionType2 = std::string(feature->Type2.getValueAsString());
        return true;
    };

    bool ret;
    if (isGroove) {
        ret = getFeatureProps(getObject<PartDesign::Groove>());
    }
    else {
        ret = getFeatureProps(getObject<PartDesign::Revolution>());
    }

    gizmoContainer->visible = ret;
    if (!ret) {
        return;
    }

    auto diff = profileCog - basePos;
    axisDir.Normalize();
    auto axisComp = axisDir * diff.Dot(axisDir);
    auto normalComp = diff - axisComp;

    if (reversed) {
        axisDir = -axisDir;
    }

    auto revolved = getObject<PartDesign::Revolved>();
    Base::Vector3d startDirection = normalComp;
    Base::Vector3d referenceDirection = normalComp;
    try {
        const double effectiveStartOffset = revolved->getStartOffset();
        startDirection
            = Base::Rotation(axisDir, Base::toRadians(effectiveStartOffset)).multVec(normalComp);
        referenceDirection
            = Base::Rotation(
                  axisDir,
                  Base::toRadians(effectiveStartOffset - revolved->StartOffset.getValue())
            )
                  .multVec(normalComp);
    }
    catch (const Base::Exception&) {
    }

    const Base::Vector3d axisPosition = basePos + axisComp;
    rotationGizmo->Gizmo::setDraggerPlacement(axisPosition, startDirection);
    rotationGizmo->getDraggerContainer()->setArcNormalDirection(Base::convertTo<SbVec3f>(axisDir));
    rotationGizmo->setVisibility(revolutionType == "Angle" || isLegacyTwoAngles(revolutionType));

    rotationGizmo2->Gizmo::setDraggerPlacement(axisPosition, startDirection);
    rotationGizmo2->getDraggerContainer()->setArcNormalDirection(Base::convertTo<SbVec3f>(-axisDir));
    rotationGizmo2->setVisibility(
        (sideType == "Two sides" && revolutionType2 == "Angle") || isLegacyTwoAngles(revolutionType)
    );

    startOffsetGizmo->Gizmo::setDraggerPlacement(axisPosition, referenceDirection);
    startOffsetGizmo->getDraggerContainer()->setArcNormalDirection(Base::convertTo<SbVec3f>(axisDir));
    startOffsetGizmo->setVisibility(
        std::strcmp(revolved->StartType.getValueAsString(), "Profile plane") != 0
    );

    if (!symmetric) {
        rotationGizmo->setMultFactor(defaultGizmoMultFactor);
    }
    else {
        rotationGizmo->setMultFactor(defaultGizmoMultFactor / 2.0);
    }
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
TaskDlgRevolutionParameters::TaskDlgRevolutionParameters(ViewProviderRevolution* RevolutionView)
    : TaskDlgSketchBasedParameters(RevolutionView)
{
    assert(RevolutionView);
    Content.push_back(
        new TaskRevolutionParameters(RevolutionView, "PartDesign_Revolution", tr("Revolution Parameters"))
    );
    Content.push_back(preview);
}

TaskDlgGrooveParameters::TaskDlgGrooveParameters(ViewProviderGroove* GrooveView)
    : TaskDlgSketchBasedParameters(GrooveView)
{
    assert(GrooveView);
    Content.push_back(
        new TaskRevolutionParameters(GrooveView, "PartDesign_Groove", tr("Groove Parameters"))
    );
    Content.push_back(preview);
}


#include "moc_TaskRevolutionParameters.cpp"
