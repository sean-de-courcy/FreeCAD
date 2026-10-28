# SPDX-License-Identifier: LGPL-2.1-or-later
"""The review of fork PR 383 round 4 (class B, ops#469), ported for round 5: attacks on the
per-input start records (SpineStart, EarlierSpineStarts), the shared-edge (warned) read, the frame
in the record, and the I-B7 leg rename (`PLM`).

The ring of K4b (`pipe_closed_r4.py`), scaled: a closed rectangle of four lines on the XZ plane,
(0, 0) -> (0, 20) -> (30, 20) -> (30, 0) (sketch x = global X, sketch y = global Z), a 4 x 4
square profile at the bottom left corner, "Right corner". SIZE 34 (the frame's extent).

The finds (R1): the ring and its profile turned 120 or 150 degrees about Z, with the profile
attached to the XY plane (`RingTurnedAttachedProfile`, `RingTurned150AttachedProfile`) or after a
base feature (`RingTurnedAfterABase`). Round 4 stored the pipe's frame with the record, and that
frame (positionByPrevious: the base's placement, or the profile's support's) didn't turn: the
record was read in the body, the start went to the vertex a translation fit picked (the bottom
right), and the profile's own names at the start with it, silently (`point_bottom_left`; integration
was right). The record now holds the profile's frame.
`RingTurned180InItsSketch` turns the lines in their sketch, in no stored frame: read in the body,
every leg is renamed (loud). The others are controls and the round's other attacks."""

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


class Ring(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r4"
    TIER = "F"
    SIZE = 34
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
    LISTED = False
    PROFILE_Z = 0  # the profile on the left leg at this height (unscaled)

    # geometry, scaled
    @property
    def W(self):
        return self.s(30)

    @property
    def H(self):
        return self.s(20)

    @property
    def A(self):
        return self.s(2)

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
            through=self.at(0, -self.A, self.H + self.A),
            contains=self.at(self.W / 2, -self.A, self.H + self.A),
        )

    def topRight(self):
        return vertex(self.at(self.W + self.A, -self.A, self.H + self.A))

    def bottomLeft(self):
        return vertex(self.at(-self.A, -self.A, -self.A))

    def spinePlacement(self):
        return App.Placement(V(), App.Rotation(Z, self.turn).multiply(App.Rotation(X, 90)))

    def profilePlacement(self, z=None):
        z = self.s(self.PROFILE_Z if z is None else z)
        return App.Placement(self.at(0, 0, z), App.Rotation(Z, self.turn))

    def build(self, doc):
        body = getattr(self, "_body", None) or m.body(doc)
        self.body = body
        self.spine = m.sketch(doc, "Spine", m.polygon(self.corners()), body, placement=self.spinePlacement())
        a = self.A
        self.profile = m.sketch(doc, "Square", m.rectangle(-a, -a, a, a), body, placement=self.profilePlacement())
        link = self.profileLink(doc)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = link
        pipe.Spine = (self.spine, ["Edge1", "Edge2", "Edge3", "Edge4"] if self.LISTED else [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        self.pipe = pipe
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        made = {}
        for name, kind, predicate, mode in self.attachments():
            if name not in self.REFS:
                continue
            obj = body.newObject(kind, name)
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            obj.MapMode = mode
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())
        if "fillet_top_front" in self.REFS:
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (pipe, self.names(pipe, self.topFront()))
            fillet.Radius = self.s(0.5)
            self.ref("fillet_top_front", fillet, "Base", self.topFront, Filleted(self.s(0.5)))

    def profileLink(self, doc):
        """The pipe's Profile: the square sketch"""
        return self.profile

    def attachments(self):
        return (
            ("datum_left_outer", "PartDesign::Plane", self.leftOuter, "FlatFace"),
            ("datum_top_outer", "PartDesign::Plane", self.topOuter, "FlatFace"),
            ("sketch_bottom_inner", "Sketcher::SketchObject", self.bottomInner, "FlatFace"),
            ("point_top_right", "PartDesign::Point", self.topRight, "Vertex"),
            ("point_bottom_left", "PartDesign::Point", self.bottomLeft, "Vertex"),
        )

    def swapTopAndBottom(self):
        """Lines 1 (top) and 3 (bottom) trade places, ids kept (K4b's RingLinesSwapped)."""
        g = self.spine.Geometry
        W, H = self.W, self.H
        g[1].StartPoint, g[1].EndPoint = V(3e3, 0, 0), V(3e3, 5, 0)
        g[3].StartPoint, g[3].EndPoint = V(4e3, 0, 0), V(4e3, 5, 0)
        g[1].StartPoint, g[1].EndPoint = V(W, 0, 0), V(0, 0, 0)
        g[3].StartPoint, g[3].EndPoint = V(0, H, 0), V(W, H, 0)
        self.spine.Geometry = g


# The I-B7 gap after a rename: the top and bottom lines traded (the legs renamed, PLM), then the
# right leg split in two (5 edges: nothing compared, the names follow their lines).
class RingSwappedThenRightLegSplit(Ring):
    """Step swap: lines 1 and 3 trade places. Step split: the right leg (line 2) split at its
    middle into two lines. The solid stays (one more vertex on the right leg's line, inside its
    faces' run: the right leg's faces split); every reference stays."""

    AXES = ("M3", "E2", "E4")
    steps = ("swap", "split")

    def swap(self, doc):
        self.swapTopAndBottom()

    def split(self, doc):
        g = self.spine.Geometry
        g[2].EndPoint = V(self.W, self.H / 2, 0)
        self.spine.Geometry = g
        self.spine.addGeometry(Part.LineSegment(V(self.W, self.H / 2, 0), V(self.W, 0, 0)))


# The shared-edge (warned) read: the edges listed, the profile slid past the leg's middle, then
# the top line deleted and drawn anew 2 higher and the edges listed again.
class RingListedTopRedrawnHigherAfterSlide(Ring):
    """Spine: the four edges listed. Step slide: the profile from z = 4 to z = 16 on the left
    leg. Step redraw: the top line deleted, the left and right legs lengthened to 22, a new top
    line at 22, the four edges listed again. The bottom leg and the lower corners stay: the
    references below z = 20 hold their elements."""

    AXES = ("M3", "E4", "E5")
    LISTED = True
    PROFILE_Z = 4
    steps = ("slide", "redraw")
    REFS = ("datum_left_outer", "sketch_bottom_inner", "point_bottom_left", "point_bottom_right",
            "datum_bottom_outer")

    def bottomRight(self):
        return vertex(self.at(self.W + self.A, -self.A, -self.A))

    def bottomOuter(self):
        return face("plane", normal=-Z, contains=self.at(self.W / 2, 0, -self.A))

    def attachments(self):
        return Ring.attachments(self) + (
            ("point_bottom_right", "PartDesign::Point", self.bottomRight, "Vertex"),
            ("datum_bottom_outer", "PartDesign::Plane", self.bottomOuter, "FlatFace"),
        )

    def slide(self, doc):
        self.profile.Placement = self.profilePlacement(16)

    def redraw(self, doc):
        top = self.s(22)
        self.spine.delGeometry(1)  # now: left, right, bottom
        g = self.spine.Geometry
        g[0].EndPoint = V(0, top, 0)
        g[1].StartPoint = V(self.W, top, 0)
        self.spine.Geometry = g
        self.spine.addGeometry(Part.LineSegment(V(0, top, 0), V(self.W, top, 0)))
        self.pipe.Spine = (self.spine, ["Edge1", "Edge2", "Edge3", "Edge4"])


# The frame read and the leg rename in one recompute: the whole model turned 120 degrees and
# the top and bottom lines traded.
class RingTurnedAndSwapped(Ring):
    """The whole model turns 120 degrees about Z, and lines 1 and 3 trade places in the same
    recompute. Every reference follows the turn."""

    AXES = ("M3", "E2", "E7")

    def edit(self, doc):
        self.swapTopAndBottom()
        self.turn = 120
        self.spine.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()


# Control at other sizes: K4b's RingTurned with SIZE (the frame read is exact-in-place).
class RingTurnedScaled(Ring):
    """The whole model turns 120 degrees about Z."""

    AXES = ("M3", "E7")

    def edit(self, doc):
        self.turn = 120
        self.spine.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()


# The whole model turned, the profile sketch attached to the XY plane (an offset): the pipe's
# frame is the support's and doesn't turn; the profile's does (R1).
class RingTurnedAttachedProfile(Ring):
    """The profile sketch attached to the body's XY plane with an attachment offset; the whole
    model turns 120 degrees about Z (the spine's placement, the profile's offset)."""

    AXES = ("M3", "E7")

    def build(self, doc):
        Ring.build(self, doc)
        xy = [
            f
            for f in self.body.Origin.OriginFeatures
            if "XY_Plane" in (getattr(f, "Role", ""), f.Name)
        ][0]
        self.profile.AttachmentSupport = [(xy, "")]
        self.profile.MapMode = "FlatFace"
        self.profile.AttachmentOffset = self.profilePlacement()
        doc.recompute()

    def edit(self, doc):
        self.turn = 120
        self.spine.Placement = self.spinePlacement()
        self.profile.AttachmentOffset = self.profilePlacement()


class RingTurned90AttachedProfile(RingTurnedAttachedProfile):
    """As RingTurnedAttachedProfile, turned 90 degrees."""

    TURN = 90

    def edit(self, doc):
        self.turn = self.TURN
        self.spine.Placement = self.spinePlacement()
        self.profile.AttachmentOffset = self.profilePlacement()


class RingTurned60AttachedProfile(RingTurned90AttachedProfile):
    """Turned 60 degrees."""

    TURN = 60


class RingTurned30AttachedProfile(RingTurned90AttachedProfile):
    """Turned 30 degrees."""

    TURN = 30


class RingTurned150AttachedProfile(RingTurned90AttachedProfile):
    """Turned 150 degrees."""

    TURN = 150


# The pipe's frame is its base's placement when it has a base, and doesn't turn (R1): a Pad first
# (a cylinder about Z at the origin, which the turn maps onto itself), then the pipe; the ring and
# the profile turn.
class RingTurnedAfterABase(Ring):
    """A Pad of a circle of radius 3 (scaled) at the origin on the XY plane, 3 high, first; the
    pipe fused onto it at the ring's bottom-left corner. The ring and the profile (unattached)
    turn 120 degrees about Z; the Pad maps onto itself. Every reference follows the turn."""

    AXES = ("M3", "E7")
    TURN = 120

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", [Part.Circle(V(0, 0, 0), Z, self.s(3))], body)
        pad = m.pad(body, base, self.s(3))
        doc.recompute()
        self._body = body
        Ring.build(self, doc)

    def edit(self, doc):
        self.turn = self.TURN
        self.spine.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()


# Control: the ring's and the profile's sketches attached to one LCS, which turns.
class RingTurnedOnAnLCS(Ring):
    """Both sketches attached to a local coordinate system (offsets as built); the LCS turns
    120 degrees about Z."""

    AXES = ("M3", "E7")

    def build(self, doc):
        Ring.build(self, doc)
        lcs = self.body.newObject("PartDesign::CoordinateSystem", "LCS")
        self.lcs = lcs
        for sketch, offset in ((self.spine, self.spinePlacement()), (self.profile, self.profilePlacement())):
            sketch.AttachmentSupport = [(lcs, "")]
            sketch.MapMode = "ObjectXY"
            sketch.AttachmentOffset = offset
        doc.recompute()

    def edit(self, doc):
        self.turn = 120
        self.lcs.Placement = App.Placement(V(), App.Rotation(Z, 120))


# A turn in no stored frame: the ring's lines turned in their own sketch, the profile kept. Read in
# the body, every leg's line came from another place and is renamed: loud. Integration follows the
# lines, and the seam vertex at the start goes to another corner silently (point_bottom_left).
class RingTurned180InItsSketch(Ring):
    """The ring's lines (IDs kept) moved to the loop turned 180 degrees about the bottom left
    corner in the sketch's plane (about Y); the profile kept. The references follow the turn."""

    AXES = ("M3", "E2", "E7")
    flip = False

    def at(self, x, y, z):
        return App.Rotation(Y, 180 if self.flip else 0).multVec(V(x, y, z))

    def along(self, d):
        return App.Rotation(Y, 180 if self.flip else 0).multVec(d)

    def edit(self, doc):
        g = self.spine.Geometry
        for i in range(4):
            g[i].StartPoint = V(100 + 10 * i, 100, 0)
            g[i].EndPoint = V(105 + 10 * i, 105, 0)
        self.spine.Geometry = g
        g = self.spine.Geometry
        c = [(-x, -y) for x, y in self.corners()]
        for i in range(4):
            g[i].StartPoint = V(*c[i], 0)
            g[i].EndPoint = V(*c[(i + 1) % 4], 0)
        self.spine.Geometry = g
        self.flip = True

    def topOuter(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.H + self.A))

    def bottomInner(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.A))


def xyPlane(body):
    return [
        f for f in body.Origin.OriginFeatures if "XY_Plane" in (getattr(f, "Role", ""), f.Name)
    ][0]


# The profile a face of a feature: the square sketch attached to the XY plane (an offset) and
# padded 1 down, the pipe sweeping the Pad's top face (inside the pipe's corner). The face's
# placement is the Pad's, which doesn't turn with the sketch's offset (the pre-push review of
# round 5, T1): the record is read in the frame of the profile's geometry.
class RingTurnedFaceProfile(Ring):
    """The profile is the top face of a Pad (1 down) of the square, whose sketch is attached to
    the XY plane through its offset; the ring's placement and the sketch's offset turn 120
    degrees about Z. Every reference follows the turn."""

    AXES = ("M3", "E7")
    TURN = 120

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
        self.turn = self.TURN
        self.spine.Placement = self.spinePlacement()
        self.profile.AttachmentOffset = self.profilePlacement()


class RingTurned150FaceProfile(RingTurnedFaceProfile):
    """As RingTurnedFaceProfile, turned 150 degrees."""

    TURN = 150


# The profile attached normal to the ring's left line at its bottom left corner, the ring turned
# in its own plane (its placement, about the sketch's normal): the attacher keeps the profile's y
# axis vertical, so the profile turns with the ring and half a turn more about its own normal
# (the pre-push review of round 5, T2). In no stored frame, the record is read in the body: five
# references quiet, one broken; integration breaks all six. Read in the spine's frame (tried), all
# six broke.
class RingTurnedInPlaneProfileOnRing(Ring):
    """The profile sketch attached NormalToEdge to the ring's left line (Edge1) at its bottom
    left corner; the ring's placement turns 120 degrees about the sketch's normal (global -Y)
    about that corner. Every reference follows the turn."""

    AXES = ("M3", "E7")
    TURN = 120
    spun = 0

    def at(self, x, y, z):
        return App.Rotation(-Y, self.spun).multVec(V(x, y, z))

    def along(self, d):
        return App.Rotation(-Y, self.spun).multVec(d)

    def topOuter(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.H + self.A))

    def bottomInner(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.A))

    def profileLink(self, doc):
        self.profile.AttachmentSupport = [(self.spine, "Edge1"), (self.spine, "Vertex1")]
        self.profile.MapMode = "NormalToEdge"
        doc.recompute()
        return self.profile

    def spinePlacement(self):
        return App.Placement(V(), App.Rotation(X, 90).multiply(App.Rotation(Z, self.spun)))

    def edit(self, doc):
        self.spun = self.TURN
        self.spine.Placement = self.spinePlacement()


# The profile edited in the recompute that turns the model: the frame of the profile's geometry
# (its first point and the chord to the next) changed with the edit, so the turned ring was read in
# the body (the second pre-push review of round 5, F1, F2). Integration starts at the drawn first
# line. The frame is the profile's placement for a sketch: drawn and sized as it may be.
class RingTurnedProfileResized(Ring):
    """The whole model turns 120 degrees about Z, and the profile's square grows from 4 x 4 to
    5 x 5 about its centre (its lines' IDs kept), in one recompute. Every reference follows the
    turn, on the bigger tube."""

    AXES = ("M3", "E7", "E1")
    half = 2

    @property
    def A(self):
        return self.s(self.half)

    def resize(self, factor):
        g = self.profile.Geometry
        for line in g:
            line.StartPoint, line.EndPoint = line.StartPoint * factor, line.EndPoint * factor
        self.profile.Geometry = g
        self.half *= factor

    def edit(self, doc):
        self.resize(1.25)
        self.turn = 120
        self.spine.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()


class RingTurnedOnAnLCSProfileResized(RingTurnedProfileResized):
    """As RingTurnedOnAnLCS (both sketches on one LCS, which turns 120 degrees), and the profile's
    square grows from 4 x 4 to 5 x 5 in the same recompute."""

    def build(self, doc):
        RingTurnedOnAnLCS.build(self, doc)

    def edit(self, doc):
        self.resize(1.25)
        self.turn = 120
        self.lcs.Placement = App.Placement(V(), App.Rotation(Z, 120))


class RingTurnedProfileLineReversed(Ring):
    """The whole model turns 120 degrees about Z, and the profile's first line is drawn the other
    way (its ID kept), in one recompute. The solid turns; every reference follows the turn."""

    AXES = ("M3", "E7", "E3")

    def edit(self, doc):
        g = self.profile.Geometry
        start, end = V(g[0].StartPoint), V(g[0].EndPoint)
        g[0].StartPoint = V(1e3, 0, 0)  # out of the way: the two ends can't meet
        g[0].EndPoint = start
        g[0].StartPoint = end
        self.profile.Geometry = g
        self.turn = 120
        self.spine.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()


class RingTurnedFaceProfileResized(RingTurnedFaceProfile):
    """As RingTurnedFaceProfile (the profile a Pad's top face), and the Pad's square grows from
    4 x 4 to 5 x 5 about its centre (its lines' IDs kept) in the recompute that turns the model:
    the frame is the face's plane, not its drawing."""

    AXES = ("M3", "E7", "E1")
    half = 2

    @property
    def A(self):
        return self.s(self.half)

    def edit(self, doc):
        RingTurnedProfileResized.resize(self, 1.25)
        RingTurnedFaceProfile.edit(self, doc)
