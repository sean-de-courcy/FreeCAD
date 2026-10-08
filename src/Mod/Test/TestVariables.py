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

"""`#name` in expressions (FreeCAD-CH, ops#152, notes/variables-design.md section 6, T1-T10).

`#Width` is input sugar: when an expression is parsed it becomes the full path of the one
variable named `Width` in the owner's document, a VarSet property or a Spreadsheet alias.
Every model here is built by the test, and every expected value is fixed up front.
"""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD


def expressionText(obj, prop):
    for path, text in obj.ExpressionEngine:
        if path == prop:
            return text
    return None


class VariablesBase(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestVariables")
        self.extraDocs = []
        self.tempDir = None

    def tearDown(self):
        for doc in [self.doc] + self.extraDocs:
            if doc.Name in FreeCAD.listDocuments():
                FreeCAD.closeDocument(doc.Name)
        if self.tempDir:
            shutil.rmtree(self.tempDir, ignore_errors=True)

    def addVarSet(self, name="VarSet", **lengths):
        varSet = self.doc.addObject("App::VarSet", name)
        for key, value in lengths.items():
            varSet.addProperty("App::PropertyLength", key)
            setattr(varSet, key, value)
        return varSet

    def addSheet(self, name="Sheet", **aliases):
        """aliases: alias -> (cell, content)."""
        sheet = self.doc.addObject("Spreadsheet::Sheet", name)
        for alias, (cell, content) in aliases.items():
            sheet.set(cell, content)
            sheet.setAlias(cell, alias)
        return sheet

    def addBox(self, name="Box", length=10, width=10, height=10):
        box = self.doc.addObject("Part::Box", name)
        box.Length, box.Width, box.Height = length, width, height
        return box

    def assertParserError(self, fn, *fragments):
        with self.assertRaises(FreeCAD.Base.ParserError) as cm:
            fn()
        message = str(cm.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message


class TestScanner(VariablesBase):
    """T1. What is rewritten and what is left alone."""

    def setUp(self):
        super().setUp()
        self.varSet = self.addVarSet(Width=20, a=3, b=4, Breite_2=6)
        self.varSet.addProperty("App::PropertyLength", "größe")
        setattr(self.varSet, "größe", 7)
        self.box = self.addBox()
        self.doc.recompute()

    def textOf(self, expr):
        self.box.setExpression("Length", expr)
        return expressionText(self.box, "Length")

    def test_hash_name_becomes_path(self):
        self.assertEqual(self.textOf("#Width * 2"), "VarSet.Width * 2")

    def test_operators_around(self):
        self.assertEqual(self.textOf("(#a+#b)"), "VarSet.a + VarSet.b")
        self.assertEqual(self.textOf("-#a + 10 mm"), "-VarSet.a + 10 mm")

    def test_hash_after_name_is_an_error(self):
        # `#a#b`: the second `#` follows an identifier, so it isn't rewritten; the parser rejects it.
        self.assertParserError(lambda: self.box.setExpression("Length", "#a#b"))

    def test_name_characters(self):
        self.assertEqual(self.textOf("#Breite_2"), "VarSet.Breite_2")
        self.assertEqual(self.textOf("#größe"), "VarSet.größe")

    def test_unit_symbol_name(self):
        # A property named `L` can't exist (unit symbols aren't identifiers), so `#L` finds nothing.
        self.assertParserError(
            lambda: self.box.setExpression("Length", "#L"), "no variable named L"
        )

    def test_document_paths_unchanged(self):
        # `Doc#Obj.Prop`, `<<Doc>>#Obj.Prop`, `<<Doc>> #Obj.Prop` and `Doc # Obj.Prop` aren't
        # rewritten: no variable here is named `Obj`, so a rewrite would raise `no variable named
        # Obj`. The `#` inside `<<a#b>>` would become `VarSet.b`, which exists, so that case is
        # checked by its stored text.
        other = FreeCAD.newDocument("VarOther")
        self.extraDocs.append(other)
        obj = other.addObject("App::VarSet", "Obj")
        obj.addProperty("App::PropertyLength", "Prop")
        obj.Prop = 12
        labelled = self.doc.addObject("App::VarSet", "Labelled")
        labelled.Label = "a#b"
        labelled.addProperty("App::PropertyLength", "Size")
        labelled.Size = 9
        # An expression may link to another document only once both are saved.
        self.tempDir = tempfile.mkdtemp(prefix="TestVariables")
        self.doc.saveAs(os.path.join(self.tempDir, "variables.FCStd"))
        other.saveAs(os.path.join(self.tempDir, "other.FCStd"))
        for expr, value in [
            (f"{other.Name}#Obj.Prop", 12),
            (f"<<{other.Label}>>#Obj.Prop", 12),
            (f"<<{other.Label}>> #Obj.Prop", 12),
            (f"{other.Name} # Obj.Prop", 12),
        ]:
            with self.subTest(expr=expr):
                self.assertAlmostEqual(float(self.box.evalExpression(expr)), value)
                text = self.textOf(expr)
                self.assertIn("#Obj.Prop", text)
                self.assertNotIn("VarSet", text)
        self.assertEqual(self.textOf("<<a#b>>.Size"), "<<a#b>>.Size")
        self.assertAlmostEqual(float(self.box.evalExpression("<<a#b>>.Size")), 9)

    def test_unterminated_string(self):
        # `<<` without its `>>` isn't a string: the parser rejects the text as it does today.
        for expr in ["#Width + <<x", "<<x #Width", r"<<x\>> #Width"]:
            with self.subTest(expr=expr):
                self.assertParserError(lambda: self.box.setExpression("Length", expr))

    def test_no_owner(self):
        # Without an owner there is no document to search, so `#Width` stays a syntax error.
        self.assertParserError(
            lambda: FreeCAD.DocumentObject.evalExpression("#Width"),
            "Failed to parse expression '#Width'",
        )


class TestResolution(VariablesBase):
    def test_varset_variable(self):
        """T2. `#Width` in a Box: the stored text is the full path, and the value follows."""
        varSet = self.addVarSet(Width=20)
        box = self.addBox()
        box.setExpression("Length", "#Width * 2")
        self.doc.recompute()
        self.assertEqual(expressionText(box, "Length"), "VarSet.Width * 2")
        self.assertAlmostEqual(box.Length.Value, 40)
        self.assertAlmostEqual(box.Shape.Volume, 40 * 10 * 10)
        varSet.Width = 25
        self.doc.recompute()
        self.assertAlmostEqual(box.Length.Value, 50)
        self.assertAlmostEqual(box.Shape.Volume, 5000)

    def checkAlias(self, recomputeFirst):
        sheet = self.addSheet(Depth=("A1", "30 mm"))
        box = self.addBox(length=20, width=10)
        if recomputeFirst:
            self.doc.recompute()
        box.setExpression("Height", "#Depth")
        self.doc.recompute()
        self.assertEqual(expressionText(box, "Height"), "Sheet.Depth")
        self.assertAlmostEqual(box.Shape.Volume, 20 * 10 * 30)
        sheet.set("A1", "35 mm")
        self.doc.recompute()
        self.assertAlmostEqual(box.Shape.Volume, 20 * 10 * 35)

    def test_alias_after_recompute(self):
        """T3. An alias, with the sheet recomputed first."""
        self.checkAlias(recomputeFirst=True)

    def test_alias_before_first_recompute(self):
        """T3. An alias, before the sheet's first recompute (its cell property doesn't exist yet)."""
        self.checkAlias(recomputeFirst=False)

    def test_ambiguous_varset_and_alias(self):
        """T4. `Width` in a VarSet and as an alias: an error naming both; full paths still work."""
        self.addVarSet(Width=20)
        self.addSheet(Width=("A1", "30 mm"))
        box = self.addBox()
        self.doc.recompute()
        self.assertParserError(
            lambda: box.setExpression("Length", "#Width"),
            "#Width is ambiguous",
            "VarSet.Width",
            "Sheet.Width",
        )
        box.setExpression("Length", "Sheet.Width")
        self.doc.recompute()
        self.assertAlmostEqual(box.Length.Value, 30)
        box.setExpression("Length", "VarSet.Width")
        self.doc.recompute()
        self.assertAlmostEqual(box.Length.Value, 20)

    def test_ambiguous_two_varsets(self):
        """T4. `Width` in two VarSets."""
        self.addVarSet("VarSet", Width=20)
        self.addVarSet("VarSet001", Width=21)
        box = self.addBox()
        self.assertParserError(
            lambda: box.setExpression("Length", "#Width"),
            "#Width is ambiguous",
            "VarSet.Width",
            "VarSet001.Width",
        )
        box.setExpression("Length", "VarSet001.Width")
        self.doc.recompute()
        self.assertAlmostEqual(box.Length.Value, 21)

    def test_unknown(self):
        """T5. `#Nope`: an error naming it, and the property keeps its value and expression."""
        self.addVarSet(Width=20)
        box = self.addBox(length=17)
        box.setExpression("Length", "VarSet.Width")
        self.doc.recompute()
        self.assertAlmostEqual(box.Length.Value, 20)
        self.assertParserError(
            lambda: box.setExpression("Length", "#Nope"), "no variable named Nope"
        )
        self.doc.recompute()
        self.assertEqual(expressionText(box, "Length"), "VarSet.Width")
        self.assertAlmostEqual(box.Length.Value, 20)

    def test_static_binding(self):
        """T6. A later alias `Width` doesn't re-bind an existing expression."""
        self.addVarSet(Width=20)
        box = self.addBox()
        box.setExpression("Length", "#Width * 2")
        self.doc.recompute()
        self.addSheet(Width=("A1", "99 mm"))
        self.doc.recompute()
        self.assertEqual(expressionText(box, "Length"), "VarSet.Width * 2")
        self.assertAlmostEqual(box.Length.Value, 40)

    def test_within_varset(self):
        """T9. Inside a VarSet, `#Width` is stored in the parser's form for the owner: `Width`."""
        varSet = self.addVarSet(Width=20)
        varSet.addProperty("App::PropertyLength", "Depth")
        varSet.setExpression("Depth", "#Width + 5 mm")
        self.doc.recompute()
        self.assertEqual(expressionText(varSet, "Depth"), "Width + 5 mm")
        self.assertAlmostEqual(varSet.Depth.Value, 25)

    def test_dependencies(self):
        """T10 (part). Expressions written with `#Width` depend on the VarSet like full paths do.

        The uses helper's exact oracle ({Box.Length, Sheet.B1}) is the gtest
        VariableDisplay.usesCoverSheetCells (Spreadsheet_tests_run): the helper has no Python API.
        """
        varSet = self.addVarSet(Width=20)
        box = self.addBox()
        box.setExpression("Length", "#Width * 2")
        sheet = self.addSheet()
        sheet.set("B1", "=#Width")
        self.doc.recompute()
        self.assertEqual(sheet.getContents("B1"), "=VarSet.Width")
        self.assertAlmostEqual(sheet.B1.Value, 20)
        self.assertEqual({o.Name for o in varSet.InList}, {"Box", "Sheet"})


class TestSaveAndRename(VariablesBase):
    def buildT2T3(self):
        varSet = self.addVarSet(Width=20)
        box = self.addBox()
        box.setExpression("Length", "#Width * 2")
        self.addSheet(Depth=("A1", "30 mm"))
        box2 = self.addBox("Box2", length=20, width=10)
        box2.setExpression("Height", "#Depth")
        self.doc.recompute()
        return varSet, box, box2

    def test_save_and_reopen(self):
        """T7. The file holds only the stock grammar; the values follow after a reopen."""
        self.buildT2T3()
        self.tempDir = tempfile.mkdtemp(prefix="TestVariables")
        path = os.path.join(self.tempDir, "variables.FCStd")
        self.doc.saveAs(path)
        with zipfile.ZipFile(path) as z:
            xml = z.read("Document.xml").decode("utf-8")
        expressions = re.findall(r'expression="([^"]*)"', xml)
        self.assertIn("VarSet.Width * 2", expressions)
        self.assertIn("Sheet.Depth", expressions)
        for text in expressions:
            # A `#` is only ever a document separator: after an identifier or `>>`.
            self.assertIsNone(re.search(r"(?<![\w>])#", re.sub(r"\s+#", "#", text)), text)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        self.doc.getObject("VarSet").Width = 25
        self.doc.getObject("Sheet").set("A1", "35 mm")
        self.doc.recompute()
        self.assertAlmostEqual(self.doc.getObject("Box").Length.Value, 50)
        self.assertAlmostEqual(self.doc.getObject("Box2").Shape.Volume, 20 * 10 * 35)

    def test_rename(self):
        """T8. A rename reaches `#`-written expressions, sheet cells and other documents, as one
        undo step (ops#177: under a transaction it raised TypeError when a feature expression and a
        sheet cell both used the property)."""
        self.doc.UndoMode = 1
        varSet = self.addVarSet(Width=20)
        box = self.addBox()
        box.setExpression("Length", "#Width * 2")
        sheet = self.addSheet()
        sheet.set("B1", "=#Width")
        other = FreeCAD.newDocument("VarRenameOther")
        self.extraDocs.append(other)
        otherBox = other.addObject("Part::Box", "Box")
        # An expression may link to another document only once both are saved.
        self.tempDir = tempfile.mkdtemp(prefix="TestVariables")
        self.doc.saveAs(os.path.join(self.tempDir, "variables.FCStd"))
        other.saveAs(os.path.join(self.tempDir, "other.FCStd"))
        otherBox.setExpression("Length", f"{self.doc.Name}#VarSet.Width")
        self.doc.recompute()
        other.recompute()
        self.assertAlmostEqual(otherBox.Length.Value, 20)

        self.doc.openTransaction("Rename")
        varSet.renameProperty("Width", "BoxWidth")
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(expressionText(box, "Length"), "VarSet.BoxWidth * 2")
        self.assertEqual(sheet.getContents("B1"), "=VarSet.BoxWidth")
        self.assertEqual(expressionText(otherBox, "Length"), f"{self.doc.Name}#VarSet.BoxWidth")
        self.assertAlmostEqual(box.Length.Value, 40)
        self.assertAlmostEqual(sheet.B1.Value, 20)

        self.doc.undo()
        self.doc.recompute()
        other.recompute()
        self.assertTrue(hasattr(varSet, "Width"))
        self.assertFalse(hasattr(varSet, "BoxWidth"))
        self.assertEqual(expressionText(box, "Length"), "VarSet.Width * 2")
        self.assertEqual(sheet.getContents("B1"), "=VarSet.Width")
        self.assertEqual(expressionText(otherBox, "Length"), f"{self.doc.Name}#VarSet.Width")
        self.assertAlmostEqual(box.Length.Value, 40)
        self.assertAlmostEqual(sheet.B1.Value, 20)
        self.assertAlmostEqual(otherBox.Length.Value, 20)

        self.doc.redo()
        self.doc.recompute()
        other.recompute()
        self.assertTrue(hasattr(varSet, "BoxWidth"))
        self.assertEqual(expressionText(box, "Length"), "VarSet.BoxWidth * 2")
        self.assertEqual(sheet.getContents("B1"), "=VarSet.BoxWidth")
        self.assertEqual(expressionText(otherBox, "Length"), f"{self.doc.Name}#VarSet.BoxWidth")
        self.assertAlmostEqual(box.Length.Value, 40)
        self.assertAlmostEqual(otherBox.Length.Value, 20)

    def buildSheetHistory(self):
        """A VarSet variable used by a Box and a sheet cell, and a committed transaction that
        edited the sheet, so the undo stack holds a copy of the sheet's cells."""
        self.doc.UndoMode = 1
        varSet = self.addVarSet(Width=20)
        target = self.addVarSet("Target")
        box = self.addBox()
        box.setExpression("Length", "#Width * 2")
        sheet = self.addSheet()
        sheet.set("B1", "=#Width")
        self.doc.recompute()
        self.doc.openTransaction("Edit sheet")
        sheet.set("A1", "5")
        self.doc.commitTransaction()
        self.doc.recompute()
        return varSet, target, box, sheet

    def test_rename_with_sheet_undo_history(self):
        """ops#179: a sheet's undo copy made every rename raise TypeError, with or without a
        transaction (PropertySheet built ObjectIdentifier(*this) for a copy with no owner)."""
        varSet, _, box, sheet = self.buildSheetHistory()
        varSet.renameProperty("Width", "W2")
        self.assertEqual(expressionText(box, "Length"), "VarSet.W2 * 2")
        self.assertEqual(sheet.getContents("B1"), "=VarSet.W2")

        self.doc.openTransaction("Rename")
        varSet.renameProperty("W2", "W3")
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(expressionText(box, "Length"), "VarSet.W3 * 2")
        self.assertEqual(sheet.getContents("B1"), "=VarSet.W3")
        self.assertAlmostEqual(box.Length.Value, 40)
        self.assertAlmostEqual(sheet.B1.Value, 20)

    def test_move_with_sheet_undo_history(self):
        """ops#179, the move slot: the same copy made every move raise TypeError."""
        varSet, target, box, sheet = self.buildSheetHistory()
        varSet.moveProperty("Width", target)
        self.assertEqual(expressionText(box, "Length"), "Target.Width * 2")
        self.assertEqual(sheet.getContents("B1"), "=Target.Width")

        self.doc.openTransaction("Move")
        target.moveProperty("Width", varSet)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(expressionText(box, "Length"), "VarSet.Width * 2")
        self.assertEqual(sheet.getContents("B1"), "=VarSet.Width")
        self.assertAlmostEqual(box.Length.Value, 40)
        self.assertAlmostEqual(sheet.B1.Value, 20)

    def test_rename_without_transaction_reaches_undo_states(self):
        """fork PR 148 review: a rename outside a transaction can't be undone, so the undo
        states already recorded must follow it: undoing an earlier change restores an expression
        that uses the new name."""
        self.doc.UndoMode = 1
        varSet = self.addVarSet(Width=20)
        box = self.addBox()
        self.doc.openTransaction("Length")
        box.setExpression("Length", "#Width * 2")
        self.doc.commitTransaction()
        self.doc.openTransaction("Height")
        box.setExpression("Height", "#Width")
        self.doc.commitTransaction()
        self.doc.recompute()

        varSet.renameProperty("Width", "BoxWidth")
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(expressionText(box, "Length"), "VarSet.BoxWidth * 2")
        self.assertIsNone(expressionText(box, "Height"))
        self.assertTrue(box.isValid())
        self.assertAlmostEqual(box.Length.Value, 40)

    def test_rename_in_application_transaction_with_redo_elsewhere(self):
        """fork PR 148 review: under an application transaction, renaming changes another
        document's expression, which opens a transaction there and clears its redo stack, freeing
        undo copies the rename was about to visit. Without the snapshot check this fails only
        when the freed copies come after otherBox's engine in the container map's (pointer)
        order."""
        varSet = self.addVarSet(Width=20)
        other = FreeCAD.newDocument("VarRenameRedo")
        self.extraDocs.append(other)
        other.UndoMode = 1
        otherBox = other.addObject("Part::Box", "Box")
        self.tempDir = tempfile.mkdtemp(prefix="TestVariables")
        self.doc.saveAs(os.path.join(self.tempDir, "variables.FCStd"))
        other.saveAs(os.path.join(self.tempDir, "other.FCStd"))
        otherBox.setExpression("Length", f"{self.doc.Name}#VarSet.Width")
        other.openTransaction("Height")
        otherBox.setExpression("Height", f"{self.doc.Name}#VarSet.Width / 2")
        other.commitTransaction()
        other.undo()
        self.assertEqual(other.RedoCount, 1)

        FreeCAD.setActiveTransaction("Rename")
        try:
            varSet.renameProperty("Width", "BoxWidth")
        finally:
            FreeCAD.closeActiveTransaction()
        self.assertEqual(other.RedoCount, 0)
        self.assertEqual(expressionText(otherBox, "Length"), f"{self.doc.Name}#VarSet.BoxWidth")
        other.recompute()
        self.assertAlmostEqual(otherBox.Length.Value, 20)

    def test_rename_changing_object_only_redo_holds(self):
        """fork PR 148 round 2: objects that only another document's redo stack holds (their
        creation undone) use the variable. Under an application transaction, changing one opened
        a transaction there, which cleared that redo stack and freed the object in the middle of
        its change. Now that transaction is opened before the change, and the freed objects are
        skipped. Without the fix this reads freed memory, which crashes only sometimes."""
        varSet = self.addVarSet(Width=20)
        other = FreeCAD.newDocument("VarRenameRedoHeld")
        self.extraDocs.append(other)
        other.UndoMode = 1
        self.tempDir = tempfile.mkdtemp(prefix="TestVariables")
        self.doc.saveAs(os.path.join(self.tempDir, "variables.FCStd"))
        other.saveAs(os.path.join(self.tempDir, "other.FCStd"))
        other.openTransaction("Boxes")
        for i in range(3):
            box = other.addObject("Part::Box", f"Box{i}")
            box.setExpression("Length", f"{self.doc.Name}#VarSet.Width")
        del box
        other.commitTransaction()
        other.undo()
        self.assertEqual(len(other.Objects), 0)
        self.assertEqual(other.RedoCount, 1)

        FreeCAD.setActiveTransaction("Rename")
        try:
            varSet.renameProperty("Width", "BoxWidth")
        finally:
            FreeCAD.closeActiveTransaction()
        self.assertEqual(other.RedoCount, 0)
        self.assertEqual(len(other.Objects), 0)
        self.assertAlmostEqual(varSet.BoxWidth.Value, 20)

    def test_rename_unchanged_object_redo_holds_keeps_redo(self):
        """The same, for an object in the redo stack that doesn't use the variable: nothing
        changes there, so no transaction opens and the redo stack stays. Also the test for the
        `ObjectIdentifier.cpp` crash (fork PR 148): the Box's `Width`, a reference to its own
        property, resolved through its owner's null name while the redo stack held it."""
        varSet = self.addVarSet(Width=20)
        other = FreeCAD.newDocument("VarRenameRedoKept")
        self.extraDocs.append(other)
        other.UndoMode = 1
        other.openTransaction("Box")
        box = other.addObject("Part::Box", "Box")
        box.setExpression("Length", "Width * 2")
        del box
        other.commitTransaction()
        other.undo()
        self.assertEqual(other.RedoCount, 1)

        FreeCAD.setActiveTransaction("Rename")
        try:
            varSet.renameProperty("Width", "BoxWidth")
        finally:
            FreeCAD.closeActiveTransaction()
        self.assertEqual(other.RedoCount, 1)
        other.redo()
        self.assertEqual(expressionText(other.getObject("Box"), "Length"), "Width * 2")

    def test_rename_while_relabeling_keeps_redo_elsewhere(self):
        """ops#181: changes made while a document is relabeled aren't recorded. A rename made then
        (by an observer of the relabel), under an application transaction, changes a deleted Box
        in another document that uses the variable: that document opens no transaction and keeps
        its redo stack, and undoing the delete brings back the Box with the new name."""
        varSet = self.addVarSet(Width=20)
        other = FreeCAD.newDocument("VarRenameRelabel")
        self.extraDocs.append(other)
        other.UndoMode = 1
        self.tempDir = tempfile.mkdtemp(prefix="TestVariables")
        self.doc.saveAs(os.path.join(self.tempDir, "variables.FCStd"))
        other.saveAs(os.path.join(self.tempDir, "other.FCStd"))
        box = other.addObject("Part::Box", "Box")
        box.setExpression("Length", f"{self.doc.Name}#VarSet.Width * 2")
        del box
        other.openTransaction("Delete box")
        other.removeObject("Box")
        other.commitTransaction()
        other.openTransaction("Extra")
        other.addObject("App::FeaturePython", "Extra")
        other.commitTransaction()
        other.undo()
        self.assertEqual((other.UndoCount, other.RedoCount), (1, 1))

        docName = self.doc.Name

        class RenameOnRelabel:
            def slotRelabelDocument(self, doc):
                if doc.Name == docName and "Width" in varSet.PropertiesList:
                    varSet.renameProperty("Width", "BoxWidth")

        observer = RenameOnRelabel()
        FreeCAD.addDocumentObserver(observer)
        FreeCAD.setActiveTransaction("Relabel")
        try:
            self.doc.Label = "Relabeled"
        finally:
            FreeCAD.closeActiveTransaction()
            FreeCAD.removeDocumentObserver(observer)
        self.assertIn("BoxWidth", varSet.PropertiesList)
        self.assertEqual((other.UndoCount, other.RedoCount), (1, 1))
        self.assertEqual(other.UndoNames, ["Delete box"])

        other.undo()
        self.assertEqual(
            expressionText(other.getObject("Box"), "Length"), f"{self.doc.Name}#VarSet.BoxWidth * 2"
        )

    def buildDeletedSheet(self):
        """A VarSet variable used by a Box and a sheet cell (and a cell using that cell), then the
        sheet deleted in a transaction: the undo stack holds it, detached."""
        self.doc.UndoMode = 1
        varSet = self.addVarSet(Width=20)
        target = self.addVarSet("Target")
        box = self.addBox()
        box.setExpression("Length", "#Width * 2")
        sheet = self.addSheet()
        sheet.set("A1", "=#Width")
        sheet.set("A2", "=A1 * 3")
        self.doc.recompute()
        self.doc.openTransaction("Delete sheet")
        self.doc.removeObject("Sheet")
        self.doc.commitTransaction()
        self.assertIsNone(self.doc.getObject("Sheet"))
        return varSet, target, box

    def checkRestoredSheet(self, a1):
        sheet = self.doc.getObject("Sheet")
        self.assertIsNotNone(sheet)
        self.assertEqual(sheet.getContents("A1"), a1)
        self.assertEqual(sheet.getContents("A2"), "=A1 * 3")
        self.doc.recompute()
        self.assertAlmostEqual(sheet.A2.Value, 60)

    def test_rename_after_deleting_sheet_in_transaction(self):
        """fork PR 148 round 2: naming the deleted sheet's cells threw "invalid object", so every
        rename (and move) stopped half way, leaving later containers unrenamed."""
        varSet, _, box = self.buildDeletedSheet()
        self.doc.openTransaction("Rename")
        varSet.renameProperty("Width", "W2")
        self.doc.commitTransaction()
        self.assertEqual(expressionText(box, "Length"), "VarSet.W2 * 2")

        self.doc.undo()
        self.assertEqual(expressionText(box, "Length"), "VarSet.Width * 2")
        self.doc.undo()
        self.checkRestoredSheet("=VarSet.Width")

    def test_rename_and_move_reach_deleted_sheet(self):
        """The same without transactions: the rename and the move reach the deleted sheet's
        cells, so undoing the delete brings back a sheet that uses the new path."""
        varSet, target, box = self.buildDeletedSheet()
        varSet.renameProperty("Width", "W2")
        varSet.moveProperty("W2", target)
        self.assertEqual(expressionText(box, "Length"), "Target.W2 * 2")

        self.doc.undo()
        self.checkRestoredSheet("=Target.W2")
