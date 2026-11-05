"""Review pr579-r4 (ops#579 round 4, decisions 255 (1) and 257): a Body whose first solid feature is
a subtractive one that makes nothing on nothing (in error: "Nothing to cut", as a reorder or the
user leaves it at the top), followed by the Body's real base, Pad1. 257 passes the leading
feature's empty base through, and baseInError() stops reading the Body at that first solid
feature, so a failure of Pad1 (the feature that makes the Body's first solid) is claimed again:
its pass-through is the empty shape, and the boss after it computes on nothing, Valid: round 3's
FirstPad* silent, reopened by a leading subtractive feature.

Since ops#591 (decision 262 (1)) the leading feature is claimed with the empty pass-through, exactly
its result on nothing, so the Body computes below it at the build; a failure of Pad1 is judged on
Pad1's own pass-through, which is empty, so the Body stops (loud), as round 4 left it.

Each case: a 600 x 300 block padded 300 high (Pad1), a 100 x 100 boss padded 50 on its top (Pad2,
its sketch at z = 300), a fillet r 10 on the boss's top back edge (y = 200, z = 350), judged by its
edge and its volume (the block, the boss, less the fillet's (1 - pi/4) r^2 L). The leading
feature: a subtractive box 10 x 10 x 10 at (500, 0, 290) (FeatureAddSub, subtractive), or a
pocket 20 deep of a 50 x 50 square at z = 300."""

import math

import FreeCAD as App
import Part

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


class LeadSub(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#591"
    FOUND_BY = "review pr579-r4"
    TIER = "F"
    SIZE = 600
    REFS = ("fillet_edge",)
    steps = ("fail", "fix")
    radius = 10
    lead = "subbox"

    def topBackEdge(self):
        return edge("line", direction=X, through=self.s(300, 200, 350))

    def fullVolume(self):
        L, W, H, b, h, r = self.s(600, 300, 300, 100, 50, self.radius)
        return L * W * H + b * b * h - (1 - math.pi / 4) * r * r * b

    def leading(self, doc, body):
        if self.lead == "subbox":
            box = body.newObject("PartDesign::SubtractiveBox", "SubBox")
            box.Length, box.Width, box.Height = self.s(10, 10, 10)
            box.Placement.Base = App.Vector(*self.s(500, 0, 290))
        else:
            sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(500, 0, 550, 50)), body,
                              z=self.s(300))
            m.pocket(body, sketch, self.s(20), "Pocket")

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


class LeadSubExprOnFailedGauge(LeadSub):
    """Pad1's length is an expression on Gauge, a Part box outside the Body (300 high). Gauge fails
    (length 0); then it is made good. Integration's filter leaves Pad1 unrun on its old shape."""

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


class LeadPocketExprOnFailedGauge(LeadSubExprOnFailedGauge):
    lead = "pocket"


class LeadSubOnBinderOfFailedPlate(LeadSub):
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


class LeadSubOwnFailure(LeadSub):
    """Pad1 fails on its own (length 0); then it is made good (integration passes the empty shape
    through as well: the shared form)."""

    def build(self, doc):
        body = m.body(doc)
        self.leading(doc, body)
        self.block(doc, body)
        self.bossAndFillet(doc, body)

    def fail(self, doc):
        doc.Pad1.Length = 0

    def fix(self, doc):
        doc.Pad1.Length = self.s(300)


class LeadSubControl(LeadSubExprOnFailedGauge):
    """The control: Gauge gets taller and back (no failure)."""

    def fail(self, doc):
        doc.Gauge.Length = self.s(20)


class ReorderedPocketExprOnFailedGauge(LeadSubExprOnFailedGauge):
    """As LeadSubExprOnFailedGauge, the leading pocket put there by a reorder: built after Pad1 (a
    50 x 50 square at z = 300, 20 deep, cutting the block), then moved above Pad1 (ops#127's
    reorder park: it cuts nothing there). The full model is then the block, the boss and the
    fillet."""

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
        self.bossAndFillet(doc, body)
