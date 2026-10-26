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

"""Corpus cases (ops#503, class D): the top rim of a hole when the pad is tapered.

A pad 20 x 10 x 5 and a through pocket of a circle of radius 2 centred on the front edge (10, 0),
in a sketch on the top face; a fillet of radius 0.3 on the hole's top rim arc. The pad's taper
angle goes to 1 degree (the draft path renames the caps) and back. The rim arc stays a circle of
radius 2 about (10, 0, 5), whole or in pieces; the bottom rim arc (z = 0) is another element.
Ported from `work/503-r2/taper2.py` (`work/501-review/taper_blind.py`; `corpus/predicted/D.json`:
CC3)."""

from PartDesignTests.Scenarios.harness import Filleted, Scenario, edge, pieces
from PartDesignTests.Scenarios import models as m

TOP = 5


class TaperedPadRimArc(Scenario):
    """The tapered pad and the fillet on the top rim arc."""

    area = "taper-rim"
    CLASSES = ("D",)
    AXES = ("M1", "E4")
    ISSUE = "ops#503"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("top_rim_fillet",)
    steps = ("taper", "straight")

    def topRim(self):
        return pieces(edge("circle", center=(10, 0, TOP), radius=2))

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), body)
        self.pad = m.pad(body, base, TOP)
        doc.recompute()
        hole = m.sketch(doc, "Hole", [m.circle(10, 0, 2.0)], body, z=TOP)
        pocket = m.pocketThroughAll(body, hole)
        pocket.Midplane = True
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "FilletTop")
        fillet.Base = (pocket, self.names(pocket, self.topRim().predicate))
        fillet.Radius = 0.3
        doc.recompute()
        self.ref("top_rim_fillet", fillet, "Base", self.topRim, Filleted(0.3))

    def taper(self, doc):
        self.pad.TaperAngle = 1.0

    def straight(self, doc):
        self.pad.TaperAngle = 0.0
