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

"""The document switch InternNames turned over on a built model (ops#6, Task 1): every feature is
named again in the other form, and the references, which hold names in the old form, must still
find their elements."""

from .harness import Attached, ExternalCoincides, Filleted, Scenario, X, edge, face
from . import models as m


class InternSwitch(Scenario):
    """A pad (0..20 x 0..10 x 0..10) with a hole through it (x = 10, radius 2), a fillet of its
    front top edge (radius 1), a sketch attached to the fillet's right face, and a sketch on the
    XY plane with the fillet's back bottom edge as external geometry (its Ref and its link's
    shadow must stay in one form, ops#97). Step 1 turns the document's InternNames over (on in
    V2, V2multi and V2s; off in V2i); step 2 makes the pad longer (10 -> 15) in the new form;
    step 3 turns the switch back."""

    area = "interning"
    MULTI = True
    REFS = ("fillet_edge", "sketch_right_face", "external_back_edge")
    steps = ("turnOver", "longer", "turnBack")
    height = 10

    def frontTopEdge(self):
        return edge("line", direction=X, through=(0, 0, self.height))

    def rightFace(self):
        return face("plane", normal=X, through=(20, 0, 0))

    def backBottomEdge(self):
        return edge("line", direction=X, through=(0, 10, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, self.height)
        hole = m.sketch(doc, "HoleSketch", [m.circle(10, 5, 2)], body, z=self.height)
        pocket = m.pocketThroughAll(body, hole, "Hole")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, self.frontTopEdge()))
        fillet.Radius = 1
        doc.recompute()
        onSide = body.newObject("Sketcher::SketchObject", "OnSide")
        onSide.AttachmentSupport = [(fillet, self.names(fillet, self.rightFace())[0])]
        onSide.MapMode = "FlatFace"
        self.ref("fillet_edge", fillet, "Base", self.frontTopEdge, Filleted(1))
        self.ref("sketch_right_face", onSide, "AttachmentSupport", self.rightFace, Attached())
        onBottom = m.sketch(doc, "OnBottom", [], body)
        onBottom.addExternal(fillet.Name, self.names(fillet, self.backBottomEdge())[0])
        self.ref(
            "external_back_edge",
            onBottom,
            "ExternalGeometry",
            self.backBottomEdge,
            ExternalCoincides(),
        )

    def turnOver(self, doc):
        doc.InternNames = not doc.InternNames

    def longer(self, doc):
        doc.Pad.Length = 15
        self.height = 15

    def turnBack(self, doc):
        doc.InternNames = not doc.InternNames
