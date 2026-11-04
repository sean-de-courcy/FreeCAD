"""Design s9347 (ops#579, decision 262): the base stop's chain rule, probes A and B of
work/s9347/base-stop-design.md section 4.1.

A failed solid feature is claimed, and its Body continues past it, when its base holds a solid and
is Valid or itself a claimed failure, up its BaseFeature chain.

ChainTwoFailures* (A, T10 of ops#126's rows): Pad2 takes its length from Gauge, a Part box outside
the Body, and Pad3 after it fails on its own in the same edit. Pad2 passes the block through; Pad3's
base is Pad2, a claimed failure, so Pad3 passes the block on and Pad4 and the Body compute on it.
Right: the Body Valid with the block and Pad4. Integration: Pad3 stays Valid on its old shape (the
ops#579 class).

ChainStaleBase* (B): Pad1 and Pad2 fail on their own in one edit. Pad1 has no base, so it isn't
passed through and keeps the block; Pad2's base holds a solid that no recompute made, so Pad2 isn't
claimed either: the Body stops, keeping its last shape (loud). A claim that asked only whether the
base holds a solid would compute Pad3 on the stale block. Integration: Pad3 on nothing.

The model: a 600 x 300 block padded 300 high; bosses 100 x 100 on its top, 50 high. Judged by a
sketch outside the Body attached to the Body's front face (y = 0) and by the Body's volume."""

from PartDesignTests.Scenarios.harness import Attached, Scenario, Y, face
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


class Chain(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "design s9347"
    TIER = "F"
    SIZE = 600
    REFS = ("front",)
    steps = ("fail", "fix")
    bosses = 3  # the bosses the expected Body holds (each 100 x 100 x 50)

    def front(self):
        return face("plane", normal=-Y, through=self.s(300, 0, 150))

    def bodyVolume(self):
        L, W, H, b, h = self.s(600, 300, 300, 100, 50)
        return L * W * H + self.bosses * b * b * h

    def build(self, doc):
        m.box(doc, "Gauge", self.s(10, 10, 50), at=self.s(2000, 0, 0))
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        m.pad(body, base, self.s(300), "Pad1")
        for i, x0 in enumerate((50, 250, 450), start=2):
            sketch = m.sketch(doc, f"S{i}", m.rectangle(*self.s(x0, 100, x0 + 100, 200)), body,
                              z=self.s(300))
            m.pad(body, sketch, self.s(50), f"Pad{i}")
        doc.Pad2.setExpression("Length", "Gauge.Height")
        doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(body, self.names(body, self.front())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("front", sketch, "AttachmentSupport", self.front, AttachedWithBodyVolume())


class ChainTwoFailures(Chain):
    """A: Gauge fails and Pad3 is set to length 0; then both are made good."""

    def fail(self, doc):
        doc.Gauge.Length = 0
        doc.Pad3.Length = 0
        self.bosses = 1  # Pad2 and Pad3 pass the block through, Pad4 is on it

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)
        doc.Pad3.Length = self.s(50)
        self.bosses = 3


class ChainStaleBase(Chain):
    """B: Pad1 and Pad2 are set to length 0; then both are made good."""

    def fail(self, doc):
        doc.Pad1.Length = 0
        doc.Pad2.Length = 0
        self.bosses = 3  # stopped: the Body keeps its last shape

    def fix(self, doc):
        doc.Pad1.Length = self.s(300)
        doc.Pad2.Length = self.s(50)
        self.bosses = 3
