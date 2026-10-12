# SPDX-License-Identifier: LGPL-2.1-or-later

"""The GUI side of files of a newer fork release (ops#323 PR A, notes/beta-compatibility.md 2.3):
the warning once after the open, and the save guard (Save a Copy / Save Anyway / Cancel). A timer
answers each modal box and records it. The App side is in ForkReleaseTest.
"""

import contextlib
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from parttests.ForkReleaseTest import (
    FORK_RELEASE,
    _boxModel,
    _documentXml,
    _rewriteDocumentXml,
    _setDocumentAttribute,
)


class ForkReleaseGuiTest(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ForkReleaseGuiTest"))
        self.docNames = []

    def tearDown(self):
        for name in self.docNames:
            if name in App.listDocuments():
                App.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    @contextlib.contextmanager
    def answering(self, *answers):
        """Answers the modal boxes shown while the block runs with the buttons `answers`, in
        order (a box with no answer left is rejected), and yields the list of
        (title, text, buttons, answer) it saw."""
        seen = []
        pending = list(answers)

        def answer():
            modal = QtWidgets.QApplication.activeModalWidget()
            if modal is None:
                return
            box = isinstance(modal, QtWidgets.QMessageBox)
            text = modal.text() if box else ""
            buttons = sorted(b.text().replace("&", "") for b in modal.buttons()) if box else []
            wanted = pending.pop(0) if pending else None
            seen.append((modal.windowTitle(), text, buttons, wanted))
            if wanted and box:
                for button in modal.buttons():
                    if button.text().replace("&", "") == wanted:
                        button.click()
                        return
            modal.reject()

        timer = QtCore.QTimer()
        timer.timeout.connect(answer)
        timer.start(100)
        try:
            yield seen
        finally:
            timer.stop()

    def _newerFile(self):
        doc = App.newDocument("GuiSaved")
        self.docNames.append(doc.Name)
        _boxModel(doc)
        path = os.path.join(self.dir, "Saved.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        newer = os.path.join(self.dir, "Newer.FCStd")
        _rewriteDocumentXml(path, newer, _setDocumentAttribute("ForkRelease", 999))
        return newer

    def _opened(self, path):
        for name, doc in App.listDocuments().items():
            if os.path.realpath(doc.FileName) == os.path.realpath(path):
                self.docNames.append(name)
                return doc
        self.fail("not open: " + path)

    def testWarnAtOpenAndAskBeforeSaving(self):
        newer = self._newerFile()
        with self.answering("OK") as seen:
            Gui.loadFile(newer)
        doc = self._opened(newer)
        self.assertEqual(len(seen), 1, seen)
        title, text, _, _ = seen[0]
        self.assertIn("newer", title.lower())
        self.assertIn("ForkRelease 999", text)

        gdoc = Gui.getDocument(doc.Name)
        with self.answering("Cancel") as seen:
            self.assertFalse(gdoc.save())
        self.assertEqual(len(seen), 1, seen)
        _, text, buttons, _ = seen[0]
        self.assertIn("ForkRelease 999", text)
        self.assertEqual(buttons, ["Cancel", "Save Anyway", "Save a Copy…"])
        self.assertEqual(FORK_RELEASE.findall(_documentXml(newer)), ["999"], "not saved")
        self.assertIn("ForkRelease 999", App.getNewerFormat(doc))

        with self.answering("Save Anyway") as seen:
            self.assertTrue(gdoc.save())
        self.assertEqual(len(seen), 1, seen)
        self.assertEqual(FORK_RELEASE.findall(_documentXml(newer)), [str(App.getForkRelease())])
        self.assertEqual(App.getNewerFormat(doc), "")

        # Saved: no more question
        with self.answering() as seen:
            saved = gdoc.save()
        self.assertEqual(seen, [])
        self.assertTrue(saved)
