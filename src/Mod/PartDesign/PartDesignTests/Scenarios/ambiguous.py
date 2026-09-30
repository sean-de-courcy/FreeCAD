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

"""Deliberately ambiguous cases: the referenced element is split into equal halves, or deleted
while an identical twin stays. Nothing tells the candidates apart, so a consumer that needs one
element should break; one for which the candidates are equivalent (an attachment to coplanar
halves) may take either."""

from .harness import Attached, Broken, Filleted, Scenario, X, Z, edge, face, pieces
from . import models as m


class AmbiguousHalves(Scenario):
    """A block 0..20 x 0..10 x 0..10 (a pad) with a blind hole (x 16..18, y 2..4, 4 deep) in its
    top; a sketch attached to the top face, and a datum point at the top face's centre of mass.
    The hole becomes a groove across the middle (x 9..11): the top face splits into two equal
    halves. The sketch lies on either half; the point has no right half to go to."""

    area = "ambiguous"
    REFS = ("sketch_top", "point_top")
    halves = False

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def leftHalf(self):
        return face("plane", normal=Z, through=(0, 0, 10), contains=(2, 5, 10))

    def pointFace(self):
        return Broken(pieces(self.topFace())) if self.halves else self.topFace()

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "GrooveSketch", m.rectangle(16, 2, 18, 4), body, z=10)
        groove = m.pocket(body, sketch, 4, "Groove")
        doc.recompute()
        top = self.names(groove, self.topFace())[0]
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(groove, top)]
        onTop.MapMode = "FlatFace"
        point = body.newObject("PartDesign::Point", "Centre")
        point.AttachmentSupport = [(groove, top)]
        point.MapMode = "CenterOfMass"
        self.ref("sketch_top", onTop, "AttachmentSupport", self.leftHalf, Attached())
        self.ref("point_top", point, "AttachmentSupport", self.pointFace, Attached())

    def edit(self, doc):
        m.moveRectangle(doc.GrooveSketch, 9, -1, 11, 11)
        self.halves = True


class TwinBosses(Scenario):
    """A plate 0..40 x 0..10 x 0..5; one sketch with two equal squares, boss A (x 5..15) and
    boss B (x 25..35), both y 2..8, padded 5 on the plate. A sketch attached to B's top face, and
    a fillet, radius 0.5, on B's front top edge."""

    abstract = True
    area = "ambiguous"
    MULTI = True
    REFS = ("sketch_top_b", "fillet_edge_b")
    deleted = None

    def topB(self):
        if self.deleted == "B":
            return Broken()
        return face("plane", normal=Z, through=(0, 0, 10), contains=(30, 5, 10))

    def frontTopEdgeB(self):
        if self.deleted == "B":
            return Broken()
        return edge("line", direction=X, through=(0, 2, 10), contains=(30, 2, 10))

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        plate = m.sketch(doc, "Plate", m.rectangle(0, 0, 40, 10), body)
        m.pad(body, plate, 5, name="PlatePad")
        squares = m.rectangle(5, 2, 15, 8) + m.rectangle(25, 2, 35, 8)
        bosses = m.pad(body, m.sketch(doc, "Bosses", squares, body, z=5), 5, name="BossPad")
        doc.recompute()
        onTop = body.newObject("Sketcher::SketchObject", "OnTopB")
        onTop.AttachmentSupport = [(bosses, self.names(bosses, self.topB())[0])]
        onTop.MapMode = "FlatFace"
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (bosses, self.names(bosses, self.frontTopEdgeB()))
        fillet.Radius = 0.5
        self.ref("sketch_top_b", onTop, "AttachmentSupport", self.topB, Attached())
        self.ref("fillet_edge_b", fillet, "Base", self.frontTopEdgeB, Filleted(0.5))


class TwinDeleteB(TwinBosses):
    """Boss B's square is deleted: both references should break, not move to boss A."""

    def edit(self, doc):
        doc.Bosses.delGeometries([4, 5, 6, 7])
        self.deleted = "B"


class TwinDeleteA(TwinBosses):
    """Boss A's square is deleted (B's lines become geometry 0..3, their IDs unchanged): both
    references stay on boss B."""

    def edit(self, doc):
        doc.Bosses.delGeometries([0, 1, 2, 3])
        self.deleted = "A"
