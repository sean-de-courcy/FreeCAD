# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (slice 9, T2): the part mirror's and part pattern's command and dialog
#
# In a listed studio, Mirror with no Body active (or a part picked, whole or by a face) makes a
# part mirror (Onshape's Mirror, Part type): a studio feature with the picked part as the part to
# mirror and a New result. Its dialog: the Result box (New / Add / Remove / Intersect and the merge
# scope's ticks, as an Extrude owner's), the part to mirror (a tick per live part; a face click
# picks its part) and the mirror plane (armed once the part is set). Edit again keeps every field;
# Cancel leaves nothing. With a Body active and nothing picked, Mirror stays today's feature mirror.
#
# Designed geometry only: Src, a block x 0..10, y 0..20, z 0..5; P, a block x -20..-2 (1800).
# Src mirrored about its YZ plane is x -10..0: Remove leaves P x -20..-10 (1000).

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests.TestDressUpDeleteKeyGui import pump, taskButton, waitFor
from PartDesignTests.TestReferenceFieldGui import settle
from PartDesignTests.TestStudio import faceAt
from PartDesignTests.TestStudioPartMirror import boxPart, originPlane


def flushDeletes():
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def visible(kind, name):
    flushDeletes()
    for widget in Gui.getMainWindow().findChildren(kind, name):
        if widget.isVisible():
            return widget
    return None


def item(listWidget, text):
    for i in range(listWidget.count()):
        if listWidget.item(i).text() == text:
            return listWidget.item(i)
    return None


class TestStudioPartMirrorGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("StudioPartMirrorGui")
        self.doc.UndoMode = 1
        self.S = self.doc.addObject("App::Part", "S")
        self.src = boxPart(self.doc, self.S, "Src", 0, 0, 10, 20, 0, 5)
        self.P = boxPart(self.doc, self.S, "P", -20, 0, -2, 20, 0, 5)
        self.doc.recompute()
        self.list = PartDesign.studioList(self.S, True)
        self.doc.recompute()
        Gui.Selection.clearSelection()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", None)
        view.setActiveObject("part", self.S)

    def tearDown(self):
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        guiDoc = Gui.getDocument(self.doc.Name)
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        flushDeletes()
        App.closeDocument(self.doc.Name)

    # ------------------------------------------------------------------------------ helpers
    def mirrors(self):
        return [o for o in self.doc.Objects if o.TypeId == "PartDesign::Mirrored"]

    def made(self, owner):
        return [
            b for b in self.doc.Objects
            if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner
        ]

    def accept(self):
        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        self.assertIsNotNone(ok, "no OK button")
        ok.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays open")
        self.doc.recompute()

    def cancel(self):
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        self.doc.recompute()

    def runMirror(self, *selection):
        Gui.Selection.clearSelection()
        for obj, sub in selection:
            Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        Gui.runCommand("PartDesign_Mirrored")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        settle()

    def pick(self, obj, sub=""):
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        pump(0.4)

    def mirrorRemoveFromP(self):
        """Mirror with Src's top face picked; the plane picked (Src's YZ plane); Result Remove,
        P ticked; OK. Returns the owner."""
        pad = self.doc.getObject("SrcPad")
        self.runMirror((pad, faceAt(pad, 5)))
        [owner] = self.mirrors()
        self.assertFalse(
            [b.Name for b in self.doc.Objects
             if b.TypeId == "PartDesign::Body" and b.hasObject(owner)],
            "the part mirror is in no Body",
        )
        self.assertEqual(owner.PatternType, "Part")
        self.assertEqual(list(owner.StudioEntities), ["Src"])
        self.assertEqual(owner.Operation, "Union")
        self.assertEqual(len(self.made(owner)), 1, "New makes a part")
        self.assertIn(owner, self.list.Entries)
        planeButton = visible(QtWidgets.QPushButton, "studioMirrorPlaneButton")
        self.assertIsNotNone(planeButton, "no plane field")
        self.assertTrue(planeButton.isChecked(), "the plane is armed once the part is set")
        yz = originPlane(self.src, "YZ_Plane")
        self.pick(yz)
        self.assertTrue(waitFor(lambda: owner.MirrorPlane and owner.MirrorPlane[0] == yz))
        combo = visible(QtWidgets.QComboBox, "resultCombo")
        self.assertIsNotNone(combo, "no Result box")
        combo.setCurrentIndex(2)  # Remove
        pump(0.3)
        self.assertEqual(owner.Operation, "Subtraction")
        self.assertFalse(self.made(owner), "leaving New deletes its part")
        ticks = visible(QtWidgets.QListWidget, "studioScopeList")
        p = item(ticks, "P")
        self.assertIsNotNone(p, [ticks.item(i).text() for i in range(ticks.count())])
        p.setCheckState(QtCore.Qt.Checked)
        pump(0.3)
        self.assertEqual(list(owner.StudioScope), ["P"])
        self.accept()
        return owner

    # ------------------------------------------------------------------------------ tests
    def testCommandMakesAPartMirror(self):
        """The face pick gives the part; the plane, Remove and P set in the dialog: P loses the
        mirrored copy (1800 -> 1000), Src stays a live part, unchanged."""
        owner = self.mirrorRemoveFromP()
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertAlmostEqual(self.P.Shape.Volume, 1000, places=3)
        self.assertAlmostEqual(self.src.Shape.Volume, 1000, places=3)
        self.assertIn(self.src, PartDesign.studioLiveParts(self.list))

    def testEditAgainKeepsEveryField(self):
        owner = self.mirrorRemoveFromP()
        Gui.getDocument(self.doc.Name).setEdit(owner.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()))
        settle()
        sources = visible(QtWidgets.QListWidget, "studioMirrorSourceList")
        self.assertIsNotNone(sources, "no part field")
        self.assertEqual(item(sources, "Src").checkState(), QtCore.Qt.Checked)
        self.assertEqual(item(sources, "P").checkState(), QtCore.Qt.Unchecked)
        planeButton = visible(QtWidgets.QPushButton, "studioMirrorPlaneButton")
        self.assertIn(originPlane(self.src, "YZ_Plane").Label, planeButton.text())
        self.assertFalse(planeButton.isChecked())
        self.assertEqual(visible(QtWidgets.QComboBox, "resultCombo").currentIndex(), 2)
        ticks = visible(QtWidgets.QListWidget, "studioScopeList")
        self.assertEqual(item(ticks, "P").checkState(), QtCore.Qt.Checked)
        self.cancel()
        self.assertAlmostEqual(self.P.Shape.Volume, 1000, places=3)
        self.assertEqual(owner.Operation, "Subtraction")

    def testCancelLeavesNothing(self):
        pad = self.doc.getObject("SrcPad")
        self.runMirror((pad, faceAt(pad, 5)))
        self.assertEqual(len(self.mirrors()), 1)
        self.cancel()
        self.assertEqual(self.mirrors(), [])
        self.assertEqual(
            sorted(b.Name for b in self.doc.Objects if b.TypeId == "PartDesign::Body"), ["P", "Src"]
        )

    def testABodyActiveKeepsTheFeatureMirror(self):
        """A Body active and nothing picked: the feature mirror, a studio feature since T1a
        (ops#654 10.16: every new feature pattern in a listed studio is one), outside every Body."""
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.src)
        self.runMirror()
        [mirror] = self.mirrors()
        self.assertFalse(self.src.hasObject(mirror))
        self.assertEqual(mirror.getParentGeoFeatureGroup(), self.S)
        self.assertEqual(mirror.PatternType, "Feature")
        self.assertIsNone(visible(QtWidgets.QPushButton, "studioMirrorPlaneButton"))


# ----------------------------------------------------------------------------------------------
# FreeCAD-CH ops#654 T2 (notes/parts-design.md 10.16, "Dialog (minimal)", acceptance T2): the part
# pattern's command and dialog, Linear and Circular. In a listed studio, Linear pattern or Circular
# pattern with a part picked (a Body: a Parts-list row) or with nothing picked and no Body active
# makes a part pattern (PatternType Part), its sources' ids in StudioEntities, New (Union, no
# scope: each copy a part); a feature picked keeps the feature pattern. Its dialog: the Result box,
# the parts to pattern (ticks; a face click picks its part), the native placement panel with its
# Features list hidden. OK makes the copies' parts in the dialog's one step; Cancel leaves nothing.
#
# Designed geometry only (the App suite TestStudioPartPattern's): boxes padded in Bodies of the
# studio S; the expected volumes and centres come from the boxes and the spacing.


def typeInto(name, text):
    """Types text over the value of the visible panel box `name`, key by key, then leaves it
    (which commits it: the boxes don't track keys; Return would press OK)."""
    from PySide import QtGui, QtTest

    box = visible(QtWidgets.QWidget, name)
    if box is None:
        raise AssertionError(f"no box {name}")
    edit = box.findChild(QtWidgets.QLineEdit)
    edit.setFocus()
    edit.selectAll()
    QtTest.QTest.keyClicks(edit, text)
    leave = QtGui.QFocusEvent(QtCore.QEvent.FocusOut, QtCore.Qt.TabFocusReason)
    QtWidgets.QApplication.sendEvent(box, leave)
    pump(0.8)  # the panel's recompute timer (500 ms)


class TestStudioPartPatternGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("StudioPartPatternGui")
        self.doc.UndoMode = 1
        self.S = self.doc.addObject("App::Part", "S")

    def tearDown(self):
        TestStudioPartMirrorGui.tearDown(self)

    # ------------------------------------------------------------------------------ helpers
    def box(self, name, x0, y0, x1, y1, z0, height):
        return boxPart(self.doc, self.S, name, x0, y0, x1, y1, z0, height)

    def start(self, active=None):
        """The studio listed, the workbench up, S the active part, active the active Body."""
        self.doc.recompute()
        self.list = PartDesign.studioList(self.S, True)
        self.doc.recompute()
        Gui.Selection.clearSelection()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", active)
        view.setActiveObject("part", self.S)

    def runTool(self, command, *selection):
        Gui.Selection.clearSelection()
        for entry in selection:
            obj, sub = entry if isinstance(entry, tuple) else (entry, "")
            Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        Gui.runCommand(command)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        settle()

    def patterns(self, typeId="PartDesign::LinearPattern"):
        return [o for o in self.doc.Objects
                if o.TypeId == typeId and getattr(o, "StudioOwner", None) is None]

    def pattern(self, typeId="PartDesign::LinearPattern"):
        found = self.patterns(typeId)
        self.assertEqual(len(found), 1, [o.Name for o in found])
        return found[0]

    def made(self, owner):
        return sorted(
            (b for b in self.doc.Objects
             if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner),
            key=lambda b: b.StudioPartId,
        )

    def bodies(self):
        return sorted(b.Name for b in self.doc.Objects if b.TypeId == "PartDesign::Body")

    def live(self):
        return sorted(b.Name for b in PartDesign.studioLiveParts(self.list))

    def shape(self, part):
        body = self.doc.getObject(part) if isinstance(part, str) else part
        return body.Tip.Shape

    def assertVolume(self, part, expected):
        self.assertAlmostEqual(self.shape(part).Volume, expected, places=3, msg=str(part))

    def assertCentres(self, bodies, expected):
        got = sorted(tuple(round(c, 4) for c in self.shape(b).CenterOfMass) for b in bodies)
        self.assertEqual(got, sorted(tuple(float(c) for c in e) for e in expected))

    def assertValid(self, *objects):
        for obj in objects:
            self.assertTrue(obj.isValid(), f"{obj.Name}: {obj.getStatusString()}")

    def accept(self):
        TestStudioPartMirrorGui.accept(self)

    def cancel(self):
        TestStudioPartMirrorGui.cancel(self)

    def result(self, index):
        """The Result row: 0 New, 1 Add, 2 Remove, 3 Intersect."""
        combo = visible(QtWidgets.QComboBox, "resultCombo")
        self.assertIsNotNone(combo, "no Result box")
        combo.setCurrentIndex(index)
        pump(0.3)

    def tick(self, name):
        ticks = visible(QtWidgets.QListWidget, "studioScopeList")
        self.assertIsNotNone(ticks, "no merge scope ticks")
        row = item(ticks, name)
        self.assertIsNotNone(row, [ticks.item(i).text() for i in range(ticks.count())])
        row.setCheckState(QtCore.Qt.Checked)
        pump(0.3)

    def spacing(self, spacing, count):
        typeInto("spinSpacing", f"{spacing} mm")
        typeInto("spinOccurrences", str(count))

    def edit(self, owner):
        Gui.getDocument(self.doc.Name).setEdit(owner.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()))
        settle()

    def undoRedo(self, before, after):
        """One undo gives before(), one redo after() (each asserts the state)."""
        self.doc.undo()
        self.doc.recompute()
        before()
        self.doc.redo()
        self.doc.recompute()
        after()

    def linearOf(self, source, operation, scope, spacing, count):
        """Linear pattern with the part source picked, the Result row operation, scope ticked,
        spacing and count typed; OK. One undo step. Returns the pattern."""
        undo = self.doc.UndoCount
        self.runTool("PartDesign_LinearPattern", source)
        pat = self.pattern()
        if operation:
            self.result(operation)
        for name in scope:
            self.tick(name)
        self.spacing(spacing, count)
        self.accept()
        self.assertEqual(self.doc.UndoCount, undo + 1, self.doc.UndoNames[:3])
        return pat

    def o5(self):
        p = self.box("P", 0, 0, 30, 20, 0, 5)
        s = self.box("Src", 0, 5, 10, 15, 5, 5)
        self.start()
        return p, s

    def q5(self):
        p = self.box("P", 0, 0, 60, 20, 0, 10)
        s = self.box("Src", 5, 5, 10, 10, 0, 20)
        self.start()
        return p, s

    # ------------------------------------------------------------------------------ the command
    def testAPickedPartMakesAPartPattern(self):
        """A Body picked (a Parts-list row), another Body active: a part pattern of it, outside
        every Body, New (Union, no scope); its dialog: the parts ticked, Result New, no Features
        list, the studio's X as direction."""
        p, s = self.o5()
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", p)
        self.runTool("PartDesign_LinearPattern", s)
        pat = self.pattern()
        self.assertEqual(pat.PatternType, "Part")
        self.assertEqual(list(pat.StudioEntities), ["Src"])
        self.assertEqual(pat.Operation, "Union")
        self.assertEqual(list(pat.StudioScope), [])
        self.assertEqual(pat.getParentGeoFeatureGroup(), self.S)
        self.assertFalse([b.Name for b in self.doc.Objects
                          if b.TypeId == "PartDesign::Body" and b.hasObject(pat)])
        self.assertIn(pat, self.list.Entries)
        self.assertEqual(pat.Direction[0], self.S.Origin.OriginFeatures[0])
        sources = visible(QtWidgets.QListWidget, "studioPatternSourceList")
        self.assertIsNotNone(sources, "no parts field")
        self.assertEqual(item(sources, "Src").checkState(), QtCore.Qt.Checked)
        self.assertEqual(item(sources, "P").checkState(), QtCore.Qt.Unchecked)
        self.assertEqual(visible(QtWidgets.QComboBox, "resultCombo").currentIndex(), 0)
        self.assertIsNone(visible(QtWidgets.QWidget, "fieldOriginals"), "a Features list")
        self.assertIsNone(visible(QtWidgets.QCheckBox, "checkBoxReapply"))
        self.assertIsNotNone(visible(QtWidgets.QWidget, "spinOccurrences"), "no placement panel")
        self.cancel()

    def testNoPickAndNoBodyMakesAPartPattern(self):
        """Circular pattern, nothing picked, no Body active: a part pattern with no part yet, its
        parts field armed; a face of Src clicked: Src is the part; the studio's Z the axis."""
        self.box("Src", 10, -5, 20, 5, 0, 10)
        self.start()
        self.runTool("PartDesign_PolarPattern")
        pat = self.pattern("PartDesign::PolarPattern")
        self.assertEqual(pat.PatternType, "Part")
        self.assertEqual(list(pat.StudioEntities), [])
        self.assertEqual(pat.Axis[0], self.S.Origin.OriginFeatures[2])
        button = visible(QtWidgets.QPushButton, "studioPatternSourceButton")
        self.assertIsNotNone(button, "no parts field")
        self.assertTrue(button.isChecked(), "the parts field isn't armed")
        pad = self.doc.getObject("SrcPad")
        Gui.Selection.addSelection(self.doc.Name, pad.Name, faceAt(pad, 10))
        self.assertTrue(waitFor(lambda: list(pat.StudioEntities) == ["Src"]), pat.StudioEntities)
        self.cancel()
        self.assertEqual(self.patterns("PartDesign::PolarPattern"), [])

    def testAPickedFeatureKeepsTheFeaturePattern(self):
        """Src active, its Pad picked: the feature pattern (T1a), its original the Pad."""
        s = self.box("Src", 0, 0, 10, 10, 0, 10)
        self.start(active=s)
        pad = self.doc.getObject("SrcPad")
        self.runTool("PartDesign_LinearPattern", pad)
        pat = self.pattern()
        self.assertEqual(pat.PatternType, "Feature")
        self.assertEqual(list(pat.Originals), [pad])
        self.assertIsNone(visible(QtWidgets.QListWidget, "studioPatternSourceList"))
        self.cancel()

    def testCancelLeavesNothing(self):
        p, s = self.o5()
        undo = self.doc.UndoCount
        self.runTool("PartDesign_LinearPattern", s)
        self.spacing(20, 3)
        self.cancel()
        self.assertEqual(self.patterns(), [])
        self.assertEqual(self.bodies(), ["P", "Src"])
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertNotIn("LinearPattern", [e.Name for e in self.list.Entries])

    # ------------------------------------------------------------------------------ acceptance T2
    def testO5AddThroughTheDialog(self):
        """T2 (1), O5: +x 20 x 3, Add, scope P: P 4000 with its id, Src consumed, instance 3 a new
        part of 500; one undo takes it all back, redo brings it again."""
        p, s = self.o5()
        pat = self.linearOf(s, 1, ("P",), 20, 3)
        self.assertEqual((pat.Occurrences, pat.Offset.Value), (3, 20))

        def after():
            pat = self.doc.getObject("LinearPattern")
            self.assertValid(pat)
            self.assertVolume("P", 4000)
            self.assertIs(PartDesign.studioConsumerOf(s), pat)
            [new] = self.made(pat)
            self.assertVolume(new, 500)
            self.assertCentres([new], [(45, 10, 7.5)])
            self.assertEqual(self.live(), sorted(["P", new.Name]))

        def before():
            self.assertIsNone(self.doc.getObject("LinearPattern"))
            self.assertVolume("P", 3000)
            self.assertEqual(self.live(), ["P", "Src"])

        after()
        self.undoRedo(before, after)

    def testNewThreeThenFiveAndBack(self):
        """T2 (2): New +x 20 x 3: two parts following the source (its pad 10 -> 5: 500 each);
        count 3 -> 5 in the dialog: four parts, one undo step; 5 -> 3: the two Bodies deleted in
        the same step; each undone and redone."""
        s = self.box("Src", 0, 0, 10, 10, 0, 10)
        self.start()
        pat = self.linearOf(s, None, (), 20, 3)
        self.assertValid(pat)
        made = self.made(pat)
        self.assertEqual([b.StudioPartId for b in made], ["LinearPattern:1", "LinearPattern:2"])
        self.assertCentres(made, [(25, 5, 5), (45, 5, 5)])
        self.doc.getObject("SrcPad").Length = 5
        self.doc.recompute()
        for body in self.made(pat):
            self.assertVolume(body, 500)

        undo = self.doc.UndoCount
        self.edit(pat)
        typeInto("spinOccurrences", "5")
        self.accept()
        self.assertEqual(self.doc.UndoCount, undo + 1, self.doc.UndoNames[:3])
        self.assertValid(pat)
        self.assertEqual(len(self.made(pat)), 4)
        self.assertCentres(self.made(pat), [(25, 5, 2.5), (45, 5, 2.5), (65, 5, 2.5), (85, 5, 2.5)])
        extra = [b.Name for b in self.made(pat)[2:]]
        self.undoRedo(lambda: self.assertEqual(len(self.made(pat)), 2),
                      lambda: self.assertEqual(len(self.made(pat)), 4))

        undo = self.doc.UndoCount
        self.edit(pat)
        typeInto("spinOccurrences", "3")
        self.accept()
        self.assertEqual(self.doc.UndoCount, undo + 1, self.doc.UndoNames[:3])
        self.assertValid(pat)
        self.assertEqual(len(self.made(pat)), 2)
        for name in extra:
            self.assertIsNone(self.doc.getObject(name), f"{name}: an empty Body kept")
        self.assertEqual(len(self.live()), 3)
        self.undoRedo(lambda: self.assertEqual(len(self.made(pat)), 4),
                      lambda: self.assertEqual(len(self.made(pat)), 2))

    def testRemoveFromAPlate(self):
        """T2 (3), Q5: +x 15 x 3, Remove, scope P: three holes (11250), Src consumed."""
        p, s = self.q5()
        self.linearOf(s, 2, ("P",), 15, 3)

        def after():
            pat = self.doc.getObject("LinearPattern")
            self.assertValid(pat)
            self.assertVolume("P", 11250)
            self.assertIs(PartDesign.studioConsumerOf(s), pat)
            self.assertEqual(self.live(), ["P"])

        def before():
            self.assertVolume("P", 12000)
            self.assertEqual(self.live(), ["P", "Src"])

        after()
        self.undoRedo(before, after)

    def testPolarNewFourAboutZ(self):
        """T2 (4): Src x 10..20, y -5..5 about the studio's Z, 4 over 360 (the defaults): three
        new parts of 1000 at (0, 15), (-15, 0), (0, -15)."""
        s = self.box("Src", 10, -5, 20, 5, 0, 10)
        self.start()
        undo = self.doc.UndoCount
        self.runTool("PartDesign_PolarPattern", s)
        self.accept()
        self.assertEqual(self.doc.UndoCount, undo + 1)

        def after():
            pat = self.pattern("PartDesign::PolarPattern")
            self.assertValid(pat)
            made = self.made(pat)
            self.assertCentres(made, [(0, 15, 5), (-15, 0, 5), (0, -15, 5)])
            for body in made:
                self.assertVolume(body, 1000)

        def before():
            self.assertEqual(self.patterns("PartDesign::PolarPattern"), [])
            self.assertEqual(self.bodies(), ["Src"])

        after()
        self.undoRedo(before, after)

    def testIntersectOnOnePart(self):
        """T2 (5), Q5: Intersect, scope P: three new parts of 250, Src consumed, P no part."""
        p, s = self.q5()
        self.linearOf(s, 3, ("P",), 15, 3)

        def after():
            pat = self.doc.getObject("LinearPattern")
            self.assertValid(pat)
            made = self.made(pat)
            self.assertCentres(made, [(7.5, 7.5, 5), (22.5, 7.5, 5), (37.5, 7.5, 5)])
            for body in made:
                self.assertVolume(body, 250)
            self.assertEqual(self.live(), sorted(b.Name for b in made))

        def before():
            self.assertEqual(self.live(), ["P", "Src"])
            self.assertVolume("P", 12000)

        after()
        self.undoRedo(before, after)

    def testEditAgainShowsTheStoredFields(self):
        """Reopened: Src ticked, Result Remove, P ticked, count 3; Cancel changes nothing."""
        p, s = self.q5()
        pat = self.linearOf(s, 2, ("P",), 15, 3)
        self.edit(pat)
        sources = visible(QtWidgets.QListWidget, "studioPatternSourceList")
        self.assertIsNotNone(sources, "no parts field")
        self.assertEqual(item(sources, "Src").checkState(), QtCore.Qt.Checked)
        self.assertEqual(visible(QtWidgets.QComboBox, "resultCombo").currentIndex(), 2)
        self.assertEqual(item(visible(QtWidgets.QListWidget, "studioScopeList"), "P").checkState(),
                         QtCore.Qt.Checked)
        self.assertEqual(visible(QtWidgets.QSpinBox, "spinOccurrences").cleanText(), "3")
        self.assertIsNone(visible(QtWidgets.QWidget, "fieldOriginals"), "a Features list")
        self.cancel()
        self.assertVolume("P", 11250)
        self.assertEqual(pat.Operation, "Subtraction")

    def testLoudStatesShowTheAppsWords(self):
        """Intersect with overlapping instances (spacing 2 on a pin 5 wide): the parts field's
        note says so in the App's words; a copy gone under a later feature: reopened, the note
        says the pattern no longer makes it."""
        p, s = self.q5()
        self.runTool("PartDesign_LinearPattern", s)
        self.result(3)
        self.tick("P")
        self.spacing(2, 2)
        note = visible(QtWidgets.QLabel, "studioPatternNote")
        self.assertTrue(waitFor(lambda: note.isVisible() and "overlap" in note.text()),
                        note.text())
        self.cancel()

    def testACopyGoneUnderALaterFeatureIsLoud(self):
        from PartDesignTests.TestStudio import pad, sketch, xyPlane

        s = self.box("Src", 0, 0, 10, 10, 0, 10)
        self.start()
        pat = self.linearOf(s, None, (), 20, 3)
        second = self.made(pat)[1]
        self.doc.openTransaction("boss")
        sk = sketch(second, "BossSk", xyPlane(second), (42, 2, 48, 8), z=10)
        boss = pad(second, "Boss", sk, 2)
        for obj in (sk, boss):
            if obj not in self.list.Entries:
                PartDesign.studioInsert(obj, -1)
        self.doc.recompute()
        self.doc.commitTransaction()
        self.doc.recompute()
        self.edit(pat)
        typeInto("spinOccurrences", "2")
        self.accept()
        self.assertIsNotNone(self.doc.getObject(second.Name))
        self.assertFalse(pat.isValid())
        self.edit(pat)
        note = visible(QtWidgets.QLabel, "studioPatternNote")
        self.assertTrue(waitFor(lambda: note.isVisible() and "no longer makes the copy" in note.text()),
                        note.text())
        self.cancel()


if __name__ == "__main__":
    unittest.main()
