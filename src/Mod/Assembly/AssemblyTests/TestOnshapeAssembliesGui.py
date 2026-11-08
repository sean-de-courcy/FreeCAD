# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 round 7, ops#651): Onshape's assemblies in the GUI.
#
# - A document holds any number of assemblies, each a tab ("Assembly 1", "Assembly 2"...), as
#   Onshape's documents do (gap A13). Two root assemblies used to crash FreeCAD after the document
#   was closed: each entry into edit (each switch to an assembly's tab) left a connection to the
#   view provider behind, called at the next workbench switch after the provider was gone.
# - A joint whose face is gone is red in the tree and named in the solver panel (gaps A10, A11).
# - Insert lists this document's Part Studios first, each insertable whole (gap A16).
# Designed geometry: 10 mm cubes, a notched box, a cylinder; see each class.

import math
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets

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


RED = (0xD0, 0x30, 0x30)  # the Features list's error colour


def onshapeKeymap():
    general = App.ParamGet("User parameter:BaseApp/Preferences/General")
    return general.GetString("Keymap", "Onshape") != "FreeCAD"


def treeItems(text):
    """The model tree's items reading text, in every tree of the main window."""
    found = []
    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        found += tree.findItems(text, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive, 0)
    return found


def solverMessage():
    """The assembly's "Solver messages" panel: (status, link text) of the panel showing one."""
    found = []
    for panel in Gui.getMainWindow().findChildren(QtWidgets.QWidget, "TaskSolverMessages"):
        try:  # a panel of a closed dialog may be on its way out (deleteLater)
            status = panel.findChild(QtWidgets.QLabel, "labelStatus")
            link = panel.findChild(QtWidgets.QLabel, "labelStatusLink")
            if status is not None and link is not None and status.text():
                found.append((status.text(), link.text()))
        except RuntimeError:
            continue
    return found


class TestJointErrorsGui(AssembliesGuiBase):
    """A joint whose face is gone (gap A11) is red in the tree and named in the solver panel,
    as Onshape's red mate; designed model: a 10 mm box notched by a 4 mm cube, the notch's face
    at x = 4 picked, then the notch deleted."""

    def messagesInADialog(self):
        import CommandCreateJoint

        CommandCreateJoint.activateJoint(0)
        self.assertTrue(waitFor(lambda: JointObject.activeTask is not None), "no joint dialog")
        pump(0.3)
        messages = solverMessage()
        JointObject.activeTask.reject()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        pump(0.2)
        return messages

    def testMissingReferenceIsRedAndListed(self):
        doc = self.newDocument("JointErrorsGui")
        asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        joints = asm.newObject("Assembly::JointGroup", "Joints")
        body = asm.newObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 10
        notch = body.newObject("PartDesign::SubtractiveBox", "Notch")
        notch.Length = notch.Width = notch.Height = 4
        other = asm.newObject("Part::Box", "Other")
        other.Length = other.Width = other.Height = 10
        other.Placement = App.Placement(App.Vector(40, 0, 0), App.Rotation())
        doc.recompute()
        face = [
            f"Face{i}"
            for i, f in enumerate(body.Shape.Faces, 1)
            if f.Area < 20 and abs(f.CenterOfMass.x - 4) < 1e-6
        ][0]
        joint = joints.newObject("App::FeaturePython", "Fixed")
        JointObject.Joint(joint, 0)
        joint.Proxy.setJointConnectors(joint, [[other, ["Face6", "Vertex7"]], [body, [face, face]]])
        doc.recompute()
        gdoc = Gui.getDocument(doc.Name)
        Gui.activateWorkbench("AssemblyWorkbench")
        gdoc.setEdit(asm.Name)
        self.assertTrue(waitFor(lambda: gdoc.getInEdit() is not None))
        pump(0.3)
        self.assertTrue(joint.isValid())

        doc.openTransaction("Delete the notch")
        body.Tip = box
        doc.removeObject(notch.Name)
        doc.commitTransaction()
        doc.recompute()
        asm.solve()
        pump(0.3)
        self.assertFalse(joint.isValid())
        # The "Solver messages" panel joins a task dialog: a joint's, opened now
        messages = self.messagesInADialog()
        self.assertTrue(
            any(text.startswith("Joints in error") and joint.Label in link for text, link in messages),
            messages,
        )
        items = treeItems(joint.Label)
        self.assertTrue(items, "the joint's tree row")
        if onshapeKeymap():
            color = items[0].foreground(0).color()
            self.assertEqual((color.red(), color.green(), color.blue()), RED)
        # Undo brings the notch back: the joint is valid again, its row no longer red
        doc.undo()
        doc.recompute()
        asm.solve()
        pump(0.3)
        self.assertTrue(joint.isValid(), joint.getStatusString())
        messages = self.messagesInADialog()
        self.assertTrue(messages, "no solver panel in the joint dialog")
        self.assertFalse(any(text.startswith("Joints in error") for text, _l in messages), messages)
        color = treeItems(joint.Label)[0].foreground(0).color()
        self.assertNotEqual((color.red(), color.green(), color.blue()), RED)


class TestInsertStudioGui(AssembliesGuiBase):
    """Insert lists this document's Part Studios first, by tab name, each insertable whole
    (Onshape's "Insert entire Part Studio", gap A16). Designed model: Part Studio 1 (the top
    level) two 10 mm boxes, the second Body at x = 20; Part Studio 2 (an App::Part) a cylinder
    r 5, h 20; an assembly."""

    def model(self):
        doc = self.newDocument("InsertStudioGui")
        for name, x in (("Body", 0), ("Body001", 20)):
            body = doc.addObject("PartDesign::Body", name)
            box = body.newObject("PartDesign::AdditiveBox", name + "Box")
            box.Length = box.Width = box.Height = 10
            body.Placement.Base = App.Vector(x, 0, 0)
        studio = doc.addObject("App::Part", "Part")
        studio.Label = "Part Studio 2"
        body = doc.addObject("PartDesign::Body", "Body002")
        studio.addObject(body)
        self.cylinder = body.newObject("PartDesign::AdditiveCylinder", "Cylinder")
        self.cylinder.Radius = 5
        self.cylinder.Height = 20
        asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        asm.newObject("Assembly::JointGroup", "Joints")
        doc.recompute()
        pump(0.2)
        return doc, studio, asm

    def openInsert(self, doc, asm):
        import CommandInsertLink

        gdoc = Gui.getDocument(doc.Name)
        Gui.activateWorkbench("AssemblyWorkbench")
        if tabsOn():
            done, refusal = Gui.DocumentTabs.switchTo(doc, asm.Name)
            self.assertTrue(done, refusal)
        else:
            gdoc.setEdit(asm.Name)
        self.assertTrue(waitFor(lambda: gdoc.getInEdit() is not None))
        pump(0.2)
        panel = CommandInsertLink.TaskAssemblyInsertLink(asm, Gui.activeView())
        Gui.Control.showDialog(panel)
        pump(0.2)
        return panel

    @staticmethod
    def children(item):
        return [item.child(i) for i in range(item.childCount())]

    def testStudiosFirstAndWhole(self):
        if not tabsOn():
            self.skipTest("the typed tabs are on under the Onshape keymap only")
        doc, studio, asm = self.model()
        panel = self.openInsert(doc, asm)
        top = panel.form.partList.topLevelItem(0)
        self.assertEqual(top.text(0), doc.Label, "this document first")
        rows = self.children(top)
        self.assertEqual([r.text(0) for r in rows[:2]], ["Part Studio 1", "Part Studio 2"])
        self.assertEqual([c.text(0) for c in self.children(rows[0])], ["Body", "Body001"])
        self.assertEqual([c.text(0) for c in self.children(rows[1])], ["Body002"])
        self.assertNotIn("Assembly", [r.text(0) for r in rows], "the active assembly is listed")

        # Part Studio 2 whole: one link to the App::Part, following the studio
        panel.onItemClicked(rows[1])
        pump(0.2)
        links = [o for o in asm.Group if o.TypeId == "App::Link"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].LinkedObject, studio)
        # Part Studio 1 whole: a link per part, their poses kept, one rigid group
        panel.onItemClicked(rows[0])
        pump(0.2)
        links = [o for o in asm.Group if o.TypeId == "App::Link"]
        self.assertEqual(len(links), 3)
        first, second = links[1], links[2]
        self.assertEqual(
            (first.LinkedObject.Name, second.LinkedObject.Name), ("Body", "Body001")
        )
        offset = second.Shape.BoundBox.XMin - first.Shape.BoundBox.XMin
        self.assertAlmostEqual(offset, 20, 6)
        groups = [o for o in asm.InListRecursive + asm.OutListRecursive if hasattr(o, "ObjectsToRigidGroup")]
        self.assertEqual(len(groups), 1, groups)
        self.assertEqual(groups[0].Label, "Part Studio 1")
        self.assertEqual({o.Name for o in groups[0].ObjectsToRigidGroup}, {first.Name, second.Name})
        self.assertTrue(panel.accept())
        Gui.Control.closeDialog()
        pump(0.2)

        self.cylinder.Radius = 6
        doc.recompute()
        self.assertAlmostEqual(links[0].Shape.Volume, math.pi * 36 * 20, 3)
        self.assertAlmostEqual(first.Shape.Volume + second.Shape.Volume, 2000, 6)


if __name__ == "__main__":
    unittest.main()
