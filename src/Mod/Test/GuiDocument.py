# SPDX-License-Identifier: LGPL-2.1-or-later
"""**************************************************************************
*                                                                          *
*   Copyright (c) 2024 Ondsel <development@ondsel.com>                     *
*                                                                          *
*   This file is part of FreeCAD.                                          *
*                                                                          *
*   FreeCAD is free software: you can redistribute it and/or modify it     *
*   under the terms of the GNU Lesser General Public License as            *
*   published by the Free Software Foundation, either version 2.1 of the   *
*   License, or (at your option) any later version.                        *
*                                                                          *
*   FreeCAD is distributed in the hope that it will be useful, but         *
*   WITHOUT ANY WARRANTY; without even the implied warranty of             *
*   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
*   Lesser General Public License for more details.                        *
*                                                                          *
*   You should have received a copy of the GNU Lesser General Public       *
*   License along with FreeCAD. If not, see                                *
*   <https://www.gnu.org/licenses/>.                                       *
*                                                                          *
***************************************************************************/"""

import inspect
import os
import sys
import tempfile
import threading
import time
import unittest
import warnings
import zipfile

import FreeCAD
import FreeCADGui
from PySide6 import QtCore, QtGui, QtWidgets

# ---------------------------------------------------------------------------
# define the functions to test the FreeCAD Gui Document code
# ---------------------------------------------------------------------------


class TestGuiDocument(unittest.TestCase):
    def setUp(self):
        # Create a new document
        self.doc = FreeCAD.newDocument("TestDoc")

    def tearDown(self):
        # Close the document
        if self.doc is not None and self.doc.Name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(self.doc.Name)

    def _findAutoSaver(self):
        app = QtWidgets.QApplication.instance()
        self.assertIsNotNone(app)

        for child in app.children():
            meta_object = child.metaObject() if hasattr(child, "metaObject") else None
            if meta_object and meta_object.className() == "Gui::AutoSaver":
                return child

        raise self.failureException("Gui::AutoSaver was not found in the QApplication object tree")

    def _recoveryArchive(self):
        return os.path.join(self.doc.TransientDir, "fc_recovery_file.fcstd")

    def _removeRecoveryArchive(self):
        archive = self._recoveryArchive()
        if os.path.exists(archive):
            os.remove(archive)

    def _invokeAutoSaverFlush(self):
        invoked = QtCore.QMetaObject.invokeMethod(
            self._findAutoSaver(),
            "flushPendingSave",
            QtCore.Qt.ConnectionType.DirectConnection,
            QtCore.Q_ARG(str, self.doc.Name),
        )
        self.assertTrue(invoked)

    def _processEventsUntil(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
            if predicate():
                return True
            time.sleep(0.01)

        return predicate()

    def _assertRecoveryArchiveContains(self, expected_label=None):
        archive = self._recoveryArchive()
        self.assertTrue(os.path.isfile(archive))

        with zipfile.ZipFile(archive) as recovery:
            self.assertIn("Document.xml", recovery.namelist())
            self.assertIn("GuiDocument.xml", recovery.namelist())

            if expected_label is not None:
                document_xml = recovery.read("Document.xml").decode("utf-8", errors="replace")
                self.assertIn(expected_label, document_xml)

    def _writeArchiveWithoutGuiDocument(self, source_path, target_path):
        with zipfile.ZipFile(source_path, "r") as source:
            self.assertIn("Document.xml", source.namelist())
            self.assertIn("GuiDocument.xml", source.namelist())

            with zipfile.ZipFile(target_path, "w") as target:
                for item in source.infolist():
                    if item.filename == "GuiDocument.xml":
                        continue

                    target.writestr(item, source.read(item.filename))

        with zipfile.ZipFile(target_path, "r") as target:
            self.assertIn("Document.xml", target.namelist())
            self.assertNotIn("GuiDocument.xml", target.namelist())

    def testPropertyDescriptionMarksModified(self):
        # FreeCAD-CH (ops#317, D-2): a dynamic property's new documentation or group marks the
        # Gui document modified, as a rename does; it didn't, so closing lost it without a prompt
        varSet = self.doc.addObject("App::VarSet", "VarSet")
        varSet.addProperty("App::PropertyLength", "Width", "Sizes", "old text")
        guiDoc = FreeCADGui.getDocument(self.doc.Name)
        for change in (lambda: varSet.setDocumentationOfProperty("Width", "new text"),
                       lambda: varSet.setGroupOfProperty("Width", "Other")):
            guiDoc.Modified = False
            change()
            self.assertTrue(guiDoc.Modified)

    def testGetTreeRootObject(self):
        # Create objects at the root level
        group1 = self.doc.addObject("App::DocumentObjectGroup", "Group1")
        group2 = self.doc.addObject("App::DocumentObjectGroup", "Group2")
        obj1 = self.doc.addObject("App::FeaturePython", "RootObject1")
        part1 = self.doc.addObject("App::Part", "Part1")

        # Create App::Parts and groups with objects in them
        part1_obj = part1.newObject("App::FeaturePython", "Part1_Object")
        group3 = group2.newObject("App::DocumentObjectGroup", "Group1")
        group1_obj = group3.newObject("App::FeaturePython", "Group1_Object")

        # Fetch the root objects using getTreeRootObjects
        root_objects = FreeCADGui.getDocument("TestDoc").TreeRootObjects

        # Check if the new function returns the correct root objects
        expected_root_objects = [group1, group2, obj1, part1]
        self.assertEqual(set(root_objects), set(expected_root_objects))

    def testIssue30418(self):
        class ViewProvider:
            def __init__(self, vobj):
                vobj.Proxy = self

            def attach(self, vobj):
                self.ViewObject = vobj
                self.Object = vobj.Object

            def setEdit(self, vobj, mode):
                return True

            def unsetEdit(self, vobj, mode):
                obj = vobj.Object
                doc = obj.Document
                doc.removeObject(obj.Name)
                return True

        gui = FreeCADGui.getDocument(self.doc)

        self.doc.openTransaction("Add object")
        obj = self.doc.addObject("App::FeaturePython", "Object")
        ViewProvider(obj.ViewObject)
        self.doc.commitTransaction()
        gui.setEdit(obj, 0)
        self.doc.undo()

        self.assertTrue(True)

    def testViewObjectRequiresMainThread(self):
        obj = self.doc.addObject("App::FeaturePython", "ThreadGuard")

        result = {}

        def access_view_object():
            try:
                _ = obj.ViewObject
            except Exception as exc:  # pragma: no cover - exercised through assertion below
                result["exception"] = exc

        worker = threading.Thread(target=access_view_object)
        worker.start()
        worker.join()

        self.assertIn("exception", result)
        self.assertIsInstance(result["exception"], RuntimeError)
        self.assertIn("main thread", str(result["exception"]).lower())

    def testRefreshFallsBackToSyncForFeaturePython(self):
        params = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document")
        old_async = params.GetBool("AsyncRecomputeWorker", False)

        class RefreshProxy:
            def __init__(self):
                self.executed_thread_id = None

            def execute(self, obj):
                self.executed_thread_id = threading.get_ident()
                time.sleep(0.05)

        proxy = RefreshProxy()
        obj = self.doc.addObject("App::FeaturePython", "PythonFeature")
        obj.Proxy = proxy
        obj.touch()

        try:
            params.SetBool("AsyncRecomputeWorker", True)

            start = time.monotonic()
            FreeCADGui.runCommand("Std_Refresh", 0)
            elapsed = time.monotonic() - start
        finally:
            params.SetBool("AsyncRecomputeWorker", old_async)

        self.assertEqual(proxy.executed_thread_id, threading.get_ident())
        self.assertGreaterEqual(elapsed, 0.04)

    def testAsyncRefreshRunsDocumentObserversOnTheMainThread(self):
        """The worker's document signals run their slots on the main thread (ops#365): on
        Windows FreeCADApp.dll had its own null copy of the GUI's hooks, so an observer of
        signalRecomputedObject ran on the recompute worker during an async Std_Refresh."""
        params = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document")
        old_async = params.GetBool("AsyncRecomputeWorker", False)
        main = threading.get_ident()

        class Observer:
            def __init__(self, doc):
                self.doc = doc
                self.threads = []

            def slotRecomputedObject(self, obj):
                if obj.Document == self.doc and obj.Name == "Feature":
                    self.threads.append(threading.get_ident())

        obj = self.doc.addObject("App::FeatureTest", "Feature")
        self.doc.recompute()
        observer = Observer(self.doc)
        FreeCAD.addDocumentObserver(observer)
        try:
            params.SetBool("AsyncRecomputeWorker", True)
            FreeCADGui.setActiveDocument(self.doc.Name)
            obj.touch()
            FreeCADGui.runCommand("Std_Refresh", 0)
            # On the worker: its hop to this thread waits for the event loop
            ranBeforeReturning = list(observer.threads)
            self.assertTrue(self._processEventsUntil(lambda: observer.threads, timeout=10.0))
            self.assertTrue(self._processEventsUntil(lambda: not self.doc.Recomputing))
        finally:
            FreeCAD.removeDocumentObserver(observer)
            params.SetBool("AsyncRecomputeWorker", old_async)

        self.assertEqual(observer.threads, [main])
        self.assertEqual(ranBeforeReturning, [])

    def testCloseDuringAsyncRefreshRunsTheWorkersHops(self):
        """Closing a document while the worker waits in a hop to the main thread (ops#365): the
        close waits for the worker's request and runs the hops meanwhile. It waited for a worker
        that waited for it (a hang, off Windows before ops#365, since the hop happened there)."""
        params = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document")
        old_async = params.GetBool("AsyncRecomputeWorker", False)
        main = threading.get_ident()

        class Observer:
            def __init__(self, doc):
                self.doc = doc
                self.threads = []

            def slotRecomputedObject(self, obj):
                if obj.Document == self.doc and obj.Name == "Feature":
                    self.threads.append(threading.get_ident())

        obj = self.doc.addObject("App::FeatureTest", "Feature")
        self.doc.recompute()
        observer = Observer(self.doc)
        FreeCAD.addDocumentObserver(observer)
        name = self.doc.Name
        try:
            params.SetBool("AsyncRecomputeWorker", True)
            FreeCADGui.setActiveDocument(name)
            obj.touch()
            FreeCADGui.runCommand("Std_Refresh", 0)
            # No events: the worker reaches its first hop and waits there, Recomputing set
            deadline = time.monotonic() + 10.0
            while not self.doc.Recomputing and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.doc.Recomputing)
            FreeCAD.closeDocument(name)
            self.doc = None
        finally:
            FreeCAD.removeDocumentObserver(observer)
            params.SetBool("AsyncRecomputeWorker", old_async)

        self.assertNotIn(name, FreeCAD.listDocuments())
        self.assertEqual(observer.threads, [main])

    def testASlotClosingItsDocumentInTheWorkersHopGetsARuntimeError(self):
        """A slot in the worker's hop that closes the document being recomputed gets a Python
        RuntimeError (ops#365). App.closeDocument let the C++ refusal unwind through the
        interpreter's frames: the except never ran, and a later slot in the same wait walked a
        cycle of stale frames forever."""
        params = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document")
        old_async = params.GetBool("AsyncRecomputeWorker", False)

        class Observer:
            def __init__(self, doc):
                self.doc = doc
                self.closing = False
                self.caught = None
                self.depths = []

            def slotRecomputedObject(self, obj):
                if not self.closing or obj.Document != self.doc:
                    return
                if self.caught is None:
                    self.caught = "nothing"
                    try:
                        FreeCAD.closeDocument(self.doc.Name)
                        self.caught = "returned"
                    except RuntimeError:
                        self.caught = "RuntimeError"
                    return
                if len(self.depths) < 3:
                    # The frames above this slot end, a few calls above the test
                    frame = sys._getframe()
                    n = 0
                    while frame is not None and n < 10000:
                        frame = frame.f_back
                        n += 1
                    self.depths.append(n)

        for i in range(5):
            self.doc.addObject("App::FeatureTest", "Feature%d" % i)
        self.doc.recompute()
        observer = Observer(self.doc)
        FreeCAD.addDocumentObserver(observer)
        name = self.doc.Name
        here = len(inspect.stack(0))
        try:
            params.SetBool("AsyncRecomputeWorker", True)
            FreeCADGui.setActiveDocument(name)
            for obj in self.doc.Objects:
                obj.touch()
            FreeCADGui.runCommand("Std_Refresh", 0)
            deadline = time.monotonic() + 10.0
            while not self.doc.Recomputing and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.doc.Recomputing)
            observer.closing = True
            # The slots run in this close's wait
            FreeCAD.closeDocument(name)
            self.doc = None
        finally:
            FreeCAD.removeDocumentObserver(observer)
            params.SetBool("AsyncRecomputeWorker", old_async)

        self.assertEqual(observer.caught, "RuntimeError")
        self.assertNotIn(name, FreeCAD.listDocuments())
        self.assertTrue(observer.depths)
        for depth in observer.depths:
            self.assertLess(depth, here + 20)

    def testSaveCommandDoesNotUseDeprecatedAPI(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.doc.saveAs(os.path.join(temp_dir, "TestDoc.FCStd"))
            self.doc.addObject("App::FeaturePython", "ModifiedObject")

            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always", DeprecationWarning)
                FreeCADGui.runCommand("Std_Save", 0)

            deprecations = [
                warning
                for warning in caught_warnings
                if issubclass(warning.category, DeprecationWarning)
            ]
            self.assertEqual(deprecations, [])

    def testRecoverySnapshotIncludesGuiDocument(self):
        self.doc.addObject("App::FeaturePython", "RecoveryGuiObject")

        self.assertTrue(FreeCAD.writeRecoverySnapshotToTransientDir(self.doc))

        self._assertRecoveryArchiveContains()

    def testRestoreWithoutGuiDocumentFitsViewAndRestoresVisibility(self):
        try:
            from pivy import coin  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"Coin bindings are unavailable: {exc}") from exc

        try:
            import Part  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"Part workbench objects are unavailable: {exc}") from exc

        visible_box = self.doc.addObject("Part::Box", "VisibleBox")
        hidden_cylinder = self.doc.addObject("Part::Cylinder", "HiddenCylinder")

        visible_box.Length = 25
        visible_box.Width = 20
        visible_box.Height = 15
        visible_box.Placement.Base = FreeCAD.Vector(80, 35, 45)
        visible_box.Visibility = True
        visible_box.ViewObject.Visibility = True

        hidden_cylinder.Radius = 5
        hidden_cylinder.Height = 20
        hidden_cylinder.Placement.Base = FreeCAD.Vector(120, 50, 55)
        hidden_cylinder.Visibility = False
        hidden_cylinder.ViewObject.Visibility = False

        self.doc.recompute()

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "with_gui_document.FCStd")
            target_path = os.path.join(temp_dir, "without_gui_document.FCStd")

            self.doc.saveAs(source_path)
            self._writeArchiveWithoutGuiDocument(source_path, target_path)

            FreeCAD.closeDocument(self.doc.Name)
            self.doc = None

            restored_doc = FreeCAD.openDocument(target_path)
            self.doc = restored_doc
            try:
                FreeCAD.setActiveDocument(restored_doc.Name)

                view = FreeCADGui.getDocument(restored_doc.Name).ActiveView
                self.assertIsNotNone(view)

                self.assertTrue(restored_doc.VisibleBox.ViewObject.Visibility)
                self.assertFalse(restored_doc.HiddenCylinder.Visibility)
                self.assertFalse(restored_doc.HiddenCylinder.ViewObject.Visibility)

                def cameraIsFitted():
                    position = view.getCameraNode().position.getValue().getValue()
                    return sum(abs(component) for component in position) > 10.0

                self.assertTrue(self._processEventsUntil(cameraIsFitted), view.getCamera())
            finally:
                if self.doc is not None and self.doc.Name in FreeCAD.listDocuments():
                    FreeCAD.closeDocument(self.doc.Name)
                self.doc = None

    def testAutoSaverFlushWritesRecoverySnapshot(self):
        obj = self.doc.addObject("App::FeaturePython", "AutoSaveGuiObject")
        obj.Label = "AutoSaveImmediate"
        self._removeRecoveryArchive()

        self._invokeAutoSaverFlush()

        self._assertRecoveryArchiveContains(expected_label="AutoSaveImmediate")

    def testAutoSaverRetriesWhenDocumentBecomesStable(self):
        obj = self.doc.addObject("App::FeaturePython", "AutoSaveBlockedObject")
        self._removeRecoveryArchive()

        self.doc.openTransaction("AutoSaveBlocked")
        obj.Label = "AutoSaveRetried"
        self._invokeAutoSaverFlush()

        self.assertFalse(os.path.exists(self._recoveryArchive()))

        self.doc.abortTransaction()

        self.assertTrue(self._processEventsUntil(lambda: os.path.exists(self._recoveryArchive())))
        self._assertRecoveryArchiveContains()

    def testAutoSaverStableSignalDoesNotBypassTimeout(self):
        obj = self.doc.addObject("App::FeaturePython", "AutoSaveStableObject")
        self._removeRecoveryArchive()

        self.doc.openTransaction("AutoSaveStable")
        obj.Label = "AutoSaveStillPending"
        self.doc.commitTransaction()

        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
        self.assertFalse(os.path.exists(self._recoveryArchive()))

    # FreeCAD-CH (ops#711): a recovery snapshot a moment after a change, not only on the timer, so
    # a crash before the timer's first pass (a new document's first minutes) or after a step loses
    # nothing. The timer is minutes long (15 by default, 5 in the Onshape pack): a snapshot within
    # seconds can only be the soon pass.
    def _autoSaveTimerMinutes(self):
        group = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document")
        if not group.GetBool("AutoSaveEnabled", True):
            raise unittest.SkipTest("auto-recovery is off in these preferences")
        minutes = group.GetInt("AutoSaveTimeout", 15)
        if minutes < 1:
            raise unittest.SkipTest("the auto-recovery timer is off in these preferences")
        return minutes

    def _recoveryLabel(self, label):
        archive = self._recoveryArchive()
        if not os.path.isfile(archive):
            return False
        try:
            with zipfile.ZipFile(archive) as recovery:
                return label in recovery.read("Document.xml").decode("utf-8", errors="replace")
        except (zipfile.BadZipFile, KeyError, OSError):
            return False

    def testAutoSaverWritesSoonAfterTheFirstChange(self):
        self._autoSaveTimerMinutes()
        obj = self.doc.addObject("App::FeaturePython", "AutoSaveSoonObject")
        obj.Label = "AutoSaveSoonFirst"
        self.assertTrue(FreeCADGui.getDocument(self.doc.Name).Modified)

        self.assertTrue(
            self._processEventsUntil(lambda: self._recoveryLabel("AutoSaveSoonFirst"), 10.0),
            "no recovery snapshot within 10 s of a new document's first change",
        )

    def testAutoSaverWritesSoonAfterALaterStep(self):
        self._autoSaveTimerMinutes()
        obj = self.doc.addObject("App::FeaturePython", "AutoSaveStepObject")
        obj.Label = "AutoSaveStepOne"
        self.assertTrue(
            self._processEventsUntil(lambda: self._recoveryLabel("AutoSaveStepOne"), 10.0)
        )

        self.doc.openTransaction("AutoSaveStep")
        obj.Label = "AutoSaveStepTwo"
        self.doc.commitTransaction()

        self.assertTrue(
            self._processEventsUntil(lambda: self._recoveryLabel("AutoSaveStepTwo"), 10.0),
            "the step after the first snapshot is not in a snapshot within 10 s",
        )

    def testAutoSaverSlowSoonPassWaitsForAPause(self):
        # A snapshot expected to block the window past AutoSaveSoonIdleAbove seconds waits until the
        # user has given no input for 3 s; 0 makes this small document's snapshot count as slow
        self._autoSaveTimerMinutes()
        group = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document")
        group.SetFloat("AutoSaveSoonIdleAbove", 0.0)
        try:
            obj = self.doc.addObject("App::FeaturePython", "AutoSaveBusyObject")
            obj.Label = "AutoSaveBusy"
            window = FreeCADGui.getMainWindow()
            typing_until = time.monotonic() + 6.0
            while time.monotonic() < typing_until:
                key = QtGui.QKeyEvent(
                    QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Shift, QtCore.Qt.KeyboardModifier.NoModifier
                )
                QtWidgets.QApplication.sendEvent(window, key)
                self._processEventsUntil(lambda: False, 0.3)
            self.assertFalse(self._recoveryLabel("AutoSaveBusy"), "a slow soon pass ran while the user typed")
            self.assertTrue(
                self._processEventsUntil(lambda: self._recoveryLabel("AutoSaveBusy"), 10.0),
                "no snapshot within 10 s of the pause",
            )
        finally:
            group.RemFloat("AutoSaveSoonIdleAbove")

    def testAutoSaverSoonPassSkipsAnUnmodifiedDocument(self):
        self._autoSaveTimerMinutes()
        self.doc.addObject("App::FeaturePython", "AutoSaveUnmodifiedObject")
        FreeCADGui.getDocument(self.doc.Name).Modified = False
        self._removeRecoveryArchive()

        # The soon pass comes 2 s after the change at the earliest: it finds nothing to recover
        self._processEventsUntil(lambda: False, 4.0)
        self.assertFalse(os.path.exists(self._recoveryArchive()))

    # FreeCAD-CH (ops#710): the active tab is kept in GuiDocument.xml, so an open and a recovery
    # come back on it
    def _secondStudio(self):
        tabs = getattr(FreeCADGui, "DocumentTabs", None)
        if not tabs or not tabs.isOn():
            raise unittest.SkipTest("the typed tabs are off (FreeCAD keymap)")
        FreeCAD.setActiveDocument(self.doc.Name)
        first = tabs.create(self.doc, "PartStudio")
        second = tabs.create(self.doc, "PartStudio")
        self.assertTrue(first and second and first != second, (first, second))
        done, refusal = tabs.switchTo(self.doc, first)
        self.assertTrue(done, refusal)
        done, refusal = tabs.switchTo(self.doc, second)
        self.assertTrue(done, refusal)
        FreeCADGui.updateGui()
        self.assertEqual(tabs.activeTab(self.doc), second)
        return tabs, second

    def _reopenOn(self, tabs, path, expected):
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = None
        self.doc = FreeCAD.openDocument(path)
        FreeCAD.setActiveDocument(self.doc.Name)
        reopened = self.doc
        self.assertTrue(
            self._processEventsUntil(lambda: tabs.activeTab(reopened) == expected, 5.0),
            f"reopened on {tabs.activeTab(reopened)!r}, saved on {expected!r}",
        )
        # Showing the saved tab is no change to the document
        self.assertFalse(FreeCADGui.getDocument(reopened.Name).Modified)

    def testActiveTabSurvivesSaveAndOpen(self):
        tabs, second = self._secondStudio()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "active_tab.FCStd")
            self.doc.saveAs(path)
            with zipfile.ZipFile(path) as saved:
                gui_xml = saved.read("GuiDocument.xml").decode("utf-8", errors="replace")
            self.assertIn(f'<ActiveTab name="{second}"/>', gui_xml)
            self._reopenOn(tabs, path, second)
            FreeCAD.closeDocument(self.doc.Name)
            self.doc = None

    def testActiveTabSurvivesRecovery(self):
        tabs, second = self._secondStudio()
        self.assertTrue(FreeCAD.writeRecoverySnapshotToTransientDir(self.doc))
        with tempfile.TemporaryDirectory() as temp_dir:
            # The Document Recovery dialog opens the snapshot as a file (openDocuments())
            path = os.path.join(temp_dir, "recovered.FCStd")
            with open(self._recoveryArchive(), "rb") as source, open(path, "wb") as target:
                target.write(source.read())
            self._reopenOn(tabs, path, second)
            FreeCAD.closeDocument(self.doc.Name)
            self.doc = None

    def testAutoSaverCoalescesBlockedFlushesToLatestCommittedState(self):
        obj = self.doc.addObject("App::FeaturePython", "AutoSaveChurnObject")
        self._removeRecoveryArchive()

        self.doc.openTransaction("AutoSaveChurn")
        for index in range(8):
            obj.Label = f"AutoSaveBurst{index}"
            self._invokeAutoSaverFlush()

        self.assertFalse(os.path.exists(self._recoveryArchive()))

        self.doc.commitTransaction()

        self.assertTrue(self._processEventsUntil(lambda: os.path.exists(self._recoveryArchive())))
        self._assertRecoveryArchiveContains(expected_label="AutoSaveBurst7")
