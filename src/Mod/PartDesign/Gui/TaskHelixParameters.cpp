// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
 *                 2020 David Österberg                                    *
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


#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Origin.h>
#include <Base/Console.h>
#include <Base/Converter.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/CommandT.h>
#include <Gui/Document.h>
#include <Gui/Selection/Selection.h>
#include <Gui/WaitCursor.h>
#include <Mod/Part/App/Tools.h>
#include <Gui/ViewProviderCoordinateSystem.h>
#include <Gui/Inventor/Draggers/SoLinearDragger.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureHelix.h>
#include <Mod/Part/App/GizmoHelper.h>

#include "ReferenceSelection.h"
#include "ui_TaskHelixParameters.h"
#include "TaskHelixParameters.h"

using namespace PartDesignGui;
using PartDesign::HelixMode;
using namespace Gui;


/* TRANSLATOR PartDesignGui::TaskHelixParameters */

namespace
{
bool isSubtractiveHelix(PartDesignGui::ViewProviderHelix* view)
{
    auto* helix = view->getObject<PartDesign::Helix>();
    return helix->getAddSubType() == PartDesign::FeatureAddSub::Type::Subtractive;
}

std::string helixTaskIconName(PartDesignGui::ViewProviderHelix* view)
{
    return isSubtractiveHelix(view) ? "PartDesign_SubtractiveHelix" : "PartDesign_AdditiveHelix";
}

QString helixTaskTitle(PartDesignGui::ViewProviderHelix* view)
{
    return isSubtractiveHelix(view) ? TaskHelixParameters::tr("Subtractive Helix Parameters")
                                    : TaskHelixParameters::tr("Additive Helix Parameters");
}
}  // namespace

TaskHelixParameters::TaskHelixParameters(PartDesignGui::ViewProviderHelix* HelixView, QWidget* parent)
    : TaskSketchBasedParameters(HelixView, parent, helixTaskIconName(HelixView), helixTaskTitle(HelixView))
    , ui(new Ui_TaskHelixParameters)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    this->groupLayout()->addWidget(proxy);

    initializeHelix();

    assignProperties();
    createAxisField();
    setValuesFromProperties();

    updateUI();

    // enable use of parametric expressions for the numerical fields
    bindProperties();

    connectSlots();
    setFocus();
    showCoordinateAxes();

    setupGizmos(HelixView);
}

void TaskHelixParameters::initializeHelix()
{
    auto helix = getObject<PartDesign::Helix>();
    if (!(helix->HasBeenEdited).getValue()) {
        helix->proposeParameters();
        recomputeFeature();
    }
}

void TaskHelixParameters::assignProperties()
{
    auto helix = getObject<PartDesign::Helix>();
    propAngle = &(helix->Angle);
    propGrowth = &(helix->Growth);
    propPitch = &(helix->Pitch);
    propHeight = &(helix->Height);
    propTurns = &(helix->Turns);
    propReferenceAxis = &(helix->ReferenceAxis);
    propLeftHanded = &(helix->LeftHanded);
    propReversed = &(helix->Reversed);
    propMode = &(helix->Mode);
    propOutside = &(helix->Outside);
}

void TaskHelixParameters::setValuesFromProperties()
{
    double pitch = propPitch->getValue();
    double height = propHeight->getValue();
    double turns = propTurns->getValue();
    double angle = propAngle->getValue();
    double growth = propGrowth->getValue();
    bool leftHanded = propLeftHanded->getValue();
    bool reversed = propReversed->getValue();
    int index = propMode->getValue();
    bool outside = propOutside->getValue();

    ui->pitch->setValue(pitch);
    ui->height->setValue(height);
    ui->turns->setValue(turns);
    ui->coneAngle->setValue(angle);
    ui->coneAngle->setMinimum(propAngle->getMinimum());
    ui->coneAngle->setMaximum(propAngle->getMaximum());
    ui->growth->setValue(growth);
    ui->checkBoxLeftHanded->setChecked(leftHanded);
    ui->checkBoxReversed->setChecked(reversed);
    ui->inputMode->setCurrentIndex(index);
    ui->checkBoxOutside->setChecked(outside);
}

void TaskHelixParameters::bindProperties()
{
    auto helix = getObject<PartDesign::Helix>();
    ui->pitch->bind(helix->Pitch);
    ui->height->bind(helix->Height);
    ui->turns->bind(helix->Turns);
    ui->coneAngle->bind(helix->Angle);
    ui->growth->bind(helix->Growth);
}

void TaskHelixParameters::connectSlots()
{
    QMetaObject::connectSlotsByName(this);

    // clang-format off
    connect(ui->pitch, qOverload<double>(&QuantitySpinBox::valueChanged),
            this, &TaskHelixParameters::onPitchChanged);
    connect(ui->height, qOverload<double>(&QuantitySpinBox::valueChanged),
            this, &TaskHelixParameters::onHeightChanged);
    connect(ui->turns, qOverload<double>(&QuantitySpinBox::valueChanged),
            this, &TaskHelixParameters::onTurnsChanged);
    connect(ui->coneAngle, qOverload<double>(&QuantitySpinBox::valueChanged),
            this, &TaskHelixParameters::onAngleChanged);
    connect(ui->growth, qOverload<double>(&QuantitySpinBox::valueChanged),
            this, &TaskHelixParameters::onGrowthChanged);
    connect(ui->checkBoxLeftHanded, &QCheckBox::toggled,
            this, &TaskHelixParameters::onLeftHandedChanged);
    connect(ui->checkBoxReversed, &QCheckBox::toggled,
            this, &TaskHelixParameters::onReversedChanged);
    connect(ui->checkBoxUpdateView, &QCheckBox::toggled,
            this, &TaskHelixParameters::onUpdateView);
    connect(ui->inputMode, qOverload<int>(&QComboBox::activated),
            this, &TaskHelixParameters::onModeChanged);
    connect(ui->checkBoxOutside, &QCheckBox::toggled,
            this, &TaskHelixParameters::onOutsideChanged);
    // clang-format on
}

void TaskHelixParameters::showCoordinateAxes()
{
    // show the parts coordinate system axis for selection
    if (PartDesign::Body* body = PartDesign::Body::findBodyOf(getObject())) {
        try {
            App::Origin* origin = body->getOrigin();
            ViewProviderCoordinateSystem* vpOrigin;
            vpOrigin = static_cast<ViewProviderCoordinateSystem*>(
                Gui::Application::Instance->getViewProvider(origin)
            );
            vpOrigin->setTemporaryVisibility(Gui::DatumElement::Axes);
        }
        catch (const Base::Exception& ex) {
            ex.reportException();
        }
    }
}

void TaskHelixParameters::createAxisField()
{
    // The axis: the box's choices, and a picked edge or line in the row under it, through the
    // cross-body question as before
    ReferenceField::Options axis;
    axis.kind = ReferenceField::Kind::SingleElement;
    axis.flags = AllowSelection::EDGE | AllowSelection::PLANAR | AllowSelection::CIRCLE;
    axis.target = [this]() -> App::DocumentObject* {
        auto helix = getObject<PartDesign::ProfileBased>();
        return helix ? helix->getBaseObject(/*silent=*/true) : nullptr;
    };
    axis.required = false;
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
    auto write = [this, axisSelf](App::DocumentObject* obj, const std::vector<std::string>& picked) {
        // A line or an origin axis is linked whole as {""}: getAxis() takes no axis from no subs
        const std::vector<std::string> subs = picked.empty() ? std::vector<std::string> {""} : picked;
        if (*axisSelf) {
            (*axisSelf)->assign(obj, subs);
        }
        writeAxis(obj, subs);
    };
    auto axisField = new ReferenceField(getObject(), "ReferenceAxis", axis, write, proxy);
    *axisSelf = axisField;
    axisField->takePlaceOf(ui->axisFieldPlaceholder);
    axisField->hide();
    // The box is filled by fillAxisCombo (the .ui's entries are placeholders)
    ui->axis->clear();
    axisCombo = new ReferenceCombo(ui->axis, axisField, propReferenceAxis, write, this);
    // The profile shows while the row is armed, the preview's or not (B18)
    showProfileWhileArmed(axisField);
}

std::vector<ReferenceField*> TaskHelixParameters::referenceFields() const
{
    if (axisCombo && axisCombo->field()) {
        return {axisCombo->field()};
    }
    return {};
}

void TaskHelixParameters::onReferenceSelectionTaken()
{
    // The row disarms through the dialog's group (B15)
}

void TaskHelixParameters::fillAxisCombo(bool forceRefill)
{
    if (!axisCombo) {
        return;
    }
    Base::StateLocker lock(getUpdateBlockRef(), true);

    if (!forceRefill && ui->axis->count() > 0) {
        axisCombo->refresh();
        return;
    }

    std::vector<ReferenceCombo::Choice> choices;
    addSketchAxes(choices);
    addPartAxes(choices);
    // A link that is none of these shows in the row under the box (B19)
    axisCombo->setChoices(choices);
}
void TaskHelixParameters::addSketchAxes(std::vector<ReferenceCombo::Choice>& choices)
{
    auto profile = getObject<PartDesign::ProfileBased>();
    auto sketch = dynamic_cast<Part::Part2DObject*>(profile->Profile.getValue());
    if (sketch) {
        choices.push_back({tr("Normal sketch axis"), sketch, "N_Axis"});
        choices.push_back({tr("Vertical sketch axis"), sketch, "V_Axis"});
        choices.push_back({tr("Horizontal sketch axis"), sketch, "H_Axis"});
        for (int i = 0; i < sketch->getAxisCount(); i++) {
            QString itemText = tr("Construction line %1").arg(i + 1);
            choices.push_back({itemText, sketch, "Axis" + std::to_string(i)});
        }
    }
}
void TaskHelixParameters::addPartAxes(std::vector<ReferenceCombo::Choice>& choices)
{
    auto profile = getObject<PartDesign::ProfileBased>();
    if (PartDesign::Body* body = PartDesign::Body::findBodyOf(profile)) {
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
}
void TaskHelixParameters::onReferencesRepaired()
{
    fillAxisCombo(false);
}

void TaskHelixParameters::updateStatus()
{
    auto helix = getObject<PartDesign::Helix>();
    auto status = std::string(helix->getStatusString());
    QString translatedStatus;
    if (status.compare("Valid") == 0 || status.compare("Touched") == 0) {
        if (helix->safePitch() > helix->Pitch.getValue()) {
            translatedStatus = tr("Warning: helix might be self intersecting");
        }
    }
    // if the helix touches itself along a single helical edge we get this error
    else if (status.compare("NCollection_IndexedDataMap::FindFromKey") == 0) {
        translatedStatus = tr("Error: helix touches itself");
    }
    else {
        translatedStatus = QString::fromStdString(status);
    }
    ui->labelMessage->setText(translatedStatus);
}

void TaskHelixParameters::updateUI()
{
    fillAxisCombo();
    assignToolTipsFromPropertyDocs();
    updateStatus();
    adaptVisibilityToMode();
}

void TaskHelixParameters::adaptVisibilityToMode()
{
    bool isPitchVisible = false;
    bool isHeightVisible = false;
    bool isTurnsVisible = false;
    bool isOutsideVisible = false;
    bool isAngleVisible = false;
    bool isGrowthVisible = false;

    auto helix = getObject<PartDesign::Helix>();
    if (helix->getAddSubType() == PartDesign::FeatureAddSub::Type::Subtractive) {
        isOutsideVisible = true;
    }

    HelixMode mode = static_cast<HelixMode>(propMode->getValue());
    if (mode == HelixMode::pitch_height_angle) {
        isPitchVisible = true;
        isHeightVisible = true;
        isAngleVisible = true;
    }
    else if (mode == HelixMode::pitch_turns_angle) {
        isPitchVisible = true;
        isTurnsVisible = true;
        isAngleVisible = true;
    }
    else if (mode == HelixMode::height_turns_angle) {
        isHeightVisible = true;
        isTurnsVisible = true;
        isAngleVisible = true;
    }
    else if (mode == HelixMode::height_turns_growth) {
        isHeightVisible = true;
        isTurnsVisible = true;
        isGrowthVisible = true;
    }
    else {
        ui->labelMessage->setText(tr("Error: unsupported mode"));
    }

    ui->pitch->setVisible(isPitchVisible);
    ui->labelPitch->setVisible(isPitchVisible);

    ui->height->setVisible(isHeightVisible);
    ui->labelHeight->setVisible(isHeightVisible);

    ui->turns->setVisible(isTurnsVisible);
    ui->labelTurns->setVisible(isTurnsVisible);

    ui->coneAngle->setVisible(isAngleVisible);
    ui->labelConeAngle->setVisible(isAngleVisible);

    ui->growth->setVisible(isGrowthVisible);
    ui->labelGrowth->setVisible(isGrowthVisible);

    ui->checkBoxOutside->setVisible(isOutsideVisible);
}

void TaskHelixParameters::assignToolTipsFromPropertyDocs()
{
    auto helix = getObject<PartDesign::Helix>();
    const char* propCategory = "App::Property";  // cf. https://tracker.freecad.org/view.php?id=0002524
    QString toolTip;

    // Beware that "Axis" in the GUI actually represents the property "ReferenceAxis"!
    // The property "Axis" holds only the directional part of the reference axis and has no
    // corresponding GUI element.
    toolTip = QApplication::translate(propCategory, helix->ReferenceAxis.getDocumentation());
    ui->axis->setToolTip(toolTip);
    ui->labelAxis->setToolTip(toolTip);

    toolTip = QApplication::translate(propCategory, helix->Mode.getDocumentation());
    ui->inputMode->setToolTip(toolTip);
    ui->labelInputMode->setToolTip(toolTip);

    toolTip = QApplication::translate(propCategory, helix->Pitch.getDocumentation());
    ui->pitch->setToolTip(toolTip);
    ui->labelPitch->setToolTip(toolTip);

    toolTip = QApplication::translate(propCategory, helix->Height.getDocumentation());
    ui->height->setToolTip(toolTip);
    ui->labelHeight->setToolTip(toolTip);

    toolTip = QApplication::translate(propCategory, helix->Turns.getDocumentation());
    ui->turns->setToolTip(toolTip);
    ui->labelTurns->setToolTip(toolTip);

    toolTip = QApplication::translate(propCategory, helix->Angle.getDocumentation());
    ui->coneAngle->setToolTip(toolTip);
    ui->labelConeAngle->setToolTip(toolTip);

    toolTip = QApplication::translate(propCategory, helix->Growth.getDocumentation());
    ui->growth->setToolTip(toolTip);
    ui->labelGrowth->setToolTip(toolTip);

    toolTip = QApplication::translate(propCategory, helix->LeftHanded.getDocumentation());
    ui->checkBoxLeftHanded->setToolTip(toolTip);

    toolTip = QApplication::translate(propCategory, helix->Reversed.getDocumentation());
    ui->checkBoxReversed->setToolTip(toolTip);

    toolTip = QApplication::translate(propCategory, helix->Outside.getDocumentation());
    ui->checkBoxOutside->setToolTip(toolTip);
}

void TaskHelixParameters::onSelectionChanged(const Gui::SelectionChanges& /*msg*/)
{}
void TaskHelixParameters::onPitchChanged(double len)
{
    if (getObject()) {
        propPitch->setValue(len);
        recomputeFeature();
        updateUI();
    }
}

void TaskHelixParameters::onHeightChanged(double len)
{
    if (getObject()) {
        propHeight->setValue(len);
        recomputeFeature();
        updateUI();
    }
}

void TaskHelixParameters::onTurnsChanged(double len)
{
    if (getObject()) {
        propTurns->setValue(len);
        recomputeFeature();
        updateUI();
    }
}

void TaskHelixParameters::onAngleChanged(double len)
{
    if (getObject()) {
        propAngle->setValue(len);
        recomputeFeature();
        updateUI();
    }
}

void TaskHelixParameters::onGrowthChanged(double len)
{
    if (getObject()) {
        propGrowth->setValue(len);
        recomputeFeature();
        updateUI();
    }
}

void TaskHelixParameters::writeAxis(App::DocumentObject* obj, const std::vector<std::string>& subs)
{
    // The field's writer has assigned it (with its records); a choice of the box is set here
    if (propReferenceAxis->getValue() != obj || propReferenceAxis->getSubValues() != subs) {
        propReferenceAxis->setValue(obj, subs);
    }
    try {
        // FreeCAD-CH (ops#170): no "suggest reversed" here. Revolution's block was copied with a
        // test of the value against itself (never true); a helix has no rule for it, its
        // profile's normal says nothing about which way along the axis to go.
        recomputeFeature();
        updateStatus();

        setGizmoPositions();
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}
void TaskHelixParameters::onModeChanged(int index)
{
    propMode->setValue(index);

    ui->pitch->setValue(propPitch->getValue());
    ui->height->setValue(propHeight->getValue());
    ui->turns->setValue(propTurns->getValue());
    ui->coneAngle->setValue(propAngle->getValue());
    ui->growth->setValue(propGrowth->getValue());

    recomputeFeature();
    updateUI();
}

void TaskHelixParameters::onLeftHandedChanged(bool on)
{
    if (getObject()) {
        propLeftHanded->setValue(on);
        recomputeFeature();
        updateUI();
    }
}

void TaskHelixParameters::onReversedChanged(bool on)
{
    if (getObject()) {
        propReversed->setValue(on);
        recomputeFeature();
        updateUI();

        setGizmoPositions();
    }
}

void TaskHelixParameters::onOutsideChanged(bool on)
{
    if (getObject()) {
        propOutside->setValue(on);
        recomputeFeature();
        updateUI();
    }
}


TaskHelixParameters::~TaskHelixParameters()
{
    try {
        // hide the parts coordinate system axis for selection
        auto obj = getObject();
        PartDesign::Body* body = obj ? PartDesign::Body::findBodyOf(obj) : nullptr;
        if (body) {
            App::Origin* origin = body->getOrigin();
            ViewProviderCoordinateSystem* vpOrigin {};
            vpOrigin = static_cast<ViewProviderCoordinateSystem*>(
                Gui::Application::Instance->getViewProvider(origin)
            );
            vpOrigin->resetTemporaryVisibility();
        }
    }
    catch (const Base::Exception& ex) {
        ex.reportException();
    }
}

void TaskHelixParameters::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        // save current indexes
        int mode = ui->inputMode->currentIndex();
        ui->retranslateUi(proxy);
        assignToolTipsFromPropertyDocs();

        // The box shows the property again (a picked axis in its row)
        fillAxisCombo(true);

        ui->inputMode->setCurrentIndex(mode);
    }
}

bool TaskHelixParameters::showPreview(PartDesign::Helix* helix)
{
    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/PartDesign"
    );
    if ((hGrp->GetBool("SubractiveHelixPreview", true)
         && helix->getAddSubType() == PartDesign::FeatureAddSub::Type::Subtractive)
        || (hGrp->GetBool("AdditiveHelixPreview", false)
            && helix->getAddSubType() == PartDesign::FeatureAddSub::Type::Additive)) {
        return true;
    }

    return false;
}

// this is used for logging the command fully when recording macros
void TaskHelixParameters::apply()  // NOLINT
{
    auto tobj = getObject();
    // The axis was written as picked or chosen (ops#150: the fields write references, not
    // commands; written again with a plain name it would drop a guess record, ops#127)
    FCMD_OBJ_CMD(tobj, "Mode = " << propMode->getValue());
    FCMD_OBJ_CMD(tobj, "Pitch = " << propPitch->getValue());
    FCMD_OBJ_CMD(tobj, "Height = " << propHeight->getValue());
    FCMD_OBJ_CMD(tobj, "Turns = " << propTurns->getValue());
    FCMD_OBJ_CMD(tobj, "Angle = " << propAngle->getValue());
    FCMD_OBJ_CMD(tobj, "Growth = " << propGrowth->getValue());
    FCMD_OBJ_CMD(tobj, "LeftHanded = " << (propLeftHanded->getValue() ? 1 : 0));
    FCMD_OBJ_CMD(tobj, "Reversed = " << (propReversed->getValue() ? 1 : 0));
}
void TaskHelixParameters::setupGizmos(ViewProviderHelix* vp)
{
    if (!GizmoContainer::isEnabled()) {
        return;
    }

    heightGizmo = new Gui::LinearGizmo(ui->height);

    connect(ui->inputMode, qOverload<int>(&QComboBox::currentIndexChanged), [this](int index) {
        bool isPitchTurnsAngle = index == static_cast<int>(HelixMode::pitch_turns_angle);
        heightGizmo->setVisibility(!isPitchTurnsAngle);
    });

    gizmoContainer = GizmoContainer::create({heightGizmo}, vp);

    setGizmoPositions();

    ui->inputMode->currentIndexChanged(ui->inputMode->currentIndex());
    showDraggerHints();
}

void TaskHelixParameters::setGizmoPositions()
{
    if (!gizmoContainer) {
        return;
    }

    auto helix = getObject<PartDesign::Helix>();
    if (!helix || helix->isError()) {
        gizmoContainer->visible = false;
        return;
    }
    Part::TopoShape profileShape;
    try {
        profileShape = helix->getProfileShape();
    }
    catch (const Base::Exception&) {
        // a missing profile element, while the helix isn't recomputed yet (ops#70)
        gizmoContainer->visible = false;
        return;
    }
    gizmoContainer->visible = true;
    double reversed = propReversed->getValue() ? -1.0 : 1.0;
    auto profileCentre = getMidPointFromProfile(profileShape);
    Base::Vector3d axisDir = helix->Axis.getValue() * reversed;
    Base::Vector3d basePos = helix->Base.getValue();

    // Project the centre point of the helix to a plane passing through the com of the profile
    // and along the helix axis
    Base::Vector3d pos = basePos + axisDir.Dot(profileCentre - basePos) * axisDir;

    heightGizmo->Gizmo::setDraggerPlacement(pos, axisDir);
}


//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
TaskDlgHelixParameters::TaskDlgHelixParameters(ViewProviderHelix* HelixView)
    : TaskDlgSketchBasedParameters(HelixView)
{
    assert(HelixView);
    Content.push_back(new TaskHelixParameters(HelixView));
    Content.push_back(preview);
}


#include "moc_TaskHelixParameters.cpp"
