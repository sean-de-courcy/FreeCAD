# SPDX-License-Identifier: LGPL-2.1-or-later

"""Onshape's mouse in the 3D view (FreeCAD-CH, ops#640): Gui::OnshapeNavigationStyle.

Right-drag turns the model, middle-drag and Ctrl+right-drag pan it, the wheel zooms, a double
middle click fits the model, and a right click without a drag selects the entity under the cursor
and opens the context menu. Each test builds a designed model (a 10 mm Part::Box in a fresh
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

ONSHAPE = "Gui::OnshapeNavigationStyle"

LEFT = QtCore.Qt.MouseButton.LeftButton
RIGHT = QtCore.Qt.MouseButton.RightButton
MIDDLE = QtCore.Qt.MouseButton.MiddleButton
NO_BUTTON = QtCore.Qt.MouseButton.NoButton
NO_MODIFIER = QtCore.Qt.KeyboardModifier.NoModifier
CONTROL = QtCore.Qt.KeyboardModifier.ControlModifier
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
        """The view's GL widget (the Quarter widget's viewport), once it is wrapped."""
        end = time.monotonic() + timeout
        while True:
            try:
                viewport = self.view.graphicsView().viewport()
                viewport.rect()
                return viewport
            except RuntimeError:
                if time.monotonic() >= end:
                    raise
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

    def wheel(self, pos, delta=120):
        event = QtGui.QWheelEvent(
            QtCore.QPointF(pos),
            QtCore.QPointF(self.viewport.mapToGlobal(pos)),
            QtCore.QPoint(),
            QtCore.QPoint(0, delta),
            NO_BUTTON,
            NO_MODIFIER,
            QtCore.Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QtWidgets.QApplication.sendEvent(self.viewport, event)
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

    def closePopup(self):
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is not None:
            popup.close()
            pump()
        return popup

    # tests

    def testStyleIsSet(self):
        """The view runs Gui::OnshapeNavigationStyle, which the type system lists."""
        self.assertEqual(self.view.getNavigationType(), ONSHAPE)

    def testRightDragTurns(self):
        """A right-drag of 80 px changes the camera's orientation."""
        before = self.orientation()
        start = self.center()
        self.drag(RIGHT, start, start + QtCore.QPoint(80, 0))
        self.assertFalse(sameRotation(before, self.orientation()), "a right-drag didn't turn")

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

    def testRightClickSelectsAndOpensTheMenu(self):
        """A right click without a drag selects the preselected entity (Box, Face1) and opens
        the context menu; the camera doesn't move."""
        Gui.Selection.setPreselection(self.box, "Face1")
        self.assertEqual(Gui.Selection.getPreselection().ObjectName, "Box")
        orientation = self.orientation()
        position = self.position()
        self.click(RIGHT, self.center())
        QtTest.QTest.qWait(300)
        popup = QtWidgets.QApplication.activePopupWidget()
        self.assertIsInstance(popup, QtWidgets.QMenu, "a right click opened no context menu")
        self.closePopup()
        self.assertEqual([o.Name for o in Gui.Selection.getSelection()], ["Box"])
        self.assertEqual(Gui.Selection.getSelectionEx()[0].SubElementNames, ("Face1",))
        self.assertTrue(sameRotation(orientation, self.orientation()), "a right click turned")
        self.assertEqual(position, self.position(), "a right click panned")

    def testRightClickKeepsASelection(self):
        """A right click on the selected entity keeps the selection as it is."""
        Gui.Selection.addSelection(self.doc.Name, "Box", "Face1")
        Gui.Selection.setPreselection(self.box, "Face1")
        self.click(RIGHT, self.center())
        QtTest.QTest.qWait(300)
        self.closePopup()
        self.assertEqual(Gui.Selection.getSelectionEx()[0].SubElementNames, ("Face1",))

    def testRightClickWithoutPreselectionKeepsTheSelection(self):
        """A right click over empty space leaves the selection alone."""
        Gui.Selection.addSelection(self.doc.Name, "Box")
        Gui.Selection.clearPreselection()
        self.click(RIGHT, QtCore.QPoint(5, 5))
        QtTest.QTest.qWait(300)
        self.closePopup()
        self.assertEqual([o.Name for o in Gui.Selection.getSelection()], ["Box"])

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

    def testWheelZooms(self):
        """The wheel changes the zoom."""
        before = self.zoomMeasure()
        self.wheel(self.center())
        self.assertGreater(abs(self.zoomMeasure() - before), 1e-6, "the wheel didn't zoom")
