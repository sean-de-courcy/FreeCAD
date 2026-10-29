# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6g (fork PR 383, round 6's second fix, 475a82449c): the closed spine's start by its
lines' names, now accepted where the translation fit's best start and way (bestFitOf) agree, read
in the body where no frame of the profile turned, else in each frame that turned; the names may be
partly gone (two or more stored names on the spine, at the places one cyclic order gives them).

Aimed at: (a) a wrong names' start the fit could agree with (the lines' IDs shifted round the ring
by its symmetry, mirrored, traded in pairs, with a face profile whose placement frame doesn't turn);
(b) partial names (two lines drawn anew at opposite places or adjacent, one drawn anew in place, a
line drawn anew with a turn); (c) the earlier families again.

The model as pipe_closed_r6fs.py's Ring (copied: a case imports only harness and models): a closed
rectangle of four lines on the XZ plane, (0, 0) -> (0, H) -> (W, H) -> (W, 0), W = 30, H = 20
(sketch x = global X, sketch y = global Z), a square profile 2A x 2B (normal Z, along the left leg)
at the bottom left corner, "Right corner". The stored start is the bottom left corner, the way up
the left leg. The expectations are the elements at their places on the edited model."""

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
    FOUND_BY = "review pr383-r6g"
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


# ---- (b) partial names


class TopAndBottomRedrawnFar(Ring):
    """One edit: the top and bottom lines deleted and drawn anew (new lines, at their places), the
    right leg moved out to x = 50 (the fit is not clear). Only the left and right lines' stored names
    are on the spine, at opposite places, which both cyclic orders give. The references to the left
    and right legs stay."""

    AXES = ("M3", "E2", "E3")
    REFS = ("datum_left_outer", "datum_right_outer")

    def edit(self, doc):
        self.width = 50
        w, h = self.W, self.H
        left, top, right, bottom = self.spine.Geometry
        right.StartPoint, right.EndPoint = V(w, h, 0), V(w, 0, 0)
        self.spine.Geometry = [
            left,
            right,
            Part.LineSegment(V(0, h, 0), V(w, h, 0)),
            Part.LineSegment(V(w, 0, 0), V(0, 0, 0)),
        ]


class TopAndRightRedrawnFar(Ring):
    """Control for TopAndBottomRedrawnFar: the top and right lines deleted and drawn anew (adjacent
    places), the right leg at x = 50. The left and bottom lines' stored names are on the spine at
    adjacent places (one cyclic order). The references to the left, bottom and the start corner
    stay."""

    AXES = ("M3", "E2", "E3")
    REFS = ("datum_left_outer", "sketch_bottom_inner", "point_bottom_left")

    def edit(self, doc):
        self.width = 50
        w, h = self.W, self.H
        left, top, right, bottom = self.spine.Geometry
        bottom.StartPoint = V(w, 0, 0)
        self.spine.Geometry = [
            left,
            bottom,
            Part.LineSegment(V(0, h, 0), V(w, h, 0)),
            Part.LineSegment(V(w, h, 0), V(w, 0, 0)),
        ]


class LeftLegRedrawnInPlaceWidenedFar(Ring):
    """One edit: the left leg (the stored start's line, where the profile is) deleted and drawn anew
    at its place, and the right leg moved out to x = 50. The three other lines' stored names place
    the start at the new line's start. The references to the right, top and bottom stay."""

    AXES = ("M3", "E2", "E3")
    REFS = ("datum_right_outer", "datum_top_outer", "sketch_bottom_inner", "point_top_right")

    def edit(self, doc):
        self.width = 50
        w, h = self.W, self.H
        left, top, right, bottom = self.spine.Geometry
        top.EndPoint = V(w, h, 0)
        right.StartPoint, right.EndPoint = V(w, h, 0), V(w, 0, 0)
        bottom.StartPoint = V(w, 0, 0)
        self.spine.Geometry = [top, right, bottom, Part.LineSegment(V(0, 0, 0), V(0, h, 0))]


class TopLegRedrawnTurned(Ring):
    """The top leg deleted and drawn anew at its place, and the whole model turned 120 degrees about
    Z, in one recompute (partial names with a turned frame). The references to the left, bottom and
    the start corner follow the turn."""

    AXES = ("M3", "E7", "E3")
    REFS = ("datum_left_outer", "sketch_bottom_inner", "point_bottom_left")

    def edit(self, doc):
        w, h = self.W, self.H
        left, top, right, bottom = self.spine.Geometry
        self.spine.Geometry = [left, right, bottom, Part.LineSegment(V(0, h, 0), V(w, h, 0))]
        self.turnModel(120)


# ---- (a) a wrong names' start


class RedrawnBy2WidenedFar(Ring):
    """One edit: the ring's lines redrawn from the top right corner (IDs kept, shifted round the
    ring by two: line 0 is now the right leg, drawn downward), the right leg at x = 50 (the fit is
    not clear). By the IDs the start goes to the top right corner and the legs follow the lines to
    the opposite places. The references stay at their places."""

    AXES = ("M3", "E2", "E3")

    def edit(self, doc):
        self.width = 50
        w, h = self.W, self.H
        self.setSpine([((w, h), (w, 0)), ((w, 0), (0, 0)), ((0, 0), (0, h)), ((0, h), (w, h))])


class MirroredWidenedFar(Ring):
    """One edit: the ring's lines mirrored about its middle line x = W / 2 (IDs kept: line 0 is the
    right leg drawn upward, the cyclic order of the IDs kept), the right leg at x = 50. The
    references stay at their places."""

    AXES = ("M3", "E2", "E3")

    def edit(self, doc):
        self.width = 50
        w, h = self.W, self.H
        self.setSpine([((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0)), ((0, 0), (w, 0))])


class TradedLegsWidenedFar(Ring):
    """S-4 without the turn: the left and right lines trade their geometry (IDs kept), the right leg
    moved out to x = 50, in one recompute. The stored names run the other way round the ring. The
    references to the top, bottom and fillet stay."""

    AXES = ("M3", "E2", "E3")
    REFS = ("datum_top_outer", "sketch_bottom_inner", "fillet_top_front", "point_top_right")

    def edit(self, doc):
        self.width = 50
        w, h = self.W, self.H
        self.setSpine([((w, h), (w, 0)), ((0, h), (w, h)), ((0, 0), (0, h)), ((w, 0), (0, 0))])


class FaceProfileRedrawnBy2Turned180AndWidened(Ring):
    """The profile is the top face of a Pad (1 down) of the square, its sketch attached to the XY
    plane through its offset (the Pad's placement doesn't turn). The ring's lines redrawn from the
    top right corner (IDs shifted by two), the right line at x = 34, and the ring's placement and
    the profile sketch's offset turned 180 degrees about Z, in one recompute: the rectangle's own
    symmetry. The references follow the turn, at their places."""

    AXES = ("M3", "E7", "E2", "E3")
    faceProfile = True

    def edit(self, doc):
        self.width = 34
        w, h = self.W, self.H
        self.setSpine([((w, h), (w, 0)), ((w, 0), (0, 0)), ((0, 0), (0, h)), ((0, h), (w, h))])
        self.turnModel(180)


class FaceProfileTurned180AndWidened(FaceProfileRedrawnBy2Turned180AndWidened):
    """Control: FaceProfileRedrawnBy2Turned180AndWidened with the lines kept (no redraw)."""

    AXES = ("M3", "E7", "E2")

    def edit(self, doc):
        self.widen(34)
        self.turnModel(180)


class SketchTurned180AboutCornerWidenedFar(Ring):
    """The ring's lines (IDs kept) moved to the loop turned 180 degrees about the bottom left corner
    in the sketch's plane, the profile kept, and the right line (now at x = -W) moved out to
    x = -50, in one recompute (no frame turns; the body fit's best start is the translated twin,
    the names' the turned start). The references follow the turn."""

    AXES = ("M3", "E7", "E2")
    REFS = ("datum_left_outer", "datum_top_outer", "sketch_bottom_inner", "point_bottom_left")
    flip = False

    def at(self, x, y, z):
        return App.Rotation(Y, 180 if self.flip else 0).multVec(V(x, y, z))

    def along(self, d):
        return App.Rotation(Y, 180 if self.flip else 0).multVec(d)

    def edit(self, doc):
        self.width = 50
        w, h = self.W, self.H
        c = [(0, 0), (0, -h), (-w, -h), (-w, 0)]
        self.setSpine([(c[i], c[(i + 1) % 4]) for i in range(4)])
        self.flip = True


class RedrawnBy2Turned120AndWidened(Ring):
    """The ring's lines redrawn from the top right corner (IDs shifted by two), the right line at
    x = 34 and the whole model turned 120 degrees about Z (sketch profile), in one recompute. The
    references follow the turn, at their places."""

    AXES = ("M3", "E7", "E2", "E3")

    def edit(self, doc):
        self.width = 34
        w, h = self.W, self.H
        self.setSpine([((w, h), (w, 0)), ((w, 0), (0, 0)), ((0, 0), (0, h)), ((0, h), (w, h))])
        self.turnModel(120)


# ---- (a) a frame that turned by the ring's symmetry while the profile stayed


class ProfileReplacedWidened(Ring):
    """The profile's sketch placed half a turn about its normal with its lines drawn at the
    negated sketch coordinates (IDs and directions kept): the profile is the same in the body, line
    for line (a reparameterisation; its placement frame turns half a turn, its geometry frame
    doesn't), and the ring's right line moved out to x = 34, in one recompute. Every reference
    stays."""

    AXES = ("M3", "E3", "E2")

    def replaceProfile(self):
        g = self.profile.Geometry
        for line in g:
            s, e = V(line.StartPoint), V(line.EndPoint)
            line.StartPoint, line.EndPoint = V(-s.x, -s.y, 0), V(-e.x, -e.y, 0)
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(
            self.at(0, 0, 0), self.rot().multiply(App.Rotation(Z, 180))
        )

    def edit(self, doc):
        self.replaceProfile()
        self.widen(34)


class ProfileReplacedMirroredWidened(ProfileReplacedWidened):
    """ProfileReplacedWidened with the ring's lines mirrored about its middle line (IDs kept: line 0
    is the right leg drawn upward; the cyclic order of the IDs kept), the right leg at x = 34, in one
    recompute. Read in the turned placement frame, the stored ring is mirrored about the left leg,
    and the fit's best start is the mirrored ring's, the bottom right corner, where line 0 now
    starts. The references stay at their places."""

    AXES = ("M3", "E3", "E2")

    def mirror(self):
        self.width = 34
        w, h = self.W, self.H
        self.setSpine([((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0)), ((0, 0), (w, 0))])

    def edit(self, doc):
        self.replaceProfile()
        self.mirror()


class MirroredWidened(Ring):
    """Control for ProfileReplacedMirroredWidened: the ring's lines mirrored, the right leg at
    x = 34, the profile untouched. The references stay at their places."""

    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        self.width = 34
        w, h = self.W, self.H
        self.setSpine([((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0)), ((0, 0), (w, 0))])


class ProfileTurned180MirroredWidened(ProfileReplacedWidened):
    """The profile's sketch turned half a turn about its normal (its lines kept in the sketch: the
    square is the same in the body, each line at the opposite side), the ring's lines mirrored about
    its middle line (IDs kept: line 0 is the right leg drawn upward, the IDs' cyclic order kept) and
    the right leg at x = 34, in one recompute. Both profile frames turned half a turn about the left
    leg's line, which carries the stored ring onto its mirror image; the translation fit read there
    starts at the bottom right corner, where the names (line 0's start) put it too, so the names'
    start is taken quietly and every leg follows its line to the mirrored place (475a82449c: wrong,
    silently; integration and 4117368552's frame carry: loud). The references stay at their
    places."""

    AXES = ("M3", "E7", "E3", "E2")

    def edit(self, doc):
        self.profile.Placement = App.Placement(
            self.at(0, 0, 0), self.rot().multiply(App.Rotation(Z, 180))
        )
        ProfileReplacedMirroredWidened.mirror(self)


class ProfileCycledBy2MirroredWidened(ProfileReplacedWidened):
    """The profile's lines each take the place of the line two on (IDs kept; the square is the
    same, its first line the opposite side: its geometry frame turns half a turn), the ring's lines
    mirrored about its middle line (IDs kept) and the right leg at x = 34, in one recompute. The
    references stay at their places."""

    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        g = self.profile.Geometry
        ends = [(V(l.StartPoint), V(l.EndPoint)) for l in g]
        for i, line in enumerate(g):
            line.StartPoint = V(1e3 + 10 * i, 0, 0)
            line.EndPoint = V(1e3 + 10 * i, 5, 0)
        for i, line in enumerate(g):
            s, e = ends[(i + 2) % len(g)]
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        ProfileReplacedMirroredWidened.mirror(self)
