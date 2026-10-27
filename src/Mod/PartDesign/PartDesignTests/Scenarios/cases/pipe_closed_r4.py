# SPDX-License-Identifier: LGPL-2.1-or-later
"""K4b's ring cases (class A's attacker, pass 1b, ops#500), ported for fork PR 383 round 4: a square
tube swept around a closed spine (M3), the loop redrawn with its lines' IDs kept.

The spine, a sketch on the XZ plane: a closed rectangle of four lines, (0, 0) -> (0, 20) ->
(30, 20) -> (30, 0) -> (0, 0) (sketch x = global X, sketch y = global Z). The profile, a 4 x 4
square centred on the spine's start, normal to its first line. PartDesign AdditivePipe, "Right
corner": a rectangular frame. Opposite legs are mirror twins (made from the same profile edges,
told apart by the spine line), and every leg's faces are siblings of the other legs'. Every edit
but the turn leaves the solid as it was (oracle O4: every reference stays).

The class B ruling (10-27, `notes/naming-class-B.md` 9, I-B7): a closed-spine leg is its place in
the loop, named by its line, and the two must agree. A place whose line came from another place
is renamed (a `PLM` source), so its references break, or, after D1, are re-bound where they were;
before, they followed the line to another leg, silently. K4b's `LowIds` copies (X2) stay in the
inbox module."""

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
WIDTH, HEIGHT, A = 30, 20, 2
CORNERS = [(0, 0), (0, HEIGHT), (WIDTH, HEIGHT), (WIDTH, 0)]


class Ring(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2")
    ISSUE = "ops#469"
    FOUND_BY = "K4b attacker pass 1b"
    TIER = "F"
    REFS = (
        "datum_left_outer",
        "datum_right_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "fillet_top_front",
        "point_top_right",
    )
    turn = 0
    transition = "Right corner"  # "Transformed" refuses the 90-degree corners

    def at(self, x, y, z):
        return App.Rotation(Z, self.turn).multVec(V(x, y, z))

    def along(self, d):
        return App.Rotation(Z, self.turn).multVec(d)

    def leftOuter(self):
        return face("plane", normal=self.along(-X), contains=self.at(-A, 0, HEIGHT / 2))

    def rightOuter(self):
        return face("plane", normal=self.along(X), contains=self.at(WIDTH + A, 0, HEIGHT / 2))

    def topOuter(self):
        return face("plane", normal=Z, contains=self.at(WIDTH / 2, 0, HEIGHT + A))

    def bottomInner(self):
        return face("plane", normal=Z, contains=self.at(WIDTH / 2, 0, A))

    def topFront(self):
        return edge(
            "line",
            direction=self.along(X),
            through=self.at(0, -A, HEIGHT + A),
            contains=self.at(WIDTH / 2, -A, HEIGHT + A),
        )

    def topRight(self):
        return vertex(self.at(WIDTH + A, -A, HEIGHT + A))

    def spinePlacement(self):
        return App.Placement(V(), App.Rotation(Z, self.turn).multiply(App.Rotation(X, 90)))

    def profilePlacement(self, start=(0, 0), direction=(0, 1)):
        """The profile at the spine's start (sketch coordinates), normal to the first line."""
        turn = App.Rotation(Z, self.turn)
        base = turn.multVec(V(start[0], 0, start[1]))
        if direction[1]:  # along Z: the profile in the XY plane
            rotation = App.Rotation() if direction[1] > 0 else App.Rotation(X, 180)
        else:  # along X: the profile in the YZ plane
            axes = ((0, 1, 0), (0, 0, 1)) if direction[0] > 0 else ((0, -1, 0), (0, 0, 1))
            rotation = m.rotationFromAxes(*axes)
        return App.Placement(base, turn.multiply(rotation))

    def build(self, doc):
        body = m.body(doc)
        self.spine = m.sketch(
            doc, "Spine", m.polygon(CORNERS), body, placement=self.spinePlacement()
        )
        self.profile = m.sketch(
            doc, "Square", m.rectangle(-A, -A, A, A), body, placement=self.profilePlacement()
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.spine, [])
        pipe.Transition = self.transition
        self.pipe = pipe
        doc.recompute()
        made = {}
        for name, kind, predicate, mode in (
            ("datum_left_outer", "PartDesign::Plane", self.leftOuter, "FlatFace"),
            ("datum_right_outer", "PartDesign::Plane", self.rightOuter, "FlatFace"),
            ("datum_top_outer", "PartDesign::Plane", self.topOuter, "FlatFace"),
            ("sketch_bottom_inner", "Sketcher::SketchObject", self.bottomInner, "FlatFace"),
            ("point_top_right", "PartDesign::Point", self.topRight, "Vertex"),
        ):
            obj = body.newObject(kind, name)
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            obj.MapMode = mode
            made[name] = (obj, predicate)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pipe, self.names(pipe, self.topFront()))
        fillet.Radius = 0.5
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())
        self.ref("fillet_top_front", fillet, "Base", self.topFront, Filleted(0.5))

    def redraw(self, points, start, direction):
        """Moves the four lines (IDs kept) onto the loop through `points` and the profile to
        the new start."""
        lines = {i: (points[i], points[(i + 1) % 4]) for i in range(4)}
        geometry = self.spine.Geometry
        for i in range(4):  # first out of the way, so no end lands on another line's end
            geometry[i].StartPoint = V(100 + 10 * i, 100, 0)
            geometry[i].EndPoint = V(105 + 10 * i, 105, 0)
        for i, (p, q) in lines.items():
            geometry[i].StartPoint = V(*p, 0)
            geometry[i].EndPoint = V(*q, 0)
        self.spine.Geometry = geometry
        self.profile.Placement = self.profilePlacement(start, direction)

    def setTurn(self, turn):
        self.turn = turn
        self.spine.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()


# FIND. Verdicts on integration 95538c7728 (V2s, Windows): wrong (silent): datum_left_outer,
#  datum_right_outer, datum_top_outer, fillet_top_front, point_top_right, sketch_bottom_inner
# On fork PR 383 round 4 (a leg whose line came from another place renamed): broken (loud): every
#  reference
class RingStartMoved(Ring):
    """The loop drawn from the top-left corner (lines shifted by one: line 0 is now the top
    leg), the profile moved there, normal to +X."""

    def edit(self, doc):
        self.redraw(CORNERS[1:] + CORNERS[:1], (0, HEIGHT), (1, 0))


# FIND. Verdicts on integration 95538c7728 (V2s, Windows): wrong (silent): datum_left_outer,
#  datum_right_outer, datum_top_outer, fillet_top_front, point_top_right, sketch_bottom_inner
# On fork PR 383 round 4 (a leg whose line came from another place renamed): broken (loud): five;
#  guessed-wrong (warned, the solver's tier 3, a class D case): datum_left_outer
class RingStartMovedTwice(Ring):
    """The loop drawn from the top-right corner (lines shifted by two: each line on the
    opposite leg, its twin), the profile moved there, normal to -Z."""

    AXES = ("M3", "E2", "E3")

    def edit(self, doc):
        self.redraw(CORNERS[2:] + CORNERS[:2], (WIDTH, HEIGHT), (0, -1))


# FIND. Verdicts on integration 95538c7728 (V2s, Windows): correct: point_top_right; wrong
#  (silent): datum_left_outer, datum_right_outer, datum_top_outer, fillet_top_front,
#  sketch_bottom_inner
# On fork PR 383 round 4 (a leg whose line came from another place renamed): broken (loud): every
#  reference (point_top_right right -> loud, decision 150 (1))
class RingReversed(Ring):
    """The loop drawn the other way round from the same start: (0, 0) -> (30, 0) -> (30, 20) ->
    (0, 20) -> (0, 0), the profile normal to +X."""

    AXES = ("M3", "E3")

    def edit(self, doc):
        self.redraw([(0, 0), (WIDTH, 0), (WIDTH, HEIGHT), (0, HEIGHT)], (0, 0), (1, 0))


# FIND. Verdicts on integration 95538c7728 (V2s, Windows): wrong (silent): datum_left_outer,
#  datum_right_outer, datum_top_outer, fillet_top_front, point_top_right, sketch_bottom_inner
# On fork PR 383 round 4 (a leg whose line came from another place renamed): broken (loud): every
#  reference
class RingReversedFromOpposite(Ring):
    """The loop drawn the other way round from the opposite corner (30, 20): (30, 20) ->
    (0, 20) -> (0, 0) -> (30, 0) -> (30, 20), the profile normal to -X."""

    AXES = ("M3", "E2", "E3")

    def edit(self, doc):
        self.redraw([(WIDTH, HEIGHT), (0, HEIGHT), (0, 0), (WIDTH, 0)], (WIDTH, HEIGHT), (-1, 0))


# control. Verdicts on integration 95538c7728 (V2s, Windows): correct: datum_left_outer,
#  datum_right_outer, datum_top_outer, fillet_top_front, point_top_right, sketch_bottom_inner
# On fork PR 383 round 4 (a leg whose line came from another place renamed): correct: every
#  reference
class RingMiddleLinesReversed(Ring):
    """Lines 1 and 2 (the top and right legs) drawn the other way, IDs kept; the loop's start
    and the solid stay."""

    AXES = ("M3", "E3")

    def edit(self, doc):
        geometry = self.spine.Geometry
        for i in (1, 2):
            p, q = geometry[i].StartPoint, geometry[i].EndPoint
            geometry[i].StartPoint = V(200, 200 + i, 0)
            geometry[i].EndPoint = V(p)
            geometry[i].StartPoint = V(q)
        self.spine.Geometry = geometry


# control. Verdicts on integration 95538c7728 (V2s, Windows): broken: datum_top_outer,
#  fillet_top_front, point_top_right, sketch_bottom_inner; correct: datum_left_outer,
#  datum_right_outer
# On fork PR 383 round 4 (a leg whose line came from another place renamed): correct:
#  datum_left_outer, datum_right_outer; quiet (warned, re-bound at the same place): datum_top_outer,
#  fillet_top_front, point_top_right, sketch_bottom_inner
class RingLinesSwapped(Ring):
    """The top and bottom legs' lines swap geometry IDs (line 1 drawn on the bottom, (30, 0) ->
    (0, 0); line 3 on the top, (0, 20) -> (30, 20)): the loop is the same, drawn in another
    order."""

    def edit(self, doc):
        geometry = self.spine.Geometry
        for i, (p, q) in ((1, ((300, 0), (300, 5))), (3, ((400, 0), (400, 5)))):
            geometry[i].StartPoint = V(*p, 0)
            geometry[i].EndPoint = V(*q, 0)
        geometry[1].StartPoint = V(WIDTH, 0, 0)
        geometry[1].EndPoint = V(0, 0, 0)
        geometry[3].StartPoint = V(0, HEIGHT, 0)
        geometry[3].EndPoint = V(WIDTH, HEIGHT, 0)
        self.spine.Geometry = geometry


# control. Verdicts on integration 95538c7728 (V2s, Windows): correct: datum_left_outer,
#  datum_right_outer, datum_top_outer, fillet_top_front, point_top_right, sketch_bottom_inner
# On fork PR 383 round 4 (a leg whose line came from another place renamed): correct: every
#  reference
class RingTurned(Ring):
    """The whole model turns 120 degrees about Z."""

    AXES = ("M3", "E7")

    def edit(self, doc):
        self.setTurn(120)
