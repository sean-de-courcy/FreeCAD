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

"""Splits under each consumer (the naming design's section 8, approved 2026-09-30): an element a
consumer references is split in two by an edit of the feature it belongs to. Dress-ups and a
profile given as faces should take every piece; an attachment takes one piece of a split face
when the pieces are coplanar (correct or equivalent). Sketch external geometry is in
`external.py`.

Each model is a block 0..20 x 0..10 x 0..10 (a pad) and a cutter, a pocket or a pad, that first
sits where it touches nothing referenced and is then moved across the referenced element. The
consumers reference the cutter's shape, so the split happens in the feature they link to."""

import os
import shutil
import tempfile

import FreeCAD as App

from .harness import (
    BROKEN,
    Attached,
    Broken,
    Chamfered,
    Drafted,
    Extruded,
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


class SplitModel(Scenario):
    abstract = True
    area = "splits"
    MULTI = True
    width, depth, height = 20, 10, 10

    def block(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.width, self.depth), body)
        m.pad(body, profile, self.height)
        return body

    def frontTopEdge(self):
        return pieces(edge("line", direction=X, through=(0, 0, self.height)))


class SplitFilletFuse(SplitModel):
    """A rib (a pad of x 8..12, y 3..7, 12 high) stands on the block; a fillet, radius 1, on the
    block's front top edge. The rib moves to y -3..3: it is fused across the edge, which splits
    into x 0..8 and x 12..20."""

    REFS = ("fillet_edge",)

    def build(self, doc):
        body = self.block(doc)
        sketch = m.sketch(doc, "RibSketch", m.rectangle(8, 3, 12, 7), body)
        rib = m.pad(body, sketch, 12, name="Rib")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, self.names(rib, self.frontTopEdge().predicate))
        fillet.Radius = 1
        self.ref("fillet_edge", fillet, "Base", self.frontTopEdge, Filleted(1))

    def edit(self, doc):
        m.moveRectangle(doc.RibSketch, 8, -3, 12, 3)


class SplitChamferCut(SplitModel):
    """A slot (x 8..12, y 4..6) through the block; a chamfer, size 1, on the block's front top
    edge. The slot moves to y -1..3: it removes the edge's middle, which splits into x 0..8 and
    x 12..20."""

    REFS = ("chamfer_edge",)

    def build(self, doc):
        body = self.block(doc)
        sketch = m.sketch(doc, "SlotSketch", m.rectangle(8, 4, 12, 6), body, z=self.height)
        slot = m.pocketThroughAll(body, sketch, "Slot")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (slot, self.names(slot, self.frontTopEdge().predicate))
        chamfer.Size = 1
        self.ref("chamfer_edge", chamfer, "Base", self.frontTopEdge, Chamfered(1))

    def edit(self, doc):
        m.moveRectangle(doc.SlotSketch, 8, -1, 12, 3)


class SplitDraftGroove(SplitModel):
    """A slot (x 14..16, y 4..6) through the block; a draft, 5 degrees, of the right face (x = 20)
    on the bottom face. The slot moves to x 17..21: a groove down the right face, which splits
    into y 0..4 and y 6..10."""

    REFS = ("draft_face",)

    def rightFace(self):
        return pieces(face("plane", normal=X, through=(self.width, 0, 0)))

    def bottomFace(self):
        return face("plane", normal=-Z, through=(0, 0, 0))

    def build(self, doc):
        body = self.block(doc)
        sketch = m.sketch(doc, "SlotSketch", m.rectangle(14, 4, 16, 6), body, z=self.height)
        slot = m.pocketThroughAll(body, sketch, "Slot")
        doc.recompute()
        draft = body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (slot, self.names(slot, self.rightFace().predicate))
        draft.NeutralPlane = (slot, self.names(slot, self.bottomFace()))
        draft.Angle = 5
        self.ref("draft_face", draft, "Base", self.rightFace, Drafted(5, self.bottomFace))

    def edit(self, doc):
        m.moveRectangle(doc.SlotSketch, 17, 4, 21, 6)


class SplitTopGroove(SplitModel):
    """A blind hole (x 16..18, y 2..4, 4 deep) in the block's top; a pad, 3 high, whose profile
    is the top face; a sketch attached to the top face. The hole becomes a groove across the top
    (x 12..14, y -1..11): the top face splits into x 0..12 and x 14..20. The pad should pad both
    pieces, and the sketch lies on either (they are coplanar)."""

    REFS = ("pad_profile", "sketch_top")

    def topFace(self):
        return pieces(face("plane", normal=Z, through=(0, 0, self.height)))

    def topLeftPiece(self):
        return face("plane", normal=Z, through=(0, 0, self.height), contains=(2, 5, self.height))

    def build(self, doc):
        body = self.block(doc)
        sketch = m.sketch(doc, "GrooveSketch", m.rectangle(16, 2, 18, 4), body, z=self.height)
        groove = m.pocket(body, sketch, 4, "Groove")
        doc.recompute()
        top = self.names(groove, self.topFace().predicate)
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(groove, top[0])]
        onTop.MapMode = "FlatFace"
        pad = body.newObject("PartDesign::Pad", "PadTop")
        pad.Profile = (groove, top)
        pad.Length = 3
        self.ref("pad_profile", pad, "Profile", self.topFace, Extruded(3, Z))
        self.ref("sketch_top", onTop, "AttachmentSupport", self.topLeftPiece, Attached())

    def edit(self, doc):
        m.moveRectangle(doc.GrooveSketch, 12, -1, 14, 11)


class SplitFilletNotch(SplitModel):
    """A fillet, radius 1, on the block's front top edge; a notch (x 8..12, 2 deep) is then cut
    into the front side of the block's sketch, as in SketchNotch: the front line ends at x = 8,
    and four lines are added, the last one the rest of the side (x 12..20, a new geometry). The
    edge splits into x 0..8 and x 12..20; the fillet should take both. Found by the randomized
    sequences (seed 6): the second piece comes from a new sketch line, so the multi-match flags
    don't find it either."""

    REFS = ("fillet_edge",)
    radius = 1

    def build(self, doc):
        body = self.block(doc)
        pad = doc.Pad
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.frontTopEdge().predicate))
        fillet.Radius = self.radius
        self.ref("fillet_edge", fillet, "Base", self.frontTopEdge, Filleted(self.radius))

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)


# Controls: the referenced element is removed, not split. The reference should break, loudly.


class ChamferEdgeRemoved(SplitChamferCut):
    """As SplitChamferCut, but the slot becomes a step along the whole front (x -1..21, y -1..3):
    the chamfered edge is gone, and the chamfer should fail."""

    area = "dress-ups"
    gone = False

    def frontTopEdge(self):
        return BROKEN if self.gone else super().frontTopEdge()

    def edit(self, doc):
        m.moveRectangle(doc.SlotSketch, -1, -1, 21, 3)
        self.gone = True


class DraftFaceRemoved(SplitDraftGroove):
    """As SplitDraftGroove, but the slot becomes a step along the whole right side (x 18..21,
    y -1..11): the drafted face is gone, and the draft should fail."""

    area = "dress-ups"
    gone = False

    def rightFace(self):
        return BROKEN if self.gone else super().rightFace()

    def edit(self, doc):
        m.moveRectangle(doc.SlotSketch, 18, -1, 21, 11)
        self.gone = True


# The reference solver's splits (ops#7, Task 2 PR 7): an expansion merged back, a notch's
# continuation, and edits the continuation must not take.


class SolverSplitThenMerge(SplitFilletFuse):
    """SplitFilletFuse in two steps. `split`: the rib moves across the filleted edge, and the
    fillet takes both pieces. `merge`: the rib moves back to y 3..7, the edge is whole again
    under its old name, and the pieces merge back into it: the fillet holds one reference."""

    steps = ("split", "merge")

    def split(self, doc):
        m.moveRectangle(doc.RibSketch, 8, -3, 12, 3)

    def merge(self, doc):
        m.moveRectangle(doc.RibSketch, 8, 3, 12, 7)


class SolverSplitThenMergeReopened(SolverSplitThenMerge):
    """As SolverSplitThenMerge, with the document saved, closed and opened again between the
    steps: the pieces keep the name they were expanded from (`from`) in the file."""

    steps = ("split", "reopen", "merge")

    def reopen(self, doc):
        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        path = os.path.join(self.folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        self.doc = App.openDocument(path)
        self.documents.append(self.doc.Name)
        for obj in self.doc.Objects:
            obj.touch()

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class SolverNotchThenFill(SplitFilletNotch):
    """SplitFilletNotch in two steps. `notch`: the fillet takes both pieces, the second (a new
    line's edge) as the continuation of the first. `fill`: the notch's four lines are deleted
    and the front line goes back to x 0..20: the edge is whole again, and the pieces merge back
    into it."""

    steps = ("notch", "fill")

    def notch(self, doc):
        self.edit(doc)

    def fill(self, doc):
        for geoId in reversed(range(4, doc.Profile.GeometryCount)):
            doc.Profile.delGeometry(geoId)
        m.setLines(doc.Profile, {0: ((0, 0), (20, 0))})


class SideMovedIn(SplitFilletNotch):
    """A fillet, radius 1, on the block's front top edge; the right side moves in to x = 16 (the
    front, right and back lines moved, their geometry IDs kept). The edge is shorter, and nothing
    lies on the rest of its old place: the fillet keeps the edge, 0..16."""

    def edit(self, doc):
        lines = {0: ((0, 0), (16, 0)), 1: ((16, 0), (16, 10)), 2: ((16, 10), (0, 10))}
        m.setLines(doc.Profile, lines)


class NotchStepOffset(SplitFilletNotch):
    """A fillet, radius 0.5, on the block's front top edge; the front line then ends at x = 8,
    and a step follows as new lines, (8, 0)-(8, 1)-(20, 1), with the right side from (20, 1).
    The edge at y = 1 is parallel to the old one but 1 mm off its line: never its continuation.
    The fillet keeps 0..8."""

    radius = 0.5

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0)), 1: ((20, 1), (20, 10))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 1), (20, 1)]), False)


class NotchAndExtend(SplitFilletNotch):
    """SplitFilletNotch's notch, with the right side moved out to x = 26: the rest of the side
    (x 12..26) runs past the old edge's end (x = 20), part continuation and part new. The
    reference breaks, with both edges as candidates: the fillet neither keeps 0..8 alone
    (partial) nor takes 12..26."""

    split = False

    def frontTopEdge(self):
        if self.split:
            return Broken(super().frontTopEdge())
        return super().frontTopEdge()

    def edit(self, doc):
        lines = {0: ((0, 0), (8, 0)), 1: ((26, 0), (26, 10)), 2: ((26, 10), (0, 10))}
        m.setLines(doc.Profile, lines)
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (26, 0)]), False)
        self.split = True


class DraftFaceNotch(SplitModel):
    """A draft, 5 degrees, of the block's front face (y = 0) on the bottom face; a notch (x 8..12,
    2 deep) is then cut into the front side of the block's sketch, as in SplitFilletNotch. The
    front face keeps its name on x 0..8, and the rest (x 12..20) comes from a new line, coplanar,
    beside the same top and bottom faces. A face's fingerprint doesn't bound its region, so the
    rest can't be told from a coplanar neighbour: the reference breaks with both as candidates
    (Q3 (b) of the PR 7 design), never keeps 0..8 alone (partial)."""

    REFS = ("draft_face",)
    split = False

    def frontFace(self):
        front = pieces(face("plane", normal=-Y, through=(0, 0, 0)))
        return Broken(front) if self.split else front

    def bottomFace(self):
        return face("plane", normal=-Z, through=(0, 0, 0))

    def build(self, doc):
        body = self.block(doc)
        pad = doc.Pad
        doc.recompute()
        draft = body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (pad, self.names(pad, self.frontFace().predicate))
        draft.NeutralPlane = (pad, self.names(pad, self.bottomFace()))
        draft.Angle = 5
        self.ref("draft_face", draft, "Base", self.frontFace, Drafted(5, self.bottomFace))

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)
        self.split = True


class SolverNotchRedrawn(SplitFilletNotch):
    """SplitFilletNotch in two steps. `notch`: the fillet takes both pieces. `redraw`: the side's
    rest (x 12..20) is drawn again as a new line and the old one deleted, so it gets a new
    geometry ID and its edge another name. The pieces must not merge back into the kept piece
    alone (a silent partial): the redrawn edge is found in its place (tier 3), and the fillet
    keeps both (the review of Task 2 PR 7, B1)."""

    steps = ("notch", "redraw")

    def notch(self, doc):
        self.edit(doc)

    def redraw(self, doc):
        last = doc.Profile.GeometryCount - 1  # the side's rest, (12, 0)-(20, 0)
        doc.Profile.addGeometry(m.polyline([(12, 0), (20, 0)]), False)
        doc.Profile.delGeometry(last)


class AttachFaceNotch(SplitModel):
    """A sketch attached (FlatFace) to the block's front face (y = 0); a notch (x 8..12, 2 deep)
    is then cut into the front side, as in SplitFilletNotch. The face keeps its name on x 0..8,
    and the rest (x 12..20) is coplanar: the sketch's placement is the same on either, so it
    keeps its face (Equivalent under the split face's rule)."""

    REFS = ("sketch_front",)

    def frontFace(self):
        return face("plane", normal=-Y, through=(0, 0, 0), contains=(2, 0, 5))

    def build(self, doc):
        body = self.block(doc)
        pad = doc.Pad
        doc.recompute()
        onFront = body.newObject("Sketcher::SketchObject", "OnFront")
        onFront.AttachmentSupport = [(pad, self.names(pad, self.frontFace())[0])]
        onFront.MapMode = "FlatFace"
        self.ref("sketch_front", onFront, "AttachmentSupport", self.frontFace, Attached())

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)


class DraftUProngNarrowed(SplitModel):
    """A U-shaped pad: the block 0..20 x 0..10, 10 high, with a slot (x 6..14, y 4..10) in its
    profile, so two prongs (x 0..6 and 14..20) end in coplanar faces at y = 10. A draft, 5
    degrees, of the left prong's end face on the bottom face; the left prong is then narrowed to
    x 0..4 (its lines keep their geometry IDs). The end face only shrinks, and the draft should
    keep it. The right prong's end face is coplanar and shares the top and bottom faces with it,
    so the split face's rule (Q3 (b) of the Task 2 PR 7 design) can't tell this from a split:
    V2s breaks the draft, a false break (broken, never wrong), listed for PR 8's gate."""

    REFS = ("draft_face",)

    def block(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        outline = [(0, 0), (20, 0), (20, 10), (14, 10), (14, 4), (6, 4), (6, 10), (0, 10)]
        profile = m.sketch(doc, "Profile", m.polygon(outline), body)
        m.pad(body, profile, self.height)
        return body

    def endFace(self):
        return face("plane", normal=Y, through=(0, 10, 0), contains=(2, 10, 5))

    def bottomFace(self):
        return face("plane", normal=-Z, through=(0, 0, 0))

    def build(self, doc):
        body = self.block(doc)
        pad = doc.Pad
        doc.recompute()
        draft = body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (pad, self.names(pad, self.endFace()))
        draft.NeutralPlane = (pad, self.names(pad, self.bottomFace()))
        draft.Angle = 5
        self.ref("draft_face", draft, "Base", self.endFace, Drafted(5, self.bottomFace))

    def edit(self, doc):
        m.setLines(doc.Profile, {4: ((14, 4), (4, 4)), 5: ((4, 4), (4, 10)), 6: ((4, 10), (0, 10))})


# Arcs (ops#7, Task 2 PR 7b): the continuation along a circle.


class SplitArcNotch(SplitModel):
    """A disc with two flats (centre (10, 5), radius 5, the chords y = 1 and y = 9) padded 10
    high; a fillet, radius 0.5, on its right arc's top edge. A notch is then cut into the right
    arc: the arc ends at -10 degrees (its geometry ID kept), lines go in to radius 3 and out, with
    a concentric arc of radius 3 as the notch's floor, and a new arc runs from 10 degrees to the
    old end. The fillet should take both outer pieces of the right arc (the second as the
    continuation of the first), never the notch's floor (concentric, another radius) nor the
    left arc (the same circle, beyond the old ends)."""

    REFS = ("fillet_edge",)
    radius = 0.5

    def block(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.twoFlatDisc(), body)
        m.pad(body, profile, self.height)
        return body

    def rightArcTop(self):
        return pieces(
            edge(
                center=(*m.DISC_CENTER, self.height),
                radius=m.DISC_RADIUS,
                where=lambda e: e.CenterOfMass.x > m.DISC_CENTER[0],
            )
        )

    def build(self, doc):
        body = self.block(doc)
        pad = doc.Pad
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.rightArcTop().predicate))
        fillet.Radius = self.radius
        self.ref("fillet_edge", fillet, "Base", self.rightArcTop, Filleted(self.radius))

    def edit(self, doc):
        m.notchDiscArc(doc.Profile)


class SolverArcNotchThenFill(SplitArcNotch):
    """SplitArcNotch in two steps. `notch`: the fillet takes both outer pieces. `fill`: the
    notch's geometries are deleted and the right arc is whole again: the pieces merge back into
    it."""

    steps = ("notch", "fill")

    def notch(self, doc):
        self.edit(doc)

    def fill(self, doc):
        m.fillDiscNotch(doc.Profile)
