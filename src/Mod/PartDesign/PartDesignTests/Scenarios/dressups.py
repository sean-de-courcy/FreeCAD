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

from .harness import Chamfered, Drafted, Filleted, Scenario, X, Y, Z, edge, face
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
