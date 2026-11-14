// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD project.

/******************************************************************************
 *                                                                            *
 *   FreeCAD is free software: you can redistribute it and/or modify          *
 *   it under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1            *
 *   of the License, or (at your option) any later version.                   *
 *                                                                            *
 *   FreeCAD is distributed in the hope that it will be useful,               *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty              *
 *   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                  *
 *   See the GNU Lesser General Public License for more details.              *
 *                                                                            *
 *   You should have received a copy of the GNU Lesser General Public         *
 *   License along with FreeCAD. If not, see https://www.gnu.org/licenses     *
 *                                                                            *
 ******************************************************************************/


#pragma once

#include <functional>
#include <memory>
#include <vector>

#include <Mod/PartDesign/App/FeatureFacePattern.h>

#include "EnumFlags.h"
#include "TaskDressUpParameters.h"
#include "ViewProviderFacePattern.h"

class QTimer;
class Ui_TaskFacePatternParameters;

namespace PartGui
{
class PatternParametersWidget;
}

namespace PartDesignGui
{

class ReferenceCombo;
class ReferenceField;

/** FreeCAD-CH (ops#655 T8): the panel of the face patterns. The Base field takes the faces, as
 * Defeaturing's; under it the pattern's own fields: one or two Part pattern widgets (linear),
 * one (circular), or a plane box (mirror). A direction, an axis or a plane is picked through a
 * field of its own that disarms the Base field while it takes the pick and hands it back after,
 * so that a pick sets the reference and doesn't toggle a face.
 */
class TaskFacePatternParameters: public TaskDressUpParameters
{
    Q_OBJECT

public:
    explicit TaskFacePatternParameters(ViewProviderDressUp* DressUpView, QWidget* parent = nullptr);
    ~TaskFacePatternParameters() override;

    void apply() override;
    void onReferencesRepaired() override;
    std::vector<ReferenceField*> referenceFields() const override;

protected:
    void changeEvent(QEvent* e) override;
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;

private Q_SLOTS:
    void onParametersChanged();
    void onUpdateTimer();

private:
    void addLinearFields(PartDesign::FaceLinearPattern* pattern);
    void addPolarFields(PartDesign::FacePolarPattern* pattern);
    void addMirroredFields(PartDesign::FaceMirrored* pattern);
    void addCheckBox(const char* property, const QString& text);
    /// A field for the pick of \a property's reference; \a widget's combo shows the result
    ReferenceField* createPickField(
        const char* property,
        AllowSelectionFlags flags,
        const QString& kinds,
        PartGui::PatternParametersWidget* widget,
        std::function<void(App::DocumentObject*, const std::vector<std::string>&)>* writerOut = nullptr
    );
    /// A Part pattern widget for \a property's reference, \a title over it (empty: none)
    PartGui::PatternParametersWidget* createWidget(
        bool linear,
        const char* property,
        AllowSelectionFlags flags,
        const QString& kinds,
        const QString& title
    );
    void updateWidgets();
    /// The planes box: the Body origin's planes, then "Select reference..."
    void fillPlaneChoices();

    std::unique_ptr<Ui_TaskFacePatternParameters> ui;
    QTimer* updateTimer = nullptr;
    std::vector<PartGui::PatternParametersWidget*> widgets;
    /// The fields of the pattern's references, hidden but for the plane's
    std::vector<ReferenceField*> pickFields;
    ReferenceCombo* planeCombo = nullptr;
};

class TaskDlgFacePatternParameters: public TaskDlgDressUpParameters
{
    Q_OBJECT

public:
    explicit TaskDlgFacePatternParameters(ViewProviderFacePattern* DressUpView);
    ~TaskDlgFacePatternParameters() override;

    bool accept() override;
};

}  // namespace PartDesignGui
