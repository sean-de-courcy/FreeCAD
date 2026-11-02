# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6hs (fork PR 383, round 6, head 5fe2ddbea7): the closed D (a line and a 300 degree
arc, two edges: the next vertex is the same for both orders) with its profile moved to the other
vertex by the D's mirror symmetry (a half turn about X through the middle of the line's chord, the
profile flipped over) while the D is scaled, in one recompute; the IDs kept. The D as in
pipe_closed_r6gs.py (copied: a case imports only harness and models)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    Scenario,
    X,
    Y,
    Z,
    edge,
    face,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


class D(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6hs"
    TIER = "F"
    SIZE = 40
    SCALE = 1.0
    REFS = tuple(f"a_{k}{i}" for k in ("e", "v") for i in range(4))
    turn = 0
    length = 10

    def rot(self):
        return App.Rotation(Z, self.turn)

    def spinePlacement(self):
        return App.Placement(V(), self.rot().multiply(XZ.Rotation))

    def profilePlacement(self):
        return App.Placement(V(), self.rot())

    def arcOf(self, L):
        return Part.ArcOfCircle(V(0, L, 0), V(-1.8660254037844386 * L, L / 2, 0), V(0, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        L = self.length
        self.path = m.sketch(
            doc,
            "Path",
            [Part.LineSegment(V(0, 0, 0), V(0, L, 0)), self.arcOf(L)],
            body,
            placement=self.spinePlacement(),
        )
        self.profile = m.sketch(doc, "Profile", m.rectangle(-1, -1, 1, 1), body)
        self.profile.Placement = self.profilePlacement()
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = False
        self.pipe = pipe
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        shape = pipe.Shape
        at = V(0, 0, 0)
        for kind, elements in (("e", shape.Edges), ("v", shape.Vertexes)):

            def where(element, kind=kind):
                return element.Point if kind == "v" else element.valueAt(
                    (element.FirstParameter + element.LastParameter) / 2
                )

            nearest = sorted(
                elements,
                key=lambda e: (round((where(e) - at).Length, 6), tuple(round(c, 6) for c in where(e))),
            )[:4]
            for i, element in enumerate(nearest):
                key = f"a_{kind}{i}"
                point = V(where(element))
                if kind == "v":
                    expect = lambda p=point: vertex(self.rot().multVec(p))  # noqa: E731
                else:
                    ends = [V(v.Point) for v in element.Vertexes]

                    def expect(p=point, ends=ends):
                        q = self.rot()
                        turned = [q.multVec(e) for e in ends]
                        return edge(
                            contains=q.multVec(p),
                            where=lambda e: len(e.Vertexes) == len(turned)
                            and all(
                                min((V(v.Point) - t).Length for v in e.Vertexes) < 1e-6
                                for t in turned
                            ),
                        )

                datum = body.newObject("PartDesign::Point", "On_" + key)
                datum.AttachmentSupport = [(pipe, self.names(pipe, expect()))]
                datum.MapMode = "Vertex" if kind == "v" else "CenterOfMass"
                self.ref(key, datum, "AttachmentSupport", expect, Attached())

    def turnModel(self, degrees):
        self.turn = degrees
        self.path.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()

    def setLength(self, L):
        g = self.path.Geometry
        g[0].EndPoint = V(0, L, 0)
        g[1].Center = V(-0.8660254037844386 * L, L / 2, 0)
        g[1].Radius = L
        self.path.Geometry = g
        self.length = L



class DProfileFlippedAtStartScaled(D):
    """The D scaled from 10 to 14 and its profile flipped over (half turn about X) at the start
    vertex, IDs kept."""

    AXES = ("M3", "E3", "E7")

    def edit(self, doc):
        self.setLength(14)
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(X, 180))


class DProfileTurnedOnItselfScaled(D):
    """The D scaled from 10 to 14 and its profile (a square) turned a quarter turn about its normal
    at the start vertex, IDs kept."""

    AXES = ("M3", "E3", "E7")

    def edit(self, doc):
        self.setLength(14)
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(Z, 90))


class DReplace(D):
    abstract = True
    AXES = ("M3", "E3", "E7")

    def replaceProfile(self):
        g = self.profile.Geometry
        for line in g:
            s, e = V(line.StartPoint), V(line.EndPoint)
            line.StartPoint, line.EndPoint = V(-s.x, -s.y, 0), V(-e.x, -e.y, 0)
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(Z, 180))

    def reorder(self):
        g = self.path.Geometry
        self.path.Geometry = [g[1], g[0]]


class DScaledProfileReplaced(DReplace):
    """Control: the D scaled from 10 to 14 and the profile reparameterised (its placement turned half
    a turn about its normal, its lines negated: the same square in the body), IDs kept."""

    def edit(self, doc):
        self.setLength(14)
        self.replaceProfile()


class DReorderedScaled(DReplace):
    """Control: the D scaled from 10 to 14 and its geometry listed arc first, then line (the IDs
    swap their geometry), the profile untouched (no frame turns)."""

    def edit(self, doc):
        self.setLength(14)
        self.reorder()


class DReorderedScaledProfileReplaced(DReplace):
    """The D scaled from 10 to 14, its geometry listed arc first then line (ID 0 is now the arc, ID
    1 the line), and the profile reparameterised, in one recompute."""

    def edit(self, doc):
        self.setLength(14)
        self.reorder()
        self.replaceProfile()
