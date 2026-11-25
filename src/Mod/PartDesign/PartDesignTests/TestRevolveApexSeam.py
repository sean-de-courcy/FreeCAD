# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#1048)

"""A full revolve or groove whose cone has its apex on a cylinder wall, a round-off away from the
wall's seam, is right or fails loudly, never a silent wrong result.

OCCT finds no intersection between a cone and a cylinder when the cone's apex lies within 1e-12 to
1e-7 of the cylinder's seam line, on the side where the apex's u is just under 2 pi
(notes/kernel-robustness.md section 35). The fuse then added the whole cone over the base, or
nothing; the cut removed nothing; all Up-to-date.

Designed geometry, each model built by the test:
- Base: a cylinder of radius R = 10 about Z, z 0..6. Its seam is the line x = 10, y = 0.
- Triangle: in the plane y = delta, A = (10, delta, 2) and A0 = (10, delta, 5) on the wall, T = (12,
  delta, 5) outward at A0's height. Turned a full turn about A-A0, it is a cone of height 3 and base
  radius 2 with its apex A on the wall.
- Expected, geometric: the cone's part outside the cylinder is V_out, the integral over z of the
  area of a disc of radius r(z) = 2 (z - 2) / 3 centred on the wall, outside the circle of radius
  10 (Simpson, 20000 steps: 6.483319). A Revolution adds V_out; a Groove of the same triangle (the
  same cone) removes the cone's part inside, 4 pi - V_out.
- Fin: the base also carries a wedge behind the triangle (y from delta - 3 to delta), whose cap in
  the plane y = delta is the triangle widened 1 into the wall; the cap is the profile, its flank a
  line (or a degree-1 B-spline, which ops#768 rebuilds as a line). The wedge and the cylinder hold
  the cone's half y < delta, so the Revolution adds V_out / 2.
delta 0 is on the seam; -1e-9 and -1e-10 are in OCCT's window; +1e-9 and -1e-6 outside it; the
quarter-turn controls put the apex at (0, 10) on the wall, far from the seam.
"""

import math
import unittest

import FreeCAD as App
import Part

V = App.Vector
R, H = 10.0, 6.0
Z0, HC, W = 2.0, 3.0, 2.0


def outsideVolume(n=20000):
    """V_out: the cone's part outside the cylinder (Simpson's rule over z)."""

    def outArea(r):
        if r <= 0:
            return 0.0
        lens = (
            r * r * math.acos(r / (2 * R))
            + R * R * math.acos(1 - r * r / (2 * R * R))
            - 0.5 * r * math.sqrt(4 * R * R - r * r)
        )
        return math.pi * r * r - lens

    h = HC / n
    return (
        h
        / 3
        * sum((1 if i in (0, n) else 4 if i % 2 else 2) * outArea(W * i / n) for i in range(n + 1))
    )


V_OUT = outsideVolume()
CONE = math.pi * W * W * HC / 3


def turned(point, quarter):
    """The point turned a quarter turn about Z when asked (the apex moved off the seam)."""
    return App.Rotation(V(0, 0, 1), 90 if quarter else 0).multVec(point)


class TestRevolveApexSeam(unittest.TestCase):
    def setUp(self):
        self.opened = []

    def tearDown(self):
        docs = App.listDocuments()
        for name in self.opened:
            if name in docs:
                App.closeDocument(name)

    def newDoc(self):
        """A fresh document per model"""
        doc = App.newDocument("TestRevolveApexSeam")
        self.opened.append(doc.Name)
        return doc

    def checkResult(self, feature, baseVolume, expected, label):
        """Right within 1e-6 of the base, or failed loudly; never a wrong Up-to-date result."""
        if not feature.isValid():
            return "loud"
        self.assertFalse(feature.Shape.isNull(), label)
        self.assertTrue(feature.Shape.isValid(), label)
        self.assertEqual(len(feature.Shape.Solids), 1, label)
        change = feature.Shape.Volume - baseVolume
        self.assertAlmostEqual(change, expected, delta=1e-6 * baseVolume, msg=label)
        return "right"

    def sketchModel(self, delta, groove=False, quarter=False):
        doc = self.newDoc()
        body = doc.addObject("PartDesign::Body", "Body")
        circle = body.newObject("Sketcher::SketchObject", "Circle")
        circle.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        circle.MapMode = "FlatFace"
        circle.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), R))
        doc.recompute()
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = circle
        pad.Length = H
        doc.recompute()
        baseVolume = pad.Shape.Volume
        tri = body.newObject("Sketcher::SketchObject", "Tri")
        # sketch x along x, sketch y along z, in the plane y = delta (turned with the apex)
        tri.Placement = App.Placement(
            turned(V(0, delta, 0), quarter),
            App.Rotation(V(0, 0, 1), 90 if quarter else 0).multiply(App.Rotation(V(1, 0, 0), 90)),
        )
        points = [V(R, Z0, 0), V(R, Z0 + HC, 0), V(R + W, Z0 + HC, 0)]
        for i in range(3):
            tri.addGeometry(Part.LineSegment(points[i], points[(i + 1) % 3]))
        doc.recompute()
        rev = body.newObject("PartDesign::Groove" if groove else "PartDesign::Revolution", "Rev")
        rev.Profile = tri
        rev.ReferenceAxis = (tri, ["Edge1"])
        rev.Angle = 360
        doc.recompute()
        expected = -(CONE - V_OUT) if groove else V_OUT
        return rev, baseVolume, expected

    def finModel(self, delta, bspline):
        doc = self.newDoc()
        slope = HC / W
        P = [V(R - 1, delta, Z0 - slope), V(R + W, delta, Z0 + HC), V(R - 1, delta, Z0 + HC)]
        flank = Part.LineSegment(P[0], P[1])
        edges = [
            flank.toBSpline().toShape() if bspline else flank.toShape(),
            Part.LineSegment(P[1], P[2]).toShape(),
            Part.LineSegment(P[2], P[0]).toShape(),
        ]
        wedge = Part.Face(Part.Wire(edges)).extrude(V(0, -3.0, 0))
        base = Part.makeCylinder(R, H).fuse(wedge)
        feature = doc.addObject("Part::Feature", "Base")
        feature.Shape = base
        body = doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = feature
        doc.recompute()
        tip = body.Tip
        shape = tip.Shape
        caps = [
            i
            for i, f in enumerate(shape.Faces)
            if f.Surface.__class__.__name__ == "Plane"
            and abs(f.BoundBox.YMax - delta) < 1e-6
            and abs(f.BoundBox.YMin - delta) < 1e-6
        ]
        ends = [
            j
            for j, v in enumerate(shape.Vertexes)
            if abs(v.Point.x - R) < 1e-6
            and abs(v.Point.y - delta) < 1e-6
            and (abs(v.Point.z - Z0) < 1e-6 or abs(v.Point.z - Z0 - HC) < 1e-6)
        ]
        self.assertEqual(len(caps), 1)
        self.assertEqual(len(ends), 2)
        axis = body.newObject("PartDesign::Line", "Axis")
        axis.AttachmentSupport = [
            (tip, "Vertex%d" % (ends[0] + 1)),
            (tip, "Vertex%d" % (ends[1] + 1)),
        ]
        axis.MapMode = "TwoPointLine"
        rev = body.newObject("PartDesign::Revolution", "Rev")
        rev.Profile = (tip, ["Face%d" % (caps[0] + 1)])
        rev.ReferenceAxis = (axis, [""])
        rev.Angle = 360
        doc.recompute()
        return rev, base.Volume, V_OUT / 2

    def coneGrooveModel(self, delta):
        """Review r1: a Groove of the same triangle on a conical base, cone Part.makeCone(10, 6,
        6), whose wall leans in at atan(4 / 6), the tool's half angle: the tool lies outside and
        touches the wall along one line, so it removes nothing."""
        doc = self.newDoc()
        base = Part.makeCone(10, 6, 6)
        feature = doc.addObject("Part::Feature", "Base")
        feature.Shape = base
        body = doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = feature
        doc.recompute()
        r = 10 - 4 * Z0 / 6
        xa = math.sqrt(r * r - delta * delta)
        tri = body.newObject("Sketcher::SketchObject", "Tri")
        tri.Placement = App.Placement(V(0, delta, 0), App.Rotation(V(1, 0, 0), 90))
        points = [V(xa, Z0, 0), V(xa, Z0 + HC, 0), V(xa + W, Z0 + HC, 0)]
        for i in range(3):
            tri.addGeometry(Part.LineSegment(points[i], points[(i + 1) % 3]))
        doc.recompute()
        groove = body.newObject("PartDesign::Groove", "Groove")
        groove.Profile = tri
        groove.ReferenceAxis = (tri, ["Edge1"])
        groove.Angle = 360
        doc.recompute()
        return groove, base.Volume, 0.0

    def testGrooveTangentToConeWallAtSeam(self):
        """Review r1: removes nothing and stays one valid solid (the point check refused it, and
        the retry left two sliver faces, Up-to-date)."""
        for delta in (0.0, -1e-10, -1e-9, 1e-9):
            groove, base, expected = self.coneGrooveModel(delta)
            label = "cone groove delta %g" % delta
            self.assertEqual(self.checkResult(groove, base, expected, label), "right", label)

    def testExpectedVolumes(self):
        """The geometric expectations themselves: V_out lies between 0 and the cone."""
        self.assertAlmostEqual(V_OUT, 6.483319, places=5)
        self.assertGreater(CONE - V_OUT, 0)

    def testSketchRevolutionApexBesideSeam(self):
        """A sketch triangle's cone, apex in OCCT's window: adds V_out, not the whole cone."""
        for delta in (-1e-9, -1e-10):
            rev, base, expected = self.sketchModel(delta)
            self.assertEqual(self.checkResult(rev, base, expected, "delta %g" % delta), "right")

    def testSketchGrooveApexBesideSeam(self):
        """The same cone as a Groove removes its part inside the wall, not nothing."""
        for delta in (-1e-9, -1e-10):
            rev, base, expected = self.sketchModel(delta, groove=True)
            self.assertEqual(
                self.checkResult(rev, base, expected, "groove delta %g" % delta), "right"
            )

    def testFinRevolutionApexBesideSeam(self):
        """A wedge's cap revolved, apex in OCCT's window (the real row's shape): adds V_out / 2."""
        for delta, bspline in ((-1e-9, False), (-1e-10, False), (-1e-10, True), (-1e-9, True)):
            rev, base, expected = self.finModel(delta, bspline)
            label = "fin %s delta %g" % ("bspline" if bspline else "line", delta)
            self.assertEqual(self.checkResult(rev, base, expected, label), "right")

    def testControlsUnchanged(self):
        """Apex on the seam, outside OCCT's window, or a quarter turn away: right, as before."""
        cases = []
        for delta in (0.0, 1e-9, -1e-6):
            cases.append(("sketch delta %g" % delta, self.sketchModel, (delta,), {}))
            cases.append(("groove delta %g" % delta, self.sketchModel, (delta,), {"groove": True}))
            cases.append(("fin line delta %g" % delta, self.finModel, (delta, False), {}))
            cases.append(("fin bspline delta %g" % delta, self.finModel, (delta, True), {}))
        for delta in (0.0, -1e-9):
            cases.append(
                ("quarter delta %g" % delta, self.sketchModel, (delta,), {"quarter": True})
            )
            cases.append(
                (
                    "quarter groove delta %g" % delta,
                    self.sketchModel,
                    (delta,),
                    {"groove": True, "quarter": True},
                )
            )
        for label, build, args, kwargs in cases:
            rev, base, expected = build(*args, **kwargs)
            self.assertEqual(self.checkResult(rev, base, expected, label), "right", label)


if __name__ == "__main__":
    unittest.main()
