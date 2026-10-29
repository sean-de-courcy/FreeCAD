# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6s: a closed spine turned by a symmetry of the ring while something else changes
in the same recompute (decision 171, fitIsClear). A rectangle ring turned 180 degrees (or a
square one 90) lies on itself, so the translation fit pairs the stored start with the opposite
(twin) corner with a residual of the size of the other edit alone: clear by fitIsClear. The turn
is not exact in any stored frame once another edit comes with it, so the body read applies; the
profile turned with the model sits at the turned first corner, and the start went to the twin
corner, silently.

The model as pipe_closed_r6.py's PostRing (copied): a closed rectangle of four lines on the XZ
plane, (0, 0) -> (0, H) -> (W, H) -> (W, 0), a square profile 2A x 2B at the bottom left corner,
"Right corner"; the whole model turns about Z."""


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
    FOUND_BY = "review pr383-r6s"
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

    height = 20

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

    TURN = 120

    def turnModel(self):
        self.turn = self.TURN
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



    def widen(self, width):
        w = self.s(width)
        h = self.H
        g = self.spine.Geometry
        g[1].EndPoint = V(w, h, 0)
        g[2].StartPoint, g[2].EndPoint = V(w, h, 0), V(w, 0, 0)
        g[3].StartPoint = V(w, 0, 0)
        self.spine.Geometry = g
        self.width = width

    def raiseTop(self, height):
        h = self.s(height)
        w = self.W
        g = self.spine.Geometry
        g[0].EndPoint = V(0, h, 0)
        g[1].StartPoint, g[1].EndPoint = V(0, h, 0), V(w, h, 0)
        g[2].StartPoint = V(w, h, 0)
        self.spine.Geometry = g
        self.height = height

    def profileLink(self, doc):
        if not getattr(self, "FACE", False):
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


class Ring180(PostRing):
    """Control: the whole model turns 180 degrees about Z and nothing else changes (the profile's
    frame holds exactly). Every reference follows the turn."""

    AXES = ("M3", "E7")
    TURN = 180

    def edit(self, doc):
        self.turnModel()


class Ring180Widened(PostRing):
    """The ring's right line moves from x = 30 to x = 34 (the top and bottom lines lengthened, IDs
    kept) as the whole model turns 180 degrees about Z, in one recompute. The ring turned by
    180 degrees about Z is its own mirror in its plane: the translation fit pairs the stored
    start with the turned bottom right corner (residual 1.7 of a size of 18), clear by
    fitIsClear. The profile turned with the model, at the turned bottom left corner. Every
    reference follows the turn, on the wider ring."""

    AXES = ("M3", "E7", "E2")
    TURN = 180

    def edit(self, doc):
        self.widen(34)
        self.turnModel()


class Ring170Widened(Ring180Widened):
    """As Ring180Widened, the model turned 170 degrees (the mirror reading is not exact; the fit's
    residual is 3 of 18)."""

    TURN = 170


class Ring190Widened(Ring180Widened):
    """As Ring180Widened, turned 190 degrees."""

    TURN = 190


class Ring180TopRaised(PostRing):
    """The ring's top line moves from z = 20 to z = 26 (the left and right lines lengthened, IDs
    kept) as the whole model turns 180 degrees about Z. Every reference follows the turn."""

    AXES = ("M3", "E7", "E2")
    TURN = 180

    def edit(self, doc):
        self.raiseTop(26)
        self.turnModel()


class Ring180FaceProfileStretched(PostRing):
    """The profile is the top face of a Pad of the square (as pipe_closed_r6.py's
    RingTurnedFaceProfileStretched), stretched in sketch y (B from 2 to 3) as the model turns
    180 degrees about Z. Every reference follows the turn."""

    AXES = ("M3", "E7", "E1")
    TURN = 180
    FACE = True

    def edit(self, doc):
        self.stretchProfileY(1.5)
        self.turnModel()


class Square180Widened(Ring180Widened):
    """A 20 x 20 ring (the right line from x = 20 to x = 24) turned 180 degrees."""

    width = 20


class Ring180FaceProfileWidened(PostRing):
    """The face profile of Ring180FaceProfileStretched, unstretched; the ring's right line moves
    out to x = 34 as the model turns 180 degrees about Z. Every reference follows the turn."""

    AXES = ("M3", "E7", "E2")
    TURN = 180
    FACE = True

    def edit(self, doc):
        self.widen(34)
        self.turnModel()


class Ring180ProfileStretched(PostRing):
    """Control: a sketch profile (unattached), stretched in sketch y (B from 2 to 3) as the whole
    model turns 180 degrees about Z (the placement frame holds). Every reference follows the turn."""

    AXES = ("M3", "E7", "E1")
    TURN = 180

    def edit(self, doc):
        self.stretchProfileY(1.5)
        self.turnModel()


class Ring175FaceProfileStretched(Ring180FaceProfileStretched):
    """As Ring180FaceProfileStretched, turned 175 degrees."""

    TURN = 175


class Square180FaceProfileWidened(Ring180FaceProfileWidened):
    """A 20 x 20 ring (the right line from x = 20 to x = 24), face profile, turned 180 degrees."""

    width = 20


class SlideThenFar(PostRing):
    """The profile slid from the bottom left corner up the left leg to z = 16 (past the leg's
    middle: the stored start stays at the bottom left, B1's rule), then the ring's right line
    moves from x = 30 to x = 50 (no turn): the fit isn't clear and the start is taken at the
    profile, the top left corner. The references to the ring's faces and edges stay (point_bottom_left
    is the profile's vertex, which slid, and is left out)."""

    AXES = ("M3", "E4", "E2")
    steps = ("slide", "widenfar")
    slideTo = 0
    REFS = (
        "datum_left_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "fillet_top_front",
        "point_top_right",
    )

    def profilePlacement(self):
        return App.Placement(
            self.at(0, 0, self.s(self.slideTo)), App.Rotation(Z, self.turn)
        )

    def attachments(self):
        return tuple(a for a in PostRing.attachments(self) if a[0] != "point_bottom_left")

    def slide(self, doc):
        self.slideTo = 16
        self.profile.Placement = self.profilePlacement()

    def widenfar(self, doc):
        self.widen(50)


class SlideThenTurnWidened(SlideThenFar):
    """As SlideThenFar, but the second step turns the model 120 degrees about Z and widens the
    ring to x = 34 (no frame holds, the fit isn't clear)."""

    AXES = ("M3", "E4", "E7", "E2")
    steps = ("slide", "turnwiden")

    def turnwiden(self, doc):
        self.widen(34)
        self.turnModel()
