# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review probes of fork PR 386 round 5 (ops#504, class E's E2, invariant I-S10): the round's
`held` rule (an old entry a dedupe leaves unpaired is held when a paired entry holds its
element) on a split edge's pieces, with a duplicate entry added and removed again."""

from PartDesignTests.Scenarios.harness import Broken, Filleted, Scenario, Warned, X, edge, pieces
from PartDesignTests.Scenarios import models as m


class R5DupRib(Scenario):
    """A block 0..20 x 0..10 x 0..10 (scaled) with a rib (x 8..12, y 3..7, 12 high). The
    reference holds the block's front top edge (y 0, z 10). Steps:
    split   the rib moves to y -3..3: the edge splits into x 0..8 and x 12..20 (both pieces kept)
    dup     the reference written again with the right piece twice (left, right, right)
    dedupe  written again with the duplicate removed (left, right): both pieces still held
    merge   the rib moves back: the edge is whole; the person holds both pieces, so the whole
            edge is the right answer (or a loud break)."""

    abstract = True
    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r5"
    TIER = "F"
    REFS = ("piece",)
    SIZE = 20
    SCALE = 30
    steps = ("split", "dup", "dedupe", "merge")
    PROP = "App::PropertyLinkSubListGlobal"

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

    def left(self):
        return self.frontTop(lambda x: x < self.s(8))

    def right(self):
        return self.frontTop(lambda x: x > self.s(12))

    def expect(self):
        step = self.stepName
        if step is None:
            return self.whole()
        if step in ("split", "dup", "dedupe"):
            return pieces(self.whole())
        return self.whole()

    def model(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 20, 10)), body)
        m.pad(body, profile, self.s(10))
        sketch = m.sketch(doc, "RibSketch", m.rectangle(*self.s(8, 3, 12, 7)), body)
        rib = m.pad(body, sketch, self.s(12), name="Rib")
        doc.recompute()
        return body, rib

    def build(self, doc):
        _, rib = self.model(doc)
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty(self.PROP, "Refs")
        self.setRefs(doc, rib, self.names(rib, self.whole()))
        self.ref("piece", holder, "Refs", self.expect)

    def setRefs(self, doc, rib, subs):
        if self.PROP.startswith("App::PropertyLinkSubList"):
            doc.Holder.Refs = [(rib, tuple(subs))]
        else:
            doc.Holder.Refs = (rib, list(subs))

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(8, -3, 12, 3))

    def dup(self, doc):
        [left] = self.names(doc.Rib, self.left())
        [right] = self.names(doc.Rib, self.right())
        self.setRefs(doc, doc.Rib, [left, right, right])

    def dedupe(self, doc):
        [left] = self.names(doc.Rib, self.left())
        [right] = self.names(doc.Rib, self.right())
        self.setRefs(doc, doc.Rib, [left, right])

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(8, 3, 12, 7))


class R5FilletDupDedupeMerge(R5DupRib):
    """R5DupRib on a fillet's Base (radius 1, scaled; PropertyLinkSub: `from` on the pieces)."""

    def build(self, doc):
        body, rib = self.model(doc)
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, self.names(rib, self.whole()))
        fillet.Radius = self.s(1)
        self.ref("piece", fillet, "Base", self.expect, Filleted(self.s(1)))

    def setRefs(self, doc, rib, subs):
        doc.Fillet.Base = (rib, list(subs))


class R5FilletDupLeftTrimMerge(R5FilletDupDedupeMerge):
    """The left piece added twice (left, right, left), then the right piece kept alone: no
    duplicate holds the left piece, so the person asked for x 12..20 only and the merge breaks
    (the whole edge among the candidates)."""

    steps = ("split", "dupleft", "trim", "merge")

    def expect(self):
        step = self.stepName
        if step == "dupleft":
            return pieces(self.whole())
        if step == "trim":
            return self.right()
        if step == "merge":
            return Broken(self.whole())
        return super().expect()

    def dupleft(self, doc):
        [left] = self.names(doc.Rib, self.left())
        [right] = self.names(doc.Rib, self.right())
        self.setRefs(doc, doc.Rib, [left, right, left])

    def trim(self, doc):
        [right] = self.names(doc.Rib, self.right())
        self.setRefs(doc, doc.Rib, [right])


class R5FilletRedrawDupDedupeMerge(R5FilletDupDedupeMerge):
    """split, the block's profile redrawn (each piece a warned same-place guess), the right piece
    added again by its name (the person's pick beside the guess), the duplicate removed (R2: the
    pick stays), merge: the whole edge (or a loud break)."""

    steps = ("split", "redraw", "dup", "dedupe", "merge")

    def expect(self):
        step = self.stepName
        if step in ("redraw", "dup", "dedupe"):
            return Warned(pieces(self.whole()))
        return super().expect()

    def redraw(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(
            m.polygon([self.s(20, 10), self.s(20, 0), self.s(0, 0), self.s(0, 10)]), False
        )


class R5FilletRedrawDupLeftTrimMerge(R5FilletDupLeftTrimMerge):
    """R5FilletDupLeftTrimMerge with the redraw after the split: the right piece kept alone is
    the guess nobody accepted (warned), and the merge breaks. Debt (decision 125): `wrong` at the
    trim on `integration` and on the PR alike (FilletRedrawThenTrim's), so it isn't scored."""

    abstract = True

    steps = ("split", "redraw", "dupleft", "trim", "merge")

    def expect(self):
        step = self.stepName
        if step == "redraw":
            return Warned(pieces(self.whole()))
        if step == "dupleft":
            return Warned(pieces(self.whole()))
        if step == "trim":
            return Warned(self.right())
        return super().expect()

    def redraw(self, doc):
        R5FilletRedrawDupDedupeMerge.redraw(self, doc)


class R5TwoRibs(R5FilletDupDedupeMerge):
    """A block 0..30 x 0..10 x 0..10 (scaled) with two ribs (x 8..12 and x 18..22, y 3..7, 12
    high) and a fillet (radius 1) on the block's front top edge (y 0, z 10). Steps:
    split   both ribs move to y -3..3: the edge splits into x 0..8, 12..18 and 22..30
    dup     the fillet's Base written with the last piece twice
    dedupe  written with the duplicate removed (three pieces, all held)
    back1   the first rib moves back: the edge is in two pieces, x 0..18 and 22..30; the person
            holds all of the edge, so both pieces
    back2   the second rib moves back: the whole edge."""

    abstract = True
    SIZE = 30
    SCALE = 20
    steps = ("split", "dup", "dedupe", "back1", "back2")
    dupMode = "dup"

    def frontPieces(self):
        return pieces(self.whole())

    def last(self):
        return self.frontTop(lambda x: x > self.s(22))

    def expect(self):
        step = self.stepName
        if step is None or step == "back2":
            return self.whole()
        return pieces(self.whole())

    def model(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 30, 10)), body)
        m.pad(body, profile, self.s(10))
        sk1 = m.sketch(doc, "RibSketch", m.rectangle(*self.s(8, 3, 12, 7)), body)
        m.pad(body, sk1, self.s(12), name="Rib1")
        sk2 = m.sketch(doc, "RibSketch2", m.rectangle(*self.s(18, 3, 22, 7)), body)
        rib = m.pad(body, sk2, self.s(12), name="Rib")
        doc.recompute()
        return body, rib

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(8, -3, 12, 3))
        m.moveRectangle(doc.RibSketch2, *self.s(18, -3, 22, 3))

    def current(self, doc):
        return list(self.whole().select(doc.Rib.Shape))

    def dup(self, doc):
        subs = sorted(self.current(doc), key=lambda n: doc.Rib.Shape.getElement(n).CenterOfMass.x)
        [last] = self.names(doc.Rib, self.last())
        self.setRefs(doc, doc.Rib, subs + [last] if self.dupMode == "dup" else subs)

    def dedupe(self, doc):
        subs = sorted(self.current(doc), key=lambda n: doc.Rib.Shape.getElement(n).CenterOfMass.x)
        self.setRefs(doc, doc.Rib, subs)

    def back1(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(8, 3, 12, 7))

    def back2(self, doc):
        m.moveRectangle(doc.RibSketch2, *self.s(18, 3, 22, 7))


class R5TwoRibsDupDedupeBack(R5TwoRibs):
    abstract = False


class R5TwoRibsIdentityBack(R5TwoRibs):
    """R5TwoRibs without the duplicate (the same three pieces written twice): the baseline."""

    abstract = False
    dupMode = "same"
