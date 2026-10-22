# SPDX-License-Identifier: LGPL-2.1-or-later

"""A Pipe's and a Sweep's legs (ops#415, the ops repo's notes\\ops415-leg-names.md).

A square -2..2 profile at the origin (XY plane), swept along a path drawn in XZ, "Right corner".
A sketch is attached to each leg's four side faces (FlatFace), its four lateral edges and the
corner edges between two legs (NormalToEdge). After the edit the expected element is found by
geometry: each leg keeps its identity through the edit (it is the same sketch line), and the
element is the one swept from the same profile element along it.

The PartDesign Pipe named its side faces and lateral edges from the profile alone, the legs of
one profile element told apart by their order along the spine: a segment added at the spine's
start, or the spine drawn the other way, moved every reference to another leg silently, in V2s
too. They are named from the spine edge too now, as Part::Sweep's are (fork PR 352). The Sweep
scenarios are guards.
"""

import FreeCAD as App
import Part

from . import harness as h
from . import models as m

V = App.Vector
Y = V(0, 1, 0)
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))

# m.rectangle(-2, -2, 2, 2): its edges' midpoints and its corners, in the profile's plane
EDGES = {"f1": (0, -2), "f2": (2, 0), "f3": (0, 2), "f4": (-2, 0)}
VERTICES = {"v1": (-2, -2), "v2": (2, -2), "v3": (2, 2), "v4": (-2, 2)}


def point3(pt):
    """A point of the path's sketch (x, y) in 3D: (x, 0, y)"""
    return V(pt[0], 0, pt[1])


def onLeg(leg, uv):
    """The point (u, v) of the profile's plane carried to the middle of \a leg (id, start,
    end): the profile's X turns with the leg at a right corner, its Y stays"""
    _, a, b = leg
    d = point3(b) - point3(a)
    d.normalize()
    across = V(d.z, 0, -d.x)
    return (point3(a) + point3(b)) * 0.5 + across * uv[0] + Y * uv[1]


class Shared:
    """The edge where the faces holding two points meet"""

    kind = "Edge"

    def __init__(self, p1, p2, text):
        self.p1, self.p2, self.text = p1, p2, text

    def select(self, shape):
        tol = h.tolerance(shape)
        fa = [f for f in shape.Faces if f.isInside(self.p1, tol, True)]
        fb = [f for f in shape.Faces if f.isInside(self.p2, tol, True)]
        if len(fa) != 1 or len(fb) != 1:
            return []
        return [
            "Edge%d" % i
            for i, e in enumerate(shape.Edges, 1)
            if any(e.isSame(x) for x in fa[0].Edges) and any(e.isSame(x) for x in fb[0].Edges)
        ]

    def one(self, shape):
        names = self.select(shape)
        if len(names) != 1:
            raise h.ScenarioError("%r matches %s, not one element" % (self, names or "nothing"))
        return names

    def __repr__(self):
        return "Shared(%s)" % self.text


def predicate(legs, key):
    """key: '<leg>.f<j>' a side face, '<leg>.v<j>' a lateral edge, '<a><b>.c<j>' the edge
    between legs a and b on the profile's edge j"""
    where, what = key.split(".")
    if what.startswith("c"):
        j = "f" + what[1:]
        return Shared(onLeg(legs[where[0]], EDGES[j]), onLeg(legs[where[1]], EDGES[j]), key)
    leg = legs[where]
    if what.startswith("f"):
        return h.face(contains=onLeg(leg, EDGES[what]))
    _, a, b = leg
    return h.edge(curve="line", direction=point3(b) - point3(a), contains=onLeg(leg, VERTICES[what]))


def refsFor(legs, corners):
    keys = []
    for leg in legs:
        keys += ["%s.%s" % (leg, j) for j in EDGES]
        keys += ["%s.%s" % (leg, j) for j in VERTICES]
    for corner in corners:
        keys += ["%s.c%d" % (corner, j) for j in range(1, 5)]
    return tuple(keys)


class Legs(h.Scenario):
    """The model; a scenario gives the path as drawn (DRAW: its lines in order, sketch x, y),
    its legs before and after the edit (LEGS, AFTER: (id, start, end)), the corners referenced
    and the edit"""

    abstract = True
    area = "PipeLegs"
    kind = "pipe"
    DRAW = ()
    LEGS = ()
    AFTER = None
    REF_LEGS = None
    CORNERS = ()

    @classmethod
    def refs(cls):
        return refsFor(cls.REF_LEGS or [leg[0] for leg in cls.LEGS], cls.CORNERS)

    def legsNow(self):
        legs = self.AFTER if self.stepName == "edit" and self.AFTER is not None else self.LEGS
        return {leg[0]: leg for leg in legs}

    def build(self, doc):
        body = m.body(doc) if self.kind == "pipe" else None
        lines = [Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in self.DRAW]
        path = m.sketch(doc, "Path", lines, body, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), body)
        if self.kind == "pipe":
            solid = body.newObject("PartDesign::AdditivePipe", "Pipe")
            solid.Profile = profile
            solid.Refine = False
        else:
            solid = doc.addObject("Part::Sweep", "Sweep")
            solid.Sections = [profile]
            solid.Solid = True
        solid.Spine = (path, [])
        solid.Transition = "Right corner"
        doc.recompute()
        if not solid.isValid() or solid.Shape.isNull():
            raise h.ScenarioError("model invalid: %s" % solid.State)
        for key in self.REFS:
            sketch = doc.addObject("Sketcher::SketchObject", "On_" + key.replace(".", "_"))
            if body is not None:
                body.addObject(sketch)
            sketch.AttachmentSupport = [
                (solid, self.names(solid, predicate(self.legsNow(), key))[0])
            ]
            sketch.MapMode = "FlatFace" if ".f" in key else "NormalToEdge"
            self.ref(
                key,
                sketch,
                "AttachmentSupport",
                lambda k=key: predicate(self.legsNow(), k),
                h.Attached(),
            )

    def edit(self, doc):
        raise NotImplementedError


L_DRAW = (((0, 0), (0, 30)), ((0, 30), (20, 30)))
L_LEGS = (("A", (0, 0), (0, 30)), ("B", (0, 30), (20, 30)))
U_DRAW = L_DRAW + (((20, 30), (20, 10)),)
U_LEGS = L_LEGS + (("C", (20, 30), (20, 10)),)
MID_DRAW = (((0, -10), (0, 30)), ((0, 30), (20, 30)))
MID_LEGS = (("A", (0, -10), (0, 30)), ("B", (0, 30), (20, 30)))


def addLine(doc, a, b):
    doc.Path.addGeometry(Part.LineSegment(V(*a, 0), V(*b, 0)), False)


def movePoint(sketch, geo, pos, at):
    sketch.moveGeometry(geo, pos, V(at[0], at[1], 0))


def moveLine(sketch, geo, a, b):
    """Moves line `geo`'s ends to a and b, keeping its geometry id"""
    movePoint(sketch, geo, 1, (1234.5, 6789.1))
    movePoint(sketch, geo, 2, b)
    movePoint(sketch, geo, 1, a)


class PipeLegsSegmentAddedAtStart(Legs):
    """ops#415's case: a segment added before the path's start, turning, (-10, 0) -> (0, 0)"""

    abstract = False
    DRAW, LEGS, CORNERS = L_DRAW, L_LEGS, ("AB",)
    AFTER = (("N", (-10, 0), (0, 0)),) + L_LEGS

    def edit(self, doc):
        addLine(doc, (-10, 0), (0, 0))


class PipeLegsCollinearSegmentAddedAtStart(Legs):
    """A segment added before the path's start, going on straight, (0, -10) -> (0, 0)"""

    abstract = False
    DRAW, LEGS, CORNERS = L_DRAW, L_LEGS, ("AB",)
    AFTER = (("N", (0, -10), (0, 0)),) + L_LEGS

    def edit(self, doc):
        addLine(doc, (0, -10), (0, 0))


class PipeLegsProfileMidEdgeSegmentAddedAtStart(Legs):
    """The profile on the first line's middle (the path from (0, -10)), a segment added before
    the start"""

    abstract = False
    DRAW, LEGS, CORNERS = MID_DRAW, MID_LEGS, ("AB",)
    AFTER = (("N", (-10, -10), (0, -10)),) + MID_LEGS

    def edit(self, doc):
        addLine(doc, (-10, -10), (0, -10))


class PipeLegsUPathSegmentAddedAtStart(Legs):
    """A U path (up 30, +X 20, down 20), a segment added before the start"""

    abstract = False
    DRAW, LEGS, CORNERS = U_DRAW, U_LEGS, ("AB", "BC")
    AFTER = (("N", (-10, 0), (0, 0)),) + U_LEGS

    def edit(self, doc):
        addLine(doc, (-10, 0), (0, 0))


class PipeLegsSketchSpineReversed(Legs):
    """The U path's every line drawn the other way, its geometry ids kept: the path runs from
    its old end now, and the pipe starts there"""

    abstract = False
    DRAW, LEGS, CORNERS = U_DRAW, U_LEGS, ("AB", "BC")

    def edit(self, doc):
        for geo, (a, b) in enumerate(self.DRAW):
            moveLine(doc.Path, geo, b, a)


class PipeLegsSegmentAddedAtEnd(Legs):
    """Guard: a segment added after the path's end"""

    abstract = False
    DRAW, LEGS, CORNERS = L_DRAW, L_LEGS, ("AB",)
    AFTER = L_LEGS + (("N", (20, 30), (20, 50)),)

    def edit(self, doc):
        addLine(doc, (20, 30), (20, 50))


class PipeLegsFirstLegLengthened(Legs):
    """Guard: the corner moved up 15, the first leg longer"""

    abstract = False
    DRAW, LEGS, CORNERS = L_DRAW, L_LEGS, ("AB",)
    AFTER = (("A", (0, 0), (0, 45)), ("B", (0, 45), (20, 45)))

    def edit(self, doc):
        movePoint(doc.Path, 0, 2, (0, 45))
        movePoint(doc.Path, 1, 1, (0, 45))
        movePoint(doc.Path, 1, 2, (20, 45))


class PipeLegsLastLegDeleted(Legs):
    """Guard: the U path's last line deleted; the references on its first two legs"""

    abstract = False
    DRAW, LEGS, CORNERS = U_DRAW, U_LEGS, ("AB",)
    AFTER = L_LEGS
    REF_LEGS = ("A", "B")

    def edit(self, doc):
        doc.Path.delGeometry(len(doc.Path.Geometry) - 1)


class PipeLegsSegmentRedrawn(Legs):
    """Guard: the first line deleted and drawn again in place (a new geometry id): the leg is
    named from the new line, and the references follow by its place"""

    abstract = False
    DRAW, LEGS, CORNERS = L_DRAW, L_LEGS, ("AB",)

    def edit(self, doc):
        doc.Path.delGeometry(0)
        addLine(doc, (0, 0), (0, 30))


class SweepLegsSegmentAddedAtStart(PipeLegsSegmentAddedAtStart):
    """Guard: the same edit on a Part::Sweep, which names its legs from the spine (fork PR 352)"""

    kind = "sweep"


class SweepLegsSketchSpineReversed(PipeLegsSketchSpineReversed):
    """Guard: the same edit on a Part::Sweep"""

    kind = "sweep"


for _cls in list(globals().values()):
    if isinstance(_cls, type) and issubclass(_cls, Legs) and not _cls.__dict__.get("abstract", False):
        _cls.REFS = _cls.refs()
