# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (asm-patterns): the assembly Linear pattern command in the GUI, as Onshape's: select an
# instance, Linear Pattern, pick the direction, set the distance and the count, OK; the copies are
# instances in the Assembly tab's list and the pattern is listed with the mates; a double-click
# opens it again; undo takes the pattern and its copies back.
# Designed geometry: "Part 1", a PartDesign box 10 x 10 x 10; the direction is its edge along X.

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets

import AssemblyPattern
from AssemblyTests.TestOnshapeAssembliesGui import (
    AssembliesGuiBase,
    TestAssemblyListGui,
    onshapeKeymap,
    pump,
    tabsOn,
    waitFor,
)

X = App.Vector(1, 0, 0)


class TestAssemblyPatternsGui(AssembliesGuiBase):
    def setUp(self):
        super().setUp()
        if not tabsOn() or not onshapeKeymap():
            self.skipTest("the typed tabs and the list are on under the Onshape keymap only")
        self.param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        self.param.SetBool("ShowModelTree", False)
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()

    def tearDown(self):
        super().tearDown()
        self.param.SetBool("ShowModelTree", self.savedTree)
        pump(0.2)

    # The Assembly tab's list, as TestAssemblyListGui reads it
    assemblyList = TestAssemblyListGui.assemblyList
    shown = TestAssemblyListGui.shown
    row = TestAssemblyListGui.row
    doubleClick = TestAssemblyListGui.doubleClick
    view = staticmethod(TestAssemblyListGui.view)

    def model(self):
        doc = self.newDocument("AssemblyPatternsGui")
        body = doc.addObject("PartDesign::Body", "Body")
        body.Label = "Part 1"
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 10
        asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        asm.newObject("Assembly::JointGroup", "Joints")
        doc.recompute()
        pump(0.2)
        done, refusal = Gui.DocumentTabs.switchTo(doc, asm.Name)
        self.assertTrue(done, refusal)
        pump(0.4)
        seed = asm.newObject("App::Link", "Part1")
        seed.LinkedObject = body
        seed.Label = AssemblyPattern.instanceLabel(asm, body)
        doc.recompute()
        pump(0.2)
        edge = None
        for i, e in enumerate(body.Shape.Edges, 1):
            p0, p1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
            along = p1 - p0
            if min(p0.Length, p1.Length) < 1e-9 and abs(abs(along.normalize().dot(X)) - 1) < 1e-12:
                edge, self.along = f"Edge{i}", along.normalize()
        self.assertIsNotNone(edge)
        return doc, asm, seed, edge

    def testLinearPatternJourney(self):
        doc, asm, seed, edge = self.model()
        doc.UndoMode = 1
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, asm.Name, f"{seed.Name}.")
        Gui.runCommand("Assembly_CreatePatternLinear")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "the pattern panel")
        pattern = [o for o in asm.getObject("Joints").Group if AssemblyPattern.isPattern(o)][0]
        self.assertEqual(list(pattern.Seeds), [seed], "the selected instance is the seed")
        # The direction field is the next pick's: pick the edge along X
        Gui.Selection.addSelection(doc.Name, asm.Name, f"{seed.Name}.{edge}")
        pump(0.3)
        self.assertEqual(pattern.Direction[0], seed)
        self.assertTrue(pattern.Direction[1][0].endswith(edge))
        main = Gui.getMainWindow()
        distance = main.findChild(QtWidgets.QWidget, "patternAmount")
        count = main.findChild(QtWidgets.QWidget, "patternCount")
        self.assertIsNotNone(distance)
        self.assertIsNotNone(count)
        distance.setProperty("rawValue", 15.0)
        count.setValue(4)
        pump(0.3)
        self.assertEqual(pattern.Count, 4)
        self.assertAlmostEqual(pattern.Distance.Value, 15.0)
        copies = list(pattern.Instances)
        self.assertEqual(len(copies), 3)
        for copy in copies:
            expected = App.Placement(self.along * (15.0 * copy.PatternIndex), App.Rotation()).multiply(seed.Placement)
            self.assertTrue(copy.Placement.isSame(expected, 1e-6), copy.Label)
        self.assertIsNotNone(AssemblyPattern.activePanel)
        self.assertTrue(AssemblyPattern.activePanel.accept())
        pump(0.3)
        self.assertFalse(Gui.Control.activeDialog(), "the panel closed")
        # The list: four instances, the pattern with the mates
        self.assertTrue(waitFor(lambda: self.shown() is not None))
        shown = self.shown()
        headers = list(shown)
        self.assertEqual(headers[0], "Instances (4)")
        self.assertIn("Part 1 <2>", shown[headers[0]])
        self.assertIn("Linear pattern 1", shown[headers[1]])
        # A double-click on the pattern opens its panel again; Cancel leaves it as it was
        k = shown[headers[1]].index("Linear pattern 1")
        self.doubleClick(self.row(1, k))
        self.assertTrue(waitFor(lambda: bool(Gui.Control.activeDialog())), "the panel opens again")
        self.assertIsNotNone(AssemblyPattern.activePanel)
        AssemblyPattern.activePanel.reject()
        pump(0.3)
        self.assertEqual(len(pattern.Instances), 3)
        # Undo takes the pattern and its copies back
        name = pattern.Name
        names = [c.Name for c in copies]
        Gui.runCommand("Std_Undo")
        pump(0.4)
        self.assertIsNone(doc.getObject(name))
        for n in names:
            self.assertIsNone(doc.getObject(n), n)

    def edgeAlong(self, body, direction):
        """The name and the way (first vertex to last) of the box's edge through its origin along
        direction"""
        for i, e in enumerate(body.Shape.Edges, 1):
            p0, p1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
            along = p1 - p0
            if min(p0.Length, p1.Length) < 1e-9 and abs(abs(along.normalize().dot(direction)) - 1) < 1e-12:
                return f"Edge{i}", along.normalize()
        self.fail("no such edge")

    def testSecondDirectionJourney(self):
        """ops#640 C7, as Onshape's dialog: ticking Second direction shows its own fields, empty
        (count 1, 25 mm: nothing copied from the first direction), its Direction the next pick's;
        picked and set, the copies fill the grid; reopened, the box shows them again"""
        doc, asm, seed, edge = self.model()
        body = seed.LinkedObject
        edge2, along2 = self.edgeAlong(body, App.Vector(0, 1, 0))
        doc.UndoMode = 1
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, asm.Name, f"{seed.Name}.")
        Gui.runCommand("Assembly_CreatePatternLinear")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "the pattern panel")
        pattern = [o for o in asm.getObject("Joints").Group if AssemblyPattern.isPattern(o)][0]
        Gui.Selection.addSelection(doc.Name, asm.Name, f"{seed.Name}.{edge}")
        pump(0.3)
        main = Gui.getMainWindow()
        main.findChild(QtWidgets.QWidget, "patternAmount").setProperty("rawValue", 15.0)
        main.findChild(QtWidgets.QWidget, "patternCount").setValue(3)
        pump(0.3)
        second = main.findChild(QtWidgets.QCheckBox, "patternSecondDirection")
        box = main.findChild(QtWidgets.QWidget, "patternSecondBox")
        self.assertIsNotNone(second)
        self.assertIsNotNone(box)
        self.assertFalse(second.isChecked())
        self.assertFalse(box.isVisible(), "the second direction's fields show only when ticked")
        second.setChecked(True)
        pump(0.3)
        self.assertTrue(pattern.SecondDirection)
        self.assertTrue(box.isVisible())
        direction2 = main.findChild(QtWidgets.QPushButton, "patternDirection2")
        distance2 = main.findChild(QtWidgets.QWidget, "patternAmount2")
        count2 = main.findChild(QtWidgets.QWidget, "patternCount2")
        self.assertTrue(direction2.isChecked(), "the empty second direction takes the next pick")
        self.assertEqual(count2.value(), 1)
        self.assertAlmostEqual(distance2.property("rawValue"), 25.0)
        self.assertEqual(len(pattern.Instances), 2, "count 1 with no direction: the first direction's copies")
        self.assertNotIn("Invalid", pattern.State)
        Gui.Selection.addSelection(doc.Name, asm.Name, f"{seed.Name}.{edge2}")
        pump(0.3)
        self.assertEqual(pattern.Direction2[0], seed)
        self.assertTrue(pattern.Direction2[1][0].endswith(edge2))
        self.assertFalse(direction2.isChecked())
        distance2.setProperty("rawValue", 12.0)
        count2.setValue(2)
        pump(0.3)
        self.assertEqual(int(pattern.Count2), 2)
        self.assertAlmostEqual(pattern.Distance2.Value, 12.0)

        def checkGrid(sign2):
            copies = list(pattern.Instances)
            self.assertEqual(len(copies), 5)
            cells = set()
            for copy in copies:
                i, j = AssemblyPattern.cellOf(copy)
                cells.add((i, j))
                offset = self.along * (15.0 * i) + along2 * (sign2 * 12.0 * j)
                expected = App.Placement(offset, App.Rotation()).multiply(seed.Placement)
                self.assertTrue(copy.Placement.isSame(expected, 1e-6), f"{copy.Label} ({i}, {j})")
            self.assertEqual(cells, {(1, 0), (2, 0), (0, 1), (1, 1), (2, 1)})

        checkGrid(1.0)
        main.findChild(QtWidgets.QCheckBox, "patternReversed2").setChecked(True)
        pump(0.3)
        self.assertTrue(pattern.Reversed2)
        checkGrid(-1.0)
        self.assertTrue(AssemblyPattern.activePanel.accept())
        pump(0.3)
        self.assertFalse(Gui.Control.activeDialog(), "the panel closed")
        self.assertTrue(waitFor(lambda: self.shown() is not None))
        shown = self.shown()
        headers = list(shown)
        self.assertEqual(headers[0], "Instances (6)")
        # Reopened, the box is ticked and shows the second direction's values
        k = shown[headers[1]].index("Linear pattern 1")
        self.doubleClick(self.row(1, k))
        self.assertTrue(waitFor(lambda: bool(Gui.Control.activeDialog())), "the panel opens again")
        # The new panel's own widgets (the first panel's may outlive it under the same names)
        panel = AssemblyPattern.activePanel
        self.assertIsNotNone(panel)
        self.assertTrue(panel.second.isChecked())
        self.assertTrue(panel.secondBox.isVisible())
        self.assertTrue(panel.reversed2.isChecked())
        self.assertEqual(panel.count2.value(), 2)
        self.assertAlmostEqual(panel.amount2.property("rawValue"), 12.0)
        self.assertTrue(panel.direction2Label.text().endswith(edge2))
        panel.reject()
        pump(0.3)
        checkGrid(-1.0)
        # Undo takes the pattern and its copies back
        name = pattern.Name
        names = [c.Name for c in pattern.Instances]
        Gui.runCommand("Std_Undo")
        pump(0.4)
        self.assertIsNone(doc.getObject(name))
        for n in names:
            self.assertIsNone(doc.getObject(n), n)


if __name__ == "__main__":
    unittest.main()
