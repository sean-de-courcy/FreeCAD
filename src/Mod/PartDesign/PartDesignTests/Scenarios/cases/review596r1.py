"""Review pr596-r1 (ops#596, design notes/park-design.md 5 (P) and (R)): the additive park (W16),
aimed at what the PR changes: the claim of a parked first Pad with the empty pass-through, and rule
PT's veto lifted for a parked lead (shapeInputChain(): a claimed failure with a null shape is no
longer `failed`).

Each case: a 600 x 300 block padded 300 high (Pad1), a 100 x 100 boss padded 50 whose sketch is
attached to Pad1's top face (Pad2), references taken on Pad2's shape (the Tip the user picks on),
then Pad2 moved above Pad1 (Body.reorderObject, the GUI's drag)."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Filleted,
    Outcome,
    Scenario,
    X,
    Z,
    edge,
    face,
)
from PartDesignTests.Scenarios import models as m

NY = (0, -1, 0)


class Park596R1(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#596"
    FOUND_BY = "review pr596-r1"
    TIER = "F"
    SIZE = 600
    REFS = ()
    steps = ("park", "taller", "back")
    height = 300
    parked = False
    boss = (250, 100, 350, 200)  # the boss's footprint on the block's top, at scale 1

    def blockTop(self, at=(100, 50)):
        return face("plane", normal=Z, contains=self.s(at[0], at[1], self.height))

    def block(self, doc, body):
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        return m.pad(body, base, self.s(300), "Pad1")

    def bossOn(self, doc, body, support, rect, name, sketchName):
        sketch = body.newObject("Sketcher::SketchObject", sketchName)
        sketch.AttachmentSupport = [support]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        local = sketch.getGlobalPlacement().inverse()
        x0, y0, x1, y1 = rect
        a, b = (local.multVec(App.Vector(*self.s(x, y, 300))) for x, y in ((x0, y0), (x1, y1)))
        sketch.addGeometry(
            m.rectangle(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y)), False
        )
        return m.pad(body, sketch, self.s(50), name)

    def extra(self, doc, body):
        """What the case adds after the boss, before the park; takes its references."""

    def build(self, doc):
        body = m.body(doc)
        pad = self.block(doc, body)
        doc.recompute()
        top = self.blockTop()
        self.bossOn(doc, body, (pad, self.names(pad, top)[0]), self.boss, "Pad2", "BossSketch")
        doc.recompute()
        self.parked = False
        self.extra(doc, body)
        doc.recompute()

    def park(self, doc):
        doc.Body.reorderObject([doc.Pad2], None, True)
        self.parked = True

    def taller(self, doc):
        doc.Pad1.Length = self.s(450)
        self.height = 450

    def back(self, doc):
        doc.Pad1.Length = self.s(300)
        self.height = 300

    def moveBack(self, doc):
        doc.Body.reorderObject([doc.Pad2], doc.Pad1, True)
        self.parked = False


class SketchOnParkedBossTop(Park596R1):
    """A sketch on the boss's top face (z = 350), taken on Pad2: while the boss is parked the face
    isn't there (the sketch must break, Onshape's sketch on a failed feature's face); moved back
    below Pad1, it is again, at the block's height plus 50."""

    REFS = ("sketch_boss",)
    steps = ("park", "taller", "moveBack")

    def bossTop(self):
        if self.parked:
            return BROKEN
        return face("plane", normal=Z, contains=self.s(300, 150, self.height + 50))

    def extra(self, doc, body):
        sketch = body.newObject("Sketcher::SketchObject", "OnBoss")
        sketch.AttachmentSupport = [
            (doc.Pad2, self.names(doc.Pad2, face("plane", normal=Z, contains=self.s(300, 150, 350))))
        ]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        self.ref("sketch_boss", sketch, "AttachmentSupport", self.bossTop, Attached())


class SketchOnFusedTop(Park596R1):
    """A sketch on the block's top face as Pad2 has it (with the boss's footprint), taken on Pad2;
    the boss parked: the sketch follows the block's top as Pad1 grows and comes back."""

    REFS = ("sketch_top",)

    def extra(self, doc, body):
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(doc.Pad2, self.names(doc.Pad2, self.blockTop()))]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        self.ref("sketch_top", sketch, "AttachmentSupport", self.blockTop, Attached())


class FlushBossFrontSketch(Park596R1):
    """The boss flush with the block's front (y = 0); a sketch on the block's front face as Pad2
    has it; the boss parked: the sketch stays on the front face as Pad1 grows."""

    REFS = ("sketch_front",)
    boss = (250, 0, 350, 100)

    def front(self):
        return face("plane", normal=NY, contains=self.s(100, 0, self.height / 2))

    def extra(self, doc, body):
        sketch = body.newObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(doc.Pad2, self.names(doc.Pad2, self.front()))]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        self.ref("sketch_front", sketch, "AttachmentSupport", self.front, Attached())


class FlushBossTopEdgeFillet(Park596R1):
    """The boss flush with the block's front; a fillet r 10 on the block's top front edge left of
    the boss (x 0..250, split by the boss on Pad2); the boss parked: the edge is the block's whole
    top front edge, as Pad1 grows and comes back."""

    REFS = ("fillet_edge",)
    boss = (250, 0, 350, 100)
    radius = 10

    def topFront(self):
        return edge("line", direction=X, contains=self.s(100, 0, self.height))

    def extra(self, doc, body):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (doc.Pad2, self.names(doc.Pad2, self.topFront()))
        fillet.Radius = self.s(self.radius)
        doc.recompute()
        self.ref("fillet_edge", fillet, "Base", self.topFront, Filleted(self.s(self.radius)))


class TwinBossTopSketch(Park596R1):
    """Two equal bosses on the block's top: A (Pad2, at x 100..200) and B (Pad3, at x 400..500),
    both 50 high; a sketch on A's top face taken on Pad3. A parked: its top is gone and B's top
    is its twin at the same height (the sketch must break); A moved back, it is A's top again."""

    REFS = ("sketch_a",)
    steps = ("park", "taller", "moveBack")
    boss = (100, 100, 200, 200)

    def aTop(self):
        if self.parked:
            return BROKEN
        return face("plane", normal=Z, contains=self.s(150, 150, self.height + 50))

    def extra(self, doc, body):
        top = self.blockTop()
        self.bossOn(doc, body, (doc.Pad1, self.names(doc.Pad1, top)[0]), (400, 100, 500, 200),
                    "Pad3", "BSketch")
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "OnA")
        sketch.AttachmentSupport = [
            (doc.Pad3, self.names(doc.Pad3, face("plane", normal=Z, contains=self.s(150, 150, 350))))
        ]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        self.ref("sketch_a", sketch, "AttachmentSupport", self.aTop, Attached())


class ZeroLengthWhileParked(Park596R1):
    """The design's stale-record trace (park-design 9): the boss parked, its Length set to 0 while
    parked, then moved back below Pad1 with Length 0 (its own failure, mid-Body), then Pad1
    taller. A fillet r 10 on the block's front bottom edge taken on Pad2 keeps its edge."""

    REFS = ("fillet_edge",)
    steps = ("park", "zero", "moveBack", "taller")
    radius = 10

    def frontBottom(self):
        return edge("line", direction=X, contains=self.s(300, 0, 0))

    def extra(self, doc, body):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (doc.Pad2, self.names(doc.Pad2, self.frontBottom()))
        fillet.Radius = self.s(self.radius)
        doc.recompute()
        self.ref("fillet_edge", fillet, "Base", self.frontBottom, Filleted(self.s(self.radius)))

    def zero(self, doc):
        doc.Pad2.Length = 0


class FullVolume(Outcome):
    """The consumer's volume is the full model's (scenario.fullVolume()) as the step leaves it."""

    def compare(self, scenario, consumer, target, expectation):
        want = scenario.fullVolume()
        got = consumer.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"{consumer.Name} volume {got:.1f}, the full model's is {want:.1f}"
        return True, ""


class StockReadsParkedSketch(Park596R1):
    """The boss parked; then the stock Pad1 is given the parked boss sketch's normal as its
    direction reference (ReferenceAxis; the GUI's "Select reference..."): Pad1 fails naming the
    sketch, which holds the park's record, though Pad1 was never moved and everything after it
    was built on it. A Pad3 (100 x 100, 400 long from z = 0 at the block's back right corner, so
    it pokes 100 above the block) and a fillet r 10 on its top back edge come after Pad1; judged
    on the full model's volume (the block with Pad3, less the fillet); the link removed again."""

    REFS = ("fillet_edge",)
    steps = ("park", "link", "unlink")
    radius = 10

    def p3TopBack(self):
        return edge("line", direction=X, contains=self.s(550, 300, 400))

    def fullVolume(self):
        L, W, H, b, h, r = self.s(600, 300, 300, 100, 400, self.radius)
        boss = 0 if self.parked else b * b * self.s(50)
        return L * W * H + b * b * (h - H) - (1 - math.pi / 4) * r * r * b + boss

    def extra(self, doc, body):
        sketch = m.sketch(doc, "P3Sketch", m.rectangle(*self.s(500, 200, 600, 300)), body)
        pad3 = m.pad(body, sketch, self.s(400), "Pad3")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad3, self.names(pad3, self.p3TopBack()))
        fillet.Radius = self.s(self.radius)
        doc.recompute()
        self.ref("fillet_edge", fillet, "Base", self.p3TopBack, FullVolume())

    def link(self, doc):
        doc.Pad1.ReferenceAxis = (doc.BossSketch, ["N_Axis"])

    def unlink(self, doc):
        doc.Pad1.ReferenceAxis = None
