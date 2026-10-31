# SPDX-License-Identifier: LGPL-2.1-or-later
"""A crossing leaves the edge and the other lands on its place (ops#553; fork PR 390 round 2s's
review cases, ported for D2, ops#526): a hole whose rim crosses a pad's front edges slides and
grows so that one crossing goes past the edge's end while the other lands exactly where the gone
one was. The one at the place is another element of the same size there: its edge leaves it the
other way (the record's sides, D2), so the gone crossing's reference breaks."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector


class HoleCrossingsGone(Scenario):
    """A PartDesign pad 20 x 10 x 5 (scale 1) with a through pocket of a circle of radius r0
    centred on its front edge at (cx0, 0); its crossings with the front bottom and top edges are
    at x = cx -+ r (`lo`/`hi`, z 0 and 5). The circle's centre and radius change to cx1, r1."""

    abstract = True
    area = "twins"
    CLASSES = ("D",)
    AXES = ("M3", "E1")
    ISSUE = "ops#553"
    FOUND_BY = "review pr390-r2s"
    TIER = "F"
    SIZE = 20
    SCALE = 60
    REFS = ("lo_z0", "lo_z5", "hi_z0", "hi_z5")
    cx0, r0 = 10.0, 2.0
    cx1, r1 = 10.0, 2.0
    cy = 0.0  # the circle's centre off the front edge (oblique crossings)
    windingReversed = False  # the base rectangle's four lines replaced, drawn the other way
    clockwise = False  # the hole's circle replaced by one with its axis reversed (same geometry)
    redraw = False  # the hole's circle deleted and drawn again

    def crossing(self, side, z):
        x = self.cx + side * (self.r**2 - self.cy**2) ** 0.5
        if not 1e-6 < x < 20 - 1e-6:
            return BROKEN
        return vertex(self.s(x, 0, z))

    def build(self, doc):
        self.cx, self.r = self.cx0, self.r0
        body = m.body(doc)
        profile = m.sketch(doc, "Base", m.rectangle(*self.s(0, 0, 20, 10)), body)
        m.pad(body, profile, self.s(5))
        doc.recompute()
        self.base = profile
        self.hole = m.sketch(
            doc, "HoleSketch", [m.circle(*self.s(self.cx, self.cy, self.r))], body, z=self.s(5)
        )
        pocket = m.pocketThroughAll(body, self.hole, "Hole")
        doc.recompute()
        for side, label in ((-1, "lo"), (1, "hi")):
            for z in (0, 5):
                name = f"{label}_z{z}"
                point = body.newObject("PartDesign::Point", name)
                point.AttachmentSupport = [(pocket, self.names(pocket, self.crossing(side, z))[0])]
                point.MapMode = "Vertex"
                self.ref(
                    name, point, "AttachmentSupport", lambda side=side, z=z: self.crossing(side, z)
                )
        doc.recompute()

    def edit(self, doc):
        self.cx, self.r = self.cx1, self.r1
        if self.windingReversed:
            # New lines (new geometry IDs), each drawn the other way
            corners = [(0, 0), (20, 0), (20, 10), (0, 10)]
            geometry = self.base.Geometry
            for i in range(4):
                a, b = self.s(*corners[(i + 1) % 4]), self.s(*corners[i])
                geometry[i] = Part.LineSegment(V(*a, 0), V(*b, 0))
            self.base.Geometry = geometry
        if self.redraw:
            self.hole.deleteAllGeometry()
            self.hole.addGeometry(m.circle(*self.s(self.cx, self.cy, self.r)), False)
        elif self.clockwise:
            self.hole.deleteAllGeometry()
            self.hole.addGeometry(
                Part.Circle(V(*self.s(self.cx, self.cy, 0)), V(0, 0, -1), self.s(self.r)), False
            )
        else:
            geometry = self.hole.Geometry
            geometry[0].Center = V(*self.s(self.cx, self.cy, 0))
            geometry[0].Radius = self.s(self.r)
            self.hole.Geometry = geometry
        doc.recompute()


class HoleLoGoneHiLandsOnLo(HoleCrossingsGone):
    __doc__ = (
        HoleCrossingsGone.__doc__
        + " cx 10 -> 3.5, r 2 -> 4.5: lo (-1) leaves past the edge's start, hi (8) lands on lo's"
        + " old place."
    )
    cx1, r1 = 3.5, 4.5


class HoleHiGoneLoLandsOnHi(HoleCrossingsGone):
    __doc__ = (
        HoleCrossingsGone.__doc__
        + " cx 10 -> 16.5, r 2 -> 4.5: hi (21) leaves past the edge's end, lo (12) lands on hi's"
        + " old place."
    )
    cx1, r1 = 16.5, 4.5


class HoleBaseWindingReversedLoGone(HoleCrossingsGone):
    __doc__ = (
        HoleCrossingsGone.__doc__
        + " The base rectangle's lines replaced, drawn the other way; and cx 10 -> 3.5, r 2 -> 4.5"
        + " (lo gone, hi on lo's old place). At z 0, tier 1 keeps the circle's crossing with the"
        + " pad's other front edge, 480 mm away (design 9.10)."
    )
    windingReversed = True
    cx1, r1 = 3.5, 4.5


class HoleRedrawnLoGone(HoleCrossingsGone):
    __doc__ = (
        HoleCrossingsGone.__doc__
        + " The circle deleted and drawn again at cx 3.5, r 4.5 (lo gone, hi on lo's old place):"
        + " every source new, so only the sides tell hi from lo drawn again."
    )
    redraw = True
    cx1, r1 = 3.5, 4.5


class HoleObliqueLoGone(HoleCrossingsGone):
    __doc__ = (
        HoleCrossingsGone.__doc__
        + " cy 1: cx 10 -> 3.5, r 2 -> 4.5 (lo gone, hi lands near lo's old place, not on it)."
    )
    cy = 1.0
    cx1, r1 = 3.5, 4.5


class HoleClockwise(HoleCrossingsGone):
    __doc__ = (
        HoleCrossingsGone.__doc__
        + " The control: the circle drawn again with its axis reversed, the same geometry; every"
        + " crossing drawn again where it was."
    )
    clockwise = True
