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

"""Corpus cases (ops#501, class B): which end of a Pipe or Sweep carries the profile's names.

Ports, from the ops repo's `corpus/predicted/B.json`:
- `rows261_315|fixed_pipe_sweep_end_rules` (the end-rule rows 261-263, 265, 266, 281, 284: one
  designed representative per rule, below);
- `row264|reversal_and_shift_past_length` (`PipeReversedAndShiftedByItsLength`);
- `row286|multisection_first_section_decides` (`SweepFirstSectionTurnedOver*`).
(The leg, corner and joint rows 304, 312, 314, 315 are in `pipe_leg_names.py`.)

The Pipe model (`PipeEnds`): a PartDesign AdditivePipe of a 4 x 4 square (the profile, in the XY
plane at height `PROFILE_Z`) along a spine in an XZ sketch (`POINTS`, a straight line up Z or an
L). Its start edge, start vertex and start cap are named by the profile (its own names), the
other end's are the projections (PRJ) of the last section; `named` is the height of the end
that carries the profile's names, `other` the other end's. The references, as `TestPipe.py`'s
`TestPipeEndNames` holds them with a fillet and a sketch on the cap: a sketch on each end's cap
(FlatFace), a datum point on each end's edge along X (CenterOfMass) and on each end's vertex.
A phase (`PHASES`) lists the heights each edit leaves them at, as the test's docstrings say:
- `PipeEndStaysWhenProfileCrossesTheMiddle`: the profile at z = 0, the spine 15 -> -15 (a tie:
  the start), then 16 -> -15: the names stay at the start, z = 16 (rows 263 MID, 261);
- `PipeEndStaysWhenProfileSlidesPastTheMiddle`: the spine 0 -> 30, the profile at z = 14, moved
  to z = 16 and then to z = 30: the names stay at z = 0 (263 MOV);
- `PipeEndStaysWhenFarEndShortenedToProfile`: the profile at 0, the spine 30 -> -40, then
  30 -> 0: the names stay at z = 30 (263 SHR);
- `PipeEndFollowsSpineExtendedPastProfile`: the spine 30 -> 0 (profile at its end, z = 0), then
  30 -> -10 and 30 -> -40: the names follow the extended end (261 F1, 263 F1-long);
- `PipeEndStaysWhenSpineDrawnTheOtherWay`, `...ProfileInsideTheSpine`: the line redrawn from the
  other end, its id kept (the solid is the same): the names stay where they were (263 REV, REVm);
- `PipeEndStaysWhenProfileSketchTurnedOver`: the profile sketch turned over in place (180
  degrees about X) at z = 10 of the spine 0 -> 30: the names stay at z = 0 and, the profile
  being turned over, its first edge's names follow it to the mirror edge (y = +2; 265 R1,
  `corpus/predicted/B.json` flips_follow_motion);
- `PipeEndStaysWhenABaseFeatureIsInserted`: a box 100 up made the body's base feature (265 R1);
- `PipeEndStaysWhenATransformedPipeTurnsPastNinetyDegrees`: "Transformed" along an L drawn towards
  the profile, the corner turned from 80 to 120 degrees (the union of pieces) and back (266 R2);
- `NewTransformedPipePastNinetyDegreesNamesTheProfileEnd`: the same L made at 120 degrees and
  edited to 80 (266 N2);
- `MultisectionPipeEndStaysWhenProfileCrossesTheMiddle`: the profile 4 x 4 at z = 14 and a 6 x 6
  section at z = 30, the profile moved to z = 16: both sections decide, the start keeps the
  profile's names (262 MS1);
- `MultisectionPipeEndFollowsExtendedSpine`: a holed 4 x 4 profile at z = 0 and a holed 6 x 6
  section at z = 12, the spine extended to z = 60 (262 MS2).

The Sweep model (`SweepEnds`, as `derived.py`'s `SweepInteriorProfileChamfered`): a Part::Sweep
of the same square along a line up Z, sketches attached NormalToEdge to the two edges on x = 2
and y = 2 and (Translate) to the vertex (-2, 2) at each end:
- `SweepEndsStayWhenProfileCrossesTheMiddle` (281, profile z = 14 -> 16);
- `SweepEndsStayWhenPathLineIsReversed`, `...ProfileAtTheStart` (281: the line reversed, its id
  kept);
- `SweepEndsStayWhenPathStartMovesOutOfTheBand`, `...IntoTheBand` (284: the path's start moved
  across the 1e-4 band of the profile).

The multisection Sweep (`SweepFirstSectionTurnedOver`, row 286 / ops#433's multisection): two
squares, the first at z = 0 (or 10) and the last at z = 30, the first sketch turned over in
place (180 degrees about X): the solid is the same, the first section's edge on y = -2 is now
on y = +2 (the names follow the section's motion) and its end stays at the first section; the
last section's end is not touched by the first section's rule (`dupv.py` multiAlong_flip,
multiInterior_flip). Its edge on x = 2 keeps its place.

The row 264 case (`PipeReversedAndShiftedByItsLength`): the spine 0 -> 30 with the profile at
z = 0, then redrawn the other way and 30 up (60 -> 30): a reversal shifted by the spine's length
reads as the start (z = 60) or as the old start now at the end (z = 30): the two pairings tie.
Nothing in the model tells which, so a reference must break (BROKEN), never move silently."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Predicate,
    Scenario,
    edge,
    face,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
TURNED_OVER = App.Rotation(V(1, 0, 0), 180)


def turned(z, degrees, length):
    """In an XZ sketch: the end of a leg of `length` from (0, z), turned `degrees` from +Z
    towards +X."""
    return (length * math.sin(math.radians(degrees)), z + length * math.cos(math.radians(degrees)))


def reverseLine(sketch, index):
    """Swaps the end points of a line, keeping its geometry id (through a point between them)."""
    geometry = sketch.Geometry
    start, end = V(geometry[index].StartPoint), V(geometry[index].EndPoint)
    geometry[index].StartPoint = start + (end - start) * 0.75
    geometry[index].EndPoint = start
    geometry[index].StartPoint = end
    sketch.Geometry = geometry


def capAt(x, z):
    """The face in the plane z = `z` with a normal along Z (not a side face that happens to
    pass through the same point)"""
    return face("plane", through=(x, 0, z), where=lambda f: abs(abs(f.normalAt(0, 0).z) - 1) < 1e-9)


def endEdge(x, z, sign, outer):
    """The edge of the end section at height `z` (the section centred on `x`) on the side
    `sign` (-1: y < 0) of the section, at least `outer` from its centre: the section's own
    first line, whether a line or a curve, and not the hole's"""

    def test(e):
        return (
            all(abs(v.Z - z) < 1e-6 for v in e.Vertexes)
            and abs(e.CenterOfMass.x - x) < 1e-6
            and sign * e.CenterOfMass.y > outer
        )

    return edge(where=test)


def endCorner(x, z, sign, outer):
    """The vertex of the end section at height `z` that is left (x smaller than the section's
    centre) on the side `sign` of it, at least `outer` from its centre"""
    return Predicate(
        "Vertex",
        f"corner x<{x} y*{sign}>{outer} z={z}",
        [
            lambda v, tol: abs(v.Z - z) < 1e-6
            and v.X < x - outer
            and sign * v.Y > outer
        ],
    )


# ---------------------------------------------------------------------------------------------
# A PartDesign Pipe along a line or an L
# ---------------------------------------------------------------------------------------------


class PipeEnds(Scenario):
    """The Pipe and its references at both ends. A subclass gives the spine (`POINTS`), the
    profile's height, `PHASES`: the model as built first, then after each edit
    ({"named", "other"}: the heights of the two ends; "points": the new spine; "profile": the new
    height of the profile sketch; "flip": the profile turned over; "half": the other end's half
    width (a section of 6 x 6 is 3); "otherx": the other end's x; "base": a base feature
    inserted)."""

    abstract = True
    area = "pipe_end_names"
    CLASSES = ("B",)
    AXES = ("M3", "E3")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    REFS = (
        "named_cap",
        "other_cap",
        "named_edge",
        "other_edge",
        "named_vertex",
        "other_vertex",
    )
    POINTS = ((0, 0), (0, 30))
    PROFILE_Z = 0
    TRANSITION = "Right corner"
    HOLE = False
    SECTION = None  # (height, half width) of a second section
    OUTER = 1.5  # the end sections' edges and vertices at least this far from the centre
    PHASES = ()
    steps = None

    def build(self, doc):
        self.phase = 0
        body = m.body(doc)
        path = m.sketch(doc, "Path", m.polyline(self.POINTS), body, placement=XZ)
        geometry = m.rectangle(-2, -2, 2, 2) + (m.rectangle(-1, -1, 1, 1) if self.HOLE else [])
        profile = m.sketch(doc, "Profile", geometry, body, z=self.PROFILE_Z)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = self.TRANSITION
        pipe.Refine = False
        if self.SECTION:
            z, half = self.SECTION
            geometry = m.rectangle(-half, -half, half, half)
            if self.HOLE:
                geometry += m.rectangle(-1, -1, 1, 1)
            section = m.sketch(doc, "Section", geometry, body, z=z)
            pipe.Transformation = "Multisection"
            pipe.Sections = [section]
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        for key in self.REFS:
            which, kind = key.split("_")
            if kind == "cap":
                sketch = body.newObject("Sketcher::SketchObject", "On_" + key)
                sketch.AttachmentSupport = [(pipe, self.names(pipe, self.target(key)())[0])]
                sketch.MapMode = "FlatFace"
                self.ref(key, sketch, "AttachmentSupport", self.target(key), Attached())
            else:
                point = body.newObject("PartDesign::Point", "On_" + key)
                point.AttachmentSupport = [(pipe, self.names(pipe, self.target(key)())[0])]
                point.MapMode = "Vertex" if kind == "vertex" else "CenterOfMass"
                self.ref(key, point, "AttachmentSupport", self.target(key), Attached())

    def target(self, key):
        """A function giving the element the reference `key` holds after the current phase"""
        which, kind = key.split("_")

        def expect():
            phase = self.PHASES[self.phase]
            z = phase[which]
            half = phase.get("half", 2) if which == "other" else 2
            # the profile's first edge is the one on y = -half, or on y = +half once the profile
            # is turned over (its names follow it; the last section's don't)
            y = half if phase.get("flip") and not (which == "other" and self.SECTION) else -half
            x = phase.get("otherx", 0) if which == "other" else 0
            sign = 1 if y > 0 else -1
            if kind == "cap":
                return capAt(x, z)
            if kind == "edge":
                return endEdge(x, z, sign, self.OUTER)
            return endCorner(x, z, sign, self.OUTER)

        return expect

    def apply(self, doc, index):
        """The edit that leaves the model in phase `index`"""
        self.phase = index
        phase = self.PHASES[index]
        if phase.get("reverse"):
            for i in range(doc.Path.GeometryCount):
                reverseLine(doc.Path, i)
        elif "points" in phase:
            points = phase["points"]
            m.setLines(doc.Path, {i: (a, b) for i, (a, b) in enumerate(zip(points, points[1:]))})
        if "profile" in phase or "flip" in phase:
            rotation = TURNED_OVER if phase.get("flip") else App.Rotation()
            z = phase.get("profile", self.PROFILE_Z)
            doc.Profile.Placement = App.Placement(V(0, 0, z), rotation)
        if phase.get("base"):
            box = doc.addObject("Part::Box", "Box")
            box.Placement = App.Placement(V(0, 0, 100), App.Rotation())
            doc.recompute()
            doc.Body.BaseFeature = box

    def edit(self, doc):
        self.apply(doc, 1)

    def first(self, doc):
        self.apply(doc, 1)

    def second(self, doc):
        self.apply(doc, 2)


class PipeEndStaysWhenProfileCrossesTheMiddle(PipeEnds):
    """The profile at z = 0, the spine 15 -> -15 (a tie: the start carries the names); the spine
    then 16 -> -15, so the profile is nearer the other end: the names stay at the start
    (z = 16), the end at -15 keeps the projections."""

    AXES = ("M3", "E4")

    POINTS = ((0, 15), (0, -15))
    PHASES = (
        {"named": 15, "other": -15},
        {"points": ((0, 16), (0, -15)), "named": 16, "other": -15},
    )


class PipeEndStaysWhenProfileSlidesPastTheMiddle(PipeEnds):
    """The spine 0 -> 30, the profile at z = 14 (nearer the start), moved to z = 16 (past the
    middle) and then to z = 30 (the far end; the solid is the same): the names stay at z = 0."""

    AXES = ("M3", "E4")
    PROFILE_Z = 14
    steps = ("first", "second")
    PHASES = (
        {"named": 0, "other": 30},
        {"profile": 16, "named": 0, "other": 30},
        {"profile": 30, "named": 0, "other": 30},
    )


class PipeEndStaysWhenFarEndShortenedToProfile(PipeEnds):
    """The profile at z = 0, the spine 30 -> -40 (the start is nearer), then shortened to
    30 -> 0, so the profile lies at the other end: the names stay on the unchanged cap at z = 30,
    and the cap at the profile (z = 0) has the projections."""

    AXES = ("M3", "E4")

    POINTS = ((0, 30), (0, -40))
    PHASES = (
        {"named": 30, "other": -40},
        {"points": ((0, 30), (0, 0)), "named": 30, "other": 0},
    )


class PipeEndFollowsSpineExtendedPastProfile(PipeEnds):
    """The spine drawn towards the profile (30 -> 0, the profile at z = 0, the end that carries
    its names), then extended past it to -10 and on to -40: the names follow the extended end."""

    AXES = ("M3", "E3", "E4")
    POINTS = ((0, 30), (0, 0))
    steps = ("first", "second")
    PHASES = (
        {"named": 0, "other": 30},
        {"points": ((0, 30), (0, -10)), "named": -10, "other": 30},
        {"points": ((0, 30), (0, -40)), "named": -40, "other": 30},
    )


class PipeEndStaysWhenSpineDrawnTheOtherWay(PipeEnds):
    """The line 0 -> 30 (the profile at z = 0, at its start) redrawn 30 -> 0, its geometry id
    kept: the solid is the same and the names stay at z = 0."""

    PHASES = (
        {"named": 0, "other": 30},
        {"reverse": True, "named": 0, "other": 30},
    )


class PipeEndStaysWhenSpineDrawnTheOtherWayProfileInsideTheSpine(PipeEnds):
    """The line 10 -> -30 (the profile at z = 0, inside it, nearer the start) redrawn
    -30 -> 10: the solid is the same and the names stay at z = 10."""

    POINTS = ((0, 10), (0, -30))
    PHASES = (
        {"named": 10, "other": -30},
        {"reverse": True, "named": 10, "other": -30},
    )


class PipeEndStaysWhenProfileSketchTurnedOver(PipeEnds):
    """The spine 0 -> 30, the profile at z = 10, its sketch turned over in place (180 degrees
    about X; the solid is the same): the names stay at z = 0, and the profile's first edge
    names the edge that is on y = +2 now, at both ends (a flip: the names follow the motion).
    The pipe's own frame is the profile sketch's; with the ends stored in it, the turn read as a
    reversed spine and the names went to z = 30 (fork PR 356 round 1)."""

    PROFILE_Z = 10
    PHASES = (
        {"named": 0, "other": 30},
        {"profile": 10, "flip": True, "named": 0, "other": 30},
    )


class PipeEndStaysWhenABaseFeatureIsInserted(PipeEnds):
    """The spine drawn towards the profile (30 -> 0, the profile at z = 5), then a box 100 up
    made the body's base feature: the names stay at z = 0 (the pipe's frame is then the base
    feature's)."""

    AXES = ("M3", "E2")

    POINTS = ((0, 30), (0, 0))
    PROFILE_Z = 5
    PHASES = (
        {"named": 0, "other": 30},
        {"base": True, "named": 0, "other": 30},
    )


class TransformedL(PipeEnds):
    """"Transformed" along an L drawn towards the profile (from the second leg's end down to the
    profile at z = 0): the corner at z = 30 is turned from START to OTHER degrees, across 90
    (the union of pieces, ops#370). The names stay at z = 0, the far end's (z = 30 + 20 cos a)
    keeps the projections."""

    AXES = ("M3", "E4")

    abstract = True
    TRANSITION = "Transformed"
    START, OTHER = 80, 120
    steps = ("first", "second")

    @staticmethod
    def points(degrees):
        return (turned(30, degrees, 20), (0, 30), (0, 0))

    @classmethod
    def far(cls, degrees):
        return {"named": 0, "other": 30 + 20 * math.cos(math.radians(degrees)),
                "otherx": 20 * math.sin(math.radians(degrees))}

    @property
    def POINTS(self):
        return self.points(self.START)

    @property
    def PHASES(self):
        return (
            self.far(self.START),
            dict(self.far(self.OTHER), points=self.points(self.OTHER)),
            dict(self.far(self.START), points=self.points(self.START)),
        )


class PipeEndStaysWhenATransformedPipeTurnsPastNinetyDegrees(TransformedL):
    """80 -> 120 -> 80 degrees (fork PR 356 round 1: the union named the spine's start, the
    names went to z = 20 and stayed there back at 80)."""


class NewTransformedPipePastNinetyDegreesNamesTheProfileEnd(TransformedL):
    """Made at 120 degrees (a union from the start), edited to 80 and back: the names are at the
    profile's end (z = 0) each time, as for the one sweep (fork PR 356 round 2: with nothing
    stored the union named the spine's start)."""

    START, OTHER = 120, 80


class MultisectionPipeEndStaysWhenProfileCrossesTheMiddle(PipeEnds):
    """Multisection along z = 0 -> 30, the profile (4 x 4) at z = 14, a section (6 x 6) at
    z = 30; the profile moves to z = 16, past the spine's middle: the start (z = 0) keeps the
    profile's names, the end (z = 30) the section's projections (fork PR 337 round 2: with the
    profile's distance alone the ends swapped)."""

    AXES = ("M3", "E4")
    PROFILE_Z = 14
    SECTION = (30, 3)
    OUTER = 0.5  # the sweep is thinner at the start, 4 x 4 at z = 14 and 6 x 6 at z = 30
    PHASES = (
        {"named": 0, "other": 30, "half": 3},
        {"profile": 16, "named": 0, "other": 30, "half": 3},
    )


class MultisectionPipeEndFollowsExtendedSpine(PipeEnds):
    """Multisection along z = 0 -> 30, a holed 4 x 4 profile at z = 0 and a holed 6 x 6 section
    at z = 12 (more vertices than the profile); the spine's end is extended to z = 60: the start
    keeps the profile's names, the far cap (z = 60) is the section's projection (fork PR 337
    round 3: with distances summed over a section's vertices the ends swapped)."""

    AXES = ("M3", "E4")

    REFS = ("named_cap", "other_cap", "named_edge", "named_vertex")
    HOLE = True
    SECTION = (12, 3)
    PHASES = (
        {"named": 0, "other": 30},
        {"points": ((0, 0), (0, 60)), "named": 0, "other": 60},
    )


class PipeReversedAndShiftedByItsLength(PipeEnds):
    """Row 264: the spine 0 -> 30 with the profile at z = 0 redrawn the other way and shifted up
    by its length, 60 -> 30 (its id kept). The solid is a tube z = 30..60: whether the old start
    (the profile's end) is now its end at z = 30 (a reversal) or its start at z = 60 (the spine's
    start) can't be told from the model, the two pairings tie. The right answer is a loud break
    for the references that carried the old names; the end that took the projections is the same
    either way and isn't judged."""

    AXES = ("M3", "E3", "E4")
    REFS = ("named_cap", "named_edge", "named_vertex")
    PHASES = (
        {"named": 0, "other": 30},
        {"points": ((0, 60), (0, 30)), "named": 60, "other": 30},
    )

    def target(self, key):
        found = super().target(key)

        def expect():
            return found() if self.phase == 0 else BROKEN

        return expect


# ---------------------------------------------------------------------------------------------
# A Part::Sweep along a line up Z
# ---------------------------------------------------------------------------------------------


def sketchOnVertex(doc, obj, predicate, name):
    sketch = doc.addObject("Sketcher::SketchObject", name)
    sketch.AttachmentSupport = [(obj, Scenario.names(obj, predicate)[0])]
    sketch.MapMode = "Translate"
    return sketch


class SweepEnds(Scenario):
    """A Part::Sweep of the square -2..2 along the line up Z (0..30, `PATH`), the profile at
    `PROFILE_Z`, Transition "Right corner". Sketches are attached to the edges on x = 2 and
    y = 2 and to the vertex (-2, 2) at each end (`startZ`, `endZ`: where the ends are now)."""

    abstract = True
    area = "pipe_end_names"
    CLASSES = ("B",)
    AXES = ("M3", "E3")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("start_x2", "start_y2", "start_v", "end_x2", "end_y2", "end_v")
    PATH = [(0, 0), (0, 30)]
    PROFILE_Z = 14
    startZ, endZ = 0, 30

    def build(self, doc):
        path = m.sketch(doc, "Path", m.polyline(self.PATH), placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), z=self.PROFILE_Z)
        sweep = doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections = [profile]
        sweep.Spine = (path, [])
        sweep.Solid = True
        sweep.Transition = "Right corner"
        doc.recompute()
        if not sweep.isValid():
            raise RuntimeError(f"the sweep is invalid: {sweep.State}")
        self.attach(doc, sweep, "start_x2", lambda: self.edgeX2(self.startZ))
        self.attach(doc, sweep, "start_y2", lambda: self.edgeY2(self.startZ))
        self.attachVertex(doc, sweep, "start_v", lambda: self.startZ)
        self.attach(doc, sweep, "end_x2", lambda: self.edgeX2(self.endZ))
        self.attach(doc, sweep, "end_y2", lambda: self.edgeY2(self.endZ))
        self.attachVertex(doc, sweep, "end_v", lambda: self.endZ)

    def attach(self, doc, sweep, ref, predicate):
        sketch = doc.addObject("Sketcher::SketchObject", "On" + ref)
        sketch.AttachmentSupport = [(sweep, self.names(sweep, predicate())[0])]
        sketch.MapMode = "NormalToEdge"
        self.ref(ref, sketch, "AttachmentSupport", predicate, Attached())

    def attachVertex(self, doc, sweep, ref, z):
        predicate = lambda: vertex((-2, 2, z()))  # noqa: E731
        sketch = sketchOnVertex(doc, sweep, predicate(), "On" + ref)
        self.ref(ref, sketch, "AttachmentSupport", predicate, Attached())

    @staticmethod
    def edgeX2(z):
        return edge("line", direction=(0, 1, 0), through=(2, 0, z))

    @staticmethod
    def edgeY2(z):
        return edge("line", direction=(1, 0, 0), through=(0, 2, z))


class SweepEndsStayWhenProfileCrossesTheMiddle(SweepEnds):
    """The square at z = 14 on the path 0..30 moves to z = 16: the plane rule, not the nearest
    end, decides, and the ends keep their edges and vertices (fork PR 352 round 3, row 281)."""

    AXES = ("M3", "E4")

    def edit(self, doc):
        doc.Profile.Placement = App.Placement(V(0, 0, 16), App.Rotation())


class SweepEndsStayWhenPathLineIsReversed(SweepEnds):
    """The square at z = 14 on the path 0..30; the edit reverses the path's line, keeping its
    geometry id: the ends stay where they are, and so do their edges and vertices (row 281)."""

    def edit(self, doc):
        reverseLine(doc.Path, 0)


class SweepEndsStayWhenPathLineIsReversedProfileAtTheStart(SweepEndsStayWhenPathLineIsReversed):
    """As above with the square at the path's start (z = 0)."""

    PROFILE_Z = 0


class SweepEndsStayWhenPathStartMovesOutOfTheBand(SweepEnds):
    """The square at the path's start (z = 0); the edit moves the path's start 2e-4 down, so the
    square lies inside the path, beyond MakePipeShell's tolerance (ops#425, row 284): the ends'
    edges and vertices stay theirs, the start ones moved down with the path's start."""

    AXES = ("M3", "E4")
    PROFILE_Z = 0
    MOVED = -2e-4

    def edit(self, doc):
        m.setLines(doc.Path, {0: ((0, self.MOVED), (0, 30))})
        self.startZ = self.MOVED


class SweepEndsStayWhenPathStartMovesIntoTheBand(SweepEndsStayWhenPathStartMovesOutOfTheBand):
    """The path starts 2e-4 below the square (z = 0); the edit moves its start up to the
    square's plane."""

    PATH = [(0, -2e-4), (0, 30)]
    startZ = -2e-4
    MOVED = 0


# ---------------------------------------------------------------------------------------------
# A Part::Sweep of two sections, the first turned over (row 286)
# ---------------------------------------------------------------------------------------------


class SweepFirstSectionTurnedOver(Scenario):
    """A Part::Sweep of two squares -2..2 along the line up Z (0..30): the first at z = `FIRST`
    (its own names go to the spine's start), the last at z = 30 (its projections at the end).
    The first sketch is turned over in place (180 degrees about X); the solid is the same. The
    first section's names follow its motion: its edge on y = -2 is on y = +2 now, and its end
    stays where the first section is; the last section is untouched and its end keeps its
    names. Both sections lie at their ends, and a rule looking at the first section alone
    (a flip and a reversal give the same inputs, ops#433) swaps the ends instead (`dupv.py`'s
    multiAlong_flip and multiInterior_flip)."""

    abstract = True
    area = "pipe_end_names"
    CLASSES = ("B",)
    AXES = ("M3", "E3")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("start_y", "start_x", "start_cap", "end_y", "end_x", "end_cap")
    FIRST = 0

    def build(self, doc):
        self.flipped = False
        path = m.sketch(doc, "Path", m.polyline([(0, 0), (0, 30)]), placement=XZ)
        first = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), z=self.FIRST)
        last = m.sketch(doc, "Last", m.rectangle(-2, -2, 2, 2), z=30)
        sweep = doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections = [first, last]
        sweep.Spine = (path, [])
        sweep.Solid = True
        sweep.Transition = "Right corner"
        doc.recompute()
        if not sweep.isValid():
            raise RuntimeError(f"the sweep is invalid: {sweep.State}")
        # the first section's edge on y = -2 is the one that moves (to y = +2); its end is at
        # the start, wherever the section lies on the first leg's side of the middle
        for key, z, mode in (
            ("start_y", 0, "NormalToEdge"),
            ("start_x", 0, "NormalToEdge"),
            ("start_cap", 0, "FlatFace"),
            ("end_y", 30, "NormalToEdge"),
            ("end_x", 30, "NormalToEdge"),
            ("end_cap", 30, "FlatFace"),
        ):
            expect = self.target(key, z)
            sketch = doc.addObject("Sketcher::SketchObject", "On" + key)
            sketch.AttachmentSupport = [(sweep, self.names(sweep, expect())[0])]
            sketch.MapMode = mode
            self.ref(key, sketch, "AttachmentSupport", expect, Attached())

    def target(self, key, z):
        def expect():
            if key.endswith("cap"):
                return capAt(0, z)
            if key.endswith("_x"):
                return edge("line", direction=(0, 1, 0), through=(2, 0, z))
            moved = self.flipped and key.startswith("start")
            return edge("line", direction=(1, 0, 0), through=(0, 2 if moved else -2, z))

        return expect

    def edit(self, doc):
        self.flipped = True
        doc.Profile.Placement = App.Placement(V(0, 0, self.FIRST), TURNED_OVER)


class SweepFirstSectionAtTheStartTurnedOver(SweepFirstSectionTurnedOver):
    """The first section at z = 0, the start of the path."""


class SweepFirstSectionInsideThePathTurnedOver(SweepFirstSectionTurnedOver):
    """The first section at z = 10, inside the path 0..30 (the sweep still starts at z = 0)."""

    FIRST = 10
