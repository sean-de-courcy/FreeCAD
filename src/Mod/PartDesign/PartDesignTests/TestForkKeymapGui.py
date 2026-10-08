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
import math
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
    "Std_SelectOther": "`",  # Onshape's select other (PR C)
    "Std_Refresh": "F5",  # QKeySequence::Refresh is Ctrl+R (a tool's own key) on macOS
    # the fork's commands (PR B), and the key Space was
    "Std_ClearSelection": "Space",
    "Std_ToggleVisibility": "",
    "Std_ViewNormal": "N",
    "Std_Isolate": "Shift+I",
    "PartDesign_ToggleSketches": "Shift+H",
    "PartDesign_TogglePlanes": "P",
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
    # The arrows orbit the view (B2): the chords the viewer takes are off the commands
    "Std_ViewRotateLeft": "",
    "Std_ViewRotateRight": "",
    "Std_DockOverlayToggleLeft": "",
    "Std_DockOverlayToggleRight": "",
    "Std_DockOverlayToggleTop": "",
    "Std_DockOverlayToggleBottom": "",
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
    "Sketcher_ViewSketch": "",  # N is Std_ViewNormal's, which runs it in sketch edit
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
    "Std_SelectOther": "",
    "Std_ClarifySelection": "`",
    "PartDesign_Pad": "",
    "Sketcher_CreateLine": "G, L",
    "Sketcher_CreateRectangle": "G, R",
    "Sketcher_ConstrainParallel": "P",
    "Part_FaceSelection": "F, S",
    "Std_Refresh": QtGui.QKeySequence(QtGui.QKeySequence.Refresh).toString(),
    "Std_ToggleVisibility": "Space",
    "Std_ClearSelection": "",
    "Std_ViewNormal": "",
    "Sketcher_ViewSketch": "Q, P",
    "Std_ViewRotateLeft": "Shift+Left",
    "Std_ViewRotateRight": "Shift+Right",
    "Std_DockOverlayToggleLeft": "Ctrl+Left",
    "Std_DockOverlayToggleRight": "Ctrl+Right",
    "Std_DockOverlayToggleTop": "Ctrl+Up",
    "Std_DockOverlayToggleBottom": "Ctrl+Down",
}

# Assembly's single letters that are the fork's keys: cleared (decision 31); upstream's
ASSEMBLY_KEYS = {
    "Assembly_CreateJointFixed": "F",
    "Assembly_SolveAssembly": "Z",
    "Assembly_CreateJointScrew": "W",
    "Assembly_CreateJointRigidGroup": "Y",
    "Assembly_CreateBom": "O",  # enabled in sketch edit too, beside Sketcher_Offset's O
    "Assembly_InsertNewPart": "P",  # PR B: the planes
    "Assembly_CreateJointParallel": "N",  # PR B: normal to
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
    "Draft_Wire": "P, L",  # P and N: PR B
    "Draft_Polygon": "P, G",
    # Onshape's Shift+S (PR B: the clash scans see Draft's keys once BIM, which loads Draft, ran)
    "Draft_Snap_Lock": "Shift+S",
}

# BIM's and CAM's chords starting with P or N (PR B), cleared; upstream's keys
OTHER_CHORDS = {
    "BIMWorkbench": {
        "Arch_Panel": "P, A",
        "Arch_Panel_Cut": "P, C",
        "Arch_Panel_Sheet": "P, S",
        "Arch_Pipe": "P, I",
        "Arch_PipeConnector": "P, C",
        "Arch_Profile": "P, F",
        "Arch_Nest": "N, E",
    },
    "CAMWorkbench": {
        "CAM_Camotics": "P, C",
        "CAM_Inspect": "P, I",
        "CAM_Job": "P, J",
        "CAM_Sanity": "P, S",
        "CAM_QuickValidate": "P, V",
        "CAM_Simulator": "P, M",
        "CAM_SimulatorGL": "P, N",
        "CAM_Post": "P, P",
        "CAM_PostSelected": "P, O",
        "CAM_ToolBitDock": "P, T",
        "CAM_SelectLoop": "P, L",
        "CAM_OpActiveToggle": "P, X",
    },
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


def toolKey(name):
    """The key the command's actions carry: its own action's, or else that of a Python group's
    action for it (a group's tool may have no action of its own, and then its getShortcut() is
    ""); None where it has no action at all."""
    if hasAction(name):
        return shortcut(name)
    for action in Gui.getMainWindow().findChildren(QtGui.QAction):
        commandName = action.property("CommandName")
        if commandName and bytes(commandName).decode() == name:
            return action.shortcut().toString()
    return None


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
        # a list a failed test left open takes the keys of every later test; so does a filter
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is not None and popup.objectName() == "SelectOtherMenu":
            popup.close()
            pump(0.1)
        Gui.runCommand("Part_SelectFilter", 3)
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
        # a group's button carries its default tool's key once a tool was picked from it
        # (GroupCommand::setup(); earlier tests pick, and a workbench switch sets the buttons up)
        # (only where the tool's key is the table's for the tool: a group whose key the table takes
        # away must stay "")
        tools = {
            name: toolKey
            for name, (_, toolName, toolKey) in groupCommands().items()
            if toolName in ONSHAPE and toolKey and same(toolKey, ONSHAPE[toolName])
        }
        wrong = []
        checked = 0
        for name, key in ONSHAPE.items():
            self.assertIsNotNone(Gui.Command.get(name), f"{name} isn't a command")
            if not hasAction(name):
                continue
            checked += 1
            actual = shortcut(name)
            if not same(actual, key) and not (name in tools and same(actual, tools[name])):
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
            wrong = [f"{n}: {toolKey(n)!r}" for n in DRAFT_CHORDS if toolKey(n) != ""]
            self.assertEqual(wrong, [], "Onshape")
            setKeymap("FreeCAD")
            wrong = [
                f"{n}: {toolKey(n)!r}" for n, k in DRAFT_CHORDS.items() if not same(toolKey(n), k)
            ]
            self.assertEqual(wrong, [], "FreeCAD")
        finally:
            Gui.activateWorkbench("PartDesignWorkbench")
            pump()

    def testBIMAndCAMChordsOnPAndNAreCleared(self):
        """BIM's and CAM's chords starting with P or N have no key under the fork's keymap (P and
        N would wait for them once the workbench is loaded), and upstream's under FreeCAD's. In
        each workbench, so their actions exist."""
        # BIM's first activation queues its modal Welcome dialog, which a test run never closes
        bim = App.ParamGet("User parameter:BaseApp/Preferences/Mod/BIM")
        firstTime = bim.GetBool("FirstTime") if "FirstTime" in bim.GetBools() else None
        bim.SetBool("FirstTime", False)
        self.addCleanup(
            lambda: bim.RemBool("FirstTime")
            if firstTime is None
            else bim.SetBool("FirstTime", firstTime)
        )
        tried = 0
        for workbench, chords in OTHER_CHORDS.items():
            if workbench not in Gui.listWorkbenches():
                continue
            tried += 1
            try:
                Gui.activateWorkbench(workbench)
                pump()
                # a command with no action yet (CAM_Camotics, CAM_QuickValidate: in no toolbar
                # or menu) takes the table's key when its action is made
                chords = {n: k for n, k in chords.items() if command(n) and toolKey(n) is not None}
                self.assertGreater(len(chords), len(OTHER_CHORDS[workbench]) // 2, workbench)
                wrong = [f"{n}: {toolKey(n)!r}" for n in chords if toolKey(n) != ""]
                self.assertEqual(wrong, [], f"{workbench}, Onshape")
                setKeymap("FreeCAD")
                wrong = [
                    f"{n}: {toolKey(n)!r}" for n, k in chords.items() if not same(toolKey(n), k)
                ]
                self.assertEqual(wrong, [], f"{workbench}, FreeCAD")
            finally:
                setKeymap("Onshape")
                Gui.activateWorkbench("PartDesignWorkbench")
                pump()
        if not tried:
            self.skipTest("no BIM or CAM")

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

    def toolOption(self, prefix):
        boxes = [
            b
            for b in Gui.getMainWindow().findChildren(QtWidgets.QCheckBox)
            if b.text().startswith(prefix) and b.isVisible()
        ]
        return boxes[0] if boxes else None

    def checked(self, prefix):
        """The tool option's state, None while it isn't shown; looked up each time, since a
        toggle can rebuild the tool's widget."""
        box = self.toolOption(prefix)
        return box.isChecked() if box else None

    def allCommands(self):
        return [n for n in Gui.Command.listAll() if hasAction(n)]

    def testCtrlKeyIsTheToolsOwn(self):
        """With the rectangle running, Ctrl+U and Ctrl+J toggle its rounded corners and frame and
        run no command, and the options' labels and the construction method's show Ctrl+U,
        Ctrl+J and Ctrl+M; the plain J, which no shortcut takes, reaches the tool and leaves the
        frame alone (the plain U, R, F and M are shortcuts); under FreeCAD's keymap the plain U
        toggles the rounded corners, as upstream."""
        self.editSketch()
        self.press(QtCore.Qt.Key_G)
        self.assertTrue(waitFor(lambda: self.toolOption("Rounded corners")), "no rectangle options")
        rounded = self.toolOption("Rounded corners")
        frame = self.toolOption("Frame")

        def native(key):
            return QtGui.QKeySequence(key).toString(QtGui.QKeySequence.NativeText)

        self.assertTrue(rounded.text().endswith(f"({native('Ctrl+U')})"), rounded.text())
        self.assertTrue(frame.text().endswith(f"({native('Ctrl+J')})"), frame.text())
        modes = [
            label.text()
            for label in Gui.getMainWindow().findChildren(QtWidgets.QLabel)
            if label.objectName() == "comboLabel1" and label.isVisible()
        ]
        self.assertEqual(modes, [f"Mode ({native('Ctrl+M')})"])

        def options():
            return (self.checked("Rounded corners"), self.checked("Frame"))

        before = options()
        with self.watching(*self.allCommands()) as fired:
            self.press(QtCore.Qt.Key_J)
            pump(0.4)
            self.assertEqual(options(), before, "plain J")
            self.press(QtCore.Qt.Key_U, QtCore.Qt.ControlModifier)
            self.assertTrue(waitFor(lambda: options() == (not before[0], before[1])), "Ctrl+U")
            self.press(QtCore.Qt.Key_J, QtCore.Qt.ControlModifier)
            self.assertTrue(waitFor(lambda: options() == (not before[0], not before[1])), "Ctrl+J")
            pump(0.4)
        self.assertEqual(fired, [])
        setKeymap("FreeCAD")
        self.press(QtCore.Qt.Key_U)
        self.assertTrue(
            waitFor(lambda: options() == (before[0], not before[1])), "U under FreeCAD's"
        )
        self.escapeTool()

    def testCtrlFAndRAreThePolylinesOwn(self):
        """With the polyline running and the document needing a recompute, Ctrl+F toggles its
        fillet option and Ctrl+R (undo the last point) runs no command: Std_Refresh is F5, not
        QKeySequence::Refresh, which is Ctrl+R on macOS."""
        self.editSketch()
        self.assertTrue(same(shortcut("Std_Refresh"), "F5"), shortcut("Std_Refresh"))
        self.press(QtCore.Qt.Key_L)
        self.assertTrue(waitFor(lambda: self.toolOption("Fillet")), "no polyline options")
        before = self.checked("Fillet")
        self.body.touch()
        with self.watching(*self.allCommands()) as fired:
            self.press(QtCore.Qt.Key_F, QtCore.Qt.ControlModifier)
            self.assertTrue(waitFor(lambda: self.checked("Fillet") == (not before)), "Ctrl+F")
            self.press(QtCore.Qt.Key_R, QtCore.Qt.ControlModifier)
            pump(0.4)
        self.assertEqual(fired, [])
        self.escapeTool()

    def testFFitsTheViewInAssemblyEdit(self):
        """In assembly edit, F fits the view, not a Fixed joint (Assembly's joints are ForEdit, so
        the tie rule gave them F): Assembly's F, Z, W, Y and the BOM's O are cleared under the
        fork's keymap, nothing clashes in assembly edit, and the keys are back under FreeCAD's.
        An assembly of two boxes, in edit in the Assembly workbench."""
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
                self.assertEqual(toolKey(name), "", name)
            with self.watching("Std_ViewFitAll", "Assembly_CreateJointFixed") as fired:
                self.press(QtCore.Qt.Key_F)
                self.assertTrue(waitFor(lambda: fired), "F ran nothing")
                pump(0.4)
            self.assertEqual(fired, ["Std_ViewFitAll"])
            # the fork's general keys: the sketch's keys meet Assembly's letters only on actions
            # that aren't reachable there (D: the sketch's dimension group, its toolbar hidden),
            # and Assembly's letters meet upstream's own (S and Std_LinkSelectActions' S, G)
            general = {
                QtGui.QKeySequence(k).toString()
                for n, k in ONSHAPE.items()
                if k and not n.startswith("Sketcher_")
            }
            self.assertNoClashes("assembly edit", only=general)
            setKeymap("FreeCAD")
            wrong = [f"{n}: {toolKey(n)!r}" for n, k in ASSEMBLY_KEYS.items() if toolKey(n) != k]
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

    # --- the fork's commands (PR B)

    def visibility(self):
        """{name: shown} of the document's objects with a view provider."""
        guiDoc = Gui.getDocument(self.doc.Name)
        return {
            o.Name: guiDoc.getObject(o.Name).Visibility
            for o in self.doc.Objects
            if guiDoc.getObject(o.Name) is not None
        }

    def pressFor(self, key, modifiers, name):
        """Presses the key once the command `name` is enabled, and waits for it to run."""
        action = Gui.Command.get(name).getAction()
        self.assertTrue(waitFor(lambda: all(a.isEnabled() for a in action)), f"{name} is off")
        with self.watching(name) as fired:
            self.press(key, modifiers)
            self.assertTrue(waitFor(lambda: fired), f"{name} didn't run")
            pump(0.2)

    def testSpaceClearsTheSelection(self):
        """Space clears the selection and leaves the visibility alone; under FreeCAD's keymap it
        is Std_ToggleVisibility's, and hides the selected sketch."""
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name)
        before = self.visibility()
        with self.watching("Std_ToggleVisibility") as toggled:
            self.pressFor(QtCore.Qt.Key_Space, QtCore.Qt.NoModifier, "Std_ClearSelection")
        self.assertEqual(Gui.Selection.getSelection(), [])
        self.assertEqual(toggled, [])
        self.assertEqual(self.visibility(), before)
        setKeymap("FreeCAD")
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name)
        self.pressFor(QtCore.Qt.Key_Space, QtCore.Qt.NoModifier, "Std_ToggleVisibility")
        self.assertNotEqual(self.visibility()[self.sketch.Name], before[self.sketch.Name])

    def treeSpace(self):
        """Presses Space with the model tree focused; the selected sketch, as the 3D view
        would have it."""
        tree = next(
            w
            for w in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget)
            if w.metaObject().className() == "Gui::TreeWidget" and w.isVisible()
        )
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name)
        # the commands are enabled on a timer after the selection changed
        for name in ("Std_ClearSelection", "Std_ToggleVisibility"):
            action = Gui.Command.get(name).getAction()
            if action and shortcut(name):
                self.assertTrue(waitFor(lambda: all(a.isEnabled() for a in action)), name)
        self.assertTrue(focus(tree), "the tree doesn't take the focus")
        QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_Space)
        pump(0.5)

    def testSpaceInTheTreeClearsTheSelection(self):
        """With the focus in the tree, Space clears the selection under the fork's keymap (the
        tree used to take it and hide the selected feature), and toggles the visibility under
        FreeCAD's."""
        before = self.visibility()
        self.treeSpace()
        self.assertEqual(Gui.Selection.getSelection(), [])
        self.assertEqual(self.visibility(), before)
        setKeymap("FreeCAD")
        Gui.Selection.clearSelection()
        self.treeSpace()
        self.assertNotEqual(self.visibility()[self.sketch.Name], before[self.sketch.Name])

    def modelTree(self):
        return next(
            w
            for w in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget)
            if w.metaObject().className() == "Gui::TreeWidget" and w.isVisible()
        )

    def spaceOnTheBodysItem(self):
        """Presses Space in the tree with nothing selected and the body's item current."""
        tree = self.modelTree()
        tree.expandAll()
        pump(0.2)
        item = None
        for found in tree.findItems("Body", QtCore.Qt.MatchRecursive | QtCore.Qt.MatchStartsWith):
            item = found
        self.assertIsNotNone(item, "the body's tree item")
        # the current item without selecting it
        tree.selectionModel().setCurrentIndex(
            tree.indexFromItem(item), QtCore.QItemSelectionModel.NoUpdate
        )
        Gui.Selection.clearSelection()
        pump(0.2)
        self.assertEqual(Gui.Selection.getSelection(), [])
        self.assertTrue(focus(tree), "the tree doesn't take the focus")
        QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_Space)
        pump(0.5)
        return tree

    def testSpaceInTheTreeWithNothingSelectedSelectsNothing(self):
        """With nothing selected, Std_ClearSelection is off and Space goes on to the tree, whose
        own handling selects the current item (so Space twice would clear, then select again):
        under the fork's keymap the tree drops a plain Space."""
        tree = self.spaceOnTheBodysItem()
        self.assertEqual(Gui.Selection.getSelection(), [])
        self.assertEqual(tree.selectedItems(), [])

    def testSpaceInTheTreeIsTheTreesOnceTheUserMovesClearSelection(self):
        """The tree drops Space only while Space is Std_ClearSelection's: a user who moves the
        command to another key gets the tree's own Space back (it selects the current item)."""
        App.ParamGet(SHORTCUTS).SetString("Std_ClearSelection", "Ctrl+Alt+F12")
        self.addCleanup(App.ParamGet(SHORTCUTS).RemString, "Std_ClearSelection")
        pump(0.1)
        self.assertTrue(same(shortcut("Std_ClearSelection"), "Ctrl+Alt+F12"))
        self.spaceOnTheBodysItem()
        self.assertEqual([o.Name for o in Gui.Selection.getSelection()], [self.body.Name])

    def boxes(self):
        """Two 10 mm boxes outside the body, at x 0 and x 30."""
        a = self.doc.addObject("Part::Box", "BoxA")
        b = self.doc.addObject("Part::Box", "BoxB")
        b.Placement.Base = App.Vector(30, 0, 0)
        self.doc.recompute()
        pump()
        return a, b

    def viewDirection(self):
        d = Gui.ActiveDocument.ActiveView.getViewDirection()
        return App.Vector(d.x, d.y, d.z)

    def testNIsNormalToTheSelectedFace(self):
        """With a box's face selected, N looks along the face's normal (Std_AlignToSelection):
        BoxA's Face1 is its x = 0 face."""
        a, _ = self.boxes()
        Gui.ActiveDocument.ActiveView.viewIsometric()
        Gui.Selection.addSelection(self.doc.Name, a.Name, "Face1")
        self.pressFor(QtCore.Qt.Key_N, QtCore.Qt.NoModifier, "Std_ViewNormal")
        self.assertTrue(
            waitFor(lambda: abs(abs(self.viewDirection().x) - 1) < 1e-3), self.viewDirection()
        )

    def testNInSketchEditLooksAtTheSketch(self):
        """In sketch edit, N looks at the sketch plane (Sketcher_ViewSketch), here XY: along -Z,
        with nothing selected."""
        self.editSketch()
        Gui.ActiveDocument.ActiveView.viewIsometric()
        pump(0.2)
        self.pressFor(QtCore.Qt.Key_N, QtCore.Qt.NoModifier, "Std_ViewNormal")
        self.assertTrue(
            waitFor(lambda: (self.viewDirection() - App.Vector(0, 0, -1)).Length < 1e-3),
            self.viewDirection(),
        )

    def testShiftIIsolatesTheSelectionAndRestores(self):
        """Shift+I with a face of BoxA selected hides every other shown object (BoxB, the body,
        its sketch) and keeps BoxA; Shift+I again, with nothing selected, shows exactly those
        again."""
        a, b = self.boxes()
        before = self.visibility()
        self.assertTrue(before[b.Name] and before[self.body.Name])
        Gui.Selection.addSelection(self.doc.Name, a.Name, "Face1")
        self.pressFor(QtCore.Qt.Key_I, QtCore.Qt.ShiftModifier, "Std_Isolate")
        shown = {n for n, v in self.visibility().items() if v}
        self.assertEqual(shown, {a.Name})
        Gui.Selection.clearSelection()
        self.pressFor(QtCore.Qt.Key_I, QtCore.Qt.ShiftModifier, "Std_Isolate")
        self.assertEqual(self.visibility(), before)

    def testShiftIKeepsTheGroupsOfAnObjectSelectedWithoutAPath(self):
        """An object selected without a path (a click in the tree selects the box alone) keeps
        the group it is in: hiding the Part would hide the box."""
        a, b = self.boxes()
        part = self.doc.addObject("App::Part", "Part")
        inner = part.newObject("Part::Box", "Inner")
        self.doc.recompute()
        Gui.getDocument(self.doc.Name).getObject(part.Name).Visibility = True
        Gui.getDocument(self.doc.Name).getObject(inner.Name).Visibility = True
        pump()
        self.assertTrue(self.visibility()[part.Name], "the part starts hidden")
        Gui.Selection.addSelection(self.doc.Name, inner.Name)
        self.pressFor(QtCore.Qt.Key_I, QtCore.Qt.ShiftModifier, "Std_Isolate")
        shown = {n for n, v in self.visibility().items() if v}
        self.assertEqual(shown & {part.Name, inner.Name}, {part.Name, inner.Name})
        self.assertEqual(shown & {a.Name, b.Name, self.body.Name}, set())

    def testShiftIKeepsTheFolderOfAnObjectSelectedWithoutAPath(self):
        """The same for a plain folder (App::DocumentObjectGroup): an App::Part resolves to a path
        even without the loop that keeps the groups, a folder doesn't, and hiding the folder would
        hide the object in it."""
        a, b = self.boxes()
        folder = self.doc.addObject("App::DocumentObjectGroup", "Folder")
        inner = self.doc.addObject("Part::Box", "Inner")
        folder.addObject(inner)
        self.doc.recompute()
        Gui.getDocument(self.doc.Name).getObject(folder.Name).Visibility = True
        Gui.getDocument(self.doc.Name).getObject(inner.Name).Visibility = True
        pump()
        self.assertTrue(self.visibility()[folder.Name], "the folder should start shown")
        Gui.Selection.addSelection(self.doc.Name, inner.Name)
        self.pressFor(QtCore.Qt.Key_I, QtCore.Qt.ShiftModifier, "Std_Isolate")
        shown = {n for n, v in self.visibility().items() if v}
        self.assertEqual(shown & {folder.Name, inner.Name}, {folder.Name, inner.Name})
        self.assertEqual(shown & {a.Name, b.Name, self.body.Name}, set())

    def testShiftIKeepsTheSelectedFeaturesBody(self):
        """Isolating a feature of a body (selected through the body, as a click in the 3D view
        does) keeps the body, whose hiding would hide the feature, and hides the boxes and the
        body's other shown features."""
        a, b = self.boxes()
        pad = self.body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.sketch
        pad.Length = 5
        self.doc.recompute()
        Gui.getDocument(self.doc.Name).getObject(self.sketch.Name).Visibility = True
        pump()
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, "Pad.Face1")
        self.pressFor(QtCore.Qt.Key_I, QtCore.Qt.ShiftModifier, "Std_Isolate")
        shown = {n for n, v in self.visibility().items() if v}
        self.assertEqual(shown & {self.body.Name, pad.Name}, {self.body.Name, pad.Name})
        self.assertEqual(shown & {a.Name, b.Name, self.sketch.Name}, set())

    def secondBody(self):
        """A second body with a shown sketch, and a second, hidden sketch in the first body."""
        hidden = self.body.newObject("Sketcher::SketchObject", "Hidden")
        hidden.AttachmentSupport = (self.body.Origin.OriginFeatures[4], [""])  # XZ_Plane
        hidden.MapMode = "FlatFace"
        other = self.doc.addObject("PartDesign::Body", "Other")
        otherSketch = other.newObject("Sketcher::SketchObject", "OtherSketch")
        otherSketch.AttachmentSupport = (other.Origin.OriginFeatures[3], [""])
        otherSketch.MapMode = "FlatFace"
        self.doc.recompute()
        guiDoc = Gui.getDocument(self.doc.Name)
        guiDoc.getObject(hidden.Name).Visibility = False
        guiDoc.getObject(self.sketch.Name).Visibility = True
        guiDoc.getObject(otherSketch.Name).Visibility = True
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        pump()
        return hidden, other, otherSketch

    def testShiftHTogglesTheBodysSketches(self):
        """Shift+H hides the active body's sketches when one is shown, and shows them all when
        none is; another body's sketch stays as it is."""
        hidden, _, otherSketch = self.secondBody()
        ours = (self.sketch.Name, hidden.Name)
        self.pressFor(QtCore.Qt.Key_H, QtCore.Qt.ShiftModifier, "PartDesign_ToggleSketches")
        vis = self.visibility()
        self.assertEqual([vis[n] for n in ours], [False, False])
        self.assertTrue(vis[otherSketch.Name])
        self.pressFor(QtCore.Qt.Key_H, QtCore.Qt.ShiftModifier, "PartDesign_ToggleSketches")
        vis = self.visibility()
        self.assertEqual([vis[n] for n in ours], [True, True])
        self.assertTrue(vis[otherSketch.Name])

    def testShiftHLeavesTheSketchInEditShown(self):
        """In sketch edit the command hides and shows the body's other sketches, and leaves the
        sketch being edited shown and in edit. (Its key does nothing there: the action sits in
        Part Design's View menu, which sketch edit replaces; the menu of the edit's workbench
        has no entry for it.)"""
        hidden, _, _ = self.secondBody()
        self.editSketch()
        guiDoc = Gui.getDocument(self.doc.Name)
        # the sketch in edit is as it is while it is edited (its own state, not necessarily shown)
        editing = self.visibility()[self.sketch.Name]
        action = Gui.Command.get("PartDesign_ToggleSketches").getAction()
        self.assertTrue(waitFor(lambda: all(a.isEnabled() for a in action)))
        Gui.runCommand("PartDesign_ToggleSketches")
        pump(0.3)
        vis = self.visibility()
        self.assertTrue(vis[hidden.Name], "the other sketch isn't shown")
        self.assertEqual(vis[self.sketch.Name], editing, "the sketch in edit was changed")
        self.assertIsNotNone(guiDoc.getInEdit(), "the sketch left edit")
        Gui.runCommand("PartDesign_ToggleSketches")
        pump(0.3)
        vis = self.visibility()
        self.assertFalse(vis[hidden.Name], "the other sketch isn't hidden again")
        self.assertEqual(vis[self.sketch.Name], editing, "the sketch in edit was changed")
        self.assertIsNotNone(guiDoc.getInEdit(), "the sketch left edit")

    def planesShown(self, body):
        """{role or name: shown in the 3D view} of the body's origin features and datum planes:
        an origin feature shows only with its origin."""
        guiDoc = Gui.getDocument(self.doc.Name)
        origin = guiDoc.getObject(body.Origin.Name).Visibility
        shown = {}
        for feature in body.Origin.OriginFeatures:
            shown[feature.Role] = origin and guiDoc.getObject(feature.Name).Visibility
        for o in body.Group:
            if o.isDerivedFrom("PartDesign::Plane"):
                shown[o.Name] = guiDoc.getObject(o.Name).Visibility
        return shown

    def testPTogglesTheBodysPlanes(self):
        """P shows the active body's three origin planes and its datum plane (not the axes or the
        origin point), and P again hides them; the other body's stay hidden."""
        _, other, _ = self.secondBody()
        datum = self.body.newObject("PartDesign::Plane", "DatumPlane")
        self.doc.recompute()
        Gui.getDocument(self.doc.Name).getObject(datum.Name).Visibility = False
        pump()
        self.assertFalse(any(self.planesShown(self.body).values()))
        self.pressFor(QtCore.Qt.Key_P, QtCore.Qt.NoModifier, "PartDesign_TogglePlanes")
        shown = self.planesShown(self.body)
        self.assertEqual(
            {k for k, v in shown.items() if v}, {"XY_Plane", "XZ_Plane", "YZ_Plane", datum.Name}
        )
        self.assertFalse(any(self.planesShown(other).values()))
        self.pressFor(QtCore.Qt.Key_P, QtCore.Qt.NoModifier, "PartDesign_TogglePlanes")
        self.assertFalse(any(self.planesShown(self.body).values()))

    def testNewCommandsAreInTheMenus(self):
        """A shortcut needs its action in a visible widget: each new command is in a menu of the
        menu bar (the View menu; Part Design's for the body's)."""
        inMenus = set()
        for menu in Gui.getMainWindow().menuBar().findChildren(QtWidgets.QMenu):
            inMenus.update(a.objectName() for a in menu.actions())
        names = (
            "Std_ClearSelection",
            "Std_ViewNormal",
            "Std_Isolate",
            "PartDesign_ToggleSketches",
            "PartDesign_TogglePlanes",
        )
        self.assertEqual([n for n in names if n not in inMenus], [])

    # --- conflicts

    def assertNoClashes(self, context, allowed=UPSTREAM_CLASHES, only=None):
        """No two enabled actions share a key, except a group with its default tool (the same
        command), where the tie rule picks one (in an edit, one Sketcher command against general
        or Part Design ones, which aren't ForEdit where they share a key), or where `allowed`
        lists the pair; and no enabled chord starts with an enabled single key (that key would
        wait 300 ms). Another workbench's command beside a Sketcher one is a clash: it may be
        ForEdit too (Assembly_CreateBom's O), and then the tie rule can't choose. With `only`
        (key strings), just the clashes on those keys."""
        keys = enabledShortcuts()
        tools = {name: tool for name, (key, tool, toolKey) in groupCommands().items()}
        inEdit = Gui.ActiveDocument.getInEdit() is not None
        clashes = []
        for key, names in keys.items():
            if only is not None and key not in only:
                continue
            names = {n for n in names if tools.get(n) not in names}
            if len(names) < 2:
                continue
            sketcher = [n for n in names if n.startswith("Sketcher_")]
            general = [n for n in names if n.startswith(("Std_", "PartDesign_"))]
            if inEdit and len(sketcher) == 1 and len(sketcher) + len(general) == len(names):
                continue
            if frozenset(names) in {frozenset(a) for a in allowed}:
                continue
            clashes.append(f"{key}: {sorted(names)}")
        singles = {k for k in keys if QtGui.QKeySequence(k).count() == 1}
        for key, names in keys.items():
            sequence = QtGui.QKeySequence(key)
            if sequence.count() > 1:
                first = QtGui.QKeySequence(sequence[0]).toString()
                if only is not None and first not in only:
                    continue
                if first in singles:
                    clashes.append(f"{key} {sorted(names)} delays {first} {sorted(keys[first])}")
        self.assertEqual(clashes, [], context)

    def testNoClashesInPartDesign(self):
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name)
        pump(0.5)
        self.assertNoClashes("PartDesign")

    def testNoClashesInSketchEdit(self):
        """In sketch edit, and again with an edge selected, which enables the commands that work
        on geometry (Sketcher_Offset's O met Assembly_CreateBom's only then). Assembly loaded
        first: its commands stay registered and enabled in Part Design."""
        if "AssemblyWorkbench" in Gui.listWorkbenches():
            Gui.activateWorkbench("AssemblyWorkbench")
            Gui.activateWorkbench("PartDesignWorkbench")
            pump()
        self.editSketch()
        pump(0.5)
        self.assertNoClashes("sketch edit")
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge1")
        offset = Gui.Command.get("Sketcher_Offset").getAction()
        self.assertTrue(waitFor(lambda: all(a.isEnabled() for a in offset)), "Offset stays off")
        pump(0.5)
        self.assertNoClashes("sketch edit, an edge selected")

    # --- Select other on backtick (PR C)

    def viewportPoint(self, point):
        """The widget position in the 3D view's viewport where the world point shows."""
        view = Gui.getDocument(self.doc.Name).ActiveView
        viewport = view.graphicsView().viewport()
        x, y = view.getPointOnViewport(point)
        _, height = view.getSize()
        scale = viewport.devicePixelRatioF()
        return viewport, QtCore.QPoint(int(round(x / scale)), int(round((height - y - 1) / scale)))

    def cursorOver(self, point):
        """Moves the cursor over the world point (the command opens its list at the cursor).
        Skips where the platform keeps the cursor where it is."""
        viewport, at = self.viewportPoint(point)
        target = viewport.mapToGlobal(at)
        QtGui.QCursor.setPos(target)
        pump(0.1)
        if QtGui.QCursor.pos() != target:
            self.skipTest("the platform doesn't move the cursor")

    def topBand(self):
        """How far (mm, for the 40 mm high cameras here) a point at the centre of the view has to
        move up to show 90 px below its top edge: the fresh test profile docks the Tasks panel as
        an overlay over most of the view, but not its top (a toolbar lies over the top edge in
        sketch edit), and the list opens only where the view itself is under the cursor."""
        _, height = Gui.getDocument(self.doc.Name).ActiveView.getSize()
        return (height / 2 - 90) * 40 / height

    def assertCursorOverTheView(self):
        """The widget under the cursor is the 3D view's own (no panel over it there)."""
        view = Gui.getDocument(self.doc.Name).ActiveView
        viewport = view.graphicsView().viewport()
        under = QtWidgets.QApplication.widgetAt(QtGui.QCursor.pos())
        self.assertTrue(
            under is viewport or (under is not None and viewport.isAncestorOf(under)),
            f"a {under.metaObject().className() if under else None} is over the view here",
        )

    def frontCamera(self, cx=5, cz=5):
        """An orthographic camera 100 mm in front of (cx, 0, cz) looking along +y, 40 mm high,
        with the near and far planes around the model (fitAll can put the near plane inside the
        front box, and a ray pick starts at the near plane)."""
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setCameraType("Orthographic")
        pump(0.2)
        view.setCamera(
            f"""#Inventor V2.1 ascii
OrthographicCamera {{
  viewportMapping ADJUST_CAMERA
  position {cx} -100 {cz}
  orientation 1 0 0  1.5707964
  nearDistance 10
  farDistance 300
  aspectRatio 1
  focalDistance 100
  height 40
}}
"""
        )
        pump(0.3)
        return view

    def stack(self):
        """Two 10 mm boxes one behind the other, seen from the front (along +y) with an
        orthographic camera, the body hidden: BoxA's faces at y = 0 and 10, BoxB's at 30 and 40,
        all under a cursor over (5, 0, 5)."""
        for name in (self.body.Name, self.sketch.Name):
            Gui.getDocument(self.doc.Name).getObject(name).Visibility = False
        a = self.doc.addObject("Part::Box", "BoxA")
        b = self.doc.addObject("Part::Box", "BoxB")
        b.Placement.Base = App.Vector(0, 30, 0)
        self.doc.recompute()
        view = self.frontCamera()
        self.cursorOver(App.Vector(5, 0, 5))
        # a ray through the cursor must meet all four faces, or the 3D view doesn't pick here
        if len(view.getObjectsInfo(view.getPointOnViewport(App.Vector(5, 0, 5)), 1) or []) < 4:
            self.skipTest("the 3D view doesn't pick here (off screen without OpenGL)")
        return a, b

    def selectOtherList(self):
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is not None and popup.objectName() == "SelectOtherMenu":
            return popup
        return None

    def openSelectOther(self):
        """Presses backtick over the cursor's position; returns the list that opens."""
        with self.watching("Std_SelectOther") as fired:
            self.pressFor(QtCore.Qt.Key_QuoteLeft, QtCore.Qt.NoModifier, "Std_SelectOther")
        self.assertEqual(fired, ["Std_SelectOther"])
        self.assertTrue(waitFor(lambda: self.selectOtherList() is not None), "no list opened")
        return self.selectOtherList()

    def listKey(self, key, modifiers=QtCore.Qt.NoModifier):
        """A key as the window system delivers it while the list is open."""
        QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), key, modifiers)
        pump(0.15)

    def preselectedY(self):
        """The y of the preselected element's centre (the boxes lie along y), None for none."""
        presel = Gui.Selection.getPreselection()
        if not presel.ObjectName:
            return None
        shape = self.doc.getObject(presel.ObjectName).Shape
        return round(shape.getElement(presel.SubElementNames[0].split(".")[-1]).CenterOfMass.y, 6)

    def selectedElements(self):
        return [
            (s.ObjectName, sub)
            for s in Gui.Selection.getSelectionEx(self.doc.Name)
            for sub in s.SubElementNames
        ]

    def testStdSelectOtherIsOnBacktick(self):
        """Std_SelectOther has the backtick, as Onshape's select other; Std_ClarifySelection keeps
        none (the context menu and long-press) and FreeCAD's keymap has it the other way round."""
        self.assertTrue(same(shortcut("Std_SelectOther"), "`"), shortcut("Std_SelectOther"))
        self.assertEqual(shortcut("Std_ClarifySelection"), "")
        setKeymap("FreeCAD")
        self.assertEqual(shortcut("Std_SelectOther"), "")
        self.assertTrue(same(shortcut("Std_ClarifySelection"), "`"))

    def testSelectOtherListsTheElementsUnderTheCursorNearestFirst(self):
        """Over the front face of BoxA, the list holds the four faces the ray meets, in depth
        order, the first preselected; nothing is selected."""
        a, b = self.stack()
        popup = self.openSelectOther()
        self.assertEqual(popup.actions().__len__(), 4, [x.text() for x in popup.actions()])
        self.assertIn("BoxA", popup.actions()[0].text())
        self.assertIn("BoxB", popup.actions()[3].text())
        self.assertEqual(self.preselectedY(), 0.0)
        self.assertEqual(popup.activeAction(), popup.actions()[0])
        self.assertEqual(self.selectedElements(), [])
        self.listKey(QtCore.Qt.Key_Escape)

    def testBacktickStepsThroughTheListWithoutSelecting(self):
        """Backtick and Down go on, Shift+backtick and Up go back, both wrapping; each step only
        preselects, and the window shortcut doesn't open a second list."""
        self.stack()
        self.openSelectOther()
        steps = [
            (QtCore.Qt.Key_QuoteLeft, QtCore.Qt.NoModifier, 10.0),
            (QtCore.Qt.Key_QuoteLeft, QtCore.Qt.NoModifier, 30.0),
            (QtCore.Qt.Key_QuoteLeft, QtCore.Qt.ShiftModifier, 10.0),
            (QtCore.Qt.Key_Down, QtCore.Qt.NoModifier, 30.0),
            (QtCore.Qt.Key_Up, QtCore.Qt.NoModifier, 10.0),
            (QtCore.Qt.Key_AsciiTilde, QtCore.Qt.ShiftModifier, 0.0),
            (QtCore.Qt.Key_QuoteLeft, QtCore.Qt.ShiftModifier, 40.0),  # back from the first
            (QtCore.Qt.Key_QuoteLeft, QtCore.Qt.NoModifier, 0.0),  # on from the last
        ]
        with self.watching("Std_SelectOther") as again:
            for key, modifiers, expected in steps:
                self.listKey(key, modifiers)
                self.assertIsNotNone(self.selectOtherList(), "the list closed")
                self.assertEqual(self.preselectedY(), expected, (key, modifiers))
                self.assertEqual(self.selectedElements(), [])
        self.assertEqual(again, [], "a key of the list ran the command again")
        self.listKey(QtCore.Qt.Key_Escape)

    def testEnterSelectsTheCurrentEntryOnce(self):
        """Enter makes one pick of the current element and closes the list."""
        a, b = self.stack()
        self.openSelectOther()
        self.listKey(QtCore.Qt.Key_QuoteLeft)
        self.listKey(QtCore.Qt.Key_QuoteLeft)
        self.assertEqual(self.preselectedY(), 30.0)
        self.listKey(QtCore.Qt.Key_Return)
        self.assertTrue(waitFor(lambda: self.selectOtherList() is None), "the list stays open")
        picked = self.selectedElements()
        self.assertEqual(len(picked), 1, picked)
        name, sub = picked[0]
        self.assertEqual(name, b.Name)
        self.assertEqual(round(b.Shape.getElement(sub.split(".")[-1]).CenterOfMass.y, 6), 30.0)
        self.assertIsNone(self.preselectedY())

    def testClickOnAnEntrySelectsIt(self):
        """A click on an entry picks that element."""
        a, b = self.stack()
        popup = self.openSelectOther()
        action = popup.actions()[3]
        QtTest.QTest.mouseClick(
            popup, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, popup.actionGeometry(action).center()
        )
        self.assertTrue(waitFor(lambda: self.selectOtherList() is None), "the list stays open")
        picked = self.selectedElements()
        self.assertEqual(len(picked), 1, picked)
        self.assertEqual(picked[0][0], b.Name)
        self.assertEqual(
            round(b.Shape.getElement(picked[0][1].split(".")[-1]).CenterOfMass.y, 6), 40.0
        )

    def filletScene(self):
        """The body with a 10 mm AdditiveBox seen from the front, orthographic, and a new
        fillet's dialog open with its edge field armed. Returns (fillet, field)."""
        for name in (self.body.Name, self.sketch.Name):
            Gui.getDocument(self.doc.Name).getObject(name).Visibility = True
        box = self.doc.addObject("PartDesign::AdditiveBox", "Box")
        self.body.addObject(box)
        for prop in ("Length", "Width", "Height"):
            setattr(box, prop, 10)
        self.doc.recompute()
        self.sketch.Visibility = False
        # the box in the top band, clear of the Fillet panel
        self.frontCamera(cz=5 - self.topBand())
        Gui.Selection.clearSelection()
        Gui.runCommand("PartDesign_Fillet")

        def fields():
            return [
                w
                for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget)
                if w.property("armed") is not None and w.isVisible()
            ]

        self.assertTrue(waitFor(lambda: len(fields()) == 1), "the fillet's reference field")
        pump(0.3)
        field = fields()[0]
        self.assertTrue(waitFor(lambda: bool(field.property("armed"))), "not armed")
        fillet = self.doc.getObject("Fillet")
        self.assertEqual(fillet.Base[1], [])
        return fillet, field

    def testEscClosesTheListAndTheArmedFieldStaysArmed(self):
        """Esc closes the list: no selection, no preselection left, and its release doesn't
        reach the 3D view to disarm the field or cancel the Fillet panel."""
        fillet, field = self.filletScene()
        self.cursorOver(App.Vector(5, 0, 5))
        self.assertCursorOverTheView()
        self.openSelectOther()
        self.listKey(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: self.selectOtherList() is None), "the list stays open")
        pump(0.3)
        self.assertEqual(self.selectedElements(), [])
        self.assertIsNone(self.preselectedY())
        self.assertTrue(Gui.Control.activeDialog(), "the Esc release closed the task panel")
        self.assertTrue(field.property("armed"), "the Esc release disarmed the field")
        self.assertEqual(fillet.Base[1], [])

    def testMouseLeavingTheListClosesIt(self):
        """The mouse moving away from the list closes it and changes nothing."""
        self.stack()
        popup = self.openSelectOther()
        QtTest.QTest.mouseMove(popup, QtCore.QPoint(-300, -300))
        self.assertTrue(waitFor(lambda: self.selectOtherList() is None), "the list stays open")
        self.assertEqual(self.selectedElements(), [])
        self.assertIsNone(self.preselectedY())

    def testSelectOtherLeavesOutWhatTheFilterRefuses(self):
        """With the edge filter on, every face under the cursor is refused, so the list is empty
        and nothing opens; without the filter the same position lists the four faces. (Off
        screen the 3D view picks no edges, so a list of the edges that remain can't be
        shown.)"""
        self.stack()
        Gui.runCommand("Part_SelectFilter", 1)  # edges
        pump(0.1)
        with self.watching("Std_SelectOther") as fired:
            self.press(QtCore.Qt.Key_QuoteLeft)
            self.assertTrue(waitFor(lambda: fired), "the command didn't run")
        pump(0.4)
        self.assertIsNone(self.selectOtherList(), "a list of refused faces opened")
        Gui.runCommand("Part_SelectFilter", 3)  # none
        pump(0.1)
        popup = self.openSelectOther()
        self.assertEqual(len(popup.actions()), 4)
        self.listKey(QtCore.Qt.Key_Escape)

    def testBacktickTypesInAFieldAndOpensNothing(self):
        """With the focus in a line edit the backtick is typed, not a command."""
        self.stack()
        edit = QtWidgets.QLineEdit(Gui.getMainWindow())
        edit.setGeometry(0, 0, 100, 24)
        edit.show()
        try:
            self.assertTrue(focus(edit), "the field doesn't take the focus")
            with self.watching("Std_SelectOther") as fired:
                QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_QuoteLeft)
                pump(0.4)
            self.assertEqual(fired, [])
            self.assertIsNone(self.selectOtherList())
            self.assertEqual(edit.text(), "`")
        finally:
            edit.deleteLater()
            pump(0.1)

    def testSelectOtherDoesNothingWithTheCursorOutsideTheView(self):
        """With the cursor over the model tree, backtick opens no list."""
        self.stack()
        tree = next(
            w
            for w in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget)
            if w.metaObject().className() == "Gui::TreeWidget" and w.isVisible()
        )
        target = tree.mapToGlobal(tree.rect().center())
        QtGui.QCursor.setPos(target)
        pump(0.1)
        if QtGui.QCursor.pos() != target:
            self.skipTest("the platform doesn't move the cursor")
        with self.watching("Std_SelectOther") as fired:
            self.press(QtCore.Qt.Key_QuoteLeft)
            self.assertTrue(waitFor(lambda: fired), "the command didn't run")
        pump(0.3)
        self.assertIsNone(self.selectOtherList())

    def testPreselectionClearedLateComesBack(self):
        """The 3D view clears a preselection on its next mouse event, which can come well after
        the list opened (a slow machine): the current entry is preselected again while the list
        is open (ops#217, PR 189 review finding 3)."""
        self.stack()
        self.openSelectOther()
        pump(0.5)  # later than any fixed delay
        self.assertEqual(self.preselectedY(), 0.0)
        Gui.Selection.clearPreselection()
        self.assertTrue(
            waitFor(lambda: self.preselectedY() == 0.0),
            "the current entry's preselection stays gone",
        )
        self.assertIsNotNone(self.selectOtherList(), "the list closed")
        self.listKey(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: self.selectOtherList() is None), "the list stays open")
        self.assertIsNone(self.preselectedY())

    def testClickOutsideTheListSelectsNothing(self):
        """A click just outside the list, over the front box, closes the list and changes
        nothing: it isn't passed on to the 3D view (ops#217, PR 189 review finding 4). Off screen
        Qt doesn't replay such a click with or without the attribute that stops it, so the test
        also checks the attribute (PR 197 review finding 5)."""
        self.stack()
        popup = self.openSelectOther()
        self.assertTrue(popup.testAttribute(QtCore.Qt.WA_NoMouseReplay))
        outside = popup.geometry().topLeft() - QtCore.QPoint(8, 8)
        window = Gui.getMainWindow()
        at = window.mapFromGlobal(outside)
        QtTest.QTest.mouseClick(window.windowHandle(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, at)
        self.assertTrue(waitFor(lambda: self.selectOtherList() is None), "the list stays open")
        pump(0.3)
        self.assertEqual(self.selectedElements(), [], "the click outside selected in the 3D view")

    def testSelectOtherDoesNothingOverATaskPanelOverlay(self):
        """With the cursor over a task panel docked as an overlay over the 3D view (its content,
        where the panel keeps the mouse), backtick opens no list: a click there wouldn't reach
        the view either (PR 197 review finding 2). The box lies under the panel there: with the
        panel hidden, the same spot opens a list (PR 198 review finding 3)."""
        self.filletScene()
        view = Gui.getDocument(self.doc.Name).ActiveView
        viewport = view.graphicsView().viewport()
        taskView = Gui.getMainWindow().findChild(QtWidgets.QWidget, "Tasks")
        # a point of the view where the panel's content lies
        spot = None
        for fy in (0.5, 0.6, 0.7, 0.4):
            for fx in (0.5, 0.6, 0.7, 0.8):
                target = viewport.mapToGlobal(
                    QtCore.QPoint(int(viewport.width() * fx), int(viewport.height() * fy))
                )
                under = QtWidgets.QApplication.widgetAt(target)
                if under is not None and taskView is not None and taskView.isAncestorOf(under):
                    if under.metaObject().className() not in ("QWidget", "QScrollArea"):
                        spot = target
                        break
            if spot is not None:
                break
        if spot is None:
            self.skipTest("no task panel overlay over the view here")
        # the box's front face under the spot: move the camera so that (5, 0, 5) shows there
        local = viewport.mapFromGlobal(spot)
        _, height = view.getSize()
        scale = viewport.devicePixelRatioF()
        pixel = (int(local.x() * scale), int(height - 1 - local.y() * scale))
        there = view.getPoint(*pixel)
        self.frontCamera(cx=5 + 5 - there.x, cz=5 - self.topBand() + 5 - there.z)
        if not view.getObjectsInfo(pixel, 1):
            self.skipTest("the 3D view doesn't pick here (off screen without OpenGL)")
        QtGui.QCursor.setPos(spot)
        pump(0.1)
        if QtGui.QCursor.pos() != spot:
            self.skipTest("the platform doesn't move the cursor")
        with self.watching("Std_SelectOther") as fired:
            self.press(QtCore.Qt.Key_QuoteLeft)
            self.assertTrue(waitFor(lambda: fired), "the command didn't run")
        pump(0.3)
        self.assertIsNone(self.selectOtherList(), "a list opened under the task panel")
        # the overlays over the spot hidden (the Tasks panel's, and any other docked there): the
        # view is under the cursor, and the list opens
        hidden = []
        try:
            for _ in range(4):
                under = QtWidgets.QApplication.widgetAt(spot)
                if under is viewport or (under is not None and viewport.isAncestorOf(under)):
                    break
                chain, overlay = [], under
                while overlay is not None:
                    chain.append(overlay.metaObject().className())
                    if chain[-1] == "Gui::OverlayTabWidget":
                        break
                    overlay = overlay.parentWidget()
                self.assertIsNotNone(overlay, f"no overlay over the view here: {chain}")
                overlay.hide()
                hidden.append(overlay)
                pump(0.2)
            self.assertCursorOverTheView()
            self.openSelectOther()
        finally:
            for overlay in hidden:
                overlay.show()
            pump(0.2)

    def testSelectOtherDoesNothingUnderAWindowOverTheView(self):
        """With the cursor over a window in front of the 3D view (a floating panel), backtick
        opens no list (ops#217, PR 189 review finding 5)."""
        self.stack()
        cursor = QtGui.QCursor.pos()
        panel = QtWidgets.QWidget(Gui.getMainWindow(), QtCore.Qt.Tool)
        panel.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        panel.setGeometry(QtCore.QRect(cursor - QtCore.QPoint(50, 50), QtCore.QSize(100, 100)))
        panel.show()
        try:
            self.assertTrue(waitFor(lambda: panel.isVisible()))
            pump(0.1)
            if QtWidgets.QApplication.widgetAt(cursor) is not panel:
                self.skipTest("the platform doesn't put the window under the cursor")
            with self.watching("Std_SelectOther") as fired:
                self.press(QtCore.Qt.Key_QuoteLeft)
                self.assertTrue(waitFor(lambda: fired), "the command didn't run")
            pump(0.3)
            self.assertIsNone(self.selectOtherList(), "a list opened under the window")
        finally:
            panel.close()
            panel.deleteLater()
            pump(0.1)

    # --- Select other in sketch edit (PR E)

    def sketchInEdit(self, lines=(), points=(), inBody=False, offset=(0, 0)):
        """A sketch in the XY plane with the given lines ((x1, y1), (x2, y2)) and points, in edit,
        seen from the top by an orthographic camera 40 mm high, with (10, 5) in the top band of
        the view. Its edges are Edge1, Edge2, ... in the order given; the points' vertices follow
        the lines' ends. With `inBody` the sketch is the body's, the body moved by `offset` (x,
        y), and the edit entered through the body (a subname), as the tree does; the camera
        follows the offset."""
        if inBody:
            self.body.Placement.Base = App.Vector(offset[0], offset[1], 0)
            sketch = self.body.newObject("Sketcher::SketchObject", "SketchE")
        else:
            sketch = self.doc.addObject("Sketcher::SketchObject", "SketchE")
        for (ax, ay), (bx, by) in lines:
            sketch.addGeometry(Part.LineSegment(App.Vector(ax, ay, 0), App.Vector(bx, by, 0)))
        for x, y in points:
            sketch.addGeometry(Part.Point(App.Vector(x, y, 0)))
        self.doc.recompute()
        if inBody:
            Gui.ActiveDocument.setEdit(self.body.Name, 0, sketch.Name + ".")
        else:
            Gui.ActiveDocument.setEdit(sketch.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setCameraType("Orthographic")
        pump(0.2)
        view.setCamera(
            f"""#Inventor V2.1 ascii
OrthographicCamera {{
  viewportMapping ADJUST_CAMERA
  position {10 + offset[0]} {5 + offset[1] - self.topBand()} 100
  orientation 0 0 1  0
  nearDistance 10
  farDistance 300
  aspectRatio 1
  focalDistance 100
  height 40
}}
"""
        )
        pump(0.3)
        return sketch

    def cursorOverSketch(self, point):
        self.cursorOver(point)
        self.assertCursorOverTheView()

    def entries(self, popup):
        """The list's element names, in order ("Edge1 · SketchE" -> "Edge1")."""
        return [action.text().split(" ")[0] for action in popup.actions()]

    def preselectedName(self):
        """The preselected element's name (the sketch's preselection carries the path to it)."""
        presel = Gui.Selection.getPreselection()
        if not presel.ObjectName or not presel.SubElementNames:
            return None
        return presel.SubElementNames[0].split(".")[-1]

    def selectedNames(self):
        return [sub.split(".")[-1] for _, sub in self.selectedElements()]

    def testSelectOtherInSketchListsBothOverlappingLines(self):
        """Two overlapping lines in sketch edit: the list holds both, the first preselected;
        backtick preselects the other and selects nothing, Enter selects it and the sketch stays
        in edit."""
        self.overlappingLines()

    def testSelectOtherInABodysSketchListsBothOverlappingLines(self):
        """The same in a sketch of the body, its edit entered through the body (PR 198 review
        finding 2: the sketch's own hover lookup found no view for a sketch in a body)."""
        self.overlappingLines(inBody=True)

    def testSelectOtherInAMovedBodysSketchListsBothOverlappingLines(self):
        """The same with the body moved away from the origin."""
        self.overlappingLines(inBody=True, offset=(30, -20))

    def overlappingLines(self, inBody=False, offset=(0, 0)):
        import SketcherGui

        self.sketchInEdit(
            lines=[((0, 5), (20, 5)), ((5, 5), (15, 5))], inBody=inBody, offset=offset
        )
        at = App.Vector(10 + offset[0], 5 + offset[1], 0)
        # the sketch's own hover picks a line there
        view = Gui.getDocument(self.doc.Name).ActiveView
        info = SketcherGui.getActiveSketchPreselection(view.getPointOnViewport(at)) or {}
        self.assertIn(
            (info.get("SubElementNames") or [None])[0],
            ("Edge1", "Edge2"),
            "the sketch's hover picks no line",
        )
        self.cursorOverSketch(at)
        popup = self.openSelectOther()
        names = self.entries(popup)
        self.assertEqual(sorted(names), ["Edge1", "Edge2"], names)
        self.assertTrue(waitFor(lambda: self.preselectedName() == names[0]), self.preselectedName())
        self.listKey(QtCore.Qt.Key_QuoteLeft)
        self.assertTrue(waitFor(lambda: self.preselectedName() == names[1]), self.preselectedName())
        self.assertEqual(self.selectedNames(), [])
        self.listKey(QtCore.Qt.Key_Return)
        self.assertTrue(waitFor(lambda: self.selectOtherList() is None), "the list stays open")
        self.assertTrue(waitFor(lambda: self.selectedNames() == [names[1]]), self.selectedNames())
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit(), "the sketch left the edit")

    def testSelectOtherInSketchPutsTheVertexBeforeTheLine(self):
        """A point on a line: the vertex comes first, as a hover picks it, then the line; Enter on
        the line selects the line only."""
        self.sketchInEdit(lines=[((0, 5), (20, 5))], points=[(10, 5)])
        self.cursorOverSketch(App.Vector(10, 5, 0))
        popup = self.openSelectOther()
        self.assertEqual(self.entries(popup), ["Vertex3", "Edge1"])
        self.assertTrue(
            waitFor(lambda: self.preselectedName() == "Vertex3"), self.preselectedName()
        )
        self.listKey(QtCore.Qt.Key_Down)
        self.assertTrue(waitFor(lambda: self.preselectedName() == "Edge1"), self.preselectedName())
        self.listKey(QtCore.Qt.Key_Return)
        self.assertTrue(waitFor(lambda: self.selectedNames() == ["Edge1"]), self.selectedNames())

    def iconPixels(self, name, around, span=40):
        """The viewport points (Coin's, y up) near the world point `around` where the sketch's
        hover picks the constraint `name`."""
        import SketcherGui

        view = Gui.getDocument(self.doc.Name).ActiveView
        x0, y0 = (int(v) for v in view.getPointOnViewport(around))
        found = []
        for dy in range(-span, span + 1, 2):
            for dx in range(-span, span + 1, 2):
                info = SketcherGui.getActiveSketchPreselection((x0 + dx, y0 + dy)) or {}
                if name in (info.get("SubElementNames") or []):
                    found.append((x0 + dx, y0 + dy))
        return found

    def cursorAtPixel(self, x, y):
        """Moves the cursor to the viewport point (Coin's, y up)."""
        view = Gui.getDocument(self.doc.Name).ActiveView
        viewport = view.graphicsView().viewport()
        _, height = view.getSize()
        scale = viewport.devicePixelRatioF()
        target = viewport.mapToGlobal(
            QtCore.QPoint(int(round(x / scale)), int(round((height - y - 1) / scale)))
        )
        QtGui.QCursor.setPos(target)
        pump(0.1)
        if QtGui.QCursor.pos() != target:
            self.skipTest("the platform doesn't move the cursor")
        self.assertCursorOverTheView()

    def testSelectOtherInSketchListsAConstraintIconAndTheLineUnderIt(self):
        """A constraint icon over a line: the icon of the first line's Horizontal constraint, and
        a second, vertical line drawn through it. The constraint comes first (a hover picks the
        icon), the line under it is listed too and Enter on it selects it."""
        import Sketcher

        sketch = self.sketchInEdit(lines=[((0, 5), (20, 5))])
        sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.doc.recompute()
        pump(0.3)
        view = Gui.getDocument(self.doc.Name).ActiveView
        hits = self.iconPixels("Constraint1", App.Vector(10, 5, 0))
        self.assertTrue(hits, "the constraint's icon isn't under any probe")
        cx = sum(x for x, _ in hits) // len(hits)
        cy = sum(y for _, y in hits) // len(hits)
        through = view.getPoint(cx, cy)
        sketch.addGeometry(
            Part.LineSegment(
                App.Vector(through.x, through.y - 8, 0), App.Vector(through.x, through.y + 8, 0)
            )
        )
        self.doc.recompute()
        pump(0.3)
        # the icon again (a redraw can move it a little), at its pixel nearest the new line
        lineX = view.getPointOnViewport(App.Vector(through.x, through.y, 0))[0]
        hits = []

        def iconBack():
            hits.extend(self.iconPixels("Constraint1", App.Vector(10, 5, 0)))
            return bool(hits)

        self.assertTrue(waitFor(iconBack), "the constraint's icon is gone")
        x, y = min(hits, key=lambda hit: abs(hit[0] - lineX))
        self.assertLessEqual(abs(x - lineX), 2, "the new line doesn't run under the icon")
        self.cursorAtPixel(x, y)
        popup = self.openSelectOther()
        names = self.entries(popup)
        self.assertEqual(names[0], "Constraint1", names)
        self.assertIn("Edge2", names)
        for _ in range(names.index("Edge2")):
            self.listKey(QtCore.Qt.Key_QuoteLeft)
        self.assertTrue(waitFor(lambda: self.preselectedName() == "Edge2"), self.preselectedName())
        self.listKey(QtCore.Qt.Key_Return)
        self.assertTrue(waitFor(lambda: self.selectedNames() == ["Edge2"]), self.selectedNames())

    def testEscClosesTheSketchListAndTheSketchStaysInEdit(self):
        """Esc closes the list in sketch edit: nothing is selected or preselected, and the sketch
        stays in edit (the view ignores the release of an Esc it didn't see pressed)."""
        self.sketchInEdit(lines=[((0, 5), (20, 5)), ((5, 5), (15, 5))])
        self.cursorOverSketch(App.Vector(10, 5, 0))
        self.openSelectOther()
        self.listKey(QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: self.selectOtherList() is None), "the list stays open")
        pump(0.3)
        self.assertEqual(self.selectedNames(), [])
        self.assertIsNone(self.preselectedName())
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit(), "the sketch left the edit")

    def testSelectOtherOpensNothingWhileASketchToolRuns(self):
        """With a sketch tool running (the line tool), backtick opens no list: a click there is
        the tool's."""
        self.sketchInEdit(lines=[((0, 5), (20, 5)), ((5, 5), (15, 5))])
        self.cursorOverSketch(App.Vector(10, 5, 0))
        Gui.runCommand("Sketcher_CreateLine")
        pump(0.3)
        try:
            with self.watching("Std_SelectOther") as fired:
                self.press(QtCore.Qt.Key_QuoteLeft)
                self.assertTrue(waitFor(lambda: fired), "the command didn't run")
            pump(0.3)
            self.assertIsNone(self.selectOtherList(), "a list opened while the line tool runs")
        finally:
            self.escapeTool()

    def testSelectOtherInAnotherDocumentsViewIsThe3DViewsList(self):
        """With a sketch in edit, backtick in another document's 3D view lists what that view
        picks (a box), as without the sketch; it used to list nothing there, the sketch's picker
        claiming the view (PR 198 review finding 1; another view of the sketch's own document was
        safe: Document::getInEdit is empty while that view is active). The other view has the
        sketch's camera, so the sketch's lines would lie under the cursor there too. Back in the
        sketch's view, the same spot gives the sketch's list."""
        self.sketchInEdit(lines=[((0, 5), (20, 5)), ((5, 5), (15, 5))])
        camera = Gui.getDocument(self.doc.Name).ActiveView.getCamera()
        other = App.newDocument("ForkKeymapOther")
        try:
            box = other.addObject("Part::Box", "Box")
            box.Length, box.Width, box.Height = 20, 10, 2
            box.Placement.Base = App.Vector(0, 0, -5)
            other.recompute()
            pump(0.3)
            self.assertIsNotNone(Gui.getDocument(self.doc.Name).getInEdit(), "the edit ended")
            view = Gui.getDocument(other.Name).ActiveView
            view.setCameraType("Orthographic")
            pump(0.2)
            view.setCamera(camera)
            pump(0.3)
            viewport = view.graphicsView().viewport()
            x, y = view.getPointOnViewport(App.Vector(10, 5, -3))
            _, height = view.getSize()
            scale = viewport.devicePixelRatioF()
            target = viewport.mapToGlobal(
                QtCore.QPoint(int(round(x / scale)), int(round((height - y - 1) / scale)))
            )
            QtGui.QCursor.setPos(target)
            pump(0.1)
            if QtGui.QCursor.pos() != target:
                self.skipTest("the platform doesn't move the cursor")
            under = QtWidgets.QApplication.widgetAt(target)
            self.assertTrue(under is viewport or viewport.isAncestorOf(under), "not over the view")
            if not view.getObjectsInfo((x, y), 1):
                self.skipTest("the 3D view doesn't pick here (off screen without OpenGL)")
            popup = self.openSelectOther()
            labels = [action.text() for action in popup.actions()]
            self.assertTrue(labels and all("Box" in label for label in labels), labels)
            self.listKey(QtCore.Qt.Key_Escape)
            self.assertTrue(waitFor(lambda: self.selectOtherList() is None), "the list stays open")
        finally:
            App.closeDocument(other.Name)
            pump(0.3)
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        self.cursorOverSketch(App.Vector(10, 5, 0))
        popup = self.openSelectOther()
        self.assertEqual(sorted(self.entries(popup)), ["Edge1", "Edge2"])

    def testCommitToggleOnceInAnArmedFilletField(self):
        """In a Fillet's armed field a commit toggles the element once, and cycling the list
        toggles nothing. (A face: off screen the 3D view picks no edges.)"""
        fillet, field = self.filletScene()
        self.cursorOver(App.Vector(5, 0, 5))
        self.assertCursorOverTheView()
        self.openSelectOther()
        self.listKey(QtCore.Qt.Key_QuoteLeft)  # the second entry
        sub = Gui.Selection.getPreselection().SubElementNames[0].split(".")[-1]
        self.assertTrue(sub.startswith("Face"), sub)
        self.assertEqual(fillet.Base[1], [], "cycling toggled an element")
        self.listKey(QtCore.Qt.Key_Return)
        self.assertTrue(waitFor(lambda: self.selectOtherList() is None))
        pump(0.3)
        self.assertEqual(fillet.Base[1], [sub])

    # --- the orbit arrows (B2)

    def orbitView(self):
        """The designed view: an orthographic camera in front of (5, 0, 5) looking along +y, up
        +z, right +x. The point is the camera's focal point."""
        view = self.frontCamera()
        self.assertTrue(
            waitFor(lambda: (self.cameraDirection() - App.Vector(0, 1, 0)).Length < 1e-3)
        )
        return view

    def cameraDirection(self):
        """The camera's view direction from its orientation (getViewDirection() reads the view
        volume of the last render, which off screen is stale)."""
        view = Gui.getDocument(self.doc.Name).ActiveView
        d = view.getCameraOrientation().multVec(App.Vector(0, 0, -1))
        return App.Vector(d.x, d.y, d.z)

    def focalOnScreen(self):
        """Where the focal point (5, 0, 5) shows in the viewport."""
        _, at = self.viewportPoint(App.Vector(5, 0, 5))
        return at

    def arrow(self, key, modifiers=QtCore.Qt.NoModifier):
        self.press(key, modifiers)
        pump(0.3)

    def assertDirection(self, expected, message=""):
        self.assertTrue(
            waitFor(lambda: (self.cameraDirection() - expected).Length < 2e-3),
            f"{message}: the view direction is {self.cameraDirection()}, expected {expected}",
        )

    def turned(self, angle, toward):
        """The view direction after turning the designed view's (0, 1, 0) by `angle` degrees
        toward the unit vector `toward`."""
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        return App.Vector(0, 1, 0) * c + toward * s

    LEFT, RIGHT = App.Vector(-1, 0, 0), App.Vector(1, 0, 0)
    UP, DOWN = App.Vector(0, 0, 1), App.Vector(0, 0, -1)
    NONE, CTRL = QtCore.Qt.NoModifier, QtCore.Qt.ControlModifier
    SHIFT = QtCore.Qt.ShiftModifier
    ARROWS = {
        QtCore.Qt.Key_Left: LEFT,
        QtCore.Qt.Key_Right: RIGHT,
        QtCore.Qt.Key_Up: UP,
        QtCore.Qt.Key_Down: DOWN,
    }

    def testArrowsOrbitTheViewByFixedSteps(self):
        """In the 3D view the arrows turn the view direction about the focal point: 15 degrees,
        5 with Ctrl, 90 with Shift; Left turns it toward the left of the screen, Up toward the
        top. The steps are fixed: the navigation cube's step setting (here 7 steps a turn) isn't
        theirs."""
        naviSetting = App.ParamGet("User parameter:BaseApp/Preferences/View")
        oldSteps = naviSetting.GetInt("NaviStepByTurn", 8)
        naviSetting.SetInt("NaviStepByTurn", 7)
        self.addCleanup(naviSetting.SetInt, "NaviStepByTurn", oldSteps)
        for key, toward in self.ARROWS.items():
            for modifiers, angle in ((self.NONE, 15), (self.CTRL, 5), (self.SHIFT, 90)):
                self.orbitView()
                before = self.focalOnScreen()
                self.arrow(key, modifiers)
                self.assertDirection(self.turned(angle, toward), f"{key} {modifiers} {angle}")
                # about the focal point: it stays where it was on the screen
                after = self.focalOnScreen()
                self.assertLessEqual(abs(after.x() - before.x()) + abs(after.y() - before.y()), 2)

    def testKeypadArrowsOrbitToo(self):
        """Qt reports the arrows of a Mac keyboard (and the keypad's) with KeypadModifier: they
        orbit the same, Shift+Left 90 degrees."""
        self.orbitView()
        self.arrow(QtCore.Qt.Key_Left, QtCore.Qt.KeypadModifier | self.SHIFT)
        self.assertDirection(self.turned(90, self.LEFT), "keypad shift+left")

    def testAnArrowStopsAViewAnimation(self):
        """An arrow during a view animation (a standard view; a sketch's edit entry with
        OrientViewOnEdit on) stops it and turns the camera from where it is, as a mouse drag
        does; the animation used to run on, turning the camera by the rest of its way from where
        the arrow had put it, so the view didn't end where the arrow put it. The animation is slowed
        to 10 s, so that the arrow lands in it."""
        view = self.orbitView()
        viewSettings = App.ParamGet("User parameter:BaseApp/Preferences/View")
        hadDuration = "AnimationDuration" in viewSettings.GetInts()
        oldDuration = viewSettings.GetInt("AnimationDuration", 500)
        animated = view.isAnimationEnabled()
        viewSettings.SetInt("AnimationDuration", 10000)
        view.setAnimationEnabled(True)
        front, top = App.Vector(0, 1, 0), App.Vector(0, 0, -1)
        try:
            view.viewTop()
            self.assertTrue(
                waitFor(lambda: math.degrees(self.cameraDirection().getAngle(front)) > 1),
                "the view animation didn't start",
            )
            before = self.cameraDirection()
            self.assertGreater(math.degrees(before.getAngle(top)), 45, "the animation ran ahead")
            self.press(QtCore.Qt.Key_Left)
            pump(0.1)
            after = self.cameraDirection()
            self.assertAlmostEqual(math.degrees(before.getAngle(after)), 15, delta=1)
            pump(1.0)
            moved = math.degrees(after.getAngle(self.cameraDirection()))
            self.assertLess(moved, 0.1, "the animation went on after the arrow")
        finally:
            view.stopAnimating()
            view.setAnimationEnabled(animated)
            if hadDuration:
                viewSettings.SetInt("AnimationDuration", oldDuration)
            else:
                viewSettings.RemInt("AnimationDuration")

    def testARefusedArrowLeavesAViewAnimationRunning(self):
        """With rotation off (the navigation style's setRotationEnabled), an arrow doesn't turn
        the view, and a running view animation goes on to its end: the arrow used to stop it
        before the turn was refused, which froze the view half way (PR 195 verification)."""
        view = self.orbitView()
        navigation = view.getViewer().getNavigationStyle()
        viewSettings = App.ParamGet("User parameter:BaseApp/Preferences/View")
        hadDuration = "AnimationDuration" in viewSettings.GetInts()
        oldDuration = viewSettings.GetInt("AnimationDuration", 500)
        animated = view.isAnimationEnabled()
        viewSettings.SetInt("AnimationDuration", 3000)
        view.setAnimationEnabled(True)
        front, top = App.Vector(0, 1, 0), App.Vector(0, 0, -1)
        navigation.setRotationEnabled(False)
        try:
            view.viewTop()
            self.assertTrue(
                waitFor(lambda: math.degrees(self.cameraDirection().getAngle(front)) > 1),
                "the view animation didn't start",
            )
            self.assertGreater(
                math.degrees(self.cameraDirection().getAngle(top)), 30, "the animation ran ahead"
            )
            self.press(QtCore.Qt.Key_Left)
            self.assertTrue(
                waitFor(lambda: math.degrees(self.cameraDirection().getAngle(top)) < 0.5, 6),
                "the animation stopped short of the top view",
            )
        finally:
            navigation.setRotationEnabled(True)
            view.stopAnimating()
            view.setAnimationEnabled(animated)
            if hadDuration:
                viewSettings.SetInt("AnimationDuration", oldDuration)
            else:
                viewSettings.RemInt("AnimationDuration")

    def testArrowsDoNotOrbitDuringABoxSelection(self):
        """While a box selection (Std_BoxSelection) waits for its box, its mouse model takes the
        keys, as before the orbit: an arrow leaves the camera alone; once the box is done, the
        arrows orbit again."""
        self.orbitView()
        self.assertTrue(focus(self.view3d()), "the 3D view doesn't take the focus")
        Gui.runCommand("Std_BoxSelection")
        pump(0.2)
        self.arrow(QtCore.Qt.Key_Left)
        pump(0.3)
        self.assertLess(
            math.degrees(self.cameraDirection().getAngle(App.Vector(0, 1, 0))),
            0.1,
            "an arrow turned the view during a box selection",
        )
        # the rubber band ends only on a click (Esc is no key of its): an empty corner
        viewport = Gui.getDocument(self.doc.Name).ActiveView.graphicsView().viewport()
        QtTest.QTest.mouseClick(
            viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, QtCore.QPoint(3, 3)
        )
        pump(0.2)
        Gui.Selection.clearSelection()
        self.arrow(QtCore.Qt.Key_Left)
        self.assertDirection(self.turned(15, self.LEFT), "left after the box")

    def testShiftArrowsDoNotRunTheViewRotateCommands(self):
        """Shift+Left / Right are the orbit's 90 degrees, not Std_ViewRotateLeft / Right (the
        roll about the view direction), whose window shortcuts the table clears."""
        self.orbitView()
        with self.watching("Std_ViewRotateLeft", "Std_ViewRotateRight") as fired:
            self.arrow(QtCore.Qt.Key_Left, self.SHIFT)
            self.arrow(QtCore.Qt.Key_Right, self.SHIFT)
            pump(0.3)
        self.assertEqual(fired, [])
        self.assertDirection(App.Vector(0, 1, 0), "left 90, right 90")
        for name in ("Std_ViewRotateLeft", "Std_ViewRotateRight"):
            self.assertEqual(shortcut(name), "", name)

    def testCtrlShiftArrowsPanAndCtrlArrowsAreNoOverlayToggles(self):
        """Ctrl+Shift+arrows move the camera without turning it, as the plain arrows do under
        FreeCAD's keymap. Ctrl+arrows are the 5 degree orbit: the dock overlay's toggles lose
        them."""
        self.orbitView()
        before = self.focalOnScreen()
        with self.watching(
            "Std_DockOverlayToggleLeft",
            "Std_DockOverlayToggleRight",
            "Std_DockOverlayToggleTop",
            "Std_DockOverlayToggleBottom",
        ) as fired:
            self.arrow(QtCore.Qt.Key_Left, self.CTRL | self.SHIFT)
            self.assertDirection(App.Vector(0, 1, 0), "ctrl+shift+left")
            moved = self.focalOnScreen()
            self.assertGreater(abs(moved.x() - before.x()), 10, "the camera didn't move")
            self.arrow(QtCore.Qt.Key_Right, self.CTRL)
            self.assertDirection(self.turned(5, self.RIGHT), "ctrl+right")
        self.assertEqual(fired, [])

    def testArrowsPanUnderFreeCADsKeymap(self):
        """The default keymap is unchanged: the arrows move the camera without turning it,
        Shift+Left is Std_ViewRotateLeft and Ctrl+Left the dock overlay's toggle."""
        setKeymap("FreeCAD")
        pump(0.2)
        self.orbitView()
        before = self.focalOnScreen()
        self.arrow(QtCore.Qt.Key_Left)
        self.assertDirection(App.Vector(0, 1, 0), "left")
        self.assertGreater(abs(self.focalOnScreen().x() - before.x()), 10)
        with self.watching("Std_ViewRotateLeft") as fired:
            self.press(QtCore.Qt.Key_Left, self.SHIFT)
            self.assertTrue(waitFor(lambda: fired), "Shift+Left didn't run Std_ViewRotateLeft")
        self.assertEqual(shortcut("Std_DockOverlayToggleLeft"), "Ctrl+Left")

    def testArrowsOrbitInSketchEditToo(self):
        """Sketch edit has no arrow handling of its own (the viewer panned on them before the
        sketch saw a key): the arrows orbit there too, the sketch stays in edit, and its other
        keys still reach its tools."""
        self.editSketch()
        # with OrientViewOnEdit on (off by default) the edit entry turns the view to the sketch
        # with an animation: read the camera after it
        self.assertDirection(App.Vector(0, 0, -1), "the sketch's view")
        pump(0.3)
        before = self.cameraDirection()
        self.arrow(QtCore.Qt.Key_Left)
        after = self.cameraDirection()
        self.assertAlmostEqual(math.degrees(before.getAngle(after)), 15, delta=0.1)
        self.arrow(QtCore.Qt.Key_Right)
        self.assertDirection(before, "left, then right")
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit())
        with self.watching("Sketcher_CreateFillet") as fired:
            self.press(QtCore.Qt.Key_F, self.SHIFT)
            self.assertTrue(waitFor(lambda: fired), "the sketch's Shift+F")
        self.escapeTool()

    def testArrowsStayWithTheTreeAndATaskPanelList(self):
        """With the focus in the model tree or in a list of a task panel, the arrows move the
        current item and leave the camera alone."""
        self.orbitView()
        direction = self.cameraDirection()
        window = Gui.getMainWindow().windowHandle()
        tree = self.modelTree()
        tree.expandAll()
        pump(0.2)
        first = tree.topLevelItem(0)
        tree.setCurrentItem(first)
        pump(0.1)
        self.assertTrue(focus(tree), "the tree doesn't take the focus")
        QtTest.QTest.keyClick(window, QtCore.Qt.Key_Down)
        pump(0.3)
        self.assertIsNot(tree.currentItem(), first)
        self.assertDirection(direction, "tree")

        class ListPanel:
            def __init__(self):
                self.list = QtWidgets.QListWidget()
                self.list.addItems(["one", "two", "three"])
                self.form = self.list

            def getStandardButtons(self):
                return int(QtWidgets.QDialogButtonBox.Close)

            def reject(self):
                Gui.Control.closeDialog()

        panel = ListPanel()
        Gui.Control.showDialog(panel)
        pump(0.3)
        panel.list.setCurrentRow(0)
        self.assertTrue(focus(panel.list), "the list doesn't take the focus")
        QtTest.QTest.keyClick(window, QtCore.Qt.Key_Down)
        pump(0.3)
        self.assertEqual(panel.list.currentRow(), 1)
        self.assertDirection(direction, "task panel list")


if __name__ == "__main__":
    unittest.main()
