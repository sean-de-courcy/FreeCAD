# SPDX-License-Identifier: LGPL-2.1-or-later

"""The Cancel of a sketch edit leaves no undo step (FreeCAD-CH ops#640, round 5, hands-on B5-5).

Onshape (hands-on B5-5): editing a sketch, changing its dimension and cancelling with the red x
leaves the model as it was and no history entry; Ctrl+Z then undoes the step before the edit.
Cancelling with nothing changed: no entry either (and no toast; the toast is a status-bar
message here). Here the edit's own transactions are undone at
the Cancel, and the Redo stack loses them: the undo and redo lists are as before the edit. The
Redo stack before an edit that changed something is lost at its first change (a commit clears
it); an edit that changed nothing keeps it. A new sketch's Cancel still removes it.

Designed geometry: a 20 x 10 x 5 box (Pad of the Base sketch) and, on its top (z 5), the
Profile sketch: a 4 x 4 square at (2, 2), fully constrained, its bottom line's length a
dimension, padded 3 up (Boss). The boss's volume is computed: 4 x 4 x 3 = 48, 6 x 4 x 3 = 72
with the dimension at 6."""

import time

import FreeCAD
import Part
import Sketcher
from PySide import QtWidgets

from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase

V = FreeCAD.Vector
BOX = 20 * 10 * 5


class TestSketchCancelGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        FreeCADGui.getMainWindow().show()
        FreeCADGui.activateWorkbench("PartDesignWorkbench")
        self.doc = FreeCAD.newDocument(type(self).__name__)
        self.doc.UndoMode = 1
        FreeCADGui.Selection.clearSelection()

        self.doc.openTransaction("Make Box")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        xy = self.body.Origin.OriginFeatures[3]
        base = self.body.newObject("Sketcher::SketchObject", "Base")
        base.AttachmentSupport = [(xy, "")]
        base.MapMode = "FlatFace"
        self.square(base, 0, 0, 20, 10)
        self.doc.recompute()
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = base
        self.pad.Length = 5.0
        self.doc.recompute()
        self.doc.commitTransaction()

        self.doc.openTransaction("Make Boss")
        self.sketch = self.body.newObject("Sketcher::SketchObject", "Profile")
        self.sketch.AttachmentSupport = [(xy, "")]
        self.sketch.MapMode = "FlatFace"
        self.sketch.AttachmentOffset = FreeCAD.Placement(V(0, 0, 5), FreeCAD.Rotation())
        self.dimension = self.square(self.sketch, 2, 2, 4, 4)
        self.doc.recompute()
        self.boss = self.body.newObject("PartDesign::Pad", "Boss")
        self.boss.Profile = self.sketch
        self.boss.Length = 3.0
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertTrue(self.boss.isValid(), self.boss.getStatusString())
        self.assertAlmostEqual(self.boss.Shape.Volume, BOX + 48, places=6)
        self.assertEqual(self.doc.UndoNames, ["Make Boss", "Make Box"])

    def square(self, sketch, x, y, width, height):
        """A fully constrained rectangle; returns its bottom line's length constraint."""
        corners = [V(x, y, 0), V(x + width, y, 0), V(x + width, y + height, 0), V(x, y + height, 0)]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", 2))
        sketch.addConstraint(Sketcher.Constraint("Vertical", 1))
        sketch.addConstraint(Sketcher.Constraint("Vertical", 3))
        sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, x))
        sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, y))
        sketch.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, height))
        return sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, width))

    # helpers --------------------------------------------------------------------------------

    def start_edit(self):
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.pump(200)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected sketch edit mode")

    def set_dimension(self, value):
        """As the dimension's dialog does: its own transaction (Gui::Command's openCommand)."""
        FreeCAD.setActiveTransaction("Modify sketch constraints")
        self.sketch.setDatum(self.dimension, FreeCAD.Units.Quantity(f"{value} mm"))
        FreeCAD.closeActiveTransaction()
        self.sketch.solve()
        self.flush_gui(50)

    def add_line(self):
        FreeCAD.setActiveTransaction("Add sketch line")
        self.sketch.addGeometry(Part.LineSegment(V(10, 2, 0), V(14, 6, 0)), False)
        FreeCAD.closeActiveTransaction()
        self.flush_gui(50)

    def cancel(self):
        """The task panel's Cancel button."""
        dialog = FreeCADGui.Control.activeTaskDialog()
        self.assertIsNotNone(dialog, "Expected the sketch's dialog")
        dialog.reject()
        self.flush_gui(300)
        self.assertIsNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected the edit closed")

    def message(self):
        """The status bar's text: MainWindow::showMessage writes to a label in it."""
        bar = FreeCADGui.getMainWindow().statusBar()
        return " ".join([bar.currentMessage()] + [w.text() for w in bar.findChildren(QtWidgets.QLabel)])

    def wait_for_message(self, text, seconds=2.0):
        """The recomputes after the close clear the status message when they end; the sketch shows
        its message again while they run down: wait for it."""
        end = time.time() + seconds
        while time.time() < end:
            if text in self.message():
                return True
            self.flush_gui(50)
        return text in self.message()

    def datum(self):
        return self.sketch.Constraints[self.dimension].Value

    def assert_as_before(self, undo, redo):
        self.assertAlmostEqual(self.datum(), 4.0, places=9)
        self.assertEqual(len(self.sketch.Geometry), 4)
        self.assertEqual(self.doc.UndoNames, undo, "Expected no step left by the Cancel")
        self.assertEqual(self.doc.RedoNames, redo)
        self.doc.recompute()
        self.assertTrue(self.boss.isValid(), self.boss.getStatusString())
        self.assertAlmostEqual(self.boss.Shape.Volume, BOX + 48, places=6)

    # tests ----------------------------------------------------------------------------------

    def test_cancel_of_a_changed_dimension_leaves_no_step(self):
        """B5-5: 4 -> 6, Cancel: 4 again, the undo list as before the edit, nothing to redo;
        Std_Undo then undoes the step before the edit ("Make Boss")."""
        undo = self.doc.UndoNames
        self.start_edit()
        self.set_dimension(6)
        self.assertAlmostEqual(self.datum(), 6.0, places=9)
        self.assertEqual(self.doc.UndoNames[0], "Modify sketch constraints")
        self.cancel()
        # Onshape's toast "Sketch 2 has been canceled.": here a status-bar message
        self.assertTrue(self.wait_for_message("Profile has been canceled"), self.message())
        self.assertFalse(self.doc.mustExecute(), "Expected nothing left to regenerate")
        self.assert_as_before(undo, [])
        FreeCADGui.runCommand("Std_Undo")
        self.flush_gui(200)
        self.assertEqual(self.doc.UndoNames, ["Make Box"])
        self.assertIsNone(self.doc.getObject("Boss"), "Expected Std_Undo to undo Make Boss")

    def test_unchanged_cancel_leaves_nothing_and_keeps_the_redo_list(self):
        """Cancel with nothing changed: no step, and a Redo list from before the edit stays."""
        self.doc.openTransaction("Boss length")
        self.boss.Length = 4.0
        self.doc.commitTransaction()
        self.doc.undo()
        self.flush_gui(50)
        undo = self.doc.UndoNames
        self.assertEqual(self.doc.RedoNames, ["Boss length"])
        for label in FreeCADGui.getMainWindow().statusBar().findChildren(QtWidgets.QLabel):
            if "has been canceled" in label.text():
                label.setText("")  # an earlier test's message
        self.start_edit()
        self.cancel()
        self.assertNotIn("has been canceled", self.message(), "Expected no message for no change")
        self.assert_as_before(undo, ["Boss length"])
        FreeCADGui.runCommand("Std_Redo")
        self.flush_gui(200)
        self.assertAlmostEqual(self.boss.Length.Value, 4.0, places=9)

    def test_cancel_after_a_change_undone_in_the_edit_leaves_nothing_to_redo(self):
        """4 -> 6, Std_Undo inside the sketch (6 -> 4, the change on the Redo list), Cancel: no
        step and nothing to redo (Ctrl+Y can't bring back a cancelled edit's change)."""
        undo = self.doc.UndoNames
        self.start_edit()
        self.set_dimension(6)
        FreeCADGui.runCommand("Std_Undo")
        self.flush_gui(100)
        self.assertAlmostEqual(self.datum(), 4.0, places=9)
        self.assertEqual(self.doc.RedoNames, ["Modify sketch constraints"])
        self.cancel()
        self.assert_as_before(undo, [])

    def test_cancel_command_undoes_every_change_of_the_edit(self):
        """Two changes (the dimension, a line), Sketcher_CancelSketch: both gone, no step."""
        undo = self.doc.UndoNames
        self.start_edit()
        self.set_dimension(6)
        self.add_line()
        self.assertEqual(len(self.sketch.Geometry), 5)
        FreeCADGui.runCommand("Sketcher_CancelSketch")
        self.flush_gui(300)
        self.assertIsNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected the edit closed")
        self.assert_as_before(undo, [])

    def test_cancel_of_a_new_sketch_still_removes_it(self):
        """PartDesign_NewSketch on the boss's top (Onshape's keymap marks it new), a line drawn,
        Cancel: the sketch is gone, in its own step, which Ctrl+Z undoes (hands-on R1)."""
        top = None
        for i, face in enumerate(self.boss.Shape.Faces):
            box = face.BoundBox
            if abs(box.ZMin - 8) < 1e-9 and abs(box.ZMax - 8) < 1e-9:
                top = "Face%d" % (i + 1)
        self.assertIsNotNone(top, "Expected the boss's top face")
        before = {o.Name for o in self.doc.Objects}
        FreeCADGui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        FreeCADGui.Selection.addSelection(self.doc.Name, self.body.Name, "Boss." + top)
        self.flush_gui(200)
        FreeCADGui.runCommand("PartDesign_NewSketch")
        self.flush_gui(800)
        made = [
            o
            for o in self.doc.Objects
            if o.Name not in before and o.isDerivedFrom("Sketcher::SketchObject")
        ]
        self.assertEqual(len(made), 1, [o.Name for o in self.doc.Objects])
        name = made[0].Name
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected the new sketch in edit")
        if not FreeCADGui.Control.activeTaskDialog():
            self.fail("Expected the new sketch's dialog")
        made[0].addGeometry(Part.LineSegment(V(0, 0, 0), V(3, 0, 0)))
        self.flush_gui(100)
        self.cancel()
        if self.doc.getObject(name) is not None:
            keymap = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").GetString(
                "Keymap", "Onshape"
            )
            if keymap == "FreeCAD":
                self.skipTest("FreeCAD's keymap: a new sketch's Cancel keeps it")
            self.fail("Expected the cancelled new sketch removed")
        self.doc.undo()
        self.flush_gui(300)
        self.assertIsNotNone(self.doc.getObject(name), "Expected Ctrl+Z to bring the sketch back")
