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

"""Corpus cases (ops#502, class C; ops#441's battery): a Part::Sweep along a spine without an
element map, under point edits of the spine.

A square -2..2 profile at the origin (XY plane) swept along a U in XZ, (0, 0) -> (0, 30) ->
(20, 30) -> (20, 10), legs A, B, C, right corners. The spine is a Part::Polygon, a Draft Wire or
a script's Part::Feature: none has history, so the sweep's names come from the spine's MLN ids.
References: each leg's four side faces (FlatFace) and four lateral edges (NormalToEdge), and the
corner edges between legs A and B, and B and C (NormalToEdge), 32 in all; each expected on the
same leg's element after the edit. The edits: the points reversed, a point added before the
start, a point inside leg A (refs on B and C only), the last point moved, a point appended.
Ported from `work/441/research/p2_edits.py` (`corpus/predicted/C.json` row 324)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, ScenarioError, edge, face, tolerance
from PartDesignTests.Scenarios import models as m

V = App.Vector
Y = V(0, 1, 0)
# the profile's edges (by their midpoints) and vertices, in profile coordinates
EDGES = {"f1": (0, -2), "f2": (2, 0), "f3": (0, 2), "f4": (-2, 0)}
VERTS = {"v1": (-2, -2), "v2": (2, -2), "v3": (2, 2), "v4": (-2, 2)}
U_POINTS = [(0, 0), (0, 30), (20, 30), (20, 10)]
U_LEGS = [("A", (0, 0), (0, 30)), ("B", (0, 30), (20, 30)), ("C", (20, 30), (20, 10))]


def at3(point):
    return V(point[0], 0, point[1])


def onLeg(leg, uv):
    """The point of the leg's middle section at profile coordinates uv (the profile's X turned
    with the leg at the right corners)."""
    _, a, b = leg
    d = at3(b) - at3(a)
    d.normalize()
    middle = at3(a) + (at3(b) - at3(a)) * 0.5
    return middle + V(d.z, 0, -d.x) * uv[0] + Y * uv[1]


class Shared:
    """The edge shared by the faces that contain two points."""

    kind = "Edge"

    def __init__(self, first, second, text):
        self.first, self.second, self.text = first, second, text

    def select(self, shape):
        tol = tolerance(shape)
        firsts = [f for f in shape.Faces if f.isInside(self.first, tol, True)]
        seconds = [f for f in shape.Faces if f.isInside(self.second, tol, True)]
        if len(firsts) != 1 or len(seconds) != 1:
            return []
        return [
            "Edge%d" % i
            for i, e in enumerate(shape.Edges, 1)
            if any(e.isSame(x) for x in firsts[0].Edges) and any(e.isSame(x) for x in seconds[0].Edges)
        ]

    def one(self, shape):
        names = self.select(shape)
        if len(names) != 1:
            raise ScenarioError("%r matches %s, not one element" % (self, names or "nothing"))
        return names

    def __repr__(self):
        return "Shared(%s)" % self.text


def predicate(legs, key):
    """key: '<leg>.f<j>' a side face, '<leg>.v<j>' a lateral edge, '<a><b>.c<j>' the edge between
    legs a and b on profile edge j."""
    where, what = key.split(".")
    if what.startswith("c"):
        j = "f" + what[1:]
        return Shared(onLeg(legs[where[0]], EDGES[j]), onLeg(legs[where[1]], EDGES[j]), key)
    leg = legs[where]
    if what.startswith("f"):
        return face(contains=onLeg(leg, EDGES[what]))
    _, a, b = leg
    d = at3(b) - at3(a)
    d.normalize()
    return edge(curve="line", direction=d, contains=onLeg(leg, VERTS[what]))


def keysFor(legs, corners):
    keys = []
    for leg in legs:
        keys += ["%s.%s" % (leg, j) for j in EDGES]
        keys += ["%s.%s" % (leg, j) for j in VERTS]
    for corner in corners:
        keys += ["%s.c%d" % (corner, j) for j in range(1, 5)]
    return tuple(keys)


class SpineEdit(Scenario):
    """The U sweep along a SPINE ("polygon", "draft", "script"); POINTS and LEGS after the edit."""

    abstract = True
    area = "mapless-spines"
    CLASSES = ("C",)
    AXES = ("M3", "E1")
    ISSUE = "ops#502"
    FOUND_BY = "port"
    SPINE = None
    POINTS = U_POINTS
    LEGS = U_LEGS
    REFS = keysFor("ABC", ("AB", "BC"))

    def legsNow(self):
        return {leg[0]: leg for leg in (self.LEGS if self.stepName == "edit" else U_LEGS)}

    def setPoints(self, points):
        vectors = [at3(q) for q in points]
        if self.SPINE == "polygon":
            self.path.Nodes = vectors
        elif self.SPINE == "draft":
            self.path.Points = vectors
        else:
            self.path.Shape = Part.makePolygon(vectors)

    def build(self, doc):
        if self.SPINE == "polygon":
            self.path = doc.addObject("Part::Polygon", "Path")
        elif self.SPINE == "draft":
            import Draft

            self.path = Draft.make_wire([at3(q) for q in U_POINTS], closed=False, face=False)
            self.path.Placement = App.Placement()
        else:
            self.path = doc.addObject("Part::Feature", "Path")
        self.setPoints(U_POINTS)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2))
        solid = doc.addObject("Part::Sweep", "Sweep")
        solid.Sections = [profile]
        solid.Spine = (self.path, [])
        solid.Solid = True
        solid.Transition = "Right corner"
        doc.recompute()
        if not solid.isValid() or solid.Shape.isNull():
            raise ScenarioError("model invalid: %s" % solid.State)
        for key in self.REFS:
            sketch = doc.addObject("Sketcher::SketchObject", "On_" + key.replace(".", "_"))
            sketch.AttachmentSupport = [(solid, self.names(solid, predicate(self.legsNow(), key))[0])]
            sketch.MapMode = "FlatFace" if ".f" in key else "NormalToEdge"
            self.ref(
                key,
                sketch,
                "AttachmentSupport",
                (lambda k=key: predicate(self.legsNow(), k)),
                Attached(),
            )

    def edit(self, doc):
        self.setPoints(self.POINTS)


class Reverse:
    """The points in the other order."""

    POINTS = list(reversed(U_POINTS))


class InsertStart:
    """A point before the start: a new leg N before A."""

    POINTS = [(-10, 0)] + U_POINTS
    LEGS = [("N", (-10, 0), (0, 0))] + U_LEGS


class SplitA:
    """A point inside leg A: A becomes two legs; the references are on B and C."""

    POINTS = [(0, 0), (0, 15), (0, 30), (20, 30), (20, 10)]
    LEGS = [("P", (0, 0), (0, 15)), ("Q", (0, 15), (0, 30))] + U_LEGS[1:]
    REFS = keysFor("BC", ("BC",))


class MoveLast:
    """The last point moved: leg C longer."""

    POINTS = [(0, 0), (0, 30), (20, 30), (20, 0)]
    LEGS = U_LEGS[:2] + [("C", (20, 30), (20, 0))]


class AppendEnd:
    """A point after the end: a new leg after C."""

    POINTS = U_POINTS + [(40, 10)]
    LEGS = U_LEGS + [("N", (20, 10), (40, 10))]


def _cases():
    made = {}
    for spine in ("polygon", "draft", "script"):
        for edit in (Reverse, InsertStart, SplitA, MoveLast, AppendEnd):
            name = "%sSpine%s" % (spine.capitalize(), edit.__name__)
            made[name] = type(
                name,
                (edit, SpineEdit),
                {"SPINE": spine, "__doc__": "%s spine: %s" % (spine.capitalize(), edit.__doc__)},
            )
    return made


globals().update(_cases())
