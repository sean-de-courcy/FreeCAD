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
#include <cstring>
#include <deque>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <QAbstractSpinBox>
#include <QAction>
#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QCoreApplication>
#include <QEvent>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPointer>
#include <QPushButton>
#include <QSignalBlocker>
#include <QStandardItemModel>
#include <QStatusBar>
#include <QTimer>
#include <QToolButton>


#include <App/AutoTransaction.h>
#include <App/DocumentObserver.h>
#include <App/Part.h>
#include <App/PropertyStandard.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/CommandT.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/ForkKeymap.h>
#include <Gui/InputHint.h>
#include <Gui/Inventor/Draggers/Gizmo.h>
#include <Gui/MainWindow.h>
#include <Gui/TaskView/TaskView.h>
#include <Gui/BitmapFactory.h>
#include <Mod/PartDesign/App/StudioList.h>
#include <Mod/PartDesign/App/Feature.h>
#include <Mod/PartDesign/App/FeatureAddSub.h>
#include <Mod/PartDesign/App/FeatureBoolean.h>
#include <Mod/PartDesign/App/FeatureExtrude.h>
#include <Mod/PartDesign/App/FeatureHelix.h>
#include <Mod/PartDesign/App/FeatureLoft.h>
#include <Mod/PartDesign/App/FeaturePipe.h>
#include <Mod/PartDesign/App/FeatureRevolved.h>
#include <Mod/PartDesign/App/FeatureSketchBased.h>
#include <Mod/PartDesign/App/FeatureTransformed.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/Part/App/PropertyTopoShape.h>

#include "ui_TaskPreviewParameters.h"

#include "ReferenceField.h"
#include "StudioGui.h"
#include "TaskFeatureParameters.h"
#include "TaskReferences.h"
#include "TaskSketchBasedParameters.h"
#include "TaskTransformedParameters.h"
#include "Utils.h"
#include "ViewProviderBody.h"

namespace Gui
{
/// FreeCAD-CH (ops#640): defined and explained in Gui/Document.cpp (not in Document.h)
GuiExport bool editStartedUnchanged(const App::Document* doc);
}  // namespace Gui

namespace PartDesign
{
/// FreeCAD-CH (ops#640 round 5): defined and explained in PartDesign/App/Body.cpp (no header
/// names them): why New part is refused for a feature (what follows it can't be told apart), and
/// why its Merge can't go for a Remove or an Intersect (something builds on it)
PartDesignExport std::string newPartRefusal(const App::DocumentObject* feature, bool ignoreMerge);
PartDesignExport std::string mergeGoesRefusal(const App::DocumentObject* feature);
}  // namespace PartDesign

namespace PartDesignGui
{
/// FreeCAD-CH (ops#640 round 6, J22): defined and explained in Utils.cpp (no header names it):
/// Onshape's "Part N" for a new part, under its keymap
void nameNewPart(PartDesign::Body* body, App::Part* studioHint);
}  // namespace PartDesignGui

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

void TaskPreviewParameters::setOnshapeLayout(bool finalOffered)
{
    // Onshape's dialog has no overlay switch: the overlay stays on, its opacity is the preview row
    ui->showTransparentPreviewCheckBox->setChecked(true);
    ui->showTransparentPreviewCheckBox->hide();
    ui->opacityLabel->setText(tr("Preview"));
    ui->showFinalCheckBox->setText(tr("Final"));
    ui->showFinalCheckBox->setVisible(finalOffered);
}

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
    // What went to the new part (its profile, the feature, what follows it: ops#640 round 5), in
    // the order of `from`, and `from`'s members and Tip before the move
    std::vector<App::DocumentObjectT> moved;
    std::vector<App::DocumentObjectT> fromGroup;
    App::DocumentObjectT fromTip;
};
// One per feature: each document can have its dialog open (PR 303 round 1)
std::vector<NewPartMove> newPartMoves;
// The merge scope a merged Add had when its open dialog switched it away from Add (ops#640 round
// 5, hands-on B5-3 and B5-4): Onshape keeps the scope while the Extrude is New, a Remove or an
// Intersect, and Add merges it again. Kept across the dialog's restarts, forgotten when it closes
std::vector<std::pair<App::DocumentObjectT, std::vector<App::DocumentObjectT>>> scopesWas;

const std::vector<App::DocumentObjectT>* scopeWas(const App::DocumentObject* feature)
{
    auto it = std::ranges::find_if(scopesWas, [feature](const auto& entry) {
        return feature && entry.first.getObject() == feature;
    });
    return it != scopesWas.end() ? &it->second : nullptr;
}

void forgetScopeWas(const App::DocumentObjectT& featureT)
{
    std::erase_if(scopesWas, [&featureT](const auto& entry) { return entry.first == featureT; });
}

void rememberScope(const App::DocumentObjectT& featureT, std::vector<App::DocumentObjectT> parts)
{
    forgetScopeWas(featureT);
    scopesWas.emplace_back(featureT, std::move(parts));
}
// The features whose direction the user flipped in their open dialog (ops#640 H4): the dialog's
// session, kept across its restarts as the moves are, forgotten when it closes
std::vector<App::DocumentObjectT> reversedTouched;

bool isReversedTouched(const App::DocumentObject* feature)
{
    return feature && std::ranges::any_of(reversedTouched, [feature](const auto& touched) {
        return touched.getObject() == feature;
    });
}

void forgetReversedTouched(const App::DocumentObjectT& featureT)
{
    std::erase(reversedTouched, featureT);
}
// The new Extrudes the command made with no profile: their first profile decides where they open
// (hands-on check A-1, TaskResultParameters::profileTaken), unless the user chose a row first
std::vector<App::DocumentObjectT> openingAwaited;

bool isOpeningAwaited(const App::DocumentObject* feature)
{
    return feature && std::ranges::any_of(openingAwaited, [feature](const auto& awaited) {
        return awaited.getObject() == feature;
    });
}

void forgetOpeningAwaited(const App::DocumentObjectT& featureT)
{
    std::erase(openingAwaited, featureT);
}
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
    /** The dialog's net change, for an OK that changed nothing (leftUnchanged()): the first value
     * of each input of the step, as App's no-op rule reads inputs, whatever changed it (a field,
     * a pick, a recompute, the history itself). Known only while pristine: the step had nothing
     * when the edit started (an edit's booked step, not a new feature's:
     * Gui::editStartedUnchanged()), and no object came or went. */
    std::vector<Change> originals;
    bool pristine = true;
    bool linkChanged = false;  // a link among the originals: App's no-op rule keeps the step
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
    void track(const App::DocumentObject& obj, const App::Property& prop);
    bool leftUnchanged() const;
    bool restartable() const;
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

// A result in App's no-op rule (Transactions.cpp isResult): not an input of the step
bool isStepResult(const App::Property& prop)
{
    using App::Property;
    if (prop.testStatus(Property::NoModify) || prop.testStatus(Property::Transient)
        || prop.testStatus(Property::PropTransient)) {
        return true;
    }
    const bool output = prop.testStatus(Property::Output) || prop.testStatus(Property::PropOutput);
    const bool readOnly = prop.testStatus(Property::ReadOnly)
        || prop.testStatus(Property::PropReadOnly);
    static const Base::Type partShape = Base::Type::fromName("Part::PropertyPartShape");
    return (output && readOnly) || (!partShape.isBad() && prop.getTypeId().isDerivedFrom(partShape));
}

/** Whether the live property holds the value `recorded` (a Copy() of it): values by isSame() on
 * two copies (as App's no-op rule compares), links by what they name (the objects and the
 * subnames, which App's rule doesn't compare: it keeps every recorded link as a change). Not an
 * expression container (its links don't tell two expressions apart), nor geometry data. */
bool holdsValue(const App::Property& live, const App::Property& recorded)
{
    static const Base::Type geoData = Base::Type::fromName("App::PropertyComplexGeoData");
    if (!geoData.isBad() && live.getTypeId().isDerivedFrom(geoData)) {
        return false;
    }
    if (live.isDerivedFrom<App::PropertyXLinkContainer>()) {
        return false;
    }
    std::unique_ptr<App::Property> now(live.Copy());
    if (!now || now->getTypeId() != recorded.getTypeId()) {
        return false;
    }
    if (auto link = dynamic_cast<const App::PropertyLinkBase*>(now.get())) {
        auto before = dynamic_cast<const App::PropertyLinkBase*>(&recorded);
        if (!before) {
            return false;
        }
        std::vector<App::DocumentObject*> objsNow;
        std::vector<App::DocumentObject*> objsBefore;
        std::vector<std::string> subsNow;
        std::vector<std::string> subsBefore;
        link->getLinks(objsNow, true, &subsNow, false);
        before->getLinks(objsBefore, true, &subsBefore, false);
        // a single link to a whole object, written with no subname or with an empty one
        auto noEmpty = [](std::vector<std::string>& subs) {
            std::erase_if(subs, [](const std::string& sub) {
                return sub.empty();
            });
        };
        if (objsNow.size() == 1 && objsBefore.size() == 1) {
            noEmpty(subsNow);
            noEmpty(subsBefore);
        }
        // and by the naming solver's guesses: an accepted guess (the field's Accept guess, Mark
        // broken) names the same element and drops or changes only the record (ops#640)
        return objsNow == objsBefore && subsNow == subsBefore
            && link->getElementGuesses() == before->getElementGuesses();
    }
    return now->isSame(recorded);
}

// The dialog's net change (originals), from any change of the step's inputs
void DialogHistory::track(const App::DocumentObject& obj, const App::Property& prop)
{
    App::Document* doc = document();
    if (!pristine || !dialog || !doc || doc->isPerformingTransaction() || isStepResult(prop)) {
        return;
    }
    const char* objName = obj.getNameInDocument();
    const char* propName = prop.getName();
    if (!objName || !propName || prop.getContainer() != &obj) {
        return;
    }
    const bool known = std::ranges::any_of(originals, [&](const Change& change) {
        return change.object == objName && change.property == propName;
    });
    if (known) {
        return;
    }
    try {
        std::unique_ptr<App::Property> before(prop.Copy());
        if (!before) {
            pristine = false;
            return;
        }
        linkChanged = linkChanged || prop.isDerivedFrom<App::PropertyLinkBase>();
        originals.push_back(
            Change {.object = objName, .property = propName, .value = std::move(before)}
        );
    }
    catch (...) {
        pristine = false;
    }
}

/** FreeCAD-CH (ops#640, the rule "an unchanged accept leaves no step"): whether the dialog's OK
 * would commit a step that changes nothing App's no-op rule can tell: a link picked and then
 * undone or picked back (App keeps every recorded link as a change, deliberately: Transactions.cpp
 * holdsRecorded). Only for a pristine step whose every input holds its first value, with a link
 * among them, and no other document in the step (its changes aren't seen here); the OK then
 * aborts the step instead of committing it (TaskDlgFeatureParameters::accept), as Cancel does,
 * which keeps the Redo stack. */
bool DialogHistory::leftUnchanged() const
{
    App::Document* doc = document();
    if (!doc || !pristine || !linkChanged) {
        return false;
    }
    const int id = currentStep(doc);
    for (App::Document* other : App::GetApplication().getDocuments()) {
        if (other != doc && other->hasPendingTransaction()
            && other->getTransactionID(true, 0) == id) {
            return false;
        }
    }
    return std::ranges::all_of(originals, [doc](const Change& change) {
        App::DocumentObject* obj = doc->getObject(change.object.c_str());
        App::Property* live = obj ? obj->getPropertyByName(change.property.c_str()) : nullptr;
        try {
            return live && holdsValue(*live, *change.value);
        }
        catch (...) {
            return false;
        }
    });
}

/** Whether an undo or redo can rebuild the panels (refresh(), restartEdit): the dialog is still
 * the document's, edited on the history's feature. If it can't, the history doesn't move: the
 * panels would keep the values from before, and the next OK would apply() them over the undone
 * ones. */
bool DialogHistory::restartable() const
{
    App::Document* doc = document();
    Gui::Document* guiDoc = doc ? Gui::Application::Instance->getDocument(doc) : nullptr;
    auto vp = guiDoc
        ? freecad_cast<Gui::ViewProviderDocumentObject*>(guiDoc->getEditViewProvider())
        : nullptr;
    App::DocumentObject* obj = vp ? vp->getObject() : nullptr;
    return obj && obj->getNameInDocument() && feature == obj->getNameInDocument() && dialog
        && Gui::Control().activeDialog(doc) == dialog.data();
}

bool DialogHistory::watches() const
{
    App::Document* doc = document();
    return doc && dialog && undoAction && !restoring && doc->isStepLocked() && !doc->isPerformingTransaction()
        && !doc->testStatus(App::Document::Recomputing);
}

void DialogHistory::record(const App::DocumentObject& obj, const App::Property& prop)
{
    track(obj, prop);
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
    if (undos.empty() || !watches() || !restartable()) {
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
    if (redos.empty() || !watches() || !restartable()) {
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
        // FreeCAD-CH (ops#640, journey J1 G1): the rebuilt panel puts the cursor in its first
        // field, so the next Ctrl+Y went to that field's text redo. A focus outside the panel
        // (the 3D view, where Ctrl+Z was pressed) is given back once the panel is up
        QPointer<QWidget> focus = QApplication::focusWidget();
        Gui::TaskView::TaskView* panel = Gui::Control().taskPanel();
        if (focus && panel && panel->isAncestorOf(focus)) {
            focus = nullptr;  // a field of the old panel: it goes with the rebuild
        }
        {
            Base::FlagToggler<> own(historyRestart);
            restartEdit(featureT, []() {});
        }
        if (focus) {
            QTimer::singleShot(0, focus, [focus]() {
                if (focus) {
                    focus->setFocus(Qt::OtherFocusReason);
                }
            });
        }
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
        // a new feature's step (or a move's) holds changes from before the edit
        history->pristine = Gui::editStartedUnchanged(doc);
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
        if (found && found->dialog && doc && !doc->isPerformingTransaction()) {
            found->pristine = false;
            if (doc->isStepLocked()) {
                found->clear();
            }
        }
    };
    history->connections.emplace_back(doc->signalNewObject.connect(structural));
    history->connections.emplace_back(doc->signalDeletedObject.connect(structural));
    history->updateActions();
}

// The dialog goes: its history stops listening, and ends unless the history's own restart
// rebuilds the dialog (the next dialog takes it again). A dialog closed any other way than its OK
// or Cancel (its document closed, the application quit, an OK that failed after its resetEdit)
// ends it here: kept in the map, its copies of properties (Property::Copy()) were destroyed only
// at the static destruction, after App and Python, too late for a Python object's or a link's.
void detachDialogHistory(const Gui::TaskView::TaskDialog* dlg)
{
    std::erase_if(dialogHistories, [dlg](auto& entry) {
        DialogHistory* history = entry.second.get();
        if (!history || history->dialog != dlg) {
            return false;
        }
        history->connections.clear();
        if (history->open) {
            history->seal();
        }
        history->dialog = nullptr;
        return !historyRestart;
    });
}

// Whether the dialog's OK would commit a step that changes nothing (DialogHistory::leftUnchanged)
bool dialogLeftUnchanged(const App::Document* doc)
{
    DialogHistory* history = doc ? findHistory(doc->getName()) : nullptr;
    if (!history) {
        return false;
    }
    history->seal();
    return history->leftUnchanged();
}

// The dialog's OK or Cancel: its history ends
void endDialogHistory(const App::Document* doc)
{
    if (doc) {
        dialogHistories.erase(doc->getName());
    }
}

// FreeCAD-CH ops#654 R0 lite: in a studio with a history list the studio features (owners) act on
// other parts, so an in-Body feature's Result box offers no sibling rows there (the parts list, the
// in-Body merge list); the sibling code stays for studios without a list, and files using it open
// as before
static bool inListedStudio(const PartDesign::Body* body)
{
    App::Part* studio = nullptr;
    return body && Part::BodyBase::studioOf(body, studio)
        && PartDesign::StudioList::of(body->getDocument(), studio);
}

// Other parts in the Body's studio: Bodies of one container placed alike (ops#325); none offered
// in a listed studio (R0 lite)
bool hasStudioSiblings(const PartDesign::Body* body)
{
    if (inListedStudio(body)) {
        return false;
    }
    for (auto obj : body->getDocument()->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        if (obj != body
            && Part::BodyBase::areStudioSiblings(body, static_cast<PartDesign::Body*>(obj))) {
            return true;
        }
    }
    return false;
}

// Why New part isn't offered for an additive feature; empty when it is. newPartFrom's rule
// (PartDesign::newPartRefusal: the later features that work on its material go along, one that
// can't be told apart refuses, ops#640 round 5), and a transaction that Cancel aborts. With
// `ignoreMerge`, its Merge counts as gone (the user unticked the whole scope)
QString newPartRefusal(PartDesign::FeatureAddSub* feature, bool ignoreMerge = false)
{
    auto body = PartDesign::Body::findBodyOf(feature);
    if (!body) {
        return QObject::tr("New part needs a feature in a body");
    }
    if (!hasOpenTransaction(feature->getDocument())) {
        return QObject::tr("New part needs a dialog that Cancel can undo");
    }
    QString why = QString::fromStdString(PartDesign::newPartRefusal(feature, ignoreMerge));
    if (!why.isEmpty()) {
        why[0] = why[0].toUpper();
    }
    return why;
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
    // FreeCAD-CH (selection parity P1): the field armed now is armed again in the new dialog. A
    // new Extrude's first region moves it to its part (profileTaken), and the field that took
    // the pick disarmed with the old dialog, so the second region became a plain selection
    std::string armedProperty;
    if (ReferenceField* field = ReferenceField::armedField();
        field && field->ownerDocument() == doc) {
        armedProperty = field->propertyName();
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
        TaskDlgFeatureParameters::armOnOpen(armedProperty);
        try {
            PartDesignGui::setEdit(feature, PartDesign::Body::findBodyOf(feature));
        }
        catch (const Base::Exception& e) {
            e.reportException();
        }
        // Taken by the dialog's open(), or no dialog came
        TaskDlgFeatureParameters::armOnOpen({});
    }
    // No panel came back, so no box takes the move over (PR 303 round 2)
    if (!Gui::Control().activeDialog(doc)) {
        forgetMove(featureT);
        forgetReversedTouched(featureT);
        forgetScopeWas(featureT);
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

// New part's move, inside a restart of the edit (restartEdit)
void newPartMove(const App::DocumentObjectT& featureT)
{
    App::DocumentObject* feature = featureT.getObject();
    PartDesign::Body* from = PartDesign::Body::findBodyOf(feature);
    if (!from) {
        return;
    }
    std::vector<App::DocumentObjectT> fromGroup;
    for (App::DocumentObject* obj : from->Group.getValues()) {
        fromGroup.emplace_back(obj);
    }
    App::DocumentObjectT fromTip(from->Tip.getValue());
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
    nameNewPart(part, nullptr);
    NewPartMove move {
        .feature = featureT,
        .from = App::DocumentObjectT(from),
        .part = App::DocumentObjectT(part),
        .moved = {},
        .fromGroup = fromGroup,
        .fromTip = fromTip,
    };
    for (const App::DocumentObjectT& objT : fromGroup) {
        App::DocumentObject* obj = objT.getObject();
        if (obj && part->hasObject(obj)) {
            move.moved.push_back(objT);
        }
    }
    forgetMove(featureT);
    newPartMoves.push_back(move);
    // The part it left shows its own result now; OK purges the document's touched objects
    // (accept()), so the part would keep the feature's solid until its next recompute
    from->recomputeFeature(/*recursive=*/true);
    // ...and stays shown, as Onshape's other parts do (ops#630): the command hid its Tip for
    // the feature, which has left. A feature the user shows instead stays the shown one
    showTipIfNoneShown(from);
}

// Add to's move back of what this dialog's New part moved, inside a restart of the edit: each
// where it was in `from`, in order (the chain reroutes through each, Body::insertObject), and
// `from`'s Tip as it was
void backMove(const App::DocumentObjectT& featureT)
{
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
    std::vector<App::DocumentObject*> back;
    for (const App::DocumentObjectT& objT : move.moved) {
        App::DocumentObject* obj = objT.getObject();
        if (obj && part->hasObject(obj)) {
            back.push_back(obj);
        }
    }
    for (auto it = back.rbegin(); it != back.rend(); ++it) {
        run(cmd(part) + ".removeObject(" + cmd(*it) + ")");
    }
    for (App::DocumentObject* obj : back) {
        // after the nearest member before it that is in `from` again (relinked to its origin on
        // insert)
        App::DocumentObject* after = nullptr;
        for (const App::DocumentObjectT& memberT : move.fromGroup) {
            App::DocumentObject* member = memberT.getObject();
            if (member == obj) {
                break;
            }
            const auto& group = from->Group.getValues();
            if (member && std::ranges::find(group, member) != group.end()) {
                after = member;
            }
        }
        run(cmd(from) + ".insertObject(" + cmd(obj) + ", " + (after ? cmd(after) : std::string("None"))
            + ", True)");
    }
    App::DocumentObject* tip = move.fromTip.getObject();
    const auto& members = from->Group.getValues();
    if (tip && std::ranges::find(members, tip) != members.end() && from->Tip.getValue() != tip) {
        run(cmd(from) + ".Tip = " + cmd(tip));
    }
    // The part shows its Tip alone again, as Body::addObject() did for the feature
    if (tip && std::ranges::find(members, tip) != members.end()) {
        for (App::DocumentObject* obj : members) {
            if (obj != tip && obj->isDerivedFrom<PartDesign::Feature>() && obj->Visibility.getValue()) {
                obj->Visibility.setValue(false);
            }
        }
        if (!tip->Visibility.getValue()) {
            tip->Visibility.setValue(true);
        }
    }
    // the new Body, empty now, goes with its origin
    if (part->Group.getValues().empty()) {
        run(
            std::string("App.getDocument('") + part->getDocument()->getName()
            + "').removeObject('" + part->getNameInDocument() + "')"
        );
    }
}

void moveToNewPart(const App::DocumentObjectT& featureT)
{
    restartEdit(featureT, [&featureT]() { newPartMove(featureT); });
}

void moveBack(const App::DocumentObjectT& featureT)
{
    restartEdit(featureT, [&featureT]() { backMove(featureT); });
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

// An operation row's own tooltip, the part it acts on, kept while a refusal's shows instead
constexpr int PartTipRole = Qt::UserRole + 1;

QString partLabel(const App::DocumentObject* body)
{
    return body ? QString::fromUtf8(body->Label.getValue()) : QString();
}

// A Pad, Pocket, Revolution, Groove, Loft, Pipe or Helix in a body: the operation row, New part /
// Add / Remove / Intersect, at its creation and at every edit, as Onshape's Extrude, Revolve,
// Loft, Sweep and Helix (FreeCAD-CH ops#640, rank 20)
bool hasOperationRow(const App::DocumentObject* feature)
{
    return feature
        && (feature->isDerivedFrom<PartDesign::FeatureExtrude>()
            || feature->isDerivedFrom<PartDesign::Revolved>()
            || feature->isDerivedFrom<PartDesign::Loft>()
            || feature->isDerivedFrom<PartDesign::Pipe>()
            || feature->isDerivedFrom<PartDesign::Helix>())
        && PartDesign::Body::findBodyOf(feature);
}
}  // namespace

// FreeCAD-CH (ops#640 rank 14): restartEdit for a tool-first dress-up's move to the part of its
// dialog's first pick (TaskDressUpParameters.cpp declares it too: no header names it)
namespace PartDesignGui
{
void restartFeatureEdit(const App::DocumentObjectT& featureT, const std::function<void()>& change);
void restartFeatureEdit(const App::DocumentObjectT& featureT, const std::function<void()>& change)
{
    restartEdit(featureT, change);
}
}  // namespace PartDesignGui

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
    // FreeCAD-CH (ops#640 round 9): why a row is greyed, under the row (showRefusals)
    auto* refusals = new QLabel(this);
    refusals->setObjectName(QStringLiteral("refusalNote"));
    refusals->setWordWrap(true);
    refusals->setVisible(false);
    groupLayout()->addWidget(refusals);

    auto feature = getObject<PartDesign::FeatureAddSub>();
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    if (hasOperationRow(feature)) {
        addOperationRow();
    }
    else if (feature->getAddSubType() == PartDesign::FeatureAddSub::Type::Additive) {
        App::DocumentObject* from = movedFrom(feature);
        // Onshape's words, the part in the tooltip (ops#640 round 6, J2/J9)
        combo->addItem(tr("Add"), QStringLiteral("add"));
        combo->setItemData(0, tr("Add to %1").arg(partLabel(from ? from : body)), Qt::ToolTipRole);
        combo->addItem(tr("New"), QStringLiteral("new"));
        if (from) {
            combo->setCurrentIndex(1);
        }
        else {
            refuseRow(QStringLiteral("new"), newPartRefusal(feature));
        }
        // Merge with (design 2.5): for a feature in its own part, not one moved to a new part
        if (!from && body && hasStudioSiblings(body) && !PartDesign::Boolean::mergeOf(body)) {
            addMergeList();
        }
    }
    else {
        combo->addItem(tr("Remove"), QStringLiteral("Subtraction"));
        combo->setItemData(0, tr("Remove from %1").arg(partLabel(body)), Qt::ToolTipRole);
        combo->addItem(tr("Intersect"), QStringLiteral("Common"));
        combo->setItemData(1, tr("Intersect with %1").arg(partLabel(body)), Qt::ToolTipRole);
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
    // OK, Cancel or another close: the move is final, or aborted with the transaction; the
    // dialog's session ends with the user's direction (ops#640 H4)
    if (!restartingEdit) {
        forgetMove(featureT);
        forgetReversedTouched(featureT);
        forgetOpeningAwaited(featureT);
        forgetScopeWas(featureT);
    }
}

void TaskResultParameters::noteReversedTouched(App::DocumentObject* feature)
{
    // Only an Extrude's dialog has the switch, and its Result box forgets the note when it closes
    if (hasOperationRow(feature) && !isReversedTouched(feature)) {
        reversedTouched.emplace_back(feature);
    }
}

bool TaskResultParameters::hasRows(App::DocumentObject* feature)
{
    auto addSub = freecad_cast<PartDesign::FeatureAddSub*>(feature);
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    if (!addSub || !body) {
        return false;
    }
    if (hasOperationRow(feature)) {
        return true;  // New part, Add, Remove, Intersect: always (ops#640)
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

bool isSubtractive(const QString& key)
{
    return key == QStringLiteral("Subtraction") || key == QStringLiteral("Common");
}

// Merge with all on a new Add (ops#640 rank 1): Onshape's help says on; the hands-on checks R5, R8
// and A-1 found it off (a sketch on a face: the face's part as the scope; Add from New: the one
// part the tool touches, or none). This line switches it
constexpr bool mergeWithAllByDefault = false;

// Nothing before the feature in its part: its merge scope holds no part of its own (ops#640)
bool isFirstSolid(PartDesign::FeatureAddSub* feature)
{
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    return body && !body->BaseFeature.getValue() && !body->getPrevSolidFeature(feature);
}

// A part's own first solid, adding: the feature that made the part (Onshape's New). Not an Add
// whose merge scope is empty, or that merges with all (ops#640 rank 1)
bool isNewPart(PartDesign::FeatureAddSub* feature)
{
    return isFirstSolid(feature)
        && feature->getBooleanOperation() == PartDesign::FeatureAddSub::BooleanOperation::Union
        && !feature->EmptyMergeScope.getValue() && !feature->MergeWithAll.getValue();
}

// The row the feature is on: new, add, Subtraction or Common
QString operationKey(PartDesign::FeatureAddSub* feature)
{
    if (isMoved(feature) || isNewPart(feature)) {
        return QStringLiteral("new");
    }
    if (feature->getBooleanOperation() == PartDesign::FeatureAddSub::BooleanOperation::Union) {
        return QStringLiteral("add");
    }
    return QString::fromLatin1(feature->Operation.getValueAsString());
}

// The part a new part's feature goes to for Add, Remove or Intersect: the one this dialog moved it
// from, else the one studio part its tool touches. Touching two or more, none: Onshape's Add then
// has an empty scope, red, and merges neither (hands-on check A-1 (b), (c); ops#640 rank 1)
PartDesign::Body* operationTarget(PartDesign::FeatureAddSub* feature)
{
    if (auto from = freecad_cast<PartDesign::Body*>(TaskResultParameters::movedFrom(feature))) {
        return from;
    }
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    if (!body) {
        return nullptr;
    }
    TaskResultParameters::TouchCache cache;
    PartDesign::Body* touched = nullptr;
    for (auto obj : feature->getDocument()->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        auto other = static_cast<PartDesign::Body*>(obj);
        if (other != body && Part::BodyBase::areStudioSiblings(body, other)
            && !PartDesign::Boolean::mergeOf(other) && toolTouches(feature, other, cache)) {
            if (touched) {
                return nullptr;
            }
            touched = other;
        }
    }
    return touched;
}

// Why a new part's feature can't go to target, or empty: PartDesign.addToPart's own rule
// (Body::addToPartRefusal, ops#640), after the dialog's: a move this dialog made is taken back,
// and the move needs the dialog's transaction, which Cancel aborts. No target moves nothing:
// the feature stays its part's first solid, with an empty merge scope ('No merge scope
// selected', ops#640 rank 3a) unless an Add merges with all
QString addToPartRefusal(PartDesign::FeatureAddSub* feature, PartDesign::Body* target)
{
    if (TaskResultParameters::movedFrom(feature) || !target) {
        return {};  // this dialog's move, taken back; or no move
    }
    if (!hasOpenTransaction(feature->getDocument())) {
        return QObject::tr("Needs a dialog that Cancel can undo");
    }
    QString why = QString::fromStdString(PartDesign::Body::addToPartRefusal(feature, target));
    if (!why.isEmpty()) {
        why[0] = why[0].toUpper();
    }
    return why;
}

// A new part's feature touching no other part may become a Remove or an Intersect: its merge
// scope is empty, and it fails red, "No merge scope selected", as Onshape's does (hands-on checks
// R7(a) and R8, ops#640 rank 3a; FeatureAddSub::recompute). The scope list then picks its part

// The Merge right after the feature (makeMerge's place), or null
PartDesign::Boolean* mergeAfter(PartDesign::FeatureAddSub* feature)
{
    return PartDesign::Boolean::mergeAfter(feature);
}

// Puts the feature on the row `key`, inside a restart of the edit, so the box shows the parts
// list or the merge list that goes with it. Leaving a cut drops its siblings; a new part's
// feature goes to its target first; the tool flips between adding and cutting when its
// direction, not a face, ends it (Onshape flips the arrow for Remove: the tool goes into the
// material).
// A merged Add leaving Add drops its Merge (the merged parts are parts again, whole) and keeps its
// scope, `scope` (the ticked parts; null: what the Merge merges), for the dialog: a Remove or an
// Intersect then cuts those parts too (siblings), as Onshape's (hands-on B5-4), and Add merges them
// again (B5-3), as a cut's siblings do (ops#640 round 5)
void switchOperation(
    const App::DocumentObjectT& featureT,
    const QString& key,
    const std::optional<std::vector<App::DocumentObjectT>>& scope
)
{
    restartEdit(featureT, [&featureT, &key, &scope]() {
        auto feature = freecad_cast<PartDesign::FeatureAddSub*>(featureT.getObject());
        if (!feature) {
            return;
        }
        const QString was = operationKey(feature);
        auto run = [](const std::string& line) {
            Gui::Command::doCommand(Gui::Command::Doc, "%s", line.c_str());
        };
        auto list = [](const std::vector<App::DocumentObjectT>& parts) {
            std::string text;
            for (const App::DocumentObjectT& partT : parts) {
                if (App::DocumentObject* part = partT.getObject()) {
                    text += (text.empty() ? "" : ", ") + Gui::Command::getObjectCmd(part);
                }
            }
            return text;
        };
        const std::string obj = Gui::Command::getObjectCmd(feature);
        run("import PartDesign");
        if (was == QStringLiteral("add") && key != QStringLiteral("add")) {
            if (PartDesign::Boolean* merge = mergeAfter(feature)) {
                std::vector<App::DocumentObjectT> parts;
                if (scope) {
                    parts = *scope;
                }
                else {
                    for (App::DocumentObject* part : merge->mergedBodies()) {
                        parts.emplace_back(part);
                    }
                }
                rememberScope(featureT, parts);
                run("PartDesign.setMergeScope(" + obj + ", [])");
            }
        }
        if (isSubtractive(was) && !isSubtractive(key) && !feature->getSiblings().empty()) {
            std::vector<App::DocumentObjectT> parts;
            for (PartDesign::FeatureAddSub* sibling : feature->getSiblings()) {
                if (PartDesign::Body* part = PartDesign::Body::findBodyOf(sibling)) {
                    parts.emplace_back(part);
                }
            }
            // The scope the dialog keeps is the cut's latest
            if (scopeWas(feature)) {
                rememberScope(featureT, parts);
            }
            run("PartDesign.makeSiblings(" + obj + ", [])");
            // Each part a sibling left shows its own result now: OK purges the document's touched
            // objects (accept()), so it would keep the cut until its next recompute (newPartMove's
            // rule). It stays shown, its Tip taking over from the sibling
            for (const App::DocumentObjectT& partT : parts) {
                if (auto part = freecad_cast<PartDesign::Body*>(partT.getObject())) {
                    part->recomputeFeature(/*recursive=*/true);
                    showTipIfNoneShown(part);
                }
            }
        }
        if (was == QStringLiteral("new") && key != QStringLiteral("new")) {
            if (isMoved(feature)) {
                backMove(featureT);
            }
            else if (PartDesign::Body* target = operationTarget(feature)) {
                // The one part the tool touches is the scope (R8), as for a sketch on its face
                run("PartDesign.addToPart(" + obj + ", " + Gui::Command::getObjectCmd(target) + ")");
            }
            else if (key == QStringLiteral("add") && mergeWithAllByDefault) {
                // Merge with all, touching nothing: a new part, healthy (R8, ops#640 H2)
                run(obj + ".MergeWithAll = True");
                Gui::getMainWindow()->showMessage(
                    QObject::tr("Touches no other part: added as a new part"),
                    8000
                );
            }
        }
        const std::string operation =
            isSubtractive(key) ? std::string(key.toLatin1().constData()) : std::string("Union");
        if (operation != feature->Operation.getValueAsString()) {
            run(obj + ".Operation = '" + operation + "'");
        }
        // every end bound to the direction flips (Onshape: Blind, Through all, Up to next); a face
        // or a shape fixes the side itself. Intersect flips as Remove does. Not once the user
        // flipped it in this dialog: Onshape then keeps the user's direction (R5, ops#640 H4).
        // Revolution and Groove pair like Pad and Pocket (each class's suggested direction adds,
        // or cuts); a Loft, Sweep or Helix changes only the Operation (rank 20)
        auto profileBased = freecad_cast<PartDesign::ProfileBased*>(feature);
        auto typeProp = dynamic_cast<App::PropertyEnumeration*>(feature->getPropertyByName("Type"));
        const bool pairs = feature->isDerivedFrom<PartDesign::FeatureExtrude>()
            || feature->isDerivedFrom<PartDesign::Revolved>();
        const char* typeName = pairs && typeProp ? typeProp->getValueAsString() : nullptr;
        const std::string type = typeName ? typeName : "";
        const bool directionBound = type == "Length" || type == "Angle" || type == "ThroughAll"
            || type == "UpToLast" || type == "UpToFirst";
        if (isSubtractive(was) != isSubtractive(key) && directionBound && profileBased
            && !isReversedTouched(feature)) {
            run(obj + ".Reversed = " + (profileBased->Reversed.getValue() ? "False" : "True"));
        }
        // Its part's first solid: New is the same feature with no scope; an Add, a Remove or an
        // Intersect has an empty scope, red until a part is picked (ops#640 rank 3a)
        const bool first = isFirstSolid(feature);
        if (key == QStringLiteral("new") && was != QStringLiteral("new")) {
            if (!first) {
                newPartMove(featureT);
            }
            else {
                if (feature->EmptyMergeScope.getValue()) {
                    run(obj + ".EmptyMergeScope = False");
                }
                if (feature->MergeWithAll.getValue()) {
                    run(obj + ".MergeWithAll = False");
                }
            }
        }
        else if (key != QStringLiteral("new") && first && !feature->EmptyMergeScope.getValue()
                 && !feature->MergeWithAll.getValue()) {
            run(obj + ".EmptyMergeScope = True");
        }
        // The scope it kept: Add merges it again, a Remove or an Intersect cuts it too. A part gone
        // or merged elsewhere meanwhile is left out; a refusal leaves the feature on its own part
        const std::vector<App::DocumentObjectT>* kept = scopeWas(feature);
        if (kept && !first && !isMoved(feature) && key != QStringLiteral("new")) {
            std::vector<App::DocumentObjectT> parts;
            PartDesign::Body* own = PartDesign::Body::findBodyOf(feature);
            for (const App::DocumentObjectT& partT : *kept) {
                auto part = freecad_cast<PartDesign::Body*>(partT.getObject());
                if (part && part != own && !PartDesign::Boolean::mergeOf(part)
                    && Part::BodyBase::areStudioSiblings(own, part)) {
                    parts.emplace_back(part);
                }
            }
            const bool adding = key == QStringLiteral("add");
            if (adding) {
                forgetScopeWas(featureT);
            }
            if (!parts.empty() && (adding ? !mergeAfter(feature) : feature->getSiblings().empty())) {
                try {
                    run(std::string(adding ? "PartDesign.setMergeScope(" : "PartDesign.makeSiblings(")
                        + obj + ", [" + list(parts) + "])");
                }
                catch (const Base::Exception& e) {
                    e.reportException();
                }
            }
        }
        feature->recomputeFeature();
        // What it merges or cuts besides its own part computes now (OK purges the touched objects)
        for (PartDesign::FeatureAddSub* sibling : feature->getSiblings()) {
            if (PartDesign::Body* part = PartDesign::Body::findBodyOf(sibling)) {
                part->recomputeFeature(/*recursive=*/true);
            }
        }
    });
}

// FreeCAD-CH (ops#640, hands-on check A-1): a new Extrude opens as Onshape's does. Add, with the
// one part its tool touches as its scope (a sketch on that part's face, or on a plane overlapping
// only that part); else New, a part of its own (touching nothing, or two parts or more)
// Where A-1 puts the feature: nowhere else (an Add to its own part, or New already), a new part,
// and/or into another part
struct OpeningMove
{
    bool toNewPart = false;
    PartDesign::Body* into = nullptr;
};

// FreeCAD-CH (ops#640, round 3 of A-1): a new Remove (a Pocket, a Groove, a subtractive Loft,
// Sweep or Helix) opens with its own part as its scope when its tool overlaps it, else in the one
// other part its tool overlaps (moved there). Overlapping no part it stays in its own, a healthy
// no-op with round 2's 'do not intersect' note, as Onshape's Remove that misses (hands-on R7b,
// Batch 4 A-2'a); overlapping two other parts or more it stays too (not seen in Onshape: the cheap
// call, no new Body made for it, the scope picked by hand)
OpeningMove removeOpeningMove(PartDesign::FeatureAddSub* feature, PartDesign::Body* body)
{
    OpeningMove move;
    // A Remove as the command made it: not a sibling, none made yet, not moved, no scope chosen;
    // a tool not made (no profile or axis yet) waits
    if (feature->getBooleanOperation() != PartDesign::FeatureAddSub::BooleanOperation::Subtraction
        || feature->MergeWithAll.getValue() || feature->EmptyMergeScope.getValue()
        || TaskResultParameters::primaryOf(feature) || !feature->getSiblings().empty()
        || isMoved(feature) || feature->AddSubShape.getShape().isNull()) {
        return move;
    }
    TaskResultParameters::TouchCache cache;
    const bool first = isFirstSolid(feature);
    bool own = false;
    if (!first) {
        auto before = freecad_cast<Part::Feature*>(body->getPrevSolidFeature(feature));
        if (!before) {
            return move;  // a BaseFeature alone: can't tell, so it stays
        }
        Part::TopoShape tool = feature->AddSubShape.getShape();
        Part::TopoShape shape = before->Shape.getShape();
        tool.setPlacement(feature->globalPlacement());
        shape.setPlacement(before->globalPlacement());
        own = !shape.isNull()
            && PartDesign::FeatureAddSub::shapesTouch(tool.getShape(), shape.getShape());
    }
    if (own) {
        return move;  // its own part the scope
    }
    PartDesign::Body* other = nullptr;
    int touched = 0;
    for (auto obj : feature->getDocument()->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        auto part = static_cast<PartDesign::Body*>(obj);
        if (part != body && Part::BodyBase::areStudioSiblings(body, part)
            && !PartDesign::Boolean::mergeOf(part) && toolTouches(feature, part, cache)) {
            other = part;
            ++touched;
        }
    }
    // Out of its part, which it doesn't overlap, into the one other part it overlaps
    if (touched != 1) {
        return move;
    }
    move.toNewPart = !first;
    move.into = other;
    return move;
}

OpeningMove openingMove(PartDesign::FeatureAddSub* feature)
{
    OpeningMove move;
    PartDesign::Body* body = feature ? PartDesign::Body::findBodyOf(feature) : nullptr;
    if (body && hasOperationRow(feature)
        && feature->getAddSubType() == PartDesign::FeatureAddSub::Type::Subtractive) {
        return removeOpeningMove(feature, body);
    }
    // An Add as the command made it: not a cut, not a sibling, not moved, no scope chosen; a
    // feature in error (no profile, a failed shape) stays where it is
    if (!body || !hasOperationRow(feature)
        || feature->getAddSubType() != PartDesign::FeatureAddSub::Type::Additive
        || feature->getBooleanOperation() != PartDesign::FeatureAddSub::BooleanOperation::Union
        || feature->MergeWithAll.getValue() || feature->EmptyMergeScope.getValue()
        || TaskResultParameters::primaryOf(feature) || isMoved(feature) || !feature->isValid()
        || feature->AddSubShape.getShape().isNull()) {
        return move;
    }
    TaskResultParameters::TouchCache cache;
    const bool first = isFirstSolid(feature);
    // Its own part: the solid before it, placed as toolTouches places a part
    int touched = 0;
    bool own = false;
    if (!first) {
        auto before = freecad_cast<Part::Feature*>(body->getPrevSolidFeature(feature));
        if (!before) {
            own = true;  // a BaseFeature alone: can't tell, so it stays an Add
        }
        else {
            Part::TopoShape tool = feature->AddSubShape.getShape();
            Part::TopoShape shape = before->Shape.getShape();
            tool.setPlacement(feature->globalPlacement());
            shape.setPlacement(before->globalPlacement());
            own = !shape.isNull()
                && PartDesign::FeatureAddSub::shapesTouch(tool.getShape(), shape.getShape());
        }
        touched += own ? 1 : 0;
    }
    PartDesign::Body* other = nullptr;
    for (auto obj : feature->getDocument()->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        auto part = static_cast<PartDesign::Body*>(obj);
        if (part != body && Part::BodyBase::areStudioSiblings(body, part)
            && !PartDesign::Boolean::mergeOf(part) && toolTouches(feature, part, cache)) {
            other = part;
            ++touched;
        }
    }
    if (touched == 1 && own) {
        return move;  // Add, its own part the scope
    }
    move.toNewPart = !first;
    if (touched == 1) {
        move.into = other;  // Add, that part the scope
    }
    return move;
}

// Runs A-1's move, as commands in the open transaction: New part (PartDesign.newPartFrom), then
// Add to the touched part (PartDesign.addToPart). A move refused leaves the feature where it got
// to: a refused Add stays New
void runOpeningMove(const App::DocumentObjectT& featureT)
{
    auto feature = freecad_cast<PartDesign::FeatureAddSub*>(featureT.getObject());
    if (!feature) {
        return;
    }
    const OpeningMove move = openingMove(feature);
    if (!move.toNewPart && !move.into) {
        return;
    }
    App::DocumentObjectT intoT(move.into);
    App::DocumentObjectT fromT(PartDesign::Body::findBodyOf(feature));
    const std::string obj = Gui::Command::getObjectCmd(feature);
    Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
    if (move.toNewPart) {
        if (!newPartRefusal(feature).isEmpty()) {
            return;
        }
        Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.newPartFrom(%s)", obj.c_str());
        nameNewPart(PartDesign::Body::findBodyOf(feature), nullptr);
    }
    auto into = freecad_cast<PartDesign::Body*>(intoT.getObject());
    if (into && PartDesign::Body::addToPartRefusal(feature, into).empty()) {
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "PartDesign.addToPart(%s, %s)",
            obj.c_str(),
            Gui::Command::getObjectCmd(into).c_str()
        );
    }
    feature->recomputeFeature();
    // The part it left (when it had solids, it stays) shows its own result, as newPartMove's
    auto from = freecad_cast<PartDesign::Body*>(fromT.getObject());
    if (from && from != PartDesign::Body::findBodyOf(feature)) {
        from->recomputeFeature(/*recursive=*/true);
        showTipIfNoneShown(from);
    }
}
}  // namespace

void TaskResultParameters::applyOpeningOperation(App::DocumentObject* feature)
{
    if (!feature) {
        return;
    }
    try {
        runOpeningMove(App::DocumentObjectT(feature));
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

void TaskResultParameters::awaitOpeningOperation(App::DocumentObject* feature)
{
    if (hasOperationRow(feature) && !isOpeningAwaited(feature)) {
        openingAwaited.emplace_back(feature);
    }
}

void TaskResultParameters::profileTaken(App::DocumentObject* feature)
{
    if (!isOpeningAwaited(feature)) {
        return;
    }
    App::DocumentObjectT target(feature);
    auto addSub = freecad_cast<PartDesign::FeatureAddSub*>(feature);
    // A tool not made yet (a Revolve still waiting for its axis, a Sweep for its path, a profile
    // that failed) decides nothing: the pick that makes it does (FreeCAD-CH ops#640)
    if (!addSub || addSub->AddSubShape.getShape().isNull()) {
        return;
    }
    // The first tool decides it, once: the field's next pick is the user's
    forgetOpeningAwaited(target);
    const OpeningMove move = openingMove(addSub);
    if (!move.toNewPart && !move.into) {
        return;
    }
    // The move restarts the edit, which closes the dialog whose field took the pick: after the
    // pick, from the event loop, while the dialog is still open in its transaction
    Gui::TaskView::TaskDialog* dialog = Gui::Control().activeDialog(feature->getDocument());
    QWidget* box = nullptr;
    if (dialog) {
        for (QWidget* widget : dialog->getDialogContent()) {
            if (qobject_cast<TaskResultParameters*>(widget)) {
                box = widget;
            }
        }
    }
    if (!box) {
        return;
    }
    QPointer<QWidget> boxPtr(box);
    QTimer::singleShot(0, qApp, [boxPtr, target]() {
        if (!isEditing(boxPtr.data(), target)) {
            return;
        }
        restartEdit(target, [&target]() { runOpeningMove(target); });
    });
}

void TaskResultParameters::addOperationRow()
{
    auto feature = getObject<PartDesign::FeatureAddSub>();
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    operation = operationKey(feature);
    const bool isNew = operation == QStringLiteral("new");
    // Its part's first solid, not New: its merge scope is empty (or Merge with all), so no part
    const bool firstWithScope = !isNew && isFirstSolid(feature);
    // A new part's feature names the part it would go to; the others their own
    PartDesign::Body* target = isNew ? operationTarget(feature) : firstWithScope ? nullptr : body;
    // Onshape's words on every dialog (ops#640 round 6, J2/J9 N5); the part they act on is in
    // the tooltip (a refused row's tooltip says why instead)
    combo->addItem(tr("New"), QStringLiteral("new"));
    combo->addItem(tr("Add"), QStringLiteral("add"));
    combo->addItem(tr("Remove"), QStringLiteral("Subtraction"));
    combo->addItem(tr("Intersect"), QStringLiteral("Common"));
    if (target) {
        const QString part = partLabel(target);
        const QString tips[] = {
            QString(),
            tr("Add to %1").arg(part),
            tr("Remove from %1").arg(part),
            tr("Intersect with %1").arg(part),
        };
        for (int i = 1; i < 4; ++i) {
            combo->setItemData(i, tips[i], Qt::ToolTipRole);
            combo->setItemData(i, tips[i], PartTipRole);  // refuseOperations restores it
        }
    }
    combo->setCurrentIndex(combo->findData(operation));

    if (App::DocumentObject* primary = primaryOf(feature)) {
        combo->setEnabled(false);  // bound to the primary's
        addFollowsNote(primary);
        return;
    }
    if (isNew) {
        const QString why = addToPartRefusal(feature, target);
        for (const char* key : {"add", "Subtraction", "Common"}) {
            refuseRow(QString::fromLatin1(key), why);
        }
        return;  // a new part merges nothing (Onshape's New has no merge scope)
    }
    refuseOperations();
    if (!body || PartDesign::Boolean::mergeOf(body)) {
        return;
    }
    // Onshape's Add always has its merge scope (Merge with all, at least); a first solid's cut
    // picks its part there; another cut has the parts list, in a studio
    if (!isSubtractive(operation) || firstWithScope) {
        scopePickMoves = firstWithScope;
        addMergeList();
    }
    else if (hasStudioSiblings(body)) {
        addPartsList();
    }
}

namespace
{
// FreeCAD-CH (ops#640 round 9, journeys J8 and J17): the greyed rows of the Result row and why, in
// the line under it (refusalNote), as the box's other notes: a greyed row's tooltip alone went
// unseen. Rows refused for one reason share a line: "Can't switch to Add, Remove or Intersect:
// 'Mirrored' uses 'BossB'"
void showRefusals(QWidget* box, QComboBox* combo)
{
    auto note = box->findChild<QLabel*>(QStringLiteral("refusalNote"));
    auto model = qobject_cast<QStandardItemModel*>(combo->model());
    if (!note || !model) {
        return;
    }
    std::vector<std::pair<QString, QStringList>> reasons;
    for (int i = 0; i < combo->count(); ++i) {
        const QString why = combo->itemData(i, Qt::ToolTipRole).toString();
        if (model->item(i)->isEnabled() || why.isEmpty()) {
            continue;
        }
        auto found = std::ranges::find_if(reasons, [&why](const auto& reason) {
            return reason.first == why;
        });
        if (found == reasons.end()) {
            reasons.emplace_back(why, QStringList {combo->itemText(i)});
        }
        else {
            found->second << combo->itemText(i);
        }
    }
    QStringList lines;
    for (const auto& [why, rows] : reasons) {
        const QString list = rows.size() < 2
            ? rows.first()
            : TaskResultParameters::tr("%1 or %2")
                  .arg(rows.mid(0, rows.size() - 1).join(QStringLiteral(", ")), rows.last());
        lines << TaskResultParameters::tr("Can't switch to %1: %2").arg(list, why);
    }
    note->setText(lines.join(QLatin1Char('\n')));
    note->setVisible(!lines.isEmpty());
}
}  // namespace

void TaskResultParameters::refuseRow(const QString& key, const QString& why)
{
    const int index = combo->findData(key);
    if (why.isEmpty() || index < 0 || index == combo->currentIndex()) {
        return;
    }
    if (auto model = qobject_cast<QStandardItemModel*>(combo->model())) {
        model->item(index)->setEnabled(false);
    }
    combo->setItemData(index, why, Qt::ToolTipRole);
    showRefusals(this, combo);
}

void TaskResultParameters::refuseOperations()
{
    auto feature = getObject<PartDesign::FeatureAddSub>();
    if (!feature || !combo || primaryOf(feature) || operation == QStringLiteral("new")) {
        return;
    }
    // Every row offered, then the refusals as the document stands
    auto model = qobject_cast<QStandardItemModel*>(combo->model());
    for (int i = 0; i < combo->count(); ++i) {
        if (model) {
            model->item(i)->setEnabled(true);
        }
        combo->setItemData(i, combo->itemData(i, PartTipRole), Qt::ToolTipRole);
    }
    showRefusals(this, combo);  // none yet; refuseRow shows each
    PartDesign::Boolean* merge = mergeAfter(feature);
    // The whole merge scope unticked (Merge with all off): the Merge goes at OK, so what builds on
    // it builds on the feature, and the rows are refused as without it (ops#640 round 5)
    bool unmerged = merge && mergeParts && !(mergeWithAll && mergeWithAll->isChecked());
    for (int i = 0; unmerged && i < mergeParts->count(); ++i) {
        unmerged = mergeParts->item(i)->checkState() != Qt::Checked;
    }
    // New part: newPartFrom's rule, what follows the feature going along (ops#640 round 5); a cut
    // through other parts drops them first, unless something uses one. A first solid stays where
    // it is
    const bool firstWithScope = isFirstSolid(feature);
    if (!firstWithScope) {
        QString why;
        for (PartDesign::FeatureAddSub* sibling : feature->getSiblings()) {
            if (App::DocumentObject* user = PartDesign::FeatureAddSub::siblingUser(sibling)) {
                why = tr("Its cut %1 is used by %2").arg(partLabel(sibling), partLabel(user));
                break;
            }
        }
        refuseRow(QStringLiteral("new"), why.isEmpty() ? newPartRefusal(feature, unmerged) : why);
    }
    // Remove and Intersect drop the Merge (hands-on B5-4), unless something builds on it
    if (merge && !unmerged) {
        QString why = QString::fromStdString(PartDesign::mergeGoesRefusal(feature));
        if (!why.isEmpty()) {
            why[0] = why[0].toUpper();
        }
        refuseRow(QStringLiteral("Subtraction"), why);
        refuseRow(QStringLiteral("Common"), why);
    }
    for (PartDesign::FeatureAddSub* sibling : feature->getSiblings()) {
        if (App::DocumentObject* user = PartDesign::FeatureAddSub::siblingUser(sibling)) {
            refuseRow(
                QStringLiteral("add"),
                tr("Its cut %1 is used by %2").arg(partLabel(sibling), partLabel(user))
            );
        }
    }
}

void TaskResultParameters::addPartsList()
{
    auto feature = getObject<PartDesign::FeatureAddSub>();
    PartDesign::Body* body = PartDesign::Body::findBodyOf(feature);
    if (inListedStudio(body)) {
        return;  // R0 lite: the studio's owners act on other parts
    }
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
    if (inListedStudio(body)) {
        return;  // R0 lite: the studio's owners act on other parts
    }
    touchCache = std::make_shared<TouchCache>();
    PartDesign::Boolean* merge = mergeAfter(feature);
    const bool adding =
        feature->getBooleanOperation() == PartDesign::FeatureAddSub::BooleanOperation::Union;
    // Onshape's Merge with all (ops#640 rank 1): an Add's, stored on the feature
    if (adding) {
        mergeWithAll = new QCheckBox(tr("Merge with all"), this);
        mergeWithAll->setObjectName(QStringLiteral("mergeWithAll"));
        mergeWithAll->setToolTip(tr("Merges every part the tool touches, as they are at OK"));
        mergeWithAllWas = feature->MergeWithAll.getValue();
        mergeWithAll->setChecked(mergeWithAllWas);
        groupLayout()->addWidget(mergeWithAll);
        connect(mergeWithAll, &QCheckBox::toggled, this, &TaskResultParameters::onMergeWithAll);
    }
    // The studio's other parts, those the tool touches first; a part merged elsewhere isn't one,
    // one this feature merges is, ticked (unticked, OK unmerges it)
    std::vector<std::pair<PartDesign::Body*, bool>> others;
    for (auto obj : feature->getDocument()->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        auto other = static_cast<PartDesign::Body*>(obj);
        PartDesign::Boolean* mergedBy = PartDesign::Boolean::mergeOf(other);
        if (other != body && Part::BodyBase::areStudioSiblings(body, other)
            && (!mergedBy || (merge && mergedBy == merge))) {
            others.emplace_back(other, toolTouches(feature, other, *touchCache));
        }
    }
    if (others.empty()) {
        return;
    }
    std::ranges::stable_partition(others, [](const auto& other) { return other.second; });

    mergeLabel = new QLabel(tr("Merge scope:"), this);
    groupLayout()->addWidget(mergeLabel);
    mergeParts = new QListWidget(this);
    mergeParts->setObjectName(QStringLiteral("mergeList"));
    for (const auto& [other, touches] : others) {
        auto item = new QListWidgetItem(touchText(other, touches), mergeParts);
        item->setData(Qt::UserRole, QString::fromLatin1(other->getNameInDocument()));
        item->setData(Qt::UserRole + 1, touches);
        const bool merged = merge && PartDesign::Boolean::mergeOf(other) == merge;
        item->setCheckState(merged ? Qt::Checked : Qt::Unchecked);
        Qt::ItemFlags flags = Qt::ItemIsUserCheckable | Qt::ItemIsEnabled;
        QString why;
        if (scopePickMoves && !merged) {
            why = addToPartRefusal(feature, other);  // the tick moves the feature there
        }
        else if (!merged && other->isRolledBack()) {
            why = tr("Roll %1 to the end first").arg(partLabel(other));  // a frozen shape (2.6)
        }
        if (!why.isEmpty()) {
            flags &= ~Qt::ItemIsEnabled;
            item->setToolTip(why);
        }
        item->setFlags(flags);
    }
    groupLayout()->addWidget(mergeParts);
    mergeNote = new QLabel(this);
    mergeNote->setObjectName(QStringLiteral("mergeNote"));
    mergeNote->setWordWrap(true);
    groupLayout()->addWidget(mergeNote);
    connect(mergeParts, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
        // A first solid's tick moves it into the part: its scope is that part (Add from New)
        auto feature = getObject<PartDesign::FeatureAddSub>();
        if (scopePickMoves && item && feature && item->checkState() == Qt::Checked) {
            auto merge = mergeAfter(feature);
            App::DocumentObject* other =
                feature->getDocument()->getObject(item->data(Qt::UserRole).toString().toLatin1());
            if (other && !(merge && PartDesign::Boolean::mergeOf(other) == merge)) {
                onScopePicked(item->data(Qt::UserRole).toString());
                return;
            }
        }
        updateMergeNotes();
        // Unticking the whole scope frees the rows its Merge held, at once (ops#640 round 5)
        if (hasOperationRow(feature)) {
            refuseOperations();
        }
    });
    // Onshape shows the scope only while Merge with all is off
    const bool all = mergeWithAll && mergeWithAll->isChecked();
    mergeLabel->setVisible(!all);
    mergeParts->setVisible(!all);
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
    if (!mergeParts || !mergeNote) {
        return;
    }
    // With Merge with all, every touching part merges: no line
    const bool all = mergeWithAll && mergeWithAll->isChecked();
    QStringList touching;
    for (int i = 0; i < mergeParts->count() && !all; ++i) {
        QListWidgetItem* item = mergeParts->item(i);
        App::DocumentObject* other =
            getObject()->getDocument()->getObject(item->data(Qt::UserRole).toString().toLatin1());
        if (other && item->checkState() != Qt::Checked && item->data(Qt::UserRole + 1).toBool()) {
            touching << partLabel(other);
        }
    }
    // Overlapping parts are a normal state while modelling: a plain line, no warning (2.5); a
    // merge is a plain feature, so no banner either (P50, ops#640 rank 1)
    mergeNote->setText(
        touching.isEmpty()
            ? QString()
            : tr("Touches %1 (not merged)").arg(touching.join(QStringLiteral(", ")))
    );
    mergeNote->setVisible(!touching.isEmpty());
}

void TaskResultParameters::onMergeWithAll(bool checked)
{
    auto feature = getObject<PartDesign::FeatureAddSub>();
    if (!feature) {
        return;
    }
    if (mergeLabel) {
        mergeLabel->setVisible(!checked);
    }
    if (mergeParts) {
        mergeParts->setVisible(!checked);
    }
    updateMergeNotes();
    if (hasOperationRow(feature)) {
        refuseOperations();
    }
    // At once, as Onshape's: an Add whose scope is empty is healthy with it (a new part, R8) and
    // red without it (OK writes it again, for the macro)
    if (feature->MergeWithAll.getValue() != checked) {
        feature->MergeWithAll.setValue(checked);
        // Unticked on its part's first solid, an Add keeps its empty scope: not New (rank 3a)
        if (!checked && hasOperationRow(feature) && isFirstSolid(feature)
            && !feature->EmptyMergeScope.getValue()) {
            feature->EmptyMergeScope.setValue(true);
        }
        recomputeFeature();
    }
}

void TaskResultParameters::onScopePicked(const QString& part)
{
    if (mergeParts) {
        mergeParts->setEnabled(false);
    }
    // The edit restarts, which closes this dialog: after the signal, from the event loop
    App::DocumentObjectT target(getObject());
    QPointer<TaskResultParameters> box(this);
    QTimer::singleShot(0, qApp, [box, target, part]() {
        if (!isEditing(box.data(), target)) {
            return;
        }
        restartEdit(target, [&target, &part]() {
            auto feature = freecad_cast<PartDesign::FeatureAddSub*>(target.getObject());
            App::DocumentObject* other =
                feature ? feature->getDocument()->getObject(part.toLatin1().constData()) : nullptr;
            if (!feature || !other) {
                return;
            }
            const std::string obj = Gui::Command::getObjectCmd(feature);
            Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.addToPart(%s, %s)",
                obj.c_str(),
                Gui::Command::getObjectCmd(other).c_str()
            );
            if (feature->EmptyMergeScope.getValue()) {
                Gui::Command::doCommand(Gui::Command::Doc, "%s.EmptyMergeScope = False", obj.c_str());
            }
            feature->recomputeFeature();
        });
    });
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
    if (hasOperationRow(feature)) {
        if (what == operation) {
            return;
        }
        // The user's row: A-1's opening operation no longer waits for the profile
        forgetOpeningAwaited(featureT);
        // Add, a new part's feature touching no other part: its merge scope is empty, red, unless
        // Merge with all, which keeps it a new part (hands-on check R8; ops#640 H2 and rank 3a).
        // The restart shows the scope either way (switchOperation)
        // The edit restarts, which closes this dialog: after the signal, from the event loop
        combo->setEnabled(false);
        App::DocumentObjectT target(feature);
        QPointer<TaskResultParameters> box(this);
        const QString was = operation;
        // The merge scope as the box has it (the ticks; with Merge with all, what the Merge merges)
        std::optional<std::vector<App::DocumentObjectT>> scope;
        if (mergeParts && !(mergeWithAll && mergeWithAll->isChecked())) {
            scope.emplace();
            for (int i = 0; i < mergeParts->count(); ++i) {
                QListWidgetItem* item = mergeParts->item(i);
                App::DocumentObject* other = feature->getDocument()->getObject(
                    item->data(Qt::UserRole).toString().toLatin1().constData()
                );
                if (other && item->checkState() == Qt::Checked) {
                    scope->emplace_back(other);
                }
            }
        }
        QTimer::singleShot(0, qApp, [box, target, what, was, scope]() {
            if (!isEditing(box.data(), target)) {
                if (box) {
                    QSignalBlocker block(box->combo);
                    box->combo->setCurrentIndex(box->combo->findData(was));
                    box->combo->setEnabled(true);
                }
                return;
            }
            switchOperation(target, what, scope);
        });
        return;
    }
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
        && !primaryOf(feature) && !hasOperationRow(feature)) {
        FCMD_OBJ_CMD(feature, "Operation = '" << feature->Operation.getValueAsString() << "'");
    }
    // Merge with all, as the box has it (set at once while editing; here for the macro)
    const bool all = mergeWithAll && mergeWithAll->isChecked();
    if (feature && mergeWithAll && all != mergeWithAllWas) {
        FCMD_OBJ_CMD(feature, "MergeWithAll = " << (all ? "True" : "False"));
        // Unticked on a first solid, onMergeWithAll left its scope empty: the macro says so too
        if (!all && feature->EmptyMergeScope.getValue()) {
            FCMD_OBJ_CMD(feature, "EmptyMergeScope = True");
        }
    }
    // The merge scope (ops#640 rank 1): the ticked parts, or with Merge with all every part the
    // tool touches now (a snapshot), merged right after the feature (design 2.5); a part it
    // merged and is left out is a part again. Nothing is written when the scope is as it was
    if (feature && mergeParts) {
        App::Document* doc = feature->getDocument();
        PartDesign::Boolean* merge = mergeAfter(feature);
        std::vector<App::DocumentObject*> before;
        if (merge) {
            before = merge->mergedBodies();
        }
        std::vector<App::DocumentObject*> scope;
        std::string ticked;
        for (int i = 0; i < mergeParts->count(); ++i) {
            QListWidgetItem* item = mergeParts->item(i);
            auto other = freecad_cast<PartDesign::Body*>(
                doc->getObject(item->data(Qt::UserRole).toString().toLatin1())
            );
            if (!other) {
                continue;
            }
            const bool here = merge && PartDesign::Boolean::mergeOf(other) == merge;
            // A part merged elsewhere meanwhile (an OK that failed, tried again) is left out, as
            // is a rolled-back one that Merge with all would take
            if (PartDesign::Boolean::mergeOf(other) && !here) {
                continue;
            }
            const bool in = all
                ? (here || (!other->isRolledBack() && toolTouches(feature, other, *touchCache)))
                : item->checkState() == Qt::Checked;
            if (in) {
                scope.push_back(other);
                ticked += (ticked.empty() ? "" : ", ") + Gui::Command::getObjectCmd(other);
            }
        }
        auto same = [](std::vector<App::DocumentObject*> one, std::vector<App::DocumentObject*> other) {
            std::ranges::sort(one);
            std::ranges::sort(other);
            return one == other;
        };
        if (!same(scope, before)) {
            Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.setMergeScope(%s, [%s])",
                Gui::Command::getObjectCmd(feature).c_str(),
                ticked.c_str()
            );
            // The merged material shows: the Merge, the feature's result with the merged parts
            if (PartDesign::Boolean* made = mergeAfter(feature)) {
                Gui::cmdAppObjectShow(made);
            }
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
namespace
{
// The features a command made for the dialog it opens next (TaskDlgFeatureParameters::hasInput)
std::vector<App::DocumentObjectT> createdForDialog;
// The field the dialog opened next arms first (TaskDlgFeatureParameters::armOnOpen)
std::string armOnOpenProperty;

// A property the user gives (a value, a link, a choice): not a result, not the view's
bool isInputProperty(const App::Property* prop)
{
    if (!prop || (prop->getType() & (App::Prop_Output | App::Prop_Transient)) != 0
        || prop->isDerivedFrom<Part::PropertyPartShape>()) {
        return false;
    }
    // A profile-based feature writes its Placement at each compute; Visibility is the view's
    const char* name = prop->getName();
    return name && std::strcmp(name, "Placement") != 0 && std::strcmp(name, "Visibility") != 0;
}

// A property's value against its copy from the dialog's opening. Links compare by their targets
// and old-style subnames, whatever their scope: PropertyLinkBase::isSame also compares scopes, and
// the opening's Copy() keeps none (a Global or Child link's copy is Local)
bool sameValue(const App::Property& now, const App::Property& then)
{
    auto nowLink = dynamic_cast<const App::PropertyLinkBase*>(&now);
    auto thenLink = dynamic_cast<const App::PropertyLinkBase*>(&then);
    if (nowLink && thenLink) {
        std::vector<App::DocumentObject*> nowObjs;
        std::vector<App::DocumentObject*> thenObjs;
        std::vector<std::string> nowSubs;
        std::vector<std::string> thenSubs;
        nowLink->getLinks(nowObjs, /*all=*/true, &nowSubs, /*newStyle=*/false);
        thenLink->getLinks(thenObjs, /*all=*/true, &thenSubs, /*newStyle=*/false);
        return nowObjs == thenObjs && nowSubs == thenSubs;
    }
    // A Length's or an Angle's Copy() is a plain PropertyFloat (an IntegerConstraint's a plain
    // PropertyInteger), which isSame never takes for the same: compared by value
    auto nowFloat = dynamic_cast<const App::PropertyFloat*>(&now);
    auto thenFloat = dynamic_cast<const App::PropertyFloat*>(&then);
    if (nowFloat && thenFloat) {
        return nowFloat->getValue() == thenFloat->getValue();
    }
    auto nowInteger = dynamic_cast<const App::PropertyInteger*>(&now);
    auto thenInteger = dynamic_cast<const App::PropertyInteger*>(&then);
    if (nowInteger && thenInteger) {
        return nowInteger->getValue() == thenInteger->getValue();
    }
    return now.isSame(then);
}
}  // namespace

void TaskDlgFeatureParameters::noteCreated(App::DocumentObject* feature)
{
    std::erase_if(createdForDialog, [](const App::DocumentObjectT& made) {
        return !made.getObject();
    });
    if (feature && std::ranges::find(createdForDialog, App::DocumentObjectT(feature))
            == createdForDialog.end()) {
        createdForDialog.emplace_back(feature);
    }
}

void TaskDlgFeatureParameters::armOnOpen(const std::string& property)
{
    armOnOpenProperty = property;
}

bool TaskDlgFeatureParameters::hasInput() const
{
    App::DocumentObject* feature = getObject();
    if (!created || !feature) {
        return true;  // an edit, or a dialog this check can't tell: committed, as before
    }
    for (const ReferenceField* field : fieldGroup->fields()) {
        if (field && !field->entries().empty()) {
            return true;
        }
    }
    for (const auto& [name, value] : openingValues) {
        App::Property* now = feature->getPropertyByName(name.c_str());
        if (!now || !sameValue(*now, *value)) {
            return true;
        }
    }
    return false;
}

TaskDlgFeatureParameters::TaskDlgFeatureParameters(PartDesignGui::ViewProvider* vp)
    : preview(new TaskPreviewParameters(vp))
    , fieldGroup(new ReferenceFieldGroup(this))
    , vp(vp)
{
    assert(vp);
    // Made by the command for this dialog: hasInput() compares with the opening
    if (App::DocumentObject* made = vp->getObject()) {
        auto it = std::ranges::find(createdForDialog, App::DocumentObjectT(made));
        if (it != createdForDialog.end()) {
            createdForDialog.erase(it);
            created = true;
        }
    }
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

namespace
{
// A preview failure's warning (FeatureAddSub::updatePreviewShape) stays in the status bar after
// its dialog: it goes with the dialog (ops#640 round 6, J2)
void clearPreviewFailureStatus()
{
    Gui::MainWindow* main = Gui::getMainWindow();
    QStatusBar* bar = main ? main->statusBar() : nullptr;
    if (!bar) {
        return;
    }
    const QString prefix = QCoreApplication::translate(
                               "PartDesign::FeatureAddSub",
                               "Failure while computing removed volume preview: %1"
    )
                               .arg(QString())
                               .trimmed();
    if (!prefix.isEmpty() && bar->currentMessage().startsWith(prefix)) {
        bar->clearMessage();
        // The status colour and level too, as the message's own timeout does
        QMetaObject::invokeMethod(main, "clearStatus");
    }
}
}  // namespace

TaskDlgFeatureParameters::~TaskDlgFeatureParameters()
{
    detachDialogHistory(this);
    clearPreviewFailureStatus();
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
    fieldGroup->armFirstEmpty(std::exchange(armOnOpenProperty, std::string()));
    // A new feature's values as the dialog opens: what the user gives from here is its input
    if (App::DocumentObject* feature = created ? getObject() : nullptr) {
        std::vector<App::Property*> props;
        feature->getPropertyList(props);
        for (App::Property* prop : props) {
            // A property that can't copy itself can't tell a change: left out
            std::unique_ptr<App::Property> copy(isInputProperty(prop) ? prop->Copy() : nullptr);
            if (copy) {
                openingValues.emplace_back(prop->getName(), std::move(copy));
            }
        }
    }
    // The first parameter box's title is the feature's name, red while it is in error, as
    // Onshape's dialog title (ops#640 rank 36; renamed in it, polish P13: addTitleRename). The
    // operation row's box when it is on top (round 6, J9); a pattern's or a mirror's box, which
    // isn't a TaskFeatureParameters (round 6, J16 N1)
    for (QWidget* wgt : Content) {
        if (wgt != references) {
            if (qobject_cast<TaskResultParameters*>(wgt)) {
                titleBox = wgt;
            }
            break;
        }
    }
    forEachParameters([this](TaskFeatureParameters* param) {
        if (!titleBox && !qobject_cast<TaskResultParameters*>(param)) {
            titleBox = param;
        }
    });
    for (QWidget* wgt : Content) {
        if (!titleBox && qobject_cast<TaskTransformedParameters*>(wgt)) {
            titleBox = wgt;
        }
    }
    if (App::DocumentObject* feature = titleBox ? getObject() : nullptr) {
        App::DocumentObjectT featureT(feature);
        auto schedule = [this, featureT](const App::DocumentObject& obj) {
            if (&obj != featureT.getObject() || titlePending) {
                return;
            }
            titlePending = true;
            // Only while the feature is there: a Cancel that aborts its creation deletes it and
            // its view provider (vp, which getObject() reads) before the dialog goes (ops#654)
            QTimer::singleShot(0, this, [this, featureT]() {
                titlePending = false;
                if (featureT.getObject()) {
                    updateTitle();
                }
            });
        };
        titleChanged = feature->getDocument()->signalChangedObject.connect(
            [schedule](const App::DocumentObject& obj, const App::Property&) { schedule(obj); }
        );
        titleRecomputed = feature->getDocument()->signalRecomputedObject.connect(
            [schedule](const App::DocumentObject& obj) { schedule(obj); }
        );
        updateTitle();
    }
    flattenForOnshape();
    // A sibling follows its primary: only the Result box, with Unlink, is editable (ops#325)
    if (TaskResultParameters::primaryOf(getObject())) {
        forEachParameters([](TaskFeatureParameters* param) {
            if (!qobject_cast<TaskResultParameters*>(param)) {
                param->setEnabled(false);
            }
        });
    }
}

void TaskDlgFeatureParameters::modifyStandardButtons(QDialogButtonBox* box)
{
    okButton = box->button(QDialogButtonBox::Ok);
    App::DocumentObject* feature = getObject();
    if (!okButton || !feature || !feature->getDocument()) {
        return;
    }
    // A pick or a choice writes the feature: OK follows, after the change is done
    App::DocumentObjectT featureT(feature);
    requiredConnection = feature->getDocument()->signalChangedObject.connect(
        [this, featureT](const App::DocumentObject& obj, const App::Property&) {
            if (&obj == featureT.getObject()) {
                // The rollback of a Cancel changes the feature, then deletes it and its view
                // provider: the queued update must not read vp then (getObject()), FreeCAD-CH
                // ops#654 P5 (the Boolean dialog's intermittent "Illegal storage access")
                QTimer::singleShot(0, this, [this, featureT]() {
                    if (featureT.getObject()) {
                        updateOkButton();
                    }
                });
            }
        }
    );
    // Once the box is decorated: TaskEditControl::decorateButtons sets its tooltip after this call
    QTimer::singleShot(0, this, [this, featureT]() {
        if (featureT.getObject()) {
            updateOkButton();
        }
    });
}

void TaskDlgFeatureParameters::updateTitle()
{
    auto box = qobject_cast<Gui::TaskView::TaskBox*>(titleBox.data());
    App::DocumentObject* feature = getObject();
    if (!box || !feature || !feature->isAttachedToDocument()) {
        return;
    }
    const QString name = QString::fromUtf8(feature->Label.getValue());
    if (box->headerText() != name) {
        box->setHeaderText(name);
    }
    // The header's title button (QSint's ActionLabel); hovering shows the name, as Onshape's. In
    // error: Onshape's red and its tooltip, "<name> did not regenerate properly: <why>" (polish
    // P13, PL3a)
    const bool invalid = !feature->isValid();
    const QString tip = invalid
        ? tr("%1 did not regenerate properly: %2")
              .arg(name, QString::fromUtf8(feature->getStatusString()))
        : name;
    for (QToolButton* title : box->findChildren<QToolButton*>()) {
        if (title->text() == name) {
            title->setStyleSheet(invalid ? QStringLiteral("color: #AA252D;") : QString());
            title->setToolTip(tip);
            title->setProperty("featureInError", invalid);
        }
    }
}

namespace
{
// Hands a watched widget's events to a function (polish P13)
class EventHook: public QObject
{
public:
    EventHook(QObject* parent, std::function<bool(QObject*, QEvent*)> handler)
        : QObject(parent)
        , handler(std::move(handler))
    {}

protected:
    bool eventFilter(QObject* watched, QEvent* event) override
    {
        return handler(watched, event);
    }

private:
    std::function<bool(QObject*, QEvent*)> handler;
};
}  // namespace

void TaskDlgFeatureParameters::addTitleRename()
{
    auto box = qobject_cast<Gui::TaskView::TaskBox*>(titleBox.data());
    App::DocumentObject* feature = getObject();
    if (!box || !feature) {
        return;
    }
    const QString name = QString::fromUtf8(feature->Label.getValue());
    QToolButton* title = nullptr;
    for (QToolButton* button : box->findChildren<QToolButton*>()) {
        if (button->text() == name) {
            title = button;
            break;
        }
    }
    QWidget* header = title ? title->parentWidget() : nullptr;
    auto row = header ? qobject_cast<QHBoxLayout*>(header->layout()) : nullptr;
    if (!row) {
        return;
    }
    // Onshape: a pencil shown while the title row is hovered; it turns the title into a text box
    auto pencil = new QToolButton(header);
    pencil->setObjectName(QStringLiteral("FreeCAD-CH rename title"));
    pencil->setIcon(Gui::BitmapFactory().iconFromTheme("edit-edit"));
    pencil->setAutoRaise(true);
    pencil->setToolTip(tr("Rename"));
    pencil->hide();
    auto edit = new QLineEdit(header);
    edit->setObjectName(QStringLiteral("FreeCAD-CH rename box"));
    edit->hide();
    const int at = row->indexOf(title);
    row->insertWidget(at + 1, edit, 1);
    row->insertWidget(at + 1, pencil);

    App::DocumentObjectT featureT(feature);
    // Enter or leaving the box renames (the edit's transaction takes it: Cancel undoes it, and
    // OK counts it as a change); Esc only closes the box. An empty name keeps the old one
    auto finish = [title, edit, featureT](bool rename) {
        if (!edit->isVisible()) {  // hiding the focused box ends its editing a second time
            return;
        }
        edit->hide();
        title->show();
        App::DocumentObject* obj = featureT.getObject();
        const QString text = edit->text().trimmed();
        if (rename && obj && !text.isEmpty() && text != QString::fromUtf8(obj->Label.getValue())) {
            obj->Label.setValue(text.toUtf8().constData());
        }
    };
    QObject::connect(pencil, &QToolButton::clicked, edit, [title, pencil, edit, featureT]() {
        App::DocumentObject* obj = featureT.getObject();
        if (!obj) {
            return;
        }
        edit->setText(QString::fromUtf8(obj->Label.getValue()));
        title->hide();
        pencil->hide();
        edit->show();
        edit->setFocus(Qt::OtherFocusReason);
        edit->selectAll();
    });
    QObject::connect(edit, &QLineEdit::editingFinished, edit, [finish]() { finish(true); });
    edit->installEventFilter(new EventHook(edit, [finish](QObject*, QEvent* event) {
        auto key = event->type() == QEvent::ShortcutOverride || event->type() == QEvent::KeyPress
            ? static_cast<QKeyEvent*>(event)
            : nullptr;
        const bool enter = key && (key->key() == Qt::Key_Return || key->key() == Qt::Key_Enter);
        if (!key || (!enter && key->key() != Qt::Key_Escape)) {
            return false;
        }
        // The dialog's own Esc (Cancel) and Enter (OK) don't take it: QLineEdit passes Enter on
        event->accept();
        if (event->type() == QEvent::KeyPress) {
            finish(enter);
        }
        return true;
    }));
    header->installEventFilter(new EventHook(header, [pencil, edit](QObject*, QEvent* event) {
        if (event->type() == QEvent::Enter && !edit->isVisible()) {
            pencil->show();
        }
        else if (event->type() == QEvent::Leave) {
            pencil->hide();
        }
        return false;
    }));
}

void TaskDlgFeatureParameters::flattenForOnshape()
{
    if (!Gui::ForkKeymap::isOnshape()) {
        return;
    }
    for (QWidget* wgt : Content) {
        auto box = qobject_cast<Gui::TaskView::TaskBox*>(wgt);
        if (!box) {
            continue;
        }
        if (wgt == titleBox.data()) {
            box->setExpandable(false);
        }
        else {
            box->setHeader(false);
        }
    }
    if (preview) {
        preview->setOnshapeLayout(hasLaterFeature());
    }
    addTitleRename();
}

bool TaskDlgFeatureParameters::hasLaterFeature() const
{
    App::DocumentObject* feature = getObject();
    PartDesign::Body* body = feature ? PartDesign::Body::findBodyOf(feature) : nullptr;
    if (!body) {
        return false;
    }
    const std::vector<App::DocumentObject*>& members = body->Group.getValues();
    auto it = std::find(members.begin(), members.end(), feature);
    return it != members.end() && std::next(it) != members.end();
}

void TaskDlgFeatureParameters::updateOkButton()
{
    if (!okButton || !getObject()) {
        return;
    }
    // A hint, not a block: Onshape's check stays enabled with a required selection missing, and
    // Enter or OK commits the feature in error (hands-on check R6, ops#640 H1; F7's path)
    const QString missing = missingRequired();
    if (missing.isEmpty()) {
        if (showingHint) {
            okButton->setToolTip(okToolTip);
            showingHint = false;
        }
        return;
    }
    if (!showingHint) {
        okToolTip = okButton->toolTip();
        showingHint = true;
    }
    okButton->setToolTip(missing);
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
    // FreeCAD-CH (ops#654 S4): a studio feature's own Result box, on top as an Extrude's
    if (QWidget* studioBox = makeStudioResultBox(vp)) {
        auto at = Content.begin();
        if (references && !Content.empty() && Content.front() == references) {
            ++at;
        }
        Content.insert(at, studioBox);
        return;
    }
    if (!TaskResultParameters::hasRows(getObject())) {
        return;
    }
    auto box = new TaskResultParameters(vp);
    // The operation row first, above the fields, as Onshape's Extrude, Revolve, Loft, Sweep and
    // Helix (ops#640 round 6, J9); below the references panel, which comes before any parameter
    if (hasOperationRow(getObject())) {
        auto at = Content.begin();
        if (references && !Content.empty() && Content.front() == references) {
            ++at;
        }
        Content.insert(at, box);
        return;
    }
    Content.push_back(box);
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
    // The Result box last, wherever it is shown (an operation row is on top, addResultBox): what
    // it writes follows the other boxes' values (a sibling's sync at OK)
    for (bool result : {false, true}) {
        for (QWidget* wgt : Content) {
            auto param = qobject_cast<TaskFeatureParameters*>(wgt);
            if (param && (qobject_cast<TaskResultParameters*>(wgt) != nullptr) == result) {
                fn(param);
            }
        }
    }
}

bool TaskDlgFeatureParameters::accept()
{
    App::DocumentObject* feature = getObject();
    // A required selection still missing doesn't hold the dialog: the feature is committed in
    // error below, as Onshape's check commits a Revolve with no axis (ops#640 H1)
    bool isUpdateBlocked = false;
    fieldGroup->disarm();
    if (references) {
        references->stopPick();
    }
    // The pieces' step (P6p), open while they are made: a refusal aborts it
    bool piecesStep = false;
    try {
        // Iterate over parameter dialogs and apply all parameters from them, the Result box last
        forEachParameters([&isUpdateBlocked](TaskFeatureParameters* param) {
            param->saveHistory();
            param->apply();
            isUpdateBlocked |= param->isUpdateBlocked();
        });
        // Make sure the feature is what we are expecting
        // Should be fine but you never know...
        if (!feature->isDerivedFrom<PartDesign::Feature>()) {
            throw Base::TypeError("Bad object processed in the feature dialog.");
        }

        // FreeCAD-CH (ops#654 S4): a studio feature's edit changes Bodies that don't use it (a
        // part left out of its scope loses its step): nothing touched is purged
        if (PartDesign::isStudioOwner(feature)) {
            // Its steps take its values at reconcile (Operation, Refine)
            std::string why;
            if (!PartDesign::StudioList::holding(feature)->reconcile(&why)) {
                throw Base::ValueError(why.empty() ? "The studio's list can't take the feature" : why);
            }
        }
        // FreeCAD-CH (ops#654 P6p): the OK of a studio feature, or of an in-Body pattern of a
        // listed part, is the command that makes its pieces and leftovers parts
        // (run once the edit has ended: during it the edited feature isn't recomputed)
        const bool makesPieces = PartDesign::isStudioOwner(feature)
            || (feature->isDerivedFrom<PartDesign::Transformed>()
                && PartDesign::StudioList::holding(feature));
        // Whether it made or deleted a part: the Bodies themselves, not their count (one record
        // deleted and one piece made leave it equal: review prline-b5-r1 T3). A refusal throws
        auto makePieces = [feature]() {
            App::Document* document = feature->getDocument();
            auto bodies = [document]() {
                std::set<std::string> names;
                for (auto obj : document->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
                    names.insert(obj->getNameInDocument());
                }
                return names;
            };
            const auto before = bodies();
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "import PartDesign\nPartDesign.studioMakePieces(%s)",
                Gui::Command::getObjectCmd(feature).c_str()
            );
            return bodies() != before;
        };
        // A feature still touched (a value written outside the panel while it was open: the
        // property editor, a macro, an expression) was not computed with it: recompute it, or
        // the purge below keeps its stale result and error (ops#640 F3)
        const bool stale = feature->isTouched() || feature->mustExecute() > 0;
        if (isUpdateBlocked || stale || PartDesign::isStudioOwner(feature)) {
            Gui::cmdAppDocument(feature, "recompute()");
        }
        else {
            // object was already computed, nothing more to do with it...
            Gui::cmdAppDocument(feature, "purgeTouched()");

            // ...but touch parents to signal the change...
            for (auto obj : feature->getInList()) {
                obj->touch();
            }
            // ...and recompute them
            Gui::cmdAppDocument(feature->getDocument(), "recompute()");
        }

        // A feature in error is committed as it is, as Onshape's check does: it stays red in
        // the lists, with its message, to be repaired later (F7 of the blind test, ops#640). A
        // failed solid passes its base through (registerFailureContinuation), so its part keeps
        // showing what it had
        if (!feature->isValid()) {
            Base::Console().warning(
                "%s: %s\n",
                feature->Label.getValue(),
                feature->getStatusString()
            );
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

        // FreeCAD-CH (ops#640): an OK that changed nothing leaves no step, as Cancel (Onshape),
        // also when App's no-op rule can't tell (a link picked and undone)
        if (dialogLeftUnchanged(feature->getDocument())) {
            App::Document* document = feature->getDocument();
            endDialogHistory(document);
            document->abortTransaction();
            Gui::cmdAppDocument(document, "recompute()");
            Gui::cmdGuiDocument(document, "resetEdit()");
            // An unchanged OK of a feature whose pieces aren't parts yet makes them (P6p): its
            // message says to press OK. A step of its own, only when it made a part
            if (makesPieces) {
                document->openTransaction(QT_TRANSLATE_NOOP("Command", "Make pieces parts"));
                piecesStep = true;
                if (makePieces()) {
                    document->commitTransaction();
                }
                else {
                    document->abortTransaction();
                }
            }
            return true;
        }

        Gui::cmdGuiDocument(feature, "resetEdit()");
        if (makesPieces) {
            // The edit's step may be closed by now: the pieces then make a step of their own
            App::Document* document = feature->getDocument();
            const bool own = !document->hasPendingTransaction();
            if (own) {
                document->openTransaction(QT_TRANSLATE_NOOP("Command", "Make pieces parts"));
            }
            // Not its own, the edit's step: then a refusal fails the OK as a whole
            piecesStep = true;
            const bool made = makePieces();
            if (own && made) {
                document->commitTransaction();
            }
            else if (own) {
                document->abortTransaction();
            }
        }
        // FreeCAD-CH (ops#640, journey J18, F4): the edit's end shows the feature it edited,
        // which hid its Merge again, so a merged part vanished from the view while the merging
        // extrude was the last feature. The part's result is the Merge when it is the tip
        if (PartDesign::Boolean* merge = PartDesign::Boolean::scopeMerge(feature)) {
            PartDesign::Body* body = PartDesign::Body::findBodyOf(merge);
            if (body && body->Tip.getValue() == merge) {
                Gui::cmdAppObjectShow(merge);
                Gui::cmdAppObjectHide(feature);  // as a new tip hides the feature before it
            }
        }
        feature->getDocument()->commitTransaction();
        endDialogHistory(feature->getDocument());  // FreeCAD-CH (ops#640)
    }
    catch (const Base::Exception& e) {
        // A refusal of the pieces' command (P6p): its step goes, with what it changed (review
        // prline-b5-r1 T3)
        if (App::Document* document = feature->getDocument();
            piecesStep && document && document->hasPendingTransaction()) {
            document->abortTransaction();
            endDialogHistory(document);
            Gui::cmdAppDocument(document, "recompute()");
        }
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
