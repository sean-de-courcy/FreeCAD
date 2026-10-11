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
    BROKEN,
    Attached,
    Bound,
    Filleted,
    ReachesFace,
    Scenario,
    Settled,
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
    bottom, topZ = 5, 10  # the profile's bottom and the height of the ring's top face

    def profileGeometry(self):
        return m.rectangle(10, self.bottom, 20, 10)

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
        self.revolve(doc, body, wall, self.profileGeometry())
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
        # The chamfer line is the last geometry: chamfer() adds it after every rectangle
        sketch.delGeometries([sketch.GeometryCount - 1])
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
    bottom, topZ = 6, 6  # the floor

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
        self.revolve(doc, body, pit, self.profileGeometry())
        doc.recompute()
        self.consumers(doc, body)


class GrooveChamferProfile(ChamferProfile):
    """The profile's outer top corner (20, 10) gets a chamfer 2 x 2, then it is removed again."""

    def chamfer(self, doc):
        m.setLines(doc.Profile, {1: ((20, 6), (20, 8)), 2: ((18, 10), (10, 10))})
        doc.Profile.addGeometry(m.polyline([(20, 8), (18, 10)]), False)

    def unchamfer(self, doc):
        doc.Profile.delGeometries([doc.Profile.GeometryCount - 1])
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


class GrooveUpToDatumEdit(GrooveUpToFaceEdit):
    """The Groove of GrooveUpToFaceEdit up to the origin YZ plane instead of the pit's wall: an
    unbounded up-to face, which BRepFeat trims to the box the feature adds beside the base
    (ops#239, ops#242). References: the sketch, fillet and binder of GrooveUpToFaceEdit."""

    abstract = True
    area = "GrooveUpToDatum"
    REFS = ("sketch_top", "fillet_outer_arc", "binder_outer")

    def revolve(self, doc, body, target, profileGeometry):
        profile = m.sketch(doc, "Profile", profileGeometry, body, placement=XZ)
        revolved = body.newObject(self.FEATURE, "Revolved")
        revolved.Profile = profile
        revolved.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        revolved.Type = "UpToFace"
        revolved.UpToFace = (m.originFeature(body, "YZ_Plane"), [""])
        return revolved


class GrooveUpToDatumChamfer(GrooveChamferProfile, GrooveUpToDatumEdit):
    __doc__ = GrooveUpToDatumEdit.__doc__ + "\n\n" + GrooveChamferProfile.__doc__


class GrooveUpToDatumHole(EarlierHole, GrooveUpToDatumEdit):
    __doc__ = GrooveUpToDatumEdit.__doc__ + "\n\n" + EarlierHole.__doc__
    holeZ = 10

    def beforeRevolved(self, doc):
        return doc.PitPocket


class GrooveUpToDatumAngle(SwitchToAngle, GrooveUpToDatumEdit):
    __doc__ = GrooveUpToDatumEdit.__doc__ + "\n\n" + SwitchToAngle.__doc__


class InnerRing:
    """Multi-face: the profile also has the rectangle x 4..8 (geometry 4..7), a second ring inside
    the first. Each face of the profile is revolved up to its own face and the tools are fused
    (ops#263). More references, on the inner ring: a sketch on its top face (the floor for a
    Groove) and a binder of its outer cylinder (radius 8)."""

    INNER_REFS = ("sketch_top_inner", "binder_inner")

    def profileGeometry(self):
        return super().profileGeometry() + m.rectangle(4, self.bottom, 8, 10)

    def topInner(self):
        z = self.topZ
        return face("plane", normal=Z, through=(0, 0, z), contains=ray(30, 6, z))

    def innerOuter(self):
        return cylinder(8)

    def consumers(self, doc, body):
        super().consumers(doc, body)
        revolved = doc.Revolved
        onTop = body.newObject("Sketcher::SketchObject", "OnTopInner")
        onTop.AttachmentSupport = [(revolved, self.names(revolved, self.topInner())[0])]
        onTop.MapMode = "FlatFace"
        binder = doc.addObject("PartDesign::SubShapeBinder", "BinderInner")
        binder.Support = [(revolved, tuple(self.names(revolved, self.innerOuter())))]
        self.ref("sketch_top_inner", onTop, "AttachmentSupport", self.topInner, Attached())
        self.ref("binder_inner", binder, "Support", self.innerOuter, Bound())


class RevolutionTwoRingsUpToFaceChamfer(InnerRing, RevolutionUpToFaceChamfer):
    __doc__ = RevolutionUpToFaceChamfer.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = RevolutionUpToFaceChamfer.REFS + InnerRing.INNER_REFS


class RevolutionTwoRingsUpToFaceHole(InnerRing, RevolutionUpToFaceHole):
    __doc__ = RevolutionUpToFaceHole.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = RevolutionUpToFaceHole.REFS + InnerRing.INNER_REFS


class RevolutionTwoRingsUpToFaceMove(InnerRing, RevolutionUpToFaceMove):
    __doc__ = RevolutionUpToFaceMove.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = RevolutionUpToFaceMove.REFS + InnerRing.INNER_REFS


class RevolutionTwoRingsUpToFaceAngle(InnerRing, RevolutionUpToFaceAngle):
    __doc__ = RevolutionUpToFaceAngle.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = RevolutionUpToFaceAngle.REFS + InnerRing.INNER_REFS


class GrooveTwoRingsUpToFaceChamfer(InnerRing, GrooveUpToFaceChamfer):
    __doc__ = GrooveUpToFaceChamfer.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = GrooveUpToFaceChamfer.REFS + InnerRing.INNER_REFS


class GrooveTwoRingsUpToFaceHole(InnerRing, GrooveUpToFaceHole):
    __doc__ = GrooveUpToFaceHole.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = GrooveUpToFaceHole.REFS + InnerRing.INNER_REFS


class GrooveTwoRingsUpToFaceMove(InnerRing, GrooveUpToFaceMove):
    __doc__ = GrooveUpToFaceMove.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = GrooveUpToFaceMove.REFS + InnerRing.INNER_REFS


class GrooveTwoRingsUpToFaceAngle(InnerRing, GrooveUpToFaceAngle):
    __doc__ = GrooveUpToFaceAngle.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = GrooveUpToFaceAngle.REFS + InnerRing.INNER_REFS


class GrooveTwoRingsUpToDatumChamfer(InnerRing, GrooveUpToDatumChamfer):
    __doc__ = GrooveUpToDatumChamfer.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = GrooveUpToDatumChamfer.REFS + InnerRing.INNER_REFS


class GrooveTwoRingsUpToDatumHole(InnerRing, GrooveUpToDatumHole):
    __doc__ = GrooveUpToDatumHole.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = GrooveUpToDatumHole.REFS + InnerRing.INNER_REFS


class GrooveTwoRingsUpToDatumAngle(InnerRing, GrooveUpToDatumAngle):
    __doc__ = GrooveUpToDatumAngle.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = GrooveUpToDatumAngle.REFS + InnerRing.INNER_REFS


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
    bottom, topZ = 5, 10

    def profileGeometry(self):
        return m.rectangle(10, self.bottom, 20, 10)

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
        profile = m.sketch(doc, "Profile", self.profileGeometry(), body, placement=XZ)
        revolved = body.newObject("PartDesign::Revolution", "Revolved")
        revolved.Profile = profile
        revolved.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        revolved.Refine = False
        revolved.Type = "UpToFace"
        revolved.UpToFace = (wall, self.names(wall, wallFace(90, 10)))
        self.setSides(revolved, wall)
        doc.recompute()
        self.consumers(doc, body)
        body.Tip = revolved

    def consumers(self, doc, body):
        revolved = doc.Revolved
        sides = (("sketch_top_side1", self.topSide1), ("sketch_top_side2", self.topSide2))
        for name, expect in sides:
            sketch = body.newObject("Sketcher::SketchObject", "On" + name)
            sketch.AttachmentSupport = [(revolved, self.names(revolved, expect())[0])]
            sketch.MapMode = "FlatFace"
            self.ref(name, sketch, "AttachmentSupport", expect, Attached())


class RevolutionUpToFaceSymmetric(RevolutionUpToFaceTwoSided):
    __doc__ = (
        RevolutionUpToFaceTwoSided.__doc__
        + "\n\nSymmetric: up to the wall, and up to its mirror image on the other side."
    )
    side2Angle = -45

    def setSides(self, revolved, wall):
        revolved.SideType = "Symmetric"


class RevolutionUpToFaceSymmetricAcross(RevolutionUpToFaceTwoSided):
    __doc__ = (
        RevolutionUpToFaceTwoSided.__doc__
        + "\n\nSymmetric, the wall across the plate: its face mirrors onto itself, and the second "
        + "side ends on the same face (ops#254: it was revolved the long way round)."
    )
    side2Angle = -45
    wallAcross = True

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


class RevolutionTwoRingsUpToFaceSymmetric(InnerRing, RevolutionUpToFaceSymmetric):
    __doc__ = RevolutionUpToFaceSymmetric.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = RevolutionUpToFaceSymmetric.REFS + InnerRing.INNER_REFS


class RevolutionTwoRingsUpToFaceSymmetricAcross(InnerRing, RevolutionUpToFaceSymmetricAcross):
    __doc__ = RevolutionUpToFaceSymmetricAcross.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = RevolutionUpToFaceSymmetricAcross.REFS + InnerRing.INNER_REFS


class RevolutionTwoRingsUpToFaceUpToAndAngle(InnerRing, RevolutionUpToFaceUpToAndAngle):
    __doc__ = RevolutionUpToFaceUpToAndAngle.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = RevolutionUpToFaceUpToAndAngle.REFS + InnerRing.INNER_REFS


class RevolutionTwoRingsUpToFaceBothUpTo(InnerRing, RevolutionUpToFaceBothUpTo):
    __doc__ = RevolutionUpToFaceBothUpTo.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = RevolutionUpToFaceBothUpTo.REFS + InnerRing.INNER_REFS


class RevolutionSideOneToFaceFillet(Scenario):
    """PR 243 round 3 (ops#255): the plate of RevolvedUpToFaceEdit with its wall (`slab(90, 5)`),
    and the profile x 10..20, z 5..10 revolved Two sides by angle, 60 and 60 degrees, with Refine
    off; a fillet (radius 1) on the top edge of side 1's end face (at 60 degrees, z = 10). Side 1
    is then revolved up to the wall's face instead: its end face lies on the wall, and the edge
    is gone. Side 2's end face at -60 degrees is its twin, named from the profile's second-side
    copy (CPY on the profile's names inside its own): the name matcher took its edge, and the
    solver resolved it at tier 1 ("names"), silently. The fillet breaks."""

    area = "RevolutionUpToFace"
    MULTI = True
    REFS = ("fillet_end_top",)
    upTo = False

    endAngle = 60  # the end face the fillet is on
    endGone = True  # after the edit

    def endTop(self):
        if self.upTo and self.endGone:
            return BROKEN
        return edge("line", contains=ray(self.endAngle, 15, 10))

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(-30, -30, 30, 30), body)
        m.pad(body, plate, 5, name="PlatePad")
        wallSketch = m.sketch(doc, "Wall", m.polygon(slab(90, 5)), body, z=5)
        self.wall = m.pad(body, wallSketch, 10, "WallPad")
        profile = m.sketch(doc, "Profile", m.rectangle(10, 5, 20, 10), body, placement=XZ)
        revolved = body.newObject("PartDesign::Revolution", "Revolved")
        revolved.Profile = profile
        revolved.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        revolved.Refine = False
        revolved.SideType = "Two sides"
        revolved.Type = "Angle"
        revolved.Angle = 60
        revolved.Type2 = "Angle"
        revolved.Angle2 = 60
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (revolved, self.names(revolved, self.endTop()))
        fillet.Radius = 1
        self.ref("fillet_end_top", fillet, "Base", self.endTop, Filleted(1))

    def edit(self, doc):
        revolved = doc.Revolved
        revolved.Type = "UpToFace"
        revolved.UpToFace = (self.wall, self.names(self.wall, wallFace(90, 10)))
        self.upTo = True



class RevolutionSideTwoEndAfterSideOneToFace(RevolutionSideOneToFaceFillet):
    """PR 243 round 4 (verification F3): the Revolution of RevolutionSideOneToFaceFillet, Two
    sides by angle, is one solid; the fillet is on the top edge of side 2's end face (at -60
    degrees, z = 10) instead. That face is the solid's start face, the turned profile. Side 1
    going up to the wall builds the sides apart, side 2 marked as a copy, and the profile's names
    were on the seam at 0 degrees: with them the fillet moved there. In V2 the seam, side 1's start
    face, is marked (CPY;1, PR 243 round 5), so the name is on no element of the two sides, and
    the geometric search finds the edge where it was: the fillet stays on side 2's end edge.
    The solver (V2s) has a structural candidate from the same sketch line whose geometry
    disagrees, so it breaks the reference, loudly, instead of searching by geometry. V1 keeps
    upstream's names."""

    REFS = ("fillet_end_top",)
    endAngle = -60
    endGone = False

    def endTop(self):
        if self.upTo and self.solver:
            return BROKEN
        expected = super().endTop()
        # Held plainly in V2 without the solver: a warned guess doesn't pass (verification 6, L2)
        return Settled(expected) if self.upTo and self.mode == "V2" else expected


class RevolutionSideTwoOuterEdgeAfterSideOneToFace(RevolutionSideTwoEndAfterSideOneToFace):
    """PR 243 round 6 (Fable review 5, M1), a guard for the connected elements' path: the
    Revolution of RevolutionSideTwoEndAfterSideOneToFace, the fillet on the outer edge of side 2's
    end face (the start face, at -60 degrees, radius 20, z 5..10). After side 1 goes up to the
    wall, the wall's bottom edge (x = 0, y 20..30, z = 5) lists the outer face (the profile's
    outer line, GEN) among its connected elements, so the old name is in its ancestry; tier 2
    drops it (it runs along Y, the old edge along Z), and side 1's far outer edge holds the
    name through PRJ only. The solver breaks the reference; V2 finds the edge where it was."""

    def endTop(self):
        if self.upTo and self.solver:
            return BROKEN
        expected = edge("line", contains=ray(self.endAngle, 20, 7.5))
        return Settled(expected) if self.upTo and self.mode == "V2" else expected


class RevolutionStartFaceOfOneSideToSymmetric(Scenario):
    """PR 243 round 5 (verification 4, finding 1): the profile x 10..20, z 5..10 revolved about
    the Z axis, One side, 60 degrees, Refine off; a fillet (radius 1) on the top edge of the
    start face (the profile, at 0 degrees, z = 10). The Revolution goes Symmetric by angle (one
    solid from -30 to 30 degrees), then Two sides, 30 and 30 (one solid, the same): its start
    face is the turned profile in each, with the profile's names, and the fillet follows to the
    top edge at -30 degrees. Round 4 marked the single solid's start face, and the reference
    broke; round 5 marks the seam of two sides built apart instead."""

    area = "RevolutionUpToFace"
    MULTI = True
    REFS = ("start_top",)
    steps = ("symmetric", "twoSides")
    startAngle = 0
    bottom, topZ = 5, 10

    def profileGeometry(self):
        return m.rectangle(10, self.bottom, 20, 10)

    def startTop(self):
        return edge("line", contains=ray(self.startAngle, 15, 10))

    def followedStartTop(self):
        """The edge, held plainly in V2: a warned guess doesn't pass (verification 5, L3)."""
        expected = self.startTop()
        return Settled(expected) if self.mode == "V2" else expected

    def revolve(self, doc, **properties):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.profileGeometry(), body, placement=XZ)
        revolved = body.newObject("PartDesign::Revolution", "Revolved")
        revolved.Profile = profile
        revolved.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        revolved.Refine = False
        revolved.Type = "Angle"
        for name, value in properties.items():
            setattr(revolved, name, value)
        doc.recompute()
        self.consumers(doc, body)

    def consumers(self, doc, body):
        revolved = doc.Revolved
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (revolved, self.names(revolved, self.startTop()))
        fillet.Radius = 1
        self.ref("start_top", fillet, "Base", self.followedStartTop, Filleted(1))

    def build(self, doc):
        self.revolve(doc, Angle=60)

    def symmetric(self, doc):
        doc.Revolved.SideType = "Symmetric"
        self.startAngle = -30

    def twoSides(self, doc):
        revolved = doc.Revolved
        revolved.SideType = "Two sides"
        revolved.Angle = 30
        revolved.Type2 = "Angle"
        revolved.Angle2 = 30


class RevolutionStartFaceOfSymmetricAngleEdit(RevolutionStartFaceOfOneSideToSymmetric):
    """PR 243 round 5 (verification 4, L6): an angle edit within the single-solid build. The
    profile of RevolutionStartFaceOfOneSideToSymmetric revolved Symmetric by angle, 60 degrees
    (one solid from -30 to 30); the fillet on the start face's top edge (at -30 degrees). The
    angle goes to 80 (start face at -40), then the Revolution goes Two sides, 40 and 50 (start
    face, side 2's end, at -50): the fillet follows the start face's top edge."""

    steps = ("wider", "twoSides")
    startAngle = -30

    def build(self, doc):
        self.revolve(doc, SideType="Symmetric", Angle=60)

    def wider(self, doc):
        doc.Revolved.Angle = 80
        self.startAngle = -40

    def twoSides(self, doc):
        revolved = doc.Revolved
        revolved.SideType = "Two sides"
        revolved.Angle = 40
        revolved.Type2 = "Angle"
        revolved.Angle2 = 50
        self.startAngle = -50


class RevolutionTwoRingsStartFaceOfOneSideToSymmetric(
    InnerRing, RevolutionStartFaceOfOneSideToSymmetric
):
    __doc__ = RevolutionStartFaceOfOneSideToSymmetric.__doc__ + "\n\n" + InnerRing.__doc__
    REFS = RevolutionStartFaceOfOneSideToSymmetric.REFS + InnerRing.INNER_REFS
