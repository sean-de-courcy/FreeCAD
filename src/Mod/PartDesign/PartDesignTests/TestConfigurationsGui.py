# SPDX-License-Identifier: LGPL-2.1-or-later

"""The configurations' GUI, Onshape's (FreeCAD-CH ops#671, slice C2; notes/configurations-design.md
3.8 and the CP2 answers in notes/onshape-facts.md): the Configuration panel, the configuration
items of a field's menu, the configured field's marker and typing, and the active-configuration bar
above the Features list. Designed geometry: TestConfigurations' studio (parts A, B, C: 10 x 10 pads
of height 10; a cut owner E on B) with a List "Size" (Small = the row "Default", Large)."""

import json
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from PartDesign import ConfigurationsGui
from PartDesignTests.TestFeaturesViewGui import pump, waitFor
from PartDesignTests.TestStudioList import makeOwner, newStudio

TOL = 1e-6


def height(body):
    return body.Shape.BoundBox.ZMax - body.Shape.BoundBox.ZMin


def menuActions(widget, pos=QtCore.QPoint(4, 4)):
    """The object names of the actions of widget's context menu (the menu is closed again)"""
    names = []

    def grab():
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(w, QtWidgets.QMenu) and w.isVisible():
                names.extend(a.objectName() for a in w.actions())
                w.close()

    QtCore.QTimer.singleShot(300, grab)
    event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, widget.mapToGlobal(pos))
    QtWidgets.QApplication.sendEvent(widget, event)
    pump()
    return names


class TestConfigurationsGui(unittest.TestCase):
    def setUp(self):
        Gui.activateWorkbench("PartDesignWorkbench")
        self.doc, self.studio = newStudio("TestConfigurationsGui")
        self.A, self.B, self.C = (self.doc.getObject(n) for n in "ABC")
        self.APad = self.doc.getObject("APad")
        self.E = makeOwner(self.doc, self.studio, "E", (22, 2, 25, 5), 2, "Subtraction", ["B"])
        self.edit(lambda: PartDesign.studioInsert(self.E, -1))
        self.size = self.edit(lambda: PartDesign.configAddList(self.studio, "Size", ["Small", "Large"]))
        self.cfg = PartDesign.configStudio(self.studio)
        self.savedTree = None

    def tearDown(self):
        guiDoc = Gui.getDocument(self.doc.Name)
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        ConfigurationsGui.closePanel()
        pump()
        App.closeDocument(self.doc.Name)
        if self.savedTree is not None:
            self.showTree(self.savedTree)
        pump()

    def edit(self, fn):
        self.doc.openTransaction("edit")
        out = fn()
        self.doc.recompute()
        self.doc.commitTransaction()
        return out

    def configureSizes(self):
        """A's pad: Small 10, Large 20; E suppressed in Small only"""
        self.edit(lambda: PartDesign.configConfigure(self.APad, "Length", self.size))
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "20 mm"))
        self.edit(lambda: PartDesign.configConfigureSuppression(self.E, self.size))
        self.edit(lambda: PartDesign.configSetSuppressionCell(self.E, "Small", True))

    def inputs(self):
        return json.loads(self.cfg.Inputs)["inputs"]

    def cells(self, obj, path):
        return next(e["cells"] for e in PartDesign.configEntries(self.studio) if e["object"] == obj and e["path"] == path)

    def table(self, panel, inputId):
        pump()
        return panel.findChild(QtWidgets.QTableWidget, "configTable_" + inputId)

    @staticmethod
    def headers(table):
        return [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]

    @staticmethod
    def names(table):
        return [table.item(r, 0).text() for r in range(table.rowCount())]

    # ---------------------------------------------------------------------------- the panel
    def testPanelShowsTheTableAndHidesStaleEntries(self):
        """Onshape's table (CP2-4): a Name column, then "<feature> / <parameter>" and
        "<feature> / Unsuppressed" (a tick: unsuppressed); the default row has its bar (CP2-5), the
        active row is highlighted; a deleted owner's column goes, and comes back with the undo"""
        self.configureSizes()
        panel = ConfigurationsGui.showPanel(self.studio)
        tabs = panel.findChild(QtWidgets.QTabWidget, "configTabs")
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ["Size"])
        table = self.table(panel, self.size)
        self.assertEqual(self.headers(table), ["Name", "APad / Length", "E / Unsuppressed"])
        self.assertEqual(self.names(table), ["Small", "Large"])
        self.assertEqual(table.item(0, 0).data(QtCore.Qt.UserRole + 1), "default")
        self.assertIsNone(table.item(1, 0).data(QtCore.Qt.UserRole + 1))
        self.assertEqual(table.item(1, 1).text(), "20 mm")
        self.assertEqual(table.item(0, 2).checkState(), QtCore.Qt.Unchecked)
        self.assertEqual(table.item(1, 2).checkState(), QtCore.Qt.Checked)
        self.assertTrue(table.item(0, 0).font().bold())
        self.assertFalse(table.item(1, 0).font().bold())
        self.edit(lambda: (PartDesign.studioRemove(self.E), self.doc.removeObject("E")))
        self.assertTrue(waitFor(lambda: self.headers(self.table(panel, self.size)) == ["Name", "APad / Length"]))
        self.doc.undo()
        self.assertTrue(waitFor(lambda: len(self.headers(self.table(panel, self.size))) == 3))

    def testPanelEditsRowsCellsAndSuppression(self):
        """Add, rename, reorder, default; a cell and a suppression tick edit the model, each one undo step"""
        self.configureSizes()
        panel = ConfigurationsGui.showPanel(self.studio)
        medium = panel.addRow(self.size, "Medium")
        table = self.table(panel, self.size)
        self.assertEqual(self.names(table), ["Small", "Large", "Medium"])
        table.item(2, 0).setText("Mid")
        table = self.table(panel, self.size)
        self.assertEqual(self.names(table), ["Small", "Large", "Mid"])
        self.assertEqual(self.inputs()[0]["rows"][2]["id"], medium)
        table.item(2, 1).setText("15 mm")
        self.assertEqual(self.cells(self.APad, "Length")[medium], "15 mm")
        PartDesign.configSetActive(self.studio, {"Size": "Mid"})
        self.assertAlmostEqual(height(self.A), 15, delta=TOL)
        panel.moveRow(self.size, medium, -1)
        self.assertEqual(self.names(self.table(panel, self.size)), ["Small", "Mid", "Large"])
        panel.setDefaultRow(self.size, "Large")
        table = self.table(panel, self.size)
        self.assertEqual(self.inputs()[0]["default"], "Large")
        self.assertEqual(table.item(2, 0).data(QtCore.Qt.UserRole + 1), "default")
        # Small's E column: a tick unsuppresses E in Small
        table.item(0, 2).setCheckState(QtCore.Qt.Checked)
        self.assertEqual(self.cells(self.E, None)["Default"], "false")
        self.doc.undo()
        self.assertEqual(self.cells(self.E, None)["Default"], "true")
        self.assertTrue(waitFor(lambda: self.table(panel, self.size).item(0, 2).checkState() == QtCore.Qt.Unchecked))

    def testRefusalIsShownAndTheTableShowsTheModel(self):
        panel = ConfigurationsGui.showPanel(self.studio)
        self.assertIsNone(panel.renameRow(self.size, "Large", "Small"))
        self.assertTrue(panel.findChild(QtWidgets.QLabel, "configMessage").text())
        self.assertTrue(waitFor(lambda: self.names(self.table(panel, self.size)) == ["Small", "Large"]))

    def testCheckboxAndVariableTabs(self):
        """A Checkbox's tab: its default and its two rows; a Variable's: default and bounds; an input renamed"""
        panel = ConfigurationsGui.showPanel(self.studio)
        tall = panel.addCheckbox("Tall")
        cpad = self.doc.getObject("CPad")
        self.assertEqual(ConfigurationsGui.configureField(cpad, "Length", tall), tall)
        table = self.table(panel, tall)
        self.assertEqual(self.names(table), ["Checked", "Unchecked"])
        table.item(0, 1).setText("15 mm")
        self.assertAlmostEqual(height(self.C), 15, delta=TOL)
        panel.findChild(QtWidgets.QWidget, "configTab_" + tall).findChild(
            QtWidgets.QCheckBox, "configCheckboxDefault"
        ).setChecked(False)
        self.assertAlmostEqual(height(self.C), 10, delta=TOL)
        panel.addVariable("len", "Length", "80 mm", "10 mm", "200 mm")
        pump()
        tab = panel.findChild(QtWidgets.QWidget, "configTab_len")
        tab.findChild(QtWidgets.QLineEdit, "configVariable_default").setText("120 mm")
        tab.findChild(QtWidgets.QPushButton, "configVariableApply").click()
        self.assertAlmostEqual(self.inputs()[2]["default"], 120, delta=TOL)
        panel.renameInput(self.size, "Width")
        pump()
        tabs = panel.findChild(QtWidgets.QTabWidget, "configTabs")
        self.assertEqual(tabs.tabText(0), "Width")

    # ------------------------------------------------------------------------ field menus
    def testFieldMenuItemsAndTheirActions(self):
        """Onshape's field menu (CP2-1): "Configure with <input>" per List or Checkbox, "Set to #len"
        per Variable; a configured field offers only "Unconfigure from <input>", which keeps the
        active value; with no List or Checkbox, "Configure..." makes the List "Configuration"."""
        self.assertEqual(PartDesign.configMenuItems(self.APad, "Length"), [("Configure with Size", "configure", self.size)])
        self.edit(lambda: PartDesign.configAddVariable(self.studio, "len", "Length", "80 mm"))
        self.assertIn(("Set to #len", "variable", "len"), PartDesign.configMenuItems(self.APad, "Length"))
        self.assertEqual(
            PartDesign.configMenuItems(self.E), [("Configure suppression with Size", "configure", self.size)]
        )
        ConfigurationsGui.fieldAction(self.APad, "Length", "configure", self.size)
        self.assertTrue(PartDesign.configIsConfigured(self.APad, "Length"))
        panel = ConfigurationsGui.panel()
        self.assertTrue(panel is not None and panel.isVisible())
        self.assertEqual(panel.currentInput(), self.size)
        self.assertEqual(PartDesign.configMenuItems(self.APad, "Length"), [("Unconfigure from Size", "unconfigure", self.size)])
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "20 mm"))
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        ConfigurationsGui.fieldAction(self.APad, "Length", "unconfigure", self.size)
        self.assertFalse(PartDesign.configIsConfigured(self.APad, "Length"))
        self.assertAlmostEqual(height(self.A), 20, delta=TOL)
        bpad = self.doc.getObject("BPad")
        ConfigurationsGui.fieldAction(bpad, "Length", "variable", "len")
        self.assertAlmostEqual(height(self.B), 80, delta=TOL)
        self.edit(lambda: PartDesign.configRemoveInput(self.studio, self.size))
        self.assertIn(("Configure...", "new", ""), PartDesign.configMenuItems(self.APad, "Length"))
        made = ConfigurationsGui.fieldAction(self.APad, "Length", "new", "")
        new = next(i for i in self.inputs() if i["id"] == made)
        self.assertEqual((new["name"], [r["name"] for r in new["rows"]]), ("Configuration", ["Default"]))

    def testSketchDimensionIsConfiguredByName(self):
        """A sketch dimension is configured as Constraints.<name>; an unnamed one is named first"""
        import Part
        import Sketcher

        sk = self.A.newObject("Sketcher::SketchObject", "CfgSketch")
        sk.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(10, 0, 0)))
        sk.addConstraint(Sketcher.Constraint("Distance", 0, 10))
        self.doc.recompute()
        saved = ConfigurationsGui.askText
        ConfigurationsGui.askText = lambda *args, **kw: "w"
        try:
            ConfigurationsGui.fieldAction(sk, "Constraints[0]", "configure", self.size)
        finally:
            ConfigurationsGui.askText = saved
        self.assertEqual(sk.Constraints[0].Name, "w")
        self.assertTrue(PartDesign.configIsConfigured(sk, "Constraints.w"))
        self.assertEqual(PartDesign.configMenuItems(sk, ".Constraints.w"), [("Unconfigure from Size", "unconfigure", self.size)])

    def testConfiguredFieldInTheDialog(self):
        """Onshape's configured field (CP2-2): a dotted orange outline, and typing writes the active
        row's cell only; the field's menu offers the configuration items"""
        self.APad.ViewObject.doubleClicked()
        pump()
        field = Gui.getMainWindow().findChild(QtWidgets.QWidget, "lengthEdit")
        self.assertIsNotNone(field)
        line = field.findChild(QtWidgets.QLineEdit)
        self.assertIn("fieldConfig_configure", menuActions(line))
        guiDoc = Gui.getDocument(self.doc.Name)
        guiDoc.resetEdit()
        Gui.Control.closeDialog()
        pump()
        self.configureSizes()
        self.APad.ViewObject.doubleClicked()
        pump()
        field = Gui.getMainWindow().findChild(QtWidgets.QWidget, "lengthEdit")
        line = field.findChild(QtWidgets.QLineEdit)
        self.assertEqual(field.property("configured"), "Size")
        self.assertIn("dotted", field.styleSheet())
        self.assertFalse(field.property("readOnly"))
        self.assertIn("fieldConfig_unconfigure", menuActions(line))
        line.setFocus()
        line.selectAll()
        QTest.keyClicks(line, "12 mm")
        QTest.keyClick(line, QtCore.Qt.Key_Return)
        pump()
        cells = self.cells(self.APad, "Length")
        self.assertEqual(App.Units.Quantity(cells["Default"]).Value, 12)
        self.assertEqual(cells["Large"], "20 mm")

    # -------------------------------------------------------------------- the active bar
    def showTree(self, tree):
        param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        if param.GetBool("ShowModelTree", False) != tree:
            Gui.runCommand("PartDesign_ToggleModelTree")

    def featuresView(self):
        param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        self.savedTree = param.GetBool("ShowModelTree", False)
        self.showTree(False)
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        view = lambda: Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")
        self.assertTrue(waitFor(lambda: view() is not None and view().isVisible()))
        return view()

    def testActiveBarSwitchesTheConfiguration(self):
        """Onshape's bar above the Feature list (CP2-8): one control per input; a value out of a
        Variable's range is refused and the box shows the model's value again"""
        self.configureSizes()
        view = self.featuresView()
        bar = view.findChild(QtWidgets.QWidget, "configBar")
        self.assertTrue(waitFor(lambda: bar.isVisible()))
        combo = view.findChild(QtWidgets.QComboBox, "configInput_" + self.size)
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["Small", "Large"])
        combo.setCurrentIndex(1)
        combo.activated.emit(1)
        self.assertTrue(waitFor(lambda: abs(height(self.A) - 20) < TOL))
        self.assertEqual(PartDesign.configKey(self.studio), self.size + "=Large")
        self.edit(lambda: PartDesign.configAddCheckbox(self.studio, "Tall"))
        self.assertTrue(waitFor(lambda: view.findChild(QtWidgets.QCheckBox, "configInput_Tall") is not None))
        view.findChild(QtWidgets.QCheckBox, "configInput_Tall").click()
        self.assertTrue(waitFor(lambda: dict(self.cfg.Active).get("Tall") == "false"))
        self.edit(lambda: PartDesign.configAddVariable(self.studio, "len", "Length", "80 mm", "10 mm", "200 mm"))
        self.assertTrue(waitFor(lambda: view.findChild(QtWidgets.QLineEdit, "configInput_len") is not None))
        box = view.findChild(QtWidgets.QLineEdit, "configInput_len")
        box.setText("300 mm")
        box.editingFinished.emit()
        pump()
        self.assertNotAlmostEqual(float(dict(self.cfg.Active).get("len", "80")), 300)
        self.assertTrue(waitFor(lambda: abs(App.Units.Quantity(view.findChild(QtWidgets.QLineEdit, "configInput_len").text()).Value - 80) < TOL))
        box = view.findChild(QtWidgets.QLineEdit, "configInput_len")
        box.setText("120 mm")
        box.editingFinished.emit()
        self.assertTrue(waitFor(lambda: abs(float(dict(self.cfg.Active).get("len", "0")) - 120) < TOL))
        view.findChild(QtWidgets.QToolButton, "featuresConfigurations").click()
        pump()
        panel = ConfigurationsGui.panel()
        self.assertTrue(panel is not None and panel.isVisible())
        self.assertEqual(panel.studio, self.studio)


if __name__ == "__main__":
    unittest.main()
