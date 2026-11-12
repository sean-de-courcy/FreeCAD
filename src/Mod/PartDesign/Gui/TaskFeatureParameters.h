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

#pragma once


#include <functional>
#include <memory>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>
#include <QPointer>
#include <fastsignals/connection.h>
#include <App/DocumentObserver.h>
#include <Gui/TaskView/TaskDialog.h>
#include <Gui/TaskView/TaskView.h>
#include <Gui/DocumentObserver.h>

#include "ViewProvider.h"

class QCheckBox;
class QComboBox;
class QDialogButtonBox;
class QLabel;
class QPushButton;
class QListWidget;
class QTimer;

namespace PartDesignGui
{

class Ui_TaskPreviewParameters;
class ReferenceField;
class ReferenceFieldGroup;
class TaskReferences;

class TaskPreviewParameters: public Gui::TaskView::TaskBox
{
    Q_OBJECT

public:
    explicit TaskPreviewParameters(ViewProvider* vp, QWidget* parent = nullptr);
    ~TaskPreviewParameters() override;
    /// FreeCAD-CH (ops#640 polish P5): Onshape's preview row, the overlay always on with its
    /// opacity as "Preview", and a Final box only when \a finalOffered (a later feature exists)
    void setOnshapeLayout(bool finalOffered);

public Q_SLOTS:
    void onShowPreviewChanged(bool show);
    void onShowFinalChanged(bool show);
    void onOpacityChanged(int percent);

private:
    ViewProvider* vp;
    std::unique_ptr<Ui_TaskPreviewParameters> ui;

    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/PartDesign/Preview"
    );
};

/// Convenience class to collect common methods for all SketchBased features
class TaskFeatureParameters: public Gui::TaskView::TaskBox, public Gui::DocumentObserver
{
    Q_OBJECT

public:
    TaskFeatureParameters(
        PartDesignGui::ViewProvider* vp,
        QWidget* parent,
        const std::string& pixmapname,
        const QString& parname
    );
    ~TaskFeatureParameters() override;

    /// save field history
    virtual void saveHistory()
    {}
    /// apply changes made in the parameters input to the model via commands
    virtual void apply()
    {}
    /// A reference was repaired in the dialog's References panel (ops#127): widgets that show a
    /// link property read it again, so that OK doesn't write the old value back.
    virtual void onReferencesRepaired()
    {}
    /// The References panel is about to change the selection (a highlight or a re-pick): the
    /// panel's own selection mode ends, so that it doesn't act on the panel's elements.
    virtual void onReferenceSelectionTaken()
    {}
    /// The panel's reference fields (ops#150): the dialog keeps one of them armed at a time, and
    /// its References panel leaves out what they show.
    virtual std::vector<ReferenceField*> referenceFields() const
    {
        return {};
    }

    void recomputeFeature();

    bool isUpdateBlocked() const
    {
        return blockUpdate;
    }

protected:
    void showDraggerHints();
    void hideDraggerHints();

protected Q_SLOTS:
    // TODO Add update view to all dialogs (2015-12-05, Fat-Zer)
    void onUpdateView(bool on);

private:
    /** Notifies when the object is about to be removed. */
    void slotDeletedObject(const Gui::ViewProviderDocumentObject& Obj) override;

protected:
    template<typename T = PartDesignGui::ViewProvider>
    T* getViewObject() const
    {
        static_assert(std::is_base_of<PartDesignGui::ViewProvider, T>::value, "Wrong template argument");
        return freecad_cast<T*>(vp);
    }

    template<typename T = App::DocumentObject>
    T* getObject() const
    {
        static_assert(std::is_base_of<App::DocumentObject, T>::value, "Wrong template argument");

        if (vp) {
            return vp->getObject<T>();
        }

        return nullptr;
    }

    Gui::Document* getGuiDocument() const
    {
        return vp ? vp->getDocument() : nullptr;
    }

    App::Document* getAppDocument() const
    {
        auto obj = getObject();
        return obj ? obj->getDocument() : nullptr;
    }

    bool& getUpdateBlockRef()
    {
        return blockUpdate;
    }

    void setUpdateBlocked(bool value)
    {
        blockUpdate = value;
    }

protected:
    PartDesignGui::ViewProvider* vp;

private:
    bool blockUpdate;
};

/** The Result box (ops#325, B+ Stage 1, notes/bplus-stage1-design.md 2.3): where the solid of an
 * additive or subtractive feature goes.
 * - Additive: Add to <its part>, or New part. New part moves the feature (and a sketch only it
 *   uses) to a new Body at once, inside the dialog's transaction (PartDesign.newPartFrom), so the
 *   preview is the real result; the edit restarts on the moved feature. Choosing Add to again
 *   moves it back and deletes the new Body. Cancel aborts it all with the transaction.
 * - Subtractive: Remove from, or Intersect with (Operation Common), in a studio with other parts.
 *   Row 2 lists the studio's other parts, those the tool touches first, one tick each; OK makes
 *   the ticked ones' siblings (PartDesign.makeSiblings, 2.4, session 3a). In a sibling's panel
 *   the box says whom it follows, offers Unlink, and the other boxes are read-only.
 * - Additive: the merge scope (Onshape's Extrude, ops#640 rank 1). Merge with all (MergeWithAll),
 *   and, while it is off, the Merge scope list of the studio's other parts, those the tool touches
 *   first, a part this feature merges already ticked. A touching part left out gets a plain line.
 *   OK sets the scope (PartDesign.setMergeScope): the ticked parts, or with Merge with all every
 *   part the tool touches, merged right after the feature in an accepted Merge; an unticked part
 *   is unmerged. On an Add, Remove or Intersect that is its part's first solid (its scope empty),
 *   ticking a part moves the feature into it (PartDesign.addToPart), as Add from New does.
 */
class TaskResultParameters: public TaskFeatureParameters
{
    Q_OBJECT

public:
    explicit TaskResultParameters(PartDesignGui::ViewProvider* vp, QWidget* parent = nullptr);
    ~TaskResultParameters() override;

    void apply() override;

    /// Whether the dialog of @p feature shows the box: New part can be offered (or was chosen),
    /// its Body is in a studio with other parts, or a subtractive feature intersects already
    static bool hasRows(App::DocumentObject* feature);
    /// The Body @p feature was in before this dialog moved it to a new part, or null
    static App::DocumentObject* movedFrom(const App::DocumentObject* feature);

    /// The primary that @p feature follows, or null (ops#325 3a)
    static App::DocumentObject* primaryOf(App::DocumentObject* feature);

    /// The user flipped @p feature's direction (Reversed) in its open dialog: from then on a
    /// switch between Add and Remove or Intersect keeps the user's direction, until the dialog
    /// closes; before it, the switch flips it (Onshape's Extrude, hands-on check R5, ops#640 H4)
    static void noteReversedTouched(App::DocumentObject* feature);

    /// Hands-on check A-1 (ops#640): a new Extrude opens as Onshape's. Add when its tool touches
    /// exactly one part, that part its scope (the feature moves into it, PartDesign.addToPart);
    /// else New, a part of its own (PartDesign.newPartFrom). A cut, a feature in error or one
    /// whose row or scope was chosen stays. For the command, before the dialog opens, inside
    /// its transaction
    static void applyOpeningOperation(App::DocumentObject* feature);
    /// The command made @p feature with no profile: its first profile (profileTaken) decides
    /// where it opens, unless a row is chosen first
    static void awaitOpeningOperation(App::DocumentObject* feature);
    /// The Profile field of @p feature's open dialog took a pick: a feature awaiting its opening
    /// operation gets it, once, in a restart of the edit after the pick
    static void profileTaken(App::DocumentObject* feature);

    /// The touch tests done, by the two shapes: the distance is slow on B-splines (design 2.3)
    struct TouchCache;

private:
    void onResultChanged(int index);
    /// A Pad's or a Pocket's rows: New part, Add, Remove, Intersect (ops#640)
    void addOperationRow();
    /// The operation row's refusals as the document and the box stand: each row offered, then
    /// greyed with its reason. Again when the merge scope's ticks change (ops#640 round 5)
    void refuseOperations();
    /// Greys the row `key` (not the current one) with `why` as its tooltip; empty: offered
    void refuseRow(const QString& key, const QString& why);
    void addPartsList();
    void addMergeList();
    /// The plain line for touching parts left out of the merge scope
    void updateMergeNotes();
    /// Merge with all ticked or unticked: the feature follows at once, the list hides or shows
    void onMergeWithAll(bool checked);
    /// A part ticked in the scope of a first solid: the feature moves into it (addToPart)
    void onScopePicked(const QString& part);
    void addFollowsNote(App::DocumentObject* primary);
    void onUnlink();
    /// Marks the parts the tool doesn't touch (debounced; the distance is cached per shape)
    void updateTouches();
    void slotChangedObject(const Gui::ViewProviderDocumentObject& Obj, const App::Property& Prop)
        override;

    QComboBox* combo;
    /// Row 2 of a subtractive primary: the studio's other parts, one tick each
    QListWidget* parts = nullptr;
    /// Row 2 of an additive feature: the studio's other parts to merge, one tick each (3b)
    QListWidget* mergeParts = nullptr;
    QLabel* mergeLabel = nullptr;
    QLabel* mergeNote = nullptr;
    /// Onshape's Merge with all (ops#640 rank 1), and its value when the box opened
    QCheckBox* mergeWithAll = nullptr;
    bool mergeWithAllWas = false;
    /// The scope list of a first solid: a tick moves the feature into the part (ops#640)
    bool scopePickMoves = false;
    QTimer* touchTimer = nullptr;
    std::shared_ptr<TouchCache> touchCache;
    /// The feature, still named when it is deleted (Cancel of a new one)
    App::DocumentObjectT featureT;
    /// The operation row's current row (new, add, Subtraction, Common), when it has one
    QString operation;
};

/// A common base for sketch based, dressup and other solid parameters dialogs
class TaskDlgFeatureParameters: public Gui::TaskView::TaskDialog
{
    Q_OBJECT

public:
    explicit TaskDlgFeatureParameters(PartDesignGui::ViewProvider* vp);
    ~TaskDlgFeatureParameters() override;

public:
    /// is called by the framework if the dialog is accepted (Ok)
    bool accept() override;
    /// is called by the framework if the dialog is rejected (Cancel)
    bool reject() override;
    /// The panels are in place: their reference fields join the group (ops#150).
    void open() override;
    /// Keeps the box's OK, whose tooltip says what a required selection still lacks
    /// (missingRequired); OK stays enabled (ops#640 H1).
    void modifyStandardButtons(QDialogButtonBox* box) override;

    /// FreeCAD-CH (ops#640 rank 24, hands-on F2): whether the dialog holds any input, for a tool
    /// started while it is open. Onshape commits a dialog with any input, even in error, and
    /// drops an empty one silently. An edit of an existing feature always has input; a new
    /// feature's dialog has once a reference field holds an entry (a preselection too) or a
    /// property of the feature differs from the dialog's opening. Invokable by name
    /// (QMetaObject::invokeMethod), so Gui's commands need no PartDesign header.
    Q_INVOKABLE bool hasInput() const;
    /// The command made @p feature for the dialog it opens next (hasInput).
    static void noteCreated(App::DocumentObject* feature);
    /// FreeCAD-CH (selection parity P1): the dialog opened next arms the field of @p property
    /// instead of the first empty one: a restart of the edit (restartEdit) keeps the field that
    /// was armed armed, so the next pick still goes to it. Empty: none.
    static void armOnOpen(const std::string& property);

    template<typename T = PartDesignGui::ViewProvider>
    T* getViewObject() const
    {
        static_assert(std::is_base_of<PartDesignGui::ViewProvider, T>::value, "Wrong template argument");
        return freecad_cast<T*>(vp);
    }

    template<typename T = App::DocumentObject>
    T* getObject() const
    {
        static_assert(std::is_base_of<App::DocumentObject, T>::value, "Wrong template argument");
        if (vp) {
            return vp->getObject<T>();
        }

        return nullptr;
    }

protected:
    /// The References panel repaired a reference, or is about to change the selection: the
    /// parameter panels hear of it (TaskFeatureParameters::onReferencesRepaired and
    /// onReferenceSelectionTaken). A dialog whose panels aren't TaskFeatureParameters adds its own.
    virtual void referencesRepaired();
    virtual void referenceSelectionTaken();
    /// The reference fields of the dialog's panels (TaskFeatureParameters::referenceFields). A
    /// dialog whose panels aren't TaskFeatureParameters adds theirs.
    virtual std::vector<ReferenceField*> panelFields();
    /// The Result box (ops#325), when the feature has one: the dialogs of additive and
    /// subtractive features add it before the preview box
    void addResultBox();
    /// What a required selection still lacks, or empty: OK's tooltip says it, a hint, not a
    /// block. Onshape's check stays enabled while a required field is empty, and OK commits the
    /// feature in error, as for a geometric failure (a Revolve's axis: ops#643, ops#640 H1, F7).
    virtual QString missingRequired() const
    {
        return {};
    }
    /// OK's tooltip, as missingRequired() says; called when the feature changes.
    void updateOkButton();
    /// FreeCAD-CH (ops#640 rank 36, hands-on B-4): the first parameter box's title is the
    /// feature's name, red while the feature is in error, with Onshape's "did not regenerate
    /// properly" tooltip (polish P13). Called after the feature changes or recomputes.
    void updateTitle();
    /// FreeCAD-CH (ops#640 polish P13, PL3a): under the Onshape keymap a pencil shown while the
    /// title row is hovered turns the title into a text box that renames the feature. Called
    /// from flattenForOnshape().
    void addTitleRename();
    /// FreeCAD-CH (ops#640 polish P5): under the Onshape keymap the dialog is one flat form under
    /// its title row: the other boxes lose their headers, the title row doesn't fold, and the
    /// Preview row is Onshape's. Called from open(), after the title box is chosen.
    void flattenForOnshape();
    /// A member of the feature's Body comes after it (Onshape offers Final then)
    bool hasLaterFeature() const;

    PartDesignGui::TaskPreviewParameters* preview;
    /// The feature's guessed, partly resolved or broken references, at the top; null if none
    /// (ops#127).
    PartDesignGui::TaskReferences* references = nullptr;
    /// The panels' reference fields: one armed at a time (ops#150).
    PartDesignGui::ReferenceFieldGroup* fieldGroup;

private:
    /// Calls \a fn on each parameter panel.
    void forEachParameters(const std::function<void(TaskFeatureParameters*)>& fn);

    PartDesignGui::ViewProvider* vp;
    /// The box's OK, and its tooltip when nothing is missing
    QPointer<QPushButton> okButton;
    QString okToolTip;
    /// OK's tooltip is missingRequired()'s hint
    bool showingHint = false;
    fastsignals::scoped_connection requiredConnection;
    /// The command made the feature for this dialog (noteCreated), and the feature's properties
    /// as the dialog opened (hasInput)
    bool created = false;
    std::vector<std::pair<std::string, std::unique_ptr<App::Property>>> openingValues;
    /// The box whose title is the feature's name (updateTitle), and its updates
    QPointer<QWidget> titleBox;
    bool titlePending = false;
    fastsignals::scoped_connection titleChanged;
    fastsignals::scoped_connection titleRecomputed;
};

}  // namespace PartDesignGui
