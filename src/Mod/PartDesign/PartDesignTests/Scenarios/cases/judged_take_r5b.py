# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr564opus-r5b (ops#564 round 5b): a take of a record a solve held (`_TakingJudged`)
re-measures every sub of the property, and takes each one's world from now, also a sub whose
target no solve judged.

The model (as failure_pass_through.ThinSlabUnderCap): a Body with a block 20 x 10 x 10 (sketch
`Base` on XY, rectangle (0, 0)-(20, 10), padded 10); a slab `Boss` 0.1 high on the block's whole
top ((0, 0)-(20, 10) at z = 10); a Pad `Cap` 3 high ((16, 2)-(19, 8) from z = 10) after it.
A datum plane `Tangent`, mode TangentPlane, on two references of one property: the slab's top
face (z = 10.1) as the Cap carries it (sub 0, the scored one), and the block's bottom corner
(20, 10, 0) as the Boss carries it (sub 1: the Boss's batch judges it, at its place in both
worlds, and holds the record while the Boss is touched).

`sup` suppresses the Boss: the slab's top face is gone from the Cap's shape (right: BROKEN, as
ThinSlabUnderCap's edit and ThinSlabSuppressed); the block's top 0.1 below has the same outline
(tier 3's C2 pick, warned and wrong, if the switch isn't seen).
- `JudgedTakeSlabAlone`: `sup` is the setter and `Boss.recompute()` (obj.recompute(), a task
  dialog's preview), then the harness's recompute.
- `JudgedTakeSlabControl`: the setter alone, then the recompute.
- `JudgedTakeSlabSingle`: as JudgedTakeSlabAlone with a datum plane on the slab's top through the
  Cap alone (FlatFace, one sub).
Expected results are defined by the geometry above; no file is used.
"""

import FreeCAD as App

from PartDesignTests.Scenarios import harness as H
from PartDesignTests.Scenarios.harness import BROKEN, Scenario, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
Z = V(0, 0, 1)


class JudgedTakeBase(Scenario):
    abstract = True
    area = "failure pass-through"
    CLASSES = ("D",)
    AXES = ("M1", "E4")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r5b"
    TIER = "F"
    REFS = ("slab_top_cap",)
    steps = ("sup",)
    single = False

    def slabTop(self):
        if self.stepName in ("sup",):
            return BROKEN
        return face("plane", normal=Z, contains=(10, 5, 10.1))

    def corner(self):
        return vertex((20, 10, 0))

    def build(self, doc):
        self.body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), self.body)
        self.block = m.pad(self.body, base, 10, "Block")
        self.block.Refine = False
        bossSketch = m.sketch(doc, "BossSketch", m.rectangle(0, 0, 20, 10), self.body, z=10)
        self.boss = m.pad(self.body, bossSketch, 0.1, "Boss")
        self.boss.Refine = False
        capSketch = m.sketch(doc, "CapSketch", m.rectangle(16, 2, 19, 8), self.body, z=10)
        self.cap = m.pad(self.body, capSketch, 3, "Cap")
        self.cap.Refine = False
        doc.recompute()
        plane = self.body.newObject("PartDesign::Plane", "Tangent")
        top = self.names(self.cap, face("plane", normal=Z, contains=(10, 5, 10.1)))
        if self.single:
            plane.AttachmentSupport = [(self.cap, top)]
            plane.MapMode = "FlatFace"
        else:
            plane.AttachmentSupport = [(self.cap, top), (self.boss, self.names(self.boss, self.corner()))]
            plane.MapMode = "TangentPlane"
        doc.recompute()
        self.ref("slab_top_cap", plane, "AttachmentSupport", self.slabTop)

    def judge(self, ref, step):
        # The harness scores a one-object list: the Cap's sub only
        original = H.storedLinks

        def capOnly(obj, prop):
            value = getattr(obj, prop)
            if isinstance(value, list) and len({o.Name for o, _ in value}) > 1:
                value = [(o, s) for o, s in value if o.Name == "Cap"]
                subs = []
                for _, s in value:
                    subs.extend([s] if isinstance(s, str) else s)
                return value[0][0], subs
            return original(obj, prop)

        H.storedLinks = capOnly
        try:
            return super().judge(ref, step)
        finally:
            H.storedLinks = original


class JudgedTakeSlabAlone(JudgedTakeBase):
    """The Boss suppressed and recomputed alone, then the document."""

    def sup(self, doc):
        self.boss.Suppressed = True
        self.boss.recompute()


class JudgedTakeSlabControl(JudgedTakeBase):
    """The Boss suppressed, then the document recomputed."""

    def sup(self, doc):
        self.boss.Suppressed = True


class JudgedTakeSlabSingle(JudgedTakeSlabAlone):
    """As JudgedTakeSlabAlone, the datum on the Cap's slab top alone."""

    single = True


class JudgedTakeSlabPartial(JudgedTakeBase):
    """The Boss suppressed and the document recomputed for the Boss only (its dependencies), then
    the whole document: the Cap is left touched by the first."""

    def sup(self, doc):
        self.boss.Suppressed = True
        doc.recompute([self.boss])


class JudgedTakeSlabAloneBack(JudgedTakeSlabAlone):
    """As JudgedTakeSlabAlone, then the Boss unsuppressed: the slab's top again."""

    steps = ("sup", "uns")

    def uns(self, doc):
        self.boss.Suppressed = False


class JudgedTakeSlabPartialThenBlock(JudgedTakeBase):
    """As JudgedTakeSlabPartial (the take holds the record again, the Cap touched), then the Block
    recomputed alone (in every sub's closure), then the document."""

    def sup(self, doc):
        self.boss.Suppressed = True
        doc.recompute([self.boss])
        self.block.recompute()
