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

import os
import unittest

import FreeCAD
import Part
import Sketcher
import TestSketcherApp
from PartDesignTests.Scenarios import harness


class TestPolarPattern(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestPolarPattern")

    def testXAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Box]
        self.PolarPattern.Axis = (self.Doc.X_Axis, [""])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Box, FreeCAD.Vector(1, 0, 0))

    def testYAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Box]
        self.PolarPattern.Axis = (self.Doc.Y_Axis, [""])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Box, FreeCAD.Vector(0, 1, 0))

    def testZAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Box]
        self.PolarPattern.Axis = (self.Doc.Z_Axis, [""])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Box, FreeCAD.Vector(0, 0, 1))

    def testNormalSketchAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 10
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Pad]
        self.PolarPattern.Axis = (self.PadSketch, ["N_Axis"])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Pad, FreeCAD.Vector(0, 0, 1))

    def testVerticalSketchAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 10
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Pad]
        self.PolarPattern.Axis = (self.PadSketch, ["V_Axis"])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Pad, FreeCAD.Vector(0, 1, 0))

    def testHorizontalSketchAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 10
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Pad]
        self.PolarPattern.Axis = (self.PadSketch, ["H_Axis"])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Pad, FreeCAD.Vector(1, 0, 0))

    def checkPattern(self, original, axis):
        """The instances on the unrefined result, then the names of the refined one. Angle 360
        and 4 occurrences put the instances 90 degrees apart about the axis through the origin,
        one per quadrant."""
        pattern = self.PolarPattern
        placements = [
            FreeCAD.Placement(FreeCAD.Vector(), FreeCAD.Rotation(axis, 90.0 * k)) for k in range(4)
        ]
        with self.subTest("unrefined"):
            harness.assertEveryElementNamed(pattern.Shape)
            harness.assertInstancesDistinct(pattern.Shape, original.Shape, placements)
        pattern.Refine = True
        self.Doc.recompute()
        self.assertAlmostEqual(pattern.Shape.Volume, 4000)
        harness.assertEveryElementNamed(pattern.Shape)
        harness.assertDistinctNames(pattern.Shape)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestPolarPattern")
        # print ("omit closing document for debugging")


class TestPolarPatternOverlappingCuts(unittest.TestCase):
    """FreeCAD-CH ops#901: a polar pattern of a subtractive loft whose copies overlap their
    neighbours in a small wedge. Each loft ends "Normal to profile", so two neighbours' top faces
    are tangent at the corner and cross at well under a degree; OCCT 8.0.1 finds no curve for that
    crossing, and the one cut over all copies leaves an open shell that checkResult() refuses
    (fork-1.0.2: Invalid, "a shell's faces are not oriented consistently"). Onshape builds such a
    pattern, so the expected result is the plate less the union of the 8 cutouts. All dimensions
    are chosen here (notes/polar-pattern-901.md sections 5 and 9)."""

    plate = 40.0
    copies = 8

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestPolarPatternOverlappingCuts")
        self.recovery = os.environ.get("FREECAD_CH_CROSSING_RECOVERY")

    def tearDown(self):
        if self.recovery is None:
            os.environ.pop("FREECAD_CH_CROSSING_RECOVERY", None)
        else:
            os.environ["FREECAD_CH_CROSSING_RECOVERY"] = self.recovery
        FreeCAD.closeDocument(self.Doc.Name)

    def newDocument(self):
        FreeCAD.closeDocument(self.Doc.Name)
        self.Doc = FreeCAD.newDocument("PartDesignTestPolarPatternOverlappingCuts")

    def rectangle(self, name, placement, x0, x1, y0, y1):
        sketch = self.Doc.addObject("Sketcher::SketchObject", name)
        self.body.addObject(sketch)
        sketch.MapMode = "Deactivated"
        sketch.Placement = placement
        corners = [
            FreeCAD.Vector(x0, y0, 0),
            FreeCAD.Vector(x1, y0, 0),
            FreeCAD.Vector(x1, y1, 0),
            FreeCAD.Vector(x0, y1, 0),
        ]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        return sketch

    def makeModel(
        self,
        halfWidth,
        offset=FreeCAD.Vector(),
        outerY=-23.0,
        thickness=10.0,
        bottom=1.0,
        additive=False,
        pattern=True,
    ):
        """Plate 40 x 40 x thickness centred on offset; a loft from a section at outerY (x -6..6,
        z bottom..9) to one inside (x -halfWidth..halfWidth, z bottom..4 at y = -6), its inner
        end normal to the profile; 8 copies about the plate's axis. The 8-gon's half side at the
        inner end is 6 tan(22.5 deg) = 2.485: a wider inner end overlaps its neighbours."""
        self.offset = offset
        self.body = self.Doc.addObject("PartDesign::Body", "Body")
        half = self.plate / 2
        square = self.rectangle(
            "Square", FreeCAD.Placement(offset, FreeCAD.Rotation()), -half, half, -half, half
        )
        self.pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.body.addObject(self.pad)
        self.pad.Profile = square
        self.pad.Length = thickness
        self.pad.Refine = False
        upright = FreeCAD.Rotation(0, 0, 90)
        outer = self.rectangle(
            "Outer",
            FreeCAD.Placement(offset + FreeCAD.Vector(0, outerY, 0), upright),
            -6,
            6,
            bottom,
            9,
        )
        inner = self.rectangle(
            "Inner",
            FreeCAD.Placement(offset + FreeCAD.Vector(0, -6, 0), upright),
            -halfWidth,
            halfWidth,
            bottom,
            4,
        )
        kind = "PartDesign::AdditiveLoft" if additive else "PartDesign::SubtractiveLoft"
        self.loft = self.Doc.addObject(kind, "Loft")
        self.body.addObject(self.loft)
        self.loft.Profile = outer
        self.loft.Sections = [inner]
        self.loft.Ruled = False
        self.loft.EndCondition = "Normal to profile"
        self.loft.Refine = False
        self.Doc.recompute()
        self.assertTrue(self.loft.isValid(), self.loft.getStatusString())
        if not pattern:
            return
        # Set up before it joins the body (added the other way round it stays Touched)
        self.pattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.pattern.Originals = [self.loft]
        self.pattern.Axis = (square, ["N_Axis"])
        self.pattern.Angle = 360
        self.pattern.Occurrences = self.copies
        self.pattern.Refine = False
        self.body.addObject(self.pattern)
        self.Doc.recompute()

    def copy(self, k):
        """The loft's tool turned k eighths about the plate's axis"""
        copy = self.loft.AddSubShape.copy()
        # The tool is in the feature's frame
        copy.Placement = self.loft.Placement.multiply(copy.Placement)
        copy.rotate(self.offset, FreeCAD.Vector(0, 0, 1), 360.0 / self.copies * k)
        return copy

    def changedByEachCopy(self, cut=True):
        """The volume each of the 8 tools removes from (or adds to) the plate on its own"""
        plate = self.pad.Shape
        changed = []
        for k in range(self.copies):
            alone = plate.cut(self.copy(k)) if cut else plate.fuse(self.copy(k))
            changed.append(abs(alone.Volume - plate.Volume))
        return changed

    def assertUnionChanged(self, shape, each, overlaps):
        """The shape changed the plate by the union of the tools: the sum of what each changes
        alone where they don't overlap; where they do, less than the sum (each wedge counted
        once) by far less than one tool"""
        changed = abs(shape.Volume - self.pad.Shape.Volume)
        if not overlaps:
            self.assertAlmostEqual(changed / sum(each), 1, places=7)
        else:
            self.assertLess(changed, sum(each))
            self.assertGreater(changed, sum(each) - 0.05 * min(each))

    def assertSoundPattern(self, overlaps):
        """One valid solid centred on the axis (the square plate and the 8 copies share a
        quarter turn) that removed the union of the 8 cutouts"""
        shape = self.pattern.Shape
        self.assertTrue(self.pattern.isValid(), self.pattern.getStatusString())
        self.assertEqual(len(shape.Solids), 1)
        self.assertTrue(shape.isValid())
        centre = shape.Solids[0].CenterOfMass - self.offset
        self.assertAlmostEqual(centre.x / self.plate, 0, places=7)
        self.assertAlmostEqual(centre.y / self.plate, 0, places=7)
        self.assertUnionChanged(shape, self.changedByEachCopy(), overlaps)

    def testOverlappingCopiesAreCut(self):
        for halfWidth in (2.52, 2.6, 2.7, 2.8):
            with self.subTest(halfWidth=halfWidth):
                self.newDocument()
                self.makeModel(halfWidth)
                self.assertSoundPattern(overlaps=True)
                harness.assertEveryElementNamed(self.pattern.Shape)
                harness.assertDistinctNames(self.pattern.Shape)
                if halfWidth == 2.7:
                    # The copies cut one at a time give the same 58 faces (notes section 9.2);
                    # the same count on Windows and macOS (R4)
                    self.assertEqual(len(self.pattern.Shape.Faces), 58)

    def testCopiesApartAreCut(self):
        """The control: copies apart from each other (inner half width 2.0) build today"""
        self.makeModel(2.0)
        self.assertSoundPattern(overlaps=False)

    def testFarFromTheOrigin(self):
        """The same pattern 200 m away (OCCT intersects such faces moved near the origin) gives
        the same solid"""
        self.makeModel(2.7)
        volume = self.pattern.Shape.Volume
        area = self.pattern.Shape.Area
        self.newDocument()
        self.makeModel(2.7, offset=FreeCAD.Vector(2.0e5, -1.0e5, 0))
        self.assertSoundPattern(overlaps=True)
        self.assertAlmostEqual(self.pattern.Shape.Volume / volume, 1, places=8)
        self.assertAlmostEqual(self.pattern.Shape.Area / area, 1, places=8)

    def testAFarCopysFacesKeepTheirReferences(self):
        """Datum points on the faces of the far copy (it lies at y > 0), attached while the
        copies are apart (the one cut), stay on those faces once an edit makes the copies
        overlap (the cut made again with the crossings recovered), and after a further edit"""
        self.makeModel(2.0)
        self.assertSoundPattern(overlaps=False)
        points = []
        for index, face in enumerate(self.pattern.Shape.Faces):
            centre = face.CenterOfMass
            if centre.y > 7 and abs(centre.x) < 7:
                point = self.Doc.addObject("PartDesign::Point", "Point")
                self.body.addObject(point)
                point.AttachmentSupport = [(self.pattern, "Face%d" % (index + 1))]
                point.MapMode = "CenterOfMass"
                points.append((point, centre))
        self.assertEqual(len(points), 5)  # the floor, the two sides, the top, the wall's cut
        self.Doc.recompute()
        inner = self.Doc.getObject("Inner")
        for halfWidth in (2.7, 2.75):
            with self.subTest(halfWidth=halfWidth):
                for geometry, end, x, y in ((0, 1, -1, 1), (1, 1, 1, 1), (1, 2, 1, 4), (3, 1, -1, 4)):
                    inner.moveGeometry(
                        geometry, end, FreeCAD.Vector(x * halfWidth, y, 0), False
                    )
                self.Doc.recompute()
                self.assertSoundPattern(overlaps=True)
                for point, centre in points:
                    self.assertTrue(point.isValid(), point.getStatusString())
                    self.assertLess((point.Placement.Base - centre).Length, 1.0, point.Name)
                    if abs(centre.z - 1) < 1e-9:  # the floor stays on z = 1
                        self.assertAlmostEqual(point.Placement.Base.z, 1, places=7)

    def testOverlappingCutWithItsEndOnTheWall(self):
        """ops#904: two overlapping cutouts whose outer end lies on the plate's wall. OCCT's one
        cut removes one cutout's worth (silent); the recovery removes their union"""
        self.makeModel(2.7, outerY=-20.0, pattern=False)
        self.offset = FreeCAD.Vector()
        os.environ["FREECAD_CH_CROSSING_RECOVERY"] = "on"
        result = self.pad.Shape.cut([self.copy(0), self.copy(1)])
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        each = self.changedByEachCopy()[:2]
        self.assertUnionChanged(result, each, overlaps=True)

    def testOverlappingAdditiveCopiesAreFused(self):
        """ops#903: the additive twin on a thin plate. OCCT's one fuse returns an empty shape
        (silent); the recovery fuses the union"""
        self.makeModel(
            2.7, outerY=-18.0, thickness=0.5, bottom=0.25, additive=True, pattern=False
        )
        self.offset = FreeCAD.Vector()
        os.environ["FREECAD_CH_CROSSING_RECOVERY"] = "on"
        result = self.pad.Shape.fuse([self.copy(k) for k in range(self.copies)])
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertUnionChanged(result, self.changedByEachCopy(cut=False), overlaps=True)
