# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (notes/derived-design.md, slice 1): Derived from another document, the GUI

"""Two commands for freecad.derived:

- PartDesign_DerivedFromFile: choose a saved .FCStd, a studio of it and its parts; a Derived
  feature of copies of them goes into the active studio (the active Body's, else the active
  App::Part, else the document's top level).
- PartDesign_DerivedRefresh: the selected Derived feature from another document copies its parts
  again from the saved file (Onshape's update to the newest version); its state is shown first.
"""

import FreeCAD as App
import FreeCADGui as Gui

translate = App.Qt.translate


def _active_studio(doc):
    import PartDesign

    view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
    body = view.getActiveObject("pdbody") if view and hasattr(view, "getActiveObject") else None
    if body is not None:
        return PartDesign.studioOf(body)
    part = view.getActiveObject("part") if view and hasattr(view, "getActiveObject") else None
    if part is not None and not part.isDerivedFrom("Assembly::AssemblyObject"):
        return part
    return doc


def _error(text):
    from PySide import QtWidgets

    QtWidgets.QMessageBox.warning(Gui.getMainWindow(), translate("Derived", "Derived"), text)


class _Chooser:
    """A dialog: the studio of the file and its parts, all ticked."""

    def __init__(self, studios):
        from PySide import QtWidgets

        self.studios = studios
        self.dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self.dialog.setWindowTitle(translate("Derived", "Derived from another document"))
        layout = QtWidgets.QVBoxLayout(self.dialog)
        self.combo = QtWidgets.QComboBox()
        for _, label, _ in studios:
            self.combo.addItem(label)
        layout.addWidget(self.combo)
        self.list = QtWidgets.QListWidget()
        layout.addWidget(self.list)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.dialog.accept)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)
        self.combo.currentIndexChanged.connect(self._fill)
        self._fill(0)

    def _fill(self, index):
        from PySide import QtCore, QtWidgets

        self.list.clear()
        for name, label in self.studios[index][2]:
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.list.addItem(item)

    def run(self):
        from PySide import QtCore

        if not self.dialog.exec_():
            return None
        index = self.combo.currentIndex()
        parts = []
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.checkState() == QtCore.Qt.Checked:
                parts.append(item.data(QtCore.Qt.UserRole))
        return self.studios[index][0], parts


class CommandDerivedFromFile:
    def GetResources(self):
        return {
            "Pixmap": "PartDesign_SubShapeBinder",
            "MenuText": translate("Derived", "Derived from file..."),
            "ToolTip": translate(
                "Derived",
                "Brings parts of a part studio of another saved document into this one, as "
                "copies of the saved file that change only on Refresh",
            ),
        }

    def IsActive(self):
        return Gui.ActiveDocument is not None

    def Activated(self):
        from PySide import QtWidgets
        from freecad import derived

        doc = App.ActiveDocument
        # The active studio is read first: the hidden read of the source file below must not
        # decide it (Onshape: always the current Part Studio)
        studio = _active_studio(doc)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            Gui.getMainWindow(),
            translate("Derived", "The source document"),
            "",
            "FreeCAD (*.FCStd)",
        )
        if not path:
            return
        try:
            studios = derived.list_source(path)
        except Exception as e:
            _error(str(e))
            return
        if not studios:
            _error(translate("Derived", "The document has no part studio with a part to derive."))
            return
        chosen = _Chooser(studios).run()
        if not chosen:
            return
        try:
            derived.derive_from_file(doc, studio, path, chosen[0], chosen[1])
        except Exception as e:
            _error(str(e))


class CommandDerivedRefresh:
    def GetResources(self):
        return {
            "Pixmap": "view-refresh",
            "MenuText": translate("Derived", "Refresh derived parts"),
            "ToolTip": translate(
                "Derived",
                "Copies the selected Derived feature's parts again from its saved source file",
            ),
        }

    def _lead(self):
        import PartDesign

        for obj in Gui.Selection.getSelection():
            lead = PartDesign.derivedLead(obj)
            if lead is not None and lead.BaseFeature is not None and PartDesign.isDerivedCopy(
                lead.BaseFeature
            ):
                return lead
        return None

    def IsActive(self):
        return self._lead() is not None

    def Activated(self):
        from PySide import QtWidgets
        from freecad import derived

        lead = self._lead()
        state = derived.derived_state(lead)
        if state == derived.UP_TO_DATE:
            answer = QtWidgets.QMessageBox.question(
                Gui.getMainWindow(),
                translate("Derived", "Derived"),
                translate("Derived", "The source file hasn't changed. Refresh anyway?"),
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return
        try:
            derived.refresh_derived(lead)
        except Exception as e:
            _error(str(e))


def register():
    Gui.addCommand("PartDesign_DerivedFromFile", CommandDerivedFromFile())
    Gui.addCommand("PartDesign_DerivedRefresh", CommandDerivedRefresh())
