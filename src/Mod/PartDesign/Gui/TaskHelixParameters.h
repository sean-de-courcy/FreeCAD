// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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

#include <Gui/Inventor/Draggers/Gizmo.h>

#include "TaskSketchBasedParameters.h"
#include "ViewProviderHelix.h"


namespace App
{
class Property;
}

namespace Gui
{
class LinearGizmo;
class GizmoContainer;
class ViewProvider;
}  // namespace Gui

namespace PartDesignGui
{
class Ui_TaskHelixParameters;


class TaskHelixParameters: public TaskSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskHelixParameters(ViewProviderHelix* HelixView, QWidget* parent = nullptr);
    ~TaskHelixParameters() override;

    void apply() override;
    /// The axis box shows ReferenceAxis again (ops#127).
    void onReferencesRepaired() override;
    /// The axis row disarms through the dialog's group; the panel has no pick mode (B15).
    void onReferenceSelectionTaken() override;
    /// The picked axis's row (ops#150 W6).
    std::vector<ReferenceField*> referenceFields() const override;

    static bool showPreview(PartDesign::Helix*);

private:
    /**
     * @brief fillAxisCombo fills the axis box with the sketch's and the body's axes; with
     * \a forceRefill false it only shows the property again, unless it is still empty.
     */
    void fillAxisCombo(bool forceRefill = false);
    void addSketchAxes(std::vector<ReferenceCombo::Choice>& choices);
    void addPartAxes(std::vector<ReferenceCombo::Choice>& choices);
    void createAxisField();
    /// Writes a picked or chosen axis.
    void writeAxis(App::DocumentObject* obj, const std::vector<std::string>& subs);
    void assignToolTipsFromPropertyDocs();
    void adaptVisibilityToMode();

private Q_SLOTS:
    void onPitchChanged(double);
    void onHeightChanged(double);
    void onTurnsChanged(double);
    void onAngleChanged(double);
    void onGrowthChanged(double);
    void onLeftHandedChanged(bool);
    void onReversedChanged(bool);
    void onModeChanged(int);
    void onOutsideChanged(bool);


protected:
    /// The picks go to the axis row
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void changeEvent(QEvent* e) override;
    bool updateView() const;

    // mirrors of helixes's properties
    App::PropertyLength* propPitch;
    App::PropertyLength* propHeight;
    App::PropertyFloatConstraint* propTurns;
    App::PropertyBool* propLeftHanded;
    App::PropertyBool* propReversed;
    App::PropertyLinkSub* propReferenceAxis;
    App::PropertyAngle* propAngle;
    App::PropertyDistance* propGrowth;
    App::PropertyEnumeration* propMode;
    App::PropertyBool* propOutside;


private:
    void initializeHelix();
    void connectSlots();
    void updateUI();
    void updateStatus();
    void assignProperties();
    void setValuesFromProperties();
    void bindProperties();
    void showCoordinateAxes();

private:
    QWidget* proxy;
    std::unique_ptr<Ui_TaskHelixParameters> ui;

    /// The axis box and its picked axis's row (ops#150 W6)
    ReferenceCombo* axisCombo = nullptr;

    std::unique_ptr<Gui::GizmoContainer> gizmoContainer;
    Gui::LinearGizmo* heightGizmo = nullptr;
    void setupGizmos(ViewProviderHelix* vp);
    void setGizmoPositions();
};

/// simulation dialog for the TaskView
class TaskDlgHelixParameters: public TaskDlgSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskDlgHelixParameters(ViewProviderHelix* HelixView);
};

}  // namespace PartDesignGui
