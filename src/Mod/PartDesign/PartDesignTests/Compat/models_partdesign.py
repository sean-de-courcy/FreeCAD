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
    drift calibrates the BSpline tolerance (3.2)."""
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
    doc.recompute()
    loftVolume = frustum(20, 10, 10)
    return {
        "volumes": {
            "Loft": loftVolume,
            "Pipe": loftVolume + math.pi * 4 * (math.pi * 10 / 2),
        }
    }


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
    plane revolved about the Z axis up to the datum plane (a quarter of a ring, radii 4..8)."""
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
    doc.recompute()
    walls = 8000 + 10 * 20 * 15
    return {
        "volumes": {
            "Post": walls + 10 * 10 * 15,
            "Pocket": walls + 10 * 10 * 15 - math.pi * 4 * 15,
            "Revolution": math.pi * (64 - 16) * 4 / 4,
        }
    }


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


MODELS = [
    RevolutionGroove,
    SidedVariants,
    DraftThickness,
    MirroredMultiTransform,
    LoftPipe,
    HoleFeature,
    UpToFace,
    BodyFromFeature,
    Binders,
]
