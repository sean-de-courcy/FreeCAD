# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-CH lane solid-ops: the Thicken, Scale and Offset surface commands and task panels."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PartDesignTests.TestSolidOps import top_face_name

try:
    from PartDesign import SolidOpsGui as G
except ImportError:  # run with the source folder on the path
    import SolidOpsGui as G


class TestSolidOpsGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SolidOpsGui")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.box = self.doc.addObject("PartDesign::AdditiveBox", "Box")
        self.box.Length, self.box.Width, self.box.Height = 20, 20, 10
        self.body.addObject(self.box)
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)

    def tearDown(self):
        Gui.Control.closeDialog()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)

    def selectTop(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.box.Name, top_face_name(self.box.Shape))

    def features(self, typeName):
        return [o for o in self.doc.Objects if o.TypeId == typeName]

    def testCommandsAreRegistered(self):
        names = Gui.listCommands()
        for cmd in ("PartDesign_Thicken", "PartDesign_ScalePart", "PartDesign_OffsetSurface"):
            self.assertIn(cmd, names)

    def testThickenFromTheSelectedFaceAddsToTheBody(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        self.assertIsNotNone(panel)
        feature = panel.obj
        self.assertEqual(len(feature.Base), 1)
        self.assertEqual(panel.faceList.count(), 1)
        panel.widgets["Thickness1"].setValue(2.0)
        self.assertTrue(panel.accept())
        self.assertIsNone(G.Panel.current)
        self.assertAlmostEqual(self.body.Shape.Volume, 4800.0, 3)
        self.assertEqual(self.body.Tip, feature)

    def testThickenAsNewMovesIntoANewPart(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        panel.widgets["Operation"].setCurrentIndex(0)  # New
        panel.widgets["Thickness1"].setValue(2.0)
        self.assertTrue(panel.accept())
        feature = [o for o in self.doc.Objects if o.Name.startswith("Thicken")][0]
        self.assertNotEqual(feature.getParentGeoFeatureGroup(), self.body)
        self.assertAlmostEqual(self.body.Shape.Volume, 4000.0, 3)
        self.assertAlmostEqual(feature.Shape.Volume, 800.0, 3)

    def testThickenRemoveFromThePanel(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        panel.widgets["Operation"].setCurrentIndex(2)  # Remove
        panel.widgets["Thickness1"].setValue(0.0)
        panel.widgets["Thickness2"].setValue(2.0)
        self.assertTrue(panel.accept())
        self.assertAlmostEqual(self.body.Shape.Volume, 3200.0, 3)

    def testAZeroThicknessKeepsThePanelOpenWithTheError(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        panel.widgets["Thickness1"].setValue(0.0)
        self.assertFalse(panel.accept())
        self.assertIs(G.Panel.current, panel)
        self.assertIn("zero", panel.message.text().lower())

    def testCancelRemovesTheFeature(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        G.Panel.current.reject()
        self.assertEqual(self.features("PartDesign::FeatureAdditivePython"), [])
        self.assertAlmostEqual(self.body.Shape.Volume, 4000.0, 3)

    def testOffsetSurfaceFromTheSelectedFace(self):
        self.selectTop()
        Gui.runCommand("PartDesign_OffsetSurface")
        panel = G.Panel.current
        panel.widgets["Distance"].setValue(3.0)
        panel.widgets["Flip"].setChecked(True)
        self.assertTrue(panel.accept())
        feature = panel.obj
        self.assertAlmostEqual(feature.Shape.BoundBox.ZMin, 7.0, 5)
        self.assertAlmostEqual(feature.Shape.Area, 400.0, 4)

    def testScaleTheActiveBody(self):
        Gui.runCommand("PartDesign_ScalePart")
        panel = G.Panel.current
        panel.widgets["Factor"].setValue(2.0)
        self.assertTrue(panel.accept())
        self.assertAlmostEqual(self.body.Shape.Volume, 32000.0, 2)

    def testScalePerAxisThroughThePanel(self):
        Gui.runCommand("PartDesign_ScalePart")
        panel = G.Panel.current
        panel.widgets["Uniform"].setChecked(False)
        panel.widgets["FactorX"].setValue(2.0)
        panel.widgets["FactorY"].setValue(1.0)
        panel.widgets["FactorZ"].setValue(0.5)
        self.assertTrue(panel.accept())
        self.assertAlmostEqual(self.body.Shape.BoundBox.XMax, 40.0, 4)
        self.assertAlmostEqual(self.body.Shape.BoundBox.ZMax, 5.0, 4)

    def testEditingAnExistingFeatureOpensItsPanel(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        feature = G.Panel.current.obj
        G.Panel.current.accept()
        Gui.ActiveDocument.setEdit(feature.Name, 0)
        panel = G.Panel.current
        self.assertIsNotNone(panel)
        self.assertEqual(panel.obj, feature)
        self.assertEqual(panel.faceList.count(), 1)
        self.assertAlmostEqual(panel.widgets["Thickness1"].value(), 1.0)
        panel.widgets["Thickness1"].setValue(3.0)
        panel.accept()
        self.assertAlmostEqual(self.body.Shape.Volume, 4000.0 + 1200.0, 3)
