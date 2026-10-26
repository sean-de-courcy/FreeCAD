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

"""Corpus cases (ops#503, class D): a rim board redrawn in a metre-scale floor frame.

Two rim boards 45 x 235 mm, 3600 long, 4 m apart; a joist 45 x 4000 between them with a notch
in its top, patterned 9 times at 400 mm; a chamfer on the first rim's front top edge. The rim's
rectangle is deleted and drawn again (new geometry IDs): in place, and 3000 long from the same
corner (the edge's centre moves 300 mm, more than the solver's reach by distance at 1 % of the
diagonal). Ported from `work/394/probe_joists.py` and the `redraw a rim` edit of
`scripts/warning_load/m_joists.py` (`corpus/predicted/D.json`: joists, m_joists)."""

from PartDesignTests.Scenarios.harness import Chamfered, Scenario, X, Z, edge, face
from PartDesignTests.Scenarios import models as m

DEPTH = 235  # the rims' height


class JoistRimRedrawn(Scenario):
    """The frame, and the redraw of the first rim's rectangle."""

    abstract = True
    area = "joist-frame"
    CLASSES = ("D",)
    AXES = ("M2", "E3", "X4:3600")
    ISSUE = "ops#503"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("rim_chamfer",)
    length = 3600  # the first rim's length now
    chamferFirst = False  # the chamfer directly after the rims, not after the pattern

    def frontTopEdge(self):
        return edge("line", direction=X, through=(0, 0, DEPTH))

    def build(self, doc):
        body = m.body(doc)
        self.rims = m.sketch(
            doc,
            "RimSketch",
            m.rectangle(0, 0, 3600, 45) + m.rectangle(0, 4045, 3600, 4090),
            body,
        )
        rims = m.pad(body, self.rims, DEPTH, "Rims")
        doc.recompute()
        chamfer = None
        if self.chamferFirst:
            chamfer = self.chamfer(body, rims, "RimChamfer")
        joist = m.sketch(doc, "JoistSketch", m.rectangle(0, 45, 45, 4045), body)
        joistPad = m.pad(body, joist, DEPTH, "Joist")
        joistPad.setExpression("Length", "Rims.Length")
        doc.recompute()
        notchSketch = body.newObject("Sketcher::SketchObject", "NotchSketch")
        notchSketch.AttachmentSupport = [
            (joistPad, self.names(joistPad, face("plane", normal=Z, contains=(22.5, 2000, DEPTH)))[0])
        ]
        notchSketch.MapMode = "FlatFace"
        doc.recompute()
        notchSketch.addGeometry(m.rectangle(0, 1950, 45, 2050), False)
        notch = m.pocket(body, notchSketch, 38, "Notch")
        doc.recompute()
        if abs(notch.Shape.Volume - joistPad.Shape.Volume) < 1:
            notch.Reversed = True
            doc.recompute()
        pattern = body.newObject("PartDesign::LinearPattern", "JoistRow")
        pattern.Originals = [joistPad, notch]
        pattern.Direction = (m.originFeature(body, "X_Axis"), [""])
        pattern.Mode = "Spacing"
        pattern.Offset = 400
        pattern.Occurrences = 9
        body.Tip = pattern
        doc.recompute()
        if not self.chamferFirst:
            chamfer = self.chamfer(body, pattern, "RimChamfer")
        self.ref(
            "rim_chamfer", chamfer, "Base", self.frontTopEdge, Chamfered(5)
        )

    def chamfer(self, body, base, name):
        chamfer = body.newObject("PartDesign::Chamfer", name)
        chamfer.Base = (base, self.names(base, self.frontTopEdge()))
        chamfer.Size = 5
        body.Tip = chamfer
        self.doc.recompute()
        return chamfer

    def redraw(self, length):
        """The first rim's four lines deleted and drawn again, as a user does."""
        for geoId in (3, 2, 1, 0):
            self.rims.delGeometry(geoId)
        self.rims.addGeometry(m.rectangle(0, 0, length, 45), False)
        self.length = length


class JoistRimRedrawnInPlace(JoistRimRedrawn):
    """The chamfered rim is drawn again at the same place; the chamfer is after the pattern."""

    def edit(self, doc):
        self.redraw(3600)


class JoistRimRedrawnInPlaceBeforeJoists(JoistRimRedrawn):
    """As JoistRimRedrawnInPlace with the chamfer directly after the rims' pad."""

    chamferFirst = True

    def edit(self, doc):
        self.redraw(3600)


class JoistRimRedrawnShorter(JoistRimRedrawn):
    """The rim is drawn again 3000 long from the same corner: the chamfered edge is now the
    shorter one at the same line, its centre 300 mm from the old one."""

    def edit(self, doc):
        self.redraw(3000)
