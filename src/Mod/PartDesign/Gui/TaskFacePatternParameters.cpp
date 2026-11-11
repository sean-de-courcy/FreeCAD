// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD project.

/******************************************************************************
 *                                                                            *
 *   FreeCAD is free software: you can redistribute it and/or modify          *
 *   it under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1            *
 *   of the License, or (at your option) any later version.                   *
 *                                                                            *
 *   FreeCAD is distributed in the hope that it will be useful,               *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty              *
 *   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                  *
 *   See the GNU Lesser General Public License for more details.              *
 *                                                                            *
 *   You should have received a copy of the GNU Lesser General Public         *
 *   License along with FreeCAD. If not, see https://www.gnu.org/licenses     *
 *                                                                            *
 ******************************************************************************/

#include <QCheckBox>
#include <QComboBox>
#include <QLabel>
#include <QPointer>
#include <QTimer>
#include <QVBoxLayout>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Origin.h>
#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Gui/Command.h>
#include <Gui/Document.h>
#include <Gui/Selection/Selection.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/Part/Gui/PatternParametersWidget.h>

#include "ui_TaskFacePatternParameters.h"
#include "ReferenceField.h"
#include "ReferenceSelection.h"
#include "TaskFacePatternParameters.h"


using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskFacePatternParameters */

TaskFacePatternParameters::TaskFacePatternParameters(ViewProviderDressUp* DressUpView, QWidget* parent)
    : TaskDressUpParameters(DressUpView, false, true, parent)
    , ui(new Ui_TaskFacePatternParameters)
{
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    this->groupLayout()->addWidget(proxy);

    createBaseField(ui->baseFieldPlaceholder);

    updateTimer = new QTimer(this);
    updateTimer->setSingleShot(true);
    updateTimer->setInterval(300);
    connect(updateTimer, &QTimer::timeout, this, &TaskFacePatternParameters::onUpdateTimer);

    auto pattern = getObject();
    if (auto linear = freecad_cast<PartDesign::FaceLinearPattern*>(pattern)) {
        addLinearFields(linear);
    }
    else if (auto polar = freecad_cast<PartDesign::FacePolarPattern*>(pattern)) {
        addPolarFields(polar);
    }
    else if (auto mirrored = freecad_cast<PartDesign::FaceMirrored*>(pattern)) {
        addMirroredFields(mirrored);
    }
    hideOnError();
}

TaskFacePatternParameters::~TaskFacePatternParameters()
{
    try {
        Gui::Selection().clearSelection();
    }
    catch (const Py::Exception&) {
        Base::PyException e;
        e.reportException();
    }
}

void TaskFacePatternParameters::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        ui->retranslateUi(proxy);
    }
}

// The fields take the picks: the Base field's, and the one a reference is armed for
void TaskFacePatternParameters::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    Q_UNUSED(msg)
}

ReferenceField* TaskFacePatternParameters::createPickField(
    const char* property,
    AllowSelectionFlags flags,
    const QString& kinds,
    PartGui::PatternParametersWidget* widget,
    std::function<void(App::DocumentObject*, const std::vector<std::string>&)>* writerOut
)
{
    ReferenceField::Options options;
    options.kind = ReferenceField::Kind::SingleElement;
    options.flags = flags;
    // The base shows while the field is armed; datum and origin planes and lines go too
    options.target = [this]() -> App::DocumentObject* {
        return getBase();
    };
    // The faces are the panel's first job: this field arms for one pick, on request
    options.required = false;
    options.removable = false;
    options.once = true;
    options.label = tr("Reference");
    options.kinds = kinds;
    // Another body's element through the copy or cross-reference question, as before
    options.resolve = [this](const Gui::SelectionChanges& msg,
                             App::DocumentObject*& obj,
                             std::vector<std::string>& subs) {
        obj = nullptr;
        return getReferencedSelection(getObject(), msg, obj, subs) && obj;
    };
    auto self = std::make_shared<QPointer<ReferenceField>>();
    auto write = [this, self, widget](App::DocumentObject* obj, const std::vector<std::string>& picked) {
        // A line, an origin axis or a plane is linked whole as {""}
        const std::vector<std::string> subs
            = picked.empty() ? std::vector<std::string> {std::string()} : picked;
        setupTransaction();
        if (*self) {
            (*self)->assign(obj, subs);
        }
        recomputeFeature();
        hideOnError();
        if (widget) {
            widget->updateUI();
        }
    };
    auto field = new ReferenceField(getObject(), property, options, write, proxy);
    *self = field;
    if (writerOut) {
        *writerOut = write;
    }
    // Done, the faces take the picks again
    connect(field, &ReferenceField::picked, this, [this]() {
        QTimer::singleShot(0, this, [this]() {
            if (baseField) {
                baseField->setArmed(true);
            }
        });
    });
    if (widget) {
        // Disarmed without a pick: the box shows the direction there is
        connect(field, &ReferenceField::armedChanged, widget, [widget](bool on) {
            if (!on) {
                widget->updateUI();
            }
        });
        connect(
            widget,
            &PartGui::PatternParametersWidget::requestReferenceSelection,
            field,
            [field]() { field->setArmed(true); }
        );
        field->hide();
    }
    ui->verticalLayout->addWidget(field);
    pickFields.push_back(field);
    return field;
}

PartGui::PatternParametersWidget* TaskFacePatternParameters::createWidget(
    bool linear,
    const char* property,
    AllowSelectionFlags flags,
    const QString& kinds,
    const QString& title
)
{
    Gui::View3DInventorViewer* viewer = nullptr;
    if (Gui::Document* document = getGuiDocument()) {
        if (auto* view3d = freecad_cast<Gui::View3DInventor*>(document->getActiveView())) {
            viewer = view3d->getViewer();
        }
    }
    auto* widget = new PartGui::PatternParametersWidget(
        linear ? PartGui::PatternType::Linear : PartGui::PatternType::Polar,
        viewer,
        proxy
    );
    ui->verticalLayout->addWidget(widget);

    // The directions: the Body origin's axes, then "Select reference..."
    widget->dirLinks.clear();
    if (auto body = PartDesign::Body::findBodyOf(getObject())) {
        try {
            App::Origin* origin = body->getOrigin();
            widget->dirLinks.addLink(origin->getX(), "", tr("Base X-axis"));
            widget->dirLinks.addLink(origin->getY(), "", tr("Base Y-axis"));
            widget->dirLinks.addLink(origin->getZ(), "", tr("Base Z-axis"));
        }
        catch (const Base::Exception& ex) {
            Base::Console().error("%s\n", ex.what());
        }
    }
    widget->dirLinks.addLink(nullptr, std::string(), tr("Select reference…"));

    connect(
        widget,
        &PartGui::PatternParametersWidget::parametersChanged,
        this,
        &TaskFacePatternParameters::onParametersChanged
    );
    if (!title.isEmpty()) {
        widget->setTitle(title);
        widget->setCheckable(true);
    }
    createPickField(property, flags, kinds, widget);
    widgets.push_back(widget);
    return widget;
}

void TaskFacePatternParameters::addLinearFields(PartDesign::FaceLinearPattern* pattern)
{
    const AllowSelectionFlags flags = AllowSelection::EDGE | AllowSelection::PLANAR
        | AllowSelection::FACE;
    const QString kinds = tr("A straight edge, a planar face or a line");

    auto* first = createWidget(true, "Direction", flags, kinds, QString());
    first->bindProperties(
        &pattern->Part::LinearPatternExtension::Direction,
        &pattern->Part::LinearPatternExtension::Reversed,
        &pattern->Part::LinearPatternExtension::Mode,
        &pattern->Part::LinearPatternExtension::Length,
        &pattern->Part::LinearPatternExtension::Offset,
        &pattern->Part::LinearPatternExtension::Spacings,
        &pattern->Part::LinearPatternExtension::SpacingPattern,
        &pattern->Part::LinearPatternExtension::Occurrences,
        pattern
    );
    addCheckBox("Centered", tr("Centered"));

    auto* second = createWidget(true, "Direction2", flags, kinds, tr("Direction 2"));
    second->bindProperties(
        &pattern->Part::LinearPatternExtension::Direction2,
        &pattern->Part::LinearPatternExtension::Reversed2,
        &pattern->Part::LinearPatternExtension::Mode2,
        &pattern->Part::LinearPatternExtension::Length2,
        &pattern->Part::LinearPatternExtension::Offset2,
        &pattern->Part::LinearPatternExtension::Spacings2,
        &pattern->Part::LinearPatternExtension::SpacingPattern2,
        &pattern->Part::LinearPatternExtension::Occurrences2,
        pattern
    );
    addCheckBox("Centered2", tr("Centered (direction 2)"));
}

void TaskFacePatternParameters::addPolarFields(PartDesign::FacePolarPattern* pattern)
{
    auto* widget = createWidget(
        false,
        "Axis",
        AllowSelection::EDGE | AllowSelection::PLANAR | AllowSelection::CIRCLE,
        tr("A straight or circular edge, or a line"),
        QString()
    );
    widget->bindProperties(
        &pattern->Part::PolarPatternExtension::Axis,
        &pattern->Part::PolarPatternExtension::Reversed,
        &pattern->Part::PolarPatternExtension::Mode,
        &pattern->Part::PolarPatternExtension::Angle,
        &pattern->Part::PolarPatternExtension::Offset,
        &pattern->Part::PolarPatternExtension::Spacings,
        &pattern->Part::PolarPatternExtension::SpacingPattern,
        &pattern->Part::PolarPatternExtension::Occurrences,
        pattern
    );
    addCheckBox("Centered", tr("Centered"));
}

void TaskFacePatternParameters::addMirroredFields(PartDesign::FaceMirrored* pattern)
{
    auto* label = new QLabel(tr("Mirror plane"), proxy);
    auto* combo = new QComboBox(proxy);
    ui->verticalLayout->addWidget(label);
    ui->verticalLayout->addWidget(combo);

    ReferenceField::Writer write;
    ReferenceField* field = createPickField(
        "MirrorPlane",
        AllowSelection::FACE | AllowSelection::PLANAR,
        tr("A plane or a planar face"),
        nullptr,
        &write
    );
    field->hide();
    planeCombo = new ReferenceCombo(combo, field, &pattern->MirrorPlane, write, this);
    fillPlaneChoices();
}

void TaskFacePatternParameters::fillPlaneChoices()
{
    std::vector<ReferenceCombo::Choice> choices;
    if (auto body = PartDesign::Body::findBodyOf(getObject())) {
        try {
            App::Origin* origin = body->getOrigin();
            choices.push_back({tr("Base XY-plane"), origin->getXY(), std::string()});
            choices.push_back({tr("Base XZ-plane"), origin->getXZ(), std::string()});
            choices.push_back({tr("Base YZ-plane"), origin->getYZ(), std::string()});
        }
        catch (const Base::Exception& ex) {
            Base::Console().error("%s\n", ex.what());
        }
    }
    // A link that is none of these shows in the row under the box
    planeCombo->setChoices(choices, tr("Select reference…"));
}

void TaskFacePatternParameters::addCheckBox(const char* property, const QString& text)
{
    auto prop = freecad_cast<App::PropertyBool*>(getObject()->getPropertyByName(property));
    if (!prop) {
        return;
    }
    auto* box = new QCheckBox(text, proxy);
    box->setChecked(prop->getValue());
    ui->verticalLayout->addWidget(box);
    const std::string name = property;
    connect(box, &QCheckBox::toggled, this, [this, name](bool on) {
        if (isUpdateBlocked() || !getObject()) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), name << " = " << (on ? "True" : "False"));
        onParametersChanged();
    });
}

std::vector<ReferenceField*> TaskFacePatternParameters::referenceFields() const
{
    std::vector<ReferenceField*> fields = TaskDressUpParameters::referenceFields();
    fields.insert(fields.end(), pickFields.begin(), pickFields.end());
    return fields;
}

void TaskFacePatternParameters::onParametersChanged()
{
    // A parameter changed: recompute once the changes stop
    if (isUpdateBlocked()) {
        return;
    }
    updateTimer->start();
}

void TaskFacePatternParameters::onUpdateTimer()
{
    setupTransaction();
    recomputeFeature();
    hideOnError();
    updateWidgets();
}

void TaskFacePatternParameters::updateWidgets()
{
    for (auto* widget : widgets) {
        widget->updateUI();
    }
    if (planeCombo) {
        planeCombo->refresh();
    }
}

void TaskFacePatternParameters::onReferencesRepaired()
{
    TaskDressUpParameters::onReferencesRepaired();
    updateWidgets();
}

void TaskFacePatternParameters::apply()
{
    for (auto* widget : widgets) {
        widget->applyQuantitySpinboxes();
    }
    if (getReferences().empty()) {
        std::string text = tr("Empty face pattern created").toStdString();
        Base::Console().warning("%s\n", text.c_str());
    }
}

//**************************************************************************
// TaskDialog
//**************************************************************************

TaskDlgFacePatternParameters::TaskDlgFacePatternParameters(ViewProviderFacePattern* DressUpView)
    : TaskDlgDressUpParameters(DressUpView)
{
    parameter = new TaskFacePatternParameters(DressUpView);

    Content.push_back(parameter);
    Content.push_back(preview);
}

TaskDlgFacePatternParameters::~TaskDlgFacePatternParameters() = default;

bool TaskDlgFacePatternParameters::accept()
{
    auto obj = getObject();
    if (!obj->isError()) {
        getViewObject()->showPreviousFeature(false);
    }

    parameter->apply();

    return TaskDlgDressUpParameters::accept();
}

#include "moc_TaskFacePatternParameters.cpp"
