# SPDX-License-Identifier: LGPL-2.1-or-later
# ***************************************************************************
# *   Copyright (c) 2026 FreeCAD-CH contributors                            *
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
# ***************************************************************************

"""Pick-first feature dialogs (FreeCAD-CH ops#640, ranks 13 and 5).

Profile features (Pad, Pocket, Hole, Loft, Pipe), Mirror and the patterns open with their first
field armed, as Onshape's do. With nothing selected Pad makes its feature with no profile, red,
and arms the Profile field: no sketch list (TaskFeaturePick), no "No sketch" message box. A
selection the feature can't take is left out and said in the field's status (or the status bar),
never in a modal. Mirror and the patterns with nothing selected stay in Features mode, their
Features field armed. The Extrude's profile gate refuses a face that isn't planar (B3-4).

Designed models, each built by the test:
- Plate: a sketch of a rectangle 0..10 x 0..20 in a Body. Padded 10 long: 2000 mm^3.
- Disc: a circle r 5 at the origin padded 10: a cylinder, 250 pi. Its side face is curved, its
  top (z = 10) is planar; a Pad of the top face, 10 long, makes the cylinder 20 high: 500 pi.
- Cube: a 10 x 10 x 10 additive box at the origin. Mirrored in the XY plane it adds the box
  z -10..0: 2000. A new linear pattern along X (spacing 25, 2 occurrences) adds a copy at x 25,
  kept since the cube is a part of its own: 2000.
"""

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestDressUpDeleteKeyGui import pump, taskButton, waitFor
from PartDesignTests.TestCrossBodyGui import siblingEraPath  # ops#654 list on first use


def flushDeletes():
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def visibleField(name):
    """The task view's visible reference field of that objectName ("fieldProfile"), or None."""
    flushDeletes()
    found = [
        widget
        for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget, name)
        if widget.isVisible()
    ]
    return found[0] if found else None


def armed(field):
    return field is not None and bool(field.property("armed"))


def notes(name):
    """Where a left-out selection is said: the status of the field `name`, and the status bar."""
    texts = [label.text() for label in Gui.getMainWindow().statusBar().findChildren(QtWidgets.QLabel)]
    flushDeletes()
    for field in Gui.getMainWindow().findChildren(QtWidgets.QWidget, name):
        status = field.findChild(QtWidgets.QLabel, "status")
        if status is not None:
            texts.append(status.text())
    return texts


class TestPickFirstGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PickFirst")
        self.doc.UndoMode = 1
        self.modals = []
        self.answering = False
        Gui.Selection.clearSelection()

    def tearDown(self):
        self.answering = False
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

    # -- helpers ---------------------------------------------------------------------------------

    def watchModals(self):
        """Until self.answering is False: records and closes any modal (none is expected)."""
        self.answering = True

        def poll():
            if not self.answering:
                return
            widget = QtWidgets.QApplication.activeModalWidget()
            if widget is not None:
                text = widget.text() if isinstance(widget, QtWidgets.QMessageBox) else ""
                self.modals.append(widget.metaObject().className() + ": " + text)
                widget.reject()
            QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)

    def activate(self, body):
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", body)

    def runTool(self, command, *selection):
        """`command` with `selection` (objects, or (object, element) pairs) selected; waits for
        its dialog, with no modal on the way."""
        Gui.Selection.clearSelection()
        for item in selection:
            if isinstance(item, tuple):
                Gui.Selection.addSelection(self.doc.Name, item[0].Name, item[1])
            else:
                Gui.Selection.addSelection(self.doc.Name, item.Name)
        self.watchModals()
        Gui.runCommand(command)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.5)
        self.answering = False
        self.assertEqual(self.modals, [])
        # no sketch list: the pick dialog's list widget isn't there
        self.assertIsNone(
            Gui.getMainWindow().findChild(QtWidgets.QListWidget, "listWidget"), "a sketch list"
        )

    def only(self, typeId):
        found = [o for o in self.doc.Objects if o.TypeId == typeId]
        self.assertEqual(len(found), 1, [o.Name for o in found])
        return found[0]

    def plate(self):
        self.body = models.body(self.doc)
        self.sketch = models.sketch(self.doc, "Plate", models.rectangle(0, 0, 10, 20), self.body)
        self.doc.recompute()
        self.activate(self.body)

    def disc(self):
        """The Disc: a cylinder r 5, z 0..10. Returns the pad and its curved and top faces."""
        self.body = models.body(self.doc)
        sketch = models.sketch(self.doc, "Disc", [models.circle(0, 0, 5)], self.body)
        pad = models.pad(self.body, sketch, 10, name="Disc")
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 250 * math.pi, places=4)
        curved = top = None
        for index, face in enumerate(pad.Shape.Faces, 1):
            if isinstance(face.Surface, Part.Cylinder):
                curved = f"Face{index}"
            elif abs(face.CenterOfMass.z - 10) < 1e-6:
                top = f"Face{index}"
        self.assertIsNotNone(curved)
        self.assertIsNotNone(top)
        self.activate(self.body)
        return pad, curved, top

    def cube(self):
        self.body = models.body(self.doc)
        self.box = self.doc.addObject("PartDesign::AdditiveBox", "Cube")
        self.body.addObject(self.box)
        for prop in ("Length", "Width", "Height"):
            setattr(self.box, prop, 10)
        self.doc.recompute()
        self.activate(self.body)

    # -- profile features ------------------------------------------------------------------------

    @siblingEraPath
    def testPadWithNothingSelectedArmsItsProfile(self):
        """Pad with nothing selected: a Pad with no profile, red, its Profile field armed (no
        sketch list although the document has one free sketch, no message box). The sketch
        picked: the Pad takes it, valid, 2000 mm^3."""
        self.plate()
        self.runTool("PartDesign_Pad")
        pad = self.only("PartDesign::Pad")
        self.assertIsNone(pad.Profile)
        self.assertFalse(pad.isValid())
        self.assertTrue(waitFor(lambda: armed(visibleField("fieldProfile"))), "Profile isn't armed")
        field = visibleField("fieldProfile")
        self.assertTrue(field.property("missing"), "the empty Profile isn't shown missing")
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name)
        self.assertTrue(waitFor(lambda: pad.Profile is not None), "the pick wasn't taken")
        self.assertIs(pad.Profile[0], self.sketch)
        pad.Length = 10
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, 2000, places=4)

    def testCancelOfAPadWithNoProfileLeavesNothing(self):
        """The Pad made with no profile, then Cancel: it goes, and so does its transaction."""
        self.plate()
        names = sorted(o.Name for o in self.doc.Objects)
        undo = self.doc.UndoNames
        self.runTool("PartDesign_Pad")
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump(0.2)
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertIsNone(App.getActiveTransaction())
        self.assertEqual(self.doc.UndoNames, undo)

    def testPadOnAnOriginPlaneIsLeftOut(self):
        """Pad with the XY plane selected: no profile can come from it (Pad made nothing, without
        a word): the Pad starts empty and the plane is said to be left out."""
        self.plate()
        plane = models.originFeature(self.body, "XY_Plane")
        self.runTool("PartDesign_Pad", plane)
        pad = self.only("PartDesign::Pad")
        self.assertIsNone(pad.Profile)
        self.assertTrue(
            waitFor(lambda: any("Left out of the selection" in t for t in notes("fieldProfile"))),
            notes("fieldProfile"),
        )

    @siblingEraPath
    def testPadOfACurvedFaceStartsEmpty(self):
        """Rank 5: the Disc's curved face selected, then Pad: the face is left out (an extrude
        takes planar faces), said in the field or the status bar; the new Pad has no profile."""
        disc, curved, _ = self.disc()
        self.runTool("PartDesign_Pad", (disc, curved))
        pads = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Pad" and o is not disc]
        self.assertEqual(len(pads), 1)
        self.assertIsNone(pads[0].Profile)
        self.assertTrue(
            waitFor(lambda: any("is not planar" in t for t in notes("fieldProfile"))),
            notes("fieldProfile"),
        )

    @siblingEraPath
    def testPadOfASolidsEdgeStartsEmpty(self):
        """Hands-on B-2: an edge of a solid selected, then Extrude: Onshape opens with the field
        empty. The Disc's top circle selected, then Pad: the new Pad has no profile and the edge
        is said to be left out."""
        disc, _, _ = self.disc()
        [edge] = [
            f"Edge{i}"
            for i, e in enumerate(disc.Shape.Edges, 1)
            if isinstance(e.Curve, Part.Circle) and abs(e.CenterOfMass.z - 10) < 1e-6
        ]
        self.runTool("PartDesign_Pad", (disc, edge))
        pads = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Pad" and o is not disc]
        self.assertEqual(len(pads), 1)
        self.assertIsNone(pads[0].Profile)
        self.assertTrue(
            waitFor(lambda: any("is not a face" in t for t in notes("fieldProfile"))),
            notes("fieldProfile"),
        )

    @siblingEraPath
    def testProfileFieldRefusesACurvedFace(self):
        """Rank 5 (B3-4): with the new Pad's Profile armed the Disc's curved face can't be picked
        (nothing is selected, the Profile stays empty); its top face can: the Pad takes it, and
        10 long it makes the cylinder 20 high, 500 pi."""
        disc, curved, top = self.disc()
        self.runTool("PartDesign_Pad")
        pad = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Pad" and o is not disc][0]
        self.assertTrue(waitFor(lambda: armed(visibleField("fieldProfile"))), "Profile isn't armed")
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, disc.Name + "." + curved)
        pump(0.3)
        self.assertIsNone(pad.Profile)
        self.assertEqual(Gui.Selection.getSelectionEx(self.doc.Name), [])
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, disc.Name + "." + top)
        self.assertTrue(waitFor(lambda: pad.Profile is not None), "the top face wasn't taken")
        self.assertIs(pad.Profile[0], disc)
        self.assertEqual(pad.Profile[1], [top])
        pad.Length = 10
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, 500 * math.pi, places=3)

    def testLeftOutNoteIsInTheProfileFieldInRed(self):
        """The fix round's setNote(): the origin plane's note is in the Profile field's own
        status, in red (not only on the status bar); the sketch picked clears it."""
        self.plate()
        plane = models.originFeature(self.body, "XY_Plane")
        self.runTool("PartDesign_Pad", plane)
        pad = self.only("PartDesign::Pad")
        field = visibleField("fieldProfile")
        self.assertIsNotNone(field)
        status = field.findChild(QtWidgets.QLabel, "status")
        self.assertTrue(
            waitFor(lambda: "Left out of the selection" in status.text()), status.text()
        )
        self.assertIn("red", status.styleSheet())
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name)
        self.assertTrue(waitFor(lambda: pad.Profile is not None), "the pick wasn't taken")
        self.assertNotIn("Left out of the selection", status.text())

    def opensEmptyAndCancels(self, command, typeId):
        """`command` with nothing selected: no modal, no sketch list, the new feature has no
        profile and its Profile field is armed; Cancel leaves the document as it was."""
        names = sorted(o.Name for o in self.doc.Objects)
        undo = self.doc.UndoNames
        self.runTool(command)
        feature = self.only(typeId)
        self.assertIsNone(feature.Profile)
        self.assertTrue(waitFor(lambda: armed(visibleField("fieldProfile"))), "Profile isn't armed")
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump(0.2)
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertIsNone(App.getActiveTransaction())
        self.assertEqual(self.doc.UndoNames, undo)

    def testPocketWithNothingSelectedStartsEmpty(self):
        """Checker's coverage gap: Pocket on the Cube (a solid to subtract from)."""
        self.cube()
        self.opensEmptyAndCancels("PartDesign_Pocket", "PartDesign::Pocket")

    def testHoleWithNothingSelectedStartsEmpty(self):
        """Hole on the Cube: its positions field (Profile) armed, nothing dereferences the
        missing profile (gizmo, base profile type)."""
        self.cube()
        self.opensEmptyAndCancels("PartDesign_Hole", "PartDesign::Hole")

    def testAdditiveLoftWithNothingSelectedStartsEmpty(self):
        self.plate()
        self.opensEmptyAndCancels("PartDesign_AdditiveLoft", "PartDesign::AdditiveLoft")

    def testAdditivePipeWithNothingSelectedStartsEmpty(self):
        self.plate()
        self.opensEmptyAndCancels("PartDesign_AdditivePipe", "PartDesign::AdditivePipe")

    def testSubtractiveLoftWithNothingSelectedStartsEmpty(self):
        self.cube()
        self.opensEmptyAndCancels("PartDesign_SubtractiveLoft", "PartDesign::SubtractiveLoft")

    def testSubtractivePipeWithNothingSelectedStartsEmpty(self):
        self.cube()
        self.opensEmptyAndCancels("PartDesign_SubtractivePipe", "PartDesign::SubtractivePipe")

    # -- Mirror and the patterns -----------------------------------------------------------------

    def testMirrorWithNothingSelectedStaysInFeaturesMode(self):
        """Mirror with nothing selected: Features mode (it was Whole shape), no originals, the
        Features field armed, the cube still shown (1000). The cube picked: mirrored in XY, 2000."""
        self.cube()
        self.runTool("PartDesign_Mirrored")
        mirror = self.only("PartDesign::Mirrored")
        self.assertEqual(mirror.TransformMode, "Features")
        self.assertEqual(mirror.Originals, [])
        self.assertTrue(
            waitFor(lambda: armed(visibleField("fieldOriginals"))), "Features isn't armed"
        )
        self.assertAlmostEqual(mirror.Shape.Volume, 1000, places=4)
        Gui.Selection.addSelection(self.doc.Name, self.box.Name)
        self.assertTrue(waitFor(lambda: mirror.Originals == [self.box]), mirror.Originals)
        self.doc.recompute()
        self.assertTrue(mirror.isValid(), mirror.getStatusString())
        self.assertAlmostEqual(mirror.Shape.Volume, 2000, places=4)

    @siblingEraPath
    def testLinearPatternWithNothingSelectedArmsItsFeatures(self):
        """Linear pattern with nothing selected: Features mode, its Features field armed. The
        cube picked: a copy at x 25, 2000."""
        self.cube()
        self.runTool("PartDesign_LinearPattern")
        pattern = self.only("PartDesign::LinearPattern")
        self.assertEqual(pattern.TransformMode, "Features")
        self.assertTrue(
            waitFor(lambda: armed(visibleField("fieldOriginals"))), "Features isn't armed"
        )
        Gui.Selection.addSelection(self.doc.Name, self.box.Name)
        self.assertTrue(waitFor(lambda: pattern.Originals == [self.box]), pattern.Originals)
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.assertAlmostEqual(pattern.Shape.Volume, 2000, places=4)

    def testPolarPatternWithNothingSelectedArmsItsFeatures(self):
        self.cube()
        self.runTool("PartDesign_PolarPattern")
        pattern = self.only("PartDesign::PolarPattern")
        self.assertEqual(pattern.TransformMode, "Features")
        self.assertTrue(
            waitFor(lambda: armed(visibleField("fieldOriginals"))), "Features isn't armed"
        )

    def testMirrorOfAFeatureOfAnotherBodyLeavesItOut(self):
        """A feature of another body selected, then Mirror: no message box ("Selection is not in
        the active body"); the mirror opens empty, in Features mode, and says the feature is
        left out."""
        self.cube()
        other = models.body(self.doc)
        otherBox = self.doc.addObject("PartDesign::AdditiveBox", "OtherCube")
        other.addObject(otherBox)
        self.doc.recompute()
        self.activate(self.body)
        self.runTool("PartDesign_Mirrored", otherBox)
        mirror = self.only("PartDesign::Mirrored")
        self.assertEqual(mirror.Originals, [])
        self.assertEqual(mirror.TransformMode, "Features")
        self.assertTrue(self.body.hasObject(mirror))
        self.assertTrue(
            waitFor(
                lambda: any(
                    "left out of the selection: 'OtherCube'" in t for t in notes("fieldOriginals")
                )
            ),
            notes("fieldOriginals"),
        )
