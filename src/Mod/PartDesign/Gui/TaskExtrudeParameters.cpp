// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2021 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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
#include <memory>
#include <sstream>

#include <QAction>
#include <QAbstractButton>
#include <QHBoxLayout>
#include <QPushButton>
#include <QPointer>
#include <QSignalBlocker>
#include <QTimer>


#include <App/Datums.h>
#include <App/Document.h>
#include <Base/Tools.h>
#include <Base/UnitsApi.h>
#include <Gui/Application.h>
#include <Gui/Command.h>
#include <Gui/Tools.h>
#include <Gui/Inventor/Draggers/Gizmo.h>
#include <Gui/Inventor/Draggers/SoLinearDragger.h>
#include <Gui/Inventor/Draggers/SoRotationDragger.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureExtrude.h>
#include <Mod/Part/App/GizmoHelper.h>
#include <Mod/Sketcher/Gui/ViewProviderSketch.h>

#include "ui_TaskPadPocketParameters.h"
#include "TaskExtrudeParameters.h"
#include "TaskTransformedParameters.h"
#include "ReferenceField.h"
#include "ReferenceSelection.h"


using namespace PartDesignGui;
using namespace Gui;

namespace
{
// What the profile takes (ops#125): a sketch or other 2D object of the body, whole or by its
// edges and regions, or faces and edges of the solid before the feature. \a why: the refusal.
bool acceptProfile(const App::DocumentObject* feature,
                   const App::DocumentObject* base,
                   App::DocumentObject* obj,
                   const char* sub,
                   std::string& why)
{
    if (!obj) {
        return false;
    }
    if (obj == feature) {
        why = QT_TR_NOOP("The feature can't be its own profile.");
        return false;
    }
    const std::string element(sub ? sub : "");
    auto startsWith = [&element](const char* prefix) {
        return element.rfind(prefix, 0) == 0;
    };
    if (obj == base) {
        if (startsWith("Face") || startsWith("Edge")) {
            return true;
        }
        why = QT_TR_NOOP("Pick faces or edges of the solid.");
        return false;
    }
    if (!obj->isDerivedFrom<Part::Part2DObject>()) {
        why = QT_TR_NOOP("Pick a sketch, its regions or edges, or faces of the solid.");
        return false;
    }
    auto body = PartDesign::Body::findBodyOf(feature);
    if (body && !body->hasObject(obj)) {
        why = QT_TR_NOOP("Pick a sketch of the same body.");
        return false;
    }
    if (element.empty() || startsWith("Edge") || startsWith("Face")
        || startsWith("InternalFace") || startsWith("Wire")) {
        return true;
    }
    why = QT_TR_NOOP("Pick the sketch, its regions or its edges.");
    return false;
}
}  // namespace

/* TRANSLATOR PartDesignGui::TaskExtrudeParameters */

TaskExtrudeParameters::TaskExtrudeParameters(
    ViewProviderExtrude* SketchBasedView,
    QWidget* parent,
    const std::string& pixmapname,
    const QString& parname
)
    : TaskSketchBasedParameters(SketchBasedView, parent, pixmapname, parname)
    , propReferenceAxis(nullptr)
    , ui(new Ui_TaskPadPocketParameters)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    ui->startOffsetEdit->setToolTip(tr("Offset from the profile or selected start reference"));

    Gui::ButtonGroup* group = new Gui::ButtonGroup(this);
    group->addButton(ui->checkBoxReversed);
    group->setExclusive(true);

    this->groupLayout()->addWidget(proxy);
}

void TaskExtrudeParameters::setupDialog()
{
    createSideControllers();
    createFields();

    // --- Global, Non-Side-Specific Setup ---
    auto extrude = getObject<PartDesign::FeatureExtrude>();

    int UserDecimals = Base::UnitsApi::getDecimals();
    ui->XDirectionEdit->setDecimals(UserDecimals);
    ui->YDirectionEdit->setDecimals(UserDecimals);
    ui->ZDirectionEdit->setDecimals(UserDecimals);

    ui->checkBoxAlongDirection->setChecked(extrude->AlongSketchNormal.getValue());

    ui->XDirectionEdit->setValue(extrude->Direction.getValue().x);
    ui->YDirectionEdit->setValue(extrude->Direction.getValue().y);
    ui->ZDirectionEdit->setValue(extrude->Direction.getValue().z);

    ui->XDirectionEdit->bind(App::ObjectIdentifier::parse(extrude, "Direction.x"));
    ui->YDirectionEdit->bind(App::ObjectIdentifier::parse(extrude, "Direction.y"));
    ui->ZDirectionEdit->bind(App::ObjectIdentifier::parse(extrude, "Direction.z"));

    ui->checkBoxReversed->setChecked(extrude->Reversed.getValue());

    ui->startMode->setCurrentIndex(extrude->StartType.getValue());
    ui->startOffsetEdit->setValue(extrude->StartOffset.getQuantityValue());
    ui->startOffsetEdit->bind(extrude->StartOffset);

    // --- Per-Side Setup using the Helper ---
    setupSideDialog(m_side1);
    setupSideDialog(m_side2);

    // --- Final Global UI State Setup ---
    translateSidesList(extrude->SideType.getValue());

    connectSlots();

    this->propReferenceAxis = &(extrude->ReferenceAxis);
    updateStartUI();
    updateUI(Side::First);

    setupGizmos();

    // trigger recompute to ensure external geometry references update correctly.
    // see freecad issue #25794
    tryRecomputeFeature();
    // From here a mode chosen arms its field; on open the dialog arms the first empty one
    dialogReady = true;
}

App::DocumentObject* TaskExtrudeParameters::baseSolid() const
{
    auto profileBased = getObject<PartDesign::ProfileBased>();
    return profileBased ? profileBased->getBaseObject(/* silent =*/true) : nullptr;
}

ReferenceField* TaskExtrudeParameters::createFaceField(QWidget* placeholder,
                                                       const char* property,
                                                       const QString& label)
{
    ReferenceField::Options options;
    options.kind = ReferenceField::Kind::SingleElement;
    options.flags = AllowSelection::FACE;
    // The solid before shows while the field is armed, as the face pick showed it
    options.target = [this]() -> App::DocumentObject* {
        return baseSolid();
    };
    options.required = false;
    options.noDependents = true;
    options.label = label;
    options.kinds = tr("A face or a plane");
    // A plane of a coordinate system is linked through the system, a datum or origin plane
    // whole (as the face pick did)
    options.resolve = [](const Gui::SelectionChanges& msg,
                         App::DocumentObject*& obj,
                         std::vector<std::string>& subs) {
        subs.clear();
        if (!obj) {
            return false;
        }
        if (PartDesign::Feature::isDatum(obj)) {
            auto datum = freecad_cast<App::DatumElement*>(obj);
            if (datum && datum->getLCS()) {
                subs.emplace_back(datum->getNameInDocument());
                obj = datum->getLCS();
            }
            return true;
        }
        if (!Base::Tools::isNullOrEmpty(msg.pSubName)) {
            subs.emplace_back(msg.pSubName);
        }
        return true;
    };
    auto self = std::make_shared<QPointer<ReferenceField>>();
    auto write = [this, self](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        if (*self) {
            (*self)->assign(obj, subs);
        }
        tryRecomputeFeature();
        setGizmoPositions();
    };
    auto field = new ReferenceField(getObject(), property, options, write, proxy);
    *self = field;
    field->takePlaceOf(placeholder);
    return field;
}

void TaskExtrudeParameters::createSideFields(SideController& side, Side which)
{
    const bool first = which == Side::First;
    QWidget* facePlaceholder = first ? ui->faceFieldPlaceholder : ui->faceFieldPlaceholder2;
    QWidget* shapePlaceholder = first ? ui->shapeFieldPlaceholder : ui->shapeFieldPlaceholder2;
    QWidget* facesPlaceholder =
        first ? ui->shapeFacesFieldPlaceholder : ui->shapeFacesFieldPlaceholder2;

    side.faceField = createFaceField(facePlaceholder, first ? "UpToFace" : "UpToFace2", tr("Face"));

    // The up-to-shape: a whole shape; a pick of another one takes all its faces
    QCheckBox* allFaces = side.checkBoxAllFaces;
    const char* shapeProperty = first ? "UpToShape" : "UpToShape2";
    ReferenceField::Options shape;
    shape.kind = ReferenceField::Kind::SingleElement;
    shape.wholeObject = true;
    shape.target = [this]() -> App::DocumentObject* {
        return baseSolid();
    };
    shape.required = false;
    shape.noDependents = true;
    shape.label = tr("Shape");
    shape.kinds = tr("A shape");
    auto shapeSelf = std::make_shared<QPointer<ReferenceField>>();
    auto writeShape = [this, shapeSelf, allFaces](App::DocumentObject* obj,
                                                  const std::vector<std::string>& subs) {
        if (*shapeSelf) {
            (*shapeSelf)->assign(obj, subs);
        }
        QSignalBlocker block(allFaces);
        allFaces->setChecked(true);
        tryRecomputeFeature();
    };
    side.shapeField = new ReferenceField(getObject(), shapeProperty, shape, writeShape, proxy);
    *shapeSelf = side.shapeField;
    side.shapeField->takePlaceOf(shapePlaceholder);

    // Its faces: a list on the shape, or on the solid before while there is none (the feature
    // goes up to that then)
    ReferenceField::Options faces;
    faces.flags = AllowSelection::FACE;
    // Looked up each time: the feature can go while the panel is open (a script)
    faces.target = [this, first]() -> App::DocumentObject* {
        auto extrude = getObject<PartDesign::FeatureExtrude>();
        if (!extrude) {
            return nullptr;
        }
        App::DocumentObject* obj = (first ? extrude->UpToShape : extrude->UpToShape2).getValue();
        return obj ? obj : baseSolid();
    };
    faces.required = false;
    faces.kinds = tr("Faces");
    auto facesSelf = std::make_shared<QPointer<ReferenceField>>();
    auto writeFaces = [this, facesSelf](App::DocumentObject* obj,
                                        const std::vector<std::string>& subs) {
        if (*facesSelf) {
            (*facesSelf)->assign(obj, subs);
        }
        tryRecomputeFeature();
    };
    side.shapeFacesField = new ReferenceField(getObject(), shapeProperty, faces, writeFaces, proxy);
    *facesSelf = side.shapeFacesField;
    side.shapeFacesField->setObjectName(QStringLiteral("field") + QString::fromLatin1(shapeProperty).replace(QStringLiteral("UpToShape"), QStringLiteral("UpToShapeFaces")));
    side.shapeFacesField->takePlaceOf(facesPlaceholder);
}

void TaskExtrudeParameters::createProfileField()
{
    // The profile on top: the sketch whole, its regions or edges, or faces of the solid before
    // (ops#150 W3, in place of the Profile row's Select button)
    ReferenceField::Options profile;
    profile.kind = ReferenceField::Kind::Profile;
    // The solid before shows while it is armed, the sketch too (showProfileTarget)
    profile.target = [this]() -> App::DocumentObject* {
        return baseSolid();
    };
    profile.accept = [this](App::DocumentObject* obj, const char* sub, std::string& why) {
        return acceptProfile(getObject(), baseSolid(), obj, sub, why);
    };
    profile.label = tr("Profile");
    profile.kinds = tr("A sketch, its regions or edges, or faces of the solid");
    auto self = std::make_shared<QPointer<ReferenceField>>();
    auto write = [this, self](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        // In the same command: without it the subs of a sketch are ignored (ops#162 B7)
        allowMultiFace(!subs.empty());
        if (*self) {
            (*self)->assign(obj, subs);
        }
        followProfile();
        tryRecomputeFeature();
        if (axesInList.empty()) {
            fillDirectionCombo();
        }
    };
    profileField = new ReferenceField(getObject(), "Profile", profile, write, proxy);
    *self = profileField;
    ui->verticalLayout->insertWidget(0, profileField);
    connect(profileField, &ReferenceField::armedChanged, this, [this](bool on) {
        showProfileTarget(on);
    });
    connect(profileField, &ReferenceField::picked, this, [this]() {
        // The entry menu's actions (Use, Re-pick) write subs past the writer
        auto profileBased = getObject<PartDesign::ProfileBased>();
        if (profileBased && allowMultiFace(!profileBased->Profile.getSubValues().empty())) {
            tryRecomputeFeature();
        }
        // Another sketch is shown and emphasized instead
        if (profileField->isArmed()) {
            showProfileTarget(true);
        }
    });
}

bool TaskExtrudeParameters::allowMultiFace(bool hasSubs)
{
    auto profileBased = getObject<PartDesign::ProfileBased>();
    if (!hasSubs || !profileBased || profileBased->AllowMultiFace.getValue()) {
        return false;
    }
    FCMD_OBJ_CMD(profileBased, "AllowMultiFace = True");
    return true;
}

void TaskExtrudeParameters::showProfileTarget(bool on)
{
    // What an earlier arming showed goes back first
    if (auto sketch = emphasizedProfile.getObject()) {
        if (auto vp = freecad_cast<SketcherGui::ViewProviderSketch*>(
                Gui::Application::Instance->getViewProvider(sketch)
            )) {
            vp->setRegionEmphasis(false);
        }
    }
    emphasizedProfile = App::DocumentObjectT();
    if (auto profile = shownProfile.getObject()) {
        if (auto vp = Gui::Application::Instance->getViewProvider(profile)) {
            vp->hide();
        }
    }
    shownProfile = App::DocumentObjectT();
    if (hiddenSelf) {
        if (auto vp = getViewObject()) {
            vp->show();
        }
        hiddenSelf = false;
    }
    // The profile preview draws the picked regions over the sketch's (S1)
    if (auto vp = freecad_cast<ViewProviderSketchBased*>(getViewObject())) {
        vp->setProfileEmphasis(on);
    }
    if (!on) {
        return;
    }
    auto profileBased = getObject<PartDesign::ProfileBased>();
    App::DocumentObject* profile = profileBased ? profileBased->Profile.getValue() : nullptr;
    if (profile) {
        Gui::ViewProvider* vp = Gui::Application::Instance->getViewProvider(profile);
        if (vp && !vp->isShow()) {
            vp->show();
            shownProfile = profile;
        }
        if (auto sketchVp = freecad_cast<SketcherGui::ViewProviderSketch*>(vp)) {
            sketchVp->setRegionEmphasis(true);
            emphasizedProfile = profile;
        }
    }
    // Nothing before the feature: the feature hides, so that the sketch can be picked
    if (!baseSolid() && getViewObject() && getViewObject()->isShow()) {
        getViewObject()->hide();
        hiddenSelf = true;
    }
}

void TaskExtrudeParameters::createFields()
{
    createProfileField();
    startField = createFaceField(ui->startReferenceFieldPlaceholder,
                                 "StartReference",
                                 tr("Start reference"));
    createSideFields(m_side1, Side::First);
    createSideFields(m_side2, Side::Second);

    // The direction box's "Select reference…": a pick of an edge or a datum line, through the
    // cross-body question as before; hidden, so its states stay in the References panel
    ReferenceField::Options axis;
    axis.kind = ReferenceField::Kind::SingleElement;
    axis.flags = AllowSelection::EDGE | AllowSelection::PLANAR | AllowSelection::CIRCLE;
    axis.target = [this]() -> App::DocumentObject* {
        return baseSolid();
    };
    axis.required = false;
    axis.once = true;
    axis.covers = false;
    axis.kinds = tr("A straight or circular edge, or a line");
    axis.resolve = [this](const Gui::SelectionChanges& msg,
                          App::DocumentObject*& obj,
                          std::vector<std::string>& subs) {
        obj = nullptr;
        return getReferencedSelection(getObject(), msg, obj, subs) && obj;
    };
    auto axisSelf = std::make_shared<QPointer<ReferenceField>>();
    auto writeAxis = [this, axisSelf](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        if (*axisSelf) {
            (*axisSelf)->assign(obj, subs);
        }
        tryRecomputeFeature();
        fillDirectionCombo();
        setGizmoPositions();
    };
    axisField = new ReferenceField(getObject(), "ReferenceAxis", axis, writeAxis, proxy);
    *axisSelf = axisField;
    axisField->hide();
    ui->verticalLayout->addWidget(axisField);
    // Disarmed without a pick: the box shows the direction there is
    connect(axisField, &ReferenceField::armedChanged, this, [this](bool on) {
        if (!on && ui->directionCB->currentIndex() == DirectionModes::Select) {
            fillDirectionCombo();
        }
    });
}

std::vector<ReferenceField*> TaskExtrudeParameters::referenceFields() const
{
    std::vector<ReferenceField*> fields;
    for (ReferenceField* field : {profileField,
                                  startField,
                                  m_side1.faceField,
                                  m_side1.shapeField,
                                  m_side1.shapeFacesField,
                                  m_side2.faceField,
                                  m_side2.shapeField,
                                  m_side2.shapeFacesField,
                                  axisField}) {
        if (field) {
            fields.push_back(field);
        }
    }
    return fields;
}

void TaskExtrudeParameters::armField(ReferenceField* field)
{
    if (!dialogReady || !field) {
        return;
    }
    // After the mode's widgets are shown
    QTimer::singleShot(0, field, [field]() {
        if (field->isVisible()) {
            field->setArmed(true);
            field->list()->setFocus(Qt::OtherFocusReason);
        }
    });
}

void TaskExtrudeParameters::setupSideDialog(SideController& side)
{
    // --- Get initial values from the correct side's properties ---
    Base::Quantity length = side.Length->getQuantityValue();
    Base::Quantity offset = side.Offset->getQuantityValue();
    Base::Quantity taper = side.TaperAngle->getQuantityValue();
    int typeIndex = side.Type->getValue();
    // The Type/Type2 properties are stuck with the deprecated 'TwoLength' mode.
    // Because enums do not store text just an index. So this create
    // a inconsistence between the UI and the property.
    if (typeIndex > static_cast<int>(Mode::ToShape)) {
        typeIndex--;
    }

    // --- Set up UI widgets with initial values ---
    side.lengthEdit->setValue(length);
    side.offsetEdit->setValue(offset);
    side.taperEdit->setMinimum(side.TaperAngle->getMinimum());
    side.taperEdit->setMaximum(side.TaperAngle->getMaximum());
    side.taperEdit->setSingleStep(side.TaperAngle->getStepSize());
    side.taperEdit->setValue(taper);

    // --- Bind UI widgets to the correct properties ---
    side.lengthEdit->bind(*side.Length);
    side.offsetEdit->bind(*side.Offset);
    side.taperEdit->bind(*side.TaperAngle);

    // --- Set up the mode combobox ---
    translateModeList(side.changeMode, typeIndex);

    // All faces: the shape without faces of its own
    side.checkBoxAllFaces->setChecked(side.shapeFacesField->entries().empty());
    side.upToShapeFaces->setVisible(!side.checkBoxAllFaces->isChecked());
}

void TaskExtrudeParameters::updateStartUI()
{
    const auto mode = static_cast<StartMode>(ui->startMode->currentIndex());
    const bool hasOffset = mode != StartMode::ProfilePlane;
    const bool hasReference = mode == StartMode::Reference;

    ui->labelStartOffset->setVisible(hasOffset);
    ui->startOffsetEdit->setVisible(hasOffset);
    startField->setVisible(hasReference);
    startField->setRequired(hasReference);
    if (!hasReference) {
        startField->setArmed(false);
    }
}

void TaskExtrudeParameters::createSideControllers()
{
    auto extrude = getObject<PartDesign::FeatureExtrude>();

    // --- Initialize Side 1 Controller ---
    m_side1.changeMode = ui->changeMode;
    m_side1.labelLength = ui->labelLength;
    m_side1.labelOffset = ui->labelOffset;
    m_side1.labelTaperAngle = ui->labelTaperAngle;
    m_side1.lengthEdit = ui->lengthEdit;
    m_side1.offsetEdit = ui->offsetEdit;
    m_side1.taperEdit = ui->taperEdit;
    m_side1.checkBoxAllFaces = ui->checkBoxAllFaces;
    m_side1.upToShapeList = ui->upToShapeList;
    m_side1.upToShapeFaces = ui->upToShapeFaces;

    m_side1.Type = &extrude->Type;
    m_side1.Length = &extrude->Length;
    m_side1.Offset = &extrude->Offset;
    m_side1.TaperAngle = &extrude->TaperAngle;
    m_side1.UpToFace = &extrude->UpToFace;
    m_side1.UpToShape = &extrude->UpToShape;

    // --- Initialize Side 2 Controller ---
    m_side2.changeMode = ui->changeMode2;
    m_side2.labelLength = ui->labelLength2;
    m_side2.labelOffset = ui->labelOffset2;
    m_side2.labelTaperAngle = ui->labelTaperAngle2;
    m_side2.lengthEdit = ui->lengthEdit2;
    m_side2.offsetEdit = ui->offsetEdit2;
    m_side2.taperEdit = ui->taperEdit2;
    m_side2.checkBoxAllFaces = ui->checkBoxAllFaces2;
    m_side2.upToShapeList = ui->upToShapeList2;
    m_side2.upToShapeFaces = ui->upToShapeFaces2;

    m_side2.Type = &extrude->Type2;
    m_side2.Length = &extrude->Length2;
    m_side2.Offset = &extrude->Offset2;
    m_side2.TaperAngle = &extrude->TaperAngle2;
    m_side2.UpToFace = &extrude->UpToFace2;
    m_side2.UpToShape = &extrude->UpToShape2;
}

void TaskExtrudeParameters::readValuesFromHistory()
{
    ui->lengthEdit->setToLastUsedValue();
    ui->lengthEdit->selectNumber();
    ui->lengthEdit2->setToLastUsedValue();
    ui->lengthEdit2->selectNumber();
    ui->offsetEdit->setToLastUsedValue();
    ui->offsetEdit->selectNumber();
    ui->offsetEdit2->setToLastUsedValue();
    ui->offsetEdit2->selectNumber();
    ui->taperEdit->setToLastUsedValue();
    ui->taperEdit->selectNumber();
    ui->taperEdit2->setToLastUsedValue();
    ui->taperEdit2->selectNumber();
}

void TaskExtrudeParameters::connectSlots()
{
    QMetaObject::connectSlotsByName(this);

    auto connectSideSlots = [this](auto& side, Side sideEnum, auto modeChangedSlot) {
        connect(
            side.lengthEdit,
            qOverload<double>(&Gui::PrefQuantitySpinBox::valueChanged),
            this,
            [this, sideEnum](double val) { onLengthChanged(val, sideEnum); }
        );
        connect(
            side.offsetEdit,
            qOverload<double>(&Gui::PrefQuantitySpinBox::valueChanged),
            this,
            [this, sideEnum](double val) { onOffsetChanged(val, sideEnum); }
        );
        connect(
            side.taperEdit,
            qOverload<double>(&Gui::PrefQuantitySpinBox::valueChanged),
            this,
            [this, sideEnum](double val) { onTaperChanged(val, sideEnum); }
        );
        connect(side.changeMode, qOverload<int>(&QComboBox::currentIndexChanged), this, modeChangedSlot);
        connect(side.checkBoxAllFaces, &QCheckBox::toggled, this, [this, sideEnum](bool checked) {
            onAllFacesToggled(checked, sideEnum);
        });
    };

    // Use the lambda to connect slots for both sides
    connectSideSlots(m_side1, Side::First, &TaskExtrudeParameters::onModeChanged_Side1);
    connectSideSlots(m_side2, Side::Second, &TaskExtrudeParameters::onModeChanged_Side2);

    connect(ui->startMode, qOverload<int>(&QComboBox::currentIndexChanged), this, [this](int type) {
        onStartModeChanged(type);
    });
    connect(
        ui->startOffsetEdit,
        qOverload<double>(&Gui::PrefQuantitySpinBox::valueChanged),
        this,
        [this](double value) { onStartOffsetChanged(value); }
    );

    // clang-format off
    connect(ui->directionCB, qOverload<int>(&QComboBox::activated),
            this, &TaskExtrudeParameters::onDirectionCBChanged);
    connect(ui->checkBoxAlongDirection, &QCheckBox::toggled,
            this, &TaskExtrudeParameters::onAlongSketchNormalChanged);
    connect(ui->XDirectionEdit, qOverload<double>(&QDoubleSpinBox::valueChanged),
            this, &TaskExtrudeParameters::onXDirectionEditChanged);
    connect(ui->YDirectionEdit, qOverload<double>(&QDoubleSpinBox::valueChanged),
            this, &TaskExtrudeParameters::onYDirectionEditChanged);
    connect(ui->ZDirectionEdit, qOverload<double>(&QDoubleSpinBox::valueChanged),
            this, &TaskExtrudeParameters::onZDirectionEditChanged);
    connect(ui->checkBoxReversed, &QCheckBox::toggled,
            this, &TaskExtrudeParameters::onReversedChanged);
    connect(ui->sidesMode, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskExtrudeParameters::onSidesModeChanged);
    connect(ui->checkBoxUpdateView, &QCheckBox::toggled,
            this, &TaskExtrudeParameters::onUpdateView);
    // clang-format on
}

void TaskExtrudeParameters::onModeChanged_Side1(int index)
{
    onModeChanged(index, Side::First);
    setGizmoPositions();
}

void TaskExtrudeParameters::onModeChanged_Side2(int index)
{
    onModeChanged(index, Side::Second);
    setGizmoPositions();
}

void TaskExtrudeParameters::tryRecomputeFeature()
{
    try {
        // recompute and update the direction
        recomputeFeature();
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

void TaskExtrudeParameters::onSelectionChanged(const Gui::SelectionChanges& /*msg*/)
{
    // The picks are the reference fields' (ops#150)
}

bool TaskExtrudeParameters::followProfile()
{
    auto profileBased = getObject<PartDesign::ProfileBased>();
    if (!profileBased || axesInList.empty()) {
        return false;
    }
    App::DocumentObject* profile = profileBased->Profile.getValue();
    App::DocumentObject* old = directionProfile.getObject();
    if (profile == old) {
        return false;
    }
    bool changed = false;
    const std::vector<std::string> normal {"N_Axis"};
    if (old && propReferenceAxis->getValue() == old && propReferenceAxis->getSubValues() == normal) {
        // As a command, so a recorded macro moves the direction with the profile
        if (profile && profile->isDerivedFrom<Part::Part2DObject>()) {
            FCMD_OBJ_CMD(
                profileBased,
                "ReferenceAxis = (" << Gui::Command::getObjectCmd(profile) << ", ['N_Axis'])"
            );
        }
        else {
            FCMD_OBJ_CMD(profileBased, "ReferenceAxis = None");
        }
        changed = true;
    }
    // The list first: onDirectionCBChanged returns on an empty one
    axesInList.clear();
    ui->directionCB->clear();
    return changed;
}

void TaskExtrudeParameters::onReferencesRepaired()
{
    for (ReferenceField* field : referenceFields()) {
        field->reload();
    }
    if (followProfile()) {
        tryRecomputeFeature();
    }
    fillDirectionCombo();
}

void TaskExtrudeParameters::onReferenceSelectionTaken()
{
    // The fields disarm through their group; the panel has no pick mode of its own to end
}

void TaskExtrudeParameters::onLengthChanged(double len, Side side)
{
    getSideController(side).Length->setValue(len);
    tryRecomputeFeature();
}

void TaskExtrudeParameters::onStartOffsetChanged(double len)
{
    getObject<PartDesign::FeatureExtrude>()->StartOffset.setValue(len);
    tryRecomputeFeature();
    setGizmoPositions();
}

void TaskExtrudeParameters::onStartModeChanged(int type)
{
    auto extrude = getObject<PartDesign::FeatureExtrude>();
    const auto mode = static_cast<StartMode>(type);
    extrude->StartType.setValue(type);
    updateStartUI();
    // A start reference to pick: its field arms
    if (mode == StartMode::Reference && !extrude->StartReference.getValue()) {
        armField(startField);
    }
    tryRecomputeFeature();
    setGizmoPositions();
}

void TaskExtrudeParameters::onOffsetChanged(double len, Side side)
{
    getSideController(side).Offset->setValue(len);
    tryRecomputeFeature();
}

void TaskExtrudeParameters::onTaperChanged(double angle, Side side)
{
    getSideController(side).TaperAngle->setValue(angle);
    tryRecomputeFeature();
}

bool TaskExtrudeParameters::hasProfileFace(PartDesign::ProfileBased* profile) const
{
    try {
        Part::Feature* pcFeature = profile->getVerifiedObject();
        Base::Vector3d SketchVector = profile->getProfileNormal();
        Q_UNUSED(pcFeature)
        Q_UNUSED(SketchVector)
        return true;
    }
    catch (const Base::Exception&) {
    }

    return false;
}

void TaskExtrudeParameters::fillDirectionCombo()
{
    Base::StateLocker lock(getUpdateBlockRef(), true);

    if (axesInList.empty()) {
        bool hasFace = false;
        ui->directionCB->clear();
        // we can have sketches or faces
        // for sketches just get the sketch normal
        auto pcFeat = getObject<PartDesign::ProfileBased>();
        directionProfile = App::DocumentObjectT(pcFeat->Profile.getValue());
        Part::Part2DObject* pcSketch = dynamic_cast<Part::Part2DObject*>(pcFeat->Profile.getValue());
        // for faces we test if it is verified and if we can get its normal
        if (!pcSketch) {
            hasFace = hasProfileFace(pcFeat);
        }

        if (pcSketch) {
            addAxisToCombo(pcSketch, "N_Axis", tr("Sketch normal"));
        }
        else if (hasFace) {
            addAxisToCombo(pcFeat->Profile.getValue(), std::string(), tr("Face normal"), false);
        }

        // add the other entries
        addAxisToCombo(nullptr, std::string(), tr("Select reference…"));

        // we start with the sketch normal as proposal for the custom direction
        if (pcSketch) {
            addAxisToCombo(pcSketch, "N_Axis", tr("Custom direction"));
        }
        else if (hasFace) {
            addAxisToCombo(pcFeat->Profile.getValue(), std::string(), tr("Custom direction"), false);
        }
    }

    // add current link, if not in list
    // first, figure out the item number for current axis
    int indexOfCurrent = -1;
    App::DocumentObject* ax = propReferenceAxis->getValue();
    const std::vector<std::string>& subList = propReferenceAxis->getSubValues();
    for (size_t i = 0; i < axesInList.size(); i++) {
        if (ax == axesInList[i]->getValue() && subList == axesInList[i]->getSubValues()) {
            indexOfCurrent = i;
            break;
        }
    }
    // if the axis is not yet listed in the combobox
    if (indexOfCurrent == -1 && ax) {
        assert(subList.size() <= 1);
        std::string sub;
        if (!subList.empty()) {
            sub = subList[0];
        }
        addAxisToCombo(ax, sub, getRefStr(ax, subList));
        indexOfCurrent = axesInList.size() - 1;
        // the axis is not the normal, thus enable along direction
        ui->checkBoxAlongDirection->setEnabled(true);
        // we don't have custom direction thus disable its settings
        ui->XDirectionEdit->setEnabled(false);
        ui->YDirectionEdit->setEnabled(false);
        ui->ZDirectionEdit->setEnabled(false);
    }

    // highlight either current index or set custom direction
    auto extrude = getObject<PartDesign::FeatureExtrude>();
    bool hasCustom = extrude->UseCustomVector.getValue();
    if (indexOfCurrent != -1 && !hasCustom) {
        ui->directionCB->setCurrentIndex(indexOfCurrent);
        updateDirectionEdits();
        setDirectionMode(indexOfCurrent);
    }
    if (hasCustom) {
        ui->directionCB->setCurrentIndex(DirectionModes::Custom);
        setDirectionMode(ui->directionCB->currentIndex());
    }
}

void TaskExtrudeParameters::addAxisToCombo(
    App::DocumentObject* linkObj,
    std::string linkSubname,
    QString itemText,
    bool hasSketch
)
{
    this->ui->directionCB->addItem(itemText);
    this->axesInList.emplace_back(new App::PropertyLinkSub);
    App::PropertyLinkSub& lnk = *(axesInList.back());
    // if we have a face, we leave the link empty since we cannot
    // store the face normal as sublink
    if (hasSketch) {
        lnk.setValue(linkObj, std::vector<std::string>(1, linkSubname));
    }
}

void TaskExtrudeParameters::updateWholeUI(Type type, Side side)
{
    SidesMode sidesMode = static_cast<SidesMode>(ui->sidesMode->currentIndex());
    Mode mode1 = static_cast<Mode>(ui->changeMode->currentIndex());
    Mode mode2 = static_cast<Mode>(ui->changeMode2->currentIndex());

    // --- Global UI visibility based on SidesMode ---
    const bool isSide2GroupVisible = (sidesMode == SidesMode::TwoSides);
    ui->side1Label->setVisible(isSide2GroupVisible);
    ui->line1->setVisible(isSide2GroupVisible);
    ui->side2Label->setVisible(isSide2GroupVisible);
    ui->line2->setVisible(isSide2GroupVisible);
    ui->typeLabel2->setVisible(isSide2GroupVisible);
    ui->changeMode2->setVisible(isSide2GroupVisible);

    // --- Configure each side using the helper method ---
    // Side 1 is always conceptually visible, and we pass whether it should receive focus.
    updateSideUI(m_side1, type, mode1, true, (side == Side::First));
    // Side 2 is only visible if in TwoSides mode, and we pass whether it should receive focus.
    updateSideUI(m_side2, type, mode2, isSide2GroupVisible, (side == Side::Second));

    ui->checkBoxReversed->setEnabled(sidesMode != SidesMode::Symmetric || mode1 != Mode::Dimension);
}

void TaskExtrudeParameters::updateSideUI(
    const SideController& s,
    Type featureType,
    Mode sideMode,
    bool isParentVisible,
    bool setFocus
)
{
    // Default states for all controls for this side
    bool isLengthVisible = false;
    bool isOffsetVisible = false;
    bool isTaperVisible = false;
    bool isFaceVisible = false;
    bool isShapeVisible = false;

    // This logic block is a direct translation of the original 'if/else if' chain
    if (sideMode == Mode::Dimension) {
        isLengthVisible = true;
        isTaperVisible = true;
        if (setFocus) {
            s.lengthEdit->selectNumber();
            QMetaObject::invokeMethod(s.lengthEdit, "setFocus", Qt::QueuedConnection);
        }
    }
    else if (sideMode == Mode::ThroughAll && featureType == Type::Pocket) {
        isTaperVisible = true;
    }
    else if (sideMode == Mode::ToLast && featureType == Type::Pad) {
        isOffsetVisible = true;
    }
    else if (sideMode == Mode::ToFirst) {
        isOffsetVisible = true;
    }
    else if (sideMode == Mode::ToFace) {
        isOffsetVisible = true;
        isFaceVisible = true;
        // No face yet: its field arms (on open the dialog arms it, as the first empty one)
        if (setFocus && s.faceField->entries().empty()) {
            armField(s.faceField);
        }
    }
    else if (sideMode == Mode::ToShape) {
        isShapeVisible = true;
        if (setFocus && !s.checkBoxAllFaces->isChecked()) {
            armField(s.shapeFacesField);
        }
    }

    // Apply visibility based on the logic above AND the parent visibility.
    // This single 'isParentVisible' check correctly hides all of Side 2's UI at once.
    const bool finalLengthVisible = isParentVisible && isLengthVisible;
    s.labelLength->setVisible(finalLengthVisible);
    s.lengthEdit->setVisible(finalLengthVisible);
    s.lengthEdit->setEnabled(finalLengthVisible);

    const bool finalOffsetVisible = isParentVisible && isOffsetVisible;
    s.labelOffset->setVisible(finalOffsetVisible);
    s.offsetEdit->setVisible(finalOffsetVisible);
    s.offsetEdit->setEnabled(finalOffsetVisible);

    const bool finalTaperVisible = isParentVisible && isTaperVisible;
    s.labelTaperAngle->setVisible(finalTaperVisible);
    s.taperEdit->setVisible(finalTaperVisible);
    s.taperEdit->setEnabled(finalTaperVisible);

    // A hidden field doesn't pick
    const bool faceShown = isParentVisible && isFaceVisible;
    s.faceField->setVisible(faceShown);
    s.faceField->setRequired(faceShown);
    if (!faceShown) {
        s.faceField->setArmed(false);
    }

    const bool shapeShown = isParentVisible && isShapeVisible;
    s.upToShapeList->setVisible(shapeShown);
    if (!shapeShown) {
        s.shapeField->setArmed(false);
        s.shapeFacesField->setArmed(false);
    }
}

void TaskExtrudeParameters::onDirectionCBChanged(int num)
{
    if (axesInList.empty()) {
        return;
    }

    // we use this scheme for 'num'
    // 0: normal to sketch or face
    // 1: selection mode
    // 2: custom
    // 3-x: edges selected in the 3D model

    // check the axis
    // when the link is empty we are either in selection mode
    // or we are normal to a face
    App::PropertyLinkSub& lnk = *(axesInList[num]);

    if (num == DirectionModes::Select) {
        // The hidden direction field takes the next pick (ops#150)
        setDirectionMode(num);
        axisField->setArmed(true);
    }
    else if (auto extrude = getObject<PartDesign::FeatureExtrude>()) {
        if (lnk.getValue()) {
            if (!extrude->getDocument()->isIn(lnk.getValue())) {
                Base::Console().error("Object was deleted\n");
                return;
            }
            propReferenceAxis->Paste(lnk);
        }

        // in case the user is in selection mode, but changed his mind before selecting anything
        axisField->setArmed(false);
        setDirectionMode(num);

        extrude->ReferenceAxis.setValue(lnk.getValue(), lnk.getSubValues());
        tryRecomputeFeature();
        updateDirectionEdits();

        setGizmoPositions();
    }
}

void TaskExtrudeParameters::onAlongSketchNormalChanged(bool on)
{
    if (auto extrude = getObject<PartDesign::FeatureExtrude>()) {
        extrude->AlongSketchNormal.setValue(on);
        tryRecomputeFeature();

        setGizmoPositions();
    }
}

void TaskExtrudeParameters::onAllFacesToggled(bool on, Side side)
{
    auto& sideCtrl = getSideController(side);
    sideCtrl.upToShapeFaces->setVisible(!on);

    if (on) {
        // All faces of this side's shape (it was always the first side's)
        sideCtrl.shapeFacesField->setArmed(false);
        if (!sideCtrl.shapeFacesField->entries().empty()) {
            sideCtrl.UpToShape->setValue(sideCtrl.UpToShape->getValue());
            tryRecomputeFeature();
        }
    }
    else {
        armField(sideCtrl.shapeFacesField);
    }
}

void TaskExtrudeParameters::onXDirectionEditChanged(double len)
{
    if (auto extrude = getObject<PartDesign::FeatureExtrude>()) {
        extrude->Direction
            .setValue(len, extrude->Direction.getValue().y, extrude->Direction.getValue().z);
        tryRecomputeFeature();
        // checking for case of a null vector is done in FeatureExtrude.cpp
        // if there was a null vector, the normal vector of the sketch is used.
        // therefore the vector component edits must be updated
        updateDirectionEdits();
        setGizmoPositions();
    }
}

void TaskExtrudeParameters::onYDirectionEditChanged(double len)
{
    if (auto extrude = getObject<PartDesign::FeatureExtrude>()) {
        extrude->Direction
            .setValue(extrude->Direction.getValue().x, len, extrude->Direction.getValue().z);
        tryRecomputeFeature();
        updateDirectionEdits();
        setGizmoPositions();
    }
}

void TaskExtrudeParameters::onZDirectionEditChanged(double len)
{
    if (auto extrude = getObject<PartDesign::FeatureExtrude>()) {
        extrude->Direction
            .setValue(extrude->Direction.getValue().x, extrude->Direction.getValue().y, len);
        tryRecomputeFeature();
        updateDirectionEdits();
        setGizmoPositions();
    }
}

void TaskExtrudeParameters::updateDirectionEdits()
{
    auto extrude = getObject<PartDesign::FeatureExtrude>();
    // we don't want to execute the onChanged edits, but just update their contents
    QSignalBlocker xdir(ui->XDirectionEdit);
    QSignalBlocker ydir(ui->YDirectionEdit);
    QSignalBlocker zdir(ui->ZDirectionEdit);
    ui->XDirectionEdit->setValue(extrude->Direction.getValue().x);
    ui->YDirectionEdit->setValue(extrude->Direction.getValue().y);
    ui->ZDirectionEdit->setValue(extrude->Direction.getValue().z);
}

void TaskExtrudeParameters::setDirectionMode(int index)
{
    auto extrude = getObject<PartDesign::FeatureExtrude>();
    if (!extrude) {
        return;
    }

    switch (index) {

        case DirectionModes::Normal:
            ui->groupBoxDirection->hide();

            extrude->UseCustomVector.setValue(false);
            ui->XDirectionEdit->setEnabled(false);
            ui->YDirectionEdit->setEnabled(false);
            ui->ZDirectionEdit->setEnabled(false);

            ui->checkBoxAlongDirection->setEnabled(false);
            ui->checkBoxAlongDirection->hide();

            break;

            // Covered by the default option
            // case DirectionModes::Select:

        case DirectionModes::Custom:
            ui->groupBoxDirection->show();

            extrude->UseCustomVector.setValue(true);
            ui->XDirectionEdit->setEnabled(true);
            ui->YDirectionEdit->setEnabled(true);
            ui->ZDirectionEdit->setEnabled(true);

            ui->checkBoxAlongDirection->setEnabled(true);
            ui->checkBoxAlongDirection->show();
            break;

        default:
            ui->groupBoxDirection->show();

            updateDirectionEdits();

            extrude->UseCustomVector.setValue(false);
            ui->XDirectionEdit->setEnabled(false);
            ui->YDirectionEdit->setEnabled(false);
            ui->ZDirectionEdit->setEnabled(false);

            ui->checkBoxAlongDirection->setEnabled(true);
            ui->checkBoxAlongDirection->show();
            break;
    }
}

void TaskExtrudeParameters::onReversedChanged(bool on)
{
    if (auto extrude = getObject<PartDesign::FeatureExtrude>()) {
        extrude->Reversed.setValue(on);
        // update the direction
        tryRecomputeFeature();
        updateDirectionEdits();

        setGizmoPositions();
    }
}

void TaskExtrudeParameters::getReferenceAxis(App::DocumentObject*& obj, std::vector<std::string>& sub) const
{
    if (axesInList.empty()) {
        throw Base::RuntimeError("Not initialized!");
    }

    int num = ui->directionCB->currentIndex();
    const App::PropertyLinkSub& lnk = *(axesInList[num]);
    if (!lnk.getValue()) {
        // Note: It is possible that a face of an object is directly padded/pocketed without
        // defining a profile shape
        obj = nullptr;
        sub.clear();
    }
    else {
        auto pcDirection = getObject<PartDesign::ProfileBased>();
        if (!pcDirection->getDocument()->isIn(lnk.getValue())) {
            throw Base::RuntimeError("Object was deleted");
        }

        obj = lnk.getValue();
        sub = lnk.getSubValues();
    }
}

double TaskExtrudeParameters::getOffset() const
{
    return ui->offsetEdit->value().getValue();
}

double TaskExtrudeParameters::getOffset2() const
{
    return ui->offsetEdit2->value().getValue();
}

bool TaskExtrudeParameters::getAlongSketchNormal() const
{
    return ui->checkBoxAlongDirection->isChecked();
}

bool TaskExtrudeParameters::getCustom() const
{
    return (ui->directionCB->currentIndex() == DirectionModes::Custom);
}

std::string TaskExtrudeParameters::getReferenceAxis() const
{
    std::vector<std::string> sub;
    App::DocumentObject* obj;
    getReferenceAxis(obj, sub);
    return buildLinkSingleSubPythonStr(obj, sub);
}

double TaskExtrudeParameters::getXDirection() const
{
    return ui->XDirectionEdit->value();
}

double TaskExtrudeParameters::getYDirection() const
{
    return ui->YDirectionEdit->value();
}

double TaskExtrudeParameters::getZDirection() const
{
    return ui->ZDirectionEdit->value();
}

bool TaskExtrudeParameters::getReversed() const
{
    return ui->checkBoxReversed->isChecked();
}

int TaskExtrudeParameters::getMode() const
{
    return ui->changeMode->currentIndex();
}

int TaskExtrudeParameters::getMode2() const
{
    return ui->changeMode2->currentIndex();
}

int TaskExtrudeParameters::getSidesMode() const
{
    return ui->sidesMode->currentIndex();
}

void TaskExtrudeParameters::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        QSignalBlocker length(ui->lengthEdit);
        QSignalBlocker length2(ui->lengthEdit2);
        QSignalBlocker offset(ui->offsetEdit);
        QSignalBlocker offset2(ui->offsetEdit2);
        QSignalBlocker taper(ui->taperEdit);
        QSignalBlocker taper2(ui->taperEdit2);
        QSignalBlocker xdir(ui->XDirectionEdit);
        QSignalBlocker ydir(ui->YDirectionEdit);
        QSignalBlocker zdir(ui->ZDirectionEdit);
        QSignalBlocker dir(ui->directionCB);
        QSignalBlocker mode(ui->changeMode);
        QSignalBlocker mode2(ui->changeMode2);
        QSignalBlocker sidesMode(ui->sidesMode);

        // Save all items
        QStringList items;
        for (int i = 0; i < ui->directionCB->count(); i++) {
            items << ui->directionCB->itemText(i);
        }

        // Translate direction items
        int index = ui->directionCB->currentIndex();
        ui->retranslateUi(proxy);

        // Keep custom items
        for (int i = 0; i < ui->directionCB->count(); i++) {
            items.pop_front();
        }
        ui->directionCB->addItems(items);
        ui->directionCB->setCurrentIndex(index);

        // Translate mode items
        translateModeList(ui->changeMode, ui->changeMode->currentIndex());
        translateModeList(ui->changeMode2, ui->changeMode2->currentIndex());
        translateSidesList(ui->sidesMode->currentIndex());
    }
}

void TaskExtrudeParameters::saveHistory()
{
    // save the user values to history
    ui->lengthEdit->pushToHistory();
    ui->lengthEdit2->pushToHistory();
    ui->offsetEdit->pushToHistory();
    ui->offsetEdit2->pushToHistory();
    ui->taperEdit->pushToHistory();
    ui->taperEdit2->pushToHistory();
}

void TaskExtrudeParameters::applyParameters()
{
    auto obj = getObject();
    auto extrude = getObject<PartDesign::FeatureExtrude>();

    // A link property is written only when the panel changed it: written again with plain names
    // it would drop what it keeps per reference, a guess record or a partly resolved reference's
    // missing elements among them, without a warning (ops#127).
    auto unchanged = [](const App::PropertyLinkSub& prop,
                        const App::DocumentObject* linked,
                        const std::vector<std::string>& subs) {
        return prop.getValue() == linked
            && (prop.getSubValues(false) == subs || prop.getSubValues(true) == subs);
    };

    // Handle deprecated 'TwoLength' mode.
    int type1 = getMode();
    if (static_cast<Mode>(type1) == Mode::ToShape) {
        type1++;
    }
    int type2 = getMode2();
    if (static_cast<Mode>(type2) == Mode::ToShape) {
        type2++;
    }

    ui->lengthEdit->apply();
    ui->lengthEdit2->apply();
    ui->startOffsetEdit->apply();
    ui->taperEdit->apply();
    ui->taperEdit2->apply();
    FCMD_OBJ_CMD(obj, "UseCustomVector = " << (getCustom() ? 1 : 0));
    FCMD_OBJ_CMD(
        obj,
        "Direction = (" << getXDirection() << ", " << getYDirection() << ", " << getZDirection() << ")"
    );
    {
        App::DocumentObject* axis = nullptr;
        std::vector<std::string> axisSubs;
        getReferenceAxis(axis, axisSubs);
        if (!extrude || !unchanged(extrude->ReferenceAxis, axis, axisSubs)) {
            FCMD_OBJ_CMD(obj, "ReferenceAxis = " << getReferenceAxis());
        }
    }
    FCMD_OBJ_CMD(obj, "AlongSketchNormal = " << (getAlongSketchNormal() ? 1 : 0));
    FCMD_OBJ_CMD(obj, "SideType = " << getSidesMode());
    FCMD_OBJ_CMD(obj, "Type = " << type1);
    FCMD_OBJ_CMD(obj, "Type2 = " << type2);
    // The faces and the start reference are written by their fields as they are picked
    // (ops#150); a side that doesn't go up to a face drops its face
    if (extrude && static_cast<Mode>(getMode()) != Mode::ToFace && extrude->UpToFace.getValue()) {
        FCMD_OBJ_CMD(obj, "UpToFace = None");
    }
    if (extrude && static_cast<Mode>(getMode2()) != Mode::ToFace && extrude->UpToFace2.getValue()) {
        FCMD_OBJ_CMD(obj, "UpToFace2 = None");
    }
    FCMD_OBJ_CMD(obj, "Reversed = " << (getReversed() ? 1 : 0));
    FCMD_OBJ_CMD(obj, "Offset = " << getOffset());
    FCMD_OBJ_CMD(obj, "Offset2 = " << getOffset2());
    FCMD_OBJ_CMD(obj, "StartOffset = " << ui->startOffsetEdit->value().getValue());
    FCMD_OBJ_CMD(obj, "StartType = " << ui->startMode->currentIndex());
}

void TaskExtrudeParameters::onSidesModeChanged(int index)
{
    auto extrude = getObject<PartDesign::FeatureExtrude>();
    switch (static_cast<SidesMode>(index)) {
        case SidesMode::OneSide:
            extrude->SideType.setValue("One side");
            updateUI(Side::First);
            break;
        case SidesMode::TwoSides:
            extrude->SideType.setValue("Two sides");
            updateUI(Side::Second);
            break;
        case SidesMode::Symmetric:
            extrude->SideType.setValue("Symmetric");
            updateUI(Side::First);
            break;
    }

    recomputeFeature();
}

void TaskExtrudeParameters::updateUI(Side)
{
    // implement in sub-class
}

void TaskExtrudeParameters::translateModeList(QComboBox*, int)
{
    // implement in sub-class
}

void TaskExtrudeParameters::translateSidesList(int index)
{
    ui->sidesMode->clear();
    ui->sidesMode->addItem(tr("One sided"));
    ui->sidesMode->addItem(tr("Two sided"));
    ui->sidesMode->addItem(tr("Symmetric"));
    ui->sidesMode->setCurrentIndex(index);
}

void TaskExtrudeParameters::setupGizmos()
{
    if (GizmoContainer::isEnabled() == false) {
        return;
    }

    const auto toggleReversed = [this] {
        if (ui->checkBoxReversed->isEnabled()) {
            ui->checkBoxReversed->setChecked(!ui->checkBoxReversed->isChecked());
        }
    };

    lengthGizmo1 = new Gui::LinearGizmo(ui->lengthEdit);
    lengthGizmo1->setClickCallback(toggleReversed);
    lengthGizmo2 = new Gui::LinearGizmo(ui->lengthEdit2);
    lengthGizmo2->setClickCallback(toggleReversed);
    startOffsetGizmo = new Gui::LinearGizmo(ui->startOffsetEdit);
    startOffsetGizmo->setDraggerStyle(Gui::LinearDraggerStyle::Sphere);
    taperAngleGizmo1 = new Gui::RotationGizmo(ui->taperEdit);
    taperAngleGizmo2 = new Gui::RotationGizmo(ui->taperEdit2);

    connect(ui->sidesMode, qOverload<int>(&QComboBox::currentIndexChanged), [this](int) {
        setGizmoPositions();
    });

    gizmoContainer = GizmoContainer::create(
        {lengthGizmo1, lengthGizmo2, startOffsetGizmo, taperAngleGizmo1, taperAngleGizmo2},
        vp
    );

    setGizmoPositions();
    showDraggerHints();
}

void TaskExtrudeParameters::setGizmoPositions()
{
    if (!gizmoContainer) {
        return;
    }

    auto extrude = getObject<PartDesign::FeatureExtrude>();
    if (!extrude || extrude->isError()) {
        gizmoContainer->visible = false;
        return;
    }
    gizmoContainer->visible = true;

    PartDesign::TopoShape shape = extrude->getProfileShape();
    Base::Vector3d center = getMidPointFromProfile(shape);
    std::string sideType = std::string(extrude->SideType.getValueAsString());
    std::string extrudeType = std::string(extrude->Type.getValueAsString());
    std::string extrudeType2 = std::string(extrude->Type2.getValueAsString());
    double dir = extrude->Reversed.getValue() ? -1 : 1;

    Base::Vector3d direction = extrude->Direction.getValue() * dir;
    Base::Vector3d center1 = center;
    Base::Vector3d center2 = center;
    const bool hasStartOffset = std::strcmp(extrude->StartType.getValueAsString(), "Profile plane")
        != 0;
    try {
        const Base::Vector3d startDirection = direction.Normalized();
        const double effectiveStartOffset = extrude->getStartOffset();
        const Base::Vector3d start = startDirection * effectiveStartOffset;
        center1 += start;
        center2 += start;
        startOffsetGizmo->Gizmo::setDraggerPlacement(
            center + startDirection * (effectiveStartOffset - extrude->StartOffset.getValue()),
            direction
        );
    }
    catch (const Base::Exception&) {
    }

    startOffsetGizmo->setVisibility(hasStartOffset);

    lengthGizmo1->Gizmo::setDraggerPlacement(center1, direction);
    lengthGizmo1->setVisibility(extrudeType == "Length");
    taperAngleGizmo1->placeOverLinearGizmo(lengthGizmo1);
    taperAngleGizmo1->setVisibility(extrudeType == "Length");
    lengthGizmo2->Gizmo::setDraggerPlacement(center2, -direction);
    lengthGizmo2->setVisibility(sideType == "Two sides" && extrudeType2 == "Length");
    taperAngleGizmo2->placeOverLinearGizmo(lengthGizmo2);
    taperAngleGizmo2->setVisibility(sideType == "Two sides" && extrudeType2 == "Length");

    Base::Vector3d padDir = extrude->Direction.getValue().Normalized();
    Base::Vector3d sketchDir = extrude->getProfileNormal().Normalized();

    double lengthFactor = padDir.Dot(sketchDir);
    double multFactor = (sideType == "Symmetric") ? 0.5 : 1.0;

    // Important note: This code assumes that nothing other than alongSketchNormal
    // and symmetric option influence the multFactor. If some custom gizmos changes
    // it then that also should be handled properly here
    if (extrude->AlongSketchNormal.getValue()) {
        lengthGizmo1->setMultFactor(multFactor / lengthFactor);
        lengthGizmo2->setMultFactor(multFactor / lengthFactor);
    }
    else {
        lengthGizmo1->setMultFactor(multFactor);
        lengthGizmo2->setMultFactor(multFactor);
    }

    gizmoContainer->calculateScaleAndOrientation();
}

TaskDlgExtrudeParameters::TaskDlgExtrudeParameters(PartDesignGui::ViewProviderExtrude* vp)
    : TaskDlgSketchBasedParameters(vp)
{}

#include "moc_TaskExtrudeParameters.cpp"
