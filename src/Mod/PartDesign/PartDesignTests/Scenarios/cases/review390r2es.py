# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2f: review pr390-r2es's cases (Sonnet, the fix-trace review of round 2e at
e0871d64fc), review390r2e.py's model with reopen and composed steps. Round 2e: review pr403-r5's
(Opus, A1h) crossing cases, which found PR 390's fourth silent: a far edge piece's two crossings
saved as twins, one left on the piece after an edit, and tier 3's nearest pick of a corner that is
no twin of it. The model: a Pad (Refine off) from an
unattached sketch on the XY plane up to a Part::Feature shell at z = 10 (SIZE 30 at scale 1): the
plate x -10..20, y -10..10 with a rectangular hole and its fill (B-spline faces), as
`review524r4s.py` builds it.

The expected element is the piece the reference held, where it lies after the edit; a gone twin
breaks.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Reopens, Scenario, edge, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0


class Base(Scenario):
    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2es"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    BEFORE = {}
    AFTER = {}
    HOLES = ((-1, -2, 1, 2),)
    KIND = "face"
    EDGE_Y = 0.5
    edited = False

    def S(self, v):
        return v * self.scale

    def P(self, x, y, z=HEIGHT):
        return V(self.S(x), self.S(y), self.S(z))

    def place(self, x, y):
        if self.KIND == "edge":
            return edge(contains=self.P(x, self.EDGE_Y))
        return face(contains=self.P(x, y))

    def poly(self, points, z=HEIGHT):
        c = [self.P(x, y, z) for x, y in points]
        return Part.makePolygon(c + c[:1])

    def shell(self, holes=None, shift=0.0):
        holes = holes or self.HOLES
        outer = self.poly([(-10, -10), (20, -10), (20, 10), (-10, 10)])
        wires = [outer]
        fills = []
        for hx0, hy0, hx1, hy1 in holes:
            wires.append(self.poly([(hx0, hy0), (hx0, hy1), (hx1, hy1), (hx1, hy0)]))
            fills.append(
                Part.Face(self.poly([(hx0, hy0), (hx1, hy0), (hx1, hy1), (hx0, hy1)]))
                .toNurbs()
                .Faces[0]
            )
        plate = Part.Face(Part.Plane(self.P(0, 0), V(0, 0, 1)), wires).toNurbs().Faces[0]
        shell = Part.Shell([plate] + fills)
        if shift:
            shell.translate(V(self.S(shift), 0, 0))
        return shell

    def rect(self, x0, y0, x1, y1):
        return m.rectangle(self.S(x0), self.S(y0), self.S(x1), self.S(y1))

    def moveRect(self, x0, y0, x1, y1):
        m.moveRectangle(self.profile, self.S(x0), self.S(y0), self.S(x1), self.S(y1))

    @staticmethod
    def faceNames(shape):
        return ["Face%d" % (i + 1) for i in range(len(shape.Faces))]

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.body = body
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(doc, "Profile", self.geometry(), body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, self.faceNames(self.plate.Shape))
        self.pad.Refine = False
        doc.recompute()
        target = self.later(doc, body, self.pad)
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(target, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(target, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = target

    def later(self, doc, body, target):
        return target

    def geometry(self):
        return self.rect(-3, -0.5, 3, 0.5)

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            if self.AFTER[name] is None:
                return BROKEN
            return self.place(*self.AFTER[name])

        return expect

    def edit(self, doc):
        self.change(doc)
        self.edited = True



class Crossing(Base):
    """The far-edge crossing model of review390r2e.py (see there): a Pocket circle r 0.3 crosses
    the far edge of L twice (`first` at x -2-D, `second` at -2+D); the edit moves the circle to
    (-1.1, 0.7) and slides the Pad's rectangle to x -2.5..0. Objects are fetched by name, so a
    reopen step may come first."""

    abstract = True
    area = "crossing-twin-gone"
    AXES = ("M5", "E1")
    REFS = ("first", "second")
    D = 0.05**0.5
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {"first": (-1.1 - D, 0.5), "second": None}

    def place(self, x, y):
        return vertex(self.P(x, y))

    def later(self, doc, body, target):
        hole = m.sketch(
            doc, "Circle", m.circle(self.S(-2), self.S(0.7), self.S(0.3)), body, z=self.S(HEIGHT)
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = hole
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        return pocket

    def moveRect(self, x0, y0, x1, y1):
        m.moveRectangle(self.doc.getObject("Profile"), self.S(x0), self.S(y0), self.S(x1), self.S(y1))

    def moveCircle(self):
        hole = self.doc.getObject("Circle")
        geometry = hole.Geometry
        geometry[0].Center = V(self.S(-1.1), self.S(0.7), 0)
        hole.Geometry = geometry

    def change(self, doc):
        self.moveRect(-2.5, -0.5, 0, 0.5)
        self.moveCircle()


class R2esSlidReopenedFirst(Reopens, Crossing):
    """Saved, closed, opened, then the slide and the move (review390r2e's Slid case after a reopen):
    the record must survive the file; `first` breaks."""

    steps = ("reopen", "edit")


class R2esSlidThenReopen(Reopens, Crossing):
    """The slide and the move, then saved, closed and opened: the break stays a break."""

    steps = ("edit", "reopen")


class R2esSlidTwoStepsCircleFirst(Crossing):
    """The circle moves first (L x -3..-1: `first` is crossed once), then the rectangle slides to
    x -2.5..0 (the second step): composed edits, each recomputed. After the first step `first` is
    the lone crossing on L (its old element), after the second it is still on L (x -2.5..-1)."""

    steps = ("circle", "slide")
    AFTER = {"first": (-1.1 - Crossing.D, 0.5), "second": None}

    def circle(self, doc):
        self.moveCircle()

    def slide(self, doc):
        self.moveRect(-2.5, -0.5, 0, 0.5)

    def expectation(self, name):
        def expect():
            if getattr(self, "stepName", None) not in ("circle", "slide"):
                return self.place(*self.BEFORE[name])
            if self.AFTER[name] is None:
                return BROKEN
            return self.place(*self.AFTER[name])

        return expect

    def edit(self, doc):
        pass
