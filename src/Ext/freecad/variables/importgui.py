# SPDX-License-Identifier: LGPL-2.1-or-later
# ****************************************************************************
# *                                                                          *
# *   This file is part of FreeCAD.                                          *
# *                                                                          *
# *   FreeCAD is free software: you can redistribute it and/or modify it     *
# *   under the terms of the GNU Lesser General Public License as            *
# *   published by the Free Software Foundation, either version 2.1 of the   *
# *   License, or (at your option) any later version.                        *
# *                                                                          *
# *   FreeCAD is distributed in the hope that it will be useful, but         *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
# *   Lesser General Public License for more details.                        *
# *                                                                          *
# *   You should have received a copy of the GNU Lesser General Public       *
# *   License along with FreeCAD. If not, see                                *
# *   <https://www.gnu.org/licenses/>.                                       *
# *                                                                          *
# ***************************************************************************/

"""The import dialog for Onshape variable studio exports (FreeCAD-CH, ops#317 PR G1).

notes/variables-studio.md sections 2.5 and 2.6. The dialog lists the files, the names FreeCAD
can't use with their proposals (editable), each name the files use but don't define with its
three choices (a document variable, never preselected; a value; skip), each name several files
define with the file that provides it, and the report of `copies.plan_import()`. Import is
enabled only when nothing stands in the way; it runs `copies.import_studios()` with the choices,
as one undo step. File > Import ("Onshape variables (.json)", `freecad.variables.importer`) and
the Variables panel's "Import variables..." open it.
"""

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from freecad.variables import copies

translate = App.Qt.translate

FILTER = "Onshape variables (*.json)"
USE, VALUE, SKIP = "use", "value", "skip"
TYPES = (("LENGTH", "Length"), ("ANGLE", "Angle"), ("NUMBER", "Number"))

_open = []  # the dialogs shown with run(), kept until they close


def document_variables(doc, name=None):
    """The paths `Object.Property` of @a doc's VarSet variables that hold a number, a length or
    an angle, the ones named @a name first (section 2.6: listed first, never preselected)."""
    found = []
    for obj in doc.Objects:
        if not obj.isDerivedFrom("App::VarSet"):
            continue
        for prop in obj.PropertiesList:
            # a property every such object has, or a name expressions can't use
            if App.checkVariableName(prop, obj.TypeId):
                continue
            try:
                copies.to_quantity(getattr(obj, prop), prop)
            except Exception:  # noqa: BLE001 (not a number: not offered)
                continue
            found.append((prop != name, obj.Label, prop, f"{obj.Name}.{prop}"))
    return [path for *_key, path in sorted(found)]


class ImportDialog(QtWidgets.QDialog):
    """Imports Onshape exports into @a doc as copies, with the choices of section 2.6."""

    def __init__(self, doc, paths=(), parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.paths = [os.path.abspath(p) for p in paths]
        self.result = None  # the ImportResult once imported
        self.plan = None
        self.base = None  # the plan without choices: the rows
        self.setObjectName("ImportVariablesDialog")
        self.setWindowTitle(translate("Variables", "Import Onshape variables"))
        layout = QtWidgets.QVBoxLayout(self)

        files = QtWidgets.QHBoxLayout()
        self.fileList = QtWidgets.QListWidget(self)
        self.fileList.setObjectName("files")
        files.addWidget(self.fileList)
        fileButtons = QtWidgets.QVBoxLayout()
        self.addButton = QtWidgets.QPushButton(translate("Variables", "Add files..."), self)
        self.addButton.setObjectName("addFiles")
        self.addButton.clicked.connect(self.addFiles)
        self.removeButton = QtWidgets.QPushButton(translate("Variables", "Remove"), self)
        self.removeButton.setObjectName("removeFile")
        self.removeButton.clicked.connect(self.removeFile)
        fileButtons.addWidget(self.addButton)
        fileButtons.addWidget(self.removeButton)
        fileButtons.addStretch()
        files.addLayout(fileButtons)
        layout.addLayout(files)

        self.namesBox = QtWidgets.QGroupBox(
            translate("Variables", "Names FreeCAD can't use, and the names they get"), self)
        self.names = QtWidgets.QTableWidget(0, 2, self.namesBox)
        self.names.setObjectName("names")
        self.names.setHorizontalHeaderLabels(
            [translate("Variables", "Onshape"), translate("Variables", "FreeCAD")])
        self.names.horizontalHeader().setStretchLastSection(True)
        self.names.verticalHeader().hide()
        self.names.itemChanged.connect(lambda _item: self.update())
        QtWidgets.QVBoxLayout(self.namesBox).addWidget(self.names)
        layout.addWidget(self.namesBox)

        self.unresolvedBox = QtWidgets.QGroupBox(
            translate("Variables", "Names the files use but don't define"), self)
        self.unresolvedGrid = QtWidgets.QGridLayout(self.unresolvedBox)
        layout.addWidget(self.unresolvedBox)
        self.ambiguousBox = QtWidgets.QGroupBox(
            translate("Variables", "Names several files define"), self)
        self.ambiguousGrid = QtWidgets.QGridLayout(self.ambiguousBox)
        layout.addWidget(self.ambiguousBox)

        self.report = QtWidgets.QPlainTextEdit(self)
        self.report.setObjectName("report")
        self.report.setReadOnly(True)
        layout.addWidget(self.report)

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.importButton = self.buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self.importButton.setText(translate("Variables", "Import"))
        self.importButton.setObjectName("import")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.unresolved = {}  # name -> (choice, variable, type, value) widgets
        self.ambiguous = {}  # name -> provider combo
        self.resize(640, 560)
        self.filesChanged()

    # The files

    def addFiles(self):
        paths, _filter = QtWidgets.QFileDialog.getOpenFileNames(
            self, translate("Variables", "Onshape variable studio exports"),
            os.path.dirname(self.paths[-1]) if self.paths else "", FILTER)
        self.setPaths(self.paths + [os.path.abspath(p) for p in paths if p])

    def removeFile(self):
        row = self.fileList.currentRow()
        if 0 <= row < len(self.paths):
            self.setPaths(self.paths[:row] + self.paths[row + 1:])

    def setPaths(self, paths):
        unique = []
        for path in paths:
            if path not in unique:
                unique.append(path)
        self.paths = unique
        self.filesChanged()

    def filesChanged(self):
        """Lists the files and makes a row for each name that needs a choice."""
        self.fileList.clear()
        self.fileList.addItems(self.paths)
        self.base = copies.plan_import(self.doc, self.paths)

        self.names.blockSignals(True)
        self.names.setRowCount(0)
        for name, proposal in sorted(self.base.renames.items()):
            row = self.names.rowCount()
            self.names.insertRow(row)
            item = QtWidgets.QTableWidgetItem(name)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.names.setItem(row, 0, item)
            self.names.setItem(row, 1, QtWidgets.QTableWidgetItem(proposal))
        self.names.blockSignals(False)
        self.namesBox.setVisible(bool(self.base.renames))

        _clear(self.unresolvedGrid)
        self.unresolved = {}
        for row, (name, users) in enumerate(sorted(self.base.unresolved.items())):
            self.addUnresolvedRow(row, name, users)
        self.unresolvedBox.setVisible(bool(self.unresolved))

        _clear(self.ambiguousGrid)
        self.ambiguous = {}
        for row, (name, indexes) in enumerate(sorted(self.base.ambiguous.items())):
            label = QtWidgets.QLabel(
                translate("Variables", "#{} is defined in several files; it comes from").format(
                    name), self.ambiguousBox)
            combo = QtWidgets.QComboBox(self.ambiguousBox)
            combo.setObjectName(f"provider_{name}")
            combo.addItem(translate("Variables", "Choose..."), None)
            for index in indexes:
                combo.addItem(self.base.sources[index].label, index)
            combo.currentIndexChanged.connect(lambda _i: self.update())
            self.ambiguousGrid.addWidget(label, row, 0)
            self.ambiguousGrid.addWidget(combo, row, 1)
            self.ambiguous[name] = combo
        self.ambiguousBox.setVisible(bool(self.ambiguous))
        self.update()

    def addUnresolvedRow(self, row, name, users):
        box = self.unresolvedBox
        label = QtWidgets.QLabel(
            translate("Variables", "#{} (used by {})").format(name, ", ".join(users)), box)
        choice = QtWidgets.QComboBox(box)
        choice.setObjectName(f"choice_{name}")
        choice.addItem(translate("Variables", "Choose..."), None)
        choice.addItem(translate("Variables", "Use a document variable"), USE)
        choice.addItem(translate("Variables", "Enter a value"), VALUE)
        choice.addItem(translate("Variables", "Skip"), SKIP)
        variable = QtWidgets.QComboBox(box)
        variable.setObjectName(f"variable_{name}")
        variable.addItem(translate("Variables", "Choose a variable..."), None)
        for path in document_variables(self.doc, name):
            variable.addItem(path, path)
        kind = QtWidgets.QComboBox(box)
        kind.setObjectName(f"type_{name}")
        for onshape_type, text in TYPES:
            kind.addItem(translate("Variables", text), onshape_type)
        value = QtWidgets.QLineEdit(box)
        value.setObjectName(f"value_{name}")
        value.setPlaceholderText(translate("Variables", "a value, e.g. 7 mm"))
        for widget, column in ((label, 0), (choice, 1), (variable, 2), (kind, 3), (value, 4)):
            self.unresolvedGrid.addWidget(widget, row, column)
        choice.currentIndexChanged.connect(lambda _i: self.update())
        variable.currentIndexChanged.connect(lambda _i: self.update())
        kind.currentIndexChanged.connect(lambda _i: self.update())
        value.textChanged.connect(lambda _t: self.update())
        self.unresolved[name] = (choice, variable, kind, value)

    # The plan

    def choices(self):
        """The arguments of copies.plan_import() the widgets give."""
        name_map, bindings, values, skip, providers = {}, {}, {}, [], {}
        for row in range(self.names.rowCount()):
            name = self.names.item(row, 0).text()
            text = self.names.item(row, 1).text().strip()
            if text:
                name_map[name] = text
        for name, (choice, variable, kind, value) in self.unresolved.items():
            what = choice.currentData()
            variable.setVisible(what == USE)
            kind.setVisible(what == VALUE)
            value.setVisible(what == VALUE)
            if what == USE and variable.currentData():
                bindings[name] = variable.currentData()
            elif what == VALUE and value.text().strip():
                values[name] = (kind.currentData(), value.text().strip())
            elif what == SKIP:
                skip.append(name)
        for name, combo in self.ambiguous.items():
            if combo.currentData() is not None:
                providers[name] = combo.currentData()
        return {"name_map": name_map, "bindings": bindings, "values": values, "skip": skip,
                "providers": providers}

    def update(self):
        self.plan = copies.plan_import(self.doc, self.paths, **self.choices())
        if not self.paths:
            text = translate("Variables", "Add the Onshape exports to import.")
        else:
            lines = list(self.plan.problems)
            for source, name, why in self.plan.skipped:
                lines.append(translate("Variables", "{} ({}) is skipped: {}").format(
                    name, self.plan.sources[source].label, why))
            lines.extend(self.plan.warnings)
            text = "\n".join(lines) or translate("Variables", "Nothing stands in the way.")
        self.report.setPlainText(text)
        self.importButton.setEnabled(bool(self.paths) and self.plan.ok)

    def accept(self):
        try:
            self.result = copies.import_studios(self.doc, self.paths, **self.choices())
        except (copies.ImportBlocked, copies.ImportCheckFailed) as e:
            QtWidgets.QMessageBox.critical(
                self, translate("Variables", "Import Onshape variables"), str(e))
            self.update()
            return
        names = ", ".join(copy.Label for copy in self.result.copies)
        App.Console.PrintMessage(
            translate("Variables", "Imported {}").format(names) + "\n")
        super().accept()


def _clear(grid):
    while grid.count():
        widget = grid.takeAt(0).widget()
        if widget is not None:
            widget.deleteLater()


def run(doc=None, paths=None):
    """Opens the import dialog for @a doc (the active document, or a new one) with @a paths; with
    none, asks for the files first. Returns the dialog (shown, not waited for), or None."""
    if paths is None:
        paths, _filter = QtWidgets.QFileDialog.getOpenFileNames(
            Gui.getMainWindow(), translate("Variables", "Onshape variable studio exports"), "",
            FILTER)
        if not paths:
            return None
    if doc is None:
        doc = App.ActiveDocument or App.newDocument()
    dialog = ImportDialog(doc, paths)
    _open.append(dialog)
    dialog.finished.connect(lambda _r: _open.remove(dialog) if dialog in _open else None)
    dialog.open()
    return dialog
