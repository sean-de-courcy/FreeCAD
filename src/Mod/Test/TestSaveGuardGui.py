# SPDX-License-Identifier: LGPL-2.1-or-later
# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************/

"""The save guard's notices and question in the GUI (FreeCAD-CH, ops#640, slice A2).

notes/files-saving-history-design.md section 4 and section 3 item 3; Gui/Document.cpp. When the
document's file is replaced on disk (the other computer's save, carried by the sync), its view shows
a bar: "Sean saved a newer version at 14:02." with Reload when the document is unchanged; Ctrl+S on
a changed document asks which version to keep, and no choice loses one. A sibling with a sync
tool's conflict-copy name shows "Two versions of this document exist" with Open the other / Keep
this one / Keep the other.

Designed documents: one App::FeatureTest, "Marker", whose Integer tells the versions apart (1 at
the first save, 2 for this computer's edit, 9 for the other computer's save, written by a second
document saved elsewhere and copied over the file).
"""

import os
import shutil
import tempfile
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(test, seconds=5.0):
    """Pumps events until `test()` is true or the time is up; returns its last value"""
    end = time.time() + seconds
    value = test()
    while not value and time.time() < end:
        pump(0.05)
        value = test()
    return value


class TestSaveGuardGui(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fcch_saveguardgui_")
        self.folder = os.path.join(self.root, "team")
        self.scratch = os.path.join(self.root, "scratch")
        os.makedirs(self.folder)
        os.makedirs(self.scratch)
        self.path = os.path.join(self.folder, "Plate.FCStd")
        self.group = App.ParamGet("User parameter:BaseApp/Preferences/Document")
        self.author = self.group.GetString("prefAuthor", "")
        self.group.SetString("prefAuthor", "Ward")
        self.opened = []
        self.doc = App.newDocument("SaveGuardGui")
        self.opened.append(self.doc.Name)
        self.doc.addObject("App::FeatureTest", "Marker").Integer = 1
        self.doc.saveAs(self.path)
        Gui.getDocument(self.doc.Name).Modified = False
        pump()

    def tearDown(self):
        for name in self.opened:
            if name in App.listDocuments():
                App.closeDocument(name)
        self.group.SetString("prefAuthor", self.author)
        pump()
        shutil.rmtree(self.root, ignore_errors=True)

    def _theirSave(self, target=None, value=9):
        theirs = os.path.join(self.scratch, "theirs.FCStd")
        self.group.SetString("prefAuthor", "Sean")
        try:
            doc = App.newDocument("SaveGuardTheirs")
            doc.addObject("App::FeatureTest", "Marker").Integer = value
            doc.saveAs(theirs)
            App.closeDocument(doc.Name)
        finally:
            self.group.SetString("prefAuthor", "Ward")
        shutil.copyfile(theirs, target or self.path)

    def _bars(self):
        return Gui.getMainWindow().findChildren(QtWidgets.QToolBar, "FileChangeBar")

    def _barText(self):
        bars = self._bars()
        if not bars:
            return ""
        label = bars[0].findChild(QtWidgets.QLabel, "FileChangeText")
        return label.text() if label else ""

    def _action(self, name):
        for bar in self._bars():
            for action in bar.actions():
                if action.objectName() == name:
                    return action
        return None

    def _activate(self):
        # The window coming back to the front is one of the check's triggers; the folder
        # watcher is the other
        app = QtWidgets.QApplication.instance()
        app.applicationStateChanged.emit(QtCore.Qt.ApplicationActive)

    def testNewerVersionShowsTheBarAndReloads(self):
        self.assertEqual(self._bars(), [])
        self._theirSave()
        self._activate()
        self.assertTrue(waitFor(lambda: "Sean saved a newer version" in self._barText()),
                        self._barText())
        reload = self._action("FileChangeReload")
        self.assertIsNotNone(reload)
        reload.trigger()
        self.assertTrue(waitFor(lambda: self._bars() == []))
        self.assertEqual(App.getDocument(self.doc.Name).getObject("Marker").Integer, 9)

    def testChangedDocumentIsToldTheSaveWillAsk(self):
        self.doc.getObject("Marker").Integer = 2
        Gui.getDocument(self.doc.Name).Modified = True
        self._theirSave()
        self._activate()
        self.assertTrue(waitFor(lambda: "Saving asks" in self._barText()), self._barText())
        self.assertIsNone(self._action("FileChangeReload"), "no reload over unsaved changes")

    def testSaveAsksAndKeepsBoth(self):
        self.doc.getObject("Marker").Integer = 2
        Gui.getDocument(self.doc.Name).Modified = True
        self._theirSave()
        asked = []

        def answer():
            box = QtWidgets.QApplication.activeModalWidget()
            if box is None or box.objectName() != "FileChangeQuestion":
                QtCore.QTimer.singleShot(100, answer)
                return
            asked.append(box.text())
            box.findChild(QtWidgets.QPushButton, "SaveMineOver").click()

        QtCore.QTimer.singleShot(100, answer)
        Gui.getDocument(self.doc.Name).save()
        self.assertTrue(asked and "Sean saved this document" in asked[0], asked)
        kept = [n for n in os.listdir(self.folder) if n.startswith("Plate (Sean ")]
        self.assertEqual(len(kept), 1, os.listdir(self.folder))
        self.assertFalse(Gui.getDocument(self.doc.Name).Modified)
        self.assertTrue(waitFor(lambda: self._bars() == []))

    def testConflictCopyShowsTheBar(self):
        other = os.path.join(self.folder, "Plate.sync-conflict-20261112-140200-ABCDEF7.FCStd")
        self._theirSave(other)
        self._activate()
        self.assertTrue(waitFor(lambda: "Two versions of this document exist" in self._barText()),
                        self._barText())
        self.assertIn("Sean", self._barText())
        keep = self._action("FileChangeKeepThis")
        self.assertIsNotNone(keep)
        self.assertIsNotNone(self._action("FileChangeKeepOther"))
        self.assertIsNotNone(self._action("FileChangeOpenOther"))
        keep.trigger()
        self.assertTrue(waitFor(lambda: self._bars() == []))
        self.assertFalse(os.path.exists(other))
        self.assertEqual(len([n for n in os.listdir(self.folder) if n.startswith("Plate (Sean ")]), 1)
