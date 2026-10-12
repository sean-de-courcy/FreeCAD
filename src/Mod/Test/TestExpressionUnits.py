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

"""Silent wrong values in expressions (FreeCAD-CH, ops#319 and ops#320).

ops#319: an expression's unit replaced a quantity property's unit unchecked (a Box Length of
`30 deg` built a 30 mm box), values outside a property's constraints were clamped silently or
not checked at all, and a number property dropped a unit. ops#320: the lexer dropped characters
it doesn't know (`!true` was `true`). Every model here is built by the test, and every expected
value is fixed up front.
"""

import unittest

import FreeCAD


class ExpressionUnitsBase(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestExpressionUnits")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def addVarSet(self, **props):
        """A VarSet with one property per keyword: name=(type, value)."""
        varSet = self.doc.addObject("App::VarSet", "VarSet")
        for name, (typ, value) in props.items():
            varSet.addProperty(typ, name)
            setattr(varSet, name, value)
        return varSet

    def addBox(self):
        box = self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        self.assertAlmostEqual(box.Shape.Volume, 1000.0, places=6)
        return box

    def assertInvalid(self, obj, *words):
        self.assertFalse(obj.isValid(), f"{obj.Name} should be invalid")
        status = obj.getStatusString()
        for word in words:
            self.assertIn(word, status)


class TestQuantityUnits(ExpressionUnitsBase):
    """ops#319: a typed quantity property keeps its unit."""

    def testAngleOnLengthIsAnError(self):
        varSet = self.addVarSet(L=("App::PropertyLength", 10))
        varSet.setExpression("L", "30 deg")
        self.doc.recompute()
        self.assertInvalid(varSet, "Unit mismatch", "Length", "Angle")
        self.assertEqual(varSet.L, FreeCAD.Units.Quantity("10 mm"))

    def testBoxLengthFromAngleVariable(self):
        varSet = self.addVarSet(Ang=("App::PropertyAngle", 30))
        box = self.addBox()
        box.setExpression("Length", "VarSet.Ang")
        self.doc.recompute()
        self.assertInvalid(box, "Unit mismatch")
        self.assertEqual(box.Length, FreeCAD.Units.Quantity("10 mm"))
        self.assertAlmostEqual(box.Shape.Volume, 1000.0, places=6)

    def testUnitlessResultTakesThePropertyUnit(self):
        box = self.addBox()
        box.setExpression("Length", "3")
        self.doc.recompute()
        self.assertTrue(box.isValid())
        self.assertEqual(box.Length, FreeCAD.Units.Quantity("3 mm"))
        self.assertAlmostEqual(box.Shape.Volume, 300.0, places=6)

    def testUnitlessAfterAWrongUnitStaysMillimetres(self):
        # Before the fix, `30 deg` turned the Length into degrees, and `3` then gave 3 deg.
        box = self.addBox()
        box.setExpression("Length", "30 deg")
        self.doc.recompute()
        box.setExpression("Length", "3")
        self.doc.recompute()
        self.assertTrue(box.isValid())
        self.assertEqual(box.Length, FreeCAD.Units.Quantity("3 mm"))

    def testMatchingUnitConverts(self):
        box = self.addBox()
        box.setExpression("Length", "2 cm")
        self.doc.recompute()
        self.assertTrue(box.isValid())
        self.assertAlmostEqual(box.Shape.Volume, 2000.0, places=6)

    def testInverseLengthIsAnError(self):
        # `3/4in` parses as 3 / (4 in), an inverse length.
        box = self.addBox()
        box.setExpression("Length", "3/4in")
        self.doc.recompute()
        self.assertInvalid(box, "Unit mismatch")
        box.setExpression("Length", "3/4 * 1 in")
        self.doc.recompute()
        self.assertTrue(box.isValid())
        self.assertAlmostEqual(box.Length.Value, 19.05, places=9)

    def testRetypedVariable(self):
        varSet = self.addVarSet(D=("App::PropertyDistance", 60))
        box = self.addBox()
        box.setExpression("Length", "VarSet.D")
        self.doc.recompute()
        self.assertAlmostEqual(box.Shape.Volume, 6000.0, places=6)
        varSet.removeProperty("D")
        varSet.addProperty("App::PropertyAngle", "D")
        varSet.D = 60
        varSet.touch()
        self.doc.recompute()
        self.assertInvalid(box, "Unit mismatch")
        self.assertAlmostEqual(box.Shape.Volume, 6000.0, places=6)

    def testPlainQuantityTakesAnyUnit(self):
        varSet = self.addVarSet(Q=("App::PropertyQuantity", 0))
        varSet.setExpression("Q", "30 deg")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.Q, FreeCAD.Units.Quantity("30 deg"))
        varSet.setExpression("Q", "5 mm")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.Q, FreeCAD.Units.Quantity("5 mm"))

    def testPadLengthFromAngle(self):
        import Part

        body = self.doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        corners = [FreeCAD.Vector(x, y, 0) for x, y in ((0, 0), (10, 0), (10, 10), (0, 10))]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 5
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 500.0, places=6)
        pad.setExpression("Length", "30 deg")
        self.doc.recompute()
        self.assertInvalid(pad, "Unit mismatch")
        self.assertEqual(pad.Length, FreeCAD.Units.Quantity("5 mm"))
        # A failed PartDesign feature may drop its shape; it must not be a 30 mm pad.
        if not pad.Shape.isNull():
            self.assertAlmostEqual(pad.Shape.Volume, 500.0, places=6)


class TestQuantityRange(ExpressionUnitsBase):
    """ops#319: a value outside a property's constraints is refused, not clamped or kept."""

    def testNegativeLengthByExpression(self):
        varSet = self.addVarSet(L=("App::PropertyLength", 10))
        varSet.setExpression("L", "-5 mm")
        self.doc.recompute()
        self.assertInvalid(varSet, "below the minimum")
        self.assertEqual(varSet.L, FreeCAD.Units.Quantity("10 mm"))

    def testNegativeLengthByValue(self):
        varSet = self.addVarSet(L=("App::PropertyLength", 10))
        with self.assertRaises(ValueError):
            varSet.L = -5
        with self.assertRaises(ValueError):
            varSet.L = "-5 mm"
        self.assertEqual(varSet.L, FreeCAD.Units.Quantity("10 mm"))

    def testAngleAboveRange(self):
        varSet = self.addVarSet(Ang=("App::PropertyAngle", 30))
        with self.assertRaises(ValueError):
            varSet.Ang = 400
        self.assertEqual(varSet.Ang, FreeCAD.Units.Quantity("30 deg"))
        varSet.setExpression("Ang", "400 deg")
        self.doc.recompute()
        self.assertInvalid(varSet, "above the maximum")

    def testRoundingAtTheBoundCounts(self):
        # 2*pi rad converts to 360 deg up to rounding: that is the bound, not past it.
        varSet = self.addVarSet(Ang=("App::PropertyAngle", 30))
        varSet.setExpression("Ang", "2 * pi * 1 rad")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertAlmostEqual(varSet.Ang.Value, 360.0, places=9)
        self.assertLessEqual(varSet.Ang.Value, 360.0)

    def testInRangeValuesUnchanged(self):
        varSet = self.addVarSet(Ang=("App::PropertyAngle", 30), L=("App::PropertyLength", 1))
        varSet.Ang = -360
        varSet.L = 0
        varSet.setExpression("Ang", "-90 deg")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.Ang, FreeCAD.Units.Quantity("-90 deg"))
        self.assertEqual(varSet.L, FreeCAD.Units.Quantity("0 mm"))


class TestNumberProperties(ExpressionUnitsBase):
    """ops#319: a Float, Integer or Bool refuses a value with a unit instead of dropping it."""

    def testFloat(self):
        varSet = self.addVarSet(Factor=("App::PropertyFloat", 1.5))
        varSet.setExpression("Factor", "3 mm")
        self.doc.recompute()
        self.assertInvalid(varSet, "Unit mismatch", "Factor")
        self.assertEqual(varSet.Factor, 1.5)
        varSet.setExpression("Factor", "3 mm / 1 mm")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.Factor, 3.0)

    def testInteger(self):
        varSet = self.addVarSet(Count=("App::PropertyInteger", 1))
        varSet.setExpression("Count", "30 deg")
        self.doc.recompute()
        self.assertInvalid(varSet, "Unit mismatch", "Count")
        self.assertEqual(varSet.Count, 1)
        # A number without a unit still rounds, as before (decided in ops#319).
        varSet.setExpression("Count", "5 / 2")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.Count, 3)

    def testBool(self):
        varSet = self.addVarSet(Flag=("App::PropertyBool", False))
        varSet.setExpression("Flag", "1 mm")
        self.doc.recompute()
        self.assertInvalid(varSet, "Unit mismatch", "Flag")
        self.assertFalse(varSet.Flag)
        varSet.setExpression("Flag", "1 == 1")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertTrue(varSet.Flag)


class TestUnknownCharacters(ExpressionUnitsBase):
    """ops#320: a character the lexer doesn't know is a parse error, not dropped."""

    def setUp(self):
        super().setUp()
        self.varSet = self.addVarSet(Flag=("App::PropertyBool", False))

    def assertRefused(self, text, char):
        with self.assertRaises(FreeCAD.Base.ParserError) as cm:
            self.varSet.evalExpression(text)
        self.assertIn(f"'{char}'", str(cm.exception))

    def testRefused(self):
        self.assertRefused("!true", "!")
        self.assertRefused("1 & 2", "&")
        self.assertRefused("$a", "$")
        self.assertRefused("1 €", "€")

    def testSetExpressionRefused(self):
        with self.assertRaises(FreeCAD.Base.ParserError):
            self.varSet.setExpression("Flag", "!true")
        self.assertEqual(list(self.varSet.ExpressionEngine), [])

    def testStillParsed(self):
        self.assertTrue(self.varSet.evalExpression("1 != 2"))
        self.assertFalse(self.varSet.evalExpression("1 != 1"))
        self.assertEqual(self.varSet.evalExpression("<<a!b&c$d>>"), "a!b&c$d")
        self.assertEqual(self.varSet.evalExpression("1 +\r\n 2"), 3)

    def testCellAddresses(self):
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "5")
        sheet.set("B1", "=$A$1 * 2")
        sheet.set("B2", "=A$1 + 1")
        sheet.set("B3", "=$A1 + 2")
        self.doc.recompute()
        self.assertEqual(sheet.get("B1"), 10)
        self.assertEqual(sheet.get("B2"), 6)
        self.assertEqual(sheet.get("B3"), 7)
