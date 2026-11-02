"""Review pr564son-r3 (ops#564 round 3): probes aimed at round 2's fixes: the closure test of a
feature recomputed alone (R2-1) and the objects 0 and 1 of the closure left touched at the end of
a recompute (R2-2)."""

from PartDesignTests.Scenarios.harness import (
    BROKEN, Chamfered, Scenario, X, edge,
)
from PartDesignTests.Scenarios import models as m


class Rim(Scenario):
    """Rim 3600 x 45, 235 high, padded from Profile in a Body; a Chamfer (5) on its outer top
    edge (y = 0). Subclasses edit."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564son-r3"
    TIER = "F"
    SIZE = 3600
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235
    edited = False

    def topEdge(self):
        return edge("line", direction=X, through=(0, 0, self.s(self.height)))

    def want(self):
        return self.topEdge()

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.topEdge()))
        chamfer.Size = self.s(5)
        doc.recompute()
        self.ref("chamfer", chamfer, "Base", lambda: self.want(), Chamfered(self.s(5)))

    def redraw(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)


class HolderBehindBarSetBase(Rim):
    """The Tip rolled back to Rims (the Chamfer, the holder, behind the bar); the rim redrawn in
    place and the Base set again; the document recomputed (Rims made, the Chamfer not run); the
    Tip brought forward; the document recomputed. The redraw in place: the person's edge."""

    def edit(self, doc):
        doc.Body.Tip = doc.Rims
        doc.recompute()
        self.redraw(doc)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute()
        doc.Body.Tip = doc.Chamfer
        doc.recompute()


class HolderBehindBarNoSetter(Rim):
    """The control without the setter."""

    def edit(self, doc):
        doc.Body.Tip = doc.Rims
        doc.recompute()
        self.redraw(doc)
        doc.recompute()
        doc.Body.Tip = doc.Chamfer
        doc.recompute()


class RedrawSetBasePadSingle(Rim):
    """Redraw in place, Base set again, the Pad recomputed alone (the sketch not), then the
    document."""

    def edit(self, doc):
        self.redraw(doc)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Rims.recompute()
        doc.recompute()


class SlideAfterPadSingle(Rim):
    """Rim 2 drawn and recomputed (resolved with rim 2 in the model); rim 1 deleted, rim 2
    dragged to y = 0, the Base set again, the Pad recomputed alone; the document. Rim 2 was
    there: break."""

    steps = ("draw", "slide")

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def draw(self, doc):
        doc.Profile.addGeometry(self.rect(2000), False)

    def slide(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Rims.recompute()
        self.edited = True


class BarSlideAfterDraw(Rim):
    """The Tip rolled back to Rims; rim 2 drawn (the bar: the Chamfer doesn't run); the Tip
    forward and the document recomputed (the Chamfer resolves with rim 2 there); then rim 1
    deleted and rim 2 dragged onto y = 0 and the Base set again. Rim 2 was there: break."""

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Body.Tip = doc.Rims
        doc.recompute()
        doc.Profile.addGeometry(self.rect(2000), False)
        doc.recompute()
        doc.Body.Tip = doc.Chamfer
        doc.recompute()
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Chamfer.Base = doc.Chamfer.Base
        self.edited = True


class BarSetThenDrawThenSlide(Rim):
    """The Tip rolled back to Rims (Chamfer behind the bar); the rim redrawn in place and Base
    set (hold); recompute; rim 2 drawn; recompute; Tip forward, recompute (the Chamfer resolves
    with rim 2 there); rim 1 deleted and rim 2 dragged onto y = 0: rim 2 was there: break."""

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Body.Tip = doc.Rims
        doc.recompute()
        self.redraw(doc)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute()
        doc.Profile.addGeometry(self.rect(2000), False)
        doc.recompute()
        doc.Body.Tip = doc.Chamfer
        doc.recompute()
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Chamfer.Base = doc.Chamfer.Base
        self.edited = True


class HolderBehindBarThenSlide(Rim):
    """As above but the bar stays behind the holder (Tip = Rims) while rim 2 is drawn and slid;
    only then the Tip is brought forward. The Chamfer never saw rim 2: the redraw in place and
    the slide are one net edit of the rim: rim 1's edge's place now holds rim 2's: on integration
    the Chamfer resolves to it (drawn since). Right: the edge at y = 0 (the person's)."""

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Body.Tip = doc.Rims
        doc.recompute()
        doc.Profile.addGeometry(self.rect(2000), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute()
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute()
        doc.Body.Tip = doc.Chamfer
        doc.recompute()
