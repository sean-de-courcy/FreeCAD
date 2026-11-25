# SPDX-License-Identifier: LGPL-2.1-or-later

"""Review cases for the mitre run-on at size: joined tangent arcs (ops#1025; review pr1025-r2).

A regular N-gon across flats 600 with a vertex on +x, padded `thick`; its top edges rounded q
(Rim); its N vertical lines rounded r (Corners), each running on into the mitre of the rim rounds:
a torus corner at r = 2q, a sphere at r = q. Datum points sit, downstream of Corners, at the corner
at angle `at`: on the rim round of the side next to it (a face of the base, a cylinder q along
that side), on the corner face, on the new round (a cylinder r about a vertical axis), on
the arc between those two (in the plane z = thick - q), on the edge where the corner face meets
that rim round (from the top plane down to the new round: one arc of the rim round), and on the
top face. The edit changes q and r together, keeping r / q: every corner is the same
corner at another size, so every reference is still the element it was."""

import math

from PartDesignTests.Scenarios.harness import Attached, Scenario, Z, edge, face, pieces
from PartDesignTests.Scenarios import models as m


class MitreAtSize(Scenario):
    abstract = True
    area = "dress-ups"
    CLASSES = ("none",)
    AXES = ("M1", "E1", "X4:600")
    ISSUE = "ops#1025"
    FOUND_BY = "review pr1025-r2"
    TIER = "F"
    REFS = ("rim_face", "corner_face", "round_face", "round_arc", "contact_arc", "top_face")
    n, flats, thick = 4, 600.0, 30.0
    q, ratio = 12.0, 2.0
    after = 14.0
    at, side = 180.0, -1  # the corner (degrees); the side next to it: +1 counter-clockwise

    @property
    def r(self):
        return self.q * self.ratio

    def rad(self):
        return self.flats / 2 / math.cos(math.pi / self.n)

    def corner(self):
        a = math.radians(self.at)
        return self.rad() * math.cos(a), self.rad() * math.sin(a)

    def sideNormal(self):
        w = math.radians(self.at) + self.side * math.pi / self.n
        return math.cos(w), math.sin(w)

    def nearCorner(self, shape):
        c = shape.CenterOfMass
        x, y = self.corner()
        return math.hypot(c.x - x, c.y - y) < 3 * self.r

    def rimFace(self):
        nx, ny = self.sideNormal()

        def test(f):
            s = f.Surface
            if type(s).__name__ != "Cylinder" or abs(s.Axis.z) > 1e-6 or abs(s.Radius - self.q) > 1e-5:
                return False
            c = f.CenterOfMass
            d = math.hypot(c.x, c.y)
            return d > 1 and (c.x * nx + c.y * ny) / d > math.cos(math.radians(5))

        return face(where=test)

    def cornerFace(self):
        def test(f):
            return (
                type(f.Surface).__name__ not in ("Plane", "Cylinder")
                and self.nearCorner(f)
                and self.thick - self.q < f.CenterOfMass.z < self.thick
            )

        return face(where=test)

    def roundFace(self):
        def test(f):
            s = f.Surface
            return (
                type(s).__name__ == "Cylinder"
                and abs(abs(s.Axis.z) - 1) < 1e-9
                and abs(s.Radius - self.r) < 1e-4
                and self.nearCorner(f)
            )

        return face(where=test)

    def roundArc(self):
        t = math.pi - 2 * math.pi / self.n
        d = self.rad() - self.r / math.sin(t / 2)
        a = math.radians(self.at)
        x, y, z = d * math.cos(a), d * math.sin(a), self.thick - self.q

        def test(e):
            try:
                c = e.Curve
            except Exception:
                return False
            return (
                type(c).__name__ == "Circle"
                and abs(c.Radius - self.r) < 1e-4
                and abs(abs(c.Axis.z) - 1) < 1e-9
                and abs(c.Center.x - x) < 1e-4
                and abs(c.Center.y - y) < 1e-4
                and abs(c.Center.z - z) < 1e-4
            )

        return edge(where=test)

    def contactArc(self):
        """The curved edges on the cylinder of the rim round, within 3r of the corner, above the
        foot of the rim rounds"""
        nx, ny = self.sideNormal()
        cx, cy = self.corner()

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
                if math.hypot(p.x - cx, p.y - cy) > 3 * self.r:
                    return False
                if p.z < self.thick - q - 1e-3 * q:
                    return False
            return True

        return edge(where=test)

    def contactPieces(self):
        return pieces(self.contactArc())

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.thick))

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
        corners.Radius = self.r
        doc.recompute()
        for name, pick, expect in (
            ("rim_face", self.rimFace, self.rimFace),
            ("corner_face", self.cornerFace, self.cornerFace),
            ("round_face", self.roundFace, self.roundFace),
            ("round_arc", self.roundArc, self.roundArc),
            ("contact_arc", self.contactArc, self.contactPieces),
            ("top_face", self.topFace, self.topFace),
        ):
            point = body.newObject("PartDesign::Point", "On_" + name)
            point.AttachmentSupport = [(corners, self.names(corners, pick())[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect, Attached())
        doc.recompute()

    def edit(self, doc):
        doc.Rim.Radius = self.after
        doc.Corners.Radius = self.after * self.ratio
        self.q = self.after


class MitreTorusSquare12To14(MitreAtSize):
    """The square, r = 2q: q 12 -> 14; the corner on -x, the rim round of the side at 135."""


class MitreTorusSquare14To12(MitreAtSize):
    """The square, r = 2q: q 14 -> 12."""

    q, after = 14.0, 12.0


class MitreTorusSquare16To14(MitreAtSize):
    """The square, r = 2q: q 16 -> 14 (the pad 35); the corner on -y, the side at 225."""

    thick = 35.0
    q, after = 16.0, 14.0
    at, side = 270.0, -1


class MitreTorusSquare12To125(MitreAtSize):
    """The square, r = 2q: q 12 -> 12.5; the corner on +y, the side at 45."""

    q, after = 12.0, 12.5
    at, side = 90.0, -1


class MitreSphereSquare14To15(MitreAtSize):
    """The square, r = q: q 14 -> 15; the corner on -x, the side at 135."""

    ratio = 1.0
    q, after = 14.0, 15.0


class MitreSphereOctagon16To15(MitreAtSize):
    """The octagon, r = q: q 16 -> 15; the corner on +y, the side at 112.5."""

    n = 8
    ratio = 1.0
    q, after = 16.0, 15.0
    at, side = 90.0, +1


class MitreSphereOctagon15To16(MitreSphereOctagon16To15):
    """The octagon, r = q: q 15 -> 16."""

    q, after = 15.0, 16.0


class MitreTorusOctagon15To12(MitreAtSize):
    """The octagon, r = 2q: q 15 -> 12; the corner on -y, the side at 292.5."""

    n = 8
    q, after = 15.0, 12.0
    at, side = 270.0, +1
