# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#790): the joint dialog's widgets have wrappers of their own, and a closed
# dialog's go with it.
#
# In full TestAssemblyWorkbenchGui runs, opening the joint dialog raised "Signal source has been
# deleted" at a spinbox connect(): the UI loader wrapped a new child through a valid-looking
# wrapper left mapped at that address by an object deleted earlier, with that object's cached
# signal instances. The loader now drops a wrapper found at a widget it has just made
# (PythonWrapper::dropStaleWrapper). Address reuse can't be forced in a test (that check is the
# whole suite: 7 errors in 3 runs before, 0 in 3 after), so these tests pin the dialog's own side:
# once it is gone (Cancel, the document closed, New Part's OK) every wrapper it held is invalid
# and out of the map, while the console's `panel` still holds the dialog, and the next dialog
# connects its own widgets.
#
# Designed geometry: two 10 mm boxes, A at the origin and B at x = 20, in an assembly.

import gc
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

import shiboken6
from PySide import QtWidgets

import CommandCreateJoint
import JointObject


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


def valid(wrapper):
    try:
        return shiboken6.isValid(wrapper)
    except RuntimeError:
        return False


def liveButtonBoxes():
    """The main window's button boxes, each through a live wrapper (TestExpressionFieldsGui)."""
    boxes = Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox)
    dead = [box for box in boxes if not shiboken6.isValid(box)]
    if dead:
        for box in dead:
            shiboken6.invalidate(box)
        boxes = Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox)
    return [box for box in boxes if shiboken6.isValid(box)]


def taskButton(which):
    """The task panel's OK or Cancel button."""
    for box in liveButtonBoxes():
        try:
            button = box.button(which)
            if button is None or not button.isVisible():
                continue
            parent = box.parentWidget()
            while parent is not None:
                if parent.metaObject().className() == "Gui::TaskView::TaskView":
                    return button
                parent = parent.parentWidget()
        except RuntimeError:
            continue
    return None


class TestJointDialogWrappersGui(unittest.TestCase):
    def setUp(self):
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        self.doc = App.newDocument("JointDialogWrappersGui")
        self.docName = self.doc.Name
        Gui.activateWorkbench("AssemblyWorkbench")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.assembly.newObject("Assembly::JointGroup", "Joints")
        for name, x in (("A", 0.0), ("B", 20.0)):
            box = self.assembly.newObject("Part::Box", name)
            box.Length = box.Width = box.Height = 10
            box.Placement.Base.x = x
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.setEdit(self.assembly.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))

    def tearDown(self):
        if JointObject.activeTask is not None:
            JointObject.activeTask.reject()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        pump()
        if self.docName in App.listDocuments():
            if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
                Gui.ActiveDocument.resetEdit()
            App.closeDocument(self.docName)
        Gui.doCommand("panel = None")  # activateJoint's console reference to the last dialog
        pump()
        gc.collect()

    def openFastened(self):
        CommandCreateJoint.activateJoint(0)
        self.assertTrue(waitFor(lambda: JointObject.activeTask is not None), "no joint dialog")
        return JointObject.activeTask

    def heldWrappers(self, panel):
        """Wrappers the dialog object holds: the loaded form, named children the loader set as its
        attributes (a spinbox, the feature list), the action made in Python on the form."""
        held = {
            "jForm": panel.jForm,
            "angleSpinbox": panel.jForm.angleSpinbox,
            "offsetSpinbox": panel.jForm.offsetSpinbox,
            "featureList": panel.jForm.featureList,
            "deleteAction": panel.deleteAction,
        }
        for name, wrapper in held.items():
            self.assertTrue(valid(wrapper), name + " invalid while the dialog is open")
        return held

    def assertReleased(self, held, when):
        live = [name for name, wrapper in held.items() if valid(wrapper)]
        self.assertEqual(live, [], when + ": wrappers still live")

    def test_cancel_releases_the_widget_wrappers(self):
        panel = self.openFastened()
        held = self.heldWrappers(panel)
        panel.reject()
        pump()
        # the console still holds the dialog, as it does in a user's session
        self.assertIs(Gui.doCommandEval("panel"), panel)
        self.assertReleased(held, "after Cancel")

    def test_the_next_dialog_connects_its_own_widgets(self):
        first = self.openFastened()
        held = self.heldWrappers(first)
        first.reject()
        pump()
        second = self.openFastened()  # the console's `panel` held `first` while this was made
        self.assertIsNot(second, first)
        self.assertReleased(held, "after the next dialog opened")
        spinbox = second.jForm.angleSpinbox
        self.assertTrue(valid(spinbox))
        self.assertIsNot(spinbox, held["angleSpinbox"])
        # its own connect() went through: a value typed in the spinbox reaches the joint
        spinbox.setProperty("rawValue", 30.0)
        pump(0.1)
        self.assertAlmostEqual(second.joint.Angle.getValueAs("deg").Value, 30.0, places=6)

    def test_closing_the_document_releases_them(self):
        panel = self.openFastened()
        held = self.heldWrappers(panel)
        Gui.ActiveDocument.resetEdit()
        App.closeDocument(self.doc.Name)
        pump()
        self.assertIsNone(JointObject.activeTask)
        self.assertReleased(held, "after the document closed")

    def test_new_part_reads_its_fields_after_deactivate(self):
        # New Part's OK reads the name and the new-file box after deactivate(), while the task view
        # still holds the panel (it deletes it after accept returns): the wrappers go with the
        # widgets, not at deactivate()
        import CommandInsertNewPart
        import Preferences

        prefs = Preferences.preferences()
        newFile = prefs.GetBool("PartInNewFile", True)
        self.addCleanup(prefs.SetBool, "PartInNewFile", newFile)
        panel = CommandInsertNewPart.TaskAssemblyNewPart()
        Gui.Control.showDialog(panel)
        self.assertTrue(waitFor(lambda: JointObject.activeTask is panel), "no New Part dialog")
        held = self.heldWrappers(panel)
        held["nameEdit"] = panel.nameEdit
        panel.nameEdit.setText("Bracket")
        panel.createInNewFileCheck.setChecked(False)
        self.assertTrue(waitFor(lambda: taskButton(QtWidgets.QDialogButtonBox.Ok) is not None))
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        pump()
        self.assertFalse(Gui.Control.activeDialog(), "the dialog closed")
        parts = [o for o in self.doc.Objects if o.TypeId == "App::Part" and o.Label == "Bracket"]
        self.assertEqual(len(parts), 1, "the part named in the dialog")
        self.assertIs(panel.link.LinkedObject, parts[0])
        self.assertReleased(held, "after OK")


if __name__ == "__main__":
    unittest.main()
