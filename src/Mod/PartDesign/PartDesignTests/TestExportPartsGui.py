# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, gaps3 row 11): the part row's Export... (Onshape's GB15)
#
# Designed geometry: a 10 x 20 x 30 mm box and a 10 mm cylinder, each in its own Body, the box
# moved off the origin. Expected results are geometric: sizes in the chosen units, the placement
# kept, a finer resolution giving more facets, the STEP volume.

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import FreeCADGui as Gui

import ExportPartsGui


class TestExportPartsGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ExportParts")
        self.folder = tempfile.mkdtemp(prefix="exportparts")
        self.boxBody = self.doc.addObject("PartDesign::Body", "BoxBody")
        box = self.boxBody.newObject("PartDesign::AdditiveBox", "Box")
        box.Length, box.Width, box.Height = 10, 20, 30
        self.boxBody.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        self.cylBody = self.doc.addObject("PartDesign::Body", "CylBody")
        cyl = self.cylBody.newObject("PartDesign::AdditiveCylinder", "Cyl")
        cyl.Radius, cyl.Height = 5, 10
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.folder, name)

    def readMesh(self, path):
        import Mesh

        return Mesh.Mesh(path)

    def testStlInInches(self):
        """STL in inches: the box measures 10/25.4 x 20/25.4 x 30/25.4 and stays at x = 100 mm."""
        path = self.path("box.stl")
        ExportPartsGui.exportParts([self.boxBody], path, "STL", units="in")
        box = self.readMesh(path).BoundBox
        self.assertAlmostEqual(box.XLength, 10 / 25.4, places=4)
        self.assertAlmostEqual(box.YLength, 20 / 25.4, places=4)
        self.assertAlmostEqual(box.ZLength, 30 / 25.4, places=4)
        self.assertAlmostEqual(box.XMin, 100 / 25.4, places=4)

    def testStlTextAndBinary(self):
        """The STL format: text starts with "solid", binary doesn't."""
        text, binary = self.path("t.stl"), self.path("b.stl")
        ExportPartsGui.exportParts([self.boxBody], text, "STL", stlText=True)
        ExportPartsGui.exportParts([self.boxBody], binary, "STL")
        with open(text, "rb") as f:
            self.assertTrue(f.read(5).lower() == b"solid")
        with open(binary, "rb") as f:
            self.assertFalse(f.read(5).lower() == b"solid")
        self.assertEqual(self.readMesh(text).CountFacets, self.readMesh(binary).CountFacets)

    def testResolution(self):
        """A finer resolution makes more facets on the cylinder; Custom takes its tolerances."""
        counts = {}
        for level in ("Coarse", "Medium", "Fine"):
            path = self.path(level + ".stl")
            ExportPartsGui.exportParts([self.cylBody], path, "STL", resolution=level)
            counts[level] = self.readMesh(path).CountFacets
        self.assertLess(counts["Coarse"], counts["Medium"])
        self.assertLess(counts["Medium"], counts["Fine"])
        path = self.path("custom.stl")
        ExportPartsGui.exportParts(
            [self.cylBody], path, "STL", resolution="Custom", chordal=0.5, angular=30
        )
        self.assertLess(self.readMesh(path).CountFacets, counts["Coarse"])
        with self.assertRaises(ValueError):
            ExportPartsGui.exportParts(
                [self.cylBody], path, "STL", resolution="Custom", chordal=0, angular=5
            )

    def testTwoPartsOneFile(self):
        """Two parts go into one file, each in its placement."""
        path = self.path("both.stl")
        ExportPartsGui.exportParts([self.boxBody, self.cylBody], path, "STL")
        box = self.readMesh(path).BoundBox
        self.assertAlmostEqual(box.XMin, -5, places=3)
        self.assertAlmostEqual(box.XMax, 110, places=3)

    def testPartInContainer(self):
        """A Body inside an App::Part placed at x = 50 exports at x = 50."""
        container = self.doc.addObject("App::Part", "Container")
        container.Placement = App.Placement(App.Vector(50, 0, 0), App.Rotation())
        container.addObject(self.cylBody)
        self.doc.recompute()
        path = self.path("contained.stl")
        ExportPartsGui.exportParts([self.cylBody], path, "STL")
        self.assertAlmostEqual(self.readMesh(path).BoundBox.XMin, 45, places=3)

    def testStep(self):
        """STEP keeps the solid: volume 6000 mm^3, at x = 100 mm."""
        import Part

        path = self.path("box.step")
        ExportPartsGui.exportParts([self.boxBody], path, "STEP", units="in")
        shape = Part.read(path)
        self.assertAlmostEqual(shape.Volume, 6000, places=3)
        self.assertAlmostEqual(shape.BoundBox.XMin, 100, places=4)

    def testDialogDefaults(self):
        """The dialog opens on STL, mm and Fine; Custom alone unlocks the tolerances; STEP has
        no units or resolution; the extension follows the format."""
        from PySide import QtWidgets

        dialog = ExportPartsGui.makeDialog([self.boxBody], Gui.getMainWindow())
        try:
            find = lambda cls, name: dialog.findChild(cls, name)
            formats = find(QtWidgets.QComboBox, "exportFormat")
            resolution = find(QtWidgets.QComboBox, "exportResolution")
            units = find(QtWidgets.QComboBox, "exportUnits")
            chordal = find(QtWidgets.QDoubleSpinBox, "exportChordal")
            fileName = find(QtWidgets.QLineEdit, "exportFileName")
            self.assertEqual(formats.currentText(), "STL")
            self.assertEqual(units.currentText(), "mm")
            self.assertEqual(resolution.currentText(), "Fine")
            self.assertFalse(chordal.isEnabled())
            self.assertAlmostEqual(chordal.value(), ExportPartsGui.RESOLUTIONS["Fine"][0])
            self.assertTrue(fileName.text().endswith("BoxBody.stl"))
            resolution.setCurrentText("Custom")
            self.assertTrue(chordal.isEnabled())
            formats.setCurrentText("STEP")
            self.assertFalse(units.isEnabled())
            self.assertFalse(resolution.isEnabled())
            self.assertFalse(chordal.isEnabled())
            self.assertTrue(fileName.text().endswith("BoxBody.step"))
            opts = dialog.exportOptions()
            self.assertEqual(opts["fmt"], "STEP")
        finally:
            dialog.deleteLater()
