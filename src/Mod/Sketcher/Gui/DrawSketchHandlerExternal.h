// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2022 Abdullah Tahiri <abdullah.tahiri.yo@gmail.com>     *
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

#include <cmath>
#include <string_view>

#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <gp_Pln.hxx>

#include <App/Datums.h>
#include <Mod/Part/App/DatumFeature.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/TopoShape.h>

#include <Gui/Application.h>
#include <Gui/Notifications.h>
#include <Gui/Selection/SelectionFilter.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Gui/MDIView.h>

#include <Mod/Sketcher/App/SketchObject.h>

#include "DrawSketchHandler.h"
#include "Utils.h"
#include "ViewProviderSketch.h"
#include <Mod/Part/App/Datums.h>
#include "SnapManager.h"


namespace SketcherGui
{

class ExternalSelection: public Gui::SelectionFilterGate
{
    App::DocumentObject* object;

public:
    explicit ExternalSelection(App::DocumentObject* obj)
        : Gui::SelectionFilterGate(nullPointer())
        , object(obj)
    {}

    bool allow(App::Document* pDoc, App::DocumentObject* pObj, const char* sSubName) override
    {
        Sketcher::SketchObject* sketch = static_cast<Sketcher::SketchObject*>(object);

        this->notAllowedReason = "";
        Sketcher::SketchObject::eReasonList msg;
        if (!sketch->isExternalAllowed(pDoc, pObj, &msg)) {
            switch (msg) {
                case Sketcher::SketchObject::rlCircularReference:
                    this->notAllowedReason = QT_TR_NOOP("Linking this will cause circular dependency.");
                    break;
                case Sketcher::SketchObject::rlOtherDoc:
                    this->notAllowedReason = QT_TR_NOOP("This object is in another document.");
                    break;
                case Sketcher::SketchObject::rlOtherBody:
                    this->notAllowedReason = QT_TR_NOOP(
                        "This object belongs to another body, can't link."
                    );
                    break;
                case Sketcher::SketchObject::rlOtherPart:
                    this->notAllowedReason = QT_TR_NOOP(
                        "This object belongs to another part, can't link."
                    );
                    break;
                default:
                    break;
            }
            return false;
        }

        // Note: its better to search the support of the sketch in case the sketch support is a base
        // plane
        // Part::BodyBase* body = Part::BodyBase::findBodyOf(sketch);
        // if ( body && body->hasFeature ( pObj ) && body->isAfter ( pObj, sketch ) ) {
        // Don't allow selection after the sketch in the same body
        // NOTE: allowness of features in other bodies is handled by
        // SketchObject::isExternalAllowed()
        // TODO may be this should be in SketchObject::isExternalAllowed() (2015-08-07, Fat-Zer)
        // return false;
        //}

        if (pObj->isDerivedFrom<Part::DatumLine>() || pObj->isDerivedFrom<Part::DatumPoint>()
            || pObj->isDerivedFrom<App::Line>() || pObj->isDerivedFrom<App::Point>()) {
            return true;
        }

        if (pObj->isDerivedFrom<App::Plane>() || pObj->isDerivedFrom<Part::Datum>()) {
            return true;
        }

        if (Base::Tools::isNullOrEmpty(sSubName)) {
            return false;
        }

        std::string element(sSubName);
        if ((element.size() > 4 && element.substr(0, 4) == "Edge")
            || (element.size() > 6 && element.substr(0, 6) == "Vertex")
            || (element.size() > 4 && element.substr(0, 4) == "Face")) {
            return true;
        }

        return false;
    }
};

/** FreeCAD-CH (ops#640, rank 19): true for "FaceN"; isFaceTakenBySketch says whether it is taken. */
inline bool isFaceElement(const char* subName)
{
    const std::string_view element(subName ? subName : "");
    return element.starts_with("Face") && element.size() > 4;
}

/** FreeCAD-CH (ops#640, rank 19): a model face a sketch constraint or dimension takes, as Onshape's
 * do (hands-on F4): a planar face perpendicular to the sketch plane, whose trace on the plane is one
 * line (the one external geometry a face link gives then: SketchObject's processFace). A face
 * parallel to the plane is refused, as Onshape refuses it (C-6, "A dimension cannot be created
 * between these items"), and so is a face at another angle or a curved one. The face is read in its
 * container and mapped into the sketch's, as its external geometry is (externalFrame, ops#331).
 */
inline bool isFaceTakenBySketch(const Sketcher::SketchObject* sketch,
                                const App::DocumentObject* object,
                                const char* subName)
{
    if (!sketch || !object || object == sketch || !isFaceElement(subName)) {
        return false;
    }
    Base::Vector3d faceNormal;
    try {
        const Part::TopoShape face = Part::Feature::getTopoShape(
            object,
            Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                | Part::ShapeOption::Transform,
            subName);
        gp_Pln plane;
        if (face.isNull() || face.shapeType(/*silent*/ true) != TopAbs_FACE
            || !face.findPlane(plane)) {
            return false;
        }
        const gp_Dir& normal = plane.Axis().Direction();
        faceNormal = sketch->externalFrame(object, subName).getRotation().multVec(
            Base::Vector3d(normal.X(), normal.Y(), normal.Z()));
    }
    catch (const Base::Exception&) {
        return false;
    }
    catch (const Standard_Failure&) {
        return false;
    }
    const Base::Vector3d sketchNormal =
        sketch->Placement.getValue().getRotation().multVec(Base::Vector3d(0, 0, 1));
    const double cosine = faceNormal * sketchNormal;
    // processFace's test for a face normal to the sketch (its angle within Confusion of 90 deg)
    return std::abs(cosine) < Precision::Confusion();
}

/// FreeCAD-CH (ops#640, rank 19): Onshape's words for a face a dimension can't take (C-6)
inline const char* refusedFaceReason()
{
    return QT_TRANSLATE_NOOP("Notifications", "A dimension cannot be created between these items");
}

// FreeCAD-CH (ops#634): the gate of plain edit mode. A model edge or vertex the sketch may link is
// selectable, so it can be picked before a constraint command (Onshape's order); the command turns
// it into external geometry (takeModelSelection). The sketch's own elements and whole objects (the
// tree) pass as before; other model elements (faces) don't.
class ModelPickSelection: public ExternalSelection
{
    App::DocumentObject* sketch;

public:
    explicit ModelPickSelection(App::DocumentObject* obj)
        : ExternalSelection(obj)
        , sketch(obj)
    {}

    bool allow(App::Document* document, App::DocumentObject* object, const char* subName) override
    {
        this->notAllowedReason = "";
        // The gate is global: another document's picks are that document's business
        if (object == sketch || Base::Tools::isNullOrEmpty(subName)
            || document != sketch->getDocument()) {
            return true;
        }
        const std::string_view element(subName);
        // FreeCAD-CH (ops#640, rank 19): and a planar face perpendicular to the sketch plane
        if (!(element.starts_with("Edge") && element.size() > 4)
            && !(element.starts_with("Vertex") && element.size() > 6)
            && !isFaceTakenBySketch(static_cast<Sketcher::SketchObject*>(sketch), object, subName)) {
            return false;
        }
        // A click on a sketch element in front of (or behind) a model edge is the sketch's, and
        // so is the release of a drag or a box
        auto* vp = freecad_cast<ViewProviderSketch*>(Gui::Application::Instance->getViewProvider(sketch));
        if (vp && !vp->takesModelPick()) {
            return false;
        }
        return ExternalSelection::allow(document, object, subName);
    }
};

class DrawSketchHandlerExternal: public DrawSketchHandler
{
    Q_DECLARE_TR_FUNCTIONS(SketcherGui::DrawSketchHandlerExternal)

public:
    DrawSketchHandlerExternal(bool alwaysReference, bool intersection)
        : alwaysReference {alwaysReference}
        , intersection {intersection}
    {}
    ~DrawSketchHandlerExternal() override
    {
        Gui::Selection().rmvSelectionGate();
    }

    void mouseMove(SnapManager::SnapHandle snapHandle) override
    {
        Q_UNUSED(snapHandle);
        if (Gui::Selection().getPreselection().pObjectName) {
            applyCursor();
        }
    }

    bool pressButton(Base::Vector2d onSketchPos) override
    {
        Q_UNUSED(onSketchPos);
        return true;
    }

    bool releaseButton(Base::Vector2d onSketchPos) override
    {
        Q_UNUSED(onSketchPos);
        /* this is ok not to call to purgeHandler
         * in continuous creation mode because the
         * handler is destroyed by the quit() method on pressing the
         * right button of the mouse */
        return true;
    }

    bool onSelectionChanged(const Gui::SelectionChanges& msg) override
    {
        if (msg.Type == Gui::SelectionChanges::AddSelection) {
            App::DocumentObject* obj = sketchgui->getObject()->getDocument()->getObject(
                msg.pObjectName
            );
            if (!obj) {
                throw Base::ValueError("Sketcher: External geometry: Invalid object in selection");
            }
            std::string subName(msg.pSubName);

            if (obj->isDerivedFrom<App::Plane>() || obj->isDerivedFrom<Part::Datum>()
                || obj->isDerivedFrom<Part::DatumLine>() || obj->isDerivedFrom<Part::DatumPoint>()
                || obj->isDerivedFrom<App::Line>() || obj->isDerivedFrom<App::Point>()
                || (subName.size() > 4 && subName.substr(0, 4) == "Edge")
                || (subName.size() > 6 && subName.substr(0, 6) == "Vertex")
                || (subName.size() > 4 && subName.substr(0, 4) == "Face")) {
                try {
                    openCommand(QT_TRANSLATE_NOOP("Command", "Add external geometry"));
                    Gui::cmdAppObjectArgs(
                        sketchgui->getObject(),
                        "addExternal(\"%s\",\"%s\", %s, %s)",
                        msg.pObjectName,
                        msg.pSubName,
                        alwaysReference || isConstructionMode() ? "False" : "True",
                        intersection ? "True" : "False"
                    );

                    commitCommand();

                    // adding external geometry does not require a solve() per se (the DoF is the
                    // same), however a solve is required to update the amount of solver geometry,
                    // because we only redraw a changed Sketch if the solver geometry amount is the
                    // same as the SkethObject geometry amount (as this avoids other issues). This
                    // solver is a very low cost one anyway (there is actually nothing to solve).
                    tryAutoRecomputeIfNotSolve(sketchgui->getObject<Sketcher::SketchObject>());

                    Gui::Selection().clearSelection();
                    /* this is ok not to call to purgeHandler
                     * in continuous creation mode because the
                     * handler is destroyed by the quit() method on pressing the
                     * right button of the mouse */
                }
                catch (const Base::Exception&) {
                    Gui::NotifyError(
                        sketchgui,
                        QT_TRANSLATE_NOOP("Notifications", "Error"),
                        QT_TRANSLATE_NOOP("Notifications", "Failed to add external geometry")
                    );
                    Gui::Selection().clearSelection();
                    abortCommand();
                }
                return true;
            }
        }
        updateHint();

        return false;
    }

private:
    void activated() override
    {
        setAxisPickStyle(false);
        Gui::MDIView* mdi = Gui::Application::Instance->activeDocument()->getActiveView();
        Gui::View3DInventorViewer* viewer;
        viewer = static_cast<Gui::View3DInventor*>(mdi)->getViewer();
        viewer->setSelectionEnabled(true);

        Gui::Selection().clearSelection();
        Gui::Selection().rmvSelectionGate();
        Gui::Selection().addSelectionGate(new ExternalSelection(sketchgui->getObject()));
    }

    QString getCrosshairCursorSVGName() const override
    {
        if (intersection) {
            return QStringLiteral("Sketcher_Pointer_External_Intersection");
        }

        return QStringLiteral("Sketcher_Pointer_External");
    }

    void deactivated() override
    {
        Q_UNUSED(sketchgui);
        setAxisPickStyle(true);
    }

    bool alwaysReference;
    bool intersection;

public:
    std::list<Gui::InputHint> getToolHints() const override
    {
        return {
            {tr("%1 pick external geometry", "Sketcher External: hint"),
             {Gui::InputHint::UserInput::MouseLeft}},
        };
    }
};

}  // namespace SketcherGui
