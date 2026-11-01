# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2gs (ops#468, PLAN decision 214): attacks on the widened twin test (a connected
vertex on one side only is no difference). A block 0..40 x 0..20 x 0..10 (scaled), a through pocket
from a circle in an unattached sketch at z = 10. Circle (cx, -3) r = 5: a notch in the front face,
two vertical lines at cx -+ 4 (twins). The edits move the notch so that one line is gone, or
appears; references are datum planes normal to the line and a fillet of one line."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Filleted, Scenario, Z, edge
from PartDesignTests.Scenarios import models as m

V = App.Vector
L, W, H = 40, 20, 10
R, CY = 5, -3
HALF = 4


class Notch(Scenario):
    abstract = True
    area = "split"
    CLASSES = ("A",)
    AXES = ("M1", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2gs"
    TIER = "F"
    SIZE = 40
    REFS = ("datum_left", "datum_right")
    cx0 = 20
    cx1 = 3
    fillet = None  # "left" / "right": a fillet on that line, ref fillet_line

    def line(self, x):
        s = self.scale
        if x <= 0 or x >= L:
            return BROKEN
        return edge("line", direction=Z, through=V(x * s, 0, 0))

    def left(self, cx):
        return lambda: self.line(cx - HALF)

    def right(self, cx):
        return lambda: self.line(cx + HALF)

    def build(self, doc):
        s = self.scale
        self.cx = self.cx0
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L * s, W * s), body)
        m.pad(body, profile, H * s)
        self.notchSketch = m.sketch(doc, "NotchSketch", [m.circle(self.cx0 * s, CY * s, R * s)], body, z=H * s)
        pocket = m.pocketThroughAll(body, self.notchSketch, "Notch")
        doc.recompute()

        def plane(name, predicate):
            datum = body.newObject("PartDesign::Plane", name)
            datum.AttachmentSupport = [(pocket, self.names(pocket, predicate))]
            datum.MapMode = "NormalToEdge"
            return datum

        cx0 = self.cx0
        leftNow = lambda: self.line(self.cx - HALF)
        rightNow = lambda: self.line(self.cx + HALF)
        # the build-time predicates read the build's cx
        if "datum_left" in self.REFS:
            d = plane("LeftLinePlane", self.line(cx0 - HALF))
            self.ref("datum_left", d, "AttachmentSupport", leftNow, Attached())
        if "datum_right" in self.REFS:
            d = plane("RightLinePlane", self.line(cx0 + HALF))
            self.ref("datum_right", d, "AttachmentSupport", rightNow, Attached())
        doc.recompute()
        if self.fillet:
            side = -HALF if self.fillet == "left" else HALF
            f = body.newObject("PartDesign::Fillet", "Fillet")
            f.Base = (pocket, self.names(pocket, self.line(cx0 + side)))
            f.Radius = 0.5 * s
            now = lambda: self.line(self.cx + side)
            self.ref("fillet_line", f, "Base", now, Filleted(0.5 * s))

    def edit(self, doc):
        self.cx = self.cx1
        s = self.scale
        g = self.notchSketch.Geometry
        g[0].Center = V(self.cx1 * s, CY * s, 0)
        self.notchSketch.Geometry = g


class LeftGoes(Notch):
    """cx 20 -> 3: the left line goes."""


class LeftGoesFillRight(LeftGoes):
    REFS = ("datum_left", "datum_right", "fillet_line")
    fillet = "right"


class LeftGoesFillLeft(LeftGoes):
    REFS = ("datum_left", "datum_right", "fillet_line")
    fillet = "left"


class RightGoes(Notch):
    """cx 20 -> 37: the right line goes (41 > 40)."""
    cx1 = 37


class RightGoesFillLeft(RightGoes):
    REFS = ("datum_left", "datum_right", "fillet_line")
    fillet = "left"


class RightGoesFillRight(RightGoes):
    REFS = ("datum_left", "datum_right", "fillet_line")
    fillet = "right"


class RightAppears(Notch):
    """built at cx 3 (only the right line, x = 7), edit to cx 20 (lines 16, 24): the right line
    is the one at 24, the nearer one is the new left line at 16."""
    REFS = ("datum_right",)
    cx0 = 3
    cx1 = 20


class RightAppearsFillet(RightAppears):
    REFS = ("datum_right", "fillet_line")
    fillet = "right"


class LeftAppears(Notch):
    """built at cx 37 (only the left line, x = 33), edit to cx 20 (lines 16, 24): the left line is
    the one at 16, the nearer one is the new right line at 24."""
    REFS = ("datum_left",)
    cx0 = 37
    cx1 = 20


class LeftAppearsFillet(LeftAppears):
    REFS = ("datum_left", "fillet_line")
    fillet = "left"


class RightAppearsNear(Notch):
    """built at cx 3 (right line at 7), edit to cx 8 (lines 4, 12): the right line is at 12, the
    left at 4 (3 mm from the old place)."""
    REFS = ("datum_right",)
    cx0 = 3
    cx1 = 8


class RightAppearsFar(Notch):
    """built at cx 3 (right line at 7), edit to cx 30 (lines 26, 34): both far."""
    REFS = ("datum_right",)
    cx0 = 3
    cx1 = 30


class BothStayMoved(Notch):
    """cx 20 -> 28: both stay; control."""
    cx1 = 28


class Redrawn(Notch):
    """The circle is deleted and drawn again at cx 3 (new geometry id)."""

    def edit(self, doc):
        self.cx = self.cx1
        s = self.scale
        self.notchSketch.delGeometry(0)
        self.notchSketch.addGeometry(m.circle(self.cx1 * s, CY * s, R * s), False)


class RedrawnAppears(RightAppears):
    def edit(self, doc):
        self.cx = self.cx1
        s = self.scale
        self.notchSketch.delGeometry(0)
        self.notchSketch.addGeometry(m.circle(self.cx1 * s, CY * s, R * s), False)


class PlacementLeftGoes(Notch):
    def edit(self, doc):
        self.cx = self.cx1
        s = self.scale
        self.notchSketch.Placement = App.Placement(V((self.cx1 - self.cx0) * s, 0, H * s), App.Rotation())


class PlacementRightAppears(RightAppears):
    def edit(self, doc):
        self.cx = self.cx1
        s = self.scale
        self.notchSketch.Placement = App.Placement(V((self.cx1 - self.cx0) * s, 0, H * s), App.Rotation())


class TwoStepsRightGoes(Notch):
    """cx 20 -> 28 (both stay) then 28 -> 37 (right goes)."""
    steps = ("first", "second")

    def first(self, doc):
        self.cx = 28
        s = self.scale
        g = self.notchSketch.Geometry
        g[0].Center = V(28 * s, CY * s, 0)
        self.notchSketch.Geometry = g

    def second(self, doc):
        self.cx = 37
        s = self.scale
        g = self.notchSketch.Geometry
        g[0].Center = V(37 * s, CY * s, 0)
        self.notchSketch.Geometry = g


class TwoStepsLeftGoesBackIn(Notch):
    """cx 20 -> 3 (left goes) then 3 -> 12 (both lines, 8 and 16): the right line is at 16"""
    REFS = ("datum_right",)
    steps = ("first", "second")

    def first(self, doc):
        self.cx = 3
        s = self.scale
        g = self.notchSketch.Geometry
        g[0].Center = V(3 * s, CY * s, 0)
        self.notchSketch.Geometry = g

    def second(self, doc):
        self.cx = 12
        s = self.scale
        g = self.notchSketch.Geometry
        g[0].Center = V(12 * s, CY * s, 0)
        self.notchSketch.Geometry = g


class LeftGoes60(LeftGoes):
    SCALE = 1.5


class RightAppears60(RightAppears):
    SCALE = 1.5


class LeftAppears60(LeftAppears):
    SCALE = 1.5
