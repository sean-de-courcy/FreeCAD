"""Review pr579-r4g (ops#579 round 4 fix 2, decision 255 (1) literal): baseInError() walks the
Body's solid features and stops at the first whose shape is not null. A lead that is Valid, not
null, and holds no solid (an empty compound, a face) stops the walk there, so a failure of the
first real Pad after it is claimed; but its pass-through is getBaseTopoShape(true), which nulls a
base without a solid (Feature.cpp), so the pass-through is the empty shape, and the boss after it
computes on nothing, Valid, and so does the Body: review pr579-r4f T-R4F-1 again, through a
solidless lead instead of a null one.

The leads: a Boolean Common of two tool Bodies that don't meet (its result an empty compound,
Valid: getSolid() returns a shape without a solid as it is); the Body's BaseFeature a Part::Plane
(its FeatureBase holds a face); the Body's BaseFeature a Part::Feature holding an empty compound
(FeatureBase checks isNull() only).

Each case: a 600 x 300 block padded 300 high (Pad1, its length an expression on Gauge, a Part box
outside the Body), a 100 x 100 boss padded 50 on its top (Pad2), a fillet r 10 on the boss's top
back edge (y = 200, z = 350), judged by its edge and by the full model's volume (the block, the
boss, less the fillet's (1 - pi/4) r^2 L). Gauge fails (length 0), then is made good."""

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


class SolidlessLead(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r4g"
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

    def makeBody(self, doc):
        """The Body and its lead, before Pad1."""
        raise NotImplementedError

    def build(self, doc):
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        body = self.makeBody(doc)
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

    def fail(self, doc):
        doc.Gauge.Length = 0

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)


def toolBody(doc, name, x):
    """A 50 x 50 x 50 block at (x, 0, 0), far from the model."""
    body = doc.addObject("PartDesign::Body", name)
    sketch = m.sketch(doc, name + "Sketch", m.rectangle(x, 0, x + 50, 50), body)
    m.pad(body, sketch, 50, name + "Pad")
    return body


class DisjointCommonLeadExprOnFailedGauge(SolidlessLead):
    """The lead is a Boolean Common of two tool Bodies 1000 apart (its tools moved apart, or the
    user's intersection went empty): Valid on an empty compound, not null."""

    def makeBody(self, doc):
        t1 = toolBody(doc, "ToolA", self.s(3000))
        t2 = toolBody(doc, "ToolB", self.s(4000))
        doc.recompute()
        body = m.body(doc)
        lead = body.newObject("PartDesign::Boolean", "Lead")
        lead.Type = "Common"
        lead.addObjects([t1, t2])
        return body


class FaceBaseFeatureExprOnFailedGauge(SolidlessLead):
    """The Body's BaseFeature is a 50 x 50 Part::Plane far from the model: its FeatureBase is
    Valid on a face."""

    def makeBody(self, doc):
        plane = doc.addObject("Part::Plane", "Plane")
        plane.Length, plane.Width = self.s(50, 50)
        plane.Placement.Base = App.Vector(*self.s(3000, 0, 0))
        body = m.body(doc)
        body.BaseFeature = plane
        return body


class EmptyCompoundBaseFeatureExprOnFailedGauge(SolidlessLead):
    """The Body's BaseFeature is a Part::Feature holding an empty compound: its FeatureBase is
    Valid (it checks for a null shape only)."""

    def makeBody(self, doc):
        empty = doc.addObject("Part::Feature", "Empty")
        empty.Shape = Part.Compound([])
        body = m.body(doc)
        body.BaseFeature = empty
        return body


class SolidlessLeadControl(DisjointCommonLeadExprOnFailedGauge):
    """The control: Gauge gets taller and back (no failure)."""

    def fail(self, doc):
        doc.Gauge.Length = self.s(20)


class SameEdit(SolidlessLead):
    """The lead is a 50 x 50 pad 100 high at the origin, inside the block (the model's volume is
    the same with it or without it). In one edit the lead goes (suppressed, or deleted) and Gauge
    fails: the walk reads the lead after it recomputed (it is Pad1's base). The Body stops (loud)
    or keeps the full model; a boss alone is wrong."""

    abstract = True
    AXES = ("M1", "E4", "E5", "X4:600")

    def makeBody(self, doc):
        body = m.body(doc)
        sketch = m.sketch(doc, "LeadSketch", m.rectangle(0, 0, *self.s(50, 50)), body)
        m.pad(body, sketch, self.s(100), "Lead")
        return body


class SuppressLeadAndFailGaugeInOneEdit(SameEdit):
    def fail(self, doc):
        doc.Lead.Suppressed = True
        doc.Gauge.Length = 0


class DeleteLeadAndFailGaugeInOneEdit(SameEdit):
    def fail(self, doc):
        body = doc.Body
        lead = doc.Lead
        body.removeObject(lead)
        doc.removeObject(lead.Name)
        doc.removeObject("LeadSketch")
        doc.Gauge.Length = 0
