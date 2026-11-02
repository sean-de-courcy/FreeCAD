# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6fs (fork PR 383, round 6 fix, d1f59dcadc): where the closed spine's unpaired path
(decision 180) stops the pipe on a single edit, and the controls beside it.

Unpaired is now: a stored frame of the profile turned (> 1e-6 rad), or the body fit not clear. The
start is then taken from the lines' stored names, and only where a frame of the profile carries the
stored start and its first edge's direction onto the named start and first edge; else the pipe
stops. So it stops where the stored lines are not all on the spine (a leg deleted and drawn anew, a
corner chamfered at the start) and the fit is not clear, and where a frame turned for a reason other
than the ring's turn (the profile attached to the leg's interior, and the leg tilts).

The model as pipe_closed_r6s.py's PostRing (copied: a case imports only harness and models): a
closed rectangle of four lines on the XZ plane, (0, 0) -> (0, H) -> (W, H) -> (W, 0), W = 30, H = 20
(sketch x = global X, sketch y = global Z), a square profile 2A x 2B (normal Z, along the left leg) at
the bottom left corner, "Right corner"."""


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
    AXES = ("M3", "E7")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6fs"
    TIER = "F"
    SIZE = 40
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
    attachAt = None  # the profile attached NormalToEdge to the spine's first edge at this parameter
    modelRotation = None

    W = property(lambda self: self.s(self.width))
    H = property(lambda self: self.s(self.height))
    A = property(lambda self: self.s(self.halfX))
    B = property(lambda self: self.s(self.halfY))

    def rot(self):
        return self.modelRotation or App.Rotation(Z, self.turn)

    def at(self, x, y, z):
        return self.rot().multVec(V(x, y, z))

    def along(self, d):
        return self.rot().multVec(d)

    def leftOuter(self):
        return face("plane", normal=self.along(-X), contains=self.at(-self.A, 0, self.s(10)))

    def rightOuter(self):
        return face("plane", normal=self.along(X), contains=self.at(self.W + self.A, 0, self.s(10)))

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
        if self.attachAt is not None:
            self.profile.AttachmentSupport = [(self.spine, "Edge1")]
            self.profile.MapMode = "NormalToEdge"
            self.profile.MapPathParameter = self.attachAt
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
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
        self.profile.Placement = self.profilePlacement()


class RightLegRedrawn(Ring):
    """Control: the right leg deleted and drawn anew (a new line) at x = 34, the top and bottom
    lines lengthened to meet it (a move of 4: the fit is clear). The references to the left, top
    and bottom stay."""

    AXES = ("M3", "E2", "E3")
    X2 = 34

    def edit(self, doc):
        w, h = self.s(self.X2), self.H
        left, top, right, bottom = self.spine.Geometry
        top.EndPoint = V(w, h, 0)
        bottom.StartPoint = V(w, 0, 0)
        self.spine.Geometry = [left, top, bottom, Part.LineSegment(V(w, h, 0), V(w, 0, 0))]
        self.width = self.X2


class RightLegRedrawnFar(RightLegRedrawn):
    """A single edit: the right leg deleted and drawn anew at x = 50 (a move of 20: the fit is not
    clear), the top and bottom lines lengthened to meet it. The stored line of the right leg is gone,
    so the stored names can't be matched: the pipe stops (integration: the references stay)."""

    X2 = 50


class RightLegRedrawnNearThenFar(RightLegRedrawn):
    """The way out the error names, for the same edit: the leg drawn anew at x = 34, and in the next
    recompute the new line moved to x = 50. Every reference stays."""

    steps = ("near", "far")

    def near(self, doc):
        RightLegRedrawn.edit(self, doc)

    def far(self, doc):
        w, h = self.s(50), self.H
        self.setSpine([((0, 0), (0, h)), ((0, h), (w, h)), ((w, 0), (0, 0)), ((w, h), (w, 0))])
        self.width = 50


class TopLegRedrawnFar(Ring):
    """A single edit: the top leg deleted and drawn anew, 20 higher (z = 40), the left and right
    lines lengthened to meet it. The references to the left, bottom and the profile's corner stay."""

    AXES = ("M3", "E2", "E3")
    REFS = ("datum_left_outer", "sketch_bottom_inner", "point_bottom_left")

    def edit(self, doc):
        w, h = self.W, self.s(40)
        left, top, right, bottom = self.spine.Geometry
        left.EndPoint = V(0, h, 0)
        right.StartPoint = V(w, h, 0)
        self.spine.Geometry = [left, right, bottom, Part.LineSegment(V(0, h, 0), V(w, h, 0))]
        self.height = 40


class StartCornerChamferedProfileMoved(Ring):
    """The bottom left corner (the stored start) chamfered by 4 (a fifth line joins the left and
    bottom lines) and the profile moved with it to the chamfer's upper end (0, 4): one sketch edit
    and one profile move. The edge count changes, so the stored names (4) can't be matched to the
    lines (5): the pipe stops (integration: the references stay)."""

    AXES = ("M3", "E8", "E4")
    REFS = (
        "datum_right_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "fillet_top_front",
        "point_top_right",
    )
    slideTo = 0

    def profilePlacement(self):
        return App.Placement(self.at(0, 0, self.s(self.slideTo)), self.rot())

    def edit(self, doc):
        w, h, c = self.W, self.H, self.s(4)
        g = self.spine.Geometry
        g[0].StartPoint, g[0].EndPoint = V(0, c, 0), V(0, h, 0)
        g[3].StartPoint, g[3].EndPoint = V(w, 0, 0), V(c, 0, 0)
        g.append(Part.LineSegment(V(c, 0, 0), V(0, c, 0)))
        self.spine.Geometry = g
        self.slideTo = 4
        self.profile.Placement = self.profilePlacement()


class AttachedAtQuarterTilted(Ring):
    """The profile attached NormalToEdge to the left leg a quarter of the way up (parameter 0.25);
    the top left vertex dragged 4 to the right, so the left leg tilts (the top line shortened, still
    horizontal) and the profile's frame turns about a point 5 up the leg. No stored frame holds, a
    frame turned (by any tilt: 0.01 mm already), and none carries the stored start onto the named
    one: the pipe stops. Integration: the pipe recomputes, its references to the top, bottom and
    fillet are wrong (debt) and the right leg and the corner break."""

    attachAt = 0.25
    AXES = ("M3", "E4")
    REFS = (
        "datum_right_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "fillet_top_front",
        "point_top_right",
    )

    def edit(self, doc):
        w, h, d = self.W, self.H, self.s(4)
        self.setSpine([((0, 0), (d, h)), ((d, h), (w, h)), ((w, h), (w, 0)), ((w, 0), (0, 0))])


class TradedLegsTurnedWidened(Ring):
    """The left and right lines trade their geometry (IDs kept: line 0 is now the right leg drawn
    downward, line 2 the left leg drawn upward), the right leg moved out to x = 34, and the model
    turned 120 degrees about Z, in one recompute. The stored names run the other way round the ring:
    the pipe stops (integration: three references stay, the corner is wrong)."""

    AXES = ("M3", "E7", "E2", "E3")
    REFS = ("datum_top_outer", "sketch_bottom_inner", "fillet_top_front", "point_top_right")

    def edit(self, doc):
        w, h = self.s(34), self.H
        self.setSpine([((w, h), (w, 0)), ((0, h), (w, h)), ((0, 0), (0, h)), ((w, 0), (0, 0))])
        self.width = 34
        self.turnModel(120)


class AllReversedWidenedFar(Ring):
    """Every line drawn the other way (IDs kept) and the right leg moved out to x = 50 (the fit is
    not clear): the names run the other way round, the start is the first line's far end (where it
    was). Every reference stays (integration: breaks)."""

    AXES = ("M3", "E2", "E3")

    def edit(self, doc):
        w, h = self.s(50), self.H
        self.setSpine([((0, h), (0, 0)), ((w, h), (0, h)), ((w, 0), (w, h)), ((0, 0), (w, 0))])
        self.width = 50


class TurnThenWidenFar(Ring):
    """The way out the error names, for a turn with another edit: the model turned 120 degrees about
    Z in one recompute, and in the next the right line moved to x = 50. Every reference follows."""

    AXES = ("M3", "E7", "E2")
    steps = ("turnstep", "widenfar")

    def turnstep(self, doc):
        self.turnModel(120)

    def widenfar(self, doc):
        self.widen(50)


class LcsTurnedGenericAndWidenedFar(Ring):
    """Both sketches attached to a local coordinate system (offsets as built), which turns 37
    degrees about the axis (1, 2, 3) while the ring's right line moves from x = 30 to x = 50 (the fit
    is not clear): a turn with another edit in 3D, with the frames' noise at any scale. The
    references follow the turn."""

    AXES = ("M3", "E7", "E2")
    REFS = (
        "datum_right_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "fillet_top_front",
        "point_top_right",
    )

    def build(self, doc):
        Ring.build(self, doc)
        self.lcs = self.body.newObject("PartDesign::CoordinateSystem", "LCS")
        for sketch, offset in (
            (self.spine, self.spinePlacement()),
            (self.profile, self.profilePlacement()),
        ):
            sketch.AttachmentSupport = [(self.lcs, "")]
            sketch.MapMode = "ObjectXY"
            sketch.AttachmentOffset = offset
        doc.recompute()

    def edit(self, doc):
        self.widen(50)
        self.modelRotation = App.Rotation(V(1, 2, 3), 37)
        self.lcs.Placement = App.Placement(V(), self.modelRotation)
