"""Review pr591s-r1b (ops#591, decision 268): leads claimed as "no base at all" (solidClaimed()'s
`!getBaseObject(true) && isFirstSolid`), aimed at a base that exists but isn't a Part feature.

Each case: a 600 x 300 x 300 block (Pad1, its Length from Gauge), a 100 x 100 boss padded 50 on its
top (Pad2), a fillet r 10 on the boss's top back edge, judged by its edge and the full model."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Outcome, Scenario, X, Z, edge
from PartDesignTests.Scenarios import models as m


class FilletOnFullModel(Outcome):
    def compare(self, scenario, consumer, target, expectation):
        want = scenario.fullVolume()
        got = consumer.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"{consumer.Name} volume {got:.1f}, the full model's is {want:.1f}"
        return True, ""


class Case591(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#591"
    FOUND_BY = "review pr591s-r1b"
    TIER = "F"
    SIZE = 600
    REFS = ("fillet_edge",)
    radius = 10
    cut = 0.0

    def topBackEdge(self):
        return edge("line", direction=X, through=self.s(300, 200, 350))

    def fullVolume(self):
        L, W, H, b, h, r = self.s(600, 300, 300, 100, 50, self.radius)
        return L * W * H - self.cut * self.scale**3 + b * b * h - (1 - math.pi / 4) * r * r * b

    def block(self, doc, body):
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        pad1 = m.pad(body, base, self.s(300), "Pad1")
        pad1.setExpression("Length", "Gauge.Height")
        return pad1

    def bossAndFillet(self, doc, body, expect=None):
        sketch = m.sketch(doc, "BossSketch", m.rectangle(*self.s(250, 100, 350, 200)), body,
                          z=self.s(300))
        boss = m.pad(body, sketch, self.s(50), "Pad2")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (boss, self.names(boss, self.topBackEdge()))
        fillet.Radius = self.s(self.radius)
        doc.recompute()
        self.ref("fillet_edge", fillet, "Base", expect or self.topBackEdge, FilletOnFullModel())


class FilletLeadRelinkedToALink(Case591):
    """The Body's first solid feature is a fillet r 10 on the vertical x = y = 0 edge of Stock, an
    outside 600 x 300 x 300 box (Base set from Python: its BaseFeature stays None). In one edit
    its Base is pointed at the same edge through an App::Link to Stock, a base that exists but
    isn't a Part object: the fillet fails ("Linked object is not a Part object") and has a base,
    so nothing above it is right to compute: the Body stops (decision 268: every fallback base
    with BaseFeature null is unclaimed). Then it is pointed back."""

    steps = ("relink", "restore")
    linked = False

    def expectation(self):
        return BROKEN if self.linked else self.topBackEdge()

    def fullVolume(self):
        L, W, H, b, h, r = self.s(600, 300, 300, 100, 50, self.radius)
        corner = (1 - math.pi / 4) * r * r * H
        return L * W * H - corner + b * b * h - (1 - math.pi / 4) * r * r * b

    def build(self, doc):
        stock = m.box(doc, "Stock", self.s(600, 300, 300))
        link = doc.addObject("App::Link", "StockLink")
        link.LinkedObject = stock
        doc.recompute()
        body = m.body(doc)
        lead = body.newObject("PartDesign::Fillet", "Lead")
        lead.Base = (stock, self.names(stock, edge("line", direction=Z,
                                                    through=self.s(0, 0, 150))))
        lead.Radius = self.s(self.radius)
        doc.recompute()
        self.bossAndFillet(doc, body, self.expectation)

    def relink(self, doc):
        lead = doc.Lead
        lead.Base = (doc.StockLink, list(lead.Base[1]))
        self.linked = True

    def restore(self, doc):
        lead = doc.Lead
        lead.Base = (doc.Stock, list(lead.Base[1]))
        self.linked = False


class LeadPocketSketchOnADatumPlane(Case591):
    """A 50 x 50 pocket 20 deep at the block's corner, moved to the top before the boss and the
    fillet are made (ops#127's park: its sketch is placed, not attached), so it is the Body's first solid feature and, with no base,
    is claimed. Then its sketch is attached to a datum plane of the Body: ProfileBased::
    getBaseObject() takes the plane (a Part::Feature) as the pocket's implicit base. Gauge then
    fails. The pocket's base is a plane, with no solid: the pass-through is empty, the claim
    refuses it (a base, not none) and the Body stops, where the parked pocket without the datum
    plane is claimed (decision 262 (1)). Right -> loud against 96a25bb6a8; integration stops
    too."""

    steps = ("attach", "fail", "fix")

    def build(self, doc):
        body = m.body(doc)
        self.block(doc, body)
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(*self.s(500, 0, 550, 50)), body,
                          z=self.s(300))
        pocket = m.pocket(body, sketch, self.s(20), "Pocket")
        doc.recompute()
        body.reorderObject([pocket], None, True)
        doc.recompute()
        self.bossAndFillet(doc, body)

    def attach(self, doc):
        plane = doc.Body.newObject("PartDesign::Plane", "Datum")
        plane.AttachmentSupport = [(m.originFeature(doc.Body, "XY_Plane"), [""])]
        plane.MapMode = "FlatFace"
        plane.AttachmentOffset = App.Placement(App.Vector(0, 0, self.s(300)), App.Rotation())
        doc.recompute()
        doc.PocketSketch.AttachmentSupport = [(plane, [""])]
        doc.PocketSketch.MapMode = "FlatFace"

    def fail(self, doc):
        doc.Gauge.Length = 0

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)


class PatternLeadOriginalIsALink(Case591):
    """A linear pattern of Pad1 moved to the top of the Body (its Originals parked: claimed, the
    Body computes below it). In one edit its Originals (set from Python) take an App::Link to
    Stock, an outside 600 x 300 x 300 box: the pattern's base resolves to nothing, but it names one
    (design se47b's (N), the pattern form of FilletLeadRelinkedToALink), so the Body stops. Then
    they are emptied. A pattern given only the Link from the start isn't a solid feature (it isn't
    first: the Body puts the next solid before it), so the lead is made by the park."""

    FOUND_BY = "design se47b"
    steps = ("link", "empty")
    linked = False

    def expectation(self):
        return BROKEN if self.linked else self.topBackEdge()

    def build(self, doc):
        stock = m.box(doc, "Stock", self.s(600, 300, 300), at=self.s(0, 1000, 0))
        link = doc.addObject("App::Link", "StockLink")
        link.LinkedObject = stock
        doc.recompute()
        body = m.body(doc)
        pad1 = self.block(doc, body)
        doc.recompute()
        lead = body.newObject("PartDesign::LinearPattern", "Lead")
        lead.Direction = (m.originFeature(body, "X_Axis"), [""])
        lead.Length = self.s(700)
        lead.Occurrences = 2
        lead.Originals = [pad1]
        doc.recompute()
        body.reorderObject([lead], None, True)
        doc.recompute()
        self.bossAndFillet(doc, body, self.expectation)

    def link(self, doc):
        doc.Lead.Originals = [doc.StockLink]
        self.linked = True

    def empty(self, doc):
        doc.Lead.Originals = []
        self.linked = False
