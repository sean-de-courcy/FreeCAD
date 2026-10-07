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
        with self.assertRaises(Exception) as cm:
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
        # `Doc#Obj.Prop`, `<<Doc>>#Obj.Prop`, `Doc # Obj.Prop` and `<<a#b>>` aren't rewritten:
        # nothing here is named `Obj` or `b`, so a rewrite would raise `no variable named ...`.
        other = FreeCAD.newDocument("VarOther")
        self.extraDocs.append(other)
        obj = other.addObject("App::VarSet", "Obj")
        obj.addProperty("App::PropertyLength", "Prop")
        obj.Prop = 12
        labelled = self.doc.addObject("App::VarSet", "Labelled")
        labelled.Label = "a#b"
        labelled.addProperty("App::PropertyLength", "Size")
        labelled.Size = 9
        for expr, value in [
            (f"{other.Name}#Obj.Prop", 12),
            (f"<<{other.Name}>>#Obj.Prop", 12),
            (f"{other.Name} # Obj.Prop", 12),
            ("<<a#b>>.Size", 9),
        ]:
            with self.subTest(expr=expr):
                self.assertAlmostEqual(float(self.box.evalExpression(expr)), value)


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
        self.doc.recompute()
        self.assertParserError(
            lambda: box.setExpression("Length", "#Nope"), "no variable named Nope"
        )
        self.doc.recompute()
        self.assertAlmostEqual(box.Length.Value, 17)
        self.assertIsNone(expressionText(box, "Length"))

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

        The uses helper's exact oracle ({Box.Length, Sheet.B1}) is PR 2's (ops#152 section 7).
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
        """T8. A rename reaches `#`-written expressions, other documents too.

        Without a transaction (ops#177, see test_rename_sheet_cell); the undo half is checked with
        ops#177's fix.
        """
        varSet = self.addVarSet(Width=20)
        box = self.addBox()
        box.setExpression("Length", "#Width * 2")
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

        varSet.renameProperty("Width", "BoxWidth")
        self.doc.recompute()
        self.assertEqual(expressionText(box, "Length"), "VarSet.BoxWidth * 2")
        self.assertEqual(expressionText(otherBox, "Length"), f"{self.doc.Name}#VarSet.BoxWidth")
        self.assertAlmostEqual(box.Length.Value, 40)

    def test_rename_sheet_cell(self):
        """T8. A rename reaches a sheet cell.

        Without a transaction: under one, the rename raises TypeError in stock code (ops#177), on
        some platforms even with the sheet alone. The undo half is checked with ops#177's fix.
        """
        varSet = self.addVarSet(Width=20)
        sheet = self.addSheet()
        sheet.set("B1", "=#Width")
        self.doc.recompute()
        self.assertEqual(sheet.getContents("B1"), "=VarSet.Width")

        varSet.renameProperty("Width", "BoxWidth")
        self.doc.recompute()
        self.assertEqual(sheet.getContents("B1"), "=VarSet.BoxWidth")
        self.assertAlmostEqual(sheet.B1.Value, 20)
