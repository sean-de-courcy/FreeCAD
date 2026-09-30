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

"""Attachment to moving faces: a sketch and a datum plane follow the faces they are attached
to when the pad under them changes."""

from .harness import Attached, Scenario, X, Z, face
from . import models as m


class AttachmentEdit(Scenario):
    """A rectangle (0..20 x 0..10) padded 10 high; a sketch attached to the right face and a
    datum plane attached to the top face."""

    abstract = True
    area = "attachment"
    REFS = ("sketch_right_face", "datum_top_face")
    x0, y0, width, depth, height = 0, 0, 20, 10, 10

    def rightFace(self):
        return face("plane", normal=X, through=(self.x0 + self.width, 0, 0))

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.height))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        onSide = body.newObject("Sketcher::SketchObject", "OnSide")
        onSide.AttachmentSupport = [(pad, self.names(pad, self.rightFace())[0])]
        onSide.MapMode = "FlatFace"
        plane = body.newObject("PartDesign::Plane", "TopPlane")
        plane.AttachmentSupport = [(pad, self.names(pad, self.topFace())[0])]
        plane.MapMode = "FlatFace"
        self.ref("sketch_right_face", onSide, "AttachmentSupport", self.rightFace, Attached())
        self.ref("datum_top_face", plane, "AttachmentSupport", self.topFace, Attached())


class AttachLength(AttachmentEdit):
    """The pad gets longer: 10 -> 15."""

    def edit(self, doc):
        doc.Pad.Length = 15
        self.height = 15


class AttachWidth(AttachmentEdit):
    """The right side moves from x = 20 to x = 26; its line keeps its geometry ID."""

    def edit(self, doc):
        lines = {0: ((0, 0), (26, 0)), 1: ((26, 0), (26, 10)), 2: ((26, 10), (0, 10))}
        m.setLines(doc.Profile, lines)
        self.width = 26


class AttachMove(AttachmentEdit):
    """The whole rectangle moves by (5, 3); every line keeps its geometry ID."""

    def edit(self, doc):
        corners = [(5, 3), (25, 3), (25, 13), (5, 13)]
        m.setLines(doc.Profile, {i: (corners[i], corners[(i + 1) % 4]) for i in range(4)})
        self.x0, self.y0 = 5, 3
