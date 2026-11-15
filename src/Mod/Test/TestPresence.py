# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 6, design A's B5).

"""Presence markers: "Ward has this open on the Mac" (FreeCAD-CH, ops#640, folder sync item 6).

notes/folder-sync.md section 3 item 6; App/DocumentPresence.cpp. A document open inside the team
folder has one marker per computer and process in `<team>/.fcch/open/`, with the user, the
computer, the process and a heartbeat time. Another computer's marker under three minutes old
means "open elsewhere"; an older one does not. This computer's markers of a process that is gone
are removed. Closing the document removes ours.

Designed documents: one App::FeatureTest, "Marker", saved as `Parts/Frame.FCStd` under a
temporary team folder. The other computer is played by marker files this test writes."""

import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import FreeCAD

OTHER_HOST = "FCCH-TEST-OTHER-MAC"


def deadPid():
    """The process id of a process that has just ended"""
    if sys.platform == "win32":
        process = subprocess.Popen(["cmd", "/c", "exit"], creationflags=0x08000000)
    else:
        process = subprocess.Popen(["true"])
    process.wait()
    return process.pid


class DocumentPresenceCases(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fcch_presence_")
        self.team = os.path.join(self.root, "team")
        self.outside = os.path.join(self.root, "outside")
        os.makedirs(os.path.join(self.team, "Parts"))
        os.makedirs(self.outside)
        self.group = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document")
        self.savedTeam = self.group.GetString("TeamFolder", "")
        self.group.SetString("TeamFolder", self.team)
        self.markers = os.path.join(self.team, ".fcch", "open")
        self.file = os.path.join(self.team, "Parts", "Frame.FCStd")
        self.opened = []

    def tearDown(self):
        for name in self.opened:
            if name in FreeCAD.listDocuments():
                FreeCAD.closeDocument(name)
        self.group.SetString("TeamFolder", self.savedTeam)
        shutil.rmtree(self.root, ignore_errors=True)

    def saveDocument(self, path=None):
        doc = FreeCAD.newDocument("PresenceFrame")
        self.opened.append(doc.Name)
        marker = doc.addObject("App::FeatureTest", "Marker")
        marker.Integer = 1
        doc.saveAs(path or self.file)
        return doc

    def markerFiles(self):
        if not os.path.isdir(self.markers):
            return []
        return sorted(n for n in os.listdir(self.markers) if n.endswith(".json"))

    def writeForeign(self, age=0, host=OTHER_HOST, pid=4242, user="Ward", file="Parts/Frame.FCStd"):
        os.makedirs(self.markers, exist_ok=True)
        path = os.path.join(self.markers, "Frame-test-{}-{}.json".format(host, pid))
        with open(path, "w", encoding="utf-8") as out:
            json.dump(
                {"file": file, "user": user, "host": host, "pid": pid,
                 "time": int(time.time()) - age, "app": "FreeCAD-CH"},
                out,
            )
        return path

    def testSaveWritesOursAndCloseRemovesIt(self):
        doc = self.saveDocument()
        files = self.markerFiles()
        self.assertEqual(len(files), 1, "one marker for one open document")
        with open(os.path.join(self.markers, files[0]), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["file"], "Parts/Frame.FCStd")
        self.assertEqual(data["pid"], os.getpid())
        self.assertLess(abs(time.time() - data["time"]), 30)
        self.assertEqual(FreeCAD.presence(self.file), [], "our own marker is not someone else")
        FreeCAD.closeDocument(doc.Name)
        self.assertEqual(self.markerFiles(), [], "closing removes our marker")

    def testOpenWritesOurs(self):
        doc = self.saveDocument()
        FreeCAD.closeDocument(doc.Name)
        doc = FreeCAD.openDocument(self.file)
        self.opened.append(doc.Name)
        self.assertEqual(len(self.markerFiles()), 1, "opening writes our marker")

    def testRefreshMovesTheHeartbeat(self):
        self.saveDocument()
        path = os.path.join(self.markers, self.markerFiles()[0])
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["time"] -= 500
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        FreeCAD.refreshPresence()
        with open(path, encoding="utf-8") as f:
            self.assertLess(abs(time.time() - json.load(f)["time"]), 30)

    def testFreshForeignMarkerIsReported(self):
        self.saveDocument()
        self.writeForeign(age=10)
        found = FreeCAD.presence(self.file)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["host"], OTHER_HOST)
        self.assertEqual(found[0]["user"], "Ward")
        self.assertEqual(
            FreeCAD.presenceMessage(self.file),
            "Ward on {} has this document open".format(OTHER_HOST),
        )

    def testCaseOfTheNameDoesNotMatter(self):
        self.saveDocument()
        self.writeForeign(file="parts/FRAME.FCStd")
        self.assertEqual(len(FreeCAD.presence(self.file)), 1)

    def testOldForeignMarkerIsNot(self):
        self.saveDocument()
        path = self.writeForeign(age=600)
        self.assertEqual(FreeCAD.presence(self.file), [], "ten minutes old: not open")
        self.assertEqual(FreeCAD.presenceMessage(self.file), "")
        self.assertTrue(os.path.exists(path), "another computer's marker is never deleted here")

    def testOtherDocumentsMarkerIsNot(self):
        self.saveDocument()
        self.writeForeign(file="Parts/Other.FCStd")
        self.assertEqual(FreeCAD.presence(self.file), [])

    def testDeadProcessOnThisHostIsCleaned(self):
        self.saveDocument()
        host = None
        with open(os.path.join(self.markers, self.markerFiles()[0]), encoding="utf-8") as f:
            host = json.load(f)["host"]
        pid = deadPid()
        stale = self.writeForeign(host=host, pid=pid, user="Sean")
        self.assertEqual(FreeCAD.presence(self.file), [], "a crashed FreeCAD here is not someone")
        self.assertFalse(os.path.exists(stale), "its marker is removed")
        self.assertEqual(len(self.markerFiles()), 1, "ours stays")

    def testLiveProcessOnThisHostIsReported(self):
        self.saveDocument()
        with open(os.path.join(self.markers, self.markerFiles()[0]), encoding="utf-8") as f:
            host = json.load(f)["host"]
        if sys.platform == "win32":
            other = subprocess.Popen(["cmd", "/c", "ping -n 30 127.0.0.1 >nul"], creationflags=0x08000000)
        else:
            other = subprocess.Popen(["sleep", "30"])
        try:
            self.writeForeign(host=host, pid=other.pid, user="Sean")
            found = FreeCAD.presence(self.file)
            self.assertEqual(len(found), 1, "another FreeCAD on this computer counts")
            self.assertIn("another FreeCAD on this computer", FreeCAD.presenceMessage(self.file))
        finally:
            other.kill()
            other.wait()

    def testSaveAsOutsideRemovesOurs(self):
        doc = self.saveDocument()
        self.assertEqual(len(self.markerFiles()), 1)
        doc.saveAs(os.path.join(self.outside, "Frame.FCStd"))
        self.assertEqual(self.markerFiles(), [], "the document left the team folder")

    def testOutsideTheTeamFolderWritesNothing(self):
        self.saveDocument(os.path.join(self.outside, "Frame.FCStd"))
        self.assertFalse(os.path.exists(os.path.join(self.outside, ".fcch")))
        self.assertFalse(os.path.exists(os.path.join(self.team, ".fcch")))
        self.assertEqual(FreeCAD.presence(os.path.join(self.outside, "Frame.FCStd")), [])

    def testNoTeamFolderWritesNothing(self):
        self.group.SetString("TeamFolder", "")
        self.saveDocument()
        self.assertFalse(os.path.exists(os.path.join(self.team, ".fcch")))

    def testMarkersAreNotIgnored(self):
        """The ignore list keeps backups off the sync, not the markers (folder-sync item 2)"""
        self.saveDocument()
        with open(os.path.join(self.team, ".stglobalignore"), encoding="utf-8") as f:
            patterns = [line.strip() for line in f if line.strip() and not line.startswith("//")]
        name = self.markerFiles()[0]
        for pattern in patterns:
            bare = pattern.replace("(?i)", "").replace("(?d)", "")
            for candidate in (".fcch", ".fcch/open", ".fcch/open/" + name, name):
                self.assertFalse(
                    fnmatch.fnmatch(candidate.lower(), bare.lower()),
                    "{} matches {}".format(candidate, pattern),
                )
