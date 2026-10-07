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

#include <Mod/PartDesign/App/FeatureRevolution.h>
#include <Mod/PartDesign/App/FeatureGroove.h>
#include "TaskSketchBasedParameters.h"


class Ui_TaskRevolutionParameters;
class QAbstractButton;
class QComboBox;
class QLabel;
class QLineEdit;

namespace App
{
class Property;
}

namespace Gui
{
class QuantitySpinBox;
class RadialGizmo;
class RotationGizmo;
class Gizmo;
class ViewProvider;
class ViewProviderCoordinateSystem;
}  // namespace Gui

namespace PartDesignGui
{
class ViewProviderRevolution;
class ViewProviderGroove;

class TaskRevolutionParameters: public TaskSketchBasedParameters
{
    Q_OBJECT

public:
    TaskRevolutionParameters(
        ViewProvider* RevolutionView,
        const char* pixname,
        const QString& title,
        QWidget* parent = nullptr
    );
    ~TaskRevolutionParameters() override;

    void apply() override;
    /// The axis box shows its property again (ops#127); the fields reload themselves.
    void onReferencesRepaired() override;
    /// The fields disarm through their group; the panel has no pick mode of its own (B15).
    void onReferenceSelectionTaken() override;
    /// The start reference, each side's up-to-face and the picked axis (ops#150 W6).
    std::vector<ReferenceField*> referenceFields() const override;

    /**
     * @brief fillAxisCombo fills the axis box with the sketch's and the body's axes; with
     * \a forceRefill false it only shows the property again, unless it is still empty.
     */
    void fillAxisCombo(bool forceRefill = false);

private Q_SLOTS:
    void onAngleChanged(double);
    void onAngle2Changed(double);
    void onReversed(bool);
    void onStartModeChanged(int);
    void onStartOffsetChanged(double);
    void onModeChangedSide1(int);
    void onModeChangedSide2(int);
    void onSidesModeChanged(int);

protected:
    /// The picks go to the fields
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void changeEvent(QEvent* event) override;
    bool getReversed() const;
    int getMode() const;
    int getMode2() const;
    int getSidesMode() const;
    void setupDialog();

    enum class SidesMode
    {
        OneSide,
        TwoSides,
        Symmetric,
    };

    enum class Side
    {
        First,
        Second,
    };

    enum class StartMode
    {
        ProfilePlane,
        Offset,
        Reference,
    };

    enum class Mode
    {
        Angle,
        ThroughAll,
        ToLast = ThroughAll,
        ToFirst,
        ToFace,
        TwoAngles,
    };

private:
    struct SideController
    {
        QComboBox* changeMode = nullptr;
        QLabel* labelAngle = nullptr;
        Gui::QuantitySpinBox* angleEdit = nullptr;
        /// The up-to-face (ops#150 W6)
        ReferenceField* faceField = nullptr;

        App::PropertyEnumeration* Type = nullptr;
        App::PropertyAngle* Angle = nullptr;
        App::PropertyLinkSub* UpToFace = nullptr;
    };

    SideController m_side1;
    SideController m_side2;

    SideController& getSideController(Side side)
    {
        return side == Side::First ? m_side1 : m_side2;
    }

    const SideController& getSideController(Side side) const
    {
        return side == Side::First ? m_side1 : m_side2;
    }

    App::PropertyEnumeration* propSideType;
    App::PropertyBool* propReversed;
    App::PropertyLinkSub* propReferenceAxis;

private:
    void createSideControllers();
    void createFields();
    /// Writes a picked or chosen axis, and Reversed as the axis suggests.
    void writeAxis(App::DocumentObject* obj, const std::vector<std::string>& subs);
    /// Arms \a field once its mode's widgets show (a mode chosen with the field empty).
    void armField(ReferenceField* field);
    void setupSideDialog(SideController& side);
    void connectSignals();
    void updateUI(Side side);
    void updateWholeUI(Side side);
    void updateStartUI();
    void updateSideUI(const SideController& side, Mode mode, bool isParentVisible, bool setFocus);
    void translateModeList(QComboBox* box, int index);
    void translateSidesList(int index);
    void onModeChanged(int index, Side side);
    Gui::ViewProviderCoordinateSystem* getOriginView() const;

private:
    std::unique_ptr<Ui_TaskRevolutionParameters> ui;
    QWidget* proxy;
    bool isGroove;
    double defaultGizmoMultFactor;

    /// The start reference (ops#150 W6)
    ReferenceField* startField = nullptr;
    /// The axis box and its picked axis's row (ops#150 W6)
    ReferenceCombo* axisCombo = nullptr;

    std::unique_ptr<Gui::GizmoContainer> gizmoContainer;
    Gui::RadialGizmo* rotationGizmo = nullptr;
    Gui::RadialGizmo* rotationGizmo2 = nullptr;
    Gui::RotationGizmo* startOffsetGizmo = nullptr;
    void setupGizmos(ViewProvider* vp);
    void setGizmoPositions();
};

class TaskDlgRevolutionParameters: public TaskDlgSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskDlgRevolutionParameters(PartDesignGui::ViewProviderRevolution* RevolutionView);
};

class TaskDlgGrooveParameters: public TaskDlgSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskDlgGrooveParameters(PartDesignGui::ViewProviderGroove* GrooveView);
};

}  // namespace PartDesignGui
