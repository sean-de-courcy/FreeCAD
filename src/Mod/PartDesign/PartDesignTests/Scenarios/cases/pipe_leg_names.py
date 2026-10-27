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

"""Corpus cases (ops#501, class B): a Pipe's or Sweep's legs, corners and joints under edits of the
spine (the ops repo's `corpus/predicted/B.json`).

Ports (one designed representative per rule where the row is a family):
- `rows261_315|fixed_pipe_sweep_end_rules`, the leg and joint rules 304, 312, 314, 315:
  `UPipeAllLinesDrawnTheOtherWay` (304: a joint's vertex names follow the line direction),
  `LPipeHoleFirstLineDrawnTheOtherWay` (312: `placeOn`'s u follows the sweep direction),
  `UPipeRoundCornersAllLinesDrawnTheOtherWay` (314: Round corner faces from the spine vertex),
  `LPipeHoleAwayFromTheEndsAllLinesDrawnTheOtherWay` (315: the profile away from the path's ends,
  the lines reversed);
- `rows222_277_302|fixed_pos_rules`: `CapBetweenPiecesWhenTheBreakMoves` (302: PR 369 round 4, the cap and its edges between the
  union's pieces when the break moves to the other corner); row 277 (PR 344 round 3, an L whose
  corner is edited across 90 degrees) is `TransformedLAcross90` in `anchor_paths.py`, whose datum
  points on each element can't be fooled by a swap of the two legs; row 222 (ops#360 H2, an up-to cap
  piece that covers a whole face) is in `upto_wall_and_cap_names.py`;
- `row328|ops485_two_arc_hole_first_line_reversed`: `LPipeHoleOfTwoArcsFirstLineDrawnTheOtherWay`;
- `row323|ops486_point_inserted_mid_line`: `PointInsertedMidLine<Path><Transition>` (six paths,
  the probes `k_ZZ_hole_ins_R`, `x_I_ZZ_Round_insmid`, `k_S3_hole_ins`, `k_ZZleft_hole_ins`,
  `k_S3left_hole_ins`, `k_Z4_hole_ins` of `work/pr369-r5v/adv2.py`);
- `rows283_301|redrawn_line_new_identity`: `LPipeFirstLineRedrawn` (301),
  `SweepArcSpineRedrawn` (283);
- `ops479|pipe_binding_loops_hash_order`: `TransformedUPipeHoleFirstLegLonger`.

`ops480|round_hole_bend_arcs_4_to_3` is class A's `PipeBendMirroredLeg` (`cases/pipe_arcs.py`), the
same model, edit and datum points, so it is not ported twice.

The Pipe cases share a model builder (`MarkedPipe`): a PartDesign AdditivePipe of a profile (a
square, or a square with a round hole, or with a hole of two arcs) along a polyline in an XZ
sketch, and datum points on the elements nearest to chosen places (the corners of the spine):
`PER` edges, vertices and faces each, taken from the model as built, each reference's
expectation the element at its own place (built from the element's end points, centre of mass
and size). The edits that keep the solid (lines drawn the other way, a collinear point inserted
into a line, a line drawn again in place) leave every element where it was; the others say
where they go (`SHIFT`, the rigid move of the corners).
Lines are drawn the other way with their geometry ids kept (`reverseLine`)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    BROKEN,
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


def turned(z, degrees, length):
    """In an XZ sketch: the end of a leg of `length` from (0, z), turned `degrees` from +Z
    towards +X."""
    return (length * math.sin(math.radians(degrees)), z + length * math.cos(math.radians(degrees)))


def reverseLine(sketch, index):
    """The line at `index` drawn the other way, its geometry id kept (through a point off both
    ends: a line can't have its end points equal)."""
    geometry = sketch.Geometry
    line = geometry[index]
    start, end = V(line.StartPoint), V(line.EndPoint)
    line.StartPoint, line.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
    line.StartPoint, line.EndPoint = end, start
    sketch.Geometry = geometry


def line(p, q):
    return Part.LineSegment(V(*p, 0), V(*q, 0))


# ---------------------------------------------------------------------------------------------
# Elements described from the model as built
# ---------------------------------------------------------------------------------------------


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


class MarkedPipe(Scenario):
    """A Pipe along `POINTS` (an XZ sketch), its profile `PROFILE` at `PROFILE_AT`, and a datum
    point on each of the elements nearest to the `CENTRES` ((name, place)), `PER` of each kind
    (e, v, f). A subclass edits (`edit`, or `steps`); `SHIFT` is how far the elements near the
    centres have moved after the edit (the corners move rigidly together), and `gone(key)`
    says whether an element has no successor (BROKEN)."""

    abstract = True
    area = "pipe_leg_names"
    CLASSES = ("B",)
    AXES = ("M3", "E3")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    POINTS = ((0, 0), (0, 30), (20, 30))
    PROFILE = "square"
    PROFILE_AT = (0, 0, 0)
    TRANSITION = "Right corner"
    CENTRES = ()
    PER = {"e": 4, "v": 4}
    SHIFT = V()
    COUNTS = None  # the number of elements there should be of each kind, for a sanity check

    def profileGeometry(self):
        if self.PROFILE == "square":
            return m.rectangle(-2, -2, 2, 2)
        if self.PROFILE == "small hole":
            return m.rectangle(-1, -1, 1, 1) + [m.circle(0, 0, 0.4)]
        if self.PROFILE == "hole":
            return m.rectangle(-3, -3, 3, 3) + [m.circle(0, 0, 1)]
        if self.PROFILE == "two arc hole":
            circle = m.circle(0, 0, 0.4)
            return m.rectangle(-1, -1, 1, 1) + [
                Part.ArcOfCircle(circle, 0, math.pi),
                Part.ArcOfCircle(circle, math.pi, 2 * math.pi),
            ]
        raise ScenarioError(self.PROFILE)

    def build(self, doc):
        self.shift = V()
        body = m.body(doc)
        self.path = m.sketch(doc, "Path", m.polyline(self.POINTS), body, placement=XZ)
        self.profile = m.sketch(doc, "Profile", self.profileGeometry(), body)
        self.profile.Placement = App.Placement(V(*self.PROFILE_AT), App.Rotation())
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.Transition = self.TRANSITION
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise ScenarioError(f"the pipe is invalid: {pipe.getStatusString()}")
        shape = pipe.Shape
        if self.COUNTS:
            counts = {k: len(elementsOf(shape, k)) for k in self.COUNTS}
            if counts != self.COUNTS:
                raise ScenarioError(f"the pipe has {counts} elements, not {self.COUNTS}")
        self.elements = {}
        for centre, at, *own in self.CENTRES:
            for kind, count in (own[0] if own else self.PER).items():
                found = nearest(shape, kind, at, count)
                if len(found) != count:
                    raise ScenarioError(f"{centre}: {len(found)} {kind} elements, not {count}")
                for i, element in enumerate(found):
                    key = f"{centre}_{kind}{i}"
                    self.elements[key] = (kind, element)
                    point = body.newObject("PartDesign::Point", "On_" + key)
                    point.AttachmentSupport = [(pipe, self.names(pipe, like(element, kind))[0])]
                    point.MapMode = "Vertex" if kind == "v" else "CenterOfMass"
                    self.ref(key, point, "AttachmentSupport", self.expectation(key), Attached())

    def expectation(self, key):
        kind, element = self.elements[key]

        def expect():
            if self.stepName is None:
                return like(element, kind)
            if self.gone(key):
                return BROKEN
            return like(element, kind, self.SHIFT)

        return expect

    def gone(self, key):
        return False


# ---------------------------------------------------------------------------------------------
# Lines drawn the other way (rows 304, 312, 314, 315, 328)
# ---------------------------------------------------------------------------------------------

U_POINTS = ((0, 0), (0, 30), (20, 30), (20, 10))
CORNER_1, CORNER_2 = ("c1", (0, 0, 30)), ("c2", (20, 0, 30))


class UPipeAllLinesDrawnTheOtherWay(MarkedPipe):
    """Row 304: a 4 x 4 square along the U (up 30, +X 20, down 20), "Right corner"; every line
    drawn the other way. The solid is the same: each corner's four joint edges and vertices stay
    (ops#415 round 4: the joints' vertex names, compounds of the spine vertex's name, followed
    the line direction and shared a part with the next corner's)."""

    POINTS = U_POINTS
    CENTRES = (CORNER_1, CORNER_2)
    PER = {"e": 4, "v": 4}
    REFS = refsNear(CENTRES, PER)

    def edit(self, doc):
        for index in range(doc.Path.GeometryCount):
            reverseLine(doc.Path, index)


class LPipeHoleFirstLineDrawnTheOtherWay(MarkedPipe):
    """Row 312: a 6 x 6 square with a round hole of radius 1 along the L (up 30, +X 20),
    "Right corner"; the first line drawn the other way. The hole's sides along the two legs
    meet at the corner in four arcs and their vertices, told apart by where they lie on the
    hole, and the sweep now runs the other way along the first leg: each stays (ops#415 round 8,
    `placeOn`'s u followed the sweep direction: the arcs went to their mirrors, 1.35 mm)."""

    PROFILE = "hole"
    CENTRES = (("c1", (0, 0, 30)),)
    PER = {"e": 8, "v": 8}
    REFS = refsNear(CENTRES, PER)

    def edit(self, doc):
        reverseLine(doc.Path, 0)


class UPipeRoundCornersAllLinesDrawnTheOtherWay(MarkedPipe):
    """Row 314: the U of a 4 x 4 square with "Round corner": every line drawn the other way. The
    solid is the same; the round faces, their edges and vertices at each bend stay (ops#478,
    their names came from the spine vertex, which is read in the line's direction: 21 mm)."""

    POINTS = U_POINTS
    TRANSITION = "Round corner"
    CENTRES = (CORNER_1, CORNER_2)
    PER = {"e": 4, "v": 4, "f": 4}
    REFS = refsNear(CENTRES, PER)

    def edit(self, doc):
        for index in range(doc.Path.GeometryCount):
            reverseLine(doc.Path, index)


class LPipeHoleAwayFromTheEndsAllLinesDrawnTheOtherWay(MarkedPipe):
    """Row 315: as row 312, the 6 x 6 square with a round hole drawn along the first leg, at
    z = 15 (away from the path's ends), and every line drawn the other way: the arcs and
    vertices at the corner stay (ops#415 round 9, `runsAgainst` read the sweep's direction only
    from an end copy of the profile)."""

    PROFILE = "hole"
    PROFILE_AT = (0, 0, 15)
    CENTRES = (("c1", (0, 0, 30)),)
    PER = {"e": 8, "v": 8}
    REFS = refsNear(CENTRES, PER)

    def edit(self, doc):
        for index in range(doc.Path.GeometryCount):
            reverseLine(doc.Path, index)


class LPipeHoleOfTwoArcsFirstLineDrawnTheOtherWay(MarkedPipe):
    """Row 328 (ops#485): a 2 x 2 square with a hole of radius 0.4 drawn as two half circles
    along the L (up 30, +X 20), "Right corner"; the first line drawn the other way. The solid is
    the same and every element stays: the corner's elements and the long faces and edges of
    the hole along the legs (`adv.py` PROFILE=hole2arc SPINE=L EDIT=flip0 compares the pipe's
    58 elements; the hole's long faces and edges were the broken ones: their names came from
    the profile's arcs, PRJ at one end of the sweep and GEN at the other)."""

    PROFILE = "two arc hole"
    CENTRES = (
        ("c1", (0, 0, 30)),
        ("leg2", (10, 0, 30), {"e": 4, "f": 4}),
        ("leg1", (0, 0, 15), {"e": 4, "f": 4}),
    )
    PER = {"e": 6, "v": 4, "f": 4}
    REFS = refsNear(CENTRES, PER)

    def edit(self, doc):
        reverseLine(doc.Path, 0)


# ---------------------------------------------------------------------------------------------
# A point inserted into a line (row 323, ops#486)
# ---------------------------------------------------------------------------------------------


class PointInsertedMidLine(MarkedPipe):
    """A 2 x 2 square with a round hole of radius 0.4 along a polyline of 30 and 20 mm legs,
    the elements within 2.6 mm of each corner (the nearest `PER` of each kind); then a point
    inserted into the second line at its middle (it is cut at the middle, its first half keeps
    its geometry id, the second half is a new line). The solid is the same (a collinear joint
    added): every element stays where it was. A corner key built from the two edges
    around it names the corner differently once one of them is a new edge (ops#486): the
    corner's elements broke or warned (`adv2.py` EDIT=insmid)."""

    abstract = True
    AXES = ("M3", "E5")
    PROFILE = "small hole"
    PER = {"e": 4, "v": 4}
    PATH = ()

    @property
    def POINTS(self):
        return self.PATH

    @property
    def CENTRES(self):
        return tuple((f"c{i}", (x, 0, z)) for i, (x, z) in enumerate(self.PATH[1:-1], 1))

    def edit(self, doc):
        (ax, az), (bx, bz) = self.PATH[1], self.PATH[2]
        middle = ((ax + bx) / 2, (az + bz) / 2)
        m.setLines(doc.Path, {1: ((ax, az), middle)})
        doc.Path.addGeometry(line(middle, (bx, bz)), False)


PATHS = {
    "S3": ((0, 0), (0, 30), (20, 30), (20, 60)),
    "S3Left": ((0, 0), (0, 30), (-20, 30), (-20, 60)),
    "ZZ": ((0, 0), (0, 30), (20, 30), (20, 60), (40, 60), (40, 90)),
    "ZZLeft": ((0, 0), (0, 30), (-20, 30), (-20, 60), (-40, 60), (-40, 90)),
    "Z4": ((0, 0), (0, 30), (20, 30), (20, 10), (40, 10), (40, 40)),
}


def pointInserted(name, path, transition, per):
    corners = len(PATHS[path]) - 2
    refs = refsNear([f"c{i}" for i in range(1, corners + 1)], per)
    cls = type(
        name,
        (PointInsertedMidLine,),
        {
            "__module__": __name__,
            "__doc__": f"{path} with a hole, {transition}: a point inserted into the second line.",
            "PATH": PATHS[path],
            "TRANSITION": transition,
            "PER": per,
            "REFS": refs,
        },
    )
    return cls


PointInsertedMidLineZZRightCorner = pointInserted(
    "PointInsertedMidLineZZRightCorner", "ZZ", "Right corner", {"e": 4, "v": 4}
)
PointInsertedMidLineZZRoundCorner = pointInserted(
    "PointInsertedMidLineZZRoundCorner", "ZZ", "Round corner", {"e": 4, "v": 4, "f": 3}
)
PointInsertedMidLineS3RoundCorner = pointInserted(
    "PointInsertedMidLineS3RoundCorner", "S3", "Round corner", {"e": 6, "v": 4}
)
PointInsertedMidLineS3LeftRoundCorner = pointInserted(
    "PointInsertedMidLineS3LeftRoundCorner", "S3Left", "Round corner", {"e": 6, "v": 4}
)
PointInsertedMidLineZZLeftRoundCorner = pointInserted(
    "PointInsertedMidLineZZLeftRoundCorner", "ZZLeft", "Round corner", {"e": 4, "v": 4}
)
PointInsertedMidLineZ4RoundCorner = pointInserted(
    "PointInsertedMidLineZ4RoundCorner", "Z4", "Round corner", {"e": 4, "v": 4}
)


# ---------------------------------------------------------------------------------------------
# A hole across a Transformed U, its first leg longer (ops#479: loops in hash order)
# ---------------------------------------------------------------------------------------------


def threeLegs(extra=0.0):
    """In an XZ sketch: up 30 + `extra`, then 20 turned 40 degrees from +Z towards +X, then 20
    turned 20 degrees more"""
    points = [(0.0, 0.0), (0.0, 30.0 + extra)]
    heading = 0.0
    for turn in (40, 20):
        heading += turn
        x, z = points[-1]
        a = math.radians(heading)
        points.append((x + 20 * math.sin(a), z + 20 * math.cos(a)))
    return tuple(points)


class TransformedUPipeHoleFirstLegLonger(MarkedPipe):
    """ops#479: a 6 x 6 square with a round hole of radius 1 along the spine up 30, then 20
    turned 40 degrees, then 20 turned 20 degrees more ("Transformed" does not join a right
    angle), the first leg made 4 longer (both corners move up by 4, the other legs keep their
    shape). The binding loops of a Pipe (`bindBreak`, `sweptFrom`, `generated`, `bindEnds`) were
    walked in hash or storage order, which varies between runs, platforms and hash seeds; the
    corners' elements, here the hole's arcs and their vertices and the outer joint, must stay at
    their corners, the same in every process (tier F runs a second hash seed: a verdict that
    differs is flaky)."""

    AXES = ("M3", "X2")
    PROFILE = "hole"
    POINTS = threeLegs()
    TRANSITION = "Transformed"
    CENTRES = (("c1", (0, 0, 30)), ("c2", tuple(V(threeLegs()[2][0], 0, threeLegs()[2][1]))))
    PER = {"e": 6, "v": 6}
    REFS = refsNear(CENTRES, PER)
    SHIFT = V(0, 0, 4)

    def edit(self, doc):
        points = threeLegs(4.0)
        m.setLines(doc.Path, {i: (a, b) for i, (a, b) in enumerate(zip(points, points[1:]))})


# ---------------------------------------------------------------------------------------------
# A line drawn again in place (rows 283, 301)
# ---------------------------------------------------------------------------------------------


class LPipeFirstLineRedrawn(MarkedPipe):
    """Row 301 (ops#415 round 1): a 4 x 4 square along the L (up 30, +X 20), "Right corner"; the
    first line is deleted and drawn again in the same place: it has a new geometry id. The solid
    is the same. A leg is named from its spine line's id, so the legs of a redrawn line are new
    elements: that is by design (I-B5, a redrawn line is a new identity), but the model is the
    same and each reference must stay on its element; it never goes to another place silently
    (scored by a plain predicate: a loud break counts as a move out of the right set)."""

    AXES = ("M3", "E5")
    CENTRES = (("c1", (0, 0, 30)), ("leg1", (0, 0, 15), {"e": 4, "f": 4}))
    PER = {"e": 4, "v": 2, "f": 4}
    REFS = refsNear(CENTRES, PER)

    def edit(self, doc):
        doc.Path.delGeometry(0)
        doc.Path.addGeometry(line((0, 0), (0, 30)), False)


class SweepArcSpineRedrawn(Scenario):
    """Row 283 (PR 352 round 1): a Part::Sweep of a 4 x 4 square along a spine of a line up 10
    and a quarter circle of radius 10 turning to +X (tangent to the line), "Right corner". The
    arc is deleted and drawn again in the same place: a new geometry id. The solid is the same.
    The sweep's elements along the arc are named from the arc's id, but the model is the same
    and each reference must stay on its element; it never goes to another place silently (scored
    by a plain predicate: a loud break counts as a move out of the right set). Datum points on
    the four lateral edges and four side faces along the arc."""

    area = "pipe_leg_names"
    CLASSES = ("B",)
    AXES = ("M3", "E5")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    REFS = tuple(f"arc_{k}{i}" for k, n in (("e", 4), ("f", 4)) for i in range(n))

    @staticmethod
    def arcGeometry():
        circle = Part.Circle(V(10, 10, 0), V(0, 0, 1), 10)
        return Part.ArcOfCircle(circle, math.pi / 2, math.pi)

    def build(self, doc):
        path = m.sketch(doc, "Path", [line((0, 0), (0, 10)), self.arcGeometry()], placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2))
        sweep = doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections = [profile]
        sweep.Spine = (path, [])
        sweep.Solid = True
        sweep.Transition = "Right corner"
        doc.recompute()
        if not sweep.isValid():
            raise ScenarioError(f"the sweep is invalid: {sweep.State}")
        shape = sweep.Shape
        # the middle of the arc, 45 degrees round it: (10 - 10 cos 45, 0, 10 + 10 sin 45)
        centre = (10 - 10 * math.cos(math.pi / 4), 0, 10 + 10 * math.sin(math.pi / 4))
        for kind, count in (("e", 4), ("f", 4)):
            found = nearest(shape, kind, centre, count)
            if len(found) != count:
                raise ScenarioError(f"{len(found)} {kind} elements near the arc, not {count}")
            for i, element in enumerate(found):
                key = f"arc_{kind}{i}"
                point = doc.addObject("PartDesign::Point", "On_" + key)
                point.AttachmentSupport = [(sweep, self.names(sweep, like(element, kind))[0])]
                point.MapMode = "CenterOfMass"
                self.ref(
                    key,
                    point,
                    "AttachmentSupport",
                    lambda e=element, k=kind: like(e, k),
                    Attached(),
                )

    def edit(self, doc):
        doc.Path.delGeometry(1)
        doc.Path.addGeometry(self.arcGeometry(), False)


# ---------------------------------------------------------------------------------------------
# The cap between the union's pieces, the break moving to the other corner (row 302)
# ---------------------------------------------------------------------------------------------


class CapBetweenPiecesWhenTheBreakMoves(Scenario):
    """Row 302 (PR 369 round 4, ops#415 round 3): "Transformed" along a U, legs 30, 20 and 20
    from the square at z = 0, turning 80 and then 20 degrees more: past 90 degrees only after
    the second corner, so the union's two pieces meet there and the cap between them shows at
    that corner. A sketch on that cap and a datum point on each of its four edges; then the
    first turn is made 100 degrees (the lines moved, their ids kept): the pieces meet at the
    first corner, and the second corner moves with the edit. The cap is gone (the second corner
    is a plain bend now); each cap edge is the crease of that bend, moved with the corner, and
    stays on it. None goes to the first corner's cap silently (the cap edges were named from
    the one side face they bound, so the cap at the same leg's other end took their names,
    20 mm away)."""

    area = "pipe_leg_names"
    CLASSES = ("B",)
    AXES = ("M3", "E4")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("cap", "edge0", "edge1", "edge2", "edge3")

    @staticmethod
    def points(first):
        result = [(0, 0), (0, 30), turned(30, first, 20)]
        x, z = result[-1]
        dx, dz = turned(0, first + 20, 20)
        result.append((x + dx, z + dz))
        return result

    def build(self, doc):
        body = m.body(doc)
        path = m.sketch(doc, "Path", m.polyline(self.points(80)), body, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise ScenarioError(f"the pipe is invalid: {pipe.getStatusString()}")
        shape = pipe.Shape
        x, z = turned(30, 80, 20)
        second = V(x, 0, z)
        caps = [
            f
            for f in shape.Faces
            if abs(abs(f.normalAt(0, 0).z) - 1) < 1e-9
            and f.CenterOfMass.z > 1
            and (f.CenterOfMass - second).Length < 4
        ]
        if len(caps) != 1:
            raise ScenarioError(f"{len(caps)} caps between the pieces at the second corner")
        cap = caps[0]
        edges = sorted(
            (
                e
                for e in shape.Edges
                if any(e.isSame(own) for own in cap.Edges)
            ),
            key=lambda e: tuple(round(c, 6) for c in e.CenterOfMass),
        )
        if len(edges) != 4:
            raise ScenarioError(f"{len(edges)} edges on the cap")
        self.asBuilt = {"cap": ("f", cap)}
        self.asBuilt.update({f"edge{i}": ("e", e) for i, e in enumerate(edges)})
        sketch = body.newObject("Sketcher::SketchObject", "OnCap")
        sketch.AttachmentSupport = [(pipe, self.names(pipe, like(cap, "f"))[0])]
        sketch.MapMode = "FlatFace"
        self.ref("cap", sketch, "AttachmentSupport", lambda: self.expect("cap"), Attached())
        for i in range(4):
            key = f"edge{i}"
            point = body.newObject("PartDesign::Point", "On_" + key)
            point.AttachmentSupport = [(pipe, self.names(pipe, like(self.asBuilt[key][1], "e"))[0])]
            point.MapMode = "CenterOfMass"
            self.ref(key, point, "AttachmentSupport", lambda k=key: self.expect(k), Attached())

    def expect(self, key):
        kind, element = self.asBuilt[key]
        if self.stepName is None:
            return like(element, kind)
        # the second corner moved with the edit: the element of the first build moved with it,
        # if the edited pipe has one there (a cap edge is the crease of the bend now, the cap
        # is gone)
        x0, z0 = turned(30, 80, 20)
        x1, z1 = turned(30, 100, 20)
        moved = like(element, kind, V(x1 - x0, 0, z1 - z0))
        found = len(moved.select(self.doc.Pipe.Shape))
        if found > 1:
            raise ScenarioError(f"{found} elements of the edited pipe where {key} moved")
        return moved if found == 1 else BROKEN

    def edit(self, doc):
        points = self.points(100)
        m.setLines(doc.Path, {i: (a, b) for i, (a, b) in enumerate(zip(points, points[1:]))})
