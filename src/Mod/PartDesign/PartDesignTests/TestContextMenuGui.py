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

What the menu lists depends on what the right click hit, the preselection: the Onshape navigation
style selects the hit and keeps it preselected, so no preselection is empty space whatever is
selected. On a face of a body's feature, Sketch on face (a planar face), Fillet and Chamfer come
first, where the commands take the pick; on an edge, Fillet and Chamfer; on a vertex, a whole
object, a sketch's edge or an object outside a body, neither. Then the view entries (View normal
to on a face or a plane only, Zoom to selection), the visibility entries (Hide, Hide other parts,
Make transparent, then Edit appearance and Assign material, the Material workbench's), Select
other, Delete part (Delete for an object in no body), and a More submenu holding the rest of
FreeCAD's menu (PartDesign's Set Tip and roll-back entries, the link actions, the Standard Views
submenu, the draw style, the feature's own Delete...). The entity's own entries (a body's Active
Body) and Clarify Selection come after Onshape's, before More. On empty space: Zoom to fit,
Isometric, the Standard Views submenu, Show all parts, and More. Without the fork's keymap
(General/Keymap = FreeCAD) the menu is FreeCAD's. The commands keep their own menu texts (the
ledger notes where they differ from Onshape's words).

Designed model: a Body with a Pad of a 10 x 10 square; tests add a second body (a cylinder), a
Part::Box or a second pad where they need one. The pick is set by API as a right click finds it:
the preselection along the body's path, (Body, 'Pad.Face6'), and the selection of the picked
elements on the same path (the Onshape style keeps a selection its preselected entity is in). The
menu is opened by a synthetic right click on the 3D view with the Onshape navigation style, whose
plain right click selects the preselected entity and opens the menu; the TinkerCAD style, which
opens the menu without selecting, serves the cases where the selection comes from elsewhere (the
tree). The right click goes where the view shows the picked entity, for realism: the middle of
the view in the one-body top view (the pad's top face), else a pixel found by the view's own pick
(pixelOn). With the pick set by API the click's position does not decide the menu (the Onshape
style's right click selects the preselection, whatever is under the pointer); the one test that
sets no pick by API, testHoverSetsThePreselectionTheMenuFollows, drives the preselection by the
pointer's motion over the view (hover), so there the position is what decides. Off screen
(QT_QPA_PLATFORM=offscreen) a popup opens as on screen; where the platform opens none at all the
tests skip.

Two things the harness has to respect: Qt's Enter event to a widget outside the 3D view (the menu
as it opens, the widget under the pointer as it closes) makes OverlayManager drop the preselection,
so a pick is set only after the previous menu is closed; and the pointer is moved
(QCursor.setPos, which the offscreen platform turns into a mouse move) only where a user's pointer
would be: at the right click before the menu opens, at the entry before it is clicked.

Off screen in a fresh user home, the first right click of the session with the pointer over the
view makes two context menus: the pointer lies over a transparent overlay region in the first
layout, and OverlayManager's mouse-through re-sends the synthetic click to the view while the
original is delivered too (a real click goes to the overlay only). openMenu takes the active one;
closePopups closes the rest."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Sketcher

from PySide import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

ONSHAPE = "Gui::OnshapeNavigationStyle"
TINKERCAD = "Gui::TinkerCADNavigationStyle"
KEYMAP = "User parameter:BaseApp/Preferences/General"  # the preference Keymap (ForkKeymap)
PDBODY = "pdbody"  # the active body's key (PDBODYKEY)


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


def actionNamed(actions, text):
    """The action with the text (no accelerator mark), or None."""
    for action in actions:
        if action.text().replace("&", "") == text:
            return action
    return None


def onSelection(normalTo=True, deletePart=True):
    """The commands behind Onshape's entries on an entity, in Onshape's order: View normal to
    on a face or a plane only (ctx-11); Delete part on a body or its features, else Delete."""
    entries = [
        "Std_ViewNormal",  # View normal to
        "Std_ViewFitSelection",  # Zoom to selection
        "Std_HideSelection",  # Hide
        "Std_Isolate",  # Hide other parts
        "Std_ToggleTransparency",  # Make transparent
        "Std_SetAppearance",  # Edit appearance (the Material workbench's)
        "Std_SetMaterial",  # Assign material (the Material workbench's)
        "Std_SelectOther",  # Select other
        "Std_DeletePart" if deletePart else "Std_Delete",  # Delete part
    ]
    return entries if normalTo else entries[1:]


ON_FACE = onSelection()
ON_OTHER = onSelection(normalTo=False)
FIRST_ON_FACE = ("PartDesign_NewSketch", "PartDesign_Fillet", "PartDesign_Chamfer")
FIRST_ON_EDGE = ("PartDesign_Fillet", "PartDesign_Chamfer")

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
# Entries the view adds for the hit: the preselected view provider's own (a body's) and Clarify
# Selection (something under the cursor); they follow Onshape's entries (ctx-2)
ADDED_FOR_THE_HIT = ("Active Body", "Clarify Selection")


class TestContextMenuGui(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        Gui.getMainWindow().show()
        Gui.activateWorkbench("PartDesignWorkbench")
        group = App.ParamGet(KEYMAP)
        cls.savedKeymap = group.GetString("Keymap") if "Keymap" in group.GetStrings() else None
        pump()

    @classmethod
    def tearDownClass(cls):
        group = App.ParamGet(KEYMAP)
        if cls.savedKeymap is None:
            group.RemString("Keymap")
        else:
            group.SetString("Keymap", cls.savedKeymap)
        pump()

    def setUp(self):
        # the fork's keymap, Onshape, is the default; one test switches to FreeCAD's
        App.ParamGet(KEYMAP).RemString("Keymap")
        self.doc = App.newDocument("ContextMenuGui")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.sketch = self.squareSketch(self.body, 10, "Sketch")
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.sketch
        self.pad.Length = 5
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        self.view = Gui.ActiveDocument.ActiveView
        self.view.setAnimationEnabled(False)
        self.view.setNavigationType(ONSHAPE)
        self.view.fitAll()
        self.menu = None
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        pump(0.2)

    def tearDown(self):
        self.closePopups()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        pump()

    # --- the model

    @staticmethod
    def squareSketch(body, size, name):
        """A sketch of a size x size square on the body's XY plane."""
        sketch = body.newObject("Sketcher::SketchObject", name)
        sketch.AttachmentSupport = (body.Origin.OriginFeatures[3], [""])  # XY_Plane
        sketch.MapMode = "FlatFace"
        corners = [(0, 0), (size, 0), (size, size), (0, size)]
        for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
            sketch.addGeometry(
                Part.LineSegment(App.Vector(ax, ay, 0), App.Vector(bx, by, 0)), False
            )
        for i in range(4):
            sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        return sketch

    def cylinderBody(self):
        """A second body, Body001, with a pad of a circle beside the first: a curved face and
        two planar ones. Returns the body and its pad."""
        body = self.doc.addObject("PartDesign::Body", "Body001")
        sketch = body.newObject("Sketcher::SketchObject", "Sketch001")
        sketch.AttachmentSupport = (body.Origin.OriginFeatures[3], [""])  # XY_Plane
        sketch.MapMode = "FlatFace"
        sketch.addGeometry(Part.Circle(App.Vector(30, 0, 0), App.Vector(0, 0, 1), 4), False)
        pad = body.newObject("PartDesign::Pad", "Pad001")
        pad.Profile = sketch
        pad.Length = 5
        self.doc.recompute()
        # both bodies in view, the cylinder's curved face seen (the top view shows its rim only)
        self.view.viewIsometric()
        self.view.fitAll()
        pump(0.2)
        return body, pad

    @staticmethod
    def faces(feature):
        """The names of the feature's curved faces and of its planar faces."""
        curved, planar = [], []
        for i, face in enumerate(feature.Shape.Faces):
            kind = planar if isinstance(face.Surface, Part.Plane) else curved
            kind.append("Face%d" % (i + 1))
        return curved, planar

    @staticmethod
    def topFace(feature):
        """The planar face whose centre is highest: a pad's end face."""
        _, planar = TestContextMenuGui.faces(feature)
        return max(planar, key=lambda f: feature.Shape.Faces[int(f[4:]) - 1].CenterOfMass.z)

    def activate(self, body):
        self.view.setActiveObject(PDBODY, body)
        pump(0.1)

    # --- the pick and the menu

    def coinPixel(self, point):
        """A widget QPoint as the view's pixel (device pixels, origin bottom left), the
        coordinates getObjectInfo and the right click's position use."""
        _, height = self.view.getSize()
        scale = self.view.graphicsView().viewport().devicePixelRatioF()
        return (int(round(point.x() * scale)), int(round(height - point.y() * scale - 1)))

    def toQPoint(self, pixel):
        """The view's pixel as the widget's QPoint (TestOnshapeNavigationGui.toQPoint)."""
        _, height = self.view.getSize()
        scale = self.view.graphicsView().viewport().devicePixelRatioF()
        return QtCore.QPoint(int(round(pixel[0] / scale)), int(round((height - pixel[1] - 1) / scale)))

    def hit(self, pixel):
        """What the view's pick finds at the pixel: (object name, element), or None."""
        info = self.view.getObjectInfo(pixel)
        return None if info is None else (info["Object"], info["Component"])

    def assertHit(self, point, feature, element):
        """The pick at the widget point names the feature's element (what a right click there
        acts on)."""
        self.assertEqual(self.hit(self.coinPixel(point)), (feature.Name, element))

    def pixelOn(self, feature, element, step=10):
        """A widget point where the view shows the feature's element: the middle of the pixels
        whose pick names it, on a grid over the view (the pick is the right click's own; the
        view's projection, getPointOnViewport, does not match the pick in a viewport taller
        than wide). Asserts the pick at that point names the element."""
        width, height = self.view.getSize()
        hits = [
            (x, y)
            for y in range(step // 2, height, step)
            for x in range(step // 2, width, step)
            if self.hit((x, y)) == (feature.Name, element)
        ]
        self.assertTrue(hits, "%s.%s is not seen in the view" % (feature.Name, element))
        point = self.toQPoint((sum(h[0] for h in hits) // len(hits), sum(h[1] for h in hits) // len(hits)))
        self.assertHit(point, feature, element)
        return point

    def pick(self, *subs, feature=None):
        """Sets the pick as a right click finds it: on the feature's path through its body,
        (Body, 'Pad.Face6'), the preselection of the first sub and the selection of every sub;
        a feature in no body (a Part::Box) is its own path. An open menu is closed first, as
        a real hover comes after the menu: Qt's Enter event to the widget under the pointer as
        the menu closes makes OverlayManager drop the preselection (OverlayManager.cpp,
        eventFilter, QEvent::Enter)."""
        self.closePopups()
        feature = feature or self.pad
        group = feature.getParentGeoFeatureGroup()
        top = group if group is not None else feature
        prefix = feature.Name + "." if group is not None else ""
        Gui.Selection.clearSelection()
        for sub in subs:
            Gui.Selection.addSelection(self.doc.Name, top.Name, prefix + sub)
        Gui.Selection.setPreselection(top, prefix + subs[0])
        pump(0.1)

    def assertSelected(self, feature, element):
        """The Onshape style's right click selected the hit: the feature's element alone."""
        selected = [(s.Object.Name, s.SubElementNames) for s in Gui.Selection.getSelectionEx()]
        self.assertEqual(selected, [(feature.Name, (element,))])

    def hover(self, point):
        """Moves the pointer over the view to the widget point, as the motion event a real
        pointer sends: the view's hover pick sets the preselection (SoFCUnifiedSelection), no
        API call. An open menu is closed first, as for pick()."""
        self.closePopups()
        viewport = self.view.graphicsView().viewport()
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            QtCore.QPointF(point),
            QtCore.QPointF(viewport.mapToGlobal(point)),
            QtCore.Qt.NoButton,
            QtCore.Qt.NoButton,
            QtCore.Qt.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(viewport, event)
        pump(0.1)

    def preselected(self):
        """The preselection as (object name, element name), or None: the hover pick stores the
        path through the body, (Body, 'Pad.<mapped>.Face6'), so the element is the last part."""
        sel = Gui.Selection.getPreselection()
        if not sel.ObjectName:
            return None
        return (sel.ObjectName, sel.SubElementNames[0].split(".")[-1])

    def emptyPoint(self, step=10):
        """A widget point where the view's pick finds nothing."""
        width, height = self.view.getSize()
        for y in range(step // 2, height, step):
            for x in range(step // 2, width, step):
                if self.hit((x, y)) is None:
                    return self.toQPoint((x, y))
        self.fail("no empty space in the view")

    def closePopups(self):
        for _ in range(5):
            popup = QtWidgets.QApplication.activePopupWidget()
            if popup is None:
                break
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

    def openMenu(self, style=ONSHAPE, at=None):
        """Right-clicks the 3D view at the widget point (the middle by default) with the
        navigation style; returns the context menu's actions (the menu is self.menu). The menu
        is built from the preselection at the click; the preselection itself is gone once the
        menu is up (Qt's Enter event to the menu, OverlayManager drops it), as on screen."""
        self.closePopups()
        self.view.setNavigationType(style)
        pump(0.1)
        viewport = self.view.graphicsView().viewport()
        self.rightClick(viewport, at if at is not None else viewport.rect().center())
        QTest.qWait(300)
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is None:
            if not self.platformOpensPopups():
                self.skipTest("no popup menu opens on this platform")
            self.fail("the right-click opened no context menu")
        self.assertIsInstance(popup, QtWidgets.QMenu)
        self.menu = popup
        return popup.actions()

    def trigger(self, actions, name):
        """Triggers the menu's entry of the command, the menu left open."""
        action = actionNamed(actions, menuText(name))
        self.assertIsNotNone(action, "%s is not in the menu: %s" % (name, texts(actions)))
        action.trigger()
        pump(0.3)

    def clickEntry(self, actions, name):
        """Clicks the menu's entry of the command: as on screen, the menu closes (and is
        deleted, WA_DeleteOnClose) before the command runs. self.menu is gone afterwards."""
        action = actionNamed(actions, menuText(name))
        self.assertIsNotNone(action, "%s is not in the menu: %s" % (name, texts(actions)))
        QTest.mouseClick(
            self.menu, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, self.menu.actionGeometry(action).center()
        )
        self.menu = None
        pump(0.3)

    def assertMenu(self, actions, expectedCommands, firstCommands=()):
        """The menu starts with the expected commands' texts and ends with More; what the view
        adds for the hit (the body's Active Body, Clarify Selection) comes between (ctx-2)."""
        expected = [menuText(c) for c in tuple(firstCommands) + tuple(expectedCommands)]
        self.assertNotIn(None, expected, "a command is missing")
        found = texts(actions)
        self.assertEqual(found[: len(expected)], expected, found)
        self.assertEqual(found[-1], MORE, found)
        for text in ADDED_FOR_THE_HIT:
            if text in found:
                self.assertGreaterEqual(found.index(text), len(expected), found)
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

    def assertEmptySpaceMenu(self, actions):
        expected = [menuText(c) for c in ON_EMPTY_SPACE]
        expected += [STANDARD_VIEWS, menuText("Std_ShowParts")]
        found = texts(actions)
        self.assertEqual(found[: len(expected)], expected, found)
        self.assertEqual(found[-1], MORE, found)
        self.assertIsNotNone(submenu(actions, STANDARD_VIEWS))
        self.assertMore(submenu(actions, MORE), MORE_ON_EMPTY_SPACE, withStandardViews=False)
        for name in ON_FACE + ["Std_Delete", "Std_ShowObjects"]:
            self.assertNotIn(menuText(name), found, found)

    # --- tests

    def testOnAFace(self):
        """On a face of the body's pad: Sketch on face, Fillet and Chamfer first, View normal to
        among Onshape's entries (ctx-11), the body's Active Body after them (ctx-2), and the
        body's own entries under More."""
        self.pick("Face6")
        actions = self.openMenu()
        more = self.assertMenu(actions, ON_FACE, FIRST_ON_FACE)
        self.assertIn("Active Body", texts(actions), texts(actions))
        self.assertMore(more, MORE_ON_SELECTION, withStandardViews=True)
        # the body's own entries go under More too: the Pad is a feature of its body
        found = texts(more.actions())
        self.assertIn(menuText("PartDesign_MoveTip"), found, found)
        self.assertIn(menuText("PartDesign_RollTo"), found, found)
        # and before FreeCAD's
        self.assertLess(found.index(menuText("PartDesign_RollTo")), found.index(LINK_ACTIONS))
        # the first entries are not in the menu twice
        self.assertNotIn(menuText("PartDesign_NewSketch"), found)

    def testExportDxfOnAPlanarFace(self):
        """FreeCAD-CH, the DXF lane: Export DXF on a planar face, just before More (after
        Onshape's entries); not on an edge."""
        self.pick("Face6")
        found = texts(self.openMenu())
        export = menuText("Sketcher_ExportDxf")
        self.assertIsNotNone(export)
        self.assertIn(export, found, found)
        self.assertGreater(found.index(export), found.index(menuText("Std_DeletePart")), found)
        self.assertEqual(found[-1], MORE, found)
        self.pick("Edge1")
        self.assertNotIn(export, texts(self.openMenu()))

    def testRightClickSelectsTheFace(self):
        """The real path (ctx-8): a right click with a face preselected selects it, replacing the
        selection, and opens the face's menu."""
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, "Pad.Edge1")
        Gui.Selection.setPreselection(self.body, "Pad.Face6")
        pump(0.1)
        actions = self.openMenu()
        selected = [(s.Object.Name, s.SubElementNames) for s in Gui.Selection.getSelectionEx()]
        self.assertEqual(selected, [("Pad", ("Face6",))])
        self.assertMenu(actions, ON_FACE, FIRST_ON_FACE)

    def testOnAnEdge(self):
        """On an edge: Fillet and Chamfer, no Sketch on face, no View normal to (ctx-11)."""
        self.pick("Edge1")
        actions = self.openMenu()
        more = self.assertMenu(actions, ON_OTHER, FIRST_ON_EDGE)
        self.assertMore(more, MORE_ON_SELECTION, withStandardViews=True)
        for name in ("PartDesign_NewSketch", "Std_ViewNormal"):
            self.assertNotIn(menuText(name), texts(actions))

    def testOnAVertex(self):
        """On a vertex: none of the first entries and no View normal to (ctx-11)."""
        self.pick("Vertex1")
        actions = self.openMenu()
        more = self.assertMenu(actions, ON_OTHER)
        self.assertMore(more, MORE_ON_SELECTION, withStandardViews=True)
        for name in FIRST_ON_FACE + ("Std_ViewNormal",):
            self.assertNotIn(menuText(name), texts(actions))

    def testOnAWholeObject(self):
        """The pad selected in the tree, then a right click on it with a style that keeps the
        selection: the object's menu, without the first entries and View normal to (ctx-11)."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.pad.Name)
        Gui.Selection.setPreselection(self.body, "Pad.Face6")
        pump(0.1)
        actions = self.openMenu(TINKERCAD)
        more = self.assertMenu(actions, ON_OTHER)
        self.assertMore(more, MORE_ON_SELECTION, withStandardViews=True)
        for name in FIRST_ON_FACE + ("Std_ViewNormal",):
            self.assertNotIn(menuText(name), texts(actions))

    def testOnTwoEdges(self):
        """Fillet and Chamfer take several edges (or faces) of one object."""
        self.pick("Edge1", "Edge2")
        actions = self.openMenu()
        self.assertMenu(actions, ON_OTHER, FIRST_ON_EDGE)
        self.assertNotIn(menuText("PartDesign_NewSketch"), texts(actions))

    def testOnTwoFaces(self):
        """Sketch on face and View normal to want one face; Fillet and Chamfer take several."""
        self.pick("Face5", "Face6")
        actions = self.openMenu()
        self.assertMenu(actions, ON_OTHER, FIRST_ON_EDGE)
        self.assertNotIn(menuText("PartDesign_NewSketch"), texts(actions))

    def testOnAFaceAndAnEdge(self):
        """Mixed kinds: no Fillet or Chamfer."""
        self.pick("Face6", "Edge1")
        actions = self.openMenu()
        self.assertMenu(actions, ON_OTHER)
        for name in FIRST_ON_FACE:
            self.assertNotIn(menuText(name), texts(actions))

    def testOnEmptySpace(self):
        """Nothing under the cursor: the view menu, with Show all parts (not Show All Objects)."""
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        pump(0.1)
        self.assertEmptySpaceMenu(self.openMenu())

    def testOnEmptySpaceWithASelection(self):
        """ctx-1: a right click on empty space with the pad selected (from the tree) shows the
        view menu, not the entity's, and leaves the selection alone."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.pad.Name)
        Gui.Selection.clearPreselection()
        pump(0.1)
        self.assertEmptySpaceMenu(self.openMenu())
        self.assertEqual([o.Name for o in Gui.Selection.getSelection()], ["Pad"])

    def testAppearanceOnceAfterMakeTransparent(self):
        """ctx-7: Edit appearance and Assign material follow Make transparent at the top level
        and are not under More; each of Onshape's entries is listed once."""
        self.pick("Face6")
        actions = self.openMenu()
        found = texts(actions)
        for name in ON_FACE + list(FIRST_ON_FACE):
            self.assertEqual(found.count(menuText(name)), 1, found)
        transparent = found.index(menuText("Std_ToggleTransparency"))
        self.assertEqual(found[transparent + 1], menuText("Std_SetAppearance"), found)
        self.assertEqual(found[transparent + 2], menuText("Std_SetMaterial"), found)
        more = texts(submenu(actions, MORE).actions())
        self.assertNotIn(menuText("Std_SetAppearance"), more, more)
        self.assertNotIn(menuText("Std_SetMaterial"), more, more)

    def testFreeCADKeymapKeepsFreeCADsMenu(self):
        """ctx-6: with General/Keymap = FreeCAD the 3D view's menu is FreeCAD's: no More, Fit
        All at the top level, Delete (not Delete part), none of Onshape's first entries, the
        body's entries at the top level, Appearance where the Material workbench put it."""
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        pump(0.1)
        try:
            self.pick("Face6")
            found = texts(self.openMenu(TINKERCAD))
        finally:
            App.ParamGet(KEYMAP).RemString("Keymap")
            pump(0.1)
        self.assertNotIn(MORE, found, found)
        for name in ("Std_ViewFitAll", "Std_Delete", "PartDesign_MoveTip", "Std_SetAppearance"):
            self.assertIn(menuText(name), found, found)
        for name in FIRST_ON_FACE + ("Std_DeletePart", "Std_ShowParts", "Std_SelectOther"):
            self.assertNotIn(menuText(name), found, found)
        fitAll, delete = menuText("Std_ViewFitAll"), menuText("Std_Delete")
        self.assertLess(found.index(fitAll), found.index(delete), found)

    def testSketchOnFaceNeedsAPlanarFace(self):
        """ctx-5: on the active body's cylinder, its curved face gets Fillet and Chamfer but no
        Sketch on face; a planar face gets all three."""
        body, pad = self.cylinderBody()
        self.activate(body)
        curved, planar = self.faces(pad)
        self.assertTrue(curved and planar, (curved, planar))
        # the right click goes where the view shows the face, for realism: the pick is set by
        # API, and the menu follows it wherever the click lands (the hover test covers the hit)
        at = self.pixelOn(pad, curved[0])
        self.pick(curved[0], feature=pad)
        actions = self.openMenu(at=at)
        self.assertSelected(pad, curved[0])
        self.assertMenu(actions, ON_FACE, FIRST_ON_EDGE)
        self.assertNotIn(menuText("PartDesign_NewSketch"), texts(actions))
        top = self.topFace(pad)
        at = self.pixelOn(pad, top)
        self.pick(top, feature=pad)
        actions = self.openMenu(at=at)
        self.assertSelected(pad, top)
        self.assertMenu(actions, ON_FACE, FIRST_ON_FACE)

    def testFilletOnAnyPartsFace(self):
        """ctx-5, ops#640 rank 14: with two bodies, Fillet and Chamfer are offered on a face of
        either, the active one or not, and with none active (the dress-up goes into the face's
        Body); Sketch on face needs a body to put the sketch in: not with none active, and on a
        sibling part's face it goes into the active body (ops#325, no dialog)."""
        body, _ = self.cylinderBody()
        # with both bodies in view the middle is empty space: the click goes to the pad's top,
        # for realism (the pick is set by API; see testHoverSetsThePreselectionTheMenuFollows)
        at = self.pixelOn(self.pad, "Face6")
        self.pick("Face6")
        actions = self.openMenu(at=at)
        self.assertSelected(self.pad, "Face6")
        self.assertMenu(actions, ON_FACE, FIRST_ON_EDGE)
        self.assertNotIn(menuText("PartDesign_NewSketch"), texts(actions))
        self.activate(body)
        self.pick("Face6")
        actions = self.openMenu(at=at)
        self.assertSelected(self.pad, "Face6")
        self.assertMenu(actions, ON_FACE, FIRST_ON_FACE)
        self.activate(self.body)
        self.pick("Face6")
        actions = self.openMenu(at=at)
        self.assertSelected(self.pad, "Face6")
        self.assertMenu(actions, ON_FACE, FIRST_ON_FACE)

    def testHoverSetsThePreselectionTheMenuFollows(self):
        """The on-screen chain with no pick set by API: the pointer's motion over the view
        preselects what is under it (the hover pick), the Onshape style's right click selects
        that, and the menu follows it; so the pointer's position decides. Two bodies, the
        cylinder active: its curved face gets Fillet and Chamfer without Sketch on face, the
        first body's top face Sketch on face (a sibling part's face, ops#325), Fillet and
        Chamfer (any part's, ops#640 rank 14), and empty space the view menu with the selection
        left alone (ctx-1)."""
        body, pad = self.cylinderBody()
        self.activate(body)
        curved, _ = self.faces(pad)
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        at = self.pixelOn(pad, curved[0])
        self.hover(at)
        self.assertEqual(self.preselected(), (body.Name, curved[0]))
        actions = self.openMenu(at=at)
        self.assertSelected(pad, curved[0])
        self.assertMenu(actions, ON_FACE, FIRST_ON_EDGE)
        self.assertNotIn(menuText("PartDesign_NewSketch"), texts(actions))
        at = self.pixelOn(self.pad, "Face6")
        self.hover(at)
        self.assertEqual(self.preselected(), (self.body.Name, "Face6"))
        actions = self.openMenu(at=at)
        self.assertSelected(self.pad, "Face6")
        self.assertMenu(actions, ON_FACE, FIRST_ON_FACE)
        at = self.emptyPoint()
        self.hover(at)
        self.assertIsNone(self.preselected())
        actions = self.openMenu(at=at)
        self.assertEmptySpaceMenu(actions)
        self.assertSelected(self.pad, "Face6")

    def testFilletOnAnotherPartsEdge(self):
        """ops#640 rank 14: an edge of the second body's pad gets Fillet and Chamfer with the
        first body active, and with none active (Onshape has no active part); the entry makes the
        fillet in the edge's Body, with no question for a body."""
        body, pad = self.cylinderBody()
        edge = "Edge1"
        self.assertTrue(pad.Shape.Edges[0].Length > 0)
        for active in (self.body, None):
            self.activate(active)
            self.pick(edge, feature=pad)
            actions = self.openMenu()
            self.assertMenu(actions, ON_OTHER, FIRST_ON_EDGE)
        self.clickEntry(actions, "PartDesign_Fillet")
        try:
            self.assertTrue(Gui.Control.activeDialog(), "the Fillet's dialog did not open")
            QtWidgets.QApplication.processEvents()
            self.assertIsNone(QtWidgets.QApplication.activeModalWidget(), "a modal opened")
            [fillet] = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Fillet"]
            self.assertTrue(body.hasObject(fillet))
            self.assertEqual((fillet.Base[0], list(fillet.Base[1])), (pad, [edge]))
        finally:
            dialog = Gui.Control.activeTaskDialog()
            if dialog is not None:
                dialog.reject()
                pump(0.2)

    def testNoFilletOnASketchEdge(self):
        """ctx-5: a sketch's edge picked in the 3D view gets no Fillet or Chamfer (a Fillet on
        a sketch fails); the sketch is the body's, so Delete part applies."""
        self.pick("Edge1", feature=self.sketch)
        actions = self.openMenu()
        self.assertMenu(actions, ON_OTHER)
        for name in FIRST_ON_FACE:
            self.assertNotIn(menuText(name), texts(actions))

    def testNoFilletOrSketchOnAPartFeature(self):
        """ctx-5, ctx-4: a face of a Part::Box outside the body gets neither Fillet, Chamfer nor
        Sketch on face (the commands refuse an object outside the active body), and Delete, not
        Delete part."""
        box = self.doc.addObject("Part::Box", "Box")
        box.Placement.Base = App.Vector(20, 20, 0)
        self.doc.recompute()
        pump(0.1)
        self.pick("Face1", feature=box)
        actions = self.openMenu()
        self.assertMenu(actions, onSelection(deletePart=False))
        for name in FIRST_ON_FACE + ("Std_DeletePart",):
            self.assertNotIn(menuText(name), texts(actions))

    def testDeletePartKeepsTheFeatures(self):
        """ctx-4: Delete part on a face of the pad deletes the body as a part: a Delete part
        feature joins its history, the Pad and the Body stay; the feature's Delete is under More."""
        self.pick("Face6")
        actions = self.openMenu()
        more = self.assertMenu(actions, ON_FACE, FIRST_ON_FACE)
        self.assertIn(menuText("Std_Delete"), texts(more.actions()))
        self.trigger(actions, "Std_DeletePart")
        self.closePopups()
        # Its dialog, prefilled with the part: OK (ops#640 rank 30)
        from PartDesignTests.TestExpressionFieldsGui import taskButton, waitFor

        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no Delete part dialog")
        Gui.Control.showTaskView()
        self.assertTrue(waitFor(lambda: taskButton(QtWidgets.QDialogButtonBox.Ok) is not None))
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        self.assertIsNotNone(self.doc.getObject("Body"))
        self.assertIsNotNone(self.doc.getObject("Pad"))
        deletes = [o for o in self.body.Group if o.TypeId == "PartDesign::DeletePart"]
        self.assertEqual(len(deletes), 1, [o.Name for o in self.body.Group])

    def testShowAllPartsShowsThePartsOnly(self):
        """Show all parts (the empty-space menu) shows the bodies, each with its tip, and the
        solids outside a body; not the sketches, the earlier features or the origins."""
        sketch = self.squareSketch(self.body, 4, "Sketch001")
        pad = self.body.newObject("PartDesign::Pad", "Pad001")
        pad.Profile = sketch
        pad.Length = 2
        box = self.doc.addObject("Part::Box", "Box")
        box.Placement.Base = App.Vector(20, 20, 0)
        self.doc.recompute()
        origins = [self.body.Origin] + list(self.body.Origin.OriginFeatures)
        originsShown = [o.Visibility for o in origins]
        for obj in (self.body, self.sketch, sketch, self.pad, pad, box):
            obj.ViewObject.Visibility = False
        pump(0.1)
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        actions = self.openMenu()
        self.trigger(actions, "Std_ShowParts")
        self.closePopups()
        self.assertTrue(self.body.Visibility, "the body")
        self.assertTrue(pad.Visibility, "the body's tip")
        self.assertTrue(box.Visibility, "a solid outside a body")
        self.assertFalse(self.pad.Visibility, "an earlier feature")
        self.assertFalse(self.sketch.Visibility, "a sketch")
        self.assertFalse(sketch.Visibility, "the tip's sketch")
        self.assertEqual([o.Visibility for o in origins], originsShown, "the origin")

    def movePointer(self, globalPoint):
        """Moves the pointer (the platform turns it into a mouse move for the popup)."""
        QtGui.QCursor.setPos(globalPoint)
        pump(0.2)

    def activeList(self):
        """The Select other list when it is the active popup, else None."""
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is None or popup.objectName() != "SelectOtherMenu":
            return None
        return popup

    def testSelectOtherFromTheMenuListsTheRightClickPoint(self):
        """ctx-3, as on screen: the pointer right-clicks the view's middle, moves to the Select
        other entry and clicks it; the list opens at the right click (not under the pointer, as
        from the key) and lists what lay there, nearest first. It stays while the pointer is
        away or approaches, and closes once the pointer has been at it and leaves (the list
        the key opens is under the pointer from the start, so there leaving closes it)."""
        viewport = self.view.graphicsView().viewport()
        center = viewport.rect().center()
        rightClick = viewport.mapToGlobal(center)
        self.assertHit(center, self.pad, "Face6")
        cursor = QtGui.QCursor.pos()
        try:
            self.movePointer(rightClick)
            self.pick("Face6")
            actions = self.openMenu()
            action = actionNamed(actions, menuText("Std_SelectOther"))
            self.assertIsNotNone(action, texts(actions))
            entry = self.menu.mapToGlobal(self.menu.actionGeometry(action).center())
            self.movePointer(entry)
            self.assertIs(QtWidgets.QApplication.activePopupWidget(), self.menu)
            self.clickEntry(actions, "Std_SelectOther")
            popup = self.activeList()
            self.assertIsNotNone(popup, "Select other opened no list")
            listed = texts(popup.actions())
            # at the right click, when the list fits the screen there (QMenu shifts it otherwise)
            if QtWidgets.QApplication.primaryScreen().availableGeometry().contains(
                QtCore.QRect(rightClick, popup.size())
            ):
                opened = popup.pos() - rightClick
                self.assertLessEqual(opened.manhattanLength(), 4, "the list is not at the right click")
            # the pointer (at the entry) is outside the list's reach (SelectOtherMenu's margin)
            reach = popup.geometry().adjusted(-16, -16, 16, 16)
            self.assertFalse(reach.contains(entry), (entry, popup.geometry()))
            # the user's first motion, far from the list: the list stays
            self.movePointer(entry + QtCore.QPoint(2, 0))
            self.assertIs(self.activeList(), popup, "the list closed on the pointer's first move")
            # the pointer reaches the list, then leaves it: the list closes
            self.movePointer(popup.geometry().center())
            self.assertIs(self.activeList(), popup, "the list closed as the pointer reached it")
            self.movePointer(viewport.mapToGlobal(QtCore.QPoint(20, 20)))
            self.assertIsNone(self.activeList(), "the list stayed after the pointer left it")
        finally:
            QtGui.QCursor.setPos(cursor)
            self.closePopups()
        # the list names the element nearest first ("Face6 · Pad")
        self.assertTrue(listed and listed[0].startswith("Face6 "), listed)


if __name__ == "__main__":
    unittest.main()
