# SPDX-License-Identifier: LGPL-2.1-or-later
"""The post-push review of fork PR 383 round 5 (class B, ops#469), ported for round 6: a closed
spine turned while something else changes in the same recompute (decision 171).

The ring of K4b as in `pipe_closed_r5.py` (copied: a case imports only harness and models): a
closed rectangle of four lines on the XZ plane, (0, 0) -> (0, 20) -> (W, 20) -> (W, 0), W = 30
(sketch x = global X, sketch y = global Z), a square profile 2A x 2B (A in sketch x, B in sketch y)
at the bottom left corner, "Right corner". The whole model turns 120 degrees about Z.

The finds (T-A): the turn with a ring line moved (`RingTurnedFaceProfileWidened`,
`RingTurnedAndWidened`) or a face profile stretched (`RingTurnedFaceProfileStretched`) puts the ring
in place in no stored frame. Read in the body, the translation fit picked the bottom right corner
as the start, and the profile's names at the start went with it (`point_bottom_left` wrong,
silently; integration right). The fit now picks quietly only where it is clear (its best residual
small beside the ring's size and clearly below the next start's); else the start is taken at the
profile, as a new pipe's, with a warning, and the lines' names are checked place by place from it.

Controls: `RingTurnedProfileStretched` (the placement frame holds), `RingWidened` (no turn, a leg
moved by 4: the fit is clear), `RingWidenedFar` (no turn, a leg moved by 20: not clear, the start
at the profile, the same one), `RingTurnedRedrawnAndWidened` (the lines redrawn from the next
corner as the model turns and widens: every leg's line came from another place, renamed, loud)."""

import FreeCAD as App
import Part

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


def xyPlane(body):
    return [
        f for f in body.Origin.OriginFeatures if "XY_Plane" in (getattr(f, "Role", ""), f.Name)
    ][0]


class PostRing(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E7")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r5"
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
    halfX = 2
    halfY = 2

    @property
    def W(self):
        return self.s(self.width)

    @property
    def H(self):
        return self.s(20)

    @property
    def A(self):
        return self.s(self.halfX)

    @property
    def B(self):
        return self.s(self.halfY)

    def corners(self):
        return [(0, 0), (0, self.H), (self.W, self.H), (self.W, 0)]

    def at(self, x, y, z):
        return App.Rotation(Z, self.turn).multVec(V(x, y, z))

    def along(self, d):
        return App.Rotation(Z, self.turn).multVec(d)

    def leftOuter(self):
        return face("plane", normal=self.along(-X), contains=self.at(-self.A, 0, self.s(10)))

    def topOuter(self):
        return face("plane", normal=Z, contains=self.at(self.W / 2, 0, self.H + self.A))

    def bottomInner(self):
        return face("plane", normal=Z, contains=self.at(self.W / 2, 0, self.A))

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
        return vertex(self.at(-self.A, -self.B, -self.A))

    def spinePlacement(self):
        return App.Placement(V(), App.Rotation(Z, self.turn).multiply(App.Rotation(X, 90)))

    def profilePlacement(self):
        return App.Placement(self.at(0, 0, 0), App.Rotation(Z, self.turn))

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        self.spine = m.sketch(doc, "Spine", m.polygon(self.corners()), body, placement=self.spinePlacement())
        a, b = self.A, self.B
        self.profile = m.sketch(doc, "Square", m.rectangle(-a, -b, a, b), body, placement=self.profilePlacement())
        link = self.profileLink(doc)
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

    def profileLink(self, doc):
        return self.profile

    def attachments(self):
        return (
            ("datum_left_outer", "PartDesign::Plane", self.leftOuter, "FlatFace"),
            ("datum_top_outer", "PartDesign::Plane", self.topOuter, "FlatFace"),
            ("sketch_bottom_inner", "Sketcher::SketchObject", self.bottomInner, "FlatFace"),
            ("point_top_right", "PartDesign::Point", self.topRight, "Vertex"),
            ("point_bottom_left", "PartDesign::Point", self.bottomLeft, "Vertex"),
        )

    def turnModel(self):
        self.turn = 120
        self.spine.Placement = self.spinePlacement()
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = self.profilePlacement()
        else:
            self.profile.Placement = self.profilePlacement()

    def stretchProfileY(self, factor):
        g = self.profile.Geometry
        for line in g:
            s, e = line.StartPoint, line.EndPoint
            line.StartPoint, line.EndPoint = V(s.x, s.y * factor, 0), V(e.x, e.y * factor, 0)
        self.profile.Geometry = g
        self.halfY *= factor


class RingTurnedAndWidened(PostRing):
    """The ring's right line moves from x = 30 to x = 34 (the top and bottom lines lengthened, IDs
    kept), and the whole model turns 120 degrees about Z, in one recompute. Every reference follows
    the turn, on the wider ring."""

    AXES = ("M3", "E7", "E2")

    def edit(self, doc):
        w = self.s(34)
        h = self.H
        g = self.spine.Geometry
        g[1].EndPoint = V(w, h, 0)
        g[2].StartPoint, g[2].EndPoint = V(w, h, 0), V(w, 0, 0)
        g[3].StartPoint = V(w, 0, 0)
        self.spine.Geometry = g
        self.width = 34
        self.turnModel()


class RingTurnedFaceProfileStretched(PostRing):
    """The profile is the top face of a Pad (1 down) of the square, whose sketch is attached to
    the XY plane through its offset. The square is stretched in sketch y (B from 2 to 3, about its
    centre, IDs kept), and the ring's placement and the sketch's offset turn 120 degrees about Z, in
    one recompute. Every reference follows the turn, on the deeper tube."""

    AXES = ("M3", "E7", "E1")

    def profileLink(self, doc):
        self.profile.AttachmentSupport = [(xyPlane(self.body), "")]
        self.profile.MapMode = "FlatFace"
        self.profile.AttachmentOffset = self.profilePlacement()
        pad = m.pad(self.body, self.profile, self.s(1))
        pad.Reversed = True
        doc.recompute()
        top = [
            f"Face{i}"
            for i, f in enumerate(pad.Shape.Faces, 1)
            if abs(f.CenterOfMass.z) < 1e-6 and abs(f.normalAt(0, 0).z) > 0.99
        ]
        return (pad, top)

    def edit(self, doc):
        self.stretchProfileY(1.5)
        self.turnModel()


class RingTurnedProfileStretched(PostRing):
    """Control: a sketch profile (unattached), stretched in sketch y (B from 2 to 3) as the whole
    model turns 120 degrees about Z. Every reference follows the turn."""

    AXES = ("M3", "E7", "E1")

    def edit(self, doc):
        self.stretchProfileY(1.5)
        self.turnModel()


class RingTurnedFaceProfileWidened(RingTurnedFaceProfileStretched):
    """The face profile of RingTurnedFaceProfileStretched, unstretched; the ring's right line moves
    out to x = 34 as the model turns 120 degrees (both frames turn; the ring is in place in none)."""

    AXES = ("M3", "E7", "E2")

    def edit(self, doc):
        RingTurnedAndWidened.edit(self, doc)


class RingTurnedFaceProfileLineReversed(RingTurnedFaceProfileStretched):
    """The face profile of RingTurnedFaceProfileStretched (unstretched). The Pad's sketch's first
    line is drawn the other way (its ID kept, a reparameterisation) as the model turns 120 degrees
    about Z, in one recompute. Every reference follows the turn."""

    AXES = ("M3", "E7", "E3")

    def edit(self, doc):
        g = self.profile.Geometry
        start, end = V(g[0].StartPoint), V(g[0].EndPoint)
        g[0].StartPoint = V(1e3, 0, 0)
        g[0].EndPoint = start
        g[0].StartPoint = end
        self.profile.Geometry = g
        self.turnModel()


class RingTurnedFaceProfileLinesCycled(RingTurnedFaceProfileStretched):
    """The face profile of RingTurnedFaceProfileStretched (unstretched). Each of the Pad's sketch's
    four lines takes the next one's place (IDs kept; the square is the same, its first line is
    another side: a reparameterisation) as the model turns 120 degrees about Z, in one recompute.
    Every reference follows the turn."""

    AXES = ("M3", "E7", "E3")

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
        self.turnModel()


class RingWidened(PostRing):
    """Control, no turn: the ring's right line moves from x = 30 to x = 34 (the top and bottom
    lines lengthened, IDs kept). Every reference stays, on the wider ring; the fit is clear."""

    AXES = ("M3", "E2")
    FOUND_BY = "pr383 round 6"

    def widen(self, width):
        w = self.s(width)
        h = self.H
        g = self.spine.Geometry
        g[1].EndPoint = V(w, h, 0)
        g[2].StartPoint, g[2].EndPoint = V(w, h, 0), V(w, 0, 0)
        g[3].StartPoint = V(w, 0, 0)
        self.spine.Geometry = g
        self.width = width

    def edit(self, doc):
        self.widen(34)


class RingWidenedFar(RingWidened):
    """Control, no turn: the ring's right line moves from x = 30 to x = 50. The fit's best
    residual is no longer small beside the ring, so the start is taken at the profile (the same
    corner), with a warning. Every reference stays."""

    def edit(self, doc):
        self.widen(50)


class RingTurnedRedrawnAndWidened(RingWidened):
    """The ring's lines redrawn from the top left corner (IDs kept: line 0 is now the top leg),
    the right line at x = 34, and the whole model turned 120 degrees about Z, in one recompute. No
    frame holds and the fit isn't clear; from the profile's start, every place's line came from
    another place and every leg is renamed: the references to the legs break (loud). By the
    lines' IDs (integration), they follow the lines to other legs, silently."""

    AXES = ("M3", "E7", "E2", "E3")

    def edit(self, doc):
        w, h = self.s(34), self.H
        points = [(0, h), (w, h), (w, 0), (0, 0)]
        g = self.spine.Geometry
        for i in range(4):
            g[i].StartPoint = V(100 + 10 * i, 100, 0)
            g[i].EndPoint = V(105 + 10 * i, 105, 0)
        for i in range(4):
            g[i].StartPoint = V(*points[i], 0)
            g[i].EndPoint = V(*points[(i + 1) % 4], 0)
        self.spine.Geometry = g
        self.width = 34
        self.turnModel()
