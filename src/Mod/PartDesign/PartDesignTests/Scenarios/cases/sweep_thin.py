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
on the second segment's curve the plane x = 10 ((10, -4, 10))."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Bound, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


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
    thick2 = 0.0

    def curve1(self):
        return face(surface="plane", contains=(5, 0, 10))

    def offset1(self):
        return face(surface="plane", contains=(5, -self.thick, 10))

    def curve2(self):
        return face(surface="plane", contains=(10, -4, 10))

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
        pipe.Thickness2 = self.thick2
        self.pipe = pipe
        doc.recompute()
        for ref in self.REFS:
            expect = getattr(self, ref)
            binder = doc.addObject("PartDesign::SubShapeBinder", "Bind" + ref)
            binder.Support = [(pipe, tuple(self.names(pipe, expect())))]
            self.ref(ref, binder, "Support", expect, Bound())
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
    the second); the curves' faces stay where they were."""

    abstract = False
    REFS = ("curve1", "curve2")

    def edit(self, doc):
        self.pipe.FlipWall = True
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
    """Midplane, and FlipWall set: the wall straddles the curve as before, so every side stays."""

    def edit(self, doc):
        self.pipe.FlipWall = True
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
