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
    FOUND_BY = "review pr383-r6ks"
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
            area = sum(
                P[j][0] * P[(j + 1) % n][1] - P[(j + 1) % n][0] * P[j][1] for j in range(n)
            )
            sign = 1 if area < 0 else -1  # clockwise: the normal (-dz, dx) is outward
            nx, nz = sign * -dz / L, sign * dx / L
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
        self.spine = self.makeSpine(doc, body, P)
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

    def makeSpine(self, doc, body, P):
        return m.sketch(doc, "Spine", m.polygon(P), body, placement=self.spinePlacement())

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
    FOUND_BY = "review pr383-r6ks"
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


class Mirror(Poly):
    """The polygon mirrored about the sketch's y axis through the start corner, the profile
    reparameterised half a turn about Z (which carries the stored loop onto it). `redraw`: the lines
    drawn anew (new IDs). `ids`: "sides" line i drawn A -> the mirror of the old previous corner (each
    line keeps its side), "follow" each line drawn at its mirror image's place."""

    abstract = True
    redraw = ()
    ids = "sides"
    REFS = ("leg0", "leg1", "leg2", "leg3")

    def legFace(self, i):
        def predicate():
            P = self.P()
            n = len(P)
            (x0, z0), (x1, z1) = P[i % n], P[(i + 1) % n]
            return face(
                "plane",
                normal=self.rot().multVec(V(0, -1, 0)),
                contains=self.at((x0 + x1) / 2, -self.B, (z0 + z1) / 2),
            )

        return predicate

    def edit(self, doc):
        n = len(self.verts0)
        mir = [(-x, z) for (x, z) in self.verts0]
        order = [0] + list(range(n - 1, 0, -1)) if self.ids == "sides" else list(range(n))
        self.assign([mir[j] for j in order], redraw=self.redraw)
        self.reparameteriseProfile(180)


class Tri(Mirror):
    abstract = True
    REFS = ("leg0", "leg1", "leg2")
    verts0 = ((0, 0), (10, 30), (-16, 24))
    halfX = 1
    halfY = 1


class TriSidesReparam(Tri):
    """Control (R6J-1): mirrored, sides kept, profile reparameterised 180, nothing redrawn."""


class TriSidesReparamLines02Redrawn(Tri):
    """As the control, and the two lines whose carried places hold another line (0 and 2) drawn
    anew: every stored name that disagrees is absent from the spine."""

    redraw = (0, 2)


class TriSidesReparamAllRedrawn(Tri):
    """As the control, all three lines drawn anew."""

    redraw = (0, 1, 2)


class TriFollowReparamLine1Redrawn(Tri):
    """Mirrored with the IDs following, the profile reparameterised 180, line 1 drawn anew."""

    ids = "follow"
    redraw = (1,)


class Quad(Mirror):
    abstract = True
    verts0 = ((0, 0), (4, 22), (30, 26), (24, 2))
    halfX = 1
    halfY = 1


class QuadSidesReparam(Quad):
    """A scalene quadrilateral mirrored, sides kept, profile reparameterised 180."""


class QuadSidesReparamAllRedrawn(Quad):
    """As above, all four lines drawn anew: no stored name on the spine."""

    redraw = (0, 1, 2, 3)


class QuadFollowReparam(Quad):
    """As above, the IDs following the mirror."""

    ids = "follow"


class Quad90(Quad):
    """The quadrilateral turned 90 degrees about the start in its sketch (lines keep their IDs, each
    at its carried place), the profile reparameterised 90 to carry it."""

    def edit(self, doc):
        self.assign([(-z, x) for (x, z) in self.verts0])
        self.reparameteriseProfile(90)


class Quad90Cycled(Quad):
    """Turned 90 as above and the IDs cycled by one: the names disagree at the carried places."""

    def edit(self, doc):
        pts = [(-z, x) for (x, z) in self.verts0]
        self.assign(pts[1:] + pts[:1])
        self.reparameteriseProfile(90)


class Quad90AllRedrawn(Quad):
    """Turned 90 as above, all four lines drawn anew."""

    def edit(self, doc):
        self.assign([(-z, x) for (x, z) in self.verts0], redraw=(0, 1, 2, 3))
        self.reparameteriseProfile(90)


class RingTurnedAllRedrawn(Pivot):
    """The model turned 37.7 about (100, 40, 70), all four lines drawn anew."""

    pivot = (100, 40, 70)

    def edit(self, doc):
        self.assign(self.verts0, redraw=(0, 1, 2, 3))
        self.turnAbout(37.7)


class RingTurnedTwoRedrawn(RingTurnedAllRedrawn):
    def edit(self, doc):
        self.assign(self.verts0, redraw=(0, 2))
        self.turnAbout(37.7)


class RingTurnedCycledKept(RingTurnedAllRedrawn):
    """Turned, and the lines cycled by one with the IDs kept (line i at line i+1's place)."""

    def edit(self, doc):
        v = list(self.verts0)
        self.assign(v[1:] + v[:1])
        self.turnAbout(37.7)


class RingTurnedCycledAllRedrawn(RingTurnedAllRedrawn):
    """Turned, and the lines cycled by one and drawn anew."""

    def edit(self, doc):
        v = list(self.verts0)
        self.assign(v[1:] + v[:1], redraw=(0, 1, 2, 3))
        self.turnAbout(37.7)


class QuadFollowReparamLines02Redrawn(Quad):
    """Mirrored with the IDs following (line i at its mirror image), the profile reparameterised
    180, lines 0 and 2 drawn anew: 1 and 3 agree at their carried places, 0 and 2 are absent."""

    ids = "follow"
    redraw = (0, 2)


def arcOf(p0, pm, p1):
    """An ArcOfCircle through three points in the sketch plane (counter-clockwise from p0 to p1
    through pm, or the reverse: the one that contains pm)."""
    (x0, y0), (xm, ym), (x1, y1) = [(p.x, p.y) for p in (p0, pm, p1)]
    d = 2 * (x0 * (ym - y1) + xm * (y1 - y0) + x1 * (y0 - ym))
    ux = ((x0**2 + y0**2) * (ym - y1) + (xm**2 + ym**2) * (y1 - y0) + (x1**2 + y1**2) * (y0 - ym)) / d
    uy = ((x0**2 + y0**2) * (x1 - xm) + (xm**2 + ym**2) * (x0 - x1) + (x1**2 + y1**2) * (xm - x0)) / d
    r = math.hypot(x0 - ux, y0 - uy)
    a0, am, a1 = [math.atan2(y - uy, x - ux) for (x, y) in ((x0, y0), (xm, ym), (x1, y1))]

    def ccw(a, b):
        return (b - a) % (2 * math.pi)

    if ccw(a0, am) < ccw(a0, a1):
        first, last = a0, a0 + ccw(a0, a1)
    else:
        first, last = a1, a1 + ccw(a1, a0)
    return V(ux, uy, 0), r, first, last


class Lens(Scenario):
    """A closed spine of two arcs from A = (0, 0) to B = (30, 0): arc 0 bulging up by 8, arc 1 down
    by 14. Square profile 2 x 2 at A. Edit: mirrored about the sketch's y axis (B' = (-30, 0)), the
    profile reparameterised half a turn. `swap`: the arcs' IDs swapped (arc 0 now the lower)."""

    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E7", "E2")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6ks"
    TIER = "F"
    SIZE = 40
    SCALE = 1.0
    REFS = ("arc0_front", "arc1_front")
    swap = False
    mirrored = False
    redraw = False

    def arcs(self):
        s = self.s
        bx = -30 if self.mirrored else 30
        up = (s(bx / 2), s(8)), (s(bx), 0)
        dn = (s(bx / 2), s(-14)), (s(bx), 0)
        return up, dn

    def arcPoints(self, i):
        up, dn = self.arcs()
        if self.swap:
            up, dn = dn, up
        mid, end = (up, dn)[i]
        return V(0, 0, 0), V(mid[0], mid[1], 0), V(end[0], end[1], 0)

    def front(self, i):
        def predicate():
            # the arc's front face: plane y = -1 (the whole loop's front is one plane); the face
            # of arc i is the one whose centre of mass lies on that arc's offset
            up, dn = self.arcs()
            # arc i's middle (the arc bulges by 8 up, 14 down): the sagitta point
            if self.swap:
                up, dn = dn, up
            mid = (up, dn)[i][0]
            return face("plane", normal=V(0, -1, 0), contains=V(mid[0], -self.s(1), mid[1]))

        return predicate

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        geo = []
        for i in range(2):
            c, r, f, l = arcOf(*self.arcPoints(i))
            geo.append(Part.ArcOfCircle(Part.Circle(c, V(0, 0, 1), r), f, l))
        self.spine = m.sketch(doc, "Spine", geo, body, placement=App.Placement(V(), App.Rotation(V(1, 0, 0), 90)))
        one = self.s(1)
        self.profile = m.sketch(doc, "Square", m.rectangle(-one, -one, one, one), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.spine, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        self.pipe = pipe
        made = {}
        for name in self.REFS:
            predicate = self.front(int(name[3]))
            obj = body.newObject("PartDesign::Plane", name)
            obj.MapMode = "FlatFace"
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def edit(self, doc):
        self.mirrored = True
        g = self.spine.Geometry
        # arcs are re-created through the three points; a redraw is a new Part.Arc
        new = []
        for i in range(2):
            c, r, f, l = arcOf(*self.arcPoints(i))
            if self.redraw:
                new.append(Part.ArcOfCircle(Part.Circle(c, V(0, 0, 1), r), f, l))
            else:
                g[i].Center, g[i].Radius = c, r
                g[i].setParameterRange(f, l)
                new.append(g[i])
        self.spine.Geometry = new
        back = App.Rotation(Z, -180)
        pg = self.profile.Geometry
        for line in pg:
            s, e = back.multVec(V(line.StartPoint)), back.multVec(V(line.EndPoint))
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = pg
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(Z, 180))


class LensMirroredKeptIds(Lens):
    """Mirrored about the y axis, arcs keep their IDs and sides (arc 0 up), profile 180."""


class LensMirroredSwappedIds(Lens):
    """As above, the arcs' IDs swapped (arc 0 now the lower)."""

    swap = True


class LensMirroredSwappedRedrawn(Lens):
    """As above, both arcs drawn anew."""

    swap = True
    redraw = True


class FeatureSpine(Mirror):
    """The spine is a Part::Feature holding a wire (no sketch; its edges' names come from the shape
    alone), mirrored by a new shape with the edges in the same order, the profile reparameterised
    180."""

    abstract = True
    verts0 = ((0, 0), (4, 22), (30, 26), (24, 2))
    halfX = 1
    halfY = 1

    def wire(self, P):
        pts = [V(x, 0, z) for (x, z) in P]
        return Part.makePolygon(pts + [pts[0]])

    def makeSpine(self, doc, body, P):
        feat = doc.addObject("Part::Feature", "Spine")
        feat.Shape = self.wire(P)
        return feat

    def assign(self, verts, redraw=()):
        self.verts = [tuple(self.s(c) for c in p) for p in verts]
        self.spine.Shape = self.wire(self.P())


class FeatureSpineSidesReparam(FeatureSpine):
    """Mirrored, sides kept (the new shape's edge i is line i of Mirror's order), profile 180."""


class FeatureSpineFollowReparam(FeatureSpine):
    ids = "follow"
