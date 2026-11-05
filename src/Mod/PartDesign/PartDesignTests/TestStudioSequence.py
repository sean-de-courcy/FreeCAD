# SPDX-License-Identifier: LGPL-2.1-or-later

"""B+ Stage 2 (ops#602): the studio's feature list and its one roll-back bar.

PartDesign.studioSequence lists every member of a studio's Bodies in history order (after what it
reads in other Bodies and after its Body's earlier members, the oldest first where that leaves a
choice); rollStudioTo moves every Body's bar to one point of that list. The Features dock shows
both (notes/features-dock-design.md). Every model is designed: the expected shapes come from
volumes.
"""

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
            binder.setExpression("Probe", "C.Shape.BoundBox.XMax")
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
        """Without a hint the bar sits before the first held row: a Body2 sketch its Body
        doesn't hold shows above it."""
        self.interleaved()
        PartDesign.rollStudioTo(self.doc, self.box)
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "SkB")
        PartDesign.rollStudioTo(self.doc, None)
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "SkA")
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
