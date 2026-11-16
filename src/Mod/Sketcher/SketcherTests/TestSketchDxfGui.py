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

    def test_insert_dialog_defaults_are_onshapes(self):
        """Onshape's Insert (DX1-DX4): the Units field is shown and applies even when the file
        states units, starting at the document's unit; "Use file origin position" is off; Block is
        off, and a Block choice stored by an earlier build is reset once"""
        p = FreeCAD.ParamGet(SketcherDxfGui.PARAMS)
        saved = {
            "Block": (p.GetBool("Block", True), "Bool"),
            "UseFileOrigin": (p.GetBool("UseFileOrigin", False), "Bool"),
            SketcherDxfGui.BLOCK_RESET: (p.GetBool(SketcherDxfGui.BLOCK_RESET, False), "Bool"),
        }
        system = self.doc.UnitSystem
        try:
            # an earlier build's user: Block stored on, never reset
            p.SetBool("Block", True)
            p.RemBool(SketcherDxfGui.BLOCK_RESET)
            p.RemBool("UseFileOrigin")
            # a document in an inch unit system
            inch = [
                s
                for s in self.doc.getEnumerationsOfProperty("UnitSystem")
                if (setattr(self.doc, "UnitSystem", s) or SketcherDxfGui.document_units(self.doc)) == "in"
            ]
            self.assertTrue(inch, "no inch unit system")
            self.doc.UnitSystem = inch[0]
            ents = T._lwrect(10.0, 20.0, 50.0, 40.0)
            path = T.write(self.dir, "rect.dxf", T.dxf_text(ents, insunits=4))  # the file says mm
            dlg = SketcherDxfGui.InsertDialog(SketcherDxf.read(path), path, self.doc)
            v = dlg.values()
            dlg.d.deleteLater()
            self.assertEqual(v["units"], "in")
            self.assertEqual(v["origin"], "centre")
            self.assertEqual(v["hold"], "free")
            self.assertTrue(p.GetBool(SketcherDxfGui.BLOCK_RESET, False))
            # a Block chosen after the reset is kept
            p.SetBool("Block", True)
            dlg = SketcherDxfGui.InsertDialog(SketcherDxf.read(path), path, self.doc)
            self.assertEqual(dlg.values()["hold"], "block")
            dlg.d.deleteLater()
            # the defaults' insert: centred, in inches, no constraints
            rep = SketcherDxfGui.insert_into(self.sketch, path, v)
            self.assertEqual(self.sketch.ConstraintCount, 0)
            bb = self.sketch.Shape.BoundBox
            for got, want in ((bb.XMin, -508.0), (bb.XMax, 508.0), (bb.YMin, -254.0), (bb.YMax, 254.0)):
                self.assertAlmostEqual(got, want, 6)
            self.assertEqual(rep.units, "in")
        finally:
            self.doc.UnitSystem = system
            for k, (val, _) in saved.items():
                p.SetBool(k, val)

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
