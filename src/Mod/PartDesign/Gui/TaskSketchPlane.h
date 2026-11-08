// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#pragma once

#include <QCoreApplication>
#include <QPointer>

#include <fastsignals/signal.h>

#include <App/DocumentObserver.h>
#include <Base/Placement.h>
#include <Gui/TaskView/TaskView.h>

#include "RollbackView.h"

class QLabel;

namespace SketcherGui
{
class ViewProviderSketch;
}

namespace PartDesignGui
{

class ReferenceField;

/** FreeCAD-CH (ops#640, rank 2): the Sketch plane box at the top of the sketch dialog, as in
 * Onshape (TaskDlgEditSketch::addContentFactory; only with the Onshape keymap).
 *
 * - One reference field (ReferenceField, Kind::SingleElement) on the sketch's AttachmentSupport:
 *   a plane or a planar face. A pick replaces the plane in one undo step: Flat face, the Body's
 *   origin (MapOrigin), the sketch recomputed. The 2D geometry stays as it is in the sketch, so it
 *   rides along with the plane; the editing view follows the new placement.
 * - A lost plane shows as the field shows any broken reference: red, with the error mark and
 *   "(missing)", and its menu's re-pick.
 * - While the sketch is edited the model is shown rolled back to it (RollbackView).
 * - The field disarms after a pick, with Esc in it, and when a sketch tool starts; the sketch's
 *   own model picks come back then.
 * - A new sketch with no plane yet (New Sketch with nothing selected, hands-on C-1): the field is
 *   armed, a blue "Select a sketch plane" line shows, and the sketch tools are greyed until a
 *   pick, as Onshape's are (TaskDlgEditSketch::setToolsBlocked); a tool started anyway is
 *   cancelled. The Body's planes are shown for the pick, and hidden again when the dialog closes
 *   if they weren't shown before.
 */
class TaskSketchPlane: public Gui::TaskView::TaskBox, public App::DocumentObserver
{
    Q_DECLARE_TR_FUNCTIONS(PartDesignGui::TaskSketchPlane)

public:
    explicit TaskSketchPlane(SketcherGui::ViewProviderSketch* sketchView);
    ~TaskSketchPlane() override;

    ReferenceField* field() const;
    /// Arms the field for a pick (Attach Sketch).
    void arm();
    /// The sketch has no plane yet (New Sketch with nothing selected): arms the field, shows the
    /// banner and the Body's planes, and refuses sketch tools until a plane is picked.
    void awaitPlane();
    /// True while the sketch waits for its first plane.
    bool needsPlane() const;
    /// The box of the sketch dialog open now, or null.
    static TaskSketchPlane* ofActiveDialog();

private:
    void slotChangedObject(const App::DocumentObject& obj, const App::Property& prop) override;
    SketcherGui::ViewProviderSketch* sketchViewProvider() const;
    /// The editing view follows the sketch's placement (a new plane, its undo and redo).
    void followPlacement();
    /// The sketch's model picks of plain edit mode, once the field's gate is gone.
    void restoreSketchPicks();
    /// The red line under the field while the plane is lost: its element is missing, or its
    /// object went (a deleted feature empties the link, while the sketch stays attached).
    void updateLostPlane();
    /// The "Select a sketch plane" line, shown while the sketch needs a plane.
    void updatePickBanner();
    /// A sketch tool started before the first plane: it ends, and the field is armed again.
    void refuseTool();
    /// The Body's planes, shown for the first pick; hidden again by the destructor.
    void showPlanesForPick();
    void hidePlanesShownForPick();

    App::DocumentObjectT sketchT;
    QPointer<ReferenceField> planeField;
    QPointer<QLabel> lostPlane;
    QPointer<QLabel> pickBanner;
    bool awaitingPlane = false;
    /// The Origin whose planes this box showed (temporary visibility), or none
    App::DocumentObjectT planesShownFor;
    Base::Placement lastPlacement;
    RollbackView rollback;
    fastsignals::scoped_connection toolConnection;
};

}  // namespace PartDesignGui
