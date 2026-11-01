# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r1s (ops#468): vertexes generated along a closed edge (the closed-edge exception of
twinOrder: the maker's order from the seam, with ORD)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Predicate, Scenario
from PartDesignTests.Scenarios import models as m

V = App.Vector


def vertexWhere(where, description):
    return Predicate("Vertex", description, [lambda v, tol: where(v.Point, tol)])


class ClosedEdgeSlot(Scenario):
    """A cylinder (radius 5, height 10, axis Z through the origin) cut by a box slot (x -1..1,
    y -7..7, z -1..11) (Part::Cut): the slot's walls meet the top circle (z = 10, a closed edge
    with its seam at angle 0) at four points (+-1, +-4.899). Each is a datum point's reference
    (`pp`: x > 0, y > 0, and so on). The edit moves the model; the expected element is the vertex
    at the point's place in the edited model."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M3", "E7")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r1s"
    TIER = "F"
    SIZE = 14
    SCALE = 1.0
    REFS = ("pp", "mp", "mm", "pm")
    cylinderTurn = 0.0
    slotTurn = 0.0
    slotShift = 0.0
    HALF = math.sqrt(25 - 1)

    def corners(self):
        return {"pp": (1, self.HALF), "mp": (-1, self.HALF), "mm": (-1, -self.HALF), "pm": (1, -self.HALF)}

    def place(self, name):
        """Where the corner is in the edited model: it moves with the slot, and stays on the
        circle where the slot meets it."""
        s = self.scale
        x, y = self.corners()[name]
        a = math.radians(self.slotTurn if self.edited else 0.0)
        X = (x * math.cos(a) - y * math.sin(a) + self.slotShift) * s
        Y = (x * math.sin(a) + y * math.cos(a)) * s
        return V(X, Y, 10 * s)

    def expect(self, name):
        def predicate():
            p = self.place(name)
            return vertexWhere(lambda q, tol: (q - p).Length < 1e-3 * self.scale, f"corner {name}")

        return predicate

    edited = False

    def build(self, doc):
        s = self.scale
        self.edited = False
        self.cyl = doc.addObject("Part::Cylinder", "Cylinder")
        self.cyl.Radius = 5 * s
        self.cyl.Height = 10 * s
        self.box = doc.addObject("Part::Box", "Slot")
        self.box.Length, self.box.Width, self.box.Height = 2 * s, 14 * s, 12 * s
        self.box.Placement = App.Placement(V(-1 * s, -7 * s, -1 * s), App.Rotation())
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = self.cyl, self.box
        doc.recompute()
        self.cut = cut
        for name in self.REFS:
            pt = doc.addObject("Part::DatumPoint", name)
            pt.AttachmentSupport = [(cut, self.names(cut, self.expect(name)())[0])]
            pt.MapMode = "Vertex"
            self.ref(name, pt, "AttachmentSupport", self.expect(name))
        doc.recompute()

    def edit(self, doc):
        s = self.scale
        self.edited = True
        self.cyl.Placement = App.Placement(V(), App.Rotation(V(0, 0, 1), self.cylinderTurn))
        a = self.slotTurn
        # the slot box turned about the origin by `a`, moved by slotShift along x
        rot = App.Rotation(V(0, 0, 1), a)
        corner = rot.multVec(V(-1 * s, -7 * s, -1 * s)) + V(self.slotShift * s, 0, 0)
        self.box.Placement = App.Placement(corner, rot)
        doc.recompute()


class ClosedEdgeSeamTurned90(ClosedEdgeSlot):
    __doc__ = ClosedEdgeSlot.__doc__ + " The cylinder alone turned 90 degrees about its axis: the seam moves past the corners, they stay."
    cylinderTurn = 90.0


class ClosedEdgeSeamTurned180(ClosedEdgeSlot):
    __doc__ = ClosedEdgeSlot.__doc__ + " The cylinder alone turned 180 degrees about its axis."
    cylinderTurn = 180.0


class ClosedEdgeSeamTurned30(ClosedEdgeSlot):
    __doc__ = ClosedEdgeSlot.__doc__ + " The cylinder alone turned 30 degrees: the seam passes the first corner (at 78.5 degrees? no: stays below it)."
    cylinderTurn = 30.0


class ClosedEdgeSeamTurned80(ClosedEdgeSlot):
    __doc__ = ClosedEdgeSlot.__doc__ + " The cylinder alone turned 80 degrees: the seam passes the corner at 78.5 degrees."
    cylinderTurn = 80.0


class ClosedEdgeWholeTurned90(ClosedEdgeSlot):
    __doc__ = ClosedEdgeSlot.__doc__ + " The slot and the cylinder both turned 90 degrees about Z."
    cylinderTurn = 90.0
    slotTurn = 90.0


class ClosedEdgeWholeTurned180(ClosedEdgeSlot):
    __doc__ = ClosedEdgeSlot.__doc__ + " The slot and the cylinder both turned 180 degrees about Z."
    cylinderTurn = 180.0
    slotTurn = 180.0


class ClosedEdgeSlotTurned5(ClosedEdgeSlot):
    __doc__ = ClosedEdgeSlot.__doc__ + " The slot alone turned 5 degrees: the corners move 5 degrees along the circle."
    slotTurn = 5.0


class ClosedEdgeSlotTurned20(ClosedEdgeSlot):
    __doc__ = ClosedEdgeSlot.__doc__ + " The slot alone turned 20 degrees about Z: the corners move along the circle."
    slotTurn = 20.0
