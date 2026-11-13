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
import os
import re
import shutil
import tempfile
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


class FailureCase(unittest.TestCase):
    """The two-part model and its checks."""

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

    def twoParts(self, kind, sizeA, size, sizeB=20, heightB=10, link=False):
        """A (a cube of sizeA) and B (sizeB x sizeB x heightB) dressed up on their top front edges,
        B's size following A's as the command makes it, and with `link` B's MultiPartPrimary A, as
        the command sets it since ops#701 (without it, a file from before): the two features and
        the two Bodies."""
        bodyA, padA = self.part("PartA", 0, sizeA, sizeA)
        bodyB, padB = self.part("PartB", 120, sizeB, heightB)
        made = []
        for body, pad, height in ((bodyA, padA, sizeA), (bodyB, padB, heightB)):
            feature = body.newObject("PartDesign::" + kind, kind + body.Name)
            feature.Base = (pad, [self.topFront(pad.Shape, height)])
            made.append(feature)
        first, second = made
        param = "Radius" if kind == "Fillet" else "Size"
        setattr(first, param, size)
        second.setExpression(param, first.Name + "." + param)
        if link:
            second.MultiPartPrimary = first
        self.doc.recompute()
        return first, second, bodyA, bodyB

    def assertOnshapeFailure(self, feature, verb):
        self.assertFalse(feature.isValid())
        status = feature.getStatusString()
        self.assertTrue(status.startswith("Failed to %s selections: " % verb), status)
        self.assertIsNone(KERNEL.search(status), status)

class TestFilletFailureText(FailureCase):
    """Onshape's message; without the link (a file from before ops#701) each part's
    dress-up fails on its own."""

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
        """r 5.01 at an exact 5 step on its four edges (FilletFallbackTest's stepped body, ops#601):
        OCCT fails and the exact construction refuses (the strips meet past the ledge's outer loop,
        Onshape's *_OVERLAPS_EDGE_LOOP); the message is Onshape's, the refusal's reason after it.
        On the one edge it now builds, trimmed by the step's wall (casebase #15, LD1-LD3)."""
        from parttests.FilletFallbackTest import stepped_body

        for kind, verb in (("Fillet", "fillet"), ("Chamfer", "chamfer")):
            with self.subTest(kind=kind):
                doc = models.newDocument("PartDesignTestFilletFailureStep")
                try:
                    feature, _ = stepped_body(doc, kind, 5.01, 5, "four")
                    self.assertOnshapeFailure(feature, verb)
                    self.assertIn("run past the face's outer loop", feature.getStatusString())
                finally:
                    App.closeDocument(doc.Name)



class TestMultiPartWarning(FailureCase):
    """F2b (ops#701): over several parts, a part that fails while the first part's dress-up builds
    is Onshape's FILLET_PARTIAL_FAIL: a warning, the part unchanged, its later features computed.
    The first part failing stays an error (ops#706); every part failing is FILLET_FAILED."""

    def assertPartialFailure(self, feature, verb, body):
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertIn("Warning", feature.State)
        status = feature.getStatusString()
        prefix = "Warning: Failed to %s selections on %s: " % (verb, body.Label)
        self.assertTrue(status.startswith(prefix), status)
        self.assertIsNone(KERNEL.search(status), status)

    def assertBoxB(self, body):
        self.assertAlmostEqual(body.Shape.Volume, 4000, delta=1e-6)
        self.assertEqual(len(body.Shape.Solids), 1)
        self.assertEqual(len(body.Shape.Faces), 6)

    def testFilletPartWarns(self):
        """O2: r 50 rounds A; B fails, warns and stays its box."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        self.assertTrue(filletA.isValid(), filletA.getStatusString())
        self.assertNotIn("Warning", filletA.State)
        removed = (1 - math.pi / 4) * 50**2 * 100
        self.assertAlmostEqual(bodyA.Shape.Volume, 100**3 - removed, delta=1e-3)
        self.assertPartialFailure(filletB, "fillet", bodyB)
        self.assertBoxB(bodyB)

    def testChamferPartWarns(self):
        """O2's chamfer: 30 on a 40 cube removes 18000; B warns and stays its box."""
        chamferA, chamferB, bodyA, bodyB = self.twoParts("Chamfer", 40, 30, link=True)
        self.assertTrue(chamferA.isValid(), chamferA.getStatusString())
        self.assertAlmostEqual(bodyA.Shape.Volume, 40**3 - 30 * 30 / 2 * 40, delta=1e-3)
        self.assertPartialFailure(chamferB, "chamfer", bodyB)
        self.assertBoxB(bodyB)

    def testLaterFeatureOfTheWarnedPartComputes(self):
        """A pocket after B's warned fillet computes on B's box: a 4 x 4 square 5 deep, 3920."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        sketch = models.sketch(
            self.doc, "PocketSketch", models.rectangle(128, 8, 132, 12), bodyB, z=10
        )
        pocket = models.pocket(bodyB, sketch, 5)
        self.doc.recompute()
        self.assertPartialFailure(filletB, "fillet", bodyB)
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertEqual(bodyB.Tip, pocket)
        self.assertAlmostEqual(bodyB.Shape.Volume, 4000 - 4 * 4 * 5, delta=1e-6)

    def testEveryPartFailingIsAnError(self):
        """FILLET_FAILED: r 50 on two 20 x 20 x 10 boxes fails both, each an error."""
        bodyA, padA = self.part("PartA", 0, 20, 10)
        bodyB, padB = self.part("PartB", 120, 20, 10)
        fillets = []
        for body, pad in ((bodyA, padA), (bodyB, padB)):
            fillet = body.newObject("PartDesign::Fillet", "Fillet" + body.Name)
            fillet.Base = (pad, [self.topFront(pad.Shape, 10)])
            fillets.append(fillet)
        first, second = fillets
        first.Radius = 50
        second.setExpression("Radius", first.Name + ".Radius")
        second.MultiPartPrimary = first
        self.doc.recompute()
        for fillet in fillets:
            self.assertOnshapeFailure(fillet, "fillet")
            self.assertNotIn("Warning", fillet.State)
        self.assertAlmostEqual(bodyB.Shape.Volume, 4000, delta=1e-6)

    def testThePrimaryFailingStaysAnError(self):
        """The first part's dress-up failing is an error (ops#706, as before); the follower
        builds: B the first part (r 50 fails), A the 100 cube."""
        bodyB, padB = self.part("PartB", 120, 20, 10)
        bodyA, padA = self.part("PartA", 0, 100, 100)
        first = bodyB.newObject("PartDesign::Fillet", "FilletB")
        first.Base = (padB, [self.topFront(padB.Shape, 10)])
        first.Radius = 50
        second = bodyA.newObject("PartDesign::Fillet", "FilletA")
        second.Base = (padA, [self.topFront(padA.Shape, 100)])
        second.setExpression("Radius", first.Name + ".Radius")
        second.MultiPartPrimary = first
        self.doc.recompute()
        self.assertOnshapeFailure(first, "fillet")
        self.assertTrue(second.isValid(), second.getStatusString())
        self.assertNotIn("Warning", second.State)
        self.assertAlmostEqual(
            bodyA.Shape.Volume, 100**3 - (1 - math.pi / 4) * 50**2 * 100, delta=1e-3
        )

    def testSavedAndReopened(self):
        """The link is saved: reopened and recomputed, B still warns and A still builds."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "twoparts.FCStd")
            names = filletA.Name, filletB.Name
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            filletA, filletB = (self.doc.getObject(name) for name in names)
            bodyB = self.doc.getObject("PartB")
            self.assertEqual(filletB.MultiPartPrimary, filletA)
            for obj in self.doc.Objects:
                obj.touch()
            self.doc.recompute()
            self.assertTrue(filletA.isValid(), filletA.getStatusString())
            self.assertPartialFailure(filletB, "fillet", bodyB)
            self.assertBoxB(bodyB)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def testFollowerOfADeletedPrimaryIsAnError(self):
        """The first part's dress-up deleted: B's link is cleared and its failure is an error."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        filletB.setExpression("Radius", None)
        filletB.Radius = 50
        name = filletA.Name
        bodyA.removeObject(filletA)
        self.doc.removeObject(name)
        self.doc.recompute()
        self.assertIsNone(filletB.MultiPartPrimary)
        self.assertOnshapeFailure(filletB, "fillet")
        self.assertNotIn("Warning", filletB.State)
        self.assertBoxB(bodyB)


class TestMultiPartLink(FailureCase):
    """F2c (ops#701): the link counts only while it holds. The follower's size expression must
    still refer to the first dress-up (it alone orders the two), and the first must have built
    its own result."""

    assertPartialFailure = TestMultiPartWarning.assertPartialFailure
    assertBoxB = TestMultiPartWarning.assertBoxB

    def assertFollowerError(self, feature, body):
        """B's failure is its own error: no warning, B passed through as its box."""
        self.assertFalse(feature.isValid())
        self.assertNotIn("Warning", feature.State)
        self.assertBoxB(body)

    def testPassThroughLeavesNoAddSubShape(self):
        """B's warned fillet adds and removes nothing, as a suppressed feature: its AddSubShape
        is empty."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        self.assertPartialFailure(filletB, "fillet", bodyB)
        shape = filletB.AddSubShape
        self.assertTrue(shape.isNull() or abs(shape.Volume) < 1e-9)

    def testPrimaryDeletedWithTheExpressionLeft(self):
        """The first dress-up deleted while B's radius still refers to it: the link is cleared,
        B is an error (its expression no longer resolves), not a warning; B stays its box."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        name = filletA.Name
        bodyA.removeObject(filletA)
        self.doc.removeObject(name)
        self.doc.recompute()
        self.assertIsNone(filletB.MultiPartPrimary)
        self.assertFollowerError(filletB, bodyB)
        self.assertFalse(filletB.getStatusString().startswith("Warning"))

    def testPrimaryEditedToFail(self):
        """The pair worked; A's radius is then set to 150, past A's 100 faces: A fails, and B,
        failing too, is an error, not a warning (FILLET_FAILED)."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        self.assertPartialFailure(filletB, "fillet", bodyB)
        filletA.Radius = 150
        self.doc.recompute()
        self.assertOnshapeFailure(filletA, "fillet")
        self.assertEqual(filletB.Radius.Value, 150)
        self.assertOnshapeFailure(filletB, "fillet")
        self.assertFollowerError(filletB, bodyB)
        self.assertAlmostEqual(bodyA.Shape.Volume, 100**3, delta=1e-6)

    def testSuppressedPrimary(self):
        """A's fillet suppressed: it built nothing of its own, so B's failure is an error."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        filletA.Suppressed = True
        self.doc.recompute()
        self.assertAlmostEqual(bodyA.Shape.Volume, 100**3, delta=1e-6)
        self.assertEqual(filletB.MultiPartPrimary, filletA)
        self.assertFollowerError(filletB, bodyB)
        filletA.Suppressed = False
        self.doc.recompute()
        self.assertPartialFailure(filletB, "fillet", bodyB)

    def testUndoOfTheSuppressionWarnsAgain(self):
        """A suppressed and recomputed in one transaction, then undone: undo puts back B's
        properties but not its error, so B must run again and warn."""
        self.doc.UndoMode = 1
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        self.doc.openTransaction("Suppress the first fillet")
        filletA.Suppressed = True
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertFollowerError(filletB, bodyB)
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse(filletA.Suppressed)
        self.assertPartialFailure(filletB, "fillet", bodyB)
        self.assertBoxB(bodyB)

    def testUndoOfThePrimaryDeletionRestoresTheLink(self):
        """Undo of the first dress-up's deletion brings the link back, and B warns again."""
        self.doc.UndoMode = 1
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        name, nameB = filletA.Name, filletB.Name
        self.doc.openTransaction("Delete the first fillet")
        bodyA.removeObject(filletA)
        self.doc.removeObject(name)
        self.doc.commitTransaction()
        self.doc.recompute()
        filletB = self.doc.getObject(nameB)
        self.assertIsNone(filletB.MultiPartPrimary)
        self.doc.undo()
        self.doc.recompute()
        filletA = self.doc.getObject(name)
        self.assertIsNotNone(filletA)
        self.assertEqual(filletB.MultiPartPrimary, filletA)
        self.assertTrue(filletA.isValid(), filletA.getStatusString())
        self.assertPartialFailure(filletB, "fillet", bodyB)
        self.assertBoxB(bodyB)

    def testOwnSizeEndsTheLink(self):
        """B given a size of its own, its expression cleared or replaced: nothing orders the two
        and B no longer follows A, so B's failure is an error, the link left as it is. A hidden
        reference (href) orders nothing either."""
        for case in ("cleared", "constant", "hidden", "chamfer"):
            with self.subTest(case=case):
                if case == "chamfer":
                    first, second, bodyA, bodyB = self.twoParts("Chamfer", 40, 30, link=True)
                    second.setExpression("Size", None)
                    second.Size = 30
                else:
                    first, second, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
                    if case == "cleared":
                        second.setExpression("Radius", None)
                        second.Radius = 50
                    elif case == "hidden":
                        second.setExpression("Radius", "href(%s.Radius)" % first.Name)
                    else:
                        second.setExpression("Radius", "50 mm")
                self.doc.recompute()
                self.assertTrue(first.isValid(), first.getStatusString())
                self.assertEqual(second.MultiPartPrimary, first)
                self.assertFollowerError(second, bodyB)
                App.closeDocument(self.doc.Name)
                self.doc = models.newDocument("PartDesignTestFilletFailureText")

    def testWarningRightAfterReopen(self):
        """Saved with B warned and reopened, before any recompute: B shows the warning, valid,
        and B's shape is its box."""
        filletA, filletB, bodyA, bodyB = self.twoParts("Fillet", 100, 50, link=True)
        status = filletB.getStatusString()
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "warned.FCStd")
            nameA, nameB = filletA.Name, filletB.Name
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            filletA, filletB = self.doc.getObject(nameA), self.doc.getObject(nameB)
            bodyB = self.doc.getObject("PartB")
            self.assertTrue(filletA.isValid(), filletA.getStatusString())
            self.assertPartialFailure(filletB, "fillet", bodyB)
            self.assertEqual(filletB.getStatusString(), status)
            self.assertBoxB(bodyB)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
