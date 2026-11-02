# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6js (fork PR 383, head 64d0fc4ebf, decision 195). Rings of `pipe_closed_r6is.py`'s
Poly (copied here: a case imports only the harness and the models; 30 x 20, square 4 x 4 profile at
the start corner, a datum plane per leg's outer face, a datum point on the start corner), the model
turned about a pivot and the lines turned in their sketch."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    OwnOrBroken,
    Scenario,
    X,
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
    FOUND_BY = "review pr383-r6is"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    turn = 0
    halfX = 2
    halfY = 2
    verts0 = ((0, 0), (0, 20), (30, 20), (30, 0))  # unscaled, clockwise, line i = P_i -> P_i+1
    verts = None
    facePad = False  # the profile is the top face of a Pad of the square (attached to XY)
    REFS = ("leg0", "leg1", "leg2", "leg3", "start_pt")

    A = property(lambda self: self.s(self.halfX))
    B = property(lambda self: self.s(self.halfY))

    def P(self):
        if self.verts is None:
            self.verts = [tuple(self.s(c) for c in p) for p in self.verts0]
        return self.verts

    def rot(self):
        return App.Rotation(Z, self.turn)

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
            return face(
                "plane", normal=self.rot().multVec(V(nx, 0, nz)), contains=self.at(mx, 0, mz)
            )

        return predicate

    def startPoint(self):
        # the start corner's outer-front-bottom vertex of a rectangle ring (leg 0 up, leg n-1 back)
        return vertex(self.at(-self.A, -self.B, -self.A))

    def spinePlacement(self):
        return App.Placement(V(), self.rot().multiply(App.Rotation(X, 90)))

    def profilePlacement(self):
        return App.Placement(self.at(0, 0, 0), self.rot())

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        P = self.P()
        self.spine = m.sketch(doc, "Spine", m.polygon(P), body, placement=self.spinePlacement())
        a, b = self.A, self.B
        self.profile = m.sketch(
            doc, "Square", m.rectangle(-a, -b, a, b), body, placement=self.profilePlacement()
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
                obj = body.newObject("PartDesign::Plane", name)
                obj.MapMode = "FlatFace"
            elif name == "start_pt":
                predicate = self.startPoint
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
    FOUND_BY = "review pr383-r6js"
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


class RingTurned180AboutCentre(Pivot):
    """The whole model (spine and profile) turned 180 degrees about the vertical axis through the
    ring's centre (15, 0, 10): the ring lies on itself in the body, the profile is at the other bottom
    corner, nothing else changes. Every reference follows the turn (Ring180's control, off the corner)."""

    pivot = (15, 0, 10)

    def edit(self, doc):
        self.turnAbout(180)


class RingTurnedOnlyAbout(Pivot):
    """The model alone turned 37.7 degrees about (100, 40, 70). Control."""

    pivot = (100, 40, 70)

    def edit(self, doc):
        self.turnAbout(37.7)


class RingTurnedWithNoise(RingTurnedOnlyAbout):
    """As above and the right leg nudged by 2e-6 mm (the loop is not in place within 1e-7)."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (30 + 2e-6, 20), (30 + 2e-6, 0)])
        self.turnAbout(37.7)


class RingTurnedSmall(Pivot):
    """The model turned 0.0003 degrees (5e-6 rad) and the right leg moved to x = 36."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (36, 20), (36, 0)])
        self.turnAbout(0.0003)


class RingTurnedTiny(RingTurnedSmall):
    """0.00002 degrees (3.5e-7 rad, under the threshold) and the leg moved: the body's fit reads."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (36, 20), (36, 0)])
        self.turnAbout(0.00002)


class SpineOnlyTurned(Pivot):
    """Only the spine's sketch turns 90 degrees about Z through the start; the profile is kept."""

    def edit(self, doc):
        self.turn = 90
        self.spine.Placement = self.spinePlacement()


class RingSketchTurned180Only(Poly):
    """The lines drawn half a turn about the ring's centre in their sketch, IDs kept (line i takes line
    i + 2's place), nothing else: I-B7 (`naming-invariants.md`): the reference stays on its own place or
    breaks, never follows the identity to the other place (OwnOrBroken of the place)."""

    FOUND_BY = "review pr383-r6js"
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
        self.assign([(30, 20), (30, 0), (0, 0), (0, 20)])
