"""Review pr596s-r1 (ops#596, decisions 275 (2), 276, 281; notes/park-design.md): aimed at what the
park's (R) changes in the reference solver's view: a parked lead is no longer a shape input, so the
references of the Body are judged by the ordinary rules, with the parked feature's own elements
gone. A 600 x 300 block padded 300 (Pad1); a boss on its top (Pad2, its sketch attached to the top
face); the boss moved above Pad1 (Body.reorderObject, ops#127's park)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Filleted,
    Scenario,
    X,
    Z,
    edge,
    face,
)
from PartDesignTests.Scenarios import models as m


class Park(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#596"
    FOUND_BY = "review pr596s-r1"
    TIER = "F"
    SIZE = 600
    REFS = ("ref",)
    steps = ("park", "taller")
    parkAtBuild = False
    height = 300
    rect = (250, 100, 350, 200)   # the boss's footprint at scale 1
    thick = 50                    # the boss's height at scale 1
    radius = 1

    def top(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def bossTop(self):
        return face("plane", normal=Z, through=(0, 0, self.s(300 + self.thick)))

    def block(self, doc, body):
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        return m.pad(body, base, self.s(300), "Pad1")

    def boss(self, doc, body, pad):
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "BossSketch")
        sketch.AttachmentSupport = [(pad, self.names(pad, self.top())[0])]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        local = sketch.getGlobalPlacement().inverse()
        x0, y0, x1, y1 = self.rect
        a, b = (local.multVec(App.Vector(*self.s(x, y, 300))) for x, y in ((x0, y0), (x1, y1)))
        sketch.addGeometry(
            m.rectangle(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y)), False
        )
        return m.pad(body, sketch, self.s(self.thick), "Pad2")

    def extra(self, doc, body):
        """After the boss, before the park."""

    def addRef(self, doc):
        raise NotImplementedError

    def build(self, doc):
        body = m.body(doc)
        pad = self.block(doc, body)
        self.boss(doc, body, pad)
        doc.recompute()
        self.extra(doc, body)
        doc.recompute()
        self.addRef(doc)
        if self.parkAtBuild:
            self.park(doc)

    def park(self, doc):
        doc.Body.reorderObject([doc.Pad2], None, True)

    def taller(self, doc):
        doc.Pad1.Length = self.s(450)
        self.height = 450


class FilletOnBoss(Park):
    """A fillet on the boss's top edge at y = `edgeY`; the boss parked: the edge is gone (the
    boss's top is not there), so the fillet must break, however near Pad1's own top edge is."""

    abstract = True
    edgeY = 0

    def bossEdge(self):
        return edge("line", direction=X, through=self.s(300, self.edgeY, 300 + self.thick))

    def extra(self, doc, body):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (doc.Pad2, self.names(doc.Pad2, self.bossEdge()))
        fillet.Radius = self.s(self.radius)

    def addRef(self, doc):
        self.ref("ref", doc.Fillet, "Base", self.expected, Filleted(self.s(self.radius)))

    def expected(self):
        return BROKEN if self.stepName in ("park", "taller") else self.bossEdge()


class ThinFullBossFrontEdge(FilletOnBoss):
    """A 600 x 300 boss 3 high over the whole top face; the fillet on its top front edge
    (y = 0, z = 303), 3 from Pad1's own top front edge."""

    rect = (0, 0, 600, 300)
    thick = 3
    edgeY = 0


class ThinFlushBossBackEdge(FilletOnBoss):
    """A 600 x 100 boss 3 high flush with Pad1's back face; the fillet on its top back edge
    (y = 300, z = 303)."""

    rect = (0, 200, 600, 300)
    thick = 3
    edgeY = 300


class ThickFlushBossBackEdge(FilletOnBoss):
    """The control: the same, 50 high."""

    rect = (0, 200, 600, 300)
    thick = 50
    edgeY = 300
    radius = 10


class ThinFullBossTopSketch(Park):
    """A sketch attached to the top face of a boss 3 high over the whole top face (z = 303);
    the boss parked: that face is gone; Pad1's own top is 3 below."""

    rect = (0, 0, 600, 300)
    thick = 3

    def extra(self, doc, body):
        sketch = body.newObject("Sketcher::SketchObject", "OnBoss")
        sketch.AttachmentSupport = [(doc.Pad2, self.names(doc.Pad2, self.bossTop())[0])]
        sketch.MapMode = "FlatFace"

    def addRef(self, doc):
        self.ref("ref", doc.OnBoss, "AttachmentSupport", self.expected, Attached())

    def expected(self):
        return BROKEN if self.stepName in ("park", "taller") else self.bossTop()


class SuppressedWhileParked(Park):
    """The boss parked; a sketch on Pad1's top face; Pad1 suppressed (the Body is empty), then
    not; then made taller."""

    steps = ("suppress", "unsuppress", "taller")
    parkAtBuild = True

    def extra(self, doc, body):
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(doc.Pad1, self.names(doc.Pad1, self.top())[0])]
        sketch.MapMode = "FlatFace"

    def expected(self):
        return BROKEN if self.stepName == "suppress" else self.top()

    def addRef(self, doc):
        self.ref("ref", doc.OnTop, "AttachmentSupport", self.expected, Attached())

    def suppress(self, doc):
        doc.Pad1.Suppressed = True

    def unsuppress(self, doc):
        doc.Pad1.Suppressed = False


class PatternOfParkedBoss(Park):
    """A linear pattern of the boss (two, 150 along X) after it; the boss parked (the pattern's
    Original is set aside); a sketch on Pad1's top face follows Pad1 made taller."""

    parkAtBuild = True

    def extra(self, doc, body):
        pattern = body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [doc.Pad2]
        pattern.Direction = (m.originFeature(body, "X_Axis"), [""])
        pattern.Length = self.s(150)
        pattern.Occurrences = 2
        body.Tip = pattern
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(doc.Pad1, self.names(doc.Pad1, self.top())[0])]
        sketch.MapMode = "FlatFace"

    def addRef(self, doc):
        self.ref("ref", doc.OnTop, "AttachmentSupport", self.top, Attached())


class MoveBackOverATakenEdge(Park):
    """The boss (a 600 x 100 slab 50 high flush with Pad1's back face) parked, a fillet taken on
    Pad1's top back edge (y = 300, z = 300) in that world; the boss moved back below Pad1: that
    edge is now inside the back face, so the fillet must break."""

    rect = (0, 200, 600, 300)
    thick = 50
    radius = 10
    steps = ("moveBack", "taller")

    def backEdge(self):
        return edge("line", direction=X, through=self.s(300, 300, 300))

    def build(self, doc):
        body = m.body(doc)
        pad = self.block(doc, body)
        self.boss(doc, body, pad)
        doc.recompute()
        self.park(doc)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (doc.Pad1, self.names(doc.Pad1, self.backEdge()))
        fillet.Radius = self.s(self.radius)
        doc.recompute()
        self.ref("ref", fillet, "Base", self.expected, Filleted(self.s(self.radius)))

    def expected(self):
        return BROKEN if self.stepName in ("moveBack", "taller") else self.backEdge()

    def moveBack(self, doc):
        doc.Body.reorderObject([doc.Pad2], doc.Pad1, True)

    def taller(self, doc):
        pass


class ParkedBossFilletOnBlockRedrawn(Park):
    """A fillet r 10 on Pad1's bottom front edge (after the boss); the boss parked; Pad1's base
    rectangle is redrawn (moved lines, same IDs) 100 wider in X and 60 deeper in Y, then back.
    The fillet must follow Pad1's bottom front edge."""

    steps = ("park", "wider", "back")
    parkAtBuild = False
    wide = 600
    deep = 300

    def frontBottom(self):
        return edge("line", direction=X, through=self.s(self.wide / 2, 0, 0))

    def extra(self, doc, body):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (doc.Pad1, self.names(doc.Pad1, self.frontBottom()))
        fillet.Radius = self.s(10)

    def addRef(self, doc):
        self.ref("ref", doc.Fillet, "Base", self.frontBottom, Filleted(self.s(10)))

    def wider(self, doc):
        self.wide, self.deep = 700, 360
        m.moveRectangle(doc.Base, *self.s(0, 0, self.wide, self.deep))

    def back(self, doc):
        self.wide, self.deep = 600, 300
        m.moveRectangle(doc.Base, *self.s(0, 0, self.wide, self.deep))


class ParkedBossFilletRedrawnControl(ParkedBossFilletOnBlockRedrawn):
    """The control: the boss stays."""

    steps = ("wider", "back")


class ParkedFaceProfileBoss(Park):
    """The boss is a pad of a face (its Profile is Pad1's top face, 600 x 300, 50 high); it is
    parked above Pad1 (its Profile is set aside); a sketch on Pad1's top face follows Pad1 made
    taller."""

    parkAtBuild = False

    def boss(self, doc, body, pad):
        doc.recompute()
        top = self.names(pad, self.top())[0]
        faceBoss = body.newObject("PartDesign::Pad", "Pad2")
        faceBoss.Profile = (pad, [top])
        faceBoss.Length = self.s(50)
        return faceBoss

    def extra(self, doc, body):
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(doc.Pad1, self.names(doc.Pad1, self.top())[0])]
        sketch.MapMode = "FlatFace"

    def addRef(self, doc):
        self.ref("ref", doc.OnTop, "AttachmentSupport", self.top, Attached())
