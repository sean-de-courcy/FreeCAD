# SPDX-License-Identifier: LGPL-2.1-or-later

"""New Sketch's attachment dialog outliving its sketch, Body or document (ops#390, upstream PR 33046).

The attachment dialog New Sketch opens is not an edit-mode dialog, so deleting what it works on
doesn't close it:
- an undo of New Sketch while the dialog is open, then OK, crashed on the undone sketch;
- the Body removed while the dialog is open, then Cancel, threw "Can't find Origin" through the
  event loop and aborted;
- the document closed while the dialog is open left the dialog behind, and its Cancel crashed.

Designed geometry: an empty Body; New Sketch with nothing selected opens the attachment dialog."""

import unittest

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtGui


def flush_gui(ms=100):
    """Runs the event loop for a while, so queued calls and timers run."""
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


def attacher_panels():
    """The attachment panels still alive, after the deferred deletions have run: a dialog left
    behind keeps its panel."""
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    return [w for w in QtGui.QApplication.allWidgets() if w.objectName() == "PartGui::TaskAttacher"]


class TestNewSketchDialogGui(unittest.TestCase):
    def setUp(self):
        self.param = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        self.savedUseAttachment = self.param.GetBool("NewSketchUseAttachmentDialog", False)
        self.param.SetBool("NewSketchUseAttachmentDialog", True)
        self.doc = FreeCAD.newDocument("TestNewSketchDialogGui")
        self.docName = self.doc.Name
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.doc.recompute()
        FreeCAD.setActiveDocument(self.docName)
        FreeCADGui.activateView("Gui::View3DInventor", True)
        FreeCADGui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        FreeCADGui.Selection.clearSelection()
        flush_gui()

    def tearDown(self):
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
            flush_gui()
        if self.docName in FreeCAD.listDocuments():
            FreeCAD.closeDocument(self.docName)
        self.param.SetBool("NewSketchUseAttachmentDialog", self.savedUseAttachment)
        flush_gui()

    def open_new_sketch(self):
        FreeCADGui.runCommand("PartDesign_NewSketch")
        flush_gui()
        sketches = [o for o in self.doc.Objects if o.isDerivedFrom("Sketcher::SketchObject")]
        self.assertEqual(len(sketches), 1)
        dialog = FreeCADGui.Control.activeTaskDialog()
        self.assertIsNotNone(dialog, "New Sketch opened no attachment dialog")
        return sketches[0].Name

    def origin_planes_shown(self):
        origin = FreeCADGui.ActiveDocument.getObject(self.body.Origin.Name)
        return origin is not None and origin.Visibility

    def test_undo_closes_the_dialog(self):
        """Ctrl+Z with the dialog open undoes the sketch; the dialog cancels itself (nothing is
        left to attach), so an OK can't reach the undone sketch."""
        name = self.open_new_sketch()
        FreeCADGui.runCommand("Std_Undo")
        flush_gui(300)
        self.assertIsNone(self.doc.getObject(name))
        dialog = FreeCADGui.Control.activeTaskDialog()
        if dialog is not None:
            # before the fix: still open, and OK crashed on the undone sketch
            dialog.accept()
            flush_gui()
        self.assertFalse(FreeCADGui.Control.activeDialog())
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(attacher_panels(), [])

    def test_cancel_after_the_body_is_removed(self):
        """The Body removed from the console while the dialog is open: Cancel closes the dialog
        and leaves the document usable."""
        self.open_new_sketch()
        self.doc.removeObject(self.body.Name)
        flush_gui()
        dialog = FreeCADGui.Control.activeTaskDialog()
        if dialog is not None:
            dialog.reject()
            flush_gui()
        self.assertFalse(FreeCADGui.Control.activeDialog())
        self.assertEqual(attacher_panels(), [])
        self.assertIsNone(self.doc.getObject("Body"))
        # the document still works
        box = self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        self.assertTrue(box.Shape.isValid())

    def test_closing_the_document_closes_the_dialog(self):
        """The document closed with the dialog open takes the dialog along; a new document has
        no dialog left over to Cancel. (A control: upstream's crash needs the new document at
        the freed one's address, which a test can't arrange; this passes before the fix too.)"""
        self.open_new_sketch()
        FreeCAD.closeDocument(self.docName)
        flush_gui()
        # before the fix the dialog stayed behind, keyed on the freed document
        self.assertEqual(attacher_panels(), [])
        other = FreeCAD.newDocument("TestNewSketchDialogGuiOther")
        try:
            flush_gui()
            dialog = FreeCADGui.Control.activeTaskDialog()
            if dialog is not None:
                # before the fix: the orphan, whose Cancel crashed
                dialog.reject()
                flush_gui()
            self.assertFalse(FreeCADGui.Control.activeDialog())
        finally:
            FreeCAD.closeDocument(other.Name)
