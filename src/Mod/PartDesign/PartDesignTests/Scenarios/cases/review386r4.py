# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review cases of fork PR 386 round 4 (ops#504, class E's E2, invariant I-S10): a piece of a
split edge kept alone after the block's profile is drawn again (a warned same-place guess of
each piece). The round 4 rule ends every guess record of a lone piece that names its group's
original; the redraw's guess of the kept piece is such a record, so the rewrite may take the
redraw's warning with it."""

from PartDesignTests.Scenarios.harness import Broken, Filleted, Scenario, Warned, X, edge, pieces
from PartDesignTests.Scenarios import models as m


class R4RedrawRib(Scenario):
    """A block 0..20 x 0..10 x 0..10 (scaled) with a rib (x 8..12, y 3..7, 12 high). The
    reference holds the block's front top edge (y 0, z 10). Steps:
    split   the rib moves to y -3..3: the edge splits into x 0..8 and x 12..20 (both pieces kept)
    redraw  the block's profile is drawn again from its right back corner the other way round
            (the same geometry, new IDs): each piece is a warned same-place guess
    trim    the person keeps the right piece alone (Python assignment of it): the piece the
            solver guessed and nobody accepted, so its owner stays warned
    merge   the rib moves back: the edge is whole; the person asked for x 12..20 only, so a loud
            break (the whole edge among the candidates) is the right answer."""

    abstract = True
    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r4"
    TIER = "F"
    REFS = ("piece",)
    SIZE = 20
    SCALE = 30
    steps = ("split", "redraw", "trim", "merge")
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

    def right(self):
        return self.frontTop(lambda x: x > self.s(12))

    def expect(self):
        step = self.stepName
        if step is None:
            return self.whole()
        if step == "split":
            return pieces(self.whole())
        if step == "redraw":
            return Warned(pieces(self.whole()))
        if step == "trim":
            return Warned(self.right())
        return Broken(self.whole())

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

    def redraw(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(
            m.polygon([self.s(20, 10), self.s(20, 0), self.s(0, 0), self.s(0, 10)]), False
        )

    def trim(self, doc):
        [right] = self.names(doc.Rib, self.right())
        self.setRefs(doc, doc.Rib, [right])

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(8, 3, 12, 7))


class FilletRedrawThenTrim(R4RedrawRib):
    """R4RedrawRib with the reference a fillet's Base (radius 1, scaled; PropertyLinkSub: `from`
    on the pieces). Debt (decision 125): `wrong` at the trim on `integration` and on the PR alike
    (the warning goes with the record the rewrite ends), so it isn't scored here; it is the base
    of the two cases below."""

    abstract = True

    def build(self, doc):
        body, rib = self.model(doc)
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, self.names(rib, self.whole()))
        fillet.Radius = self.s(1)
        self.ref("piece", fillet, "Base", self.expect, Filleted(self.s(1)))

    def setRefs(self, doc, rib, subs):
        doc.Fillet.Base = (rib, list(subs))


class FilletRedrawIdentityThenMerge(FilletRedrawThenTrim):
    """FilletRedrawThenTrim, but the rewrite assigns Base its own value (both pieces kept, as a
    dialog's OK): both stay warned guesses; after the merge the fillet is on the whole edge
    again (a guess of it, or the edge plainly)."""

    steps = ("split", "redraw", "identity", "merge")

    def expect(self):
        step = self.stepName
        if step == "identity":
            return Warned(pieces(self.whole()))
        if step == "merge":
            return self.whole()
        return super().expect()

    def identity(self, doc):
        doc.Fillet.Base = doc.Fillet.Base


class FilletTrimThenRedrawIdentity(FilletRedrawThenTrim):
    """The trim before the redraw, then an identity rewrite: split, trim (the right piece kept
    alone: the person's exact pick), redraw (the kept piece a warned same-place guess),
    identity (Base assigned its own value: the guess stays warned), merge (a loud break)."""

    steps = ("split", "trim2", "redraw", "identity", "merge")

    def expect(self):
        step = self.stepName
        if step == "trim2":
            return self.right()
        if step in ("redraw", "identity"):
            return Warned(self.right())
        return super().expect()

    def trim2(self, doc):
        self.trim(doc)

    def identity(self, doc):
        doc.Fillet.Base = doc.Fillet.Base


class ListIndexRewriteAfterRedrawThenWiden(Scenario):
    """A holder's list holds the pad's two vertical edges at (20, 0) and (0, 10) of a 20 x 10 x 10
    block (scaled). redraw: the profile drawn again from its right back corner the other way
    round (both warned same-place guesses); rewrite: the list written back by index names as
    Python reads it, in the other order with the edge at (20, 10) added between them (a count
    change, a reorder, index-only subs); widen: the redrawn right line moves to x 25. The two
    guessed entries follow their edges, warned; the added edge follows to (25, 10)."""

    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r4"
    TIER = "F"
    REFS = ("entries",)
    SIZE = 25
    SCALE = 24
    steps = ("redraw", "rewrite", "widen")
    width = 20

    def vertical(self, x, y):
        tol = 1e-6 * max(1.0, self.scale)
        return lambda e: (
            abs(e.Vertexes[0].Point.x - self.s(x)) < tol
            and abs(e.Vertexes[0].Point.y - self.s(y)) < tol
            and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < tol
            and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < tol
        )

    def one(self, x, y):
        return edge("line", where=self.vertical(x, y))

    def edges(self, points):
        tests = [self.vertical(x, y) for x, y in points]
        return pieces(edge("line", where=lambda e: any(t(e) for t in tests)))

    def expect(self):
        step = self.stepName
        if step is None:
            return self.edges([(20, 0), (0, 10)])
        if step == "redraw":
            return Warned(self.edges([(20, 0), (0, 10)]))
        if step == "rewrite":
            return Warned(self.edges([(20, 0), (0, 10), (20, 10)]))
        return Warned(self.edges([(25, 0), (0, 10), (25, 10)]))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 20, 10)), body)
        pad = m.pad(body, profile, self.s(10))
        doc.recompute()
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSubListGlobal", "Refs")
        subs = self.names(pad, self.one(20, 0)) + self.names(pad, self.one(0, 10))
        holder.Refs = [(pad, tuple(subs))]
        self.ref("entries", holder, "Refs", self.expect)

    def redraw(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(
            m.polygon([self.s(20, 10), self.s(20, 0), self.s(0, 0), self.s(0, 10)]), False
        )

    def rewrite(self, doc):
        pad = doc.Pad
        [(_, held)] = doc.Holder.Refs
        added = self.names(pad, self.one(20, 10))[0]
        doc.Holder.Refs = [(pad, (held[1], added, held[0]))]

    def widen(self, doc):
        # the redrawn polygon's lines: 0 (20,10)-(20,0) is the right side; move it to x 25,
        # keeping its neighbours joined
        m.setLines(
            doc.Profile,
            {
                0: (self.s(25, 10), self.s(25, 0)),
                1: (self.s(25, 0), self.s(0, 0)),
                3: (self.s(0, 10), self.s(25, 10)),
            },
        )
