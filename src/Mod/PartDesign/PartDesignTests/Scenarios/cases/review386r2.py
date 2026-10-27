# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review cases of fork PR 386 round 2 (ops#504 E2, invariant I-S10): composed rewrites, a
rewrite while the target's edit is pending, a missing entry written back as Python reads it, and
rewrites of a split edge's pieces before the merge."""

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Filleted,
    Scenario,
    Warned,
    X,
    Z,
    edge,
    pieces,
)
from PartDesignTests.Scenarios import models as m


def zEdgeAt(x, y):
    return edge("line", direction=Z, through=(x, y, 0))


class Pr386r2(Scenario):
    abstract = True
    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r2"
    TIER = "F"
    PROP = "App::PropertyLinkSubListGlobal"

    def padded(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        return body, pad

    def holder(self, doc, pad, predicate):
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty(self.PROP, "Refs")
        sub = self.names(pad, predicate)[0]
        if self.PROP.startswith("App::PropertyLinkSubList"):
            holder.Refs = [(pad, (sub,))]
        else:
            holder.Refs = (pad, [sub])
        return holder

    def redraw(self, doc):
        """The rectangle drawn again from (20, 10) the other way round: same geometry, new IDs
        (the references become warned same-place guesses)."""
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)


class PendingEditRewrite(Pr386r2):
    """A holder's list holds the pad's vertical edge at (0, 0). Steps: redraw (a warned guess);
    then `notch_ok`: a tab 4 wide and 2 deep is drawn onto the profile's right side at y 3..7
    (the lines keep their IDs; the tab renumbers the pad's edge at (0, 0), whose lines it
    leaves alone) and, before any
    recompute, the property is assigned its own value (a dialog's OK while the edit is pending:
    the subs are index names of the shape before the notch). After the recompute the reference
    must hold its edge at (0, 0), still warned."""

    REFS = ("pending",)
    steps = ("redraw", "notch_ok")

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, zEdgeAt(0, 0))

        def expect():
            return zEdgeAt(0, 0) if self.stepName is None else Warned(zEdgeAt(0, 0))

        self.ref("pending", doc.Holder, "Refs", expect)

    def notch(self, doc):
        # the redrawn lines: 0 right, 1 bottom (20, 0)-(0, 0), 2 left, 3 top
        m.setLines(doc.Profile, {0: ((20, 10), (20, 7))})
        doc.Profile.addGeometry(m.polyline([(20, 7), (22, 7), (22, 3), (20, 3), (20, 0)]), False)

    def notch_ok(self, doc):
        self.notch(doc)
        doc.Holder.Refs = doc.Holder.Refs


class PendingEditRewriteXLinkSub(PendingEditRewrite):
    """PendingEditRewrite with the holder's property an App::PropertyXLinkSub."""

    PROP = "App::PropertyXLinkSub"


class GoneThenIdentityRewrite(Pr386r2):
    """A holder's list holds the pad's vertical edge at (20, 0). Steps: `chamfer`, the profile's
    corner at (20, 0) is cut by a 5 x 5 line (the corner and its edge are gone: break, or a warned
    guess among the edges at (15, 0) and (20, 5)); `ok`, the property is assigned its own value
    as Python reads it. A rewrite never turns the break into a silent pick."""

    REFS = ("gone",)
    steps = ("chamfer", "ok")

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, zEdgeAt(20, 0))

        def expect():
            if self.stepName is None:
                return zEdgeAt(20, 0)
            return BROKEN

        self.ref("gone", doc.Holder, "Refs", expect)

    def chamfer(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(0, 0), (15, 0), (20, 5), (20, 10), (0, 10)]), False)

    def ok(self, doc):
        doc.Holder.Refs = doc.Holder.Refs


class UndoAddedEntry(Pr386r2):
    """The guessed edge at (20, 0); `add`: the edge at (0, 0) is added before it in one
    transaction; `undo`: the transaction is undone. The list holds the guessed edge alone again,
    warned."""

    REFS = ("undone",)
    steps = ("redraw", "add", "undo")

    def build(self, doc):
        doc.UndoMode = 1
        _, pad = self.padded(doc)
        self.holder(doc, pad, zEdgeAt(20, 0))

        def expect():
            if self.stepName is None:
                return zEdgeAt(20, 0)
            if self.stepName == "add":
                return Warned(pieces(edge("line", direction=Z, where=lambda e: abs(e.Vertexes[0].Point.y) < 1e-6 and min(abs(e.Vertexes[0].Point.x), abs(e.Vertexes[0].Point.x - 20)) < 1e-6)))
            return Warned(zEdgeAt(20, 0))

        self.ref("undone", doc.Holder, "Refs", expect)

    def add(self, doc):
        doc.recompute()
        [held] = doc.Holder.Refs[0][1]
        other = self.names(doc.Pad, zEdgeAt(0, 0))[0]
        doc.openTransaction("add")
        doc.Holder.Refs = [(doc.Pad, (other, held))]
        doc.commitTransaction()

    def undo(self, doc):
        doc.undo()


class RibPieces(Scenario):
    """A block 0..20 x 0..10 x 10 with a rib (x 8..12, y 3..7, 12 high) and a fillet (radius 1)
    on the block's front top edge. `split`: the rib moves to y -3..3, so the edge splits into
    x 0..8 and x 12..20 (the fillet takes both pieces, each with `from`); `rewrite`, the case's
    own rewrite that keeps both pieces; `merge`: the rib moves back, the pieces join."""

    abstract = True
    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "review pr386-r2"
    TIER = "F"
    steps = ("split", "rewrite", "merge")

    @staticmethod
    def whole():
        return edge("line", direction=X, through=(0, 0, 10))

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

    def expect(self):
        if self.stepName in ("split", "rewrite"):
            return pieces(self.whole())
        return self.whole()

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, 8, -3, 12, 3)

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch, 8, 3, 12, 7)


class PiecesIdentityThenMerge(RibPieces):
    """RibPieces; the rewrite assigns Base its own value (both pieces kept): after the merge the
    fillet is on the whole edge again."""

    REFS = ("fillet_edge",)

    def rewrite(self, doc):
        doc.Fillet.Base = doc.Fillet.Base


class PiecesReversedThenMerge(RibPieces):
    """RibPieces; the rewrite writes the two pieces back in the other order."""

    REFS = ("fillet_edge",)

    def rewrite(self, doc):
        rib, subs = doc.Fillet.Base
        doc.Fillet.Base = (rib, list(reversed(subs)))


class PiecesPlusBackThenMerge(RibPieces):
    """RibPieces; the rewrite keeps both pieces and adds the block's back top edge (y 10, z 10):
    after the merge the fillet is on the whole front edge and the back edge."""

    REFS = ("fillet_edge",)

    @staticmethod
    def back():
        return edge("line", direction=X, through=(0, 10, 10))

    def expect(self):
        front = lambda e: abs(e.CenterOfMass.z - 10) < 1e-6 and abs(e.CenterOfMass.y) < 1e-6
        back = lambda e: abs(e.CenterOfMass.z - 10) < 1e-6 and abs(e.CenterOfMass.y - 10) < 1e-6
        if self.stepName is None:
            return self.whole()
        if self.stepName == "split":
            return pieces(self.whole())
        if self.stepName == "rewrite":
            return pieces(edge("line", direction=X, where=lambda e: front(e) or back(e)))
        return pieces(edge("line", direction=X, where=lambda e: front(e) or back(e)))

    def rewrite(self, doc):
        rib, subs = doc.Fillet.Base
        [back] = self.names(rib, self.back())
        doc.Fillet.Base = (rib, list(subs) + [back])


class PendingWidenRewrite(Pr386r2):
    """The guessed edge at (20, 0); `widen_ok`: the redrawn right line moves to x 25 (its ID
    kept) and, before the recompute, the property is assigned its own value. The reference
    follows its edge to (25, 0), still warned."""

    REFS = ("pending",)
    steps = ("redraw", "widen_ok")

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, zEdgeAt(20, 0))

        def expect():
            if self.stepName is None:
                return zEdgeAt(20, 0)
            if self.stepName == "widen_ok":
                return Warned(zEdgeAt(25, 0))
            return Warned(zEdgeAt(20, 0))

        self.ref("pending", doc.Holder, "Refs", expect)

    def widen_ok(self, doc):
        m.setLines(doc.Profile, {0: ((25, 10), (25, 0)), 1: ((25, 0), (0, 0)), 3: ((0, 10), (25, 10))})
        doc.Holder.Refs = doc.Holder.Refs


class PendingWidenRewriteLinkSub(PendingWidenRewrite):
    """PendingWidenRewrite with the holder's property an App::PropertyLinkSub."""

    PROP = "App::PropertyLinkSub"


class PendingEditAddEntry(PendingEditRewrite):
    """PendingEditRewrite, but the pending rewrite adds the edge at (20, 10) after the guessed
    entry (by its index on the shape before the notch: a count change)."""

    REFS = ("pending",)

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, zEdgeAt(0, 0))

        def expect():
            if self.stepName is None:
                return zEdgeAt(0, 0)
            if self.stepName == "notch_ok":
                return Warned(
                    pieces(
                        edge(
                            "line",
                            direction=Z,
                            where=lambda e: (e.Vertexes[0].Point.x, e.Vertexes[0].Point.y)
                            in ((0.0, 0.0), (20.0, 10.0)),
                        )
                    )
                )
            return Warned(zEdgeAt(0, 0))

        self.ref("pending", doc.Holder, "Refs", expect)

    def notch_ok(self, doc):
        other = self.names(doc.Pad, zEdgeAt(20, 10))[0]
        [held] = doc.Holder.Refs[0][1]
        self.notch(doc)
        doc.Holder.Refs = [(doc.Pad, (held, other))]


class MissingRewriteThenRestore(Pr386r2):
    """A holder's list holds the pad's vertical edge at (20, 0) (the profile's lines keep their
    IDs throughout). `cut`: the corner is cut, lines 0 and 1 shortened to (20, 5) and (15, 0)
    and a diagonal added between them: the corner's edge is gone (break, or a warned guess among
    the edges at (15, 0) and (20, 5)). `ok`: the property is assigned its own value as Python
    reads it (the missing entry written back). `restore`: the diagonal is deleted and the lines
    meet at (20, 0) again: the corner's edge is back, and the reference holds it."""

    REFS = ("missing",)
    steps = ("cut", "ok", "restore")

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, zEdgeAt(20, 0))

        def expect():
            if self.stepName in ("cut", "ok"):
                return BROKEN
            return zEdgeAt(20, 0)

        self.ref("missing", doc.Holder, "Refs", expect)

    def cut(self, doc):
        # m.rectangle(0, 0, 20, 10): 0 bottom (0,0)-(20,0), 1 right (20,0)-(20,10), 2 top, 3 left
        m.setLines(doc.Profile, {0: ((0, 0), (15, 0)), 1: ((20, 5), (20, 10))})
        doc.Profile.addGeometry(m.polyline([(15, 0), (20, 5)]), False)

    def ok(self, doc):
        doc.Holder.Refs = doc.Holder.Refs

    def restore(self, doc):
        doc.Profile.delGeometry(4)
        m.setLines(doc.Profile, {0: ((0, 0), (20, 0)), 1: ((20, 0), (20, 10))})


class TargetAheadIdentityRewrite(Pr386r2):
    """A holder's list holds the pad's vertical edge at (20, 10) (a plain pick). `tab_ok`: a tab
    is drawn onto the profile's right side (renumbering the edge at (20, 10): Edge5 to Edge17); the profile and the
    pad are recomputed alone, the holder not; then the holder's property is assigned its own
    value as Python reads it. The tab's last line makes the corner at (20, 10), so the pad's
    recompute already re-binds the reference as a same-place guess (and rewrites the holder's
    sub to the new index). The rewrite keeps that: the reference holds its edge, warned.""" 

    REFS = ("ahead",)
    steps = ("tab_ok",)

    def build(self, doc):
        _, pad = self.padded(doc)
        self.holder(doc, pad, zEdgeAt(20, 10))
        self.ref(
            "ahead",
            doc.Holder,
            "Refs",
            lambda: zEdgeAt(20, 10) if self.stepName is None else Warned(zEdgeAt(20, 10)),
        )

    def tab_ok(self, doc):
        m.setLines(doc.Profile, {1: ((20, 0), (20, 3))})
        doc.Profile.addGeometry(m.polyline([(20, 3), (22, 3), (22, 7), (20, 7), (20, 10)]), False)
        doc.Profile.recompute()
        doc.Pad.recompute()
        doc.Holder.Refs = doc.Holder.Refs


class SketchDelExternalKeepsGuess(Pr386r2):
    """A sketch 20 above the pad projects its top front edge and then its top back edge; after
    the redraw both are warned guesses; the rewrite deletes the first external (Sketcher
    delExternal: the kept link passed on with its shadow, a count change). The second keeps its
    edge, warned."""

    REFS = ("kept_external",)
    steps = ("redraw", "rewrite")

    @staticmethod
    def back():
        return edge("line", direction=X, through=(0, 10, 10))

    @staticmethod
    def both():
        return pieces(edge("line", direction=X, where=lambda e: abs(e.CenterOfMass.z - 10) < 1e-6))

    def build(self, doc):
        body, pad = self.padded(doc)
        sketch = m.sketch(doc, "Projection", [], body, z=20)
        sketch.addExternal(pad.Name, self.names(pad, edge("line", direction=X, through=(0, 0, 10)))[0])
        sketch.addExternal(pad.Name, self.names(pad, self.back())[0])

        def expect():
            if self.stepName is None:
                return self.both()
            if self.stepName == "redraw":
                return Warned(self.both())
            return Warned(self.back())

        self.ref("kept_external", sketch, "ExternalGeometry", expect)

    def rewrite(self, doc):
        doc.Projection.delExternal(0)
