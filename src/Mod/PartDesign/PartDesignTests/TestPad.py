# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import math
import unittest

import FreeCAD
import Part
from FreeCAD import Base
import TestSketcherApp


# A Pad made from two regions of a sketch (ops#125): a 30 x 20 x 2 plate, and two bosses of
# radius 2 and height 5 from a sketch at z = 2, each with a 0.5 fillet on its top edge.
REGIONS = ["InternalFace1", "InternalFace2"]
BOSS_RADIUS = 2.0
BOSS_HEIGHT = 5.0
BOSS_FILLET = 0.5
REGION_PAD_VOLUME = 30 * 20 * 2 + 2 * math.pi * BOSS_RADIUS**2 * BOSS_HEIGHT
# Each fillet removes the area between a square of side r and its quarter circle,
# r^2 (1 - pi/4), turned around the boss's axis at its centroid, r (10 - 3 pi) / (12 - 3 pi)
# inside the edge (Pappus).
REGION_FILLET_VOLUME = REGION_PAD_VOLUME - 2 * (
    2
    * math.pi
    * (BOSS_RADIUS - BOSS_FILLET * (10 - 3 * math.pi) / (12 - 3 * math.pi))
    * BOSS_FILLET**2
    * (1 - math.pi / 4)
)


def makeRegionPad(doc):
    """The ops#125 model in doc, with the bosses at (-5, 0) and (5, 0).
    Returns the boss sketch, the Pad made from its two regions, and the fillet."""
    body = doc.addObject("PartDesign::Body", "Body")
    xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
    plateSketch = body.newObject("Sketcher::SketchObject", "PlateSketch")
    plateSketch.AttachmentSupport = [(xy, "")]
    plateSketch.MapMode = "FlatFace"
    corners = [
        FreeCAD.Vector(-15, -10, 0),
        FreeCAD.Vector(15, -10, 0),
        FreeCAD.Vector(15, 10, 0),
        FreeCAD.Vector(-15, 10, 0),
    ]
    for i in range(4):
        plateSketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    plate = body.newObject("PartDesign::Pad", "Plate")
    plate.Profile = plateSketch
    plate.Length = 2
    sketch = body.newObject("Sketcher::SketchObject", "BossSketch")
    sketch.AttachmentSupport = [(xy, "")]
    sketch.MapMode = "FlatFace"
    sketch.AttachmentOffset = FreeCAD.Placement(FreeCAD.Vector(0, 0, 2), FreeCAD.Rotation())
    sketch.MakeInternals = True  # the regions (InternalFaceN)
    for x in (-5, 5):
        sketch.addGeometry(
            Part.Circle(FreeCAD.Vector(x, 0, 0), FreeCAD.Vector(0, 0, 1), BOSS_RADIUS)
        )
    doc.recompute()
    pad = body.newObject("PartDesign::Pad", "Bosses")
    pad.Profile = (sketch, REGIONS)
    pad.Length = BOSS_HEIGHT
    doc.recompute()
    fillet = body.newObject("PartDesign::Fillet", "Fillet")
    fillet.Base = (pad, bossTopEdges(pad))
    fillet.Radius = BOSS_FILLET
    doc.recompute()
    return sketch, pad, fillet


def redrawBosses(sketch):
    """Deletes the two circles and draws them again at (0, -5) and (0, 5): new geometry."""
    sketch.delGeometries([0, 1])
    for y in (-5, 5):
        sketch.addGeometry(
            Part.Circle(FreeCAD.Vector(0, y, 0), FreeCAD.Vector(0, 0, 1), BOSS_RADIUS)
        )


def bossTopEdges(pad):
    """The index names of the bosses' top circles."""
    top = 2 + BOSS_HEIGHT
    return [
        "Edge%d" % (i + 1)
        for i, e in enumerate(pad.Shape.Edges)
        if isinstance(e.Curve, Part.Circle)
        and abs(e.BoundBox.ZMin - top) < 1e-6
        and abs(e.BoundBox.ZMax - top) < 1e-6
    ]


def bossCentres(shape):
    """The (x, y) of each boss's axis, sorted."""
    return sorted(
        (round(f.Surface.Center.x, 6) + 0.0, round(f.Surface.Center.y, 6) + 0.0)
        for f in shape.Faces
        if isinstance(f.Surface, Part.Cylinder)
    )


class TestPad(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestPad")

    def testBoxCase(self):
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        TestSketcherApp.CreateSlotPlateSet(self.PadSketch)
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Doc.recompute()
        self.assertEqual(len(self.Pad.Shape.Faces), 6)

    def testSketchOnBasePlane(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.PadSketch.AttachmentSupport = (self.Doc.XY_Plane, [""])
        self.PadSketch.MapMode = "FlatFace"
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateSlotPlateSet(self.PadSketch)
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Body.addObject(self.Pad)
        self.Doc.recompute()
        self.assertEqual(len(self.Pad.Shape.Faces), 6)

    def testSketchOnDatumPlane(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.DatumPlane = self.Doc.addObject("PartDesign::Plane", "DatumPlane")
        self.DatumPlane.AttachmentSupport = (self.Doc.XY_Plane, [""])
        self.DatumPlane.MapMode = "FlatFace"
        self.Body.addObject(self.DatumPlane)
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.PadSketch.AttachmentSupport = (self.DatumPlane, [""])
        self.PadSketch.MapMode = "FlatFace"
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateSlotPlateSet(self.PadSketch)
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Body.addObject(self.Pad)
        self.Doc.recompute()
        self.assertEqual(len(self.Pad.Shape.Faces), 6)

    def testSketchAttachmentDoesNotImportExternalBody(self):
        source_body = self.Doc.addObject("PartDesign::Body", "SourceBody")
        source_box = source_body.newObject("PartDesign::AdditiveBox", "SourceBox")
        source_box.Length = 1
        source_box.Width = 1
        source_box.Height = 1

        target_body = self.Doc.addObject("PartDesign::Body", "TargetBody")
        sketch = target_body.newObject("Sketcher::SketchObject", "SketchPad")
        sketch.AttachmentSupport = (source_body, [""])
        sketch.MapMode = "ObjectXY"
        TestSketcherApp.CreateRectangleSketch(sketch, (2, 0), (1, 1))

        pad = target_body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 1
        self.Doc.recompute()

        self.assertIsNone(pad.BaseFeature)
        self.assertEqual(len(pad.Shape.Solids), 1)
        self.assertAlmostEqual(pad.Shape.Volume, 1)

    def testStartOffsetAndReference(self):
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (1, 1))
        self.Doc.recompute()

        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Pad.StartType = "Offset"
        self.Pad.StartOffset = 2
        self.Pad.Length = 3
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 2.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 5.0)

        reference = self.Doc.addObject("Part::Feature", "Reference")
        outer = Part.makeCylinder(2, 1, Base.Vector(0, 0, 10))
        inner = Part.makeCylinder(1, 1, Base.Vector(0, 0, 10))
        reference.Shape = outer.cut(inner)
        top_face = max(
            range(1, len(reference.Shape.Faces) + 1),
            key=lambda index: reference.Shape.Faces[index - 1].CenterOfMass.z,
        )
        self.Pad.StartReference = (reference, [f"Face{top_face}"])
        self.Pad.StartType = "Reference"
        self.Pad.StartOffset = 2
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 13.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 16.0)

    def testStartReferenceInternalSketchFace(self):
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (1, 1))
        self.Doc.recompute()

        reference = self.Doc.addObject("Sketcher::SketchObject", "Reference")
        reference.MakeInternals = True
        reference.Placement.Base = Base.Vector(0, 0, 10)
        TestSketcherApp.CreateRectangleSketch(reference, (0, 0), (1, 1))
        self.Doc.recompute()

        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 3
        self.Pad.StartReference = (reference, ["InternalFace1"])
        self.Pad.StartType = "Reference"
        self.Pad.StartOffset = 2
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 12.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 15.0)

    def testStartOffsetForTwoSidedAndSymmetricPad(self):
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (1, 1))
        self.Doc.recompute()

        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Pad.StartType = "Offset"
        self.Pad.StartOffset = 2
        self.Pad.SideType = "Two sides"
        self.Pad.Length = 1
        self.Pad.Length2 = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 1.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 3.0)

        self.Pad.SideType = "Symmetric"
        self.Pad.Length = 4
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 0.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 4.0)

    def testPadToFirstCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.Type = 2
        self.Pad1.Reversed = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 2.0)

    def testPadtoLastCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0.5, 1), (0.5, 2))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.Type = 1
        self.Pad1.Reversed = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 3.0)

    def testPadToFaceCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to face on first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.Type = 3
        self.Pad1.UpToFace = (self.Pad, ["Face3"])
        self.Pad1.Reversed = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 2.0)

    def testPadTwoDimensionsCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to face on first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.SideType = 1
        self.Pad1.Length = 1.0
        self.Pad1.Length2 = 2.0
        self.Pad1.Reversed = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 4.0)

    def testPadToConcaveCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make a half revolution
        self.RevolutionSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.RevolutionSketch)
        TestSketcherApp.CreateRectangleSketch(self.RevolutionSketch, (9, 0), (10, 5))
        self.Doc.recompute()
        self.Revolution = self.Doc.addObject("PartDesign::Revolution", "Revolution")
        self.Body.addObject(self.Revolution)
        self.Revolution.Profile = self.RevolutionSketch
        self.Revolution.ReferenceAxis = (self.RevolutionSketch, ["V_Axis"])
        self.Revolution.Angle = 180
        self.Doc.recompute()
        # Make a sketch and pad to first
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Type = 2
        self.Pad.Reversed = True
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.Volume, 2208.0963, places=4)

    def testPadToShapeCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.PadSketch1.AttachmentOffset.Rotation.Axis = Base.Vector(0, 1, 0)
        self.PadSketch1.AttachmentOffset.Rotation.Angle = 0.436332  # 25°
        self.PadSketch1.AttachmentOffset.Base.z = 1
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (1, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.Type = 5
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 2.58787, places=4)

    def testPadToPlaneCustomDir(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Type = 3
        self.Doc.Pad.UseCustomVector = True
        self.Doc.Pad.Direction = Base.Vector(0, 1, 1)
        self.Pad.UpToFace = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.Volume, 1.5)

    def _twoSidedUpToPad(self, side1, side2, taper1=0.0, sideType="Two sides"):
        """A 5 x 5 square on XY centred on the origin, padded with SideType `sideType`. A side is
        ("Length", <length>) or ("UpToFace", (<object>, <face>)). Side 1 goes +z, side 2 -z."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        body.addObject(sketch)
        TestSketcherApp.CreateRectangleSketch(sketch, (-2.5, -2.5), (5, 5))
        self.Doc.recompute()
        pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        body.addObject(pad)
        pad.Profile = sketch
        pad.SideType = sideType
        pad.TaperAngle = taper1
        for typeProp, lengthProp, faceProp, (kind, arg) in (
            ("Type", "Length", "UpToFace", side1),
            ("Type2", "Length2", "UpToFace2", side2),
        ):
            setattr(pad, typeProp, kind)
            if kind == "Length":
                setattr(pad, lengthProp, arg)
            else:
                setattr(pad, faceProp, (arg[0], [arg[1]]))
        self.Doc.recompute()
        return pad

    def testTwoSidedPadUpToFaceBehindSide(self):
        """ops#73: a side of a two-sided Pad whose up-to face lies behind it is an error naming
        that side. It used to be turned around silently, and the XOR of the sides then cancelled
        the overlap: an empty valid Pad, or one on the wrong side. One side still pads backwards
        to such a face, and a plane off to the side is still reached on the side's own side."""
        # Above: plane z = 10 (Face5, the bottom of a box at z 10..15). Below: plane z = -10
        # (Face6, the top of a box at z -15..-10). Wall: a box off to the side whose Face6 is
        # the plane z = -10, outside the profile's projection.
        top = self.Doc.addObject("Part::Box", "Above")
        top.Placement.Base = FreeCAD.Vector(-5, -5, 10)
        bottom = self.Doc.addObject("Part::Box", "Below")
        bottom.Placement.Base = FreeCAD.Vector(-5, -5, -15)
        wall = self.Doc.addObject("Part::Box", "Wall")
        wall.Placement.Base = FreeCAD.Vector(30, 0, -15)
        for box in (top, bottom, wall):
            box.Length, box.Width, box.Height = 10, 10, 5
        wall.Length = wall.Width = 5
        self.Doc.recompute()
        above = ("UpToFace", (top, "Face5"))
        below = ("UpToFace", (bottom, "Face6"))

        def assertBuilt(pad, volume, zmin, zmax):
            self.assertTrue(pad.isValid(), pad.getStatusString())
            self.assertAlmostEqual(pad.Shape.Volume, volume, places=4)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, zmin, places=6)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, zmax, places=6)

        with self.subTest("control: each face ahead of its side"):
            assertBuilt(self._twoSidedUpToPad(above, below), 25 * 20, -10, 10)
        with self.subTest("a plane off to the side is reached on side 2's side"):
            assertBuilt(self._twoSidedUpToPad(above, ("UpToFace", (wall, "Face6"))), 500, -10, 10)
        with self.subTest("one side pads backwards to a face behind it"):
            pad = self._twoSidedUpToPad(below, ("Length", 0.0), sideType="One side")
            assertBuilt(pad, 250, -10, 0)
        length5 = ("Length", 5.0)
        cases = (
            # (name, side 1, side 2, taper 1, the side named in the error)
            ("both to the face above (two prisms)", above, above, 0.0, "Side 2"),
            ("length, then to the face above (one prism)", length5, above, 0.0, "Side 2"),
            ("tapered length, then to the face above (two prisms)", length5, above, 1.0, "Side 2"),
            ("to the face below, then length (one prism)", below, length5, 0.0, "Side 1"),
        )
        for name, side1, side2, taper1, side in cases:
            with self.subTest(name):
                pad = self._twoSidedUpToPad(side1, side2, taper1)
                self.assertFalse(pad.isValid())
                self.assertIn(side + " can't reach its face", pad.getStatusString())

    def testTwoSidedPadUpToFaceInsideOtherSide(self):
        """ops#73 (option B): an up-to face between the sketch plane and the other side's end is
        an error naming the up-to side, with or without a taper. Without one, the Pad takes a
        one-prism path that starts the up-to side at the other side's end, and it used to build
        a cut-down Pad there (z 3..5 instead of an error). A face beyond the sketch plane still
        builds on both paths."""
        # Inside: plane z = 3 (Face5, the bottom of a box at z 3..8), within side 1 (Length 5).
        # InsideBelow: plane z = -3 (Face6, the top of a box at z -8..-3), within side 2.
        inside = self.Doc.addObject("Part::Box", "Inside")
        inside.Placement.Base = FreeCAD.Vector(-5, -5, 3)
        insideBelow = self.Doc.addObject("Part::Box", "InsideBelow")
        insideBelow.Placement.Base = FreeCAD.Vector(-5, -5, -8)
        for box in (inside, insideBelow):
            box.Length, box.Width, box.Height = 10, 10, 5
        self.Doc.recompute()
        length5 = ("Length", 5.0)
        toInside = ("UpToFace", (inside, "Face5"))
        toInsideBelow = ("UpToFace", (insideBelow, "Face6"))
        errors = (
            # (name, side 1, side 2, taper 1, the side named in the error)
            ("length, then to a face inside side 1 (one prism)", length5, toInside, 0.0, "Side 2"),
            ("tapered length, then to a face inside side 1 (two prisms)", length5, toInside, 1.0,
             "Side 2"),
            ("to a face inside side 2, then length (one prism)", toInsideBelow, length5, 0.0,
             "Side 1"),
        )
        for name, side1, side2, taper1, side in errors:
            with self.subTest(name):
                pad = self._twoSidedUpToPad(side1, side2, taper1)
                self.assertFalse(pad.isValid())
                self.assertIn(side + " can't reach its face", pad.getStatusString())
        with self.subTest("control: length, then to a face beyond the sketch plane (one prism)"):
            pad = self._twoSidedUpToPad(length5, toInsideBelow)
            self.assertTrue(pad.isValid(), pad.getStatusString())
            self.assertAlmostEqual(pad.Shape.Volume, 25 * 8, places=4)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, -3, places=6)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 5, places=6)
        with self.subTest("control: tapered length, then to a face beyond the sketch plane"):
            pad = self._twoSidedUpToPad(length5, toInsideBelow, 1.0)
            self.assertTrue(pad.isValid(), pad.getStatusString())
            box = pad.Shape.optimalBoundingBox(False, False)
            self.assertAlmostEqual(box.ZMin, -3, places=6)
            self.assertAlmostEqual(box.ZMax, 5, places=6)

    def testReselectedRegionsRepairThePad(self):
        """ops#125: a Pad made from two sketch regions breaks when the sketch's circles are
        drawn again elsewhere, and setting its Profile to the new regions repairs it. The fillet
        on it then breaks loudly. The property editor's link dialog sets the Profile this way
        (TestProfileLinkDialog checks the dialog)."""
        for solver in (True, False):
            with self.subTest(solver=solver):
                doc = FreeCAD.newDocument("PartDesignTestPadRegions")
                try:
                    if hasattr(doc, "ReferenceSolver"):
                        doc.ReferenceSolver = solver
                    sketch, pad, fillet = makeRegionPad(doc)
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    self.assertAlmostEqual(pad.Shape.Volume, REGION_PAD_VOLUME, places=4)
                    self.assertAlmostEqual(fillet.Shape.Volume, REGION_FILLET_VOLUME, places=4)

                    redrawBosses(sketch)
                    doc.recompute()
                    self.assertFalse(pad.isValid())
                    self.assertIn("InternalFace", pad.getStatusString())

                    pad.Profile = (sketch, REGIONS)
                    doc.recompute()
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    self.assertEqual(pad.Profile[1], REGIONS)
                    self.assertAlmostEqual(pad.Shape.Volume, REGION_PAD_VOLUME, places=4)
                    self.assertEqual(bossCentres(pad.Shape), [(0.0, -5.0), (0.0, 5.0)])
                    self.assertFalse(fillet.isValid())
                    self.assertIn("Edge", fillet.getStatusString())
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestPad")
        # print ("omit closing document for debugging")


class TestUpToPlanePlacement(unittest.TestCase):
    """A pad up to a plane that isn't a face (FreeCAD-CH ops#198): a 2 x 2 square at z = -3 in
    the body, padded up to the body's XY origin plane (12 mm^3), or up to a coordinate
    system's XY plane, the coordinate system at z = 7 in the body (40 mm^3; it was taken at
    z = 0), as the face or as the shape."""

    bodyPlacement = FreeCAD.Placement()

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestUpToPlane")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Body.Placement = self.bodyPlacement
        sketch = self.Body.newObject("Sketcher::SketchObject", "Square")
        sketch.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, -3), FreeCAD.Rotation())
        corners = [FreeCAD.Vector(x, y, 0) for x, y in ((0, 0), (2, 0), (2, 2), (0, 2))]
        sketch.addGeometry(
            [Part.LineSegment(p, q) for p, q in zip(corners, corners[1:] + corners[:1])], False
        )
        self.Pad = self.Body.newObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = sketch

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def xyPlane(self, coordinateSystem):
        [plane] = [f for f in coordinateSystem.OriginFeatures if f.Role == "XY_Plane"]
        return plane

    def coordinateSystemPlane(self):
        lcs = self.Doc.addObject("Part::LocalCoordinateSystem", "LCS")
        self.Body.addObject(lcs)
        lcs.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 7), FreeCAD.Rotation())
        return self.xyPlane(lcs)

    def assertVolume(self, volume):
        self.Doc.recompute()
        self.assertTrue(self.Pad.isValid(), self.Pad.getStatusString())
        self.assertAlmostEqual(self.Pad.Shape.Volume, volume, places=6)

    def testUpToOriginPlane(self):
        self.Pad.Type = "UpToFace"
        self.Pad.UpToFace = (self.xyPlane(self.Body.Origin), [""])
        self.assertVolume(12)

    def testUpToCoordinateSystemPlane(self):
        self.Pad.Type = "UpToFace"
        self.Pad.UpToFace = (self.coordinateSystemPlane(), [""])
        self.assertVolume(40)

    def testUpToCoordinateSystemPlaneAsShape(self):
        self.Pad.Type = "UpToShape"
        self.Pad.UpToShape = [(self.coordinateSystemPlane(), [""])]
        self.assertVolume(40)


class TestUpToPlanePlacementInAPlacedBody(TestUpToPlanePlacement):
    """The same in a body moved and turned: the same volumes."""

    bodyPlacement = FreeCAD.Placement(
        FreeCAD.Vector(5, -4, 9), FreeCAD.Rotation(FreeCAD.Vector(1, 1, 0), 30)
    )
