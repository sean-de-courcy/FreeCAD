// SPDX-License-Identifier: LGPL-2.1-or-later
// FreeCAD-CH (Onshape's sketch patterns, onshape-facts GA3-28, 28b, 28c;
// notes/sketch-patterns-design.md item 4): the circular and the linear sketch pattern tools.
//
// The tool starts with the selected geometry as its seeds, or with none. Each click on the
// sketch's own point, line, circle or arc picks it as a seed (a second click unpicks it), and the
// pattern shows at once: 3 instances over the full turn about the sketch's origin (circular), or
// 3 along +X at a spacing of one unit (linear). The preview is the pattern itself, made in an
// open transaction (SketchObject::addCircularPattern, addLinearPattern), so what shows is what
// commits. The tool keys U and J raise and lower the count (R and F the linear pattern's second
// count). A click on empty canvas or Enter commits; Esc, or another tool, cancels: the
// transaction is aborted and nothing is left.

#pragma once

#include <algorithm>
#include <list>
#include <string>
#include <vector>

#include <QObject>

#include <Inventor/events/SoKeyboardEvent.h>

#include <Base/Exception.h>
#include <Gui/CommandT.h>
#include <Gui/InputHint.h>
#include <Gui/Notifications.h>
#include <Gui/Selection/Selection.h>
#include <Mod/Sketcher/App/SketchObject.h>

#include "DrawSketchHandler.h"
#include "Utils.h"
#include "ViewProviderSketch.h"

namespace SketcherGui
{

class DrawSketchHandlerPattern: public DrawSketchHandler
{
public:
    enum class Kind
    {
        Circular,
        Linear
    };

    DrawSketchHandlerPattern(Kind kind, std::vector<int> seeds)
        : kind(kind)
        , seeds(std::move(seeds))
    {}

    ~DrawSketchHandlerPattern() override
    {
        // another tool took over, or editing ended: as Esc
        if (open) {
            try {
                abortCommand();
            }
            catch (...) {
            }
        }
    }

    void mouseMove(SnapManager::SnapHandle /*snapHandle*/) override
    {}

    bool pressButton(Base::Vector2d /*pos*/) override
    {
        return true;
    }

    bool releaseButton(Base::Vector2d /*pos*/) override
    {
        const int geoId = pickedGeoId();
        if (geoId == Sketcher::GeoEnum::GeoUndef) {
            if (open) {
                commit();  // deletes this
            }
            return true;
        }
        if (geoId < 0 || (open && geoId >= firstOwnGeoId)) {
            return true;  // an axis or projected geometry, or the preview's own geometry
        }
        auto found = std::ranges::find(seeds, geoId);
        if (found != seeds.end()) {
            seeds.erase(found);
        }
        else {
            seeds.push_back(geoId);
        }
        rebuild();
        return true;
    }

    void registerPressedKey(bool pressed, int key) override
    {
        if ((key == SoKeyboardEvent::RETURN || key == SoKeyboardEvent::PAD_ENTER) && !pressed) {
            if (open) {
                commit();  // deletes this
            }
            return;
        }
        const bool counts = key == SoKeyboardEvent::U || key == SoKeyboardEvent::J
            || (kind == Kind::Linear && (key == SoKeyboardEvent::R || key == SoKeyboardEvent::F));
        if (counts && pressed && isToolKey(pressed, key)) {
            int& count = (key == SoKeyboardEvent::U || key == SoKeyboardEvent::J) ? count1 : count2;
            const bool up = key == SoKeyboardEvent::U || key == SoKeyboardEvent::R;
            const int changed = std::clamp(count + (up ? 1 : -1), 1, 999);
            if (changed != count) {
                count = changed;
                rebuild();
            }
            return;
        }
        DrawSketchHandler::registerPressedKey(pressed, key);
    }

    void cancelCurrentAction() override
    {
        if (open) {
            abortCommand();
            open = false;
            tryAutoRecomputeIfNotSolve(sketchgui->getSketchObject());
        }
        DrawSketchHandler::cancelCurrentAction();  // deletes this
    }

    std::list<Gui::InputHint> getToolHints() const override
    {
        using enum Gui::InputHint::UserInput;
        std::list<Gui::InputHint> hints {
            {QObject::tr("%1 pick the geometry to pattern", "Sketcher pattern: hint"), {MouseLeft}}
        };
        if (open) {
            hints.push_back(
                {QObject::tr("%1/%2 count: %3", "Sketcher pattern: hint").arg(count1),
                 {toolKey(KeyU), toolKey(KeyJ)}}
            );
            if (kind == Kind::Linear) {
                hints.push_back(
                    {QObject::tr("%1/%2 second count: %3", "Sketcher pattern: hint").arg(count2),
                     {toolKey(KeyR), toolKey(KeyF)}}
                );
            }
            hints.push_back(
                {QObject::tr("%1 or a click on empty canvas: accept", "Sketcher pattern: hint"),
                 {KeyReturn}}
            );
        }
        hints.push_back({QObject::tr("%1 cancel", "Sketcher pattern: hint"), {KeyEscape}});
        return hints;
    }

private:
    void activated() override
    {
        Gui::Selection().clearSelection();
        if (!seeds.empty()) {
            rebuild();
        }
    }

    std::string getToolName() const override
    {
        return kind == Kind::Circular ? "DSH_CircularPattern" : "DSH_LinearPattern";
    }

    /// the sketch geometry under the cursor (a curve, or the geometry a point is of); GeoUndef
    /// for empty canvas
    int pickedGeoId() const
    {
        int geoId = getPreselectCurve();
        if (geoId != -1) {
            return geoId < 0 ? -1 : geoId;  // getPreselectCurve: -1 none, below it an external
        }
        const int vertex = getPreselectPoint();
        if (vertex >= 0) {
            Sketcher::PointPos pos {};
            sketchgui->getSketchObject()->getGeoVertexIndex(vertex, geoId, pos);
            return geoId;
        }
        if (getPreselectCross() >= 0) {
            return -1;  // the origin or an axis: not empty canvas
        }
        return Sketcher::GeoEnum::GeoUndef;
    }

    /// the pattern of the seeds and counts as they are now, in a new transaction (the one before
    /// is aborted); with no seeds, nothing
    void rebuild()
    {
        Sketcher::SketchObject* obj = sketchgui->getSketchObject();
        if (open) {
            abortCommand();
            open = false;
        }
        if (!seeds.empty()) {
            std::string list;
            for (int seed : seeds) {
                list += (list.empty() ? "" : ", ") + std::to_string(seed);
            }
            firstOwnGeoId = obj->getHighestCurveIndex() + 1;
            openCommand(
                kind == Kind::Circular ? QT_TRANSLATE_NOOP("Command", "Circular sketch pattern")
                                       : QT_TRANSLATE_NOOP("Command", "Linear sketch pattern")
            );
            open = true;
            try {
                if (kind == Kind::Circular) {
                    Gui::cmdAppObjectArgs(
                        obj,
                        "addCircularPattern([%s], %d, App.Vector(0, 0, 0))",
                        list,
                        count1
                    );
                }
                else {
                    Gui::cmdAppObjectArgs(
                        obj,
                        "addLinearPattern([%s], %d, App.Vector(1, 0, 0), %d)",
                        list,
                        count1,
                        count2
                    );
                }
            }
            catch (const Base::Exception& e) {
                // refused (an ellipse, another pattern's copy...): the last pick is dropped
                abortCommand();
                open = false;
                Gui::NotifyUserError(obj, QT_TRANSLATE_NOOP("Notifications", "Sketch pattern"), e.what());
                seeds.pop_back();
                if (!seeds.empty()) {
                    rebuild();
                    return;
                }
            }
        }
        tryAutoRecomputeIfNotSolve(obj);
        updateHint();
    }

    void commit()
    {
        commitCommand();
        open = false;
        tryAutoRecomputeIfNotSolve(sketchgui->getSketchObject());
        Gui::Selection().clearSelection();
        quit();  // no code after this line: the handler is deleted
    }

    Kind kind;
    std::vector<int> seeds;
    int count1 {3};
    int count2 {1};
    bool open {false};
    int firstOwnGeoId {0};
};

}  // namespace SketcherGui
