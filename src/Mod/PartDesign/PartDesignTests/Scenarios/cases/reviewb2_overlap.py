# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prline-b2-r1 (ops#640, feat/profile-regions): a whole-sketch Pocket whose loops come
to overlap outside the material. Two round holes (r 1) cross a plate's front top edge (y 0); their
centres lie at y -0.5, so each crosses the edge at its centre +-0.866. A move of one hole to 1.85
from the other makes the circles overlap only below y -0.12, in the air in front of the plate:
the cut solid has the same faces and crossings as two apart holes, but the sketch's loops are no
longer simple, so the regions (FaceMakerBuildFace) make the profile instead of the loops. The
references to the untouched hole's crossings must stay; the moved hole's must follow it (the
model of review390r2hs's R2hsMovedWithNewAtOwnPlace, REGRESSED broken -> wrong on this batch)."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Attached, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HALF = math.sqrt(1 - 0.5**2)


class OverlapInAir(Scenario):
    """A plate 200 x 100 x 5 (scale 3); a Pocket through all (symmetric) of the sketch `Holes`
    with circles A (centre x `a`) and B (centre x `b`), r 1, centre y -0.5; a datum point on each
    of the four crossings of the front top edge; `edit` moves B to `b2` by its geometry."""

    abstract = True
    area = "profile_regions"
    CLASSES = ("all",)
    AXES = ("M1", "E1", "X4:600")
    ISSUE = "ops#640"
    FOUND_BY = "review prline-b2-r1"
    TIER = "F"
    SIZE, SCALE = 200, 3
    REFS = ("a_left", "a_right", "b_left", "b_right")
    a, b, b2 = 100.0, 104.0, 101.85

    def crossing(self, name):
        centre = self.a if name.startswith("a") else self.bNow
        x = centre + (-HALF if name.endswith("left") else HALF)
        return vertex(at=self.s(x, 0, 5))

    def build(self, doc):
        self.bNow = self.b
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, profile, self.s(5))
        holes = m.sketch(
            doc,
            "Holes",
            [m.circle(*self.s(self.a, -0.5, 1)), m.circle(*self.s(self.b, -0.5, 1))],
            body,
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile, pocket.Type = holes, 1
        pocket.SideType = "Symmetric"
        pocket.Refine = False
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On_" + name)
            point.AttachmentSupport = [(pocket, self.names(pocket, self.crossing(name))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda n=name: self.crossing(n), Attached())
        doc.recompute()

    def edit(self, doc):
        geometry = doc.Holes.Geometry
        geometry[1].Center = V(*self.s(self.b2, -0.5), 0)
        doc.Holes.Geometry = geometry
        self.bNow = self.b2


class HoleMovedToOverlapInAir(OverlapInAir):
    """B moves from 104 to 101.85: it overlaps A in the air only (loops to regions)."""


class HoleMovedOutOfOverlap(OverlapInAir):
    """B starts at 101.85 (overlapping A in the air: regions) and moves to 104 (loops)."""

    b, b2 = 101.85, 104.0


class HoleMovedWithinOverlap(OverlapInAir):
    """B starts at 101.85 and moves to 101.9: still overlapping in the air (regions both times)."""

    b, b2 = 101.85, 101.9
