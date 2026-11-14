# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#655: the Transform command (move, rotate, copy part), its view provider and task
# panel (the feature is in TransformFeature.py). Registered at startup (InitGui.py); it joins the
# PartDesign menu and toolbar through a WorkbenchManipulator, after the Scale command.

import FreeCAD
import FreeCADGui
import PartDesign

from PySide import QtCore, QtWidgets

try:
    from PartDesign import TransformFeature as F
except ImportError:  # path-injected test runs
    import TransformFeature as F

COMMAND = "PartDesign_TransformParts"
ICON = ":/icons/Std_TransformManip.svg"


def _tr(s):
    return QtCore.QCoreApplication.translate("Transform", s)


def _doc():
    return FreeCADGui.ActiveDocument.Document if FreeCADGui.ActiveDocument else None


def body_of(obj):
    if obj is None:
        return None
    if obj.TypeId == "PartDesign::Body":
        return obj
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def selected_parts():
    """The parts (Bodies) of the current selection, in order, each once."""
    out = []
    for sel in FreeCADGui.Selection.getSelectionEx("", 1):
        body = body_of(sel.Object)
        if body is not None and body not in out:
            out.append(body)
    return out


def selected_reference():
    """(object, [sub]) of the first selected item, or None."""
    for sel in FreeCADGui.Selection.getSelectionEx("", 1):
        subs = [s for s in sel.SubElementNames if s]
        return sel.Object, subs[:1]
    return None


def reference_at(owner, link):
    """A reference read where the Transform is in the history: a picked part's geometry is its
    solid before the Transform (the step's base), never its tip (that would be the Transform's own
    result: a cycle)."""
    obj, subs = link
    body = body_of(obj)
    if body is None:
        return link
    step = PartDesign.studioStepOf(owner, body)
    if step is not None and (obj == body or obj == step or body.Tip == obj):
        base = step.BaseFeature
        if base is None:
            raise FreeCAD.Base.FreeCADError(f"'{body.Label}' has no solid before '{owner.Label}'")
        return base, subs
    if obj == body:
        return body.Tip, subs
    return link


# ---------------------------------------------------------------- view provider


class ViewProviderTransform:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ICON

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        FreeCADGui.Control.showDialog(Panel(vobj.Object, creating=False))
        return True

    def unsetEdit(self, vobj, mode=0):
        return mode == 0 or None

    def doubleClicked(self, vobj):
        vobj.Document.setEdit(vobj.Object.Name)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ---------------------------------------------------------------- task panel

REFERENCES = {
    "Translate by line": [("Line", "Line")],
    "Translate by distance": [("Direction", "Direction")],
    "Rotate": [("Axis", "Axis")],
    "Transform by mate connectors": [("FromConnector", "From"), ("ToConnector", "To")],
    "Translate by XYZ": [],
    "Copy in place": [],
    "Scale": [("ScalePoint", "Point or mate connector")],
}
VALUES = {
    "Translate by line": [],
    "Translate by distance": [("Distance", "Distance")],
    "Rotate": [("Angle", "Angle")],
    "Transform by mate connectors": [],
    "Translate by XYZ": [("X", "X"), ("Y", "Y"), ("Z", "Z")],
    "Copy in place": [],
    "Scale": [("Scale", "Scale"), ("ScaleX", "X"), ("ScaleY", "Y"), ("ScaleZ", "Z")],
}


def _number(value):
    return getattr(value, "Value", value)  # a quantity's value, or a float


class Panel:
    current = None  # the open panel (the GUI unit drives it)

    def __init__(self, obj, creating):
        Panel.current = self
        self.obj = obj
        self.doc = obj.Document
        self.creating = creating
        if not creating:
            self.doc.openTransaction(_tr("Edit Transform"))
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(_tr("Transform"))
        layout = QtWidgets.QFormLayout(self.form)
        self.parts = QtWidgets.QLabel()
        partsButton = QtWidgets.QPushButton(_tr("Parts from selection"))
        partsButton.clicked.connect(self.partsFromSelection)
        layout.addRow(_tr("Parts"), self.parts)
        layout.addRow("", partsButton)
        self.type = QtWidgets.QComboBox()
        self.type.addItems([_tr(t) for t in F.TYPES])
        self.type.setCurrentIndex(F.TYPES.index(obj.TransformType))
        self.type.currentIndexChanged.connect(self.typeChanged)
        layout.addRow(_tr("Type"), self.type)
        self.rows = {}
        for prop, text in [("Line", "Line"), ("Direction", "Direction"), ("Axis", "Axis"),
                           ("FromConnector", "From"), ("ToConnector", "To"),
                           ("ScalePoint", "Point or mate connector")]:
            button = QtWidgets.QPushButton()
            button.clicked.connect(lambda _=False, p=prop: self.pick(p))
            layout.addRow(_tr(text), button)
            self.rows[prop] = button
        self.uniform = QtWidgets.QCheckBox(_tr("Scale uniformly"))
        self.uniform.setChecked(obj.ScaleUniformly)
        self.uniform.toggled.connect(self.setUniform)
        layout.addRow("", self.uniform)
        self.spins = {}
        labels = {"ScaleX": "X", "ScaleY": "Y", "ScaleZ": "Z"}
        for prop in ("Distance", "Angle", "X", "Y", "Z", "Scale", "ScaleX", "ScaleY", "ScaleZ"):
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(-1e6, 1e6)
            spin.setDecimals(6)
            spin.setValue(_number(getattr(obj, prop)))
            spin.valueChanged.connect(lambda v, p=prop: self.setValue(p, v))
            layout.addRow(_tr(labels.get(prop, prop)), spin)
            self.spins[prop] = spin
        self.opposite = QtWidgets.QCheckBox(_tr("Opposite direction"))
        self.opposite.setChecked(obj.OppositeDirection)
        self.opposite.toggled.connect(self.setOpposite)
        layout.addRow("", self.opposite)
        self.copy = QtWidgets.QCheckBox(_tr("Copy part"))
        self.copy.setChecked(obj.MakeCopy)
        self.copy.toggled.connect(self.setCopy)
        layout.addRow("", self.copy)
        self.layout = layout
        self.sync()

    # the fields
    def sync(self):
        kind = self.obj.TransformType
        shown = {p for p, _ in REFERENCES[kind]}
        for prop, button in self.rows.items():
            self.layout.setRowVisible(button, prop in shown)
            value = getattr(self.obj, prop)
            if prop in ("FromConnector", "ToConnector"):
                button.setText(value.Label if value else _tr("Select, then click"))
            else:
                button.setText(f"{value[0].Label} {' '.join(value[1])}" if value else _tr("Select, then click"))
        values = {p for p, _ in VALUES[kind]}
        if kind == "Scale":
            values -= {"ScaleX", "ScaleY", "ScaleZ"} if self.obj.ScaleUniformly else {"Scale"}
        self.layout.setRowVisible(self.uniform, kind == "Scale")
        for prop, spin in self.spins.items():
            self.layout.setRowVisible(spin, prop in values)
        self.layout.setRowVisible(self.opposite, kind in ("Translate by line", "Translate by distance", "Rotate"))
        parts = [b.Label for b in self.doc.Objects if b.TypeId == "PartDesign::Body"
                 and PartDesign.studioPartId(b) in F.picked_ids(self.obj)]
        self.parts.setText(", ".join(parts) if parts else _tr("none: select parts"))

    def recompute(self):
        self.doc.recompute()
        self.sync()

    def typeChanged(self, index):
        self.obj.TransformType = F.TYPES[index]
        if F.TYPES[index] == "Copy in place" and not self.obj.MakeCopy:
            # Onshape's Copy in place has only the parts: it always copies
            self.copy.setChecked(True)
        self.recompute()

    def partsFromSelection(self):
        parts = [b for b in selected_parts() if b.StudioMadeBy != self.obj]
        F.set_parts(self.obj, parts)
        self.recompute()

    def pick(self, prop):
        link = selected_reference()
        if link is None:
            return
        if prop in ("FromConnector", "ToConnector"):
            setattr(self.obj, prop, link[0])
        else:
            setattr(self.obj, prop, reference_at(self.obj, link))
        self.recompute()

    def setValue(self, prop, value):
        setattr(self.obj, prop, value)
        self.recompute()

    def setUniform(self, on):
        self.obj.ScaleUniformly = on
        self.recompute()

    def setOpposite(self, on):
        self.obj.OppositeDirection = on
        self.recompute()

    def setCopy(self, on):
        F.set_copy(self.obj, on)
        self.recompute()

    # the dialog
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self.doc.recompute()
        if not self.obj.isValid():
            FreeCAD.Console.PrintError(f"{self.obj.Label}: {self.obj.getStatusString()}\n")
            return False
        self.doc.commitTransaction()
        self.close()
        return True

    def reject(self):
        self.doc.abortTransaction()
        self.doc.recompute()
        self.close()
        return True

    def close(self):
        Panel.current = None
        FreeCADGui.Control.closeDialog()
        if FreeCADGui.ActiveDocument:
            FreeCADGui.ActiveDocument.resetEdit()


# ---------------------------------------------------------------- the command


class Command:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": _tr("Transform"),
            "ToolTip": _tr("Move, rotate or copy parts of the studio (Onshape's Transform)"),
        }

    def IsActive(self):
        return FreeCADGui.ActiveDocument is not None and not FreeCADGui.Control.activeDialog()

    def Activated(self):
        doc = _doc()
        parts = selected_parts()
        if not parts:
            raise FreeCAD.Base.FreeCADError("Select parts to transform")
        doc.openTransaction(_tr("Transform"))
        try:
            obj = F.make_transform(parts)
            ViewProviderTransform(obj.ViewObject)
            doc.recompute()
        except Exception:
            doc.abortTransaction()
            raise
        FreeCADGui.Control.showDialog(Panel(obj, creating=True))


_registered = False


class Manipulator:
    def modifyToolBars(self):
        return [{"insert": COMMAND, "toolItem": "PartDesign_Thickness"}]

    def modifyMenuBar(self):
        return [{"insert": COMMAND, "menuItem": "PartDesign_Thickness"}]


def register():
    global _registered
    if _registered:
        return
    FreeCADGui.addCommand(COMMAND, Command())
    FreeCADGui.addWorkbenchManipulator(Manipulator())
    _registered = True
