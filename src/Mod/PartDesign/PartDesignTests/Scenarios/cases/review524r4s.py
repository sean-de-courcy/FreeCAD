# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr403-r4 (Sonnet, ops#524): lone far pieces moved alone, composed with other edits, at
other scales. A Pad (Refine off) from an unattached sketch on the XY plane up to a Part::Feature
shell at z = 10 (SIZE 30 at scale 1): the plate x -10..20, y -10..10 with a rectangular hole and the
hole's fill (B-spline faces), as `review524r1.py` builds it.

CapSlideHoleGrows and CapSlideHoleMoves M break (right -> loud, accepted under decision 120 (4) in
decision 199 (4)'s plate-geometry family, beside `review524r1.py`'s SlideWhilePlateGrows L): the
piece's own up-to face, the fill, is rebuilt with the hole, which can't be told from the piece
moved alone off it.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0


class Base(Scenario):
    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#524"
    FOUND_BY = "review pr403-r4"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    BEFORE = {}
    AFTER = {}
    HOLE = (-1, -2, 1, 2)
    KIND = "face"
    ORDER = (0, 1)
    edited = False

    def S(self, v):
        return v * self.scale

    def P(self, x, y, z=HEIGHT):
        return V(self.S(x), self.S(y), self.S(z))

    def place(self, x, y):
        if self.KIND == "edge":
            return edge(contains=self.P(x, y))
        return face(contains=self.P(x, y))

    def poly(self, points, z=HEIGHT):
        c = [self.P(x, y, z) for x, y in points]
        return Part.makePolygon(c + c[:1])

    def shell(self, hole=None, x1=20):
        hole = hole or self.HOLE
        hx0, hy0, hx1, hy1 = hole
        outer = self.poly([(-10, -10), (x1, -10), (x1, 10), (-10, 10)])
        h = self.poly([(hx0, hy0), (hx0, hy1), (hx1, hy1), (hx1, hy0)])
        plate = (
            Part.Face(Part.Plane(self.P(0, 0), V(0, 0, 1)), [outer, h]).toNurbs().Faces[0]
        )
        fill = Part.Face(self.poly([(hx0, hy0), (hx1, hy0), (hx1, hy1), (hx0, hy1)])).toNurbs().Faces[0]
        faces = [plate, fill]
        return Part.Shell([faces[i] for i in self.ORDER])

    def rect(self, x0, y0, x1, y1):
        return m.rectangle(self.S(x0), self.S(y0), self.S(x1), self.S(y1))

    def moveRect(self, x0, y0, x1, y1):
        m.moveRectangle(self.profile, self.S(x0), self.S(y0), self.S(x1), self.S(y1))

    @staticmethod
    def faceNames(shape):
        return ["Face%d" % (i + 1) for i in range(len(shape.Faces))]

    def buildPad(self, doc, body):
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(doc, "Profile", self.geometry(), body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, self.faceNames(self.plate.Shape))
        self.pad.Refine = False
        doc.recompute()
        return self.pad

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.body = body
        target = self.buildPad(doc, body)
        target = self.later(doc, body, target)
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(target, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(target, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = target

    def later(self, doc, body, target):
        return target

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

    def setPlate(self, shape):
        self.plate.Shape = shape
        self.pad.UpToShape = (self.plate, self.faceNames(shape))


class CapSlideHoleGrows(Base):
    """`MoveAcrossHalf` (rectangle x -3..0, y -0.5..0.5; L on the plate, M on the fill) slid by 0.5
    while the hole grows to the right (x -1..2): L's cap x -2.5..-1, M's cap x -1..0.5."""

    area = "slide-plate-edited"
    AXES = ("M5", "E1")
    REFS = ("L", "M")
    BEFORE = {"L": (-2, 0), "M": (-0.5, 0)}
    AFTER = {"L": (-1.75, 0), "M": (-0.25, 0)}

    def geometry(self):
        return self.rect(-3, -0.5, 0, 0.5)

    def change(self, doc):
        self.moveRect(-2.5, -0.5, 0.5, 0.5)
        self.setPlate(self.shell(hole=(-1, -2, 2, 2)))


class CapSlideShellReordered(Base):
    """The same slide with the up-to shell's faces in the other order (fill first)."""

    area = "slide-plate-reordered"
    AXES = ("M5", "E1")
    REFS = ("L", "M")
    BEFORE = {"L": (-2, 0), "M": (-0.5, 0)}
    AFTER = {"L": (-1.75, 0), "M": (-0.25, 0)}

    def geometry(self):
        return self.rect(-3, -0.5, 0, 0.5)

    def change(self, doc):
        self.moveRect(-2.5, -0.5, 0.5, 0.5)
        self.ORDER = (1, 0)
        self.setPlate(self.shell())


class CapSlideHoleMoves(Base):
    """The slide by 0.5 while the hole moves left by 0.5 (x -1.5..0.5): L's cap x -2.5..-1.5, M's
    cap x -1.5..0.5. The plate is rebuilt with its hole moved (the plate-geometry family: loud is
    accepted, silent wrong is not)."""

    area = "slide-plate-edited"
    AXES = ("M5", "E1")
    REFS = ("L", "M")
    BEFORE = {"L": (-2, 0), "M": (-0.5, 0)}
    AFTER = {"L": (-2.0, 0), "M": (-0.5, 0)}

    def geometry(self):
        return self.rect(-3, -0.5, 0, 0.5)

    def change(self, doc):
        self.moveRect(-2.5, -0.5, 0.5, 0.5)
        self.setPlate(self.shell(hole=(-1.5, -2, 0.5, 2)))


class CapSlideThenTip(Base):
    """`MoveAcrossHalf` slid by 0.5 with a Pocket after the Pad (the Tip): a corner of M's cap is
    cut away (x -0.5..0, y 0..0.5, 2 deep from z = 10). References on the Pocket's shape: L's cap
    x -2.5..-1 and M's cap x -1..0.5 minus the corner."""

    area = "later-feature"
    AXES = ("M5", "E1")
    REFS = ("L", "M")
    BEFORE = {"L": (-2, 0), "M": (-0.75, 0)}
    AFTER = {"L": (-1.75, 0), "M": (-0.75, 0)}

    def geometry(self):
        return self.rect(-3, -0.5, 0, 0.5)

    def later(self, doc, body, target):
        sk = m.sketch(doc, "Corner", self.rect(-0.5, 0, 0, 0.5), body, z=self.S(HEIGHT))
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = sk
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        return pocket

    def change(self, doc):
        self.moveRect(-2.5, -0.5, 0.5, 0.5)


class CapAcrossThenTip(CapSlideThenTip):
    """The same Pad and Pocket; the rectangle moves across the hole (x 0.5..3.5): L's piece is
    gone, M's carries on at x 0.5..1."""

    AFTER = {"L": None, "M": (0.75, 0)}

    def change(self, doc):
        self.moveRect(0.5, -0.5, 3.5, 0.5)


class EdgeSplitsAtHole(Base):
    """A rectangle x -5..-2, y 0..2 (its far bottom edge y = 0 and the side edge x = -5 lone on the
    plate) slid right by 2.5 (x -2.5..0.5): the bottom edge now crosses the hole's left side
    (x = -1), so its far piece splits into one on the plate (x -2.5..-1) and one on the fill. The
    bottom edge's reference follows the plate piece or breaks."""

    area = "edge-splits"
    AXES = ("M5", "E1")
    KIND = "edge"
    REFS = ("B", "S")
    HOLE = (-1, -0.5, 1, 0.5)
    BEFORE = {"B": (-3.5, 0), "S": (-5, 1)}
    AFTER = {"B": (-1.75, 0), "S": (-2.5, 1)}

    def geometry(self):
        return self.rect(-5, 0, -2, 2)

    def change(self, doc):
        self.moveRect(-2.5, 0, 0.5, 2)


class EdgeAcrossHoleBroken(EdgeSplitsAtHole):
    """The same rectangle moved by 5.5 (x 0.5..3.5, y 0..2) past the hole's right side: the
    bottom edge's piece on the plate lies at x 1..3.5, nowhere near the old x -5..-2 piece: the
    bottom edge's reference breaks (or follows nothing)."""

    AFTER = {"B": None, "S": None}

    def change(self, doc):
        self.moveRect(0.5, 0, 3.5, 2)


class CircleMovedOnPlate(Base):
    """A circle r = 5 at the origin padded up to a plain plate (no hole): its far circle is two
    pieces on the one plate face with the same marks (twins, `PRJ,MOD,ORD` counters). The circle
    moves by (1, 0) (geometry kept): the upper and lower halves keep their pieces."""

    area = "ring-twins"
    AXES = ("M5", "E1")
    KIND = "edge"
    REFS = ("U", "D")
    HOLE = (14, 14, 15, 15)
    BEFORE = {"U": (0, 5), "D": (0, -5)}
    AFTER = {"U": (1, 5), "D": (1, -5)}

    def geometry(self):
        return m.circle(0, 0, self.S(5))

    def change(self, doc):
        self.profile.moveGeometry(0, 3, V(self.S(1), 0, 0), True)


class CircleMovedBeyondTwins(CircleMovedOnPlate):
    """The circle moves by (6, 0) (the plate runs to x = 20, so it stays on it)."""

    AFTER = {"U": (6, 5), "D": (6, -5)}

    def change(self, doc):
        self.profile.moveGeometry(0, 3, V(self.S(6), 0, 0), True)


class SwapRects(Base):
    """Two rectangles in one sketch, A (x -6..-4, y -0.5..0.5) and B (x 3..5), their caps both
    alone on the plate (the hole is x -1..1). They swap places by moving the lines: A to x 3..5,
    B to x -6..-4. Each reference follows its own cap or breaks; neither may hold the other's."""

    area = "swap"
    AXES = ("M5", "E1")
    REFS = ("A", "B")
    BEFORE = {"A": (-5, 0), "B": (4, 0)}
    AFTER = {"A": (4, 0), "B": (-5, 0)}

    def geometry(self):
        return self.rect(-6, -0.5, -4, 0.5) + self.rect(3, -0.5, 5, 0.5)

    def change(self, doc):
        m.moveRectangle(self.profile, self.S(3), self.S(-0.5), self.S(5), self.S(0.5), first=0)
        m.moveRectangle(self.profile, self.S(-6), self.S(-0.5), self.S(-4), self.S(0.5), first=4)


class FusedCircleArcsMoved(Base):
    """Fork PR 390's closed-edge twins in the Pad's own result: a Base pad (x -1..10, y -10..10,
    10 high) and a circle r = 5 padded up to a two-face plate (the plate and a small fill far
    away) over it. The Pad's fuse cuts the far circle at the base's wall x = -1: the arcs carry
    `<k>of<n>,MOD,ORD,CLS` places (three of them). References on the arcs at 45 and -45 degrees
    (inside the base's top) and at 180 degrees. The circle moves by (0, 1), its geometry kept."""

    area = "closed-twins"
    AXES = ("M5", "E1")
    KIND = "edge"
    REFS = ("UP", "DN", "LEFT")
    BEFORE = {"UP": (3.5355339, 3.5355339), "DN": (3.5355339, -3.5355339), "LEFT": (-5, 0)}
    AFTER = {"UP": (3.5355339, 4.5355339), "DN": (3.5355339, -2.5355339), "LEFT": (-5, 1)}

    def shell(self, hole=None, x1=20):
        hole = (15, 15, 16, 16)
        return super().shell(hole=hole, x1=20)

    def geometry(self):
        return m.circle(0, 0, self.S(5))

    def buildPad(self, doc, body):
        base = m.sketch(doc, "BaseProfile", self.rect(-1, -10, 10, 10), body)
        basePad = m.pad(body, base, self.S(10), "Base")
        basePad.Refine = False
        doc.recompute()
        return super().buildPad(doc, body)

    def change(self, doc):
        self.profile.moveGeometry(0, 3, V(0, self.S(1), 0), True)


class FusedCircleArcsMovedFar(FusedCircleArcsMoved):
    """The same, the circle moved by (0, 4): the arcs at 45 and -45 degrees move off their old
    places along the circle, the wall x = -1 cuts the circle at other points."""

    AFTER = {"UP": (3.5355339, 7.5355339), "DN": (3.5355339, 0.4644661), "LEFT": (-5, 4)}

    def change(self, doc):
        self.profile.moveGeometry(0, 3, V(0, self.S(4), 0), True)
