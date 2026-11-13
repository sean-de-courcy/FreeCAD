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
define with the file that provides it, the Onshape document's default units, a Skip box for each
variable refused or caught in a cycle between the copies, and the report of
`copies.plan_import()`. The names a local set of the document defines too have their own box
(ops#640, decision 317): which variable `#name` means, "Use <the files>", "Use local", or "Pick"
per name. Import is
enabled only when nothing stands in the way and each such name has a choice; it runs `copies.import_studios()` with the choices,
as one undo step. File > Import ("Onshape variables (.json)", `freecad.variables.importer`) and
the Variables panel's "Import variables..." open it.

The panel's "Refresh...", "Locate..." and "Copy variables from a FreeCAD file..." open a
`PlanDialog` (ops#317 PRs G2 and F, ops#640 round 5): the preview of what the Refresh or the
copy does (sections 3.3 and 3.4), the same choices for the names the source uses but doesn't
define, and its button to apply it as one undo step.
"""

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from freecad.variables import copies, onshape

translate = App.Qt.translate

FILTER = "Onshape variables (*.json)"
USE, VALUE, SKIP = "use", "value", "skip"
TYPES = (("LENGTH", "Length"), ("ANGLE", "Angle"), ("NUMBER", "Number"))
# The units a unitless Length or Angle can take (the Onshape document's default unit, which the
# export doesn't record): onshape.UNITS' symbols.
DEFAULT_UNITS = (("LENGTH", ("mm", "cm", "m", "in", "ft", "yd")), ("ANGLE", ("deg", "rad")))

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


class ClashBox(QtWidgets.QGroupBox):
    """The names a local set of the document defines too (ops#640, decision 317): which variable
    `#name` means in new expressions, for all of them ("Use <source>", "Use local") or per name
    ("Pick", a choice in each name's row). Nothing is chosen at first: the dialog's button waits
    for a choice. Existing expressions keep the variables they use."""

    def __init__(self, parent, changed):
        super().__init__(translate("Variables", "Names this document already defines"), parent)
        self.setObjectName("clashes")
        self.changed = changed
        layout = QtWidgets.QVBoxLayout(self)
        self.note = QtWidgets.QLabel(self)
        self.note.setObjectName("clashNote")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QtWidgets.QHBoxLayout()
        self.group = QtWidgets.QButtonGroup(self)
        self.useImport = QtWidgets.QRadioButton(self)
        self.useImport.setObjectName("useImport")
        self.useLocal = QtWidgets.QRadioButton(translate("Variables", "Use local"), self)
        self.useLocal.setObjectName("useLocal")
        self.pick = QtWidgets.QRadioButton(translate("Variables", "Pick"), self)
        self.pick.setObjectName("pick")
        for button in (self.useImport, self.useLocal, self.pick):
            self.group.addButton(button)
            buttons.addWidget(button)
            button.toggled.connect(self.onToggled)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.grid = QtWidgets.QGridLayout()
        layout.addLayout(self.grid)
        self.rows = {}  # FreeCAD name -> its combo
        self.setVisible(False)

    def onToggled(self, on):  # not toggled: QGroupBox has that signal
        if on:
            self.showRows()
            self.changed()

    def showRows(self):
        for row in range(self.grid.rowCount()):
            for column in range(self.grid.columnCount()):
                item = self.grid.itemAtPosition(row, column)
                if item is not None and item.widget() is not None:
                    item.widget().setVisible(self.pick.isChecked())

    def sync(self, doc, plan, source):
        """Rows for @a plan's clashes (kept once made, so a choice stays); @a source names what
        is imported, for the button."""
        clashes = getattr(plan, "clashes", {}) if plan is not None else {}
        self.useImport.setText(translate("Variables", "Use {}").format(source))
        self.note.setText(translate(
            "Variables", "These names are defined by a local set here too: choose which variable "
            "#name means in new expressions. Existing expressions keep the variable they use.\n{}"
        ).format("\n".join(f"#{fc}: {', '.join(paths)}" for fc, paths in sorted(clashes.items()))))
        for fc in sorted(clashes):
            if fc in self.rows:
                continue
            row = len(self.rows)
            label = QtWidgets.QLabel(translate("Variables", "#{} means").format(fc), self)
            combo = QtWidgets.QComboBox(self)
            combo.setObjectName(f"clash_{fc}")
            combo.addItem(translate("Variables", "Choose..."), None)
            for path in clashes[fc]:
                combo.addItem(translate("Variables", "{} (local)").format(_labelled(doc, path)),
                              path)
            for path in plan.clash_paths.get(fc, []):
                combo.addItem(translate("Variables", "{} ({})").format(fc, source), path)
            for other in copies.copies_defining(doc, fc):
                path = f"{other.Name}.{fc}"
                if combo.findData(path) < 0:
                    combo.addItem(_labelled(doc, path), path)
            combo.currentIndexChanged.connect(lambda _i: self.changed())
            self.grid.addWidget(label, row, 0)
            self.grid.addWidget(combo, row, 1)
            self.rows[fc] = combo
        self.showRows()
        self.setVisible(bool(clashes))

    def reset(self):
        """Drops the rows (other files: other names)."""
        _clear(self.grid)
        self.rows = {}

    def value(self):
        """plan_import()'s `clashes`: None until a choice is made."""
        if self.useImport.isChecked():
            return copies.IMPORT
        if self.useLocal.isChecked():
            return copies.LOCAL
        if self.pick.isChecked():
            return {fc: combo.currentData() for fc, combo in self.rows.items()
                    if combo.currentData() is not None}
        return None

    def complete(self, plan):
        """Whether every clash of @a plan has a choice."""
        clashes = getattr(plan, "clashes", {}) if plan is not None else {}
        return all(fc in plan.chosen for fc in clashes)


def _labelled(doc, path):
    """`Variables.Width` as the panel names it: the set's label and the variable."""
    obj_name, _, prop = path.partition(".")
    obj = doc.getObject(obj_name)
    return f"{obj.Label}.{prop}" if obj is not None else path


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
        self.clashBox = ClashBox(self, lambda: self.update())
        layout.addWidget(self.clashBox)

        self.skipsBox = QtWidgets.QGroupBox(
            translate("Variables", "Variables that can't be imported as they are"), self)
        self.skipsLayout = QtWidgets.QVBoxLayout(self.skipsBox)
        layout.addWidget(self.skipsBox)

        units = QtWidgets.QHBoxLayout()
        units.addWidget(QtWidgets.QLabel(
            translate("Variables", "Default units of the Onshape document (for values without "
                      "a unit):"), self))
        self.defaultUnits = {}  # Onshape type -> its unit combo
        for onshape_type, symbols in DEFAULT_UNITS:
            combo = QtWidgets.QComboBox(self)
            combo.setObjectName(f"defaultUnit_{onshape_type}")
            combo.addItem(translate("Variables", "{}: not set").format(
                translate("Variables", dict(TYPES)[onshape_type])), None)
            for symbol in symbols:
                combo.addItem(symbol, symbol)
            combo.currentIndexChanged.connect(lambda _i: self.update())
            units.addWidget(combo)
            self.defaultUnits[onshape_type] = combo
        units.addStretch()
        layout.addLayout(units)

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
        self.skips = {}  # variable name -> its Skip check box
        self.nameRows = {}  # Onshape name -> its proposal: the names table's rows
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
        self.names.blockSignals(False)
        self.nameRows = {}
        self.syncNames(self.base.renames)
        _clear(self.skipsLayout)
        self.skips = {}

        _clear(self.unresolvedGrid)
        self.unresolved = {}
        for row, (name, users) in enumerate(sorted(self.base.unresolved.items())):
            self.addUnresolvedRow(row, name, users)
        self.unresolvedBox.setVisible(bool(self.unresolved))

        self.clashBox.reset()
        _clear(self.ambiguousGrid)
        self.ambiguous = {}
        for row, (name, indexes) in enumerate(sorted(self.base.ambiguous.items())):
            label = QtWidgets.QLabel(
                translate("Variables", "#{} is defined in several files; it comes from").format(
                    name), self.ambiguousBox)
            combo = QtWidgets.QComboBox(self.ambiguousBox)
            combo.setObjectName(f"provider_{name}")
            combo.addItem(translate("Variables", "Choose..."), None)
            labels = [self.base.sources[index].label for index in indexes]
            for index, text in zip(indexes, labels):
                source = self.base.sources[index]
                # two files of the same name in different folders: the path tells them apart
                if labels.count(text) > 1:
                    text = f"{text} ({source.path})"
                combo.addItem(text, index)
                combo.setItemData(combo.count() - 1, source.path, QtCore.Qt.ToolTipRole)
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
        for name, box in self.skips.items():
            if box.isChecked():
                skip.append(name)
        default_units = {kind: combo.currentData() for kind, combo in self.defaultUnits.items()
                         if combo.currentData()}
        return {"name_map": name_map, "bindings": bindings, "values": values, "skip": skip,
                "providers": providers, "default_units": default_units,
                "clashes": self.clashBox.value()}

    def syncNames(self, renames):
        """Makes the names table's rows the names of @a renames (Onshape name -> proposal),
        keeping what was typed in the rows that stay."""
        self.namesBox.setVisible(bool(renames))
        if set(renames) == set(self.nameRows):
            return
        typed = {self.names.item(r, 0).text(): self.names.item(r, 1).text()
                 for r in range(self.names.rowCount())}
        self.names.blockSignals(True)
        self.names.setRowCount(0)
        for name, proposal in sorted(renames.items()):
            row = self.names.rowCount()
            self.names.insertRow(row)
            item = QtWidgets.QTableWidgetItem(name)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.names.setItem(row, 0, item)
            self.names.setItem(row, 1, QtWidgets.QTableWidgetItem(typed.get(name, proposal)))
        self.names.blockSignals(False)
        self.nameRows = dict(renames)

    def syncSkips(self):
        """A Skip box for each variable the plan refuses or finds in a cycle between the copies,
        and for each one skipped so far (plan_import's `skip` takes variable names)."""
        wanted = {}
        for source, name, why in self.plan.refused:
            wanted.setdefault(name, f"{self.plan.sources[source].label}: {why}")
        for user, provider, name, ref in self.plan.cycle:
            wanted.setdefault(name, translate(
                "Variables", "{}: uses #{} of {}, which depends on it").format(
                    self.plan.sources[user].label, ref, self.plan.sources[provider].label))
        for name, box in self.skips.items():
            if box.isChecked():
                wanted.setdefault(name, box.toolTip())
        if set(wanted) != set(self.skips):
            checked = {name for name, box in self.skips.items() if box.isChecked()}
            _clear(self.skipsLayout)
            self.skips = {}
            for name, why in sorted(wanted.items()):
                box = QtWidgets.QCheckBox(
                    translate("Variables", "Skip {} ({})").format(name, why), self.skipsBox)
                box.setObjectName(f"skip_{name}")
                box.setToolTip(why)
                box.setChecked(name in checked)
                box.toggled.connect(lambda _on: self.update())
                self.skipsLayout.addWidget(box)
                self.skips[name] = box
        self.skipsBox.setVisible(bool(self.skips))

    def update(self):
        self.plan = copies.plan_import(self.doc, self.paths, **self.choices())
        # a value for a name FreeCAD can't use gets a row in the names table, as a variable does
        self.syncNames({**self.base.renames, **self.plan.input_renames})
        self.syncSkips()
        self.clashBox.sync(self.doc, self.plan,
                           ", ".join(os.path.basename(p) for p in self.paths))
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
        self.importButton.setEnabled(bool(self.paths) and self.plan.ok
                                     and self.clashBox.complete(self.plan))

    def accept(self):
        try:
            self.result = copies.import_studios(self.doc, self.paths, **self.choices())
        except Exception as e:  # noqa: BLE001 (import_studios undid it; any failure is shown)
            QtWidgets.QMessageBox.critical(
                self, translate("Variables", "Import Onshape variables"), str(e))
            self.update()
            return
        names = ", ".join(copy.Label for copy in self.result.copies)
        App.Console.PrintMessage(
            translate("Variables", "Imported {}").format(names) + "\n")
        super().accept()


def _clear(layout):
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.deleteLater()


def run(doc=None, paths=None, close_on_cancel=False):
    """Opens the import dialog for @a doc (the active document, or a new one) with @a paths; with
    none, asks for the files first. Returns the dialog (shown, not waited for, deleted once
    closed), or None. A new document, or @a doc with @a close_on_cancel (File > Open's), is
    closed when the dialog is cancelled."""
    if paths is None:
        paths, _filter = QtWidgets.QFileDialog.getOpenFileNames(
            Gui.getMainWindow(), translate("Variables", "Onshape variable studio exports"), "",
            FILTER)
        if not paths:
            if close_on_cancel and doc is not None:
                App.closeDocument(doc.Name)
            return None
    if doc is None:
        doc = App.ActiveDocument
        if doc is None:
            doc = App.newDocument()
            close_on_cancel = True
    dialog = ImportDialog(doc, paths)
    dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    _open.append(dialog)
    name = doc.Name

    def finished(result):
        if dialog in _open:
            _open.remove(dialog)
        cancelled = result != QtWidgets.QDialog.Accepted
        if close_on_cancel and cancelled and name in App.listDocuments():
            App.closeDocument(name)

    dialog.finished.connect(finished)
    dialog.open()
    return dialog


# --- Refresh, Locate, and copies of a FreeCAD file's variables (ops#317 PRs G2, F; ops#640) ----

FCSTD_FILTER = "FreeCAD documents (*.FCStd)"
FREEZE = "freeze"


class PlanDialog(QtWidgets.QDialog):
    """The preview of a Refresh (notes/variables-studio.md 3.4), or of a copy of a FreeCAD file's
    VarSet (3.3), with a choice for each name the source uses but doesn't define (2.6: a document
    variable, never preselected; a value; the value saved in the file, for a FreeCAD source;
    skip), a provider for a name several copies define, a Switch box for a binding a copy could
    now provide, and a Skip box for each refused variable. Its button is enabled only when
    nothing stands in the way, and applies it as one undo step.

    @a planner(choices) gives the plan (copies.RefreshPlan), @a applier(choices) applies it."""

    def __init__(self, doc, title, planner, applier, button, default_units=False, exclude=None,
                 parent=None, source=""):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.source = source  # the source file's name, for the clash box
        self.planner = planner
        self.applier = applier
        self.exclude = exclude  # a copy's own variables aren't offered to it
        self.result = None
        self.plan = None
        self.setObjectName("variablesPlanDialog")
        self.setWindowTitle(title)
        layout = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel(self)
        self.summary.setObjectName("summary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.unresolvedBox = QtWidgets.QGroupBox(
            translate("Variables", "Names the source uses but doesn't define"), self)
        self.unresolvedGrid = QtWidgets.QGridLayout(self.unresolvedBox)
        layout.addWidget(self.unresolvedBox)
        self.providersBox = QtWidgets.QGroupBox(
            translate("Variables", "Names several copies define"), self)
        self.providersGrid = QtWidgets.QGridLayout(self.providersBox)
        layout.addWidget(self.providersBox)
        self.switchBox = QtWidgets.QGroupBox(
            translate("Variables", "Bindings another copy could provide"), self)
        self.switchLayout = QtWidgets.QVBoxLayout(self.switchBox)
        layout.addWidget(self.switchBox)
        self.clashBox = ClashBox(self, lambda: self.update())
        layout.addWidget(self.clashBox)
        self.skipsBox = QtWidgets.QGroupBox(
            translate("Variables", "Variables that can't be copied as they are"), self)
        self.skipsLayout = QtWidgets.QVBoxLayout(self.skipsBox)
        layout.addWidget(self.skipsBox)

        self.defaultUnits = {}
        if default_units:
            units = QtWidgets.QHBoxLayout()
            units.addWidget(QtWidgets.QLabel(
                translate("Variables", "Default units of the Onshape document (for values "
                          "without a unit; read back from the copy when not set):"), self))
            for onshape_type, symbols in DEFAULT_UNITS:
                combo = QtWidgets.QComboBox(self)
                combo.setObjectName(f"defaultUnit_{onshape_type}")
                combo.addItem(translate("Variables", "{}: as before").format(
                    translate("Variables", dict(TYPES)[onshape_type])), None)
                for symbol in symbols:
                    combo.addItem(symbol, symbol)
                combo.currentIndexChanged.connect(lambda _i: self.update())
                units.addWidget(combo)
                self.defaultUnits[onshape_type] = combo
            units.addStretch()
            layout.addLayout(units)

        self.report = QtWidgets.QPlainTextEdit(self)
        self.report.setObjectName("report")
        self.report.setReadOnly(True)
        layout.addWidget(self.report)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.applyButton = self.buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self.applyButton.setText(button)
        self.applyButton.setObjectName("apply")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.rows = {}  # name -> (choice, variable, type, value) widgets
        self.providers = {}  # name -> its provider combo
        self.switches = {}  # name -> its Switch box
        self.skips = {}  # variable name -> its Skip box
        self.resize(640, 520)
        self.update()

    def addRow(self, name, users, frozen):
        box = self.unresolvedBox
        row = len(self.rows)
        label = QtWidgets.QLabel(
            translate("Variables", "{} (used by {})").format(name, ", ".join(users) or "-"), box)
        choice = QtWidgets.QComboBox(box)
        choice.setObjectName(f"choice_{name}")
        choice.addItem(translate("Variables", "Choose..."), None)
        choice.addItem(translate("Variables", "Use a document variable"), USE)
        choice.addItem(translate("Variables", "Enter a value"), VALUE)
        if frozen is not None:
            choice.addItem(translate("Variables", "Use its saved value ({})").format(frozen),
                           FREEZE)
        choice.addItem(translate("Variables", "Skip"), SKIP)
        variable = QtWidgets.QComboBox(box)
        variable.setObjectName(f"variable_{name}")
        variable.addItem(translate("Variables", "Choose a variable..."), None)
        short = name.rsplit(".", 1)[-1]
        for path in document_variables(self.doc, short):
            if self.exclude is None or not path.startswith(self.exclude + "."):
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
        self.rows[name] = (choice, variable, kind, value)

    def choices(self):
        """The choice arguments of copies.plan_refresh() / plan_copy() the widgets give."""
        bindings, values, skip, freeze, providers, switch = {}, {}, [], [], {}, []
        for name, (choice, variable, kind, value) in self.rows.items():
            what = choice.currentData()
            variable.setVisible(what == USE)
            kind.setVisible(what == VALUE)
            value.setVisible(what == VALUE)
            if what == USE and variable.currentData():
                bindings[name] = variable.currentData()
            elif what == VALUE and value.text().strip():
                values[name] = (kind.currentData(), value.text().strip())
            elif what == FREEZE:
                freeze.append(name)
            elif what == SKIP:
                skip.append(name)
        for name, combo in self.providers.items():
            if combo.currentData() is not None:
                providers[name] = combo.currentData()
        for name, box in self.switches.items():
            if box.isChecked():
                switch.append(name)
        for name, box in self.skips.items():
            if box.isChecked():
                skip.append(name)
        result = {"bindings": bindings, "values": values, "skip": skip, "freeze": freeze,
                  "providers": providers, "switch": switch, "clashes": self.clashBox.value()}
        units = {kind: combo.currentData() for kind, combo in self.defaultUnits.items()
                 if combo.currentData()}
        if units:
            result["default_units"] = units
        return result

    def sync(self):
        """Rows for what the plan asks about (kept once made, so a choice stays visible)."""
        for name, users in sorted(self.plan.unresolved.items()):
            if name not in self.rows:
                self.addRow(name, users, self.plan.freezable.get(name))
        self.unresolvedBox.setVisible(bool(self.rows))
        for name, names in sorted(self.plan.ambiguous.items()):
            if name in self.providers:
                continue
            row = len(self.providers)
            label = QtWidgets.QLabel(
                translate("Variables", "#{} is defined by several copies; it comes from").format(
                    name), self.providersBox)
            combo = QtWidgets.QComboBox(self.providersBox)
            combo.setObjectName(f"provider_{name}")
            combo.addItem(translate("Variables", "Choose..."), None)
            for copy_name in names:
                obj = self.doc.getObject(copy_name)
                combo.addItem(obj.Label if obj is not None else copy_name, copy_name)
            combo.currentIndexChanged.connect(lambda _i: self.update())
            self.providersGrid.addWidget(label, row, 0)
            self.providersGrid.addWidget(combo, row, 1)
            self.providers[name] = combo
        self.providersBox.setVisible(bool(self.providers))
        for name, (bound, where) in sorted(self.plan.switchable.items()):
            if name in self.switches:
                continue
            box = QtWidgets.QCheckBox(
                translate("Variables", "Switch #{} from {} to {}").format(name, bound, where),
                self.switchBox)
            box.setObjectName(f"switch_{name}")
            box.toggled.connect(lambda _on: self.update())
            self.switchLayout.addWidget(box)
            self.switches[name] = box
        self.switchBox.setVisible(bool(self.switches))
        for name, why in self.plan.refused:
            if name in self.skips:
                continue
            box = QtWidgets.QCheckBox(translate("Variables", "Skip {} ({})").format(name, why),
                                      self.skipsBox)
            box.setObjectName(f"skip_{name}")
            box.setToolTip(why)
            box.toggled.connect(lambda _on: self.update())
            self.skipsLayout.addWidget(box)
            self.skips[name] = box
        self.skipsBox.setVisible(bool(self.skips))

    def update(self):
        try:
            self.plan = self.planner(self.choices())
        except Exception as e:  # noqa: BLE001 (a source that can't be read is shown)
            self.plan = None
            self.summary.setText(str(e))
            self.report.setPlainText(str(e))
            self.applyButton.setEnabled(False)
            return
        self.sync()
        self.clashBox.sync(self.doc, self.plan, self.source)
        if self.plan.copy is not None:
            self.summary.setText(self.plan.summary())
        else:
            self.summary.setText(translate("Variables", "{} variables to copy").format(
                len(self.plan.targets)))
        self.report.setPlainText(self.plan.report())
        self.applyButton.setEnabled(self.plan.ok and self.clashBox.complete(self.plan))

    def accept(self):
        try:
            self.result = self.applier(self.choices())
        except Exception as e:  # noqa: BLE001 (nothing was changed; any failure is shown)
            QtWidgets.QMessageBox.critical(self, self.windowTitle(), str(e))
            self.update()
            return
        super().accept()


def _keep(dialog):
    """Shows @a dialog (not waited for), kept until it closes, then deleted."""
    dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    _open.append(dialog)

    def finished(_result):
        if dialog in _open:
            _open.remove(dialog)

    dialog.finished.connect(finished)
    dialog.open()
    return dialog


def refresh(copy, path=None, entry=None, varset=None):
    """The Refresh preview of @a copy (or Locate: from @a path, with @a entry or @a varset); its
    Refresh button applies it as one undo step. Returns the dialog (shown, not waited for)."""

    def planner(choices):
        return copies.plan_refresh(copy, path, entry=entry, varset=varset, **choices)

    def applier(choices):
        plan = copies.refresh(copy, path, entry=entry, varset=varset, **choices)
        App.Console.PrintMessage(translate("Variables", "Refreshed {}: {}").format(
            copy.Label, plan.summary()) + "\n")
        return plan

    title = translate("Variables", "Refresh {}").format(copy.Label)
    return _keep(PlanDialog(copy.Document, title, planner, applier,
                            translate("Variables", "Refresh"),
                            default_units=copy.SourceKind == copies.JSON_KIND,
                            exclude=copy.Name,
                            source=os.path.basename(path or copy.SourcePath) or copy.Label))


def _pick(title, label, items, current=0):
    """One of @a items (texts) by its index, or None; asks only when there are several."""
    if len(items) == 1:
        return 0
    text, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), title, label, items,
                                              max(0, min(current, len(items) - 1)), False)
    if not ok:
        return None
    return items.index(text)


def _varset(path, title, current=None):
    """The internal name of a VarSet of the saved document @a path, chosen if it has several."""
    try:
        sets = copies.fcstd_varsets(path)
    except (OSError, copies.SourceError) as e:
        QtWidgets.QMessageBox.critical(Gui.getMainWindow(), title,
                                       f"{os.path.basename(path)} can't be read: {e}")
        return None
    if not sets:
        QtWidgets.QMessageBox.critical(Gui.getMainWindow(), title, translate(
            "Variables", "{} has no VarSet").format(os.path.basename(path)))
        return None
    items = [translate("Variables", "{} ({}, {} variables)").format(label, name, count)
             for name, label, count in sets]
    names = [name for name, _label, _count in sets]
    index = _pick(title, translate("Variables", "VarSet:"), items,
                  names.index(current) if current in names else 0)
    return None if index is None else names[index]


def locate(copy, path=None, entry=None, varset=None):
    """Locate...: points @a copy at another file (asked for when @a path is None), and an entry
    (JSON) or a VarSet (FreeCAD) in it, then shows the Refresh preview for it."""
    title = translate("Variables", "Locate the source of {}").format(copy.Label)
    json_source = copy.SourceKind == copies.JSON_KIND
    if path is None:
        start = os.path.dirname(copy.SourcePath) if copy.SourcePath else ""
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            Gui.getMainWindow(), title, start, FILTER if json_source else FCSTD_FILTER)
        if not path:
            return None
    if json_source and entry is None:
        try:
            entries = onshape.read_export(path)
        except (OSError, onshape.ExportError) as e:
            QtWidgets.QMessageBox.critical(Gui.getMainWindow(), title,
                                           f"{os.path.basename(path)} can't be read: {e}")
            return None
        items = [translate("Variables", "Studio entry {} ({} variables)").format(
            i + 1, len(e.variables)) for i, e in enumerate(entries)]
        if not items:
            return None
        try:
            current = int(copy.SourceObject)
        except ValueError:
            current = 0
        entry = _pick(title, translate("Variables", "Studio entry:"), items, current)
        if entry is None:
            return None
    if not json_source and varset is None:
        varset = _varset(path, title, copy.SourceObject)
        if varset is None:
            return None
    return refresh(copy, path, entry=entry, varset=varset)


def copy_from_file(doc=None, path=None, varset=None, studio=None):
    """"Copy variables from a FreeCAD file...": a saved document (asked for when @a path is
    None) and a VarSet in it (asked for when it has several), read from the file without opening
    it; the dialog shows what will be copied and the choices, its Copy button makes the copy
    (section 3.3). With @a studio (a Variable Studio's "Insert Variable Studio..."), the copy
    joins the end of its reference list (ops#721). Returns the dialog, or None."""
    title = translate("Variables", "Copy variables from a FreeCAD file")
    if path is None:
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), title, "",
                                                              FCSTD_FILTER)
        if not path:
            return None
    if varset is None:
        varset = _varset(path, title)
        if varset is None:
            return None
    if doc is None:
        doc = App.ActiveDocument or App.newDocument()

    def planner(choices):
        return copies.plan_copy(doc, path, varset, **choices)

    def applier(choices):
        if studio is not None:
            copy = copies.reference_from_fcstd(studio, path, varset, **choices)
        else:
            copy = copies.copy_from_fcstd(doc, path, varset, **choices)
        App.Console.PrintMessage(translate("Variables", "Copied {} from {}").format(
            copy.Label, os.path.basename(path)) + "\n")
        return copy

    title = translate("Variables", "Copy variables from {}").format(os.path.basename(path))
    return _keep(PlanDialog(doc, title, planner, applier, translate("Variables", "Copy"),
                            source=os.path.basename(path)))
