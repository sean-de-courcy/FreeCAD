# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2c's attack-set find (ops#468, PLAN decision 214): a twin told apart by a
connected vertex, whose twin goes.

A block 0..40 x 0..20 x 0..10; a pocket through all from a circle r = 5 at (cx, -3) in an
unattached sketch at z = 10: a notch in the front face (y = 0), whose sides meet it in two
vertical lines at x = cx -+ 4, twins of one cylinder and plane. A2 tells them apart by the
crossing vertex only one of them has (its name's connected elements); integration by their rank.
The edit moves the notch left to cx = 3, over the front face's left end: the left line is gone,
and its references must break; the right line stays. The left line's lone survivor, the right
one, has the same name without the connected vertex, and tier 1 took it silently (the attack
set's `ANotch|move-leftGoes.*|datum_line`, `ANotchFilletLeft|...|fillet_line`); decision 214
makes it the old element's twin, which D1's twin clause breaks.
"""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Filleted, Scenario, Z, edge
from PartDesignTests.Scenarios import models as m

V = App.Vector
L, W, H = 40, 20, 10
R, CY = 5, -3
HALF = 4  # sqrt(R^2 - CY^2)


class R2fNotch(Scenario):
    """The model above: a datum plane normal to each line, and a fillet of one of them."""

    abstract = True
    area = "split"
    CLASSES = ("A",)
    AXES = ("M1", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "attack set, fork PR 390 round 2c (A2f)"
    TIER = "F"
    REFS = ("datum_left_line", "datum_right_line", "fillet_line")
    cx = 20
    filletLeft = True

    def line(self, x):
        if x <= 0 or x >= L:
            return BROKEN
        return edge("line", direction=Z, through=V(x, 0, 0))

    def leftLine(self):
        return self.line(self.cx - HALF)

    def rightLine(self):
        return self.line(self.cx + HALF)

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, W), body)
        m.pad(body, profile, H)
        self.notchSketch = m.sketch(doc, "NotchSketch", [m.circle(self.cx, CY, R)], body, z=H)
        pocket = m.pocketThroughAll(body, self.notchSketch, "Notch")
        doc.recompute()

        def plane(name, predicate):
            datum = body.newObject("PartDesign::Plane", name)
            datum.AttachmentSupport = [(pocket, self.names(pocket, predicate))]
            datum.MapMode = "NormalToEdge"
            return datum

        left = plane("LeftLinePlane", self.leftLine())
        right = plane("RightLinePlane", self.rightLine())
        doc.recompute()
        filleted = self.leftLine if self.filletLeft else self.rightLine
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, filleted()))
        fillet.Radius = 0.5
        self.ref("datum_left_line", left, "AttachmentSupport", self.leftLine, Attached())
        self.ref("datum_right_line", right, "AttachmentSupport", self.rightLine, Attached())
        self.ref("fillet_line", fillet, "Base", filleted, Filleted(0.5))


class R2fNotchLeftGoes(R2fNotch):
    """The circle's geometry moves left to cx = 3: the left line is gone."""

    abstract = False

    def edit(self, doc):
        self.cx = 3
        geometry = self.notchSketch.Geometry
        geometry[0].Center = V(self.cx, CY, 0)
        self.notchSketch.Geometry = geometry


class R2fNotchLeftGoesByPlacement(R2fNotch):
    """The same move through the notch sketch's Placement (by -17 in x)."""

    abstract = False

    def edit(self, doc):
        self.cx = 3
        self.notchSketch.Placement = App.Placement(V(-17, 0, H), App.Rotation())


class R2fNotchRightFilletLeftGoes(R2fNotchLeftGoes):
    """The fillet on the right line, which stays: it follows."""

    filletLeft = False
