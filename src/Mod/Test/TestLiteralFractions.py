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


if __name__ == "__main__":
    unittest.main()
