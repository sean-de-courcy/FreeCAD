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

"""References across a fillet's limit (FreeCAD-CH, ops#300 S3).

At the limit (r = 2 on a 4 mm rib, r = t/2 on a plate) OCCT's fillet and chamfer fail, and the
exact construction (Part's FilletFallback) builds the result, named through the dress-up's own
history. A reference to an element that survives the limit keeps its element by its name, with
no solver entry, as the size goes to the limit and back. A reference to an element the dress-up
consumes at the limit (a full round's top face, a rib's end face, a slot's floor, a vertical
round of zero length) goes missing and fails its owner, with candidates for the user, and is
never re-pointed to the round or sphere patch that consumed it; when the element comes back
below the limit, the reference finds it again by its name.

The dress-ups have Refine off: Refine merges the faces of one surface (the two quarter rounds of
a full round, the two sphere patches meeting at r = t/2), which is a change of its own.
"""

from .harness import (
    Attached,
    Broken,
    Chamfered,
    Filleted,
    Reopens,
    Scenario,
    ScenarioError,
    Settled,
    V,
    X,
    Y,
    Z,
    edge,
    face,
    faceNormal,
    vertex,
)
from . import models as m

TOL = 1e-6
ALL_EDGES = edge(where=lambda e: True)


def sphereFace(center, side):
    """The sphere face centred at `center` whose centre of mass passes `side`."""
    c = V(*center)
    return face(
        "sphere",
        where=lambda f: (f.Surface.Center - c).Length < TOL and side(f.CenterOfMass),
    )


def cylinderFace(through, direction, radius, side=None):
    """The cylinder face of the radius whose axis runs along `direction` through `through` (and
    whose centre of mass passes `side`)."""
    p, d = V(*through), V(*direction)

    def test(f):
        s = f.Surface
        if abs(s.Radius - radius) > TOL or abs(abs(s.Axis.dot(d)) - 1) > 1e-9:
            return False
        if (s.Center - p).cross(d).Length > TOL:
            return False
        return side is None or side(f.CenterOfMass)

    return face("cylinder", where=test)


def frontOf(y):
    """A centre of mass in front of y."""
    return lambda c: c.y < y


class Exact(Settled):
    """The reference holds `expected`'s element by its name: the solver has no report entry for
    it (nothing resolved beyond the exact lookup, no guess, no warning)."""

    def __repr__(self):
        return f"SETTLED-EXACT[{self.expected}]"


class Missing(Broken):
    """The element is gone: the reference breaks and fails its owner, and (solver on) its report
    entry is broken with candidates, none of them taken."""

    def __repr__(self):
        return "BROKEN-MISSING"


class FilletLimit(Scenario):
    """A fillet (or, `kind` "Chamfer", a chamfer) whose size moves to its limit and back. `sizes`
    maps the build and each step to the size, `self.r` is the current step's. Each step sets the
    size, recomputes the dress-up and runs `check()` on its shape. The dress-up is the document's
    object named `kind`."""

    abstract = True
    area = "fillet limit"
    kind = "Fillet"
    limit = 2.0
    sizes = {"build": 1.9, "atLimit": 2.0, "below": 1.9}
    steps = ("atLimit", "below")

    def __init__(self, config):
        super().__init__(config)
        self.r = self.sizes["build"]

    def consumed(self):
        """The elements that vanish at the limit are gone: OCCT's face narrower than its tolerance
        (2 - 1e-8) is built by the construction too."""
        return self.r > self.limit - 1e-7

    @staticmethod
    def sizeProperty(kind):
        return "Radius" if kind == "Fillet" else "Size"

    def setSize(self, doc, r):
        self.r = r
        setattr(doc.getObject(self.kind), self.sizeProperty(self.kind), r)
        doc.recompute()

    def dressUp(self, body, base, predicates, name=None, size=None, kind=None):
        """A fillet or chamfer (`kind`) of the edges the predicates match (each one edge;
        `ALL_EDGES` every edge), of `size` or the build's."""
        doc = body.Document
        doc.recompute()
        kind = kind or self.kind
        names = [
            n
            for p in predicates
            for n in (p.select(base.Shape) if p is ALL_EDGES else self.names(base, p))
        ]
        feature = body.newObject(f"PartDesign::{kind}", name or kind)
        feature.Base = (base, names)
        setattr(feature, self.sizeProperty(kind), self.r if size is None else size)
        feature.Refine = False
        doc.recompute()
        return feature

    def datums(self, body, target, points, consumed=(), limitOnly=()):
        """A datum point per (reference name, predicate method) of `points`, at the element's
        centre of mass (on a vertex: the vertex). The references in `consumed` vanish at the
        limit, those in `limitOnly` exist only there; the others survive every step."""
        for name, predicate in points.items():
            element = predicate()
            point = body.newObject("PartDesign::Point", "On_" + name)
            point.AttachmentSupport = [(target, self.names(target, element))]
            point.MapMode = "Vertex" if element.kind == "Vertex" else "CenterOfMass"
            if name in consumed:
                expect = lambda p=predicate: Missing() if self.consumed() else Exact(p())
            elif name in limitOnly:
                expect = lambda p=predicate: Exact(p()) if self.consumed() else Missing()
            else:
                expect = lambda p=predicate: Exact(p())
            self.ref(name, point, "AttachmentSupport", expect, Attached())

    def check(self, doc):
        """Shape checks after the build and every step."""

    # The steps

    def justBelow(self, doc):
        self.setSize(doc, self.sizes["justBelow"])
        self.check(doc)

    def atLimit(self, doc):
        self.setSize(doc, self.sizes["atLimit"])
        self.check(doc)

    def justAbove(self, doc):
        self.setSize(doc, self.sizes["justAbove"])
        self.check(doc)

    def below(self, doc):
        self.setSize(doc, self.sizes["below"])
        self.check(doc)

    def overThenBelow(self, doc):
        """Over the limit, where the dress-up fails, then back below it."""
        self.setSize(doc, self.limit + 0.1)
        if doc.getObject(self.kind).isValid():
            raise ScenarioError(f"the {self.kind} at {self.r} doesn't fail")
        self.setSize(doc, self.sizes["overThenBelow"])
        self.check(doc)

    def judge(self, ref, step):
        result = super().judge(ref, step)
        if not self.solver or result.verdict not in ("correct", "equivalent", "broken"):
            return result
        expectation = ref.expect()
        rows = self._reportRows(self.doc.getObject(ref.owner), ref.prop)
        record = result.record
        if isinstance(expectation, Exact) and rows:
            result.verdict = "wrong"
            record["detail"] = "the solver resolved it, not its name: " + "; ".join(
                f"{e['status']} tier {e['tier']} ({e.get('evidence', '')})" for e in rows
            )
        elif isinstance(expectation, Missing) and result.verdict == "broken":
            if not rows or not all(e["status"] == "broken" and e["candidates"] for e in rows):
                result.verdict = "wrong"
                record["detail"] = f"no broken report entry with candidates: {rows}"
        record["verdict"] = result.verdict
        return result


class RibLimit(FilletLimit):
    """A rib (30 x 4, 20 high) whose two long top edges are filleted or chamfered: at size 2 the
    top face vanishes. The size goes to 2 - 1e-8 (OCCT leaves a top face 2e-8 wide, narrower than
    its tolerance, which the construction builds as at the limit), to 2, to 2 + 1e-8 (within
    tolerance of the limit), and over the limit to 2.1, where the dress-up fails, then back to
    1.9.

    References: a datum point on the front round or chamfer, a sketch on the end face at x = 0
    (next to them), a second dress-up of size 0.3 on the front round's or chamfer's edge at x = 30
    (all surviving every step), and a datum point on the top face (consumed)."""

    abstract = True
    REFS = ("front", "end_face", "front_edge", "top_face")
    sizes = {
        "build": 1.9,
        "justBelow": 2 - 1e-8,
        "atLimit": 2.0,
        "justAbove": 2 + 1e-8,
        "overThenBelow": 1.9,
    }
    steps = ("justBelow", "atLimit", "justAbove", "overThenBelow")
    length, width, height = 30.0, 4.0, 20.0

    def endFace(self):
        return face("plane", normal=-X, through=(0, 0, 0))

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.height))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.length, self.width), body)
        pad = m.pad(body, profile, self.height)
        edges = [edge("line", direction=X, through=(0, y, self.height)) for y in (0, self.width)]
        dressUp = self.dressUp(body, pad, edges)
        self.datums(
            body, dressUp, {"front": self.front, "top_face": self.topFace}, ("top_face",)
        )
        sketch = m.sketch(doc, "OnEnd", [m.circle(1, 5, 0.5)], body)
        sketch.AttachmentSupport = [(dressUp, self.names(dressUp, self.endFace()))]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        second = self.dressUp(body, dressUp, [self.frontEdge()], name=self.kind + "2", size=0.3)
        self.ref(
            "end_face", sketch, "AttachmentSupport", lambda: Exact(self.endFace()), Attached()
        )
        outcome = Filleted(0.3) if self.kind == "Fillet" else Chamfered(0.3)
        self.ref("front_edge", second, "Base", lambda: Exact(self.frontEdge()), outcome)


class FilletLimitFullRound(RibLimit):
    __doc__ = RibLimit.__doc__ + """

    Filleted: a full round at r = 2, the second fillet on the front round's arc."""

    def front(self):
        r = self.r
        return cylinderFace((0, r, self.height - r), X, r, frontOf(self.width / 2))

    def frontEdge(self):
        r = self.r
        return edge(
            "circle",
            center=(self.length, r, self.height - r),
            radius=r,
            where=lambda e: e.CenterOfMass.y < self.width / 2,
        )


class ChamferLimitRoof(RibLimit):
    __doc__ = RibLimit.__doc__ + """

    Chamfered: a roof at d = 2, the second chamfer on the front chamfer's edge, which ends in the
    ridge at the limit."""

    kind = "Chamfer"

    def front(self):
        return face("plane", normal=(0, -1, 1), through=(0, 0, self.height - self.r))

    def frontEdge(self):
        return edge("line", direction=(0, 1, 1), through=(self.length, 0, self.height - self.r))


class FilletLimitDomedRib(FilletLimit):
    """A5: the rib (30 x 4, 20 high) with its four top edges and four vertical edges filleted,
    r 1.9 -> 2 -> 1.9. Each top corner gets a sphere patch. At r = 2 the end faces and the top face
    vanish, the rounds of the short top edges have zero length, and the two patches at an end meet
    (one sphere, two faces).

    References: datum points on the sphere patch at the corner (0, 0, 20), on its edge with the
    long top round, on its vertex on the side face y = 0, on the vertical round at (0, 0) and on
    the long top round at y = 0 (surviving); on the end face at x = 0, on the top face and on the
    round of the short top edge at x = 0 (consumed)."""

    REFS = (
        "sphere_patch",
        "sphere_edge",
        "sphere_vertex",
        "vertical_round",
        "top_round",
        "end_face",
        "top_face",
        "end_round",
    )
    length, width, height = 30.0, 4.0, 20.0

    def spherePatch(self):
        r = self.r
        return sphereFace((r, r, self.height - r), frontOf(self.width / 2))

    def sphereEdge(self):
        r = self.r

        def withTheLongRound(e):
            c = e.CenterOfMass
            return abs(c.x - r) < TOL and c.y < self.width / 2

        return edge("circle", center=(r, r, self.height - r), radius=r, where=withTheLongRound)

    def sphereVertex(self):
        return vertex(at=(self.r, 0, self.height - self.r))

    def verticalRound(self):
        r = self.r
        return cylinderFace((r, r, 0), Z, r, frontOf(self.width / 2))

    def topRound(self):
        r = self.r
        return cylinderFace((0, r, self.height - r), X, r, frontOf(self.width / 2))

    def endFace(self):
        return face("plane", normal=-X, through=(0, 0, 0))

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.height))

    def endRound(self):
        r = self.r
        return cylinderFace((r, 0, self.height - r), Y, r)

    def build(self, doc):
        body = m.body(doc)
        L, W, H = self.length, self.width, self.height
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, W), body)
        pad = m.pad(body, profile, H)
        edges = (
            [edge("line", direction=X, through=(0, y, H)) for y in (0, W)]
            + [edge("line", direction=Y, through=(x, 0, H)) for x in (0, L)]
            + [edge("line", direction=Z, through=(x, y, 0)) for x in (0, L) for y in (0, W)]
        )
        fillet = self.dressUp(body, pad, edges)
        points = {
            "sphere_patch": self.spherePatch,
            "sphere_edge": self.sphereEdge,
            "sphere_vertex": self.sphereVertex,
            "vertical_round": self.verticalRound,
            "top_round": self.topRound,
            "end_face": self.endFace,
            "top_face": self.topFace,
            "end_round": self.endRound,
        }
        self.datums(body, fillet, points, ("end_face", "top_face", "end_round"))


class FilletLimitDomedRibReopened(Reopens, FilletLimitDomedRib):
    """FilletLimitDomedRib, saved and reopened at the limit (its broken references with it)
    before the radius goes back to 1.9."""

    steps = ("atLimit", "reopen", "below")


class SlabLimit(FilletLimit):
    """A plate (30 x 20, 4 thick) with all twelve edges dressed up, size 1.9 -> 2 -> 1.9. At
    t/2 the four vertical rounds or chamfers have zero length and the four side faces vanish; the
    top and bottom corner patches at each corner meet and stay two faces. `check()` runs after
    the build and every step: eight corner patches with distinct names, no face of zero area, and
    at the limit nothing left of the vertical rounds or chamfers (a vanished one doesn't come
    back as a face of zero length).

    References: datum points on the top and the bottom corner patch at the corner (0, 0), on the
    top face and on the top round or chamfer at y = 0 (surviving); on the vertical round or
    chamfer at (0, 0) and on the side face at x = 0 (consumed)."""

    abstract = True
    REFS = ("top_patch", "bottom_patch", "top_face", "top_edge", "vertical", "side_face")
    length, width, thickness = 30.0, 20.0, 4.0

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.thickness))

    def sideFace(self):
        return face("plane", normal=-X, through=(0, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.length, self.width), body)
        pad = m.pad(body, profile, self.thickness)
        dressUp = self.dressUp(body, pad, [ALL_EDGES])
        points = {
            "top_patch": self.topPatch,
            "bottom_patch": self.bottomPatch,
            "top_face": self.topFace,
            "top_edge": self.topEdge,
            "vertical": self.vertical,
            "side_face": self.sideFace,
        }
        self.datums(body, dressUp, points, ("vertical", "side_face"))
        self.check(doc)

    def check(self, doc):
        shape = doc.getObject(self.kind).Shape
        faces = shape.Faces
        patches = [i for i, f in enumerate(faces, 1) if self.isPatch(f)]
        names = [shape.getElementMappedName(f"Face{i}") for i in patches]
        if len(patches) != 8 or len(set(map(str, names))) != 8:
            raise ScenarioError(f"{self.r}: corner patches {patches}, names {names}")
        if any(f.Area < 1e-9 for f in faces):
            raise ScenarioError(f"{self.r}: a face of zero area")
        vertical = [i for i, f in enumerate(faces, 1) if self.isVertical(f)]
        if self.consumed() and vertical:
            raise ScenarioError(f"{self.r}: vertical rounds or chamfers {vertical} at the limit")


class FilletLimitRoundedSlab(SlabLimit):
    __doc__ = "A1: " + SlabLimit.__doc__ + """

    Filleted: the corner patches are spheres, which meet on one sphere at r = t/2."""

    def topPatch(self):
        r, t = self.r, self.thickness
        return sphereFace((r, r, t - r), lambda c: c.z > t / 2)

    def bottomPatch(self):
        r, t = self.r, self.thickness
        return sphereFace((r, r, r), lambda c: c.z < t / 2)

    def topEdge(self):
        r, t = self.r, self.thickness
        return cylinderFace((0, r, t - r), X, r, lambda c: c.z > t / 2)

    def vertical(self):
        r = self.r
        return cylinderFace((r, r, 0), Z, r)

    @staticmethod
    def isPatch(f):
        return type(f.Surface).__name__ == "Sphere"

    @staticmethod
    def isVertical(f):
        return type(f.Surface).__name__ == "Cylinder" and abs(abs(f.Surface.Axis.z) - 1) < 1e-9


class ChamferLimitSlab(SlabLimit):
    __doc__ = "A9: " + SlabLimit.__doc__ + """

    Chamfered: the corner patches are triangles through the three points where a corner's chamfer
    lines meet (x + y + z = 2d from the corner); the top and the bottom one meet in a point at
    d = t/2."""

    kind = "Chamfer"

    def topPatch(self):
        return face("plane", normal=(-1, -1, 1), through=(2 * self.r, 0, self.thickness))

    def bottomPatch(self):
        return face("plane", normal=(-1, -1, -1), through=(2 * self.r, 0, 0))

    def topEdge(self):
        return face("plane", normal=(0, -1, 1), through=(0, 0, self.thickness - self.r))

    def vertical(self):
        return face("plane", normal=(-1, -1, 0), through=(self.r, 0, 0))

    @staticmethod
    def isPatch(f):
        n = faceNormal(f)
        return all(abs(abs(c) - 3**-0.5) < 1e-9 for c in (n.x, n.y, n.z))

    @staticmethod
    def isVertical(f):
        n = faceNormal(f)
        return abs(n.z) < 1e-9 and abs(abs(n.x) - 2**-0.5) < 1e-9 and abs(abs(n.y) - 2**-0.5) < 1e-9


class FilletLimitBallEndSlot(FilletLimit):
    """A11: a block (40 x 12, 10 high) with a slot (x 5..35, y 4..8, 6 deep) whose four floor
    edges and four vertical edges are filleted, r 1.9 -> 2 -> 1.9: a ball-end slot at the limit,
    where the floor, the end walls and the short floor rounds vanish.

    References: datum points on the concave sphere patch at the corner (5, 4), on the long floor
    round at y = 4 and on the long wall at y = 4 (surviving); on the floor and on the end wall at
    x = 5 (consumed)."""

    REFS = ("sphere_patch", "floor_round", "side_wall", "floor", "end_wall")
    x0, x1, y0, y1, depth, height = 5.0, 35.0, 4.0, 8.0, 6.0, 10.0

    def floorZ(self):
        return self.height - self.depth

    def spherePatch(self):
        r = self.r
        center = (self.x0 + r, self.y0 + r, self.floorZ() + r)
        return sphereFace(center, frontOf(self.y0 + 2))

    def floorRound(self):
        r = self.r
        return cylinderFace((0, self.y0 + r, self.floorZ() + r), X, r, frontOf(self.y0 + 2))

    def sideWall(self):
        return face("plane", normal=Y, through=(0, self.y0, 0))

    def floor(self):
        return face("plane", normal=Z, through=(0, 0, self.floorZ()))

    def endWall(self):
        return face("plane", normal=X, through=(self.x0, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 40, 12), body)
        m.pad(body, profile, self.height)
        outline = m.rectangle(self.x0, self.y0, self.x1, self.y1)
        slotSketch = m.sketch(doc, "SlotSketch", outline, body, z=self.height)
        slot = m.pocket(body, slotSketch, self.depth, name="Slot")
        z = self.floorZ()
        edges = (
            [edge("line", direction=X, through=(0, y, z)) for y in (self.y0, self.y1)]
            + [edge("line", direction=Y, through=(x, 0, z)) for x in (self.x0, self.x1)]
            + [
                edge("line", direction=Z, through=(x, y, 0))
                for x in (self.x0, self.x1)
                for y in (self.y0, self.y1)
            ]
        )
        fillet = self.dressUp(body, slot, edges)
        points = {
            "sphere_patch": self.spherePatch,
            "floor_round": self.floorRound,
            "side_wall": self.sideWall,
            "floor": self.floor,
            "end_wall": self.endWall,
        }
        self.datums(body, fillet, points, ("floor", "end_wall"))


class FilletLimitRibAgainstWall(FilletLimit):
    """The rib (30 x 4, 20 high) ending against a wall (x 30..34, y -6..10, 30 high), both long
    top edges filleted, r 1.9 -> 2 -> 1.9: the rounds end in the wall's face (a wall end), and at
    the limit the top face vanishes.

    References: datum points on the wall's face towards the rib, on the front round and on the
    free end face at x = 0 (surviving), and on the top face (consumed)."""

    REFS = ("wall_face", "round_front", "end_face", "top_face")
    length, width, height = 30.0, 4.0, 20.0

    def wallFace(self):
        return face("plane", normal=-X, through=(self.length, 0, 0))

    def roundFront(self):
        r = self.r
        return cylinderFace((0, r, self.height - r), X, r, frontOf(self.width / 2))

    def endFace(self):
        return face("plane", normal=-X, through=(0, 0, 0))

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.height))

    def build(self, doc):
        body = m.body(doc)
        L, W, H = self.length, self.width, self.height
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, W), body)
        m.pad(body, profile, H)
        wallSketch = m.sketch(doc, "WallSketch", m.rectangle(L, -6, L + 4, 10), body)
        wall = m.pad(body, wallSketch, 30, name="Wall")
        edges = [edge("line", direction=X, through=(0, y, H)) for y in (0, W)]
        fillet = self.dressUp(body, wall, edges)
        points = {
            "wall_face": self.wallFace,
            "round_front": self.roundFront,
            "end_face": self.endFace,
            "top_face": self.topFace,
        }
        self.datums(body, fillet, points, ("top_face",))


class FilletLimitFullRoundFromLimit(FilletLimit):
    """The full round of FilletLimitFullRound built at the limit (r = 2), r 2 -> 1.9 -> 2: a
    reference made at the limit, to the crest between the two rounds, an element that exists only
    there.

    References: datum points on the crest (gone below the limit, where the top face lies between
    the rounds, and back at it), on the front round and on the end face at x = 0 (surviving)."""

    REFS = ("crest", "round_front", "end_face")
    sizes = {"build": 2.0, "below": 1.9, "atLimit": 2.0}
    steps = ("below", "atLimit")
    length, width, height = 30.0, 4.0, 20.0

    def crest(self):
        return edge("line", direction=X, through=(0, self.width / 2, self.height))

    def roundFront(self):
        r = self.r
        return cylinderFace((0, r, self.height - r), X, r, frontOf(self.width / 2))

    def endFace(self):
        return face("plane", normal=-X, through=(0, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.length, self.width), body)
        pad = m.pad(body, profile, self.height)
        edges = [edge("line", direction=X, through=(0, y, self.height)) for y in (0, self.width)]
        fillet = self.dressUp(body, pad, edges)
        points = {"crest": self.crest, "round_front": self.roundFront, "end_face": self.endFace}
        self.datums(body, fillet, points, limitOnly=("crest",))


class FilletLimitRoundedSlabFromLimit(FilletLimit):
    """The rounded slab of FilletLimitRoundedSlab built at the limit (r = t/2 = 2), r 2 -> 1.9 -> 2:
    references made at the limit, to the edge where the top and the bottom sphere patch at the
    corner (0, 0) meet (below the limit the vertical round lies between them) and to its vertex
    on the side face y = 0.

    References: datum points on that edge and that vertex (gone below the limit, and back at it),
    on the two patches and on the top face (surviving)."""

    REFS = ("equator", "equator_vertex", "top_patch", "bottom_patch", "top_face")
    sizes = {"build": 2.0, "below": 1.9, "atLimit": 2.0}
    steps = ("below", "atLimit")
    length, width, thickness = 30.0, 20.0, 4.0

    def equator(self):
        r, t = self.r, self.thickness

        def atTheCorner(e):
            c = e.CenterOfMass
            return abs(c.z - t / 2) < TOL and c.x < r - 0.1 and c.y < r - 0.1

        return edge("circle", center=(r, r, t / 2), radius=r, where=atTheCorner)

    def equatorVertex(self):
        return vertex(at=(self.r, 0, self.thickness / 2))

    def topPatch(self):
        r, t = self.r, self.thickness
        return sphereFace((r, r, t - r), lambda c: c.z > t / 2)

    def bottomPatch(self):
        r, t = self.r, self.thickness
        return sphereFace((r, r, r), lambda c: c.z < t / 2)

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.thickness))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.length, self.width), body)
        pad = m.pad(body, profile, self.thickness)
        fillet = self.dressUp(body, pad, [ALL_EDGES])
        points = {
            "equator": self.equator,
            "equator_vertex": self.equatorVertex,
            "top_patch": self.topPatch,
            "bottom_patch": self.bottomPatch,
            "top_face": self.topFace,
        }
        self.datums(body, fillet, points, limitOnly=("equator", "equator_vertex"))
