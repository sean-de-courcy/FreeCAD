# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr403-r5 (Opus, ops#524): a lone far piece on a curved or closed up-to face, slid alone,
and ops#516's twins under a placement move.

Tube: an up-to shell of two B-spline faces: the full lateral face of a cylinder of radius 10 whose
axis is the Y axis (y -10..10), its seam turned to the bottom (x = 0, z = -10), with a slot
x -6..6, y 0.5..3 cut through its top, and the slot's fill. A rectangle on the XY plane, inside the
tube, padded up to the shell: its cap is cut into P (y -1..0.5), lone on the holed tube face, and
the slot's piece (y 0.5..1). Roof: the same with an open roof, the top of a cylinder of radius 200
(no seam), z = 10 on its top line. The edits slide P alone on its face, overlapping its old place,
by the sketch's geometry or its Placement; P stays one piece on the same face. Expected: P holds
the cap piece at its new place.

Before round 5's fix, PR 403's placeOnUpToFace() broke each slide across the curvature: sameUpToFaces() compares the
normal at the piece's new point with the one saved at its old point (1e-6 rad), so any slide on a
curved face reads as "off its place on its up-to face", by sketch or by placement. A slide along
the axis by placement right above the far side's seam breaks as "can't be told": upToPath()'s strip
runs along the sweep both ways and meets the seam on the far side of the closed face.

Twins: `sketch_twin_attach.py`'s model (a disc of radius 3 at (3, 3) up to a plate with an
elliptic hole a 4, b 1 and its fill), the hole turned 0, 30 or 60 degrees while the disc's sketch is
placed 0.3 in x: ops#516's nearer-twin rule beside the PR's up-to face test (twins only).

Round 5's fix (A1i): the faces under the piece's new point are matched without the normal (it
is another point's on a curved face); the frames test at the saved point keeps it. A placement
move that reaches the path test over the closed tube (TubeNurbsCentredPlacedAlongAxis, and
TubeNurbsSeamBelowPlaced) stays broken, with decision 215's family queued in ops#558.
"""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
R = 10.0


def tubeShell(seamAt, slot=False, nurbs=False):
    """The tube's shell: the cylinder's lateral face with its seam at the top (`seamAt` 'top') or
    the bottom ('bottom'), and a plane face x 20..30, y -10..10 at z = 10. With `slot`, the tube
    has a slot x -6..6, y 0.5..3 cut through its top, and the slot's fill (the cylinder's piece
    there) is the shell's second face instead."""
    cyl = Part.makeCylinder(R, 2 * R, V(0, -R, 0), V(0, 1, 0))
    lateral = [f for f in cyl.Faces if f.Surface.TypeId == "Part::GeomCylinder"][0]
    if seamAt == "bottom":
        lateral.rotate(V(0, 0, 0), V(0, 1, 0), 180)
    if slot:
        box = Part.makeBox(12, 2.5, 10, V(-6, 0.5, 5))
        holed = lateral.cut(box).Faces
        fill = lateral.common(box).Faces
        assert len(holed) == 1 and len(fill) == 1, (len(holed), len(fill))
        if nurbs:
            return Part.Shell([holed[0].toNurbs().Faces[0], fill[0].toNurbs().Faces[0]])
        return Part.Shell([holed[0], fill[0]])
    c = [V(20, -10, R), V(30, -10, R), V(30, 10, R), V(20, 10, R)]
    side = Part.Face(Part.makePolygon(c + c[:1]))
    return Part.Shell([lateral, side])


def roofShell(radius, z=10.0):
    """A gently curved roof: the top of a cylinder of `radius` whose axis is parallel to Y, its
    top line at x = 0, z = `z`, trimmed to x -10..20 (an open face, no seam), with a slot x -6..6,
    y 0.5..3 cut through it and the slot's fill, both as B-splines."""
    cyl = Part.makeCylinder(radius, 20, V(0, -10, z - radius), V(0, 1, 0))
    lateral = [f for f in cyl.Faces if f.Surface.TypeId == "Part::GeomCylinder"][0]
    lateral.rotate(V(0, 0, z - radius), V(0, 1, 0), 180)  # the seam to the bottom, far away
    top = Part.makeBox(30, 20, 5, V(-10, -10, z - 4))
    roof = lateral.common(top).Faces
    assert len(roof) == 1, len(roof)
    box = Part.makeBox(12, 2.5, 10, V(-6, 0.5, z - 5))
    holed = roof[0].cut(box).Faces
    fill = roof[0].common(box).Faces
    assert len(holed) == 1 and len(fill) == 1, (len(holed), len(fill))
    return Part.Shell([holed[0].toNurbs().Faces[0], fill[0].toNurbs().Faces[0]])


class Tube(Scenario):
    abstract = True
    area = "lone-piece-periodic"
    CLASSES = ("A",)
    AXES = ("M5", "E1")
    ISSUE = "ops#524"
    FOUND_BY = "review pr403-r5"
    TIER = "F"
    REFS = ("P",)
    SEAM = "bottom"
    SLOT = True
    NURBS = True
    RECT = (-4, -1, 0, 1)
    SHIFT = 3.0
    Y = -0.25  # the tube piece's middle in y (y -1..0.5); the slot's fill piece is y 0.5..1
    edited = False

    def at(self, x):
        return face(contains=V(x, self.Y, math.sqrt(R * R - x * x)))

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plate = m.feature(doc, "Tube", tubeShell(self.SEAM, self.SLOT, self.NURBS))
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.RECT), body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, ["Face1", "Face2"])
        self.pad.Refine = False
        doc.recompute()
        point = body.newObject("PartDesign::Point", "OnP")
        point.AttachmentSupport = [(self.pad, self.names(self.pad, self.at(self.X0))[0])]
        point.MapMode = "CenterOfMass"
        self.ref("P", point, "AttachmentSupport", self.expect, Attached())
        body.Tip = self.pad

    X0 = -2.0  # P's middle in x before the edit

    def expect(self):
        return self.at(self.X0 + self.SHIFT if self.edited else self.X0)

    def edit(self, doc):
        self.change(doc)
        self.edited = True


class TubeNurbsSeamBelowPlaced(Tube):
    """The sketch placed 3 in x: P slides along the tube's top (x -1..3), overlapping its old
    place."""

    def change(self, doc):
        self.profile.Placement = App.Placement(V(self.SHIFT, 0, 0), App.Rotation())


class TubeNurbsSeamBelowRedrawn(Tube):
    """The same slide by the sketch's geometry (x -1..3)."""

    def change(self, doc):
        m.moveRectangle(self.profile, -4 + self.SHIFT, -1, self.SHIFT, 1)


# ops#516's twins under a placement move

HEIGHT = 10.0
CENTRE = (3.0, 3.0)


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


class TwinsPlaced(Scenario):
    abstract = True
    area = "twins-placed"
    CLASSES = ("A",)
    AXES = ("M5", "E7")
    ISSUE = "ops#524"
    FOUND_BY = "review pr403-r5"
    TIER = "F"
    REFS = ("sketch_top", "sketch_bottom", "datum_top", "datum_bottom")
    SPOTS = {"sketch_top": (3.0, 5.5), "sketch_bottom": (3.0, 0.5), "datum_top": (3.0, 5.5),
             "datum_bottom": (3.0, 0.5)}
    TURN = 30.0
    DX = 0.3
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
            if name.startswith("sketch"):
                owner = body.newObject("Sketcher::SketchObject", name)
                mode = "FlatFace"
            else:
                owner = body.newObject("PartDesign::Point", name)
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
            if abs(abs(self.TURN) - 90.0) < 1e-9:
                return BROKEN
            x, y = turned(*self.SPOTS[name], self.TURN)
            return self.at(x, y)

        return expect

    def edit(self, doc):
        self.plate.Shape = ellipseShell(HEIGHT, rot=self.TURN)
        self.pad.UpToShape = (self.plate, ["Face1", "Face2"])
        self.profile.Placement = App.Placement(V(self.DX, 0, 0), App.Rotation())
        self.edited = True


class TwinsTurned30Placed(TwinsPlaced):
    """The hole turned 30 degrees, the disc's sketch placed 0.3 in x (no trade)."""


class TwinsTurned60Placed(TwinsPlaced):
    """The hole turned 60 degrees (a trade), the disc's sketch placed 0.3 in x."""

    TURN = 60.0


class TwinsPlacedOnly(TwinsPlaced):
    """The disc's sketch placed 0.3 in x alone: the twins slide on their plate, the hole stays."""

    TURN = 0.0


class TubeNurbsCentredPlacedAlongAxis(Tube):
    """The rectangle x -2..2 (P over the tube's top line, right above the seam on the far side),
    the sketch placed -0.2 along the tube's axis (y): the normal under P's point stays the same,
    and the straight path from the saved foot runs along the top."""

    RECT = (-2, -1, 2, 1)
    X0 = 0.0
    SHIFT = 0.0

    def at(self, x):
        y = self.Y - (0.2 if self.edited else 0.0)
        return face(contains=V(x, y, math.sqrt(R * R - x * x)))

    def change(self, doc):
        self.profile.Placement = App.Placement(V(0, -0.2, 0), App.Rotation())


class TubeNurbsCentredRedrawnAlongAxis(TubeNurbsCentredPlacedAlongAxis):
    """Control: the same move by the sketch's geometry."""

    def change(self, doc):
        m.moveRectangle(self.profile, -2, -1.2, 2, 0.8)


class Roof(Tube):
    """A roof of radius 200 (curving 0.0025 mm over the first 1 mm off its top line, 0.06 mm at
    x = 5) instead of the tube; the same rectangle, its tube piece P (y -1..0.5) lone on the
    holed roof face, its slot piece on the fill."""

    abstract = True
    area = "lone-piece-curved"
    RADIUS = 200.0
    HEIGHT = 10.0

    def z(self, x):
        return self.HEIGHT - self.RADIUS + math.sqrt(self.RADIUS ** 2 - x * x)

    def at(self, x):
        return face(contains=V(x, self.Y, self.z(x)))

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plate = m.feature(doc, "Roof", roofShell(self.RADIUS, self.HEIGHT))
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.RECT), body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, ["Face1", "Face2"])
        self.pad.Refine = False
        doc.recompute()
        point = body.newObject("PartDesign::Point", "OnP")
        point.AttachmentSupport = [(self.pad, self.names(self.pad, self.at(-2))[0])]
        point.MapMode = "CenterOfMass"
        self.ref("P", point, "AttachmentSupport", self.expect, Attached())
        body.Tip = self.pad


class RoofRedrawn(Roof):
    """The rectangle redrawn 3 to the right (x -1..3): P slides along the roof, overlapping its
    old place, still one piece on the holed roof face."""

    def change(self, doc):
        m.moveRectangle(self.profile, -4 + self.SHIFT, -1, self.SHIFT, 1)


class RoofRedrawnSmall(Roof):
    """The rectangle redrawn 0.5 to the right (x -3.5..0.5)."""

    SHIFT = 0.5

    def change(self, doc):
        m.moveRectangle(self.profile, -4 + self.SHIFT, -1, self.SHIFT, 1)


class RoofPlaced(Roof):
    """The sketch placed 3 in x."""

    def change(self, doc):
        self.profile.Placement = App.Placement(V(self.SHIFT, 0, 0), App.Rotation())


class RoofRedrawnAlongAxis(Roof):
    """The rectangle redrawn 0.2 along the roof's axis (y -1.2..0.8): the normal under P's point
    stays, a control."""

    SHIFT = 0.0

    def at(self, x):
        y = self.Y - (0.2 if self.edited else 0.0)
        return face(contains=V(x, y, self.z(x)))

    def change(self, doc):
        m.moveRectangle(self.profile, -4, -1.2, 0, 0.8)
