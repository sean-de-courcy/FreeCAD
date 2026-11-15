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


def menuBarMenu(menuTitle):
    """The menu bar's current menu with this title: the menus of an earlier workbench stay
    children of the menu bar after it is cleared, and may come first in findChildren, so the menu
    must be one whose action is in the bar. Not QAction.menu(): with it the View menu's submenus
    were found deleted ("Internal C++ object already deleted") a line later."""
    bar = Gui.getMainWindow().menuBar()
    current = bar.actions()
    for menu in bar.findChildren(QtWidgets.QMenu):
        if menu.title().replace("&", "") == menuTitle and menu.menuAction() in current:
            return menu
    return None


def subMenu(menu, title):
    """The submenu of `menu` with this title, at any depth, or None."""
    if menu is None:
        return None
    for sub in menu.findChildren(QtWidgets.QMenu):
        if sub.title().replace("&", "") == title:
            return sub
    return None


def menuActions(menuTitle):
    """The objectNames of the actions of the menu-bar menu with this title, in order."""
    menu = menuBarMenu(menuTitle)
    return None if menu is None else [a.objectName() for a in menu.actions()]


class ViewToolsCase(unittest.TestCase):
    """A document with a box and its 3D view, active."""

    docName = "ViewToolsGui"

    @classmethod
    def setUpClass(cls):
        import PartGui  # noqa: F401

        Gui.activateWorkbench("PartDesignWorkbench")
        pump()

    def setUp(self):
        self.documentsBefore = set(App.listDocuments())
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
        # every document the test opened, even one a failed test left behind: a leaked 3D view
        # breaks the later units that count the views
        for name in list(App.listDocuments()):
            if name not in self.documentsBefore:
                App.closeDocument(name)
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

    def testClickOnTheCapPicksNothing(self):
        """The 20 mm box cut at y = 10, the near half cut away (the normal points to the cut
        side, -y). A ray along +y through the box's middle meets the plane inside the box, where
        the cap is drawn: it picks nothing, not the far wall (y = 20) behind the cap (review
        prviewtools-r1 T1)."""
        self.view.setSectionView(origin=(0, 10, 0), normal=(0, -1, 0))
        pump()
        start, direction = App.Vector(10, -50, 10), App.Vector(0, 1, 0)
        self.assertIsNone(self.view.getObjectInfoRay(start, direction))
        self.view.clearSectionView()
        pump()
        info = self.view.getObjectInfoRay(start, direction)
        self.assertIsNotNone(info, "without the section the ray picks the box")
        self.assertAlmostEqual(info["PickedPoint"].y, 0.0, places=3)  # the near wall

    def testRayCrossingThePlaneOutsideTheSolidStillPicks(self):
        """The same cut. A ray that crosses y = 10 at x = 24, beside the box, then meets the
        face x = 20 at y = 15 (direction (-0.8, 1, 0) from (40, -10, 10)): that face is seen
        and picked."""
        self.view.setSectionView(origin=(0, 10, 0), normal=(0, -1, 0))
        pump()
        info = self.view.getObjectInfoRay(App.Vector(40, -10, 10), App.Vector(-0.8, 1, 0))
        self.assertIsNotNone(info, "the face x = 20 is seen")
        self.assertEqual(info["Object"], "Box")
        self.assertAlmostEqual(info["PickedPoint"].x, 20.0, places=3)
        self.assertAlmostEqual(info["PickedPoint"].y, 15.0, places=3)

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
        try:
            self.view.setAnimationEnabled(True)
        except RuntimeError:
            pass  # the view went with its document (a reopen that failed half way)
        super().tearDown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assertCamera(self, view, want):
        """The view's camera is the camera string `want`. Both are compared as setCamera leaves
        them: getCamera writes only the fields that are set, and a restore sets them all."""
        got = view.getCamera()
        view.setCamera(want)
        self.assertEqual(got, view.getCamera())

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
        self.assertCamera(self.view, top)
        self.guiDoc.restoreNamedView("Front")
        self.assertCamera(self.view, front)

    def testSameNameReplaces(self):
        self.twoViews()
        self.view.viewRear()
        rear = self.view.getCamera()
        self.guiDoc.saveNamedView("Top")
        self.assertEqual(self.guiDoc.namedViews(), ["Top", "Front"])  # same place, no new entry
        self.view.viewFront()
        self.guiDoc.restoreNamedView("Top")
        self.assertCamera(self.view, rear)

    def testRename(self):
        top, front = self.twoViews()
        self.guiDoc.renameNamedView("Top", "Roof")
        self.assertEqual(self.guiDoc.namedViews(), ["Roof", "Front"])
        self.guiDoc.restoreNamedView("Roof")
        self.assertCamera(self.view, top)
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
        Gui.ActiveDocument = guiDoc
        view = guiDoc.ActiveView
        self.view, self.guiDoc = view, guiDoc  # for tearDown, before anything can fail
        self.assertEqual(guiDoc.namedViews(), ["Top", "Front"])
        view.setAnimationEnabled(False)
        # Top first: the reopened view stands where it was saved, at Front
        guiDoc.restoreNamedView("Top")
        self.assertCamera(view, top)
        guiDoc.restoreNamedView("Front")
        self.assertCamera(view, front)

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
        self.assertCamera(self.view, top)

    def namedViewsMenu(self):
        menu = subMenu(menuBarMenu("View"), "Named views")
        if menu is None:
            self.fail("the Named views menu in the View menu")
        return menu

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
        self.assertCamera(self.view, top)


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
        menu = subMenu(menuBarMenu("View"), "Display")
        if menu is None:
            self.fail("the Display menu in the View menu")
        return menu

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
        # the draw styles stay: a drop-down submenu without an object name, found by its title
        self.assertIsNotNone(subMenu(menuBarMenu("View"), "Draw Style"))

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
    """A new view is orthographic, as Onshape's (its "Perspective view" is a toggle that starts off),
    through FreeCAD's own preference View/Orthographic; the camera entries and the zoom to a window
    make a Camera group of the View menu (ops#640, view tools 4)."""

    docName = "CameraMenuGui"

    def setUp(self):
        super().setUp()
        params = App.ParamGet(GUI_VIEW)
        self.hadPreference = "Orthographic" in params.GetBools()
        self.saved = params.GetBool("Orthographic", True)
        self.extra = []

    def tearDown(self):
        for name in self.extra:
            App.closeDocument(name)
        params = App.ParamGet(GUI_VIEW)
        if self.hadPreference:
            params.SetBool("Orthographic", self.saved)
        else:
            params.RemBool("Orthographic")
        self.view.setCameraType("Orthographic")
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
        menu = subMenu(menuBarMenu("View"), "Camera")
        if menu is None:
            self.fail("the Camera menu in the View menu")
        return menu

    def testNewViewIsOrthographicWithoutAPreference(self):
        App.ParamGet(GUI_VIEW).RemBool("Orthographic")
        self.assertEqual(self.newViewCameraType("CameraDefault"), "Orthographic")

    def testNewViewTakesThePreference(self):
        params = App.ParamGet(GUI_VIEW)
        params.SetBool("Orthographic", False)
        self.assertEqual(self.newViewCameraType("CameraPersp"), "Perspective")
        params.SetBool("Orthographic", True)
        self.assertEqual(self.newViewCameraType("CameraOrtho"), "Orthographic")

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
