# SPDX-License-Identifier: LGPL-2.1-or-later

"""Review pr383-r2's cases: PartDesign Pipes along closed spines, composed edits aimed at the
stored start (fork PR 383 round 2). The model as `pipe_closed.py`'s: an XZ sketch for the spine,
a square profile in the XY plane on it; the ring a closed rectangle of four lines 30 x 20 (at
scale 1; SIZE 30), the profile on its left leg. References: datum points on the joint edges and
vertices nearest each corner, found by points on them taken from the model as built. Every edit
leaves the solid as built (Right corner), so each reference must hold the element at its own
place.

The review's RingSlidThenTopSplit (the top line split at its middle after the slide: 24 correct, 8
quiet on this PR and on integration) is left out: its 8 quiet references at the top right get other
names under interned naming (the V2si oracle differs, on integration too): ops#514."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def drawnTheOtherWay(sketch, indices):
    """The sketch's lines at `indices` drawn the other way, their ids kept."""
    geometry = sketch.Geometry
    for index in indices:
        curve = geometry[index]
        start, end = V(curve.StartPoint), V(curve.EndPoint)
        curve.StartPoint, curve.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
        curve.StartPoint, curve.EndPoint = end, start
    sketch.Geometry = geometry


def corners(names, per):
    return tuple(f"{c}_{k}{i}" for c in names for k in ("e", "v") for i in range(per))


class Ring(Scenario):
    """The ring drawn from its bottom left corner (then top left, top right, bottom right), the
    profile a 2 x 2 square (scaled) at `PROFILE_Z` on the left leg."""

    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E4")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r2"
    TIER = "F"
    SIZE = 30
    TRANSITION = "Right corner"
    PER = 4
    PROFILE_Z = 4
    CORNER_AT = {"bl": (0, 0), "tl": (0, 20), "tr": (30, 20), "br": (30, 0)}
    REFS = corners(("bl", "tl", "tr", "br"), 4)

    def points(self):
        return [self.s(*self.CORNER_AT[c]) for c in ("bl", "tl", "tr", "br")]

    def spine(self):
        p = self.points()
        return [Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in zip(p, p[1:] + p[:1])]

    def slide(self, doc, z):
        doc.Profile.Placement = App.Placement(V(0, 0, self.s(z)), App.Rotation())

    def build(self, doc):
        self.shift = V(0, 0, 0)
        body = m.body(doc)
        path = m.sketch(doc, "Path", self.spine(), body, placement=XZ)
        h = self.s(1)
        profile = m.sketch(doc, "Profile", m.rectangle(-h, -h, h, h), body)
        self.slide(doc, self.PROFILE_Z)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = self.TRANSITION
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        shape = pipe.Shape
        for corner, (x, z) in self.CORNER_AT.items():
            at = V(self.s(x), 0, self.s(z))
            for kind, elements in (("e", shape.Edges), ("v", shape.Vertexes)):

                def where(element):
                    return element.Point if kind == "v" else element.valueAt(
                        (element.FirstParameter + element.LastParameter) / 2
                    )

                nearest = sorted(
                    elements,
                    key=lambda e: (round((where(e) - at).Length, 6), tuple(round(c, 6) for c in where(e))),
                )[: self.PER]
                for i, element in enumerate(nearest):
                    key = f"{corner}_{kind}{i}"
                    point = V(where(element))
                    if kind == "v":
                        expect = lambda p=point: vertex(p + self.shift)  # noqa: E731
                    else:
                        ends = [V(v.Point) for v in element.Vertexes]

                        def expect(p=point, ends=ends):
                            return edge(
                                contains=p + self.shift,
                                where=lambda e: len(e.Vertexes) == len(ends)
                                and all(
                                    min((V(v.Point) - q - self.shift).Length for v in e.Vertexes)
                                    < 1e-6
                                    for q in ends
                                ),
                            )

                    datum = body.newObject("PartDesign::Point", "On_" + key)
                    datum.AttachmentSupport = [(pipe, self.names(pipe, expect()))]
                    datum.MapMode = "Vertex" if kind == "v" else "CenterOfMass"
                    self.ref(key, datum, "AttachmentSupport", expect, Attached())


class RingSlidThenOpenedAndClosedMoved(Ring):
    """The profile slid from z = 4 to 16 (past the leg's middle: the stored start stays at the
    bottom left), recomputed; then the bottom line's end at the bottom left moved to (5, -5),
    so the spine is open for one recompute, and moved back. The solid is as built."""

    abstract = False

    def edit(self, doc):
        self.slide(doc, 16)
        doc.recompute()
        geometry = doc.Path.Geometry
        line = geometry[3]
        line.EndPoint = V(*self.s(5, -5), 0)
        doc.Path.Geometry = geometry
        doc.recompute()
        geometry = doc.Path.Geometry
        line = geometry[3]
        line.EndPoint = V(0, 0, 0)
        doc.Path.Geometry = geometry


class RingSlidThenOpenedAndClosedRedrawn(Ring):
    """As RingSlidThenOpenedAndClosedMoved, but the bottom line deleted (the spine open for one
    recompute) and drawn again, from the bottom right to the bottom left."""

    abstract = False

    def edit(self, doc):
        self.slide(doc, 16)
        doc.recompute()
        doc.Path.delGeometry(3)
        doc.recompute()
        doc.Path.addGeometry(Part.LineSegment(V(*self.s(30, 0), 0), V(0, 0, 0)), False)


class RingSlidThenReorderedAndReversed(Ring):
    """The profile slid from z = 4 to 16, recomputed; then the lines listed from the top right
    and the left leg drawn the other way (rung 4 against a reparameterisation after a slide)."""

    abstract = False

    def edit(self, doc):
        self.slide(doc, 16)
        doc.recompute()
        geometry = doc.Path.Geometry
        doc.Path.Geometry = geometry[2:] + geometry[:2]
        drawnTheOtherWay(doc.Path, [2])


class RingMovedAndLineReversed(Ring):
    """The spine's sketch and the profile moved down 25 together (more than a leg) and the left
    leg drawn the other way, one recompute."""

    abstract = False
    AXES = ("M3", "E3", "E4")

    def edit(self, doc):
        down = V(0, 0, -self.s(25))
        self.shift = down
        doc.Path.Placement = App.Placement(down, XZ.Rotation)
        doc.Profile.Placement = App.Placement(V(0, 0, self.s(self.PROFILE_Z)) + down, App.Rotation())
        drawnTheOtherWay(doc.Path, [0])


class RingTiedThenReordered(Ring):
    """The profile at the left leg's middle (z = 10, both left corners tie), then the lines
    listed from the top left (rung 4 decides; the drawing must not)."""

    abstract = False
    PROFILE_Z = 10

    def edit(self, doc):
        geometry = doc.Path.Geometry
        doc.Path.Geometry = geometry[1:] + geometry[:1]


class DSlidThenReorderedAndReversed(Ring):
    """The D of `pipe_closed.py` (a line up 10, then a 300 degree arc back; SIZE 20),
    "Transformed", the profile at its bottom vertex: the profile slid to the top vertex,
    recomputed (the stored start stays at the bottom, the solid as built); then the arc listed
    first and the line drawn the other way."""

    abstract = False
    SIZE = 20
    TRANSITION = "Transformed"
    PROFILE_Z = 0
    CORNER_AT = {"a": (0, 0), "b": (0, 10)}
    REFS = corners(("a", "b"), 4)

    def spine(self):
        arc = Part.ArcOfCircle(V(0, self.s(10), 0), V(-self.s(18.66025), self.s(5), 0), V(0, 0, 0))
        return [Part.LineSegment(V(0, 0, 0), V(0, self.s(10), 0)), arc]

    def edit(self, doc):
        self.slide(doc, 10)
        doc.recompute()
        geometry = doc.Path.Geometry
        doc.Path.Geometry = [geometry[1], geometry[0]]
        drawnTheOtherWay(doc.Path, [1])


class RingSlidThenSpineEdgeRemovedAndAdded(Ring):
    """The Spine picked as the ring's four edges; the profile slid from z = 4 to 16, recomputed;
    then the bottom edge removed from the Spine, recomputed (the open spine), and picked again,
    as the task panel does it (each pick sets the Spine and recomputes). The Spine ends as it
    began; the solid is as built."""

    abstract = False
    AXES = ("M3", "E4", "E5")

    def build(self, doc):
        super().build(doc)
        doc.Pipe.Spine = (doc.Path, ["Edge1", "Edge2", "Edge3", "Edge4"])
        doc.recompute()

    def edit(self, doc):
        self.slide(doc, 16)
        doc.recompute()
        doc.Pipe.Spine = (doc.Path, ["Edge1", "Edge2", "Edge3"])
        doc.recompute()
        doc.Pipe.Spine = (doc.Path, ["Edge1", "Edge2", "Edge3", "Edge4"])
