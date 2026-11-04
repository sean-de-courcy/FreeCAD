"""Review pr579s-r5 (ops#579, decision 262): the chain rule and (N) for a MultiTransform's step.

The model: a 600 x 300 block padded 300 high; bosses 100 x 100 on its top, 50 high. Judged by a
sketch outside the Body attached to the Body's front face (y = 0) and by the Body's volume.

MtStep*: a MultiTransform of a boss whose step takes its offset from Gauge, a Part box outside the
Body. Gauge fails: the step (not a solid feature) is stopped by an input no rule claims, so the
MultiTransform fails naming it and passes the boss through; the boss after it computes.

PatternChain*: a LinearPattern after a boss, the boss fails on its own and the pattern fails on its
own in the same edit: both pass the block through (a claimed failure serves as a base).

DressUpChain*: a pad after a failed pattern whose Gauge also fails.
"""

from PartDesignTests.Scenarios.harness import Attached, Scenario, Y, face
from PartDesignTests.Scenarios import models as m


class AttachedWithBodyVolume(Attached):
    def compare(self, scenario, consumer, target, expectation):
        ok, why = super().compare(scenario, consumer, target, expectation)
        if not ok:
            return ok, why
        want = scenario.bodyVolume()
        got = scenario.doc.Body.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"Body volume {got:.1f}, expected {want:.1f}"
        return True, ""


class R5(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579s-r5"
    TIER = "F"
    SIZE = 600
    REFS = ("front",)
    steps = ("fail", "fix")
    bosses = 0

    def front(self):
        return face("plane", normal=-Y, through=self.s(300, 0, 150))

    def bodyVolume(self):
        L, W, H, b, h = self.s(600, 300, 300, 100, 50)
        return L * W * H + self.bosses * b * b * h

    def boss(self, doc, body, name, x0, y0=100, length=50):
        sk = m.sketch(doc, name + "S", m.rectangle(*self.s(x0, y0, x0 + 100, y0 + 100)), body,
                      z=self.s(300))
        return m.pad(body, sk, self.s(length), name)

    def outsideRef(self, doc, body):
        sketch = doc.addObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(body, self.names(body, self.front())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("front", sketch, "AttachmentSupport", self.front, AttachedWithBodyVolume())

    def block(self, doc):
        m.box(doc, "Gauge", self.s(10, 10, 50), at=self.s(2000, 0, 0))
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        m.pad(body, base, self.s(300), "Pad1")
        return body


class MtStep(R5):
    """A MultiTransform whose step reads a failing Gauge; a boss after it."""

    abstract = True
    bossesBefore = 1

    def build(self, doc):
        body = self.block(doc)
        boss = self.boss(doc, body, "BossA", 50)
        mt = doc.addObject("PartDesign::MultiTransform", "MT")
        mt.Originals = [boss]
        mt.Refine = False
        body.addObject(mt)
        step = doc.addObject("PartDesign::LinearPattern", "Step")
        step.Direction = (m.originFeature(body, "X_Axis"), [""])
        step.Mode = "Spacing"
        step.Offset = self.s(100)
        step.Occurrences = 2
        body.addObject(step)
        mt.Transformations = [step]
        step.setExpression("Offset", "Gauge.Height * 2")
        self.boss(doc, body, "BossB", 400, 100)
        doc.recompute()
        self.bosses = 3
        self.outsideRef(doc, body)

    def fail(self, doc):
        doc.Gauge.Length = 0
        self.bosses = 2  # MT passes BossA through; BossB computes

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)
        self.bosses = 3


class MtStepOnFailedGauge(MtStep):
    pass


class PatternChain(R5):
    """Boss, pattern of it, a boss after: the boss and the pattern fail on their own at once."""

    def build(self, doc):
        body = self.block(doc)
        boss = self.boss(doc, body, "BossA", 50)
        lp = body.newObject("PartDesign::LinearPattern", "LP")
        lp.Originals = [boss]
        lp.Direction = (m.originFeature(body, "X_Axis"), [""])
        lp.Length = self.s(150)
        lp.Occurrences = 2
        body.Tip = lp
        self.boss(doc, body, "BossB", 400, 100)
        doc.recompute()
        self.bosses = 3
        self.outsideRef(doc, body)

    def fail(self, doc):
        doc.BossA.Length = 0
        doc.LP.setExpression("Length", "Gauge.Height")
        doc.Gauge.Length = 0
        self.bosses = 1  # BossA and LP pass the block through; BossB computes

    def fix(self, doc):
        doc.BossA.Length = self.s(50)
        doc.LP.setExpression("Length", None)
        doc.LP.Length = self.s(150)
        doc.Gauge.Length = self.s(10)
        self.bosses = 3  # BossA, its copy (LP Length 100 -> a second instance), BossB


class PatternChainOneStep(PatternChain):
    """The same, the fix is in two recomputes (Gauge first)."""

    steps = ("fail", "fixGauge", "fixBoss")

    def fixGauge(self, doc):
        doc.Gauge.Length = self.s(10)
        self.bosses = 1  # LP is back (its copies of BossA's pass-through: none); BossB

    def fixBoss(self, doc):
        doc.BossA.Length = self.s(50)
        doc.LP.setExpression("Length", None)
        doc.LP.Length = self.s(150)
        self.bosses = 3
