# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6k (fork PR 383 at f54fb67fff, decision 198). A closed spine of two edges: the lines'
places don't fix the way round, so decision 198's names check holds whichever end the frame carries
the start to. Spine in the XZ plane (sketch x = X, y = Z): line 0 A = (0, 0) -> B = (0, 30); line 1 a
B-spline B -> A bulging to +x, not symmetric about z = 15. Profile: a 2 x 2 square in the plane
z = 15 centred on M = (0, 0, 15), its line 0 from (1, -1) to (1, 1) ("Right corner"). Edit, one
recompute: the spline mirrored about z = 15 (its ID kept; A, B and the line stay) and the profile's
line 0 drawn the other way (a reparameterisation: same square, same placement). The profile's
geometry frame (its first wire's first point and point order) turns half a turn about X through M,
which carries the stored spine exactly onto the edited one, A onto B. References: datum points on
the line leg's outer-front corner vertices (x = -1, y = -1) and at the centres of its outer corner
edges (along y at x = -1), at each end. Nothing at A or B moved: each stays at its end."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Predicate, Scenario
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
POLES = ((0, 30), (12, 30), (14, 4), (0, 0))  # B -> A


class TwoEdge(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6k"
    TIER = "F"
    SIZE = 40
    SCALE = 1.0
    REFS = ("a_corner", "b_corner", "a_edge", "b_edge")
    mirrored = False

    def spline(self):
        poles = [(x, 30 - z) for x, z in POLES] if self.mirrored else POLES
        curve = Part.BSplineCurve()
        curve.buildFromPoles([V(self.s(x), self.s(z), 0) for x, z in poles])
        return curve

    def atEnd(self, kind, atA):
        def predicate():
            one, mid = self.s(1), self.s(15)

            def side(p):
                return (p.z < mid) if atA else (p.z > mid)

            def vertexTest(v, tol):
                p = v.Point
                return abs(p.x + one) < tol and abs(p.y + one) < tol and side(p)

            def edgeTest(e, tol):
                c, d = e.CenterOfMass, e.Vertexes[-1].Point - e.Vertexes[0].Point
                return abs(c.x + one) < tol and abs(c.y) < tol and abs(d.x) < tol and abs(d.z) < tol and side(c)

            test = vertexTest if kind == "Vertex" else edgeTest
            return Predicate(kind, f"line leg's outer {kind} at {'A' if atA else 'B'}", [test])

        return predicate

    def build(self, doc):
        body = m.body(doc)
        line = Part.LineSegment(V(0, 0, 0), V(0, self.s(30), 0))
        self.path = m.sketch(doc, "Path", [line, self.spline()], body, placement=XZ)
        one = self.s(1)
        square = [(one, -one), (one, one), (-one, one), (-one, -one)]
        at = App.Placement(V(0, 0, self.s(15)), App.Rotation())
        self.profile = m.sketch(doc, "Profile", m.polygon(square), body, placement=at)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        made = {}
        for name in self.REFS:
            predicate = self.atEnd("Vertex" if name.endswith("corner") else "Edge", name[0] == "a")
            obj = body.newObject("PartDesign::Point", name)
            obj.MapMode = "Vertex" if name.endswith("corner") else "CenterOfMass"
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def mirrorSpline(self):
        """The spline redrawn as its mirror image about z = 15, its ID kept."""
        self.mirrored = True
        g = self.path.Geometry
        for i, p in enumerate(self.spline().getPoles(), 1):
            g[1].setPole(i, p)
        self.path.Geometry = g


class TwoEdgeSplineMirroredProfileLineReversed(TwoEdge):
    """The round: the spline mirrored and the profile's line 0 drawn the other way, in one
    recompute."""

    def edit(self, doc):
        self.mirrorSpline()
        g = self.profile.Geometry
        s, e = V(g[0].StartPoint), V(g[0].EndPoint)
        g[0].StartPoint, g[0].EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
        g[0].StartPoint, g[0].EndPoint = e, s
        self.profile.Geometry = g


class TwoEdgeSplineMirroredLineKept(TwoEdge):
    """Control, no frame turned: the spline mirrored."""

    def edit(self, doc):
        self.mirrorSpline()
