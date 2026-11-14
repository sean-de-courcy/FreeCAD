// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Onshape's Delete part dialog (FreeCAD-CH ops#640 rank 30, blind test F48; the feature:
// PartDesign/App/FeatureDeletePart.h)

#include <string>
#include <vector>

#include <Gui/Selection/Selection.h>
#include <Gui/TaskView/TaskDialog.h>

class QLabel;
class QListWidget;

namespace App
{
class Document;
}  // namespace App

namespace PartDesign
{
class Body;
class DeletePart;
}  // namespace PartDesign

namespace PartDesignGui
{

/** The Delete part dialog: "Entities to delete", the parts of one part studio, each with an x;
 * a pick in the 3D view, the Parts list or the Features list adds the part it belongs to, or takes
 * it out when it is listed. A new one is prefilled (Delete on parts under the Onshape keymap); an
 * edit (the Delete part row's Edit) lists its part. OK writes it in one undo step: each part
 * added gets a Delete part feature (at the bar; an edit's at the edited row's place in history),
 * an edit whose part was taken out loses its row. Cancel changes nothing. OK with the list empty
 * keeps the dialog open with a message
 */
class TaskDlgDeletePart: public Gui::TaskView::TaskDialog, public Gui::SelectionObserver
{
    Q_OBJECT

public:
    TaskDlgDeletePart(App::Document* doc,
                      const std::vector<PartDesign::Body*>& parts,
                      PartDesign::DeletePart* feature = nullptr);
    ~TaskDlgDeletePart() override;

    /// Opens the dialog for body once the current event is done, with the other parts asked for
    /// until then (one Delete on several parts); an open Delete part dialog takes them instead
    static void openFor(PartDesign::Body* body);

    /// Adds parts that can be deleted and aren't listed (the others are named in the message)
    void addParts(const std::vector<PartDesign::Body*>& parts);

    bool accept() override;
    bool reject() override;

    QDialogButtonBox::StandardButtons getStandardButtons() const override
    {
        return QDialogButtonBox::Ok | QDialogButtonBox::Cancel;
    }

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    App::Document* document() const;
    PartDesign::DeletePart* edited() const;
    /// Why body can't be listed, or empty
    std::string refusal(const PartDesign::Body* body) const;
    /// Adds or takes out body (a pick)
    void toggle(PartDesign::Body* body);
    void removeName(const std::string& name);
    void fillList();
    /// The selection shows the listed parts, after the current event
    void scheduleSync();
    void showMessage(const QString& text);

    std::string docName;
    std::string featureName;  // the edited Delete part, empty for a new one
    std::vector<std::string> names;  // the listed Bodies
    QListWidget* list = nullptr;
    QLabel* message = nullptr;
    bool syncing = false;
    bool syncPending = false;
};

}  // namespace PartDesignGui
