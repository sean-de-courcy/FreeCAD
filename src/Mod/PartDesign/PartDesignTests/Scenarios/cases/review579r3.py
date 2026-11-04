"""Review pr579-r3 (ops#579, decision 254): a Body's first solid feature, with no BaseFeature, fails
through an input outside the Body that no rule claims (S1, which integration's filter left out).
The Body's rule claims it, its pass-through is the empty shape, and the boss after it computes on
nothing, Valid: the same compute-on-nothing as round 2's T-R2-1, reached without a FeatureBase.

Each case: a 600 x 300 block padded 300 high (Pad1), a 100 x 100 boss padded 50 on its top (Pad2,
its sketch placed at z = 300), and a fillet r 10 on the boss's top back edge (y = 200, z = 350).
The fillet is judged by its edge and by its volume: the block, the boss, less the fillet's
(1 - pi/4) r^2 L. A fillet on the boss alone is the silent wrong result; a fillet that fails,
keeping its last output, is the loud one."""

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


class FirstPadRim(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r3"
    TIER = "F"
    SIZE = 600
    REFS = ("fillet_edge",)
    steps = ("fail", "fix")
    radius = 10

    def topBackEdge(self):
        return edge("line", direction=X, through=self.s(300, 200, 350))

    def fullVolume(self):
        L, W, H, b, h, r = self.s(600, 300, 300, 100, 50, self.radius)
        return L * W * H + b * b * h - (1 - math.pi / 4) * r * r * b

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
        return boss, fillet


class FirstPadExprOnFailedGauge(FirstPadRim):
    """Pad1's length is an expression on Gauge, a Part box outside the Body (300 high). Gauge
    fails (length 0); then it is made good."""

    def build(self, doc):
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        body = m.body(doc)
        pad1 = self.block(doc, body)
        pad1.setExpression("Length", "Gauge.Height")
        self.bossAndFillet(doc, body)

    def fail(self, doc):
        doc.Gauge.Length = 0

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)


class FirstPadOnBinderOfFailedPlate(FirstPadRim):
    """Pad1's profile is a SubShapeBinder in the Body of the top face (z = 0) of Plate, a Part box
    outside it. Plate fails (length 0); then it is made good."""

    def build(self, doc):
        plate = m.box(doc, "Plate", self.s(600, 300, 1), at=self.s(0, 0, -1))
        doc.recompute()
        top = [i + 1 for i, f in enumerate(plate.Shape.Faces)
               if abs(f.CenterOfMass.z) < 1e-6]
        body = m.body(doc)
        binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(plate, (f"Face{top[0]}",))]
        m.pad(body, binder, self.s(300), "Pad1")
        self.bossAndFillet(doc, body)

    def fail(self, doc):
        doc.Plate.Length = 0

    def fix(self, doc):
        doc.Plate.Length = self.s(600)


class FirstPadOwnFailure(FirstPadRim):
    """Pad1 fails on its own (length 0); then it is made good. (Integration has the same empty
    pass-through: the shared form of the two above.)"""

    def build(self, doc):
        body = m.body(doc)
        self.block(doc, body)
        self.bossAndFillet(doc, body)

    def fail(self, doc):
        doc.Pad1.Length = 0

    def fix(self, doc):
        doc.Pad1.Length = self.s(300)


class SecondBodyOnFirstPadExpr(FirstPadRim):
    """As FirstPadExprOnFailedGauge with no fillet in Body; a second Body on Body (BaseFeature) holds
    the fillet, on its FeatureBase's boss edge: a consumer outside the failed Body."""

    def build(self, doc):
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        body = m.body(doc)
        pad1 = self.block(doc, body)
        pad1.setExpression("Length", "Gauge.Height")
        sketch = m.sketch(doc, "BossSketch", m.rectangle(*self.s(250, 100, 350, 200)), body,
                          z=self.s(300))
        m.pad(body, sketch, self.s(50), "Pad2")
        doc.recompute()
        second = doc.addObject("PartDesign::Body", "Second")
        second.BaseFeature = body
        doc.recompute()
        base = second.Group[0]
        fillet = second.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (base, self.names(base, self.topBackEdge()))
        fillet.Radius = self.s(self.radius)
        doc.recompute()
        self.ref("fillet_edge", fillet, "Base", self.topBackEdge, FilletOnFullModel())

    def fail(self, doc):
        doc.Gauge.Length = 0

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)


class FirstPadControl(FirstPadExprOnFailedGauge):
    """The control: Gauge gets taller and back (no failure)."""

    def fail(self, doc):
        doc.Gauge.Length = self.s(20)
