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

"""Class B's cases for the open Pipes whose spine lines are drawn the other way (ops#501; the ops
repo's `corpus/predicted/B.json`, row `proto_b|open_pipes_line_reversals|V2s`, the null-edit audit
of `work/501/proto_b.py`, part N).

The model: a PartDesign AdditivePipe of a 4 x 4 square with a round hole (radius 0.8) in the XY
plane at the origin, along an open spine of straight lines drawn in an XZ sketch:
- L: (0,0)-(0,30)-(20,30); Z: L and (20,30)-(20,60); U: L and (20,30)-(20,10), each with the
  "Right corner" and the "Round corner" transition;
- L2: (0,0)-(0,30)-(20,40); Z2: L2 and (20,40)-(20,70), with "Transformed" (which makes one sweep
  only where the legs bend by less than 90 degrees, ops#370).

One class per run of the audit (29): one spine line drawn the other way with its geometry id kept
(`Line<k>`), or every line (`AllLines`). The solid is unchanged, so each reference must hold its
element at its own place. The references are datum points on the elements nearest each vertex of
the spine (its ends and bends): the 2 nearest edges (their middles), the 2 nearest vertices and the
2 nearest faces, found on the pipe as built; an element is identified by its geometry (an edge by
its curve, length and middle, a face by its surface, area and centre of mass). Degenerate edges
(length 0, at the pole of a Round corner's torus) are no elements to refer to: they are left out."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, face, vertex
from PartDesignTests.Scenarios import models as m


V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
TOL = 1e-4


def drawnTheOtherWay(sketch, indices=None):
    """The sketch's lines (at `indices`, or all) drawn the other way, their geometry ids kept."""
    geometry = sketch.Geometry
    for index in range(len(geometry)) if indices is None else indices:
        line = geometry[index]
        if line.TypeId != "Part::GeomLineSegment":
            continue
        start, end = V(line.StartPoint), V(line.EndPoint)
        line.StartPoint, line.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
        line.StartPoint, line.EndPoint = end, start
    sketch.Geometry = geometry


# ---- elements found by their geometry, as built (copied into each module of the group) ----


def middle(e):
    return V(e.valueAt((e.FirstParameter + e.LastParameter) / 2))


def curveKind(e):
    try:
        return type(e.Curve).__name__
    except Exception:
        return "?"


def surfaceKind(f):
    try:
        return type(f.Surface).__name__
    except Exception:
        return "?"


def signature(element):
    """What identifies the element in the shape as built: a vertex by its point, an edge by its
    curve, length and middle, a face by its surface, area and centre of mass."""
    if element.ShapeType == "Vertex":
        return ("Vertex", "", 0.0, V(element.Point))
    if element.ShapeType == "Edge":
        return ("Edge", curveKind(element), element.Length, middle(element))
    return ("Face", surfaceKind(element), element.Area, V(element.CenterOfMass))


def predicate(sig, move=None):
    """The predicate of the element with the signature `sig`, at its place or, with `move` (a
    function of a point), where the motion `move` sends its place."""
    shape, kind, size, at = sig
    if move is not None:
        at = move(at)
    if shape == "Vertex":
        return vertex(at)
    if shape == "Edge":
        return edge(
            where=lambda e: curveKind(e) == kind
            and abs(e.Length - size) <= TOL * max(1.0, size)
            and (middle(e) - at).Length <= TOL
        )
    return face(
        where=lambda f: surfaceKind(f) == kind
        and abs(f.Area - size) <= TOL * max(1.0, size)
        and (V(f.CenterOfMass) - at).Length <= TOL
    )


def nearest(shape, at, per):
    """The elements of `shape` nearest the point `at`: per[0] edges (by their middles), per[1]
    vertices, per[2] faces (by their distance to it), ties broken by place. Degenerate edges (a
    length of 0, as at the pole of a Round corner's torus) are no place: they are left out."""

    def key(distance, place):
        return (round(distance, 6), tuple(round(c, 6) for c in place))

    point = Part.Vertex(at)
    edges = sorted(
        (e for e in shape.Edges if e.Length > 1e-6),
        key=lambda e: key((middle(e) - at).Length, middle(e)),
    )
    vertices = sorted(shape.Vertexes, key=lambda v: key((V(v.Point) - at).Length, v.Point))
    faces = sorted(shape.Faces, key=lambda f: key(point.distToShape(f)[0], V(f.CenterOfMass)))
    return {"e": edges[: per[0]], "v": vertices[: per[1]], "f": faces[: per[2]]}


def refNames(count, per=(2, 2, 2), prefix="p"):
    """REFS: at each of `count` places, the elements `nearest` takes"""
    return tuple(
        f"{prefix}{c}_{kind}{i}" for c in range(count) for kind, n in zip("evf", per) for i in range(n)
    )


class Anchored(Scenario):
    """A case whose references are datum points on the elements nearest its PLACES (taken on the
    target as built: `PER` edges, vertices and faces at each), and an edit that leaves the solid
    as it was, or moves its elements by `moved` (applied to the expected places after the edit)."""

    abstract = True
    CLASSES = ("B",)
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    PLACES = ()
    PER = (2, 2, 2)

    def moved(self, point):
        """Where the edit sends a place of the model (the identity: the solid is unchanged)."""
        return point

    def anchor(self, doc, body, target):
        """Datum points on the elements of `target` nearest each place (in `body`, or in the
        document where the target is no body feature)."""
        for c, place in enumerate(self.PLACES):
            found = nearest(target.Shape, V(*place), self.PER)
            for kind in "evf":
                for i, element in enumerate(found[kind]):
                    key = f"p{c}_{kind}{i}"
                    sig = signature(element)
                    expect = lambda sig=sig: predicate(  # noqa: E731
                        sig, self.moved if self.stepName else None
                    )
                    before = predicate(sig)
                    name = "On_" + key
                    datum = (
                        body.newObject("PartDesign::Point", name)
                        if body
                        else doc.addObject("PartDesign::Point", name)
                    )
                    datum.AttachmentSupport = [(target, self.names(target, before))]
                    datum.MapMode = "Vertex" if kind == "v" else "CenterOfMass"
                    self.ref(key, datum, "AttachmentSupport", expect, Attached())


L = (((0, 0), (0, 30)), ((0, 30), (20, 30)))
Z = (((0, 0), (0, 30)), ((0, 30), (20, 30)), ((20, 30), (20, 60)))
U = (((0, 0), (0, 30)), ((0, 30), (20, 30)), ((20, 30), (20, 10)))
L2 = (((0, 0), (0, 30)), ((0, 30), (20, 40)))
Z2 = (((0, 0), (0, 30)), ((0, 30), (20, 40)), ((20, 40), (20, 70)))


class OpenPipe(Anchored):
    """A Pipe along an open spine; references on the elements at its ends and bends; then spine
    lines drawn the other way (`WHICH`: their indexes, or None for every line)."""

    abstract = True
    area = "anchor_pipe_line_flips"
    AXES = ("M3", "E3")
    DRAW = ()
    TRANSITION = "Right corner"
    WHICH = None

    @property
    def PLACES(self):
        return [(x, 0, z) for x, z in [self.DRAW[0][0]] + [end for _, end in self.DRAW]]

    def build(self, doc):
        body = m.body(doc)
        geometry = [Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in self.DRAW]
        path = m.sketch(doc, "Path", geometry, body, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2) + [m.circle(0, 0, 0.8)], body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = self.TRANSITION
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        self.anchor(doc, body, pipe)

    def edit(self, doc):
        drawnTheOtherWay(doc.Path, None if self.WHICH is None else self.WHICH)


SPINES = {"L": L, "Z": Z, "U": U, "L2": L2, "Z2": Z2}
RUNS = [(s, t) for s in ("L", "Z", "U") for t in ("Right corner", "Round corner")] + [
    ("L2", "Transformed"),
    ("Z2", "Transformed"),
]
for _spine, _transition in RUNS:
    _draw = SPINES[_spine]
    for _which in [[k] for k in range(len(_draw))] + [None]:
        _what = "AllLines" if _which is None else f"Line{_which[0]}"
        _name = f"OpenPipe{_spine}{_transition.split()[0]}{_what}Reversed"
        globals()[_name] = type(
            _name,
            (OpenPipe,),
            {
                "__module__": __name__,
                "__doc__": f"The {_spine} spine, '{_transition}': "
                + ("every line" if _which is None else f"line {_which[0]}")
                + " drawn the other way, its id kept (the solid is unchanged).",
                "abstract": False,
                "DRAW": _draw,
                "TRANSITION": _transition,
                "WHICH": _which,
                "REFS": refNames(len(_draw) + 1),
            },
        )
