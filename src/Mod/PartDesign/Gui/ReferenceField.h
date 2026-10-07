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
#include <set>
#include <string>
#include <vector>

#include <QPointer>
#include <QWidget>

#include <fastsignals/signal.h>

#include <App/DocumentObserver.h>
#include <App/ReferenceRepair.h>
#include <Gui/Selection/Selection.h>

#include "EnumFlags.h"
#include "ReferenceActions.h"

class QAction;
class QLabel;
class QListWidget;
class QListWidgetItem;
class QMenu;

namespace App
{
class PropertyLinkSub;
}

namespace PartDesignGui
{

class ReferenceFieldGroup;

/** One reference property of a feature's dialog, as a list of entries (FreeCAD-CH, ops#150;
 * notes/reference-list-widget.md).
 *
 * Armed while it is the dialog's active field: it arms when it gets the focus (a click on it, or
 * Tab) and stays armed while the focus goes to the 3D view, the tree or another window, where the
 * picks come from. While it is armed, its gate lets through only what it takes, its target is
 * shown, and its entries are coloured on the target (the current one in a second colour, never
 * through the selection). A pick of an element that is in the list removes it, one that isn't
 * adds it. Esc, another input of the dialog, the References panel's selection and a gate put in
 * its place disarm it.
 *
 * Each entry shows its state: exact, guessed (yellow) or broken (red), from the owner's slots and
 * reference rows (App::ReferenceReport::slotsOf, App::referenceRows). Its context menu has Remove
 * and the References panel's actions (ReferenceActions): Accept guess, Use (the ranked candidates
 * or alternatives), Mark broken, Re-pick, and Zoom to. Delete removes the selected entries;
 * Ctrl+Z / Ctrl+Y undo and redo the field's own changes.
 *
 * Each change goes through the panel's writer, which writes the property in the edit's
 * transaction and recomputes, as the panels do; the field then lists the property again.
 */
class ReferenceField: public QWidget, public Gui::SelectionObserver, public App::DocumentObserver
{
    Q_OBJECT
    Q_PROPERTY(bool armed READ isArmed WRITE setArmed NOTIFY armedChanged)
    Q_PROPERTY(QString state READ state)

public:
    /// What the field holds. W1 has Elements; the later kinds (notes 11.3) build on it.
    enum class Kind
    {
        Elements,  ///< a list of elements of the target (PropertyLinkSub)
    };
    struct Options
    {
        Kind kind = Kind::Elements;
        /// What the gate lets through (ReferenceSelection's flags).
        AllowSelectionFlags flags;
        /// The object picks come from; null: none (the field doesn't arm).
        std::function<App::DocumentObject*()> target;
        /// The field's own test, after the flags; \a why says what it refuses.
        std::function<bool(App::DocumentObject*, const char* sub, std::string& why)> accept;
        /// Also refuse what depends on the owner (NoDependentsSelection).
        bool noDependents = false;
        /// Armed when the dialog opens while it is empty.
        bool required = true;
        /// What it takes, for its label: "Edges, faces".
        QString kinds;
    };
    /// Writes the property: the target and the subs, in the stored style.
    using Writer =
        std::function<void(App::DocumentObject* obj, const std::vector<std::string>& subs)>;

    ReferenceField(App::DocumentObject* owner,
                   const char* property,
                   Options options,
                   Writer write,
                   QWidget* parent = nullptr);
    ~ReferenceField() override;

    bool isArmed() const
    {
        return armed;
    }
    /// Arms or disarms the field; arming disarms the group's other fields.
    void setArmed(bool on);
    /// The entries' subs, old-style (`?Edge5` when missing).
    std::vector<std::string> entries() const;
    /// Lists the property again, with the states.
    void reload();
    /// The list of entries (objectName "entries").
    QListWidget* list() const
    {
        return entryList;
    }
    const std::string& propertyName() const
    {
        return propertyNameStr;
    }
    bool isRequired() const
    {
        return options.required;
    }
    /// The owner's document, or null.
    App::Document* ownerDocument() const
    {
        auto own = owner();
        return own ? own->getDocument() : nullptr;
    }
    /// `exact`, `guessed` (an entry is) or `broken` (an entry is).
    QString state() const;

    void setGroup(ReferenceFieldGroup* group);
    /// A panel's action, shown in each entry's menu after the field's own, its shortcut taken
    /// while the field has the focus (Add All Edges).
    void addMenuAction(QAction* action);

    /// Removes the selected entries.
    void removeSelected();
    /// The field's own undo and redo of its changes.
    bool undo();
    bool redo();

    /// The field armed now, if any: the selection has one gate, so there is at most one.
    static ReferenceField* armedField();
    /// Called by the field's gate when it goes, whoever removed it.
    void gateGone();

Q_SIGNALS:
    void armedChanged(bool armed);
    /// The field is about to arm: its gate will replace the panel's, whose pick modes end now.
    void arming();
    /// The field wrote the property.
    void picked();

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;
    void changeEvent(QEvent* event) override;

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void slotChangedObject(const App::DocumentObject& obj, const App::Property& prop) override;
    void slotRecomputedObject(const App::DocumentObject& obj) override;
    void slotDeletedDocument(const App::Document& doc) override;
    void scheduleReload();

    App::DocumentObject* owner() const
    {
        return ownerT.getObject();
    }
    App::PropertyLinkSub* property() const;
    App::DocumentObject* target() const;
    /// The subs as the property stores them (mapped names kept).
    std::vector<std::string> storedSubs() const;
    /// Writes \a subs through the writer and lists them; \a undoable: a step of the field's undo.
    void write(const std::vector<std::string>& subs, bool undoable = true);
    void pick(App::DocumentObject* obj, const std::string& sub);

    void updateLook();
    void highlight(bool on, const std::string& extra = std::string());
    void zoomTo(const std::string& element);

    /// The reference row of the entry \a item (its slot index), or null.
    const App::ReferenceRow* rowOf(const QListWidgetItem* item) const;
    void showMenu(const QPoint& pos);
    QMenu* buildMenu(QListWidgetItem* item);
    void fillUseMenu(QMenu* menu, const App::ReferenceRow& row);
    void runAction(const std::string& command);
    void startRepick(int index);

    App::DocumentObjectT ownerT;
    std::string propertyNameStr;
    Options options;
    Writer writer;
    QPointer<ReferenceFieldGroup> group;

    QLabel* label = nullptr;
    QListWidget* entryList = nullptr;
    QLabel* hint = nullptr;
    QLabel* status = nullptr;
    std::vector<QPointer<QAction>> menuActions;

    bool armed = false;
    bool busy = false;
    bool reloadPending = false;
    Gui::SelectionGate* gate = nullptr;
    /// The slot a Re-pick replaces, or -1.
    int repickIndex = -1;
    /// The property's reference rows that need the user (App::referenceRows).
    std::vector<App::ReferenceRow> rows;
    std::vector<std::vector<std::string>> undoStack;
    std::vector<std::vector<std::string>> redoStack;
    /// The target shown while armed, and the one its entries are coloured on.
    TargetDisplay display;
    App::DocumentObjectT highlightedTarget;
    QString message;
};

/** The reference fields of one dialog (TaskDlgFeatureParameters): one armed at a time; a field
 * disarms when another input of the dialog takes the focus, when the References panel takes the
 * selection, and when the active document changes. The first empty required field arms when the
 * dialog opens.
 */
class ReferenceFieldGroup: public QObject
{
    Q_OBJECT

public:
    explicit ReferenceFieldGroup(QObject* parent = nullptr);
    ~ReferenceFieldGroup() override;

    void addField(ReferenceField* field);
    /// The dialog's panels: a focus there, outside the fields, disarms.
    void setPanels(const std::vector<QWidget*>& panels);
    std::vector<ReferenceField*> fields() const;
    /// The properties the fields show.
    std::set<std::string> properties() const;

    /// Arms the first empty required field (Q2), once the dialog shows.
    void armFirstEmpty();
    void disarm();
    /// Called by a field about to arm: the others disarm.
    void fieldArming(ReferenceField* field);

private:
    void onFocusChanged(QWidget* old, QWidget* now);

    std::vector<QPointer<ReferenceField>> fieldList;
    std::vector<QPointer<QWidget>> panels;
    fastsignals::scoped_connection activeDocumentConnection;
};

}  // namespace PartDesignGui
