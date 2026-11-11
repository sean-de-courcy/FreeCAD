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

    def testTubesOverlappingWhileThePathIsClearStop(self):
        """The path ends at (10, 0.5): the last tube runs 0.5 into the first, the path clear of itself.
        Onshape builds the exact union (154.3944, not the naive 155.509); FreeCAD-CH built the naive
        self-intersecting solid, Up-to-date. Until it builds the union, it stops with an error."""
        self.assertStops(self.tube((10, 0.5)), "overlaps itself")

    def testTubesClearOfEachOtherSweep(self):
        """The path ends at (10, 1.5): the tubes miss each other: pi x the path's length."""
        self.assertSweeps(self.tube((10, 1.5)), math.pi * 48.5, places=2)


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
