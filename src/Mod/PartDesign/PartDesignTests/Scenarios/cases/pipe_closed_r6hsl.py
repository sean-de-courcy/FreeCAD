# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6hs (fork PR 383, round 6, head 5fe2ddbea7): a closed spine of two edges (a lens: two
arcs between A = (0, 0, 0) and C = (0, 0, 30)) where a frame of the profile turned.

The carry of the stored start and its next vertex is the same for both orders of a two-edge spine
(the one other vertex): it fixes the start vertex but can't tell which edge the sweep runs along
first. With the arcs' geometry traded under their IDs, the names put the first leg on the other
arc, and the carry agrees: the legs follow their lines to the other arcs.

The lens: arc 0 up from A through (b, 0, 15), arc 1 back down through (-b, 0, 15), b = 11.51 (sketch
x = global X, sketch y = global Z; B-splines). The profile: a 2 x 2 square in the XY plane centred on A
("Transformed"). The spine lies in y = 0, so each leg's front and back sides are planar faces at
y = -1 and y = 1: the four references are datum points at the centres of mass of those faces (right
or left leg, front or back), each held at its place on the edited model."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


class Lens(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2", "E7")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6hs"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("right_front", "left_front", "right_back", "left_back")
    bulge = 11.51

    def arcs(self, traded=False):
        h, b = self.s(30), self.s(self.bulge)
        right_up = Part.ArcOfCircle(V(0, 0, 0), V(b, h / 2, 0), V(0, h, 0)).toBSpline()
        left_down = Part.ArcOfCircle(V(0, h, 0), V(-b, h / 2, 0), V(0, 0, 0)).toBSpline()
        if not traded:
            return [right_up, left_down]
        # arc 0 is the left arc drawn up from A, arc 1 the right arc drawn back down from C
        left_up = Part.ArcOfCircle(V(0, 0, 0), V(-b, h / 2, 0), V(0, h, 0)).toBSpline()
        right_down = Part.ArcOfCircle(V(0, h, 0), V(b, h / 2, 0), V(0, 0, 0)).toBSpline()
        return [left_up, right_down]

    def side(self, sign, y):
        def predicate():
            return face(
                "plane",
                normal=V(0, y, 0),
                contains=V(sign * self.s(self.bulge), y * self.s(1), self.s(15)),
            )

        return predicate

    def build(self, doc):
        body = m.body(doc)
        self.path = m.sketch(doc, "Path", self.arcs(), body, placement=XZ)
        one = self.s(1)
        self.profile = m.sketch(doc, "Profile", m.rectangle(-one, -one, one, one), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        kinds = {
            "right_front": self.side(1, -1),
            "left_front": self.side(-1, -1),
            "right_back": self.side(1, 1),
            "left_back": self.side(-1, 1),
        }
        made = {}
        for name in self.REFS:
            obj = body.newObject("PartDesign::Point", name)
            obj.AttachmentSupport = [(pipe, self.names(pipe, kinds[name]()))]
            obj.MapMode = "CenterOfMass"
            made[name] = (obj, kinds[name])
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def setArcs(self, traded):
        g = self.path.Geometry
        for curve, new in zip(g, self.arcs(traded)):
            # rebuilt in place: the geometry's id (its Tag) kept
            curve.buildFromPolesMultsKnots(
                new.getPoles(),
                new.getMultiplicities(),
                new.getKnots(),
                new.isPeriodic(),
                new.Degree,
                new.getWeights(),
            )
        self.path.Geometry = g

    def replaceProfile(self, degrees):
        """The profile's placement turned `degrees` about its normal and its lines drawn at the
        coordinates turned back: the same square in the body, line for line."""
        back = App.Rotation(V(0, 0, 1), -degrees)
        g = self.profile.Geometry
        for line in g:
            s, e = back.multVec(V(line.StartPoint)), back.multVec(V(line.EndPoint))
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), degrees))


class LensWidenedProfileReplaced(Lens):
    """Control: the lens widened to b = 14 and the profile reparameterised by 180 degrees, the arcs
    kept. The references stay at their places."""

    def edit(self, doc):
        self.replaceProfile(180)
        self.bulge = 14
        self.setArcs(False)


class LensArcsTradedWidened(Lens):
    """Control: the arcs trade geometry (IDs kept) and the lens widens to b = 14, no frame of the
    profile turning. The references stay at their places."""

    def edit(self, doc):
        self.bulge = 14
        self.setArcs(True)


class LensArcsTradedWidenedProfileReplaced180(Lens):
    """The arcs trade geometry (IDs kept: arc 0 is now the left arc), the lens widens to b = 14 and
    the profile is reparameterised by 180 degrees, in one recompute. The placement frame turned
    about the profile's normal through A carries A and C onto themselves; the names put the start at
    arc 0's start and the way along arc 0, now the left arc; the carry agrees. The references stay
    at their places."""

    def edit(self, doc):
        self.replaceProfile(180)
        self.bulge = 14
        self.setArcs(True)


class LensArcsTradedWidenedProfileReplaced90(LensArcsTradedWidenedProfileReplaced180):
    def edit(self, doc):
        self.replaceProfile(90)
        self.bulge = 14
        self.setArcs(True)


class LensArcsTradedWidenedProfileReplaced180Far(LensArcsTradedWidenedProfileReplaced180):
    """As above with the lens widened to b = 20."""

    def edit(self, doc):
        self.replaceProfile(180)
        self.bulge = 20
        self.setArcs(True)
