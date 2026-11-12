# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: fillet tangent propagation off, as Onshape's (ops#655, notes/loft-options.md, oracle fact GB13).
#
# Designed geometry: a slot (lines y = +-5 from x -10..10, half-circle ends r5) padded 10. Onshape's results are
# closed forms: propagation off runs the fillet straight on past the tangent vertices and cuts both round ends
# until it leaves the body: removed = 20 (4 - pi) + 2 * integral of sqrt(25 - y^2) over the corner region
# (y 3..5, z 8..10 outside the r2 circle about (3, 8)) = 20.338.

import math
import unittest

import FreeCAD
import Part

from PartDesignTests.Scenarios import models

App = FreeCAD
V = App.Vector
SLOT = 10 * (20 * 10 + math.pi * 25)  # 2785.398


def slot():
    return [
        Part.LineSegment(V(-10, 5, 0), V(10, 5, 0)),
        Part.ArcOfCircle(Part.Circle(V(10, 0, 0), V(0, 0, 1), 5), -math.pi / 2, math.pi / 2),
        Part.LineSegment(V(10, -5, 0), V(-10, -5, 0)),
        Part.ArcOfCircle(Part.Circle(V(-10, 0, 0), V(0, 0, 1), 5), math.pi / 2, 3 * math.pi / 2),
    ]


class TestFilletPropagation(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PartDesignTestFilletPropagation")
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def slotPad(self):
        sketch = models.sketch(self.doc, "Slot", slot(), self.body)
        pad = models.pad(self.body, sketch, 10)
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, SLOT, delta=1e-3)
        return pad

    def edgeName(self, shape, test):
        names = [
            "Edge%d" % (i + 1)
            for i, edge in enumerate(shape.Edges)
            if test(edge)
        ]
        self.assertEqual(len(names), 1, names)
        return names[0]

    def topLine(self, shape, y=5):
        """The top edge of the y = 5 side."""

        def test(edge):
            box = edge.BoundBox
            return (
                isinstance(edge.Curve, Part.Line)
                and abs(box.ZMin - 10) < 1e-6
                and abs(box.ZMax - 10) < 1e-6
                and abs(box.YMin - y) < 1e-6
                and abs(box.YMax - y) < 1e-6
            )

        return self.edgeName(shape, test)

    def fillet(self, base, edges, radius=2.0, **properties):
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (base, edges)
        fillet.Radius = radius
        for name, value in properties.items():
            setattr(fillet, name, value)
        self.doc.recompute()
        return fillet

    def assertResult(self, feature, volume, faces, delta=0.002):
        self.assertTrue(feature.isValid(), feature.getStatusString())
        shape = feature.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume, delta=delta)
        self.assertEqual(len(shape.Faces), faces)

    def testPropagationIsOnByDefault(self):
        pad = self.slotPad()
        fillet = self.fillet(pad, [self.topLine(pad.Shape)])
        self.assertTrue(fillet.TangentPropagation)
        # GB13: the whole tangent top loop, V 2726.504, 10 faces
        self.assertResult(fillet, 2726.504, 10)

    def testOffRunsStraightOnThroughTheRoundEnds(self):
        pad = self.slotPad()
        fillet = self.fillet(pad, [self.topLine(pad.Shape)], TangentPropagation=False)
        # GB13: 1 fillet face, V 2765.061, 7 faces, no error
        self.assertResult(fillet, 2765.061, 7)
        cylinders = [f for f in fillet.Shape.Faces if isinstance(f.Surface, Part.Cylinder)]
        spans = [f for f in cylinders if abs(f.Surface.Radius - 2) < 1e-6]
        self.assertEqual(len(spans), 1)
        box = spans[0].BoundBox
        self.assertAlmostEqual(box.XMin, -14, delta=1e-3)
        self.assertAlmostEqual(box.XMax, 14, delta=1e-3)
        self.assertAlmostEqual(box.YMin, 3, delta=1e-6)
        self.assertAlmostEqual(box.YMax, 5, delta=1e-6)

    def testOffOnBothLinesCutsBothSides(self):
        pad = self.slotPad()
        edges = [self.topLine(pad.Shape, 5), self.topLine(pad.Shape, -5)]
        fillet = self.fillet(pad, edges, TangentPropagation=False)
        self.assertResult(fillet, SLOT - 2 * 20.338046, 8)

    def testOffWithoutATangentNeighbourIsTheUsualFillet(self):
        """A box edge has no tangent continuation: off and on are the same fillet."""
        sketch = models.sketch(self.doc, "Square", models.rectangle(0, 0, 10, 10), self.body)
        pad = models.pad(self.body, sketch, 10)
        self.doc.recompute()

        def test(edge):
            box = edge.BoundBox
            return box.ZMin > 9.999 and box.YMax < 1e-6

        fillet = self.fillet(pad, [self.edgeName(pad.Shape, test)], TangentPropagation=False)
        self.assertResult(fillet, 1000 - 10 * 4 * (1 - math.pi / 4), 7)

    def testOffOnAWholeLoopIsTheUsualFillet(self):
        """Every edge of the tangent loop picked: nothing is left to stop at, as with propagation on."""
        pad = self.slotPad()
        shape = pad.Shape
        loop = [
            "Edge%d" % (i + 1)
            for i, edge in enumerate(shape.Edges)
            if edge.BoundBox.ZMin > 9.999
        ]
        self.assertEqual(len(loop), 4)
        fillet = self.fillet(pad, loop, TangentPropagation=False)
        self.assertResult(fillet, 2726.504, 10)

    def testOffOnACurvedEdgeWithATangentNeighbourStops(self):
        pad = self.slotPad()

        def test(edge):
            return isinstance(edge.Curve, Part.Circle) and edge.BoundBox.ZMin > 9.999 and edge.BoundBox.XMin > 0

        fillet = self.fillet(pad, [self.edgeName(pad.Shape, test)], TangentPropagation=False)
        self.assertFalse(fillet.isValid(), "expected a stop")
        self.assertIn("tangent", fillet.getStatusString().lower())


if __name__ == "__main__":
    unittest.main()
