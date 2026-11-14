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

#include <array>
#include <cmath>
#include <cstring>
#include <vector>
#include <QAbstractButton>
#include <QCheckBox>
#include <QGridLayout>
#include <QListView>
#include <QPointer>
#include <QSignalBlocker>
#include <QTimer>
#include <QVBoxLayout>
#include <Precision.hxx>
#include <Standard_Failure.hxx>

#include <App/Datums.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Origin.h>
#include <Base/Console.h>
#include <Base/Converter.h>
#include <Base/Rotation.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/CommandT.h>
#include <Gui/MainWindow.h>
#include <Gui/Selection/Selection.h>
#include <Gui/ViewProvider.h>
#include <Gui/ViewProviderCoordinateSystem.h>
#include <Gui/Inventor/Draggers/Gizmo.h>
#include <Gui/Utilities.h>
#include <Gui/Inventor/Draggers/SoRotationDragger.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/PartDesign/App/FeatureRevolved.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/DatumPoint.h>

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

// Onshape's Revolve defaults (hands-on B-5, ops#640 rank 21): Full revolve unticked gives 30 deg;
// Second end position, "Start angle 330 deg" measured the first end's way, is 30 deg the other
// way here (Angle2 turns against Angle)
constexpr double fullTurn = 360.0;
constexpr double blindDefault = 30.0;
constexpr double secondEndDefault = 30.0;

bool isFullTurn(double angle)
{
    return std::fabs(angle) >= fullTurn - Precision::Angular();
}

// What a Revolve's profile takes (ops#640 rank 21, as an Extrude's): a sketch or other 2D object,
// whole or by its regions or edges, or planar faces of the solid before. \a why: the refusal
bool acceptRevolveProfile(
    const App::DocumentObject* feature,
    const App::DocumentObject* base,
    App::DocumentObject* obj,
    const char* sub,
    std::string& why
)
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
    if (obj->isDerivedFrom<Part::Part2DObject>()) {
        if (element.empty() || startsWith("Edge") || startsWith("Face")
            || startsWith("InternalFace") || startsWith("Wire")) {
            return true;
        }
        why = QT_TR_NOOP("Pick the sketch, its regions or its edges.");
        return false;
    }
    if (obj == base && startsWith("Face")) {
        auto feat = freecad_cast<Part::Feature*>(obj);
        try {
            const Part::TopoShape face(
                feat ? feat->Shape.getShape().getSubShape(element.c_str(), /*silent=*/true)
                     : TopoDS_Shape()
            );
            if (!face.isNull() && face.isPlanar()) {
                return true;
            }
        }
        catch (const Base::Exception&) {
        }
        catch (const Standard_Failure&) {
        }
        why = QT_TR_NOOP("Pick a planar face.");
        return false;
    }
    why = QT_TR_NOOP("Pick a sketch, its regions or edges, or faces of the solid.");
    return false;
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
        // The class, not the Operation: a Revolution can cut and a Groove can add (ops#640 rank
        // 20), and each keeps its end types (index 1: Up to last, or Through all)
        isGroove = rev->isDerivedFrom<PartDesign::Groove>();
        this->propSideType = &(rev->SideType);
        this->propReferenceAxis = &(rev->ReferenceAxis);
        this->propReversed = &(rev->Reversed);
    }
    else {
        throw Base::TypeError("The object is neither a groove nor a revolution.");
    }

    setupDialog();
    // the user's choice, kept through axis picks: Reversed against the axis's suggestion. With
    // no suggestion (no valid axis yet) there is no choice to keep (ops#276: Reversed's own value
    // was taken as one, and the first pick said "as you set it")
    if (auto rev = getObject<PartDesign::Revolved>()) {
        const auto suggested = rev->suggestedReversed();
        userFlip = suggested && propReversed->getValue() != *suggested;
    }

    setUpdateBlocked(false);
    updateUI(Side::First);
    connectSignals();

    setFocus();

    // show the parts coordinate system axis for selection; a new part studio's planes stay
    // (ops#626, rank 52)
    try {
        if (auto vpOrigin = getOriginView()) {
            studioPlanes = vpOrigin->isTemporaryVisibility();
            vpOrigin->setTemporaryVisibility(
                studioPlanes ? Gui::DatumElement::Axes | Gui::DatumElement::Planes
                             : Gui::DatumElement::Axes
            );
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
    createOnshapeFields();
}

void TaskRevolutionParameters::createFields()
{
    createProfileField();
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
    // Each side's face, vertex and part share the face's row (ops#640 rank 21): a holder in the
    // placeholder's place, the fields one under the other, all on UpToFace
    auto sideFields = [this, baseSolid, &faceField](SideController& side,
                                                   QWidget* placeholder,
                                                   const char* property,
                                                   bool first) {
        auto holder = new QWidget(proxy);
        holder->setObjectName(first ? QStringLiteral("upToFaceVertexOrPart")
                                    : QStringLiteral("upToFaceVertexOrPart2"));
        auto layout = new QVBoxLayout(holder);
        layout->setContentsMargins(0, 0, 0, 0);
        std::array<QWidget*, 3> cells {};
        for (QWidget*& cell : cells) {
            cell = new QWidget(holder);
            layout->addWidget(cell);
        }
        if (QWidget* parent = placeholder->parentWidget(); parent && parent->layout()) {
            delete parent->layout()->replaceWidget(placeholder, holder, Qt::FindChildrenRecursively);
        }
        placeholder->hide();
        placeholder->deleteLater();
        side.faceField = faceField(cells[0], property, tr("Face"), true);

        auto make = [this, property](const ReferenceField::Options& options,
                                     QWidget* where,
                                     const QString& name) {
            auto self = std::make_shared<QPointer<ReferenceField>>();
            auto write = [this, self](App::DocumentObject* obj,
                                      const std::vector<std::string>& subs) {
                if (*self) {
                    (*self)->assign(obj, subs);
                }
                recomputeFeature();
                setGizmoPositions();
            };
            auto field = new ReferenceField(getObject(), property, options, write, proxy);
            *self = field;
            field->setObjectName(name);
            field->takePlaceOf(where);
            return field;
        };
        // Up to vertex: a vertex of a part or a sketch, or a datum point
        ReferenceField::Options vertex = faceFieldOptions(tr("Vertex"), baseSolid, false);
        vertex.flags = AllowSelection::POINT;
        vertex.kinds = tr("A vertex or a point");
        side.vertexField = make(vertex,
                                cells[1],
                                first ? QStringLiteral("fieldUpToVertex")
                                      : QStringLiteral("fieldUpToVertex2"));
        // Up to part: a pick takes its part, whole
        ReferenceField::Options part;
        part.kind = ReferenceField::Kind::SingleElement;
        part.wholeObject = true;
        part.target = baseSolid;
        part.required = false;
        part.noDependents = true;
        part.label = tr("Part");
        part.kinds = tr("A part");
        side.partField = make(part,
                              cells[2],
                              first ? QStringLiteral("fieldUpToPart") : QStringLiteral("fieldUpToPart2"));
    };
    sideFields(m_side1, ui->faceFieldPlaceholder, "UpToFace", true);
    sideFields(m_side2, ui->faceFieldPlaceholder2, "UpToFace2", false);

    // The axis: the box's choices, and a picked edge or line in the row under it, through the
    // cross-body question as before
    ReferenceField::Options axis;
    axis.kind = ReferenceField::Kind::SingleElement;
    axis.flags = AllowSelection::EDGE | AllowSelection::PLANAR | AllowSelection::CIRCLE;
    axis.target = baseSolid;
    // Required: a new Revolve has none, and its dialog opens waiting for the pick, Onshape's way
    // (FreeCAD-CH ops#643): the first empty required field is armed (armFirstEmpty)
    axis.required = true;
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
    for (ReferenceField* field : {profileField,
                                  startField,
                                  m_side1.faceField,
                                  m_side1.vertexField,
                                  m_side1.partField,
                                  m_side2.faceField,
                                  m_side2.vertexField,
                                  m_side2.partField,
                                  axisField}) {
        if (field) {
            fields.push_back(field);
        }
    }
    return fields;
}

void TaskRevolutionParameters::createProfileField()
{
    // The profile on top, as an Extrude's (ops#640 rank 21): a new Revolve opens with it armed
    // when nothing was preselected (the first empty required field), a preselected sketch fills
    // it (hands-on B-2)
    ReferenceField::Options profile;
    profile.kind = ReferenceField::Kind::Profile;
    // The solid before shows while it is armed
    profile.target = [this]() -> App::DocumentObject* {
        auto revolved = getObject<PartDesign::ProfileBased>();
        return revolved ? revolved->getBaseObject(/*silent=*/true) : nullptr;
    };
    App::DocumentObjectT featureT(getObject());
    profile.accept = [featureT](App::DocumentObject* obj, const char* sub, std::string& why) {
        auto revolved = freecad_cast<PartDesign::ProfileBased*>(featureT.getObject());
        App::DocumentObject* base = revolved ? revolved->getBaseObject(/*silent=*/true) : nullptr;
        return acceptRevolveProfile(revolved, base, obj, sub, why);
    };
    // A sketch attached to the feature itself would make a cycle
    profile.noDependents = true;
    profile.label = tr("Profile");
    profile.kinds = tr("A sketch, its regions or edges, or faces of the solid");
    auto self = std::make_shared<QPointer<ReferenceField>>();
    auto write = [this, self](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        // Regions of a sketch need the multi-face profile (an older feature's whole sketch keeps
        // its face maker)
        auto revolved = getObject<PartDesign::ProfileBased>();
        if (revolved && !subs.empty() && !revolved->AllowMultiFace.getValue()) {
            revolved->AllowMultiFace.setValue(true);
        }
        if (*self) {
            (*self)->assign(obj, subs);
        }
        // The axis box lists the new sketch's axes
        fillAxisCombo(true);
        recomputeFeature();
        setGizmoPositions();
        // A new Revolve's first tool decides where it opens (FreeCAD-CH ops#640, round 3)
        TaskResultParameters::profileTaken(getObject());
    };
    profileField = new ReferenceField(getObject(), "Profile", profile, write, proxy);
    *self = profileField;
    profileField->setObjectName(QStringLiteral("fieldProfile"));
    ui->verticalLayout->insertWidget(0, profileField);
}

void TaskRevolutionParameters::createOnshapeFields()
{
    QGridLayout* grid = ui->gridLayout;
    // The Sides box goes (its index is still what apply() writes), and so does the first side's
    // header: Full revolve takes its row, under the axis
    grid->removeWidget(ui->sidesLabel);
    grid->removeWidget(ui->sidesMode);
    ui->sidesLabel->hide();
    ui->sidesMode->hide();
    auto takeLayout = [grid](QLayout* layout,
                             int& row,
                             int& column,
                             int& rowSpan,
                             int& columnSpan) {
        for (int index = 0; index < grid->count(); ++index) {
            if (grid->itemAt(index)->layout() == layout) {
                grid->getItemPosition(index, &row, &column, &rowSpan, &columnSpan);
                grid->takeAt(index);
                if (layout->parent()) {
                    layout->setParent(nullptr);
                }
                return true;
            }
        }
        return false;
    };
    int row = 0;
    int column = 0;
    int rowSpan = 0;
    int columnSpan = 0;
    ui->side1Label->hide();
    ui->line1->hide();
    if (takeLayout(ui->side1HeaderLayout, row, column, rowSpan, columnSpan)) {
        delete ui->side1HeaderLayout;  // its widgets stay, hidden, in the proxy
        ui->side1HeaderLayout = nullptr;
    }
    // The second side moves down four rows: Flip, Symmetric and Second end position come between
    // the first end and the second, as in Onshape's dialog
    constexpr int firstSide2Row = 10;
    constexpr int shift = 4;
    struct Moved
    {
        QLayoutItem* item;
        int row;
        int column;
        int rowSpan;
        int columnSpan;
    };
    std::vector<Moved> moved;
    for (int index = grid->count() - 1; index >= 0; --index) {
        grid->getItemPosition(index, &row, &column, &rowSpan, &columnSpan);
        if (row < firstSide2Row) {
            continue;
        }
        QLayoutItem* item = grid->takeAt(index);
        if (item) {
            moved.push_back({item, row, column, rowSpan, columnSpan});
        }
    }
    for (const Moved& entry : moved) {
        if (QLayout* layout = entry.item->layout()) {
            if (layout->parent()) {
                layout->setParent(nullptr);
            }
            grid->addLayout(
                layout,
                entry.row + shift,
                entry.column,
                entry.rowSpan,
                entry.columnSpan
            );
        }
        else {
            grid->addItem(
                entry.item,
                entry.row + shift,
                entry.column,
                entry.rowSpan,
                entry.columnSpan
            );
        }
    }

    fullRevolve = new QCheckBox(tr("Full revolve"), proxy);
    fullRevolve->setObjectName(QStringLiteral("checkBoxFullRevolve"));
    grid->addWidget(fullRevolve, 6, 0, 1, 2);
    ui->verticalLayout->removeWidget(ui->checkBoxReversed);
    grid->addWidget(ui->checkBoxReversed, firstSide2Row, 0, 1, 2);
    symmetric = new QCheckBox(tr("Symmetric"), proxy);
    symmetric->setObjectName(QStringLiteral("checkBoxSymmetric"));
    grid->addWidget(symmetric, firstSide2Row + 1, 0, 1, 2);
    secondEnd = new QCheckBox(tr("Second end position"), proxy);
    secondEnd->setObjectName(QStringLiteral("checkBoxSecondEnd"));
    grid->addWidget(secondEnd, firstSide2Row + 2, 0, 1, 2);

    connect(fullRevolve, &QCheckBox::toggled, this, [this](bool on) {
        onFullRevolveToggled(on);
    });
    connect(symmetric, &QCheckBox::toggled, this, [this](bool on) {
        onSymmetricToggled(on);
    });
    connect(secondEnd, &QCheckBox::toggled, this, [this](bool on) {
        onSecondEndToggled(on);
    });
}

bool TaskRevolutionParameters::isFullRevolve() const
{
    return std::strcmp(propSideType->getValueAsString(), "One side") == 0
        && std::strcmp(m_side1.Type->getValueAsString(), "Angle") == 0
        && isFullTurn(m_side1.Angle->getValue());
}

void TaskRevolutionParameters::updateOnshapeUI()
{
    if (!fullRevolve) {
        return;
    }
    const auto sidesMode = static_cast<SidesMode>(ui->sidesMode->currentIndex());
    const bool full = isFullRevolve();
    {
        QSignalBlocker block(fullRevolve);
        fullRevolve->setChecked(full);
    }
    {
        QSignalBlocker block(symmetric);
        symmetric->setChecked(sidesMode == SidesMode::Symmetric);
    }
    {
        QSignalBlocker block(secondEnd);
        secondEnd->setChecked(sidesMode == SidesMode::TwoSides);
    }
    ui->sidesLabel->hide();
    ui->sidesMode->hide();
    // Full revolve: no end, no angle, no flip (Onshape's box hides them)
    ui->textLabelMode->setVisible(!full);
    ui->changeMode->setVisible(!full);
    ui->checkBoxReversed->setVisible(!full);
    if (full) {
        ui->labelAngle->hide();
        ui->revolveAngle->hide();
        ui->revolveAngle->setEnabled(false);
    }
    // Symmetric and Second end position exclude each other, as in Onshape's dialog
    symmetric->setVisible(!full && sidesMode != SidesMode::TwoSides);
    secondEnd->setVisible(!full && sidesMode != SidesMode::Symmetric);
}

void TaskRevolutionParameters::setSides(SidesMode mode)
{
    static constexpr std::array<const char*, 3> names {"One side", "Two sides", "Symmetric"};
    {
        QSignalBlocker block(ui->sidesMode);
        ui->sidesMode->setCurrentIndex(static_cast<int>(mode));
    }
    propSideType->setValue(names.at(static_cast<std::size_t>(mode)));
}

void TaskRevolutionParameters::setAngle(Side side, double angle)
{
    SideController& controller = getSideController(side);
    controller.Angle->setValue(angle);
    QSignalBlocker block(controller.angleEdit);
    controller.angleEdit->setValue(angle);
}

void TaskRevolutionParameters::onFullRevolveToggled(bool on)
{
    if (!getObject()) {
        return;
    }
    if (on) {
        setSides(SidesMode::OneSide);
        {
            QSignalBlocker block(ui->changeMode);
            ui->changeMode->setCurrentIndex(static_cast<int>(Mode::Angle));
        }
        m_side1.Type->setValue("Angle");
        setAngle(Side::First, fullTurn);
    }
    else if (isFullTurn(m_side1.Angle->getValue())) {
        // Onshape's Blind default (B-5)
        setAngle(Side::First, blindDefault);
    }
    updateUI(Side::First);
    recomputeFeature();
    setGizmoPositions();
}

void TaskRevolutionParameters::onSymmetricToggled(bool on)
{
    if (!getObject()) {
        return;
    }
    setSides(on ? SidesMode::Symmetric : SidesMode::OneSide);
    updateUI(Side::First);
    recomputeFeature();
    setGizmoPositions();
}

void TaskRevolutionParameters::onSecondEndToggled(bool on)
{
    if (!getObject()) {
        return;
    }
    if (on && std::fabs(m_side2.Angle->getValue()) < Precision::Angular()
        && std::strcmp(m_side2.Type->getValueAsString(), "Angle") == 0) {
        setAngle(Side::Second, secondEndDefault);
    }
    setSides(on ? SidesMode::TwoSides : SidesMode::OneSide);
    updateUI(on ? Side::Second : Side::First);
    recomputeFeature();
    setGizmoPositions();
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
    // Onshape's names and order (hands-on B-5, ops#640 rank 21): Blind, Up to next, Up to face,
    // Up to part, Up to vertex; each row's data is its Mode, the Type's index (\a index is one)
    auto add = [box](const QString& text, Mode mode) {
        box->addItem(text, static_cast<int>(mode));
    };
    box->clear();
    add(tr("Blind"), Mode::Angle);
    add(isGroove ? tr("Through all") : tr("To last"), Mode::ToLast);
    add(tr("Up to next"), Mode::ToFirst);
    add(tr("Up to face"), Mode::ToFace);
    add(tr("Up to part"), Mode::ToShape);
    add(tr("Up to vertex"), Mode::ToVertex);
    const int row = box->findData(index);
    box->setCurrentIndex(row >= 0 ? row : 0);
    // Onshape's Revolve has neither To last nor Through all: listed only while the feature uses it
    if (auto view = qobject_cast<QListView*>(box->view())) {
        view->setRowHidden(1, index != static_cast<int>(Mode::ToLast));
    }
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
    bool isVertexVisible = false;
    bool isPartVisible = false;

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
    else if (mode == Mode::ToVertex) {
        isVertexVisible = true;
    }
    else if (mode == Mode::ToShape) {
        isPartVisible = true;
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
    // Up to vertex's and Up to part's fields (ops#640 rank 21), as the face's
    for (auto [field, shown] : {std::pair {side.vertexField, isParentVisible && isVertexVisible},
                                std::pair {side.partField, isParentVisible && isPartVisible}}) {
        field->setVisible(shown);
        field->setRequired(shown);
        if (!shown) {
            field->setArmed(false);
        }
    }
    if (QWidget* holder = side.faceField->parentWidget()) {
        holder->setVisible(isParentVisible && (isFaceVisible || isVertexVisible || isPartVisible));
    }
}

void TaskRevolutionParameters::updateWholeUI(Side side)
{
    SidesMode sidesMode = static_cast<SidesMode>(ui->sidesMode->currentIndex());
    Mode mode1 = static_cast<Mode>(getMode());
    Mode mode2 = static_cast<Mode>(getMode2());

    const bool isSide2Visible = sidesMode == SidesMode::TwoSides;
    // No side headers: Onshape's Second end position shows its own end under its box (rank 21)
    ui->side1Label->setVisible(false);
    ui->line1->setVisible(false);
    ui->side2Label->setVisible(false);
    ui->line2->setVisible(false);
    ui->typeLabel2->setVisible(isSide2Visible);
    ui->changeMode2->setVisible(isSide2Visible);

    updateSideUI(m_side1, mode1, true, side == Side::First);
    updateSideUI(m_side2, mode2, isSide2Visible, side == Side::Second);

    const bool symmetricAngleLike = sidesMode == SidesMode::Symmetric
        && (mode1 == Mode::Angle || (isGroove && mode1 == Mode::ThroughAll));
    ui->checkBoxReversed->setEnabled(!symmetricAngleLike);
    updateOnshapeUI();
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
        // A picked axis turns the revolution the way it suggests, or the other way when the
        // user's Reversed went against the suggestion (ops#252: every pick overwrote it silently;
        // PR 245 review M1: the choice is kept relative to the suggestion, not as a value). A
        // change, or a result against the suggestion, is said once the pick's recompute is done
        // (it clears the status bar, so the message was never seen). It is queued before the
        // recompute, which can throw (ops#276: Reversed changed without a word)
        QString message;
        auto revolved = freecad_cast<PartDesign::Revolved*>(pcRevolution);
        const auto suggested = revolved ? revolved->suggestedReversed() : std::nullopt;
        if (suggested) {
            const bool reversed = *suggested != userFlip;
            const bool changed = reversed != propReversed->getValue();
            if (changed) {
                propReversed->setValue(reversed);
                QSignalBlocker block(ui->checkBoxReversed);
                ui->checkBoxReversed->setChecked(reversed);
            }
            if (userFlip) {
                message = reversed
                    ? tr("Reversed is on: the revolution turns against the way the axis suggests, "
                         "as you set it.")
                    : tr("Reversed is off: the revolution turns against the way the axis "
                         "suggests, as you set it.");
            }
            else if (changed) {
                message = reversed
                    ? tr("Reversed is now on: the revolution turns the way the axis suggests.")
                    : tr("Reversed is now off: the revolution turns the way the axis suggests.");
            }
        }
        if (!message.isEmpty()) {
            QTimer::singleShot(0, this, [message]() {
                Gui::getMainWindow()->showMessage(message, 10000);
            });
        }

        recomputeFeature();
        setGizmoPositions();
        // the axis may make its first tool: it decides where it opens (ops#640, round 3)
        TaskResultParameters::profileTaken(getObject());
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

void TaskRevolutionParameters::onModeChangedSide1(int)
{
    // the row's mode, not the row (ops#640 rank 21)
    onModeChanged(getMode(), Side::First);
}

void TaskRevolutionParameters::onModeChangedSide2(int)
{
    onModeChanged(getMode2(), Side::Second);
}

void TaskRevolutionParameters::dropUpToFaceOfOtherKind(Side side, Mode mode)
{
    if (mode != Mode::ToFace && mode != Mode::ToVertex && mode != Mode::ToShape) {
        return;  // the link stays until OK (apply() drops it), as before
    }
    App::PropertyLinkSub* link = getSideController(side).UpToFace;
    App::DocumentObject* obj = link ? link->getValue() : nullptr;
    if (!obj) {
        return;
    }
    const std::vector<std::string> subs = link->getSubValues();
    const std::string sub = subs.empty() ? std::string() : subs.front();
    App::DocumentObject* named = sub.empty() || !obj->getDocument()
        ? nullptr
        : obj->getDocument()->getObject(sub.c_str());
    // an origin point is linked whole (no LCS sub): a vertex too
    const bool isVertex = sub.starts_with("Vertex") || obj->isDerivedFrom<PartDesign::Point>()
        || obj->isDerivedFrom<App::Point>() || (named && named->isDerivedFrom<App::Point>());
    // a part is linked whole; a face or a plane by its element, or a datum or origin plane whole
    const bool isPart = !isVertex && sub.empty() && !PartDesign::Feature::isDatum(obj);
    const Mode kind = isVertex ? Mode::ToVertex : isPart ? Mode::ToShape : Mode::ToFace;
    if (kind != mode) {
        link->setValue(nullptr);
    }
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
        case Mode::ToVertex:
            sideCtrl.Type->setValue("UpToVertex");
            break;
        case Mode::ToShape:
            sideCtrl.Type->setValue("UpToShape");
            break;
    }
    dropUpToFaceOfOtherKind(side, static_cast<Mode>(index));

    updateUI(side);
    // Up to a face, a vertex or a part with none yet: its field takes the next pick
    if (static_cast<Mode>(index) == Mode::ToFace) {
        armField(sideCtrl.faceField);
    }
    else if (static_cast<Mode>(index) == Mode::ToVertex) {
        armField(sideCtrl.vertexField);
    }
    else if (static_cast<Mode>(index) == Mode::ToShape) {
        armField(sideCtrl.partField);
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
        // the user's direction: an operation switch keeps it now (ops#640 H4, rank 20; a no-op
        // until the Result box gives a Revolve the operation row)
        TaskResultParameters::noteReversedTouched(getObject());
        propReversed->setValue(on);
        if (auto revolved = getObject<PartDesign::Revolved>()) {
            const auto suggested = revolved->suggestedReversed();
            userFlip = suggested && on != *suggested;
        }
        recomputeFeature();

        setGizmoPositions();
    }
}

bool TaskRevolutionParameters::getReversed() const
{
    return ui->checkBoxReversed->isChecked();
}

namespace
{
// The end type box's rows carry their Mode (ops#640 rank 21: Onshape's order, not the Modes')
int modeOfRow(const QComboBox* box)
{
    const QVariant data = box->currentData();
    return data.isValid() ? data.toInt() : box->currentIndex();
}
}  // namespace

int TaskRevolutionParameters::getMode() const
{
    return modeOfRow(ui->changeMode);
}

int TaskRevolutionParameters::getMode2() const
{
    return modeOfRow(ui->changeMode2);
}

int TaskRevolutionParameters::getSidesMode() const
{
    return ui->sidesMode->currentIndex();
}

TaskRevolutionParameters::~TaskRevolutionParameters()
{
    // hide the parts coordinate system axis for selection; a new part studio's planes stay
    // shown, as SketchWorkflow's showStudioPlanes() shows them (ops#626, rank 52)
    try {
        if (auto vpOrigin = getOriginView()) {
            vpOrigin->resetTemporaryVisibility();
            if (studioPlanes) {
                vpOrigin->setTemporaryVisibility(Gui::DatumElement::Planes);
                vpOrigin->setPlaneLabelVisibility(true);
            }
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
        translateModeList(ui->changeMode, getMode());
        translateModeList(ui->changeMode2, getMode2());
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

    // A side that doesn't go up to a face keeps none (nor a vertex or a part, ops#640 rank 21)
    auto upToFaceKept = [](int mode) {
        const auto kind = static_cast<Mode>(mode);
        return kind == Mode::ToFace || kind == Mode::ToVertex || kind == Mode::ToShape;
    };
    if (!upToFaceKept(getMode()) && revolved->UpToFace.getValue()) {
        FCMD_OBJ_CMD(tobj, "UpToFace = None");
    }
    if (!upToFaceKept(getMode2()) && revolved->UpToFace2.getValue()) {
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
    // none on a full revolve, as in Onshape's (ops#640 rank 21)
    rotationGizmo->setVisibility(
        (revolutionType == "Angle" || isLegacyTwoAngles(revolutionType)) && !isFullRevolve()
    );

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
    addResultBox();
    Content.push_back(preview);
}

namespace
{
QString missingAxis(const App::DocumentObject* feature)
{
    auto axis = feature
        ? dynamic_cast<const App::PropertyLinkSub*>(feature->getPropertyByName("ReferenceAxis"))
        : nullptr;
    if (!axis || axis->getValue()) {
        return {};
    }
    return QObject::tr("Pick a line or an edge to revolve about");
}
}  // namespace

QString TaskDlgRevolutionParameters::missingRequired() const
{
    return missingAxis(getObject());
}

QString TaskDlgGrooveParameters::missingRequired() const
{
    return missingAxis(getObject());
}

TaskDlgGrooveParameters::TaskDlgGrooveParameters(ViewProviderGroove* GrooveView)
    : TaskDlgSketchBasedParameters(GrooveView)
{
    assert(GrooveView);
    Content.push_back(
        new TaskRevolutionParameters(GrooveView, "PartDesign_Groove", tr("Groove Parameters"))
    );
    addResultBox();
    Content.push_back(preview);
}


#include "moc_TaskRevolutionParameters.cpp"
