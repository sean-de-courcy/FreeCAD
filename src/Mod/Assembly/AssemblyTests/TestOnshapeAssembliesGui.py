# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 round 7, ops#651): Onshape's assemblies in the GUI.
#
# - A document holds any number of assemblies, each a tab ("Assembly 1", "Assembly 2"...), as
#   Onshape's documents do (gap A13). Two root assemblies used to crash FreeCAD after the document
#   was closed: each entry into edit (each switch to an assembly's tab) left a connection to the
#   view provider behind, called at the next workbench switch after the provider was gone.
# Designed geometry: two 10 mm cubes per assembly, 40 mm apart along X, one Fixed joint.

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets

import JointObject
import UtilsAssembly


def pump(seconds=0.2):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


def tabsOn():
    return hasattr(Gui, "DocumentTabs") and Gui.DocumentTabs.isOn()


class AssembliesGuiBase(unittest.TestCase):
    def setUp(self):
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        self.startWorkbench = Gui.activeWorkbench().name()
        self.docs = []

    def tearDown(self):
        if JointObject.activeTask is not None:
            JointObject.activeTask.reject()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        pump()
        for name in self.docs:
            if name in App.listDocuments():
                gdoc = Gui.getDocument(name)
                if gdoc and gdoc.getInEdit():
                    gdoc.resetEdit()
                App.closeDocument(name)
        pump()
        Gui.activateWorkbench(self.startWorkbench)
        pump()

    def newDocument(self, name):
        doc = App.newDocument(name)
        self.docs.append(doc.Name)
        Gui.ActiveDocument = Gui.getDocument(doc.Name)
        return doc

    def assembly(self, doc, name, label, x=0):
        """A root assembly as Assembly_CreateAssembly makes it, with cubes A and B 40 mm apart
        and a Fixed joint moving A onto B."""
        asm = doc.addObject("Assembly::AssemblyObject", name)
        asm.Label = label
        asm.Type = "Assembly"
        joints = asm.newObject("Assembly::JointGroup", "Joints")
        cubes = []
        for i, at in enumerate((0, 40)):
            box = asm.newObject("Part::Box", f"{name}Cube{i}")
            box.Length = box.Width = box.Height = 10
            box.Placement = App.Placement(App.Vector(x + at, 0, 0), App.Rotation())
            cubes.append(box)
        doc.recompute()
        joint = joints.newObject("App::FeaturePython", f"{name}Fixed")
        JointObject.Joint(joint, 0)
        joint.Proxy.setJointConnectors(
            joint, [[cubes[0], ["Face6", "Vertex7"]], [cubes[1], ["Face6", "Vertex7"]]]
        )
        return asm, cubes, joint

    def cycleWorkbenches(self):
        """The workbench switches that called the stale connections (TechDraw's "+" > Create
        Drawing crashed after a two-assembly document was closed)."""
        for name in ("PartDesignWorkbench", "AssemblyWorkbench", "PartWorkbench"):
            if name in Gui.listWorkbenches():
                Gui.activateWorkbench(name)
                pump(0.1)


class TestSeveralAssembliesGui(AssembliesGuiBase):
    def testEditEachAssemblyAgainThenClose(self):
        """Two root assemblies, each put in edit and out of it twice (as switching their tabs
        does), then the document closed: the next workbench switches and a new document run
        (before ops#651: "Illegal storage access" at the first switch)."""
        doc = self.newDocument("SeveralAssembliesGui")
        first, cubes1, _ = self.assembly(doc, "Assembly", "Assembly 1")
        second, cubes2, _ = self.assembly(doc, "Assembly001", "Assembly 2", x=100)
        gdoc = Gui.getDocument(doc.Name)
        Gui.activateWorkbench("AssemblyWorkbench")
        for _ in range(2):
            for asm in (first, second, first, second):
                gdoc.setEdit(asm.Name)
                self.assertTrue(waitFor(lambda: gdoc.getInEdit() is not None))
                self.cycleWorkbenches()
                Gui.activateWorkbench("AssemblyWorkbench")
                pump(0.1)
                gdoc.resetEdit()
                pump(0.1)
        # Each assembly solved on its own: A onto B in each
        self.assertEqual(first.solve(), 0)
        self.assertEqual(second.solve(), 0)
        self.assertTrue(cubes1[0].Placement.isSame(cubes1[1].Placement, 1e-6))
        self.assertTrue(cubes2[0].Placement.isSame(cubes2[1].Placement, 1e-6))
        self.assertAlmostEqual(cubes2[1].Placement.Base.x, 140, 6)

        App.closeDocument(doc.Name)
        pump(0.3)
        self.cycleWorkbenches()
        other = self.newDocument("SeveralAssembliesAfter")
        other.addObject("Part::Box", "Box")
        other.recompute()
        self.cycleWorkbenches()
        self.assertAlmostEqual(other.getObject("Box").Shape.Volume, 1000, 6)

    def testTabsMakeAssembly1And2(self):
        """Under the Onshape keymap "+" > Create Assembly makes "Assembly 1", then "Assembly 2",
        both at the root, each its tab, in edit while active; switching between them and closing
        the document leaves FreeCAD running."""
        if not tabsOn():
            self.skipTest("the typed tabs are on under the Onshape keymap only")
        GuiTabs = Gui.DocumentTabs
        doc = self.newDocument("SeveralAssembliesTabs")
        pump(0.2)
        first = GuiTabs.create(doc, "Assembly")
        pump(0.3)
        second = GuiTabs.create(doc, "Assembly")
        pump(0.3)
        self.assertTrue(first and second, (first, second))
        self.assertNotEqual(first, second)
        for name, label in ((first, "Assembly 1"), (second, "Assembly 2")):
            asm = doc.getObject(name)
            self.assertEqual(asm.TypeId, "Assembly::AssemblyObject")
            self.assertEqual(asm.Label, label)
            self.assertIsNone(asm.getParentGeoFeatureGroup(), "not at the root")
        self.assertEqual(GuiTabs.activeTab(doc), second)
        gdoc = Gui.getDocument(doc.Name)
        for name in (first, second, first, second):
            done, refusal = GuiTabs.switchTo(doc, name)
            self.assertTrue(done, refusal)
            pump(0.2)
            self.assertIsNotNone(gdoc.getInEdit())
            self.assertEqual(UtilsAssembly.activeAssembly().Name, name)
        gdoc.resetEdit()
        pump(0.1)
        App.closeDocument(doc.Name)
        pump(0.3)
        self.cycleWorkbenches()
        if "TechDrawWorkbench" in Gui.listWorkbenches():
            Gui.activateWorkbench("TechDrawWorkbench")
            pump(0.2)


if __name__ == "__main__":
    unittest.main()
