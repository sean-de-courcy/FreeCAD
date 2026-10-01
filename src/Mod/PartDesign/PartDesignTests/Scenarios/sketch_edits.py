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

"""Sketch edits: the profile of a pad changes, and the references downstream follow it."""

import FreeCAD as App
import Part

from .harness import BROKEN, Attached, Filleted, ReachesFace, Scenario, X, Y, Z, edge, face
from . import models as m

V = App.Vector


class SketchEdit(Scenario):
    """A rectangle (0..20 x 0..10, lines: front, right, back, left) padded 10 high; a fillet on
    the right top edge; a tunnel (y, z 3..7) pocketed from the left face up to the right face;
    a sketch attached to the pad's top face."""

    abstract = True
    area = "sketch edits"
    MULTI = True
    REFS = ("top_face", "right_face", "right_top_edge")
    width, depth, height = 20, 10, 10

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.height))

    def rightFace(self):
        return face("plane", normal=X, through=(self.width, 0, 0))

    def rightTopEdge(self):
        return edge("line", direction=Y, through=(self.width, 0, self.height))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.rightTopEdge()))
        fillet.Radius = 1
        doc.recompute()
        # on the left face, facing -X, so the pocket runs +X; sketch x = global z, y = global y
        at = App.Placement(V(0, 0, 0), m.rotationFromAxes((0, 0, 1), (0, 1, 0)))
        tunnel = m.sketch(doc, "Tunnel", m.rectangle(3, 3, 7, 7), body, placement=at)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = tunnel
        pocket.Type = "UpToFace"
        pocket.UpToFace = (fillet, self.names(fillet, self.rightFace()))
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(pad, self.names(pad, self.topFace())[0])]
        onTop.MapMode = "FlatFace"
        self.ref("top_face", onTop, "AttachmentSupport", self.topFace, Attached())
        self.ref("right_face", pocket, "UpToFace", self.rightFace, ReachesFace())
        self.ref("right_top_edge", fillet, "Base", self.rightTopEdge, Filleted(1))


class SketchMoveSide(SketchEdit):
    """The right side moves from x = 20 to x = 24; its line keeps its geometry ID."""

    def edit(self, doc):
        lines = {0: ((0, 0), (24, 0)), 1: ((24, 0), (24, 10)), 2: ((24, 10), (0, 10))}
        m.setLines(doc.Profile, lines)
        self.width = 24


class SketchNotch(SketchEdit):
    """A notch (x 8..12, 2 deep) is cut into the front side: four new lines, and the front line
    ends at the notch."""

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)


class SketchRedraw(SketchEdit):
    """The rectangle is deleted and drawn again from the right back corner, the other way
    round: the same geometry, every geometry ID new."""

    def edit(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)


class SketchReaddLine(SketchEdit):
    """The right side's line is deleted and drawn again in the same place. The sketcher's
    geometry history gives it its old geometry ID back (SketchObject::generateId matches the end
    points of deleted geometry), so this checks a delete and re-add, not a new ID."""

    def edit(self, doc):
        doc.Profile.delGeometry(1)
        doc.Profile.addGeometry(Part.LineSegment(V(20, 0, 0), V(20, 10, 0)), False)


class SolverOuterWireGains(Scenario):
    """The reference solver's tier 1 (ops#7): a rectangle (0..20 x 0..10) padded 10 high, a
    sketch attached to the pad's top face and a fillet on its front top edge. The profile's right
    back corner is cut off by a new line from (20, 7) to (17, 10): the outer wire gains an edge,
    so the top face's name changes, and its old name's edges are all in the new one's."""

    area = "sketch edits"
    MULTI = True
    REFS = ("top_face", "front_top_edge")

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def frontTopEdge(self):
        return edge("line", direction=X, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.frontTopEdge()))
        fillet.Radius = 1
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(pad, self.names(pad, self.topFace())[0])]
        onTop.MapMode = "FlatFace"
        self.ref("top_face", onTop, "AttachmentSupport", self.topFace, Attached())
        self.ref("front_top_edge", fillet, "Base", self.frontTopEdge, Filleted(1))

    def edit(self, doc):
        m.setLines(doc.Profile, {1: ((20, 0), (20, 7)), 2: ((17, 10), (0, 10))})
        doc.Profile.addGeometry(Part.LineSegment(V(20, 7, 0), V(17, 10, 0)), False)


# ---------------------------------------------------------------------------------------------
# The reference solver's tiers 2 and 3 (ops#7, Task 2 PR 4): sketches drawn again, so that no
# name relates the old elements to the new ones and only geometry can. SketchRedraw's
# right_top_edge is the case where it should (the edge is back in its place).
# ---------------------------------------------------------------------------------------------


class SolverSketchReplacedMoved(Scenario):
    """A rectangle (0..20 x 0..10) padded 10 high, a fillet on its right top edge. The rectangle
    is deleted and drawn again 5 mm over (x 5..25): every geometry ID is new, and the old edge's
    place is empty. The nearest edge along Y is 5 mm away, so the fillet's reference breaks
    rather than move to it."""

    area = "sketch edits"
    MULTI = True
    REFS = ("right_top_edge",)
    redrawn = False

    def rightTopEdge(self):
        if self.redrawn:
            return BROKEN
        return edge("line", direction=Y, through=(20, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.rightTopEdge()))
        fillet.Radius = 1
        self.ref("right_top_edge", fillet, "Base", self.rightTopEdge, Filleted(1))

    def edit(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(25, 10), (25, 0), (5, 0), (5, 10)]), False)
        self.redrawn = True


class SolverTwinRotate(Scenario):
    """A plate (0..30 x 0..30, 5 high) with two round bosses (radius 3, 5 high) at (10, 15) and
    (20, 15) from one sketch, and a fillet on each boss's top circle. The bosses' sketch is
    replaced by two circles at (15, 10) and (15, 20): every name is new, and each old circle has
    two circles of its radius and axis, neither in its place. Both references break; neither
    takes a rotated boss."""

    area = "sketch edits"
    MULTI = True
    REFS = ("edge_a", "edge_b")
    replaced = False

    def topCircle(self, x):
        if self.replaced:
            return BROKEN
        return edge("circle", center=(x, 15, 10), radius=3)

    def edgeA(self):
        return self.topCircle(10)

    def edgeB(self):
        return self.topCircle(20)

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(0, 0, 30, 30), body)
        m.pad(body, plate, 5, name="PlatePad")
        bosses = m.sketch(doc, "Bosses", [m.circle(10, 15, 3), m.circle(20, 15, 3)], body, z=5)
        bossPad = m.pad(body, bosses, 5, name="BossPad")
        doc.recompute()
        for ref, predicate in (("edge_a", self.edgeA), ("edge_b", self.edgeB)):
            fillet = body.newObject("PartDesign::Fillet", "Fillet_" + ref)
            fillet.Base = (bossPad, self.names(bossPad, predicate()))
            fillet.Radius = 0.5
            self.ref(ref, fillet, "Base", predicate, Filleted(0.5))
            doc.recompute()

    def edit(self, doc):
        doc.Bosses.deleteAllGeometry()
        doc.Bosses.addGeometry([m.circle(15, 10, 3), m.circle(15, 20, 3)], False)
        self.replaced = True
