# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6ls (fork PR 383, head c29953fd8d, decision 195's literal stop). Rings of
`pipe_closed_r6js.py`'s Poly (copied: 30 x 20 rectangle in the XZ plane, 4 x 4 square profile at the
start corner (0, 0), a datum plane per leg's outer face) with datum points on the start cross-section's
mitre corners, the model turned about a pivot so that the ring lies on itself in the body (the body
read, not the turned-frame stop) or not."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    OwnOrBroken,
    Scenario,
    X,
    Y,
    Z,
    face,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector


class Poly(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E7", "E2")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6ls"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    turn = 0
    halfX = 2
    halfY = 2
    verts0 = ((0, 0), (0, 20), (30, 20), (30, 0))  # unscaled, clockwise, line i = P_i -> P_i+1
    verts = None
    facePad = False  # the profile is the top face of a Pad of the square (attached to XY)
    REFS = ("leg0", "leg1", "leg2", "leg3", "start_pt", "c_ob", "c_ot", "c_it")
    CORNERS = {
        "start_pt": (-1, -1, -1),
        "c_ob": (-1, 1, -1),
        "c_it": (1, -1, 1),
        "c_ot": (1, 1, 1),
    }

    A = property(lambda self: self.s(self.halfX))
    B = property(lambda self: self.s(self.halfY))

    def P(self):
        if self.verts is None:
            self.verts = [tuple(self.s(c) for c in p) for p in self.verts0]
        return self.verts

    axis = Z

    def rot(self):
        return App.Rotation(self.axis, self.turn)

    def at(self, x, y, z):
        return self.rot().multVec(V(x, y, z))

    def legFace(self, i):
        def predicate():
            P = self.P()
            n = len(P)
            (x0, z0), (x1, z1) = P[i % n], P[(i + 1) % n]
            dx, dz = x1 - x0, z1 - z0
            L = math.hypot(dx, dz)
            nx, nz = -dz / L, dx / L
            mx, mz = (x0 + x1) / 2 + nx * self.A, (z0 + z1) / 2 + nz * self.A
            if self.circle:
                return face(contains=self.at(mx, 0, mz))
            return face(
                "plane", normal=self.rot().multVec(V(nx, 0, nz)), contains=self.at(mx, 0, mz)
            )

        return predicate

    def startPoint(self):
        # the start corner's outer-front-bottom vertex of a rectangle ring (leg 0 up, leg n-1 back)
        return vertex(self.at(-self.A, -self.B, -self.A))

    def cornerAt(self, name):
        sx, sy, sz = self.CORNERS[name]
        return lambda: vertex(self.at(sx * self.A, sy * self.B, sz * self.A))

    def spinePlacement(self):
        return App.Placement(V(), self.rot().multiply(App.Rotation(X, 90)))

    def profilePlacement(self):
        return App.Placement(self.at(0, 0, 0), self.rot())

    circle = False

    def profileGeometry(self, a, b):
        if self.circle:
            return [Part.Circle(V(0, 0, 0), V(0, 0, 1), a)]
        return m.rectangle(-a, -b, a, b)

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        P = self.P()
        self.spine = m.sketch(doc, "Spine", m.polygon(P), body, placement=self.spinePlacement())
        a, b = self.A, self.B
        self.profile = m.sketch(
            doc, "Square", self.profileGeometry(a, b), body, placement=self.profilePlacement()
        )
        link = self.profile
        if self.facePad:
            xy = [
                f
                for f in body.Origin.OriginFeatures
                if "XY_Plane" in (getattr(f, "Role", ""), f.Name)
            ][0]
            self.profile.AttachmentSupport = [(xy, "")]
            self.profile.MapMode = "FlatFace"
            self.profile.AttachmentOffset = self.profilePlacement()
            pad = m.pad(body, self.profile, self.s(1))
            pad.Reversed = True
            doc.recompute()
            top = [
                f"Face{i}"
                for i, f in enumerate(pad.Shape.Faces, 1)
                if abs(f.CenterOfMass.z) < 1e-6 and abs(f.normalAt(0, 0).z) > 0.99
            ]
            link = (pad, top)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = link
        pipe.Spine = (self.spine, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        self.pipe = pipe
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        made = {}
        n = len(P)
        for name in self.REFS:
            if name.startswith("leg"):
                i = int(name[3:])
                if i >= n:
                    continue
                predicate = self.legFace(i)
                if self.circle:
                    obj = body.newObject("PartDesign::Point", name)
                    obj.MapMode = "CenterOfMass"
                else:
                    obj = body.newObject("PartDesign::Plane", name)
                    obj.MapMode = "FlatFace"
            elif name in self.CORNERS:
                predicate = self.cornerAt(name)
                obj = body.newObject("PartDesign::Point", name)
                obj.MapMode = "Vertex"
            else:
                continue
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    # ---- edits
    def assign(self, verts, redraw=()):
        """The polygon through `verts` (unscaled); lines keep their IDs except those in `redraw`
        (drawn anew: a new ID)."""
        self.verts = [tuple(self.s(c) for c in p) for p in verts]
        P = self.P()
        n = len(P)
        g = self.spine.Geometry
        for i in range(n):
            if i not in redraw:
                g[i].StartPoint, g[i].EndPoint = V(100 + 10 * i, 100, 0), V(105 + 10 * i, 105, 0)
        for i in range(n):
            p, q = P[i], P[(i + 1) % n]
            if i in redraw:
                g[i] = Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0))
            else:
                g[i].StartPoint, g[i].EndPoint = V(p[0], p[1], 0), V(q[0], q[1], 0)
        self.spine.Geometry = g

    def placeProfile(self, placement):
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = placement
        else:
            self.profile.Placement = placement

    def turnModel(self, degrees):
        self.turn = degrees
        self.spine.Placement = self.spinePlacement()
        self.placeProfile(self.profilePlacement())

    def reparameteriseProfile(self, degrees):
        """The profile's placement turned `degrees` about its normal, its lines turned back: the
        same square in the body (the placement frame turns, the geometry frame doesn't)."""
        back = App.Rotation(Z, -degrees)
        g = self.profile.Geometry
        for line in g:
            s, e = back.multVec(V(line.StartPoint)), back.multVec(V(line.EndPoint))
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        self.placeProfile(App.Placement(self.at(0, 0, 0), App.Rotation(Z, degrees + self.turn)))


# ---- the rectangle ring: two names at opposite places, a frame turned for another reason


class Pivot(Poly):
    abstract = True
    FOUND_BY = "review pr383-r6ls"
    pivot = (0, 0, 0)  # unscaled world point the model turns about
    offset = None

    def off(self):
        return V(0, 0, 0) if self.offset is None else self.offset

    def at(self, x, y, z):
        return self.rot().multVec(V(x, y, z)) + self.off()

    def spinePlacement(self):
        return App.Placement(self.off(), self.rot().multiply(App.Rotation(V(1, 0, 0), 90)))

    def profilePlacement(self):
        return App.Placement(self.off(), self.rot())

    def turnAbout(self, degrees):
        c = V(*(self.s(v) for v in self.pivot))
        self.turn, self.offset = degrees, None
        self.offset = c - self.rot().multVec(c)
        self.spine.Placement = self.spinePlacement()
        self.placeProfile(self.profilePlacement())



# ---- the ring lies on itself in the body after the model turned (the body read)


class Rect180Z(Pivot):
    """Rectangle ring, the model turned 180 degrees about the vertical axis through the ring's centre
    (15, 0, 10): the profile at the other bottom corner. Every reference follows the turn."""

    pivot = (15, 0, 10)

    def edit(self, doc):
        self.turnAbout(180)


class Rect180Y(Pivot):
    """As above about the axis through the centre normal to the ring's plane: the profile at the
    diagonally opposite (top right) corner."""

    pivot = (15, 0, 10)
    axis = Y

    def edit(self, doc):
        self.turnAbout(180)


class Square90Y(Pivot):
    """Square ring 20 x 20, the model turned 90 degrees about the axis through its centre normal to its
    plane: the ring lies on itself, the profile at the next corner."""

    verts0 = ((0, 0), (0, 20), (20, 20), (20, 0))
    pivot = (10, 0, 10)
    axis = Y

    def edit(self, doc):
        self.turnAbout(90)


class Square270Y(Square90Y):
    def edit(self, doc):
        self.turnAbout(270)


class Square180Y(Square90Y):
    def edit(self, doc):
        self.turnAbout(180)


class SpineTurned180AboutStartY(Pivot):
    """Only the spine's sketch turned 180 degrees about the axis through the start corner A normal to
    its plane (the rectangle is now the translate of the old one by (-30, -20), A is its far corner);
    the profile stays at A. Legs follow their lines."""

    axis = Y
    REFS = ("leg0", "leg1", "leg2", "leg3")

    def profilePlacement(self):
        return App.Placement(V(), App.Rotation())

    def edit(self, doc):
        self.turn = 180
        self.spine.Placement = self.spinePlacement()


# ---- a round profile: the frames' x axis is the circle's seam


class CircleFaceRing(Pivot):
    """A circle profile (radius 2) that is a Pad's top face (the Pad's sketch attached to XY, its offset
    turned), the rectangle ring and the model turned 120 degrees about Z through the start A, which
    is the circle's axis. The Pad's placement doesn't turn; the face's circle is its own image.
    The legs follow the turn."""

    facePad = True
    circle = True
    REFS = ("leg0", "leg1", "leg2", "leg3")

    def edit(self, doc):
        self.turnAbout(120)


class CircleSketchRing(CircleFaceRing):
    """The same with the profile the sketch itself."""

    facePad = False


class CircleFaceRingWidened(CircleFaceRing):
    """As CircleFaceRing, and the right leg moved to x = 36 in the same recompute."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (36, 20), (36, 0)])
        self.turnAbout(120)


class SquareFaceRing(Pivot):
    """The same with a square face profile (the control)."""

    facePad = True
    REFS = ("leg0", "leg1", "leg2", "leg3")

    def edit(self, doc):
        self.turnAbout(120)


# ---- a spine of two edges (two half circles) lying on itself after the model turned


class TwoArcRing(Pivot):
    """Two half circles of radius 10 about (10, 10) in the sketch (the XZ plane): arc 0 over the top from
    (20, 10) to (0, 10), arc 1 under it back. A 4 x 4 square profile at the left junction (0, 0, 10),
    normal to the spine there. Datum points at the centres of mass of each arc's four walls (outer and
    inner cylinder, front and back flat annulus). The model turned 180 degrees about the axis through
    the ring's centre (10, 0, 10) normal to its plane: the ring lies on itself, the arcs trade places,
    the profile is at the right junction. Every wall follows its arc."""

    axis = Y
    pivot = (10, 0, 10)
    REFS = tuple(f"arc{a}_{w}" for a in (0, 1) for w in ("outer", "inner", "front", "back"))

    def P(self):
        return [(0, 0)]

    def profilePlacement(self):
        return App.Placement(self.at(0, 0, self.s(10)), self.rot())

    def wall(self, arc, which):
        def predicate():
            s, r, a = self.s, self.s(10), self.A
            up = 1 if arc == 0 else -1
            c = self.at(s(10), 0, s(10) + up * r)  # the arc's top (arc 0) or bottom (arc 1)
            if which == "outer":
                return face(contains=self.at(s(10), 0, s(10) + up * (r + a)))
            if which == "inner":
                return face(contains=self.at(s(10), 0, s(10) + up * (r - a)))
            y = -a if which == "front" else a
            return face("plane", contains=self.at(s(10), y, s(10) + up * r))

        return predicate

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        s = self.s
        circle = Part.Circle(V(s(10), s(10), 0), V(0, 0, 1), s(10))
        arcs = [
            Part.ArcOfCircle(circle, 0, math.pi),
            Part.ArcOfCircle(circle, math.pi, 2 * math.pi),
        ]
        self.spine = m.sketch(doc, "Spine", arcs, body, placement=self.spinePlacement())
        a = self.A
        self.profile = m.sketch(
            doc, "Square", m.rectangle(-a, -a, a, a), body, placement=self.profilePlacement()
        )
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
        for name in self.REFS:
            arc, which = int(name[3]), name[5:]
            predicate = self.wall(arc, which)
            obj = body.newObject("PartDesign::Point", name)
            obj.MapMode = "CenterOfMass"
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def edit(self, doc):
        self.turnAbout(180)


# ---- the model moved without a turn (the frame read that stays), composed with a redraw


class Moved(Pivot):
    """Rectangle ring and its profile translated by (40, 0, 25) (unscaled), nothing else: read in the
    stored frame, every reference follows."""

    shift = (40, 0, 25)

    def translate(self):
        self.turn = 0
        self.offset = V(*(self.s(v) for v in self.shift))
        self.spine.Placement = self.spinePlacement()
        self.placeProfile(self.profilePlacement())

    def edit(self, doc):
        self.translate()


class MovedAllRedrawn(Moved):
    """Translated, and all four lines drawn anew (same places) in the same recompute: no stored name
    is left. Integration: lines drawn anew break their legs or are guessed."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (30, 20), (30, 0)], redraw=range(4))
        self.translate()


class MovedCycled(Moved):
    """Translated, and the lines cycled (IDs kept: line i takes line i + 1's places) in one recompute."""

    edited = False
    first = None

    def legFace(self, i):
        base = Poly.legFace(self, i)

        def predicate():
            if self.first is None:
                self.first = list(self.P())
            if not self.edited:
                return base()
            now, self.verts = self.verts, self.first
            try:
                return OwnOrBroken(base())
            finally:
                self.verts = now

        return predicate

    def edit(self, doc):
        self.edited = True
        self.assign([(0, 20), (30, 20), (30, 0), (0, 0)])
        self.translate()


class MovedAndWidened(Moved):
    """Translated and the right leg moved to x = 36."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (36, 20), (36, 0)])
        self.translate()


class MovedAndProfileFlipped(Moved):
    """Translated, and the profile's lines drawn the other way round (the profile's first line
    reversed; the shape is the same square): the geometry frame's normal and first point change."""

    def edit(self, doc):
        g = self.profile.Geometry
        s, e = V(g[0].StartPoint), V(g[0].EndPoint)
        g[0].StartPoint, g[0].EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
        g[0].StartPoint, g[0].EndPoint = e, s
        self.profile.Geometry = g
        self.translate()


class Rect180ThenWidened(Pivot):
    """Rectangle ring: the model turned 180 degrees about the vertical axis through its centre (the ring
    lies on itself, the profile at the other bottom corner), then in the next recompute the right leg
    (line 2's x) moved to 36. The start the body read kept stays at the old corner, away from the profile."""

    pivot = (15, 0, 10)
    steps = ("doTurn", "doWiden")

    def doTurn(self, doc):
        self.turnAbout(180)

    def doWiden(self, doc):
        self.assign([(0, 0), (0, 20), (36, 20), (36, 0)])


class Rect180YThenWidened(Rect180ThenWidened):
    axis = Y


class Square90ThenRaised(Pivot):
    """Square ring 20 x 20 turned 90 degrees (lies on itself), then its top leg raised (line 1 and 2's
    z to 26)."""

    verts0 = ((0, 0), (0, 20), (20, 20), (20, 0))
    pivot = (10, 0, 10)
    axis = Y
    steps = ("doTurn", "doRaise")

    def doTurn(self, doc):
        self.turnAbout(90)

    def doRaise(self, doc):
        self.assign([(0, 0), (0, 26), (20, 26), (20, 0)])
