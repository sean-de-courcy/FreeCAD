# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2f: review pr390-r2e's cases (Opus, the fix-trace review of round 2e's literal
stop), which found PR 390's fifth silent, R2eRSecondHoleTakesPlace: another circle's crossing put
0.1 from the old one, an order group of the saved size at the saved offset, taken by tier 3. Built
on review390r2e.py's model. Round 2e: review pr403-r5's (Opus, A1h) crossing cases, which found
PR 390's fourth silent: a far edge piece's two crossings saved as twins, one left on the piece
after an edit, and tier 3's nearest pick of a corner that is no twin of it. The model: a Pad
(Refine off) from an
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
    AXES = ("M5", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2e"
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



D = 0.05**0.5


class Holes(Base):
    abstract = True
    CIRCLES = ((-2, 0.7),)
    MOVED = ((-1.1, 0.7),)
    TWO_POCKETS = False

    def place(self, x, y):
        return vertex(self.P(x, y))

    def later(self, doc, body, target):
        self.holes = []
        groups = [self.CIRCLES] if not self.TWO_POCKETS else [(c,) for c in self.CIRCLES]
        for i, group in enumerate(groups):
            hole = m.sketch(
                doc,
                "Circle%d" % i,
                [m.circle(self.S(x), self.S(y), self.S(0.3)) for x, y in group],
                body,
                z=self.S(HEIGHT),
            )
            pocket = body.newObject("PartDesign::Pocket", "Pocket%d" % i)
            pocket.Profile = hole
            pocket.Type = 0
            pocket.Length = self.S(2)
            pocket.Refine = False
            doc.recompute()
            self.holes.append(hole)
            target = pocket
        return target

    def moveCircles(self):
        k = 0
        for hole in self.holes:
            geometry = hole.Geometry
            for i in range(len(geometry)):
                x, y = self.MOVED[k]
                k += 1
                geometry[i].Center = V(self.S(x), self.S(y), 0)
            hole.Geometry = geometry

    def change(self, doc):
        self.moveCircles()


class R2eRSecondHoleTakesPlace(Holes):
    """Two circles r 0.3 in one sketch, one Pocket: A at (-2, 0.7) crosses L's far edge (y 0.5,
    x -3..-1) at -2 -+ D, B at (2, 0.7) crosses R's. One edit: A moves to (-1.1, 0.7) (one crossing
    left on L at -1.1 - D, its other one on the fill's piece), B moves to (-1.9, 0.7), its crossings
    on L at -1.9 -+ D, 0.1 from A's old ones. A's second crossing has no successor on L: it breaks;
    B's crossing 0.1 away is another circle's (an unrelated order group of the saved size, whose
    offset matches the saved one)."""

    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7), (2, 0.7))
    MOVED = ((-1.1, 0.7), (-1.9, 0.7))
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {"first": (-1.1 - D, 0.5), "second": None}


class R2eRSecondHoleTakesPlaceTwoPockets(R2eRSecondHoleTakesPlace):
    """R2eRSecondHoleTakesPlace with B in its own sketch and Pocket (another maker)."""

    TWO_POCKETS = True


class R2eRSmallMoveCountChanges(Holes):
    """One circle r 0.3 at (-1.3, 0.7): its crossings of L's far edge at -1.3 -+ D, both on L
    (x -3..-1). It moves 0.1 to (-1.2, 0.7): first at -1.2 - D stays on L, second (-1.2 + D) goes
    to the fill's piece and breaks. The control for the redrawn variant below."""

    REFS = ("first", "second")
    CIRCLES = ((-1.3, 0.7),)
    MOVED = ((-1.2, 0.7),)
    BEFORE = {"first": (-1.3 - D, 0.5), "second": (-1.3 + D, 0.5)}
    AFTER = {"first": (-1.2 - D, 0.5), "second": None}


class R2eRSmallMoveCountChangesTopRedrawn(R2eRSmallMoveCountChanges):
    """R2eRSmallMoveCountChanges while the Pad's far line (y 0.5) is drawn again where it was (a
    new geometry ID, policy D's redraw), in the same edit: first's crossing is renamed and lone,
    0.1 from its saved place."""

    def change(self, doc):
        geometry = self.profile.Geometry
        far = [i for i, g in enumerate(geometry) if abs(g.StartPoint.y - self.S(0.5)) < 1e-9
               and abs(g.EndPoint.y - self.S(0.5)) < 1e-9][0]
        line = Part.LineSegment(geometry[far].StartPoint, geometry[far].EndPoint)
        self.profile.delGeometry(far)
        self.profile.addGeometry(line, False)
        self.moveCircles()
