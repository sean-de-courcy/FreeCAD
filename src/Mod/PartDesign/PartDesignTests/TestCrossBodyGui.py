# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Sub-Shape Binder command on a pick in another Body (FreeCAD-CH ops#308 T2): it binds the
feature, not the Body. Designed geometry. Off screen: QT_QPA_PLATFORM=offscreen, a fresh
FREECAD_USER_HOME (notes/build.md)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PartDesignTests.Scenarios import models
from PartDesignTests.TestExpressionFieldsGui import pump

V = App.Vector


class TestCrossBodyGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("CrossBodyGui")
        Gui.Selection.clearSelection()

    def tearDown(self):
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        pump()

    def testBinderOfAFaceOfAnotherBodyBindsTheFeature(self):
        """A pad 20 x 10 x 5 in a Body at (100, 50); in a second, active Body, the command on
        the pad's top as picked in 3D, (Body, "Pad.FaceN"). The binder binds (Pad, "FaceN"): a
        binder through the Body made the two Bodies depend on each other once the other Body
        bound something of this one, a cycle that never settled. It lies on the pad's top,
        where the pad is in the document."""
        source = self.doc.addObject("PartDesign::Body", "Source")
        source.Placement.Base = V(100, 50, 0)
        sketch = models.sketch(self.doc, "Sk", models.rectangle(0, 0, 20, 10), source)
        pad = models.pad(source, sketch, 5)
        self.doc.recompute()
        [top] = [
            f"Face{i}"
            for i, f in enumerate(pad.Shape.Faces, 1)
            if abs(f.normalAt(0, 0).z - 1) < 1e-9 and abs(f.CenterOfMass.z - 5) < 1e-6
        ]
        target = self.doc.addObject("PartDesign::Body", "Target")
        self.doc.recompute()

        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", target)
        Gui.Selection.addSelection(self.doc.Name, source.Name, "%s.%s" % (pad.Name, top))
        Gui.runCommand("PartDesign_SubShapeBinder")
        pump(0.2)
        [binder] = [o for o in target.Group if o.TypeId == "PartDesign::SubShapeBinder"]
        self.assertEqual(binder.Support, [(pad, (top,))])
        self.doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        self.assertAlmostEqual(binder.Shape.Area, 200, places=6)
        box = binder.Shape.BoundBox
        for got, expected in zip((box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax),
                                 (100, 50, 5, 120, 60)):
            self.assertAlmostEqual(got, expected, places=6)


if __name__ == "__main__":
    unittest.main()
