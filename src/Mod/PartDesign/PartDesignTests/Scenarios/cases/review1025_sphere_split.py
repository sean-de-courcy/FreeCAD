# SPDX-License-Identifier: LGPL-2.1-or-later

"""Review case for the sphere corner at the user's size (ops#1025; review pr1025-r1).

A regular octagon across flats 600 with a vertex on +x, padded 30; its top edges rounded q (Rim),
its eight vertical lines rounded r = q (Corners). At each corner the corner face (Onshape's sphere
q) meets each of the two rim rounds along one edge, from the corner face's tip on the top plane
down to the new round. A datum point sits on that edge at the corner on +y, on its -x side, and
another on the same edge of the corner on +x (its -y side). The edit takes q and r from 14 to 15
together: every corner is the same corner, a little larger, and each of the two edges is still
one edge (Onshape: 72 edges at every size)."""

import math

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, pieces
from PartDesignTests.Scenarios import models as m


class MitreSphereContactArc(Scenario):
    """q = r 14 -> 15 on the 600 octagon, 30 thick."""

    area = "dress-ups"
    CLASSES = ("none",)
    AXES = ("M1", "E1", "X4:600")
    ISSUE = "ops#1025"
    FOUND_BY = "review pr1025-r1"
    TIER = "F"
    REFS = ("arc_at_y", "arc_at_x")
    n, flats, thick = 8, 600.0, 30.0
    q = 14.0
    before, after = 14.0, 15.0

    def rad(self):
        return self.flats / 2 / math.cos(math.pi / self.n)

    def contactArc(self, corner, side):
        """The curved edges on the rim round of the octagon's side next to the corner at angle
        `corner` (degrees) on the side given (+1: counter-clockwise), within 3q of the corner"""
        a = math.radians(corner)
        w = a + side * math.pi / self.n  # the side's outward normal
        nx, ny = math.cos(w), math.sin(w)
        cx, cy = self.rad() * math.cos(a), self.rad() * math.sin(a)

        def test(e):
            if e.Degenerated:
                return False
            try:
                if type(e.Curve).__name__ == "Line":
                    return False
            except Exception:
                return False
            q = self.q
            first, last = e.FirstParameter, e.LastParameter
            for k in range(5):
                p = e.valueAt(first + (last - first) * k / 4)
                d = math.hypot(p.x * nx + p.y * ny - (self.flats / 2 - q), p.z - (self.thick - q))
                if abs(d - q) > 1e-3 * q:
                    return False
                if math.hypot(p.x - cx, p.y - cy) > 3 * q:
                    return False
                if p.z < self.thick - q - 1e-3 * q:
                    return False
            return True

        return edge(where=test)

    def atY(self):
        return pieces(self.contactArc(90, +1))

    def atX(self):
        return pieces(self.contactArc(0, -1))

    def build(self, doc):
        body = m.body(doc)
        rad = self.rad()
        points = [
            (rad * math.cos(2 * math.pi * k / self.n), rad * math.sin(2 * math.pi * k / self.n))
            for k in range(self.n)
        ]
        profile = m.sketch(doc, "Profile", m.polygon(points), body)
        pad = m.pad(body, profile, self.thick)
        doc.recompute()
        rim = body.newObject("PartDesign::Fillet", "Rim")
        rim.Base = (
            pad,
            [
                "Edge%d" % i
                for i, e in enumerate(pad.Shape.Edges, 1)
                if all(abs(v.Point.z - self.thick) < 1e-9 for v in e.Vertexes)
            ],
        )
        rim.Radius = self.q
        doc.recompute()
        corners = body.newObject("PartDesign::Fillet", "Corners")
        corners.Base = (
            rim,
            [
                "Edge%d" % i
                for i, e in enumerate(rim.Shape.Edges, 1)
                if type(e.Curve).__name__ == "Line" and abs(e.tangentAt(e.FirstParameter).z) > 0.999
            ],
        )
        corners.Radius = self.q
        doc.recompute()
        for name, corner, side, expect in (
            ("arc_at_y", 90, +1, self.atY),
            ("arc_at_x", 0, -1, self.atX),
        ):
            point = body.newObject("PartDesign::Point", "On_" + name)
            point.AttachmentSupport = [(corners, self.names(corners, self.contactArc(corner, side))[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect, Attached())
        doc.recompute()

    def edit(self, doc):
        doc.Rim.Radius = self.after
        doc.Corners.Radius = self.after
        self.q = self.after


class MitreSphereContactArcSmaller(MitreSphereContactArc):
    """q = r 16 -> 15."""

    q = 16.0


class MitreSphereContactArcThicker(MitreSphereContactArc):
    """q = r 15 throughout (the pad 36 -> 30)."""

    q = 15.0
    thick = 36.0

    def edit(self, doc):
        doc.Pad.Length = 30.0
        self.thick = 30.0
