"""Review pr591-r1b (ops#591, decision 268): leads that fail on nothing, aimed at round 1b's
narrowed claim in solidClaimed() (no base at all: getBaseObject(true) null, and isFirstSolid()).

Each case: a 600 x 300 block padded 300 high (Pad1, its length Gauge.Height), a 100 x 100 boss
padded 50 on its top (Pad2), a fillet r 10 on the boss's top back edge (y = 200, z = 350), judged
by its edge and by the volume the full model has after each step (the block, less what the case's
still working cuts remove, plus the boss, less the fillet's (1 - pi/4) r^2 L). Gauge fails (Pad1
fails naming it), then is made good."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Outcome, Scenario, X, Z, edge
from PartDesignTests.Scenarios import models as m

V = App.Vector


class FilletOnFullModel(Outcome):
    """The consumer's volume is the full model's (scenario.fullVolume()) as the step leaves it."""

    def compare(self, scenario, consumer, target, expectation):
        want = scenario.fullVolume()
        got = consumer.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"{consumer.Name} volume {got:.1f}, the full model's is {want:.1f}"
        return True, ""


class Lead591b(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#591"
    FOUND_BY = "review pr591-r1b"
    TIER = "F"
    SIZE = 600
    REFS = ("fillet_edge",)
    steps = ("fail", "fix")
    radius = 10
    cut = 0.0

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


class DatumSketchPocketParked(Lead591b):
    """A 50 x 50 pocket 20 deep at the block's corner (500, 0), its sketch attached to a datum
    plane of the Body at z = 300 (on the XY plane, offset); the pocket is moved to the top of the
    Body (ops#127's park): on nothing it cuts nothing, and the rest computes. Then Gauge fails and
    is made good."""

    steps = ("park", "fail", "fix")
    cut = 50 * 50 * 20

    def build(self, doc):
        body = m.body(doc)
        self.gaugeAndBlock(doc, body)
        doc.recompute()
        plane = body.newObject("PartDesign::Plane", "Datum")
        plane.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), "")]
        plane.MapMode = "FlatFace"
        plane.AttachmentOffset = App.Placement(V(0, 0, self.s(300)), App.Rotation())
        sketch = body.newObject("Sketcher::SketchObject", "PocketSketch")
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
        sketch.addGeometry(m.rectangle(*self.s(500, 0, 550, 50)), False)
        m.pocket(body, sketch, self.s(20), "Pocket")
        doc.recompute()
        self.bossAndFillet(doc, body)

    def park(self, doc):
        doc.Body.reorderObject([doc.Pocket], None, True)
        self.cut = 0.0


class FaceSketchPocketParked(Lead591b):
    """The corner pocket's sketch attached to Pad1's top face (FlatFace); the pocket is moved to
    the top of the Body. Then Gauge fails and is made good."""

    steps = ("park", "fail", "fix")
    cut = 50 * 50 * 20

    def build(self, doc):
        body = m.body(doc)
        pad1 = self.gaugeAndBlock(doc, body)
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "PocketSketch")
        top = self.names(pad1, _topFace(self.s(300)))
        sketch.AttachmentSupport = [(pad1, top)]
        sketch.MapMode = "FlatFace"
        sketch.addGeometry(m.rectangle(*self.s(500, 0, 550, 50)), False)
        m.pocket(body, sketch, self.s(20), "Pocket")
        doc.recompute()
        self.bossAndFillet(doc, body)

    def park(self, doc):
        doc.Body.reorderObject([doc.Pocket], None, True)
        self.cut = 0.0


def _topFace(z):
    from PartDesignTests.Scenarios.harness import face

    return face("plane", normal=Z, through=(0, 0, z))


class WholeShapePatternLead(Lead591b):
    """The Body's first solid feature is a linear pattern in whole-shape mode (no Originals, no
    base: it transforms nothing), then the block, the boss and the fillet."""

    def build(self, doc):
        body = m.body(doc)
        pattern = body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.TransformMode = "Whole shape"
        pattern.Direction = (m.originFeature(body, "X_Axis"), [""])
        pattern.Length = self.s(60)
        pattern.Occurrences = 2
        self.gaugeAndBlock(doc, body)
        self.bossAndFillet(doc, body)


class ParkedPocketInPart(Lead591b):
    """The Body is in an App::Part placed at (1000, 0, 0); the corner pocket is moved to the top
    of the Body, then Gauge fails and is made good."""

    steps = ("park", "fail", "fix")
    cut = 50 * 50 * 20

    def build(self, doc):
        part = doc.addObject("App::Part", "Part")
        part.Placement.Base = V(*self.s(1000, 0, 0))
        body = m.body(doc)
        part.addObject(body)
        self.gaugeAndBlock(doc, body)
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(500, 0, 550, 50)), body,
                          z=self.s(300))
        m.pocket(body, sketch, self.s(20), "Pocket")
        doc.recompute()
        self.bossAndFillet(doc, body)

    def park(self, doc):
        doc.Body.reorderObject([doc.Pocket], None, True)
        self.cut = 0.0


class ParkedMultiTransformLead(Lead591b):
    """A 20 x 20 pocket 20 deep at (20, 20), multi-transformed by one linear step (2 along X, 60);
    the MultiTransform moved to the top of the Body. The pocket itself still cuts."""

    steps = ("park", "fail", "fix")
    cut = 2 * 20 * 20 * 20

    def build(self, doc):
        body = m.body(doc)
        self.gaugeAndBlock(doc, body)
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(20, 20, 40, 40)), body,
                          z=self.s(300))
        pocket = m.pocket(body, sketch, self.s(20), "PocketA")
        doc.recompute()
        multi = body.newObject("PartDesign::MultiTransform", "Multi")
        multi.Originals = [pocket]
        step = body.newObject("PartDesign::LinearPattern", "Step")
        step.Direction = (m.originFeature(body, "X_Axis"), [""])
        step.Length = self.s(60)
        step.Occurrences = 2
        multi.Transformations = [step]
        body.Tip = multi
        doc.recompute()
        self.bossAndFillet(doc, body)

    def park(self, doc):
        doc.Body.reorderObject([doc.Multi], None, True)
        doc.Body.Tip = doc.Fillet
        self.cut = 20 * 20 * 20


class PatternOfSuppressedOriginal(Lead591b):
    """A 20 x 20 pocket 20 deep at (20, 20) on the block's top, patterned 3 times 60 along X (the
    Tip on the pattern), then the boss and the fillet. The pocket is suppressed: it and its
    instances are gone (getOriginals() drops a suppressed original, "as if not there"), so the
    block is whole. Then it is unsuppressed (three cuts again). Not this PR's code: the pattern's
    execute() returns early with no originals and keeps its old shape (debt check)."""

    steps = ("suppress", "unsuppress")
    cut = 3 * 20 * 20 * 20

    def build(self, doc):
        body = m.body(doc)
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        m.pad(body, base, self.s(300), "Pad1")
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(20, 20, 40, 40)), body,
                          z=self.s(300))
        pocket = m.pocket(body, sketch, self.s(20), "PocketA")
        doc.recompute()
        pattern = body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [pocket]
        pattern.Direction = (m.originFeature(body, "X_Axis"), [""])
        pattern.Length = self.s(120)
        pattern.Occurrences = 3
        body.Tip = pattern
        doc.recompute()
        self.bossAndFillet(doc, body)

    def suppress(self, doc):
        doc.PocketA.Suppressed = True
        self.cut = 0.0

    def unsuppress(self, doc):
        doc.PocketA.Suppressed = False
        self.cut = 3 * 20 * 20 * 20
