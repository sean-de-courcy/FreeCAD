// SPDX-License-Identifier: LGPL-2.1-or-later
/***************************************************************************
 *   Copyright (c) 2026 Crawlspace Habitats LLC                            *
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

// FreeCAD-CH (ops#640): Onshape's mouse: right-drag turns about the point under the cursor,
// freely (a trackball) and Alt+right-drag keeps Z up (a turntable),
// middle or Ctrl+right pans, the wheel zooms at the cursor, a double middle click fits the model,
// Shift+right does nothing, and a right click (a jitter within the dead zone allowed) selects
// the entity under the cursor before it opens the context menu, under the fork's keymap.

#include <Inventor/nodes/SoCamera.h>
#include <QApplication>

#include <string>

#include "ForkKeymap.h"
#include "Navigation/NavigationStyle.h"
#include "Selection.h"
#include "View3DInventorViewer.h"


using namespace Gui;

// ----------------------------------------------------------------------------------

/* TRANSLATOR Gui::OnshapeNavigationStyle */

TYPESYSTEM_SOURCE(Gui::OnshapeNavigationStyle, Gui::UserNavigationStyle)

OnshapeNavigationStyle::OnshapeNavigationStyle() = default;

OnshapeNavigationStyle::~OnshapeNavigationStyle() = default;

const char* OnshapeNavigationStyle::mouseButtons(ViewerMode mode)
{
    switch (mode) {
        case NavigationStyle::SELECTION:
            return QT_TR_NOOP("Press left mouse button");
        case NavigationStyle::PANNING:
            return QT_TR_NOOP("Press middle mouse button or Ctrl + right mouse button");
        case NavigationStyle::DRAGGING:
            return QT_TR_NOOP("Press right mouse button");
        case NavigationStyle::ZOOMING:
            return QT_TR_NOOP("Scroll mouse wheel");
        default:
            return "No description";
    }
}

/*!
 * A middle press within the double-click interval of the previous middle click (a press and
 * a release that didn't pan) is the second click of a double click.
 */
bool OnshapeNavigationStyle::isDoubleMiddleClick(const SoEvent* const ev) const
{
    if (lastMiddleClickTime == SbTime::zero()) {
        return false;
    }
    const SbTime elapsed = ev->getTime() - lastMiddleClickTime;
    const auto interval = static_cast<float>(QApplication::doubleClickInterval()) / 1000.0F;
    return elapsed.getValue() < interval;
}

/*!
 * Onshape's right click selects what is under the cursor: the preselected entity becomes the
 * selection unless it is selected already. With no preselection the selection stays as it is.
 */
void OnshapeNavigationStyle::selectPreselected()
{
    SelectionSingleton& selection = Gui::Selection();
    if (!selection.hasPreselection()) {
        return;
    }
    // copies: the selection changes below would invalidate the preselection's pointers
    const SelectionChanges& preselection = selection.getPreselection();
    const std::string docName = preselection.Object.getDocumentName();
    const std::string objName = preselection.Object.getObjectName();
    const std::string subName = preselection.Object.getSubName();
    if (selection.isSelected(docName.c_str(), objName.c_str(), subName.c_str())) {
        return;
    }
    // keep the preselection: the context menu that follows lists the entity's own entries
    selection.clearSelection(docName.c_str(), false);
    selection.addSelection(
        docName.c_str(),
        objName.c_str(),
        subName.c_str(),
        0,
        0,
        0,
        nullptr,
        false
    );
}

SbBool OnshapeNavigationStyle::processSoEvent(const SoEvent* const ev)
{
    // Events when in "ready-to-seek" mode are ignored, except those
    // which influence the seek mode itself -- these are handled further
    // up the inheritance hierarchy.
    if (this->isSeekMode()) {
        return inherited::processSoEvent(ev);
    }
    // Switch off viewing mode
    if (!this->isSeekMode() && !this->isAnimating() && this->isViewing()) {
        this->setViewing(false);  // by default disable viewing mode to render the scene
    }

    const SoType type(ev->getTypeId());

    const SbViewportRegion& vp = viewer->getSoRenderManager()->getViewportRegion();
    const SbVec2s pos(ev->getPosition());
    const SbVec2f posn = normalizePixelPos(pos);

    const SbVec2f prevnormalized = this->lastmouseposition;
    this->lastmouseposition = posn;

    // Set to true if any event processing happened. Note that it is not
    // necessary to restrict ourselves to only do one "action" for an
    // event, we only need this flag to see if any processing happened
    // at all.
    SbBool processed = false;
    bool triedSelectionDrag = false;

    const ViewerMode curmode = this->currentmode;
    ViewerMode newmode = curmode;

    // Mismatches in state of the modifier keys happens if the user
    // presses or releases them outside the viewer window.
    syncModifierKeys(ev);

    // give the nodes in the foreground root the chance to handle events (e.g color bar)
    if (!viewer->isEditing()) {
        processed = handleEventInForeground(ev);
        if (processed) {
            return true;
        }
    }

    // Keyboard handling
    if (type.isDerivedFrom(SoKeyboardEvent::getClassTypeId())) {
        const auto event = static_cast<const SoKeyboardEvent*>(ev);
        processed = processKeyboardEvent(event);
    }

    // Mouse Button / Spaceball Button handling
    if (type.isDerivedFrom(SoMouseButtonEvent::getClassTypeId())) {
        const auto event = (const SoMouseButtonEvent*)ev;
        const int button = event->getButton();
        const SbBool press = event->getState() == SoButtonEvent::DOWN ? true : false;

        switch (button) {
            case SoMouseButtonEvent::BUTTON1:
                this->button1down = press;
                updateSelectionStartPosition(press, pos);
                if (press && (curmode == NavigationStyle::SEEK_WAIT_MODE)) {
                    newmode = NavigationStyle::SEEK_MODE;
                    this->seekToPoint(pos);  // implicitly calls interactiveCountInc()
                    processed = true;
                }
                else if (viewer->isEditing() && (curmode == NavigationStyle::SPINNING)) {
                    processed = true;
                }
                else {
                    processed = processClickEvent(event);
                }
                break;
            case SoMouseButtonEvent::BUTTON2:
                // If we are in edit mode then simply ignore the RMB events
                // to pass the event to the base class.
                this->button2down = press;

                // About to turn (once the cursor leaves the dead zone), to pan with Ctrl, or
                // nothing with Shift
                if (!viewer->isEditing() && press && (curmode == NavigationStyle::IDLE)) {
                    this->centerTime = ev->getTime();
                    if (this->ctrldown || this->shiftdown) {
                        // the press position only: a pan has no turn centre to pick
                        this->localPos = pos;
                        if (this->ctrldown) {
                            setupPanningPlane(getCamera());
                        }
                    }
                    else {
                        // the press position, and the point under it as the turn's centre
                        saveCursorPosition(ev);
                    }
                    processed = true;
                }
                // Don't show the context menu after dragging, panning or zooming; the gesture
                // ends with the button even while its modifier is still held
                else if (!press && (hasDragged || hasPanned || hasZoomed)) {
                    newmode = NavigationStyle::IDLE;
                    processed = true;
                }
                else if (!press) {
                    newmode = NavigationStyle::IDLE;
                    if (!viewer->isEditing()) {
                        // a click: not a Ctrl+right (a pan), not a Shift+right (nothing), and not
                        // a flick that left the dead zone with too few motion events to spin
                        if (this->currentmode != NavigationStyle::ZOOMING
                            && this->currentmode != NavigationStyle::PANNING
                            && this->currentmode != NavigationStyle::DRAGGING
                            && !this->shiftdown) {
                            if (ForkKeymap::isOnshape()) {
                                selectPreselected();
                            }
                            if (this->isPopupMenuEnabled()) {
                                this->openPopupMenu(event->getPosition());
                            }
                        }
                        processed = true;
                    }
                }
                break;
            case SoMouseButtonEvent::BUTTON3:
                if (press && !viewer->isEditing() && isDoubleMiddleClick(ev)) {
                    // The second click of a double click fits the model; the button isn't
                    // recorded as down, so no panning starts from this press
                    this->lastMiddleClickTime = SbTime::zero();
                    viewer->viewAll();
                    processed = true;
                    break;
                }
                {
                    // the release of a double click's second press (never recorded as down) is
                    // no click of its own: a third press within the interval starts a pan, no fit
                    const bool wasDown = this->button3down;
                    this->button3down = press;
                    if (press) {
                        this->centerTime = ev->getTime();
                        setupPanningPlane(getCamera());
                    }
                    else {
                        // a click (no pan) may be the first half of a double click
                        this->lastMiddleClickTime =
                            (wasDown && !hasPanned) ? ev->getTime() : SbTime::zero();
                        if (curmode == NavigationStyle::PANNING) {
                            newmode = NavigationStyle::IDLE;
                            processed = true;
                        }
                    }
                }
                break;
            default:
                break;
        }
    }

    // Mouse Movement handling
    if (type.isDerivedFrom(SoLocation2Event::getClassTypeId())) {
        const auto event = (const SoLocation2Event*)ev;
        if (curmode == NavigationStyle::SELECTION && this->button1down) {
            triedSelectionDrag = true;
            processed = handleSelectionDragMotion(event, newmode, this->ctrldown);
        }
        else if (curmode == NavigationStyle::PANNING) {
            float ratio = vp.getViewportAspectRatio();
            panCamera(
                viewer->getSoRenderManager()->getCamera(),
                ratio,
                this->panningplane,
                posn,
                prevnormalized
            );
            processed = true;
        }
        else if (curmode == NavigationStyle::DRAGGING) {
            this->addToLog(event->getPosition(), event->getTime());
            if (this->altdown) {
                // Alt+right-drag is Onshape's constrained rotate: a horizontal drag turns about
                // the world Z axis and a vertical one about the screen's horizontal, so Z stays
                // vertical on screen. The plain drag keeps the orbit style (free by default).
                const OrbitStyle style = getOrbitStyle();
                setOrbitStyle(FreeTurntable);
                this->spin(posn);
                setOrbitStyle(style);
            }
            else {
                this->spin(posn);
            }
            moveCursorPosition();
            processed = true;
        }
    }

    // Spaceball & Joystick handling
    if (type.isDerivedFrom(SoMotion3Event::getClassTypeId())) {
        const auto event = static_cast<const SoMotion3Event*>(ev);
        if (event) {
            this->processMotionEvent(event);
        }
        processed = true;
    }

    enum
    {
        BUTTON1DOWN = 1 << 0,
        BUTTON3DOWN = 1 << 1,
        CTRLDOWN = 1 << 2,
        SHIFTDOWN = 1 << 3,
        BUTTON2DOWN = 1 << 4
    };
    unsigned int combo = (this->button1down ? BUTTON1DOWN : 0)
        | (this->button2down ? BUTTON2DOWN : 0) | (this->button3down ? BUTTON3DOWN : 0)
        | (this->ctrldown ? CTRLDOWN : 0) | (this->shiftdown ? SHIFTDOWN : 0);

    switch (combo) {
        case 0:
            if (curmode == NavigationStyle::SPINNING) {
                break;
            }
            newmode = NavigationStyle::IDLE;
            break;
        case BUTTON1DOWN:
        case CTRLDOWN | BUTTON1DOWN:
            if (newmode != NavigationStyle::INTERACT) {
                newmode = NavigationStyle::SELECTION;
            }
            break;
        case BUTTON2DOWN: {
            // A right click may jitter a few pixels and still be a click: the turn (with its
            // cursor and rotation-centre marker) starts once the cursor has left the dead zone
            // around the press position, which saveCursorPosition kept in localPos.
            // Shift+right (SHIFTDOWN | BUTTON2DOWN) is no gesture: it falls to default.
            const SbVec2f movedBy(pos - this->localPos);
            if (curmode == NavigationStyle::DRAGGING
                || movedBy.length() > float(selectionMoveThreshold())) {
                newmode = NavigationStyle::DRAGGING;
            }
            break;
        }
        case CTRLDOWN | BUTTON2DOWN:
        case BUTTON3DOWN:
            newmode = NavigationStyle::PANNING;
            break;
        default:
            break;
    }

    // Process when selection button is pressed together with other buttons that could trigger
    // different actions.
    if (this->button1down && (this->button2down || this->button3down)) {
        processed = true;
    }

    // Prevent interrupting rubber-band selection in sketcher
    if (viewer->isEditing() && curmode == NavigationStyle::SELECTION
        && newmode != NavigationStyle::IDLE) {
        newmode = NavigationStyle::SELECTION;
        processed = false;
    }

    // Reset flags when newmode is IDLE and the buttons are released
    if (newmode == IDLE && !button1down && !button2down && !button3down) {
        hasPanned = false;
        hasDragged = false;
        hasZoomed = false;
    }

    if (newmode != curmode) {
        this->setViewingMode(newmode);
    }

    // If not handled in this class, pass on upwards in the inheritance
    // hierarchy.
    if (!processed && !triedSelectionDrag) {
        processed = inherited::processSoEvent(ev);
    }
    return processed;
}
