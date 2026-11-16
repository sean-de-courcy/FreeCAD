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

#include <QApplication>
#include <Base/Tools.h>

#include <Gui/Notifications.h>
#include <Gui/Selection/SelectionFilter.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>

#include <Mod/Sketcher/App/SketchObject.h>

#include "DrawSketchControllableHandler.h"
#include "DrawSketchDefaultWidgetController.h"
#include "DrawSketchHandlerSplitting.h"  // SketchCurveTracer, curvesThrough
#include "Utils.h"
#include "ViewProviderSketch.h"


namespace SketcherGui
{

class TrimmingSelection: public Gui::SelectionFilterGate
{
    App::DocumentObject* object;

public:
    explicit TrimmingSelection(App::DocumentObject* obj)
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
            if (geom->isDerivedFrom<Part::GeomTrimmedCurve>() || geom->is<Part::GeomCircle>()
                || geom->is<Part::GeomEllipse>() || geom->is<Part::GeomBSplineCurve>()) {
                // We do not trim internal geometry of complex geometries
                if (Sketcher::GeometryFacade::isInternalType(geom, Sketcher::InternalType::None)) {
                    return true;
                }
            }
        }
        else if (element.substr(0, 6) == "Vertex") {
            // FreeCAD-CH (sketcher 4, Onshape SK19): the cursor can rest on any point with the
            // normal cursor, as in Onshape; a click on a point trims nothing
            return true;
        }
        return false;
    }
};

class DrawSketchHandlerTrimming;

using DSHTrimmingController = DrawSketchDefaultWidgetController<
    DrawSketchHandlerTrimming,
    StateMachines::OneSeekEnd,
    /*PAutoConstraintSize=*/0,
    /*OnViewParametersT=*/OnViewParameters<0, 0>,
    /*WidgetParametersT=*/WidgetParameters<0, 0>,
    /*WidgetCheckboxesT=*/WidgetCheckboxes<1, 1>,
    /*WidgetComboboxesT=*/WidgetComboboxes<0, 0>,
    /*WidgetLineEditsT=*/WidgetLineEdits<0, 0>>;

using DSHTrimmingControllerBase = DSHTrimmingController::ControllerBase;
using DrawSketchHandlerTrimmingBase = DrawSketchControllableHandler<DSHTrimmingController>;

class DrawSketchHandlerTrimming: public DrawSketchHandlerTrimmingBase
{
    Q_DECLARE_TR_FUNCTIONS(SketcherGui::DrawSketchHandlerTrimming)

    friend DSHTrimmingController;
    friend DSHTrimmingControllerBase;

public:
    DrawSketchHandlerTrimming()
        : DrawSketchHandlerTrimmingBase()
    {}
    ~DrawSketchHandlerTrimming() override
    {
        Gui::Selection().rmvSelectionGate();
    }

    bool pressButton(Base::Vector2d onSketchPos) override
    {
        mousePressed = true;
        pressing = hasHover;  // the press trims what the last hover showed
        // FreeCAD-CH (sketcher 4): a button event's position is the point the pick hit, often a
        // vertex of the curve's drawn polyline (a line's middle, millimetres from the cursor), so
        // a click trimmed the wrong piece; the last hover's position is the cursor's
        return DrawSketchControllableHandler::pressButton(hasHover ? hoverPos : onSketchPos);
    }

    bool releaseButton(Base::Vector2d onSketchPos) override
    {
        mousePressed = false;
        return DrawSketchControllableHandler::releaseButton(onSketchPos);
    }

    // FreeCAD-CH (sketcher 4, Onshape SK19-SK25): near a point where another curve crosses the
    // curve the cursor came along (the traced curve, as Split's), the pick snaps to the crossing
    // (Onshape's exact crossing), and Trim trims the highest piece there of all the curves through
    // it, whichever curve was traced (Onshape trims a circle's upper arc at either crossing with a
    // line, along either curve, and the upper piece of a vertical line). Where another curve only ends inside the
    // traced one, the traced curve's piece on the cursor's side goes. On a point: a curve's free
    // end trims that curve, a corner trims the other curve there, a centre does nothing.
    void updateDataAndDrawToPosition(Base::Vector2d onSketchPos) override
    {
        int preselect = getPreselectCurve();

        // Hold-and-drag trim; the press itself trims what the last hover resolved
        if (mousePressed) {
            if (!pressing) {
                trimPos = onSketchPos;
                geoIdToTrim = preselect;
            }
            pressing = false;
            executeCommands();
            return;
        }

        hoverPos = onSketchPos;
        hasHover = true;
        trimPos = onSketchPos;
        geoIdToTrim = preselect;
        tracer.trace(sketchgui, onSketchPos, preselect, [this](int geoId) {
            return isTrimmable(geoId);
        });
        int resolvedGeoId = Sketcher::GeoEnum::GeoUndef;
        Base::Vector2d resolvedPos;
        if (tracer.isSnapped()) {
            if (resolveAtSnap(onSketchPos, resolvedGeoId, resolvedPos)) {
                geoIdToTrim = resolvedGeoId;
                trimPos = resolvedPos;
            }
            else {
                tracer.dropSnap();  // nothing to resolve there: trim as usual
            }
        }
        else if (preselect < 0) {
            geoIdToTrim = Sketcher::GeoEnum::GeoUndef;
            if (resolveAtPoint(getPreselectPoint(), onSketchPos, resolvedGeoId, resolvedPos)) {
                geoIdToTrim = resolvedGeoId;
                trimPos = resolvedPos;
            }
        }

        if (geoIdToTrim < 0) {
            EditMarkers.resize(0);
            drawEditMarkers(EditMarkers, 2);
        }

        auto sk = sketchgui->getObject<Sketcher::SketchObject>();
        int GeoId1, GeoId2;
        Base::Vector3d intersect1, intersect2;
        if (!sk->seekTrimPoints(
                geoIdToTrim,
                Base::Vector3d(trimPos.x, trimPos.y, 0),
                includeAxes,
                GeoId1,
                intersect1,
                GeoId2,
                intersect2
            )) {
            return;
        }

        EditMarkers.resize(0);

        if (GeoId1 != Sketcher::GeoEnum::GeoUndef) {
            EditMarkers.emplace_back(intersect1.x, intersect1.y);
        }
        else {
            auto start = sk->getPoint(geoIdToTrim, Sketcher::PointPos::start);
            EditMarkers.emplace_back(start.x, start.y);
        }

        if (GeoId2 != Sketcher::GeoEnum::GeoUndef) {
            EditMarkers.emplace_back(intersect2.x, intersect2.y);
        }
        else {
            auto end = sk->getPoint(geoIdToTrim, Sketcher::PointPos::end);
            EditMarkers.emplace_back(end.x, end.y);
        }

        // maker augmented by two sizes (see supported marker sizes)
        drawEditMarkers(EditMarkers, 2);
    }

    bool canGoToNextMode() override
    {
        if (geoIdToTrim < 0) {
            return false;
        }
        const Part::Geometry* geo = sketchgui->getSketchObject()->getGeometry(geoIdToTrim);
        return geo->isDerivedFrom<Part::GeomTrimmedCurve>() || geo->is<Part::GeomCircle>()
            || geo->is<Part::GeomEllipse>() || geo->is<Part::GeomBSplineCurve>();
    }

    void executeCommands() override
    {
        if (geoIdToTrim < 0) {
            return;
        }

        // FIXME: Attempt to avoid double trimming. This messes up the cursor.
        // Possibly `mouseMove` gets triggered after first trim, but before preselection,
        // resulting in another edge being deleted.
        Gui::Selection().rmvPreselect();

        try {
            openCommand(QT_TRANSLATE_NOOP("Command", "Trim edge"));
            Gui::cmdAppObjectArgs(
                sketchgui->getObject(),
                "trim(%d,App.Vector(%.12g,%.12g,0),%s)",
                geoIdToTrim,
                trimPos.x,
                trimPos.y,
                includeAxes ? "True" : "False"
            );
            commitCommand();
            tryAutoRecompute(sketchgui->getObject<Sketcher::SketchObject>());
        }
        catch (const Base::Exception&) {
            Gui::NotifyError(
                sketchgui,
                QT_TRANSLATE_NOOP("Notifications", "Error"),
                QT_TRANSLATE_NOOP("Notifications", "Failed to trim edge")
            );
            abortCommand();
        }
        // the geometry changed: the traced curve's index and its crossings are stale
        tracer.reset();
    }

private:
    std::string getToolName() const override
    {
        return "DSH_Trimming";
    }

    QString getCrosshairCursorSVGName() const override
    {
        Gui::Selection().rmvSelectionGate();
        Gui::Selection().addSelectionGate(new TrimmingSelection(sketchgui->getObject()));
        return QStringLiteral("Sketcher_Pointer_Trimming");
    }

    std::unique_ptr<QWidget> createWidget() const override
    {
        return std::make_unique<SketcherToolDefaultWidget>();
    }

    bool isWidgetVisible() const override
    {
        return true;
    };

    QPixmap getToolIcon() const override
    {
        return Gui::BitmapFactory().pixmap("Sketcher_Trimming");
    }

    QString getToolWidgetText() const override
    {
        return QString(tr("Trimming Parameters"));
    }

    bool isTrimmable(int geoId) const
    {
        if (geoId < 0) {
            return false;
        }
        const Part::Geometry* geo = sketchgui->getSketchObject()->getGeometry(geoId);
        return geo
            && (geo->isDerivedFrom<Part::GeomTrimmedCurve>() || geo->is<Part::GeomCircle>()
                || geo->is<Part::GeomEllipse>() || geo->is<Part::GeomBSplineCurve>())
            && Sketcher::GeometryFacade::isInternalType(geo, Sketcher::InternalType::None);
    }

    bool endsAt(int geoId, const Base::Vector2d& p) const
    {
        const auto* sketch = sketchgui->getSketchObject();
        const Part::Geometry* geom = sketch->getGeometry(geoId);
        Base::Vector3d at(p.x, p.y, 0);
        return geom && geom->isDerivedFrom<Part::GeomBoundedCurve>()
            && ((sketch->getPoint(geoId, Sketcher::PointPos::start) - at).Length() <= 1e-7
                || (sketch->getPoint(geoId, Sketcher::PointPos::end) - at).Length() <= 1e-7);
    }

    /// A point inside the piece of curve geoId next to p (just off p, on the curve), on the side
    /// takeAfter picks from the point before p and the one after it in the curve's direction; at
    /// an end of the curve, the one side there is. False if p isn't on the curve.
    bool pointBeside(
        int geoId,
        const Base::Vector2d& p,
        const std::function<bool(const Base::Vector2d&, const Base::Vector2d&, const Base::Vector2d&)>& takeAfter,
        Base::Vector2d& inside
    ) const
    {
        const auto* curve
            = dynamic_cast<const Part::GeomCurve*>(sketchgui->getSketchObject()->getGeometry(geoId));
        Base::Vector3d at(p.x, p.y, 0);
        double u0 = 0;
        if (!curve || !curve->closestParameter(at, u0) || (curve->value(u0) - at).Length() > 1e-7) {
            return false;
        }
        double speed = curve->firstDerivativeAtParameter(u0).Length();
        if (speed <= 0) {
            return false;
        }
        double step = 1e-3 * SketchCurveTracer::pickRadius(sketchgui) / speed;  // NOLINT
        bool periodic = curve->is<Part::GeomCircle>() || curve->is<Part::GeomEllipse>();
        if (const auto* bspline = dynamic_cast<const Part::GeomBSplineCurve*>(curve)) {
            periodic = bspline->isPeriodic();
        }
        double first = curve->getFirstParameter();
        double last = curve->getLastParameter();
        auto at2d = [&](double u) {
            Base::Vector3d v = curve->value(u);
            return Base::Vector2d(v.x, v.y);
        };
        bool hasBefore = periodic || u0 - step >= first;
        bool hasAfter = periodic || u0 + step <= last;
        if (hasBefore && hasAfter) {
            Base::Vector2d before = at2d(u0 - step);
            Base::Vector2d after = at2d(u0 + step);
            inside = takeAfter(p, before, after) ? after : before;
            return true;
        }
        if (hasBefore || hasAfter) {
            inside = at2d(hasAfter ? u0 + step : u0 - step);
            return true;
        }
        return false;
    }

    /// The snapped crossing: Onshape trims the highest piece of the curves through it, the traced
    /// one included (SK19-SK23); where the other curves only end there, the traced curve's piece
    /// on the cursor's side (SK25).
    bool resolveAtSnap(const Base::Vector2d& cursorPos, int& geoId, Base::Vector2d& inside) const
    {
        const auto* sketch = sketchgui->getSketchObject();
        const Base::Vector2d& p = tracer.snapPoint();
        int traced = tracer.tracedGeoId();
        auto others = curvesThrough(sketch, p, [&](int g) {
            return g == traced || !isTrimmable(g);
        });
        // each curve's higher piece there (level: the one to the right), then the highest of them
        auto higher = [](const Base::Vector2d& a, const Base::Vector2d& b) {
            if (std::abs(a.y - b.y) > 1e-12) {  // NOLINT
                return a.y > b.y;
            }
            return a.x > b.x;
        };
        auto upper = [&](const Base::Vector2d&, const Base::Vector2d& before, const Base::Vector2d& after) {
            return higher(after, before);
        };
        bool crossing = false;
        std::vector<int> through(1, traced);
        for (int other : others) {
            if (!endsAt(other, p)) {
                crossing = true;
                through.push_back(other);
            }
        }
        if (crossing) {
            bool found = false;
            for (int g : through) {
                Base::Vector2d candidate;
                if (g >= 0 && pointBeside(g, p, upper, candidate) && (!found || higher(candidate, inside))) {
                    inside = candidate;
                    geoId = g;
                    found = true;
                }
            }
            return found;
        }
        if (others.empty() || traced < 0) {
            return false;
        }
        if (pointBeside(traced, p, cursorSide(cursorPos), inside)) {
            geoId = traced;
            return true;
        }
        return false;
    }

    /// Picks the piece on the cursor's side of a point along a curve (level: the piece before).
    std::function<bool(const Base::Vector2d&, const Base::Vector2d&, const Base::Vector2d&)>
    cursorSide(const Base::Vector2d& cursorPos) const
    {
        double radius = SketchCurveTracer::pickRadius(sketchgui);
        return [cursorPos, radius](const Base::Vector2d& at, const Base::Vector2d&, const Base::Vector2d& after) {
            Base::Vector2d direction = after - at;
            direction.Normalize();
            return (cursorPos - at) * direction > 0.1 * radius;  // NOLINT
        };
    }

    /// A point under the cursor (Onshape SK24, SK25). Inside a curve (another curve's end on it):
    /// that curve's piece on the cursor's side, the traced one if it passes there. Else the curves
    /// that end there: the other curve than the traced one if there is one, else that curve (a
    /// free end: a curve with no crossing goes whole). A centre or a lone point: nothing.
    bool resolveAtPoint(int vertex, const Base::Vector2d& cursorPos, int& geoId, Base::Vector2d& inside) const
    {
        if (vertex < 0) {
            return false;
        }
        const auto* sketch = sketchgui->getSketchObject();
        int pointGeoId = Sketcher::GeoEnum::GeoUndef;
        Sketcher::PointPos pointPos = Sketcher::PointPos::none;
        sketch->getGeoVertexIndex(vertex, pointGeoId, pointPos);
        if (pointGeoId == Sketcher::GeoEnum::GeoUndef) {
            return false;
        }
        Base::Vector3d at = sketch->getPoint(pointGeoId, pointPos);
        Base::Vector2d p(at.x, at.y);
        int traced = tracer.tracedGeoId();
        auto passing = curvesThrough(sketch, p, [&](int g) {
            return g < 0 || !isTrimmable(g) || endsAt(g, p);
        });
        if (!passing.empty()) {
            int chosen = std::find(passing.begin(), passing.end(), traced) != passing.end()
                ? traced
                : passing.front();
            if (pointBeside(chosen, p, cursorSide(cursorPos), inside)) {
                geoId = chosen;
                return true;
            }
            return false;
        }
        std::vector<int> ending;
        for (int g = 0; g <= sketch->getHighestCurveIndex(); ++g) {
            if (isTrimmable(g) && endsAt(g, p)) {
                ending.push_back(g);
            }
        }
        if (ending.empty()) {
            return false;
        }
        int chosen = ending.front();
        for (int g : ending) {
            if (g != traced) {
                chosen = g;
                break;
            }
        }
        auto either = [](const Base::Vector2d&, const Base::Vector2d&, const Base::Vector2d&) {
            return false;
        };
        if (pointBeside(chosen, p, either, inside)) {
            geoId = chosen;
            return true;
        }
        return false;
    }

private:
    std::vector<Base::Vector2d> EditMarkers;
    SketchCurveTracer tracer;
    Base::Vector2d hoverPos;  // the cursor's position at the last move without a button held
    bool hasHover = false;
    bool pressing = false;  // the press's own update: it trims what the last hover resolved
    bool mousePressed = false;
    Base::Vector2d trimPos;
    int geoIdToTrim = Sketcher::GeoEnum::GeoUndef;
    bool includeAxes = false;

public:
    std::list<Gui::InputHint> getToolHints() const override
    {
        using enum Gui::InputHint::UserInput;

        return Gui::lookupHints<SelectMode>(
            state(),
            {{.state = SelectMode::SeekFirst,
              .hints
              = {{tr("%1 pick edge to trim", "Sketcher Trimming: hint"), {MouseLeft}},
                 {tr("%1 toggle include axes as trim boundaries"), {toolKey(KeyU)}}}}}
        );
    }
};

template<>
void DSHTrimmingController::configureToolWidget()
{
    if (!init) {  // Code to be executed only upon initialisation
        toolWidget->setCheckboxLabel(
            WCheckbox::FirstBox,
            QApplication::translate("TaskSketcherTool_c1_trimming", "Include axes (U)")
        );
        toolWidget->setCheckboxToolTip(
            WCheckbox::FirstBox,
            QApplication::translate("TaskSketcherTool_c1_trimming", "Include axes as trim boundaries")
        );
    }
    syncCheckboxToHandler(WCheckbox::FirstBox, handler->includeAxes);
}

template<>
void DSHTrimmingController::adaptDrawingToCheckboxChange(int checkboxindex, bool value)
{
    if (checkboxindex == WCheckbox::FirstBox) {
        handler->includeAxes = value;
    }
    handler->updateCursor();
}
}  // namespace SketcherGui
