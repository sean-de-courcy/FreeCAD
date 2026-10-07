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

#include "ReferenceActions.h"
#include "TaskSketchBasedParameters.h"
#include "ViewProviderLoft.h"


class Ui_TaskLoftParameters;

namespace App
{
class Property;
}

namespace Gui
{
class ViewProvider;
}

namespace PartDesignGui
{


class TaskLoftParameters: public TaskSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskLoftParameters(
        ViewProviderLoft* LoftView,
        bool newObj = false,
        QWidget* parent = nullptr
    );
    ~TaskLoftParameters() override;

    /// The profile and the sections (ops#150 W7).
    std::vector<ReferenceField*> referenceFields() const override;
    /// The profile and the sections shown for the edit as they were before.
    void restoreVisibility();

private Q_SLOTS:
    void onClosed(bool);
    void onRuled(bool);

protected:
    void changeEvent(QEvent* e) override;

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void updateUI();
    void createFields();

private:
    QWidget* proxy;
    std::unique_ptr<Ui_TaskLoftParameters> ui;

    ReferenceField* profileField = nullptr;
    ReferenceField* sectionsField = nullptr;
    /// What the edit shows: the profile and the sections, also those picked during it
    /// (ops#162 B13).
    EditVisibility shown;
};

/// simulation dialog for the TaskView
class TaskDlgLoftParameters: public TaskDlgSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskDlgLoftParameters(ViewProviderLoft* LoftView, bool newObj = false);
    ~TaskDlgLoftParameters() override;

    /// is called by the framework if the dialog is accepted (Ok)
    bool accept() override;
    /// is called by the framework if the dialog is rejected (Cancel)
    bool reject() override;

protected:
    TaskLoftParameters* parameter;
};

}  // namespace PartDesignGui
