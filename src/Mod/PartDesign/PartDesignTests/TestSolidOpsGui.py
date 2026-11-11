# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-CH lane solid-ops: the Thicken, Scale and Offset surface commands and task panels."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets
from PySide6.QtTest import QTest

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
        self.assertEqual(panel.widgets["Operation"].currentIndex(), 0)  # Onshape starts on New
        self.assertAlmostEqual(panel.value("Thickness1"), 5.0)
        panel.widgets["Operation"].setCurrentIndex(1)  # Add
        panel.setValue("Thickness1", 2.0)
        self.assertTrue(panel.accept())
        self.assertIsNone(G.Panel.current)
        self.assertAlmostEqual(self.body.Shape.Volume, 4800.0, 3)
        self.assertEqual(self.body.Tip, feature)

    def testThickenAsNewMovesIntoANewPart(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        panel.widgets["Operation"].setCurrentIndex(0)  # New
        panel.setValue("Thickness1", 2.0)
        self.assertTrue(panel.accept())
        feature = [o for o in self.doc.Objects if o.Name.startswith("Thicken")][0]
        self.assertNotEqual(feature.getParentGeoFeatureGroup(), self.body)
        self.assertAlmostEqual(self.body.Shape.Volume, 4000.0, 3)
        self.assertAlmostEqual(feature.Shape.Volume, 800.0, 3)

    def testMidplaneAndFlipFromThePanel(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        panel.widgets["Operation"].setCurrentIndex(1)  # Add
        panel.widgets["Midplane"].setChecked(True)
        panel.setValue("Thickness", 4.0)  # z 8..12
        self.assertTrue(panel.accept())
        self.assertAlmostEqual(self.body.Shape.Volume, 4000.0 + 400.0 * 2, 3)

    def testThickenRemoveFromThePanel(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        panel.widgets["Operation"].setCurrentIndex(2)  # Remove
        panel.setValue("Thickness1", 0.0)
        panel.setValue("Thickness2", 2.0)
        self.assertTrue(panel.accept())
        self.assertAlmostEqual(self.body.Shape.Volume, 3200.0, 3)

    def testAZeroThicknessKeepsThePanelOpenWithTheError(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        panel.setValue("Thickness1", 0.0)
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
        panel.setValue("Distance", 3.0)
        panel.widgets["Flip"].setChecked(True)
        self.assertTrue(panel.accept())
        feature = panel.obj
        self.assertNotEqual(feature.getParentGeoFeatureGroup(), self.body)  # a part of its own
        self.assertAlmostEqual(self.body.Shape.Volume, 4000.0, 3)  # the solid stays
        self.assertAlmostEqual(feature.Shape.BoundBox.ZMin, 7.0, 5)
        self.assertAlmostEqual(feature.Shape.Area, 400.0, 4)

    def testScaleTheActiveBody(self):
        Gui.runCommand("PartDesign_ScalePart")
        panel = G.Panel.current
        panel.setValue("Factor", 2.0)
        self.assertTrue(panel.accept())
        self.assertAlmostEqual(self.body.Shape.Volume, 32000.0, 2)

    def testScalePerAxisThroughThePanel(self):
        Gui.runCommand("PartDesign_ScalePart")
        panel = G.Panel.current
        panel.widgets["Uniform"].setChecked(False)
        panel.setValue("FactorX", 2.0)
        panel.setValue("FactorY", 1.0)
        panel.setValue("FactorZ", 0.5)
        self.assertTrue(panel.accept())
        self.assertAlmostEqual(self.body.Shape.BoundBox.XMax, 40.0, 4)
        self.assertAlmostEqual(self.body.Shape.BoundBox.ZMax, 5.0, 4)

    def testEditingAnExistingFeatureOpensItsPanel(self):
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        feature = G.Panel.current.obj
        G.Panel.current.widgets["Operation"].setCurrentIndex(1)  # Add
        G.Panel.current.setValue("Thickness1", 1.0)
        G.Panel.current.accept()
        Gui.ActiveDocument.setEdit(feature.Name, 0)
        panel = G.Panel.current
        self.assertIsNotNone(panel)
        self.assertEqual(panel.obj, feature)
        self.assertEqual(panel.faceList.count(), 1)
        self.assertAlmostEqual(panel.value("Thickness1"), 1.0)
        panel.setValue("Thickness1", 3.0)
        panel.accept()
        self.assertAlmostEqual(self.body.Shape.Volume, 4000.0 + 1200.0, 3)

    def testEditingAfterSaveAndReopenOpensThePanel(self):
        """Rehearsal 3's F2: a restored view provider had no `kind`, so no icon and no dialog."""
        import os
        import tempfile

        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        G.Panel.current.widgets["Operation"].setCurrentIndex(1)  # Add
        self.assertTrue(G.Panel.current.accept())
        Gui.runCommand("PartDesign_ScalePart")
        self.assertTrue(G.Panel.current.accept())
        self.selectTop()
        Gui.runCommand("PartDesign_OffsetSurface")
        self.assertTrue(G.Panel.current.accept())
        kinds = {o.Name: type(o.Proxy).__name__ for o in self.doc.Objects if hasattr(o, "Proxy") and o.isDerivedFrom("PartDesign::Feature")}
        self.assertEqual(sorted(kinds.values()), ["OffsetSurface", "Scale", "Thicken"])
        path = os.path.join(tempfile.mkdtemp(), "SolidOpsReopen.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        for name, kind in kinds.items():
            vobj = self.doc.getObject(name).ViewObject
            self.assertEqual(vobj.Proxy.getIcon(), G.KINDS[kind]["icon"])
            Gui.getDocument(self.doc.Name).setEdit(name, 0)
            panel = G.Panel.current
            self.assertIsNotNone(panel, "no dialog for %s after reopening" % kind)
            self.assertEqual((panel.obj.Name, panel.kind), (name, kind))
            panel.reject()
            self.pump(0.1)

    # -- expression fields: `#variable` typed into a field binds it (Onshape's variables)

    def pump(self, seconds=0.2):
        app = QtWidgets.QApplication.instance()
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    def typeInto(self, panel, name, text):
        from PySide import QtCore

        spin = panel.widgets[name]
        spin.show()
        spin.setFocus()
        self.pump(0.1)
        spin.findChild(QtWidgets.QLineEdit).selectAll()
        QTest.keyClicks(spin, text)
        # ops#640's fields set this property on a text update only, so it is read after typing
        if spin.property("unresolvedVariable") is None:
            self.skipTest("this build's fields do not take #variable (ops#640)")
        QTest.keyClick(spin, QtCore.Qt.Key_Return)
        self.pump(0.2)

    def addVariables(self):
        vs = self.doc.addObject("App::VarSet", "Variables")
        vs.addProperty("App::PropertyLength", "Thick")
        vs.addProperty("App::PropertyLength", "Dist")
        vs.addProperty("App::PropertyFloat", "Scl")
        vs.Thick, vs.Dist, vs.Scl = 2.0, 3.0, 2.0
        self.doc.recompute()
        return vs

    def exprs(self, obj):
        return {p.lstrip("."): e for p, e in obj.ExpressionEngine}

    def testThickenFieldTakesAVariable(self):
        vs = self.addVariables()
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        feature = panel.obj
        self.typeInto(panel, "Thickness1", "#Thick")
        self.assertEqual(self.exprs(feature).get("Thickness1"), "Variables.Thick")
        self.assertAlmostEqual(feature.Thickness1.Value, 2.0, 6)
        self.assertAlmostEqual(feature.Shape.Volume, 4800.0, 3)
        panel.widgets["Operation"].setCurrentIndex(1)  # Add: the panel starts on New (Onshape's)
        self.assertTrue(panel.accept())
        vs.Thick = 3.0
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 4000.0 + 400.0 * 3.0, 3)

    def testOffsetFieldTakesAVariable(self):
        self.addVariables()
        self.selectTop()
        Gui.runCommand("PartDesign_OffsetSurface")
        panel = G.Panel.current
        self.typeInto(panel, "Distance", "#Dist")
        self.assertEqual(self.exprs(panel.obj).get("Distance"), "Variables.Dist")
        self.assertAlmostEqual(panel.obj.Shape.BoundBox.ZMin, 13.0, 5)
        self.assertTrue(panel.accept())

    def testScaleFactorFieldTakesAVariable(self):
        self.addVariables()
        Gui.runCommand("PartDesign_ScalePart")
        panel = G.Panel.current
        self.typeInto(panel, "Factor", "#Scl")
        self.assertEqual(self.exprs(panel.obj).get("Factor"), "Variables.Scl")
        self.assertAlmostEqual(panel.obj.Shape.Volume, 32000.0, 2)
        self.assertTrue(panel.accept())

    def testAnExpressionFieldIsNotOverwrittenByThePanel(self):
        vs = self.addVariables()
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        panel = G.Panel.current
        panel.obj.setExpression("Thickness1", "Variables.Thick")
        panel.changed()  # any later edit: the value is not written over the expression
        self.assertEqual(self.exprs(panel.obj).get("Thickness1"), "Variables.Thick")
        vs.Thick = 4.0
        self.doc.recompute()
        self.assertAlmostEqual(panel.obj.Thickness1.Value, 4.0, 6)
        self.assertTrue(panel.accept())

    def testReopenedPanelShowsTheExpression(self):
        self.addVariables()
        self.selectTop()
        Gui.runCommand("PartDesign_Thicken")
        feature = G.Panel.current.obj
        feature.setExpression("Thickness1", "Variables.Thick")
        G.Panel.current.accept()
        Gui.ActiveDocument.setEdit(feature.Name, 0)
        panel = G.Panel.current
        self.assertTrue(panel.hasExpression("Thickness1"))
        self.assertAlmostEqual(panel.value("Thickness1"), 2.0, 6)
        panel.reject()
        self.assertEqual(self.exprs(feature).get("Thickness1"), "Variables.Thick")
