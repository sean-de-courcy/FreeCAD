# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6hs (fork PR 383, round 6, head 5fe2ddbea7, decision 187 (2)): where a frame of the
profile turned, the closed spine's start by the lines' names is accepted when a frame of the profile
carries the stored start and its next vertex exactly onto the names' start and the next vertex of
their order.

Aimed at (a): a frame that carries the stored start onto the names' start while the ring's lines
changed places with their IDs kept. The profile is moved by the ring's own symmetry (a rectangle's
half turn about its centre, a square's quarter turn), the ring's lines redrawn (cycled, mirrored,
traded) with the right leg moved in one recompute, so the ring's geometry is the old one, widened.
The legs stay at their places: the solid is the old ring, and only the profile (the section) moved.
The model as pipe_closed_r6g.py's Ring (copied: a case imports only harness and models): a closed
rectangle of four lines on the XZ plane, (0, 0) -> (0, H) -> (W, H) -> (W, 0), W = 30, H = 20
(sketch x = global X, sketch y = global Z), a square profile 2A x 2B (normal Z, along the left leg)
at the bottom left corner, "Right corner"."""

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


class Ring(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6hs"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    REFS = (
        "datum_left_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "fillet_top_front",
        "point_bottom_left",
    )
    turn = 0
    width = 30
    height = 20
    halfX = 2
    halfY = 2
    faceProfile = False  # the profile is the top face of a Pad of the square (attached to XY)

    W = property(lambda self: self.s(self.width))
    H = property(lambda self: self.s(self.height))
    A = property(lambda self: self.s(self.halfX))
    B = property(lambda self: self.s(self.halfY))

    def rot(self):
        return App.Rotation(Z, self.turn)

    def at(self, x, y, z):
        return self.rot().multVec(V(x, y, z))

    def along(self, d):
        return self.rot().multVec(d)

    def leftOuter(self):
        return face("plane", normal=self.along(-X), contains=self.at(-self.A, 0, self.H / 2))

    def rightOuter(self):
        return face("plane", normal=self.along(X), contains=self.at(self.W + self.A, 0, self.H / 2))

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
        return App.Placement(self.at(0, 0, 0), self.rot())

    def profileLink(self, doc):
        if not self.faceProfile:
            return self.profile
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

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        w, h = self.W, self.H
        self.spine = m.sketch(
            doc,
            "Spine",
            m.polygon([(0, 0), (0, h), (w, h), (w, 0)]),
            body,
            placement=self.spinePlacement(),
        )
        a, b = self.A, self.B
        self.profile = m.sketch(
            doc, "Square", m.rectangle(-a, -b, a, b), body, placement=self.profilePlacement()
        )
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
        kinds = {
            "datum_left_outer": ("PartDesign::Plane", self.leftOuter, "FlatFace"),
            "datum_right_outer": ("PartDesign::Plane", self.rightOuter, "FlatFace"),
            "datum_top_outer": ("PartDesign::Plane", self.topOuter, "FlatFace"),
            "sketch_bottom_inner": ("Sketcher::SketchObject", self.bottomInner, "FlatFace"),
            "point_top_right": ("PartDesign::Point", self.topRight, "Vertex"),
            "point_bottom_left": ("PartDesign::Point", self.bottomLeft, "Vertex"),
        }
        made = {}
        for name in self.REFS:
            if name in kinds:
                kind, predicate, mode = kinds[name]
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

    # ---- edits
    def setSpine(self, lines):
        """lines: (start, end) in sketch coordinates for ids 0..3; the lines keep their IDs."""
        g = self.spine.Geometry
        for i in range(len(lines)):
            g[i].StartPoint, g[i].EndPoint = V(100 + 10 * i, 100, 0), V(105 + 10 * i, 105, 0)
        for i, (p, q) in enumerate(lines):
            g[i].StartPoint, g[i].EndPoint = V(p[0], p[1], 0), V(q[0], q[1], 0)
        self.spine.Geometry = g

    def widen(self, width):
        self.width = width
        w, h = self.W, self.H
        self.setSpine([((0, 0), (0, h)), ((0, h), (w, h)), ((w, h), (w, 0)), ((w, 0), (0, 0))])

    def turnModel(self, degrees):
        self.turn = degrees
        self.spine.Placement = self.spinePlacement()
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = self.profilePlacement()
        else:
            self.profile.Placement = self.profilePlacement()



# ---- (a) the profile moved by the ring's symmetry, the ring's lines redrawn with their IDs kept


class OppositeCorner(Ring):
    """The profile's sketch moved to the opposite bottom/top corner by the ring's half turn about
    its centre (about Y for the corner across the ring; about Z for the corner across the bottom),
    the right leg moved to x = 34 (the stored ring is not in place), and the ring's lines redrawn
    from that corner (IDs kept). The carry of the profile's frame puts the stored start on the
    names' start. The solid is the old ring, widened: every reference stays at its place."""

    abstract = True
    AXES = ("M3", "E7", "E2", "E3")
    wide = 34
    to = "across"  # "across" (V2, rotation about Y), "bottom" (V3, rotation about Z)

    def lines(self, w, h):
        raise NotImplementedError

    def moveProfile(self):
        w, h = self.W, self.H
        if self.to == "across":
            where = App.Placement(V(w, 0, h), App.Rotation(Y, 180))
        else:
            where = App.Placement(V(w, 0, 0), App.Rotation(Z, 180))
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = where
        else:
            self.profile.Placement = where

    def edit(self, doc):
        self.width = self.wide
        w, h = self.W, self.H
        self.setSpine(self.lines(w, h))
        self.moveProfile()


class ProfileAcrossIdsCycled2(OppositeCorner):
    """IDs shifted by two (line 0 is the right leg drawn downward from the top right corner), the
    profile moved to that corner by the half turn about Y."""

    def lines(self, w, h):
        return [((w, h), (w, 0)), ((w, 0), (0, 0)), ((0, 0), (0, h)), ((0, h), (w, h))]


class ProfileAcrossIdsCycled2Face(ProfileAcrossIdsCycled2):
    """The same with a face profile (the top face of a Pad of the square; its placement frame stays,
    its geometry's turns)."""
    # The Pipe stops and passes its Pad's shape through: the point lands on the Pad's
    # vertex, which carries the profile sketch's name (ops#549, decision 193)
    ACCEPTED = {"point_bottom_left|V2s": "decision 193"}

    faceProfile = True


class ProfileBottomRightMirrored(OppositeCorner):
    """IDs mirrored about the middle line (line 0 is the right leg drawn upward from the bottom
    right corner), the profile moved to that corner by the half turn about Z."""

    to = "bottom"

    def lines(self, w, h):
        return [((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0)), ((0, 0), (w, 0))]


class ProfileBottomRightMirroredFace(ProfileBottomRightMirrored):
    # The Pipe stops and passes its Pad's shape through: the point lands on the Pad's
    # vertex, which carries the profile sketch's name (ops#549, decision 193)
    ACCEPTED = {"point_bottom_left|V2s": "decision 193"}
    faceProfile = True


class ProfileAcrossLinesTraded(OppositeCorner):
    """The left and right lines trade their geometry (IDs kept: line 0 is the right leg drawn
    downward, line 2 the left drawn upward), the profile moved to the top right corner."""

    def lines(self, w, h):
        return [((w, h), (w, 0)), ((0, h), (w, h)), ((0, 0), (0, h)), ((w, 0), (0, 0))]


class ProfileAcrossIdsCycled2Far(ProfileAcrossIdsCycled2):
    """As ProfileAcrossIdsCycled2 with the right leg at x = 50 (the fit is not clear)."""

    wide = 50


class ProfileBottomRightMirroredFar(ProfileBottomRightMirrored):
    wide = 50


class SquareRingProfileQuarterTurn(Ring):
    """A square ring (24 x 24 after the edit; 20 x 20 before), the profile moved from the bottom
    left corner to the top left one by the ring's quarter turn about its centre (a rotation of the
    square profile by 90 about Y), the ring's lines redrawn from the top left corner (IDs shifted by
    one). The ring is the old one, grown; every reference stays at its place."""

    AXES = ("M3", "E7", "E2", "E3")
    width = 20
    height = 20
    REFS = (
        "datum_left_outer",
        "datum_right_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "point_bottom_left",
    )
    side = 24

    def edit(self, doc):
        self.width = self.side
        self.height = self.side
        w, h = self.W, self.H
        self.setSpine([((0, h), (w, h)), ((w, h), (w, 0)), ((w, 0), (0, 0)), ((0, 0), (0, h))])
        where = App.Placement(V(0, 0, h), App.Rotation(Y, 90))
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = where
        else:
            self.profile.Placement = where


class SquareRingProfileQuarterTurnBack(SquareRingProfileQuarterTurn):
    """The ring's lines redrawn from the bottom right corner going up (IDs shifted by three: the
    other way round the ring), the profile moved there by the quarter turn about Y the other way."""

    def edit(self, doc):
        self.width = self.side
        self.height = self.side
        w, h = self.W, self.H
        self.setSpine([((w, 0), (0, 0)), ((0, 0), (0, h)), ((0, h), (w, h)), ((w, h), (w, 0))])
        where = App.Placement(V(w, 0, 0), App.Rotation(Y, -90))
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = where
        else:
            self.profile.Placement = where


# ---- (c) the profile moved or turned with the lines' IDs kept: where integration is right


class ProfileMoved(Ring):
    """The profile's sketch placed at `where` (a Placement from the unscaled ring) and the right leg
    moved to x = `wide`, in one recompute; the IDs kept. Every reference stays at its place."""

    abstract = True
    AXES = ("M3", "E7", "E2")
    wide = 34

    def where(self):
        raise NotImplementedError

    def edit(self, doc):
        place = self.where()
        self.widen(self.wide)
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = place
        else:
            self.profile.Placement = place


class ProfileAcrossWidened(ProfileMoved):
    """The profile moved to the top right corner by the half turn about Y, IDs kept."""

    def where(self):
        return App.Placement(V(self.s(34), 0, self.H), App.Rotation(Y, 180))


class ProfileFlippedOverWidened(ProfileMoved):
    """The profile turned half a turn about X through the start corner (the sketch flipped over;
    the square is the same), IDs kept."""

    def where(self):
        return App.Placement(V(0, 0, 0), App.Rotation(X, 180))




class ProfileTurned90OnItselfLowered(Ring):
    """The profile turned a quarter turn on itself and the bottom line and the right leg's foot
    lowered by 4 (the start corner moved down along the left leg), IDs kept: L-1's family without
    a stretched profile."""

    AXES = ("M3", "E7", "E2")
    REFS = ("datum_left_outer", "datum_top_outer", "datum_right_outer", "point_top_right")

    def edit(self, doc):
        w, h = self.W, self.H
        d = self.s(4)
        self.setSpine([((0, -d), (0, h)), ((0, h), (w, h)), ((w, h), (w, -d)), ((w, -d), (0, -d))])
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(Z, 90))


class ProfileSlidTurned90(Ring):
    """The profile slid 5 up the left leg (before its middle) and turned a quarter turn on itself,
    the right leg moved to 34, IDs kept."""

    AXES = ("M3", "E7", "E2")

    def edit(self, doc):
        self.widen(34)
        self.profile.Placement = App.Placement(V(0, 0, self.s(5)), App.Rotation(Z, 90))


# ---- (a) partial names: the profile slid to the far end of the start leg, flipped over


class SlidToLegEndFlippedPartialNames(Ring):
    """The top and bottom lines deleted and drawn anew, the right leg moved to x = 50 (the fit is
    not clear), and the profile moved to the top of the left leg and flipped over (a half turn about
    Y: the sweep runs down the leg). Only the left and right lines' stored names are on the spine,
    at opposite places, which both cyclic orders give; a frame carries the stored start to the top
    left corner and the next vertex to the bottom left. The solid is the ring, widened."""

    AXES = ("M3", "E7", "E2", "E3")
    REFS = (
        "datum_left_outer",
        "datum_right_outer",
        "point_bottom_left",
        "point_top_right",
    )
    wide = 50

    def edit(self, doc):
        self.width = self.wide
        w, h = self.W, self.H
        left, top, right, bottom = self.spine.Geometry
        right.StartPoint, right.EndPoint = V(w, h, 0), V(w, 0, 0)
        self.spine.Geometry = [
            left,
            right,
            Part.LineSegment(V(0, h, 0), V(w, h, 0)),
            Part.LineSegment(V(w, 0, 0), V(0, 0, 0)),
        ]
        where = App.Placement(V(0, 0, h), App.Rotation(Y, 180))
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = where
        else:
            self.profile.Placement = where


class SlidToLegEndFlippedPartialNamesFace(SlidToLegEndFlippedPartialNames):
    # The Pipe stops and passes its Pad's shape through: the point lands on the Pad's
    # vertex, which carries the profile sketch's name (ops#549, decision 193)
    ACCEPTED = {"point_bottom_left|V2s": "decision 193"}
    faceProfile = True
    # The Pipe stops (decision 192) and passes its Pad's shape through: the point lands on the
    # Pad's vertex, which carries the profile sketch's name (ops#549; integration breaks it)
    ACCEPTED = {"point_bottom_left|V2s": "decision 193"}


class SlidToLegEndFlipped(Ring):
    """Control: the same without the redraw (IDs kept, right leg at 50)."""

    AXES = ("M3", "E7", "E2")
    wide = 50

    def edit(self, doc):
        self.widen(self.wide)
        where = App.Placement(V(0, 0, self.H), App.Rotation(Y, 180))
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = where
        else:
            self.profile.Placement = where


class SlidToLegEndReplacedPartialNames(SlidToLegEndFlippedPartialNames):
    """SlidToLegEndFlippedPartialNames with the profile moved to the top of the left leg by a
    reparameterisation instead of a flip: its sketch placed there, half a turn about Y (the sweep
    runs down the leg), with its lines drawn at the sketch coordinates negated in x, so the square
    in the body keeps each line on its own side. The references stay at their places."""

    def edit(self, doc):
        g = self.profile.Geometry
        for line in g:
            s, e = V(line.StartPoint), V(line.EndPoint)
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = V(-s.x, s.y, 0), V(-e.x, e.y, 0)
        self.profile.Geometry = g
        SlidToLegEndFlippedPartialNames.edit(self, doc)


class SlidToLegEndReplaced(Ring):
    """Control: IDs kept, right leg at 50, the profile moved to the top of the left leg by the same
    reparameterisation."""

    AXES = ("M3", "E7", "E2")

    def edit(self, doc):
        g = self.profile.Geometry
        for line in g:
            s, e = V(line.StartPoint), V(line.EndPoint)
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = V(-s.x, s.y, 0), V(-e.x, e.y, 0)
        self.profile.Geometry = g
        self.widen(50)
        self.profile.Placement = App.Placement(V(0, 0, self.H), App.Rotation(Y, 180))
