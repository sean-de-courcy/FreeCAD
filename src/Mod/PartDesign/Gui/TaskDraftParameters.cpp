// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer                                    *
 *                                   <jrheinlaender@users.sourceforge.net> *
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

#include <QAction>
#include <QLabel>
#include <QKeyEvent>
#include <QListWidget>
#include <QMessageBox>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <Base/Converter.h>
#include <Gui/Command.h>
#include <Base/Interpreter.h>
#include <Gui/Selection/Selection.h>
#include <Gui/ViewProvider.h>
#include <Gui/Inventor/Draggers/Gizmo.h>
#include <Gui/Inventor/Draggers/SoRotationDragger.h>
#include <Gui/Utilities.h>
#include <Mod/PartDesign/App/FeatureDraft.h>
#include <Mod/PartDesign/Gui/ReferenceSelection.h>
#include <Mod/Part/App/GizmoHelper.h>
#include <Mod/Part/App/Tools.h>

#include "ui_TaskDraftParameters.h"
#include "TaskDraftParameters.h"
#include "ReferenceField.h"

using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskDraftParameters */

TaskDraftParameters::TaskDraftParameters(ViewProviderDressUp* DressUpView, QWidget* parent)
    : TaskDressUpParameters(DressUpView, false, true, parent)
    , ui(new Ui_TaskDraftParameters)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);

    this->groupLayout()->addWidget(proxy);
    createBaseField(ui->baseFieldPlaceholder);

    PartDesign::Draft* pcDraft = DressUpView->getObject<PartDesign::Draft>();
    double a = pcDraft->Angle.getValue();

    ui->draftAngle->setMinimum(pcDraft->Angle.getMinimum());
    ui->draftAngle->setMaximum(pcDraft->Angle.getMaximum());
    ui->draftAngle->setValue(a);
    ui->draftAngle->selectAll();
    // A new draft's faces field takes the focus when the dialog opens (Q2)
    if (!pcDraft->Base.getSubValues().empty()) {
        QMetaObject::invokeMethod(ui->draftAngle, "setFocus", Qt::QueuedConnection);
    }

    // Bind input fields to properties
    ui->draftAngle->bind(pcDraft->Angle);

    bool r = pcDraft->Reversed.getValue();
    ui->checkReverse->setChecked(r);

    QMetaObject::connectSlotsByName(this);

    // clang-format off
    connect(ui->draftAngle, qOverload<double>(&Gui::QuantitySpinBox::valueChanged),
            this, &TaskDraftParameters::onAngleChanged);
    connect(ui->checkReverse, &QCheckBox::toggled,
            this, &TaskDraftParameters::onReversedChanged);
    // clang-format on

    // The neutral plane and the pull direction: one reference each, a pick replaces it (ops#150)
    planeField = createSingleField(ui->planeFieldPlaceholder,
                                   "NeutralPlane",
                                   AllowSelection::EDGE | AllowSelection::FACE | AllowSelection::PLANAR,
                                   tr("Neutral plane"),
                                   tr("A planar face, a straight edge or a plane"));
    lineField = createSingleField(ui->lineFieldPlaceholder,
                                  "PullDirection",
                                  AllowSelection::EDGE | AllowSelection::PLANAR,
                                  tr("Pull direction"),
                                  tr("A straight edge or a line"));
    // The two labels lined up
    auto labelOf = [](ReferenceField* field) {
        return field->findChild<QLabel*>(QStringLiteral("label"));
    };
    const int width = std::max(labelOf(planeField)->sizeHint().width(),
                               labelOf(lineField)->sizeHint().width());
    labelOf(planeField)->setMinimumWidth(width);
    labelOf(lineField)->setMinimumWidth(width);

    hideOnError();

    setupGizmos(DressUpView);
}

ReferenceField* TaskDraftParameters::createSingleField(QWidget* placeholder,
                                                       const char* property,
                                                       AllowSelectionFlags flags,
                                                       const QString& label,
                                                       const QString& kinds)
{
    ReferenceField::Options options;
    options.kind = ReferenceField::Kind::SingleElement;
    options.flags = flags;
    // The base shows while the field is armed; datum and origin planes and lines go too
    options.target = [this]() -> App::DocumentObject* {
        return getBase();
    };
    options.required = false;
    options.label = label;
    options.kinds = kinds;
    // Another body's element through the copy or cross-reference question, as before
    options.resolve = [this](const Gui::SelectionChanges& msg,
                             App::DocumentObject*& obj,
                             std::vector<std::string>& subs) {
        obj = nullptr;
        return getReferencedSelection(getObject(), msg, obj, subs) && obj;
    };
    const std::string name = property;
    auto write = [this, name](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        auto draft = getObject<PartDesign::Draft>();
        if (!draft) {
            return;
        }
        setupTransaction();
        (name == "NeutralPlane" ? planeField : lineField)->assign(obj, subs);
        draft->recomputeFeature();
        // hide the draft if there was a computation error
        hideOnError();
        setGizmoPositions();
    };
    auto field = new ReferenceField(getObject(), property, options, write, proxy);
    field->takePlaceOf(placeholder);
    return field;
}

std::vector<ReferenceField*> TaskDraftParameters::referenceFields() const
{
    std::vector<ReferenceField*> fields = TaskDressUpParameters::referenceFields();
    for (ReferenceField* field : {planeField, lineField}) {
        if (field) {
            fields.push_back(field);
        }
    }
    return fields;
}

void TaskDraftParameters::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (msg.Type == Gui::SelectionChanges::ClrSelection) {
        // TODO: the gizmo position should be only recalculated when the feature associated
        // with the gizmo is removed from the list
        setGizmoPositions();
    }
}

void TaskDraftParameters::onAngleChanged(double angle)
{
    if (auto draft = getObject<PartDesign::Draft>()) {
        // a value edit ends the picking, gate and display included (B3)
        disarmFields();
        setupTransaction();
        draft->Angle.setValue(angle);
        draft->recomputeFeature();
        // hide the draft if there was a computation error
        hideOnError();
    }
}

double TaskDraftParameters::getAngle() const
{
    return ui->draftAngle->value().getValue();
}

void TaskDraftParameters::onReversedChanged(const bool reversed)
{
    if (auto draft = getObject<PartDesign::Draft>()) {
        disarmFields();
        setupTransaction();
        draft->Reversed.setValue(reversed);
        draft->recomputeFeature();
        // hide the draft if there was a computation error
        hideOnError();

        setGizmoPositions();
    }
}

bool TaskDraftParameters::getReversed() const
{
    return ui->checkReverse->isChecked();
}

TaskDraftParameters::~TaskDraftParameters()
{
    try {
        Gui::Selection().clearSelection();
    }
    catch (const Py::Exception&) {
        Base::PyException e;  // extract the Python error text
        e.reportException();
    }
}

void TaskDraftParameters::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        ui->retranslateUi(proxy);
    }
}

void TaskDraftParameters::apply()
{
    // Alert user if he created an empty feature
    if (getReferences().empty()) {
        Base::Console().warning(tr("Empty draft created!\n").toStdString().c_str());
    }

    TaskDressUpParameters::apply();
}


void TaskDraftParameters::setupGizmos(ViewProvider* vp)
{
    if (!GizmoContainer::isEnabled()) {
        return;
    }

    angleGizmo = new Gui::RotationGizmo(ui->draftAngle);

    gizmoContainer = GizmoContainer::create({angleGizmo}, vp);

    setGizmoPositions();
    showDraggerHints();
}

void TaskDraftParameters::setGizmoPositions()
{
    if (!gizmoContainer) {
        return;
    }
    gizmoContainer->visible = false;

    auto draft = getObject<PartDesign::Draft>();
    if (!draft || draft->isError()) {
        return;
    }
    Part::TopoShape baseShape = draft->getBaseTopoShape(true);
    std::vector<Part::TopoShape> faces;
    try {
        faces = draft->getFaces(baseShape);
    }
    catch (const Base::Exception&) {
        return;  // a missing face, while the draft isn't recomputed yet (ops#60)
    }
    if (faces.empty()) {
        return;
    }

    auto [pullDirection, neutralPlane] = draft->getLastComputedProps();

    std::optional<DraggerPlacementPropsWithNormals> props
        = getDraggerPlacementFromPlaneAndFace(faces[0], neutralPlane);
    if (!props) {
        return;
    }

    if (auto normalProps = props->normalProps) {
        auto pos = Base::convertTo<SbVec3f>(props->placementProps.position);
        auto dir = Base::convertTo<SbVec3f>(props->placementProps.dir);
        auto lineDir = Base::convertTo<SbVec3f>(normalProps->normal);
        auto pp = Base::convertTo<SbVec3f>(pullDirection);

        angleGizmo->setDraggerPlacement(pos, (dir.dot(pp) < 0) ? -pp : pp);

        auto rotDir = Base::convertTo<SbVec3f>(normalProps->faceNormal).cross(pp);
        if (lineDir.dot(rotDir) < 0) {
            lineDir *= -1;
        }
        if (draft->Reversed.getValue()) {
            lineDir = -lineDir;
        }
        angleGizmo->getDraggerContainer()->setArcNormalDirection(lineDir);
        angleGizmo->automaticOrientation = false;
    }
    else {
        // The face is cone or cylinder
        angleGizmo->setDraggerPlacement(
            Base::convertTo<SbVec3f>(props->placementProps.position),
            Base::convertTo<SbVec3f>(props->placementProps.dir)
        );
        angleGizmo->automaticOrientation = true;
    }
    gizmoContainer->visible = true;
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgDraftParameters::TaskDlgDraftParameters(ViewProviderDraft* DraftView)
    : TaskDlgDressUpParameters(DraftView)
{
    parameter = new TaskDraftParameters(DraftView);

    Content.push_back(parameter);
    Content.push_back(preview);
}

TaskDlgDraftParameters::~TaskDlgDraftParameters() = default;

//==== calls from the TaskView ===============================================================

bool TaskDlgDraftParameters::accept()
{
    auto tobj = getObject();
    if (!tobj->isError()) {
        getViewObject()->showPreviousFeature(false);
    }

    parameter->apply();

    // The neutral plane and the pull direction are written by their fields as they are picked
    // (ops#150), their guess records kept (ops#127)
    auto draftparameter = static_cast<TaskDraftParameters*>(parameter);
    FCMD_OBJ_CMD(tobj, "Angle = " << draftparameter->getAngle());
    FCMD_OBJ_CMD(tobj, "Reversed = " << draftparameter->getReversed());

    return TaskDlgDressUpParameters::accept();
}

#include "moc_TaskDraftParameters.cpp"
