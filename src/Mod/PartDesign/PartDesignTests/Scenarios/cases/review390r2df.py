# SPDX-License-Identifier: LGPL-2.1-or-later
"""Corpus cases (class A, ops#468): fork PR 390 round 2d's fix-trace review (pr390-r2df). The count
kept: both crossings of a hole survive on the crossed edge, whose sketch line is drawn the other way
(A2's switch point, I-A6) while the hole moves along the edge, nothing left at either old place.
Model P: plate 200 x 100 x 5 (scale 3), through pocket of a circle r 1 at (ax, 0.5) crossing the top
front edge (y 0, z 5) at ax -+ 0.866, points on both crossings. Model S: pad 20 x 10 x 5, the same
circle at (cx, 0.5), points on its crossings, a Fillet on one of the hole's vertical lines on the
front face (x = cx -+ 0.866). R2dfCornerHole: crossings saved alone. Expectations: the element at its
place on the edited model, else BROKEN."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Filleted, Scenario, edge, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HALF = math.sqrt(1 - 0.5**2)


def drawnTheOtherWay(sketch, index=0):
    geometry = sketch.Geometry
    line = geometry[index]
    start, end = V(line.StartPoint), V(line.EndPoint)
    line.StartPoint, line.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
    line.StartPoint, line.EndPoint = end, start
    sketch.Geometry = geometry


class R2dfCase(Scenario):
    abstract = True
    area, CLASSES, ISSUE, FOUND_BY, TIER = "twins", ("A",), "ops#468", "review pr390-r2df", "F"
    AXES = ("M1", "E1", "E4", "X4:600")
    SIZE, SCALE, width, depth = 200, 3, 200, 100
    REFS = ("left", "right")
    x0, x1, flip, filletSide = 100.0, 150.0, True, 0

    def crossing(self, side):
        x = self.x + side * HALF
        return vertex(at=self.s(x, 0, 5)) if x > 1e-6 else BROKEN

    def line(self):
        x, z, top = self.s(self.x + self.filletSide * HALF, 2.5, 5)
        tol = 1e-6 * max(1, self.scale)
        return edge(where=lambda e: (e.CenterOfMass - V(x, 0, z)).Length < tol
                    and abs(e.Length - top) < tol)

    def build(self, doc):
        self.x = self.x0
        body = m.body(doc)
        rectangle = m.rectangle(*self.s(0, 0, self.width, self.depth))
        self.profile = m.sketch(doc, "Profile", rectangle, body)
        m.pad(body, self.profile, self.s(5))
        self.hole = m.sketch(doc, "Hole", [m.circle(*self.s(self.x0, 0.5, 1))], body)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile, pocket.Type, pocket.Midplane = self.hole, 1, True
        doc.recompute()
        for name, side in zip(self.REFS[:2], (-1, 1)):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(pocket, self.names(pocket, self.crossing(side))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda s=side: self.crossing(s), Attached())
        if self.filletSide:
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (pocket, self.names(pocket, self.line()))
            fillet.Radius = self.s(0.3)
            doc.recompute()
            self.ref("line", fillet, "Base", self.line, Filleted(self.s(0.3)))
        doc.recompute()

    def edit(self, doc):
        if self.flip:
            drawnTheOtherWay(self.profile)
        self.hole.moveGeometry(0, 3, V(*self.s(self.x1, 0.5, 0)), False)
        self.x = self.x1
        doc.recompute()


class R2dfFlipMovedFar(R2dfCase):
    """Flipped, the hole moved +50: count 2 kept. Each point stays on the crossing on its side."""


class R2dfFlipMovedNear(R2dfCase):
    """Flipped, the hole moved +0.5: each crossing 0.5 from its old place."""
    x1 = 100.5


class R2dfMovedFar(R2dfCase):
    """The control: moved +50, not flipped."""
    flip = False


class R2dfLoneRightMoved(R2dfCase):
    """Not flipped, the hole to (0.3, 0.5): the left crossing leaves the edge (2 -> 1), the right
    one stays alone, its role kept. Left breaks; right follows (1.166)."""
    x1, flip = 0.3, False


class R2dfSeamFlipMoved(R2dfCase):
    """Model S, flipped, the hole moved +3 along the edge; the Fillet on the right line."""
    AXES = ("M4", "E1", "E4")
    SIZE, SCALE, width, depth = 20, 1, 20, 10
    REFS = ("left_point", "right_point", "line")
    x0, x1, filletSide = 10.0, 13.0, 1


class R2dfSeamFlipMovedFilletLeft(R2dfSeamFlipMoved):
    filletSide = -1


class R2dfSeamMoved(R2dfSeamFlipMoved):
    """The control: moved +3, not flipped."""
    flip = False


class R2dfCornerHole(R2dfCase):
    """Pad 20 x 10 x 5, the circle at (0.3, 0.5) over the front-left corner: one crossing on the top
    front edge (x = 0.3 + 0.866), one on the top left edge (y = 0.5 + 0.954), each saved alone. The
    hole moves to (0.5, 0.5); each crossing moves alone along its edge. Each point follows."""
    AXES = ("M4", "E1")
    SIZE, SCALE, width, depth = 20, 1, 20, 10
    REFS = ("front", "left")
    x0, x1, flip = 0.3, 0.5, False

    def crossing(self, side):
        if side < 0:
            return vertex(at=self.s(self.x + HALF, 0, 5))
        return vertex(at=self.s(0, 0.5 + math.sqrt(1 - self.x**2), 5))
