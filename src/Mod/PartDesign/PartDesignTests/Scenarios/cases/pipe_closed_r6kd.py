# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6k (fork PR 383 at f54fb67fff, decision 198): with a frame of the profile turned,
`inFrame` stands where every stored line found lies at its frame-carried place. On a closed spine of
two edges the lines' places don't fix the way round: a place holds the same line whichever end of
it is the start. A closed spine of two edges in the XZ plane (sketch x = X, y = Z): line 0 from
A = (0, 0) to B = (0, 30); line 1 a B-spline from B back to A bulging to +x, not symmetric about the
line's perpendicular bisector (z = 15). The profile: a 2 x 2 square in the plane z = 15, centred on
the line's middle M = (0, 0, 15) ("Right corner"). References: datum planes on the line leg's outer
(x = -1) and front (y = -1) faces, a datum plane on the spline leg's front face, datum points on the
line leg's outer-front corner vertices and at the centres of its outer corner edges (along y, at
x = -1), at the A end and the B end."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Predicate, Scenario, face
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
    REFS = ("line_outer", "line_front", "spline_front", "a_corner", "b_corner", "a_edge", "b_edge")
    poles0 = POLES
    verticalFirst = False  # the profile's line 0 from (1, -1) to (1, 1)
    mirrored = False  # the spline mirrored about z = 15 (as the edit leaves it)
    turned = False  # the whole model turned half a turn about X through M (the motion)

    def poles(self):
        poles = self.poles0
        if self.mirrored:
            poles = tuple((x, 30 - z) for x, z in poles)
        return [V(self.s(x), self.s(z), 0) for x, z in poles]

    def spline(self):
        curve = Part.BSplineCurve()
        curve.buildFromPoles(self.poles())
        return curve

    def motion(self, p):
        """Where the edit's motion carries the body point p."""
        if self.turned:
            return V(p.x, -p.y, self.s(30) - p.z)
        return p

    def corner(self, atA):
        def predicate():
            one, mid = self.s(1), self.s(15)
            # before the motion: the vertex on the line leg's lateral edge x = -1, y = -1 at that end
            sign = -1 if self.turned else 1
            low = atA != self.turned

            def test(v, tol):
                p = v.Point
                return (
                    abs(p.x + one) < tol
                    and abs(p.y + sign * one) < tol
                    and ((p.z < mid) if low else (p.z > mid))
                )

            return Predicate("Vertex", f"line leg corner at {'A' if atA else 'B'}", [test])

        return predicate

    def cornerEdge(self, atA):
        def predicate():
            one, mid = self.s(1), self.s(15)
            low = atA != self.turned

            def test(e, tol):
                c = e.CenterOfMass
                d = e.Vertexes[-1].Point - e.Vertexes[0].Point
                return (
                    abs(c.x + one) < tol
                    and abs(c.y) < tol
                    and abs(d.x) < tol
                    and abs(d.z) < tol
                    and ((c.z < mid) if low else (c.z > mid))
                )

            return Predicate("Edge", f"outer corner edge at {'A' if atA else 'B'}", [test])

        return predicate

    def lineOuter(self):
        return face("plane", normal=V(-1, 0, 0), contains=self.motion(V(-self.s(1), 0, self.s(15))))

    def lineFront(self):
        n = V(0, 1, 0) if self.turned else V(0, -1, 0)
        return face("plane", normal=n, contains=self.motion(V(0, -self.s(1), self.s(15))))

    def splineFront(self):
        # the spline leg's front face at the spline's middle, in the sketch as the edit leaves it
        curve = self.spline()
        mid = curve.value((curve.FirstParameter + curve.LastParameter) / 2)
        p = self.motion(V(mid.x, -self.s(1), mid.y))
        n = V(0, 1, 0) if self.turned else V(0, -1, 0)
        return face("plane", normal=n, contains=p)

    def predicates(self):
        return {
            "line_outer": self.lineOuter,
            "line_front": self.lineFront,
            "spline_front": self.splineFront,
            "a_corner": self.corner(True),
            "b_corner": self.corner(False),
            "a_edge": self.cornerEdge(True),
            "b_edge": self.cornerEdge(False),
        }

    def build(self, doc):
        body = m.body(doc)
        self.path = m.sketch(
            doc,
            "Path",
            [Part.LineSegment(V(0, 0, 0), V(0, self.s(30), 0)), self.spline()],
            body,
            placement=XZ,
        )
        one = self.s(1)
        square = [(-one, -one), (one, -one), (one, one), (-one, one)]
        if self.verticalFirst:
            square = square[1:] + square[:1]
        self.profile = m.sketch(
            doc,
            "Profile",
            m.polygon(square),
            body,
            placement=App.Placement(V(0, 0, self.s(15)), App.Rotation()),
        )
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
            predicate = self.predicates()[name]
            if name.endswith("corner") or name.endswith("edge"):
                obj = body.newObject("PartDesign::Point", name)
                obj.MapMode = "Vertex" if name.endswith("corner") else "CenterOfMass"
            else:
                obj = body.newObject("PartDesign::Plane", name)
                obj.MapMode = "FlatFace"
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def mirrorSpline(self):
        """The spline redrawn as its mirror image about z = 15, its ID kept; the line stays."""
        self.mirrored = True
        g = self.path.Geometry
        curve = g[1]
        for i, p in enumerate(self.poles(), 1):
            curve.setPole(i, p)
        self.path.Geometry = g

    def reparameteriseProfile(self):
        """The profile's placement turned half a turn about X through M, its lines drawn back
        (mirrored in the sketch), so the square lies where it was in the body, line for line."""
        g = self.profile.Geometry
        for line in g:
            s, e = V(line.StartPoint), V(line.EndPoint)
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = V(s.x, -s.y, 0), V(e.x, -e.y, 0)
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(
            V(0, 0, self.s(15)), App.Rotation(V(1, 0, 0), 180)
        )


class TwoEdgeSplineMirroredProfileReparameterised180(TwoEdge):
    """The probe: the spline mirrored about z = 15 (A and B stay, the line stays) and the profile
    reparameterised half a turn about X through M, in one recompute. The placement frame's half
    turn carries the stored spine exactly onto the edited one, A onto B, and each line onto its own
    place. Nothing but the spline's shape moved: each corner stays at its end."""

    def edit(self, doc):
        self.mirrorSpline()
        self.reparameteriseProfile()


class TwoEdgeSplineMirrored(TwoEdge):
    """Control, no frame turned: the spline mirrored about z = 15."""

    def edit(self, doc):
        self.mirrorSpline()


class TwoEdgeTurned180AboutMiddle(TwoEdge):
    """Control, the motion: the whole model (spine and profile) turned half a turn about X through
    M. The A end's corner goes to the B end with the motion."""

    def edit(self, doc):
        turn = App.Placement(V(0, 0, self.s(15)), App.Rotation()).multiply(
            App.Placement(V(), App.Rotation(V(1, 0, 0), 180))
        ).multiply(App.Placement(V(0, 0, -self.s(15)), App.Rotation()))
        self.path.Placement = turn.multiply(self.path.Placement)
        self.profile.Placement = turn.multiply(self.profile.Placement)
        self.turned = True
