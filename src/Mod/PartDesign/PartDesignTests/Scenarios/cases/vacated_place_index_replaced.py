# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prd2eopus-r5 (ops#526 D2e): SourceGone, an index-made old name whose record has no
mark of its object, breaks at the place. Aimed at what it turns loud where integration is
right: an index-made reference whose object was replaced by an identical one (the element at
the place is still the right one, a warned guess, as replaced_hole.ReplacedHoleSamePlace), a
fusion's inputs swapped, a copied shape whose names keep another object's tag. The breaks where
integration is right are accepted under D2's Decision 120 (4) line: a box replaced in a Body
(the record refreshed before the solve, ops#564) and a copied shape (ops#565)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    Attached,
    Chamfered,
    Guessed,
    Scenario,
    X,
    edge,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = m.V


def featureBase(body):
    return next(o for o in body.Group if o.TypeId == "PartDesign::FeatureBase")


class FusedBoxes(Scenario):
    """Two Part::Box 100 x 10 x 20, box 1 at the origin, box 2 at y = 50 (apart), fused by a
    Part::MultiFuse; a body based on the fusion. A PartDesign Chamfer (1) on box 1's outer top
    edge (y = 0, z = 20, along X) and a datum point on its corner vertex (100, 0, 20). The fusion
    names box 1's elements by its index (`Edge10;_;<Box1>;MKR;...;IDX,SRC`)."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M4", "E5")
    ISSUE = "ops#526"
    FOUND_BY = "review prd2eopus-r5"
    TIER = "F"
    REFS = ("chamfer", "corner")
    maker = "Part::MultiFuse"
    size = (100, 10, 20)

    def topEdge(self):
        return edge("line", direction=X, through=(0, 0, self.size[2]))

    def cornerVertex(self):
        return vertex(at=(self.size[0], 0, self.size[2]))

    def expectEdge(self):
        return self.topEdge()

    def expectCorner(self):
        return self.cornerVertex()

    def makeBox(self, doc, name, y):
        b = doc.addObject("Part::Box", name)
        b.Length, b.Width, b.Height = self.size
        b.Placement.Base = V(0, y, 0)
        return b

    def setInputs(self, maker, inputs):
        if self.maker == "Part::MultiFuse":
            maker.Shapes = inputs
        else:
            maker.Links = inputs

    def baseShape(self, doc):
        return doc.Fusion

    def build(self, doc):
        b1 = self.makeBox(doc, "Box1", 0)
        b2 = self.makeBox(doc, "Box2", 50)
        fusion = doc.addObject(self.maker, "Fusion")
        self.setInputs(fusion, [b1, b2])
        doc.recompute()
        body = m.body(doc)
        body.BaseFeature = self.baseShape(doc)
        doc.recompute()
        base = featureBase(body)
        c = body.newObject("PartDesign::Chamfer", "Chamfer")
        c.Base = (base, self.names(base, self.topEdge()))
        c.Size = 1
        p = body.newObject("PartDesign::Point", "Corner")
        p.AttachmentSupport = [(base, self.names(base, self.cornerVertex())[0])]
        p.MapMode = "Vertex"
        doc.recompute()
        self.ref("chamfer", c, "Base", self.expectEdge, Chamfered(1))
        self.ref("corner", p, "AttachmentSupport", self.expectCorner, Attached())


class FusedBoxReplacedSamePlace(FusedBoxes):
    """Box 1 is replaced in the fusion by box 3, identical, at the same place; box 1 deleted.
    The element at the place is the right one (a warned guess; a break is loud)."""

    def expectEdge(self):
        return Guessed(self.topEdge()) if getattr(self, "replaced", False) else self.topEdge()

    def expectCorner(self):
        c = self.cornerVertex()
        return Guessed(c) if getattr(self, "replaced", False) else c

    deleteOld = True

    def edit(self, doc):
        b3 = self.makeBox(doc, "Box3", 0)
        self.setInputs(doc.Fusion, [b3, doc.Box2])
        if self.deleteOld:
            doc.removeObject("Box1")
        self.replaced = True


class FusedBoxReplacedSamePlaceKept(FusedBoxReplacedSamePlace):
    """The same, box 1 kept in the document (out of the fusion)."""

    deleteOld = False


class CompoundBoxReplacedSamePlace(FusedBoxReplacedSamePlace):
    """The same with a Part::Compound."""

    maker = "Part::Compound"


class FusedBoxInputsSwapped(FusedBoxes):
    """The fusion's inputs swapped (box 2, box 1): nothing moved, both stand."""

    def edit(self, doc):
        self.setInputs(doc.Fusion, [doc.Box2, doc.Box1])


class CopiedFusionReplacedSamePlace(FusedBoxReplacedSamePlace):
    """The body is based on a simple copy of the fusion (a Part::Feature whose shape keeps the
    fusion's names, box 1's tag included, without a link to it). Box 1 is replaced by an
    identical box 3 and the copy's shape set again from the fusion."""

    ISSUE = "ops#565"

    def baseShape(self, doc):
        copy = doc.addObject("Part::Feature", "Copy")
        copy.Shape = doc.Fusion.Shape
        return copy

    def edit(self, doc):
        super().edit(doc)
        doc.recompute()
        doc.Copy.Shape = doc.Fusion.Shape


class CopiedFusionBox2Moved(FusedBoxes):
    """The body on a simple copy of the fusion; box 2 moves to y = 30 and the copy's shape is set
    again. Box 1's elements keep their names: both stand."""

    def baseShape(self, doc):
        copy = doc.addObject("Part::Feature", "Copy")
        copy.Shape = doc.Fusion.Shape
        return copy

    def edit(self, doc):
        doc.Box2.Placement.Base = V(0, 30, 0)
        doc.recompute()
        doc.Copy.Shape = doc.Fusion.Shape


class AdditiveBoxReplacedSamePlace(Scenario):
    """PartDesign: three AdditiveBoxes 100 x 10 x 20 at y = 0, 50, 100 in one body; a Chamfer (1)
    on box 1's outer top edge, held through box 3. Box 1 deleted and an identical AdditiveBox
    inserted at its place in the chain (before box 2): the element at the place is the right one
    (a warned guess; a break is loud)."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E5")
    ISSUE = "ops#564"
    FOUND_BY = "review prd2eopus-r5"
    TIER = "F"
    REFS = ("chamfer",)
    replaced = False

    def topEdge(self):
        return edge("line", direction=X, through=(0, 0, 20))

    def expectEdge(self):
        return Guessed(self.topEdge()) if self.replaced else self.topEdge()

    def build(self, doc):
        body = m.body(doc)
        self.made = []
        for i, y in enumerate((0, 50, 100)):
            box = body.newObject("PartDesign::AdditiveBox", "Box%d" % (i + 1))
            box.Length, box.Width, box.Height = 100, 10, 20
            box.Placement.Base = V(0, y, 0)
            self.made.append(box)
        doc.recompute()
        last = self.made[-1]
        c = body.newObject("PartDesign::Chamfer", "Chamfer")
        c.Base = (last, self.names(last, self.topEdge()))
        c.Size = 1
        doc.recompute()
        self.ref("chamfer", c, "Base", self.expectEdge, Chamfered(1))

    def edit(self, doc):
        first, second = self.made[0], self.made[1]
        body = first.getParentGeoFeatureGroup()
        body.removeObject(first)
        doc.removeObject(first.Name)
        new = doc.addObject("PartDesign::AdditiveBox", "BoxAgain")
        new.Length, new.Width, new.Height = 100, 10, 20
        body.insertObject(new, second, False)
        self.replaced = True


class FusedBox1EdgeCut(FusedBoxes):
    """Box 2 moves to (50, -5, 10): it swallows box 1's top outer edge from x = 50 and the corner.
    The edge's piece x = 0..50 is the chamfer's element (box 1's own, named as its piece); the
    corner is gone."""

    AXES = ("M4", "E2")
    cut = False

    def expectCorner(self):
        from PartDesignTests.Scenarios.harness import BROKEN

        return BROKEN if self.cut else self.cornerVertex()

    def edit(self, doc):
        doc.Box2.Placement.Base = V(50, -5, 10)
        self.cut = True


class CopiedFusionBox1EdgeCut(FusedBox1EdgeCut):
    """The same through a simple copy of the fusion, its shape set again after the edit."""

    def baseShape(self, doc):
        copy = doc.addObject("Part::Feature", "Copy")
        copy.Shape = doc.Fusion.Shape
        return copy

    def edit(self, doc):
        super().edit(doc)
        doc.recompute()
        doc.Copy.Shape = doc.Fusion.Shape


class NotchedBox(Scenario):
    """A Part::Box 100 x 10 x 20 cut (Part::Cut) by a cylinder r = 5, h = 30 at (50, 0, -5): a
    notch through the front face splits the box's outer top edge (y = 0, z = 20) into two pieces,
    x = 0..45 and 55..100, each a piece of the box's index-made edge. A body on the cut; a
    PartDesign Chamfer (1) on the left piece and a datum point on the box's corner (0, 0, 20)."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M4", "E5")
    ISSUE = "ops#526"
    FOUND_BY = "review prd2eopus-r5"
    TIER = "F"
    REFS = ("chamfer", "corner")
    replaced = False

    def leftPiece(self):
        return edge("line", direction=X, contains=(10, 0, 20))

    def cornerVertex(self):
        return vertex(at=(0, 0, 20))

    def expectEdge(self):
        return Guessed(self.leftPiece()) if self.replaced else self.leftPiece()

    def expectCorner(self):
        return self.cornerVertex()

    def makeTool(self, doc, name):
        c = doc.addObject("Part::Cylinder", name)
        c.Radius, c.Height = 5, 30
        c.Placement.Base = V(50, 0, -5)
        return c

    def build(self, doc):
        b = doc.addObject("Part::Box", "Box1")
        b.Length, b.Width, b.Height = 100, 10, 20
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = b, self.makeTool(doc, "Tool1")
        doc.recompute()
        body = m.body(doc)
        body.BaseFeature = cut
        doc.recompute()
        base = featureBase(body)
        c = body.newObject("PartDesign::Chamfer", "Chamfer")
        c.Base = (base, self.names(base, self.leftPiece()))
        c.Size = 1
        p = body.newObject("PartDesign::Point", "Corner")
        p.AttachmentSupport = [(base, self.names(base, self.cornerVertex())[0])]
        p.MapMode = "Vertex"
        doc.recompute()
        self.ref("chamfer", c, "Base", self.expectEdge, Chamfered(1))
        self.ref("corner", p, "AttachmentSupport", self.expectCorner, Attached())


class NotchToolReplacedSamePlace(NotchedBox):
    """The cut's tool replaced by an identical cylinder (tool 2), tool 1 deleted: the box and its
    left piece stay; only the piece's cutting source is new."""

    def edit(self, doc):
        doc.Cut.Tool = self.makeTool(doc, "Tool2")
        doc.removeObject("Tool1")
        self.replaced = True


class NotchToolMoved(NotchedBox):
    """The tool moves 10 to the right (x = 60): the left piece grows to x = 0..55 (the same piece,
    longer)."""

    def edit(self, doc):
        doc.Tool1.Placement.Base = V(60, 0, -5)
