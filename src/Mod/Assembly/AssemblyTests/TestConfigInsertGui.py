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

from PySide import QtCore, QtGui, QtWidgets

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
        self.configureSize(doc, studio)
        return doc, studio, self.newAssembly(doc)

    def configureSize(self, doc, studio):
        """The List Size (Small, Large) on studio (an App::Part, or the document for its implicit
        studio) configuring A's pad length: Small 10, Large 20; Large the default row, Small
        active."""
        self.A = doc.getObject("A")
        self.edit(doc, lambda: setattr(self, "size", PartDesign.configAddList(studio, "Size", ["Small", "Large"])))
        pad = doc.getObject("APad")
        self.edit(doc, lambda: PartDesign.configConfigure(pad, "Length", self.size))
        self.edit(doc, lambda: PartDesign.configSetCell(pad, "Length", "Large", "20 mm"))
        self.edit(doc, lambda: PartDesign.configSetDefaultRow(studio, self.size, "Large"))
        self.edit(doc, lambda: PartDesign.configSetActive(studio, {"Size": "Small"}))

    @staticmethod
    def newAssembly(doc):
        asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        asm.newObject("Assembly::JointGroup", "Joints")
        doc.recompute()
        pump(0.2)
        return asm

    def savedModels(self, implicit):
        """The configured studio in its own saved document and an assembly in another (Insert
        asks to save before linking across documents). implicit: the studio is the document's top
        level (Body A only), else the App::Part S of A, B, C. Returns (studio doc, assembly doc,
        assembly)."""
        import os
        import shutil
        import tempfile

        from PartDesignTests.TestStudio import pad, sketch, xyPlane
        from PartDesignTests.TestStudioList import newStudio

        folder = tempfile.mkdtemp(prefix="ConfigInsertGui")
        self.addCleanup(shutil.rmtree, folder, True)  # after tearDown has closed the documents
        asmDoc = self.newDocument("ConfigInsertAsm")
        if implicit:
            doc = App.newDocument("ConfigInsertStudio")
            body = doc.addObject("PartDesign::Body", "A")
            pad(body, "APad", sketch(body, "ASk", xyPlane(body), (0, 0, 10, 10)), 10)
            doc.recompute()
            studio = doc
        else:
            doc, studio = newStudio("ConfigInsertStudio")
        self.docs.append(doc.Name)  # closed after the assembly's document
        self.configureSize(doc, studio)
        doc.saveAs(os.path.join(folder, "Studio.FCStd"))
        asm = self.newAssembly(asmDoc)
        asmDoc.saveAs(os.path.join(folder, "Assembly.FCStd"))
        App.setActiveDocument(asmDoc.Name)
        Gui.ActiveDocument = Gui.getDocument(asmDoc.Name)
        return doc, asmDoc, asm

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

    @staticmethod
    def menuTexts(openMenu):
        """The texts of the context menu openMenu() opens (its exec blocks: the texts are read and
        the menu closed from the event loop)."""
        texts = []
        tries = [0]

        def answer():
            menu = QtWidgets.QApplication.activePopupWidget()
            if menu is None:
                tries[0] += 1
                if tries[0] < 60:
                    QtCore.QTimer.singleShot(50, answer)
                return
            texts.extend(a.text().replace("&", "") for a in menu.actions())
            menu.close()

        QtCore.QTimer.singleShot(50, answer)
        openMenu()
        pump(0.3)
        return texts


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


CHANGE = "Change configuration..."  # Onshape's instance menu entry (CF8)


class TestInstanceMenuGui(ConfigInsertBase):
    """The instance's context menus offer Change configuration... on an instance of a configured
    studio's part, and only there: the Model tree's (the Link view provider's menu) and, under the
    Onshape keymap, the Assembly tab's list."""

    def setUp(self):
        super().setUp()
        self.param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        self.savedTree = self.param.GetBool("ShowModelTree", False)

    def tearDown(self):
        super().tearDown()
        self.param.SetBool("ShowModelTree", self.savedTree)
        pump(0.2)

    def instances(self):
        """The model with a configured instance and a plain one (a link to a box)"""
        doc, studio, asm = self.model()
        link = asm.newObject("App::Link", "Instance")
        link.LinkedObject = self.A
        box = asm.newObject("Part::Box", "Plain")
        plain = asm.newObject("App::Link", "PlainLink")
        plain.LinkedObject = box
        self.settle(doc)
        return doc, asm, link, plain

    @staticmethod
    def rowOf(tree, label):
        found = tree.findItems(label, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive, 0)
        if not found:
            return None, []
        item, parents = found[0], []  # parents held: PySide drops a child's wrapper with its parent's
        parent = item.parent()
        while parent is not None:
            parents.append(parent)
            parent.setExpanded(True)
            parent = parent.parent()
        pump(0.1)
        tree.scrollToItem(item)
        pump(0.1)
        return item, parents

    def modelTree(self, label):
        for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
            if tree.isVisible() and tree.objectName() != "assemblyList":
                if tree.findItems(label, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive, 0):
                    return tree
        return None

    def treeMenu(self, doc, asm, obj):
        tree = self.modelTree(obj.Label)
        if tree is None:
            self.skipTest("no visible Model tree lists the instance here")
        item, parents = self.rowOf(tree, obj.Label)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, asm.Name, obj.Name + ".")
        pump(0.1)
        pos = tree.visualItemRect(item).center()
        viewport = tree.viewport()

        def openMenu():
            event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, viewport.mapToGlobal(pos))
            QtWidgets.QApplication.sendEvent(viewport, event)

        return self.menuTexts(openMenu)

    def testModelTreeMenu(self):
        doc, asm, link, plain = self.instances()
        self.param.SetBool("ShowModelTree", True)
        self.enterAssembly(doc, asm)
        texts = self.treeMenu(doc, asm, link)
        self.assertTrue(texts, "the right-click opened no menu")
        self.assertIn(CHANGE, texts)
        self.assertNotIn(CHANGE, self.treeMenu(doc, asm, plain))

    def testAssemblyListMenu(self):
        from AssemblyTests.TestOnshapeAssembliesGui import onshapeKeymap, tabsOn

        if not tabsOn() or not onshapeKeymap():
            self.skipTest("the Assembly tab's list is shown under the Onshape keymap only")
        doc, asm, link, plain = self.instances()
        self.param.SetBool("ShowModelTree", False)
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        self.enterAssembly(doc, asm)
        view = Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")
        tree = view.findChild(QtWidgets.QTreeWidget, "assemblyList") if view else None
        self.assertTrue(waitFor(lambda: tree is not None and tree.isVisible()), "no Assembly list")

        def listMenu(obj):
            self.assertTrue(waitFor(lambda: self.rowOf(tree, obj.Label)[0] is not None), "no row")
            item, parents = self.rowOf(tree, obj.Label)
            pos = tree.visualItemRect(item).center()
            return self.menuTexts(lambda: tree.customContextMenuRequested.emit(pos))

        texts = listMenu(link)
        self.assertTrue(texts, "the right-click opened no menu")
        self.assertIn(CHANGE, texts)
        self.assertNotIn(CHANGE, listMenu(plain))


class TestConfiguredInsertSourcesGui(ConfigInsertBase):
    """Onshape's Insert offers a configured studio's inputs wherever the studio is (CF8): a studio
    of another document, its implicit one or an App::Part, gets its own section; a configured
    App::Part studio inserted whole makes one instance per part (Onshape's whole-studio insert,
    GB10), each showing the chosen configuration."""

    def insertSmall(self, asmDoc, asm, rowText):
        """Chooses Small in the Configuration box (its only section), clicks the row rowText and
        accepts; returns the assembly's links"""
        panel = self.openInsert(asmDoc, asm)
        box = panel.configBox
        self.assertIsNotNone(box, "no Configuration box")
        combo = box.findChild(QtWidgets.QComboBox, "ConfigInput_" + self.size)
        self.assertIsNotNone(combo, "no Size input")
        self.assertEqual(combo.currentText(), "Large", "the default row first")
        combo.setCurrentIndex(combo.findText("Small"))
        item = self.findItem(panel, rowText)
        self.assertIsNotNone(item, rowText + " is not in the list")
        panel.onItemClicked(item)
        pump(0.2)
        self.assertTrue(panel.accept())
        Gui.Control.closeDialog()
        pump(0.2)
        return self.links(asm)

    def assertShowsSmallAfterTheSwitch(self, studioDoc, studio, link):
        """Small (10) while the studio shows Small, and still after it shows Large (an entry)"""
        self.settle(link.Document)
        self.assertTrue(waitFor(lambda: abs(linkHeight(link) - 10) < TOL), "Small is not shown")
        self.edit(studioDoc, lambda: PartDesign.configSetActive(studio, {"Size": "Large"}))
        self.settle(link.Document)
        self.assertTrue(waitFor(lambda: isEntry(link)), "Small is not shown through an entry")
        self.assertTrue(waitFor(lambda: abs(linkHeight(link) - 10) < TOL), "the instance left Small")

    def testOtherDocumentsImplicitStudio(self):
        doc, asmDoc, asm = self.savedModels(implicit=True)
        links = self.insertSmall(asmDoc, asm, "A")
        self.assertEqual([l.LinkedObject for l in links], [self.A])
        self.assertShowsSmallAfterTheSwitch(doc, doc, links[0])

    def testOtherDocumentsPartStudio(self):
        doc, asmDoc, asm = self.savedModels(implicit=False)
        links = self.insertSmall(asmDoc, asm, "A")
        self.assertEqual([l.LinkedObject for l in links], [self.A])
        self.assertShowsSmallAfterTheSwitch(doc, doc.getObject("S"), links[0])

    def testWholeStudioMakesAKeyedInstancePerPart(self):
        from AssemblyTests.TestOnshapeAssembliesGui import tabsOn

        if not tabsOn():
            self.skipTest("a studio is inserted whole under the typed tabs only")
        doc, studio, asm = self.model()
        links = self.insertSmall(doc, asm, studio.Label)
        self.assertEqual([l.LinkedObject for l in links], [doc.getObject(n) for n in ("A", "B", "C")])
        self.assertEqual(len({str(l.Placement) for l in links}), 1, "the parts moved apart")
        xmin = [Part.getShape(l).BoundBox.XMin for l in links]
        self.assertAlmostEqual(xmin[1] - xmin[0], 20, delta=TOL)
        self.assertAlmostEqual(xmin[2] - xmin[0], 40, delta=TOL)
        self.assertShowsSmallAfterTheSwitch(doc, studio, links[0])
        self.assertAlmostEqual(linkHeight(links[1]), 10, delta=TOL)

    def testRightClickTakesTheWholeInsertBack(self):
        """In the panel a right-click on the studio's row removes its last insert, all its parts"""
        from AssemblyTests.TestOnshapeAssembliesGui import tabsOn

        if not tabsOn():
            self.skipTest("a studio is inserted whole under the typed tabs only")
        doc, studio, asm = self.model()
        panel = self.openInsert(doc, asm)
        item = self.findItem(panel, studio.Label)
        self.assertIsNotNone(item, "the studio is not in the list")
        panel.onItemClicked(item)
        pump(0.2)
        self.assertEqual(len(self.links(asm)), 3)
        tree = panel.form.partList
        pos = tree.visualItemRect(item).center()
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, tree.mapToGlobal(pos))
        QtWidgets.QApplication.sendEvent(tree, event)
        pump(0.2)
        self.assertEqual(self.links(asm), [], "parts of the insert are left")
        panel.reject()
        Gui.Control.closeDialog()
        pump(0.2)


if __name__ == "__main__":
    unittest.main()
