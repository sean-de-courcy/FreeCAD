# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review cases of fork PR 386 round 3 (ops#504 E2, invariant I-S10): a piece kept alone by a
rewrite, and the original its later split or guess inherits."""

from PartDesignTests.Scenarios.harness import BROKEN, Filleted, Scenario, X, edge, pieces
from PartDesignTests.Scenarios import models as m


class TrimmedPieceSplitAgainThenMerged(Scenario):
    """A block 0..30 x 0..10 x 10 with two ribs (x 14..18 and x 4..8, y 3..7, 12 high) and a
    fillet (radius 1) on the block's front top edge. Steps:
    split1   the first rib moves to y -3..3: the edge splits into x 0..14 and x 18..30 (the
             fillet takes both pieces, an expansion)
    trim     the person keeps the left piece alone (`fillet.Base = (rib, [x 0..14])`)
    split2   the second rib moves to y -3..3 too: the kept piece splits again (x 0..4, x 8..14)
    merge    both ribs move back: the front top edge is whole again
    The person removed the right piece, so the whole edge is not what the fillet holds: it
    breaks. It never fillets the whole edge, which would cover x 14..30 the person dropped."""

    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r3s"
    TIER = "F"
    REFS = ("fillet_edge",)
    steps = ("split1", "trim", "split2", "merge")

    @staticmethod
    def front(test=lambda x: True):
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.CenterOfMass.z - 10) < 1e-6
            and abs(e.CenterOfMass.y) < 1e-6
            and test(e.CenterOfMass.x),
        )

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 30, 10), body)
        m.pad(body, profile, 10)
        s1 = m.sketch(doc, "Rib1Sketch", m.rectangle(14, 3, 18, 7), body)
        m.pad(body, s1, 12, name="Rib1")
        s2 = m.sketch(doc, "Rib2Sketch", m.rectangle(4, 3, 8, 7), body)
        rib = m.pad(body, s2, 12, name="Rib2")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, self.names(rib, self.front()))
        fillet.Radius = 1
        self.ref("fillet_edge", fillet, "Base", self.expect, Filleted(1))

    def expect(self):
        if self.stepName is None:
            return self.front()
        if self.stepName == "split1":
            return pieces(self.front())
        if self.stepName == "trim":
            return self.front(lambda x: x < 14)
        if self.stepName == "split2":
            return pieces(self.front(lambda x: x < 14))
        return BROKEN

    def split1(self, doc):
        m.moveRectangle(doc.Rib1Sketch, 14, -3, 18, 3)

    def trim(self, doc):
        rib = doc.Rib2
        keep = [s for s in doc.Fillet.Base[1] if rib.Shape.getElement(s).CenterOfMass.x < 14]
        doc.Fillet.Base = (rib, keep)

    def split2(self, doc):
        m.moveRectangle(doc.Rib2Sketch, 4, -3, 8, 3)

    def merge(self, doc):
        m.moveRectangle(doc.Rib1Sketch, 14, 3, 18, 7)
        m.moveRectangle(doc.Rib2Sketch, 4, 3, 8, 7)


class TrimmedRightPieceEarlyThenSplitJoinedMerged(Scenario):
    """A block 0..30 x 0..10 x 10 with two ribs (x 8..12 and x 20..24, y 3..7, 12 high) and a
    fillet (radius 1) on the block's front top edge. Steps:
    split    the second rib moves to y -3..3: the edge splits into x 0..20 and x 24..30 (the
             fillet takes both pieces, an expansion)
    trim     the person keeps the right piece (x 24..30) alone, right after the split
    flicker  the first rib moves to y -3..3 and, in the same step list, back (two recomputes)
    merge    the second rib moves back: the front top edge is whole again
    The person removed the left piece, so the whole edge is not what the fillet holds: it breaks
    (or keeps the right piece x 24..30 only, if that piece is still an element)."""

    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r3s"
    TIER = "F"
    REFS = ("fillet_edge",)
    steps = ("split", "trim", "away", "back", "merge")

    @staticmethod
    def front(test=lambda x: True):
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.CenterOfMass.z - 10) < 1e-6
            and abs(e.CenterOfMass.y) < 1e-6
            and test(e.CenterOfMass.x),
        )

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 30, 10), body)
        m.pad(body, profile, 10)
        s1 = m.sketch(doc, "RibSketch", m.rectangle(8, 3, 12, 7), body)
        m.pad(body, s1, 12, name="Rib")
        s2 = m.sketch(doc, "RibSketch2", m.rectangle(20, 3, 24, 7), body)
        rib = m.pad(body, s2, 12, name="Rib2")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, self.names(rib, self.front()))
        fillet.Radius = 1
        self.ref("fillet_edge", fillet, "Base", self.expect, Filleted(1))

    def expect(self):
        if self.stepName is None:
            return self.front()
        if self.stepName == "split":
            return pieces(self.front())
        if self.stepName in ("trim", "away", "back"):
            return self.front(lambda x: x > 22)
        return BROKEN

    def split(self, doc):
        m.moveRectangle(doc.RibSketch2, 20, -3, 24, 3)

    def trim(self, doc):
        rib = doc.Rib2
        keep = [s for s in doc.Fillet.Base[1] if rib.Shape.getElement(s).CenterOfMass.x > 22]
        doc.Fillet.Base = (rib, keep)

    def away(self, doc):
        m.moveRectangle(doc.RibSketch, 8, -3, 12, 3)

    def back(self, doc):
        m.moveRectangle(doc.RibSketch, 8, 3, 12, 7)

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch2, 20, 3, 24, 7)
