# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#723): Part Studio variables have a place in the history

"""A Part Studio variable (Onshape's Variable feature) sits right after one row of its studio's
history (PartDesign.studioSequence). Onshape's rules (notes/onshape-facts.md DV1 and DV4):

- DV1: a Variable Studio's w = 10 and a Part Studio Variable w = 20 in one studio. A feature placed
  before the Variable takes 10, one placed after it takes 20.
- DV4: a feature placed before the Variable it uses fails; the Variable itself is fine.

Designed geometry: each feature is an AdditiveBox 10 x 10 x 10 in its own Body whose Length is an
expression, so the expected Length is the value of the variable the rules pick, and the volume is
Length x 100. Nothing comes from a user's file."""

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import PartDesign


class TestVariableHistoryPosition(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("VariableHistory")
        # The document's Variable Studio stand-in: a top-level set, seen from every studio
        self.outer = self.doc.addObject("App::VarSet", "Outer")
        self.outer.addProperty("App::PropertyLength", "w")
        self.outer.w = 10
        self.studio = self.doc.addObject("App::Part", "Studio")
        self.vars = self.doc.addObject("App::VarSet", "StudioVars")
        self.studio.addObject(self.vars)
        self.doc.recompute()

    def tearDown(self):
        for name in list(App.listDocuments()):
            if name.startswith("VariableHistory"):
                App.closeDocument(name)

    def box(self, name):
        body = self.doc.addObject("PartDesign::Body", name + "Body")
        self.studio.addObject(body)
        box = body.newObject("PartDesign::AdditiveBox", name)
        box.Length = box.Width = box.Height = 10
        self.doc.recompute()
        return box

    def addVariable(self, name, value):
        self.vars.addProperty("App::PropertyLength", name)
        setattr(self.vars, name, value)
        self.doc.recompute()

    def assertLength(self, box, length):
        self.assertNotIn("Invalid", box.State, box.getStatusString())
        self.assertAlmostEqual(box.Length.Value, length, places=9)
        self.assertAlmostEqual(box.Shape.Volume, length * 100, places=6)

    def assertFails(self, box, text):
        self.assertIn("Invalid", box.State)
        self.assertIn(text, box.getStatusString())

    # DV1
    def testShadowsFromItsPlaceOn(self):
        """A by #w, then the studio's w = 20, then B by #w: A is 10 and B is 20."""
        a = self.box("A")
        a.setExpression("Length", "#w")
        self.doc.recompute()
        self.addVariable("w", 20)
        self.assertEqual(PartDesign.variablePosition(self.vars, "w"), a)
        b = self.box("B")
        b.setExpression("Length", "#w")
        self.doc.recompute()
        self.assertLength(a, 10)
        self.assertLength(b, 20)
        self.assertEqual(a.ExpressionEngine[0][1], "Outer.w")
        self.assertEqual(b.ExpressionEngine[0][1], "StudioVars.w")

    def testEnteredAboveTheVariableTakesTheOuterOne(self):
        """#w entered on A, above the studio's w, is the Variable Studio's (input sees the place)."""
        a = self.box("A")
        self.addVariable("w", 20)
        a.setExpression("Length", "#w")
        self.doc.recompute()
        self.assertLength(a, 10)
        self.assertEqual(a.ExpressionEngine[0][1], "Outer.w")

    def testMovedAboveAUserOfTheOuterOneIsLoud(self):
        """The studio's w moved above A, which uses the outer w: Onshape's A would take 20, so A
        fails and says to enter #w again; entered again it takes 20."""
        a = self.box("A")
        a.setExpression("Length", "#w")
        self.addVariable("w", 20)
        PartDesign.setVariablePosition(self.vars, "w", None)
        self.doc.recompute()
        self.assertFails(a, "enter #w again")
        a.setExpression("Length", "#w")
        self.doc.recompute()
        self.assertLength(a, 20)

    # DV4
    def testUseBeforeSetFails(self):
        """q = 20 then a box by #q: 20. q moved below the box: the box fails, q is fine. Moved
        back up: 20 again."""
        self.addVariable("q", 20)
        self.assertIsNone(PartDesign.variablePosition(self.vars, "q"))
        p = self.box("P")
        p.setExpression("Length", "#q")
        self.doc.recompute()
        self.assertLength(p, 20)
        PartDesign.setVariablePosition(self.vars, "q", p)
        self.doc.recompute()
        self.assertFails(p, "can't be used before it is set")
        self.assertNotIn("Invalid", self.vars.State)
        PartDesign.setVariablePosition(self.vars, "q", None)
        self.doc.recompute()
        self.assertLength(p, 20)

    def testEnteringAVariableSetLaterIsRefused(self):
        """#q entered on a box above q (and no outer q) is refused at once, nothing bound."""
        p = self.box("P")
        self.addVariable("q", 20)
        with self.assertRaises(Exception) as ctx:
            p.setExpression("Length", "#q")
        self.assertIn("before it is set", str(ctx.exception))
        self.assertEqual(p.ExpressionEngine, [])

    # The place itself
    def testAddedAtTheRolledBackBar(self):
        """With the studio rolled back to A, a new variable goes right after A, not at the end."""
        a = self.box("A")
        b = self.box("B")
        PartDesign.rollStudioTo(self.studio, a)
        self.addVariable("r", 15)
        self.assertEqual(PartDesign.variablePosition(self.vars, "r"), a)
        PartDesign.rollStudioToEnd(self.studio)
        self.doc.recompute()
        b.setExpression("Length", "#r")
        self.doc.recompute()
        self.assertLength(b, 15)

    def testFollowsTheRowBeforeADeletedOne(self):
        """q after B (A, B, C): B deleted, q follows A; C still uses it."""
        a = self.box("A")
        b = self.box("B")
        self.addVariable("q", 20)
        self.assertEqual(PartDesign.variablePosition(self.vars, "q"), b)
        c = self.box("C")
        c.setExpression("Length", "#q")
        self.doc.recompute()
        body = b.getParentGeoFeatureGroup()
        self.doc.removeObject(b.Name)
        self.doc.removeObject(body.Name)
        self.doc.recompute()
        self.assertEqual(PartDesign.variablePosition(self.vars, "q"), a)
        self.assertLength(c, 20)

    def testRenameKeepsThePlace(self):
        a = self.box("A")
        self.addVariable("q", 20)
        self.vars.renameProperty("q", "q2")
        self.assertEqual(PartDesign.variablePosition(self.vars, "q2"), a)
        self.assertIsNone(PartDesign.variablePosition(self.vars, "q"))

    def testUndoAndRedo(self):
        self.doc.UndoMode = 1
        a = self.box("A")
        self.doc.openTransaction("add q")
        self.addVariable("q", 20)
        self.doc.commitTransaction()
        self.assertEqual(PartDesign.variablePosition(self.vars, "q"), a)
        self.doc.undo()
        self.assertFalse(hasattr(self.vars, "q"))
        self.assertEqual(dict(self.vars.VariablePositions), {})
        self.doc.redo()
        self.assertTrue(hasattr(self.vars, "q"))
        self.assertEqual(PartDesign.variablePosition(self.vars, "q"), a)

    def testRefusals(self):
        a = self.box("A")
        self.addVariable("q", 20)
        with self.assertRaises(ValueError):
            PartDesign.setVariablePosition(self.vars, "nope", a)
        with self.assertRaises(ValueError):
            PartDesign.setVariablePosition(self.outer, "w", a)
        with self.assertRaises(ValueError):
            PartDesign.setVariablePosition(self.vars, "q", self.vars)

    def testSaveAndReopen(self):
        """The place is saved: after a reopen the box above q still fails, B below it is 20; a
        set saved without places (moved to the start) is seen by every row."""
        p = self.box("P")
        self.addVariable("q", 20)
        b = self.box("B")
        b.setExpression("Length", "#q")
        self.doc.recompute()
        folder = tempfile.mkdtemp(prefix="varhistory")
        try:
            path = os.path.join(folder, "VariableHistory.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.vars = self.doc.getObject("StudioVars")
            p = self.doc.getObject("P")
            self.assertEqual(PartDesign.variablePosition(self.vars, "q"), p)
            with self.assertRaises(Exception):
                p.setExpression("Length", "#q")
            self.doc.getObject("StudioVars").q = 30
            self.doc.recompute()
            self.assertLength(self.doc.getObject("B"), 30)
            PartDesign.setVariablePosition(self.vars, "q", None)
            p.setExpression("Length", "#q")
            self.doc.recompute()
            self.assertLength(p, 30)
        finally:
            App.closeDocument(self.doc.Name)
            shutil.rmtree(folder, ignore_errors=True)
