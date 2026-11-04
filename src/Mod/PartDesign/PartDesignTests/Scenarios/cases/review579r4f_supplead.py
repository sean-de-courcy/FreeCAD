"""Review pr579-r4f (ops#579 round 4 fix, decision 255 (1) literal): a Body whose first solid
feature is suppressed (Suppressed = True: it passes its empty base through, Valid, not in error),
followed by the Body's real base, Pad1. baseInError() reads only the first solid feature, which
isn't in error, so a failure of Pad1 is claimed: its pass-through is the empty shape, and the boss
after it computes on nothing, Valid, and so does the Body: round 3's T-R3-1 / round 4's R4-1,
reached through a suppressed leading feature instead of a failing one.

The user path: a reorder leaves a pocket at the top ("Nothing to cut"); under the literal rule the
Body stops below it, and the user suppresses the pocket to get the Body back. Or a first Pad the
user suppressed (a stock block switched off).

Each case: a 600 x 300 block padded 300 high (Pad1), a 100 x 100 boss padded 50 on its top (Pad2,
its sketch at z = 300), a fillet r 10 on the boss's top back edge (y = 200, z = 350), judged by its
edge and by the full model's volume (the block, the boss, less the fillet's (1 - pi/4) r^2 L)."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Outcome, Scenario, X, edge
from PartDesignTests.Scenarios import models as m


class FilletOnFullModel(Outcome):
    """The consumer's volume is the full model's (block + boss) less the fillet's."""

    def compare(self, scenario, consumer, target, expectation):
        want = scenario.fullVolume()
        got = consumer.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"{consumer.Name} volume {got:.1f}, the full model's is {want:.1f}"
        return True, ""


class SuppLead(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r4f"
    TIER = "F"
    SIZE = 600
    REFS = ("fillet_edge",)
    steps = ("fail", "fix")
    radius = 10
    lead = "pocket"

    def topBackEdge(self):
        return edge("line", direction=X, through=self.s(300, 200, 350))

    def fullVolume(self):
        L, W, H, b, h, r = self.s(600, 300, 300, 100, 50, self.radius)
        return L * W * H + b * b * h - (1 - math.pi / 4) * r * r * b

    def leading(self, doc, body):
        """The suppressed first solid feature: a 50 x 50 pocket 20 deep at z = 300, or a 50 x 50
        pad 900 high at the origin (switched-off stock)."""
        if self.lead == "pocket":
            sketch = m.sketch(doc, "LeadSketch", m.rectangle(*self.s(500, 0, 550, 50)), body,
                              z=self.s(300))
            lead = m.pocket(body, sketch, self.s(20), "Lead")
        else:
            sketch = m.sketch(doc, "LeadSketch", m.rectangle(*self.s(0, 0, 50, 50)), body)
            lead = m.pad(body, sketch, self.s(900), "Lead")
        lead.Suppressed = True
        return lead

    def block(self, doc, body):
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        return m.pad(body, base, self.s(300), "Pad1")

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


class SuppPocketExprOnFailedGauge(SuppLead):
    """Pad1's length is an expression on Gauge, a Part box outside the Body (300 high). Gauge fails
    (length 0); then it is made good. The suppressed lead is a pocket."""

    def build(self, doc):
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        body = m.body(doc)
        self.leading(doc, body)
        pad1 = self.block(doc, body)
        pad1.setExpression("Length", "Gauge.Height")
        self.bossAndFillet(doc, body)

    def fail(self, doc):
        doc.Gauge.Length = 0

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)


class SuppPadExprOnFailedGauge(SuppPocketExprOnFailedGauge):
    """As SuppPocketExprOnFailedGauge, the suppressed lead a pad (switched-off stock)."""

    lead = "pad"


class SuppPocketOnBinderOfFailedPlate(SuppLead):
    """Pad1's profile is a SubShapeBinder in the Body of the top face (z = 0) of Plate, a Part box
    outside it. Plate fails (length 0); then it is made good."""

    def build(self, doc):
        plate = m.box(doc, "Plate", self.s(600, 300, 1), at=self.s(0, 0, -1))
        doc.recompute()
        top = [i + 1 for i, f in enumerate(plate.Shape.Faces) if abs(f.CenterOfMass.z) < 1e-6]
        body = m.body(doc)
        self.leading(doc, body)
        binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(plate, (f"Face{top[0]}",))]
        m.pad(body, binder, self.s(300), "Pad1")
        self.bossAndFillet(doc, body)

    def fail(self, doc):
        doc.Plate.Length = 0

    def fix(self, doc):
        doc.Plate.Length = self.s(600)


class ReorderedPocketSuppressedExprOnFailedGauge(SuppPocketExprOnFailedGauge):
    """The user path: the pocket is built after Pad1 (cutting the block), moved above it (ops#127's
    park: there it cuts nothing, in error, and the Body stops below it, decision 255 (1)), and
    suppressed to get the Body back. Then Gauge fails, and is made good. The full model is the
    block, the boss and the fillet."""

    def build(self, doc):
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        body = m.body(doc)
        pad1 = self.block(doc, body)
        pad1.setExpression("Length", "Gauge.Height")
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(500, 0, 550, 50)), body,
                          z=self.s(300))
        pocket = m.pocket(body, sketch, self.s(20), "Pocket")
        doc.recompute()
        body.removeObject(pocket)
        body.insertObject(pocket, pad1, False)
        doc.recompute()
        pocket.Suppressed = True
        doc.recompute()
        self.bossAndFillet(doc, body)


class EmptyBooleanLeadExprOnFailedGauge(SuppPocketExprOnFailedGauge):
    """As SuppPocketExprOnFailedGauge, the first solid feature a Boolean that never had a tool: it
    is Valid on its null shape (Boolean::execute, no tools and no shape), not in error, so the
    same claim of Pad1 follows."""

    def leading(self, doc, body):
        return body.newObject("PartDesign::Boolean", "Lead")


class SuppLeadControl(SuppPocketExprOnFailedGauge):
    """The control: Gauge gets taller and back (no failure)."""

    def fail(self, doc):
        doc.Gauge.Length = self.s(20)
