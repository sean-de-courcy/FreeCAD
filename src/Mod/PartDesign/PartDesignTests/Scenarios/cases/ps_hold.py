"""Review pr564son-r5 (ops#564 round 5): the rebase's resolution of fork PR 410's world (rule PS,
the `:s` flag on a record's marks) with the hold. A record whose element is unchanged, taken
while the target is still to be recomputed, is held; the solve's own refresh (a feature given) is
the one that takes the world from now on (`keepWorld` is a setter's), and the end of the recompute's
take is feature-less: a flag-only change of a held record is lost."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached, BROKEN, Chamfered, Scenario, X, edge, vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector


class PsCornerBase(Scenario):
    """A block 20 x 10 x 10 (Block); a Boss (5 high, (5, 3)-(15, 7) on its top) that is suppressed;
    a datum point on the block's far corner (0, 0, 10) as the Boss's shape carries it (the Boss
    doesn't touch that corner: its record's element data is the same with the Boss in or out)."""

    abstract = True
    area = "failure pass-through"
    CLASSES = ("D",)
    AXES = ("M1", "E4")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564son-r5"
    TIER = "F"
    REFS = ("corner",)
    height = 10

    def want(self):
        return vertex((0, 0, self.height))

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), body)
        self.block = m.pad(body, base, 10, "Block")
        bs = m.sketch(doc, "BossSketch", m.rectangle(5, 3, 15, 7), body, z=10)
        self.boss = m.pad(body, bs, 5, "Boss")
        doc.recompute()
        pt = body.newObject("PartDesign::Point", "Datum")
        pt.AttachmentSupport = [(self.boss, self.names(self.boss, self.want()))]
        pt.MapMode = "Vertex"
        self.ref("corner", pt, "AttachmentSupport", lambda: self.want(), Attached())


class PsCornerSuppressTaller(PsCornerBase):
    """Boss suppressed (recomputed); the block made 2 taller while it stays suppressed: the corner
    follows (0, 0, 12), as editing goes on while a feature is suppressed (decision 213)."""

    steps = ("suppress", "taller")

    def suppress(self, doc):
        self.boss.Suppressed = True

    def taller(self, doc):
        doc.Block.Length = 12
        self.height = 12


class PsCornerSuppressTallerBack(PsCornerBase):
    """As PsCornerSuppressTaller, then the Boss unsuppressed: the corner stays at (0, 0, 12)."""

    steps = ("suppress", "taller", "back")

    def suppress(self, doc):
        self.boss.Suppressed = True

    def taller(self, doc):
        doc.Block.Length = 12
        self.height = 12

    def back(self, doc):
        self.boss.Suppressed = False


class PsCornerTallerThenSuppress(PsCornerBase):
    """Control: the block made taller first, then the Boss suppressed (the corner follows each)."""

    steps = ("taller", "suppress")

    def taller(self, doc):
        doc.Block.Length = 12
        self.height = 12

    def suppress(self, doc):
        self.boss.Suppressed = True


class PsCornerSuppressTallerSameStep(PsCornerBase):
    """The Boss suppressed and the block made taller in one edit, one recompute."""

    steps = ("both",)

    def both(self, doc):
        self.boss.Suppressed = True
        doc.Block.Length = 12
        self.height = 12


# ---------------------------------------------------------------------------------------------
# a vacated place under a suppression: rims A (y = 0) and B (y = 2000), a Hole (suppressed) in B,
# a Chamfer on A's top edge
# ---------------------------------------------------------------------------------------------


class PsRims(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564son-r5"
    TIER = "F"
    SIZE = 3600
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235
    edited = False

    def topEdge(self, y=0):
        return edge("line", direction=X, through=(0, self.s(y), self.s(self.height)))

    def want(self):
        return BROKEN if self.edited else self.topEdge()

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
        H = self.s(self.height)
        body = m.body(doc)
        blocks = m.sketch(doc, "Blocks", self.block(0) + self.block(2000), body)
        m.pad(body, blocks, H / 2, "Pad0")
        profile = m.sketch(doc, "Profile", self.rect(0) + self.rect(2000), body)
        m.pad(body, profile, H, "Rims")
        doc.recompute()
        hs = m.sketch(
            doc,
            "HoleSketch",
            [m.circle(self.s(1800), self.s(2000 + 22.5), self.s(10))],
            body,
            z=H,
        )
        self.hole = m.pocket(body, hs, self.s(20), "Hole")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (self.hole, self.names(self.hole, self.topEdge()))
        chamfer.Size = self.s(5)
        doc.recompute()
        self.ref("chamfer", chamfer, "Base", lambda: self.want(), Chamfered(self.s(5)))

    def slide(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True

    def redraw(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.poly(0), False)


class PsRimsSlideControl(PsRims):
    """Control, nothing suppressed: A deleted and B dragged onto A's place. B was there: break."""

    steps = ("slide",)


class PsRimsSuppressThenSlide(PsRims):
    """The Hole suppressed (recomputed); then A deleted and B dragged onto A's place. Break."""

    steps = ("suppress", "slide")

    def suppress(self, doc):
        self.hole.Suppressed = True


class PsRimsSuppressSlideSameStep(PsRims):
    """The Hole suppressed and A deleted and B dragged onto A's place, one recompute. Break."""

    steps = ("both",)

    def both(self, doc):
        self.hole.Suppressed = True
        self.slide(doc)


class PsRimsSuppressUnsuppressSlide(PsRims):
    """The Hole suppressed, then back (each recomputed), then the slide. Break."""

    steps = ("suppress", "back", "slide")

    def suppress(self, doc):
        self.hole.Suppressed = True

    def back(self, doc):
        self.hole.Suppressed = False


class PsRimsSlideSuppressedThenBack(PsRims):
    """The Hole suppressed (recomputed), the slide (recomputed), the Hole back. Break."""

    steps = ("suppress", "slide", "back")

    def suppress(self, doc):
        self.hole.Suppressed = True

    def back(self, doc):
        self.hole.Suppressed = False


class PsRimsSuppressThenRedraw(PsRims):
    """The Hole suppressed; then A redrawn in place. The redrawn edge (quiet) or a break."""

    steps = ("suppress", "redraw")

    def want(self):
        return self.topEdge()

    def suppress(self, doc):
        self.hole.Suppressed = True


class PsRimsSuppressThenSetBaseSlide(PsRims):
    """The Hole suppressed; the Base set again; then the slide. Break."""

    steps = ("suppress", "setBase", "slide")

    def suppress(self, doc):
        self.hole.Suppressed = True

    def setBase(self, doc):
        doc.Chamfer.Base = doc.Chamfer.Base


class PsRimsSuppressSetBaseSlideSameStep(PsRims):
    """The Hole suppressed, the Base set again, and the slide, before the recompute. Break."""

    steps = ("all",)

    def all(self, doc):
        self.hole.Suppressed = True
        doc.Chamfer.Base = doc.Chamfer.Base
        self.slide(doc)
