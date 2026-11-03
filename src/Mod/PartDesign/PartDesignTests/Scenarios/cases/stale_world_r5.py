# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr564opus-r5 (ops#564 round 5, the rebase onto rule PS): a record's world (the `:s` flag
on its marks, ops#549 PS) when the referenced element is the same in both worlds.

The model: a Body with a block 20 x 10 x 10 (sketch `Base` on XY, rectangle (0, 0)-(20, 10), padded
10) and a Pocket `Slot` 4 deep from a sketch at the block's top, rectangle (5, 3)-(15, 7). A datum
point on the block's outer top corner (0, 0, 10), through the Slot (the Slot carries the corner).

`sup` suppresses the Slot: the corner is the same element, at the same place, in both worlds. The
datum's record is taken again by the target's batch with the Slot flagged (PS: from then on the
edits are judged as on a model without the Slot). `taller` makes the block 12 high while the Slot
stays suppressed (its sketch with the top): the corner moves to (0, 0, 12), the same element.

- `StaleWorldTaller`: then `uns`. Right: the corner (0, 0, 12) throughout (as
  SlotSuppressedThenTaller).
- `StaleWorldCornerCut`: in `taller` the Slot's sketch also becomes the rectangle (-1, -1)-(5, 3),
  2 deep, so at `uns` the pocket cuts the corner's column from z = 12 down to z = 10: the corner
  (0, 0, 12) is gone (right: BROKEN). The pocket's floor leaves a vertex at (0, 0, 10), the place
  the corner had before `taller`.
Expected results are defined by the geometry above; no file is used.
"""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector


class StaleWorldBase(Scenario):
    abstract = True
    area = "failure pass-through"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:600")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r5"
    TIER = "F"
    REFS = ("corner_point",)
    steps = ("sup", "taller", "uns")
    height = 10

    def corner(self):
        return vertex((0, 0, self.height))

    def build(self, doc):
        self.body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), self.body)
        self.block = m.pad(self.body, base, 10, "Block")
        self.block.Refine = False
        doc.recompute()
        self.slotSketch = m.sketch(doc, "SlotSketch", m.rectangle(5, 3, 15, 7), self.body, z=10)
        self.slot = m.pocket(self.body, self.slotSketch, 4, "Slot")
        self.slot.Refine = False
        doc.recompute()
        point = self.body.newObject("PartDesign::Point", "CornerPoint")
        point.AttachmentSupport = [(self.slot, self.names(self.slot, self.corner()))]
        point.MapMode = "Vertex"
        doc.recompute()
        self.ref("corner_point", point, "AttachmentSupport", self.want, Attached())

    def want(self):
        return self.corner()

    def sup(self, doc):
        self.slot.Suppressed = True

    def taller(self, doc):
        self.height = 12
        self.block.Length = 12
        self.slotSketch.Placement = App.Placement(V(0, 0, 12), App.Rotation())

    def uns(self, doc):
        self.slot.Suppressed = False


class StaleWorldTaller(StaleWorldBase):
    """Suppressed, the block 12 high meanwhile, back: the corner throughout."""


class StaleWorldCornerCut(StaleWorldBase):
    """Suppressed, the block 12 high and the Slot moved onto the corner (2 deep) meanwhile, back:
    the corner (0, 0, 12) is cut away (BROKEN); a vertex is left at (0, 0, 10), where the corner
    was before the block grew."""

    def want(self):
        return BROKEN if self.stepName == "uns" else self.corner()

    def taller(self, doc):
        super().taller(doc)
        m.moveRectangle(self.slotSketch, -1, -1, 5, 3)
        self.slot.Length = 2


class StaleWorldAttachedSuppressed(StaleWorldBase):
    """The datum taken while the Slot is suppressed (its record flags it), the Slot back, then
    suppressed again together with the block 12 high: the corner (0, 0, 12) at every step."""

    steps = ("uns", "supTaller")

    def build(self, doc):
        self.body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), self.body)
        self.block = m.pad(self.body, base, 10, "Block")
        self.block.Refine = False
        doc.recompute()
        self.slotSketch = m.sketch(doc, "SlotSketch", m.rectangle(5, 3, 15, 7), self.body, z=10)
        self.slot = m.pocket(self.body, self.slotSketch, 4, "Slot")
        self.slot.Refine = False
        self.slot.Suppressed = True
        doc.recompute()
        point = self.body.newObject("PartDesign::Point", "CornerPoint")
        point.AttachmentSupport = [(self.slot, self.names(self.slot, self.corner()))]
        point.MapMode = "Vertex"
        doc.recompute()
        self.ref("corner_point", point, "AttachmentSupport", self.want, Attached())

    def supTaller(self, doc):
        self.sup(doc)
        self.taller(doc)
