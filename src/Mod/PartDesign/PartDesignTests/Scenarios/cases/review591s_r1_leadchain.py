"""Review pr591s-r1 (ops#591, decision 262 (1)): a lead that is claimed with the empty pass-through
(a subtractive feature, a dress-up or a pattern on no base) stays red while the Body computes below
it. Every reference in the Body now has the claimed lead at the foot of its base chain (the
shape-input chain the reference solver reads, `shapeInputChain()`: the lead is in error and
`failurePassedThrough`). Does that hold the Body's references back or turn them wrong?

Each case: a 600 x 300 block padded 300 high (Pad1), a lead above it (a subtractive box, or a
pocket / fillet / pattern parked there by a reorder, ops#127), a sketch attached to Pad1's top
face (z = 300). The edit makes Pad1 150 higher; the sketch must follow the top face to z = 450."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, Z, face
from PartDesignTests.Scenarios import models as m


class LeadChain(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#591"
    FOUND_BY = "review pr591s-r1"
    TIER = "F"
    SIZE = 600
    REFS = ("sketch_top",)
    steps = ("taller", "back")
    height = 300

    def top(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def leading(self, doc, body):
        """Builds Pad1 and the lead above it; returns Pad1."""
        raise NotImplementedError

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        pad = self.leading(doc, body)
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(pad, self.names(pad, self.top())[0])]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        self.ref("sketch_top", sketch, "AttachmentSupport", self.top, Attached())

    def taller(self, doc):
        doc.Pad1.Length = self.s(450)
        self.height = 450

    def back(self, doc):
        doc.Pad1.Length = self.s(300)
        self.height = 300

    def block(self, doc, body):
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        return m.pad(body, base, self.s(300), "Pad1")


class LeadSubBoxTaller(LeadChain):
    """The lead is a subtractive box (nothing to cut: red from the start)."""

    def leading(self, doc, body):
        box = body.newObject("PartDesign::SubtractiveBox", "SubBox")
        box.Length, box.Width, box.Height = self.s(10, 10, 10)
        return self.block(doc, body)


class ParkedPocketTaller(LeadChain):
    """A pocket cut in the block, parked above Pad1 by a reorder."""

    def leading(self, doc, body):
        pad = self.block(doc, body)
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(500, 0, 550, 50)), body,
                          z=self.s(300))
        pocket = m.pocket(body, sketch, self.s(20), "Pocket")
        doc.recompute()
        body.reorderObject([pocket], None, True)
        return pad


class ParkedFilletTaller(LeadChain):
    """A fillet on the block's front top edge, parked above Pad1 by a reorder."""

    def leading(self, doc, body):
        pad = self.block(doc, body)
        doc.recompute()
        edge = Part.Edge  # noqa: F841 (the edge is found by position below)
        shape = pad.Shape
        index = [i + 1 for i, e in enumerate(shape.Edges)
                 if abs(e.CenterOfMass.z - self.s(300)) < 1e-6 and abs(e.CenterOfMass.y) < 1e-6][0]
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, [f"Edge{index}"])
        fillet.Radius = self.s(10)
        doc.recompute()
        body.reorderObject([fillet], None, True)
        return pad


class ParkedPatternTaller(LeadChain):
    """A linear pattern of a pocket, parked above Pad1 by a reorder (the pocket stays below)."""

    def leading(self, doc, body):
        pad = self.block(doc, body)
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(10, 10, 30, 30)), body,
                          z=self.s(300))
        pocket = m.pocket(body, sketch, self.s(20), "Pocket")
        pattern = body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [pocket]
        pattern.Direction = (sketch, ["H_Axis"])
        pattern.Length = self.s(100)
        pattern.Occurrences = 3
        doc.recompute()
        body.reorderObject([pattern], None, True)
        return pad


class NoLeadTaller(LeadChain):
    """The control: no lead."""

    def leading(self, doc, body):
        return self.block(doc, body)


class ParkedPocketTallerSuppressed(ParkedPocketTaller):
    """The parked pocket is suppressed by the user (a Valid lead that passes the empty shape): the
    chain has no failure."""

    def leading(self, doc, body):
        pad = super().leading(doc, body)
        doc.Pocket.Suppressed = True
        return pad
