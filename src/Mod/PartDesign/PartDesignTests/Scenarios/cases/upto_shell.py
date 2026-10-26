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

"""Corpus cases (ops#500, class A): the pieces a Pad up to a B-spline shell cuts its far end into.

A Pad (Refine off) of rectangles on the XY plane, up to a `Part::Feature` shell of B-spline faces
above them. Where a profile's far face or a profile edge meets an edge of the shell (a seam, or
the border of a hole) the Pad's result has two pieces, one on each face of the shell. A datum
point (centre of mass) sits on each piece; the profile rectangle is moved, or the shell is
rebuilt, and each datum must follow the piece that carries on its place, or break where its
piece is gone or the choice between pieces is open.

Two families, ported from the probes:
- `UptoCap*`: the far face. The shell is one cylinder face (radius 20, axis along y, centre
  z = 30) with its seam turned to the line x = 0 at the bottom; rectangle A (2 x 2) crosses the
  seam, rectangle B (5..8 x 0..3) is clear of it. The datums are on A's cap pieces
  (`work/pr340-review/r1v/p_seam.py`, the Refine-off run, `work/386/out/p_seam.off.txt`;
  `corpus/predicted/A.json`: p_seam.off).
- `UptoSeamEdge*` and `UptoHoleEdge*`: the far edges. The shell is two plates meeting at x = 1
  (the seam), or a plate with a hole x -1..1, y -2..2 and the hole's fill, at z = 10; the datums
  are on the pieces of A's far edges (`work/386/p_edges.py`, the Pad run without refine, ops#386;
  `corpus/predicted/A.json`: p_edges, p_edges ontoSeam).

The probes judged by `(x, y)` places on the new pieces; so do these, as geometric predicates on
the edited model: a face containing the place on the cylinder, an edge containing the place at
the shell's height. A datum whose piece is gone expects a break. The probes drew the rectangles
with named dimensions and set those; here the rectangle's lines are moved (`models.moveRectangle`),
which keeps their geometry IDs as a re-dimension does."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge, face
from PartDesignTests.Scenarios import models as m

V = App.Vector

# ---------------------------------------------------------------------------------------------
# The shells
# ---------------------------------------------------------------------------------------------

CYL_R = 20.0
CYL_CZ = 30.0
HEIGHT = 10.0  # the plates' height (the far end of a pad)


def cylinderShell():
    """One B-spline cylinder face, axis along y through (0, *, 30), radius 20, y -20..20, its
    seam turned to the bottom line x = 0, z = 10."""
    cylinder = Part.makeCylinder(CYL_R, 40, V(0, -20, CYL_CZ), V(0, 1, 0))
    side = [f for f in cylinder.Faces if f.Surface.TypeId == "Part::GeomCylinder"][0]
    seam = [e for e in side.Edges if e.isSeam(side)][0]
    p = seam.valueAt(seam.FirstParameter)
    current = math.atan2(p.z - CYL_CZ, p.x)
    wanted = math.atan2(-1, 0)
    side.rotate(V(0, 0, CYL_CZ), V(0, 1, 0), -math.degrees(wanted - current))
    return side.toNurbs().Faces[0]


def cylinderZ(x):
    """The cylinder's height above the point x (the lower side)."""
    return CYL_CZ - math.sqrt(CYL_R * CYL_R - x * x)


def bsFace(x0, x1, y0, y1, z):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.Face(Part.makePolygon(c + c[:1])).toNurbs().Faces[0]


def seamShell(z, seam=1.0, order=(0, 1), extraFirst=False):
    """Two plates x -10..seam and seam..20, y -10..10, at height z, as a shell; `order` the
    faces' order, `extraFirst` a third plate (x 20..30) put before them."""
    faces = [bsFace(-10, seam, -10, 10, z), bsFace(seam, 20, -10, 10, z)]
    faces = [faces[i] for i in order]
    if extraFirst:
        faces.insert(0, bsFace(20, 30, -10, 10, z))
    return Part.Shell(faces)


def holeShell(z, order=(0, 1), hole=(-1, -2, 1, 2)):
    """A plate x -10..20, y -10..10 with a rectangular hole, and the hole's fill, at height z."""
    hx0, hy0, hx1, hy1 = hole
    c = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
    h = [V(hx0, hy0, z), V(hx0, hy1, z), V(hx1, hy1, z), V(hx1, hy0, z)]
    plate = (
        Part.Face(
            Part.Plane(V(0, 0, z), V(0, 0, 1)),
            [Part.makePolygon(c + c[:1]), Part.makePolygon(h + h[:1])],
        )
        .toNurbs()
        .Faces[0]
    )
    fill = bsFace(hx0, hx1, hy0, hy1, z)
    faces = [plate, fill]
    return Part.Shell([faces[i] for i in order])


# ---------------------------------------------------------------------------------------------
# The common model: rectangles A and B, a Pad up to the shell, datum points
# ---------------------------------------------------------------------------------------------


class UptoShell(Scenario):
    """The model and its edit; a subclass sets the shell, the rectangles, the datums and what
    each datum must hold afterwards (`AFTER`: a place (x, y), or None where its piece is gone)."""

    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#500"
    FOUND_BY = "port"
    TIER = "F"

    A = (0, 0, 2, 2)  # rectangle A at the start: x0, y0, x1, y1
    B = (5, 0, 8, 3)
    A1 = None  # A after the edit (None: A isn't edited)
    SHELL1 = None  # the name of the method building the shell after the edit (None: unchanged)
    BEFORE = {}  # ref: the place (x, y) of its datum's piece at the start
    AFTER = {}  # ref: the place (x, y) of the piece it holds after the edit, None where it's gone

    def shell(self):
        raise NotImplementedError

    def place(self, x, y):
        """The predicate of the element of the Pad's result at the place."""
        raise NotImplementedError

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plate = m.feature(doc, "Plate", self.shell())
        geometry = m.rectangle(*self.A) + m.rectangle(*self.B)
        self.profile = m.sketch(doc, "Profile", geometry, body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, self.faceNames(self.plate.Shape))
        self.pad.Refine = False
        doc.recompute()
        for name in self.REFS:
            x, y = self.BEFORE[name]
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(self.pad, self.names(self.pad, self.place(x, y))[0])]
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

    def edit(self, doc):
        if self.A1:
            m.moveRectangle(self.profile, *self.A1)
        if self.SHELL1:
            shape = getattr(self, self.SHELL1)()
            self.plate.Shape = shape
            self.pad.UpToShape = (self.plate, self.faceNames(shape))
        self.edited = True


# ---------------------------------------------------------------------------------------------
# The far face: A's cap on the cylinder, cut by the cylinder's seam
# ---------------------------------------------------------------------------------------------


class UptoCap(UptoShell):
    """A Pad up to the cylinder whose seam is at x = 0; a datum on A's cap on each side of it."""

    abstract = True
    area = "upto-cap"
    AXES = ("M5", "E1")
    A = (-1, 0, 1, 2)
    REFS = ("AL", "AR")
    BEFORE = {"AL": (-0.5, 1), "AR": (0.5, 1)}

    def shell(self):
        return cylinderShell()

    def place(self, x, y):
        p = V(x, y, cylinderZ(x))
        return face(
            where=lambda f: f.Surface.TypeId == "Part::GeomBSplineSurface"
            and f.isInside(p, 1e-4, True)
        )


class UptoCapGrowA(UptoCap):
    """A grows to x -1..3, y 0..4: its two pieces stay on their sides of the seam."""

    A1 = (-1, 0, 3, 4)
    AFTER = {"AL": (-0.5, 2), "AR": (2.5, 2)}


class UptoCapOffSeamRight(UptoCap):
    """A moves to x 0.5..2.5, clear of the seam, wholly on its right: the left piece is gone
    (the datum on it breaks), the right one is A's whole cap."""

    A1 = (0.5, 0, 2.5, 2)
    AFTER = {"AL": None, "AR": (1.5, 1)}


class UptoCapOffSeamLeft(UptoCap):
    """A moves to x -2.5..-0.5, wholly on the left of the seam: the right piece is gone."""

    A1 = (-2.5, 0, -0.5, 2)
    AFTER = {"AL": (-1.5, 1), "AR": None}


class UptoCapShift(UptoCap):
    """A moves to x -1.5..0.5: still two pieces, the left one longer."""

    A1 = (-1.5, 0, 0.5, 2)
    AFTER = {"AL": (-1, 1), "AR": (0.25, 1)}


class UptoCapOntoSeam(UptoCap):
    """A, wholly right of the seam (x 0.5..2.5), moves to x -1..1 across it: one cap becomes two.
    The piece that carries on the old one is the right piece, where the old cap and the new
    overlap (x 0.5..1)."""

    A = (0.5, 0, 2.5, 2)
    A1 = (-1, 0, 1, 2)
    REFS = ("A",)
    BEFORE = {"A": (1.5, 1)}
    AFTER = {"A": (0.5, 1)}


class UptoCapOntoSeamFromLeft(UptoCap):
    """A, wholly left of the seam (x -2.5..-0.5), moves to x -1..1 across it: the piece that
    carries on the old cap is the left one."""

    A = (-2.5, 0, -0.5, 2)
    A1 = (-1, 0, 1, 2)
    REFS = ("A",)
    BEFORE = {"A": (-1.5, 1)}
    AFTER = {"A": (-0.5, 1)}


# ---------------------------------------------------------------------------------------------
# The far edges: A's edges on the plates' seam, or across a hole
# ---------------------------------------------------------------------------------------------


class UptoEdge(UptoShell):
    """A datum on the piece of a far edge of A (an edge at the shell's height); the places are
    the edge's points."""

    abstract = True
    AXES = ("M5", "E1", "E2")

    def place(self, x, y):
        return edge(contains=V(x, y, HEIGHT))


class UptoSeamEdge(UptoEdge):
    """Two plates meeting at x = 1. A (0..2 x 0..2) crosses the seam: its top and bottom edges
    are each two pieces. Datums on the top-left, top-right, bottom-left and bottom-right."""

    abstract = True
    area = "upto-seam-edge"
    REFS = ("TL", "TR", "BL", "BR")
    BEFORE = {"TL": (0.5, 2), "TR": (1.5, 2), "BL": (0.5, 0), "BR": (1.5, 0)}

    def shell(self):
        return seamShell(HEIGHT)

    def reordered(self):
        return seamShell(HEIGHT, order=(1, 0))

    def extraFirst(self):
        return seamShell(HEIGHT, extraFirst=True)

    def seamMoved(self):
        return seamShell(HEIGHT, seam=0.8)

    def seamOff(self):
        return seamShell(HEIGHT, seam=-1)


class UptoSeamEdgeOffRight(UptoSeamEdge):
    """A moves to x 1.5..3.5, wholly right of the seam: the left pieces are gone, the right
    pieces are A's whole edges."""

    A1 = (1.5, 0, 3.5, 2)
    AFTER = {"TL": None, "TR": (2.5, 2), "BL": None, "BR": (2.5, 0)}


class UptoSeamEdgeOffLeft(UptoSeamEdge):
    """A moves to x -2.5..-0.5, wholly left of the seam."""

    A1 = (-2.5, 0, -0.5, 2)
    AFTER = {"TL": (-1.5, 2), "TR": None, "BL": (-1.5, 0), "BR": None}


class UptoSeamEdgeShift(UptoSeamEdge):
    """A moves to x 0.5..2.5: still two pieces on each edge."""

    A1 = (0.5, 0, 2.5, 2)
    AFTER = {"TL": (0.75, 2), "TR": (2.0, 2), "BL": (0.75, 0), "BR": (2.0, 0)}


class UptoSeamEdgeGrowA(UptoSeamEdge):
    """A grows to 4 x 4: the far edges are at y = 4 and y = 0, still two pieces each."""

    A1 = (0, 0, 4, 4)
    AFTER = {"TL": (0.5, 4), "TR": (2.5, 4), "BL": (0.5, 0), "BR": (2.5, 0)}


class UptoSeamEdgeReorder(UptoSeamEdge):
    """The shell is rebuilt with its two faces in the other order; A is not touched."""

    SHELL1 = "reordered"
    AFTER = dict(UptoSeamEdge.BEFORE)


class UptoSeamEdgeExtraFirst(UptoSeamEdge):
    """The shell is rebuilt with another plate (x 20..30) before its two faces; A is not
    touched."""

    SHELL1 = "extraFirst"
    AFTER = dict(UptoSeamEdge.BEFORE)


class UptoSeamEdgeReorderOffRight(UptoSeamEdge):
    """The shell with its faces in the other order, and A moved off the seam to the right."""

    A1 = (1.5, 0, 3.5, 2)
    SHELL1 = "reordered"
    AFTER = {"TL": None, "TR": (2.5, 2), "BL": None, "BR": (2.5, 0)}


class UptoSeamEdgeSeamMoved(UptoSeamEdge):
    """The seam moves from x = 1 to x = 0.8 (an upstream edit): the pieces change length, A's
    four stay two on each edge."""

    SHELL1 = "seamMoved"
    AFTER = dict(UptoSeamEdge.BEFORE)


class UptoSeamEdgeSeamOff(UptoSeamEdge):
    """The seam moves to x = -1, clear of A: each far edge is one piece again, and both datums
    of an edge hold it."""

    SHELL1 = "seamOff"
    AFTER = {"TL": (1.0, 2), "TR": (1.0, 2), "BL": (1.0, 0), "BR": (1.0, 0)}


class UptoSeamEdgeOntoSeam(UptoSeamEdge):
    """A, wholly right of the seam (x 1.5..3.5), moves to x 0..2 across it: each far edge was
    one piece and is now two. Neither piece is the old one, so a datum on it breaks (decision
    119 (3): a piece appearing on an edge is loud)."""

    A = (1.5, 0, 3.5, 2)
    A1 = (0, 0, 2, 2)
    REFS = ("T", "Bo")
    BEFORE = {"T": (2.5, 2), "Bo": (2.5, 0)}
    AFTER = {"T": None, "Bo": None}


class UptoHoleEdge(UptoEdge):
    """A plate with a hole x -1..1, y -2..2 and its fill. A (-3..3 x 1..3) has its bottom edge
    y = 1 across the hole: three pieces, on the plate's left part, the fill, and the plate's
    right part. Datums on each."""

    abstract = True
    area = "upto-hole-edge"
    A = (-3, 1, 3, 3)
    REFS = ("L", "M", "R")
    BEFORE = {"L": (-2, 1), "M": (0, 1), "R": (2, 1)}

    def shell(self):
        return holeShell(HEIGHT)

    def reordered(self):
        return holeShell(HEIGHT, order=(1, 0))

    def holeWider(self):
        return holeShell(HEIGHT, hole=(-4, -2, 1, 2))


class UptoHoleEdgeLeftGone(UptoHoleEdge):
    """A moves to x -0.5..3: the piece on the plate's left part is gone."""

    A1 = (-0.5, 1, 3, 3)
    AFTER = {"L": None, "M": (0.25, 1), "R": (2, 1)}


class UptoHoleEdgeRightGone(UptoHoleEdge):
    """A narrows to x -3..0.5: the piece on the plate's right part is gone."""

    A1 = (-3, 1, 0.5, 3)
    AFTER = {"L": (-2, 1), "M": (-0.25, 1), "R": None}


class UptoHoleEdgeMiddleGone(UptoHoleEdge):
    """A moves to x 1.5..3.5, right of the hole: the left piece and the fill's are gone."""

    A1 = (1.5, 1, 3.5, 3)
    AFTER = {"L": None, "M": None, "R": (2.5, 1)}


class UptoHoleEdgeReorder(UptoHoleEdge):
    """The shell is rebuilt with the plate and the fill in the other order; A is not touched."""

    SHELL1 = "reordered"
    AFTER = dict(UptoHoleEdge.BEFORE)


class UptoHoleEdgeMovedUp(UptoHoleEdge):
    """A moves up to y 2.5..4.5, clear of the hole: its bottom edge is one piece on the plate,
    and all three datums hold it."""

    A1 = (-3, 2.5, 3, 4.5)
    AFTER = {"L": (0, 2.5), "M": (0, 2.5), "R": (0, 2.5)}


class UptoHoleEdgeShift(UptoHoleEdge):
    """A moves to x -2..4: still three pieces."""

    A1 = (-2, 1, 4, 3)
    AFTER = {"L": (-1.5, 1), "M": (0, 1), "R": (2.5, 1)}


class UptoHoleEdgeHoleWider(UptoHoleEdge):
    """The hole is made wider on the left (x -4..1; an upstream edit): the left piece and the
    fill's join into one edge across the fill, so both datums hold it."""

    SHELL1 = "holeWider"
    AFTER = {"L": (-2, 1), "M": (0, 1), "R": (2.5, 1)}
