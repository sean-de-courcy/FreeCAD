# SPDX-License-Identifier: LGPL-2.1-or-later

"""Per-feature post-conditions, report-only (FreeCAD-CH kernel layer, PostCondition.h).

With FREECAD_CH_POSTCOND_LOG set, each solid feature whose result passed its check logs one JSON
line: tolerance growth (tol), a degraded surface type among the faces it made (deg), no volume
change for an operation meant to change it (dv), and OCCT's self-interference and curve-on-surface
check of the faces it made and their neighbours (bop). Nothing is thrown and no result changes.
Each check has a designed model that must flag it, and ordinary features must flag nothing.
Designed geometry only.
"""

import json
import os
import tempfile
import unittest

import FreeCAD
import Part

V = FreeCAD.Vector
ENV = "FREECAD_CH_POSTCOND_LOG"


def rect(x0, y0, x1, y1, z):
    return Part.Face(
        Part.makePolygon([V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z), V(x0, y0, z)])
    )


def disk(x, y, r, z):
    return Part.Face(Part.Wire(Part.makeCircle(r, V(x, y, z))))


def splineRect(x0, y0, x1, y1, z):
    """A rectangle whose sides are degree-2 B-splines on three collinear poles: straight lines that
    are not Geom_Line, so a pad's side faces are extrusions of B-splines lying on planes"""
    corners = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    edges = []
    for i in range(4):
        a = corners[i]
        b = corners[(i + 1) % 4]
        curve = Part.BSplineCurve()
        curve.buildFromPolesMultsKnots([a, (a + b) * 0.5, b], [3, 3], [0.0, 1.0], False, 2)
        edges.append(curve.toShape())
    return Part.Face(Part.Wire(edges))


class Retoleranced:
    """A PartDesign::FeaturePython proxy: its base, copied, with every tolerance raised to 0.01 mm"""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        shape = obj.BaseFeature.Shape.copy()
        shape.fixTolerance(0.01)
        obj.Shape = shape


class Overlapping:
    """A PartDesign::FeaturePython proxy with no base: two boxes overlapping by half, as one
    compound (each solid valid, their faces cross)"""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        a = Part.makeBox(10, 10, 10)
        b = Part.makeBox(10, 10, 10, V(5, 5, 5))
        obj.Shape = Part.makeCompound([a, b])


class TestPostCondition(unittest.TestCase):
    def setUp(self):
        handle, self.log = tempfile.mkstemp(prefix="postcond-", suffix=".jsonl")
        os.close(handle)
        os.environ[ENV] = self.log
        self.doc = FreeCAD.newDocument("PostCondition")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        os.environ.pop(ENV, None)
        os.remove(self.log)

    def entries(self):
        with open(self.log) as f:
            return {e["name"]: e for e in (json.loads(line) for line in f if line.strip())}

    def entry(self, feature):
        found = self.entries()
        self.assertIn(feature.Name, found, "no post-condition line for %s" % feature.Name)
        return found[feature.Name]

    def body(self, base_shape=None):
        body = self.doc.addObject("PartDesign::Body", "Body")
        if base_shape is not None:
            base = self.doc.addObject("Part::Feature", "Base")
            base.Shape = base_shape
            body.BaseFeature = base
        return body

    def profile(self, shape, name):
        prof = self.doc.addObject("Part::Feature", name)
        prof.Shape = shape
        return prof

    def pad(self, body, face, length, name="Pad"):
        p = body.newObject("PartDesign::Pad", name)
        p.Profile = (self.profile(face, name + "Profile"), ["Face1"])
        p.Length = length
        return p

    def pocket(self, body, face, name="Pocket"):
        p = body.newObject("PartDesign::Pocket", name)
        p.Profile = (self.profile(face, name + "Profile"), ["Face1"])
        p.Type = "ThroughAll"
        return p

    def assertNoFlag(self, e):
        for check in ("tol", "deg", "dv", "bop"):
            self.assertFalse(e[check]["flag"], "%s flagged %s: %s" % (e["name"], check, e[check]))

    def testOrdinaryFeaturesFlagNothing(self):
        body = self.body(Part.makeBox(40, 30, 10))
        pad = self.pad(body, rect(5, 5, 15, 15, 10), 5)
        pocket = self.pocket(body, disk(30, 15, 4, 10))
        self.doc.recompute()
        for feature in (pad, pocket):
            self.assertTrue(feature.isValid(), feature.getStatusString())
            e = self.entry(feature)
            self.assertNoFlag(e)
            self.assertTrue(e["dv"]["applies"], e)
            self.assertEqual(e["bop"]["status"], "ok", e)
        # the pad adds 10 x 10 x 5, the pocket takes a cylinder r 4 through 10
        self.assertAlmostEqual(self.entry(pad)["dv"]["change"], 500, delta=1e-6)

    def testPocketThatMissesFlagsNoVolumeChange(self):
        body = self.body(Part.makeBox(40, 30, 10))
        pocket = self.pocket(body, disk(100, 100, 4, 10))
        self.doc.recompute()
        e = self.entry(pocket)
        self.assertTrue(e["dv"]["flag"], e)
        self.assertEqual(e["dv"]["change"], 0.0)
        # report-only: the result is the base's, unchanged
        self.assertAlmostEqual(pocket.Shape.Volume, 12000, delta=1e-6)

    def testStraightSplineSidesAreDegradedPlanes(self):
        body = self.body(Part.makeBox(40, 30, 10))
        pad = self.pad(body, splineRect(5, 5, 15, 15, 10), 5)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        e = self.entry(pad)
        self.assertTrue(e["deg"]["flag"], e)
        faces = e["deg"]["faces"]
        self.assertEqual(len(faces), 4, faces)
        for face in faces:
            self.assertEqual(face["to"], "Plane", face)
            self.assertAlmostEqual(face["area"], 50, delta=1e-6)
        self.assertFalse(e["tol"]["flag"], e)
        self.assertFalse(e["dv"]["flag"], e)

    def testReTrimmedDegradedFaceIsInheritedNotFlagged(self):
        """The pad's spline sides are flagged at the pad; a pocket through the side at x = 15 re-trims
        that face, which it did not make degraded"""
        body = self.body(Part.makeBox(40, 30, 10))
        pad = self.pad(body, splineRect(5, 5, 15, 15, 10), 5)
        pocket = self.pocket(body, disk(15, 10, 2, 15), "SidePocket")
        self.doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertTrue(self.entry(pad)["deg"]["flag"])
        e = self.entry(pocket)
        self.assertFalse(e["deg"]["flag"], e)
        self.assertGreaterEqual(e["deg"]["inherited"], 1, e)

    def testRevolvedCircleIsNotFlagged(self):
        body = self.body()
        prof = self.profile(
            Part.Face(Part.Wire(Part.Circle(V(10, 0, 0), V(0, 1, 0), 2).toShape())), "RevProfile"
        )
        axis = self.doc.addObject("Part::Feature", "Axis")
        axis.Shape = Part.makeLine(V(0, 0, -5), V(0, 0, 5))
        rev = body.newObject("PartDesign::Revolution", "Revolution")
        rev.Profile = (prof, ["Face1"])
        rev.ReferenceAxis = (axis, ["Edge1"])
        rev.Angle = 360
        self.doc.recompute()
        self.assertTrue(rev.isValid(), rev.getStatusString())
        self.assertNoFlag(self.entry(rev))

    def testRaisedToleranceIsFlagged(self):
        body = self.body(Part.makeBox(40, 30, 10))
        feature = body.newObject("PartDesign::FeaturePython", "Retoleranced")
        Retoleranced(feature)
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        e = self.entry(feature)
        self.assertTrue(e["tol"]["flag"], e)
        self.assertGreaterEqual(e["tol"]["result"], 0.01)
        self.assertFalse(e["dv"]["applies"], e)

    def testCrossingFacesAreFlaggedByTheBopCheck(self):
        body = self.body()
        feature = body.newObject("PartDesign::FeaturePython", "Overlapping")
        Overlapping(feature)
        self.doc.recompute()
        e = self.entry(feature)
        self.assertEqual(e["bop"]["status"], "faulty", e)
        self.assertGreater(e["bop"]["selfIntersect"], 0, e)
        # report-only: both boxes stay
        self.assertEqual(len(feature.Shape.Solids), 2)

    def testNothingLoggedWithoutTheVariable(self):
        os.environ.pop(ENV, None)
        body = self.body(Part.makeBox(40, 30, 10))
        self.pocket(body, disk(100, 100, 4, 10))
        self.doc.recompute()
        self.assertEqual(os.path.getsize(self.log), 0)
