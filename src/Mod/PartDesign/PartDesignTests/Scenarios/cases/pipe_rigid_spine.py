# SPDX-License-Identifier: LGPL-2.1-or-later
"""References into a closed-spine Pipe whose whole model turns as one piece (class B, ops#546): the
Pipe's rung lets it compute on the turned model, and with the rigid follow off for the beta
(decisions 237 and 239) the references into it are judged by decision 211's frame rule and 236's
guard. Each must come out right or broken, never quietly on another element (the coordinator's
ruling on ops#546's scope note, 2026-11-03; decision 150).

The ring of K4b as in `pipe_closed_r5.py` (copied: a case imports only harness and models): a
closed rectangle of four lines on the XZ plane, (0, 0) -> (0, 20) -> (30, 20) -> (30, 0) (sketch
x = global X, sketch y = global Z), a 4 x 4 square profile at the bottom left corner, "Right
corner". The references: datum planes on the left and top outer faces, a sketch on the bottom
inner face, points on the top right and bottom left corners, a fillet on the top front edge and
a linear pattern of the Pipe along that edge.

The motions, each by three routes (the two sketches' Placements, the frame moved; their
AttachmentOffsets on the XY plane, the frame stayed; an LCS both sketches are attached to):
- `Turn120`: 120 degrees about Z, nothing of the ring where an element was.
- `HalfTurnOntoItself`: half a turn about the ring's centre, normal to its plane: the ring lies on
  itself, each leg where the opposite one was (a twin where every element was).
- `SquareQuarterTurn`: the ring a 30 x 30 square, a quarter turn about its centre, normal to its
  plane: onto itself again, each leg where the next one was.
The expectations follow the motion (the Pipe's names at its moved elements); broken is loud and
allowed, wrong is a finding."""

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


class Turned(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E7")
    ISSUE = "ops#546"
    FOUND_BY = "scope ops#546"
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
        "pattern_top_front",
    )
    HEIGHT = 20
    ROUTE = "placement"  # "placement", "offset" or "lcs"
    moved = False

    # geometry, scaled
    @property
    def W(self):
        return self.s(30)

    @property
    def H(self):
        return self.s(self.HEIGHT)

    @property
    def A(self):
        return self.s(2)

    def corners(self):
        return [(0, 0), (0, self.H), (self.W, self.H), (self.W, 0)]

    def turn(self):
        """The motion's axis, angle and the point it turns about"""
        raise NotImplementedError

    def motion(self):
        """The whole model's motion after the edit, in the body (the identity before)"""
        if not self.moved:
            return App.Placement()
        axis, angle, centre = self.turn()
        rotation = App.Rotation(axis, angle)
        return App.Placement(centre - rotation.multVec(centre), rotation)

    def at(self, x, y, z):
        return self.motion().multVec(V(x, y, z))

    def along(self, d):
        return self.motion().Rotation.multVec(d)

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
            through=self.at(0, -self.A, self.H + self.A),
            contains=self.at(self.W / 2, -self.A, self.H + self.A),
        )

    def topRight(self):
        return vertex(self.at(self.W + self.A, -self.A, self.H + self.A))

    def bottomLeft(self):
        return vertex(self.at(-self.A, -self.A, -self.A))

    @staticmethod
    def spineBase():
        return App.Placement(V(), App.Rotation(X, 90))

    @staticmethod
    def profileBase():
        return App.Placement()

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        self.spine = m.sketch(doc, "Spine", m.polygon(self.corners()), body, placement=self.spineBase())
        a = self.A
        self.profile = m.sketch(
            doc, "Square", m.rectangle(-a, -a, a, a), body, placement=self.profileBase()
        )
        if self.ROUTE == "offset":
            xy = m.originFeature(body, "XY_Plane")
            for sketch, offset in ((self.spine, self.spineBase()), (self.profile, self.profileBase())):
                sketch.AttachmentSupport = [(xy, "")]
                sketch.MapMode = "FlatFace"
                sketch.AttachmentOffset = offset
        elif self.ROUTE == "lcs":
            self.lcs = body.newObject("PartDesign::CoordinateSystem", "LCS")
            for sketch, offset in ((self.spine, self.spineBase()), (self.profile, self.profileBase())):
                sketch.AttachmentSupport = [(self.lcs, "")]
                sketch.MapMode = "ObjectXY"
                sketch.AttachmentOffset = offset
        doc.recompute()
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
        for name, kind, predicate, mode in (
            ("datum_left_outer", "PartDesign::Plane", self.leftOuter, "FlatFace"),
            ("datum_top_outer", "PartDesign::Plane", self.topOuter, "FlatFace"),
            ("sketch_bottom_inner", "Sketcher::SketchObject", self.bottomInner, "FlatFace"),
            ("point_top_right", "PartDesign::Point", self.topRight, "Vertex"),
            ("point_bottom_left", "PartDesign::Point", self.bottomLeft, "Vertex"),
        ):
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
        doc.recompute()
        # Two rings a little apart along the top front edge: one solid
        pattern = body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [pipe]
        pattern.Direction = (pipe, self.names(pipe, self.topFront()))
        pattern.Length = self.s(6)
        pattern.Occurrences = 2
        body.Tip = pattern
        self.ref("pattern_top_front", pattern, "Direction", self.topFront)

    def edit(self, doc):
        self.moved = True
        motion = self.motion()
        if self.ROUTE == "lcs":
            self.lcs.Placement = motion
            return
        for sketch, base in ((self.spine, self.spineBase()), (self.profile, self.profileBase())):
            if self.ROUTE == "offset":
                sketch.AttachmentOffset = motion.multiply(base)
            else:
                sketch.Placement = motion.multiply(base)


class Turn120(Turned):
    """The whole model turns 120 degrees about Z: nothing of the ring is where an element was."""

    def turn(self):
        return Z, 120, V()


class HalfTurnOntoItself(Turned):
    """The whole model turns half a turn about the ring's centre, normal to its plane: the ring
    lies on itself, the left leg where the right one was (a twin where every element was)."""

    def turn(self):
        return Y, 180, V(self.W / 2, 0, self.H / 2)


class SquareQuarterTurn(Turned):
    """The ring a 30 x 30 square; the whole model turns a quarter turn about its centre, normal to
    its plane: the ring lies on itself, each leg where the next one was."""

    HEIGHT = 30

    def turn(self):
        return Y, 90, V(self.W / 2, 0, self.H / 2)


class Turn120Offset(Turn120):
    """As Turn120, by the sketches' AttachmentOffsets on the XY plane (the Pipe's frame stays)."""

    ROUTE = "offset"


class HalfTurnOntoItselfOffset(HalfTurnOntoItself):
    """As HalfTurnOntoItself, by the sketches' AttachmentOffsets on the XY plane (the Pipe's frame
    stays)."""

    ROUTE = "offset"


class SquareQuarterTurnOffset(SquareQuarterTurn):
    """As SquareQuarterTurn, by the sketches' AttachmentOffsets on the XY plane (the Pipe's frame
    stays)."""

    ROUTE = "offset"


class Turn120OnAnLCS(Turn120):
    """As Turn120, both sketches on an LCS, which turns."""

    ROUTE = "lcs"


class HalfTurnOntoItselfOnAnLCS(HalfTurnOntoItself):
    """As HalfTurnOntoItself, both sketches on an LCS, which turns."""

    ROUTE = "lcs"


class SquareQuarterTurnOnAnLCS(SquareQuarterTurn):
    """As SquareQuarterTurn, both sketches on an LCS, which turns."""

    ROUTE = "lcs"
