# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2f: review pr390-r2fs's cases (Sonnet, the fix-trace review of round 2f's
literal stop: a saved twin's tier 3 and wide-reach picks run the twin clause's source checks).
Two circles of one sketch, one Pocket: A moves off its crossings of the far edge piece L, B comes
to A's old crossings (`R2fsP*`, `R2fsE*` with references on the pocket's vertical edges,
`R2fsDeletedA`), A redrawn (a new geometry ID: the stop's cost, `R2fsRedrawnA*`), and a thin strip
crossed on its other edge (`R2fsThinStrip*`). Built on review390r2er.py's model: a Pad (Refine off)
from an unattached sketch on the XY plane up to a Part::Feature shell at z = 10 (SIZE 30 at scale
1): the plate x -10..20, y -10..10 with a rectangular hole and its fill (B-spline faces), as
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
    FOUND_BY = "review pr390-r2fs"
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


class EdgeHoles(Holes):
    """Holes whose references are the pocket wall's vertical edges at the crossings (edge twins)."""

    abstract = True

    def place(self, x, y):
        return edge(contains=self.P(x, y, HEIGHT - 1))


class TwoCircles(Holes):
    """Two circles r 0.3 in one sketch, one Pocket: A at (-2, 0.7) crosses L's far edge (y 0.5,
    x -3..-1) at -2 -+ D. A is moved off the pad; B moves to A's old place plus SHIFT. Both of A's
    crossings are gone (nothing of A's crossings is left): the only right answer is a break."""

    abstract = True
    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7), (2, 0.7))
    SHIFT = 0.0
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {"first": None, "second": None}

    @property
    def MOVED(self):
        return ((0, 5), (-2 + self.SHIFT, 0.7))


class R2fsP0(TwoCircles):
    SHIFT = 0.0


class R2fsP05(TwoCircles):
    SHIFT = 0.05


class R2fsP10(TwoCircles):
    SHIFT = 0.1


class R2fsP30(TwoCircles):
    SHIFT = 0.3


class R2fsP60(TwoCircles):
    SHIFT = 0.6


class R2fsP100(TwoCircles):
    SHIFT = 1.0


class R2fsE10(EdgeHoles, TwoCircles):
    SHIFT = 0.1


class R2fsE0(EdgeHoles, TwoCircles):
    SHIFT = 0.0


class R2fsE30(EdgeHoles, TwoCircles):
    SHIFT = 0.3


class R2fsP10TwoPockets(TwoCircles):
    SHIFT = 0.1
    TWO_POCKETS = True


class R2fsDeletedA(Holes):
    """A is deleted from the sketch; B moves to A's old place + 0.1."""

    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7), (2, 0.7))
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {"first": None, "second": None}

    def change(self, doc):
        for hole in self.holes:
            hole.delGeometry(0)
            g = hole.Geometry
            g[0].Center = V(self.S(-1.9), self.S(0.7), 0)
            hole.Geometry = g


class R2fsRedrawnA(Holes):
    """A is deleted and drawn again where it was (a new geometry ID): policy D re-binds it, or
    breaks; the crossings are where they were."""

    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7), (2, 0.7))
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}

    def change(self, doc):
        for hole in self.holes:
            hole.delGeometry(0)
            hole.addGeometry(m.circle(self.S(-2), self.S(0.7), self.S(0.3)), False)


class R2fsRedrawnAOnly(Holes):
    """One circle, drawn again where it was: its crossings, named anew."""

    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7),)
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}

    def change(self, doc):
        for hole in self.holes:
            hole.delGeometry(0)
            hole.addGeometry(m.circle(self.S(-2), self.S(0.7), self.S(0.3)), False)


class R2fsRedrawnAMoved(Holes):
    """One circle, drawn again 0.15 to the right, a crossing each side still on L."""

    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7),)
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {"first": (-1.85 - D, 0.5), "second": (-1.85 + D, 0.5)}

    def change(self, doc):
        for hole in self.holes:
            hole.delGeometry(0)
            hole.addGeometry(m.circle(self.S(-1.85), self.S(0.7), self.S(0.3)), False)


class R2fsThinStrip(Holes):
    """The Pad's strip is 0.2 wide (y -0.1..0.1): edges E1 (y 0.1) and E2 (y -0.1), x -3..-1 on
    the left piece. One circle r 0.3 at (-2, YA) crosses E1 at -2 -+ D (YA 0.3); the edit moves it
    to (-2, YB) = (-2, -0.3), where it crosses E2 at -2 -+ D and E1 not at all. The reference held
    a crossing of E1, which is gone: it breaks (the crossing of E2 is another edge's, 0.2 away)."""

    abstract = True
    REFS = ("first", "second")
    CIRCLES = ((-2, 0.3),)
    MOVED = ((-2, -0.3),)
    EDGE_Y = 0.1
    BEFORE = {"first": (-2 - D, 0.1), "second": (-2 + D, 0.1)}
    AFTER = {"first": None, "second": None}

    def geometry(self):
        return self.rect(-3, -0.1, 3, 0.1)


class R2fsThinStripMovedOver(R2fsThinStrip):
    pass


class R2fsThinStripLowerFirst(R2fsThinStrip):
    """Same, the references on E2's crossings and the circle moved from (-2, -0.3) to (-2, 0.3)."""

    CIRCLES = ((-2, -0.3),)
    MOVED = ((-2, 0.3),)
    BEFORE = {"first": (-2 - D, -0.1), "second": (-2 + D, -0.1)}


class R2fsThinStripSmall(R2fsThinStrip):
    """Strip 0.2 wide but the circle moved less: (-2, 0.3) -> (-2, -0.15): crosses E2 at -2 -+
    sqrt(0.09 - 0.0025), E1 not (circle top at y 0.15 > 0.1: it does cross E1 at -2 -+ 0.283).
    Both edges are crossed; both of the old crossings of E1 stay, moved: control."""

    MOVED = ((-2, -0.05),)
    AFTER = {"first": (-2 - (0.09 - 0.0225) ** 0.5, 0.1), "second": (-2 + (0.09 - 0.0225) ** 0.5, 0.1)}


class R2fsThinStripTwoCircles(R2fsThinStrip):
    """Two circles: A (-2, 0.3) crossing E1, B (-1.5, -0.3) crossing E2 (at -1.5 -+ D). The edit:
    A moves away off the strip (-2, 5), B to (-2, -0.3): E2's crossings at -2 -+ D, the E1 ones
    gone, with another circle's source."""

    CIRCLES = ((-2, 0.3), (-1.5, -0.3))
    MOVED = ((-2, 5), (-2, -0.3))
