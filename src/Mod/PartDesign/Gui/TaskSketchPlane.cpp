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

#include <algorithm>
#include <memory>
#include <string>
#include <vector>

#include <QLabel>
#include <QTimer>
#include <QVBoxLayout>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <App/Origin.h>
#include <App/Part.h>
#include <Base/Exception.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/ForkKeymap.h>
#include <Gui/MainWindow.h>
#include <Gui/Selection/Selection.h>
#include <Gui/ViewProviderCoordinateSystem.h>
#include <Mod/Part/App/AttachExtension.h>
#include <Mod/Part/App/Attacher.h>
#include <Mod/Part/App/BodyBase.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/Sketcher/Gui/TaskDlgEditSketch.h>
#include <Mod/Sketcher/Gui/ViewProviderSketch.h>

#include "EnumFlags.h"
#include "ReferenceField.h"
#include "TaskSketchPlane.h"

using namespace PartDesignGui;

namespace
{

// The Part Studio's own Top, Front or Right (an origin feature of the App::Part holding @p body):
// with the Body placed off the studio's origin it isn't mapped to the Body's own, and the sketch
// attaches to it directly, which recomputes in place (RT-2)
bool isOwnStudioOrigin(const App::DocumentObject* body, const App::DocumentObject* obj)
{
    auto datum = freecad_cast<const App::DatumElement*>(obj);
    const App::DocumentObject* lcs = datum ? datum->getLCS() : nullptr;
    if (!lcs || !body) {
        return false;
    }
    const Base::Type assembly = Base::Type::fromName("Assembly::AssemblyObject");
    for (auto user : lcs->getInList()) {
        auto part = freecad_cast<App::Part*>(user);
        if (part && part->Origin.getValue() == lcs
            && !(!assembly.isBad() && part->isDerivedFrom(assembly))
            && part->hasObject(body, /*recursive=*/true)) {
            return true;
        }
    }
    return false;
}

// The sketch dialog asks for the box (TaskDlgEditSketch::addContentFactory): with the Onshape
// keymap only, so FreeCAD's keymap keeps FreeCAD's sketch dialog
QWidget* makeSketchPlaneBox(SketcherGui::ViewProviderSketch* sketchView)
{
    if (!sketchView || !Gui::ForkKeymap::isOnshape()) {
        return nullptr;
    }
    App::DocumentObject* sketch = sketchView->getObject();
    if (!sketch || !sketch->hasExtension(Part::AttachExtension::getExtensionClassTypeId())) {
        return nullptr;
    }
    return new TaskSketchPlane(sketchView);
}

// Registered when the module's library loads; the dialog's list is a plain function list
struct SketchPlaneBoxRegistrar
{
    SketchPlaneBoxRegistrar()
    {
        SketcherGui::TaskDlgEditSketch::addContentFactory(&makeSketchPlaneBox);
    }
};
SketchPlaneBoxRegistrar registrar;

}  // namespace

TaskSketchPlane::TaskSketchPlane(SketcherGui::ViewProviderSketch* sketchView)
    : TaskBox(Gui::BitmapFactory().pixmap("Sketcher_MapSketch"), tr("Sketch plane"), true, nullptr)
    , sketchT(sketchView->getObject())
{
    setObjectName(QStringLiteral("sketchPlaneBox"));
    auto sketch = sketchT.getObjectAs<Part::Part2DObject>();
    if (sketch) {
        lastPlacement = sketch->Placement.getValue();
    }

    ReferenceField::Options options;
    options.kind = ReferenceField::Kind::SingleElement;
    // Planar faces, origin and datum planes
    // OTHERBODY: the studio's own origin too, unmapped when the Body sits off it (RT-2)
    options.flags = AllowSelection::FACE | AllowSelection::PLANAR | AllowSelection::OTHERBODY;
    options.label = tr("Sketch plane");
    options.kinds = tr("A plane or a planar face");
    options.required = false;
    // A sketch is always on a plane: a pick replaces it, nothing clears it
    options.removable = false;
    // Disarmed after the pick, so the next click draws
    options.once = true;
    // "Face of Pad", as Onshape's Sketch plane field (ops#640 round 6, J10)
    options.elementWords = true;
    // Not a face of what this sketch makes (a cycle)
    options.noDependents = true;
    const App::DocumentObjectT owner = sketchT;
    options.accept = [owner](App::DocumentObject* obj, const char* /*sub*/, std::string& why) {
        if (!obj) {
            return false;
        }
        if (obj->isDerivedFrom<Part::Part2DObject>()) {
            why = QT_TR_NOOP("Pick a plane or a planar face, not a sketch.");
            return false;
        }
        if (obj->isDerivedFrom<PartDesign::Body>()) {
            why = QT_TR_NOOP("Pick a face of a feature, or a plane.");
            return false;
        }
        // The model as it is before the sketch, which is what the roll-back shows (Onshape's
        // part studio rolled back to the sketch)
        App::DocumentObject* own = owner.getObject();
        PartDesign::Body* body = own ? PartDesign::Body::findBodyOf(own) : nullptr;
        // Only what the sketch may link as it is: its own Body's (its origin planes included) or
        // a studio sibling's, or the studio's own Top, Front, Right (the field writes the Body's
        // own plane for it, J1T A). Anything else would fail as a link out of the allowed scope
        if (body && !body->hasObject(obj) && !Part::BodyBase::isInOneStudio(own, obj)
            && !Part::BodyBase::studioOriginFeature(own, obj)
            && !isOwnStudioOrigin(body, obj)) {
            why = QT_TR_NOOP("Pick a face or a plane of this part studio.");
            return false;
        }
        if (body && body->hasObject(obj) && body->isAfter(obj, own)) {
            why = QT_TR_NOOP("Pick a face or a plane from before the sketch.");
            return false;
        }
        return true;
    };

    auto self = std::make_shared<QPointer<ReferenceField>>();
    auto write = [owner, self](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        auto part2d = owner.getObjectAs<Part::Part2DObject>();
        auto attach = part2d ? part2d->getExtensionByType<Part::AttachExtension>(true) : nullptr;
        if (!attach || !*self) {
            return;
        }
        const int tid =
            Gui::Command::openActiveDocumentCommand(QT_TRANSLATE_NOOP("Command", "Sketch plane"));
        try {
            // Flat face, from the Body's origin (as the attachment panel writes a support, ops#311).
            // Another mode goes off first, so the old support isn't positioned in the new mode, nor
            // the new support in the old one.
            const std::string flatFace =
                Attacher::AttachEngine::getModeName(Attacher::mmFlatFace);
            const bool wasFlat = flatFace == attach->MapMode.getValueAsString();
            if (!wasFlat) {
                attach->MapMode.setValue(
                    Attacher::AttachEngine::getModeName(Attacher::mmDeactivated).c_str()
                );
            }
            attach->MapOrigin.setValue(1L);
            // On the plane itself, as Onshape's sketch is: an offset or a flip the attachment
            // editor gave the old plane would move the sketch off the new one
            attach->MapReversed.setValue(false);
            attach->AttachmentOffset.setValue(Base::Placement());
            (*self)->assign(obj, subs);
            if (!wasFlat) {
                attach->MapMode.setValue(flatFace.c_str());
            }
            // The sketch's external geometry is projected on the new plane
            part2d->recomputeFeature();
            Gui::Command::commitCommand(tid);
        }
        catch (const Base::Exception& e) {
            e.reportException();
            Gui::Command::abortCommand(tid);
        }
    };

    auto content = new QWidget(this);
    auto layout = new QVBoxLayout(content);
    layout->setContentsMargins(0, 0, 0, 0);
    planeField = new ReferenceField(sketch, "AttachmentSupport", options, write, content);
    *self = planeField;
    layout->addWidget(planeField);
    lostPlane = new QLabel(content);
    lostPlane->setObjectName(QStringLiteral("lostPlane"));
    lostPlane->setWordWrap(true);
    lostPlane->setStyleSheet(QStringLiteral("color: red;"));
    lostPlane->setText(tr("The sketch plane is missing: pick a plane or a planar face."));
    lostPlane->hide();
    layout->addWidget(lostPlane);
    // Onshape's blue banner while a new sketch has no plane (hands-on C-1)
    pickBanner = new QLabel(content);
    pickBanner->setObjectName(QStringLiteral("pickPlaneBanner"));
    pickBanner->setWordWrap(true);
    pickBanner->setStyleSheet(QStringLiteral("color: white; background-color: #2f6fd1; padding: 4px;"));
    pickBanner->setText(tr("Select a sketch plane"));
    pickBanner->hide();
    layout->addWidget(pickBanner);
    groupLayout()->addWidget(content);
    updateLostPlane();

    // Each way the field disarms (a pick, Esc, a sketch tool) gives the sketch its picks back
    connect(planeField, &ReferenceField::armedChanged, this, [this](bool armed) {
        if (!armed) {
            // After the selection change or the gate swap under way
            QTimer::singleShot(0, this, [this]() { restoreSketchPicks(); });
        }
    });
    // A sketch tool started: its clicks are the tool's. Before a new sketch's first plane there
    // is nothing to draw on: the tool ends again (queued, it is starting now)
    toolConnection = sketchView->registerToolChanged([this](const std::string& toolname) {
        if (toolname == "DSH_None") {
            return;
        }
        if (planeField && planeField->isArmed()) {
            planeField->setArmed(false);
        }
        if (needsPlane()) {
            QTimer::singleShot(0, this, [this]() { refuseTool(); });
        }
    });

    if (sketch) {
        attachDocument(sketch->getDocument());
        // The model as it is before the sketch (only in a Body)
        rollback.rollBackTo(sketch);
    }
}

TaskSketchPlane::~TaskSketchPlane()
{
    toolConnection.disconnect();
    detachDocument();
    try {
        hidePlanesShownForPick();
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
    // rollback restores the model's view as it goes
}

ReferenceField* TaskSketchPlane::field() const
{
    return planeField.data();
}

void TaskSketchPlane::arm()
{
    if (planeField) {
        planeField->setArmed(true);
    }
}

void TaskSketchPlane::awaitPlane()
{
    awaitingPlane = true;
    showPlanesForPick();
    updatePickBanner();
    arm();
}

bool TaskSketchPlane::needsPlane() const
{
    auto sketch = sketchT.getObjectAs<Part::Part2DObject>();
    return awaitingPlane && sketch && !sketch->AttachmentSupport.getValue()
        && sketch->MapMode.getValue() == Attacher::mmDeactivated;
}

void TaskSketchPlane::updatePickBanner()
{
    const bool waiting = needsPlane();
    if (pickBanner) {
        pickBanner->setVisible(waiting);
    }
    // Onshape greys the sketch toolbar until the plane is picked (hands-on C-1)
    auto dlg = SketcherGui::TaskDlgEditSketch::ofSketchView(sketchViewProvider());
    if (dlg && dlg->areToolsBlocked() != waiting) {
        dlg->setToolsBlocked(waiting);
        // queued: this runs from a document observer, mid-property-change
        if (Gui::MainWindow* mainWindow = Gui::getMainWindow()) {
            mainWindow->updateActions(/*delay*/ true);
        }
    }
}

void TaskSketchPlane::refuseTool()
{
    SketcherGui::ViewProviderSketch* vp = sketchViewProvider();
    if (!needsPlane() || !vp || !vp->isInEditMode()) {
        return;
    }
    if (vp->getSketchMode() == SketcherGui::ViewProviderSketch::STATUS_SKETCH_UseHandler) {
        vp->purgeHandler();
    }
    // purgeHandler put the sketch's own gate in place: the field's comes back over it
    arm();
}

void TaskSketchPlane::showPlanesForPick()
{
    App::DocumentObject* sketch = sketchT.getObject();
    PartDesign::Body* body = sketch ? PartDesign::Body::findBodyOf(sketch) : nullptr;
    App::Origin* origin = nullptr;
    try {
        origin = body ? body->getOrigin() : nullptr;
    }
    catch (const Base::Exception&) {
        return;  // a Body without its Origin: nothing to show
    }
    auto vpo = origin && Gui::Application::Instance
        ? dynamic_cast<Gui::ViewProviderCoordinateSystem*>(
              Gui::Application::Instance->getViewProvider(origin)
          )
        : nullptr;
    // Shown already (a new part studio's planes, which stay: ops#626) or by someone else
    if (!vpo || vpo->isTemporaryVisibility()) {
        return;
    }
    vpo->setTemporaryVisibility(Gui::DatumElement::Planes);
    vpo->setPlaneLabelVisibility(true);
    planesShownFor = origin;
}

void TaskSketchPlane::hidePlanesShownForPick()
{
    App::DocumentObject* origin = planesShownFor.getObject();
    planesShownFor = App::DocumentObjectT();
    auto vpo = origin && Gui::Application::Instance
        ? dynamic_cast<Gui::ViewProviderCoordinateSystem*>(
              Gui::Application::Instance->getViewProvider(origin)
          )
        : nullptr;
    if (vpo && vpo->isTemporaryVisibility()) {
        vpo->resetTemporaryVisibility();
        vpo->setPlaneLabelVisibility(false);
    }
}

TaskSketchPlane* TaskSketchPlane::ofActiveDialog()
{
    auto dlg = qobject_cast<SketcherGui::TaskDlgEditSketch*>(Gui::Control().activeDialog());
    if (!dlg) {
        return nullptr;
    }
    for (QWidget* widget : dlg->getDialogContent()) {
        if (auto box = dynamic_cast<TaskSketchPlane*>(widget)) {
            return box;
        }
    }
    return nullptr;
}

SketcherGui::ViewProviderSketch* TaskSketchPlane::sketchViewProvider() const
{
    App::DocumentObject* sketch = sketchT.getObject();
    if (!sketch || !Gui::Application::Instance) {
        return nullptr;
    }
    return Gui::Application::Instance->getViewProvider<SketcherGui::ViewProviderSketch>(sketch);
}

void TaskSketchPlane::slotChangedObject(const App::DocumentObject& obj, const App::Property& prop)
{
    auto sketch = sketchT.getObjectAs<Part::Part2DObject>();
    if (!sketch || &obj != sketch) {
        return;
    }
    if (&prop == &sketch->Placement) {
        followPlacement();
    }
    else if (&prop == &sketch->AttachmentSupport || &prop == &sketch->MapMode) {
        updateLostPlane();
        updatePickBanner();
    }
}

void TaskSketchPlane::updateLostPlane()
{
    auto sketch = sketchT.getObjectAs<Part::Part2DObject>();
    if (!lostPlane || !sketch) {
        return;
    }
    const std::vector<std::string> subs = sketch->AttachmentSupport.getSubValues(false);
    const bool missing = std::ranges::any_of(subs, [](const std::string& sub) {
        return Data::hasMissingElement(sub.c_str());
    });
    const bool attached = sketch->MapMode.getValue() != Attacher::mmDeactivated;
    lostPlane->setVisible(missing || (attached && !sketch->AttachmentSupport.getValue()));
}

void TaskSketchPlane::followPlacement()
{
    auto sketch = sketchT.getObjectAs<Part::Part2DObject>();
    if (!sketch) {
        return;
    }
    const Base::Placement now = sketch->Placement.getValue();
    const Base::Placement before = lastPlacement;
    lastPlacement = now;
    SketcherGui::ViewProviderSketch* vp = sketchViewProvider();
    Gui::Document* guiDocument = vp ? vp->getDocument() : nullptr;
    if (!vp || !vp->isInEditMode() || !guiDocument || guiDocument->getInEdit() != vp
        || now.isSame(before, 1e-12)) {
        return;
    }
    // The editing transform is the sketch's placement under its containers': swap the sketch's
    // own part, so a Body's (or a link's) placement stays in it
    const Base::Placement editing(guiDocument->getEditingTransform());
    // Gui::Document follows the edited object's Placement itself while the edit's object list
    // holds it (slotChangedObject, before this slot): composed again, the move went in twice (a
    // face at z = 5 edited at z = 10). Followed already when the transform is the sketch's global
    // placement now
    const Base::Placement global = App::GeoFeature::getGlobalPlacement(sketch);
    Base::Placement moved = editing;
    if (!editing.isSame(global, 1e-9)) {
        moved = editing * before.inverse() * now;
        guiDocument->setEditingTransform(moved.toMatrix());
    }
    vp->setGridOrientation(moved.getPosition(), moved.getRotation());
    vp->draw(false, true);
}

void TaskSketchPlane::restoreSketchPicks()
{
    if (planeField && planeField->isArmed()) {
        return;
    }
    SketcherGui::ViewProviderSketch* vp = sketchViewProvider();
    // Only plain edit mode, with no gate in place: a tool, or a constraint tool's gate, keeps its
    // own picks, and gives the sketch's back when it ends
    if (!vp || !vp->isInEditMode()
        || vp->getSketchMode() != SketcherGui::ViewProviderSketch::STATUS_NONE
        || Gui::Selection().getSelectionGate(nullptr)) {
        return;
    }
    vp->purgeHandler();
}
