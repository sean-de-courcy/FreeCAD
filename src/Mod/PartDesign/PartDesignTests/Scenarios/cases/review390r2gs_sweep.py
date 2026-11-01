# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2gs: a sweep of the notch (circle r = 5 at (cx, -3) through the front face of a
40 x 20 x 10 block) from cx0 to cx1: the lines at cx -+ 4 exist while inside 0..40. Refs: a datum
plane normal to each line that exists at the build."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, Z, edge
from PartDesignTests.Scenarios import models as m

V = App.Vector
L, W, H = 40, 20, 10
R, CY = 5, -3
HALF = 4


def inside(x):
    return 0 < x < L


class R2gsSweep(Scenario):
    abstract = True
    area = "split"
    CLASSES = ("A",)
    AXES = ("M1", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2gs"
    TIER = "F"
    REFS = ()
    cx0 = 20
    cx1 = 3

    def line(self, x):
        if not inside(x):
            return BROKEN
        return edge("line", direction=Z, through=V(x, 0, 0))

    def build(self, doc):
        self.cx = self.cx0
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, W), body)
        m.pad(body, profile, H)
        self.sk = m.sketch(doc, "NotchSketch", [m.circle(self.cx0, CY, R)], body, z=H)
        pocket = m.pocketThroughAll(body, self.sk, "Notch")
        doc.recompute()
        for name, side in (("datum_left", -HALF), ("datum_right", HALF)):
            if name not in self.REFS:
                continue
            d = body.newObject("PartDesign::Plane", name + "Plane")
            d.AttachmentSupport = [(pocket, self.names(pocket, self.line(self.cx0 + side)))]
            d.MapMode = "NormalToEdge"
            self.ref(name, d, "AttachmentSupport", (lambda sd: lambda: self.line(self.cx + sd))(side), Attached())
        doc.recompute()

    def edit(self, doc):
        self.cx = self.cx1
        g = self.sk.Geometry
        g[0].Center = V(self.cx1, CY, 0)
        self.sk.Geometry = g


for cx0 in (20, 8, 32, 3, 37):
    refs = tuple(n for n, s in (("datum_left", -HALF), ("datum_right", HALF)) if inside(cx0 + s))
    for cx1 in (-3, 1, 3, 5, 8, 10, 14, 17, 20, 23, 26, 30, 33, 36, 38, 43):
        if cx1 == cx0 or abs(cx1 - HALF) < 1e-9 or abs(cx1 + HALF - L) < 1e-9 or cx1 - HALF == 0 or cx1 + HALF == L:
            continue
        name = f"R2gsSw{cx0}to{cx1}".replace("-", "m")
        globals()[name] = type(name, (R2gsSweep,), {"abstract": False, "REFS": refs, "cx0": cx0, "cx1": cx1})
