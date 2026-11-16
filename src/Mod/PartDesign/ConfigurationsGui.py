# SPDX-License-Identifier: LGPL-2.1-or-later

"""The Configuration panel, Onshape's (FreeCAD-CH ops#671, slice C2; notes/configurations-design.md
3.8). A dock with one tab per configuration input of a part studio: a List's table (its rows by the
parameters and suppressions it configures, in feature order); a Checkbox's two rows; a Variable's
default and bounds. As in Onshape (CP2, oracle 9f): the active row carries the bar and the default
is named above the table; a click selects a cell and a double-click edits it, and rows switch,
become the default, are duplicated, moved and deleted from the row's menu. Inputs are renamed,
moved and deleted from the head. Every edit is one undo step through the PartDesign.config*
calls (the App side, slice C1).

The configuration items of a field's context menu (Gui core's spin boxes, the sketch's constraint
list, the Features list rows) come from PartDesign.configMenuItems (Onshape's "Configure", "Configure
with <input>", "Set to #<variable>", "Unconfigure from <input>"; none while the studio has no input)
and run `fieldAction`; Gui core reaches it through
the App hook, as it can't import PartDesign. The Features list's Configurations button runs
`openFor`, and calls `follow` when its studio changes."""

import json

import FreeCAD
import FreeCADGui
import PartDesign
from PySide import QtCore, QtGui, QtWidgets

PANEL = "Configurations"
DOCK = "ConfigurationsDock"
ROW_ID = QtCore.Qt.UserRole
NEW_LIST_NAME = "Configuration"


def _tr(text):
    return QtCore.QCoreApplication.translate("PartDesign_Configurations", text)


# ---------------------------------------------------------------------------------- the model
def studioOf(doc, name):
    """The studio a [document, studio name] pair names: a Part, or the document ('' name)"""
    if doc is None:
        return None
    return doc.getObject(name) if name else doc


def documentOf(studio):
    return studio if isinstance(studio, FreeCAD.Document) else studio.Document


def inputsOf(studio):
    cfg = PartDesign.configStudio(studio) if studio is not None else None
    if cfg is None or not cfg.Inputs:
        return []
    return json.loads(cfg.Inputs).get("inputs", [])


def activeOf(studio, inp):
    """The active row id (List), 'true'/'false' (Checkbox) or value text (Variable) of inp"""
    cfg = PartDesign.configStudio(studio)
    active = dict(cfg.Active) if cfg is not None else {}
    value = active.get(inp["id"])
    if inp["kind"] == "list":
        ids = [r["id"] for r in inp["rows"]]
        return value if value in ids else inp.get("default", ids[0] if ids else "")
    if inp["kind"] == "checkbox":
        if value in ("true", "false"):
            return value
        return "true" if inp.get("default", True) else "false"
    return value if value is not None else str(inp.get("default", ""))


def valueText(inp, value):
    """A Variable's internal value (mm, degrees) as the user's text"""
    kind = inp.get("type")
    if kind == "Length":
        return FreeCAD.Units.Quantity(float(value), FreeCAD.Units.Length).UserString
    if kind == "Angle":
        return FreeCAD.Units.Quantity(float(value), FreeCAD.Units.Angle).UserString
    if kind == "Integer":
        return str(int(round(float(value))))
    return str(value)


def entryTitle(entry):
    """Onshape's column heads (CP2-4): "Extrude B / Depth", and "Extrude E / Unsuppressed" for a
    suppression, whose tick means unsuppressed"""
    obj = entry["object"]
    if entry["path"] is None:
        return _tr("{} / Unsuppressed").format(obj.Label)
    return "{} / {}".format(obj.Label, entry["path"])


def activeMarker():
    """The bar that marks the active row in the Name column (CP2-4)"""
    pix = QtGui.QPixmap(4, 16)
    pix.fill(QtGui.QColor(52, 120, 220))
    return QtGui.QIcon(pix)


def edit(doc, title, fn):
    """fn as one undo step, then a recompute; a refusal aborts the step and raises. Inside an open
    dialog's transaction, fn joins that edit (Onshape: cancelling the dialog undoes it, CP2-1)"""
    if doc.HasPendingTransaction:
        out = fn()
        doc.recompute()
        return out
    doc.openTransaction(title)
    try:
        out = fn()
    except Exception:
        doc.abortTransaction()
        raise
    doc.recompute()
    doc.commitTransaction()
    return out


# ------------------------------------------------------------------- dialogs (tests replace them)
def askText(title, label, text=""):
    value, ok = QtWidgets.QInputDialog.getText(FreeCADGui.getMainWindow(), title, label, text=text)
    return value if ok and value else None


# --------------------------------------------------------------------------------- the panel
class ConfigurationsPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName(PANEL)
        self.studio = None
        self._building = False
        self._observer = None
        self._pending = False

        layout = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel()
        self.title.setObjectName("configStudio")
        head.addWidget(self.title, 1)
        self.addButton = QtWidgets.QToolButton()
        self.addButton.setObjectName("configAddInput")
        self.addButton.setText(_tr("Add input"))
        self.addButton.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(self.addButton)
        menu.addAction(_tr("List"), self.promptAddList).setObjectName("configAddList")
        menu.addAction(_tr("Checkbox"), self.promptAddCheckbox).setObjectName("configAddCheckbox")
        menu.addAction(_tr("Variable"), self.promptAddVariable).setObjectName("configAddVariable")
        self.addButton.setMenu(menu)
        head.addWidget(self.addButton)
        self.renameButton = QtWidgets.QToolButton()
        self.renameButton.setObjectName("configRenameInput")
        self.renameButton.setText(_tr("Rename"))
        self.renameButton.clicked.connect(self.promptRenameInput)
        head.addWidget(self.renameButton)
        self.removeButton = QtWidgets.QToolButton()
        self.removeButton.setObjectName("configRemoveInput")
        self.removeButton.setText(_tr("Remove"))
        self.removeButton.clicked.connect(lambda: self.removeInput(self.currentInput()))
        head.addWidget(self.removeButton)
        self.moveInputButtons = []
        for name, text, step in (("configMoveInputUp", _tr("Move up"), -1), ("configMoveInputDown", _tr("Move down"), 1)):
            b = QtWidgets.QToolButton()
            b.setObjectName(name)
            b.setText(text)
            b.clicked.connect(lambda checked=False, st=step: self.moveInput(self.currentInput(), st))
            head.addWidget(b)
            self.moveInputButtons.append(b)
        layout.addLayout(head)
        # Onshape's "Configure Part Studio": the first input, a List "Configuration" with one row
        # "Default" (CP2-1); fields offer no configure item before it
        self.createButton = QtWidgets.QPushButton(_tr("Configure studio"))
        self.createButton.setObjectName("configCreate")
        self.createButton.clicked.connect(self.createFirstInput)
        layout.addWidget(self.createButton)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("configTabs")
        layout.addWidget(self.tabs, 1)
        self.empty = QtWidgets.QLabel(
            _tr("Right click sketch dimensions, features, or feature parameters to configure them.")
        )
        self.empty.setObjectName("configEmpty")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("configMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        layout.addWidget(self.message)

    # -------------------------------------------------------------------------- the studio
    def setStudio(self, studio):
        self.studio = studio
        self._watch()
        self.refresh()

    def _watch(self):
        if self._observer is None:
            self._observer = _Observer(self)
            FreeCAD.addDocumentObserver(self._observer)

    def closeEvent(self, event):
        self.detach()
        super().closeEvent(event)

    def detach(self):
        if self._observer is not None:
            FreeCAD.removeDocumentObserver(self._observer)
            self._observer = None

    def config(self):
        return PartDesign.configStudio(self.studio) if self.studio is not None else None

    def scheduleRefresh(self):
        if not self._pending:
            self._pending = True
            QtCore.QTimer.singleShot(0, self.refresh)

    # --------------------------------------------------------------------------- building
    def currentInput(self):
        w = self.tabs.currentWidget()
        return w.property("inputId") if w is not None else None

    def refresh(self):
        self._pending = False
        current = self.currentInput()
        self._building = True
        try:
            while self.tabs.count():
                w = self.tabs.widget(0)
                self.tabs.removeTab(0)
                # Out of the panel now (a name lookup finds the new tab), deleted later
                w.setParent(None)
                w.deleteLater()
            if self.studio is None:
                self.title.setText(_tr("No part studio"))
                inputs = []
            else:
                self.title.setText(self.studio.Label)
                inputs = inputsOf(self.studio)
            entries = PartDesign.configEntries(self.studio) if inputs else []
            for inp in inputs:
                mine = [e for e in entries if e["input"] == inp["id"]]
                if inp["kind"] == "list":
                    w = self._listTab(inp, mine)
                elif inp["kind"] == "checkbox":
                    w = self._checkboxTab(inp, mine)
                else:
                    w = self._variableTab(inp)
                w.setProperty("inputId", inp["id"])
                w.setObjectName("configTab_" + inp["id"])
                self.tabs.addTab(w, inp["name"])
                if inp["id"] == current:
                    self.tabs.setCurrentWidget(w)
            self.tabs.setVisible(bool(inputs))
            self.empty.setVisible(not inputs)
            self.renameButton.setEnabled(bool(inputs))
            self.removeButton.setEnabled(bool(inputs))
            for b in self.moveInputButtons:
                b.setEnabled(len(inputs) > 1)
            self.createButton.setVisible(self.studio is not None and not inputs)
        finally:
            self._building = False

    def _table(self, inp, rows, entries):
        """rows: [(key, shown name)]; one column per entry after the Name column"""
        table = QtWidgets.QTableWidget(len(rows), 1 + len(entries))
        table.setObjectName("configTable_" + inp["id"])
        table.setHorizontalHeaderLabels([_tr("Name")] + [entryTitle(e) for e in entries])
        table.verticalHeader().setVisible(False)
        # A click selects a cell, a double-click edits it; it doesn't switch rows (CP2-4)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        active = activeOf(self.studio, inp)
        for r, (key, name) in enumerate(rows):
            item = QtWidgets.QTableWidgetItem(name)
            item.setData(ROW_ID, key)
            if inp["kind"] != "list":
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            table.setItem(r, 0, item)
            for c, e in enumerate(entries, start=1):
                text = e["cells"].get(key, "")
                cell = QtWidgets.QTableWidgetItem()
                cell.setData(ROW_ID, key)
                if e["path"] is None:
                    cell.setFlags((cell.flags() | QtCore.Qt.ItemIsUserCheckable) & ~QtCore.Qt.ItemIsEditable)
                    # The tick means unsuppressed (Onshape's "Unsuppressed" column, CP2-4)
                    cell.setCheckState(QtCore.Qt.Unchecked if text == "true" else QtCore.Qt.Checked)
                else:
                    cell.setText(text)
                table.setItem(r, c, cell)
            if key == active:
                # The active row: the bar and blue text (CP2-4)
                item.setIcon(activeMarker())
                item.setData(QtCore.Qt.UserRole + 1, "active")
                item.setToolTip(_tr("The active configuration"))
                for c in range(table.columnCount()):
                    table.item(r, c).setForeground(QtGui.QBrush(QtGui.QColor(40, 100, 200)))
        header = table.horizontalHeader()
        header.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(
            lambda pos, t=table, es=entries: self._headerMenu(t, es, t.horizontalHeader().logicalIndexAt(pos))
        )
        table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(
            lambda pos, t=table, i=inp: self._execRowMenu(t, i, t.itemAt(pos))
        )
        table.setProperty("entryCount", len(entries))
        table.itemChanged.connect(lambda item, i=inp, es=entries: self._cellChanged(i, es, item))
        table.resizeColumnsToContents()
        return table

    def _listTab(self, inp, entries):
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        rows = [(r["id"], r["name"]) for r in inp["rows"]]
        default = next((name for key, name in rows if key == inp.get("default")), "")
        layout.addWidget(self._defaultLabel(default))
        layout.addWidget(self._table(inp, rows, entries), 1)
        add = QtWidgets.QPushButton(_tr("Add row"))
        add.setObjectName("configAddRow")
        add.clicked.connect(lambda: self.addRow(inp["id"]))
        layout.addWidget(add, 0, QtCore.Qt.AlignLeft)
        return w

    def _checkboxTab(self, inp, entries):
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        # No Edit definition: the default changes through a row's "Set as default" (CP2-7)
        rows = [("true", _tr("Checked")), ("false", _tr("Unchecked"))]
        layout.addWidget(self._defaultLabel(rows[0][1] if inp.get("default", True) else rows[1][1]))
        layout.addWidget(self._table(inp, rows, entries), 1)
        return w

    @staticmethod
    def _defaultLabel(name):
        """The block header that names the default row (CP2-4: "Default: Small")"""
        label = QtWidgets.QLabel(_tr("Default: {}").format(name))
        label.setObjectName("configDefaultLabel")
        return label

    def _variableTab(self, inp):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        form.addRow(_tr("Type"), QtWidgets.QLabel(inp.get("type", "")))
        form.addRow(_tr("Use as"), QtWidgets.QLabel("#" + inp["name"]))
        fields = {}
        for key, label in (("default", _tr("Default")), ("min", _tr("Minimum")), ("max", _tr("Maximum"))):
            if key != "default" and inp.get("type") == "Text":
                continue
            line = QtWidgets.QLineEdit()
            line.setObjectName("configVariable_" + key)
            if key in inp:
                line.setText(valueText(inp, inp[key]) if inp.get("type") != "Text" else str(inp[key]))
            form.addRow(label, line)
            fields[key] = line
        apply = QtWidgets.QPushButton(_tr("Apply"))
        apply.setObjectName("configVariableApply")

        def check():
            # Onshape (CP2-7): a maximum below the default (or a minimum above it) turns the boxes
            # red and greys out OK
            bad = variableProblem(inp, {k: f.text() for k, f in fields.items()})
            for k, f in fields.items():
                f.setStyleSheet("QLineEdit { color: #c0392b; }" if k in bad else "")
            apply.setEnabled(not bad)

        for f in fields.values():
            f.textChanged.connect(lambda text: check())
        check()
        apply.clicked.connect(
            lambda: self.editVariable(
                inp["id"],
                fields["default"].text(),
                fields["min"].text() if "min" in fields else "",
                fields["max"].text() if "max" in fields else "",
            )
        )
        form.addRow(apply)
        return w


    def _headerMenu(self, table, entries, column):
        if column < 1 or column > len(entries):
            return
        entry = entries[column - 1]
        menu = QtWidgets.QMenu(table)
        menu.addAction(_tr("Delete column"), lambda: self.unconfigure(entry["object"], entry["path"])).setObjectName(
            "configDeleteColumn"
        )
        menu.exec_(QtGui.QCursor.pos())

    def rowMenu(self, inputId, key, parent=None):
        """A row's menu (CP2-4): Switch to "<row>", Set as default (not on the default row), and for a
        List row Duplicate row, Move up, Move down, Delete row"""
        inp = next(i for i in inputsOf(self.studio) if i["id"] == inputId)
        menu = QtWidgets.QMenu(parent or self)
        if inp["kind"] == "list":
            ids = [r["id"] for r in inp["rows"]]
            name = next(r["name"] for r in inp["rows"] if r["id"] == key)
            isDefault = key == inp.get("default")
        else:
            ids = ["true", "false"]
            name = _tr("Checked") if key == "true" else _tr("Unchecked")
            isDefault = (key == "true") == bool(inp.get("default", True))

        def add(objectName, text, fn, enabled=True):
            action = menu.addAction(text, fn)
            action.setObjectName(objectName)
            action.setEnabled(enabled)

        add("configRowSwitch", _tr('Switch to "{}"').format(name), lambda: self.switchTo(inputId, key),
            key != activeOf(self.studio, inp))
        if not isDefault:
            add("configRowSetDefault", _tr("Set as default"), lambda: self.setDefaultRow(inputId, key))
        if inp["kind"] == "list":
            add("configRowDuplicate", _tr("Duplicate row"), lambda: self.duplicateRow(inputId, key))
            add("configRowMoveUp", _tr("Move up"), lambda: self.moveRow(inputId, key, -1), ids.index(key) > 0)
            add("configRowMoveDown", _tr("Move down"), lambda: self.moveRow(inputId, key, 1), ids.index(key) < len(ids) - 1)
            add("configRowDelete", _tr("Delete row"), lambda: self.removeRow(inputId, key), len(ids) > 1)
        return menu

    def _execRowMenu(self, table, inp, item):
        if item is None:
            return
        key = table.item(item.row(), 0).data(ROW_ID)
        self.rowMenu(inp["id"], key, table).exec_(QtGui.QCursor.pos())

    # ------------------------------------------------------------------------------ edits
    def run(self, title, fn):
        """One undo step; a refusal is shown in the panel, and the panel shows the model again"""
        self.message.clear()
        try:
            return edit(documentOf(self.studio), title, fn)
        except Exception as exc:
            self.message.setText(str(exc))
            FreeCAD.Console.PrintWarning("Configurations: {}\n".format(exc))
            return None
        finally:
            self.scheduleRefresh()

    def _cellChanged(self, inp, entries, item):
        if self._building:
            return
        key = item.data(ROW_ID)
        col = item.column()
        if col == 0:
            self.renameRow(inp["id"], key, item.text())
            return
        entry = entries[col - 1]
        if entry["path"] is None:
            suppressed = item.checkState() != QtCore.Qt.Checked
            self.run(
                _tr("Configure suppression"),
                lambda: PartDesign.configSetSuppressionCell(entry["object"], key, suppressed),
            )
        else:
            text = item.text()
            self.run(_tr("Configure value"), lambda: PartDesign.configSetCell(entry["object"], entry["path"], key, text))

    def addList(self, name, rows=None):
        return self.run(_tr("Add configuration input"), lambda: PartDesign.configAddList(self.studio, name, rows or []))

    def addCheckbox(self, name, default=True):
        return self.run(_tr("Add configuration input"), lambda: PartDesign.configAddCheckbox(self.studio, name, default))

    def addVariable(self, name, kind, default, minimum=None, maximum=None):
        return self.run(
            _tr("Add configuration input"),
            lambda: PartDesign.configAddVariable(self.studio, name, kind, default, minimum, maximum),
        )

    def renameInput(self, inputId, name):
        return self.run(_tr("Rename configuration input"), lambda: PartDesign.configRenameInput(self.studio, inputId, name))

    def removeInput(self, inputId):
        """No confirmation; what it configured keeps the active row's values (CP2-6)"""
        if inputId:
            return self.run(_tr("Remove configuration input"), lambda: PartDesign.configRemoveInput(self.studio, inputId))

    def moveInput(self, inputId, step):
        ids = [i["id"] for i in inputsOf(self.studio)]
        if inputId not in ids or not 0 <= ids.index(inputId) + step < len(ids):
            return None
        return self.run(
            _tr("Reorder configuration inputs"),
            lambda: PartDesign.configMoveInput(self.studio, inputId, ids.index(inputId) + step),
        )

    def createFirstInput(self):
        """Onshape's "Configure Part Studio": a List "Configuration" with one row "Default" """
        return self.addList(_newListName(self.studio), ["Default"])

    def switchTo(self, inputId, key):
        inp = next(i for i in inputsOf(self.studio) if i["id"] == inputId)
        value = (key == "true") if inp["kind"] == "checkbox" else key
        return self.run(_tr("Switch configuration"), lambda: PartDesign.configSetActive(self.studio, {inputId: value}))

    def duplicateRow(self, inputId, rowId):
        """A copy of the row's cells, right below it"""
        inp = next(i for i in inputsOf(self.studio) if i["id"] == inputId)
        ids = [r["id"] for r in inp["rows"]]
        source = next(r["name"] for r in inp["rows"] if r["id"] == rowId)
        taken = {r["name"] for r in inp["rows"]} | set(ids)
        name, n = _tr("{} copy").format(source), 2
        while name in taken:
            name = _tr("{} copy {}").format(source, n)
            n += 1
        entries = [e for e in PartDesign.configEntries(self.studio) if e["input"] == inputId]

        def apply():
            new = PartDesign.configAddRow(self.studio, inputId, name)
            for e in entries:
                if rowId not in e["cells"]:
                    continue
                if e["path"] is None:
                    PartDesign.configSetSuppressionCell(e["object"], new, e["cells"][rowId] == "true")
                else:
                    PartDesign.configSetCell(e["object"], e["path"], new, e["cells"][rowId])
            PartDesign.configMoveRow(self.studio, inputId, new, ids.index(rowId) + 1)
            return new

        return self.run(_tr("Duplicate configuration"), apply)

    def addRow(self, inputId, name=None):
        inp = next(i for i in inputsOf(self.studio) if i["id"] == inputId)
        if name is None:
            taken = {r["name"] for r in inp["rows"]} | {r["id"] for r in inp["rows"]}
            n = len(inp["rows"]) + 1
            while "Configuration {}".format(n) in taken:
                n += 1
            name = "Configuration {}".format(n)
        return self.run(_tr("Add configuration"), lambda: PartDesign.configAddRow(self.studio, inputId, name))

    def renameRow(self, inputId, rowId, name):
        return self.run(_tr("Rename configuration"), lambda: PartDesign.configRenameRow(self.studio, inputId, rowId, name))

    def removeRow(self, inputId, rowId):
        if rowId:
            return self.run(_tr("Remove configuration"), lambda: PartDesign.configRemoveRow(self.studio, inputId, rowId))

    def moveRow(self, inputId, rowId, step):
        if not rowId:
            return None
        inp = next(i for i in inputsOf(self.studio) if i["id"] == inputId)
        ids = [r["id"] for r in inp["rows"]]
        index = ids.index(rowId) + step
        if index < 0 or index >= len(ids):
            return None
        out = self.run(_tr("Reorder configurations"), lambda: PartDesign.configMoveRow(self.studio, inputId, rowId, index))
        QtCore.QTimer.singleShot(0, lambda: self.selectRow(inputId, rowId))
        return out

    def selectRow(self, inputId, rowId):
        table = self.findChild(QtWidgets.QTableWidget, "configTable_" + inputId)
        if table is None:
            return
        for r in range(table.rowCount()):
            if table.item(r, 0).data(ROW_ID) == rowId:
                table.setCurrentCell(r, 0)

    def setDefaultRow(self, inputId, rowId):
        """A List's default row, or a Checkbox's default (its row "true" or "false")"""
        if not rowId:
            return None
        inp = next(i for i in inputsOf(self.studio) if i["id"] == inputId)
        if inp["kind"] == "checkbox":
            return self.setCheckboxDefault(inputId, rowId == "true")
        return self.run(_tr("Set default configuration"), lambda: PartDesign.configSetDefaultRow(self.studio, inputId, rowId))

    def setCheckboxDefault(self, inputId, on):
        if not self._building:
            return self.run(_tr("Set checkbox default"), lambda: PartDesign.configSetCheckboxDefault(self.studio, inputId, on))

    def editVariable(self, inputId, default, minimum="", maximum=""):
        return self.run(
            _tr("Edit configuration variable"),
            lambda: PartDesign.configEditVariable(self.studio, inputId, default, minimum or None, maximum or None),
        )

    def unconfigure(self, obj, path):
        if path is None:
            return self.run(_tr("Remove configuration"), lambda: PartDesign.configUnconfigureSuppression(obj))
        return self.run(_tr("Remove configuration"), lambda: PartDesign.configUnconfigure(obj, path))

    # ---------------------------------------------------------------------------- prompts
    def promptAddList(self):
        name = askText(_tr("Add List"), _tr("Name:"), self._freeName("List"))
        if name:
            self.addList(name)

    def promptAddCheckbox(self):
        name = askText(_tr("Add Checkbox"), _tr("Name (letters, digits and _):"), self._freeName("Checkbox"))
        if name:
            self.addCheckbox(name)

    def promptAddVariable(self):
        kinds = ["Length", "Angle", "Integer", "Real", "Text"]
        kind, ok = QtWidgets.QInputDialog.getItem(self, _tr("Add Variable"), _tr("Type:"), kinds, 0, False)
        if not ok:
            return
        name = askText(_tr("Add Variable"), _tr("Name, used as #name:"), self._freeName("var"))
        if not name:
            return
        default = askText(_tr("Add Variable"), _tr("Default value:"), {"Length": "10 mm", "Angle": "0 deg"}.get(kind, "0"))
        if default is not None:
            self.addVariable(name, kind, default)

    def promptRenameInput(self):
        inputId = self.currentInput()
        inp = next((i for i in inputsOf(self.studio) if i["id"] == inputId), None)
        if inp is not None:
            name = askText(_tr("Rename input"), _tr("Name:"), inp["name"])
            if name:
                self.renameInput(inputId, name)

    def _freeName(self, base):
        taken = {i["name"] for i in inputsOf(self.studio)} | {i["id"] for i in inputsOf(self.studio)}
        n = 1
        while "{}{}".format(base, n) in taken:
            n += 1
        return "{}{}".format(base, n)


class _Observer:
    """Refreshes the panel when its studio's configuration or a configured object changes"""

    WATCHED = {"Inputs", "Table", "Active", "Label"}

    def __init__(self, panel):
        self.panel = panel

    def _mine(self, obj):
        studio = self.panel.studio
        if studio is None:
            return False
        try:
            return obj.Document == documentOf(studio)
        except Exception:
            return False

    def slotChangedObject(self, obj, prop):
        if prop in self.WATCHED and self._mine(obj):
            self.panel.scheduleRefresh()

    def slotCreatedObject(self, obj):
        if obj.TypeId == "PartDesign::StudioConfig" and self._mine(obj):
            self.panel.scheduleRefresh()

    def slotDeletedObject(self, obj):
        if self._mine(obj):
            if obj is self.panel.studio:
                self.panel.studio = None
            self.panel.scheduleRefresh()

    def slotDeletedDocument(self, doc):
        studio = self.panel.studio
        if studio is not None and documentOf(studio) == doc:
            self.panel.studio = None
            self.panel.scheduleRefresh()

    def slotUndoDocument(self, doc):
        self.panel.scheduleRefresh()

    def slotRedoDocument(self, doc):
        self.panel.scheduleRefresh()


# ------------------------------------------------------------------------- opening the panel
def panel():
    """The open panel, or None"""
    mw = FreeCADGui.getMainWindow()
    return mw.findChild(QtWidgets.QWidget, PANEL) if mw is not None else None


def showPanel(studio, inputId=None):
    mw = FreeCADGui.getMainWindow()
    dock = mw.findChild(QtWidgets.QDockWidget, DOCK)
    if dock is None:
        dock = QtWidgets.QDockWidget(_tr("Configurations"), mw)
        dock.setObjectName(DOCK)
        dock.setWidget(ConfigurationsPanel(dock))
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    p = dock.widget()
    p.setStudio(studio)
    if inputId:
        w = p.findChild(QtWidgets.QWidget, "configTab_" + inputId)
        if w is not None:
            p.tabs.setCurrentWidget(w)
    dock.show()
    dock.raise_()
    return p


def follow(docName, studioName):
    """The Features list's studio changed: an open panel shows the new one"""
    p = panel()
    if p is None or not p.isVisible():
        return
    doc = FreeCAD.listDocuments().get(docName)
    studio = studioOf(doc, studioName)
    if studio is not p.studio:
        p.setStudio(studio)


def closePanel():
    mw = FreeCADGui.getMainWindow()
    dock = mw.findChild(QtWidgets.QDockWidget, DOCK) if mw is not None else None
    if dock is not None:
        dock.widget().detach()
        mw.removeDockWidget(dock)
        dock.deleteLater()


# ------------------------------------------------------------------------ Configure a field
def _newListName(studio):
    names = {i["name"] for i in inputsOf(studio)} | {i["id"] for i in inputsOf(studio)}
    name, n = NEW_LIST_NAME, 2
    while name in names:
        name = "{} {}".format(NEW_LIST_NAME, n)
        n += 1
    return name


def _fieldPath(obj, path):
    """The path as the config calls take it; a sketch constraint's by name (None: not named)"""
    if path and path.startswith("."):
        path = path[1:]
    if path and obj.isDerivedFrom("Sketcher::SketchObject"):
        return _namedConstraintPath(obj, path)
    return path


def configureField(obj, path, inputId):
    """Configures obj's path (None or '': its suppression) with the List or Checkbox inputId; nothing
    makes an input implicitly (CP2-1). Shows Onshape's toast ("Extrude 2 Depth added to
    Configuration") and the panel. Returns the input id, or None when nothing was configured"""
    studio = PartDesign.studioOf(obj)
    inp = next((i for i in inputsOf(studio) if i["id"] == inputId), None) if inputId else None
    if inp is None:
        return None
    path = _fieldPath(obj, path)
    if path is None:
        return None
    what = obj.Label if not path else "{} / {}".format(obj.Label, path)

    def apply():
        if not path:
            PartDesign.configConfigureSuppression(obj, inputId)
        else:
            PartDesign.configConfigure(obj, path, inputId)

    if not _try(studio, _tr("Configure {}").format(what), apply):
        return None
    toast(_tr("{} {} added to {}").format(obj.Label, path or _tr("suppression"), inp["name"]))
    showPanel(studio, inputId)
    return inputId


def toast(text):
    """Onshape's toast, as a status bar message"""
    mw = FreeCADGui.getMainWindow()
    if mw is not None:
        mw.statusBar().showMessage(text, 5000)


def unconfigureField(obj, path):
    """Onshape's "Unconfigure from <input>": the field keeps the active row's value"""
    path = _fieldPath(obj, path)
    if path is None:
        return False
    if not path:
        return _try(PartDesign.studioOf(obj), _tr("Unconfigure suppression"),
                    lambda: PartDesign.configUnconfigureSuppression(obj))
    return _try(PartDesign.studioOf(obj), _tr("Unconfigure"), lambda: PartDesign.configUnconfigure(obj, path))


def setToVariable(obj, path, name):
    """Onshape's "Set to #len": the field's expression becomes the configuration Variable"""
    path = _fieldPath(obj, path)
    if not path:
        return False
    return _try(PartDesign.studioOf(obj), _tr("Set to #{}").format(name),
                lambda: obj.setExpression(path, "#" + name))


def fieldAction(obj, path, action, inputId=""):
    """A field menu's configuration item (PartDesign.configMenuItems), run by Gui core's spin
    boxes, the sketch's constraint list and the Features list"""
    if action == "configure":
        return configureField(obj, path, inputId)
    if action == "unconfigure":
        return unconfigureField(obj, path)
    if action == "variable":
        inp = next((i for i in inputsOf(PartDesign.studioOf(obj)) if i["id"] == inputId), None)
        return setToVariable(obj, path, inp["name"] if inp else inputId)
    return None


def _try(studio, title, fn):
    try:
        edit(documentOf(studio), title, fn)
        return True
    except Exception as exc:
        FreeCAD.Console.PrintWarning("Configurations: {}\n".format(exc))
        p = panel()
        if p is not None:
            p.message.setText(str(exc))
        return False


def _namedConstraintPath(sketch, path):
    """Constraints.<name> for a sketch constraint path; an unnamed constraint (Constraints[i]) is
    named first (asked), as a configured path must survive the constraints' renumbering"""
    if not path.startswith("Constraints["):
        return path
    try:
        index = int(path[len("Constraints[") : path.index("]")])
    except ValueError:
        return path
    name = askText(_tr("Configure"), _tr("A configured dimension needs a name:"), "Dimension{}".format(index + 1))
    if not name:
        return None
    try:
        edit(sketch.Document, _tr("Rename constraint"), lambda: sketch.renameConstraint(index, name))
    except Exception as exc:
        FreeCAD.Console.PrintWarning("Configurations: {}\n".format(exc))
        return None
    return "Constraints." + name


def variableProblem(inp, texts):
    """The fields of a Variable's definition that make it invalid ({'default', 'min', 'max'}):
    a value that doesn't read, a minimum above the maximum, or a default outside them"""
    kind = inp.get("type")
    if kind == "Text":
        return set()

    def read(text):
        if not text.strip():
            return None
        if kind in ("Length", "Angle"):
            q = FreeCAD.Units.Quantity(text)
            unit = FreeCAD.Units.Length if kind == "Length" else FreeCAD.Units.Angle
            if q.Unit != unit and q.Unit != FreeCAD.Units.Unit():
                raise ValueError(text)
            return q.Value
        return float(text)

    values, bad = {}, set()
    for key, text in texts.items():
        try:
            values[key] = read(text)
        except Exception:
            bad.add(key)
    if values.get("default") is None and "default" not in bad:
        bad.add("default")
    lo, hi, d = values.get("min"), values.get("max"), values.get("default")
    if lo is not None and hi is not None and lo > hi:
        bad |= {"min", "max"}
    if d is not None and hi is not None and d > hi:
        bad |= {"default", "max"}
    if d is not None and lo is not None and d < lo:
        bad |= {"default", "min"}
    return bad


def openFor(docName, studioName):
    """The Features list's Configurations button: the panel of its studio"""
    doc = FreeCAD.listDocuments().get(docName)
    studio = studioOf(doc, studioName)
    return showPanel(studio if studio is not None else doc)
