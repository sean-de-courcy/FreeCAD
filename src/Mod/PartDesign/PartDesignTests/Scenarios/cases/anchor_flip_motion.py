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

"""Class B's cases for an input turned over where the solid stays as it was, so the elements of the
moved input follow its motion (ops#501; the ops repo's `corpus/predicted/B.json`, rows
`proto_b|flips_follow_motion|V2s` and `row285|ops433_sweep_profile_turned_over|V2s`; the null-edit
audit of `work/501/proto_b.py`, part N, the `turnProfile` and `padmid` runs). The design (the ops
repo's `notes/naming-class-B.md`, I-B1's flip clause and I-T1): a profile turned over, or a
Midplane Pad's Reversed toggled, leaves the solid as it was but moves the input, and the elements
made of the input move with it: a reference to the element made of the profile's bottom edge
holds, after the edit, the element at the place the bottom edge went to (the mirror place).

The references are datum points on the elements nearest some places of the model, found on the
tip as built; an element is identified by its geometry (an edge by its curve, length and middle, a
face by its surface, area and centre of mass, a vertex by its point). After the edit the expected
element is the one at the moved place. Degenerate edges (length 0, at the pole of a Round corner's
torus) are left out.

- `OpenPipe<L|Z|U><Right|Round>ProfileTurnedOver`, `OpenPipe<L2|Z2>TransformedProfileTurnedOver`
  (8, `flips_follow_motion`): a PartDesign AdditivePipe of a 4 x 4 square with a round hole
  (radius 0.8) in the XY plane at the origin along a spine drawn in an XZ sketch (L: (0,0)-(0,30)-
  (20,30); Z: L and (20,30)-(20,60); U: L and (20,30)-(20,10); L2: (0,0)-(0,30)-(20,40); Z2: L2 and
  (20,40)-(20,70)); the profile sketch turned over, 180 degrees about its X axis (the profile is
  symmetric: the same solid). The motion: the profile's mirror, (x, y, z) to (x, -y, z). Places:
  the spine's vertices, 2 edges, 2 vertices and 2 faces at each.
- `PadMidplaneReversed` (`flips_follow_motion`): a 20 x 10 sketch padded 5 about its plane
  (Midplane), a through-all hole of radius 2 centred on the front edge; Reversed toggled on the
  Pad. The motion: z to -z. Places: the hole's crossings with the top and bottom faces and the far
  corner; 3 edges, 3 vertices and 2 faces at each.
- `PartSweep<L|Z>ProfileTurnedOver` (2, `row285`, ops#433): a Part::Sweep of a 4 x 4 square along
  the L or the Z, "Right corner"; the profile turned over as above, the same motion. On
  integration decision 108 accepts the result (the caps cross the ends)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, face, vertex
from PartDesignTests.Scenarios import models as m


V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
TOL = 1e-4


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


SPINES = {
    "L": (((0, 0), (0, 30)), ((0, 30), (20, 30))),
    "Z": (((0, 0), (0, 30)), ((0, 30), (20, 30)), ((20, 30), (20, 60))),
    "U": (((0, 0), (0, 30)), ((0, 30), (20, 30)), ((20, 30), (20, 10))),
    "L2": (((0, 0), (0, 30)), ((0, 30), (20, 40))),
    "Z2": (((0, 0), (0, 30)), ((0, 30), (20, 40)), ((20, 40), (20, 70))),
}


def turnedOver(doc):
    """The profile sketch turned over: 180 degrees about its X axis."""
    profile = doc.Profile
    profile.Placement = App.Placement(profile.Placement.Base, App.Rotation(V(1, 0, 0), 180))


class Spined(Anchored):
    """A swept square along a spine of lines in an XZ sketch, its places the spine's vertices;
    then the profile turned over (a mirror in y)."""

    abstract = True
    area = "anchor_flip_motion"
    DRAW = ()

    @property
    def PLACES(self):
        return [(x, 0, z) for x, z in [self.DRAW[0][0]] + [end for _, end in self.DRAW]]

    def moved(self, point):
        return V(point.x, -point.y, point.z)

    def edit(self, doc):
        turnedOver(doc)


class OpenPipeProfileTurnedOver(Spined):
    """A PartDesign Pipe of the square with a round hole."""

    abstract = True
    AXES = ("M3", "E3")
    TRANSITION = "Right corner"

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


class PartSweepProfileTurnedOver(Spined):
    """A Part::Sweep of the plain square (ops#433)."""

    abstract = True
    AXES = ("M3", "E3")

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


for _spine, _transition in [(s, t) for s in ("L", "Z", "U") for t in ("Right corner", "Round corner")] + [
    ("L2", "Transformed"),
    ("Z2", "Transformed"),
]:
    _name = f"OpenPipe{_spine}{_transition.split()[0]}ProfileTurnedOver"
    globals()[_name] = type(
        _name,
        (OpenPipeProfileTurnedOver,),
        {
            "__module__": __name__,
            "__doc__": f"The {_spine} spine, '{_transition}': the profile turned over.",
            "abstract": False,
            "DRAW": SPINES[_spine],
            "TRANSITION": _transition,
            "REFS": refNames(len(SPINES[_spine]) + 1),
        },
    )

SWEEP_END_SWAPS = {
    "L": ("p0_e0", "p0_f0", "p2_e1", "p2_f0"),
    "Z": ("p0_e0", "p0_f0", "p3_e0", "p3_f0"),
}

for _spine in ("L", "Z"):
    _name = f"PartSweep{_spine}ProfileTurnedOver"
    globals()[_name] = type(
        _name,
        (PartSweepProfileTurnedOver,),
        {
            "__module__": __name__,
            "__doc__": f"A Part::Sweep along the {_spine}: the profile turned over (ops#433).",
            "abstract": False,
            "DRAW": SPINES[_spine],
            "REFS": refNames(len(SPINES[_spine]) + 1),
            # a turned-over Sweep's ends swap names silently, a known silent case (decision 108):
            # accepted on the end references that do so on integration 69d24e907a
            "ACCEPTED": {f"{r}|V2s": "decision 108" for r in SWEEP_END_SWAPS[_spine]},
        },
    )


class PadMidplaneReversed(Anchored):
    """A 20 x 10 sketch padded 5 about its plane (Midplane), a through-all hole of radius 2
    centred on its front edge; the Pad's Reversed toggled. The solid is symmetric about the
    sketch's plane, so the elements go to their mirror in z."""

    area = "anchor_flip_motion"
    AXES = ("M1", "E3")
    PLACES = ((10, 0, 2.5), (10, 0, -2.5), (20, 10, 2.5))
    PER = (3, 3, 2)
    REFS = refNames(3, (3, 3, 2))

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, base, 5, "Pad")
        pad.Midplane = True
        doc.recompute()
        hole = m.sketch(doc, "Hole", [m.circle(10, 0, 2)], body, z=10)
        m.pocketThroughAll(body, hole, "Pocket").Midplane = True
        doc.recompute()
        self.anchor(doc, body, doc.Pocket)

    def moved(self, point):
        return V(point.x, point.y, -point.z)

    def edit(self, doc):
        doc.Pad.Reversed = not doc.Pad.Reversed
