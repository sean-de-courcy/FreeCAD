# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, notes/measured-variables-design.md in the ops repo)

"""Measured variables in the GUI, as Onshape's Variable feature in the measured mode: the
Variables panel's Add offers the measured kinds, a task dialog takes picks in the 3D view and
resolves each to the feature that made the element, the value shows live in the panel, and a lost
reference shows the variable failed with its users.

Designed geometry, in part studio P (the active tab):
- Body A: a sketch on XY, a 20 x 10 rectangle with its corner on the origin (constraint W),
  padded 5 mm. Its bottom long edge (y = 0, z = 0) is 20 mm long.
- Sometimes a second pad in A, a 4 x 4 square at (5, 2) on a plane 5 mm up, padded 3 mm: it
  leaves the bottom edges alone.
- Body B: a 4 x 4 square at x = 40, padded by `#w`.
Every expected value is a length read from that geometry."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Sketcher
from FreeCAD import Vector as V

from PySide import QtCore, QtWidgets

# VariablesModel's roles and columns (src/Gui/VariablesView.h)
VariableRole = QtCore.Qt.UserRole + 4
NAME, TYPE, EXPRESSION, VALUE, DESCRIPTION, SOURCE = range(6)


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(condition, seconds=5.0):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    value = condition()
    while not value and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
        value = condition()
    return value


def rectangle(sketch, x, y, w, h, name=None):
    first = sketch.GeometryCount
    pts = [V(x, y, 0), V(x + w, y, 0), V(x + w, y + h, 0), V(x, y + h, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", first))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", first + 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", first + 1))
    sketch.addConstraint(Sketcher.Constraint("Vertical", first + 3))
    sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, first, 1, x))
    sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, first, 1, y))
    c = sketch.addConstraint(Sketcher.Constraint("DistanceX", first, 1, first, 2, w))
    if name:
        sketch.renameConstraint(c, name)
    sketch.addConstraint(Sketcher.Constraint("DistanceY", first + 1, 1, first + 1, 2, h))


def edge_named(shape, test):
    found = ["Edge%d" % i for i, e in enumerate(shape.Edges, 1) if test(e)]
    assert len(found) == 1, found
    return found[0]


def bottom_long(e):
    return abs(e.Length - 20) < 1e-6 and e.BoundBox.YMax < 1e-6 and e.BoundBox.ZMax < 1e-6


def dockOf(widget):
    while widget is not None and not isinstance(widget, QtWidgets.QDockWidget):
        widget = widget.parentWidget()
    return widget


class TestMeasuredVariablesGui(unittest.TestCase):
    def setUp(self):
        from freecad.variables import measured, measuredgui

        self.measured = measured
        self.gui = measuredgui
        Gui.activateWorkbench("PartDesignWorkbench")
        self.doc = App.newDocument("MeasuredVariablesGui")
        self.doc.UndoMode = 1
        self.studio = self.doc.addObject("App::Part", "P")
        self.bodyA = self.doc.addObject("PartDesign::Body", "BodyA")
        self.studio.addObject(self.bodyA)
        self.sketchA = self.sketch(self.bodyA, "SketchA")
        rectangle(self.sketchA, 0, 0, 20, 10, name="W")
        self.padA = self.bodyA.newObject("PartDesign::Pad", "PadA")
        self.padA.Profile = self.sketchA
        self.padA.Length = 5
        self.doc.recompute()
        try:
            Gui.DocumentTabs.switchTo(self.doc, self.studio.Name)
        except Exception:
            pass  # the tabs are off: the only App::Part is the studio
        pump(0.2)
        self.panel = Gui.getMainWindow().findChild(QtWidgets.QWidget, "Variables")
        self.assertIsNotNone(self.panel, "no Variables panel")
        self.tree = self.panel.findChild(QtWidgets.QTreeView, "variablesTree")
        dock = dockOf(self.panel)
        if dock is not None:
            dock.show()
        pump(0.3)

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        if self.gui.current is not None:
            self.gui.current.observe(False)
            self.gui.current = None
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(w, QtWidgets.QDialog) and w.isVisible():
                w.reject()
        pump(0.1)
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        dock = dockOf(self.panel)
        if dock is not None:
            dock.hide()
        pump(0.1)

    # helpers

    def sketch(self, body, name):
        sk = body.newObject("Sketcher::SketchObject", name)
        sk.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        sk.MapMode = "FlatFace"
        return sk

    def top_pad(self):
        sk = self.sketch(self.bodyA, "Pad2Sketch")
        sk.AttachmentOffset = App.Placement(V(0, 0, 5), App.Rotation())
        rectangle(sk, 5, 2, 4, 4)
        pad = self.bodyA.newObject("PartDesign::Pad", "Pad2")
        pad.Profile = sk
        pad.Length = 3
        self.doc.recompute()
        return pad

    def make_user(self, expression="#w"):
        self.bodyB = self.doc.addObject("PartDesign::Body", "BodyB")
        self.studio.addObject(self.bodyB)
        sk = self.sketch(self.bodyB, "SketchB")
        rectangle(sk, 40, 0, 4, 4)
        self.padB = self.bodyB.newObject("PartDesign::Pad", "PadB")
        self.padB.Profile = sk
        self.padB.setExpression("Length", expression)
        self.doc.recompute()
        return self.padB

    def action(self, name):
        for candidate in self.panel.findChildren(QtCore.QObject, name):
            if hasattr(candidate, "trigger"):
                return candidate
        self.fail("no action " + name)

    def openAddDialog(self):
        self.action("addVariable").trigger()
        dialog = waitFor(lambda: [w for w in QtWidgets.QApplication.topLevelWidgets()
                                  if w.objectName() == "addVariableDialog" and w.isVisible()])
        self.assertTrue(dialog, "no Add variable dialog")
        return dialog[0]

    def chooseType(self, dialog, text):
        box = dialog.findChild(QtWidgets.QComboBox, "type")
        index = box.findText(text)
        self.assertGreaterEqual(index, 0, text)
        box.setCurrentIndex(index)
        pump(0.05)
        return box

    def addMeasured(self, name, kind_text):
        """The panel's Add with a measured kind; returns the measured variable dialog's panel."""
        dialog = self.openAddDialog()
        dialog.findChild(QtWidgets.QLineEdit, "name").setText(name)
        self.chooseType(dialog, kind_text)
        dialog.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok).click()
        pump(0.3)
        import shiboken6

        # The Add dialog deletes itself on OK (macOS real-window run, measured variables 3)
        open_ = shiboken6.isValid(dialog) and dialog.isVisible()
        error = dialog.findChild(QtWidgets.QLabel, "error") if open_ else None
        self.assertIsNone(error and error.text() or None, error and error.text())
        panel = waitFor(lambda: self.gui.current)
        self.assertIsNotNone(panel, "no measured variable dialog")
        return panel

    def pick(self, sub):
        Gui.Selection.addSelection(self.doc.Name, self.studio.Name, sub)
        pump(0.1)

    def rows(self):
        """{variable name: (header text, index in column 0)}."""
        pump(0.4)
        model = self.tree.model()
        result = {}
        for row in range(model.rowCount()):
            header = model.index(row, 0)
            for child in range(model.rowCount(header)):
                index = model.index(child, NAME, header)
                result[model.data(index)] = (model.data(header), index)
        return result

    def cell(self, name, column):
        index = self.rows()[name][1]
        return index.sibling(index.row(), column)

    def text(self, name, column):
        return self.tree.model().data(self.cell(name, column))

    # --- the Add dialog

    def test_add_offers_measured_kinds(self):
        dialog = self.openAddDialog()
        box = dialog.findChild(QtWidgets.QComboBox, "type")
        texts = [box.itemText(i) for i in range(box.count())]
        for kind in ("Measured distance", "Measured length", "Measured diameter"):
            self.assertIn(kind, texts)
        self.chooseType(dialog, "Measured length")
        self.assertFalse(dialog.findChild(QtWidgets.QLineEdit, "value").isEnabled())
        self.assertFalse(dialog.findChild(QtWidgets.QComboBox, "set").isEnabled())
        self.chooseType(dialog, "Length")
        self.assertTrue(dialog.findChild(QtWidgets.QLineEdit, "value").isEnabled())

    def test_add_refuses_a_bad_name(self):
        dialog = self.openAddDialog()
        dialog.findChild(QtWidgets.QLineEdit, "name").setText("2w")
        self.chooseType(dialog, "Measured length")
        dialog.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok).click()
        pump(0.3)
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.findChild(QtWidgets.QLabel, "error").text())
        self.assertIsNone(self.gui.current)

    # --- picks

    def test_length_from_a_pick(self):
        panel = self.addMeasured("w", "Measured length")
        edge = edge_named(self.padA.Shape, bottom_long)
        self.pick("{}.{}.{}".format(self.bodyA.Name, self.padA.Name, edge))
        self.assertEqual([(o.Name, s) for o, s in panel.references()], [(self.padA.Name, edge)])
        self.assertAlmostEqual(panel.value, 20, places=6)
        self.assertIn("20", panel.form.findChild(QtWidgets.QLabel, "value").text())
        self.assertTrue(panel.accept())
        pump(0.3)
        holder = self.doc.getObjectsByLabel("w (measured)")[0]
        self.assertAlmostEqual(holder.w.Value, 20, places=6)
        self.assertIsNone(self.gui.current)
        # one undo step takes it all back
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse(self.doc.getObjectsByLabel("w (measured)"))

    def test_pick_reads_the_feature_it_was_picked_on(self):
        """Onshape's variable reads the geometry at its own place: an edge picked on the tip is
        the tip's, even where an earlier pad has the same edge (ops#640, integrator 12's review)."""
        pad2 = self.top_pad()
        panel = self.addMeasured("w", "Measured length")
        tip_edge = edge_named(pad2.Shape, bottom_long)
        self.pick("{}.{}.{}".format(self.bodyA.Name, pad2.Name, tip_edge))
        (feature, element), = panel.references()
        self.assertIs(feature, pad2)
        self.assertEqual(element, tip_edge)
        self.assertEqual(panel.list.item(0).text(), pad2.Label + "." + element)

    def face(self, test):
        return ["Face%d" % i for i, f in enumerate(self.padA.Shape.Faces, 1) if test(f)][0]

    def test_distance_options(self):
        """Onshape's MV0: Minimum or Maximum, Use axis with Minimum only, Value to record; the row
        says what it records."""
        panel = self.addMeasured("d", "Measured distance")
        self.assertTrue(panel.distanceBox.isVisibleTo(panel.form))
        self.assertTrue(panel.useAxisBox.isVisibleTo(panel.form))
        self.assertTrue(panel.recordBox.isVisibleTo(panel.form))
        self.assertFalse(panel.radiusBox.isVisibleTo(panel.form))
        x0 = self.face(lambda f: f.BoundBox.XMax < 1e-6)
        x1 = self.face(lambda f: f.BoundBox.XMin > 20 - 1e-6)
        self.pick("{}.{}.{}".format(self.bodyA.Name, self.padA.Name, x0))
        self.pick("{}.{}.{}".format(self.bodyA.Name, self.padA.Name, x1))
        self.assertAlmostEqual(panel.value, 20, places=6)
        self.assertIn("20", panel.axisLabel.text())
        # a third pick is refused, loudly
        top = self.face(lambda f: f.BoundBox.ZMin > 5 - 1e-6)
        self.pick("{}.{}.{}".format(self.bodyA.Name, self.padA.Name, top))
        self.assertEqual(len(panel.references()), 2)
        self.assertTrue(panel.errorLabel.text())
        panel.useAxisBox.setChecked(True)  # two planes have no axis: unchanged
        pump(0.05)
        self.assertAlmostEqual(panel.value, 20, places=6)
        panel.distanceBox.setCurrentIndex(panel.distanceBox.findData("Maximum"))
        pump(0.05)
        self.assertFalse(panel.useAxisBox.isVisibleTo(panel.form))
        self.assertAlmostEqual(panel.value, (20 ** 2 + 10 ** 2 + 5 ** 2) ** 0.5, places=6)
        panel.recordBox.setCurrentIndex(panel.recordBox.findData("Y"))
        pump(0.05)
        self.assertAlmostEqual(panel.value, 10, places=6)
        self.assertTrue(panel.accept())
        pump(0.3)
        holder = self.doc.getObjectsByLabel("d (measured)")[0]
        self.assertAlmostEqual(holder.d.Value, 10, places=6)
        m = self.measured.measurement_of(holder, "d")
        self.assertEqual((m.DistanceType, m.ValueToRecord), ("Maximum", "Y"))
        self.assertEqual(self.text("d", EXPRESSION),
                         "Distance along Y (maximum) of PadA.{}, PadA.{}".format(x0, x1))

    def test_diameter_radius_option(self):
        """Onshape's MV3: Radius records the radius; the row says so."""
        self.sketchA.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 2))
        self.doc.recompute()
        edge = ["Edge%d" % i for i, e in enumerate(self.padA.Shape.Edges, 1)
                if isinstance(e.Curve, Part.Circle) and e.BoundBox.ZMax < 1e-6][0]
        panel = self.addMeasured("r", "Measured diameter")
        self.assertTrue(panel.radiusBox.isVisibleTo(panel.form))
        self.assertFalse(panel.distanceBox.isVisibleTo(panel.form))
        self.pick("{}.{}.{}".format(self.bodyA.Name, self.padA.Name, edge))
        self.assertAlmostEqual(panel.value, 4, places=6)
        panel.radiusBox.setChecked(True)
        pump(0.05)
        self.assertAlmostEqual(panel.value, 2, places=6)
        self.assertTrue(panel.accept())
        pump(0.3)
        holder = self.doc.getObjectsByLabel("r (measured)")[0]
        self.assertAlmostEqual(holder.r.Value, 2, places=6)
        self.assertEqual(self.text("r", EXPRESSION), "Radius of PadA." + edge)

    def test_length_of_a_sketch_picked_whole(self):
        """Onshape's MV2: Length takes a wire body (a sketch picked in the tree): A's rectangle, 60."""
        panel = self.addMeasured("p", "Measured length")
        self.pick("{}.{}.".format(self.bodyA.Name, self.sketchA.Name))
        self.assertEqual([(o.Name, s) for o, s in panel.references()], [(self.sketchA.Name, "")])
        self.assertAlmostEqual(panel.value, 60, places=6)

    def test_pick_in_another_studio_refused(self):
        other = self.doc.addObject("App::Part", "Q")
        box = self.doc.addObject("Part::Box", "Block")
        other.addObject(box)
        self.doc.recompute()
        panel = self.addMeasured("w", "Measured length")
        Gui.Selection.addSelection(self.doc.Name, other.Name, box.Name + ".Edge1")
        pump(0.1)
        self.assertEqual(panel.references(), [])
        self.assertIn("Part Studio", panel.errorLabel.text())

    # --- the panel

    def add_w(self):
        edge = edge_named(self.padA.Shape, bottom_long)
        self.doc.openTransaction("add w")
        holder, m = self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        self.doc.commitTransaction()
        self.doc.recompute()
        return holder, m, edge

    def test_row_under_the_studio_set(self):
        holder, m, edge = self.add_w()
        own = self.measured.studio_variables(self.studio)
        rows = self.rows()
        self.assertIn("w", rows)
        self.assertEqual(rows["w"][0], own.Label)  # folded under the studio's own set
        self.assertEqual(self.text("w", SOURCE), "measured length")
        self.assertEqual(self.text("w", EXPRESSION), "Length of PadA." + edge)
        self.assertIn("20", self.text("w", VALUE))
        flags = self.tree.model().flags(self.cell("w", EXPRESSION))
        self.assertFalse(flags & QtCore.Qt.ItemFlag.ItemIsEditable)

    def test_value_is_live(self):
        holder, m, edge = self.add_w()
        self.assertIn("20", self.text("w", VALUE))
        self.sketchA.setDatum("W", App.Units.Quantity("30 mm"))
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: "30" in (self.text("w", VALUE) or "")))

    def test_lost_reference_shows_failed(self):
        holder, m, edge = self.add_w()
        user = self.make_user("#w")
        self.doc.removeObject(self.padA.Name)
        self.doc.recompute()
        self.assertIn("Invalid", m.State)
        self.assertIn("Invalid", user.State)
        self.assertEqual(self.text("w", VALUE), "failed")
        tip = self.tree.model().data(self.cell("w", VALUE), QtCore.Qt.ToolTipRole)
        self.assertIn("lost reference", tip)
        self.assertIn("PadB", tip)

    def test_double_click_reopens_the_dialog(self):
        holder, m, edge = self.add_w()
        index = self.cell("w", VALUE)
        self.tree.doubleClicked.emit(index)
        panel = waitFor(lambda: self.gui.current)
        self.assertIsNotNone(panel)
        self.assertIs(panel.measurement, m)
        self.assertEqual([(o.Name, s) for o, s in panel.references()], [(self.padA.Name, edge)])
        # change it to the short edge: 10 mm
        short = edge_named(self.padA.Shape, lambda e: abs(e.Length - 10) < 1e-6
                           and e.BoundBox.XMax < 1e-6 and e.BoundBox.ZMax < 1e-6)
        panel.refs = []
        self.pick("{}.{}.{}".format(self.bodyA.Name, self.padA.Name, short))
        error = panel.errorLabel.text()  # read first: an accepted dialog deletes itself
        self.assertTrue(panel.accept(), error)
        pump(0.2)
        self.assertAlmostEqual(holder.w.Value, 10, places=6)

    def test_delete_removes_its_holder_and_measurement(self):
        holder, m, edge = self.add_w()
        names = holder.Name, m.Name
        self.tree.setCurrentIndex(self.cell("w", NAME))
        self.action("deleteVariable").trigger()
        pump(0.3)
        self.assertIsNone(self.doc.getObject(names[0]))
        self.assertIsNone(self.doc.getObject(names[1]))
        self.assertNotIn("w", self.rows())


if __name__ == "__main__":
    unittest.main()
