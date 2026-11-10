# SPDX-License-Identifier: LGPL-2.1-or-later
"""The DXF commands (FreeCAD-CH): Insert DXF into the open sketch, Export DXF of a sketch or face.

- `Sketcher_InsertDxf`, in the Sketch toolbar and the Sketch menu while a sketch is open:
  pick a file, choose the units when it has none, the fitting tolerance and corner angle, and
  whether the curves are fixed (one Block each); one undo step; the report says what came in.
- `Sketcher_ExportDxf`, on the context menu of a sketch (tree and 3D view) and of a planar face:
  an R12 DXF in millimetres of true lines, arcs and circles (`SketcherDxf/exporter.py`).
The entries are added by a WorkbenchManipulator, so they reach every workbench's menus.
"""

import os

import FreeCAD
import FreeCADGui

PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher/Dxf"


def _params():
    return FreeCAD.ParamGet(PARAMS)


def _tr(text):
    try:
        from PySide import QtCore

        return QtCore.QCoreApplication.translate("Sketcher_Dxf", text)
    except Exception:
        return text


def _sketch_in_edit():
    gdoc = FreeCADGui.ActiveDocument
    if gdoc is None:
        return None
    vp = gdoc.getInEdit()
    if vp is None:
        return None
    obj = getattr(vp, "Object", None)
    if obj is not None and obj.isDerivedFrom("Sketcher::SketchObject"):
        return obj
    return None


def _main_window():
    return FreeCADGui.getMainWindow()


# ---------------------------------------------------------------------------------------------


class InsertDialog:
    """The options of one insert; exec() -> dict or None"""

    UNITS = ["mm", "cm", "m", "in", "ft"]

    def __init__(self, drawing, path):
        from PySide import QtWidgets

        p = _params()
        self.d = QtWidgets.QDialog(_main_window())
        self.d.setWindowTitle(_tr("Insert DXF"))
        form = QtWidgets.QFormLayout(self.d)
        segs = sum(1 for it in drawing.items if type(it).__name__ == "Line")
        form.addRow(QtWidgets.QLabel(f"{os.path.basename(path)}: {len(drawing.items)} curves, {segs} line segments"))
        self.units = None
        if drawing.mm_per_unit is None:
            self.units = QtWidgets.QComboBox()
            self.units.addItems(self.UNITS)
            last = p.GetString("Units", "mm")
            if last in self.UNITS:
                self.units.setCurrentIndex(self.UNITS.index(last))
            form.addRow(_tr("The file states no units. Units:"), self.units)
        else:
            from SketcherDxf import reader

            name = reader.UNIT_NAMES.get(drawing.insunits, f"code {drawing.insunits}")
            form.addRow(_tr("Units:"), QtWidgets.QLabel(_tr("from the file: ") + name))
        self.fit = QtWidgets.QCheckBox(_tr("Fit chains of short segments to lines, arcs and splines"))
        self.fit.setChecked(p.GetBool("Fit", True))
        form.addRow(self.fit)
        self.tol = QtWidgets.QDoubleSpinBox()
        self.tol.setDecimals(4)
        self.tol.setRange(0.0001, 10.0)
        self.tol.setSingleStep(0.005)
        self.tol.setSuffix(" mm")
        self.tol.setValue(p.GetFloat("Tolerance", 0.01))
        form.addRow(_tr("Fitting tolerance:"), self.tol)
        self.corner = QtWidgets.QDoubleSpinBox()
        self.corner.setRange(1.0, 179.0)
        self.corner.setSuffix(" °")
        self.corner.setValue(p.GetFloat("CornerAngle", 30.0))
        form.addRow(_tr("Corners sharper than:"), self.corner)
        self.fit.toggled.connect(self.tol.setEnabled)
        self.fit.toggled.connect(self.corner.setEnabled)
        self.tol.setEnabled(self.fit.isChecked())
        self.corner.setEnabled(self.fit.isChecked())
        self.block = QtWidgets.QCheckBox(_tr("Fix the imported curves (one Block constraint each)"))
        self.block.setChecked(p.GetBool("Block", True))
        form.addRow(self.block)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.d.accept)
        bb.rejected.connect(self.d.reject)
        form.addRow(bb)

    def values(self):
        return {
            "units": self.units.currentText() if self.units is not None else None,
            "fit": self.fit.isChecked(),
            "tolerance": self.tol.value(),
            "corner": self.corner.value(),
            "hold": "block" if self.block.isChecked() else "free",
        }

    def exec(self):
        from PySide import QtWidgets

        if self.d.exec() != QtWidgets.QDialog.Accepted:
            return None
        v = self.values()
        p = _params()
        if v["units"]:
            p.SetString("Units", v["units"])
        p.SetBool("Fit", v["fit"])
        p.SetFloat("Tolerance", v["tolerance"])
        p.SetFloat("CornerAngle", v["corner"])
        p.SetBool("Block", v["hold"] == "block")
        return v


def insert_into(sketch, path, options):
    """The command's work, without dialogs (GUI tests call it): one undo step; the Report"""
    import SketcherDxf

    doc = sketch.Document
    doc.openTransaction("Insert DXF")
    try:
        rep = SketcherDxf.insert(sketch, path, **options)
        sketch.solve()
        sketch.recompute()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return rep


class CommandInsertDxf:
    def GetResources(self):
        return {
            "Pixmap": "Std_Import",
            "MenuText": _tr("Insert DXF..."),
            "ToolTip": _tr(
                "Insert a DXF file's curves into the open sketch, at its origin and in the file's units; "
                "long chains of short segments are fitted to lines, arcs and splines"
            ),
        }

    def IsActive(self):
        return _sketch_in_edit() is not None

    def Activated(self):
        from PySide import QtWidgets
        import SketcherDxf

        sketch = _sketch_in_edit()
        if sketch is None:
            return
        p = _params()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            _main_window(), _tr("Insert DXF"), p.GetString("LastDir", ""), "DXF (*.dxf *.DXF)"
        )
        if not path:
            return
        p.SetString("LastDir", os.path.dirname(path))
        try:
            drawing = SketcherDxf.read(path)
        except SketcherDxf.DxfError as exc:
            QtWidgets.QMessageBox.warning(_main_window(), _tr("Insert DXF"), f"{os.path.basename(path)}: {exc}")
            return
        options = InsertDialog(drawing, path).exec()
        if options is None:
            return
        try:
            rep = insert_into(sketch, path, options)
        except SketcherDxf.DxfError as exc:
            QtWidgets.QMessageBox.warning(_main_window(), _tr("Insert DXF"), f"{os.path.basename(path)}: {exc}")
            return
        text = "\n".join(rep.lines())
        FreeCAD.Console.PrintMessage(f"Insert DXF {path}:\n{text}\n")
        QtWidgets.QMessageBox.information(_main_window(), _tr("Insert DXF"), text)


# ---------------------------------------------------------------------------------------------


def export_target():
    """(object, subname) of what Export DXF would write, or None: one sketch, one planar face, or
    the sketch in edit when nothing is selected"""
    sel = FreeCADGui.Selection.getSelectionEx("", 0)
    if not sel:
        sk = _sketch_in_edit()
        return (sk, "") if sk is not None else None
    if len(sel) != 1:
        return None
    s = sel[0]
    obj = s.Object
    subs = [n for n in s.SubElementNames if n]
    if not subs:
        leaf = obj
        return (obj, "") if leaf.isDerivedFrom("Sketcher::SketchObject") else None
    if len(subs) != 1:
        return None
    # without the mapped element name the selection may carry (";...;.Face6" -> "Face6")
    sub = ".".join(p for p in subs[0].split(".") if not p.startswith(";"))
    # a sub-object path (Body.Pad.Face6): the leaf object and its element
    leaf = obj.getSubObject(sub, retType=1)
    element = sub.split(".")[-1]
    if leaf is not None and leaf.isDerivedFrom("Sketcher::SketchObject") and not element.startswith("Face"):
        return (leaf, "")
    if not element.startswith("Face"):
        return None
    try:
        face = obj.getSubObject(sub)
        if face is None or face.isNull() or not face.Faces:
            return None
        f = face.Faces[0]
        import Part

        if not (isinstance(f.Surface, Part.Plane) or f.findPlane() is not None):
            return None
    except Exception:
        return None
    return (obj, sub)


class ExportDialog:
    def __init__(self):
        from PySide import QtWidgets

        p = _params()
        self.d = QtWidgets.QDialog(_main_window())
        self.d.setWindowTitle(_tr("Export DXF"))
        form = QtWidgets.QFormLayout(self.d)
        form.addRow(QtWidgets.QLabel(_tr("AutoCAD R12 DXF, millimetres, 1:1: lines, arcs and circles")))
        self.tol = QtWidgets.QDoubleSpinBox()
        self.tol.setDecimals(4)
        self.tol.setRange(0.0001, 10.0)
        self.tol.setSuffix(" mm")
        self.tol.setValue(p.GetFloat("ExportTolerance", 0.01))
        form.addRow(_tr("Ellipses and splines as arcs within:"), self.tol)
        self.poly = QtWidgets.QCheckBox(_tr("Each closed loop as one polyline (true arcs as bulges)"))
        self.poly.setChecked(p.GetBool("ExportPolylines", False))
        form.addRow(self.poly)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.d.accept)
        bb.rejected.connect(self.d.reject)
        form.addRow(bb)

    def exec(self):
        from PySide import QtWidgets

        if self.d.exec() != QtWidgets.QDialog.Accepted:
            return None
        p = _params()
        p.SetFloat("ExportTolerance", self.tol.value())
        p.SetBool("ExportPolylines", self.poly.isChecked())
        return {"tolerance": self.tol.value(), "polylines": self.poly.isChecked()}


class CommandExportDxf:
    def GetResources(self):
        return {
            "Pixmap": "Std_Export",
            "MenuText": _tr("Export DXF..."),
            "ToolTip": _tr(
                "Export the selected sketch, or the selected planar face's loops seen from outside, "
                "to a DXF in millimetres at 1:1 (lines, arcs and circles)"
            ),
        }

    def IsActive(self):
        try:
            return export_target() is not None
        except Exception:
            return False

    def Activated(self):
        from PySide import QtWidgets
        import SketcherDxf

        target = export_target()
        if target is None:
            return
        obj, sub = target
        options = ExportDialog().exec()
        if options is None:
            return
        p = _params()
        name = obj.Label + ("-" + sub.split(".")[-1] if sub else "") + ".dxf"
        start = os.path.join(p.GetString("LastExportDir", ""), name)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(_main_window(), _tr("Export DXF"), start, "DXF (*.dxf)")
        if not path:
            return
        if not path.lower().endswith(".dxf"):
            path += ".dxf"
        p.SetString("LastExportDir", os.path.dirname(path))
        try:
            rep = SketcherDxf.export_selection(obj, sub, path, **options)
        except (SketcherDxf.ExportError, OSError) as exc:
            QtWidgets.QMessageBox.warning(_main_window(), _tr("Export DXF"), str(exc))
            return
        text = "\n".join(rep.lines())
        FreeCAD.Console.PrintMessage(f"Export DXF:\n{text}\n")
        QtWidgets.QMessageBox.information(_main_window(), _tr("Export DXF"), text)


# ---------------------------------------------------------------------------------------------


class DxfManipulator:
    """Insert DXF in the Sketch toolbar and menu; Export DXF on the context menus"""

    def modifyToolBars(self):
        return [{"insert": "Sketcher_InsertDxf", "toolItem": "Sketcher_ToggleConstruction"}]

    def modifyMenuBar(self):
        return [
            {"insert": "Sketcher_InsertDxf", "menuItem": "Sketcher_LeaveSketch"},
            {"insert": "Sketcher_ExportDxf", "menuItem": "Sketcher_LeaveSketch"},
        ]

    def modifyContextMenu(self, recipient):
        try:
            target = export_target()
        except Exception:
            target = None
        if target is None or not FreeCADGui.Selection.getSelectionEx("", 0):
            return []
        if recipient == "View":
            # Onshape's menu (the fork's keymap) ends with More: the entry goes just before it
            keymap = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").GetString("Keymap", "Onshape")
            anchor = "Std_Delete" if keymap == "FreeCAD" else "More"
            return [{"insert": "Sketcher_ExportDxf", "menuItem": anchor}]
        if recipient == "Tree" and not target[1]:
            return [{"insert": "Sketcher_ExportDxf", "menuItem": "Std_TreeNextProblem"}]
        return []


_registered = False


def register():
    global _registered
    if _registered:
        return
    FreeCADGui.addCommand("Sketcher_InsertDxf", CommandInsertDxf())
    FreeCADGui.addCommand("Sketcher_ExportDxf", CommandExportDxf())
    FreeCADGui.addWorkbenchManipulator(DxfManipulator())
    _registered = True
