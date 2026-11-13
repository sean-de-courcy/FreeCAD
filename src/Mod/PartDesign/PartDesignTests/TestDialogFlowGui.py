# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, the Onshape experiment: hands-on A-1, F2, B-1, B-4, ranks 24, 36, 38, 52)

"""How a feature dialog opens, closes and reads, as Onshape's:

- A-1: a new Extrude opens as Add with the one part its tool touches (a sketch on that part's
  face, or on a plane overlapping only that part: the feature goes into that part), else as New, a
  part of its own (touching nothing, or two parts). With no profile preselected, the first profile
  picked decides it.
- Rank 38 (B-1, the hands-on notes): Enter on a check box or in the graphics area accepts the
  dialog; Enter in a value field only commits the value.
- Rank 36 (B-4): the first box's title is the feature's name, red while the feature is in error.
- Rank 24 (F2), with regeneration round 1 merged (Document.isStepLocked): another tool started
  with a dialog open commits it when it has any input, even in error, and drops an empty one.
- Rank 52: a new part studio's planes stay shown after the primitive and feature-pick dialogs.
- Round 6 (the journeys' small items): under the Onshape keymap a new part is "Part N", the lowest
  N free (J22); the operation row reads New / Add / Remove / Intersect, its part in the tooltip,
  in a box on top of the Extrude dialog, which takes the feature's name as its title (J2, J9); a
  preview failure's status message goes with its dialog (J2); no "Start Part" box in the Tasks
  panel under the Onshape keymap (J2); a pattern's dialog title is its name, red in error (J16).

Designed geometry: the Enclosure 40 x 40 x 10 at the origin (16000) with its lid sketch (30 x 30 on
its top; a pad's default length is 10: 9000 more), and a part "Panel" 20 x 20 x 10 at x 60..80
(4000), apart from it. A sketch on the Enclosure's XY plane padded 10 from z 0: a 20 x 10
rectangle at x 70..90 overlaps Panel only (Panel then 4000 + 10 x 10 x 10 = 5000); one at x 30..70
overlaps both (a new part of 40 x 10 x 10 = 4000); one at x 100..110 touches nothing (1000)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from PySide6 import QtTest

from PartDesignTests.TestCrossBodyGui import ResultBoxGuiCase
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor
from PartDesignTests.TestStudio import pad, sketch, xyPlane
from PartDesignTests.TestCrossBodyGui import siblingEraPath  # ops#654 list on first use

ENCLOSURE = 16000
LID = ENCLOSURE + 9000
PANEL = 4000


class DialogFlowCase(ResultBoxGuiCase):
    def parts(self):
        self.enclosure()
        self.panel = self.part("Panel", (60, 0, 80, 20), 0)

    def planeSketch(self, rect):
        """A sketch of `rect` on the Enclosure's XY plane, in the Enclosure."""
        planeSk = sketch(self.body, "PlaneSk", xyPlane(self.body), rect)
        self.doc.recompute()
        return planeSk

    def newPad(self, *selection):
        """PartDesign_Pad with the Enclosure active and `selection` selected; the new Pad, its
        dialog open. (By object, not name: a dropped pad's name is free again.)"""
        before = list(self.doc.Objects)
        self.runCommand("PartDesign_Pad", *selection)
        [made] = [
            o
            for o in self.doc.Objects
            if o.TypeId == "PartDesign::Pad" and not any(o is old for old in before)
        ]
        return made

    def newBodies(self, before):
        return [
            o
            for o in self.doc.Objects
            if o.TypeId == "PartDesign::Body" and o.Name not in before
        ]

    def bodyNames(self):
        return {o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Body"}

    def titleButton(self, feature):
        """The visible tool button in the task panel showing the feature's name, or None."""
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        for button in Gui.getMainWindow().findChildren(QtWidgets.QToolButton):
            if button.isVisible() and button.text() == feature.Label:
                return button
        return None


class TestOpeningOperationGui(DialogFlowCase):
    """Hands-on check A-1: where a new Extrude opens."""

    @siblingEraPath
    def testASketchOnAPartFaceOpensAsAdd(self):
        """The lid sketch on the Enclosure's top: the pad stays in the Enclosure, Add to
        Enclosure; OK: the Enclosure 25000, Panel 4000, no new part."""
        self.parts()
        bodies = self.bodyNames()
        lid = self.newPad(self.lidSk)
        self.assertIs(lid.getParentGeoFeatureGroup(), self.body)
        self.assertEqual(self.combo().currentText(), "Add")
        self.close(ok=True)
        self.assertEqual(self.newBodies(bodies), [])
        self.assertAlmostEqual(self.body.Shape.Volume, LID, places=3)
        self.assertAlmostEqual(self.panel.Shape.Volume, PANEL, places=3)

    @siblingEraPath
    def testAPlaneSketchOverOnePartOpensAsAddToIt(self):
        """A plane sketch at x 70..90, in the Enclosure, overlapping Panel only: the pad and its
        sketch go into Panel, Add to Panel; OK: Panel 5000, the Enclosure 16000, no new part."""
        self.parts()
        planeSk = self.planeSketch((70, 5, 90, 15))
        bodies = self.bodyNames()
        made = self.newPad(planeSk)
        self.assertIs(made.getParentGeoFeatureGroup(), self.panel)
        self.assertIs(planeSk.getParentGeoFeatureGroup(), self.panel)
        self.assertEqual(self.combo().currentText(), "Add")
        self.close(ok=True)
        self.assertEqual(self.newBodies(bodies), [])
        self.assertTrue(made.isValid(), made.getStatusString())
        self.assertAlmostEqual(self.panel.Shape.Volume, PANEL + 1000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, ENCLOSURE, places=3)

    @siblingEraPath
    def testAPlaneSketchOverTwoPartsOpensAsNew(self):
        """A plane sketch at x 30..70 overlapping the Enclosure and Panel: New, a part of its own
        (A-1 (c): neither is merged); OK: the new part 4000, the others as they were."""
        self.parts()
        planeSk = self.planeSketch((30, 5, 70, 15))
        bodies = self.bodyNames()
        made = self.newPad(planeSk)
        [part] = self.newBodies(bodies)
        self.assertIs(made.getParentGeoFeatureGroup(), part)
        self.assertEqual(self.combo().currentText(), "New")
        self.close(ok=True)
        self.assertAlmostEqual(part.Shape.Volume, 4000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, ENCLOSURE, places=3)
        self.assertAlmostEqual(self.panel.Shape.Volume, PANEL, places=3)

    @siblingEraPath
    def testAPlaneSketchTouchingNothingOpensAsNew(self):
        """A plane sketch at x 100..110 touching no part: New; OK: the new part 1000."""
        self.parts()
        planeSk = self.planeSketch((100, 0, 110, 10))
        bodies = self.bodyNames()
        made = self.newPad(planeSk)
        [part] = self.newBodies(bodies)
        self.assertIs(made.getParentGeoFeatureGroup(), part)
        self.assertEqual(self.combo().currentText(), "New")
        self.close(ok=True)
        self.assertAlmostEqual(part.Shape.Volume, 1000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, ENCLOSURE, places=3)

    @siblingEraPath
    def testCancelTakesTheOpeningMoveBack(self):
        """The pad moved into Panel at its opening, then Cancel: no pad, the sketch back in the
        Enclosure, no new part, the volumes as they were."""
        self.parts()
        planeSk = self.planeSketch((70, 5, 90, 15))
        bodies = self.bodyNames()
        made = self.newPad(planeSk)
        name = made.Name
        self.assertIs(made.getParentGeoFeatureGroup(), self.panel)
        self.close(ok=False)
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(name))
        self.assertIs(planeSk.getParentGeoFeatureGroup(), self.body)
        self.assertEqual(self.newBodies(bodies), [])
        self.assertAlmostEqual(self.panel.Shape.Volume, PANEL, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, ENCLOSURE, places=3)

    @siblingEraPath
    def testTheFirstProfilePickedDecides(self):
        """Nothing selected, Pad: the pad starts in the Enclosure with its Profile field armed;
        the plane sketch over Panel picked: the edit restarts with the pad in Panel, Add to
        Panel; OK: Panel 5000."""
        self.parts()
        planeSk = self.planeSketch((70, 5, 90, 15))
        made = self.newPad()
        self.assertIs(made.getParentGeoFeatureGroup(), self.body)
        Gui.Selection.addSelection(self.doc.Name, planeSk.Name)
        self.assertTrue(
            waitFor(lambda: made.getParentGeoFeatureGroup() == self.panel),
            "the first profile didn't move the pad into Panel",
        )
        self.waitForPanel()
        self.assertTrue(
            waitFor(lambda: self.combo() is not None
                    and self.combo().currentText() == "Add"),
            "the edit didn't restart on the moved pad",
        )
        self.close(ok=True)
        self.assertAlmostEqual(self.panel.Shape.Volume, PANEL + 1000, places=3)


class TestDialogKeysGui(DialogFlowCase):
    """Rank 38 (B-1, the hands-on notes) and rank 36 (B-4)."""

    def testEnterOnACheckBoxAccepts(self):
        """The lid pad's dialog, the focus on its Reversed check box: Enter accepts the dialog;
        the box isn't toggled (the Enclosure 25000)."""
        self.enclosure()
        lid = self.newPad(self.lidSk)
        box = self.visible(QtWidgets.QCheckBox, "checkBoxReversed")
        self.assertIsNotNone(box, "no Reversed check box")
        box.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.3)
        QtTest.QTest.keyClick(box, QtCore.Qt.Key_Return)
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Enter left the dialog open")
        self.assertFalse(lid.Reversed)
        self.assertAlmostEqual(self.body.Shape.Volume, LID, places=3)

    def testEnterInAValueFieldOnlyCommitsTheValue(self):
        """The lid pad's length set to 20 and Enter in the field: the dialog stays open with the
        pad 20 long (the Enclosure 16000 + 18000); Enter in the graphics area then accepts it."""
        self.enclosure()
        lid = self.newPad(self.lidSk)
        length = self.visible(QtWidgets.QWidget, "lengthEdit")
        self.assertIsNotNone(length, "no length field")
        length.setFocus(QtCore.Qt.OtherFocusReason)
        length.setProperty("rawValue", 20.0)
        pump(0.3)
        QtTest.QTest.keyClick(length, QtCore.Qt.Key_Return)
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "Enter in the length field closed the dialog")
        self.assertAlmostEqual(lid.Length.Value, 20.0, places=6)
        viewport = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
        viewport.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.3)
        QtTest.QTest.keyClick(viewport, QtCore.Qt.Key_Return)
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Enter in the graphics left it open")
        self.assertAlmostEqual(self.body.Shape.Volume, ENCLOSURE + 18000, places=3)

    def testEnterInTheGraphicsWithNoDialogDoesNothing(self):
        """B-1's second Enter: with no dialog open, Enter in the graphics area changes nothing."""
        self.enclosure()
        names = sorted(o.Name for o in self.doc.Objects)
        viewport = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
        viewport.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.2)
        QtTest.QTest.keyClick(viewport, QtCore.Qt.Key_Return)
        pump(0.3)
        self.assertFalse(Gui.Control.activeDialog())
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)

    def testTheTitleIsTheFeatureNameRedInError(self):
        """The lid pad's dialog: a title shows its name, not red. A new pad with no profile: its
        title shows its name, red (in error until a profile is picked)."""
        self.enclosure()
        lid = self.newPad(self.lidSk)
        title = self.titleButton(lid)
        self.assertIsNotNone(title, "no title with the feature's name")
        self.assertFalse(title.property("featureInError"))
        self.close(ok=True)
        empty = self.newPad()
        self.assertFalse(empty.isValid())
        self.assertTrue(waitFor(lambda: self.titleButton(empty) is not None), "no title")
        self.assertTrue(
            waitFor(lambda: bool(self.titleButton(empty).property("featureInError"))),
            "the title of a feature in error isn't red",
        )


class TestAnotherToolGui(DialogFlowCase):
    """Rank 24 (F2): another tool started with a dialog open. Needs regeneration round 1's step
    lock (Document.isStepLocked) and the commit-or-drop in Gui::Command::acceptOpenDialog."""

    def setUp(self):
        super().setUp()
        if not hasattr(self.doc, "isStepLocked"):
            self.tearDown()  # unittest runs no tearDown after a skip in setUp: close the document
            self.skipTest("needs regeneration round 1 (Document.isStepLocked)")

    def pads(self):
        return [o for o in self.doc.Objects if o.TypeId == "PartDesign::Pad"]

    # The second Pad runs with nothing selected: a selection made while the first dialog is open
    # goes into its armed Profile field, as Onshape's does (the first dialog then has input)

    def testAnEmptyDialogIsDropped(self):
        """A new pad with nothing given, then Pad again: the empty pad is gone, with no message,
        and the new pad's dialog is open."""
        self.enclosure()
        before = self.pads()
        empty = self.newPad()
        second = self.newPad()
        # by object: the new pad may take the dropped one's name
        self.assertFalse(any(o is empty for o in self.doc.Objects), "the empty dialog's pad stayed")
        self.assertEqual([p.Name for p in self.pads()], [p.Name for p in before] + [second.Name])
        self.assertTrue(Gui.Control.activeDialog())

    def testADialogWithInputIsCommittedInError(self):
        """A new pad with no profile but its length typed (20), then Pad again: the first pad is
        committed, in error (no profile), 20 long; the new pad's dialog is open."""
        self.enclosure()
        first = self.newPad()
        length = self.visible(QtWidgets.QWidget, "lengthEdit")
        self.assertIsNotNone(length, "no length field")
        length.setProperty("rawValue", 20.0)
        pump(0.3)
        self.assertAlmostEqual(first.Length.Value, 20.0, places=6)
        second = self.newPad()
        self.assertIsNotNone(self.doc.getObject(first.Name), "the dialog with input was dropped")
        self.assertFalse(first.isValid())
        self.assertAlmostEqual(first.Length.Value, 20.0, places=6)
        self.assertNotEqual(first.Name, second.Name)
        self.assertTrue(Gui.Control.activeDialog())

    def testADialogWithAnUnresolvedNameIsNotAccepted(self):
        """Review check-r3 (3): a field showing an unresolved #name has disabled the dialog's OK
        (hands-on F10), so Pad again doesn't accept the open dialog either: the Pad is refused
        and the first pad's dialog stays open. (The field's mark is set as QuantitySpinBox sets
        it; TestVariableFieldsGui types the name.)"""
        self.enclosure()
        first = self.newPad()
        length = self.visible(QtWidgets.QWidget, "lengthEdit")
        self.assertIsNotNone(length, "no length field")
        length.setProperty("unresolvedVariable", True)
        pump(0.3)
        before = list(self.doc.Objects)
        self.runCommand("PartDesign_Pad")
        self.assertEqual(
            [o.Name for o in self.doc.Objects if not any(o is old for old in before)],
            [],
            "Pad ran over a dialog whose OK an unresolved #name disabled",
        )
        self.assertIsNotNone(self.doc.getObject(first.Name))
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertTrue(self.doc.isStepLocked(), "the first pad's step ended")
        length.setProperty("unresolvedVariable", False)
        pump(0.3)

    @siblingEraPath
    def testAPreselectedProfileIsInput(self):
        """The lid pad's dialog (its profile preselected, nothing else given), then Pad with
        nothing selected: the lid pad is committed (the Enclosure 25000)."""
        self.enclosure()
        lid = self.newPad(self.lidSk)
        self.newPad()
        self.assertIsNotNone(self.doc.getObject(lid.Name))
        self.assertTrue(lid.isValid(), lid.getStatusString())
        self.assertAlmostEqual(lid.Shape.Volume, LID, places=3)


KEYMAP = "User parameter:BaseApp/Preferences/General"  # the preference Keymap (ForkKeymap)
PREVIEW_FAILURE = "Failure while computing removed volume preview: Resulting shape is empty."


class TestRound6PolishGui(DialogFlowCase):
    """Round 6: the journeys' small open items (ops#640)."""

    def setKeymap(self, name):
        group = App.ParamGet(KEYMAP)
        saved = group.GetString("Keymap") if "Keymap" in group.GetStrings() else None
        if name is None:
            group.RemString("Keymap")
        else:
            group.SetString("Keymap", name)
        pump(0.1)
        return saved

    def newBody(self):
        """PartDesign_Body with nothing selected; the new Body."""
        before = self.bodyNames()
        Gui.Selection.clearSelection()
        Gui.runCommand("PartDesign_Body")
        pump(0.3)
        [made] = self.newBodies(before)
        return made

    def testNewPartsAreNamedPartN(self):
        """J22: the Body command makes "Part 1", then "Part 2"; a pad touching nothing, New,
        makes "Part 3" (the lowest N free); with "Part 1" renamed, the next one is "Part 1"
        again. FreeCAD's keymap keeps "Body"."""
        self.enclosure()
        self.assertEqual(self.newBody().Label, "Part 1")
        second = self.newBody()
        self.assertEqual(second.Label, "Part 2")
        planeSk = self.planeSketch((100, 0, 110, 10))
        bodies = self.bodyNames()
        self.newPad(planeSk)
        [part] = self.newBodies(bodies)
        self.assertEqual(part.Label, "Part 3")
        self.close(ok=True)
        self.assertEqual(part.Label, "Part 3")
        [first] = [o for o in self.doc.Objects if o.Label == "Part 1"]
        first.Label = "Bracket"
        self.assertEqual(self.newBody().Label, "Part 1")
        saved = self.setKeymap("FreeCAD")
        try:
            self.assertEqual(self.newBody().Label, "Body")
        finally:
            self.setKeymap(saved)

    def testTheOperationRowReadsOnshapesWordsOnTop(self):
        """J2/J9: the lid pad's and the lid pocket's operation rows read New, Add, Remove,
        Intersect, the part they act on in the tooltips; the row is in the first box, above the
        length field, and that box's title is the feature's name."""
        self.enclosure()
        for command in ("PartDesign_Pad", "PartDesign_Pocket"):
            before = {o.Name for o in self.doc.Objects}
            self.runCommand(command, self.lidSk)
            [feature] = [o for o in self.doc.Objects if o.Name not in before]
            combo = self.combo()
            self.assertIsNotNone(combo, command)
            self.assertEqual(self.items(combo), ["New", "Add", "Remove", "Intersect"], command)
            self.assertEqual(combo.itemData(1, QtCore.Qt.ToolTipRole), "Add to Enclosure")
            self.assertEqual(combo.itemData(2, QtCore.Qt.ToolTipRole), "Remove from Enclosure")
            self.assertEqual(combo.itemData(3, QtCore.Qt.ToolTipRole), "Intersect with Enclosure")
            length = self.visible(QtWidgets.QWidget, "lengthEdit")
            self.assertIsNotNone(length, command)
            top = lambda w: w.mapToGlobal(QtCore.QPoint(0, 0)).y()
            self.assertLess(top(combo), top(length), command)
            title = self.titleButton(feature)
            self.assertIsNotNone(title, command)
            self.assertLess(top(title), top(combo), command)
            self.close(ok=False)

    def testAPreviewFailureMessageGoesWithItsDialog(self):
        """J2: the preview failure's warning, which the status bar shows as the feature's
        preview gives it (a translated user warning), is cleared when its dialog closes."""
        self.enclosure()
        bar = Gui.getMainWindow().statusBar()
        self.runCommand("PartDesign_Pad", self.lidSk)
        # A status shown in the last 5 s holds the bar (MainWindow::showStatus): its timeout's end
        QtCore.QMetaObject.invokeMethod(Gui.getMainWindow(), "clearStatus")
        App.Console.PrintTranslatedUserWarning("Preview", PREVIEW_FAILURE + "\n")
        self.assertTrue(
            waitFor(lambda: bar.currentMessage().startswith(PREVIEW_FAILURE[:40])),
            bar.currentMessage(),
        )
        pump(0.3)
        self.assertTrue(bar.currentMessage().startswith(PREVIEW_FAILURE[:40]), "it went by itself")
        self.close(ok=False)
        pump(0.2)
        self.assertEqual(bar.currentMessage(), "")

    def startPartShown(self):
        Gui.Selection.addSelection(self.doc.Name, self.body.Name)
        pump(0.2)
        Gui.Selection.clearSelection()
        pump(0.3)
        return any(
            b.isVisible() and b.text() == "Start Part"
            for b in Gui.getMainWindow().findChildren(QtWidgets.QToolButton)
        )

    def testNoStartPartBoxUnderTheOnshapeKeymap(self):
        """J2: after a dialog, nothing selected, the Tasks panel has no "Start Part" box under
        the Onshape keymap; FreeCAD's keymap keeps it."""
        self.enclosure()
        self.runCommand("PartDesign_Pad", self.lidSk)
        self.close(ok=False)
        Gui.Control.showTaskView()
        self.assertFalse(self.startPartShown())
        saved = self.setKeymap("FreeCAD")
        try:
            self.assertTrue(self.startPartShown())
        finally:
            self.setKeymap(saved)
        self.assertFalse(self.startPartShown())

    def testThePatternDialogsTitleIsItsNameRedInError(self):
        """J16 N1: a pattern of the base pad: its dialog's title is its name, not red; a pattern
        with nothing to pattern: its name, red."""
        self.enclosure()
        before = {o.Name for o in self.doc.Objects}
        self.runCommand("PartDesign_LinearPattern", self.base)
        [pattern] = [o for o in self.doc.Objects if o.Name not in before]
        self.assertTrue(waitFor(lambda: self.titleButton(pattern) is not None), "no title")
        self.assertFalse(self.titleButton(pattern).property("featureInError"))
        self.close(ok=True)
        before = {o.Name for o in self.doc.Objects}
        self.runCommand("PartDesign_LinearPattern")
        [empty] = [o for o in self.doc.Objects if o.Name not in before]
        self.assertTrue(waitFor(lambda: self.titleButton(empty) is not None), "no title")
        self.assertTrue(
            waitFor(lambda: bool(self.titleButton(empty).property("featureInError"))),
            "the title of a pattern in error isn't red",
        )


class TestStudioPlanesStayGui(unittest.TestCase):
    """Rank 52: a new part studio's planes stay shown after the primitive dialog."""

    def setUp(self):
        self.docs = []
        Gui.activateWorkbench("PartDesignWorkbench")

    def tearDown(self):
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump(0.2)
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump(0.2)
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        pump(0.2)

    def planesShown(self, body):
        shown = body.Origin.ViewObject.Visibility
        return {
            f.Role: shown and f.ViewObject.Visibility
            for f in body.Origin.OriginFeatures
            if f.Role in ("XY_Plane", "XZ_Plane", "YZ_Plane")
        }

    def testThePlanesStayAfterTheBoxDialog(self):
        """Std_New in PartDesign shows the studio's three planes; the additive box's dialog,
        cancelled, and again, accepted: the planes are still shown."""
        before = set(App.listDocuments())
        Gui.runCommand("Std_New")
        pump(0.3)
        [name] = [n for n in App.listDocuments() if n not in before]
        self.docs.append(name)
        doc = App.getDocument(name)
        [body] = [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")]
        self.assertTrue(all(self.planesShown(body).values()), self.planesShown(body))
        for which in (QtWidgets.QDialogButtonBox.Cancel, QtWidgets.QDialogButtonBox.Ok):
            Gui.runCommand("PartDesign_CompPrimitiveAdditive", 0)
            self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no box dialog")
            pump(0.3)
            Gui.Control.showTaskView()
            self.assertTrue(waitFor(lambda: taskButton(which) is not None), "no button")
            taskButton(which).click()
            self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
            pump(0.3)
            self.assertTrue(all(self.planesShown(body).values()), (which, self.planesShown(body)))


if __name__ == "__main__":
    unittest.main()
