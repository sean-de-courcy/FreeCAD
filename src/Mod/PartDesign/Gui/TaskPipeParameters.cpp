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


#include <memory>

#include <QPointer>
#include <QTimer>

#include <boost/algorithm/string/predicate.hpp>

#include <App/Application.h>
#include <App/DocumentObject.h>
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

}  // namespace


//**************************************************************************
//**************************************************************************
// Task Parameter
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskPipeParameters::TaskPipeParameters(ViewProviderPipe* PipeView, bool /*newObj*/, QWidget* parent)
    : TaskSketchBasedParameters(PipeView, parent, pipeTaskIconName(PipeView), pipeTaskTitle(PipeView))
    , ui(new Ui_TaskPipeParameters)
    , stateHandler(nullptr)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    // Enable multi-selection in edges list
    ui->listWidgetReferences->setSelectionMode(QAbstractItemView::ExtendedSelection);

    // Ctrl+A should select edges list, not tree view
    auto* selectAll = new QAction(tr("Select All"), this);
    selectAll->setShortcut(QKeySequence::SelectAll);
    selectAll->setShortcutContext(Qt::WidgetShortcut);
    ui->listWidgetReferences->addAction(selectAll);
    connect(selectAll, &QAction::triggered, ui->listWidgetReferences, &QListWidget::selectAll);

    QMetaObject::connectSlotsByName(this);

    // some buttons are handled in a buttongroup
    connect(ui->buttonProfileBase, &QToolButton::toggled, this, &TaskPipeParameters::onProfileButton);
    connect(
        ui->comboBoxTransition,
        qOverload<int>(&QComboBox::currentIndexChanged),
        this,
        &TaskPipeParameters::onTransitionChanged
    );

    // Create context menu
    QAction* remove = new QAction(tr("Remove"), this);
    remove->setShortcut(Gui::QtTools::deleteKeySequence());
    remove->setShortcutContext(Qt::WidgetShortcut);

    // display shortcut behind the context menu entry
    remove->setShortcutVisibleInContextMenu(true);


    ui->listWidgetReferences->addAction(remove);
    connect(remove, &QAction::triggered, this, &TaskPipeParameters::onDeleteEdge);
    connect(ui->buttonRefRemove, &QToolButton::clicked, this, &TaskPipeParameters::onDeleteEdge);
    ui->listWidgetReferences->setContextMenuPolicy(Qt::ActionsContextMenu);

    this->groupLayout()->addWidget(proxy);

    PartDesign::Pipe* pipe = PipeView->getObject<PartDesign::Pipe>();

    // make sure the user sees all important things and load the values; what is shown goes
    // back as it was when the dialog closes, on OK and Cancel (ops#162 B13)
    // first the spine
    if (pipe->Spine.getValue()) {
        shown.show(pipe->Spine.getValue());
        ui->spineBaseEdit->setText(QString::fromUtf8(pipe->Spine.getValue()->Label.getValue()));
    }
    // the profile
    if (pipe->Profile.getValue()) {
        shown.show(pipe->Profile.getValue());
        ui->profileBaseEdit->setText(
            make2DLabel(pipe->Profile.getValue(), pipe->Profile.getSubValues())
        );
    }
    // the auxiliary spine
    if (pipe->AuxiliarySpine.getValue()) {
        shown.show(pipe->AuxiliarySpine.getValue());
    }
    // the spine edges
    std::vector<std::string> strings = pipe->Spine.getSubValues();
    for (const auto& string : strings) {
        QString label = QString::fromStdString(string);
        QListWidgetItem* item = new QListWidgetItem();
        item->setText(label);
        item->setData(Qt::UserRole, QByteArray(label.toUtf8()));
        ui->listWidgetReferences->addItem(item);
    }

    if (!strings.empty()) {
        PipeView->makeTemporaryVisible(true);
    }

    ui->comboBoxTransition->setCurrentIndex(pipe->Transition.getValue());

    updateUI();
    this->blockSelection(false);
}

TaskPipeParameters::~TaskPipeParameters()
{
    try {
        if (auto pipe = getObject<PartDesign::Pipe>()) {
            // setting visibility to true is needed when preselecting profile and path prior to
            // invoking sweep
            Gui::cmdGuiObject(pipe, "Visibility = True");
            getViewObject<ViewProviderPipe>()->highlightReferences(ViewProviderPipe::Spine, false);
            getViewObject<ViewProviderPipe>()->highlightReferences(ViewProviderPipe::Profile, false);
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

void TaskPipeParameters::updateUI()
{}

void TaskPipeParameters::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (stateHandler->getSelectionMode() == StateHandlerTaskPipe::SelectionModes::none) {
        return;
    }

    if (msg.Type == Gui::SelectionChanges::AddSelection) {
        if (referenceSelected(msg)) {
            if (stateHandler->getSelectionMode() == StateHandlerTaskPipe::SelectionModes::refProfile) {
                App::Document* document = App::GetApplication().getDocument(msg.pDocName);
                App::DocumentObject* object = document ? document->getObject(msg.pObjectName)
                                                       : nullptr;
                if (object) {
                    QString label = make2DLabel(object, {msg.pSubName});
                    ui->profileBaseEdit->setText(label);
                }
            }
            else if (
                stateHandler->getSelectionMode() == StateHandlerTaskPipe::SelectionModes::refSpineEdgeAdd
            ) {
                QString sub = QString::fromStdString(msg.pSubName);
                if (!sub.isEmpty()) {
                    QListWidgetItem* item = new QListWidgetItem();
                    item->setText(sub);
                    item->setData(Qt::UserRole, QByteArray(msg.pSubName));
                    ui->listWidgetReferences->addItem(item);
                }

                App::Document* document = App::GetApplication().getDocument(msg.pDocName);
                App::DocumentObject* object = document ? document->getObject(msg.pObjectName)
                                                       : nullptr;
                if (object) {
                    QString label = QString::fromUtf8(object->Label.getValue());
                    ui->spineBaseEdit->setText(label);
                }
            }
            else if (
                stateHandler->getSelectionMode()
                == StateHandlerTaskPipe::SelectionModes::refSpineEdgeRemove
            ) {
                QString sub = QString::fromLatin1(msg.pSubName);
                if (!sub.isEmpty()) {
                    removeFromListWidget(ui->listWidgetReferences, sub);
                }
                else {
                    ui->spineBaseEdit->clear();
                }
            }
            else if (
                stateHandler->getSelectionMode() == StateHandlerTaskPipe::SelectionModes::refSpine
            ) {
                ui->listWidgetReferences->clear();

                App::Document* document = App::GetApplication().getDocument(msg.pDocName);
                App::DocumentObject* object = document ? document->getObject(msg.pObjectName)
                                                       : nullptr;
                if (object) {
                    QString label = QString::fromUtf8(object->Label.getValue());
                    ui->spineBaseEdit->setText(label);
                }
            }

            clearButtons();
            recomputeFeature();
        }

        clearButtons();
        exitSelectionMode();
    }
}

void TaskPipeParameters::onTransitionChanged(int idx)
{
    if (auto pipe = getObject<PartDesign::Pipe>()) {
        pipe->Transition.setValue(idx);
        recomputeFeature();
    }
}

void TaskPipeParameters::onProfileButton(bool checked)
{
    if (checked) {
        if (auto pipe = getObject<PartDesign::Pipe>()) {
            Gui::Document* doc = getGuiDocument();

            if (pipe->Profile.getValue()) {
                auto* pvp = doc->getViewProvider(pipe->Profile.getValue());
                pvp->setVisible(true);
            }
        }
    }
}

void TaskPipeParameters::onTangentChanged(bool checked)
{
    if (auto pipe = getObject<PartDesign::Pipe>()) {
        pipe->SpineTangent.setValue(checked);
        recomputeFeature();
    }
}

void TaskPipeParameters::removeFromListWidget(QListWidget* widget, QString itemstr)
{
    QList<QListWidgetItem*> items = widget->findItems(itemstr, Qt::MatchExactly);
    if (!items.empty()) {
        for (auto item : items) {
            QListWidgetItem* it = widget->takeItem(widget->row(item));
            delete it;
        }
    }
}

void TaskPipeParameters::onDeleteEdge()
{
    auto items = ui->listWidgetReferences->selectedItems();
    if (items.empty()) {
        return;
    }

    const auto pipe = getObject<PartDesign::Pipe>();
    std::vector<std::string> refs = pipe->Spine.getSubValues();

    for (auto* item : items) {
        QByteArray data = item->data(Qt::UserRole).toByteArray();
        std::string obj = data.constData();

        delete ui->listWidgetReferences->takeItem(ui->listWidgetReferences->row(item));

        if (const auto f = std::ranges::find(refs, obj); f != refs.end()) {
            refs.erase(f);
        }
    }

    pipe->Spine.setValue(pipe->Spine.getValue(), refs);
    clearButtons();
    recomputeFeature();
}

bool TaskPipeParameters::referenceSelected(const SelectionChanges& msg) const
{
    auto selectionMode = stateHandler->getSelectionMode();

    if (msg.Type == Gui::SelectionChanges::AddSelection
        && selectionMode != StateHandlerTaskPipe::SelectionModes::none) {
        if (strcmp(msg.pDocName, getAppDocument()->getName()) != 0) {
            return false;
        }

        // not allowed to reference ourself
        const char* fname = getObject()->getNameInDocument();
        if (strcmp(msg.pObjectName, fname) == 0) {
            return false;
        }

        switch (selectionMode) {
            case StateHandlerTaskPipe::SelectionModes::refProfile: {
                auto pipe = getObject<PartDesign::Pipe>();
                Gui::Document* doc = getGuiDocument();

                getViewObject<ViewProviderPipe>()->highlightReferences(ViewProviderPipe::Profile, false);

                bool success = true;
                App::DocumentObject* profile = pipe->getDocument()->getObject(msg.pObjectName);
                if (profile) {
                    std::vector<App::DocumentObject*> sections = pipe->Sections.getValues();

                    // cannot use the same object for profile and section
                    if (std::ranges::find(sections, profile) != sections.end()) {
                        success = false;
                    }
                    else {
                        pipe->Profile.setValue(profile, {msg.pSubName});
                    }

                    // hide the old or new profile again
                    auto* pvp = doc->getViewProvider(pipe->Profile.getValue());
                    if (pvp) {
                        pvp->setVisible(false);
                    }
                }
                return success;
            }
            case StateHandlerTaskPipe::SelectionModes::refSpine:
            case StateHandlerTaskPipe::SelectionModes::refSpineEdgeAdd:
            case StateHandlerTaskPipe::SelectionModes::refSpineEdgeRemove: {
                // change the references
                const std::string subName(msg.pSubName);
                const auto pipe = getObject<PartDesign::Pipe>();
                std::vector<std::string> refs = pipe->Spine.getSubValues();
                const auto f = std::ranges::find(refs, subName);

                if (selectionMode == StateHandlerTaskPipe::SelectionModes::refSpine) {
                    getViewObject<ViewProviderPipe>()->highlightReferences(
                        ViewProviderPipe::Spine,
                        false
                    );
                    refs.clear();
                }
                else if (selectionMode == StateHandlerTaskPipe::SelectionModes::refSpineEdgeAdd) {
                    if (f == refs.end()) {
                        refs.push_back(subName);
                    }
                    else {
                        return false;  // duplicate selection
                    }
                }
                else if (selectionMode == StateHandlerTaskPipe::SelectionModes::refSpineEdgeRemove) {
                    if (f != refs.end()) {
                        refs.erase(f);
                    }
                    else {
                        return false;
                    }
                }

                pipe->Spine.setValue(getAppDocument()->getObject(msg.pObjectName), refs);
                return true;
            }
            default:
                return false;
        }
    }

    return false;
}

void TaskPipeParameters::clearButtons()
{
    ui->buttonProfileBase->setChecked(false);
    ui->buttonRefAdd->setChecked(false);
    ui->buttonRefRemove->setChecked(false);
    ui->buttonSpineBase->setChecked(false);
}

void TaskPipeParameters::onReferenceSelectionTaken()
{
    // Unchecking the buttons ends the dialog's selection mode (TaskDlgPipeParameters).
    clearButtons();
}

void TaskPipeParameters::exitSelectionMode()
{
    // commenting because this should be handled by buttonToggled signal
    // selectionMode = none;
    Gui::Selection().clearSelection();
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

    // If a spine isn't set but user entered a label then search for the appropriate document object
    QString label = ui->spineBaseEdit->text();
    if (!spine && !label.isEmpty()) {
        QByteArray ba = label.toUtf8();
        std::vector<App::DocumentObject*> objs = pipe->getDocument()->findObjects(
            App::DocumentObject::getClassTypeId(),
            nullptr,
            ba.constData()
        );
        if (!objs.empty()) {
            pipe->Spine.setValue(objs.front());
            spine = objs.front();
        }
    }

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
            // FreeCAD-CH (ops#170): each spine on its own (both can be outside the body), and
            // neither when missing (makeCopy(nullptr) put a null into the body after the commit)
            if (outside(spine)) {
                pipe->Spine.setValue(
                    PartDesignGui::TaskFeaturePick::makeCopy(spine, "", dlg.radioIndependent->isChecked()),
                    pipe->Spine.getSubValues()
                );
                copies.push_back(pipe->Spine.getValue());
            }
            if (outside(auxSpine)) {
                pipe->AuxiliarySpine.setValue(
                    PartDesignGui::TaskFeaturePick::makeCopy(
                        auxSpine,
                        "",
                        dlg.radioIndependent->isChecked()
                    ),
                    pipe->AuxiliarySpine.getSubValues()
                );
                copies.push_back(pipe->AuxiliarySpine.getValue());
            }

            std::vector<App::PropertyLinkSubList::SubSet> subSets;
            for (auto& subSet : pipe->Sections.getSubListValues()) {
                if (outside(subSet.first)) {
                    subSets.emplace_back(
                        PartDesignGui::TaskFeaturePick::makeCopy(
                            subSet.first,
                            "",
                            dlg.radioIndependent->isChecked()
                        ),
                        subSet.second
                    );
                    copies.push_back(subSets.back().first);
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
        // FreeCAD crashes unexplainably
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
    , stateHandler(nullptr)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    // clang-format off
    // some buttons are handled in a buttongroup
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

    // Create context menu
    QAction* remove = new QAction(tr("Remove"), this);
    remove->setShortcut(Gui::QtTools::deleteKeySequence());
    remove->setShortcutContext(Qt::WidgetShortcut);

    // display shortcut behind the context menu entry
    remove->setShortcutVisibleInContextMenu(true);

    ui->listWidgetReferences->addAction(remove);
    connect(remove, &QAction::triggered, this, &TaskPipeOrientation::onDeleteItem);
    connect(ui->buttonRefRemove, &QToolButton::clicked, this, &TaskPipeOrientation::onDeleteItem);
    ui->listWidgetReferences->setContextMenuPolicy(Qt::ActionsContextMenu);

    this->groupLayout()->addWidget(proxy);

    PartDesign::Pipe* pipe = PipeView->getObject<PartDesign::Pipe>();

    // add initial values
    if (pipe->AuxiliarySpine.getValue()) {
        ui->profileBaseEdit->setText(
            QString::fromUtf8(pipe->AuxiliarySpine.getValue()->Label.getValue())
        );
    }

    std::vector<std::string> strings = pipe->AuxiliarySpine.getSubValues();
    for (const auto& string : strings) {
        QString label = QString::fromStdString(string);
        QListWidgetItem* item = new QListWidgetItem();
        item->setText(label);
        item->setData(Qt::UserRole, QByteArray(label.toUtf8()));
        ui->listWidgetReferences->addItem(item);
    }

    ui->comboBoxMode->setCurrentIndex(pipe->Mode.getValue());
    ui->curvilinear->setChecked(pipe->AuxiliaryCurvilinear.getValue());
    {
        // FreeCAD-CH (ops#170): the binormal as stored. The boxes kept their 0, and editing one
        // wrote all three. Loading writes nothing.
        const Base::Vector3d& binormal = pipe->Binormal.getValue();
        QSignalBlocker blockX(ui->doubleSpinBoxX);
        QSignalBlocker blockY(ui->doubleSpinBoxY);
        QSignalBlocker blockZ(ui->doubleSpinBoxZ);
        ui->doubleSpinBoxX->setValue(binormal.x);
        ui->doubleSpinBoxY->setValue(binormal.y);
        ui->doubleSpinBoxZ->setValue(binormal.z);
    }

    // should be called after panel has become visible
    QMetaObject::invokeMethod(this, "updateUI", Qt::QueuedConnection, Q_ARG(int, pipe->Mode.getValue()));
    this->blockSelection(false);
}

TaskPipeOrientation::~TaskPipeOrientation()
{
    try {
        if (auto view = getViewObject<ViewProviderPipe>()) {
            view->highlightReferences(ViewProviderPipe::AuxiliarySpine, false);
        }
    }
    catch (const Standard_OutOfRange&) {
    }
}

void TaskPipeOrientation::onOrientationChanged(int idx)
{
    if (auto pipe = getObject<PartDesign::Pipe>()) {
        pipe->Mode.setValue(idx);
        recomputeFeature();
    }
}

void TaskPipeOrientation::clearButtons()
{
    ui->buttonRefAdd->setChecked(false);
    ui->buttonRefRemove->setChecked(false);
    ui->buttonProfileBase->setChecked(false);
}

void TaskPipeOrientation::onReferenceSelectionTaken()
{
    clearButtons();
}

void TaskPipeOrientation::exitSelectionMode()
{
    Gui::Selection().clearSelection();
}

void TaskPipeOrientation::onClearButton()
{
    ui->listWidgetReferences->clear();
    ui->profileBaseEdit->clear();
    if (auto view = getViewObject<ViewProviderPipe>()) {
        view->highlightReferences(ViewProviderPipe::AuxiliarySpine, false);
        getObject<PartDesign::Pipe>()->AuxiliarySpine.setValue(nullptr);
        recomputeFeature();  // FreeCAD-CH (ops#170): as every other change in the panel
    }
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

void TaskPipeOrientation::onSelectionChanged(const SelectionChanges& msg)
{
    if (stateHandler->getSelectionMode() == StateHandlerTaskPipe::SelectionModes::none) {
        return;
    }

    if (msg.Type == Gui::SelectionChanges::AddSelection) {
        if (referenceSelected(msg)) {
            if (stateHandler->getSelectionMode()
                == StateHandlerTaskPipe::SelectionModes::refAuxSpineEdgeAdd) {
                QString sub = QString::fromStdString(msg.pSubName);
                if (!sub.isEmpty()) {
                    QListWidgetItem* item = new QListWidgetItem();
                    item->setText(sub);
                    item->setData(Qt::UserRole, QByteArray(msg.pSubName));
                    ui->listWidgetReferences->addItem(item);
                }

                App::Document* document = App::GetApplication().getDocument(msg.pDocName);
                App::DocumentObject* object = document ? document->getObject(msg.pObjectName)
                                                       : nullptr;
                if (object) {
                    QString label = QString::fromUtf8(object->Label.getValue());
                    ui->profileBaseEdit->setText(label);
                }
            }
            else if (
                stateHandler->getSelectionMode()
                == StateHandlerTaskPipe::SelectionModes::refAuxSpineEdgeRemove
            ) {
                QString sub = QString::fromLatin1(msg.pSubName);
                if (!sub.isEmpty()) {
                    removeFromListWidget(ui->listWidgetReferences, sub);
                }
                else {
                    ui->profileBaseEdit->clear();
                }
            }
            else if (
                stateHandler->getSelectionMode() == StateHandlerTaskPipe::SelectionModes::refAuxSpine
            ) {
                ui->listWidgetReferences->clear();

                App::Document* document = App::GetApplication().getDocument(msg.pDocName);
                App::DocumentObject* object = document ? document->getObject(msg.pObjectName)
                                                       : nullptr;
                if (object) {
                    QString label = QString::fromUtf8(object->Label.getValue());
                    ui->profileBaseEdit->setText(label);
                }
            }

            clearButtons();
            auto view = getViewObject<ViewProviderPipe>();
            view->highlightReferences(ViewProviderPipe::AuxiliarySpine, false);
            recomputeFeature();
        }

        clearButtons();
        exitSelectionMode();
    }
}

bool TaskPipeOrientation::referenceSelected(const SelectionChanges& msg) const
{
    auto selectionMode = stateHandler->getSelectionMode();

    if (msg.Type == Gui::SelectionChanges::AddSelection
        && (selectionMode == StateHandlerTaskPipe::SelectionModes::refAuxSpine
            || selectionMode == StateHandlerTaskPipe::SelectionModes::refAuxSpineEdgeAdd
            || selectionMode == StateHandlerTaskPipe::SelectionModes::refAuxSpineEdgeRemove)) {
        if (strcmp(msg.pDocName, getObject()->getDocument()->getName()) != 0) {
            return false;
        }

        // not allowed to reference ourself
        const char* fname = getObject()->getNameInDocument();
        if (strcmp(msg.pObjectName, fname) == 0) {
            return false;
        }

        if (const auto pipe = getObject<PartDesign::Pipe>()) {
            // change the references
            const std::string subName(msg.pSubName);
            std::vector<std::string> refs = pipe->AuxiliarySpine.getSubValues();
            const auto f = std::ranges::find(refs, subName);

            if (selectionMode == StateHandlerTaskPipe::SelectionModes::refAuxSpine) {
                refs.clear();
            }
            else if (selectionMode == StateHandlerTaskPipe::SelectionModes::refAuxSpineEdgeAdd) {
                if (f != refs.end()) {
                    return false;  // duplicate selection
                }

                refs.push_back(subName);
            }
            else if (selectionMode == StateHandlerTaskPipe::SelectionModes::refAuxSpineEdgeRemove) {
                if (f == refs.end()) {
                    return false;
                }

                refs.erase(f);
            }

            App::Document* doc = pipe->getDocument();
            pipe->AuxiliarySpine.setValue(doc->getObject(msg.pObjectName), refs);
            return true;
        }
    }

    return false;
}

void TaskPipeOrientation::removeFromListWidget(QListWidget* widget, QString name)
{
    QList<QListWidgetItem*> items = widget->findItems(name, Qt::MatchExactly);
    if (!items.empty()) {
        for (auto item : items) {
            QListWidgetItem* it = widget->takeItem(widget->row(item));
            delete it;
        }
    }
}

void TaskPipeOrientation::onDeleteItem()
{
    // Delete the selected spine
    int row = ui->listWidgetReferences->currentRow();
    QListWidgetItem* item = ui->listWidgetReferences->takeItem(row);
    if (item) {
        QByteArray data = item->data(Qt::UserRole).toByteArray();
        delete item;

        // search inside the list of spines
        if (const auto pipe = getObject<PartDesign::Pipe>()) {
            std::vector<std::string> refs = pipe->AuxiliarySpine.getSubValues();
            const std::string obj = data.constData();

            // if something was found, delete it and update the spine list
            if (const auto f = std::ranges::find(refs, obj); f != refs.end()) {
                refs.erase(f);
                pipe->AuxiliarySpine.setValue(pipe->AuxiliarySpine.getValue(), refs);
                clearButtons();
                recomputeFeature();
            }
        }
    }
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
    , stateHandler(nullptr)
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
        if (!ReferenceActions::wholeObjectFits(obj, sub, why)) {
            return false;
        }
        auto pipe = freecad_cast<PartDesign::Pipe*>(pipeT.getObject());
        if (pipe && obj == pipe->Profile.getValue()) {
            why = QT_TR_NOOP("This is the pipe's profile: it can't be a section too.");
            return false;
        }
        if (pipe && (obj == pipe->Spine.getValue() || obj == pipe->AuxiliarySpine.getValue())) {
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

    stateHandler = new StateHandlerTaskPipe();

    Content.push_back(parameter);
    Content.push_back(orientation);
    Content.push_back(scaling);
    Content.push_back(preview);

    parameter->stateHandler = stateHandler;
    orientation->stateHandler = stateHandler;
    scaling->stateHandler = stateHandler;

    buttonGroup = new ButtonGroup(this);
    buttonGroup->setExclusive(true);

    buttonGroup->addButton(parameter->ui->buttonProfileBase, StateHandlerTaskPipe::refProfile);
    buttonGroup->addButton(parameter->ui->buttonSpineBase, StateHandlerTaskPipe::refSpine);
    buttonGroup->addButton(parameter->ui->buttonRefAdd, StateHandlerTaskPipe::refSpineEdgeAdd);
    buttonGroup->addButton(parameter->ui->buttonRefRemove, StateHandlerTaskPipe::refSpineEdgeRemove);

    buttonGroup->addButton(orientation->ui->buttonProfileBase, StateHandlerTaskPipe::refAuxSpine);
    buttonGroup->addButton(orientation->ui->buttonRefAdd, StateHandlerTaskPipe::refAuxSpineEdgeAdd);
    buttonGroup->addButton(orientation->ui->buttonRefRemove, StateHandlerTaskPipe::refAuxSpineEdgeRemove);

    connect(
        buttonGroup,
        qOverload<QAbstractButton*, bool>(&QButtonGroup::buttonToggled),
        this,
        &TaskDlgPipeParameters::onButtonToggled
    );
    // A field armed ends the profile's and the spines' pick buttons, and they the field
    connect(scaling->sectionsField, &ReferenceField::arming, this, [this]() {
        parameter->clearButtons();
        orientation->clearButtons();
    });
}

TaskDlgPipeParameters::~TaskDlgPipeParameters()
{
    delete stateHandler;
}

void TaskDlgPipeParameters::onButtonToggled(QAbstractButton* button, bool checked)
{
    int id = buttonGroup->id(button);

    if (checked) {
        // hideObject();
        fieldGroup->disarm();
        Gui::Selection().clearSelection();
        stateHandler->selectionMode = static_cast<StateHandlerTaskPipe::SelectionModes>(id);
    }
    else {
        Gui::Selection().clearSelection();
        if (stateHandler->selectionMode == static_cast<StateHandlerTaskPipe::SelectionModes>(id)) {
            stateHandler->selectionMode = StateHandlerTaskPipe::SelectionModes::none;
        }
    }

    switch (id) {
        case StateHandlerTaskPipe::SelectionModes::refProfile:
            getViewObject<ViewProviderPipe>()->highlightReferences(ViewProviderPipe::Profile, checked);
            break;
        case StateHandlerTaskPipe::SelectionModes::refSpine:
        case StateHandlerTaskPipe::SelectionModes::refSpineEdgeAdd:
        case StateHandlerTaskPipe::SelectionModes::refSpineEdgeRemove:
            getViewObject<ViewProviderPipe>()->highlightReferences(ViewProviderPipe::Spine, checked);
            break;
        case StateHandlerTaskPipe::SelectionModes::refAuxSpine:
        case StateHandlerTaskPipe::SelectionModes::refAuxSpineEdgeAdd:
        case StateHandlerTaskPipe::SelectionModes::refAuxSpineEdgeRemove:
            getViewObject<ViewProviderPipe>()->highlightReferences(
                ViewProviderPipe::AuxiliarySpine,
                checked
            );
            break;
        default:
            break;
    }
}

//==== calls from the TaskView ===============================================================


bool TaskDlgPipeParameters::accept()
{
    return parameter->accept();
}

bool TaskDlgPipeParameters::reject()
{
    // What the edit showed goes back first: the abort that follows shows a new pipe's profile
    // again, and a restore after it (the panels' destructors) would hide it (ops#150)
    parameter->shown.restore();
    scaling->shown.restore();
    return TaskDlgSketchBasedParameters::reject();
}


#include "moc_TaskPipeParameters.cpp"
