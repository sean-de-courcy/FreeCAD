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

"""Sketch external geometry: a sketch's external edge follows the pad's edge it projects when
the pad's profile changes. When the edge is split, the reference should break with the pieces
as candidates (the naming design's section 8: the consumer needs exactly one edge)."""

import FreeCAD as App
import Part

from .harness import Broken, ExternalCoincides, Scenario, X, Y, edge, pieces
from . import models as m


class ExternalEdit(Scenario):
    """A rectangle (0..20 x 0..10, lines: front, right, back, left) padded 10 high; two sketches
    at z = 10, one with the pad's front top edge as external geometry, one with its right top
    edge."""

    abstract = True
    area = "external geometry"
    REFS = ("front_edge", "right_edge")
    width, depth, height = 20, 10, 10

    def frontEdge(self):
        return edge("line", direction=X, through=(0, 0, self.height))

    def rightEdge(self):
        return edge("line", direction=Y, through=(self.width, 0, self.height))

    def external(self, doc, body, name, pad, predicate):
        sketch = m.sketch(doc, name, [], body, z=self.height)
        sketch.addExternal(pad.Name, self.names(pad, predicate)[0])
        return sketch

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.width, self.depth), body)
        pad = m.pad(body, profile, self.height)
        doc.recompute()
        front = self.external(doc, body, "OnFront", pad, self.frontEdge())
        right = self.external(doc, body, "OnRight", pad, self.rightEdge())
        self.ref("front_edge", front, "ExternalGeometry", self.frontEdge, ExternalCoincides())
        self.ref("right_edge", right, "ExternalGeometry", self.rightEdge, ExternalCoincides())


class ExternalBackNotch(ExternalEdit):
    """A notch (x 8..12, 2 deep) is cut into the back side: four new lines, every face and edge
    after them renumbered; the referenced edges don't change."""

    def edit(self, doc):
        m.setLines(doc.Profile, {2: ((20, 10), (12, 10))})
        doc.Profile.addGeometry(m.polyline([(12, 10), (12, 8), (8, 8), (8, 10), (0, 10)]), False)


class ExternalMoveSide(ExternalEdit):
    """The right side moves from x = 20 to x = 24; its line keeps its geometry ID. The front
    edge gets longer."""

    def edit(self, doc):
        lines = {0: ((0, 0), (24, 0)), 1: ((24, 0), (24, 10)), 2: ((24, 10), (0, 10))}
        m.setLines(doc.Profile, lines)
        self.width = 24


class ExternalSplit(ExternalEdit):
    """A notch (x 8..12, 2 deep) is cut into the front side: the front top edge splits into
    x 0..8 and x 12..20, and the reference to it should break, with both pieces as
    candidates."""

    split = False

    def frontEdge(self):
        if self.split:
            return Broken(pieces(super().frontEdge()))
        return super().frontEdge()

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)
        self.split = True



class ExternalLineToArc(ExternalEdit):
    """The front line is deleted and an arc drawn between its end points (through (10, -3)). The
    sketcher's geometry history gives the arc the deleted line's ID, as its replacement
    (`SketchObject::generateId`), so the external edge should follow to the arc's top edge."""

    arc = False

    def frontEdge(self):
        if self.arc:
            return edge("circle", contains=(10, -3, 10))
        return super().frontEdge()

    def edit(self, doc):
        doc.Profile.delGeometry(0)
        arc = Part.Arc(App.Vector(0, 0, 0), App.Vector(10, -3, 0), App.Vector(20, 0, 0))
        doc.Profile.addGeometry(arc, False)
        self.arc = True
