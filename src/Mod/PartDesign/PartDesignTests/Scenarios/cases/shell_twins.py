# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Corpus cases (ops#500, class A): twin pieces of a Pad's cap, up to a plate and its fill.

A Pad (Refine off) of circles on the XY plane, up to a `Part::Feature` shell at z = 10 made of a
plate with a hole and the hole's fill (all B-spline or planar faces). Where a disc crosses the
border of a hole, the Pad's far end is cut into pieces, one on the plate on each side of the hole
and one on the fill. A datum point (centre of mass) sits on each piece; the shell or the profile
is edited, and each datum must hold the piece that carries on its place, or break where its piece
is gone or the choice is open. Four families, ported from the probes:
- `TiltedTwins*`: a disc of radius 3 at (3, 3) across an elliptic hole (a = 4, b = 1,
  centre (3, 3)): twin pieces above (T) and below (Bo) the hole and the fill piece (M). The
  ellipse is tilted about its centre, by 0.0001 degrees to 2 degrees (the twins are told apart by
  x, and within 1e-5 by y); some also move the disc. (`work/pr340-review/r2v/p_twins.py`, the
  `twins/tilt*` cases; `corpus/predicted/A.json`: H-A_tilt_stacked_twins_row224.)
- `MoveAcrossHalf`: a plate x -10..20, y -10..10 with a hole x -1..1, y -2..2 and its fill; a
  rectangle x -3..0, y -0.5..0.5 gives a piece on the plate (L, x -3..-1) and one on the fill (M,
  x -1..0); the rectangle moves to x 0.5..3.5, across the hole's far border, so L's piece is gone
  and M's piece carries on in the fill at x 0.5..1. (`work/pr340-review/r2v/p_p34.py`,
  `need/moveAcross`; row 231.)
- `HoleToC`: discs A (r 3 at (3, 3)) and C (r 3 at (14, 3)); the elliptic hole is under A. The hole
  moves away to (14, 3): A's cap is whole, so the datums on its three pieces all land on it; C's
  cap, whole before, is cut into three, so its datum has no single piece to follow.
  (`work/pr366-r3v/p_r2.py`, `cap/holeToC`; row 238, decision 122 (2).)
- `SlotTwins*`: four plates F0..F3: F0 (x -10..5) with a slot x 0.6..1.4, y -5..5, F1 the slot's
  fill, F2 (x 5..20) with the same slot 6 further (x 6.6..7.4) and F3 its fill. A disc of radius 1
  at (1, 0) is cut into twins on F0 left and right of the slot (CL, CR) and a middle piece on
  F1 (CM); the datums are also on the disc's far edge on each twin (EL, ER). The disc moves by 6
  (the sketch's attachment offset), onto F2 and F3, and the shell is rebuilt in another order of its
  faces, or not. F0 has no piece of the pad any more, so the datums on its pieces and on F1's must
  break: landing on the identical-looking pieces of F2 and F3 is a wrong plate.
  (`work/pr366-r5v/p_x.py`, `X_SET=twinrigid`; PR366|twins_slid_reorder_row248.)
- `SlideAlongHole*`: the disc slides along a long elliptic hole (a = 20) and its pieces move with it
  (`work/pr340-review/r3v/p_r3twins3.py`, `slideX`).

The probes judged by `(x, y)` places on the new pieces; so do these, as geometric predicates on the
edited model (a face, or an edge, containing the place at the shell's height). The probes drew the
discs with named dimensions and set those; here the circle's centre is moved with
`moveGeometry`, which keeps its geometry ID."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0  # the shell's height (the far end of the pad)

# ---------------------------------------------------------------------------------------------
# The shells
# ---------------------------------------------------------------------------------------------


def outer(z, x0=-10, y0=-10, x1=20, y1=10):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.makePolygon(c + c[:1])


def ellipseShell(z, cx=3, cy=3, a=4, b=1, rot=0.0, border=(-10, -10, 20, 10)):
    """A plate with an elliptic hole (one closed edge), turned by `rot` degrees about its centre,
    and the hole's fill, at height z."""
    edge_ = Part.Ellipse(V(cx, cy, z), a, b).toShape()
    if rot:
        edge_.rotate(V(cx, cy, z), V(0, 0, 1), rot)
    plate = (
        Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), [outer(z, *border), Part.Wire([edge_])])
        .toNurbs()
        .Faces[0]
    )
    fill = Part.Face(Part.Wire([edge_])).toNurbs().Faces[0]
    return Part.Shell([plate, fill])


def rectFace(x0, y0, x1, y1, z, nurbs=True):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    face_ = Part.Face(Part.makePolygon(c + c[:1]))
    return face_.toNurbs().Faces[0] if nurbs else face_


def holeShell(z, hole=(-1, -2, 1, 2)):
    """A plate x -10..20, y -10..10 with a rectangular hole, and the hole's fill, at height z."""
    hx0, hy0, hx1, hy1 = hole
    h = [V(hx0, hy0, z), V(hx0, hy1, z), V(hx1, hy1, z), V(hx1, hy0, z)]
    plate = (
        Part.Face(
            Part.Plane(V(0, 0, z), V(0, 0, 1)), [outer(z), Part.makePolygon(h + h[:1])]
        )
        .toNurbs()
        .Faces[0]
    )
    return Part.Shell([plate, rectFace(hx0, hy0, hx1, hy1, z)])


def slotShell(z, order, nurbs):
    """F0 (x -10..5, y -10..10) with a slot x 0.6..1.4, y -5..5, F1 the slot's fill, F2 (x 5..20)
    with the same slot 6 further, F3 its fill; the faces in the given order."""

    def holed(x0, x1, s0, s1):
        plate = Part.Face(outer(z, x0, -10, x1, 10)).cut(Part.Face(outer(z, s0, -5, s1, 5)))
        plate = plate.Faces[0]
        return plate.toNurbs().Faces[0] if nurbs else plate

    faces = [
        holed(-10, 5, 0.6, 1.4),
        rectFace(0.6, -5, 1.4, 5, z, nurbs),
        holed(5, 20, 6.6, 7.4),
        rectFace(6.6, -5, 7.4, 5, z, nurbs),
    ]
    return Part.Shell([faces[i] for i in order])


# ---------------------------------------------------------------------------------------------
# The common model: a sketch, a Pad up to the shell, datum points
# ---------------------------------------------------------------------------------------------


class ShellTwins(Scenario):
    """The model and its edit; a subclass sets the shell, the profile, the datums and what each
    must hold afterwards (`AFTER`: a place ("F"|"E", x, y), or None where it must break)."""

    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#500"
    FOUND_BY = "port"
    TIER = "F"

    BEFORE = {}  # ref: the place ("F" face | "E" edge, x, y) of its datum's element at the start
    AFTER = {}  # ref: the place of the element it holds after the edit, None where it breaks
    attached = False  # the sketch attached to the XY plane with an offset (SlotTwins)

    def shell(self):
        raise NotImplementedError

    def geometry(self):
        raise NotImplementedError

    def place(self, kind, x, y):
        """The predicate of the element of the Pad's result at the place."""
        if kind == "F":
            return face(contains=V(x, y, HEIGHT))
        return edge(contains=V(x, y, HEIGHT))

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(doc, "Profile", self.geometry(), body)
        if self.attached:
            self.profile.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), "")]
            self.profile.MapMode = "FlatFace"
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
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

    def change(self, doc):
        raise NotImplementedError

    def edit(self, doc):
        self.change(doc)
        self.edited = True

    def reshell(self, shape):
        """The up-to shape rebuilt as `shape` (the pad's link to its faces set again)."""
        self.plate.Shape = shape
        self.pad.UpToShape = (self.plate, self.faceNames(shape))

    def moveCircle(self, x, y):
        """The circle (geometry 0) to centre (x, y), the sketch placed at the origin."""
        self.profile.moveGeometry(0, 3, V(x, y, 0), False)


# ---------------------------------------------------------------------------------------------
# A disc across an elliptic hole, the ellipse tilted
# ---------------------------------------------------------------------------------------------


def discSpots(cx, cy):
    """The twins' places for a disc of radius 3 at (cx, cy): 2.5 above, below, and its centre."""
    return {"top": ("F", cx, cy + 2.5), "bottom": ("F", cx, cy - 2.5), "middle": ("F", cx, cy)}


class TiltedTwins(ShellTwins):
    """The ellipse turns from `tilt0` to `tilt1` degrees about its centre (3, 3); the disc, moved to
    `moved` if that is set, stays across it: each twin holds its own piece (above, below,
    middle)."""

    abstract = True
    area = "tilted-twins"
    AXES = ("M5", "E7")
    REFS = ("top", "bottom", "middle")
    tilt0, tilt1 = 0.0, 0.0
    start = (3.0, 3.0)  # the disc's centre at the start
    moved = None  # and after the edit, if it moves

    def shell(self):
        return ellipseShell(HEIGHT, rot=self.tilt0)

    def geometry(self):
        return [m.circle(*self.start, 3)]

    @property
    def BEFORE(self):
        return discSpots(*self.start)

    @property
    def AFTER(self):
        return discSpots(*(self.moved or self.start))

    def change(self, doc):
        if self.tilt1 != self.tilt0:
            self.reshell(ellipseShell(HEIGHT, rot=self.tilt1))
        if self.moved:
            self.moveCircle(*self.moved)


class TiltedTwinsToPlus001(TiltedTwins):
    """The ellipse tilts from 0 to +0.01 degrees: the twins' centres differ by 4 sin(0.01 deg) in
    x, so the order of the pieces is told by x, and by y within 1e-5 mm."""

    tilt1 = 0.01


class TiltedTwinsToMinus001(TiltedTwins):
    """The ellipse tilts from 0 to -0.01 degrees."""

    tilt1 = -0.01


class TiltedTwinsPlus1ToMinus1(TiltedTwins):
    """The ellipse tilts from +1 to -1 degrees."""

    tilt0, tilt1 = 1.0, -1.0


class TiltedTwinsMinus1ToPlus1(TiltedTwins):
    """The ellipse tilts from -1 to +1 degrees."""

    tilt0, tilt1 = -1.0, 1.0


class TiltedTwinsPlus1ToPlus2(TiltedTwins):
    """The ellipse tilts from +1 to +2 degrees."""

    tilt0, tilt1 = 1.0, 2.0


class TiltedTwinsToPlus00001(TiltedTwins):
    """The ellipse tilts from 0 to +0.0001 degrees (the twins' centres differ in x by 7e-6 mm)."""

    tilt1 = 0.0001


class TiltedTwinsToPlus00003(TiltedTwins):
    """The ellipse tilts from 0 to +0.0003 degrees (the twins' centres differ in x by 2e-5 mm)."""

    tilt1 = 0.0003


class TiltedTwinsPlus00001ToPlus00003(TiltedTwins):
    """The ellipse tilts from +0.0001 to +0.0003 degrees."""

    tilt0, tilt1 = 0.0001, 0.0003


class TiltedTwinsToPlus001DiscMoves(TiltedTwins):
    """The ellipse tilts from 0 to +0.01 degrees and the disc moves 0.3 in x at the same time."""

    tilt1 = 0.01
    moved = (3.3, 3.0)


class TiltedTwinsDiscMovesOnTilted(TiltedTwins):
    """The ellipse stays tilted 5 degrees; the disc moves by (0.2, 0.1), off the ellipse's centre
    (a sketch edit only, the up-to shape unchanged)."""

    tilt0 = tilt1 = 5.0
    moved = (3.2, 3.1)


# ---------------------------------------------------------------------------------------------
# A piece of a rectangle moves across a hole's border
# ---------------------------------------------------------------------------------------------


class MoveAcrossHalf(ShellTwins):
    """A plate with a hole x -1..1, y -2..2 and its fill. The rectangle x -3..0, y -0.5..0.5 has a
    piece on the plate (L, x -3..-1) and one on the fill (M, x -1..0). It moves to x 0.5..3.5: the
    plate's piece is now x 1..3.5, the fill's x 0.5..1. L's piece (the plate between x -3 and -1)
    is gone, so its datum breaks; M's piece carries on in the fill, at x 0.5..1."""

    area = "move-across"
    AXES = ("M5", "E1")
    REFS = ("L", "M")
    BEFORE = {"L": ("F", -2, 0), "M": ("F", -0.5, 0)}
    AFTER = {"L": None, "M": ("F", 0.75, 0)}

    def shell(self):
        return holeShell(HEIGHT)

    def geometry(self):
        return m.rectangle(-3, -0.5, 0, 0.5)

    def change(self, doc):
        m.moveRectangle(self.profile, 0.5, -0.5, 3.5, 0.5)


# ---------------------------------------------------------------------------------------------
# The hole goes to another disc: a cap split in three becomes whole, a whole one is split
# ---------------------------------------------------------------------------------------------


class HoleToC(ShellTwins):
    """Disc A (radius 3 at (3, 3)) lies across the elliptic hole and has twins above (AT) and below
    (ABo) and the fill piece (AM); disc C (radius 3 at (14, 3)) lies on the plate whole (C).
    The hole
    moves to (14, 3), under C: A's cap is whole again, so the three datums on its pieces hold it
    (decision 122 (2): the twins land on the whole cap); C's cap is cut in three, so its datum
    has no piece to follow and must break."""

    area = "hole-to-c"
    AXES = ("M5", "E1")
    REFS = ("AT", "ABo", "AM", "C")
    BEFORE = {"AT": ("F", 3, 5.5), "ABo": ("F", 3, 0.5), "AM": ("F", 3, 3), "C": ("F", 14, 3)}
    AFTER = {"AT": ("F", 3, 3), "ABo": ("F", 3, 3), "AM": ("F", 3, 3), "C": None}

    def shell(self):
        return ellipseShell(HEIGHT)

    def geometry(self):
        return [m.circle(3, 3, 3), m.circle(14, 3, 3)]

    def change(self, doc):
        self.reshell(ellipseShell(HEIGHT, cx=14))


# ---------------------------------------------------------------------------------------------
# A disc sliding along a long hole
# ---------------------------------------------------------------------------------------------


class SlideAlongHole(ShellTwins):
    """A plate x -30..30, y -30..30 with a long elliptic hole (a = 20, b = 1, centre (3, 3)); the
    disc of radius 3 at (3, 3) lies across it with twins above and below and the fill piece. The
    disc slides along the hole by `dx`: its pieces move with it and each datum holds its own."""

    abstract = True
    area = "slide-along-hole"
    AXES = ("M5", "E1")
    REFS = ("top", "bottom", "middle")
    dx = 0.0

    def shell(self):
        return ellipseShell(HEIGHT, a=20, border=(-30, -30, 30, 30))

    def geometry(self):
        return [m.circle(3, 3, 3)]

    BEFORE = discSpots(3, 3)

    @property
    def AFTER(self):
        return discSpots(3 + self.dx, 3)

    def change(self, doc):
        self.moveCircle(3 + self.dx, 3)


class SlideAlongHole3(SlideAlongHole):
    """The disc slides 3 along the hole."""

    dx = 3


class SlideAlongHole8(SlideAlongHole):
    """The disc slides 8 along the hole."""

    dx = 8


class SlideAlongHole15(SlideAlongHole):
    """The disc slides 15 along the hole (its centre at x = 18, the hole ends at x = 23)."""

    dx = 15


# ---------------------------------------------------------------------------------------------
# Rigid twins moved onto the next plates, the shell reordered
# ---------------------------------------------------------------------------------------------

RIM = math.sqrt(1 - 0.7**2)  # the disc's circle at x = 1 -+ 0.7 has y = +-RIM


class SlotTwins(ShellTwins):
    """The disc and the plates are described in the module's docstring. The sketch is moved by 6
    in x (its attachment offset) and the shell rebuilt with its faces in `order` (None: not
    rebuilt). F0 has no piece of the pad afterwards, so every datum on its pieces, and on F1's,
    breaks; the identical pieces on F2 and F3 are other plates'."""

    abstract = True
    area = "slot-twins"
    AXES = ("M5", "E1", "E2")
    REFS = ("CL", "CR", "CM", "EL", "ER")
    attached = True
    nurbs = True
    order = None
    BEFORE = {
        "CL": ("F", 0.3, 0),
        "CR": ("F", 1.7, 0),
        "CM": ("F", 1.0, 0.5),
        "EL": ("E", 0.3, RIM),
        "ER": ("E", 1.7, RIM),
    }
    AFTER = {name: None for name in REFS}

    def shell(self):
        return slotShell(HEIGHT, (0, 1, 2, 3), self.nurbs)

    def geometry(self):
        return [m.circle(1, 0, 1)]

    def change(self, doc):
        self.profile.AttachmentOffset = App.Placement(V(6, 0, 0), App.Rotation())
        if self.order:
            self.reshell(slotShell(HEIGHT, self.order, self.nurbs))


class SlotTwinsBs2301(SlotTwins):
    """B-spline plates; the shell rebuilt as F2 F3 F0 F1."""

    order = (2, 3, 0, 1)


class SlotTwinsBs2103(SlotTwins):
    """B-spline plates; the shell rebuilt as F2 F1 F0 F3."""

    order = (2, 1, 0, 3)


class SlotTwinsBs0321(SlotTwins):
    """B-spline plates; the shell rebuilt as F0 F3 F2 F1."""

    order = (0, 3, 2, 1)


class SlotTwinsBsNoReorder(SlotTwins):
    """B-spline plates; the shell is not rebuilt: the pieces on F2 and F3 carry the plates' own
    marks, and the datums must not land on them."""


class SlotTwinsPl2301(SlotTwins):
    """Planar plates; the shell rebuilt as F2 F3 F0 F1."""

    nurbs = False
    order = (2, 3, 0, 1)


class SlotTwinsPl2103(SlotTwins):
    """Planar plates; the shell rebuilt as F2 F1 F0 F3."""

    nurbs = False
    order = (2, 1, 0, 3)


class SlotTwinsPl0321(SlotTwins):
    """Planar plates; the shell rebuilt as F0 F3 F2 F1."""

    nurbs = False
    order = (0, 3, 2, 1)


class SlotTwinsPlNoReorder(SlotTwins):
    """Planar plates; the shell is not rebuilt."""

    nurbs = False
