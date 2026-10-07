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
#include <QListWidget>
#include <QMessageBox>


#include <Base/Interpreter.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Command.h>
#include <Gui/ViewProvider.h>
#include <Mod/PartDesign/App/FeatureThickness.h>
#include <Mod/Part/App/GizmoHelper.h>

#include "ui_TaskThicknessParameters.h"
#include "TaskThicknessParameters.h"

using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskThicknessParameters */

TaskThicknessParameters::TaskThicknessParameters(ViewProviderDressUp* DressUpView, QWidget* parent)
    : TaskDressUpParameters(DressUpView, false, true, parent)
    , ui(new Ui_TaskThicknessParameters)
{
    addContainerWidget();
    initControls();

    setupGizmos(DressUpView);
}

void TaskThicknessParameters::addContainerWidget()
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    this->groupLayout()->addWidget(proxy);
    createBaseField(ui->baseFieldPlaceholder);
}

void TaskThicknessParameters::initControls()
{
    auto thickness = getObject<PartDesign::Thickness>();
    double a = thickness->Value.getValue();

    ui->Value->setMinimum(0.0);
    ui->Value->setValue(a);
    ui->Value->selectAll();
    // A new thickness's faces field takes the focus when the dialog opens (Q2)
    if (!thickness->Base.getSubValues().empty()) {
        QMetaObject::invokeMethod(ui->Value, "setFocus", Qt::QueuedConnection);
    }

    // Bind input fields to properties
    ui->Value->bind(thickness->Value);

    bool r = thickness->Reversed.getValue();
    ui->checkReverse->setChecked(r);

    bool i = thickness->Intersection.getValue();
    ui->checkIntersection->setChecked(i);

    setupConnections();

    int mode = static_cast<int>(thickness->Mode.getValue());
    ui->modeComboBox->setCurrentIndex(mode);

    int join = static_cast<int>(thickness->Join.getValue());
    ui->joinComboBox->setCurrentIndex(join);

    hideOnError();
}

void TaskThicknessParameters::setupConnections()
{
    // clang-format off
    QMetaObject::connectSlotsByName(this);

    connect(ui->Value, qOverload<double>(&Gui::QuantitySpinBox::valueChanged),
            this, &TaskThicknessParameters::onValueChanged);
    connect(ui->checkReverse, &QCheckBox::toggled,
            this, &TaskThicknessParameters::onReversedChanged);
    connect(ui->checkIntersection, &QCheckBox::toggled,
            this, &TaskThicknessParameters::onIntersectionChanged);
    connect(ui->modeComboBox, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskThicknessParameters::onModeChanged);
    connect(ui->joinComboBox, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskThicknessParameters::onJoinTypeChanged);
    // clang-format on
}

void TaskThicknessParameters::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (msg.Type == Gui::SelectionChanges::ClrSelection) {
        // TODO: the gizmo position should be only recalculated when the feature associated
        // with the gizmo is removed from the list
        setGizmoPositions();
    }
}

PartDesign::Thickness* TaskThicknessParameters::onBeforeChange()
{
    // a value edit ends the picking, gate and display included (B3)
    setSelectionMode(none);
    setupTransaction();
    return getObject<PartDesign::Thickness>();
}

void TaskThicknessParameters::onAfterChange(PartDesign::Thickness* obj)
{
    obj->recomputeFeature();
    // hide the thickness if there was a computation error
    hideOnError();
}

void TaskThicknessParameters::onValueChanged(double angle)
{
    if (PartDesign::Thickness* thickness = onBeforeChange()) {
        thickness->Value.setValue(angle);
        onAfterChange(thickness);
    }
}

void TaskThicknessParameters::onJoinTypeChanged(int join)
{
    if (PartDesign::Thickness* thickness = onBeforeChange()) {
        thickness->Join.setValue(join);
        onAfterChange(thickness);
    }
}

void TaskThicknessParameters::onModeChanged(int mode)
{
    if (PartDesign::Thickness* thickness = onBeforeChange()) {
        thickness->Mode.setValue(mode);
        onAfterChange(thickness);
    }
}

double TaskThicknessParameters::getValue() const
{
    return ui->Value->value().getValue();
}

void TaskThicknessParameters::onReversedChanged(bool on)
{
    if (PartDesign::Thickness* thickness = onBeforeChange()) {
        thickness->Reversed.setValue(on);
        onAfterChange(thickness);

        setGizmoPositions();
    }
}

bool TaskThicknessParameters::getReversed() const
{
    return ui->checkReverse->isChecked();
}

void TaskThicknessParameters::onIntersectionChanged(bool on)
{
    if (PartDesign::Thickness* thickness = onBeforeChange()) {
        thickness->Intersection.setValue(on);
        onAfterChange(thickness);
    }
}

bool TaskThicknessParameters::getIntersection() const
{
    return ui->checkIntersection->isChecked();
}

int TaskThicknessParameters::getJoinType() const
{

    return ui->joinComboBox->currentIndex();
}

int TaskThicknessParameters::getMode() const
{

    return ui->modeComboBox->currentIndex();
}

TaskThicknessParameters::~TaskThicknessParameters()
{
    try {
        Gui::Selection().clearSelection();
    }
    catch (const Py::Exception&) {
        Base::PyException e;  // extract the Python error text
        e.reportException();
    }
}

void TaskThicknessParameters::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        ui->retranslateUi(proxy);
    }
}

void TaskThicknessParameters::apply()
{
    // Alert user if he created an empty feature
    if (getReferences().empty()) {
        Base::Console().warning(tr("Empty thickness created!\n").toStdString().c_str());
    }
}

void TaskThicknessParameters::setupGizmos(ViewProviderDressUp* vp)
{
    if (!GizmoContainer::isEnabled()) {
        return;
    }

    linearGizmo = new Gui::LinearGizmo(ui->Value);

    gizmoContainer = GizmoContainer::create({linearGizmo}, vp);

    setGizmoPositions();
    showDraggerHints();
}

void TaskThicknessParameters::setGizmoPositions()
{
    if (!gizmoContainer) {
        return;
    }

    auto thickness = getObject<PartDesign::Thickness>();
    if (!thickness) {
        gizmoContainer->visible = false;
        return;
    }
    auto baseShape = thickness->getBaseTopoShape();
    auto shapes = thickness->getContinuousEdges(baseShape);
    auto faces = thickness->getFaces(baseShape);

    if (shapes.size() == 0 || faces.size() == 0) {
        gizmoContainer->visible = false;
        return;
    }
    gizmoContainer->visible = true;

    Part::TopoShape edge = shapes[0];
    DraggerPlacementProps props = getDraggerPlacementFromEdgeAndFace(edge, faces[0]);
    props.dir *= thickness->Reversed.getValue() ? 1 : -1;

    linearGizmo->Gizmo::setDraggerPlacement(props.position, props.dir);
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgThicknessParameters::TaskDlgThicknessParameters(ViewProviderThickness* DressUpView)
    : TaskDlgDressUpParameters(DressUpView)
{
    parameter = new TaskThicknessParameters(DressUpView);

    Content.push_back(parameter);
    Content.push_back(preview);
}

TaskDlgThicknessParameters::~TaskDlgThicknessParameters() = default;

bool TaskDlgThicknessParameters::accept()
{
    auto obj = getObject();
    if (!obj->isError()) {
        getViewObject()->showPreviousFeature(false);
    }

    parameter->apply();

    auto draftparameter = dynamic_cast<TaskThicknessParameters*>(parameter);

    FCMD_OBJ_CMD(obj, "Value = " << draftparameter->getValue());
    FCMD_OBJ_CMD(obj, "Reversed = " << draftparameter->getReversed());
    FCMD_OBJ_CMD(obj, "Mode = " << draftparameter->getMode());
    FCMD_OBJ_CMD(obj, "Intersection = " << draftparameter->getIntersection());
    FCMD_OBJ_CMD(obj, "Join = " << draftparameter->getJoinType());

    return TaskDlgDressUpParameters::accept();
}

#include "moc_TaskThicknessParameters.cpp"
