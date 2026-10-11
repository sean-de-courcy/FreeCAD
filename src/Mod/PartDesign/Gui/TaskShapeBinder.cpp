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


#include <boost/core/ignore_unused.hpp>
#include <QAction>
#include <QLabel>
#include <QMessageBox>
#include <QSignalBlocker>
#include <QTimer>


#include <App/Document.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/CommandT.h>
#include <Gui/Document.h>
#include <Gui/MainWindow.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Tools.h>
#include <Gui/Widgets.h>

#include <Mod/Part/App/PartFeature.h>
#include <Mod/PartDesign/App/ShapeBinder.h>

#include "ui_TaskShapeBinder.h"
#include "TaskShapeBinder.h"


using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskShapeBinder */


//**************************************************************************
//**************************************************************************
// TaskShapeBinder
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskShapeBinder::TaskShapeBinder(ViewProviderShapeBinder* view, bool newObj, QWidget* parent)
    : Gui::TaskView::TaskBox(
          Gui::BitmapFactory().pixmap("PartDesign_ShapeBinder"),
          tr("Shape Binder Parameters"),
          true,
          parent
      )
    , SelectionObserver(view)
    , ui(new Ui_TaskShapeBinder)
    , vp(view)
{
    boost::ignore_unused(newObj);

    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    setupButtonGroup();
    setupContextMenu();
    // A Support the binder doesn't bind as it is (set from Python) is named when the panel opens:
    // an edit here sets Support to what the panel shows (PR 232 review L2, ops#266)
    droppedNote = new QLabel(this);
    droppedNote->setObjectName(QStringLiteral("droppedNote"));
    droppedNote->setWordWrap(true);
    droppedNote->setVisible(false);
    this->groupLayout()->addWidget(droppedNote);
    this->groupLayout()->addWidget(proxy);

    updateUI();

    auto* binder = view->getObject<PartDesign::ShapeBinder>();
    if (binder && binder->getDocument()) {
        supportConnection = binder->getDocument()->signalChangedObject.connect(
            [this, binder](const App::DocumentObject& obj, const App::Property& prop) {
                // The object field and the list follow too, after the change is done (ops#276:
                // the note did, the list didn't, and an OK set the stale object again). The
                // panel's own edits come here as well: the list then already shows Support
                if (&obj == binder && &prop == &binder->Support) {
                    QTimer::singleShot(0, this, [this]() { refreshFromSupport(); });
                }
            }
        );
    }
}

TaskShapeBinder::~TaskShapeBinder() = default;

void TaskShapeBinder::updateUI()
{
    Gui::Document* doc = vp->getDocument();

    // add initial values
    App::GeoFeature* obj = nullptr;
    std::vector<std::string> subs;

    PartDesign::ShapeBinder::getFilteredReferences(
        &vp->getObject<PartDesign::ShapeBinder>()->Support,
        obj,
        subs
    );

    if (obj) {
        ui->baseEdit->setText(QString::fromStdString(obj->Label.getStrValue()));
    }

    // Allow one to clear the Support
    ui->baseEdit->setClearButtonEnabled(true);
    connect(ui->baseEdit, &QLineEdit::textChanged, this, &TaskShapeBinder::supportChanged);

    for (const auto& sub : subs) {
        ui->listWidgetReferences->addItem(QString::fromStdString(sub));
    }

    if (obj) {
        auto* svp = doc->getViewProvider(obj);
        if (svp) {
            supportShow = svp->isShow();
            svp->setVisible(true);
        }
    }

    updateDroppedNote();
}

void TaskShapeBinder::refreshFromSupport()
{
    if (vp.expired()) {
        return;
    }
    App::GeoFeature* obj = nullptr;
    std::vector<std::string> subs;
    PartDesign::ShapeBinder::getFilteredReferences(
        &vp->getObject<PartDesign::ShapeBinder>()->Support,
        obj,
        subs
    );

    const QString label = obj ? QString::fromStdString(obj->Label.getStrValue()) : QString();
    if (ui->baseEdit->text() != label) {
        // Support is already what the field shows: clearing it mustn't write Support again
        QSignalBlocker block(ui->baseEdit);
        ui->baseEdit->setText(label);
    }

    QStringList wanted;
    for (const auto& sub : subs) {
        wanted << QString::fromStdString(sub);
    }
    QStringList shown;
    for (int row = 0; row < ui->listWidgetReferences->count(); ++row) {
        shown << ui->listWidgetReferences->item(row)->text();
    }
    if (shown != wanted) {
        ui->listWidgetReferences->clear();
        ui->listWidgetReferences->addItems(wanted);
    }

    updateDroppedNote();
}

void TaskShapeBinder::updateDroppedNote()
{
    if (vp.expired()) {
        return;
    }
    const QString dropped = droppedText(&vp->getObject<PartDesign::ShapeBinder>()->Support);
    droppedNote->setText(
        dropped.isEmpty() ? QString()
                          : tr("The binder doesn't bind its Support as it is. %1\nThe list shows "
                               "what it can bind; an edit here sets Support to that.")
                                .arg(dropped)
    );
    droppedNote->setVisible(!dropped.isEmpty());
}

QString TaskShapeBinder::droppedText(const App::PropertyLinkSubList* support)
{
    using Kind = PartDesign::ShapeBinder::Dropped::Kind;
    const PartDesign::ShapeBinder::Dropped dropped =
        PartDesign::ShapeBinder::findDroppedReferences(support);
    QStringList names;
    for (const std::string& name : dropped.names) {
        names << QStringLiteral("'%1'").arg(QString::fromStdString(name));
    }
    const QString list = names.join(QStringLiteral(", "));
    const QString object = QString::fromStdString(dropped.object);
    switch (dropped.kind) {
        case Kind::None:
            return {};
        case Kind::NoPartFeature:
            return tr("A shape binder binds a Part feature or a datum; Support links none, only %1.")
                .arg(list);
        case Kind::OtherObjects:
            return tr("A shape binder binds one object: Support links '%1' and also %2. Use a "
                      "sub-shape binder to bind several objects.")
                .arg(object, list);
        case Kind::Mixed:
            return tr("Support links '%1' both as a whole and by its elements (%2); link either "
                      "the object or its elements.")
                .arg(object, list);
        case Kind::DatumElements:
            return tr("Support links the datum '%1' by its elements (%2); a datum is bound as a "
                      "whole: link it without elements.")
                .arg(object, list);
    }
    return {};
}

void TaskShapeBinder::setupButtonGroup()
{
    buttonGroup = new ButtonGroup(this);
    buttonGroup->setExclusive(true);

    buttonGroup->addButton(ui->buttonRefAdd, TaskShapeBinder::refAdd);
    buttonGroup->addButton(ui->buttonRefRemove, TaskShapeBinder::refRemove);
    buttonGroup->addButton(ui->buttonBase, TaskShapeBinder::refObjAdd);
    connect(
        buttonGroup,
        qOverload<QAbstractButton*, bool>(&QButtonGroup::buttonToggled),
        this,
        &TaskShapeBinder::onButtonToggled
    );
}

void TaskShapeBinder::setupContextMenu()
{
    // Create context menu
    QAction* remove = new QAction(tr("Remove"), this);
    remove->setShortcut(Gui::QtTools::deleteKeySequence());
    remove->setShortcutContext(Qt::WidgetShortcut);
    // display shortcut behind the context menu entry
    remove->setShortcutVisibleInContextMenu(true);
    ui->listWidgetReferences->addAction(remove);
    connect(remove, &QAction::triggered, this, &TaskShapeBinder::deleteItem);
    ui->listWidgetReferences->setContextMenuPolicy(Qt::ActionsContextMenu);
}

void TaskShapeBinder::supportChanged(const QString& text)
{
    if (!vp.expired() && text.isEmpty()) {
        PartDesign::ShapeBinder* binder = vp->getObject<PartDesign::ShapeBinder>();
        binder->Support.setValue(nullptr, nullptr);
        vp->highlightReferences(false);
        vp->getObject()->getDocument()->recomputeFeature(vp->getObject());
        ui->listWidgetReferences->clear();
        updateDroppedNote();
    }
}

void TaskShapeBinder::onButtonToggled(QAbstractButton* button, bool checked)
{
    int id = buttonGroup->id(button);

    if (checked) {
        Gui::Selection().clearSelection();
        selectionMode = static_cast<TaskShapeBinder::selectionModes>(id);
    }
    else {
        Gui::Selection().clearSelection();
        if (selectionMode == static_cast<TaskShapeBinder::selectionModes>(id)) {
            selectionMode = TaskShapeBinder::none;
        }
    }

    switch (id) {
        case TaskShapeBinder::refAdd:
        case TaskShapeBinder::refRemove:
            if (!vp.expired()) {
                vp->highlightReferences(true);
            }
            break;
        case TaskShapeBinder::refObjAdd:
            break;
        default:
            break;
    }
}

void TaskShapeBinder::changeEvent(QEvent*)
{}

void TaskShapeBinder::deleteItem()
{
    if (vp.expired()) {
        return;
    }

    // Delete the selected spine
    int row = ui->listWidgetReferences->currentRow();
    if (row >= 0 && ui->listWidgetReferences->count() == 1) {
        refuseRemovingTheLastElement();
        return;
    }
    QListWidgetItem* item = ui->listWidgetReferences->takeItem(row);
    if (item) {
        QByteArray data = item->text().toLatin1();
        delete item;

        // search inside the list of sub-elements
        App::GeoFeature* obj = nullptr;
        std::vector<std::string> subs;

        PartDesign::ShapeBinder* binder = vp->getObject<PartDesign::ShapeBinder>();
        PartDesign::ShapeBinder::getFilteredReferences(&binder->Support, obj, subs);

        const std::string subname = data.constData();

        // if something was found, delete it and update the support
        if (const auto it = std::ranges::find(subs, subname); it != subs.end()) {
            subs.erase(it);
            binder->Support.setValue(obj, subs);

            vp->highlightReferences(false);
            vp->getObject()->getDocument()->recomputeFeature(vp->getObject());
            updateDroppedNote();

            clearButtons();
        }
    }
}

void TaskShapeBinder::refuseRemovingTheLastElement() const
{
    // Support.setValue(obj, {}) stores (obj, ""): the whole object, which the user didn't pick
    // (ops#251). Binding the whole object and emptying the binder have their own controls.
    QString label;
    if (!vp.expired()) {
        if (auto obj = vp->getObject<PartDesign::ShapeBinder>()->Support.getValue()) {
            label = QString::fromStdString(obj->Label.getStrValue());
        }
    }
    Gui::getMainWindow()->showMessage(
        tr("The binder's last element is kept: without it the binder would hold the whole of %1. "
           "Use Object to bind the whole object. Clearing the object field unlinks the binder: it "
           "then keeps its current shape and no longer follows %1.")
            .arg(label),
        10000
    );
}

void TaskShapeBinder::removeFromListWidget(QListWidget* widget, QString itemstr)
{
    QList<QListWidgetItem*> items = widget->findItems(itemstr, Qt::MatchExactly);
    if (!items.empty()) {
        for (auto item : items) {
            QListWidgetItem* it = widget->takeItem(widget->row(item));
            delete it;
        }
    }
}

void TaskShapeBinder::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    auto setObjectLabel = [this](const Gui::SelectionChanges& msg) {
        App::DocumentObject* obj = msg.Object.getObject();
        if (obj) {
            ui->baseEdit->setText(QString::fromStdString(obj->Label.getStrValue()));
        }
    };

    if (selectionMode == none) {
        return;
    }

    if (msg.Type == Gui::SelectionChanges::AddSelection) {
        if (referenceSelected(msg)) {
            if (selectionMode == refAdd) {
                QString sub = QString::fromUtf8(msg.pSubName);
                if (!sub.isEmpty()) {
                    ui->listWidgetReferences->addItem(sub);
                }

                setObjectLabel(msg);
            }
            else if (selectionMode == refRemove) {
                QString sub = QString::fromUtf8(msg.pSubName);
                if (!sub.isEmpty()) {
                    removeFromListWidget(ui->listWidgetReferences, sub);
                }
            }
            else if (selectionMode == refObjAdd) {
                ui->listWidgetReferences->clear();
                setObjectLabel(msg);
            }

            clearButtons();

            if (!vp.expired()) {
                vp->highlightReferences(false);
                vp->getObject()->getDocument()->recomputeFeature(vp->getObject());
                updateDroppedNote();
            }
        }

        clearButtons();
        exitSelectionMode();
    }
}

bool TaskShapeBinder::referenceSelected(const SelectionChanges& msg) const
{
    if (vp.expired()) {
        return false;
    }

    if ((msg.Type == Gui::SelectionChanges::AddSelection)
        && ((selectionMode == refAdd) || (selectionMode == refRemove)
            || (selectionMode == refObjAdd))) {

        if (strcmp(msg.pDocName, vp->getObject()->getDocument()->getName()) != 0) {
            return false;
        }

        // not allowed to reference ourself
        const char* fname = vp->getObject()->getNameInDocument();
        if (strcmp(msg.pObjectName, fname) == 0) {
            return false;
        }

        // change the references
        std::string subName(msg.pSubName);

        Part::Feature* selectedObj = nullptr;
        App::GeoFeature* obj = nullptr;
        std::vector<std::string> refs;

        PartDesign::ShapeBinder::getFilteredReferences(
            &vp->getObject<PartDesign::ShapeBinder>()->Support,
            obj,
            refs
        );

        // get selected object
        auto docObj = vp->getObject()->getDocument()->getObject(msg.pObjectName);
        if (docObj && docObj->isDerivedFrom<Part::Feature>()) {
            selectedObj = static_cast<Part::Feature*>(docObj);
        }

        // ensure we have a valid object, and say why another one binds nothing (PR 232 review
        // L1, ops#266)
        if (!selectedObj) {
            if (docObj) {
                Gui::getMainWindow()->showMessage(
                    tr("%1 isn't a Part feature: the panel binds a Part feature or its elements. "
                       "Use a sub-shape binder to bind a Link or another object.")
                        .arg(QString::fromStdString(docObj->Label.getStrValue())),
                    10000
                );
            }
            return false;
        }
        if (!obj) {
            // Support has not been set before
            obj = selectedObj;
        }

        if (selectionMode != refObjAdd) {
            // ensure the new selected subref belongs to the same object
            if (strcmp(msg.pObjectName, obj->getNameInDocument()) != 0) {
                // Say why the click adds nothing (ops#251)
                Gui::getMainWindow()->showMessage(
                    tr("The binder holds elements of %1; %2 is another object. Use Object to "
                       "bind another object, or a sub-shape binder to bind several.")
                        .arg(QString::fromStdString(obj->Label.getStrValue()),
                             QString::fromStdString(selectedObj->Label.getStrValue())),
                    10000
                );
                return false;
            }

            const auto f = std::ranges::find(refs, subName);

            if (selectionMode == refAdd) {
                if (subName.empty() && !refs.empty()) {
                    // The whole object beside its elements is a Support the binder can't bind
                    // (PR 232 review M1)
                    Gui::getMainWindow()->showMessage(
                        tr("The binder holds elements of %1, not the whole object. Use Object to "
                           "bind the whole object.")
                            .arg(QString::fromStdString(obj->Label.getStrValue())),
                        10000
                    );
                    return false;
                }
                if (f == refs.end()) {
                    refs.push_back(subName);
                }
                else {
                    return false;  // duplicate selection
                }
            }
            else {
                if (f != refs.end() && refs.size() == 1) {
                    refuseRemovingTheLastElement();
                    return false;
                }
                if (f != refs.end()) {
                    refs.erase(f);
                }
                else {
                    return false;
                }
            }
        }
        else {
            // change object
            refs.clear();
            obj = selectedObj;
        }

        vp->getObject<PartDesign::ShapeBinder>()->Support.setValue(obj, refs);

        return true;
    }

    return false;
}

void TaskShapeBinder::clearButtons()
{

    ui->buttonRefAdd->setChecked(false);
    ui->buttonRefRemove->setChecked(false);
    ui->buttonBase->setChecked(false);
}

void TaskShapeBinder::exitSelectionMode()
{

    selectionMode = none;
    Gui::Selection().clearSelection();
}

void TaskShapeBinder::accept()
{
    if (vp.expired()) {
        return;
    }

    std::string label = ui->baseEdit->text().toStdString();
    PartDesign::ShapeBinder* binder = vp->getObject<PartDesign::ShapeBinder>();
    if (!binder->Support.getValue() && !label.empty()) {
        auto mode = selectionMode;
        selectionMode = refObjAdd;
        SelectionChanges msg(
            SelectionChanges::AddSelection,
            binder->getDocument()->getName(),
            label.c_str()
        );
        referenceSelected(msg);
        selectionMode = mode;
    }
}

//**************************************************************************
//**************************************************************************
// TaskDlgShapeBinder
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgShapeBinder::TaskDlgShapeBinder(ViewProviderShapeBinder* view, bool newObj)
    : Gui::TaskView::TaskDialog()
    , vp(view)
{
    assert(view);
    parameter = new TaskShapeBinder(view, newObj);

    Content.push_back(parameter);
}

TaskDlgShapeBinder::~TaskDlgShapeBinder() = default;

bool TaskDlgShapeBinder::accept()
{
    try {
        if (!vp.expired()) {
            parameter->accept();

            Gui::cmdAppDocument(vp->getObject(), "recompute()");
            if (!vp->getObject()->isValid()) {
                throw Base::RuntimeError(vp->getObject()->getStatusString());
            }
            Gui::cmdGuiDocument(vp->getObject(), "resetEdit()");
            vp->getDocument()->commitCommand();
        }
    }
    catch (const Base::Exception& e) {
        vp->getDocument()->abortCommand();
        QMessageBox::warning(
            parameter,
            tr("Input Error"),
            QApplication::translate("Exception", e.what())
        );
        return false;
    }

    return true;
}

bool TaskDlgShapeBinder::reject()
{
    if (!vp.expired()) {
        // roll back the done things (deletes 'vp')
        // Gui::Command::abortCommand();
        vp->getDocument()->abortCommand();
        App::Document* doc = vp->getObject()->getDocument();
        Gui::cmdGuiDocument(doc, "resetEdit()");
        Gui::cmdAppDocument(doc, "recompute()");
    }
    return true;
}

#include "moc_TaskShapeBinder.cpp"
