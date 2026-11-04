"""Review pr579-r4h (ops#579 round 4 fix 3, decision 259): baseInError() asks every solid member
in error whether its pass-through is empty, from the state it holds when it is asked. A member
after the failed one, in error from an earlier recompute, is judged before its chain recomputes
in this one: its base's shape is its last, stale.

StaleNullSuccessor*: the user adds two bosses while the Body's first Pad is broken (each fails
naming its input, without running: its Shape stays null), then fixes the Pad, and in the same
edit the first boss fails on its own (Length 0). The first boss's pass-through is the block, but
the second boss is still in error from before with a null base (the first boss never ran):
baseInError() says the base is in error, the first boss isn't claimed, and the Body stops. It
stays stopped through further recomputes (the first boss never writes a shape). Right: the first
boss passes the block through, the second boss computes on it (pass-through, as integration).

OrphanFlip*: a member whose BaseFeature isn't the solid before it (set from Python): an orphan
pad with no base, in error from the step before; in the next step it is fixed and the boss (on
the block) fails. The boss is judged unclaimed while the orphan is still in error; if the orphan
then recomputes before the cap on the boss, the cap reads the boss's claim again, now claimed,
and runs on the boss's last shape (no pass-through was written).

The model: a 600 x 300 block padded 300 high; bosses 100 x 100 on its top, 50 high. Judged by a
sketch attached to the block's front face (y = 0) and by the Body's volume."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Attached, Scenario, Y, Z, face
from PartDesignTests.Scenarios import models as m


class AttachedWithBodyVolume(Attached):
    """Attached, and the Body's volume is the scenario's expected one."""

    def compare(self, scenario, consumer, target, expectation):
        ok, why = super().compare(scenario, consumer, target, expectation)
        if not ok:
            return ok, why
        want = scenario.bodyVolume()
        got = scenario.doc.Body.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"Body volume {got:.1f}, expected {want:.1f}"
        return True, ""


class StaleBase(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r4h"
    TIER = "F"
    SIZE = 600
    REFS = ("front",)
    bosses = 0  # the bosses the expected Body holds (each 100 x 100 x 50)

    def front(self):
        return face("plane", normal=-Y, through=self.s(300, 0, 150))

    def bodyVolume(self):
        L, W, H, b, h = self.s(600, 300, 300, 100, 50)
        return L * W * H + self.bosses * b * b * h

    def boss(self, doc, body, name, x0, length=50):
        sketch = m.sketch(doc, name + "Sketch",
                          m.rectangle(*self.s(x0, 100, x0 + 100, 200)), body, z=self.s(300))
        return m.pad(body, sketch, self.s(length), name)


class StaleNullSuccessor(StaleBase):
    """The ref: a sketch in the Body attached to the block's front face; the Body's volume."""

    abstract = True
    failBoss = True
    extraRecompute = True

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        pad1 = m.pad(body, base, self.s(300), "Pad1")
        doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(body, self.names(body, self.front())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("front", sketch, "AttachmentSupport", self.front,
                 AttachedWithBodyVolume())

    def edit(self, doc):
        body = doc.Body
        doc.Pad1.Length = 0
        self.boss(doc, body, "BossA", 100)
        self.boss(doc, body, "BossB", 400)
        doc.recompute()
        doc.Pad1.Length = self.s(300)
        if self.failBoss:
            doc.BossA.Length = 0
            self.bosses = 1  # BossA passes the block through, BossB is on it
        else:
            self.bosses = 2
        if self.extraRecompute:
            doc.recompute()


class StaleNullSuccessorOutsideSketch(StaleNullSuccessor):
    """The bosses are added while the first Pad is broken; the Pad is fixed and BossA fails."""


class StaleNullSuccessorControl(StaleNullSuccessor):
    """The control: the Pad is fixed and no boss fails."""

    failBoss = False


class OrphanFlip(StaleBase):
    """An orphan pad (BaseFeature None, at x = 2000) between the boss and the cap; the cap's
    BaseFeature is the boss. The ref: a sketch outside the Body on its front face, and the
    volume (the orphan isn't in the Tip's chain)."""

    abstract = True
    orphanFirst = False
    steps = ("breakOrphan", "fixOrphanFailBoss")

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        m.pad(body, base, self.s(300), "Pad1")
        if self.orphanFirst:
            orphan = self.makeOrphan(doc, body)
            boss = self.boss(doc, body, "Boss", 100)
        else:
            boss = self.boss(doc, body, "Boss", 100)
            orphan = self.makeOrphan(doc, body)
        cap = self.boss(doc, body, "Cap", 400)
        orphan.BaseFeature = None
        boss.BaseFeature = doc.Pad1
        cap.BaseFeature = boss
        doc.recompute()
        self.bosses = 2
        sketch = body.newObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(cap, self.names(cap, self.front())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("front", sketch, "AttachmentSupport", self.front,
                 AttachedWithBodyVolume())

    def makeOrphan(self, doc, body):
        sketch = m.sketch(doc, "OrphanSketch",
                          m.rectangle(*self.s(2000, 0, 2100, 100)), body)
        return m.pad(body, sketch, self.s(50), "Orphan")

    def breakOrphan(self, doc):
        doc.Orphan.Length = 0
        self.bosses = 2

    settle = False

    def fixOrphanFailBoss(self, doc):
        doc.Orphan.Length = self.s(50)
        doc.Boss.Length = 0
        self.bosses = 1  # the boss passes the block through, the cap is on it
        if self.settle:
            doc.recompute()


class OrphanFlipBossFirst(OrphanFlip):
    pass


class OrphanFlipOrphanFirst(OrphanFlip):
    orphanFirst = True


class OrphanFlipBossFirstSettled(OrphanFlip):
    """The same with one more recompute in the step: the boss, left touched, runs again."""

    settle = True
