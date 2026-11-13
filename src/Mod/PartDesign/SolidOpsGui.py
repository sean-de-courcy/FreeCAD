# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (lane solid-ops): commands, view providers and task panels of Thicken, Scale and
# Offset surface (the features are in SolidOpsFeatures.py).
#
# Registered at startup (InitGui.py): the commands reach the PartDesign menu and toolbar through
# a WorkbenchManipulator, next to PartDesign_Thickness.

import FreeCAD
import FreeCADGui
import Part

from PySide import QtCore, QtGui, QtWidgets

try:
    from PartDesign import SolidOpsFeatures as F
except ImportError:  # path-injected test runs
    import SolidOpsFeatures as F

KINDS = {
    "Thicken": dict(
        command="PartDesign_Thicken",
        text="Thicken",
        tip="Thicken faces or surfaces into a solid, on one or both sides: New, Add, Remove or Intersect",
        icon=":/icons/Part_Thickness.svg",
        proxy=F.Thicken,
        type="PartDesign::FeatureAdditivePython",
        faces=True,
    ),
    "Scale": dict(
        command="PartDesign_ScalePart",
        text="Scale",
        tip="Scale the part before it about a point, uniformly or per axis",
        icon=":/icons/Part_Scale.svg",
        proxy=F.Scale,
        type="PartDesign::FeaturePython",
        faces=False,
    ),
    "OffsetSurface": dict(
        command="PartDesign_OffsetSurface",
        text="Offset surface",
        tip="Offset faces or surfaces by a distance",
        icon=":/icons/Part_Offset.svg",
        proxy=F.OffsetSurface,
        type="PartDesign::FeaturePython",
        faces=True,
    ),
}


def _tr(s):
    return QtCore.QCoreApplication.translate("SolidOps", s)


def _doc():
    return FreeCADGui.ActiveDocument.Document if FreeCADGui.ActiveDocument else None


def _active_body(doc):
    view = FreeCADGui.ActiveDocument.ActiveView
    body = view.getActiveObject("pdbody") if view and hasattr(view, "getActiveObject") else None
    return body if body and body.Document == doc else None


def selected_faces():
    """[(object, [FaceN, ...])] from the current selection."""
    out = []
    for sel in FreeCADGui.Selection.getSelectionEx("", 1):
        faces = [s for s in sel.SubElementNames if s.startswith("Face")]
        if faces:
            out.append((sel.Object, faces))
    return out


# ---------------------------------------------------------------- view provider


class ViewProviderSolidOp:
    def __init__(self, vobj, kind=None):
        vobj.Proxy = self
        self.kind = kind

    def attach(self, vobj):
        self.ViewObject = vobj
        self.Object = vobj.Object

    def _kind(self):
        # A restored view provider has no `kind`: loads() keeps no state and __init__ doesn't run
        return getattr(self, "kind", None) or type(self.Object.Proxy).__name__

    def getIcon(self):
        return KINDS.get(self._kind(), KINDS["Thicken"])["icon"]

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        vobj.Object.Document.openTransaction(_tr("Edit") + " " + vobj.Object.Label)
        FreeCADGui.Control.showDialog(Panel(vobj.Object, self._kind(), creating=False))
        return True

    def unsetEdit(self, vobj, mode=0):
        FreeCADGui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        FreeCADGui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ---------------------------------------------------------------- task panel

OPS = [("New", None), ("Add", "Union"), ("Remove", "Subtraction"), ("Intersect", "Common")]


class Panel:
    current = None  # the open panel (the GUI unit drives it)

    def __init__(self, obj, kind, creating):
        Panel.current = self
        self.obj = obj
        self.kind = kind
        self.creating = creating
        self.doc = obj.Document
        self.cfg = KINDS[kind]
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(_tr(self.cfg["text"]))
        self.layout = QtWidgets.QFormLayout(self.form)
        self.widgets = {}
        self.paths = {}
        self.busy = True
        self.closed = False
        if self.cfg["faces"]:
            self.addFaces()
        if kind == "Thicken":
            self.addOperation()
            self.check("Flip", _tr("Opposite direction"), self.obj.Flip)
            self.check("Midplane", _tr("Midplane"), self.obj.Midplane)
            self.spin("Thickness1", _tr("Thickness 1"), "Thickness1", 0, 5e5)
            self.spin("Thickness2", _tr("Thickness 2"), "Thickness2", 0, 5e5)
            self.spin("Thickness", _tr("Thickness (midplane)"), "Thickness", 0, 5e5)
            self.syncMidplane()
        elif kind == "OffsetSurface":
            self.spin("Distance", _tr("Distance"), "Distance", 0, 5e5)
            self.check("Flip", _tr("Flip direction"), self.obj.Flip)
        else:
            self.check("Uniform", _tr("Uniform"), self.obj.Uniform)
            self.spin("Factor", _tr("Scale factor"), "Factor", F.SCALE_MIN, F.SCALE_MAX, unit=None)
            for ax in "XYZ":
                self.spin("Factor" + ax, _tr("Scale " + ax), "Factor" + ax, F.SCALE_MIN, F.SCALE_MAX, unit=None)
            for ax in "XYZ":
                self.spin("Point" + ax, _tr("Point " + ax), "Point." + ax.lower(), -1e9, 1e9)
            self.syncUniform()
        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c00;")
        self.layout.addRow(self.message)
        self.busy = False
        self.refresh()

    # -- widgets
    def spin(self, name, label, path, lo, hi, unit="mm"):
        """A Gui::QuantitySpinBox bound to the property (or component, "Point.x") `path`: the
        f(x) button, `#variable` and `=expression` work, and an expression is stored on the feature."""
        w = FreeCADGui.UiLoader().createWidget("Gui::QuantitySpinBox")
        if unit:
            w.setProperty("unit", unit)
        w.setProperty("minimum", float(lo))
        w.setProperty("maximum", float(hi))
        w.setProperty("decimals", 6)
        w.setProperty("rawValue", self._number(path))
        FreeCADGui.ExpressionBinding(w).bind(self.obj, path)  # after the value (binding shows none)
        w.valueChanged.connect(self.changed)
        # An expression is stored when the edit ends (Enter, or leaving the field): recompute then
        w.editingFinished.connect(self.edited)
        self.widgets[name] = w
        self.paths[name] = path
        self.layout.addRow(label, w)

    def _number(self, path):
        value = self.obj
        for part in path.split("."):
            value = getattr(value, part)
        return float(getattr(value, "Value", value))

    def hasExpression(self, name):
        path = self.paths[name]
        return any(p.lstrip(".") == path for p, _ in self.obj.ExpressionEngine)

    def value(self, name):
        """The field's number (mm, or plain for a factor)."""
        return float(self.widgets[name].property("rawValue"))

    def setValue(self, name, number):
        self.widgets[name].setProperty("rawValue", float(number))
        self.changed()

    def edited(self):
        QtCore.QTimer.singleShot(0, self.changed)

    def check(self, name, label, value):
        w = QtWidgets.QCheckBox(label)
        w.setChecked(bool(value))
        w.toggled.connect(self.changed)
        self.widgets[name] = w
        self.layout.addRow(w)

    def addFaces(self):
        self.faceList = QtWidgets.QListWidget()
        self.faceList.setMaximumHeight(90)
        self.layout.addRow(_tr("Faces"), self.faceList)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton(_tr("Use selection"))
        clear = QtWidgets.QPushButton(_tr("Clear"))
        add.clicked.connect(self.useSelection)
        clear.clicked.connect(self.clearFaces)
        row.addWidget(add)
        row.addWidget(clear)
        self.layout.addRow(row)
        self.fillFaces()

    def addOperation(self):
        combo = QtWidgets.QComboBox()
        for text, _ in OPS:
            combo.addItem(_tr(text))
        hasBase = self.obj.BaseFeature is not None
        op = self.obj.Operation
        if not hasBase or self.creating:
            index = 0
        else:
            index = [o for _, o in OPS].index(op)
        combo.setCurrentIndex(index)
        if not hasBase and not self.creating:
            for i in (2, 3):
                combo.model().item(i).setEnabled(False)
        combo.currentIndexChanged.connect(self.changed)
        self.widgets["Operation"] = combo
        self.layout.addRow(_tr("Operation"), combo)

    # -- faces
    def faceLinks(self):
        return [(o, list(s)) for o, s in self.obj.Base]

    def fillFaces(self):
        self.faceList.clear()
        for o, subs in self.obj.Base:
            for s in subs:
                self.faceList.addItem("%s.%s" % (o.Label, s))

    def useSelection(self):
        links = selected_faces()
        if links:
            self.obj.Base = links
            self.fillFaces()
            self.refresh()

    def clearFaces(self):
        self.obj.Base = []
        self.fillFaces()
        self.refresh()

    # -- values
    def syncMidplane(self):
        mid = self.widgets["Midplane"].isChecked()
        self.widgets["Thickness"].setEnabled(mid)
        self.widgets["Thickness1"].setEnabled(not mid)
        self.widgets["Thickness2"].setEnabled(not mid)
        self.widgets["Flip"].setEnabled(not mid)

    def syncUniform(self):
        uniform = self.widgets["Uniform"].isChecked()
        self.widgets["Factor"].setEnabled(uniform)
        for ax in "XYZ":
            self.widgets["Factor" + ax].setEnabled(not uniform)

    def put(self, name):
        """Write a field's number to the feature, unless an expression drives it."""
        if name in self.paths and not self.hasExpression(name):
            path = self.paths[name]
            if "." in path:
                prop, comp = path.split(".")
                vec = FreeCAD.Vector(getattr(self.obj, prop))
                setattr(vec, comp, self.value(name))
                setattr(self.obj, prop, vec)
            else:
                setattr(self.obj, path, self.value(name))

    def changed(self, *args):
        if self.busy or self.closed:
            return
        w = self.widgets
        o = self.obj
        for name in self.paths:
            self.put(name)
        if self.kind == "Thicken":
            o.Flip = w["Flip"].isChecked()
            o.Midplane = w["Midplane"].isChecked()
            self.syncMidplane()
            ops = OPS[w["Operation"].currentIndex()][1]
            if ops:
                o.Operation = ops
        elif self.kind == "OffsetSurface":
            o.Flip = w["Flip"].isChecked()
        else:
            o.Uniform = w["Uniform"].isChecked()
            self.syncUniform()
        self.refresh()

    def refresh(self):
        self.doc.recompute()
        failed = "Invalid" in self.obj.State or "Error" in "".join(self.obj.State)
        self.message.setText(self.obj.getStatusString() if failed else "")
        return not failed

    # -- dialog protocol
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self.changed()
        if not self.refresh():
            # A loud failure keeps the dialog open with the message (Onshape shows the error)
            return False
        if self.kind == "Thicken":
            wantNew = self.widgets["Operation"].currentIndex() == 0
            if wantNew and self.obj.BaseFeature is not None:
                import PartDesign

                PartDesign.newPartFrom(self.obj)
                self.doc.recompute()
        self.doc.commitTransaction()
        self.close()
        return True

    def reject(self):
        self.doc.abortTransaction()
        self.doc.recompute()
        self.close()
        return True

    def close(self):
        self.closed = True
        Panel.current = None
        FreeCADGui.Control.closeDialog()
        FreeCADGui.ActiveDocument.resetEdit()


# ---------------------------------------------------------------- commands


class Command:
    def __init__(self, kind):
        self.kind = kind
        self.cfg = KINDS[kind]

    def GetResources(self):
        c = self.cfg
        return {"Pixmap": c["icon"], "MenuText": _tr(c["text"]), "ToolTip": _tr(c["tip"])}

    def IsActive(self):
        return FreeCADGui.ActiveDocument is not None and not FreeCADGui.Control.activeDialog()

    def Activated(self):
        doc = _doc()
        doc.openTransaction(self.cfg["text"])
        try:
            obj = self.create(doc)
        except Exception:
            doc.abortTransaction()
            raise
        FreeCADGui.Control.showDialog(Panel(obj, self.kind, creating=True))

    def create(self, doc):
        faces = selected_faces() if self.cfg["faces"] else []
        body = _active_body(doc)
        if self.kind == "Thicken":
            # The panel starts on New (Onshape's default): accepting moves it into a part of its own
            if body is None:
                body = doc.addObject("PartDesign::Body", "Body")
            obj = F.make_thicken(body, faces, 5.0, 0.0, "Union")
        elif self.kind == "OffsetSurface":
            # A sheet is a part of its own (Onshape: a new surface part): in the active Body it
            # would replace the solid before it
            if body is None or body.BaseFeature is not None or any(o.isDerivedFrom("PartDesign::Feature") for o in body.Group):
                body = doc.addObject("PartDesign::Body", "Body")
            obj = F.make_offset_surface(body, faces, 5.0)
        else:
            if body is None:
                raise FreeCAD.Base.FreeCADError("Scale needs an active Body: activate the part to scale")
            obj = F.make_scale(body, None, 1.0)
        ViewProviderSolidOp(obj.ViewObject, self.kind)
        return obj


_registered = False


class Manipulator:
    def modifyToolBars(self):
        return [{"insert": c["command"], "toolItem": "PartDesign_Thickness"} for c in KINDS.values()]

    def modifyMenuBar(self):
        return [{"insert": c["command"], "menuItem": "PartDesign_Thickness"} for c in KINDS.values()]


def register():
    global _registered
    if _registered:
        return
    for kind, c in KINDS.items():
        FreeCADGui.addCommand(c["command"], Command(kind))
    FreeCADGui.addWorkbenchManipulator(Manipulator())
    _registered = True
