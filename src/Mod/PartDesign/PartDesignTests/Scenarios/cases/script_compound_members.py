# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************


"""Corpus cases (ops#502, class C): a script compound whose members change shape while they move
(P1b, decision 260; the class C ruling `work/s3339/c2-platebthin-ruling.md`, from review
pr399-r3g's `PlateBThinToCPlace`).

The model: `Plate`, a script's compound of three 40 x 30 x 5 slabs A, B and C at x = 0, 60 and
120, as a fresh shape (no element map, so this build names it by match); `Cut`, the plate less a
box notching A's corner; a sketch on each slab's top in the plate (`pA`, `pB`, `pC`) and in the cut
(`cA`, `cB`, `cC`). The script sets the plate again with the slabs listed in `slabs` (x, height).

"B thinned and moved onto C's place, C moved on" and "C thinned in place, B deleted, a slab
appended" make the same compound in the same order, so no rule over the shapes can be right for
both: P1b retires the changed slab matched at another member's order position, and the
references to both slabs break (loud). Round 4's P1b asked a whole twin of the old member standing
free; review pr399-r4 found the ambiguity silent without it, so P1b takes the ruling's widest stop
(its 3.3, decision 260 (1)): no corroboration is asked, and the uncorroborated variants the ruling
listed in its 5 break too. A trade of places with a changed member breaks as a whole (decision 269).
A piece changed at its own order position keeps the place reading. Since decision 274 (the path's
widest stop, after review pr399-r4c) a member changed where the pieces' face correspondence is out
of order (an inverted pair: a trade, a cycle, a reorder; or a span over an old piece at another
position) gives every piece of the compound fresh ids, the whole ones too: every reference into it
breaks, and the whole members' right -> loud is the stop's accepted cost (`ACCEPTED`)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, X, Y, Z, edge, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector


class _Plate(Scenario):
    abstract = True
    area = "history-less results"
    CLASSES = ("C",)
    ISSUE = "ops#502"
    FOUND_BY = "review pr399-r3g"
    TIER = "F"
    AXES = ("M2", "X4")
    REFS = ("pA", "pB", "pC", "cA", "cB", "cC")
    slabs = ((0, 5), (60, 5), (120, 5))  # the edit's compound: (x, height) per slab, in order
    where = {"A": (0, 5), "B": (60, 5), "C": (120, 5)}  # after the edit: the slab's (x, height); None: broken

    def plate(self, slabs):
        shape = Part.Shape()
        compound = Part.makeCompound([Part.makeBox(40, 30, h, V(x, 0, 0)) for x, h in slabs])
        shape.importBrepFromString(compound.exportBrepToString())
        return shape

    def top(self, tag):
        if self.stepName is None:
            x, h = {"A": (0, 5), "B": (60, 5), "C": (120, 5)}[tag]
        elif self.where[tag] is None:
            return BROKEN
        else:
            x, h = self.where[tag]
        return face("plane", normal=Z, contains=V(x + 20, 15, h))

    def build(self, doc):
        self.target = m.feature(doc, "Plate", self.plate(((0, 5), (60, 5), (120, 5))))
        notch = m.box(doc, "Notch", (6, 6, 10), at=(-1, -1, -2))
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = self.target, notch
        doc.recompute()
        for tag in "ABC":
            for prefix, owner in (("p", self.target), ("c", cut)):
                expect = lambda tag=tag: self.top(tag)
                sketch = doc.addObject("Sketcher::SketchObject", "On_" + prefix + tag)
                sketch.AttachmentSupport = [(owner, self.names(owner, expect())[0])]
                sketch.MapMode = "FlatFace"
                self.ref(prefix + tag, sketch, "AttachmentSupport", expect, Attached())

    def edit(self, doc):
        self.target.Shape = self.plate(self.slabs)


class PlateBThinToCPlace(_Plate):
    """The find (review pr399-r3g): B 3 high moves onto C's place (120), C moves to 300. The thin
    slab is matched to C by place, while C's whole twin stands free at 300 and B is unmatched: P1b
    retires it. Right by the order: B's top on the thin slab, C's at 300; a break offering them
    is loud+. A keeps its top."""

    FOUND_BY = "review pr399-r3g"
    slabs = ((0, 5), (120, 3), (300, 5))
    where = {"A": (0, 5), "B": (120, 3), "C": (300, 5)}


class PlateInsertFrontBThickerDropC(_Plate):
    """A slab inserted in front (x = -100), B 8 high in place, C dropped. B+ is matched to B at its
    own place but at another order position, A's whole twin (the new slab in front) stands free
    and C is unmatched: P1b retires B+, and B's references break (right -> loud: the class's
    price, decision 260)."""

    FOUND_BY = "design s3339"
    ACCEPTED = {f"{r}|{c}": "decision 260" for r in ("pB", "cB") for c in ("V2", "V2s")}
    slabs = ((-100, 5), (0, 5), (60, 8))
    where = {"A": (0, 5), "B": (60, 8), "C": None}


class PlateBThinToCPlaceCDropped(_Plate):
    """B 3 high onto C's place, C deleted. No whole twin of C stands free, but "C thinned in place,
    B deleted" makes the same compound (the uncorroborated order/place ambiguity, the ruling's 5):
    the widest stop retires the thin slab, and C's references break (right -> loud, decision 260
    (1)). Under the place reading they would follow it, under the order reading B's would;
    integration answers by index."""

    FOUND_BY = "design s3339"
    ACCEPTED = {f"{r}|{c}": "decision 260 (1)" for r in ("pC", "cC") for c in ("V2", "V2s")}
    slabs = ((0, 5), (120, 3))
    where = {"A": (0, 5), "B": None, "C": (120, 3)}


class PlateBThinCThickTraded(_Plate):
    """B 3 high moves to C's place (120) and C 8 high to B's (60): under the place reading the slab
    at 60 keeps B's ids and the one at 120 C's, under the order reading they trade (the
    uncorroborated order/place ambiguity, the ruling's 5). Both are changed at another order
    position: the widest stop retires both, and the references to B and C break (right -> loud,
    decision 260 (1)); integration answers by index. A trade with a change gives every piece fresh
    ids since decision 274, so A's references break too (its accepted cost)."""

    FOUND_BY = "design s3339"
    ACCEPTED = {
        **{f"{r}|{c}": "decision 260 (1)" for r in ("pB", "cB", "pC", "cC") for c in ("V2", "V2s")},
        **{f"{r}|{c}": "decision 274" for r in ("pA", "cA") for c in ("V2", "V2s")},
    }
    slabs = ((0, 5), (120, 3), (60, 8))
    where = {"A": (0, 5), "B": (60, 8), "C": (120, 3)}


class PlateCThinInPlaceBAway(_Plate):
    """B moves to 300 and C is 3 high in place. The thin slab is C's at C's own position: the order
    agrees, P1b doesn't fire, and C's references stay on it. B moved whole: R2' retires it, and a
    break offering the slab at 300 is loud+."""

    FOUND_BY = "design s3339"
    slabs = ((0, 5), (300, 5), (120, 3))
    where = {"A": (0, 5), "B": (300, 5), "C": (120, 3)}


class PlateBThicker(_Plate):
    """The control: B 8 high in place. Every reference stays on its slab."""

    FOUND_BY = "design s3339"
    slabs = ((0, 5), (60, 8), (120, 5))
    where = {"A": (0, 5), "B": (60, 8), "C": (120, 5)}


class HiddenTradeInsertFront(_Plate):
    """A trade hidden by a non-twin inserted in front (the class C ruling of 2026-11-04, decision
    272, its F8): [X 8 high at -100, A, B 3 high at C's place, C whole at B's place]. The thin slab
    stands at C's own position, so no position test sees the trade, but its pair with C and the
    whole slab's with B are inverted: both break (the order and the place readings differ). A,
    shifted, breaks with them: a member changed out of order gives every piece fresh ids (decision
    274, its accepted cost)."""

    FOUND_BY = "design sf785"
    ACCEPTED = {f"{r}|{c}": "decision 274" for r in ("pA", "cA") for c in ("V2", "V2s")}
    slabs = ((-100, 8), (0, 5), (120, 3), (60, 5))
    where = {"A": (0, 5), "B": None, "C": None}


class HiddenTradeDeleteFront(_Plate):
    """The same hidden by a deletion in front: A deleted, [B 3 high at C's place, C whole at B's
    place]. The whole slab stands at B's own position; the pairs are inverted: both break."""

    FOUND_BY = "design sf785"
    slabs = ((120, 3), (60, 5))
    where = {"A": None, "B": None, "C": None}


class HiddenTradeInsertFrontTwin(_Plate):
    """The trade behind a whole twin inserted in front: P1 retires the whole slabs (equal class
    counts), and the thin slab, left alone at C's position, breaks by its inverted pair, read
    before P1 withdraws anything."""

    FOUND_BY = "design sf785"
    slabs = ((-100, 5), (0, 5), (120, 3), (60, 5))
    where = {"A": None, "B": None, "C": None}


class ListSwapTwinsDropA(_Plate):
    """Whole twins B and C listed swapped with A deleted: P1's class counts are unequal (3 old, 2
    new), so P1 doesn't see the swap, but the pairs are inverted and each one's old piece has a
    displaced twin: both break."""

    FOUND_BY = "design sf785"
    slabs = ((120, 5), (60, 5))
    where = {"A": None, "B": None, "C": None}


class ListSwapTwinsThickenA(_Plate):
    """Whole twins B and C listed swapped with A thickened in place (A leaves P1's class: 3 old, 2
    new): B and C break; A, changed at its own position and in no inversion, breaks with them since
    decision 274 (a member changed where the pairs are inverted: every piece takes fresh ids)."""

    FOUND_BY = "design sf785"
    ACCEPTED = {f"{r}|{c}": "decision 274" for r in ("pA", "cA") for c in ("V2", "V2s")}
    slabs = ((0, 8), (120, 5), (60, 5))
    where = {"A": (0, 8), "B": None, "C": None}


# Review pr399-r4b's finds and controls (the class C ruling of 2026-11-04, decision 272, section 7):
# slabs with a length, refs named prefix + slab tag + face (t top, b bottom, l the -X wall, r the
# +X wall). Unless a docstring says otherwise the expectation is the order reading (the member
# listed at a position is the member listed there before); a break offering it is loud+.


class _R4bPlate(Scenario):
    abstract = True
    area = "history-less results"
    CLASSES = ("C",)
    ISSUE = "ops#502"
    FOUND_BY = "review pr399-r4b"
    TIER = "F"
    AXES = ("M2", "X4")
    start = (("A", 0, 5, 40), ("B", 60, 5, 40), ("C", 120, 5, 40))  # (tag, x, height, length)
    slabs = ()  # the edit's compound: (x, height, length) per slab, in order
    extras = ()  # (before index, ((a), (b))): face-less members (lines) of the start compound
    newExtras = ()  # the same, of the edited compound
    where = {}  # tag -> (x, height, length) after the edit; None: broken
    k = 1  # the scale: every length times k
    notchAt = (-1, -1, -2)

    def plate(self, slabs, extras):
        k = self.k
        members = [Part.makeBox(L * k, 30 * k, h * k, V(x * k, 0, 0)) for x, h, L in slabs]
        for at, (a, b) in sorted(extras, reverse=True):
            members.insert(at, Part.makeLine(V(*a) * k, V(*b) * k))
        compound = Part.makeCompound(members)
        shape = Part.Shape()
        shape.importBrepFromString(compound.exportBrepToString())
        return shape

    def place(self, tag):
        if self.stepName is None:
            return {t: (x, h, L) for t, x, h, L in self.start}[tag]
        return self.where[tag]

    def predicate(self, tag, which):
        placed = self.place(tag)
        if placed is None:
            return BROKEN
        q = self.k
        x, h, L = placed[0] * q, placed[1] * q, placed[2] * q
        if which == "t":
            return face("plane", normal=Z, contains=V(x + L / 2, 15 * q, h))
        if which == "b":
            return face("plane", normal=-Z, contains=V(x + L / 2, 15 * q, 0))
        if which == "l":
            return face("plane", normal=-X, contains=V(x, 15 * q, h / 2))
        return face("plane", normal=X, contains=V(x + L, 15 * q, h / 2))

    def build(self, doc):
        start = [(x, h, L) for _, x, h, L in self.start]
        self.target = doc.addObject("Part::Feature", "Plate")
        self.target.Shape = self.plate(start, self.extras)
        notch = doc.addObject("Part::Box", "Notch")
        notch.Length, notch.Width, notch.Height = 6 * self.k, 6 * self.k, 10 * self.k
        notch.Placement.Base = V(*self.notchAt) * self.k
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = self.target, notch
        doc.recompute()
        for ref in self.REFS:
            prefix, tag, which = ref[0], ref[1], ref[2]
            owner = self.target if prefix == "p" else cut
            expect = lambda tag=tag, which=which: self.predicate(tag, which)
            sketch = doc.addObject("Sketcher::SketchObject", "On_" + ref)
            sketch.AttachmentSupport = [(owner, self.names(owner, expect())[0])]
            sketch.MapMode = "FlatFace"
            self.ref(ref, sketch, "AttachmentSupport", expect, Attached())

    def edit(self, doc):
        self.doc.getObject("Plate").Shape = self.plate(self.slabs, self.newExtras)


_FOUR = (("A", 0, 5, 40), ("B", 60, 5, 40), ("C", 120, 5, 40), ("D", 180, 5, 40))


class R4bBLongOverCDTrade(_R4bPlate):
    """A trade with the changed member reaching two old places: slabs A B C D at 0/60/120/180.
    B is lengthened to 100 and moved onto C's and D's places (120..220), C moves whole onto B's
    place (60), D moves to 300; listed [A, B, C, D] as before. The long slab's -X wall is C's
    old wall, its +X wall D's, so it reaches two old pieces and P1b's first loop passes it by;
    C at B's place then keeps B's ids by place. Order reading: B's on the long slab, C's at 60,
    D's at 300. Since decision 274 every piece takes fresh ids, A's too (its accepted cost)."""

    start = _FOUR
    ACCEPTED = {f"{r}|{c}": "decision 274" for r in ("pAt",) for c in ("V2", "V2s")}
    REFS = ("pAt", "pBt", "pCt", "pDt", "cBt", "cCt", "pBl", "pCl", "pDr")
    slabs = ((0, 5, 40), (120, 5, 100), (60, 5, 40), (300, 5, 40))
    where = {"A": (0, 5, 40), "B": (120, 5, 100), "C": (60, 5, 40), "D": (300, 5, 40)}


class R4bSplitB(_R4bPlate):
    """B split in two halves at its own place (60..80, 80..100), A and C kept: [A, B1, B2, C].
    B's -X wall lies wholly on B1 (the near half), at its own order position; the far half, changed
    at another position, is the widest stop's named cost. Expected: B's -X wall on B1, its +X wall
    on B2, C's top on C."""

    REFS = ("pBl", "cBl", "pBr", "pCt", "pAt")
    slabs = ((0, 5, 40), (60, 5, 20), (80, 5, 20), (120, 5, 40))
    where = {"A": (0, 5, 40), "B": (60, 5, 40), "C": (120, 5, 40)}

    def predicate(self, tag, which):
        if self.stepName is not None and tag == "B":
            return {
                "l": face("plane", normal=-X, contains=V(60, 15, 2.5)),
                "r": face("plane", normal=X, contains=V(100, 15, 2.5)),
            }[which]
        return super().predicate(tag, which)


class R4bTradeCLongTouching(_R4bPlate):
    """T1's trade with both members changed, the sweep's Sw33 made minimal: B 3 high onto C's place
    (120..160), C lengthened to 60 onto B's place (60..120), listed [A, B, C]. The long slab's +X
    end stands on C's old -X wall's corners, so its matches reach C as well as B: P1b's first loop
    passes it by, and the cycle from the thin slab breaks there. Order reading: B's on the thin
    slab, C's on the long one (the widest stop retires both readings' pieces when it sees them).
    Since decision 274 every piece takes fresh ids, A's too (its accepted cost)."""

    ACCEPTED = {f"{r}|{c}": "decision 274" for r in ("pAt",) for c in ("V2", "V2s")}
    REFS = ("pAt", "pBt", "pCt", "cBt", "cCt", "pBl", "pCr", "pBb")
    slabs = ((0, 5, 40), (120, 3, 40), (60, 5, 60))
    where = {"A": (0, 5, 40), "B": (120, 3, 40), "C": (60, 5, 60)}


class R4bDistinctSwapPlace(_R4bPlate):
    """Review pr399-r4b's F-L2 (Sonnet's `R4b_DistinctSwapPlace`): distinct members A 5, B 8 and C
    3 high, re-listed [B, A thickened to 6, C]. B's exact shape stands at B's own place: no displaced
    old piece is its twin, so the place reading keeps it (the ruling's rule 2); A, changed in a
    reorder, breaks. Expected by place: B on the 8 high slab at 60. Since decision 274 a member
    changed in a reorder gives every piece fresh ids: B's and C's references break too (its
    accepted cost)."""

    ACCEPTED = {f"{r}|{c}": "decision 274" for r in ("pBt", "cBt", "pCt") for c in ("V2", "V2s")}
    REFS = ("pAt", "pBt", "pCt", "cBt")
    start = (("A", 0, 5, 40), ("B", 60, 8, 40), ("C", 120, 3, 40))
    slabs = ((60, 8, 40), (0, 6, 40), (120, 3, 40))
    where = {"A": (0, 6, 40), "B": (60, 8, 40), "C": (120, 3, 40)}


# Review pr399-r4c's finds and controls (Opus; decision 274, the widest stop): slabs with a length,
# refs named prefix + slab tag + kind (t top, l the -X wall, r the +X wall, by sketches; e the +X top
# edge, a datum point at its centre of mass; v the +X top front corner, a datum point on the
# vertex). Unless a docstring says otherwise the expectation is the order reading (the member
# listed at a position is the member listed there before); a break offering it is loud+.


class _R4cPlate(Scenario):
    abstract = True
    area = "history-less results"
    CLASSES = ("C",)
    ISSUE = "ops#502"
    FOUND_BY = "review pr399-r4c"
    TIER = "F"
    AXES = ("M2", "X4")
    SIZE = 400.0
    start = _FOUR  # (tag, x, height, length)
    slabs = ()  # the edit's compound: (x, height, length) per slab, in order
    where = {}  # tag -> (x, height, length) after the edit; None: broken
    special = {}  # (tag, kind) -> (x, height, length) after the edit, where a kind differs

    def plate(self, slabs):
        s = self.s
        members = [Part.makeBox(s(L), s(30), s(h), V(s(x), 0, 0)) for x, h, L in slabs]
        compound = Part.makeCompound(members)
        shape = Part.Shape()
        shape.importBrepFromString(compound.exportBrepToString())
        return shape

    def place(self, tag, which):
        if self.stepName is None:
            return {t: (x, h, L) for t, x, h, L in self.start}[tag]
        if (tag, which) in self.special:
            return self.special[(tag, which)]
        return self.where[tag]

    def predicate(self, tag, which):
        placed = self.place(tag, which)
        if placed is None:
            return BROKEN
        x, h, L = (self.s(v) for v in placed)
        y = self.s(15)
        if which == "t":
            return face("plane", normal=Z, contains=V(x + L / 2, y, h))
        if which == "l":
            return face("plane", normal=-X, contains=V(x, y, h / 2))
        if which == "r":
            return face("plane", normal=X, contains=V(x + L, y, h / 2))
        if which == "e":
            return edge(direction=Y, contains=V(x + L, y, h))
        if which == "v":
            return vertex(V(x + L, 0, h))
        raise ValueError(which)

    def build(self, doc):
        s = self.s
        self.target = doc.addObject("Part::Feature", "Plate")
        self.target.Shape = self.plate([(x, h, L) for _, x, h, L in self.start])
        notch = doc.addObject("Part::Box", "Notch")
        notch.Length, notch.Width, notch.Height = s(6), s(6), s(10)
        notch.Placement.Base = V(s(-1), s(-1), s(-2))
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = self.target, notch
        doc.recompute()
        for ref in self.REFS:
            prefix, tag, which = ref[0], ref[1], ref[2]
            owner = self.target if prefix == "p" else cut
            expect = lambda tag=tag, which=which: self.predicate(tag, which)
            if which in "tlr":
                consumer = doc.addObject("Sketcher::SketchObject", "On_" + ref)
                consumer.AttachmentSupport = [(owner, self.names(owner, expect())[0])]
                consumer.MapMode = "FlatFace"
            else:
                consumer = doc.addObject("PartDesign::Point", "On_" + ref)
                consumer.AttachmentSupport = [(owner, self.names(owner, expect())[0])]
                consumer.MapMode = "Vertex" if which == "v" else "CenterOfMass"
            self.ref(ref, consumer, "AttachmentSupport", expect, Attached())

    def edit(self, doc):
        self.target.Shape = self.plate(self.slabs)


class R4cTradeNeighbourOnCorner(_R4cPlate):
    """Review pr399-r4c's T1: B 3 high onto C's place, C whole onto B's place (a trade), and D
    lengthened back to 160, its -X end now on C's old +X top corners. Round 4c withdrew C's ids from
    the reorder's pieces only, so D', changed at its own position and in no inversion, kept C's +X
    top edge and corner by place, silently. A member changed out of order gives every piece fresh
    ids (decision 274): every reference breaks. Order reading: C's edge and corner at 100 (C moved
    whole onto B's place); B's on the thin slab; D's top on D'."""

    ACCEPTED = {f"{r}|{c}": "decision 274" for r in ("pAt",) for c in ("V2", "V2s")}
    REFS = ("pCe", "pCv", "cCe", "cCv", "pCt", "pBt", "pDt", "pAt")
    slabs = ((0, 5, 40), (120, 3, 40), (60, 5, 40), (160, 5, 60))
    where = {"A": (0, 5, 40), "B": (120, 3, 40), "C": (60, 5, 40), "D": (160, 5, 60)}


class R4cTradeNeighbourApart(R4cTradeNeighbourOnCorner):
    """Control: the same with D lengthened back only to 165 (no corner on C's old place)."""

    slabs = ((0, 5, 40), (120, 3, 40), (60, 5, 40), (165, 5, 55))
    where = {"A": (0, 5, 40), "B": (120, 3, 40), "C": (60, 5, 40), "D": (165, 5, 55)}


class R4cTradeWholeNeighbourOnCorner(R4cTradeNeighbourOnCorner):
    """The trade of twins B and C, both whole (P1's class: A B C D old, A B C new + D' changed),
    with D lengthened back onto C's old +X corners as above."""

    slabs = ((0, 5, 40), (120, 5, 40), (60, 5, 40), (160, 5, 60))
    where = {"A": (0, 5, 40), "B": (120, 5, 40), "C": (60, 5, 40), "D": (160, 5, 60)}


class R4cCycleNeighbourOnCorner(_R4cPlate):
    """T1 through a three-cycle: B 3 high onto D's place, C whole onto B's place, D whole onto C's
    place, listed [A, B, C, D, E], and a fifth slab E (240) lengthened back to 220, onto D's old +X
    top corners (vacated: the thin slab is 3 high). Every reference breaks (decision 274). Order
    reading: D's +X top edge and corner at 160 (D whole at C's place); E's top on E'."""

    ACCEPTED = {f"{r}|{c}": "decision 274" for r in ("pAt",) for c in ("V2", "V2s")}
    start = _FOUR + (("E", 240, 5, 40),)
    REFS = ("pDe", "pDv", "cDe", "pEt", "pAt", "pBt")
    slabs = ((0, 5, 40), (180, 3, 40), (60, 5, 40), (120, 5, 40), (220, 5, 60))
    where = {"A": (0, 5, 40), "B": (180, 3, 40), "C": (60, 5, 40), "D": (120, 5, 40), "E": (220, 5, 60)}


class R4cSpanOverMovedC(_R4cPlate):
    """Review pr399-r4c's T2: C moved whole to a free place (300), D lengthened back over C's old
    place (120..220), listed [A, B, C, D]. D' pairs with C (its -X wall is C's old one) and with D
    (its +X wall), with D at its own position and no pair inverted: round 4c's span keep left it C's
    -X wall, silently. A span over an old piece at another position is out of order: every reference
    breaks (decision 274). Order reading: C's walls on the slab at 300, D's +X wall and top on D'."""

    ACCEPTED = {f"{r}|{c}": "decision 274" for r in ("pBt",) for c in ("V2", "V2s")}
    REFS = ("pCl", "cCl", "pCt", "pDr", "pDt", "pBt")
    slabs = ((0, 5, 40), (60, 5, 40), (300, 5, 40), (120, 5, 100))
    where = {"A": (0, 5, 40), "B": (60, 5, 40), "C": (300, 5, 40), "D": (120, 5, 100)}


class R4cSplitFarHalfListedLast(_R4cPlate):
    """C split in place into two halves, the far half listed after D: [A, B, C1 120..140, D,
    C2 140..160]. The far half's pair with C is inverted with D's: a member changed out of order,
    so every reference breaks (decision 274), D's too, whole at its own place and position. Both
    readings put D on D; C's -X wall on the near half; C's +X wall on the far half."""

    ACCEPTED = {f"{r}|{c}": "decision 274" for r in ("pDt", "pDr", "cDt", "pBt", "pCl") for c in ("V2", "V2s")}
    REFS = ("pDt", "pDr", "cDt", "pCl", "pBt", "pCr")
    slabs = ((0, 5, 40), (60, 5, 40), (120, 5, 20), (180, 5, 40), (140, 5, 20))
    where = {"A": (0, 5, 40), "B": (60, 5, 40), "C": (120, 5, 20), "D": (180, 5, 40)}
    special = {("C", "r"): (140, 5, 20)}


class R4cSplitFarHalfInOrder(R4cSplitFarHalfListedLast):
    """Control: the halves listed in order, [A, B, C1, C2, D]: no inversion, the far half (changed
    at another position) is the widest stop's named cost, the rest keep their ids."""

    ACCEPTED = {}
    slabs = ((0, 5, 40), (60, 5, 40), (120, 5, 20), (140, 5, 20), (180, 5, 40))
