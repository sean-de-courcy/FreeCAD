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

"""Class B's path-switch cases (ops#501, I-B6, taxonomy PTH x E8: the construction path is not in
the name; the ops repo's `corpus/predicted/B.json`): an edit that builds the same solid by another
internal path, or moves it across a switch between paths.

Rows ported:
- `proto_b|path_switches_same_solid|V2s`: the null path switches of `work/501/proto_b.py` `run_path`
  (output `work/501/out/proto_b.path2.txt`), on the notched Pad (a 20 x 10 x 5 Pad with a through
  Pocket of radius 2 centred on its front top edge: 8 faces, 18 edges, 12 vertices):
  `PadLengthToAPlaneAtTheSameHeight` (Length -> up to a datum plane at z 5),
  `PadSecondSideOfLengthZero` (One side -> Two sides, side 2 of length 0); and on a Revolution
  (the rectangle x 5..9, z 0..6 about Z, 270 degrees; 6 faces, 12 edges, 8 vertices):
  `RevolutionSecondSideOfAngleZero` (Angle -> Two sides, side 2 of angle 0). The solid is
  unchanged, so a datum point on every element's centre of mass (every vertex: on it) must stay
  with its element, found from the element's geometry as built. (The fourth switch of that probe,
  taper 0 -> 1e-9, is `anchor_taper.py`.)
- `rows162_299|fixed_pth|V2s`: the guards of the fixed PTH rows, copied from the general scenarios
  `revolve_uptoface.py` and `pipe_legs.py`. Row 162 (ops#334, a Revolution up to a face): the type
  switched to Angle and back (`RevolutionUpToFaceTypeSwitched`) and the wall turned from 90 to 120
  degrees (`RevolutionUpToFaceWallTurned`). Row 203 (ops#255, one primitive vs sides built apart):
  `RevolutionOneSideToSymmetricToTwoSides`. Row 210 (ops#263, two sides across the axis, an angle
  change): `RevolutionAcrossTheAxisSide2Widened`. Row 211 (ops#271, the BRepFeat fallbacks replaced
  profile edges): `RevolutionUpToFaceProfileChamfered`, an edge added to the profile and removed.
  Row 299 (ops#415, "Transformed" across 90 degrees, PR 369): `TransformedLAcross90` and its three
  siblings.
- `row278|union_vs_one_sweep_past_90|V2s`: the same edit on a profile with a round hole
  (`TransformedHoleLAcross90`, `TransformedHoleLBackAcross90`), the empty cell of notes
  `naming-class-B.md` 5 (PTH x M3 x E8 beyond 90 degrees, a Transformed Pipe with a round hole).
  The design (PLAN decision 91, the PR 344 design): the Pipe is one sweep up to 90 degrees at the
  corner and the union of its pieces past it, and the union's fuse renames the faces it cuts, so a
  reference stays on its own element or breaks loudly, never moves (`OwnOrBroken`).
- `row212|ops290_revolution_two_sides_angle_to_face_top|V2s`: `AcrossTheAxisTwoSidesAngleToFace`
  (`RevolutionAcrossTheAxisStartFaceAngleToFace`, `test_start_top_V2s`, in revolve_uptoface.py)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    Bound,
    Filleted,
    OwnOrBroken,
    ReachesFace,
    Scenario,
    ScenarioError,
    edge,
    face,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
Z = V(0, 0, 1)
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


# ---------------------------------------------------------------------------------------------
# References to every element of a shape that an edit leaves as it is
# ---------------------------------------------------------------------------------------------


def ownPlace(element):
    """The predicate for `element` of a shape that the edit leaves as it is: the element of the
    same kind with its size (area or length) and its centre of mass (a vertex: its point)."""
    kind = element.ShapeType
    if kind == "Vertex":
        return vertex(V(element.Point))
    centre = V(element.CenterOfMass)
    if kind == "Edge":
        size = element.Length
        return edge(
            where=lambda e: abs(e.Length - size) < 1e-6 * max(1.0, size)
            and (V(e.CenterOfMass) - centre).Length < 1e-5
        )
    size = element.Area
    return face(
        where=lambda f: abs(f.Area - size) < 1e-6 * max(1.0, size)
        and (V(f.CenterOfMass) - centre).Length < 1e-5
    )


def centreOf(element):
    return V(element.Point) if element.ShapeType == "Vertex" else V(element.CenterOfMass)


def ordered(elements):
    """The elements in a fixed geometric order: by height, then y, then x of their centres."""
    return sorted(
        elements,
        key=lambda e: tuple(round(c, 4) for c in (centreOf(e).z, centreOf(e).y, centreOf(e).x)),
    )


def labels(counts):
    """REFS: `face0..`, `edge0..`, `vertex0..` for the (faces, edges, vertices) counts."""
    return tuple(
        f"{kind}{i}" for kind, count in zip(("face", "edge", "vertex"), counts) for i in range(count)
    )


class OwnPlaceRefs(Scenario):
    """A datum point on the centre of mass of every face and edge of the tip feature's shape, and
    on every vertex; each must stay at its own place after an edit that leaves the solid as it is."""

    abstract = True
    area = "anchor_paths"
    CLASSES = ("B",)
    AXES = ("M1", "M7", "E8")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"

    def build(self, doc):
        body, tip = self.model(doc)
        shape = tip.Shape
        elements = {
            "face": ordered(shape.Faces),
            "edge": ordered(shape.Edges),
            "vertex": ordered(shape.Vertexes),
        }
        for kind, found in elements.items():
            for i, element in enumerate(found):
                key, place = f"{kind}{i}", ownPlace(element)
                consumer = body.newObject("PartDesign::Point", "On_" + key)
                consumer.AttachmentSupport = [(tip, self.names(tip, place)[0])]
                consumer.MapMode = "Vertex" if kind == "vertex" else "CenterOfMass"
                self.ref(key, consumer, "AttachmentSupport", lambda p=place: p, Attached())


def notchedPad(doc):
    """A 20 x 10 x 5 Pad and a through Pocket (symmetric) of radius 2 centred on its front top
    edge (x 10, y 0), the hole's sketch turned about Z by -90 degrees (its circle starts outside the
    material). Returns (body, pocket)."""
    body = m.body(doc)
    base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), body)
    m.pad(body, base, 5, "Pad")
    doc.recompute()
    at = App.Placement(V(10, 0, 10), App.Rotation(Z, -90))
    hole = m.sketch(doc, "Hole", [m.circle(0, 0, 2)], body, placement=at)
    pocket = m.pocketThroughAll(body, hole, "Pocket")
    pocket.SideType = "Symmetric"
    doc.recompute()
    return body, pocket


class NotchedPadSwitch(OwnPlaceRefs):
    abstract = True
    REFS = labels((8, 18, 12))

    def model(self, doc):
        return notchedPad(doc)


class PadLengthToAPlaneAtTheSameHeight(NotchedPadSwitch):
    """The notched Pad's Length 5 -> up to a datum plane at z 5: the same solid, built by
    BRepFeat or the split instead of the prism."""

    def edit(self, doc):
        plane = doc.addObject("PartDesign::Plane", "At5")
        doc.Body.addObject(plane)
        plane.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        pad = doc.Pad
        pad.Type = "UpToFace"
        pad.UpToFace = (plane, [""])


class PadSecondSideOfLengthZero(NotchedPadSwitch):
    """The notched Pad One side -> Two sides with side 2 of length 0: the same solid, the sides
    built apart."""

    def edit(self, doc):
        pad = doc.Pad
        pad.SideType = "Two sides"
        pad.Length2 = 0


class RevolutionSecondSideOfAngleZero(OwnPlaceRefs):
    """A Revolution of the rectangle x 5..9, z 0..6 about the sketch's V axis (global Z), 270
    degrees; Angle -> Two sides with side 2 of angle 0: the same solid."""

    REFS = labels((6, 12, 8))

    def model(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Prof", m.rectangle(5, 0, 9, 6), body, placement=XZ)
        revolution = body.newObject("PartDesign::Revolution", "Rev")
        revolution.Profile = profile
        revolution.ReferenceAxis = (profile, ["V_Axis"])
        revolution.Angle = 270
        doc.recompute()
        return body, revolution

    def edit(self, doc):
        revolution = doc.Rev
        revolution.SideType = "Two sides"
        revolution.Angle2 = 0


# ---------------------------------------------------------------------------------------------
# Revolutions up to a face (copied from revolve_uptoface.py)
# ---------------------------------------------------------------------------------------------


def ray(theta, radius, z):
    """The point at `radius` from the Z axis, `theta` degrees from +X, at height z."""
    a = math.radians(theta)
    return (radius * math.cos(a), radius * math.sin(a), z)


def slab(theta, thickness, length=30):
    """A rectangle with one long side on the ray at `theta` degrees from the origin, `length`
    long, and `thickness` wide on the counterclockwise side of the ray."""
    a = math.radians(theta)
    u = V(math.cos(a), math.sin(a), 0)
    n = V(-u.y, u.x, 0)
    return [(q.x, q.y) for q in (V(0, 0, 0), u * length, u * length + n * thickness, n * thickness)]


def setPolygon(sketch, points):
    """Moves the polygon drawn by `m.polygon()` (geometry 0..n-1) to new corners; its lines keep
    their geometry IDs."""
    count = len(points)
    m.setLines(sketch, {i: (points[i], points[(i + 1) % count]) for i in range(count)})


def cylinder(radius):
    return face("cylinder", where=lambda f: abs(f.Surface.Radius - radius) < 1e-6)


def wallFace(theta, z):
    """The planar face through the Z axis at `theta` degrees, facing the clockwise side (where
    the sweep comes from), containing the point at radius 15 and height z."""
    a = math.radians(theta)
    return face("plane", normal=V(math.sin(a), -math.cos(a), 0), contains=ray(theta, 15, z))


class RevolutionPath(Scenario):
    """The tags of the Revolution cases."""

    abstract = True
    area = "anchor_paths"
    CLASSES = ("B",)
    AXES = ("M2", "M3", "E8")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"


class RevolvedUpToFaceEdit(RevolutionPath):
    """A plate -30..30 x -30..30 x 0..5 and a wall 5 thick on it (`slab(theta, 5)`, 10 high).
    The profile is the rectangle x 10..20, z 5..10, standing on the plate, revolved up to the
    wall's face: a quarter ring at theta = 90. References: a sketch on the ring's top face
    (z = 10), a fillet (radius 1) on its outer top arc (radius 20, z = 10), a binder of its outer
    cylinder (radius 20), and the Revolution's own up-to face."""

    abstract = True
    REFS = ("sketch_top", "fillet_outer_arc", "binder_outer", "up_to_wall")
    theta = 90
    bottom, topZ = 5, 10  # the profile's bottom and the height of the ring's top face

    def profileGeometry(self):
        return m.rectangle(10, self.bottom, 20, 10)

    def top(self):
        return face("plane", normal=Z, through=(0, 0, 10), contains=ray(30, 15, 10))

    def outerArc(self):
        return edge("circle", center=(0, 0, 10), radius=20)

    def outer(self):
        return cylinder(20)

    def wall(self):
        return wallFace(self.theta, 10)

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        plate = m.sketch(doc, "Plate", m.rectangle(-30, -30, 30, 30), body)
        m.pad(body, plate, 5, name="PlatePad")
        wall = m.pad(body, m.sketch(doc, "Wall", m.polygon(slab(90, 5)), body, z=5), 10, "WallPad")
        doc.recompute()
        profile = m.sketch(doc, "Profile", self.profileGeometry(), body, placement=XZ)
        revolved = body.newObject("PartDesign::Revolution", "Revolved")
        revolved.Profile = profile
        revolved.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        revolved.Type = "UpToFace"
        revolved.UpToFace = (wall, self.names(wall, self.wall()))
        self.ref("up_to_wall", revolved, "UpToFace", self.wall, ReachesFace())
        doc.recompute()
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(revolved, self.names(revolved, self.top())[0])]
        onTop.MapMode = "FlatFace"
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (revolved, self.names(revolved, self.outerArc()))
        fillet.Radius = 1
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(revolved, tuple(self.names(revolved, self.outer())))]
        body.Tip = fillet
        self.ref("sketch_top", onTop, "AttachmentSupport", self.top, Attached())
        self.ref("fillet_outer_arc", fillet, "Base", self.outerArc, Filleted(1))
        self.ref("binder_outer", binder, "Support", self.outer, Bound())


class RevolutionUpToFaceTypeSwitched(RevolvedUpToFaceEdit):
    """Row 162 (ops#334): the type goes to Angle (90 degrees, so the same solid: the sweep, not
    BRepFeat) and back to UpToFace."""

    AXES = ("M2", "M3", "E8")
    steps = ("toAngle", "toFace")

    def toAngle(self, doc):
        doc.Revolved.Type = "Angle"
        doc.Revolved.Angle = 90

    def toFace(self, doc):
        doc.Revolved.Type = "UpToFace"


class RevolutionUpToFaceWallTurned(RevolvedUpToFaceEdit):
    """Row 162 (ops#334): the face the feature revolves up to turns from 90 to 120 degrees."""

    wallThickness = 5

    def edit(self, doc):
        setPolygon(doc.Wall, slab(120, self.wallThickness))
        self.theta = 120


class RevolutionUpToFaceProfileChamfered(RevolvedUpToFaceEdit):
    """Row 211 (ops#271): the profile's corner at (20, 5) gets a chamfer 2 x 2 (a new sketch edge,
    so a new revolved face before or among the others), then the chamfer is removed again."""

    steps = ("chamfer", "unchamfer")
    low = 5

    def chamfer(self, doc):
        sketch, low = doc.Profile, self.low
        m.setLines(sketch, {0: ((10, low), (18, low)), 1: ((20, low + 2), (20, 10))})
        sketch.addGeometry(m.polyline([(18, low), (20, low + 2)]), False)

    def unchamfer(self, doc):
        sketch, low = doc.Profile, self.low
        # The chamfer line is the last geometry: chamfer() adds it after every rectangle
        sketch.delGeometries([sketch.GeometryCount - 1])
        m.setLines(sketch, {0: ((10, low), (20, low)), 1: ((20, low), (20, 10))})


class RevolutionOneSideToSymmetricToTwoSides(RevolutionPath):
    """Row 203 (ops#255; PR 243 round 5): the profile x 10..20, z 5..10 revolved about the Z axis,
    One side, 60 degrees, Refine off; a fillet (radius 1) on the top edge of the start face (the
    profile, at 0 degrees, z = 10). The Revolution goes Symmetric by angle (one solid from -30 to
    30 degrees), then Two sides, 30 and 30 (one solid, the same): its start face is the turned
    profile in each, with the profile's names, and the fillet follows to the top edge at -30
    degrees."""

    REFS = ("start_top",)
    steps = ("symmetric", "twoSides")
    startAngle = 0
    bottom, topZ = 5, 10

    def profileGeometry(self):
        return m.rectangle(10, self.bottom, 20, 10)

    def startTop(self):
        return edge("line", contains=ray(self.startAngle, 15, 10))

    def followedStartTop(self):
        return self.startTop()

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.profileGeometry(), body, placement=XZ)
        revolved = body.newObject("PartDesign::Revolution", "Revolved")
        revolved.Profile = profile
        revolved.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        revolved.Refine = False
        revolved.Type = "Angle"
        revolved.Angle = 60
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (revolved, self.names(revolved, self.startTop()))
        fillet.Radius = 1
        self.ref("start_top", fillet, "Base", self.followedStartTop, Filleted(1))

    def symmetric(self, doc):
        doc.Revolved.SideType = "Symmetric"
        self.startAngle = -30

    def twoSides(self, doc):
        revolved = doc.Revolved
        revolved.SideType = "Two sides"
        revolved.Angle = 30
        revolved.Type2 = "Angle"
        revolved.Angle2 = 30


class AcrossTheAxisTwoSidesAngleToFace(RevolutionPath):
    """Row 212 (ops#290; ops#263 follow-up, PR 259 verification 1, L2; decision 44's edit case):
    a profile of two faces on opposite sides of the Z axis, A x 10..20 and B x -25..-15, z 5..10,
    on the plate and wall (`slab(90, 5)`) of RevolvedUpToFaceEdit, Refine off. Two sides by
    angles, 90 and 30: one solid, whose side 2 ends at -30 degrees for A and at 150 for B. A
    fillet (radius 1) on the top edge of B's side 2 end (z = 10, at 150). Side 1 then goes up to
    the wall's face, so each face is revolved on its own (B from 180 through 270 to 90, across A's
    side 2 at radii 15..20), then back to 90 degrees, then side 2 widens to 40: the fillet follows
    B's end each time."""

    AXES = ("M2", "E8")
    REFS = ("start_top",)
    steps = ("upToWall", "backToAngle", "wider")
    startAngle = 150

    def startTop(self):
        return edge("line", contains=ray(self.startAngle, 20, 10))

    def followedStartTop(self):
        return self.startTop()

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(-30, -30, 30, 30), body)
        m.pad(body, plate, 5, name="PlatePad")
        wallSketch = m.sketch(doc, "Wall", m.polygon(slab(90, 5)), body, z=5)
        self.wallPad = m.pad(body, wallSketch, 10, "WallPad")
        doc.recompute()
        geometry = m.rectangle(10, 5, 20, 10) + m.rectangle(-25, 5, -15, 10)
        profile = m.sketch(doc, "Profile", geometry, body, placement=XZ)
        revolved = body.newObject("PartDesign::Revolution", "Revolved")
        revolved.Profile = profile
        revolved.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        revolved.Refine = False
        revolved.SideType = "Two sides"
        revolved.Type = "Angle"
        revolved.Angle = 90
        revolved.Type2 = "Angle"
        revolved.Angle2 = 30
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (revolved, self.names(revolved, self.startTop()))
        fillet.Radius = 1
        self.ref("start_top", fillet, "Base", self.followedStartTop, Filleted(1))

    def upToWall(self, doc):
        revolved = doc.Revolved
        revolved.Type = "UpToFace"
        revolved.UpToFace = (self.wallPad, self.names(self.wallPad, wallFace(90, 10)))

    def backToAngle(self, doc):
        doc.Revolved.Type = "Angle"

    def wider(self, doc):
        doc.Revolved.Angle2 = 40
        self.startAngle = 140


class RevolutionAcrossTheAxisSide2Widened(AcrossTheAxisTwoSidesAngleToFace):
    """Row 210 (ops#263): the same model, only side 2 widened from 30 to 40 degrees (side 1 by
    angle throughout): the fillet follows B's end from 150 to 140 degrees."""

    AXES = ("M2", "M3", "E8")
    steps = ("wider",)


# ---------------------------------------------------------------------------------------------
# "Transformed" Pipes across 90 degrees (copied from pipe_legs.py)
# ---------------------------------------------------------------------------------------------

Y = V(0, 1, 0)

# m.rectangle(-2, -2, 2, 2): its edges' midpoints and its corners, in the profile's plane
EDGES = {"f1": (0, -2), "f2": (2, 0), "f3": (0, 2), "f4": (-2, 0)}
VERTICES = {"v1": (-2, -2), "v2": (2, -2), "v3": (2, 2), "v4": (-2, 2)}
HOLE = (0.8, 0)  # a point of the round hole (radius 0.8) of the profile with a hole


def point3(pt):
    """A point of the path's sketch (x, y) in 3D: (x, 0, y)"""
    return V(pt[0], 0, pt[1])


def onLeg(leg, uv):
    """The point (u, v) of the profile's plane carried to the middle of `leg` (id, start, end) by
    "Transformed", which keeps the profile's orientation (the legs after a corner are sheared)"""
    _, a, b = leg
    return (point3(a) + point3(b)) * 0.5 + V(1, 0, 0) * uv[0] + Y * uv[1]


def predicate(legs, key):
    """key: '<leg>.f<j>' a side face, '<leg>.v<j>' a lateral edge, '<leg>.h' the hole's wall"""
    where, what = key.split(".")
    leg = legs[where]
    if what == "h":
        return face(contains=onLeg(leg, HOLE))
    if what.startswith("f"):
        return face(contains=onLeg(leg, EDGES[what]))
    _, a, b = leg
    return edge(curve="line", direction=point3(b) - point3(a), contains=onLeg(leg, VERTICES[what]))


def moveLine(sketch, geo, a, b):
    """Moves line `geo`'s ends to a and b, keeping its geometry id"""
    sketch.moveGeometry(geo, 1, V(1234.5, 6789.1, 0))
    sketch.moveGeometry(geo, 2, V(b[0], b[1], 0))
    sketch.moveGeometry(geo, 1, V(a[0], a[1], 0))


def transformedL(degrees, towards):
    """The L of TestPipe's side-face tests: up 30 from the profile, then 20 turned `degrees` from
    +Z towards +X; (DRAW, LEGS), the lines drawn towards the profile with `towards`"""
    end = (20 * math.sin(math.radians(degrees)), 30 + 20 * math.cos(math.radians(degrees)))
    legs = (("A", (0, 0), (0, 30)), ("B", (0, 30), end))
    draw = (((0, 0), (0, 30)), ((0, 30), end))
    if towards:
        draw = ((end, (0, 30)), ((0, 30), (0, 0)))
    return draw, legs


def legRefs(withHole):
    keys = []
    for leg in "AB":
        keys += [f"{leg}.{j}" for j in EDGES]
        keys += [f"{leg}.{j}" for j in VERTICES]
        if withHole:
            keys.append(f"{leg}.h")
    return tuple(keys)


class TransformedAcross90(Scenario):
    """"Transformed" along an L whose corner turns from START degrees to OTHER and back, across
    90: between the one sweep and the union of pieces, the lines moved (their ids kept). A
    reference stays on its own element or breaks loudly: the union's fuse renames the faces it
    cuts in the planes the two legs share (y = +-2), and a reference to one may go missing. It
    never moves to another leg or face (ops#415, the design's Transformed test; PLAN decision
    91). The Pipe's 4 x 4 square profile is at the path's start; the references are the four side
    faces and four lateral edges of each leg (and, with HOLE, the hole's wall), at the legs'
    middles, each a datum point on the element's centre of mass."""

    abstract = True
    area = "anchor_paths"
    CLASSES = ("B",)
    AXES = ("M2", "M3", "E8")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    START, OTHER, TOWARDS = 80, 120, False
    HOLE = False
    steps = ("across", "back")

    def legsNow(self):
        degrees = self.OTHER if self.stepName == "across" else self.START
        return {leg[0]: leg for leg in transformedL(degrees, self.TOWARDS)[1]}

    def expect(self, key):
        """What the reference `key` should hold after the current step: the element at its place
        on its leg, or (after an edit) that or a loud break"""
        found = predicate(self.legsNow(), key)
        return found if self.stepName is None else OwnOrBroken(found)

    def build(self, doc):
        body = m.body(doc)
        draw = transformedL(self.START, self.TOWARDS)[0]
        lines = [Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in draw]
        path = m.sketch(doc, "Path", lines, body, placement=XZ)
        geometry = m.rectangle(-2, -2, 2, 2) + ([m.circle(0, 0, 0.8)] if self.HOLE else [])
        profile = m.sketch(doc, "Profile", geometry, body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Refine = False
        pipe.Spine = (path, [])
        pipe.Transition = "Transformed"
        doc.recompute()
        if not pipe.isValid() or pipe.Shape.isNull():
            raise ScenarioError("model invalid: %s" % pipe.State)
        for key in self.REFS:
            # a datum point on the element's centre of mass: a sketch on a side face would have
            # the plane the two legs share (y = +-2) for both legs
            consumer = body.newObject("PartDesign::Point", "On_" + key.replace(".", "_"))
            consumer.AttachmentSupport = [(pipe, self.names(pipe, self.expect(key))[0])]
            consumer.MapMode = "CenterOfMass"
            self.ref(key, consumer, "AttachmentSupport", lambda k=key: self.expect(k), Attached())

    def turnTo(self, doc, degrees):
        for geo, (a, b) in enumerate(transformedL(degrees, self.TOWARDS)[0]):
            moveLine(doc.Path, geo, a, b)

    def across(self, doc):
        self.turnTo(doc, self.OTHER)

    def back(self, doc):
        self.turnTo(doc, self.START)


class TransformedLAcross90(TransformedAcross90):
    """Row 299: 80 -> 120 -> 80 degrees, the spine from the profile"""

    REFS = legRefs(False)


class TransformedLBackAcross90(TransformedAcross90):
    """Row 299: 120 -> 80 -> 120 degrees (the union first), the spine from the profile"""

    START, OTHER = 120, 80
    REFS = legRefs(False)


class TransformedLAcross90TowardsTheProfile(TransformedAcross90):
    """Row 299: 80 -> 120 -> 80 degrees, the spine drawn towards the profile"""

    TOWARDS = True
    REFS = legRefs(False)


class TransformedLBackAcross90TowardsTheProfile(TransformedAcross90):
    """Row 299: 120 -> 80 -> 120 degrees, the spine drawn towards the profile"""

    START, OTHER, TOWARDS = 120, 80, True
    REFS = legRefs(False)


class TransformedHoleLAcross90(TransformedAcross90):
    """Row 278: the same with a round hole of radius 0.8 in the profile, 80 -> 120 -> 80 degrees:
    the references add each leg's hole wall."""

    AXES = ("M3", "E8")
    HOLE = True
    REFS = legRefs(True)


class TransformedHoleLBackAcross90(TransformedAcross90):
    """Row 278: the same with a round hole, 120 -> 80 -> 120 degrees (the union first)."""

    AXES = ("M3", "E8")
    HOLE = True
    START, OTHER = 120, 80
    REFS = legRefs(True)
