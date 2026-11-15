# SPDX-License-Identifier: LGPL-2.1-or-later
# /**************************************************************************
#                                                                           *
#    This file is part of FreeCAD.                                          *
#                                                                           *
#    FreeCAD is free software: you can redistribute it and/or modify it     *
#    under the terms of the GNU Lesser General Public License as            *
#    published by the Free Software Foundation, either version 2.1 of the   *
#    License, or (at your option) any later version.                        *
#                                                                           *
#    FreeCAD is distributed in the hope that it will be useful, but         *
#    WITHOUT ANY WARRANTY; without even the implied warranty of             *
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
#    Lesser General Public License for more details.                        *
#                                                                           *
#    You should have received a copy of the GNU Lesser General Public       *
#    License along with FreeCAD. If not, see                                *
#    <https://www.gnu.org/licenses/>.                                       *
#                                                                           *
# **************************************************************************/

"""Show mates mode (FreeCAD-CH, ops#640 gaps3 row 8; Onshape's h, oracle 24 G3-7, fact UI1).

Onshape: h toggles "Show mates mode", off by default. While it is on, hovering over or selecting
an instance shows that instance's mates; with it off, hovering shows nothing. Here, while the
mode is on, the joints of the active assembly are hidden except those of the instances under the
cursor or selected; turning it off (or the assembly leaving edit) gives every joint back its own
visibility."""

import FreeCAD as App

from PySide.QtCore import QT_TRANSLATE_NOOP

if App.GuiUp:
    import FreeCADGui as Gui

import UtilsAssembly

__title__ = "Assembly Command Show Mates Mode"
__url__ = "https://www.freecad.org"

COMMAND = "Assembly_ToggleShowMatesMode"

_mode = None  # the ShowMates of the assembly the mode is on in, or None


def isShowMatesModeOn():
    return _mode is not None


def activeMode():
    """The ShowMates while the mode is on (for the tests), else None."""
    return _mode


def setShowMatesMode(on):
    """Turns Show mates mode on for the active assembly, or off."""
    global _mode
    if _mode is not None:
        _mode.remove()
        _mode = None
    if on:
        assembly = UtilsAssembly.activeAssembly()
        if assembly is not None:
            _mode = ShowMates(assembly)
    _syncAction()


def _syncAction():
    try:
        actions = Gui.Command.get(COMMAND).getAction()
    except Exception:
        return
    for action in actions:
        if action.isCheckable() and action.isChecked() != isShowMatesModeOn():
            blocked = action.blockSignals(True)
            action.setChecked(isShowMatesModeOn())
            action.blockSignals(blocked)


def _joints(assembly):
    group = UtilsAssembly.getJointGroup(assembly)
    return list(group.Group) if group is not None else []


class ShowMates:
    """The joints' own visibility while the mode is on, and the selection observer."""

    def __init__(self, assembly):
        self.assembly = assembly
        self.docName = assembly.Document.Name
        self.saved = {}
        for joint in _joints(assembly):
            if hasattr(joint, "ViewObject") and joint.ViewObject is not None:
                self.saved[joint.Name] = joint.ViewObject.Visibility
        self.update()
        Gui.Selection.addObserver(self)

    def isCurrent(self):
        doc = App.ActiveDocument
        return doc is not None and doc.Name == self.docName and \
            UtilsAssembly.activeAssembly() == self.assembly

    def remove(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        doc = App.listDocuments().get(self.docName)
        if doc is None:
            return
        for name, shown in self.saved.items():
            joint = doc.getObject(name)
            if joint is not None and joint.ViewObject is not None:
                joint.ViewObject.Visibility = shown

    def instanceOf(self, obj, sub):
        """The assembly's instance an object and a sub path name, or None."""
        if obj is None:
            return None
        if obj == self.assembly and sub:
            first = sub.split(".")[0]
            return self.assembly.Document.getObject(first)
        if obj in self.assembly.Group:
            return obj
        return None

    def jointInstances(self, joint):
        parts = set()
        for prop in ("Reference1", "Reference2"):
            ref = getattr(joint, prop, None)
            if ref and len(ref) == 2:
                subs = ref[1] or [""]
                part = self.instanceOf(ref[0], subs[0])
                if part is not None:
                    parts.add(part.Name)
        grounded = getattr(joint, "ObjectToGround", None)
        if grounded is not None:
            parts.add(grounded.Name)
        return parts

    def focused(self):
        """The instances under the cursor or selected."""
        names = set()
        for sel in Gui.Selection.getSelectionEx("", 0):
            subs = sel.SubElementNames or [""]
            for sub in subs:
                part = self.instanceOf(sel.Object, sub)
                if part is not None:
                    names.add(part.Name)
        # With nothing under the cursor the preselection's object is already deleted
        try:
            pre = Gui.Selection.getPreselection()
            obj = pre.Object if pre is not None else None
            subs = pre.SubElementNames if obj is not None else []
        except RuntimeError:
            obj, subs = None, []
        part = self.instanceOf(obj, (subs or [""])[0])
        if part is not None:
            names.add(part.Name)
        return names

    def update(self):
        doc = App.listDocuments().get(self.docName)
        if doc is None:
            return
        focused = self.focused()
        for joint in _joints(self.assembly):
            if joint.ViewObject is None:
                continue
            shown = bool(focused & self.jointInstances(joint))
            if joint.ViewObject.Visibility != shown:
                joint.ViewObject.Visibility = shown

    # Selection observer
    def addSelection(self, doc, obj, sub, pnt):
        self.update()

    def removeSelection(self, doc, obj, sub):
        self.update()

    def setSelection(self, doc):
        self.update()

    def clearSelection(self, doc):
        self.update()

    def setPreselection(self, doc, obj, sub):
        self.update()

    def removePreselection(self, doc, obj, sub):
        self.update()


class CommandToggleShowMatesMode:
    def GetResources(self):
        return {
            "Pixmap": "Assembly_CreateJointFixed",
            "MenuText": QT_TRANSLATE_NOOP("Assembly_ToggleShowMatesMode", "Show mates mode"),
            "Accel": "H",
            "ToolTip": QT_TRANSLATE_NOOP(
                "Assembly_ToggleShowMatesMode",
                "While on, the mates show only for the instances under the cursor or selected.",
            ),
            "CmdType": "ForEdit",
            "Checkable": False,
        }

    def IsActive(self):
        active = UtilsAssembly.activeAssembly() is not None
        if _mode is not None and not (active and _mode.isCurrent()):
            setShowMatesMode(False)  # the assembly left edit, or the document changed
        return active

    def Activated(self, checked=None):
        setShowMatesMode(not isShowMatesModeOn() if checked is None else bool(checked))


if App.GuiUp:
    Gui.addCommand(COMMAND, CommandToggleShowMatesMode())
