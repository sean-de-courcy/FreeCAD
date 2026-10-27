# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr386-r3 (fork PR 386 round 3): a piece of a split edge kept alone by a rewrite, in
the property classes that keep no `from` (PropertyLinkSubList, PropertyXLinkSub: their pieces
carry only `expanded` records), and with the kept piece nearly the whole edge. The review's
cases ListLongPieceTrimmedMergedBack and ListTwoSplitsTrimmedMergedBack (a list's `piece` guess
at the split, wrong on integration too: debt) are not in the corpus."""

from PartDesignTests.Scenarios.harness import (
    Broken,
    Filleted,
    Scenario,
    Warned,
    X,
    edge,
    pieces,
)
from PartDesignTests.Scenarios import models as m


class R3Rib(Scenario):
    """A block 0..L x 0..10 x 0..10 with a rib (x a..b, y 3..7, 12 high). The reference holds the
    block's front top edge (y 0, z 10). split: the rib moves to y -3..3, so the edge splits into
    x 0..a and x b..L; trim: the person keeps the right piece alone (Python assignment of that
    piece); merge: the rib moves back and the edge is whole again. The person asked for x b..L;
    the whole edge also covers x 0..b, which they removed: a loud break with the whole edge among
    the candidates is the right answer (as for review386s.TrimmedPieceMergedBack), never the
    whole edge silently."""

    abstract = True
    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r3"
    TIER = "F"
    REFS = ("piece",)
    steps = ("split", "trim", "merge")
    PROP = "App::PropertyLinkSubListGlobal"
    L, a, b = 20, 8, 12

    def frontTop(self, where):
        tol = 1e-6 * max(1.0, self.scale)
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.CenterOfMass.y) < tol
            and abs(e.CenterOfMass.z - self.s(10)) < tol
            and where(e.CenterOfMass.x),
        )

    def whole(self):
        return self.frontTop(lambda x: True)

    def right(self):
        return self.frontTop(lambda x: x > self.s(self.b))

    def expect(self):
        step = self.stepName
        if step is None:
            return self.whole()
        if step == "split":
            return pieces(self.whole())
        if step == "trim":
            return self.right()
        return Broken(self.whole())

    def model(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, self.L, 10)), body)
        m.pad(body, profile, self.s(10))
        sketch = m.sketch(doc, "RibSketch", m.rectangle(*self.s(self.a, 3, self.b, 7)), body)
        rib = m.pad(body, sketch, self.s(12), name="Rib")
        doc.recompute()
        return rib

    def build(self, doc):
        rib = self.model(doc)
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty(self.PROP, "Refs")
        self.setRefs(holder, rib, self.names(rib, self.whole()))
        self.ref("piece", holder, "Refs", self.expect)

    def setRefs(self, holder, rib, subs):
        if self.PROP.startswith("App::PropertyLinkSubList"):
            holder.Refs = [(rib, tuple(subs))]
        else:
            holder.Refs = (rib, list(subs))

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(self.a, -3, self.b, 3))

    def trim(self, doc):
        rib = doc.Rib
        [right] = self.names(rib, self.right())
        self.setRefs(doc.Holder, rib, [right])

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(self.a, 3, self.b, 7))


class ListPieceTrimmedMergedBack(R3Rib):
    """R3Rib with the reference in a holder's App::PropertyLinkSubListGlobal."""


class XLinkSubPieceTrimmedMergedBack(R3Rib):
    """R3Rib with the reference in a holder's App::PropertyXLinkSub."""

    PROP = "App::PropertyXLinkSub"


class FilletLongPieceTrimmedMergedBack(R3Rib):
    """ListLongPieceTrimmedMergedBack with the reference a fillet's Base (radius 0.5, LinkSub:
    `from` and the `expanded` record), at ~600 mm."""

    SIZE = 30
    SCALE = 20
    L, a, b = 30, 2, 4

    def build(self, doc):
        rib = self.model(doc)
        fillet = rib.getParentGeoFeatureGroup().newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, self.names(rib, self.whole()))
        fillet.Radius = self.s(0.5)
        self.ref("piece", fillet, "Base", self.expect, Filleted(self.s(0.5)))

    def trim(self, doc):
        rib = doc.Rib
        [right] = self.names(rib, self.right())
        doc.Fillet.Base = (rib, [right])


class FilletPieceTrimmedEarlyThenSplitMerged(Scenario):
    """review386r2s.TrimmedPieceKeepsItsGuessRecord with the trim first. A 30 x 10 x 10 block
    with two ribs (x 8..12 and x 20..24, y 3..7, 12 high) and a fillet (radius 1) on the block's
    front top edge. Steps:
    split2   the second rib moves to y -3..3: the edge splits at it, the fillet takes the pieces
             x 0..20 and x 24..30 (`from`, `expanded` records)
    trim     the person keeps the right piece x 24..30 alone (Python assignment)
    split    the first rib moves too (the edge x 0..20, no longer referenced, splits)
    merge    the first rib moves back
    merge2   the second rib moves back: the edge is whole again.
    The person asked for x 24..30 alone; the stretch they dropped was never theirs again: after
    merge2 a loud break (the whole edge among the candidates) is the right answer, never the
    whole edge silently."""

    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r3"
    TIER = "F"
    REFS = ("fillet_edge",)
    steps = ("split2", "trim", "split", "merge", "merge2")

    @staticmethod
    def frontTop(where):
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.CenterOfMass.y) < 1e-6
            and abs(e.CenterOfMass.z - 10) < 1e-6
            and where(e.CenterOfMass.x),
        )

    def whole(self):
        return self.frontTop(lambda x: True)

    def right(self):
        return self.frontTop(lambda x: x > 24)

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 30, 10), body)
        m.pad(body, profile, 10)
        m.pad(body, m.sketch(doc, "RibSketch", m.rectangle(8, 3, 12, 7), body), 12, name="Rib")
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
        if step in ("trim", "split", "merge"):
            return self.right()
        return Broken(self.whole())

    def split2(self, doc):
        m.moveRectangle(doc.RibSketch2, 20, -3, 24, 3)

    def trim(self, doc):
        rib2 = doc.Rib2
        [right] = self.names(rib2, self.right())
        doc.Fillet.Base = (rib2, [right])

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, 8, -3, 12, 3)

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch, 8, 3, 12, 7)

    def merge2(self, doc):
        m.moveRectangle(doc.RibSketch2, 20, 3, 24, 7)


class FilletPieceTrimmedEarlyMerged(FilletPieceTrimmedEarlyThenSplitMerged):
    """FilletPieceTrimmedEarlyThenSplitMerged without the first rib's split and merge (the
    control: the right piece kept alone with its `expanded` record, then the edge whole)."""

    steps = ("split2", "trim", "merge2")


class FilletPieceTrimmedEarlyThenRedrawn(FilletPieceTrimmedEarlyThenSplitMerged):
    """FilletPieceTrimmedEarlyThenSplitMerged with the block's profile drawn again (from its
    right back corner, the other way round: the same geometry, new IDs) in place of the first
    rib's split and merge: the kept piece becomes a warned same-place guess. After merge2: a
    loud break, never the whole edge silently."""

    steps = ("split2", "trim", "redraw", "merge2")

    def expect(self):
        if self.stepName == "redraw":
            # the kept piece found again by its place: a guess, so warned (I-S1, I-P1)
            return Warned(self.right())
        return super().expect()

    def redraw(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(30, 10), (30, 0), (0, 0), (0, 10)]), False)
