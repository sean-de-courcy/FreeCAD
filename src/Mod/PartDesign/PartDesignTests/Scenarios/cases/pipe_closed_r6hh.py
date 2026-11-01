# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6hh (fork PR 383, the corpus judging change of decision 186, 4f7b7121d1 and
4b142faa8d): a Pipe on a Pad's face that stops after the edit (decision 180) passes the Pad's shape
through (ops#126), and a datum point on the Pipe's corner vertex follows its name to the Pad's
corner, valid and without a warning, at another place. The expected vertex isn't on the pass-through
shape, so the harness's new branch (`# 0.`, the ScenarioError of the expectation) scores the
reference `broken` whatever its owner does.

The model: a closed rectangle of four lines on the XZ plane, (0, 0) -> (0, H) -> (W, H) -> (W, 0),
W = 30, H = 20 (sketch x = global X, sketch y = global Z); a square 2A x 2B (A = B = 2) sketched on
the XY plane through its attachment offset and padded 1 down; the Pipe sweeps the Pad's top face
round the ring, "Right corner". The point is on the Pipe's outer bottom left corner (-A, -B, -A).
The edit (as pipe_closed_r6g's FaceProfileRedrawnBy2Turned180AndWidened): the ring's lines redrawn
from the top right corner (IDs shifted by two), the right line at x = 34, and the ring's placement
and the profile's offset turned 180 degrees about Z, in one recompute. The expectation: the corner
at its place on the edited model, (A, B, -A) after the turn."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Attached, Scenario, X, Z, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector


def xyPlane(body):
    return [
        f for f in body.Origin.OriginFeatures if "XY_Plane" in (getattr(f, "Role", ""), f.Name)
    ][0]


class StoppedPipeOnPadPointCorner(Scenario):
    """The datum point on the Pipe's outer bottom left corner; the Pipe stops after the edit and
    passes the Pad through. Held silently on the Pad's corner (2, 2, 0) on the PR: `wrong` by the
    harness's own rules, scored `broken` by the new branch. `datum_top_outer` is the loud
    control (its owner fails)."""

    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E7", "E2", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6hh"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    REFS = ("point_bottom_left", "datum_top_outer")
    turn = 0
    width = 30
    height = 20
    half = 2

    W = property(lambda self: self.s(self.width))
    H = property(lambda self: self.s(self.height))
    A = property(lambda self: self.s(self.half))

    def rot(self):
        return App.Rotation(Z, self.turn)

    def at(self, x, y, z):
        return self.rot().multVec(V(x, y, z))

    def bottomLeft(self):
        return vertex(self.at(-self.A, -self.A, -self.A))

    def topOuter(self):
        return face(
            "plane", normal=self.rot().multVec(Z), contains=self.at(self.W / 2, 0, self.H + self.A)
        )

    def spinePlacement(self):
        return App.Placement(V(), self.rot().multiply(App.Rotation(X, 90)))

    def setSpine(self, lines):
        g = self.spine.Geometry
        for i in range(len(lines)):
            g[i].StartPoint, g[i].EndPoint = V(100 + 10 * i, 100, 0), V(105 + 10 * i, 105, 0)
        for i, (p, q) in enumerate(lines):
            g[i].StartPoint, g[i].EndPoint = V(p[0], p[1], 0), V(q[0], q[1], 0)
        self.spine.Geometry = g

    def build(self, doc):
        body = m.body(doc)
        w, h, a = self.W, self.H, self.A
        self.spine = m.sketch(
            doc,
            "Spine",
            m.polygon([(0, 0), (0, h), (w, h), (w, 0)]),
            body,
            placement=self.spinePlacement(),
        )
        self.profile = m.sketch(doc, "Square", m.rectangle(-a, -a, a, a), body)
        self.profile.AttachmentSupport = [(xyPlane(body), "")]
        self.profile.MapMode = "FlatFace"
        self.profile.AttachmentOffset = App.Placement(V(), self.rot())
        pad = m.pad(body, self.profile, self.s(1))
        pad.Reversed = True
        doc.recompute()
        top = [
            f"Face{i}"
            for i, f in enumerate(pad.Shape.Faces, 1)
            if abs(f.CenterOfMass.z) < 1e-6 and abs(f.normalAt(0, 0).z) > 0.99
        ]
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = (pad, top)
        pipe.Spine = (self.spine, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        point = body.newObject("PartDesign::Point", "point_bottom_left")
        point.AttachmentSupport = [(pipe, self.names(pipe, self.bottomLeft()))]
        point.MapMode = "Vertex"
        plane = body.newObject("PartDesign::Plane", "datum_top_outer")
        plane.AttachmentSupport = [(pipe, self.names(pipe, self.topOuter()))]
        plane.MapMode = "FlatFace"
        doc.recompute()
        self.ref("point_bottom_left", point, "AttachmentSupport", self.bottomLeft, Attached())
        self.ref("datum_top_outer", plane, "AttachmentSupport", self.topOuter, Attached())

    def edit(self, doc):
        self.width = 34
        w, h = self.W, self.H
        self.setSpine([((w, h), (w, 0)), ((w, 0), (0, 0)), ((0, 0), (0, h)), ((0, h), (w, h))])
        self.turn = 180
        self.spine.Placement = self.spinePlacement()
        self.profile.AttachmentOffset = App.Placement(V(), self.rot())
