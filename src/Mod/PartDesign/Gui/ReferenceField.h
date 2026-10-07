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
#include <App/ElementRecords.h>
#include <App/PropertyLinks.h>
#include <App/ReferenceReport.h>
#include <App/ReferenceRepair.h>
#include <Gui/Selection/Selection.h>

#include "EnumFlags.h"
#include "ReferenceActions.h"

class QAction;
class QComboBox;
class QKeyEvent;
class QLabel;
class QListWidget;
class QListWidgetItem;
class QMenu;


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
    /// What the field holds (notes 11.3 adds the later kinds).
    enum class Kind
    {
        /// A list of elements of the target (PropertyLinkSub or PropertyLinkSubList): a pick
        /// adds an element or takes it out.
        Elements,
        /// One reference (PropertyLinkSub, or a PropertyLinkSubList holding one object): an
        /// element of any object the gate takes, or a datum or origin plane or line, or with
        /// Options::wholeObject an object. A pick replaces it.
        SingleElement,
        /// A profile (PropertyLinkSub): an object, whole or by its elements (a sketch's regions
        /// or edges, faces of the solid before). A pick of another object, or of an object
        /// whole, replaces it; a pick of an element of the linked object adds it or takes it
        /// out, and taking out the last one leaves the object whole. Options::target is what
        /// shows while armed besides the object (the solid before), and may be null; the gate
        /// is Options::accept alone.
        Profile,
        /// A list of objects (PropertyLinkList: a pattern's Originals): a pick of an object, or
        /// of any element of it, adds the object or takes it out. Options::target is what shows
        /// while armed; the gate is Options::accept and noDependents. Written through an
        /// ObjectsWriter.
        Objects,
        /// An ordered list of sections (PropertyLinkSubList: a loft's or a pipe's Sections), each
        /// an object whole or one element of it, one per object. A pick of an object not listed
        /// appends it; the same object and element again takes it out; another element of a
        /// listed object replaces that section's (a sketch and one of its points). The order is
        /// changed by drag, the entry menu's Move up / Move down, or Alt+Up / Alt+Down, each one
        /// write. The gate is Options::accept and noDependents. Written through a SectionsWriter.
        Sections,
    };
    /// Turns a pick into what is written: the object and its subs (a copy of another body's
    /// element, a datum's coordinate system). False: nothing is written.
    using Resolver = std::function<
        bool(const Gui::SelectionChanges& msg, App::DocumentObject*& obj, std::vector<std::string>& subs)>;
    struct Options
    {
        Kind kind = Kind::Elements;
        /// What the gate lets through (ReferenceSelection's flags).
        AllowSelectionFlags flags;
        /// Elements: the object picks come from (null: the field doesn't arm). SingleElement:
        /// the object shown while armed, and the gate's support (null: the active body's).
        std::function<App::DocumentObject*()> target;
        /// The field's own test, after the flags; \a why says what it refuses.
        std::function<bool(App::DocumentObject*, const char* sub, std::string& why)> accept;
        /// Also refuse what depends on the owner (NoDependentsSelection).
        bool noDependents = false;
        /// Armed when the dialog opens while it is empty.
        bool required = true;
        /// SingleElement: Delete may clear it; an axis can't be empty (PR 159 review).
        bool removable = true;
        /// What it takes: "Edges, faces". The label, and the hint while armed.
        QString kinds;
        /// The label when it isn't the kinds: "Neutral plane".
        QString label;
        /// SingleElement: a pick takes the picked element's object, whole.
        bool wholeObject = false;
        /// SingleElement: what a pick writes; by default the picked object and element.
        Resolver resolve;
        /// Disarms after a pick: a hidden field the panel arms for one pick (the direction
        /// box's "Select reference").
        bool once = false;
        /// The References panel leaves out the property's rows while the field is enabled; a
        /// hidden field doesn't (they would be shown nowhere).
        bool covers = true;
        /// SingleElement: the gate is accept and noDependents alone, not ReferenceSelection's
        /// flags (a loft's profile: a sketch whole, a sketch point, a face).
        bool acceptOnly = false;
        /// Sections: whether the feature takes the sections in this order; \a why says what it
        /// refuses (a pipe takes a point only as the last section).
        std::function<bool(const std::vector<App::PropertyLinkSubList::SubSet>&, std::string& why)>
            checkSections;
    };
    /// Writes the property: the target and the subs, in the stored style.
    using Writer =
        std::function<void(App::DocumentObject* obj, const std::vector<std::string>& subs)>;
    /// Writes a list of objects (Kind::Objects).
    using ObjectsWriter = std::function<void(const std::vector<App::DocumentObject*>& objs)>;
    /// Writes a list of sections (Kind::Sections), in order.
    using SectionsWriter =
        std::function<void(const std::vector<App::PropertyLinkSubList::SubSet>& sections)>;

    ReferenceField(App::DocumentObject* owner,
                   const char* property,
                   Options options,
                   Writer write,
                   QWidget* parent = nullptr);
    /// A field of Kind::Objects.
    ReferenceField(App::DocumentObject* owner,
                   const char* property,
                   Options options,
                   ObjectsWriter write,
                   QWidget* parent = nullptr);
    /// A field of Kind::Sections.
    ReferenceField(App::DocumentObject* owner,
                   const char* property,
                   Options options,
                   SectionsWriter write,
                   QWidget* parent = nullptr);
    ~ReferenceField() override;

    bool isArmed() const
    {
        return armed;
    }
    /// Arms or disarms the field; arming disarms the group's other fields.
    void setArmed(bool on);
    /// The entries' subs, old-style (`?Edge5` when missing); a list of objects' names.
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
    /// Required or not now (a face field while its side goes up to a face).
    void setRequired(bool on)
    {
        options.required = on;
    }
    /// Whether the References panel leaves out the property's rows now: while the field is
    /// enabled and shown in its panel (a field hidden with its mode or side shows nothing).
    bool coversProperty() const;
    /// Takes \a placeholder's place in its parent's layout and deletes it (a `.ui` file's
    /// placeholder widget).
    void takePlaceOf(QWidget* placeholder);
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

    /// For the panel's writer: sets the property to \a obj and \a subs, the entries this change
    /// keeps with their mapped names, element records (guess, rejection) and fingerprints, which
    /// a plain setValue() drops (a missing element's candidates go with its mapped name). Called
    /// between the writer's transaction and its recompute.
    void assign(App::DocumentObject* obj, const std::vector<std::string>& subs);
    /// The same for a SectionsWriter: sets the property to \a sections, the kept sections with
    /// their records.
    void assign(const std::vector<App::PropertyLinkSubList::SubSet>& sections);
    /// Writes \a subs (stored style) as one step of the field's undo (Add All Edges).
    void replaceEntries(const std::vector<std::string>& subs);

    /// Removes the selected entries.
    void removeSelected();
    /// Kind::Sections: moves the current section up (\a step -1) or down (+1), one write.
    void moveCurrent(int step);
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
    /// The field was enabled or disabled: whether it shows its property's states changed.
    void coverageChanged();

protected:
    bool event(QEvent* event) override;
    bool eventFilter(QObject* watched, QEvent* event) override;
    void changeEvent(QEvent* event) override;

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void slotChangedObject(const App::DocumentObject& obj, const App::Property& prop) override;
    void slotRecomputedObject(const App::DocumentObject& obj) override;
    void slotDeletedDocument(const App::Document& doc) override;
    void scheduleReload();
    /// coverageChanged() once, after the event (a show or hide comes for each widget).
    void scheduleCoverageChanged();

    App::DocumentObject* owner() const
    {
        return ownerT.getObject();
    }
    /// The property: a PropertyLinkSub or a PropertyLinkSubList (a PropertyLinkList for
    /// Kind::Objects), or null.
    App::PropertyLinkBase* property() const;
    App::DocumentObject* target() const;
    /// The object the property links (a list's, when it links one).
    App::DocumentObject* linkedObject() const;
    bool isSingle() const
    {
        return options.kind == Kind::SingleElement;
    }
    bool isProfile() const
    {
        return options.kind == Kind::Profile;
    }
    bool isObjects() const
    {
        return options.kind == Kind::Objects;
    }
    bool isSections() const
    {
        return options.kind == Kind::Sections;
    }
    /// Kind::Sections: the sections as the property stores them (mapped names kept).
    std::vector<App::PropertyLinkSubList::SubSet> storedSections() const;
    /// Kind::Sections: writes \a sections (stored style) if the feature takes their order; the
    /// sections kept from the current value keep their records.
    void writeSections(const std::vector<App::PropertyLinkSubList::SubSet>& sections,
                       bool undoable = true);
    /// Kind::Sections: a pick appends a section, takes it out or changes its element.
    void pickSection(const Gui::SelectionChanges& msg);
    /// Kind::Sections: the entries dragged into another order are written in it.
    void sectionsDragged();
    /// Sets the property's records, fingerprints, `from`s and report to the pending value's.
    void assignPendingRecords(App::PropertyLinkBase* prop);
    /// Alt+Up or Alt+Down on a list of sections.
    bool isSectionMove(const QKeyEvent* ke) const;
    /// Kind::Objects: the objects the property lists.
    std::vector<App::DocumentObject*> linkedObjects() const;
    /// The object a list's entries are written on: the one the property links, the target
    /// while there is none.
    App::DocumentObject* listObject() const;
    /// The subs as the property stores them (mapped names kept).
    std::vector<std::string> storedSubs() const;
    /// The property's value as the field's undo keeps it: the object, and per sub its mapped
    /// name (the shadow: a missing element's is only there), element records, fingerprint and
    /// `from`.
    struct Snapshot
    {
        App::DocumentObjectT object;
        std::vector<std::string> subs;
        std::vector<App::PropertyLinkBase::ShadowSub> shadows;
        std::vector<App::ElementRecords> records;
        std::vector<std::string> fingerprints;
        std::vector<std::string> froms;
        /// The reference solver's report on the subs (a broken one's candidates), by index.
        std::vector<App::ReferenceReport::Entry> report;
        /// Kind::Objects: the objects listed. Kind::Sections: the object of each sub.
        std::vector<App::DocumentObjectT> objects;
    };
    Snapshot snapshot() const;
    /// Writes \a subs of the target through the writer and lists them; \a undoable: a step of
    /// the field's undo. The entries kept from the current value keep their records.
    void write(const std::vector<std::string>& subs, bool undoable = true);
    /// The same for \a obj's \a subs (a single entry, whose object changes).
    void write(App::DocumentObject* obj, const std::vector<std::string>& subs, bool undoable = true);
    /// Writes \a value with its records as they are (the field's undo and redo).
    void write(const Snapshot& value, bool undoable);
    /// Kind::Objects: writes \a objs (a step of the field's undo when \a undoable).
    void writeObjects(const std::vector<App::DocumentObject*>& objs, bool undoable = true);
    /// Kind::Objects: a pick adds \a obj, or takes it out when it is listed.
    void pickObject(App::DocumentObject* obj);
    /// Records the current value as a step of the field's undo.
    void pushUndo();
    void pick(App::DocumentObject* obj, const std::string& sub);
    /// A single entry's pick: replaces the entry.
    void pickSingle(const Gui::SelectionChanges& msg);
    /// A profile's pick: an element of the linked object toggles, anything else replaces it.
    void pickProfile(const Gui::SelectionChanges& msg);
    /// A profile's linked object whole again (its entries all go).
    void useWhole();
    /// A sketch without regions (MakeInternals off) gets them, in the edit's transaction.
    void makeRegions();
    /// A profile on a sketch that makes no regions.
    bool lacksRegions() const;
    /// A profile of a solid's faces whose last element \a stored would take out: refused, with
    /// a message (the solid whole is no profile).
    bool refusesLastElement(const std::vector<std::string>& stored);

    void updateLook();
    void highlight(bool on, const std::string& extra = std::string());
    /// Kind::Sections: each section coloured on its own object, a whole one all its edges.
    void highlightSections();
    /// Zooms to \a element of the field's object, or of \a obj when given.
    void zoomTo(const std::string& element, App::DocumentObject* obj = nullptr);

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
    ObjectsWriter objectsWriter;
    SectionsWriter sectionsWriter;
    QPointer<ReferenceFieldGroup> group;

    QLabel* label = nullptr;
    QListWidget* entryList = nullptr;
    QLabel* hint = nullptr;
    QLabel* status = nullptr;
    std::vector<QPointer<QAction>> menuActions;

    bool armed = false;
    bool busy = false;
    bool reloadPending = false;
    bool coveragePending = false;
    Gui::SelectionGate* gate = nullptr;
    /// The slot a Re-pick replaces, or -1.
    int repickIndex = -1;
    /// The property's reference rows that need the user (App::referenceRows).
    std::vector<App::ReferenceRow> rows;
    std::vector<Snapshot> undoStack;
    std::vector<Snapshot> redoStack;
    /// What assign() gives the written subs besides their names, while write() runs.
    Snapshot pending;
    bool valuePending = false;
    /// The target shown while armed, and the one its entries are coloured on.
    TargetDisplay display;
    /// The objects whose elements are coloured (a list of sections colours several).
    std::vector<App::DocumentObjectT> highlightedTargets;
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
    /// The properties the fields show: those of the enabled fields (a disabled field can't act on
    /// its entries, so the References panel lists them).
    std::set<std::string> properties() const;
    /// One of the dialog's panels.
    bool isPanel(const QWidget* widget) const;

    /// Arms the first empty required field (Q2), once the dialog shows.
    void armFirstEmpty();
    void disarm();
    /// Called by a field about to arm: the others disarm.
    void fieldArming(ReferenceField* field);

Q_SIGNALS:
    /// properties() changed: a field was enabled or disabled.
    void propertiesChanged();

private:
    void onFocusChanged(QWidget* old, QWidget* now);

    std::vector<QPointer<ReferenceField>> fieldList;
    std::vector<QPointer<QWidget>> panels;
    fastsignals::scoped_connection activeDocumentConnection;
};

/** An axis box (ops#150 W6; notes 11.3): a combo box of fixed choices ending in "Select
 * reference...", and under it a reference field (Kind::SingleElement) for a picked reference.
 * The field shows while the property links something that isn't a choice, with its state and
 * menu, so a guessed or broken axis is never a plain entry of the box (B19). "Select
 * reference..." shows the field and arms it; a choice disarms and hides it. A choice is written
 * through the same writer as the field's picks.
 */
class ReferenceCombo: public QObject
{
    Q_OBJECT

public:
    struct Choice
    {
        QString text;
        App::DocumentObject* object = nullptr;
        std::string sub;
    };

    /// \a combo and \a field are the panel's; \a property is the field's.
    ReferenceCombo(QComboBox* combo,
                   ReferenceField* field,
                   App::PropertyLinkSub* property,
                   ReferenceField::Writer write,
                   QObject* parent = nullptr);

    /// Fills the box: the choices, then \a selectReference ("Select reference...", in the
    /// panel's translation context).
    void setChoices(const std::vector<Choice>& choices, const QString& selectReference);
    /// Shows the property: its choice, or "Select reference..." with the field under the box.
    void refresh();
    ReferenceField* field() const
    {
        return referenceField;
    }

private:
    void onActivated(int index);
    /// The choice the property links, or -1.
    int currentChoice() const;

    QPointer<QComboBox> combo;
    QPointer<ReferenceField> referenceField;
    App::PropertyLinkSub* property;
    ReferenceField::Writer writer;
    std::vector<std::pair<App::DocumentObjectT, std::string>> choices;
};

}  // namespace PartDesignGui
