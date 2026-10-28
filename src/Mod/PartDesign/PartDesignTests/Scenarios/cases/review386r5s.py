# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review cases of fork PR 386 round 5 (ops#504, class E's E2, invariant I-S10), Sonnet review:
a block 0..20 x 0..10 x 0..10 (scaled) with a rib (x 8..12, y 3..7, 12 high); the rib moves to
y -3..3 and splits the front top edge (y 0, z 10) into two pieces; the back top edge (y 10, z 10)
stays whole. The rewrites compose the round's three changes (dedupe holds, expansion keep,
index records) with count changes, lone pieces and a redraw."""

from PartDesignTests.Scenarios.harness import (
    Broken,
    Filleted,
    PartialWarned,
    Scenario,
    Warned,
    X,
    edge,
    pieces,
)
from PartDesignTests.Scenarios import models as m


class R5Base(Scenario):
    abstract = True
    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r5s"
    TIER = "F"
    REFS = ("ref",)
    SIZE = 20
    SCALE = 30

    def topEdge(self, y, where=lambda x: True):
        tol = 1e-6 * max(1.0, self.scale)
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.CenterOfMass.y - self.s(y)) < tol
            and abs(e.CenterOfMass.z - self.s(10)) < tol
            and where(e.CenterOfMass.x),
        )

    def whole(self):
        return self.topEdge(0)

    def left(self):
        return self.topEdge(0, lambda x: x < self.s(8))

    def right(self):
        return self.topEdge(0, lambda x: x > self.s(12))

    def back(self):
        return self.topEdge(10)

    def wholePlusBack(self):
        tol = 1e-6 * max(1.0, self.scale)
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.CenterOfMass.z - self.s(10)) < tol
            and (abs(e.CenterOfMass.y) < tol or abs(e.CenterOfMass.y - self.s(10)) < tol),
        )

    def model(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 20, 10)), body)
        m.pad(body, profile, self.s(10))
        sketch = m.sketch(doc, "RibSketch", m.rectangle(*self.s(8, 3, 12, 7)), body)
        rib = m.pad(body, sketch, self.s(12), name="Rib")
        doc.recompute()
        return body, rib

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(8, -3, 12, 3))

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(8, 3, 12, 7))

    def redraw(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(
            m.polygon([self.s(20, 10), self.s(20, 0), self.s(0, 0), self.s(0, 10)]), False
        )

    # the reference is a fillet's Base (PropertyLinkSub, `from` on the pieces) unless PROP says
    PROP = None

    def build(self, doc):
        body, rib = self.model(doc)
        if self.PROP is None:
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (rib, self.names(rib, self.whole()))
            fillet.Radius = self.s(1)
            self.ref("ref", fillet, "Base", self.expect, Filleted(self.s(1)))
        else:
            holder = doc.addObject("App::FeaturePython", "Holder")
            holder.addProperty(self.PROP, "Refs")
            holder.Refs = [(rib, tuple(self.names(rib, self.whole())))]
            self.ref("ref", holder, "Refs", self.expect)

    def setRefs(self, doc, subs):
        rib = doc.Rib
        if self.PROP is None:
            doc.Fillet.Base = (rib, list(subs))
        else:
            doc.Holder.Refs = [(rib, tuple(subs))]

    def namesOf(self, doc, *predicates):
        out = []
        for p in predicates:
            out += self.names(doc.Rib, p)
        return out


class R5PiecesPlusBackThenMerge(R5Base):
    """split (pieces), extend (Base written with both pieces and the back top edge: a count
    change, index names), merge: the whole front edge and the back edge."""

    steps = ("split", "extend", "merge")

    def expect(self):
        step = self.stepName
        if step is None:
            return self.whole()
        if step == "split":
            return pieces(self.whole())
        if step == "extend":
            return pieces(self.wholePlusBack())
        return pieces(self.wholePlusBack())

    def extend(self, doc):
        self.setRefs(doc, self.namesOf(doc, self.left(), self.right(), self.back()))


class R5LonePieceAndBackThenMerge(R5Base):
    """split, trim (the right piece and the back edge, the same count as the pieces were),
    merge: the person asked for the right piece only: its reference breaks (the whole edge among
    the candidates) and the fillet runs on the back edge with the warning."""

    steps = ("split", "trim", "merge")

    def expect(self):
        step = self.stepName
        if step is None:
            return self.whole()
        if step == "split":
            return pieces(self.whole())
        if step == "trim":
            tol = 1e-6 * max(1.0, self.scale)
            return pieces(
                edge(
                    "line",
                    direction=X,
                    where=lambda e: abs(e.CenterOfMass.z - self.s(10)) < tol
                    and (
                        abs(e.CenterOfMass.y - self.s(10)) < tol
                        or (abs(e.CenterOfMass.y) < tol and e.CenterOfMass.x > self.s(12))
                    ),
                )
            )
        return PartialWarned(self.back())

    def trim(self, doc):
        self.setRefs(doc, self.namesOf(doc, self.right(), self.back()))


class R5RedrawExtendMerge(R5Base):
    """split, redraw (a warned guess of each piece), extend (both pieces and the back edge
    written by index: the back edge's name is a guess too), merge: the whole edge and the back
    edge. The pieces keep their expansion and merge. Debt (decision 125):
    `wrong` on `integration` and on the PR alike, so it isn't scored."""

    abstract = True

    steps = ("split", "redraw", "extend", "merge")

    def expect(self):
        step = self.stepName
        if step is None:
            return self.whole()
        if step == "split":
            return pieces(self.whole())
        if step == "redraw":
            return Warned(pieces(self.whole()))
        if step == "extend":
            return pieces(self.wholePlusBack())
        return pieces(self.wholePlusBack())

    def extend(self, doc):
        self.setRefs(doc, self.namesOf(doc, self.left(), self.right(), self.back()))


class R5RedrawLonePieceDropBackMerge(R5Base):
    """split, extend (pieces + back), redraw, shrink (only the right piece: the left piece and
    the back edge removed), merge: a loud break (the person kept one piece). Debt (decision 125):
    `wrong` on `integration` and on the PR alike, so it isn't scored."""

    abstract = True

    steps = ("split", "extend", "redraw", "shrink", "merge")

    def expect(self):
        step = self.stepName
        if step is None:
            return self.whole()
        if step == "split":
            return pieces(self.whole())
        if step == "extend":
            return pieces(self.wholePlusBack())
        if step == "redraw":
            return Warned(pieces(self.wholePlusBack()))
        if step == "shrink":
            return Warned(self.right())
        return Broken(self.whole())

    def extend(self, doc):
        self.setRefs(doc, self.namesOf(doc, self.left(), self.right(), self.back()))

    def shrink(self, doc):
        self.setRefs(doc, self.namesOf(doc, self.right()))
