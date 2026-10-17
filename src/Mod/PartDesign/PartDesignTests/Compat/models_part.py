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

"""The corpus's Part models (FreeCAD-CH ops#323 PR B2, notes/beta-compatibility.md 3.6, D3's
Part list). Same conventions as `models.py`."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Compat.models import TOP, V, edgeWhere, faceWhere, lineThrough, planeFacing
from PartDesignTests.Compat.models_partdesign import block, frustum, newBody
from PartDesignTests.Scenarios import models as m

XZ = App.Rotation(V(1, 0, 0), 90)  # a sketch placed so: its x is X, its y is Z


def freeSketch(doc, name, geometry, placement=None):
    """A sketch outside any Body, at `placement`."""
    sketch = doc.addObject("Sketcher::SketchObject", name)
    if placement is not None:
        sketch.Placement = placement
    sketch.addGeometry(geometry, False)
    return sketch


def PartPrimitives(make):
    """Part primitives with attachment.

    A Box 20 x 20 x 10 (0..20); a Cylinder, radius 3, height 8, attached to the box's top face
    with an attachment offset (5, 5, 0); a Part datum plane attached to the box's top face,
    offset 15 up; a Cone, radii 4 and 1, height 6, attached to the datum plane."""
    doc = make("PartPrimitives")
    box = m.box(doc, "Box", (20, 20, 10))
    doc.recompute()
    top = faceWhere(box.Shape, planeFacing(TOP, V(0, 0, 10)))
    cylinder = doc.addObject("Part::Cylinder", "Cylinder")
    cylinder.Radius = 3
    cylinder.Height = 8
    cylinder.AttachmentSupport = [(box, top)]
    cylinder.MapMode = "FlatFace"
    cylinder.AttachmentOffset = App.Placement(V(5, 5, 0), App.Rotation())
    datum = doc.addObject("Part::DatumPlane", "DatumPlane")
    datum.AttachmentSupport = [(box, top)]
    datum.MapMode = "FlatFace"
    datum.AttachmentOffset = App.Placement(V(0, 0, 15), App.Rotation())
    cone = doc.addObject("Part::Cone", "Cone")
    cone.Radius1 = 4
    cone.Radius2 = 1
    cone.Height = 6
    cone.AttachmentSupport = [(datum, "")]
    cone.MapMode = "FlatFace"
    doc.recompute()
    if abs(cone.Shape.BoundBox.ZMin - 25) > 1e-9:
        raise AssertionError(f"the cone starts at z {cone.Shape.BoundBox.ZMin}, expected 25")
    return {
        "volumes": {
            "Box": 4000,
            "Cylinder": math.pi * 9 * 8,
            "Cone": math.pi * 6 / 3 * (16 + 4 + 1),
        }
    }


def PartBooleans(make):
    """Part Booleans, and a Part Cut of two PartDesign Bodies.

    Cut: a 10 mm cube minus a cylinder, radius 2, through it at (5, 5). Fuse: two 10 mm cubes
    side by side (x 20..30 and 30..40), Refine on (one box, six faces). Common: a 10 mm cube
    at y 20..30 and another at (5, 25, 5) (a 5 mm cube). MultiFuse: three 10 mm cubes at x 0, 5
    and 10, y 40..50 (x 0..20). BodyCut: Body, a 20 x 10 x 10 block (y 60..70) minus Body001,
    a cylinder, radius 3, 10 high, at (10, 65)."""
    doc = make("PartBooleans")
    cube = m.box(doc, "Cube", (10, 10, 10))
    drill = doc.addObject("Part::Cylinder", "Drill")
    drill.Radius = 2
    drill.Height = 10
    drill.Placement = App.Placement(V(5, 5, 0), App.Rotation())
    cut = doc.addObject("Part::Cut", "Cut")
    cut.Base = cube
    cut.Tool = drill
    fuse = doc.addObject("Part::Fuse", "Fuse")
    fuse.Base = m.box(doc, "Left", (10, 10, 10), (20, 0, 0))
    fuse.Tool = m.box(doc, "Right", (10, 10, 10), (30, 0, 0))
    fuse.Refine = True
    common = doc.addObject("Part::Common", "Common")
    common.Base = m.box(doc, "CommonA", (10, 10, 10), (0, 20, 0))
    common.Tool = m.box(doc, "CommonB", (10, 10, 10), (5, 25, 5))
    multi = doc.addObject("Part::MultiFuse", "MultiFuse")
    multi.Shapes = [m.box(doc, f"Multi{i}", (10, 10, 10), (5 * i, 40, 0)) for i in range(3)]
    body = newBody(doc, "Body")
    block(body, 0, 60, 20, 70, 10)
    body2 = newBody(doc, "Body001")
    sketch = body2.newObject("Sketcher::SketchObject", "Sketch001")
    sketch.AttachmentSupport = [(m.originFeature(body2, "XY_Plane"), "")]
    sketch.MapMode = "FlatFace"
    sketch.addGeometry(m.circle(10, 65, 3), False)
    m.pad(body2, sketch, 10, "Pad001")
    bodyCut = doc.addObject("Part::Cut", "BodyCut")
    bodyCut.Base = body
    bodyCut.Tool = body2
    doc.recompute()
    if len(fuse.Shape.Faces) != 6:
        raise AssertionError(f"the refined Fuse has {len(fuse.Shape.Faces)} faces, expected 6")
    return {
        "volumes": {
            "Cut": 1000 - math.pi * 4 * 10,
            "Fuse": 2000,
            "Common": 125,
            "MultiFuse": 2000,
            "BodyCut": 2000 - math.pi * 9 * 10,
        }
    }


def PartProfiles(make):
    """Part profile features: Extrusion, Revolution, Mirroring.

    A sketch with a square 0..10 at z 0, extruded along Z, 10 in all, symmetric to its plane,
    with a 5 degree outward taper both ways (two square frustums, sides 10 and 10 + 10 tan 5,
    each 5 high); a sketch in the XZ plane with a rectangle x 20..25, z 0..5, revolved 360
    degrees about the Z axis (a ring, radii 20..25); the extrusion mirrored in the plane x = 30
    (normal X)."""
    doc = make("PartProfiles")
    square = freeSketch(doc, "Square", m.rectangle(0, 0, 10, 10))
    extrusion = doc.addObject("Part::Extrusion", "Extrusion")
    extrusion.Base = square
    extrusion.DirMode = "Custom"
    extrusion.Dir = V(0, 0, 1)
    extrusion.LengthFwd = 10
    extrusion.Symmetric = True
    extrusion.Solid = True
    extrusion.TaperAngle = 5
    extrusion.TaperAngleRev = 5
    section = freeSketch(
        doc, "Section", m.rectangle(20, 0, 25, 5), App.Placement(V(0, 0, 0), XZ)
    )
    revolution = doc.addObject("Part::Revolution", "Revolution")
    revolution.Source = section
    revolution.Axis = V(0, 0, 1)
    revolution.Base = V(0, 0, 0)
    revolution.Angle = 360
    revolution.Solid = True
    mirroring = doc.addObject("Part::Mirroring", "Mirroring")
    mirroring.Source = extrusion
    mirroring.Normal = V(1, 0, 0)
    mirroring.Base = V(30, 0, 0)
    doc.recompute()
    tapered = 2 * frustum(10, 10 + 10 * math.tan(math.radians(5)), 5)
    return {
        "volumes": {
            "Extrusion": tapered,
            "Revolution": math.pi * (625 - 400) * 5,
            "Mirroring": tapered,
        }
    }


def PartFilletChamfer(make):
    """Part Fillet and Chamfer on indexed edges of a Cut's result.

    A 20 x 20 x 10 box (0..20) with its corner x 10..20, y 10..20, z 5..10 cut away; a Fillet,
    radius 1, on the cut's inner vertical edge (x 10, y 10, z 5..10: a concave edge, so the
    fillet adds material); a Chamfer, size 1, on the box's top front edge (y 0, z 10). The edge
    indices are the Cut's, so they depend on the Boolean (3.2)."""
    doc = make("PartFilletChamfer")
    box = m.box(doc, "Box", (20, 20, 10))
    notch = m.box(doc, "Notch", (10, 10, 5), (10, 10, 5))
    cut = doc.addObject("Part::Cut", "Cut")
    cut.Base = box
    cut.Tool = notch
    doc.recompute()
    inner = int(edgeWhere(cut.Shape, lineThrough((10, 10, 5), (10, 10, 10)))[4:])
    front = int(edgeWhere(cut.Shape, lineThrough((0, 0, 10), (20, 0, 10)))[4:])
    fillet = doc.addObject("Part::Fillet", "Fillet")
    fillet.Base = cut
    fillet.Edges = [(inner, 1.0, 1.0)]
    chamfer = doc.addObject("Part::Chamfer", "Chamfer")
    chamfer.Base = cut
    chamfer.Edges = [(front, 1.0, 1.0)]
    doc.recompute()
    notched = 4000 - 500
    return {
        "volumes": {
            "Cut": notched,
            "Fillet": notched + (1 - math.pi / 4) * 5,
            "Chamfer": notched - 0.5 * 20,
        }
    }


def PartLoftSweep(make):
    """Part Loft and Sweep, a Compound and a non-parametric simple copy.

    Loft: ruled and solid, from a square 20 (centred) at z 0 to a square 10 at z 10 (a
    frustum). Sweep: a circle, radius 2, at (40, 0, 0) in the XY plane, swept along a quarter
    circle, radius 10, in the XZ plane from (40, 0, 0) up and over to (50, 0, 10), given as the
    spine sketch's edge (a link-sub), solid, Frenet (a quarter torus, Pappus). Compound: the
    loft and the sweep. SimpleCopy: a Part::Feature holding a copy of the loft's shape, moved to
    x 100 (only a saved shape: a recompute must leave it alone)."""
    doc = make("PartLoftSweep")
    bottom = freeSketch(doc, "Bottom", m.rectangle(-10, -10, 10, 10))
    top = freeSketch(
        doc, "Top", m.rectangle(-5, -5, 5, 5), App.Placement(V(0, 0, 10), App.Rotation())
    )
    loft = doc.addObject("Part::Loft", "Loft")
    loft.Sections = [bottom, top]
    loft.Solid = True
    loft.Ruled = True
    profile = freeSketch(doc, "Profile", [m.circle(40, 0, 2)])
    spine = freeSketch(
        doc,
        "Spine",
        [Part.ArcOfCircle(Part.Circle(V(50, 0, 0), V(0, 0, 1), 10), math.pi / 2, math.pi)],
        App.Placement(V(0, 0, 0), XZ),
    )
    sweep = doc.addObject("Part::Sweep", "Sweep")
    sweep.Sections = [profile]
    sweep.Spine = (spine, ["Edge1"])
    sweep.Solid = True
    sweep.Frenet = True
    compound = doc.addObject("Part::Compound", "Compound")
    compound.Links = [loft, sweep]
    doc.recompute()
    copy = doc.addObject("Part::Feature", "SimpleCopy")
    shape = loft.Shape.copy()
    shape.translate(V(100, 0, 0))
    copy.Shape = shape
    doc.recompute()
    loftVolume = frustum(20, 10, 10)
    sweepVolume = math.pi * 4 * (math.pi * 10 / 2)
    return {
        "volumes": {
            "Loft": loftVolume,
            "Sweep": sweepVolume,
            "Compound": loftVolume + sweepVolume,
            "SimpleCopy": loftVolume,
        }
    }


MODELS = [PartPrimitives, PartBooleans, PartProfiles, PartFilletChamfer, PartLoftSweep]
