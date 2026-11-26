# SPDX-License-Identifier: LGPL-2.1-or-later

"""Review cases for the lone round on its cylinder (ops#1051; review pr546-r1f).

A tray 60 x 60 x 20 (walls 5; its pocket 15 deep, from y 5 to y yb), a U slot through the
wall x 55..60 (walls y 26 and 34 down to z 12, below them the half circle of radius 4 about y 30,
z 12). Round: the slot's top edge (y 34, z 20) rounded rr. With rr <= 8 the ball rests on the slot's
wall (axis y 34 + rr, z 20 - rr); with rr > 8 it rolls onto the slot's arc (axis z 20 - rr,
y 30 + sqrt((rr + 4)^2 - (rr - 8)^2)): the lone round. Fill: the pocket's corner x 55, y yb filleted
rf (concave), in front of the wall whose top the round cut away. Datum points on Fill's result hold
the round's face, the fill's face, the round's line on the top face, its line on the slot and its
arc on the outer wall (x 60). Every edit keeps each of these elements: they are the same elements
at another size or place."""

import math

import FreeCAD as App
import Part
from FreeCAD import Vector as V

from PartDesignTests.Scenarios.harness import Attached, Reopens, Scenario, X, Z, edge, face, pieces
from PartDesignTests.Scenarios import models as m


class LoneRound(Scenario):
    abstract = True
    area = "dress-ups"
    CLASSES = ("none",)
    AXES = ("M1", "E1", "X4:60")
    ISSUE = "ops#1051"
    FOUND_BY = "review pr546-r1f"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    REFS = ("round_face", "fill_face", "top_line", "foot_line", "end_arc")
    rr, rf, yb = 10.0, 2.5, 45.0

    # The round's axis (y, z) and its foot on the slot (y, z), unscaled
    def axis(self):
        r = self.rr
        if r <= 8:
            return 34 + r, 20 - r
        return 30 + math.sqrt((r + 4) ** 2 - (r - 8) ** 2), 20 - r

    def foot(self):
        r = self.rr
        y, z = self.axis()
        if r <= 8:
            return 34.0, z
        return 30 + 4 * (y - 30) / (r + 4), 12 + 4 * (z - 12) / (r + 4)

    def onRound(self, p):
        y, z = self.s(*self.axis())
        return abs(math.hypot(p.y - y, p.z - z) - self.s(self.rr)) < 1e-5 * self.s(self.rr)

    def roundFace(self):
        def test(f):
            if type(f.Surface).__name__ == "Plane":
                return False
            u0, u1, v0, v1 = f.ParameterRange
            return all(
                self.onRound(f.valueAt(u0 + (u1 - u0) * a, v0 + (v1 - v0) * b))
                for a in (0.1, 0.5, 0.9)
                for b in (0.1, 0.5, 0.9)
            )

        return pieces(face(where=test))

    def fillFace(self):
        x, y = self.s(55 - self.rf, self.yb - self.rf)

        def test(f):
            s = f.Surface
            return (
                type(s).__name__ == "Cylinder"
                and abs(abs(s.Axis.z) - 1) < 1e-9
                and abs(s.Radius - self.s(self.rf)) < 1e-5 * self.s(self.rf)
                and math.hypot(s.Center.x - x, s.Center.y - y) < 1e-5 * self.s(60)
            )

        return face(where=test)

    def lineAt(self, y, z):
        y, z = self.s(y, z)
        tol = 1e-5 * self.s(60)

        def test(e):
            if e.Degenerated:
                return False
            a, b = e.ParameterRange
            for k in range(5):
                p = e.valueAt(a + (b - a) * k / 4)
                if abs(p.y - y) > tol or abs(p.z - z) > tol:
                    return False
            return True

        return pieces(edge(where=test))

    def topLine(self):
        return self.lineAt(self.axis()[0], 20)

    def footLine(self):
        return self.lineAt(*self.foot())

    def endArc(self):
        x = self.s(60)
        tol = 1e-5 * self.s(60)

        def test(e):
            if e.Degenerated or e.Length < tol:
                return False
            a, b = e.ParameterRange
            for k in range(5):
                p = e.valueAt(a + (b - a) * k / 4)
                if abs(p.x - x) > tol or not self.onRound(p):
                    return False
            return True

        return pieces(edge(where=test))

    def trayRectangle(self):
        return self.s(5, 5, 55, self.yb)

    def build(self, doc):
        s = self.s
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*s(0, 0, 60, 60)), body)
        m.pad(body, profile, s(20))
        doc.recompute()
        hollow = m.sketch(doc, "Hollow", m.rectangle(*self.trayRectangle()), body, z=s(20))
        m.pocket(body, hollow, s(15), "Tray")
        doc.recompute()
        # The slot's U in the plane x = 62, seen along -x: sketch x is global y, sketch y global z
        circle = Part.Circle(V(s(30), s(12), 0), V(0, 0, 1), s(4))
        u = [
            Part.ArcOfCircle(circle, math.pi, 2 * math.pi),
            Part.LineSegment(V(s(34), s(12), 0), V(s(34), s(30), 0)),
            Part.LineSegment(V(s(34), s(30), 0), V(s(26), s(30), 0)),
            Part.LineSegment(V(s(26), s(30), 0), V(s(26), s(12), 0)),
        ]
        place = App.Placement(V(s(62), 0, 0), m.rotationFromAxes((0, 1, 0), (0, 0, 1)))
        slotSketch = m.sketch(doc, "SlotU", u, body, placement=place)
        slot = m.pocket(body, slotSketch, s(10), "Slot")
        doc.recompute()
        top = edge(curve="line", direction=X, contains=s(57.5, 34, 20))
        rounded = body.newObject("PartDesign::Fillet", "Round")
        rounded.Base = (slot, self.names(slot, top))
        rounded.Radius = s(self.rr)
        doc.recompute()
        corner = edge(curve="line", direction=Z, contains=s(55, self.yb, 10))
        fill = body.newObject("PartDesign::Fillet", "Fill")
        fill.Base = (rounded, self.names(rounded, corner))
        fill.Radius = s(self.rf)
        doc.recompute()
        for name, expect in (
            ("round_face", self.roundFace),
            ("fill_face", self.fillFace),
            ("top_line", self.topLine),
            ("foot_line", self.footLine),
            ("end_arc", self.endArc),
        ):
            names = expect().select(fill.Shape)
            point = body.newObject("PartDesign::Point", "On_" + name)
            point.AttachmentSupport = [(fill, tuple(names))]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect, Attached())
        doc.recompute()


class LoneRound10To11(LoneRound):
    """The lone round grows: rr 10 -> 11 (rolling before and after)."""

    def edit(self, doc):
        self.rr = 11.0
        doc.Round.Radius = self.s(self.rr)


class LoneRound11To12(LoneRound):
    """The lone round grows: rr 11 -> 12, the pocket's wall at y 46.5 (rolling before and after)."""

    rr, yb = 11.0, 46.5

    def edit(self, doc):
        self.rr = 12.0
        doc.Round.Radius = self.s(self.rr)


class LoneRound11To10(LoneRound):
    """The lone round shrinks: rr 11 -> 10 (rolling before and after)."""

    rr = 11.0

    def edit(self, doc):
        self.rr = 10.0
        doc.Round.Radius = self.s(self.rr)


class LoneRoundPlainToRolling(LoneRound):
    """The switch point: rr 7 (on the slot's wall) -> 10 (rolling onto the arc)."""

    rr = 7.0

    def edit(self, doc):
        self.rr = 10.0
        doc.Round.Radius = self.s(self.rr)


class LoneRoundRollingToPlain(LoneRound):
    """The switch point the other way: rr 10 -> 7."""

    def edit(self, doc):
        self.rr = 7.0
        doc.Round.Radius = self.s(self.rr)


class LoneRoundFillGrows(LoneRound):
    """The fill under the lone round grows: rf 2.5 -> 3.5."""

    def edit(self, doc):
        self.rf = 3.5
        doc.Fill.Radius = self.s(self.rf)


class LoneRoundFillMovesAway(LoneRound):
    """The pocket's wall moves from y 45 to y 48: the fill leaves the round's reach."""

    def edit(self, doc):
        self.yb = 48.0
        m.moveRectangle(doc.Hollow, *self.trayRectangle())


class LoneRoundFillMovesUnder(LoneRound):
    """The pocket's wall moves from y 48 to y 45: the fill comes under the round."""

    yb = 48.0

    def edit(self, doc):
        self.yb = 45.0
        m.moveRectangle(doc.Hollow, *self.trayRectangle())


class LoneRoundReopened(Reopens, LoneRound):
    """Saved, closed and reopened, then rr 10 -> 11."""

    steps = ("reopen", "grow")

    def grow(self, doc):
        self.rr = 11.0
        self.doc.Round.Radius = self.s(self.rr)
