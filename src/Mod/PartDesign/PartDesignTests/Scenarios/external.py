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

from .harness import BROKEN, Broken, ExternalCoincides, Guessed, Scenario, X, Y, edge, pieces
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


class ExternalSplitOffCentre(ExternalSplit):
    """ExternalSplit's notch moved left, to x 4..8: the front top edge splits into x 0..4, which
    keeps its name, and x 8..20, which holds the old edge's centre (x = 10). In solver documents
    the reference is guessed to the piece at the saved centre, the continuation, not the piece
    with the name (ops#127, N2 5.2 G3); without the solver it breaks with both pieces as
    candidates, as ExternalSplit's does."""

    def frontEdge(self):
        if self.split and self.solver:
            return Guessed(edge("line", direction=X, contains=(14, 0, self.height)))
        return super().frontEdge()

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (4, 0))})
        doc.Profile.addGeometry(m.polyline([(4, 0), (4, 2), (8, 2), (8, 0), (20, 0)]), False)
        self.split = True


class ExternalSplitNamedPieceKept(ExternalSplit):
    """ExternalSplit's notch moved right, to x 12..16, in two steps. `notch`: the front top edge
    splits into x 0..12, which keeps its name and holds the old edge's centre (x = 10), and
    x 16..20. In solver documents the reference is guessed to the named piece (N2 5.2 G3) and
    keeps its record. `moveBack`: the back side moves out to y = 12, an edit that leaves the
    pick alone; the guess stays a guess, its warning too, until the user ends it (A1; the Fable
    review of fork PR 117, finding 1). Without the solver it breaks, as ExternalSplit's does."""

    steps = ("notch", "moveBack")

    def frontEdge(self):
        if self.split and self.solver:
            return Guessed(edge("line", direction=X, contains=(6, 0, self.height)))
        return super().frontEdge()

    def notch(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (12, 0))})
        doc.Profile.addGeometry(m.polyline([(12, 0), (12, 2), (16, 2), (16, 0), (20, 0)]), False)
        self.split = True

    def moveBack(self, doc):
        m.setLines(doc.Profile, {1: ((20, 0), (20, 12)), 2: ((20, 12), (0, 12)), 3: ((0, 12), (0, 0))})
        self.depth = 12


class ExternalMoveSideIn(ExternalEdit):
    """The right side moves in from x = 20 to x = 16, its lines keeping their geometry IDs: the
    front edge gets shorter, and nothing lies on the rest of its old place. The external edge
    follows it: a shortened edge isn't a split (ops#7, Task 2 PR 7)."""

    def edit(self, doc):
        lines = {0: ((0, 0), (16, 0)), 1: ((16, 0), (16, 10)), 2: ((16, 10), (0, 10))}
        m.setLines(doc.Profile, lines)
        self.width = 16


class ExternalNotchAndExtend(ExternalSplit):
    """ExternalSplit's notch, with the right side moved out to x = 26: the rest of the front
    side (x 12..26) runs past the old edge's end. The reference breaks, with both edges as
    candidates (ops#7, Task 2 PR 7)."""

    def edit(self, doc):
        lines = {0: ((0, 0), (8, 0)), 1: ((26, 0), (26, 10)), 2: ((26, 10), (0, 10))}
        m.setLines(doc.Profile, lines)
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (26, 0)]), False)
        self.width = 26
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


class ExternalSideReplaced(ExternalEdit):
    """The right line is deleted and replaced by a V, (20, 0)-(25, 5)-(20, 10): the side face at
    x = 20 and its top edge are gone (two slanted faces take their place). The right edge's
    sketch should report the missing reference and keep its link (ops#72: it stayed valid,
    frozen at x = 20, and dropped the link). The front edge doesn't change."""

    replaced = False

    def rightEdge(self):
        return BROKEN if self.replaced else super().rightEdge()

    def edit(self, doc):
        doc.Profile.delGeometry(1)
        doc.Profile.addGeometry(m.polyline([(20, 0), (25, 5), (20, 10)]), False)
        self.replaced = True


class ExternalEdgeRemoved(Scenario):
    """A block 0..20 x 0..10 x 10 (a pad) with a hole, radius 2 at (6, 5), pocketed through it;
    a boss (x 13..17, y 3..7, 3 high) padded on the top; a sketch at z = 0 with the boss
    feature's edge of the hole's bottom (the circle at z = 0) as external geometry. The hole is
    deleted, as the GUI does it: the boss now builds on the pad, the circle is gone, and the
    sketch should report it (ops#72: it stays valid and drops the link). Found by the randomized
    sequences (seed 38)."""

    area = "external geometry"
    REFS = ("hole_bottom",)
    gone = False

    def holeBottom(self):
        return BROKEN if self.gone else edge("circle", center=(6, 5, 0), radius=2)

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        hole = m.sketch(doc, "HoleSketch", [m.circle(6, 5, 2)], body, z=10)
        m.pocketThroughAll(body, hole, "Hole")
        boss = m.sketch(doc, "BossSketch", m.rectangle(13, 3, 17, 7), body, z=10)
        boss = m.pad(body, boss, 3, name="Boss")
        doc.recompute()
        sketch = m.sketch(doc, "OnBottom", [], body, z=0)
        sketch.addExternal(boss.Name, self.names(boss, self.holeBottom())[0])
        self.ref("hole_bottom", sketch, "ExternalGeometry", self.holeBottom, ExternalCoincides())

    def edit(self, doc):
        self.bodyObject.removeObject(doc.Hole)
        doc.removeObject("Hole")
        self.gone = True


class ExternalArcSplit(Scenario):
    """A disc with two flats (centre (10, 5), radius 5, the chords y = 1 and y = 9) padded 10
    high; a sketch at z = 10 with the right arc's top edge as external geometry. A notch is cut
    into the right arc as in SplitArcNotch: the arc keeps its ID on -53..-10 degrees, and a new arc
    continues it on 10..53. The external edge needs one element, so its reference breaks with the
    two outer pieces as candidates (ops#7, Task 2 PR 7b)."""

    area = "external geometry"
    REFS = ("right_arc",)
    height = 10
    split = False

    def rightArc(self):
        arc = edge(
            center=(*m.DISC_CENTER, self.height),
            radius=m.DISC_RADIUS,
            where=lambda e: e.CenterOfMass.x > m.DISC_CENTER[0],
        )
        return Broken(pieces(arc)) if self.split else arc

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.twoFlatDisc(), body)
        pad = m.pad(body, profile, self.height)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body, z=self.height)
        sketch.addExternal(pad.Name, self.names(pad, self.rightArc())[0])
        self.ref("right_arc", sketch, "ExternalGeometry", self.rightArc, ExternalCoincides())

    def edit(self, doc):
        m.notchDiscArc(doc.Profile)
        self.split = True


class ExternalArcSplitOffCentre(ExternalArcSplit):
    """ExternalArcSplit's notch moved down, to -30..-10 degrees: the arc keeps its ID on
    -53..-30, and the new arc on -10..53 holds the old arc's mid-angle (0 degrees). In solver
    documents the reference is guessed to that arc, not the piece with the name (ops#127, N2 5.2
    G3); without the solver it breaks with both pieces as candidates, as ExternalArcSplit's
    does."""

    def rightArc(self):
        if self.split and self.solver:
            on = m.onDisc(m.DISC_RADIUS, 0)
            return Guessed(
                edge(
                    center=(*m.DISC_CENTER, self.height),
                    radius=m.DISC_RADIUS,
                    contains=(on.x, on.y, self.height),
                )
            )
        return super().rightArc()

    def edit(self, doc):
        m.notchDiscArc(doc.Profile, -30, -10)
        self.split = True


class ExternalThreadRemoved(Scenario):
    """A block 0..30 x 0..30 x 10 (a pad) with a threaded hole (M6 by its thread size, 8 deep,
    a drill point) at (15, 15), its thread modelled; a sketch at z = 0 with one of the thread's
    edges (a B-spline) as external geometry. The thread stops being modelled: every thread edge
    is gone, and the sketch should report it. The drill point's circles share the thread edge's
    sources, so tier 1 found one of them alone, which has another curve (ops#87: the sketch
    stayed valid on that circle)."""

    area = "external geometry"
    REFS = ("thread_edge",)
    gone = False

    def threadEdge(self):
        return BROKEN if self.gone else self.thread

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 30, 30), body)
        m.pad(body, profile, 10)
        circle = m.sketch(doc, "HoleSketch", [m.circle(15, 15, 0.25)], body)
        doc.recompute()  # the hole's properties read its base's shape
        hole = body.newObject("PartDesign::Hole", "Hole")
        hole.Profile = circle
        hole.Reversed = True
        hole.Diameter = 6
        hole.Depth = 8
        hole.DepthType = 0
        hole.DrillPoint = 1
        hole.DrillPointAngle = 118
        hole.Threaded = 1
        hole.ThreadType = 1
        hole.ThreadSize = 16
        hole.ModelThread = 1
        doc.recompute()
        # The thread's first B-spline edge, by index: its place is all the scenario needs.
        first = next(
            i
            for i, e in enumerate(hole.Shape.Edges, 1)
            if isinstance(e.Curve, Part.BSplineCurve)
        )
        where = hole.Shape.Edges[first - 1].CenterOfMass
        self.thread = edge(
            where=lambda e: isinstance(e.Curve, Part.BSplineCurve)
            and (e.CenterOfMass - where).Length < 1e-6
        )
        sketch = m.sketch(doc, "OnBottom", [], body)
        sketch.addExternal(hole.Name, f"Edge{first}")
        self.ref("thread_edge", sketch, "ExternalGeometry", self.threadEdge, ExternalCoincides())

    def edit(self, doc):
        doc.Hole.ModelThread = 0
        self.gone = True
