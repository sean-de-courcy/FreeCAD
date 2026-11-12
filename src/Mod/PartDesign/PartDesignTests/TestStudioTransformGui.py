# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-CH ops#655: the Transform command and panel (TransformGui.py), on
TestStudioList.newStudio's boxes A, B and C."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PartDesignTests.TestStudioList import newStudio, studioList

try:
    from PartDesign import TransformGui as G
    from PartDesign import TransformFeature as T
except ImportError:
    import TransformGui as G
    import TransformFeature as T


class TestStudioTransformGui(unittest.TestCase):
    def setUp(self):
        G.register()
        self.doc, self.studio = newStudio("TestStudioTransformGui")
        studioList(self.doc)
        Gui.Selection.clearSelection()

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)

    def bounds(self, name):
        b = self.doc.getObject(name).Shape.BoundBox
        return [round(v, 6) for v in (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)]

    def open(self, *parts):
        for p in parts:
            Gui.Selection.addSelection(self.doc.Name, p)
        Gui.runCommand(G.COMMAND)
        panel = G.Panel.current
        self.assertIsNotNone(panel)
        self.assertEqual(panel.obj.TransformType, "Translate by line")  # Onshape's default
        panel.type.setCurrentIndex(T.TYPES.index("Translate by XYZ"))
        return panel

    def testMoveThroughThePanel(self):
        panel = self.open("A", "B")
        panel.spins["X"].setValue(5)
        panel.spins["Z"].setValue(2)
        self.assertTrue(panel.accept())
        self.assertEqual(self.bounds("A"), [5, 0, 2, 15, 10, 12])
        self.assertEqual(self.bounds("B"), [25, 0, 2, 35, 10, 12])
        self.assertEqual(self.bounds("C"), [40, 0, 0, 50, 10, 10])

    def testCopyPartThroughThePanel(self):
        panel = self.open("A")
        panel.spins["Y"].setValue(20)
        panel.copy.setChecked(True)
        obj = panel.obj
        self.assertTrue(panel.accept())
        self.assertEqual(self.bounds("A"), [0, 0, 0, 10, 10, 10])
        copies = T.made_parts(obj)
        self.assertEqual(len(copies), 1)
        self.assertEqual(self.bounds(copies[0].Name), [0, 20, 0, 10, 30, 10])

    def testCancelLeavesNothing(self):
        names = {o.Name for o in self.doc.Objects}
        panel = self.open("A")
        panel.spins["X"].setValue(5)
        panel.copy.setChecked(True)
        panel.reject()
        self.assertEqual({o.Name for o in self.doc.Objects}, names)
        self.assertEqual(self.bounds("A"), [0, 0, 0, 10, 10, 10])

    def testScaleThroughThePanel(self):
        """ops#677: Scale with the uniform tick off, about a coordinate system picked in the view."""
        c = self.doc.addObject("App::LocalCoordinateSystem", "Centre")
        self.studio.addObject(c)
        c.Placement = App.Placement(App.Vector(5, 5, 5), App.Rotation())
        self.doc.recompute()
        panel = self.open("A")
        panel.type.setCurrentIndex(T.TYPES.index("Scale"))
        self.assertTrue(panel.uniform.isChecked())  # Onshape's default
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(c)
        panel.pick("ScalePoint")
        panel.uniform.setChecked(False)
        panel.spins["ScaleX"].setValue(2)
        panel.spins["ScaleZ"].setValue(3)
        self.assertTrue(panel.accept())
        # about (5, 5, 5): x -5..15, y 0..10, z -10..20
        self.assertEqual(self.bounds("A"), [-5, 0, -10, 15, 10, 20])

    def testRotateAboutAnAxisPickedInTheView(self):
        panel = self.open("B")
        panel.type.setCurrentIndex(T.TYPES.index("Rotate"))
        Gui.Selection.clearSelection()
        z = self.doc.getObject("A").Origin.OriginFeatures[2]
        Gui.Selection.addSelection(z)
        panel.pick("Axis")
        panel.spins["Angle"].setValue(90)
        self.assertTrue(panel.accept())
        self.assertEqual(self.bounds("B"), [-10, 20, 0, 0, 30, 10])
