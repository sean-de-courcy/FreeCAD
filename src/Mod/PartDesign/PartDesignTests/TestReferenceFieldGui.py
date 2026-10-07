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
        [field] = self.edit(second)
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
        [field] = self.edit(second)
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
        self.edit(pad, count=0)
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
        [field] = self.edit(pad)
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
        [field] = self.edit(pad)
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
        [field] = self.edit(pad)
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
        [shape, faces] = self.edit(pad, count=2)
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
        [shape, faces] = self.edit(pad, count=2)
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
        [shape] = self.edit(pad, count=1)
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
        self.edit(pad, count=0)
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
        self.edit(pad, count=0)
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
        [field] = self.edit(second)
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
        [field] = self.edit(pad)
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
        [field] = self.edit(pad)
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
        self.edit(pad, count=0)
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
