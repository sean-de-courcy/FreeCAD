# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6h (fork PR 383, round 6's third fix, 5fe2ddbea7): where a frame of the profile
turned, a closed spine's start by its lines' names is taken where a frame carries the stored start
and its next vertex exactly to the names' start and the next vertex of their order.

Aimed at a spine of two edges, where the next vertex is the same for both ways round: the carry
checks the start and the chord to the next vertex, not which edge the way runs along.

The lens: two arcs (B-splines) in the XZ plane between A = (0, 0, 0) and C = (0, 0, 30), arc 0 from A
up through (b, 0, 15), arc 1 back down through (-b, 0, 15), b = 11.51 (sketch x = global X, sketch
y = global Z). The profile: a 2 x 2 square in the XY plane centred on A. The spine lies in y = 0,
so each leg's front and back sides are planar faces at y = -1 and y = 1. The references: those
four faces, each at its place (the right or left leg) on the edited model, held by datum points at
their centres of mass (the right and left front faces share a plane: a datum plane on either is the
same)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


class Lens(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6h"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    TRANSITION = "Transformed"
    REFS = ("right_front", "left_front", "right_back", "left_back")
    bulge = 11.51
    turn = 0  # the whole model's turn about Z (through A), degrees

    def rot(self):
        return App.Rotation(V(0, 0, 1), self.turn)

    def arcs(self, right, left):
        """Arc 0, up on x > 0 (bulge `right`), and arc 1, down on x < 0 (bulge `left`)."""
        h, r, l = self.s(30), self.s(right), self.s(left)
        up = Part.ArcOfCircle(V(0, 0, 0), V(r, h / 2, 0), V(0, h, 0)).toBSpline()
        down = Part.ArcOfCircle(V(0, h, 0), V(-l, h / 2, 0), V(0, 0, 0)).toBSpline()
        return up, down

    def side(self, sign, y):
        def predicate():
            return face(
                "plane",
                normal=self.rot().multVec(V(0, y, 0)),
                contains=self.rot().multVec(
                    V(sign * self.s(self.bulge), y * self.s(1), self.s(15))
                ),
            )

        return predicate

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        up, down = self.arcs(self.bulge, self.bulge)
        self.path = m.sketch(doc, "Path", [up, down], body, placement=XZ)
        one = self.s(1)
        self.profile = m.sketch(doc, "Profile", m.rectangle(-one, -one, one, one), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.Transition = self.TRANSITION
        pipe.Refine = False
        self.pipe = pipe
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        kinds = {
            "right_front": self.side(1, -1),
            "left_front": self.side(-1, -1),
            "right_back": self.side(1, 1),
            "left_back": self.side(-1, 1),
        }
        made = {}
        for name in self.REFS:
            predicate = kinds[name]
            obj = body.newObject("PartDesign::Point", name)
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            obj.MapMode = "CenterOfMass"
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    # ---- edits
    def setArcs(self, traded):
        """The lens at self.bulge; `traded`: arc 0 (id 0) is the left arc, drawn from A up, and
        arc 1 the right one, drawn from C down (the ids kept, each arc moved to the other's place)."""
        h, b = self.s(30), self.s(self.bulge)
        if traded:
            first = Part.ArcOfCircle(V(0, 0, 0), V(-b, h / 2, 0), V(0, h, 0)).toBSpline()
            second = Part.ArcOfCircle(V(0, h, 0), V(b, h / 2, 0), V(0, 0, 0)).toBSpline()
        else:
            first, second = self.arcs(self.bulge, self.bulge)
        g = self.path.Geometry
        for curve, new in ((g[0], first), (g[1], second)):
            # rebuilt in place: the geometry's id (its Tag) kept
            curve.buildFromPolesMultsKnots(
                new.getPoles(),
                new.getMultiplicities(),
                new.getKnots(),
                new.isPeriodic(),
                new.Degree,
                new.getWeights(),
            )
        self.path.Geometry = g

    def turnModel(self, degrees):
        """The path's and the profile's placements turned `degrees` about Z through A."""
        self.turn = degrees
        self.path.Placement = App.Placement(V(0, 0, 0), self.rot().multiply(XZ.Rotation))
        self.profile.Placement = App.Placement(V(0, 0, 0), self.rot())

    def reparameteriseProfile(self, degrees):
        """The profile's placement turned `degrees` about its normal and its lines drawn at the
        sketch coordinates turned back: the same square in the body, line for line (its placement
        frame turns, its geometry frame doesn't)."""
        back = App.Rotation(V(0, 0, 1), -degrees)
        g = self.profile.Geometry
        for line in g:
            s, e = back.multVec(V(line.StartPoint)), back.multVec(V(line.EndPoint))
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), degrees))


class LensTradedWidened(Lens):
    """Control: the two arcs trade places (ids kept: arc 0 now the left arc, from A up) and the lens
    widens to b = 14, in one recompute; no frame of the profile turns. The references stay at their
    places."""

    def edit(self, doc):
        self.bulge = 14
        self.setArcs(True)


class LensProfileReparameterisedWidened(Lens):
    """Control: the profile reparameterised (placement turned 90 degrees, its lines turned back: the
    same square, line for line) and the lens widened to b = 14, in one recompute, the arcs kept.
    The references stay at their places."""

    AXES = ("M3", "E2", "E3")

    def edit(self, doc):
        self.reparameteriseProfile(90)
        self.bulge = 14
        self.setArcs(False)


class LensTradedWidenedProfileReparameterised(Lens):
    """LensTradedWidened with the profile reparameterised (placement turned 90 degrees, its lines
    turned back: the same square in the body, line for line) in the same recompute. The placement
    frame turned about the profile's normal through A, which carries the stored start A and its
    next vertex C onto themselves; the names put the start at arc 0's start, A, the next vertex C,
    so the carry agrees, and the way goes along arc 0, now the left arc. The references stay at
    their places."""

    def edit(self, doc):
        self.reparameteriseProfile(90)
        self.bulge = 14
        self.setArcs(True)


class LensTradedWidenedProfileReparameterised180(LensTradedWidenedProfileReparameterised):
    """LensTradedWidenedProfileReparameterised with the placement turned 180 degrees."""

    def edit(self, doc):
        self.reparameteriseProfile(180)
        self.bulge = 14
        self.setArcs(True)


class LensTradedProfileReparameterised(Lens):
    """The arcs traded (ids kept) and the profile reparameterised by 90 degrees, the lens kept at
    b = 11.51: the spine lies in place in the body (closedInPlace), so the record pairs by place."""

    def edit(self, doc):
        self.reparameteriseProfile(90)
        self.setArcs(True)


class LensTurnedTradedWidened(Lens):
    """The whole model turned 120 degrees about Z (through A, the path's and the profile's
    placements), the arcs traded (ids kept) and the lens widened to b = 14, in one recompute. Both
    profile frames turned about the profile's normal through A, which carries A and C onto
    themselves. The references follow the turn, at their places."""

    AXES = ("M3", "E7", "E2", "E3")
    degrees = 120

    def edit(self, doc):
        self.turnModel(self.degrees)
        self.bulge = 14
        self.setArcs(True)


class LensTurned30TradedWidened(LensTurnedTradedWidened):
    """LensTurnedTradedWidened turned 30 degrees."""

    degrees = 30


class LensTurnedWidened(LensTurnedTradedWidened):
    """Control: LensTurnedTradedWidened with the arcs kept at their places (no trade)."""

    def edit(self, doc):
        self.turnModel(self.degrees)
        self.bulge = 14
        self.setArcs(False)
