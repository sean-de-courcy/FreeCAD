"""Review pr564son-r5 (ops#564 round 5): round 4's widened stop (an object with PendingRecompute
of any document counts as included at a recompute's end) on a holder in document A of a target in
document B's Body (two rims, as held_records_r4's TwinBar). A recompute of A runs B's objects too:
what does the take do with B's objects left touched (a Body behind the roll-back bar, a Pad that
failed) and with a setter on the holder?"""

import os
import shutil
import tempfile

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    BROKEN, Outcome, Scenario, X, edge, expectedNames, _sameEdge, tolerance,
)
from PartDesignTests.Scenarios import models as m


class BoundEdge(Outcome):
    """A SubShapeBinder of an edge: its shape holds the expected edge."""

    def compare(self, scenario, consumer, target, expectation):
        expected = [target.Shape.getElement(n) for n in expectedNames(expectation, target.Shape)]
        got = consumer.Shape.Edges
        if len(got) != len(expected):
            return False, f"{len(got)} edges bound for {len(expected)}"
        tol = tolerance(target.Shape)
        for e in expected:
            if not any(_sameEdge(g, e, tol) for g in got):
                return False, f"no bound edge at {e.CenterOfMass}"
        return True, ""


class XBody(Scenario):
    """Document B: a Body with blocks Pad0 (made to fail by its length 0) and two rims `Rims` (A at
    y = 0, B at y = 2000; 3600 x 45 x 235). Document A: a SubShapeBinder of Rims' top edge at
    y = 0."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564son-r5"
    TIER = "F"
    SIZE = 3600
    REFS = ("binder",)
    length, thickness, height = 3600, 45, 235
    edited = False

    def topEdge(self, y=0):
        return edge("line", direction=X, through=(0, self.s(y), self.s(self.height)))

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def path(self, doc):
        return os.path.join(self.folder, doc.Name + ".FCStd")

    def anchorEdge(self):
        return Part.makeLine(App.Vector(0, -self.s(3000), 0), App.Vector(self.s(100), -self.s(3000), 0))

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def poly(self, y):
        L, T = self.s(self.length, self.thickness)
        y = self.s(y)
        return m.polygon([(L, y + T), (L, y), (0, y), (0, y + T)])

    def block(self, y):
        L, T, B = self.s(self.length, self.thickness, 100)
        y = self.s(y)
        return m.rectangle(L - B, y + T, L, y + T + B)

    def build(self, doc):
        self.folder = os.path.realpath(tempfile.mkdtemp(prefix="NamingScenario"))
        H = self.s(self.height)
        T = self.newDocument("B")
        T.saveAs(self.path(T))
        body = m.body(T)
        blocks = m.sketch(T, "Blocks", self.block(0) + self.block(2000), body)
        m.pad(body, blocks, H / 2, "Pad0")
        profile = m.sketch(T, "Profile", self.rect(0) + self.rect(2000), body)
        rims = m.pad(body, profile, H, "Rims")
        T.recompute()
        T.save()
        doc.saveAs(self.path(doc))
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(rims, tuple(self.names(rims, self.topEdge())))]
        doc.recompute()
        self.target = T
        self.ref("binder", binder, "Support", lambda: self.want(), BoundEdge())

    def slide(self, T):
        L, Th = self.s(self.length, self.thickness)
        m.moveRectangle(T.Profile, 0, 0, L, Th, first=4)
        T.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True

    def redraw(self, T):
        T.Profile.delGeometries([0, 1, 2, 3])
        T.Profile.addGeometry(self.poly(0), False)

    def breakAnchor(self, T):
        T.Pad0.Length = 0

    def fixAnchor(self, T):
        T.Pad0.Length = self.s(self.height) / 2

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class XBodySlideOnlyA(XBody):
    """The slide in B; only A recomputed (it runs B's chain). Break."""

    steps = ("slide",)

    def slide(self, doc):
        super().slide(self.target)


class XBodySlideBThenA(XBody):
    """The slide in B; B recomputed, then A. Break."""

    steps = ("slide",)

    def slide(self, doc):
        super().slide(self.target)
        self.target.recompute()


class XBodyRedrawOnlyA(XBody):
    """A redraw in place in B; only A recomputed. The redrawn edge (quiet) or a break."""

    steps = ("redraw",)

    def want(self):
        return self.topEdge()

    def redraw(self, doc):
        super().redraw(self.target)


class XBodySetterSlide(XBody):
    """The binder's Support set again (a setter, in A), the slide in B, A recomputed. Break."""

    steps = ("setter", "slide")

    def setter(self, doc):
        doc.Binder.Support = doc.Binder.Support

    def slide(self, doc):
        super().slide(self.target)


class XBodySlideSetterSameStep(XBody):
    """The slide in B, then the binder's Support set again, then A recomputed. Break."""

    steps = ("both",)

    def both(self, doc):
        super().slide(self.target)
        doc.Binder.Support = doc.Binder.Support


class XBodyFailSlide(XBody):
    """Rims' sketch made then failed (Anchor's edge gone) with the slide; only A recomputed; then
    Anchor back, A recomputed. Break."""

    steps = ("failSlide", "fix")

    def failSlide(self, doc):
        super().slide(self.target)
        self.breakAnchor(self.target)

    def fix(self, doc):
        self.fixAnchor(self.target)


class XBodyFailSlideSetter(XBody):
    """As XBodyFailSlide with the binder's Support set again before A's recompute."""

    steps = ("failSlide", "fix")

    def failSlide(self, doc):
        super().slide(self.target)
        self.breakAnchor(self.target)
        doc.Binder.Support = doc.Binder.Support

    def fix(self, doc):
        self.fixAnchor(self.target)


class XBodyFailRedrawThenSlide(XBody):
    """Anchor's edge gone and rim A redrawn in place (A recomputed), then A's lines deleted and B
    dragged to y = 0 with Anchor back (A recomputed): B was there: break."""

    steps = ("failRedraw", "slideFix")

    def failRedraw(self, doc):
        super().redraw(self.target)
        self.breakAnchor(self.target)

    def slideFix(self, doc):
        L, Th = self.s(self.length, self.thickness)
        # the redrawn rim 1 is the last four lines; rim 2 is geometry 4-7
        count = len(self.target.Profile.Geometry)
        m.moveRectangle(self.target.Profile, 0, 0, L, Th, first=4)
        self.target.Profile.delGeometries(list(range(count - 4, count)))
        self.fixAnchor(self.target)
        self.edited = True


class XBodyBarSlide(XBody):
    """B's Tip rolled back behind Rims (the Rims and nothing after it...) -- the Tip at Pad0 (Rims
    behind the bar), the slide, A recomputed; then the Tip forward, A recomputed. Break."""

    steps = ("bar", "slide", "forward")

    def bar(self, doc):
        self.target.Body.Tip = self.target.Pad0

    def slide(self, doc):
        super().slide(self.target)
        self.edited = False  # Rims behind the bar is not made again: its edge is still there

    def forward(self, doc):
        self.target.Body.Tip = self.target.Rims
        self.edited = True
