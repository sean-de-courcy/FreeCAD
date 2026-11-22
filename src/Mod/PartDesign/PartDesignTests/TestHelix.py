# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2023 Werner Mayer <wmayer[at]users.sourceforge.net>     *
# *   Copyright (c) 2023 <bgbsww@gmail.com>                                 *
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

from math import cos, pi, sin
import math
import unittest

import FreeCAD
from FreeCAD import Base
import Part
import Sketcher
import TestSketcherApp

""" Test various helixes """


class TestHelix(unittest.TestCase):
    """Test various helixes"""

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestHelix")

    def testHelicalTubeCase(self):
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        sketch.AttachmentSupport = (self.Doc.getObject("XY_Plane"), [""])
        sketch.MapMode = "FlatFace"

        geoList = []
        geoList.append(Part.Circle(Base.Vector(-40.0, 0.0, 0.0), Base.Vector(0.0, 0.0, 1.0), 7.5))
        geoList.append(Part.Circle(Base.Vector(-40.0, 0.0, 0.0), Base.Vector(0.0, 0.0, 1.0), 10.0))
        sketch.addGeometry(geoList, False)
        del geoList

        sketch.addConstraint(Sketcher.Constraint("PointOnObject", 0, 3, -1))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 1, 3, 0, 3))
        self.Doc.recompute()

        helix = body.newObject("PartDesign::AdditiveHelix", "AdditiveHelix")
        helix.Profile = sketch
        helix.ReferenceAxis = (sketch, ["V_Axis"])
        helix.Mode = 0
        helix.Pitch = 35
        helix.Height = 100
        helix.Turns = 3
        helix.Angle = 0
        helix.Growth = 0
        helix.LeftHanded = 0
        helix.Reversed = 0

        self.Doc.recompute()
        self.assertEqual(len(helix.Shape.Solids), 1)

    def testCircleQ1(self):
        """Test helix based on circle in Quadrant 1"""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        profileSketch = self.Doc.addObject("Sketcher::SketchObject", "ProfileSketch")
        body.addObject(profileSketch)
        TestSketcherApp.CreateCircleSketch(profileSketch, (2, 0), 1)
        self.Doc.recompute()
        helix = self.Doc.addObject("PartDesign::AdditiveHelix", "AdditiveHelix")
        body.addObject(helix)
        helix.Profile = profileSketch
        helix.ReferenceAxis = (profileSketch, "V_Axis")
        helix.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 0),
            FreeCAD.Vector(0, 0, 0),
        )
        helix.Pitch = 3
        helix.Height = 9
        helix.Turns = 2
        helix.Angle = 0
        helix.Mode = 1
        self.Doc.recompute()
        self.assertAlmostEqual(helix.Shape.Volume, 78.957, places=3)

        helix.Angle = 25
        self.Doc.recompute()
        self.assertAlmostEqual(helix.Shape.Volume, 134.17, places=2)

        profileSketch.addGeometry(
            Part.Circle(FreeCAD.Vector(2, 0, 0), FreeCAD.Vector(0, 0, 1), 0.5)
        )
        self.Doc.recompute()
        self.assertAlmostEqual(helix.Shape.Volume, 100.63, places=2)

    def testRectangle(self):
        """Test helix based on a rectangle"""
        body = self.Doc.addObject("PartDesign::Body", "GearBody")
        gearSketch = self.Doc.addObject("Sketcher::SketchObject", "GearSketch")
        body.addObject(gearSketch)
        TestSketcherApp.CreateRectangleSketch(gearSketch, (0, 0), (5, 5))
        self.Doc.recompute()

        # xz_plane = body.Origin.OriginFeatures[4]
        # coneSketch.AttachmentSupport = xz_plane
        # coneSketch.MapMode = 'FlatFace'
        helix = self.Doc.addObject("PartDesign::AdditiveHelix", "AdditiveHelix")
        body.addObject(helix)
        helix.Profile = gearSketch
        helix.ReferenceAxis = (gearSketch, "V_Axis")
        helix.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 0),
            FreeCAD.Vector(0, 0, 0),
        )

        helix.Pitch = 50
        helix.Height = 150
        helix.Turns = 3
        helix.Angle = 0
        helix.Mode = 0
        self.Doc.recompute()
        bbox = helix.Shape.BoundBox
        self.assertAlmostEqual(bbox.YMin, 0)
        # Computed exact value
        # with r = radius, l = length of square, t = turns
        # pi * r**2 * l * t
        expected = pi * 25 * 5 * 3
        self.assertAlmostEqual(helix.Shape.Volume, expected, places=2)

    def testGiantHelix(self):
        """Test giant helix"""
        _OCC_VERSION = [int(v) for v in Part.OCC_VERSION.split(".") if v.isnumeric()]
        if _OCC_VERSION[0] > 7 or (_OCC_VERSION[0] == 7 and _OCC_VERSION[1] > 3):
            mine = -1
            maxe = 10
        else:
            mine = -1
            maxe = 9
        for iexponent in range(mine, maxe):
            exponent = float(iexponent)
            body = self.Doc.addObject("PartDesign::Body", "GearBody")
            gearSketch = self.Doc.addObject("Sketcher::SketchObject", "GearSketch")
            body.addObject(gearSketch)
            TestSketcherApp.CreateRectangleSketch(
                gearSketch, (10 * (10**exponent), 0), (1 * (10**exponent), 1 * (10**exponent))
            )
            xz_plane = body.Origin.OriginFeatures[4]
            gearSketch.AttachmentSupport = xz_plane
            gearSketch.MapMode = "FlatFace"
            self.Doc.recompute()

            helix = self.Doc.addObject("PartDesign::AdditiveHelix", "AdditiveHelix")
            body.addObject(helix)
            helix.Profile = gearSketch
            helix.ReferenceAxis = (gearSketch, "V_Axis")
            helix.Placement = FreeCAD.Placement(
                FreeCAD.Vector(0, 0, 0),
                FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 0),
                FreeCAD.Vector(0, 0, 0),
            )

            helix.Pitch = 2 * (10**exponent)
            helix.Turns = 2
            helix.Height = helix.Turns * helix.Pitch
            helix.Angle = 0
            helix.Mode = 0
            self.Doc.recompute()

            self.assertTrue(helix.Shape.isValid())
            bbox = helix.Shape.BoundBox
            self.assertAlmostEqual(bbox.ZMin / ((10**exponent) ** 3), 0, places=4)
            # Computed exact value
            # with r = radius, l = length of square, t = turns
            # pi * r**2 * l * t
            expected = (
                pi
                * (((11 * (10**exponent)) ** 2) - ((10 * (10**exponent)) ** 2))
                * 1
                * (10**exponent)
                * helix.Turns
            )
            self.assertAlmostEqual(
                helix.Shape.Volume / ((10**exponent) ** 3),
                expected / ((10**exponent) ** 3),
                places=2,
            )

    def testGiantHelixAdditive(self):
        """Test giant helix added to Cylinder"""
        _OCC_VERSION = [int(v) for v in Part.OCC_VERSION.split(".") if v.isnumeric()]
        if _OCC_VERSION[0] > 7 or (_OCC_VERSION[0] == 7 and _OCC_VERSION[1] > 3):
            mine = -1
            maxe = 8
        else:
            mine = -1
            maxe = 6
        for iexponent in range(mine, maxe):
            exponent = float(iexponent)
            body = self.Doc.addObject("PartDesign::Body", "GearBody")
            gearSketch = self.Doc.addObject("Sketcher::SketchObject", "GearSketch")
            body.addObject(gearSketch)
            TestSketcherApp.CreateRectangleSketch(
                gearSketch, (10 * (10**exponent), 0), (1 * (10**exponent), 1 * (10**exponent))
            )
            xz_plane = body.Origin.OriginFeatures[4]
            gearSketch.AttachmentSupport = xz_plane
            gearSketch.MapMode = "FlatFace"
            self.Doc.recompute()

            cylinder = self.Doc.addObject("PartDesign::AdditiveCylinder", "Cylinder")
            cylinder.Radius = 10 * (10**exponent)
            cylinder.Height = 8 * (10**exponent)
            cylinder.Angle = 360
            body.addObject(cylinder)
            self.Doc.recompute()

            helix = self.Doc.addObject("PartDesign::AdditiveHelix", "AdditiveHelix")
            body.addObject(helix)
            helix.Profile = gearSketch
            helix.ReferenceAxis = (gearSketch, "V_Axis")
            helix.Placement = FreeCAD.Placement(
                FreeCAD.Vector(0, 0, 0),
                FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 0),
                FreeCAD.Vector(0, 0, 0),
            )

            helix.Pitch = 2 * (10**exponent)
            helix.Turns = 2.5  # workaround for OCCT bug with very large helices - full turns truncate the cylinder due to seam alignment
            helix.Height = helix.Turns * helix.Pitch
            helix.Angle = 0
            helix.Mode = 0
            helix.Tolerance = 0.12
            self.Doc.recompute()

            self.assertTrue(helix.Shape.isValid())
            bbox = helix.Shape.BoundBox
            self.assertAlmostEqual(bbox.ZMin / ((10**exponent) ** 3), 0, places=4)
            # Computed exact value
            # with r = radius, l = length of square, t = turns
            # pi * r**2 * l * t
            cyl = pi * ((10 * (10**exponent)) ** 2) * 8 * (10**exponent)
            expected = cyl + (
                pi
                * (((11 * (10**exponent)) ** 2) - ((10 * (10**exponent)) ** 2))
                * 1
                * (10**exponent)
                * helix.Turns
            )
            self.assertAlmostEqual(
                helix.Shape.Volume / ((10**exponent) ** 3),
                expected / ((10**exponent) ** 3),
                places=2,
            )

    def testGiantHelixSubtractive(self):
        """Test giant helix subtracted from Cylinder"""
        _OCC_VERSION = [int(v) for v in Part.OCC_VERSION.split(".") if v.isnumeric()]
        if _OCC_VERSION[0] > 7 or (_OCC_VERSION[0] == 7 and _OCC_VERSION[1] > 3):
            mine = -1
            maxe = 8
        else:
            mine = -1
            maxe = 6
        for iexponent in range(mine, maxe):
            exponent = float(iexponent)
            body = self.Doc.addObject("PartDesign::Body", "GearBody")
            gearSketch = self.Doc.addObject("Sketcher::SketchObject", "GearSketch")
            body.addObject(gearSketch)
            TestSketcherApp.CreateRectangleSketch(
                gearSketch, (10 * (10**exponent), 0), (1 * (10**exponent), 1 * (10**exponent))
            )
            xz_plane = body.Origin.OriginFeatures[4]
            gearSketch.AttachmentSupport = xz_plane
            gearSketch.MapMode = "FlatFace"
            self.Doc.recompute()

            cylinder = self.Doc.addObject("PartDesign::AdditiveCylinder", "Cylinder")
            cylinder.Radius = 11 * (10**exponent)
            cylinder.Height = 8 * (10**exponent)
            cylinder.Angle = 360
            body.addObject(cylinder)
            self.Doc.recompute()

            helix = self.Doc.addObject("PartDesign::SubtractiveHelix", "SubtractiveHelix")
            body.addObject(helix)
            helix.Profile = gearSketch
            helix.ReferenceAxis = (gearSketch, "V_Axis")
            helix.Placement = FreeCAD.Placement(
                FreeCAD.Vector(0, 0, 0),
                FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 0),
                FreeCAD.Vector(0, 0, 0),
            )

            helix.Pitch = 2 * (10**exponent)
            helix.Turns = 2.5  # workaround for OCCT bug with very large helices - full turns truncate the cylinder due to seam alignment
            helix.Height = helix.Turns * helix.Pitch
            helix.Angle = 0
            helix.Mode = 0
            self.Doc.recompute()

            self.assertTrue(helix.Shape.isValid())
            bbox = helix.Shape.BoundBox
            self.assertAlmostEqual(bbox.ZMin / ((10**exponent) ** 3), 0, places=4)
            # Computed exact value
            # with r = radius, l = length of square, t = turns
            # pi * r**2 * l * t
            cyl = pi * ((11 * (10**exponent)) ** 2) * 8 * (10**exponent)
            expected = cyl - (
                pi
                * (((11 * (10**exponent)) ** 2) - ((10 * (10**exponent)) ** 2))
                * 1
                * (10**exponent)
                * helix.Turns
            )
            self.assertAlmostEqual(
                helix.Shape.Volume / ((10**exponent) ** 3),
                expected / ((10**exponent) ** 3),
                places=2,
            )

    def testCone(self):
        """Test helix following a cone"""
        body = self.Doc.addObject("PartDesign::Body", "ConeBody")
        coneSketch = self.Doc.addObject("Sketcher::SketchObject", "ConeSketch")
        body.addObject(coneSketch)

        geoList = []
        geoList.append(Part.LineSegment(FreeCAD.Vector(-5, -5, 0), FreeCAD.Vector(-3, 0, 0)))
        geoList.append(Part.LineSegment(FreeCAD.Vector(-3, 0, 0), FreeCAD.Vector(-2, 0, 0)))
        geoList.append(Part.LineSegment(FreeCAD.Vector(-2, 0, 0), FreeCAD.Vector(-4, -5, 0)))
        geoList.append(Part.LineSegment(FreeCAD.Vector(-4, -5, 0), FreeCAD.Vector(-5, -5, 0)))
        l1, l2, l3, l4 = coneSketch.addGeometry(geoList)

        conList = []
        conList.append(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        conList.append(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        conList.append(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        conList.append(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        conList.append(Sketcher.Constraint("Horizontal", 1))
        conList.append(
            Sketcher.Constraint("Angle", l3, 1, -2, 2, FreeCAD.Units.Quantity("30.000000 deg"))
        )
        conList.append(Sketcher.Constraint("DistanceX", 1, 2, -5))
        conList.append(Sketcher.Constraint("DistanceY", 1, 2, 0))
        conList.append(Sketcher.Constraint("Equal", 0, 2))
        conList.append(Sketcher.Constraint("Equal", 1, 3))
        conList.append(Sketcher.Constraint("DistanceY", 0, 50))
        conList.append(Sketcher.Constraint("DistanceX", 1, 10))
        coneSketch.addConstraint(conList)

        xz_plane = body.Origin.OriginFeatures[4]
        coneSketch.AttachmentSupport = xz_plane
        coneSketch.MapMode = "FlatFace"
        helix = self.Doc.addObject("PartDesign::AdditiveHelix", "AdditiveHelix")
        body.addObject(helix)
        helix.Profile = coneSketch
        helix.ReferenceAxis = (coneSketch, "V_Axis")
        helix.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 0),
            FreeCAD.Vector(0, 0, 0),
        )

        helix.Pitch = 50
        helix.Height = 110
        helix.Turns = 2.2
        helix.Angle = 30
        helix.Mode = 0
        helix.Reversed = True
        self.Doc.recompute()
        self.assertAlmostEqual(helix.Shape.Volume / 1e5, 3.8828, places=4)

    def testNegativeCone(self):
        """Test helix following a cone with a negative angle"""
        body = self.Doc.addObject("PartDesign::Body", "ConeBody")
        coneSketch = self.Doc.addObject("Sketcher::SketchObject", "ConeSketch")
        body.addObject(coneSketch)

        geoList = []
        geoList.append(Part.LineSegment(FreeCAD.Vector(5, 5, 0), FreeCAD.Vector(3, 0, 0)))
        geoList.append(Part.LineSegment(FreeCAD.Vector(3, 0, 0), FreeCAD.Vector(2, 0, 0)))
        geoList.append(Part.LineSegment(FreeCAD.Vector(2, 0, 0), FreeCAD.Vector(4, 5, 0)))
        geoList.append(Part.LineSegment(FreeCAD.Vector(4, 5, 0), FreeCAD.Vector(5, 5, 0)))
        l1, l2, l3, l4 = coneSketch.addGeometry(geoList)

        conList = []
        conList.append(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        conList.append(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        conList.append(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        conList.append(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        conList.append(Sketcher.Constraint("Horizontal", 1))
        conList.append(Sketcher.Constraint("Angle", l3, 1, -2, 2, FreeCAD.Units.Quantity("30 deg")))
        conList.append(Sketcher.Constraint("DistanceX", 1, 2, -100))
        conList.append(Sketcher.Constraint("DistanceY", 1, 2, 0))
        conList.append(Sketcher.Constraint("Equal", 0, 2))
        conList.append(Sketcher.Constraint("Equal", 1, 3))
        conList.append(Sketcher.Constraint("DistanceY", 0, 50))
        conList.append(Sketcher.Constraint("DistanceX", 1, 10))
        coneSketch.addConstraint(conList)

        xz_plane = body.Origin.OriginFeatures[4]
        coneSketch.AttachmentSupport = xz_plane
        coneSketch.MapMode = "FlatFace"
        helix = self.Doc.addObject("PartDesign::AdditiveHelix", "AdditiveHelix")
        body.addObject(helix)
        helix.Profile = coneSketch
        helix.ReferenceAxis = (coneSketch, "V_Axis")

        helix.Pitch = 50
        helix.Height = 110
        helix.Angle = -30
        helix.Mode = 0
        helix.Reversed = False
        self.Doc.recompute()
        self.assertAlmostEqual(helix.Shape.Volume / 1e5, 6.0643, places=4)

    def testRefineAfterThreadMergesCoplanarFaces(self):
        """A refined feature after a thread merges coplanar neighbours, as Onshape does.

        A tube (r 10..20, height 8) carries an outer thread on r 20; a ring (r 20..23) padded down
        1 mm from the tube's top plane puts its top face beside the tube's. The two make one face
        r 10..23 at z = 8, area pi (23^2 - 10^2). The helix widens its edges' tolerance, and the
        refine kept the two faces apart, with no warning (rehearsal 5, rb43)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        planes = {f.Role: f for f in body.Origin.OriginFeatures}

        def annulus(name, r0, r1, z):
            sketch = body.newObject("Sketcher::SketchObject", name)
            sketch.AttachmentSupport = [(planes["XY_Plane"], "")]
            sketch.MapMode = "FlatFace"
            sketch.AttachmentOffset = FreeCAD.Placement(Base.Vector(0, 0, z), FreeCAD.Rotation())
            sketch.addGeometry(Part.Circle(Base.Vector(0, 0, 0), Base.Vector(0, 0, 1), r1))
            sketch.addGeometry(Part.Circle(Base.Vector(0, 0, 0), Base.Vector(0, 0, 1), r0))
            return sketch

        tube = body.newObject("PartDesign::Pad", "Tube")
        tube.Profile = annulus("TubeSketch", 10, 20, 0)
        tube.Length = 8
        profile = body.newObject("Sketcher::SketchObject", "ThreadProfile")
        profile.AttachmentSupport = [(planes["XZ_Plane"], "")]
        profile.MapMode = "FlatFace"
        corners = [Base.Vector(20, 1.0, 0), Base.Vector(20, 2.0, 0), Base.Vector(20.8, 1.5, 0)]
        for i in range(3):
            profile.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 3]))
        thread = body.newObject("PartDesign::AdditiveHelix", "Thread")
        thread.Profile = profile
        thread.ReferenceAxis = (planes["Z_Axis"], [""])
        thread.Mode = "pitch-height-angle"
        thread.Pitch = 2.5
        thread.Height = 4.0
        thread.Refine = True
        ring = body.newObject("PartDesign::Pad", "Ring")
        ring.Profile = annulus("RingSketch", 20, 23, 8)
        ring.Length = 1
        ring.Reversed = True
        ring.Refine = True
        self.Doc.recompute()

        self.assertTrue(ring.isValid(), ring.getStatusString())
        self.assertTrue(ring.Shape.isValid())
        top = [
            f
            for f in ring.Shape.Faces
            if f.Surface.__class__.__name__ == "Plane"
            and abs(f.BoundBox.ZMin - 8) < 1e-7
            and abs(f.BoundBox.ZMax - 8) < 1e-7
        ]
        self.assertEqual(len(top), 1, [f.Area for f in top])
        self.assertAlmostEqual(top[0].Area, pi * (23**2 - 10**2), places=6)

    def testRefineAfterThreadKeepsTorusHalvesApart(self):
        """The refine after a thread merges only what it merges without one.

        A tube (r 10..20, height 8) carries an outer thread; two refined AdditiveTorus halves
        (R 15, r 3, 180 degrees each, turned 180 degrees apart) sit on its top. The face uniter
        merges the two halves into one ring, as Onshape does (ops#931), with or without the thread;
        the refine's fallback after a thread once merged them alone (review replc r2, T-A)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        planes = {f.Role: f for f in body.Origin.OriginFeatures}
        sketch = body.newObject("Sketcher::SketchObject", "TubeSketch")
        sketch.AttachmentSupport = [(planes["XY_Plane"], "")]
        sketch.MapMode = "FlatFace"
        sketch.addGeometry(Part.Circle(Base.Vector(0, 0, 0), Base.Vector(0, 0, 1), 20))
        sketch.addGeometry(Part.Circle(Base.Vector(0, 0, 0), Base.Vector(0, 0, 1), 10))
        tube = body.newObject("PartDesign::Pad", "Tube")
        tube.Profile = sketch
        tube.Length = 8
        profile = body.newObject("Sketcher::SketchObject", "ThreadProfile")
        profile.AttachmentSupport = [(planes["XZ_Plane"], "")]
        profile.MapMode = "FlatFace"
        corners = [Base.Vector(20, 1.0, 0), Base.Vector(20, 2.0, 0), Base.Vector(20.8, 1.5, 0)]
        for i in range(3):
            profile.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 3]))
        thread = body.newObject("PartDesign::AdditiveHelix", "Thread")
        thread.Profile = profile
        thread.ReferenceAxis = (planes["Z_Axis"], [""])
        thread.Mode = "pitch-height-angle"
        thread.Pitch = 2.5
        thread.Height = 4.0
        thread.Refine = True
        for i, angle in enumerate((0, 180)):
            bead = body.newObject("PartDesign::AdditiveTorus", "Bead%d" % i)
            bead.Radius1 = 15
            bead.Radius2 = 3
            bead.Angle3 = 180
            bead.Placement = FreeCAD.Placement(
                Base.Vector(0, 0, 8), FreeCAD.Rotation(Base.Vector(0, 0, 1), angle)
            )
            bead.Refine = True
        self.Doc.recompute()

        self.assertTrue(bead.isValid(), bead.getStatusString())
        tori = [f for f in bead.Shape.Faces if f.Surface.__class__.__name__ == "Toroid"]
        self.assertEqual(len(tori), 1, [f.Area for f in tori])

    def testRefineAfterThreadLeavesAPointedConeAsWithout(self):
        """A pointed cone the face uniter leaves in pieces stays so after a thread (ops#931).

        The tube and thread of the test above; on its top a pointed AdditiveCone (r 15, height 10)
        and the same cone over 90 degrees, refined. The face uniter refuses a cone group whose
        boundary runs to the apex, so without the thread the cone keeps two faces. The thread sends
        the refine to its UnifySameDomain fallback, which merged them (review pri931-r1, F1):
        suppressing the thread then turned one face into two and broke a reference to it."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        planes = {f.Role: f for f in body.Origin.OriginFeatures}
        sketch = body.newObject("Sketcher::SketchObject", "TubeSketch")
        sketch.AttachmentSupport = [(planes["XY_Plane"], "")]
        sketch.MapMode = "FlatFace"
        sketch.addGeometry(Part.Circle(Base.Vector(0, 0, 0), Base.Vector(0, 0, 1), 20))
        sketch.addGeometry(Part.Circle(Base.Vector(0, 0, 0), Base.Vector(0, 0, 1), 10))
        tube = body.newObject("PartDesign::Pad", "Tube")
        tube.Profile = sketch
        tube.Length = 8
        profile = body.newObject("Sketcher::SketchObject", "ThreadProfile")
        profile.AttachmentSupport = [(planes["XZ_Plane"], "")]
        profile.MapMode = "FlatFace"
        corners = [Base.Vector(20, 1.0, 0), Base.Vector(20, 2.0, 0), Base.Vector(20.8, 1.5, 0)]
        for i in range(3):
            profile.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 3]))
        thread = body.newObject("PartDesign::AdditiveHelix", "Thread")
        thread.Profile = profile
        thread.ReferenceAxis = (planes["Z_Axis"], [""])
        thread.Mode = "pitch-height-angle"
        thread.Pitch = 2.5
        thread.Height = 4.0
        thread.Refine = True
        for i, sweep in enumerate((360, 90)):
            cone = body.newObject("PartDesign::AdditiveCone", "Cone%d" % i)
            cone.Radius1 = 15
            cone.Radius2 = 0
            cone.Height = 10
            cone.Angle = sweep
            cone.Placement = FreeCAD.Placement(Base.Vector(0, 0, 8), FreeCAD.Rotation())
            cone.Refine = True
        self.Doc.recompute()

        def cones():
            self.assertTrue(cone.isValid(), cone.getStatusString())
            return [f for f in cone.Shape.Faces if f.Surface.__class__.__name__ == "Cone"]

        withThread = cones()
        self.assertEqual(len(withThread), 2, [f.Area for f in withThread])
        self.assertAlmostEqual(sum(f.Area for f in withThread), math.pi * 15 * math.hypot(15, 10), delta=1e-6)
        thread.Suppressed = True
        self.Doc.recompute()
        self.assertEqual(len(cones()), 2)

    def testRefineKeepsThreadWallWithinOnePeriod(self):
        """The refine keeps a threaded wall's faces within one turn, so booleans see them.

        A tube (r 75.5..76.5, height 6.6, its seam turned 50 degrees) carries an outer thread of
        2.64 turns that runs past both of the tube's ends. Refined, the face uniter merged the
        wall between the turns into one cylinder face spanning 3.36 periods with no seam edge.
        OCCT projects a point to the principal period, finds it outside such a face, and drops
        the face's sections: a box half in the wall then overlapped the whole of itself (the
        native replica's #30 revolved a thread's cap across such a wall and overlapped nothing).
        Expected: each wall face spans at most one period; a box straddling the wall between
        the turns overlaps the part as it overlaps the plain tube; the volume is the tube's plus
        the profile's area swept round its centroid (Pappus), the profile touching the wall."""
        r, height, z0, pitch = 76.5, 6.6, -0.3, 2.5
        tube = Part.makeCylinder(r, height).cut(Part.makeCylinder(r - 1, height))
        tube.rotate(Base.Vector(0, 0, 0), Base.Vector(0, 0, 1), 50)
        base = self.Doc.addObject("Part::Feature", "Tube")
        base.Shape = tube
        body = self.Doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = base
        planes = {f.Role: f for f in body.Origin.OriginFeatures}
        profile = body.newObject("Sketcher::SketchObject", "ThreadProfile")
        profile.AttachmentSupport = [(planes["XZ_Plane"], "")]
        profile.MapMode = "FlatFace"
        corners = [(r, z0), (r, z0 + 0.7), (r + 0.75, z0 + 0.1), (r + 0.8, z0)]
        for i in range(4):
            (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 4]
            profile.addGeometry(Part.LineSegment(Base.Vector(x1, y1, 0), Base.Vector(x2, y2, 0)))
        thread = body.newObject("PartDesign::AdditiveHelix", "Thread")
        thread.Profile = profile
        thread.ReferenceAxis = (planes["Z_Axis"], [""])
        thread.Mode = "pitch-height-angle"
        thread.Pitch = pitch
        thread.Height = height
        thread.Refine = True
        self.Doc.recompute()

        self.assertTrue(thread.isValid(), thread.getStatusString())
        shape = thread.Shape
        self.assertTrue(shape.isValid())
        walls = [
            f
            for f in shape.Faces
            if f.Surface.__class__.__name__ == "Cylinder" and abs(f.Surface.Radius - r) < 1e-9
        ]
        spans = [f.ParameterRange[1] - f.ParameterRange[0] for f in walls]
        self.assertTrue(all(s <= 2 * pi + 1e-9 for s in spans), spans)
        wrong = []
        for k in range(12):
            phi = 2 * pi * k / 12
            for turn in range(2):
                z = z0 + 1.6 + pitch * (phi / (2 * pi) + turn)
                if z > height - 0.5:
                    continue
                center = Base.Vector(r * cos(phi), r * sin(phi), z)
                box = Part.makeBox(0.4, 0.4, 0.4, center - Base.Vector(0.2, 0.2, 0.2))
                expected, got = box.common(tube).Volume, box.common(shape).Volume
                if abs(expected - got) > 1e-7:
                    wrong.append((k * 30, turn, got, expected))
        self.assertEqual(wrong, [])
        area = centroid = 0.0
        for i in range(4):
            (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 4]
            cross = x1 * y2 - x2 * y1
            area += cross / 2
            centroid += (x1 + x2) * cross / 6
        centroid /= area
        volume = pi * (r**2 - (r - 1) ** 2) * height + abs(area) * 2 * pi * centroid * height / pitch
        self.assertAlmostEqual(shape.Volume, volume, delta=5e-4)

    # ops#895: a helix has one face per profile edge, as Onshape's (a 10-turn thread there has 9
    # faces in all), not one per turn. A tube r 10..20 carries a triangular thread profile
    # (r 20, z 5) .. (r 20, z 6) .. (r 20.8, z 5.5) on its wall, pitch 2.5; the edge on the wall
    # sweeps into the wall, so the thread shows two flanks. The thread's volume is the profile's
    # area swept round its centroid (Pappus): 0.4 * 2 pi * 20.2667 per turn.
    THREAD = [(20.0, 5.0), (20.0, 6.0), (20.8, 5.5)]
    THREAD_AREA = 0.4
    THREAD_CENTROID = (20.0 + 20.0 + 20.8) / 3

    def makeThread(self, turns, height=40.0, kind="PartDesign::AdditiveHelix", tube=True, refine=False, reversed_=False):
        body = self.Doc.addObject("PartDesign::Body", "Body")
        planes = {f.Role: f for f in body.Origin.OriginFeatures}
        if tube:
            base = self.Doc.addObject("Part::Feature", "Tube")
            base.Shape = Part.makeCylinder(20, height).cut(Part.makeCylinder(10, height))
            body.BaseFeature = base
        profile = body.newObject("Sketcher::SketchObject", "ThreadProfile")
        profile.AttachmentSupport = [(planes["XZ_Plane"], "")]
        profile.MapMode = "FlatFace"
        corners = list(self.THREAD)
        if kind == "PartDesign::SubtractiveHelix":
            corners[2] = (19.2, 5.5)
        for i in range(3):
            (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 3]
            profile.addGeometry(Part.LineSegment(Base.Vector(x1, y1, 0), Base.Vector(x2, y2, 0)))
        thread = body.newObject(kind, "Thread")
        thread.Profile = profile
        thread.ReferenceAxis = (planes["Z_Axis"], [""])
        thread.Mode = "pitch-turns-angle"
        thread.Pitch = 2.5
        thread.Turns = turns
        thread.Refine = refine
        thread.Reversed = reversed_
        self.Doc.recompute()
        self.assertTrue(thread.isValid(), thread.getStatusString())
        self.assertTrue(thread.Shape.isValid())
        return thread

    def faceKinds(self, shape):
        kinds = {}
        for f in shape.Faces:
            kinds.setdefault(f.Surface.__class__.__name__, []).append(f)
        return kinds

    def threadVolume(self, turns):
        return self.THREAD_AREA * 2 * pi * self.THREAD_CENTROID * turns

    def testThreadHasOneFacePerProfileEdge(self):
        """A thread over several turns has one face per flank, with Refine on or off (ops#895).

        Before, each turn had its own two flank faces (3.4 turns: 8, 10 turns: 21). The wall
        stays one cylinder face per turn: a cylinder face over more than one period breaks
        OCCT's booleans (testRefineKeepsThreadWallWithinOnePeriod)."""
        tube = pi * (20**2 - 10**2) * 40
        for turns in (1, 2, 3.4, 5, 10):
            for refine in (False, True):
                with self.subTest(turns=turns, refine=refine):
                    thread = self.makeThread(turns, refine=refine)
                    kinds = self.faceKinds(thread.Shape)
                    self.assertEqual(len(kinds.get("BSplineSurface", [])), 2)
                    self.assertEqual(len(kinds.get("Plane", [])), 4)
                    walls = [f for f in kinds.get("Cylinder", []) if abs(f.Surface.Radius - 20) < 1e-9]
                    spans = [f.ParameterRange[1] - f.ParameterRange[0] for f in walls]
                    self.assertTrue(all(s <= 2 * pi + 1e-6 for s in spans), spans)
                    self.assertAlmostEqual(
                        thread.Shape.Volume, tube + self.threadVolume(turns), delta=5e-3
                    )
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestHelix")

    def testHelixAloneHasOneFacePerProfileEdge(self):
        """A helix with no base has one face per profile edge and its two caps (ops#895)."""
        thread = self.makeThread(3.4, tube=False)
        kinds = self.faceKinds(thread.Shape)
        self.assertEqual(len(thread.Shape.Faces), 5)
        self.assertEqual(len(kinds.get("BSplineSurface", [])), 3)
        self.assertAlmostEqual(thread.Shape.Volume, self.threadVolume(3.4), delta=1e-3)

    def testThreadRunningOutOfThePartHasOneFacePerProfileEdge(self):
        """A thread that runs out through the tube's top or bottom face (ops#895).

        Beyond the tube the profile's edge on the wall shows as the thread's inner face, so the
        thread has one face per profile edge, three: up 5 turns from z 5 on a tube 10 high, and
        Reversed, down 3.4 turns from z 5 on a tube 30 high. The whole thread adds to the tube."""
        for turns, height, reversed_ in ((5, 10.0, False), (3.4, 30.0, True)):
            with self.subTest(reversed=reversed_):
                thread = self.makeThread(turns, height=height, reversed_=reversed_)
                kinds = self.faceKinds(thread.Shape)
                self.assertEqual(len(kinds.get("BSplineSurface", [])), 3)
                self.assertAlmostEqual(
                    thread.Shape.Volume,
                    pi * (20**2 - 10**2) * height + self.threadVolume(turns),
                    delta=5e-3,
                )
            FreeCAD.closeDocument(self.Doc.Name)
            self.Doc = FreeCAD.newDocument("PartDesignTestHelix")

    def testGrooveHasOneFacePerProfileEdge(self):
        """A subtractive helix cut into a wall leaves one face per flank (ops#895)."""
        thread = self.makeThread(3.4, kind="PartDesign::SubtractiveHelix")
        kinds = self.faceKinds(thread.Shape)
        self.assertEqual(len(kinds.get("BSplineSurface", [])), 2)
        centroid = (20.0 + 20.0 + 19.2) / 3
        groove = self.THREAD_AREA * 2 * pi * centroid * 3.4
        self.assertAlmostEqual(thread.Shape.Volume, pi * (20**2 - 10**2) * 40 - groove, delta=5e-3)

    def testThreadFacesKeepTheirNamesWhenTheTurnsChange(self):
        """A flank's and an end cap's names don't depend on the number of turns (ops#895).

        Before, a flank was one face per turn, named by its turn, and the names of the last
        turn's faces moved with Turns."""
        thread = self.makeThread(3.4)

        def names():
            shape = thread.Shape
            found = {}
            for i, f in enumerate(shape.Faces, 1):
                kind = f.Surface.__class__.__name__
                # the flanks, and the thread's caps: planes through the axis
                if kind == "BSplineSurface" or (
                    kind == "Plane" and abs(f.Surface.Axis.z) < 1e-9
                ):
                    mapped = shape.ElementReverseMap.get("Face%d" % i)
                    found.setdefault(kind, set()).add(mapped if isinstance(mapped, str) else mapped[0])
            return found

        before = names()
        self.assertEqual(len(before["BSplineSurface"]), 2)
        self.assertEqual(len(before["Plane"]), 2)
        for turns in (5, 2.2):
            thread.Turns = turns
            self.Doc.recompute()
            self.assertTrue(thread.isValid(), thread.getStatusString())
            self.assertEqual(names(), before, turns)

    def testThreadStandsLaterBooleans(self):
        """Booleans after a thread of ten turns, whose flanks are one face each (ops#895).

        A coaxial cut through the crests at r 20.5, a Common with a cylinder r 20.6 and an axial
        slot across every turn: each result is valid, and the volumes are the exact ones. The
        crest cut removes the profile's part beyond r 20.5 (a triangle 0.375 x 0.3, its centroid
        at r 20.6) over ten turns; the Common keeps the tube and the profile's part within r 20.6
        (all but a triangle 0.25 x 0.2, centroid at r 20.6667). The bound is about 1e-4 of the
        material the crest cut removes: a face over many turns intersects a little less exactly
        than one over one turn (0.03 against 0.004 for the per-turn faces before)."""
        turns = 10
        thread = self.makeThread(turns)
        shape = thread.Shape
        tube = pi * (20**2 - 10**2) * 40
        crest = Part.makeCylinder(30, 42, Base.Vector(0, 0, -1)).cut(
            Part.makeCylinder(20.5, 42, Base.Vector(0, 0, -1))
        )
        cut = shape.cut(crest)
        self.assertTrue(cut.isValid())
        removed = 0.5 * 0.375 * 0.3 * 2 * pi * 20.6 * turns
        self.assertAlmostEqual(shape.Volume - cut.Volume, removed, delta=0.05)
        common = shape.common(Part.makeCylinder(20.6, 42, Base.Vector(0, 0, -1)))
        self.assertTrue(common.isValid())
        kept = tube + self.threadVolume(turns) - 0.5 * 0.25 * 0.2 * 2 * pi * (20.6 + 0.2 / 3) * turns
        self.assertAlmostEqual(common.Volume, kept, delta=0.05)
        slot = Part.makeBox(4, 30, 42, Base.Vector(-2, 0, -1))
        slotted, inside = shape.cut(slot), shape.common(slot)
        self.assertTrue(slotted.isValid())
        self.assertTrue(inside.isValid())
        self.assertAlmostEqual(slotted.Volume + inside.Volume, shape.Volume, delta=1e-3)

    def tearDown(self):
        FreeCAD.closeDocument("PartDesignTestHelix")
