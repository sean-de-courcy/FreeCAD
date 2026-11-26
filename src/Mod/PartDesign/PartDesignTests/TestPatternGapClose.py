# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Pattern copies stay rigid, and a narrow gap between an adding copy and the part is closed
(FreeCAD-CH ops#1041; ops repo notes/pattern-gap-close-1041-design.md, tests C1-C19).

Onshape (RB120, RB143, RB151, RB152, RB156, RB157, RB158): a FEATURE pattern's copy is the seed's
tool moved, never re-derived; with Reapply on, a copy's face that stands at most about 0.00825 off
the part is closed (the gap becomes material), unless that face's edge on the part crosses the wall
reaching more than about 0.0054 outside it or 0.015 inside it. A Remove's copies are never closed.

Designed geometry only (INSTRUCTIONS 19). Two models:
- the tilted post (scripts/repro_1041_tilted_post.py, sk1041's B rows): a flange r 15, a post r 12
  tilted by t degrees, a lens ridge 0.25 high whose flat side is the post's trace at the flange,
  patterned about z;
- model G (RB143): flange r 15, post r 12 about (cx, cy), a lens ridge on the post's +x side whose
  flat side is the post's circle about the origin, patterned twice over 360 (one copy at 180 deg).
Expected gains come from integrators that use no boolean (scripts/repro_1041_refvol.py,
scripts/pattern_gap_1041_vol.py, A(d) of sk1041) and from Onshape's rows."""

import math
import unittest

import FreeCAD as App
import Part

V = App.Vector

# The tilted post (repro_1041_tilted_post.py's defaults)
R, H, RHO, DC = 12.0, 0.25, 1.0, 0.03
FL_R, FL_H, POST_H = 15.0, 2.0, 3.0


def kinds(shape):
    out = {}
    for face in shape.Faces:
        name = type(face.Surface).__name__
        out[name] = out.get(name, 0) + 1
    return out


def xyPlane(body):
    return [o for o in body.Origin.OriginFeatures if o.Role == "XY_Plane"][0]


def planeSketch(body, name, z=0.0, rotation=None, base=None):
    sk = body.newObject("Sketcher::SketchObject", name)
    sk.AttachmentSupport = (xyPlane(body), [""])
    sk.MapMode = "FlatFace"
    sk.AttachmentOffset = App.Placement(base or V(0, 0, z), rotation or App.Rotation())
    return sk


def flange(body, radius=FL_R):
    sk = planeSketch(body, "FlangeSketch")
    sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), radius))
    pad = body.newObject("PartDesign::Pad", "Flange")
    pad.Profile = sk
    pad.Length = FL_H
    return sk, pad


def lensSketch(body, name, small, big, z=FL_H, rotation=None):
    """A lens: the arc of `small` outside `big`, closed by the arc of `big`"""
    pts = sorted(((q.X, q.Y) for q in small.intersect(big)), key=lambda q: q[1])
    assert len(pts) == 2, pts
    lo, hi = V(pts[0][0], pts[0][1], 0), V(pts[1][0], pts[1][1], 0)
    sk = planeSketch(body, name, z)
    sk.addGeometry(Part.ArcOfCircle(small, small.parameter(lo), small.parameter(hi)))
    b0, b1 = big.parameter(lo), big.parameter(hi)
    if b0 > b1:
        b0 -= 2 * math.pi
    if isinstance(big, Part.Ellipse):
        sk.addGeometry(Part.ArcOfEllipse(big, b0, b1))
    else:
        sk.addGeometry(Part.ArcOfCircle(big, b0, b1))
    if rotation is not None:
        sk.AttachmentOffset = App.Placement(V(0, 0, z), rotation)
    return sk


class TestPatternGapClose(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestPatternGapClose")

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestPatternGapClose"):
                App.closeDocument(doc.Name)

    # -- models ----------------------------------------------------------------------------------

    def tiltedPost(self, tilt=2.0, n=40, angle=360.0, refine=True, reapply=True, pocket=False,
                   seedTurn=0.0, post=POST_H, removeToo=False):
        """sk1041's B model: returns (body, ridge, pattern), recomputed"""
        tr = math.radians(tilt)
        off = H * math.tan(tr)
        a = R / math.cos(tr)
        body = self.doc.addObject("PartDesign::Body", "Body")
        sk0, _ = flange(body)
        axis = V(math.sin(tr), 0, math.cos(tr))
        start = V(-off, 0, FL_H) - axis * 1.0
        sk1 = body.newObject("Sketcher::SketchObject", "PostSketch")
        sk1.AttachmentSupport = (xyPlane(body), [""])
        sk1.MapMode = "FlatFace"
        sk1.AttachmentOffset = App.Placement(start, App.Rotation(V(0, 1, 0), tilt))
        sk1.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), R))
        padPost = body.newObject("PartDesign::Pad", "Post")
        padPost.Profile = sk1
        padPost.Length = post + 1.0
        self.doc.recompute()
        ell = Part.Ellipse(V(-off, 0, 0), a, R)
        circ = Part.Circle(V(-off + a - DC, 0, 0), V(0, 0, 1), RHO)
        sk2 = lensSketch(body, "RidgeSketch", circ, ell)
        if pocket:
            # cut 0.25 down into the flange: the floors at z 1.75 (RB148 K1.2)
            ridge = body.newObject("PartDesign::Pocket", "Ridge")
            ridge.Profile = sk2
            ridge.Length = H
        else:
            ridge = body.newObject("PartDesign::Pad", "Ridge")
            ridge.Profile = sk2
            ridge.Length = H
        if seedTurn:
            sk2.AttachmentOffset = App.Placement(V(0, 0, FL_H), App.Rotation(V(0, 0, 1), seedTurn))
        originals = [ridge]
        if removeToo:
            originals.append(self.clearHole(body))
        self.doc.recompute()
        pat = body.newObject("PartDesign::PolarPattern", "Ring")
        pat.Originals = originals
        pat.Axis = (sk2, ["N_Axis"])
        pat.Angle = angle
        pat.Occurrences = n
        pat.Refine = refine
        pat.Reapply = reapply
        body.Tip = pat
        self.doc.recompute()
        return body, ridge, pat

    def clearHole(self, body):
        """A Remove clear of the ridges: a small hole through the flange near the axis"""
        sk = planeSketch(body, "HoleSketch")
        sk.addGeometry(Part.Circle(V(6, 0, 0), V(0, 0, 1), 0.1))
        hole = body.newObject("PartDesign::Pocket", "Hole")
        hole.Profile = sk
        hole.Type = "ThroughAll"
        hole.Reversed = True
        return hole

    def modelG(self, cx, cy, reapply=True, external=False, ridgeLift=0.0, post="solid",
               mirror=False, roundCorner=False):
        """RB143's model G: returns (body, ridge, pattern), recomputed"""
        body = self.doc.addObject("PartDesign::Body", "Body")
        sk0, _ = flange(body)
        sk1 = planeSketch(body, "PostSketch", FL_H)
        sk1.addGeometry(Part.Circle(V(cx, cy, 0), V(0, 0, 1), 12))
        if post == "tube":
            sk1.addGeometry(Part.Circle(V(cx, cy, 0), V(0, 0, 1), 11.99))
        padPost = body.newObject("PartDesign::Pad", "Post")
        padPost.Profile = sk1
        padPost.Length = 3
        self.doc.recompute()
        if post == "hole":
            # a hole 0.1 behind the gap's wall: the copy sits at x -12, the hole at x -11.9
            skh = planeSketch(body, "PostHoleSketch", FL_H + 3)
            skh.addGeometry(Part.Circle(V(-11.85, 0, 0), V(0, 0, 1), 0.04))
            hole = body.newObject("PartDesign::Pocket", "PostHole")
            hole.Profile = skh
            hole.Length = 2.0
            self.doc.recompute()
        big = Part.Circle(V(0, 0, 0), V(0, 0, 1), 12)
        small = Part.Circle(V(11.97, 0, 0), V(0, 0, 1), 1)
        sk2 = lensSketch(body, "RidgeSketch", small, big, z=FL_H + ridgeLift)
        if external:
            sk2.addExternal("PostSketch", "Edge1")
        ridge = body.newObject("PartDesign::Pad", "Ridge")
        ridge.Profile = sk2
        ridge.Length = 0.25
        self.doc.recompute()
        last = ridge
        if roundCorner:
            # the rounded corner next to the flat side: the lens's tip edge at +y, vertical
            edge = self.verticalEdgeAt(ridge.Shape, ymax=True)
            fil = body.newObject("PartDesign::Fillet", "RidgeRound")
            fil.Base = (ridge, [edge])
            fil.Radius = 0.02
            self.doc.recompute()
            last = fil
        if mirror:
            pat = body.newObject("PartDesign::Mirrored", "Ring")
            pat.Originals = [last]
            pat.MirrorPlane = (sk0, ["V_Axis"])
        else:
            pat = body.newObject("PartDesign::PolarPattern", "Ring")
            pat.Originals = [last]
            pat.Axis = (sk0, ["N_Axis"])
            pat.Angle = 360
            pat.Occurrences = 2
        pat.Reapply = reapply
        body.Tip = pat
        self.doc.recompute()
        return body, ridge, pat

    def verticalEdgeAt(self, shape, ymax):
        best = None
        for i, edge in enumerate(shape.Edges):
            if isinstance(edge.Curve, Part.Line) and abs(edge.Curve.Direction.z) > 0.999:
                y = edge.Vertexes[0].Point.y
                if best is None or (y > best[0] if ymax else y < best[0]):
                    best = (y, "Edge%d" % (i + 1))
        return best[1]

    # -- checks ----------------------------------------------------------------------------------

    def assertBuilds(self, pat, faces=None, kindsWanted=None, gain=None, base=None, tol=2e-4,
                     warning=False):
        self.assertTrue(pat.isValid(), pat.getStatusString())
        shape = pat.Shape
        self.assertEqual(len(shape.Solids), 1)
        self.assertEqual(len(shape.Shells), 1)
        if faces is not None:
            self.assertEqual(len(shape.Faces), faces, kinds(shape))
        if kindsWanted is not None:
            self.assertEqual(kinds(shape), kindsWanted)
        if gain is not None:
            self.assertAlmostEqual(shape.Volume - base.Shape.Volume, gain, delta=tol)
        described = self.doc.getWarningDescription(pat) if hasattr(self.doc, "getWarningDescription") else ""
        if not warning:
            self.assertFalse(described and "wasn't closed" in described, described)
        return shape

    def flatSides(self, shape, cx, cy):
        """The copy's own flat side in model G: a cylinder r 12 about (-cx, -cy)"""
        return [
            f for f in shape.Faces
            if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - 12) < 1e-6
            and math.hypot(f.Surface.Center.x + cx, f.Surface.Center.y + cy) < 1e-7
        ]

    @staticmethod
    def gainG(g):
        """The closed copy of model G: a quarter of A(11.97 + g), sk1041's closed form (RB143)"""
        return {0.002: 0.385651, 0.004: 0.386650, 0.007: 0.388150, 0.008: 0.388650,
                0.00825: 0.388775}[g]

    # -- C1-C5: the tilted-post ring ---------------------------------------------------------------

    def testC1Ring40(self):
        body, ridge, pat = self.tiltedPost(2.0)
        shape = self.assertBuilds(pat, faces=46, kindsWanted={"Cylinder": 42, "Plane": 4},
                                  gain=14.707297, base=ridge)
        self.assertNotIn("SurfaceOfExtrusion", kinds(shape))

    def testC2FirstN(self):
        gains = {2: 0.377645, 3: 0.755461, 5: 1.511923, 8: 2.648811}
        previous = 0.0
        for n, gain in gains.items():
            body, ridge, pat = self.tiltedPost(2.0, n=n, angle=9.0 * (n - 1))
            self.assertBuilds(pat, faces=7 + (n - 1), gain=gain, base=ridge)
            self.assertGreater(gain, previous)
            previous = gain
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def testC3Ring20AndRefineOff(self):
        body, ridge, pat = self.tiltedPost(2.0, n=20)
        self.assertBuilds(pat, faces=45, kindsWanted={"Cylinder": 22, "Plane": 23},
                          gain=7.259784, base=ridge)
        App.closeDocument(self.doc.Name)
        self.doc = App.newDocument("TestPatternGapClose")
        body, ridge, pat = self.tiltedPost(2.0, refine=False)
        self.assertTrue(pat.isValid(), pat.getStatusString())
        shape = pat.Shape
        self.assertEqual(len(shape.Solids), 1)
        self.assertEqual(len(shape.Shells), 1)
        self.assertAlmostEqual(shape.Volume - ridge.Shape.Volume, 14.707297, delta=2e-4)

    def testC4OtherTilts(self):
        for tilt, gain in ((0.5, 14.764341), (3.0, 14.714238)):
            body, ridge, pat = self.tiltedPost(tilt)
            shape = self.assertBuilds(pat, faces=46, gain=gain, base=ridge)
            self.assertNotIn("SurfaceOfExtrusion", kinds(shape))
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def testC5UprightUnchanged(self):
        for n, faces, gain in ((40, 46, 14.801327), (20, 45, 7.308369)):
            body, ridge, pat = self.tiltedPost(0.0, n=n)
            self.assertBuilds(pat, faces=faces, gain=gain, base=ridge)
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    # -- C6-C10, C13, C14, C16: model G ------------------------------------------------------------

    def testC6ClosedUpToTheLimit(self):
        for g in (0.002, 0.004, 0.008, 0.00825):
            cx = g / 2
            body, ridge, pat = self.modelG(cx, 0)
            shape = self.assertBuilds(pat, faces=len(ridge.Shape.Faces) + 2, gain=self.gainG(g),
                                      base=ridge)
            self.assertEqual(self.flatSides(shape, cx, 0), [])
            self.assertTrue(shape.isInside(V(-12, 0, 2.1), 1e-9, False))
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def testC6OpenOverTheLimit(self):
        for g in (0.0085, 0.02, 0.2):
            cx = g / 2
            body, ridge, pat = self.modelG(cx, 0)
            shape = self.assertBuilds(pat, faces=len(ridge.Shape.Faces) + 3, gain=0.384651,
                                      base=ridge)
            flat = self.flatSides(shape, cx, 0)
            self.assertEqual(len(flat), 1)
            self.assertAlmostEqual(flat[0].Area, 0.500546, delta=1e-5)
            self.assertFalse(shape.isInside(V(-12, 0, 2.1), 1e-9, False))
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def testC7ExternalGeometry(self):
        for g, closed in ((0.002, True), (0.2, False)):
            body, ridge, pat = self.modelG(g / 2, 0, external=True)
            shape = self.assertBuilds(pat, faces=len(ridge.Shape.Faces) + (2 if closed else 3))
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def testC8CrossingEdge(self):
        for w, closed in ((0.001, True), (0.003, True), (0.005, True), (0.0055, False),
                          (0.006, False)):
            body, ridge, pat = self.modelG(0, 6 * w)
            shape = self.assertBuilds(pat, faces=len(ridge.Shape.Faces) + (2 if closed else 3))
            self.assertEqual(len(self.flatSides(shape, 0, 6 * w)), 0 if closed else 1, w)
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def testC9DeepInsideStaysOpen(self):
        body, ridge, pat = self.modelG(-0.004, 0.072)
        shape = self.assertBuilds(pat, faces=len(ridge.Shape.Faces) + 3, gain=0.380835, base=ridge)
        flat = self.flatSides(shape, -0.004, 0.072)
        self.assertEqual(len(flat), 1)
        self.assertAlmostEqual(flat[0].Area, 0.101805, delta=1e-5)

    def testC9bShallowInsideCloses(self):
        for cx, cy in ((-0.002, 0.036), (-0.001, 0.030), (-0.0005, 0.018)):
            body, ridge, pat = self.modelG(cx, cy)
            shape = self.assertBuilds(pat, faces=len(ridge.Shape.Faces) + 2)
            self.assertEqual(self.flatSides(shape, cx, cy), [])
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def testC10CrossingBetweenSamples(self):
        body, ridge, pat = self.modelG(0.001675, 0.0219)
        shape = self.assertBuilds(pat, faces=len(ridge.Shape.Faces) + 3)
        self.assertEqual(len(self.flatSides(shape, 0.001675, 0.0219)), 1)

    def testC13UnsoundSlabWarns(self):
        for post, corner in (("tube", False), ("hole", False), ("solid", True)):
            body, ridge, pat = self.modelG(0.002, 0, post=post, roundCorner=corner)
            self.assertTrue(pat.isValid(), pat.getStatusString())
            described = self.doc.getWarningDescription(pat) or ""
            self.assertIn("wasn't closed", described, post)
            self.assertEqual(len(self.flatSides(pat.Shape, 0.002, 0)), 1, post)
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def testC14TouchesNothing(self):
        body, ridge, pat = self.modelG(0.002, 0, ridgeLift=0.005)
        self.assertFalse(pat.isValid())
        self.assertIn("touches nothing", pat.getStatusString())

    def testC16ReapplyOffMirror(self):
        body, ridge, pat = self.modelG(0.001, 0, reapply=False)
        shape = self.assertBuilds(pat, faces=len(ridge.Shape.Faces) + 3)
        self.assertEqual(len(self.flatSides(shape, 0.001, 0)), 1)
        App.closeDocument(self.doc.Name)
        self.doc = App.newDocument("TestPatternGapClose")
        body, ridge, pat = self.modelG(0.001, 0, mirror=True)
        shape = self.assertBuilds(pat, faces=len(ridge.Shape.Faces) + 2)

    # -- C11, C12, C15: removes, steep tilts, the instance path -----------------------------------

    def testC11RemoveStaysRigid(self):
        body, ridge, pat = self.tiltedPost(2.0, pocket=True)
        if not pat.isValid():
            return  # loud before the fix as well: filed, never silent
        shape = pat.Shape
        self.assertEqual(len(shape.Solids), 1)
        self.assertEqual(kinds(shape), {"Cylinder": 42, "SurfaceOfExtrusion": 40, "Plane": 5})

    def testC12SteepTiltNeverSilent(self):
        tr = math.radians(5.0)
        for n in (40, 3, 5, 8):
            body, ridge, pat = self.tiltedPost(5.0, n=n, angle=360.0 if n == 40 else 9.0 * (n - 1),
                                               post=POST_H + 2.0)
            if pat.isValid():
                shape = pat.Shape
                self.assertEqual(len(shape.Solids), 1, n)
                gain = shape.Volume - ridge.Shape.Volume
                self.assertGreater(gain, 0.0)
                self.assertLess(gain, (n - 1) * ridge.AddSubShape.Volume + 1e-6)
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def testC15InstancePathAndSeedTurn(self):
        body, ridge, pat = self.tiltedPost(2.0, removeToo=True)
        self.assertTrue(pat.isValid(), pat.getStatusString())
        shape = pat.Shape
        self.assertEqual(len(shape.Solids), 1)
        self.assertNotIn("SurfaceOfExtrusion", kinds(shape))
        App.closeDocument(self.doc.Name)
        self.doc = App.newDocument("TestPatternGapClose")
        for turn in (45.0, 180.0):
            body, ridge, pat = self.tiltedPost(2.0, seedTurn=turn)
            shape = self.assertBuilds(pat)
            self.assertNotIn("SurfaceOfExtrusion", kinds(shape))
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")
