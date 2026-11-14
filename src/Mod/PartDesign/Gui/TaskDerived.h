// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Onshape's Derived dialog (FreeCAD-CH ops#640 round 6, PartDesign/App/Derived.h)

#include <string>
#include <vector>

#include <Gui/TaskView/TaskDialog.h>

class QCheckBox;
class QComboBox;
class QLabel;
class QListWidget;
class QListWidgetItem;

namespace App
{
class Document;
class Part;
}  // namespace App

namespace PartDesign
{
class FeatureBase;
}

namespace PartDesignGui
{

/// The studio a new feature goes in: the active Body's, else the active App::Part (not an
/// Assembly), else the document's top level (null). False when the active Body is in no studio
bool activeStudio(App::Document* doc, App::Part*& studio);

/** The Derived dialog: a source part studio of this document (not the one the feature goes in) and
 * the parts of it to bring in (all ticked for a new feature [guess]). OK makes the Derived feature
 * in studio, or, with lead, applies the edit of lead's feature, in one undo step; Cancel changes
 * nothing. OK with no part ticked keeps the dialog open with a message
 */
class TaskDlgDerived: public Gui::TaskView::TaskDialog
{
    Q_OBJECT

public:
    TaskDlgDerived(App::Document* doc, App::Part* studio, PartDesign::FeatureBase* lead = nullptr);

    bool accept() override;
    bool reject() override;

    QDialogButtonBox::StandardButtons getStandardButtons() const override
    {
        return QDialogButtonBox::Ok | QDialogButtonBox::Cancel;
    }

private:
    App::Document* document() const;
    App::Part* sourceStudio() const;
    void fillParts(const std::vector<std::string>& ticked);
    void onStudioChanged();
    void onAllClicked(bool checked);
    void onItemChanged(QListWidgetItem* item);
    void updateAll();

    std::string docName;
    std::string studioName;  // where the feature goes: empty for the top level
    std::string leadName;    // the edited feature's lead, empty for a new one
    std::vector<std::string> sourceNames;  // per row of studios: empty for the top level
    QComboBox* studios = nullptr;
    QListWidget* parts = nullptr;
    QCheckBox* all = nullptr;
    QLabel* message = nullptr;
};

}  // namespace PartDesignGui
