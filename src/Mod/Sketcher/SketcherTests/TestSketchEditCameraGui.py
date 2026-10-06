# SPDX-License-Identifier: LGPL-2.1-or-later

"""A sketch in edit reports its bounding box where it is (FreeCAD-CH, ops#144; upstream PR 32611
for upstream issue 31804).

In edit mode `ViewProviderSketch::_getBoundingBox` dropped the sketch's placement
(`bbox.Transformed(m)` discarded its result), so the view fitted on opening a sketch away from
the origin looked at the origin instead: the camera flew off.

Designed geometry: a circle r 5 at the sketch's origin, the sketch placed at (100, 50, 30)."""

import FreeCAD
import Part

from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase

App = FreeCAD
V = App.Vector
TOL = 1e-4  # Coin pads the box by about 1e-7


class TestSketchEditCameraGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        self.doc = App.newDocument("TestSketchEditCameraGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.Placement = App.Placement(V(100, 50, 30), App.Rotation())
        self.sketch.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5), False)
        self.doc.recompute()

    def tearDown(self):
        FreeCADGui.getDocument(self.doc.Name).resetEdit()
        self.flush_gui()
        super().tearDown()

    def testBoundingBoxInEditFollowsPlacement(self):
        FreeCADGui.getDocument(self.doc.Name).setEdit(self.sketch.Name)
        self.flush_gui(100)
        box = self.sketch.ViewObject.getBoundingBox()
        # the circle (95..105, 45..55) and the sketch's origin (100, 50), at z = 30
        self.assertAlmostEqual(box.XMin, 95, delta=TOL)
        self.assertAlmostEqual(box.XMax, 105, delta=TOL)
        self.assertAlmostEqual(box.YMin, 45, delta=TOL)
        self.assertAlmostEqual(box.YMax, 55, delta=TOL)
        self.assertAlmostEqual(box.ZMin, 30, delta=TOL)
        self.assertAlmostEqual(box.ZMax, 30, delta=TOL)
