# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r1s (ops#468): ops#468's pipe-joint hole crossings, scaled (liesOn's fixed
tolerance, crossing roles, twin order at ~60 mm, ~600 mm and ~4 m)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Predicate, Scenario
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def walk(lengths, turns):
    points = [(0.0, 0.0)]
    heading = 0.0
    for i, length in enumerate(lengths):
        if i:
            heading += turns[i - 1]
        a = math.radians(heading)
        x, z = points[-1]
        points.append((x + length * math.sin(a), z + length * math.cos(a)))
    return points


def onCircle(where, description):
    return Predicate("Vertex", description, [lambda v, tol: where(v.Point, tol)])


class PipeJointHoleScaled(Scenario):
    """ops#468's model (twins.py PipeJointHoleCrossings) at a scale: a square swept along a
    polyline in XZ (legs 30, 20, 20, turned 40 and 20 degrees; Transformed, Refine) and a pocket
    through it of a circle in the YZ plane centred `dz` above the first bend; the crossings of the
    joint edges and the seam are labelled by their x and y signs. The first leg 30.3 long."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M3", "E1", "X4:80")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r1s"
    TIER = "F"
    SIZE = 80
    SCALE = 1.0
    dz = 0.0
    radius = 0.5
    REFS = ("xm_ym", "xm_yp", "xp_yp", "xp_ym")

    def labelled(self, x, y):
        s = self.scale
        zc = (30 + self.dz) * s
        shape = self.pocket.Shape
        r = self.radius * s

        def onHole(p, tol):
            return abs(math.hypot(p.y, p.z - zc) - r) < tol

        def seam(p, tol):
            return abs(p.y - r) < tol and abs(p.z - zc) < tol

        def crossing(p, tol):
            return onHole(p, tol) and not seam(p, tol) and p.x * x > 0 and p.y * y > 0

        def seamOnSide(p, tol):
            return seam(p, tol) and p.x * x > 0

        found = onCircle(crossing, f"crossing x{x:+d} y{y:+d}")
        if found.select(shape):
            return found
        onSeam = onCircle(seamOnSide, f"seam vertex x{x:+d}")
        if y > 0 and onSeam.select(shape):
            return onSeam
        return BROKEN

    def build(self, doc):
        s = self.scale
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(-2 * s, -2 * s, 2 * s, 2 * s), body)
        self.path = m.sketch(
            doc,
            "Path",
            m.polyline([(x * s, z * s) for x, z in walk([30, 20, 20], [40, 20])]),
            body,
            placement=XZ,
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = True
        doc.recompute()
        hole = m.sketch(
            doc,
            "Hole",
            [m.circle(0, (30 + self.dz) * s, self.radius * s)],
            body,
            placement=App.Placement(V(0, 0, 0), App.Rotation(V(1, 1, 1), 120)),
        )
        self.pocket = body.newObject("PartDesign::Pocket", "Cut")
        self.pocket.Profile = hole
        self.pocket.Type = 1
        self.pocket.Midplane = True
        self.pocket.Refine = True
        doc.recompute()
        for x, xs in ((-1, "m"), (1, "p")):
            for y, ys in ((-1, "m"), (1, "p")):
                name = f"x{xs}_y{ys}"
                if name in self.REFS:
                    pt = body.newObject("PartDesign::Point", name)
                    pt.AttachmentSupport = [
                        (self.pocket, self.names(self.pocket, self.labelled(x, y))[0])
                    ]
                    pt.MapMode = "Vertex"
                    self.ref(name, pt, "AttachmentSupport", lambda x=x, y=y: self.labelled(x, y))
        doc.recompute()

    def edit(self, doc):
        s = self.scale
        points = [(x * s, z * s) for x, z in walk([30.3, 20, 20], [40, 20])]
        m.setLines(self.path, {i: (points[i], points[i + 1]) for i in range(len(points) - 1)})
        doc.recompute()


class ScaledJointCrossingsStay(PipeJointHoleScaled):
    __doc__ = PipeJointHoleScaled.__doc__ + " dz = 0.2: the crossings stay twins."
    dz = 0.2


class ScaledJointCrossingsStayNear(PipeJointHoleScaled):
    __doc__ = PipeJointHoleScaled.__doc__ + " dz = 0.1: the crossings stay twins."
    dz = 0.1


class ScaledJointSeamLeavesTheJoint(PipeJointHoleScaled):
    __doc__ = PipeJointHoleScaled.__doc__ + " dz = 0: the seam lies on the joint; the longer leg takes it off (1 -> 2)."
    REFS = ("xm_ym", "xp_yp", "xp_ym")
