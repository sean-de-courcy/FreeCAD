// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                               *
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

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QLabel>
#include <QLineEdit>
#include <QPointer>
#include <QRegularExpression>
#include <QSpinBox>
#include <QTimer>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <Base/Tools.h>
#include <Gui/Command.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/PartDesign/App/FeatureCurvePattern.h>

#include "ui_TaskCurvePatternParameters.h"
#include "ReferenceField.h"
#include "TaskCurvePatternParameters.h"

using namespace PartDesignGui;
using namespace Gui;

namespace
{

/// The Python list SkippedInstances is written with: the field's whole numbers, in order
std::string skippedPython(const QString& text)
{
    static const QRegularExpression number(QStringLiteral("-?\\d+"));
    std::string list = "[";
    bool first = true;
    auto it = number.globalMatch(text);
    while (it.hasNext()) {
        list += (first ? "" : ", ") + std::to_string(it.next().captured().toLong());
        first = false;
    }
    return list + "]";
}

QString skippedText(const std::vector<long>& values)
{
    QStringList items;
    for (long value : values) {
        items << QString::number(value);
    }
    return items.join(QStringLiteral(", "));
}

/// A path: edges of a sketch or a feature, or a sketch or a wire whole
bool acceptPath(App::DocumentObject* obj, const char* sub, std::string& why)
{
    if (!obj || !obj->isDerivedFrom<Part::Feature>()) {
        why = QT_TRANSLATE_NOOP("PartDesignGui::TaskCurvePatternParameters", "Pick an edge, or a sketch whole.");
        return false;
    }
    if (!Base::Tools::isNullOrEmpty(sub)) {
        if (std::string(sub).rfind("Edge", 0) != 0) {
            why = QT_TRANSLATE_NOOP("PartDesignGui::TaskCurvePatternParameters", "A path is made of edges: pick an edge.");
            return false;
        }
        return true;
    }
    try {
        const Part::TopoShape shape = static_cast<Part::Feature*>(obj)->Shape.getShape();
        if (!shape.isNull() && shape.hasSubShape(TopAbs_EDGE) && !shape.hasSubShape(TopAbs_FACE)) {
            return true;
        }
    }
    catch (const Base::Exception&) {
    }
    why = QT_TRANSLATE_NOOP(
        "PartDesignGui::TaskCurvePatternParameters",
        "A whole object is a path only when it is edges or wires: pick its edges."
    );
    return false;
}

}  // namespace

/* TRANSLATOR PartDesignGui::TaskCurvePatternParameters */

TaskCurvePatternParameters::TaskCurvePatternParameters(ViewProviderTransformed* TransformedView, QWidget* parent)
    : TaskTransformedParameters(TransformedView, parent)
    , ui(new Ui_TaskCurvePatternParameters)
{
    setupUI();
}

TaskCurvePatternParameters::~TaskCurvePatternParameters() = default;

void TaskCurvePatternParameters::setupParameterUI(QWidget* widget)
{
    ui->setupUi(widget);
    QMetaObject::connectSlotsByName(this);

    updateViewTimer = new QTimer(this);
    updateViewTimer->setSingleShot(true);
    updateViewTimer->setInterval(getUpdateViewTimeout());
    connect(updateViewTimer, &QTimer::timeout, this, [this]() {
        setupTransaction();
        recomputeFeature();
    });

    auto pattern = getObject<PartDesign::CurvePattern>();
    if (!pattern) {
        return;
    }

    // The path: a Profile field of edges, as the pipe's (ops#150 W8)
    ReferenceField::Options options;
    options.kind = ReferenceField::Kind::Profile;
    options.use = ReferenceField::ProfileUse::Path;
    options.noDependents = true;
    options.kinds = tr("Edges, or a sketch whole");
    options.label = tr("Path to pattern along");
    options.accept = [](App::DocumentObject* obj, const char* sub, std::string& why) {
        return acceptPath(obj, sub, why);
    };
    auto self = std::make_shared<QPointer<ReferenceField>>();
    auto write = [this, self](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        if (*self) {
            (*self)->assign(obj, subs);
        }
        recomputeFeature();
    };
    pathField = new ReferenceField(pattern, "Path", options, write, widget);
    *self = pathField;
    pathField->takePlaceOf(ui->pathFieldPlaceholder);
    connect(pathField, &ReferenceField::arming, this, [this]() { endPickModes(); });

    updateUI();

    connect(ui->spinOccurrences, qOverload<int>(&QSpinBox::valueChanged), this, [this](int value) {
        if (blockUpdate || !getObject()) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), "Occurrences = " << value);
        kickUpdateViewTimer();
    });
    connect(ui->comboOrientation, qOverload<int>(&QComboBox::currentIndexChanged), this, [this](int index) {
        if (blockUpdate || !getObject() || index < 0) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), "Orientation = " << index);
        kickUpdateViewTimer();
    });
    connect(ui->comboSpacing, qOverload<int>(&QComboBox::currentIndexChanged), this, [this](int index) {
        const bool distance = index == 1;
        ui->labelDistance->setVisible(distance);
        ui->spinDistance->setVisible(distance);
        if (blockUpdate || !getObject() || index < 0) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), "SpacingType = " << index);
        kickUpdateViewTimer();
    });
    connect(ui->spinDistance, qOverload<double>(&QDoubleSpinBox::valueChanged), this, [this](double value) {
        if (blockUpdate || !getObject()) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), "Distance = " << value);
        kickUpdateViewTimer();
    });
    connect(ui->checkSkip, &QCheckBox::toggled, this, [this](bool on) {
        ui->editSkipped->setVisible(on);
        if (on) {
            ui->editSkipped->setFocus();
            return;
        }
        ui->editSkipped->clear();
        if (blockUpdate || !getObject()) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), "SkippedInstances = []");
        kickUpdateViewTimer();
    });
    connect(ui->editSkipped, &QLineEdit::editingFinished, this, [this]() {
        if (blockUpdate || !getObject()) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), "SkippedInstances = " << skippedPython(ui->editSkipped->text()));
        kickUpdateViewTimer();
    });
}

void TaskCurvePatternParameters::updateUI()
{
    auto pattern = getObject<PartDesign::CurvePattern>();
    if (!pattern) {
        return;
    }
    const bool blocked = blockUpdate;
    blockUpdate = true;
    ui->spinOccurrences->setValue(static_cast<int>(pattern->Occurrences.getValue()));
    ui->comboOrientation->setCurrentIndex(pattern->Orientation.getValue());
    ui->comboSpacing->setCurrentIndex(pattern->SpacingType.getValue());
    ui->spinDistance->setValue(pattern->Distance.getValue());
    const bool distance = pattern->SpacingType.getValue() == 1;
    ui->labelDistance->setVisible(distance);
    ui->spinDistance->setVisible(distance);
    const auto& skipped = pattern->SkippedInstances.getValues();
    ui->checkSkip->setChecked(!skipped.empty());
    ui->editSkipped->setText(skippedText(skipped));
    ui->editSkipped->setVisible(!skipped.empty());
    blockUpdate = blocked;
}

void TaskCurvePatternParameters::retranslateParameterUI(QWidget* widget)
{
    ui->retranslateUi(widget);
}

void TaskCurvePatternParameters::onUpdateView(bool on)
{
    blockUpdate = !on;
    if (on) {
        kickUpdateViewTimer();
    }
}

void TaskCurvePatternParameters::kickUpdateViewTimer() const
{
    if (updateViewTimer) {
        updateViewTimer->start();
    }
}

void TaskCurvePatternParameters::onReferencesRepaired()
{
    if (pathField) {
        pathField->reload();
    }
    updateUI();
}

std::vector<ReferenceField*> TaskCurvePatternParameters::pathFields() const
{
    if (pathField) {
        return {pathField};
    }
    return {};
}

void TaskCurvePatternParameters::apply()
{
    auto pattern = getObject<PartDesign::CurvePattern>();
    if (!pattern) {
        return;
    }
    // Each field wrote its value when it changed; what is left is a value typed and not yet
    // committed (Enter or OK straight after the typing)
    const std::string list = skippedPython(ui->editSkipped->text());
    if (list != skippedPython(skippedText(pattern->SkippedInstances.getValues()))) {
        FCMD_OBJ_CMD(pattern, "SkippedInstances = " << list);
    }
    if (ui->spinOccurrences->value() != pattern->Occurrences.getValue()) {
        FCMD_OBJ_CMD(pattern, "Occurrences = " << ui->spinOccurrences->value());
    }
    if (updateViewTimer && updateViewTimer->isActive()) {
        updateViewTimer->stop();
        recomputeFeature();
    }
}

//**************************************************************************
// TaskDialog
//**************************************************************************

TaskDlgCurvePatternParameters::TaskDlgCurvePatternParameters(ViewProviderTransformed* CurvePatternView)
    : TaskDlgTransformedParameters(CurvePatternView)
{
    parameter = new TaskCurvePatternParameters(CurvePatternView);
    Content.push_back(parameter);
    Content.push_back(preview);
}

std::vector<ReferenceField*> TaskDlgCurvePatternParameters::panelFields()
{
    std::vector<ReferenceField*> fields = TaskDlgTransformedParameters::panelFields();
    if (auto panel = qobject_cast<TaskCurvePatternParameters*>(parameter)) {
        for (ReferenceField* field : panel->pathFields()) {
            fields.push_back(field);
        }
    }
    return fields;
}

#include "moc_TaskCurvePatternParameters.cpp"
