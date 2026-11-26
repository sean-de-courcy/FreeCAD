# SPDX-License-Identifier: LGPL-2.1-or-later

"""Review pr1045-r1 (ops#1045): fillets around a round on a wall extruded along its edge (a pad's
elliptic side). Designed geometry; each reference is the fillet's own selection, judged by the
fillet building on the expected edges after the pad gets longer."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Bound, Filleted, Scenario, edge, face, pieces
from PartDesignTests.Scenarios import models as m

V = App.Vector


def ellipse(a, b, cx=0.0, cy=0.0):
    return Part.Ellipse(V(cx + a, cy, 0), V(cx, cy + b, 0), V(cx, cy, 0))


def arc(e, start, end):
    """The ellipse's arc counter-clockwise from start to end."""
    u1 = e.parameter(start)
    u2 = e.parameter(end)
    if u2 <= u1:
        u2 += 2 * math.pi
    return Part.ArcOfEllipse(e, u1, u2)


def lines(points):
    return [Part.LineSegment(p, q) for p, q in zip(points, points[1:])]


class FilletedAsSet(Filleted):
    """Filleted at the radius the feature holds now (the edit changes it)."""

    def compare(self, scenario, consumer, target, expectation):
        self.radius = float(consumer.Radius)
        return super().compare(scenario, consumer, target, expectation)


def vertical(e, x, y, tol=1e-6):
    """A straight edge along z through (x, y)."""
    if not isinstance(e.Curve, Part.Line):
        return False
    return all(abs(v.Point.x - x) < tol and abs(v.Point.y - y) < tol for v in e.Vertexes)


def atHeight(e, z, tol=1e-6):
    return all(abs(v.Point.z - z) < tol for v in e.Vertexes)


class RibRoundWallEdgeAndRim(Scenario):
    """The ellipse 30 x 15 kept above the chord y = -5, with a rib 4 wide and 6 long on the chord
    plane (x 10..14, y -11..-5), padded 20. One fillet, radius 2: the rib's two outer edges (its
    full round, where OCCT fails on the whole selection), the straight edge E between the chord
    plane and the elliptic wall at (28.2843, -5), and the wall's top rim (the ellipse arc at
    z = 20, which meets E at its top vertex). Before ops#1045 the split by coverage rounded the
    rib by the construction and E with the rim by OCCT; with E counted as covered, E and the rim
    fall into different groups that meet at a vertex, and the fillet fails. Built at radius 1
    (the rib below its limit, OCCT builds the whole selection); the edit sets the radius to 2."""

    area = "dress-ups"
    CLASSES = ("none",)
    AXES = ("M1", "E5")
    ISSUE = "ops#1045"
    FOUND_BY = "review pr1045-r1"
    TIER = "F"
    REFS = ("fillet_edges",)
    height = 20
    a, b, chord = 30.0, 15.0, -5.0
    rib = (10.0, 14.0, -11.0)
    radius = 1

    def cornerX(self):
        return self.a * math.sqrt(1 - (self.chord / self.b) ** 2)

    def picked(self):
        x0, x1, yr = self.rib
        xs = self.cornerX()

        def test(e):
            if vertical(e, x0, yr) or vertical(e, x1, yr) or vertical(e, xs, self.chord):
                return True
            return isinstance(e.Curve, Part.Ellipse) and atHeight(e, self.height)

        return pieces(edge(where=test))

    def build(self, doc):
        body = m.body(doc)
        xs = self.cornerX()
        x0, x1, yr = self.rib
        wall = arc(ellipse(self.a, self.b), V(xs, self.chord, 0), V(-xs, self.chord, 0))
        outline = [wall] + lines(
            [
                wall.EndPoint,
                V(x0, self.chord, 0),
                V(x0, yr, 0),
                V(x1, yr, 0),
                V(x1, self.chord, 0),
                wall.StartPoint,
            ]
        )
        profile = m.sketch(doc, "Profile", outline, body)
        pad = m.pad(body, profile, self.height)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.picked().select(pad.Shape))
        fillet.Radius = self.radius
        self.ref("fillet_edges", fillet, "Base", self.picked, FilletedAsSet(self.radius))

    def edit(self, doc):
        doc.Fillet.Radius = 2
        self.radius = 2


class NoseRoundSwitch(Scenario):
    """The ellipse 20 x 5 kept above the chord y = -1, padded 20 (RB53's N1): the straight edge E
    at (19.5959, -1) between the chord plane and the elliptic wall, whose nose has a curvature
    radius of 1.25. Fillet rounds E; a binder holds the round's face. At radius 1.2 the round's
    touch on the wall is before the nose (with ops#1045 the construction's cylinder); at 1.5 it
    is past it (the construction refuses: OCCT's face). The edit changes the radius across that
    switch; the binder must keep the round's face: the face through the point of the cylinder of
    that radius, r from the chord plane and from the wall, nearest E."""

    abstract = True
    area = "dress-ups"
    CLASSES = ("none",)
    AXES = ("M1", "E1")
    ISSUE = "ops#1045"
    FOUND_BY = "review pr1045-r1"
    TIER = "F"
    REFS = ("fillet_edge", "binder_round")
    height = 20
    a, b, chord = 20.0, 5.0, -1.0
    radius = 1.2
    after = 1.5

    def cornerX(self):
        return self.a * math.sqrt(1 - (self.chord / self.b) ** 2)

    def wallEdge(self):
        xs = self.cornerX()
        return edge(where=lambda e: vertical(e, xs, self.chord))

    def roundPoint(self):
        """The point of the round nearest E at half height: on the cylinder of the radius whose
        axis is r from the chord plane and r from the ellipse."""
        r = self.radius
        xs = self.cornerX()
        curve = ellipse(self.a, self.b).toShape()
        y = self.chord + r

        def off(x):
            return Part.Vertex(V(x, y, 0)).distToShape(curve)[0] - r

        lo, hi = xs - 2.5 * r, xs
        for _ in range(80):
            mid = (lo + hi) / 2
            if off(mid) > 0:
                lo = mid
            else:
                hi = mid
        c = V((lo + hi) / 2, y, self.height / 2)
        corner = V(xs, self.chord, self.height / 2)
        return c + (corner - c).normalize() * r

    def roundFace(self):
        p = self.roundPoint()

        def test(f):
            if isinstance(f.Surface, Part.Plane) or "Extrusion" in f.Surface.TypeId:
                return False
            return Part.Vertex(p).distToShape(f)[0] < 1e-3

        return face(where=test)

    def build(self, doc):
        body = m.body(doc)
        xs = self.cornerX()
        wall = arc(ellipse(self.a, self.b), V(xs, self.chord, 0), V(-xs, self.chord, 0))
        profile = m.sketch(doc, "Profile", [wall] + lines([wall.EndPoint, wall.StartPoint]), body)
        pad = m.pad(body, profile, self.height)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.wallEdge()))
        fillet.Radius = self.radius
        doc.recompute()
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(fillet, tuple(self.names(fillet, self.roundFace())))]
        self.ref("fillet_edge", fillet, "Base", self.wallEdge, FilletedAsSet(self.radius))
        self.ref("binder_round", binder, "Support", self.roundFace, Bound())

    def edit(self, doc):
        doc.Fillet.Radius = self.after
        self.radius = self.after


class NoseRoundPastTheNose(NoseRoundSwitch):
    """Radius 1.2 -> 1.5: from before the nose to past it."""


class NoseRoundBeforeTheNose(NoseRoundSwitch):
    """Radius 1.5 -> 1.2: from past the nose to before it."""

    radius = 1.5
    after = 1.2


class NoseRoundSameSide(NoseRoundSwitch):
    """Radius 0.8 -> 1.2: both before the nose (the control: no switch)."""

    radius = 0.8
    after = 1.2
