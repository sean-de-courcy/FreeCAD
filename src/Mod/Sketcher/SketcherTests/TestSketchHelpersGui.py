# SPDX-License-Identifier: LGPL-2.1-or-later

"""A model pick's helper link goes with its last constraint (ops#634, slice 2).

Onshape constrains a sketch to model geometry with nothing projected, so nothing is left once the
constraint goes. FreeCAD-CH: the constraint needs external geometry, so a model pick's link (made by
a select-first constraint command or a running constraint tool) is marked implicit in its
ExternalTypes entry; deleting the last constraint on it (in the editor or the Constraints list)
deletes it in the same undo step. A link the user added, or took with the External geometry tool,
stays; so does a helper another constraint still uses, or one made defining since.

Designed geometry: TestSketchModelPicksGui's 20 x 10 x 5 box Pad and the sketch on its top (z 5)
with one line from (2, 2) to (8, 2)."""

import os
import shutil
import tempfile

import FreeCAD

from SketcherTests.GuiTestCase import FreeCADGui, QtCore, QtGui
from SketcherTests.TestSketchModelPicksGui import V, ModelPicksGuiCase

IMPLICIT = 0x100  # SketchObject::implicitExternalMark
PROJECTION = 0


class TestSketchHelpersGui(ModelPicksGuiCase):
    def setUp(self):
        super().setUp()
        self.folder = None

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            if self.folder:
                shutil.rmtree(self.folder, ignore_errors=True)

    def corner(self):
        return self.vertex_at(self.pad, V(20, 10, 5))

    def front_edge(self):
        return self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))

    def links(self):
        return [(obj.Name, sub) for obj, subs in self.sketch.ExternalGeometry for sub in subs]

    def pick_coincident(self):
        """The line's end and the box's top corner, then Coincident: one helper link, marked."""
        self.select((self.sketch, "Vertex2"), (self.pad, self.corner()))
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        self.assertEqual(self.links(), [("Pad", self.corner())])
        self.assertEqual(len(self.constraints_of("Coincident")), 1)
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION | IMPLICIT])

    def delete_in_editor(self, *subs):
        self.select(*[(self.sketch, sub) for sub in subs])
        self.run_command("Std_Delete")

    def assertNoHelper(self):
        self.assertEqual(self.links(), [])
        self.assertEqual(len(self.sketch.ExternalGeo), 2)  # the axes
        self.assertEqual(list(self.sketch.ExternalTypes), [])

    def constraint_list(self):
        for widget in FreeCADGui.getMainWindow().findChildren(QtGui.QListWidget):
            if widget.metaObject().className() == "SketcherGui::ConstraintView":
                return widget
        self.skipTest("no Constraints list in the task panel")

    def test_deleting_a_helper_s_constraint_deletes_the_helper(self):
        """The Coincident on a model pick deleted in the editor: its helper link goes too, in
        the deletion's undo step."""
        self.start_edit()
        self.pick_coincident()
        before = self.doc.UndoCount

        self.delete_in_editor("Constraint1")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertNoHelper()
        self.assertEqual(self.doc.UndoCount, before + 1)

    def test_a_link_the_user_added_stays(self):
        """A link added with addExternal (the user's, not marked) and a model pick's helper, a
        constraint on each; both constraints deleted: the helper goes, the user's link stays."""
        self.sketch.addExternal(self.pad.Name, self.front_edge())
        self.doc.recompute()
        self.start_edit()
        self.select((self.sketch, "Vertex1"), (self.sketch, "ExternalEdge1"))
        self.run_command("Sketcher_ConstrainDistance")
        self.assertEqual(len(self.constraints_of("Distance")), 1)
        self.select((self.sketch, "Vertex2"), (self.pad, self.corner()))
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        self.assertEqual(self.links(), [("Pad", self.front_edge()), ("Pad", self.corner())])
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, PROJECTION | IMPLICIT])

        self.delete_in_editor("Constraint1", "Constraint2")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(self.links(), [("Pad", self.front_edge())])
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION])

    def test_a_helper_another_constraint_uses_stays(self):
        """Two constraints on the same model pick (the second reuses its link): deleting the
        first keeps the helper, deleting the second deletes it."""
        self.start_edit()
        self.pick_coincident()
        self.select((self.sketch, "Vertex1"), (self.pad, self.corner()))
        self.run_command("Sketcher_ConstrainDistanceX")
        self.assertEqual(len(self.constraints_of("DistanceX")), 1)
        self.assertEqual(self.links(), [("Pad", self.corner())])

        self.delete_in_editor("Constraint1")
        self.assertEqual(len(self.sketch.Constraints), 1)
        self.assertEqual(self.links(), [("Pad", self.corner())])
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION | IMPLICIT])

        self.delete_in_editor("Constraint1")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertNoHelper()

    def test_undo_restores_the_helper_and_its_constraint_in_one_step(self):
        """The deletion undone: the constraint, the link and its mark come back in one step, and
        the line's end is on the corner again."""
        self.start_edit()
        self.pick_coincident()
        self.delete_in_editor("Constraint1")
        self.assertNoHelper()

        self.doc.undo()
        self.flush_gui(100)
        self.assertEqual(len(self.constraints_of("Coincident")), 1)
        self.assertEqual(self.links(), [("Pad", self.corner())])
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION | IMPLICIT])
        end = self.line_point(2)
        self.assertAlmostEqual(end.x, 20, places=6)
        self.assertAlmostEqual(end.y, 10, places=6)

    def test_deleting_the_line_deletes_its_helper(self):
        """The line deleted (its Coincident goes with it): the helper goes too."""
        self.start_edit()
        self.pick_coincident()
        self.delete_in_editor("Edge1")
        self.assertEqual(len(self.sketch.Geometry), 0)
        self.assertNoHelper()

    def test_the_constraints_list_s_deletes_delete_helpers(self):
        """The Constraints list's Delete all, and its delete of the listed constraints: each
        deletes the helper with the constraint."""
        self.start_edit()
        self.pick_coincident()
        QtCore.QMetaObject.invokeMethod(self.constraint_list(), "deleteAllItems")
        self.flush_gui(100)
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertNoHelper()

        self.doc.undo()
        self.flush_gui(100)
        self.assertEqual(self.links(), [("Pad", self.corner())])
        QtCore.QMetaObject.invokeMethod(self.constraint_list(), "deleteFilterItems")
        self.flush_gui(100)
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertNoHelper()

    def answer_yes(self, timeout_ms=4000):
        """Answers Yes to the question boxes that open (Delete all constraints?)."""
        state = {"waited": 0, "stop": False, "seen": 0}
        self.answerers.append(state)

        def poll():
            if state["stop"]:
                return
            modal = QtGui.QApplication.activeModalWidget()
            if isinstance(modal, QtGui.QMessageBox):
                yes = modal.button(QtGui.QMessageBox.Yes)
                if yes is not None:
                    state["seen"] += 1
                    yes.click()
            state["waited"] += 50
            if state["waited"] < timeout_ms:
                QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)
        return state

    def test_the_toolbar_s_delete_all_constraints_deletes_helpers(self):
        """Sketcher_DeleteAllConstraints, answered Yes: the helper goes with the constraints."""
        self.start_edit()
        self.pick_coincident()
        FreeCADGui.Selection.clearSelection()
        answered = self.answer_yes()
        self.run_command("Sketcher_DeleteAllConstraints")
        self.assertEqual(answered["seen"], 1)
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertNoHelper()

    def test_the_continuous_tool_s_link_is_a_helper(self):
        """The Coincident tool running, the corner then the line's end picked (a click through
        the scene graph, which reaches the tool off screen): the link is a helper and goes with
        the constraint."""
        self.start_edit()
        self.raise_camera()
        FreeCADGui.Selection.clearSelection()
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        FreeCADGui.Selection.addSelection(self.doc.Name, self.pad.Name, self.corner())
        self.flush_gui(100)
        end = V(8, 2, 5)
        for kind in ("move", "down", "up"):
            self.coin_event(kind, end)
        self.flush_gui(100)
        self.key_click(self.viewport, QtCore.Qt.Key_Escape)
        self.flush_gui(100)
        self.assertEqual(len(self.constraints_of("Coincident")), 1)
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION | IMPLICIT])

        self.delete_in_editor("Constraint1")
        self.assertNoHelper()

    def test_the_external_geometry_tool_takes_a_helper(self):
        """The External geometry tool (Sketcher_Projection) on a helper's element: no error, the same link, no longer
        marked; deleting the constraint then keeps it."""
        self.start_edit()
        self.pick_coincident()
        FreeCADGui.Selection.clearSelection()
        self.run_command("Sketcher_Projection")
        FreeCADGui.Selection.addSelection(self.doc.Name, self.pad.Name, self.corner())
        self.flush_gui(100)
        self.key_click(self.viewport, QtCore.Qt.Key_Escape)
        self.flush_gui(100)
        self.assertEqual(self.links(), [("Pad", self.corner())])
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION])

        self.delete_in_editor("Constraint1")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(self.links(), [("Pad", self.corner())])

    def test_a_defining_helper_stays(self):
        """A helper made defining (part of the profile) since: deleting its constraint keeps it."""
        self.start_edit()
        self.pick_coincident()
        self.sketch.toggleConstruction(-3)  # the helper's point: ExternalGeo[2]
        self.delete_in_editor("Constraint1")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(self.links(), [("Pad", self.corner())])

    def test_save_and_reopen_keep_the_mark(self):
        """Saved and opened again: the link is still marked, and deleting its constraint there
        deletes it."""
        self.start_edit()
        self.pick_coincident()
        FreeCADGui.ActiveDocument.resetEdit()
        self.flush_gui(100)
        self.folder = tempfile.mkdtemp(prefix="helpers")
        path = os.path.join(self.folder, "helpers.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.flush_gui(100)

        self.doc = FreeCAD.openDocument(path)
        self.flush_gui(100)
        self.sketch = self.doc.getObject("Sketch")
        self.pad = self.doc.getObject("Pad")
        self.assertEqual(self.links(), [("Pad", self.corner())])
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION | IMPLICIT])

        self.start_edit()
        self.delete_in_editor("Constraint1")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertNoHelper()
