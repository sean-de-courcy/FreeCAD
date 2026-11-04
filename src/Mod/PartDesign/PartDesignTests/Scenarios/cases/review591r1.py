"""Review pr591-r1 (ops#591, decision 262 (1)): leads that fail on nothing and are claimed with the
empty pass-through, aimed at what the PR's emptyOnEmpty() branch of solidClaimed() changes.

Each case: a 600 x 300 block padded 300 high (Pad1), a 100 x 100 boss padded 50 on its top (Pad2,
its sketch at z = 300), a fillet r 10 on the boss's top back edge (y = 200, z = 350), judged by its
edge and by the volume the full model has after each step (the block, less what the case's still
working cuts remove, plus the boss, less the fillet's (1 - pi/4) r^2 L)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Outcome, Reopens, Scenario, X, Z, edge
from PartDesignTests.Scenarios import models as m


class FilletOnFullModel(Outcome):
    """The consumer's volume is the full model's (scenario.fullVolume()) as the step leaves it."""

    def compare(self, scenario, consumer, target, expectation):
        want = scenario.fullVolume()
        got = consumer.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"{consumer.Name} volume {got:.1f}, the full model's is {want:.1f}"
        return True, ""


class Lead591(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#591"
    FOUND_BY = "review pr591-r1"
    TIER = "F"
    SIZE = 600
    REFS = ("fillet_edge",)
    steps = ("fail", "fix")
    radius = 10
    cut = 0.0  # the volume the case's working cuts take from the block, at scale 1

    def topBackEdge(self):
        return edge("line", direction=X, through=self.s(300, 200, 350))

    def fullVolume(self):
        L, W, H, b, h, r = self.s(600, 300, 300, 100, 50, self.radius)
        return L * W * H - self.cut * self.scale**3 + b * b * h - (1 - math.pi / 4) * r * r * b

    def gaugeAndBlock(self, doc, body):
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        pad1 = m.pad(body, base, self.s(300), "Pad1")
        pad1.setExpression("Length", "Gauge.Height")
        return pad1

    def bossAndFillet(self, doc, body):
        sketch = m.sketch(doc, "BossSketch", m.rectangle(*self.s(250, 100, 350, 200)), body,
                          z=self.s(300))
        boss = m.pad(body, sketch, self.s(50), "Pad2")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (boss, self.names(boss, self.topBackEdge()))
        fillet.Radius = self.s(self.radius)
        doc.recompute()
        self.ref("fillet_edge", fillet, "Base", self.topBackEdge, FilletOnFullModel())

    def fail(self, doc):
        doc.Gauge.Length = 0

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)


class ReorderedChamferLead(Lead591):
    """A chamfer 5 on Pad1's vertical edge at x = y = 0; Pad1 moved below it (Body.reorderObject:
    the chamfer becomes the lead, its Base cleared, fork PR 270 M1). Then the boss and the fillet;
    Gauge fails (Pad1 with it), then is made good."""

    def build(self, doc):
        body = m.body(doc)
        pad1 = self.gaugeAndBlock(doc, body)
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad1, self.names(pad1, edge("line", direction=Z,
                                                     through=self.s(0, 0, 150))))
        chamfer.Size = self.s(5)
        doc.recompute()
        body.reorderObject([pad1], chamfer, True)
        body.Tip = pad1
        doc.recompute()
        self.bossAndFillet(doc, body)


class ReorderedPatternLead(Lead591):
    """A 20 x 20 pocket 20 deep at (20, 20) on the block's top, patterned twice 60 along X; the
    pattern moved to the top of the Body (its Original parked). The pocket itself still cuts."""

    cut = 20 * 20 * 20

    def build(self, doc):
        body = m.body(doc)
        self.gaugeAndBlock(doc, body)
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(20, 20, 40, 40)), body,
                          z=self.s(300))
        pocket = m.pocket(body, sketch, self.s(20), "PocketA")
        doc.recompute()
        pattern = body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [pocket]
        pattern.Direction = (m.originFeature(body, "X_Axis"), [""])
        pattern.Length = self.s(60)
        pattern.Occurrences = 2
        body.Tip = pattern
        doc.recompute()
        body.reorderObject([pattern], None, True)
        body.Tip = pocket
        doc.recompute()
        self.bossAndFillet(doc, body)


class TwoLeads(Lead591):
    """Two leads that fail on nothing: a subtractive box, then a chamfer with no Base; then Pad1."""

    def build(self, doc):
        body = m.body(doc)
        box = body.newObject("PartDesign::SubtractiveBox", "SubBox")
        box.Length, box.Width, box.Height = self.s(10, 10, 10)
        box.Placement.Base = App.Vector(*self.s(500, 0, 290))
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Size = self.s(1)
        self.gaugeAndBlock(doc, body)
        self.bossAndFillet(doc, body)


class SuppressedPadThenFailedPocket(Lead591):
    """A Valid lead that makes nothing (a suppressed pad), then a pocket that fails on it (claimed:
    its base is current and holds no solid), then Pad1: Gauge fails."""

    def build(self, doc):
        body = m.body(doc)
        sketch = m.sketch(doc, "LeadSketch", m.rectangle(*self.s(0, 0, 50, 50)), body)
        lead = m.pad(body, sketch, self.s(900), "Lead")
        lead.Suppressed = True
        psketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(500, 0, 550, 50)), body,
                           z=self.s(300))
        m.pocket(body, psketch, self.s(20), "Pocket")
        self.gaugeAndBlock(doc, body)
        self.bossAndFillet(doc, body)


class ComposedParkAndFail(Lead591):
    """A 50 x 50 pocket 20 deep at the block's corner (500, 0) cuts it; in one edit the pocket is
    moved to the top (ops#127's park, in a transaction) and Gauge fails; Gauge made good; the move
    undone (the pocket cuts the block again)."""

    steps = ("parkAndFail", "fix", "undoPark")
    cut = 50 * 50 * 20

    def build(self, doc):
        doc.UndoMode = 1
        body = m.body(doc)
        self.gaugeAndBlock(doc, body)
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(500, 0, 550, 50)), body,
                          z=self.s(300))
        m.pocket(body, sketch, self.s(20), "Pocket")
        doc.recompute()
        self.bossAndFillet(doc, body)

    def parkAndFail(self, doc):
        doc.openTransaction("Move")
        doc.Body.reorderObject([doc.Pocket], None, True)
        doc.commitTransaction()
        doc.Gauge.Length = 0
        self.cut = 0.0

    def undoPark(self, doc):
        doc.undo()
        self.cut = 50 * 50 * 20


class ParkedPocketReopened(Reopens, Lead591):
    """The corner pocket moved to the top, the document saved and reopened, then Gauge fails and
    is made good."""

    steps = ("park", "reopen", "fail", "fix")
    cut = 50 * 50 * 20

    def build(self, doc):
        body = m.body(doc)
        self.gaugeAndBlock(doc, body)
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(500, 0, 550, 50)), body,
                          z=self.s(300))
        m.pocket(body, sketch, self.s(20), "Pocket")
        doc.recompute()
        self.bossAndFillet(doc, body)

    def park(self, doc):
        doc.Body.reorderObject([doc.Pocket], None, True)
        self.cut = 0.0


class _EmptyingStock:
    """An outside scripted solid: a 600 x 300 x 300 block, or, with Size 0, no shape and an error
    (its execute() clears the shape before it raises)."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLength", "Size")
        obj.Proxy = self

    def execute(self, obj):
        if obj.Size.Value <= 0:
            obj.Shape = Part.Shape()
            raise RuntimeError("no stock")
        k = obj.Size.Value / 600.0
        obj.Shape = Part.makeBox(600 * k, 300 * k, 300 * k)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class DressUpLeadOnOutsideBase(Lead591):
    """The Body's first solid feature is a fillet r 10 whose Base (set from Python; its BaseFeature
    stays None, DressUp::onChanged) is the vertical x = y = 0 edge of Stock, an outside scripted
    600 x 300 x 300 block; the boss sits on it. Stock fails with no shape (Size 0): the fillet
    fails naming it, and whatever follows has no real base. Then Stock is made good."""

    def fullVolume(self):
        L, W, H, b, h, r = self.s(600, 300, 300, 100, 50, self.radius)
        corner = (1 - math.pi / 4) * r * r * H
        return L * W * H - corner + b * b * h - (1 - math.pi / 4) * r * r * b

    def build(self, doc):
        stock = doc.addObject("Part::FeaturePython", "Stock")
        _EmptyingStock(stock)
        stock.Size = self.s(600)
        doc.recompute()
        body = m.body(doc)
        lead = body.newObject("PartDesign::Fillet", "Lead")
        lead.Base = (stock, self.names(stock, edge("line", direction=Z,
                                                   through=self.s(0, 0, 150))))
        lead.Radius = self.s(self.radius)
        doc.recompute()
        self.bossAndFillet(doc, body)

    def fail(self, doc):
        doc.Stock.Size = 0

    def fix(self, doc):
        doc.Stock.Size = self.s(600)
