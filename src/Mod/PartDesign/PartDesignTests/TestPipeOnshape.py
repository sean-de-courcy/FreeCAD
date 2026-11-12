# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: PartDesign Pipe as Onshape's Sweep, slice 1 (notes\sweep-design.md, decision 344).
#
# Designed geometry only; every expected value is geometric. Where Onshape's answer is still pending from
# the oracle (SWn), the test says so and holds FreeCAD-CH's chosen behaviour (the loud one where unsure).

import math
import unittest

import FreeCAD
import Part

from PartDesignTests.Scenarios import models

App = FreeCAD
V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))  # sketch (x, y) -> (x, 0, y)
AREA = 4 * math.pi  # circle r 2


def arc3(a, centre, b):
    """The arc from a to b about centre (a quarter or less), through its midpoint."""
    a, centre, b = V(*a), V(*centre), V(*b)
    r = (a - centre).Length
    mid = (a - centre) + (b - centre)
    mid.normalize()
    return Part.Arc(a, centre + mid * r, b)


class PipeCase(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PartDesignTestPipeOnshape")
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sketch(self, name, geometry, **placement):
        return models.sketch(self.doc, name, geometry, self.body, **placement)

    def circle(self, x=0, y=0, r=2, name="Profile", **placement):
        return self.sketch(name, [models.circle(x, y, r)], **placement)

    def line(self, start=0, end=20, name="Path"):
        """Along Z from z = start to z = end."""
        return self.sketch(name, models.polyline([(0, start), (0, end)]), placement=XZ)

    def pipe(self, profile, spine, kind="AdditivePipe", more=(), **properties):
        pipe = self.body.newObject("PartDesign::" + kind, "Pipe")
        pipe.Profile = profile
        pipe.Spine = spine if isinstance(spine, tuple) else (spine, [])
        if more:
            pipe.SpineMore = [m if isinstance(m, tuple) else (m, "") for m in more]  # (m, []) adds nothing
        for name, value in properties.items():
            setattr(pipe, name, value)
        self.doc.recompute()
        return pipe

    def assertSweeps(self, pipe, volume=None, places=3):
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        if volume is not None:
            self.assertAlmostEqual(pipe.Shape.Volume, volume, places)

    def assertStops(self, pipe, *words):
        """Invalid, with a message holding each word (case-insensitive)."""
        self.assertFalse(pipe.isValid(), "expected a stop")
        message = pipe.getStatusString()
        for word in words:
            self.assertIn(word.lower(), message.lower(), message)

    def assertHasVertices(self, shape, points, tolerance=1e-3):
        for point in points:
            point = V(*point)
            nearest = min((v.Point - point).Length for v in shape.Vertexes)
            self.assertLess(nearest, tolerance, (point, sorted(tuple(round(c, 3) for c in v.Point)
                                                              for v in shape.Vertexes)))


class TestPipeToolCheck(PipeCase):
    """A sweep tighter than its profile (the path bends with a smaller radius than the profile reaches)
    folds over itself: OCCT returns a solid of negative volume that BRepCheck passes. It stops loudly,
    naming the place (skeptic c721, finding 1). Onshape refuses a self-intersecting sweep."""

    def tightArc(self, radius):
        """A quarter arc in XZ from the origin (tangent +Z) bending towards +X with the radius."""
        return self.sketch("Path", [arc3((0, 0, 0), (radius, 0, 0), (radius, radius, 0))], placement=XZ)

    def testTighterThanTheProfileStops(self):
        pipe = self.pipe(self.circle(), self.tightArc(1.5))
        self.assertStops(pipe, "over itself", "(")

    def testTighterThanTheProfileStopsInFrenetToo(self):
        pipe = self.pipe(self.circle(), self.tightArc(1.5), Mode="Frenet")
        self.assertStops(pipe, "over itself")

    def testRemoveTighterThanTheProfileStops(self):
        models.pad(self.body, self.sketch("Block", models.rectangle(-10, -10, 10, 10), z=-5), 10)
        self.doc.recompute()
        pipe = self.pipe(self.circle(), self.tightArc(1.5), kind="SubtractivePipe")
        self.assertStops(pipe, "over itself")

    def testLooserThanTheProfileSweeps(self):
        """Radius 3 > 2: Pappus, area x the centroid's path (a quarter of radius 3)."""
        pipe = self.pipe(self.circle(), self.tightArc(3))
        self.assertSweeps(pipe, AREA * 3 * math.pi / 2)


class TestPipeProfileControl(PipeCase):
    """`ProfileControl` drives `Mode`: None = Onshape's frame (hypothesis until SW3 and SW16: Frenet where
    it is defined and stays put, else the minimal-roll frame), Keep orientation = a translation in the
    profile's own plane, stopping where the path turns edge-on to it."""

    def quarterArc(self):
        """SW2: r 20, centre (20, 0, 0), from the origin (tangent +Z) to (20, 0, 20)."""
        return self.sketch("Path", [arc3((0, 0, 0), (20, 0, 0), (20, 20, 0))], placement=XZ)

    def testNoneFollowsAPlanarArc(self):
        """Pappus: area x a quarter of radius 20."""
        self.assertSweeps(self.pipe(self.circle(), self.quarterArc(), ProfileControl="None"), AREA * 10 * math.pi)

    def testKeepOrientationTranslatesAlongAPlanarArc(self):
        """A translation: area x the rise along the profile's normal (20)."""
        pipe = self.pipe(self.circle(), self.quarterArc(), ProfileControl="Keep orientation")
        self.assertSweeps(pipe, AREA * 20)

    def testKeepOrientationUsesTheProfilesPlane(self):
        """A profile on Front (normal -Y) along a path along +Y: not edge-on to the profile's plane, so it
        sweeps (with the global Z frame it read as edge-on and stopped)."""
        profile = self.circle(placement=XZ)
        path = self.sketch("Path", models.polyline([(0, 0), (0, 20)]))  # Top: (0,0,0)-(0,20,0)
        pipe = self.pipe(profile, path, ProfileControl="Keep orientation")
        self.assertSweeps(pipe, AREA * 20)
        box = pipe.Shape.BoundBox
        self.assertAlmostEqual(box.YMin, 0, 4)
        self.assertAlmostEqual(box.YMax, 20, 4)

    def testKeepOrientationKeepsATiltedProfilesTilt(self):
        """A circle tilted 30 degrees about X, translated 20 along Z: area x 20 x cos 30."""
        tilted = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 30))
        pipe = self.pipe(self.circle(placement=tilted), self.line(), ProfileControl="Keep orientation")
        self.assertSweeps(pipe, AREA * 20 * math.cos(math.radians(30)))

    def testKeepOrientationStopsWhereThePathTurnsEdgeOn(self):
        """SW4's path: up 10, a quarter arc r 10 to (10, 0, 20), then along +X: edge-on to a Top profile."""
        path = self.sketch("Path", [Part.LineSegment(V(0, 0, 0), V(0, 10, 0)),
                                    arc3((0, 10, 0), (10, 10, 0), (10, 20, 0)),
                                    Part.LineSegment(V(10, 20, 0), V(30, 20, 0))], placement=XZ)
        pipe = self.pipe(self.circle(), path, ProfileControl="Keep orientation")
        self.assertStops(pipe, "edge-on", "(")

    def testNoneCarriesAnAsymmetricProfileWithoutRollOnAThreeDPath(self):
        """SW16 (Onshape: 165.664 and these vertices, no roll): a line up Z, a quarter arc to +X, a
        quarter arc at z = 20 to +Y; a triangle with legs 4 (X) and 2 (Y), right angle at (-1, -1).
        Carried without roll, the end face's right angle is at (21, 10, 21), the 4 leg's end at
        (21, 10, 17), the 2 leg's end at (19, 10, 21). The path comes from two sketches."""
        first = self.sketch("Path", [Part.LineSegment(V(0, 0, 0), V(0, 10, 0)),
                                     arc3((0, 10, 0), (10, 10, 0), (10, 20, 0))], placement=XZ)
        second = self.sketch("Path001", [arc3((10, 0, 0), (10, 10, 0), (20, 10, 0))], z=20)
        profile = self.sketch("Profile", models.polygon([(-1, -1), (3, -1), (-1, 1)]))
        pipe = self.pipe(profile, first, more=[second], ProfileControl="None")
        self.assertSweeps(pipe, 165.664)
        self.assertHasVertices(pipe.Shape, [(21, 10, 21), (21, 10, 17), (19, 10, 21)])
        # Keep orientation: Onshape fails (SWEEP_FAILED); the path turns edge-on to the profile
        pipe.ProfileControl = "Keep orientation"
        self.doc.recompute()
        self.assertStops(pipe, "edge-on")

    def testNoneKeepsASquareRadialAlongAHelix(self):
        """SW3 (pending): a 1 x 1 square on Front at the helix start, one side on the cylinder r 10;
        helix pitch 2, height 10 (5 turns). In the helix's own frame the square stays radial, so the end
        face is the start face 10 higher (the minimal-roll frame drifts: FreeCAD-CH's Standard)."""
        helix = self.doc.addObject("Part::Helix", "Helix")
        helix.Pitch, helix.Height, helix.Radius = 2, 10, 10
        self.doc.recompute()
        profile = self.sketch("Profile", models.rectangle(10, -0.5, 11, 0.5), placement=XZ)
        pipe = self.pipe(profile, (helix, ["Edge1"]), ProfileControl="None")
        self.assertSweeps(pipe)
        self.assertHasVertices(pipe.Shape, [(10, 0, 9.5), (11, 0, 9.5), (11, 0, 10.5), (10, 0, 10.5)])


class TestPipeExtendToFullPath(PipeCase):
    """`ExtendToFullPath` (Onshape, SW0 and SW1): off by default; a profile in the middle of the path then
    sweeps one way from it, against the profile's normal (a Top circle on a line along Z sweeps -Z, whichever
    way the line is drawn; at a joint, the segment below it), the other way with `PathReversed`. On, it
    sweeps both ways along all of the path, as Pipe did before (a file without the property reads on).
    SW1b: against the profile plane's normal whatever the pick order or the lines' way."""

    def sw4Path(self, reversedOrder=False):
        """SW4's path shifted so the joint of its first two segments is at the origin: a line up to the
        origin from z = -10, a quarter arc r 10 to (10, 0, 10), a line to (30, 0, 10)."""
        geometry = [Part.LineSegment(V(0, -10, 0), V(0, 0, 0)),
                    arc3((0, 0, 0), (10, 0, 0), (10, 10, 0)),
                    Part.LineSegment(V(10, 10, 0), V(30, 10, 0))]
        return self.sketch("Path", geometry[::-1] if reversedOrder else geometry, placement=XZ)

    def testOffByDefault(self):
        self.assertFalse(self.pipe(self.circle(), self.line(0, 20)).ExtendToFullPath)

    def testOnSweepsBothWaysFromTheMiddle(self):
        pipe = self.pipe(self.circle(), self.line(-10, 10), ExtendToFullPath=True)
        self.assertSweeps(pipe, AREA * 20)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMin, -10, 4)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMax, 10, 4)

    def testOffAtTheStartSweepsTheWholePath(self):
        self.assertSweeps(self.pipe(self.circle(), self.line(0, 20), ExtendToFullPath=False), AREA * 20)

    def testOffAtTheFarEndSweepsTheWholePath(self):
        self.assertSweeps(self.pipe(self.circle(), self.line(20, 0), ExtendToFullPath=False), AREA * 20)

    def assertZ(self, pipe, low, high):
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMin, low, 4)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMax, high, 4)

    def testOffInTheMiddleSweepsAgainstTheNormal(self):
        """SW1: 125.664, z -10..0."""
        pipe = self.pipe(self.circle(), self.line(-10, 10))
        self.assertSweeps(pipe, AREA * 10)
        self.assertZ(pipe, -10, 0)

    def testOffInTheMiddleSweepsTheSameWayWhenTheLineIsDrawnTheOtherWay(self):
        pipe = self.pipe(self.circle(), self.line(10, -10))
        self.assertSweeps(pipe, AREA * 10)
        self.assertZ(pipe, -10, 0)

    def testOppositeDirectionFlipsIt(self):
        """SW1: pathOppositeDirection gives z 0..10."""
        pipe = self.pipe(self.circle(), self.line(-10, 10), PathReversed=True)
        self.assertSweeps(pipe, AREA * 10)
        self.assertZ(pipe, 0, 10)

    def testOffAtAJointSweepsTheSegmentBelow(self):
        """SW1's 3-segment path, profile at the joint of segments 1 and 2: off, segment 1 only (125.664)."""
        pipe = self.pipe(self.circle(), self.sw4Path())
        self.assertSweeps(pipe, AREA * 10)
        self.assertZ(pipe, -10, 0)

    def testOnAtAJointSweepsAllOfIt(self):
        """SW1: on, 574.383 = area x (10 + 5 pi + 20): the whole path."""
        pipe = self.pipe(self.circle(), self.sw4Path(), ExtendToFullPath=True)
        self.assertSweeps(pipe, AREA * (10 + 5 * math.pi + 20), 2)

    def testOffFollowsTheProfilesNormalNotThePicks(self):
        """SW1b (c): the path's segments picked 3, 2, 1, a profile whose normal is -Z: segments 2 and 3
        (448.720, box (-2, -2, 0)-(30, 2, 12))."""
        flipped = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 180))
        pipe = self.pipe(self.circle(placement=flipped), self.sw4Path(reversedOrder=True))
        self.assertSweeps(pipe, AREA * (5 * math.pi + 20), 2)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMin, 0, 4)
        self.assertAlmostEqual(pipe.Shape.BoundBox.XMax, 30, 4)

    def testOppositeDirectionChangesNothingWhenExtended(self):
        pipe = self.pipe(self.circle(), self.line(-10, 10), ExtendToFullPath=True, PathReversed=True)
        self.assertSweeps(pipe, AREA * 20)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMin, -10, 4)


class TestPipeProfilePlacement(PipeCase):
    """The profile's foot point on the path (skeptic c721, finding 3): a profile whose nearest point on
    the path is ambiguous stops loudly instead of sweeping something degenerate. Off the path, near or
    far, it keeps its offset (Onshape, SW5)."""

    def testProfileAtTheCentreOfASemicircleStops(self):
        path = self.sketch("Path", [Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10), 0, math.pi)],
                           placement=XZ)
        self.assertStops(self.pipe(self.circle(), path), "nearest")

    def testProfileBesideThePathKeepsItsOffset(self):
        """SW5: a circle r 2 at (5, 0): x 3..7, z 0..20, 251.327."""
        pipe = self.pipe(self.circle(5, 0), self.line())
        self.assertSweeps(pipe, AREA * 20)
        self.assertAlmostEqual(pipe.Shape.BoundBox.XMin, 3, 4)
        self.assertAlmostEqual(pipe.Shape.BoundBox.XMax, 7, 4)

    def testProfileBelowThePathKeepsItsOffset(self):
        """SW5: a circle r 2 on a plane 5 below Top: z -5..15."""
        pipe = self.pipe(self.circle(z=-5), self.line())
        self.assertSweeps(pipe, AREA * 20)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMin, -5, 4)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMax, 15, 4)

    def testProfileNearThePathKeepsItsOffset(self):
        pipe = self.pipe(self.circle(1, 0), self.line())
        self.assertSweeps(pipe, AREA * 20)
        self.assertAlmostEqual(pipe.Shape.BoundBox.XMin, -1, 4)
        self.assertAlmostEqual(pipe.Shape.BoundBox.XMax, 3, 4)


class TestPipePathFromSeveralObjects(PipeCase):
    """`SpineMore`: the path's edges may come from several objects (sketches, model edges), joined in any
    order (Onshape picks path edges one by one). A path whose edges don't meet stops, naming the gap."""

    def testSketchAndModelEdge(self):
        box = models.box(self.doc, "Box", (10, 10, 10))  # outside the body; Edge along Z at x = y = 0
        self.doc.recompute()
        edge = [f"Edge{i}" for i, e in enumerate(box.Shape.Edges, 1)
                if e.Vertexes[0].Point.x == 0 and e.Vertexes[0].Point.y == 0
                and e.Vertexes[-1].Point.x == 0 and e.Vertexes[-1].Point.y == 0]
        self.assertEqual(len(edge), 1)
        pipe = self.pipe(self.circle(), (box, edge), more=[self.line(10, 20)])
        self.assertSweeps(pipe, AREA * 20)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMax, 20, 4)

    def testTwoSketchesInAnyOrder(self):
        far = self.line(10, 20, name="Far")
        near = self.line(0, 10, name="Near")
        pipe = self.pipe(self.circle(), far, more=[near])
        self.assertSweeps(pipe, AREA * 20)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMin, 0, 4)

    def testBrokenPathNamesTheGap(self):
        pipe = self.pipe(self.circle(), self.line(0, 10, name="Near"), more=[self.line(12, 20, name="Far")])
        self.assertStops(pipe, "don't meet", "(0, 0, 10)")


class TestPipeEndAfterThePathGrows(PipeCase):
    """SW6c: a feature on the sweep's end face follows when an edge joins the path's far end."""

    def testPadOnTheEndFaceFollows(self):
        path = self.line(0, 20)
        pipe = self.pipe(self.circle(), (path, ["Edge1"]))
        self.assertSweeps(pipe)
        end = [f"Face{i}" for i, f in enumerate(pipe.Shape.Faces, 1)
               if abs(f.CenterOfMass.z - 20) < 1e-6 and f.Surface.isPlanar()]
        self.assertEqual(len(end), 1)
        top = self.body.newObject("Sketcher::SketchObject", "OnEnd")
        top.AttachmentSupport = [(pipe, end[0])]
        top.MapMode = "FlatFace"
        top.addGeometry(models.circle(0, 0, 1), False)
        pad = models.pad(self.body, top, 5)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        path.addGeometry(Part.LineSegment(V(0, 20, 0), V(0, 30, 0)), False)
        pipe.Spine = (path, ["Edge1", "Edge2"])
        self.doc.recompute()
        self.assertSweeps(pipe, AREA * 30)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 35, 4)

    def testPadOnTheEndFaceFollowsPastACorner(self):
        """The probe's case (q02e): the path gets a second edge at a 45 degree corner ("Right corner");
        the pad on the end face follows to the new end face's plane, 5 along the new edge's direction."""
        path = self.line(0, 20)
        pipe = self.pipe(self.circle(), (path, ["Edge1"]))
        end = [f"Face{i}" for i, f in enumerate(pipe.Shape.Faces, 1)
               if abs(f.CenterOfMass.z - 20) < 1e-6 and f.Surface.isPlanar()]
        self.assertEqual(len(end), 1)
        top = self.body.newObject("Sketcher::SketchObject", "OnEnd")
        top.AttachmentSupport = [(pipe, end[0])]
        top.MapMode = "FlatFace"
        top.addGeometry(models.circle(0, 0, 1), False)
        pad = models.pad(self.body, top, 5)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        path.addGeometry(Part.LineSegment(V(0, 20, 0), V(10, 30, 0)), False)
        pipe.Spine = (path, ["Edge1", "Edge2"])
        self.doc.recompute()
        self.assertSweeps(pipe)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        # FlatFace puts the sketch's origin where the global origin projects onto the face: the pad
        # stands on the new end face's plane, 5 along its normal
        normal = V(1, 0, 1).normalize()
        centre = pad.AddSubShape.BoundBox.Center
        self.assertAlmostEqual(centre.dot(normal), V(10, 0, 30).dot(normal) + 2.5, 4)

    def testPadOnTheEndFaceFollowsATangentArc(self):
        """SW6 (c): a tangent quarter arc appended to the path (centre (10, 0, 20), to (10, 0, 30)); Onshape's
        boss follows, its axis +X from (10, 0, 30) to x = 15."""
        path = self.line(0, 20)
        pipe = self.pipe(self.circle(), (path, ["Edge1"]))
        end = [f"Face{i}" for i, f in enumerate(pipe.Shape.Faces, 1)
               if abs(f.CenterOfMass.z - 20) < 1e-6 and f.Surface.isPlanar()]
        self.assertEqual(len(end), 1)
        top = self.body.newObject("Sketcher::SketchObject", "OnEnd")
        top.AttachmentSupport = [(pipe, end[0])]
        top.MapMode = "FlatFace"
        top.addGeometry(models.circle(0, 0, 1), False)
        pad = models.pad(self.body, top, 5)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        path.addGeometry(arc3((0, 20, 0), (10, 20, 0), (10, 30, 0)), False)
        pipe.Spine = (path, ["Edge1", "Edge2"])
        self.doc.recompute()
        self.assertSweeps(pipe, AREA * (20 + 5 * math.pi))
        self.assertTrue(pad.isValid(), pad.getStatusString())
        # On the new end face's plane x = 10, 5 along +X (FlatFace: the sketch origin at the
        # global origin's projection, (10, 0, 0); Onshape's concentric constraint put it at the end)
        box = pad.AddSubShape.BoundBox
        self.assertAlmostEqual(box.XMin, 10, 4)
        self.assertAlmostEqual(box.XMax, 15, 4)


class TestThreadCapFollowsEdits(PipeCase):
    """SW7 (oracle 5): Onshape's thread cap, a revolve of the thread's end face about the face's
    edge on the cylinder, follows the helix's height and pitch edits. Designed: a cylinder r 10,
    20 tall; a tooth (10, 2)-(11, 2.5)-(10, 3) on XZ; an AdditiveHelix about Z, pitch 2, height 10
    (5 turns); the cap a Revolution of the end face about its edge at r = 10, 90 degrees. The tooth
    is 0.5 in area, its centroid 1/3 from that edge: the cap is 0.5 x 1/3 x pi/2 = pi/12, between
    z = H + 2 and H + 3, on the end face's side of the axis plane through the helix's end."""

    CAP = math.pi / 12

    def thread(self):
        base = self.circle(r=10, name="Base")
        models.pad(self.body, base, 20, "Cylinder")
        tooth = self.sketch("Tooth", models.polygon([(10, 2), (11, 2.5), (10, 3)]), placement=XZ)
        helix = self.body.newObject("PartDesign::AdditiveHelix", "Thread")
        helix.Profile = tooth
        helix.ReferenceAxis = (models.originFeature(self.body, "Z_Axis"), [""])
        helix.Mode = "pitch-height-angle"
        helix.Pitch = 2
        helix.Height = 10
        self.doc.recompute()
        self.assertTrue(helix.isValid(), helix.getStatusString())
        return helix

    def endFace(self, helix):
        """The thread's end face: the planar face on the cylinder (centroid at r > 9.95) highest up."""
        shape = helix.Shape
        planar = [
            (f.CenterOfMass.z, "Face%d" % (i + 1), f)
            for i, f in enumerate(shape.Faces)
            if f.Surface.__class__.__name__ == "Plane"
            and math.hypot(f.CenterOfMass.x, f.CenterOfMass.y) > 9.95
        ]
        return max(planar, key=lambda t: t[0])[1:]

    def axisEdge(self, shape, face):
        """The end face's edge on the cylinder: both its vertices at r = 10."""
        for edge in face.Edges:
            if all(abs(math.hypot(v.Point.x, v.Point.y) - 10) < 1e-3 for v in edge.Vertexes):
                return next("Edge%d" % (j + 1) for j, e in enumerate(shape.Edges) if e.isSame(edge))
        self.fail("no edge of the end face on the cylinder")

    def cap(self, helix):
        name, face = self.endFace(helix)
        cap = self.body.newObject("PartDesign::Revolution", "Cap")
        cap.Profile = (helix, [name])
        cap.ReferenceAxis = (helix, [self.axisEdge(helix.Shape, face)])
        cap.Angle = 90
        self.doc.recompute()
        return cap

    def assertCapAt(self, cap, helix):
        """The cap is the revolve of the thread's end face where the helix ends now."""
        self.assertTrue(cap.isValid(), cap.getStatusString())
        height = helix.Height.Value
        tool = cap.AddSubShape
        self.assertAlmostEqual(tool.Volume, self.CAP, 4)
        box = tool.BoundBox
        self.assertAlmostEqual(box.ZMin, height + 2, 3)
        self.assertAlmostEqual(box.ZMax, height + 3, 3)
        # It starts at the thread's end face as it is now: the face's centroid is on the cap
        _, face = self.endFace(helix)
        self.assertLess(tool.distToShape(Part.Vertex(face.CenterOfMass))[0], 1e-3)

    def testCapFollowsHeightAndPitchAtWholeTurns(self):
        """Height 10 -> 12 (6 turns), then pitch 2 -> 2.4 (5 turns): the end face's edge on the
        cylinder is a line at whole turns; the cap's axis is named from the tooth's edge, not from
        the last turn's side face (which renamed with the turn count: "Missing edge reference")."""
        helix = self.thread()
        cap = self.cap(helix)
        self.assertCapAt(cap, helix)
        helix.Height = 12
        self.doc.recompute()
        self.assertCapAt(cap, helix)
        helix.Pitch = 2.4
        self.doc.recompute()
        self.assertCapAt(cap, helix)

    def testCapFollowsAtPartTurns(self):
        """Height 10 -> 11 (5.5 turns): the end face's edge on the cylinder stays a B-spline,
        straight within tolerance; the revolve takes it as its axis, as Onshape does."""
        helix = self.thread()
        cap = self.cap(helix)
        helix.Height = 11
        self.doc.recompute()
        self.assertCapAt(cap, helix)

    def testInnerCapInsideTheThreadIsNotLostSilently(self):
        """Rehearsal 4's silent find, designed: a thread swept by a Pipe along a helix (pitch 2,
        r 10, 10 tall, from z = 2.5), its tooth (9.9, 2)-(11, 2.5)-(9.9, 3) sunk 0.1 into the
        cylinder (the fuse trims the start face to x >= 10); the cap a Revolution of that face about
        its edge on the cylinder, 180 degrees one way, swinging into the cylinder and the thread. The fuse of the two came out
        empty (no solid) while the Revolution was Up-to-date. Onshape builds it: the thread, the cap
        adding at most its own 0.476. The thread's path now sweeps turn by turn (ops#665), and the
        fuse builds: the cap lies almost wholly inside the thread and the cylinder, so it adds next
        to nothing (the boolean's noise is about 1e-4)."""
        base = self.circle(r=10, name="Base")
        models.pad(self.body, base, 20, "Cylinder")
        tooth = self.sketch("Tooth", models.polygon([(9.9, 2), (11, 2.5), (9.9, 3)]), placement=XZ)
        path = self.doc.addObject("Part::Helix", "Helix")
        path.Pitch = 2
        path.Height = 10
        path.Radius = 10
        path.Placement = App.Placement(V(0, 0, 2.5), App.Rotation())
        thread = self.pipe(tooth, path)
        self.assertSweeps(thread)
        before = thread.Shape.Volume
        start = min(
            (f.CenterOfMass.z, "Face%d" % (i + 1), f)
            for i, f in enumerate(thread.Shape.Faces)
            if f.Surface.__class__.__name__ == "Plane"
            and math.hypot(f.CenterOfMass.x, f.CenterOfMass.y) > 9.95
        )
        [axis] = [
            "Edge%d" % (j + 1)
            for j, e in enumerate(thread.Shape.Edges)
            if any(e.isSame(x) for x in start[2].Edges)
            and all(abs(math.hypot(v.Point.x, v.Point.y) - 10) < 1e-3 for v in e.Vertexes)
        ]
        cap = self.body.newObject("PartDesign::Revolution", "Cap")
        cap.Profile = (thread, [start[1]])
        cap.ReferenceAxis = (thread, [axis])
        cap.Angle = 180
        cap.Refine = False
        self.doc.recompute()
        self.assertTrue(cap.isValid(), cap.getStatusString())
        self.assertEqual(len(cap.Shape.Solids), 1, "the cap's result lost the part")
        self.assertGreaterEqual(cap.Shape.Volume, before - 1e-3)
        self.assertLessEqual(cap.Shape.Volume, before + cap.AddSubShape.Volume + 1e-3)


class TestHelixTurnNamesNeverPass(PipeCase):
    """Batch 4's T1 (ops#640): a helix's side faces are twins, one per turn, turn 1's told apart by
    the start cap's names. In two turns the last turn took the plain name turn 1 has in one turn,
    so a reference on turn 1 went to turn 2 when a turn was added, silently (and back). Onshape's
    side face is one face, and a reference to it follows. Designed: an AdditiveHelix about Z of a
    3 x 2 rectangle (x 9..12, z 0..2 on XZ), pitch 6; a datum point at the centre of a turn's outer
    face (r 12, area 2 pi 12 x 2, its centre on the axis at z = 4 + 6 (k - 1) for turn k)."""

    def helix(self, turns):
        profile = self.sketch("HS", models.rectangle(9, 0, 12, 2), placement=XZ)
        helix = self.body.newObject("PartDesign::AdditiveHelix", "Helix")
        helix.Profile = profile
        helix.ReferenceAxis = (profile, ["V_Axis"])
        helix.Mode = "pitch-turns-angle"
        helix.Pitch = 6
        helix.Turns = turns
        self.doc.recompute()
        self.assertTrue(helix.isValid(), helix.getStatusString())
        return helix

    def outer(self, helix, k):
        """The outer face of turn k: the B-spline face of area 2 pi 12 x 2 centred at z = 4 + 6 (k - 1)."""
        z = 4 + 6 * (k - 1)
        [name] = [
            "Face%d" % (i + 1)
            for i, f in enumerate(helix.Shape.Faces)
            if f.Surface.__class__.__name__ == "BSplineSurface"
            and abs(f.Area - 2 * math.pi * 12 * 2) < 3
            and abs(f.CenterOfMass.z - z) < 0.25
        ]
        return name

    def pointOn(self, helix, k):
        point = self.body.newObject("PartDesign::Point", "OnTurn%d" % k)
        point.AttachmentSupport = [(helix, self.outer(helix, k))]
        point.MapMode = "CenterOfMass"
        self.doc.recompute()
        self.assertAlmostEqual(point.Placement.Base.z, 4 + 6 * (k - 1), 2)
        return point

    def assertNotOnTurn(self, point, k):
        """Broken (loud), or anywhere but turn k's outer face."""
        if point.isValid():
            self.assertGreater(abs(point.Placement.Base.z - (4 + 6 * (k - 1))), 1,
                               "the reference passed to turn %d's face" % k)

    def testTurnOneDoesNotPassToTurnTwo(self):
        """1 -> 2 turns: the point on turn 1 stays on turn 1 or breaks; it went to turn 2."""
        helix = self.helix(1)
        point = self.pointOn(helix, 1)
        helix.Turns = 2
        self.doc.recompute()
        self.assertNotOnTurn(point, 2)

    def testGoneTurnTwoDoesNotPassToTurnOne(self):
        """2 -> 1 turn: turn 2's face is gone, so the point on it breaks; it went to turn 1."""
        helix = self.helix(2)
        point = self.pointOn(helix, 2)
        helix.Turns = 1
        self.doc.recompute()
        self.assertFalse(point.isValid(), "the reference on the gone turn 2 moved to turn 1")

    def testTurnTwoFollowsATurnAdded(self):
        """2 -> 3 turns: the point on turn 2 stays on turn 2 (integration's twins did, by their count)."""
        helix = self.helix(2)
        point = self.pointOn(helix, 2)
        helix.Turns = 3
        self.doc.recompute()
        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertAlmostEqual(point.Placement.Base.z, 10, 2)

    def testTurnOneFollowsASecondTurn(self):
        """1 -> 2 turns: the point on the one turn stays on turn 1, which sits where it was (sweeps
        16; Onshape follows its one face). It broke, the twin count having changed."""
        helix = self.helix(1)
        point = self.pointOn(helix, 1)
        helix.Turns = 2
        self.doc.recompute()
        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertAlmostEqual(point.Placement.Base.z, 4, 2)

    def testTurnOneFollowsTheSecondTurnGone(self):
        """2 -> 1 turn: the point on turn 1 stays on the one turn left (sweeps 16). It broke."""
        helix = self.helix(2)
        point = self.pointOn(helix, 1)
        helix.Turns = 1
        self.doc.recompute()
        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertAlmostEqual(point.Placement.Base.z, 4, 2)


class TestPipeHelixTurnsCountFromTheStart(PipeCase):
    """Batch 6's R1 (ops#640): a Pipe along a Part::Helix of several turns is swept turn by turn
    (the path cut at each whole turn, ops#665), one side face per turn and profile edge. Turn k's
    pieces took the plain names of the path's pieces, and the last piece was told apart by the
    path's end vertex: after an edit that adds turns, "turn 2 of 2" was the new end piece, and a
    reference on turn 2 went to it, silently. Onshape's helix sweep has one side face, which
    follows the edit. Turn k is now named by its place counted from the helix's start, so it keeps
    its name whatever the number of turns. Designed: a Part::Helix about Z, r 10.5, pitch 6,
    height 12; a 3 x 2 rectangle on XZ (x 9..12, z -1..1) swept in Frenet mode. Turn k's outer
    face lies at r 12 (area 2 pi 12 x 2) and its centre of mass on the axis at
    z = pitch (k - 1/2)."""

    def build(self, height=12.0, pitch=6.0, half=1.0):
        self.helixPath = self.doc.addObject("Part::Helix", "Path")
        self.helixPath.Pitch, self.helixPath.Height, self.helixPath.Radius = pitch, height, 10.5
        self.doc.recompute()
        profile = self.sketch("HS", models.rectangle(9, -half, 12, half), placement=XZ)
        self.profile = profile
        pipe = self.pipe(profile, (self.helixPath, ["Edge1"]), Mode="Frenet")
        self.assertSweeps(pipe)
        return pipe

    def outer(self, pipe, k, pitch):
        """Turn k's outer face: area 2 pi 12 x 2, its centre of mass at z = pitch (k - 1/2)."""
        z = pitch * (k - 0.5)
        names = [
            "Face%d" % (i + 1)
            for i, f in enumerate(pipe.Shape.Faces)
            if abs(f.Area - 2 * math.pi * 12 * 2) < 1 and abs(f.CenterOfMass.z - z) < 0.25
        ]
        self.assertEqual(len(names), 1, names)
        return names[0]

    def pointOn(self, pipe, k, pitch=6.0):
        point = self.body.newObject("PartDesign::Point", "OnTurn%d" % k)
        point.AttachmentSupport = [(pipe, self.outer(pipe, k, pitch))]
        point.MapMode = "CenterOfMass"
        self.doc.recompute()
        self.assertAlmostEqual(point.Placement.Base.z, pitch * (k - 0.5), 2)
        return point

    def edit(self, pitch, height):
        self.helixPath.Pitch = pitch
        self.helixPath.Height = height
        self.doc.recompute()

    def assertOnTurn(self, point, k, pitch):
        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertAlmostEqual(point.Placement.Base.z, pitch * (k - 0.5), 2)

    def testPitchDownKeepsTurn2(self):
        """Pitch 6 -> 5 (2 -> 2.4 turns): the point on turn 2 stays on turn 2 (z 7.5), not on the
        0.4-turn end piece (z 10..12), where it went (the review's PipeHelixPitchDown|t2_outer)."""
        pipe = self.build()
        point = self.pointOn(pipe, 2)
        self.edit(5.0, 12.0)
        self.assertOnTurn(point, 2, 5.0)

    def testPitchDownKeepsTurn1(self):
        pipe = self.build()
        point = self.pointOn(pipe, 1)
        self.edit(5.0, 12.0)
        self.assertOnTurn(point, 1, 5.0)

    def testTurnAddedKeepsTurn2(self):
        """Height 12 -> 18 (2 -> 3 turns)."""
        pipe = self.build()
        point = self.pointOn(pipe, 2)
        self.edit(6.0, 18.0)
        self.assertOnTurn(point, 2, 6.0)

    def testHalfTurnMoreKeepsTurn2(self):
        """Height 12 -> 15 (2 -> 2.5 turns)."""
        pipe = self.build()
        point = self.pointOn(pipe, 2)
        self.edit(6.0, 15.0)
        self.assertOnTurn(point, 2, 6.0)

    def testThreeToFourKeepsTurn2(self):
        """Built at 3 turns; height 18 -> 24: turn 2 goes from the middle turn to the second of
        three middle turns."""
        pipe = self.build(height=18.0)
        point = self.pointOn(pipe, 2)
        self.edit(6.0, 24.0)
        self.assertOnTurn(point, 2, 6.0)

    def testTurnRemovedKeepsTurn2(self):
        """Built at 3 turns; height 18 -> 12: turn 2 becomes the last turn."""
        pipe = self.build(height=18.0)
        point = self.pointOn(pipe, 2)
        self.edit(6.0, 12.0)
        self.assertOnTurn(point, 2, 6.0)

    def testGoneTurnDoesNotPassToAnother(self):
        """Built at 3 turns; height 18 -> 12: turn 3 is gone, so the point on it breaks (loud) or
        stays off turns 1 and 2."""
        pipe = self.build(height=18.0)
        point = self.pointOn(pipe, 3)
        self.edit(6.0, 12.0)
        if point.isValid():
            for k in (1, 2):
                self.assertGreater(abs(point.Placement.Base.z - 6.0 * (k - 0.5)), 1,
                                   "the reference on the gone turn 3 passed to turn %d" % k)

    def turnPoint(self, k, pitch=6.0):
        """On turn k's part of the outer side face (r 12): angle 2 pi (k - 1) + pi / 2,
        z = pitch (k - 3/4), a quarter turn on from the profile's start."""
        a = 2 * math.pi * (k - 1) + math.pi / 2
        return V(12 * math.cos(a), 12 * math.sin(a), pitch * (k - 0.75))

    def faceAt(self, pipe, point):
        names = [
            "Face%d" % (i + 1)
            for i, f in enumerate(pipe.Shape.Faces)
            if f.distToShape(Part.Vertex(point))[0] < 1e-6
        ]
        self.assertEqual(len(names), 1, names)
        return names[0]

    def bindAt(self, pipe, k):
        binder = self.body.newObject("PartDesign::SubShapeBinder", "OnTurn%d" % k)
        binder.Support = [(pipe, (self.faceAt(pipe, self.turnPoint(k)),))]
        self.doc.recompute()
        return binder

    def holds(self, binder, point):
        """The binder holds one face, the one through `point`."""
        faces = binder.Shape.Faces
        return len(faces) == 1 and faces[0].distToShape(Part.Vertex(point))[0] < 1e-6

    def testTouchingTurnsKeepTheTurnsFaces(self):
        """The profile grows from 2 to 6 tall, the pitch: the turns touch, and the path is swept
        whole (withHelixTurns' switch point, OCCT's sweep fails along the turns): one outer face
        holds both turns' points. References picked on turn 1's and turn 2's outer faces follow it,
        as Onshape's references to its one side face do; they broke (the review's
        PipeHelixProfileToTouching)."""
        pipe = self.build()
        binders = [self.bindAt(pipe, k) for k in (1, 2)]
        models.moveRectangle(self.profile, 9, -3, 12, 3)
        self.doc.recompute()
        self.assertSweeps(pipe)
        outer = self.faceAt(pipe, self.turnPoint(1))
        self.assertEqual(self.faceAt(pipe, self.turnPoint(2)), outer)
        for k, binder in zip((1, 2), binders):
            self.assertTrue(binder.isValid(), binder.getStatusString())
            self.assertTrue(self.holds(binder, self.turnPoint(k)), (k, binder.Support))

    def testFromTouchingTurnsNeverPassToAnotherFace(self):
        """Built 6 tall (the turns touch, one outer face); shrunk to 2 tall: the path is cut at its
        turns again, and the one face is two. The references picked at turn 1's and turn 2's points
        are one and the same (the one face), so they can't both follow their points: each breaks
        (loud) or holds the face its point is on, never another face."""
        pipe = self.build(half=3.0)
        binders = [self.bindAt(pipe, k) for k in (1, 2)]
        self.assertEqual(binders[0].Support[0][1], binders[1].Support[0][1])
        models.moveRectangle(self.profile, 9, -1, 12, 1)
        self.doc.recompute()
        self.assertSweeps(pipe)
        self.assertNotEqual(self.faceAt(pipe, self.turnPoint(1)), self.faceAt(pipe, self.turnPoint(2)))
        for k, binder in zip((1, 2), binders):
            if binder.isValid():
                self.assertTrue(self.holds(binder, self.turnPoint(k)), (k, binder.Support))


class TestThreadToothOnTheCylinder(PipeCase):
    """Oracle 9 (ops#665, Onshape's answers): a cylinder r 10, 20 tall; a helix r 10, pitch 2,
    height 10 from z = 2.5; a tooth on XZ swept along it, added (profile control None)."""

    CYLINDER = math.pi * 10**2 * 20

    def thread(self, tooth):
        base = self.circle(r=10, name="Base")
        models.pad(self.body, base, 20, "Cylinder")
        profile = self.sketch("Tooth", models.polygon(tooth), placement=XZ)
        path = self.doc.addObject("Part::Helix", "Helix")
        path.Pitch, path.Height, path.Radius = 2, 10, 10
        path.Placement = App.Placement(V(0, 0, 2.5), App.Rotation())
        return self.pipe(profile, path, ProfileControl="None")

    def assertSolids(self, pipe, volumes):
        self.assertSweeps(pipe)
        solids = sorted(pipe.Shape.Solids, key=lambda s: s.Volume)
        self.assertEqual(len(solids), len(volumes), [s.Volume for s in solids])
        for solid, volume in zip(solids, sorted(volumes)):
            self.assertTrue(solid.isValid())
            self.assertAlmostEqual(solid.Volume, volume, delta=0.02)

    def testBaseOnTheCylinderFusesIntoOnePart(self):
        """The tooth's base edge (10, 2)-(10, 3) lies on the cylinder, so the swept base face does:
        one part, 6445.4938 (Onshape). The Pipe along a one-edge helix gave 2 solids with BOP
        errors; AdditiveHelix, whose path breaks at each turn, gave the one part."""
        pipe = self.thread([(10, 2), (11, 2.5), (10, 3)])
        self.assertSolids(pipe, [6445.4938])
        shape = pipe.Shape.copy()
        try:
            shape.check(True)
        except ValueError as error:
            self.fail(str(error))

    def testApexOnTheCylinderLeavesTwoParts(self):
        """True line contact, the tooth's apex on the cylinder: two parts, no error (Onshape: the
        cylinder 6283.1853 and the thread 167.5426)."""
        pipe = self.thread([(10, 2.5), (11, 2), (11, 3)])
        self.assertSolids(pipe, [self.CYLINDER, 167.5426])

    def testSunkToothFusesIntoOnePart(self):
        """The control, sunk 0.1 into the cylinder: one part, 6430.7378 (Onshape)."""
        pipe = self.thread([(9.9, 2), (11, 2.5), (9.9, 3)])
        self.assertSolids(pipe, [6430.7378])

    def testBaseOnTheCylinderStaysOnePartAtPartTurns(self):
        """Height 10 -> 11 (5.5 turns, the last piece half a turn): still one part, its volume between
        the cylinder's and the cylinder's plus the thread tool's."""
        pipe = self.thread([(10, 2), (11, 2.5), (10, 3)])
        self.doc.getObject("Helix").Height = 11
        self.doc.recompute()
        self.assertSweeps(pipe)
        self.assertEqual(len(pipe.Shape.Solids), 1)
        self.assertGreater(pipe.Shape.Volume, self.CYLINDER + 160)
        self.assertLess(pipe.Shape.Volume, self.CYLINDER + pipe.AddSubShape.Volume + 1e-6)


YZ = App.Placement(V(0, 0, 0), App.Rotation(V(0, 1, 0), 90) * App.Rotation(V(0, 0, 1), 90))  # (x, y) -> (0, x, y)


class TestPipeSelfOverlap(PipeCase):
    """Oracle 9 (ops#660, Onshape's answers): Onshape refuses a helix whose turns overlap
    (SWEEP_FAILED) and a path that touches or crosses itself (SWEEP_PATH_FAILED); it builds turns
    that only touch, and tubes that overlap while the path stays clear of itself (their exact
    union: FreeCAD-CH stops there with an error until it builds the union)."""

    def coil(self, pitch):
        """A 1 x 3 rectangle (radial x axial) on XZ centred on the start of a helix r 10, height 10."""
        helix = self.doc.addObject("Part::Helix", "Helix")
        helix.Pitch, helix.Height, helix.Radius = pitch, 10, 10
        profile = self.sketch("Profile", models.rectangle(9.5, -1.5, 10.5, 1.5), placement=XZ)
        return self.pipe(profile, helix, ProfileControl="None")

    def testOverlappingTurnsStop(self):
        """Pitch 2 under a profile 3 tall: each turn overlaps the next (Onshape: SWEEP_FAILED). The
        sweep came out a self-intersecting solid of the naive 942.48, Up-to-date."""
        self.assertStops(self.coil(2), "turns overlap")

    def testTouchingTurnsSweep(self):
        """Pitch 3 = the profile's height: the turns touch (Onshape builds it): 3 x 1 x the path's
        length, 2 pi 10 x 10 / 3 turns."""
        self.assertSweeps(self.coil(3), 3 * 2 * math.pi * 10 * 10 / 3, places=2)

    def testClearTurnsSweep(self):
        """Pitch 4: 3 x 1 x 2 pi 10 x 2.5 turns."""
        self.assertSweeps(self.coil(4), 3 * 2 * math.pi * 10 * 2.5, places=2)

    def tube(self, end):
        """A circle r 1 normal to X at the origin swept along (0,0)-(20,0)-(20,10)-(10,10)-end."""
        path = self.sketch("Path", models.polyline([(0, 0), (20, 0), (20, 10), (10, 10), end]))
        profile = self.sketch("Profile", [models.circle(0, 0, 1)], placement=YZ)
        return self.pipe(profile, path, ProfileControl="None")

    def testPathCrossingItselfStops(self):
        """The last segment crosses the first at (10, 0) (Onshape: SWEEP_PATH_FAILED)."""
        self.assertStops(self.tube((10, -10)), "path", "crosses or touches itself")

    def testPathTouchingItselfStops(self):
        """The path ends on its first segment (Onshape: an error too)."""
        self.assertStops(self.tube((10, 0)), "path", "crosses or touches itself")

    def testTubesOverlappingWhileThePathIsClearBuildTheUnion(self):
        """The path ends at (10, 0.5): the last tube runs 0.5 into the first, the path clear of itself.
        Onshape builds the exact union (oracle 9 S2: 7 faces, V 154.3944; the naive sweep is 155.509,
        counting the overlap twice): start cap, legs 1 (holed), 2, 3, 4 (cut short) and the end cap's
        two slivers outside leg 1 (|z| > 0.866). By geometry the overlap is the integral over z of
        2 sqrt(1 - z^2) (sqrt(1 - z^2) - 0.5), 1.117866: the union is 154.390970 (Onshape's 0.0034
        more is its own sweep's)."""
        pipe = self.tube((10, 0.5))
        self.assertSweeps(pipe, 154.390970, places=5)
        self.assertTrue(pipe.Shape.isValid())
        self.assertEqual(len(pipe.Shape.Solids), 1)
        self.assertEqual(len(pipe.Shape.Faces), 7)
        self.assertAlmostEqual(pipe.AddSubShape.Volume, 154.390970, 5)


    def testScaledTurnsOverlappingStop(self):
        """The ops#666 skeptic's silent path A: pitch 4 clears the 3-tall profile, but scaled 1.6x
        along the helix it is 4.8 tall at the end and overlaps the turn before. The turn check read
        only the start profile, and the sweep came out self-intersecting (BOP SelfIntersect, V
        810.53), Up-to-date. Scaled 1.2x (3.6 tall) it stays clear and sweeps."""
        helix = self.doc.addObject("Part::Helix", "Helix")
        helix.Pitch, helix.Height, helix.Radius = 4, 10, 10
        profile = self.sketch("Profile", models.rectangle(9.5, -1.5, 10.5, 1.5), placement=XZ)
        pipe = self.pipe(profile, helix, ProfileControl="None", HasScale=True, ScaleFactor=1.6)
        self.assertStops(pipe, "turns overlap")
        pipe.ScaleFactor = 1.2
        self.doc.recompute()
        self.assertSweeps(pipe)

    def testTubesClearOfEachOtherSweep(self):
        """The path ends at (10, 1.5): the tubes miss each other: pi x the path's length."""
        self.assertSweeps(self.tube((10, 1.5)), math.pi * 48.5, places=2)



class TestPipeSelfOverlapUnion(PipeCase):
    """ops#666: tubes overlapping while the path stays clear of itself sweep their exact union
    (notes\\sweep-design.md 13), as Onshape does (oracle 9 S2). Designed: S2's path
    (0,0)-(20,0)-(20,10)-(10,10)-end in the XY plane; leg 4 (x = 10) runs into leg 1 (y = 0) for
    an end below 1 + the profile's reach. The volumes are by geometry: a square tube along a polyline
    with mitred corners holds its area times the path's length."""

    def path(self, end):
        return self.sketch("Path", models.polyline([(0, 0), (20, 0), (20, 10), (10, 10), end]))

    def tube(self, end, profile=None, **properties):
        """A profile normal to X at the origin (a circle r 1 by default) swept along S2's path."""
        if profile is None:
            profile = [models.circle(0, 0, 1)]
        profile = self.sketch("Profile", profile, placement=YZ)
        return self.pipe(profile, self.path(end), ProfileControl="None", **properties)

    def assertOneSolid(self, pipe, volume=None, places=3):
        self.assertSweeps(pipe, volume, places)
        self.assertTrue(pipe.Shape.isValid())
        self.assertEqual(len(pipe.Shape.Solids), 1)

    def testSquareDuctCoincidentFaces(self):
        """SW19 (b): a 2 x 2 square ends at (10, 0.5): leg 4's top and bottom lie on leg 1's (a winding step
        of 2 there) and its sides cross leg 1's side. 2 x 2 x 49.5 less the overlap x 9..11, y 0.5..1,
        z -1..1 (2): 196. Refine on (the default) gives Onshape's F 12: the top (z 1) is one face over
        x 0..21, y -1..11, A 98 (49.5 x 2 less 1), the bottom the same. Refine off keeps FreeCAD's pieces,
        as on a clear path (each leg's mitred top, and the overlap's patch): 20 faces, the tops still 98."""
        pipe = self.tube((10, 0.5), models.rectangle(-1, -1, 1, 1))
        for refine, faces, tops in ((True, 12, 1), (False, 20, 5)):
            pipe.Refine = refine
            self.doc.recompute()
            self.assertOneSolid(pipe, 196)
            self.assertEqual(len(pipe.Shape.Faces), faces, refine)
            for z in (1, -1):
                flat = [f for f in pipe.Shape.Faces if f.Surface.isPlanar() and abs(f.CenterOfMass.z - z) < 1e-6]
                self.assertEqual(len(flat), tops, (refine, z, [f.Area for f in flat]))
                self.assertAlmostEqual(sum(f.Area for f in flat), 98, 6)

    def testFlushEndCapOnTheSide(self):
        """The square ends at (10, 1): its end cap lies on leg 1's side y = 1 (a step of 0: the
        pieces there bound two cells of number 1 and leave the union). 2 x 2 x 49: 196, one solid."""
        pipe = self.tube((10, 1), models.rectangle(-1, -1, 1, 1))
        self.assertOneSolid(pipe, 196)
        inner = [f for f in pipe.Shape.Faces
                 if abs(f.CenterOfMass.y - 1) < 1e-6 and abs(f.CenterOfMass.x - 10) < 1e-6]
        self.assertEqual(inner, [], "the end cap stayed inside the union")

    def testSubtractiveCutsTheUnion(self):
        """A subtractive S2 tube through a box x -5..25, y -5..15, z -3..3 cuts the union, not the
        naive sweep: 3600 - 154.390970."""
        box = self.sketch("Box", models.rectangle(-5, -5, 25, 15), z=-3)
        models.pad(self.body, box, 6, "Block")
        pipe = self.tube((10, 0.5), kind="SubtractivePipe")
        self.assertOneSolid(pipe, 3600 - 154.390970, places=4)
        self.assertAlmostEqual(pipe.AddSubShape.Volume, 154.390970, 5)

    def leg(self, pipe, centre):
        """The side face whose centroid is within 0.75 of the point `centre`."""
        found = ["Face%d" % (i + 1) for i, f in enumerate(pipe.Shape.Faces)
                 if not f.Surface.isPlanar() and (f.CenterOfMass - V(*centre)).Length < 0.75]
        self.assertEqual(len(found), 1, (centre, [tuple(round(c, 2) for c in f.CenterOfMass)
                                                  for f in pipe.Shape.Faces]))
        return found[0]

    def pointOn(self, pipe, face, name):
        point = self.body.newObject("PartDesign::Point", name)
        point.AttachmentSupport = [(pipe, face)]
        point.MapMode = "CenterOfMass"
        return point

    def testReferencesFollowTheOverlapAndBack(self):
        """Datum points on leg 1's face (rebuilt holed by the overlap), leg 2's (untouched) and leg 4's
        (cut short) follow the end 1.5 -> 0.5 -> 1.5: each stays near its leg's middle."""
        pipe = self.tube((10, 1.5))
        self.assertOneSolid(pipe, math.pi * 48.5)
        middles = {"Leg1": (10, 0, 0), "Leg2": (20, 5, 0), "Leg4": (10, 5.75, 0)}
        points = {name: self.pointOn(pipe, self.leg(pipe, at), name) for name, at in middles.items()}
        path = self.doc.getObject("Path")
        for end in (0.5, 1.5):
            models.setLines(path, {3: ((10, 10), (10, end))})
            self.doc.recompute()
            self.assertOneSolid(pipe)
            for name, point in points.items():
                self.assertTrue(point.isValid(), (end, name, point.getStatusString()))
                self.assertLess((point.Placement.Base - V(*middles[name])).Length, 0.75,
                                (end, name, point.Placement.Base))

    def endCap(self, pipe, y):
        found = ["Face%d" % (i + 1) for i, f in enumerate(pipe.Shape.Faces)
                 if f.Surface.isPlanar() and abs(f.CenterOfMass.y - y) < 1e-6]
        return found

    def testEndCapReferencesBreakWhileTheCapIsCutInTwo(self):
        """SW19 (a): a point and a sketch on the end cap at y 1.5 (clear: one cap, A pi). The end moved
        to y 0.5 cuts the cap in two (|z| > 0.866): Onshape fails both references (CANNOT_RESOLVE_ENTITIES,
        SKETCH_NO_PLANE) and picks no piece; moved back to y 1.5, both come back."""
        pipe = self.tube((10, 1.5))
        self.assertOneSolid(pipe, math.pi * 48.5)
        cap = self.endCap(pipe, 1.5)
        self.assertEqual(len(cap), 1)
        self.assertAlmostEqual(pipe.Shape.getElement(cap[0]).Area, math.pi, 4)
        point = self.pointOn(pipe, cap[0], "OnCap")
        sketch = self.body.newObject("Sketcher::SketchObject", "OnCapSketch")
        sketch.AttachmentSupport = [(pipe, cap[0])]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        self.assertTrue(point.isValid() and sketch.isValid())
        self.assertLess((point.Placement.Base - V(10, 1.5, 0)).Length, 1e-6)
        path = self.doc.getObject("Path")
        models.setLines(path, {3: ((10, 10), (10, 0.5))})
        self.doc.recompute()
        self.assertOneSolid(pipe, 154.390970, places=4)
        self.assertEqual(len(self.endCap(pipe, 0.5)), 2)
        self.assertFalse(point.isValid(), ("the point picked a piece", point.Placement.Base))
        self.assertFalse(sketch.isValid(), ("the sketch picked a piece", sketch.Placement.Base))
        models.setLines(path, {3: ((10, 10), (10, 1.5))})
        self.doc.recompute()
        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertLess((point.Placement.Base - V(10, 1.5, 0)).Length, 1e-6)
        self.assertAlmostEqual(sketch.Placement.Base.y, 1.5, 9)  # on the cap's plane again

    def testRingProfileHoleStaysOpen(self):
        """A ring r 1 / 0.4: a point is kept where it lies in some leg's annulus (Onshape's union),
        open where it lies only in holes. (10, 0.75, 0): leg 1's wall and leg 4's hole: in.
        (10, 0.3, 0) leg 1's hole only, (10, 2, 0) leg 4's hole only, (5, 0, 0): out. (A bore of
        r 0.5 would leave the end cap at y 0.5 tangent to leg 1's bore.) The volume by geometry: the
        naive 0.84 pi x 49.5 less the annuli's overlap, the integral over |z| < sqrt(0.75) of
        2 (b - a) (b - 0.5), b = sqrt(1 - z^2), a = sqrt(0.16 - z^2) (0 for |z| > 0.4): 0.876804.
        OCCT's maker builds this union only with the tubes cut at the path's corners (sweeps 15)."""
        ring = [models.circle(0, 0, 1), models.circle(0, 0, 0.4)]
        pipe = self.tube((10, 0.5), ring)
        self.assertOneSolid(pipe, 0.84 * math.pi * 49.5 - 0.876804, places=4)
        solid = pipe.Shape.Solids[0]
        self.assertTrue(solid.isInside(V(10, 0.75, 0), 1e-6, False))
        for outside in ((10, 0.3, 0), (10, 2, 0), (5, 0, 0)):
            self.assertFalse(solid.isInside(V(*outside), 1e-6, False), outside)

    def testRoundCornerCircleOverlapping(self):
        """S2's tube with 'Round corner' (FreeCAD's option; Onshape mitres every sharp corner and
        builds S2's union, oracle 9). Each 90 degree round corner holds the legs cut square at the
        corner, less their overlap on the inside (a quarter of the bicylinder, 4/3 r^3), plus the
        sphere's quarter wedge outside (pi/3 r^3): pi x 49.5 - 3 (4 - pi) / 3 for r 1, and the union
        drops S2's overlap at leg 4's end, 1.117866, as with the mitre. Stopped with OCCT's
        BOPAlgo_AlertUnableToOrientTheShape (sweeps 14)."""
        pipe = self.tube((10, 0.5), Transition="Round corner")
        self.assertOneSolid(pipe, math.pi * 49.5 - (4 - math.pi) - 1.117866, places=5)
        self.assertTrue(pipe.Shape.Solids[0].isInside(V(10, 0.75, 0), 1e-6, False))

    def testRoundCornerRingOverlapping(self):
        """The ring r 1 / 0.4 with 'Round corner', its wall meeting itself: OCCT's maker leaves
        faces unused and a Round corner's joint has no planar edges to cut the tubes at, so it stops,
        naming Right corner (Onshape has no Round corner: it mitres, and builds the union, which
        testRingProfileHoleStaysOpen checks for the mitre). Building it here is debt (sweeps 18)."""
        pipe = self.tube((10, 1.5), [models.circle(0, 0, 1), models.circle(0, 0, 0.4)],
                         Transition="Round corner")
        self.assertOneSolid(pipe)
        models.setLines(self.doc.getObject("Path"), {3: ((10, 10), (10, 0.5))})
        self.doc.recompute()
        self.assertStops(pipe, "overlaps itself", "Round corner", "Right corner")

    def testClosedSpinePassingNearItself(self):
        """A closed path with a notch, (0,0)-(20,0)-(20,10)-(12,10)-(12,1.5)-(8,1.5)-(8,10)-(0,10): the
        notch's bottom runs 1.5 above leg 1 for 4, so the tubes (r 1) overlap there (a lens of 0.4532
        in section) and at the notch's mitred corners: 2.678 by a numerical integration of the
        mitred tubes (grid 0.005), less than the naive pi x 77."""
        path = self.sketch("Path", models.polygon(
            [(0, 0), (20, 0), (20, 10), (12, 10), (12, 1.5), (8, 1.5), (8, 10), (0, 10)]))
        profile = self.sketch("Profile", [models.circle(0, 0, 1)], placement=YZ)
        pipe = self.pipe(profile, path, ProfileControl="None")
        self.assertOneSolid(pipe, math.pi * 77 - 2.678, places=2)

    def testTwistOnTheSharpPathStops(self):
        """SW19 (c): a twist of 1 turn on S2's path, sharp at its corners: Onshape refuses it
        (SWEEP_TWIST_REQUIRE_TANGENT_PATH) with the 2 x 2 square on the overlap and with the circle on
        the overlapping and the clear path alike."""
        for end, profile in (((10, 0.5), models.rectangle(-1, -1, 1, 1)), ((10, 0.5), None), ((10, 1.5), None)):
            with self.subTest(end=end, square=profile is not None):
                self.body = self.doc.addObject("PartDesign::Body", "Body")  # each case on its own
                pipe = self.tube(end, profile, HasTwist=True, TwistType="Turns", Turns=1)
                self.assertStops(pipe, "smooth path")

    def testTwistedSquareOnARoundedPathOverlapping(self):
        """The square twisted 45 degrees along S2's path with its corners rounded r 2 (smooth, so the
        twist builds), end (10, 0.5): one solid, less than the naive 4 x (37.5 + 3 pi) (twist keeps the
        section's area) by at most the end's reach into leg 1. Bounds by geometry; Onshape's value for
        this case wasn't asked (SW19 (c) covers the sharp path)."""
        geometry = models.polyline([(0, 0), (18, 0)]) + [arc3((18, 0, 0), (18, 2, 0), (20, 2, 0))]             + models.polyline([(20, 2), (20, 8)]) + [arc3((20, 8, 0), (18, 8, 0), (18, 10, 0))]             + models.polyline([(18, 10), (12, 10)]) + [arc3((12, 10, 0), (12, 8, 0), (10, 8, 0))]             + models.polyline([(10, 8), (10, 0.5)])
        path = self.sketch("Path", geometry)
        profile = self.sketch("Profile", models.rectangle(-1, -1, 1, 1), placement=YZ)
        pipe = self.pipe(profile, path, ProfileControl="None",
                         HasTwist=True, TwistType="Angle", TwistAngle=45)
        self.assertOneSolid(pipe)
        naive = 4 * (37.5 + 3 * math.pi)
        self.assertLess(pipe.Shape.Volume, naive - 0.5)
        self.assertGreater(pipe.Shape.Volume, naive - 4)

    def multisection(self, radius):
        """A circle r 1 normal to X at the origin swept along the U path (0,0)-(30,0)-(30,6)-(0,6),
        with sections r 1 at both corners and r `radius` at the end: only leg 3 (y = 6) grows."""
        path = self.sketch("Path", models.polyline([(0, 0), (30, 0), (30, 6), (0, 6)]))
        profile = self.sketch("Profile", [models.circle(0, 0, 1)], placement=YZ)
        sections = []
        for k, (x, y, r) in enumerate(((30, 0, 1), (30, 6, 1), (0, 6, radius))):
            placement = App.Placement(V(x, 0, 0), YZ.Rotation)
            sections.append(self.sketch(f"Section{k}", [models.circle(y, 0, r)], placement=placement))
        return self.pipe(profile, path, ProfileControl="None", Transformation="Multisection",
                         Sections=sections)

    def testALargerSectionFurtherOnIsUnited(self):
        """The ops#666 skeptic's silent path A for sections: the start profile's reach (r 1) keeps the
        overlap check off for legs 6 apart, but the end section r 5.5 dips leg 3's tube to y 0.5 at
        x = 0, into leg 1's (r 1). The sweep came out a self-overlapping solid (BOP SelfIntersect on
        faces, V 869.6967, the overlap counted twice), Up-to-date. Now the sections' reach arms the
        check, and the tubes' union is one solid holding the point (1, 0.8, 0), inside both tubes
        (V 869.3323, 869.2494 before SC7's readouts; 7 faces, BOP finds only the C0 edges it finds at r 4). The overlap lies in leg 1's
        tube (r 1) where leg 3 reaches below y 1, which needs its radius over 5: x < 3.4 for a radius
        growing evenly from 1 at x 30. So the union is under the double-counted volume and over it
        less a 6 long piece of leg 1's tube (twice that reach)."""
        doubled = 869.6967
        pipe = self.multisection(5.5)
        self.assertOneSolid(pipe)
        self.assertTrue(pipe.Shape.isInside(V(1, 0.8, 0), 1e-6, True))
        volume = pipe.Shape.Volume
        self.assertLess(volume, doubled - 0.1)
        self.assertGreater(volume, doubled - 6 * math.pi)
        self.assertAlmostEqual(volume, 869.3323, places=2)

    def testASectionClearOfTheOtherLegSweepsAsBefore(self):
        """The end section r 4 reaches y 2 at x = 0, clear of leg 1's tube (y 1): the check runs (the
        sections' reach, 4, against legs 6 apart) and finds nothing, and the sweep is as before
        (V 569.609 on the build without the sections' reach)."""
        self.assertOneSolid(self.multisection(4), 569.7189, places=2)


class TestPipeSelfOverlapUntouched(PipeCase):
    """Legs that pass near each other arm the self-overlap check, and the union's maker finds no
    face splitting another (sweeps 16, b9-stops): OCCT's self-interference check decides then, as
    before the union, since an overlap within one face (a looping edge) is never checked against
    itself. A 2 x 0.2 rectangle normal to X at the origin, swept in Mode Standard: legs whose tubes
    face each other edge-on don't meet, and the sweep is the plain one (its area 0.4 x the path's
    length: the legs meet in mitres)."""

    def strip(self, points, wide, spline=None):
        """`wide`: 2 across the path in its plane (0.2 out of it); else 0.2 across, 2 out of it."""
        geometry = models.polyline(points) if len(points) > 1 else []
        if spline:
            curve = Part.BSplineCurve()
            curve.interpolate([V(x, y, 0) for x, y in spline])
            geometry.append(curve)
        path = self.sketch("Path", geometry)
        start = (points or spline)[0]
        rectangle = models.rectangle(-1, -0.1, 1, 0.1) if wide else models.rectangle(-0.1, -1, 0.1, 1)
        placement = App.Placement(V(start[0], start[1], 0), YZ.Rotation)
        profile = self.sketch("Profile", rectangle, placement=placement)
        return self.pipe(profile, path, Refine=False)

    def testEdgeOnLegsSweepPlainly(self):
        """Legs 1 and 3 1.5 apart (the profile's reach about 1.005 arms the check), each 0.1 thick
        toward the other: 0.4 x (20 + 1.5 + 19)."""
        self.assertSweeps(self.strip([(0, 0), (20, 0), (20, 1.5), (1, 1.5)], False), 0.4 * 40.5, places=4)

    def testLegsJustClearSweepPlainly(self):
        """Legs 1 and 3 2.005 apart, each reaching 1 toward the other (a 0.005 gap), and a last leg
        folding back from leg 3 at 20 degrees: 0.4 x (20 + 2.005 + 19 + 11 / cos 20)."""
        t = math.tan(math.radians(20))
        pipe = self.strip([(0, 0), (20, 0), (20, 2.005), (1, 2.005), (12, 2.005 + 11 * t)], True)
        self.assertSweeps(pipe, 0.4 * (41.005 + 11 / math.cos(math.radians(20))), places=4)

    def testALoopingEdgeStops(self):
        """One B-spline edge loops back 1.4 from itself under the profile's 2 across: its tube overlaps
        within its own face (Onshape not asked; FreeCAD-CH stops)."""
        loop = [(10, 2.005), (6, 2.005), (2, 3), (1, 6), (4, 8.5), (7, 7), (7, 4.6), (4, 4.0)]
        self.assertStops(self.strip([], True, spline=loop), "valid solid")


class TestPipeTwist(PipeCase):
    """SW11: twist is linear in the path's length; `TwistCCW` off = clockwise about the path's direction.
    Line z 0..20, a 4x4 square centred on it: every section is the square (320), turned."""

    def square(self, half=2, name="Profile"):
        return self.sketch(name, models.rectangle(-half, -half, half, half))

    def twisted(self, **properties):
        return self.pipe(self.square(), self.line(0, 20), HasTwist=True, **properties)

    def corner(self, degrees, z):
        a = math.radians(45 + degrees)
        return (2 * math.sqrt(2) * math.cos(a), 2 * math.sqrt(2) * math.sin(a), z)

    def assertCornerAt(self, pipe, degrees, z):
        section = pipe.Shape.slice(V(0, 0, 1), z)
        points = [v.Point for wire in section for v in wire.Vertexes]
        nearest = min((p - V(*self.corner(degrees, z))).Length for p in points)
        self.assertLess(nearest, 1e-4, (degrees, z, [tuple(round(c, 3) for c in p) for p in points]))

    def testAngleClockwise(self):
        """ANGLE 30, ccw off: (2, 2, 0) ends at (2.732, 0.733, 20), -15 degrees at z 10."""
        pipe = self.twisted(TwistType="Angle", TwistAngle=30)
        self.assertSweeps(pipe, 320, places=4)
        self.assertHasVertices(pipe.Shape, [self.corner(-30, 20)], 1e-6)
        self.assertCornerAt(pipe, -15, 10)

    def testAngleCounterClockwise(self):
        pipe = self.twisted(TwistType="Angle", TwistAngle=30, TwistCCW=True)
        self.assertSweeps(pipe, 320, places=4)
        self.assertHasVertices(pipe.Shape, [self.corner(30, 20)], 1e-6)

    def testOneTurn(self):
        """TURNS 1: back to (2, 2, 20), at (-2, -2) at z 10."""
        pipe = self.twisted(TwistType="Turns", Turns=1)
        self.assertSweeps(pipe, 320, places=4)
        self.assertHasVertices(pipe.Shape, [(2, 2, 20)], 1e-6)
        self.assertCornerAt(pipe, -180, 10)

    def testPitch(self):
        """PITCH 15: 20/15 turns, -480 degrees: (0.736, -2.731, 20)."""
        pipe = self.twisted(TwistType="Pitch", TwistPitch=15)
        self.assertSweeps(pipe, 320, places=3)
        self.assertHasVertices(pipe.Shape, [self.corner(-480, 20)], 1e-5)

    def testProfileAtTheFarEndTwistsWithTheSameHand(self):
        """The line drawn from z 20 down to 0, the profile at z 0: still -30 degrees at z 20."""
        path = self.sketch("Path", models.polyline([(0, 20), (0, 0)]), placement=XZ)
        pipe = self.pipe(self.square(), path, HasTwist=True, TwistType="Angle", TwistAngle=30)
        self.assertSweeps(pipe, 320, places=4)
        self.assertHasVertices(pipe.Shape, [self.corner(-30, 20)], 1e-6)

    def testAlongAnArcKeepsTheSection(self):
        """A quarter arc r 20 (SW2's), one turn: every section the square, Pappus 16 x 10 pi."""
        path = self.sketch("Path", [arc3((0, 0, 0), (20, 0, 0), (20, 20, 0))], placement=XZ)
        pipe = self.pipe(self.square(), path, HasTwist=True, TwistType="Turns", Turns=1)
        self.assertSweeps(pipe, 16 * 10 * math.pi, places=3)

    def testKeepOrientationStops(self):
        self.assertStops(self.twisted(ProfileControl="Keep orientation"), "twist", "None")

    def testProfileInTheMiddleWithExtendTwistsBothWays(self):
        """SW17: line z -10..10, the profile at z 0, Extend on, ANGLE 30: reached at the one-way end
        (-Z: +30 degrees about +Z), going on past the profile (-30 at z +10). V 320."""
        pipe = self.pipe(self.square(), self.line(-10, 10), HasTwist=True, TwistType="Angle",
                         TwistAngle=30, ExtendToFullPath=True)
        self.assertSweeps(pipe, 320, places=4)
        self.assertHasVertices(pipe.Shape, [self.corner(30, -10), self.corner(-30, 10)], 1e-6)

    def testTwistAngleIsOverTheProfileToTheOneWayEnd(self):
        """SW17: path z -15..5: +30 degrees at z -15, -10 at z +5 (2 degrees a mm)."""
        pipe = self.pipe(self.square(), self.line(-15, 5), HasTwist=True, TwistType="Angle",
                         TwistAngle=30, ExtendToFullPath=True)
        self.assertSweeps(pipe, 320, places=4)
        self.assertHasVertices(pipe.Shape, [self.corner(30, -15), self.corner(-10, 5)], 1e-6)

    def testProfileInTheMiddleOneWay(self):
        """SW17 (d): Extend off: one way to -Z, +30 degrees at z -10, V 160."""
        pipe = self.pipe(self.square(), self.line(-10, 10), HasTwist=True, TwistType="Angle",
                         TwistAngle=30)
        self.assertSweeps(pipe, 160, places=4)
        self.assertHasVertices(pipe.Shape, [self.corner(30, -10)], 1e-6)

    def testEndFaceKeepsItsNameAcrossTwistEdits(self):
        """A pad on the end face (ops#379's case) follows edits of the twist's angle, turns and hand."""
        pipe = self.twisted(TwistType="Angle", TwistAngle=30)
        self.assertSweeps(pipe)
        end = [f"Face{i}" for i, f in enumerate(pipe.Shape.Faces, 1)
               if abs(f.CenterOfMass.z - 20) < 1e-6 and f.Surface.isPlanar()]
        self.assertEqual(len(end), 1)
        top = self.body.newObject("Sketcher::SketchObject", "OnEnd")
        top.AttachmentSupport = [(pipe, end[0])]
        top.MapMode = "FlatFace"
        top.addGeometry(models.circle(0, 0, 1), False)
        pad = models.pad(self.body, top, 5)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        for edit in ({"TwistAngle": 75}, {"TwistType": "Turns", "Turns": 2}, {"TwistCCW": True}):
            for name, value in edit.items():
                setattr(pipe, name, value)
            self.doc.recompute()
            self.assertSweeps(pipe, 320, places=3)
            self.assertTrue(pad.isValid(), (edit, pad.getStatusString()))
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 25, 4)
            self.assertAlmostEqual(pad.Shape.Volume, 320 + 5 * math.pi, 3)


class TestPipeScale(PipeCase):
    """SW12: the radius is linear in the path's length, reaching `ScaleFactor` at the path's end; with
    the profile in the middle and Extend to full path on, it goes on linearly past the profile."""

    def testFactorTwo(self):
        """Line z 0..20, circle r 2, factor 2: 586.431 (r 3 at z 10, cap 16 pi at z 20)."""
        pipe = self.pipe(self.circle(), self.line(0, 20), HasScale=True, ScaleFactor=2)
        self.assertSweeps(pipe, math.pi * 10 / 3 * (64 - 8), places=3)
        self.assertAlmostEqual(Part.Face(pipe.Shape.slice(V(0, 0, 1), 10)[0]).Area, 9 * math.pi, 3)
        caps = [f.Area for f in pipe.Shape.Faces if f.Surface.isPlanar() and abs(f.CenterOfMass.z - 20) < 1e-6]
        self.assertEqual(len(caps), 1)
        self.assertAlmostEqual(caps[0], 16 * math.pi, 3)

    def testLinearInLengthAcrossEdges(self):
        """Line z 0..10, then a tangent quarter arc r 10 to (10, 0, 20): length L = 10 + 5 pi. Radius
        2 -> 4 linear in length: 2 (1 + 10 / L) at the joint, and the volume pi L (4 + 8 + 16) / 3."""
        path = self.sketch("Path", models.polyline([(0, 0), (0, 10)])
                           + [arc3((0, 10, 0), (10, 10, 0), (10, 20, 0))], placement=XZ)
        pipe = self.pipe(self.circle(), path, HasScale=True, ScaleFactor=2)
        length = 10 + 5 * math.pi
        self.assertSweeps(pipe, math.pi * length * 28 / 3, places=2)
        r = 2 * (1 + 10 / length)
        self.assertAlmostEqual(Part.Face(pipe.Shape.slice(V(0, 0, 1), 10 - 1e-6)[0]).Area, math.pi * r * r, 3)

    def testInTheMiddleOneWay(self):
        """Line z -10..10, profile at z 0, extend off: -Z only, r 2 -> 4 at z -10 (293.215)."""
        pipe = self.pipe(self.circle(), self.line(-10, 10), HasScale=True, ScaleFactor=2)
        self.assertSweeps(pipe, math.pi * 10 / 3 * (64 - 8) / 2, places=3)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMin, -10, 4)
        self.assertAlmostEqual(pipe.Shape.BoundBox.XMax, 4, 3)

    def testInTheMiddleExtendedGoesOnPastTheProfile(self):
        """Extend on, factor 1.5: r 3 at z -10, r 1 at z +10 (272.271)."""
        pipe = self.pipe(self.circle(), self.line(-10, 10), HasScale=True, ScaleFactor=1.5,
                         ExtendToFullPath=True)
        self.assertSweeps(pipe, math.pi * 20 * (1 + 3 + 9) / 3, places=3)
        self.assertAlmostEqual(pipe.Shape.BoundBox.ZMin, -10, 4)
        self.assertAlmostEqual(Part.Face(pipe.Shape.slice(V(0, 0, 1), -9.9)[0]).Area, math.pi * 2.99 ** 2, 3)

    def testScaleReachingZeroStops(self):
        """Extend on, factor 2: r 0 at z +10. Onshape: SWEEP_SCALE_LESS_THAN_ZERO."""
        pipe = self.pipe(self.circle(), self.line(-10, 10), HasScale=True, ScaleFactor=2,
                         ExtendToFullPath=True)
        self.assertStops(pipe, "scale", "zero")

    def testScaleAndTwistTogether(self):
        """A square scaled 2 and turned 90 degrees: every section a square, V = 16 x 20 x 7 / 3."""
        square = self.sketch("Profile", models.rectangle(-2, -2, 2, 2))
        pipe = self.pipe(square, self.line(0, 20), HasScale=True, ScaleFactor=2, HasTwist=True,
                         TwistType="Angle", TwistAngle=90)
        self.assertSweeps(pipe, 16 * 20 * 7 / 3, places=3)
        self.assertHasVertices(pipe.Shape, [(4, -4, 20)], 1e-5)


class TestPipeLock(PipeCase):
    """SW13: Lock direction normal to the arc's plane is the same as None; in the arc's plane it fails.
    Lock faces on a path that lies on the faces gives the same as None."""

    def quarterArc(self):
        return self.sketch("Path", [arc3((0, 0, 0), (20, 0, 0), (20, 20, 0))], placement=XZ)

    def square(self):
        return self.sketch("Profile", models.rectangle(-2, -2, 2, 2))

    def testLockDirectionNormalToThePathIsNone(self):
        plane = models.originFeature(self.body, "XZ_Plane")
        pipe = self.pipe(self.square(), self.quarterArc(), ProfileControl="Lock direction",
                         LockDirection=(plane, [""]))
        self.assertSweeps(pipe, 16 * 10 * math.pi, places=3)
        self.assertEqual(pipe.Mode, "Binormal")

    def testLockDirectionIgnoresTwist(self):
        """SW0: Onshape shows Twist only for None and Keep orientation; a twist left set does nothing."""
        plane = models.originFeature(self.body, "XZ_Plane")
        pipe = self.pipe(self.square(), self.quarterArc(), ProfileControl="Lock direction",
                         LockDirection=(plane, [""]), HasTwist=True, TwistType="Angle", TwistAngle=45)
        self.assertSweeps(pipe, 16 * 10 * math.pi, places=3)
        self.assertHasVertices(pipe.Shape, [(20, 2, 18), (20, -2, 22)], 1e-5)

    def testLockDirectionInThePathsPlaneStops(self):
        plane = models.originFeature(self.body, "YZ_Plane")
        pipe = self.pipe(self.square(), self.quarterArc(), ProfileControl="Lock direction",
                         LockDirection=(plane, [""]))
        self.assertStops(pipe, "binormal")

    def testLockDirectionWithoutADirectionStops(self):
        self.assertStops(self.pipe(self.square(), self.quarterArc(), ProfileControl="Lock direction"),
                         "Lock direction")

    def boxTop(self):
        box = models.box(self.doc, "Box", (20, 20, 10))  # outside the body
        self.doc.recompute()
        top = [f"Face{i}" for i, f in enumerate(box.Shape.Faces, 1) if abs(f.CenterOfMass.z - 10) < 1e-6]
        self.assertEqual(len(top), 1)
        return box, top

    def testLockFacesOnAPlanarFaceIsNone(self):
        """An arc on a box's top face (z 10), a square standing on it: the same as None."""
        box, top = self.boxTop()
        path = self.sketch("Path", [arc3((5, 15, 0), (5, 5, 0), (15, 5, 0))], z=10)
        profile = self.sketch("Profile", models.rectangle(-1, 0, 1, 2), placement=App.Placement(
            V(5, 15, 10), App.Rotation(V(0, 1, 0), 90)))
        locked = self.pipe(profile, path, ProfileControl="Lock faces", LockFaces=[(box, top)])
        # The square spans radii 10..12 about (5, 5), 2 high, over a quarter turn
        self.assertSweeps(locked, math.pi / 4 * (144 - 100) * 2, places=4)
        self.assertAlmostEqual(locked.Shape.BoundBox.ZMin, 9, 3)
        self.assertHasVertices(locked.Shape, [(17, 5, 9), (15, 5, 11)], 1e-6)

    def testLockFacesOffThePathStops(self):
        box, top = self.boxTop()
        path = self.sketch("Path", models.polyline([(5, 5), (15, 5)]), z=11)
        profile = self.sketch("Profile", models.rectangle(-1, -1, 1, 1), placement=App.Placement(
            V(5, 5, 11), App.Rotation(V(0, 1, 0), 90)))
        pipe = self.pipe(profile, path, ProfileControl="Lock faces", LockFaces=[(box, top)])
        self.assertStops(pipe, "leaves the lock faces")


class TestPipeThin(PipeCase):
    """SW14: Thin sweeps a wall around the profile's curves. An open curve's wall goes to the right of
    its drawn direction, seen from the sketch's normal (a Top line drawn +X walls to -Y); Midplane centres
    it, FlipWall puts it on the other side, Thickness2 is the other side's. A closed loop is a region: its
    wall is a ring outward (FlipWall: inward). TrimEnds has no effect, as in Onshape."""

    def strip(self, points=((-2, 0), (2, 0))):
        return self.sketch("Profile", models.polyline(list(points)))

    def assertBox(self, shape, xmin, ymin, zmin, xmax, ymax, zmax, places=4):
        box = shape.BoundBox
        for got, want in zip((box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax),
                             (xmin, ymin, zmin, xmax, ymax, zmax)):
            self.assertAlmostEqual(got, want, places, box)

    def testOpenLineWallsToTheRight(self):
        """Line (-2, 0) -> (2, 0) on Top, thickness 1: y -1..0, 80."""
        pipe = self.pipe(self.strip(), self.line(0, 20), BodyType="Thin", Thickness1=1)
        self.assertSweeps(pipe, 80)
        self.assertBox(pipe.Shape, -2, -1, 0, 2, 0, 20)

    def testMidplane(self):
        pipe = self.pipe(self.strip(), self.line(0, 20), BodyType="Thin", Thickness1=1, Midplane=True)
        self.assertSweeps(pipe, 80)
        self.assertBox(pipe.Shape, -2, -0.5, 0, 2, 0.5, 20)

    def testFlipWall(self):
        pipe = self.pipe(self.strip(), self.line(0, 20), BodyType="Thin", Thickness1=1, FlipWall=True)
        self.assertSweeps(pipe, 80)
        self.assertBox(pipe.Shape, -2, 0, 0, 2, 1, 20)

    def testThickness2IsTheOtherSide(self):
        """SW18 (e): thickness 1 to the right, 0.5 to the left (Midplane off): y -1..0.5, 120."""
        pipe = self.pipe(self.strip(), self.line(0, 20), BodyType="Thin", Thickness1=1, Thickness2=0.5)
        self.assertSweeps(pipe, 120)
        self.assertBox(pipe.Shape, -2, -1, 0, 2, 0.5, 20)

    def testTrimEndsHasNoEffect(self):
        pipe = self.pipe(self.strip(), self.line(0, 20), BodyType="Thin", Thickness1=1, TrimEnds=False)
        self.assertSweeps(pipe, 80)

    def testClosedLoopIsARingOutward(self):
        """Circle r 2, thickness 0.5: a tube r 2..2.5, 141.372."""
        pipe = self.pipe(self.circle(), self.line(0, 20), BodyType="Thin", Thickness1=0.5)
        self.assertSweeps(pipe, math.pi * (2.5 ** 2 - 4) * 20)
        self.assertBox(pipe.Shape, -2.5, -2.5, 0, 2.5, 2.5, 20)
        self.assertTrue(pipe.Shape.isInside(V(2.25, 0, 10), 1e-7, True))
        self.assertFalse(pipe.Shape.isInside(V(1, 0, 10), 1e-7, True))

    def testClosedLoopFlippedIsARingInward(self):
        pipe = self.pipe(self.circle(), self.line(0, 20), BodyType="Thin", Thickness1=0.5, FlipWall=True)
        self.assertSweeps(pipe, math.pi * (4 - 1.5 ** 2) * 20)
        self.assertBox(pipe.Shape, -2, -2, 0, 2, 2, 20)

    def testAlongABentPath(self):
        """SW4's path (line z 0..10, quarter arc r 10 to (10, 0, 20), line to (30, 0, 20)), the line's
        wall: 4 x (10 + 5 pi + 20) = 182.832, the wall staying across the path's plane."""
        path = self.sketch("Path", models.polyline([(0, 0), (0, 10)])
                           + [arc3((0, 10, 0), (10, 10, 0), (10, 20, 0))]
                           + models.polyline([(10, 20), (30, 20)]), placement=XZ)
        pipe = self.pipe(self.strip(), path, BodyType="Thin", Thickness1=1)
        self.assertSweeps(pipe, 4 * (30 + 5 * math.pi), places=3)
        self.assertAlmostEqual(pipe.Shape.BoundBox.YMin, -1, 4)
        self.assertAlmostEqual(pipe.Shape.BoundBox.YMax, 0, 4)

    def corner(self):
        return self.strip(((-2, 0), (2, 0), (2, 3)))

    def testWallInsideACorner(self):
        """SW18 (b): polyline (-2, 0) -> (2, 0) -> (2, 3), the wall on its left (inside the corner): 120."""
        pipe = self.pipe(self.corner(), self.line(0, 20), BodyType="Thin", Thickness1=1, FlipWall=True)
        self.assertSweeps(pipe, 120)
        self.assertBox(pipe.Shape, -2, 0, 0, 2, 3, 20)

    def testWallOutsideACornerIsSharp(self):
        """SW18 (a): the wall round the corner's outside is mitred, never rounded: 4 + 3 + the 1 x 1
        corner, x 20 = 160, F 8, no cylinder."""
        pipe = self.pipe(self.corner(), self.line(0, 20), BodyType="Thin", Thickness1=1)
        self.assertSweeps(pipe, 160)
        self.assertBox(pipe.Shape, -2, -1, 0, 3, 3, 20)
        self.assertEqual(len(pipe.Shape.Faces), 8)
        self.assertTrue(all(f.Surface.TypeId == "Part::GeomPlane" for f in pipe.Shape.Faces))
        self.assertHasVertices(pipe.Shape, [(3, -1, 0), (3, -1, 20)], 1e-6)

    def square(self):
        return self.sketch("Profile", models.rectangle(-2, -2, 2, 2))

    def testClosedSquareOutwardIsSharp(self):
        """SW18 (c): square (-2, -2)..(2, 2), thickness 0.5: (25 - 16) x 20 = 180, F 10, box +-2.5."""
        pipe = self.pipe(self.square(), self.line(0, 20), BodyType="Thin", Thickness1=0.5)
        self.assertSweeps(pipe, 180)
        self.assertBox(pipe.Shape, -2.5, -2.5, 0, 2.5, 2.5, 20)
        self.assertEqual(len(pipe.Shape.Faces), 10)
        self.assertTrue(all(f.Surface.TypeId == "Part::GeomPlane" for f in pipe.Shape.Faces))

    def testClosedSquareFlippedIsInward(self):
        """SW18 (c): flipWall: (16 - 9) x 20 = 140, inward, box +-2."""
        pipe = self.pipe(self.square(), self.line(0, 20), BodyType="Thin", Thickness1=0.5, FlipWall=True)
        self.assertSweeps(pipe, 140)
        self.assertBox(pipe.Shape, -2, -2, 0, 2, 2, 20)

    def testLineDrawnBackwardsWallsToItsRight(self):
        """SW18 (d): a line drawn (2, 0) -> (-2, 0): its right seen from +Z is +Y: y 0..1, 80."""
        pipe = self.pipe(self.strip(((2, 0), (-2, 0))), self.line(0, 20), BodyType="Thin", Thickness1=1)
        self.assertSweeps(pipe, 80)
        self.assertBox(pipe.Shape, -2, 0, 0, 2, 1, 20)

    def testZeroThicknessStops(self):
        pipe = self.pipe(self.strip(), self.line(0, 20), BodyType="Thin", Thickness1=0)
        self.assertStops(pipe, "thickness")

    def testSubtractiveThinCutsTheWall(self):
        """A 10 x 10 x 10 box less the line's wall along z 0..10 (40)."""
        box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 10
        box.Placement.Base = V(-5, -5, 0)
        path = self.line(0, 10)
        pipe = self.pipe(self.strip(), path, kind="SubtractivePipe", BodyType="Thin", Thickness1=1)
        self.assertSweeps(pipe, 1000 - 40)

    def faceNameAt(self, pipe, point):
        """The mapped name of the one face of `pipe` holding `point`."""
        found = [i for i, f in enumerate(pipe.Shape.Faces, 1)
                 if f.distToShape(Part.Vertex(V(*point)))[0] < 1e-6]
        self.assertEqual(len(found), 1, (point, found))
        return pipe.Shape.getElementMappedName("Face%d" % found[0])

    def assertSidesKeepTheirNames(self, points, **properties):
        """The wall's sides along the last curve of the polyline (0,0)-(10,0)-(10,-8) keep their names when
        a segment (10,-8)-(0,-8) follows it (sweeps 19, ops#640): each side's face, at x = 10 +- `points`,
        is named from the curve alone, never as a twin counted with a piece of the wall's end."""
        profile = self.strip(((0, 0), (10, 0), (10, -8)))
        pipe = self.pipe(profile, self.line(0, 20), BodyType="Thin", **properties)
        before = [self.faceNameAt(pipe, (x, -4, 10)) for x in points]
        profile.addGeometry(Part.LineSegment(V(10, -8, 0), V(0, -8, 0)), False)
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        after = [self.faceNameAt(pipe, (x, -4, 10)) for x in points]
        self.assertEqual(before, after)

    def testMidplaneLastCurveSidesKeepTheirNames(self):
        self.assertSidesKeepTheirNames((9.5, 10.5), Thickness1=1, Midplane=True)

    def testTwoSidedLastCurveSidesKeepTheirNames(self):
        self.assertSidesKeepTheirNames((9, 10.5), Thickness1=1, Thickness2=0.5)


class TestPipeThinReferencesKeepTheirSide(PipeCase):
    """Oracle 12, Q-THIN-MID (THM1-THM4, sweeps 20, ops#640): a thin sweep along a 90 degree left turn, path
    (0,0)-(30,0)-(30,20) on Top, of an open profile on Right, the line y 0, z 0..10 (drawn up, so the wall goes
    to +y, the inside of the bend), thickness 2. A sketch on the inside wall A (y 2 in the base) holds a circle
    r 2 at x 10, z 5, padded 1 mm; a fillet r 0.5 rounds the top edge of the outside wall B (y 0) on the
    first leg. Onshape keeps each reference on its side of the bend in every (Midplane, FlipWall) state, and
    with Midplane on Flip changes nothing. The wall's corner is mitred, so the solid is the L of the wall's
    two legs; its volume is 10 x that L's area, plus the boss's 4 pi, less the fillet's (1 - pi / 4) r^2 along
    the outside edge of the first leg: 970.957, 1010.903, 1050.850 and 1010.903 (Onshape: 970.96, 1010.90,
    1050.85, 1010.90)."""

    # (Midplane, FlipWall) -> the wall on the first leg, y0..y1: A is the y1 side, B the y0 side
    WALL = {(False, False): (0, 2), (True, False): (-1, 1), (False, True): (-2, 0), (True, True): (-1, 1)}

    def expectedVolume(self, y0, y1):
        # The L: the first leg x 0..30 + (the outside's reach past the corner), the second leg's 20 + the same
        reach = -y0
        legs = (30 + reach) * 2 + (20 + reach) * 2 - 4
        fillet = (1 - math.pi / 4) * 0.25 * (30 + reach)
        return 10 * legs + 4 * math.pi - fillet

    def faceAt(self, shape, point, normal):
        found = [i for i, f in enumerate(shape.Faces, 1)
                 if f.Surface.TypeId == "Part::GeomPlane" and f.distToShape(Part.Vertex(V(*point)))[0] < 1e-6
                 and abs(f.normalAt(0, 0).dot(V(*normal)) - 1) < 1e-6]
        self.assertEqual(len(found), 1, (point, found))
        return "Face%d" % found[0]

    def edgeAt(self, shape, a, b):
        found = [i for i, e in enumerate(shape.Edges, 1)
                 if e.distToShape(Part.Vertex(V(*a)))[0] < 1e-6 and e.distToShape(Part.Vertex(V(*b)))[0] < 1e-6]
        self.assertEqual(len(found), 1, (a, b, found))
        return "Edge%d" % found[0]

    def build(self):
        path = self.sketch("Path", models.polyline([(0, 0), (30, 0), (30, 20)]))
        right = App.Placement(V(0, 0, 0), App.Rotation(0.5, 0.5, 0.5, 0.5))  # sketch (x, y) -> (0, x, y)
        profile = self.sketch("Profile", models.polyline([(0, 0), (0, 10)]), placement=right)
        pipe = self.pipe(profile, path, BodyType="Thin", Thickness1=2)
        self.assertSweeps(pipe, 960)
        sketch = self.body.newObject("Sketcher::SketchObject", "SketchOnA")
        sketch.AttachmentSupport = [(pipe, self.faceAt(pipe.Shape, (15, 2, 5), (0, 1, 0)))]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        centre = sketch.Placement.inverse().multVec(V(10, 2, 5))
        sketch.addGeometry(Part.Circle(V(centre.x, centre.y, 0), V(0, 0, 1), 2), False)
        boss = models.pad(self.body, sketch, 1, name="BossOnA")
        self.doc.recompute()
        fillet = self.body.newObject("PartDesign::Fillet", "FilletOnB")
        fillet.Base = (boss, [self.edgeAt(boss.Shape, (5, 0, 10), (25, 0, 10))])
        fillet.Radius = 0.5
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        return pipe, sketch, boss, fillet

    def assertState(self, features, midplane, flip):
        pipe, sketch, boss, fillet = features
        pipe.Midplane = midplane
        pipe.FlipWall = flip
        self.doc.recompute()
        state = (midplane, flip)
        for feature in features:
            self.assertTrue(feature.isValid(), (state, feature.Name, feature.getStatusString()))
        y0, y1 = self.WALL[state]
        # The sketch on A, facing +y, at x 10 z 5
        self.assertAlmostEqual(sketch.Placement.Base.y, y1, 6, state)
        normal = sketch.Placement.Rotation.multVec(V(0, 0, 1))
        self.assertLess((normal - V(0, 1, 0)).Length, 1e-9, (state, normal))
        circle = sketch.Shape.Edges[0]
        self.assertLess((circle.Curve.Center - V(10, y1, 5)).Length, 1e-6, (state, circle.Curve.Center))
        # The boss on A, y1..y1 + 1; the fillet on B's top edge, y0..y0 + 0.5
        bossFaces = [f for f in fillet.Shape.Faces if f.Surface.TypeId == "Part::GeomCylinder"
                     and abs(f.Surface.Radius - 2) < 1e-6]
        self.assertEqual(len(bossFaces), 1, state)
        self.assertAlmostEqual(bossFaces[0].BoundBox.YMin, y1, 5, state)
        self.assertAlmostEqual(bossFaces[0].BoundBox.YMax, y1 + 1, 5, state)
        rounds = [f for f in fillet.Shape.Faces if f.Surface.TypeId == "Part::GeomCylinder"
                  and abs(f.Surface.Radius - 0.5) < 1e-6]
        self.assertEqual(len(rounds), 1, state)
        box = rounds[0].BoundBox
        self.assertAlmostEqual(box.YMin, y0, 5, state)
        self.assertAlmostEqual(box.YMax, y0 + 0.5, 5, state)
        self.assertAlmostEqual(box.ZMax, 10, 5, state)
        self.assertAlmostEqual(fillet.Shape.Volume, self.expectedVolume(y0, y1), 2, state)

    def testEachStateFromTheBase(self):
        """Oracle 12's steps 1, 2 and 3, each from the base."""
        for state in ((True, False), (False, True), (True, True)):
            features = self.build()
            self.assertState(features, False, False)
            self.assertState(features, *state)
            App.closeDocument(self.doc.Name)
            self.setUp()

    def testInSequence(self):
        """THM3's 16 updates in sequence: each state reads the same every time."""
        features = self.build()
        self.assertState(features, False, False)
        for midplane, flip in ((1, 0), (0, 0), (0, 1), (0, 0), (0, 1), (1, 1), (1, 0), (1, 1), (1, 0), (0, 0),
                               (0, 1), (1, 1), (1, 0), (1, 1), (1, 0), (0, 0)):
            self.assertState(features, bool(midplane), bool(flip))
