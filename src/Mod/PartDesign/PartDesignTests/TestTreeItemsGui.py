# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Tree items (FreeCAD-CH, ops#149).

- The item in edit is bold as well as coloured (upstream issue 20599): a style sheet that paints
  item backgrounds, or the item's selection, hid the edit colour. Leaving edit restores the item's
  font and background.
- Deleting the visible last feature of a Body shows the feature before it (upstream issue 30499),
  also when the deleted feature has a nested sketch. This didn't fail on integration in any
  variant tried (ops#149): the tests pin it. The left-behind sketch stays hidden (PLAN decision
  29; upstream's makeChildrenVisible showed it), so only the previous feature shows, as when a
  feature without a sketch is deleted. The same for a profile that isn't a sketch (a binder) and
  for a hidden feature. With no previous feature (the Body's only feature), the sketch is shown.

Designed model, built by the test: a Body with a 20 x 10 rectangle padded 10, and a second
rectangle (5..15 x 2..8) on the pad's top plane (z = 10) padded 5. The second sketch is the
second pad's profile, so the tree nests it under that pad. The reference case without a nested
sketch puts a 4 x 4 x 4 additive box on top instead of the second pad.

Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from PartDesignTests.TestExpressionFieldsGui import pump, rectangleSketch, taskButton, waitFor

EDIT_COLOR_DEFAULT = 11272191  # TreeEditColor's default, 0x00ABFFFF


def editColor():
    packed = App.ParamGet("User parameter:BaseApp/Preferences/TreeView").GetUnsigned(
        "TreeEditColor", EDIT_COLOR_DEFAULT
    )
    return QtGui.QColor((packed >> 24) & 0xFF, (packed >> 16) & 0xFF, (packed >> 8) & 0xFF)


def modelTree():
    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        if tree.metaObject().className() == "Gui::TreeWidget":
            return tree
    return None


def itemStyle(tree, label):
    """(bold, background colour name or None) of the first item labelled label, read at once:
    PySide invalidates a child item's wrapper when its parent's goes. Collapsed items are
    expanded on the way, so nested items exist."""

    def walk(item):
        if item.text(0) == label:
            brush = item.background(0)
            colour = None if brush.style() == QtCore.Qt.NoBrush else brush.color().name()
            return (item.font(0).bold(), colour)
        if item.childCount() == 0 and item.childIndicatorPolicy() == QtWidgets.QTreeWidgetItem.ShowIndicator:
            item.setExpanded(True)
            QtWidgets.QApplication.processEvents()
        for i in range(item.childCount()):
            found = walk(item.child(i))
            if found is not None:
                return found
        return None

    for i in range(tree.topLevelItemCount()):
        found = walk(tree.topLevelItem(i))
        if found is not None:
            return found
    return None


class TestTreeItemsGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TreeItemsGui")
        Gui.activateView("Gui::View3DInventor", True)
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        Gui.activeView().setActiveObject("pdbody", self.body)
        self.sketch = rectangleSketch(self.body, "Sketch", 0, 0, 20, 10)
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.sketch
        self.pad.Length = 10
        self.doc.recompute()
        self.dialogs = []

    def tearDown(self):
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        # getInEdit() is None while another view is active; resetEdit() ends the edit anyway
        if Gui.ActiveDocument:
            Gui.ActiveDocument.resetEdit()
        pump()
        App.closeDocument(self.doc.Name)

    def addSecondPad(self):
        sketch = rectangleSketch(self.body, "Sketch001", 5, 2, 15, 8, z=10)
        pad = self.body.newObject("PartDesign::Pad", "Pad001")
        pad.Profile = sketch
        pad.Length = 5
        self.doc.recompute()
        # The Pad command hides its profile; a scripted Pad leaves it shown
        self.sketch.ViewObject.Visibility = False
        sketch.ViewObject.Visibility = False
        pump()
        self.assertTrue(pad.isValid())
        self.assertAlmostEqual(self.body.Shape.Volume, 20 * 10 * 10 + 10 * 6 * 5, places=6)
        return pad

    def styleOf(self, label):
        tree = modelTree()
        self.assertIsNotNone(tree, "no model tree")
        waitFor(lambda: itemStyle(tree, label) is not None, 2.0)
        style = itemStyle(tree, label)
        self.assertIsNotNone(style, f"no tree item {label}")
        return style

    def delete(self, obj):
        """Deletes obj as the Delete key does, refusing any modal dialog (and noting its title)."""

        def refuse():
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if isinstance(widget, QtWidgets.QMessageBox) and widget.isVisible():
                    self.dialogs.append(widget.windowTitle())
                    widget.reject()

        timer = QtCore.QTimer()
        timer.timeout.connect(refuse)
        timer.start(100)
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self.doc.Name, obj.Name)
            Gui.runCommand("Std_Delete", 0)
            pump()
        finally:
            timer.stop()
        self.assertEqual(self.dialogs, [], "Std_Delete asked something")

    # -- the item in edit ------------------------------------------------------------------------

    def testFeatureInEditIsBoldAndColoured(self):
        self.assertEqual(self.styleOf("Pad")[0], False)
        Gui.Selection.clearSelection()
        self.pad.ViewObject.doubleClicked()
        pump()
        self.assertTrue(Gui.Control.activeDialog(), "no Pad panel")
        bold, colour = self.styleOf("Pad")
        self.assertTrue(bold, "the Pad in edit isn't bold")
        self.assertEqual(colour, editColor().name())
        self.assertEqual(self.styleOf("Sketch")[0], False, "only the item in edit is bold")
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        pump()
        self.assertEqual(self.styleOf("Pad"), (False, None), "the edit style stays after Cancel")

    def testNestedSketchInEditIsBold(self):
        body = self.styleOf("Body")
        Gui.Selection.clearSelection()
        self.sketch.ViewObject.doubleClicked()
        pump()
        self.assertEqual(Gui.ActiveDocument.getInEdit(), self.sketch.ViewObject)
        bold, colour = self.styleOf("Sketch")
        self.assertTrue(bold, "the sketch in edit isn't bold")
        self.assertEqual(colour, editColor().name())
        self.assertEqual(self.styleOf("Pad"), (False, None), "the Pad isn't in edit")
        self.assertEqual(self.styleOf("Body"), body, "the Body isn't in edit")
        Gui.ActiveDocument.resetEdit()
        pump()
        self.assertEqual(self.styleOf("Sketch"), (False, None))

    def testItemMadeWhileAnotherViewIsActiveIsStyled(self):
        """The sketch's item under the collapsed Pad is made after the edit started; a second 3D
        view of the document is active by then, so Document.getInEdit() is None."""
        Gui.Selection.clearSelection()
        self.sketch.ViewObject.doubleClicked()
        Gui.runCommand("Std_ViewCreate", 0)
        pump()
        self.assertIsNone(Gui.ActiveDocument.getInEdit(), "the editing view is still active")
        self.assertEqual(self.styleOf("Sketch"), (True, editColor().name()))
        Gui.ActiveDocument.resetEdit()
        pump()
        self.assertEqual(self.styleOf("Sketch"), (False, None))

    def testSearchKeepsTheEditColour(self):
        """The tree search paints its match yellow; ending the search painted the item's highlight
        background back, also over the edit colour."""
        Gui.Selection.clearSelection()
        self.sketch.ViewObject.doubleClicked()
        pump()
        self.assertEqual(self.styleOf("Sketch"), (True, editColor().name()))
        search = None
        for edit in Gui.getMainWindow().findChildren(QtWidgets.QLineEdit):
            parent = edit.parentWidget()
            if parent and parent.metaObject().className() == "Gui::TreePanel":
                search = edit
                break
        self.assertIsNotNone(search, "no tree search box")
        search.setText("Sketch")
        pump()
        self.assertNotEqual(self.styleOf("Sketch")[1], editColor().name(), "no search match")
        search.setText("")
        pump()
        self.assertEqual(self.styleOf("Sketch"), (True, editColor().name()))

    def testActiveBodyKeepsItsHighlightAfterAnEdit(self):
        """The edit end restored no background, so it wiped an active container's highlight: edit
        the active Body's placement and leave."""
        before = self.styleOf("Body")
        self.assertTrue(before[0], "the active Body isn't bold")
        self.assertIsNotNone(before[1], "the active Body has no highlight colour")
        Gui.ActiveDocument.setEdit(self.body, 1)  # Transform
        pump()
        self.assertEqual(self.styleOf("Body"), (True, editColor().name()))
        Gui.ActiveDocument.resetEdit()
        pump()
        self.assertEqual(self.styleOf("Body"), before)

    def testActiveBodyChangingDuringAnEdit(self):
        """Another Body made active while the first is in edit: the first keeps the edit style until
        the edit ends, then shows neither highlight."""
        active = self.styleOf("Body")
        other = self.doc.addObject("PartDesign::Body", "Body001")
        pump()
        Gui.ActiveDocument.setEdit(self.body, 1)  # Transform
        pump()
        Gui.activeView().setActiveObject("pdbody", other)
        pump()
        self.assertEqual(self.styleOf("Body001"), active)
        self.assertEqual(self.styleOf("Body"), (True, editColor().name()))
        Gui.ActiveDocument.resetEdit()
        pump()
        self.assertEqual(self.styleOf("Body"), (False, None))
        self.assertEqual(self.styleOf("Body001"), active)

    # -- visibility on delete --------------------------------------------------------------------

    def assertShown(self, feature):
        self.assertTrue(feature.Visibility, f"{feature.Name} isn't visible")
        self.assertTrue(feature.ViewObject.isVisible(), f"{feature.Name} isn't drawn")

    def testDeletingLastPadWithNestedSketchShowsPrevious(self):
        pad2 = self.addSecondPad()
        self.assertShown(pad2)
        self.assertFalse(self.pad.Visibility)
        self.delete(pad2)
        self.assertNotIn("Pad001", [o.Name for o in self.doc.Objects])
        self.assertEqual(self.body.Tip, self.pad)
        self.assertShown(self.pad)
        sketch = self.doc.getObject("Sketch001")
        self.assertIn(sketch, self.body.Group, "the left-behind sketch stays in the Body")
        self.assertFalse(sketch.Visibility, "the left-behind sketch is shown")

    def testDeletingLastFeatureWithoutSketchShowsPrevious(self):
        """The reference: a feature with no nested sketch."""
        box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 4
        self.doc.recompute()
        pump()
        self.assertShown(box)
        self.assertFalse(self.pad.Visibility)
        self.delete(box)
        self.assertEqual(self.body.Tip, self.pad)
        self.assertShown(self.pad)

    def testDeletingTheOnlyFeatureShowsItsSketch(self):
        """With no previous feature to show, the sketch is shown, so the Body isn't left empty
        (ops#149 review M2)."""
        self.sketch.ViewObject.Visibility = False
        pump()
        self.assertShown(self.pad)
        self.delete(self.pad)
        self.assertNotIn("Pad", [o.Name for o in self.doc.Objects])
        self.assertShown(self.sketch)

    def testDeletingAHiddenFeatureLeavesItsSketchHidden(self):
        """A hidden feature's deletion changes nothing on screen: its sketch stays hidden and the
        shown feature stays shown."""
        pad2 = self.addSecondPad()
        pad2.ViewObject.Visibility = False
        self.pad.ViewObject.Visibility = True
        pump()
        self.delete(pad2)
        self.assertNotIn("Pad001", [o.Name for o in self.doc.Objects])
        sketch = self.doc.getObject("Sketch001")
        self.assertFalse(sketch.Visibility, "the hidden feature's sketch is shown")
        self.assertShown(self.pad)

    def testDeletingAFeatureOnABinderKeepsTheBinderHidden(self):
        """A profile that isn't a sketch, a SubShapeBinder of one, stays hidden as a sketch does
        (ops#149 review L1)."""
        sketch = rectangleSketch(self.body, "Sketch001", 5, 2, 15, 8, z=10)
        binder = self.body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(sketch, ("",))]
        pad2 = self.body.newObject("PartDesign::Pad", "Pad001")
        pad2.Profile = binder
        pad2.Length = 5
        self.doc.recompute()
        for obj in (self.sketch, sketch, binder):
            obj.ViewObject.Visibility = False
        pump()
        self.assertTrue(pad2.isValid())
        self.assertAlmostEqual(self.body.Shape.Volume, 20 * 10 * 10 + 10 * 6 * 5, places=6)
        self.assertShown(pad2)
        self.delete(pad2)
        self.assertShown(self.pad)
        self.assertFalse(binder.Visibility, "the left-behind binder is shown")

    # -- the shown feature at the end of an edit -------------------------------------------------

    def addBox(self, name, x):
        box = self.body.newObject("PartDesign::AdditiveBox", name)
        for prop in ("Length", "Width", "Height"):
            setattr(box, prop, 2)
        box.Placement = App.Placement(App.Vector(x, 4, 10), App.Rotation())
        self.doc.recompute()
        self.assertTrue(box.isValid(), box.getStatusString())
        return box

    def editAndEnd(self, feature):
        guiDoc = Gui.getDocument(self.doc.Name)
        guiDoc.setEdit(feature.Name)
        pump()
        self.assertEqual(guiDoc.getInEdit().Object, feature)
        guiDoc.resetEdit()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the panel stays")
        pump()

    def testEditOutsideABodyKeepsAnEarlierShownFeatureHidden(self):
        """An edit ends by showing the feature the Body showed when it began. A feature edited in
        a Body, then taken out of it and edited again, showed the Body's feature of its first edit
        at the end of the second (ops#212: the remembered feature was set only with a Body)."""
        box = self.addBox("Box", 2)
        top = self.addBox("Top", 12)
        self.assertShown(top)
        self.editAndEnd(box)
        self.assertShown(top)

        self.body.removeObject(box)
        self.doc.recompute()
        self.assertNotIn(box, self.body.Group)
        top.ViewObject.Visibility = False
        box.ViewObject.Visibility = True
        pump()
        self.editAndEnd(box)
        self.assertFalse(top.Visibility, "the edit outside the Body showed the Body's old feature")

    def testDeletingTheShownFeatureDuringAnotherEdit(self):
        """The shown last feature, with its own sketch, deleted while the first Pad is in edit
        (ops#187 and ops#149 together): Cancel ends the edit without showing the deleted feature,
        the Pad shows and the deleted feature's sketch stays hidden."""
        pad2 = self.addSecondPad()
        self.assertShown(pad2)
        Gui.getDocument(self.doc.Name).setEdit(self.pad.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no Pad panel")
        pump()
        self.delete(pad2)
        self.assertNotIn("Pad001", [o.Name for o in self.doc.Objects])
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump()
        self.assertEqual(self.body.Tip, self.pad)
        self.assertShown(self.pad)
        sketch = self.doc.getObject("Sketch001")
        self.assertFalse(sketch.Visibility, "the left-behind sketch is shown")
        self.assertFalse(self.sketch.Visibility, "the Pad's sketch is shown after its edit")
