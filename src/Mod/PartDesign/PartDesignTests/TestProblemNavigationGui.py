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

"""Stepping through the objects in error or warning (FreeCAD-CH, ops#149, PLAN decision 29).

- "Next problem" (Std_TreeNextProblem, F8) selects the next object in error or warning after the
  selection, in tree order, errors and warnings together, and wraps; "Previous problem"
  (Std_TreePreviousProblem, Shift+F8) goes back. Objects that only need a recompute don't count.
- The tree's search box takes :errors, :warnings and :problems (or any start of them, ":e"):
  typing highlights the matches, Enter selects them all.
- Both skip an object hidden from the tree (ShowInTree off, or under a hidden parent) while the
  document's "Show hidden" is off, and un-hide no row (review M1). A failing sketch nested under
  its Pad counts too: the Pad's or the Body's row may be the hidden one (ops#208).

Designed model, built by the test (the reference solver on, V2):
- Body: a 20 x 10 rectangle padded 10 ("Pad"), a fillet of radius 1 on its vertical edge at
  (20, 0) ("Fillet"), then a 2 x 2 square on the top pocketed "Up to face" with no face picked
  ("Pocket"). The rectangle is then drawn again the other way round: the fillet finds its edge
  by geometry only and computes with a warning; the pocket fails.
- Body001: a 10 x 10 rectangle at x = 40 padded "To last" as its first feature ("Pad001"): there
  is no solid to reach, so it fails.
Tree order: Body (Pad, with Profile under it, Fillet, Pocket, with Square under it), then Body001
(Pad001, with Profile001 under it). The problems in order: Fillet (warning), Pocket (error), Pad001
(error).

Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Sketcher
from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import Z, edge
from PartDesignTests.TestExpressionFieldsGui import pump

HIGHLIGHT = (255, 255, 0, 100)


def searchBox():
    """A tree panel's search box. Under the test runner a panel's widgets can come back as stale
    PySide wrappers (already deleted), so the first box that answers is taken; the search works
    on the active document from any panel."""
    for edit in Gui.getMainWindow().findChildren(QtWidgets.QLineEdit):
        try:
            panel = edit.parentWidget()
            if panel is not None and panel.metaObject().className() == "Gui::TreePanel":
                return edit
        except RuntimeError:
            continue
    return None


def highlighted():
    """The labels of the items with the search highlight, in every model tree that answers,
    read at once (PySide drops a child item's wrapper when its parent's goes)."""
    labels = set()

    def walk(item):
        brush = item.background(0)
        if brush.style() != QtCore.Qt.NoBrush and brush.color().getRgb() == HIGHLIGHT:
            labels.add(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        try:
            if tree.metaObject().className() != "Gui::TreeWidget":
                continue
            for i in range(tree.topLevelItemCount()):
                walk(tree.topLevelItem(i))
        except RuntimeError:
            continue
    return sorted(labels)


def visibleRows():
    """The labels of the rows shown in every model tree that answers: neither the row nor a
    parent hidden (rows of collapsed parents count as shown)."""
    labels = set()

    def walk(item):
        if item.isHidden():
            return
        labels.add(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        try:
            if tree.metaObject().className() != "Gui::TreeWidget":
                continue
            for i in range(tree.topLevelItemCount()):
                walk(tree.topLevelItem(i))
        except RuntimeError:
            continue
    return labels


def selectedNames():
    return [obj.Name for obj in Gui.Selection.getSelection()]


class TestProblemNavigationGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("ProblemNavigation")
        self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = True
        Gui.activateView("Gui::View3DInventor", True)
        Gui.Selection.clearSelection()

    def tearDown(self):
        Gui.Selection.clearSelection()
        edit = searchBox()
        if edit is not None:
            edit.clear()
        App.closeDocument(self.doc.Name)
        pump()

    def model(self):
        doc = self.doc
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape))
        fillet.Radius = 1
        doc.recompute()
        self.assertTrue(fillet.isValid())
        square = models.sketch(doc, "Square", models.rectangle(2, 2, 4, 4), body, z=10)
        pocket = models.pocket(body, square, 3)
        pocket.Type = "UpToFace"
        doc.recompute()
        # The rectangle drawn again: new geometry IDs, the same edges
        profile.deleteAllGeometry()
        profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        doc.recompute()

        body2 = doc.addObject("PartDesign::Body", "Body001")
        profile2 = models.sketch(doc, "Profile001", models.rectangle(40, 0, 50, 10), body2)
        pad2 = models.pad(body2, profile2, 10, "Pad001")
        pad2.Type = "UpToLast"
        doc.recompute()
        pump()

        self.assertIn("Warning", fillet.State)
        self.assertNotIn("Invalid", fillet.State)
        self.assertIn("Invalid", pocket.State)
        self.assertIn("Invalid", pad2.State)
        for obj in (pad, profile, square, profile2):
            self.assertNotIn("Invalid", obj.State)
            self.assertNotIn("Warning", obj.State)
        return pad

    def step(self, forward=True):
        Gui.runCommand("Std_TreeNextProblem" if forward else "Std_TreePreviousProblem", 0)
        pump()
        return selectedNames()

    # -- Next problem ----------------------------------------------------------------------------

    def testKeys(self):
        self.assertEqual(Gui.Command.get("Std_TreeNextProblem").getShortcut(), "F8")
        self.assertEqual(Gui.Command.get("Std_TreePreviousProblem").getShortcut(), "Shift+F8")

    def testNextGoesInTreeOrderAndWraps(self):
        self.model()
        self.assertEqual(self.step(), ["Fillet"])
        self.assertEqual(self.step(), ["Pocket"])
        self.assertEqual(self.step(), ["Pad001"])
        self.assertEqual(self.step(), ["Fillet"], "doesn't wrap to the first")

    def testPreviousGoesBackAndWraps(self):
        self.model()
        self.assertEqual(self.step(False), ["Pad001"], "nothing selected: the last")
        self.assertEqual(self.step(False), ["Pocket"])
        self.assertEqual(self.step(False), ["Fillet"])
        self.assertEqual(self.step(False), ["Pad001"], "doesn't wrap to the last")

    def testNextStartsAfterTheSelection(self):
        pad = self.model()
        Gui.Selection.addSelection(self.doc.Name, "Body", "Pad.")
        pump()
        self.assertEqual(selectedNames(), ["Pad"])
        self.assertEqual(self.step(), ["Fillet"])
        # A sketch nested under its feature comes after that feature in the tree
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "Body", "Pocket.Square.")
        pump()
        self.assertEqual(selectedNames(), ["Square"])
        self.assertEqual(self.step(), ["Pad001"])
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "Body", "Pocket.Square.")
        pump()
        self.assertEqual(self.step(False), ["Pocket"])

    def hideFromTree(self):
        """Pocket hidden from the tree, and Body001 (so Pad001 under it), with "Show hidden" off."""
        self.model()
        self.assertFalse(self.doc.ShowHidden)
        self.doc.getObject("Pocket").ViewObject.ShowInTree = False
        self.doc.getObject("Body001").ViewObject.ShowInTree = False
        pump()
        self.assertTrue({"Pocket", "Body001", "Pad001"}.isdisjoint(visibleRows()))

    def assertStillHidden(self):
        rows = visibleRows()
        self.assertIn("Fillet", rows)
        for label in ("Pocket", "Body001", "Pad001"):
            self.assertNotIn(label, rows, f"{label} un-hidden in the tree")

    def testNextSkipsProblemsHiddenFromTheTree(self):
        """A problem hidden from the tree, or under a hidden parent, is skipped and no hidden row
        comes back (ops#149 review M1)."""
        self.hideFromTree()
        self.assertEqual(self.step(), ["Fillet"])
        self.assertEqual(self.step(), ["Fillet"], "the only shown problem: wraps to itself")
        self.assertEqual(self.step(False), ["Fillet"])
        self.assertStillHidden()
        # "Show hidden" on: they count again
        self.doc.ShowHidden = True
        pump()
        self.assertEqual(self.step(), ["Pocket"])

    def testTokensSkipProblemsHiddenFromTheTree(self):
        self.hideFromTree()
        self.assertEqual(self.search(":e"), [])
        self.assertEqual(self.search(":problems"), ["Fillet"])
        self.assertStillHidden()

    def addBadSketch(self, bodyName, sketchName, padName, x):
        """A body whose Pad takes a sketch with two conflicting length constraints on one side:
        the sketch fails (a problem inside a Pad's row), and so does the Pad."""
        body = self.doc.addObject("PartDesign::Body", bodyName)
        sketch = models.sketch(self.doc, sketchName, models.rectangle(x, 0, x + 10, 10), body)
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 10))
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 20))
        pad = models.pad(body, sketch, 10, padName)
        self.doc.recompute()
        pump()
        self.assertIn("Invalid", sketch.State)
        self.assertIn("Invalid", pad.State)
        return body, sketch, pad

    def testFailingSketchUnderHiddenBodyIsSkipped(self):
        """A failing sketch nested under its Pad, in a Body hidden from the tree: the sketch's
        top parent is itself (its row's parent is not a group), so only the Pad and Body rows
        above it say it is out of sight (ops#208)."""
        self.hideFromTree()
        body, sketch, pad = self.addBadSketch("Body002", "BadSketch", "BadPad", 60)
        body.ViewObject.ShowInTree = False
        pump()
        self.assertTrue({"Body002", "BadPad", "BadSketch"}.isdisjoint(visibleRows()))
        self.assertEqual(self.step(), ["Fillet"])
        self.assertEqual(self.step(False), ["Fillet"])
        self.assertEqual(self.search(":e"), [])
        self.assertEqual(self.search(":problems"), ["Fillet"])
        self.assertTrue({"Body002", "BadPad", "BadSketch"}.isdisjoint(visibleRows()))
        # "Show hidden" on: the sketch counts again
        self.doc.ShowHidden = True
        pump()
        self.assertIn("BadSketch", self.search(":errors"))

    def testFailingSketchUnderHiddenPadIsSkipped(self):
        """The same with the Body shown and its Pad hidden from the tree."""
        self.hideFromTree()
        body, sketch, pad = self.addBadSketch("Body002", "BadSketch", "BadPad", 60)
        pad.ViewObject.ShowInTree = False
        pump()
        rows = visibleRows()
        self.assertIn("Body002", rows)
        self.assertTrue({"BadPad", "BadSketch"}.isdisjoint(rows))
        self.assertEqual(self.step(), ["Fillet"])
        self.assertEqual(self.search(":e"), [])
        self.assertTrue({"BadPad", "BadSketch"}.isdisjoint(visibleRows()))

    def testPreviousFindsAProblemMadeAMomentAgo(self):
        """Run right after the recompute, before the tree's pending update: the new object's row
        is made first (ops#149 review L5)."""
        self.model()
        body3 = self.doc.addObject("PartDesign::Body", "Body002")
        profile3 = models.sketch(self.doc, "Profile002", models.rectangle(60, 0, 70, 10), body3)
        pad3 = models.pad(body3, profile3, 10, "Pad002")
        pad3.Type = "UpToLast"
        self.doc.recompute()
        self.assertIn("Invalid", pad3.State)
        Gui.runCommand("Std_TreePreviousProblem", 0)  # no events in between
        pump()
        self.assertEqual(selectedNames(), ["Pad002"])

    def testTouchedDoesNotCount(self):
        """A model without errors or warnings, only an object that needs a recompute: Next
        problem selects nothing."""
        body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), body)
        pad = models.pad(body, profile, 10)
        self.doc.recompute()
        pad.Length = 12
        self.assertIn("Touched", pad.State)
        pump()
        self.assertEqual(self.step(), [])
        Gui.Selection.addSelection(self.doc.Name, "Body", "Pad.")
        pump()
        self.assertEqual(self.step(), ["Pad"], "the selection changed")

    # -- search tokens ---------------------------------------------------------------------------

    def search(self, text, enter=False):
        edit = searchBox()
        self.assertIsNotNone(edit, "no tree search box")
        # The highlights are read at once: the box's wrapper may not outlive an event loop
        edit.setText(text)
        labels = highlighted()
        if enter:
            edit.returnPressed.emit()
            pump()
        return labels

    def testErrorsToken(self):
        self.model()
        self.assertEqual(self.search(":errors"), ["Pad001", "Pocket"])
        self.assertEqual(self.search(":errors", enter=True), ["Pad001", "Pocket"])
        self.assertEqual(sorted(selectedNames()), ["Pad001", "Pocket"])

    def testWarningsToken(self):
        self.model()
        self.assertEqual(self.search(":warnings"), ["Fillet"])
        self.search(":warnings", enter=True)
        self.assertEqual(selectedNames(), ["Fillet"])

    def testProblemsTokenAndPrefixes(self):
        self.model()
        self.assertEqual(self.search(":problems"), ["Fillet", "Pad001", "Pocket"])
        self.assertEqual(self.search(":e"), ["Pad001", "Pocket"])
        self.assertEqual(self.search(":warn"), ["Fillet"])
        # Not a token: an ordinary search, which finds nothing and highlights nothing
        self.assertEqual(self.search(":zzz"), [])
        self.assertEqual(self.search(""), [], "clearing the box leaves highlights")
