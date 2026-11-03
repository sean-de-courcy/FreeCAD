# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2e: review pr403-r5's (Opus, A1h) crossing cases, which found PR 390's fourth
silent: a far edge piece's two crossings saved as twins, one left on the piece after an edit, and
tier 3's nearest pick of a corner that is no twin of it. The model: a Pad (Refine off) from an
unattached sketch on the XY plane up to a Part::Feature shell at z = 10 (SIZE 30 at scale 1): the
plate x -10..20, y -10..10 with a rectangular hole and its fill (B-spline faces), as
`review524r4s.py` builds it.

The expected element is the piece the reference held, where it lies after the edit; a gone twin
breaks.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0


class Base(Scenario):
    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr403-r5"
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


class R2eCrossingTwinGoneOnFarEdge(Base):
    """A crossing vertex of a far edge piece (the twin crossings of one edge, PR 390's literal
    stop): the Pad as in review403r5o.py's TwinGoneLeftSlides, unedited; a Pocket (the Tip, 2
    deep from z = 10) of a
    circle r 0.3 at (-2, 0.7) (its seam off the edge) crosses L's far edge (y = 0.5) twice, at
    x -2 -+ D (D = sqrt(0.05)). The circle moves to (-1.1, 0.7): L (x -3..-1) is crossed once, at
    -1.1 - D, the crossing on the side the edge comes from; the other one has no successor on L
    (the circle's other crossing is now on the fill's piece, at -1.1 + D)."""

    area = "crossing-twin-gone"
    AXES = ("M5", "E1")
    REFS = ("first", "second")
    D = 0.05**0.5
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {"first": (-1.1 - D, 0.5), "second": None}

    def place(self, x, y):
        return vertex(self.P(x, y))

    def later(self, doc, body, target):
        self.hole = m.sketch(
            doc, "Circle", m.circle(self.S(-2), self.S(0.7), self.S(0.3)), body, z=self.S(HEIGHT)
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        return pocket

    def moveCircle(self):
        geometry = self.hole.Geometry
        geometry[0].Center = V(self.S(-1.1), self.S(0.7), 0)
        self.hole.Geometry = geometry

    def change(self, doc):
        self.moveCircle()


class R2eCrossingTwinGoneOnFarEdgeAndSlid(R2eCrossingTwinGoneOnFarEdge):
    """R2eCrossingTwinGoneOnFarEdge while the Pad's rectangle also slides to x -2.5..0 (R gone too,
    L x -2.5..-1): L is crossed once, at -1.1 - D."""

    def change(self, doc):
        self.moveRect(-2.5, -0.5, 0, 0.5)
        self.moveCircle()
