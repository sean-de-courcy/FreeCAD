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

#pragma once

#include "TaskSketchBasedParameters.h"
#include "ViewProviderPipe.h"
#include "TaskDressUpParameters.h"

class QListWidget;
class QListWidgetItem;


namespace App
{
class Property;
}

namespace Gui
{
class ViewProvider;
}  // namespace Gui

namespace PartDesignGui
{

class Ui_TaskPipeParameters;
class Ui_TaskPipeOrientation;
class Ui_TaskPipeScaling;

class TaskPipeParameters: public TaskSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskPipeParameters(
        ViewProviderPipe* PipeView,
        bool newObj = false,
        QWidget* parent = nullptr
    );
    ~TaskPipeParameters() override;

    bool accept();
    void onReferenceSelectionTaken() override;
    /// The profile and the path (ops#150 W8).
    std::vector<ReferenceField*> referenceFields() const override;

private Q_SLOTS:
    void onTangentChanged(bool checked);
    void onTransitionChanged(int);

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void createFields();
    void setVisibilityOfSpineAndProfile();

    /// The spine, the profile and the auxiliary spine shown for the edit, also those picked
    /// during it (ops#162 B13).
    EditVisibility shown;

private:
    QWidget* proxy;
    std::unique_ptr<Ui_TaskPipeParameters> ui;
    ReferenceField* profileField = nullptr;
    ReferenceField* spineField = nullptr;
    friend class TaskDlgPipeParameters;
};

class TaskPipeOrientation: public TaskSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskPipeOrientation(
        ViewProviderPipe* PipeView,
        bool newObj = false,
        QWidget* parent = nullptr
    );
    ~TaskPipeOrientation() override;

    void onReferenceSelectionTaken() override;
    /// The auxiliary path, shown in Mode Auxiliary (ops#150 W8).
    std::vector<ReferenceField*> referenceFields() const override;

private Q_SLOTS:
    void onOrientationChanged(int);
    void updateUI(int idx);
    void onClearButton();
    void onCurvilinearChanged(bool checked);
    void onBinormalChanged(double);

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void createAuxiliarySpineField();

    /// The auxiliary paths picked during the edit, shown; put back as they were when the dialog
    /// closes (the one the pipe had is TaskPipeParameters')
    EditVisibility shown;

private:
    QWidget* proxy;
    std::unique_ptr<Ui_TaskPipeOrientation> ui;
    ReferenceField* auxiliarySpineField = nullptr;
    friend class TaskDlgPipeParameters;
};


class TaskPipeScaling: public TaskSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskPipeScaling(ViewProviderPipe* PipeView, bool newObj = false, QWidget* parent = nullptr);
    ~TaskPipeScaling() override;

    /// The sections (ops#150 W7).
    std::vector<ReferenceField*> referenceFields() const override;

private Q_SLOTS:
    void onScalingChanged(int);
    void updateUI(int idx);

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void createSectionsField();
    /// A section that is a point: the pipe takes one only last.
    static bool isPointSection(const App::PropertyLinkSubList::SubSet& section);

private:
    QWidget* proxy;
    std::unique_ptr<Ui_TaskPipeScaling> ui;
    ReferenceField* sectionsField = nullptr;
    /// The sections shown for the edit, also those picked during it (ops#162 B13).
    EditVisibility shown;
    friend class TaskDlgPipeParameters;
};

/// simulation dialog for the TaskView
class TaskDlgPipeParameters: public TaskDlgSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskDlgPipeParameters(ViewProviderPipe* PipeView, bool newObj = false);
    ~TaskDlgPipeParameters() override;

public:
    /// is called by the framework if the dialog is accepted (Ok)
    bool accept() override;
    /// is called by the framework if the dialog is rejected (Cancel)
    bool reject() override;

protected:
    TaskPipeParameters* parameter;
    TaskPipeOrientation* orientation;
    TaskPipeScaling* scaling;
};

}  // namespace PartDesignGui
