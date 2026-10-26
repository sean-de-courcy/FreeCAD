# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr386-r1s: attacks on ops#504 E2 (a rewrite keeps `from` and the records)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    Broken,
    Filleted,
    PartialWarned,
    Scenario,
    X,
    Z,
    edge,
    pieces,
)
from PartDesignTests.Scenarios import models as m


class RibModel(Scenario):
    """A block 0..20 x 0..10 x 0..10 with a rib (x 8..12, y 3..7, 12 high) and a fillet (radius 1)
    on the block's front top edge. split: the rib moves to y -3..3, so the edge splits into
    x 0..8 and x 12..20 (the fillet takes both pieces, each with `from`); trim: the person removes
    the right piece from the fillet (Python assignment of the left piece alone); merge: the rib
    moves back and the pieces join into the whole edge again."""

    abstract = True
    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r1s"
    TIER = "F"
    steps = ("split", "trim", "merge")

    @staticmethod
    def whole():
        return edge("line", direction=X, through=(0, 0, 10))

    @staticmethod
    def left():
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.CenterOfMass.y) < 1e-6
            and abs(e.CenterOfMass.z - 10) < 1e-6
            and e.CenterOfMass.x < 8,
        )

    @staticmethod
    def right():
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.CenterOfMass.y) < 1e-6
            and abs(e.CenterOfMass.z - 10) < 1e-6
            and e.CenterOfMass.x > 12,
        )

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "RibSketch", m.rectangle(8, 3, 12, 7), body)
        rib = m.pad(body, sketch, 12, name="Rib")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, self.names(rib, self.whole()))
        fillet.Radius = 1
        self.ref("fillet_edge", fillet, "Base", self.expect, Filleted(1))

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, 8, -3, 12, 3)

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch, 8, 3, 12, 7)


class TrimmedPieceMergedBack(RibModel):
    """After the split the person drops the right piece (`fillet.Base = (rib, [left piece])`):
    the fillet is on x 0..8 only. When the rib moves back, no element is x 0..8 of the front edge
    any more; the whole edge would fillet x 8..20, which the person removed. The right answer is
    a loud break, with the whole edge among the candidates."""

    REFS = ("fillet_edge",)

    def expect(self):
        if self.stepName == "split":
            return pieces(self.whole())
        if self.stepName == "trim":
            return self.left()
        if self.stepName == "merge":
            return Broken(self.whole())
        return self.whole()

    def trim(self, doc):
        rib = doc.Rib
        [left] = self.names(rib, self.left())
        doc.Fillet.Base = (rib, [left])


class ReplacedPieceMergedBack(RibModel):
    """As TrimmedPieceMergedBack, but the person drops the left piece and picks the block's back
    top edge instead (two entries: the right piece, then the back edge). After the merge the
    right piece is gone; the whole edge is not what was picked."""

    REFS = ("fillet_edge",)

    @staticmethod
    def backEdge():
        return edge("line", direction=X, through=(0, 10, 10))

    def expect(self):
        if self.stepName == "split":
            return pieces(self.whole())
        if self.stepName == "trim":
            return pieces(
                edge(
                    "line",
                    direction=X,
                    where=lambda e: abs(e.CenterOfMass.z - 10) < 1e-6
                    and (
                        (abs(e.CenterOfMass.y) < 1e-6 and e.CenterOfMass.x > 12)
                        or abs(e.CenterOfMass.y - 10) < 1e-6
                    ),
                )
            )
        if self.stepName == "merge":
            return PartialWarned(self.backEdge())
        return self.whole()

    def trim(self, doc):
        rib = doc.Rib
        [right] = self.names(rib, self.right())
        [back] = self.names(rib, self.backEdge())
        doc.Fillet.Base = (rib, [right, back])
