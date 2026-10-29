# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6i (fork PR 383, round 6, head 8c97de1b3d, decision 192): the stop where both
cyclic orders fit the names and a frame of the profile turned, at its boundary.

The model is pipe_closed_r6hs.py's Ring (copied: a case imports only harness and models): a closed
rectangle of four lines on the XZ plane, (0, 0) -> (0, H) -> (W, H) -> (W, 0), W = 30, H = 20
(sketch x = global X, sketch y = global Z), a square profile 2A x 2B (normal Z, along the left leg)
at the bottom left corner, "Right corner"."""
import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    Filleted,
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


def xyPlane(body):
    return [
        f for f in body.Origin.OriginFeatures if "XY_Plane" in (getattr(f, "Role", ""), f.Name)
    ][0]


class Ring(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6i"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    REFS = (
        "datum_left_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "fillet_top_front",
        "point_bottom_left",
    )
    turn = 0
    width = 30
    height = 20
    halfX = 2
    halfY = 2
    faceProfile = False  # the profile is the top face of a Pad of the square (attached to XY)

    W = property(lambda self: self.s(self.width))
    H = property(lambda self: self.s(self.height))
    A = property(lambda self: self.s(self.halfX))
    B = property(lambda self: self.s(self.halfY))

    def rot(self):
        return App.Rotation(Z, self.turn)

    def at(self, x, y, z):
        return self.rot().multVec(V(x, y, z))

    def along(self, d):
        return self.rot().multVec(d)

    def leftOuter(self):
        return face("plane", normal=self.along(-X), contains=self.at(-self.A, 0, self.H / 2))

    def rightOuter(self):
        return face("plane", normal=self.along(X), contains=self.at(self.W + self.A, 0, self.H / 2))

    def topOuter(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.H + self.A))

    def bottomInner(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.A))

    def topFront(self):
        return edge(
            "line",
            direction=self.along(X),
            through=self.at(0, -self.B, self.H + self.A),
            contains=self.at(self.W / 2, -self.B, self.H + self.A),
        )

    def topRight(self):
        return vertex(self.at(self.W + self.A, -self.B, self.H + self.A))

    def bottomLeft(self):
        return vertex(self.at(-self.A, -self.B, -self.A))

    def spinePlacement(self):
        return App.Placement(V(), self.rot().multiply(App.Rotation(X, 90)))

    def profilePlacement(self):
        return App.Placement(self.at(0, 0, 0), self.rot())

    def profileLink(self, doc):
        if not self.faceProfile:
            return self.profile
        self.profile.AttachmentSupport = [(xyPlane(self.body), "")]
        self.profile.MapMode = "FlatFace"
        self.profile.AttachmentOffset = self.profilePlacement()
        pad = m.pad(self.body, self.profile, self.s(1))
        pad.Reversed = True
        doc.recompute()
        top = [
            f"Face{i}"
            for i, f in enumerate(pad.Shape.Faces, 1)
            if abs(f.CenterOfMass.z) < 1e-6 and abs(f.normalAt(0, 0).z) > 0.99
        ]
        return (pad, top)

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        w, h = self.W, self.H
        self.spine = m.sketch(
            doc,
            "Spine",
            m.polygon([(0, 0), (0, h), (w, h), (w, 0)]),
            body,
            placement=self.spinePlacement(),
        )
        a, b = self.A, self.B
        self.profile = m.sketch(
            doc, "Square", m.rectangle(-a, -b, a, b), body, placement=self.profilePlacement()
        )
        link = self.profileLink(doc)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = link
        pipe.Spine = (self.spine, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        self.pipe = pipe
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        kinds = {
            "datum_left_outer": ("PartDesign::Plane", self.leftOuter, "FlatFace"),
            "datum_right_outer": ("PartDesign::Plane", self.rightOuter, "FlatFace"),
            "datum_top_outer": ("PartDesign::Plane", self.topOuter, "FlatFace"),
            "sketch_bottom_inner": ("Sketcher::SketchObject", self.bottomInner, "FlatFace"),
            "point_top_right": ("PartDesign::Point", self.topRight, "Vertex"),
            "point_bottom_left": ("PartDesign::Point", self.bottomLeft, "Vertex"),
        }
        made = {}
        for name in self.REFS:
            if name in kinds:
                kind, predicate, mode = kinds[name]
                obj = body.newObject(kind, name)
                obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
                obj.MapMode = mode
                made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())
        if "fillet_top_front" in self.REFS:
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (pipe, self.names(pipe, self.topFront()))
            fillet.Radius = self.s(0.5)
            self.ref("fillet_top_front", fillet, "Base", self.topFront, Filleted(self.s(0.5)))

    # ---- edits
    def setSpine(self, lines):
        """lines: (start, end) in sketch coordinates for ids 0..3; the lines keep their IDs."""
        g = self.spine.Geometry
        for i in range(len(lines)):
            g[i].StartPoint, g[i].EndPoint = V(100 + 10 * i, 100, 0), V(105 + 10 * i, 105, 0)
        for i, (p, q) in enumerate(lines):
            g[i].StartPoint, g[i].EndPoint = V(p[0], p[1], 0), V(q[0], q[1], 0)
        self.spine.Geometry = g

    def widen(self, width):
        self.width = width
        w, h = self.W, self.H
        self.setSpine([((0, 0), (0, h)), ((0, h), (w, h)), ((w, h), (w, 0)), ((w, 0), (0, 0))])

    def turnModel(self, degrees):
        self.turn = degrees
        self.spine.Placement = self.spinePlacement()
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = self.profilePlacement()
        else:
            self.profile.Placement = self.profilePlacement()



    def reparameteriseProfile(self, degrees):
        """The profile's placement turned `degrees` about its normal (Z) and its lines drawn at the
        sketch coordinates turned back: the same square in the body, line for line."""
        back = App.Rotation(Z, -degrees)
        g = self.profile.Geometry
        for line in g:
            s, e = back.multVec(V(line.StartPoint)), back.multVec(V(line.EndPoint))
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(V(), App.Rotation(Z, degrees))

    def redrawFar(self, which):
        """The right leg moved to x = 50 and the lines named in `which` ("top", "bottom") deleted
        and drawn anew at their places."""
        self.width = 50
        w, h = self.W, self.H
        left, top, right, bottom = self.spine.Geometry
        right.StartPoint, right.EndPoint = V(w, h, 0), V(w, 0, 0)
        top.StartPoint, top.EndPoint = V(0, h, 0), V(w, h, 0)
        bottom.StartPoint, bottom.EndPoint = V(w, 0, 0), V(0, 0, 0)
        geometry = [left, right]
        geometry.append(Part.LineSegment(V(0, h, 0), V(w, h, 0)) if "top" in which else top)
        geometry.append(Part.LineSegment(V(w, 0, 0), V(0, 0, 0)) if "bottom" in which else bottom)
        self.spine.Geometry = geometry


class TopAndBottomRedrawnFarProfileReparameterised90(Ring):
    """The top and bottom lines drawn anew, the right leg moved to x = 50, and the profile
    reparameterised a quarter turn on itself (the same square in the body), in one recompute: two
    names left at opposite places with a frame turned. Every reference stays at its place."""

    AXES = ("M3", "E2", "E3")
    REFS = ("datum_left_outer", "datum_right_outer", "point_bottom_left", "datum_top_outer")
    degrees = 90

    def edit(self, doc):
        self.redrawFar(("top", "bottom"))
        self.reparameteriseProfile(self.degrees)


class TopAndBottomRedrawnFarProfileReparameterised180(TopAndBottomRedrawnFarProfileReparameterised90):
    degrees = 180


class TopRedrawnFarProfileReparameterised180(TopAndBottomRedrawnFarProfileReparameterised90):
    """Only the top line drawn anew (three names found: one cyclic order), the right leg at 50, the
    profile reparameterised half a turn."""

    degrees = 180

    def edit(self, doc):
        self.redrawFar(("top",))
        self.reparameteriseProfile(self.degrees)
