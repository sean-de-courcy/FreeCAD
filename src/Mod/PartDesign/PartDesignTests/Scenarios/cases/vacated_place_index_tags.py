# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prd2eson-r5 (ops#526 D2, round 5): placeVerdict's SourceGone (893786373f): an index-made
old name (`Edge10;_;<id>;MKR;0;E;0;IDX,SRC;_`, a primitive's) whose object has no mark in the
record breaks at the place. Aimed at the references SourceGone turns loud where the element is
still the right one (an object replaced by an identical one, a name nobody renamed) and at the
names whose tag the marks can't carry (a second AdditiveBox's tag is negative in a Body: F1,
fixed in D2). A copied shape's break is accepted under D2's Decision 120 (4) line (ops#565)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Chamfered,
    face,
    Z,
    Scenario,
    X,
    Y,
    edge,
    pieces,
)
from PartDesignTests.Scenarios import models as m

V = m.V


class BoxRef(Scenario):
    """A Body of AdditiveBoxes L x T x H at the y places `boxes`; a datum Plane in the Body
    (`inner`) and a Part Plane outside it (`outer`) attached (NormalToEdge) to the outer top edge
    of box `ref` (0-based; y = boxes[ref], z = H) as the last box's shape holds it."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review prd2eson-r5"
    TIER = "F"
    SIZE = 4090
    REFS = ("inner", "outer")
    length, thickness, height = 3600, 45, 235
    boxes = (0, 2000, 4045)
    ref_box = 0
    edited = False

    def topEdge(self, k=None):
        y = self.boxes[self.ref_box if k is None else k]
        y, H = self.s(y, self.height)
        return edge("line", direction=X, through=(0, y, H))

    def want(self):
        return self.topEdge()

    def cutAfter(self, doc, name):
        """A SubtractiveBox put into the Body right after the referenced box, so that the
        referenced box's successors (the last box, the holders' target) carry the cut."""
        cut = doc.addObject("PartDesign::SubtractiveBox", name)
        self.body.insertObject(cut, self.made[self.ref_box], True)
        return cut

    def addBox(self, doc, body, name, y, before=None):
        L, T, H = self.s(self.length, self.thickness, self.height)
        if before is None:
            box = body.newObject("PartDesign::AdditiveBox", name)
        else:
            box = doc.addObject("PartDesign::AdditiveBox", name)
        box.Length, box.Width, box.Height = L, T, H
        box.Placement.Base = V(0, self.s(y), 0)
        if before is not None:
            body.insertObject(box, before, False)
        return box

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        self.made = [self.addBox(doc, body, "Box%d" % (i + 1), y) for i, y in enumerate(self.boxes)]
        doc.recompute()
        last = self.made[-1]
        inner = body.newObject("PartDesign::Plane", "InnerPlane")
        inner.AttachmentSupport = [(last, self.names(last, self.topEdge())[0])]
        inner.MapMode = "NormalToEdge"
        doc.recompute()
        outer = doc.addObject("Part::Plane", "EdgePlane")
        outer.Length = outer.Width = self.s(10)
        outer.AttachmentSupport = [(body, self.names(body, self.topEdge())[0])]
        outer.MapMode = "NormalToEdge"
        doc.recompute()
        self.ref("inner", inner, "AttachmentSupport", lambda: self.want(), Attached())
        self.ref("outer", outer, "AttachmentSupport", lambda: self.want(), Attached())

    def replace(self, doc, k):
        """Box k replaced by an identical new box at the same place in the Body's order."""
        old = self.made[k]
        new = self.addBox(doc, self.body, "BoxNew", self.boxes[k], before=old)
        self.body.removeObject(old)
        doc.removeObject(old.Name)
        self.made[k] = new


class FirstBoxReplacedByIdentical(BoxRef):
    """Box 1 (positive tag) deleted and an identical box put in its place in the Body's order.
    The reference is box 1's outer top edge; the new box has it at the same place (the person's
    element, as a sketch drawn again in place), so integration's expectation is that edge."""

    def edit(self, doc):
        self.replace(doc, 0)


class SecondBoxReplacedByIdentical(BoxRef):
    """The same for box 2 (its tag is negative in the Body's fuse: -ID)."""

    ref_box = 1

    def edit(self, doc):
        self.replace(doc, 1)


class SecondBoxRenamed(BoxRef):
    """Box 2's Label changed and the document recomputed: nothing about the element changed."""

    ref_box = 1

    def edit(self, doc):
        self.made[1].Label = "Renamed"
        self.made[1].touch()


class SecondBoxMovedAlongX(BoxRef):
    """Box 2 moved 10 along its length: the element is where it was (shifted), the names stay."""

    ref_box = 1

    def want(self):
        return self.topEdge()

    def edit(self, doc):
        self.made[1].Placement.Base = V(self.s(10), self.s(self.boxes[1]), 0)


class SecondBoxCutAcross(BoxRef):
    """Box 2's outer top edge cut in two by a SubtractiveBox slot across it (x 1000..1100)."""

    ref_box = 1

    def want(self):
        L, T, H = self.s(self.length, self.thickness, self.height)
        y = self.s(self.boxes[self.ref_box])
        a, b = self.s(1000), self.s(1100)
        if not self.edited:
            return self.topEdge()
        return pieces(
            edge(
                "line",
                direction=X,
                where=lambda e: abs(e.Vertexes[0].Point.y - y) < 1e-3
                and abs(e.Vertexes[0].Point.z - H) < 1e-3
                and abs(e.Vertexes[1].Point.y - y) < 1e-3
                and abs(e.Vertexes[1].Point.z - H) < 1e-3
                and (e.BoundBox.XMin < a + 1e-3 or e.BoundBox.XMax > b - 1e-3)
                and e.BoundBox.XLength < L - 1e-3,
            )
        )

    def edit(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        slot = self.cutAfter(doc, "Slot")
        slot.Length, slot.Width, slot.Height = self.s(100), 2 * T, 2 * H
        slot.Placement.Base = V(self.s(1000), self.s(self.boxes[1]) - T / 2, -H / 2)
        self.edited = True


class FirstBoxCutAcross(SecondBoxCutAcross):
    ref_box = 0

    def edit(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        slot = self.cutAfter(doc, "Slot")
        slot.Length, slot.Width, slot.Height = self.s(100), 2 * T, 2 * H
        slot.Placement.Base = V(self.s(1000), self.s(self.boxes[0]) - T / 2, -H / 2)
        self.edited = True


class SecondBoxEndTrimmed(BoxRef):
    """Box 2's outer top edge shortened: a SubtractiveBox takes x 0..100 off box 2 (the edge is
    still the same edge, shorter)."""

    ref_box = 1

    def want(self):
        L, T, H = self.s(self.length, self.thickness, self.height)
        y = self.s(self.boxes[self.ref_box])
        return edge(
            "line",
            direction=X,
            where=lambda e: abs(e.Vertexes[0].Point.y - y) < 1e-3
            and abs(e.Vertexes[0].Point.z - H) < 1e-3
            and abs(e.Vertexes[1].Point.y - y) < 1e-3
            and abs(e.Vertexes[1].Point.z - H) < 1e-3,
        )

    def edit(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        cut = self.cutAfter(doc, "Trim")
        cut.Length, cut.Width, cut.Height = self.s(100), 2 * T, 2 * H
        cut.Placement.Base = V(0, self.s(self.boxes[1]) - T / 2, -H / 2)


class FirstBoxEndTrimmed(SecondBoxEndTrimmed):
    ref_box = 0

    def edit(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        cut = self.cutAfter(doc, "Trim")
        cut.Length, cut.Width, cut.Height = self.s(100), 2 * T, 2 * H
        cut.Placement.Base = V(0, self.s(self.boxes[0]) - T / 2, -H / 2)


class FusedBoxes(Scenario):
    """Part::Box A (y = 0) and B (y = 2000), L x T x H, a Part::MultiFuse of them, and a Part
    Plane attached (NormalToEdge) to the fuse's outer top edge of box `ref_box`."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review prd2eson-r5"
    TIER = "F"
    SIZE = 4090
    REFS = ("plane",)
    length, thickness, height = 3600, 45, 235
    ys = (0, 2000)
    ref_box = 0
    edited = False

    def topEdge(self):
        y, H = self.s(self.ys[self.ref_box], self.height)
        return edge("line", direction=X, through=(0, y, H))

    def box(self, doc, name, k):
        L, T, H = self.s(self.length, self.thickness, self.height)
        return m.box(doc, name, (L, T, H), at=(0, self.s(self.ys[k]), 0))

    def build(self, doc):
        self.a = self.box(doc, "A", 0)
        self.b = self.box(doc, "B", 1)
        self.fuse = doc.addObject("Part::MultiFuse", "Fuse")
        self.fuse.Shapes = [self.a, self.b]
        doc.recompute()
        plane = doc.addObject("Part::Plane", "EdgePlane")
        plane.Length = plane.Width = self.s(10)
        plane.AttachmentSupport = [(self.fuse, self.names(self.fuse, self.topEdge())[0])]
        plane.MapMode = "NormalToEdge"
        doc.recompute()
        self.ref("plane", plane, "AttachmentSupport", lambda: self.topEdge(), Attached())


class FuseFirstInputSwapped(FusedBoxes):
    """The fuse's first input replaced by an identical box (the old one deleted)."""

    def edit(self, doc):
        new = self.box(doc, "ANew", 0)
        self.fuse.Shapes = [new, self.b]
        doc.removeObject(self.a.Name)


class FuseSecondInputSwapped(FusedBoxes):
    ref_box = 1

    def edit(self, doc):
        new = self.box(doc, "BNew", 1)
        self.fuse.Shapes = [self.a, new]
        doc.removeObject(self.b.Name)


class FuseFirstInputSwappedKept(FusedBoxes):
    """The same, the old box kept in the document (unused): its ID is still in the model, no
    longer in the fuse's closure."""

    def edit(self, doc):
        new = self.box(doc, "ANew", 0)
        self.fuse.Shapes = [new, self.b]
        self.a.Visibility = False


class FuseInputsReordered(FusedBoxes):
    """The fuse's inputs listed the other way round: the same boxes, the same edge."""

    def edit(self, doc):
        self.fuse.Shapes = [self.b, self.a]


class FuseInputMoved(FusedBoxes):
    """Box A moved 10 along X: the same box, the same edge, shifted."""

    def edit(self, doc):
        self.a.Placement.Base = V(self.s(10), 0, 0)


class CopyOfFuse(Scenario):
    """A Part::Feature `Copy` holds the fuse's shape (a simple copy: its names keep the boxes'
    tags, it has no link to them) and a Part Plane is attached to Copy's outer top edge of box
    A. Edit: A deleted and replaced by an identical box, the copy taken again."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#565"
    FOUND_BY = "review prd2eson-r5"
    TIER = "F"
    SIZE = 4090
    REFS = ("plane",)
    length, thickness, height = 3600, 45, 235
    ys = (0, 2000)

    def topEdge(self):
        y, H = self.s(self.ys[0], self.height)
        return edge("line", direction=X, through=(0, y, H))

    def box(self, doc, name, k):
        L, T, H = self.s(self.length, self.thickness, self.height)
        return m.box(doc, name, (L, T, H), at=(0, self.s(self.ys[k]), 0))

    def build(self, doc):
        self.a = self.box(doc, "A", 0)
        self.b = self.box(doc, "B", 1)
        self.fuse = doc.addObject("Part::MultiFuse", "Fuse")
        self.fuse.Shapes = [self.a, self.b]
        doc.recompute()
        self.copy = doc.addObject("Part::Feature", "Copy")
        self.copy.Shape = self.fuse.Shape
        doc.recompute()
        plane = doc.addObject("Part::Plane", "EdgePlane")
        plane.Length = plane.Width = self.s(10)
        plane.AttachmentSupport = [(self.copy, self.names(self.copy, self.topEdge())[0])]
        plane.MapMode = "NormalToEdge"
        doc.recompute()
        self.ref("plane", plane, "AttachmentSupport", lambda: self.topEdge(), Attached())

    def edit(self, doc):
        new = self.box(doc, "ANew", 0)
        self.fuse.Shapes = [new, self.b]
        doc.recompute()
        self.copy.Shape = self.fuse.Shape


class FirstBoxDeletedRefSecond(BoxRef):
    """Three boxes; the reference is box 2's outer top edge (named from box 2's tag, negative in
    the fuse: -ID); box 1, which is not referenced, is deleted. Box 2 is the first feature now
    (its elements are named by the positive ID): same element, same place."""

    ref_box = 1

    def edit(self, doc):
        old = self.made[0]
        self.body.removeObject(old)
        doc.removeObject(old.Name)


class FirstBoxDeletedRefSecondTarget(BoxRef):
    """Two boxes, the reference is box 2's outer top edge held on Box2 itself (the last box, the
    target); box 1 is deleted."""

    boxes = (0, 2000)
    ref_box = 1

    def edit(self, doc):
        old = self.made[0]
        self.body.removeObject(old)
        doc.removeObject(old.Name)


class FirstBoxDeletedRefThird(BoxRef):
    """Three boxes; the reference is box 3's outer top edge; box 1 is deleted."""

    ref_box = 2

    def edit(self, doc):
        old = self.made[0]
        self.body.removeObject(old)
        doc.removeObject(old.Name)


class FirstBoxDeletedRefSecondThick(FirstBoxDeletedRefSecond):
    thickness = 100
    boxes = (0, 2000, 3990)


class FirstBoxReorderedAfterRefSecond(BoxRef):
    """Three boxes; the reference is box 2's outer top edge; box 1 is moved after box 3 in the
    Body's order (the Tip follows): box 2 is first now."""

    ref_box = 1

    def edit(self, doc):
        b1, b3 = self.made[0], self.made[2]
        self.body.removeObject(b1)
        self.body.insertObject(b1, b3, True)
        self.body.Tip = b1


class SecondBoxTipRolledBack(BoxRef):
    """Three boxes; the reference is box 2's outer top edge held on Box2 (the target) through a
    Body whose Tip is box 1... the first box's Label changed, nothing else (control)."""

    boxes = (0, 2000)
    ref_box = 1

    def edit(self, doc):
        self.made[0].Placement.Base = V(0, self.s(self.boxes[0]) - self.s(100), 0)


class FirstBoxDeletedRefSecondChamfer(Scenario):
    """Boxes at y = 0, 2000, 4045 (3600 x 45 x 235); a Chamfer (5) on box 2's outer top edge
    (y = 2000), held on Box3 (the last box); a sketch on box 2's top face (held on Box3 too).
    Box 1, unreferenced, is deleted: box 2 is the first feature now, its elements renamed by the
    positive ID (it had -ID as the second box)."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review prd2eson-r5"
    TIER = "F"
    SIZE = 4090
    REFS = ("chamfer", "sketch")
    length, thickness, height = 3600, 45, 235
    boxes = (0, 2000, 4045)

    def topEdge(self):
        y, H = self.s(self.boxes[1], self.height)
        return edge("line", direction=X, through=(0, y, H))

    def topFace(self):
        L, T, H = self.s(self.length, self.thickness, self.height)
        return face("plane", normal=Z, contains=(L / 2, self.s(self.boxes[1]) + T / 2, H))

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        self.made = []
        for i, y in enumerate(self.boxes):
            box = body.newObject("PartDesign::AdditiveBox", "Box%d" % (i + 1))
            box.Length, box.Width, box.Height = L, T, H
            box.Placement.Base = V(0, self.s(y), 0)
            self.made.append(box)
        doc.recompute()
        last = self.made[-1]
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (last, self.names(last, self.topEdge()))
        chamfer.Size = self.s(5)
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(last, self.names(last, self.topFace())[0])]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        self.body = body
        self.ref("chamfer", chamfer, "Base", lambda: self.topEdge(), Chamfered(self.s(5)))
        self.ref("sketch", sketch, "AttachmentSupport", lambda: self.topFace(), Attached())

    def edit(self, doc):
        old = self.made[0]
        self.body.removeObject(old)
        doc.removeObject(old.Name)
