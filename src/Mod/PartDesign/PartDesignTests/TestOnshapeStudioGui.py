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
# ***************************************************************************

"""Onshape's defaults for a new user and a new document (FreeCAD-CH, ops#605 Tier 1, 2a, 2f).

- The task box's OK and Cancel are a check and a cross, and OK is the default button: Enter in the
  graphics area or on a check box accepts a feature's panel, as in Onshape; Enter in a value field
  only commits the value (ops#640 rank 38).
- Std_New in PartDesign makes a part studio: one Body, its Origin's three planes shown; they stay
  shown after its first sketch, as Onshape's default planes do (ops#626). Std_New with 1 (the
  Start page's cards) is an empty document.
- A new settings folder starts with the "FreeCAD-CH Onshape" preference pack; an existing user.cfg,
  and a run started with a script (the test runners), keep their settings.

Designed model: a 10 x 20 rectangle sketch in a Body, padded 5 (volume 1000). The first-start
cases run FreeCAD.exe on new settings folders, with a probe add-on that reports one setting."""

import os
import shutil
import subprocess
import tempfile
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets
from PySide6 import QtTest

from PartDesignTests.Scenarios import models
from PartDesignTests.TestExpressionFieldsGui import liveButtonBoxes
from PartDesignTests.TestCrossBodyGui import siblingEraPath  # ops#654 list on first use

ONSHAPE = "Gui::OnshapeNavigationStyle"  # the pack's and the code's default since ops#640

# The probe: an add-on in the settings folder whose InitGui.py, once the event loop runs (after
# the start-up steps, the first-start apply among them), writes the navigation style and exits
# hard, so nothing is saved and no prompt is shown
PROBE = r'''
import os
import FreeCAD
from PySide import QtCore


def report():
    style = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View").GetString("NavigationStyle")
    # the style a new 3D view runs: the parameter where it is set, else the code default
    try:
        import FreeCADGui

        FreeCAD.newDocument("Probe")
        viewStyle = FreeCADGui.ActiveDocument.ActiveView.getNavigationType()
    except Exception as error:  # noqa: BLE001  reported, not raised: the probe must exit
        viewStyle = "error: %s" % error
    with open(os.environ["FC_ONSHAPE_PROBE_OUT"], "w", encoding="utf-8") as out:
        out.write("style=" + style + "\n")
        out.write("viewStyle=" + viewStyle + "\n")
        units = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Units")
        out.write("decimals=%d\n" % units.GetInt("Decimals", -1))
        view = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View")
        out.write("orbit=%d\n" % view.GetInt("OrbitStyle", -1))
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 0)
    os._exit(0)


QtCore.QTimer.singleShot(0, report)
'''

# A user.cfg of an existing settings folder, with one setting of its own
USER_CFG = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<FCParameters>
  <FCParamGroup Name="Root">
    <FCParamGroup Name="BaseApp">
      <FCParamGroup Name="Preferences">
        <FCParamGroup Name="View">
          <FCText Name="NavigationStyle">Gui::CADNavigationStyle</FCText>
        </FCParamGroup>
      </FCParamGroup>
    </FCParamGroup>
  </FCParamGroup>
</FCParameters>
"""


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def taskButton(which):
    """The task panel's OK or Cancel button (dead wrappers: TestExpressionFieldsGui.liveButtonBoxes)."""
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
        except RuntimeError:  # a box (or a parent) deleted under its wrapper: not the panel's
            continue
    return None


def taskViewHolds(widget):
    parent = widget.parentWidget()
    while parent is not None:
        if parent.metaObject().className() == "Gui::TaskView::TaskView":
            return True
        parent = parent.parentWidget()
    return False


def visibleChild(name):
    for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget, name):
        if widget.isVisible():
            return widget
    return None


def freecadExecutable():
    name = "FreeCAD.exe" if os.name == "nt" else "FreeCAD"
    path = os.path.join(App.getHomePath(), "bin", name)
    return path if os.path.isfile(path) else None


class RenamedOkPanel:
    """A task panel with a line edit whose OK the dialog renames, as Mesh's Delete panel."""

    def __init__(self):
        self.form = QtWidgets.QWidget()
        self.field = QtWidgets.QLineEdit(self.form)
        layout = QtWidgets.QVBoxLayout(self.form)
        layout.addWidget(self.field)
        self.accepted = False

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def modifyStandardButtons(self, box):
        box.button(QtWidgets.QDialogButtonBox.Ok).setText("Delete")

    def accept(self):
        self.accepted = True
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class TestOnshapeStudioGui(unittest.TestCase):
    def setUp(self):
        self.docs = []
        self.homes = []
        Gui.activateWorkbench("PartDesignWorkbench")

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump(0.2)
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        for home in self.homes:
            shutil.rmtree(home, ignore_errors=True)
        pump(0.2)

    def newDocument(self, iMsg=None):
        """The document Std_New makes (with iMsg, if given)."""
        before = set(App.listDocuments())
        if iMsg is None:
            Gui.runCommand("Std_New")
        else:
            Gui.runCommand("Std_New", iMsg)
        pump(0.3)
        added = [name for name in App.listDocuments() if name not in before]
        self.assertEqual(len(added), 1, added)
        self.docs.append(added[0])
        return App.getDocument(added[0])

    def originVisibility(self, body):
        """Whether the Origin's planes, axes and point are drawn, by role: each one's own
        Visibility under the Origin's (a new Body's elements are all on, under a hidden Origin)."""
        shown = body.Origin.ViewObject.Visibility
        return {f.Role: shown and f.ViewObject.Visibility for f in body.Origin.OriginFeatures}

    def assertStudioPlanes(self, body, shown):
        visibility = self.originVisibility(body)
        for role in ("XY_Plane", "XZ_Plane", "YZ_Plane"):
            self.assertEqual(visibility[role], shown, (role, visibility))
        for role in ("X_Axis", "Y_Axis", "Z_Axis", "Origin"):
            self.assertFalse(visibility[role], (role, visibility))

    # -- 2a: the check and cross, Enter accepts ---------------------------------------------------

    def openPadPanel(self):
        """A Pad panel on a 10 x 20 rectangle sketch in a Body. Returns the document."""
        doc = models.newDocument("OnshapeEnter")
        self.docs.append(doc.Name)
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 10, 20), body)
        doc.recompute()
        App.setActiveDocument(doc.Name)
        Gui.setActiveDocument(doc.Name)
        Gui.activateView("Gui::View3DInventor", True)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, profile.Name)
        Gui.runCommand("PartDesign_Pad")
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "no Pad panel")
        return doc

    @siblingEraPath
    def testEnterInThePadPanelAcceptsIt(self):
        """A Pad panel on a 10 x 20 sketch, length 5: Enter in the length field commits the value
        and leaves the panel open (ops#640 rank 38, the hands-on notes); Enter in the graphics area
        then closes the panel and keeps the Pad (volume 1000). OK is a check icon with no words and
        the default button; Cancel is a cross."""
        doc = self.openPadPanel()

        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
        self.assertIsNotNone(ok)
        self.assertIsNotNone(cancel)
        self.assertTrue(ok.isDefault())
        self.assertEqual(ok.text(), "")
        self.assertFalse(ok.icon().isNull())
        self.assertEqual(cancel.text(), "")
        self.assertFalse(cancel.icon().isNull())

        length = visibleChild("lengthEdit")
        self.assertIsNotNone(length, "no length field")
        length.setProperty("rawValue", 5.0)
        length.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.3)
        QtTest.QTest.keyClick(length, QtCore.Qt.Key_Return)
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "Enter in the length field closed the panel")

        viewport = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
        viewport.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.3)
        QtTest.QTest.keyClick(viewport, QtCore.Qt.Key_Return)
        pump(0.5)

        self.assertFalse(Gui.Control.activeDialog(), "Enter in the graphics left the Pad panel open")
        pads = [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Pad")]
        self.assertEqual(len(pads), 1)
        self.assertAlmostEqual(pads[0].Shape.Volume, 1000.0, places=6)

    def testEnterOnAFocusedCancelCancels(self):
        """Enter on Cancel with the focus is Cancel, not the default OK: the panel closes and no
        Pad is left."""
        doc = self.openPadPanel()
        cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
        cancel.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.3)
        QtTest.QTest.keyClick(cancel, QtCore.Qt.Key_Return)
        pump(0.5)
        self.assertFalse(Gui.Control.activeDialog(), "Enter on Cancel left the panel open")
        self.assertEqual([o.Name for o in doc.Objects if o.isDerivedFrom("PartDesign::Pad")], [])

    def testEnterInTheSketchEditorKeepsItOpen(self):
        """The sketch editor's OK is a check that Enter doesn't click: Enter on a list of its
        panel, and the keypad's Enter in a field of the panel (as in a tool's parameter field,
        whose widget filters only Return), leave the sketch in edit. The tool's own fields are
        hidden off screen, so the field is a line edit put into the panel."""
        doc = models.newDocument("OnshapeSketchEnter")
        self.docs.append(doc.Name)
        body = models.body(doc)
        sketch = models.sketch(doc, "Profile", models.rectangle(0, 0, 10, 20), body)
        doc.recompute()
        App.setActiveDocument(doc.Name)
        Gui.setActiveDocument(doc.Name)
        Gui.activateView("Gui::View3DInventor", True)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        Gui.ActiveDocument.setEdit(sketch.Name)
        pump(1.0)
        self.assertTrue(Gui.ActiveDocument.getInEdit(), "the sketch isn't in edit")
        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        self.assertIsNotNone(ok)
        self.assertFalse(ok.icon().isNull())
        lists = [
            w
            for w in Gui.getMainWindow().findChildren(QtWidgets.QListWidget)
            if w.isVisible() and w.count() > 0
        ]
        self.assertTrue(lists, "no list with items in the sketch editor")
        lists[0].setCurrentRow(0)
        lists[0].setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.2)
        QtTest.QTest.keyClick(lists[0], QtCore.Qt.Key_Enter)
        pump(0.5)
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QDialog) and widget.isVisible():
                widget.reject()
        pump(0.3)
        self.assertTrue(Gui.ActiveDocument.getInEdit(), "Enter closed the sketch")

        field = QtWidgets.QLineEdit(lists[0].parentWidget())
        field.show()
        pump(0.2)
        self.assertTrue(field.isVisible() and taskViewHolds(field))
        field.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.2)
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Enter, QtCore.Qt.KeypadModifier)
        pump(0.5)
        self.assertTrue(Gui.ActiveDocument.getInEdit(), "keypad Enter in a field closed the sketch")
        field.deleteLater()
        Gui.ActiveDocument.resetEdit()
        pump(0.5)

    def testEnterInARenamedOkPanelDoesNothing(self):
        """A panel whose OK the dialog renamed ("Delete", as Mesh's) keeps the words, gets no
        check, and Enter in its field doesn't click it (Qt makes it the default when it shows)."""
        doc = models.newDocument("OnshapeRenamed")
        self.docs.append(doc.Name)
        App.setActiveDocument(doc.Name)
        Gui.setActiveDocument(doc.Name)
        Gui.activateView("Gui::View3DInventor", True)
        pump(0.5)
        panel = RenamedOkPanel()
        Gui.Control.showDialog(panel)
        pump(0.5)
        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        self.assertIsNotNone(ok)
        self.assertEqual(ok.text(), "Delete")
        self.assertTrue(ok.icon().isNull())
        panel.field.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.2)
        QtTest.QTest.keyClick(panel.field, QtCore.Qt.Key_Return)
        pump(0.5)
        self.assertFalse(panel.accepted, "Enter clicked the renamed OK")
        self.assertTrue(Gui.Control.activeDialog())

    # -- 2f: a new document in PartDesign is a part studio ----------------------------------------

    def testNewDocumentInPartDesignIsAPartStudio(self):
        """Std_New in PartDesign: one Body, active, its three planes shown, its axes and point
        not. New Sketch with nothing selected opens a sketch with no plane in the sketch editor
        (ops#640 rank 2, hands-on C-1: its Sketch plane field armed); the planes stay shown after
        it and after a sketch on the selected XY plane (ops#626)."""
        doc = self.newDocument()
        bodies = [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")]
        self.assertEqual(len(bodies), 1, [o.Name for o in doc.Objects])
        body = bodies[0]
        active = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        self.assertEqual(active.Name if active else None, body.Name)
        self.assertStudioPlanes(body, True)

        # New Sketch with nothing selected opens a sketch with no plane in the sketch editor
        plane = models.originFeature(body, "XY_Plane")
        Gui.Selection.clearSelection()
        Gui.runCommand("PartDesign_NewSketch")
        pump(0.5)
        self.assertTrue(Gui.ActiveDocument.getInEdit(), "the new sketch isn't in edit")
        sketches = [o for o in body.Group if o.isDerivedFrom("Sketcher::SketchObject")]
        self.assertEqual(len(sketches), 1, [o.Name for o in body.Group])
        self.assertEqual(sketches[0].AttachmentSupport, [])
        self.assertEqual(sketches[0].MapMode, "Deactivated")
        self.assertStudioPlanes(body, True)
        Gui.ActiveDocument.resetEdit()
        pump(0.3)
        self.assertStudioPlanes(body, True)

        # A sketch on the selected XY plane: the planes stay
        Gui.Selection.addSelection(doc.Name, body.Name, body.Origin.Name + "." + plane.Name + ".")
        Gui.runCommand("PartDesign_NewSketch")
        pump(0.5)
        sketches = [o for o in body.Group if o.isDerivedFrom("Sketcher::SketchObject")]
        self.assertEqual(len(sketches), 2, [o.Name for o in body.Group])
        if Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
            pump(0.3)
        self.assertStudioPlanes(body, True)

    def testNewDocumentWithOneIsEmpty(self):
        """Std_New with 1, as the Start page's cards run it: an empty document in PartDesign too."""
        doc = self.newDocument(1)
        self.assertEqual([o.Name for o in doc.Objects], [])

    # -- Tier 1: the first-start apply ------------------------------------------------------------

    def runOnNewHome(self, userCfg=None, script=False):
        """FreeCAD.exe on a new settings folder holding the probe (and `userCfg` as user.cfg),
        started with no file or with an empty script. Returns the navigation style parameter it
        reports, the style a new 3D view runs there, and whether it has the pack's three decimals
        (a key nothing else writes on start)."""
        exe = freecadExecutable()
        if exe is None:
            self.skipTest("no FreeCAD executable beside the build")
        home = tempfile.mkdtemp(prefix="onshape-first-start-")
        self.homes.append(home)
        probeDir = os.path.join(home, "Mod", "OnshapeProbe")
        os.makedirs(probeDir)
        with open(os.path.join(probeDir, "InitGui.py"), "w", encoding="utf-8") as f:
            f.write(PROBE)
        if userCfg is not None:
            with open(os.path.join(home, "user.cfg"), "w", encoding="utf-8") as f:
                f.write(userCfg)
        out = os.path.join(home, "probe.txt")
        env = dict(os.environ)
        env["FREECAD_USER_HOME"] = home
        env["FC_ONSHAPE_PROBE_OUT"] = out
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        args = [exe]
        if script:
            empty = os.path.join(home, "empty.py")
            with open(empty, "w", encoding="utf-8") as f:
                f.write("# nothing\n")
            args.append(empty)
        subprocess.run(
            args, env=env, timeout=240, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self.assertTrue(os.path.isfile(out), "the probe didn't report")
        with open(out, encoding="utf-8") as f:
            lines = dict(line.rstrip("\n").split("=", 1) for line in f if "=" in line)
        self.probe = lines  # every key the probe reported, for checks beyond the three
        return lines.get("style"), lines.get("viewStyle"), lines.get("decimals") == "3"

    def testFirstStartAppliesTheOnshapePack(self):
        """A settings folder with no user.cfg starts with the pack's Onshape navigation style."""
        style, _, decimals = self.runOnNewHome()
        self.assertEqual((style, decimals), (ONSHAPE, True))
        # rank 90 (hands-on R12b): Onshape's plain right-drag is a free trackball, so the pack
        # sets the free orbit (4, RoundedArcball) over a turntable; Alt+right-drag keeps Z up
        self.assertEqual(self.probe.get("orbit"), "4", "the pack's orbit is not the free one")

    def testFirstStartLeavesAnExistingUserCfgAlone(self):
        """A settings folder with a user.cfg keeps its own navigation style."""
        style, _, decimals = self.runOnNewHome(userCfg=USER_CFG)
        self.assertEqual((style, decimals), ("Gui::CADNavigationStyle", False))

    def testFirstStartSkipsARunWithAScript(self):
        """A run started with a script (as the test runners start FreeCAD) keeps the code
        defaults on a new folder: not the pack's decimals, and no navigation style written (the
        pack is skipped; the status bar's indicator writes none when the key is unset, ops#640),
        so a new 3D view runs the code default, the Onshape style."""
        style, viewStyle, decimals = self.runOnNewHome(script=True)
        self.assertIn(style, ("", ONSHAPE))
        self.assertEqual(viewStyle, ONSHAPE)
        self.assertFalse(decimals)
