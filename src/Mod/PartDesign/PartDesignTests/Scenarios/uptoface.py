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

"""UpToFace: a Pad up to a face of an earlier feature keeps reaching that face when the
features before it change."""

from .harness import ReachesFace, Scenario, Z, face
from . import models as m


class UpToFaceEdit(Scenario):
    """A rectangle (0..20 x 0..10) padded 10 high, with a hole (x = 10, radius 2) through it;
    a second pad next to it (20..30 x 0..10) from z = 0 up to the hole feature's top face."""

    abstract = True
    area = "UpToFace"
    REFS = ("pad_up_to_top",)
    height = 10

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.height))

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        holeSketch = m.sketch(doc, "HoleSketch", [m.circle(10, 5, 2)], body, z=10)
        hole = m.pocketThroughAll(body, holeSketch, "Hole")
        doc.recompute()
        sideSketch = m.sketch(doc, "SideProfile", m.rectangle(20, 0, 30, 10), body)
        side = m.pad(body, sideSketch, 1, name="SidePad")
        side.Type = "UpToFace"
        side.UpToFace = (hole, self.names(hole, self.topFace()))
        self.ref("pad_up_to_top", side, "UpToFace", self.topFace, ReachesFace())


class UpToFaceLength(UpToFaceEdit):
    """The first pad gets longer: 10 -> 14."""

    def edit(self, doc):
        doc.Pad.Length = 14
        self.height = 14


class UpToFaceInsert(UpToFaceEdit):
    """A slot (x 2..6, y 2..8) through the first pad is inserted before the hole, which
    renumbers the hole feature's faces."""

    def edit(self, doc):
        body = self.bodyObject
        body.Tip = doc.Pad
        sketch = m.sketch(doc, "SlotSketch", m.rectangle(2, 2, 6, 8), body, z=10)
        m.pocketThroughAll(body, sketch, "Slot")
        body.Tip = doc.SidePad
