"""Review pr579-r4f (ops#579 round 4 fix): composed edits across the switch between a claimed
failure (the Body continues, the failed feature passes its base through) and a stopped Body (its
first solid feature in error, decision 255 (1) literal), on the same model as r4f_supplead: a
600 x 300 x 300 block (Pad1, its length an expression on Gauge, a Part box outside the Body), a
100 x 100 x 50 boss on its top (Pad2), a fillet r 10 on the boss's top back edge (y = 200,
z = 350), judged by its edge and by the full model's volume."""

import math

from PartDesignTests.Scenarios.harness import Outcome, Scenario, X, edge
from PartDesignTests.Scenarios import models as m


class FilletOnFullModel(Outcome):
    def compare(self, scenario, consumer, target, expectation):
        want = scenario.fullVolume()
        got = consumer.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"{consumer.Name} volume {got:.1f}, the full model's is {want:.1f}"
        return True, ""


class Switch(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r4f"
    TIER = "F"
    SIZE = 600
    REFS = ("fillet_edge",)
    radius = 10

    def topBackEdge(self):
        return edge("line", direction=X, through=self.s(300, 200, 350))

    def fullVolume(self):
        L, W, H, b, h, r = self.s(600, 300, 300, 100, 50, self.radius)
        return L * W * H + b * b * h - (1 - math.pi / 4) * r * r * b

    def build(self, doc):
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        pad1 = m.pad(body, base, self.s(300), "Pad1")
        pad1.setExpression("Length", "Gauge.Height")
        sketch = m.sketch(doc, "BossSketch", m.rectangle(*self.s(250, 100, 350, 200)), body,
                          z=self.s(300))
        boss = m.pad(body, sketch, self.s(50), "Pad2")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (boss, self.names(boss, self.topBackEdge()))
        fillet.Radius = self.s(self.radius)
        doc.recompute()
        self.ref("fillet_edge", fillet, "Base", self.topBackEdge, FilletOnFullModel())

    def bossFails(self, doc):
        doc.Pad2.Length = 0

    def bossBack(self, doc):
        doc.Pad2.Length = self.s(50)

    def gaugeFails(self, doc):
        doc.Gauge.Length = 0

    def gaugeBack(self, doc):
        doc.Gauge.Length = self.s(10)


class BossThenBaseFailFixBaseThenBoss(Switch):
    """The boss fails (claimed: it passes the block through), then the block (the Body stops);
    the block is made good (the boss's claim again), then the boss."""

    steps = ("bossFails", "gaugeFails", "gaugeBack", "bossBack")


class BossThenBaseFailFixBossThenBase(Switch):
    """As above, the boss made good first, while the Body is stopped."""

    steps = ("bossFails", "gaugeFails", "bossBack", "gaugeBack")


class BaseThenBossFailFixBaseThenBoss(Switch):
    """The block fails first (the Body stops), then the boss; the block is made good (the boss's
    failure is claimed now), then the boss."""

    steps = ("gaugeFails", "bossFails", "gaugeBack", "bossBack")
