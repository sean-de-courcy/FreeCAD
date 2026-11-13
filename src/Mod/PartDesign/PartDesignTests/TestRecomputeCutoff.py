# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640): the recompute cut-off (notes/recompute-cutoff.md in the ops repo).
#
# A feature that ran and reads the same as after its last run doesn't make its dependants run.
# The model is designed: a 40 x 40 block padded to `length`, then N unattached additive boxes of
# 2 x 2 x 2 at (39, 4 i, 0), each half inside the block, so the solid's volume is
# 1600 * length + 4 * N (each box adds the 1 x 2 x 2 that sticks out), one solid for length >= 2.
# What ran is counted by a document observer's slotRecomputedObject.

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models

V = App.Vector
N = 6
PARAMETERS = "User parameter:BaseApp/Preferences/Document"


class Ran:
    """The names of the objects a recompute ran (or passed as touched), in order."""

    def __init__(self):
        self.names = []

    def slotRecomputedObject(self, obj):
        self.names.append(obj.Name)


class Proxy:
    """A Python feature: a 5 mm cube."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        obj.Shape = Part.makeBox(5, 5, 5)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class TestRecomputeCutoff(unittest.TestCase):
    def setUp(self):
        self.parameters = App.ParamGet(PARAMETERS)
        self.wasOn = self.parameters.GetBool("RecomputeCutOff", True)
        self.parameters.SetBool("RecomputeCutOff", True)
        self.doc = models.newDocument("RecomputeCutoff")
        self.doc.UndoMode = 1
        self.body = models.body(self.doc)
        self.sketch = models.sketch(
            self.doc, "BlockSketch", models.rectangle(0, 0, 40, 40), self.body
        )
        self.pad = models.pad(self.body, self.sketch, 10, "Block")
        self.boxes = []
        for i in range(N):
            box = self.body.newObject("PartDesign::AdditiveBox", f"Box{i}")
            box.Length, box.Width, box.Height = 2, 2, 2
            box.Placement = App.Placement(V(39, 4 * i, 0), App.Rotation())
            self.boxes.append(box)
        self.doc.recompute()
        for obj in [self.sketch, self.pad, self.body] + self.boxes:
            self.assertTrue(obj.isValid(), obj.Name)
        self.assertVolume(10)
        self.folder = None

    def tearDown(self):
        self.parameters.SetBool("RecomputeCutOff", self.wasOn)
        for name in list(App.listDocuments()):
            if name.startswith("RecomputeCutoff"):
                App.closeDocument(name)
        if self.folder:
            shutil.rmtree(self.folder, ignore_errors=True)

    # -- helpers ---------------------------------------------------------------------------------

    def recompute(self, doc=None):
        """Recomputes; the set of the names that ran."""
        ran = Ran()
        App.addDocumentObserver(ran)
        try:
            (doc or self.doc).recompute()
        finally:
            App.removeDocumentObserver(ran)
        return set(ran.names)

    def assertVolume(self, length, extra=4 * N, body=None):
        self.assertAlmostEqual(
            (body or self.body).Shape.Volume, 1600 * length + extra, delta=1e-6
        )

    def assertAllRan(self, ran):
        for box in self.boxes:
            self.assertIn(box.Name, ran)
        self.assertIn(self.body.Name, ran)

    # -- the cut-off -----------------------------------------------------------------------------

    def testTouchedPadStopsAtThePad(self):
        """The first pad touched, nothing changed: it runs, nothing after it does."""
        self.pad.touch()
        self.assertEqual(self.recompute(), {self.pad.Name})
        self.assertVolume(10)
        self.assertFalse(any("Touched" in o.State for o in self.doc.Objects))

    def testTouchedSketchStopsAtTheSketch(self):
        """A sketch that re-solves to the same curves stops there: the pad doesn't run."""
        self.sketch.touch()
        self.assertEqual(self.recompute(), {self.sketch.Name})

    def testLengthThereAndBackStopsAtThePad(self):
        """Two edits that leave the value as it was, with no recompute between them."""
        self.pad.Length = 12
        self.pad.Length = 10
        self.assertEqual(self.recompute(), {self.pad.Name})
        self.assertVolume(10)

    def testShownOrHiddenPadStopsToo(self):
        """A dialog shows the feature it edits: Visibility is not part of what is compared."""
        self.pad.Visibility = not self.pad.Visibility
        self.pad.touch()
        self.assertEqual(self.recompute(), {self.pad.Name})

    def testSecondNoOpStopsToo(self):
        """The state kept at a cut-off serves the next one."""
        self.pad.touch()
        self.recompute()
        self.pad.touch()
        self.assertEqual(self.recompute(), {self.pad.Name})

    # -- what must still run ---------------------------------------------------------------------

    def testRealEditRunsEverything(self):
        self.pad.Length = 12
        self.assertAllRan(self.recompute())
        self.assertVolume(12)
        # ... and back, with a recompute between: a real edit again
        self.pad.Length = 10
        self.assertAllRan(self.recompute())
        self.assertVolume(10)

    def testMovedPadRunsEverything(self):
        """Same shape, another place: the Placement is part of what dependants read. The boxes
        at x = 39..41 then lie inside the block (x = 1..41), which adds 2 * 2 * 1 less each."""
        self.sketch.Placement = App.Placement(V(1, 0, 0), App.Rotation())
        ran = self.recompute()
        self.assertAllRan(ran)
        self.assertVolume(10, extra=0)

    def testInputWithoutShapeEffectReachesItsReader(self):
        """Length2 changes nothing of a pad of type Length, but an expression reads it: the
        reader runs and takes the value (a shape-only identity would cut it off)."""
        self.boxes[0].setExpression("Height", f"{self.pad.Name}.Length2")
        self.pad.Length2 = 2
        self.recompute()
        self.assertAlmostEqual(self.boxes[0].Height.Value, 2)
        self.pad.Length2 = 3
        ran = self.recompute()
        self.assertIn(self.boxes[0].Name, ran)
        self.assertAlmostEqual(self.boxes[0].Height.Value, 3)
        # Box0 sticks out 1 x 2 x 3 now
        self.assertVolume(10, extra=4 * (N - 1) + 6)

    def testMultiTransformReadsItsStepsCount(self):
        """A MultiTransform's step has no shape of its own: its Occurrences are read through a
        plain link. Two more holes must appear when the count goes from 2 to 4."""
        hole = self.body.newObject("PartDesign::SubtractiveBox", "Notch")
        hole.Length, hole.Width, hole.Height = 2, 2, 2
        hole.Placement = App.Placement(V(10, 30, 9), App.Rotation())  # 2 x 2 x 1 inside the top
        multi = self.doc.addObject("PartDesign::MultiTransform", "NotchMulti")
        multi.Originals = [hole]
        multi.Refine = False
        self.body.addObject(multi)
        step = self.doc.addObject("PartDesign::LinearPattern", "NotchStep")
        step.Direction = (models.originFeature(self.body, "X_Axis"), [""])
        step.Mode = "Spacing"
        step.Offset = 5
        step.Occurrences = 2
        self.body.addObject(step)
        multi.Transformations = [step]
        self.recompute()
        self.assertTrue(multi.isValid())
        self.assertVolume(10, extra=4 * N - 2 * 4)
        step.Occurrences = 4
        ran = self.recompute()
        self.assertIn(multi.Name, ran)
        self.assertVolume(10, extra=4 * N - 4 * 4)

    def testUndoVoidsTheKeptState(self):
        """12, recompute, undo (everything is back at 10 without a run), 12 again: the pad's
        result equals the one kept before the undo, and the boxes must run all the same."""
        self.doc.openTransaction("length")
        self.pad.Length = 12
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertVolume(12)
        self.doc.undo()
        self.doc.recompute()
        self.assertVolume(10)
        self.pad.Length = 12
        self.recompute()
        self.assertVolume(12)

    def testFeatureRecomputeAloneHidesNoEdit(self):
        """A dialog recomputes its feature alone (it enforces nobody), then the document: the
        edit reaches the features after it."""
        self.pad.Length = 12
        self.pad.recompute()
        ran = self.recompute()
        self.assertAllRan(ran)
        self.assertVolume(12)

    def testFailureAndRepairRunTheDependants(self):
        """In error and repaired to the value it had: the dependants that failed naming it run."""
        self.pad.setExpression("Length", "Block.NoSuchProperty")
        self.recompute()
        self.assertFalse(self.pad.isValid())
        self.pad.setExpression("Length", None)
        self.pad.Length = 10
        ran = self.recompute()
        self.assertAllRan(ran)
        for box in self.boxes:
            self.assertTrue(box.isValid(), box.Name)
        self.assertVolume(10)

    def testContainerNeverCutsOff(self):
        """A reader of the Body runs whenever the Body does: readers reach a container's members
        through it."""
        mirror = self.doc.addObject("Part::Mirroring", "Mirror")
        mirror.Source = self.body
        mirror.Normal = V(1, 0, 0)
        self.recompute()
        self.body.touch()
        self.assertIn(mirror.Name, self.recompute())

    def testPythonFeatureNeverCutsOff(self):
        """A Python feature's state isn't in its properties: its dependant always runs. A
        Python feature that is the dependant is cut off like any other."""
        cube = self.doc.addObject("Part::FeaturePython", "Cube")
        Proxy(cube)
        mirror = self.doc.addObject("Part::Mirroring", "CubeMirror")
        mirror.Source = cube
        mirror.Normal = V(1, 0, 0)
        self.recompute()
        cube.touch()
        self.assertEqual(self.recompute(), {cube.Name, mirror.Name})

    def testOffByParameter(self):
        self.parameters.SetBool("RecomputeCutOff", False)
        self.pad.touch()
        self.assertAllRan(self.recompute())

    # -- after opening ---------------------------------------------------------------------------

    def testFirstRunAfterOpenRunsEverythingOnce(self):
        """No state is saved: the first run of a feature after opening enforces its dependants
        (the step after this one changes that, and this test with it); the second is cut off."""
        self.folder = tempfile.mkdtemp(prefix="RecomputeCutoff")
        path = os.path.join(self.folder, "RecomputeCutoffSaved.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        doc = App.openDocument(path)
        pad = doc.getObject(self.pad.Name)
        body = doc.getObject(self.body.Name)
        self.assertEqual(self.recompute(doc), set())
        pad.touch()
        ran = self.recompute(doc)
        self.assertIn(self.boxes[0].Name, ran)
        self.assertVolume(10, body=body)
        pad.touch()
        self.assertEqual(self.recompute(doc), {pad.Name})
        self.assertVolume(10, body=body)
        App.closeDocument(doc.Name)
        self.boxes = []
