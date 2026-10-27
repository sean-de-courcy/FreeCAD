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

"""Class B's taper-path cases (ops#501, I-B6: the construction path is not in the name; the ops
repo's `corpus/predicted/B.json`): a Pad's TaperAngle switched from 0 builds the same solid (or,
at one degree, nearly) by the draft path, which names its caps differently from the prism path.

Rows ported:
- `inboxB|PadTaperSwitchKeepsTheTopRimArc_topRim`: `PadTaperSwitchKeepsTheTopRimArc` (the
  attacker's case from `corpus/inbox/B/taper_path.py`, but for its tags and its hole sketch turned
  by -90 degrees about Z, see Models), and two
  variants of its model: `PadTaperSwitchTinyKeepsTheTopRimArc` (TaperAngle 1e-9, the same solid:
  `work/501/taper.py`) and `PadTaperSwitchKeepsTheTopRimArcOfABlindHole` (a blind hole, whose
  top rim arc is the only one: `work/501-review/taper_blind.py`).
- `proto_b|taper_switch_other_refs|V2s`: `PadTaperSwitchTinyOtherElements` (`work/501/proto_b.py`
  path `padhole/taper1e-9`; its output `work/501/out/proto_b.path2.txt`).
- `review501|taper_two_rectangles_redrawn|V2s`: `TaperedTwoRectanglesOneRedrawn`
  (`work/501-review/taper_twowires.py`), with `UntaperedTwoRectanglesOneRedrawn` as its control.

Models. The notched Pad: a 20 x 10 x 5 Pad, and a through Pocket (symmetric) of radius 2 centred
on its front top edge (x 10, y 0), so the hole cuts a half-round notch into the front face (8
faces, 18 edges, 12 vertices); the Pad's TaperAngle goes 0 -> 1e-9 or 1 degree. The hole's sketch is
turned by -90 degrees about Z, which puts its circle's seam at (10, -2), outside the material: the
attacker's unturned circle has its seam at (12, 0), where a 1 degree taper (the front face moves to
y = -0.087 at the top) splits the top rim arc into two edges, so no single edge is the right
answer after the edit (`work/501-review/taper_blind.py` shows the two arcs). The two rectangles:
10 x 10 squares at x 0..10 and 20..30 in one sketch, padded 5 with a 1 degree taper; rectangle 1
is deleted and drawn again after rectangle 2.

References. The other elements (`PadTaperSwitchTinyOtherElements`): every element of the notched
Pad's result but the top rim arc, a datum point on the centre of mass of every face and edge and on
every vertex; the solid is unchanged, so each stays at its own place, found from the element's
geometry as built (its area or length and its centre of mass). The two rectangles: the top cap,
the four top edges and the four top vertices of each; rectangle 2 is untouched by the edit and
holds its elements; rectangle 1's lines are new lines (a redrawn line is a new identity,
`notes/naming-class-B.md` 4.3), so its references may break loudly (`OwnOrBroken`) but never move."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    Attached,
    OwnOrBroken,
    Scenario,
    edge,
    face,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector


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


def labels(prefix, counts):
    """REFS: `<prefix>face0..`, `<prefix>edge0..`, `<prefix>vertex0..` for the (faces, edges,
    vertices) counts."""
    return tuple(
        f"{prefix}{kind}{i}"
        for kind, count in zip(("face", "edge", "vertex"), counts)
        for i in range(count)
    )


def attachTo(scenario, body, owner, key, element, place, expect):
    """A reference to `element` of `owner`'s shape, which `place` (a predicate) selects: a datum
    point on its centre of mass (a vertex: on the vertex), so that a reference on another element
    gives another placement. `expect` gives what it must hold after the edit."""
    sub = scenario.names(owner, place)[0]
    consumer = body.newObject("PartDesign::Point", "On_" + key)
    consumer.AttachmentSupport = [(owner, sub)]
    consumer.MapMode = "Vertex" if element.ShapeType == "Vertex" else "CenterOfMass"
    scenario.ref(key, consumer, "AttachmentSupport", expect, Attached())


def notchedPad(doc, taper=0.0, blind=False):
    """The 20 x 10 x 5 Pad with the half-round notch at the middle of its front top edge; the
    hole's Pocket is through all (symmetric), or `blind` 3 deep from the top. Returns (body, pad,
    pocket).

    The hole's sketch is turned about Z by -90 degrees, so that its circle starts (its seam) at (10,
    -2), outside the material: with a taper the front face moves to y = -0.087 at the top, the
    rim arc then passes the seam at (12, 0) of an unturned circle and would be split in two edges
    there."""
    body = m.body(doc)
    base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), body)
    pad = m.pad(body, base, 5, "Pad")
    pad.TaperAngle = taper
    doc.recompute()
    turned = App.Rotation(V(0, 0, 1), -90)
    if blind:
        at = App.Placement(V(10, 0, 5), turned)
        hole = m.sketch(doc, "Hole", [m.circle(0, 0, 2)], body, placement=at)
        pocket = m.pocket(body, hole, 3, "Pocket")
    else:
        at = App.Placement(V(10, 0, 10), turned)
        hole = m.sketch(doc, "Hole", [m.circle(0, 0, 2)], body, placement=at)
        pocket = m.pocketThroughAll(body, hole, "Pocket")
        pocket.SideType = "Symmetric"
    doc.recompute()
    return body, pad, pocket


def topRimArc():
    return edge(curve="circle", center=(10, 0, 5), radius=2)


class PadTaperSwitchKeepsTheTopRimArc(Scenario):
    """Class B find (ops#501): a Pad's taper switched from 0 moves a hole's top rim arc reference
    to the bottom rim arc, silently (PTH x SLP).

    A 20 x 10 x 5 Pad; a through Pocket of radius 2 centred on the Pad's front top edge (x 10, y
    0), so the hole cuts a half-round notch whose rims are arcs on the top (z 5) and bottom (z 0)
    faces. A sketch is attached to the top rim arc (NormalToEdge). Edit: the Pad's TaperAngle 0 ->
    1 degree (the draft path, `generateSingleExtrusionSide` -> `makeElementDraft`, names the caps
    differently from the prism path; taxonomy PTH, invariant I-B6). The top rim arc is still a
    circle of radius 2 at z 5 (the hole is vertical).

    The attacker's case (corpus/inbox/B/taper_path.py), tags kept: B for the path (I-B6), D for
    tier 1's pick (HG). Its hole sketch is turned so that the rim arc stays one edge under the
    taper (see the module's docstring)."""

    abstract = False
    area = "anchor_taper"
    CLASSES = ("B", "D")
    AXES = ("M1", "E8")
    ISSUE = "ops#501"
    FOUND_BY = "attacker B"
    TIER = "F"
    REFS = ("topRim",)
    TAPER = 1.0
    BLIND = False

    def expect(self):
        return topRimArc()

    def build(self, doc):
        body, pad, pocket = notchedPad(doc, blind=self.BLIND)
        on = doc.addObject("Sketcher::SketchObject", "OnTopRim")
        body.addObject(on)
        on.AttachmentSupport = [(pocket, self.names(pocket, self.expect())[0])]
        on.MapMode = "NormalToEdge"
        self.ref("topRim", on, "AttachmentSupport", self.expect, Attached())

    def edit(self, doc):
        doc.getObject("Pad").TaperAngle = self.TAPER


class PadTaperSwitchTinyKeepsTheTopRimArc(PadTaperSwitchKeepsTheTopRimArc):
    """The same, with TaperAngle 1e-9: the solid is unchanged, the draft path alone differs
    (`work/501/taper.py`)."""

    FOUND_BY = "port"

    TAPER = 1e-9


class PadTaperSwitchKeepsTheTopRimArcOfABlindHole(PadTaperSwitchKeepsTheTopRimArc):
    """The same, with a blind hole (the Pocket 3 deep from the top, so the notch has no bottom rim
    arc): the top rim arc is the only one (`work/501-review/taper_blind.py`)."""

    FOUND_BY = "port"

    BLIND = True


class OwnPlaceRefs(Scenario):
    """References to the elements of a tip feature's shape, each of which must stay at its own
    place after an edit that leaves the solid as it is. Subclasses give `model(doc)` (the body and
    the tip) and `selection(shape)` (the elements, as (key, element) in a fixed order)."""

    abstract = True
    area = "anchor_taper"
    CLASSES = ("B",)
    AXES = ("M1", "E8")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"

    def build(self, doc):
        body, tip = self.model(doc)
        for key, element in self.selection(tip.Shape):
            place = ownPlace(element)
            attachTo(self, body, tip, key, element, place, lambda p=place: p)


class PadTaperSwitchTinyOtherElements(OwnPlaceRefs):
    """`proto_b.py` path `padhole/taper1e-9` (ops#501): the notched Pad, TaperAngle 0 -> 1e-9, the
    solid unchanged. References: every face, edge and vertex of the result but the top rim arc
    (`PadTaperSwitchKeepsTheTopRimArc` has it): 8 faces, 17 edges, 12 vertices, each at its own
    place."""

    REFS = labels("", (8, 17, 12))

    def model(self, doc):
        body, pad, pocket = notchedPad(doc)
        return body, pocket

    def selection(self, shape):
        skipped = set(topRimArc().select(shape))
        edges = [e for i, e in enumerate(shape.Edges, 1) if f"Edge{i}" not in skipped]
        elements = {
            "face": ordered(shape.Faces),
            "edge": ordered(edges),
            "vertex": ordered(shape.Vertexes),
        }
        return [(f"{kind}{i}", e) for kind, es in elements.items() for i, e in enumerate(es)]

    def edit(self, doc):
        doc.getObject("Pad").TaperAngle = 1e-9


class TaperedTwoRectanglesOneRedrawn(Scenario):
    """`taper_twowires.py` (ops#501 review): two 10 x 10 squares in one sketch, x 0..10 and 20..30,
    padded 5 with a 1 degree taper, so the caps of the two wires are told apart by a counter only
    in their draft-path names. Rectangle 1's four lines are deleted and drawn again after
    rectangle 2's. References: each rectangle's top cap, four top edges and four top vertices.
    Rectangle 2 and its elements are untouched: they stay at their places. Rectangle 1's lines are
    new lines (a new identity: its references may break loudly) but its elements must not move."""

    area = "anchor_taper"
    CLASSES = ("B",)
    AXES = ("M1", "E5", "E8")
    ISSUE = "ops#501"
    FOUND_BY = "review501"
    TIER = "F"
    TAPER = 1.0
    REFS = labels("r1_", (1, 4, 4)) + labels("r2_", (1, 4, 4))

    def build(self, doc):
        body = m.body(doc)
        sketch = m.sketch(
            doc, "Base", m.rectangle(0, 0, 10, 10) + m.rectangle(20, 0, 30, 10), body
        )
        pad = m.pad(body, sketch, 5, "Pad")
        pad.TaperAngle = self.TAPER
        doc.recompute()
        if not pad.isValid() or pad.Shape.isNull():
            raise RuntimeError(f"the pad is invalid: {pad.getStatusString()}")
        shape = pad.Shape
        tops = {
            "face": [f for f in shape.Faces if abs(f.CenterOfMass.z - 5) < 1e-6],
            "edge": [e for e in shape.Edges if abs(e.CenterOfMass.z - 5) < 1e-6],
            "vertex": [v for v in shape.Vertexes if abs(v.Point.z - 5) < 1e-6],
        }
        for rectangle, left in (("r1_", True), ("r2_", False)):
            for kind, elements in tops.items():
                mine = [e for e in elements if (centreOf(e).x < 15) == left]
                for i, element in enumerate(ordered(mine)):
                    place = ownPlace(element)
                    # rectangle 1's lines are new lines after the edit: it may break, not move
                    if left:
                        expect = lambda p=place: OwnOrBroken(p)  # noqa: E731
                    else:
                        expect = lambda p=place: p  # noqa: E731
                    attachTo(self, body, pad, f"{rectangle}{kind}{i}", element, place, expect)

    def edit(self, doc):
        sketch = doc.Base
        for index in (3, 2, 1, 0):
            sketch.delGeometry(index)
        sketch.addGeometry(m.rectangle(0, 0, 10, 10), False)


class UntaperedTwoRectanglesOneRedrawn(TaperedTwoRectanglesOneRedrawn):
    """The control: no taper, so the caps are named by the prism path (the probe: all right)."""

    TAPER = 0.0
