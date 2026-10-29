# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r1s (ops#468): the side faces of a Pipe's legs when the number of legs changes."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def walk(lengths, turns):
    points = [(0.0, 0.0)]
    heading = 0.0
    headings = []
    for i, length in enumerate(lengths):
        if i:
            heading += turns[i - 1]
        a = math.radians(heading)
        headings.append(heading)
        x, z = points[-1]
        points.append((x + length * math.sin(a), z + length * math.cos(a)))
    return points, headings


class PipeLegs(Scenario):
    """A 4 x 4 square (XY plane, z = 0, half width 2) swept along a polyline in an XZ sketch
    (legs `legs0`, each turned `turns` degrees from the one before; Transition Transformed,
    Refine). A datum point sits on the face of each leg on its +perpendicular side (in the XZ
    plane). The edit changes the legs."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M3", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r1s"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    legs0 = (30, 20)
    legs1 = (30, 20, 20)
    turns = (40, 20)
    REFS = ("leg1", "leg2")

    def side(self, i):
        s = self.scale
        points, headings = walk([x * s for x in self.legs], self.turns)
        if i >= len(self.legs):
            return BROKEN
        (x0, z0), (x1, z1) = points[i], points[i + 1]
        h = math.radians(headings[i])
        p = (math.cos(h), 0, -math.sin(h))
        mid = V((x0 + x1) / 2 + 2 * s, 0, (z0 + z1) / 2)
        return face(surface="plane", contains=mid)

    def build(self, doc):
        s = self.scale
        self.legs = self.legs0
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(-2 * s, -2 * s, 2 * s, 2 * s), body)
        points, _ = walk([x * s for x in self.legs], self.turns)
        self.path = m.sketch(doc, "Path", m.polyline(points), body, placement=XZ)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = True
        doc.recompute()
        self.pipe = pipe
        for i in range(3):
            name = f"leg{i + 1}"
            if name in self.REFS:
                pt = body.newObject("PartDesign::Point", name)
                pt.AttachmentSupport = [(pipe, self.names(pipe, self.side(i))[0])]
                pt.MapMode = "CenterOfMass"
                self.ref(name, pt, "AttachmentSupport", lambda i=i: self.side(i))
        doc.recompute()

    def edit(self, doc):
        s = self.scale
        self.legs = self.legs1
        points, _ = walk([x * s for x in self.legs], self.turns)
        n = len(self.legs0)
        geometry = self.path.Geometry
        if len(self.legs1) > n:
            for k in range(n, len(self.legs1)):
                self.path.addGeometry(
                    Part.LineSegment(V(*points[k], 0), V(*points[k + 1], 0)), False
                )
        elif len(self.legs1) < n:
            for k in range(n - 1, len(self.legs1) - 1, -1):
                self.path.delGeometry(k)
        doc.recompute()


class PipeLegAddedAtTheEnd(PipeLegs):
    __doc__ = PipeLegs.__doc__ + " 2 -> 3 legs: a leg is drawn onto the end."
    REFS = ("leg1", "leg2")


class PipeLegRemovedFromTheEnd(PipeLegs):
    __doc__ = PipeLegs.__doc__ + " 3 -> 2 legs: the last line is deleted; its face goes."
    legs0, legs1 = (30, 20, 20), (30, 20)
    REFS = ("leg1", "leg2", "leg3")


class PipeLegRemovedTwoToOne(PipeLegs):
    __doc__ = PipeLegs.__doc__ + " 2 -> 1 leg: the second line is deleted; its face goes."
    legs0, legs1 = (30, 20), (30,)
    REFS = ("leg1", "leg2")


class PipeLegAddedOneToTwo(PipeLegs):
    __doc__ = PipeLegs.__doc__ + " 1 -> 2 legs: a leg is drawn onto the end."
    legs0, legs1 = (30,), (30, 20)
    REFS = ("leg1",)
