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
- Ring (W6): a sketch in the XZ plane, the rectangle x 1..3, z 0..2 (area 4, centroid 2 from Z);
  datum lines along Z through x = 0 and x = -1; two datum planes through Z, normal X ("walls").
  By Pappus a revolution of 360 degrees about Z is 16 pi, about the x = -1 line 24 pi; up to a
  wall on each side, 90 degrees each, 8 pi. A groove of the same from a cylinder r 5, 2 high
  (50 pi) leaves 34 pi about Z, 26 pi about x = -1 (the annulus r 2..4 about it lies inside the
  cylinder), 42 pi up to the walls.
- Coil (W6): the Ring's rectangle, a helix of pitch 5 and height 10 (two turns): 32 pi about Z,
  48 pi about the x = -1 line (the sweep is approximated: relative tolerance 1e-3).
- Tower (W7): squares centred on Z, the profile 10 x 10 at z = 0, S1 20 x 20 at z = 10, S2 10 x 10
  at z = 20. A loft passes through its sections: in the order [S1, S2] its slice at z = 10 is S1,
  400; in the order [S2, S1] it isn't.
- Rod (W7): a profile 2 x 2 at z = 0 swept along a spine of two lines along Z (10 and 20 long);
  as a multisection pipe through S10 (4 x 4 at z = 10) and S30 (2 x 2 at z = 30) its slice at
  z = 10 is 16.

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
from PartDesignTests.Scenarios.harness import X, Z, edge, face, vertex
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
# The Pattern model's bumps (1 x 1 x 1 at x 1, y 1 and -3, on the box's top): the centres of their
# top faces.
FIRST_TOP = (1.5, 1.5, 11)
SECOND_TOP = (1.5, -2.5, 11)


def flushDeletes():
    """Deletes the widgets of closed dialogs now: processEvents() leaves deleteLater() to the
    event loop, and a closed dialog's field still counts as visible until then."""
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def settle():
    """After a dialog opens: its panel's queued focus (the value field, when the list is complete)
    lands, and so does the last dialog's late switch back to the Model tab, which hides the task
    view off screen; the task view is put in front again, until the panel's buttons show (under
    load the panel can show later than the fixed wait, ops#215)."""
    pump(0.3)
    if not waitFor(panelShown):
        raise AssertionError("no task panel OK/Cancel")
    pump(0.05)


def panelShown():
    """The task view put in front; whether the open dialog's OK or Cancel shows in it."""
    Gui.Control.showTaskView()
    buttons = (QtWidgets.QDialogButtonBox.Ok, QtWidgets.QDialogButtonBox.Cancel)
    return any(taskButton(which) is not None for which in buttons)


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

    def escInTheViewFirst(self, field, view):
        """Arms the field and presses and releases Esc in the view, which disarms it; then arms it
        again. The view's record of an Esc press it saw starts empty, whatever an earlier test
        left (a press in the view whose release went elsewhere)."""
        self.arm(field, byFocus=True)
        self.assertTrue(focus(view))
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(field)), "Esc in the 3D view didn't disarm")
        self.arm(field, byFocus=False)
        self.assertTrue(focus(view))

    def testEscClosingAPopupKeepsTheFieldArmed(self):
        """ops#216: Esc that closes a popup over the 3D view (Clarify, a context menu) is pressed
        in the popup; the release then reaches the view, which didn't see the press: the field
        stays armed and the edit stays."""
        box, fillet = self.newFillet()
        [field] = fields()
        [view] = views3D()
        self.escInTheViewFirst(field, view)
        menu = QtWidgets.QMenu(Gui.getMainWindow())
        menu.addAction("Entry")
        menu.popup(view.mapToGlobal(view.rect().center()))
        self.assertTrue(waitFor(lambda: QtWidgets.QApplication.activePopupWidget() is menu))
        window = Gui.getMainWindow().windowHandle()
        QtTest.QTest.keyPress(window, QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not menu.isVisible()), "Esc didn't close the popup")
        # focus goes back to the view, as on screen (off screen it can stay with no widget)
        self.assertTrue(focus(view))
        QtTest.QTest.keyRelease(window, QtCore.Qt.Key_Escape)
        pump(0.5)
        menu.deleteLater()
        self.assertTrue(armed(field), "the release of the popup's Esc disarmed the field")
        self.assertTrue(Gui.Control.activeDialog(), "the release of the popup's Esc closed the dialog")
        self.assertIsNotNone(Gui.getDocument(self.doc.Name).getInEdit(), "the edit was reset")

    def testEscClosingTheExpressionEditorKeepsTheFieldArmed(self):
        """ops#216: Esc that closes the '=' expression editor of the radius is pressed there; the
        release then reaches the 3D view (where the focus went, ops#146), which didn't see the
        press: the armed field stays armed and the edit stays."""
        box, fillet = self.newFillet()
        [field] = fields()
        [view] = views3D()
        self.escInTheViewFirst(field, view)
        radius = Gui.getMainWindow().findChild(QtWidgets.QWidget, "filletRadius")
        self.assertTrue(focus(radius), "the radius doesn't take the focus")
        QtTest.QTest.keyClick(radius, QtCore.Qt.Key_Equal)

        def editor():
            for dialog in radius.findChildren(QtWidgets.QDialog, "DlgExpressionInput"):
                if dialog.isVisible():
                    return dialog
            return None

        self.assertTrue(waitFor(lambda: editor() is not None), "'=' opened no expression editor")
        dialog = editor()
        edit = dialog.findChild(QtWidgets.QPlainTextEdit, "expression")
        QtTest.QTest.keyPress(edit, QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not dialog.isVisible()), "the editor stays")
        pump(0.3)
        # the radius's focus disarmed the field; armed again, as a user would before the release
        self.arm(field, byFocus=False)
        self.assertTrue(focus(view))
        QtTest.QTest.keyRelease(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_Escape)
        pump(0.5)
        self.assertTrue(armed(field), "the release of the editor's Esc disarmed the field")
        self.assertTrue(Gui.Control.activeDialog(), "the release of the editor's Esc closed the dialog")

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

    def testDraftWithFacesOpensUnarmed(self):
        """B1 (ops#162): a draft with faces and no pull direction opens with no field armed (the
        old panel armed on the pull direction's subs, not Base's)."""
        box, draft = self.draft()
        self.assertEqual(draft.PullDirection, None)
        [faces, plane, line] = self.edit(draft, count=3)
        pump(0.2)
        self.assertFalse(armed(faces), "a draft with faces opens armed")
        self.assertFalse(armed(line))

    def testDraftWithoutFacesOpensArmed(self):
        """B1 (ops#162): a draft with a pull direction and no faces opens with its faces field
        armed."""
        box, draft = self.draft()
        [vertical] = edge("line", direction=Z, through=(0, 0, 0)).one(box.Shape)
        draft.PullDirection = (box, [vertical])
        draft.Base = (box, [])
        self.doc.recompute()
        [faces, plane, line] = self.edit(draft, count=3)
        self.assertTrue(waitFor(lambda: armed(faces)), "a draft without faces opens unarmed")
        self.assertEqual(draft.PullDirection[1], [vertical])

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

    def testThicknessValueFocusDisarmsTheField(self):
        """B3 (ops#162): the value takes the focus: the field disarms, and a pick of the top face
        leaves Base alone (Thickness used to turn only the button off and keep the gate)."""
        box, thickness, field = self.emptyDressUp("PartDesign::Thickness", "Thickness")
        value = Gui.getMainWindow().findChild(QtWidgets.QWidget, "Value")
        self.assertIsNotNone(value)
        self.assertTrue(focus(value), "the value doesn't take the focus")
        self.assertTrue(waitFor(lambda: not armed(field)), "still armed with the value focused")
        [top] = face(normal=(0, 0, 1)).one(box.Shape)
        self.pick(box, top)
        self.assertEqual(thickness.Base[1], [])
        self.assertEqual(texts(field), [])

    def testThicknessValueEditDisarmsTheField(self):
        """B3 (ops#162): a value edit, the focus left in the field, disarms it (the panel's own
        disarm, not the focus model's), and a pick of the top face leaves Base alone."""
        box, thickness, field = self.emptyDressUp("PartDesign::Thickness", "Thickness")
        self.assertTrue(waitFor(lambda: armed(field)), "the new thickness's field isn't armed")
        value = Gui.getMainWindow().findChild(QtWidgets.QWidget, "Value")
        self.assertIsNotNone(value)
        self.assertFalse(value.hasFocus())
        value.setProperty("rawValue", 2.0)
        pump(0.2)
        self.assertAlmostEqual(thickness.Value.Value, 2.0, places=6)
        self.assertFalse(armed(field), "still armed after a value edit")
        [top] = face(normal=(0, 0, 1)).one(box.Shape)
        self.pick(box, top)
        self.assertEqual(thickness.Base[1], [])

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

    def testPadFaceRefusesAWholeSketch(self):
        """B20 (ops#162): a sketch picked whole gives an up-to-face no face: refused with the
        reason, UpToFace and the field stay as they were, and the field stays armed."""
        box, pad = self.padOnBox(toFace=False)
        self.edit(pad, count=1)
        self.padModeBox().setCurrentIndex(3)
        pump(0.2)
        field = findField("fieldUpToFace")
        self.assertTrue(
            waitFor(lambda: field.isVisible() and armed(field)), "the face field isn't armed"
        )
        self.pick(self.doc.getObject("Square"), "")
        self.assertIsNone(pad.UpToFace)
        self.assertEqual(texts(field), [])
        self.assertIn("isn't a face", statusText())
        self.assertTrue(armed(field))

    def testPadFaceTakesACoordinateSystemPlane(self):
        """B20 (ops#162): the XY plane of a coordinate system at z = 15 is linked through the
        system (the plane's name as the sub), the field shows it and the pad goes up to it."""
        box, pad = self.padOnBox(toFace=False)
        lcs = self.doc.addObject("Part::LocalCoordinateSystem", "LCS")
        self.body.addObject(lcs)
        lcs.Placement = App.Placement(App.Vector(0, 0, 15), App.Rotation())
        self.doc.recompute()
        [lcsPlane] = [f for f in lcs.OriginFeatures if f.Role == "XY_Plane"]
        self.edit(pad, count=1)
        self.padModeBox().setCurrentIndex(3)
        pump(0.2)
        field = findField("fieldUpToFace")
        self.assertTrue(
            waitFor(lambda: field.isVisible() and armed(field)), "the face field isn't armed"
        )
        self.pick(lcsPlane, "")
        self.assertLink(pad.UpToFace, lcs, [lcsPlane.Name])
        self.assertEqual(len(texts(field)), 1)
        self.assertVolume(pad, 1020)

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
        """Mark broken on the second guessed entry; the first deleted: the rejection moves up with
        its entry (index 0 now, still broken); another edge picked: it stays broken beside the
        new exact entry, not dropped by the count-changing writes. Without the field carrying
        the records by entry (ReferenceField::write) the entry stays broken by its "?" name, but
        the report loses the rejection (seen with the carry disabled, PR 142's review gap)."""
        pad, fillet = self.redrawnTwoEdgeFillet()
        [field] = self.edit(fillet)
        self.assertEqual(states(field), ["guessed", "guessed"])
        menu = openMenu(field, 1)
        menuActions(menu)["Mark broken"].trigger()
        menu.close()
        pump(0.3)
        self.assertTrue(waitFor(lambda: states(field) == ["guessed", "broken"]), states(field))
        second = fillet.Base[1][1]
        self.assertTrue(focus(entries(field)))
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: len(states(field)) == 1), states(field))
        self.assertEqual(states(field), ["broken"])
        self.assertEqual(fillet.Base[1], [second])
        self.assertRejectedAt(fillet, 0)
        self.arm(field, byFocus=False)
        [other] = edge("line", direction=Z, through=(20, 10, 0)).one(pad.Shape)
        self.pick(pad, other)
        self.assertTrue(waitFor(lambda: states(field) == ["broken", "exact"]), states(field))
        self.assertRejectedAt(fillet, 0)

    def assertRejectedAt(self, fillet, index):
        """The reference report keeps the Mark broken record at the entry's index: the "?" of a
        missing name alone isn't the rejection (without the record the entry is broken still)."""
        [row] = [e for e in App.getReferenceReport(fillet) if e["index"] == index]
        self.assertEqual(row["guess_kind"], "rejected", row)
        self.assertEqual([a["role"] for a in row["alternatives"]], ["rejected"], row)

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
        """An entry of a combo box chosen through its popup, as a user does. The popup is waited
        for until the entry has its place, and then until it closes (under load a fixed wait
        clicked a popup not yet laid out, ops#215)."""
        combo.showPopup()
        view = combo.view()

        def placed():
            rect = view.visualRect(view.model().index(index, 0))
            return view.isVisible() and rect.isValid() and not rect.isEmpty()

        self.assertTrue(waitFor(placed), "the popup's entry isn't placed")
        pump(0.05)
        rect = view.visualRect(view.model().index(index, 0))
        QtTest.QTest.mouseClick(
            view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center()
        )
        if not waitFor(lambda: not view.isVisible()):
            combo.hidePopup()  # not left open for the next test
            self.fail("the popup didn't close")
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

    def shadingRestoredWhenTheEditEnds(self, close, editEnds, transaction=None):
        """Review 5: the field armed (the sketch shown and stronger, the pad hidden), then the
        dialog closed (OK, Cancel, or other than by them): all as before. The pad as before the
        edit when the edit ends, as in the dialog when it goes on (closeDialog). A transaction
        opened before the edit, as a double click opens it, for Cancel to abort."""
        pad, sketch, regions = self.regionsPad()
        sketch.ViewObject.Visibility = False
        saved = sketch.ViewObject.ShapeAppearance[0].Transparency
        padBefore = pad.ViewObject.Visibility
        if transaction:
            self.doc.openTransaction(transaction)
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

    def elementNear(self, obj, kind, point):
        """The name of the face (kind "Face"), edge or vertex of obj's shape that is at point: its
        centre, or the vertex itself. The shape's own indices, as a pick in the 3D view gives."""
        shape = obj.Shape
        elements = {"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}[kind]
        wanted = App.Vector(*point)
        for i, element in enumerate(elements, 1):
            centre = element.Point if kind == "Vertex" else element.CenterOfMass
            if centre.distanceToPoint(wanted) < 1e-6:
                return "%s%d" % (kind, i)
        self.fail("no %s of %s at %s" % (kind, obj.Name, point))

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
        Remove buttons); a pick of a bump in the tree adds it, and the pattern computes during
        the edit (ops#182: the edit's roll-back point took it for a MultiTransform's step and
        held it until the edit ended). A bump made after the pattern stays held during the edit,
        and the pattern doesn't (ops#212)."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [])
        after = self.doc.addObject("PartDesign::AdditiveBox", "After")
        self.body.addObject(after)
        for prop in ("Length", "Width", "Height"):
            setattr(after, prop, 1)
        after.Placement = App.Placement(App.Vector(-3, 3, 10), App.Rotation())
        self.doc.recompute()
        self.assertEqual(self.body.Group.index(after), self.body.Group.index(pattern) + 1)
        self.assertAlmostEqual(after.Shape.Volume, 1003, places=6)
        [field] = self.edit(pattern)
        self.assertTrue(self.body.holds(after), "the feature after the pattern isn't held")
        self.assertFalse(self.body.holds(pattern), "the pattern in edit is held")
        self.assertEqual(field.objectName(), "fieldOriginals")
        self.assertTrue(waitFor(lambda: armed(field)), "the empty Originals field isn't armed")
        for name in ("buttonAddFeature", "buttonRemoveFeature"):
            self.assertIsNone(Gui.getMainWindow().findChild(QtWidgets.QAbstractButton, name))

        self.pick(first, "")
        self.assertEqual(self.originalNames(pattern), [first.Name])
        self.assertEqual(self.names(field), [first.Name])
        self.assertEqual(texts(field), ["Bump"])
        self.assertTrue(armed(field))
        self.assertVolume(pattern, 1003)
        self.assertTrue(self.body.holds(after), "the pick released the feature after the pattern")
        self.assertFalse(self.body.holds(pattern))

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

        self.pick(second, self.elementNear(second, "Face", SECOND_TOP))
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

    def testPatternOriginalsPickOfAnElement(self):
        """ops#184: while the field is armed the 3D view shows the base feature's shape (the
        box and both bumps), and a pick of a face, an edge or a vertex of it adds the feature
        that made the element, or takes it out: the first bump, the second, the box."""
        first, second = self.bumps()
        box = self.boxFeature
        pattern = self.pattern("PartDesign::LinearPattern", [second])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=True)

        # a face of the first bump, in the second bump's shape: the first bump, not the base
        self.pick(second, self.elementNear(second, "Face", FIRST_TOP))
        self.assertEqual(self.originalNames(pattern), [first.Name, second.Name])
        self.assertVolume(pattern, 1004)

        # a face of the second bump: the second
        self.pick(second, self.elementNear(second, "Face", SECOND_TOP))
        self.assertEqual(self.originalNames(pattern), [first.Name])
        self.assertVolume(pattern, 1003)

        # a side face of the box
        self.pick(second, self.elementNear(second, "Face", (5, 0, 5)))
        self.assertEqual(self.originalNames(pattern), [box.Name, first.Name])

        # an edge of the first bump takes it out, a corner of it puts it back
        self.pick(second, self.elementNear(second, "Edge", (1.5, 1, 11)))
        self.assertEqual(self.originalNames(pattern), [box.Name])
        self.pick(second, self.elementNear(second, "Vertex", (2, 2, 11)))
        self.assertEqual(self.originalNames(pattern), [box.Name, first.Name])
        self.assertEqual(self.names(field), [box.Name, first.Name])
        self.assertTrue(armed(field))

    def testPatternOriginalsPickThroughADressUp(self):
        """ops#184: the base feature is a fillet; a pick of a face of its shape in the 3D view
        reaches the features that made it, not the fillet."""
        [bump] = self.bumps(ys=(1,))
        box = self.boxFeature
        fillet = self.addFillet(bump, [self.elementNear(bump, "Edge", (-5, -5, 5))])
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        self.assertEqual(pattern.BaseFeature.Name, fillet.Name)
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(fillet, self.elementNear(fillet, "Face", (5, 0, 5)))
        self.assertEqual(self.originalNames(pattern), [box.Name, bump.Name])
        self.pick(fillet, self.elementNear(fillet, "Face", FIRST_TOP))
        self.assertEqual(self.originalNames(pattern), [box.Name])

    def bumpOn(self, x, y, z, name="Bump"):
        bump = self.doc.addObject("PartDesign::AdditiveBox", name)
        self.body.addObject(bump)
        for prop in ("Length", "Width", "Height"):
            setattr(bump, prop, 1)
        bump.Placement = App.Placement(App.Vector(x, y, z), App.Rotation())
        self.doc.recompute()
        return bump

    def testPatternOriginalsPickReachesAPadUnderAFillet(self):
        """ops#184 review F1: the pad's bottom face, seen through a fillet, has the fillet and
        the sketch in its history and not the pad: the sketch maps to the pad (the fillet, the
        base, made the element no more than the pad did)."""
        self.body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        pad = models.pad(self.body, profile, 5)
        self.doc.recompute()
        bump = self.bumpOn(1, 1, 5)
        fillet = self.addFillet(bump, [self.elementNear(bump, "Edge", (0, 0, 2.5))])
        [bottom] = face(normal=(0, 0, -1)).one(fillet.Shape)
        history = fillet.getElementHistory(bottom, recursive=True)
        self.assertEqual([item[0].Name for item in history], ["Fillet", "Profile"], history)
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        self.assertEqual(pattern.BaseFeature.Name, fillet.Name)
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(fillet, bottom)
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])

    def testPatternOriginalsPickOfPadAndPocketOnOneSketch(self):
        """ops#184 review F2, F4: a pad and a pocket share a sketch, the sketch's square at the
        box's top: a pick of the pad's wall adds the pad, a pick of the pocket's wall the pocket
        (the one in the element's history), and a pick of the pocket's wall again takes it out."""
        box = self.box()
        sketch = models.sketch(self.doc, "Shared", models.rectangle(4, 4, 6, 6), self.body, z=10)
        pad = models.pad(self.body, sketch, 3)
        pad.Refine = False
        self.doc.recompute()
        pocket = models.pocket(self.body, sketch, 3)
        pocket.Refine = False
        self.doc.recompute()
        bump = self.bumpOn(1, 1, 10)
        self.assertTrue(pocket.isValid() and pad.isValid())
        self.assertAlmostEqual(bump.Shape.Volume, 1000 + 12 - 12 + 1, places=6)
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(bump, self.elementNear(bump, "Face", (4, 5, 11.5)))
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])
        self.pick(bump, self.elementNear(bump, "Face", (4, 5, 8.5)))
        self.assertEqual(self.originalNames(pattern), [pad.Name, pocket.Name, bump.Name])
        self.pick(bump, self.elementNear(bump, "Face", (4, 5, 8.5)))
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])

    def testPatternOriginalsPickOfAnElementNoFeatureMade(self):
        """ops#184 review F5: the body's base feature is a Part::Box, which is no feature of the
        body: a pick of its face in the bump's shape says so, and changes neither the Originals
        nor the armed field."""
        self.body = models.body(self.doc)
        partBox = self.doc.addObject("Part::Box", "PartBox")
        self.body.BaseFeature = partBox
        bump = self.bumpOn(1, 1, 10)
        self.assertAlmostEqual(bump.Shape.Volume, 1001, places=6)
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(bump, self.elementNear(bump, "Face", (0, 5, 5)))
        self.assertEqual(self.originalNames(pattern), [bump.Name])
        self.assertIn("No feature", self.statusText(field))
        self.assertTrue(armed(field))
        # the next pick clears it
        self.pick(bump, self.elementNear(bump, "Face", (1.5, 1.5, 11)))
        self.assertEqual(self.originalNames(pattern), [])
        self.assertNotIn("No feature", self.statusText(field))

    def historyNames(self, feature, sub):
        return [item[0].Name for item in feature.getElementHistory(sub, recursive=True)]

    def binder(self, typeName, name, source, sub=""):
        binder = self.body.newObject(typeName, name)
        if typeName == "PartDesign::ShapeBinder":
            binder.Support = [(source, sub)]
        else:
            binder.Support = [(source, (sub,))]
        self.doc.recompute()
        return binder

    def testPatternOriginalsPickOfAPadOnAShapeBinder(self):
        """ops#214: the pad's profile is a ShapeBinder of a sketch outside the body. The pad's
        side face comes from the sketch, its top from the binder: a pick of either adds the pad,
        or takes it out."""
        self.body = models.body(self.doc)
        source = models.sketch(self.doc, "Source", models.rectangle(0, 0, 10, 10))
        binder = self.binder("PartDesign::ShapeBinder", "Binder", source)
        pad = models.pad(self.body, binder, 5)
        self.doc.recompute()
        bump = self.bumpOn(1, 1, 5)
        [side] = face(contains=(10, 5, 2.5)).one(bump.Shape)
        [top] = face(contains=(8, 8, 5)).one(bump.Shape)
        self.assertEqual(self.historyNames(bump, side)[-1], source.Name)
        self.assertEqual(self.historyNames(bump, top)[-1], binder.Name)
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(bump, side)
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])
        self.pick(bump, top)
        self.assertEqual(self.originalNames(pattern), [bump.Name])
        self.assertNotIn("No feature", self.statusText(field))

    def testPatternOriginalsPickOfAPadOnABinderOfABinder(self):
        """ops#214: the pad's profile is a SubShapeBinder of a SubShapeBinder of a sketch. The
        bottom face's history ends at the inner binder and doesn't name the pad, the side face's
        ends at the sketch: both picks reach the pad through the binders."""
        self.body = models.body(self.doc)
        source = models.sketch(self.doc, "Source", models.rectangle(0, 0, 10, 10))
        inner = self.binder("PartDesign::SubShapeBinder", "Inner", source)
        outer = self.binder("PartDesign::SubShapeBinder", "Outer", inner)
        pad = models.pad(self.body, outer, 5)
        self.doc.recompute()
        bump = self.bumpOn(1, 1, 5)
        [side] = face(contains=(0, 5, 2.5)).one(bump.Shape)
        [bottom] = face(normal=(0, 0, -1)).one(bump.Shape)
        self.assertEqual(self.historyNames(bump, side)[-1], source.Name)
        self.assertEqual(self.historyNames(bump, bottom), [bump.Name, inner.Name])
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(bump, bottom)
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])
        self.pick(bump, side)
        self.assertEqual(self.originalNames(pattern), [bump.Name])

    def testPatternOriginalsPickOfAPadOnABinderOfTheBase(self):
        """ops#214: the body's base feature is a Part::Box, and a pad stands on a SubShapeBinder of
        the box's top face. The histories of the box's side and of the pad's side both end at the
        box, without the pad: a pick of either says no feature made it, rather than taking the
        box's faces for the pad's (a limit: the pad's side can't be told from the box's)."""
        self.body = models.body(self.doc)
        partBox = self.doc.addObject("Part::Box", "PartBox")
        self.body.BaseFeature = partBox
        self.doc.recompute()
        [lid] = face(contains=(5, 5, 10)).one(partBox.Shape)
        binder = self.binder("PartDesign::SubShapeBinder", "Binder", partBox, lid)
        pad = models.pad(self.body, binder, 5)
        pad.Refine = False
        self.doc.recompute()
        bump = self.bumpOn(1, 1, 15)
        [padSide] = face(contains=(5, 0, 12.5)).one(bump.Shape)
        [boxSide] = face(contains=(5, 0, 5)).one(bump.Shape)
        for side in (padSide, boxSide):
            self.assertEqual(self.historyNames(bump, side), [bump.Name, partBox.Name])
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        for side in (boxSide, padSide):
            self.pick(bump, side)
            self.assertEqual(self.originalNames(pattern), [bump.Name])
            self.assertIn("No feature", self.statusText(field))
        self.assertTrue(armed(field))
        self.assertTrue(pad.isValid())

    def testPatternOriginalsPickOfAPadOnABinderOfACutBase(self):
        """Fork PR 196 review, 2a: the body's base feature is a Part::Cut of a box, and a pad
        stands on a SubShapeBinder of the box's top face. The box's side, merged with the pad's
        by the bump's refine, ends at the box (not at the base, the cut) without the pad: a pick
        says no feature made it, rather than taking the pad. The pad's top, which the pad is in
        the history of, adds the pad."""
        self.body = models.body(self.doc)
        box = models.box(self.doc, "Box", (10, 10, 10))
        tool = models.box(self.doc, "Tool", (2, 2, 10), at=(8, 8, 0))
        cut = self.doc.addObject("Part::Cut", "Cut")
        cut.Base = box
        cut.Tool = tool
        self.doc.recompute()
        self.body.BaseFeature = cut
        self.doc.recompute()
        [lid] = face(contains=(5, 5, 10)).one(box.Shape)
        binder = self.binder("PartDesign::SubShapeBinder", "Binder", box, lid)
        pad = models.pad(self.body, binder, 5)
        pad.Refine = False
        self.doc.recompute()
        bump = self.bumpOn(1, 1, 15)
        [side] = face(contains=(5, 0, 5)).one(bump.Shape)
        [top] = face(contains=(8, 8, 15)).one(bump.Shape)
        self.assertEqual(self.historyNames(bump, side), [bump.Name, box.Name])
        self.assertEqual(self.historyNames(bump, top)[-2:], [pad.Name, box.Name])
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(bump, side)
        self.assertEqual(self.originalNames(pattern), [bump.Name])
        self.assertIn("No feature", self.statusText(field))
        self.pick(bump, top)
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])

    def testPatternOriginalsPickOfAPadOnABinderOfAnotherBody(self):
        """Fork PR 196 review, 2b: a Boolean fuses a second body's pad into the body, and a pad
        stands on a SubShapeBinder of that pad's top face. Their faces end at the second body's
        sketch, which no feature of this body uses: a pick of the second body's side or of the
        pad's top says no feature made it (a limit: the pad isn't found through the binder of a
        face in the middle of the history), and nothing is guessed."""
        self.body = models.body(self.doc)
        other = models.body(self.doc)
        otherSketch = models.sketch(
            self.doc, "OtherSketch", models.rectangle(10, 0, 20, 10), other
        )
        otherPad = models.pad(other, otherSketch, 10, "OtherPad")
        self.doc.recompute()
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        models.pad(self.body, profile, 10)
        self.doc.recompute()
        boolean = self.body.newObject("PartDesign::Boolean", "Boolean")
        boolean.addObject(other)
        boolean.Type = "Fuse"
        self.doc.recompute()
        self.assertTrue(boolean.isValid(), boolean.getStatusString())
        [lid] = face(contains=(15, 5, 10)).one(otherPad.Shape)
        binder = self.binder("PartDesign::SubShapeBinder", "Binder", otherPad, lid)
        pad = models.pad(self.body, binder, 5, "Raised")
        pad.Refine = False
        self.doc.recompute()
        bump = self.bumpOn(1, 1, 10)
        [side] = face(contains=(20, 5, 5)).one(bump.Shape)
        [top] = face(contains=(15, 5, 15)).one(bump.Shape)
        for element in (side, top):
            self.assertEqual(self.historyNames(bump, element)[-1], otherSketch.Name)
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        for element in (side, top):
            self.pick(bump, element)
            self.assertEqual(self.originalNames(pattern), [bump.Name])
            self.assertIn("No feature", self.statusText(field))

    def testPatternOriginalsPickOfPadAndPocketOnTwoBindersOfOneSketch(self):
        """Fork PR 196 review, 1 (round 2: reaches the "several candidates" case): a pad stands on
        a SubShapeBinder of a sketch outside the body, a pocket on a SubShapeBinder of that
        binder; the sketch's rectangle crosses the box's top edge, so the pad overhangs. The
        walls' histories name their features: a pick of the pad's wall adds the pad, of the
        pocket's the pocket, and of the pocket's again takes it out. The overhang's bottom ends
        at the pad's binder without a feature, and both the pad (on it) and the pocket (through
        the other binder) are candidates: no guess (a geometric choice is ops#219). With two
        binders of the sketch itself, that bottom ends at the pad's binder, which only the pad
        uses: a single candidate, so this case needs the chain."""
        box = self.box()
        source = models.sketch(self.doc, "Source", models.rectangle(8, 4, 12, 6), z=10)
        padBinder = self.binder("PartDesign::SubShapeBinder", "PadBinder", source)
        pocketBinder = self.binder("PartDesign::SubShapeBinder", "PocketBinder", padBinder)
        pad = models.pad(self.body, padBinder, 3)
        pad.Refine = False
        self.doc.recompute()
        pocket = models.pocket(self.body, pocketBinder, 3)
        pocket.Refine = False
        self.doc.recompute()
        bump = self.bumpOn(1, 1, 10)
        bump.Refine = False
        self.doc.recompute()
        self.assertTrue(pocket.isValid() and pad.isValid())
        [padWall] = face(contains=(8, 5, 11.5)).one(bump.Shape)
        [pocketWall] = face(contains=(8, 5, 8.5)).one(bump.Shape)
        [overhang] = face(contains=(11, 5, 10)).one(bump.Shape)
        self.assertEqual(self.historyNames(bump, padWall)[-2:], [pad.Name, source.Name])
        self.assertEqual(self.historyNames(bump, pocketWall)[-2:], [pocket.Name, source.Name])
        self.assertEqual(self.historyNames(bump, overhang), [bump.Name, padBinder.Name])
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(bump, padWall)
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])
        self.pick(bump, pocketWall)
        self.assertEqual(self.originalNames(pattern), [pad.Name, pocket.Name, bump.Name])
        self.pick(bump, pocketWall)
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])
        self.pick(bump, overhang)
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])
        self.assertIn("No feature", self.statusText(field))

    def testPatternOriginalsPickOfAnotherBodysPadOfABoundSketch(self):
        """Fork PR 196 round 2: a Boolean fuses another body's pad into the body, and a pad
        reversed below it stands on a SubShapeBinder of the other body's sketch. The other pad's
        top ends at that sketch through the other pad: a pick says no feature made it (the
        other body's pad did), rather than taking the pad on the binder. The reversed pad's side,
        whose history names it, adds it."""
        self.body = models.body(self.doc)
        other = models.body(self.doc)
        otherSketch = models.sketch(
            self.doc, "OtherSketch", models.rectangle(10, 0, 20, 10), other
        )
        otherPad = models.pad(other, otherSketch, 10, "OtherPad")
        self.doc.recompute()
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        models.pad(self.body, profile, 8).Refine = False
        self.doc.recompute()
        boolean = self.body.newObject("PartDesign::Boolean", "Boolean")
        boolean.addObject(other)
        boolean.Type = "Fuse"
        boolean.Refine = False
        self.doc.recompute()
        binder = self.binder("PartDesign::SubShapeBinder", "Binder", otherSketch)
        below = models.pad(self.body, binder, 5, "Below")
        below.Reversed = True
        below.Refine = False
        self.doc.recompute()
        self.assertTrue(below.isValid(), below.getStatusString())
        bump = self.bumpOn(1, 1, 8)
        bump.Refine = False
        self.doc.recompute()
        [otherTop] = face(contains=(15, 5, 10)).one(bump.Shape)
        [belowSide] = face(contains=(20, 5, -2.5)).one(bump.Shape)
        self.assertEqual(
            self.historyNames(bump, otherTop), [bump.Name, otherPad.Name, otherSketch.Name]
        )
        self.assertEqual(self.historyNames(bump, belowSide)[-2:], [below.Name, otherSketch.Name])
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(bump, otherTop)
        self.assertEqual(self.originalNames(pattern), [bump.Name])
        self.assertIn("No feature", self.statusText(field))
        self.pick(bump, belowSide)
        self.assertEqual(self.originalNames(pattern), [below.Name, bump.Name])

    def testPatternOriginalsPickOfAnExtrusionBaseOfABoundSketch(self):
        """Fork PR 196 round 2: the body's base feature is a Part::Extrusion of a sketch, and a
        pad reversed below it stands on a SubShapeBinder of that sketch. The extrusion's side
        ends at the sketch through the extrusion: a pick says no feature made it, rather than
        taking the pad. The pad's side, whose history names it, adds it."""
        self.body = models.body(self.doc)
        sketch = models.sketch(self.doc, "S", models.rectangle(0, 0, 10, 10))
        extrusion = self.doc.addObject("Part::Extrusion", "Extrusion")
        extrusion.Base = sketch
        extrusion.Dir = App.Vector(0, 0, 1)
        extrusion.LengthFwd = 10
        extrusion.Solid = True
        self.doc.recompute()
        self.body.BaseFeature = extrusion
        self.doc.recompute()
        binder = self.binder("PartDesign::SubShapeBinder", "Binder", sketch)
        pad = models.pad(self.body, binder, 5)
        pad.Reversed = True
        pad.Refine = False
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        bump = self.bumpOn(1, 1, 10)
        bump.Refine = False
        self.doc.recompute()
        [extrusionSide] = face(contains=(5, 0, 5)).one(bump.Shape)
        [padSide] = face(contains=(5, 0, -2.5)).one(bump.Shape)
        self.assertEqual(
            self.historyNames(bump, extrusionSide), [bump.Name, extrusion.Name, sketch.Name]
        )
        self.assertEqual(self.historyNames(bump, padSide)[-2:], [pad.Name, sketch.Name])
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        self.pick(bump, extrusionSide)
        self.assertEqual(self.originalNames(pattern), [bump.Name])
        self.assertIn("No feature", self.statusText(field))
        self.pick(bump, padSide)
        self.assertEqual(self.originalNames(pattern), [pad.Name, bump.Name])

    def testPatternOriginalsPickOfUpToFaceLoftAndPipeCaps(self):
        """ops#214, a pin: the top of a pad up to a datum plane, the cap of a loft at its section
        and the cap of a pipe at its spine's end have histories that end at the pad's sketch, the
        loft and the pipe: a pick of each adds its feature."""
        self.body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        datum = self.body.newObject("PartDesign::Plane", "DatumPlane")
        datum.AttachmentSupport = [(models.originFeature(self.body, "XY_Plane"), "")]
        datum.MapMode = "FlatFace"
        datum.AttachmentOffset = App.Placement(App.Vector(0, 0, 7), App.Rotation())
        self.doc.recompute()
        pad = models.pad(self.body, profile, 5)
        pad.Type = "UpToFace"
        pad.UpToFace = (datum, [""])
        self.doc.recompute()
        loftProfile = models.sketch(
            self.doc, "LoftProfile", models.rectangle(1, 1, 4, 4), self.body, z=7
        )
        section = models.sketch(self.doc, "Section", models.rectangle(2, 2, 3, 3), self.body, z=9)
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = loftProfile
        loft.Sections = [section]
        self.doc.recompute()
        pipeProfile = models.sketch(
            self.doc, "PipeProfile", models.rectangle(6, 6, 8, 8), self.body, z=7
        )
        spine = models.sketch(
            self.doc,
            "Spine",
            models.polyline([(7, 7), (7, 10)]),
            self.body,
            placement=App.Placement(App.Vector(0, 7, 0), App.Rotation(App.Vector(1, 0, 0), 90)),
        )
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = pipeProfile
        pipe.Spine = (spine, ["Edge1"])
        self.doc.recompute()
        self.assertTrue(pad.isValid() and loft.isValid() and pipe.isValid())
        bump = self.bumpOn(1, 8, 7)
        [padTop] = face(contains=(5, 9.5, 7)).one(bump.Shape)
        [loftCap] = face(contains=(2.5, 2.5, 9)).one(bump.Shape)
        [pipeCap] = face(contains=(7, 7, 10)).one(bump.Shape)
        self.assertEqual(self.historyNames(bump, padTop)[-1], profile.Name)
        self.assertEqual(self.historyNames(bump, loftCap)[-1], loft.Name)
        self.assertEqual(self.historyNames(bump, pipeCap)[-1], pipe.Name)
        pattern = self.pattern("PartDesign::LinearPattern", [bump])
        [field] = self.edit(pattern)
        self.arm(field, byFocus=False)

        for picked in (padTop, loftCap, pipeCap):
            self.pick(bump, picked)
        self.assertEqual(self.originalNames(pattern), [pad.Name, loft.Name, pipe.Name, bump.Name])

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
        self.pick(second, self.elementNear(second, "Face", SECOND_TOP))
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

        def shown():
            window = Gui.getMainWindow()
            return [c for c in window.findChildren(QtWidgets.QComboBox, comboName) if c.isVisible()]

        self.assertTrue(waitFor(lambda: shown()), f"no {comboName} box shows")
        [combo] = shown()
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

    # -- ops#186: a pending "Select reference..." by the other paths ------------------------------

    def multiTransform(self, typeName):
        """The bumps in a MultiTransform of one sub-feature (linear along X, or mirrored in YZ),
        its sub-task open."""
        first, second = self.bumps()
        multi = self.doc.addObject("PartDesign::MultiTransform", "MultiTransform")
        multi.Originals = [first, second]
        self.body.addObject(multi)
        sub = self.doc.addObject(typeName, typeName.split("::")[1])
        if typeName == "PartDesign::LinearPattern":
            sub.Direction = (models.originFeature(self.body, "X_Axis"), [""])
            sub.Length = 2
            sub.Occurrences = 2
        else:
            sub.MirrorPlane = (models.originFeature(self.body, "YZ_Plane"), [""])
        self.body.addObject(sub)
        multi.Transformations = [sub]
        self.doc.recompute()
        self.assertAlmostEqual(multi.Shape.Volume, 1004, places=6)
        # The body's shown feature is its first visible solid: the sub-feature, added last
        # (ops#187's test deletes it; ops#212)
        solids = [o for o in self.body.Group if o.isDerivedFrom("PartDesign::Feature")]
        shown = [o for o in solids if o.Visibility]
        self.assertEqual(shown, [sub], "the sub-feature isn't the body's shown feature")
        [field] = self.edit(multi)
        transforms = Gui.getMainWindow().findChild(QtWidgets.QListWidget, "listTransformFeatures")
        transforms.setCurrentRow(0)
        transforms.activated.emit(transforms.currentIndex())
        pump(0.3)
        return multi, sub, field

    def testMultiTransformSubFeatureDeletedThenCancel(self):
        """ops#187: the open sub-task's feature, the Mirrored (the body's shown feature when the
        edit began), deleted from Python; then Cancel. The dialog closes and the document goes
        on (the edit's end showed the deleted feature's view provider again: an access
        violation)."""
        multi, mirrored, field = self.multiTransform("PartDesign::Mirrored")
        name = mirrored.Name
        multi.Transformations = []
        self.body.removeObject(mirrored)
        self.doc.removeObject(name)
        pump(0.3)
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        self.doc.recompute()
        self.assertTrue(multi.isValid(), multi.getStatusString())

    def testPatternReferencePickPendingThenOk(self):
        """ops#186 (2): "Select reference..." chosen and OK pressed without a pick: the
        direction stays."""
        first, second = self.bumps()
        pattern = self.pattern("PartDesign::LinearPattern", [first])
        self.edit(pattern)
        self.selectReference("comboDirection")
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertIsNotNone(pattern.Direction, "OK cleared the direction")
        self.assertEqual(pattern.Direction[0].Name, models.originFeature(self.body, "X_Axis").Name)

    def testMultiTransformSubTaskPickPendingThenOk(self):
        """ops#186 (2): the sub-task's "Select reference..." chosen, then its OK: the sub-pattern's
        direction stays."""
        multi, linear, field = self.multiTransform("PartDesign::LinearPattern")
        self.selectReference("comboDirection")
        ok = Gui.getMainWindow().findChild(QtWidgets.QPushButton, "buttonOK")
        ok.click()
        pump(0.3)
        self.assertIsNotNone(linear.Direction, "the sub-task's OK cleared the direction")
        self.assertEqual(linear.Direction[0].Name, models.originFeature(self.body, "X_Axis").Name)

    def testPatternPickTakenByTheReferencesPanel(self):
        """ops#186 (3): the direction a guessed edge of the redrawn pad (listed by the References
        panel); "Select reference..." chosen, then the panel's Re-pick takes the selection: the
        combo shows the edge again, and OK keeps it."""
        body, pad = self.redrawnPad()
        frontTop = edge("line", direction=X, through=(0, 0, 10))
        [edgeName] = frontTop.one(pad.Shape)
        pattern = self.doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = [pad]
        pattern.Direction = (pad, [edgeName])
        pattern.Length = 30
        pattern.Occurrences = 2
        body.addObject(pattern)
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.redraw()
        self.doc.recompute()
        self.edit(pattern)
        tree = Gui.getMainWindow().findChild(QtWidgets.QTreeWidget, "references")
        self.assertTrue(tree is not None and tree.isVisible(), "no References panel")
        combo, index = self.selectReference("comboDirection")
        tree.setCurrentItem(tree.topLevelItem(0))
        pick = Gui.getMainWindow().findChild(QtWidgets.QPushButton, "buttonPick")
        pick.click()
        pump(0.3)
        self.assertNotEqual(combo.currentIndex(), index, "the combo stays on the pick")
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertIsNotNone(pattern.Direction, "OK cleared the direction")
        self.assertEqual(pattern.Direction[0].Name, pad.Name)

    def testMirroredUpdateViewOffPickPending(self):
        """ops#186 (4): "Update view" off, "Select reference..." chosen, the Originals field
        armed: the combo shows the plane again, and OK keeps it."""
        first, second = self.bumps()
        mirrored = self.pattern("PartDesign::Mirrored", [first])
        [field] = self.edit(mirrored)
        update = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "checkBoxUpdateView")
        update.setChecked(False)
        pump(0.1)
        combo, index = self.selectReference("comboPlane")
        self.arm(field, byFocus=False)
        self.assertTrue(waitFor(lambda: combo.currentIndex() != index), "the combo stays on the pick")
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertIsNotNone(mirrored.MirrorPlane, "OK cleared the plane")
        self.assertEqual(
            mirrored.MirrorPlane[0].Name, models.originFeature(self.body, "YZ_Plane").Name
        )

    def choosePlane(self, text):
        """The visible plane box's entry of that text chosen, as a user does."""
        [combo] = [
            c for c in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, "comboPlane") if c.isVisible()
        ]
        [index] = [i for i in range(combo.count()) if combo.itemText(i) == text]
        self.choose(combo, index)
        self.assertEqual(combo.currentIndex(), index)

    def testMirroredUpdateViewOffPlaneChosenThenOk(self):
        """PR 156 review (1): "Update view" off, the XZ plane chosen in the box: OK writes it
        (the pending-pick cancel showed the old plane again, so apply() wrote YZ back)."""
        first, second = self.bumps()
        mirrored = self.pattern("PartDesign::Mirrored", [first])
        self.edit(mirrored)
        update = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "checkBoxUpdateView")
        update.setChecked(False)
        pump(0.1)
        self.choosePlane("Base XZ-plane")
        self.assertEqual(
            mirrored.MirrorPlane[0].Name, models.originFeature(self.body, "YZ_Plane").Name
        )
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertEqual(
            mirrored.MirrorPlane[0].Name, models.originFeature(self.body, "XZ_Plane").Name
        )
        self.assertTrue(mirrored.isValid(), mirrored.getStatusString())

    def testMultiTransformMirroredPlaneChosenThenOk(self):
        """PR 156 review (1), the sub-task: the MultiTransform's "Update view" off, the
        sub-task's XZ plane chosen, its OK: the sub-feature keeps XZ."""
        multi, mirrored, field = self.multiTransform("PartDesign::Mirrored")
        update = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "checkBoxUpdateView")
        update.setChecked(False)
        pump(0.1)
        self.choosePlane("Base XZ-plane")
        ok = Gui.getMainWindow().findChild(QtWidgets.QPushButton, "buttonOK")
        ok.click()
        pump(0.3)
        self.assertEqual(
            mirrored.MirrorPlane[0].Name, models.originFeature(self.body, "XZ_Plane").Name
        )

    # -- ops#189: Mirrored with "Update view" off ------------------------------------------------

    def mirroredOnRedrawnPad(self):
        """The redrawn pad mirrored on its right face, x = 20 (4000 mm^3), the face guessed after
        the redraw: the References panel lists MirrorPlane. Returns the Mirrored, the panel, and
        the pad's left face (x = 0) by its name now."""
        body, pad = self.redrawnPad()
        right = face(normal=(1, 0, 0))
        mirrored = self.doc.addObject("PartDesign::Mirrored", "Mirrored")
        mirrored.Originals = [pad]
        mirrored.MirrorPlane = (pad, right.one(pad.Shape))
        body.addObject(mirrored)
        self.doc.recompute()
        self.assertAlmostEqual(mirrored.Shape.Volume, 4000, places=3)
        self.redraw()
        self.doc.recompute()
        self.assertTrue(mirrored.isValid(), mirrored.getStatusString())
        rows = {(e["property"], e["index"]) for e in App.getReferenceReport(mirrored)}
        self.assertIn(("MirrorPlane", 0), rows)
        [field] = self.edit(mirrored)
        tree = Gui.getMainWindow().findChild(QtWidgets.QTreeWidget, "references")
        self.assertTrue(tree is not None and tree.isVisible(), "no References panel")
        [left] = face(normal=(-1, 0, 0)).one(pad.Shape)
        return mirrored, pad, field, tree, left

    def updateView(self, on):
        update = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "checkBoxUpdateView")
        update.setChecked(on)
        pump(0.1)

    def testMirroredUpdateViewOffReferencesRepaired(self):
        """ops#189 (1): "Update view" off, the References panel repairs MirrorPlane to the
        pad's left face: the box shows it, and OK keeps it (the box kept the old face, which
        OK wrote back)."""
        mirrored, pad, field, tree, left = self.mirroredOnRedrawnPad()
        self.updateView(False)
        tree.setCurrentItem(tree.topLevelItem(0))
        pick = Gui.getMainWindow().findChild(QtWidgets.QPushButton, "buttonPick")
        pick.click()
        pump(0.3)
        self.pick(pad, left)
        self.assertTrue(
            waitFor(lambda: mirrored.MirrorPlane[1] == [left]), "the panel didn't repair the plane"
        )
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertLink(mirrored.MirrorPlane, pad, [left])

    def testMirroredUpdateViewOnDuringAPick(self):
        """ops#189 (2): "Update view" off, "Select reference..." chosen, then "Update view" on:
        the plane stays (it was set to None from the empty entry)."""
        first, second = self.bumps()
        mirrored = self.pattern("PartDesign::Mirrored", [first])
        self.edit(mirrored)
        self.updateView(False)
        self.selectReference("comboPlane")
        self.updateView(True)
        yz = models.originFeature(self.body, "YZ_Plane")
        self.assertIsNotNone(mirrored.MirrorPlane, "Update view on cleared the plane")
        self.assertEqual(mirrored.MirrorPlane[0].Name, yz.Name)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertEqual(mirrored.MirrorPlane[0].Name, yz.Name)

    def testMirroredUpdateViewOffPlaneChosenThenOtherPaths(self):
        """ops#189 (3): "Update view" off, the XZ plane chosen in the box; then the Originals
        field armed and the References panel's Re-pick, both of which end a pending pick: the
        box keeps XZ, and OK writes it."""
        mirrored, pad, field, tree, left = self.mirroredOnRedrawnPad()
        self.updateView(False)
        self.choosePlane("Base XZ-plane")
        self.arm(field, byFocus=False)
        pump(0.2)
        tree.setCurrentItem(tree.topLevelItem(0))
        pick = Gui.getMainWindow().findChild(QtWidgets.QPushButton, "buttonPick")
        pick.click()
        pump(0.3)
        [combo] = [
            c for c in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, "comboPlane")
            if c.isVisible()
        ]
        self.assertEqual(combo.currentText(), "Base XZ-plane")
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        xz = models.originFeature(mirrored.getParentGeoFeatureGroup(), "XZ_Plane")
        self.assertEqual(mirrored.MirrorPlane[0].Name, xz.Name)

    def testPreviewOpacitySliderEnds(self):
        """PR 156 review (7): the slider at 100 % makes the pocket's preview opaque and its tool
        0.25 (the theme's 0.05 scaled by 5: transparency 0.75); at 0 both vanish (1)."""
        self.defaultOpacity()
        self.box()
        square = models.sketch(self.doc, "Square", models.rectangle(2, 2, 4, 4), self.body, z=10)
        pocket = models.pocket(self.body, square, 3)
        self.doc.recompute()
        self.edit(pocket, count=1)

        def shown():
            """The preview's transparency, then the tool's (the profile's has no faces: 1)."""
            main, *others = self.previewTransparencies(pocket)
            return main, min(others)

        self.opacitySlider().setValue(100)
        pump(0.05)
        main, tool = shown()
        self.assertAlmostEqual(main, 0.0, places=5)
        self.assertAlmostEqual(tool, 0.75, places=5)
        self.opacitySlider().setValue(0)
        pump(0.05)
        self.assertEqual([round(t, 5) for t in self.previewTransparencies(pocket)], [1.0] * 3)

    def testPreviewOpacityDressUpError(self):
        """PR 156 review (7): a fillet in its error state keeps the error opacity (0.05,
        transparency 0.95) when the slider moves."""
        self.defaultOpacity()
        box = self.box()
        fillet = self.addFillet(box, TOP_FRONT.one(box.Shape))
        self.edit(fillet, count=1)
        # Through the panel: its recompute shows the error state
        radius = Gui.getMainWindow().findChild(QtWidgets.QAbstractSpinBox, "filletRadius")
        radius.setProperty("rawValue", 20.0)
        self.assertTrue(waitFor(lambda: not fillet.isValid()), "the fillet didn't fail")
        pump(0.05)
        self.assertAlmostEqual(self.previewTransparencies(fillet)[0], 0.95, places=5)
        self.opacitySlider().setValue(60)
        pump(0.05)
        self.assertAlmostEqual(self.previewTransparencies(fillet)[0], 0.95, places=5)

    def testPreviewOpacityBoolean(self):
        """PR 156 review (7): a Boolean's tool and base shapes scale as a pocket's tool does:
        0.05 at the theme's 20 % (transparency 0.95), 0.15 at 60 % (0.85); its preview shape
        takes 60 % (0.4)."""
        self.defaultOpacity()
        self.box()
        other = self.doc.addObject("PartDesign::Body", "Other")
        tool = self.doc.addObject("PartDesign::AdditiveBox", "ToolBox")
        for prop in ("Length", "Width", "Height"):
            setattr(tool, prop, 10)
        tool.Placement = App.Placement(App.Vector(5, 0, 0), App.Rotation())
        other.addObject(tool)
        self.doc.recompute()
        boolean = self.doc.addObject("PartDesign::Boolean", "Boolean")
        self.body.addObject(boolean)
        boolean.setObjects([other])
        boolean.Type = "Fuse"
        self.doc.recompute()
        self.assertAlmostEqual(boolean.Shape.Volume, 1500, places=6)
        Gui.getDocument(self.doc.Name).setEdit(boolean.Name)
        self.assertTrue(waitFor(lambda: self.opacitySlider() is not None), "no opacity slider")
        settle()

        def others():
            """The transparencies of the tool and base shapes (and the base class's tool)."""
            shapes = [t for t in self.previewTransparencies(boolean)[1:] if t < 0.999]
            self.assertGreaterEqual(len(shapes), 2, "no tool shapes in the preview")
            return shapes

        for transparency in others():
            self.assertAlmostEqual(transparency, 0.95, places=5)
        self.opacitySlider().setValue(60)
        pump(0.05)
        self.assertAlmostEqual(self.previewTransparencies(boolean)[0], 0.4, places=5)
        for transparency in others():
            self.assertAlmostEqual(transparency, 0.85, places=5)

    # -- W6: Revolution, Groove and Helix ---------------------------------------------------------

    def ring(self, groove=False, core=False):
        """The Ring model: the profile, the datum lines at x = 0 and x = -1, the walls; with a
        groove, its cylinder first (r 5); with a core, a cylinder r 1 first (2 pi: an additive
        revolution up to a face needs a base solid: ops#191)."""
        self.body = models.body(self.doc)
        if groove or core:
            cylinder = self.doc.addObject("PartDesign::AdditiveCylinder", "Cylinder")
            self.body.addObject(cylinder)
            cylinder.Radius = 5 if groove else 1
            cylinder.Height = 2
        xz = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(1, 0, 0), 90))
        self.ringSketch = models.sketch(
            self.doc, "Ring", models.rectangle(1, 0, 3, 2), self.body, placement=xz
        )
        self.lines = {}
        for name, x in (("LineAt0", 0), ("LineAtMinus1", -1)):
            line = self.body.newObject("PartDesign::Line", name)
            line.MapMode = "Deactivated"
            line.Placement = App.Placement(App.Vector(x, 0, 0), App.Rotation())
            self.lines[x] = line
        self.walls = []
        for name in ("Wall1", "Wall2"):
            wall = self.body.newObject("PartDesign::Plane", name)
            wall.MapMode = "Deactivated"
            wall.Placement = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(0, 1, 0), 90))
            self.walls.append(wall)
        self.doc.recompute()
        return self.ringSketch

    def revolution(self, groove=False, core=False):
        sketch = self.ring(groove, core)
        typeName = "PartDesign::Groove" if groove else "PartDesign::Revolution"
        feature = self.body.newObject(typeName, "Groove" if groove else "Revolution")
        feature.Profile = sketch
        feature.ReferenceAxis = (sketch, ["V_Axis"])
        feature.Angle = 360
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        expected = 34 * math.pi if groove else (18 if core else 16) * math.pi
        self.assertAlmostEqual(feature.Shape.Volume, expected, places=3)
        return feature

    def axisCombo(self):
        return Gui.getMainWindow().findChild(QtWidgets.QComboBox, "axis")

    def pickedAxis(self, groove):
        """T21 / T36: "Select reference..." shows the axis row, armed; the x = -1 line picked is
        its entry (exact) and the axis; the V axis chosen again hides the row."""
        feature = self.revolution(groove)
        self.edit(feature, count=0)
        combo = self.axisCombo()
        self.assertFalse(any("?" in combo.itemText(i) for i in range(combo.count())))
        field = findField("fieldReferenceAxis")
        self.assertIsNotNone(field, "the axis has no row")
        self.assertFalse(field.isVisible(), "the row shows while the axis is a choice")

        combo_, index = self.selectReference("axis")
        self.assertTrue(waitFor(lambda: field.isVisible() and armed(field)), "the row isn't armed")
        self.pick(self.lines[-1], "")
        self.assertLink(feature.ReferenceAxis, self.lines[-1], [])
        self.assertTrue(waitFor(lambda: texts(field) == [self.lines[-1].Label]), texts(field))
        self.assertEqual(states(field), ["exact"])
        self.assertEqual(combo.currentIndex(), index)
        self.assertVolume(feature, 26 * math.pi if groove else 24 * math.pi)

        [vAxis] = [i for i in range(combo.count()) if combo.itemText(i) == "Vertical sketch axis"]
        self.choose(combo, vAxis)
        self.assertTrue(waitFor(lambda: not field.isVisible()), "the row stays after a choice")
        self.assertFalse(armed(field))
        self.assertLink(feature.ReferenceAxis, self.ringSketch, ["V_Axis"])
        self.assertVolume(feature, 34 * math.pi if groove else 16 * math.pi)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertLink(feature.ReferenceAxis, self.ringSketch, ["V_Axis"])

    def testRevolutionPickedAxis(self):
        self.pickedAxis(groove=False)

    def testGroovePickedAxis(self):
        self.pickedAxis(groove=True)

    def testRevolutionAxisGuessed(self):
        """T22, B19: the axis an edge of a sketch that is drawn again: the row shows it guessed,
        no "?" entry in the combo; Accept guess makes it exact."""
        feature = self.revolution()
        self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = True
        xz = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(1, 0, 0), 90))
        axisSketch = models.sketch(
            self.doc, "AxisSketch", models.polyline([(0, -1), (0, 5)]), self.body, placement=xz
        )
        self.doc.recompute()
        feature.ReferenceAxis = (axisSketch, ["Edge1"])
        self.doc.recompute()
        self.assertAlmostEqual(feature.Shape.Volume, 16 * math.pi, places=3)
        axisSketch.deleteAllGeometry()
        axisSketch.addGeometry(models.polyline([(0, 5), (0, -1)]), False)
        self.doc.recompute()

        self.edit(feature, count=1)
        combo = self.axisCombo()
        self.assertFalse(
            any("?" in combo.itemText(i) for i in range(combo.count())),
            [combo.itemText(i) for i in range(combo.count())],
        )
        field = findField("fieldReferenceAxis")
        self.assertTrue(field.isVisible())
        # The line drawn again in place, the other way round: found again by geometry, a guess
        self.assertEqual(states(field), ["guessed"])
        menu = openMenu(field, 0)
        menuActions(menu)["Accept guess"].trigger()
        menu.close()
        pump(0.3)
        self.assertTrue(waitFor(lambda: states(field) == ["exact"]), states(field))
        self.assertVolume(feature, 16 * math.pi)

    def upToWalls(self, groove):
        """T23 / T36: both sides up to a face, each side's field writes its own property; a
        whole sketch is refused with a reason (B20). Each wall is the YZ plane, met a quarter
        turn each way: 2 x 4 pi of the ring (Pappus: 2 pi x 2 x 4 / 4 each), added to the core
        (2 pi) or taken from the cylinder (50 pi)."""
        feature = self.revolution(groove, core=not groove)
        self.edit(feature, count=0)
        sides = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "sidesMode")
        self.choose(sides, 1)
        first = findField("fieldUpToFace")
        second = findField("fieldUpToFace2")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertFalse(first.isVisible() or second.isVisible())

        mode = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "changeMode")
        self.choose(mode, 3)
        self.assertTrue(waitFor(lambda: first.isVisible() and armed(first)), "side 1 isn't armed")
        self.pick(self.ringSketch, "")
        self.assertIsNone(feature.UpToFace)
        self.assertIn("sketch", statusText().lower())
        self.assertTrue(armed(first))
        self.pick(self.walls[0], "")
        self.assertLink(feature.UpToFace, self.walls[0], [])

        mode2 = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "changeMode2")
        self.choose(mode2, 3)
        self.assertTrue(waitFor(lambda: second.isVisible() and armed(second)), "side 2 isn't armed")
        self.assertFalse(armed(first))
        self.pick(self.walls[1], "")
        self.assertLink(feature.UpToFace2, self.walls[1], [])
        self.assertLink(feature.UpToFace, self.walls[0], [])
        self.assertVolume(feature, 42 * math.pi if groove else 10 * math.pi)

        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertLink(feature.UpToFace, self.walls[0], [])
        self.assertLink(feature.UpToFace2, self.walls[1], [])

    def testRevolutionUpToFaces(self):
        self.upToWalls(groove=False)

    def testGrooveUpToFaces(self):
        self.upToWalls(groove=True)

    def visibilities(self, *objs):
        return tuple(obj.ViewObject.isVisible() for obj in objs)

    def testRevolutionFieldsAndVisibility(self):
        """T24: the start reference armed, an angle change keeps it armed (B17); the axis row
        armed after it, then disarmed (Esc): the base solid (the core) and the revolution are as
        the edit showed them (B16: the second start of a pick took the shown base for the edited
        feature, which stayed hidden). B15 is testReferencesPanelDisarmsTheAxisRow."""
        feature = self.revolution(core=True)
        core = self.doc.getObject("Cylinder")
        self.edit(feature, count=0)
        shown = self.visibilities(feature, core, self.ringSketch)
        start = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "startMode")
        self.choose(start, 2)
        startField = findField("fieldStartReference")
        self.assertTrue(waitFor(lambda: startField.isVisible() and armed(startField)))
        angle = Gui.getMainWindow().findChild(QtWidgets.QWidget, "revolveAngle")
        angle.setProperty("rawValue", 270)
        pump(0.2)
        self.assertAlmostEqual(feature.Angle, 270, places=6)
        self.assertTrue(armed(startField), "an angle change disarmed the field")

        field = findField("fieldReferenceAxis")
        self.selectReference("axis")
        self.assertTrue(waitFor(lambda: armed(field)), "the axis row isn't armed")
        self.assertFalse(armed(startField))
        self.assertTrue(self.ringSketch.ViewObject.isVisible(), "the profile isn't shown")
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(field)), "Esc left the row armed")
        self.assertTrue(Gui.Control.activeDialog())
        self.assertEqual(
            self.visibilities(feature, core, self.ringSketch),
            shown,
            "the revolution, its base and its sketch aren't as the edit showed them",
        )
        self.assertLink(feature.ReferenceAxis, self.ringSketch, ["V_Axis"])

    def coil(self):
        """The Coil model: the Ring's profile, a helix of pitch 5 and height 10 (2 turns) about
        the V axis: 2 pi x 2 x 4 x 2 = 32 pi. Marked edited, as a helix made in its dialog is:
        an unedited one gets the dialog's proposed pitch and height when it opens."""
        sketch = self.ring()
        helix = self.body.newObject("PartDesign::AdditiveHelix", "Helix")
        helix.Profile = sketch
        helix.ReferenceAxis = (sketch, ["V_Axis"])
        helix.Pitch = 5
        helix.Height = 10
        helix.HasBeenEdited = True
        self.doc.recompute()
        self.assertTrue(helix.isValid(), helix.getStatusString())
        self.assertAlmostEqual(helix.Shape.Volume / (32 * math.pi), 1, delta=1e-3)
        return sketch, helix

    def helixPreview(self):
        """The additive helix's preview on, restored after the test. With it on, the stock axis
        pick hid the helix itself (startReferenceSelection is given the feature, not its profile)
        and left a hidden profile hidden, so its lines couldn't be picked."""
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        old = prefs.GetBool("AdditiveHelixPreview", False)
        prefs.SetBool("AdditiveHelixPreview", True)
        self.addCleanup(prefs.SetBool, "AdditiveHelixPreview", old)

    def testHelixAxisRow(self):
        """T25, B18: with the preview on and the profile sketch hidden, the helix's axis row armed
        shows it (the stock pick left it hidden); the x = -1 line picked: 48 pi, the row disarmed
        and the sketch hidden again; OK closes the dialog (B15's throw)."""
        self.helixPreview()
        sketch, helix = self.coil()
        self.edit(helix, count=0)
        sketch.ViewObject.Visibility = False
        pump(0.1)
        field = findField("fieldReferenceAxis")
        self.selectReference("axis")
        self.assertTrue(waitFor(lambda: armed(field)), "the axis row isn't armed")
        pump(0.3)
        self.assertTrue(sketch.ViewObject.isVisible(), "the profile isn't shown")
        self.pick(self.lines[-1], "")
        self.assertTrue(waitFor(lambda: not armed(field)), "the row stays armed")
        pump(0.2)
        self.assertFalse(sketch.ViewObject.isVisible(), "the sketch stays shown after the pick")
        self.assertLink(helix.ReferenceAxis, self.lines[-1], [])
        self.doc.recompute()
        self.assertAlmostEqual(helix.Shape.Volume / (48 * math.pi), 1, delta=1e-3)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertLink(helix.ReferenceAxis, self.lines[-1], [])

    def testHelixReferencePickTakenByThePanel(self):
        """B15: the axis row armed, the References panel takes the selection (its gate goes):
        the row disarms and OK still closes."""
        sketch, helix = self.coil()
        self.edit(helix, count=0)
        field = findField("fieldReferenceAxis")
        self.selectReference("axis")
        self.assertTrue(waitFor(lambda: armed(field)))
        Gui.Selection.removeSelectionGate()
        pump(0.2)
        self.assertFalse(armed(field), "the row stays armed without its gate")
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertLink(helix.ReferenceAxis, sketch, ["V_Axis"])

    # -- PR 159 review round 1 -----------------------------------------------------------------

    def testRevolutionStartReferenceWholeSketch(self):
        """Review (1): a whole sketch is a start reference again (its plane; only an up-to-face
        refuses it). The ring turned 90 degrees about Z from a sketch whose plane holds Z at 60
        degrees: 4 pi (Pappus), and the solid's centroid lies 45 degrees from that plane, where
        from the ring's own plane it lies at 45 degrees from X (15 degrees from that plane)."""
        feature = self.revolution()
        feature.Angle = 90
        self.doc.recompute()
        self.assertAlmostEqual(feature.Shape.Volume, 4 * math.pi, places=3)
        plane = App.Rotation(App.Vector(0, 0, 1), 60).multiply(
            App.Rotation(App.Vector(1, 0, 0), 90)
        )
        reference = models.sketch(
            self.doc,
            "StartPlane",
            models.rectangle(1, 0, 2, 1),
            self.body,
            placement=App.Placement(App.Vector(), plane),
        )
        self.doc.recompute()

        def fromPlane():
            # The centroid's angle from the plane's trace (the line at 60 degrees), in 0..90
            centre = feature.Shape.Solids[0].CenterOfMass
            azimuth = math.degrees(math.atan2(centre.y, centre.x))
            return abs((azimuth - 60 + 90) % 180 - 90)

        self.assertNotAlmostEqual(fromPlane(), 45, places=1)
        self.edit(feature, count=0)
        start = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "startMode")
        self.choose(start, 2)
        startField = findField("fieldStartReference")
        self.assertTrue(waitFor(lambda: startField.isVisible() and armed(startField)))
        self.pick(reference, "")
        self.assertLink(feature.StartReference, reference, [])
        self.assertVolume(feature, 4 * math.pi)
        self.assertAlmostEqual(fromPlane(), 45, places=3)

    def testPadDirectionDatumLine(self):
        """Review (2): a datum line picked as the pad's direction is linked whole as [""] (it was
        [], which gives no direction). The line leans 45 degrees towards X: the square 2..4
        padded 3 along the normal is sheared, its top at x 5..7; the volume is the prism's."""
        box, pad = self.padOnBox(toFace=False)
        line = self.body.newObject("PartDesign::Line", "Leaning")
        line.MapMode = "Deactivated"
        line.Placement = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(0, 1, 0), 45))
        self.doc.recompute()
        self.assertAlmostEqual(pad.AddSubShape.BoundBox.XMax, 4, places=4)
        self.edit(pad, count=1)
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "directionCB")
        combo.setCurrentIndex(1)
        combo.activated.emit(1)
        pump(0.2)
        field = findField("fieldReferenceAxis")
        self.assertTrue(waitFor(lambda: armed(field)), "the direction field isn't armed")
        self.pick(line, "")
        self.assertEqual(pad.ReferenceAxis[0].Name, "Leaning")
        self.assertEqual(pad.ReferenceAxis[1], [""])
        self.assertVolume(pad, 1012)
        self.assertAlmostEqual(pad.AddSubShape.BoundBox.XMax, 7, places=4)

    def testAxisRowDeleteKeepsTheAxis(self):
        """Review (5): Delete in the axis row (armed by "Select reference...", showing the axis
        there is) doesn't clear the axis: refused with a message."""
        feature = self.revolution()
        self.edit(feature, count=0)
        field = findField("fieldReferenceAxis")
        self.selectReference("axis")
        self.assertTrue(waitFor(lambda: armed(field)), "the axis row isn't armed")
        self.assertTrue(focus(entries(field)))
        entries(field).setCurrentRow(0)
        key(QtCore.Qt.Key_Delete)
        self.assertLink(feature.ReferenceAxis, self.ringSketch, ["V_Axis"])
        self.assertVolume(feature, 16 * math.pi)
        self.assertIn("empty", field.findChild(QtWidgets.QLabel, "status").text())

    # Flaky (ops#215): fails now and then in a full TestPartDesignGui run, "0 != 5" in selectReference(),
    # and passes alone straight after
    def testAxisComboFollowsFieldUndo(self):
        """Review (6): the x = -1 line picked in the row, then the row's own undo (Ctrl+Z, the row
        disarmed): the axis is the V axis again and the box shows it, the row hidden."""
        feature = self.revolution()
        self.edit(feature, count=0)
        combo = self.axisCombo()
        field = findField("fieldReferenceAxis")
        self.selectReference("axis")
        self.assertTrue(waitFor(lambda: armed(field)))
        self.pick(self.lines[-1], "")
        self.assertLink(feature.ReferenceAxis, self.lines[-1], [])
        self.assertTrue(focus(entries(field)))
        field.setProperty("armed", False)
        pump(0.1)
        self.assertFalse(armed(field))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(
            waitFor(lambda: feature.ReferenceAxis[1] == ["V_Axis"]), feature.ReferenceAxis
        )
        self.assertTrue(
            waitFor(lambda: combo.currentText() == "Vertical sketch axis"), combo.currentText()
        )
        self.assertFalse(field.isVisible(), "the row stays under the box")

    def testHelixProfileHiddenWhenDialogCloses(self):
        """Review (7): the profile hidden, the axis row armed shows it; the dialog closed
        (Control.closeDialog) while the row is armed: the profile is hidden again."""
        sketch, helix = self.coil()
        self.edit(helix, count=0)
        sketch.ViewObject.Visibility = False
        pump(0.1)
        field = findField("fieldReferenceAxis")
        self.selectReference("axis")
        self.assertTrue(waitFor(lambda: armed(field)))
        pump(0.3)
        self.assertTrue(sketch.ViewObject.isVisible())
        Gui.Control.closeDialog()
        pump(0.2)
        flushDeletes()
        pump(0.2)
        self.assertFalse(sketch.ViewObject.isVisible(), "the profile stays shown")

    def testReferencesPanelDisarmsTheAxisRow(self):
        """B15 (review 4): the axis row armed, the References panel takes the selection (its
        selectionTaken, which its picks and highlights send first): the row disarms; the guessed
        axis, no choice of the box, stays in the row under "Select reference..."; OK closes."""
        feature = self.revolution()
        self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = True
        xz = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(1, 0, 0), 90))
        axisSketch = models.sketch(
            self.doc, "AxisSketch", models.polyline([(0, -1), (0, 5)]), self.body, placement=xz
        )
        self.doc.recompute()
        feature.ReferenceAxis = (axisSketch, ["Edge1"])
        self.doc.recompute()
        axisSketch.deleteAllGeometry()
        axisSketch.addGeometry(models.polyline([(0, 5), (0, -1)]), False)
        self.doc.recompute()
        self.edit(feature, count=1)
        field = findField("fieldReferenceAxis")
        self.arm(field, byFocus=True)
        [panel] = [
            w
            for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget)
            if w.metaObject().className() == "PartDesignGui::TaskReferences"
        ]
        self.assertTrue(QtCore.QMetaObject.invokeMethod(panel, "selectionTaken"))
        pump(0.2)
        self.assertFalse(armed(field), "the row stays armed")
        # The guessed axis is no choice of the box: the box shows "Select reference...", the row
        # under it holds the axis
        self.assertTrue(self.axisCombo().currentText().startswith("Select reference"))
        self.assertTrue(field.isVisible())
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertEqual(feature.ReferenceAxis[0].Name, "AxisSketch")
    # -- W7: Loft and Pipe sections (T26-T30, T35; B8, B11-B14, B21) -------------------------------

    def squareSketch(self, name, half, z):
        """A square sketch centred on Z, side 2 x half, at height z."""
        return models.sketch(
            self.doc, name, models.rectangle(-half, -half, half, half), self.body, z=z
        )

    def tower(self, sections=(), labels=None):
        """The Tower model: the profile 10 x 10 at z = 0, S1 20 x 20 at z = 10, S2 10 x 10 at
        z = 20; a loft of the profile and the sections given (names, in order). With labels, the
        sections are labelled so (DuplicateLabels on while they are made)."""
        self.body = models.body(self.doc)
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/Document")
        duplicates = prefs.GetBool("DuplicateLabels", False)
        prefs.SetBool("DuplicateLabels", True)
        try:
            self.towerProfile = self.squareSketch("Profile", 5, 0)
            self.s1 = self.squareSketch("S1", 10, 10)
            self.s2 = self.squareSketch("S2", 5, 20)
            if labels:
                self.s1.Label, self.s2.Label = labels
        finally:
            prefs.SetBool("DuplicateLabels", duplicates)
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = self.towerProfile
        named = {"S1": self.s1, "S2": self.s2}
        loft.Sections = [(named[n], [""]) for n in sections]
        self.doc.recompute()
        return loft

    def sliceArea(self, shape, z):
        import Part

        return sum(Part.Face(wire).Area for wire in shape.slice(App.Vector(0, 0, 1), z))

    def assertThroughSection(self, feature, z, area):
        """The feature is valid and its cross-section at z is the section's (it passes through
        it)."""
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertAlmostEqual(self.sliceArea(feature.Shape, z), area, places=3)

    def assertNotThroughSection(self, feature, z, area):
        self.doc.recompute()
        if feature.isValid():
            self.assertNotAlmostEqual(self.sliceArea(feature.Shape, z), area, places=1)

    def sectionNames(self, feature):
        return [obj.Name for obj, subs in feature.Sections]

    def sectionsField(self):
        field = findField("fieldSections")
        self.assertIsNotNone(field, "no sections field")
        return field

    def testLoftSectionsReorderByKey(self):
        """T26, T35: a loft with no sections opens with its sections field armed; S2 picked before
        S1 makes no loft through S1 (its slice at z = 10 isn't 400); Alt+Up on S1 puts it first:
        [S1, S2], and the slice at z = 10 is S1's 20 x 20 = 400."""
        loft = self.tower()
        self.edit(loft, count=2)
        field = self.sectionsField()
        self.assertTrue(waitFor(lambda: armed(field)), "the sections field isn't armed on open")
        self.assertEqual(texts(findField("fieldProfile")), ["Profile"])
        self.pick(self.s2, "")
        self.pick(self.s1, "Edge2")  # an edge of a sketch: the sketch whole
        self.assertEqual(self.sectionNames(loft), ["S2", "S1"])
        self.assertEqual([list(subs) for obj, subs in loft.Sections], [[""], [""]])
        self.assertEqual(texts(field), ["1. S2", "2. S1"])
        self.assertTrue(armed(field), "a pick disarmed the field")
        self.assertNotThroughSection(loft, 10, 400)

        clickRow(field, 1)
        key(QtCore.Qt.Key_Up, QtCore.Qt.AltModifier)
        self.assertTrue(waitFor(lambda: self.sectionNames(loft) == ["S1", "S2"]), loft.Sections)
        self.assertEqual(texts(field), ["1. S1", "2. S2"])
        self.assertEqual(entries(field).currentRow(), 0, "the moved entry isn't the current one")
        self.assertThroughSection(loft, 10, 400)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertEqual(self.sectionNames(loft), ["S1", "S2"])
        self.assertThroughSection(loft, 10, 400)

    def testLoftSectionsReorderByDragAndMenu(self):
        """T27: a drag (the list's rows moved) and the menu's Move up each reorder in one write;
        Ctrl+Z steps back over each."""
        loft = self.tower(("S2", "S1"))
        self.edit(loft, count=2)
        field = self.sectionsField()
        self.assertEqual(texts(field), ["1. S2", "2. S1"])
        model = entries(field).model()
        self.assertTrue(model.moveRow(QtCore.QModelIndex(), 1, QtCore.QModelIndex(), 0))
        self.assertTrue(waitFor(lambda: self.sectionNames(loft) == ["S1", "S2"]), loft.Sections)
        self.assertTrue(waitFor(lambda: texts(field) == ["1. S1", "2. S2"]), texts(field))
        self.assertThroughSection(loft, 10, 400)

        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: self.sectionNames(loft) == ["S2", "S1"]), loft.Sections)

        menu = openMenu(field, 1)
        actions = menuActions(menu)
        self.assertFalse(actions["Move down"].isEnabled())
        actions["Move up"].trigger()
        menu.close()
        self.assertTrue(waitFor(lambda: self.sectionNames(loft) == ["S1", "S2"]), loft.Sections)
        self.assertThroughSection(loft, 10, 400)
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: self.sectionNames(loft) == ["S2", "S1"]), loft.Sections)
        key(QtCore.Qt.Key_Y, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: self.sectionNames(loft) == ["S1", "S2"]), loft.Sections)

    def testLoftSectionsOfOneLabel(self):
        """T28, B8: two sections of one Label; Delete on the second takes out that one (the old
        list matched rows by label and the property by object, then wrote past its end on a
        reorder); picked again and moved up, the list and the property agree."""
        loft = self.tower(("S1", "S2"), labels=("Section", "Section"))
        self.assertThroughSection(loft, 10, 400)
        self.edit(loft, count=2)
        field = self.sectionsField()
        self.assertEqual(texts(field), ["1. Section", "2. Section"])
        clickRow(field, 1)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: self.sectionNames(loft) == ["S1"]), loft.Sections)
        self.assertEqual(texts(field), ["1. Section"])
        self.pick(self.s2, "")
        self.assertEqual(self.sectionNames(loft), ["S1", "S2"])
        clickRow(field, 1)
        key(QtCore.Qt.Key_Up, QtCore.Qt.AltModifier)
        self.assertTrue(waitFor(lambda: self.sectionNames(loft) == ["S2", "S1"]), loft.Sections)
        self.assertEqual(len(texts(field)), 2)
        self.assertEqual([entries(field).item(i).toolTip() for i in range(2)], ["", ""])
        self.assertTrue(Gui.Control.activeDialog())

    def testLoftDeleteRemovesAllSelected(self):
        """B12 (ops#162): Delete with both sections selected takes out both (the old loft took
        only the current row)."""
        loft = self.tower(("S1", "S2"))
        self.edit(loft, count=2)
        field = self.sectionsField()
        clickRow(field, 0)
        clickRow(field, 1, QtCore.Qt.ControlModifier)
        self.assertEqual(len(entries(field).selectedItems()), 2)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: self.sectionNames(loft) == []), loft.Sections)
        self.assertEqual(texts(field), [])

    def testLoftSectionPickTogglesAndReplaces(self):
        """T29, B21: S1 picked again comes out of the list (the field stays armed); picked again
        it is last; a point of it picked replaces its entry, not another one."""
        loft = self.tower(("S1", "S2"))
        self.edit(loft, count=2)
        field = self.sectionsField()
        self.arm(field, byFocus=True)
        self.pick(self.s1, "")
        self.assertEqual(self.sectionNames(loft), ["S2"])
        self.assertTrue(armed(field), "a pick that removes disarmed the field")
        self.pick(self.s1, "")
        self.assertEqual(self.sectionNames(loft), ["S2", "S1"])
        self.pick(self.s1, "Vertex1")
        self.assertEqual(self.sectionNames(loft), ["S2", "S1"])
        self.assertEqual([list(subs) for obj, subs in loft.Sections], [[""], ["Vertex1"]])
        self.assertEqual(texts(field), ["1. S2", "2. S1:Vertex1"])
        # The profile is no section, and a section no profile: refused with the reason
        self.pick(self.towerProfile, "")
        self.assertEqual(self.sectionNames(loft), ["S2", "S1"])
        self.assertIn("profile", statusText().lower())

    def testLoftProfileField(self):
        """Q8 (a): the profile is its own field above the sections; a pick replaces it, a section
        is refused as profile."""
        loft = self.tower(("S1", "S2"))
        self.edit(loft, count=2)
        profile, sections = fields()
        self.assertEqual(profile.objectName(), "fieldProfile")
        self.assertEqual(sections.objectName(), "fieldSections")
        self.arm(profile, byFocus=True)
        self.pick(self.s1, "")
        self.assertEqual(loft.Profile[0].Name, "Profile")
        self.assertIn("section", statusText().lower())
        other = self.squareSketch("Other", 5, -10)
        self.doc.recompute()
        self.pick(other, "Edge1")  # a sketch whole
        self.assertLink(loft.Profile, other, [])
        self.assertEqual(texts(profile), ["Other"])

    def sketchColours(self, sketch):
        vp = sketch.ViewObject
        return list(vp.LineColorArray)

    def testLoftHighlightLeavesLineColours(self):
        """B14, PR 163 review 11: armed, the field colours the whole section S1 in the Coin nodes,
        all four edges in the entries' colour; disarmed, and after the dialog closed while armed,
        S1 is drawn in its own per-edge colours again. LineColorArray is never written."""
        loft = self.tower(("S1", "S2"))
        colours = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 0.0)]
        self.s1.ViewObject.LineColorArray = colours
        before = self.sketchColours(self.s1)
        pump(0.1)
        self.assertEqual(self.edgeColours(self.s1), colours)
        self.edit(loft, count=2)
        field = self.sectionsField()

        def lit():
            drawn = self.edgeColours(self.s1)
            return len(drawn) == 4 and len(set(drawn)) == 1 and drawn[0] in (MAGENTA, CURRENT)

        self.arm(field, byFocus=False)
        self.assertTrue(waitFor(lit), self.edgeColours(self.s1))
        self.assertEqual(self.sketchColours(self.s1), before)
        field.setProperty("armed", False)
        pump(0.2)
        self.assertEqual(self.edgeColours(self.s1), colours, "disarmed: not S1's own colours")
        self.assertEqual(self.sketchColours(self.s1), before)
        self.arm(field, byFocus=False)
        self.assertTrue(waitFor(lit), self.edgeColours(self.s1))
        Gui.Control.closeDialog()
        pump(0.2)
        flushDeletes()
        pump(0.2)
        self.assertEqual(self.edgeColours(self.s1), colours, "closed: not S1's own colours")
        self.assertEqual(self.sketchColours(self.s1), before)

    def testLoftCancelRestoresVisibility(self):
        """B13 (the loft too): the sections hidden before the edit show during it; Cancel hides
        them again, a section picked during the edit included."""
        loft = self.tower(("S1",))
        for sketch in (self.towerProfile, self.s1, self.s2):
            sketch.ViewObject.Visibility = False
        # The transaction a double click opens: Cancel undoes the edit's writes through it
        self.doc.openTransaction("Edit Loft")
        self.edit(loft, count=2)
        self.assertTrue(self.s1.ViewObject.Visibility)
        field = self.sectionsField()
        self.arm(field, byFocus=True)
        self.pick(self.s2, "")
        self.assertEqual(self.sectionNames(loft), ["S1", "S2"])
        self.assertTrue(self.s2.ViewObject.Visibility, "a picked section isn't shown")
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump(0.2)
        self.assertEqual(self.sectionNames(loft), ["S1"])
        self.assertFalse(self.s1.ViewObject.Visibility, "Cancel left the section shown")
        self.assertFalse(self.s2.ViewObject.Visibility, "Cancel left the picked section shown")

    def testNewLoftArmsItsSections(self):
        """T35: PartDesign_AdditiveLoft on a selected sketch makes a loft with that profile and
        opens its dialog with the sections field armed."""
        self.body = models.body(self.doc)
        profile = self.squareSketch("Profile", 5, 0)
        self.doc.recompute()
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, profile.Name)
        Gui.runCommand("PartDesign_AdditiveLoft")
        self.assertTrue(waitFor(lambda: len(fields()) == 2), "the loft's fields")
        settle()
        field = self.sectionsField()
        self.assertTrue(waitFor(lambda: armed(field)), "the new loft's sections aren't armed")
        loft = self.doc.getObject("AdditiveLoft")
        self.assertEqual(loft.Profile[0].Name, "Profile")
        self.assertEqual(loft.Sections, [])

    def rod(self, transformation="Multisection"):
        """The Rod model: the profile 2 x 2 centred on Z at z = 0; a spine sketch in the XZ plane
        of two lines along Z, 10 and 20 long; the sections 4 x 4 at z = 10 (S10) and 2 x 2 at
        z = 30 (S30); a pipe of the profile along the whole spine, with no sections yet."""
        self.body = models.body(self.doc)
        self.rodProfile = self.squareSketch("Profile", 1, 0)
        xz = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(1, 0, 0), 90))
        self.spine = models.sketch(
            self.doc, "Spine", models.polyline([(0, 0), (0, 10), (0, 30)]), self.body, placement=xz
        )
        self.s10 = self.squareSketch("S10", 2, 10)
        self.s30 = self.squareSketch("S30", 1, 30)
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.rodProfile
        pipe.Spine = self.spine
        pipe.Transformation = transformation
        self.doc.recompute()
        return pipe

    def testPipeSectionsReorderAndPointLast(self):
        """T30, T35: a multisection pipe opens on its page, the empty sections field armed; S30
        picked before S10, then Alt+Up on S10: [S10, S30], the slice at z = 10 is S10's 4 x 4 =
        16. (The sweep places each section where it lies on the spine: [S30, S10] slices so too,
        so the order isn't told from the shape here.) A point of S30 replaces it, last; moved up
        it is refused with the reason (only the last section can be a point)."""
        pipe = self.rod()
        self.edit(pipe, count=3)
        field = self.sectionsField()
        self.assertTrue(field.isVisible(), "the multisection page isn't shown")
        self.assertTrue(waitFor(lambda: armed(field)), "the sections field isn't armed on open")
        self.pick(self.s30, "")
        self.pick(self.s10, "")
        self.assertEqual(self.sectionNames(pipe), ["S30", "S10"])
        self.assertEqual(texts(field), ["1. S30", "2. S10"])
        clickRow(field, 1)
        key(QtCore.Qt.Key_Up, QtCore.Qt.AltModifier)
        self.assertTrue(waitFor(lambda: self.sectionNames(pipe) == ["S10", "S30"]), pipe.Sections)
        self.assertThroughSection(pipe, 10, 16)

        self.pick(self.s30, "Vertex1")
        self.assertEqual([list(subs) for obj, subs in pipe.Sections], [[""], ["Vertex1"]])
        clickRow(field, 1)
        key(QtCore.Qt.Key_Up, QtCore.Qt.AltModifier)
        pump(0.2)
        self.assertEqual(self.sectionNames(pipe), ["S10", "S30"])
        status = field.findChild(QtWidgets.QLabel, "status")
        self.assertIn("last section", status.text())
        self.assertEqual(texts(field), ["1. S10", "2. S30:Vertex1"])

    def testPipeDeleteRemovesAllSelected(self):
        """B11, B12: no Remove Section toggle; Delete removes every selected section."""
        pipe = self.rod()
        pipe.Sections = [(self.s10, [""]), (self.s30, [""])]
        self.assertThroughSection(pipe, 10, 16)
        self.edit(pipe, count=3)
        buttons = Gui.getMainWindow().findChildren(QtWidgets.QToolButton)
        self.assertFalse([b for b in buttons if b.text() == "Remove Section"])
        field = self.sectionsField()
        clickRow(field, 0)
        clickRow(field, 1, QtCore.Qt.ControlModifier)
        self.assertEqual(len(entries(field).selectedItems()), 2)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: pipe.Sections == []), pipe.Sections)

    def testPipeConstantModeArmsOnMultisection(self):
        """T35 for the pipe: a constant pipe's sections field is hidden and not armed; switching to
        Multisection arms it (it has no sections)."""
        pipe = self.rod("Constant")
        self.edit(pipe, count=2)
        field = findField("fieldSections")
        self.assertFalse(field.isVisible())
        self.assertFalse(armed(field))
        box = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "comboBoxScaling")
        self.choose(box, 1)
        self.assertTrue(
            waitFor(lambda: field.isVisible() and armed(field)), "not armed on Multisection"
        )
        self.pick(self.s10, "")
        self.assertEqual(self.sectionNames(pipe), ["S10"])

    def pipeVisibility(self, ok):
        """B13: on Cancel the sections each go back to their own visibility, not to the
        profile's, and the spine too. On OK the spine goes back and the sections are hidden, as
        the loft's are (PR 163 review, Low 2: the user's answer)."""
        pipe = self.rod()
        pipe.Sections = [(self.s10, [""]), (self.s30, [""])]
        self.doc.recompute()
        self.rodProfile.ViewObject.Visibility = True
        self.spine.ViewObject.Visibility = False
        self.s10.ViewObject.Visibility = False
        self.s30.ViewObject.Visibility = True
        self.edit(pipe, count=3)
        self.assertTrue(self.s10.ViewObject.Visibility)
        self.assertTrue(self.spine.ViewObject.Visibility)
        button = QtWidgets.QDialogButtonBox.Ok if ok else QtWidgets.QDialogButtonBox.Cancel
        taskButton(button).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog didn't close")
        pump(0.2)
        self.assertFalse(self.s10.ViewObject.Visibility, "a hidden section is shown after")
        if ok:
            self.assertFalse(self.s30.ViewObject.Visibility, "OK left a section shown")
        else:
            self.assertTrue(self.s30.ViewObject.Visibility, "a shown section is hidden after")
        self.assertFalse(self.spine.ViewObject.Visibility, "the spine is shown after")

    def testPipeOkRestoresSectionVisibility(self):
        self.pipeVisibility(ok=True)

    def testPipeCancelRestoresVisibility(self):
        self.pipeVisibility(ok=False)

    # -- PR 163 review round 1 ----------------------------------------------------------------

    def testLoftSectionsDragOfTwo(self):
        """H1: two entries dropped together. Qt's drop moves them one row at a time, each move
        signalled, before any event runs: S1 and S2 of [S3, S1, S2] dropped on top give
        [S1, S2, S3] in one write (the slice at z = 10 is S1's 20 x 20 = 400), and one Ctrl+Z puts
        back [S3, S1, S2]."""
        loft = self.tower()
        s3 = self.squareSketch("S3", 5, 30)
        loft.Sections = [(s3, [""]), (self.s1, [""]), (self.s2, [""])]
        self.doc.recompute()
        self.edit(loft, count=2)
        field = self.sectionsField()
        self.assertEqual(texts(field), ["1. S3", "2. S1", "3. S2"])
        refs = entries(field)
        refs.item(1).setSelected(True)
        refs.item(2).setSelected(True)
        model = refs.model()
        # As QListWidget::dropEvent moves rows 1 and 2 to the top: row 1 to 0, then row 2 to 1
        self.assertTrue(model.moveRow(QtCore.QModelIndex(), 1, QtCore.QModelIndex(), 0))
        self.assertTrue(model.moveRow(QtCore.QModelIndex(), 2, QtCore.QModelIndex(), 1))
        self.assertTrue(
            waitFor(lambda: self.sectionNames(loft) == ["S1", "S2", "S3"]), loft.Sections
        )
        pump(0.2)
        self.assertEqual(self.sectionNames(loft), ["S1", "S2", "S3"])
        self.assertTrue(waitFor(lambda: texts(field) == ["1. S1", "2. S2", "3. S3"]), texts(field))
        self.assertThroughSection(loft, 10, 400)
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(
            waitFor(lambda: self.sectionNames(loft) == ["S3", "S1", "S2"]), loft.Sections
        )

    def newFeatureCancelled(self, command, name):
        """H2: the command on a shown sketch makes the feature and hides the sketch; Cancel
        removes the feature and the sketch is shown again, as before the command."""
        self.body = models.body(self.doc)
        profile = self.squareSketch("Profile", 5, 0)
        self.doc.recompute()
        self.assertTrue(profile.ViewObject.Visibility)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, profile.Name)
        Gui.runCommand(command)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no dialog")
        settle()
        self.assertIsNotNone(self.doc.getObject(name))
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump(0.2)
        flushDeletes()
        pump(0.2)
        self.assertIsNone(self.doc.getObject(name), "Cancel left the feature")
        self.assertTrue(profile.ViewObject.Visibility, "Cancel left the profile hidden")

    def testNewLoftCancelShowsTheProfile(self):
        self.newFeatureCancelled("PartDesign_AdditiveLoft", "AdditiveLoft")

    def testNewPipeCancelShowsTheProfile(self):
        self.newFeatureCancelled("PartDesign_AdditivePipe", "AdditivePipe")

    def testLoftCancelRestoresVisibilityItself(self):
        """Review 11: testLoftCancelRestoresVisibility with no transaction for Cancel to abort
        (setEdit alone), so only the dialog puts the visibility back: the profile and the
        sections hidden before the edit, the picked one included, are hidden after."""
        loft = self.tower(("S1",))
        for sketch in (self.towerProfile, self.s1, self.s2):
            sketch.ViewObject.Visibility = False
        self.edit(loft, count=2)
        self.assertTrue(self.s1.ViewObject.Visibility)
        self.assertTrue(self.towerProfile.ViewObject.Visibility)
        field = self.sectionsField()
        self.arm(field, byFocus=False)
        self.pick(self.s2, "")
        self.assertTrue(self.s2.ViewObject.Visibility, "a picked section isn't shown")
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump(0.2)
        flushDeletes()
        pump(0.2)
        self.assertFalse(self.towerProfile.ViewObject.Visibility, "Cancel left the profile shown")
        self.assertFalse(self.s1.ViewObject.Visibility, "Cancel left the section shown")
        self.assertFalse(self.s2.ViewObject.Visibility, "Cancel left the picked section shown")

    def testLoftRefusesAWholeSolid(self):
        """Review 9: a solid picked whole (in the tree) is no section: refused with the reason;
        one of its faces is taken."""
        loft = self.tower(("S1",))
        block = self.doc.addObject("Part::Box", "Block")
        block.Placement = App.Placement(App.Vector(-5, -5, 40), App.Rotation())
        self.doc.recompute()
        self.edit(loft, count=2)
        field = self.sectionsField()
        self.arm(field, byFocus=False)
        self.pick(block, "")
        self.assertEqual(self.sectionNames(loft), ["S1"])
        self.assertIn("whole solid", statusText().lower())
        self.assertTrue(armed(field), "a refused pick ended the pick (B21, ops#162)")
        self.pick(block, "Face6")  # its top, at z = 50
        self.assertEqual(self.sectionNames(loft), ["S1", "Block"])
        self.assertEqual([list(subs) for obj, subs in loft.Sections], [[""], ["Face6"]])

    # -- W8: the Pipe's profile, spine and auxiliary spine (T31-T33, T35; B9-B12) -----------------

    def spineField(self):
        field = findField("fieldSpine")
        self.assertIsNotNone(field, "no spine field")
        return field

    def spineSubs(self, pipe):
        return [s for s in pipe.Spine[1]] if pipe.Spine else None

    def testPipeSpinePicksToggle(self):
        """T31: the Rod's spine whole (120); edge 1 picked: the sweep follows it alone, 4 x 10 =
        40; edge 2 added: both edges, 120; edge 2 again: out, 40; edge 1 deleted: the sketch whole
        again, 120. The Spine's subs follow each pick."""
        pipe = self.rod("Constant")
        self.assertVolume(pipe, 120)
        self.edit(pipe, count=2)
        field = self.spineField()
        self.assertEqual(texts(field), ["Spine (whole)"])
        self.arm(field, byFocus=False)
        self.pick(self.spine, "Edge1")
        self.assertEqual(self.spineSubs(pipe), ["Edge1"])
        self.assertVolume(pipe, 40)
        self.pick(self.spine, "Edge2")
        self.assertEqual(self.spineSubs(pipe), ["Edge1", "Edge2"])
        self.assertVolume(pipe, 120)
        self.pick(self.spine, "Edge2")
        self.assertEqual(self.spineSubs(pipe), ["Edge1"])
        self.assertVolume(pipe, 40)
        self.assertTrue(armed(field), "a pick disarmed the spine")
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: self.spineSubs(pipe) == []), pipe.Spine)
        self.assertEqual(texts(field), ["Spine (whole)"])
        self.assertVolume(pipe, 120)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertLink(pipe.Spine, self.spine, [])
        self.assertVolume(pipe, 120)

    def testPipeSpineOtherObject(self):
        """T32, B9, B10: an edge of another sketch (a line along Z, 5 long) starts the spine on
        that sketch with that edge alone (4 x 5 = 20), not the old sketch's edge names; a tree
        pick of the Rod's spine sketch makes it the spine whole (120), with no empty sub. The
        profile sketch whole is refused as the spine, with the reason; so is a face."""
        pipe = self.rod("Constant")
        xz = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(1, 0, 0), 90))
        other = models.sketch(
            self.doc, "Other", models.polyline([(0, 0), (0, 5)]), self.body, placement=xz
        )
        pipe.Spine = (self.spine, ["Edge1", "Edge2"])
        self.doc.recompute()
        self.assertVolume(pipe, 120)
        self.edit(pipe, count=2)
        field = self.spineField()
        self.assertEqual(texts(field), ["Spine:Edge1", "Spine:Edge2"])
        self.arm(field, byFocus=False)
        self.pick(other, "Edge1")
        self.assertLink(pipe.Spine, other, ["Edge1"])
        self.assertEqual(self.spineSubs(pipe), ["Edge1"])
        self.assertEqual(texts(field), ["Other:Edge1"])
        self.assertVolume(pipe, 20)
        self.pick(self.spine, "")
        self.assertEqual(pipe.Spine[0].Name, "Spine")
        self.assertEqual(self.spineSubs(pipe), [])
        self.assertEqual(texts(field), ["Spine (whole)"])
        self.assertVolume(pipe, 120)
        self.pick(self.rodProfile, "")
        self.assertEqual(pipe.Spine[0].Name, "Spine")
        self.assertIn("profile", statusText().lower())
        block = self.doc.addObject("Part::Box", "Block")
        self.doc.recompute()
        self.pick(block, "Face1")
        self.assertEqual(pipe.Spine[0].Name, "Spine")
        self.assertIn("edge", statusText().lower())
        # The profile sketch's own edge is another use of it, as in stock: taken
        self.pick(self.rodProfile, "Edge1")
        self.assertLink(pipe.Spine, self.rodProfile, ["Edge1"])

    def testPipeSpineDeleteRemovesAllSelected(self):
        """B11, B12: no Object / Add edge / Remove edge buttons on the Pipe's panels; Delete on
        both selected edges of the spine leaves the sketch whole (120)."""
        pipe = self.rod("Constant")
        pipe.Spine = (self.spine, ["Edge1", "Edge2"])
        self.doc.recompute()
        self.edit(pipe, count=2)
        buttons = [b.text() for b in Gui.getMainWindow().findChildren(QtWidgets.QToolButton)]
        for text in ("Object", "Add edge", "Remove edge", "Add Edge", "Remove Edge"):
            self.assertNotIn(text, buttons)
        field = self.spineField()
        clickRow(field, 0)
        clickRow(field, 1, QtCore.Qt.ControlModifier)
        self.assertEqual(len(entries(field).selectedItems()), 2)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: self.spineSubs(pipe) == []), pipe.Spine)
        self.assertVolume(pipe, 120)

    def testPipeProfileField(self):
        """The profile is a field (a sketch, a sketch point or a face): another sketch picked
        replaces it (a 4 x 4 square along the spine: 480); the spine is refused as the profile,
        with the reason."""
        pipe = self.rod("Constant")
        self.edit(pipe, count=2)
        profile, spine = fields()
        self.assertEqual(profile.objectName(), "fieldProfile")
        self.assertEqual(spine.objectName(), "fieldSpine")
        self.assertEqual(texts(profile), ["Profile"])
        self.arm(profile, byFocus=False)
        self.pick(self.spine, "Edge1")
        self.assertEqual(pipe.Profile[0].Name, "Profile")
        self.assertIn("path", statusText().lower())
        big = self.squareSketch("Big", 2, 0)
        self.doc.recompute()
        self.pick(big, "Edge1")  # an edge of a sketch: the sketch whole
        self.assertLink(pipe.Profile, big, [])
        self.assertEqual(texts(profile), ["Big"])
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 480, places=3)

    def auxiliarySketch(self):
        """Two lines along Z at x = 5, 10 and 20 long, in the XZ plane: the auxiliary spine,
        parallel to the Rod's spine edge by edge, so the profile keeps its orientation."""
        xz = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(1, 0, 0), 90))
        return models.sketch(
            self.doc, "Aux", models.polyline([(5, 0), (5, 10), (5, 30)]), self.body, placement=xz
        )

    def testPipeAuxiliarySpineField(self):
        """T33: Mode Auxiliary shows the field titled "Auxiliary path"; an edge picked sets
        AuxiliarySpine (along the spine's first edge, the pipe is the 2 x 2 x 10 prism still,
        40, axis-aligned: the auxiliary path is parallel); the profile, spine and auxiliary spine
        fields share one armed field across the panels; Delete on the edge leaves the sketch
        whole, Delete on the whole entry clears it."""
        pipe = self.rod("Constant")
        aux = self.auxiliarySketch()
        pipe.Spine = (self.spine, ["Edge1"])
        # Curvilinear, the sweep is approximated: 0.12 % under 40, and its sides bulge to
        # y = +-1.758; without it the prism is exact
        pipe.AuxiliaryCurvilinear = False
        self.doc.recompute()
        self.edit(pipe, count=2)
        field = findField("fieldAuxiliarySpine")
        self.assertIsNotNone(field)
        self.assertFalse(field.isVisible(), "the auxiliary path shows outside Mode Auxiliary")
        box = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "comboBoxMode")
        self.choose(box, 3)
        self.assertTrue(waitFor(lambda: field.isVisible()), "no auxiliary path in Mode Auxiliary")
        self.assertEqual(field.findChild(QtWidgets.QLabel, "label").text(), "Auxiliary path")
        self.arm(field, byFocus=False)
        self.pick(aux, "Edge1")
        self.assertLink(pipe.AuxiliarySpine, aux, ["Edge1"])
        self.assertEqual(pipe.Mode, "Auxiliary")
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume / 40, 1, delta=1e-3)
        # The volume alone doesn't show the orientation: the prism stays axis-aligned, 2 x 2 x 10
        box = pipe.Shape.BoundBox
        for got, want in zip(
            (box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax), (-1, 1, -1, 1, 0, 10)
        ):
            self.assertAlmostEqual(got, want, delta=1e-3)
        spine = self.spineField()
        self.arm(spine, byFocus=False)
        self.assertFalse(armed(field), "two armed fields")
        self.arm(field, byFocus=False)
        self.assertFalse(armed(spine), "two armed fields")
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: list(pipe.AuxiliarySpine[1]) == []), pipe.AuxiliarySpine)
        self.assertEqual(texts(field), ["Aux (whole)"])
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: pipe.AuxiliarySpine is None), pipe.AuxiliarySpine)
        self.assertEqual(texts(field), [])

    def testNewPipeArmsItsSpine(self):
        """T35: PartDesign_AdditivePipe on a selected sketch makes a pipe with that profile and
        opens its dialog with the spine field armed."""
        self.body = models.body(self.doc)
        profile = self.squareSketch("Profile", 1, 0)
        self.doc.recompute()
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, profile.Name)
        Gui.runCommand("PartDesign_AdditivePipe")
        self.assertTrue(waitFor(lambda: len(fields()) == 2), "the pipe's fields")
        settle()
        field = self.spineField()
        self.assertTrue(waitFor(lambda: armed(field)), "the new pipe's spine isn't armed")
        pipe = self.doc.getObject("AdditivePipe")
        self.assertEqual(pipe.Profile[0].Name, "Profile")
        self.assertIsNone(pipe.Spine)

    # -- PR 166 review round 1 ----------------------------------------------------------------

    def wireAndPoint(self):
        """A Part wire along Z (two edges, 10 and 20 long) and a datum point at z = 40, both
        outside the body: whole, neither is anything a pipe can take as its profile or a
        section (Pipe::execute takes a whole object only when it is a sketch)."""
        import Part

        points = [App.Vector(0, 0, 0), App.Vector(0, 0, 10), App.Vector(0, 0, 30)]
        wire = models.feature(self.doc, "Wire", Part.makePolygon(points))
        dot = self.doc.addObject("PartDesign::Point", "Dot")
        dot.MapMode = "Deactivated"
        dot.Placement = App.Placement(App.Vector(0, 0, 40), App.Rotation())
        self.doc.recompute()
        return wire, dot

    def testPipeRefusesWholeObjectsButSketches(self):
        """Medium 1: a Part wire or a datum point picked whole is refused as the pipe's profile
        and as a section, with the reason; a sketch whole is still taken as a section."""
        pipe = self.rod()
        wire, dot = self.wireAndPoint()
        self.edit(pipe, count=3)
        profile = findField("fieldProfile")
        self.arm(profile, byFocus=False)
        for obj in (wire, dot):
            self.pick(obj, "")
            self.assertLink(pipe.Profile, self.rodProfile, [])
            self.assertIn("sketch", statusText().lower())
        sections = self.sectionsField()
        self.arm(sections, byFocus=False)
        for obj in (wire, dot):
            self.pick(obj, "")
            self.assertEqual(self.sectionNames(pipe), [])
            self.assertIn("sketch", statusText().lower())
        self.pick(self.s10, "")
        self.assertEqual(self.sectionNames(pipe), ["S10"])

    def block(self):
        """A box 2 x 2 x 10 outside the body, over the Rod's profile: its bottom face is the
        profile's square, its edge at x = y = -1 runs along Z from 0 to 10."""
        block = self.doc.addObject("Part::Box", "Block")
        block.Length = 2
        block.Width = 2
        block.Height = 10
        block.Placement = App.Placement(App.Vector(-1, -1, 0), App.Rotation())
        self.doc.recompute()
        [bottom] = face(normal=(0, 0, -1), through=(0, 0, 0)).one(block.Shape)
        [corner] = edge("line", direction=Z, through=(-1, -1, 0)).one(block.Shape)
        return block, bottom, corner

    def testPipeProfileFaceWithItsSolidsEdgeAsPath(self):
        """Medium 2 (as stock): a face of a solid as the profile and an edge of the same solid as
        the path; the pipe is the 2 x 2 x 10 prism, 40. The same face again as a section is
        refused (the same element on both sides)."""
        pipe = self.rod()
        block, bottom, corner = self.block()
        self.edit(pipe, count=3)
        profile = findField("fieldProfile")
        self.arm(profile, byFocus=False)
        self.pick(block, bottom)
        self.assertLink(pipe.Profile, block, [bottom])
        spine = self.spineField()
        self.arm(spine, byFocus=False)
        self.pick(block, corner)
        self.assertLink(pipe.Spine, block, [corner])
        sections = self.sectionsField()
        self.arm(sections, byFocus=False)
        self.pick(block, bottom)
        self.assertEqual(self.sectionNames(pipe), [])
        self.assertIn("profile", statusText().lower())
        pipe.Transformation = "Constant"
        self.assertVolume(pipe, 40)

    def testPipeProfileIgnoresAnUnusedAuxiliaryPath(self):
        """Medium 2: an auxiliary path left from Mode Auxiliary, in another mode, doesn't refuse
        its sketch as the profile; in Mode Auxiliary it does."""
        pipe = self.rod("Constant")
        aux = self.auxiliarySketch()
        pipe.AuxiliarySpine = aux
        self.doc.recompute()
        self.edit(pipe, count=2)
        profile = findField("fieldProfile")
        self.arm(profile, byFocus=False)
        self.pick(aux, "")
        self.assertLink(pipe.Profile, aux, [])
        self.pick(self.rodProfile, "")
        self.assertLink(pipe.Profile, self.rodProfile, [])
        box = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "comboBoxMode")
        self.choose(box, 3)
        self.arm(profile, byFocus=False)
        self.pick(aux, "")
        self.assertLink(pipe.Profile, self.rodProfile, [])
        self.assertIn("path", statusText().lower())

    def testPipeAuxiliaryPathDisarmsOffItsPage(self):
        """Low 1: the auxiliary path, armed, disarms when the mode leaves Auxiliary (its page
        hides)."""
        pipe = self.rod("Constant")
        self.edit(pipe, count=2)
        field = findField("fieldAuxiliarySpine")
        box = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "comboBoxMode")
        self.choose(box, 3)
        self.assertTrue(waitFor(lambda: field.isVisible()), "no auxiliary path in Mode Auxiliary")
        self.arm(field, byFocus=False)
        self.choose(box, 0)
        self.assertTrue(waitFor(lambda: not armed(field)), "armed off its page")

    def testPipeWirePathBackToWhole(self):
        """Low 3: a path of one edge of a Part wire, deleted, leaves the wire whole (the sweep
        along both edges, 120), as a sketch's does."""
        pipe = self.rod("Constant")
        wire, dot = self.wireAndPoint()
        pipe.Spine = (wire, ["Edge1"])
        self.assertVolume(pipe, 40)
        self.edit(pipe, count=2)
        field = self.spineField()
        self.assertEqual(texts(field), ["Wire:Edge1"])
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: self.spineSubs(pipe) == []), pipe.Spine)
        self.assertEqual(texts(field), ["Wire (whole)"])
        self.assertVolume(pipe, 120)

    def testPipeClearButtonIsAFieldStep(self):
        """Low 4: the auxiliary path's clear button is a step of the field's undo: Ctrl+Z in the
        field brings the path back."""
        pipe = self.rod("Constant")
        aux = self.auxiliarySketch()
        pipe.Mode = "Auxiliary"
        pipe.AuxiliarySpine = (aux, ["Edge1"])
        self.doc.recompute()
        self.edit(pipe, count=3)
        field = findField("fieldAuxiliarySpine")
        clear = Gui.getMainWindow().findChild(QtWidgets.QToolButton, "buttonProfileClear")
        self.assertTrue(clear.isVisible())
        clear.click()
        self.assertTrue(waitFor(lambda: pipe.AuxiliarySpine is None), pipe.AuxiliarySpine)
        self.assertEqual(texts(field), [])
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: pipe.AuxiliarySpine is not None), "Ctrl+Z")
        self.assertLink(pipe.AuxiliarySpine, aux, ["Edge1"])

    def testPipeOkKeepsUnusedSectionsShown(self):
        """Low 5: OK on a Constant pipe with sections left from Multisection leaves them as they
        were; it hides them only when the pipe uses them."""
        pipe = self.rod("Constant")
        pipe.Sections = [(self.s10, [""])]
        self.doc.recompute()
        self.s10.ViewObject.Visibility = True
        self.edit(pipe, count=2)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        pump(0.2)
        self.assertTrue(self.s10.ViewObject.Visibility, "OK hid an unused section")

    def testPipeCancelRestoresThePaths(self):
        """Low 7: Cancel after picks of the profile, the spine and the auxiliary path puts back
        Profile, Spine, AuxiliarySpine and Mode, and hides the auxiliary path shown for the
        pick."""
        pipe = self.rod("Constant")
        aux = self.auxiliarySketch()
        big = self.squareSketch("Big", 2, 0)
        self.doc.recompute()
        aux.ViewObject.Visibility = False
        self.doc.openTransaction("Edit Pipe")  # as the edit command does
        self.edit(pipe, count=2)
        profile = findField("fieldProfile")
        self.arm(profile, byFocus=False)
        self.pick(big, "")
        self.assertLink(pipe.Profile, big, [])
        spine = self.spineField()
        self.arm(spine, byFocus=False)
        self.pick(self.spine, "Edge1")
        self.assertEqual(self.spineSubs(pipe), ["Edge1"])
        box = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "comboBoxMode")
        self.choose(box, 3)
        field = findField("fieldAuxiliarySpine")
        self.arm(field, byFocus=False)
        self.pick(aux, "Edge1")
        self.assertLink(pipe.AuxiliarySpine, aux, ["Edge1"])
        self.assertTrue(aux.ViewObject.Visibility, "the picked auxiliary path isn't shown")
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump(0.2)
        self.assertLink(pipe.Profile, self.rodProfile, [])
        self.assertLink(pipe.Spine, self.spine, [])
        self.assertIsNone(pipe.AuxiliarySpine)
        self.assertEqual(pipe.Mode, "Standard")
        self.assertFalse(aux.ViewObject.Visibility, "Cancel left the auxiliary path shown")

    # -- T34, T37: the Hole (W9) ------------------------------------------------------------------

    def plate(self, positions=None, boss=False, arc=False, binder=False):
        """The Plate: a 20 x 20 x 10 additive box; a sketch on its top with three circles r = 1,
        at (5, 5), (15, 5) and (10, 15), and a point at (10, 10); a hole of diameter 2 through
        all, on circles and arcs (6), from the sketch whole or the given positions. Each hole
        removes 10 pi. With boss, a cylinder r = 2, 2 high, centred at (10, 10) on the plate,
        before the hole. With arc, the sketch has a half circle r = 1 centred at (5, 15) too.
        With binder, a shape binder of the sketch whole, before the hole."""
        import Part

        self.body = models.body(self.doc)
        self.plateBox = self.body.newObject("PartDesign::AdditiveBox", "Box")
        self.plateBox.Length = 20
        self.plateBox.Width = 20
        self.plateBox.Height = 10
        geometry = [
            models.circle(5, 5, 1),
            models.circle(15, 5, 1),
            models.circle(10, 15, 1),
            Part.Point(App.Vector(10, 10, 0)),
        ]
        if arc:
            geometry.append(Part.ArcOfCircle(models.circle(5, 15, 1), 0, math.pi))
        self.holes = models.sketch(self.doc, "Holes", geometry, self.body, z=10)
        if boss:
            self.boss = self.body.newObject("PartDesign::AdditiveCylinder", "Boss")
            self.boss.Radius = 2
            self.boss.Height = 2
            self.boss.Placement = App.Placement(App.Vector(10, 10, 10), App.Rotation())
        if binder:
            self.binder = self.body.newObject("PartDesign::ShapeBinder", "Binder")
            self.binder.Support = [(self.holes, "")]
        self.doc.recompute()
        hole = self.body.newObject("PartDesign::Hole", "Hole")
        hole.Profile = (self.holes, positions or [])
        hole.Diameter = 2
        hole.DepthType = "ThroughAll"
        hole.BaseProfileType = 6
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        return hole

    def circleOf(self, x, y):
        [name] = edge("circle", center=(x, y, 10), radius=1).one(self.holes.Shape)
        return name

    def pointOf(self, x, y):
        """The sketch's vertex at (x, y) on its plane that no edge has: the point."""
        for i, vertex in enumerate(self.holes.Shape.Vertexes):
            if vertex.Point.distanceToPoint(App.Vector(x, y, 10)) < 1e-6:
                return "Vertex%d" % (i + 1)
        self.fail("no vertex at (%g, %g)" % (x, y))

    def removed(self, hole):
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        return self.plateBox.Shape.Volume - hole.Shape.Volume

    def assertHoles(self, hole, count):
        self.assertAlmostEqual(self.removed(hole), count * 10 * math.pi, places=3)

    def refusedPick(self, obj, sub):
        """The status bar's text right after a pick: the Hole's gizmos write their hint over a
        refusal's reason soon after."""
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        text = statusText().lower()
        pump(0.2)
        return text

    def bossRemoved(self, hole):
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        return self.boss.Shape.Volume - hole.Shape.Volume

    def positionsSubs(self, hole):
        return [s for s in hole.Profile[1] if s]

    def testHoleStartReferenceField(self):
        """T34: Start "Reference" with no reference arms the start field; a datum plane at z = 6
        picked: StartReference is the plane, and the holes start there, their top at z = 6 (the
        removed part's bounding box), 3 x 6 pi removed."""
        hole = self.plate()
        low = self.datumPlane(self.body, "Low", 6)
        self.doc.recompute()
        self.assertHoles(hole, 3)
        self.edit(hole, count=1)
        start = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "StartType")
        start.setCurrentIndex(2)
        pump(0.2)
        field = findField("fieldStartReference")
        self.assertIsNotNone(field, "no start reference field")
        self.assertTrue(
            waitFor(lambda: field.isVisible() and armed(field)), "the start field isn't armed"
        )
        self.assertIsNone(Gui.getMainWindow().findChild(QtWidgets.QLineEdit, "lineStartReference"))
        self.pick(low, "")
        self.assertLink(hole.StartReference, low, [])
        self.assertAlmostEqual(self.removed(hole), 3 * 6 * math.pi, places=3)
        cut = self.plateBox.Shape.cut(hole.Shape)
        self.assertAlmostEqual(cut.BoundBox.ZMax, 6, places=4)
        self.assertAlmostEqual(cut.BoundBox.ZMin, 0, places=4)
        start.setCurrentIndex(0)
        pump(0.2)
        self.assertTrue(waitFor(lambda: not field.isVisible()), "the start field stays shown")
        self.assertFalse(armed(field))
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertEqual(hole.StartType, "Profile plane")
        self.assertHoles(hole, 3)

    def testHolePositionsPicksToggle(self):
        """T37: the positions field lists the sketch whole (30 pi); circles 1 and 2 picked: two
        holes, 20 pi; both deleted: the sketch whole again, 30 pi."""
        hole = self.plate()
        self.assertHoles(hole, 3)
        self.edit(hole, count=1)
        field = findField("fieldProfile")
        self.assertIsNotNone(field, "no positions field")
        self.assertEqual(field.findChild(QtWidgets.QLabel, "label").text(), "Positions")
        self.assertEqual(texts(field), ["Holes (whole)"])
        self.arm(field, byFocus=False)
        first, second = self.circleOf(5, 5), self.circleOf(15, 5)
        self.pick(self.holes, first)
        self.assertEqual(self.positionsSubs(hole), [first])
        self.assertHoles(hole, 1)
        self.pick(self.holes, second)
        self.assertEqual(self.positionsSubs(hole), [first, second])
        self.assertHoles(hole, 2)
        clickRow(field, 0)
        clickRow(field, 1, QtCore.Qt.ControlModifier)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: self.positionsSubs(hole) == []), hole.Profile)
        self.assertEqual(texts(field), ["Holes (whole)"])
        self.assertHoles(hole, 3)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertLink(hole.Profile, self.holes, [])
        self.assertHoles(hole, 3)

    def testHolePositionsPointWidensTheType(self):
        """T37: under "Circles and arcs", the three circles picked (30 pi), then the sketch's
        point: BaseProfileType widens to points, circles and arcs (7) in the same pick, the combo
        follows, and the point makes a fourth hole, 40 pi. A face of the plate and a straight
        edge are refused, with the reason."""
        hole = self.plate()
        self.edit(hole, count=1)
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "BaseProfileType")
        self.assertEqual(combo.currentIndex(), 0)
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        circles = [self.circleOf(5, 5), self.circleOf(15, 5), self.circleOf(10, 15)]
        for name in circles:
            self.pick(self.holes, name)
        self.assertHoles(hole, 3)
        point = self.pointOf(10, 10)
        self.pick(self.holes, point)
        self.assertEqual(self.positionsSubs(hole), circles + [point])
        self.assertEqual(hole.BaseProfileType, 7)
        self.assertTrue(waitFor(lambda: combo.currentIndex() == 1), "the combo didn't follow")
        self.assertHoles(hole, 4)
        [top] = face(normal=(0, 0, 1), through=(0, 0, 10)).one(self.plateBox.Shape)
        self.assertIn("circle", self.refusedPick(self.plateBox, top))
        self.assertEqual(self.positionsSubs(hole), circles + [point])
        [straight] = edge("line", direction=X, through=(0, 0, 10)).one(self.plateBox.Shape)
        self.assertIn("circle", self.refusedPick(self.plateBox, straight))
        self.assertEqual(self.positionsSubs(hole), circles + [point])

    def testHolePositionsOnASolidsCircularEdge(self):
        """Q10: a circular edge of a solid: a boss r = 2, 2 high, centred at (10, 10) on the
        plate; its top circle picked as the positions starts the list on the boss, and the hole
        drills from z = 12 through all: a column r = 1, 12 high, 12 pi removed from the plate
        and boss (whose volume is 4000 + 8 pi)."""
        hole = self.plate(boss=True)
        boss = self.boss
        self.assertEqual(hole.BaseFeature, boss)
        self.assertAlmostEqual(boss.Shape.Volume, 4000 + 8 * math.pi, places=3)
        self.edit(hole, count=1)
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        [rim] = edge("circle", center=(10, 10, 12), radius=2).one(boss.Shape)
        self.pick(boss, rim)
        self.assertLink(hole.Profile, boss, [rim])
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        self.assertAlmostEqual(boss.Shape.Volume - hole.Shape.Volume, 12 * math.pi, places=3)

    def testHolePositionsArmingShowsTheSketch(self):
        """PR 169 H1: the hole's sketch hidden, as after the hole's creation: arming the positions
        shows it (its circles and points can be picked in the 3D view) and hides the hole;
        disarming hides it again, and so does Cancel while armed."""
        hole = self.plate()
        self.holes.ViewObject.Visibility = False
        self.doc.openTransaction("Edit Hole")
        self.edit(hole, count=1)
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        self.assertTrue(waitFor(lambda: self.holes.ViewObject.Visibility), "the sketch is hidden")
        self.assertFalse(hole.ViewObject.Visibility, "arming left the hole shown")
        field.setProperty("armed", False)
        self.assertTrue(waitFor(lambda: not armed(field)))
        self.assertTrue(
            waitFor(lambda: not self.holes.ViewObject.Visibility), "disarming left the sketch shown"
        )
        self.arm(field, byFocus=False)
        self.assertTrue(waitFor(lambda: self.holes.ViewObject.Visibility))
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump(0.2)
        self.assertFalse(self.holes.ViewObject.Visibility, "Cancel left the sketch shown")
        self.assertTrue(hole.ViewObject.Visibility, "Cancel left the hole hidden")

    def testHolePositionsRepickWidensTheType(self):
        """PR 169 M1, L5: under "Circles and arcs", circles 1 and 2 listed (20 pi); the first
        entry's Re-pick onto the sketch's point: the type widens to 7 in the same step, the combo
        follows, and the point and circle 2 make two holes, 20 pi."""
        hole = self.plate()
        first, second = self.circleOf(5, 5), self.circleOf(15, 5)
        hole.Profile = (self.holes, [first, second])
        self.assertHoles(hole, 2)
        self.edit(hole, count=1)
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "BaseProfileType")
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        menu = openMenu(field, 0)
        menuActions(menu)["Re-pick"].trigger()
        menu.close()
        pump()
        point = self.pointOf(10, 10)
        self.pick(self.holes, point)
        self.assertTrue(waitFor(lambda: self.positionsSubs(hole) == [point, second]), hole.Profile)
        self.assertEqual(hole.BaseProfileType, 7)
        self.assertTrue(waitFor(lambda: combo.currentIndex() == 1), "the combo didn't follow")
        self.assertHoles(hole, 2)

    def testHolePositionsUndoNarrowsTheType(self):
        """PR 169 M2, L5: the sketch whole under "Circles and arcs" (30 pi); the point picked
        widens the type to 7 (10 pi); the field's Ctrl+Z gives the sketch whole and type 6 back
        (30 pi, not 40). The point and circle 1 picked (7, 20 pi), Delete on the point: circle 1
        under 6 again. The point picked again, then Cancel: the sketch whole under 6, 30 pi."""
        hole = self.plate()
        self.doc.openTransaction("Edit Hole")
        self.edit(hole, count=1)
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "BaseProfileType")
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        point, first = self.pointOf(10, 10), self.circleOf(5, 5)
        self.pick(self.holes, point)
        self.assertEqual(self.positionsSubs(hole), [point])
        self.assertEqual(hole.BaseProfileType, 7)
        self.assertHoles(hole, 1)
        self.assertTrue(focus(entries(field)))
        key(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertTrue(waitFor(lambda: self.positionsSubs(hole) == []), hole.Profile)
        self.assertEqual(hole.BaseProfileType, 6)
        self.assertTrue(waitFor(lambda: combo.currentIndex() == 0), "the combo didn't follow")
        self.assertHoles(hole, 3)

        self.arm(field, byFocus=False)
        self.pick(self.holes, point)
        self.pick(self.holes, first)
        self.assertEqual(self.positionsSubs(hole), [point, first])
        self.assertEqual(hole.BaseProfileType, 7)
        self.assertHoles(hole, 2)
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: self.positionsSubs(hole) == [first]), hole.Profile)
        self.assertEqual(hole.BaseProfileType, 6)
        self.assertHoles(hole, 1)

        self.arm(field, byFocus=False)
        self.pick(self.holes, point)
        self.assertEqual(hole.BaseProfileType, 7)
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        self.assertLink(hole.Profile, self.holes, [])
        self.assertEqual(hole.BaseProfileType, 6)
        self.assertHoles(hole, 3)

    def testHolePositionsArcWidensACirclesOnlyType(self):
        """PR 169 L3: a type set from Python, circles only (2): an arc picked widens it by the
        arcs' bit alone, to circles and arcs (6), and the combo shows it; the arc makes a hole at
        its centre, 10 pi."""
        hole = self.plate(arc=True)
        hole.BaseProfileType = 2
        self.doc.recompute()
        self.edit(hole, count=1)
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "BaseProfileType")
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        halfCircle = self.circleOf(5, 15)
        self.pick(self.holes, halfCircle)
        self.assertEqual(self.positionsSubs(hole), [halfCircle])
        self.assertEqual(hole.BaseProfileType, 6)
        self.assertTrue(waitFor(lambda: combo.currentIndex() == 0), "the combo didn't follow")
        self.assertHoles(hole, 1)

    def testHolePositionsOnFaces(self):
        """PR 169 M3, as stock: the boss's top face (flat, a circle among its edges) makes a hole
        at the circle's centre from z = 12 (12 pi); its own rim beside it is taken, and the
        circle drilled once (PR 172 review L2). The boss's cylindrical face: holes at its two
        circles along its axis, 12 pi down or 2 pi up (Reversed), and its rim beside it changes
        nothing; the rim, then the top face beside it, the same. A flat face with no circle is
        refused, with the reason."""
        hole = self.plate(boss=True)
        boss = self.boss
        self.edit(hole, count=1)
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        [top] = face(normal=(0, 0, 1), through=(10, 10, 12)).one(boss.Shape)
        [side] = face(surface="cylinder").one(boss.Shape)
        [rim] = edge("circle", center=(10, 10, 12), radius=2).one(boss.Shape)
        self.pick(boss, top)
        self.assertLink(hole.Profile, boss, [top])
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        self.assertAlmostEqual(boss.Shape.Volume - hole.Shape.Volume, 12 * math.pi, places=3)
        self.pick(boss, rim)
        self.assertLink(hole.Profile, boss, [top, rim])
        self.assertAlmostEqual(self.bossRemoved(hole), 12 * math.pi, places=3)

        self.pick(self.holes, "")
        self.assertLink(hole.Profile, self.holes, [])
        self.pick(boss, side)
        self.assertLink(hole.Profile, boss, [side])
        # The direction is the cylinder's axis, either sense (Hole::guessNormalDirection): one
        # way the holes go down through the plate (12 pi), the other up out of the boss (2 pi)
        removed = []
        for reversed in (False, True):
            hole.Reversed = reversed
            self.doc.recompute()
            self.assertTrue(hole.isValid(), hole.getStatusString())
            removed.append(boss.Shape.Volume - hole.Shape.Volume)
        for got, want in zip(sorted(removed), (2 * math.pi, 12 * math.pi)):
            self.assertAlmostEqual(got, want, places=3)
        hole.Reversed = False
        alone = self.bossRemoved(hole)
        self.pick(boss, rim)
        self.assertLink(hole.Profile, boss, [side, rim])
        self.assertAlmostEqual(self.bossRemoved(hole), alone, places=3)

        self.pick(self.holes, "")
        self.pick(boss, rim)
        self.assertLink(hole.Profile, boss, [rim])
        alone = self.bossRemoved(hole)
        self.pick(boss, top)
        self.assertLink(hole.Profile, boss, [rim, top])
        self.assertAlmostEqual(self.bossRemoved(hole), alone, places=3)
        [plain] = face(normal=(-1, 0, 0), through=(0, 0, 0)).one(boss.Shape)
        self.assertIn("circle", self.refusedPick(boss, plain))
        self.assertLink(hole.Profile, boss, [rim, top])

    def testHolePositionsWholeBinderAndSolid(self):
        """PR 169 M3: a shape binder of the sketch, whole, gives the sketch's three holes (30 pi);
        a solid whole is refused, with a reason naming the solid."""
        hole = self.plate(binder=True)
        self.edit(hole, count=1)
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        self.pick(self.binder, "")
        self.assertLink(hole.Profile, self.binder, [])
        self.assertHoles(hole, 3)
        self.assertIn("solid", self.refusedPick(self.plateBox, ""))
        self.assertLink(hole.Profile, self.binder, [])

    def testHolePositionsVertices(self):
        """PR 169 L1, L2: a vertex of the sketch on one of its curves (circle 1's seam) is refused,
        as the sketch whole leaves it out; a solid's vertex is taken, as stock takes it from a
        preselection: the plate's corner (20, 20, 10), the type widened to 7, a quarter column
        drilled down from it, 10 pi / 4."""
        hole = self.plate()
        self.edit(hole, count=1)
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        seam = None
        for i, point in enumerate(self.holes.Shape.Vertexes):
            if abs(point.Point.distanceToPoint(App.Vector(5, 5, 10)) - 1) < 1e-6:
                seam = "Vertex%d" % (i + 1)
        self.assertIsNotNone(seam)
        self.assertIn("curve", self.refusedPick(self.holes, seam))
        self.assertLink(hole.Profile, self.holes, [])
        [corner] = vertex(at=(20, 20, 10)).one(self.plateBox.Shape)
        self.pick(self.plateBox, corner)
        self.assertLink(hole.Profile, self.plateBox, [corner])
        self.assertEqual(hole.BaseProfileType, 7)
        self.assertAlmostEqual(self.removed(hole), 10 * math.pi / 4, places=3)

    def testHolePositionsRepickAFaceOntoItsRim(self):
        """PR 169 verification, Low 1: the boss's top face listed (12 pi); its entry's Re-pick
        onto the face's own rim replaces it: the rim alone, the same hole, 12 pi."""
        hole = self.plate(boss=True)
        boss = self.boss
        [top] = face(normal=(0, 0, 1), through=(10, 10, 12)).one(boss.Shape)
        [rim] = edge("circle", center=(10, 10, 12), radius=2).one(boss.Shape)
        hole.Profile = (boss, [top])
        self.doc.recompute()
        self.assertAlmostEqual(boss.Shape.Volume - hole.Shape.Volume, 12 * math.pi, places=3)
        self.edit(hole, count=1)
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        menu = openMenu(field, 0)
        menuActions(menu)["Re-pick"].trigger()
        menu.close()
        pump()
        self.pick(boss, rim)
        self.assertTrue(waitFor(lambda: self.positionsSubs(hole) == [rim]), hole.Profile)
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        self.assertAlmostEqual(boss.Shape.Volume - hole.Shape.Volume, 12 * math.pi, places=3)

    def testHolePositionsFacesSharingACircle(self):
        """PR 169 verification, Low 2, and PR 172 review L2: the boss's cylindrical face listed,
        then its top face, which shares the circle at z = 12: both taken, and the circle drilled
        once, as with the first alone (Hole::findHoles takes each edge once; the direction is
        the first entry's: 2 pi up the cylinder's axis). The other way round: 12 pi, the top
        face's alone."""
        hole = self.plate(boss=True)
        boss = self.boss
        [top] = face(normal=(0, 0, 1), through=(10, 10, 12)).one(boss.Shape)
        [side] = face(surface="cylinder").one(boss.Shape)
        self.edit(hole, count=1)
        field = findField("fieldProfile")
        self.arm(field, byFocus=False)
        for first, second, removed in ((side, top, 2 * math.pi), (top, side, 12 * math.pi)):
            self.pick(self.holes, "")
            self.pick(boss, first)
            self.assertLink(hole.Profile, boss, [first])
            self.assertAlmostEqual(self.bossRemoved(hole), removed, places=3)
            self.pick(boss, second)
            self.assertLink(hole.Profile, boss, [first, second])
            self.assertAlmostEqual(self.bossRemoved(hole), removed, places=3)

    # -- ops#150 W2 follow-ups (PR 142's review gaps) ---------------------------------------------

    def testDraftNeutralPlaneOfOriginAndDatumPlanes(self):
        """The neutral plane picked as planes that aren't faces, each written whole: the body's
        XY origin plane (z = 0, the bottom's plane: the bottom's draft again), then a datum plane
        at z = 10 (the top's plane: the other way, 2000 minus the bottom's volume)."""
        box, draft = self.draft()
        bottomVolume = draft.Shape.Volume
        datum = self.datumPlane(self.body, "TopPlane", 10)
        self.doc.recompute()
        [faces, plane, line] = self.edit(draft, count=3)
        self.arm(plane, byFocus=False)
        for obj, expected in (
            (models.originFeature(self.body, "XY_Plane"), bottomVolume),
            (datum, 2000 - bottomVolume),
        ):
            self.pick(obj, "")
            self.assertLink(draft.NeutralPlane, obj, [])
            self.assertVolume(draft, expected)
        self.assertEqual(draft.Base[1], [self.side])

    def testDraftNeutralPlaneOfACoordinateSystem(self):
        """The neutral plane picked as a coordinate system's XY plane, the coordinate system at
        z = 5: written whole, and the draft computes. Where it pivots is TestDraft's
        TestNeutralPlanePlacement (ops#198)."""
        box, draft = self.draft()
        lcs = self.doc.addObject("Part::LocalCoordinateSystem", "LCS")
        self.body.addObject(lcs)
        lcs.Placement = App.Placement(App.Vector(0, 0, 5), App.Rotation())
        self.doc.recompute()
        [lcsPlane] = [f for f in lcs.OriginFeatures if f.Role == "XY_Plane"]
        [faces, plane, line] = self.edit(draft, count=3)
        self.arm(plane, byFocus=False)
        self.pick(lcsPlane, "")
        self.assertLink(draft.NeutralPlane, lcsPlane, [])
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())

    def testPadFaceFieldVisibilityAfterCancel(self):
        """While the up-to-face field is armed the box (the solid before) shows and the pad
        hides; Cancel while armed: both as before the edit."""
        box, pad = self.padOnBox()
        box.ViewObject.Visibility = False
        pad.ViewObject.Visibility = True
        self.doc.openTransaction("Edit Pad")
        [profile, field] = self.edit(pad, count=2)
        self.arm(field, byFocus=False)
        self.assertTrue(waitFor(lambda: box.ViewObject.Visibility), "the box isn't shown")
        self.assertFalse(pad.ViewObject.Visibility, "the pad stays shown")
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump(0.3)
        self.assertFalse(box.ViewObject.Visibility, "Cancel left the box shown")
        self.assertTrue(pad.ViewObject.Visibility, "Cancel left the pad hidden")
        self.assertLink(pad.UpToFace, self.low, [])

    def testDocumentClosedWhileAFieldIsArmed(self):
        """The document closed while the up-to-face field is armed: the dialog goes with it and
        nothing stays armed; another document's objects keep their visibility, and an edit
        there arms its own field."""
        other = models.newDocument("ReferenceFieldOther")
        otherBody = models.body(other)
        otherSketch = models.sketch(other, "OtherSquare", models.rectangle(0, 0, 2, 2), otherBody)
        otherPad = models.pad(otherBody, otherSketch, 3)
        other.recompute()
        # The other way round from what a restore of this document's pad and sketch would set:
        # one misdirected by name into the other document flips them (PR 172 review L3)
        otherSketch.ViewObject.Visibility = True
        otherPad.ViewObject.Visibility = False
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        box, pad = self.padOnBox()
        box.ViewObject.Visibility = False
        [profile, field] = self.edit(pad, count=2)
        self.arm(field, byFocus=False)
        self.assertTrue(waitFor(lambda: box.ViewObject.Visibility))
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = other
        pump(0.3)
        self.assertNotIn(name, App.listDocuments())
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        self.assertTrue(waitFor(lambda: not fields(), 3.0), "a field outlived its document")
        self.assertTrue(otherSketch.ViewObject.Visibility)
        self.assertFalse(otherPad.ViewObject.Visibility)

        otherSketch.ViewObject.Visibility = False
        otherPad.ViewObject.Visibility = True
        App.setActiveDocument(other.Name)
        Gui.setActiveDocument(other.Name)
        [otherField] = self.edit(otherPad, count=1)
        self.arm(otherField, byFocus=False)
        self.assertTrue(waitFor(lambda: otherSketch.ViewObject.Visibility), "the sketch is hidden")
        otherField.setProperty("armed", False)
        self.assertTrue(waitFor(lambda: not otherSketch.ViewObject.Visibility))

    # -- ops#150 W3 follow-ups (PR 144's review gaps) ---------------------------------------------

    def testRepickOnAnOlderPadSetsAllowMultiFace(self):
        """B7 through the picked handler: a pad without AllowMultiFace whose profile lists region
        B (ignored then: the whole sketch is padded); the entry's Re-pick onto the disk sets
        AllowMultiFace in the same step, and the pad is the disk's, 20 pi."""
        pad, sketch, regions = self.regionsPad(allowMultiFace=False)
        pad.Profile = (sketch, [regions["B"]])
        self.doc.recompute()
        self.assertFalse(pad.AllowMultiFace)
        self.assertVolume(pad, WHOLE_SKETCH)
        [field] = self.edit(pad)
        self.arm(field, byFocus=False)
        menu = openMenu(field, 0)
        menuActions(menu)["Re-pick"].trigger()
        menu.close()
        pump()
        self.pickRegion(sketch, regions["disk"])
        self.assertTrue(waitFor(lambda: pad.Profile[1] == [regions["disk"]]), pad.Profile)
        self.assertTrue(pad.AllowMultiFace)
        self.assertVolume(pad, 20 * math.pi)

    def testShadingRestoredOnOk(self):
        self.shadingRestoredWhenTheEditEnds(
            lambda: taskButton(QtWidgets.QDialogButtonBox.Ok).click(), editEnds=True
        )

    def testShadingRestoredOnCancel(self):
        self.shadingRestoredWhenTheEditEnds(
            lambda: taskButton(QtWidgets.QDialogButtonBox.Cancel).click(),
            editEnds=True,
            transaction="Edit Pad",
        )

    def testShadingRestoredOnEscIn3DView(self):
        """Esc in the 3D view disarms the profile field and the dialog stays: the sketch hides
        again, its regions drawn as saved, and the pad shows as in the dialog."""
        pad, sketch, regions = self.regionsPad()
        sketch.ViewObject.Visibility = False
        saved = sketch.ViewObject.ShapeAppearance[0].Transparency
        [field] = self.edit(pad)
        padShown = pad.ViewObject.Visibility
        self.arm(field, byFocus=False)
        self.assertTrue(sketch.ViewObject.Visibility)
        self.assertFalse(pad.ViewObject.Visibility)
        self.assertTrue(focus(views3D()[0]), "the 3D view doesn't take the focus")
        key(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not armed(field)), "Esc in the 3D view didn't disarm")
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "Esc in the 3D view closed the dialog")
        self.assertFalse(sketch.ViewObject.Visibility)
        self.assertAlmostEqual(self.regionTransparency(sketch), saved, places=5)
        self.assertEqual(pad.ViewObject.Visibility, padShown)

    def testRegionWhoseFaceVanished(self):
        """Regions B and the disk listed; the disk's circle deleted from the sketch, so its
        region is gone: the entry shows broken and B stays. Region A, now the whole rectangle
        (200), picked beside it: added, the broken entry kept. Delete on the broken entry: B and
        A remain, (100 + 200) x 5 = 1500 mm^3."""
        pad, sketch, regions = self.regionsPad()
        pad.Profile = (sketch, [regions["B"], regions["disk"]])
        self.doc.recompute()
        self.assertVolume(pad, 500 + 20 * math.pi)
        circles = [i for i, g in enumerate(sketch.Geometry) if g.TypeId == "Part::GeomCircle"]
        self.assertEqual(len(circles), 1)
        sketch.delGeometry(circles[0])
        self.doc.recompute()
        [field] = self.edit(pad)
        self.assertTrue(waitFor(lambda: len(states(field)) == 2), states(field))
        self.assertEqual(states(field)[1], "broken", states(field))
        self.assertNotEqual(states(field)[0], "broken", states(field))
        [whole] = [
            "InternalFace%d" % (i + 1)
            for i, f in enumerate(sketch.InternalShape.Faces)
            if abs(f.Area - 200) < 1e-6
        ]
        self.arm(field, byFocus=False)
        self.pickRegion(sketch, whole)
        self.assertTrue(waitFor(lambda: len(states(field)) == 3), states(field))
        self.assertEqual(states(field)[1], "broken", states(field))
        self.assertTrue(focus(entries(field)))
        clickRow(field, 1)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: len(states(field)) == 2), states(field))
        self.assertNotIn("broken", states(field))
        self.assertEqual(pad.Profile[1][1], whole)
        self.assertVolume(pad, 1500)
