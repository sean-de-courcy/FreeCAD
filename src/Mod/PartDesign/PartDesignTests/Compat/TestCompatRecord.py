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

"""Units of Part's CompatRecord (FreeCAD-CH ops#343): what the record must see in shapes, values
and names that no corpus model holds yet, so that the reopen gate can't miss a change there.
Designed shapes only."""

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
from FreeCAD import Vector as V

import CompatRecord


class TestCompatRecord(unittest.TestCase):
    def setUp(self):
        self.docs = []
        self.folder = None

    def tearDown(self):
        for doc in reversed(self.docs):
            App.closeDocument(doc.Name)
        if self.folder:
            shutil.rmtree(self.folder, ignore_errors=True)

    def newDocument(self, name):
        doc = App.newDocument(name)
        self.docs.append(doc)
        return doc

    def recordOf(self, shape):
        """The record of a document holding the shape in a Part::Feature named Shape"""
        doc = self.newDocument("CompatRecordShape")
        doc.addObject("Part::Feature", "Shape").Shape = shape
        doc.recompute()
        rec = CompatRecord.record(doc)
        App.closeDocument(doc.Name)
        self.docs.remove(doc)
        return rec

    def differences(self, a, b):
        lines, _ = CompatRecord.compare(a, b, "recompute")
        return [line for line in lines if not line.startswith("Shape.id")]

    def testSolidBesideAnInfinitePlaneIsRecordedInFull(self):
        # A compound of a box and an infinite plane (a Part::Compound holding a datum plane, a
        # binder of a datum and a solid): the box's volume, area, box, centre and names are
        # recorded, the plane counted. Recorded as an infinite shape, the box's move was unseen
        plane = Part.Face(Part.Plane(V(0, 0, 5), V(0, 0, 1)))
        rec = self.recordOf(Part.Compound([Part.makeBox(10, 20, 30), plane]))
        shape = rec["objects"]["Shape"]["shape"]
        self.assertNotIn("infinite", shape)
        self.assertEqual(shape["unbounded"], 1)
        self.assertAlmostEqual(shape["volume"], 6000)
        self.assertAlmostEqual(shape["area"], 2200)
        for value, expected in zip(shape["box"] + shape["centre"], [0, 0, 0, 10, 20, 30, 5, 10, 15]):
            self.assertAlmostEqual(value, expected)
        names = rec["objects"]["Shape"]["names"]
        plane = "Face infinite n=(0.0000,0.0000,1.0000) d=5.0000 : "
        self.assertTrue([line for line in names if line.startswith(plane)])
        self.assertFalse([line for line in names if "e+" in line])
        moved = self.recordOf(Part.Compound([Part.makeBox(10, 20, 30, V(1, 0, 0)), plane]))
        self.assertTrue(self.differences(rec, moved))

    def testInfinitePlaneIsRecordedWithItsPlane(self):
        # An infinite plane on an object other than a datum (a binder of a datum plane): its
        # position is in no property of its own, so the record keeps the plane
        rec = self.recordOf(Part.Face(Part.Plane(V(0, 0, 5), V(0, 0, 1))))
        shape = rec["objects"]["Shape"]["shape"]
        self.assertTrue(shape["infinite"])
        self.assertEqual(shape["plane"], {"normal": [0.0, 0.0, 1.0], "offset": 5.0})
        moved = self.recordOf(Part.Face(Part.Plane(V(0, 0, 6), V(0, 0, 1))))
        self.assertTrue(self.differences(rec, moved))

    def testReferenceToAnInfiniteFace(self):
        # A reference to a datum plane's face (DatumPlane:Face1), and to an infinite cylinder:
        # keyed by the surface's type, and a plane by its normal and offset
        doc = self.newDocument("CompatRecordRefs")
        body = doc.addObject("PartDesign::Body", "Body")
        datum = body.newObject("PartDesign::Plane", "DatumPlane")
        datum.MapMode = "Deactivated"
        datum.Placement = App.Placement(V(0, 0, 7), App.Rotation())
        cylinder = doc.addObject("Part::Feature", "Cylinder")
        cylinder.Shape = Part.Face(Part.Cylinder())
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSubList", "Refs")
        holder.Refs = [(datum, ["Face1"]), (cylinder, ["Face1"])]
        doc.recompute()
        refs = CompatRecord.record(doc)["objects"]["Holder"]["refs"]
        plane = refs["Refs[0]"]["key"]
        self.assertEqual(plane["kind"], "Face")
        self.assertTrue(plane["infinite"])
        self.assertEqual(plane["surface"], "Plane")
        self.assertAlmostEqual(abs(plane["normal"][2]), 1.0)
        self.assertAlmostEqual(abs(plane["offset"]), 7.0)
        tube = refs["Refs[1]"]["key"]
        self.assertTrue(tube["infinite"])
        self.assertEqual(tube["surface"], "Cylinder")
