# SPDX-License-Identifier: LGPL-2.1-or-later
"""A widget the UI loader makes never comes back through a stale wrapper (FreeCAD-CH, ops#790, ops#825).

A Python wrapper whose object was deleted from C++ without shiboken being told stays valid and
mapped at the freed address, and a widget later made there came back through it, with the dead
object's cached signal instances ("Signal source has been deleted" in the joint dialog, ops#790).
Since ops#825 the loader drops such a wrapper as it makes each widget, layout and action
(`UiLoader::createWidget`), on every load path; before, only `UiLoader.load`'s named children and
`createWidget` were covered (ops#790).

The tests force the address reuse: they make spin boxes, delete them, plant a wrapper at each
freed address (`shiboken6.wrapInstance`, which maps without telling the object), then load spin
boxes until one lands on a planted address. That widget must come back through a new, valid
wrapper whose signals work, and the planted one must be invalid. A wrapper held from before the
load, of a live widget, must stay valid.
"""

import os
import tempfile
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

import shiboken6
from PySide import QtWidgets

PLANTED = 256  # freed spin-box addresses per round
BOXES = 32  # spin boxes per loaded form
ROUNDS = 20


def pump(seconds=0.1):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def address(wrapper):
    return shiboken6.getCppPointer(wrapper)[0]


def valid(wrapper):
    try:
        return shiboken6.isValid(wrapper)
    except RuntimeError:
        return False


def formXml(named):
    """A form of BOXES spin boxes. Names that start with `_` get no attribute on the loaded form,
    so UiLoader.load's own walk over named children (ops#790) never sees them."""
    prefix = "spin" if named else "_spin"
    items = "".join(
        '<item><widget class="QDoubleSpinBox" name="%s%d"/></item>' % (prefix, i)
        for i in range(BOXES)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ui version="4.0"><class>Form</class>'
        '<widget class="QWidget" name="Form">'
        '<layout class="QVBoxLayout" name="layout">%s</layout>'
        "</widget></ui>\n" % items
    )


class TestUiLoaderWrappersGui(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="uiloader_")
        self.loader = Gui.UiLoader()
        self.planted = {}
        self.doc = None  # a task dialog's document
        self.keep = []  # loaded forms, alive until tearDown so their addresses stay taken
        # wrappers held from before any load: one of a C++-made widget, one made by Python
        self.heldCpp = self.loader.createWidget("QLabel")
        self.heldCpp.setText("held")
        self.heldPy = QtWidgets.QLabel("held")

    def tearDown(self):
        self.unplant()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        if self.doc:
            App.closeDocument(self.doc.Name)
            self.doc = None
        for form in self.keep:
            if valid(form):
                form.deleteLater()
        self.keep.clear()
        pump()

    def uiFile(self, named):
        path = os.path.join(self.dir, "form_%s.ui" % ("named" if named else "unnamed"))
        with open(path, "w", encoding="utf-8") as f:
            f.write(formXml(named))
        return path

    def unplant(self):
        for wrapper in self.planted.values():
            if valid(wrapper):
                shiboken6.invalidate(wrapper)  # unmaps only: it owns nothing
        self.planted.clear()

    def plant(self):
        """Wrappers left at freed spin-box addresses, as a C++ deletion shiboken missed leaves them."""
        boxes = [self.loader.createWidget("QDoubleSpinBox") for _ in range(PLANTED)]
        addresses = [address(box) for box in boxes]
        for box in boxes:
            shiboken6.delete(box)
        del boxes
        for addr in addresses:
            if addr not in self.planted:
                self.planted[addr] = shiboken6.wrapInstance(addr, QtWidgets.QDoubleSpinBox)

    def checkReused(self, load):
        """`load()` makes spin boxes and returns their wrappers, as the path hands them to Python.
        Loads until one lands on a planted address, and checks it.

        Only the spin boxes the path loaded count, by name: another widget of the same size (a
        task box's header, made outside the loader) may land on a planted address too, and
        findChildren then hands it out through the planted wrapper. objectName() is a QObject
        method, so it is safe through a wrapper of the wrong widget type."""
        hits = []
        for _ in range(ROUNDS):
            self.plant()
            for box in load():
                if not box.objectName().startswith(("spin", "_spin")):
                    continue
                old = self.planted.get(address(box))
                if old is not None:
                    hits.append((box, old))
            if hits:
                break
            self.unplant()  # missed: no planted wrapper stays mapped at a live widget
        if not hits:
            self.skipTest("no address reuse in %d rounds" % ROUNDS)
        for box, old in hits:
            self.assertIsNot(box, old, "a new widget came back through a stale wrapper")
            self.assertFalse(valid(old), "the stale wrapper is still valid")
            self.assertTrue(valid(box))
            seen = []
            box.valueChanged.connect(seen.append)
            box.setValue(1.5)
            self.assertEqual(seen, [1.5])
        self.assertTrue(valid(self.heldCpp))
        self.assertTrue(valid(self.heldPy))
        self.assertEqual(self.heldCpp.text(), "held")
        self.assertEqual(self.heldPy.text(), "held")

    def test_loadUnnamedChildren(self):
        """UiLoader.load: spin boxes with no attribute on the form (fails before ops#825)."""
        path = self.uiFile(named=False)

        def load():
            form = self.loader.load(path)
            self.keep.append(form)
            return form.findChildren(QtWidgets.QDoubleSpinBox)

        self.checkReused(load)

    def test_loadNamedChildren(self):
        """UiLoader.load: the form's named attributes (ops#790's case)."""
        path = self.uiFile(named=True)

        def load():
            form = self.loader.load(path)
            self.keep.append(form)
            return [getattr(form, "spin%d" % i) for i in range(BOXES)]

        self.checkReused(load)

    def test_createWidget(self):
        """UiLoader.createWidget (ops#790's other case)."""

        def load():
            boxes = [
                self.loader.createWidget("QDoubleSpinBox", None, "spin%d" % i) for i in range(BOXES)
            ]
            self.keep.extend(boxes)
            return boxes

        self.checkReused(load)

    def test_taskDialogUiFile(self):
        """A task dialog's `ui` file, which C++ loads (fails before ops#825)."""
        path = self.uiFile(named=True)
        self.doc = App.newDocument("UiLoaderWrappers")  # task dialogs belong to a document
        Gui.setActiveDocument(self.doc.Name)

        class Dialog:
            ui = path

            def getStandardButtons(self):
                return QtWidgets.QDialogButtonBox.Close

            def reject(self):
                return True

        def load():
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
                pump()
            Gui.Control.showDialog(Dialog())
            pump()
            dialog = Gui.Control.activeTaskDialog()
            self.assertIsNotNone(dialog, "the task dialog didn't open")
            content = dialog.getDialogContent()
            boxes = []
            for form in content:
                boxes.extend(form.findChildren(QtWidgets.QDoubleSpinBox))
            return boxes

        self.checkReused(load)
