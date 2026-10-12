# SPDX-License-Identifier: LGPL-2.1-or-later

# **************************************************************************
#   Copyright (c) 2024 Syres                                               *
#                                                                          *
#   This file is part of the FreeCAD CAx development system.               *
#                                                                          *
#   FreeCAD is free software: you can redistribute it and/or modify it     *
#   under the terms of the GNU Lesser General Public License as            *
#   published by the Free Software Foundation, either version 2.1 of the   *
#   License, or (at your option) any later version.                        *
#                                                                          *
#   FreeCAD is distributed in the hope that it will be useful, but         *
#   WITHOUT ANY WARRANTY; without even the implied warranty of             *
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
#   Lesser General Public License for more details.                        *
#                                                                          *
#   You should have received a copy of the GNU Lesser General Public       *
#   License along with FreeCAD. If not, see                                *
#   <https://www.gnu.org/licenses/>.                                       *
# **************************************************************************

import math
import unittest
import FreeCAD
import Part
import Sketcher
from FreeCAD import Vector

App = FreeCAD


class TestSketchValidateCoincidents(unittest.TestCase):
    """Sketch validation test"""

    def setUp(self):
        self.Doc = FreeCAD.newDocument("SketchValidateCoincidentsTest")

    def testSingleMissingCoincidentCase(self):
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        v0 = Vector(-47.680691, 18.824165000000004, 0.0)
        v1 = Vector(-47.680691, -27.346279, 0.0)
        v2 = Vector(51.132679, -27.346279, 0.0)
        v3 = Vector(51.132679, 18.824165000000004, 0.0)
        v4 = Vector(51.132679, 18.824165, 0.0)
        v5 = Vector(-47.680691, 18.824165, 0.0)

        geo0 = sketch.addGeometry(Part.LineSegment(v0, v1))
        geo1 = sketch.addGeometry(Part.LineSegment(v1, v2))
        geo2 = sketch.addGeometry(Part.LineSegment(v2, v3))
        geo3 = sketch.addGeometry(Part.LineSegment(v4, v5))

        sketch.addConstraint(Sketcher.Constraint("Coincident", geo0, 2, geo1, 1))
        sketch.addConstraint(Sketcher.Constraint("Coincident", geo1, 2, geo2, 1))
        sketch.addConstraint(Sketcher.Constraint("Vertical", geo0))
        sketch.addConstraint(Sketcher.Constraint("Vertical", geo2))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", geo1))
        sketch.addConstraint(Sketcher.Constraint("Coincident", geo3, 1, geo2, 2))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", geo3))
        self.Doc.recompute()
        self.assertEqual(sketch.ConstraintCount, 7)
        sketch.detectMissingPointOnPointConstraints()
        sketch.makeMissingPointOnPointCoincident()
        self.Doc.recompute()
        self.assertEqual(sketch.ConstraintCount, 8)
        del v0, v1, v2, v3, v4, v5
        del geo0, geo1, geo2, geo3
        del sketch

    def testDegenratedGeometryCase(self):
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        v0 = Vector(-47.680691, 18.824165000000004, 0.0)
        v1 = Vector(-47.680691, -27.346279, 0.0)
        v2 = Vector(-47.680691, -27.34627900001, 0.0)

        geo0 = sketch.addGeometry(Part.LineSegment(v0, v1))
        geo1 = sketch.addGeometry(Part.LineSegment(v1, v2))
        sketch.addConstraint(Sketcher.Constraint("Coincident", geo0, 2, geo1, 1))
        self.Doc.recompute()
        tol = 1.0e-8
        self.assertEqual(sketch.ConstraintCount, 1)
        self.assertEqual(sketch.detectDegeneratedGeometries(tol), 1)
        self.assertEqual(sketch.removeDegeneratedGeometries(tol), 1)
        self.assertEqual(sketch.detectDegeneratedGeometries(tol), 0)
        self.assertEqual(sketch.ConstraintCount, 0)
        del v0, v1, v2
        del geo0, geo1
        del sketch

    def testDeleteConstraintsToExternalCase(self):
        box = self.Doc.addObject("Part::Box", "Box")
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        self.Doc.recompute()
        sketch.addExternal("Box", "Edge12")

        v0 = Vector(-47.680691, 18.824165000000004, 0.0)
        v1 = Vector(-47.680691, -27.346279, 0.0)
        geo0 = sketch.addGeometry(Part.LineSegment(v0, v1))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", geo0))
        sketch.addConstraint(Sketcher.Constraint("Equal", -3, geo0))
        self.Doc.recompute()
        self.assertEqual(sketch.ConstraintCount, 2)
        sketch.delConstraintsToExternal()
        self.Doc.recompute()
        self.assertEqual(sketch.ConstraintCount, 1)
        del v0, v1
        del geo0
        del sketch
        del box

    def testValidateConstraintsCase(self):
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        v0 = Vector(-47.680691, 18.824165000000004, 0.0)
        v1 = Vector(-47.680691, -27.346279, 0.0)
        v2 = Vector(51.132679, -27.346279, 0.0)
        geo0 = sketch.addGeometry(Part.LineSegment(v0, v1))
        geo1 = sketch.addGeometry(Part.LineSegment(v1, v2))
        sketch.addConstraint(Sketcher.Constraint("Coincident", geo0, 2, geo1, 1))

        c = sketch.Constraints[0]
        c.First = 2
        sketch.Constraints = [c]
        self.assertEqual(sketch.ConstraintCount, 1)
        self.assertFalse(sketch.evaluateConstraints())

        sketch.validateConstraints()

        self.assertEqual(sketch.ConstraintCount, 0)
        self.assertTrue(sketch.evaluateConstraints())
        del v0, v1, v2
        del geo0, geo1
        del sketch, c

    def testExternalGeoDeletion(self):
        """Make sure that we don't remove External Geometry references to deleted geometry.
        See https://github.com/FreeCAD/FreeCAD/issues/16361"""
        if "BUILD_PART_DESIGN" in FreeCAD.__cmake__:
            doc = App.ActiveDocument
            doc.addObject("PartDesign::Body", "Body")
            doc.Body.Label = "Body"
            doc.recompute()
            doc.Body.newObject("Sketcher::SketchObject", "Sketch")
            doc.Sketch.AttachmentSupport = (doc.XY_Plane, [""])
            doc.Sketch.MapMode = "FlatFace"
            doc.recompute()
            geoList = []
            geoList.append(
                Part.LineSegment(
                    App.Vector(7.548310, 5.193216, 0.000000),
                    App.Vector(31.461353, 5.193216, 0.000000),
                )
            )
            geoList.append(
                Part.LineSegment(
                    App.Vector(31.461353, 5.193216, 0.000000),
                    App.Vector(31.461353, 20.652151, 0.000000),
                )
            )
            geoList.append(
                Part.LineSegment(
                    App.Vector(31.461353, 20.652151, 0.000000),
                    App.Vector(7.548310, 20.652151, 0.000000),
                )
            )
            geoList.append(
                Part.LineSegment(
                    App.Vector(7.548310, 20.652151, 0.000000),
                    App.Vector(7.548310, 5.193216, 0.000000),
                )
            )
            doc.Sketch.addGeometry(geoList, False)
            del geoList
            constraintList = []
            constraintList.append(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
            constraintList.append(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
            constraintList.append(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
            constraintList.append(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
            constraintList.append(Sketcher.Constraint("Horizontal", 0))
            constraintList.append(Sketcher.Constraint("Horizontal", 2))
            constraintList.append(Sketcher.Constraint("Vertical", 1))
            constraintList.append(Sketcher.Constraint("Vertical", 3))
            doc.Sketch.addConstraint(constraintList)
            del constraintList
            constraintList = []
            doc.recompute()
            doc.Body.newObject("Sketcher::SketchObject", "Sketch001")
            doc.Sketch001.AttachmentSupport = (doc.XY_Plane, [""])
            doc.Sketch001.MapMode = "FlatFace"
            doc.recompute()
            doc.Sketch001.addExternal("Sketch", "Edge3")
            geoList = []
            geoList.append(
                Part.LineSegment(
                    App.Vector(33.192780, 22.530144, 0.000000),
                    App.Vector(38.493977, 32.289181, 0.000000),
                )
            )
            doc.Sketch001.addGeometry(geoList, False)
            del geoList
            constraintList = []
            doc.Sketch001.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
            doc.recompute()
            doc.Sketch.delGeometries([1])
            doc.Sketch.delGeometries([1])
            doc.recompute()
            doc.Sketch001.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
            doc.recompute()
            # Assert
            self.assertEqual(len(doc.Sketch001.Constraints), 2)  # Still have the constraints
            # The link to the deleted edge is kept, and the sketch fails (ops#72)
            self.assertEqual(doc.Sketch001.ExternalGeometry, [(doc.Sketch, ("?Edge3",))])
            self.assertFalse(doc.Sketch001.isValid())
            self.assertEqual(len(doc.Sketch001.Geometry), 1)
            self.assertEqual(
                len(doc.Sketch001.ExternalGeo), 3
            )  # Two axis, plus one the reference to deleted geometry

    def testMissingCoincidenceAfterTheGeometryChanged(self):
        """ops#252: a coincidence found between line 0's end and line 1's start isn't made once
        line 0 is deleted: its GeoIds would then join line 1's end (10, 10) and line 2's start
        (20, 20), and the solver would pull them together. Nothing is added, with a warning."""
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        sketch.addGeometry(Part.LineSegment(Vector(0, 0, 0), Vector(10, 0, 0)))
        sketch.addGeometry(Part.LineSegment(Vector(10, 0, 0), Vector(10, 10, 0)))
        sketch.addGeometry(Part.LineSegment(Vector(20, 20, 0), Vector(30, 30, 0)))
        self.Doc.recompute()
        self.assertEqual(sketch.detectMissingPointOnPointConstraints(), 1)
        sketch.delGeometry(0)
        sketch.makeMissingPointOnPointCoincident()
        self.Doc.recompute()
        self.assertEqual(sketch.ConstraintCount, 0)
        self.assertEqual(sketch.Geometry[1].StartPoint, Vector(20, 20, 0))
        # detected again on the geometry as it is: nothing missing
        self.assertEqual(sketch.detectMissingPointOnPointConstraints(), 0)

    def testMissingCoincidenceAfterTheGeometryMoved(self):
        """PR 269 review L3: line 1's start moves from (10, 0) to (12, 3) after the coincidence
        with line 0's end is found. The geometry keeps its tags, but the points are no longer
        within the precision they were found with: nothing is added, and the list stays (the
        validation panel tells the user)."""
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        sketch.addGeometry(Part.LineSegment(Vector(0, 0, 0), Vector(10, 0, 0)))
        sketch.addGeometry(Part.LineSegment(Vector(10, 0, 0), Vector(10, 10, 0)))
        self.Doc.recompute()
        self.assertEqual(sketch.detectMissingPointOnPointConstraints(), 1)
        sketch.moveGeometry(1, 1, Vector(12, 3, 0))
        self.assertLess((sketch.Geometry[1].StartPoint - Vector(12, 3, 0)).Length, 1e-6)
        sketch.makeMissingPointOnPointCoincident()
        self.Doc.recompute()
        self.assertEqual(sketch.ConstraintCount, 0)
        self.assertEqual(len(sketch.MissingPointOnPointConstraints), 1)

    def testMissingCoincidencesOfAThreePointGroup(self):
        """PR 269 round 2: three line starts at x = -0.08, 0 and 0.08 form one group at precision
        0.1, each within it of the group's middle point, but the outer two are 0.16 apart. Both
        coincidences found are made: each point is still where it was found."""
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        sketch.addGeometry(Part.LineSegment(Vector(0, 0, 0), Vector(0, 10, 0)))
        sketch.addGeometry(Part.LineSegment(Vector(0.08, 0, 0), Vector(10, -5, 0)))
        sketch.addGeometry(Part.LineSegment(Vector(-0.08, 0, 0), Vector(-10, -5, 0)))
        self.Doc.recompute()
        self.assertEqual(sketch.detectMissingPointOnPointConstraints(0.1), 2)
        sketch.makeMissingPointOnPointCoincident()
        self.Doc.recompute()
        made = sorted(
            tuple(sorted(((c.First, c.FirstPos), (c.Second, c.SecondPos))))
            for c in sketch.Constraints
            if c.Type == "Coincident"
        )
        self.assertEqual(len(made), 2)
        # the three starts end up joined
        self.assertEqual({point for pair in made for point in pair}, {(0, 1), (1, 1), (2, 1)})

    def testAutoconstraintMakesCoincidencesAfterHorizontalVertical(self):
        """PR 269 round 2: autoconstraint() solves the horizontal/vertical constraints it finds
        before it makes the coincidences it found earlier. A rectangle's bottom edge 3 degrees off
        horizontal: making it horizontal moves its ends about 2.6, and the four corners are still
        joined."""
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        rise = 100 * math.tan(math.radians(3))
        corners = [Vector(0, 0, 0), Vector(100, rise, 0), Vector(100, 60, 0), Vector(0, 60, 0)]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        self.Doc.recompute()
        sketch.autoconstraint()
        self.Doc.recompute()
        types = [c.Type for c in sketch.Constraints]
        self.assertEqual(types.count("Horizontal"), 2)
        self.assertEqual(types.count("Vertical"), 2)
        self.assertEqual(types.count("Coincident"), 4)
        bottom = sketch.Geometry[0]
        self.assertAlmostEqual(bottom.StartPoint.y, bottom.EndPoint.y, places=6)
        for i in range(4):
            gap = sketch.Geometry[i].EndPoint - sketch.Geometry[(i + 1) % 4].StartPoint
            self.assertLess(gap.Length, 1e-6)

    def testMissingCoincidenceAfterARecompute(self):
        """ops#252: a recompute between Detect and Make (the solver moves nothing here, and keeps
        each geometry's tag) doesn't stop the coincidence from being made."""
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        sketch.addGeometry(Part.LineSegment(Vector(0, 0, 0), Vector(10, 0, 0)))
        sketch.addGeometry(Part.LineSegment(Vector(10, 0, 0), Vector(10, 10, 0)))
        self.Doc.recompute()
        self.assertEqual(sketch.detectMissingPointOnPointConstraints(), 1)
        sketch.touch()
        self.Doc.recompute()
        sketch.makeMissingPointOnPointCoincident()
        self.Doc.recompute()
        self.assertEqual(sketch.ConstraintCount, 1)
        c = sketch.Constraints[0]
        self.assertEqual((c.Type, c.First, c.FirstPos, c.Second, c.SecondPos), ("Coincident", 0, 2, 1, 1))

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument(self.Doc.Name)
