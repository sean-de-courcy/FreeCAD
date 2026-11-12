# SPDX-License-Identifier: LGPL-2.1-or-later

"""Configurations in the assembly's GUI (FreeCAD-CH ops#671, slice C3 GUI;
notes/configurations-design.md 3.6): the pass that refills other configurations' cached shapes
runs from the event loop, never inside the GUI event that ended the recompute (ruling 4); the
Insert dialog offers a configured studio's inputs, the default row first, and sets the instance's
ConfigKey; the instance's context menu command changes them (F6).

Designed model: the studio of TestStudioList (parts A, B, C, 10 x 10 pads of height 10) with a
List "Size" (Small = the first row, Large) that configures A's pad length: Small 10, Large 20. The
expected results are the heights of A's instances."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
import PartDesign

from PySide import QtCore, QtWidgets

from AssemblyTests.TestOnshapeAssembliesGui import (
    AssembliesGuiBase,
    TestInsertStudioGui,
    pump,
    waitFor,
)

TOL = 1e-6


def linkHeight(link):
    box = Part.getShape(link).BoundBox
    return box.ZMax - box.ZMin


def isEntry(link):
    return getattr(link.LinkedObject, "TypeId", "") == "PartDesign::ConfigShape"


class ConfigInsertBase(AssembliesGuiBase):
    def model(self):
        """The configured studio and an empty assembly in one document; Small is the active
        configuration and the default row is Large (so the default row is not the first one)."""
        from PartDesignTests.TestStudioList import newStudio

        doc, studio = newStudio("ConfigInsertGui")
        self.docs.append(doc.Name)
        Gui.ActiveDocument = Gui.getDocument(doc.Name)
        self.A = doc.getObject("A")
        self.edit(doc, lambda: setattr(self, "size", PartDesign.configAddList(studio, "Size", ["Small", "Large"])))
        pad = doc.getObject("APad")
        self.edit(doc, lambda: PartDesign.configConfigure(pad, "Length", self.size))
        self.edit(doc, lambda: PartDesign.configSetCell(pad, "Length", "Large", "20 mm"))
        self.edit(doc, lambda: PartDesign.configSetDefaultRow(studio, self.size, "Large"))
        self.edit(doc, lambda: PartDesign.configSetActive(studio, {"Size": "Small"}))
        asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        asm.newObject("Assembly::JointGroup", "Joints")
        doc.recompute()
        pump(0.2)
        return doc, studio, asm

    @staticmethod
    def edit(doc, fn):
        doc.openTransaction("edit")
        try:
            fn()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
        doc.commitTransaction()

    def openInsert(self, doc, asm):
        return TestInsertStudioGui.openInsert(self, doc, asm)

    @staticmethod
    def findItem(panel, label):
        found = []

        def walk(item):
            if item.text(0) == label and item.data(0, QtCore.Qt.UserRole):
                found.append(item)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(panel.form.partList.topLevelItemCount()):
            walk(panel.form.partList.topLevelItem(i))
        return found[0] if found else None

    def enterAssembly(self, doc, asm):
        """The assembly's tab (or its edit mode), where its instances can be selected"""
        gdoc = Gui.getDocument(doc.Name)
        Gui.activateWorkbench("AssemblyWorkbench")
        if hasattr(Gui, "DocumentTabs") and Gui.DocumentTabs.isOn():
            done, refusal = Gui.DocumentTabs.switchTo(doc, asm.Name)
            self.assertTrue(done, refusal)
        else:
            gdoc.setEdit(asm.Name)
        self.assertTrue(waitFor(lambda: gdoc.getInEdit() is not None))
        pump(0.2)

    def links(self, asm):
        return [o for o in asm.Group if o.TypeId == "App::Link"]

    def settle(self, doc):
        doc.recompute()
        pump(0.3)


class TestConfigPassSchedulerGui(ConfigInsertBase):
    def testPassRunsFromTheEventLoop(self):
        """In the GUI the pass that refills another configuration's entry runs after the event
        that ended the edit, from the event loop (ruling 4). An instance shows the default row,
        Large (20 mm), through an entry while the studio shows Small; editing Large's cell to
        30 mm makes the entry stale: right after the edit the instance still shows 20 mm (or
        nothing), one pump later 30 mm."""
        doc, studio, asm = self.model()
        link = asm.newObject("App::Link", "Instance")
        link.LinkedObject = self.A
        self.settle(doc)
        self.assertTrue(waitFor(lambda: isEntry(link)), "the default row is not shown")
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)

        pad = doc.getObject("APad")
        self.edit(doc, lambda: PartDesign.configSetCell(pad, "Length", "Large", "30 mm"))
        self.assertGreater(
            abs(linkHeight(link) - 30), TOL, "the pass ran inside the event that ended the edit"
        )
        self.assertTrue(waitFor(lambda: abs(linkHeight(link) - 30) < TOL), "the pass never ran")


class TestConfigInsertDialogGui(ConfigInsertBase):
    def combo(self, panel):
        box = panel.configBox
        self.assertIsNotNone(box, "no Configuration box for a configured studio")
        combo = box.findChild(QtWidgets.QComboBox, "ConfigInput_" + self.size)
        self.assertIsNotNone(combo, "no combo box for the Size input")
        return combo

    def testInsertOffersTheInputsDefaultFirst(self):
        doc, studio, asm = self.model()
        panel = self.openInsert(doc, asm)
        combo = self.combo(panel)
        self.assertEqual(
            [combo.itemText(i) for i in range(combo.count())], ["Large", "Small"], "default first"
        )
        self.assertEqual(combo.currentText(), "Large")
        Gui.Control.closeDialog()
        pump(0.2)

    def testInsertSetsTheInstancesConfigKey(self):
        """An instance inserted with Small chosen shows Small while the studio shows Large, in the
        dialog and after it is accepted (the committed links carry the key as well)"""
        doc, studio, asm = self.model()
        panel = self.openInsert(doc, asm)
        combo = self.combo(panel)
        combo.setCurrentIndex(combo.findText("Small"))
        item = self.findItem(panel, "A")
        self.assertIsNotNone(item, "A is not in the list")
        panel.onItemClicked(item)
        pump(0.2)
        self.assertEqual(len(self.links(asm)), 1)
        self.assertTrue(self.links(asm)[0].ConfigKey, "the inserted instance has no ConfigKey")
        self.assertTrue(panel.accept())
        Gui.Control.closeDialog()
        pump(0.2)

        link = self.links(asm)[0]
        self.assertTrue(link.ConfigKey, "the committed instance has no ConfigKey")
        self.edit(doc, lambda: PartDesign.configSetActive(studio, {"Size": "Large"}))
        self.assertTrue(waitFor(lambda: isEntry(link)), "Small is not shown through an entry")
        self.assertAlmostEqual(linkHeight(link), 10, delta=TOL)

    def testInsertWithTheDefaultRow(self):
        """With the panel untouched the instance shows the default row, Large"""
        doc, studio, asm = self.model()
        panel = self.openInsert(doc, asm)
        panel.onItemClicked(self.findItem(panel, "A"))
        pump(0.2)
        link = self.links(asm)[0]
        self.assertTrue(panel.accept())
        Gui.Control.closeDialog()
        pump(0.2)
        link = self.links(asm)[0]
        self.assertTrue(waitFor(lambda: isEntry(link)), "the default row is not shown")
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)


class TestInstanceConfigurationGui(ConfigInsertBase):
    def setUp(self):
        super().setUp()
        self.dialogDriver = None

    def driveDialog(self, rowText):
        """Chooses rowText in the instance configuration dialog and accepts it, from the event
        loop while the dialog is open"""

        def drive():
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if widget.objectName() == "InstanceConfigurationDialog" and widget.isVisible():
                    combo = widget.findChild(QtWidgets.QComboBox, "ConfigInput_" + self.size)
                    combo.setCurrentIndex(combo.findText(rowText))
                    widget.accept()
                    return
            QtCore.QTimer.singleShot(50, drive)

        QtCore.QTimer.singleShot(100, drive)

    def testContextMenuCommandChangesTheConfiguration(self):
        import CommandInsertLink

        doc, studio, asm = self.model()
        link = asm.newObject("App::Link", "Instance")
        link.LinkedObject = self.A
        self.settle(doc)
        command = CommandInsertLink.CommandInstanceConfiguration()
        Gui.Selection.clearSelection()
        self.assertFalse(command.IsActive(), "active with nothing selected")
        self.enterAssembly(doc, asm)
        Gui.Selection.addSelection(doc.Name, asm.Name, link.Name + ".")
        pump(0.1)
        self.assertTrue(
            command.IsActive(),
            "not active on a configured part's instance: %s, %s"
            % (Gui.Selection.getSelection(), PartDesign.configInstancePart(link)),
        )
        self.assertIsNotNone(Gui.Command.get("Assembly_InstanceConfiguration"))

        # the instance shows the default row, Large; the dialog starts there and changes it to Small
        self.assertTrue(waitFor(lambda: isEntry(link)), "the default row is not shown")
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        self.driveDialog("Small")
        self.assertTrue(CommandInsertLink.changeInstanceConfiguration(link))
        self.assertTrue(waitFor(lambda: abs(linkHeight(link) - 10) < TOL), "Small is not shown")

        # one undo step puts the instance back
        doc.undo()
        self.settle(doc)
        self.assertTrue(waitFor(lambda: abs(linkHeight(link) - 20) < TOL), "undo did not restore")

    def testNotActiveOnAPlainLink(self):
        import CommandInsertLink

        doc, studio, asm = self.model()
        box = asm.newObject("Part::Box", "Plain")
        link = asm.newObject("App::Link", "PlainLink")
        link.LinkedObject = box
        doc.recompute()
        self.enterAssembly(doc, asm)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, asm.Name, link.Name + ".")
        pump(0.1)
        self.assertEqual(len(Gui.Selection.getSelection()), 1)
        self.assertFalse(CommandInsertLink.CommandInstanceConfiguration().IsActive())


if __name__ == "__main__":
    unittest.main()
