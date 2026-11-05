"""Design s7fc8 (ops#596, decisions 275 (2), 276, 281; notes/park-design.md): the additive park. A
boss whose sketch sits on Pad1's top face is moved above Pad1 (W16): the reorder sets the sketch's
attachment aside (ops#127), the boss fails and passes the empty shape on, and the Body computes below
it, as Onshape fails only the moved feature. References below the parked boss keep following edits
(design 5 (R), decision 275 (4)).

Each case: a 600 x 300 block padded 300 high (Pad1), a 100 x 100 boss padded 50 at (250, 100) to
(350, 200) whose sketch is attached to Pad1's top face (Pad2), and a sketch attached to Pad1's top
face (OnTop), taken before the park. The edit makes Pad1 150 higher; OnTop must follow to z = 450."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Filleted,
    Reopens,
    Scenario,
    X,
    Z,
    edge,
    face,
)
from PartDesignTests.Scenarios import models as m


class Park596(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#596"
    FOUND_BY = "design s7fc8"
    TIER = "F"
    SIZE = 600
    REFS = ("sketch_top",)
    steps = ("taller", "back")
    height = 300
    park = True
    onDatum = False

    def top(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def block(self, doc, body):
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        return m.pad(body, base, self.s(300), "Pad1")

    def bossOn(self, doc, body, pad):
        """Pad2: its sketch on Pad1's top face, or on a datum plane there."""
        doc.recompute()
        support = (pad, self.names(pad, self.top())[0])
        if self.onDatum:
            plane = body.newObject("PartDesign::Plane", "BossPlane")
            plane.AttachmentSupport = [support]
            plane.MapMode = "FlatFace"
            doc.recompute()
            support = (plane, "")
        sketch = body.newObject("Sketcher::SketchObject", "BossSketch")
        sketch.AttachmentSupport = [support]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        local = sketch.getGlobalPlacement().inverse()
        a, b = (local.multVec(App.Vector(*self.s(x, y, 300))) for x, y in ((250, 100), (350, 200)))
        sketch.addGeometry(
            m.rectangle(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y)), False
        )
        return m.pad(body, sketch, self.s(50), "Pad2")

    def extra(self, doc, body):
        """What the case adds after the boss and OnTop, before the park."""

    def parkBoss(self, doc):
        doc.Body.reorderObject([doc.Pad2], None, True)

    def build(self, doc):
        body = m.body(doc)
        pad = self.block(doc, body)
        self.bossOn(doc, body, pad)
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(pad, self.names(pad, self.top())[0])]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        self.extra(doc, body)
        doc.recompute()
        self.addRefs(doc)
        if self.park:
            self.parkBoss(doc)

    def addRefs(self, doc):
        self.ref("sketch_top", doc.OnTop, "AttachmentSupport", self.top, Attached())

    def taller(self, doc):
        doc.Pad1.Length = self.s(450)
        self.height = 450

    def back(self, doc):
        doc.Pad1.Length = self.s(300)
        self.height = 300


class ParkedPadControl(Park596):
    """The control: the boss stays where it was."""

    park = False


class ParkedPadTaller(Park596):
    """The boss parked above Pad1; Pad1 made taller and back."""


class ParkedPadOnDatum(Park596):
    """The boss's sketch on a datum plane on Pad1's top face: the plane moves with the boss and its
    attachment is set aside (design 5 (P) through the sketch and the plane)."""

    onDatum = True


class ParkedPadReopened(Reopens, Park596):
    """The boss parked, the document saved and reopened, then Pad1 made taller and back."""

    steps = ("reopen", "taller", "back")


class ParkedPadUndo(Park596):
    """The park in a transaction; undone (the boss on Pad1 again), redone, then Pad1 taller and
    back."""

    steps = ("undoPark", "redoPark", "taller", "back")

    def parkBoss(self, doc):
        doc.UndoMode = 1
        doc.openTransaction("Move")
        super().parkBoss(doc)
        doc.recompute()
        doc.commitTransaction()

    def undoPark(self, doc):
        doc.undo()

    def redoPark(self, doc):
        doc.redo()


class ParkedPadThenFail(Park596):
    """The boss parked; then Pad1 fails through Gauge, an outside box its Length reads: Pad1 isn't
    parked and passes the empty shape, so the Body stops (decision 281, ops#579 find 3); Gauge made
    good."""

    steps = ("fail", "fix")

    def block(self, doc, body):
        m.box(doc, "Gauge", self.s(10, 10, 300), at=self.s(2000, 0, 0))
        pad = super().block(doc, body)
        pad.setExpression("Length", "Gauge.Height")
        return pad

    def fail(self, doc):
        doc.Gauge.Length = 0

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)


class ParkedPadFilletBelow(Park596):
    """A fillet r 10 on Pad1's front bottom edge (y = 0, z = 0) after the boss; the boss parked:
    the fillet keeps its edge on Pad1 as Pad1 grows."""

    REFS = ("fillet_edge",)
    radius = 10

    def frontBottom(self):
        return edge("line", direction=X, through=self.s(300, 0, 0))

    def extra(self, doc, body):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (doc.Pad2, self.names(doc.Pad2, self.frontBottom()))
        fillet.Radius = self.s(self.radius)

    def addRefs(self, doc):
        self.ref("fillet_edge", doc.Fillet, "Base", self.frontBottom, Filleted(self.s(self.radius)))


class ParkedPadOwnEdge(Park596):
    """A fillet r 10 on the boss's top back edge (y = 200, z = 350); the boss then parked: the edge
    isn't there while it is, so the fillet breaks (design 6.3); moved back below Pad1, it is."""

    REFS = ("fillet_edge",)
    steps = ("parkIt", "taller", "moveBack")
    radius = 10
    park = False
    parked = False

    def topBackEdge(self):
        return edge("line", direction=X, through=self.s(300, 200, self.height + 50))

    def expectation(self):
        return BROKEN if self.parked else self.topBackEdge()

    def extra(self, doc, body):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (doc.Pad2, self.names(doc.Pad2, self.topBackEdge()))
        fillet.Radius = self.s(self.radius)

    def addRefs(self, doc):
        self.ref("fillet_edge", doc.Fillet, "Base", self.expectation, Filleted(self.s(self.radius)))

    def parkIt(self, doc):
        self.parkBoss(doc)
        self.parked = True

    def moveBack(self, doc):
        doc.Body.reorderObject([doc.Pad2], doc.Pad1, True)
        self.parked = False
