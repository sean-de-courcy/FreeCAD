# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6j (fork PR 383 at 64d0fc4ebf, decision 195's bound): a turned frame still resolves
where a stored frame puts the loop exactly in place (`inFrame`), here for a reason other than the
loop's motion. A scalene triangle in the XZ plane (sketch x = X, y = Z): A = (0, 0), right corner
R = (10, 30), left corner L = (-16, 24), line 0 A -> R, line 1 R -> L, line 2 L -> A; a 2 x 2 square
profile in the XY plane centred on A, "Right corner". Edit: the triangle mirrored about the sketch's
y axis (R' = (16, 24), L' = (-10, 30)) and the profile reparameterised half a turn about its normal
(the same square in the body, line for line: only its placement frame turns, half a turn about Z
through A, which carries the stored triangle exactly onto the mirrored one). References: datum
points at the centres of mass of the legs' front faces (planar, y = -1), held at their sides (I-B7:
a leg is its place; as `pipe_closed_r6i.py`). A profile flip is left out: its motion carries the
profile's own faces to the back (I-B1)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


class Scalene(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6j"
    TIER = "F"
    SIZE = 40
    SCALE = 1.0
    REFS = ("right_front", "left_front", "top_front")
    mirrored = False

    def corners(self):
        r, l = (10, 30), (-16, 24)
        if self.mirrored:
            r, l = (-l[0], l[1]), (-r[0], r[1])
        return V(0, 0, 0), V(self.s(r[0]), self.s(r[1]), 0), V(self.s(l[0]), self.s(l[1]), 0)

    def frontOf(self, which):
        def predicate():
            a, r, l = self.corners()
            p, q = {"right": (a, r), "left": (l, a), "top": (r, l)}[which]
            mid = V((p.x + q.x) / 2, -self.s(1), (p.y + q.y) / 2)
            return face("plane", normal=V(0, -1, 0), contains=mid)

        return predicate

    def build(self, doc):
        body = m.body(doc)
        a, r, l = self.corners()
        lines = [Part.LineSegment(a, r), Part.LineSegment(r, l), Part.LineSegment(l, a)]
        self.path = m.sketch(doc, "Path", lines, body, placement=XZ)
        one = self.s(1)
        self.profile = m.sketch(doc, "Profile", m.rectangle(-one, -one, one, one), body)
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
            predicate = self.frontOf(name.split("_")[0])
            obj = body.newObject("PartDesign::Point", name)
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            obj.MapMode = "CenterOfMass"
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def mirror(self, idsFollow):
        """The triangle mirrored. `idsFollow`: each line drawn at its mirror image's place (line 0
        A -> L'); otherwise each line keeps its side (line 0 A -> R', line 2 L' -> A)."""
        self.mirrored = True
        a, r, l = self.corners()
        lines = [(a, l), (l, r), (r, a)] if idsFollow else [(a, r), (r, l), (l, a)]
        g = self.path.Geometry
        for i, line in enumerate(g):
            line.StartPoint, line.EndPoint = V(100 + 10 * i, 100, 0), V(105 + 10 * i, 105, 0)
        for line, (p, q) in zip(g, lines):
            line.StartPoint, line.EndPoint = p, q
        self.path.Geometry = g

    def reparameteriseProfile(self):
        """The profile's placement turned half a turn about its normal, its lines drawn back."""
        back = App.Rotation(V(0, 0, 1), -180)
        g = self.profile.Geometry
        for line in g:
            s, e = back.multVec(V(line.StartPoint)), back.multVec(V(line.EndPoint))
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), 180))


class ScaleneMirroredSidesKeptProfileReparameterised180(Scalene):
    """The round: mirrored, each line keeping its side, and the profile reparameterised half a
    turn, in one recompute. Each front face stays at its side."""

    def edit(self, doc):
        self.mirror(False)
        self.reparameteriseProfile()


class ScaleneMirroredSidesKept(Scalene):
    """Control, no frame turned: mirrored, each line keeping its side."""

    def edit(self, doc):
        self.mirror(False)


class ScaleneMirroredIdsFollowProfileReparameterised180(Scalene):
    """Mirrored under the lines' IDs (line 0 now the left leg), the profile reparameterised half a
    turn: the frame's places and the lines' names agree. Each front face stays at its side."""

    def edit(self, doc):
        self.mirror(True)
        self.reparameteriseProfile()
