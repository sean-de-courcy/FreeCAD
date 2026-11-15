# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 6, design A's B5).

"""Presence in the GUI: the open question and the status-bar line (FreeCAD-CH, ops#640, item 6).

notes/folder-sync.md section 3 item 6; Gui/DocumentPresenceGui.cpp. Opening a team-folder
document that another computer has open (its marker under three minutes old) asks "Open anyway /
Cancel"; Cancel leaves it closed. While it is open here too, the status bar says who else has it.
An old marker asks nothing and shows nothing.

Designed documents: one App::FeatureTest, "Marker", saved as `Parts/Frame.FCStd` under a
temporary team folder. The other computer is played by a marker file this test writes."""

import json
import os
import shutil
import tempfile
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets

OTHER_HOST = "FCCH-TEST-OTHER-MAC"


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


class TestPresenceGui(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fcch_presencegui_")
        self.team = os.path.join(self.root, "team")
        os.makedirs(os.path.join(self.team, "Parts"))
        self.group = App.ParamGet("User parameter:BaseApp/Preferences/Document")
        self.savedTeam = self.group.GetString("TeamFolder", "")
        self.group.SetString("TeamFolder", self.team)
        self.markers = os.path.join(self.team, ".fcch", "open")
        self.file = os.path.join(self.team, "Parts", "Frame.FCStd")
        doc = App.newDocument("PresenceGuiFrame")
        doc.addObject("App::FeatureTest", "Marker").Integer = 1
        doc.saveAs(self.file)
        App.closeDocument(doc.Name)
        self.asked = []
        self.listening = True

    def tearDown(self):
        self.listening = False
        for name, doc in list(App.listDocuments().items()):
            if doc.FileName and os.path.normcase(doc.FileName).startswith(os.path.normcase(self.root)):
                App.closeDocument(name)
        self.group.SetString("TeamFolder", self.savedTeam)
        shutil.rmtree(self.root, ignore_errors=True)

    def writeForeign(self, age=0):
        os.makedirs(self.markers, exist_ok=True)
        with open(os.path.join(self.markers, "Frame-test-other.json"), "w", encoding="utf-8") as out:
            json.dump({"file": "Parts/Frame.FCStd", "user": "Ward", "host": OTHER_HOST,
                       "pid": 4242, "time": int(time.time()) - age}, out)

    def answerWith(self, buttonName):
        """Clicks `buttonName` in the presence question when it comes up, and records the text"""

        def answer():
            if not self.listening:
                return
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if widget.objectName() == "PresenceQuestion" and widget.isVisible():
                    self.asked.append(widget.text())
                    widget.findChild(QtWidgets.QPushButton, buttonName).click()
                    return
            QtCore.QTimer.singleShot(50, answer)

        QtCore.QTimer.singleShot(50, answer)

    def openedFrame(self):
        return [d for d in App.listDocuments().values()
                if d.FileName and os.path.samefile(d.FileName, self.file)]

    def statusLine(self):
        return Gui.getMainWindow().findChild(QtWidgets.QLabel, "presenceLabel").text()

    def testCancelLeavesItClosed(self):
        self.writeForeign(age=5)
        self.answerWith("PresenceCancel")
        Gui.loadFile(self.file)
        pump()
        self.assertEqual(len(self.asked), 1, "the question came up")
        self.assertIn("Ward on " + OTHER_HOST, self.asked[0])
        self.assertEqual(self.openedFrame(), [], "Cancel does not open it")

    def testOpenAnywayShowsTheStatusLine(self):
        self.writeForeign(age=5)
        self.answerWith("PresenceOpenAnyway")
        Gui.loadFile(self.file)
        pump()
        self.assertEqual(len(self.openedFrame()), 1)
        self.assertEqual(self.statusLine(), "Ward on {} has this document open".format(OTHER_HOST))
        os.remove(os.path.join(self.markers, "Frame-test-other.json"))
        # The heartbeat, run now: the other computer's marker is gone, so is the line
        timer = Gui.getMainWindow().findChild(QtCore.QTimer, "PresenceHeartbeat")
        self.assertIsNotNone(timer)
        timer.timeout.emit()
        pump()
        self.assertEqual(self.statusLine(), "", "they closed it: the line goes")

    def testOldMarkerAsksNothing(self):
        self.writeForeign(age=600)
        self.answerWith("PresenceCancel")
        Gui.loadFile(self.file)
        pump()
        self.assertEqual(self.asked, [], "ten minutes old: no question")
        self.assertEqual(len(self.openedFrame()), 1)
        self.assertEqual(self.statusLine(), "")
