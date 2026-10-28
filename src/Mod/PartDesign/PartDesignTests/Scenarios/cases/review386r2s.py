# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr386-r2s (fork PR 386 round 2): attacks on ops#504 E2 (a rewrite keeps the
records of what it doesn't change)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    Broken,
    Filleted,
    PartialWarned,
    Scenario,
    X,
    edge,
    pieces,
)
from PartDesignTests.Scenarios import models as m


def frontTop(where):
    """The edges of the block's front top side (y 0, z 10) whose centre x satisfies `where`."""
    return edge(
        "line",
        direction=X,
        where=lambda e: abs(e.CenterOfMass.y) < 1e-6
        and abs(e.CenterOfMass.z - 10) < 1e-6
        and where(e.CenterOfMass.x),
    )


class TrimmedPieceKeepsItsGuessRecord(Scenario):
    """A 30 x 10 x 10 block with two ribs (x 8..12 and x 20..24, y 3..7, 12 high) and a fillet
    (radius 1) on the block's front top edge, which the ribs touch. Steps:
    split2   the second rib moves to y -3..3: the edge splits at it, the fillet takes the pieces
             x 0..20 and x 24..30
    split    the first rib moves too: x 0..20 splits again; the piece x 24..30 is found again by
             its place (a tier 3 guess record), the other breaks
    merge    the first rib moves back: x 0..20 is whole again
    trim     the person drops the left piece (Python assignment of the right piece alone)
    merge2   the second rib moves back: the edge is whole again.
    The person asked for x 24..30 alone; the stretch they dropped was never theirs again. The
    right answer after merge2 is a loud break (the whole edge among the candidates), as for
    TrimmedPieceMergedBack. The guess record of the kept piece (the whole edge's name, from before
    the splits) must not snap it back to the whole edge."""

    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r2s"
    TIER = "F"
    REFS = ("fillet_edge",)
    steps = ("split2", "split", "merge", "trim", "merge2")

    @staticmethod
    def whole():
        return frontTop(lambda x: True)

    @staticmethod
    def right():
        return frontTop(lambda x: x > 24)

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 30, 10), body)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "RibSketch", m.rectangle(8, 3, 12, 7), body)
        m.pad(body, sketch, 12, name="Rib")
        sketch2 = m.sketch(doc, "RibSketch2", m.rectangle(20, 3, 24, 7), body)
        rib2 = m.pad(body, sketch2, 12, name="Rib2")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib2, self.names(rib2, self.whole()))
        fillet.Radius = 1
        self.ref("fillet_edge", fillet, "Base", self.expect, Filleted(1))

    def expect(self):
        step = self.stepName
        if step is None:
            return self.whole()
        if step == "split2":
            return pieces(self.whole())
        if step == "split":
            return PartialWarned(self.right())
        if step == "merge":
            return pieces(frontTop(lambda x: x < 20 or x > 24))
        if step == "trim":
            return self.right()
        return Broken(self.whole())

    def split2(self, doc):
        m.moveRectangle(doc.RibSketch2, 20, -3, 24, 3)

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, 8, -3, 12, 3)

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch, 8, 3, 12, 7)

    def trim(self, doc):
        rib2 = doc.Rib2
        [right] = self.names(rib2, self.right())
        doc.Fillet.Base = (rib2, [right])

    def merge2(self, doc):
        m.moveRectangle(doc.RibSketch2, 20, 3, 24, 7)

