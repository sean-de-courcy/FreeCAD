# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2f: review pr390-r2f's probes of the round's change (the twin clause's source
checks for a twin record of two or more, no structural candidate). review390r2er.py's model: a
Pad (Refine off) from an unattached sketch (rectangle x -3..3, y -0.5..0.5) up to a Part::Feature
shell at z = 10 (SIZE 30 at scale 1): the plate x -10..20, y -10..10 with a rectangular hole
x -1..1, y -2..2 and its fill (B-spline faces), so the Pad's far edge y 0.5 comes in pieces L
(x -3..-1), M (the fill) and R (1..3). Pocket circles r 0.3 at z 10 cross L's far edge twice.

The expected element is the crossing the reference held, where it lies after the edit; a crossing
of a deleted circle breaks.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0
D = 0.05**0.5


class Base(Scenario):
    abstract = True
    AXES = ("M5", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2f"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7),)
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {}
    HOLES = ((-1, -2, 1, 2),)
    RECT = (-3, -0.5, 3, 0.5)
    edited = False

    def S(self, v):
        return v * self.scale

    def P(self, x, y, z=HEIGHT):
        return V(self.S(x), self.S(y), self.S(z))

    def place(self, x, y):
        return vertex(self.P(x, y))

    def poly(self, points, z=HEIGHT):
        c = [self.P(x, y, z) for x, y in points]
        return Part.makePolygon(c + c[:1])

    def shell(self):
        outer = self.poly([(-10, -10), (20, -10), (20, 10), (-10, 10)])
        wires = [outer]
        fills = []
        for hx0, hy0, hx1, hy1 in self.HOLES:
            wires.append(self.poly([(hx0, hy0), (hx0, hy1), (hx1, hy1), (hx1, hy0)]))
            fills.append(
                Part.Face(self.poly([(hx0, hy0), (hx1, hy0), (hx1, hy1), (hx0, hy1)]))
                .toNurbs()
                .Faces[0]
            )
        plate = Part.Face(Part.Plane(self.P(0, 0), V(0, 0, 1)), wires).toNurbs().Faces[0]
        return Part.Shell([plate] + fills)

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(
            doc, "Profile", m.rectangle(*[self.S(v) for v in self.RECT]), body
        )
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.profile
        pad.Type = "UpToShape"
        pad.UpToShape = (self.plate, ["Face%d" % (i + 1) for i in range(len(self.plate.Shape.Faces))])
        pad.Refine = False
        doc.recompute()
        self.hole = m.sketch(
            doc,
            "Circles",
            [m.circle(self.S(x), self.S(y), self.S(0.3)) for x, y in self.CIRCLES],
            body,
            z=self.S(HEIGHT),
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(pocket, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(pocket, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = pocket

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            if self.AFTER[name] is None:
                return BROKEN
            return self.place(*self.AFTER[name])

        return expect

    def redrawCircle(self, index, x, y):
        self.hole.delGeometry(index)
        self.hole.addGeometry(m.circle(self.S(x), self.S(y), self.S(0.3)), False)

    def moveCircle(self, index, x, y):
        geometry = self.hole.Geometry
        geometry[index].Center = V(self.S(x), self.S(y), 0)
        self.hole.Geometry = geometry

    def redrawFarLine(self):
        geometry = self.profile.Geometry
        far = [
            i
            for i, g in enumerate(geometry)
            if abs(g.StartPoint.y - self.S(0.5)) < 1e-9 and abs(g.EndPoint.y - self.S(0.5)) < 1e-9
        ][0]
        line = Part.LineSegment(geometry[far].StartPoint, geometry[far].EndPoint)
        self.profile.delGeometry(far)
        self.profile.addGeometry(line, False)

    def edit(self, doc):
        self.change(doc)
        self.edited = True


def moved(dx):
    return {"first": (-2 + dx - D, 0.5), "second": (-2 + dx + D, 0.5)}


class R2fPRedrawnSmallMove(Base):
    """The circle deleted and drawn again 0.05 to the right (a new geometry ID): both crossings
    stay on L, renamed, within tier 3's strict reach of their saved places."""

    AFTER = moved(0.05)

    def change(self, doc):
        self.redrawCircle(0, -1.95, 0.7)


class R2fPRedrawnFarMove(Base):
    """The circle deleted and drawn again 0.6 to the right: both crossings stay on L (x -1.62 and
    -1.18), renamed, beyond tier 3's strict reach (G2's wide reach)."""

    AFTER = moved(0.6)

    def change(self, doc):
        self.redrawCircle(0, -1.4, 0.7)


class R2fPMovedFarControl(Base):
    """The control: the circle moved 0.6 to the right, its geometry ID kept."""

    AFTER = moved(0.6)

    def change(self, doc):
        self.moveCircle(0, -1.4, 0.7)


class R2fPFarLineRedrawnSmallMove(Base):
    """The Pad's far line drawn again where it was (a new geometry ID) and the circle moved 0.05:
    the crossings are renamed, both still on L, near their saved places."""

    AFTER = moved(0.05)

    def change(self, doc):
        self.redrawFarLine()
        self.moveCircle(0, -1.95, 0.7)


class R2fPFarLineRedrawnFarMove(Base):
    """The Pad's far line drawn again where it was and the circle moved 0.6 (G2's reach)."""

    AFTER = moved(0.6)

    def change(self, doc):
        self.redrawFarLine()
        self.moveCircle(0, -1.4, 0.7)


class R2fPSiblingIntoVacated(Base):
    """Circles A (-2, 0.7) and B (2, 0.7) in one sketch, one Pocket. A deleted, B moved to
    (-1.97, 0.7): B's crossings lie 0.03 from A's old ones, an order group of the saved size at
    the saved offsets. A is gone: both break."""

    CIRCLES = ((-2, 0.7), (2, 0.7))
    AFTER = {"first": None, "second": None}

    def change(self, doc):
        self.hole.delGeometry(0)
        self.moveCircle(0, -1.97, 0.7)


class R2fPSiblingIntoVacatedFar(R2fPSiblingIntoVacated):
    """As R2fPSiblingIntoVacated with B moved to (-1.6, 0.7) (G2's reach)."""

    def change(self, doc):
        self.hole.delGeometry(0)
        self.moveCircle(0, -1.6, 0.7)


class R2fPThinCrossingsToNearEdge(Base):
    """A thin member: the Pad's rectangle y 0.3..0.5 (0.2 wide). The circle (-2, 0.7) crosses the
    far edge (y 0.5) at -2 -+ D; it moves to (-2, 0.1), where it crosses the near edge (y 0.3) at
    the same x, 0.2 from the old crossings, and the far edge no more. The far edge's crossings are
    gone: both break (the near edge's crossings are other elements, of another edge)."""

    RECT = (-3, 0.3, 3, 0.5)
    AFTER = {"first": None, "second": None}

    def change(self, doc):
        self.moveCircle(0, -2, 0.1)


class R2fPThinCrossingsToNearEdgeRedrawn(R2fPThinCrossingsToNearEdge):
    """As R2fPThinCrossingsToNearEdge with the circle deleted and drawn again at (-2, 0.1)."""

    def change(self, doc):
        self.redrawCircle(0, -2, 0.1)


class R2fPThinSiblingOnNearEdge(Base):
    """The thin member (y 0.3..0.5); circles A (-2, 0.7) on the far edge and B (-2, 0.1) on the
    near edge, one sketch, one Pocket. A deleted: B's crossings sit 0.2 from A's old ones, at the
    saved offsets. A is gone: both break."""

    RECT = (-3, 0.3, 3, 0.5)
    CIRCLES = ((-2, 0.7), (-2, 0.1))
    AFTER = {"first": None, "second": None}

    def change(self, doc):
        self.hole.delGeometry(0)
