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

import unittest
import math

import FreeCAD
import TestSketcherApp
from PartDesignTests.Scenarios import harness

App = FreeCAD


class TestMultiTransform(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestMultiTransform")
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def testMultiTransform(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 10
        self.Doc.recompute()
        self.MultiTransform = self.Doc.addObject("PartDesign::MultiTransform", "MultiTransform")
        self.Doc.recompute()
        self.MultiTransform.Originals = [self.Pad]
        self.MultiTransform.Shape = self.Pad.Shape
        self.Body.addObject(self.MultiTransform)
        self.Doc.recompute()
        self.Mirrored = self.Doc.addObject("PartDesign::Mirrored", "Mirrored")
        self.Mirrored.MirrorPlane = (self.PadSketch, ["H_Axis"])
        self.Body.addObject(self.Mirrored)
        self.LinearPattern = self.Doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        self.LinearPattern.Direction = (self.PadSketch, ["H_Axis"])
        self.LinearPattern.Length = 20
        self.LinearPattern.Occurrences = 3
        self.Body.addObject(self.LinearPattern)
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Axis = (self.PadSketch, ["N_Axis"])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.Body.addObject(self.PolarPattern)
        self.MultiTransform.Transformations = [self.Mirrored, self.LinearPattern, self.PolarPattern]
        self.Doc.recompute()
        self.assertAlmostEqual(self.MultiTransform.Shape.Volume, 20000)

    def testMultiTransformDressup(self):
        # Arrange
        Doc = self.Doc
        Body = Doc.addObject("PartDesign::Body", "Body")
        Body.AllowCompound = False
        # Make first offset cube Pad
        PadSketch = Doc.addObject("Sketcher::SketchObject", "SketchPad")
        Body.addObject(PadSketch)
        xw = yw = zw = 10
        TestSketcherApp.CreateRectangleSketch(PadSketch, (0, 0), (xw, yw))
        Doc.recompute()
        Pad = Doc.addObject("PartDesign::Pad", "Pad")
        Body.addObject(Pad)
        Pad.Profile = PadSketch
        Pad.Length = zw
        Doc.recompute()
        MultiTransform = Doc.addObject("PartDesign::MultiTransform", "MultiTransform")
        Doc.recompute()
        MultiTransform.Originals = [Pad]
        MultiTransform.Shape = Pad.Shape
        Body.addObject(MultiTransform)
        Doc.recompute()
        Mirrored = Doc.addObject("PartDesign::Mirrored", "Mirrored")
        Mirrored.MirrorPlane = (Doc.getObject("XY_Plane"), [""])
        Mirrored.Refine = True
        Body.addObject(Mirrored)
        Mirrored2 = Doc.addObject("PartDesign::Mirrored", "Mirrored")
        Mirrored2.MirrorPlane = (Doc.getObject("XZ_Plane"), [""])
        Mirrored2.Refine = True
        Body.addObject(Mirrored2)
        MultiTransform.Transformations = [Mirrored, Mirrored2]
        MultiTransform.Refine = True
        Doc.recompute()
        Fillet = Doc.addObject("PartDesign::Fillet", "Fillet")
        Fillet.Base = (MultiTransform, ["Face1", "Face2"])
        radius = 3
        Fillet.Radius = radius
        Body.addObject(Fillet)
        # Broken out calculation of volume with two adjacent filleted faces = 5 long edges, 2 short edges,
        # 2 fully rounded corners and 4 corners with only 2 fillets meeting
        cubeVolume = xw * yw * zw * 2 * 2  # Mirrored and mirrored again.
        filletOuter = radius**2 * (xw - radius * 2)  # Volume of the rect prisms the fillets are in.
        filletCorner = radius**3  # Volume of the rect prism corners
        qRoundArea = math.pi * radius**2 / 4  # Area of the quarter round fillet profile
        filletPrism = qRoundArea * (xw - radius * 2)  # Volume of fillet minus corners
        fillet3Corner = (
            math.pi * radius**3 * 4 / 3 / 8
        )  # Volume of a fully rounded corner ( Sphere / 8 )
        fillet2Corner = radius**2 * 2  # Volume of corner with two fillets intersecting
        fillet1Corner = (
            math.pi * radius**2 / 4 * radius
        )  # Volume of corner with stopped single fillet
        extraFillet = qRoundArea * xw  # extra fillet in a mirrored direction
        filletOuterExt = radius**2 * 10  # extra rect prim surrounding fillet
        rectBox = (
            cubeVolume - (4 + 3) * (filletOuter + filletCorner) - 5 * filletOuterExt + filletCorner
        )
        fillets = (
            (4 + 3) * filletPrism
            + 5 * extraFillet
            + fillet3Corner * 2
            + fillet2Corner * 4
            + fillet1Corner * 0
        )
        volume = rectBox + fillets
        # Act
        Link = Doc.addObject("App::Link", "Link001")
        Link.setLink(Doc.Body)
        Link.Label = "Body001"
        Doc.recompute()
        # Assert
        self.assertAlmostEqual(abs(Body.Shape.Volume), volume, 6)
        self.assertAlmostEqual(abs(Link.Shape.Volume), volume, 6)

    def testMultiTransformBody(self):
        pass
        # TODO:  Someone who understands the second mode added to transform needs to
        #  write a test here.  Maybe close to  testMultiTransform but with
        #  self.Mirrored.TransformMode="Transform body"  instead of
        #  self.Mirrored.TransformMode="Transform tools"

    def testInstanceNumbersPerStep(self):
        """V2 numbers a MultiTransform's instances per step (ops#6): block (i, j) of LinX then
        LinY is `i:j`, so an edit of LinX's count leaves every other block's number alone."""
        if hasattr(self.Doc, "HistoryAlgorithm"):
            self.Doc.HistoryAlgorithm = "V2"
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 10
        multi = self.Doc.addObject("PartDesign::MultiTransform", "MultiTransform")
        multi.Originals = [box]
        multi.Refine = False
        body.addObject(multi)
        steps = []
        for name, axis, occurrences in (
            ("LinX", self.Doc.X_Axis, 3),
            ("LinY", self.Doc.Y_Axis, 2),
        ):
            step = self.Doc.addObject("PartDesign::LinearPattern", name)
            step.Direction = (axis, [""])
            step.Mode = "Spacing"
            step.Offset = 30
            step.Occurrences = occurrences
            body.addObject(step)
            steps.append(step)
        multi.Transformations = steps
        linX, linY = steps
        for xCount, yCount in ((3, 2), (2, 2), (3, 2), (3, 1), (3, 2), (1, 2), (3, 2)):
            linX.Occurrences = xCount
            linY.Occurrences = yCount
            self.Doc.recompute()
            self.assertEqual(
                harness.topFaceInstances(multi.Shape, 10),
                harness.gridInstances(xCount, yCount, 30, 10),
                f"LinX {xCount}, LinY {yCount}",
            )

    def newStepsBody(self):
        """A V2 body with a 10 x 10 x 10 box at the origin and a MultiTransform of it."""
        if hasattr(self.Doc, "HistoryAlgorithm"):
            self.Doc.HistoryAlgorithm = "V2"
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 10
        multi = self.Doc.addObject("PartDesign::MultiTransform", "MultiTransform")
        multi.Originals = [box]
        multi.Refine = False
        body.addObject(multi)
        return body, multi

    def newLinear(self, body, name, axis, occurrences, axis2=None, offset2=30, occurrences2=1):
        step = self.Doc.addObject("PartDesign::LinearPattern", name)
        step.Direction = (axis, [""])
        step.Mode = "Spacing"
        step.Offset = 30
        step.Occurrences = occurrences
        if axis2 is not None:
            step.Direction2 = (axis2, [""])
            step.Mode2 = "Spacing"
            step.Spacings2 = []  # a new pattern's is [0.0], a gap of 0 (ops#93)
            step.Offset2 = offset2
            step.Occurrences2 = occurrences2
        body.addObject(step)
        return step

    def testInstanceNumbersInnerDirection2(self):
        """The digits go by level (ops#6): every feature's first step, then their second steps.
        LinX (3 along X; Direction2 along Z) then LinY (2 along Y; Direction2 along X, 100
        apart, 2): block (a, b, x2, y2) is `a:b:x2:y2`, the trailing 1s left out. While LinX's
        Direction2 has one occurrence, its digit is a 1 in the middle (`2:2:1:2`), so giving it
        two renames none of the blocks there were: the new ones, 30 higher, are `a:b:2:y2`."""
        body, multi = self.newStepsBody()
        linX = self.newLinear(body, "LinX", self.Doc.X_Axis, 3, self.Doc.Z_Axis)
        linY = self.newLinear(body, "LinY", self.Doc.Y_Axis, 2, self.Doc.X_Axis, 100, 2)
        multi.Transformations = [linX, linY]

        def layer(x2):
            instances = {}
            for a in range(1, 4):
                for b in range(1, 3):
                    for y2 in range(1, 3):
                        digits = [a, b, x2, y2]
                        while digits and digits[-1] == 1:
                            digits.pop()
                        centre = (30.0 * (a - 1) + 100.0 * (y2 - 1) + 5, 30.0 * (b - 1) + 5)
                        instances[centre] = [":".join(map(str, digits))] if digits else []
            return instances

        for x2Count in (1, 2, 1):
            linX.Occurrences2 = x2Count
            self.Doc.recompute()
            self.assertEqual(
                harness.topFaceInstances(multi.Shape, 10), layer(1), f"Occurrences2 {x2Count}"
            )
            if x2Count == 2:
                self.assertEqual(harness.topFaceInstances(multi.Shape, 40), layer(2))

    def testInstanceNumbersMirroredStep(self):
        """A Mirrored feature is one step of 2 (ops#6): LinX (3) then a mirror in the XZ plane
        numbers the mirrored copy of block a `a:2`."""
        body, multi = self.newStepsBody()
        linX = self.newLinear(body, "LinX", self.Doc.X_Axis, 3)
        mirrored = self.Doc.addObject("PartDesign::Mirrored", "Mirrored")
        mirrored.MirrorPlane = (self.Doc.XZ_Plane, [""])
        body.addObject(mirrored)
        multi.Transformations = [linX, mirrored]
        self.Doc.recompute()
        expected = {}
        for a in range(1, 4):
            expected[(30.0 * (a - 1) + 5, 5.0)] = [str(a)] if a > 1 else []
            expected[(30.0 * (a - 1) + 5, -5.0)] = [f"{a}:2"]
        self.assertEqual(harness.topFaceInstances(multi.Shape, 10), expected)

    def testInstanceNumbersScaledStep(self):
        """A Scaled feature after another one scales the instances there are and adds no step
        (ops#6): LinX (3) then Scaled (factor 2, 3 occurrences) keeps the numbers `2` and `3`
        for blocks 2 and 3, now 15 and 20 high."""
        body, multi = self.newStepsBody()
        linX = self.newLinear(body, "LinX", self.Doc.X_Axis, 3)
        scaled = self.Doc.addObject("PartDesign::Scaled", "Scaled")
        scaled.Factor = 2
        scaled.Occurrences = 3
        body.addObject(scaled)
        multi.Transformations = [linX, scaled]
        self.Doc.recompute()
        tops = {}
        for z in (10, 12.5, 15):
            tops.update(harness.topFaceInstances(multi.Shape, z))
        self.assertEqual(sorted(tops.values()), [[], ["2"], ["3"]])

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestMultiTransform")
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "")
        # print ("omit closing document for debugging")
