# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6l (fork PR 383 at c29953fd8d: a closed spine whose profile frame turned stops).
The stop is taken only where the stored loop isn't in place in the body. These cases turn the whole
model (spine sketch and profile together, a rigid motion) by a symmetry of the ring about the ring's
own normal (the Y axis through its centre), so the ring lies on itself in the body and the body's
read is in place: no frame check. Ring on the XZ plane (sketch x = X, sketch y = Z), line i =
P_i -> P_i+1, a 2a x 2a square profile on the XY plane at P_0 = the origin, "Right corner". A datum
plane on each leg's outer face and a datum point on the start corner's outer vertex. A rigid motion
of everything: every reference follows the turn (the expectation is the turned element)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, X, Y, Z, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector


class Rigid(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E7", "E2")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6l"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    half = 2
    verts0 = ((0, 0), (0, 20), (30, 20), (30, 0))  # unscaled, line i = P_i -> P_i+1
    pivot = (15, 0, 10)  # unscaled, the ring's centre
    axis = Y
    degrees = 0
    verts = None
    REFS = ("leg0", "leg1", "leg2", "leg3", "start_pt")

    A = property(lambda self: self.s(self.half))

    def P(self):
        if self.verts is None:
            self.verts = [tuple(self.s(c) for c in p) for p in self.verts0]
        return self.verts

    def T(self):
        rot = App.Rotation(self.axis, self.degrees)
        c = V(*(self.s(v) for v in self.pivot))
        return App.Placement(c - rot.multVec(c), rot)

    def at(self, x, y, z):
        return self.T().multVec(V(x, y, z))

    def along(self, d):
        return self.T().Rotation.multVec(d)

    def legFace(self, i):
        def predicate():
            P = self.P()
            n = len(P)
            (x0, z0), (x1, z1) = P[i % n], P[(i + 1) % n]
            dx, dz = x1 - x0, z1 - z0
            L = math.hypot(dx, dz)
            nx, nz = -dz / L, dx / L
            mx, mz = (x0 + x1) / 2 + nx * self.A, (z0 + z1) / 2 + nz * self.A
            return face("plane", normal=self.along(V(nx, 0, nz)), contains=self.at(mx, 0, mz))

        return predicate

    def startPoint(self):
        a = self.A
        return vertex(self.at(-a, -a, -a))

    def spinePlacement(self):
        return self.T().multiply(App.Placement(V(), App.Rotation(X, 90)))

    def profilePlacement(self):
        return self.T()

    def build(self, doc):
        body = m.body(doc)
        P = self.P()
        self.spine = m.sketch(doc, "Spine", m.polygon(P), body, placement=self.spinePlacement())
        a = self.A
        self.profile = m.sketch(
            doc, "Square", m.rectangle(-a, -a, a, a), body, placement=self.profilePlacement()
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.spine, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
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
            else:
                predicate = self.startPoint
                obj = body.newObject("PartDesign::Point", name)
                obj.MapMode = "Vertex"
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def redrawAll(self):
        """Every line drawn anew at its own sketch place (new IDs)."""
        P = self.P()
        n = len(P)
        g = self.spine.Geometry
        for i in range(n):
            p, q = P[i], P[(i + 1) % n]
            g[i] = Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0))
        self.spine.Geometry = g

    def turn(self, degrees):
        self.degrees = degrees
        self.spine.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()


class Square(Rigid):
    abstract = True
    verts0 = ((0, 0), (0, 20), (20, 20), (20, 0))
    pivot = (10, 0, 10)


class SquareTurned90AboutNormal(Square):
    """The whole model turned 90 degrees about the ring's normal through its centre: the ring lies on
    itself in the body, each line at the next place, the profile at the next corner."""

    def edit(self, doc):
        self.turn(90)


class SquareTurned90AboutNormalAllRedrawn(Square):
    """As above, and every line drawn anew at its own sketch place, in the same recompute."""

    def edit(self, doc):
        self.redrawAll()
        self.turn(90)


class RectTurned180AboutNormal(Rigid):
    """The 30 x 20 ring and its profile turned 180 degrees about the ring's normal through its
    centre (a true rotation in the ring's plane): the ring lies on itself in the body."""

    def edit(self, doc):
        self.turn(180)


class RectTurned180AboutNormalAllRedrawn(Rigid):
    """As above, and every line drawn anew at its own sketch place, in the same recompute."""

    def edit(self, doc):
        self.redrawAll()
        self.turn(180)


class RectTurned180AboutVerticalAllRedrawn(Rigid):
    """The model turned 180 degrees about the vertical axis through the ring's centre (the ring
    mirrored onto itself in its plane, `RingTurned180AboutCentre`), every line drawn anew."""

    axis = Z

    def edit(self, doc):
        self.redrawAll()
        self.turn(180)


class SquareTurned90AboutNormalControlOff(Square):
    """Control: turned 90 degrees about the ring's normal through a point off the ring's centre
    (the ring not on itself): the frame check stops the pipe (accepted, decision 195's bound)."""

    pivot = (3, 0, 4)

    def edit(self, doc):
        self.turn(90)


class RepickedAndTurnedNearCentre(Rigid):
    """In one recompute: the spine re-picked as its four edges listed (the same input as the whole
    sketch, so its own record is read) and the whole model
    turned 180 degrees about the ring's normal through (15.5, 0, 10.5), just off the ring's centre:
    the turned ring lies 1.4 mm from itself, its top right corner next to the stored start."""

    pivot = (15.5, 0, 10.5)

    def edit(self, doc):
        doc.Pipe.Spine = (self.spine, ["Edge1", "Edge2", "Edge3", "Edge4"])
        self.turn(180)


class RepickedAndTurnedOff(Rigid):
    """In one recompute: the spine re-picked as its four edges listed and the whole model turned
    37.7 degrees about the vertical axis through (100, 40, 70)."""

    pivot = (100, 40, 70)
    axis = Z

    def edit(self, doc):
        doc.Pipe.Spine = (self.spine, ["Edge1", "Edge2", "Edge3", "Edge4"])
        self.turn(37.7)


class RepickedOnly(Rigid):
    """Control: the spine re-picked as its four edges listed, nothing moved."""

    def edit(self, doc):
        doc.Pipe.Spine = (self.spine, ["Edge1", "Edge2", "Edge3", "Edge4"])


class BodyTurned(Rigid):
    """Control: the Body's own placement turned 90 degrees about Y and moved; the features keep
    their placements in the body (the expectations are in the body's frame, unchanged)."""

    def edit(self, doc):
        doc.Body.Placement = App.Placement(V(7, -3, 5), App.Rotation(Y, 90))


class SpineCopyTurned(Rigid):
    """The spine relinked to an equal copy sketch (another object) whose placement, with the
    profile's, is turned 90 degrees about the vertical axis through (100, 40, 70) in the same
    recompute: no record of the copy; the pipe decides as a new one."""

    pivot = (100, 40, 70)
    axis = Z

    def edit(self, doc):
        P = self.P()
        self.degrees = 90
        copy = m.sketch(doc, "Spine2", m.polygon(P), doc.Body, placement=self.spinePlacement())
        doc.Pipe.Spine = (copy, [])
        self.spine.Visibility = False
        self.profile.Placement = self.profilePlacement()
