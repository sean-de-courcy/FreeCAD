// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                            *
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

#include <algorithm>
#include <map>
#include <set>
#include <string>

#include <QPointer>
#include <QTimer>

#include <App/Application.h>
#include <App/Document.h>
#include <App/Transactions.h>
#include <Base/Exception.h>
#include <Gui/Application.h>
#include <Gui/Document.h>
#include <Gui/ForkKeymap.h>
#include <Gui/Notifications.h>
#include <Mod/Part/App/Geometry.h>
#include <Mod/Sketcher/App/Constraint.h>
#include <Mod/Sketcher/App/Sketch.h>
#include <Mod/Sketcher/App/SketchObject.h>

#include "ConflictRefusal.h"
#include "ViewProviderSketch.h"

using namespace SketcherGui;

namespace
{

/// a line or arc shorter than this (sketch units) has collapsed. The solver stops near zero, not
/// at it: two Horizontal lines 10 long made Perpendicular end about 8e-5 long
constexpr double collapsedSize = 1e-3;

struct Pending
{
    int countBefore = 0;
    int additions = 0;  // more than one before the solve: a group (a tool's), not checked
    Sketcher::ConstraintType type = Sketcher::None;
    int first = Sketcher::GeoEnum::GeoUndef;
    int second = Sketcher::GeoEnum::GeoUndef;
    std::set<int> collapsedBefore;
};

std::map<const ViewProviderSketch*, Pending>& pendingChecks()
{
    static std::map<const ViewProviderSketch*, Pending> pending;
    return pending;
}

/// the sketch's own lines and arcs the last solve shrank to nothing
std::set<int> collapsedGeometry(const Sketcher::SketchObject* sketch)
{
    std::set<int> collapsed;
    const Sketcher::Sketch& solved = sketch->getSolvedSketch();
    const int count = std::min(sketch->getHighestCurveIndex() + 1, solved.getGeometrySize());
    for (int geoId = 0; geoId < count; ++geoId) {
        const Part::Geometry* geometry = sketch->getGeometry(geoId);
        if (!geometry) {
            continue;
        }
        try {
            if (geometry->is<Part::GeomLineSegment>()) {
                const Base::Vector3d start = solved.getPoint(geoId, Sketcher::PointPos::start);
                const Base::Vector3d end = solved.getPoint(geoId, Sketcher::PointPos::end);
                if ((end - start).Length() < collapsedSize) {
                    collapsed.insert(geoId);
                }
            }
            else if (geometry->is<Part::GeomArcOfCircle>()) {
                const Base::Vector3d start = solved.getPoint(geoId, Sketcher::PointPos::start);
                const Base::Vector3d centre = solved.getPoint(geoId, Sketcher::PointPos::mid);
                const Base::Vector3d end = solved.getPoint(geoId, Sketcher::PointPos::end);
                if ((start - centre).Length() < collapsedSize
                    || (end - start).Length() < collapsedSize) {
                    collapsed.insert(geoId);
                }
            }
        }
        catch (const Base::Exception&) {
            // the solver's geometry is not the sketch's yet: nothing to compare
            return {};
        }
    }
    return collapsed;
}

/// takes the constraint at index out again, while the transaction tid is the document's last
/// (open or committed) one. Only the constraint goes: a tool that added geometry and this one
/// constraint in one command keeps its geometry.
void refuse(App::Document* document, const std::string& sketchName, int tid, int index)
{
    auto sketchOf = [document, &sketchName]() {
        return dynamic_cast<Sketcher::SketchObject*>(document->getObject(sketchName.c_str()));
    };
    auto* sketch = sketchOf();
    if (!sketch || document->getTransactionID(true, 0) != tid
        || sketch->Constraints.getSize() != index + 1) {
        return;  // something else happened since: leave it
    }
    if (document->hasPendingTransaction()) {
        if (document->getBookedTransactionID() != tid) {
            return;
        }
        sketch->delConstraint(index);  // inside the command's own transaction
    }
    else if (auto* guiDocument = Gui::Application::Instance->getDocument(document)) {
        const int geometryCount = sketch->Geometry.getSize();
        guiDocument->undo(1);  // a constraint command: as if it never ran
        sketch = sketchOf();
        if (!sketch) {
            return;
        }
        if (sketch->Geometry.getSize() != geometryCount) {
            // the command added geometry too: put it back and take out only the constraint
            guiDocument->redo(1);
            sketch = sketchOf();
            if (!sketch || sketch->Constraints.getSize() != index + 1) {
                return;
            }
            document->openTransaction("Remove conflicting constraint");
            sketch->delConstraint(index);
            document->commitTransaction();
        }
        else {
            // the undo left the refused command on the Redo stack (Ctrl+Y brought the conflict
            // back): an empty transaction opened at once clears it, and its abort leaves no step
            if (document->openTransaction("Refuse conflicting constraint") != 0) {
                App::Transaction::openPendingTransaction(*document);
                document->abortTransaction();
            }
        }
    }
    else {
        return;
    }
    // the sketch is solved again for the view, without the constraint
    sketch->solve();
    Gui::NotifyUserError(sketch,
                         QT_TRANSLATE_NOOP("Notifications", "Conflicting constraint"),
                         QT_TRANSLATE_NOOP("Notifications",
                                           "The constraint conflicts with the sketch's other "
                                           "constraints and was not added."));
}

}  // namespace

void SketcherGui::noteConstraintAdded(ViewProviderSketch& viewProvider,
                                      const Sketcher::Constraint& constraint)
{
    auto& pending = pendingChecks();
    if (!Gui::ForkKeymap::isOnshape() || !viewProvider.isInEditMode()) {
        pending.erase(&viewProvider);
        return;
    }
    const Sketcher::SketchObject* sketch = viewProvider.getSketchObject();
    // signalConstraintAdded comes before the constraint is in the list
    const int countBefore = sketch->Constraints.getSize();
    auto it = pending.find(&viewProvider);
    if (it != pending.end() && it->second.countBefore + it->second.additions == countBefore) {
        ++it->second.additions;  // one of a group (addConstraints): the group isn't checked
        return;
    }
    Pending check;
    check.countBefore = countBefore;
    check.additions = 1;
    check.type = constraint.Type;
    check.first = constraint.First;
    check.second = constraint.Second;
    check.collapsedBefore = collapsedGeometry(sketch);
    pending[&viewProvider] = std::move(check);
}

void SketcherGui::checkAddedConstraint(ViewProviderSketch& viewProvider)
{
    auto& pendingMap = pendingChecks();
    auto it = pendingMap.find(&viewProvider);
    if (it == pendingMap.end()) {
        return;
    }
    const Pending pending = it->second;
    pendingMap.erase(it);

    Sketcher::SketchObject* sketch = viewProvider.getSketchObject();
    App::Document* document = sketch->getDocument();
    const int index = pending.countBefore;
    if (pending.additions != 1 || sketch->Constraints.getSize() != index + 1
        || !document->hasPendingTransaction()) {
        return;  // a group, or no command to undo with it
    }
    const Sketcher::Constraint* added = sketch->Constraints.getValues()[index];
    if (!added || added->Type != pending.type || added->First != pending.first
        || added->Second != pending.second || added->isDimensional()
        || !added->isDriving) {
        return;
    }

    // FreeCAD-CH (ops#640, sketch conflicts): a conflicting constraint is kept, as Onshape keeps
    // it (PL1d): the solve leaves it out and solves the rest, and the marks show it. Only a
    // constraint that collapses a curve to a point is still refused.
    bool conflicts = false;
    for (int geoId : collapsedGeometry(sketch)) {
        if (!pending.collapsedBefore.contains(geoId)) {
            conflicts = true;
            break;
        }
    }
    if (!conflicts) {
        return;
    }

    // Undone once its command is done with it (the solve runs inside the command's addConstraint)
    const int tid = document->getTransactionID(true, 0);
    const std::string sketchName = sketch->getNameInDocument();
    const std::string documentName = document->getName();
    QTimer::singleShot(0, [documentName, sketchName, tid, index]() {
        if (auto* doc = App::GetApplication().getDocument(documentName.c_str())) {
            refuse(doc, sketchName, tid, index);
        }
    });
}

void SketcherGui::forgetAddedConstraint(const ViewProviderSketch& viewProvider)
{
    pendingChecks().erase(&viewProvider);
}
