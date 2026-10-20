# SPDX-License-Identifier: LGPL-2.1-or-later
# ****************************************************************************
# *                                                                          *
# *   This file is part of FreeCAD.                                          *
# *                                                                          *
# *   FreeCAD is free software: you can redistribute it and/or modify it     *
# *   under the terms of the GNU Lesser General Public License as            *
# *   published by the Free Software Foundation, either version 2.1 of the   *
# *   License, or (at your option) any later version.                        *
# *                                                                          *
# *   FreeCAD is distributed in the hope that it will be useful, but         *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
# *   Lesser General Public License for more details.                        *
# *                                                                          *
# *   You should have received a copy of the GNU Lesser General Public       *
# *   License along with FreeCAD. If not, see                                *
# *   <https://www.gnu.org/licenses/>.                                       *
# *                                                                          *
# ***************************************************************************/

"""The notification area raising a notification from its own code (FreeCAD-CH, ops#121).

Showing a non-intrusive notification under the offscreen platform makes Qt warn ("This plugin
does not support raise()"); the warning reaches the notification area again through the Console
while it held its mutex, and MSVC threw resource_deadlock_would_occur. In a GUI started from
FreeCADCmd (FreeCADGui.showMainWindow(), a plain QApplication) the exception unwound through the
event processing of an open and failed it.

Each test runs a FreeCADCmd child with the GUI off screen and a new, empty FREECAD_USER_HOME (the
start state the failure needs). It activates the main window (the box shows only in an active
one; off screen it starts inactive), warns, then opens a document of 400 boxes saved here, which
processes Qt events once the notification's 250 ms delay has passed.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import FreeCAD as App

BOXES = 400
WARNING = "ops121 warning before the open"
RAISE_WARNING = "does not support raise()"

CHILD_SCRIPT = r"""
import json, os, time, traceback
result = {}
try:
    import FreeCAD as App
    if os.environ.get("FC_NOTIFY_AREA_OFF") == "1":
        App.ParamGet("User parameter:BaseApp/Preferences/NotificationArea").SetBool(
            "NotificationAreaEnabled", False
        )
    import FreeCADGui
    FreeCADGui.showMainWindow()
    from PySide import QtWidgets
    app = QtWidgets.QApplication.instance()
    mainWindow = FreeCADGui.getMainWindow()
    # The startup's notifications go by first; the box shows only in an active main window
    for _ in range(50):
        app.processEvents()
        time.sleep(0.02)
    mainWindow.activateWindow()
    for _ in range(10):
        app.processEvents()
    result["active"] = mainWindow.isActiveWindow()
    App.Console.PrintWarning(os.environ["FC_NOTIFY_WARNING"] + "\n")
    time.sleep(0.3)
    try:
        doc = App.openDocument(os.environ["FC_NOTIFY_FILE"])
        result["objects"] = len(doc.Objects)
    except Exception as e:
        result["openError"] = str(e)
    # Let the delayed and the deferred notifications run
    end = time.time() + 2.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
    areas = []
    for button in mainWindow.statusBar().findChildren(QtWidgets.QPushButton):
        menu = button.menu()
        tree = menu.findChild(QtWidgets.QTreeWidget) if menu else None
        if tree is None:
            continue
        menu.aboutToShow.emit()  # moves the pushed notifications into the widget
        areas.append([tree.topLevelItem(i).text(2) for i in range(tree.topLevelItemCount())])
    result["areas"] = areas
except Exception:
    result["error"] = traceback.format_exc()
with open(os.environ["FC_NOTIFY_OUT"], "w", encoding="utf-8") as fh:
    json.dump(result, fh)
os._exit(0)
"""


def _freecadCmd():
    names = ("FreeCADCmd.exe", "FreeCADCmd") if sys.platform == "win32" else ("FreeCADCmd",)
    if os.path.basename(sys.executable).lower().startswith("freecadcmd"):
        return sys.executable
    for folder in ("bin", "MacOS", ""):
        for name in names:
            path = os.path.join(App.getHomePath(), folder, name)
            if os.path.isfile(path):
                return path
    raise FileNotFoundError("FreeCADCmd next to " + App.getHomePath())


class TestNotificationAreaReentry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="notify121-")
        cls.path = os.path.join(cls.folder, "boxes.FCStd")
        doc = App.newDocument("Notify121Boxes")
        try:
            for i in range(BOXES):
                box = doc.addObject("Part::Box", f"Box{i}")
                box.Placement.Base = App.Vector(20 * (i % 20), 20 * (i // 20), 0)
            doc.recompute()
            doc.saveAs(cls.path)
        finally:
            App.closeDocument(doc.Name)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def runChild(self, name, areaOff=False):
        """(the child's result, its log)."""
        work = os.path.join(self.folder, name)
        home = os.path.join(work, "home")
        os.makedirs(home)
        script = os.path.join(work, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(CHILD_SCRIPT)
        out = os.path.join(work, "out.json")
        env = dict(os.environ)
        env["FREECAD_USER_HOME"] = home
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["FC_NOTIFY_FILE"] = self.path
        env["FC_NOTIFY_OUT"] = out
        env["FC_NOTIFY_WARNING"] = WARNING
        env["FC_NOTIFY_AREA_OFF"] = "1" if areaOff else "0"
        logPath = os.path.join(work, "child.log")
        with open(logPath, "w") as log:
            proc = subprocess.Popen(
                [_freecadCmd(), script], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=work
            )
            try:
                proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        with open(logPath, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if not os.path.isfile(out):
            self.fail(f"the child wrote no result (exit {proc.returncode}):\n{text[-3000:]}")
        with open(out, encoding="utf-8") as fh:
            return json.load(fh), text

    def testOpenAfterAWarning(self):
        """The open succeeds, and no notification is lost: the warning before it, and the Qt
        warning raised by showing it, are both in the area."""
        result, log = self.runChild("area")
        self.assertNotIn("error", result, log[-3000:])
        self.assertNotIn("openError", result, log[-3000:])
        self.assertTrue(result["active"], "the main window is active, so the box shows")
        self.assertEqual(result["objects"], BOXES)
        self.assertNotIn("resource deadlock", log)
        self.assertEqual(len(result["areas"]), 1, "one notification area")
        messages = result["areas"][0]
        self.assertTrue(any(WARNING in m for m in messages), messages)
        if RAISE_WARNING in log:
            # Raised while the area showed the warning: pushed afterwards, not lost
            self.assertTrue(any(RAISE_WARNING in m for m in messages), messages)

    def testOpenWithTheAreaOff(self):
        """The harness workaround (NotificationAreaEnabled false) still opens, with no area."""
        result, log = self.runChild("area-off", areaOff=True)
        self.assertNotIn("error", result, log[-3000:])
        self.assertNotIn("openError", result, log[-3000:])
        self.assertEqual(result["objects"], BOXES)
        self.assertEqual(result["areas"], [])


if __name__ == "__main__":
    unittest.main()
