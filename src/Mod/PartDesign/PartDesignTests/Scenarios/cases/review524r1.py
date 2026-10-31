# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prA1c-r1 (ops#524): attacks on N1 (a lone far piece slid within its up-to face), N2
(the maker of a piece passed on by a later feature) and the "left its face" break.

A Pad (Refine off) from an unattached sketch on the XY plane up to a `Part::Feature` shell at
z = 10: a plate x -10..20, y -10..10 with a rectangular hole, and the hole's fill (B-spline faces).
Datum points (centre of mass) on far cap pieces.
- `UArmSwapRedraw`: a U profile in a wide hole x -5..5, y -2..2; only its left arm's tip
  (x -4..-3, y 2..3) reaches the plate (L, alone on it), the rest lies on the fill (M). The sketch
  is redrawn: the left arm shortened to y 1.5, the right arm lengthened to y 3. L's piece is gone
  (its arm no longer reaches the plate); the right arm's tip (x 3..4, y 2..3) is another piece,
  alone on the plate, and the straight path from L's place to it runs above the hole, on the plate.
- `MirrorCopyAcrossHole`: `MoveAcrossHalf` with the hole at y 2..4 and a Mirrored of the Pad across
  the XZ plane as the Tip: the copies of L and M lie at y -3.5..-2.5, where the plate has no hole.
  The rectangle moves across the hole; L's piece and its copy are gone.
- `SlideWhilePlateGrows`: `MoveAcrossHalf`'s rectangle moves by 0.5 (L and M slide along their
  faces, overlapping their old places) while the plate's outer border grows from x 20 to 25.
- `UTranslatedOverSteppedHole` (PLAN decision 202): `UArmSwapRedraw`'s U moved rigidly, over a
  hole whose top steps; the right arm's tip is reborn on the plate.

Decision 202 took back decision 182's N1 (a lone piece slid within its up-to face keeps its name):
the face and the path from the old place can't tell a slid piece from another part of the profile
reborn alone on the same face. Both U cases must break L; `SlideWhilePlateGrows` breaks L too
(decision 199 (4), accepted right -> loud).
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0


def outer(z, x0=-10, y0=-10, x1=20, y1=10):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.makePolygon(c + c[:1])


def rectFace(x0, y0, x1, y1, z):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.Face(Part.makePolygon(c + c[:1])).toNurbs().Faces[0]


def holeShell(z, hole, x1=20):
    hx0, hy0, hx1, hy1 = hole
    h = [V(hx0, hy0, z), V(hx0, hy1, z), V(hx1, hy1, z), V(hx1, hy0, z)]
    plate = (
        Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), [outer(z, x1=x1), Part.makePolygon(h + h[:1])])
        .toNurbs()
        .Faces[0]
    )
    return Part.Shell([plate, rectFace(hx0, hy0, hx1, hy1, z)])


class Base(Scenario):
    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#524"
    FOUND_BY = "review prA1c-r1"
    TIER = "F"
    BEFORE = {}
    AFTER = {}
    HOLE = (-1, -2, 1, 2)
    mirror = False

    def place(self, x, y):
        return face(contains=V(x, y, HEIGHT))

    def shell(self):
        return holeShell(HEIGHT, self.HOLE)

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
        target = self.pad
        if self.mirror:
            mirrored = doc.addObject("PartDesign::Mirrored", "Mirrored")
            mirrored.Originals = [self.pad]
            mirrored.MirrorPlane = (m.originFeature(body, "XZ_Plane"), [""])
            mirrored.Refine = False
            body.addObject(mirrored)
            doc.recompute()
            target = mirrored
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(target, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(target, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = target

    @staticmethod
    def faceNames(shape):
        return ["Face%d" % (i + 1) for i in range(len(shape.Faces))]

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


class UArmSwapRedraw(Base):
    """A U in a wide hole; the left arm's tip on the plate is replaced by the right arm's
    (redrawn lines): L must break, M keeps the fill's piece."""

    area = "reborn-lone-piece"
    AXES = ("M5", "E2")
    REFS = ("L", "M")
    HOLE = (-5, -2, 5, 2)
    BEFORE = {"L": (-3.5, 2.5), "M": (0, -0.5)}
    AFTER = {"L": None, "M": (0, -0.5)}

    def geometry(self):
        return m.polygon(
            [(-4, -1), (4, -1), (4, 1.5), (3, 1.5), (3, 0), (-3, 0), (-3, 3), (-4, 3)]
        )

    def change(self, doc):
        m.setLines(
            self.profile,
            {
                1: ((4, -1), (4, 3)),
                2: ((4, 3), (3, 3)),
                3: ((3, 3), (3, 0)),
                5: ((-3, 0), (-3, 1.5)),
                6: ((-3, 1.5), (-4, 1.5)),
                7: ((-4, 1.5), (-4, -1)),
            },
        )


def polygonHoleShell(z, hole):
    """The plate x -10..20, y -10..10 with one polygonal hole, and the hole's fill."""
    h = [V(x, y, z) for x, y in hole]
    wire = Part.makePolygon(h + h[:1])
    plate = Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), [outer(z), wire]).toNurbs().Faces[0]
    return Part.Shell([plate, Part.Face(wire).toNurbs().Faces[0]])


class UTranslatedOverSteppedHole(Base):
    """`UArmSwapRedraw`'s U, unchanged in shape, moved by -3 along x over a hole whose top steps:
    y 2 at x -7.5..-5.5 rising to 3.5 (where the left arm goes), 2 at x -5.5..-3.5, 1 at x
    -3.5..1.5 (a tooth of the plate), 2 at x 1.5..5. Before, only the left arm's tip reaches the
    plate (L, x -4..-3, y 2..3 and x -3.5..-3, y 1..2), alone on it; after, the left arm lies in the
    hole's raised part and the right arm's tip (x 0..1, y 1..1.5) on the tooth is the plate's one
    piece. The straight path between them runs above y 1, on the plate. A rigid move keeping the
    lines' geometry IDs: L must break, M keeps the fill's piece."""

    area = "reborn-lone-piece"
    FOUND_BY = "ops#524 A1e (PLAN decision 202)"
    AXES = ("M5", "E1")
    REFS = ("L", "M")
    BEFORE = {"L": (-3.5, 2.5), "M": (0, -0.5)}
    AFTER = {"L": None, "M": (-3, -0.5)}
    POINTS = [(-4, -1), (4, -1), (4, 1.5), (3, 1.5), (3, 0), (-3, 0), (-3, 3), (-4, 3)]

    def shell(self):
        return polygonHoleShell(
            HEIGHT,
            [
                (-7.5, -2),
                (5, -2),
                (5, 2),
                (1.5, 2),
                (1.5, 1),
                (-3.5, 1),
                (-3.5, 2),
                (-5.5, 2),
                (-5.5, 3.5),
                (-7.5, 3.5),
            ],
        )

    def geometry(self):
        return m.polygon(self.POINTS)

    def change(self, doc):
        moved = [(x - 3, y) for x, y in self.POINTS]
        m.setLines(
            self.profile,
            {i: (moved[i], moved[(i + 1) % len(moved)]) for i in range(len(moved))},
        )


class MirrorCopyAcrossHole(Base):
    """`MoveAcrossHalf` mirrored across XZ: L and its copy Lc must break, M and Mc carry on in the
    fill and in its copy."""

    area = "mirror-copy"
    AXES = ("M5", "E1")
    REFS = ("L", "M", "Lc", "Mc")
    HOLE = (-1, 2, 1, 4)
    mirror = True
    BEFORE = {"L": (-2, 3), "M": (-0.5, 3), "Lc": (-2, -3), "Mc": (-0.5, -3)}
    AFTER = {"L": None, "M": (0.75, 3), "Lc": None, "Mc": (0.75, -3)}

    def geometry(self):
        return m.rectangle(-3, 2.5, 0, 3.5)

    def change(self, doc):
        m.moveRectangle(self.profile, 0.5, 2.5, 3.5, 3.5)


class SlideWhilePlateGrows(Base):
    """`MoveAcrossHalf`'s rectangle moved by 0.5 while the plate grows: L and M slid along their
    faces and keep their pieces."""

    area = "slide-plate-edited"
    AXES = ("M5", "E1")
    REFS = ("L", "M")
    BEFORE = {"L": (-2, 0), "M": (-0.5, 0)}
    AFTER = {"L": (-1.75, 0), "M": (-0.25, 0)}

    def geometry(self):
        return m.rectangle(-3, -0.5, 0, 0.5)

    def change(self, doc):
        m.moveRectangle(self.profile, -2.5, -0.5, 0.5, 0.5)
        shape = holeShell(HEIGHT, self.HOLE, x1=25)
        self.plate.Shape = shape
        self.pad.UpToShape = (self.plate, self.faceNames(shape))


class PadOnUpToCapAcrossHole(Base):
    """Pad1 (the rectangle x -3..0, y -0.5..0.5) up to a plain plate A at z = 10; Pad2 from Pad1's
    far cap (a face as its profile) up to plate B at z = 20, which has the hole x -1..1, y -2..2
    and its fill: `MoveAcrossHalf` one storey up. The rectangle moves to x 0.5..3.5: Pad2's piece
    on plate B left of the hole (L) is gone and must break; its fill piece (M) carries on at
    x 0.5..1. Plate A under it has no hole."""

    area = "maker-of-piece"
    AXES = ("M5", "E1")
    REFS = ("L", "M")
    BEFORE = {"L": (-2, 0), "M": (-0.5, 0)}
    AFTER = {"L": None, "M": (0.75, 0)}
    TOP = 20.0

    def place(self, x, y):
        return face(contains=V(x, y, self.TOP))

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        plateA = m.feature(doc, "PlateA", Part.Shell([rectFace(-10, -10, 20, 10, HEIGHT)]))
        self.plate = m.feature(doc, "PlateB", holeShell(self.TOP, self.HOLE))
        self.profile = m.sketch(doc, "Profile", m.rectangle(-3, -0.5, 0, 0.5), body)
        pad1 = body.newObject("PartDesign::Pad", "Pad1")
        pad1.Profile = self.profile
        pad1.Type = "UpToShape"
        pad1.UpToShape = (plateA, ["Face1"])
        pad1.Refine = False
        doc.recompute()
        cap = self.names(pad1, face(contains=V(-1.5, 0, HEIGHT)))[0]
        self.pad = body.newObject("PartDesign::Pad", "Pad2")
        self.pad.Profile = (pad1, [cap])
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, self.faceNames(self.plate.Shape))
        self.pad.Refine = False
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(self.pad, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(self.pad, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = self.pad

    def change(self, doc):
        m.moveRectangle(self.profile, 0.5, -0.5, 3.5, 0.5)


def holesShell(z, holes):
    """The plate x -10..20, y -10..10 with rectangular holes, and each hole's fill."""
    wires = [outer(z)]
    for hx0, hy0, hx1, hy1 in holes:
        h = [V(hx0, hy0, z), V(hx0, hy1, z), V(hx1, hy1, z), V(hx1, hy0, z)]
        wires.append(Part.makePolygon(h + h[:1]))
    plate = Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), wires).toNurbs().Faces[0]
    return Part.Shell([plate] + [rectFace(*hole, z) for hole in holes])


class EdgeFewerPiecesAroundHole(Base):
    """The rectangle x -5..5, y 0..2: its far bottom edge (y 0) crosses the thin hole H
    (x -1..1, y -0.2..0.2), so it has two pieces on the plate, P0 (x -5..-1) and P1 (x 1..5).
    The rectangle moves up by 1: the bottom edge (y 1) misses H, and its part x 0.5..5 lies over
    the second hole H3 (x 0.5..6, y 0.6..3): on the plate only Q (x -5..0.5), P0's carrying on, is
    left. P1's piece of the plate is gone; the straight path from P1's middle (3, 0) to Q's
    (-2.25, 1) passes above H and below H3, on the plate."""

    area = "edge-fewer-pieces"
    AXES = ("M5", "E1")
    REFS = ("P0", "P1")
    BEFORE = {"P0": (-3, 0), "P1": (3, 0)}
    AFTER = {"P0": (-3, 1), "P1": None}

    def place(self, x, y):
        return edge(contains=V(x, y, HEIGHT))

    def shell(self):
        return holesShell(HEIGHT, [(-1, -0.2, 1, 0.2), (0.5, 0.6, 6, 3)])

    def geometry(self):
        return m.rectangle(-5, 0, 5, 2)

    def change(self, doc):
        m.moveRectangle(self.profile, -5, 1, 5, 3)
