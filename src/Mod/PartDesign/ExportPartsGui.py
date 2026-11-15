# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, gaps3 row 11): Onshape's Export... on a part (GB15).
#
# One dialog: file name, format (STL by default), the STL format (text or binary), units and
# resolution (Coarse, Medium, Fine by default, or Custom with a chordal tolerance and an angular
# deviation). The parts are written as one file, in their placement in the studio. Meshes take the
# units; STEP and IGES are written in millimetres, as FreeCAD's exporters do.

import math
import os

import FreeCAD

translate = FreeCAD.Qt.translate

# Onshape's unit list (GB15): the size of one unit in millimetres
UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8, "yd": 914.4}

# The resolutions: chordal tolerance (mm) and angular deviation (degrees). Onshape's numbers were
# not read (GB15 names the levels only): these are FreeCAD-CH's, Fine about a print's needs
RESOLUTIONS = {
    "Coarse": (0.1, 15.0),
    "Medium": (0.05, 10.0),
    "Fine": (0.02, 5.0),
}
DEFAULT_RESOLUTION = "Fine"

# Format name -> (file extension, is a mesh)
FORMATS = {
    "STL": (".stl", True),
    "OBJ": (".obj", True),
    "3MF": (".3mf", True),
    "STEP": (".step", False),
    "IGES": (".iges", False),
}
DEFAULT_FORMAT = "STL"


def shapeOf(objs):
    """The parts' shapes in their global placement, as one shape."""
    import Part

    shapes = []
    for obj in objs:
        shape = Part.getShape(obj)
        if shape.isNull():
            raise ValueError(translate("ExportParts", "{} has no shape").format(obj.Label))
        shapes.append(shape)
    if not shapes:
        raise ValueError(translate("ExportParts", "No part to export"))
    return shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)


def exportParts(
    objs,
    path,
    fmt=DEFAULT_FORMAT,
    units="mm",
    resolution=DEFAULT_RESOLUTION,
    chordal=None,
    angular=None,
    stlText=False,
):
    """Write objs to path in fmt. Meshes (STL, OBJ, 3MF) are scaled to units and tessellated at
    resolution, or at chordal (mm) and angular (degrees) when resolution is "Custom"."""
    if fmt not in FORMATS:
        raise ValueError(translate("ExportParts", "Unknown format {}").format(fmt))
    if units not in UNITS:
        raise ValueError(translate("ExportParts", "Unknown units {}").format(units))
    shape = shapeOf(objs)
    if not FORMATS[fmt][1]:
        if fmt == "STEP":
            shape.exportStep(path)
        else:
            shape.exportIges(path)
        return
    if resolution != "Custom":
        chordal, angular = RESOLUTIONS[resolution]
    if not chordal or chordal <= 0 or not angular or angular <= 0:
        raise ValueError(translate("ExportParts", "The tolerances must be positive"))
    import MeshPart

    factor = UNITS[units]
    if factor != 1.0:
        shape = shape.copy()
        shape.scale(1.0 / factor)
    mesh = MeshPart.meshFromShape(
        Shape=shape,
        LinearDeflection=chordal / factor,
        AngularDeflection=math.radians(angular),
        Relative=False,
    )
    meshFormat = {"STL": "AST" if stlText else "STL", "OBJ": "OBJ", "3MF": "3MF"}[fmt]
    mesh.write(path, meshFormat)


def safeFileName(text):
    for bad in '\\/:*?"<>|':
        text = text.replace(bad, "_")
    return text or "export"


def makeDialog(objs, parent=None):
    """The Export dialog for objs (not shown)."""
    from PySide import QtWidgets

    dialog = QtWidgets.QDialog(parent)
    dialog.setObjectName("ExportPartsDialog")
    dialog.setWindowTitle(translate("ExportParts", "Export"))
    form = QtWidgets.QFormLayout(dialog)

    base = safeFileName(objs[0].Label if len(objs) == 1 else objs[0].Document.Label)
    folder = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").GetString(
        "FileOpenSavePath", os.path.expanduser("~")
    )
    nameRow = QtWidgets.QHBoxLayout()
    fileName = QtWidgets.QLineEdit(os.path.join(folder, base))
    fileName.setObjectName("exportFileName")
    browse = QtWidgets.QPushButton("...")
    browse.setObjectName("exportBrowse")
    nameRow.addWidget(fileName)
    nameRow.addWidget(browse)
    form.addRow(translate("ExportParts", "File name"), nameRow)

    formats = QtWidgets.QComboBox()
    formats.setObjectName("exportFormat")
    formats.addItems(list(FORMATS))
    formats.setCurrentText(DEFAULT_FORMAT)
    form.addRow(translate("ExportParts", "Format"), formats)

    stlFormat = QtWidgets.QComboBox()
    stlFormat.setObjectName("exportStlFormat")
    stlFormat.addItems([translate("ExportParts", "Binary"), translate("ExportParts", "Text")])
    form.addRow(translate("ExportParts", "STL format"), stlFormat)

    units = QtWidgets.QComboBox()
    units.setObjectName("exportUnits")
    units.addItems(list(UNITS))
    units.setCurrentText("mm")
    form.addRow(translate("ExportParts", "Units"), units)

    resolution = QtWidgets.QComboBox()
    resolution.setObjectName("exportResolution")
    resolution.addItems(list(RESOLUTIONS) + ["Custom"])
    resolution.setCurrentText(DEFAULT_RESOLUTION)
    form.addRow(translate("ExportParts", "Resolution"), resolution)

    chordal = QtWidgets.QDoubleSpinBox()
    chordal.setObjectName("exportChordal")
    chordal.setDecimals(4)
    chordal.setRange(0.0001, 100.0)
    chordal.setSuffix(" mm")
    form.addRow(translate("ExportParts", "Chordal tolerance"), chordal)

    angular = QtWidgets.QDoubleSpinBox()
    angular.setObjectName("exportAngular")
    angular.setDecimals(2)
    angular.setRange(0.01, 90.0)
    angular.setSuffix(" °")
    form.addRow(translate("ExportParts", "Angular deviation"), angular)

    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    form.addRow(buttons)

    def update():
        fmt = formats.currentText()
        mesh = FORMATS[fmt][1]
        stlFormat.setEnabled(fmt == "STL")
        units.setEnabled(mesh)
        resolution.setEnabled(mesh)
        custom = mesh and resolution.currentText() == "Custom"
        chordal.setEnabled(custom)
        angular.setEnabled(custom)
        if resolution.currentText() in RESOLUTIONS:
            chordal.setValue(RESOLUTIONS[resolution.currentText()][0])
            angular.setValue(RESOLUTIONS[resolution.currentText()][1])
        # the extension follows the format
        stem, ext = os.path.splitext(fileName.text())
        known = [e for e, _ in FORMATS.values()] + [".stp", ".igs"]
        if ext.lower() in known or not ext:
            fileName.setText(stem + FORMATS[fmt][0])

    def pick():
        fmt = formats.currentText()
        ext = FORMATS[fmt][0]
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            dialog, translate("ExportParts", "Export"), fileName.text(), "{} (*{})".format(fmt, ext)
        )
        if path:
            fileName.setText(path)

    formats.currentTextChanged.connect(lambda _: update())
    resolution.currentTextChanged.connect(lambda _: update())
    browse.clicked.connect(pick)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    update()

    def options():
        return {
            "path": fileName.text(),
            "fmt": formats.currentText(),
            "units": units.currentText(),
            "resolution": resolution.currentText(),
            "chordal": chordal.value(),
            "angular": angular.value(),
            "stlText": stlFormat.currentIndex() == 1,
        }

    dialog.exportOptions = options
    return dialog


def showDialog(docName, names):
    """The part row's Export...: the dialog for the named parts of document docName."""
    import FreeCADGui

    doc = FreeCAD.getDocument(docName)
    objs = [doc.getObject(name) for name in names if doc.getObject(name)]
    if not objs:
        return
    dialog = makeDialog(objs, FreeCADGui.getMainWindow())
    if not dialog.exec():
        return
    opts = dialog.exportOptions()
    path = opts.pop("path")
    try:
        exportParts(objs, path, **opts)
    except Exception as e:
        from PySide import QtWidgets

        QtWidgets.QMessageBox.warning(
            FreeCADGui.getMainWindow(), translate("ExportParts", "Export"), str(e)
        )
        return
    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").SetString(
        "FileOpenSavePath", os.path.dirname(path)
    )
    FreeCADGui.getMainWindow().statusBar().showMessage(
        translate("ExportParts", "Exported {}").format(path), 5000
    )
