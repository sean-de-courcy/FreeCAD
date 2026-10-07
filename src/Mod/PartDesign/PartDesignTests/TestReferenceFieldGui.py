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

"""The reference field of the dress-up panels (FreeCAD-CH, ops#150 W1; notes/reference-list-widget.md).

One field per reference list, armed while it has the focus (no Select button): a pick toggles an
element, Delete removes the selected entries, Ctrl+Z / Ctrl+Y step through the field's own picks,
Esc disarms before it cancels. Entries show their state (broken red, guessed yellow) and carry the
References panel's actions in their context menu; the panel at the top only lists what no field
shows.

Designed models, each built by the test:
- Box: a 10 x 10 x 10 additive box. A fillet of radius r on an edge of length L takes
  (1 - pi/4) r^2 L off the volume: 2.146 mm^3 for r = 1, L = 10.
- Boss: a block 0..20 x 0..10 x 10 and a step padded onto its right side (x 20..20.5); a fillet,
  r = 0.25, on the step's front vertical edge. The step is deleted: the reference breaks, with the
  block's front right edge (0.5 mm away) as the first candidate (N3, policy D).
- Redraw: a pad of a rectangle 0..20 x 0..10, 10 high, a fillet r = 1 on its vertical edge at
  (20, 0); the rectangle drawn again the other way round: the edge is found again by geometry
  (tier 3), a guess with a warning.
- Regions (W3): a sketch with rectangle A 0..20 x 0..10, a circle r = 2 at (10, 5) inside it, and
  a separate rectangle B 30..40 x 0..10; Pad 5. Its regions: A minus the disk (200 - 4 pi), the
  disk (4 pi), B (100). The whole sketch pads 5 (300 - 4 pi) (A's hole stays); B alone 500; the
  disk alone 20 pi; all three 1500 (the hole filled).
- Pattern (W4): the box moved to -5..5 x -5..5 x 0..10, and two 1 x 1 x 1 additive boxes on its
  top of one Label, "Bump": the first at (1, 1), the second at (1, -3). A pattern of both adds one
  copy of each, 2 mm^3, all on the box's top and apart: linear along X, length 2 (copies at x 3);
  polar about Z, 360 degrees in 2 (at x -2); mirrored in the YZ plane (at x -2). The volume is
  1002 plus 1 per bump patterned.
- Preview opacity (W5): the pad of padOnBox (a square on the box, 3 long); a pocket of the same
  square, 3 deep; a fillet on the box's top front edge. The Preview box's slider sets the preview
  shape's opacity, read back as its Coin node's transparency (1 - opacity); a pocket's tool shape
  scales with it (the theme's 0.05 at the theme's 0.2, so 0.15 at 0.6).

Keys go through the window (QTest's QWindow overload), so the shortcut map sees them as it sees a
user's. Each arming test also has a twin that arms through the field's `armed` property, so that a
focus quirk of an off-screen platform can't hide a logic failure."""

import math
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets
from PySide6 import QtTest

from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import X, Z, edge, face
from PartDesignTests.TestDressUpDeleteKeyGui import focus, pump, taskButton, waitFor

STATE_ROLE = QtCore.Qt.UserRole + 1
SUB_ROLE = QtCore.Qt.UserRole + 2
FILLET_CUT = (1 - math.pi / 4) * 10  # r = 1, L = 10
# The highlight's colours (rounded): an entry, the current entry, and the highlighter's colour for
# a whole object, which no entry should show.
MAGENTA = (1.0, 0.0, 1.0)
CURRENT = (0.0, 0.75, 1.0)
PURPLE = (0.6, 0.0, 1.0)
# A face 10 x 10 drafted by 2 degrees about its line on the neutral plane, 10 away at the other
# end: the volume changes by a wedge, 10 * 10 * 10 tan(2) / 2.
DRAFT_CHANGE = 500 * math.tan(math.radians(2))
TOP_FRONT = edge("line", direction=X, through=(0, 0, 10))
BOTTOM_BACK = edge("line", direction=X, through=(0, 10, 0))
VERTICAL = edge("line", direction=Z, through=(10, 0, 0))
# The Regions model padded 5 from the whole sketch: A's hole stays.
WHOLE_SKETCH = 5 * (300 - 4 * math.pi)


def flushDeletes():
    """Deletes the widgets of closed dialogs now: processEvents() leaves deleteLater() to the
    event loop, and a closed dialog's field still counts as visible until then."""
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def settle():
    """After a dialog opens: its panel's queued focus (the value field, when the list is complete)
    lands, and so does the last dialog's late switch back to the Model tab, which hides the task
    view off screen; the task view is put in front again."""
    pump(0.3)
    Gui.Control.showTaskView()
    pump(0.05)


def fields():
    """The visible reference fields of the task view, top to bottom."""
    flushDeletes()
    found = [
        widget
        for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget)
        if widget.metaObject().className() == "PartDesignGui::ReferenceField"
        and widget.isVisible()
    ]
    return sorted(found, key=lambda w: w.mapTo(Gui.getMainWindow(), QtCore.QPoint(0, 0)).y())


def entries(field):
    return field.findChild(QtWidgets.QListWidget, "entries")


def texts(field):
    refs = entries(field)
    return [refs.item(i).text() for i in range(refs.count())]


def states(field):
    refs = entries(field)
    return [refs.item(i).data(STATE_ROLE) for i in range(refs.count())]


def armed(field):
    return bool(field.property("armed"))


def findField(name):
    """A reference field of the task view by its objectName, shown or not."""
    flushDeletes()
    return Gui.getMainWindow().findChild(QtWidgets.QWidget, name)


def selected(doc):
    return [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx(doc.Name)]


def views3D():
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    return [w.widget() for w in mdi.subWindowList() if w.widget().metaObject().className() == "Gui::View3DInventor"]


def key(which, modifiers=QtCore.Qt.NoModifier):
    """A key as the window system delivers it: shortcut map first, then the focus widget."""
    QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), which, modifiers)
    pump(0.1)


def clickRow(field, row, modifiers=QtCore.Qt.NoModifier):
    refs = entries(field)
    rect = refs.visualItemRect(refs.item(row))
    QtTest.QTest.mouseClick(refs.viewport(), QtCore.Qt.LeftButton, modifiers, rect.center())
    pump(0.1)


def statusText():
    """The status bar's text: MainWindow::showMessage writes to a label in it."""
    bar = Gui.getMainWindow().statusBar()
    texts = [bar.currentMessage()] + [label.text() for label in bar.findChildren(QtWidgets.QLabel)]
    return "\n".join(texts)


def openMenu(field, row):
    """The entry's context menu, as a right click opens it; returns the menu (it stays open)."""
    refs = entries(field)
    refs.setCurrentRow(row)
    rect = refs.visualItemRect(refs.item(row))
    refs.customContextMenuRequested.emit(rect.center())
    menu = None

    def found():
        nonlocal menu
        menu = Gui.getMainWindow().findChild(QtWidgets.QMenu, "entryMenu")
        if menu is None:
            popup = QtWidgets.QApplication.activePopupWidget()
            if popup is not None and popup.objectName() == "entryMenu":
                menu = popup
        return menu is not None

    waitFor(found, 2.0)
    return menu


def menuActions(menu):
    """{text: action} of a menu, the shortcut text left out."""
    return {a.text().split("\t")[0]: a for a in menu.actions() if not a.isSeparator()}


class TestReferenceFieldGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("ReferenceField")
        self.doc.UndoMode = 1
        Gui.Selection.clearSelection()
        mainWindow = Gui.getMainWindow()
        mainWindow.activateWindow()

    def tearDown(self):
        guiDoc = Gui.getDocument(self.doc.Name)
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        # the closed dialog's widgets go later: the next test mustn't count its field
        waitFor(lambda: not fields(), 3.0)
        for name in list(App.listDocuments()):
            if name.startswith(("ReferenceField", "OtherDocument")):
                App.closeDocument(name)
        pump()

    # -- models ---------------------------------------------------------------------------------

    def box(self):
        self.body = models.body(self.doc)
        self.boxFeature = self.doc.addObject("PartDesign::AdditiveBox", "Box")
        self.body.addObject(self.boxFeature)
        for prop in ("Length", "Width", "Height"):
            setattr(self.boxFeature, prop, 10)
        self.doc.recompute()
        return self.boxFeature

    def newFillet(self):
        """The box, and a new fillet made as the command makes one with nothing selected: an
        empty edge list and the fillet's dialog open."""
        box = self.box()
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        Gui.runCommand("PartDesign_Fillet")
        self.assertTrue(waitFor(lambda: len(fields()) == 1), "the fillet's reference field")
        settle()
        self.assertEqual(len(fields()), 1)
        fillet = self.doc.getObject("Fillet")
        self.assertIsNotNone(fillet)
        self.assertEqual(fillet.Base[1], [])
        return box, fillet

    def addFillet(self, base, names, radius=1):
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (base, names)
        fillet.Radius = radius
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        return fillet

    def edit(self, feature, count=1):
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        self.assertTrue(waitFor(lambda: len(fields()) == count), "the dialog's reference fields")
        self.assertTrue(Gui.Control.activeDialog())
        settle()
        return fields()

    def boss(self):
        """The Boss model, the step deleted: the fillet's reference is broken."""
        self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = True
        body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        stepSketch = models.sketch(self.doc, "StepSketch", models.rectangle(20, 0, 20.5, 10), body)
        step = models.pad(body, stepSketch, 10, name="Step")
        self.doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (step, edge("line", direction=Z, through=(20.5, 0, 0)).one(step.Shape))
        fillet.Radius = 0.25
        self.doc.recompute()
        body.removeObject(step)
        self.doc.removeObject("Step")
        self.doc.recompute()
        self.assertFalse(fillet.isValid())
        self.assertTrue(fillet.Base[1][0].startswith("?"), fillet.Base)
        return pad, fillet

    def redrawnPad(self):
        self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = True
        body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        self.doc.recompute()
        return body, pad

    def redraw(self):
        self.doc.Profile.deleteAllGeometry()
        self.doc.Profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        self.doc.recompute()

    def redrawnFillet(self):
        body, pad = self.redrawnPad()
        corner = edge("line", direction=Z, through=(20, 0, 0))
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, corner.one(pad.Shape))
        fillet.Radius = 1
        self.doc.recompute()
        self.redraw()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertIn("Warning", fillet.State)
        [now] = corner.one(pad.Shape)
        return pad, fillet, now

    def draft(self):
        """The box and a 2 degree draft of its front face, the bottom as the neutral plane."""
        box = self.box()
        [self.side] = face(normal=(0, -1, 0)).one(box.Shape)
        [self.bottom] = face(normal=(0, 0, -1)).one(box.Shape)
        [self.top] = face(normal=(0, 0, 1)).one(box.Shape)
        [self.back] = face(normal=(0, 1, 0)).one(box.Shape)
        draft = self.body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (box, [self.side])
        draft.NeutralPlane = (box, [self.bottom])
        draft.Angle = 2
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        self.assertAlmostEqual(abs(draft.Shape.Volume - 1000), DRAFT_CHANGE, places=3)
        return box, draft

    def datumPlane(self, body, name, z):
        """A datum plane parallel to XY at height z, not attached."""
        plane = body.newObject("PartDesign::Plane", name)
        plane.MapMode = "Deactivated"
        plane.Placement = App.Placement(App.Vector(0, 0, z), App.Rotation())
        return plane

    def padOnBox(self, toFace=True):
        """The box, two datum planes at z = 15 and 17, and a pad of a square 2..4 x 2..4 on the
        box's top: up to the lower plane (20 mm^3 added), or 3 long when not toFace."""
        box = self.box()
        self.low = self.datumPlane(self.body, "Low", 15)
        self.high = self.datumPlane(self.body, "High", 17)
        square = models.sketch(self.doc, "Square", models.rectangle(2, 2, 4, 4), self.body, z=10)
        pad = models.pad(self.body, square, 3)
        if toFace:
            pad.Type = "UpToFace"
            pad.UpToFace = (self.low, [""])
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, 1020 if toFace else 1012, places=3)
        return box, pad

    def upToShapePad(self, faces):
        """A pad of a square 2..4 x 2..4 on XY, up to a shape outside the body: three squares
        0..10 x 0..10 at z = 20, 30 and 40 (Face1, Face2, Face3). It stops at the lowest face
        it is given: 80, 120 or 160 mm^3; all faces of the shape, 80."""
        body = models.body(self.doc)
        square = models.sketch(self.doc, "Square", models.rectangle(2, 2, 4, 4), body)
        import Part

        planes = [Part.makePlane(10, 10, App.Vector(0, 0, z)) for z in (20, 30, 40)]
        target = models.feature(self.doc, "Target", Part.makeCompound(planes))
        self.doc.recompute()
        for i, z in enumerate((20, 30, 40)):
            self.assertAlmostEqual(target.Shape.Faces[i].CenterOfMass.z, z)
        pad = models.pad(body, square, 5)
        pad.Type = "UpToShape"
        pad.UpToShape = (target, faces)
        self.doc.recompute()
        return pad, target

    def pick(self, obj, sub):
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        pump(0.2)

    def assertLink(self, prop, obj, subs):
        """A link property names obj and, besides empty names, subs."""
        self.assertIsNotNone(prop)
        self.assertEqual(prop[0].Name, obj.Name)
        self.assertEqual([s for s in prop[1] if s], subs)

    def arm(self, field, byFocus):
        if byFocus:
            self.assertTrue(focus(entries(field)), "the field doesn't take the focus")
        else:
            field.setProperty("armed", True)
            pump(0.1)
        self.assertTrue(waitFor(lambda: armed(field)), "the field isn't armed")

    def assertVolume(self, feature, expected):
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertAlmostEqual(feature.Shape.Volume, expected, places=3)

    # -- T1, T2: arming on open, picks toggle -----------------------------------------------------

    def testNewFilletIsArmedAndPicksToggle(self):
        """T1, T2: a new fillet's edges field is armed when the dialog opens; a pick in the 3D
        view adds the edge, a second edge adds that one, a pick of the second again removes it.
        The volume follows (2.146 mm^3 per edge)."""
        box, fillet = self.newFillet()
        [field] = fields()
        self.assertTrue(waitFor(lambda: armed(field)), "the new fillet's field isn't armed")
        self.assertIsNone(
            Gui.getMainWindow().findChild(QtWidgets.QAbstractButton, "buttonRefSel"),
            "the Select button is still there",
        )
        [first] = TOP_FRONT.one(box.Shape)
        [second] = BOTTOM_BACK.one(box.Shape)

        self.pick(box, first)
        self.assertEqual(fillet.Base[1], [first])
        self.assertEqual(texts(field), [first])
        self.assertVolume(fillet, 1000 - FILLET_CUT)

        self.pick(box, second)
        self.assertEqual(fillet.Base[1], [first, second])
        self.assertVolume(fillet, 1000 - 2 * FILLET_CUT)

        self.pick(box, second)
        self.assertEqual(fillet.Base[1], [first])
        self.assertEqual(texts(field), [first])
        self.assertVolume(fillet, 1000 - FILLET_CUT)
        self.assertTrue(armed(field))

    def testCompleteFilletOpensUnarmed(self):
        """Q2: an edit of a complete fillet arms nothing; a pick then only selects."""
        box = self.box()
        [first] = TOP_FRONT.one(box.Shape)
        fillet = self.addFillet(box, [first])
        [field] = self.edit(fillet)
        pump(0.3)
        self.assertFalse(armed(field))
        [second] = BOTTOM_BACK.one(box.Shape)
        self.pick(box, second)
        self.assertEqual(fillet.Base[1], [first])

    # -- T3, T4: what disarms and what doesn't --------------------------------------------------

    def disarmBySpinBox(self, byFocus):
        """T3: the radius takes the focus: the field disarms, and a pick leaves Base alone."""
        box, fillet = self.newFillet()
        [field] = fields()
        self.arm(field, byFocus)
        radius = Gui.getMainWindow().findChild(QtWidgets.QWidget, "filletRadius")
        self.assertIsNotNone(radius)
        self.assertTrue(focus(radius), "the radius doesn't take the focus")
        self.assertTrue(waitFor(lambda: not armed(field)), "still armed with the radius focused")
        [first] = TOP_FRONT.one(box.Shape)
        self.pick(box, first)
        self.assertEqual(fillet.Base[1], [])
        self.assertEqual(texts(field), [])

    def testSpinBoxDisarms(self):
        self.disarmBySpinBox(byFocus=True)

    def testSpinBoxDisarmsArmedByProperty(self):
        self.disarmBySpinBox(byFocus=False)

    def staysArmedIn3DView(self, byFocus):
        """T4: a click into the 3D view (the focus leaves the dialog): still armed, a pick adds."""
        box, fillet = self.newFillet()
        [field] = fields()
        self.arm(field, byFocus)
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        self.views = [
            w for w in mdi.subWindowList() if w.widget().metaObject().className() == "Gui::View3DInventor"
        ]
        self.assertTrue(self.views)
        self.assertTrue(focus(self.views[0].widget()), "the 3D view doesn't take the focus")
        pump(0.2)
        self.assertTrue(armed(field), "the 3D view's focus disarmed the field")
        [first] = TOP_FRONT.one(box.Shape)
        self.pick(box, first)
        self.assertEqual(fillet.Base[1], [first])

    def testStaysArmedIn3DView(self):
        self.staysArmedIn3DView(byFocus=True)

    def testStaysArmedIn3DViewArmedByProperty(self):
        self.staysArmedIn3DView(byFocus=False)

    # -- T5: Esc --------------------------------------------------------------------------------

    def testEscDisarmsThenCancels(self):
        """T5: Esc with the field armed disarms it and the dialog stays; the next Esc cancels the
        dialog, and Base is what it was before the edit."""
        box = self.box()
        [first] = TOP_FRONT.one(box.Shape)
        [second] = BOTTOM_BACK.one(box.Shape)
        fillet = self.addFillet(box, [first])
        [field] = self.edit(fillet)
        self.arm(field, byFocus=True)
        self.pick(box, second)
        self.assertEqual(fillet.Base[1], [first, second])
        self.assertTrue(focus(entries(field)))

        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(field)), "Esc didn't disarm the field")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "the first Esc closed the dialog")

        key(QtCore.Qt.Key_Escape)
        self.assertTrue(
            waitFor(lambda: not Gui.Control.activeDialog()), "the second Esc left the dialog open"
        )
        self.doc.recompute()
        self.assertEqual(fillet.Base[1], [first])

    def testEscInThe3DViewDisarms(self):
        """T5 from the 3D view: Esc there is the dialog's too; with a field armed it disarms the
        field and the edit stays."""
        box, fillet = self.newFillet()
        [field] = fields()
        self.arm(field, byFocus=True)
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        self.views = [
            w for w in mdi.subWindowList() if w.widget().metaObject().className() == "Gui::View3DInventor"
        ]
        self.assertTrue(focus(self.views[0].widget()))
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(field)), "Esc in the 3D view didn't disarm")
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "Esc in the 3D view closed the dialog")
        self.assertIsNotNone(Gui.getDocument(self.doc.Name).getInEdit(), "the edit was reset")

    # -- T6: Delete -----------------------------------------------------------------------------

    def testDeleteRemovesSelectedEntries(self):
        """T6: two of three entries selected, Delete: both go; OK makes one undo step, and undo
        brings them back."""
        box = self.box()
        names = TOP_FRONT.one(box.Shape) + BOTTOM_BACK.one(box.Shape) + VERTICAL.one(box.Shape)
        fillet = self.addFillet(box, names)
        undoCount = self.doc.UndoCount
        [field] = self.edit(fillet)
        self.assertEqual(texts(field), names)
        self.assertTrue(focus(entries(field)))
        clickRow(field, 0)
        clickRow(field, 2, QtCore.Qt.ControlModifier)
        self.assertEqual(len(entries(field).selectedItems()), 2)
        # a row click highlights without the selection: nothing for Std_Delete to take (3.1)
        self.assertEqual(Gui.Selection.getSelectionEx(self.doc.Name), [])

        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: texts(field) == names[1:2]), texts(field))
        self.assertEqual(fillet.Base[1], names[1:2])
        self.assertEqual(self.body.Group, [box, fillet])

        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        ok.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        self.assertEqual(self.doc.UndoCount, undoCount + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(fillet.Base[1], names)

    # -- T7: the field's own undo ---------------------------------------------------------------

    def testCtrlZStepsThroughThePicks(self):
        """T7: two picks, then Ctrl+Z twice and Ctrl+Y once with the focus in the field: the
        entries step back and forward, and Base follows."""
        box, fillet = self.newFillet()
        [field] = fields()
        self.arm(field, byFocus=True)
        [first] = TOP_FRONT.one(box.Shape)
        [second] = BOTTOM_BACK.one(box.Shape)
        self.pick(box, first)
        self.pick(box, second)
        self.assertEqual(fillet.Base[1], [first, second])
        self.assertTrue(focus(entries(field)))

        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: fillet.Base[1] == [first]), fillet.Base)
        self.assertEqual(texts(field), [first])
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: fillet.Base[1] == []), fillet.Base)
        key(QtCore.Qt.Key_Y, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: fillet.Base[1] == [first]), fillet.Base)
        self.assertEqual(texts(field), [first])
        self.assertTrue(Gui.Control.activeDialog(), "Ctrl+Z ended the edit")

    # -- T8, T9: states and the entry's actions ---------------------------------------------------

    def testBrokenEntryUsesACandidate(self):
        """T8: the Boss fillet: its entry is broken (red, its label red); Use lists the
        candidates, the 0.5 mm one first; using it makes the entry exact and the fillet computes
        on the block's front right edge."""
        pad, fillet = self.boss()
        [field] = self.edit(fillet)
        self.assertEqual(states(field), ["broken"])
        self.assertIn("missing", texts(field)[0])
        self.assertEqual(field.property("state"), "broken")
        [blockEdge] = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)

        menu = openMenu(field, 0)
        self.assertIsNotNone(menu, "no context menu")
        actions = menuActions(menu)
        self.assertIn("Use", actions)
        use = actions["Use"].menu()
        candidates = [a for a in use.actions() if not a.isSeparator()]
        self.assertTrue(candidates)
        self.assertTrue(candidates[0].text().startswith(blockEdge), candidates[0].text())
        candidates[0].trigger()
        menu.close()
        pump(0.3)

        self.assertTrue(waitFor(lambda: states(field) == ["exact"]), states(field))
        self.assertEqual(fillet.Base[1], [blockEdge])
        self.assertEqual(field.property("state"), "exact")
        self.assertVolume(fillet, 2000 - (1 - math.pi / 4) * 0.25**2 * 10)

    def testGuessedEntryIsAccepted(self):
        """T9: the redrawn fillet: its entry is guessed (yellow); Accept guess makes it exact and
        the reference report has nothing left for it."""
        pad, fillet, corner = self.redrawnFillet()
        [field] = self.edit(fillet)
        self.assertEqual(states(field), ["guessed"])
        self.assertEqual(texts(field), [corner])
        self.assertEqual(field.property("state"), "guessed")

        menu = openMenu(field, 0)
        self.assertIsNotNone(menu, "no context menu")
        actions = menuActions(menu)
        for name in ("Remove", "Accept guess", "Mark broken", "Re-pick"):
            self.assertIn(name, actions)
        actions["Accept guess"].trigger()
        menu.close()
        pump(0.3)

        self.assertTrue(waitFor(lambda: states(field) == ["exact"]), states(field))
        self.assertEqual(App.getReferenceReport(fillet), [])
        self.assertNotIn("Warning", fillet.State)

    # -- T10: one armed field at a time ---------------------------------------------------------

    def testDraftFacesAndNeutralPlane(self):
        """T10: the Draft's faces field and its neutral-plane field, one armed at a time. With
        the plane armed a pick goes to NeutralPlane only; a click into the faces field disarms
        the plane, and the next pick goes to Base only."""
        box, draft = self.draft()
        [faces, plane, line] = self.edit(draft, count=3)
        self.assertEqual(plane.objectName(), "fieldNeutralPlane")
        self.assertEqual(line.objectName(), "fieldPullDirection")
        self.assertIsNone(
            Gui.getMainWindow().findChild(QtWidgets.QAbstractButton, "buttonPlane"),
            "the Neutral Plane button is still there",
        )
        self.arm(faces, byFocus=True)
        self.arm(plane, byFocus=True)
        self.assertFalse(armed(faces), "two fields armed")
        self.assertFalse(armed(line))
        self.pick(box, self.top)
        self.assertEqual(draft.Base[1], [self.side])
        self.assertEqual(draft.NeutralPlane[1], [self.top])

        clickRow(faces, 0)
        self.assertTrue(waitFor(lambda: armed(faces)), "a click into the faces field didn't arm it")
        self.assertFalse(armed(plane), "the plane field stays armed")
        self.pick(box, self.back)
        self.assertEqual(draft.Base[1], [self.side, self.back])
        self.assertEqual(draft.NeutralPlane[1], [self.top])

    # -- T11: another document ------------------------------------------------------------------

    def testOtherDocumentRefused(self):
        """T11: an edge of another document's box: refused, the field unchanged, the reason in
        the status bar."""
        other = App.newDocument("OtherDocument", hidden=True)
        otherBox = other.addObject("Part::Box", "Box")
        other.recompute()
        box, fillet = self.newFillet()
        [field] = fields()
        self.arm(field, byFocus=False)
        Gui.Selection.addSelection(other.Name, otherBox.Name, "Edge1")
        pump(0.2)
        self.assertEqual(fillet.Base[1], [])
        self.assertEqual(texts(field), [])
        self.assertEqual(Gui.Selection.getSelectionEx(other.Name), [])
        self.assertIn("another document", statusText())

    # -- T12, T13: the References panel at the top ----------------------------------------------

    def redrawnDraft(self):
        """The redrawn pad and a draft on its front face with the bottom as the neutral plane:
        after the redraw both references are guesses."""
        body, pad = self.redrawnPad()
        front = face(normal=(0, -1, 0))
        bottom = face(normal=(0, 0, -1))
        draft = body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (pad, front.one(pad.Shape))
        draft.NeutralPlane = (pad, bottom.one(pad.Shape))
        draft.Angle = 2
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        self.redraw()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        return pad, draft

    def testDraftFieldsShowTheirStates(self):
        """3.3, 3.5 on single entries: after the redraw the draft's faces and neutral plane are
        guesses; each field shows its own (yellow, label coloured), and the References panel,
        with nothing left that no field shows, isn't added."""
        pad, draft = self.redrawnDraft()
        rows = {(e["property"], e["index"]) for e in App.getReferenceReport(draft)}
        self.assertIn(("Base", 0), rows)
        self.assertIn(("NeutralPlane", 0), rows)
        [faces, plane, line] = self.edit(draft, count=3)
        self.assertEqual(states(faces), ["guessed"])
        self.assertEqual(states(plane), ["guessed"])
        self.assertEqual(plane.property("state"), "guessed")
        self.assertEqual(states(line), [])
        self.assertTrue(texts(plane)[0].startswith(pad.Label + ":Face"), texts(plane))
        label = plane.findChild(QtWidgets.QLabel, "label")
        self.assertIn("color", label.styleSheet())
        tree = Gui.getMainWindow().findChild(QtWidgets.QTreeWidget, "references")
        self.assertTrue(tree is None or not tree.isVisible(), "the References panel is shown")

    def redrawnSecondPad(self):
        """The redrawn pad, and a second pad inside it, a square 2..4 x 2..4 from z = 0 up to its
        top face, along its vertical edge at (20, 0): after the redraw both are guesses. The face
        is in the up-to-face field; the edge only the References panel shows (the direction field
        is hidden)."""
        body, pad = self.redrawnPad()
        corner = edge("line", direction=Z, through=(20, 0, 0))
        top = face(normal=(0, 0, 1))
        square = models.sketch(self.doc, "Square", models.rectangle(2, 2, 4, 4), body)
        second = models.pad(body, square, 5, name="Second")
        second.Type = "UpToFace"
        second.UpToFace = (pad, top.one(pad.Shape))
        second.ReferenceAxis = (pad, corner.one(pad.Shape))
        self.doc.recompute()
        self.assertTrue(second.isValid(), second.getStatusString())
        self.assertAlmostEqual(second.Shape.Volume, 2000, places=3)
        self.redraw()
        self.assertTrue(second.isValid(), second.getStatusString())
        return pad, second

    def testPanelPickDisarmsTheField(self):
        """T12, 3.5: the References panel lists only the direction's edge (the up-to-face field
        shows UpToFace); its Re-pick, with the field armed, disarms the field."""
        pad, second = self.redrawnSecondPad()
        rows = {(e["property"], e["index"]) for e in App.getReferenceReport(second)}
        self.assertIn(("ReferenceAxis", 0), rows)
        [profile, field] = self.edit(second, count=2)
        self.assertEqual(field.objectName(), "fieldUpToFace")
        tree = Gui.getMainWindow().findChild(QtWidgets.QTreeWidget, "references")
        self.assertIsNotNone(tree, "no References panel")
        self.assertTrue(tree.isVisible())
        listed = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
        self.assertEqual(listed, ["ReferenceAxis[0]"])

        self.arm(field, byFocus=True)
        tree.setCurrentItem(tree.topLevelItem(0))
        pick = Gui.getMainWindow().findChild(QtWidgets.QPushButton, "buttonPick")
        pick.click()
        pump()
        self.assertTrue(pick.isChecked())
        self.assertFalse(armed(field), "the panel's Re-pick left the field armed")

    def testPanelLeftOutWhenTheFieldsShowEverything(self):
        """T13, Q3 (a): the redrawn fillet's only row is in its field: no References panel."""
        pad, fillet, corner = self.redrawnFillet()
        [field] = self.edit(fillet)
        pump(0.3)
        self.assertEqual(states(field), ["guessed"])
        tree = Gui.getMainWindow().findChild(QtWidgets.QTreeWidget, "references")
        self.assertTrue(tree is None or not tree.isVisible(), "the References panel is shown")

    # -- T20: document undo during the edit ------------------------------------------------------

    def testDocumentUndoRefreshesTheField(self):
        """T20: a pick, then the document's undo with the dialog open: the field shows Base as
        the undo left it."""
        box = self.box()
        [first] = TOP_FRONT.one(box.Shape)
        [second] = BOTTOM_BACK.one(box.Shape)
        fillet = self.addFillet(box, [first])
        [field] = self.edit(fillet)
        self.arm(field, byFocus=False)
        self.pick(box, second)
        self.assertEqual(texts(field), [first, second])

        Gui.runCommand("Std_Undo")
        self.assertTrue(waitFor(lambda: fillet.Base[1] == [first]), fillet.Base)
        self.assertTrue(waitFor(lambda: texts(field) == [first]), texts(field))

    # -- PR 140 review round ------------------------------------------------------------------------

    def edgeColours(self, obj):
        """The colours the view provider draws obj's edges in: its line material, one colour per
        edge while a highlight is on."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoMaterial.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(obj.ViewObject.RootNode)
        count = len(obj.Shape.Edges)
        for path in search.getPaths():
            material = path.getTail()
            if material.diffuseColor.getNum() == count:
                return [tuple(round(v, 2) for v in c.getValue()) for c in material.diffuseColor.getValues()]
        return []

    def testHighlightColoursOnlyTheEntries(self):
        """Review 1: a pick colours that edge only, in the entries' colour; the current entry is
        the only one in the current colour. No edge takes the highlighter's whole-object colour
        (purple), which it gives every edge when handed an empty list."""
        box, fillet = self.newFillet()
        [field] = fields()
        self.assertTrue(waitFor(lambda: armed(field)))
        [first] = TOP_FRONT.one(box.Shape)
        self.pick(box, first)
        colours = self.edgeColours(box)
        self.assertEqual(len(colours), 12, "no per-edge colours on the base")
        self.assertNotIn(PURPLE, colours)
        self.assertEqual(colours.count(MAGENTA), 1)
        self.assertEqual(colours[int(first[4:]) - 1], MAGENTA)

        clickRow(field, 0)
        colours = self.edgeColours(box)
        self.assertNotIn(PURPLE, colours)
        self.assertNotIn(MAGENTA, colours)
        self.assertEqual(colours.count(CURRENT), 1)

    def testGuessStaysGuessedAfterAnotherPick(self):
        """Review 2: the redrawn fillet's guessed entry stays guessed (its record kept) when
        another edge is picked, when that one is deleted again, and through the field's undo."""
        pad, fillet, corner = self.redrawnFillet()
        [field] = self.edit(fillet)
        self.assertEqual(states(field), ["guessed"])
        self.arm(field, byFocus=True)
        [other] = edge("line", direction=Z, through=(0, 0, 0)).one(pad.Shape)
        self.pick(pad, other)
        self.assertTrue(waitFor(lambda: states(field) == ["guessed", "exact"]), states(field))
        self.assertIn(("Base", 0), {(e["property"], e["index"]) for e in App.getReferenceReport(fillet)})

        self.assertTrue(focus(entries(field)))
        clickRow(field, 1)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: states(field) == ["guessed"]), states(field))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: states(field) == ["guessed", "exact"]), states(field))

    def testFieldUndoStepsBackOverAUse(self):
        """Review 3: the Boss fillet, a second edge picked, then the broken entry repaired with
        Use: Ctrl+Z takes back the Use only (the entry broken again, the pick kept), not the
        pick with it."""
        pad, fillet = self.boss()
        [field] = self.edit(fillet)
        self.arm(field, byFocus=False)
        [topBack] = edge("line", direction=X, through=(0, 10, 10)).one(pad.Shape)
        self.pick(pad, topBack)
        self.assertEqual(states(field), ["broken", "exact"])
        menu = openMenu(field, 0)
        use = menuActions(menu)["Use"].menu()
        [a for a in use.actions() if not a.isSeparator()][0].trigger()
        menu.close()
        pump(0.3)
        self.assertTrue(waitFor(lambda: states(field) == ["exact", "exact"]), states(field))

        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: states(field) == ["broken", "exact"]), states(field))
        self.assertEqual(len(fillet.Base[1]), 2)
        self.assertEqual(fillet.Base[1][1], topBack)

    def testDocumentUndoEndsTheFieldUndo(self):
        """Review 3: two picks, then the document's undo: Base is back to the one edge, and the
        field's Ctrl+Z has nothing left to write back."""
        box = self.box()
        [first] = TOP_FRONT.one(box.Shape)
        [second] = BOTTOM_BACK.one(box.Shape)
        [third] = VERTICAL.one(box.Shape)
        fillet = self.addFillet(box, [first])
        [field] = self.edit(fillet)
        self.arm(field, byFocus=False)
        self.pick(box, second)
        self.pick(box, third)
        Gui.runCommand("Std_Undo")
        self.assertTrue(waitFor(lambda: texts(field) == [first]), texts(field))
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        pump(0.3)
        self.assertEqual(fillet.Base[1], [first])
        self.assertEqual(texts(field), [first])

    def testAddAllEdgesShowsThemAndUndoes(self):
        """B5, review 3: Add All Edges (Ctrl+Shift+A in the field) lists all twelve edges; the
        field's Ctrl+Z takes them back to the one edge."""
        box = self.box()
        [first] = TOP_FRONT.one(box.Shape)
        fillet = self.addFillet(box, [first])
        [field] = self.edit(fillet)
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_A, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
        self.assertTrue(waitFor(lambda: len(texts(field)) == 12), texts(field))
        self.assertEqual(len(fillet.Base[1]), 12)
        self.assertEqual(texts(field)[0], first)
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: fillet.Base[1] == [first]), fillet.Base)
        self.assertEqual(texts(field), [first])

    def referencesTree(self):
        return Gui.getMainWindow().findChild(QtWidgets.QTreeWidget, "references")

    def listedRows(self):
        tree = self.referencesTree()
        if tree is None or not tree.isVisible():
            return None
        return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]

    def testDisabledFieldLeavesItsRowsToThePanel(self):
        """Review 5: the redrawn fillet's guessed row is in its field, no References panel; with
        Use All Edges on the field can't act on it, so the panel lists it; off again, it goes."""
        pad, fillet, corner = self.redrawnFillet()
        [field] = self.edit(fillet)
        self.assertIsNone(self.listedRows())
        useAll = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "checkBoxUseAllEdges")
        useAll.setChecked(True)
        self.assertTrue(waitFor(lambda: self.listedRows() == ["Base[0]"]), self.listedRows())
        useAll.setChecked(False)
        self.assertTrue(waitFor(lambda: self.listedRows() is None), self.listedRows())

    def testHiddenPanelComesBackOnRefresh(self):
        """Review 6: the second pad with its direction's guess accepted: only the up-to-face is
        left, in its field, so no References panel. The document's undo takes the acceptance
        back: the panel comes back with the direction."""
        pad, second = self.redrawnSecondPad()
        self.doc.openTransaction("Accept")
        App.acceptReference(second, "ReferenceAxis", 0)
        self.doc.commitTransaction()
        self.doc.recompute()
        rows = {(e["property"], e["index"]) for e in App.getReferenceReport(second)}
        self.assertEqual(rows, {("UpToFace", 0)})
        [profile, field] = self.edit(second, count=2)
        self.assertIsNone(self.listedRows())
        Gui.runCommand("Std_Undo")
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: self.listedRows() == ["ReferenceAxis[0]"]), self.listedRows())

    # -- ops#162 B1, B3; the other dress-up panels -------------------------------------------------

    def testNewDraftArmsItsFaces(self):
        """B1: a new draft (nothing selected) opens with its faces field armed; a face pick
        writes Base."""
        box = self.box()
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        Gui.runCommand("PartDesign_Draft")
        self.assertTrue(waitFor(lambda: len(fields()) >= 1), "the draft's reference field")
        settle()
        draft = self.doc.getObject("Draft")
        field = fields()[0]
        self.assertTrue(waitFor(lambda: armed(field)), "the new draft's faces field isn't armed")
        [side] = face(normal=(0, -1, 0)).one(box.Shape)
        self.pick(box, side)
        self.assertEqual(draft.Base[1], [side])

    def testDraftAngleEndsThePlanePick(self):
        """B3: the plane field armed, an angle edit disarms it: its gate goes (a vertex can be
        selected again) and NeutralPlane takes no pick."""
        box, draft = self.draft()
        bottom, top = self.bottom, self.top
        [faces, plane, line] = self.edit(draft, count=3)
        self.arm(plane, byFocus=False)
        angle = Gui.getMainWindow().findChild(QtWidgets.QWidget, "draftAngle")
        angle.setProperty("rawValue", 3.0)
        pump(0.3)
        self.assertAlmostEqual(draft.Angle.Value, 3.0)
        Gui.Selection.addSelection(self.doc.Name, box.Name, "Vertex1")
        pump(0.1)
        self.assertEqual(
            [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx(self.doc.Name)],
            [(box.Name, ["Vertex1"])],
            "the plane's gate stayed",
        )
        Gui.Selection.clearSelection()
        self.pick(box, top)
        self.assertEqual(draft.NeutralPlane[1], [bottom])

    def emptyDressUp(self, typeName, name):
        box = self.box()
        feature = self.body.newObject(typeName, name)
        feature.Base = (box, [])
        self.doc.recompute()
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        self.assertTrue(waitFor(lambda: len(fields()) == 1), "the dialog's reference field")
        settle()
        [field] = fields()
        self.assertTrue(waitFor(lambda: armed(field)), f"the new {name}'s field isn't armed")
        return box, feature, field

    def testChamferField(self):
        """A new chamfer (size 1) arms its field; an edge pick writes Base and takes a prism of
        1 x 1 / 2 x 10 off the box."""
        box, chamfer, field = self.emptyDressUp("PartDesign::Chamfer", "Chamfer")
        chamfer.Size = 1
        [first] = TOP_FRONT.one(box.Shape)
        self.pick(box, first)
        self.assertEqual(chamfer.Base[1], [first])
        self.assertEqual(texts(field), [first])
        self.assertVolume(chamfer, 1000 - 5)

    def testThicknessField(self):
        """A new thickness (1, inward) arms its field; a pick of the top face writes Base and
        hollows the box: 1000 - 8 x 8 x 9."""
        box, thickness, field = self.emptyDressUp("PartDesign::Thickness", "Thickness")
        thickness.Value = 1
        [top] = face(normal=(0, 0, 1)).one(box.Shape)
        self.pick(box, top)
        self.assertEqual(thickness.Base[1], [top])
        self.assertEqual(texts(field), [top])
        self.assertVolume(thickness, 1000 - 8 * 8 * 9)

    def testDefeaturingField(self):
        """A new defeaturing arms its field; a face pick writes Base."""
        box, defeaturing, field = self.emptyDressUp("PartDesign::Defeaturing", "Defeaturing")
        [top] = face(normal=(0, 0, 1)).one(box.Shape)
        self.pick(box, top)
        self.assertEqual(defeaturing.Base[1], [top])
        self.assertEqual(texts(field), [top])
    # -- W2: single-entry fields, Draft (T1-T5 variants, B4) ---------------------------------------

    def draftPlanePicksReplace(self, byFocus):
        """T1, T2 for a single entry: the neutral plane, armed, takes a pick of the top face in
        place of the bottom (the draft pivots at the other end: the same wedge, the other way);
        the same pick again changes nothing, and the field stays armed."""
        box, draft = self.draft()
        bottomVolume = draft.Shape.Volume
        [faces, plane, line] = self.edit(draft, count=3)
        self.assertEqual(texts(plane), [f"{box.Label}:{self.bottom}"])
        self.assertFalse(armed(plane), "a complete draft opens with its plane armed")
        self.arm(plane, byFocus)

        self.pick(box, self.top)
        self.assertEqual(draft.NeutralPlane[1], [self.top])
        self.assertEqual(texts(plane), [f"{box.Label}:{self.top}"])
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        self.assertAlmostEqual(abs(draft.Shape.Volume - 1000), DRAFT_CHANGE, places=3)
        self.assertAlmostEqual(draft.Shape.Volume + bottomVolume, 2000, places=3)

        self.pick(box, self.top)
        self.assertEqual(draft.NeutralPlane[1], [self.top])
        self.assertEqual(texts(plane), [f"{box.Label}:{self.top}"])
        self.assertTrue(armed(plane), "a pick disarmed the field")
        self.assertEqual(draft.Base[1], [self.side])
        self.assertIsNone(draft.PullDirection)

    def testDraftPlanePicksReplace(self):
        self.draftPlanePicksReplace(byFocus=True)

    def testDraftPlanePicksReplaceArmedByProperty(self):
        self.draftPlanePicksReplace(byFocus=False)

    def testDraftAngleDisarmsThePlane(self):
        """T3: the angle takes the focus: the plane field disarms, a pick leaves it alone."""
        box, draft = self.draft()
        [faces, plane, line] = self.edit(draft, count=3)
        self.arm(plane, byFocus=True)
        angle = Gui.getMainWindow().findChild(QtWidgets.QWidget, "draftAngle")
        self.assertTrue(focus(angle), "the angle doesn't take the focus")
        self.assertTrue(waitFor(lambda: not armed(plane)), "still armed with the angle focused")
        self.pick(box, self.top)
        self.assertEqual(draft.NeutralPlane[1], [self.bottom])

    def testDraftPlaneStaysArmedIn3DView(self):
        """T4: the focus goes to the 3D view: the plane field stays armed and takes the pick."""
        box, draft = self.draft()
        [faces, plane, line] = self.edit(draft, count=3)
        self.arm(plane, byFocus=True)
        self.assertTrue(focus(views3D()[0]), "the 3D view doesn't take the focus")
        pump(0.2)
        self.assertTrue(armed(plane), "the 3D view's focus disarmed the field")
        self.pick(box, self.top)
        self.assertEqual(draft.NeutralPlane[1], [self.top])

    def testDraftEscDisarmsThePlaneThenCancels(self):
        """T5: Esc disarms the plane field and the dialog stays; the next Esc cancels, and the
        neutral plane is the bottom again."""
        box, draft = self.draft()
        [faces, plane, line] = self.edit(draft, count=3)
        self.arm(plane, byFocus=True)
        self.pick(box, self.top)
        self.assertEqual(draft.NeutralPlane[1], [self.top])
        self.assertTrue(focus(entries(plane)))
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(plane)), "Esc didn't disarm the field")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "the first Esc closed the dialog")
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(
            waitFor(lambda: not Gui.Control.activeDialog()), "the second Esc left the dialog open"
        )
        self.doc.recompute()
        self.assertEqual(draft.NeutralPlane[1], [self.bottom])

    def testDraftDisarmedPlaneLeavesNoGate(self):
        """B4: the neutral plane disarmed (Esc), nothing of its pick stays: a vertex, which its
        gate refuses, can be selected again, what the field showed is as before, and a face pick
        leaves NeutralPlane alone."""
        box, draft = self.draft()
        [faces, plane, line] = self.edit(draft, count=3)
        shown = (box.ViewObject.Visibility, draft.ViewObject.Visibility)
        self.arm(plane, byFocus=True)
        Gui.Selection.addSelection(self.doc.Name, box.Name, "Vertex1")
        pump(0.1)
        self.assertEqual(selected(self.doc), [], "the armed plane's gate let a vertex through")
        self.assertTrue(focus(entries(plane)))
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(plane)), "Esc didn't disarm the field")

        Gui.Selection.addSelection(self.doc.Name, box.Name, "Vertex1")
        pump(0.1)
        self.assertEqual(selected(self.doc), [(box.Name, ["Vertex1"])], "a gate stayed")
        self.assertEqual((box.ViewObject.Visibility, draft.ViewObject.Visibility), shown)
        Gui.Selection.clearSelection()
        self.pick(box, self.top)
        self.assertEqual(draft.NeutralPlane[1], [self.bottom])

    # -- W2: Pad/Pocket up to face (T1-T5 variants) ------------------------------------------------

    def padModeBox(self):
        return Gui.getMainWindow().findChild(QtWidgets.QComboBox, "changeMode")

    def testPadUpToFaceArmsAndPicksReplace(self):
        """T1, T2: a pad switched to Up to face arms its face field (empty); a pick of the plane
        at 15 pads 5 high (20 mm^3), the plane at 17 replaces it (28 mm^3), the same pick again
        changes nothing and the field stays armed."""
        box, pad = self.padOnBox(toFace=False)
        self.edit(pad, count=1)
        self.assertIsNone(Gui.getMainWindow().findChild(QtWidgets.QAbstractButton, "buttonFace"))
        self.padModeBox().setCurrentIndex(3)
        pump(0.2)
        field = findField("fieldUpToFace")
        self.assertIsNotNone(field)
        self.assertTrue(
            waitFor(lambda: field.isVisible() and armed(field)), "the face field isn't armed"
        )

        self.pick(self.low, "")
        self.assertLink(pad.UpToFace, self.low, [])
        self.assertEqual(texts(field), [self.low.Label])
        self.assertVolume(pad, 1020)
        self.pick(self.high, "")
        self.assertLink(pad.UpToFace, self.high, [])
        self.assertVolume(pad, 1028)
        self.pick(self.high, "")
        self.assertLink(pad.UpToFace, self.high, [])
        self.assertTrue(armed(field))
        self.assertEqual(texts(field), [self.high.Label])

    def testPadOffsetDisarmsTheFace(self):
        """T3: the offset takes the focus: the face field disarms, a pick leaves UpToFace."""
        box, pad = self.padOnBox()
        [profile, field] = self.edit(pad, count=2)
        self.assertFalse(armed(field), "a complete pad opens armed")
        self.arm(field, byFocus=True)
        offset = Gui.getMainWindow().findChild(QtWidgets.QWidget, "offsetEdit")
        self.assertTrue(focus(offset), "the offset doesn't take the focus")
        self.assertTrue(waitFor(lambda: not armed(field)), "still armed with the offset focused")
        self.pick(self.high, "")
        self.assertLink(pad.UpToFace, self.low, [])

    def testPadFaceStaysArmedIn3DView(self):
        """T4: the face field stays armed with the focus in the 3D view, and takes the pick."""
        box, pad = self.padOnBox()
        [profile, field] = self.edit(pad, count=2)
        self.arm(field, byFocus=False)
        self.assertTrue(focus(views3D()[0]))
        pump(0.2)
        self.assertTrue(armed(field), "the 3D view's focus disarmed the field")
        self.pick(self.high, "")
        self.assertLink(pad.UpToFace, self.high, [])
        self.assertVolume(pad, 1028)

    def testPadEscDisarmsThenCancels(self):
        """T5: Esc disarms the face field, the next Esc cancels: UpToFace is the lower plane."""
        box, pad = self.padOnBox()
        # The edit opened as a double click opens it, in a command Cancel aborts (the Pad's panel
        # opens none of its own)
        self.doc.openTransaction("Edit Pad")
        [profile, field] = self.edit(pad, count=2)
        self.arm(field, byFocus=True)
        self.pick(self.high, "")
        self.assertLink(pad.UpToFace, self.high, [])
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(field)), "Esc didn't disarm the field")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "the first Esc closed the dialog")
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(
            waitFor(lambda: not Gui.Control.activeDialog()), "the second Esc left the dialog open"
        )
        self.doc.recompute()
        self.assertLink(pad.UpToFace, self.low, [])
        self.assertAlmostEqual(pad.Shape.Volume, 1020, places=3)

    # -- W2: up to shape (T18, B2), start reference, direction --------------------------------------

    def testUpToShapeRemovesTheSelectedFaces(self):
        """T18, B2: up to three faces of the shape; the first and the third selected, Delete:
        exactly those two go, and the pad stops at the middle face (120 mm^3)."""
        pad, target = self.upToShapePad(["Face1", "Face2", "Face3"])
        self.assertAlmostEqual(pad.Shape.Volume, 80, places=3)
        [profile, shape, faces] = self.edit(pad, count=3)
        self.assertEqual(shape.objectName(), "fieldUpToShape")
        self.assertEqual(faces.objectName(), "fieldUpToShapeFaces")
        self.assertEqual(texts(shape), [target.Label])
        self.assertEqual(texts(faces), ["Face1", "Face2", "Face3"])
        self.assertTrue(focus(entries(faces)))
        clickRow(faces, 0)
        clickRow(faces, 2, QtCore.Qt.ControlModifier)
        self.assertEqual(len(entries(faces).selectedItems()), 2)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: texts(faces) == ["Face2"]), texts(faces))
        self.assertEqual(len(pad.UpToShape), 1)
        self.assertLink(pad.UpToShape[0], target, ["Face2"])
        self.assertVolume(pad, 120)

    def testUpToShapeFacesToggle(self):
        """The faces field is a list: a pick of the shape's top face adds it, a pick of the
        lowest removes it; the pad follows (80, then 120 mm^3)."""
        pad, target = self.upToShapePad(["Face1", "Face2"])
        [profile, shape, faces] = self.edit(pad, count=3)
        self.arm(faces, byFocus=False)
        self.pick(target, "Face3")
        self.assertEqual(texts(faces), ["Face1", "Face2", "Face3"])
        self.assertVolume(pad, 80)
        self.pick(target, "Face1")
        self.assertEqual(texts(faces), ["Face2", "Face3"])
        self.assertVolume(pad, 120)

    def testUpToShapePickTakesTheObject(self):
        """The shape field takes a whole object: a pick of one face of the shape links the
        shape, all its faces (the pad stops at the lowest: 80 mm^3)."""
        pad, target = self.upToShapePad([])
        pad.UpToShape = None
        self.doc.recompute()
        [profile, shape] = self.edit(pad, count=2)
        self.assertEqual(shape.objectName(), "fieldUpToShape")
        self.arm(shape, byFocus=True)
        self.pick(target, "Face2")
        self.assertEqual(len(pad.UpToShape), 1)
        self.assertLink(pad.UpToShape[0], target, [])
        self.assertEqual(texts(shape), [target.Label])
        self.assertVolume(pad, 80)

    def testStartReferenceField(self):
        """The start reference, switched on, arms its field; a datum plane at z = 3 starts the
        pad there, one at z = 4 replaces it."""
        body = models.body(self.doc)
        square = models.sketch(self.doc, "Square", models.rectangle(2, 2, 4, 4), body)
        pad = models.pad(body, square, 5)
        lower = self.datumPlane(body, "Lower", 3)
        upper = self.datumPlane(body, "Upper", 4)
        self.doc.recompute()
        self.edit(pad, count=1)
        start = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "startMode")
        start.setCurrentIndex(2)
        pump(0.2)
        field = findField("fieldStartReference")
        self.assertIsNotNone(field)
        self.assertTrue(
            waitFor(lambda: field.isVisible() and armed(field)), "the start field isn't armed"
        )
        self.pick(lower, "")
        self.assertLink(pad.StartReference, lower, [])
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, 3, places=4)
        self.pick(upper, "")
        self.assertLink(pad.StartReference, upper, [])
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, 4, places=4)

    def testDirectionSelectReferenceArmsAField(self):
        """The direction box's "Select reference" arms the hidden direction field: a pick of
        the box's vertical edge becomes ReferenceAxis and the box's entry, and the field
        disarms (one pick)."""
        box, pad = self.padOnBox(toFace=False)
        self.edit(pad, count=1)
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "directionCB")
        combo.setCurrentIndex(1)
        combo.activated.emit(1)
        pump(0.2)
        field = findField("fieldReferenceAxis")
        self.assertIsNotNone(field)
        self.assertFalse(field.isVisible())
        self.assertTrue(waitFor(lambda: armed(field)), "the direction field isn't armed")
        [vertical] = VERTICAL.one(box.Shape)
        self.pick(box, vertical)
        self.assertLink(pad.ReferenceAxis, box, [vertical])
        self.assertTrue(waitFor(lambda: not armed(field)), "the direction field stays armed")
        self.assertIn(vertical, combo.currentText())
        self.assertVolume(pad, 1012)

    # -- Records kept across writes (PR 140 verification) ------------------------------------------

    def redrawnTwoEdgeFillet(self):
        """The redrawn pad and a fillet on two vertical edges, (0, 0) first and (20, 0) second:
        after the redraw both are guesses."""
        body, pad = self.redrawnPad()
        first = edge("line", direction=Z, through=(0, 0, 0))
        corner = edge("line", direction=Z, through=(20, 0, 0))
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, first.one(pad.Shape) + corner.one(pad.Shape))
        fillet.Radius = 1
        self.doc.recompute()
        self.redraw()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        return pad, fillet

    def testGuessMovesWithItsEntry(self):
        """The entry before a guessed one deleted: the second guess moves up with its entry
        (index 0 now) and stays guessed; the reference report has it at its new index only."""
        pad, fillet = self.redrawnTwoEdgeFillet()
        [field] = self.edit(fillet)
        self.assertEqual(states(field), ["guessed", "guessed"])
        second = fillet.Base[1][1]
        self.assertTrue(focus(entries(field)))
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: states(field) == ["guessed"]), states(field))
        self.assertEqual(fillet.Base[1], [second])
        rows = {(e["property"], e["index"]) for e in App.getReferenceReport(fillet)}
        self.assertEqual(rows, {("Base", 0)})

    def testMarkBrokenSurvivesAPick(self):
        """Mark broken on the guessed entry, then another edge picked: the rejection stays (the
        entry broken), not dropped by the write."""
        pad, fillet, corner = self.redrawnFillet()
        [field] = self.edit(fillet)
        menu = openMenu(field, 0)
        menuActions(menu)["Mark broken"].trigger()
        menu.close()
        pump(0.3)
        self.assertTrue(waitFor(lambda: states(field) == ["broken"]), states(field))
        self.arm(field, byFocus=False)
        [other] = edge("line", direction=Z, through=(0, 0, 0)).one(pad.Shape)
        self.pick(pad, other)
        self.assertTrue(waitFor(lambda: states(field) == ["broken", "exact"]), states(field))

    # -- PR 142 review round ------------------------------------------------------------------------

    def testPickAfterAnInsertKeepsTheCandidates(self):
        """Finding 1: the Boss fillet (its entry broken, with candidates), a pocket inserted
        before it while it had no shape, without the solver: Body.insertObject can't relink Base
        (ops#82), so BaseFeature is the pocket and Base still names the pad; the dialog can't
        move Base onto the pocket either (the broken entry resolves to nothing there). Another
        edge picked: the broken entry keeps its mapped name and its candidates (Use)."""
        pad, fillet = self.boss()
        body = pad.getParent()
        notch = models.sketch(self.doc, "Notch", models.rectangle(5, 3, 7, 5), body, z=10)
        pocket = self.doc.addObject("PartDesign::Pocket", "Pocket")
        self.doc.ReferenceSolver = False
        body.insertObject(pocket, pad, True)
        self.doc.ReferenceSolver = True
        pocket.Profile = notch
        pocket.Length = 2
        self.doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertEqual(fillet.BaseFeature, pocket)
        self.assertEqual(fillet.Base[0], pad)
        [field] = self.edit(fillet)
        self.assertEqual(fillet.Base[0], pad)
        self.assertEqual(states(field), ["broken"])
        menu = openMenu(field, 0)
        self.assertIn("Use", menuActions(menu))
        menu.close()
        pump()

        self.arm(field, byFocus=False)
        [other] = edge("line", direction=Z, through=(0, 0, 0)).one(pocket.Shape)
        self.pick(pocket, other)
        self.assertTrue(waitFor(lambda: len(states(field)) == 2), texts(field))
        self.assertEqual(states(field), ["broken", "exact"])
        menu = openMenu(field, 0)
        self.assertIn("Use", menuActions(menu), "the broken entry lost its candidates")
        menu.close()
        pump()

    def testHiddenFieldLeavesItsRowsToThePanel(self):
        """Finding 2: the second pad's up-to-face is a guess, in its field; the pad switched to
        a length hides the field, and the References panel lists UpToFace again."""
        pad, second = self.redrawnSecondPad()
        [profile, field] = self.edit(second, count=2)
        self.assertEqual(field.objectName(), "fieldUpToFace")
        self.assertEqual(self.listedRows(), ["ReferenceAxis[0]"])
        self.padModeBox().setCurrentIndex(0)
        pump(0.2)
        self.assertFalse(field.isVisible())
        self.assertTrue(
            waitFor(lambda: "UpToFace[0]" in (self.listedRows() or [])), self.listedRows()
        )
        self.padModeBox().setCurrentIndex(3)
        pump(0.2)
        self.assertTrue(
            waitFor(lambda: self.listedRows() == ["ReferenceAxis[0]"]), self.listedRows()
        )

    def testExpandedFromKeptAcrossAPick(self):
        """`from` survives a write that changes the count: a fillet on the block's front top
        edge, a rib moved across it (the reference expands into two pieces); in the dialog the
        back top edge is added. The rib moved back, the pieces merge into the one edge again,
        which needs their `from`: two entries, the front edge and the back one."""
        self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = True
        body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10)
        ribSketch = models.sketch(self.doc, "RibSketch", models.rectangle(8, 3, 12, 7), body)
        rib = models.pad(body, ribSketch, 12, name="Rib")
        self.doc.recompute()
        front = edge("line", direction=X, through=(0, 0, 10))
        back = edge("line", direction=X, through=(0, 10, 10))
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, front.one(rib.Shape))
        fillet.Radius = 1
        self.doc.recompute()
        models.moveRectangle(ribSketch, 8, -3, 12, 3)
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(len(fillet.Base[1]), 2)

        [field] = self.edit(fillet)
        self.assertEqual(len(entries(field).findItems("*", QtCore.Qt.MatchWildcard)), 2)
        self.arm(field, byFocus=False)
        [backEdge] = back.one(rib.Shape)
        self.pick(rib, backEdge)
        self.assertTrue(waitFor(lambda: len(fillet.Base[1]) == 3), fillet.Base)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        pump()

        models.moveRectangle(ribSketch, 8, 3, 12, 7)
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(
            sorted(fillet.Base[1]), sorted(front.one(rib.Shape) + back.one(rib.Shape))
        )

    def testSingleEntryCtrlZ(self):
        """Ctrl+Z / Ctrl+Y in a single-entry field: the up-to-face steps back to the lower plane
        and forward to the higher one."""
        box, pad = self.padOnBox()
        [profile, field] = self.edit(pad, count=2)
        self.arm(field, byFocus=True)
        self.pick(self.high, "")
        self.assertLink(pad.UpToFace, self.high, [])
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: pad.UpToFace[0] == self.low), pad.UpToFace)
        self.assertEqual(texts(field), [self.low.Label])
        key(QtCore.Qt.Key_Y, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: pad.UpToFace[0] == self.high), pad.UpToFace)
        self.assertVolume(pad, 1028)

    def testTypeSwitchWhileArmedRemovesTheGate(self):
        """The face field armed, the pad switched to a length: the field disarms, its gate goes
        (a pick of the plane selects it), UpToFace stays."""
        box, pad = self.padOnBox()
        [profile, field] = self.edit(pad, count=2)
        self.arm(field, byFocus=False)
        self.padModeBox().setCurrentIndex(0)
        pump(0.2)
        self.assertFalse(armed(field))
        self.pick(self.high, "")
        self.assertEqual(selected(self.doc), [(self.high.Name, [])])
        self.assertLink(pad.UpToFace, self.low, [])

    def choose(self, combo, index):
        """An entry of a combo box chosen through its popup, as a user does."""
        combo.showPopup()
        pump(0.2)
        view = combo.view()
        rect = view.visualRect(view.model().index(index, 0))
        QtTest.QTest.mouseClick(
            view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center()
        )
        pump(0.2)

    def testDirectionFieldDisarmsThroughThePopup(self):
        """The direction box's "Select reference" chosen in its popup arms the hidden field;
        the sketch normal chosen there again disarms it without a pick."""
        box, pad = self.padOnBox(toFace=False)
        self.edit(pad, count=1)
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "directionCB")
        self.choose(combo, 1)
        field = findField("fieldReferenceAxis")
        self.assertTrue(waitFor(lambda: armed(field)), "the direction field isn't armed")
        self.choose(combo, 0)
        self.assertTrue(waitFor(lambda: not armed(field)), "the direction field stays armed")
        self.assertEqual(combo.currentIndex(), 0)
        [vertical] = VERTICAL.one(box.Shape)
        self.pick(box, vertical)
        self.assertNotEqual(pad.ReferenceAxis[1] if pad.ReferenceAxis else [], [vertical])
        self.assertVolume(pad, 1012)
    # -- W3: the Pad's profile and its regions (T14-T16) ----------------------------------------

    def regionsPad(self, allowMultiFace=True, makeInternals=True):
        """The Regions model, padded 5 from the whole sketch; returns the pad, the sketch and its
        regions by name (found by their areas): "A" A minus the disk, "disk", "B"."""
        body = models.body(self.doc)
        geometry = (
            models.rectangle(0, 0, 20, 10)
            + [models.circle(10, 5, 2)]
            + models.rectangle(30, 0, 40, 10)
        )
        sketch = models.sketch(self.doc, "Regions", geometry, body)
        sketch.MakeInternals = True
        pad = models.pad(body, sketch, 5)
        pad.AllowMultiFace = allowMultiFace
        self.doc.recompute()
        regions = {}
        for i, f in enumerate(sketch.InternalShape.Faces):
            for name, area in (("A", 200 - 4 * math.pi), ("disk", 4 * math.pi), ("B", 100)):
                if abs(f.Area - area) < 1e-6:
                    regions[name] = "InternalFace%d" % (i + 1)
        self.assertEqual(sorted(regions), ["A", "B", "disk"], regions)
        if not makeInternals:
            sketch.MakeInternals = False
            self.doc.recompute()
        self.assertVolume(pad, WHOLE_SKETCH)
        return pad, sketch, regions

    def pickRegion(self, sketch, region):
        """A region picked in the 3D view, through the body as the view gives it."""
        Gui.Selection.addSelection(self.doc.Name, "Body", sketch.Name + "." + region)
        pump(0.2)

    def profileRegions(self, byFocus):
        """T14: the profile field shows the whole sketch; region B picked: 500 mm^3 and
        AllowMultiFace set; the disk added: 500 + 20 pi; B picked again goes: 20 pi; the disk
        picked again, the last region, leaves the whole sketch."""
        pad, sketch, regions = self.regionsPad()
        [field] = self.edit(pad)
        self.assertEqual(field.objectName(), "fieldProfile")
        self.assertFalse(armed(field), "a complete pad opens armed")
        self.assertEqual(texts(field), ["Regions (whole)"])
        self.arm(field, byFocus)

        self.pickRegion(sketch, regions["B"])
        self.assertEqual(pad.Profile[1], [regions["B"]])
        self.assertTrue(pad.AllowMultiFace)
        self.assertEqual(texts(field), ["Regions:" + regions["B"]])
        self.assertVolume(pad, 500)
        self.pickRegion(sketch, regions["disk"])
        self.assertEqual(pad.Profile[1], [regions["B"], regions["disk"]])
        self.assertVolume(pad, 500 + 20 * math.pi)
        self.pickRegion(sketch, regions["B"])
        self.assertEqual(pad.Profile[1], [regions["disk"]])
        self.assertVolume(pad, 20 * math.pi)
        self.pickRegion(sketch, regions["disk"])
        self.assertEqual(pad.Profile, (sketch, []))
        self.assertEqual(texts(field), ["Regions (whole)"])
        self.assertTrue(armed(field))
        self.assertVolume(pad, WHOLE_SKETCH)

    def testProfileRegionsPickAndRemove(self):
        self.profileRegions(byFocus=True)

    def testProfileRegionsPickAndRemoveArmedByProperty(self):
        self.profileRegions(byFocus=False)

    def testProfileAllRegionsFillTheHole(self):
        """5.1: all three regions are not the whole sketch: A minus the disk and the disk fill
        A's hole (1000 mm^3 with B: 1500)."""
        pad, sketch, regions = self.regionsPad()
        [field] = self.edit(pad)
        self.arm(field, byFocus=False)
        for name in ("A", "disk", "B"):
            self.pickRegion(sketch, regions[name])
        self.assertEqual(len(entries(field).findItems("*", QtCore.Qt.MatchWildcard)), 3)
        self.assertVolume(pad, 1500)

    def testOlderPadGetsAllowMultiFace(self):
        """T16, B7: a pad saved before AllowMultiFace (False): region B picked pads B alone,
        500 mm^3, not the whole sketch (P7's re-pick padded the whole sketch silently)."""
        pad, sketch, regions = self.regionsPad(allowMultiFace=False)
        [field] = self.edit(pad)
        self.arm(field, byFocus=False)
        self.pickRegion(sketch, regions["B"])
        self.assertEqual(pad.Profile[1], [regions["B"]])
        self.assertTrue(pad.AllowMultiFace)
        self.assertVolume(pad, 500)

    def testProfileOtherSketchReplaces(self):
        """A pick of another sketch, whole, replaces the profile, regions and all: a square
        50..52 x 0..2 padded 5, 20 mm^3."""
        pad, sketch, regions = self.regionsPad()
        other = models.sketch(self.doc, "Other", models.rectangle(50, 0, 52, 2), pad.getParent())
        self.doc.recompute()
        [field] = self.edit(pad)
        self.arm(field, byFocus=False)
        self.pickRegion(sketch, regions["B"])
        self.pick(other, "")
        self.assertEqual(pad.Profile, (other, []))
        self.assertEqual(texts(field), ["Other (whole)"])
        self.assertVolume(pad, 20)

    def testProfileDeleteAndUseWholeSketch(self):
        """Delete of the last region, and the entry menu's Use whole sketch, leave the whole
        sketch; the whole entry can't be removed."""
        pad, sketch, regions = self.regionsPad()
        [field] = self.edit(pad)
        self.arm(field, byFocus=True)
        self.pickRegion(sketch, regions["B"])
        self.assertEqual(pad.Profile[1], [regions["B"]])
        self.assertTrue(focus(entries(field)))
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: pad.Profile[1] == []), pad.Profile)
        self.assertEqual(texts(field), ["Regions (whole)"])
        menu = openMenu(field, 0)
        actions = menuActions(menu)
        self.assertFalse(actions["Remove"].isEnabled())
        self.assertNotIn("Use whole sketch", actions)
        menu.close()
        pump()

        self.arm(field, byFocus=False)
        self.pickRegion(sketch, regions["disk"])
        self.pickRegion(sketch, regions["B"])
        menu = openMenu(field, 1)
        menuActions(menu)["Use whole sketch"].trigger()
        menu.close()
        pump(0.3)
        self.assertEqual(pad.Profile, (sketch, []))
        self.assertVolume(pad, WHOLE_SKETCH)
        #   one step of the field's undo
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        both = [regions["disk"], regions["B"]]
        self.assertTrue(waitFor(lambda: pad.Profile[1] == both), pad.Profile)

    def testProfileMakeRegions(self):
        """A sketch that makes no regions: the armed field says so, its menu's Make regions sets
        MakeInternals, and region B can be picked then (500 mm^3)."""
        pad, sketch, regions = self.regionsPad(makeInternals=False)
        [field] = self.edit(pad)
        self.arm(field, byFocus=False)
        hint = field.findChild(QtWidgets.QLabel, "hint")
        self.assertIn("Make regions", hint.text())
        menu = openMenu(field, 0)
        menuActions(menu)["Make regions"].trigger()
        menu.close()
        pump(0.3)
        self.assertTrue(sketch.MakeInternals)
        self.assertNotIn("Make regions", hint.text())
        self.pickRegion(sketch, regions["B"])
        self.assertVolume(pad, 500)

    def testProfileEscDisarmsThenCancels(self):
        """Esc disarms the profile field (10.1), the next Esc cancels: the whole sketch again."""
        pad, sketch, regions = self.regionsPad()
        self.doc.openTransaction("Edit Pad")
        [field] = self.edit(pad)
        self.arm(field, byFocus=True)
        self.pickRegion(sketch, regions["B"])
        self.assertEqual(pad.Profile[1], [regions["B"]])
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(field)), "Esc didn't disarm the field")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "the first Esc closed the dialog")
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(
            waitFor(lambda: not Gui.Control.activeDialog()), "the second Esc left the dialog open"
        )
        self.assertEqual(pad.Profile, (sketch, []))
        self.assertVolume(pad, WHOLE_SKETCH)

    def coinNodes(self, obj, typeName):
        """obj's view provider's nodes of a type, those under switches that are off included."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoType.fromName(typeName))
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(obj.ViewObject.RootNode)
        return [path.getTail() for path in search.getPaths()]

    def regionTransparency(self, sketch):
        [faces] = self.coinNodes(sketch, "SoSketchFaces")
        return faces.getField("transparency").getValue()

    def shownToggles(self, pad):
        return sum(bool(t.getField("on").getValue()) for t in self.coinNodes(pad, "SoToggleSwitch"))

    def testProfileShadingWhileArmed(self):
        """T15, S1: while the field is armed the sketch shows, its regions drawn at half their
        saved transparency, the profile preview shows though its preference is off, and the pad
        (nothing before it) hides; disarmed, all as before."""
        pad, sketch, regions = self.regionsPad()
        preview = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign/Preview")
        had = preview.GetBool("ShowProfilePreview", True)
        preview.SetBool("ShowProfilePreview", False)
        try:
            sketch.ViewObject.Visibility = False
            saved = sketch.ViewObject.ShapeAppearance[0].Transparency
            [field] = self.edit(pad)
            padShown = pad.ViewObject.Visibility
            toggles = self.shownToggles(pad)
            self.assertAlmostEqual(self.regionTransparency(sketch), saved, places=5)

            self.arm(field, byFocus=True)
            self.assertTrue(sketch.ViewObject.Visibility)
            self.assertAlmostEqual(self.regionTransparency(sketch), saved / 2, places=5)
            self.assertEqual(self.shownToggles(pad), toggles + 1)
            self.assertFalse(pad.ViewObject.Visibility)
            #   a pick keeps it so
            self.pickRegion(sketch, regions["B"])
            self.assertAlmostEqual(self.regionTransparency(sketch), saved / 2, places=5)

            field.setProperty("armed", False)
            pump(0.2)
            self.assertFalse(sketch.ViewObject.Visibility)
            self.assertAlmostEqual(self.regionTransparency(sketch), saved, places=5)
            self.assertEqual(self.shownToggles(pad), toggles)
            self.assertEqual(pad.ViewObject.Visibility, padShown)
        finally:
            preview.SetBool("ShowProfilePreview", had)

    # -- PR 144's review (ops#150 W3, round 1) ---------------------------------------------------

    def statusText(self, field):
        return field.findChild(QtWidgets.QLabel, "status").text()

    def solidFaceProfile(self, typeName, expected):
        """The box (10 x 10 x 10), and a Pad or Pocket of its top face, 2 long: 1200 or 800 mm^3.
        Returns the feature and the top face's name."""
        box = self.box()
        [top] = [
            "Face%d" % (i + 1)
            for i, f in enumerate(box.Shape.Faces)
            if abs(f.CenterOfMass.z - 10) < 1e-6
        ]
        feature = self.body.newObject(typeName, typeName.split("::")[1])
        feature.Profile = (box, [top])
        feature.Length = 2
        self.assertVolume(feature, expected)
        return feature, top

    def testPadKeepsTheSolidsLastFace(self):
        """Review 1: a pad of the solid's top face; a pick of that face again would take out the
        last element and leave the solid whole, which is no profile: refused, with a message."""
        pad, top = self.solidFaceProfile("PartDesign::Pad", 1200)
        [field] = self.edit(pad)
        self.arm(field, byFocus=False)
        self.pick(self.boxFeature, top)
        self.assertLink(pad.Profile, self.boxFeature, [top])
        self.assertTrue(self.statusText(field), "no message for the refused pick")
        self.assertVolume(pad, 1200)

    def testPocketKeepsTheSolidsLastFace(self):
        """Review 1: the same for a pocket, through Delete on its entry."""
        pocket, top = self.solidFaceProfile("PartDesign::Pocket", 800)
        [field] = self.edit(pocket)
        self.assertTrue(focus(entries(field)))
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        pump(0.3)
        self.assertLink(pocket.Profile, self.boxFeature, [top])
        self.assertTrue(self.statusText(field), "no message for the refused Delete")
        self.assertVolume(pocket, 800)

    def testProfileRefusesASketchOnTheFeature(self):
        """Review 2: a sketch attached to the pad's own top face depends on the pad: the profile
        field refuses it (a cycle), as the start and up-to fields do."""
        pad, sketch, regions = self.regionsPad()
        [top] = [
            "Face%d" % (i + 1)
            for i, f in enumerate(pad.Shape.Faces)
            if abs(f.CenterOfMass.z - 5) < 1e-6 and f.Area > 150
        ]
        onPad = pad.getParent().newObject("Sketcher::SketchObject", "OnPad")
        onPad.AttachmentSupport = [(pad, top)]
        onPad.MapMode = "FlatFace"
        onPad.addGeometry(models.rectangle(1, 1, 3, 3), False)
        self.doc.recompute()
        self.assertTrue(onPad.isValid(), onPad.getStatusString())
        [field] = self.edit(pad)
        self.arm(field, byFocus=False)
        self.pick(onPad, "")
        self.assertEqual(pad.Profile, (sketch, []))
        self.assertVolume(pad, WHOLE_SKETCH)

    def testRepickRefusesAnotherObject(self):
        """Review 3: during an entry's Re-pick, a pick of another sketch, or of the sketch whole,
        would replace the profile and drop every entry: refused; a region replaces the entry."""
        pad, sketch, regions = self.regionsPad()
        other = models.sketch(self.doc, "Other", models.rectangle(50, 0, 52, 2), pad.getParent())
        self.doc.recompute()
        [field] = self.edit(pad)
        self.arm(field, byFocus=False)
        self.pickRegion(sketch, regions["B"])
        self.pickRegion(sketch, regions["disk"])
        both = [regions["B"], regions["disk"]]
        self.assertEqual(pad.Profile[1], both)
        menu = openMenu(field, 0)
        menuActions(menu)["Re-pick"].trigger()
        menu.close()
        pump()
        self.pick(other, "")
        self.assertEqual(pad.Profile, (sketch, both))
        self.assertTrue(self.statusText(field), "no message for the refused pick")
        self.pick(sketch, "")
        self.assertEqual(pad.Profile, (sketch, both))
        self.pickRegion(sketch, regions["A"])
        self.assertTrue(
            waitFor(lambda: pad.Profile[1] == [regions["A"], regions["disk"]]), pad.Profile
        )

    def testOlderPadGetsItsAllowMultiFaceBack(self):
        """Review 4: a pad without AllowMultiFace gets it with region B; without regions again
        (the field's undo, Delete of the last region, Use whole sketch) it goes back to False,
        so that the whole sketch takes its old way after OK; Cancel restores it too."""
        pad, sketch, regions = self.regionsPad(allowMultiFace=False)
        self.doc.openTransaction("Edit Pad")
        [field] = self.edit(pad)
        self.arm(field, byFocus=True)
        self.pickRegion(sketch, regions["B"])
        self.assertTrue(pad.AllowMultiFace)
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: pad.Profile[1] == []), pad.Profile)
        self.assertFalse(pad.AllowMultiFace)

        self.arm(field, byFocus=False)
        self.pickRegion(sketch, regions["B"])
        self.assertTrue(pad.AllowMultiFace)
        self.assertTrue(focus(entries(field)))
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: pad.Profile[1] == []), pad.Profile)
        self.assertFalse(pad.AllowMultiFace)

        self.arm(field, byFocus=False)
        self.pickRegion(sketch, regions["B"])
        self.pickRegion(sketch, regions["disk"])
        self.assertTrue(pad.AllowMultiFace)
        menu = openMenu(field, 0)
        menuActions(menu)["Use whole sketch"].trigger()
        menu.close()
        pump(0.3)
        self.assertEqual(pad.Profile, (sketch, []))
        self.assertFalse(pad.AllowMultiFace)
        self.assertVolume(pad, WHOLE_SKETCH)

        self.pickRegion(sketch, regions["B"])
        self.assertTrue(pad.AllowMultiFace)
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel")
        self.assertEqual(pad.Profile, (sketch, []))
        self.assertFalse(pad.AllowMultiFace)

    def shadingRestoredWhenTheEditEnds(self, close, editEnds):
        """Review 5: the field armed (the sketch shown and stronger, the pad hidden), then the
        dialog closed other than by OK or Cancel: all as before. The pad as before the edit when
        the edit ends (resetEdit), as in the dialog when it goes on (closeDialog)."""
        pad, sketch, regions = self.regionsPad()
        sketch.ViewObject.Visibility = False
        saved = sketch.ViewObject.ShapeAppearance[0].Transparency
        padBefore = pad.ViewObject.Visibility
        [field] = self.edit(pad)
        padShown = padBefore if editEnds else pad.ViewObject.Visibility
        self.arm(field, byFocus=False)
        self.assertTrue(sketch.ViewObject.Visibility)
        self.assertFalse(pad.ViewObject.Visibility)
        close()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.3)
        self.assertFalse(sketch.ViewObject.Visibility)
        self.assertAlmostEqual(self.regionTransparency(sketch), saved, places=5)
        self.assertEqual(pad.ViewObject.Visibility, padShown)

    def testShadingRestoredOnResetEdit(self):
        self.shadingRestoredWhenTheEditEnds(
            lambda: Gui.getDocument(self.doc.Name).resetEdit(), editEnds=True
        )

    def testShadingRestoredOnCloseDialog(self):
        self.shadingRestoredWhenTheEditEnds(Gui.Control.closeDialog, editEnds=False)

    def testZoomToARegion(self):
        """Review 6: the entry menu's Zoom to on a region moves the view to it (it looked the
        region up in the sketch's Shape, which has none: nothing happened)."""
        pad, sketch, regions = self.regionsPad()
        [field] = self.edit(pad)
        self.arm(field, byFocus=False)
        self.pickRegion(sketch, regions["B"])
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.viewTop()
        view.fitAll()
        pump(0.2)
        before = view.getCameraNode().position.getValue().getValue()
        menu = openMenu(field, 0)
        menuActions(menu)["Zoom to"].trigger()
        menu.close()
        pump(0.3)
        after = view.getCameraNode().position.getValue().getValue()
        # B is 30..40 x 0..10: the view centres on it
        self.assertNotAlmostEqual(before[0], after[0], places=3)
        self.assertAlmostEqual(after[0], 35, delta=0.5)
        self.assertAlmostEqual(after[1], 5, delta=0.5)

    def testGuessedRegionKeepsItsWarning(self):
        """Review test gap: region B's rectangle drawn again in place (new geometry) is found by
        geometry, a guess with a warning; the entry stays guessed, its warning kept, when region
        A is picked and when A is taken out again."""
        self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = True
        pad, sketch, regions = self.regionsPad()
        pad.Profile = (sketch, [regions["B"], regions["disk"]])
        self.assertVolume(pad, 500 + 20 * math.pi)
        last = sketch.GeometryCount
        sketch.delGeometries(list(range(last - 4, last)))
        sketch.addGeometry(models.polygon([(40, 10), (40, 0), (30, 0), (30, 10)]), False)
        self.assertVolume(pad, 500 + 20 * math.pi)
        self.assertIn("Warning", pad.State)

        def warned():
            return {
                e["index"]
                for e in App.getReferenceReport(pad)
                if e["property"] == "Profile" and e["warning"]
            }

        self.assertEqual(warned(), {0})
        [field] = self.edit(pad)
        self.assertEqual(states(field), ["guessed", "exact"])
        self.arm(field, byFocus=True)
        self.pickRegion(sketch, regions["A"])
        self.assertTrue(
            waitFor(lambda: states(field) == ["guessed", "exact", "exact"]), states(field)
        )
        self.assertEqual(warned(), {0})
        self.assertTrue(focus(entries(field)))
        clickRow(field, 2)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: states(field) == ["guessed", "exact"]), states(field))
        self.assertEqual(warned(), {0})
        self.assertVolume(pad, 500 + 20 * math.pi)

    # -- W4: a pattern's Originals (T17, B6; T1-T6) -------------------------------------------------

    def bumps(self, ys=(1, -3)):
        """The Pattern model: the box at -5..5 x -5..5 and a 1 x 1 x 1 bump on its top at x 1 and
        each of ys, all labelled "Bump" (duplicate Labels allowed while they are made)."""
        box = self.box()
        box.Placement = App.Placement(App.Vector(-5, -5, 0), App.Rotation())
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/Document")
        duplicates = prefs.GetBool("DuplicateLabels", False)
        prefs.SetBool("DuplicateLabels", True)
        bumps = []
        try:
            for y in ys:
                bump = self.doc.addObject("PartDesign::AdditiveBox", "Bump")
                self.body.addObject(bump)
                for prop in ("Length", "Width", "Height"):
                    setattr(bump, prop, 1)
                bump.Placement = App.Placement(App.Vector(1, y, 10), App.Rotation())
                bump.Label = "Bump"
                bumps.append(bump)
        finally:
            prefs.SetBool("DuplicateLabels", duplicates)
        self.doc.recompute()
        self.assertEqual({b.Label for b in bumps}, {"Bump"})
        self.assertEqual(len({b.Name for b in bumps}), len(bumps))
        self.assertAlmostEqual(bumps[-1].Shape.Volume, 1000 + len(bumps), places=6)
        return bumps

    def pattern(self, typeName, originals, transformBody=False):
        """A pattern of the bumps, as the Pattern model places its copies. It joins the body with
        its Originals set: a pattern of the tool shapes with none counts as a MultiTransform's
        step and gets no base feature, so an empty one joins as a pattern of the whole body and
        is switched back."""
        pattern = self.doc.addObject(typeName, typeName.split("::")[1])
        if typeName == "PartDesign::LinearPattern":
            pattern.Direction = (models.originFeature(self.body, "X_Axis"), [""])
            pattern.Length = 2
            pattern.Occurrences = 2
        elif typeName == "PartDesign::PolarPattern":
            pattern.Axis = (models.originFeature(self.body, "Z_Axis"), [""])
            pattern.Angle = 360
            pattern.Occurrences = 2
        elif typeName == "PartDesign::Mirrored":
            pattern.MirrorPlane = (models.originFeature(self.body, "YZ_Plane"), [""])
        elif typeName == "PartDesign::Scaled":
            pattern.Factor = 2
            pattern.Occurrences = 2
        pattern.Originals = originals
        if transformBody or not originals:
            pattern.TransformMode = "Whole shape"
        self.body.addObject(pattern)
        if not transformBody and not originals:
            pattern.TransformMode = "Features"
        self.doc.recompute()
        self.assertIsNotNone(pattern.BaseFeature)
        return pattern

    def names(self, field):
        """The objects a list of objects shows, by name."""
        refs = entries(field)
        return [refs.item(i).data(SUB_ROLE) for i in range(refs.count())]

    def originalNames(self, pattern):
        return [o.Name for o in pattern.Originals]

    def panelSpinBox(self, field):
        """A spin box of the panel that holds the field."""
        panel = field
        while not panel.metaObject().className().startswith("PartDesignGui::Task"):
            panel = panel.parentWidget()
        spins = [s for s in panel.findChildren(QtWidgets.QAbstractSpinBox) if s.isVisible()]
        self.assertTrue(spins, "no spin box in the panel")
        return spins[0]

    def testPatternOriginalsArmOnOpen(self):
        """T1: an edit of a linear pattern with no originals arms its Originals field (no Add and
        Remove buttons); a pick of a bump in the tree adds it. (A pattern that opens with none
        doesn't recompute until the edit ends: the edit's roll-back point takes it for a
        MultiTransform's step, ops#182; so no volume here.)"""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [])
        [field] = self.edit(pattern)
        self.assertEqual(field.objectName(), "fieldOriginals")
        self.assertTrue(waitFor(lambda: armed(field)), "the empty Originals field isn't armed")
        for name in ("buttonAddFeature", "buttonRemoveFeature"):
            self.assertIsNone(Gui.getMainWindow().findChild(QtWidgets.QAbstractButton, name))

        self.pick(first, "")
        self.assertEqual(self.originalNames(pattern), [first.Name])
        self.assertEqual(self.names(field), [first.Name])
        self.assertEqual(texts(field), ["Bump"])
        self.assertTrue(armed(field))

    def testPatternOriginalsPicksToggle(self):
        """T2: with the field armed, a pick of a face of the second bump adds it, a pick of the
        first (in the tree: the object alone) takes it out. The volume follows (1 mm^3 per bump
        patterned). A pick of the origin's plane is refused."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [first])
        [field] = self.edit(pattern)
        self.assertFalse(armed(field), "a complete pattern opens armed")
        self.arm(field, byFocus=True)
        self.assertVolume(pattern, 1003)

        self.pick(second, "Face6")
        self.assertEqual(self.originalNames(pattern), [first.Name, second.Name])
        self.assertVolume(pattern, 1004)

        self.pick(first, "")
        self.assertEqual(self.originalNames(pattern), [second.Name])
        self.assertEqual(self.names(field), [second.Name])
        self.assertVolume(pattern, 1003)
        self.assertTrue(armed(field))

        self.pick(models.originFeature(self.body, "XY_Plane"), "")
        self.assertEqual(self.originalNames(pattern), [second.Name])
        self.assertIn("adds or removes material", statusText())

    def testPatternOriginalsOfOneLabel(self):
        """T17, B6: two originals of one Label, which the list tells apart by their names. The
        second taken out, by a pick or by Delete on its row, is the one that goes, from the
        property and from the list; picked again, it comes back in the body's order."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [first, second])
        self.assertAlmostEqual(pattern.Shape.Volume, 1004, places=6)
        [field] = self.edit(pattern)
        self.assertFalse(armed(field), "a complete pattern opens armed")
        self.assertEqual(texts(field), [f"Bump ({first.Name})", f"Bump ({second.Name})"])

        self.arm(field, byFocus=True)
        self.pick(second, "")
        self.assertEqual(self.originalNames(pattern), [first.Name])
        self.assertEqual(self.names(field), [first.Name])
        self.assertEqual(texts(field), ["Bump"])
        self.assertVolume(pattern, 1003)

        self.pick(second, "")
        self.pick(first, "")
        self.pick(first, "")
        self.assertEqual(self.originalNames(pattern), [first.Name, second.Name])
        self.assertTrue(focus(entries(field)))
        clickRow(field, 1)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: self.names(field) == [first.Name]), self.names(field))
        self.assertEqual(self.originalNames(pattern), [first.Name])
        self.assertVolume(pattern, 1003)

    def testPatternOriginalsDisarmAndStayArmed(self):
        """T3, T4: with the focus in the 3D view the field stays armed and takes a pick; a spin box
        of the panel disarms it, and a pick then leaves the Originals alone."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [first])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)
        self.assertTrue(focus(views3D()[0]), "the 3D view doesn't take the focus")
        pump(0.2)
        self.assertTrue(armed(field), "the 3D view's focus disarmed the field")
        self.pick(second, "")
        self.assertEqual(self.originalNames(pattern), [first.Name, second.Name])

        self.assertTrue(focus(self.panelSpinBox(field)), "the spin box doesn't take the focus")
        self.assertTrue(waitFor(lambda: not armed(field)), "still armed with a spin box focused")
        self.pick(second, "")
        self.assertEqual(self.originalNames(pattern), [first.Name, second.Name])
        self.assertVolume(pattern, 1004)

    def testPatternOriginalsEscDisarmsThenCancels(self):
        """T5: Esc disarms the field and the dialog stays; the next Esc cancels, and the Originals
        are what they were before the edit."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [first])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=True)
        self.pick(second, "")
        self.assertEqual(self.originalNames(pattern), [first.Name, second.Name])
        self.assertTrue(focus(entries(field)))

        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(field)), "Esc didn't disarm the field")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "the first Esc closed the dialog")

        key(QtCore.Qt.Key_Escape)
        self.assertTrue(
            waitFor(lambda: not Gui.Control.activeDialog()), "the second Esc left the dialog open"
        )
        self.doc.recompute()
        self.assertEqual(self.originalNames(pattern), [first.Name])
        self.assertAlmostEqual(pattern.Shape.Volume, 1003, places=6)

    def testPatternOriginalsDeleteTwo(self):
        """T6: two of three originals selected, Delete: both go; OK makes one undo step, and undo
        brings them back."""
        bumps = self.bumps(ys=(1, -3, -1))
        pattern = self.pattern("PartDesign::LinearPattern", bumps)
        self.assertAlmostEqual(pattern.Shape.Volume, 1006, places=6)
        undoCount = self.doc.UndoCount
        [field] = self.edit(pattern)
        self.assertEqual(self.names(field), [b.Name for b in bumps])
        self.assertTrue(focus(entries(field)))
        clickRow(field, 0)
        clickRow(field, 2, QtCore.Qt.ControlModifier)
        self.assertEqual(len(entries(field).selectedItems()), 2)
        self.assertEqual(Gui.Selection.getSelectionEx(self.doc.Name), [])

        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: self.names(field) == [bumps[1].Name]), self.names(field))
        self.assertEqual(self.originalNames(pattern), [bumps[1].Name])
        self.assertVolume(pattern, 1004)

        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        ok.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        self.assertEqual(self.doc.UndoCount, undoCount + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.originalNames(pattern), [b.Name for b in bumps])
        self.assertAlmostEqual(pattern.Shape.Volume, 1006, places=6)

    def patternKind(self, typeName, volumes):
        """The Originals field in another pattern's panel: listed, and a pick takes the second
        bump out (volumes: before and after; None: the copy overlaps, only the property)."""
        first, second = self.bumps()
        pattern = self.pattern(typeName, [first, second])
        if volumes:
            self.assertAlmostEqual(pattern.Shape.Volume, volumes[0], places=6)
        [field] = self.edit(pattern)
        self.assertEqual(field.objectName(), "fieldOriginals")
        self.assertEqual(self.names(field), [first.Name, second.Name])
        self.arm(field, byFocus=False)
        self.pick(second, "")
        self.assertEqual(self.originalNames(pattern), [first.Name])
        self.assertEqual(self.names(field), [first.Name])
        if volumes:
            self.assertVolume(pattern, volumes[1])

    def testPolarPatternOriginals(self):
        self.patternKind("PartDesign::PolarPattern", (1004, 1003))

    def testMirroredOriginals(self):
        self.patternKind("PartDesign::Mirrored", (1004, 1003))

    def testScaledOriginals(self):
        self.patternKind("PartDesign::Scaled", None)

    def testPatternModeSwitchArmsTheEmptyField(self):
        """The whole body transformed: the field is greyed and doesn't arm; switching to the tool
        shapes with none listed arms it, and a pick adds the bump."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [], transformBody=True)
        [field] = self.edit(pattern)
        pump(0.3)
        self.assertFalse(field.isEnabled())
        self.assertFalse(armed(field))
        radio = Gui.getMainWindow().findChild(QtWidgets.QRadioButton, "radioTransformToolShapes")
        radio.click()
        self.assertTrue(waitFor(lambda: armed(field)), "the field isn't armed after the switch")
        self.pick(first, "")
        self.assertEqual(pattern.TransformMode, "Features")
        self.assertEqual(self.originalNames(pattern), [first.Name])
        self.assertVolume(pattern, 1003)

    def testMultiTransformOriginals(self):
        """The MultiTransform's panel has the field; its linear sub-pattern's "Select reference"
        takes the selection (the field disarms), and the field armed again ends that pick: the next
        pick changes the Originals, not the sub-pattern's direction."""
        first, second = self.bumps()
        multi = self.doc.addObject("PartDesign::MultiTransform", "MultiTransform")
        multi.Originals = [first, second]
        self.body.addObject(multi)
        linear = self.doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        xAxis = models.originFeature(self.body, "X_Axis")
        linear.Direction = (xAxis, [""])
        linear.Length = 2
        linear.Occurrences = 2
        self.body.addObject(linear)
        multi.Transformations = [linear]
        self.doc.recompute()
        self.assertAlmostEqual(multi.Shape.Volume, 1004, places=6)

        [field] = self.edit(multi)
        self.assertEqual(self.names(field), [first.Name, second.Name])
        transforms = Gui.getMainWindow().findChild(QtWidgets.QListWidget, "listTransformFeatures")
        transforms.setCurrentRow(0)
        transforms.activated.emit(transforms.currentIndex())
        pump(0.3)
        combos = [
            c
            for c in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, "comboDirection")
            if c.isVisible()
        ]
        self.assertEqual(len(combos), 1, "the sub-pattern's panel isn't open")
        self.arm(field, byFocus=False)
        self.choose(combos[0], combos[0].count() - 1)
        self.assertTrue(waitFor(lambda: not armed(field)), "the sub-pattern's pick left it armed")

        self.arm(field, byFocus=False)
        self.pick(second, "Face6")
        self.assertEqual(self.originalNames(multi), [first.Name])
        self.assertEqual(linear.Direction[0].Name, xAxis.Name)
        self.assertVolume(multi, 1003)

        # the sub-pattern's OK keeps its direction: the pick the field ended left no null entry
        ok = Gui.getMainWindow().findChild(QtWidgets.QPushButton, "buttonOK")
        self.assertTrue(ok.isVisible())
        ok.click()
        pump(0.3)
        self.assertEqual(linear.Direction[0].Name, xAxis.Name)
        self.assertVolume(multi, 1003)

    # -- PR 154's review (round 1) ---------------------------------------------------------------

    def selectReference(self, comboName):
        """The panel's "Select reference..." entry chosen, as a user does."""
        [combo] = [
            c for c in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, comboName) if c.isVisible()
        ]
        [index] = [i for i in range(combo.count()) if combo.itemText(i).startswith("Select reference")]
        self.choose(combo, index)
        self.assertEqual(combo.currentIndex(), index)
        return combo, index

    def referencePickThenOk(self, typeName, comboName, linkName, linked):
        """The field armed during a "Select reference..." pick ends the pick: the combo shows the
        link again, and OK keeps it (it wrote None before)."""
        first, second = self.bumps()
        pattern = self.pattern(typeName, [first])
        [field] = self.edit(pattern)
        combo, index = self.selectReference(comboName)
        self.arm(field, byFocus=False)
        self.assertTrue(waitFor(lambda: combo.currentIndex() != index), "the combo stays on the pick")
        self.pick(second, "")
        self.assertEqual(self.originalNames(pattern), [first.Name, second.Name])
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        link = getattr(pattern, linkName)
        self.assertIsNotNone(link, linkName + " was cleared")
        self.assertEqual(link[0].Name, models.originFeature(self.body, linked).Name)
        self.assertAlmostEqual(pattern.Shape.Volume, 1004, places=6)

    def testLinearReferencePickThenOk(self):
        self.referencePickThenOk("PartDesign::LinearPattern", "comboDirection", "Direction", "X_Axis")

    def testMirroredReferencePickThenOk(self):
        self.referencePickThenOk("PartDesign::Mirrored", "comboPlane", "MirrorPlane", "YZ_Plane")

    def testPatternOriginalsLabelRenamed(self):
        """A listed original renamed while the panel is open shows its new Label (and the other
        one no longer needs its name)."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [first, second])
        [field] = self.edit(pattern)
        self.assertEqual(texts(field), ["Bump ({})".format(first.Name), "Bump ({})".format(second.Name)])
        second.Label = "Knob"
        self.assertTrue(waitFor(lambda: texts(field) == ["Bump", "Knob"]), texts(field))

    def testPatternOriginalsRefusals(self):
        """A feature of another body and a feature after the pattern are refused; the Originals
        stay."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [first])
        later = self.doc.addObject("PartDesign::AdditiveBox", "Later")
        self.body.addObject(later)
        other = self.doc.addObject("PartDesign::Body", "OtherBody")
        foreign = self.doc.addObject("PartDesign::AdditiveBox", "Foreign")
        other.addObject(foreign)
        foreign.Placement = App.Placement(App.Vector(50, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertTrue(later.isValid() and foreign.isValid())
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)
        for refused in (foreign, later):
            self.pick(refused, "")
            self.assertEqual(self.originalNames(pattern), [first.Name], refused.Name)
            self.assertEqual(self.names(field), [first.Name], refused.Name)
        self.pick(second, "")
        self.assertEqual(self.originalNames(pattern), [first.Name, second.Name])

    def testPatternOriginalDeletedWhileOpen(self):
        """An original deleted while the panel is open leaves the list."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [first, second])
        [field] = self.edit(pattern)
        self.assertEqual(self.names(field), [first.Name, second.Name])
        name = second.Name
        self.body.removeObject(second)
        self.doc.removeObject(name)
        self.assertTrue(waitFor(lambda: self.names(field) == [first.Name]), self.names(field))
        self.assertEqual(self.originalNames(pattern), [first.Name])

    def testPatternCancelAfterModeSwitch(self):
        """Switched to the whole body, then Cancel: the pattern transforms its originals again,
        and they're all there."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [first, second])
        [field] = self.edit(pattern)
        radio = Gui.getMainWindow().findChild(QtWidgets.QRadioButton, "radioTransformBody")
        radio.click()
        self.assertTrue(waitFor(lambda: not field.isEnabled()), "the field isn't greyed")
        self.assertEqual(pattern.TransformMode, "Whole shape")
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        self.assertEqual(pattern.TransformMode, "Features")
        self.assertEqual(self.originalNames(pattern), [first.Name, second.Name])
        self.doc.recompute()
        self.assertAlmostEqual(pattern.Shape.Volume, 1004, places=6)

    # -- the preview's opacity (W5) -------------------------------------------------------------

    def opacitySlider(self):
        return Gui.getMainWindow().findChild(QtWidgets.QSlider, "opacitySlider")

    def previewTransparencies(self, feature):
        """The transparency of feature's preview shape, then of its other preview shapes (a
        subtractive feature's tool) in scene order."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoType.fromName("SoPreviewShape"))
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(feature.ViewObject.PreviewRootNode)
        main = feature.ViewObject.PreviewShapeNode
        others = [path.getTail() for path in search.getPaths()]
        others = [node for node in others if node != main]
        return [node.getField("transparency").getValue() for node in [main] + others]

    def defaultOpacity(self):
        """The preview parameters without a saved opacity (the theme's 0.2 applies), restored
        after the test."""
        params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign/Preview")
        saved = params.GetInt("Opacity") if "Opacity" in params.GetInts() else None
        params.RemInt("Opacity")

        def restore():
            if saved is None:
                params.RemInt("Opacity")
            else:
                params.SetInt("Opacity", saved)

        self.addCleanup(restore)
        return params

    def testPreviewOpacitySlider(self):
        """W5 (Q7 a): the Preview box's slider starts at the theme's opacity (20 %); moved to 60 %
        the pad's preview shape takes it at once (transparency 0.4) and the setting is saved; the
        slider is off while the preview is; the next dialog opens with 60 %."""
        params = self.defaultOpacity()
        box, pad = self.padOnBox(toFace=False)
        self.edit(pad, count=1)
        slider = self.opacitySlider()
        self.assertIsNotNone(slider, "the Preview box has no opacity slider")
        self.assertEqual((slider.minimum(), slider.maximum(), slider.value()), (0, 100, 20))
        self.assertAlmostEqual(self.previewTransparencies(pad)[0], 0.8, places=5)

        slider.setValue(60)
        pump(0.05)
        self.assertAlmostEqual(self.previewTransparencies(pad)[0], 0.4, places=5)
        self.assertEqual(params.GetInt("Opacity"), 60)

        preview = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "showTransparentPreviewCheckBox")
        preview.setChecked(False)
        pump(0.05)
        self.assertFalse(slider.isEnabled())
        preview.setChecked(True)
        pump(0.05)
        self.assertTrue(slider.isEnabled())

        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not fields()), "the dialog didn't close")
        self.edit(pad, count=1)
        self.assertEqual(self.opacitySlider().value(), 60)
        self.assertAlmostEqual(self.previewTransparencies(pad)[0], 0.4, places=5)

    def testPreviewOpacityPocketTool(self):
        """W5: a pocket's tool shape scales with the slider: 0.05 at the theme's 20 %, 0.15 at
        60 % (transparencies 0.95 and 0.85); its preview shape takes 60 % (0.4)."""
        self.defaultOpacity()
        self.box()
        square = models.sketch(self.doc, "Square", models.rectangle(2, 2, 4, 4), self.body, z=10)
        pocket = models.pocket(self.body, square, 3)
        self.doc.recompute()
        self.assertAlmostEqual(pocket.Shape.Volume, 988, places=3)
        self.edit(pocket, count=1)

        def tool():
            """The tool shape's transparency: the preview's other shapes are the tool and the
            profile's (no faces drawn: 1)."""
            [shown] = [t for t in self.previewTransparencies(pocket)[1:] if t < 0.999]
            return shown

        self.assertAlmostEqual(tool(), 0.95, places=5)

        self.opacitySlider().setValue(60)
        pump(0.05)
        self.assertAlmostEqual(self.previewTransparencies(pocket)[0], 0.4, places=5)
        self.assertAlmostEqual(tool(), 0.85, places=5)

    def testPreviewOpacityDressUp(self):
        """W5: a fillet's preview (the dress-up's own opacity setting) takes the slider's 60 %."""
        self.defaultOpacity()
        box = self.box()
        fillet = self.addFillet(box, TOP_FRONT.one(box.Shape))
        self.edit(fillet, count=1)
        self.assertAlmostEqual(self.previewTransparencies(fillet)[0], 0.8, places=5)
        self.opacitySlider().setValue(60)
        pump(0.05)
        self.assertAlmostEqual(self.previewTransparencies(fillet)[0], 0.4, places=5)
