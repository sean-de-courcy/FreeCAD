# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Revolution and Groove up to a face (ops#240): the revolved faces are named from the profile's
edges, as by angle, so references to them follow edits that change how many faces come before
them: a profile edge added and removed, an earlier feature that gains faces, the face moved, and
the type switched to Angle and back.

Every model revolves a profile in the XZ plane (sketch x, y = global x, z) about the Z axis,
counterclockwise from the XZ plane up to a planar face through the axis at `theta` degrees."""

import math

import FreeCAD as App

from .harness import (
    Attached,
    Bound,
    Filleted,
    ReachesFace,
    Scenario,
    V,
    Z,
    edge,
    face,
)
from . import models as m

XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def ray(theta, radius, z):
    """The point at `radius` from the Z axis, `theta` degrees from +X, at height z."""
    a = math.radians(theta)
    return (radius * math.cos(a), radius * math.sin(a), z)


def slab(theta, thickness, length=30):
    """A rectangle with one long side on the ray at `theta` degrees from the origin, `length`
    long, and `thickness` wide on the counterclockwise side of the ray."""
    a = math.radians(theta)
    u = V(math.cos(a), math.sin(a), 0)
    n = V(-u.y, u.x, 0)
    return [(q.x, q.y) for q in (V(0, 0, 0), u * length, u * length + n * thickness, n * thickness)]


def setPolygon(sketch, points):
    """Moves the polygon drawn by `m.polygon()` (geometry 0..n-1) to new corners; its lines keep
    their geometry IDs."""
    count = len(points)
    m.setLines(sketch, {i: (points[i], points[(i + 1) % count]) for i in range(count)})


def cylinder(radius):
    return face("cylinder", where=lambda f: abs(f.Surface.Radius - radius) < 1e-6)


def wallFace(theta, z):
    """The planar face through the Z axis at `theta` degrees, facing the clockwise side (where
    the sweep comes from), containing the point at radius 15 and height z."""
    a = math.radians(theta)
    return face("plane", normal=V(math.sin(a), -math.cos(a), 0), contains=ray(theta, 15, z))


class RevolvedUpToFaceEdit(Scenario):
    """A plate -30..30 x -30..30 x 0..5 and a wall 5 thick on it (`slab(theta, 5)`, 10 high).
    The profile is the rectangle x 10..20, z 5..10, standing on the plate, revolved up to the
    wall's face: a quarter ring at theta = 90. References: a sketch on the ring's top face
    (z = 10), a fillet (radius 1) on its outer top arc (radius 20, z = 10), a binder of its outer
    cylinder (radius 20), and the Revolution's own up-to face."""

    abstract = True
    area = "RevolutionUpToFace"
    MULTI = True
    REFS = ("sketch_top", "fillet_outer_arc", "binder_outer", "up_to_wall")
    FEATURE = "PartDesign::Revolution"
    theta = 90

    def top(self):
        return face("plane", normal=Z, through=(0, 0, 10), contains=ray(30, 15, 10))

    def outerArc(self):
        return edge("circle", center=(0, 0, 10), radius=20)

    def outer(self):
        return cylinder(20)

    def wall(self):
        return wallFace(self.theta, 10)

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        plate = m.sketch(doc, "Plate", m.rectangle(-30, -30, 30, 30), body)
        m.pad(body, plate, 5, name="PlatePad")
        wall = m.pad(body, m.sketch(doc, "Wall", m.polygon(slab(90, 5)), body, z=5), 10, "WallPad")
        doc.recompute()
        self.revolve(doc, body, wall, m.rectangle(10, 5, 20, 10))
        doc.recompute()
        self.consumers(doc, body)

    def revolve(self, doc, body, target, profileGeometry):
        profile = m.sketch(doc, "Profile", profileGeometry, body, placement=XZ)
        revolved = body.newObject(self.FEATURE, "Revolved")
        revolved.Profile = profile
        revolved.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        revolved.Type = "UpToFace"
        revolved.UpToFace = (target, self.names(target, self.wall()))
        self.ref("up_to_wall", revolved, "UpToFace", self.wall, ReachesFace())
        return revolved

    def consumers(self, doc, body):
        revolved = doc.Revolved
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(revolved, self.names(revolved, self.top())[0])]
        onTop.MapMode = "FlatFace"
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (revolved, self.names(revolved, self.outerArc()))
        fillet.Radius = 1
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(revolved, tuple(self.names(revolved, self.outer())))]
        body.Tip = fillet
        self.ref("sketch_top", onTop, "AttachmentSupport", self.top, Attached())
        self.ref("fillet_outer_arc", fillet, "Base", self.outerArc, Filleted(1))
        self.ref("binder_outer", binder, "Support", self.outer, Bound())


class ChamferProfile:
    """The profile's corner at (20, low) gets a chamfer 2 x 2 (a new sketch edge, so a new
    revolved face before or among the others), then the chamfer is removed again."""

    steps = ("chamfer", "unchamfer")
    low = 5

    def chamfer(self, doc):
        sketch, low = doc.Profile, self.low
        m.setLines(sketch, {0: ((10, low), (18, low)), 1: ((20, low + 2), (20, 10))})
        sketch.addGeometry(m.polyline([(18, low), (20, low + 2)]), False)

    def unchamfer(self, doc):
        sketch, low = doc.Profile, self.low
        sketch.delGeometries([4])
        m.setLines(sketch, {0: ((10, low), (20, low)), 1: ((20, low), (20, 10))})


class EarlierHole:
    """A hole (radius 2, through all) at (-20, -20) is inserted before the revolved feature: the
    base gains faces away from the revolved feature."""

    def edit(self, doc):
        body = self.bodyObject
        body.Tip = self.beforeRevolved(doc)
        sketch = m.sketch(doc, "HoleSketch", [m.circle(-20, -20, 2)], body, z=self.holeZ)
        m.pocketThroughAll(body, sketch, "Hole")
        body.Tip = doc.Fillet


class MoveWall:
    """The face the feature revolves up to turns from 90 to 120 degrees."""

    def edit(self, doc):
        setPolygon(self.wallSketch(doc), slab(120, self.wallThickness))
        self.theta = 120


class SwitchToAngle:
    """The type goes to Angle (90 degrees, so the same solid) and back to UpToFace."""

    steps = ("toAngle", "toFace")

    def toAngle(self, doc):
        doc.Revolved.Type = "Angle"
        doc.Revolved.Angle = 90

    def toFace(self, doc):
        doc.Revolved.Type = "UpToFace"


class RevolutionUpToFaceChamfer(ChamferProfile, RevolvedUpToFaceEdit):
    __doc__ = RevolvedUpToFaceEdit.__doc__ + "\n\n" + ChamferProfile.__doc__


class RevolutionUpToFaceHole(EarlierHole, RevolvedUpToFaceEdit):
    __doc__ = RevolvedUpToFaceEdit.__doc__ + "\n\n" + EarlierHole.__doc__
    holeZ = 5

    def beforeRevolved(self, doc):
        return doc.WallPad


class RevolutionUpToFaceMove(MoveWall, RevolvedUpToFaceEdit):
    __doc__ = RevolvedUpToFaceEdit.__doc__ + "\n\n" + MoveWall.__doc__
    wallThickness = 5

    def wallSketch(self, doc):
        return doc.Wall


class RevolutionUpToFaceAngle(SwitchToAngle, RevolvedUpToFaceEdit):
    __doc__ = RevolvedUpToFaceEdit.__doc__ + "\n\n" + SwitchToAngle.__doc__


class GrooveUpToFaceEdit(RevolvedUpToFaceEdit):
    """A block -30..30 x -30..30 x 0..10 with a pit through it (`slab(theta, 10)`). The groove's
    profile is the rectangle x 10..20, z 6..10, grooved up to the pit's wall: a quarter ring
    4 deep at theta = 90. References: a sketch on the groove's floor (z = 6), a fillet
    (radius 1) on its outer floor arc (radius 20, z = 6), a binder of its outer wall (radius 20),
    and the Groove's own up-to face."""

    abstract = True
    area = "GrooveUpToFace"
    FEATURE = "PartDesign::Groove"

    def top(self):
        return face("plane", normal=Z, through=(0, 0, 6), contains=ray(30, 15, 6))

    def outerArc(self):
        return edge("circle", center=(0, 0, 6), radius=20)

    def wall(self):
        a = math.radians(self.theta)
        normal = V(-math.sin(a), math.cos(a), 0)
        return face("plane", normal=normal, contains=ray(self.theta, 15, 3))

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        block = m.sketch(doc, "Block", m.rectangle(-30, -30, 30, 30), body)
        m.pad(body, block, 10, name="BlockPad")
        pitSketch = m.sketch(doc, "Pit", m.polygon(slab(90, 10)), body, z=10)
        pit = m.pocketThroughAll(body, pitSketch, "PitPocket")
        doc.recompute()
        self.revolve(doc, body, pit, m.rectangle(10, 6, 20, 10))
        doc.recompute()
        self.consumers(doc, body)


class GrooveChamferProfile(ChamferProfile):
    """The profile's outer top corner (20, 10) gets a chamfer 2 x 2, then it is removed again."""

    def chamfer(self, doc):
        m.setLines(doc.Profile, {1: ((20, 6), (20, 8)), 2: ((18, 10), (10, 10))})
        doc.Profile.addGeometry(m.polyline([(20, 8), (18, 10)]), False)

    def unchamfer(self, doc):
        doc.Profile.delGeometries([4])
        m.setLines(doc.Profile, {1: ((20, 6), (20, 10)), 2: ((20, 10), (10, 10))})


class GrooveUpToFaceChamfer(GrooveChamferProfile, GrooveUpToFaceEdit):
    __doc__ = GrooveUpToFaceEdit.__doc__ + "\n\n" + GrooveChamferProfile.__doc__


class GrooveUpToFaceHole(EarlierHole, GrooveUpToFaceEdit):
    __doc__ = GrooveUpToFaceEdit.__doc__ + "\n\n" + EarlierHole.__doc__
    holeZ = 10

    def beforeRevolved(self, doc):
        return doc.PitPocket


class GrooveUpToFaceMove(MoveWall, GrooveUpToFaceEdit):
    __doc__ = GrooveUpToFaceEdit.__doc__ + "\n\n" + MoveWall.__doc__
    wallThickness = 10

    def wallSketch(self, doc):
        return doc.Pit


class GrooveUpToFaceAngle(SwitchToAngle, GrooveUpToFaceEdit):
    __doc__ = GrooveUpToFaceEdit.__doc__ + "\n\n" + SwitchToAngle.__doc__


class RevolutionUpToFaceTwoSided(ChamferProfile, Scenario):
    """The plate of RevolvedUpToFaceEdit with its wall (`slab(90, 5)`), or a wall across it
    (x -5..0, y -30..30) when both sides go up to it. The profile x 10..20, z 5..10 is revolved
    on both sides of the XZ plane (`setSides`), with Refine off, so the two sides' top faces
    (z = 10) are separate faces; a sketch is attached to each. Then the profile's outer bottom
    corner is chamfered and the chamfer removed: each sketch stays on its own side's top
    face."""

    abstract = True
    area = "RevolutionUpToFace"
    REFS = ("sketch_top_side1", "sketch_top_side2")
    wallAcross = False

    def topSide1(self):
        return face("plane", normal=Z, through=(0, 0, 10), contains=ray(45, 15, 10))

    def topSide2(self):
        return face("plane", normal=Z, through=(0, 0, 10), contains=ray(self.side2Angle, 15, 10))

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(-30, -30, 30, 30), body)
        m.pad(body, plate, 5, name="PlatePad")
        wallGeometry = m.rectangle(-5, -30, 0, 30) if self.wallAcross else m.polygon(slab(90, 5))
        wall = m.pad(body, m.sketch(doc, "Wall", wallGeometry, body, z=5), 10, name="WallPad")
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(10, 5, 20, 10), body, placement=XZ)
        revolved = body.newObject("PartDesign::Revolution", "Revolved")
        revolved.Profile = profile
        revolved.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        revolved.Refine = False
        revolved.Type = "UpToFace"
        revolved.UpToFace = (wall, self.names(wall, wallFace(90, 10)))
        self.setSides(revolved, wall)
        doc.recompute()
        sides = (("sketch_top_side1", self.topSide1), ("sketch_top_side2", self.topSide2))
        for name, expect in sides:
            sketch = body.newObject("Sketcher::SketchObject", "On" + name)
            sketch.AttachmentSupport = [(revolved, self.names(revolved, expect())[0])]
            sketch.MapMode = "FlatFace"
            self.ref(name, sketch, "AttachmentSupport", expect, Attached())
        body.Tip = revolved


class RevolutionUpToFaceSymmetric(RevolutionUpToFaceTwoSided):
    __doc__ = (
        RevolutionUpToFaceTwoSided.__doc__
        + "\n\nSymmetric: up to the wall, and up to its mirror image on the other side."
    )
    side2Angle = -45

    def setSides(self, revolved, wall):
        revolved.SideType = "Symmetric"


class RevolutionUpToFaceUpToAndAngle(RevolutionUpToFaceTwoSided):
    __doc__ = (
        RevolutionUpToFaceTwoSided.__doc__
        + "\n\nTwo sides: side 1 up to the wall, side 2 by 45 degrees."
    )
    side2Angle = -20

    def setSides(self, revolved, wall):
        revolved.SideType = "Two sides"
        revolved.Type2 = "Angle"
        revolved.Angle2 = 45


class RevolutionUpToFaceBothUpTo(RevolutionUpToFaceTwoSided):
    __doc__ = (
        RevolutionUpToFaceTwoSided.__doc__
        + "\n\nTwo sides, the wall across the plate: each side up to the wall's face on its side "
        + "(the same face)."
    )
    side2Angle = -45
    wallAcross = True

    def setSides(self, revolved, wall):
        revolved.SideType = "Two sides"
        revolved.Type2 = "UpToFace"
        otherHalf = face("plane", normal=(1, 0, 0), contains=(0, -15, 10))
        revolved.UpToFace2 = (wall, self.names(wall, otherHalf))
