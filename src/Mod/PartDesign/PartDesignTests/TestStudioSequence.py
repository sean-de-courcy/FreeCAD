# SPDX-License-Identifier: LGPL-2.1-or-later

"""B+ Stage 2 (ops#602): the studio's feature list and its one roll-back bar.

PartDesign.studioSequence lists every member of a studio's Bodies in history order (after what it
reads in other Bodies and after its Body's earlier members, the oldest first where that leaves a
choice); rollStudioTo moves every Body's bar to one point of that list. The Features dock shows
both (notes/features-dock-design.md). Every model is designed: the expected shapes come from
volumes.
"""

import os
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign
import Sketcher

V = App.Vector


def rect(sketch, x0, y0, x1, y1):
    points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    first = len(sketch.Geometry)
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(points[i], points[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1)
        )


def sketch(body, name, *rects, z=0, support=None):
    s = body.newObject("Sketcher::SketchObject", name)
    s.AttachmentSupport = support or [(body.Origin.OriginFeatures[3], "")]
    s.MapMode = "FlatFace"
    if z:
        s.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
    for r in rects:
        rect(s, *r)
    return s


def faceAt(feature, z):
    """The planar face of feature's shape at height z facing up."""
    for i, face in enumerate(feature.Shape.Faces, 1):
        if (
            face.Surface.__class__.__name__ == "Plane"
            and abs(face.normalAt(0, 0).z - 1) < 1e-9
            and abs(face.CenterOfMass.z - z) < 1e-6
        ):
            return f"Face{i}"
    return None


class TestStudioSequence(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestStudioSequence")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def names(self, objs):
        return [o.Name if o else None for o in objs]

    def interleaved(self, container=None):
        """Made in this order: Body1's sketch and Pad (20x10x5); Body2's box (6x6x3) on the
        Pad's top face; a Body2 sketch (6x4) at the box's top; a Body1 Pocket through all from
        that Body2 sketch; a Body2 Pocket through all from it too."""
        doc = self.doc
        self.body1 = doc.addObject("PartDesign::Body", "Body1")
        self.body2 = doc.addObject("PartDesign::Body", "Body2")
        if container:
            container.addObject(self.body1)
            container.addObject(self.body2)
        self.skA = sketch(self.body1, "SkA", (0, 0, 20, 10))
        self.padA = self.body1.newObject("PartDesign::Pad", "PadA")
        self.padA.Profile = self.skA
        self.padA.Length = 5
        doc.recompute()
        self.box = self.body2.newObject("PartDesign::AdditiveBox", "Box")
        self.box.Length = self.box.Width = 6
        self.box.Height = 3
        self.box.AttachmentSupport = [(self.padA, faceAt(self.padA, 5))]
        self.box.MapMode = "FlatFace"
        self.box.AttachmentOffset = App.Placement(V(2, 2, 0), App.Rotation())
        doc.recompute()
        self.skB = sketch(self.body2, "SkB", (6, 2, 12, 6), z=8)
        self.pocket1 = self.body1.newObject("PartDesign::Pocket", "Pocket1")
        self.pocket1.Profile = self.skB
        self.pocket1.Type = "ThroughAll"
        self.pocket1.SideType = "Symmetric"
        self.pocketB = self.body2.newObject("PartDesign::Pocket", "PocketB")
        self.pocketB.Profile = self.skB
        self.pocketB.Type = "ThroughAll"
        self.pocketB.SideType = "Symmetric"
        doc.recompute()
        self.assertEqual([o.Name for o in doc.Objects if not o.isValid()], [])
        self.checkEnd()

    def checkEnd(self):
        # Body1: 20x10x5 less the 6x4 hole; Body2: the 6x6x3 box less the 2x4 overlap of the hole
        self.assertAlmostEqual(self.body1.Shape.Volume, (200 - 24) * 5, places=3)
        self.assertAlmostEqual(self.body2.Shape.Volume, 108 - 24, places=3)

    # ------------------------------------------------------------------------------ the order

    def testInterleavedOrder(self):
        self.interleaved()
        self.assertEqual(
            self.names(PartDesign.studioSequence(self.doc)),
            ["SkA", "PadA", "Box", "SkB", "Pocket1", "PocketB"],
        )

    def testInAnAppPart(self):
        """An App::Part is a studio of its own: the top level lists none of its Bodies."""
        studio = self.doc.addObject("App::Part", "Studio")
        self.interleaved(studio)
        other = self.doc.addObject("PartDesign::Body", "Other")
        sketch(other, "SkO", (0, 0, 1, 1))
        self.assertEqual(
            self.names(PartDesign.studioSequence(studio)),
            ["SkA", "PadA", "Box", "SkB", "Pocket1", "PocketB"],
        )
        self.assertEqual(self.names(PartDesign.studioSequence(self.doc)), ["SkO"])

    def testDependencyBeatsAge(self):
        """A Body2 sketch made before Body1's Pad, then attached to its face, comes after it."""
        body1 = self.doc.addObject("PartDesign::Body", "Body1")
        body2 = self.doc.addObject("PartDesign::Body", "Body2")
        skA = sketch(body1, "SkA", (0, 0, 20, 10))
        skB = sketch(body2, "SkB", (2, 2, 4, 4))
        padA = body1.newObject("PartDesign::Pad", "PadA")
        padA.Profile = skA
        padA.Length = 5
        self.doc.recompute()
        self.assertEqual(self.names(PartDesign.studioSequence(self.doc)), ["SkA", "SkB", "PadA"])
        skB.AttachmentSupport = [(padA, faceAt(padA, 5))]
        self.doc.recompute()
        self.assertEqual(self.names(PartDesign.studioSequence(self.doc)), ["SkA", "PadA", "SkB"])

    def testReorderKeepsBodyAndDependencyOrder(self):
        """A Pad made last and moved before Body1's Pocket: Body1's rows keep its Group order,
        the Pocket stays after the Body2 sketch it reads, and Body2's older rows go first."""
        self.interleaved()
        skC = sketch(self.body1, "SkC", (14, 0, 20, 10), z=5)
        padC = self.body1.newObject("PartDesign::Pad", "PadC")
        padC.Profile = skC
        padC.Length = 2
        self.doc.recompute()
        self.assertEqual(
            self.names(PartDesign.studioSequence(self.doc)),
            ["SkA", "PadA", "Box", "SkB", "Pocket1", "PocketB", "SkC", "PadC"],
        )
        self.body1.reorderObject([skC, padC], self.pocket1, False)
        self.doc.recompute()
        self.assertEqual(self.names(self.body1.Group), ["SkA", "PadA", "SkC", "PadC", "Pocket1"])
        self.assertEqual(
            self.names(PartDesign.studioSequence(self.doc)),
            ["SkA", "PadA", "Box", "SkB", "PocketB", "SkC", "PadC", "Pocket1"],
        )
        # The hole still goes through Body1, now 20x10x5 plus 6x10x2
        self.assertAlmostEqual(self.body1.Shape.Volume, (200 - 24) * 5 + 120, places=3)

    def testReadThroughAnotherStudio(self):
        """Review props602-r1 T1: A's sketch sits on a Body C of another studio (an App::Part)
        whose sketch sits on B's Pad. A, made first, comes after B's Pad all the same."""
        bodyA = self.doc.addObject("PartDesign::Body", "A")
        skA = sketch(bodyA, "SkA", (0, 0, 2, 2))
        padA = bodyA.newObject("PartDesign::Pad", "PadA")
        padA.Profile = skA
        padA.Length = 1
        bodyB = self.doc.addObject("PartDesign::Body", "B")
        skB = sketch(bodyB, "SkB", (0, 0, 10, 10))
        padB = bodyB.newObject("PartDesign::Pad", "PadB")
        padB.Profile = skB
        padB.Length = 5
        self.doc.recompute()
        part = self.doc.addObject("App::Part", "P")
        bodyC = self.doc.addObject("PartDesign::Body", "C")
        part.addObject(bodyC)
        skC = sketch(bodyC, "SkC", (0, 0, 4, 4), support=[(padB, faceAt(padB, 5))])
        padC = bodyC.newObject("PartDesign::Pad", "PadC")
        padC.Profile = skC
        padC.Length = 2
        self.doc.recompute()
        self.assertEqual(self.names(PartDesign.studioSequence(self.doc)), ["SkA", "PadA", "SkB", "PadB"])
        skA.AttachmentSupport = [(padC, faceAt(padC, 7))]
        self.doc.recompute()
        self.assertEqual(self.names(PartDesign.studioSequence(self.doc)), ["SkB", "PadB", "SkA", "PadA"])
        self.assertEqual(self.names(PartDesign.studioSequence(part)), ["SkC", "PadC"])

    def subnameModel(self, viaPart):
        """Review props602-r1fix R1: Body A's binder reads one face of PadC1, a feature of Body C
        in another studio (the App::Part P), by a subname: (C, "PadC1.FaceN"), or (P,
        "C.PadC1.FaceN") with viaPart. C's later Pad sits on Body D's, and D's first sketch is
        moved onto A's Pad last. A reads PadC1 only, so A comes before D."""
        bodyD = self.doc.addObject("PartDesign::Body", "D")
        skD1 = sketch(bodyD, "SkD1", (0, 0, 10, 10))
        padD1 = bodyD.newObject("PartDesign::Pad", "PadD1")
        padD1.Profile = skD1
        padD1.Length = 1
        skD2 = sketch(bodyD, "SkD2", (0, 0, 10, 10), z=1)
        padD2 = bodyD.newObject("PartDesign::Pad", "PadD2")
        padD2.Profile = skD2
        padD2.Length = 1
        part = self.doc.addObject("App::Part", "P")
        bodyC = self.doc.addObject("PartDesign::Body", "C")
        part.addObject(bodyC)
        padC1 = bodyC.newObject("PartDesign::AdditiveBox", "PadC1")
        padC1.Length = padC1.Width = 4
        padC1.Height = 3
        self.doc.recompute()
        bodyA = self.doc.addObject("PartDesign::Body", "A")
        binder = bodyA.newObject("PartDesign::SubShapeBinder", "BinA")
        face = faceAt(padC1, 3)
        binder.Support = [(part, (f"C.PadC1.{face}",))] if viaPart else [(bodyC, (f"PadC1.{face}",))]
        skA2 = sketch(bodyA, "SkA2", (20, 0, 24, 4))
        padA2 = bodyA.newObject("PartDesign::Pad", "PadA2")
        padA2.Profile = skA2
        padA2.Length = 2
        self.doc.recompute()
        skC2 = sketch(bodyC, "SkC2", (0, 0, 2, 2), support=[(padD2, faceAt(padD2, 2))])
        padC2 = bodyC.newObject("PartDesign::Pad", "PadC2")
        padC2.Profile = skC2
        padC2.Length = 1
        self.doc.recompute()
        skD1.AttachmentSupport = [(padA2, faceAt(padA2, 2))]
        self.doc.recompute()
        self.assertEqual(
            self.names(PartDesign.studioSequence(self.doc)),
            ["BinA", "SkA2", "PadA2", "SkD1", "PadD1", "SkD2", "PadD2"],
        )
        # The bar after A's Pad holds all of D and none of A
        PartDesign.rollStudioTo(self.doc, padA2)
        self.assertEqual(self.names((bodyA.Tip, bodyD.Tip)), ["PadA2", None])

    def testSubnameIntoAnotherStudiosBody(self):
        self.subnameModel(viaPart=False)

    def testSubnameThroughAnotherStudio(self):
        self.subnameModel(viaPart=True)

    def wholeAndSubnameModel(self, whole):
        """Review props602-r2fix N1: Body A (made first) has a binder of one face of PadC1, in
        Body C of another studio, and also reads all of C: by an expression (whole="expression")
        or by a second entry linking an App::Link to C (whole="link"); whole=None reads PadC1
        only. C's later Pad sits on Body D's, so reading all of C puts A after D."""
        bodyA = self.doc.addObject("PartDesign::Body", "A")
        binder = bodyA.newObject("PartDesign::SubShapeBinder", "BinA")
        skA2 = sketch(bodyA, "SkA2", (20, 0, 24, 4))
        padA2 = bodyA.newObject("PartDesign::Pad", "PadA2")
        padA2.Profile = skA2
        padA2.Length = 2
        bodyD = self.doc.addObject("PartDesign::Body", "D")
        skD = sketch(bodyD, "SkD", (0, 0, 10, 10))
        padD = bodyD.newObject("PartDesign::Pad", "PadD")
        padD.Profile = skD
        padD.Length = 1
        part = self.doc.addObject("App::Part", "P")
        bodyC = self.doc.addObject("PartDesign::Body", "C")
        part.addObject(bodyC)
        padC1 = bodyC.newObject("PartDesign::AdditiveBox", "PadC1")
        padC1.Length = padC1.Width = 4
        padC1.Height = 3
        self.doc.recompute()
        skC2 = sketch(bodyC, "SkC2", (0, 0, 2, 2), support=[(padD, faceAt(padD, 1))])
        padC2 = bodyC.newObject("PartDesign::Pad", "PadC2")
        padC2.Profile = skC2
        padC2.Length = 1
        self.doc.recompute()
        support = [(bodyC, (f"PadC1.{faceAt(padC1, 3)}",))]
        if whole == "link":
            link = self.doc.addObject("App::Link", "LnkC")
            link.LinkedObject = bodyC
            support.append((link, ("",)))
        binder.Support = support
        if whole == "expression":
            binder.addProperty("App::PropertyFloat", "Probe")
            binder.setExpression("Probe", "<<C>>.Shape.BoundBox.XMax")  # C alone is a unit
        return self.names(PartDesign.studioSequence(self.doc))

    def testSubnameOnlyReadsThatFeature(self):
        self.assertEqual(self.wholeAndSubnameModel(None), ["BinA", "SkA2", "PadA2", "SkD", "PadD"])

    def testSubnameAndExpressionOfTheWholeBody(self):
        self.assertEqual(
            self.wholeAndSubnameModel("expression"), ["SkD", "PadD", "BinA", "SkA2", "PadA2"]
        )

    def testSubnameAndLinkToTheWholeBody(self):
        self.assertEqual(self.wholeAndSubnameModel("link"), ["SkD", "PadD", "BinA", "SkA2", "PadA2"])

    def testALoopListsEveryMemberOnce(self):
        """Sketches that read each other's Body crosswise (from Python): no order satisfies both
        Bodies, and every member is still listed once, each Body's in its Group order."""
        body1 = self.doc.addObject("PartDesign::Body", "Body1")
        body2 = self.doc.addObject("PartDesign::Body", "Body2")
        x1 = sketch(body1, "X1", (0, 0, 1, 1))
        y1 = body1.newObject("PartDesign::Pad", "Y1")
        x2 = sketch(body2, "X2", (0, 0, 1, 1))
        y2 = body2.newObject("PartDesign::Pad", "Y2")
        x1.MapMode = x2.MapMode = "Deactivated"
        x1.AttachmentSupport = [(y2, "")]
        x2.AttachmentSupport = [(y1, "")]
        sequence = self.names(PartDesign.studioSequence(self.doc))
        self.assertEqual(sorted(sequence), ["X1", "X2", "Y1", "Y2"])
        self.assertLess(sequence.index("X1"), sequence.index("Y1"))
        self.assertLess(sequence.index("X2"), sequence.index("Y2"))

    def testMultiTransformStepsAreNoRows(self):
        body = self.doc.addObject("PartDesign::Body", "Body")
        sk = sketch(body, "Sk", (0, 0, 2, 2))
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sk
        pad.Length = 1
        multi = body.newObject("PartDesign::MultiTransform", "Multi")
        multi.Originals = [pad]
        step = body.newObject("PartDesign::LinearPattern", "Step")
        multi.Transformations = [step]
        self.doc.recompute()
        self.assertIn(step, body.Group)
        self.assertEqual(self.names(PartDesign.studioSequence(self.doc)), ["Sk", "Pad", "Multi"])

    # -------------------------------------------------------------------------------- the bar

    def testBarAfterEachRow(self):
        self.interleaved()
        expected = {
            None: (None, None),
            "SkA": (None, None),
            "PadA": ("PadA", None),
            "Box": ("PadA", "Box"),
            "SkB": ("PadA", "Box"),
            "Pocket1": ("Pocket1", "Box"),
            "PocketB": ("Pocket1", "PocketB"),
        }
        sequence = PartDesign.studioSequence(self.doc)
        for member in [None] + sequence:
            name = member.Name if member else None
            with self.subTest(after=name):
                PartDesign.rollStudioTo(self.doc, member)
                self.doc.recompute()
                tips = (self.body1.Tip, self.body2.Tip)
                self.assertEqual(self.names(tips), list(expected[name]))
                self.assertEqual(PartDesign.isStudioRolledBack(self.doc), name != "PocketB")
                # The bar shows where it was put (the hint), and without one before the first
                # held row
                self.assertEqual(PartDesign.studioBarAfter(self.doc, member), member)
                # Nothing above the bar is held, everything below it that is a solid is
                above = sequence[: sequence.index(member) + 1] if member else []
                for row in sequence:
                    body = self.body1 if row in self.body1.Group else self.body2
                    if row in above:
                        self.assertFalse(body.holds(row), row.Name)
                    elif row.Name in ("PadA", "Box", "Pocket1", "PocketB"):
                        self.assertTrue(body.holds(row), row.Name)
        self.checkEnd()

    def testBarShapes(self):
        """The Tips' shapes at each point, and both Bodies' shapes back at the end."""
        self.interleaved()
        PartDesign.rollStudioTo(self.doc, self.box)
        self.doc.recompute()
        self.assertAlmostEqual(self.body1.Tip.Shape.Volume, 1000, places=3)
        self.assertAlmostEqual(self.body2.Tip.Shape.Volume, 108, places=3)
        PartDesign.rollStudioTo(self.doc, self.pocket1)
        self.doc.recompute()
        self.assertAlmostEqual(self.body1.Tip.Shape.Volume, 880, places=3)
        self.assertAlmostEqual(self.body2.Tip.Shape.Volume, 108, places=3)
        # An edit while rolled back is computed on the way to the end
        self.padA.Length = 7
        PartDesign.rollStudioToEnd(self.doc)
        self.doc.recompute()
        self.assertFalse(PartDesign.isStudioRolledBack(self.doc))
        self.assertAlmostEqual(self.body1.Shape.Volume, (200 - 24) * 7, places=3)
        self.assertAlmostEqual(self.body2.Shape.Volume, 108 - 24, places=3)
        self.assertAlmostEqual(self.body2.Shape.BoundBox.ZMin, 7, places=6)

    def testBarWithoutHint(self):
        """Without a hint the bar sits above the sketches waiting with the held rows: a sketch
        whose users are all held is listed below the bar with them (ops#640 rank 34)."""
        self.interleaved()
        PartDesign.rollStudioTo(self.doc, self.box)
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "Box")
        PartDesign.rollStudioTo(self.doc, None)
        self.assertIsNone(PartDesign.studioBarAfter(self.doc))
        self.assertIsNone(PartDesign.studioBarAfter(self.doc, None))
        PartDesign.rollStudioToEnd(self.doc)
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "PocketB")
        # A hint below the first held row is ignored
        PartDesign.rollStudioTo(self.doc, self.padA)
        self.assertEqual(PartDesign.studioBarAfter(self.doc, self.pocketB).Name, "PadA")

    def testOneUndoStepPerMove(self):
        self.interleaved()
        self.doc.UndoMode = 1
        count = self.doc.UndoCount
        self.doc.openTransaction("Roll to here")
        PartDesign.rollStudioTo(self.doc, self.padA)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(self.names((self.body1.Tip, self.body2.Tip)), ["PadA", None])
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.names((self.body1.Tip, self.body2.Tip)), ["Pocket1", "PocketB"])
        self.assertFalse(PartDesign.isStudioRolledBack(self.doc))
        self.checkEnd()

    def testRefusals(self):
        self.interleaved()
        stray = self.doc.addObject("Part::Box", "Stray")
        with self.assertRaises(ValueError):
            PartDesign.rollStudioTo(self.doc, stray)
        with self.assertRaises(TypeError):
            PartDesign.studioSequence(stray)
        self.assertEqual(self.names((self.body1.Tip, self.body2.Tip)), ["Pocket1", "PocketB"])


class TestHistoryOrder(unittest.TestCase):
    """ops#632 (notes/part-history-design.md 3.3): the saved history order and the drop.

    PartDesign.moveInStudio drags features of one Body in the studio's history; an insert at a
    rolled-back bar is listed at the bar. Both save the order (HistoryRank). Designed blocks: the
    expected shapes come from volumes."""

    def setUp(self):
        self.doc = App.newDocument("TestHistoryOrder")
        self.doc.UndoMode = 1
        self.reopened = None

    def tearDown(self):
        App.closeDocument((self.reopened or self.doc).Name)

    def names(self, objs):
        return [o.Name if o else None for o in objs]

    def order(self, doc=None):
        return self.names(PartDesign.studioSequence(doc or self.doc))

    def ranked(self):
        return sorted(o.Name for o in self.doc.Objects if "HistoryRank" in o.PropertiesList)

    def pad(self, body, name, profile, length):
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile = profile
        pad.Length = length
        return pad

    def twoParts(self):
        """Made in this order: Body1's sketch and Pad (a 10x10x5 block at the origin); Body2's
        sketch and Pad (a 10x10x4 block at x = 20); Body1's sketch at z = 5 and Pad (a 4x4x2 boss
        on the first block). No feature reads another Body."""
        doc = self.doc
        self.body1 = doc.addObject("PartDesign::Body", "Body1")
        self.body2 = doc.addObject("PartDesign::Body", "Body2")
        self.skA = sketch(self.body1, "SkA", (0, 0, 10, 10))
        self.padA = self.pad(self.body1, "PadA", self.skA, 5)
        self.skC = sketch(self.body2, "SkC", (20, 0, 30, 10))
        self.padC = self.pad(self.body2, "PadC", self.skC, 4)
        self.skA2 = sketch(self.body1, "SkA2", (2, 2, 6, 6), z=5)
        self.padA2 = self.pad(self.body1, "PadA2", self.skA2, 2)
        doc.recompute()
        self.assertEqual(self.order(), ["SkA", "PadA", "SkC", "PadC", "SkA2", "PadA2"])
        self.checkVolumes(500 + 32, 400)

    def checkVolumes(self, v1, v2):
        self.doc.recompute()
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.assertAlmostEqual(self.body1.Shape.Volume, v1, places=3)
        self.assertAlmostEqual(self.body2.Shape.Volume, v2, places=3)

    # --------------------------------------------------------------------- insert at the bar

    def testInsertAtTheBarIsListedAboveTheHeldRows(self):
        """Design 2.3: rolled back after PadA, a sketch and Pad added to Body1 are listed at the
        bar, above Body2's held Pad (before: after it, the oldest first), with Body1's sketch made
        before them; the order is saved with the file."""
        self.twoParts()
        PartDesign.rollStudioTo(self.doc, self.padA)
        self.doc.recompute()
        self.assertEqual(self.names((self.body1.Tip, self.body2.Tip)), ["PadA", None])
        skN = sketch(self.body1, "SkN", (7, 7, 9, 9), z=5)
        padN = self.pad(self.body1, "PadN", skN, 1)
        self.doc.recompute()
        expected = ["SkA", "PadA", "SkN", "PadN", "SkC", "PadC", "SkA2", "PadA2"]
        self.assertEqual(self.order(), expected)
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "PadN")
        self.assertEqual(self.body1.Tip, padN)
        # Rolled to the end: both parts, the new boss on the first block
        PartDesign.rollStudioToEnd(self.doc)
        self.checkVolumes(500 + 32 + 4, 400)
        self.assertEqual(self.order(), expected)
        # Saved and opened again: the same order
        path = os.path.join(tempfile.mkdtemp(), "HistoryOrder.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.reopened = App.openDocument(path)
        self.assertEqual(self.order(self.reopened), expected)

    def testInsertAtTheEndSavesNothing(self):
        """Not rolled back: an insert is the newest and listed last, as before; no order is
        saved."""
        self.twoParts()
        skN = sketch(self.body2, "SkN", (22, 2, 24, 4), z=4)
        self.pad(self.body2, "PadN", skN, 1)
        self.doc.recompute()
        self.assertEqual(self.order()[-2:], ["SkN", "PadN"])
        self.assertEqual(self.ranked(), [])

    # ------------------------------------------------------------------------------ the drop

    def testDropAcrossBodies(self):
        """Body2's rows dragged to the top, then Body1's boss dragged between Body2's sketch and
        Pad: the list is the dropped order, the Groups don't change, and the shapes are the
        same."""
        self.twoParts()
        self.assertTrue(PartDesign.moveInStudio(self.doc, [self.skC, self.padC], None))
        self.assertEqual(self.order(), ["SkC", "PadC", "SkA", "PadA", "SkA2", "PadA2"])
        self.assertTrue(PartDesign.moveInStudio(self.doc, [self.skA2, self.padA2], self.skC))
        self.assertEqual(self.order(), ["SkC", "SkA2", "PadA2", "PadC", "SkA", "PadA"])
        # Inside Body1 the boss went above the block: the reorder's path
        self.assertEqual(self.names(self.body1.Group), ["SkA2", "PadA2", "SkA", "PadA"])
        self.assertEqual(self.names(self.body2.Group), ["SkC", "PadC"])
        self.checkVolumes(500 + 32, 400)

    def testDropInsideABodyWithItsSketch(self):
        """Body1's boss Pad dragged to the top with its sketch: Body1's Group puts them first,
        and the list is the dropped order. Alone, the Pad would go above its sketch: refused
        (ops#640 rank 31: a drag moves only the dragged rows), and nothing changes."""
        self.twoParts()
        with self.assertRaisesRegex(ValueError, "'PadA2' uses 'SkA2', which would come after it"):
            PartDesign.moveInStudio(self.doc, self.padA2, None)
        self.assertEqual(self.names(self.body1.Group), ["SkA", "PadA", "SkA2", "PadA2"])
        self.assertEqual(self.ranked(), [])
        self.assertTrue(PartDesign.moveInStudio(self.doc, [self.skA2, self.padA2], None))
        self.assertEqual(self.names(self.body1.Group), ["SkA2", "PadA2", "SkA", "PadA"])
        self.assertEqual(self.order(), ["SkA2", "PadA2", "SkA", "PadA", "SkC", "PadC"])
        self.assertEqual(self.body1.Tip, self.padA)
        self.checkVolumes(500 + 32, 400)

    def testDropNextToItsSketch(self):
        """Body1's boss Pad dragged to after Body1's block, above Body2: it would go above its
        sketch, refused; with its sketch, Body1's Group stays as it is."""
        self.twoParts()
        with self.assertRaisesRegex(ValueError, "'PadA2' uses 'SkA2'"):
            PartDesign.moveInStudio(self.doc, self.padA2, self.padA)
        self.assertTrue(PartDesign.moveInStudio(self.doc, [self.skA2, self.padA2], self.padA))
        self.assertEqual(self.names(self.body1.Group), ["SkA", "PadA", "SkA2", "PadA2"])
        self.assertEqual(self.order(), ["SkA", "PadA", "SkA2", "PadA2", "SkC", "PadC"])
        self.checkVolumes(500 + 32, 400)

    def holeBlock(self):
        """ops#640 rank 31 (blind test F31, J5): Body1's 20x10x5 block; on its top face a boss
        sketch (4x4 at x 2..6) and a hole sketch (2x2 at x 14..16), then the boss Pad (2 high) and
        a Pocket through all from the hole sketch, which misses the boss."""
        doc = self.doc
        self.body1 = doc.addObject("PartDesign::Body", "Body1")
        self.base = self.pad(self.body1, "BasePad", sketch(self.body1, "Base", (0, 0, 20, 10)), 5)
        doc.recompute()
        top = [(self.base, faceAt(self.base, 5))]
        self.bossSk = sketch(self.body1, "BossSk", (2, 2, 6, 6), support=top)
        self.holeSk = sketch(self.body1, "HoleSk", (14, 4, 16, 6), support=top)
        doc.recompute()
        self.boss = self.pad(self.body1, "BossPad", self.bossSk, 2)
        self.pocket = self.body1.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.holeSk
        self.pocket.Type = "ThroughAll"
        doc.recompute()
        self.assertEqual(self.order(), ["Base", "BasePad", "BossSk", "HoleSk", "BossPad", "Pocket"])
        self.assertAlmostEqual(self.body1.Shape.Volume, 1000 + 32 - 20, places=3)

    def testADraggedFeatureLeavesItsSketch(self):
        """The Pocket dragged above the boss Pad moves alone: its sketch stays where it is and
        its face reference isn't rewritten (before: the sketch came along and was re-attached);
        the part is the same."""
        self.holeBlock()
        support = [(o.Name, subs) for o, subs in self.holeSk.AttachmentSupport]
        self.assertTrue(PartDesign.moveInStudio(self.doc, self.pocket, self.holeSk))
        self.assertEqual(self.order(), ["Base", "BasePad", "BossSk", "HoleSk", "Pocket", "BossPad"])
        self.assertEqual(self.names(self.body1.Group), self.order())
        self.assertEqual([(o.Name, subs) for o, subs in self.holeSk.AttachmentSupport], support)
        self.assertIs(self.boss.BaseFeature, self.pocket)
        self.doc.recompute()
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.assertAlmostEqual(self.body1.Shape.Volume, 1000 + 32 - 20, places=3)

    def testAFeatureDraggedAboveItsSketchIsRefused(self):
        """The Pocket dragged above its sketch, or the sketch below the Pocket: refused, naming
        both, and nothing changes."""
        self.holeBlock()
        before = self.order()
        with self.assertRaisesRegex(ValueError, "'Pocket' uses 'HoleSk', which would come after it"):
            PartDesign.moveInStudio(self.doc, self.pocket, self.bossSk)
        with self.assertRaisesRegex(ValueError, "'Pocket' uses 'HoleSk'"):
            PartDesign.moveInStudio(self.doc, self.holeSk, self.pocket)
        self.assertEqual(self.order(), before)
        self.assertEqual(self.names(self.body1.Group), before)
        self.assertEqual(self.ranked(), [])

    def testDropInPlaceChangesNothing(self):
        self.twoParts()
        self.assertFalse(PartDesign.moveInStudio(self.doc, self.padC, self.skC))
        self.assertEqual(self.ranked(), [])

    def testOneUndoStep(self):
        """A drop in one transaction is one undo step: the order, the Group and the saved ranks
        go back."""
        self.twoParts()
        count = self.doc.UndoCount
        self.doc.openTransaction("Reorder")
        PartDesign.moveInStudio(self.doc, [self.skA2, self.padA2], None)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertNotEqual(self.ranked(), [])
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.names(self.body1.Group), ["SkA", "PadA", "SkA2", "PadA2"])
        self.assertEqual(self.order(), ["SkA", "PadA", "SkC", "PadC", "SkA2", "PadA2"])
        self.assertEqual(self.ranked(), [])
        self.checkVolumes(500 + 32, 400)

    # ------------------------------------------------------------------------------ the bar

    def testDropAboveTheBarComputes(self):
        """Rolled back after PadA, Body1's held boss dropped above the bar (the bar after it, as
        the list shows it) computes; Body2 stays held."""
        self.twoParts()
        PartDesign.rollStudioTo(self.doc, self.padA)
        self.doc.recompute()
        PartDesign.moveInStudio(self.doc, [self.skA2, self.padA2], self.padA, self.padA2)
        self.assertEqual(self.order(), ["SkA", "PadA", "SkA2", "PadA2", "SkC", "PadC"])
        self.assertEqual(self.names((self.body1.Tip, self.body2.Tip)), ["PadA2", None])
        self.doc.recompute()
        self.assertAlmostEqual(self.body1.Shape.Volume, 500 + 32, places=3)

    def testDropBelowTheBarIsHeld(self):
        """Rolled back after PadA, PadA dropped below the bar (after Body2's Pad): Body1 is
        rolled back to its top, so PadA and the boss are held."""
        self.twoParts()
        PartDesign.rollStudioTo(self.doc, self.padA)
        self.doc.recompute()
        PartDesign.moveInStudio(self.doc, self.padA, self.padC, self.skA)
        self.assertEqual(self.order(), ["SkA", "SkC", "PadC", "PadA", "SkA2", "PadA2"])
        self.assertEqual(self.names((self.body1.Tip, self.body2.Tip)), [None, None])
        self.assertTrue(PartDesign.isStudioRolledBack(self.doc))
        PartDesign.rollStudioToEnd(self.doc)
        self.checkVolumes(500 + 32, 400)

    def testTheBarStaysAfterItsRow(self):
        """Without a bar given, it stays after the row it followed (PadA: Body2's sketch waits
        below it with its Pad, ops#640 rank 34): rows dropped below it are held."""
        self.twoParts()
        PartDesign.rollStudioTo(self.doc, self.padA)
        self.doc.recompute()
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "PadA")
        PartDesign.moveInStudio(self.doc, [self.skA2, self.padA2], self.skC)
        self.assertEqual(self.order(), ["SkA", "PadA", "SkC", "SkA2", "PadA2", "PadC"])
        self.assertEqual(self.names((self.body1.Tip, self.body2.Tip)), ["PadA", None])

    # --------------------------------------------------------------------------- refusals

    def testDropAboveWhatItReadsIsRefused(self):
        """In TestStudioSequence's interleaved model Pocket1 (Body1) reads Body2's sketch SkB and
        Box (Body2) sits on Body1's PadA. Drops that would put a reader above what it reads, or
        what is read below its reader, are refused, naming both, and nothing changes."""
        model = TestStudioSequence("testInterleavedOrder")
        model.doc = self.doc
        model.interleaved()
        before = self.order()
        with self.assertRaisesRegex(ValueError, "'Pocket1' uses 'SkB' of 'Body2'"):
            PartDesign.moveInStudio(self.doc, model.pocket1, model.padA)
        with self.assertRaisesRegex(ValueError, "'Box' uses 'PadA' of 'Body1'"):
            PartDesign.moveInStudio(self.doc, model.box, None)
        with self.assertRaisesRegex(ValueError, "'Box' of 'Body2' uses 'PadA'"):
            PartDesign.moveInStudio(self.doc, model.padA, model.box)
        self.assertEqual(self.order(), before)
        self.assertEqual(self.names(model.body1.Group), ["SkA", "PadA", "Pocket1"])
        self.assertEqual(self.ranked(), [])
        model.checkEnd()

    def testDropBelowAWholeBodyReaderIsRefused(self):
        """Review prlocal632-r1 T1: Body2's binder reads Body1 whole, as its last solid. Body1's
        block dropped below the binder would become Body1's last solid, read by the binder above
        it: refused, naming both (before: accepted, and the list put the block back)."""
        self.twoParts()
        binder = self.body2.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(self.body1, "")]
        self.doc.recompute()
        self.assertEqual(self.order()[-1], "Binder")
        with self.assertRaisesRegex(ValueError, "'Binder' of 'Body2' uses 'PadA'"):
            PartDesign.moveInStudio(self.doc, self.padA, binder)
        self.assertEqual(self.names(self.body1.Group), ["SkA", "PadA", "SkA2", "PadA2"])
        self.assertEqual(self.ranked(), [])
        # Below the binder as its last solid, Body1's boss can't go either; above it, it can
        with self.assertRaisesRegex(ValueError, "'Binder' of 'Body2' uses 'PadA2'"):
            PartDesign.moveInStudio(self.doc, [self.skA2, self.padA2], binder)
        self.assertTrue(PartDesign.moveInStudio(self.doc, [self.skC, self.padC], None))

    def testCopyIsListedAsTheNewest(self):
        """Reviews prlocal632-r1 T3 and r1s 1: a copied Body's features don't keep their sources'
        saved places: they are listed after every row, as the newest."""
        self.twoParts()
        PartDesign.moveInStudio(self.doc, [self.skC, self.padC], None)
        dragged = self.order()
        copy = self.doc.copyObject(self.body1, True)
        self.doc.recompute()
        self.assertEqual(self.order()[: len(dragged)], dragged)
        self.assertEqual(self.order()[len(dragged):], self.names(copy.Group))
        self.assertTrue(all("HistoryRank" not in o.PropertiesList for o in copy.Group))

    def testRefusals(self):
        self.twoParts()
        with self.assertRaisesRegex(ValueError, "one part at a time"):
            PartDesign.moveInStudio(self.doc, [self.padA2, self.padC], None)
        with self.assertRaises(ValueError):
            PartDesign.moveInStudio(self.doc, self.body1.Origin.OriginFeatures[0], None)
        stray = self.doc.addObject("Part::Box", "Stray")
        with self.assertRaises(ValueError):
            PartDesign.moveInStudio(self.doc, self.padC, stray)
        with self.assertRaises(TypeError):
            PartDesign.moveInStudio(self.doc, 3, None)
        self.assertEqual(self.ranked(), [])

    # ------------------------------------------------- a face traced back (report 16, ops#647)

    def filletedBlock(self):
        """Made in this order: Body1's sketch and Pad (a 20x10x5 block at the origin) and a Fillet
        (radius 1) of the block's top edge along y = 0, which trims the top face to y >= 1; Body2's
        sketch on that trimmed top face (a 4x4 square at x, y = 4..8) and a Pad of 2 from it."""
        doc = self.doc
        self.body1 = doc.addObject("PartDesign::Body", "Body1")
        self.body2 = doc.addObject("PartDesign::Body", "Body2")
        self.skA = sketch(self.body1, "SkA", (0, 0, 20, 10))
        self.padA = self.pad(self.body1, "PadA", self.skA, 5)
        doc.recompute()
        edge = next(
            f"Edge{i}"
            for i, e in enumerate(self.padA.Shape.Edges, 1)
            if all(abs(v.Point.z - 5) < 1e-9 and abs(v.Point.y) < 1e-9 for v in e.Vertexes)
        )
        self.fillet = self.body1.newObject("PartDesign::Fillet", "Fillet")
        self.fillet.Base = (self.padA, [edge])
        self.fillet.Radius = 1
        self.body1.Tip = self.fillet
        doc.recompute()
        self.top = faceAt(self.fillet, 5)
        self.assertIsNotNone(self.top)
        self.skF = sketch(self.body2, "SkF", (4, 4, 8, 8), support=[(self.fillet, self.top)])
        self.padF = self.pad(self.body2, "PadF", self.skF, 2)
        doc.recompute()
        self.assertEqual(self.order(), ["SkA", "PadA", "Fillet", "SkF", "PadF"])
        self.filletVolume = self.body1.Shape.Volume
        self.assertLess(self.filletVolume, 1000)
        self.checkVolumes(self.filletVolume, 32)

    def testSketchOnAFilletedFaceGoesAboveTheFillet(self):
        """Report 16: Body2's sketch sits on the block's top face, which the Fillet only trimmed.
        Dragged above the Fillet (with its Pad) it is put on the Pad's top face, the face the
        Fillet trimmed, as Onshape traces the face to the feature that made it: the drop is
        accepted, nothing moves or fails, and it is one undo step."""
        self.filletedBlock()
        count = self.doc.UndoCount
        self.doc.openTransaction("Reorder")
        self.assertTrue(PartDesign.moveInStudio(self.doc, [self.skF, self.padF], self.padA))
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(self.order(), ["SkA", "PadA", "SkF", "PadF", "Fillet"])
        support = self.skF.AttachmentSupport
        self.assertEqual(len(support), 1)
        self.assertIs(support[0][0], self.padA)
        self.assertEqual(support[0][1], (faceAt(self.padA, 5),))
        self.assertAlmostEqual(self.skF.Placement.Base.z, 5, places=9)
        self.checkVolumes(self.filletVolume, 32)
        self.assertAlmostEqual(self.padF.Shape.BoundBox.ZMax, 7, places=6)
        # One undo step: back on the Fillet's face
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertIs(self.skF.AttachmentSupport[0][0], self.fillet)
        self.assertEqual(self.order(), ["SkA", "PadA", "Fillet", "SkF", "PadF"])
        self.checkVolumes(self.filletVolume, 32)

    def testTheFilletIsDroppedBelowTheSketchOnItsFace(self):
        """The same read, the other way: the Fillet dragged below Body2's Pad. The sketch is put
        on the Pad's face and stays where it is."""
        self.filletedBlock()
        self.assertTrue(PartDesign.moveInStudio(self.doc, self.fillet, self.padF))
        self.doc.recompute()
        self.assertEqual(self.order(), ["SkA", "PadA", "SkF", "PadF", "Fillet"])
        self.assertIs(self.skF.AttachmentSupport[0][0], self.padA)
        self.checkVolumes(self.filletVolume, 32)

    def testAnEdgeTheFilletMadeIsStillRefused(self):
        """A reference with no earlier version still refuses the drop, writing nothing: a Body2
        sketch normal to the Fillet's tangent edge on the top face (y = 1), an edge the Fillet
        generated from the sharp edge (y = 0), which is another line."""
        self.filletedBlock()
        tangent = next(
            f"Edge{i}"
            for i, e in enumerate(self.fillet.Shape.Edges, 1)
            if all(abs(v.Point.z - 5) < 1e-9 and abs(v.Point.y - 1) < 1e-9 for v in e.Vertexes)
        )
        skE = sketch(self.body2, "SkE", (0, 0, 1, 1), support=[(self.fillet, tangent)])
        skE.MapMode = "NormalToEdge"
        self.doc.recompute()
        self.assertTrue(skE.isValid())
        before = self.order()
        with self.assertRaisesRegex(ValueError, "'SkE' uses 'Fillet' of 'Body1'"):
            PartDesign.moveInStudio(self.doc, skE, self.padA)
        self.assertEqual(self.order(), before)
        self.assertIs(skE.AttachmentSupport[0][0], self.fillet)
        self.assertIs(self.skF.AttachmentSupport[0][0], self.fillet)
        self.assertEqual(self.ranked(), [])

    def testAPatternCopysFaceIsRefused(self):
        """Review sff13-r1 (Opus T1): a pattern copy's top face lies in the original's plane but
        elsewhere; it has no earlier version. Body2's datum point at its centre, dragged above the
        pattern, is refused (before: it went to the original's face, 20 mm away, silently)."""
        doc = self.doc
        self.body1 = doc.addObject("PartDesign::Body", "Body1")
        self.body2 = doc.addObject("PartDesign::Body", "Body2")
        plate = self.pad(self.body1, "Plate", sketch(self.body1, "SkPlate", (0, 0, 30, 10)), 2)
        boss = self.pad(self.body1, "Boss", sketch(self.body1, "SkBoss", (0, 2, 10, 8), z=2), 3)
        doc.recompute()
        pattern = self.body1.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [boss]
        pattern.Direction = (self.body1.Origin.OriginFeatures[0], [""])
        pattern.Mode = "Spacing"
        pattern.Offset = 20
        pattern.Occurrences = 2
        self.body1.Tip = pattern
        doc.recompute()
        self.assertTrue(pattern.isValid())
        copyTop = next(
            f"Face{i}"
            for i, f in enumerate(pattern.Shape.Faces, 1)
            if abs(f.CenterOfMass.z - 5) < 1e-9 and abs(f.CenterOfMass.x - 25) < 1e-9
        )
        point = self.body2.newObject("PartDesign::Point", "PointCopy")
        point.AttachmentSupport = [(pattern, copyTop)]
        point.MapMode = "CenterOfMass"
        doc.recompute()
        self.assertAlmostEqual(point.Placement.Base.x, 25, places=6)
        with self.assertRaisesRegex(ValueError, "'PointCopy' uses 'Pattern' of 'Body1'"):
            PartDesign.moveInStudio(doc, point, boss)
        self.assertIs(point.AttachmentSupport[0][0], pattern)
        self.assertEqual(self.ranked(), [])
        self.assertIsNotNone(plate)

    def testAnEdgeTheFilletTrimmedIsStillRefused(self):
        """Review sff13-r1 (Sonnet rl1): the top edge at x = 0 runs y = 0..10 on the Pad and
        y = 1..10 after the Fillet, on the same line. A sketch normal to it starts at its first
        point, so on the Pad's edge it would move by 1: the drop is refused, writing nothing."""
        self.filletedBlock()
        trimmed = next(
            f"Edge{i}"
            for i, e in enumerate(self.fillet.Shape.Edges, 1)
            if all(abs(v.Point.z - 5) < 1e-9 and abs(v.Point.x) < 1e-9 for v in e.Vertexes)
            and abs(e.Length - 9) < 1e-9
        )
        skT = sketch(self.body2, "SkT", (0, 0, 1, 1), support=[(self.fillet, trimmed)])
        skT.MapMode = "NormalToEdge"
        self.doc.recompute()
        self.assertTrue(skT.isValid())
        with self.assertRaisesRegex(ValueError, "'SkT' uses 'Fillet' of 'Body1'"):
            PartDesign.moveInStudio(self.doc, skT, self.padA)
        self.assertIs(skT.AttachmentSupport[0][0], self.fillet)
        self.assertEqual(self.ranked(), [])
