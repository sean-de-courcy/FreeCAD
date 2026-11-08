# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 rank 20)

"""Onshape's New / Add / Remove / Intersect on Revolve (Revolution and Groove), Loft, Sweep (Pipe)
and Helix, as on an Extrude (TestNewPart.TestOperations): every class takes Union, Subtraction and
Common, and its execute honours the Operation.

Designed geometry, each model built by the test (no saved file):
- Base: a 20 x 20 square centred on the Z axis, at z -5, padded 10: the box -10..10 x -10..10 x
  -5..5, 4000.
- Tube: a sketch in the XZ plane (placed, local y along +Z) of the rectangle x 2..5, z 0..10,
  revolved a full turn about its V axis (the Z axis): the tube r 2..5, z 0..10, 210 pi. Its half
  z 0..5 is inside the base: 105 pi. Add: 4000 + 105 pi; Remove: 4000 - 105 pi; Intersect: 105 pi.
- Far tube: the same at z 20..30, which reaches nothing.
- Prism: a 4 x 4 square centred on the axis at z 0, lofted to the same square at z 10, or swept
  along the Z axis 0..10: 160, its half inside the base 80. Add 4080, Remove 3920, Intersect 80.
- Coil: the 2 x 2 square x 2..4, z 0..2 in the XZ plane, a helix about the Z axis of pitch 5 and
  height 5 (one turn): 2 pi r A = 2 pi * 3 * 4 = 24 pi (a screw motion of a meridian profile),
  inside a 20 x 20 x 30 box (z -15..15, 12000). Add: 12000; Remove: 12000 - 24 pi; Intersect: 24 pi.
  The sweep is approximated: its volumes are checked to 0.1 (1.3e-3 of 24 pi).
- Far prism and far coil: the same at z 20..30 and z 20..27, which reach nothing of the 4000 box.
"""

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models

V = App.Vector

# Onshape's info on an Intersect that reaches nothing (hands-on check R7, ops#640 H3)
NO_INTERSECTION = "Selected tools and targets do not intersect"
ALL_OPERATIONS = ["Union", "Subtraction", "Common"]
# The XZ plane, local y along +Z: a sketch's (x, y) is (x, 0, y)
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))

TUBE = 210 * math.pi
TUBE_INSIDE = 105 * math.pi
COIL = 24 * math.pi


def volume(shape):
    """A shape's volume, 0 for the empty shape."""
    return 0 if shape.isNull() else shape.Volume


class TestRevolveOperations(unittest.TestCase):
    def setUp(self):
        self.opened = []
        self.tmp = None
        self.newDoc("TestRevolveOperations")

    def tearDown(self):
        docs = App.listDocuments()
        for name in self.opened:
            if name in docs:
                App.closeDocument(name)
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def newDoc(self, name):
        self.doc = App.newDocument(name)
        self.opened.append(self.doc.Name)
        return self.doc

    def reopen(self, path):
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.opened.append(self.doc.Name)
        return self.doc

    # -- models ---------------------------------------------------------------------------------

    def base(self, height=10):
        """The box -10..10 x -10..10 x -height/2..height/2 (4000 for the default)."""
        self.body = models.body(self.doc)
        sketch = models.sketch(
            self.doc, "BaseSk", models.rectangle(-10, -10, 10, 10), self.body, z=-height / 2
        )
        self.basePad = models.pad(self.body, sketch, height, name="Base")
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 400 * height, places=6)
        return self.body

    def revolve(self, kind, z0=0, z1=10, body=None):
        body = body or self.body
        profile = models.sketch(
            self.doc, kind + "Sk", models.rectangle(2, z0, 5, z1), body, placement=XZ
        )
        feature = body.newObject("PartDesign::" + kind, kind)
        feature.Profile = profile
        feature.ReferenceAxis = (profile, ["V_Axis"])
        feature.Angle = 360
        return feature

    def square(self, name, z):
        return models.sketch(self.doc, name, models.rectangle(-2, -2, 2, 2), self.body, z=z)

    def loft(self, kind="AdditiveLoft", z0=0, z1=10):
        bottom = self.square("LoftBottom", z0)
        top = self.square("LoftTop", z1)
        loft = self.body.newObject("PartDesign::" + kind, kind)
        loft.Profile = bottom
        loft.Sections = [top]
        return loft

    def pipe(self, kind="AdditivePipe", z0=0, z1=10):
        spine = models.sketch(
            self.doc, "Spine", [Part.LineSegment(V(0, z0, 0), V(0, z1, 0))], self.body, placement=XZ
        )
        profile = self.square("PipeProfile", z0)
        pipe = self.body.newObject("PartDesign::" + kind, kind)
        pipe.Profile = profile
        pipe.Spine = (spine, ["Edge1"])
        return pipe

    def helix(self, kind="AdditiveHelix", z0=0):
        profile = models.sketch(
            self.doc, "CoilSk", models.rectangle(2, z0, 4, z0 + 2), self.body, placement=XZ
        )
        helix = self.body.newObject("PartDesign::" + kind, kind)
        helix.Profile = profile
        helix.ReferenceAxis = (profile, ["V_Axis"])
        helix.Mode = 0  # pitch, height, angle
        helix.Pitch = 5
        helix.Height = 5
        helix.Angle = 0
        return helix

    def assertValid(self):
        self.assertEqual(
            [(o.Name, o.getStatusString()) for o in self.doc.Objects if not o.isValid()], []
        )

    def assertOperations(self, feature, expected, delta=1e-4):
        """Each operation in turn: the Body's volume is `expected[operation]`, all valid."""
        for operation in ALL_OPERATIONS:
            feature.Operation = operation
            self.doc.recompute()
            self.assertValid()
            self.assertAlmostEqual(
                self.body.Shape.Volume, expected[operation], delta=delta, msg=operation
            )

    # -- the rows -------------------------------------------------------------------------------

    def testEveryClassTakesEveryOperation(self):
        """Revolution, Groove, the Lofts, Pipes and Helixes list Union, Subtraction and Common,
        and keep their class's default."""
        body = models.body(self.doc)
        for kind, default in (
            ("Revolution", "Union"),
            ("Groove", "Subtraction"),
            ("AdditiveLoft", "Union"),
            ("SubtractiveLoft", "Subtraction"),
            ("AdditivePipe", "Union"),
            ("SubtractivePipe", "Subtraction"),
            ("AdditiveHelix", "Union"),
            ("SubtractiveHelix", "Subtraction"),
        ):
            feature = body.newObject("PartDesign::" + kind, kind)
            self.assertEqual(feature.getEnumerationsOfProperty("Operation"), ALL_OPERATIONS, kind)
            self.assertEqual(feature.Operation, default, kind)

    def testRevolutionTakesEveryOperation(self):
        """The Tube on the Base: Add 4000 + 105 pi, Remove 4000 - 105 pi, Intersect 105 pi."""
        self.base()
        tube = self.revolve("Revolution")
        self.doc.recompute()
        self.assertAlmostEqual(volume(tube.AddSubShape), TUBE, places=4)
        self.assertOperations(
            tube,
            {
                "Union": 4000 + TUBE_INSIDE,
                "Subtraction": 4000 - TUBE_INSIDE,
                "Common": TUBE_INSIDE,
            },
        )

    def testGrooveTakesEveryOperation(self):
        """The Tube as a Groove: the same three volumes (a Groove can add)."""
        self.base()
        tube = self.revolve("Groove")
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 4000 - TUBE_INSIDE, places=4)
        self.assertOperations(
            tube,
            {
                "Union": 4000 + TUBE_INSIDE,
                "Subtraction": 4000 - TUBE_INSIDE,
                "Common": TUBE_INSIDE,
            },
        )

    def testRevolveIntersectThatMissesLeavesTheBase(self):
        """The Far tube (z 20..30) as an Intersect: valid, the Base unchanged (4000), with Onshape's
        info; as a Remove: valid, 4000. A Groove the same."""
        for kind in ("Revolution", "Groove"):
            self.newDoc("TestRevolveOperations" + kind)
            self.base()
            apart = self.revolve(kind, 20, 30)
            apart.Operation = "Common"
            self.doc.recompute()
            self.assertValid()
            self.assertIn(NO_INTERSECTION, apart.getStatusString(), kind)
            self.assertAlmostEqual(self.body.Shape.Volume, 4000, places=6, msg=kind)
            apart.Operation = "Subtraction"
            self.doc.recompute()
            self.assertValid()
            self.assertAlmostEqual(self.body.Shape.Volume, 4000, places=6, msg=kind)

    def testRevolveCutWithNothingBeforeItMakesNothing(self):
        """The Tube as its Body's first solid, set to Remove or Intersect: an empty shape, never
        the 210 pi tool, in error "Nothing to cut"; Union again: the tube, valid."""
        body = models.body(self.doc)
        tube = self.revolve("Revolution", body=body)
        self.doc.recompute()
        self.assertAlmostEqual(volume(body.Shape), TUBE, places=4)
        for operation in ("Subtraction", "Common"):
            tube.Operation = operation
            self.doc.recompute()
            self.assertFalse(tube.isValid(), operation)
            self.assertIn("Nothing to cut", tube.getStatusString(), operation)
            self.assertEqual(volume(tube.Shape), 0, operation)
        tube.Operation = "Union"
        self.doc.recompute()
        self.assertTrue(tube.isValid(), tube.getStatusString())
        self.assertAlmostEqual(volume(body.Shape), TUBE, places=4)

    def testLoftTakesEveryOperation(self):
        """The Prism lofted: Add 4080, Remove 3920, Intersect 80; a Subtractive Loft the same."""
        for kind in ("AdditiveLoft", "SubtractiveLoft"):
            self.newDoc("TestRevolveOperations" + kind)
            self.base()
            loft = self.loft(kind)
            self.assertOperations(loft, {"Union": 4080, "Subtraction": 3920, "Common": 80})

    def testLoftCutWithNothingBeforeItMakesNothing(self):
        """The Prism lofted as its Body's first solid, set to Remove: empty, "Nothing to cut"."""
        self.body = models.body(self.doc)
        loft = self.loft()
        self.doc.recompute()
        self.assertAlmostEqual(volume(loft.Shape), 160, places=4)
        loft.Operation = "Subtraction"
        self.doc.recompute()
        self.assertFalse(loft.isValid())
        self.assertIn("Nothing to cut", loft.getStatusString())
        self.assertEqual(volume(loft.Shape), 0)

    def testPipeTakesEveryOperation(self):
        """The Prism swept along the Z axis: Add 4080, Remove 3920, Intersect 80."""
        for kind in ("AdditivePipe", "SubtractivePipe"):
            self.newDoc("TestRevolveOperations" + kind)
            self.base()
            pipe = self.pipe(kind)
            self.assertOperations(pipe, {"Union": 4080, "Subtraction": 3920, "Common": 80})

    def testHelixTakesEveryOperation(self):
        """The Coil in the 12000 box: Add 12000, Remove 12000 - 24 pi, Intersect 24 pi (the
        sweep is approximated: 0.1)."""
        for kind in ("AdditiveHelix", "SubtractiveHelix"):
            self.newDoc("TestRevolveOperations" + kind)
            self.base(height=30)
            helix = self.helix(kind)
            self.doc.recompute()
            self.assertAlmostEqual(volume(helix.AddSubShape), COIL, delta=0.1, msg=kind)
            self.assertOperations(
                helix,
                {"Union": 12000, "Subtraction": 12000 - COIL, "Common": COIL},
                delta=0.1,
            )

    def testLoftPipeHelixIntersectThatMissesLeavesTheBase(self):
        """The Far prism lofted or swept, and the Far coil, as an Intersect: valid, the Base
        unchanged (4000), with Onshape's info, as a Revolve's and an Extrude's."""
        for kind, make in (
            ("AdditiveLoft", lambda: self.loft(z0=20, z1=30)),
            ("AdditivePipe", lambda: self.pipe(z0=20, z1=30)),
            ("AdditiveHelix", lambda: self.helix(z0=20)),
        ):
            self.newDoc("TestRevolveOperationsFar" + kind)
            self.base()
            apart = make()
            apart.Operation = "Common"
            self.doc.recompute()
            self.assertValid()
            self.assertIn(NO_INTERSECTION, apart.getStatusString(), kind)
            self.assertAlmostEqual(self.body.Shape.Volume, 4000, places=6, msg=kind)

    def testHelixIntersectKeepsItsOperationOnReopen(self):
        """An Additive Helix set straight to Intersect: its deprecated Outside follows, so the
        reopened file is still an Intersect (the restore takes the Operation from Outside), 24 pi;
        set back to Remove, Outside goes off."""
        self.base(height=30)
        helix = self.helix()
        helix.Operation = "Common"
        self.doc.recompute()
        self.assertTrue(helix.Outside)
        self.tmp = tempfile.mkdtemp()
        path = os.path.join(self.tmp, "helix.FCStd")
        self.doc.saveAs(path)
        self.reopen(path)
        helix = self.doc.getObject("AdditiveHelix")
        self.assertEqual(helix.Operation, "Common")
        self.assertEqual(helix.getEnumerationsOfProperty("Operation"), ALL_OPERATIONS)
        self.doc.recompute()
        self.body = helix.getParentGeoFeatureGroup()
        self.assertAlmostEqual(self.body.Shape.Volume, COIL, delta=0.1)
        helix.Operation = "Subtraction"
        self.assertFalse(helix.Outside)

    def testRevolutionRemoveKeepsItsOperationOnReopen(self):
        """A Revolution saved as a Remove reopens as one, listing all three, 4000 - 105 pi."""
        self.base()
        tube = self.revolve("Revolution")
        tube.Operation = "Subtraction"
        self.doc.recompute()
        self.tmp = tempfile.mkdtemp()
        path = os.path.join(self.tmp, "revolve.FCStd")
        self.doc.saveAs(path)
        self.reopen(path)
        tube = self.doc.getObject("Revolution")
        self.assertEqual(tube.Operation, "Subtraction")
        self.assertEqual(tube.getEnumerationsOfProperty("Operation"), ALL_OPERATIONS)
        tube.touch()
        self.doc.recompute()
        body = tube.getParentGeoFeatureGroup()
        self.assertAlmostEqual(body.Shape.Volume, 4000 - TUBE_INSIDE, places=4)
