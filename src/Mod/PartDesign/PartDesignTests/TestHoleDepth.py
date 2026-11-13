# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: Onshape's hole terminations and start (ops#640, rank 23).

"""A Hole ends Blind (DepthType "Dimension"), Through all, Up to next ("UpToFirst") or Up to
entity ("UpToFace", the UpToFace link), and a new hole starts from the part (StartType "Part"),
Onshape's default. The two new terminations and the start type are appended to their lists, so a
saved file's indices read the same.

Designed geometry: a 10 mm box (0..10) in a body; a sketch on the XY plane, reversed, with a
circle of radius 1 at (5, 5) (TestHole's), so the hole runs up +z from z = 0. A flat-bottomed
hole of diameter 2 removes pi * depth."""

import math
import unittest

import FreeCAD
import TestSketcherApp

App = FreeCAD
V = App.Vector

TOL = 1e-6


class TestHoleDepth(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("PartDesignTestHoleDepth")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        self.box.Length = self.box.Width = self.box.Height = 10
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def hole(self):
        sketch = self.body.newObject("Sketcher::SketchObject", "HoleSketch")
        [xy] = [f for f in self.body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        sketch.AttachmentSupport = (xy, [""])
        sketch.MapMode = "FlatFace"
        sketch.MapReversed = True
        TestSketcherApp.CreateCircleSketch(sketch, (-5, 5), 1)
        self.doc.recompute()
        hole = self.body.newObject("PartDesign::Hole", "Hole")
        hole.Profile = sketch
        hole.ThreadType = 0
        hole.HoleCutType = 0
        hole.Diameter = 2
        hole.DrillPoint = "Flat"
        hole.Tapered = False
        return hole

    def tool(self, hole):
        """The hole's tool (AddSubShape) in the body's frame: the property holds it in the
        hole's own frame, which is its base feature's Placement (positionByPrevious)."""
        shape = hole.AddSubShape.copy()
        shape.Placement = hole.Placement.multiply(shape.Placement)
        return shape.BoundBox

    def removed(self, hole, before):
        self.assertTrue(hole.isValid(), hole.getStatusString())
        return before - hole.Shape.Volume

    def testListsAppended(self):
        """The old indices read the same: 0 Blind, 1 Through all; 0..2 the profile-based starts."""
        hole = self.hole()
        self.assertEqual(
            hole.getEnumerationsOfProperty("DepthType"),
            ["Dimension", "ThroughAll", "UpToFirst", "UpToFace"],
        )
        self.assertEqual(
            hole.getEnumerationsOfProperty("StartType"),
            ["Profile plane", "Offset", "Reference", "Part"],
        )
        hole.DepthType = 1
        self.assertEqual(hole.DepthType, "ThroughAll")

    def testNewHoleStartsFromThePart(self):
        """A new hole's start is "Part"; with the sketch on the part's face it cuts as before."""
        hole = self.hole()
        self.assertEqual(hole.StartType, "Part")
        hole.Depth = 4
        self.doc.recompute()
        self.assertAlmostEqual(self.removed(hole, 1000), math.pi * 4, delta=TOL)

    def testStartFromPartBelowTheSketch(self):
        """The box raised to 3..13, the sketch still at z = 0: from the part a 4 mm blind hole
        runs 3..7; from the profile plane it runs 0..4 and cuts 1 mm of the box."""
        self.box.Placement = App.Placement(V(0, 0, 3), App.Rotation())
        hole = self.hole()
        hole.Depth = 4
        self.doc.recompute()
        self.assertAlmostEqual(self.removed(hole, 1000), math.pi * 4, delta=TOL)
        self.assertAlmostEqual(self.tool(hole).ZMin, 3, delta=TOL)
        self.assertAlmostEqual(self.tool(hole).ZMax, 7, delta=TOL)
        hole.StartType = "Profile plane"
        self.doc.recompute()
        self.assertAlmostEqual(self.removed(hole, 1000), math.pi * 1, delta=TOL)

    def testStartFromPartInsideThePart(self):
        """The box lowered to -5..5, the sketch at z = 0 inside it: the hole starts at the plane, a
        4 mm blind hole runs 0..4 (not from the face behind the plane, -5..-1)."""
        self.box.Placement = App.Placement(V(0, 0, -5), App.Rotation())
        hole = self.hole()
        hole.Depth = 4
        self.doc.recompute()
        self.assertAlmostEqual(self.removed(hole, 1000), math.pi * 4, delta=TOL)
        self.assertAlmostEqual(self.tool(hole).ZMin, 0, delta=TOL)
        self.assertAlmostEqual(self.tool(hole).ZMax, 4, delta=TOL)

    def testStartFromPartNeverBehindThePlane(self):
        """The hole Reversed: from the sketch on the box's bottom face it runs down, away from the
        box. It starts at the plane, not at the box's top face behind it, so it cuts nothing of
        the box (valid or not, the box keeps 1000)."""
        hole = self.hole()
        hole.Reversed = True
        hole.Depth = 4
        self.doc.recompute()
        if not hole.isValid():
            return
        self.assertAlmostEqual(hole.Shape.Volume, 1000, delta=TOL)
        # the tool runs -4..0, below the box
        self.assertAlmostEqual(self.tool(hole).ZMax, 0, delta=TOL)
        self.assertAlmostEqual(self.tool(hole).ZMin, -4, delta=TOL)

    def slot(self):
        """A slot through the box along x, y 3..7, z 3..6: the hole's axis crosses material 0..3,
        air 3..6, material 6..10. The box keeps one solid (y 0..3 and 7..10 join it)."""
        slot = self.body.newObject("PartDesign::SubtractiveBox", "Slot")
        slot.Length, slot.Width, slot.Height = 10, 4, 3
        slot.Placement = App.Placement(V(0, 3, 3), App.Rotation())
        self.doc.recompute()
        self.assertTrue(slot.isValid(), slot.getStatusString())
        self.assertAlmostEqual(slot.Shape.Volume, 1000 - 120, delta=TOL)
        return slot

    def testUpToNextEndsWhereTheMaterialEnds(self):
        """Up to next stops at the slot's floor (3), where Through all goes on to 10."""
        self.slot()
        hole = self.hole()
        hole.DepthType = "UpToFirst"
        self.doc.recompute()
        self.assertAlmostEqual(self.removed(hole, 880), math.pi * 3, delta=TOL)
        hole.DepthType = "ThroughAll"
        self.doc.recompute()
        self.assertAlmostEqual(self.removed(hole, 880), math.pi * 7, delta=TOL)

    def testUpToNextFromAboveThePart(self):
        """The box raised to 3..13: up to next from the profile plane goes through the air below
        the part and ends where the box's material ends, at 13."""
        self.box.Placement = App.Placement(V(0, 0, 3), App.Rotation())
        hole = self.hole()
        hole.StartType = "Profile plane"
        hole.DepthType = "UpToFirst"
        self.doc.recompute()
        self.assertAlmostEqual(self.removed(hole, 1000), math.pi * 10, delta=TOL)

    def testUpToEntityPlane(self):
        """Up to a datum plane at z = 7: the hole runs 0..7."""
        plane = self.body.newObject("PartDesign::Plane", "Stop")
        plane.MapMode = "Deactivated"
        plane.Placement = App.Placement(V(0, 0, 7), App.Rotation())
        hole = self.hole()
        hole.DepthType = "UpToFace"
        hole.UpToFace = (plane, [""])
        self.doc.recompute()
        self.assertAlmostEqual(self.removed(hole, 1000), math.pi * 7, delta=TOL)
        self.assertAlmostEqual(self.tool(hole).ZMax, 7, delta=TOL)

    def testUpToEntityFace(self):
        """Up to the slot's ceiling (z = 6), a face of the solid before."""
        slot = self.slot()
        ceiling = None
        for i, f in enumerate(slot.Shape.Faces, 1):
            c = f.CenterOfMass
            if abs(c.z - 6) < TOL and abs(f.normalAt(0, 0).z + 1) < TOL:
                ceiling = f"Face{i}"
        self.assertIsNotNone(ceiling)
        hole = self.hole()
        hole.DepthType = "UpToFace"
        hole.UpToFace = (slot, [ceiling])
        self.doc.recompute()
        # 0..6: material 0..3, the slot's air 3..6
        self.assertAlmostEqual(self.removed(hole, 880), math.pi * 3, delta=TOL)
        self.assertAlmostEqual(self.tool(hole).ZMax, 6, delta=TOL)

    def testUpToEntityNeedsOne(self):
        """Up to entity with nothing picked: red, with the message."""
        hole = self.hole()
        hole.DepthType = "UpToFace"
        self.doc.recompute()
        self.assertFalse(hole.isValid())
        self.assertIn("Select the face or plane the hole goes up to.", hole.getStatusString())


if __name__ == "__main__":
    unittest.main()
