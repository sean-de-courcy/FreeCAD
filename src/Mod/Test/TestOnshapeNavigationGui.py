# SPDX-License-Identifier: LGPL-2.1-or-later

"""Onshape's mouse in the 3D view (FreeCAD-CH, ops#640): Gui::OnshapeNavigationStyle.

Right-drag turns the model about the point under the cursor, middle-drag and Ctrl+right-drag pan
it, the wheel zooms at the cursor, a double middle click fits the model, Shift+right does nothing,
and a right click without a drag (a jitter of a few pixels allowed) selects the entity under the
cursor and opens the context menu. Each test builds a designed model (a 10 mm Part::Box in a fresh
document, the view fitted) and drives the view's GL widget with synthetic Qt mouse events.
Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md).

To run:
    FreeCAD -t TestOnshapeNavigationGui
"""

import math
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtGui, QtWidgets
from PySide6 import QtTest
from pivy import coin  # also registers Coin's SWIG types before getCameraNode() returns one

ONSHAPE = "Gui::OnshapeNavigationStyle"
VIEW = "User parameter:BaseApp/Preferences/View"
KEYMAP = "User parameter:BaseApp/Preferences/General"  # the preference Keymap (ForkKeymap)

LEFT = QtCore.Qt.MouseButton.LeftButton
RIGHT = QtCore.Qt.MouseButton.RightButton
MIDDLE = QtCore.Qt.MouseButton.MiddleButton
NO_BUTTON = QtCore.Qt.MouseButton.NoButton
NO_MODIFIER = QtCore.Qt.KeyboardModifier.NoModifier
CONTROL = QtCore.Qt.KeyboardModifier.ControlModifier
SHIFT = QtCore.Qt.KeyboardModifier.ShiftModifier
MOVE = QtCore.QEvent.Type.MouseMove
PRESS = QtCore.QEvent.Type.MouseButtonPress
RELEASE = QtCore.QEvent.Type.MouseButtonRelease


def pump(ms=50):
    Gui.updateGui()
    QtTest.QTest.qWait(ms)


def sameRotation(a, b, tolerance=1e-6):
    """True when the rotations a and b (Base.Rotation) are the same, q and -q included."""
    dot = sum(x * y for x, y in zip(a.Q, b.Q))
    return abs(abs(dot) - 1.0) < tolerance


def distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def savedString(path, name):
    """The stored string, None where there is none (to put back as it was)."""
    group = App.ParamGet(path)
    return group.GetString(name) if name in group.GetStrings() else None


def restoreString(path, name, value):
    group = App.ParamGet(path)
    if value is None:
        group.RemString(name)
    else:
        group.SetString(name, value)


class TestOnshapeNavigationGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestOnshapeNavigation")
        self.box = self.doc.addObject("Part::Box", "Box")
        self.box.Length = 10
        self.box.Width = 10
        self.box.Height = 10
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        pump()
        self.view = Gui.ActiveDocument.ActiveView
        self.viewer = self.view.getViewer()
        self.oldStyle = self.view.getNavigationType()
        self.view.setNavigationType(ONSHAPE)
        self.viewer.setEnabledNaviCube(False)
        self.view.setAxisCross(False)
        self.view.setAnimationEnabled(False)
        self.view.viewIsometric()
        Gui.SendMsgToActiveView("ViewFit")
        pump(100)
        self.viewport = self.glWidget()
        self.viewport.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        pump()
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()

    def tearDown(self):
        self.closePopup()
        Gui.Selection.clearSelection()
        try:
            self.view.setNavigationType(self.oldStyle)
        except RuntimeError:
            pass
        App.closeDocument(self.doc.Name)
        pump()

    # helpers

    def glWidget(self, timeout=5.0):
        """The view's GL widget (the Quarter widget's viewport), once it is wrapped; a skip
        where it never is (nav-11, as TestRubberbandSelection)."""
        end = time.monotonic() + timeout
        while True:
            try:
                viewport = self.view.graphicsView().viewport()
                viewport.rect()
                return viewport
            except RuntimeError:
                if time.monotonic() >= end:
                    App.closeDocument(self.doc.Name)
                    raise unittest.SkipTest(
                        "3D view widget wrapping is unavailable in this test environment"
                    )
                pump(20)

    def center(self):
        return self.viewport.rect().center()

    def mouse(self, kind, pos, button, buttons, modifiers=NO_MODIFIER):
        event = QtGui.QMouseEvent(
            kind,
            QtCore.QPointF(pos),
            QtCore.QPointF(self.viewport.mapToGlobal(pos)),
            button,
            buttons,
            modifiers,
        )
        QtWidgets.QApplication.sendEvent(self.viewport, event)

    def drag(self, button, start, end, modifiers=NO_MODIFIER, steps=4):
        """Presses button at start, moves to end in steps, releases."""
        self.mouse(MOVE, start, NO_BUTTON, NO_BUTTON, modifiers)
        pump(20)
        self.mouse(PRESS, start, button, button, modifiers)
        pump(20)
        for i in range(1, steps + 1):
            pos = QtCore.QPoint(
                start.x() + (end.x() - start.x()) * i // steps,
                start.y() + (end.y() - start.y()) * i // steps,
            )
            self.mouse(MOVE, pos, NO_BUTTON, button, modifiers)
            pump(20)
        self.mouse(RELEASE, end, button, NO_BUTTON, modifiers)
        pump(100)

    def click(self, button, pos, modifiers=NO_MODIFIER):
        self.mouse(PRESS, pos, button, button, modifiers)
        pump(10)
        self.mouse(RELEASE, pos, button, NO_BUTTON, modifiers)

    def jitterClick(self, button, pos, offsets):
        """A click whose cursor moves through pos + offset for each offset between the press
        and the release (the release at the last one)."""
        self.mouse(PRESS, pos, button, button)
        pump(10)
        last = pos
        for dx, dy in offsets:
            last = pos + QtCore.QPoint(dx, dy)
            self.mouse(MOVE, last, NO_BUTTON, button)
            pump(10)
        self.mouse(RELEASE, last, button, NO_BUTTON)

    def wheel(self, pos, delta=120):
        """A wheel notch at pos (a viewport point), delivered to the Quarter widget as a real
        wheel is. A real wheel over the viewport is spontaneous: Qt propagates it from the
        viewport up to the QuarterWidget, whose event filter turns it into the SoMouseWheelEvent
        the navigation style zooms on (Quarter/EventFilter.cpp, Quarter/Mouse.cpp). A synthetic
        wheel from sendEvent is not spontaneous, and QApplication::notify delivers those to
        their receiver only: sent to the viewport it is dropped there, unseen by the style
        (verified off screen under the Onshape and CAD styles, round 2). Mouse events
        propagate either way, so mouse() keeps the viewport as its target."""
        quarter = self.view.graphicsView()
        quarterPos = self.viewport.mapTo(quarter, pos)
        event = QtGui.QWheelEvent(
            QtCore.QPointF(quarterPos),
            QtCore.QPointF(quarter.mapToGlobal(quarterPos)),
            QtCore.QPoint(),
            QtCore.QPoint(0, delta),
            NO_BUTTON,
            NO_MODIFIER,
            QtCore.Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QtWidgets.QApplication.sendEvent(quarter, event)
        pump(100)

    def orientation(self):
        return self.view.getCameraOrientation()

    def position(self):
        return tuple(self.view.getCameraNode().position.getValue().getValue())

    def zoomMeasure(self):
        """What a zoom changes: the orthographic camera's height, else the distance from the
        perspective camera to the box's centre."""
        camera = self.view.getCameraNode()
        if self.view.getCameraType() == "Orthographic":
            return camera.height.getValue()
        return distance(self.position(), (5.0, 5.0, 5.0))

    def toQPoint(self, viewportPixel):
        """A Coin viewport pixel (device pixels, origin bottom left) as the widget's QPoint."""
        _, height = self.view.getSize()
        scale = self.viewport.devicePixelRatioF()
        x = int(round(viewportPixel[0] / scale))
        y = int(round((height - viewportPixel[1] - 1) / scale))
        return QtCore.QPoint(x, y)

    def projectToViewport(self, point):
        """The viewport pixel (device pixels, floats, origin bottom left) a 3D point renders at.
        The camera's view volume as rendered: Coin's ADJUST_CAMERA mapping scales the volume by
        1/aspect when the viewport is taller than wide (SoCamera::getViewVolume with a viewport
        region), as panCamera does (NavigationStyle.cpp). View.getPointOnViewport leaves that
        scaling out, so in a portrait viewport (the off-screen window is one) it misplaces
        off-centre points by (1 - aspect) of their offset from the centre."""
        width, height = self.view.getSize()
        aspect = width / height
        volume = self.view.getCameraNode().getViewVolume(aspect)
        if aspect < 1.0:
            volume.scale(1.0 / aspect)
        screen = volume.projectToScreen(coin.SbVec3f(point.x, point.y, point.z))
        return (screen[0] * width, screen[1] * height)

    def focalPlanePoint(self, right, up):
        """The point of the camera's focal plane right mm to the right and up mm up from the
        focal point: zoom-at-cursor keeps a focal-plane point under the cursor exactly."""
        camera = self.view.getCameraNode()
        rotation = self.orientation()
        position = App.Vector(*self.position())
        focal = position + rotation.multVec(App.Vector(0, 0, -1)) * camera.focalDistance.getValue()
        return (
            focal
            + rotation.multVec(App.Vector(1, 0, 0)) * right
            + rotation.multVec(App.Vector(0, 1, 0)) * up
        )

    def closePopup(self):
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is not None:
            popup.close()
            pump()
        return popup

    def platformOpensPopups(self):
        """Whether a popup menu opens at all here (a plain QMenu as the probe)."""
        probe = QtWidgets.QMenu(Gui.getMainWindow())
        probe.addAction("probe")
        probe.popup(QtCore.QPoint(0, 0))
        QtTest.QTest.qWait(100)
        opened = QtWidgets.QApplication.activePopupWidget() is probe
        probe.close()
        probe.deleteLater()
        pump()
        return opened

    def popupMenu(self):
        """The context menu that is open after a right click; a skip where this platform opens
        no popups at all (nav-11, as TestContextMenuGui)."""
        QtTest.QTest.qWait(300)
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is None and not self.platformOpensPopups():
            self.skipTest("no popup menu opens on this platform")
        self.assertIsInstance(popup, QtWidgets.QMenu, "the right click opened no context menu")
        return popup

    def assertNoPopup(self, message):
        QtTest.QTest.qWait(300)
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is not None:
            popup.close()
            pump()
        self.assertIsNone(popup, message)

    def selectedNames(self):
        return [o.Name for o in Gui.Selection.getSelection()]

    # tests: the style

    def testStyleIsSet(self):
        """The view runs Gui::OnshapeNavigationStyle, which the type system lists."""
        self.assertEqual(self.view.getNavigationType(), ONSHAPE)

    # tests: turning and panning

    def testRightDragTurns(self):
        """A right-drag of 80 px changes the camera's orientation."""
        before = self.orientation()
        start = self.center()
        self.drag(RIGHT, start, start + QtCore.QPoint(80, 0))
        self.assertFalse(sameRotation(before, self.orientation()), "a right-drag didn't turn")

    def testRightDragOpensNoMenuAndSelectsNothing(self):
        """nav-8: a right-drag of 80 px opens no context menu and selects nothing, with an
        entity preselected under the press."""
        Gui.Selection.setPreselection(self.box, "Face1")
        start = self.center()
        self.drag(RIGHT, start, start + QtCore.QPoint(80, 0))
        self.assertNoPopup("a right-drag opened the context menu")
        self.assertEqual(self.selectedNames(), [], "a right-drag selected")

    def testMiddleDragPans(self):
        """A middle-drag moves the camera and keeps its orientation."""
        orientation = self.orientation()
        position = self.position()
        start = self.center()
        self.drag(MIDDLE, start, start + QtCore.QPoint(80, 0))
        self.assertGreater(distance(position, self.position()), 1e-6, "a middle-drag didn't pan")
        self.assertTrue(sameRotation(orientation, self.orientation()), "a middle-drag turned")

    def testCtrlRightDragPans(self):
        """A Ctrl+right-drag moves the camera and keeps its orientation."""
        orientation = self.orientation()
        position = self.position()
        start = self.center()
        self.drag(RIGHT, start, start + QtCore.QPoint(80, 0), CONTROL)
        self.assertGreater(
            distance(position, self.position()), 1e-6, "a Ctrl+right-drag didn't pan"
        )
        self.assertTrue(sameRotation(orientation, self.orientation()), "a Ctrl+right-drag turned")

    def testReleaseWithCtrlHeldStopsPanning(self):
        """nav-1: after a Ctrl+right-drag released with Ctrl still held, mouse moves with no
        button down pan no more."""
        start = self.center()
        self.drag(RIGHT, start, start + QtCore.QPoint(80, 0), CONTROL)
        position = self.position()
        for dx, dy in ((40, 10), (80, 40), (120, 90)):
            self.mouse(MOVE, start + QtCore.QPoint(dx, dy), NO_BUTTON, NO_BUTTON, CONTROL)
            pump(20)
        self.assertEqual(
            position, self.position(), "the view kept panning after the right button's release"
        )

    def testShiftRightDragDoesNothing(self):
        """nav-7: a Shift+right-drag neither turns nor pans, opens no menu and selects
        nothing."""
        Gui.Selection.setPreselection(self.box, "Face1")
        orientation = self.orientation()
        position = self.position()
        start = self.center()
        self.drag(RIGHT, start, start + QtCore.QPoint(80, 0), SHIFT)
        self.assertNoPopup("a Shift+right-drag opened the context menu")
        self.assertTrue(sameRotation(orientation, self.orientation()), "a Shift+right-drag turned")
        self.assertEqual(position, self.position(), "a Shift+right-drag panned")
        self.assertEqual(self.selectedNames(), [], "a Shift+right-drag selected")

    # tests: the right click

    def testRightClickSelectsAndOpensTheMenu(self):
        """A right click without a drag selects the preselected entity (Box, Face1) and opens
        the context menu; the camera doesn't move."""
        Gui.Selection.setPreselection(self.box, "Face1")
        self.assertEqual(Gui.Selection.getPreselection().ObjectName, "Box")
        orientation = self.orientation()
        position = self.position()
        self.click(RIGHT, self.center())
        self.popupMenu()
        self.closePopup()
        self.assertEqual(self.selectedNames(), ["Box"])
        self.assertEqual(Gui.Selection.getSelectionEx()[0].SubElementNames, ("Face1",))
        self.assertTrue(sameRotation(orientation, self.orientation()), "a right click turned")
        self.assertEqual(position, self.position(), "a right click panned")

    def testRightClickWithJitterOpensTheMenu(self):
        """nav-2 (ctx-10): a right click whose cursor moves through three positions within
        3 px of the press is a click: the view doesn't turn, the entity under the cursor is
        selected (one sub-element of the Box) and the context menu opens."""
        self.assertLess(4, QtWidgets.QApplication.startDragDistance())
        Gui.Selection.setPreselection(self.box, "Face1")
        orientation = self.orientation()
        self.jitterClick(RIGHT, self.center(), ((2, 0), (3, 1), (1, 2)))
        self.popupMenu()
        self.closePopup()
        self.assertTrue(sameRotation(orientation, self.orientation()), "a jittered click turned")
        self.assertEqual(self.selectedNames(), ["Box"], "a jittered right click didn't select")
        self.assertEqual(len(Gui.Selection.getSelectionEx()[0].SubElementNames), 1)

    def testRightClickKeepsASelection(self):
        """A right click on the selected entity keeps the selection as it is."""
        Gui.Selection.addSelection(self.doc.Name, "Box", "Face1")
        Gui.Selection.setPreselection(self.box, "Face1")
        self.click(RIGHT, self.center())
        self.popupMenu()
        self.closePopup()
        self.assertEqual(Gui.Selection.getSelectionEx()[0].SubElementNames, ("Face1",))

    def testRightClickOnEmptySpaceOpensAMenuAndKeepsTheSelection(self):
        """nav-8: a right click over empty space (no preselection) opens a context menu and
        leaves the selection alone (which menu it is: TestContextMenuGui, ctx-1)."""
        Gui.Selection.addSelection(self.doc.Name, "Box")
        Gui.Selection.clearPreselection()
        self.click(RIGHT, QtCore.QPoint(5, 5))
        self.popupMenu()
        self.closePopup()
        self.assertEqual(self.selectedNames(), ["Box"])

    def testRightClickWithoutTheForkKeymapDoesNotSelect(self):
        """Decision 1: with General/Keymap = FreeCAD a right click opens the context menu as
        before but selects nothing."""
        saved = savedString(KEYMAP, "Keymap")
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        pump(100)
        try:
            Gui.Selection.setPreselection(self.box, "Face1")
            self.click(RIGHT, self.center())
            self.popupMenu()
            self.closePopup()
            self.assertEqual(
                self.selectedNames(), [], "a right click selected under the FreeCAD keymap"
            )
        finally:
            restoreString(KEYMAP, "Keymap", saved)
            pump(100)

    def testCtrlRightClickOpensNoMenu(self):
        """nav-8: a Ctrl+right click without motion (a pan of nothing) opens no menu and
        selects nothing."""
        Gui.Selection.setPreselection(self.box, "Face1")
        self.click(RIGHT, self.center(), CONTROL)
        self.assertNoPopup("a Ctrl+right click opened the context menu")
        self.assertEqual(self.selectedNames(), [], "a Ctrl+right click selected")

    def testShiftRightClickDoesNothing(self):
        """nav-7: a Shift+right click without motion opens no menu and selects nothing."""
        Gui.Selection.setPreselection(self.box, "Face1")
        orientation = self.orientation()
        self.click(RIGHT, self.center(), SHIFT)
        self.assertNoPopup("a Shift+right click opened the context menu")
        self.assertEqual(self.selectedNames(), [], "a Shift+right click selected")
        self.assertTrue(sameRotation(orientation, self.orientation()), "a Shift+right click turned")

    # tests: the middle button

    def testDoubleMiddleClickFits(self):
        """A double middle click after zooming in restores the fitted view."""
        fitted = self.zoomMeasure()
        for _ in range(3):
            Gui.SendMsgToActiveView("ZoomIn")
        pump()
        self.assertGreater(abs(self.zoomMeasure() - fitted), 0.01 * fitted, "ZoomIn didn't zoom")
        gap = 30
        self.assertLess(gap, QtWidgets.QApplication.doubleClickInterval())
        self.click(MIDDLE, self.center())
        QtTest.QTest.qWait(gap)
        self.click(MIDDLE, self.center())
        pump(300)
        self.assertLess(
            abs(self.zoomMeasure() - fitted),
            0.01 * fitted,
            "a double middle click didn't fit the model",
        )

    def testSingleMiddleClickDoesNotFit(self):
        """A middle click on its own leaves the zoom alone."""
        for _ in range(3):
            Gui.SendMsgToActiveView("ZoomIn")
        pump()
        zoomed = self.zoomMeasure()
        self.click(MIDDLE, self.center())
        pump(300)
        self.assertAlmostEqual(self.zoomMeasure(), zoomed, places=6)

    def testDoubleMiddleClickAfterPanDoesNotFit(self):
        """nav-8: a middle click right after a middle-drag (a pan) is no double click: the
        zoom stays."""
        for _ in range(3):
            Gui.SendMsgToActiveView("ZoomIn")
        pump()
        start = self.center()
        self.drag(MIDDLE, start, start + QtCore.QPoint(60, 0))
        zoomed = self.zoomMeasure()
        self.click(MIDDLE, start)
        pump(300)
        self.assertAlmostEqual(
            self.zoomMeasure(), zoomed, places=6, msg="a click after a pan fitted the model"
        )

    def testMiddleDragAfterADoubleClickPans(self):
        """nav-3: a middle press within the double-click interval after a double click's
        second click is a new first click, so the drag it starts pans (and doesn't fit
        again)."""
        interval = QtWidgets.QApplication.doubleClickInterval()
        QtWidgets.QApplication.setDoubleClickInterval(2000)
        try:
            for _ in range(3):
                Gui.SendMsgToActiveView("ZoomIn")
            pump()
            self.click(MIDDLE, self.center())
            QtTest.QTest.qWait(30)
            self.click(MIDDLE, self.center())
            pump(100)
            position = self.position()
            start = self.center()
            self.drag(MIDDLE, start, start + QtCore.QPoint(80, 0))
            self.assertGreater(
                distance(position, self.position()),
                1e-6,
                "a middle-drag right after a double click didn't pan",
            )
        finally:
            QtWidgets.QApplication.setDoubleClickInterval(interval)

    # tests: the wheel

    def testWheelZooms(self):
        """One wheel notch zooms by the View/ZoomStep factor (exp(step) on the orthographic
        camera's height; in the direction View/InvertZoom chooses, both at their defaults in
        the test's fresh user home)."""
        view = App.ParamGet(VIEW)
        step = view.GetFloat("ZoomStep", 0.2)
        if view.GetBool("InvertZoom", True):
            step = -step
        before = self.zoomMeasure()
        self.wheel(self.center())
        after = self.zoomMeasure()
        self.assertGreater(abs(after - before), 1e-6, "the wheel didn't zoom")
        if self.view.getCameraType() == "Orthographic":
            self.assertAlmostEqual(
                after / before, math.exp(step), places=4, msg="the wheel zoomed by another factor"
            )

    def testWheelZoomsAtCursor(self):
        """nav-8: the wheel at an off-centre point keeps that point under the cursor (the
        focal-plane point 3 mm right and 2 mm up of the focal point, projected before and
        after; 2 px covers the rounding of the wheel's pixel)."""
        point = self.focalPlanePoint(3.0, 2.0)
        before = self.projectToViewport(point)
        pos = self.toQPoint(before)
        self.assertGreater(
            distance((pos.x(), pos.y()), (self.center().x(), self.center().y())),
            10,
            "the probe point is too close to the centre to tell zoom-at-cursor apart",
        )
        measure = self.zoomMeasure()
        self.wheel(pos)
        self.assertGreater(abs(self.zoomMeasure() - measure), 1e-6, "the wheel didn't zoom")
        after = self.projectToViewport(point)
        self.assertLessEqual(
            distance(before, after), 2.0, "the point under the cursor moved while zooming"
        )

    # tests: the status-bar indicator (Tux)

    def testTuxIndicatorHasOnshapeAndLeavesAnUnsetStyleAlone(self):
        """nav-5, nav-6: the status-bar navigation indicator has an entry for the Onshape
        style; with View/NavigationStyle unset it shows that entry and does not write the
        parameter (the C++ default applies)."""
        try:
            import NavigationIndicatorGui as indicator
        except ImportError:
            self.skipTest("Tux's navigation indicator is not available")
        onshape = [a for a in indicator.gStyle.actions() if a.data() == ONSHAPE]
        self.assertEqual(len(onshape), 1, "the indicator has no Onshape entry")
        self.assertIn(onshape[0], indicator.menu.actions(), "the Onshape entry isn't in the menu")
        self.assertFalse(onshape[0].icon().isNull(), "the Onshape entry has no icon")
        view = App.ParamGet(VIEW)
        saved = savedString(VIEW, "NavigationStyle")
        try:
            view.RemString("NavigationStyle")
            indicator.setCurrent()
            self.assertNotIn(
                "NavigationStyle",
                view.GetStrings(),
                "the indicator wrote a navigation style for an unset parameter",
            )
            self.assertTrue(onshape[0].isChecked(), "an unset style doesn't show as Onshape")
            self.assertFalse(indicator.a0.isVisible(), "an unset style shows as Undefined")
        finally:
            restoreString(VIEW, "NavigationStyle", saved)
            pump()
