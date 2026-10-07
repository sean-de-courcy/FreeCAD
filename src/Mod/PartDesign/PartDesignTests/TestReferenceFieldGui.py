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

    def pick(self, obj, sub):
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        pump(0.2)

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
        """T10: the Draft's faces field and its neutral-plane pick: one at a time. The plane pick
        disarms the field and goes to NeutralPlane only; a click into the field ends the plane
        pick, and the next pick goes to Base only."""
        box = self.box()
        [side] = face(normal=(0, -1, 0)).one(box.Shape)
        [bottom] = face(normal=(0, 0, -1)).one(box.Shape)
        [back] = face(normal=(0, 1, 0)).one(box.Shape)
        draft = self.body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (box, [side])
        draft.NeutralPlane = (box, [bottom])
        draft.Angle = 2
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        [field] = self.edit(draft)
        self.arm(field, byFocus=True)

        plane = Gui.getMainWindow().findChild(QtWidgets.QAbstractButton, "buttonPlane")
        plane.click()
        pump()
        self.assertTrue(plane.isChecked())
        self.assertFalse(armed(field), "the plane pick left the field armed")
        self.pick(box, bottom)
        self.assertEqual(draft.Base[1], [side])
        self.assertEqual(draft.NeutralPlane[1], [bottom])

        clickRow(field, 0)
        self.assertTrue(waitFor(lambda: armed(field)), "a click into the field didn't arm it")
        self.assertFalse(plane.isChecked(), "the plane pick stays on")
        self.pick(box, back)
        self.assertEqual(draft.Base[1], [side, back])
        self.assertEqual(draft.NeutralPlane[1], [bottom])

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

    def testPanelPickDisarmsTheField(self):
        """T12, 3.5: the References panel lists only the neutral plane (the faces field shows
        Base); its Re-pick, with the field armed, disarms the field."""
        pad, draft = self.redrawnDraft()
        rows = {(e["property"], e["index"]) for e in App.getReferenceReport(draft)}
        self.assertIn(("Base", 0), rows)
        self.assertIn(("NeutralPlane", 0), rows)
        [field] = self.edit(draft)
        self.assertEqual(states(field), ["guessed"])
        tree = Gui.getMainWindow().findChild(QtWidgets.QTreeWidget, "references")
        self.assertIsNotNone(tree, "no References panel")
        self.assertTrue(tree.isVisible())
        listed = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
        self.assertEqual(listed, ["NeutralPlane[0]"])

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
