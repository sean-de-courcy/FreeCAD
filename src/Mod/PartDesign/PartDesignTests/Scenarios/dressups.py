# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Dress-ups after upstream edits: a draft, a fillet and a chamfer keep their edges and faces
when the features before them change, are inserted or are reordered."""

from .harness import (
    Broken,
    Chamfered,
    Drafted,
    Filleted,
    Scenario,
    X,
    Y,
    Z,
    edge,
    expectedNames,
    face,
    pieces,
    sameSolid,
)
from . import models as m


class DressUpEdit(Scenario):
    """A pad (0..20 x 0..10 x 0..10) with two holes through it (HoleA at x = 6, HoleB at
    x = 14, radius 2); a draft of the right face on the bottom face, 5 degrees; a fillet of the
    front top edge, radius 1; a chamfer of the left bottom edge, size 1."""

    abstract = True
    area = "dress-ups"
    MULTI = True
    REFS = ("draft_face", "draft_neutral", "fillet_edge", "chamfer_edge")
    width, depth, height = 20, 10, 10

    def rightFace(self):
        return face("plane", normal=X, through=(self.width, 0, 0))

    def bottomFace(self):
        return face("plane", normal=-Z, through=(0, 0, 0))

    def frontTopEdge(self):
        return edge("line", direction=X, through=(0, 0, self.height))

    def leftBottomEdge(self):
        return edge("line", direction=Y, through=(0, 0, 0))

    def hole(self, body, name, x):
        sketch = m.sketch(self.doc, name + "Sketch", [m.circle(x, 5, 2)], body, z=self.height)
        return m.pocketThroughAll(body, sketch, name)

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.width, self.depth), body)
        m.pad(body, profile, self.height)
        self.hole(body, "HoleA", 6)
        holeB = self.hole(body, "HoleB", 14)
        doc.recompute()
        draft = body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (holeB, self.names(holeB, self.rightFace()))
        draft.NeutralPlane = (holeB, self.names(holeB, self.bottomFace()))
        draft.Angle = 5
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (draft, self.names(draft, self.frontTopEdge()))
        fillet.Radius = 1
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (fillet, self.names(fillet, self.leftBottomEdge()))
        chamfer.Size = 1
        self.ref("draft_face", draft, "Base", self.rightFace, Drafted(5, self.bottomFace))
        self.ref("draft_neutral", draft, "NeutralPlane", self.bottomFace)
        self.ref("fillet_edge", fillet, "Base", self.frontTopEdge, Filleted(1))
        self.ref("chamfer_edge", chamfer, "Base", self.leftBottomEdge, Chamfered(1))


class DressUpLength(DressUpEdit):
    """The pad gets longer: 10 -> 15."""

    def edit(self, doc):
        doc.Pad.Length = 15
        self.height = 15


class DressUpInsertPocket(DressUpEdit):
    """A notch (x 8..12, y 8..10) through the back is inserted before the draft, as a user does
    it: the tip set to HoleB, a sketch and a pocket added, the tip set back."""

    def edit(self, doc):
        body = self.bodyObject
        body.Tip = doc.HoleB
        sketch = m.sketch(doc, "NotchSketch", m.rectangle(8, 8, 12, 12), body, z=self.height)
        m.pocketThroughAll(body, sketch, "Notch")
        body.Tip = doc.Chamfer


class DressUpReorder(DressUpEdit):
    """HoleA is moved after HoleB, as the GUI's "Move object after other object" does it."""

    def edit(self, doc):
        body = self.bodyObject
        body.removeObject(doc.HoleA)
        body.insertObject(doc.HoleA, doc.HoleB, True)


class FilletDeleteBase(Scenario):
    """A block (0..10 each way); fillet A on the front top edge, radius 1; fillet B on A's back
    bottom edge, radius 0.25, an edge A leaves as it was on the block. A is deleted, as the GUI
    does it (the body reroutes its next feature, then the document removes it): B's Base should
    move to the block's back bottom edge (ops#23 step 5)."""

    abstract = True
    area = "dress-ups"
    MULTI = True
    REFS = ("fillet_edge",)
    size = 10

    def frontTopEdge(self):
        return edge("line", direction=X, through=(0, 0, self.size))

    def backBottomEdge(self):
        return edge("line", direction=X, through=(0, self.size, 0))

    def block(self, doc, body):
        raise NotImplementedError

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        block = self.block(doc, body)
        doc.recompute()
        filletA = body.newObject("PartDesign::Fillet", "FilletA")
        filletA.Base = (block, self.names(block, self.frontTopEdge()))
        filletA.Radius = 1
        doc.recompute()
        filletB = body.newObject("PartDesign::Fillet", "FilletB")
        filletB.Base = (filletA, self.names(filletA, self.backBottomEdge()))
        filletB.Radius = 0.25
        self.ref("fillet_edge", filletB, "Base", self.backBottomEdge, Filleted(0.25))

    def edit(self, doc):
        self.bodyObject.removeObject(doc.FilletA)
        doc.removeObject("FilletA")


class FilletDeleteBaseBox(FilletDeleteBase):
    """The block is a PartDesign AdditiveBox, whose shape has no element map (TestFillet's
    model)."""

    def block(self, doc, body):
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = self.size
        return box


class FilletDeleteBasePad(FilletDeleteBase):
    """The block is a pad of a square sketch, whose shape is named."""

    def block(self, doc, body):
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.size, self.size), body)
        return m.pad(body, profile, self.size)


class FilletCornerCut(Scenario):
    """A pad of a rectangle 0..20 x 0..10, 10 high; a fillet, radius 1, on its vertical edge at
    x = 20, y = 0. The sketch's corner there is then cut off by 1, as a user chamfers a sketch
    corner: the front and right lines end short and a new line joins them. The filleted edge is
    gone, so the fillet should break, with the two new corner edges, at (19, 0) and (20, 1), as
    the candidates. Found by the randomized sequences (seed 4)."""

    area = "dress-ups"
    MULTI = True
    REFS = ("fillet_edge",)
    cut = False

    def cornerEdge(self):
        if self.cut:
            return Broken(
                edge("line", direction=Z, through=(19, 0, 0)),
                edge("line", direction=Z, through=(20, 1, 0)),
            )
        return edge("line", direction=Z, through=(20, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.cornerEdge()))
        fillet.Radius = 1
        self.ref("fillet_edge", fillet, "Base", self.cornerEdge, Filleted(1))

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (19, 0)), 1: ((20, 1), (20, 10))})
        doc.Profile.addGeometry(m.polyline([(19, 0), (20, 1)]), False)
        self.cut = True


class FilletNotchBeside(Scenario):
    """As FilletCornerCut, a fillet, radius 1, on the vertical edge at x = 20, y = 0. A notch
    (x 8..12, 2 deep) is cut into the back side, and after a recompute another into the front
    side, as in SketchNotch: the front line ends at x = 8, and the rest of the side, x 12..20,
    is a new line. The corner at (20, 0) is where it was, so the fillet should stay on it.
    The corner's vertex joined the front line's end and the right line's start (g1v2, g2v1); it
    is now g12v2, g2v1, and the notch's first corner, at (8, 0), is g1v2, g9v1. With the front
    notch only (new lines g5-g8) every mode is correct. Found by the randomized sequences (seeds
    12 and 29): with the multi-match flags on, the fillet took both edges (ops#76) until a match
    on one shared vertex ID counted only when it is the only one (ops#79)."""

    area = "dress-ups"
    MULTI = True
    REFS = ("fillet_edge",)

    def cornerEdge(self):
        return edge("line", direction=Z, through=(20, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.cornerEdge()))
        fillet.Radius = 1
        self.ref("fillet_edge", fillet, "Base", self.cornerEdge, Filleted(1))

    def edit(self, doc):
        m.setLines(doc.Profile, {2: ((20, 10), (12, 10))})
        doc.Profile.addGeometry(m.polyline([(12, 10), (12, 8), (8, 8), (8, 10), (0, 10)]), False)
        doc.recompute()
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)


class FilletNotchAfterChamfer(Scenario):
    """A pad of a rectangle 0..20 x 0..10, 10 high; a chamfer, size 0.75, on the front bottom edge;
    a fillet, radius 0.5, on the chamfer's vertical edge at x = 20, y = 0, which the chamfer
    shortened at its foot. A notch (x 8..12, 2 deep) is then cut into the front side, as in
    SketchNotch: the front line ends at x = 8, and the rest of the side is a new line. The corner
    at (20, 0) is where it was, so the fillet should stay on it. Found by the randomized sequences
    (seeds 151, 153 and 200): V2 moved the fillet to the notch's corner (ops#79); it now breaks,
    as V1 does. With the fillet on the pad itself (FilletNotchBeside with one notch) V2 is
    correct. The chamfer's own edge splits into x 0..8 and x 12..20, and the chamfer should take
    both pieces (SplitFilletNotch's case, ops#7): keeping the front line's piece is what moves the
    chamfer off the corner and takes the geometric search's rescue away from the fillet."""

    area = "dress-ups"
    MULTI = True
    REFS = ("chamfer_edge", "fillet_edge")

    def cornerEdge(self):
        return edge("line", direction=Z, through=(20, 0, 0))

    def frontBottomEdge(self):
        return pieces(edge("line", direction=X, through=(0, 0, 0)))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.frontBottomEdge().predicate))
        chamfer.Size = 0.75
        self.ref("chamfer_edge", chamfer, "Base", self.frontBottomEdge, Chamfered(0.75))
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (chamfer, self.names(chamfer, self.cornerEdge()))
        fillet.Radius = 0.5
        self.ref("fillet_edge", fillet, "Base", self.cornerEdge, Filleted(0.5))

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)


class ChamferedOn(Chamfered):
    """A chamfer that should build on the named feature: the oracle is the Part chamfer of that
    feature's shape, whatever the dress-up's BaseFeature says."""

    def __init__(self, size, base):
        super().__init__(size)
        self.base = base

    def compare(self, scenario, consumer, target, expectation):
        base = scenario.doc.getObject(self.base).Shape
        edges = [base.getElement(n) for n in expectedNames(expectation, base)]
        return sameSolid(consumer.Shape, self.oracle(base, edges))


class DressUpInsertThenNotch(Scenario):
    """A pad of a rectangle 0..20 x 0..10, 10 high; a chamfer, size 1, on its back top edge; a
    boss (x 5..9, y 3..7, 3 high) inserted after the pad, as a user does it (the tip set to the
    pad, the sketch and the pad added, the tip set back). The chamfer's Base still names the pad,
    and its BaseFeature is the boss, so the chamfer should build on the boss. Then a notch (x 8..12,
    2 deep) is cut into the front side of the pad's sketch, which renumbers the pad's edges: the
    naming refresh rewrites the chamfer's Base (Edge10 -> Edge22, the same edge), and
    DressUp::onChanged then sets BaseFeature to Base's object, the pad. The boss drops out of the
    model and the chamfer stays valid (ops#82). Found by the randomized sequences (seed 194).
    V1 can't build the model: its chamfer breaks at the insert."""

    area = "dress-ups"
    MULTI = True
    REFS = ("chamfer_edge",)

    def backTopEdge(self):
        return edge("line", direction=X, through=(0, 10, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.backTopEdge()))
        chamfer.Size = 1
        doc.recompute()
        body.Tip = pad
        boss = m.sketch(doc, "BossSketch", m.rectangle(5, 3, 9, 7), body, z=10)
        m.pad(body, boss, 3, name="Boss")
        body.Tip = chamfer
        self.ref("chamfer_edge", chamfer, "Base", self.backTopEdge, ChamferedOn(1, "Boss"))

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)
