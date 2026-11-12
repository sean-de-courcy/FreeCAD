# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: a fillet's or chamfer's failure as Onshape's (ops#640, design F slice F2, notes/fillet-gaps-design.md;
# oracle facts O2 and FC1 in notes/onshape-facts.md).
#
# Onshape fails a fillet with one message, "Failed to fillet selections", and never shows the kernel's own text. A
# fillet over two parts whose edge on one part fails warns and builds the other (O2): per part, not all or nothing.
# In FreeCAD-CH a dress-up over two parts is one feature in each part's Body (the command makes the second with its
# size following the first), so a failing part's feature passes its base through and the other part builds.
#
# Designed geometry (O2's): part A a 100 cube, part B a 20 x 20 x 10 box at x 120..140, each a Pad in its own Body;
# the picked edge of each is its top front edge (y 0, z top). Fillet r 50: A loses the round's section along the
# 100 mm edge, (1 - pi/4) 50^2 100 = 53650.46; on B r 50 leaves nothing (FC1: r 49.9 leaves 0.033 mm^3, r 50
# fails), so B's fillet fails and B stays 4000. Chamfer 30 on a 40 cube and the same B (O2's chamfer case): A loses
# the triangle 30 x 30 / 2 along 40 mm, 18000; B stays 4000.

import math
import re
import unittest

import FreeCAD

from PartDesignTests.Scenarios import models

App = FreeCAD
V = App.Vector

# What no failure message may contain: OCCT's class and exception names, its "command not done", C++'s
KERNEL = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|\b(?:TopoDS|Base|Part|std)::\w+|command not done"
    r"|Unknown C\+\+ exception|OCCT"
)


class TestFilletFailureText(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PartDesignTestFilletFailureText")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def part(self, name, x0, size, height):
        """A Body holding one Pad: the square x0..x0+size, 0..size, padded height."""
        body = self.doc.addObject("PartDesign::Body", name)
        sketch = models.sketch(
            self.doc, name + "Sketch", models.rectangle(x0, 0, x0 + size, size), body
        )
        pad = models.pad(body, sketch, height, name + "Pad")
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, size * size * height, delta=1e-6)
        return body, pad

    def topFront(self, shape, height):
        """The name of the top front edge: along x at y 0, z height."""
        names = [
            "Edge%d" % (i + 1)
            for i, edge in enumerate(shape.Edges)
            if abs(edge.CenterOfMass.y) < 1e-7
            and abs(edge.CenterOfMass.z - height) < 1e-7
            and abs(edge.Vertexes[0].Y - edge.Vertexes[-1].Y) < 1e-7
            and abs(edge.Vertexes[0].Z - edge.Vertexes[-1].Z) < 1e-7
        ]
        self.assertEqual(len(names), 1, names)
        return names[0]

    def twoParts(self, kind, sizeA, size):
        """A (a cube of sizeA) and B (20 x 20 x 10) dressed up on their top front edges, B's size
        following A's as the command makes it: the two features and the two Bodies."""
        bodyA, padA = self.part("PartA", 0, sizeA, sizeA)
        bodyB, padB = self.part("PartB", 120, 20, 10)
        made = []
        for body, pad, height in ((bodyA, padA, sizeA), (bodyB, padB, 10)):
            feature = body.newObject("PartDesign::" + kind, kind + body.Name)
            feature.Base = (pad, [self.topFront(pad.Shape, height)])
            made.append(feature)
        first, second = made
        param = "Radius" if kind == "Fillet" else "Size"
        setattr(first, param, size)
        second.setExpression(param, first.Name + "." + param)
        self.doc.recompute()
        return first, second, bodyA, bodyB

    def assertOnshapeFailure(self, feature, verb):
        self.assertFalse(feature.isValid())
        status = feature.getStatusString()
        self.assertTrue(status.startswith("Failed to %s selections: " % verb), status)
        self.assertIsNone(KERNEL.search(status), status)

    def testFilletOverTwoPartsBuildsThePartThatWorks(self):
        """O2: r 50 rounds A's edge; on B it leaves nothing, so B's fails and B is unchanged."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50)
        self.assertTrue(filletA.isValid(), filletA.getStatusString())
        self.assertEqual(filletB.Radius.Value, 50)
        removed = (1 - math.pi / 4) * 50**2 * 100
        self.assertAlmostEqual(filletA.Shape.Volume, 100**3 - removed, delta=1e-3)
        self.assertAlmostEqual(bodyA.Shape.Volume, 100**3 - removed, delta=1e-3)
        self.assertOnshapeFailure(filletB, "fillet")
        self.assertAlmostEqual(bodyB.Shape.Volume, 4000, delta=1e-6)
        self.assertEqual(len(bodyB.Shape.Solids), 1)
        self.assertEqual(len(bodyB.Shape.Faces), 6)

    def testChamferOverTwoPartsBuildsThePartThatWorks(self):
        """O2's chamfer case: 30 on a 40 cube's edge removes 18000; B's fails, B is unchanged."""
        chamferA, chamferB, bodyA, bodyB = self.twoParts("Chamfer", 40, 30)
        self.assertTrue(chamferA.isValid(), chamferA.getStatusString())
        self.assertAlmostEqual(chamferA.Shape.Volume, 40**3 - 30 * 30 / 2 * 40, delta=1e-3)
        self.assertOnshapeFailure(chamferB, "chamfer")
        self.assertAlmostEqual(bodyB.Shape.Volume, 4000, delta=1e-6)
        self.assertEqual(len(bodyB.Shape.Faces), 6)

    def testOnePartFailsWhole(self):
        """Within one part a fillet is all or nothing: r 50 on B's top front and top back edges
        fails, and B keeps its box."""
        body, pad = self.part("PartB", 120, 20, 10)
        back = [
            "Edge%d" % (i + 1)
            for i, edge in enumerate(pad.Shape.Edges)
            if abs(edge.CenterOfMass.y - 20) < 1e-7 and abs(edge.CenterOfMass.z - 10) < 1e-7
        ]
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, [self.topFront(pad.Shape, 10)] + back)
        fillet.Radius = 50
        self.doc.recompute()
        self.assertOnshapeFailure(fillet, "fillet")
        self.assertAlmostEqual(body.Shape.Volume, 4000, delta=1e-6)

    def testTheReasonFollowsTheMessage(self):
        """r 5.01 at an exact 5 step (FilletFallbackTest's stepped body, ops#601): OCCT fails and
        the exact construction refuses; the message is Onshape's, the refusal's reason after it."""
        from parttests.FilletFallbackTest import stepped_body

        for kind, verb in (("Fillet", "fillet"), ("Chamfer", "chamfer")):
            with self.subTest(kind=kind):
                doc = models.newDocument("PartDesignTestFilletFailureStep")
                try:
                    feature, _ = stepped_body(doc, kind, 5.01, 5, "one")
                    self.assertOnshapeFailure(feature, verb)
                    self.assertIn("runs off its face", feature.getStatusString())
                finally:
                    App.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()
