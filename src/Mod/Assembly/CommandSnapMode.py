# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, design C9, notes/assemblies-design.md section 4b): Onshape's Snap mode.
#
# A toggle, Shift+S, off by default and kept nowhere: not in the document, not in the settings
# (GC-S4: Onshape's is off again after a reload). With it off nothing changes (GC-S6). While it is
# on, a drag of a free instance (no mate, not fixed) is this module's: the grab point is the
# connector point of the element picked on the instance (C3's rule: the point under the cursor,
# else the element's centre); under the cursor the connector points of the hovered face or edge of
# another instance are drawn (C3's points); near one, the instance is shown snapped there; on
# release it stays, in one undo step. No mate is made (GC-S1).
#
# The snapped position is the joint dialog's presolve of an unflipped Fastened mate between the
# two points (JointObject.matchJCS: target connector x grabbed connector inverse), so a snap lands
# where that mate would put the instance. Onshape's landing by a hand drag is still open (S1 by
# hand): its synthetic drags turned the box once and missed the corner by 1 mm once.
#
# The pick under the cursor sees through the dragged instance: getObjectsInfo picks every object
# along the ray, and the dragged one is skipped.
#
# Not snapped (the assembly's own drag, as before): an instance with a mate or fixed, and a
# selection of several. Onshape's snap of those is not known (S2 asks about the triad's drags).

import FreeCAD as App

from PySide.QtCore import QT_TRANSLATE_NOOP

if App.GuiUp:
    import FreeCADGui as Gui
    from pivy import coin
    from PySide import QtCore

import UtilsAssembly

translate = App.Qt.translate

__title__ = "Assembly Command Snap Mode"
__url__ = "https://www.freecad.org"

COMMAND = "Assembly_ToggleSnapMode"

_snap = None  # the SnapDrag of the view Snap mode is on in, or None


def isSnapModeOn():
    return _snap is not None


def activeSnap():
    """The SnapDrag while Snap mode is on (for the tests), else None."""
    return _snap


def setSnapMode(on):
    """Turns Snap mode on in the active view, or off."""
    global _snap
    if _snap is not None:
        _snap.remove()
        _snap = None
    if on:
        doc = Gui.ActiveDocument
        view = doc.activeView() if doc else None
        if view is not None and hasattr(view, "addEventCallback"):
            _snap = SnapDrag(view, doc.Document.Name)
    _syncAction()


def _syncAction():
    try:
        actions = Gui.Command.get(COMMAND).getAction()
    except Exception:
        return
    for action in actions:
        if action.isCheckable() and action.isChecked() != isSnapModeOn():
            blocked = action.blockSignals(True)
            action.setChecked(isSnapModeOn())
            action.blockSignals(blocked)


def _jointGroup(assembly):
    for obj in assembly.OutList:
        if obj.TypeId == "Assembly::JointGroup":
            return obj
    return None


def isFreeInstance(assembly, part):
    """True when no mate and no fixing touch part (the instances Snap mode drags)."""
    group = _jointGroup(assembly)
    if group is None:
        return True
    for joint in group.Group:
        if getattr(joint, "Suppressed", False):
            continue
        if getattr(joint, "ObjectToGround", None) == part:
            return False
        for prop in ("Reference1", "Reference2"):
            ref = getattr(joint, prop, None)
            if ref and UtilsAssembly.getMovingPart(ref) == part:
                return False
    return True


if App.GuiUp:

    class _ReleaseFilter(QtCore.QObject):
        """Ends the drag on the left button's release, seen on the viewport itself: the release
        doesn't reach the view's Coin callbacks after a drag over parts (the real-mouse test)."""

        def __init__(self, snap):
            super().__init__()
            self.snap = snap

        def eventFilter(self, watched, event):
            if (
                event.type() == QtCore.QEvent.MouseButtonRelease
                and event.button() == QtCore.Qt.LeftButton
                and self.snap.drag is not None
            ):
                self.snap.release(None)
            return False


class SnapDrag:
    """The event handling and the markers of Snap mode in one 3D view."""

    def __init__(self, view, docName):
        self.view = view
        self.docName = docName
        self.drag = None
        self.cbButton = view.addEventCallback("SoMouseButtonEvent", self.onButton)
        self.cbMove = view.addEventCallback("SoLocation2Event", self.onMove)
        self.markers = self.makeMarkers()
        view.getSceneGraph().addChild(self.markers)
        self.viewport = None
        self.releaseFilter = _ReleaseFilter(self)
        try:
            self.viewport = view.graphicsView().viewport()
            self.viewport.installEventFilter(self.releaseFilter)
        except Exception:
            self.viewport = None

    def remove(self):
        if self.drag is not None:
            self.release(None)
        try:
            self.view.removeEventCallback("SoMouseButtonEvent", self.cbButton)
            self.view.removeEventCallback("SoLocation2Event", self.cbMove)
        except Exception:
            pass  # the view is gone
        try:
            self.view.getSceneGraph().removeChild(self.markers)
        except Exception:
            pass
        try:
            if self.viewport is not None:
                self.viewport.removeEventFilter(self.releaseFilter)
        except Exception:
            pass  # the viewport is gone

    def isCurrent(self):
        doc = Gui.ActiveDocument
        return doc is not None and doc.Document.Name == self.docName

    # --- the markers ------------------------------------------------------------------------

    def makeMarkers(self):
        switch = coin.SoSwitch()
        switch.whichChild = coin.SO_SWITCH_NONE
        root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        root.addChild(pick)
        color = coin.SoBaseColor()
        color.rgb.setValue(1.0, 0.6, 0.0)
        root.addChild(color)
        self.pointsCoords = coin.SoCoordinate3()
        root.addChild(self.pointsCoords)
        points = coin.SoMarkerSet()
        points.markerIndex = coin.SoMarkerSet.CIRCLE_FILLED_7_7
        root.addChild(points)
        chosen = coin.SoSeparator()
        self.chosenCoords = coin.SoCoordinate3()
        chosen.addChild(self.chosenCoords)
        chosenSet = coin.SoMarkerSet()
        chosenSet.markerIndex = coin.SoMarkerSet.CIRCLE_LINE_9_9
        chosen.addChild(chosenSet)
        root.addChild(chosen)
        switch.addChild(root)
        self.switch = switch
        return switch

    def showPoints(self, points=None, chosen=None):
        """points: document-coordinate points (None hides them); chosen: the index snapped to."""
        if not points:
            self.switch.whichChild = coin.SO_SWITCH_NONE
            return
        self.pointsCoords.point.setNum(0)
        self.pointsCoords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
        self.chosenCoords.point.setNum(0)
        if chosen is not None:
            p = points[chosen]
            self.chosenCoords.point.setValues(0, 1, [(p.x, p.y, p.z)])
        self.switch.whichChild = coin.SO_SWITCH_ALL

    def pointsShown(self):
        """The number of points drawn (0 when hidden), for the tests."""
        if self.switch.whichChild.getValue() == coin.SO_SWITCH_NONE:
            return 0
        return self.pointsCoords.point.getNum()

    # --- picking ----------------------------------------------------------------------------

    def pickInstance(self, assembly, pos, exclude=None):
        """The nearest element under the screen position pos of an instance of assembly other
        than exclude, as (ref, point): ref as the joint dialog's ([component, [sub]]), point in
        the document's coordinates. None when there is none."""
        try:
            infos = self.view.getObjectsInfo((int(pos[0]), int(pos[1]))) or []
        except Exception:
            return None
        doc = assembly.Document
        for info in infos:
            root = info.get("ParentObject")
            sub = info.get("SubName")
            if root is None:
                root = doc.getObject(info.get("Object", ""))
                sub = info.get("Component", "")
            if root is None or not sub:
                continue
            try:
                part, newSub = UtilsAssembly.getComponentReference(assembly, root, sub)
            except Exception:
                continue
            if part is None or part == exclude:
                continue
            ref = [part, [newSub]]
            if not UtilsAssembly.connectorCandidates(ref):
                continue
            return ref, App.Vector(info["x"], info["y"], info["z"])
        return None

    def connectorPlacement(self, ref, name):
        ref = UtilsAssembly.addVertexToReference(ref, name)
        return UtilsAssembly.getJcsGlobalPlc(UtilsAssembly.findPlacement(ref), ref)

    # --- the drag ---------------------------------------------------------------------------

    def onButton(self, info):
        if info.get("Button") != "BUTTON1":
            return
        if info.get("State") == "DOWN":
            self.press(info["Position"])
        elif info.get("State") == "UP":
            self.release(info["Position"])

    def onMove(self, info):
        if self.drag is not None:
            self.moveTo(info["Position"])

    def press(self, pos):
        """Starts a snap drag when pos is on a free instance; returns True if it did."""
        self.drag = None
        assembly = UtilsAssembly.activeAssembly()
        if assembly is None or Gui.Control.activeDialog():
            return False
        hit = self.pickInstance(assembly, pos)
        if hit is None:
            return False
        ref, point = hit
        part = ref[0]
        if not isFreeInstance(assembly, part):
            return False
        candidates = UtilsAssembly.connectorCandidates(ref)
        index = UtilsAssembly.chooseConnector(ref, candidates, point, self.view)
        self.drag = {
            "assembly": assembly,
            "part": part,
            "start": App.Placement(part.Placement),
            "grab": self.connectorPlacement(ref, candidates[index][1]),
            "startPoint": self.view.getPoint(int(pos[0]), int(pos[1])),
            "moved": False,
            "snapped": False,
            "enableMovement": assembly.ViewObject.EnableMovement,
        }
        # the assembly's own drag is off for this drag (as the joint dialog does)
        assembly.ViewObject.EnableMovement = False
        return True

    def target(self, pos):
        """The placement that snaps the dragged instance onto the connector point under pos,
        or None (the markers show the hovered element's points either way)."""
        d = self.drag
        hit = self.pickInstance(d["assembly"], pos, exclude=d["part"])
        if hit is None:
            self.showPoints(None)
            return None
        ref, point = hit
        candidates = UtilsAssembly.connectorCandidates(ref)
        index = UtilsAssembly.connectorUnderCursor(ref, candidates, point, self.view)
        self.showPoints([UtilsAssembly.shapeToGlobal(ref, p) for p, _n, _k in candidates], index)
        if index is None:
            return None
        onto = self.connectorPlacement(ref, candidates[index][1])
        # an unflipped Fastened mate's presolve (JointObject.matchJCS)
        return onto * d["grab"].inverse() * d["start"]

    def moveTo(self, pos):
        d = self.drag
        now = self.view.getPoint(int(pos[0]), int(pos[1]))
        snapped = self.target(pos)
        if snapped is None:
            plc = App.Placement(d["start"].Base + (now - d["startPoint"]), d["start"].Rotation)
        else:
            plc = snapped
        if not d["moved"]:
            if plc.isSame(d["start"], 1e-9):
                return
            d["assembly"].Document.openTransaction("Move part")
            d["moved"] = True
        d["snapped"] = snapped is not None
        d["part"].Placement = plc

    def release(self, pos):
        d = self.drag
        if d is None:
            return
        if pos is not None:
            self.moveTo(pos)
        self.drag = None
        self.showPoints(None)
        try:
            d["assembly"].ViewObject.EnableMovement = d["enableMovement"]
        except Exception:
            pass
        if d["moved"]:
            d["assembly"].Document.commitTransaction()


class CommandToggleSnapMode:
    def GetResources(self):
        return {
            "Pixmap": "Assembly_SnapMode",
            "MenuText": QT_TRANSLATE_NOOP("Assembly_ToggleSnapMode", "Snap mode"),
            "Accel": "Shift+S",
            "ToolTip": QT_TRANSLATE_NOOP(
                "Assembly_ToggleSnapMode",
                "While on, a dragged instance without mates snaps onto the connector point of "
                "another instance under the cursor. No mate is made.",
            ),
            "CmdType": "ForEdit",
            "Checkable": False,
        }

    def IsActive(self):
        active = UtilsAssembly.activeAssembly() is not None
        if _snap is not None and not (active and _snap.isCurrent()):
            setSnapMode(False)  # the assembly left edit, or the document changed: off, as Onshape's after a reload
        return active

    def Activated(self, checked=None):
        setSnapMode(not isSnapModeOn() if checked is None else bool(checked))


if App.GuiUp:
    Gui.addCommand(COMMAND, CommandToggleSnapMode())
