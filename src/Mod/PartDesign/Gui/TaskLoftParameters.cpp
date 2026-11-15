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


#include <algorithm>
#include <cstring>
#include <memory>

#include <QKeyEvent>
#include <QListWidget>
#include <QPointer>

#include <boost/algorithm/string/predicate.hpp>

#include <App/Document.h>
#include <App/ElementNamingUtils.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/CommandT.h>
#include <Gui/Document.h>
#include <Gui/Selection/Selection.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/PartDesign/App/FeatureLoft.h>

#include "ui_TaskLoftParameters.h"
#include "TaskLoftParameters.h"
#include "TaskSketchBasedParameters.h"

using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskLoftParameters */

namespace
{
bool isSubtractiveLoft(ViewProviderLoft* view)
{
    auto* loft = view->getObject<PartDesign::Loft>();
    return loft->getAddSubType() == PartDesign::FeatureAddSub::Type::Subtractive;
}

std::string loftTaskIconName(ViewProviderLoft* view)
{
    return isSubtractiveLoft(view) ? "PartDesign_SubtractiveLoft" : "PartDesign_AdditiveLoft";
}

QString loftTaskTitle(ViewProviderLoft* view)
{
    return isSubtractiveLoft(view) ? TaskLoftParameters::tr("Subtractive Loft Parameters")
                                   : TaskLoftParameters::tr("Additive Loft Parameters");
}

// A sketch is taken whole, unless one of its points or regions is picked: the loft takes the
// whole sketch for any other element of it, and a picked region as it is (Loft::getSectionShape)
std::string sectionElement(App::DocumentObject* obj, const char* sub)
{
    std::string element = Base::Tools::isNullOrEmpty(sub) ? std::string() : std::string(sub);
    if (obj && obj->isDerivedFrom<Part::Part2DObject>()
        && !ReferenceField::keepsSketchElement(element)) {
        element.clear();
    }
    return element;
}
}  // namespace

TaskLoftParameters::TaskLoftParameters(ViewProviderLoft* LoftView, bool /*newObj*/, QWidget* parent)
    : TaskSketchBasedParameters(LoftView, parent, loftTaskIconName(LoftView), loftTaskTitle(LoftView))
    , ui(new Ui_TaskLoftParameters)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    // clang-format off
    connect(ui->checkBoxRuled, &QCheckBox::toggled,
            this, &TaskLoftParameters::onRuled);
    connect(ui->checkBoxClosed, &QCheckBox::toggled,
            this, &TaskLoftParameters::onClosed);
    connect(ui->comboStartCondition, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskLoftParameters::onStartCondition);
    connect(ui->spinStartMagnitude, qOverload<double>(&QDoubleSpinBox::valueChanged),
            this, &TaskLoftParameters::onStartMagnitude);
    connect(ui->comboEndCondition, qOverload<int>(&QComboBox::currentIndexChanged),
            this, &TaskLoftParameters::onEndCondition);
    connect(ui->spinEndMagnitude, qOverload<double>(&QDoubleSpinBox::valueChanged),
            this, &TaskLoftParameters::onEndMagnitude);
    connect(ui->checkBoxUpdateView, &QCheckBox::toggled,
            this, &TaskLoftParameters::onUpdateView);
    connect(ui->buttonAddConnection, &QPushButton::toggled,
            this, &TaskLoftParameters::onAddConnection);
    connect(ui->buttonRemoveConnection, &QPushButton::clicked,
            this, &TaskLoftParameters::onRemoveConnection);
    connect(ui->listConnections, &QListWidget::itemSelectionChanged,
            this, &TaskLoftParameters::onConnectionRow);
    // clang-format on
    ui->listConnections->installEventFilter(this);

    this->groupLayout()->addWidget(proxy);

    // Temporarily prevent unnecessary feature recomputes
    const auto childs = proxy->findChildren<QWidget*>();
    for (QWidget* child : childs) {
        child->blockSignals(true);
    }

    // The profile and the sections show for the edit; OK and Cancel put them back (ops#162 B13)
    PartDesign::Loft* loft = LoftView->getObject<PartDesign::Loft>();
    shown.show(loft->Profile.getValue());
    for (App::DocumentObject* obj : loft->Sections.getValues()) {
        shown.show(obj);
    }

    // get options
    ui->checkBoxRuled->setChecked(loft->Ruled.getValue());
    ui->checkBoxClosed->setChecked(loft->Closed.getValue());
    // The end conditions, as Onshape's Loft panel (ops#655); the combo's items are the
    // properties' enums in order
    ui->comboStartCondition->setCurrentIndex(static_cast<int>(loft->StartCondition.getValue()));
    ui->spinStartMagnitude->setValue(loft->StartMagnitude.getValue());
    ui->comboEndCondition->setCurrentIndex(static_cast<int>(loft->EndCondition.getValue()));
    ui->spinEndMagnitude->setValue(loft->EndMagnitude.getValue());

    // activate and de-activate dialog elements as appropriate
    for (QWidget* child : childs) {
        child->blockSignals(false);
    }

    createFields();
    // ops#640: a field armed for a pick ends the connection pick
    for (ReferenceField* field : {profileField, sectionsField}) {
        if (field) {
            connect(field, &ReferenceField::armedChanged, this, [this](bool armed) {
                if (armed) {
                    ui->buttonAddConnection->setChecked(false);
                }
            });
        }
    }
    fillConnections();
    connectionHint(QString());
    updateUI();
}

TaskLoftParameters::~TaskLoftParameters() = default;

void TaskLoftParameters::createFields()
{
    App::DocumentObjectT loftT(getObject());
    auto isShape = [](App::DocumentObject* obj, const char* sub, std::string& why) {
        if (!obj || !obj->isDerivedFrom<Part::Feature>()) {
            why = QT_TR_NOOP("Pick a sketch, a sketch point or a face.");
            return false;
        }
        return ReferenceActions::wholeObjectFits(obj, sub, why);
    };

    // The profile: one sketch, sketch point or face (Q8 (a): its own field, above the sections)
    ReferenceField::Options profile;
    profile.kind = ReferenceField::Kind::SingleElement;
    profile.acceptOnly = true;
    profile.noDependents = true;
    profile.removable = false;
    profile.label = tr("Profile");
    profile.kinds = tr("A sketch, a sketch point or a face");
    profile.accept = [loftT, isShape](App::DocumentObject* obj, const char* sub, std::string& why) {
        if (!isShape(obj, sub, why)) {
            return false;
        }
        auto loft = freecad_cast<PartDesign::Loft*>(loftT.getObject());
        if (loft
            && std::ranges::find(loft->Sections.getValues(), obj)
                != loft->Sections.getValues().end()) {
            why = QT_TR_NOOP("This is a section of the loft: the profile can't be one too.");
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
        TaskResultParameters::profileTaken(getObject());  // ops#640, round 3: where it opens
    };
    profileField = new ReferenceField(getObject(), "Profile", profile, writeProfile, proxy);
    *profileSelf = profileField;
    profileField->takePlaceOf(ui->profileFieldPlaceholder);

    // The sections, in the loft's order (ops#162 B8, B11, B12, B21)
    ReferenceField::Options sections;
    sections.kind = ReferenceField::Kind::Sections;
    sections.noDependents = true;
    sections.label = tr("Sections");
    sections.kinds = tr("Sketches, sketch points or faces");
    sections.accept = [loftT, isShape](App::DocumentObject* obj,
                                       const char* sub,
                                       std::string& why) {
        if (!isShape(obj, sub, why)) {
            return false;
        }
        auto loft = freecad_cast<PartDesign::Loft*>(loftT.getObject());
        if (loft && obj == loft->Profile.getValue()) {
            why = QT_TR_NOOP("This is the loft's profile: it can't be a section too.");
            return false;
        }
        return true;
    };
    auto sectionsSelf = std::make_shared<QPointer<ReferenceField>>();
    using SubSets = std::vector<App::PropertyLinkSubList::SubSet>;
    auto writeSections = [this, sectionsSelf](const SubSets& list) {
        if (*sectionsSelf) {
            (*sectionsSelf)->assign(list);
        }
        for (const auto& section : list) {
            shown.show(section.first);
        }
        recomputeFeature();
        updateUI();
        TaskResultParameters::profileTaken(getObject());  // ops#640, round 3: where it opens
    };
    sectionsField = new ReferenceField(
        getObject(),
        "Sections",
        sections,
        ReferenceField::SectionsWriter(writeSections),
        proxy
    );
    *sectionsSelf = sectionsField;
    sectionsField->takePlaceOf(ui->sectionsFieldPlaceholder);
}

std::vector<ReferenceField*> TaskLoftParameters::referenceFields() const
{
    return {profileField, sectionsField};
}

void TaskLoftParameters::restoreVisibility()
{
    shown.restore();
}

void TaskLoftParameters::updateUI()
{
    // we must assure the changed loft is kept visible on section changes,
    // see https://forum.freecad.org/viewtopic.php?f=3&t=63252
    auto loft = getObject<PartDesign::Loft>();
    if (loft) {
        auto view = getViewObject();
        view->makeTemporaryVisible(!loft->Sections.getValues().empty());
    }

    // A condition's magnitude shows only while the condition is set, as in Onshape
    const bool start = ui->comboStartCondition->currentIndex() != 0;
    ui->labelStartMagnitude->setVisible(start);
    ui->spinStartMagnitude->setVisible(start);
    const bool end = ui->comboEndCondition->currentIndex() != 0;
    ui->labelEndMagnitude->setVisible(end);
    ui->spinEndMagnitude->setVisible(end);
}

void TaskLoftParameters::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    // The fields take the picks; the Add connection button takes vertex pairs (ops#640)
    if (picking || !ui->buttonAddConnection->isChecked()
        || msg.Type != Gui::SelectionChanges::AddSelection) {
        return;
    }
    auto loft = getObject<PartDesign::Loft>();
    if (!loft || !msg.pDocName
        || std::strcmp(msg.pDocName, loft->getDocument()->getName()) != 0) {
        return;
    }
    App::DocumentObject* obj = loft->getDocument()->getObject(msg.pObjectName);
    const std::string sub =
        Base::Tools::isNullOrEmpty(msg.pSubName) ? std::string() : Data::oldElementName(msg.pSubName);
    {
        Base::StateLocker lock(picking, true);
        Gui::Selection().clearSelection();
    }
    App::DocumentObject* profile = loft->Profile.getValue();
    const auto& sections = loft->Sections.getValues();
    App::DocumentObject* section = sections.size() == 1 ? sections.front() : nullptr;
    if (!section) {
        connectionHint(tr("Connections need exactly two profiles: the profile and one section"));
        return;
    }
    if (!obj || (obj != profile && obj != section) || !boost::starts_with(sub, "Vertex")) {
        connectionHint(tr("Pick a vertex of the profile or of the section"));
        return;
    }
    if (!pendingObject || obj == pendingObject) {
        pendingObject = obj;
        pendingVertex = sub;
        connectionHint(
            obj == profile ? tr("Now pick its vertex on the section")
                           : tr("Now pick its vertex on the profile")
        );
        return;
    }
    auto objects = loft->Connections.getValues();
    auto subs = loft->Connections.getSubValues(false);
    if (pendingObject == profile) {
        objects.insert(objects.end(), {pendingObject, obj});
        subs.insert(subs.end(), {pendingVertex, sub});
    }
    else {
        objects.insert(objects.end(), {obj, pendingObject});
        subs.insert(subs.end(), {sub, pendingVertex});
    }
    loft->Connections.setValues(objects, subs);
    ui->buttonAddConnection->setChecked(false);
    fillConnections();
    recomputeFeature();
}

void TaskLoftParameters::connectionHint(const QString& text)
{
    ui->labelConnectionHint->setText(text);
    ui->labelConnectionHint->setVisible(!text.isEmpty());
}

void TaskLoftParameters::fillConnections()
{
    QSignalBlocker block(ui->listConnections);
    ui->listConnections->clear();
    auto loft = getObject<PartDesign::Loft>();
    if (!loft) {
        return;
    }
    const auto& objects = loft->Connections.getValues();
    const auto subs = loft->Connections.getSubValues(false);
    auto end = [&](size_t i) {
        const char* label = objects[i] ? objects[i]->Label.getValue() : "?";
        return QStringLiteral("%1: %2").arg(
            QString::fromUtf8(label),
            QString::fromStdString(i < subs.size() ? subs[i] : std::string())
        );
    };
    for (size_t k = 0; k + 1 < objects.size(); k += 2) {
        ui->listConnections->addItem(QStringLiteral("%1 \u2192 %2").arg(end(k), end(k + 1)));
    }
}

void TaskLoftParameters::onAddConnection(bool on)
{
    pendingObject = nullptr;
    pendingVertex.clear();
    // The panel's own observer is blocked (TaskSketchBasedParameters); it listens while the button is down
    blockSelection(!on);
    if (on) {
        if (ReferenceField* field = ReferenceField::armedField()) {
            field->setArmed(false);
        }
        connectionHint(tr("Pick a vertex on the profile, then its partner on the section"));
    }
    else {
        connectionHint(QString());
    }
}

void TaskLoftParameters::onRemoveConnection()
{
    auto loft = getObject<PartDesign::Loft>();
    if (!loft) {
        return;
    }
    std::vector<int> rows;
    for (const QModelIndex& index : ui->listConnections->selectionModel()->selectedRows()) {
        rows.push_back(index.row());
    }
    if (rows.empty()) {
        return;
    }
    std::sort(rows.rbegin(), rows.rend());
    auto objects = loft->Connections.getValues();
    auto subs = loft->Connections.getSubValues(false);
    for (int row : rows) {
        const auto at = static_cast<size_t>(2 * row);
        if (at + 1 < objects.size() && at + 1 < subs.size()) {
            objects.erase(objects.begin() + at, objects.begin() + at + 2);
            subs.erase(subs.begin() + at, subs.begin() + at + 2);
        }
    }
    loft->Connections.setValues(objects, subs);
    fillConnections();
    recomputeFeature();
}

void TaskLoftParameters::onConnectionRow()
{
    // The selected rows' vertices show selected in the 3D view, unless a field waits for a pick
    auto loft = getObject<PartDesign::Loft>();
    if (!loft || ReferenceField::armedField() || ui->buttonAddConnection->isChecked()) {
        return;
    }
    Base::StateLocker lock(picking, true);
    Gui::Selection().clearSelection();
    const auto& objects = loft->Connections.getValues();
    const auto subs = loft->Connections.getSubValues(false);
    const char* doc = loft->getDocument()->getName();
    for (const QModelIndex& index : ui->listConnections->selectionModel()->selectedRows()) {
        for (size_t i : {static_cast<size_t>(2 * index.row()), static_cast<size_t>(2 * index.row() + 1)}) {
            if (i < objects.size() && i < subs.size() && objects[i]) {
                Gui::Selection().addSelection(doc, objects[i]->getNameInDocument(), subs[i].c_str());
            }
        }
    }
}

bool TaskLoftParameters::eventFilter(QObject* watched, QEvent* event)
{
    if (watched == ui->listConnections && event->type() == QEvent::KeyPress) {
        const auto key = static_cast<QKeyEvent*>(event)->key();
        if (key == Qt::Key_Delete || key == Qt::Key_Backspace) {
            onRemoveConnection();
            return true;
        }
    }
    return TaskSketchBasedParameters::eventFilter(watched, event);
}

void TaskLoftParameters::changeEvent(QEvent* /*e*/)
{}

void TaskLoftParameters::onClosed(bool val)
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        loft->Closed.setValue(val);
        recomputeFeature();
    }
}

void TaskLoftParameters::onRuled(bool val)
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        loft->Ruled.setValue(val);
        recomputeFeature();
    }
}

void TaskLoftParameters::onStartCondition(int index)
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        loft->StartCondition.setValue(index);
        updateUI();
        recomputeFeature();
    }
}

void TaskLoftParameters::onStartMagnitude(double val)
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        loft->StartMagnitude.setValue(val);
        recomputeFeature();
    }
}

void TaskLoftParameters::onEndCondition(int index)
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        loft->EndCondition.setValue(index);
        updateUI();
        recomputeFeature();
    }
}

void TaskLoftParameters::onEndMagnitude(double val)
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        loft->EndMagnitude.setValue(val);
        recomputeFeature();
    }
}


//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgLoftParameters::TaskDlgLoftParameters(ViewProviderLoft* LoftView, bool newObj)
    : TaskDlgSketchBasedParameters(LoftView)
{
    assert(LoftView);
    parameter = new TaskLoftParameters(LoftView, newObj);

    Content.push_back(parameter);
    addResultBox();
    Content.push_back(preview);
}

TaskDlgLoftParameters::~TaskDlgLoftParameters() = default;

bool TaskDlgLoftParameters::accept()
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        // First verify that the loft can be built and then hide the sections as otherwise
        // they will remain hidden if the loft's recompute fails
        if (TaskDlgSketchBasedParameters::accept()) {
            // What the edit showed goes back as it was (a section taken out of the list
            // included), then the profile and the sections are hidden, as OK always did
            parameter->restoreVisibility();
            Gui::cmdAppObjectHide(loft->Profile.getValue());
            for (App::DocumentObject* obj : loft->Sections.getValues()) {
                Gui::cmdAppObjectHide(obj);
            }

            return true;
        }
    }

    return false;
}

bool TaskDlgLoftParameters::reject()
{
    // What the edit showed goes back first: the abort that follows shows a new loft's profile
    // again, and a restore after it (the panel's destructor) would hide it (ops#150)
    parameter->restoreVisibility();
    return TaskDlgSketchBasedParameters::reject();
}

//==== calls from the TaskView ===============================================================


#include "moc_TaskLoftParameters.cpp"
