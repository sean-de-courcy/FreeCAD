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

#include <functional>
#include <set>


namespace SketcherGui
{

/// FreeCAD-CH (sketcher 3 and 4, Onshape SK13 and SK19): follows the curve the preselection was on while
/// the cursor approached a point (the traced curve), and snaps to the points inside it where another
/// curve crosses or touches it, or a sketch point lies on it. Split cuts the traced curve there; Trim
/// trims the other curve there (Onshape's Trim doesn't follow the traced curve at a crossing).
class SketchCurveTracer
{
public:
    void reset()
    {
        traced = Sketcher::GeoEnum::GeoUndef;
        lastPreselectCurve = Sketcher::GeoEnum::GeoUndef;
        snapped = false;
        candidates.clear();
    }

    int tracedGeoId() const
    {
        return traced;
    }
    bool isSnapped() const
    {
        return snapped;
    }
    const Base::Vector2d& snapPoint() const
    {
        return snap;
    }
    void dropSnap()
    {
        snapped = false;
    }

    /// The view's pick radius in sketch units: the preselection's reach. Measured on the focal
    /// plane (the sketch plane in a view square to it).
    static double pickRadius(const ViewProviderSketch* sketchgui)
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
    static double snapRadius(const ViewProviderSketch* sketchgui)
    {
        return 1.2 * pickRadius(sketchgui);  // NOLINT
    }

    /// The zone around an intersection where the traced curve stays traced: the other curve's
    /// pick radius reaches it there for crossings down to about 25 degrees.
    static double lockRadius(const ViewProviderSketch* sketchgui)
    {
        return 2.5 * pickRadius(sketchgui);  // NOLINT
    }

    /// Follows the cursor at pos; preselectCurve is the curve the preselection is on (or < 0),
    /// eligible says which curves can be traced.
    void trace(
        ViewProviderSketch* sketchgui,
        const Base::Vector2d& pos,
        int preselectCurve,
        const std::function<bool(int)>& eligible
    )
    {
        // a snapped intersection keeps its curve while the cursor stays at it, whichever curve the
        // preselection is on there: the curve traced on the way in
        if (snapped && (pos - snap).Length() <= snapRadius(sketchgui)) {
            return;
        }
        snapped = false;
        // entering a curve (again) traces it; its intersections are found afresh, since the
        // sketch may have changed meanwhile (an undo). Near one of the traced curve's
        // intersections the other curve's pick radius can take the preselection before the
        // cursor reaches the point: the traced curve stays until the cursor leaves that zone.
        if (!nearCandidate(pos, lockRadius(sketchgui))) {
            if (preselectCurve >= 0 && preselectCurve != lastPreselectCurve && eligible(preselectCurve)) {
                traced = preselectCurve;
                findCandidates(sketchgui->getSketchObject());
            }
            lastPreselectCurve = preselectCurve;
        }
        if (traced == Sketcher::GeoEnum::GeoUndef) {
            return;
        }
        double best = snapRadius(sketchgui);
        for (const auto& candidate : candidates) {
            double distance = (candidate - pos).Length();
            if (distance <= best) {
                best = distance;
                snap = candidate;
                snapped = true;
            }
        }
    }

private:
    bool nearCandidate(const Base::Vector2d& pos, double radius) const
    {
        return traced != Sketcher::GeoEnum::GeoUndef
            && std::any_of(candidates.begin(), candidates.end(), [&](const Base::Vector2d& p) {
                   return (p - pos).Length() <= radius;
               });
    }

    /// The points inside the traced curve where another curve crosses or touches it, or where a
    /// sketch point lies on it (another curve's end, a centre, a point). The curve's own ends
    /// are not candidates.
    void findCandidates(const Sketcher::SketchObject* sketch)
    {
        candidates.clear();
        const auto* tracedCurve = dynamic_cast<const Part::GeomCurve*>(sketch->getGeometry(traced));
        if (!tracedCurve) {
            return;
        }
        constexpr double onCurve = 1e-7;
        std::vector<Base::Vector3d> ownEnds;
        if (!tracedCurve->is<Part::GeomCircle>() && !tracedCurve->is<Part::GeomEllipse>()) {
            ownEnds.push_back(Sketcher::SketchObject::getPoint(tracedCurve, Sketcher::PointPos::start));
            ownEnds.push_back(Sketcher::SketchObject::getPoint(tracedCurve, Sketcher::PointPos::end));
        }
        auto add = [&](const Base::Vector3d& p) {
            for (const auto& end : ownEnds) {
                if ((p - end).Length() < 1e-6) {
                    return;
                }
            }
            double u = 0;
            if (!tracedCurve->closestParameter(p, u) || (tracedCurve->value(u) - p).Length() > onCurve) {
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
            if (geoId == traced) {
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
                if (tracedCurve->intersect(curve, points, onCurve)) {
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

    int traced = Sketcher::GeoEnum::GeoUndef;  // the last curve the preselection was on
    int lastPreselectCurve = Sketcher::GeoEnum::GeoUndef;
    std::vector<Base::Vector2d> candidates;  // the traced curve's intersection points
    bool snapped = false;                    // the pick is at snap
    Base::Vector2d snap;
};

/// FreeCAD-CH (sketcher 4): the curves other than the ones in `skip` that pass through p (within
/// 1e-7), internal geometry and the sketch's axes left out. A curve with an end at p is listed too.
inline std::vector<int> curvesThrough(
    const Sketcher::SketchObject* sketch,
    const Base::Vector2d& p,
    const std::function<bool(int)>& skip
)
{
    std::vector<int> found;
    Base::Vector3d point(p.x, p.y, 0);
    auto check = [&](int geoId) {
        if (skip(geoId)) {
            return;
        }
        const auto* curve = dynamic_cast<const Part::GeomCurve*>(sketch->getGeometry(geoId));
        if (!curve || !Sketcher::GeometryFacade::isInternalType(curve, Sketcher::InternalType::None)) {
            return;
        }
        double u = 0;
        if (curve->closestParameter(point, u) && (curve->value(u) - point).Length() <= 1e-7) {
            found.push_back(geoId);
        }
    };
    for (int geoId = 0; geoId <= sketch->getHighestCurveIndex(); ++geoId) {
        check(geoId);
    }
    for (int geoId = Sketcher::GeoEnum::RefExt; geoId >= -sketch->getExternalGeometryCount(); --geoId) {
        check(geoId);
    }
    return found;
}


class SplittingSelection: public Gui::SelectionFilterGate
{
    App::DocumentObject* object;
    const int* pending;  // a circle waiting for its second point, or GeoUndef

public:
    SplittingSelection(App::DocumentObject* obj, const int* pendingGeoId)
        : Gui::SelectionFilterGate(nullPointer())
        , object(obj)
        , pending(pendingGeoId)
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
            // Onshape SK16: while a circle's first pick is pending, other curves don't highlight
            if (*pending != Sketcher::GeoEnum::GeoUndef && GeoId != *pending) {
                return false;
            }
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
            // way in splits that curve, anything else does nothing (Onshape SK18).
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

    // FreeCAD-CH (sketcher 3 and 4, Ward's hand-check 6; Onshape SK11, SK13-SK18): the curve that
    // is split at an intersection is the one the preselection was on while the cursor approached
    // it (the traced curve). Near a point where another curve crosses or touches it (or a sketch
    // point lies on it), the pick snaps there and a marker shows it, and the split ties the new
    // end to the other curve. A whole circle takes two picks, the first shown by a marker until
    // the second; meanwhile other curves can't be picked, and Esc leaves the tool.
    void mouseMove(SnapManager::SnapHandle snapHandle) override
    {
        cursor = snapHandle.cursorPos;
        hasCursor = true;
        tracer.trace(sketchgui, cursor, getPreselectCurve(), [this](int geoId) {
            return isSplittable(geoId);
        });
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
        bool atIntersection = false;

        if (tracer.isSnapped()) {
            GeoId = tracer.tracedGeoId();
            point = tracer.snapPoint();
            atIntersection = true;
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
            if (pointGeoId != Sketcher::GeoEnum::GeoUndef && conIt != constraints.end()
                && firstGeoId == Sketcher::GeoEnum::GeoUndef) {
                GeoId = (*conIt)->Second;
                Base::Vector3d knot = getSketchObject()->getPoint(pointGeoId, pointPos);
                point = Base::Vector2d(knot.x, knot.y);  // at the knot, not the cursor's pixel
            }
            else if (pointGeoId != Sketcher::GeoEnum::GeoUndef
                     && firstGeoId == Sketcher::GeoEnum::GeoUndef
                     && insideAnotherCurve(getSketchObject()->getPoint(pointGeoId, pointPos))) {
                // Onshape SK17: a curve traced to its own end where another curve's middle passes
                // is split there, leaving a zero-length arc. FreeCAD's curves can't have zero
                // length (OCCT refuses the arc), so this one case is refused, loudly.
                refuse(tr("Cannot split a curve at its own end (it would leave a zero-length piece)"));
                return true;
            }
            else {
                // Onshape SK18: a curve's end, a corner or a centre: nothing happens
                return true;
            }
        }

        if (GeoId < 0) {
            if (firstGeoId != Sketcher::GeoEnum::GeoUndef) {
                return true;  // Onshape SK16: a click off the pending circle does nothing
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
            return true;  // Onshape SK16: a pick on another curve does nothing; the first stays
        }
        if (geom->is<Part::GeomCircle>()) {
            Base::Vector2d onCircle = projectToCurve(GeoId, point);
            if (firstGeoId == Sketcher::GeoEnum::GeoUndef) {
                firstGeoId = GeoId;
                firstPoint = onCircle;
                firstAtIntersection = atIntersection;
                refusal.clear();
                updateHint();
                drawMarkers();
                return true;
            }
            if ((onCircle - firstPoint).Length() < SketchCurveTracer::snapRadius(sketchgui)) {
                refuse(tr("Select a second point away from the first"));
                return true;
            }
        }

        // what the split's ties need: the curves there before it (by tag: a circle's split
        // renumbers the geometry), and whether a line is split at its midpoint
        std::set<boost::uuids::uuid> before;
        const auto* sketch = getSketchObject();
        for (int geoId = 0; geoId <= sketch->getHighestCurveIndex(); ++geoId) {
            if (geoId != GeoId) {
                before.insert(sketch->getGeometry(geoId)->getTag());
            }
        }
        bool atLineMidpoint = false;
        if (const auto* line = dynamic_cast<const Part::GeomLineSegment*>(geom)) {
            Base::Vector3d mid = (line->getStartPoint() + line->getEndPoint()) / 2;
            atLineMidpoint = (Base::Vector2d(mid.x, mid.y) - point).Length() < 1e-7;
        }
        std::vector<Base::Vector2d> ties;
        if (firstGeoId == GeoId && firstAtIntersection) {
            ties.push_back(firstPoint);
        }
        if (atIntersection) {
            ties.push_back(point);
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
            for (const auto& tie : ties) {
                tieSplitPoint(tie, before, atLineMidpoint && ties.size() == 1);
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
        firstAtIntersection = false;
        refusal.clear();
        // the geometry changed: the traced curve's index and its intersections are stale
        tracer.reset();
        updateHint();
        drawMarkers();
        return true;
    }

private:
    void activated() override
    {
        Gui::Selection().clearSelection();
        Gui::Selection().rmvSelectionGate();
        Gui::Selection().addSelectionGate(new SplittingSelection(sketchgui->getObject(), &firstGeoId));
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

    /// whether p lies inside a curve (on it, but not at one of its ends)
    bool insideAnotherCurve(const Base::Vector3d& p) const
    {
        const auto* sketch = sketchgui->getSketchObject();
        auto hasEndAt = [&](int geoId) {
            const Part::Geometry* geom = sketch->getGeometry(geoId);
            if (!geom || !geom->isDerivedFrom<Part::GeomBoundedCurve>()) {
                return false;
            }
            return (sketch->getPoint(geoId, Sketcher::PointPos::start) - p).Length() <= 1e-7
                || (sketch->getPoint(geoId, Sketcher::PointPos::end) - p).Length() <= 1e-7;
        };
        return !curvesThrough(sketch, Base::Vector2d(p.x, p.y), hasEndAt).empty();
    }

    /// Onshape SK14 and SK15: the end made by a split at an intersection is tied to the other
    /// curves there: coincident with a point or a curve's end or centre at it, else on the curve.
    /// A line split at its midpoint gets a midpoint tie instead (Onshape's MIDPOINT; here the two
    /// pieces equal, since the pieces' tangency already holds them in line).
    void tieSplitPoint(const Base::Vector2d& p, const std::set<boost::uuids::uuid>& before, bool atLineMidpoint)
    {
        const auto* sketch = getSketchObject();
        Base::Vector3d at(p.x, p.y, 0);
        constexpr double tol = 1e-7;
        std::vector<int> pieces;
        int jointGeoId = Sketcher::GeoEnum::GeoUndef;
        Sketcher::PointPos jointPos = Sketcher::PointPos::none;
        for (int geoId = 0; geoId <= sketch->getHighestCurveIndex(); ++geoId) {
            if (before.count(sketch->getGeometry(geoId)->getTag()) != 0) {
                continue;
            }
            pieces.push_back(geoId);
            for (auto pos : {Sketcher::PointPos::start, Sketcher::PointPos::end}) {
                if (jointGeoId == Sketcher::GeoEnum::GeoUndef
                    && (sketch->getPoint(geoId, pos) - at).Length() <= tol) {
                    jointGeoId = geoId;
                    jointPos = pos;
                }
            }
        }
        if (jointGeoId == Sketcher::GeoEnum::GeoUndef) {
            return;
        }
        auto isPiece = [&](int geoId) {
            return std::find(pieces.begin(), pieces.end(), geoId) != pieces.end();
        };
        if (atLineMidpoint && pieces.size() == 2
            && sketch->getGeometry(pieces[0])->is<Part::GeomLineSegment>()
            && sketch->getGeometry(pieces[1])->is<Part::GeomLineSegment>()) {
            Gui::cmdAppObjectArgs(
                sketchgui->getObject(),
                "addConstraint(Sketcher.Constraint('Equal',%d,%d))",
                pieces[0],
                pieces[1]
            );
            return;
        }
        // a tie at p already (the split carried it over): a constraint naming that curve and a
        // piece's vertex at p
        auto pieceVertexAt = [&](int geoId, Sketcher::PointPos pos) {
            return isPiece(geoId) && pos != Sketcher::PointPos::none
                && (sketch->getPoint(geoId, pos) - at).Length() <= tol;
        };
        auto alreadyTied = [&](int other) {
            for (const auto* c : sketch->Constraints.getValues()) {
                if (c->Type != Sketcher::Coincident && c->Type != Sketcher::PointOnObject) {
                    continue;
                }
                if ((c->Second == other && pieceVertexAt(c->First, c->FirstPos))
                    || (c->First == other && pieceVertexAt(c->Second, c->SecondPos))) {
                    return true;
                }
            }
            return false;
        };
        bool vertexTied = false;
        auto tieTo = [&](int other) {
            const Part::Geometry* geom = sketch->getGeometry(other);
            if (!geom || alreadyTied(other)) {
                return;
            }
            for (auto pos : {Sketcher::PointPos::start, Sketcher::PointPos::end, Sketcher::PointPos::mid}) {
                if (geom->is<Part::GeomPoint>() && pos != Sketcher::PointPos::start) {
                    continue;
                }
                if (pos == Sketcher::PointPos::mid && !geom->isDerivedFrom<Part::GeomConic>()
                    && !geom->isDerivedFrom<Part::GeomArcOfConic>()) {
                    continue;
                }
                if (pos != Sketcher::PointPos::mid && !geom->is<Part::GeomPoint>()
                    && !geom->isDerivedFrom<Part::GeomBoundedCurve>()) {
                    continue;
                }
                if ((sketch->getPoint(other, pos) - at).Length() <= tol) {
                    // one coincidence: the ends already joined there (a split curve's two pieces)
                    // would make a second one redundant
                    if (vertexTied) {
                        return;
                    }
                    vertexTied = true;
                    Gui::cmdAppObjectArgs(
                        sketchgui->getObject(),
                        "addConstraint(Sketcher.Constraint('Coincident',%d,%d,%d,%d))",
                        jointGeoId,
                        static_cast<int>(jointPos),
                        other,
                        static_cast<int>(pos)
                    );
                    return;
                }
            }
            if (geom->is<Part::GeomPoint>()) {
                return;
            }
            Gui::cmdAppObjectArgs(
                sketchgui->getObject(),
                "addConstraint(Sketcher.Constraint('PointOnObject',%d,%d,%d))",
                jointGeoId,
                static_cast<int>(jointPos),
                other
            );
        };
        for (int other : curvesThrough(sketch, p, isPiece)) {
            tieTo(other);
        }
        // points and centres at p (a curve not passing through p)
        for (int geoId = 0; geoId <= sketch->getHighestCurveIndex(); ++geoId) {
            const Part::Geometry* geom = sketch->getGeometry(geoId);
            if (isPiece(geoId) || !Sketcher::GeometryFacade::isInternalType(geom, Sketcher::InternalType::None)) {
                continue;
            }
            bool pointAt = geom->is<Part::GeomPoint>()
                && (sketch->getPoint(geoId, Sketcher::PointPos::start) - at).Length() <= tol;
            bool centreAt = (geom->isDerivedFrom<Part::GeomConic>() || geom->isDerivedFrom<Part::GeomArcOfConic>())
                && (sketch->getPoint(geoId, Sketcher::PointPos::mid) - at).Length() <= tol;
            if (pointAt || centreAt) {
                tieTo(geoId);
            }
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
        if (tracer.isSnapped()) {
            EditMarkers.push_back(tracer.snapPoint());
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
    bool firstAtIntersection = false;  // the first pick was snapped to an intersection
    SketchCurveTracer tracer;
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
