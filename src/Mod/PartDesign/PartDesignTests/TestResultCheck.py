# SPDX-License-Identifier: LGPL-2.1-or-later

"""The check of each solid feature's result (FreeCAD-CH kernel safety S2, ResultCheck.h).

OCCT can build an invalid solid, or a valid one of the wrong volume, without an error, and the
next features built on it silently. Each case here was measured on fork-0.9.0 (notes
kernel-robustness.md, probe 4): an inverted base, a revolve about an axis tangent to its profile
(a horn torus, which OCCT's fuse with the plate leaves invalid) followed by a pocket that adds
volume, and a whole-sketch pad of two overlapping squares (a solid of volume 0). Now the feature
that makes the wrong result fails, and the ones after it build on its base. A set of ordinary
features must not be flagged. Designed geometry; expected volumes are closed forms.
"""

import math
import unittest

import FreeCAD
import Part

V = FreeCAD.Vector
PARAMS = "User parameter:BaseApp/Preferences/Mod/PartDesign"


def disk(x, y, r, z):
    return Part.Face(Part.Wire(Part.makeCircle(r, V(x, y, z))))


def rect(x0, y0, x1, y1, z):
    return Part.Face(
        Part.makePolygon([V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z), V(x0, y0, z)])
    )


def mid(edge):
    return edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))


class TestResultCheck(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("ResultCheck")
        self.params = FreeCAD.ParamGet(PARAMS)

    def tearDown(self):
        self.params.RemBool("CheckResults")
        FreeCAD.closeDocument(self.doc.Name)

    def body(self, base_shape=None):
        body = self.doc.addObject("PartDesign::Body", "Body")
        if base_shape is not None:
            base = self.doc.addObject("Part::Feature", "Base")
            base.Shape = base_shape
            body.BaseFeature = base
        return body

    def profile(self, shape, name="Profile"):
        prof = self.doc.addObject("Part::Feature", name)
        prof.Shape = shape
        return prof

    def pocket(self, body, face, name="Pocket"):
        p = body.newObject("PartDesign::Pocket", name)
        p.Profile = (self.profile(face, name + "Profile"), ["Face1"])
        p.Type = "ThroughAll"
        return p

    def pad(self, body, face, length, name="Pad"):
        p = body.newObject("PartDesign::Pad", name)
        p.Profile = (self.profile(face, name + "Profile"), ["Face1"])
        p.Length = length
        return p

    def assertBuilt(self, feature):
        self.assertTrue(feature.isValid(), "%s: %s" % (feature.Name, feature.getStatusString()))
        self.assertNotIn("Touched", feature.State, feature.Name)
        self.assertFalse(feature.Shape.isNull(), feature.Name)

    def origin(self, body, role):
        return [o for o in body.Origin.OriginFeatures if o.Role == role][0]

    def testInvertedBaseFailsItsFirstFeature(self):
        body = self.body(Part.makeBox(40, 30, 10).reversed())
        pocket = self.pocket(body, disk(20, 15, 4, 10))
        self.doc.recompute()
        self.assertFalse(pocket.isValid())
        self.assertIn("turned inside out", pocket.getStatusString())

    def testHornTorusRevolveBuildsAndThePocketAfterIt(self):
        """A circle r 3 tangent to the axis, a full turn: a horn torus whose lower half lies in the
        box. It failed as an invalid shape (the pocket then built on the base) until the revolve
        put a vertex at the touch (P4, ops#640); it is exact now. The torus adds its upper half,
        pi^2 R r^2; the pocket, a rod r 1 about the axis, takes the box's 4 pi and the torus's part
        within 1 of the axis above the box, the integral of 2 pi rho sqrt(9 - (rho - 3)^2)."""
        body = self.body(Part.makeBox(40, 40, 4))
        circle = Part.Circle(V(23, 20, 4), V(0, 1, 0), 3)
        prof = self.profile(Part.Face(Part.Wire(circle.toShape())), "RevProfile")
        axis = self.doc.addObject("Part::Feature", "Axis")
        axis.Shape = Part.makeLine(V(20, 20, -5), V(20, 20, 15))
        rev = body.newObject("PartDesign::Revolution", "Revolution")
        rev.Profile = (prof, ["Face1"])
        rev.ReferenceAxis = (axis, ["Edge1"])
        rev.Angle = 360
        pocket = self.pocket(body, disk(20, 20, 1.0, 10), "PocketAxis")
        self.doc.recompute()
        self.assertTrue(rev.isValid(), rev.getStatusString())
        # within 1e-7 relative: OCCT's integration on the torus face (2e-8 seen)
        self.assertAlmostEqual(rev.Shape.Volume, 6400 + math.pi**2 * 3 * 9, delta=7e-4)
        # Fork-0.9.0: the pocket was "Valid" with volume 6920.4, more than the 6708.9 before it
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        n = 2000  # Simpson's rule over rho in [0, 1]

        def ring(rho):
            return 2 * math.pi * rho * math.sqrt(9 - (rho - 3) ** 2)

        inner = sum(
            (1 if k in (0, n) else 4 if k % 2 else 2) * ring(k / n) for k in range(n + 1)
        ) / (3 * n)
        self.assertAlmostEqual(
            pocket.Shape.Volume, 6400 + math.pi**2 * 27 - math.pi * 4 - inner, delta=7e-4
        )
        self.assertTrue(pocket.Shape.isValid())

    def revolveSketch(self, body, geometry, angle):
        sketch = body.newObject("Sketcher::SketchObject", "RevSketch")
        sketch.Placement = FreeCAD.Placement(V(0, 0, 0), FreeCAD.Rotation(V(1, 0, 0), 90))
        for g in geometry:
            sketch.addGeometry(g)
        rev = body.newObject("PartDesign::Revolution", "Revolution")
        rev.Profile = sketch
        rev.ReferenceAxis = (sketch, ["V_Axis"])
        rev.Angle = angle
        return rev

    def testHornTorusRevolveWithoutBaseBuilds(self):
        """The horn torus as the Body's first feature, from a sketch: a circle r 3 tangent to the
        sketch's V axis, a full turn, 2 pi^2 R r^2 with R = r = 3 (Onshape's RV1 builds it). The
        seated profile (P4) turned a sketch face's Reversed wire twice: the face's area came out
        negative, the solid inside out, and S2 stopped it (F1, kernel-8, ops#640)."""
        body = self.body()
        rev = self.revolveSketch(body, [Part.Circle(V(3, 4, 0), V(0, 0, 1), 3)], 360)
        self.doc.recompute()
        self.assertBuilt(rev)
        self.assertAlmostEqual(rev.Shape.Volume, 2 * math.pi**2 * 3 * 9, delta=1e-6 * 533)
        self.assertTrue(rev.Shape.isValid())

    def testHalfDiscTouchingTheAxisRevolvesWithoutBase(self):
        """A D (the left half of a circle r 100 centred (100, 0), closed by the line x = 100) touches
        the axis at the arc's middle; revolved without a base it builds at 360, 180 and 120 degrees,
        V by Pappus (half disc area times its centroid's path), and the 180-degree end caps have the
        half disc's positive area (F1: they were turned inside out)."""
        r = 100.0
        area = math.pi * r * r / 2
        centroid = r - 4 * r / (3 * math.pi)
        for angle in (360, 180, 120):
            body = self.body()
            arc = Part.ArcOfCircle(Part.Circle(V(r, 0, 0), V(0, 0, 1), r), math.pi / 2, 1.5 * math.pi)
            rev = self.revolveSketch(body, [arc, Part.LineSegment(V(r, -r, 0), V(r, r, 0))], angle)
            self.doc.recompute()
            self.assertBuilt(rev)
            shape = rev.Shape
            self.assertTrue(shape.isValid(), angle)
            expected = area * centroid * math.radians(angle)
            self.assertAlmostEqual(shape.Volume, expected, delta=1e-7 * expected)
            for f in shape.Faces:
                self.assertGreater(f.Area, 0, (angle, f.Surface))
            if angle < 360:
                caps = [f for f in shape.Faces if isinstance(f.Surface, Part.Plane)]
                self.assertEqual(len(caps), 2, angle)
                for cap in caps:
                    self.assertAlmostEqual(cap.Area, area, delta=1e-7 * area)

    def testOverlappingSquaresPadOfNoVolumeFails(self):
        body = self.body()
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        for x0, y0, x1, y1 in ((0, 0, 10, 10), (5, 5, 15, 15)):
            pts = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
            for a, b in zip(pts, pts[1:] + pts[:1]):
                sketch.addGeometry(Part.LineSegment(a, b))
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 2
        self.doc.recompute()
        if pad.isValid():
            # A face maker that reads the squares right gives 2 x 175 (Onshape's all regions)
            self.assertAlmostEqual(pad.Shape.Volume, 350, places=6)
        else:
            self.assertIn("no volume", pad.getStatusString())

    def testTheCheckCanBeTurnedOff(self):
        self.params.SetBool("CheckResults", False)
        body = self.body(Part.makeBox(40, 30, 10).reversed())
        pocket = self.pocket(body, disk(20, 15, 4, 10))
        self.doc.recompute()
        self.assertTrue(pocket.isValid())

    def testOrdinaryFeaturesPass(self):
        body = self.body(Part.makeBox(100, 60, 10))
        feats = []
        feats.append(self.pocket(body, disk(10, 10, 3, 10), "Hole1"))
        feats.append(self.pad(body, disk(30, 30, 5, 10), 6, "Boss"))
        miss = self.pocket(body, disk(300, 300, 3, 10), "Miss")
        feats.append(miss)
        feats.append(self.pocket(body, rect(48, -1, 52, 61, 10), "Slot"))  # splits it in two
        feats.append(self.pad(body, rect(70, 20, 90, 40, 10), 3, "Block"))
        lp = self.doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        lp.Originals = [feats[0]]
        lp.Direction = (self.origin(body, "Y_Axis"), [""])
        lp.Length = 30
        lp.Occurrences = 3
        body.addObject(lp)
        feats.append(lp)
        mirror = self.doc.addObject("PartDesign::Mirrored", "Mirrored")
        mirror.Originals = [feats[0]]
        mirror.MirrorPlane = (self.origin(body, "XZ_Plane"), [""])
        body.addObject(mirror)
        feats.append(mirror)
        polar = self.doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        polar.Originals = [feats[1]]
        polar.Axis = (self.origin(body, "Z_Axis"), [""])
        polar.Angle = 20
        polar.Occurrences = 2
        body.addObject(polar)
        feats.append(polar)
        self.doc.recompute()
        for f in feats:
            self.assertBuilt(f)
        # Dress-ups on the block's top edges, then a revolve and a groove
        prev = feats[-1]
        top = [
            "Edge%d" % (i + 1)
            for i, e in enumerate(prev.Shape.Edges)
            if abs(mid(e).z - 13) < 1e-6
            and 70 - 1e-6 < mid(e).x < 90 + 1e-6
            and 20 - 1e-6 < mid(e).y < 40 + 1e-6
        ]
        self.assertEqual(len(top), 4)
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (prev, top[:2])
        fillet.Radius = 1
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (prev, top[2:])
        chamfer.Size = 0.5
        self.doc.recompute()
        self.assertBuilt(fillet)
        self.assertBuilt(chamfer)
        axis = self.doc.addObject("Part::Feature", "RevAxis")
        axis.Shape = Part.makeLine(V(20, 50, 0), V(20, 50, 30))
        ring = body.newObject("PartDesign::Revolution", "Ring")
        ring_face = Part.Face(
            Part.makePolygon([V(24, 50, 10), V(26, 50, 10), V(26, 50, 12), V(24, 50, 12), V(24, 50, 10)])
        )
        ring.Profile = (self.profile(ring_face, "RingProfile"), ["Face1"])
        ring.ReferenceAxis = (axis, ["Edge1"])
        ring.Angle = 360
        groove = body.newObject("PartDesign::Groove", "Groove")
        groove_face = Part.Face(
            Part.makePolygon([V(21, 50, 9), V(22, 50, 9), V(22, 50, 11), V(21, 50, 11), V(21, 50, 9)])
        )
        groove.Profile = (self.profile(groove_face, "GrooveProfile"), ["Face1"])
        groove.ReferenceAxis = (axis, ["Edge1"])
        groove.Angle = 360
        box = body.newObject("PartDesign::AdditiveBox", "AddBox")
        box.Length, box.Width, box.Height = 5, 5, 5
        box.AttachmentOffset = FreeCAD.Placement(V(0, 50, 10), FreeCAD.Rotation())
        cyl = body.newObject("PartDesign::SubtractiveCylinder", "SubCyl")
        cyl.Radius, cyl.Height = 1, 30
        cyl.AttachmentOffset = FreeCAD.Placement(V(2.5, 52.5, -5), FreeCAD.Rotation())
        self.doc.recompute()
        for f in (ring, groove, box, cyl):
            self.assertBuilt(f)
        self.assertTrue(body.Shape.isValid())

    def testBlindPocketAndBossPass(self):
        # The volume's change is integrated over the faces that differ only: they must close up
        # (a blind pocket's floor and a boss's top are open faces on their own)
        body = self.body(Part.makeBox(40, 30, 10, V(300, 200, 0)))
        blind = body.newObject("PartDesign::Pocket", "Blind")
        blind.Profile = (self.profile(disk(310, 215, 4, 10), "BlindProfile"), ["Face1"])
        blind.Length = 5
        boss = self.pad(body, disk(330, 215, 3, 10), 7, "Boss")
        self.doc.recompute()
        self.assertBuilt(blind)
        self.assertBuilt(boss)
        self.assertAlmostEqual(blind.Shape.Volume, 12000 - math.pi * 16 * 5, places=6)
        self.assertAlmostEqual(boss.Shape.Volume, 12000 - math.pi * 16 * 5 + math.pi * 9 * 7, places=6)

    def testASmallPartBesideAHugeOnePasses(self):
        body = self.body(
            Part.makeCompound([Part.makeBox(2000, 1000, 1000), Part.makeBox(1, 1, 1, V(3000, 0, 0))])
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = (self.profile(disk(100, 100, 4, 1000)), ["Face1"])
        pocket.Length = 5
        self.doc.recompute()
        for f in body.Group:
            if f.isDerivedFrom("PartDesign::Feature"):
                self.assertBuilt(f)
        self.assertEqual(len(pocket.Shape.Solids), 2)

    def testABaseWithLooseFacesPasses(self):
        loose = Part.Face(
            Part.makePolygon([V(0, 0, 50), V(100, 0, 50), V(100, 100, 50), V(0, 100, 50), V(0, 0, 50)])
        )
        body = self.body(Part.makeCompound([Part.makeBox(10, 10, 10), loose]))
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = (self.profile(disk(5, 5, 2, 10)), ["Face1"])
        pocket.Length = 3
        self.doc.recompute()
        self.assertBuilt(pocket)
        solids = sum(solid.Volume for solid in pocket.Shape.Solids)
        self.assertAlmostEqual(solids, 1000 - math.pi * 4 * 3, places=6)

    def testAPadInsideTheBodyAndARefinedChainPass(self):
        body = self.body(Part.makeBox(40, 40, 10))
        inner = self.pad(body, disk(20, 20, 3, 2), 3, "Inside")  # wholly inside: no change
        feats = [inner]
        for k in range(6):
            p = self.pocket(body, disk(6 + 6 * k, 6, 1.5, 10), "P%d" % k)
            p.Refine = k % 2 == 0
            feats.append(p)
        self.doc.recompute()
        for f in feats:
            self.assertBuilt(f)
        self.assertAlmostEqual(feats[-1].Shape.Volume, 16000 - 6 * math.pi * 2.25 * 10, places=6)

    def testARepairedToolOnAVouchedBasePasses(self):
        """A Boolean whose tool Body is an invalid box (its top reversed), on a base the feature
        vouches for: only the tool is repaired, so the result is checked as any other (the faces it
        made, the direction of the volume's change: kernel-6, debt (a)) and must not be flagged.
        The repaired box is 10 x 10 x 6 with 3 above the plate: Fuse adds 300, Cut takes 300."""
        for kind, change in (("Fuse", 300), ("Cut", -300)):
            body = self.body()
            pad = self.pad(body, rect(0, 0, 40, 30, 0), 10, "Pad%s" % kind)
            hole = self.pocket(body, disk(5, 5, 3, 10), "Hole%s" % kind)
            box = Part.makeBox(10, 10, 6, V(20, 10, 7))
            faces = list(box.Faces)
            faces[5] = faces[5].reversed()
            invalid = Part.Solid(Part.Shell(faces))
            self.assertFalse(invalid.isValid())
            tool = self.doc.addObject("PartDesign::Body", "Tool%s" % kind)
            tool.BaseFeature = self.profile(invalid, "ToolShape%s" % kind)
            boolean = body.newObject("PartDesign::Boolean", kind)
            boolean.Type = kind
            boolean.addObjects([tool])
            self.doc.recompute()
            self.assertBuilt(hole)
            # The base is vouched for: only the tool is checked and repaired
            self.assertFalse(boolean.checksBase())
            self.assertBuilt(boolean)
            before = 12000 - math.pi * 9 * 10
            self.assertAlmostEqual(hole.Shape.Volume, before, places=6)
            self.assertAlmostEqual(boolean.Shape.Volume, before + change, places=6)
            self.assertTrue(boolean.Shape.isValid())


if __name__ == "__main__":
    unittest.main()
