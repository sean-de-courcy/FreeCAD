// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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


#include <string_view>
#include <vector>

#include <Standard_Failure.hxx>

#include <App/Document.h>
#include <Gui/Application.h>
#include <Gui/Command.h>
#include <Gui/Control.h>
#include <Gui/ForkKeymap.h>
#include <Gui/MDIView.h>
#include <Gui/Selection/Selection.h>
#include <Mod/Part/App/Attacher.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Sketcher/Gui/Workbench.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureMultiTransform.h>

#include "FeaturesView.h"
#include "TaskReferences.h"
#include "Utils.h"
#include "Workbench.h"
#include "WorkflowManager.h"

using namespace PartDesignGui;
namespace sp = std::placeholders;

#if 0  // needed for Qt's lupdate utility
    qApp->translate("Workbench", "&Sketch");
    //
    qApp->translate("Workbench", "&Part Design");
    qApp->translate("Workbench", "Datums");
    qApp->translate("Workbench", "Additive Features");
    qApp->translate("Workbench", "Subtractive Features");
    qApp->translate("Workbench", "Dress-Up Features");
    qApp->translate("Workbench", "Transformation Features");
    qApp->translate("Workbench", "Sprocket…");
    qApp->translate("Workbench", "Involute Gear");

    qApp->translate("Workbench", "Shaft Design Wizard");
    qApp->translate("Gui::TaskView::TaskWatcherCommands", "Face Tools");
    qApp->translate("Gui::TaskView::TaskWatcherCommands", "Edge Tools");
    qApp->translate("Gui::TaskView::TaskWatcherCommands", "Boolean Tools");
    qApp->translate("Gui::TaskView::TaskWatcherCommands", "Helper Tools");
    qApp->translate("Gui::TaskView::TaskWatcherCommands", "Modeling Tools");
    qApp->translate("Gui::TaskView::TaskWatcherCommands", "Create Geometry");
    //
    qApp->translate("Workbench", "Measure");
    qApp->translate("Workbench", "Refresh");
    qApp->translate("Workbench", "Toggle 3D");
    qApp->translate("Workbench", "Part Design Helper");
    qApp->translate("Workbench", "Part Design Modeling");
#endif

/// @namespace PartDesignGui @class Workbench
TYPESYSTEM_SOURCE(PartDesignGui::Workbench, Gui::StdWorkbench)

Workbench::Workbench() = default;

Workbench::~Workbench()
{
    WorkflowManager::destruct();
}

namespace
{

/// The Tasks panel's "Start Part: New Body" with nothing selected: not under the Onshape keymap,
/// which has no such panel (ops#640 round 6, J2); asked each time, so a keymap change applies
class StartPartWatcher: public Gui::TaskView::TaskWatcherCommandsEmptySelection
{
public:
    using TaskWatcherCommandsEmptySelection::TaskWatcherCommandsEmptySelection;

    bool shouldShow() override
    {
        return !Gui::ForkKeymap::isOnshape() && TaskWatcherCommandsEmptySelection::shouldShow();
    }
};

/// "Face" or "Edge" when every selected sub-element is one of that kind, on one object; else ""
std::string_view subElementKind(const std::vector<Gui::SelectionSingleton::SelObj>& selection)
{
    std::string_view kind;
    for (const auto& sel : selection) {
        std::string_view sub = sel.SubName ? sel.SubName : "";
        std::string_view thisKind;
        if (sub.starts_with("Face")) {
            thisKind = "Face";
        }
        else if (sub.starts_with("Edge")) {
            thisKind = "Edge";
        }
        if (thisKind.empty() || sel.pObject != selection.front().pObject
            || (!kind.empty() && thisKind != kind)) {
            return {};
        }
        kind = thisKind;
    }
    return kind;
}

/// The Body PartDesign's commands act in: the active Body or, with none active, the document's
/// only Body, which they activate themselves (PartDesignGui::getBody with autoActivate); nullptr
/// where they would ask instead (a dialog)
PartDesign::Body* commandBody()
{
    if (PartDesign::Body* active = PartDesignGui::getBody(false, false)) {
        return active;
    }
    Gui::MDIView* view = Gui::Application::Instance->activeView();
    App::Document* doc = view ? view->getAppDocument() : nullptr;
    if (!doc) {
        return nullptr;
    }
    const auto bodies = doc->getObjectsOfType<PartDesign::Body>();
    return bodies.size() == 1 ? bodies.front() : nullptr;
}

/// Whether sub names a planar face of obj's shape: Sketch on face (PartDesign_NewSketch) refuses
/// the others
bool isPlanarFace(App::DocumentObject* obj, const char* sub)
{
    auto feature = freecad_cast<Part::Feature*>(obj);
    if (!feature || !sub || !*sub) {
        return false;
    }
    try {
        const Part::TopoShape face(feature->Shape.getShape().getSubShape(sub, /*silent=*/true));
        return !face.isNull() && face.isPlanar(Attacher::AttachEnginePlane::planarPrecision());
    }
    catch (const Base::Exception&) {
        return false;
    }
    catch (const Standard_Failure&) {
        return false;
    }
}

/// Whether every selected object is a Body or one of its features, all of one Body: Onshape's
/// Delete part deletes that Body (the fork's Delete part feature, ops#635)
bool selectionIsInOnePart(const std::vector<Gui::SelectionSingleton::SelObj>& selection)
{
    PartDesign::Body* part = nullptr;
    for (const auto& sel : selection) {
        App::DocumentObject* obj = sel.pObject;
        auto body = freecad_cast<PartDesign::Body*>(obj);
        if (!body) {
            body = PartDesignGui::getBodyFor(obj, false, false, true);
            if (!body || !body->hasObject(obj)) {
                return false;
            }
        }
        if (part && part != body) {
            return false;
        }
        part = body;
    }
    return part != nullptr;
}

}  // namespace

void Workbench::setupContextMenu(const char* recipient, Gui::MenuItem* item) const
{
    auto selection = Gui::Selection().getSelection();
    // FreeCAD-CH (ops#640): in the 3D view, under the fork's keymap, Onshape's menu: the body's
    // own entries (Move tip, the roll-back bar) go under a More submenu, which Gui::StdWorkbench
    // fills and puts last. Without the keymap the menu is FreeCAD's.
    const bool inView = strcmp(recipient, "View") == 0;
    const bool onshape = inView && Gui::ForkKeymap::isOnshape();
    Gui::MenuItem* more = nullptr;
    Gui::MenuItem* bodyItem = item;
    if (onshape) {
        more = new Gui::MenuItem;
        more->setCommand("More");
        bodyItem = more;
    }
    // Add move Tip Command
    if (!selection.empty()) {
        App::DocumentObject* feature = selection.front().pObject;
        PartDesign::Body* body = nullptr;

        body = PartDesignGui::getBodyFor(feature, false, false, true);
        // lote of assertion so feature should be marked as a tip
        if (selection.size() == 1 && feature && body
            && (feature->isDerivedFrom<PartDesign::Feature>()
                || (feature->isDerivedFrom<Part::Feature>()
                    && body->BaseFeature.getValue() == feature))) {
            *bodyItem << "PartDesign_MoveTip";
        }
        // The roll-back bar (ops#127): on a feature, sketch or datum of a body, and to the end
        // while the body is rolled back
        if (selection.size() == 1 && feature && body && body->hasObject(feature)) {
            *bodyItem << "PartDesign_RollTo";
        }
        // A selected Body is its own (getBodyFor finds no Body containing it)
        auto rollBody = body ? body : freecad_cast<PartDesign::Body*>(feature);
        if (selection.size() == 1 && rollBody && rollBody->isRolledBack()) {
            *bodyItem << "PartDesign_RollToEnd";
        }

        if (onshape && feature && Gui::Selection().hasPreselection()) {
            // Onshape's first entries, on an entity under the cursor (no preselection is empty
            // space) and only where the commands take the pick: Sketch on face on one planar
            // face, Fillet and Chamfer on faces or edges of a solid feature of any part, the
            // active Body or not (ops#640 rank 14: the dress-up goes into the pick's Body; a
            // sketch's edges would make a failing Fillet)
            const std::string_view kind = subElementKind(selection);
            PartDesign::Body* target = kind.empty() ? nullptr : commandBody();
            // the sketch goes into target without a dialog: it holds the face's feature, or
            // (ops#325) the feature is a sibling part's of its studio
            if (kind == "Face" && selection.size() == 1 && target
                && (target->hasObject(feature) || PartDesignGui::isStudioSelection(target, feature))
                && isPlanarFace(feature, selection.front().SubName)) {
                *item << "PartDesign_NewSketch";
            }
            // body: the active Body when it holds the feature, else the feature's own
            if (!kind.empty() && body && body->hasObject(feature)
                && (feature->isDerivedFrom<PartDesign::Feature>()
                    || body->BaseFeature.getValue() == feature)) {
                *item << "PartDesign_Fillet" << "PartDesign_Chamfer";
            }
        }

        if (strcmp(recipient, "Tree") == 0) {
            // A guessed, partly resolved or broken reference (ops#127)
            if (selection.size() == 1 && TaskReferences::hasRows(feature)) {
                *item << "PartDesign_RepairReferences";
            }

            Gui::MDIView* activeView = Gui::Application::Instance->activeView();

            if (activeView) {
                if (feature && feature->isDerivedFrom<PartDesign::Body>()) {
                    *item << "Std_ToggleFreeze";
                }

                if (activeView->getAppDocument()->countObjectsOfType<PartDesign::Body>() > 0) {
                    bool addMoveFeature = true;
                    bool addMoveFeatureInTree = (body != nullptr);
                    for (auto sel : selection) {
                        // if at least one selected feature cannot be moved to a body
                        // disable the entry
                        if (addMoveFeature && !PartDesign::Body::isAllowed(sel.pObject)) {
                            addMoveFeature = false;
                        }
                        // if all at least one selected feature doesn't belong to the same body
                        // disable the menu entry
                        if (addMoveFeatureInTree && !body->hasObject(sel.pObject)) {
                            addMoveFeatureInTree = false;
                        }

                        if (!addMoveFeatureInTree && !addMoveFeature) {
                            break;
                        }
                    }
                    if (addMoveFeature) {
                        *item << "PartDesign_MoveFeature";
                    }
                    if (addMoveFeatureInTree) {
                        *item << "PartDesign_MoveFeatureInTree";
                    }
                }
            }
            if (Gui::Selection().countObjectsOfType<PartDesign::Transformed>()
                    - Gui::Selection().countObjectsOfType<PartDesign::MultiTransform>()
                == 1) {
                *item << "PartDesign_MultiTransform";
            }
        }
    }

    if (item->hasItems()) {
        *item << "Separator";
    }
    if (more) {
        if (more->hasItems()) {
            *item << more;
        }
        else {
            delete more;
        }
    }
    Gui::StdWorkbench::setupContextMenu(recipient, item);

    // Onshape's Delete part on a Body or its features: Std_DeletePart deletes the part (Std_Delete
    // on the Body, which ViewProviderBody::onDelete makes a Delete part feature of its history,
    // ops#635); the feature's own Delete stays under More
    if (onshape && !selection.empty() && selectionIsInOnePart(selection)) {
        if (Gui::MenuItem* deleteItem = item->findItem("Std_Delete")) {
            deleteItem->setCommand("Std_DeletePart");
            if (Gui::MenuItem* moreItem = item->findItem("More")) {
                *moreItem << "Std_Delete";
            }
        }
    }
}

void Workbench::activated()
{
    Gui::Workbench::activated();

    WorkflowManager::init();

    std::vector<Gui::TaskView::TaskWatcher*> Watcher;

    const char* Vertex[]
        = {"Part_DatumPoint", "Part_DatumLine", "Part_DatumPlane", "Part_CoordinateSystem", nullptr};
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT Part::Feature SUBELEMENT Vertex COUNT 1..",
        Vertex,
        "Vertex Tools",
        "PartDesign_Body"
    ));

    const char* Edge[] = {
        "PartDesign_Fillet",
        "PartDesign_Chamfer",
        "Part_DatumPoint",
        "Part_DatumLine",
        "Part_DatumPlane",
        "Part_CoordinateSystem",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT Part::Feature SUBELEMENT Edge COUNT 1..",
        Edge,
        "Edge Tools",
        "PartDesign_Body"
    ));

    const char* Face[] = {
        "PartDesign_NewSketch",
        "PartDesign_Fillet",
        "PartDesign_Chamfer",
        "PartDesign_Draft",
        "PartDesign_Thickness",
        "PartDesign_Defeaturing",
        "Part_DatumPoint",
        "Part_DatumLine",
        "Part_DatumPlane",
        "Part_CoordinateSystem",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT Part::Feature SUBELEMENT Face COUNT 1",
        Face,
        "Face Tools",
        "PartDesign_Body"
    ));

    const char* Body[] = {"PartDesign_NewSketch", nullptr};
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT PartDesign::Body COUNT 1",
        Body,
        "Helper Tools",
        "PartDesign_Body"
    ));

    const char* Body2[] = {
        "PartDesign_Boolean",
        "PartDesign_MergeParts",
        "PartDesign_Split",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT PartDesign::Body COUNT 1..",
        Body2,
        "Boolean Tools",
        "PartDesign_Body"
    ));

    const char* Plane1[] = {
        "PartDesign_NewSketch",
        "Part_DatumPoint",
        "Part_DatumLine",
        "Part_DatumPlane",
        "Part_CoordinateSystem",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT App::Plane COUNT 1",
        Plane1,
        "Helper Tools",
        "PartDesign_Body"
    ));

    const char* Plane2[] = {
        "PartDesign_NewSketch",
        "Part_DatumPoint",
        "Part_DatumLine",
        "Part_DatumPlane",
        "Part_CoordinateSystem",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT PartDesign::Plane COUNT 1",
        Plane2,
        "Helper Tools",
        "PartDesign_Body"
    ));

    const char* Line[] = {"Part_DatumPoint", "Part_DatumLine", "Part_DatumPlane", nullptr};
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT PartDesign::Line COUNT 1",
        Line,
        "Helper Tools",
        "PartDesign_Body"
    ));

    const char* Point[]
        = {"Part_DatumPoint", "Part_DatumLine", "Part_DatumPlane", "Part_CoordinateSystem", nullptr};
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT PartDesign::Point COUNT 1",
        Point,
        "Helper Tools",
        "PartDesign_Body"
    ));

    const char* NoSel[] = {"PartDesign_Body", nullptr};
    Watcher.push_back(
        new StartPartWatcher(NoSel, "Start Part", "Part_Box_Parametric")
    );

    const char* Faces[] = {
        "PartDesign_Fillet",
        "PartDesign_Chamfer",
        "PartDesign_Draft",
        "PartDesign_Thickness",
        "PartDesign_Defeaturing",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT Part::Feature SUBELEMENT Face COUNT 2..",
        Faces,
        "Face Tools",
        "PartDesign_Body"
    ));

    const char* Sketch[] = {
        "PartDesign_NewSketch",
        "PartDesign_Pad",
        "PartDesign_Pocket",
        "PartDesign_Hole",
        "PartDesign_Revolution",
        "PartDesign_Groove",
        "PartDesign_AdditiveLoft",
        "PartDesign_SubtractiveLoft",
        "PartDesign_AdditivePipe",
        "PartDesign_SubtractivePipe",
        "PartDesign_AdditiveHelix",
        "PartDesign_SubtractiveHelix",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT Sketcher::SketchObject COUNT 1",
        Sketch,
        "Modeling Tools",
        "PartDesign_Body"
    ));

    const char* Sketches[] = {
        "PartDesign_AdditiveLoft",
        "PartDesign_SubtractiveLoft",
        "PartDesign_AdditivePipe",
        "PartDesign_SubtractivePipe",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT Sketcher::SketchObject COUNT 2..",
        Sketches,
        "Modeling tools",
        "PartDesign_Body"
    ));

    const char* ShapeBinder[] = {
        "PartDesign_Pad",
        "PartDesign_Pocket",
        "PartDesign_Revolution",
        "PartDesign_Groove",
        "PartDesign_AdditiveLoft",
        "PartDesign_SubtractiveLoft",
        "PartDesign_AdditivePipe",
        "PartDesign_SubtractivePipe",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT PartDesign::ShapeBinder COUNT 1",
        ShapeBinder,
        "Modeling tools",
        "PartDesign_Body"
    ));

    const char* SubShapeBinder[] = {
        "PartDesign_Pad",
        "PartDesign_Pocket",
        "PartDesign_Revolution",
        "PartDesign_Groove",
        "PartDesign_AdditiveLoft",
        "PartDesign_SubtractiveLoft",
        "PartDesign_AdditivePipe",
        "PartDesign_SubtractivePipe",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT PartDesign::SubShapeBinder COUNT 1",
        SubShapeBinder,
        "Modeling tools",
        "PartDesign_Body"
    ));

    const char* Transformed[] = {
        "PartDesign_Mirrored",
        "PartDesign_LinearPattern",
        "PartDesign_PolarPattern",
        "PartDesign_CurvePattern",
        "PartDesign_MultiTransform",
        // FreeCAD-CH (ops#655 T8): the face patterns
        "PartDesign_FaceLinearPattern",
        "PartDesign_FacePolarPattern",
        "PartDesign_FaceMirrored",
        nullptr
    };
    Watcher.push_back(new Gui::TaskView::TaskWatcherCommands(
        "SELECT PartDesign::SketchBased",
        Transformed,
        "Transformation Tools",
        "PartDesign_MultiTransform"
    ));

    // FreeCAD-CH (ops#640 polish P9): Onshape shows no command boxes in its panel when no
    // dialog is open, whatever is selected
    if (Gui::ForkKeymap::isOnshape()) {
        for (Gui::TaskView::TaskWatcher* watcher : Watcher) {
            delete watcher;
        }
        Watcher.clear();
    }
    addTaskWatcher(Watcher);
    if (App::GetApplication()
            .GetUserParameter()
            .GetGroup("BaseApp")
            ->GetGroup("Preferences")
            ->GetGroup("Mod/PartDesign")
            ->GetBool("SwitchToTask", true)) {
        Gui::Control().showTaskView();
    }
    // FreeCAD-CH (ops#602): the Features and Parts lists in place of the Model panel's tree
    FeaturesView::enterPartDesign();
}

void Workbench::deactivated()
{
    // FreeCAD-CH (ops#602): the Model panel's tree comes back
    FeaturesView::leavePartDesign();
    removeTaskWatcher();
    // reset the active Body
    Gui::Command::doCommand(Gui::Command::Doc, "import PartDesignGui");

    Gui::Workbench::deactivated();
}

Gui::MenuItem* Workbench::setupMenuBar() const
{
    Gui::MenuItem* root = StdWorkbench::setupMenuBar();
    Gui::MenuItem* item = root->findItem("&Windows");

    // FreeCAD-CH (ops#602): the model tree in place of the Features list, after View > Panels
    if (Gui::MenuItem* view = root->findItem("&View")) {
        auto tree = new Gui::MenuItem;
        tree->setCommand("PartDesign_ToggleModelTree");
        Gui::MenuItem* panels = view->findItem("Std_DockViewMenu");
        Gui::MenuItem* next = panels ? view->afterItem(panels) : nullptr;
        if (!next || !view->insertItem(next, tree)) {
            view->appendItem(tree);
        }
    }

    // add another top level menu left besides the Part Design menu for the Sketcher commands
    Gui::MenuItem* sketch = new Gui::MenuItem;
    root->insertItem(item, sketch);
    sketch->setCommand("&Sketch");

    *sketch << "PartDesign_NewSketch"
            << "Sketcher_EditSketch"
            << "Sketcher_MapSketch"
            << "Sketcher_ReorientSketch"
            << "Sketcher_ValidateSketch"
            << "Sketcher_MergeSketches"
            << "Sketcher_MirrorSketch";

    Gui::MenuItem* part = new Gui::MenuItem;
    root->insertItem(item, part);
    part->setCommand("&Part Design");

    // additives
    Gui::MenuItem* additives = new Gui::MenuItem;
    additives->setCommand("Additive Features");

    *additives << "PartDesign_Pad"
               << "PartDesign_Revolution"
               << "PartDesign_AdditiveLoft"
               << "PartDesign_AdditivePipe"
               << "PartDesign_AdditiveHelix";

    // subtractives
    Gui::MenuItem* subtractives = new Gui::MenuItem;
    subtractives->setCommand("Subtractive Features");

    *subtractives << "PartDesign_Pocket"
                  << "PartDesign_Hole"
                  << "PartDesign_Groove"
                  << "PartDesign_SubtractiveLoft"
                  << "PartDesign_SubtractivePipe"
                  << "PartDesign_SubtractiveHelix";

    // transformations
    Gui::MenuItem* transformations = new Gui::MenuItem;
    transformations->setCommand("Transformation Features");

    *transformations << "PartDesign_Mirrored"
                     << "PartDesign_LinearPattern"
                     << "PartDesign_PolarPattern"
                     << "PartDesign_CurvePattern"
                     << "PartDesign_MultiTransform"
                     // FreeCAD-CH (ops#655 T8): the face patterns
                     << "PartDesign_FaceLinearPattern"
                     << "PartDesign_FacePolarPattern"
                     << "PartDesign_FaceMirrored";

    // dressups
    Gui::MenuItem* dressups = new Gui::MenuItem;
    dressups->setCommand("Dress-Up Features");

    *dressups << "PartDesign_Fillet"
              << "PartDesign_Chamfer"
              << "PartDesign_Draft"
              << "PartDesign_Thickness"
              << "PartDesign_Defeaturing";

    *part << "PartDesign_Body"
          << "Separator"
          << "PartDesign_ShapeBinder"
          << "PartDesign_SubShapeBinder"
          << "PartDesign_Clone"
          << "Separator" << additives << "PartDesign_CompPrimitiveAdditive"
          << "Separator" << subtractives << "PartDesign_CompPrimitiveSubtractive"
          << "Separator" << dressups << "Separator" << transformations << "Separator"
          << "PartDesign_Boolean"
          << "PartDesign_MergeParts"
          << "PartDesign_Split"
          << "PartDesign_Derived"
          << "PartDesign_DerivedFromFile"  // FreeCAD-CH, notes/derived-design.md
          << "PartDesign_DerivedRefresh"
          << "Separator"
          << "Materials_InspectAppearance"
          << "Materials_InspectMaterial"
          << "Separator"
          << "Part_CheckGeometry"
          << "Separator"
          << "PartDesign_InvoluteGear"
          << "PartDesign_Sprocket";

    // For 0.13 a couple of python packages like numpy, matplotlib and others
    // are not deployed with the installer on Windows. Thus, the WizardShaft is
    // not deployed either hence the check for the existence of the command.
    if (Gui::Application::Instance->commandManager().getCommandByName("PartDesign_WizardShaft")) {
        *part << "Separator" << "PartDesign_WizardShaft";
    }

    Gui::MenuItem* view = root->findItem("&View");
    if (view) {
        Gui::MenuItem* appr = view->findItem("Std_RandomColor");
        appr = view->afterItem(appr);
        Gui::MenuItem* face = new Gui::MenuItem();
        face->setCommand("Part_ColorPerFace");
        view->insertItem(appr, face);
        // FreeCAD-CH (ops#194): the keys Shift+H and P need the actions in a visible widget
        if (Gui::MenuItem* visibility = view->findItem("V&isibility")) {
            *visibility << "Separator" << "PartDesign_ToggleSketches" << "PartDesign_TogglePlanes";
        }
    }

    // Replace the "Duplicate selection" menu item with a replacement that is compatible with Body
    item = root->findItem("&Edit");
    Gui::MenuItem* dup = item->findItem("Std_DuplicateSelection");
    dup->setCommand("PartDesign_DuplicateSelection");

    return root;
}

Gui::ToolBarItem* Workbench::setupToolBars() const
{
    Gui::ToolBarItem* root = StdWorkbench::setupToolBars();

    // FreeCAD-CH (ops#605): one toolbar in Onshape's order. Groove and the subtractive Pipe and
    // Loft stay beside their additive twins. Pocket is off it (ops#640, rank 22): Onshape has one
    // Extrude, whose Remove does a pocket; PartDesign_Pocket stays in the Part Design menu and
    // the stock toolbars. The four stock toolbars are kept for those who show them from the
    // toolbar menu.
    Gui::ToolBarItem* part = new Gui::ToolBarItem(root);
    part->setCommand("Features");

    *part << "PartDesign_NewSketch"
          << "PartDesign_Pad"
          << "PartDesign_Revolution"
          << "PartDesign_Groove"
          << "PartDesign_AdditivePipe"
          << "PartDesign_SubtractivePipe"
          << "PartDesign_AdditiveLoft"
          << "PartDesign_SubtractiveLoft"
          << "Separator"
          << "PartDesign_Fillet"
          << "PartDesign_Chamfer"
          << "PartDesign_Draft"
          << "PartDesign_Thickness"
          << "PartDesign_Hole"
          << "Separator"
          << "PartDesign_Mirrored"
          << "PartDesign_LinearPattern"
          << "PartDesign_PolarPattern"
          << "PartDesign_CurvePattern"
          << "PartDesign_MultiTransform"
          // FreeCAD-CH (ops#655 T8): the face patterns
          << "PartDesign_FaceLinearPattern"
          << "PartDesign_FacePolarPattern"
          << "PartDesign_FaceMirrored"
          << "Separator"
          << "PartDesign_Boolean"
          << "PartDesign_Split"
          << "PartDesign_MergeParts"
          << "PartDesign_Derived"  // Onshape's Derived (ops#640 round 6)
          << "Separator"
          << "PartDesign_CompDatums"
          << "PartDesign_AdditiveHelix"
          << "PartDesign_SubShapeBinder"
          << "PartDesign_Body"
          << "PartDesign_CompPrimitiveAdditive"
          << "Std_AddVariable"  // Onshape's Variable tool (ops#640, rank 15; VariablesView.cpp)
          << "Sketcher_ValidateSketch"
          << "PartDesign_ToggleModelTree";  // brings the model tree back (ops#602)

    const auto hidden = Gui::ToolBarItem::DefaultVisibility::Hidden;

    part = new Gui::ToolBarItem(root, hidden);
    part->setCommand("Part Design Helper Features");

    *part << "PartDesign_Body"
          << "PartDesign_ToggleModelTree"
          << "PartDesign_CompSketches"
          << "Sketcher_ValidateSketch"
          << "Part_CheckGeometry"
          << "PartDesign_SubShapeBinder"
          << "PartDesign_Clone";

    part = new Gui::ToolBarItem(root, hidden);
    part->setCommand("Part Design Modeling Features");

    *part << "PartDesign_Pad"
          << "PartDesign_Revolution"
          << "PartDesign_AdditiveLoft"
          << "PartDesign_AdditivePipe"
          << "PartDesign_AdditiveHelix"
          << "PartDesign_CompPrimitiveAdditive"
          << "Separator"
          << "PartDesign_Pocket"
          << "PartDesign_Hole"
          << "PartDesign_Groove"
          << "PartDesign_SubtractiveLoft"
          << "PartDesign_SubtractivePipe"
          << "PartDesign_SubtractiveHelix"
          << "PartDesign_CompPrimitiveSubtractive"
          << "Separator"
          << "PartDesign_Boolean";

    part = new Gui::ToolBarItem(root, hidden);

    part->setCommand("Part Design Dress-Up Features");
    *part << "PartDesign_Fillet"
          << "PartDesign_Chamfer"
          << "PartDesign_Draft"
          << "PartDesign_Thickness"
          << "PartDesign_Defeaturing";

    part = new Gui::ToolBarItem(root, hidden);
    part->setCommand("Part Design Transformation Features");

    *part << "PartDesign_Mirrored"
          << "PartDesign_LinearPattern"
          << "PartDesign_PolarPattern"
          << "PartDesign_CurvePattern"
          << "PartDesign_MultiTransform"
          // FreeCAD-CH (ops#655 T8): the face patterns
          << "PartDesign_FaceLinearPattern"
          << "PartDesign_FacePolarPattern"
          << "PartDesign_FaceMirrored";

    return root;
}
