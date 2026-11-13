# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-CH ops#655: Transform (move, rotate, copy part) as a studio feature
(notes/transform-design.md). Designed geometry: TestStudioList.newStudio's parts A, B and C, 10 mm
boxes at x 0, 20 and 40; every expected result is the box's bounds after the motion."""

import os
import tempfile
import unittest

import FreeCAD as App
import PartDesign

from PartDesignTests.TestStudioList import newStudio, studioList

try:
    from PartDesign import TransformFeature as T
except ImportError:
    import TransformFeature as T

V = App.Vector
X_AXIS, Y_AXIS, Z_AXIS = 0, 1, 2


def bounds(shape):
    b = shape.BoundBox
    return (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)


def edgeOf(feature, a, b):
    """The name of feature's edge from a to b (either way), in its Body's frame."""
    for i, edge in enumerate(feature.Shape.Edges, 1):
        ends = {tuple(round(c, 6) for c in v.Point) for v in edge.Vertexes}
        if ends == {tuple(map(float, a)), tuple(map(float, b))}:
            return f"Edge{i}"
    raise AssertionError(f"no edge {a}-{b}")


def vertexAt(feature, point):
    for i, vertex in enumerate(feature.Shape.Vertexes, 1):
        if (vertex.Point - V(*point)).Length < 1e-9:
            return f"Vertex{i}"
    raise AssertionError(f"no vertex at {point}")


def faceAtZ(feature, z):
    for i, face in enumerate(feature.Shape.Faces, 1):
        bb = face.BoundBox
        if abs(bb.ZMin - z) < 1e-9 and abs(bb.ZMax - z) < 1e-9:
            return f"Face{i}"
    raise AssertionError(f"no face at z {z}")


class TestStudioTransform(unittest.TestCase):
    def setUp(self):
        self.doc, self.studio = newStudio("TestStudioTransform")
        studioList(self.doc)
        self.A, self.B, self.C = (self.doc.getObject(n) for n in "ABC")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assertBounds(self, shape, expected, places=6):
        for got, want in zip(bounds(shape), expected):
            self.assertAlmostEqual(got, want, places=places, msg=f"{bounds(shape)} != {expected}")

    def transform(self, parts, **values):
        """A Transform of parts, by XYZ unless a type is given (Onshape's default is by line)."""
        values.setdefault("TransformType", "Translate by XYZ")
        obj = T.make_transform(parts, **values)
        self.doc.recompute()
        return obj

    def assertValid(self, *objs):
        for obj in objs:
            self.assertTrue(obj.isValid(), f"{obj.Label}: {obj.getStatusString()}")

    # ------------------------------------------------------------------------------ the types
    def testTranslateByXYZ(self):
        t = self.transform([self.A], TransformType="Translate by XYZ", X=5, Y=7, Z=3)
        self.assertValid(t, self.A)
        self.assertBounds(self.A.Shape, (5, 7, 3, 15, 17, 13))
        self.assertAlmostEqual(self.A.Shape.Volume, 1000, places=6)
        self.assertBounds(self.B.Shape, (20, 0, 0, 30, 10, 10))

    def testTranslateByDistanceAlongAnAxis(self):
        axis = (self.A.Origin.OriginFeatures[Y_AXIS], [""])
        t = self.transform([self.A], TransformType="Translate by distance", Direction=axis, Distance=12)
        self.assertValid(t)
        self.assertBounds(self.A.Shape, (0, 12, 0, 10, 22, 10))
        t.OppositeDirection = True
        self.doc.recompute()
        self.assertBounds(self.A.Shape, (0, -12, 0, 10, -2, 10))

    def testTranslateByDistanceAlongAFaceNormal(self):
        top = (self.doc.getObject("BPad"), [faceAtZ(self.doc.getObject("BPad"), 10)])
        t = self.transform([self.A], TransformType="Translate by distance", Direction=top, Distance=4)
        self.assertValid(t)
        self.assertBounds(self.A.Shape, (0, 0, 4, 10, 10, 14))

    def testTranslateByLineMovesByItsLength(self):
        pad = self.doc.getObject("BPad")
        line = (pad, [edgeOf(pad, (20, 0, 0), (30, 0, 0))])
        t = self.transform([self.A], TransformType="Translate by line", Line=line)
        self.assertValid(t)
        forward = bounds(self.A.Shape)
        self.assertAlmostEqual(abs(forward[0]), 10, places=6)
        self.assertAlmostEqual(forward[1], 0, places=6)
        t.OppositeDirection = True
        self.doc.recompute()
        self.assertAlmostEqual(bounds(self.A.Shape)[0], -forward[0], places=6)

    def testTranslateByLineRefusesAnAxis(self):
        axis = (self.A.Origin.OriginFeatures[X_AXIS], [""])
        t = self.transform([self.A], TransformType="Translate by line", Line=axis)
        self.assertFalse(t.isValid())

    def testRotateAboutTheZAxis(self):
        axis = (self.A.Origin.OriginFeatures[Z_AXIS], [""])
        t = self.transform([self.B], TransformType="Rotate", Axis=axis, Angle=90)
        self.assertValid(t)
        self.assertBounds(self.B.Shape, (-10, 20, 0, 0, 30, 10))

    def testRotateAboutItsOwnEdge(self):
        """About A's vertical edge at (10, 0): read at the Transform's place (A's Pad), no cycle."""
        pad = self.doc.getObject("APad")
        edge = (pad, [edgeOf(pad, (10, 0, 0), (10, 0, 10))])
        t = self.transform([self.A], TransformType="Rotate", Axis=edge, Angle=90)
        self.assertValid(t, self.A)
        one = bounds(self.A.Shape)
        senses = [(0, -10, 0, 10, 0, 10), (10, 0, 0, 20, 10, 10)]
        self.assertTrue(
            any(all(abs(g - w) < 1e-6 for g, w in zip(one, s)) for s in senses), one
        )
        t.OppositeDirection = True
        self.doc.recompute()
        other = bounds(self.A.Shape)
        self.assertTrue(
            any(all(abs(g - w) < 1e-6 for g, w in zip(other, s)) for s in senses), other
        )
        self.assertNotAlmostEqual(one[0], other[0], places=3)

    def testRotateRefusesAPlanarFace(self):
        pad = self.doc.getObject("BPad")
        t = self.transform([self.A], TransformType="Rotate", Axis=(pad, [faceAtZ(pad, 10)]), Angle=90)
        self.assertFalse(t.isValid())
        self.assertIn("NO_ROTATION_AXIS", t.getStatusString())

    def testRotateRefusesAVertex(self):
        pad = self.doc.getObject("BPad")
        t = self.transform([self.A], TransformType="Rotate", Axis=(pad, [vertexAt(pad, (20, 0, 0))]))
        self.assertFalse(t.isValid())
        self.assertIn("NO_ROTATION_AXIS", t.getStatusString())

    def testRotateDefaultsToThirtyDegrees(self):
        axis = (self.A.Origin.OriginFeatures[Z_AXIS], [""])
        t = self.transform([self.B], TransformType="Rotate", Axis=axis)
        self.assertAlmostEqual(t.Angle.Value, 30)
        self.assertValid(t)

    def testDefaultTypeIsByLine(self):
        t = T.make_transform([self.A])
        self.assertEqual(t.TransformType, "Translate by line")

    def testTranslateByTwoVertices(self):
        """From the first vertex picked to the second (TR2)."""
        pad = self.doc.getObject("BPad")
        line = (pad, [vertexAt(pad, (30, 0, 0)), vertexAt(pad, (20, 0, 10))])
        t = self.transform([self.A], TransformType="Translate by line", Line=line)
        self.assertValid(t)
        self.assertBounds(self.A.Shape, (-10, 0, 10, 0, 10, 20))

    def testTranslateByDistanceZeroIsOutOfRange(self):
        axis = (self.A.Origin.OriginFeatures[Y_AXIS], [""])
        t = self.transform([self.A], TransformType="Translate by distance", Direction=axis, Distance=0)
        self.assertFalse(t.isValid())
        self.assertIn("PARAMETER_OUT_OF_RANGE", t.getStatusString())

    def testTranslateByDistanceRefusesAVertex(self):
        pad = self.doc.getObject("BPad")
        t = self.transform(
            [self.A], TransformType="Translate by distance",
            Direction=(pad, [vertexAt(pad, (20, 0, 0))]), Distance=5,
        )
        self.assertFalse(t.isValid())
        self.assertIn("TRANSFORM_TRANSLATE_BY_DISTANCE_INPUT", t.getStatusString())

    def testTranslateByDistanceAlongTheBottomFaceGoesDown(self):
        """A planar face's outward normal (TR3: the bottom face moves it down)."""
        pad = self.doc.getObject("BPad")
        t = self.transform(
            [self.A], TransformType="Translate by distance", Direction=(pad, [faceAtZ(pad, 0)]), Distance=5
        )
        self.assertValid(t)
        self.assertBounds(self.A.Shape, (0, 0, -5, 10, 10, 5))

    def testZeroAngleIsNoMotion(self):
        axis = (self.A.Origin.OriginFeatures[Z_AXIS], [""])
        t = self.transform([self.B], TransformType="Rotate", Axis=axis, Angle=0)
        self.assertValid(t)
        self.assertBounds(self.B.Shape, (20, 0, 0, 30, 10, 10))

    def testCopyInPlace(self):
        t = T.make_transform([self.B], TransformType="Copy in place")
        self.doc.recompute()
        self.assertValid(t)
        copies = T.made_parts(t)
        self.assertEqual(len(copies), 1)
        self.assertBounds(copies[0].Shape, (20, 0, 0, 30, 10, 10))
        self.assertBounds(self.B.Shape, (20, 0, 0, 30, 10, 10))

    def testRotateWithoutAnAxisFails(self):
        t = self.transform([self.A], TransformType="Rotate", Angle=90)
        self.assertFalse(t.isValid())

    def testMateConnectors(self):
        a = self.doc.addObject("App::LocalCoordinateSystem", "From")
        b = self.doc.addObject("App::LocalCoordinateSystem", "To")
        self.studio.addObject(a)
        self.studio.addObject(b)
        a.Placement = App.Placement(V(10, 0, 0), App.Rotation())
        b.Placement = App.Placement(V(0, 0, 20), App.Rotation(V(0, 0, 1), 90))
        t = self.transform(
            [self.A], TransformType="Transform by mate connectors", FromConnector=a, ToConnector=b
        )
        self.assertValid(t)
        # (x, y) -> (x - 10, y) about the From frame, then rotated 90 and lifted 20: x -10..0, y -10..0
        self.assertBounds(self.A.Shape, (-10, -10, 20, 0, 0, 30))

    def testZeroIsNoMotion(self):
        t = self.transform([self.A], TransformType="Translate by XYZ")
        self.assertValid(t)
        self.assertBounds(self.A.Shape, (0, 0, 0, 10, 10, 10))

    # ------------------------------------------------------------------------------ the parts
    def testSeveralPartsAtOnce(self):
        t = self.transform([self.A, self.B], Y=30)
        self.assertValid(t)
        self.assertBounds(self.A.Shape, (0, 30, 0, 10, 40, 10))
        self.assertBounds(self.B.Shape, (20, 30, 0, 30, 40, 10))
        self.assertBounds(self.C.Shape, (40, 0, 0, 50, 10, 10))
        steps = [PartDesign.studioStepOf(t, b) for b in (self.A, self.B, self.C)]
        self.assertIsNotNone(steps[0])
        self.assertIsNotNone(steps[1])
        self.assertIsNone(steps[2])

    def testNoPartsFails(self):
        with self.assertRaises(Exception):
            T.make_transform([])
        t = self.transform([self.A], X=5)
        t.StudioScope = []
        self.doc.recompute()
        self.assertFalse(t.isValid())

    def testAMovedPartOverlappingAnotherStaysTwoParts(self):
        t = self.transform([self.A], X=15)
        self.assertValid(t)
        self.assertBounds(self.A.Shape, (15, 0, 0, 25, 10, 10))
        self.assertBounds(self.B.Shape, (20, 0, 0, 30, 10, 10))
        self.assertEqual(len(PartDesign.studioLiveParts(self.A)), 3)

    def testNamesKept(self):
        pad = self.doc.getObject("APad")
        before = sorted(pad.Shape.ElementMap.items())
        self.transform([self.A], X=5, Y=5)
        step = self.A.Tip
        self.assertEqual(sorted(step.Shape.ElementMap.items()), before)

    def testLaterReferenceFollowsTheMovedFace(self):
        """A second Transform by the moved A's top face normal reads A after the first."""
        t1 = self.transform([self.A], Z=5)
        step = PartDesign.studioStepOf(t1, self.A)
        top = (step, [faceAtZ(step, 15)])
        t2 = self.transform([self.B], TransformType="Translate by distance", Direction=top, Distance=3)
        self.assertValid(t1, t2)
        self.assertBounds(self.B.Shape, (20, 0, 3, 30, 10, 13))
        t1.Z = 7
        self.doc.recompute()
        self.assertValid(t2)
        self.assertEqual(faceAtZ(step, 17), top[1][0])

    def testSketchOnAMovedFaceKeepsItsWorldPositionInThePlane(self):
        """ops#679, Onshape TR11: a sketch on the moved A's top face keeps its world position within
        the face's plane, and only the plane follows the face. A by Y 30, a 6 x 6 boss (Add 5, scope
        A) sketched at x 2..8, y 32..38 on A's top: A 1180. The Transform to Y 60: the sketch stays at
        y 32..38 on z 10, off A. Onshape makes the boss a new part there (INFO BOOLEAN_UNION_NO_OP);
        the fork's Add fails loudly instead, as for any tool off its scope (parts are made by
        command, never by recompute). To Y 30, Z 5: the sketch rises with the face to z 15 and the
        boss is on A again. The rule is the new sketch's default MapOrigin "Body" (ops#311); the
        stock "Feature" origin moves the sketch along with the face."""
        from PartDesignTests.TestStudio import rect
        from PartDesignTests.TestStudioOwner import makeOwner

        t = self.transform([self.A], Y=30)
        step = PartDesign.studioStepOf(t, self.A)
        sk = self.doc.addObject("Sketcher::SketchObject", "Sk")
        self.studio.addObject(sk)
        sk.AttachmentSupport = [(step, faceAtZ(step, 10))]
        sk.MapMode = "FlatFace"
        self.assertEqual(sk.MapOrigin, "Body")
        rect(sk, 2, 32, 8, 38)
        self.doc.recompute()
        boss = makeOwner(self.doc, self.studio, "Pad", "Boss", sk, ("A",), Length=5)
        self.doc.recompute()
        self.assertValid(boss)
        self.assertBounds(sk.Shape, (2, 32, 10, 8, 38, 10))
        self.assertAlmostEqual(self.A.Shape.Volume, 1180, places=6)

        t.Y = 60
        self.doc.recompute()
        self.assertBounds(self.A.Shape, (0, 60, 0, 10, 70, 10))
        self.assertBounds(sk.Shape, (2, 32, 10, 8, 38, 10))
        self.assertFalse(boss.isValid())
        self.assertIn("touches no part of the merge scope", boss.getStatusString())

        t.Y, t.Z = 30, 5
        self.doc.recompute()
        self.assertBounds(sk.Shape, (2, 32, 15, 8, 38, 15))
        self.assertValid(boss)
        self.assertBounds(self.A.Shape, (0, 30, 5, 10, 40, 20))
        self.assertAlmostEqual(self.A.Shape.Volume, 1180, places=6)

    # ------------------------------------------------------------------------------ Copy part
    def testCopyPart(self):
        t = self.transform([self.A], copy=True, Y=20)
        self.assertValid(t)
        copies = T.made_parts(t)
        self.assertEqual(len(copies), 1)
        self.assertValid(copies[0])
        self.assertBounds(self.A.Shape, (0, 0, 0, 10, 10, 10))
        self.assertBounds(copies[0].Shape, (0, 20, 0, 10, 30, 10))
        self.assertEqual(len(PartDesign.studioLiveParts(self.A)), 4)

    def testCopyOfSeveralParts(self):
        t = self.transform([self.A, self.C], copy=True, Z=10)
        copies = T.made_parts(t)
        self.assertEqual(len(copies), 2)
        got = sorted(bounds(c.Shape) for c in copies)
        want = sorted([(0, 0, 10, 10, 10, 20), (40, 0, 10, 50, 10, 20)])
        for g, w in zip(got, want):
            for a, b in zip(g, w):
                self.assertAlmostEqual(a, b, places=6)

    def testCopyHasNamesOfItsOwn(self):
        t = self.transform([self.A], copy=True, Y=20)
        copy = T.made_parts(t)[0]
        # the mapped names (the keys; the values are the indexed names Face1..., the same for any box)
        source = set(self.A.Shape.ElementMap.keys())
        names = set(copy.Shape.ElementMap.keys())
        self.assertTrue(names)
        self.assertFalse(names & source)

    def testCopyFollowsWhatComesBeforeIt(self):
        t = self.transform([self.A], copy=True, Y=20)
        self.doc.getObject("APad").Length = 15
        self.doc.recompute()
        self.assertBounds(T.made_parts(t)[0].Shape, (0, 20, 0, 10, 30, 15))

    def testCopyDoesNotFollowWhatComesAfter(self):
        t = self.transform([self.A], copy=True, Y=20)
        later = self.transform([self.A], X=100)
        self.assertValid(later)
        self.assertBounds(self.A.Shape, (100, 0, 0, 110, 10, 10))
        self.assertBounds(T.made_parts(t)[0].Shape, (0, 20, 0, 10, 30, 10))

    def testCopyOffRemovesTheCopies(self):
        t = self.transform([self.A, self.B], copy=True, Y=20)
        self.assertEqual(len(T.made_parts(t)), 2)
        T.set_copy(t, False)
        self.doc.recompute()
        self.assertEqual(T.made_parts(t), [])
        self.assertBounds(self.A.Shape, (0, 20, 0, 10, 30, 10))

    def testUnpickingASourceRemovesItsCopy(self):
        t = self.transform([self.A, self.B], copy=True, Y=20)
        T.set_parts(t, [self.B])
        self.doc.recompute()
        copies = T.made_parts(t)
        self.assertEqual(len(copies), 1)
        self.assertBounds(copies[0].Shape, (20, 20, 0, 30, 30, 10))
        self.assertValid(t, copies[0])

    # ------------------------------------------------------------------------------ the history
    def testSuppressPutsThePartsBack(self):
        t = self.transform([self.A], X=5)
        t.Suppressed = True
        self.doc.recompute()
        self.assertBounds(self.A.Shape, (0, 0, 0, 10, 10, 10))

    def testSuppressedCopyIsNotLive(self):
        t = self.transform([self.A], copy=True, Y=20)
        t.Suppressed = True
        PartDesign.studioReconcile(studioList(self.doc))
        self.doc.recompute()
        self.assertEqual(len(PartDesign.studioLiveParts(self.A)), 3)

    def testUndoRedo(self):
        self.doc.openTransaction("Transform")
        t = T.make_transform([self.A], TransformType="Translate by XYZ", X=5)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertBounds(self.A.Shape, (5, 0, 0, 15, 10, 10))
        self.doc.undo()
        self.doc.recompute()
        self.assertBounds(self.A.Shape, (0, 0, 0, 10, 10, 10))
        self.doc.redo()
        self.doc.recompute()
        self.assertBounds(self.A.Shape, (5, 0, 0, 15, 10, 10))

    def testReopen(self):
        t = self.transform([self.A], copy=True, X=3, Y=20)
        owner = t.Name
        path = os.path.join(tempfile.mkdtemp(), "transform.FCStd")
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = App.openDocument(path)
        self.doc.recompute()
        t = self.doc.getObject(owner)
        self.assertValid(t)
        copy = T.made_parts(t)[0]
        self.assertBounds(copy.Shape, (3, 20, 0, 13, 30, 10))
        self.assertBounds(self.doc.getObject("A").Shape, (0, 0, 0, 10, 10, 10))
        t.Y = 40
        self.doc.recompute()
        self.assertBounds(copy.Shape, (3, 40, 0, 13, 50, 10))

    # ------------------------------------------------------------------------------ Scale (ops#677)
    def scaleAbout(self, parts, point, copy=False, **values):
        return self.transform(parts, copy=copy, TransformType="Scale", ScalePoint=point, **values)

    def origin(self):
        pad = self.doc.getObject("APad")
        return (pad, [vertexAt(pad, (0, 0, 0))])

    def testTypesInOnshapesOrder(self):
        self.assertEqual(
            T.TYPES,
            ["Translate by line", "Translate by distance", "Translate by XYZ",
             "Transform by mate connectors", "Rotate", "Copy in place", "Scale"],
        )

    def testScaleUniformlyAboutAVertex(self):
        t = self.scaleAbout([self.A], self.origin(), Scale=2)
        self.assertValid(t, self.A)
        self.assertBounds(self.A.Shape, (0, 0, 0, 20, 20, 20))
        self.assertAlmostEqual(self.A.Shape.Volume, 8000, places=6)
        self.assertBounds(self.B.Shape, (20, 0, 0, 30, 10, 10))

    def testScaleUniformlyIsTheDefault(self):
        t = self.scaleAbout([self.A], self.origin(), Scale=3, ScaleX=5)
        self.assertTrue(t.ScaleUniformly)
        self.assertBounds(self.A.Shape, (0, 0, 0, 30, 30, 30))

    def testScaleAboutAMateConnector(self):
        c = self.doc.addObject("App::LocalCoordinateSystem", "Centre")
        self.studio.addObject(c)
        c.Placement = App.Placement(V(5, 5, 5), App.Rotation())
        t = self.scaleAbout([self.A], (c, [""]), Scale=2)
        self.assertValid(t)
        self.assertBounds(self.A.Shape, (-5, -5, -5, 15, 15, 15))

    def testScaleNonUniformly(self):
        t = self.scaleAbout([self.A], self.origin(), ScaleUniformly=False, ScaleX=2, ScaleY=1, ScaleZ=3)
        self.assertValid(t, self.A)
        self.assertBounds(self.A.Shape, (0, 0, 0, 20, 10, 30))
        self.assertAlmostEqual(self.A.Shape.Volume, 6000, places=6)

    def testScaleNonUniformlyAlongTheConnectorsAxes(self):
        # the connector's X runs along the world Y: factor 2 on X stretches A in y
        c = self.doc.addObject("App::LocalCoordinateSystem", "Turned")
        self.studio.addObject(c)
        c.Placement = App.Placement(V(), App.Rotation(V(0, 0, 1), 90))
        t = self.scaleAbout([self.A], (c, [""]), ScaleUniformly=False, ScaleX=2, ScaleY=1, ScaleZ=1)
        self.assertValid(t)
        self.assertBounds(self.A.Shape, (0, 0, 0, 10, 20, 10))

    def testScaledPartKeepsItsNames(self):
        pad = self.doc.getObject("APad")
        before = set(pad.Shape.ElementMap.keys())
        self.scaleAbout([self.A], self.origin(), Scale=2)
        self.assertEqual(set(self.A.Tip.Shape.ElementMap.keys()), before)

    def testScaleCopyPart(self):
        t = self.scaleAbout([self.A], self.origin(), copy=True, Scale=2)
        self.assertValid(t)
        copies = T.made_parts(t)
        self.assertEqual(len(copies), 1)
        self.assertValid(copies[0])
        self.assertBounds(self.A.Shape, (0, 0, 0, 10, 10, 10))
        self.assertBounds(copies[0].Shape, (0, 0, 0, 20, 20, 20))
        self.assertFalse(set(copies[0].Shape.ElementMap.keys()) & set(self.A.Shape.ElementMap.keys()))

    def testScaleZeroIsOutOfRange(self):
        t = self.scaleAbout([self.A], self.origin(), Scale=0)
        self.assertFalse(t.isValid())
        self.assertIn("PARAMETER_OUT_OF_RANGE", t.getStatusString())

    def testScaleWithoutAPointFails(self):
        t = self.transform([self.A], TransformType="Scale", Scale=2)
        self.assertFalse(t.isValid())
        self.assertIn("point", t.getStatusString())

    def testScaleSuppressedPutsThePartBack(self):
        t = self.scaleAbout([self.A], self.origin(), Scale=2)
        t.Suppressed = True
        self.doc.recompute()
        self.assertBounds(self.A.Shape, (0, 0, 0, 10, 10, 10))

    # ------------------------------------------------------------------- surfaces (ops#678, TR10)
    def sheetPart(self):
        """Part D, a sheet: an Offset surface 5 above A's top face (x 0..10, y 0..10 at z 15)."""
        try:
            from PartDesign import SolidOpsFeatures as S
        except ImportError:
            import SolidOpsFeatures as S
        pad = self.doc.getObject("APad")
        D = self.doc.addObject("PartDesign::Body", "D")
        self.studio.addObject(D)
        S.make_offset_surface(D, [(pad, [faceAtZ(pad, 10)])], 5.0)
        self.doc.recompute()
        PartDesign.studioReconcile(studioList(self.doc))
        self.doc.recompute()
        self.assertIn(D, PartDesign.studioLiveParts(self.A))
        self.assertEqual((len(D.Shape.Solids), len(D.Shape.Faces)), (0, 1))
        return D

    def assertSheet(self, shape, expected, area):
        self.assertBounds(shape, expected)
        self.assertEqual((len(shape.Solids), len(shape.Faces)), (0, 1))
        self.assertAlmostEqual(shape.Area, area, places=6)

    def testSheetPartMoves(self):
        """TR10: Onshape's Transform moves a surface as it moves a solid; the sheet keeps its names."""
        D = self.sheetPart()
        before = sorted(D.Tip.Shape.ElementMap.items())
        t = self.transform([D], X=30)
        self.assertValid(t, D.Tip)
        self.assertSheet(D.Shape, (30, 0, 15, 40, 10, 15), 100)
        self.assertEqual(sorted(D.Tip.Shape.ElementMap.items()), before)

    def testSheetPartRotates(self):
        D = self.sheetPart()
        t = self.transform([D], TransformType="Rotate", Axis=(D.Origin.OriginFeatures[2], [""]), Angle=90)
        self.assertValid(t, D.Tip)
        self.assertSheet(D.Shape, (-10, 0, 15, 0, 10, 15), 100)

    def testSheetPartCopy(self):
        D = self.sheetPart()
        t = self.transform([D], copy=True, Y=30)
        self.assertValid(t, D.Tip)
        self.assertSheet(D.Shape, (0, 0, 15, 10, 10, 15), 100)
        copy = T.made_parts(t)[0]
        self.assertValid(copy.Tip)
        self.assertSheet(copy.Shape, (0, 30, 15, 10, 40, 15), 100)

    def testSheetPartScales(self):
        D = self.sheetPart()
        t = self.scaleAbout([D], self.origin(), Scale=2)
        self.assertValid(t, D.Tip)
        self.assertSheet(D.Shape, (0, 0, 30, 20, 20, 30), 400)

    def testWirePartMoves(self):
        """TR10: a curve (wire body) moves too. No feature of the line makes one yet; a polyline
        feature stands in: (0,0,20)-(10,0,20)-(10,10,20)."""
        E = self.doc.addObject("PartDesign::Body", "E")
        self.studio.addObject(E)
        wire = self.doc.addObject("PartDesign::FeaturePython", "Polyline")
        _Polyline(wire)
        E.addObject(wire)
        self.doc.recompute()
        PartDesign.studioReconcile(studioList(self.doc))
        self.doc.recompute()
        self.assertIn(E, PartDesign.studioLiveParts(self.A))
        t = self.transform([E], X=5, Z=-20)
        self.assertValid(t, E.Tip)
        self.assertBounds(E.Shape, (5, 0, 0, 15, 10, 0))
        self.assertEqual((len(E.Shape.Faces), len(E.Shape.Edges)), (0, 2))


class _Polyline:
    """A wire body, for testWirePartMoves."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        import Part

        obj.Shape = Part.makePolygon([V(0, 0, 20), V(10, 0, 20), V(10, 10, 20)])

    def dumps(self):
        return None

    def loads(self, state):
        return None
