# SPDX-License-Identifier: LGPL-2.1-or-later

"""The DXF commands in the GUI (FreeCAD-CH, the DXF lane): Insert DXF while a sketch is open,
one undo step; Export DXF of a selected sketch or planar face. Designed geometry only (the files
are written by SketcherTests.TestSketchDxf)."""

import os
import tempfile
import unittest

import FreeCAD
import FreeCADGui
import Part

import SketcherDxf
import SketcherDxfGui
from SketcherTests import TestSketchDxf as T

V = FreeCAD.Vector


def pump():
    from PySide import QtWidgets

    QtWidgets.QApplication.processEvents()


class TestSketchDxfGui(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="dxfgui_")
        self.doc = FreeCAD.newDocument("DxfGui")
        FreeCADGui.activateWorkbench("SketcherWorkbench")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.doc.recompute()

    def tearDown(self):
        if FreeCADGui.ActiveDocument and FreeCADGui.ActiveDocument.getInEdit():
            FreeCADGui.ActiveDocument.resetEdit()
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(self.doc.Name)
        pump()

    def test_commands_registered(self):
        for name in ("Sketcher_InsertDxf", "Sketcher_ExportDxf"):
            self.assertIsNotNone(FreeCADGui.Command.get(name), name)

    def test_insert_needs_an_open_sketch_and_is_one_undo_step(self):
        cmd = SketcherDxfGui.CommandInsertDxf()
        self.assertFalse(cmd.IsActive())
        FreeCADGui.ActiveDocument.setEdit(self.sketch)
        pump()
        self.assertTrue(cmd.IsActive())
        path = T.write(self.dir, "logo.dxf", T.dxf_text(T.lines_text(T.logo_loops())))
        undo = self.doc.UndoCount
        rep = SketcherDxfGui.insert_into(
            self.sketch, path, {"units": None, "fit": True, "tolerance": 0.01, "corner": 30.0, "hold": "block"}
        )
        self.assertLessEqual(rep.max_deviation, 0.01)
        self.assertEqual(len(self.sketch.Geometry), rep.curves)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.assertEqual(len(self.sketch.Geometry), 0)

    def test_export_targets(self):
        box = self.doc.addObject("Part::Box", "Box")
        cyl = self.doc.addObject("Part::Cylinder", "Cyl")
        self.doc.recompute()
        FreeCADGui.Selection.clearSelection()
        self.assertIsNone(SketcherDxfGui.export_target())
        FreeCADGui.Selection.addSelection(self.doc.Name, "Sketch")
        self.assertEqual(SketcherDxfGui.export_target(), (self.sketch, ""))
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, "Box", "Face6")
        self.assertEqual(SketcherDxfGui.export_target(), (box, "Face6"))
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, "Box", "Edge1")
        self.assertIsNone(SketcherDxfGui.export_target())
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, "Cyl", "Face1")  # the cylinder's side
        self.assertIsNone(SketcherDxfGui.export_target())
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, "Box", "Face6")
        path = os.path.join(self.dir, "top.dxf")
        rep = SketcherDxf.export_selection(box, "Face6", path)
        self.assertEqual(rep.entities["LINE"], 4)
        self.assertAlmostEqual(rep.size[0], 10.0, 9)
