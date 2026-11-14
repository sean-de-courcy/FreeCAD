# SPDX-License-Identifier: LGPL-2.1-or-later
"""Thin sweeps (ops#640, sweeps 16; first as review prline-b6-r1's cases): a Pipe of BodyType Thin
sweeps a wall around the profile's curves (`thinProfileOf`), whose edges are named from the
profile's by geometry (`MapperThinWall`): on a curve, modified from it; parallel to it at the
wall's thickness, generated from it; through an open curve's end, generated from that vertex.
References to the side faces the sweep makes from the profile's own curves and from their
offsets; edits change the thickness, add a curve to the profile, or flip the wall. Onshape keeps
such references (its thin sweep names the wall's sides from the profile's curves).

The path: a line along Z, (0, 0, 0)-(0, 0, 20), drawn in the XZ plane. The open profile, in the XY
plane at z 0: a polyline (0,0)-(10,0)-(10,-8) (it turns right, so the wall's default side, the
right seen from +Z, is the corner's inside), Thickness1 `thick`. The wall is y -thick..0 along
the first segment and x 10-thick..10 along the second. The face on the first segment's curve is
the plane y = 0 (it holds (5, 0, 10)); its offset the plane y = -thick ((5, -thick, 10)); the face
on the second segment's curve the plane x = 10 ((10, -4, 10)).

Midplane and FlipWall (sweeps 20, oracle 12's THM1-THM4, ops `notes/onshape-facts.md`): Onshape keeps
each of the wall's sides on its own side of the curve in every (Midplane, Flip) state; nothing
swaps, and with Midplane on Flip changes nothing. A reference follows its side, not "the face on the
curve" or "the offset face": `left1`/`right1` are the first segment's sides left (+y) and right (-y)
of its drawn direction, `left2`/`right2` the second's (+x and -x), placed from the state."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Bound, Outcome, Scenario, edge, expectedNames, face, tolerance
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


class BoundEdges(Outcome):
    """A SubShapeBinder of edges: its shape has exactly the expected edges (each point of one on the
    other, the same length), as `Bound` is for faces."""

    def compare(self, scenario, consumer, target, expectation):
        expected = [target.Shape.getElement(n) for n in expectedNames(expectation, target.Shape)]
        edges = consumer.Shape.Edges
        tol = tolerance(target.Shape)
        if len(edges) != len(expected):
            return False, f"{len(edges)} edges bound for {len(expected)}"

        def same(a, b):
            return abs(a.Length - b.Length) <= tol and all(
                Part.Vertex(p).distToShape(b)[0] < tol for p in a.discretize(9))

        for e in expected:
            if not any(same(g, e) for g in edges):
                return False, f"no bound edge at {e.CenterOfMass} with length {e.Length:.4f}"
        return True, ""


class _ThinPipe(Scenario):
    abstract = True
    area = "pipe-thin"
    CLASSES = ("A",)
    AXES = ("M3", "E1")
    ISSUE = "ops#640"
    FOUND_BY = "review prline-b6-r1"
    TIER = "F"
    REFS = ("curve1", "offset1", "curve2")
    thick = 1.0
    points = ((0, 0), (10, 0), (10, -8))
    closed = False
    midplane = False
    flip = False
    thick2 = 0.0

    def _out(self):
        """How far the wall's left and right sides lie from the curve (Thickness2 is 0 here)."""
        if self.midplane:
            return self.thick / 2, self.thick / 2
        return (self.thick, 0.0) if self.flip else (0.0, self.thick)

    def left1(self):
        return face(surface="plane", contains=(5, self._out()[0], 10))

    def right1(self):
        return face(surface="plane", contains=(5, -self._out()[1], 10))

    def left2(self):
        return face(surface="plane", contains=(10 + self._out()[0], -4, 10))

    def right2(self):
        return face(surface="plane", contains=(10 - self._out()[1], -4, 10))

    def leftCorner(self):
        """The wall's edge along the path where the two segments' left sides meet (the outside of
        the profile's corner: the corner's own vertex in the base state)."""
        out = self._out()[0]
        return edge(curve="line", direction=(0, 0, 1), contains=(10 + out, out, 10))

    def rightCorner(self):
        """Where the right sides meet, the inside of the corner."""
        out = self._out()[1]
        return edge(curve="line", direction=(0, 0, 1), contains=(10 - out, -out, 10))

    def leftStart(self):
        """The edge along the path at the profile's start, on the left side."""
        return edge(curve="line", direction=(0, 0, 1), contains=(0, self._out()[0], 10))

    # In the base state the left sides lie on the curves and the first's right side is its offset
    curve1 = left1
    offset1 = right1
    curve2 = left2

    def build(self, doc):
        body = m.body(doc)
        self.path = m.sketch(doc, "Path", m.polyline([(0, 0), (0, 20)]), body, placement=XZ)
        shape = m.polygon if self.closed else m.polyline
        self.profile = m.sketch(doc, "Profile", shape(list(self.points)), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.BodyType = "Thin"
        pipe.Thickness1 = self.thick
        pipe.Midplane = self.midplane
        pipe.FlipWall = self.flip
        pipe.Thickness2 = self.thick2
        self.pipe = pipe
        doc.recompute()
        for ref in self.REFS:
            expect = getattr(self, ref)
            binder = doc.addObject("PartDesign::SubShapeBinder", "Bind" + ref)
            binder.Support = [(pipe, tuple(self.names(pipe, expect())))]
            self.ref(ref, binder, "Support", expect, BoundEdges() if expect().kind == "Edge" else Bound())
        doc.recompute()


class ThinPipeThicker(_ThinPipe):
    """Thickness1 1 -> 2: the offset face moves to y = -2; the curves' faces stay."""

    abstract = False

    def edit(self, doc):
        self.thick = 2.0
        self.pipe.Thickness1 = 2.0
        doc.recompute()


class ThinPipeCurveAdded(_ThinPipe):
    """A third segment (10,-8)-(0,-8) is added to the profile (a U, turning right again): the
    first two segments, their faces and the first's offset stay."""

    abstract = False

    def edit(self, doc):
        self.profile.addGeometry(Part.LineSegment(V(10, -8, 0), V(0, -8, 0)), False)
        doc.recompute()


class ThinPipeCurveAddedFirst(_ThinPipe):
    """A segment (0,-6)-(0,0) is added to the profile (the sketch's last geometry, but the wire's
    first edge: the curve now starts at (0,-6), going +y, then turns right twice). The wall's
    default side is the inside of both corners (x 0..1 along the new segment). The old segments'
    faces and the first's offset stay."""

    abstract = False

    def edit(self, doc):
        self.profile.addGeometry(Part.LineSegment(V(0, -6, 0), V(0, 0, 0)), False)
        doc.recompute()


class ThinPipeWallFlipped(_ThinPipe):
    """FlipWall: the wall goes to the curve's left (y 0..1 along the first segment, x 10..11 along
    the second). The references to the faces on the curves follow their side (THM1): the first's
    left side moves to y = 1, the second's to x = 11; the faces now on the curves are the right
    sides, a different reference's."""

    abstract = False
    REFS = ("curve1", "curve2", "leftCorner", "rightCorner", "leftStart")

    def edit(self, doc):
        self.flip = True
        self.pipe.FlipWall = True
        doc.recompute()


class ThinPipeToMidplane(_ThinPipe):
    """Midplane off -> on (oracle 12's step 1): the wall moves from y -1..0 to y -0.5..0.5; each side
    stays its side, the left (on the curve) to y = 0.5, the right (the offset) to y = -0.5."""

    abstract = False
    REFS = ("left1", "right1", "left2", "right2", "leftCorner", "rightCorner", "leftStart")

    def edit(self, doc):
        self.midplane = True
        self.pipe.Midplane = True
        doc.recompute()


class ThinPipeFlippedToMidplane(ThinPipeToMidplane):
    """FlipWall on, then Midplane off -> on (oracle 12's step 3, where sweeps 19 swapped the names):
    the wall moves from y 0..1 to y -0.5..0.5; the left side (the offset) to y = 0.5, the right (on
    the curve) to y = -0.5."""

    flip = True


class ThinPipeFromMidplane(_ThinPipe):
    """Midplane on -> off (THM3, the reverse of step 1): each side stays its side."""

    abstract = False
    midplane = True
    REFS = ("left1", "right1", "left2", "right2", "leftCorner", "rightCorner", "leftStart")

    def edit(self, doc):
        self.midplane = False
        self.pipe.Midplane = False
        doc.recompute()


class ThinPipeFlippedFromMidplane(ThinPipeFromMidplane):
    """FlipWall on and Midplane on -> off: the wall goes to y 0..1, the left side to y = 1, the
    right to y = 0 (on the curve)."""

    flip = True


class ThinPipeWallUnflipped(_ThinPipe):
    """FlipWall on -> off, Midplane off: the wall comes back to y -1..0; the left side from y = 1 to
    y = 0, the right from y = 0 to y = -1."""

    abstract = False
    flip = True
    REFS = ("left1", "right1", "left2", "right2", "leftCorner", "rightCorner", "leftStart")

    def edit(self, doc):
        self.flip = False
        self.pipe.FlipWall = False
        doc.recompute()


class ThinPipeRingThicker(_ThinPipe):
    """A closed profile, the rectangle (0,0)-(10,0)-(10,-8)-(0,-8), its wall outward (y 0..thick
    above the first side, x 10..10+thick beside the second): Thickness1 1 -> 2. The sides' faces
    stay; the first side's offset moves from y = 1 to y = 2."""

    abstract = False
    closed = True
    points = ((0, 0), (10, 0), (10, -8), (0, -8))

    def offset1(self):
        return face(surface="plane", contains=(5, self.thick, 10))

    def edit(self, doc):
        self.thick = 2.0
        self.pipe.Thickness1 = 2.0
        doc.recompute()


class ThinPipeRingCurveAdded(ThinPipeRingThicker):
    """The closed profile, and an open line (20,0)-(30,0) added to the sketch beside it (its own
    strip): the rectangle's faces and the first side's offset stay."""

    def edit(self, doc):
        self.profile.addGeometry(Part.LineSegment(V(20, 0, 0), V(30, 0, 0)), False)
        doc.recompute()


class ThinPipeMidplaneThicker(_ThinPipe):
    """Midplane: the wall straddles the open polyline, y -thick/2..thick/2 along the first segment
    and x 10-thick/2..10+thick/2 along the second, so each segment's two sides are offsets of the
    same curve (twins told apart only by their connected names, sweeps 16). Thickness1 1 -> 2:
    each side moves out by 0.5 and stays the side it was (Onshape names a thin sweep's sides from
    the profile's curves)."""

    abstract = False
    midplane = True
    REFS = ("upper1", "lower1", "outer2", "inner2")

    def upper1(self):
        return face(surface="plane", contains=(5, self.thick / 2, 10))

    def lower1(self):
        return face(surface="plane", contains=(5, -self.thick / 2, 10))

    def outer2(self):
        return face(surface="plane", contains=(10 + self.thick / 2, -4, 10))

    def inner2(self):
        return face(surface="plane", contains=(10 - self.thick / 2, -4, 10))

    def edit(self, doc):
        self.thick = 2.0
        self.pipe.Thickness1 = 2.0
        doc.recompute()


class ThinPipeMidplaneCurveAdded(ThinPipeMidplaneThicker):
    """Midplane, and a third segment (10,-8)-(0,-8) added to the profile: the first two segments'
    sides stay."""

    def edit(self, doc):
        self.profile.addGeometry(Part.LineSegment(V(10, -8, 0), V(0, -8, 0)), False)
        doc.recompute()


class ThinPipeMidplaneCurveAddedFirst(ThinPipeMidplaneThicker):
    """Midplane, and a segment (0,-6)-(0,0) added before the first (the wire's first edge now):
    the old segments' sides stay."""

    def edit(self, doc):
        self.profile.addGeometry(Part.LineSegment(V(0, -6, 0), V(0, 0, 0)), False)
        doc.recompute()


class ThinPipeMidplaneFlipped(ThinPipeMidplaneThicker):
    """Midplane, and FlipWall set: the wall straddles the curve as before, so every side stays
    (THM2: with Midplane on, Flip changes nothing)."""

    def edit(self, doc):
        self.flip = True
        self.pipe.FlipWall = True
        doc.recompute()


class ThinPipeMidplaneUnflipped(ThinPipeMidplaneFlipped):
    """Midplane and FlipWall on, then FlipWall off: nothing moves (THM2)."""

    flip = True

    def edit(self, doc):
        self.flip = False
        self.pipe.FlipWall = False
        doc.recompute()


class ThinPipeTwoSidedCurveAdded(_ThinPipe):
    """Thickness1 1 and Thickness2 0.5 (Midplane off): the wall is y -1..0.5 along the first
    segment, x 9..10.5 along the second (Thickness1 to the right of the drawn direction, SW18 (e)),
    both sides offsets of the curve. A third segment (10,-8)-(0,-8) is added: the first two
    segments' four sides stay."""

    abstract = False
    thick2 = 0.5
    REFS = ("right1", "left1", "right2", "left2")

    def right1(self):
        return face(surface="plane", contains=(5, -1, 10))

    def left1(self):
        return face(surface="plane", contains=(5, 0.5, 10))

    def right2(self):
        return face(surface="plane", contains=(9, -4, 10))

    def left2(self):
        return face(surface="plane", contains=(10.5, -4, 10))

    def edit(self, doc):
        self.profile.addGeometry(Part.LineSegment(V(10, -8, 0), V(0, -8, 0)), False)
        doc.recompute()
