# SPDX-License-Identifier: LGPL-2.1-or-later

"""Reorder, insert at the bar and roll-back (ops#127, notes/reorder-rollback-design.md 7.1).

Every model starts from a 20 x 20 x 10 block. A feature inserted with the body rolled back goes
before the features after the bar, and their references follow it (the reroute, N1 2.2). A
feature moved above the feature its own inputs sit on has those references moved to its new base
with a re-target record, and back when it is moved back (the re-target rule, N1 section 3)."""

import FreeCAD as App

from .harness import (
    BROKEN,
    Attached,
    ExternalCoincides,
    Filleted,
    Scenario,
    X,
    Y,
    Z,
    edge,
    face,
    pieces,
)
from . import models as m

V = App.Vector


class ReorderScenario(Scenario):
    abstract = True
    area = "reorder"

    def block(self, doc, body):
        sketch = m.sketch(doc, "BlockSketch", m.rectangle(0, 0, 20, 20), body)
        return m.pad(body, sketch, 10, "Block")

    def pad2(self, doc, body):
        """A 10 x 10 x 5 pad on the block's top, (5, 5) to (15, 15)."""
        sketch = m.sketch(doc, "Pad2Sketch", m.rectangle(5, 5, 15, 15), body, z=10)
        return m.pad(body, sketch, 5, "Pad2")

    def sketchOn(self, doc, body, name, feature, predicate, centre, radius):
        """A sketch attached to the feature's face (FlatFace), with a circle at the global point
        centre."""
        sketch = doc.addObject("Sketcher::SketchObject", name)
        body.addObject(sketch)
        sketch.AttachmentSupport = [(feature, self.names(feature, predicate))]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        local = sketch.getGlobalPlacement().inverse().multVec(centre)
        sketch.addGeometry(m.circle(local.x, local.y, radius), False)
        return sketch


# -- Insert at the bar (N1 2.3): the fillet's Base follows the inserted feature -----------------


class InsertBeforeFillet(ReorderScenario):
    """A fillet (radius 1) of the block's front top edge; rolled back to the block, a pocket is
    added (`cut`, a rectangle on the top, 3 deep) and the body rolled to the end."""

    abstract = True
    MULTI = True
    REFS = ("fillet_edge",)
    cut = None

    def frontTopEdge(self):
        return edge("line", direction=X, through=(0, 0, 10))

    def expected(self):
        return self.frontTopEdge()

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        block = self.block(doc, body)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (block, self.names(block, self.frontTopEdge()))
        fillet.Radius = 1
        self.ref("fillet_edge", fillet, "Base", self.expected, Filleted(1))

    def edit(self, doc):
        body = self.bodyObject
        body.rollTo(doc.Block)
        sketch = m.sketch(doc, "CutSketch", m.rectangle(*self.cut), body, z=10)
        m.pocket(body, sketch, 3, "Cut")
        doc.recompute()
        body.rollToEnd()
        self.edited = True


class InsertBeforeFilletUntouched(InsertBeforeFillet):
    """The pocket is far from the edge (RO1): the fillet keeps it."""

    cut = (12, 12, 18, 18)


class InsertBeforeFilletSplit(InsertBeforeFillet):
    """The pocket cuts the edge in two (RO2): the fillet keeps both pieces."""

    cut = (8, -1, 12, 3)

    def expected(self):
        if getattr(self, "edited", False):
            return pieces(self.frontTopEdge())
        return self.frontTopEdge()


class InsertBeforeFilletGone(InsertBeforeFillet):
    """The pocket removes the whole edge (RO3): the fillet breaks."""

    cut = (-1, -1, 21, 3)

    def expected(self):
        return BROKEN if getattr(self, "edited", False) else self.frontTopEdge()


# -- Reorder of a dress-up (N1 2.1, 2.2) --------------------------------------------------------


class MoveFilletBelowHoleAndBack(ReorderScenario):
    """A fillet (radius 1) of the block's vertical edge at the origin, then a hole at (10, 10);
    the fillet is moved below the hole, then back (RO5): its Base follows its base feature and
    keeps the edge."""

    MULTI = True
    REFS = ("fillet_edge",)
    steps = ("down", "up")

    def originEdge(self):
        return edge("line", direction=Z, through=(0, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        block = self.block(doc, body)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (block, self.names(block, self.originEdge()))
        fillet.Radius = 1
        sketch = m.sketch(doc, "HoleSketch", [m.circle(10, 10, 2)], body, z=10)
        m.pocket(body, sketch, 3, "Hole")
        self.ref("fillet_edge", fillet, "Base", self.originEdge, Filleted(1))

    def down(self, doc):
        self.bodyObject.reorderObject([doc.Fillet], doc.Hole, True)

    def up(self, doc):
        self.bodyObject.reorderObject([doc.Fillet], doc.Block, True)


# -- Above a dependency: the re-target rule (N1 section 3) --------------------------------------


class MoveAboveDependency(ReorderScenario):
    """A hole (radius 1, 2 deep) whose sketch sits on a face; the hole is moved above the feature
    that face comes from (`up`), then back (`back`)."""

    abstract = True
    REFS = ("support",)
    steps = ("up", "back")

    def onFace(self):
        """The face the sketch sits on: (feature name, predicate, the hole's centre)."""
        raise NotImplementedError

    def afterUp(self):
        """The expectation once the hole is above the face's feature."""
        raise NotImplementedError

    def model(self, doc, body):
        """The features before the hole; returns the one the hole is moved above."""
        raise NotImplementedError

    def expected(self):
        if self.stepName == "up":
            return self.afterUp()
        return self.onFace()[1]

    def target(self):
        """The object the support must be on: the face's feature, the hole's new base after
        `up` (so a move back that leaves the support on the block's like face is wrong)."""
        if getattr(self, "stepName", None) == "up":
            return self.upTarget
        return self.onFace()[0]

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        self.above = self.model(doc, body)
        doc.recompute()
        name, predicate, centre = self.onFace()
        sketch = self.sketchOn(doc, body, "HoleSketch", doc.getObject(name), predicate, centre, 1)
        m.pocket(body, sketch, 2, "Hole")
        self.ref("support", sketch, "AttachmentSupport", self.expected, Attached(), self.target)

    def up(self, doc):
        body = self.bodyObject
        previous = body.Group[body.Group.index(self.above) - 1]
        while not previous.isDerivedFrom("PartDesign::Feature"):
            previous = body.Group[body.Group.index(previous) - 1]
        self.upTarget = previous.Name
        body.reorderObject([doc.Hole], previous, True)

    def back(self, doc):
        self.bodyObject.reorderObject([doc.Hole], self.above, True)


class MoveHoleAbovePadItSitsOn(MoveAboveDependency):
    """The sketch on Pad2's top face (RO6): above Pad2 the support is on the block, where the
    face isn't, so it breaks; moved back, it is on Pad2's top face again."""

    def model(self, doc, body):
        self.block(doc, body)
        return self.pad2(doc, body)

    def onFace(self):
        return "Pad2", face("plane", normal=Z, through=(0, 0, 15)), V(10, 10, 15)

    def afterUp(self):
        return BROKEN


class MoveHoleAboveTrimmingNotch(MoveAboveDependency):
    """The sketch on the block's front face, which a notch (x 8..12, 3 deep from the top)
    trims (RO6b): above the notch the support is the block's front face (the solver's tier 1);
    moved back, the notch's trimmed face again."""

    def model(self, doc, body):
        self.block(doc, body)
        sketch = m.sketch(doc, "NotchSketch", m.rectangle(8, -1, 12, 3), body, z=10)
        return m.pocket(body, sketch, 3, "Notch")

    def onFace(self):
        return "Notch", face("plane", normal=-Y, through=(0, 0, 0)), V(4, 0, 4)

    def afterUp(self):
        return face("plane", normal=-Y, through=(0, 0, 0))


class MoveHoleAbovePadOnBlockFace(MoveAboveDependency):
    """The sketch on the block's right side face, which Pad2 doesn't touch (RO7): above Pad2 the
    support is the same face of the block; moved back, Pad2's."""

    def model(self, doc, body):
        self.block(doc, body)
        return self.pad2(doc, body)

    def onFace(self):
        return "Pad2", face("plane", normal=X, through=(20, 0, 0)), V(20, 10, 5)

    def afterUp(self):
        return face("plane", normal=X, through=(20, 0, 0))


class MoveProjectionAbovePad(ReorderScenario):
    """A sketch (at z = 15) projecting Pad2's front top edge, with a hole from it, moved above
    Pad2 and back (RO11): above Pad2 the projection is on the block, which hasn't the edge; moved
    back, it is on Pad2's edge again."""

    REFS = ("projection",)
    steps = ("up", "back")

    def frontEdge(self):
        return edge("line", direction=X, through=(0, 5, 15))

    def expected(self):
        return BROKEN if self.stepName == "up" else self.frontEdge()

    def target(self):
        return "Block" if getattr(self, "stepName", None) == "up" else "Pad2"

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        self.block(doc, body)
        pad2 = self.pad2(doc, body)
        doc.recompute()
        sketch = m.sketch(doc, "Projecting", [m.circle(10, 10, 1)], body, z=15)
        sketch.addExternal(pad2.Name, self.names(pad2, self.frontEdge())[0])
        m.pocket(body, sketch, 1, "Hole")
        self.ref(
            "projection", sketch, "ExternalGeometry", self.expected, ExternalCoincides(), self.target
        )

    def up(self, doc):
        self.bodyObject.reorderObject([doc.Hole], doc.Block, True)

    def back(self, doc):
        self.bodyObject.reorderObject([doc.Hole], doc.Pad2, True)


class MoveProjectionToTop(MoveProjectionAbovePad):
    """The hole moved to the very top (RO11b-c, ops#131): nothing before it can take the
    projection, so it is parked in place (no link: broken, the sketch fails); moved back below
    Pad2, it is on Pad2's edge again, on the same geometry."""

    steps = ("top", "back")

    def expected(self):
        return BROKEN if self.stepName == "top" else self.frontEdge()

    def target(self):
        return None if getattr(self, "stepName", None) == "top" else "Pad2"

    def top(self, doc):
        self.bodyObject.reorderObject([doc.Hole], None, True)
