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
    BROKEN,
    Attached,
    Broken,
    Chamfered,
    Defeatured,
    Drafted,
    Filleted,
    PartialWarned,
    Scenario,
    X,
    Y,
    Z,
    edge,
    expectedNames,
    face,
    faceNormal,
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


class FilletDeleteNearStep(Scenario):
    """A block (0..20 x 0..10, 10 high) and a step padded onto its right side (x 20..20.5, the
    same height); a fillet, radius 0.25, on the step's front vertical edge at x = 20.5. The step
    is deleted: its edge is gone, and the reference should break. The block's front right edge is
    the same kind 0.5 mm away (2 % of the diagonal), within the no-structure guess's wide reach
    (N2 5.5, the case it names): in solver documents with NamingSolver/GuessNoStructure on (the
    default), G2 picks it loudly, which N2 7.2 scores `guessed-wrong` (the Fable review of fork
    PR 117, finding 3: the record the user decides G2's default with; ops#127)."""

    area = "dress-ups"
    REFS = ("fillet_edge",)

    def stepEdge(self):
        return edge("line", direction=Z, through=(20.5, 0, 0))

    def filletEdge(self):
        return BROKEN if getattr(self, "deleted", False) else self.stepEdge()

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        stepSketch = m.sketch(doc, "StepSketch", m.rectangle(20, 0, 20.5, 10), body)
        step = m.pad(body, stepSketch, 10, name="Step")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (step, self.names(step, self.stepEdge()))
        fillet.Radius = 0.25
        self.ref("fillet_edge", fillet, "Base", self.filletEdge, Filleted(0.25))

    def edit(self, doc):
        self.bodyObject.removeObject(doc.Step)
        doc.removeObject("Step")
        self.deleted = True


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

    def edgeB(self):
        return self.backBottomEdge()

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
        filletB.Base = (filletA, self.names(filletA, self.edgeB()))
        filletB.Radius = 0.25
        self.ref("fillet_edge", filletB, "Base", self.edgeB, Filleted(0.25))

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


class FilletDeleteBaseTrimmed(FilletDeleteBase):
    """As FilletDeleteBase, but fillet B is on the block's left top edge (x = 0, z = 10), which
    fillet A trims to y 1..10. When A is deleted, B should follow the block's full edge, y 0..10
    (the user's requirement, ops#7, 2026-09-30): a 1:1 modified edge keeps its incoming name, so
    A's trimmed edge is named as the block's edge."""

    abstract = True

    def edgeB(self):
        return edge("line", direction=Y, through=(0, 0, self.size))


class FilletDeleteBaseTrimmedBox(FilletDeleteBaseTrimmed):
    """The block is an AdditiveBox: A names the trimmed edge by the box's index (an IDX name
    tagged with the box), and the box has no element map to find it by (Q5 of the plan)."""

    block = FilletDeleteBaseBox.block


class FilletDeleteBaseTrimmedPad(FilletDeleteBaseTrimmed):
    """The block is a pad: the trimmed edge carries the pad's own name."""

    block = FilletDeleteBasePad.block


class FilletDeleteBaseArc(FilletDeleteBase):
    """As FilletDeleteBase, but fillet B is on A's arc at x = 0, an edge A made (the end of its
    rounded face). The block has no such edge: when A is deleted, B should break, never move to
    one of the block's edges."""

    abstract = True
    deleted = False

    def edgeB(self):
        if self.deleted:
            return BROKEN
        return edge("circle", center=(0, 1, self.size - 1), radius=1)

    def edit(self, doc):
        super().edit(doc)
        self.deleted = True


class FilletDeleteBaseArcBox(FilletDeleteBaseArc):
    block = FilletDeleteBaseBox.block


class FilletDeleteBaseArcPad(FilletDeleteBaseArc):
    block = FilletDeleteBasePad.block


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
    naming refresh rewrites the chamfer's Base (Edge10 -> Edge22, the same edge). BaseFeature must
    stay on the boss: DressUp::onChanged used to set it to Base's object, the pad, and the boss
    dropped out of the model with the chamfer valid (ops#82). Found by the randomized sequences
    (seed 194). V1 can't build the model: its chamfer breaks at the insert."""

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


class ChamferTangentToHoleResized(Scenario):
    """A block 0..20 x 0..20, 10 high; a hole through it at (10, 3), radius 2; a chamfer of size 1
    on the block's top front edge, whose inner edge on the top face (y = 1) is tangent to the
    hole; a sketch attached to the chamfer's top face. The hole's radius then goes 2 -> 1.5. OCCT's
    chamfer is invalid at the tangency and the dress-up repairs it; the repair named every element
    anew (`MAK`), so the sketch's reference to the top face went missing once the tangency went
    away: V2 kept it by index, V2s broke it. Found by the randomized sequences (seed 290, gap 1,
    ops#168). The repair now keeps the names of the elements it didn't change."""

    area = "dress-ups"
    MULTI = True
    REFS = ("sketch_top",)
    KIND = "Chamfer"

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 20), body)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "HoleSketch", [m.circle(10, 3, 2)], body, z=10)
        hole = m.pocketThroughAll(body, sketch, "Hole")
        doc.recompute()
        dress = body.newObject("PartDesign::" + self.KIND, self.KIND)
        dress.Base = (hole, self.names(hole, edge("line", direction=X, through=(0, 0, 10))))
        if self.KIND == "Fillet":
            dress.Radius = 1
        else:
            dress.Size = 1
        doc.recompute()
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(dress, self.names(dress, self.topFace())[0])]
        onTop.MapMode = "FlatFace"
        self.ref("sketch_top", onTop, "AttachmentSupport", self.topFace, Attached())

    def edit(self, doc):
        geometry = doc.HoleSketch.Geometry
        geometry[0].Radius = 1.5
        doc.HoleSketch.Geometry = geometry


class FilletTangentToHoleResized(ChamferTangentToHoleResized):
    """As ChamferTangentToHoleResized, with a fillet of radius 1 (the same repair, ops#12)."""

    KIND = "Fillet"


# Missing faces (ops#60, ops#65): a draft or a defeaturing loses one of its faces. The feature
# should fail, whatever the face's place in Base; it used to skip a missing face ("?Face3")
# and stay valid without it.


class DraftSomeFacesRemoved(Scenario):
    """A block 0..20 x 0..10 x 0..10 with a slot (x 14..16, y 4..6) through it; a draft, 5
    degrees, of the left face (x = 0) and the right face (x = 20) on the bottom face, listed in
    that order. The slot becomes a step along the whole right side (x 18..21, y -1..11): the
    right face is gone, the left one stays, and the draft should fail. It used to draft the
    left face alone (ops#60). With the reference solver it drafts the left face with a warning
    (ops#127, the user's decision 4: Onshape's rule)."""

    area = "dress-ups"
    MULTI = True
    REFS = ("draft_faces",)
    gone = False

    def sideFaces(self):
        def side(f):
            n = faceNormal(f)
            x = f.Surface.Position.x
            return abs(n.y) < 1e-9 and abs(n.z) < 1e-9 and min(abs(x), abs(x - 20)) < 1e-9

        if self.gone:
            return PartialWarned(self.leftFace()) if self.solver else BROKEN
        return pieces(face("plane", where=side))

    def leftFace(self):
        return face("plane", normal=-X, through=(0, 0, 0))

    def rightFace(self):
        return face("plane", normal=X, through=(20, 0, 0))

    def bottomFace(self):
        return face("plane", normal=-Z, through=(0, 0, 0))

    def order(self, slot):
        return self.names(slot, self.leftFace()) + self.names(slot, self.rightFace())

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "SlotSketch", m.rectangle(14, 4, 16, 6), body, z=10)
        slot = m.pocketThroughAll(body, sketch, "Slot")
        doc.recompute()
        draft = body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (slot, self.order(slot))
        draft.NeutralPlane = (slot, self.names(slot, self.bottomFace()))
        draft.Angle = 5
        self.ref("draft_faces", draft, "Base", self.sideFaces, Drafted(5, self.bottomFace))

    def edit(self, doc):
        m.moveRectangle(doc.SlotSketch, 18, -1, 21, 11)
        self.gone = True


class DraftSomeFacesRemovedFirst(DraftSomeFacesRemoved):
    """As DraftSomeFacesRemoved, with the faces listed right, then left: the missing face comes
    first. The draft used to fail naming the wrong face (ops#65)."""

    def order(self, slot):
        return self.names(slot, self.rightFace()) + self.names(slot, self.leftFace())


class DefeaturingFacesRemoved(Scenario):
    """A block 0..20 x 0..10 x 0..10 with two holes through it, radius 2, at (5, 5) and (15, 5),
    from one sketch; a defeaturing of the second hole's wall. The second circle is then deleted:
    the wall is gone, and the defeaturing should fail. It used to pass its base through
    unchanged (ops#60)."""

    area = "dress-ups"
    MULTI = True
    REFS = ("defeatured_faces",)
    gone = False

    def walls(self):
        return BROKEN if self.gone else pieces(self.removed())

    def removed(self):
        return face("cylinder", contains=(17, 5, 5))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "HoleSketch", [m.circle(5, 5, 2), m.circle(15, 5, 2)], body, z=10)
        holes = m.pocketThroughAll(body, sketch, "Holes")
        doc.recompute()
        defeaturing = body.newObject("PartDesign::Defeaturing", "Defeaturing")
        defeaturing.Base = (holes, self.removed().select(holes.Shape))
        self.ref("defeatured_faces", defeaturing, "Base", self.walls, Defeatured())

    def edit(self, doc):
        doc.HoleSketch.delGeometry(1)
        self.gone = True


class DefeaturingSomeFacesRemoved(DefeaturingFacesRemoved):
    """As DefeaturingFacesRemoved, with both holes' walls defeatured: after the edit the first
    wall stays, and the defeaturing should still fail. It used to fill the first hole alone
    (ops#60). With the reference solver it fills the first hole with a warning (ops#127)."""

    def removed(self):
        return face("cylinder")

    def walls(self):
        if self.gone and self.solver:
            return PartialWarned(pieces(self.removed()))
        return super().walls()


class FilletEdgesDeleteNearStep(Scenario):
    """FilletDeleteNearStep's model, the fillet on two edges: the step's front vertical edge
    (x = 20.5) and the block's front top edge (x 0..20). The step is deleted. Its edge is gone;
    the block's corner edge, 0.5 mm away, is within G2's wide reach but of another source (the
    block's sketch, not the step's): policy D doesn't guess it (N3's N11) and lists it for that
    sub. In solver documents the fillet computes on the front top edge with a warning (Onshape's
    partial rule, C10); without the solver it fails."""

    area = "dress-ups"
    REFS = ("fillet_edges",)
    deleted = False

    def stepEdge(self):
        return edge("line", direction=Z, through=(20.5, 0, 0))

    def frontTopEdge(self):
        return edge("line", direction=X, contains=(10, 0, 10))

    def filletEdges(self):
        if self.deleted:
            return PartialWarned(self.frontTopEdge()) if self.solver else BROKEN
        step, top = self.stepEdge(), self.frontTopEdge()
        return pieces(edge(where=lambda e: step.matches(e, 1e-7) or top.matches(e, 1e-7)))

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        stepSketch = m.sketch(doc, "StepSketch", m.rectangle(20, 0, 20.5, 10), body)
        step = m.pad(body, stepSketch, 10, name="Step")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (step, self.filletEdges().select(step.Shape))
        fillet.Radius = 0.25
        self.ref("fillet_edges", fillet, "Base", self.filletEdges, Filleted(0.25))

    def edit(self, doc):
        self.bodyObject.removeObject(doc.Step)
        doc.removeObject("Step")
        self.deleted = True


class StepDeletedFacesMerge(Scenario):
    """A block (0..20 x 0..10 x 0..10); a step, 0.5 high, padded on the back half of its top
    (y 5..10), which leaves the front half (y 0..5) as a piece of the block's top face; a
    thickness, 1 inward, with that piece as its open face. The step is deleted (its Base goes
    to the block, as FilletDeleteNearStep's): the top is one face again, the front half's
    ancestor (C3, N3 6.1). The whole top's centre is 2.5 mm from the saved one, beyond every
    guess's reach. The run (ops#127 P8a): in V2, with or without the solver, pass 1's exact
    lookup gives the whole top (no solver tier runs), so the reference follows the merge,
    `correct`; V1 breaks it."""

    area = "dress-ups"
    REFS = ("thickness_face",)
    deleted = False

    def topFace(self):
        if not self.deleted:
            return face("plane", normal=Z, through=(0, 0, 10), contains=(10, 2.5, 10))
        return BROKEN if self.mode == "V1" else face("plane", normal=Z, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        stepSketch = m.sketch(doc, "StepSketch", m.rectangle(0, 5, 20, 10), body, z=10)
        step = m.pad(body, stepSketch, 0.5, name="Step")
        doc.recompute()
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (step, self.names(step, self.topFace()))
        thickness.Value = 1
        thickness.Reversed = True
        self.ref("thickness_face", thickness, "Base", self.topFace)

    def edit(self, doc):
        self.bodyObject.removeObject(doc.Step)
        doc.removeObject("Step")
        self.deleted = True


class StepTopSplitByGrooveDeleted(Scenario):
    """The Fable review of fork PR 122, finding 1 (G1 and a deleted feature's split piece): a
    block (0..20 x 0..10 x 0..10); a step, 0.5 high, padded on its whole top; a groove (x 9..11,
    across) pocketed 2 deep from the step's top, which splits the step's top into two pieces and
    cuts 1.5 into the block; a thickness, 1 inward, with the left piece (x 0..9) as its open
    face. The step is deleted (the groove's Base goes to the block): the piece is gone. The
    block's left top piece, which the groove also made, lies 0.5 mm below the saved one, within
    the guess rules' wide reach and of another source (the block's sketch). Policy D: no guess;
    the reference breaks. Without the solver it breaks. The run (ops#127 P8b): G1 doesn't fire.
    The piece's structural survivors are the groove's floor and left wall only (the piece's name
    holds the groove's edges as connected elements; the block's pieces don't descend from it),
    so the block's piece is never a candidate. Tier 2 keeps the floor alone, 5.9 mm away, and a
    tier-1 partner must agree with the old name's top section or hold it in its ancestry, which
    the floor doesn't: the reference breaks (`no top agreement`), listing the floor and the
    wall."""

    area = "dress-ups"
    REFS = ("thickness_face",)
    deleted = False

    def leftPiece(self, z):
        return face("plane", normal=Z, through=(0, 0, z), contains=(4.5, 5, z))

    def topFace(self):
        if not self.deleted:
            return self.leftPiece(10.5)
        return Broken(self.leftPiece(10)) if self.solver else BROKEN

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        stepSketch = m.sketch(doc, "StepSketch", m.rectangle(0, 0, 20, 10), body, z=10)
        m.pad(body, stepSketch, 0.5, name="Step")
        grooveSketch = m.sketch(doc, "GrooveSketch", m.rectangle(9, -1, 11, 11), body, z=10.5)
        groove = m.pocket(body, grooveSketch, 2, name="Groove")
        doc.recompute()
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (groove, self.names(groove, self.topFace()))
        thickness.Value = 1
        thickness.Reversed = True
        self.ref("thickness_face", thickness, "Base", self.topFace)

    def edit(self, doc):
        self.bodyObject.removeObject(doc.Step)
        doc.removeObject("Step")
        self.deleted = True


class StepNarrowPieceGrooveDeleted(Scenario):
    """StepTopSplitByGrooveDeleted with the groove's floor in the wide reach: a block (0..40 x
    0..10 x 0..10); a step, 0.5 high, on its whole top; a groove (x 1.5..3, across) 0.75 deep
    from the step's top, which leaves a narrow left piece (x 0..1.5) of the step's top and cuts
    0.25 into the block; a sketch attached to that piece. The step is deleted: the piece is
    gone. The groove's floor (z = 9.75) is a structural survivor of the piece (the piece's name
    holds the groove's edges as connected elements), parallel, of the same area, and 1.68 mm
    from the saved centre, within the wide reach (2.12 mm) with no rival: G1's ground. It is of
    another source (the groove's sketch, not the step's): policy D doesn't guess it, and the
    reference breaks with the floor listed. Without the solver it breaks. The run (ops#127 P8b):
    G1 doesn't fire here either. It runs only when tier 2 keeps two or more structural
    survivors; the floor is the only one that agrees (the wall is vertical), so tier 2 takes it,
    and the top-agreement check breaks the reference (`no top agreement`), as in
    StepTopSplitByGrooveDeleted."""

    area = "dress-ups"
    REFS = ("piece_support",)
    deleted = False

    def floor(self):
        return face("plane", normal=Z, through=(0, 0, 9.75), contains=(2.25, 5, 9.75))

    def piece(self):
        if not self.deleted:
            return face("plane", normal=Z, through=(0, 0, 10.5), contains=(0.75, 5, 10.5))
        return Broken(self.floor()) if self.solver else BROKEN

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 40, 10), body)
        m.pad(body, profile, 10)
        stepSketch = m.sketch(doc, "StepSketch", m.rectangle(0, 0, 40, 10), body, z=10)
        m.pad(body, stepSketch, 0.5, name="Step")
        grooveSketch = m.sketch(doc, "GrooveSketch", m.rectangle(1.5, -1, 3, 11), body, z=10.5)
        groove = m.pocket(body, grooveSketch, 0.75, name="Groove")
        doc.recompute()
        marker = body.newObject("Sketcher::SketchObject", "Marker")
        marker.AttachmentSupport = [(groove, self.names(groove, self.piece())[0])]
        marker.MapMode = "FlatFace"
        self.ref("piece_support", marker, "AttachmentSupport", self.piece, Attached())

    def edit(self, doc):
        self.bodyObject.removeObject(doc.Step)
        doc.removeObject("Step")
        self.deleted = True
