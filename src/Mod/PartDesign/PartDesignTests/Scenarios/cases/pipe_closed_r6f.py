# SPDX-License-Identifier: LGPL-2.1-or-later
"""The review of fork PR 383 round 6's fix (d1f59dcadc, decision 180), class B (ops#469): the
start corner moved along the profile's leg, where the names path's frame check can't carry it.

The ring of K4b as in `pipe_closed_r6.py` (copied: a case imports only harness and models): a
closed rectangle of four lines on the XZ plane, (0, Z0) -> (0, 20) -> (W, 20) -> (W, Z0), W = 30,
Z0 = 0 (sketch x = global X, sketch y = global Z), a square profile 2A x 2B (A in sketch x, B in
sketch y, normal Z, along the left leg) at the bottom left corner (0, 0, 0), "Right corner". The
stored start is the bottom left corner.

The edits move the bottom line down (Z0 < 0, the left and right lines lengthened, IDs kept): the
start corner moves down the left leg, away from the profile, which stays at z = 0 on that leg,
below its middle (the corner is still the profile's nearest vertex). No line is redrawn."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    Attached,
    Filleted,
    Scenario,
    X,
    Y,
    Z,
    edge,
    face,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector


class LoweredRing(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6f"
    TIER = "F"
    SIZE = 40
    SCALE = 1.0
    REFS = (
        "datum_left_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "fillet_top_front",
        "point_top_right",
        "point_bottom_left",
    )
    turn = 0
    width = 30
    bottom = 0  # the bottom line's z (unscaled)
    offX = 0  # the ring's and the profile's x (unscaled), off the turn's axis
    halfX = 2
    halfY = 2

    @property
    def W(self):
        return self.s(self.width)

    @property
    def H(self):
        return self.s(20)

    @property
    def Z0(self):
        return self.s(self.bottom)

    @property
    def A(self):
        return self.s(self.halfX)

    @property
    def B(self):
        return self.s(self.halfY)

    @property
    def X0(self):
        return self.s(self.offX)

    def corners(self):
        return [(0, self.Z0), (0, self.H), (self.W, self.H), (self.W, self.Z0)]

    def at(self, x, y, z):
        return App.Rotation(Z, self.turn).multVec(V(x + self.X0, y, z))

    def along(self, d):
        return App.Rotation(Z, self.turn).multVec(d)

    def leftOuter(self):
        return face("plane", normal=self.along(-X), contains=self.at(-self.A, 0, (self.Z0 + self.H) / 2))

    def topOuter(self):
        return face("plane", normal=Z, contains=self.at(self.W / 2, 0, self.H + self.A))

    def bottomInner(self):
        return face("plane", normal=Z, contains=self.at(self.W / 2, 0, self.Z0 + self.A))

    def topFront(self):
        return edge(
            "line",
            direction=self.along(X),
            through=self.at(0, -self.B, self.H + self.A),
            contains=self.at(self.W / 2, -self.B, self.H + self.A),
        )

    def topRight(self):
        return vertex(self.at(self.W + self.A, -self.B, self.H + self.A))

    def bottomLeft(self):
        return vertex(self.at(-self.A, -self.B, self.Z0 - self.A))

    def spinePlacement(self):
        return App.Placement(self.at(0, 0, 0), App.Rotation(Z, self.turn).multiply(App.Rotation(X, 90)))

    def profilePlacement(self):
        return App.Placement(self.at(0, 0, 0), App.Rotation(Z, self.turn))

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        self.spine = m.sketch(doc, "Spine", m.polygon(self.corners()), body, placement=self.spinePlacement())
        a, b = self.A, self.B
        self.profile = m.sketch(doc, "Square", m.rectangle(-a, -b, a, b), body, placement=self.profilePlacement())
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.spine, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        self.pipe = pipe
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        made = {}
        for name, kind, predicate, mode in self.attachments():
            obj = body.newObject(kind, name)
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            obj.MapMode = mode
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pipe, self.names(pipe, self.topFront()))
        fillet.Radius = self.s(0.5)
        self.ref("fillet_top_front", fillet, "Base", self.topFront, Filleted(self.s(0.5)))

    def attachments(self):
        return (
            ("datum_left_outer", "PartDesign::Plane", self.leftOuter, "FlatFace"),
            ("datum_top_outer", "PartDesign::Plane", self.topOuter, "FlatFace"),
            ("sketch_bottom_inner", "Sketcher::SketchObject", self.bottomInner, "FlatFace"),
            ("point_top_right", "PartDesign::Point", self.topRight, "Vertex"),
            ("point_bottom_left", "PartDesign::Point", self.bottomLeft, "Vertex"),
        )

    def widen(self, width):
        w, h, z0 = self.s(width), self.H, self.Z0
        g = self.spine.Geometry
        g[1].EndPoint = V(w, h, 0)
        g[2].StartPoint, g[2].EndPoint = V(w, h, 0), V(w, z0, 0)
        g[3].StartPoint = V(w, z0, 0)
        self.spine.Geometry = g
        self.width = width

    def lower(self, z):
        """The bottom line moved to z (unscaled): lines 0 and 2 lengthened, line 3 moved."""
        z0 = self.s(z)
        w, h = self.W, self.H
        g = self.spine.Geometry
        g[0].StartPoint = V(0, z0, 0)
        g[2].EndPoint = V(w, z0, 0)
        g[3].StartPoint, g[3].EndPoint = V(w, z0, 0), V(0, z0, 0)
        self.spine.Geometry = g
        self.bottom = z

    def turnModel(self):
        self.turn = 120
        self.spine.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()

    def stretchProfileY(self, factor):
        g = self.profile.Geometry
        for line in g:
            s, e = line.StartPoint, line.EndPoint
            line.StartPoint, line.EndPoint = V(s.x, s.y * factor, 0), V(e.x, e.y * factor, 0)
        self.profile.Geometry = g
        self.halfY *= factor


class RingLowered(LoweredRing):
    """Control: the bottom line moves from z = 0 to z = -4 (one edit, no turn; the fit is clear).
    Every reference stays, on the taller ring."""

    def edit(self, doc):
        self.lower(-4)


class RingLoweredFar(LoweredRing):
    """The bottom line moves from z = 0 to z = -15 (one edit, no turn, the profile untouched): the
    start corner moves down the left leg to (0, 0, -15), the profile stays at z = 0 (still nearer
    the bottom corner than the top one). The fit isn't clear (a residual of about 0.43 x 15 beside
    the ring's size of 18), so the names path runs: the lines' names are in the stored order and
    the start goes to line 0's start, but no frame of the profile carries the stored start
    (0, 0, 0) there. Every reference stays, on the taller ring."""

    def edit(self, doc):
        self.lower(-15)


class RingProfileStretchedAndLowered(LoweredRing):
    """The profile stretched in sketch y (B from 2 to 3, about its centre, IDs kept) and the bottom
    line moved from z = 0 to z = -4, in one recompute; nothing turns. The stretch turns the
    profile's geometry frame (its x axis points at the first vertex: atan(3/2) against atan(1)),
    so the fit isn't read and the names path runs; the placement frame is unmoved and doesn't
    carry the stored start to the lowered corner. Every reference stays, on the taller ring and
    the deeper tube."""

    AXES = ("M3", "E1", "E2")

    def edit(self, doc):
        self.stretchProfileY(1.5)
        self.lower(-4)


class RingTurnedAndLowered(LoweredRing):
    """The bottom line moved from z = 0 to z = -4 and the whole model turned 120 degrees about Z,
    in one recompute (a turn with another edit, no redraw). Every reference follows the turn, on
    the taller ring."""

    AXES = ("M3", "E7", "E2")

    def edit(self, doc):
        self.lower(-4)
        self.turnModel()


class RingOffAxisTurnedAndWidened(LoweredRing):
    """Control for the frame check's tolerance at other sizes: the ring and the profile 40 off the
    turn's axis (x = 40 to 70), the right line moved out to x = 74 and the whole model turned 120
    degrees about the global Z axis, in one recompute. The start corner moves 69 with the turn
    (scaled: 4.2 m at 4 m), carried there by the profile's placement frame. Every reference
    follows the turn, on the wider ring."""

    AXES = ("M3", "E7", "E2", "X4")
    SIZE = 80
    offX = 40

    def edit(self, doc):
        self.widen(34)
        self.turnModel()


class RingProfileLinesCycledAndLowered(LoweredRing):
    """The profile's four lines each take the next one's place (IDs kept; the square is the same,
    its first line another side: a reparameterisation of the profile) and the bottom line moved
    from z = 0 to z = -4, in one recompute; nothing turns. The profile's geometry frame (its x
    axis towards the first vertex) turns a quarter turn with the reparameterisation alone. Every
    reference stays, on the taller ring."""

    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        g = self.profile.Geometry
        ends = [(V(l.StartPoint), V(l.EndPoint)) for l in g]
        for i, line in enumerate(g):
            line.StartPoint = V(1e3 + 10 * i, 0, 0)
            line.EndPoint = V(1e3 + 10 * i, 5, 0)
        for i, line in enumerate(g):
            s, e = ends[(i + 1) % len(g)]
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        self.lower(-4)


class RingTurnedLineReversedAndWidened(LoweredRing):
    """The ring's left line drawn the other way (its ID kept, a reparameterisation), the right line
    moved out to x = 34 and the whole model turned 120 degrees about Z, in one recompute (the names
    path, with the lines' order read the other way round). Every reference follows the turn, on
    the wider ring."""

    AXES = ("M3", "E7", "E2", "E3")

    def edit(self, doc):
        self.widen(34)
        g = self.spine.Geometry
        start, end = V(g[0].StartPoint), V(g[0].EndPoint)
        g[0].StartPoint = V(1e3, 0, 0)
        g[0].EndPoint = start
        g[0].StartPoint = end
        self.spine.Geometry = g
        self.turnModel()
