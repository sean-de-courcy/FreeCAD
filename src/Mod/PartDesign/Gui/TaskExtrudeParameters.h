// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2021 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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

#include <QLabel>

#include <App/DocumentObserver.h>
#include <Gui/Inventor/Draggers/Gizmo.h>

#include "TaskSketchBasedParameters.h"
#include "ViewProviderExtrude.h"

class QCheckBox;
class QComboBox;
class QLineEdit;
class QListWidget;
class QPushButton;
class QToolButton;

class Ui_TaskPadPocketParameters;

namespace App
{
class Property;
class PropertyLinkSubList;
}  // namespace App
namespace Gui
{
class PrefQuantitySpinBox;
}

namespace Gui
{
class LinearGizmo;
class RotationalGizmo;
class GizmoContainer;
}  // namespace Gui

namespace PartDesign
{
class ProfileBased;
}

namespace PartDesignGui
{

class ReferenceField;

class TaskExtrudeParameters: public TaskSketchBasedParameters
{
    Q_OBJECT

    enum DirectionModes
    {
        Normal,
        Select,
        Custom,
        Reference
    };

public:
    enum class Type
    {
        Pad,
        Pocket
    };

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

    enum class Mode
    {
        Dimension,
        ThroughAll,
        ToLast = ThroughAll,
        ToFirst,
        ToFace,
        ToShape,
        // The other class's end type, appended to Type's list (ops#640): Through all on a Pad,
        // To last on a Pocket. UI index 5, Type index 6 (the UI skips "?TwoLengths").
        Appended,
        // Up to vertex (ops#640 rank 22): Type index 7, appended. The end type box lists the
        // modes in Onshape's order, each row's data its mode (getMode()).
        ToVertex,
    };

    enum class StartMode
    {
        ProfilePlane = 0,
        Offset = 1,
        Reference = 2,
    };

    TaskExtrudeParameters(
        ViewProviderExtrude* ExtrudeView,
        QWidget* parent,
        const std::string& pixmapname,
        const QString& parname
    );
    ~TaskExtrudeParameters() override;

    void saveHistory() override;

    void fillDirectionCombo();
    void addAxisToCombo(
        App::DocumentObject* linkObj,
        std::string linkSubname,
        QString itemText,
        bool hasSketch = true
    );
    void applyParameters();

    /// The widgets that show link properties read them again (ops#127).
    void onReferencesRepaired() override;
    void onReferenceSelectionTaken() override;
    /// The profile, the start reference, each side's up-to-face, up-to-shape and its faces, and
    /// the hidden direction field (ops#150).
    std::vector<ReferenceField*> referenceFields() const override;

protected:
    // This struct holds all pointers for one side's UI and properties
    struct SideController
    {
        // UI Widgets
        QComboBox* changeMode = nullptr;
        QLabel* labelLength = nullptr;
        QLabel* labelOffset = nullptr;
        QLabel* labelTaperAngle = nullptr;
        Gui::PrefQuantitySpinBox* lengthEdit = nullptr;
        Gui::PrefQuantitySpinBox* offsetEdit = nullptr;
        Gui::PrefQuantitySpinBox* taperEdit = nullptr;
        /// The up-to-face, the up-to-shape's object and its faces (ops#150).
        ReferenceField* faceField = nullptr;
        ReferenceField* shapeField = nullptr;
        ReferenceField* shapeFacesField = nullptr;
        /// Up to vertex: a vertex or a point, in UpToFace too (ops#640 rank 22).
        ReferenceField* vertexField = nullptr;
        QCheckBox* checkBoxAllFaces = nullptr;
        QWidget* upToShapeList = nullptr;
        QWidget* upToShapeFaces = nullptr;

        // Feature Properties
        App::PropertyEnumeration* Type = nullptr;
        App::PropertyLength* Length = nullptr;
        App::PropertyLength* Offset = nullptr;
        App::PropertyAngle* TaperAngle = nullptr;
        App::PropertyLinkSub* UpToFace = nullptr;
        App::PropertyLinkSubList* UpToShape = nullptr;
    };

    SideController m_side1;
    SideController m_side2;

    SideController& getSideController(Side side)
    {
        return (side == Side::First) ? m_side1 : m_side2;
    }

protected Q_SLOTS:
    void onSidesModeChanged(int);
    virtual void onModeChanged(int index, Side side) = 0;

private Q_SLOTS:
    void onDirectionCBChanged(int);
    void onAlongSketchNormalChanged(bool);
    void onXDirectionEditChanged(double);
    void onYDirectionEditChanged(double);
    void onZDirectionEditChanged(double);
    void onReversedChanged(bool);

private:
    void onModeChanged_Side1(int index);
    void onModeChanged_Side2(int index);
    void onLengthChanged(double len, Side side);
    void onStartModeChanged(int type);
    void onStartOffsetChanged(double len);
    void onOffsetChanged(double len, Side side);
    void onTaperChanged(double angle, Side side);
    void onAllFacesToggled(bool checked, Side side);

protected:
    void updateWholeUI(Type type, Side side);
    void updateSideUI(
        const SideController& s,
        Type featureType,
        Mode sideMode,
        bool isParentVisible,
        bool setFocus
    );
    void setupDialog();
    void readValuesFromHistory();
    void changeEvent(QEvent* e) override;
    App::PropertyLinkSub* propReferenceAxis;
    void getReferenceAxis(App::DocumentObject*& obj, std::vector<std::string>& sub) const;

    double getOffset() const;
    double getOffset2() const;
    bool getAlongSketchNormal() const;
    bool getCustom() const;
    std::string getReferenceAxis() const;
    double getXDirection() const;
    double getYDirection() const;
    double getZDirection() const;
    bool getReversed() const;
    /// The side's end type: the Mode of the end type box's row (not the row, ops#640 rank 22).
    int getMode() const;
    int getMode2() const;
    /// The end type box's row of  mode (-1: none).
    static int rowOfMode(const QComboBox* box, Mode mode);
    /// Up to face and Up to vertex share UpToFace: a switch between them drops a link of the
    /// other kind (a face for a vertex) (ops#640 rank 22).
    void dropUpToFaceOfOtherKind(Side side, Mode mode);
    int getSidesMode() const;
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void translateSidesList(int index);
    virtual void translateModeList(QComboBox* box, int index);
    virtual void updateUI(Side side);
    void updateDirectionEdits();
    void setDirectionMode(int index);

private:
    void setupSideDialog(SideController& side);

    void tryRecomputeFeature();
    void connectSlots();
    bool hasProfileFace(PartDesign::ProfileBased*) const;

    void createSideControllers();
    void updateStartUI();

    /// FreeCAD-CH (ops#640, rank 22): Onshape's fields. Symmetric and Second end position as
    /// checkboxes for the Sides box (hidden, still what is written), Starting offset as a checkbox
    /// for the Start box (shown only for a start reference), a Draft checkbox for the taper, and
    /// Onshape's words; no Recompute on change.
    void createOnshapeFields();
    /// The checkboxes follow the boxes they stand for; the taper shows only with Draft ticked.
    void updateOnshapeUI();
    /// Onshape's words on the labels (again after a retranslation).
    void setOnshapeWords();
    void setSides(SidesMode mode);
    QCheckBox* symmetric = nullptr;
    QCheckBox* secondEnd = nullptr;
    QCheckBox* startingOffset = nullptr;
    QCheckBox* draft = nullptr;

    /// The reference fields, in place of the `.ui` placeholders (ops#150).
    void createFields();
    /// The profile and its regions (ops#150 W3).
    void createProfileField();
    /// Sets AllowMultiFace when the profile gets subs (a command): an older feature without it
    /// ignores a sketch's subs and pads the whole sketch (ops#162 B7). Without subs it goes back
    /// to the value the dialog opened with (undo, Use whole sketch, the last region taken out).
    /// True if it was changed.
    bool allowMultiFace(bool hasSubs);
    /// AllowMultiFace when the dialog opened.
    bool savedAllowMultiFace = false;
    /// While the profile field is armed: the sketch shown with its regions stronger, the profile
    /// preview shown, and the feature hidden when nothing comes before it; off, as they were.
    void showProfileTarget(bool on);
    void createSideFields(SideController& side, Side which);
    /// A single-entry field of a face or plane (an up-to-face, the start reference).
    ReferenceField* createFaceField(QWidget* placeholder,
                                    const char* property,
                                    const QString& label,
                                    bool refuseWholeSketch);
    /// Arms \a field and gives it the focus, once the dialog is up (a mode just chosen).
    void armField(ReferenceField* field);
    /// The solid before the feature: shown while a field is armed.
    App::DocumentObject* baseSolid() const;
    ReferenceField* profileField = nullptr;
    ReferenceField* startField = nullptr;
    /// The direction box's "Select reference…": a hidden field for one pick.
    ReferenceField* axisField = nullptr;
    /// setupDialog() is done: a mode chosen now arms its field.
    bool dialogReady = false;

    /// What showProfileTarget() showed and emphasized.
    App::DocumentObjectT shownProfile;
    App::DocumentObjectT emphasizedProfile;
    /// After a pick of another profile object: the direction box rebuilt for it, and a
    /// ReferenceAxis on the old profile's normal moved to the new one's (ops#130). True when
    /// ReferenceAxis changed.
    bool followProfile();
    /// The profile object the direction box's normal entries were made for.
    App::DocumentObjectT directionProfile;
    /// showProfileTarget() hid the feature.
    bool hiddenSelf = false;

    std::unique_ptr<Gui::GizmoContainer> gizmoContainer;
    Gui::LinearGizmo* startOffsetGizmo = nullptr;
    Gui::LinearGizmo* lengthGizmo1 = nullptr;
    Gui::LinearGizmo* lengthGizmo2 = nullptr;
    Gui::RotationGizmo* taperAngleGizmo1 = nullptr;
    Gui::RotationGizmo* taperAngleGizmo2 = nullptr;
    void setupGizmos();
    void setGizmoPositions();

protected:
    QWidget* proxy;

    std::unique_ptr<Ui_TaskPadPocketParameters> ui;
    std::vector<std::unique_ptr<App::PropertyLinkSub>> axesInList;
};

class TaskDlgExtrudeParameters: public TaskDlgSketchBasedParameters
{
    Q_OBJECT

public:
    explicit TaskDlgExtrudeParameters(PartDesignGui::ViewProviderExtrude* vp);
    ~TaskDlgExtrudeParameters() override = default;

protected:
    virtual TaskExtrudeParameters* getTaskParameters() = 0;
};

}  // namespace PartDesignGui
