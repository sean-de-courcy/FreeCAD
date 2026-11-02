# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6is (fork PR 383, round 6, head 8c97de1b3d, decisions 190 and 192): with a frame of
the profile turned, a closed spine's stored start is never chosen between two orders of the lines'
names (a spine of two edges, or both orders fit the names: the pipe stops).

Aimed at the boundary of that stop and at what stays quiet beside it:
- two names left at opposite places with a frame turned for other reasons than F-A's: the whole model
  turned (`TopBottomRedrawnTurned*`), the profile's placement turned on itself with its lines turned
  back (`TopBottomRedrawnProfileReparameterised*`), the start leg itself drawn anew;
- three names found with one line drawn anew, two adjacent names (the turned frame carries the start
  and the way, the names give the order);
- a ring of 3 and of 5 lines (`Tri*`, `House*`): odd n, where two names never fit both orders.

Rings: a closed polygon of lines in the XZ plane (sketch x = global X, sketch y = global Z) drawn
clockwise from (0, 0) up the first line (along Z), a square profile 2A x 2B (A = B = 2; normal Z,
along the first line) at (0, 0), "Right corner". Each reference is a datum plane on one leg's outer
face (the plane through the line offset by A to the outside); the expectation is that leg's outer
face on the edited model, at the place the leg is."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, X, Y, Z, face, vertex
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


class TopBottomRedrawnTurned(Poly):
    """The top and bottom lines drawn anew, the right leg moved to x = 50 and the model turned
    `DEG` degrees, in one recompute: the left and right lines' names remain, at opposite places.
    Both profile frames turn with the ring (carry of the start would be one corner). Every leg stays
    at its place."""

    DEG = 120
    wide = 50

    def edit(self, doc):
        w = self.wide
        self.assign([(0, 0), (0, 20), (w, 20), (w, 0)], redraw=(1, 3))
        self.turnModel(self.DEG)


class TopBottomRedrawnTurned30(TopBottomRedrawnTurned):
    DEG = 30


class TopBottomRedrawnTurnedSmallWiden(TopBottomRedrawnTurned):
    """As the 120 degree one, right leg at x = 34 (the fit would be clear unturned)."""

    wide = 34


class TopBottomRedrawnProfileReparameterised(Poly):
    """The ring not turned; the profile's placement turned `DEG` degrees about its normal with its
    lines turned back (the square is the same), the top and bottom lines drawn anew, the right leg
    moved to x = 50: a frame of the profile turned, two names at opposite places."""

    DEG = 90
    wide = 50

    def edit(self, doc):
        w = self.wide
        self.assign([(0, 0), (0, 20), (w, 20), (w, 0)], redraw=(1, 3))
        self.reparameteriseProfile(self.DEG)


class TopBottomRedrawnProfileReparameterised180(TopBottomRedrawnProfileReparameterised):
    DEG = 180


class TopBottomRedrawnTurnedFace(TopBottomRedrawnTurned):
    """TopBottomRedrawnTurned with the profile the top face of a Pad (a stopped Pipe passes the
    Pad's shape through: ops#549's class)."""
    # The Pipe stops and passes its Pad's shape through: the point lands on the Pad's
    # vertex, which carries the profile sketch's name (ops#549, decision 193)
    ACCEPTED = {"start_pt|V2": "decision 193", "start_pt|V2s": "decision 193"}

    facePad = True


class TopBottomRedrawnProfileReparameterisedFace(TopBottomRedrawnProfileReparameterised):
    facePad = True


class LeftRightRedrawnTurned(Poly):
    """The left (start) and right lines drawn anew, the top moved up to z = 30 and the model turned
    120 degrees: the top and bottom lines' names remain, at opposite places 1 and 3."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 30), (30, 30), (30, 0)], redraw=(0, 2))
        self.turnModel(120)


class OneRedrawnTurned(Poly):
    """Only the top line drawn anew (three names found), the right leg moved to x = 50, the model
    turned 120 degrees."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (50, 20), (50, 0)], redraw=(1,))
        self.turnModel(120)


class AdjacentRedrawnTurned(Poly):
    """The top and right lines drawn anew (two names, adjacent places 0 and 3), right leg at 50,
    turned 120 degrees."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (50, 20), (50, 0)], redraw=(1, 2))
        self.turnModel(120)


class AdjacentRedrawnProfileReparameterised(Poly):
    """The top and right lines drawn anew, right leg at 50, the profile reparameterised by 90."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (50, 20), (50, 0)], redraw=(1, 2))
        self.reparameteriseProfile(90)


# ---- rings of three and five lines


class Tri(Poly):
    abstract = True
    verts0 = ((0, 0), (0, 20), (30, 10))
    REFS = ("leg0", "leg1", "leg2")


class TriTurnedWidenedOneRedrawn(Tri):
    """A triangle (0,0) (0,20) (30,10): the second line drawn anew, the apex moved to (50, 10) and
    the model turned 120 degrees in one recompute (two names left, adjacent)."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (50, 10)], redraw=(1,))
        self.turnModel(120)


class TriProfileReparameterisedWidenedOneRedrawn(Tri):
    """As above with the profile reparameterised by 90 instead of the turn."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (50, 10)], redraw=(1,))
        self.reparameteriseProfile(90)


class TriTurnedWidened(Tri):
    """Control: all names kept, the apex moved to (50, 10) and the model turned 120 degrees."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (50, 10)])
        self.turnModel(120)


class House(Poly):
    abstract = True
    verts0 = ((0, 0), (0, 20), (15, 32), (30, 20), (30, 0))
    REFS = ("leg0", "leg1", "leg2", "leg3", "leg4")


class HouseTurnedWidenedTwoRedrawn(House):
    """A house of five lines: lines 1 and 3 drawn anew (names 0, 2, 4 left), the right wall moved to
    x = 50 (and the apex to x = 25), the model turned 120 degrees."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (25, 32), (50, 20), (50, 0)], redraw=(1, 3))
        self.turnModel(120)


class HouseTurnedWidenedThreeRedrawn(House):
    """Lines 1, 2 and 3 drawn anew (names 0 and 4 left, adjacent), widened, turned 120."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (25, 32), (50, 20), (50, 0)], redraw=(1, 2, 3))
        self.turnModel(120)


class HouseReparameterisedWidenedTwoRedrawn(House):
    """Lines 1 and 3 drawn anew, widened, the profile reparameterised by 180."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (25, 32), (50, 20), (50, 0)], redraw=(1, 3))
        self.reparameteriseProfile(180)


class HouseTurnedWidened(House):
    """Control: all names kept, widened and turned 120."""

    def edit(self, doc):
        self.assign([(0, 0), (0, 20), (25, 32), (50, 20), (50, 0)])
        self.turnModel(120)


# ---- a spine of two edges listed from a sketch that holds more


class LensListed(Scenario):
    """The lens of two arcs (A = (0,0,0), C = (0,0,30), arc 0 up on x > 0, arc 1 down on x < 0, XZ
    plane) drawn with a third, unrelated line in the same sketch, the Spine listing `Edge1` and
    `Edge2` only. Profile: a 2 x 2 square in the XY plane centred on A. References: the four side
    faces of the legs (planes at y = -1 and y = 1), by datum points at their centres of mass. Edit:
    the arcs trade places (ids kept), the lens widens to b = 14 and the profile is reparameterised
    (placement turned `DEG` degrees about its normal, lines turned back), in one recompute."""

    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6is"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("right_front", "left_front", "right_back", "left_back")
    bulge = 11.51
    DEG = 90
    XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))

    def arcs(self, traded):
        h, b = self.s(30), self.s(self.bulge)
        k = -1 if traded else 1
        first = Part.ArcOfCircle(V(0, 0, 0), V(k * b, h / 2, 0), V(0, h, 0)).toBSpline()
        second = Part.ArcOfCircle(V(0, h, 0), V(-k * b, h / 2, 0), V(0, 0, 0)).toBSpline()
        return first, second

    def side(self, sign, y):
        def predicate():
            return face(
                "plane",
                normal=V(0, y, 0),
                contains=V(sign * self.s(self.bulge), y * self.s(1), self.s(15)),
            )

        return predicate

    def build(self, doc):
        body = m.body(doc)
        first, second = self.arcs(False)
        stray = Part.LineSegment(V(self.s(60), 0, 0), V(self.s(60), self.s(10), 0))
        self.path = m.sketch(doc, "Path", [first, second, stray], body, placement=self.XZ)
        one = self.s(1)
        self.profile = m.sketch(doc, "Profile", m.rectangle(-one, -one, one, one), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, ["Edge1", "Edge2"])
        pipe.Transition = "Transformed"
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        kinds = {
            "right_front": self.side(1, -1),
            "left_front": self.side(-1, -1),
            "right_back": self.side(1, 1),
            "left_back": self.side(-1, 1),
        }
        made = {}
        for name in self.REFS:
            obj = body.newObject("PartDesign::Point", name)
            obj.AttachmentSupport = [(pipe, self.names(pipe, kinds[name]()))]
            obj.MapMode = "CenterOfMass"
            made[name] = (obj, kinds[name])
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def edit(self, doc):
        back = App.Rotation(V(0, 0, 1), -self.DEG)
        g = self.profile.Geometry
        for line in g:
            s, e = back.multVec(V(line.StartPoint)), back.multVec(V(line.EndPoint))
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), self.DEG))
        self.bulge = 14
        first, second = self.arcs(True)
        g = self.path.Geometry
        for curve, new in ((g[0], first), (g[1], second)):
            curve.buildFromPolesMultsKnots(
                new.getPoles(),
                new.getMultiplicities(),
                new.getKnots(),
                new.isPeriodic(),
                new.Degree,
                new.getWeights(),
            )
        self.path.Geometry = g


class LensListedReparameterised180(LensListed):
    DEG = 180


class LensListedWidenedOnly(LensListed):
    """Control: the lens widens (arcs kept at their places), the profile kept. No frame turns."""

    def edit(self, doc):
        self.bulge = 14
        first, second = self.arcs(False)
        g = self.path.Geometry
        for curve, new in ((g[0], first), (g[1], second)):
            curve.buildFromPolesMultsKnots(
                new.getPoles(),
                new.getMultiplicities(),
                new.getKnots(),
                new.isPeriodic(),
                new.Degree,
                new.getWeights(),
            )
        self.path.Geometry = g
