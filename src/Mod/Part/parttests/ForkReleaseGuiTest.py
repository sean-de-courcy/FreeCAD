# SPDX-License-Identifier: LGPL-2.1-or-later

"""The GUI side of files of a newer fork release (ops#323 PR A, notes/beta-compatibility.md 2.3):
the warning once after the open, and the save guard (Save a Copy / Save Anyway / Cancel). A timer
answers each modal box and records it. The App side is in ForkReleaseTest.
"""

import contextlib
import os
import shutil
import sys
import tempfile
import time
import unittest
from xml.sax.saxutils import escape as xml_escape

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from parttests.ForkReleaseTest import (
    FORK_RELEASE,
    _boxModel,
    _documentXml,
    _rewriteDocumentXml,
    _setDocumentAttribute,
)


def _acceptFile(path=None):
    """An answer for a file dialog: accepts it, with `path` selected if given."""

    def answer(dialog):
        if path:
            # The name field itself: selectFile() doesn't reach it before the dialog's file
            # model has listed the folder, and accept() then takes the suggested name
            dialog.findChild(QtWidgets.QLineEdit, "fileNameEdit").setText(path)
        dialog.accept()

    return answer


def _clickOk(dialog):
    """An answer for a dialog with a button box: clicks its OK button (the recovery dialog's "Start
    Recovery", then its "Finish")."""
    box = dialog.findChild(QtWidgets.QDialogButtonBox)
    box.button(QtWidgets.QDialogButtonBox.Ok).click()


def _rejectFile(dialog):
    """An answer for a file dialog: records what it suggests (the seen entry) and cancels."""
    dialog.reject()


def _waitWritable(path, seconds=10):
    """Waits until no other process holds `path` open. FreeCAD's save refuses a file it can't open
    exclusively ("No write permission ... read-only", `FileInfo::isWritable`), and on Windows a
    scanner may hold a file for a moment right after it was written: the 1-in-5 failure of the
    save after a save (PR 293 review)."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    invalid = wintypes.HANDLE(-1).value
    generic_write, open_existing = 0x40000000, 3
    deadline = time.monotonic() + seconds
    while True:
        handle = kernel32.CreateFileW(path, generic_write, 0, None, open_existing, 0, None)
        if handle != invalid:
            kernel32.CloseHandle(handle)
            return
        if time.monotonic() > deadline:
            return  # the save then reports it
        time.sleep(0.05)


DIALOG_PARAMETERS = "User parameter:BaseApp/Preferences/Dialog"


# The folders of the tests that showed a file dialog: kept until the next run's start. Deleting one
# while the process runs was followed, in 2 of 16 Windows runs off screen, by Qt aborting a later
# save ("Qt Concurrent has caught an exception thrown from a worker thread"); 0 of 24 with them kept
KEPT_FOLDERS = os.path.realpath(os.path.join(tempfile.gettempdir(), "ForkReleaseGuiTest-dialogs"))


class ForkReleaseGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(KEPT_FOLDERS, ignore_errors=True)
        os.makedirs(KEPT_FOLDERS, exist_ok=True)

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ForkReleaseGuiTest"))
        self.docNames = []
        # Qt's own file dialog, which the timer can answer (a native one it can't see)
        group = App.ParamGet(DIALOG_PARAMETERS)
        self.nativeDialogSetting = (
            group.GetBool("DontUseNativeDialog", True),
            "DontUseNativeDialog" in group.GetBools(),
        )
        group.SetBool("DontUseNativeDialog", True)

    def tearDown(self):
        for name in self.docNames:
            if name in App.listDocuments():
                App.closeDocument(name)
        if not self.dir.startswith(KEPT_FOLDERS):
            shutil.rmtree(self.dir, ignore_errors=True)
        group = App.ParamGet(DIALOG_PARAMETERS)
        value, present = self.nativeDialogSetting
        if present:
            group.SetBool("DontUseNativeDialog", value)
        else:
            group.RemBool("DontUseNativeDialog")

    @contextlib.contextmanager
    def answering(self, *answers):
        """Answers the modal boxes shown while the block runs with the buttons `answers`, in
        order (a box with no answer left is rejected; a file dialog takes a function such as
        _acceptFile()), and yields the list of (title, text, buttons, answer) it saw."""
        seen = []
        pending = list(answers)
        acting = []

        # An answer runs from the event loop, not from the timer's slot: one that opens a nested
        # modal box (accepting a file dialog over an existing file asks to replace it) would
        # otherwise block the slot, and Qt doesn't fire a timer again while its slot runs
        def run():
            action = acting.pop()
            action()

        actor = QtCore.QTimer()
        actor.setSingleShot(True)
        actor.timeout.connect(run)

        def act(action):
            acting.append(action)
            actor.start(0)

        def answer():
            modal = QtWidgets.QApplication.activeModalWidget()
            if modal is None or acting:
                return
            box = isinstance(modal, QtWidgets.QMessageBox)
            text = modal.text() if box else ""
            buttons = sorted(b.text().replace("&", "") for b in modal.buttons()) if box else []
            wanted = pending.pop(0) if pending else None
            if isinstance(modal, QtWidgets.QFileDialog):
                # A file dialog: its text is the file it suggests; the answer is a function
                text = modal.selectedFiles()[0] if modal.selectedFiles() else ""
                seen.append((modal.windowTitle(), text, [], "file"))
                App.Console.PrintLog(f"ForkReleaseGuiTest: {seen[-1]}\n")
                act((lambda: wanted(modal)) if callable(wanted) else modal.reject)
                return
            if callable(wanted):
                # Any other dialog, or a box the answer looks into: the function answers it
                seen.append((modal.windowTitle(), text, buttons, "call"))
                App.Console.PrintLog(f"ForkReleaseGuiTest: {seen[-1]}\n")
                act(lambda: wanted(modal))
                return
            seen.append((modal.windowTitle(), text, buttons, wanted))
            # In the console log: which box a failing or hanging run stopped at
            App.Console.PrintLog(f"ForkReleaseGuiTest: {seen[-1]}\n")
            if wanted and box:
                for button in modal.buttons():
                    if button.text().replace("&", "") == wanted:
                        act(button.click)
                        return
            act(modal.reject)

        timer = QtCore.QTimer()
        timer.timeout.connect(answer)
        timer.start(100)
        try:
            yield seen
        finally:
            timer.stop()
            actor.stop()

    def _keepFolder(self):
        """This test shows file dialogs: its files go in a folder kept until the next run."""
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ForkReleaseGuiTest", dir=KEPT_FOLDERS))

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
        _waitWritable(newer)
        with self.answering("Cancel") as seen:
            self.assertFalse(gdoc.save())
        self.assertEqual(len(seen), 1, seen)
        _, text, buttons, _ = seen[0]
        self.assertIn("ForkRelease 999", text)
        self.assertEqual(buttons, ["Cancel", "Save Anyway", "Save a Copy…"])
        self.assertEqual(FORK_RELEASE.findall(_documentXml(newer)), ["999"], "not saved")
        self.assertIn("ForkRelease 999", App.getNewerFormat(doc))

        _waitWritable(newer)
        with self.answering("Save Anyway") as seen:
            self.assertTrue(gdoc.save())
        self.assertEqual(len(seen), 1, seen)
        self.assertEqual(FORK_RELEASE.findall(_documentXml(newer)), [str(App.getForkRelease())])
        self.assertEqual(App.getNewerFormat(doc), "")

        # Saved: no more question
        _waitWritable(newer)
        with self.answering() as seen:
            saved = gdoc.save()
        self.assertEqual(seen, [])
        self.assertTrue(saved)

    def _openedNewer(self):
        newer = self._newerFile()
        with self.answering("OK") as seen:
            Gui.loadFile(newer)
        self.assertEqual(len(seen), 1, seen)
        doc = self._opened(newer)
        return newer, doc, Gui.getDocument(doc.Name)

    def testSaveAsOntoItsOwnFileAsks(self):
        """Save As onto the document's own file saves it there: a newer file asks first, as a
        Save does (PR 293 review)."""
        self._keepFolder()
        newer, doc, gdoc = self._openedNewer()
        _waitWritable(newer)
        with self.answering(_acceptFile(newer), "Yes", "Cancel") as seen:
            self.assertFalse(gdoc.saveAs())
        self.assertEqual(os.path.realpath(seen[0][1]), os.path.realpath(newer), seen)
        self.assertEqual(seen[-1][2], ["Cancel", "Save Anyway", "Save a Copy…"], seen)
        self.assertIn("ForkRelease 999", seen[-1][1])
        self.assertEqual(FORK_RELEASE.findall(_documentXml(newer)), ["999"], "not saved")
        self.assertIn("ForkRelease 999", App.getNewerFormat(doc))

        _waitWritable(newer)
        with self.answering(_acceptFile(newer), "Yes", "Save Anyway") as seen:
            self.assertTrue(gdoc.saveAs())
        self.assertEqual(seen[-1][3], "Save Anyway", seen)
        self.assertEqual(FORK_RELEASE.findall(_documentXml(newer)), [str(App.getForkRelease())])
        self.assertEqual(App.getNewerFormat(doc), "")

    def testSaveACopyOffersACopyName(self):
        """The save guard's "Save a Copy…" suggests "<name> (copy).FCStd" beside the file, and a
        copy onto the document's own file is refused with a message (PR 293 review)."""
        self._keepFolder()
        newer, doc, gdoc = self._openedNewer()
        _waitWritable(newer)
        with self.answering("Save a Copy…", _rejectFile) as seen:
            gdoc.save()
        self.assertEqual(len(seen), 2, seen)
        suggested = seen[1][1]
        self.assertEqual(os.path.basename(suggested), "Newer (copy).FCStd", seen)
        self.assertEqual(
            os.path.realpath(os.path.dirname(suggested)), os.path.realpath(self.dir), seen
        )

        _waitWritable(newer)
        with self.answering("Save a Copy…", _acceptFile(newer), "Yes", "OK") as seen:
            gdoc.save()
        self.assertEqual(seen[-1][0], "Save a Copy", seen)
        self.assertEqual(FORK_RELEASE.findall(_documentXml(newer)), ["999"], "not saved")
        self.assertIn("ForkRelease 999", App.getNewerFormat(doc))

    def testMergeOfANewerFileWarnsOnce(self):
        """A merge of a newer file shows the warning as it happens (decision 71 Q2 B), once:
        merging it again, or opening another file later, shows nothing more."""
        newer = self._newerFile()
        target = App.newDocument("GuiMergeTarget")
        self.docNames.append(target.Name)
        gdoc = Gui.getDocument(target.Name)
        with self.answering("OK") as seen:
            gdoc.mergeProject(newer)
        self.assertEqual(len(seen), 1, seen)
        title, text, _, _ = seen[0]
        self.assertIn("newer", title.lower())
        self.assertIn("ForkRelease 999", text)
        self.assertIn("ForkRelease 999", App.getNewerFormat(target))

        with self.answering() as seen:
            gdoc.mergeProject(newer)
        self.assertEqual(seen, [], "the same markers again")

        current = os.path.join(self.dir, "Saved.FCStd")
        with self.answering() as seen:
            Gui.loadFile(current)
        self._opened(current)
        self.assertEqual(seen, [], "no late warning at the next open")

    def testMergeWarnsOnlyWhenItBringsMarkers(self):
        """The merge box blames the merged objects only when they made the document newer (ops#330
        L2). A document newer by itself, opened from the console, shows no box at a merge of
        current objects; a warned document shows one when a merge brings another marker."""
        newer = self._newerFile()
        current = os.path.join(self.dir, "Saved.FCStd")
        doc = App.openDocument(newer)  # no GUI open: its notice is still pending
        self.docNames.append(doc.Name)
        with self.answering() as seen:
            Gui.getDocument(doc.Name).mergeProject(current)
        self.assertEqual(seen, [], "the merged objects are current")
        App.closeDocument(doc.Name)

        _, doc, gdoc = self._openedNewer()  # warned at the open
        newest = os.path.join(self.dir, "Newest.FCStd")
        _rewriteDocumentXml(current, newest, _setDocumentAttribute("ForkRelease", 1000))
        with self.answering("OK") as seen:
            gdoc.mergeProject(newest)
        self.assertEqual(len(seen), 1, seen)
        self.assertIn("newer", seen[0][0].lower())
        self.assertIn("ForkRelease 1000", seen[0][1])

    def _fakeCrashedSession(self, snapshot, label, fileName):
        """Recovery files of a crashed session in the user cache, as the start finds them: the
        session's lock file (not held) and one document folder with `snapshot` (a compressed
        recovery file) and its meta file. Returns the paths to delete afterwards."""
        cache = App.getUserCachePath()
        # Letters only: the start skips the lock files whose name holds its own (numeric) ID
        session = "opsTestRecovery"
        exe = App.ConfigGet("ExeName")
        lock = os.path.join(cache, f"{exe}_{session}.lock")
        folder = os.path.join(cache, f"{exe}_Doc_{session}Document_{session}")
        os.makedirs(folder)
        shutil.copyfile(snapshot, os.path.join(folder, "fc_recovery_file.fcstd"))
        with open(os.path.join(folder, "fc_recovery_file.xml"), "w", encoding="utf-8") as meta:
            meta.write(
                "<?xml version='1.0' encoding='utf-8'?>\n"
                '<AutoRecovery SchemaVersion="1">\n'
                "  <Status>Created</Status>\n"
                f"  <Label>{xml_escape(label)}</Label>\n"
                f"  <FileName>{xml_escape(fileName)}</FileName>\n"
                "</AutoRecovery>\n"
            )
        open(lock, "w").close()
        return [lock, folder]

    def testRecoveryWarnsAtOnce(self):
        """A recovered newer document warns when it is recovered, not at the next File > Open
        (ops#330 L1)."""
        newer = self._newerFile()
        doc = App.openDocument(newer)
        self.assertTrue(App.writeRecoverySnapshotToTransientDir(doc, compressed=True))
        snapshot = os.path.join(self.dir, "Snapshot.FCStd")
        shutil.copyfile(os.path.join(doc.TransientDir, "fc_recovery_file.fcstd"), snapshot)
        App.closeDocument(doc.Name)
        leftovers = self._fakeCrashedSession(snapshot, "Newer", newer)
        try:
            with self.answering(_clickOk, "OK", _clickOk) as seen:
                self.assertTrue(Gui.checkForPreviousCrashes())
        finally:
            for path in leftovers:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.exists(path):
                    os.remove(path)
        recovered = self._opened(newer)
        self.assertIn("ForkRelease 999", App.getNewerFormat(recovered))
        self.assertEqual(len(seen), 3, seen)
        self.assertEqual(seen[0][3], "call", seen)  # Start Recovery
        title, text, _, answer = seen[1]
        self.assertIn("newer", title.lower(), seen)
        self.assertIn("ForkRelease 999", text)
        self.assertEqual(answer, "OK")
        self.assertEqual(seen[2][0], seen[0][0], seen)  # Finish

        current = os.path.join(self.dir, "Saved.FCStd")
        with self.answering() as seen:
            Gui.loadFile(current)
        self._opened(current)
        self.assertEqual(seen, [], "no late warning at the next open")

    def testDropWarnsAfterTheDrop(self):
        """A dropped newer file opens, and warns, once the drop has returned: the drag source
        doesn't wait for the box (ops#330 L3)."""
        newer = self._newerFile()
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(newer)])
        window = Gui.getMainWindow()
        # Qt gives a drop only to the widget that accepted the drag's entry
        enter = QtGui.QDragEnterEvent(
            QtCore.QPoint(10, 10),
            QtCore.Qt.CopyAction,
            mime,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(window, enter)
        self.assertTrue(enter.isAccepted())
        event = QtGui.QDropEvent(
            QtCore.QPointF(10, 10),
            QtCore.Qt.CopyAction,
            mime,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        dropping = [False]
        during = []

        def ok(box):
            during.append(dropping[0])
            box.accept()

        with self.answering(ok) as seen:
            dropping[0] = True
            QtWidgets.QApplication.sendEvent(window, event)
            dropping[0] = False
            deadline = time.monotonic() + 30
            while not during and time.monotonic() < deadline:
                QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 50)
        self._opened(newer)
        self.assertEqual(len(seen), 1, seen)
        self.assertIn("newer", seen[0][0].lower())
        self.assertEqual(during, [False], "the box showed inside the drop")
