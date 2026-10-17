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
#include <type_traits>
#include <App/DocumentObserver.h>
#include <Gui/TaskView/TaskDialog.h>
#include <Gui/TaskView/TaskView.h>
#include <Gui/DocumentObserver.h>

#include "ViewProvider.h"

class QComboBox;
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
 * The merge scope of row 2 for an additive feature (2.5) comes with session 3b.
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

    /// The touch tests done, by the two shapes: the distance is slow on B-splines (design 2.3)
    struct TouchCache;

private:
    void onResultChanged(int index);
    void addPartsList();
    void addFollowsNote(App::DocumentObject* primary);
    void onUnlink();
    /// Marks the parts the tool doesn't touch (debounced; the distance is cached per shape)
    void updateTouches();
    void slotChangedObject(const Gui::ViewProviderDocumentObject& Obj, const App::Property& Prop)
        override;

    QComboBox* combo;
    /// Row 2 of a subtractive primary: the studio's other parts, one tick each
    QListWidget* parts = nullptr;
    QTimer* touchTimer = nullptr;
    std::shared_ptr<TouchCache> touchCache;
    /// The feature, still named when it is deleted (Cancel of a new one)
    App::DocumentObjectT featureT;
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
};

}  // namespace PartDesignGui
