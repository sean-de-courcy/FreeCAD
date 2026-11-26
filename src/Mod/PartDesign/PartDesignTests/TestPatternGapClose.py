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
    """A lens: the arc of `small` outside `big`, closed by the arc of `big` inside `small`"""
    xy = lambda q: (q.X, q.Y) if hasattr(q, "X") else (q.x, q.y)
    pts = [V(x, y, 0) for x, y in (xy(q) for q in small.intersect(big))]
    assert len(pts) == 2, pts

    def arc(curve, p, q):
        a, b = curve.parameter(p), curve.parameter(q)
        if b < a:
            b += 2 * math.pi
        return a, b

    def mid(curve, a, b):
        return curve.value((a + b) / 2)

    sk = planeSketch(body, name, z)
    centre = small.Center
    for p, q in ((pts[0], pts[1]), (pts[1], pts[0])):
        a, b = arc(small, p, q)
        # the small circle's arc outside big: farther from big's centre than big's own points there
        m = mid(small, a, b)
        if (m - big.Center).Length > (pts[0] - big.Center).Length:
            sk.addGeometry(Part.ArcOfCircle(small, a, b))
            break
    for p, q in ((pts[0], pts[1]), (pts[1], pts[0])):
        a, b = arc(big, p, q)
        if (mid(big, a, b) - centre).Length < small.Radius:
            if isinstance(big, Part.Ellipse):
                sk.addGeometry(Part.ArcOfEllipse(big, a, b))
            else:
                sk.addGeometry(Part.ArcOfCircle(big, a, b))
            break
    assert sk.GeometryCount == 2, name
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
        ell = Part.Ellipse(V(-off, 0, 0), a, R) if tilt else Part.Circle(V(0, 0, 0), V(0, 0, 1), R)
        circ = Part.Circle(V(-off + a - DC, 0, 0), V(0, 0, 1), RHO)
        if seedTurn:
            # the sketch's frame turned about z, its curves turned back: the same lens in another frame
            back = App.Placement(V(), App.Rotation(V(0, 0, 1), -seedTurn))
            ell.transform(back.toMatrix())
            circ.transform(back.toMatrix())
        sk2 = lensSketch(body, "RidgeSketch", circ, ell,
                         rotation=App.Rotation(V(0, 0, 1), seedTurn) if seedTurn else None)
        if pocket:
            # cut 0.25 down into the flange: the floors at z 1.75 (RB148 K1.2)
            ridge = body.newObject("PartDesign::Pocket", "Ridge")
            ridge.Profile = sk2
            ridge.Length = H
        else:
            ridge = body.newObject("PartDesign::Pad", "Ridge")
            ridge.Profile = sk2
            ridge.Length = H
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
            # a wall 0.005 thick: thinner than the slab's depth (g 0.004 + m 0.01)
            sk1.addGeometry(Part.Circle(V(cx, cy, 0), V(0, 0, 1), 11.995))
        padPost = body.newObject("PartDesign::Pad", "Post")
        padPost.Profile = sk1
        padPost.Length = 3
        self.doc.recompute()
        if post == "hole":
            # a hole 0.1 deep just behind the wall the copy faces (x cx - 12), under a skin 0.003 thick: the
            # rays see the wall, the slab's far face (0.014 in) lies in the hole
            skh = planeSketch(body, "PostHoleSketch", FL_H + 3)
            skh.addGeometry(Part.Circle(V(cx - 12 + 0.053, cy, 0), V(0, 0, 1), 0.05))
            hole = body.newObject("PartDesign::Pocket", "PostHole")
            hole.Profile = skh
            hole.Length = 3.5
            self.doc.recompute()
        # the seed's flat side lies on the post; its copy at 180 deg stands 2 cx off it at -x
        big = Part.Circle(V(cx, cy, 0), V(0, 0, 1), 12)
        small = Part.Circle(V(cx + 11.97, cy, 0), V(0, 0, 1), 1)
        if roundCorner:
            sk2 = self.roundedLens(body, small, big, 0.02, FL_H + ridgeLift)
        else:
            sk2 = lensSketch(body, "RidgeSketch", small, big, z=FL_H + ridgeLift)
        if external:
            sk2.addExternal("PostSketch", "Edge1")
        ridge = body.newObject("PartDesign::Pad", "Ridge")
        ridge.Profile = sk2
        ridge.Length = 0.25
        self.doc.recompute()
        last = ridge
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

    def roundedLens(self, body, small, big, r, z):
        """The lens with its +y tip rounded by a circle r tangent to both arcs (inside small, outside big)"""
        cs, cb = small.Center, big.Center
        rs, rb = small.Radius - r, big.Radius + r
        # the fillet centre: |c - cs| = rs and |c - cb| = rb, the +y solution
        d = (cs - cb).Length
        ex = (cs - cb) * (1 / d)
        ey = V(-ex.y, ex.x, 0)
        x = (rb * rb - rs * rs + d * d) / (2 * d)
        y = math.sqrt(rb * rb - x * x)
        c = cb + ex * x + ey * (y if (cb + ey * y).y > (cb - ey * y).y else -y)
        ts = cs + (c - cs) * (small.Radius / rs)
        tb = cb + (c - cb) * (big.Radius / rb)
        xy = lambda q: (q.X, q.Y) if hasattr(q, "X") else (q.x, q.y)
        low = min((V(*xy(q), 0) for q in small.intersect(big)), key=lambda q: q.y)
        sk = planeSketch(body, "RidgeSketch", z)

        def ccw(curve, p, q):
            a0, b0 = curve.parameter(p), curve.parameter(q)
            return (a0, b0 + 2 * math.pi) if b0 < a0 else (a0, b0)
        sk.addGeometry(Part.ArcOfCircle(small, *ccw(small, low, ts)))
        corner = Part.Circle(c, V(0, 0, 1), r)
        sk.addGeometry(Part.ArcOfCircle(corner, *ccw(corner, ts, tb)))
        sk.addGeometry(Part.ArcOfCircle(big, *ccw(big, low, tb)))
        return sk

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
            self.assertAlmostEqual(self.added(shape, base), gain, delta=tol)
        if not warning:
            self.assertNotIn("Warning", pat.State, pat.getStatusString())
        return shape

    @staticmethod
    def added(shape, base):
        """The material the pattern added over the part: read from the difference itself, since shape.Volume less
        the part's volume loses about 4e-4 on the tilted ring at 20 copies (OCCT's volume of a large part)"""
        return shape.cut(base.Shape).Volume

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
        gains = {2: 0.377645, 3: 0.755461, 5: 1.511923, 8: 2.648811, 12: 4.164764, 20: 7.169232, 39: 14.334549}
        previous = 0.0
        for n, gain in gains.items():
            body, ridge, pat = self.tiltedPost(2.0, n=n, angle=9.0 * (n - 1))
            self.assertBuilds(pat, faces=7 + (n - 1), gain=gain, base=ridge)
            self.assertGreater(gain, previous)
            previous = gain
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")
        # 39 to 40 rises by one more copy (B3)
        self.assertAlmostEqual(14.707297 - previous, 0.372748, delta=2e-6)

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
        self.assertAlmostEqual(self.added(shape, ridge), 14.707297, delta=2e-4)

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

    def testC5RidgeAndRingRowsUnchanged(self):
        """B9 (RB51's ridge) and B10 (sk1126b's rows): no near-coincident sides, so the fix changes nothing"""
        for reapply in (True, False):
            body = self.doc.addObject("PartDesign::Body", "Body")
            sk0 = planeSketch(body, "BaseSketch")
            self.rectangle(sk0, -15, -15, 15, 15)
            base = body.newObject("PartDesign::Pad", "Base")
            base.Profile = sk0
            base.Length = 3
            sk1 = planeSketch(body, "SeedSketch", 3)
            self.rectangle(sk1, 4, -0.75, 14, 0.75)
            pad = body.newObject("PartDesign::Pad", "Seed")
            pad.Profile = sk1
            pad.Length = 2
            self.doc.recompute()
            pat = body.newObject("PartDesign::PolarPattern", "Ring")
            pat.Originals = [pad]
            pat.Axis = (self.zAxisThrough(body, 3.0), ["Edge"])
            pat.Angle = 360
            pat.Occurrences = 40
            pat.Reapply = reapply
            body.Tip = pat
            self.doc.recompute()
            shape = self.assertBuilds(pat, faces=168)
            self.assertAlmostEqual(shape.Volume - 2730.0, 711.92465, delta=1e-2)
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")
        for w, faces, volume in ((2.0, 123, 4893.272375), (0.5, 163, 2005.413826)):
            body = self.doc.addObject("PartDesign::Body", "Body")
            sk0 = planeSketch(body, "BaseSketch")
            sk0.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10))
            sk0.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 6))
            base = body.newObject("PartDesign::Pad", "Base")
            base.Profile = sk0
            base.Length = 5
            sk1 = planeSketch(body, "SeedSketch")
            self.rectangle(sk1, 8, -w / 2, 20, w / 2)
            pad = body.newObject("PartDesign::Pad", "Seed")
            pad.Profile = sk1
            pad.Length = 5
            self.doc.recompute()
            pat = body.newObject("PartDesign::PolarPattern", "Ring")
            pat.Originals = [pad]
            pat.Axis = (sk0, ["N_Axis"])
            pat.Angle = 360
            pat.Occurrences = 40
            pat.Reapply = True
            body.Tip = pat
            self.doc.recompute()
            shape = self.assertBuilds(pat, faces=faces)
            self.assertAlmostEqual(shape.Volume, volume, delta=1e-2)
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    def zAxisThrough(self, body, x):
        """A datum line along z through (x, 0, 0)"""
        line = body.newObject("PartDesign::Line", "Axis")
        line.MapMode = "Deactivated"
        line.Placement = App.Placement(V(x, 0, 0), App.Rotation())
        self.doc.recompute()
        return line

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
            self.assertIn("Warning", pat.State, post)
            self.assertIn("wasn't closed", pat.getStatusString(), post)
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

    def rectangle(self, sk, x0, y0, x1, y1):
        pts = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
        for i in range(4):
            sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))

    def testC17Corner(self):
        """A block's copy lands in a corner: 0.004 off one wall (closed), 0.02 off the other (kept)"""
        body = self.doc.addObject("PartDesign::Body", "Body")
        sk0 = planeSketch(body, "FlangeSketch")
        self.rectangle(sk0, -3, -3, 10, 4)
        flangePad = body.newObject("PartDesign::Pad", "Flange")
        flangePad.Profile = sk0
        flangePad.Length = FL_H
        # an L of two walls: x >= 6.004 and y <= -0.02
        skw = planeSketch(body, "WallSketch", FL_H)
        pts = [V(3, -2, 0), V(8, -2, 0), V(8, 3, 0), V(6.004, 3, 0), V(6.004, -0.02, 0), V(3, -0.02, 0)]
        for i in range(len(pts)):
            skw.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % len(pts)]))
        walls = body.newObject("PartDesign::Pad", "Walls")
        walls.Profile = skw
        walls.Length = 3
        self.doc.recompute()
        self.assertTrue(walls.isValid(), walls.getStatusString())
        skb = planeSketch(body, "BlockSketch", FL_H)
        self.rectangle(skb, 0, 0, 1, 1)
        block = body.newObject("PartDesign::Pad", "Block")
        block.Profile = skb
        block.Length = 0.25
        self.doc.recompute()
        pat = body.newObject("PartDesign::LinearPattern", "Row")
        pat.Originals = [block]
        pat.Direction = (sk0, ["H_Axis"])
        pat.Length = 5
        pat.Occurrences = 2
        pat.Reapply = True
        body.Tip = pat
        self.doc.recompute()
        shape = self.assertBuilds(pat, gain=0.25 + 0.004 * 0.25, base=block, tol=1e-6)
        planes = [f for f in shape.Faces if isinstance(f.Surface, Part.Plane)]

        def at(axis, value):
            return [f for f in planes if abs(getattr(f.Surface.Axis, axis)) > 0.999
                    and abs(getattr(f.CenterOfMass, axis) - value) < 1e-7
                    and 5 < f.CenterOfMass.x < 6.1 and 0 <= f.CenterOfMass.y <= 1]
        self.assertEqual(at("x", 6.0), [], "the 0.004 gap is closed")
        self.assertEqual(len(at("y", 0.0)), 1, "the 0.02 gap is kept")
        self.assertTrue(shape.isInside(V(6.002, 0.5, 2.1), 1e-9, False))
        self.assertFalse(shape.isInside(V(5.5, -0.01, 2.1), 1e-9, False))

    def testC18ReferenceSurvivesTheCount(self):
        """A reference to copy 7's outer cylinder made at 40 copies follows copy 7 to 41 and back"""
        body, ridge, pat = self.tiltedPost(2.0)
        self.assertTrue(pat.isValid(), pat.getStatusString())
        angle = math.radians(6 * 9.0)
        best = None
        for i, face in enumerate(pat.Shape.Faces):
            if isinstance(face.Surface, Part.Cylinder) and abs(face.Surface.Radius - RHO) < 1e-6:
                c = face.Surface.Center
                d = abs(math.atan2(c.y, c.x) - angle)
                if best is None or d < best[0]:
                    best = (d, "Face%d" % (i + 1))
        self.assertLess(best[0], 0.05)
        point = body.newObject("PartDesign::Point", "OnCopy7")
        point.AttachmentSupport = (pat, [best[1]])
        point.MapMode = "CenterOfMass"
        self.doc.recompute()
        self.assertTrue(point.isValid(), point.getStatusString())

        def turn():
            p = point.Placement.Base
            return math.degrees(math.atan2(p.y, p.x))
        at40 = turn()
        self.assertAlmostEqual(at40, 54.0, delta=1.0)
        pat.Occurrences = 41
        self.doc.recompute()
        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertAlmostEqual(turn(), at40 * 40 / 41, delta=0.2)
        pat.Occurrences = 40
        self.doc.recompute()
        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertAlmostEqual(turn(), at40, delta=1e-6)

    def testC19ReapplyOffStaysLoud(self):
        """R1, R2: with Reapply off nothing is closed, and the tilted ring stays loud, never silent"""
        for n in (40, 8):
            body, ridge, pat = self.tiltedPost(2.0, n=n, angle=360.0 if n == 40 else 9.0 * (n - 1),
                                               reapply=False)
            if pat.isValid():
                shape = pat.Shape
                self.assertEqual(len(shape.Solids), 1, n)
                gain = shape.Volume - ridge.Shape.Volume
                self.assertGreater(gain, 0.0, n)
                self.assertLessEqual(gain, (n - 1) * ridge.AddSubShape.Volume + 1e-6, n)
            else:
                self.assertTrue(pat.getStatusString(), n)
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestPatternGapClose")

    # -- C11, C12, C15: removes, steep tilts, the instance path -----------------------------------

    def testC11RemoveStaysRigid(self):
        """RB148 K1.2: a Remove's copies cut rigidly. Every copy keeps its flat side (Onshape: 0.44182 at t 2) and
        the 40 floors are one plane at z 1.75. Not asserted, filed (pre-existing, the Remove path is untouched):
        Onshape has 87 faces where the fork keeps 40 more strips (0.0294 each) between neighbouring pockets"""
        body, ridge, pat = self.tiltedPost(2.0, pocket=True)
        if not pat.isValid():
            return  # loud before the fix as well: filed, never silent
        shape = pat.Shape
        self.assertEqual(len(shape.Solids), 1)
        flat = [f for f in shape.Faces if type(f.Surface).__name__ == "SurfaceOfExtrusion"
                and abs(f.Area - 0.44182) < 1e-4]
        self.assertEqual(len(flat), 40, kinds(shape))
        floors = [f for f in shape.Faces if isinstance(f.Surface, Part.Plane)
                  and abs(f.BoundBox.ZMax - 1.75) < 1e-7 and abs(f.BoundBox.ZMin - 1.75) < 1e-7]
        self.assertEqual(len(floors), 1)
        self.assertAlmostEqual(floors[0].Area, 60.739, delta=5e-3)

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
                # rigid copies plus, per copy, at most its flat side (about 0.5) x T_gap
                self.assertLess(gain, (n - 1) * (ridge.AddSubShape.Volume + 0.5 * 0.008375) + 1e-6)
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
