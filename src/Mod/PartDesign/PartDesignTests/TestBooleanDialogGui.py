# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, the Onshape experiment, ranks 28 and 3b)

"""Onshape's Boolean dialog (ops#640 rank 28, hands-on A-5) and the Parts list's rules for Boolean
results and split parts (rank 3b, hands-on B3-3a and A-2').

TestBooleanDialogGui: the dialog has Union / Subtract / Intersect buttons; Tools lists the
Boolean's own part first ("<part> (this part)") for a Union or an Intersect; a Subtract shows the
own part as Targets instead, with Offset (not available yet: disabled); Keep tools is off by
default and remembered from the last accepted Boolean (the user parameter BooleanKeepTools), while
the operation is not (a new Boolean opens on Union). OK with Keep tools off consumes the tool parts
(PartDesign.consumerOf, hidden); a Union of a part apart leaves it a part, with Onshape's info.

TestPartsListGui: the Parts list (FeaturesView) has one row per solid of a Body (a part cut in two
is two rows, "Bar" and "Part 1" under the Onshape keymap (round 8, J3; "Bar (2)" under FreeCAD's),
the Body one), no row for a consumed tool, and none for a Body an
Intersect that missed left empty.

Designed geometry. The dialog: the enclosure 40 x 40 x 10 (16000), a part Tool 40 x 30 x 10 from
(20, 0) overlapping it in 20 x 30 x 10 (6000; union 22000), and a part Far 100 away. The list: a bar
30 x 10 x 10 (3000) and 10 mm cubes. Off screen: QT_QPA_PLATFORM=offscreen, a fresh
FREECAD_USER_HOME (notes/build.md)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtWidgets

from PartDesignTests.TestCrossBodyGui import ResultBoxGuiCase
from PartDesignTests.TestExpressionFieldsGui import pump, waitFor
from PartDesignTests.TestCrossBodyGui import siblingEraPath  # ops#654 list on first use

V = App.Vector

PARAM = "User parameter:BaseApp/Preferences/Mod/PartDesign"
UNION = 16000 + 12000 - 6000
NO_CHANGE = "Boolean resulted in no geometry change."
NO_INTERSECTION = "Selected tools and targets do not intersect."


class TestBooleanDialogGui(ResultBoxGuiCase):
    def setUp(self):
        self.param = App.ParamGet(PARAM)
        self.savedKeep = self.param.GetBool("BooleanKeepTools", False)
        self.param.SetBool("BooleanKeepTools", False)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.param.SetBool("BooleanKeepTools", self.savedKeep)

    def model(self):
        self.enclosure()
        self.tool = self.part("Tool", (20, 0, 60, 30), 0)
        self.far = self.part("Far", (100, 0, 140, 40), 0)

    def openBoolean(self, *tools):
        """The Boolean command with the enclosure active and tools picked first; returns the new
        Boolean, its dialog open."""
        before = {o.Name for o in self.doc.Objects}
        self.runCommand("PartDesign_Boolean", *tools)
        [boolean] = [
            o for o in self.doc.Objects if o.Name not in before and o.TypeId == "PartDesign::Boolean"
        ]
        return boolean

    def button(self, name):
        found = self.visible(QtWidgets.QPushButton, name)
        self.assertIsNotNone(found, f"no {name}")
        return found

    def keepTools(self):
        found = self.visible(QtWidgets.QCheckBox, "checkKeepTools")
        self.assertIsNotNone(found, "no Keep tools")
        return found

    def operation(self, name):
        self.button(name).click()
        pump(0.3)

    def toolRows(self):
        rows = self.visible(QtWidgets.QListWidget, "listWidgetBodies")
        self.assertIsNotNone(rows, "no Tools list")
        return [rows.item(i).text() for i in range(rows.count()) if not rows.item(i).isHidden()]

    @siblingEraPath
    def testTheFieldsOfEachOperation(self):
        """A-5: a new Boolean opens on Union: Tools (the enclosure first, then Tool), Keep tools
        (off), no Targets or Offset. Subtract: Type Cut, Targets "Enclosure", Offset shown but
        disabled, Tools only Tool. Intersect: Type Common, the Union's fields."""
        self.model()
        boolean = self.openBoolean(self.tool)
        self.assertTrue(self.button("buttonUnion").isChecked())
        self.assertFalse(self.button("buttonSubtract").isChecked())
        self.assertFalse(self.button("buttonIntersect").isChecked())
        self.assertEqual(self.toolRows(), ["Enclosure (this part)", "Tool"])
        self.assertIsNone(self.visible(QtWidgets.QLineEdit, "targetsField"))
        self.assertIsNone(self.visible(QtWidgets.QCheckBox, "checkOffset"))
        self.assertFalse(self.keepTools().isChecked())

        self.operation("buttonSubtract")
        self.assertEqual(boolean.Type, "Cut")
        targets = self.visible(QtWidgets.QLineEdit, "targetsField")
        self.assertIsNotNone(targets, "no Targets")
        self.assertEqual(targets.text(), "Enclosure")
        offset = self.visible(QtWidgets.QCheckBox, "checkOffset")
        self.assertIsNotNone(offset, "no Offset")
        self.assertFalse(offset.isEnabled())
        self.assertEqual(self.toolRows(), ["Tool"])
        self.assertIsNotNone(self.keepTools())

        self.operation("buttonIntersect")
        self.assertEqual(boolean.Type, "Common")
        self.assertIsNone(self.visible(QtWidgets.QLineEdit, "targetsField"))
        self.assertEqual(self.toolRows(), ["Enclosure (this part)", "Tool"])
        self.close(ok=False)

    @siblingEraPath
    def testOkConsumesTheTool(self):
        """Union, Keep tools off, OK: the enclosure is the union (22000); Tool is consumed
        (consumerOf names the Boolean) and hidden; the parameter stays off."""
        self.model()
        boolean = self.openBoolean(self.tool)
        self.close(ok=True)
        self.assertEqual(boolean.Type, "Fuse")
        self.assertFalse(boolean.KeepTools)
        self.assertTrue(boolean.isValid(), boolean.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, UNION, places=3)
        self.assertIs(PartDesign.consumerOf(self.tool), boolean)
        self.assertFalse(self.tool.Visibility)
        self.assertFalse(self.param.GetBool("BooleanKeepTools", True))

    @siblingEraPath
    def testKeepToolsIsRememberedButNotTheOperation(self):
        """A-5: Intersect with Keep tools ticked, OK: the enclosure is the overlap (6000), Tool
        stays a part, shown; the next Boolean opens on Union with Keep tools ticked."""
        self.model()
        boolean = self.openBoolean(self.tool)
        self.operation("buttonIntersect")
        self.keepTools().click()
        pump(0.3)
        self.close(ok=True)
        self.assertEqual(boolean.Type, "Common")
        self.assertTrue(boolean.KeepTools)
        self.assertAlmostEqual(self.body.Shape.Volume, 6000, places=3)
        self.assertIsNone(PartDesign.consumerOf(self.tool))
        self.assertTrue(self.tool.Visibility)
        self.assertTrue(self.param.GetBool("BooleanKeepTools", False))

        second = self.openBoolean(self.far)
        self.assertTrue(second.KeepTools)
        self.assertTrue(self.button("buttonUnion").isChecked())
        self.assertTrue(self.keepTools().isChecked())
        self.close(ok=False)

    @siblingEraPath
    def testASubtractThatMissesIsHealthy(self):
        """B3-3a: Subtract of Far, OK: healthy, the info "Selected tools and targets do not
        intersect.", the enclosure unchanged (16000), Far consumed and hidden."""
        self.model()
        boolean = self.openBoolean(self.far)
        self.operation("buttonSubtract")
        self.close(ok=True)
        self.assertTrue(boolean.isValid(), boolean.getStatusString())
        self.assertIn(NO_INTERSECTION, boolean.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertIs(PartDesign.consumerOf(self.far), boolean)
        self.assertFalse(self.far.Visibility)

    @siblingEraPath
    def testAUnionOfAPartApartLeavesIt(self):
        """A-2' b: Union of Far, OK: healthy, "Boolean resulted in no geometry change.", the
        enclosure 16000, Far left separate: a part still, shown."""
        self.model()
        boolean = self.openBoolean(self.far)
        self.close(ok=True)
        self.assertTrue(boolean.isValid(), boolean.getStatusString())
        self.assertIn(NO_CHANGE, boolean.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertEqual(boolean.SeparateTools, [self.far])
        self.assertIsNone(PartDesign.consumerOf(self.far))
        self.assertTrue(self.far.Visibility)


class TestPartsListGui(unittest.TestCase):
    """The Parts list with the list in place of the tree, as TestFeaturesViewGui has it."""

    def setUp(self):
        self.doc = App.newDocument("BooleanPartsList")
        self.doc.UndoMode = 1
        self.param = App.ParamGet(PARAM)
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        Gui.activateWorkbench("PartDesignWorkbench")
        self.showTree(False)
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        self.assertTrue(waitFor(lambda: self.view() is not None and self.view().isVisible()))
        self.parts = self.view().findChild(QtWidgets.QTreeWidget, "partsList")
        self.bar, self.barBox = self.part("Bar", 0, length=30)

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        self.showTree(self.savedTree)
        pump()

    def showTree(self, tree):
        if self.param.GetBool("ShowModelTree", False) != tree:
            Gui.runCommand("PartDesign_ToggleModelTree")

    def view(self):
        return Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")

    def part(self, name, x, length=10):
        body = self.doc.addObject("PartDesign::Body", name)
        box = body.newObject("PartDesign::AdditiveBox", name + "Box")
        box.Length = length
        box.Width = box.Height = 10
        box.Placement.Base = V(x, 0, 0)
        self.doc.recompute()
        return body, box

    def partRows(self):
        return [self.parts.topLevelItem(i).text(0) for i in range(self.parts.topLevelItemCount())]

    def assertRows(self, rows):
        self.assertTrue(waitFor(lambda: self.partRows() == rows), self.partRows())
        self.assertEqual(self.parts.headerItem().text(0), f"Parts ({len(rows)})")

    def boolean(self, kind, tool):
        boolean = self.bar.newObject("PartDesign::Boolean", kind)
        boolean.setObjects([tool])
        boolean.Type = kind
        boolean.KeepTools = False
        self.doc.recompute()
        self.assertTrue(boolean.isValid(), boolean.getStatusString())
        return boolean

    def testAPartCutInTwoHasTwoRows(self):
        """A-2' a: a cutter through the bar's middle third: two rows, "Bar" and "Part 1" (the
        lowest free "Part N", as Onshape names a split's new part; "Bar (2)" under FreeCAD's
        keymap), one Body still; the cutter deleted: one row again."""
        self.assertRows(["Bar"])
        bodies = [o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Body"]
        cutter = self.bar.newObject("PartDesign::SubtractiveBox", "Cutter")
        cutter.Length = 10
        cutter.Width = cutter.Height = 20
        cutter.Placement.Base = V(10, -5, -5)
        self.doc.recompute()
        self.assertEqual(len(self.bar.Shape.Solids), 2)
        onshape = (
            App.ParamGet("User parameter:BaseApp/Preferences/General").GetString("Keymap", "Onshape")
            != "FreeCAD"
        )
        self.assertRows(["Bar", "Part 1" if onshape else "Bar (2)"])
        self.assertEqual([o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Body"], bodies)
        self.bar.removeObject(cutter)
        self.doc.removeObject(cutter.Name)
        self.doc.recompute()
        self.assertRows(["Bar"])

    def testAConsumedToolHasNoRow(self):
        """A Union of a cube overlapping the bar's end: the cube leaves the list; Keep tools on:
        it is back."""
        tool, _ = self.part("Tool", 25)
        self.assertRows(["Bar", "Tool"])
        fuse = self.boolean("Fuse", tool)
        self.assertAlmostEqual(self.bar.Shape.Volume, 3500, places=3)
        self.assertRows(["Bar"])
        fuse.KeepTools = True
        self.doc.recompute()
        self.assertRows(["Bar", "Tool"])

    def testAUnionOfAPartApartKeepsBothRows(self):
        """A-2' b: a Union of a cube 20 away: both rows stay (Parts (2)), the bar 3000."""
        tool, _ = self.part("Tool", 50)
        self.boolean("Fuse", tool)
        self.assertAlmostEqual(self.bar.Shape.Volume, 3000, places=3)
        self.assertRows(["Bar", "Tool"])

    def testAnIntersectThatMissesLeavesNoRow(self):
        """A-2' c: an Intersect with a cube 20 away, Keep tools off: no part left (Parts (0))."""
        tool, _ = self.part("Tool", 50)
        self.assertRows(["Bar", "Tool"])
        self.boolean("Common", tool)
        self.assertRows([])


if __name__ == "__main__":
    unittest.main()
