# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prA1e-r2: SweepFold with other Tips."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge, face
from PartDesignTests.Scenarios import models as m

V = App.Vector

TOP = 10.0  # the height of the shell at x = 1
STEP = -2.0  # the drop over the steep plate
XS = (-3.0, 1.0, 1.2, 3.0, 20.0)  # the plates' x ranges
SIDE = 2.0  # the square
TOL = 1e-6


def height(i, x):
    """The height of plate i at x."""
    return (
        TOP + (x - 1.0),
        TOP + STEP * (x - 1.0) / 0.2,
        TOP + STEP,
        TOP + STEP,
    )[i]


def plate(i):
    xa, xb = XS[i], XS[i + 1]
    corners = [(xa, -10.0), (xb, -10.0), (xb, 10.0), (xa, 10.0)]
    points = [V(x, y, height(i, x)) for x, y in corners]
    return Part.Face(Part.makePolygon(points + points[:1])).toNurbs().Faces[0]


def shell(order=(0, 1, 2, 3)):
    faces = [plate(i) for i in range(4)]
    return Part.Shell([faces[i] for i in order])


class SweepFold(Scenario):
    """The model and its references; a subclass moves the profile (and maybe reorders the shell)."""

    abstract = True
    area = "sweep-later-feature"
    CLASSES = ("A",)
    AXES = ("M2", "E4")
    ISSUE = "ops#524"
    FOUND_BY = "review prA1e-r2"
    TIER = "F"
    # E<j>_p<i>: the piece of the square's edge j (0 bottom, 1 right, 2 top, 3 left) on plate i
    # before the edit; C_p<i>: its cap on plate i
    REFS = (
        "E0_p0",
        "E0_p1",
        "E0_p2",
        "E1_p2",
        "E2_p0",
        "E2_p1",
        "E2_p2",
        "E3_p0",
        "C_p0",
        "C_p1",
        "C_p2",
    )
    PIECES = {  # ref: (profile edge, plate), edge None for the cap
        "E0_p0": (0, 0),
        "E0_p1": (0, 1),
        "E0_p2": (0, 2),
        "E1_p2": (1, 2),
        "E2_p0": (2, 0),
        "E2_p1": (2, 1),
        "E2_p2": (2, 2),
        "E3_p0": (3, 0),
        "C_p0": (None, 0),
        "C_p1": (None, 1),
        "C_p2": (None, 2),
    }
    move = 2.0  # the profile's offset in X after the edit
    order = None  # the shell's face order after the edit

    def __init__(self, config):
        super().__init__(config)
        self.dx = 0.0  # the profile's offset in X now

    # Geometry of the pieces at the profile's offset dx

    def span(self, plateIndex):
        """The x range of the square over plate i at the current offset, or None."""
        x0, x1 = max(self.dx, XS[plateIndex]), min(self.dx + SIDE, XS[plateIndex + 1])
        return (x0, x1) if x1 - x0 > TOL else None

    def horizontal(self, y, plateIndex):
        span = self.span(plateIndex)
        if span is None:
            return None
        points = [V(x, y, height(plateIndex, x)) for x in span]
        centre = (points[0] + points[1]) * 0.5
        length = (points[1] - points[0]).Length
        return edge(
            where=lambda e: (e.CenterOfMass - centre).Length < TOL and abs(e.Length - length) < TOL
        )

    def vertical(self, x):
        """The square's left or right edge (a whole edge, wherever the plates carry it)."""
        plateIndex = next(i for i in range(4) if XS[i] + TOL < x < XS[i + 1] - TOL)
        centre = V(x, SIDE / 2, height(plateIndex, x))
        return edge(
            where=lambda e: (e.CenterOfMass - centre).Length < TOL and abs(e.Length - SIDE) < TOL
        )

    def cap(self, plateIndex):
        span = self.span(plateIndex)
        if span is None:
            return None
        x0, x1 = span
        centre = V((x0 + x1) / 2, SIDE / 2, height(plateIndex, (x0 + x1) / 2))
        slope = (height(plateIndex, x1) - height(plateIndex, x0)) / (x1 - x0)
        area = (x1 - x0) * SIDE * math.sqrt(1 + slope**2)
        return face(
            where=lambda f: (f.CenterOfMass - centre).Length < TOL and abs(f.Area - area) < 1e-5
        )

    def expected(self, name):
        """The predicate of the piece, or BROKEN where the profile has left the plate."""
        edgeIndex, plateIndex = self.PIECES[name]
        if edgeIndex is None:
            piece = self.cap(plateIndex)
        elif edgeIndex in (1, 3):
            piece = self.vertical(self.dx + (SIDE if edgeIndex == 1 else 0.0))
        else:
            piece = self.horizontal(0.0 if edgeIndex == 0 else SIDE, plateIndex)
        return BROKEN if piece is None else piece

    def build(self, doc):
        body = m.body(doc)
        self.shape = doc.addObject("Part::Feature", "Plates")
        self.shape.Shape = shell()
        self.sketch = body.newObject("Sketcher::SketchObject", "Profile")
        self.sketch.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), [""])]
        self.sketch.MapMode = "FlatFace"
        self.sketch.addGeometry(m.rectangle(0, 0, SIDE, SIDE) + m.rectangle(12, 0, 14, 3), False)
        self.pad = m.pad(body, self.sketch, 1)
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.shape, [f"Face{i + 1}" for i in range(4)])
        doc.recompute()
        tip = self.makeTip(doc, body)
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(tip, self.names(tip, self.expected(name))[0])]
            point.MapMode = "CenterOfMass"
            body.Tip = tip
            self.ref(
                name,
                point,
                "AttachmentSupport",
                lambda name=name: self.expected(name),
                Attached(),
            )

    def edit(self, doc):
        self.dx = self.move
        self.sketch.AttachmentOffset = App.Placement(V(self.move, 0, 0), App.Rotation())
        if self.order:
            self.shape.Shape = shell(self.order)
            self.pad.UpToShape = (self.shape, [f"Face{i + 1}" for i in range(4)])



    TIP = "subbox"

    def makeTip(self, doc, body):
        kind = self.TIP
        box = ("PartDesign::AdditiveBox" if kind in ("addbox", "addboxfar", "attached") else "PartDesign::SubtractiveBox")
        if kind in ("subbox", "addbox", "addboxfar"):
            tip = body.newObject(box, "Tip")
            tip.Length = tip.Width = tip.Height = 0.5
            tip.MapMode = "Deactivated"
            z = 8.0 if kind == "addboxfar" else 2
            tip.Placement = App.Placement(V(12.75, 1, z), App.Rotation())
        elif kind == "subcyl":
            tip = body.newObject("PartDesign::SubtractiveCylinder", "Tip")
            tip.Radius = 0.3
            tip.Height = 1.0
            tip.MapMode = "Deactivated"
            tip.Placement = App.Placement(V(13, 1.5, 2), App.Rotation())
        elif kind == "pocket":
            sk = body.newObject("Sketcher::SketchObject", "PocketSk")
            sk.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), [""])]
            sk.MapMode = "FlatFace"
            sk.addGeometry(m.circle(13, 1.5, 0.3), False)
            tip = body.newObject("PartDesign::Pocket", "Tip")
            tip.Profile = sk
            tip.Type = "Length"
            tip.Length = 3
            tip.Reversed = True
            tip.Refine = False
        elif kind == "fillet":
            idx = None
            for i, e in enumerate(self.pad.Shape.Edges):
                if (e.CenterOfMass - V(12, 0, 4)).Length < 1e-6 and abs(e.Length - 8) < 1e-6:
                    idx = i + 1
            tip = body.newObject("PartDesign::Fillet", "Tip")
            tip.Base = (self.pad, ["Edge%d" % idx])
            tip.Radius = 0.2
        elif kind == "pattern":
            tip = doc.addObject("PartDesign::LinearPattern", "Tip")
            tip.Originals = [self.pad]
            tip.Direction = (m.originFeature(body, "Y_Axis"), [""])
            tip.Mode = "Spacing"
            tip.Offset = 6
            tip.Occurrences = 2
            tip.Refine = False
            body.addObject(tip)
        elif kind == "mirror":
            tip = doc.addObject("PartDesign::Mirrored", "Tip")
            tip.Originals = [self.pad]
            tip.MirrorPlane = (m.originFeature(body, "XZ_Plane"), [""])
            tip.Refine = False
            body.addObject(tip)
        elif kind == "pad2":
            sk = body.newObject("Sketcher::SketchObject", "Pad2Sk")
            sk.AttachmentSupport = [(m.originFeature(body, "XZ_Plane"), [""])]
            sk.MapMode = "FlatFace"
            sk.addGeometry(m.rectangle(13, 1, 15, 2), False)
            tip = body.newObject("PartDesign::Pad", "Tip")
            tip.Profile = sk
            tip.Type = "Length"
            tip.Length = 2
            tip.Midplane = True
            tip.Refine = False
        elif kind == "pocketx":
            # a pocket whose direction is along x: cut into the second rectangle from its side
            sk = body.newObject("Sketcher::SketchObject", "PocketSk")
            sk.AttachmentSupport = [(m.originFeature(body, "YZ_Plane"), [""])]
            sk.MapMode = "FlatFace"
            sk.addGeometry(m.rectangle(1, 1, 2, 2), False)
            tip = body.newObject("PartDesign::Pocket", "Tip")
            tip.Profile = sk
            tip.Type = "Length"
            tip.Length = 13.5
            tip.Reversed = True
            tip.Refine = False
        elif kind == "attached":
            tip = body.newObject(box, "Tip")
            tip.Length = tip.Width = tip.Height = 0.5
            tip.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), [""])]
            tip.MapMode = "FlatFace"
            tip.AttachmentOffset = App.Placement(V(12.75, 1, 2), App.Rotation())
        else:
            raise ValueError(kind)
        self.tip = tip
        return tip

class TPad2Half(SweepFold):
    """pad2, move 0.5, order None."""

    TIP = "pad2"
    move = 0.5
    order = None


class TPad2HalfReorder(SweepFold):
    """pad2, move 0.5, order (2, 1, 0, 3)."""

    TIP = "pad2"
    move = 0.5
    order = (2, 1, 0, 3)


class TPad2Move(SweepFold):
    """pad2, move 1.1, order None."""

    TIP = "pad2"
    move = 1.1
    order = None


class TPad2MoveReorder(SweepFold):
    """pad2, move 1.1, order (2, 1, 0, 3)."""

    TIP = "pad2"
    move = 1.1
    order = (2, 1, 0, 3)


class TPad2Two(SweepFold):
    """pad2, move 2.0, order None."""

    TIP = "pad2"
    move = 2.0
    order = None


class TPad2TwoReorder(SweepFold):
    """pad2, move 2.0, order (2, 1, 0, 3)."""

    TIP = "pad2"
    move = 2.0
    order = (2, 1, 0, 3)


class TPocketXHalf(SweepFold):
    """pocketx, move 0.5, order None."""

    TIP = "pocketx"
    move = 0.5
    order = None


class TPocketXHalfReorder(SweepFold):
    """pocketx, move 0.5, order (2, 1, 0, 3)."""

    TIP = "pocketx"
    move = 0.5
    order = (2, 1, 0, 3)


class TPocketXMove(SweepFold):
    """pocketx, move 1.1, order None."""

    TIP = "pocketx"
    move = 1.1
    order = None


class TPocketXMoveReorder(SweepFold):
    """pocketx, move 1.1, order (2, 1, 0, 3)."""

    TIP = "pocketx"
    move = 1.1
    order = (2, 1, 0, 3)


class TPocketXTwo(SweepFold):
    """pocketx, move 2.0, order None."""

    TIP = "pocketx"
    move = 2.0
    order = None


class TPocketXTwoReorder(SweepFold):
    """pocketx, move 2.0, order (2, 1, 0, 3)."""

    TIP = "pocketx"
    move = 2.0
    order = (2, 1, 0, 3)



class TAttachedTipMoves(SweepFold):
    """attached box Tip; the edit moves the profile by 0.5 and the Tip's offset by 0.1 together."""

    TIP = "attached"
    move = 0.5

    def edit(self, doc):
        self.tip.AttachmentOffset = App.Placement(V(12.85, 1, 2), App.Rotation())
        super().edit(doc)


class TAttachedTipMovesReorder(TAttachedTipMoves):
    AXES = ("M2", "E2", "E4")
    order = (2, 1, 0, 3)


class TAttachedTipOnlyMoves(SweepFold):
    """attached box Tip moved only (the profile stays)."""

    TIP = "attached"
    move = 0.0

    def edit(self, doc):
        self.tip.AttachmentOffset = App.Placement(V(12.85, 1, 2), App.Rotation())
        self.dx = 0.0


class TAttachedTipRotates(SweepFold):
    """attached box Tip rotated about z by 30 degrees together with a 0.5 profile move."""

    TIP = "attached"
    move = 0.5

    def edit(self, doc):
        self.tip.AttachmentOffset = App.Placement(V(12.75, 1, 2), App.Rotation(V(0, 0, 1), 30))
        super().edit(doc)
