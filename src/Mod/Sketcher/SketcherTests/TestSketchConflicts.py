# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, decision 365 lane 1): a sketch with a conflict behaves as Onshape's.
# Onshape keeps the conflicting constraint, leaves the constraints of the conflict out, solves
# the rest, and the sketch is a warning (SKETCH_SOLVE_FAILED) the features after it still build
# from (Onshape facts SK7, SK7b, SK8, SK8b, PL1d in notes/onshape-facts.md). Designed geometry:
# a rectangle drawn 20 x 10 at the origin, its expected shape defined by the constraints.

import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector


def _rectangle(sketch, width=20.0, height=10.0, frame=True):
    """Four lines (bottom, right, top, left) joined at the corners; with frame, Horizontal on
    bottom and top and Vertical on both sides. Returns the line ids."""
    corners = [V(0, 0, 0), V(width, 0, 0), V(width, height, 0), V(0, height, 0)]
    ids = [
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]), False)
        for i in range(4)
    ]
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", ids[i], 2, ids[(i + 1) % 4], 1))
    if frame:
        sketch.addConstraint(Sketcher.Constraint("Horizontal", ids[0]))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", ids[2]))
        sketch.addConstraint(Sketcher.Constraint("Vertical", ids[1]))
        sketch.addConstraint(Sketcher.Constraint("Vertical", ids[3]))
    return ids


def _length(sketch, geo):
    return sketch.Geometry[geo].length()


class TestSketchConflicts(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SketchConflicts")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.sk = self.body.newObject("Sketcher::SketchObject", "Sketch")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _pad(self, length=10.0):
        pad = self.body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.sk
        pad.Length = length
        self.doc.recompute()
        return pad

    def _sk7b(self):
        """Onshape SK7b: two lengths on the bottom line off the drawing (25 and 30) and a 15 on
        the right side. Returns (line ids, index of the right side's length)."""
        ids = _rectangle(self.sk)
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[0], 25.0))
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[0], 30.0))
        side = self.sk.addConstraint(Sketcher.Constraint("Distance", ids[1], 15.0))
        return ids, side

    def testConflictSolvesTheRest(self):
        # SK7b: the conflicting pair is left out (the bottom stays at its drawn 20), the side's 15
        # is applied, and the sketch is a warning, not an error
        ids, _ = self._sk7b()
        self.doc.recompute()
        sk = self.sk
        self.assertTrue(sk.ConflictingConstraints)
        self.assertNotIn("Invalid", sk.State)
        self.assertIn("Warning", sk.State)
        self.assertTrue(sk.isValid())
        self.assertAlmostEqual(_length(sk, ids[0]), 20.0, places=6)
        self.assertAlmostEqual(_length(sk, ids[1]), 15.0, places=6)
        self.assertEqual(len(sk.Constraints), 11)  # nothing removed
        self.assertAlmostEqual(sk.Shape.Wires[0].Length, 70.0, places=6)

    def testConflictListNamesTheConflictingPair(self):
        self._sk7b()
        self.doc.recompute()
        # constraints 9 and 10 (1-based) are the two lengths on the bottom line
        self.assertIn(9, self.sk.ConflictingConstraints)
        self.assertIn(10, self.sk.ConflictingConstraints)

    def testPythonSolveStillReportsTheConflict(self):
        ids, _ = self._sk7b()
        self.assertIn(self.sk.solve(), (-3, -4))
        # but the rest is solved and written
        self.assertAlmostEqual(_length(self.sk, ids[1]), 15.0, places=6)

    def testPadAfterAConflictBuilds(self):
        self._sk7b()
        pad = self._pad()
        self.assertTrue(pad.isValid(), pad.State)
        self.assertNotIn("Invalid", pad.State)
        self.assertAlmostEqual(pad.Shape.Volume, 20.0 * 15.0 * 10.0, places=4)

    def testPreExistingConflictNoLongerFailsTheRecompute(self):
        # a healthy sketch padded, then a conflict added: the next recompute goes on
        ids = _rectangle(self.sk)
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[1], 10.0))
        pad = self._pad()
        self.assertAlmostEqual(pad.Shape.Volume, 2000.0, places=4)
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[1], 12.0))
        self.doc.recompute()
        self.assertTrue(self.sk.isValid(), self.sk.State)
        self.assertTrue(pad.isValid(), pad.State)
        self.assertAlmostEqual(pad.Shape.Volume, 2000.0, places=4)  # both side lengths left out

    def testGeometricConflictIsKeptAndTheNewestLeftOut(self):
        # PL1d: a Vertical on the bottom line of a framed rectangle; the constraint stays, the
        # rectangle keeps its shape (the newest constraint of the conflict is left out)
        ids = _rectangle(self.sk)
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[0], 20.0))
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[1], 10.0))
        vertical = self.sk.addConstraint(Sketcher.Constraint("Vertical", ids[0]))
        pad = self._pad()
        self.assertIn(vertical + 1, self.sk.ConflictingConstraints)
        self.assertEqual(len(self.sk.Constraints), vertical + 1)
        self.assertTrue(self.sk.isValid(), self.sk.State)
        self.assertAlmostEqual(_length(self.sk, ids[0]), 20.0, places=6)
        self.assertAlmostEqual(self.sk.Geometry[ids[0]].StartPoint.y,
                               self.sk.Geometry[ids[0]].EndPoint.y, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 2000.0, places=4)

    def testConsistentRepeatIsAcceptedWithoutWarning(self):
        # SK8 (consistent): accepted silently, as ops#656 made it
        ids = _rectangle(self.sk)
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[0], 20.0))
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[2], 20.0))
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[1], 10.0))
        self.doc.recompute()
        self.assertEqual(self.sk.solve(), 0)
        self.assertTrue(self.sk.RedundantConstraints)
        self.assertNotIn("Warning", self.sk.State)
        self.assertTrue(self.sk.isValid())

    def testContradictingRepeatSolvesTheRest(self):
        # SK8b: bottom 25 and top 20 on a rectangle drawn 20 x 10: a warning, the width stays as
        # drawn (both lengths left out), the side's 12 is applied
        ids = _rectangle(self.sk)
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[0], 25.0))
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[2], 20.0))
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[1], 12.0))
        pad = self._pad()
        self.assertIn("Warning", self.sk.State)
        self.assertTrue(self.sk.isValid(), self.sk.State)
        self.assertTrue(self.sk.ConflictingConstraints or self.sk.RedundantConstraints)
        self.assertAlmostEqual(_length(self.sk, ids[0]), 20.0, places=6)
        self.assertAlmostEqual(_length(self.sk, ids[1]), 12.0, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 20.0 * 12.0 * 10.0, places=4)

    def testMalformedStillFails(self):
        ids = _rectangle(self.sk)
        point = self.sk.addGeometry(Part.Point(V(3, 3, 0)), False)
        self.sk.addConstraint(Sketcher.Constraint("Midpoint", point, 1, ids[0]))
        self.doc.recompute()
        self.assertTrue(self.sk.MalformedConstraints)
        self.assertFalse(self.sk.isValid())

    def testDatumOfAConflictingSketchCanBeSet(self):
        # Onshape keeps a typed value; the conflict does not block editing the rest
        ids, side = self._sk7b()
        self.doc.recompute()
        self.sk.setDatum(side, App.Units.Quantity("12 mm"))
        self.doc.recompute()
        self.assertAlmostEqual(_length(self.sk, ids[1]), 12.0, places=6)
        self.assertTrue(self.sk.isValid(), self.sk.State)

    def testRemovingTheConflictClearsTheWarning(self):
        self._sk7b()
        self.doc.recompute()
        self.sk.delConstraint(9)  # the 30 on the bottom line (0-based)
        self.doc.recompute()
        self.assertFalse(self.sk.ConflictingConstraints)
        self.assertNotIn("Warning", self.sk.State)
        self.assertAlmostEqual(_length(self.sk, 0), 25.0, places=6)

    def testDragMovesAConflictingSketch(self):
        # the conflict stays left out while a point is moved: the free width follows the drag
        ids = _rectangle(self.sk)
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[1], 10.0))
        self.sk.addConstraint(Sketcher.Constraint("Distance", ids[1], 12.0))
        self.doc.recompute()
        self.sk.moveGeometry(ids[1], 1, V(30, 0, 0), False)  # the bottom-right corner
        self.assertAlmostEqual(self.sk.Geometry[ids[1]].StartPoint.x, 30.0, places=4)
        self.assertAlmostEqual(_length(self.sk, ids[1]), 10.0, places=6)  # drawn height kept

    def testSavedConflictReopensTheSame(self):
        import os
        import tempfile

        self._sk7b()
        pad = self._pad()
        path = os.path.join(tempfile.mkdtemp(), "conflict.FCStd")
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = App.openDocument(path)
        self.doc.recompute()
        pad = self.doc.getObject("Pad")
        sk = self.doc.getObject("Sketch")
        self.assertTrue(sk.isValid(), sk.State)
        self.assertAlmostEqual(pad.Shape.Volume, 3000.0, places=4)
