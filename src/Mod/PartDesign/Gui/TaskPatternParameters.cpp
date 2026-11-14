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

#include <QCheckBox>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QRegularExpression>
#include <QTimer>
#include <QVBoxLayout>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>
#include <gp_Ax2.hxx>
#include <gp_Dir.hxx>
#include <gp_Vec.hxx>
#include <gp_Pnt.hxx>

#include <BRep_Builder.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopoDS_Compound.hxx>

#include <Inventor/events/SoMouseButtonEvent.h>
#include <Inventor/nodes/SoAnnotation.h>
#include <Inventor/nodes/SoBaseColor.h>
#include <Inventor/nodes/SoCoordinate3.h>
#include <Inventor/nodes/SoEventCallback.h>
#include <Inventor/nodes/SoMarkerSet.h>
#include <Inventor/nodes/SoSeparator.h>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Origin.h>
#include <Base/Console.h>
#include <Gui/Application.h>
#include <Gui/MainWindow.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Command.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Gui/ViewProviderCoordinateSystem.h>
#include <Gui/Inventor/MarkerBitmaps.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/DatumLine.h>
#include <Mod/PartDesign/App/DatumPlane.h>
#include <Mod/PartDesign/App/FeatureLinearPattern.h>
#include <Mod/PartDesign/App/FeaturePolarPattern.h>
#include <Mod/PartDesign/App/FeatureAddSub.h>
#include <Mod/Part/Gui/PatternParametersWidget.h>
#include <Mod/Part/App/Tools.h>

#include "ui_TaskPatternParameters.h"
#include "TaskPatternParameters.h"
#include "ReferenceSelection.h"
#include "TaskMultiTransformParameters.h"


using namespace PartDesignGui;
using namespace Gui;

namespace
{

/// The Python list SkippedInstances is written with from the "Instances to skip" field's text:
/// its whole numbers in order ("(1, 0), (2, 0)" gives [1, 0, 2, 0]); for a linear pattern only
/// whole pairs (FreeCAD-CH ops#640 rank 8)
std::string skippedPython(const QString& text, bool pairs)
{
    std::vector<long> values;
    static const QRegularExpression number(QStringLiteral("-?\\d+"));
    auto it = number.globalMatch(text);
    while (it.hasNext()) {
        values.push_back(it.next().captured().toLong());
    }
    if (pairs && values.size() % 2 != 0) {
        values.pop_back();
    }
    std::string list = "[";
    for (std::size_t i = 0; i < values.size(); ++i) {
        list += (i ? ", " : "") + std::to_string(values[i]);
    }
    return list + "]";
}

/// The field's text for SkippedInstances: "(1, 0), (2, 0)" for pairs, "1, 2" otherwise
QString skippedText(const std::vector<long>& values, bool pairs)
{
    QStringList items;
    if (pairs) {
        for (std::size_t i = 0; i + 1 < values.size(); i += 2) {
            items << QStringLiteral("(%1, %2)").arg(values[i]).arg(values[i + 1]);
        }
    }
    else {
        for (long value : values) {
            items << QString::number(value);
        }
    }
    return items.join(QStringLiteral(", "));
}

}  // namespace

/* TRANSLATOR PartDesignGui::TaskPatternParameters */

TaskPatternParameters::TaskPatternParameters(ViewProviderTransformed* TransformedView, QWidget* parent)
    : TaskTransformedParameters(TransformedView, parent)
    , ui(new Ui_TaskPatternParameters)
{
    setupUI();
    updateSpacingLabels();
}

TaskPatternParameters::TaskPatternParameters(
    TaskMultiTransformParameters* parentTask,
    QWidget* parameterWidget
)
    : TaskTransformedParameters(parentTask)
    , ui(new Ui::TaskPatternParameters)
{
    setupParameterUI(parameterWidget);
    updateSpacingLabels();
}

void TaskPatternParameters::setupParameterUI(QWidget* widget)
{
    ui->setupUi(widget);  // Setup the Task's own minimal UI (placeholder)
    QMetaObject::connectSlotsByName(this);

    // --- Create and Embed the Parameter Widget ---
    auto pattern = getObject();
    if (!pattern) {
        return;
    }
    PartGui::PatternType type = pattern->isDerivedFrom<PartDesign::LinearPattern>()
        ? PartGui::PatternType::Linear
        : PartGui::PatternType::Polar;

    // Set first direction widget
    auto* viewer = getTopTransformedView()->getViewer();
    dotViewer = viewer;
    parametersWidget = new PartGui::PatternParametersWidget(type, viewer, widget);

    auto* placeholderLayout = new QVBoxLayout(ui->parametersWidgetPlaceholder);
    placeholderLayout->setContentsMargins(0, 0, 0, 0);
    placeholderLayout->addWidget(parametersWidget);
    ui->parametersWidgetPlaceholder->setLayout(placeholderLayout);

    auto* sketch = dynamic_cast<Part::Part2DObject*>(getSketchObject());
    this->fillAxisCombo(parametersWidget->dirLinks, sketch);
    connect(
        parametersWidget,
        &PartGui::PatternParametersWidget::requestReferenceSelection,
        this,
        &TaskPatternParameters::onParameterWidgetRequestReferenceSelection
    );
    connect(
        parametersWidget,
        &PartGui::PatternParametersWidget::parametersChanged,
        this,
        &TaskPatternParameters::onParameterWidgetParametersChanged
    );

    // Add second direction widget if necessary
    if (type == PartGui::PatternType::Linear) {
        parametersWidget2 = new PartGui::PatternParametersWidget(type, viewer, widget);
        auto* placeholderLayout2 = new QVBoxLayout(ui->parametersWidgetPlaceholder2);
        placeholderLayout2->setContentsMargins(0, 0, 0, 0);
        placeholderLayout2->addWidget(parametersWidget2);
        ui->parametersWidgetPlaceholder2->setLayout(placeholderLayout2);

        this->fillAxisCombo(parametersWidget2->dirLinks, sketch);
        connect(
            parametersWidget2,
            &PartGui::PatternParametersWidget::requestReferenceSelection,
            this,
            &TaskPatternParameters::onParameterWidgetRequestReferenceSelection2
        );
        connect(
            parametersWidget2,
            &PartGui::PatternParametersWidget::parametersChanged,
            this,
            &TaskPatternParameters::onParameterWidgetParametersChanged
        );
        // Onshape's Second direction box: ticked, it shows the second direction's fields; the
        // fork's "off" is count 1 (FreeCAD-CH ops#655)
        parametersWidget2->setTitle(tr("Second direction"));
        parametersWidget2->setCheckable(true);
    }

    bindProperties();
    addOnshapeOptions(widget);

    // --- Task Specific Setup ---
    showOriginAxes(true);  // Show origin helper axes

    updateViewTimer = new QTimer(this);
    updateViewTimer->setSingleShot(true);
    updateViewTimer->setInterval(getUpdateViewTimeout());
    connect(updateViewTimer, &QTimer::timeout, this, &TaskPatternParameters::onUpdateViewTimer);
}

void TaskPatternParameters::addOnshapeOptions(QWidget* widget)
{
    // FreeCAD-CH (ops#640 rank 8, B3-6, E-1): Onshape's Centered and Skip instances. Skip is a
    // list field ("Instances to skip", Onshape's (i, j) pairs for a linear pattern), not yet a
    // click on an instance's marker
    auto pattern = getObject();
    auto centeredProp = pattern
        ? freecad_cast<App::PropertyBool*>(pattern->getPropertyByName("Centered"))
        : nullptr;
    auto skippedProp = pattern
        ? freecad_cast<App::PropertyIntegerList*>(pattern->getPropertyByName("SkippedInstances"))
        : nullptr;
    if (!centeredProp || !skippedProp) {
        return;
    }
    const bool pairs = pattern->isDerivedFrom<PartDesign::LinearPattern>();

    auto* centered = new QCheckBox(tr("Centered"), widget);
    centered->setObjectName(QStringLiteral("checkCentered"));
    centered->setChecked(centeredProp->getValue());
    ui->verticalLayout->insertWidget(1, centered);
    connect(centered, &QCheckBox::toggled, this, [this](bool on) {
        if (blockUpdate || !getObject()) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), "Centered = " << (on ? "True" : "False"));
        kickUpdateViewTimer();
    });

    // The second direction's own Centered, in its group (Onshape's isCenteredTwo; ops#655), and
    // the banner for parallel directions
    auto centered2Prop = freecad_cast<App::PropertyBool*>(pattern->getPropertyByName("Centered2"));
    if (parametersWidget2 && centered2Prop) {
        auto* centered2 = new QCheckBox(tr("Centered"), parametersWidget2);
        centered2->setObjectName(QStringLiteral("checkCentered2"));
        centered2->setChecked(centered2Prop->getValue());
        parametersWidget2->addRow(centered2);
        connect(centered2, &QCheckBox::toggled, this, [this](bool on) {
            if (blockUpdate || !getObject()) {
                return;
            }
            setupTransaction();
            FCMD_OBJ_CMD(getObject(), "Centered2 = " << (on ? "True" : "False"));
            kickUpdateViewTimer();
        });

        parallelBanner = new QLabel(
            tr("Parallel directions selected for first and second direction."),
            widget
        );
        parallelBanner->setObjectName(QStringLiteral("parallelBanner"));
        parallelBanner->setWordWrap(true);
        parallelBanner->setStyleSheet(
            QStringLiteral("color: white; background-color: #2f6fd1; padding: 4px;")
        );
        parallelBanner->setVisible(false);
        ui->verticalLayout->insertWidget(0, parallelBanner);
        updateParallelBanner();
    }
    // A MultiTransform's step: the MultiTransform makes the instances and skips none of a step's,
    // so a step offers no Skip
    if (getTopTransformedObject() != pattern) {
        return;
    }

    auto* skip = new QCheckBox(tr("Skip instances"), widget);
    skip->setObjectName(QStringLiteral("checkSkip"));
    auto* skipped = new QLineEdit(widget);
    skipped->setObjectName(QStringLiteral("editSkipped"));
    skipped->setPlaceholderText(
        pairs ? tr("Instances to skip, e.g. (1, 0), (2, 0)") : tr("Instances to skip, e.g. 1, 2")
    );
    skipped->setText(skippedText(skippedProp->getValues(), pairs));
    skip->setChecked(!skippedProp->getValues().empty());
    skipped->setVisible(skip->isChecked());
    ui->verticalLayout->addWidget(skip);
    ui->verticalLayout->addWidget(skipped);

    connect(skip, &QCheckBox::toggled, this, [this, skipped](bool on) {
        skipped->setVisible(on);
        if (on) {
            skipped->setFocus();
            updateSkipDots();
            return;
        }
        // Off, nothing is skipped
        skipped->clear();
        updateSkipDots();
        if (blockUpdate || !getObject()) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), "SkippedInstances = []");
        kickUpdateViewTimer();
    });
    connect(skipped, &QLineEdit::editingFinished, this, [this, skipped, pairs]() {
        if (blockUpdate || !getObject()) {
            return;
        }
        setupTransaction();
        FCMD_OBJ_CMD(getObject(), "SkippedInstances = " << skippedPython(skipped->text(), pairs));
        kickUpdateViewTimer();
        updateSkipDots();
    });
    updateSkipDots();
}

void TaskPatternParameters::bindProperties()
{
    auto pattern = getObject();
    if (!pattern) {
        return;
    }

    if (pattern->isDerivedFrom<PartDesign::LinearPattern>()) {
        auto* linear = static_cast<PartDesign::LinearPattern*>(pattern);
        parametersWidget->bindProperties(
            &linear->Direction,
            &linear->Reversed,
            &linear->Part::LinearPatternExtension::Mode,
            &linear->Length,
            &linear->Offset,
            &linear->Spacings,
            &linear->SpacingPattern,
            &linear->Occurrences,
            linear
        );
        parametersWidget2->bindProperties(
            &linear->Direction2,
            &linear->Reversed2,
            &linear->Mode2,
            &linear->Length2,
            &linear->Offset2,
            &linear->Spacings2,
            &linear->SpacingPattern2,
            &linear->Occurrences2,
            linear
        );
    }
    else if (pattern->isDerivedFrom<PartDesign::PolarPattern>()) {
        auto* polar = static_cast<PartDesign::PolarPattern*>(pattern);
        parametersWidget->bindProperties(
            &polar->Axis,
            &polar->Reversed,
            &polar->Part::PolarPatternExtension::Mode,
            &polar->Angle,
            &polar->Offset,
            &polar->Spacings,
            &polar->SpacingPattern,
            &polar->Occurrences,
            polar
        );
    }
    else {
        Base::Console().warning(
            "PatternParametersWidget property binding failed. Something is wrong please report.\n"
        );
    }
}

void TaskPatternParameters::retranslateParameterUI(QWidget* widget)
{
    ui->retranslateUi(widget);
}

void TaskPatternParameters::updateUI()
{
    if (parametersWidget) {
        parametersWidget->updateUI();
    }
    if (parametersWidget2) {
        parametersWidget2->updateUI();
    }
    updateParallelBanner();
    updateSkipDots();
}

// --- Task-Specific Logic ---

void TaskPatternParameters::showOriginAxes(bool show)
{
    PartDesign::Body* body = PartDesign::Body::findBodyOf(getObject());
    if (body) {
        try {
            App::Origin* origin = body->getOrigin();
            auto vpOrigin = static_cast<ViewProviderCoordinateSystem*>(
                Gui::Application::Instance->getViewProvider(origin)
            );
            // FreeCAD-CH (ops#640, rank 52): a new part studio's planes are shown through the same
            // temporary visibility; they stay shown with the axes, and after the dialog
            if (show) {
                const bool studioPlanes = vpOrigin->isTemporaryVisibility();
                setProperty("studioPlanes", studioPlanes);
                Gui::DatumElements elements(Gui::DatumElement::Axes);
                if (studioPlanes) {
                    elements.setFlag(Gui::DatumElement::Planes);
                }
                vpOrigin->setTemporaryVisibility(elements);
            }
            else {
                vpOrigin->resetTemporaryVisibility();
                if (property("studioPlanes").toBool()) {
                    vpOrigin->setTemporaryVisibility(Gui::DatumElement::Planes);
                    vpOrigin->setPlaneLabelVisibility(true);
                }
            }
        }
        catch (const Base::Exception& ex) {
            Base::Console().error("TaskPatternParameters: Error accessing origin axes: %s\n", ex.what());
        }
    }
}

void TaskPatternParameters::enterReferenceSelectionMode()
{
    if (selectionMode == SelectionMode::Reference) {
        return;
    }

    hideObject();  // Hide the pattern feature itself
    showBase();    // Show the base features/body
    Gui::Selection().clearSelection();

    bool isPolar = getObject<PartDesign::PolarPattern>();

    AllowSelectionFlags commonReferences = AllowSelection::EDGE | AllowSelection::PLANAR;
    if (isPolar) {
        addReferenceSelectionGate(commonReferences | AllowSelection::CIRCLE);
    }
    else {
        // A straight edge, a planar face (its normal) or a cylindrical face (its axis), as
        // Onshape's Direction takes them (FreeCAD-CH ops#640 rank 27, E-2)
        addDirectionSelectionGate(commonReferences | AllowSelection::FACE);
    }
    Gui::getMainWindow()->showMessage(
        tr("Select a direction reference (edge, face, datum line)")
    );  // User feedback
}

void TaskPatternParameters::exitReferenceSelectionMode()
{
    exitSelectionMode();

    hideBase();
    Gui::getMainWindow()->showMessage(QString());
    activeDirectionWidget = nullptr;
}


// --- SLOTS ---

void TaskPatternParameters::onUpdateViewTimer()
{
    // Recompute is triggered when parameters change and this timer fires
    setupTransaction();  // Group potential property changes
    recomputeFeature();

    updateSpacingLabels();

    updateUI();
}

void TaskPatternParameters::onParameterWidgetRequestReferenceSelection()
{
    // The embedded widget wants to enter reference selection mode
    activeDirectionWidget = parametersWidget;
    enterReferenceSelectionMode();
    selectionMode = SelectionMode::Reference;
}

void TaskPatternParameters::onParameterWidgetRequestReferenceSelection2()
{
    // The embedded widget wants to enter reference selection mode
    activeDirectionWidget = parametersWidget2;
    enterReferenceSelectionMode();
    selectionMode = SelectionMode::Reference;
}

void TaskPatternParameters::onParameterWidgetParametersChanged()
{
    // A parameter in the embedded widget changed, trigger a recompute
    if (blockUpdate) {
        return;  // Avoid loops if change originated from Task update
    }
    kickUpdateViewTimer();  // Debounce recompute
}

void TaskPatternParameters::onReferencesRepaired()
{
    updateUI();
}

void TaskPatternParameters::cancelReferencePick()
{
    if (selectionMode != SelectionMode::None) {
        exitReferenceSelectionMode();
    }
    updateUI();
}

void TaskPatternParameters::onUpdateView(bool on)
{
    // This might be less relevant now if recomputes are triggered by parametersChanged
    blockUpdate = !on;
    if (on) {
        kickUpdateViewTimer();
    }
}

void TaskPatternParameters::kickUpdateViewTimer() const
{
    updateViewTimer->start();
}

void TaskPatternParameters::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    // Handle selection ONLY when in reference selection mode
    if (selectionMode == SelectionMode::None || msg.Type != Gui::SelectionChanges::AddSelection) {
        return;
    }

    auto patternObj = getObject();
    if (!patternObj) {
        return;
    }

    std::vector<std::string> directions;
    App::DocumentObject* selObj = nullptr;
    bool answered = false;
    getReferencedSelection(patternObj, msg, selObj, directions, &answered);
    if (!selObj) {
        // FreeCAD-CH (ops#395 5): a refused copy was said in its message box
        if (answered) {
            return;
        }
        Base::Console().warning(
            tr("Invalid selection. Select an edge, planar face, or datum line.").toStdString().c_str()
        );
        return;
    }

    // Note: ReferenceSelection has already checked the selection for validity
    if (selectionMode == SelectionMode::Reference || selObj->isDerivedFrom<App::Line>()) {
        setupTransaction();

        if (patternObj->isDerivedFrom<PartDesign::LinearPattern>()) {
            auto* linearPattern = static_cast<PartDesign::LinearPattern*>(patternObj);
            if (activeDirectionWidget == parametersWidget) {
                linearPattern->Direction.setValue(selObj, directions);
            }
            else {
                linearPattern->Direction2.setValue(selObj, directions);
            }
        }
        else if (patternObj->isDerivedFrom<PartDesign::PolarPattern>()) {
            auto* polarPattern = static_cast<PartDesign::PolarPattern*>(patternObj);
            polarPattern->Axis.setValue(selObj, directions);
        }
        recomputeFeature();
        updateUI();
    }
    exitReferenceSelectionMode();
}

TaskPatternParameters::~TaskPatternParameters()
{
    clearSkipDots();
    showOriginAxes(false);         // Clean up temporary visibility
    exitReferenceSelectionMode();  // Ensure gates are removed etc.
    // ui unique_ptr handles deletion
    // parametersWidget is deleted by Qt parent mechanism if added to layout correctly
}

void TaskPatternParameters::apply()
{
    auto pattern = getObject();
    if (!pattern || !parametersWidget) {
        return;
    }

    std::vector<std::string> dirs;
    App::DocumentObject* obj = nullptr;
    parametersWidget->getAxis(obj, dirs);
    std::string direction = buildLinkSingleSubPythonStr(obj, dirs);

    bool isLinear = pattern->isDerivedFrom<PartDesign::LinearPattern>();
    const char* propName = isLinear ? "Direction = " : "Axis = ";
    auto linkProp = freecad_cast<App::PropertyLinkSub*>(
        pattern->getPropertyByName(isLinear ? "Direction" : "Axis")
    );

    // The links are written only when the panel changed them (ops#127).
    if (!linkProp || !isSameLink(*linkProp, obj, dirs)) {
        FCMD_OBJ_CMD(pattern, propName << direction.c_str());
    }
    FCMD_OBJ_CMD(pattern, "Reversed = " << parametersWidget->getReverse());
    FCMD_OBJ_CMD(pattern, "Mode = " << parametersWidget->getMode());
    parametersWidget->applyQuantitySpinboxes();

    FCMD_OBJ_CMD(pattern, "SpacingPattern = " << parametersWidget->getSpacingPatternsAsString());

    if (parametersWidget2) {
        parametersWidget2->getAxis(obj, dirs);
        direction = buildLinkSingleSubPythonStr(obj, dirs);

        auto linearPattern = freecad_cast<PartDesign::LinearPattern*>(pattern);
        if (!linearPattern || !isSameLink(linearPattern->Direction2, obj, dirs)) {
            FCMD_OBJ_CMD(pattern, "Direction2 = " << direction.c_str());
        }
        FCMD_OBJ_CMD(pattern, "Reversed2 = " << parametersWidget2->getReverse());
        FCMD_OBJ_CMD(pattern, "Mode2 = " << parametersWidget2->getMode());
        parametersWidget2->applyQuantitySpinboxes();

        FCMD_OBJ_CMD(pattern, "SpacingPattern2 = " << parametersWidget2->getSpacingPatternsAsString());
    }

    // The instances to skip, as typed (ops#640 rank 8)
    if (auto skipped = findChild<QLineEdit*>(QStringLiteral("editSkipped"))) {
        auto skippedProp = freecad_cast<App::PropertyIntegerList*>(
            pattern->getPropertyByName("SkippedInstances")
        );
        const std::string list = skippedPython(skipped->text(), isLinear);
        if (skippedProp && list != skippedPython(skippedText(skippedProp->getValues(), isLinear), isLinear)) {
            FCMD_OBJ_CMD(pattern, "SkippedInstances = " << list);
        }
    }

    // The user may have changed a value and immediately hit 'OK' or Enter.
    // This triggers accept() before the update timer for the 3D view has a
    // chance to fire. If the timer is active, it means a recompute is
    // pending.
    if (updateViewTimer && updateViewTimer->isActive()) {
        updateViewTimer->stop();
        recomputeFeature();
    }
}

void TaskPatternParameters::updateSpacingLabels()
{
    Base::Vector3d startPoint = getStartPoint();

    if (auto* linearPattern = getObject<PartDesign::LinearPattern>()) {
        // Handle first direction widget
        if (parametersWidget) {
            // Get the direction vector using the feature's public method.
            // calculateOffsetVector returns a vector whose magnitude is one step in 'Extent' mode,
            // or a normalized vector in 'Spacing' mode. We normalize it to be safe.
            gp_Vec offset1 = linearPattern->calculateOffsetVector(Part::LinearPatternDirection::First);
            Base::Vector3d direction1(0, 0, 1);  // Default direction
            if (offset1.Magnitude() > Precision::Confusion()) {
                offset1.Normalize();
                direction1.x = offset1.X();
                direction1.y = offset1.Y();
                direction1.z = offset1.Z();
            }
            parametersWidget->updateSpacingLabels(startPoint, direction1);
        }

        // Handle second direction widget
        if (parametersWidget2) {
            gp_Vec offset2 = linearPattern->calculateOffsetVector(Part::LinearPatternDirection::Second);
            Base::Vector3d direction2(0, 1, 0);  // Default direction
            if (offset2.Magnitude() > Precision::Confusion()) {
                offset2.Normalize();
                direction2.x = offset2.X();
                direction2.y = offset2.Y();
                direction2.z = offset2.Z();
            }
            parametersWidget2->updateSpacingLabels(startPoint, direction2);
        }
        return;
    }

    if (auto* polarPattern = getObject<PartDesign::PolarPattern>()) {
        gp_Ax2 axisDef = polarPattern->getRotation();
        axisDef.Transform(polarPattern->getLocation().Transformation());

        gp_Pnt center_gp = axisDef.Location();
        gp_Dir axis_gp = axisDef.Direction();
        Base::Vector3d center(center_gp.X(), center_gp.Y(), center_gp.Z());
        Base::Vector3d axis(axis_gp.X(), axis_gp.Y(), axis_gp.Z());

        // Calculate X-axis for angular reference in the rotation plane
        Base::Rotation labelRot(Base::Vector3d(0.0, 0.0, 1.0), axis);
        Base::Vector3d xDir;
        labelRot.multVec(Base::Vector3d(1.0, 0.0, 0.0), xDir);

        Base::Vector3d startRadiusVec = startPoint - center;
        double radius = startRadiusVec.Length();
        if (radius < Precision::Confusion()) {
            radius = 1.0;
        }

        double initialAngle_rad = 0.0;
        Base::Vector3d projectedRadiusVec = startRadiusVec - (startRadiusVec.Dot(axis)) * axis;
        if (projectedRadiusVec.Length() > 1e-6) {
            initialAngle_rad = xDir.GetAngleOriented(projectedRadiusVec, axis);
        }

        if (parametersWidget) {
            parametersWidget->updateSpacingLabels(center, axis, radius, initialAngle_rad);
        }
    }
}

Base::Vector3d TaskPatternParameters::getStartPoint() const
{
    Base::Vector3d startPoint(0, 0, 0);

    auto* pattern = dynamic_cast<PartDesign::Transformed*>(getObject());
    if (!pattern) {
        return startPoint;
    }

    std::vector<App::DocumentObject*> originals = pattern->getOriginals();
    if (!originals.empty()) {
        BRep_Builder builder;
        TopoDS_Compound compoundShape;
        builder.MakeCompound(compoundShape);

        // 2. Collect the "delta" shapes from each original feature.
        for (App::DocumentObject* obj : originals) {
            // We are only interested in additive/subtractive features.
            if (auto* addSubFeature = dynamic_cast<PartDesign::FeatureAddSub*>(obj)) {
                const Part::TopoShape& deltaShape = addSubFeature->AddSubShape.getShape();
                if (!deltaShape.getShape().IsNull()) {
                    TopoDS_Shape shape = deltaShape.getShape();
                    shape.Move(addSubFeature->getLocation());
                    builder.Add(compoundShape, shape);
                }
            }
        }

        // 3. If we collected any shapes, calculate the center of their combined bounding box.
        if (!compoundShape.IsNull()) {
            try {
                Bnd_Box bndBox;
                BRepBndLib::Add(compoundShape, bndBox);
                if (!bndBox.IsVoid()) {
                    double xmin, ymin, zmin, xmax, ymax, zmax;
                    bndBox.Get(xmin, ymin, zmin, xmax, ymax, zmax);
                    startPoint.x = (xmin + xmax) / 2.0;
                    startPoint.y = (ymin + ymax) / 2.0;
                    startPoint.z = (zmin + zmax) / 2.0;
                }
            }
            catch (const Base::Exception& e) {
                Base::Console().warning(
                    "Could not calculate center of patterned features: %s\n",
                    e.what()
                );
                // startPoint remains (0,0,0) as a fallback.
            }
        }
    }
    return startPoint;
}

void TaskPatternParameters::updateParallelBanner()
{
    auto* linear = getObject<PartDesign::LinearPattern>();
    if (!linear || !parallelBanner) {
        return;
    }
    // Both directions in use with a reference each: the offsets are zero otherwise
    bool parallel = false;
    try {
        const gp_Vec first = linear->calculateOffsetVector(Part::LinearPatternDirection::First);
        const gp_Vec second = linear->calculateOffsetVector(Part::LinearPatternDirection::Second);
        parallel = first.Magnitude() > Precision::Confusion()
            && second.Magnitude() > Precision::Confusion()
            && first.IsParallel(second, Precision::Angular());
    }
    catch (const Base::Exception&) {
    }
    catch (const Standard_Failure&) {
    }
    parallelBanner->setVisible(parallel);
}

void TaskPatternParameters::clearSkipDots()
{
    if (skipDots) {
        if (dotViewer) {
            auto* root = static_cast<SoSeparator*>(dotViewer->getSceneGraph());
            const int index = root->findChild(skipDots);
            if (index >= 0) {
                root->removeChild(index);
            }
        }
        skipDots->unref();
        skipDots = nullptr;
    }
    if (dotCallback && dotViewer) {
        dotViewer->removeEventCallback(SoMouseButtonEvent::getClassTypeId(), skipDotCallback, this);
    }
    dotCallback = false;
    dots.clear();
}

void TaskPatternParameters::updateSkipDots()
{
    clearSkipDots();
    auto* linear = getObject<PartDesign::LinearPattern>();
    auto* skip = findChild<QCheckBox*>(QStringLiteral("checkSkip"));
    if (skip) {
        skip->setProperty("dots", QString());
    }
    if (!linear || !skip || !skip->isChecked() || !dotViewer) {
        return;
    }
    // A direction in use without its reference: the pattern fails ("Select a pattern
    // direction."), and its steps are zero, so no dots
    if ((parametersWidget && parametersWidget->isDirectionMissing())
        || (parametersWidget2 && parametersWidget2->isDirectionMissing())) {
        return;
    }

    // The grid as getTransformations() makes it: the steps from the seed's uncentered grid
    // (Direction2 fastest), mirrored through the seed along a centered direction, whose count is
    // per side, the seed included (oracle 9j)
    const int first = std::max(static_cast<int>(linear->Occurrences.getValue()), 1);
    const int second = std::max(static_cast<int>(linear->Occurrences2.getValue()), 1);
    std::vector<gp_Trsf> grid;
    try {
        const std::list<gp_Trsf> list = linear->calculateTransformations();
        grid.assign(list.begin(), list.end());
    }
    catch (const Base::Exception&) {
    }
    catch (const Standard_Failure&) {
    }
    if (grid.size() != static_cast<std::size_t>(first) * second) {
        return;  // no grid to show (a direction without its reference)
    }
    const auto step = [&](int k, bool alongSecond) {
        const auto index = static_cast<std::size_t>(std::abs(k));
        const gp_Trsf& t = grid[alongSecond ? index : index * static_cast<std::size_t>(second)];
        gp_Vec v(t.TranslationPart());
        return k < 0 ? v.Reversed() : v;
    };
    const bool centered = linear->Centered.getValue();
    const bool centered2 = linear->Centered2.getValue();
    const int rows = centered ? 2 * first - 1 : first;
    const int columns = centered2 ? 2 * second - 1 : second;
    const int middle = centered ? first - 1 : 0;
    const int middle2 = centered2 ? second - 1 : 0;

    const auto& values = linear->SkippedInstances.getValues();
    const auto isSkipped = [&values](long i, long j) {
        for (std::size_t k = 0; k + 1 < values.size(); k += 2) {
            if (values[k] == i && values[k + 1] == j) {
                return true;
            }
        }
        return false;
    };
    const gp_Trsf location = linear->getLocation().Transformation();
    const Base::Vector3d seed = getStartPoint();
    QStringList listed;
    for (int row = 0; row < rows; ++row) {
        for (int column = 0; column < columns; ++column) {
            if (row == middle && column == middle2) {
                continue;  // the seed has no dot
            }
            gp_Vec offset = step(row - middle, false) + step(column - middle2, true);
            offset.Transform(location);
            const Base::Vector3d at = seed + Base::Vector3d(offset.X(), offset.Y(), offset.Z());
            const bool skipped = isSkipped(row, column);
            dots.push_back({row, column, at, skipped});
            listed << QStringLiteral("(%1, %2)%3").arg(row).arg(column).arg(skipped ? "*" : "");
        }
    }
    // For the GUI tests: the dots in order, a skipped one starred
    skip->setProperty("dots", listed.join(QStringLiteral(", ")));
    if (dots.empty()) {
        return;
    }

    skipDots = new SoAnnotation();
    skipDots->ref();
    for (bool hollow : {false, true}) {
        auto* group = new SoSeparator();
        auto* color = new SoBaseColor();
        color->rgb.setValue(0.18F, 0.44F, 0.82F);
        auto* coords = new SoCoordinate3();
        int count = 0;
        for (const auto& dot : dots) {
            if (dot.skipped == hollow) {
                coords->point.set1Value(count++, SbVec3f(dot.at.x, dot.at.y, dot.at.z));
            }
        }
        auto* markers = new SoMarkerSet();
        markers->markerIndex = Gui::Inventor::MarkerBitmaps::getMarkerIndex(
            hollow ? "CIRCLE_LINE" : "CIRCLE_FILLED",
            9
        );
        markers->numPoints = count;
        group->addChild(color);
        group->addChild(coords);
        group->addChild(markers);
        skipDots->addChild(group);
    }
    static_cast<SoSeparator*>(dotViewer->getSceneGraph())->addChild(skipDots);
    dotViewer->addEventCallback(SoMouseButtonEvent::getClassTypeId(), skipDotCallback, this);
    dotCallback = true;
}

int TaskPatternParameters::skipDotAt(const SbVec2s& point) const
{
    if (!dotViewer) {
        return -1;
    }
    // Within a dot's radius and a little more, the nearest
    const double reach = 8.0 * dotViewer->devicePixelRatio();
    int found = -1;
    double best = reach * reach;
    for (std::size_t k = 0; k < dots.size(); ++k) {
        const auto& at = dots[k].at;
        const SbVec2s p = dotViewer->getPointOnViewport(SbVec3f(at.x, at.y, at.z));
        const double dx = p[0] - point[0];
        const double dy = p[1] - point[1];
        const double distance = dx * dx + dy * dy;
        if (distance <= best) {
            best = distance;
            found = static_cast<int>(k);
        }
    }
    return found;
}

void TaskPatternParameters::toggleSkipped(long i, long j)
{
    auto* pattern = getObject();
    auto skippedProp = pattern
        ? freecad_cast<App::PropertyIntegerList*>(pattern->getPropertyByName("SkippedInstances"))
        : nullptr;
    if (!skippedProp) {
        return;
    }
    std::vector<long> values;
    bool found = false;
    const auto& old = skippedProp->getValues();
    for (std::size_t k = 0; k + 1 < old.size(); k += 2) {
        if (old[k] == i && old[k + 1] == j) {
            found = true;
            continue;
        }
        values.push_back(old[k]);
        values.push_back(old[k + 1]);
    }
    if (!found) {
        values.push_back(i);
        values.push_back(j);
    }
    const QString text = skippedText(values, true);
    setupTransaction();
    FCMD_OBJ_CMD(pattern, "SkippedInstances = " << skippedPython(text, true));
    if (auto* field = findChild<QLineEdit*>(QStringLiteral("editSkipped"))) {
        field->setText(text);
    }
    updateSkipDots();
    kickUpdateViewTimer();
}

void TaskPatternParameters::skipDotCallback(void* data, SoEventCallback* node)
{
    auto* self = static_cast<TaskPatternParameters*>(data);
    const auto* event = static_cast<const SoMouseButtonEvent*>(node->getEvent());
    if (event->getButton() != SoMouseButtonEvent::BUTTON1) {
        return;
    }
    if (event->getState() == SoButtonEvent::UP) {
        // The press was a dot's: its release selects nothing either
        if (self->dotPressed) {
            self->dotPressed = false;
            node->setHandled();
        }
        return;
    }
    self->dotPressed = false;
    if (self->selectionMode != SelectionMode::None) {
        return;  // picking a direction
    }
    const int hit = self->skipDotAt(event->getPosition());
    if (hit < 0) {
        return;
    }
    self->dotPressed = true;
    node->setHandled();
    // The scene graph changes after this traversal
    const long i = self->dots[hit].i;
    const long j = self->dots[hit].j;
    QTimer::singleShot(0, self, [self, i, j]() { self->toggleSkipped(i, j); });
}

//**************************************************************************
// TaskDialog Implementation (Remains largely the same)
//**************************************************************************

TaskDlgLinearPatternParameters::TaskDlgLinearPatternParameters(
    ViewProviderTransformed* LinearPatternView
)
    : TaskDlgTransformedParameters(LinearPatternView)  // Use base class constructor
{
    // Create the specific parameter task panel
    parameter = new TaskPatternParameters(LinearPatternView);
    // Add it to the dialog's content list
    Content.push_back(parameter);
    Content.push_back(preview);
}

#include "moc_TaskPatternParameters.cpp"
