// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer                                    *
 *                                   <jrheinlaender@users.sourceforge.net> *
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

#include <QFlags>

#include "EnumFlags.h"
#include "TaskDressUpParameters.h"
#include "ViewProviderDraft.h"

class Ui_TaskDraftParameters;

namespace Gui
{
class RotationGizmo;
class GizmoContainer;
}  // namespace Gui

namespace PartDesignGui
{

class TaskDraftParameters: public TaskDressUpParameters
{
    Q_OBJECT

public:
    explicit TaskDraftParameters(ViewProviderDressUp* DressUpView, QWidget* parent = nullptr);
    ~TaskDraftParameters() override;

    void apply() override;
    /// The faces, the neutral plane and the pull direction (ops#150).
    std::vector<ReferenceField*> referenceFields() const override;

    double getAngle() const;
    bool getReversed() const;
    const std::vector<std::string> getFaces() const;

private Q_SLOTS:
    void onAngleChanged(double angle);
    void onReversedChanged(bool reversed);

protected:
    void changeEvent(QEvent* e) override;
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;

private:
    /// A single-entry field for \a property in place of \a placeholder: an element of the base,
    /// or a datum or origin plane or line, through the cross-body question.
    ReferenceField* createSingleField(QWidget* placeholder,
                                      const char* property,
                                      AllowSelectionFlags flags,
                                      const QString& label,
                                      const QString& kinds);

    std::unique_ptr<Ui_TaskDraftParameters> ui;
    ReferenceField* planeField = nullptr;
    ReferenceField* lineField = nullptr;

    std::unique_ptr<Gui::GizmoContainer> gizmoContainer;
    Gui::RotationGizmo* angleGizmo = nullptr;
    void setupGizmos(ViewProvider* vp);
    void setGizmoPositions();
};

/// simulation dialog for the TaskView
class TaskDlgDraftParameters: public TaskDlgDressUpParameters
{
    Q_OBJECT

public:
    explicit TaskDlgDraftParameters(ViewProviderDraft* DraftView);
    ~TaskDlgDraftParameters() override;

public:
    /// is called by the framework if the dialog is accepted (Ok)
    bool accept() override;
};

}  // namespace PartDesignGui
