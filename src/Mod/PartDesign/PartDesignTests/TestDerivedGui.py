# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 round 6, notes/onshape-tabs-design.md 2.5 and 6: Derived)

"""Onshape's Derived dialog and its row (PartDesign_Derived, TaskDerived.cpp).

In Part Studio 2 (the active App::Part, no part active), Derived opens a dialog: the other part
studios with parts ("Part Studio 1", the document's top level) and their parts, all ticked. OK
makes the Derived feature in one undo step: the Features list shows one "Derived 1" row however
many parts it brought in, the Parts list the new parts. Editing the row reopens the dialog with the
parts ticked; deleting the row removes the parts it made (one undo step brings them back); a source
deleted turns the row red with the message naming it. OK with nothing ticked keeps the dialog.

Designed geometry (as TestDerived): Part Studio 1 holds a Body "Box", a 10 mm cube at the origin
(1000 mm^3), and a Body "Bar" 30 x 10 x 10 from x = 20 (3000 mm^3); Part Studio 2 is an App::Part.
Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests.TestDerived import boxBody
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor
from PartDesignTests.TestStudioSequence import sketch
from PartDesignTests.TestCrossBodyGui import siblingEraPath  # ops#654 list on first use

PARAM = "User parameter:BaseApp/Preferences/Mod/PartDesign"
BAR = QtWidgets.QListWidgetItem.UserType + 1  # FeatureList::BarType
DEFAULT = QtCore.Qt.UserRole + 3  # FeatureList::DefaultRole
RED = "#d03030"  # FeaturesView's error rows


class TestDerivedGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("DerivedGui")
        self.doc.UndoMode = 1
        Gui.Selection.clearSelection()
        self.param = App.ParamGet(PARAM)
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        Gui.activateWorkbench("PartDesignWorkbench")
        self.showTree(False)
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        self.assertTrue(waitFor(lambda: self.view() is not None and self.view().isVisible()))
        self.features = self.view().findChild(QtWidgets.QListWidget, "featureList")
        self.parts = self.view().findChild(QtWidgets.QTreeWidget, "partsList")
        self.box, self.boxFeature = boxBody(self.doc, "Box", 10)
        self.bar, self.barFeature = boxBody(self.doc, "Bar", 30, x=20)
        self.studio2 = self.doc.addObject("App::Part", "Studio2")
        self.studio2.Label = "Part Studio 2"
        self.doc.recompute()
        # Under the typed tabs a Derived is made in the tab you are in (Onshape): Part Studio 2's
        # tab is opened, which makes its App::Part the view's active part; under FreeCAD's keymap
        # the one view's active part is set
        tabs = getattr(Gui, "DocumentTabs", None)
        if tabs is not None and tabs.isOn():
            done, refusal = tabs.switchTo(self.doc, self.studio2.Name)
            self.assertTrue(done, refusal)
            pump(0.2)
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", None)
        view.setActiveObject("part", self.studio2)
        pump(0.2)

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        self.showTree(self.savedTree)
        pump()

    def showTree(self, tree):
        if self.param.GetBool("ShowModelTree", False) != tree:
            Gui.runCommand("PartDesign_ToggleModelTree")

    def view(self):
        return Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")

    def visible(self, cls, name):
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
        return found[0] if found else None

    def openDialog(self, command=True):
        if command:
            Gui.runCommand("PartDesign_Derived")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no Derived dialog")
        Gui.Control.showTaskView()
        self.assertTrue(waitFor(lambda: self.visible(QtWidgets.QListWidget, "derivedParts") is not None))
        pump(0.2)

    def close(self, ok):
        which = QtWidgets.QDialogButtonBox.Ok if ok else QtWidgets.QDialogButtonBox.Cancel
        taskButton(which).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.3)

    def studioItems(self):
        combo = self.visible(QtWidgets.QComboBox, "derivedStudio")
        return [combo.itemText(i) for i in range(combo.count())]

    def partItems(self):
        rows = self.visible(QtWidgets.QListWidget, "derivedParts")
        return [(rows.item(i).text(), rows.item(i).checkState() == QtCore.Qt.Checked) for i in range(rows.count())]

    def tick(self, label, on):
        rows = self.visible(QtWidgets.QListWidget, "derivedParts")
        for i in range(rows.count()):
            if rows.item(i).text() == label:
                rows.item(i).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
        pump(0.1)

    def featureRows(self):
        """The Features list's rows, the bar as "|", without the default geometry rows."""
        out = []
        for i in range(self.features.count()):
            item = self.features.item(i)
            if item.data(DEFAULT):
                continue
            out.append("|" if item.type() == BAR else item.text())
        return out

    def featureItem(self, label):
        for i in range(self.features.count()):
            item = self.features.item(i)
            if item.type() != BAR and item.text() == label:
                return item
        raise AssertionError(f"no row {label}: {self.featureRows()}")

    def partRows(self):
        return [self.parts.topLevelItem(i).text(0) for i in range(self.parts.topLevelItemCount())]

    def leads(self):
        return [o for o in self.doc.Objects if PartDesign.derivedLead(o) is o]

    def derivedBodies(self):
        return [o for o in self.studio2.Group if o.TypeId == "PartDesign::Body"]

    def deleteSelected(self):
        """Std_Delete; a dependency question would be answered No after 3 s (and fail the test)."""
        asked = []

        def answer():
            box = QtWidgets.QApplication.activeModalWidget()
            if box is not None:
                asked.append(box.windowTitle())
                box.reject()

        QtCore.QTimer.singleShot(3000, answer)
        Gui.runCommand("Std_Delete")
        pump(0.5)
        self.assertEqual(asked, [])

    def testTheDialogMakesOneDerivedRow(self):
        """Derived in Part Studio 2: the dialog lists Part Studio 1 and its parts, all ticked; with
        Bar unticked, OK: one Derived feature, the row "Derived 1" in Part Studio 2's list, its
        part in the Parts list, 1000 mm^3. One undo removes it all."""
        before = sorted(o.Name for o in self.doc.Objects)
        self.openDialog()
        self.assertEqual(self.studioItems(), ["Part Studio 1"])
        self.assertEqual(self.partItems(), [("Box", True), ("Bar", True)])
        self.assertTrue(self.visible(QtWidgets.QCheckBox, "derivedAll").isChecked())
        self.tick("Bar", False)
        self.assertFalse(self.visible(QtWidgets.QCheckBox, "derivedAll").isChecked())
        self.close(ok=True)
        [lead] = self.leads()
        [body] = self.derivedBodies()
        self.assertAlmostEqual(body.Shape.Volume, 1000, places=6)
        self.assertIs(PartDesign.derivedSource(lead), self.box)
        self.assertTrue(waitFor(lambda: self.featureRows() == ["Derived 1", "|"]), self.featureRows())
        self.assertTrue(waitFor(lambda: self.partRows() == [body.Label]), self.partRows())
        Gui.runCommand("Std_Undo")
        pump(0.3)
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)

    def testSeveralPartsOneRowAndTheEdit(self):
        """Both parts: one row "Derived 1", two parts; the row's Edit reopens the dialog with both
        ticked; Box unticked, OK: one part left (Bar, 3000 mm^3), the row still "Derived 1"."""
        self.openDialog()
        self.close(ok=True)
        [lead] = self.leads()
        self.assertEqual(len(PartDesign.derivedMembers(lead)), 2)
        self.assertTrue(waitFor(lambda: self.featureRows() == ["Derived 1", "|"]), self.featureRows())
        self.assertTrue(waitFor(lambda: len(self.partRows()) == 2), self.partRows())
        Gui.getDocument(self.doc.Name).getObject(lead.Name).doubleClicked()
        self.openDialog(command=False)
        self.assertEqual(self.partItems(), [("Box", True), ("Bar", True)])
        self.tick("Box", False)
        self.close(ok=True)
        [lead] = self.leads()
        self.assertEqual(PartDesign.derivedMembers(lead), [lead])
        self.assertIs(PartDesign.derivedSource(lead), self.bar)
        [body] = self.derivedBodies()
        self.assertAlmostEqual(body.Shape.Volume, 3000, places=6)
        self.assertTrue(waitFor(lambda: self.featureRows() == ["Derived 1", "|"]), self.featureRows())
        self.assertTrue(waitFor(lambda: self.partRows() == [body.Label]), self.partRows())

    def testDeletingTheRowRemovesItsParts(self):
        """The row selected, Delete: no Derived feature, part or binder is left in Part Studio 2,
        with no question; one undo brings both parts back."""
        self.openDialog()
        self.close(ok=True)
        [lead] = self.leads()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, lead.Name)
        self.deleteSelected()
        # The active part went with it: the lists fall back to Part Studio 1 (no tabs yet)
        self.assertEqual(self.leads(), [])
        self.assertEqual(self.studio2.Group, [])
        self.assertFalse([o for o in self.doc.Objects if o.TypeId == "PartDesign::FeatureBase"])
        Gui.runCommand("Std_Undo")
        pump(0.3)
        self.doc.recompute()
        self.assertEqual(len(self.leads()), 1)
        self.assertEqual(len(self.derivedBodies()), 2)
        volumes = sorted(round(b.Shape.Volume, 6) for b in self.derivedBodies())
        self.assertEqual(volumes, [1000, 3000])

    def testAMissingSourceTurnsTheRowRed(self):
        """Box derived, then Part Studio 1's Box deleted: the row "Derived 1" is red, its tooltip
        "Missing source part: Box (Part Studio 1)"."""
        self.openDialog()
        self.tick("Bar", False)
        self.close(ok=True)
        self.assertTrue(waitFor(lambda: self.featureRows() == ["Derived 1", "|"]), self.featureRows())
        self.box.removeObject(self.boxFeature)
        self.doc.removeObject(self.boxFeature.Name)
        self.doc.removeObject(self.box.Name)
        self.doc.recompute()

        def red():
            brush = self.featureItem("Derived 1").foreground()
            return brush.style() != QtCore.Qt.NoBrush and brush.color().name() == RED

        self.assertTrue(waitFor(red), "the row isn't red")
        self.assertIn("Missing source part: Box (Part Studio 1)", self.featureItem("Derived 1").toolTip())

    @siblingEraPath
    def testDerivedAcceptsAnOpenExtrude(self):
        """Review R6-3: with an Extrude (Pad) dialog open on a sketch of Part Studio 2's Plate,
        Derived is enabled; run, it accepts the Pad first (the plate is 20 x 10 x 10 mm, 2000
        mm^3) and opens its own dialog, listing Part Studio 1; while that is open, Derived is
        greyed. OK makes the Derived feature."""
        plate = self.doc.addObject("PartDesign::Body", "Plate")
        self.studio2.addObject(plate)
        profile = sketch(plate, "PlateSk", (0, 0, 20, 10))
        self.doc.recompute()
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", plate)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, profile.Name)
        Gui.runCommand("PartDesign_Pad")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no Pad dialog")
        pump(0.3)
        [pad] = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Pad"]
        derived = Gui.Command.get("PartDesign_Derived")
        self.assertTrue(derived.isActive())
        Gui.Selection.clearSelection()
        self.openDialog()
        self.assertEqual(self.studioItems(), ["Part Studio 1"])
        self.assertIsNotNone(self.doc.getObject(pad.Name))
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(plate.Shape.Volume, 2000, places=6)
        self.assertFalse(derived.isActive())
        self.close(ok=True)
        self.assertEqual(len(self.leads()), 1)
        self.assertTrue(derived.isActive())

    def testOkWithNothingTickedKeepsTheDialog(self):
        """All parts unticked, OK: the dialog stays with "Choose the parts to derive"; Cancel
        makes nothing."""
        before = sorted(o.Name for o in self.doc.Objects)
        self.openDialog()
        self.visible(QtWidgets.QCheckBox, "derivedAll").click()
        pump(0.1)
        self.assertEqual(self.partItems(), [("Box", False), ("Bar", False)])
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog())
        message = self.visible(QtWidgets.QLabel, "derivedMessage")
        self.assertIsNotNone(message)
        self.assertEqual(message.text(), "Choose the parts to derive")
        self.close(ok=False)
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)


class TestDerivedFromFileGui(unittest.TestCase):
    """D1 (b2 integrator): "Derived from file" goes into the active studio. The hidden read of the
    source file leaves no active document, so the studio must be read before it, and the caller's
    document is active again afterwards.

    Designed geometry: the source file holds Body "A", a 10 mm cube (1000 mm^3), at the top
    level; the owner document has the App::Part "T", the active studio."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="derivedfromfile")
        self.src = os.path.join(self.dir, "DFSource.FCStd")
        source = App.newDocument("DFSource")
        boxBody(source, "A", 10)
        source.recompute()
        source.saveAs(self.src)
        App.closeDocument(source.Name)
        self.doc = App.newDocument("DFOwner")
        self.studio = self.doc.addObject("App::Part", "T")
        self.doc.recompute()
        Gui.activateWorkbench("PartDesignWorkbench")
        Gui.ActiveDocument.ActiveView.setActiveObject("part", self.studio)
        self.warnings = []
        self.saved = (QtWidgets.QFileDialog.getOpenFileName, QtWidgets.QMessageBox.warning)
        QtWidgets.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (self.src, ""))
        QtWidgets.QMessageBox.warning = staticmethod(
            lambda parent, title, text, *a: self.warnings.append(text)
        )

    def tearDown(self):
        QtWidgets.QFileDialog.getOpenFileName, QtWidgets.QMessageBox.warning = self.saved
        for name in list(App.listDocuments()):
            if name.startswith("DF"):
                App.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def testTheDerivedGoesIntoTheActiveStudio(self):
        import DerivedFromFileGui

        def accept():
            box = QtWidgets.QApplication.activeModalWidget()
            if box is not None:
                box.accept()

        # A repeating timer: the hidden read of the source comes before the chooser, and late in a
        # full unit run it can take longer than a single shot's delay (the chooser then blocked)
        timer = QtCore.QTimer()
        timer.timeout.connect(accept)
        timer.start(200)
        try:
            DerivedFromFileGui.CommandDerivedFromFile().Activated()
        finally:
            timer.stop()
        pump(0.5)
        self.assertEqual(self.warnings, [])
        self.assertIs(App.ActiveDocument, self.doc, "Expected the caller's document active again")
        self.assertIsNotNone(Gui.ActiveDocument)
        leads = []
        for obj in self.doc.Objects:
            lead = PartDesign.derivedLead(obj)
            if lead is not None and lead not in leads:
                leads.append(lead)
        self.assertEqual(len(leads), 1, [o.Name for o in self.doc.Objects])
        body = leads[0].getParentGeoFeatureGroup()
        self.assertIs(body.getParentGeoFeatureGroup(), self.studio, "Expected the copy in studio T")
        self.assertAlmostEqual(body.Shape.Volume, 1000, places=3)
