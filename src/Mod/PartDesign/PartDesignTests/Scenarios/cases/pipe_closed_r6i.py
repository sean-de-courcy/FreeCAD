# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6i (fork PR 383, round 6, head 8c97de1b3d, decisions 190 and 192): where a frame of
the profile turned, the carry still accepts the names' order when only one order fits the names.

F-1's family with three lines: an isosceles triangle whose start corner A lies on the profile's
normal axis. The profile's placement turned half a turn about its normal through A (the lines drawn
back, the same square in the body) is a symmetry of the spine fixing A that swaps its two other
corners, so the placement frame carries the stored start A and next vertex B onto A and C. With the
triangle's lines mirrored under their IDs (line 0 now the left leg), only the back order fits the
three names, and the placement frame's carry agrees with it.

The triangle in the XZ plane (sketch x = global X, sketch y = global Z): A = (0, 0, 0),
B = (b, 0, h), C = (-b, 0, h), b = 10, h = 30, line 0 A -> B, line 1 B -> C, line 2 C -> A. The
profile: a 2 x 2 square in the XY plane centred on A ("Right corner"). The spine lies in y = 0, so
each leg's front side is a planar face at y = -1: the references are datum points at the centres
of mass of the three legs' front faces, each held at its place on the edited model."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


class Triangle(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6i"
    TIER = "F"
    SIZE = 40
    SCALE = 1.0
    TRANSITION = "Right corner"
    REFS = ("right_front", "left_front", "top_front")
    half = 10  # b
    tall = 30  # h

    def corners(self):
        b, h = self.s(self.half), self.s(self.tall)
        return V(0, 0, 0), V(b, h, 0), V(-b, h, 0)  # sketch coordinates

    def mid(self, p, q):
        """The leg p-q's front point (global), at y = -1."""
        return V((p.x + q.x) / 2, -self.s(1), (p.y + q.y) / 2)

    def frontOf(self, which):
        def predicate():
            a, b, c = self.corners()
            p, q = {"right": (a, b), "left": (c, a), "top": (b, c)}[which]
            return face("plane", normal=V(0, -1, 0), contains=self.mid(p, q))

        return predicate

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        a, b, c = self.corners()
        self.path = m.sketch(
            doc,
            "Path",
            [Part.LineSegment(a, b), Part.LineSegment(b, c), Part.LineSegment(c, a)],
            body,
            placement=XZ,
        )
        one = self.s(1)
        self.profile = m.sketch(doc, "Profile", m.rectangle(-one, -one, one, one), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.Transition = self.TRANSITION
        pipe.Refine = False
        self.pipe = pipe
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

    # ---- edits
    def setLines(self, mirrored):
        """The triangle at the current size; `mirrored`: line 0 A -> C, line 1 C -> B, line 2
        B -> A (the IDs kept, each line drawn at its mirror image's place about the axis)."""
        a, b, c = self.corners()
        lines = [(a, c), (c, b), (b, a)] if mirrored else [(a, b), (b, c), (c, a)]
        g = self.path.Geometry
        for i, line in enumerate(g):
            line.StartPoint, line.EndPoint = V(100 + 10 * i, 100, 0), V(105 + 10 * i, 105, 0)
        for line, (p, q) in zip(g, lines):
            line.StartPoint, line.EndPoint = p, q
        self.path.Geometry = g

    def grow(self, factor):
        """The triangle scaled about A (the directions from A kept)."""
        self.half *= factor
        self.tall *= factor

    def reparameteriseProfile(self, degrees):
        """The profile's placement turned `degrees` about its normal and its lines drawn at the
        sketch coordinates turned back: the same square in the body, line for line."""
        back = App.Rotation(V(0, 0, 1), -degrees)
        g = self.profile.Geometry
        for line in g:
            s, e = back.multVec(V(line.StartPoint)), back.multVec(V(line.EndPoint))
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), degrees))


class TriangleGrownProfileReparameterised180(Triangle):
    """Control: the triangle grown by 1.25 about A and the profile reparameterised half a turn, the
    lines kept. The references stay at their places."""

    def edit(self, doc):
        self.grow(1.25)
        self.setLines(False)
        self.reparameteriseProfile(180)


class TriangleMirroredGrown(Triangle):
    """Control (no frame turned): the lines mirrored under their IDs and the triangle grown by 1.25
    about A. The references stay at their places."""

    def edit(self, doc):
        self.grow(1.25)
        self.setLines(True)


class TriangleMirroredGrownProfileReparameterised180(Triangle):
    """The lines mirrored under their IDs, the triangle grown by 1.25 about A, and the profile
    reparameterised half a turn about its normal (the same square in the body), in one recompute.
    The placement frame carries A -> A and B -> C; the names fit only the back order (start A, way
    along line 0, now the left leg), which that carry agrees with. The references stay at their
    places."""

    def edit(self, doc):
        self.grow(1.25)
        self.setLines(True)
        self.reparameteriseProfile(180)


class TriangleMirroredGrownProfileReparameterised90(TriangleMirroredGrownProfileReparameterised180):
    """The same with a quarter turn (no symmetry of the spine): no frame carries B onto C."""

    def edit(self, doc):
        self.grow(1.25)
        self.setLines(True)
        self.reparameteriseProfile(90)


class TriangleMirroredGrownProfileFlipped(Triangle):
    """The lines mirrored under their IDs, the triangle grown by 1.25 about A, and the profile
    turned half a turn about Z with its lines kept (the square is the same in the body: its own
    half-turn symmetry), so both its frames turn. The references stay at their places."""

    def edit(self, doc):
        self.grow(1.25)
        self.setLines(True)
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), 180))
