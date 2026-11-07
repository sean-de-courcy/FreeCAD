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
tree). Off screen (QT_QPA_PLATFORM=offscreen) a popup opens as on screen; where the platform opens
none at all the tests skip."""

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
        pump(0.1)
        return body, pad

    @staticmethod
    def faces(feature):
        """The names of the feature's curved faces and of its planar faces."""
        curved, planar = [], []
        for i, face in enumerate(feature.Shape.Faces):
            kind = planar if isinstance(face.Surface, Part.Plane) else curved
            kind.append("Face%d" % (i + 1))
        return curved, planar

    def activate(self, body):
        self.view.setActiveObject(PDBODY, body)
        pump(0.1)

    # --- the pick and the menu

    def pick(self, *subs, feature=None):
        """Sets the pick as a right click finds it: on the feature's path through its body,
        (Body, 'Pad.Face6'), the preselection of the first sub and the selection of every sub;
        a feature in no body (a Part::Box) is its own path."""
        feature = feature or self.pad
        group = feature.getParentGeoFeatureGroup()
        top = group if group is not None else feature
        prefix = feature.Name + "." if group is not None else ""
        Gui.Selection.clearSelection()
        for sub in subs:
            Gui.Selection.addSelection(self.doc.Name, top.Name, prefix + sub)
        Gui.Selection.setPreselection(top, prefix + subs[0])
        pump(0.1)

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

    def openMenu(self, style=ONSHAPE):
        """Right-clicks the middle of the 3D view with the navigation style; returns the context
        menu's actions (the menu is self.menu)."""
        self.closePopups()
        self.view.setNavigationType(style)
        pump(0.1)
        viewport = self.view.graphicsView().viewport()
        self.rightClick(viewport, viewport.rect().center())
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
        """Triggers the menu's entry of the command, as a click on it would."""
        action = actionNamed(actions, menuText(name))
        self.assertIsNotNone(action, "%s is not in the menu: %s" % (name, texts(actions)))
        action.trigger()
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
        self.pick(curved[0], feature=pad)
        actions = self.openMenu()
        self.assertMenu(actions, ON_FACE, FIRST_ON_EDGE)
        self.assertNotIn(menuText("PartDesign_NewSketch"), texts(actions))
        self.pick(planar[0], feature=pad)
        self.assertMenu(self.openMenu(), ON_FACE, FIRST_ON_FACE)

    def testFilletNeedsTheBodyTheCommandsUse(self):
        """ctx-5: with two bodies, Fillet and Chamfer are offered on the active body's faces
        only (the commands refuse the others); with none active neither they nor Sketch on face
        (the commands would ask for a body); Sketch on face is offered on a sibling part's face
        (ops#325: the sketch goes into the active body, no dialog)."""
        body, _ = self.cylinderBody()
        self.pick("Face6")
        actions = self.openMenu()
        self.assertMenu(actions, ON_FACE)
        for name in FIRST_ON_FACE:
            self.assertNotIn(menuText(name), texts(actions))
        self.activate(body)
        self.pick("Face6")
        actions = self.openMenu()
        self.assertMenu(actions, ON_FACE, ("PartDesign_NewSketch",))
        for name in FIRST_ON_EDGE:
            self.assertNotIn(menuText(name), texts(actions))
        self.activate(self.body)
        self.pick("Face6")
        self.assertMenu(self.openMenu(), ON_FACE, FIRST_ON_FACE)

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

    def testSelectOtherFromTheMenuListsTheRightClickPoint(self):
        """ctx-3: Select other from the menu lists what lay under the right click, with the
        cursor elsewhere (over a menu entry on screen)."""
        viewport = self.view.graphicsView().viewport()
        center = viewport.rect().center()
        # the element the right click hits, in the view's own coordinates (y from the bottom)
        info = self.view.getObjectInfo((center.x(), viewport.height() - center.y() - 1))
        self.assertIsNotNone(info, "nothing under the middle of the view")
        self.pick("Face6")
        actions = self.openMenu()
        cursor = QtGui.QCursor.pos()
        try:
            QtGui.QCursor.setPos(viewport.mapToGlobal(QtCore.QPoint(-40, -40)))
            self.trigger(actions, "Std_SelectOther")
            popup = QtWidgets.QApplication.activePopupWidget()
            self.assertIsNotNone(popup, "Select other opened no list")
            self.assertIsNot(popup, self.menu, "Select other opened no list")
            listed = texts(popup.actions())
        finally:
            QtGui.QCursor.setPos(cursor)
            self.closePopups()
        # the list names the element ("Face6 · Pad"); the hit may come as 'Pad.Face6' on the body
        element = info["Component"].rsplit(".", 1)[-1]
        self.assertTrue(any(t.startswith(element + " ") for t in listed), (element, listed))


if __name__ == "__main__":
    unittest.main()
