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

"""Reproducers for the R-list in the ops repo's `notes/naming-v2.md` below the reference level
(FreeCAD-CH, ops#5). The ones about references are scenarios (`Scenarios/rlist.py`)."""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models


class TestNamingRList(unittest.TestCase):
    def setUp(self):
        self.documents = []

    def tearDown(self):
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)

    def newDocument(self, algorithm):
        doc = models.newDocument("NamingRList")
        doc.HistoryAlgorithm = algorithm
        self.documents.append(doc.Name)
        return doc

    def testElementMapVersionFollowsHistoryAlgorithm(self):
        """R3: a document's element map version names its history algorithm, also after the
        algorithm changes. It was computed once and kept."""
        # Arrange
        doc = self.newDocument("V2")
        box = doc.addObject("Part::Box", "Box")
        v2 = box.getCorrectElementMapVersion()
        fresh = self.newDocument("V1").addObject("Part::Box", "Box")
        v1 = fresh.getCorrectElementMapVersion()
        self.assertNotEqual(v1, v2)  # the setup: the versions differ by algorithm

        # Act
        doc.HistoryAlgorithm = "V1"

        # Assert
        self.assertEqual(box.getCorrectElementMapVersion(), v1)
        doc.HistoryAlgorithm = "V2"
        self.assertEqual(box.getCorrectElementMapVersion(), v2)

    def testSwitchedDocumentReopensWithoutRecompute(self):
        """R3: a document whose history algorithm was switched saves its shapes with the new
        algorithm's element map version, so it reopens with no recompute pending. With the old
        version kept, the saved string didn't match the reopened document's and every shape was
        marked for a recompute."""
        folder = tempfile.mkdtemp(prefix="NamingRList")
        self.addCleanup(shutil.rmtree, folder, True)
        for first, second in (("V2", "V1"), ("V1", "V2")):
            with self.subTest(switch=f"{first} -> {second}"):
                # Arrange
                fresh = self.newDocument(second).addObject("Part::Box", "Box")
                expected = fresh.getCorrectElementMapVersion()
                doc = self.newDocument(first)
                doc.addObject("Part::Box", "Box")
                doc.recompute()
                doc.HistoryAlgorithm = second
                doc.recompute()
                path = os.path.join(folder, f"Switched{first}{second}.FCStd")

                # Act
                doc.saveAs(path)
                App.closeDocument(doc.Name)
                doc = App.openDocument(path)
                self.documents.append(doc.Name)

                # Assert
                with zipfile.ZipFile(path) as archive:
                    xml = archive.read("Document.xml").decode()
                saved = re.findall(r'ElementMap="([^"]*)"', xml)  # the Box's shape
                self.assertEqual(saved, [expected])
                self.assertNotIn("Touched", doc.getObject("Box").State)
                self.assertFalse(doc.mustExecute())

    def testDecodeLastFieldEndingInEscapedCharacter(self):
        """R5: a section whose last field ends in an escaped character decodes back to what was
        encoded. The decoder lost the whole name."""
        for connected in (["a"], ["a;"], ["b", "a;"]):
            with self.subTest(connectedElements=connected):
                # Arrange
                fields = dict(referenceIDs=["g1"], iterationTag="12", opCode="XTR",
                              connectedElements=connected)
                encoded = App.makeEncodedSection(**fields)

                # Act
                decoded = App.getDecodedMappedName(encoded)

                # Assert
                self.assertEqual(len(decoded), 1, encoded)
                self.assertEqual(list(decoded[0]["connectedElements"]), connected, encoded)
                self.assertEqual(list(decoded[0]["referenceIDs"]), ["g1"], encoded)

    def testBinderFacesOfOverlappingCircles(self):
        """R10: a SubShapeBinder with MakeFace, created now (_Version 3), makes faces with
        FaceMakerBuildFace: two overlapping circles give three regions that don't overlap, whose
        areas add up to the union's. The Bullseye face maker gave two full, overlapping disks."""
        # Arrange
        doc = self.newDocument("V2")
        circles = [models.circle(0, 0, 5), models.circle(6, 0, 5)]
        sketch = models.sketch(doc, "Circles", circles)
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(sketch, ("",))]
        binder.MakeFace = True
        disks = [Part.Face(Part.Wire(c.toShape())) for c in circles]
        union = disks[0].fuse(disks[1]).Area

        # Act
        doc.recompute()

        # Assert
        self.assertTrue(binder.isValid(), binder.State)
        faces = binder.Shape.Faces
        self.assertAlmostEqual(sum(f.Area for f in faces), union, places=6)
        self.assertEqual(len(faces), 3)

    def testOldBinderKeepsBullseyeFaces(self):
        """R10, the other side of the gate: a binder from an older document (_Version below 3)
        keeps the Bullseye face maker, so its faces don't change on reopen. Two overlapping
        circles give two full disks."""
        # Arrange
        doc = self.newDocument("V2")
        circles = [models.circle(0, 0, 5), models.circle(6, 0, 5)]
        sketch = models.sketch(doc, "Circles", circles)
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.setPropertyStatus("_Version", "-ReadOnly")
        binder._Version = 2
        binder.Support = [(sketch, ("",))]
        binder.MakeFace = True
        disk = Part.Face(Part.Wire(circles[0].toShape())).Area

        # Act
        doc.recompute()

        # Assert
        self.assertTrue(binder.isValid(), binder.State)
        faces = binder.Shape.Faces
        self.assertEqual(len(faces), 2)
        for face in faces:
            self.assertAlmostEqual(face.Area, disk, places=6)
