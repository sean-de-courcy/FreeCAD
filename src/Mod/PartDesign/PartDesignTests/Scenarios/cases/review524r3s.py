# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prA1e-r3 (Sonnet, ops#524): the frames test of placeOnUpToFace() under composed edits.

A plate (z = 10, x -10..20, y -10..10) with a hole x -1..1, y -1..1 and its fill, a rectangle
x -5..5, y -3..3 padded up to them: A is the ring piece (the cap's face around the hole), M the
fill's piece. The edits change the target's frame against the plate's (a placement), together with
a resize or alone, where the old inside point's foot no longer tells that nothing moved.

ResizeRightPlateShifted, ResizeRightProfileShifted, ProfileShiftedAlone, BigHoleProfileShifted and
BigHoleResizeAndShift A break (right -> loud, accepted by PLAN decision 215 under decision 120 (4)):
the path from the saved foot to the ring's new inside point crosses the hole. ops#558 keeps them
with the target's placement saved against the plate's. SlotCrossPlacement (wrong here and on
integration, a tier-1 overlap) is debt in the ops repo's corpus inbox.
"""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0


def outer(z, x0=-10, y0=-10, x1=20, y1=10):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.makePolygon(c + c[:1])


def rectFace(x0, y0, x1, y1, z):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.Face(Part.makePolygon(c + c[:1])).toNurbs().Faces[0]


def gridShell(z, holes, x0=-10, y0=-10, x1=20, y1=10):
    wires = [outer(z, x0, y0, x1, y1)]
    for hx0, hy0, hx1, hy1 in holes:
        h = [V(hx0, hy0, z), V(hx0, hy1, z), V(hx1, hy1, z), V(hx1, hy0, z)]
        wires.append(Part.makePolygon(h + h[:1]))
    plate = Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), wires).toNurbs().Faces[0]
    return Part.Shell([plate] + [rectFace(*hole, z) for hole in holes])


class Base(Scenario):
    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#524"
    FOUND_BY = "review prA1e-r3"
    TIER = "F"
    AXES = ("M5", "E1")
    area = "frames-test"
    REFS = ("A",)
    HOLES = ((-1, -1, 1, 1),)
    RECT = (-5, -3, 5, 3)
    BEFORE = {"A": (-4, -2.5)}
    AFTER = {"A": (-4, -2.5)}
    shift = (0.0, 0.0)  # where the expected piece moves with the edit (placement of the profile)

    def place(self, x, y):
        return face(contains=V(x, y, HEIGHT))

    def shell(self, holes=None):
        return gridShell(HEIGHT, holes or self.HOLES)

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.body = body
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.RECT), body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, ["Face%d" % (i + 1) for i in range(len(self.plate.Shape.Faces))])
        self.pad.Refine = False
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(self.pad, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(self.pad, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = self.pad

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            after = self.AFTER[name]
            if after is None:
                return BROKEN
            return self.place(*after)

        return expect

    def edit(self, doc):
        self.change(doc)
        self.edited = True


class ResizeRightPlateShifted(Base):
    """The right edge moves +1 while the plate (and its hole) is placed 0.5 in x: the target's
    frame moved against the plate's; the ring piece stays one piece."""

    def change(self, doc):
        m.moveRectangle(self.profile, -5, -3, 6, 3)
        self.plate.Placement = App.Placement(V(0.5, 0, 0), App.Rotation())


class ResizeRightProfileShifted(Base):
    """The right edge moves +1 and the sketch is placed 0.5 in x."""

    AFTER = {"A": (-3.5, -2.5)}

    def change(self, doc):
        m.moveRectangle(self.profile, -5, -3, 6, 3)
        self.profile.Placement = App.Placement(V(0.5, 0, 0), App.Rotation())


class ResizeRightRaised(Base):
    """The right edge moves +1 and the sketch is raised 2 along the sweep."""

    def change(self, doc):
        m.moveRectangle(self.profile, -5, -3, 6, 3)
        self.profile.Placement = App.Placement(V(0, 0, 2), App.Rotation())


class RaisedAlongSweep(Base):
    """Control: the sketch is raised 2 along the sweep alone."""

    def change(self, doc):
        self.profile.Placement = App.Placement(V(0, 0, 2), App.Rotation())


class TurnedHalfAboutHole(Base):
    """The sketch turns 180 degrees about the hole's centre: the symmetric profile and the hole
    map onto themselves, the ring is the same piece."""

    def change(self, doc):
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), 180))


class TurnedAboutPivot(Base):
    """The sketch turns 20 degrees about a point on the ring (-4, -2.5)."""

    abstract = True
    PIVOT = (-4.0, -2.5)

    def change(self, doc):
        px, py = self.PIVOT
        rot = App.Rotation(V(0, 0, 1), 20)
        centre = V(px, py, 0)
        self.profile.Placement = App.Placement(centre - rot.multVec(centre), rot)


class TurnedAboutPivotA(TurnedAboutPivot):
    abstract = False
    PIVOT = (-4.0, -2.5)
    AFTER = {"A": (-4, -2.5)}


class TurnedAboutPivotB(TurnedAboutPivot):
    abstract = False
    PIVOT = (-3.0, 2.0)
    BEFORE = {"A": (-3, 2)}
    AFTER = {"A": (-3, 2)}


class PlateHoleMovedUnderPiece(Base):
    """The plate is rebuilt with its hole moved 4 to the left (x -5..-3): the ring is still the
    one piece, around a hole elsewhere."""

    HOLES = ((-1, -1, 1, 1),)

    def change(self, doc):
        self.plate.Shape = gridShell(HEIGHT, ((-5, -1, -3, 1),))


class TwoRectsDeleteFirst(Base):
    """Two disjoint rectangles on the plain plate (a ring-less case): A is the left piece; the
    edit deletes the left rectangle (lines kept for the right). A must break."""

    HOLES = ()
    BEFORE = {"A": (-4, 0)}
    AFTER = {"A": None}

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.body = body
        self.plate = m.feature(doc, "Plate", Part.Shell([rectFace(-10, -10, 20, 10, HEIGHT)]))
        self.profile = m.sketch(
            doc, "Profile", m.rectangle(-5, -1, -3, 1) + m.rectangle(3, -1, 5, 1), body
        )
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, ["Face1"])
        self.pad.Refine = False
        doc.recompute()
        point = body.newObject("PartDesign::Point", "OnA")
        sub = self.names(self.pad, self.place(-4, 0))[0]
        point.AttachmentSupport = [(self.pad, sub)]
        point.MapMode = "CenterOfMass"
        self.ref("A", point, "AttachmentSupport", self.expectation("A"), Attached())
        body.Tip = self.pad

    def change(self, doc):
        self.profile.delGeometries([0, 1, 2, 3])


class ProfileShiftedAlone(Base):
    """The sketch is placed 0.5 in x alone (the ring piece moves with it, over the hole)."""

    AFTER = {"A": (-3.5, -2.5)}

    def change(self, doc):
        self.profile.Placement = App.Placement(V(0.5, 0, 0), App.Rotation())


class ProfileShiftedUp(Base):
    """The sketch is placed 0.5 in y alone."""

    AFTER = {"A": (-4, -2.0)}

    def change(self, doc):
        self.profile.Placement = App.Placement(V(0, 0.5, 0), App.Rotation())


class PlateShiftedAlone(Base):
    """The plate is placed 0.5 in x alone."""

    def change(self, doc):
        self.plate.Placement = App.Placement(V(0.5, 0, 0), App.Rotation())


class BigHoleProfileShifted(Base):
    """A 6 x 4 hole under a 12 x 7 rectangle; the sketch is placed 1 in x."""

    HOLES = ((-3, -2, 3, 2),)
    RECT = (-6, -3.5, 6, 3.5)
    BEFORE = {"A": (-5.5, 0)}
    AFTER = {"A": (-4.5, 0)}

    def change(self, doc):
        self.profile.Placement = App.Placement(V(1, 0, 0), App.Rotation())


class BigHoleResizeAndShift(Base):
    """The same, the right edge moves +1 and the sketch is placed 1 in x."""

    HOLES = ((-3, -2, 3, 2),)
    RECT = (-6, -3.5, 6, 3.5)
    BEFORE = {"A": (-5.5, 0)}
    AFTER = {"A": (-4.5, 0)}

    def change(self, doc):
        m.moveRectangle(self.profile, -6, -3.5, 7, 3.5)
        self.profile.Placement = App.Placement(V(1, 0, 0), App.Rotation())


class SlotCrossGeometry(Base):
    """A slot (x -0.2..0.2, y -6..6, filled) cuts the plate under the rectangle x -8..-0.1; A is the
    plate's piece left of it. The rectangle is redrawn at x 0.1..8: A's piece is gone (the plate's
    piece right of the slot takes the name) and must break."""

    HOLES = ((-0.2, -6, 0.2, 6),)
    RECT = (-8, -3, -0.1, 3)
    BEFORE = {"A": (-5, 0)}
    AFTER = {"A": None}

    def change(self, doc):
        m.moveRectangle(self.profile, 0.1, -3, 8, 3)


class SlotCrossSmall(SlotCrossGeometry):
    """The rectangle is redrawn at x -0.15..8: the same."""

    def change(self, doc):
        m.moveRectangle(self.profile, -0.15, -3, 8, 3)


class SlotCrossPlacementSmall(SlotCrossGeometry):
    """The sketch is placed 0.2 in x: the rectangle x -7.8..0.1 reaches the slot's far side; A's
    piece is still the plate's left part (x -7.8..-0.2) and must be followed (not a break)."""

    AFTER = {"A": (-5, 0)}

    def change(self, doc):
        self.profile.Placement = App.Placement(V(0.2, 0, 0), App.Rotation())
