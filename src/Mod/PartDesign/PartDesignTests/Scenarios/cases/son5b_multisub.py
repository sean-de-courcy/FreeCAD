"""Review pr564son-r5b: the judged flag of a held record is per property, and its take re-measures
every sub of the property, taking each one's world from now, a sub whose target no solve judged.

The model (ThinSlabUnderCap's shape at other sizes): a Body with a block 30 x 16 x 12 (sketch `Base`
on XY, rectangle (0, 0)-(30, 16), padded 12); a slab `Boss` 0.15 high on the block's whole top (at
z = 12); a Pad `Cap` 4 high ((24, 3)-(28, 13) from z = 12) after it. A datum plane `Tangent`
(TangentPlane) holds two references of one property: sub 0, the slab's top face (z = 12.15) as the
Cap carries it (the scored one), and sub 1, the block's bottom corner (30, 16, 0) as the Boss
carries it (the Boss's own batch judges it, at its place in both worlds, and holds its record while
the Boss is touched: the property is flagged "a solve held it").

`sup` suppresses the Boss: the slab's top face is gone from the Cap's shape (right: BROKEN); the
block's top 0.15 below has the same outline (tier 3's C2 pick, warned and wrong, when the switch
isn't seen). Sub 0's target is the Cap, which no solve judged before the take.
Expected results are defined by the geometry above; no file is used."""

import FreeCAD as App

from PartDesignTests.Scenarios import harness as H
from PartDesignTests.Scenarios.harness import BROKEN, Scenario, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
Z = V(0, 0, 1)


class MultiSubBase(Scenario):
    abstract = True
    area = "failure pass-through"
    CLASSES = ("D",)
    AXES = ("M1", "E4")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564son-r5b"
    TIER = "F"
    REFS = ("slab_top_cap",)
    steps = ("sup",)
    single = False

    def slabTop(self):
        if self.stepName == "sup":
            return BROKEN
        return face("plane", normal=Z, contains=(5, 8, 12.15))

    def corner(self):
        return vertex((30, 16, 0))

    def build(self, doc):
        self.body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, 30, 16), self.body)
        self.block = m.pad(self.body, base, 12, "Block")
        self.block.Refine = False
        bossSketch = m.sketch(doc, "BossSketch", m.rectangle(0, 0, 30, 16), self.body, z=12)
        self.boss = m.pad(self.body, bossSketch, 0.15, "Boss")
        self.boss.Refine = False
        capSketch = m.sketch(doc, "CapSketch", m.rectangle(24, 3, 28, 13), self.body, z=12)
        self.cap = m.pad(self.body, capSketch, 4, "Cap")
        self.cap.Refine = False
        doc.recompute()
        plane = self.body.newObject("PartDesign::Plane", "Tangent")
        top = self.names(self.cap, face("plane", normal=Z, contains=(5, 8, 12.15)))
        if self.single:
            plane.AttachmentSupport = [(self.cap, top)]
            plane.MapMode = "FlatFace"
        else:
            plane.AttachmentSupport = [
                (self.cap, top),
                (self.boss, self.names(self.boss, self.corner())),
            ]
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


class MultiSubControl(MultiSubBase):
    """The Boss suppressed (a setter), then the document's recompute. Right: BROKEN."""

    def sup(self, doc):
        self.boss.Suppressed = True


class MultiSubAlone(MultiSubBase):
    """The Boss suppressed and recomputed alone (obj.recompute()), then the document's recompute."""

    def sup(self, doc):
        self.boss.Suppressed = True
        self.boss.recompute()


class MultiSubAloneBack(MultiSubAlone):
    """As MultiSubAlone, then the Boss back: the slab's top again."""

    steps = ("sup", "uns")

    def uns(self, doc):
        self.boss.Suppressed = False


class MultiSubSingle(MultiSubAlone):
    """As MultiSubAlone with the datum on the slab's top through the Cap alone (one sub)."""

    single = True


class MultiSubPartialThenBlock(MultiSubBase):
    """The Boss suppressed and the document recomputed for the Boss only (the Cap is left touched,
    the take holds the record again), then the Block recomputed alone, then the document."""

    def sup(self, doc):
        self.boss.Suppressed = True
        doc.recompute([self.boss])
        self.block.recompute()


class MultiSubAloneBlockFirst(MultiSubBase):
    """The Boss suppressed and recomputed alone after the Block's own recompute alone."""

    def sup(self, doc):
        self.block.recompute()
        self.boss.Suppressed = True
        self.boss.recompute()
