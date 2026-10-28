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


"""Corpus cases (ops#502, class C): references to a history-less result whose element ids its
producer retired (the class C ruling of 10-28, `notes/naming-class-C.md` section 9).

A history-less result (a script's shape, an imported part) names its elements by a verified match
against the result it replaces (MLN), and an id the match can't verify is retired: never given
again, and the reference solver breaks on it instead of taking the element at the same place
(invariant I-C5). The cases: a fresh id at the same place (the solver's retired-id break); twins
traded in a script compound (P1: the class is retired, loud); and E1's index-shift case from
review pr384-r4 with its two controls (a map-less face or base solid moved by its own width:
the right face is the break's candidate; decision 164 (2) accepted the right -> loud move)."""

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6


class RetiredIdAtTheSamePlace(Scenario):
    """A Part::Feature holding a 8 x 8 x 5 box whose faces a script names itself (MLN ids 901-906),
    a sketch on its top face. The script sets the same box again with every face given a new id
    (951-956): the producer says each face is a new element, so the top face's old id is retired
    and the element at its place is another one. Right: the reference breaks (with the face at
    the same place as its candidate), never resolves there quietly."""

    area = "history-less results"
    CLASSES = ("C",)
    ISSUE = "ops#502"
    FOUND_BY = "ruling 10-28 (probe_names Sk)"
    TIER = "F"
    AXES = ("M2",)
    REFS = ("top",)

    def named(self, first):
        shape = Part.Shape()
        shape.importBrepFromString(Part.makeBox(8, 8, 5).exportBrepToString())
        for i in range(1, len(shape.Faces) + 1):
            shape.setElementName("Face%d" % i, "_;_;%d;MLN;%d;F;0;_;_" % (self.target.ID, first + i))
        return shape

    def topFace(self):
        return BROKEN if self.stepName else face("plane", normal=Z, through=(0, 0, 5))

    def build(self, doc):
        self.target = doc.addObject("Part::Feature", "Named")
        self.target.Shape = self.named(900)
        doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(self.target, self.names(self.target, self.topFace())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("top", sketch, "AttachmentSupport", self.topFace, Attached())

    def edit(self, doc):
        self.target.Shape = self.named(950)


class ScriptTwinsTraded(Scenario):
    """A script's compound of two 8 x 8 x 5 boxes, A at x = 0 and B at x = 20, as a fresh shape
    (no element map); a sketch on A's top face, another on B's. The script puts A at 20 and B at
    0: the shape is the same as before, so its places say nothing of which box moved, and the
    producer's order says the boxes traded. P1 retires both boxes' ids. Right by the producer's
    order: A's top at x = 20..28, B's at 0..8; a break that offers them is loud+ (decision 166:
    the trade's right -> loud cost is accepted)."""

    area = "history-less results"
    CLASSES = ("C",)
    ISSUE = "ops#502"
    FOUND_BY = "attack set c_script trade"
    TIER = "F"
    AXES = ("M2", "X4")
    REFS = ("a_top", "b_top")
    a, b = 0, 20

    def boxes(self):
        shape = Part.Shape()
        compound = Part.makeCompound([Part.makeBox(8, 8, 5, V(self.a, 0, 0)), Part.makeBox(8, 8, 5, V(self.b, 0, 0))])
        shape.importBrepFromString(compound.exportBrepToString())
        return shape

    def aTop(self):
        return face("plane", normal=Z, contains=V(self.a + 4, 4, 5))

    def bTop(self):
        return face("plane", normal=Z, contains=V(self.b + 4, 4, 5))

    def build(self, doc):
        self.target = m.feature(doc, "Twins", self.boxes())
        doc.recompute()
        for key, expect in (("a_top", self.aTop), ("b_top", self.bTop)):
            sketch = doc.addObject("Sketcher::SketchObject", "On_" + key)
            sketch.AttachmentSupport = [(self.target, self.names(self.target, expect())[0])]
            sketch.MapMode = "FlatFace"
            self.ref(key, sketch, "AttachmentSupport", expect, Attached())

    def edit(self, doc):
        self.a, self.b = 20, 0
        self.target.Shape = self.boxes()


# ---- E1's index-shift case and its controls (review pr384-r4) ----------------------------------


def onLine(g, axis, value, span):
    """Whether g is a line on axis = value spanning span (lo, hi) in the other coordinate."""
    if not hasattr(g, "StartPoint") or hasattr(g, "Radius"):
        return False
    other = "y" if axis == "x" else "x"
    ends = (g.StartPoint, g.EndPoint)
    if not all(abs(getattr(p, axis) - value) < TOL for p in ends):
        return False
    lo, hi = sorted(getattr(p, other) for p in ends)
    return abs(lo - span[0]) < TOL and abs(hi - span[1]) < TOL


def geoIdOf(sketch, match):
    found = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and match(g)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} projected geometries match")
    return found[0]


class CircleOnLine(Outcome):
    """The sketch computes, its PointOnObject constraint names the projected line `before()`
    before the edit and `after()` after it, and the circle's centre lies on that line."""

    def __init__(self, before, after):
        self.before, self.after = before, after

    def compare(self, scenario, consumer, target, expectation):
        if not consumer.isValid():
            return False, consumer.getStatusString()
        line = self.before() if scenario.stepName is None else self.after()
        constraint = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        held = consumer.ExternalGeo[-constraint.Second - 1]
        if not onLine(held, *line):
            return False, f"the constraint is on {held.StartPoint} - {held.EndPoint}"
        centre = consumer.Geometry[constraint.First].Center
        if centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint) > TOL:
            return False, f"the circle's centre is at {centre}"
        return True, ""


class FaceLinkMovedByWidth(Scenario):
    """A sketch at z = 0 projecting a map-less target's top face (the 20 x 20 square at z = 10), a
    circle r 1 on the projected right line x = 20. The edit moves the target 20 to the right (by
    its own width), so the old right line's place holds the new left line. Right: the circle on
    the right line, x = 40. With MLN the target's names are ids, and the move leaves no face of
    it at an old place: every id is retired, and the face link breaks with the moved top face as
    its candidate (loud+; decision 164 (2) accepted it where index names were right)."""

    abstract = True
    area = "history-less results"
    CLASSES = ("C",)
    ISSUE = "ops#502"
    FOUND_BY = "review pr384-r4"
    TIER = "F"
    AXES = ("M8", "E5")
    SIZE = 40
    SCALE = 1.0
    REFS = ("circle_on_line",)
    height = 10

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def before(self):
        return ("x", self.s(20), self.s(0, 20))

    def afterEdit(self):
        return ("x", self.s(40), self.s(0, 20))

    def constrain(self, doc, target, body=None):
        sketch = doc.addObject("Sketcher::SketchObject", "OnTop")
        if body is not None:
            body.addObject(sketch)
        sketch.addExternal(target.Name, self.names(target, self.topFace())[0])
        doc.recompute()
        line = geoIdOf(sketch, lambda g: onLine(g, *self.before()))
        circle = sketch.addGeometry(m.circle(*self.s(20, 5), self.s(1)), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, self.s(1)))
        self.ref("circle_on_line", sketch, "ExternalGeometry", self.topFace,
                 CircleOnLine(self.before, self.afterEdit))

    def square(self, points):
        s = self.s
        wire = Part.makePolygon([V(*s(*p), s(self.height)) for p in points + [points[0]]])
        return Part.Face(wire)


class MaplessFaceCornerCutMovedByWidth(FaceLinkMovedByWidth):
    """Review pr384-r4's `ReviewUnmappedFaceCornerCutMovedByWidth`: a Part::Feature whose shape is
    the planar square face; in one edit it moves 20 to the right and its back-left corner is cut
    5 x 5 (the count changes)."""

    AXES = ("M8", "E1", "E5")

    def build(self, doc):
        self.target = m.feature(doc, "Plate", self.square([(0, 0), (20, 0), (20, 20), (0, 20)]))
        doc.recompute()
        self.constrain(doc, self.target)

    def edit(self, doc):
        self.target.Shape = self.square([(20, 0), (40, 0), (40, 20), (25, 20), (20, 15)])


class MaplessFaceMovedByWidth(MaplessFaceCornerCutMovedByWidth):
    """Review pr384-r4's `ReviewUnmappedFaceMovedByWidth`, the control: the face moved 20 to the
    right, no corner cut."""

    AXES = ("M8", "E5")

    def edit(self, doc):
        self.target.Shape = self.square([(20, 0), (40, 0), (40, 20), (20, 20)])


class BaseFeatureIndexShiftCornerCutMovedByWidth(FaceLinkMovedByWidth):
    """Review pr384-r4's `ReviewBaseFeatureIndexShiftCornerCutMovedByWidth` (E1's case, decision
    164): a PartDesign body whose BaseFeature is a Part::Feature solid, the square extruded 10 as an
    extrusion gives it (its top face Face6, Face7 after the cut); the sketch projects the body's
    top face. In one edit the base is moved 20 to the right and its back-left corner cut 5 x 5.
    With index names the body's Face6 reference lands on the bottom face, whose projection is the
    same outline (`equivalent` by luck on integration)."""

    AXES = ("M8", "E1", "E5")

    def solid(self, points):
        s = self.s
        wire = Part.makePolygon([V(*s(*p), 0) for p in points + [points[0]]])
        return Part.Face(wire).extrude(V(0, 0, s(self.height)))

    def build(self, doc):
        self.base = m.feature(doc, "Base", self.solid([(0, 0), (20, 0), (20, 20), (0, 20)]))
        body = m.body(doc)
        body.BaseFeature = self.base
        doc.recompute()
        self.constrain(doc, body.Tip, body)

    def edit(self, doc):
        self.base.Shape = self.solid([(20, 0), (40, 0), (40, 20), (25, 20), (20, 15)])
