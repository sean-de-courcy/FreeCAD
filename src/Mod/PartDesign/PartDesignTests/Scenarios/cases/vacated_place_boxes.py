# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr379-r4: a vacated place whose old element has no sketch source (PartDesign
AdditiveBox primitives), so T1''s test (lostOldSource) can't judge the XP pick."""

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Chamfered,
    Scenario,
    X,
    edge,
)
from PartDesignTests.Scenarios import models as m


class BoxMovedIntoAVacatedPlace(Scenario):
    """Three AdditiveBoxes 3600 x 45 x 235 in one body, at y = 0, 2000 and 4045 (d_max ~54.5,
    the boxes 45 thick); a Chamfer (5) on box 1's outer top edge (y = 0, z = 235). Box 1 is
    deleted and box 2 moved to y = 0: its outer top edge lies at the saved place. Nothing of box 1
    is left, so the reference breaks."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review pr379-r4"
    TIER = "F"
    SIZE = 4090
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235
    boxes = (0, 2000, 4045)
    edited = False

    def topEdge(self, y):
        y, H = self.s(y, self.height)
        return edge("line", direction=X, through=(0, y, H))

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        self.made = []
        for i, y in enumerate(self.boxes):
            box = body.newObject("PartDesign::AdditiveBox", "Box%d" % (i + 1))
            box.Length, box.Width, box.Height = L, T, H
            box.Placement.Base = m.V(0, self.s(y), 0)
            self.made.append(box)
        doc.recompute()
        last = self.made[-1]
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (last, self.names(last, self.topEdge(0)))
        chamfer.Size = self.s(5)
        self.ref(
            "chamfer",
            chamfer,
            "Base",
            lambda: BROKEN if self.edited else self.topEdge(0),
            Chamfered(self.s(5)),
        )

    def edit(self, doc):
        first, second = self.made[0], self.made[1]
        body = first.getParentGeoFeatureGroup()
        body.removeObject(first)
        doc.removeObject(first.Name)
        second.Placement.Base = m.V(0, 0, 0)
        self.edited = True


class BoxMovedIntoAVacatedPlaceThick(BoxMovedIntoAVacatedPlace):
    """The same, boxes 100 thick (beyond d_max): tier 3's own nearest; D2's debt family."""

    thickness = 100
    boxes = (0, 2000, 3990)


class RimDraggedNearAVacatedPlace(Scenario):
    """Sketch rims (as vacated_place.RimMovedIntoAVacatedPlace), rim 1's lines deleted and rim 2
    dragged to y = 1..46: its outer top edge 1 off the saved place (G2's reach, not XP's)."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review pr379-r4"
    TIER = "F"
    SIZE = 4090
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235
    rims = (0, 2000, 4045)
    off = 1.0
    edited = False

    def topEdge(self, y):
        y, H = self.s(y, self.height)
        return edge("line", direction=X, through=(0, y, H))

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        geometry = []
        for y in self.rims:
            geometry += m.rectangle(0, self.s(y), L, self.s(y) + T)
        profile = m.sketch(doc, "Profile", geometry, body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.topEdge(0)))
        chamfer.Size = self.s(5)
        self.ref(
            "chamfer",
            chamfer,
            "Base",
            lambda: BROKEN if self.edited else self.topEdge(0),
            Chamfered(self.s(5)),
        )

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        o = self.s(self.off)
        m.moveRectangle(doc.Profile, 0, o, L, o + T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True
