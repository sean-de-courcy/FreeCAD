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
            pipe.SpineMore = [m if isinstance(m, tuple) else (m, []) for m in more]
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
        the pad on the end face follows to the new end, 5 along the new edge's direction."""
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
        tip = V(10, 0, 30) + V(1, 0, 1).normalize() * 5
        box = pad.AddSubShape.BoundBox
        self.assertLess((box.Center - (V(10, 0, 30) + tip) * 0.5).Length, 1e-3, box)

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
        box = pad.AddSubShape.BoundBox
        self.assertLess((box.Center - V(12.5, 0, 30)).Length, 1e-3, box)
