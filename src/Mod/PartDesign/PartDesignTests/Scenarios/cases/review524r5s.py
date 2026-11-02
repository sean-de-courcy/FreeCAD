# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr403-r5 (Sonnet, ops#524): where ops#516's nearerTwin rule meets this PR's lone-piece
up-to face test, and a later Pipe (fork PR 383) after the Pad whose far pieces are referenced.

TwinTurn*: `sketch_twin_attach.py`'s model (a disc r = 3 at (3, 3) padded up to an elliptic-holed
shell at z = 10: twin cap pieces T and Bo, the fill's piece F) with the hole turned AND the disc
moved by (DX, 0) in the same edit, so the twins trade (nearerTwin) while the fill's piece moves
alone on its face.
PipeAfter*: `review524r4s.py`'s slide with an AdditivePipe after the Pad.

FillTurn*, and the fill reference of every TwinTurn* case, break: the hole's turn rebuilds the
fill plate under its piece (decision 199 (4)'s plate-geometry family, accepted in the PR
description's Decision 120 (4) line).
"""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0
CENTRE = (3.0, 3.0)
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def ellipseShell(z, rot=0.0):
    c = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
    edge_ = Part.Ellipse(V(CENTRE[0], CENTRE[1], z), 4, 1).toShape()
    if rot:
        edge_.rotate(V(CENTRE[0], CENTRE[1], z), V(0, 0, 1), rot)
    hole = Part.Face(Part.Wire([edge_]))
    plate = Part.Face(Part.makePolygon(c + c[:1])).cut(hole).Faces[0].toNurbs().Faces[0]
    return Part.Shell([plate, hole.toNurbs().Faces[0]])


def turned(x, y, degrees):
    a = math.radians(degrees)
    dx, dy = x - CENTRE[0], y - CENTRE[1]
    return (CENTRE[0] + dx * math.cos(a) - dy * math.sin(a), CENTRE[1] + dx * math.sin(a) + dy * math.cos(a))


class TwinTurn(Scenario):
    abstract = True
    area = "twin-and-lone"
    CLASSES = ("A", "E")
    AXES = ("M5", "E7", "E1")
    ISSUE = "ops#524"
    FOUND_BY = "review pr403-r5"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    TURN = 60.0
    DX = 0.5
    FLAT = False
    REFS = ("top", "bottom", "fill")
    SPOTS = {"top": (3.0, 5.5), "bottom": (3.0, 0.5), "fill": (3.0, 3.0)}
    edited = False

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plate = m.feature(doc, "Plate", ellipseShell(HEIGHT))
        self.profile = m.sketch(doc, "Profile", [m.circle(CENTRE[0], CENTRE[1], 3)], body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, ["Face1", "Face2"])
        self.pad.Refine = False
        doc.recompute()
        for name in self.REFS:
            if self.FLAT:
                owner = body.newObject("Sketcher::SketchObject", "S" + name)
                mode = "FlatFace"
            else:
                owner = body.newObject("PartDesign::Point", "P" + name)
                mode = "CenterOfMass"
            owner.AttachmentSupport = [(self.pad, self.names(self.pad, self.at(*self.SPOTS[name]))[0])]
            owner.MapMode = mode
            self.ref(name, owner, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = self.pad

    @staticmethod
    def at(x, y):
        return face(contains=V(x, y, HEIGHT))

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.at(*self.SPOTS[name])
            if name == "fill":
                return self.at(*self.SPOTS[name])
            if abs(abs(self.TURN) - 90.0) < 1e-9:
                return BROKEN
            return self.at(*turned(*self.SPOTS[name], self.TURN))

        return expect

    def edit(self, doc):
        self.plate.Shape = ellipseShell(HEIGHT, rot=self.TURN)
        self.pad.UpToShape = (self.plate, ["Face1", "Face2"])
        self.profile.moveGeometry(0, 3, V(self.DX, 0, 0), True)
        self.edited = True


class TwinTurn60Shift(TwinTurn):
    TURN = 60.0
    DX = 0.5


class TwinTurn80Shift(TwinTurn):
    TURN = 80.0
    DX = 0.5


class TwinTurn60ShiftFlat(TwinTurn):
    FLAT = True
    TURN = 60.0
    DX = 0.5


class TwinTurn90Shift(TwinTurn):
    TURN = 90.0
    DX = 0.5


class TwinTurn45Shift(TwinTurn):
    TURN = 45.0
    DX = 0.3


class TwinTurn45ShiftFlat(TwinTurn):
    FLAT = True
    TURN = 45.0
    DX = 0.3


class TwinTurn30ShiftFlat(TwinTurn):
    FLAT = True
    TURN = 30.0
    DX = 0.3


# -- the later Pipe ---------------------------------------------------------------------------


class PipeBase(Scenario):
    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#524"
    FOUND_BY = "review pr403-r5"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    HOLE = (-1, -2, 1, 2)
    edited = False
    REFS = ("L", "M")
    BEFORE = {"L": (-2, 0), "M": (-0.5, 0)}
    AFTER = {"L": (-1.75, 0), "M": (-0.25, 0)}

    def S(self, v):
        return v * self.scale

    def P(self, x, y, z=HEIGHT):
        return V(self.S(x), self.S(y), self.S(z))

    def poly(self, points, z=HEIGHT):
        c = [self.P(x, y, z) for x, y in points]
        return Part.makePolygon(c + c[:1])

    def shell(self, hole=None):
        hx0, hy0, hx1, hy1 = hole or self.HOLE
        outer = self.poly([(-10, -10), (20, -10), (20, 10), (-10, 10)])
        h = self.poly([(hx0, hy0), (hx0, hy1), (hx1, hy1), (hx1, hy0)])
        plate = Part.Face(Part.Plane(self.P(0, 0), V(0, 0, 1)), [outer, h]).toNurbs().Faces[0]
        fill = Part.Face(self.poly([(hx0, hy0), (hx1, hy0), (hx1, hy1), (hx0, hy1)])).toNurbs().Faces[0]
        return Part.Shell([plate, fill])

    def rect(self, x0, y0, x1, y1):
        return m.rectangle(self.S(x0), self.S(y0), self.S(x1), self.S(y1))

    def moveRect(self, x0, y0, x1, y1):
        m.moveRectangle(self.profile, self.S(x0), self.S(y0), self.S(x1), self.S(y1))

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(doc, "Profile", self.rect(-3, -0.5, 0, 0.5), body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, ["Face1", "Face2"])
        self.pad.Refine = False
        doc.recompute()
        target = self.later(doc, body, self.pad)
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(target, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(target, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = target

    def place(self, x, y):
        return face(contains=self.P(x, y))

    def later(self, doc, body, target):
        return target

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            if self.AFTER[name] is None:
                return BROKEN
            return self.place(*self.AFTER[name])

        return expect

    def edit(self, doc):
        self.change(doc)
        self.edited = True


class PipeAfterSlide(PipeBase):
    """The slide by 0.5 (x -2.5..0.5), with an AdditivePipe after the Pad: a 2 x 2 square at
    (-2, 0), swept up z 0..6 then along -x to x = -8, fused with the Pad's side."""

    area = "later-pipe"
    AXES = ("M5", "E1")

    def later(self, doc, body, target):
        path = m.sketch(
            doc,
            "Path",
            m.polyline([(self.S(-2), 0), (self.S(-2), self.S(6)), (self.S(-8), self.S(6))]),
            body,
            placement=XZ,
        )
        prof = m.sketch(
            doc, "PipeProfile", m.rectangle(self.S(-3), self.S(-1), self.S(-1), self.S(1)), body
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = prof
        pipe.Spine = (path, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        doc.recompute()
        return pipe

    def change(self, doc):
        self.moveRect(-2.5, -0.5, 0.5, 0.5)


class PipeAfterAcross(PipeAfterSlide):
    """Moved across the hole: L's piece is gone, M's carries on at x 0.5..1."""

    AFTER = {"L": None, "M": (0.75, 0)}

    def change(self, doc):
        self.moveRect(0.5, -0.5, 3.5, 0.5)


class FillControlShiftOnly(TwinTurn):
    """Control: the disc moves 0.5, the hole stays: the fill's piece moves alone on its own face."""

    TURN = 0.0
    DX = 0.5


class FillTurn60NoShift(TwinTurn):
    """Control: the hole turns 60, the disc stays: the fill (the ellipse turned) keeps its centre."""

    TURN = 60.0
    DX = 0.0


class FillTurn30Shift(TwinTurn):
    """The hole turns 30 (no trade), the disc moves 0.5."""

    TURN = 30.0
    DX = 0.5
