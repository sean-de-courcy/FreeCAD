# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Onshape's right-click menu of the 3D view (FreeCAD-CH, ops#640).

What the menu lists depends on what the right-click selected: on a face, Sketch on face, Fillet
and Chamfer come first; on an edge, Fillet and Chamfer; on a vertex or a whole object, neither.
Then the view entries (normal to, zoom to selection), the visibility entries (hide, hide other
parts, make transparent, edit appearance), select other and delete, and a More submenu holding
the rest of FreeCAD's menu (PartDesign's Set Tip and roll-back entries, the link actions, the
Standard Views submenu, the draw style...). On empty space: zoom to fit, isometric, the Standard
Views submenu, show all parts, and More. The commands keep their own menu texts (the ledger notes
where they differ from Onshape's words).

Designed model: a Body with a Pad of a 10 x 10 square. The selection is set by API (the
navigation style's right-click selects what is under the cursor; it is not under test here) and
the menu is opened by a synthetic right-click on the 3D view with the TinkerCAD navigation style,
whose plain right-click opens the menu. Off screen (QT_QPA_PLATFORM=offscreen) a popup opens as
on screen; where the platform opens none at all the tests skip."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Sketcher

from PySide import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

NAVIGATION_STYLE = "Gui::TinkerCADNavigationStyle"


def pump(seconds=0.1):
    end = time.monotonic() + seconds
    while True:
        QtWidgets.QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def menuText(name):
    """The menu text of a command, as a user reads it (no accelerator mark)."""
    command = Gui.Command.get(name)
    if command is None:
        return None
    return command.getInfo()["menuText"].replace("&", "")


def texts(actions):
    """The texts of a menu's actions in order, separators left out."""
    return [a.text().replace("&", "") for a in actions if not a.isSeparator()]


def submenu(actions, title):
    """The submenu (a QMenu) of the action titled so, or None."""
    for action in actions:
        if action.text().replace("&", "") == title and action.menu() is not None:
            return action.menu()
    return None


# The commands behind Onshape's entries, in Onshape's order
ON_SELECTION = [
    "Std_ViewNormal",  # View normal to
    "Std_ViewFitSelection",  # Zoom to selection
    "Std_HideSelection",  # Hide
    "Std_Isolate",  # Hide other parts
    "Std_ToggleTransparency",  # Make transparent
    "Std_SetAppearance",  # Edit appearance
    "Std_SelectOther",  # Select other
    "Std_Delete",  # Delete part
]

ON_EMPTY_SPACE = [
    "Std_ViewFitAll",  # Zoom to fit
    "Std_ViewIsometric",  # Isometric
]

# FreeCAD's entries that move under More when something is selected
MORE_ON_SELECTION = [
    "Std_ViewFitAll",
    "Std_DrawStyle",
    "Std_ViewDockUndockFullscreen",
    "Std_ToggleVisibility",
    "Std_ToggleSelectability",
    "Std_TreeSelection",
    "Std_RandomColor",
    "Std_SendToPythonConsole",
]

MORE_ON_EMPTY_SPACE = ["Std_DrawStyle", "Std_ViewDockUndockFullscreen"]

STANDARD_VIEWS = "Standard Views"
LINK_ACTIONS = "Link Actions"
MORE = "More"


class TestContextMenuGui(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        Gui.getMainWindow().show()
        Gui.activateWorkbench("PartDesignWorkbench")
        pump()

    def setUp(self):
        self.doc = App.newDocument("ContextMenuGui")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.sketch = self.body.newObject("Sketcher::SketchObject", "Sketch")
        self.sketch.AttachmentSupport = (self.body.Origin.OriginFeatures[3], [""])  # XY_Plane
        self.sketch.MapMode = "FlatFace"
        corners = [(0, 0), (10, 0), (10, 10), (0, 10)]
        for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
            self.sketch.addGeometry(
                Part.LineSegment(App.Vector(ax, ay, 0), App.Vector(bx, by, 0)), False
            )
        for i in range(4):
            self.sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.sketch
        self.pad.Length = 5
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        self.view = Gui.ActiveDocument.ActiveView
        self.view.setNavigationType(NAVIGATION_STYLE)
        self.view.fitAll()
        Gui.Selection.clearSelection()
        pump(0.2)

    def tearDown(self):
        self.closePopup()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        pump()

    # --- helpers

    def closePopup(self):
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is not None:
            popup.close()
            pump(0.1)

    def platformOpensPopups(self):
        """Whether a popup menu opens at all here (a plain QMenu as the probe)."""
        probe = QtWidgets.QMenu(Gui.getMainWindow())
        probe.addAction("probe")
        probe.popup(QtCore.QPoint(0, 0))
        QTest.qWait(100)
        opened = QtWidgets.QApplication.activePopupWidget() is probe
        probe.close()
        probe.deleteLater()
        pump(0.1)
        return opened

    def rightClick(self, widget, pos):
        for kind, buttons in (
            (QtCore.QEvent.MouseButtonPress, QtCore.Qt.RightButton),
            (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.NoButton),
        ):
            event = QtGui.QMouseEvent(
                kind,
                QtCore.QPointF(pos),
                QtCore.QPointF(widget.mapToGlobal(pos)),
                QtCore.Qt.RightButton,
                buttons,
                QtCore.Qt.NoModifier,
            )
            QtWidgets.QApplication.sendEvent(widget, event)

    def openMenu(self):
        """Right-clicks the middle of the 3D view; returns the context menu's actions."""
        self.closePopup()
        viewport = self.view.graphicsView().viewport()
        self.rightClick(viewport, viewport.rect().center())
        QTest.qWait(300)
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is None:
            if not self.platformOpensPopups():
                self.skipTest("no popup menu opens on this platform")
            self.fail("the right-click opened no context menu")
        self.assertIsInstance(popup, QtWidgets.QMenu)
        return popup.actions()

    def select(self, *subs):
        Gui.Selection.clearSelection()
        for sub in subs:
            Gui.Selection.addSelection(self.doc.Name, self.pad.Name, sub)
        pump(0.1)

    def assertMenu(self, actions, expectedCommands, firstCommands=()):
        """The menu's entries end with the expected commands' texts and More; what precedes
        them is at most Clarify Selection (added when the view picks something under the
        cursor)."""
        expected = [menuText(c) for c in firstCommands + tuple(expectedCommands)] + [MORE]
        self.assertNotIn(None, expected, "a command is missing")
        found = texts(actions)
        self.assertEqual(found[-len(expected) :], expected, found)
        allowed = {menuText("Std_ClarifySelection"), "Clarify Selection"}
        self.assertTrue(set(found[: -len(expected)]) <= allowed, found)
        return submenu(actions, MORE)

    def assertMore(self, more, expectedCommands, withStandardViews):
        self.assertIsNotNone(more, "More is a submenu")
        found = texts(more.actions())
        for name in expectedCommands:
            self.assertIn(menuText(name), found, found)
        self.assertIn(LINK_ACTIONS, found, found)
        self.assertIsNotNone(submenu(more.actions(), LINK_ACTIONS))
        if withStandardViews:
            self.assertIn(STANDARD_VIEWS, found, found)
            self.assertIsNotNone(submenu(more.actions(), STANDARD_VIEWS))
        else:
            self.assertNotIn(STANDARD_VIEWS, found, found)
        # keeps FreeCAD's relative order
        positions = [found.index(menuText(name)) for name in expectedCommands]
        self.assertEqual(positions, sorted(positions), found)

    # --- tests

    def testOnAFace(self):
        self.select("Face6")
        actions = self.openMenu()
        more = self.assertMenu(
            actions,
            ON_SELECTION,
            ("PartDesign_NewSketch", "PartDesign_Fillet", "PartDesign_Chamfer"),
        )
        self.assertMore(more, MORE_ON_SELECTION, withStandardViews=True)
        # the body's own entries go under More too: the Pad is a feature of its body
        found = texts(more.actions())
        self.assertIn(menuText("PartDesign_MoveTip"), found, found)
        self.assertIn(menuText("PartDesign_RollTo"), found, found)
        # and before FreeCAD's
        self.assertLess(found.index(menuText("PartDesign_RollTo")), found.index(LINK_ACTIONS))
        # the first entries are not in the menu twice
        self.assertNotIn(menuText("PartDesign_NewSketch"), found)

    def testOnAnEdge(self):
        self.select("Edge1")
        actions = self.openMenu()
        more = self.assertMenu(
            actions, ON_SELECTION, ("PartDesign_Fillet", "PartDesign_Chamfer")
        )
        self.assertMore(more, MORE_ON_SELECTION, withStandardViews=True)
        self.assertNotIn(menuText("PartDesign_NewSketch"), texts(actions))

    def testOnAVertex(self):
        self.select("Vertex1")
        actions = self.openMenu()
        more = self.assertMenu(actions, ON_SELECTION)
        self.assertMore(more, MORE_ON_SELECTION, withStandardViews=True)
        for name in ("PartDesign_NewSketch", "PartDesign_Fillet", "PartDesign_Chamfer"):
            self.assertNotIn(menuText(name), texts(actions))

    def testOnAWholeObject(self):
        self.select("")
        actions = self.openMenu()
        more = self.assertMenu(actions, ON_SELECTION)
        self.assertMore(more, MORE_ON_SELECTION, withStandardViews=True)
        for name in ("PartDesign_NewSketch", "PartDesign_Fillet", "PartDesign_Chamfer"):
            self.assertNotIn(menuText(name), texts(actions))

    def testOnTwoEdges(self):
        """Fillet and Chamfer take several edges (or faces) of one object."""
        self.select("Edge1", "Edge2")
        actions = self.openMenu()
        self.assertMenu(actions, ON_SELECTION, ("PartDesign_Fillet", "PartDesign_Chamfer"))
        self.assertNotIn(menuText("PartDesign_NewSketch"), texts(actions))

    def testOnTwoFaces(self):
        """Sketch on face wants one face; Fillet and Chamfer take several."""
        self.select("Face5", "Face6")
        actions = self.openMenu()
        self.assertMenu(actions, ON_SELECTION, ("PartDesign_Fillet", "PartDesign_Chamfer"))
        self.assertNotIn(menuText("PartDesign_NewSketch"), texts(actions))

    def testOnAFaceAndAnEdge(self):
        """Mixed kinds: no Fillet or Chamfer."""
        self.select("Face6", "Edge1")
        actions = self.openMenu()
        self.assertMenu(actions, ON_SELECTION)
        for name in ("PartDesign_NewSketch", "PartDesign_Fillet", "PartDesign_Chamfer"):
            self.assertNotIn(menuText(name), texts(actions))

    def testOnEmptySpace(self):
        Gui.Selection.clearSelection()
        pump(0.1)
        actions = self.openMenu()
        expected = [menuText(c) for c in ON_EMPTY_SPACE]
        expected += [STANDARD_VIEWS, menuText("Std_ShowObjects"), MORE]
        found = texts(actions)
        self.assertEqual(found[-len(expected) :], expected, found)
        self.assertIsNotNone(submenu(actions, STANDARD_VIEWS))
        more = submenu(actions, MORE)
        self.assertMore(more, MORE_ON_EMPTY_SPACE, withStandardViews=False)
        for name in ON_SELECTION:
            self.assertNotIn(menuText(name), found, found)

    def testEntriesAreNotInTheMenuTwice(self):
        """Each of Onshape's entries is listed once at the top level (More may repeat
        Appearance: the Material workbench adds it after Go to Selection)."""
        self.select("Face6")
        found = texts(self.openMenu())
        for name in ON_SELECTION + ["PartDesign_NewSketch", "PartDesign_Fillet"]:
            self.assertEqual(found.count(menuText(name)), 1, found)


if __name__ == "__main__":
    unittest.main()
