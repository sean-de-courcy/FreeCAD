# SPDX-License-Identifier: LGPL-2.1-or-later
"""Attachment across containers (FreeCAD-CH ops#318): a sketch or datum in one Body attached to an
element of another Body (or App::Part) read that element in the other container's coordinates as
if they were its own, so it sat off the element by the containers' difference, and moving either
container changed nothing, silently. Each link is now mapped by the containers' relative placement,
and a container's move re-places the attachment on the next recompute.

Designed geometry. Oracles: the face's global plane ("lies on the face": the attached object's
global z axis along the face's normal and its global origin on the face's plane), and the frame
the same attachment gets with both Bodies placed alike, where no mapping is needed."""

import os
import subprocess
import sys
import tempfile
import unittest

import FreeCAD
import Part
import Sketcher

V = FreeCAD.Vector
R = FreeCAD.Rotation
P = FreeCAD.Placement
TOL = 1e-7

# Body1's and Body2's placements (design note 8, A-t1)
PAIRS = {
    "Body1Moved": (P(V(100, 50, 0), R()), P()),
    "Body2Moved": (P(), P(V(30, 0, 7), R())),
    "BothRotated": (P(V(100, 50, 0), R(V(1, 0, 0), 30)), P(V(30, 0, 7), R(V(0, 1, 0), 45))),
    "EqualRotated": (P(V(5, 6, 7), R(V(1, 1, 0), 20)), P(V(5, 6, 7), R(V(1, 1, 0), 20))),
}


def rectangle(sketch, x0, y0, x1, y1):
    points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    first = len(sketch.Geometry)
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(points[i], points[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1)
        )


def find(shape, kind, test):
    [name] = [f"{kind[:-1]}{i}" for i, s in enumerate(getattr(shape, kind), 1) if test(s)]
    return name


def topFace(feature, z):
    return find(feature.Shape, "Faces", lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-9
                and abs(f.CenterOfMass.z - z) < 1e-6)


def vertexAt(feature, point):
    return find(feature.Shape, "Vertexes", lambda v: (v.Point - point).Length < 1e-6)


def role(lcs, name):
    [element] = [f for f in lcs.OriginFeatures if f.Role == name]
    return element


def globalElement(feature, name):
    """The element as it is in the document's coordinates."""
    element = feature.Shape.getElement(name).copy()
    group = feature.getParentGeoFeatureGroup()
    if group:
        element.Placement = group.getGlobalPlacement().multiply(element.Placement)
    return element


def axis(placement):
    return placement.Rotation.multVec(V(0, 0, 1))


class TestAttachAcrossContainers(unittest.TestCase):
    def setUp(self):
        self.docs = []
        self.doc = self.newDocument()

    def tearDown(self):
        for name in self.docs:
            if name in FreeCAD.listDocuments():
                FreeCAD.closeDocument(name)

    def newDocument(self):
        doc = FreeCAD.newDocument("PartDesignTestAttachAcross")
        self.docs.append(doc.Name)
        return doc

    # Models ----------------------------------------------------------------------------------

    def source(self, doc, at, name="Body1"):
        """Body1 at `at`: Pad1 20 x 10 x 5 on its XY plane, a cylinder r 2 h 3 standing on the
        pad at (10, 5), a datum plane on its XY plane (offset), a local coordinate system LCS1."""
        body = doc.addObject("PartDesign::Body", name)
        body.Placement = at
        sketch = body.newObject("Sketcher::SketchObject", "Sk1")
        sketch.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        sketch.MapMode = "FlatFace"
        rectangle(sketch, 0, 0, 20, 10)
        pad = body.newObject("PartDesign::Pad", "Pad1")
        pad.Profile = sketch
        pad.Length = 5
        cylinder = body.newObject("PartDesign::AdditiveCylinder", "Cyl1")
        cylinder.Radius = 2
        cylinder.Height = 3
        cylinder.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        cylinder.MapMode = "ObjectXY"
        cylinder.AttachmentOffset = P(V(10, 5, 5), R())
        plane = body.newObject("PartDesign::Plane", "DP1")
        plane.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        plane.MapMode = "FlatFace"
        plane.AttachmentOffset = P(V(1, 2, 3), R(V(0, 1, 0), 10))
        lcs = body.newObject("Part::LocalCoordinateSystem", "LCS1")
        lcs.Placement = P(V(4, 3, 2), R(V(0, 0, 1), 25))
        doc.recompute()
        return body, pad, cylinder, plane, lcs

    def supports(self, body, pad, cylinder, plane, lcs):
        """(mode, support) per case."""
        top = topFace(pad, 5)
        edge = find(pad.Shape, "Edges", lambda e: all(abs(v.Z - 5) < 1e-6 for v in e.Vertexes)
                    and abs(e.Vertexes[0].Y - e.Vertexes[1].Y) < 1e-6 and e.Vertexes[0].Y < 1e-6)
        corners = [vertexAt(pad, p) for p in (V(0, 0, 5), V(20, 0, 5), V(0, 10, 5))]
        circle = find(cylinder.Shape, "Edges", lambda e: isinstance(e.Curve, Part.Circle)
                      and abs(e.Curve.Radius - 2) < 1e-6 and abs(e.Curve.Center.z - 8) < 1e-6)
        mantle = find(cylinder.Shape, "Faces", lambda f: isinstance(f.Surface, Part.Cylinder))
        seam = vertexAt(cylinder, V(12, 5, 8))
        return {
            "FlatFace": ("FlatFace", [(pad, top)]),
            "FlatFacePath": ("FlatFace", [(body, f"Pad1.{top}")]),
            "ObjectXYDatumPlane": ("ObjectXY", [(plane, "")]),
            "ObjectXYCoordinateSystem": ("ObjectXY", [(lcs, "")]),
            "ObjectXYOriginPlane": ("ObjectXY", [(body.Origin.OriginFeatures[3], "")]),
            "NormalToEdge": ("NormalToEdge", [(pad, edge)]),
            "ThreePointsPlane": ("ThreePointsPlane", [(pad, v) for v in corners]),
            "Translate": ("Translate", [(pad, corners[1])]),
            "InertialCS": ("InertialCS", [(pad, top)]),
            "Concentric": ("Concentric", [(cylinder, circle)]),
            "TangentPlane": ("TangentPlane", [(cylinder, mantle), (cylinder, seam)]),
            "FrenetNB": ("FrenetNB", [(cylinder, circle)]),
        }

    # What each mode's frame is compared on: "full" the whole frame, "plane" the z axis and the
    # origin (FlatFace and the other modes that guess their x axis in the attached object's own
    # frame), "origin" the origin
    KIND = {"Translate": "origin"}

    def attachedSketch(self, doc, first, second, padLength=3):
        """Sk2 in Body2 (at `second`) on the top of Body1's pad (Body1 at `first`), with a
        rectangle (2, 2)-(8, 8) padded by Pad2."""
        source = self.source(doc, first)
        body = doc.addObject("PartDesign::Body", "Body2")
        body.Placement = second
        sketch = body.newObject("Sketcher::SketchObject", "Sk2")
        sketch.AttachmentSupport = [(source[1], topFace(source[1], 5))]
        sketch.MapMode = "FlatFace"
        rectangle(sketch, 2, 2, 8, 8)
        pad = body.newObject("PartDesign::Pad", "Pad2")
        pad.Profile = sketch
        pad.Length = padLength
        doc.recompute()
        return source, body, sketch, pad

    def attachedFrame(self, first, second, mode, setup=None):
        """The global frame of a coordinate system in Body2 attached by `mode` (a key of
        supports()) to Body1's elements, in a document of its own."""
        doc = self.newDocument()
        source = self.source(doc, first)
        kind, support = self.supports(*source)[mode]
        body = doc.addObject("PartDesign::Body", "Body2")
        body.Placement = second
        cs = body.newObject("PartDesign::CoordinateSystem", "CS2")
        cs.AttachmentSupport = support
        cs.MapMode = kind
        if kind == "FrenetNB":
            cs.MapPathParameter = 0.3
        if setup:
            setup(cs)
        doc.recompute()
        self.assertTrue(cs.isValid(), cs.getStatusString())
        frame = cs.getGlobalPlacement()
        FreeCAD.closeDocument(doc.Name)
        return frame

    # Oracles ---------------------------------------------------------------------------------

    def assertOnFace(self, obj, face):
        """obj's global z axis is the face's normal and its global origin is on the face."""
        frame = obj.getGlobalPlacement()
        normal = face.normalAt(0, 0)
        self.assertLess(axis(frame).cross(normal).Length, TOL, (obj.Name, frame, normal))
        self.assertGreater(axis(frame).dot(normal), 0)
        self.assertLess(abs((frame.Base - face.CenterOfMass).dot(normal)), TOL,
                        (obj.Name, frame, face.CenterOfMass))

    def assertStandsOnFace(self, pad, face, length):
        """Every vertex of the pad is on the face's plane or `length` above it, both present."""
        normal = face.normalAt(0, 0)
        shape = globalElement(pad, "Solid1") if pad.Shape.Solids else None
        self.assertIsNotNone(shape, pad.getStatusString())
        heights = sorted({round((v.Point - face.CenterOfMass).dot(normal), 6)
                          for v in shape.Vertexes})
        self.assertEqual(heights, [0.0, float(length)], heights)

    def assertSameFrame(self, got, expected, kind):
        self.assertLess((got.Base - expected.Base).Length, 1e-6, (got, expected))
        if kind in ("plane", "full"):
            self.assertLess(axis(got).cross(axis(expected)).Length, 1e-7, (got, expected))
            self.assertGreater(axis(got).dot(axis(expected)), 0)
        if kind == "full":
            self.assertTrue(got.isSame(expected, 1e-6), (got, expected))

    # A-t1 ------------------------------------------------------------------------------------

    def checkSketchOnFace(self, pair):
        first, second = PAIRS[pair]
        source, _, sketch, pad = self.attachedSketch(self.doc, first, second)
        face = globalElement(source[1], topFace(source[1], 5))
        self.assertOnFace(sketch, face)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertStandsOnFace(pad, face, 3)
        # The frame with both Bodies placed alike, where nothing needs mapping. FlatFace takes its
        # x axis from the support's axes, now mapped too, so the whole frame agrees
        reference = self.newDocument()
        expected = self.attachedSketch(reference, first, first)[2].getGlobalPlacement()
        self.assertSameFrame(sketch.getGlobalPlacement(), expected, "full")

    def testSketchOnAFaceOfABodyPlacedElsewhere(self):
        """A-t1: Body1 at (100, 50, 0), Body2 at the origin: the sketch sat on the face's spot
        in Body2's coordinates (at the origin), the Pad on it too."""
        self.checkSketchOnFace("Body1Moved")

    def testSketchInABodyPlacedElsewhere(self):
        """A-t1: Body1 at the origin, Body2 at (30, 0, 7): the sketch sat 7 above the face."""
        self.checkSketchOnFace("Body2Moved")

    def testSketchBetweenRotatedBodies(self):
        """A-t1: Body1 at (100, 50, 0) turned 30 deg about X, Body2 at (30, 0, 7) turned 45 deg
        about Y: the sketch was tilted against the face."""
        self.checkSketchOnFace("BothRotated")

    def testSketchBetweenBodiesPlacedAlike(self):
        """A-t1: both Bodies at one rotated placement: right before and after."""
        self.checkSketchOnFace("EqualRotated")

    def testFirstFeatureIsPlacedAsItsSupport(self):
        """Pad2, Body2's first feature, on Sk2 attached to Body1's pad (turned Bodies), is placed
        as that pad, mapped into Body2: an attachment to Pad2 as a whole gets Pad1's global
        frame. Pad2 had Pad1's placement taken as Body2's (design note 7)."""
        first, second = PAIRS["BothRotated"]
        source, body, _, pad = self.attachedSketch(self.doc, first, second)
        expected = source[1].getGlobalPlacement()
        self.assertTrue(pad.getGlobalPlacement().isSame(expected, 1e-9), pad.getGlobalPlacement())
        cs = body.newObject("PartDesign::CoordinateSystem", "OnPad2")
        cs.AttachmentSupport = [(pad, "")]
        cs.MapMode = "ObjectXY"
        self.doc.recompute()
        self.assertTrue(cs.getGlobalPlacement().isSame(expected, 1e-9), cs.getGlobalPlacement())

    # A-t2 ------------------------------------------------------------------------------------

    def checkMode(self, mode):
        """A coordinate system in Body2 attached to Body1's elements by `mode` gets, for each
        placement pair, the frame it gets with Body2 placed as Body1."""
        for pair in ("Body1Moved", "Body2Moved", "BothRotated"):
            with self.subTest(pair=pair):
                first, second = PAIRS[pair]
                kind = self.KIND.get(mode, "full")
                if kind == "full" and not first.Rotation.isSame(second.Rotation, 1e-12):
                    kind = self.fullUnderRotation.get(mode, kind)
                self.assertSameFrame(self.attachedFrame(first, second, mode),
                                     self.attachedFrame(first, first, mode), kind)

    # Modes that guess the x axis in the attached object's own frame ("Y up"): with the Bodies
    # turned differently only the plane and the origin agree
    fullUnderRotation = {"ThreePointsPlane": "plane", "NormalToEdge": "plane"}

    def testObjectXYOnADatumPlane(self):
        """A-t2: ObjectXY on a datum plane of Body1."""
        self.checkMode("ObjectXYDatumPlane")

    def testObjectXYOnACoordinateSystem(self):
        """A-t2: ObjectXY on a coordinate system of Body1."""
        self.checkMode("ObjectXYCoordinateSystem")

    def testObjectXYOnAnOriginPlane(self):
        """A-t2: ObjectXY on Body1's XY_Plane, linked bare (its frame is Body1's Origin)."""
        self.checkMode("ObjectXYOriginPlane")

    def testNormalToEdge(self):
        """A-t2: NormalToEdge on an edge of Body1's pad."""
        self.checkMode("NormalToEdge")

    def testThreePointsPlane(self):
        """A-t2: ThreePointsPlane on three corners of Body1's pad."""
        self.checkMode("ThreePointsPlane")

    def testTranslate(self):
        """A-t2: Translate to a corner of Body1's pad (the origin only)."""
        self.checkMode("Translate")

    def testInertialCS(self):
        """A-t2: InertialCS of the top of Body1's pad."""
        self.checkMode("InertialCS")

    def testConcentric(self):
        """A-t2: Concentric to the cylinder's top circle."""
        self.checkMode("Concentric")

    def testTangentPlane(self):
        """A-t2: TangentPlane to the cylinder's mantle at its seam vertex."""
        self.checkMode("TangentPlane")

    def testFrenetNB(self):
        """A-t2: FrenetNB along the cylinder's top circle."""
        self.checkMode("FrenetNB")

    # A-t3 ------------------------------------------------------------------------------------

    def testPathFormGivesTheSameFrame(self):
        """A-t3: (Body1, "Pad1.FaceN") gives the frame (Pad1, "FaceN") gives, rotated pair."""
        first, second = PAIRS["BothRotated"]
        self.assertSameFrame(self.attachedFrame(first, second, "FlatFacePath"),
                             self.attachedFrame(first, second, "FlatFace"), "full")

    def testTopLevelDatumThroughARootPathIsUnchanged(self):
        """A-t3: a top-level Part datum plane attached through a path from the root,
        (Part, "Body1.Pad1.FaceN") with Body1 in a turned App::Part: on the face, as before."""
        group = self.doc.addObject("App::Part", "Part")
        group.Placement = P(V(3, -4, 6), R(V(1, 2, 3), 35))
        body, pad = self.source(self.doc, P(V(10, 0, 0), R(V(0, 0, 1), 15)))[:2]
        group.addObject(body)
        self.doc.recompute()
        top = topFace(pad, 5)
        datum = self.doc.addObject("Part::DatumPlane", "Datum")
        datum.AttachmentSupport = [(group, f"Body1.Pad1.{top}")]
        datum.MapMode = "FlatFace"
        self.doc.recompute()
        self.assertOnFace(datum, globalElement(pad, top))

    # A-t4, A-t9 ------------------------------------------------------------------------------

    def ownBody(self, doc):
        """Attachments inside one Body turned 30 deg about X: on its own faces, its own origin
        planes (bare and through the Origin), a coordinate system's elements (bare and through
        it) and a coordinate system attached to its pad."""
        body, pad, cylinder, plane, lcs = self.source(
            doc, P(V(3, -7, 11), R(V(1, 0, 0), 30)))
        top = topFace(pad, 5)
        objects = {}

        def add(kind, name, mode, support, offset=None):
            obj = body.newObject(kind, name)
            obj.AttachmentSupport = support
            obj.MapMode = mode
            if offset:
                obj.AttachmentOffset = offset
            objects[name] = obj
            return obj

        sketch = "Sketcher::SketchObject"
        add(sketch, "OnTop", "FlatFace", [(pad, top)])
        add(sketch, "OnXY", "FlatFace", [(body.Origin.OriginFeatures[3], "")])
        add(sketch, "OnXZThroughOrigin", "FlatFace", [(body.Origin, "XZ_Plane")])
        add(sketch, "OnLcsXY", "FlatFace", [(role(lcs, "XY_Plane"), "")])
        add(sketch, "OnLcsYZThroughIt", "FlatFace", [(lcs, "YZ_Plane")])
        add(sketch, "OnDatum", "FlatFace", [(plane, "")])
        add("PartDesign::Plane", "PlaneOnTop", "FlatFace", [(pad, top)],
            P(V(1, 1, 1), R(V(0, 0, 1), 10)))
        add("PartDesign::CoordinateSystem", "CsOnLcs", "ObjectXY", [(lcs, "")])
        add("PartDesign::Line", "LineOnEdge", "TwoPointLine",
            [(pad, vertexAt(pad, V(0, 0, 5))), (pad, vertexAt(pad, V(20, 10, 5)))])
        attached = add("Part::LocalCoordinateSystem", "AttachedLcs", "FlatFace", [(pad, top)],
                       P(V(2, 3, 0), R(V(0, 0, 1), 40)))
        doc.recompute()
        add(sketch, "OnAttachedLcsXY", "FlatFace", [(role(attached, "XY_Plane"), "")])
        doc.recompute()
        return objects

    # Recorded from the build before the change (ops#318, wt\fix at f61d59b603): (Base, Q)
    OWN_BODY = {
        "AttachedLcs": ((2.0, 3.0, 5.0),
            (0.0, 0.0, 0.3420201433256687, 0.9396926207859084)),
        "CsOnLcs": ((4.000000000000001, 3.000000000000001, 2.0),
            (0.0, 0.0, 0.21643961393810288, 0.9762960071199334)),
        "LineOnEdge": ((0.0, 0.0, 5.0),
            (0.37174803446018456, 0.6015009550075456, 0.6015009550075459, 0.37174803446018456)),
        "OnAttachedLcsXY": ((2.0000000000000004, 3.000000000000001, 5.0),
            (0.0, 0.0, 0.3420201433256687, 0.9396926207859084)),
        "OnDatum": ((1.0, 2.0, 3.0000000000000004),
            (0.0, 0.08715574274765818, 0.0, 0.9961946980917457)),
        "OnLcsXY": ((4.000000000000001, 3.000000000000001, 2.0),
            (0.0, 0.0, 0.21643961393810288, 0.9762960071199334)),
        "OnLcsYZThroughIt": ((4.0, 3.0, 1.9999999999999998),
            (0.37992819659091526, 0.5963678105290182, 0.5963678105290182, 0.3799281965909153)),
        "OnTop": ((0.0, 0.0, 5.0),
            (0.0, 0.0, 0.0, 1.0)),
        "OnXY": ((0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0)),
        "OnXZThroughOrigin": ((0.0, 0.0, 0.0),
            (0.7071067811865475, 0.0, 0.0, 0.7071067811865476)),
        "PlaneOnTop": ((1.0, 1.0, 6.0),
            (0.0, 0.0, 0.08715574274765817, 0.9961946980917455)),
    }

    def testSameBodyAttachmentsAreUnchanged(self):
        """A-t4, A-t9: within one turned Body every attachment's Placement is the one the build
        before the change computed (literals), to 1e-12."""
        objects = self.ownBody(self.doc)
        self.assertEqual(sorted(objects), sorted(self.OWN_BODY))
        for name, obj in objects.items():
            with self.subTest(name=name):
                self.assertTrue(obj.isValid(), obj.getStatusString())
                base, q = self.OWN_BODY[name]
                got = obj.Placement
                for a, b in zip(tuple(got.Base) + tuple(got.Rotation.Q), base + q):
                    self.assertAlmostEqual(a, b, delta=1e-12, msg=(name, got))

    def testSameBodyAttachmentsReopenUntouched(self):
        """A-t9: saved and reopened, nothing in the turned Body needs a recompute."""
        self.ownBody(self.doc)
        doc = self.reopen(self.doc, "own")
        self.assertEqual([o.Name for o in doc.Objects if "Touched" in o.State], [])

    # A-t5 ------------------------------------------------------------------------------------

    def testBodiesInTurnedParts(self):
        """A-t5: Body1 in App::Part PA, Body2 in App::Part PB, each Part and Body turned and
        moved: the sketch in Body2 lies on Body1's face."""
        for pair in ("Body1Moved", "Body2Moved", "BothRotated", "EqualRotated"):
            with self.subTest(pair=pair):
                doc = self.newDocument()
                first, second = PAIRS[pair]
                partA = doc.addObject("App::Part", "PA")
                partA.Placement = first
                partB = doc.addObject("App::Part", "PB")
                partB.Placement = second
                source, body, sketch, pad = self.attachedSketch(
                    doc, P(V(3, 0, 1), R(V(0, 0, 1), 15)), P(V(-2, 4, 0), R(V(1, 0, 0), 5)))
                partA.addObject(source[0])
                partB.addObject(body)
                doc.recompute()
                face = globalElement(source[1], topFace(source[1], 5))
                self.assertOnFace(sketch, face)
                self.assertStandsOnFace(pad, face, 3)

    # A-t6 ------------------------------------------------------------------------------------

    def testSketchOnADatumOnAnotherBody(self):
        """A-t6, F3's chain: a datum plane DP2 in Body2 on the top of Body1's pad, Sk2 on DP2,
        Pad2 on Sk2, Body1 at (100, 50, 20) turned 30 deg about X: Pad2 stands on the face.
        It stood at the origin."""
        source = self.source(self.doc, P(V(100, 50, 20), R(V(1, 0, 0), 30)))
        top = topFace(source[1], 5)
        body = self.doc.addObject("PartDesign::Body", "Body2")
        plane = body.newObject("PartDesign::Plane", "DP2")
        plane.AttachmentSupport = [(source[1], top)]
        plane.MapMode = "FlatFace"
        sketch = body.newObject("Sketcher::SketchObject", "Sk2")
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
        rectangle(sketch, 2, 2, 8, 8)
        pad = body.newObject("PartDesign::Pad", "Pad2")
        pad.Profile = sketch
        pad.Length = 3
        self.doc.recompute()
        face = globalElement(source[1], top)
        self.assertOnFace(plane, face)
        self.assertOnFace(sketch, face)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertStandsOnFace(pad, face, 3)

    # A-t7 ------------------------------------------------------------------------------------

    def testThreePointsFromTwoBodies(self):
        """A-t7: ThreePointsPlane through two corners of Body1's pad (global z 10) and one of
        Body3's (global z 30), the datum in a turned Body2: the plane through the three global
        points, normal (0, -2, 1)/sqrt(5)."""
        def plate(name, at, z):
            body = self.doc.addObject("PartDesign::Body", name)
            body.Placement = at
            sketch = body.newObject("Sketcher::SketchObject", name + "Sk")
            sketch.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
            sketch.MapMode = "FlatFace"
            rectangle(sketch, 0, 0, 20, 10)
            pad = body.newObject("PartDesign::Pad", name + "Pad")
            pad.Profile = sketch
            pad.Length = z
            return pad

        first = plate("Body1", P(V(0, 0, 5), R()), 5)
        third = plate("Body3", P(V(0, 10, 25), R()), 5)
        self.doc.recompute()
        body = self.doc.addObject("PartDesign::Body", "Body2")
        body.Placement = P(V(7, -3, 2), R(V(1, 1, 0), 33))
        datum = body.newObject("PartDesign::Plane", "Through")
        datum.AttachmentSupport = [(first, vertexAt(first, V(0, 0, 5))),
                                   (first, vertexAt(first, V(20, 0, 5))),
                                   (third, vertexAt(third, V(0, 0, 5)))]
        datum.MapMode = "ThreePointsPlane"
        self.doc.recompute()
        frame = datum.getGlobalPlacement()
        normal = V(0, -2, 1).normalize()
        self.assertLess(axis(frame).cross(normal).Length, TOL, frame)
        for point in (V(0, 0, 10), V(20, 0, 10), V(0, 10, 30)):
            self.assertLess(abs((frame.Base - point).dot(normal)), TOL, frame)

    # A-t8 ------------------------------------------------------------------------------------

    def reopen(self, doc, name):
        path = os.path.join(tempfile.mkdtemp(), name + ".FCStd")
        doc.saveAs(path)
        FreeCAD.closeDocument(doc.Name)
        opened = FreeCAD.openDocument(path)
        self.docs.append(opened.Name)
        return opened

    def oldFile(self):
        """A file as the build before the change saved it: Sk2 in Body2 at (30, 0, 7) on the top
        of Body1's pad, Body1 at (100, 50, 0), with Sk2 and Pad2 where that build put them (the
        face's place in Body1's coordinates, taken as Body2's). Made by attaching with both
        Bodies at Body1's placement and then moving Body2 without a recompute."""
        first, second = PAIRS["Body1Moved"][0], P(V(30, 0, 7), R())
        _, body, sketch, pad = self.attachedSketch(self.doc, first, first)
        body.Placement = second
        self.doc.purgeTouched()
        path = os.path.join(tempfile.mkdtemp(), "old.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        return path

    def testOldFileIsQueuedForRecomputeAtOpen(self):
        """A-t8: the old file's sketch moves to the face at open and is queued for recompute
        (the Pad on it is stale until then); after the recompute the Pad stands on the face."""
        doc = FreeCAD.openDocument(self.oldFile())
        self.docs.append(doc.Name)
        sketch = doc.getObject("Sk2")
        self.assertIn("Touched", sketch.State)
        doc.recompute()
        pad = doc.getObject("Pad2")
        face = globalElement(doc.getObject("Pad1"), topFace(doc.getObject("Pad1"), 5))
        self.assertOnFace(sketch, face)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertStandsOnFace(pad, face, 3)
        self.assertEqual([o.Name for o in doc.Objects if "Touched" in o.State], [])

    def testOldFileLogsTheMovedAttachments(self):
        """A-t8: opening the old file logs one line naming the attachments that will move."""
        path = self.oldFile()
        folder = os.path.dirname(path)
        script = os.path.join(folder, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("import FreeCAD\nFreeCAD.openDocument(%r)\n" % path)
        run = subprocess.run([freecadCmd(), script], cwd=folder, timeout=600, check=False,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log = run.stdout.decode("utf-8", "replace")
        lines = [line for line in log.splitlines() if "attached across containers" in line]
        self.assertEqual(len(lines), 1, log)
        self.assertIn("Sk2", lines[0])
        self.assertIn("1 object", lines[0])

    def oldDatumFile(self, kind):
        """oldFile() with F3's chain: a datum D2 (`kind`) in Body2 on the top of Body1's pad, Sk2
        on D2, Pad2 on Sk2. A Part::Datum positions itself at restore before the attachment's own
        restore step (Datum::onDocumentRestored touches AttachmentSupport)."""
        first, second = PAIRS["Body1Moved"][0], P(V(30, 0, 7), R())
        source = self.source(self.doc, first)
        body = self.doc.addObject("PartDesign::Body", "Body2")
        body.Placement = first
        datum = body.newObject(kind, "D2")
        datum.AttachmentSupport = [(source[1], topFace(source[1], 5))]
        datum.MapMode = "FlatFace"
        sketch = body.newObject("Sketcher::SketchObject", "Sk2")
        sketch.AttachmentSupport = [(datum, "")]
        sketch.MapMode = "FlatFace" if kind == "PartDesign::Plane" else "ObjectXY"
        rectangle(sketch, 2, 2, 8, 8)
        pad = body.newObject("PartDesign::Pad", "Pad2")
        pad.Profile = sketch
        pad.Length = 3
        self.doc.recompute()
        body.Placement = second
        self.doc.purgeTouched()
        path = os.path.join(tempfile.mkdtemp(), "oldDatum.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        return path

    def testOldFileWithADatumIsQueuedForRecomputeAtOpen(self):
        """A-t8, review round 1: a datum plane or coordinate system in Body2 on Body1's face moves
        at open and is queued; after the recompute the Pad on its sketch stands on the face. It
        moved unqueued, and the Pad stayed off the face after the recompute."""
        for kind in ("PartDesign::Plane", "PartDesign::CoordinateSystem"):
            with self.subTest(kind=kind):
                self.doc = self.newDocument()
                doc = FreeCAD.openDocument(self.oldDatumFile(kind))
                self.docs.append(doc.Name)
                datum = doc.getObject("D2")
                self.assertIn("Touched", datum.State)
                doc.recompute()
                face = globalElement(doc.getObject("Pad1"), topFace(doc.getObject("Pad1"), 5))
                self.assertOnFace(datum, face)
                self.assertOnFace(doc.getObject("Sk2"), face)
                pad = doc.getObject("Pad2")
                self.assertTrue(pad.isValid(), pad.getStatusString())
                self.assertStandsOnFace(pad, face, 3)
                self.assertEqual([o.Name for o in doc.Objects if "Touched" in o.State], [])
                FreeCAD.closeDocument(doc.Name)

    def testOldFileWithADatumLogsIt(self):
        """A-t8, review round 1: opening the old file with the datum logs it."""
        path = self.oldDatumFile("PartDesign::Plane")
        script = "import FreeCAD\nFreeCAD.openDocument(%r)\n" % path
        lines = [line for line in runChild(os.path.dirname(path), script)
                 if "attached across containers" in line]
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("D2", lines[0])
        self.assertIn("moved at open", lines[0])

    def testCopiedInIsNotLoggedAsOpened(self):
        """Review round 1: Body2 copied into another document with what it depends on (Pad1, but
        not Body1, which lands in the document there, so Sk2 moves) is logged as moved when
        copied in, not at open."""
        path = self.oldFile()
        script = ("import FreeCAD\n"
                  "doc = FreeCAD.openDocument(%r)\n"
                  "copy = FreeCAD.newDocument('Copy')\n"
                  "copy.copyObject(doc.getObject('Body2'), True)\n" % path)
        lines = [line for line in runChild(os.path.dirname(path), script)
                 if "attached across containers" in line]
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("moved at open", lines[0])
        self.assertIn("moved when copied in", lines[1])
        self.assertIn("Sk2", lines[1])

    def testSameBodyFileSavedStaleReopensUntouched(self):
        """A-t8: a same-Body sketch saved off its face (the pad changed without a recompute)
        reopens untouched, as before: it moves at open, as it always did."""
        body, pad = self.source(self.doc, P(V(1, 2, 3), R(V(0, 1, 0), 20)))[:2]
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(pad, topFace(pad, 5))]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        sketch.Placement = P(V(0, 0, 4), R())
        self.doc.purgeTouched()
        doc = self.reopen(self.doc, "stale")
        self.assertEqual([o.Name for o in doc.Objects if "Touched" in o.State], [])

    # A-t10 -----------------------------------------------------------------------------------

    def testReversedAndOffset(self):
        """A-t10: MapReversed and a turned, moved AttachmentOffset act in the mapped frame: on a
        datum plane (ObjectXY, both rotated) and on the face (FlatFace, Body1 moved and Body2
        moved), the frame is the one with the Bodies placed alike."""
        offset = P(V(1, -2, 3), R(V(1, 2, 0), 25))

        def setup(cs):
            cs.MapReversed = True
            cs.AttachmentOffset = offset

        for pair, mode in (("BothRotated", "ObjectXYDatumPlane"), ("Body1Moved", "FlatFace"),
                           ("Body2Moved", "FlatFace")):
            with self.subTest(pair=pair, mode=mode):
                first, second = PAIRS[pair]
                self.assertSameFrame(self.attachedFrame(first, second, mode, setup),
                                     self.attachedFrame(first, first, mode, setup), "full")

    # A-t11 -----------------------------------------------------------------------------------

    def checkThroughALink(self, transform):
        source = self.source(self.doc, P(V(10, 20, 0), R(V(0, 0, 1), 30)))
        link = self.doc.addObject("App::Link", "Link")
        link.LinkedObject = source[0]
        link.LinkTransform = transform
        link.Placement = P(V(-50, 5, 12), R(V(1, 0, 0), 20))
        top = topFace(source[1], 5)
        body = self.doc.addObject("PartDesign::Body", "Body2")
        body.Placement = P(V(30, 0, 7), R(V(0, 1, 0), 10))
        sketch = body.newObject("Sketcher::SketchObject", "Sk2")
        sketch.AttachmentSupport = [(link, f"Pad1.{top}")]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        face = Part.getShape(link, f"Pad1.{top}", needSubElement=True)
        self.assertOnFace(sketch, face)

    def testThroughALink(self):
        """A-t11: a sketch in Body2 on (Link, "Pad1.FaceN"), the Link to Body1 placed elsewhere:
        on the face where the Link shows it."""
        self.checkThroughALink(False)

    def testThroughALinkWithLinkTransform(self):
        """A-t11: the same with LinkTransform (the Link's placement and Body1's composed)."""
        self.checkThroughALink(True)

    # B-t1 ------------------------------------------------------------------------------------

    def assertAllOnFace(self, source, sketch, pad):
        face = globalElement(source[1], topFace(source[1], 5))
        self.assertOnFace(sketch, face)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertStandsOnFace(pad, face, 3)

    def testMovingEitherBodyReplacesTheSketch(self):
        """B-t1: moving Body1, then Body2, then both turned, and one recompute each: the sketch
        and Pad2 follow the face. Nothing re-ran them."""
        first, second = PAIRS["BothRotated"]
        source, body, sketch, pad = self.attachedSketch(self.doc, first, second)
        for target, placement in ((source[0], P(V(100, 50, 20), R(V(0, 1, 0), 15))),
                                  (body, P(V(-10, 3, 0), R(V(0, 0, 1), 50))),
                                  (source[0], P())):
            with self.subTest(target=target.Name, placement=placement):
                target.Placement = placement
                self.doc.recompute()
                self.assertAllOnFace(source, sketch, pad)
                self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])

    def testUndoAndRedoOfAMove(self):
        """B-t1: an undone and a redone move of Body1, each followed by a recompute."""
        self.doc.UndoMode = 1
        first, second = PAIRS["Body2Moved"]
        source, body, sketch, pad = self.attachedSketch(self.doc, first, second)
        self.doc.openTransaction("move")
        source[0].Placement = P(V(0, 0, 40), R(V(1, 0, 0), 30))
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertAllOnFace(source, sketch, pad)
        for step in (self.doc.undo, self.doc.redo):
            with self.subTest(step=step.__name__):
                step()
                self.doc.recompute()
                self.assertAllOnFace(source, sketch, pad)

    def testMovingTheContainingPartOfABody(self):
        """B-t1: Body1 in App::Part PA; moving PA re-places the sketch in Body2 on the next
        recompute. Moving PB, holding both PA and Body2, re-runs nothing (Sk2's Placement is
        bit-equal and Sk2 needs nothing)."""
        outer = self.doc.addObject("App::Part", "PB")
        partA = self.doc.addObject("App::Part", "PA")
        outer.addObject(partA)
        source, body, sketch, pad = self.attachedSketch(
            self.doc, P(V(3, 0, 1), R(V(0, 0, 1), 15)), P(V(-2, 4, 0), R()))
        partA.addObject(source[0])
        outer.addObject(body)
        self.doc.recompute()
        partA.Placement = P(V(0, 10, 30), R(V(1, 0, 0), 25))
        self.doc.recompute()
        self.assertAllOnFace(source, sketch, pad)
        before = P(sketch.Placement)
        outer.Placement = P(V(5, 5, 5), R(V(0, 1, 1), 45))
        self.assertLessEqual(self.doc.recompute(), 1, "PB alone")
        self.assertEqual(tuple(sketch.Placement.Base) + tuple(sketch.Placement.Rotation.Q),
                         tuple(before.Base) + tuple(before.Rotation.Q))
        self.assertAllOnFace(source, sketch, pad)

    def partSketchOnABox(self):
        """A Part::Box Cube (10 x 10 x 10) and a sketch Sk on its top face, both in the document,
        attached with nothing in between (the frames are the identity)."""
        box = self.doc.addObject("Part::Box", "Cube")
        self.doc.recompute()
        sketch = self.doc.addObject("Sketcher::SketchObject", "Sk")
        sketch.AttachmentSupport = [(box, "Face6")]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        self.assertOnFace(sketch, globalElement(box, "Face6"))
        return box, sketch

    def testSupportMovedIntoAContainer(self):
        """Review round 1: the box moved into an App::Part placed elsewhere after attaching; the
        sketch, in the document, follows the face on the next recompute. Nothing re-ran it: its
        frames were kept only for links across containers, and this one wasn't."""
        box, sketch = self.partSketchOnABox()
        part = self.doc.addObject("App::Part", "PA")
        part.Placement = P(V(100, 50, 0), R(V(1, 0, 0), 30))
        part.addObject(box)
        self.doc.recompute()
        self.assertOnFace(sketch, globalElement(box, "Face6"))
        self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])

    def testOwnerMovedIntoAContainer(self):
        """Review round 1: the sketch moved into an App::Part placed elsewhere after attaching;
        it stays on the box's face."""
        box, sketch = self.partSketchOnABox()
        part = self.doc.addObject("App::Part", "PB")
        part.Placement = P(V(30, 0, 7), R(V(0, 1, 0), 45))
        part.addObject(sketch)
        self.doc.recompute()
        self.assertOnFace(sketch, globalElement(box, "Face6"))
        self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])

    def testEngineWithAGoneOwnerWarns(self):
        """Review round 1: a Python AttachEngine read from a feature that is then deleted can't map
        the links into the feature's container any more: it reads them as before, and says so."""
        script = ("import FreeCAD, Part\n"
                "doc = FreeCAD.newDocument('Gone')\n"
                "part = doc.addObject('App::Part', 'PA')\n"
                "part.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 50), FreeCAD.Rotation())\n"
                "box = doc.addObject('Part::Box', 'Cube')\n"
                "doc.recompute()\n"
                "plane = part.newObject('Part::Plane', 'Attached')\n"
                "plane.AttachmentSupport = [(box, 'Face6')]\n"
                "plane.MapMode = 'FlatFace'\n"
                "doc.recompute()\n"
                "engine = Part.AttachEngine('Attacher::AttachEngine3D')\n"
                "engine.readParametersFromFeature(plane)\n"
                "doc.removeObject('Attached')\n"
                "z = engine.calculateAttachedPlacement(FreeCAD.Placement()).Base.z\n"
                "print('RESULT %.9f' % z)\n")
        lines = runChild(tempfile.mkdtemp(), script)
        # Read unmapped: the face's z in the document, not in PA (-40)
        self.assertIn("RESULT 10.000000000", lines, lines)
        self.assertTrue(any("is gone" in line and "Attached" in line for line in lines), lines)

    # B-t4 ------------------------------------------------------------------------------------

    def testMovedSavedAndReopened(self):
        """B-t4: move, recompute, save, reopen: nothing to recompute, the frames unchanged."""
        first, second = PAIRS["BothRotated"]
        source, body, sketch, pad = self.attachedSketch(self.doc, first, second)
        source[0].Placement = P(V(-20, 0, 9), R(V(1, 1, 1), 40))
        self.doc.recompute()
        frame = sketch.getGlobalPlacement()
        doc = self.reopen(self.doc, "moved")
        self.assertEqual([o.Name for o in doc.Objects if "Touched" in o.State], [])
        self.assertTrue(doc.getObject("Sk2").getGlobalPlacement().isSame(frame, 1e-9))


def runChild(folder, script):
    """The output lines of `script` run by FreeCADCmd in `folder`."""
    path = os.path.join(folder, "child.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(script)
    run = subprocess.run([freecadCmd(), path], cwd=folder, timeout=600, check=False,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return [line.strip() for line in run.stdout.decode("utf-8", "replace").splitlines()]


def freecadCmd():
    names = ("FreeCADCmd.exe", "FreeCADCmd") if sys.platform == "win32" else ("FreeCADCmd",)
    if os.path.basename(sys.executable).lower().startswith("freecadcmd"):
        return sys.executable
    for folder in ("bin", "MacOS", ""):
        for name in names:
            path = os.path.join(FreeCAD.getHomePath(), folder, name)
            if os.path.isfile(path):
                return path
    raise FileNotFoundError("FreeCADCmd next to " + FreeCAD.getHomePath())
