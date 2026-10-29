# SPDX-License-Identifier: LGPL-2.1-or-later
"""The pre-push review of fork PR 383 round 6 (class B, ops#469): decision 171's bound on the
body-read fit, attacked.

The ring of K4b as in `pipe_closed_r6.py` (copied: a case imports only harness and models): a
closed rectangle of four lines on the XZ plane, (0, 0) -> (0, H) -> (W, H) -> (W, 0), W = 30, H = 20
(sketch x = global X, sketch y = global Z), a square profile 2A x 2B (normal Z, along the left leg)
at the bottom left corner, "Right corner".

Two attacks:
- Slid: the profile slid up the left leg past its middle (to z = 14) before the references are
  made: the stored start stays at the bottom left corner (round 1's rule), where the shell's start
  section, and the profile's names, are. An edit the fit doesn't pair clearly (decision 171) then
  takes the start "at the profile", the top left corner: the profile's names go there.
- Turned by the loop's own symmetry: the whole model turned in the ring's plane about the bottom
  left corner by 180 degrees (a rectangle) or 90 degrees (a square), with the right leg moved out
  in the same recompute. No stored frame holds; read in the body, the translation fit is clear
  (the turned loop is a translated copy of the stored one from the opposite or next corner), so
  the start goes to that corner quietly, away from the profile."""

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


class Ring6(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E7")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6"
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
    TURN_AXIS = Z
    TURN_ANGLE = 120
    turned = False
    width = 30
    height = 20
    halfX = 2
    halfY = 2
    slide = 0  # the profile's place on the left leg (global z, unscaled)

    @property
    def W(self):
        return self.s(self.width)

    @property
    def H(self):
        return self.s(self.height)

    @property
    def A(self):
        return self.s(self.halfX)

    @property
    def B(self):
        return self.s(self.halfY)

    def corners(self):
        return [(0, 0), (0, self.H), (self.W, self.H), (self.W, 0)]

    def rot(self):
        return App.Rotation(self.TURN_AXIS, self.TURN_ANGLE if self.turned else 0)

    def at(self, x, y, z):
        return self.rot().multVec(V(x, y, z))

    def along(self, d):
        return self.rot().multVec(d)

    def leftOuter(self):
        return face("plane", normal=self.along(-X), contains=self.at(-self.A, 0, self.H / 2))

    def topOuter(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.H + self.A))

    def bottomInner(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.A))

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
        return App.Placement(V(), self.rot().multiply(App.Rotation(X, 90)))

    def profilePlacement(self):
        return App.Placement(self.at(0, 0, self.s(self.slide)), self.rot())

    def place(self):
        self.spine.Placement = self.spinePlacement()
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = self.profilePlacement()
        else:
            self.profile.Placement = self.profilePlacement()

    def profileLink(self, doc):
        return self.profile

    def beforeRefs(self, doc):
        pass

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
        self.beforeRefs(doc)
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
        w = self.s(width)
        h = self.H
        g = self.spine.Geometry
        g[1].EndPoint = V(w, h, 0)
        g[2].StartPoint, g[2].EndPoint = V(w, h, 0), V(w, 0, 0)
        g[3].StartPoint = V(w, 0, 0)
        self.spine.Geometry = g
        self.width = width


# Slid: the profile moved up the left leg past its middle before the references are made; the
# stored start stays at the bottom left corner (round 1). Then an edit the fit doesn't pair clearly.
class RingSlid(Ring6):
    abstract = True

    def beforeRefs(self, doc):
        self.slide = 14
        self.place()
        doc.recompute()
        if not self.pipe.isValid():
            raise RuntimeError(f"the pipe is invalid after the slide: {self.pipe.getStatusString()}")


class RingSlidThenWidenedFar(RingSlid):
    """The profile slid up the left leg to z = 14 (the solid unchanged), the references made; then
    the ring's right line moves from x = 30 to x = 50 (no turn: RingWidenedFar's edit). Every
    reference stays, on the wider ring."""

    AXES = ("M3", "E2")

    def edit(self, doc):
        self.widen(50)


class RingSlidThenTurnedAndWidened(RingSlid):
    """The profile slid up the left leg to z = 14, the references made; then the right line moves
    out to x = 34 and the whole model turns 120 degrees about Z, in one recompute
    (RingTurnedAndWidened's edit). Every reference follows the turn, on the wider ring."""

    AXES = ("M3", "E7", "E2")

    def edit(self, doc):
        self.widen(34)
        self.turned = True
        self.place()


class RingSlidThenTurned(RingSlid):
    """Control: the profile slid up the left leg to z = 14, the references made; then the whole
    model turns 120 degrees about Z (the profile's placement frame holds). Every reference follows
    the turn."""

    AXES = ("M3", "E7")

    def edit(self, doc):
        self.turned = True
        self.place()


class RingSlidThenWidened(RingSlid):
    """Control: the profile slid up the left leg to z = 14, the references made; then the right line
    moves out to x = 34 (the fit is clear). Every reference stays."""

    AXES = ("M3", "E2")

    def edit(self, doc):
        self.widen(34)


def xyPlane(body):
    return [
        f for f in body.Origin.OriginFeatures if "XY_Plane" in (getattr(f, "Role", ""), f.Name)
    ][0]


# The profile a face of a feature (pipe_closed_r6's RingTurnedFaceProfileStretched): the square
# sketch attached to the XY plane through its offset, padded 1 down, the pipe sweeping the Pad's top
# face; slid up the left leg through the offset.
class RingSlidFace(RingSlid):
    abstract = True

    def profileLink(self, doc):
        self.profile.AttachmentSupport = [(xyPlane(self.body), "")]
        self.profile.MapMode = "FlatFace"
        self.profile.AttachmentOffset = self.profilePlacement()
        pad = m.pad(self.body, self.profile, self.s(1))
        pad.Reversed = True
        self.pad = pad
        doc.recompute()
        top = [
            f"Face{i}"
            for i, f in enumerate(pad.Shape.Faces, 1)
            if abs(f.CenterOfMass.z) < 1e-6 and abs(f.normalAt(0, 0).z) > 0.99
        ]
        return (pad, top)

    def beforeRefs(self, doc):
        RingSlid.beforeRefs(self, doc)
        top = [
            f"Face{i}"
            for i, f in enumerate(self.pad.Shape.Faces, 1)
            if abs(f.CenterOfMass.z - self.s(self.slide)) < 1e-6 and abs(f.normalAt(0, 0).z) > 0.99
        ]
        if len(top) != 1 or self.pipe.Profile[1] != top:
            raise RuntimeError(f"the slid face profile is not the Pad's top face: {top}")

    def stretchProfileY(self, factor):
        g = self.profile.Geometry
        for line in g:
            s, e = line.StartPoint, line.EndPoint
            line.StartPoint, line.EndPoint = V(s.x, s.y * factor, 0), V(e.x, e.y * factor, 0)
        self.profile.Geometry = g
        self.halfY *= factor


class RingSlidThenTurnedFaceProfileWidened(RingSlidFace):
    """The face profile slid up the left leg to z = 14, the references made; then the ring's right
    line moves out to x = 34 and the whole model turns 120 degrees about Z, in one recompute
    (pipe_closed_r6's RingTurnedFaceProfileWidened after a slide). Every reference follows the
    turn, on the wider ring."""

    AXES = ("M3", "E7", "E2")

    def edit(self, doc):
        self.widen(34)
        self.turned = True
        self.place()


class RingSlidThenTurnedFaceProfileStretched(RingSlidFace):
    """The face profile slid up the left leg to z = 14, the references made; then the square is
    stretched in sketch y (B from 2 to 3) and the whole model turns 120 degrees about Z, in one
    recompute. Every reference follows the turn, on the deeper tube."""

    AXES = ("M3", "E7", "E1")

    def edit(self, doc):
        self.stretchProfileY(1.5)
        self.turned = True
        self.place()


class RingSlidThenFaceProfileWidenedFar(RingSlidFace):
    """The face profile slid up the left leg to z = 14, the references made; then the ring's right
    line moves from x = 30 to x = 50 (no turn). Every reference stays."""

    AXES = ("M3", "E2")

    def edit(self, doc):
        self.widen(50)


# Turned by the loop's own symmetry, about its corner in its plane, with a leg moved too.
class RingTurned180AboutCornerAndWidened(Ring6):
    """The whole model (the ring's and the profile's placements) turns 180 degrees about the
    ring's normal (Y) through the bottom left corner, where the profile is, and the ring's right
    line moves out to x = 34, in one recompute. The solid is a translated, wider copy; the profile
    stays at the turned bottom left corner. Every reference follows the turn."""

    AXES = ("M3", "E7", "E2")
    TURN_AXIS = Y
    TURN_ANGLE = 180

    def edit(self, doc):
        self.widen(34)
        self.turned = True
        self.place()


class RingTurned180AboutCorner(RingTurned180AboutCornerAndWidened):
    """Control: the turn of RingTurned180AboutCornerAndWidened alone (the placement frame holds)."""

    AXES = ("M3", "E7")

    def edit(self, doc):
        self.turned = True
        self.place()


class SquareRingTurned90AboutCornerAndWidened(Ring6):
    """A square ring (W = H = 20). The whole model turns 90 degrees about the ring's normal (Y)
    through the bottom left corner, where the profile is, and the ring's right line moves out to
    x = 22, in one recompute. Every reference follows the turn."""

    AXES = ("M3", "E7", "E2")
    TURN_AXIS = Y
    TURN_ANGLE = 90
    width = 20

    def edit(self, doc):
        self.widen(22)
        self.turned = True
        self.place()
