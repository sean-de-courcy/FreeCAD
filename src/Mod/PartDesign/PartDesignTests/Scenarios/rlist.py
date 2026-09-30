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

"""Reproducers for the R-list in the ops repo's `notes/naming-v2.md` that are about references
(R7). The R-list items below the reference level (R3, R5, R10) are unit tests in
`TestNamingRList.py`."""

from .harness import Chamfered, Scenario, X, edge
from . import models as m


class ChamferEdgeShortened(Scenario):
    """A slot (x 8..12, y 4..6) through a block 0..20 x 0..10 x 0..10; a chamfer, size 1, on the
    front top edge. The slot moves to x 16..21, y -1..3: it cuts the edge's right end off, and
    the edge (now x 0..16) is modified. The control for R7EdgeReturns."""

    area = "R-list"
    MULTI = True
    REFS = ("chamfer_edge",)

    def frontTopEdge(self):
        return edge("line", direction=X, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "SlotSketch", m.rectangle(8, 4, 12, 6), body, z=10)
        slot = m.pocketThroughAll(body, sketch, "Slot")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (slot, self.names(slot, self.frontTopEdge()))
        chamfer.Size = 1
        self.ref("chamfer_edge", chamfer, "Base", self.frontTopEdge, Chamfered(1))

    def edit(self, doc):
        m.moveRectangle(doc.SlotSketch, 16, -1, 21, 3)


class R7EdgeReturns(ChamferEdgeShortened):
    """R7, "a missing reference is never retried": as ChamferEdgeShortened, but on the way the
    slot first becomes a step along the whole front (x -1..21, y -1..3), which removes the edge,
    and the model is recomputed (the chamfer fails, its Base becomes ?Edge). When the slot then
    moves to x 16..21, the edge is back and the chamfer should find it again. The shortened edge
    keeps its old name (a one-to-one modification does), so this checks recovery by the exact
    name; the matcher's retry isn't reached."""

    def edit(self, doc):
        m.moveRectangle(doc.SlotSketch, -1, -1, 21, 3)
        doc.recompute()
        super().edit(doc)
