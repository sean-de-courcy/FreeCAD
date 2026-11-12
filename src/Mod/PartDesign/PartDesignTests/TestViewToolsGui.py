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

"""The view tools of Onshape's View menu (FreeCAD-CH, ops#640): the section view, named views,
display styles and the camera.

Designed model: one 20 x 20 x 20 box at the origin. The oracles are data: what the view reports
(section plane, camera string, camera type), what the document stores (named views), the menu
entries and the commands' checked state. What the screen shows (the cap, the dashed hidden
edges) is not asserted here."""

import os
import shutil
import tempfile
import time
import unittest
import zipfile

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


def menuActions(menuTitle):
    """The objectNames of the actions of the menu-bar menu with this title, in order."""
    for menu in Gui.getMainWindow().menuBar().findChildren(QtWidgets.QMenu):
        if menu.title().replace("&", "") == menuTitle:
            return [a.objectName() for a in menu.actions()]
    return None


class ViewToolsCase(unittest.TestCase):
    """A document with a box and its 3D view, active."""

    docName = "ViewToolsGui"

    @classmethod
    def setUpClass(cls):
        import PartGui  # noqa: F401

        Gui.activateWorkbench("PartDesignWorkbench")
        pump()

    def setUp(self):
        self.doc = App.newDocument(self.docName)
        box = self.doc.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 20
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        windows = [
            w
            for w in mdi.subWindowList()
            if w.widget().metaObject().className() == "Gui::View3DInventor"
        ]
        self.assertTrue(windows, "the document's 3D view")
        mdi.setActiveSubWindow(windows[-1])
        self.viewWindows = windows  # held: PySide drops a view's wrapper with its sub-window's
        self.view = Gui.ActiveDocument.ActiveView
        pump()

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        pump(0.1)


class TestSectionViewGui(ViewToolsCase):
    """Std_SectionView: a view-only section (ops#640, view tools 1)."""

    docName = "SectionViewGui"

    def tearDown(self):
        self.view.clearSectionView()
        Gui.runCommand("Std_SectionView", 0)
        pump(0.1)
        super().tearDown()

    def assertVec(self, got, want):
        self.assertEqual(len(got), 3)
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=4)

    def testNoSectionAtFirst(self):
        self.assertIsNone(self.view.sectionView())

    def testSetQueryAndClear(self):
        self.view.setSectionView(origin=(1, 2, 3), normal=(0, 0, 2))
        origin, normal = self.view.sectionView()
        self.assertVec(origin, (1, 2, 3))
        self.assertVec(normal, (0, 0, 1))  # the normal comes back unit length
        self.view.setSectionView(origin=(0, 5, 0), normal=(App.Vector(0, -1, 0)))
        origin, normal = self.view.sectionView()
        self.assertVec(origin, (0, 5, 0))
        self.assertVec(normal, (0, -1, 0))
        self.view.clearSectionView()
        self.assertIsNone(self.view.sectionView())
        self.view.clearSectionView()  # nothing to clear is fine

    def testNormalNeedsALength(self):
        with self.assertRaises(ValueError):
            self.view.setSectionView(origin=(0, 0, 0), normal=(0, 0, 0))
        self.assertIsNone(self.view.sectionView())

    def testSectionIsViewOnly(self):
        """Nothing goes into the document: no object, no touched flag."""
        count = len(self.doc.Objects)
        self.doc.recompute()
        self.assertEqual(self.doc.getObject("Box").State.count("Touched"), 0)
        self.view.setSectionView(origin=(0, 0, 10), normal=(0, 0, 1))
        pump()
        self.assertEqual(len(self.doc.Objects), count)
        self.assertEqual(self.doc.getObject("Box").State.count("Touched"), 0)

    def testCommandIsRegisteredAndCheckable(self):
        cmd = Gui.Command.get("Std_SectionView")
        self.assertIsNotNone(cmd)
        actions = cmd.getAction()
        self.assertTrue(actions)
        self.assertTrue(actions[0].isCheckable())

    def testCommandTogglesTheSectionAndItsCheck(self):
        action = Gui.Command.get("Std_SectionView").getAction()[0]
        Gui.runCommand("Std_SectionView", 1)
        pump()
        section = self.view.sectionView()
        self.assertIsNotNone(section, "the command starts a section")
        self.assertVec(section[0], (0, 0, 0))  # through the origin
        self.assertVec(section[1], (0, -1, 0))  # the front plane, the viewer's side is cut
        self.assertTrue(action.isChecked())
        Gui.runCommand("Std_SectionView", 0)
        pump()
        self.assertIsNone(self.view.sectionView())
        self.assertFalse(action.isChecked())

    def testCheckFollowsASectionSetFromPython(self):
        action = Gui.Command.get("Std_SectionView").getAction()[0]
        self.view.setSectionView(origin=(0, 0, 5), normal=(1, 0, 0))
        Gui.runCommand("Std_SectionView", 1)  # the panel keeps the section that is there
        pump()
        origin, normal = self.view.sectionView()
        self.assertVec(origin, (0, 0, 5))
        self.assertVec(normal, (1, 0, 0))
        self.assertTrue(action.isChecked())

    def testSectionViewIsInTheViewMenu(self):
        entries = menuActions("View")
        self.assertIsNotNone(entries, "the View menu")
        self.assertIn("Std_SectionView", entries)
        self.assertIn("Std_ToggleClipPlane", entries)  # the clipping dialog stays


class TestNamedViewsGui(ViewToolsCase):
    """Named views: a camera under a name, in the document (ops#640, view tools 2)."""

    docName = "NamedViewsGui"

    def setUp(self):
        super().setUp()
        self.view.setAnimationEnabled(False)
        self.guiDoc = Gui.getDocument(self.doc.Name)
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        self.view.setAnimationEnabled(True)
        super().tearDown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def twoViews(self):
        """Saves "Top" and "Front"; returns the camera strings of the two."""
        self.view.viewTop()
        top = self.view.getCamera()
        self.guiDoc.saveNamedView("Top")
        self.view.viewFront()
        front = self.view.getCamera()
        self.guiDoc.saveNamedView("Front")
        self.assertNotEqual(top, front)
        return top, front

    def testNoViewsAtFirst(self):
        self.assertEqual(self.guiDoc.namedViews(), [])

    def testSaveListRestore(self):
        top, front = self.twoViews()
        self.assertEqual(self.guiDoc.namedViews(), ["Top", "Front"])
        self.guiDoc.restoreNamedView("Top")
        self.assertEqual(self.view.getCamera(), top)
        self.guiDoc.restoreNamedView("Front")
        self.assertEqual(self.view.getCamera(), front)

    def testSameNameReplaces(self):
        self.twoViews()
        self.view.viewRear()
        rear = self.view.getCamera()
        self.guiDoc.saveNamedView("Top")
        self.assertEqual(self.guiDoc.namedViews(), ["Top", "Front"])  # same place, no new entry
        self.view.viewFront()
        self.guiDoc.restoreNamedView("Top")
        self.assertEqual(self.view.getCamera(), rear)

    def testRename(self):
        top, front = self.twoViews()
        self.guiDoc.renameNamedView("Top", "Roof")
        self.assertEqual(self.guiDoc.namedViews(), ["Roof", "Front"])
        self.guiDoc.restoreNamedView("Roof")
        self.assertEqual(self.view.getCamera(), top)
        with self.assertRaises(ValueError):
            self.guiDoc.restoreNamedView("Top")
        with self.assertRaises(ValueError):
            self.guiDoc.renameNamedView("Roof", "Front")  # the name is taken
        with self.assertRaises(ValueError):
            self.guiDoc.renameNamedView("Nothing", "Other")
        self.assertEqual(self.guiDoc.namedViews(), ["Roof", "Front"])

    def testDelete(self):
        self.twoViews()
        self.guiDoc.deleteNamedView("Top")
        self.assertEqual(self.guiDoc.namedViews(), ["Front"])
        with self.assertRaises(ValueError):
            self.guiDoc.deleteNamedView("Top")
        with self.assertRaises(ValueError):
            self.guiDoc.restoreNamedView("Top")

    def testEmptyNameIsRefused(self):
        with self.assertRaises(RuntimeError):
            self.guiDoc.saveNamedView("")
        self.assertEqual(self.guiDoc.namedViews(), [])

    def testViewsBelongToTheirDocument(self):
        self.twoViews()
        other = App.newDocument("NamedViewsOther")
        try:
            self.assertEqual(Gui.getDocument(other.Name).namedViews(), [])
        finally:
            App.closeDocument(other.Name)
        Gui.ActiveDocument = self.guiDoc
        self.assertEqual(self.guiDoc.namedViews(), ["Top", "Front"])

    def testViewsSurviveSaveCloseAndReopen(self):
        top, front = self.twoViews()
        path = os.path.join(self.tmp, "named_views.FCStd")
        self.doc.saveAs(path)
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("GuiDocument.xml").decode()
        self.assertIn("<NamedViews", xml)
        self.assertIn('name="Top"', xml)
        App.closeDocument(self.doc.Name)
        pump()
        self.doc = App.openDocument(path)
        pump()
        guiDoc = Gui.getDocument(self.doc.Name)
        self.assertEqual(guiDoc.namedViews(), ["Top", "Front"])
        Gui.ActiveDocument = guiDoc
        view = guiDoc.ActiveView
        view.setAnimationEnabled(False)
        guiDoc.restoreNamedView("Front")
        self.assertEqual(view.getCamera(), front)
        guiDoc.restoreNamedView("Top")
        self.assertEqual(view.getCamera(), top)
        self.view = view
        self.guiDoc = guiDoc

    def testDocumentWithoutViewsWritesNoElement(self):
        path = os.path.join(self.tmp, "no_views.FCStd")
        self.doc.saveAs(path)
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("GuiDocument.xml").decode()
        self.assertNotIn("NamedViews", xml)

    def testSavingAViewTouchesTheDocument(self):
        self.doc.saveAs(os.path.join(self.tmp, "touched.FCStd"))
        self.guiDoc.Modified = False
        self.guiDoc.saveNamedView("Mark")
        self.assertTrue(self.guiDoc.Modified)

    def fillDialog(self, text):
        """Answers the input dialog the next command opens."""

        def answer():
            dialog = QtWidgets.QApplication.activeModalWidget()
            if isinstance(dialog, QtWidgets.QInputDialog):
                dialog.setTextValue(text)
                dialog.accept()
            else:
                QtCore.QTimer.singleShot(50, answer)

        QtCore.QTimer.singleShot(100, answer)

    def testSaveCommandAsksTheNameAndSaves(self):
        self.view.viewTop()
        top = self.view.getCamera()
        self.fillDialog("Asked")
        Gui.runCommand("Std_SaveNamedView")
        pump()
        self.assertEqual(self.guiDoc.namedViews(), ["Asked"])
        self.view.viewFront()
        self.guiDoc.restoreNamedView("Asked")
        self.assertEqual(self.view.getCamera(), top)

    def viewMenu(self):
        for menu in Gui.getMainWindow().menuBar().findChildren(QtWidgets.QMenu):
            if menu.title().replace("&", "") == "View":
                return menu
        self.fail("the View menu")

    def namedViewsMenu(self):
        for menu in self.viewMenu().findChildren(QtWidgets.QMenu):
            if menu.title().replace("&", "") == "Named views":
                return menu
        self.fail("the Named views menu in the View menu")

    def testMenusAreInTheViewMenu(self):
        entries = menuActions("View")
        self.assertIn("Std_SaveNamedView", entries)
        self.namedViewsMenu()

    def testMenuListsTheDocumentsViewsEachTimeItOpens(self):
        menu = self.namedViewsMenu()

        def shown():
            menu.aboutToShow.emit()
            return [
                a.text().replace("&", "")
                for a in menu.actions()
                if a.isVisible() and not a.isSeparator()
            ]

        self.assertEqual(shown(), ["Rename view...", "Delete view..."])
        self.assertFalse(menu.actions()[0].isEnabled())
        self.twoViews()
        entries = shown()
        self.assertEqual(entries[2:], ["Top", "Front"])
        self.assertTrue(menu.actions()[0].isEnabled())
        self.guiDoc.deleteNamedView("Top")
        self.assertEqual(shown()[2:], ["Front"])

    def testMenuEntryRestoresTheView(self):
        top, front = self.twoViews()
        menu = self.namedViewsMenu()
        menu.aboutToShow.emit()
        entry = [a for a in menu.actions() if a.isVisible() and a.text() == "Top"]
        self.assertEqual(len(entry), 1)
        entry[0].trigger()
        pump()
        self.assertEqual(self.view.getCamera(), top)


PART_VIEW = "User parameter:BaseApp/Preferences/Mod/Part/View"


class TestDisplayStylesGui(ViewToolsCase):
    """Onshape's display menu: shaded, shaded with edges, hidden edges visible, wireframe, and
    the tangent edges toggle (ops#640, view tools 3)."""

    docName = "DisplayStylesGui"

    # the styles in the order of the menu: (override mode of the viewer, hidden edges shown)
    STYLES = [
        ("Shaded", False),
        ("Flat Lines", False),
        ("Flat Lines", True),
        ("Wireframe", False),
    ]

    def setUp(self):
        super().setUp()
        params = App.ParamGet(PART_VIEW)
        self.saved = (params.GetBool("ShowHiddenEdges", False), params.GetBool("ShowTangentEdges", True))
        params.RemBool("ShowHiddenEdges")
        params.RemBool("ShowTangentEdges")
        self.viewer = self.view.getViewer()

    def tearDown(self):
        # back to shaded with edges, through the action so the menu's check follows
        Gui.Command.get("Std_DisplayStyle").getAction()[1].trigger()
        pump(0.1)
        params = App.ParamGet(PART_VIEW)
        params.SetBool("ShowHiddenEdges", self.saved[0])
        params.SetBool("ShowTangentEdges", self.saved[1])
        super().tearDown()

    def displayMenu(self):
        for menu in Gui.getMainWindow().menuBar().findChildren(QtWidgets.QMenu):
            if menu.title().replace("&", "") == "View":
                for sub in menu.findChildren(QtWidgets.QMenu):
                    if sub.title().replace("&", "") == "Display":
                        return sub
        self.fail("the Display menu in the View menu")

    def testDisplayMenuListsTheFourStyles(self):
        entries = [a.text().replace("&", "") for a in self.displayMenu().actions()]
        self.assertEqual(
            entries, ["Shaded", "Shaded with edges", "Hidden edges visible", "Wireframe"]
        )
        names = [a.objectName() for a in self.displayMenu().actions()]
        self.assertEqual(
            names,
            [
                "Std_DisplayShaded",
                "Std_DisplayShadedEdges",
                "Std_DisplayHiddenEdges",
                "Std_DisplayWireframe",
            ],
        )

    def testTangentEdgesIsInTheViewMenu(self):
        entries = menuActions("View")
        self.assertIn("Std_TangentEdges", entries)
        self.assertIn("Std_DrawStyle", entries)  # the draw styles stay

    def testShadedWithEdgesIsTheDefault(self):
        actions = Gui.Command.get("Std_DisplayStyle").getAction()
        self.assertEqual(len(actions), 4)
        self.assertEqual([a.isChecked() for a in actions], [False, True, False, False])
        self.assertTrue(all(a.isCheckable() for a in actions))

    def testChoosingEachStyleSetsTheViewersMode(self):
        for index, (mode, hidden) in enumerate(self.STYLES):
            Gui.runCommand("Std_DisplayStyle", index)
            pump(0.1)
            self.assertEqual(self.viewer.getOverrideMode(), mode, f"style {index}")
            self.assertEqual(
                App.ParamGet(PART_VIEW).GetBool("ShowHiddenEdges", False), hidden, f"style {index}"
            )

    def testMenuEntriesRunTheStyles(self):
        """Through the menu's actions, as a click does: the entry checks, and the mode follows."""
        actions = Gui.Command.get("Std_DisplayStyle").getAction()
        for index, (mode, hidden) in enumerate(self.STYLES):
            actions[index].trigger()
            pump(0.1)
            self.assertEqual(self.viewer.getOverrideMode(), mode, f"style {index}")
            self.assertEqual(
                [a.isChecked() for a in actions],
                [i == index for i in range(4)],
                f"style {index}",
            )

    def testShapesTakeTheModeOfTheStyle(self):
        """The box's view provider shows the mode the style names, hidden edges or not."""
        box = self.doc.getObject("Box")
        self.assertIsNotNone(box.ViewObject)
        Gui.runCommand("Std_DisplayStyle", 3)
        pump(0.1)
        self.assertEqual(box.ViewObject.DisplayMode, "Flat Lines")  # the property is the shape's
        self.assertEqual(self.viewer.getOverrideMode(), "Wireframe")
        Gui.runCommand("Std_DisplayStyle", 0)
        pump(0.1)
        self.assertEqual(self.viewer.getOverrideMode(), "Shaded")

    def testTangentEdgesAreOnAtFirst(self):
        self.assertTrue(App.ParamGet(PART_VIEW).GetBool("ShowTangentEdges", True))

    def testTangentEdgesToggleChangesTheSetting(self):
        cmd = Gui.Command.get("Std_TangentEdges")
        action = cmd.getAction()[0]
        self.assertTrue(action.isCheckable())
        Gui.runCommand("Std_TangentEdges", 0)
        pump(0.1)
        self.assertFalse(App.ParamGet(PART_VIEW).GetBool("ShowTangentEdges", True))
        Gui.runCommand("Std_TangentEdges", 1)
        pump(0.1)
        self.assertTrue(App.ParamGet(PART_VIEW).GetBool("ShowTangentEdges", True))

    def edgeIndexCount(self, viewObject):
        """The number of indices of the edge line set of a Part view provider, or None where
        the scene graph can't be read from Python."""
        try:
            from pivy import coin

            search = coin.SoSearchAction()
            search.setName("Edge")
            search.setInterest(coin.SoSearchAction.FIRST)
            search.apply(viewObject.RootNode)
            path = search.getPath()
            if path is None:
                return None
            edge = path.getTail()
            lines = edge.getChild(edge.getNumChildren() - 1)
            return lines.getField("coordIndex").getNum()
        except Exception:
            return None

    def testTangentEdgesOffTakesTheLinesOfTheTangentEdges(self):
        """A box with one rounded edge has two tangent edges (where the round meets the flat
        faces): with the tangent edges off they get no line, the others stay."""
        import Part

        solid = Part.makeBox(20, 20, 20)
        solid = solid.makeFillet(3, [solid.Edges[0]])
        feature = self.doc.addObject("Part::Feature", "Rounded")
        feature.Shape = solid
        self.doc.recompute()
        pump()
        with_tangent = self.edgeIndexCount(feature.ViewObject)
        if with_tangent is None:
            self.skipTest("the scene graph can't be read from Python")
        Gui.runCommand("Std_TangentEdges", 0)
        pump(0.3)
        without = self.edgeIndexCount(feature.ViewObject)
        self.assertIsNotNone(without)
        self.assertLess(without, with_tangent)
        Gui.runCommand("Std_TangentEdges", 1)
        pump(0.3)
        self.assertEqual(self.edgeIndexCount(feature.ViewObject), with_tangent)

    def testBoxHasNoTangentEdgesToLose(self):
        """A plain box's edges are all creases: the toggle changes nothing for it."""
        box = self.doc.getObject("Box")
        before = self.edgeIndexCount(box.ViewObject)
        if before is None:
            self.skipTest("the scene graph can't be read from Python")
        Gui.runCommand("Std_TangentEdges", 0)
        pump(0.3)
        self.assertEqual(self.edgeIndexCount(box.ViewObject), before)

    def testDrawStylesStayWithTheirSevenEntries(self):
        self.assertEqual(len(Gui.Command.get("Std_DrawStyle").getAction()), 7)


GUI_VIEW = "User parameter:BaseApp/Preferences/View"


class TestCameraMenuGui(ViewToolsCase):
    """Perspective is the default camera of a new view, and the camera entries and the zoom to a
    window make a Camera group of the View menu (ops#640, view tools 4)."""

    docName = "CameraMenuGui"

    def setUp(self):
        super().setUp()
        self.saved = App.ParamGet(GUI_VIEW).GetString("DefaultCameraType", "")
        self.extra = []

    def tearDown(self):
        for name in self.extra:
            App.closeDocument(name)
        params = App.ParamGet(GUI_VIEW)
        if self.saved:
            params.SetString("DefaultCameraType", self.saved)
        else:
            params.RemString("DefaultCameraType")
        pump(0.1)
        super().tearDown()

    def newViewCameraType(self, name):
        """The camera type of the 3D view a new document gets."""
        doc = App.newDocument(name)
        self.extra.append(doc.Name)
        pump()
        guiDoc = Gui.getDocument(doc.Name)
        Gui.ActiveDocument = guiDoc
        pump()
        return guiDoc.ActiveView.getCameraType()

    def cameraMenu(self):
        for menu in Gui.getMainWindow().menuBar().findChildren(QtWidgets.QMenu):
            if menu.title().replace("&", "") == "View":
                for sub in menu.findChildren(QtWidgets.QMenu):
                    if sub.title().replace("&", "") == "Camera":
                        return sub
        self.fail("the Camera menu in the View menu")

    def testNewViewIsPerspectiveWithoutAPreference(self):
        App.ParamGet(GUI_VIEW).RemString("DefaultCameraType")
        self.assertEqual(self.newViewCameraType("CameraDefault"), "Perspective")

    def testNewViewTakesThePreference(self):
        params = App.ParamGet(GUI_VIEW)
        params.SetString("DefaultCameraType", "Orthographic")
        self.assertEqual(self.newViewCameraType("CameraOrtho"), "Orthographic")
        params.SetString("DefaultCameraType", "Perspective")
        self.assertEqual(self.newViewCameraType("CameraPersp"), "Perspective")

    def testChangingThePreferenceLeavesTheOpenViewAlone(self):
        before = self.view.getCameraType()
        other = "Orthographic" if before == "Perspective" else "Perspective"
        App.ParamGet(GUI_VIEW).SetString("DefaultCameraType", other)
        pump(0.1)
        self.assertEqual(self.view.getCameraType(), before)

    def testCameraMenuHasTheCameraEntriesAndTheZoomToWindow(self):
        names = [a.objectName() for a in self.cameraMenu().actions() if not a.isSeparator()]
        self.assertEqual(names, ["Std_OrthographicCamera", "Std_PerspectiveCamera", "Std_ViewBoxZoom"])

    def testCameraEntriesLeaveTheViewMenuTopLevel(self):
        entries = menuActions("View")
        self.assertNotIn("Std_OrthographicCamera", entries)
        self.assertNotIn("Std_PerspectiveCamera", entries)

    def testZoomToWindowIsNamedAsOnshapeNamesIt(self):
        action = Gui.Command.get("Std_ViewBoxZoom").getAction()[0]
        self.assertEqual(action.text().replace("&", ""), "Zoom to window")

    def testCameraEntriesSwitchTheType(self):
        Gui.runCommand("Std_OrthographicCamera", 1)
        pump(0.1)
        self.assertEqual(self.view.getCameraType(), "Orthographic")
        Gui.runCommand("Std_PerspectiveCamera", 1)
        pump(0.1)
        self.assertEqual(self.view.getCameraType(), "Perspective")


if __name__ == "__main__":
    unittest.main()
