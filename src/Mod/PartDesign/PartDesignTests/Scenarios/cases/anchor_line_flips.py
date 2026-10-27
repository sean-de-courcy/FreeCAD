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

"""Class B's cases for sketch lines drawn the other way where the solid stays as it was (ops#501;
the ops repo's `corpus/predicted/B.json`, rows `proto_b|sweep_line_reversals|V2s`,
`proto_b|pad_revolution_line_reversals|V2s`, `proto_b|random_every_line_reversed|V2s` and
`row194|ops468_F6a_edge_direction_flips|V2s`; the null-edit audit of `work/501/proto_b.py` and
`work/500-review/flip2.py`). The references are datum points on the elements nearest some places
of the model, found on the tip as built (an element is identified by its geometry: an edge by its
curve, length and middle, a face by its surface, area and centre of mass, a vertex by its point);
the solid is unchanged, so each reference must hold its element at its own place.

- `PartSweep<L|Z>...`: a Part::Sweep of a 4 x 4 square along the L (0,0)-(0,30)-(20,30) or the Z
  (L, then (20,30)-(20,60)) drawn in an XZ sketch, "Right corner"; line 0 or every line drawn the
  other way. Places: the spine's vertices; 2 edges, 2 vertices and 2 faces at each.
- `PadHole...`: a 20 x 10 sketch padded 5, a through-all hole of radius 2 centred on the front
  edge (y = 0), which cuts a half disc out of the front; line `k` of the rectangle drawn the other
  way, or every line. Places: the hole's crossings with the top and bottom faces and the far
  corner; 3 edges, 3 vertices and 2 faces at each.
- `Revolution...`: a 4 x 6 rectangle at x 5..9 revolved 270 degrees about the sketch's V axis;
  line `k` or every line drawn the other way. Places: the centres of the two end faces.
- `Block...`: four fixed models of the kind the random sequences build (a block of a sketched
  polygon padded, bosses, pockets and through-all holes on sketches attached to its top face, a
  fillet or chamfer on an edge); every line of every sketch drawn the other way. The sequences
  themselves (`Scenarios/randomized.py`) are not imported by a case module, so these are four
  models rebuilt by hand, not the 28 models of seeds 1-4.
- `CrossedEdge...` (the twin crossings of a hole across an edge, where the twin vertices' roles
  follow the edge's direction, ops#468 F6a): the Part::MultiFuse of two 10 mm cubes (the second at
  (5,-5,2)) cut by a cylinder (radius 1, at (7.5, 0.3)) crossing the section edge y = 0, z = 2,
  with the fuse's Shapes reordered; and a 360 degree Revolution of a ring (radius 10..20, 5 high)
  with a hole across its top rim, Reversed switched on. In each the solid is the same; the places
  are the crossings. Row 194's pad-and-hole pair (the front line, or every line, drawn the other
  way, the edge the hole crosses) is `PadHoleLine0Reversed` and `PadHoleAllLinesReversed`, whose
  places are the same crossings: a second class with the same model, edit and places was dropped
  (review of fork PR 387, S6)."""

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


Z_AXIS = V(0, 0, 1)
ROW_AXES = {
    "sweep": ("M3", "E3"),
    "pad": ("M1", "E3"),
    "revolution": ("M7", "E3"),
    "block": ("M1", "E3"),
    "cross": ("M4", "E3"),
}


# ---------------------------------------------------------------------------------------------
# Part::Sweep along an L or a Z
# ---------------------------------------------------------------------------------------------

L = (((0, 0), (0, 30)), ((0, 30), (20, 30)))
Z = (((0, 0), (0, 30)), ((0, 30), (20, 30)), ((20, 30), (20, 60)))


class PartSweep(Anchored):
    """A Part::Sweep of a square along a spine of lines in an XZ sketch; lines drawn the other
    way (`WHICH`: their indexes, or None for every line)."""

    abstract = True
    area = "anchor_line_flips"
    AXES = ROW_AXES["sweep"]
    DRAW = ()
    WHICH = None

    @property
    def PLACES(self):
        return [(x, 0, z) for x, z in [self.DRAW[0][0]] + [end for _, end in self.DRAW]]

    def build(self, doc):
        geometry = [Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in self.DRAW]
        path = m.sketch(doc, "Path", geometry, None, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), None)
        sweep = doc.addObject("Part::Sweep", "Pipe")
        sweep.Sections = [profile]
        sweep.Solid = True
        sweep.Frenet = False
        sweep.Spine = (path, [])
        sweep.Transition = "Right corner"
        doc.recompute()
        if not sweep.isValid() or sweep.Shape.isNull():
            raise RuntimeError(f"the sweep is invalid: {sweep.getStatusString()}")
        self.anchor(doc, None, sweep)

    def edit(self, doc):
        drawnTheOtherWay(doc.Path, self.WHICH)


for _spine, _draw in (("L", L), ("Z", Z)):
    for _which in ([0], None):
        _name = f"PartSweep{_spine}{'AllLines' if _which is None else 'Line0'}Reversed"
        globals()[_name] = type(
            _name,
            (PartSweep,),
            {
                "__module__": __name__,
                "__doc__": f"A Part::Sweep along the {_spine}: "
                + ("every line" if _which is None else "line 0")
                + " of the spine drawn the other way, its id kept.",
                "abstract": False,
                "DRAW": _draw,
                "WHICH": _which,
                "REFS": refNames(len(_draw) + 1),
            },
        )


# ---------------------------------------------------------------------------------------------
# Pad and hole, Revolution
# ---------------------------------------------------------------------------------------------


def padHole(doc):
    """A 20 x 10 sketch padded 5, a through-all hole of radius 2 centred on its front edge."""
    body = m.body(doc)
    base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), body)
    m.pad(body, base, 5, "Pad")
    doc.recompute()
    hole = m.sketch(doc, "Hole", [m.circle(10, 0, 2)], body, z=10)
    m.pocketThroughAll(body, hole, "Pocket").Midplane = True
    doc.recompute()
    return body


class PadHole(Anchored):
    abstract = True
    area = "anchor_line_flips"
    AXES = ROW_AXES["pad"]
    PLACES = ((10, 0, 5), (10, 0, 0), (20, 10, 5))
    PER = (3, 3, 2)
    WHICH = None

    def build(self, doc):
        body = padHole(doc)
        self.anchor(doc, body, doc.Pocket)

    def edit(self, doc):
        drawnTheOtherWay(doc.Base, self.WHICH)


class Revolution(Anchored):
    abstract = True
    area = "anchor_line_flips"
    AXES = ROW_AXES["revolution"]
    PLACES = ((7, 0, 3), (0, -7, 3))
    PER = (3, 3, 2)
    WHICH = None

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Prof", m.rectangle(5, 0, 9, 6), body, placement=XZ)
        rev = body.newObject("PartDesign::Revolution", "Rev")
        rev.Profile = profile
        rev.ReferenceAxis = (profile, ["V_Axis"])
        rev.Angle = 270
        doc.recompute()
        self.anchor(doc, body, rev)

    def edit(self, doc):
        drawnTheOtherWay(doc.Prof, self.WHICH)


for _base in (PadHole, Revolution):
    _sketch = "pad rectangle" if _base is PadHole else "profile rectangle"
    for _which in ([0], [1], [2], [3], None):
        _name = f"{_base.__name__}{'AllLines' if _which is None else 'Line%d' % _which[0]}Reversed"
        globals()[_name] = type(
            _name,
            (_base,),
            {
                "__module__": __name__,
                "__doc__": f"The {_sketch}: "
                + ("every line" if _which is None else f"line {_which[0]}")
                + " drawn the other way, its id kept.",
                "abstract": False,
                "WHICH": _which,
                "REFS": refNames(len(_base.PLACES), _base.PER),
            },
        )


# ---------------------------------------------------------------------------------------------
# Four fixed models of the random sequences' kind
# ---------------------------------------------------------------------------------------------


class Block(Anchored):
    """A block of a sketched polygon, padded, with bosses, pockets, holes and a dress-up on
    sketches attached to its top face; every line of every sketch drawn the other way."""

    abstract = True
    area = "anchor_line_flips"
    AXES = ROW_AXES["block"]
    height = 0

    def features(self, doc, body):
        raise NotImplementedError

    def build(self, doc):
        body = m.body(doc)
        self.features(doc, body)
        doc.recompute()
        tip = body.Tip
        if not tip.isValid():
            raise RuntimeError(f"{tip.Name} is invalid: {tip.getStatusString()}")
        self.anchor(doc, body, tip)

    def edit(self, doc):
        for obj in doc.Objects:
            if obj.TypeId == "Sketcher::SketchObject":
                drawnTheOtherWay(obj)

    def block(self, doc, body, points, height):
        """The block: the polygon through `points` padded `height`."""
        self.height = height
        sketch = m.sketch(doc, "Profile", m.polygon(points), body)
        m.pad(body, sketch, height, "Pad")
        doc.recompute()

    def solid(self, doc, body, kind, name, region, size):
        """A boss or pocket of a rectangle (x0, y0, x1, y1), or a through-all hole of a circle
        (x, y) of radius `size`, on a sketch attached to the block's top face."""
        tip = body.Tip
        top = face("plane", normal=Z_AXIS, through=(0, 0, self.height)).one(tip.Shape)[0]
        sketch = body.newObject("Sketcher::SketchObject", name + "Sketch")
        sketch.AttachmentSupport = [(tip, top)]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        if (V(sketch.Placement.Base) - V(0, 0, self.height)).Length > TOL:
            raise RuntimeError(f"{sketch.Name} is placed at {sketch.Placement.Base}")
        if kind == "hole":
            sketch.addGeometry([m.circle(*region, size)], False)
            m.pocketThroughAll(body, sketch, name)
        else:
            sketch.addGeometry(m.rectangle(*region), False)
            (m.pad if kind == "boss" else m.pocket)(body, sketch, size, name)
        doc.recompute()

    def dressUp(self, doc, body, kind, name, where, size):
        """A fillet or a chamfer of the tip's edge `where` (an edge predicate)."""
        tip = body.Tip
        feature = body.newObject(
            "PartDesign::Fillet" if kind == "fillet" else "PartDesign::Chamfer", name
        )
        feature.Base = (tip, where.one(tip.Shape))
        if kind == "fillet":
            feature.Radius = size
        else:
            feature.Size = size
        doc.recompute()


class BlockBossHole(Block):
    """A 30 x 20 x 10 block, an 8 x 8 boss 4 high, a through hole of radius 2.5 in the top."""

    abstract = False
    PLACES = ((0, 0, 10), (8, 8, 14), (22, 10, 10), (30, 20, 0))
    REFS = refNames(4)

    def features(self, doc, body):
        self.block(doc, body, [(0, 0), (30, 0), (30, 20), (0, 20)], 10)
        self.solid(doc, body, "boss", "F1Boss", (4, 4, 12, 12), 4)
        self.solid(doc, body, "hole", "F2Hole", (22, 10), 2.5)


class BlockPocketFillet(Block):
    """A 36 x 24 x 8 block, a 10 x 8 pocket 3 deep, a fillet of radius 1.5 on the vertical edge
    at the origin."""

    abstract = False
    PLACES = ((0, 0, 8), (11, 10, 8), (36, 24, 0), (6, 6, 5))
    REFS = refNames(4)

    def features(self, doc, body):
        self.block(doc, body, [(0, 0), (36, 0), (36, 24), (0, 24)], 8)
        self.solid(doc, body, "pocket", "F1Pocket", (6, 6, 16, 14), 3)
        self.dressUp(doc, body, "fillet", "F2Fillet", edge(direction=Z_AXIS, through=(0, 0, 0)), 1.5)


class BlockCutCornerBossChamfer(Block):
    """A 28 x 18 x 12 block with its back left corner cut (five lines), a 10 x 8 boss 3 high, a
    chamfer of 1 on the top edge at the back."""

    abstract = False
    PLACES = ((2, 16, 12), (17, 8, 15), (28, 0, 0), (14, 18, 12))
    REFS = refNames(4)

    def features(self, doc, body):
        self.block(doc, body, [(0, 0), (28, 0), (28, 18), (4, 18), (0, 14)], 12)
        self.solid(doc, body, "boss", "F1Boss", (12, 4, 22, 12), 3)
        self.dressUp(
            doc, body, "chamfer", "F2Chamfer", edge(direction=V(1, 0, 0), through=(0, 18, 12)), 1
        )


class BlockTwoHolesBossFillet(Block):
    """A 40 x 26 x 6 block, two through holes of radius 3, an 8 x 14 boss 5 high between them, a
    fillet of radius 1 on the vertical edge at the back right."""

    abstract = False
    PLACES = ((10, 13, 6), (30, 13, 6), (20, 13, 11), (40, 26, 3))
    REFS = refNames(4)

    def features(self, doc, body):
        self.block(doc, body, [(0, 0), (40, 0), (40, 26), (0, 26)], 6)
        self.solid(doc, body, "hole", "F1Hole", (10, 13), 3)
        self.solid(doc, body, "hole", "F2Hole", (30, 13), 3)
        self.solid(doc, body, "boss", "F3Boss", (16, 6, 24, 20), 5)
        self.dressUp(doc, body, "fillet", "F4Fillet", edge(direction=Z_AXIS, through=(40, 26, 0)), 1)


# ---------------------------------------------------------------------------------------------
# row 194: the crossed edge's direction
# ---------------------------------------------------------------------------------------------


class CrossedEdgeMultiFuseReordered(Anchored):
    """Two 10 mm cubes, the second at (5,-5,2), fused (Part::MultiFuse), cut by a cylinder of
    radius 1 and height 20 standing at (7.5, 0.3, -3); the cylinder crosses the section edge
    y = 0, z = 2 (the first cube's front face meets the second's bottom) twice. The fuse's Shapes
    are reordered (the solid is the same). The references: the 4 edges, 4 vertices and 3 faces
    nearest the middle of the crossings, (7.5, 0, 2) (A's review, `flip2.py`)."""

    area = "anchor_line_flips"
    AXES = ROW_AXES["cross"]
    PLACES = ((7.5, 0, 2),)
    PER = (4, 4, 3)
    REFS = refNames(1, (4, 4, 3))

    def build(self, doc):
        a = doc.addObject("Part::Box", "A")
        a.Length = a.Width = a.Height = 10
        b = doc.addObject("Part::Box", "B")
        b.Length = b.Width = b.Height = 10
        b.Placement = App.Placement(V(5, -5, 2), App.Rotation())
        fuse = doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [a, b]
        cylinder = doc.addObject("Part::Cylinder", "Cyl")
        cylinder.Radius = 1
        cylinder.Height = 20
        cylinder.Placement = App.Placement(V(7.5, 0.3, -3), App.Rotation())
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base = fuse
        cut.Tool = cylinder
        doc.recompute()
        if not cut.isValid():
            raise RuntimeError(f"the cut is invalid: {cut.getStatusString()}")
        self.anchor(doc, None, cut)

    def edit(self, doc):
        doc.Fuse.Shapes = [doc.B, doc.A]


class CrossedEdgeRevolutionReversed(Anchored):
    """A ring (a 10 x 5 rectangle at x 10..20 revolved 360 degrees about the sketch's V axis) with
    a through hole of radius 1 across its top rim at (0, 20, 5); the Revolution's Reversed
    switched on (the solid is the same). The references: the 4 edges, 4 vertices and 3 faces
    nearest the crossing (A's review, `flip2.py`)."""

    area = "anchor_line_flips"
    AXES = ROW_AXES["cross"]
    PLACES = ((0, 20, 5),)
    PER = (4, 4, 3)
    REFS = refNames(1, (4, 4, 3))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(10, 0, 20, 5), body, placement=XZ)
        rev = body.newObject("PartDesign::Revolution", "Rev")
        rev.Profile = profile
        rev.ReferenceAxis = (profile, ["V_Axis"])
        rev.Angle = 360
        doc.recompute()
        hole = m.sketch(doc, "HoleSketch", [m.circle(0, 20, 1)], body, z=5)
        m.pocketThroughAll(body, hole, "Hole")
        doc.recompute()
        self.anchor(doc, body, doc.Hole)

    def edit(self, doc):
        doc.Rev.Reversed = True
