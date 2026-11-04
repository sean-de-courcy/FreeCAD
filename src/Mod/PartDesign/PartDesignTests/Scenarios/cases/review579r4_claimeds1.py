"""Review pr579-r4 (ops#579 round 4, decision 256): the record-take for a feature failed in S1
that the Body's rule then claims. Pad2, a boss whose length is an expression on Gauge (a Part box
outside the Body), fails without running when Gauge fails, and the rule claims it: it passes Pad1
through. Decision 256's take lists every S1 failure, so the references into Pad2 are taken on the
pass-through shape at the recompute's end (the design left claimed failures out).

Pad1: rim 1, a 3600 x 45 rectangle at y = 0, padded 300. Pad2: a 100 x 30 boss on its top
(x 1000..1100, y 10..40), length Gauge.Height (50). Top: a free-standing sketch in the Body attached
to Pad2's front face (y = 0, Pad1's own). Rim 2 is drawn at y = 2000; then rim 1 is deleted and rim
2 slid onto y = 0: rim 2 was in the model before, so the front face breaks (as the control)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m


class ClaimedS1(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r4"
    TIER = "F"
    SIZE = 3600
    REFS = ("front",)
    length, thickness, height = 3600, 45, 300
    edited = False

    def frontFace(self):
        return face("plane", normal=(0, -1, 0), through=(0, 0, 0))

    def want(self):
        return BROKEN if self.edited else self.frontFace()

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        m.box(doc, "Gauge", self.s(10, 10, 50), at=self.s(9000, 0, 0))
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), body)
        m.pad(body, profile, H, "Pad1")
        boss = m.sketch(doc, "BossSketch", m.rectangle(*self.s(1000, 10, 1100, 40)), body, z=H)
        pad2 = m.pad(body, boss, self.s(50), "Pad2")
        pad2.setExpression("Length", "Gauge.Height")
        doc.recompute()
        top = body.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(pad2, self.names(pad2, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", lambda: self.want(), Attached())

    def drawRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)

    def breakGauge(self, doc):
        doc.Gauge.Length = 0

    def fixGauge(self, doc):
        doc.Gauge.Length = self.s(10)

    def slideRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class ClaimedS1DrawBreakSlideFixed(ClaimedS1):
    steps = ("drawAndBreak", "slideAndFix")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakGauge(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixGauge(doc)


class ClaimedS1BreakDrawSlideFixed(ClaimedS1):
    steps = ("breakFirst", "draw", "slideAndFix")

    def breakFirst(self, doc):
        self.breakGauge(doc)

    def draw(self, doc):
        self.drawRim2(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixGauge(doc)


class ClaimedS1BreakSlideWhileDown(ClaimedS1):
    """Rim 2 drawn, then Gauge broken, then rim 2 slid while Pad2 is still down (Pad1 rebuilds:
    the reference is judged on Pad2's pass-through), then Gauge fixed."""

    steps = ("draw", "breakFirst", "slide", "fix")

    def draw(self, doc):
        self.drawRim2(doc)

    def breakFirst(self, doc):
        self.breakGauge(doc)

    def slide(self, doc):
        self.slideRim2(doc)

    def fix(self, doc):
        self.fixGauge(doc)


class ClaimedS1Control(ClaimedS1):
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)
