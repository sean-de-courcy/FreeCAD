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

"""Corpus cases (ops#501, class B): a Pipe along a closed spine of two edges, several sections or an
auxiliary spine, both edges drawn the other way (the ops repo's `corpus/predicted/B.json`:
`ops469|lens_both_lines_reversed_multisection`, the residual of row 322).

Row 322 is a closed spine of two edges: its two corners lie between the same two edges and are
told apart by which end of an edge each is at (the `s`/`e` suffix of the corner key). Drawing
both edges the other way swaps the ends of both and the corners' keys trade places. B1 (fork
`fix/469`) pairs the key with the stored named start of a Pipe with one profile, and leaves
the residual: the same with several sections or an auxiliary spine (the known-issues list of
the design, I-B3 accepted).

The model here is the smallest one of this kind in which the edit is a null edit (a lens of
two arcs, or the D, changes its solid when it is drawn the other way, since the profile is not
perpendicular to the spine at the corner): a ring, a circle of radius 20 in the XZ plane made
of two half circles drawn as B-splines (reversible in a sketch), swept with the Frenet mode by
a 2 x 2 square lying across the ring at (20, 0, 0). The two arcs meet at (20, 0, 0) and
(-20, 0, 0). Both arcs are drawn the other way (their ids kept); the solid is the same torus.
- `ClosedRingMultisectionBothArcsDrawnTheOtherWay`: a second section, the same square, across the
  ring at (-20, 0, 0) (Multisection, "Transformed");
- `ClosedRingAuxiliaryBothArcsDrawnTheOtherWay`: the Auxiliary mode, an auxiliary spine of two
  half circles of radius 23 about the same centre (left as it is).
The references are datum points on the edges and vertices nearest to each of the two corners
(four of each), the expectation each element at its own place."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    Scenario,
    ScenarioError,
    edge,
    face,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
TOL = 1e-5
R = 20.0


def drawnTheOtherWay(sketch, indices):
    """The lines and B-splines at `indices` drawn the other way, their ids kept."""
    geometry = sketch.Geometry
    for index in indices:
        curve = geometry[index]
        if curve.TypeId == "Part::GeomLineSegment":
            start, end = V(curve.StartPoint), V(curve.EndPoint)
            curve.StartPoint, curve.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
            curve.StartPoint, curve.EndPoint = end, start
        else:
            poles = list(curve.getPoles())[::-1]
            knots = [curve.FirstParameter + curve.LastParameter - k for k in curve.getKnots()[::-1]]
            curve.buildFromPolesMultsKnots(
                poles,
                list(curve.getMultiplicities())[::-1],
                knots,
                curve.isPeriodic(),
                curve.Degree,
                list(curve.getWeights())[::-1],
            )
    sketch.Geometry = geometry


def halfCircles(radius):
    """The circle of `radius` about the origin as two half circles drawn as B-splines: the upper
    from (r, 0) to (-r, 0), the lower back"""
    circle = Part.Circle(V(0, 0, 0), V(0, 0, 1), radius)
    return [
        Part.ArcOfCircle(circle, 0, math.pi).toBSpline(),
        Part.ArcOfCircle(circle, math.pi, 2 * math.pi).toBSpline(),
    ]


def where(element, kind):
    """A place of an element, for ordering: a vertex's point, otherwise its centre of mass"""
    return V(element.Point) if kind == "v" else V(element.CenterOfMass)


def like(element, kind, shift=V()):
    """The predicate for the element of the (edited) shape that is `element` moved by `shift`:
    a vertex by its point, an edge by its end points, centre and length, a face by its centre,
    area and surface"""
    if kind == "v":
        return vertex(V(element.Point) + shift)
    if kind == "e":
        centre, length = V(element.CenterOfMass) + shift, element.Length
        ends = [V(v.Point) + shift for v in element.Vertexes]
        return edge(
            where=lambda e: abs(e.Length - length) < TOL
            and (V(e.CenterOfMass) - centre).Length < TOL
            and len(e.Vertexes) == len(ends)
            and all(min((V(v.Point) - q).Length for v in e.Vertexes) < TOL for q in ends)
        )
    centre, area, surface = V(element.CenterOfMass) + shift, element.Area, type(element.Surface)
    return face(
        where=lambda f: abs(f.Area - area) < TOL * max(1.0, area)
        and (V(f.CenterOfMass) - centre).Length < TOL
        and type(f.Surface) is surface
    )


def elementsOf(shape, kind):
    return {"v": shape.Vertexes, "e": shape.Edges, "f": shape.Faces}[kind]


def nearest(shape, kind, at, count):
    """The `count` elements of `shape` of `kind` nearest to `at` (by their place), each one the
    only element with its description"""
    ordered = sorted(
        elementsOf(shape, kind),
        key=lambda e: (
            round((where(e, kind) - V(*at)).Length, 6),
            tuple(round(c, 6) for c in where(e, kind)),
        ),
    )
    found = []
    for element in ordered:
        if len(like(element, kind).select(shape)) == 1:
            found.append(element)
        if len(found) == count:
            return found
    return found


def refsNear(centres, per):
    """REFS: at each centre ((name, place) or (name, place, per)), `per` ({"e": 4, ...}) edges,
    vertices and faces; `centres` may be names only, with `per` for all"""
    keys = []
    for centre in centres:
        name = centre if isinstance(centre, str) else centre[0]
        own = centre[2] if not isinstance(centre, str) and len(centre) > 2 else per
        keys += [f"{name}_{k}{i}" for k, n in own.items() for i in range(n)]
    return tuple(keys)



CORNERS = (("a", (R, 0, 0)), ("b", (-R, 0, 0)))
PER = {"e": 4, "v": 4}


class ClosedRing(Scenario):
    """A square across a ring of two half circles, datum points near both corners."""

    abstract = True
    area = "pipe_closed_sections"
    CLASSES = ("B",)
    AXES = ("M3", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "port"
    TIER = "F"
    REFS = refsNear(("a", "b"), PER)
    MODE = "Frenet"
    SECTIONS = False
    AUXILIARY = False

    def build(self, doc):
        body = m.body(doc)
        path = m.sketch(doc, "Path", halfCircles(R), body, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-1, -1, 1, 1), body)
        profile.Placement = App.Placement(V(R, 0, 0), App.Rotation())
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = False
        pipe.Mode = self.MODE
        if self.SECTIONS:
            section = m.sketch(doc, "Section", m.rectangle(-1, -1, 1, 1), body)
            section.Placement = App.Placement(V(-R, 0, 0), App.Rotation())
            pipe.Transformation = "Multisection"
            pipe.Sections = [section]
        if self.AUXILIARY:
            auxiliary = m.sketch(doc, "Auxiliary", halfCircles(R + 3), body, placement=XZ)
            pipe.Mode = "Auxiliary"
            pipe.AuxiliarySpine = (auxiliary, [])
        doc.recompute()
        if not pipe.isValid():
            raise ScenarioError(f"the pipe is invalid: {pipe.getStatusString()}")
        shape = pipe.Shape
        for corner, at in CORNERS:
            for kind, count in PER.items():
                found = nearest(shape, kind, at, count)
                if len(found) != count:
                    raise ScenarioError(f"{corner}: {len(found)} {kind} elements, not {count}")
                for i, element in enumerate(found):
                    key = f"{corner}_{kind}{i}"
                    point = body.newObject("PartDesign::Point", "On_" + key)
                    point.AttachmentSupport = [(pipe, self.names(pipe, like(element, kind))[0])]
                    point.MapMode = "Vertex" if kind == "v" else "CenterOfMass"
                    self.ref(
                        key,
                        point,
                        "AttachmentSupport",
                        lambda e=element, k=kind: like(e, k),
                        Attached(),
                    )

    def edit(self, doc):
        drawnTheOtherWay(doc.Path, [0, 1])


class ClosedRingMultisectionBothArcsDrawnTheOtherWay(ClosedRing):
    """Two sections (the square at both corners), Multisection: both arcs drawn the other way."""

    SECTIONS = True


class ClosedRingAuxiliaryBothArcsDrawnTheOtherWay(ClosedRing):
    """Auxiliary mode: both arcs of the spine drawn the other way."""

    AUXILIARY = True
