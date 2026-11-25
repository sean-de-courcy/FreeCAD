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

"""The corpus's PartDesign models beyond B1's core (FreeCAD-CH ops#323 PR B2,
notes/beta-compatibility.md 3.6, "B2"). Same conventions as `models.py`: each builder takes
`make(stem)` and returns the stated volumes."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Compat.models import (
    TOP,
    V,
    attachedSketch,
    edgeWhere,
    faceWhere,
    lineThrough,
    plane,
    planeFacing,
    vertexAt,
)
from PartDesignTests.Scenarios import models as m


def newBody(doc, name):
    return doc.addObject("PartDesign::Body", name)


def block(body, x0, y0, x1, y1, height, name="Pad"):
    """A rectangle on the Body's XY plane, padded `height`."""
    sketch = attachedSketch(
        body, name + "Sketch", plane(body, "XY_Plane"), m.rectangle(x0, y0, x1, y1)
    )
    return m.pad(body, sketch, height, name)


def frustum(a, b, h):
    """The volume of a square frustum, sides a and b, height h."""
    return h / 3 * (a * a + a * b + b * b)


def RevolutionGroove(make):
    """Revolution and Groove: whole, symmetric and two-sided.

    Body: a rectangle x 0..10, z 0..20 on the XZ plane revolved 360 degrees about its vertical
    axis (the Z axis): a cylinder, radius 10, height 20; a groove of x 6..10, z 8..12 about the
    same axis, symmetric, 90 degrees in all (a quarter of a ring, radii 6..10, 4 high).
    Body001: a rectangle x 5..10, z 0..4 revolved two-sided, 30 and 60 degrees (a quarter ring,
    radii 5..10); a groove of x 8..10, z 1..3, two-sided, 10 and 15 degrees (25 degrees of a
    ring, radii 8..10, 2 high), inside the revolution's span."""
    doc = make("RevolutionGroove")
    body = newBody(doc, "Body")
    profile = attachedSketch(body, "Sketch", plane(body, "XZ_Plane"), m.rectangle(0, 0, 10, 20))
    revolution = body.newObject("PartDesign::Revolution", "Revolution")
    revolution.Profile = profile
    revolution.ReferenceAxis = (profile, ["V_Axis"])
    revolution.Angle = 360
    grooveSketch = attachedSketch(
        body, "GrooveSketch", plane(body, "XZ_Plane"), m.rectangle(6, 8, 10, 12)
    )
    groove = body.newObject("PartDesign::Groove", "Groove")
    groove.Profile = grooveSketch
    groove.ReferenceAxis = (grooveSketch, ["V_Axis"])
    groove.SideType = "Symmetric"
    groove.Angle = 90
    body2 = newBody(doc, "Body001")
    profile2 = attachedSketch(
        body2, "Sketch001", plane(body2, "XZ_Plane"), m.rectangle(5, 0, 10, 4)
    )
    revolution2 = body2.newObject("PartDesign::Revolution", "Revolution001")
    revolution2.Profile = profile2
    revolution2.ReferenceAxis = (profile2, ["V_Axis"])
    revolution2.SideType = "Two sides"
    revolution2.Angle = 30
    revolution2.Angle2 = 60
    grooveSketch2 = attachedSketch(
        body2, "GrooveSketch001", plane(body2, "XZ_Plane"), m.rectangle(8, 1, 10, 3)
    )
    groove2 = body2.newObject("PartDesign::Groove", "Groove001")
    groove2.Profile = grooveSketch2
    groove2.ReferenceAxis = (grooveSketch2, ["V_Axis"])
    groove2.SideType = "Two sides"
    groove2.Angle = 10
    groove2.Angle2 = 15
    doc.recompute()
    return {
        "volumes": {
            "Revolution": math.pi * 100 * 20,
            "Groove": math.pi * 100 * 20 - math.pi * (100 - 36) * 4 / 4,
            "Groove001": math.pi * (100 - 25) * 4 / 4 - math.pi * (100 - 64) * 2 * 25 / 360,
        }
    }


def SidedVariants(make):
    """Pad symmetric to its plane and Pocket two-sided (B1's PadPocket has the other two).

    A rectangle 0..30 x 0..20 on the XY plane padded 10 symmetric (z -5..5); a circle, radius
    3, at (8, 10) on the XY plane pocketed two-sided, 2 one way and 4 the other (6 in all,
    inside the block)."""
    doc = make("SidedVariants")
    body = newBody(doc, "Body")
    sketch = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 30, 20))
    pad = m.pad(body, sketch, 10)
    pad.SideType = "Symmetric"
    holeSketch = attachedSketch(body, "HoleSketch", plane(body, "XY_Plane"), [m.circle(8, 10, 3)])
    pocket = m.pocket(body, holeSketch, 2)
    pocket.SideType = "Two sides"
    pocket.Length2 = 4
    doc.recompute()
    return {"volumes": {"Pad": 6000, "Pocket": 6000 - math.pi * 9 * 6}}


def DraftThickness(make):
    """Draft and Thickness.

    Body: a 20 x 20 x 10 block (0..20) with a 5 degree draft on its four sides, neutral plane
    its bottom face, leaning inward going up: a square frustum, sides 20 and 20 - 20 tan 5.
    Body001: a 20 x 20 x 10 block (x 30..50), its top face removed and the rest thickened 1
    towards the inside, joined by intersection: a box open at the top, walls and floor 1."""
    doc = make("DraftThickness")
    body = newBody(doc, "Body")
    pad = block(body, 0, 0, 20, 20, 10)
    doc.recompute()
    sides = [
        faceWhere(pad.Shape, planeFacing(n, p))
        for n, p in (
            (V(1, 0, 0), V(20, 0, 0)),
            (V(-1, 0, 0), V(0, 0, 0)),
            (V(0, 1, 0), V(0, 20, 0)),
            (V(0, -1, 0), V(0, 0, 0)),
        )
    ]
    draft = body.newObject("PartDesign::Draft", "Draft")
    draft.Base = (pad, sides)
    draft.NeutralPlane = (pad, [faceWhere(pad.Shape, planeFacing(V(0, 0, -1), V(0, 0, 0)))])
    draft.Angle = 5
    body2 = newBody(doc, "Body001")
    pad2 = block(body2, 30, 0, 50, 20, 10, "Pad001")
    doc.recompute()
    thickness = body2.newObject("PartDesign::Thickness", "Thickness")
    thickness.Base = (pad2, [faceWhere(pad2.Shape, planeFacing(TOP, V(0, 0, 10)))])
    thickness.Value = 1
    thickness.Reversed = True
    thickness.Join = "Intersection"
    doc.recompute()
    return {
        "volumes": {
            "Draft": frustum(20, 20 - 20 * math.tan(math.radians(5)), 10),
            "Thickness": 4000 - 18 * 18 * 9,
        }
    }


def MirroredMultiTransform(make):
    """Mirrored and MultiTransform.

    A 40 x 20 x 10 block (x -20..20, y 0..20); a boss, radius 3, 5 high, at (-12, 10) on its
    top face, mirrored in the YZ plane (a second boss at (12, 10)); a hole, radius 2, 3 deep, at
    (-15, 4) on the top face, transformed by a MultiTransform: mirrored in the YZ plane, then a
    linear pattern along the Y axis, 12 long, 2 occurrences (holes at x +-15, y 4 and 16)."""
    doc = make("MirroredMultiTransform")
    body = newBody(doc, "Body")
    pad = block(body, -20, 0, 20, 20, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    boss = m.pad(
        body, attachedSketch(body, "BossSketch", (pad, top), [m.circle(-12, 10, 3)]), 5, "Boss"
    )
    mirrored = body.newObject("PartDesign::Mirrored", "Mirrored")
    mirrored.Originals = [boss]
    mirrored.MirrorPlane = (plane(body, "YZ_Plane"), [""])
    body.Tip = mirrored  # newObject leaves the Tip (the roll-back bar, ops#127) before a pattern
    doc.recompute()
    hole = m.pocket(
        body, attachedSketch(body, "HoleSketch", (pad, top), [m.circle(-15, 4, 2)]), 3, "Hole"
    )
    doc.recompute()
    multi = body.newObject("PartDesign::MultiTransform", "MultiTransform")
    multi.Originals = [hole]
    step1 = body.newObject("PartDesign::Mirrored", "MultiMirrored")
    step1.MirrorPlane = (plane(body, "YZ_Plane"), [""])
    step2 = body.newObject("PartDesign::LinearPattern", "MultiLinear")
    step2.Direction = (plane(body, "Y_Axis"), [""])
    step2.Length = 12
    step2.Occurrences = 2
    multi.Transformations = [step1, step2]
    body.Tip = multi
    doc.recompute()
    bosses = 2 * math.pi * 9 * 5
    return {
        "volumes": {
            "Mirrored": 8000 + bosses,
            "MultiTransform": 8000 + bosses - 4 * math.pi * 4 * 3,
        }
    }


def LoftPipe(make):
    """Loft and Pipe.

    Body: a ruled loft from a square, side 20, on the XY plane (centred) to a square, side 10,
    10 up (a frustum); an additive pipe of a circle, radius 2, on the loft's top face at its
    centre, along a quarter circle, radius 10, from (0, 0, 10) up and over to (10, 0, 20) in
    the XZ plane (a quarter torus: Pappus, area times path). Body001: a smooth (BSpline) loft
    through a circle, radius 5, a square, side 8, 10 up, and a circle, radius 3, 20 up; its
    volume is integrated numerically, so it isn't stated: the gate's records pin it, and its
    drift calibrates the BSpline tolerance (3.2). Body002 (ops#376 F2): a square, side 4, centred
    on (40, 0) on the XY plane, piped along an L, up from (40, 0, 0) to (40, 0, 10), then along
    +X to (50, 0, 10), Right corner; a fillet, radius 1, on a start edge (y = -2, z = 0), and a
    datum point at the centre of the first leg's side face x = 38, so the naming migration's
    rehearsal covers references to a Pipe's start and first-leg elements."""
    doc = make("LoftPipe")
    body = newBody(doc, "Body")
    xy = plane(body, "XY_Plane")
    bottom = attachedSketch(body, "Bottom", xy, m.rectangle(-10, -10, 10, 10))
    top = attachedSketch(body, "Top", xy, m.rectangle(-5, -5, 5, 5))
    top.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
    loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
    loft.Profile = bottom
    loft.Sections = [top]
    loft.Ruled = True
    doc.recompute()
    capFace = faceWhere(loft.Shape, planeFacing(TOP, V(0, 0, 10)))
    profile = attachedSketch(body, "PipeProfile", (loft, capFace), [m.circle(0, 0, 2)])
    spine = attachedSketch(body, "Spine", plane(body, "XZ_Plane"), [])
    spine.AttachmentOffset = App.Placement(V(0, 10, 0), App.Rotation())
    # in the XZ plane's sketch, x is X and y is Z: the arc centred on (10, 10) from 180 to 90
    # degrees runs from (0, 10) to (10, 20)
    spine.addGeometry(
        Part.ArcOfCircle(Part.Circle(V(10, 0, 0), V(0, 0, 1), 10), math.pi / 2, math.pi), False
    )
    pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
    pipe.Profile = profile
    pipe.Spine = spine
    pipe.Transition = "Transformed"  # the default before ops#370 (the spine is smooth)
    body2 = newBody(doc, "Body001")
    xy2 = plane(body2, "XY_Plane")
    sections = []
    for i, (geometry, z) in enumerate(
        ((m.circle(0, 0, 5), 0), (m.rectangle(-4, -4, 4, 4), 10), (m.circle(0, 0, 3), 20))
    ):
        section = attachedSketch(
            body2, f"Section{i}", xy2, geometry if isinstance(geometry, list) else [geometry]
        )
        section.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
        sections.append(section)
    smooth = body2.newObject("PartDesign::AdditiveLoft", "SmoothLoft")
    smooth.Profile = sections[0]
    smooth.Sections = sections[1:]
    body3 = newBody(doc, "Body002")
    square = attachedSketch(
        body3, "SquareProfile", plane(body3, "XY_Plane"), m.rectangle(38, -2, 42, 2)
    )
    # in the XZ plane's sketch, x is X and y is Z
    path = attachedSketch(
        body3, "LPath", plane(body3, "XZ_Plane"), m.polyline([(40, 0), (40, 10), (50, 10)])
    )
    lPipe = body3.newObject("PartDesign::AdditivePipe", "LPipe")
    lPipe.Profile = square
    lPipe.Spine = path
    lPipe.Transition = "Right corner"
    doc.recompute()
    fillet = body3.newObject("PartDesign::Fillet", "StartEdgeFillet")
    fillet.Base = (lPipe, [edgeWhere(lPipe.Shape, lineThrough((38, -2, 0), (42, -2, 0)))])
    fillet.Radius = 1
    point = body3.newObject("PartDesign::Point", "SidePoint")
    point.AttachmentSupport = [
        (lPipe, faceWhere(lPipe.Shape, planeFacing(V(-1, 0, 0), V(38, 0, 0))))
    ]
    point.MapMode = "CenterOfMass"
    body3.Tip = fillet
    doc.recompute()
    loftVolume = frustum(20, 10, 10)
    return {
        "volumes": {
            "Loft": loftVolume,
            "Pipe": loftVolume + math.pi * 4 * (math.pi * 10 / 2),
        }
    }


def PipeCorners(make):
    """A Pipe's spine corners (ops#370).

    Body: a square, side 4, centred on the XY plane, swept with "Transformed" along an L on the
    XZ plane: up 30, then 20 turned 120 degrees from +Z towards +X. "Transformed" doesn't turn
    the profile at the corner, so the second leg, past 90 degrees, runs back under the corner:
    the pipe is the union of the square's extrusions along the two legs, 4 * 4 * 30 and
    4 * 4 * 20 * |cos 120|, less their overlap below the corner, a wedge 4 deep with the
    triangle of legs 4 and 4 / tan 60 (32 / sqrt 3). Body001: the same square along an L with a
    right angle (up 30, then 20 along +X), its Transition as a new pipe has it ("Right corner"):
    4 * 4 * 50."""
    doc = make("PipeCorners")
    turned = math.radians(120)
    for name, end, transition in (
        ("Body", (20 * math.sin(turned), 30 + 20 * math.cos(turned)), "Transformed"),
        ("Body001", (20, 30), None),
    ):
        body = newBody(doc, name)
        profile = attachedSketch(
            body, "Profile" + name[4:], plane(body, "XY_Plane"), m.rectangle(-2, -2, 2, 2)
        )
        # in the XZ plane's sketch, x is X and y is Z
        spine = attachedSketch(
            body, "Spine" + name[4:], plane(body, "XZ_Plane"), m.polyline([(0, 0), (0, 30), end])
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe" + name[4:])
        pipe.Profile = profile
        pipe.Spine = spine
        if transition:
            pipe.Transition = transition
    doc.recompute()
    return {"volumes": {"Pipe": 480 + 160 - 32 / math.sqrt(3), "Pipe001": 800}}


def HoleFeature(make):
    """A Hole: counterbored, with an angled drill point.

    A 20 x 20 x 10 block (0..20); a sketch on its top face with a circle at (10, 10); a Hole,
    diameter 6, depth 8 from the top face, counterbore diameter 10, 2 deep, drill point
    angled 118 degrees (a cone below the 8 mm, its height 3 / tan 59)."""
    doc = make("HoleFeature")
    body = newBody(doc, "Body")
    pad = block(body, 0, 0, 20, 20, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    sketch = attachedSketch(body, "HoleSketch", (pad, top), [m.circle(10, 10, 1)])
    hole = body.newObject("PartDesign::Hole", "Hole")
    hole.Profile = sketch
    # Set as the Hole panel does: a Hole's thread fields take their ThreadType's values only when
    # ThreadType is set, and a restore sets it (CosmeticThread, ThreadFit), so a Hole left with
    # its constructor's values would reopen different.
    hole.ThreadType = "None"
    hole.Diameter = 6
    hole.DepthType = "Dimension"
    hole.Depth = 8
    hole.HoleCutType = "Counterbore"
    hole.HoleCutDiameter = 10
    hole.HoleCutDepth = 2
    hole.DrillPoint = "Angled"
    hole.DrillPointAngle = 118
    doc.recompute()
    cone = math.pi * 9 * (3 / math.tan(math.radians(59))) / 3
    return {"volumes": {"Hole": 4000 - math.pi * 25 * 2 - math.pi * 9 * 6 - cone}}


def UpToFace(make):
    """Pad, Pocket and Revolution up to a face, each in its plain case (one planar face, met
    directly; ops#296/#299/#304's edge cases are not modelled).

    Body: a 40 x 20 x 10 block (0..40) and a wall x 30..40 on its top, 15 more (to z 25); a
    square x 5..15, y 5..15 on the block's top face padded up to the wall's top face (to z 25);
    a circle, radius 2, at (35, 10) on the wall's top face pocketed up to the block's top face
    (15 deep). Body001: a datum plane on the YZ plane; a rectangle x 4..8, z 0..4 on the XZ
    plane revolved about the Z axis up to the datum plane (a quarter of a ring, radii 4..8).
    Body002 (ops#360): a SubShapeBinder of a Part feature's B-spline plate x -10..20, y 25..45 at
    z = 10 (not elementary, so the prism is built by the split); a block x -1..9, y 29..34, 2 high;
    two rectangles on its top, A x 0..2, y 30..32 and B x 5..8, y 30..33, padded up to the
    binder's face; a datum point at the centre of A's far cap. Each far cap is the projection of
    its own profile face."""
    doc = make("UpToFace")
    body = newBody(doc, "Body")
    pad = block(body, 0, 0, 40, 20, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    wall = m.pad(
        body, attachedSketch(body, "WallSketch", (pad, top), m.rectangle(30, 0, 40, 20)), 15, "Wall"
    )
    doc.recompute()
    wallTop = faceWhere(wall.Shape, planeFacing(TOP, V(0, 0, 25)))
    blockTop = faceWhere(wall.Shape, planeFacing(TOP, V(0, 0, 10)))
    post = body.newObject("PartDesign::Pad", "Post")
    post.Profile = attachedSketch(body, "PostSketch", (wall, blockTop), m.rectangle(5, 5, 15, 15))
    post.Type = "UpToFace"
    post.UpToFace = (wall, [wallTop])
    doc.recompute()
    wallTop2 = faceWhere(
        post.Shape,
        lambda f: planeFacing(TOP, V(0, 0, 25))(f)
        and (f.CenterOfMass - V(35, 10, 25)).Length < 1e-6,
    )
    blockTop2 = faceWhere(post.Shape, planeFacing(TOP, V(0, 0, 10)))
    pocket = body.newObject("PartDesign::Pocket", "Pocket")
    pocket.Profile = attachedSketch(body, "PocketSketch", (post, wallTop2), [m.circle(35, 10, 2)])
    pocket.Type = "UpToFace"
    pocket.UpToFace = (post, [blockTop2])
    body2 = newBody(doc, "Body001")
    datum = body2.newObject("PartDesign::Plane", "DatumPlane")
    datum.AttachmentSupport = [(plane(body2, "YZ_Plane"), "")]
    datum.MapMode = "FlatFace"
    profile = attachedSketch(body2, "Sketch001", plane(body2, "XZ_Plane"), m.rectangle(4, 0, 8, 4))
    revolution = body2.newObject("PartDesign::Revolution", "Revolution")
    revolution.Profile = profile
    revolution.ReferenceAxis = (profile, ["V_Axis"])
    revolution.Type = "UpToFace"
    revolution.UpToFace = (datum, [""])
    corners = [V(-10, 25, 10), V(20, 25, 10), V(20, 45, 10), V(-10, 45, 10)]
    plate = doc.addObject("Part::Feature", "FreeformPlate")
    plate.Shape = Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]
    body3 = newBody(doc, "Body002")
    plateBinder = body3.newObject("PartDesign::SubShapeBinder", "PlateBinder")
    plateBinder.Support = [(plate, ("Face1",))]
    splitBase = block(body3, -1, 29, 9, 34, 2, "SplitBase")
    doc.recompute()
    baseTop = faceWhere(splitBase.Shape, planeFacing(TOP, V(0, 0, 2)))
    rectangles = m.rectangle(0, 30, 2, 32) + m.rectangle(5, 30, 8, 33)
    splitPad = body3.newObject("PartDesign::Pad", "SplitPad")
    splitPad.Profile = attachedSketch(body3, "SplitPadSketch", (splitBase, baseTop), rectangles)
    splitPad.Type = "UpToFace"
    splitPad.UpToFace = (plateBinder, ["Face1"])
    doc.recompute()
    capA = faceWhere(
        splitPad.Shape,
        lambda f: abs(f.BoundBox.ZMin - 10) < 1e-6
        and abs(f.BoundBox.ZMax - 10) < 1e-6
        and f.isInside(V(1, 31, 10), 1e-6, True),
    )
    point = body3.newObject("PartDesign::Point", "CapPoint")
    point.AttachmentSupport = [(splitPad, capA)]
    point.MapMode = "CenterOfMass"
    body3.Tip = splitPad
    doc.recompute()
    walls = 8000 + 10 * 20 * 15
    return {
        "volumes": {
            "Post": walls + 10 * 10 * 15,
            "Pocket": walls + 10 * 10 * 15 - math.pi * 4 * 15,
            "Revolution": math.pi * (64 - 16) * 4 / 4,
            "SplitPad": 10 * 5 * 2 + (4 + 9) * 8,
        }
    }


def lobedHoleShell(z, lobes):
    """A shell of two B-spline faces at height z: the rectangle x -10..20, y -10..10 with a hole
    of `lobes` lobes about (3, 3) (radius 2 + 0.8 cos(lobes t), one closed B-spline edge), and the
    hole's fill (as TestPad's lobedHoleShell)."""
    points = []
    for k in range(60):
        t = 2 * math.pi * k / 60
        r = 2 + 0.8 * math.cos(lobes * t)
        points.append(V(3 + r * math.cos(t), 3 + r * math.sin(t), z))
    curve = Part.BSplineCurve()
    curve.interpolate(points, PeriodicFlag=True)
    edge = curve.toShape()
    outer = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
    plate = Part.Face(
        Part.Plane(V(0, 0, z), TOP), [Part.makePolygon(outer + outer[:1]), Part.Wire([edge])]
    )
    fill = Part.Face(Part.Wire([edge]))
    return Part.Shell([plate.toNurbs().Faces[0], fill.toNurbs().Faces[0]])


def UpToTwins(make):
    """A Pad up to a shell whose far cap is split into identical twins, with a datum on one twin
    (PLAN decision 121 (3), ops#422/ops#423: what a twin reference computes at the beta).

    A Part feature's shell at z = 10: a plate x -10..20, y -10..10 with a four-lobed hole about
    (3, 3) (radius 2 + 0.8 cos 4t: tips 2.8 on the axes, valleys 1.2 on the diagonals) and the
    hole's fill, both B-spline faces. Body: a SubShapeBinder of both faces; a disc, radius 2.3,
    at (3, 3) on the XY plane padded up to the binder's faces (UpToShape). The disc crosses the
    hole between the tips, so the far cap is five pieces: one on the fill and four twins on the
    plate, one in each valley. A datum point at the centre of the twin in the valley at 45
    degrees."""
    doc = make("UpToTwins")
    shell = doc.addObject("Part::Feature", "LobedShell")
    shell.Shape = lobedHoleShell(10, 4)
    body = newBody(doc, "Body")
    binder = body.newObject("PartDesign::SubShapeBinder", "ShellBinder")
    binder.Support = [(shell, ("Face1", "Face2"))]
    pad = body.newObject("PartDesign::Pad", "TwinPad")
    pad.Profile = attachedSketch(body, "DiscSketch", plane(body, "XY_Plane"), [m.circle(3, 3, 2.3)])
    pad.Type = "UpToShape"
    pad.UpToShape = (binder, ["Face1", "Face2"])
    pad.Refine = False
    doc.recompute()

    def farCap(f):
        return abs(f.BoundBox.ZMin - 10) < 1e-6 and abs(f.BoundBox.ZMax - 10) < 1e-6

    caps = [f for f in pad.Shape.Faces if farCap(f)]
    if len(caps) != 5:
        raise AssertionError(f"TwinPad has {len(caps)} far caps, expected five")
    valley = V(3 + 1.75 * math.cos(math.pi / 4), 3 + 1.75 * math.sin(math.pi / 4), 10)
    twin = faceWhere(pad.Shape, lambda f: farCap(f) and f.isInside(valley, 1e-6, True))
    point = body.newObject("PartDesign::Point", "TwinPoint")
    point.AttachmentSupport = [(pad, twin)]
    point.MapMode = "CenterOfMass"
    body.Tip = pad
    doc.recompute()
    # The volume is pi 2.3^2 10, but OCCT integrates the trimmed B-spline caps only to about
    # 1e-6 (166.19004 against 166.19025): checked here at 1e-5, not as an exact stated volume.
    volume = math.pi * 2.3 * 2.3 * 10
    if abs(pad.Shape.Volume - volume) > 1e-5 * volume:
        raise AssertionError(f"TwinPad volume {pad.Shape.Volume}, expected {volume}")
    return {"volumes": {}}


def BodyFromFeature(make):
    """A Body based on another Body's feature, and a Boolean of two Bodies.

    Body: a 30 x 20 x 10 block (0..30). Body001: its BaseFeature is Body's Pad; a circle,
    radius 3, at (10, 10) on its XY plane pocketed through all. Body002: a box 10 x 10 x 10 at
    (-5, 0, 0) (an additive primitive), cut by Body (a PartDesign Boolean of the whole Body):
    5 x 10 x 10 is left."""
    doc = make("BodyFromFeature")
    body = newBody(doc, "Body")
    pad = block(body, 0, 0, 30, 20, 10)
    doc.recompute()
    body2 = newBody(doc, "Body001")
    body2.BaseFeature = pad
    doc.recompute()
    hole = m.pocketThroughAll(
        body2,
        attachedSketch(body2, "HoleSketch", plane(body2, "XY_Plane"), [m.circle(10, 10, 3)]),
        "Hole",
    )
    hole.SideType = "Symmetric"
    body3 = newBody(doc, "Body002")
    box = body3.newObject("PartDesign::AdditiveBox", "Box")
    box.Length = box.Width = box.Height = 10
    box.Placement = App.Placement(V(-5, 0, 0), App.Rotation())
    doc.recompute()
    boolean = body3.newObject("PartDesign::Boolean", "Boolean")
    boolean.setObjects([body])
    boolean.Type = "Cut"
    doc.recompute()
    return {"volumes": {"Pad": 6000, "Hole": 6000 - math.pi * 9 * 10, "Boolean": 500}}


def Binders(make):
    """A ShapeBinder, a moved source Body (ops#308 T4), an expression across Bodies, and an
    ambiguous reference (two coincident faces) kept by its index.

    Source: a Body at (100, 50, 0), a 40 x 40 x 10 block on its XY plane (so x 100..140,
    y 50..90 in the document). Lid: a SubShapeBinder of the block's top face (it follows the
    moved Body), a rectangle x 105..135, y 55..85 on it, padded 5. Cap: a ShapeBinder of the
    same face, a circle, radius 4, at (120, 70) on it, padded by the expression
    `LidPad.Length * 2` (10). Twin and Twin001: two Bodies, each a 10 x 10 x 5 block (0..10),
    whose top faces coincide; Tag: a SubShapeBinder of both top faces (a compound of two equal
    faces), a sketch on its second face with a circle, radius 2, at (5, 5), padded 3."""
    doc = make("Binders")
    source = newBody(doc, "Source")
    source.Placement = App.Placement(V(100, 50, 0), App.Rotation())
    sourcePad = block(source, 0, 0, 40, 40, 10, "SourcePad")
    doc.recompute()
    top = faceWhere(sourcePad.Shape, planeFacing(TOP, V(0, 0, 10)))
    lid = newBody(doc, "Lid")
    binder = lid.newObject("PartDesign::SubShapeBinder", "SourceTop")
    binder.Support = [(sourcePad, (top,))]
    doc.recompute()
    lidPad = m.pad(
        lid,
        attachedSketch(lid, "LidSketch", (binder, "Face1"), m.rectangle(105, 55, 135, 85)),
        5,
        "LidPad",
    )
    cap = newBody(doc, "Cap")
    shapeBinder = cap.newObject("PartDesign::ShapeBinder", "ShapeBinder")
    shapeBinder.Support = [(sourcePad, top)]
    doc.recompute()
    capPad = m.pad(
        cap,
        attachedSketch(cap, "CapSketch", (shapeBinder, "Face1"), [m.circle(120, 70, 4)]),
        1,
        "CapPad",
    )
    capPad.setExpression("Length", "LidPad.Length * 2")
    twins = []
    for name in ("Twin", "Twin001"):
        twin = newBody(doc, name)
        twins.append(block(twin, 0, 0, 10, 10, 5, name + "Pad"))
    doc.recompute()
    tag = newBody(doc, "Tag")
    both = tag.newObject("PartDesign::SubShapeBinder", "TwinTops")
    both.Support = [
        (t, (faceWhere(t.Shape, planeFacing(TOP, V(0, 0, 5))),)) for t in twins
    ]
    doc.recompute()
    if len(both.Shape.Faces) != 2:
        raise AssertionError(f"TwinTops has {len(both.Shape.Faces)} faces, expected two")
    m.pad(tag, attachedSketch(tag, "TagSketch", (both, "Face2"), [m.circle(5, 5, 2)]), 3, "TagPad")
    doc.recompute()
    return {
        "volumes": {
            "SourcePad": 16000,
            "LidPad": 900 * 5,
            "CapPad": math.pi * 16 * 10,
            "TagPad": math.pi * 4 * 3,
        }
    }


def IndexToldGroups(make):
    """References to elements named alike and told apart only by an index (ops#378).

    Body: a 6 x 6 square with a round hole, radius 1, centred on the XY plane's origin, piped
    along an L in the XZ plane, up from (0, 0, 0) to (0, 0, 30), then along +X to (20, 0, 30),
    Right corner (TestNamingDump's PipeShell Pipe). At the bend the hole's two side faces meet in
    four quarter arcs, and the four vertexes between them, all named from the same two faces;
    OCCT stores the arcs in opposite orders on Windows and macOS, and the index follows their
    places since ops#378. A chamfer, size 0.2, on the arc centred at (-0.6009, -0.6729, 30.6009)
    (a fillet there fails in OCCT: "command not done"), and a datum point on the bend vertex
    (0, -1, 30). CornerCut: two overlapping boxes, 1 x 2 x 2 and 2 x 1 x 2, as a compound, cut
    by a cylinder, radius 0.5, 2 high, on their shared corner (TestNamingDump's CompoundCut); a
    sphere, radius 0.1, attached to the cut corner (0, 0.5, 2), the one of its two coincident
    vertexes named `UPP` (index 1, counted on from an edge named from the same faces)."""
    doc = make("IndexToldGroups")
    body = newBody(doc, "Body")
    profile = attachedSketch(
        body,
        "HoledSquare",
        plane(body, "XY_Plane"),
        m.rectangle(-3, -3, 3, 3) + [m.circle(0, 0, 1)],
    )
    # in the XZ plane's sketch, x is X and y is Z
    path = attachedSketch(
        body, "LPath", plane(body, "XZ_Plane"), m.polyline([(0, 0), (0, 30), (20, 30)])
    )
    pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
    pipe.Profile = profile
    pipe.Spine = path
    pipe.Transition = "Right corner"
    doc.recompute()
    arc = edgeWhere(
        pipe.Shape, lambda e: (e.CenterOfMass - V(-0.6009, -0.6729, 30.6009)).Length < 1e-3
    )
    chamfer = body.newObject("PartDesign::Chamfer", "ArcChamfer")
    chamfer.Base = (pipe, [arc])
    chamfer.Size = 0.2
    point = body.newObject("PartDesign::Point", "BendPoint")
    point.AttachmentSupport = [(pipe, vertexAt(pipe.Shape, V(0, -1, 30)))]
    point.MapMode = "Vertex"
    body.Tip = chamfer
    first = m.box(doc, "First", (1, 2, 2))
    second = m.box(doc, "Second", (2, 1, 2))
    cylinder = doc.addObject("Part::Cylinder", "Cylinder")
    cylinder.Radius = 0.5
    cylinder.Height = 2
    compound = doc.addObject("Part::Compound", "Compound")
    compound.Links = [first, second]
    cut = doc.addObject("Part::Cut", "CornerCut")
    cut.Base, cut.Tool, cut.Refine = compound, cylinder, False
    doc.recompute()
    corners = [
        f"Vertex{i + 1}"
        for i, v in enumerate(cut.Shape.Vertexes)
        if (v.Point - V(0, 0.5, 2)).Length < 1e-6
        and ";UPP;" in cut.Shape.getElementMappedName(f"Vertex{i + 1}")
    ]
    if len(corners) != 1:
        raise AssertionError(f"{len(corners)} UPP vertexes at the cut corner, expected one")
    ball = doc.addObject("Part::Sphere", "CornerBall")
    ball.Radius = 0.1
    ball.AttachmentSupport = [(cut, corners[0])]
    ball.MapMode = "Translate"
    doc.recompute()
    return {
        "volumes": {
            "Pipe": (36 - math.pi) * 50,
            "CornerCut": 8 - 2 * (math.pi * 0.25 * 2 / 4),
            "CornerBall": 4 / 3 * math.pi * 0.001,
        }
    }


ROUND_ON_SPLINE_TWIST = 0.02
ROUND_ON_SPLINE_RADIUS = 1.5


def twistedLid(twist):
    """The face z = 20 + twist x y over x -45..45, y -25..25, as a bicubic B-spline."""
    x, y = 45.0, 25.0
    surface = Part.BSplineSurface()
    poles = [
        [V(-x, -y, 20 + twist * x * y), V(-x, y, 20 - twist * x * y)],
        [V(x, -y, 20 - twist * x * y), V(x, y, 20 + twist * x * y)],
    ]
    surface.buildFromPolesMultsKnots(poles, [2, 2], [2, 2], [0, 1], [0, 1], False, False, 1, 1)
    surface.increaseDegree(3, 3)
    return surface.toShape()


def roundOnSplineContact(fillet, twist, radius, grid=17):
    """How far the rim round of `RoundOnSpline` is from the ball's contact, in closed form (no
    kernel distance): (blend faces, ball residual, seam residual, seams).

    A round of radius r is the surface a ball of radius r sweeps while it touches both walls.
    For a point p of a blend face with outward normal n the ball's centre is c = p - r n, and
    it must be at distance r from the lid z = 20 + twist x y and from the stadium's side wall
    (the planes y = -10 and y = 10 for |x| <= 20, else the cylinders of radius 10 about
    x = -20 and x = 20). The ball residual is the largest | distance - r | over a grid on
    every blend face. Two blend faces meet where the ball's contact crosses a tangent line
    x = +-20, y = +-10 of the wall: there the centre is at (+-20, +-(10 - r), z) with z at
    distance r below the lid, and the seam is that ball's circle. The seam residual is the
    largest | distance from that centre - r | along the four seams."""

    def lidDistance(a, b, h):
        x, y = a, b
        for _ in range(50):
            g = 20 + twist * x * y - h
            fx = (x - a) + g * twist * y
            fy = (y - b) + g * twist * x
            fxx = 1 + twist * twist * y * y
            fyy = 1 + twist * twist * x * x
            fxy = g * twist + twist * twist * x * y
            det = fxx * fyy - fxy * fxy
            dx = (fx * fyy - fy * fxy) / det
            dy = (fy * fxx - fx * fxy) / det
            x -= dx
            y -= dy
            if abs(dx) + abs(dy) < 1e-15:
                break
        return math.sqrt((x - a) ** 2 + (y - b) ** 2 + (20 + twist * x * y - h) ** 2)

    def wallDistance(a, b):
        return 10 - abs(b) if abs(a) <= 20 else 10 - math.hypot(abs(a) - 20, b)

    def isBlend(face):
        if isinstance(face.Surface, Part.Plane):
            return False
        if isinstance(face.Surface, Part.Cylinder) and abs(face.Surface.Radius - 10) < 1e-9:
            return False
        return face.Area < 500  # the lid is over 1000

    blends = [f for f in fillet.Shape.Faces if isBlend(f)]
    ball = 0.0
    for face in blends:
        u0, u1, v0, v1 = face.ParameterRange
        for i in range(grid):
            for j in range(grid):
                u = u0 + (u1 - u0) * (i + 0.5) / grid
                v = v0 + (v1 - v0) * (j + 0.5) / grid
                c = face.valueAt(u, v) - face.normalAt(u, v) * radius
                ball = max(
                    ball,
                    abs(lidDistance(c.x, c.y, c.z) - radius),
                    abs(wallDistance(c.x, c.y) - radius),
                )
    seamEdges = [
        e
        for e in fillet.Shape.Edges
        if sum(1 for f in blends if any(e.isSame(x) for x in f.Edges)) == 2
    ]
    seam = 0.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            a, b = 20.0 * sx, (10.0 - radius) * sy
            low, high = 0.0, 20 + twist * a * b
            for _ in range(200):
                middle = (low + high) / 2
                if lidDistance(a, b, middle) > radius:
                    low = middle
                else:
                    high = middle
            centre = V(a, b, (low + high) / 2)
            if not seamEdges:
                continue
            seam = max(
                seam,
                min(
                    max(abs((p - centre).Length - radius) for p in e.discretize(25))
                    for e in seamEdges
                ),
            )
    return len(blends), ball, seam, len(seamEdges)


def RoundOnSpline(make):
    """A round on a B-spline support (ops#640, decision 425: a round is the rolling ball's
    surface, also where the kernel's own fillet is not).

    A Part feature's face, the twisted lid z = 20 + 0.02 x y (a bicubic B-spline). Body: a
    SubShapeBinder of the lid; a stadium on the XY plane (the lines y = -10 and y = 10 for x
    -20..20, half circles of radius 10 about (-20, 0) and (20, 0)) padded up to the binder's
    face (UpToShape), so the Pad's top is the B-spline; a Fillet of radius 1.5 round the
    top's whole rim (five edges: the half cylinder about x = 20 is cut at its seam, so its
    rim is two edges): four blend faces in one closed chain, meeting on the wall's four
    tangent lines. The lid's normal turns about the rim, so a circle swept in the plane
    normal to the edge is off the ball by 3.6e-3 and its seams by 0.07.

    The expected result is the ball's contact, in closed form (`roundOnSplineContact`): every
    blend face within 1e-6 of it, and each seam the ball's circle where the contact crosses a
    tangent line of the wall."""
    twist, radius = ROUND_ON_SPLINE_TWIST, ROUND_ON_SPLINE_RADIUS
    doc = make("RoundOnSpline")
    lid = doc.addObject("Part::Feature", "TwistedLid")
    lid.Shape = twistedLid(twist)
    body = newBody(doc, "Body")
    binder = body.newObject("PartDesign::SubShapeBinder", "LidBinder")
    binder.Support = [(lid, ("Face1",))]
    stadium = [
        Part.LineSegment(V(-20, -10, 0), V(20, -10, 0)),
        Part.ArcOfCircle(Part.Circle(V(20, 0, 0), TOP, 10), -math.pi / 2, math.pi / 2),
        Part.LineSegment(V(20, 10, 0), V(-20, 10, 0)),
        Part.ArcOfCircle(Part.Circle(V(-20, 0, 0), TOP, 10), math.pi / 2, 3 * math.pi / 2),
    ]
    pad = body.newObject("PartDesign::Pad", "StadiumPad")
    pad.Profile = attachedSketch(body, "StadiumSketch", plane(body, "XY_Plane"), stadium)
    pad.Type = "UpToShape"
    pad.UpToShape = (binder, ["Face1"])
    pad.Refine = False
    doc.recompute()
    top = [f for f in pad.Shape.Faces if isinstance(f.Surface, Part.BSplineSurface)]
    if len(top) != 1:
        raise AssertionError(f"StadiumPad has {len(top)} B-spline faces, expected its top")
    rim = [
        f"Edge{i + 1}"
        for i, e in enumerate(pad.Shape.Edges)
        if any(e.isSame(x) for x in top[0].Edges)
    ]
    if len(rim) != 5:
        raise AssertionError(f"the top's rim has {len(rim)} edges, expected five")
    fillet = body.newObject("PartDesign::Fillet", "RimRound")
    fillet.Base = (pad, rim)
    fillet.Radius = radius
    body.Tip = fillet
    doc.recompute()
    faces, ball, seam, seams = roundOnSplineContact(fillet, twist, radius)
    if (faces, seams) != (4, 4):
        raise AssertionError(f"RimRound has {faces} blend faces and {seams} seams, expected 4 and 4")
    if ball > 1e-6 or seam > 1e-6:
        raise AssertionError(
            f"RimRound is off the ball's contact by {ball:.3g} (seams {seam:.3g}), allowed 1e-6"
        )
    return {"volumes": {}}


LEANING_BOSS_LEAN = (0.3, 0.2)
LEANING_BOSS_RADIUS = 2.0
LEANING_BOSS_FLOOR = 5.0


def roundUnderLeaningWallContact(fillet, radius, grid=13):
    """How far the foot round of `RoundUnderLeaningWall` is from the ball's contact, in closed
    form (no kernel distance): (cylinder blend faces, other blend faces, ball residual).

    A round of radius r is the surface a ball of radius r sweeps while it touches both walls.
    Here the walls are the slab's top z = 5 and the boss's side: the stadium (the lines
    y = -10 and y = 10 for x -20..20, half circles of radius 10 about (-20, 0) and (20, 0))
    drawn at z = 0 and swept along (0.3, 0.2, 1). For a point p of a blend face with unit
    normal n the ball's centre is c = p + r n or p - r n, the one at height 5 + r, and it
    must be at distance r from the boss's side: under a leaning plane the distance to that
    plane, under a leaning circle's wall the distance from c, moved back along the sweep to
    z = 0, to the circle, measured across the sweep (one angle, found by search). The ball
    residual is the largest | distance - r | and | height - (5 + r) | over a grid on every
    blend face."""
    lx, ly = LEANING_BOSS_LEAN
    floor = LEANING_BOSS_FLOOR
    sweep = V(lx, ly, 1)
    sweep.normalize()

    def across(offset):
        return (offset - sweep * offset.dot(sweep)).Length

    def circleWallDistance(c, centreX):
        def at(angle):
            on = V(centreX + 10 * math.cos(angle), 10 * math.sin(angle), 0)
            return across(c - on)

        step = math.pi / 180
        k = min(range(360), key=lambda i: at(i * step))
        low, high = (k - 1) * step, (k + 1) * step
        for _ in range(80):
            m1 = low + (high - low) * 0.381966
            m2 = low + (high - low) * 0.618034
            if at(m1) < at(m2):
                high = m2
            else:
                low = m1
        return at((low + high) / 2)

    planeNormal = V(1, 0, 0).cross(sweep)
    planeNormal.normalize()

    def planeWallDistance(c, y0):
        return abs((c - V(0, y0, 0)).dot(planeNormal))

    blends = [
        f
        for f in fillet.Shape.Faces
        if not isinstance(f.Surface, Part.Plane)
        # by its corners (a spline face's box is its poles'); a wall that leans over the round
        # is touched above 5 + r
        and all(floor - 1e-6 < v.Point.z < floor + 2 * radius for v in f.Vertexes)
    ]
    cylinders = [
        f
        for f in blends
        if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - radius) < 1e-9
    ]
    ball = 0.0
    for face in blends:
        u0, u1, v0, v1 = face.ParameterRange
        for i in range(grid):
            for j in range(grid):
                u = u0 + (u1 - u0) * (i + 0.5) / grid
                v = v0 + (v1 - v0) * (j + 0.5) / grid
                p = face.valueAt(u, v)
                n = face.normalAt(u, v)
                c = min((p + n * radius, p - n * radius), key=lambda q: abs(q.z - floor - radius))
                # Back along the sweep to the sketch's plane: which part of the stadium is beside it
                foot = c - V(lx, ly, 1) * c.z
                if face in cylinders:
                    wall = planeWallDistance(c, 10.0 if foot.y > 0 else -10.0)
                else:
                    wall = circleWallDistance(c, 20.0 if foot.x > 0 else -20.0)
                ball = max(ball, abs(c.z - floor - radius), abs(wall - radius))
    return len(cylinders), len(blends) - len(cylinders), ball


def RoundUnderLeaningWall(make):
    """A round whose chain has cylinders and spline faces (ops#640, decision 425: a round is
    the rolling ball's surface, also where the kernel's own fillet is not; Nest Insert's slot
    round under a leaning elliptic wall).

    Body: a slab, the rectangle -45..55 by -30..40 padded 5; a stadium on the XY plane (the
    lines y = -10 and y = 10 for x -20..20, half circles of radius 10 about (-20, 0) and
    (20, 0)) padded 30 along (0.3, 0.2, 1), so the boss leans: its side is two leaning planes
    and two walls swept from the circles, which are elliptic cylinders, not normal to the
    slab; a Fillet of radius 2 round the boss's whole foot on the slab. Under the planes the
    round is a cylinder of radius 2. Under the circles' walls the wall's normal turns about
    the foot's edge, so a circle swept in the plane normal to the edge is off the ball by
    5e-3, and the kernel's seams between the four faces by 1.4e-2.

    The expected result is the ball's contact, in closed form (`roundUnderLeaningWallContact`):
    two cylinders of the radius and two other faces, each within 1e-6 of it."""
    radius = LEANING_BOSS_RADIUS
    doc = make("RoundUnderLeaningWall")
    body = newBody(doc, "Body")
    slab = block(body, -45, -30, 55, 40, LEANING_BOSS_FLOOR, "Slab")
    stadium = [
        Part.LineSegment(V(-20, -10, 0), V(20, -10, 0)),
        Part.ArcOfCircle(Part.Circle(V(20, 0, 0), TOP, 10), -math.pi / 2, math.pi / 2),
        Part.LineSegment(V(20, 10, 0), V(-20, 10, 0)),
        Part.ArcOfCircle(Part.Circle(V(-20, 0, 0), TOP, 10), math.pi / 2, 3 * math.pi / 2),
    ]
    boss = body.newObject("PartDesign::Pad", "LeaningBoss")
    boss.Profile = attachedSketch(body, "StadiumSketch", plane(body, "XY_Plane"), stadium)
    boss.UseCustomVector = True
    boss.Direction = V(LEANING_BOSS_LEAN[0], LEANING_BOSS_LEAN[1], 1)
    boss.AlongSketchNormal = True
    boss.Length = 30
    boss.Refine = False
    doc.recompute()
    if abs(slab.Shape.Volume - 100 * 70 * LEANING_BOSS_FLOOR) > 1e-6:
        raise AssertionError("the slab is not 100 x 70 x 5")
    foot = [
        f"Edge{i + 1}"
        for i, e in enumerate(boss.Shape.Edges)
        if abs(e.BoundBox.ZMin - LEANING_BOSS_FLOOR) < 1e-7
        and abs(e.BoundBox.ZMax - LEANING_BOSS_FLOOR) < 1e-7
        and e.BoundBox.XMin > -40
        and e.BoundBox.XMax < 50
        and e.BoundBox.YMin > -25
        and e.BoundBox.YMax < 35
    ]
    if len(foot) != 5:
        raise AssertionError(f"the boss's foot has {len(foot)} edges, expected five")
    fillet = body.newObject("PartDesign::Fillet", "FootRound")
    fillet.Base = (boss, foot)
    fillet.Radius = radius
    body.Tip = fillet
    doc.recompute()
    cylinders, others, ball = roundUnderLeaningWallContact(fillet, radius)
    if (cylinders, others) != (2, 2):
        raise AssertionError(
            f"FootRound has {cylinders} cylinders and {others} other blend faces, expected 2 and 2"
        )
    if ball > 1e-6:
        raise AssertionError(f"FootRound is off the ball's contact by {ball:.3g}, allowed 1e-6")
    return {"volumes": {}}


def bossTops(shape, z):
    """The (x, y) centres of the shape's 6 x 6 planar faces facing +z at height z, sorted."""
    return sorted(
        (round(f.CenterOfMass.x, 6), round(f.CenterOfMass.y, 6))
        for f in shape.Faces
        if isinstance(f.Surface, Part.Plane)
        and abs(f.CenterOfMass.z - z) < 1e-6
        and abs(f.Area - 36) < 1e-6
    )


def FacePatternCentered(make):
    """Face patterns with Centered and a second direction (ops#655, ops#640; Onshape's rule,
    notes/patterns-design.md section 10: Centered counts per side, the seed included, so count n
    makes 2n - 1 instances along that direction).

    Two Bodies, each a 60 x 30 x 10 plate (x -30..30, y 0..30) with a 6 x 6 boss, 5 high, at its
    centre (x -3..3, y 12..18), patterned by its faces (the boss's top and four sides):
    - `Row`: a face linear pattern along the X axis, spacing 15, count 2, Centered: three bosses,
      centres x -15, 0, 15 at y 15;
    - `Grid`: the same along X, and a second direction along the Y axis, spacing 10, count 2,
      Centered2: a 3 x 3 grid, centres x -15, 0, 15 by y 5, 15, 25 (the bosses 4 apart in y)."""
    doc = make("FacePatternCentered")
    plate = 60 * 30 * 10
    boss = 6 * 6 * 5
    expected = {
        "Row": [(x, 15) for x in (-15, 0, 15)],
        "Grid": sorted((x, y) for x in (-15, 0, 15) for y in (5, 15, 25)),
    }
    volumes = {}
    for name, centres in expected.items():
        body = newBody(doc, name + "Body")
        pad = block(body, -30, 0, 30, 30, 10, name + "Plate")
        doc.recompute()
        top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
        seed = m.pad(
            body,
            attachedSketch(body, name + "BossSketch", (pad, top), m.rectangle(-3, 12, 3, 18)),
            5,
            name + "Boss",
        )
        doc.recompute()
        picks = [
            f"Face{i + 1}"
            for i, f in enumerate(seed.Shape.Faces)
            if -3 - 1e-6 <= f.CenterOfMass.x <= 3 + 1e-6
            and 12 - 1e-6 <= f.CenterOfMass.y <= 18 + 1e-6
            and 10 + 1e-3 <= f.CenterOfMass.z <= 15 + 1e-6
        ]
        if len(picks) != 5:
            raise AssertionError(f"{name}: {len(picks)} boss faces, expected 5")
        pattern = body.newObject("PartDesign::FaceLinearPattern", name)
        pattern.Base = (seed, picks)
        pattern.Direction = (plane(body, "X_Axis"), [""])
        pattern.Mode = "Spacing"
        pattern.Offset = 15
        pattern.Occurrences = 2
        pattern.Centered = True
        if name == "Grid":
            pattern.Direction2 = (plane(body, "Y_Axis"), [""])
            pattern.Mode2 = "Spacing"
            pattern.Offset2 = 10
            pattern.Occurrences2 = 2
            pattern.Centered2 = True
        body.Tip = pattern
        doc.recompute()
        found = bossTops(pattern.Shape, 15)
        if found != sorted(centres):
            raise AssertionError(f"{name}: boss tops at {found}, expected {sorted(centres)}")
        volumes[name] = plate + len(centres) * boss
    return {"volumes": volumes}


def RevolveFreeFormProfile(make):
    """Revolutions of profiles drawn with B-spline lines and circle arcs (ops#768).

    Body: on the XZ plane, the half disk of radius 2 about (5, 0) outside x = 5 (its arc an exact
    rational B-spline) and the triangle (5, 2), (4, -2), (5, -2) (its slanted side a B-spline
    segment), revolved 360 degrees about the V axis (the Z axis): Pappus's volume, 2 pi times
    (2 pi (5 + 8 / (3 pi)) + 2 * 14 / 3). Builds since d637412375 make the arc's face a torus and
    the side's a cone; builds before it made both SurfaceOfRevolution faces of B-splines.
    Body001: on the XZ plane, the half disk of radius 3 about (0, 30) right of the V axis, its arc a
    rational B-spline ending on the axis and its chord on it, revolved 90 degrees: a quarter of a
    ball, 9 pi (since d637412375 a sphere face)."""
    doc = make("RevolveFreeFormProfile")
    body = newBody(doc, "Body")
    arc = Part.ArcOfCircle(Part.Circle(V(5, 0, 0), V(0, 0, 1), 2), -math.pi / 2, math.pi / 2)
    profile = attachedSketch(
        body,
        "Sketch",
        plane(body, "XZ_Plane"),
        [
            arc.toNurbs(),
            Part.LineSegment(V(5, 2, 0), V(4, -2, 0)).toBSpline(),
            Part.LineSegment(V(4, -2, 0), V(5, -2, 0)),
        ],
    )
    revolution = body.newObject("PartDesign::Revolution", "Revolution")
    revolution.Profile = profile
    revolution.ReferenceAxis = (profile, ["V_Axis"])
    revolution.Angle = 360
    body2 = newBody(doc, "Body001")
    cap = Part.ArcOfCircle(Part.Circle(V(0, 30, 0), V(0, 0, 1), 3), -math.pi / 2, math.pi / 2)
    profile2 = attachedSketch(
        body2,
        "Sketch001",
        plane(body2, "XZ_Plane"),
        [cap.toNurbs(), Part.LineSegment(V(0, 33, 0), V(0, 27, 0))],
    )
    revolution2 = body2.newObject("PartDesign::Revolution", "Revolution001")
    revolution2.Profile = profile2
    revolution2.ReferenceAxis = (profile2, ["V_Axis"])
    revolution2.Angle = 90
    doc.recompute()
    return {
        "volumes": {
            "Revolution": 2 * math.pi * (2 * math.pi * (5 + 8 / (3 * math.pi)) + 2 * 14 / 3),
            "Revolution001": 9 * math.pi,
        }
    }


def LoftNormalToProfile(make):
    """A loft with both ends Normal to profile, saved with Onshape's tangent rule (ops#855).

    Body: a loft from a square, side 40, on the XY plane (centred) to a square, side 10, 10 up,
    StartCondition and EndCondition "Normal to profile" at magnitude 1, TangentRule "Onshape" (fork
    PR 468, kept per file since fork PR 471). Every row is the cubic X(s) = 20 (B0 + B1) + 5 (B2 +
    B3), z(s) = k/3 B1 + (10 - k/3) B2 + 10 B3 with k = 0.9 x 10 + 0.1 x |rail| (the corner rail,
    |rail| = sqrt(2 x 15^2 + 10^2)) at both ends, uniform by symmetry; the volume is the integral of
    (2 X)^2 dz (`TestLoftOnshape.TestLoftTangentRule`). fork-1.0.0's rule (Legacy, k = 30.138/30 of
    the distance) gives 7344.4342857 instead, 44.5 below: a file saved with the property must
    reopen with Onshape's rule (R3)."""
    doc = make("LoftNormalToProfile")
    body = newBody(doc, "Body")
    xy = plane(body, "XY_Plane")
    bottom = attachedSketch(body, "Bottom", xy, m.rectangle(-20, -20, 20, 20))
    top = attachedSketch(body, "Top", xy, m.rectangle(-5, -5, 5, 5))
    top.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
    loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
    loft.Profile = bottom
    loft.Sections = [top]
    loft.StartCondition = "Normal to profile"
    loft.EndCondition = "Normal to profile"
    loft.TangentRule = "Onshape"
    doc.recompute()
    k = 0.9 * 10 + 0.1 * math.sqrt(2 * 15**2 + 10**2)
    n = 2000
    total = 0.0
    for i in range(n + 1):
        s = i / n
        t = 1 - s
        x = 20 * (t**3 + 3 * s * t * t) + 5 * (3 * s * s * t + s**3)
        dz = t * t * k + 6 * s * t * (10 - 2 * k / 3) + s * s * k
        total += (1 if i in (0, n) else (4 if i % 2 else 2)) * 4 * x * x * dz
    return {"volumes": {"Loft": total / (3 * n)}}


def MitreAtLobeCorners(make):
    """A fillet whose line and arc rounds meet in a mitre at a corner convex in the material
    (ops#941, notes/fillet-corner-mitre-941.md; Onshape's corner is that mitre, oracle941).

    Body: as BaseFeature, a ring plate of radii 2 and 9, 2 thick under z 0, with four ring-sector
    lobes between radii 4 and 5, 60 degrees wide, 2 high, turned half a turn about X and back (the
    last digits of a Body's placement); a Fillet of radius 0.588 on the lobes' 16 foot edges.
    At that radius OCCT's own result is invalid (one of its narrow bands); the exact construction
    builds the mitre: 16 new faces, each corner's rounds meeting in one edge.

    The expected volume is the plate's and the lobes', plus the fill by geometry: the lines' and
    arcs' rounds in closed form and each corner's piece by the plan integral of its height
    (`parttests.FilletFallbackTest.mitre_fill_volume`)."""
    from parttests.FilletFallbackTest import lobe_feet, lobed_plate, mitre_fill_volume

    radius = 0.588
    doc = make("MitreAtLobeCorners")
    # The plate as its file holds it: the noise in its axes is below what a saved shape keeps,
    # and the mitre turns that last digit into 2e-10 of its volume at a reopen (ops#978)
    named = lobed_plate(True)
    shape = Part.Shape()
    shape.importBrepFromString(named.exportBrepToString())
    # The plate with its history's names, from which nothing is computed: its twin places'
    # duplicate counts `<k>of<n>~<m>` must reopen as saved (ops#978)
    twins = doc.addObject("Part::Feature", "TwinNames")
    twins.Shape = named
    base = doc.addObject("Part::Feature", "Lobes")
    base.Shape = shape
    body = newBody(doc, "Body")
    body.BaseFeature = base
    doc.recompute()
    edges = [
        "Edge%d" % next(i for i, e in enumerate(base.Shape.Edges, 1) if e.isSame(edge))
        for edge in lobe_feet(base.Shape)
    ]
    if len(edges) != 16:
        raise AssertionError(f"the lobes have {len(edges)} foot edges, expected 16")
    fillet = body.newObject("PartDesign::Fillet", "FootMitre")
    fillet.Base = (body.BaseFeature, edges)
    fillet.Radius = radius
    body.Tip = fillet
    doc.recompute()
    plate = math.pi * (9 * 9 - 2 * 2) * 2
    lobes = 4 * (60.0 / 360.0) * math.pi * (5 * 5 - 4 * 4) * 2
    if abs(base.Shape.Volume - (plate + lobes)) > 1e-7 * (plate + lobes):
        raise AssertionError("the lobed plate's volume is not the plate's and the lobes'")
    if len(fillet.Shape.Faces) - len(base.Shape.Faces) != 16:
        raise AssertionError("FootMitre does not add 16 faces")
    return {"volumes": {"FootMitre": plate + lobes + mitre_fill_volume(radius, steps=4000)}}


def ChamferVaryingAngle(make):
    """Equal distance chamfers along closed edges whose faces' angle varies, as Onshape's: one ball
    rolled round each edge (ops#942, notes/chamfer-varying-angle-942.md).

    Body: a block whose top is the plane z = x tan 20 deg (60 x 60, 30 deep at x = 0), with a
    cylinder of radius 10 from z = -20 to 20 fused in (a boss); its foot chamfered 2, Narrowest
    angle: d = 2 tan 35 deg, the fill pi d^2 (R + d / 3) (1 + sin^2 t / 2) / cos t = 72.6404
    (section 2's closed form). Body001: a cone of radius 20 at z = 0 leaning in by 10 deg, 20 high,
    four holes of radius 3 square to its axis at z = 10 and 45, 135, 225 and 315 deg; their rims
    chamfered 1, Narrowest angle (77.8565 deg): each cuts 8.584185, TestChamfer's own integral of
    the ball's sweep (_coneWallChamfer). On each chamfer, points at the centres of mass of a chamfer
    face and of its two rails, so that the names of the face and the rails are kept in the file.
    fork-1.0.0's OCCT chamfer puts the width on both faces all round instead: a file saved with the
    rule must reopen with it (R3)."""
    doc = make("ChamferVaryingAngle")
    R, t = 10.0, math.radians(20)
    k = math.tan(t)
    corners = [V(-30, -30, -30), V(30, -30, -30), V(30, -30, 30 * k), V(-30, -30, -30 * k)]
    plate = Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 60, 0))
    boss = plate.fuse(Part.makeCylinder(R, 40, V(0, 0, -20))).removeSplitter()
    draft = math.radians(10)
    cone = Part.makeCone(20, 20 - 20 * math.tan(draft), 20)
    for degrees in (45.0, 135.0, 225.0, 315.0):
        p = math.radians(degrees)
        along = V(math.cos(p), math.sin(p), 0)
        cone = cone.cut(Part.makeCylinder(3, 20, V(0, 0, 10) + along * 10, along))
    cone = cone.removeSplitter()
    volumes = {}
    for name, shape, kind, size in (("Body", boss, "Part::GeomEllipse", 2.0),
                                    ("Body001", cone, "Part::GeomBSplineCurve", 1.0)):
        base = doc.addObject("Part::Feature", name + "Base")
        base.Shape = shape
        body = newBody(doc, name)
        body.BaseFeature = base
        doc.recompute()
        edges = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges)
                 if e.Curve.TypeId == kind and e.isClosed()]
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer" if name == "Body" else "HoleChamfer")
        chamfer.Base = (base, edges)
        chamfer.Size = size
        doc.recompute()
        face = [i + 1 for i, f in enumerate(chamfer.Shape.Faces)
                if f.Surface.TypeId == "Part::GeomBSplineSurface"][0]
        rails = [e for e in chamfer.Shape.Faces[face - 1].Edges
                 if not e.isSeam(chamfer.Shape.Faces[face - 1])]
        names = ["Face%d" % face] + [
            "Edge%d" % (i + 1) for i, e in enumerate(chamfer.Shape.Edges)
            if any(e.isSame(rail) for rail in rails)
        ]
        for index, element in enumerate(names):
            point = body.newObject("PartDesign::Point", "%sPoint%d" % (chamfer.Name, index))
            point.AttachmentSupport = [(chamfer, element)]
            point.MapMode = "CenterOfMass"
        body.Tip = chamfer
        doc.recompute()
        if name == "Body":
            d = 2 * math.tan((math.pi / 2 - t) / 2)
            fill = math.pi * d * d * (R + d / 3) * (1 + math.sin(t) ** 2 / 2) / math.cos(t)
            volumes[chamfer.Name] = shape.Volume + fill
        else:
            volumes[chamfer.Name] = shape.Volume - 4 * 8.584185
    return {"volumes": volumes}


def MitreRunOnHexagon(make):
    """A round along each vertical corner line of a hexagonal plate whose rim was rounded first,
    tangent propagation adding the rims' mitre ellipses: Onshape's cylinder down to the rims' plane
    with a torus at its foot at each corner (ops#1020, notes/fillet-mitre-angle-1020-design.md,
    oracle RB8).

    Body: as BaseFeature, a regular hexagon across flats 60 with a vertex on +x, 3 thick, its top
    edges rounded 1.5 (Part's makeFillet); a Fillet of radius 3 on the six vertical lines alone.
    fork-1.0.8's OCCT fillet builds B-spline faces there, 0.28 mm3 more material than Onshape's.
    Per corner (t 120 deg, c = cot(t / 2), K = (1 - pi/4) q^2 (r - q) + q^3 / 6) the volume falls by
    r^2 (c - (pi - t) / 2) h + (pi - t - 2c) K (`parttests.FilletFallbackTest.MitreRunOnAngleTest`),
    from the base's own volume."""
    from parttests.FilletFallbackTest import MitreRunOnAngleTest as T

    radius = 3.0
    doc = make("MitreRunOnHexagon")
    rad = T.flats / 2 / math.cos(math.pi / 6)
    points = [V(rad * math.cos(math.pi * k / 3), rad * math.sin(math.pi * k / 3), 0) for k in range(6)]
    prism = Part.Face(Part.makePolygon(points + points[:1])).extrude(V(0, 0, T.thick))
    top = [e for e in prism.Edges if all(abs(v.Point.z - T.thick) < 1e-9 for v in e.Vertexes)]
    named = prism.makeFillet(T.q, top)
    shape = Part.Shape()
    shape.importBrepFromString(named.exportBrepToString())
    base = doc.addObject("Part::Feature", "RimmedHexagon")
    base.Shape = shape
    body = newBody(doc, "Body")
    body.BaseFeature = base
    doc.recompute()
    lines = [
        "Edge%d" % i
        for i, e in enumerate(base.Shape.Edges, 1)
        if e.Curve.TypeId == "Part::GeomLine" and abs(e.tangentAt(e.FirstParameter).z) > 0.999
    ]
    if len(lines) != 6:
        raise AssertionError(f"the hexagon has {len(lines)} vertical lines, expected 6")
    fillet = body.newObject("PartDesign::Fillet", "CornerRunOn")
    fillet.Base = (body.BaseFeature, lines)
    fillet.Radius = radius
    body.Tip = fillet
    doc.recompute()
    if any(f.Surface.TypeId == "Part::GeomBSplineSurface" for f in fillet.Shape.Faces):
        raise AssertionError("CornerRunOn has B-spline faces, not the run-on's tori")
    return {"volumes": {"CornerRunOn": base.Shape.Volume - 6 * T.change(radius, 2 * math.pi / 3)}}


def MitreRunOnOctagonSphere(make):
    """MitreRunOnHexagon's round on an octagon (the census corners' 135 degrees) with the round's
    radius equal to the rim's, 1.5: Onshape's corner is a cylinder 1.5 with a sphere 1.5 at its
    foot, the torus's major radius 0 (ops#1025, oracle RB27: V 8851.1147166).

    Body: as BaseFeature, a regular octagon across flats 60 with a vertex on +x, 3 thick, its top
    edges rounded 1.5 (Part's makeFillet); a Fillet of radius 1.5 on the eight vertical lines alone.
    fork-1.0.8's OCCT fillet builds B-spline faces there, 1.3e-3 mm3 less material than Onshape's.
    The volume from the base's own, less 8 corners' closed form (K = q^3 / 6 at r = q)."""
    from parttests.FilletFallbackTest import MitreRunOnAngleTest as T

    radius = T.q
    doc = make("MitreRunOnOctagonSphere")
    rad = T.flats / 2 / math.cos(math.pi / 8)
    points = [V(rad * math.cos(math.pi * k / 4), rad * math.sin(math.pi * k / 4), 0) for k in range(8)]
    prism = Part.Face(Part.makePolygon(points + points[:1])).extrude(V(0, 0, T.thick))
    top = [e for e in prism.Edges if all(abs(v.Point.z - T.thick) < 1e-9 for v in e.Vertexes)]
    named = prism.makeFillet(T.q, top)
    shape = Part.Shape()
    shape.importBrepFromString(named.exportBrepToString())
    base = doc.addObject("Part::Feature", "RimmedOctagon")
    base.Shape = shape
    body = newBody(doc, "Body")
    body.BaseFeature = base
    doc.recompute()
    lines = [
        "Edge%d" % i
        for i, e in enumerate(base.Shape.Edges, 1)
        if e.Curve.TypeId == "Part::GeomLine" and abs(e.tangentAt(e.FirstParameter).z) > 0.999
    ]
    if len(lines) != 8:
        raise AssertionError(f"the octagon has {len(lines)} vertical lines, expected 8")
    fillet = body.newObject("PartDesign::Fillet", "CornerSphere")
    fillet.Base = (body.BaseFeature, lines)
    fillet.Radius = radius
    body.Tip = fillet
    doc.recompute()
    spheres = [f for f in fillet.Shape.Faces if f.Surface.TypeId == "Part::GeomSphere"]
    if len(spheres) != 8:
        raise AssertionError(f"CornerSphere has {len(spheres)} sphere faces, not the run-on's 8")
    return {"volumes": {"CornerSphere": base.Shape.Volume - 8 * T.change(radius, 0.75 * math.pi)}}


MODELS = [
    RevolutionGroove,
    SidedVariants,
    DraftThickness,
    MirroredMultiTransform,
    LoftPipe,
    PipeCorners,
    HoleFeature,
    UpToFace,
    UpToTwins,
    BodyFromFeature,
    Binders,
    IndexToldGroups,
    RoundOnSpline,
    FacePatternCentered,
    RevolveFreeFormProfile,
    RoundUnderLeaningWall,
    LoftNormalToProfile,
    MitreAtLobeCorners,


    ChamferVaryingAngle,
    MitreRunOnHexagon,
    MitreRunOnOctagonSphere,
]
