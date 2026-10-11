// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer <jrheinlaender@users.sourceforge.net> *
 *                                                                            *
 *   This file is part of the FreeCAD CAx development system.                 *
 *                                                                            *
 *   This library is free software; you can redistribute it and/or            *
 *   modify it under the terms of the GNU Library General Public              *
 *   License as published by the Free Software Foundation; either             *
 *   version 2 of the License, or (at your option) any later version.         *
 *                                                                            *
 *   This library  is distributed in the hope that it will be useful,         *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of           *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            *
 *   GNU Library General Public License for more details.                     *
 *                                                                            *
 *   You should have received a copy of the GNU Library General Public        *
 *   License along with this library; see the file COPYING.LIB. If not,       *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,            *
 *   Suite 330, Boston, MA  02111-1307, USA                                   *
 *                                                                            *
 ******************************************************************************/

#pragma once

#include <functional>
#include <optional>
#include <QListWidgetItem>

#include <App/DocumentObject.h>
#include <Gui/DocumentObserver.h>
#include <Gui/TaskView/TaskDialog.h>
#include <Gui/TaskView/TaskView.h>
#include <Gui/ViewProviderCoordinateSystem.h>


namespace PartDesignGui
{

class SoSwitch;
class Ui_TaskFeaturePick;
class TaskFeaturePick: public Gui::TaskView::TaskBox,
                       public Gui::SelectionObserver,
                       public Gui::DocumentObserver
{
    Q_OBJECT

public:
    enum featureStatus
    {
        validFeature = 0,
        invalidShape,
        noWire,
        isUsed,
        otherBody,
        otherPart,
        notInBody,
        basePlane,
        afterTip
    };

    TaskFeaturePick(
        std::vector<App::DocumentObject*>& objects,
        const std::vector<featureStatus>& status,
        bool singleFeatureSelect,
        QWidget* parent = nullptr
    );

    ~TaskFeaturePick() override;

    std::vector<App::DocumentObject*> getFeatures();
    std::vector<App::DocumentObject*> buildFeatures();
    void showExternal(bool val);
    bool isSingleSelectionEnabled() const;

    /// `target` is the container the caller puts the copy into (a body or a part; null: none):
    /// an independent copy (a sketch, a primitive, or a shape binder holding another feature's
    /// shape) is placed in it where the original is (PR 224 review M2, round 2). A dependent copy
    /// isn't yet (ops#244).
    /// A datum (point, line, plane) is copied as a datum of its own type.
    static App::DocumentObject* makeCopy(
        App::DocumentObject* obj,
        std::string sub,
        bool independent,
        App::DocumentObject* target
    );

    /// The name on `copy` (made by makeCopy from `original`) of the element `sub` of the
    /// original: the same index on a copy of the original's own type (a sketch or primitive,
    /// which has the original's elements, recomputed or not), once `sameElement` shows it's the
    /// same one; the first element of its kind on a shape binder of that element alone; none on a
    /// datum or for a whole object. Empty when the element differs on the copy (ops#244 P1, P2:
    /// the callers linked Face1/Edge1, or nothing, whatever was picked).
    static std::optional<std::string> copiedElement(
        App::DocumentObject* original,
        App::DocumentObject* copy,
        const std::string& sub
    );

    /// Whether `sub` (an index name) names the same element on `copy` as on `original`: its
    /// type, size and centre of mass, in each object's own frame
    static bool sameElement(
        App::DocumentObject* original,
        App::DocumentObject* copy,
        const std::string& sub
    );

protected Q_SLOTS:
    void onUpdate(bool);
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void onItemSelectionChanged();
    void onDoubleClick(QListWidgetItem* item);

protected:
    /** Notifies when the object is about to be removed. */
    void slotDeletedObject(const Gui::ViewProviderDocumentObject& Obj) override;
    /** Notifies on undo */
    void slotUndoDocument(const Gui::Document& Doc) override;
    /** Notifies on document deletion */
    void slotDeleteDocument(const Gui::Document& Doc) override;

private:
    std::unique_ptr<Ui_TaskFeaturePick> ui;
    QWidget* proxy;
    std::vector<Gui::ViewProviderCoordinateSystem*> origins;
    bool doSelection;
    std::string documentName;

    std::vector<QString> features;
    std::vector<featureStatus> statuses;

    void updateList();
    const QString getFeatureStatusString(const featureStatus st);
};


/// simulation dialog for the TaskView
class TaskDlgFeaturePick: public Gui::TaskView::TaskDialog
{
    Q_OBJECT

public:
    TaskDlgFeaturePick(
        std::vector<App::DocumentObject*>& objects,
        const std::vector<TaskFeaturePick::featureStatus>& status,
        std::function<bool(std::vector<App::DocumentObject*>)> acceptfunc,
        std::function<void(std::vector<App::DocumentObject*>)> workfunc,
        bool singleFeatureSelect,
        std::function<void(void)> abortfunc = 0
    );
    ~TaskDlgFeaturePick() override;

public:
    /// is called the TaskView when the dialog is opened
    void open() override;
    /// is called by the framework if an button is clicked which has no accept or reject role
    void clicked(int) override;
    /// is called by the framework if the dialog is accepted (Ok)
    bool accept() override;
    /// is called by the framework if the dialog is rejected (Cancel)
    bool reject() override;

    bool isAllowedAlterDocument() const override
    {
        return false;
    }

    void showExternal(bool val);

    /// returns for Close and Help button
    QDialogButtonBox::StandardButtons getStandardButtons() const override
    {
        return QDialogButtonBox::Ok | QDialogButtonBox::Cancel;
    }


protected:
    TaskFeaturePick* pick;
    bool accepted;
    std::function<bool(std::vector<App::DocumentObject*>)> acceptFunction;
    std::function<void(std::vector<App::DocumentObject*>)> workFunction;
    std::function<void(void)> abortFunction;
};

}  // namespace PartDesignGui
