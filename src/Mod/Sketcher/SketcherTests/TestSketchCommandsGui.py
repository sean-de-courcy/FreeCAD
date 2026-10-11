# SPDX-License-Identifier: LGPL-2.1-or-later

"""Sketcher commands' silent-pick Lows (ops#252), in the GUI.

- Reorient Sketch cleared a sketch's support before its orientation dialog, outside any
  transaction: a cancel left the sketch detached, and an undo didn't attach it again.
- Attach Sketch (Sketcher_MapSketch) took the chosen sketch by its label's text, so of two
  sketches with one label, the first was attached whichever row was chosen.
- Select Associated Geometry named a constraint's axes Edge0 and Edge-1.

Designed geometry: a 10 x 10 x 10 box whose top face carries the sketches."""

import FreeCAD
import Part
import Sketcher

from SketcherTests.GuiTestCase import FreeCADGui, QtCore, QtGui, SketcherGuiTestCase

V = FreeCAD.Vector


class TestSketchCommandsGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        self.doc = FreeCAD.newDocument("TestSketchCommandsGui")
        self.box = self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        self.top = next(
            "Face%d" % (i + 1)
            for i, f in enumerate(self.box.Shape.Faces)
            if abs(f.CenterOfMass.z - 10) < 1e-9
        )
        self.answerers = []

    def tearDown(self):
        for state in self.answerers:
            state["stop"] = True
        FreeCADGui.Selection.clearSelection()
        super().tearDown()

    def answer_modals(self, answers, timeout_ms=5000):
        """Answers the modal windows as they open, one function of the window each, in order.
        A modal window left over after the last answer is rejected, so a failure doesn't hang
        the run."""
        state = {"answers": list(answers), "waited": 0, "stop": False}
        self.answerers.append(state)

        def poll():
            if state["stop"]:
                return
            modal = QtGui.QApplication.activeModalWidget()
            # marked on the window itself: the next dialog can take a closed one's address
            if modal is not None and not modal.property("answeredByTest"):
                modal.setProperty("answeredByTest", True)
                if state["answers"]:
                    state["answers"].pop(0)(modal)
                else:
                    modal.reject()
            state["waited"] += 50
            if state["waited"] < timeout_ms:
                QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)
        return state

    @staticmethod
    def press(button):
        def answer(box):
            box.button(button).click()

        return answer

    @staticmethod
    def accept(dialog):
        dialog.accept()

    @staticmethod
    def reject(dialog):
        dialog.reject()

    def attached_sketch(self, name="Sketch"):
        sketch = self.doc.addObject("Sketcher::SketchObject", name)
        sketch.AttachmentSupport = [(self.box, self.top)]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        self.assertAlmostEqual(sketch.Placement.Base.z, 10, delta=1e-9)
        return sketch

    def reorient(self, sketch, answers):
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, sketch.Name)
        state = self.answer_modals(answers)
        FreeCADGui.runCommand("Sketcher_ReorientSketch")
        self.flush_gui(100)
        self.assertEqual(state["answers"], [])

    def test_reorient_cancelled_keeps_the_support(self):
        """Detach: Yes, then the orientation dialog cancelled: the sketch keeps its support."""
        sketch = self.attached_sketch()
        self.reorient(sketch, [self.press(QtGui.QMessageBox.Yes), self.reject])
        self.assertEqual(sketch.AttachmentSupport, [(self.box, (self.top,))])
        self.doc.recompute()
        self.assertAlmostEqual(sketch.Placement.Base.z, 10, delta=1e-9)

    def test_reorient_detaches_in_its_transaction(self):
        """Detach: Yes, then the orientation accepted: the sketch is detached and placed, and the
        undo of "Reorient sketch" attaches it again."""
        self.doc.UndoMode = 1
        sketch = self.attached_sketch()
        self.reorient(sketch, [self.press(QtGui.QMessageBox.Yes), self.accept])
        FreeCADGui.ActiveDocument.resetEdit()
        self.flush_gui(100)
        self.assertEqual(sketch.AttachmentSupport, [])
        # the edit session Reorient opens may have its own undo step above Reorient's
        names = self.doc.UndoNames
        self.assertIn("Reorient sketch", names)
        for _ in range(names.index("Reorient sketch") + 1):
            self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sketch.AttachmentSupport, [(self.box, (self.top,))])

    def test_attach_takes_the_chosen_sketch_of_two_with_one_label(self):
        """Two sketches labelled Profile: the second row is chosen, and that sketch is attached
        to the box's top face; the other stays where it is. The rows name the sketches."""
        params = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document")
        duplicates = params.GetBool("DuplicateLabels", False)
        params.SetBool("DuplicateLabels", True)
        try:
            first = self.doc.addObject("Sketcher::SketchObject", "First")
            second = self.doc.addObject("Sketcher::SketchObject", "Second")
            first.Label = "Profile"
            second.Label = "Profile"
            self.doc.recompute()
            self.assertEqual(first.Label, second.Label)
        finally:
            params.SetBool("DuplicateLabels", duplicates)
        rows = []

        def choose_second(dialog):
            items = dialog.comboBoxItems()
            rows.extend(items)
            combo = dialog.findChild(QtGui.QComboBox)
            index = next((i for i, t in enumerate(items) if "(Second)" in t), len(items) - 1)
            combo.setCurrentIndex(index)
            dialog.accept()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.box.Name, self.top)
        state = self.answer_modals([choose_second, self.accept])
        FreeCADGui.runCommand("Sketcher_MapSketch")
        self.flush_gui(100)
        self.assertEqual(state["answers"], [])
        self.assertEqual(sorted(rows), ["Profile (First)", "Profile (Second)"])
        self.doc.recompute()
        self.assertEqual(second.AttachmentSupport, [(self.box, (self.top,))])
        self.assertEqual(first.AttachmentSupport, [])

    def test_select_associated_names_the_axes(self):
        """A line whose start is on the H axis and end on the V axis: selecting the two
        constraints' geometry selects both vertices and the two axes, by their names."""
        sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        sketch.addGeometry(Part.LineSegment(V(5, 0, 0), V(0, 5, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", 0, 1, -1))
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", 0, 2, -2))
        self.doc.recompute()
        FreeCADGui.ActiveDocument.setEdit(sketch.Name)
        self.flush_gui(100)
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, sketch.Name, "Constraint1")
        FreeCADGui.Selection.addSelection(self.doc.Name, sketch.Name, "Constraint2")
        FreeCADGui.runCommand("Sketcher_SelectElementsAssociatedWithConstraints")
        self.flush_gui(100)
        names = [
            name
            for sel in FreeCADGui.Selection.getSelectionEx()
            if sel.Object == sketch
            for name in sel.SubElementNames
        ]
        self.assertEqual(sorted(names), ["H_Axis", "V_Axis", "Vertex1", "Vertex2"])
