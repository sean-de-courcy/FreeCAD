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

"""The fork's default keymap, Onshape's shortcuts (FreeCAD-CH, ops#194 PR A).

The keymap is a table of default keys applied when a command registers, so a key the user set
keeps its value and Reset goes to the table's key. The preference `General/Keymap` = `FreeCAD`
gives upstream's keys back. On a tie between two enabled commands, a command for the edit in
progress wins (Shift+F in a sketch is the sketch fillet, not PartDesign's). Shift+E / Shift+W in
a sketch close the sketch and pad / revolve it, as Onshape's extrude and revolve do. See
notes/onshape-shortcuts.md.

Designed model: a Body with a 10 x 10 rectangle sketch on XY at x 5..15, y 0..10 (so a revolution
about the sketch's V axis is valid). The oracles: the command a key runs (its action's triggered
signal), the view direction, the features a key makes, and the shortcuts the commands carry.

Keys go to the main window's QWindow, through the shortcut map as a user's key does
(notes/build.md, "Keys and shortcuts in GUI tests"). Off screen, Qt maps a synthesized Shift+1 by
its key code only, so the Shift+digit check doesn't prove a real keyboard's `!` maps to Shift+1."""

import contextlib
import os
import tempfile
import time
import unittest

import shiboken6

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtCore, QtGui, QtWidgets
from PySide6 import QtTest

KEYMAP = "User parameter:BaseApp/Preferences/General"  # the preference Keymap
SHORTCUTS = "User parameter:BaseApp/Preferences/Shortcut"

# The keys the fork's keymap sets (notes/onshape-shortcuts.md section 2, PLAN.md decision 27);
# "" for a key it takes away. Written out here as the oracle, independently of the C++ table.
ONSHAPE = {
    # General and Part Studio
    "Std_Measure": "[",
    "PartDesign_NewSketch": "Shift+S",
    "PartDesign_Pad": "Shift+E",
    "PartDesign_Revolution": "Shift+W",
    "PartDesign_Fillet": "Shift+F",
    "Std_BoxElementSelection": "",
    "Std_FreezeViews": "",
    "Std_ClarifySelection": "",
    # 3D view
    "Std_ViewFront": "Shift+1",
    "Std_ViewRear": "Shift+2",
    "Std_ViewLeft": "Shift+3",
    "Std_ViewRight": "Shift+4",
    "Std_ViewTop": "Shift+5",
    "Std_ViewBottom": "Shift+6",
    "Std_ViewIsometric": "Shift+7",
    "Std_ViewFitAll": "F",
    "Std_ViewZoomOut": "Z",
    "Std_ViewZoomIn": "Shift+Z",
    "Std_ViewBoxZoom": "W",
    "Std_HideSelection": "Y",
    "Std_ShowObjects": "Shift+Y",
    "Std_ToggleTransparency": "Shift+T",
    "Std_ToggleClipPlane": "Shift+X",
    "Std_ViewFitSelection": "",
    "Std_OrthographicCamera": "",
    "Std_PerspectiveCamera": "",
    "Std_ViewDock": "",
    "Std_ViewUndock": "",
    "Std_AxisCross": "",
    "Std_TreeSelection": "",
    "Std_TreeSyncView": "",
    "Std_TreeSyncSelection": "",
    "Std_TreeSyncPlacement": "",
    "Std_TreePreSelection": "",
    "Std_TreeRecordSelection": "",
    "Std_TreeDrag": "",
    "Std_DockOverlayMouseTransparent": "",
    # The Part selection filters move off their chords (C, E, X and F are Onshape keys)
    "Part_VertexSelection": "Shift+Alt+V",
    "Part_EdgeSelection": "Shift+Alt+E",
    "Part_FaceSelection": "Shift+Alt+F",
    "Part_RemoveSelectionGate": "Shift+Alt+C",
    # Sketch tools
    "Sketcher_CreatePolyline": "L",
    "Sketcher_Create3PointArc": "A",
    "Sketcher_CreateCircle": "C",
    "Sketcher_CreateRectangle_Center": "R",
    "Sketcher_CreateRectangle": "G",
    "Sketcher_CreatePoint": "Shift+S",
    "Sketcher_CreateFillet": "Shift+F",
    "Sketcher_Offset": "O",
    "Sketcher_Extend": "X",
    "Sketcher_Trimming": "M",  # the tools' own M / U / R are Ctrl+M / U / R (PR D)
    "Sketcher_Projection": "U",
    "Sketcher_Intersection": "Shift+G",
    "Sketcher_ToggleConstruction": "Q",
    "Sketcher_ViewSketch": "N",
    "Sketcher_ViewSection": "",
    # Sketch constraints
    "Sketcher_Dimension": "D",
    "Sketcher_ConstrainCoincidentUnified": "I",
    "Sketcher_ConstrainEqual": "E",
    "Sketcher_ConstrainHorizontal": "H",
    "Sketcher_ConstrainVertical": "V",
    "Sketcher_ConstrainParallel": "B",
    "Sketcher_ConstrainPerpendicular": "Shift+L",
    "Sketcher_ConstrainTangent": "T",
    "Sketcher_ConstrainSymmetric": "Shift+Q",
    "Sketcher_ConstrainBlock": "Shift+J",
    "Sketcher_ConstrainCoincident": "",
    "Sketcher_ConstrainPointOnObject": "",
    "Sketcher_ConstrainDistanceX": "",
    "Sketcher_ConstrainDistanceY": "",
    "Sketcher_ConstrainHorVer": "",
    "Sketcher_CompConstrainRadDia": "",
    "Sketcher_Translate": "",
    # The G, ... and Z, ... chords of the sketch tools Onshape has no key for
    "Sketcher_CompLine": "",
    "Sketcher_CreateLine": "",
    "Sketcher_CompCreateArc": "",
    "Sketcher_CreateArc": "",
    "Sketcher_CreateArcOfEllipse": "",
    "Sketcher_CreateArcOfHyperbola": "",
    "Sketcher_CreateArcOfParabola": "",
    "Sketcher_CompCreateConic": "",
    "Sketcher_Create3PointCircle": "",
    "Sketcher_CreateEllipseByCenter": "",
    "Sketcher_CreateEllipseBy3Points": "",
    "Sketcher_CompCreateRectangles": "",
    "Sketcher_CreateOblong": "",
    "Sketcher_CompCreateRegularPolygon": "",
    "Sketcher_CreateTriangle": "",
    "Sketcher_CreateSquare": "",
    "Sketcher_CreatePentagon": "",
    "Sketcher_CreateHexagon": "",
    "Sketcher_CreateHeptagon": "",
    "Sketcher_CreateOctagon": "",
    "Sketcher_CreateRegularPolygon": "",
    "Sketcher_CompSlot": "",
    "Sketcher_CreateSlot": "",
    "Sketcher_CreateArcSlot": "",
    "Sketcher_CompCreateBSpline": "",
    "Sketcher_CreateBSpline": "",
    "Sketcher_CreatePeriodicBSpline": "",
    "Sketcher_CreateBSplineByInterpolation": "",
    "Sketcher_CreatePeriodicBSplineByInterpolation": "",
    "Sketcher_CompCreateFillets": "",
    "Sketcher_CreateChamfer": "",
    "Sketcher_CompCurveEdition": "",
    "Sketcher_Split": "",
    "Sketcher_CompExternal": "",
    "Sketcher_CarbonCopy": "",
    "Sketcher_SelectConstraints": "",
    "Sketcher_SelectOrigin": "",
    "Sketcher_SelectVerticalAxis": "",
    "Sketcher_SelectHorizontalAxis": "",
    "Sketcher_SelectRedundantConstraints": "",
    "Sketcher_SelectConflictingConstraints": "",
    "Sketcher_SelectElementsAssociatedWithConstraints": "",
    "Sketcher_SelectElementsWithDoFs": "",
    "Sketcher_RestoreInternalAlignmentGeometry": "",
    "Sketcher_Symmetry": "",
    "Sketcher_Copy": "",
    "Sketcher_Clone": "",
    "Sketcher_Move": "",
    "Sketcher_RectangularArray": "",
    "Sketcher_RemoveAxesAlignment": "",
    "Sketcher_Rotate": "",
    "Sketcher_Scale": "",
    "Sketcher_SwitchVirtualSpace": "",
}

# Upstream's keys for a sample of the table (FreeCAD's keymap)
FREECAD = {
    "Std_ViewFront": "1",
    "Std_ViewIsometric": "0",
    "Std_ViewFitAll": "V, F",
    "Std_BoxElementSelection": "Shift+E",
    "Std_ClarifySelection": "`",
    "PartDesign_Pad": "",
    "Sketcher_CreateLine": "G, L",
    "Sketcher_CreateRectangle": "G, R",
    "Sketcher_ConstrainParallel": "P",
    "Part_FaceSelection": "F, S",
}

# Assembly's single letters that are the fork's general keys: cleared (decision 31); upstream's
ASSEMBLY_KEYS = {
    "Assembly_CreateJointFixed": "F",
    "Assembly_SolveAssembly": "Z",
    "Assembly_CreateJointScrew": "W",
    "Assembly_CreateJointRigidGroup": "Y",
}

# Pairs that share a key in upstream FreeCAD too, outside the keymap's commands: the tree's
# "Recompute Object" and Std_Recompute (Ctrl+Shift+R; the tree's action works on its selection)
UPSTREAM_CLASHES = [("Recompute Object", "Std_Recompute")]

# Sub-actions that aren't commands: the draw styles, and the workbenches' W, 1..9
DRAW_STYLES = {"Std_DrawStyleAsIs": "V,1", "Std_DrawStyleShaded": "V,6"}

# Draft's chords starting with an Onshape key, cleared (Python commands); upstream's keys
DRAFT_CHORDS = {
    "Draft_Line": "L, I",
    "Draft_SelectPlane": "W, P",
    "Draft_Facebinder": "F, F",
    "Draft_Move": "M, V",  # R, M and U: PR D
    "Draft_Rectangle": "R, E",
}


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


def same(a, b):
    return QtGui.QKeySequence(a) == QtGui.QKeySequence(b)


def shortcut(name):
    """The command's shortcut: its action's, "" while it has no action yet."""
    return Gui.Command.get(name).getShortcut()


def hasAction(name):
    return bool(Gui.Command.get(name).getAction())


def drawStyles():
    """{name: action} of the draw-style sub-actions."""
    return {a.objectName(): a for a in Gui.Command.get("Std_DrawStyle").getAction()}


def taskButton(which):
    for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
        button = box.button(which)
        if button is None or not button.isVisible():
            continue
        parent = box.parentWidget()
        while parent is not None:
            if parent.metaObject().className() == "Gui::TaskView::TaskView":
                return button
            parent = parent.parentWidget()
    return None


def focus(widget):
    for _ in range(20):
        widget.window().activateWindow()
        widget.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.05)
        focused = QtWidgets.QApplication.focusWidget()
        if focused is not None and (focused is widget or widget.isAncestorOf(focused)):
            return True
    return False


def command(name):
    try:
        return Gui.Command.get(name)
    except Exception:
        return None


def sameObject(a, b):
    return shiboken6.getCppPointer(a)[0] == shiboken6.getCppPointer(b)[0]


def groupCommands():
    """{group: (its key, its default tool, the tool's key)} of the group commands with an action
    (toolbar drop-downs). A group's button carries its default tool's key (GroupCommand::setup()),
    so the two run the same command. A C++ group's tools are the commands' own actions; a Python
    group's are actions of its own naming the command."""
    groups = {}
    for obj in Gui.getMainWindow().findChildren(QtCore.QObject):
        if obj.metaObject().className() != "Gui::ActionGroup":
            continue
        main = [c for c in obj.children() if isinstance(c, QtGui.QAction)]
        group = command(main[0].objectName()) if len(main) == 1 else None
        index = obj.property("defaultAction")
        if group is None or index is None:
            continue
        actions = group.getAction()
        if not 0 <= index < len(actions):
            continue
        tool = actions[index]
        if tool.property("CommandName"):
            toolName = bytes(tool.property("CommandName")).decode()
        else:
            # not a group command where the tool isn't a command's own action (the draw styles)
            toolName = tool.objectName()
            own = command(toolName).getAction() if command(toolName) else []
            if not own or not sameObject(own[0], tool):
                continue
        # the tool's action, not the command's getShortcut(): a Python group's tool (Assembly's
        # Insert, Gears/Belt) may have no action of its own, and then its getShortcut() is ""
        groups[main[0].objectName()] = (
            main[0].shortcut().toString(),
            toolName,
            tool.shortcut().toString(),
        )
    return groups


def setKeymap(name):
    App.ParamGet(KEYMAP).SetString("Keymap", name)
    pump(0.1)


def saved(path, name):
    """The stored string, None where there is none (to put back as it was)."""
    group = App.ParamGet(path)
    return group.GetString(name) if name in group.GetStrings() else None


def putBack(path, name, value):
    if value is None:
        App.ParamGet(path).RemString(name)
    else:
        App.ParamGet(path).SetString(name, value)


# GetContents()' types and the methods that set / remove each
SETTERS = {
    "String": ("SetString", "RemString"),
    "Integer": ("SetInt", "RemInt"),
    "Float": ("SetFloat", "RemFloat"),
    "Boolean": ("SetBool", "RemBool"),
    "Unsigned Long": ("SetUnsigned", "RemUnsigned"),
}


def snapshot(path):
    """({(type, name): value}, {subgroup: snapshot}) of a parameter group, recursively."""
    group = App.ParamGet(path)
    values = {(t, n): v for t, n, v in group.GetContents() or []}
    return values, {g: snapshot(f"{path}/{g}") for g in group.GetGroups()}


def restore(path, state):
    """Puts a group back as snapshot() saw it, a value at a time, so that its observers apply
    each one (ShortcutManager sets the command's key, priority or timeout); a value added since
    is removed. A group Clear() emptied but an observer holds comes back attached when written."""
    values, groups = state
    group = App.ParamGet(path)
    for t, n, v in group.GetContents() or []:
        if (t, n) not in values:
            getattr(group, SETTERS[t][1])(n)
    for (t, n), v in values.items():
        getattr(group, SETTERS[t][0])(n, v)
    for name, sub in groups.items():
        restore(f"{path}/{name}", sub)


def clearStoredKeys():
    """The commands' defaults only: removes the stored keys and priorities (each removal
    re-applies the default), and sets a changed chord timeout back to 300 ms."""
    shortcuts = App.ParamGet(SHORTCUTS)
    for name in shortcuts.GetStrings():
        shortcuts.RemString(name)
    priorities = App.ParamGet(SHORTCUTS + "/Priorities")
    for name in priorities.GetInts():
        priorities.RemInt(name)
    settings = App.ParamGet(SHORTCUTS + "/Settings")
    if "ShortcutTimeout" in settings.GetInts() and settings.GetInt("ShortcutTimeout") != 300:
        settings.SetInt("ShortcutTimeout", 300)


def isTemporaryHome():
    """Whether FreeCAD's user settings are a temporary folder's (a test run's, as CI's), not a
    user's profile."""
    home = os.environ.get("FREECAD_USER_HOME")
    if not home:
        return False
    home = os.path.normcase(os.path.realpath(home))
    temp = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
    try:
        return os.path.commonpath([home, temp]) == temp
    except ValueError:  # another drive
        return False


def enabledShortcuts():
    """{key: [action names]} of every enabled action under the main window with a shortcut."""
    keys = {}
    for action in Gui.getMainWindow().findChildren(QtGui.QAction):
        key = action.shortcut()
        if key.isEmpty() or not action.isEnabled():
            continue
        name = action.objectName() or action.text()
        keys.setdefault(key.toString(), set()).add(name)
    return keys


class TestForkKeymapGui(unittest.TestCase):
    maxDiff = None  # the clash and key lists in full

    @classmethod
    def setUpClass(cls):
        import PartGui  # noqa: F401  the selection filters' commands
        import SketcherGui  # noqa: F401
        import MeasureGui  # noqa: F401  Std_Measure

        Gui.activateWorkbench("PartDesignWorkbench")
        pump()
        # The tests change these and expect the defaults: the user's keys, priorities and keymap
        # come back at the end
        cls.saved = [(KEYMAP, "Keymap", saved(KEYMAP, "Keymap"))]
        cls.shortcuts = snapshot(SHORTCUTS)
        clearStoredKeys()
        pump(0.1)

    @classmethod
    def tearDownClass(cls):
        for path, name, value in cls.saved:
            putBack(path, name, value)
        restore(SHORTCUTS, cls.shortcuts)
        pump(0.1)

    def setUp(self):
        App.ParamGet(KEYMAP).RemString("Keymap")
        self.doc = App.newDocument("ForkKeymapGui")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.sketch = self.body.newObject("Sketcher::SketchObject", "Sketch")
        self.sketch.AttachmentSupport = (self.body.Origin.OriginFeatures[3], [""])  # XY_Plane
        self.sketch.MapMode = "FlatFace"
        corners = [(5, 0), (15, 0), (15, 10), (5, 10)]
        for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
            self.sketch.addGeometry(
                Part.LineSegment(App.Vector(ax, ay, 0), App.Vector(bx, by, 0)), False
            )
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        pump()

    def tearDown(self):
        App.ParamGet(KEYMAP).RemString("Keymap")
        App.ParamGet(SHORTCUTS).RemString("Std_ViewFitAll")
        pump(0.1)
        guiDoc = Gui.getDocument(self.doc.Name)
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        pump()

    # --- helpers

    def view3d(self):
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        # held: PySide drops a view's wrapper with its sub-window's
        self.viewWindows = [
            w
            for w in mdi.subWindowList()
            if w.widget().metaObject().className() == "Gui::View3DInventor"
        ]
        self.assertTrue(self.viewWindows, "the document's 3D view")
        mdi.setActiveSubWindow(self.viewWindows[-1])
        return self.viewWindows[-1].widget()

    def editSketch(self):
        Gui.ActiveDocument.setEdit(self.sketch.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))
        # Sketcher's commands are enabled on a timer once the sketch is in edit
        action = Gui.Command.get("Sketcher_CreateFillet").getAction()
        self.assertTrue(waitFor(lambda: action and all(a.isEnabled() for a in action)))

    @contextlib.contextmanager
    def watching(self, *names):
        """Records, in order, which of the commands run (their actions' triggered signal fires
        after the command's own slot)."""
        fired = []
        hooks = []
        for name in names:
            for action in Gui.Command.get(name).getAction():

                def onTriggered(*args, name=name):
                    fired.append(name)

                action.triggered.connect(onTriggered)
                hooks.append((action, onTriggered))
        try:
            yield fired
        finally:
            for action, hook in hooks:
                action.triggered.disconnect(hook)

    def press(self, key, modifiers=QtCore.Qt.NoModifier):
        self.assertTrue(focus(self.view3d()), "the 3D view doesn't take the focus")
        QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), key, modifiers)

    def escapeTool(self):
        QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_Escape)
        pump(0.2)

    # --- the table

    def testCommandsCarryTheTablesKeys(self):
        """Every command of the table carries the table's key, or none where it takes the key
        away. In sketch edit, so the sketch toolbars' actions exist; a command with no action yet
        has no shortcut to check (its action takes the same default when it's made)."""
        self.editSketch()
        wrong = []
        checked = 0
        for name, key in ONSHAPE.items():
            self.assertIsNotNone(Gui.Command.get(name), f"{name} isn't a command")
            if not hasAction(name):
                continue
            checked += 1
            actual = shortcut(name)
            if not same(actual, key):
                wrong.append(f"{name}: {actual!r}, expected {key!r}")
        self.assertEqual(wrong, [])
        self.assertGreater(
            checked, len(ONSHAPE) // 2, "too few of the table's commands have actions"
        )

    def testSubActionsLoseTheirChords(self):
        """The draw styles' V, 1..7 and the workbenches' W, 1..9 are cleared (V and W are Onshape
        keys)."""
        styles = drawStyles()
        self.assertEqual(len(styles), 7)
        for name, action in styles.items():
            self.assertTrue(action.shortcut().isEmpty(), name)
        workbenches = Gui.Command.get("Std_Workbench").getAction()
        self.assertTrue(workbenches)
        for action in workbenches:
            self.assertTrue(action.shortcut().isEmpty(), action.objectName())

    def testFreeCADKeymapGivesUpstreamsKeys(self):
        """Keymap = FreeCAD gives upstream's keys back without a restart, and Onshape the table's
        again."""
        self.editSketch()  # the sketch toolbars' actions
        setKeymap("FreeCAD")
        withActions = [name for name in FREECAD if hasAction(name)]
        self.assertGreater(len(withActions), len(FREECAD) // 2)
        for name in withActions:
            key = FREECAD[name]
            self.assertTrue(
                same(shortcut(name), key), f"{name}: {shortcut(name)!r}, expected {key!r}"
            )
        styles = drawStyles()
        for name, key in DRAW_STYLES.items():
            self.assertTrue(same(styles[name].shortcut().toString(), key), name)
        setKeymap("Onshape")
        for name in withActions:
            self.assertTrue(same(shortcut(name), ONSHAPE[name]), name)
        for name in DRAW_STYLES:
            self.assertTrue(styles[name].shortcut().isEmpty(), name)

    def testUserKeySurvives(self):
        """A key the user set stays through a keymap switch either way, and Reset gives the
        keymap's default."""
        App.ParamGet(SHORTCUTS).SetString("Std_ViewFitAll", "Ctrl+Alt+F")
        pump(0.1)
        self.assertTrue(same(shortcut("Std_ViewFitAll"), "Ctrl+Alt+F"))
        setKeymap("FreeCAD")
        self.assertTrue(same(shortcut("Std_ViewFitAll"), "Ctrl+Alt+F"))
        setKeymap("Onshape")
        self.assertTrue(same(shortcut("Std_ViewFitAll"), "Ctrl+Alt+F"))
        Gui.Command.get("Std_ViewFitAll").resetShortcut()
        pump(0.1)
        self.assertTrue(same(shortcut("Std_ViewFitAll"), "F"))

    def testResetAllKeepsTheKeymap(self):
        """Preferences > General > Keyboard > Reset All (the keyboard page's button) clears the
        Shortcut group and its subgroups: the keymap, kept elsewhere, stays FreeCAD's, in the
        preference and in the session. The real button clears every stored key and priority, so
        only in a temporary settings folder, and the group is put back right after: a stored key
        set here comes back on its command."""
        if not isTemporaryHome():
            self.skipTest("Reset All clears the stored keys: FREECAD_USER_HOME isn't temporary")
        App.ParamGet(SHORTCUTS).SetString("Std_ViewFitAll", "Ctrl+Alt+F")
        pump(0.1)
        before = snapshot(SHORTCUTS)
        setKeymap("FreeCAD")
        self.assertTrue(same(shortcut("Std_ViewFront"), "1"))
        page = Gui.UiLoader().createWidget("Gui::Dialog::DlgCustomKeyboardImp")
        self.assertIsNotNone(page)
        try:
            button = page.findChild(QtWidgets.QPushButton, "buttonResetAll")
            self.assertIsNotNone(button)
            button.click()
            pump(0.2)
            self.assertEqual(App.ParamGet(KEYMAP).GetString("Keymap"), "FreeCAD")
            self.assertTrue(same(shortcut("Std_ViewFront"), "1"), shortcut("Std_ViewFront"))
            self.assertTrue(same(shortcut("Std_ViewFitAll"), "V, F"), "Reset All ran")
        finally:
            page.deleteLater()
            restore(SHORTCUTS, before)
            pump(0.1)
        self.assertEqual(snapshot(SHORTCUTS), before)
        self.assertTrue(same(shortcut("Std_ViewFitAll"), "Ctrl+Alt+F"), shortcut("Std_ViewFitAll"))

    def testGroupButtonsFollowASwitch(self):
        """A group button (a toolbar drop-down) carries no key, or its default tool's once the
        user picked from the drop-down (GroupCommand::setup()). After a switch either way it
        carries the tool's new key, never the old keymap's: Std_ViewFront picked under FreeCAD's
        keymap gives the view group 1, and Onshape's then Shift+1. In sketch edit, so the sketch's
        groups have actions. Then nothing clashes, groups included."""
        self.editSketch()
        groups = groupCommands()
        for name in ("Std_ViewGroup", "Sketcher_CompHorVer", "Sketcher_CompCreateRectangles"):
            self.assertIn(name, groups)
        setKeymap("FreeCAD")
        viewGroup = Gui.Command.get("Std_ViewGroup")
        front = [a for a in viewGroup.getAction() if a.objectName() == "Std_ViewFront"]
        self.assertEqual(len(front), 1)
        front[0].trigger()
        pump(0.2)
        self.assertTrue(same(viewGroup.getShortcut(), "1"), viewGroup.getShortcut())
        for keymap in ("Onshape", "FreeCAD", "Onshape"):
            setKeymap(keymap)
            wrong = [
                f"{name}: {key!r}, its tool {tool}: {toolKey!r}"
                for name, (key, tool, toolKey) in groupCommands().items()
                if key and not same(key, toolKey)
            ]
            self.assertEqual(wrong, [], keymap)
        self.assertTrue(same(viewGroup.getShortcut(), "Shift+1"), viewGroup.getShortcut())
        pump(0.5)
        self.assertNoClashes("sketch edit, after a switch and back")

    def testFreeCADKeymapIsStockInSketchEdit(self):
        """Under FreeCAD's keymap, Pad and Revolution are disabled in sketch edit, as upstream,
        and the fork's widget doesn't hold their actions; back under Onshape's they work there."""

        def held(action):
            holder = Gui.getMainWindow().findChild(QtWidgets.QWidget, "_fc_ch_keymap_actions_")
            return holder is not None and any(sameObject(a, action) for a in holder.actions())

        pad = Gui.Command.get("PartDesign_Pad").getAction()[0]
        setKeymap("FreeCAD")
        self.editSketch()
        pump(0.5)
        self.assertFalse(pad.isEnabled())
        self.assertFalse(held(pad))
        setKeymap("Onshape")
        self.assertTrue(waitFor(pad.isEnabled))
        self.assertTrue(held(pad))

    def testOtherWorkbenchesChordsAreCleared(self):
        """Draft's chords starting with an Onshape key have no key under the fork's keymap (they
        would make that key wait once Draft is loaded), and upstream's under FreeCAD's. Python
        commands; in the Draft workbench, so their actions exist."""
        if "DraftWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Draft")
        try:
            Gui.activateWorkbench("DraftWorkbench")
            pump()
            wrong = [f"{n}: {shortcut(n)!r}" for n in DRAFT_CHORDS if shortcut(n) != ""]
            self.assertEqual(wrong, [], "Onshape")
            setKeymap("FreeCAD")
            wrong = [
                f"{n}: {shortcut(n)!r}" for n, k in DRAFT_CHORDS.items() if not same(shortcut(n), k)
            ]
            self.assertEqual(wrong, [], "FreeCAD")
        finally:
            Gui.activateWorkbench("PartDesignWorkbench")
            pump()

    # --- keys pressed

    def testShiftDigitSetsTheView(self):
        """Shift+1 gives the front view (looking along +Y), Shift+5 the top (along -Z), Shift+7
        the isometric."""
        view = Gui.ActiveDocument.ActiveView
        view.viewIsometric()
        pump(0.1)

        def direction():
            d = view.getViewDirection()
            return (round(d.x, 3), round(d.y, 3), round(d.z, 3))

        self.press(QtCore.Qt.Key_1, QtCore.Qt.ShiftModifier)
        self.assertTrue(waitFor(lambda: direction() == (0, 1, 0)), direction())
        self.press(QtCore.Qt.Key_5, QtCore.Qt.ShiftModifier)
        self.assertTrue(waitFor(lambda: direction() == (0, 0, -1)), direction())
        self.press(QtCore.Qt.Key_7, QtCore.Qt.ShiftModifier)
        self.assertTrue(
            waitFor(lambda: abs(direction()[0]) > 0.5 and abs(direction()[2]) > 0.5), direction()
        )

    def testShiftEPadsTheSelectedSketch(self):
        """With a body active and its sketch selected, Shift+E runs PartDesign_Pad (not the box
        element selection), which pads the sketch."""
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name)
        pad = Gui.Command.get("PartDesign_Pad").getAction()
        self.assertTrue(waitFor(lambda: all(a.isEnabled() for a in pad)))
        with self.watching("PartDesign_Pad", "Std_BoxElementSelection") as fired:
            self.press(QtCore.Qt.Key_E, QtCore.Qt.ShiftModifier)
            self.assertTrue(waitFor(lambda: fired), "Shift+E ran nothing")
            pump(0.4)
        self.assertEqual(fired, ["PartDesign_Pad"])
        pads = [o for o in self.body.Group if o.isDerivedFrom("PartDesign::Pad")]
        self.assertEqual(len(pads), 1)
        self.assertEqual(pads[0].Profile[0], self.sketch)

    def testShiftFInSketchIsTheSketchFillet(self):
        """In sketch edit, Shift+F (also PartDesign_Fillet's key, which the sketch's dialog
        disables) runs the sketch fillet."""
        self.editSketch()
        with self.watching("Sketcher_CreateFillet", "PartDesign_Fillet") as fired:
            self.press(QtCore.Qt.Key_F, QtCore.Qt.ShiftModifier)
            self.assertTrue(waitFor(lambda: fired), "Shift+F ran nothing")
            pump(0.4)
        self.escapeTool()
        self.assertEqual(fired, ["Sketcher_CreateFillet"])

    def testShiftSInSketchIsThePoint(self):
        """In sketch edit, Shift+S runs Sketcher_CreatePoint, not PartDesign_NewSketch."""
        self.editSketch()
        with self.watching("Sketcher_CreatePoint", "PartDesign_NewSketch") as fired:
            self.press(QtCore.Qt.Key_S, QtCore.Qt.ShiftModifier)
            self.assertTrue(waitFor(lambda: fired), "Shift+S ran nothing")
            pump(0.4)
        self.escapeTool()
        self.assertEqual(fired, ["Sketcher_CreatePoint"])

    def testTieGoesToTheEditCommand(self):
        """Two enabled commands on one key with the same priority: in sketch edit the command for
        the edit wins. Std_ViewFitAll, enabled in sketch edit, gets Shift+F as the user's key
        (stored without a priority, as in an imported user.cfg); Shift+F runs the sketch fillet,
        and outside the edit the fit."""
        App.ParamGet(SHORTCUTS).SetString("Std_ViewFitAll", "Shift+F")
        pump(0.1)
        self.assertTrue(same(shortcut("Std_ViewFitAll"), "Shift+F"))
        self.editSketch()
        fit = Gui.Command.get("Std_ViewFitAll").getAction()
        self.assertTrue(waitFor(lambda: all(a.isEnabled() for a in fit)))
        with self.watching("Sketcher_CreateFillet", "Std_ViewFitAll") as fired:
            self.press(QtCore.Qt.Key_F, QtCore.Qt.ShiftModifier)
            self.assertTrue(waitFor(lambda: fired), "Shift+F ran nothing")
            pump(0.4)
        self.escapeTool()
        self.assertEqual(fired, ["Sketcher_CreateFillet"])
        Gui.ActiveDocument.resetEdit()
        pump(0.5)
        with self.watching("Sketcher_CreateFillet", "Std_ViewFitAll") as fired:
            self.press(QtCore.Qt.Key_F, QtCore.Qt.ShiftModifier)
            self.assertTrue(waitFor(lambda: fired), "Shift+F ran nothing outside the edit")
            pump(0.4)
        self.assertEqual(fired, ["Std_ViewFitAll"])

    def testGStartsTheRectangleAtOnce(self):
        """In sketch edit, G starts the corner rectangle without the 300 ms wait for a longer
        chord: no enabled chord starts with G."""
        self.editSketch()
        self.assertTrue(focus(self.view3d()), "the 3D view doesn't take the focus")
        with self.watching("Sketcher_CreateRectangle") as fired:
            start = time.monotonic()
            QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_G)
            self.assertTrue(waitFor(lambda: fired), "G ran nothing")
            elapsed = time.monotonic() - start
        self.escapeTool()
        self.escapeTool()
        # the chord wait is 300 ms, the tool's start-up comes on top; events are pumped in 10-50
        # ms steps
        self.assertLess(elapsed, 0.28)

    def testRMUSwitchToolsWhileAToolRuns(self):
        """In sketch edit with the corner rectangle running, M starts the trim tool, R the centre
        rectangle and U the projection (use): Onshape's keys switch tools while a tool runs, as
        the other tool keys do. The tools' own M, U, J, R, F are Ctrl+ (PR D)."""
        keys = [
            (QtCore.Qt.Key_M, "Sketcher_Trimming"),
            (QtCore.Qt.Key_R, "Sketcher_CreateRectangle_Center"),
            (QtCore.Qt.Key_U, "Sketcher_Projection"),
        ]
        for key, name in keys:
            self.editSketch()
            with self.watching("Sketcher_CreateRectangle") as started:
                self.press(QtCore.Qt.Key_G)
                self.assertTrue(waitFor(lambda: started), "G ran nothing")
            pump(0.2)
            with self.watching(name) as fired:
                self.press(key)
                self.assertTrue(waitFor(lambda: fired), f"{name} didn't run")
            self.escapeTool()
            Gui.ActiveDocument.resetEdit()
            pump()

    def testCtrlKeyIsTheToolsOwn(self):
        """With the rectangle running, Ctrl+U toggles its rounded corners (U is the projection)
        and runs no command, and the option's label shows Ctrl+U; under FreeCAD's keymap the
        plain U toggles it, as upstream."""
        self.editSketch()
        self.press(QtCore.Qt.Key_G)

        def rounded():
            boxes = [
                b
                for b in Gui.getMainWindow().findChildren(QtWidgets.QCheckBox)
                if b.text().startswith("Rounded corners")
            ]
            return boxes[0] if boxes else None

        self.assertTrue(waitFor(lambda: rounded() is not None), "no rectangle options")
        ctrlU = QtGui.QKeySequence("Ctrl+U").toString(QtGui.QKeySequence.NativeText)
        self.assertTrue(rounded().text().endswith(f"({ctrlU})"), rounded().text())
        before = rounded().isChecked()
        watched = ("Sketcher_Projection", "Sketcher_Trimming", "Sketcher_CreateRectangle_Center")
        with self.watching(*watched) as fired:
            self.press(QtCore.Qt.Key_U, QtCore.Qt.ControlModifier)
            self.assertTrue(waitFor(lambda: rounded().isChecked() != before), "Ctrl+U")
            pump(0.4)
        self.assertEqual(fired, [])
        setKeymap("FreeCAD")
        self.press(QtCore.Qt.Key_U)
        self.assertTrue(waitFor(lambda: rounded().isChecked() == before), "U under FreeCAD's")
        self.escapeTool()

    def testFFitsTheViewInAssemblyEdit(self):
        """In assembly edit, F fits the view, not a Fixed joint (Assembly's joints are ForEdit, so
        the tie rule gave them F): Assembly's F, Z, W, Y are cleared under the fork's keymap, and
        back under FreeCAD's. An assembly of two boxes, in edit in the Assembly workbench."""
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        doc = App.newDocument("ForkKeymapAssembly")
        try:
            Gui.activateWorkbench("AssemblyWorkbench")
            assembly = doc.addObject("Assembly::AssemblyObject", "Assembly")
            for name in ("BoxA", "BoxB"):
                assembly.addObject(doc.addObject("Part::Box", name))
            doc.recompute()
            Gui.ActiveDocument = Gui.getDocument(doc.Name)
            Gui.ActiveDocument.setEdit(assembly.Name)
            self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))
            fixed = Gui.Command.get("Assembly_CreateJointFixed").getAction()
            self.assertTrue(waitFor(lambda: fixed and all(a.isEnabled() for a in fixed)))
            for name in ASSEMBLY_KEYS:
                self.assertEqual(shortcut(name), "", name)
            with self.watching("Std_ViewFitAll", "Assembly_CreateJointFixed") as fired:
                self.press(QtCore.Qt.Key_F)
                self.assertTrue(waitFor(lambda: fired), "F ran nothing")
                pump(0.4)
            self.assertEqual(fired, ["Std_ViewFitAll"])
            setKeymap("FreeCAD")
            wrong = [f"{n}: {shortcut(n)!r}" for n, k in ASSEMBLY_KEYS.items() if shortcut(n) != k]
            self.assertEqual(wrong, [], "FreeCAD")
        finally:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            guiDoc = Gui.getDocument(doc.Name)
            if guiDoc.getInEdit():
                guiDoc.resetEdit()
            pump()
            App.closeDocument(doc.Name)
            Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
            Gui.activateWorkbench("PartDesignWorkbench")
            pump()

    def editAndPress(self, key, typeName):
        self.editSketch()
        self.press(key, QtCore.Qt.ShiftModifier)
        self.assertTrue(
            waitFor(lambda: any(o.isDerivedFrom(typeName) for o in self.body.Group)),
            f"no {typeName}",
        )
        feature = next(o for o in self.body.Group if o.isDerivedFrom(typeName))
        self.assertEqual(feature.Profile[0], self.sketch)
        # the sketch is closed, and the new feature's panel is open
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))
        self.assertEqual(Gui.ActiveDocument.getInEdit().Object, feature)
        # the Tasks dock can sit in a hidden overlay (notes/build.md, "Task-panel GUI tests")
        Gui.Control.showTaskView()
        self.assertTrue(waitFor(lambda: taskButton(QtWidgets.QDialogButtonBox.Ok) is not None))
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        pump()
        self.doc.recompute()
        self.assertTrue(feature.isValid())
        self.assertGreater(feature.Shape.Volume, 0)

    def testShiftEInSketchClosesItAndPads(self):
        """In sketch edit, Shift+E closes the sketch and pads it, as Onshape's extrude does."""
        self.editAndPress(QtCore.Qt.Key_E, "PartDesign::Pad")

    def testShiftWInSketchClosesItAndRevolves(self):
        """In sketch edit, Shift+W closes the sketch and revolves it."""
        self.editAndPress(QtCore.Qt.Key_W, "PartDesign::Revolution")

    # --- conflicts

    def assertNoClashes(self, context, allowed=UPSTREAM_CLASHES):
        """No two enabled actions share a key, except a group with its default tool (the same
        command), where the tie rule picks one (a Sketcher command against a general one, in
        sketch edit), or where `allowed` lists the pair; and no enabled chord starts with an
        enabled single key (that key would wait 300 ms)."""
        keys = enabledShortcuts()
        tools = {name: tool for name, (key, tool, toolKey) in groupCommands().items()}
        inEdit = Gui.ActiveDocument.getInEdit() is not None
        clashes = []
        for key, names in keys.items():
            names = {n for n in names if tools.get(n) not in names}
            if len(names) < 2:
                continue
            sketcher = [n for n in names if n.startswith("Sketcher_")]
            if inEdit and len(sketcher) == 1:
                continue
            if frozenset(names) in {frozenset(a) for a in allowed}:
                continue
            clashes.append(f"{key}: {sorted(names)}")
        singles = {k for k in keys if QtGui.QKeySequence(k).count() == 1}
        for key, names in keys.items():
            sequence = QtGui.QKeySequence(key)
            if sequence.count() > 1:
                first = QtGui.QKeySequence(sequence[0]).toString()
                if first in singles:
                    clashes.append(f"{key} {sorted(names)} delays {first} {sorted(keys[first])}")
        self.assertEqual(clashes, [], context)

    def testNoClashesInPartDesign(self):
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name)
        pump(0.5)
        self.assertNoClashes("PartDesign")

    def testNoClashesInSketchEdit(self):
        self.editSketch()
        pump(0.5)
        self.assertNoClashes("sketch edit")


if __name__ == "__main__":
    unittest.main()
