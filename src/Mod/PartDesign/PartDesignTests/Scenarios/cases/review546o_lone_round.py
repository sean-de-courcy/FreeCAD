"""Review pr546-r1 (ops#1051): references through a lone round (a round along a straight edge whose
wall is shorter than its radius: it rolls past the wall onto the slot's arc below, and OCCT hands it
back as a B-spline on its cylinder; the PR makes it the Cylinder). Designed geometry only."""

import math

import FreeCAD as App
import Part
from FreeCAD import Vector as V

from PartDesignTests.Scenarios.harness import (
    DressUpOutcome,
    Scenario,
    X,
    Z,
    edge,
    face,
    pieces,
)
from PartDesignTests.Scenarios import models as m


class FilletedAsIs(DressUpOutcome):
    """A fillet whose result is the Part fillet of its base with the expected edges, at the
    fillet's own radius (the radius is an edit of the case)"""

    def compare(self, scenario, consumer, target, expectation):
        self.radius = consumer.Radius.Value
        return DressUpOutcome.compare(self, scenario, consumer, target, expectation)

    def oracle(self, base, edges):
        return base.makeFillet(self.radius, edges)


class LoneRoundTray(Scenario):
    """A tray 60 x 60 x 20 (a pad), its pocket x 5..55, y 5..45, 15 deep (floor z 5); a U slot
    through its wall x 55..60 (a pocket from a sketch in the plane x = 62, normal +X, 9 long): arc
    centre (y 30, z 12), radius 4, slot walls y 26 and 34 up past the top. Round: the slot's top
    edge y 34, z 20 (along X), radius r (10: more than the wall's 8, the round rolls onto the arc).
    Fill: the pocket's corner x 55, y 45 (along Z), radius 2.5, Refine on. Ends: the round's arc on
    the end face x = 60, filleted 1, Refine on. The round's cylinder: radius r along X through
    y = 30 + sqrt((r + 4)^2 - (8 - r)^2), z = 20 - r."""

    abstract = True
    area = "dress-ups"
    MULTI = True
    CLASSES = ("none",)
    AXES = ("M1", "E1")
    ISSUE = "ops#1051"
    FOUND_BY = "review pr546-r1"
    TIER = "F"
    REFS = ("round_edge", "fill_edge", "end_edge")
    r = 10.0

    def centre(self):
        r = self.r
        if r <= 8:  # against the slot's wall y 34
            return 34 + r, 20 - r
        return 30 + math.sqrt((r + 4) ** 2 - (8 - r) ** 2), 20 - r

    def slotTop(self):
        return edge("line", direction=X, through=(0, 34, 20))

    def corner(self):
        return edge(
            "line",
            direction=Z,
            through=(55, 45, 0),
            where=lambda e: abs(e.Length - 15) < 1e-6,
        )

    def roundEnd(self):
        """The round's edge on the end face x = 60: every point at x 60 and r from the axis"""

        def test(e):
            yc, zc = self.centre()
            a, b = e.ParameterRange
            pts = [e.valueAt(a + (b - a) * k / 8) for k in range(9)]
            if any(abs(p.x - 60) > 1e-6 for p in pts):
                return False
            if any(abs(math.hypot(p.y - yc, p.z - zc) - self.r) > 1e-6 for p in pts):
                return False
            return (pts[0] - pts[8]).Length > 1e-3 and abs(
                ((pts[4] - pts[0]).cross(pts[8] - pts[0])).Length
            ) > 1e-6

        return edge(where=test)

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        m.pad(body, m.sketch(doc, "Profile", m.rectangle(0, 0, 60, 60), body), 20)
        m.pocket(body, m.sketch(doc, "Cavity", m.rectangle(5, 5, 55, 45), body, z=20), 15, "Tray")
        place = App.Placement(V(62, 0, 0), m.rotationFromAxes((0, 1, 0), (0, 0, 1)))
        slot = [
            Part.ArcOfCircle(V(26, 12, 0), V(30, 8, 0), V(34, 12, 0)),
            Part.LineSegment(V(34, 12, 0), V(34, 30, 0)),
            Part.LineSegment(V(34, 30, 0), V(26, 30, 0)),
            Part.LineSegment(V(26, 30, 0), V(26, 12, 0)),
        ]
        slotPocket = m.pocket(body, m.sketch(doc, "SlotSketch", slot, body, placement=place), 9, "Slot")
        doc.recompute()
        rnd = body.newObject("PartDesign::Fillet", "Round")
        rnd.Base = (slotPocket, self.names(slotPocket, self.slotTop()))
        rnd.Radius = self.r
        doc.recompute()
        fill = body.newObject("PartDesign::Fillet", "Fill")
        fill.Base = (rnd, self.names(rnd, self.corner()))
        fill.Radius = 2.5
        fill.Refine = True
        doc.recompute()
        ends = body.newObject("PartDesign::Fillet", "Ends")
        ends.Base = (fill, self.names(fill, self.roundEnd()))
        ends.Radius = 1
        ends.Refine = True
        doc.recompute()
        if "round_edge" in self.REFS:
            self.ref("round_edge", rnd, "Base", self.slotTop, FilletedAsIs())
        self.ref("fill_edge", fill, "Base", self.corner, FilletedAsIs())
        self.ref("end_edge", ends, "Base", self.roundEnd, FilletedAsIs())


class LoneRoundSmaller(LoneRoundTray):
    """The round 10 -> 9 (still lone: the wall is 8)."""

    def edit(self, doc):
        doc.Round.Radius = 9
        self.r = 9.0


class LoneRoundSwitch(LoneRoundTray):
    """The round 10 -> 7 (now against its wall: OCCT's own Cylinder), then back to 10."""

    AXES = ("M1", "E1", "switch")
    steps = ("down", "up")

    def down(self, doc):
        doc.Round.Radius = 7
        self.r = 7.0

    def up(self, doc):
        doc.Round.Radius = 10
        self.r = 10.0


class LoneRoundTrayDeeper(LoneRoundTray):
    """The tray's pocket 15 -> 13 deep (the fill's corner shorter: 13 long)."""

    def corner(self):
        depth = getattr(self, "depth", 15)
        return edge(
            "line",
            direction=Z,
            through=(55, 45, 0),
            where=lambda e: abs(e.Length - depth) < 1e-6,
        )

    def edit(self, doc):
        doc.Tray.Length = 13
        self.depth = 13


class LoneRoundTwins(LoneRoundTray):
    """Both slot top edges (y 26 and y 34) in one round, radius 10 (twins about y = 30, both
    lone); the fill and the ends as above (the ends: the y 34 round's arc on x = 60). The round
    10 -> 9."""

    AXES = ("M1", "E1", "twin")
    REFS = ("round_edges", "fill_edge", "end_edge")

    def slotTops(self):
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.CenterOfMass.z - 20) < 1e-6
            and min(abs(e.CenterOfMass.y - 34), abs(e.CenterOfMass.y - 26)) < 1e-6
            and e.CenterOfMass.x > 55,
        )

    def build(self, doc):
        LoneRoundTray.build(self, doc)
        rnd = doc.Round
        slot = doc.Slot
        rnd.Base = (slot, self.slotTops().select(slot.Shape))
        doc.recompute()
        fill = doc.Fill
        fill.Base = (rnd, self.names(rnd, self.corner()))
        doc.recompute()
        ends = doc.Ends
        ends.Base = (fill, self.names(fill, self.roundEnd()))
        doc.recompute()
        self.ref("round_edges", rnd, "Base", lambda: pieces(self.slotTops()), FilletedAsIs())
        self.ref("fill_edge", fill, "Base", self.corner, FilletedAsIs())
        self.ref("end_edge", ends, "Base", self.roundEnd, FilletedAsIs())

    def edit(self, doc):
        doc.Round.Radius = 9
        self.r = 9.0
