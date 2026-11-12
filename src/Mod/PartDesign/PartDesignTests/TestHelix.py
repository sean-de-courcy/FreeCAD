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

from math import pi
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
        never merges toroidal faces, with or without the thread, so the bead keeps two of them.
        The refine's fallback after a thread merged them (review replc r2, T-A)."""
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
        self.assertEqual(len(tori), 2, [f.Area for f in tori])

    def tearDown(self):
        FreeCAD.closeDocument("PartDesignTestHelix")
