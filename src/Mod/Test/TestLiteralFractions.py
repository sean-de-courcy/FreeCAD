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

"""`3/4 in` is three quarters of an inch (FreeCAD-CH, ops#640, rank 56).

Onshape reads a literal fraction in front of a unit as one quantity. FreeCAD's grammars bound the
unit to the number just before it, so `3/4 in` was 3 / (4 in). Expressions rewrite `N / M unit`
to `(N unit / M)` in front of the lexer (App's rewriteLiteralFractions), and Base's Quantity
parser takes the quotient's value. Every expected value is fixed up front: an inch is 25.4 mm.
"""

import itertools
import math
import os
import tempfile
import unittest

import FreeCAD

INCH = 25.4


def expressionText(obj, prop):
    for path, text in obj.ExpressionEngine:
        if path == prop:
            return text
    return None


class TestLiteralFractions(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestLiteralFractions")
        self.box = self.doc.addObject("Part::Box", "Box")
        self.varSet = self.doc.addObject("App::VarSet", "VarSet")
        self.varSet.addProperty("App::PropertyDistance", "Offset")
        self.doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def length(self, text):
        self.box.setExpression("Length", text)
        self.doc.recompute()
        self.assertNotIn("Invalid", self.box.State, text)
        return self.box.Length.Value

    def test_three_quarters_of_an_inch(self):
        self.assertAlmostEqual(self.length("3/4 in"), 0.75 * INCH, places=9)
        self.assertAlmostEqual(self.length("3/4in"), 0.75 * INCH, places=9)
        self.assertAlmostEqual(self.length("3 / 4 in"), 0.75 * INCH, places=9)

    def test_stored_text_reads_back_the_same(self):
        """The stored text is the rewritten one, `3 in / 4`, which parses to the same value."""
        self.length("3/4 in")
        self.assertEqual(expressionText(self.box, "Length"), "3 in / 4")
        self.box.setExpression("Length", expressionText(self.box, "Length"))
        self.doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 0.75 * INCH, places=9)

    def test_sums_products_and_signs(self):
        self.assertAlmostEqual(self.length("1/2 in + 1/4 in"), 0.75 * INCH, places=9)
        self.assertAlmostEqual(self.length("2 * 3/4 in"), 1.5 * INCH, places=9)
        self.assertAlmostEqual(self.length("10 mm + 1/2 in"), 10 + 0.5 * INCH, places=9)
        self.assertAlmostEqual(self.length("(1/8 in)"), INCH / 8, places=9)
        self.varSet.setExpression("Offset", "-3/4 in")
        self.doc.recompute()
        self.assertAlmostEqual(self.varSet.Offset.Value, -0.75 * INCH, places=9)

    def test_decimals_exponents_and_other_units(self):
        self.assertAlmostEqual(self.length("1.5/2 in"), 0.75 * INCH, places=9)
        self.assertAlmostEqual(self.length("3/4e1 in"), 0.075 * INCH, places=9)
        self.assertAlmostEqual(self.length("1/2 mm"), 0.5, places=9)
        self.assertAlmostEqual(self.length("1/4 ft"), 3 * INCH, places=9)
        self.assertAlmostEqual(self.length('3/4"'), 0.75 * INCH, places=9)

    def test_a_unit_power_stays_with_the_unit(self):
        """`3/4 mm^2` is three quarters of a square millimetre."""
        value = self.box.evalExpression("3/4 mm^2")
        self.assertAlmostEqual(value.Value, 0.75, places=9)
        self.assertEqual(value.Unit, FreeCAD.Units.Quantity("1 mm^2").Unit)

    def test_not_a_literal_fraction(self):
        """After `^`, `/` or a name the fraction isn't one quantity: the grammar's reading stays."""
        value = self.box.evalExpression("2^3/4 mm")  # 2^3 / (4 mm) = 2 / mm
        self.assertAlmostEqual(value.Value, 2.0, places=9)
        self.assertEqual(value.Unit, FreeCAD.Units.Quantity("1/mm").Unit)
        self.box.Width = 8
        value = self.box.evalExpression("Width / 4 mm")  # 8 mm / 4 mm
        self.assertAlmostEqual(float(value), 2.0, places=9)
        # A plain fraction without a unit is a number
        self.assertAlmostEqual(float(self.box.evalExpression("3/4")), 0.75, places=12)

    def test_spreadsheet_cell(self):
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "=3/4 in")
        self.doc.recompute()
        # A cell is read with get(): only aliases become attributes
        self.assertAlmostEqual(
            getattr(sheet.get("A1"), "Value", float("nan")), 0.75 * INCH, places=9
        )

    def test_quantity_parser(self):
        """Base's parser, as Python's Units.Quantity and a property set from a string use it."""
        self.assertAlmostEqual(FreeCAD.Units.Quantity("3/4 in").Value, 0.75 * INCH, places=9)
        self.assertAlmostEqual(FreeCAD.Units.Quantity("1/2 in").Value, 0.5 * INCH, places=9)
        self.assertAlmostEqual(FreeCAD.Units.Quantity("-3/4 in").Value, -0.75 * INCH, places=9)
        self.assertAlmostEqual(FreeCAD.Units.Quantity("1/4 ft").Value, 3 * INCH, places=9)
        self.assertEqual(
            FreeCAD.Units.Quantity("3/4 in").Unit, FreeCAD.Units.Quantity("1 mm").Unit
        )
        self.assertAlmostEqual(FreeCAD.Units.Quantity("3/4").Value, 0.75, places=12)
        self.box.Height = "3/4 in"
        self.assertAlmostEqual(self.box.Height.Value, 0.75 * INCH, places=9)
        # unchanged: no unit after the denominator
        self.assertEqual(FreeCAD.Units.Quantity("1/mm").Unit, FreeCAD.Units.Quantity("1/m").Unit)


def sameValue(a, b):
    """Whether two evaluated expressions are the same quantity (value and unit) or number."""
    Quantity = FreeCAD.Units.Quantity
    if isinstance(a, Quantity) or isinstance(b, Quantity):
        qa = a if isinstance(a, Quantity) else Quantity(float(a))
        qb = b if isinstance(b, Quantity) else Quantity(float(b))
        if qa.Unit != qb.Unit:
            return False
        x, y = qa.Value, qb.Value
    else:
        x, y = float(a), float(b)
    return math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-12)


class TestStoredTextReadsBack(unittest.TestCase):
    """The stored text of an expression means what was typed (ops#652).

    The stored text is the expression printed again, and a file reopened reads it through the
    parser, the fraction rewrite included. `1/(2 mm)` was stored as `1 / 2 mm`, which reads back
    as (1/2) mm; `(3 mm)^2` as `3 mm ^ 2`, which reads as 3 mm²; and `(2 mm^2)^0.5` as text that
    doesn't parse. Every case here goes through a spreadsheet cell, whose contents are that text.
    """

    # Typed forms: a number, a fraction of a unit, quantities, a unit power, a sign
    ATOMS = ["2", "0.5", "3 mm", "4 in", "2 mm^2", "1.5 s", "1e-3", "1/2 in", "-3 mm"]
    OPERATORS = ["+", "-", "*", "/", "%", "^"]

    def setUp(self):
        self.doc = FreeCAD.newDocument("TestStoredTextReadsBack")
        self.sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def evaluated(self, text):
        """The value of @a text, or None where it has none (a unit mismatch, a complex power)."""
        try:
            value = self.sheet.evalExpression(text)
        except Exception:
            return None
        return None if isinstance(value, complex) else value

    def stored(self, text):
        self.sheet.set("A1", "=" + text)
        return self.sheet.getContents("A1")[1:]

    def problems(self, forms):
        """Each form whose stored text doesn't read back as the same value, or prints differently."""
        found = []
        for text in forms:
            typed = self.evaluated(text)
            if typed is None:
                continue
            printed = self.stored(text)
            read = self.evaluated(printed)
            again = self.stored(printed)
            if read is None or not sameValue(typed, read) or again != printed:
                found.append(f"{text!r} stored as {printed!r}: {typed} read back as {read}")
        return found

    def test_quantity_after_a_slash(self):
        self.assertEqual(self.stored("1/(2 mm)"), "1 / (2 mm)")
        self.assertEqual(self.stored("50.8mm * 1/(25.4mm)"), "50.8 mm * 1 / (25.4 mm)")
        # no number before the slash, no rewrite: the text stays as it was
        self.assertEqual(self.stored("A2 / 4 mm"), "A2 / 4 mm")
        self.assertEqual(self.stored("1 mm / 2 mm"), "1 mm / 2 mm")
        # the fraction typed as one stays one
        self.assertEqual(self.stored("3/4 in"), "3 in / 4")
        self.assertEqual(self.problems(["1/(2 mm)", "2 * 2 / (3 mm)", "2 / (1.5 s) * 3 mm"]), [])

    def test_power_of_a_quantity(self):
        self.assertEqual(self.stored("(3 mm)^2"), "(3 mm) ^ 2")
        self.assertEqual(self.stored("(2 mm^2)^0.5"), "(2 (mm ^ 2)) ^ 0.5")
        self.assertEqual(self.stored("(-3 mm)^2"), "(-3 mm) ^ 2")
        # a unit power stays with the unit, and a number's power is unchanged
        self.assertEqual(self.stored("3 mm^2"), "3 (mm ^ 2)")
        self.assertEqual(self.stored("2^3"), "2 ^ 3")
        self.assertEqual(self.problems(["(3 mm)^2", "(2 mm^2)^0.5", "(-3 mm)^2", "-2^2"]), [])

    def test_saved_and_reopened(self):
        """The file, not only the text: a Box and a sheet keep their values across a save."""
        box = self.doc.addObject("Part::Box", "Box")
        box.setExpression("Length", "1/(2 mm) * 10 mm^2")
        box.setExpression("Width", "(3 mm)^2 / 1 mm")
        self.sheet.set("A1", "=1/(2mm)")
        self.sheet.set("A2", "=50.8mm * 1/(25.4mm)")
        self.doc.recompute()
        path = os.path.join(tempfile.mkdtemp(), "StoredTextReadsBack.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        self.doc.recompute()
        box = self.doc.getObject("Box")
        sheet = self.doc.getObject("Sheet")
        self.assertNotIn("Invalid", box.State)
        self.assertAlmostEqual(box.Length.Value, 5.0, places=9)
        self.assertAlmostEqual(box.Width.Value, 9.0, places=9)
        self.assertTrue(sameValue(sheet.get("A1"), FreeCAD.Units.Quantity("0.5 1/mm")))
        self.assertTrue(sameValue(sheet.get("A2"), 2.0))

    def test_generated_pairs(self):
        """Every `(a) op (b)` of the typed forms, and a sign, a unit after `/`, a reciprocal."""
        forms = []
        for a in self.ATOMS:
            forms += [f"-({a})", f"({a}) / mm", f"1 / ({a})", f"({a}) ^ 2", f"({a}) ^ 0.5"]
        forms += [
            f"({a}) {op} ({b})"
            for a, op, b in itertools.product(self.ATOMS, self.OPERATORS, self.ATOMS)
        ]
        self.assertEqual(self.problems(forms), [])

    def test_generated_nesting(self):
        """Two operators deep, both ways round, over a smaller set of forms."""
        atoms = ["2", "3 mm", "2 mm^2", "1/2 in", "-3 mm"]
        forms = []
        for a, op1, b, op2, c in itertools.product(
            atoms, self.OPERATORS, atoms, self.OPERATORS, atoms[:3]
        ):
            forms += [f"(({a}) {op1} ({b})) {op2} ({c})", f"({a}) {op1} (({b}) {op2} ({c}))"]
        self.assertEqual(self.problems(forms), [])


if __name__ == "__main__":
    unittest.main()
