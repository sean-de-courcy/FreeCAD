# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review cases for fork PR 386 (ops#504 E2, I-S10): a rewrite keeps the records of the
references it doesn't change. Composed edits after the rewrite, reorders, re-picks of another
element, other property classes and other scales. A pad's profile, a rectangle 0..20 x 0..10
(scaled by `self.scale`) padded 10, is drawn again from its right back corner the other way round
(the same geometry, new IDs: references into the pad become warned guesses in the same place)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Scenario,
    Settled,
    Warned,
    X,
    Z,
    edge,
    pieces,
)
from PartDesignTests.Scenarios import models as m


def zEdgeAt(scenario, x, y):
    return edge("line", direction=Z, through=scenario.s(x, y, 0))


def zEdgesAt(scenario, points):
    pts = [scenario.s(x, y) for x, y in points]
    tol = 1e-6 * max(1.0, scenario.scale)
    return pieces(
        edge(
            "line",
            direction=Z,
            where=lambda e: any(
                abs(e.Vertexes[0].Point.x - x) < tol and abs(e.Vertexes[0].Point.y - y) < tol
                for x, y in pts
            ),
        )
    )


class ReviewRewrite(Scenario):
    abstract = True
    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r1"
    TIER = "F"
    SIZE = 20
    SCALE = 30  # 600 mm
    PROP = "App::PropertyLinkSubListGlobal"

    def padded(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 20, 10)), body)
        pad = m.pad(body, profile, self.s(10))
        doc.recompute()
        return body, pad

    def holder(self, doc, pad, predicates):
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty(self.PROP, "Refs")
        subs = [self.names(pad, p)[0] for p in predicates]
        self.setRefs(holder, pad, subs)
        return holder

    def setRefs(self, holder, pad, subs):
        if self.PROP.startswith("App::PropertyLinkSubList") or self.PROP.startswith(
            "App::PropertyXLinkSubList"
        ):
            holder.Refs = [(pad, tuple(subs))]
        else:
            holder.Refs = (pad, list(subs))

    def heldSubs(self, holder):
        value = holder.Refs
        if isinstance(value, list):
            return [s for _, ss in value for s in (ss if isinstance(ss, (list, tuple)) else [ss])]
        return list(value[1])

    def redraw(self, doc):
        """Profile line 0: right (20,10)-(20,0), 1: bottom (20,0)-(0,0), 2: left, 3: top."""
        doc.Profile.deleteAllGeometry()
        pts = [self.s(x, y) for x, y in ((20, 10), (20, 0), (0, 0), (0, 10))]
        doc.Profile.addGeometry(m.polygon(pts), False)

    def widen(self, doc):
        """Moves the redrawn right line from x 20 to x 25 (the lines keep their IDs)."""
        a, b, c, d = (self.s(x, y) for x, y in ((25, 10), (25, 0), (0, 0), (0, 10)))
        m.setLines(doc.Profile, {0: (a, b), 1: (b, c), 3: (d, a)})


class RewriteThenWiden(ReviewRewrite):
    """A holder's list references the pad's vertical edge at (20, 0). Steps: redraw (warned
    guess), rewrite (the same value assigned again, by index names), widen (the redrawn right
    line moves to x 25: the edge it makes is at (25, 0)). The reference must follow its edge to
    (25, 0) after the widen, as an exact pick of the redrawn edge would."""

    REFS = ("followed",)
    steps = ("redraw", "rewrite", "widen")

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, [zEdgeAt(self, 20, 0)])

        def expect():
            if self.stepName == "widen":
                return zEdgeAt(self, 25, 0)
            return zEdgeAt(self, 20, 0) if self.stepName is None else Warned(zEdgeAt(self, 20, 0))

        self.ref("followed", doc.Holder, "Refs", expect)

    def rewrite(self, doc):
        doc.Holder.Refs = doc.Holder.Refs


class RewriteThenWidenXLinkSub(RewriteThenWiden):
    """RewriteThenWiden with the holder's property an App::PropertyXLinkSub."""

    PROP = "App::PropertyXLinkSub"


class RewriteThenWidenLinkSub(RewriteThenWiden):
    """RewriteThenWiden with the holder's property an App::PropertyLinkSub."""

    PROP = "App::PropertyLinkSub"


class ReorderTwoGuessed(ReviewRewrite):
    """The holder references the vertical edges at (20, 0) and (0, 0); after the redraw both are
    warned guesses; the rewrite writes them back in the other order by index name; then widen.
    Both must hold their edges, warned, and follow to (25, 0) and (0, 0)."""

    REFS = ("both",)
    steps = ("redraw", "rewrite", "widen")

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, [zEdgeAt(self, 20, 0), zEdgeAt(self, 0, 0)])

        def expect():
            if self.stepName == "widen":
                return zEdgesAt(self, [(25, 0), (0, 0)])
            both = zEdgesAt(self, [(20, 0), (0, 0)])
            return both if self.stepName is None else Warned(both)

        self.ref("both", doc.Holder, "Refs", expect)

    def rewrite(self, doc):
        subs = self.heldSubs(doc.Holder)
        self.setRefs(doc.Holder, doc.Pad, list(reversed(subs)))


class RepickAnotherStartsFresh(ReviewRewrite):
    """The holder's guessed edge at (20, 0) is re-picked as the edge at (0, 10) by index: a pick
    of another element is the pick, plain (no record carried over), and stays on its edge
    through the widen."""

    REFS = ("repicked",)
    steps = ("redraw", "rewrite", "widen")

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, [zEdgeAt(self, 20, 0)])

        def expect():
            if self.stepName is None:
                return zEdgeAt(self, 20, 0)
            if self.stepName == "redraw":
                return Warned(zEdgeAt(self, 20, 0))
            return Settled(zEdgeAt(self, 0, 10))

        self.ref("repicked", doc.Holder, "Refs", expect)

    def rewrite(self, doc):
        self.setRefs(doc.Holder, doc.Pad, [self.names(doc.Pad, zEdgeAt(self, 0, 10))[0]])


class AddThenRemoveThenWiden(ReviewRewrite):
    """The guessed edge at (20, 0); the rewrite adds the edge at (0, 0) after it, then removes
    the first entry again and re-adds it after the second (two count changes, the guessed entry
    moved from index 0 to index 1); then widen."""

    REFS = ("moved_entry",)
    steps = ("redraw", "rewrite", "widen")

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, [zEdgeAt(self, 20, 0)])

        def expect():
            if self.stepName == "widen":
                return zEdgesAt(self, [(25, 0), (0, 0)])
            if self.stepName == "rewrite":
                return zEdgesAt(self, [(20, 0), (0, 0)])  # the re-added entry is a new pick
            return zEdgeAt(self, 20, 0) if self.stepName is None else Warned(zEdgeAt(self, 20, 0))

        self.ref("moved_entry", doc.Holder, "Refs", expect)

    def rewrite(self, doc):
        [held] = self.heldSubs(doc.Holder)
        other = self.names(doc.Pad, zEdgeAt(self, 0, 0))[0]
        self.setRefs(doc.Holder, doc.Pad, [held, other])
        self.setRefs(doc.Holder, doc.Pad, [other])
        self.setRefs(doc.Holder, doc.Pad, [other, held])


class PieceKeptThenMergedBack(Scenario):
    """A block 0..20 x 0..10 x 10 (scaled) with a rib 4 wide padded 12 from its top inside the
    block (x 8..12, y 3..7); a fillet on the block's front top edge (y 0, z 10). Steps: `split`,
    the rib moves to straddle the front (y -3..3), splitting the edge into x 0..8 and x 12..20:
    the fillet takes both pieces (an expansion, each saved with `from`); `rewrite`, the user
    keeps only the left piece (Base set to it alone, by its index name); `back`, the rib moves
    back inside (y 3..7): the front edge is whole again. The user's one piece is now part of a
    merged whole: per I-C4 it breaks with the whole as candidate; it is never widened silently to
    the whole edge (the other piece was removed by the user)."""

    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E9", "SPM")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r1"
    TIER = "F"
    SIZE = 20
    SCALE = 30
    REFS = ("kept_piece",)
    steps = ("split", "rewrite", "back")

    def front(self):
        return edge("line", direction=X, through=self.s(0, 0, 10))

    def leftPiece(self):
        limit = self.s(8) + 1e-6 * self.scale
        return edge(
            "line",
            direction=X,
            through=self.s(0, 0, 10),
            where=lambda e: max(v.Point.x for v in e.Vertexes) <= limit,
        )

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 20, 10)), body)
        m.pad(body, profile, self.s(10))
        ribSketch = m.sketch(doc, "RibSketch", m.rectangle(*self.s(8, 3, 12, 7)), body)
        rib = m.pad(body, ribSketch, self.s(12), name="Rib")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, self.names(rib, self.front()))
        fillet.Radius = self.s(1)
        doc.recompute()

        def expect():
            if self.stepName is None:
                return self.front()
            if self.stepName == "split":
                return pieces(self.front())
            if self.stepName == "rewrite":
                return self.leftPiece()
            return BROKEN

        self.ref("kept_piece", fillet, "Base", expect)

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(8, -3, 12, 3))

    def rewrite(self, doc):
        doc.Fillet.Base = (doc.Rib, self.names(doc.Rib, self.leftPiece()))

    def back(self, doc):
        m.moveRectangle(doc.RibSketch, *self.s(8, 3, 12, 7))
