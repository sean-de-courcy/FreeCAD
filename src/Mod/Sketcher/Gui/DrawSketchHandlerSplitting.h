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

#include <Inventor/SbViewportRegion.h>

#include <Gui/Application.h>
#include <Gui/Notifications.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Gui/Selection/SelectionFilter.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>

#include <Mod/Sketcher/App/SketchObject.h>

#include "DrawSketchHandler.h"
#include "Utils.h"
#include "ViewProviderSketch.h"
#include "SnapManager.h"


namespace SketcherGui
{

class SplittingSelection: public Gui::SelectionFilterGate
{
    App::DocumentObject* object;

public:
    explicit SplittingSelection(App::DocumentObject* obj)
        : Gui::SelectionFilterGate(nullPointer())
        , object(obj)
    {}

    bool allow(App::Document* /*pDoc*/, App::DocumentObject* pObj, const char* sSubName) override
    {
        if (pObj != this->object) {
            return false;
        }
        if (Base::Tools::isNullOrEmpty(sSubName)) {
            return false;
        }
        std::string element(sSubName);
        if (element.substr(0, 4) == "Edge") {
            int GeoId = std::atoi(element.substr(4, 4000).c_str()) - 1;
            Sketcher::SketchObject* Sketch = static_cast<Sketcher::SketchObject*>(object);
            const Part::Geometry* geom = Sketch->getGeometry(GeoId);

            // clang-format off: keep line breaks for readability
            if (geom->is<Part::GeomLineSegment>()
                || geom->is<Part::GeomCircle>()
                || geom->is<Part::GeomEllipse>()
                || geom->isDerivedFrom<Part::GeomArcOfConic>()
                || geom->is<Part::GeomBSplineCurve>()) {
                return true;
            }
            // clang-format on
        }
        else if (element.substr(0, 6) == "Vertex") {
            // FreeCAD-CH (sketcher 3, Ward's hand-check 6): every point of the sketch can be
            // preselected, as in Onshape, so an intersection or a shared end shows no "no" cursor.
            // The click decides: a knot splits its B-spline, a point inside the curve traced on the
            // way in splits that curve, anything else is refused in the hint line.
            return true;
        }
        return false;
    }
};


class DrawSketchHandlerSplitting: public DrawSketchHandler
{
    Q_DECLARE_TR_FUNCTIONS(SketcherGui::DrawSketchHandlerSplitting)

public:
    DrawSketchHandlerSplitting() = default;
    ~DrawSketchHandlerSplitting() override
    {
        Gui::Selection().rmvSelectionGate();
    }

    // FreeCAD-CH (sketcher 3, Ward's hand-check 6; Onshape SK11): the curve that is split at an
    // intersection is the one the preselection was on while the cursor approached it (the traced
    // curve). Near a point where another curve crosses or touches it (or a sketch point lies on
    // it), the pick snaps there and a marker shows it. A whole circle takes two picks, the first
    // shown by a marker until the second; Esc or a right click drops a pending first pick.
    void mouseMove(SnapManager::SnapHandle snapHandle) override
    {
        cursor = snapHandle.cursorPos;
        hasCursor = true;
        trace(cursor);
        drawMarkers();
    }

    bool pressButton(Base::Vector2d onSketchPos) override
    {
        Q_UNUSED(onSketchPos);
        return true;
    }

    bool releaseButton(Base::Vector2d onSketchPos) override
    {
        // A click's position is the point the pick hit on the curve, up to a pick radius away
        // from the cursor; the last move's (the cursor's ray, already traced) is the one that
        // was snapped and shown.
        int GeoId = Sketcher::GeoEnum::GeoUndef;
        Base::Vector2d point = hasCursor ? cursor : onSketchPos;

        if (snapped) {
            GeoId = tracedGeoId;
            point = snapPoint;
        }
        else if (int curveGeoId = getPreselectCurve(); curveGeoId >= 0) {
            if (isSplittable(curveGeoId)) {
                GeoId = curveGeoId;
            }
        }
        else if (int vertex = getPreselectPoint(); vertex >= 0) {
            // a B-spline's knot splits the B-spline there (the preselection is a vertex index:
            // the knot is the point geometry the knot constraint names)
            int pointGeoId = Sketcher::GeoEnum::GeoUndef;
            Sketcher::PointPos pointPos = Sketcher::PointPos::none;
            getSketchObject()->getGeoVertexIndex(vertex, pointGeoId, pointPos);
            const auto& constraints = getSketchObject()->Constraints.getValues();
            const auto& conIt
                = std::find_if(constraints.begin(), constraints.end(), [pointGeoId](auto constr) {
                      return (
                          constr->Type == Sketcher::InternalAlignment
                          && constr->AlignmentType == Sketcher::BSplineKnotPoint
                          && constr->First == pointGeoId
                      );
                  });
            if (pointGeoId != Sketcher::GeoEnum::GeoUndef && conIt != constraints.end()) {
                GeoId = (*conIt)->Second;
                Base::Vector3d knot = getSketchObject()->getPoint(pointGeoId, pointPos);
                point = Base::Vector2d(knot.x, knot.y);  // at the knot, not the cursor's pixel
            }
            else {
                // a curve's end, or a point not inside the traced curve: nothing to split there
                refuse(tr("Nothing to split at this point: approach it along the curve to split"));
                return true;
            }
        }

        if (GeoId < 0) {
            if (firstGeoId != Sketcher::GeoEnum::GeoUndef) {
                refuse(tr("Select the second point on the same circle"));
                return true;
            }
            sketchgui->purgeHandler();
            return true;
        }

        // FreeCAD-CH (ops#656 F3, Onshape SK11): a whole circle has no ends: it takes a second point,
        // then splits into two arcs joined at both points. An ellipse still can't be split.
        const Part::Geometry* geom = sketchgui->getSketchObject()->getGeometry(GeoId);
        if (geom->is<Part::GeomEllipse>()) {
            Gui::NotifyUserError(
                sketchgui->getObject(),
                QT_TRANSLATE_NOOP("Notifications", "Cannot split an ellipse"),
                QT_TRANSLATE_NOOP(
                    "Notifications",
                    "An ellipse has no ends. Trim it between two crossing curves, or draw arcs."
                )
            );
            return true;
        }
        if (firstGeoId != Sketcher::GeoEnum::GeoUndef && firstGeoId != GeoId) {
            // Onshape rejects a second pick on another curve; the first pick stays
            refuse(tr("Select the second point on the same circle"));
            return true;
        }
        if (geom->is<Part::GeomCircle>()) {
            Base::Vector2d onCircle = projectToCurve(GeoId, point);
            if (firstGeoId == Sketcher::GeoEnum::GeoUndef) {
                firstGeoId = GeoId;
                firstPoint = onCircle;
                refusal.clear();
                updateHint();
                drawMarkers();
                return true;
            }
            if ((onCircle - firstPoint).Length() < snapRadius()) {
                refuse(tr("Select a second point away from the first"));
                return true;
            }
        }

        try {
            openCommand(QT_TRANSLATE_NOOP("Command", "Split edge"));
            if (firstGeoId == GeoId) {
                Gui::cmdAppObjectArgs(
                    sketchgui->getObject(),
                    "split(%d,App.Vector(%.12g,%.12g,0),App.Vector(%.12g,%.12g,0))",
                    GeoId,
                    firstPoint.x,
                    firstPoint.y,
                    point.x,
                    point.y
                );
            }
            else {
                Gui::cmdAppObjectArgs(
                    sketchgui->getObject(),
                    "split(%d,App.Vector(%.12g,%.12g,0))",
                    GeoId,
                    point.x,
                    point.y
                );
            }
            commitCommand();
            tryAutoRecompute(sketchgui->getObject<Sketcher::SketchObject>());
        }
        catch (const Base::Exception& e) {
            Gui::NotifyUserError(
                sketchgui->getObject(),
                QT_TRANSLATE_NOOP("Notifications", "Failed to split the edge"),
                e.what()
            );
            abortCommand();
        }
        firstGeoId = Sketcher::GeoEnum::GeoUndef;
        refusal.clear();
        // the geometry changed: the traced curve's index and its intersections are stale
        tracedGeoId = Sketcher::GeoEnum::GeoUndef;
        lastPreselectCurve = Sketcher::GeoEnum::GeoUndef;
        snapped = false;
        candidates.clear();
        updateHint();
        drawMarkers();
        return true;
    }

    void cancelCurrentAction() override
    {
        if (firstGeoId != Sketcher::GeoEnum::GeoUndef) {
            firstGeoId = Sketcher::GeoEnum::GeoUndef;
            refusal.clear();
            updateHint();
            drawMarkers();
            return;
        }
        DrawSketchHandler::cancelCurrentAction();
    }

private:
    void activated() override
    {
        Gui::Selection().clearSelection();
        Gui::Selection().rmvSelectionGate();
        Gui::Selection().addSelectionGate(new SplittingSelection(sketchgui->getObject()));
    }

    QString getCrosshairCursorSVGName() const override
    {
        return QStringLiteral("Sketcher_Pointer_Splitting");
    }

    bool isSplittable(int geoId) const
    {
        if (geoId < 0) {
            return false;
        }
        const Part::Geometry* geom = sketchgui->getSketchObject()->getGeometry(geoId);
        // clang-format off: keep line breaks for readability
        return geom
            && (geom->is<Part::GeomLineSegment>()
                || geom->is<Part::GeomCircle>()
                || geom->is<Part::GeomEllipse>()  // refused with a message at the click
                || geom->isDerivedFrom<Part::GeomArcOfConic>()
                || geom->is<Part::GeomBSplineCurve>());
        // clang-format on
    }

    /// The view's pick radius in sketch units: the preselection's reach. Measured on the focal
    /// plane (the sketch plane in a view square to it).
    double pickRadius() const
    {
        auto* view = dynamic_cast<Gui::View3DInventor*>(Gui::Application::Instance->activeView());
        if (view) {
            Gui::View3DInventorViewer* viewer = view->getViewer();
            SbVec2s size = viewer->getViewportRegion().getViewportSizePixels();
            SbVec2s mid(static_cast<short>(size[0] / 2), static_cast<short>(size[1] / 2));
            SbVec2s right(static_cast<short>(mid[0] + 100), mid[1]);  // NOLINT
            double pixel = (viewer->getPointOnFocalPlane(mid) - viewer->getPointOnFocalPlane(right))
                               .length()
                / 100.0;  // NOLINT
            if (pixel > 0) {
                return std::max<double>(viewer->getPickRadius(), 4.0) * pixel;  // NOLINT
            }
        }
        return 0.3 * sketchgui->getScaleFactor();  // NOLINT
    }

    /// the snap distance onto an intersection
    double snapRadius() const
    {
        return 1.2 * pickRadius();  // NOLINT
    }

    /// The zone around an intersection where the traced curve stays traced: the other curve's
    /// pick radius reaches it there for crossings down to about 25 degrees.
    double lockRadius() const
    {
        return 2.5 * pickRadius();  // NOLINT
    }

    bool nearCandidate(const Base::Vector2d& pos, double radius) const
    {
        return tracedGeoId != Sketcher::GeoEnum::GeoUndef
            && std::any_of(candidates.begin(), candidates.end(), [&](const Base::Vector2d& p) {
                   return (p - pos).Length() <= radius;
               });
    }

    void trace(const Base::Vector2d& pos)
    {
        // a snapped intersection keeps its curve while the cursor stays at it, whichever curve the
        // preselection is on there: the split curve is the one traced on the way in
        if (snapped && (pos - snapPoint).Length() <= snapRadius()) {
            return;
        }
        snapped = false;
        // entering a curve (again) traces it; its intersections are found afresh, since the
        // sketch may have changed meanwhile (an undo). Near one of the traced curve's
        // intersections the other curve's pick radius can take the preselection before the
        // cursor reaches the point: the traced curve stays until the cursor leaves that zone.
        int curve = getPreselectCurve();
        if (!nearCandidate(pos, lockRadius())) {
            if (curve >= 0 && curve != lastPreselectCurve && isSplittable(curve)) {
                tracedGeoId = curve;
                findCandidates();
            }
            lastPreselectCurve = curve;
        }
        if (tracedGeoId == Sketcher::GeoEnum::GeoUndef) {
            return;
        }
        double best = snapRadius();
        for (const auto& candidate : candidates) {
            double distance = (candidate - pos).Length();
            if (distance <= best) {
                best = distance;
                snapPoint = candidate;
                snapped = true;
            }
        }
    }

    /// The points inside the traced curve where another curve crosses or touches it, or where a
    /// sketch point lies on it (another curve's end, a centre, a point). The curve's own ends
    /// are not candidates: there is nothing to split there.
    void findCandidates()
    {
        candidates.clear();
        const auto* sketch = sketchgui->getSketchObject();
        const auto* traced = dynamic_cast<const Part::GeomCurve*>(sketch->getGeometry(tracedGeoId));
        if (!traced) {
            return;
        }
        constexpr double onCurve = 1e-7;
        std::vector<Base::Vector3d> ownEnds;
        if (!traced->is<Part::GeomCircle>()) {
            ownEnds.push_back(Sketcher::SketchObject::getPoint(traced, Sketcher::PointPos::start));
            ownEnds.push_back(Sketcher::SketchObject::getPoint(traced, Sketcher::PointPos::end));
        }
        auto add = [&](const Base::Vector3d& p) {
            for (const auto& end : ownEnds) {
                if ((p - end).Length() < 1e-6) {
                    return;
                }
            }
            double u = 0;
            if (!traced->closestParameter(p, u) || (traced->value(u) - p).Length() > onCurve) {
                return;
            }
            Base::Vector2d point(p.x, p.y);
            for (const auto& known : candidates) {
                if ((known - point).Length() < 1e-6) {
                    return;
                }
            }
            candidates.push_back(point);
        };
        auto addCurve = [&](int geoId) {
            if (geoId == tracedGeoId) {
                return;  // a curve's intersection with itself is out of scope
            }
            const Part::Geometry* geom = sketch->getGeometry(geoId);
            if (!geom) {
                return;
            }
            if (geom->is<Part::GeomPoint>()) {
                add(Sketcher::SketchObject::getPoint(geom, Sketcher::PointPos::start));
                return;
            }
            const auto* curve = dynamic_cast<const Part::GeomCurve*>(geom);
            if (!curve) {
                return;
            }
            std::vector<std::pair<Base::Vector3d, Base::Vector3d>> points;
            try {
                if (traced->intersect(curve, points, onCurve)) {
                    for (const auto& pair : points) {
                        add(pair.first);
                    }
                }
            }
            catch (...) {  // no intersection found
            }
            for (auto pos : {Sketcher::PointPos::start, Sketcher::PointPos::end, Sketcher::PointPos::mid}) {
                if (pos == Sketcher::PointPos::mid
                    && !geom->isDerivedFrom<Part::GeomConic>()
                    && !geom->isDerivedFrom<Part::GeomArcOfConic>()) {
                    continue;
                }
                if (pos != Sketcher::PointPos::mid && !geom->isDerivedFrom<Part::GeomBoundedCurve>()) {
                    continue;
                }
                add(Sketcher::SketchObject::getPoint(geom, pos));
            }
        };
        for (int geoId = 0; geoId <= sketch->getHighestCurveIndex(); ++geoId) {
            addCurve(geoId);
        }
        // external geometry (the sketch's own axes, -1 and -2, are not cutters)
        for (int geoId = Sketcher::GeoEnum::RefExt; geoId >= -sketch->getExternalGeometryCount();
             --geoId) {
            addCurve(geoId);
        }
    }

    Base::Vector2d projectToCurve(int geoId, const Base::Vector2d& point) const
    {
        const auto* curve
            = dynamic_cast<const Part::GeomCurve*>(sketchgui->getSketchObject()->getGeometry(geoId));
        double u = 0;
        Base::Vector3d p(point.x, point.y, 0);
        if (curve && curve->closestParameter(p, u)) {
            Base::Vector3d on = curve->value(u);
            return {on.x, on.y};
        }
        return point;
    }

    void drawMarkers()
    {
        EditMarkers.clear();
        if (firstGeoId != Sketcher::GeoEnum::GeoUndef) {
            EditMarkers.push_back(firstPoint);
        }
        if (snapped) {
            EditMarkers.push_back(snapPoint);
        }
        drawEditMarkers(EditMarkers, 2);
    }

    void refuse(const QString& text)
    {
        refusal = text;
        updateHint();
    }

    enum State
    {
        WaitingForEdge
    };

private:
    std::vector<Base::Vector2d> EditMarkers;
    int firstGeoId = Sketcher::GeoEnum::GeoUndef;  // a circle waiting for its second point
    Base::Vector2d firstPoint;
    int tracedGeoId = Sketcher::GeoEnum::GeoUndef;  // the last curve the preselection was on
    int lastPreselectCurve = Sketcher::GeoEnum::GeoUndef;
    std::vector<Base::Vector2d> candidates;         // the traced curve's intersection points
    bool snapped = false;                           // the pick is at snapPoint
    Base::Vector2d snapPoint;
    QString refusal;  // why the last pick did nothing, shown in the hint line until the next pick
    Base::Vector2d cursor;  // the cursor's position on the sketch at the last move
    bool hasCursor = false;

public:
    std::list<Gui::InputHint> getToolHints() const override
    {
        QString prefix = refusal.isEmpty() ? QString() : refusal + QStringLiteral(". ");
        if (firstGeoId != Sketcher::GeoEnum::GeoUndef) {
            return {
                {prefix + tr("%1 select a second point to split the closed curve", "Sketcher Splitting: hint"),
                 {Gui::InputHint::UserInput::MouseLeft}},
            };
        }
        return {
            {prefix + tr("%1 pick location on edge to split", "Sketcher Splitting: hint"),
             {Gui::InputHint::UserInput::MouseLeft}},
        };
    }
};

}  // namespace SketcherGui
