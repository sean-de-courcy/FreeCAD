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

    def source(self):
        """A pad 20 x 10 x 5 in a Body at (100, 50); returns the Body, the pad and its top."""
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
        return source, pad, top

    def bind(self, active, source, sub):
        """The command on the pick (source, sub) as picked in 3D, with active as the active
        Body; returns the binder it made."""
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", active)
        Gui.Selection.addSelection(self.doc.Name, source.Name, sub)
        before = {o.Name for o in self.doc.Objects}
        Gui.runCommand("PartDesign_SubShapeBinder")
        pump(0.2)
        [binder] = [
            o for o in self.doc.Objects
            if o.Name not in before and o.TypeId == "PartDesign::SubShapeBinder"
        ]
        self.doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        return binder

    def assertOnTheTop(self, binder):
        """The binder lies on the pad's top, where the pad is in the document."""
        self.assertAlmostEqual(binder.Shape.Area, 200, places=6)
        box = binder.Shape.BoundBox
        for got, expected in zip((box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax),
                                 (100, 50, 5, 120, 60, 5)):
            self.assertAlmostEqual(got, expected, places=6)

    def testBinderOfAFaceOfAnotherBodyBindsTheFeature(self):
        """In a second, active Body, the command on the pad's top as picked in 3D,
        (Body, "Pad.FaceN"). The binder binds (Pad, "FaceN"): a binder through the Body made the
        two Bodies depend on each other once the other Body bound something of this one, a
        cycle that never settled. It lies on the pad's top, where the pad is in the document."""
        source, pad, top = self.source()
        target = self.doc.addObject("PartDesign::Body", "Target")
        self.doc.recompute()
        binder = self.bind(target, source, "%s.%s" % (pad.Name, top))
        self.assertIn(binder, target.Group)
        self.assertEqual(binder.Support, [(pad, (top,))])
        self.assertOnTheTop(binder)

    def testBinderWithNoActiveBodyKeepsThePick(self):
        """With no active Body, the command makes the binder at the document's top level and
        keeps the pick as it is, (Body, "Pad.FaceN"): no cycle through a Body forms there. It lies
        on the pad's top. Converted to (Pad, "FaceN"), it lay at the origin (ops#308 F1)."""
        source, pad, top = self.source()
        self.doc.addObject("PartDesign::Body", "Other")
        self.doc.recompute()
        binder = self.bind(None, source, "%s.%s" % (pad.Name, top))
        self.assertIsNone(binder.getParentGeoFeatureGroup())
        self.assertEqual(binder.Support, [(source, ("%s.%s" % (pad.Name, top),))])
        self.assertOnTheTop(binder)


if __name__ == "__main__":
    unittest.main()
