"""Review pr579-r5b (ops#579 round 5's fix, 6b0a752f3f): a transform links its base early only as
its Body's last solid feature; any other waits for execute(), as upstream.

The model: a 600 x 300 x 300 block centred on the origin, a 100 x 100 x 50 boss A on its top at
x -250..-150, y -50..50, and a 100 x 80 x 20 cap at x -50..50, y 60..140 after it. Judged by a sketch
outside the Body on the block's front face (y = -150) and the Body's volume (the Body's Tip is the
last solid).

TwoTransformsMidBody: from Python, the Tip on boss A, a LinearPattern of A (along Y, 100) and a
Mirrored of A (YZ plane) are added before the cap, one after the other, and the Tip goes back to the
cap; one recompute. Both transforms wait for execute(): the pattern links (A, and the mirror after
it onto itself), the mirror's base is then set, so it doesn't link and the cap stays on A.

MidBodyNewBase: the Tip on A, a new boss B (x 150..250) and a whole-shape Mirrored are added before
the cap, the Tip back to the cap; one recompute (the transform and its base made in one recompute,
the transform not last).

LastThenSolidBefore: the Mirrored of A is added last (its base linked early), then, the Tip still on
A, boss B is added (before the Mirrored); one recompute.

ConvertWithCapThenGrow: PartDesign_MultiTransform on a Mirrored of A that has the cap after it (the
command's steps, as review579r5.ConvertToMultiTransform), then A is made 80 high."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Attached, Scenario, Y, face
from PartDesignTests.Scenarios import models as m


class AttachedWithBodyVolume(Attached):
    """Attached, and the Body's volume is the scenario's expected one. A Body member in error or
    left touched is loud: broken."""

    def check(self, scenario, consumer, target, expectation):
        body = scenario.doc.Body
        bad = [o.Name for o in body.Group + [body] if "Touched" in o.State or (
            o.isDerivedFrom("PartDesign::Feature") and not o.isValid())]
        if bad:
            return "broken", f"in error or touched after the recompute: {bad}"
        return super().check(scenario, consumer, target, expectation)

    def compare(self, scenario, consumer, target, expectation):
        ok, why = super().compare(scenario, consumer, target, expectation)
        if not ok:
            return ok, why
        want = scenario.bodyVolume()
        got = scenario.doc.Body.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"Body volume {got:.1f}, expected {want:.1f}"
        return True, ""


class R5b(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#590"
    FOUND_BY = "review pr579-r5b"
    TIER = "F"
    SIZE = 600
    REFS = ("front",)
    bosses = 1
    bossHeight = 50
    capped = True

    def front(self):
        return face("plane", normal=-Y, through=self.s(0, -150, 150))

    def bodyVolume(self):
        L, W, H, b, h, cw, ch = self.s(600, 300, 300, 100, self.bossHeight, 80, 20)
        return L * W * H + self.bosses * b * b * h + (b * cw * ch if self.capped else 0)

    def bossAt(self, doc, body, name, x0):
        sk = m.sketch(doc, name + "S", m.rectangle(*self.s(x0, -50, x0 + 100, 50)), body,
                      z=self.s(300))
        return m.pad(body, sk, self.s(50), name)

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(*self.s(-300, -150, 300, 150)), body)
        m.pad(body, base, self.s(300), "Pad1")
        self.bossAt(doc, body, "BossA", -250)
        self.prepare(doc, body)
        doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(body, self.names(body, self.front())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("front", sketch, "AttachmentSupport", self.front, AttachedWithBodyVolume())

    def prepare(self, doc, body):
        capSketch = m.sketch(doc, "CapS", m.rectangle(*self.s(-50, 60, 50, 140)), body,
                             z=self.s(300))
        m.pad(body, capSketch, self.s(20), "Cap")


class TwoTransformsMidBody(R5b):
    """Both transforms of A before the cap, from Python, one recompute."""

    def edit(self, doc):
        body = doc.Body
        body.Tip = doc.BossA
        lp = body.newObject("PartDesign::LinearPattern", "LP")
        lp.Originals = [doc.BossA]
        lp.Direction = (m.originFeature(body, "Y_Axis"), [""])
        lp.Length = self.s(100)
        lp.Occurrences = 2
        body.Tip = lp
        mir = body.newObject("PartDesign::Mirrored", "Mirrored")
        mir.Originals = [doc.BossA]
        mir.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        body.Tip = mir
        body.Tip = doc.Cap
        self.bosses = 3  # A, its copy at y 50..150, its mirror at x 150..250


class MidBodyNewBase(R5b):
    """A new boss B and a whole-shape Mirrored before the cap, one recompute."""

    def edit(self, doc):
        body = doc.Body
        body.Tip = doc.BossA
        self.bossAt(doc, body, "BossB", 50)
        mir = body.newObject("PartDesign::Mirrored", "Mirrored")
        mir.TransformMode = "Whole shape"
        mir.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        body.Tip = mir
        body.Tip = doc.Cap
        self.bosses = 4  # A, B (x 50..150) and their mirrors (x 150..250, x -150..-50)


class LastThenSolidBefore(R5b):
    """A Mirrored of A added last (linked early), then boss B added before it, one recompute."""

    capped = False

    def prepare(self, doc, body):
        pass

    def edit(self, doc):
        body = doc.Body
        mir = body.newObject("PartDesign::Mirrored", "Mirrored")
        mir.Originals = [doc.BossA]
        mir.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        # the Tip is still on A (a new transform isn't a solid when it is added)
        self.bossAt(doc, body, "BossB", 50)
        body.Tip = mir
        self.bosses = 3  # A, B, A's mirror


class ConvertWithCapThenGrow(R5b):
    """A Mirrored of A with the cap after it, converted to a MultiTransform (the command's steps),
    then A made 80 high."""

    steps = ("convert", "grow")

    def prepare(self, doc, body):
        doc.recompute()
        mir = body.newObject("PartDesign::Mirrored", "Mirrored")
        mir.Originals = [doc.BossA]
        mir.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        body.Tip = mir
        doc.recompute()
        super().prepare(doc, body)
        self.bosses = 2

    def convert(self, doc):
        body, trFeat = doc.Body, doc.Mirrored
        oldTip = body.Tip
        body.Tip = doc.BossA  # PartDesign_MoveTip on the previous solid
        feat = body.newObject("PartDesign::MultiTransform", "MultiTransform")
        feat.Originals = trFeat.Originals
        feat.TransformMode = trFeat.TransformMode
        feat.BaseFeature = trFeat.BaseFeature
        feat.Transformations = [trFeat]
        trFeat.Originals = []
        doc.recompute()  # finishFeature: updateActive
        body.Tip = oldTip  # PartDesign_MoveTip back to the cap

    def grow(self, doc):
        doc.BossA.Length = self.s(80)
        self.bossHeight = 80


class ReorderPatternToTop(R5b):
    """ops#127's reorder: a LinearPattern of A (along Y, 100) between A and the cap is moved above
    the block (its Originals parked, a loud failure), then back: after A (mid-Body) or after the
    cap (last). Its BaseFeature is null while it is the first solid."""

    abstract = True
    steps = ("up", "back")
    toEnd = False

    def prepare(self, doc, body):
        doc.recompute()
        lp = body.newObject("PartDesign::LinearPattern", "LP")
        lp.Originals = [doc.BossA]
        lp.Direction = (m.originFeature(body, "Y_Axis"), [""])
        lp.Length = self.s(100)
        lp.Occurrences = 2
        body.Tip = lp
        doc.recompute()
        super().prepare(doc, body)
        self.bosses = 2

    def up(self, doc):
        doc.Body.reorderObject([doc.LP], doc.Pad1, False)

    def back(self, doc):
        body = doc.Body
        if self.toEnd:
            body.reorderObject([doc.LP], doc.Cap, True)
        else:
            body.reorderObject([doc.LP], doc.BossA, True)
        body.Tip = body.Group[-1] if body.Group[-1].isDerivedFrom("PartDesign::Feature") else body.Tip


class ReorderPatternToTopBackMid(ReorderPatternToTop):
    pass


class ReorderPatternToTopBackEnd(ReorderPatternToTop):
    toEnd = True
