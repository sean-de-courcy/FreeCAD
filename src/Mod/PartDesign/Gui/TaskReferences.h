// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#pragma once

#include <functional>
#include <string>
#include <vector>

#include <App/DocumentObserver.h>
#include <App/ReferenceRepair.h>
#include <Gui/Selection/Selection.h>
#include <Gui/TaskView/TaskDialog.h>
#include <Gui/TaskView/TaskView.h>

class QLabel;
class QPushButton;
class QTreeWidget;
class QTreeWidgetItem;

namespace PartDesignGui
{

/** The references of one object that need the user: guessed, resolved by geometry, partly
 * resolved or broken (FreeCAD-CH, ops#127; design note N2 section 6).
 *
 * One row per reference (`App::referenceRows()`), with its candidates or alternatives below it.
 * Selecting a row or a candidate highlights the element in the 3D view, showing its object if the
 * body hides it. The buttons call the App functions on the current row: Accept
 * (`App.acceptReference`), Use this one (`App.repairReference` with the current candidate), Mark
 * broken (`App.markReferenceBroken`) and Re-pick (`App.repairReference(..., force=True)` with an
 * element picked in the 3D view on the reference's object). Each runs as a command in the open
 * transaction and recomputes the document.
 *
 * Shown on its own (TaskDlgReferences, the tree's "Repair references…") or at the top of the
 * feature's own task panel (TaskDlgFeatureParameters). Before it changes the selection, the
 * dialog's selection modes end (selectionTaken()) and its other panels don't hear of the change.
 * It lists the rows again when the owner's links change or an object goes.
 */
class TaskReferences: public Gui::TaskView::TaskBox,
                      public Gui::SelectionObserver,
                      public App::DocumentObserver
{
    Q_OBJECT

public:
    explicit TaskReferences(App::DocumentObject* owner, QWidget* parent = nullptr);
    ~TaskReferences() override;

    /// Whether \a obj has a reference the panel would list.
    static bool hasRows(const App::DocumentObject* obj);

    /// Lists the owner's references again, keeping the current row where it still is, and
    /// highlights it if \a highlightCurrent.
    void refresh(bool highlightCurrent = true);

    /// The buttons' actions, on the current row (Use this one: the current candidate). False if
    /// there is nothing to do or the call failed (the reason is shown in the header).
    bool acceptCurrent();
    bool useCurrent();
    bool markCurrentBroken();
    /// Re-pick: the next element picked on the current row's object replaces the reference.
    bool startPick();
    void stopPick();
    bool isPicking() const
    {
        return picking;
    }

    /// Called by the selection gate of a pick when it goes, whoever removed it.
    void pickGateGone();

Q_SIGNALS:
    /// A reference was written and the document recomputed.
    void referencesChanged();
    /// The panel is about to change the selection (a highlight or a re-pick): other selection
    /// modes of the dialog end.
    void selectionTaken();

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void slotChangedObject(const App::DocumentObject& obj, const App::Property& prop) override;
    void slotRecomputedObject(const App::DocumentObject& obj) override;
    void slotDeletedObject(const App::DocumentObject& obj) override;
    void slotDeletedDocument(const App::Document& doc) override;
    /// Lists the rows again once the current event is done.
    void scheduleRefresh();
    void onCurrentItemChanged();
    void onPickToggled(bool checked);
    void updateButtons();
    void showMessage(const QString& text, bool error);

    /// The row an item belongs to (a candidate's parent), or null / -1.
    int rowIndexOf(const QTreeWidgetItem* item) const;
    const App::ReferenceRow* rowOf(const QTreeWidgetItem* item) const;
    /// The object row \a r's element lives on (the linked object, or the sub-object its path
    /// names); null when it is gone.
    App::DocumentObject* targetOf(int r) const;
    /// Runs \a change on the selection: first selectionTaken(), and the dialog's other panels
    /// don't hear of it.
    void changeSelection(const std::function<void()>& change);
    void highlight(const QTreeWidgetItem* item);
    /// Removes the panel's highlight from the selection, if it is still there.
    void clearHighlight();
    void showTarget(App::DocumentObject* target);
    void restoreVisibility();
    /// Runs \a command (Python, on the App functions), recomputes, and lists the rows again.
    bool run(const std::string& command);

    App::DocumentObjectT owner;
    std::vector<App::ReferenceRow> rows;
    /// Each row's linked object, by name: rows[r].obj may be gone.
    std::vector<App::DocumentObjectT> rowObjects;
    bool refreshPending = false;

    QLabel* header = nullptr;
    QLabel* message = nullptr;
    QTreeWidget* tree = nullptr;
    QPushButton* buttonAccept = nullptr;
    QPushButton* buttonUse = nullptr;
    QPushButton* buttonBroken = nullptr;
    QPushButton* buttonPick = nullptr;

    bool picking = false;
    bool selecting = false;
    /// The reference a pick replaces.
    std::string pickProperty;
    int pickIndex = -1;
    /// What showTarget() changed: the target it showed, and the feature it hid for it.
    App::DocumentObjectT shownTarget;
    App::DocumentObjectT hiddenFeature;
    /// The element highlight() selected.
    App::SubObjectT highlighted;
};

/// The References panel on its own, in a transaction: OK keeps the repairs, Cancel undoes them.
class TaskDlgReferences: public Gui::TaskView::TaskDialog
{
    Q_OBJECT

public:
    explicit TaskDlgReferences(App::DocumentObject* owner);
    ~TaskDlgReferences() override;

    bool accept() override;
    bool reject() override;

    TaskReferences* panel() const
    {
        return references;
    }

private:
    App::DocumentT document;
    TaskReferences* references;
};

}  // namespace PartDesignGui
