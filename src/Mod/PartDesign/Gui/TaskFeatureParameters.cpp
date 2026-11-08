// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (C) 2015 Alexander Golubev (Fat-Zer) <fatzer2@gmail.com>    *
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
#include <cmath>
#include <deque>
#include <map>
#include <vector>

#include <QAbstractSpinBox>
#include <QAction>
#include <QApplication>
#include <QComboBox>
#include <QEvent>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPointer>
#include <QPushButton>
#include <QSignalBlocker>
#include <QStandardItemModel>
#include <QTimer>


#include <App/AutoTransaction.h>
#include <App/DocumentObserver.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/CommandT.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/InputHint.h>
#include <Gui/Inventor/Draggers/Gizmo.h>
#include <Gui/MainWindow.h>
#include <Gui/BitmapFactory.h>
#include <Mod/PartDesign/App/Feature.h>
#include <Mod/PartDesign/App/FeatureAddSub.h>
#include <Mod/PartDesign/App/FeatureBoolean.h>
#include <Mod/PartDesign/App/FeatureSketchBased.h>
#include <Mod/PartDesign/App/Body.h>

#include "ui_TaskPreviewParameters.h"

#include "ReferenceField.h"
#include "TaskFeatureParameters.h"
#include "TaskReferences.h"
#include "TaskSketchBasedParameters.h"
#include "Utils.h"
#include "ViewProviderBody.h"

using namespace PartDesignGui;
using namespace Gui;

/*********************************************************************
 *                      Task Feature Parameters                      *
 *********************************************************************/

TaskPreviewParameters::TaskPreviewParameters(ViewProvider* vp, QWidget* parent)
    : TaskBox(BitmapFactory().pixmap("tree-pre-sel"), tr("Preview"), true, parent)
    , vp(vp)
    , ui(std::make_unique<Ui_TaskPreviewParameters>())
{
    vp->showPreviousFeature(!hGrp->GetBool("ShowFinal", false));
    vp->showPreview(hGrp->GetBool("ShowTransparentPreview", true));

    auto* proxy = new QWidget(this);
    ui->setupUi(proxy);

    ui->showFinalCheckBox->setChecked(vp->isVisible());
    ui->showTransparentPreviewCheckBox->setChecked(vp->isPreviewEnabled());
    // The overlay's opacity (ops#150 W5): one setting for every feature, applied to this one now
    // since another dialog may have changed it
    ui->opacitySlider->setValue(static_cast<int>(std::lround(ViewProvider::previewOpacity() * 100)));
    ui->opacitySlider->setEnabled(vp->isPreviewEnabled());
    vp->updatePreviewOpacity();
    connect(ui->opacitySlider, &QSlider::valueChanged, this, &TaskPreviewParameters::onOpacityChanged);

#if QT_VERSION >= QT_VERSION_CHECK(6, 7, 0)
    connect(
        ui->showTransparentPreviewCheckBox,
        &QCheckBox::checkStateChanged,
        this,
        &TaskPreviewParameters::onShowPreviewChanged
    );
    connect(
        ui->showFinalCheckBox,
        &QCheckBox::checkStateChanged,
        this,
        &TaskPreviewParameters::onShowFinalChanged
    );
#else
    connect(
        ui->showTransparentPreviewCheckBox,
        &QCheckBox::stateChanged,
        this,
        &TaskPreviewParameters::onShowPreviewChanged
    );
    connect(
        ui->showFinalCheckBox,
        &QCheckBox::stateChanged,
        this,
        &TaskPreviewParameters::onShowFinalChanged
    );
#endif

    groupLayout()->addWidget(proxy);
}

TaskPreviewParameters::~TaskPreviewParameters() = default;

void TaskPreviewParameters::onShowFinalChanged(bool show)
{
    vp->showPreviousFeature(!show);
    // Final: the Body's end result while the dialog is open, else rolled back to the feature
    // (ops#127)
    ViewProviderBody::setEditFinal(vp->getObject(), show);
}

void TaskPreviewParameters::onShowPreviewChanged(bool show)
{
    vp->showPreview(show);
    ui->opacitySlider->setEnabled(show);
}

void TaskPreviewParameters::onOpacityChanged(int percent)
{
    hGrp->SetInt("Opacity", percent);
    vp->updatePreviewOpacity();
}

TaskFeatureParameters::TaskFeatureParameters(
    PartDesignGui::ViewProvider* vp,
    QWidget* parent,
    const std::string& pixmapname,
    const QString& parname
)
    : TaskBox(Gui::BitmapFactory().pixmap(pixmapname.c_str()), parname, true, parent)
    , vp(vp)
    , blockUpdate(false)
{
    Gui::Document* doc = vp->getDocument();
    this->attachDocument(doc);
}

TaskFeatureParameters::~TaskFeatureParameters()
{
    hideDraggerHints();
}

void TaskFeatureParameters::showDraggerHints()
{
    if (!Gui::GizmoContainer::isEnabled() || !Gui::GizmoContainer::isCoarseSnapEnabled()) {
        return;
    }

    const Gui::InputHint::UserInput key = Gui::GizmoContainer::getFineSnapKey();
    const bool coarseByDefault = Gui::GizmoContainer::isCoarseByDefault();

    QString message;
    if (coarseByDefault) {
        message = tr("%1 fine dragging");
    }
    else {
        message = tr("%1 coarse dragging");
    }

    Gui::getMainWindow()->showHints({{
        .message = message,
        .sequences = {{key}},
    }});
}

void TaskFeatureParameters::hideDraggerHints()
{
    Gui::getMainWindow()->hideHints();
}

void TaskFeatureParameters::slotDeletedObject(const Gui::ViewProviderDocumentObject& Obj)
{
    if (this->vp == &Obj) {
        this->vp = nullptr;
    }
}

void TaskFeatureParameters::onUpdateView(bool on)
{
    blockUpdate = !on;
    recomputeFeature();
}

void TaskFeatureParameters::recomputeFeature()
{
    if (!blockUpdate) {
        auto* feature = getObject<PartDesign::Feature>();
        assert(feature);

        feature->recomputeFeature();
        feature->recomputePreview();
        // In Final, the features after it follow (ops#127)
        ViewProviderBody::recomputeEditTail(feature);
    }
}

/*********************************************************************
 *                      The Result box (ops#325)                     *
 *********************************************************************/

namespace
{
// A New part move an open dialog made: what Add to moves back
struct NewPartMove
{
    App::DocumentObjectT feature;
    App::DocumentObjectT from;  // the Body it was in
    App::DocumentObjectT part;  // the new Body
    App::DocumentObjectT sketch;  // its profile, when that moved too
    App::DocumentObjectT sketchAfter;  // the member before the sketch in `from`, if any
};
// One per feature: each document can have its dialog open (PR 303 round 1)
std::vector<NewPartMove> newPartMoves;
// The edit restarts: the box that goes keeps the move for the box that comes
bool restartingEdit = false;

NewPartMove* findMove(const App::DocumentObject* feature)
{
    if (!feature) {
        return nullptr;
    }
    auto it = std::ranges::find_if(newPartMoves, [feature](const NewPartMove& move) {
        return move.feature.getObject() == feature;
    });
    return it != newPartMoves.end() ? &*it : nullptr;
}

void forgetMove(const App::DocumentObjectT& featureT)
{
    std::erase_if(newPartMoves, [&featureT](const NewPartMove& move) {
        return move.feature == featureT;
    });
}

bool isMoved(const App::DocumentObject* feature)
{
    return findMove(feature) != nullptr;
}

// A transaction Cancel can abort: opened (a command books one until something is written), or
// pending (PR 303 round 2)
bool hasOpenTransaction(const App::Document* doc)
{
    return doc && (doc->getBookedTransactionID() != 0 || doc->hasPendingTransaction());
}

void restartEdit(const App::DocumentObjectT& featureT, const std::function<void()>& change);

/** FreeCAD-CH (ops#640, hands-on R1, R1b; round 2 of the regeneration plan): an open feature
 * dialog has its own undo history, as in Onshape. Ctrl+Z (Std_Undo) with a dialog open steps
 * back through the dialog's edits, the newest first (a depth, a selection, an option), and
 * never past the dialog's start; Ctrl+Y redoes them; the Undo arrow lights once the dialog has
 * an edit. OK still commits the whole dialog as one step, Cancel still reverts everything:
 * the history only moves values inside the dialog's own transaction (the step lock, regen-design
 * section 3), and opens none.
 *
 * - An edit is what the dialog's step changes in an input property of the document's objects
 *   while the step lock holds (not a shape, an output, Visibility, or a change made by a
 *   recompute, an undo or an abort). Its value before the edit is kept (Property::Copy()).
 * - The edits of one event, or of one field being typed in, are one step: a step closes when
 *   the event ends; a step made by typing in a text field of the dialog (the focus there, keys
 *   pressed since the last edit) closes when the field finishes, the focus moves or an edit
 *   comes without typing (each keystroke of "15" is no step of its own; a pick while the field
 *   still has the focus is). A step that ended with its values back where they were is dropped.
 * - Undo writes the kept values back (Property::Paste(), in the dialog's transaction, which
 *   recorded the originals already), recomputes the feature, and restarts the edit after the
 *   event (restartEdit), so that the panels read the values again: they read them when they are
 *   built. Redo writes the undone values back.
 * - A new or deleted object, and a restart other than the history's own (a New part move),
 *   clear the history: their changes aren't values it can write back.
 * - The history is the document's (one dialog per document), kept across the history's own
 *   restart by the dialog's transaction id, and ends with the dialog's OK or Cancel.
 * The core reaches it through two actions among the dialog's children ("FreeCAD-CH dialog
 * undo" and "... redo", Gui::Document::undo()), so no core header names it. */
class DialogHistory
{
public:
    struct Change
    {
        std::string object;
        std::string property;
        std::unique_ptr<App::Property> value;  // the value the other way: before, or undone
    };
    struct Step
    {
        std::string name;
        std::vector<Change> changes;
    };

    DialogHistory(std::string docName, std::string feature)
        : docName(std::move(docName))
        , feature(std::move(feature))
    {}

    std::string docName;
    std::string feature;
    int step = 0;  // the dialog's transaction, from its first edit
    std::vector<Step> undos;
    std::vector<Step> redos;
    bool open = false;  // the newest step takes more edits
    bool typingStep = false;  // ...as a text field of the dialog is typed in (typingWidget)
    bool turnOpen = false;  // an edit was recorded in the event being handled
    unsigned lastKeys = 0;  // keyPresses() at the last edit
    QPointer<QWidget> typingWidget;
    bool restoring = false;
    bool restartPending = false;
    QPointer<Gui::TaskView::TaskDialog> dialog;
    QPointer<QAction> undoAction;
    QPointer<QAction> redoAction;
    QMetaObject::Connection typingDone;
    std::vector<fastsignals::scoped_connection> connections;

    App::Document* document() const
    {
        return App::GetApplication().getDocument(docName.c_str());
    }

    void record(const App::DocumentObject& obj, const App::Property& prop);
    void seal();
    void clear();
    bool undo();
    bool redo();
    void updateActions();

private:
    void swap(Step& step, bool backwards);
    void refresh();
    bool watches() const;
};

std::map<std::string, std::unique_ptr<DialogHistory>> dialogHistories;

// Counts the application's key presses: an edit made while a field is typed in joins the field's
// step (DialogHistory::record)
class KeyPressCounter: public QObject
{
public:
    unsigned count = 0;
    bool eventFilter(QObject* watched, QEvent* event) override
    {
        if (event->type() == QEvent::KeyPress) {
            ++count;
        }
        return QObject::eventFilter(watched, event);
    }
};

unsigned keyPresses()
{
    static QPointer<KeyPressCounter> counter;
    if (!counter && qApp) {
        counter = new KeyPressCounter();
        counter->setParent(qApp);
        qApp->installEventFilter(counter);
    }
    return counter ? counter->count : 0;
}
// restartEdit is the history's own (the history stays)
bool historyRestart = false;

DialogHistory* findHistory(const std::string& docName)
{
    auto it = dialogHistories.find(docName);
    return it != dialogHistories.end() ? it->second.get() : nullptr;
}

// The open dialog's transaction: pending, or booked until its first change
int currentStep(const App::Document* doc)
{
    return doc->hasPendingTransaction() ? doc->getTransactionID(true, 0)
                                        : doc->getBookedTransactionID();
}

// An input the dialog's history writes back: as App's no-op rule (Transactions.cpp isResult),
// and no output at all
bool isDialogInput(const App::Property& prop)
{
    using App::Property;
    if (prop.testStatus(Property::NoModify) || prop.testStatus(Property::Transient)
        || prop.testStatus(Property::PropTransient) || prop.testStatus(Property::Output)
        || prop.testStatus(Property::PropOutput)) {
        return false;
    }
    static const Base::Type partShape = Base::Type::fromName("Part::PropertyPartShape");
    return partShape.isBad() || !prop.getTypeId().isDerivedFrom(partShape);
}

bool DialogHistory::watches() const
{
    App::Document* doc = document();
    return doc && dialog && undoAction && !restoring && doc->isStepLocked() && !doc->isPerformingTransaction()
        && !doc->testStatus(App::Document::Recomputing);
}

void DialogHistory::record(const App::DocumentObject& obj, const App::Property& prop)
{
    if (!watches() || obj.isRecomputing() || !isDialogInput(prop)) {
        return;
    }
    App::Document* doc = document();
    const int now = currentStep(doc);
    if (now == 0 || (step != 0 && now != step)) {
        return;  // not the dialog's transaction
    }
    const char* objName = obj.getNameInDocument();
    const char* propName = prop.getName();
    if (!objName || !propName || prop.getContainer() != &obj) {
        return;
    }
    step = now;
    // A text field of the dialog with the focus, typed in since the last edit: the field's typing
    QWidget* focus = QApplication::focusWidget();
    bool inDialog = false;
    if (focus && dialog) {
        for (QWidget* box : dialog->getDialogContent()) {
            if (box && box->isAncestorOf(focus)) {
                inDialog = true;
            }
        }
    }
    const bool textField = qobject_cast<QAbstractSpinBox*>(focus) || qobject_cast<QLineEdit*>(focus);
    const unsigned keys = keyPresses();
    const bool typingNow = inDialog && textField && keys != lastKeys;
    lastKeys = keys;
    // The same event's edits, and the same field's typing, are one step
    const bool joins = open && (turnOpen || (typingStep && typingNow && focus == typingWidget));
    const std::string name = docName;
    if (!joins) {
        seal();
        undos.push_back(Step {.name = propName, .changes = {}});
        redos.clear();
        open = true;
        typingStep = typingNow;
        typingWidget = typingNow ? focus : nullptr;
        auto sealIt = [name]() {
            if (DialogHistory* history = findHistory(name)) {
                history->seal();
            }
        };
        if (auto spin = qobject_cast<QAbstractSpinBox*>(focus); spin && typingNow) {
            typingDone = QObject::connect(spin, &QAbstractSpinBox::editingFinished, undoAction, sealIt);
        }
        else if (auto line = qobject_cast<QLineEdit*>(focus); line && typingNow) {
            typingDone = QObject::connect(line, &QLineEdit::editingFinished, undoAction, sealIt);
        }
    }
    if (!turnOpen) {
        // The event ends: a step that isn't a field's typing closes with it
        turnOpen = true;
        QTimer::singleShot(0, undoAction, [name]() {
            if (DialogHistory* history = findHistory(name)) {
                history->turnOpen = false;
                if (!history->typingStep) {
                    history->seal();
                }
            }
        });
    }
    auto& changes = undos.back().changes;
    const bool known = std::ranges::any_of(changes, [&](const Change& change) {
        return change.object == objName && change.property == propName;
    });
    if (!known) {
        try {
            std::unique_ptr<App::Property> before(prop.Copy());
            if (before) {
                changes.push_back(
                    Change {.object = objName, .property = propName, .value = std::move(before)}
                );
            }
        }
        catch (...) {
        }
    }
    updateActions();
}

void DialogHistory::seal()
{
    if (!open) {
        return;
    }
    open = false;
    typingStep = false;
    typingWidget = nullptr;
    QObject::disconnect(typingDone);
    // The values typed back to what they were are no edit
    App::Document* doc = document();
    auto& changes = undos.back().changes;
    std::erase_if(changes, [doc](const Change& change) {
        App::DocumentObject* obj = doc ? doc->getObject(change.object.c_str()) : nullptr;
        App::Property* live = obj ? obj->getPropertyByName(change.property.c_str()) : nullptr;
        if (!live || live->isDerivedFrom<App::PropertyLinkBase>()) {
            return false;
        }
        try {
            std::unique_ptr<App::Property> now(live->Copy());
            return now && now->getTypeId() == change.value->getTypeId()
                && now->isSame(*change.value);
        }
        catch (...) {
            return false;
        }
    });
    if (changes.empty()) {
        undos.pop_back();
    }
    updateActions();
}

void DialogHistory::clear()
{
    if (open) {
        open = false;
        typingStep = false;
        typingWidget = nullptr;
        QObject::disconnect(typingDone);
    }
    undos.clear();
    redos.clear();
    updateActions();
}

void DialogHistory::swap(Step& step, bool backwards)
{
    App::Document* doc = document();
    if (!doc) {
        return;
    }
    Base::FlagToggler<> flag(restoring);
    auto apply = [doc](Change& change) {
        App::DocumentObject* obj = doc->getObject(change.object.c_str());
        App::Property* live = obj ? obj->getPropertyByName(change.property.c_str()) : nullptr;
        if (!live) {
            return;
        }
        try {
            std::unique_ptr<App::Property> now(live->Copy());
            live->Paste(*change.value);
            change.value = std::move(now);
        }
        catch (const Base::Exception& e) {
            e.reportException();
        }
        catch (...) {
        }
    };
    if (backwards) {
        std::for_each(step.changes.rbegin(), step.changes.rend(), apply);
    }
    else {
        std::ranges::for_each(step.changes, apply);
    }
}

bool DialogHistory::undo()
{
    seal();
    if (undos.empty() || !watches()) {
        return false;
    }
    Step last = std::move(undos.back());
    undos.pop_back();
    swap(last, true);
    redos.push_back(std::move(last));
    refresh();
    return true;
}

bool DialogHistory::redo()
{
    seal();
    if (redos.empty() || !watches()) {
        return false;
    }
    Step last = std::move(redos.back());
    redos.pop_back();
    swap(last, false);
    undos.push_back(std::move(last));
    refresh();
    return true;
}

void DialogHistory::refresh()
{
    updateActions();
    App::Document* doc = document();
    auto feat = doc ? freecad_cast<PartDesign::Feature*>(doc->getObject(feature.c_str())) : nullptr;
    if (!feat) {
        return;
    }
    // The preview at once, as a field's change does (TaskFeatureParameters::recomputeFeature)
    try {
        feat->recomputeFeature();
        feat->recomputePreview();
        ViewProviderBody::recomputeEditTail(feat);
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
    // The panels after the event: the action that runs this belongs to the dialog
    if (restartPending) {
        return;
    }
    restartPending = true;
    App::DocumentObjectT featureT(feat);
    const std::string name = docName;
    QTimer::singleShot(0, qApp, [name, featureT]() {
        DialogHistory* history = findHistory(name);
        if (!history) {
            return;
        }
        history->restartPending = false;
        App::Document* doc = featureT.getDocument();
        Gui::Document* guiDoc = doc ? Gui::Application::Instance->getDocument(doc) : nullptr;
        auto vp = guiDoc
            ? freecad_cast<Gui::ViewProviderDocumentObject*>(guiDoc->getEditViewProvider())
            : nullptr;
        if (!vp || vp->getObject() != featureT.getObject() || !doc->isStepLocked()
            || !Gui::Control().activeDialog(doc)) {
            return;
        }
        Base::FlagToggler<> own(historyRestart);
        restartEdit(featureT, []() {});
    });
}

void DialogHistory::updateActions()
{
    auto names = [](const std::vector<Step>& steps) {
        QStringList list;
        for (auto it = steps.rbegin(); it != steps.rend(); ++it) {
            list << QString::fromStdString(it->name);
        }
        return list;
    };
    if (undoAction) {
        undoAction->setEnabled(!undos.empty());
        undoAction->setProperty("names", names(undos));
    }
    if (redoAction) {
        redoAction->setEnabled(!redos.empty());
        redoAction->setProperty("names", names(redos));
    }
}

// The dialog of `feature` takes the document's history: the one it had before its own restart
// (the same feature and transaction), else a new one
void attachDialogHistory(Gui::TaskView::TaskDialog* dlg, App::DocumentObject* feature)
{
    App::Document* doc = feature ? feature->getDocument() : nullptr;
    if (!doc || !feature->getNameInDocument()) {
        return;
    }
    const std::string name = doc->getName();
    auto& history = dialogHistories[name];
    if (!history || history->feature != feature->getNameInDocument() || history->step == 0
        || history->step != currentStep(doc)) {
        history = std::make_unique<DialogHistory>(name, feature->getNameInDocument());
    }
    history->open = false;
    history->typingStep = false;
    history->turnOpen = false;
    history->lastKeys = keyPresses();
    history->dialog = dlg;
    history->undoAction = new QAction(dlg);
    history->undoAction->setObjectName(QStringLiteral("FreeCAD-CH dialog undo"));
    history->redoAction = new QAction(dlg);
    history->redoAction->setObjectName(QStringLiteral("FreeCAD-CH dialog redo"));
    QObject::connect(history->undoAction, &QAction::triggered, [name]() {
        if (DialogHistory* found = findHistory(name)) {
            found->undo();
        }
    });
    QObject::connect(history->redoAction, &QAction::triggered, [name]() {
        if (DialogHistory* found = findHistory(name)) {
            found->redo();
        }
    });
    // A step closes when the focus moves (the typed field's edit is done)
    QObject::connect(qApp, &QApplication::focusChanged, history->undoAction, [name]() {
        if (DialogHistory* found = findHistory(name)) {
            found->seal();
        }
    });
    history->connections.clear();
    history->connections.emplace_back(doc->signalBeforeChangeObject.connect(
        [name](const App::DocumentObject& obj, const App::Property& prop) {
            if (DialogHistory* found = findHistory(name)) {
                found->record(obj, prop);
            }
        }
    ));
    auto structural = [name](const App::DocumentObject&) {
        DialogHistory* found = findHistory(name);
        App::Document* doc = found ? found->document() : nullptr;
        if (found && found->dialog && doc && doc->isStepLocked() && !doc->isPerformingTransaction()) {
            found->clear();
        }
    };
    history->connections.emplace_back(doc->signalNewObject.connect(structural));
    history->connections.emplace_back(doc->signalDeletedObject.connect(structural));
    history->updateActions();
}

// The dialog goes: its history stops listening (a restart's next dialog takes it again)
void detachDialogHistory(const Gui::TaskView::TaskDialog* dlg)
{
    for (auto& [name, history] : dialogHistories) {
        (void)name;
        if (history && history->dialog == dlg) {
            history->connections.clear();
            if (history->open) {
                history->seal();
            }
            history->dialog = nullptr;
        }
    }
}

// The dialog's OK or Cancel: its history ends
void endDialogHistory(const App::Document* doc)
{
    if (doc) {
        dialogHistories.erase(doc->getName());
    }
}

// Other parts in the Body's studio: Bodies of one container placed alike (ops#325)
bool hasStudioSiblings(const PartDesign::Body* body)
{
    for (auto obj : body->getDocument()->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        if (obj != body
            && Part::BodyBase::areStudioSiblings(body, static_cast<PartDesign::Body*>(obj))) {
            return true;
        }
    }
    return false;
}

// Why New part isn't offered for an additive feature; empty when it is. newPartFrom's rule (a
// feature that something uses would reroute the next solid, the design's critic, point 9), and a
// transaction that Cancel aborts
QString newPartRefusal(PartDesign::FeatureAddSub* feature)
{
    auto body = PartDesign::Body::findBodyOf(feature);
    if (!body) {
        return QObject::tr("New part needs a feature in a body");
    }
    if (!hasOpenTransaction(feature->getDocument())) {
        return QObject::tr("New part needs a dialog that Cancel can undo");
    }
    bool used = std::ranges::any_of(feature->getInList(), [body](App::DocumentObject* user) {
        return user != body;
    });
    if (body->Tip.getValue() != feature || used) {
        return QObject::tr(
            "Only the feature being created, or a tip that nothing uses, can go to a new part"
        );
    }
    return {};
}

// Ends the edit of the feature, runs `change`, and edits the feature again in its Body, all in
// the dialog's transaction: resetEdit commits that transaction, which Cancel must still abort,
// so it is locked meanwhile. The Body's path that setEdit stores (Utils.cpp), the edit roll
// points and the viewer's edit state are then the moved feature's (design 2.3)
void restartEdit(const App::DocumentObjectT& featureT, const std::function<void()>& change)
{
    App::Document* doc = featureT.getDocument();
    Gui::Document* guiDoc = doc ? Gui::Application::Instance->getDocument(doc) : nullptr;
    if (!guiDoc) {
        return;
    }
    // FreeCAD-CH (ops#640): a move's restart ends the dialog's history (DialogHistory)
    if (!historyRestart) {
        if (DialogHistory* history = findHistory(doc->getName())) {
            history->clear();
        }
    }
    App::TransactionLocker lock(doc);
    {
        Base::FlagToggler<> restarting(restartingEdit, false);
        guiDoc->resetEdit();
    }
    try {
        change();
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
    if (App::DocumentObject* feature = featureT.getObject()) {
        try {
            PartDesignGui::setEdit(feature, PartDesign::Body::findBodyOf(feature));
        }
        catch (const Base::Exception& e) {
            e.reportException();
        }
    }
    // No panel came back, so no box takes the move over (PR 303 round 2)
    if (!Gui::Control().activeDialog(doc)) {
        forgetMove(featureT);
    }
}

// Shows the Body's Tip when none of its solid features is shown, so the part isn't left empty
// (ViewProvider::unsetEdit's rule, ops#212)
void showTipIfNoneShown(const PartDesign::Body* body)
{
    App::DocumentObject* tip = body->Tip.getValue();
    bool shown = std::ranges::any_of(body->Group.getValues(), [](App::DocumentObject* obj) {
        return obj->isDerivedFrom<PartDesign::Feature>() && obj->Visibility.getValue();
    });
    if (tip && !shown) {
        Gui::cmdAppObjectShow(tip);
    }
}

void moveToNewPart(const App::DocumentObjectT& featureT)
{
    restartEdit(featureT, [&featureT]() {
        App::DocumentObject* feature = featureT.getObject();
        PartDesign::Body* from = PartDesign::Body::findBodyOf(feature);
        if (!from) {
            return;
        }
        App::DocumentObject* sketch = nullptr;
        App::DocumentObject* sketchAfter = nullptr;
        if (auto profileBased = freecad_cast<PartDesign::ProfileBased*>(feature)) {
            sketch = profileBased->Profile.getValue();
            const auto& group = from->Group.getValues();
            auto it = std::ranges::find(group, sketch);
            if (it != group.end() && it != group.begin()) {
                sketchAfter = *(it - 1);
            }
        }
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "PartDesign.newPartFrom(%s)",
            Gui::Command::getObjectCmd(feature).c_str()
        );
        PartDesign::Body* part = PartDesign::Body::findBodyOf(feature);
        if (!part || part == from) {
            return;
        }
        NewPartMove move {
            .feature = featureT,
            .from = App::DocumentObjectT(from),
            .part = App::DocumentObjectT(part),
            .sketch = {},
            .sketchAfter = {},
        };
        if (sketch && part->hasObject(sketch)) {
            move.sketch = sketch;
            move.sketchAfter = sketchAfter;
        }
        forgetMove(featureT);
        newPartMoves.push_back(move);
        // The part it left shows its own result now; OK purges the document's touched objects
        // (accept()), so the part would keep the feature's solid until its next recompute
        from->recomputeFeature(/*recursive=*/true);
        // ...and stays shown, as Onshape's other parts do (ops#630): the command hid its Tip for
        // the feature, which has left. A feature the user shows instead stays the shown one
        showTipIfNoneShown(from);
    });
}

void moveBack(const App::DocumentObjectT& featureT)
{
    restartEdit(featureT, [&featureT]() {
        NewPartMove* found = findMove(featureT.getObject());
        if (!found) {
            return;
        }
        NewPartMove move = *found;
        forgetMove(featureT);
        App::DocumentObject* feature = move.feature.getObject();
        auto from = freecad_cast<PartDesign::Body*>(move.from.getObject());
        auto part = freecad_cast<PartDesign::Body*>(move.part.getObject());
        if (!from || !part || !part->hasObject(feature)) {
            return;
        }
        auto cmd = [](const App::DocumentObject* obj) {
            return Gui::Command::getObjectCmd(obj);
        };
        auto run = [](const std::string& line) {
            Gui::Command::doCommand(Gui::Command::Doc, "%s", line.c_str());
        };
        run(cmd(part) + ".removeObject(" + cmd(feature) + ")");
        App::DocumentObject* sketch = move.sketch.getObject();
        if (sketch && part->hasObject(sketch)) {
            run(cmd(part) + ".removeObject(" + cmd(sketch) + ")");
            // where it was (relinked to this Body's origin on insert)
            App::DocumentObject* after = move.sketchAfter.getObject();
            std::string target = after && from->hasObject(after) ? cmd(after) : "None";
            run(cmd(from) + ".insertObject(" + cmd(sketch) + ", " + target + ", True)");
        }
        run(cmd(from) + ".addObject(" + cmd(feature) + ")");
        // the new Body, empty now, goes with its origin
        if (part->Group.getValues().empty()) {
            run(
                std::string("App.getDocument('") + part->getDocument()->getName()
                + "').removeObject('" + part->getNameInDocument() + "')"
            );
        }
    });
}

// Whether `box` is still in the open dialog of the feature's document, under the dialog's
// transaction
bool isEditing(const QWidget* box, const App::DocumentObjectT& featureT)
{
    App::Document* doc = featureT.getDocument();
    if (!box || !hasOpenTransaction(doc)) {
        return false;
    }
    Gui::TaskView::TaskDialog* dialog = Gui::Control().activeDialog(doc);
    if (!dialog) {
        return false;
    }
    const auto& content = dialog->getDialogContent();
    return std::ranges::find(content, box) != content.end();
}

QString partLabel(const App::DocumentObject* body)
{
    return body ? QString::fromUtf8(body->Label.getValue()) : QString();
}
}  // namespace

TaskResultParameters::TaskResultParameters(PartDesignGui::ViewProvider* vp, QWidget* parent)
    : TaskFeatureParameters(vp, parent, "PartDesign_Body", tr("Result"))
    , combo(nullptr)
    , featureT(vp->getObject())
{
    auto* proxy = new QWidget(this);
    auto* layout = new QHBoxLayout(proxy);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(new QLabel(tr("Result:"), proxy));
    combo = new QComboBox(proxy);
    combo->setObjectName(QStringLiteral("resultCombo"));
    layout->addWidget(combo, 1);
    groupLayout()->addWidget(proxy);

    auto feature = getObject<PartDesign::FeatureAddSub>();
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    if (feature->getAddSubType() == PartDesign::FeatureAddSub::Type::Additive) {
        App::DocumentObject* from = movedFrom(feature);
        combo->addItem(tr("Add to %1").arg(partLabel(from ? from : body)), QStringLiteral("add"));
        combo->addItem(tr("New part"), QStringLiteral("new"));
        if (from) {
            combo->setCurrentIndex(1);
        }
        else if (QString why = newPartRefusal(feature); !why.isEmpty()) {
            if (auto model = qobject_cast<QStandardItemModel*>(combo->model())) {
                model->item(1)->setEnabled(false);
            }
            combo->setItemData(1, why, Qt::ToolTipRole);
        }
        // Merge with (design 2.5): for a feature in its own part, not one moved to a new part
        if (!from && body && hasStudioSiblings(body) && !PartDesign::Boolean::mergeOf(body)) {
            addMergeList();
        }
    }
    else {
        combo->addItem(tr("Remove from %1").arg(partLabel(body)), QStringLiteral("Subtraction"));
        combo->addItem(tr("Intersect with %1").arg(partLabel(body)), QStringLiteral("Common"));
        bool common = feature->getBooleanOperation()
            == PartDesign::FeatureAddSub::BooleanOperation::Common;
        combo->setCurrentIndex(common ? 1 : 0);
        if (App::DocumentObject* primary = primaryOf(feature)) {
            combo->setEnabled(false);  // bound to the primary's
            addFollowsNote(primary);
        }
        else if (feature->isDerivedFrom<PartDesign::ProfileBased>() && body
                 && hasStudioSiblings(body)) {
            addPartsList();
        }
    }
    connect(
        combo,
        qOverload<int>(&QComboBox::currentIndexChanged),
        this,
        &TaskResultParameters::onResultChanged
    );
}

TaskResultParameters::~TaskResultParameters()
{
    // OK, Cancel or another close: the move is final, or aborted with the transaction
    if (!restartingEdit) {
        forgetMove(featureT);
    }
}

bool TaskResultParameters::hasRows(App::DocumentObject* feature)
{
    auto addSub = freecad_cast<PartDesign::FeatureAddSub*>(feature);
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    if (!addSub || !body) {
        return false;
    }
    if (isMoved(feature) || hasStudioSiblings(body)) {
        return true;
    }
    // Outside a studio only New part is offered (design 2.3), and an intersection is shown
    if (addSub->getAddSubType() == PartDesign::FeatureAddSub::Type::Additive) {
        return newPartRefusal(addSub).isEmpty();
    }
    return addSub->getBooleanOperation() == PartDesign::FeatureAddSub::BooleanOperation::Common;
}

App::DocumentObject* TaskResultParameters::primaryOf(App::DocumentObject* feature)
{
    auto addSub = freecad_cast<PartDesign::FeatureAddSub*>(feature);
    return addSub ? addSub->SiblingOf.getValue() : nullptr;
}

struct TaskResultParameters::TouchCache
{
    struct Entry
    {
        TopoDS_Shape tool;  // held, so a freed shape's address can't stand for another
        TopoDS_Shape part;
        bool touches;
    };
    std::deque<Entry> entries;
};

namespace
{
// Whether the feature's tool touches the part, both placed globally (design 2.3)
bool toolTouches(
    PartDesign::FeatureAddSub* feature,
    PartDesign::Body* part,
    TaskResultParameters::TouchCache& cache
)
{
    Part::TopoShape tool = feature->AddSubShape.getShape();
    Part::TopoShape shape = part->Shape.getShape();
    if (tool.isNull() || shape.isNull()) {
        return false;
    }
    tool.setPlacement(feature->globalPlacement());
    shape.setPlacement(part->globalPlacement());
    // IsEqual: the same TShape at the same place
    for (const auto& entry : cache.entries) {
        if (entry.tool.IsEqual(tool.getShape()) && entry.part.IsEqual(shape.getShape())) {
            return entry.touches;
        }
    }
    bool touches = PartDesign::FeatureAddSub::shapesTouch(tool.getShape(), shape.getShape());
    cache.entries.push_back({tool.getShape(), shape.getShape(), touches});
    if (cache.entries.size() > 32) {
        cache.entries.pop_front();
    }
    return touches;
}

QString touchText(const PartDesign::Body* part, bool touches)
{
    return touches ? partLabel(part)
                   : QObject::tr("%1 (doesn't touch)").arg(partLabel(part));
}
}  // namespace

void TaskResultParameters::addPartsList()
{
    auto feature = getObject<PartDesign::FeatureAddSub>();
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    touchCache = std::make_shared<TouchCache>();
    std::map<App::DocumentObject*, PartDesign::FeatureAddSub*> siblings;
    for (PartDesign::FeatureAddSub* sibling : feature->getSiblings()) {
        siblings[PartDesign::Body::findBodyOf(sibling)] = sibling;
    }
    // The studio's other parts, those the tool touches first (design 2.3)
    std::vector<std::pair<PartDesign::Body*, bool>> others;
    for (auto obj : feature->getDocument()->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        auto other = static_cast<PartDesign::Body*>(obj);
        if (other != body && Part::BodyBase::areStudioSiblings(body, other)) {
            others.emplace_back(other, toolTouches(feature, other, *touchCache));
        }
    }
    std::ranges::stable_partition(others, [](const auto& other) { return other.second; });

    groupLayout()->addWidget(new QLabel(tr("Parts:"), this));
    parts = new QListWidget(this);
    parts->setObjectName(QStringLiteral("partsList"));
    // its own part, always cut
    auto own = new QListWidgetItem(partLabel(body), parts);
    own->setFlags(Qt::ItemIsUserCheckable);
    own->setCheckState(Qt::Checked);
    own->setToolTip(tr("The part this feature is in"));
    for (const auto& [other, touches] : others) {
        auto item = new QListWidgetItem(touchText(other, touches), parts);
        item->setData(Qt::UserRole, QString::fromLatin1(other->getNameInDocument()));
        Qt::ItemFlags flags = Qt::ItemIsUserCheckable | Qt::ItemIsEnabled;
        auto found = siblings.find(other);
        PartDesign::FeatureAddSub* sibling = found != siblings.end() ? found->second : nullptr;
        item->setCheckState(sibling ? Qt::Checked : Qt::Unchecked);
        if (sibling) {
            if (App::DocumentObject* user = PartDesign::FeatureAddSub::siblingUser(sibling)) {
                flags &= ~Qt::ItemIsEnabled;
                item->setToolTip(tr("Its cut %1 is used by %2")
                                     .arg(partLabel(sibling), partLabel(user)));
            }
        }
        else if (other->isRolledBack()) {
            // a sibling would land mid-history (the design's critic, point 10)
            flags &= ~Qt::ItemIsEnabled;
            item->setToolTip(tr("Roll %1 to the end first").arg(partLabel(other)));
        }
        item->setFlags(flags);
    }
    groupLayout()->addWidget(parts);

    touchTimer = new QTimer(this);
    touchTimer->setSingleShot(true);
    touchTimer->setInterval(300);
    connect(touchTimer, &QTimer::timeout, this, &TaskResultParameters::updateTouches);
}

void TaskResultParameters::addMergeList()
{
    auto feature = getObject<PartDesign::FeatureAddSub>();
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    touchCache = std::make_shared<TouchCache>();
    // The studio's other parts, those the tool touches first; a part merged already isn't one
    std::vector<std::pair<PartDesign::Body*, bool>> others;
    for (auto obj : feature->getDocument()->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        auto other = static_cast<PartDesign::Body*>(obj);
        if (other != body && Part::BodyBase::areStudioSiblings(body, other)
            && !PartDesign::Boolean::mergeOf(other)) {
            others.emplace_back(other, toolTouches(feature, other, *touchCache));
        }
    }
    if (others.empty()) {
        return;
    }
    std::ranges::stable_partition(others, [](const auto& other) { return other.second; });

    groupLayout()->addWidget(new QLabel(tr("Merge with:"), this));
    mergeParts = new QListWidget(this);
    mergeParts->setObjectName(QStringLiteral("mergeList"));
    for (const auto& [other, touches] : others) {
        auto item = new QListWidgetItem(touchText(other, touches), mergeParts);
        item->setData(Qt::UserRole, QString::fromLatin1(other->getNameInDocument()));
        item->setData(Qt::UserRole + 1, touches);
        item->setCheckState(Qt::Unchecked);  // two overlapping parts by default (decision 59)
        Qt::ItemFlags flags = Qt::ItemIsUserCheckable | Qt::ItemIsEnabled;
        if (other->isRolledBack()) {
            flags &= ~Qt::ItemIsEnabled;  // a held feature would merge a frozen shape (2.6)
            item->setToolTip(tr("Roll %1 to the end first").arg(partLabel(other)));
        }
        item->setFlags(flags);
    }
    groupLayout()->addWidget(mergeParts);
    mergeNote = new QLabel(this);
    mergeNote->setObjectName(QStringLiteral("mergeNote"));
    mergeNote->setWordWrap(true);
    groupLayout()->addWidget(mergeNote);
    mergeBanner = new QLabel(this);
    mergeBanner->setObjectName(QStringLiteral("mergeBanner"));
    mergeBanner->setWordWrap(true);
    // The look of the task view's warning banner (Gui/TaskView/TaskView.cpp)
    mergeBanner->setStyleSheet(QStringLiteral(
        "QLabel#mergeBanner { background-color: rgba(230, 160, 0, 45);"
        " border: 1px solid rgba(200, 140, 0, 170); border-radius: 3px; padding: 2px; }"
    ));
    groupLayout()->addWidget(mergeBanner);
    connect(mergeParts, &QListWidget::itemChanged, this, [this]() { updateMergeNotes(); });
    updateMergeNotes();

    if (!touchTimer) {
        touchTimer = new QTimer(this);
        touchTimer->setSingleShot(true);
        touchTimer->setInterval(300);
        connect(touchTimer, &QTimer::timeout, this, &TaskResultParameters::updateTouches);
    }
}

void TaskResultParameters::updateMergeNotes()
{
    if (!mergeParts) {
        return;
    }
    QStringList ticked;
    QStringList touching;
    for (int i = 0; i < mergeParts->count(); ++i) {
        QListWidgetItem* item = mergeParts->item(i);
        App::DocumentObject* other =
            getObject()->getDocument()->getObject(item->data(Qt::UserRole).toString().toLatin1());
        if (!other) {
            continue;
        }
        if (item->checkState() == Qt::Checked) {
            ticked << partLabel(other);
        }
        else if (item->data(Qt::UserRole + 1).toBool()) {
            touching << partLabel(other);
        }
    }
    const QString comma = QStringLiteral(", ");
    // Overlapping parts are a normal state while modelling: a plain line, no warning (2.5)
    mergeNote->setText(
        touching.isEmpty() ? QString() : tr("Touches %1 (not merged)").arg(touching.join(comma))
    );
    mergeNote->setVisible(!touching.isEmpty());
    const QString into = partLabel(PartDesign::Body::findBodyOf(getObject()));
    if (ticked.size() == 1) {
        mergeBanner->setText(
            tr("Merges %1 into %2. %1 stops being a separate part: it is hidden, its shape "
               "becomes part of %2, and features added to %1 after this point fail.")
                .arg(ticked.front(), into)
        );
    }
    else if (!ticked.isEmpty()) {
        mergeBanner->setText(
            tr("Merges %1 into %2. They stop being separate parts: they are hidden, their shapes "
               "become part of %2, and features added to them after this point fail.")
                .arg(ticked.join(comma), into)
        );
    }
    mergeBanner->setVisible(!ticked.isEmpty());
}

void TaskResultParameters::updateTouches()
{
    auto feature = freecad_cast<PartDesign::FeatureAddSub*>(featureT.getObject());
    if (!feature) {
        return;
    }
    for (QListWidget* list : {parts, mergeParts}) {
        // the parts list's first row is the feature's own part
        for (int i = list == parts ? 1 : 0; list && i < list->count(); ++i) {
            QListWidgetItem* item = list->item(i);
            auto other = freecad_cast<PartDesign::Body*>(
                feature->getDocument()->getObject(item->data(Qt::UserRole).toString().toLatin1())
            );
            if (other) {
                const bool touches = toolTouches(feature, other, *touchCache);
                QSignalBlocker block(list);
                item->setText(touchText(other, touches));
                item->setData(Qt::UserRole + 1, touches);
            }
        }
    }
    updateMergeNotes();
}

void TaskResultParameters::slotChangedObject(
    const Gui::ViewProviderDocumentObject& Obj,
    const App::Property& Prop
)
{
    auto feature = freecad_cast<PartDesign::FeatureAddSub*>(featureT.getObject());
    if (touchTimer && feature && Obj.getObject() == feature && &Prop == &feature->AddSubShape) {
        touchTimer->start();  // debounced: once the preview settles
    }
}

void TaskResultParameters::addFollowsNote(App::DocumentObject* primary)
{
    auto* row = new QWidget(this);
    auto* layout = new QHBoxLayout(row);
    layout->setContentsMargins(0, 0, 0, 0);
    auto* note =
        new QLabel(tr("Follows %1: edit it there, or Unlink").arg(partLabel(primary)), row);
    note->setObjectName(QStringLiteral("followsNote"));
    note->setWordWrap(true);
    layout->addWidget(note, 1);
    auto* unlink = new QPushButton(tr("Unlink"), row);
    unlink->setObjectName(QStringLiteral("unlinkButton"));
    unlink->setToolTip(tr("Make this cut independent of %1").arg(partLabel(primary)));
    layout->addWidget(unlink);
    groupLayout()->addWidget(row);
    connect(unlink, &QPushButton::clicked, this, &TaskResultParameters::onUnlink);
}

void TaskResultParameters::onUnlink()
{
    if (auto button = qobject_cast<QPushButton*>(sender())) {
        button->setEnabled(false);
    }
    // The edit restarts, so the other boxes are editable again: after the signal, as a move
    App::DocumentObjectT target = featureT;
    QPointer<TaskResultParameters> box(this);
    QTimer::singleShot(0, qApp, [box, target]() {
        if (!isEditing(box.data(), target)) {
            return;
        }
        restartEdit(target, [&target]() {
            Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.unlinkSibling(%s)",
                Gui::Command::getObjectCmd(target.getObject()).c_str()
            );
        });
    });
}

App::DocumentObject* TaskResultParameters::movedFrom(const App::DocumentObject* feature)
{
    NewPartMove* move = findMove(feature);
    return move ? move->from.getObject() : nullptr;
}

void TaskResultParameters::onResultChanged(int index)
{
    auto feature = getObject<PartDesign::FeatureAddSub>();
    if (!feature) {
        return;
    }
    const QString what = combo->itemData(index).toString();
    if (feature->getAddSubType() == PartDesign::FeatureAddSub::Type::Subtractive) {
        feature->Operation.setValue(what.toLatin1().constData());
        recomputeFeature();
        return;
    }
    const bool toNewPart = what == QStringLiteral("new");
    if (toNewPart == isMoved(feature)) {
        return;
    }
    // The edit restarts, which closes this dialog: after the signal, from the event loop
    combo->setEnabled(false);
    App::DocumentObjectT target(feature);
    QPointer<TaskResultParameters> box(this);
    QTimer::singleShot(0, qApp, [box, target, toNewPart]() {
        // OK or Cancel came first: the dialog's transaction is closed, and a move now would be
        // outside any undo step (PR 303 round 1). A box still there shows what is
        if (!isEditing(box.data(), target)) {
            if (box) {
                QSignalBlocker block(box->combo);
                box->combo->setCurrentIndex(toNewPart ? 0 : 1);
                box->combo->setEnabled(true);
            }
            return;
        }
        if (toNewPart) {
            moveToNewPart(target);
        }
        else {
            moveBack(target);
        }
    });
}

void TaskResultParameters::apply()
{
    auto feature = getObject<PartDesign::FeatureAddSub>();
    // New part is done (PartDesign.newPartFrom, in the macro too); a sibling's Operation is bound
    if (feature && feature->getAddSubType() == PartDesign::FeatureAddSub::Type::Subtractive
        && !primaryOf(feature)) {
        FCMD_OBJ_CMD(feature, "Operation = '" << feature->Operation.getValueAsString() << "'");
    }
    // The ticked parts merged into this one, right after the feature (design 2.5). A part merged
    // already (an OK that failed, tried again) is left out
    if (feature && mergeParts) {
        App::Document* doc = feature->getDocument();
        std::string ticked;
        for (int i = 0; i < mergeParts->count(); ++i) {
            QListWidgetItem* item = mergeParts->item(i);
            App::DocumentObject* other =
                doc->getObject(item->data(Qt::UserRole).toString().toLatin1());
            if (other && item->checkState() == Qt::Checked
                && !PartDesign::Boolean::mergeOf(other)) {
                ticked += (ticked.empty() ? "" : ", ") + Gui::Command::getObjectCmd(other);
            }
        }
        if (!ticked.empty()) {
            Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.makeMerge(%s, [%s])",
                Gui::Command::getObjectCmd(feature).c_str(),
                ticked.c_str()
            );
            // The Merge computes now: OK purges the document's touched objects (accept())
            Gui::cmdAppDocument(feature, "recompute()");
        }
    }
    if (!feature || !parts) {
        return;
    }
    // The ticked parts' siblings; with none before and none ticked, nothing to do. Otherwise
    // every sibling copies the links again (design 2.4)
    App::Document* doc = feature->getDocument();
    std::string ticked;
    for (int i = 1; i < parts->count(); ++i) {
        QListWidgetItem* item = parts->item(i);
        App::DocumentObject* other = doc->getObject(item->data(Qt::UserRole).toString().toLatin1());
        if (other && item->checkState() == Qt::Checked) {
            ticked += (ticked.empty() ? "" : ", ") + Gui::Command::getObjectCmd(other);
        }
    }
    if (ticked.empty() && feature->getSiblings().empty()) {
        return;
    }
    Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
    Gui::Command::doCommand(
        Gui::Command::Doc,
        "PartDesign.makeSiblings(%s, [%s])",
        Gui::Command::getObjectCmd(feature).c_str(),
        ticked.c_str()
    );
    // The siblings compute now: OK purges the document's touched objects (accept())
    Gui::cmdAppDocument(feature, "recompute()");
}

/*********************************************************************
 *                            Task Dialog                            *
 *********************************************************************/
TaskDlgFeatureParameters::TaskDlgFeatureParameters(PartDesignGui::ViewProvider* vp)
    : preview(new TaskPreviewParameters(vp))
    , fieldGroup(new ReferenceFieldGroup(this))
    , vp(vp)
{
    assert(vp);
    // The feature's references that need the user, at the top of its dialog (ops#127). The
    // subclasses add their panels after this one.
    App::DocumentObject* feature = vp->getObject();
    if (TaskReferences::hasRows(feature)) {
        references = new TaskReferences(feature);
        Content.push_back(references);
        connect(references, &TaskReferences::referencesChanged, this, [this]() {
            referencesRepaired();
        });
        connect(references, &TaskReferences::selectionTaken, this, [this]() {
            referenceSelectionTaken();
        });
    }
    // FreeCAD-CH (ops#640, hands-on R1): the dialog's own undo history
    attachDialogHistory(this, feature);
}

TaskDlgFeatureParameters::~TaskDlgFeatureParameters()
{
    detachDialogHistory(this);
}

void TaskDlgFeatureParameters::open()
{
    TaskDialog::open();
    for (ReferenceField* field : panelFields()) {
        fieldGroup->addField(field);
    }
    fieldGroup->setPanels(Content);
    // What the fields show stays in the fields; the panel shows only while something is left
    // (3.5, Q3), and the rows of a field that is disabled come back to it
    if (references) {
        references->setHideWhenEmpty(true);
        references->setCoveredProperties(fieldGroup->properties());
        connect(fieldGroup, &ReferenceFieldGroup::propertiesChanged, references, [this]() {
            references->setCoveredProperties(fieldGroup->properties());
        });
    }
    fieldGroup->armFirstEmpty();
    // A sibling follows its primary: only the Result box, with Unlink, is editable (ops#325)
    if (TaskResultParameters::primaryOf(getObject())) {
        forEachParameters([](TaskFeatureParameters* param) {
            if (!qobject_cast<TaskResultParameters*>(param)) {
                param->setEnabled(false);
            }
        });
    }
}

std::vector<ReferenceField*> TaskDlgFeatureParameters::panelFields()
{
    std::vector<ReferenceField*> fields;
    forEachParameters([&fields](TaskFeatureParameters* param) {
        for (ReferenceField* field : param->referenceFields()) {
            fields.push_back(field);
        }
    });
    return fields;
}

void TaskDlgFeatureParameters::addResultBox()
{
    if (TaskResultParameters::hasRows(getObject())) {
        Content.push_back(new TaskResultParameters(vp));
    }
}

void TaskDlgFeatureParameters::referencesRepaired()
{
    forEachParameters([](TaskFeatureParameters* param) { param->onReferencesRepaired(); });
}

void TaskDlgFeatureParameters::referenceSelectionTaken()
{
    fieldGroup->disarm();
    forEachParameters([](TaskFeatureParameters* param) { param->onReferenceSelectionTaken(); });
}

void TaskDlgFeatureParameters::forEachParameters(const std::function<void(TaskFeatureParameters*)>& fn)
{
    for (QWidget* wgt : Content) {
        if (auto param = qobject_cast<TaskFeatureParameters*>(wgt)) {
            fn(param);
        }
    }
}

bool TaskDlgFeatureParameters::accept()
{
    App::DocumentObject* feature = getObject();
    bool isUpdateBlocked = false;
    fieldGroup->disarm();
    if (references) {
        references->stopPick();
    }
    try {
        // Iterate over parameter dialogs and apply all parameters from them
        for (QWidget* wgt : Content) {
            TaskFeatureParameters* param = qobject_cast<TaskFeatureParameters*>(wgt);
            if (!param) {
                continue;
            }

            param->saveHistory();
            param->apply();
            isUpdateBlocked |= param->isUpdateBlocked();
        }
        // Make sure the feature is what we are expecting
        // Should be fine but you never know...
        if (!feature->isDerivedFrom<PartDesign::Feature>()) {
            throw Base::TypeError("Bad object processed in the feature dialog.");
        }

        if (isUpdateBlocked) {
            Gui::cmdAppDocument(feature, "recompute()");
        }
        else {
            // object was already computed, nothing more to do with it...
            Gui::cmdAppDocument(feature, "purgeTouched()");

            if (!feature->isValid()) {
                throw Base::RuntimeError(getObject()->getStatusString());
            }

            // ...but touch parents to signal the change...
            for (auto obj : feature->getInList()) {
                obj->touch();
            }
            // ...and recompute them
            Gui::cmdAppDocument(feature->getDocument(), "recompute()");
        }

        if (!feature->isValid()) {
            throw Base::RuntimeError(getObject()->getStatusString());
        }

        App::DocumentObject* previous = static_cast<PartDesign::Feature*>(feature)->getBaseObject(
            /* silent = */ true
        );
        Gui::cmdAppObjectHide(previous);

        // detach the task panel from the selection to avoid to invoke
        // eventually onAddSelection when the selection changes
        std::vector<QWidget*> subwidgets = getDialogContent();
        for (auto it : subwidgets) {
            TaskSketchBasedParameters* param = qobject_cast<TaskSketchBasedParameters*>(it);
            if (param) {
                param->detachSelection();
            }
        }

        Gui::cmdGuiDocument(feature, "resetEdit()");
        feature->getDocument()->commitTransaction();
        endDialogHistory(feature->getDocument());  // FreeCAD-CH (ops#640)
    }
    catch (const Base::Exception& e) {
        QString errorText = QString::fromUtf8(e.what());
        QString statusText = QString::fromUtf8(getObject()->getStatusString());

        // generic, fallback error message
        if (errorText == QStringLiteral("Error") || errorText.isEmpty()) {
            if (!statusText.isEmpty() && statusText != QStringLiteral("Error")) {
                errorText = statusText;
            }
            else {
                errorText = tr(
                    "The feature could not be created with the given parameters.\n"
                    "The geometry may be invalid or the parameters may be incompatible.\n"
                    "Adjust the parameters and try again."
                );
            }
        }
        Base::Console().error("%s\n", errorText.toUtf8().constData());
        return false;
    }
    return true;
}

bool TaskDlgFeatureParameters::reject()
{
    auto feature = getObject<PartDesign::Feature>();
    App::DocumentObjectWeakPtrT weakptr(feature);
    App::Document* document = feature->getDocument();

    // The Body the feature was in before a New part move (ops#325): the abort deletes the new one
    App::DocumentObject* from = TaskResultParameters::movedFrom(feature);
    App::DocumentObjectWeakPtrT bodyPtr(from ? from : PartDesign::Body::findBodyOf(feature));

    // Find out previous feature we won't be able to do it after abort
    // (at least in the body case)
    App::DocumentObject* previous = feature->getBaseObject(/* silent = */ true);

    fieldGroup->disarm();
    if (references) {
        references->stopPick();
    }

    // detach the task panel from the selection to avoid to invoke
    // eventually onAddSelection when the selection changes
    std::vector<QWidget*> subwidgets = getDialogContent();
    for (auto it : subwidgets) {
        TaskSketchBasedParameters* param = qobject_cast<TaskSketchBasedParameters*>(it);
        if (param) {
            param->detachSelection();
        }
    }

    // roll back the done things which may delete the feature
    endDialogHistory(document);  // FreeCAD-CH (ops#640): the dialog's history ends with it
    document->abortTransaction();

    // if abort command deleted the object make the previous feature visible again
    if (weakptr.expired()) {
        // Make the tip or the previous feature visible again with preference to the previous one
        // TODO: ViewProvider::onDelete has the same code. May be this one is excess?
        if (previous && Gui::Application::Instance->getViewProvider(previous)) {
            Gui::Application::Instance->getViewProvider(previous)->show();
        }
        else if (auto body = bodyPtr.get<PartDesign::Body>()) {
            App::DocumentObject* tip = body->Tip.getValue();
            if (tip && Gui::Application::Instance->getViewProvider(tip)) {
                Gui::Application::Instance->getViewProvider(tip)->show();
            }
        }
    }

    Gui::cmdAppDocument(document, "recompute()");
    Gui::cmdGuiDocument(document, "resetEdit()");

    return true;
}

#include "moc_TaskFeatureParameters.cpp"
