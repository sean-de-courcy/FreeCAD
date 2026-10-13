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

import ctypes
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


class TestRestoredValues(ExpressionUnitsBase):
    """ops#319 round 2: a value that is out of range but equal to its expression's result, as in
    a file saved before the fix, is still checked: the engine skipped unchanged values."""

    def testRestoredNegativeLength(self):
        import os
        import tempfile

        varSet = self.addVarSet(L=("App::PropertyLength", 10))
        # AllowNegativeValues isn't saved: the file holds -5 mm, as an older build would save it.
        varSet.setPropertyStatus("L", "AllowNegativeValues")
        varSet.setExpression("L", "-5 mm")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.L, FreeCAD.Units.Quantity("-5 mm"))
        path = os.path.join(tempfile.mkdtemp(), "restored_negative_length.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)

        self.doc = FreeCAD.openDocument(path)
        varSet = self.doc.getObject("VarSet")
        self.assertEqual(varSet.L, FreeCAD.Units.Quantity("-5 mm"))
        varSet.touch()
        self.doc.recompute()
        self.assertInvalid(varSet, "below the minimum")


class TestSnappedBound(ExpressionUnitsBase):
    """ops#319 round 2: a value snapped to a bound doesn't count as a change on every evaluation."""

    class Observer:
        def __init__(self):
            self.changes = []

        def slotChangedObject(self, obj, prop):
            self.changes.append((obj.Name, prop))

    def testTwoPiRadiansSetOnce(self):
        varSet = self.addVarSet(Ang=("App::PropertyAngle", 30))
        varSet.setExpression("Ang", "2 * pi * 1 rad")
        self.doc.recompute()
        self.assertEqual(varSet.Ang.Value, 360.0)
        observer = self.Observer()
        FreeCAD.addDocumentObserver(observer)
        try:
            varSet.touch()
            self.doc.recompute()
        finally:
            FreeCAD.removeDocumentObserver(observer)
        self.assertNotIn(("VarSet", "Ang"), observer.changes)
        self.assertTrue(varSet.isValid())


class TestNumberConstraints(ExpressionUnitsBase):
    """ops#319 round 2: Float and Integer constraints and Percent refuse a value outside their
    range, from expressions and from Python (on document objects), instead of storing it as is
    or clamping it."""

    def testPercentByExpression(self):
        varSet = self.addVarSet(P=("App::PropertyPercent", 50))
        varSet.setExpression("P", "150")
        self.doc.recompute()
        self.assertInvalid(varSet, "above the maximum")
        self.assertEqual(varSet.P, 50)
        varSet.setExpression("P", "-5")
        self.doc.recompute()
        self.assertInvalid(varSet, "below the minimum")
        self.assertEqual(varSet.P, 50)
        varSet.setExpression("P", "100")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.P, 100)

    def testPercentByValue(self):
        varSet = self.addVarSet(P=("App::PropertyPercent", 50))
        with self.assertRaises(ValueError):
            varSet.P = 150
        with self.assertRaises(ValueError):
            varSet.P = -1
        self.assertEqual(varSet.P, 50)
        varSet.P = 0
        self.assertEqual(varSet.P, 0)

    def testFloatConstraint(self):
        varSet = self.addVarSet(Ratio=("App::PropertyFloatConstraint", (5.0, 0.0, 10.0, 0.5)))
        with self.assertRaises(ValueError):
            varSet.Ratio = 50.0
        with self.assertRaises(ValueError):
            varSet.Ratio = 11
        self.assertEqual(varSet.Ratio, 5.0)
        varSet.setExpression("Ratio", "50")
        self.doc.recompute()
        self.assertInvalid(varSet, "above the maximum")
        self.assertEqual(varSet.Ratio, 5.0)
        varSet.setExpression("Ratio", "2.5 * 4")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.Ratio, 10.0)

    def testIntegerConstraint(self):
        varSet = self.addVarSet(Count=("App::PropertyIntegerConstraint", (3, 1, 10, 1)))
        varSet.setExpression("Count", "21 / 2")
        self.doc.recompute()
        self.assertInvalid(varSet, "above the maximum")
        self.assertEqual(varSet.Count, 3)
        varSet.setExpression("Count", "19 / 2")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.Count, 10)  # 9.5 rounds to 10, the maximum

    def testNewRangeStillFitsItsValue(self):
        # The tuple form sets a new range; its value is fitted into it, as before.
        varSet = self.addVarSet(Ratio=("App::PropertyFloatConstraint", (5.0, 0.0, 10.0, 0.5)))
        varSet.Ratio = (50.0, 0.0, 20.0, 1.0)
        self.assertEqual(varSet.Ratio, 20.0)


class TestSubPathUnits(ExpressionUnitsBase):
    """ops#319 round 2: Placement, Vector and Sketcher constraint sub-paths dropped a wrong unit
    (`.Placement.Base.x = 30 deg` placed at 30 mm, an Angle constraint of `10 mm` gave 10 deg)."""

    def testPlacementBase(self):
        box = self.addBox()
        box.setExpression(".Placement.Base.x", "30 deg")
        self.doc.recompute()
        self.assertInvalid(box, "Unit mismatch", "Length", "Angle")
        self.assertEqual(box.Placement.Base.x, 0.0)
        box.setExpression(".Placement.Base.x", "2 cm")
        self.doc.recompute()
        self.assertTrue(box.isValid())
        self.assertEqual(box.Placement.Base.x, 20.0)
        box.setExpression(".Placement.Base.x", "7")
        self.doc.recompute()
        self.assertTrue(box.isValid())
        self.assertEqual(box.Placement.Base.x, 7.0)

    def testPlacementAngle(self):
        box = self.addBox()
        box.setExpression(".Placement.Rotation.Angle", "10 mm")
        self.doc.recompute()
        self.assertInvalid(box, "Unit mismatch", "Angle", "Length")
        self.assertAlmostEqual(box.Placement.Rotation.Angle, 0.0, places=12)
        box.setExpression(".Placement.Rotation.Angle", "90 deg")
        self.doc.recompute()
        self.assertTrue(box.isValid())
        self.assertAlmostEqual(box.Placement.Rotation.Angle, 1.5707963267948966, places=12)

    def testVectorDistance(self):
        varSet = self.addVarSet(Offset=("App::PropertyVectorDistance", FreeCAD.Vector(1, 2, 3)))
        varSet.setExpression("Offset.x", "30 deg")
        self.doc.recompute()
        self.assertInvalid(varSet, "Unit mismatch")
        self.assertEqual(varSet.Offset.x, 1.0)
        varSet.setExpression("Offset.x", "1 cm")
        self.doc.recompute()
        self.assertTrue(varSet.isValid())
        self.assertEqual(varSet.Offset, FreeCAD.Vector(10, 2, 3))

    def addSketch(self):
        import Part
        import Sketcher

        sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(10, 0, 0)))
        sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 10, 0)))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, 1, 1))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 10.0))
        sketch.renameConstraint(3, "d")
        sketch.addConstraint(Sketcher.Constraint("Angle", 0, 1, 1.5707963267948966))
        sketch.renameConstraint(4, "a")
        sketch.addConstraint(Sketcher.Constraint("Distance", 1, 10.0))
        self.doc.recompute()
        self.assertTrue(sketch.isValid())
        return sketch

    def testSketchDistance(self):
        sketch = self.addSketch()
        sketch.setExpression("Constraints.d", "30 deg")
        self.doc.recompute()
        self.assertInvalid(sketch, "Unit mismatch", "Length", "Angle")
        self.assertAlmostEqual(sketch.Geometry[0].length(), 10.0, places=9)
        sketch.setExpression("Constraints.d", "3 cm")
        self.doc.recompute()
        self.assertTrue(sketch.isValid())
        self.assertAlmostEqual(sketch.Geometry[0].length(), 30.0, places=9)

    def testSketchAngle(self):
        sketch = self.addSketch()
        sketch.setExpression("Constraints.a", "10 mm")
        self.doc.recompute()
        self.assertInvalid(sketch, "Unit mismatch", "Angle", "Length")
        sketch.setExpression("Constraints.a", "45 deg")
        self.doc.recompute()
        self.assertTrue(sketch.isValid())
        # Line 1 at 45 deg to line 0: its end is at (10 cos 45, 10 sin 45).
        end = sketch.Geometry[1].EndPoint
        self.assertAlmostEqual(end.x, 7.0710678118654755, places=9)
        self.assertAlmostEqual(end.y, 7.0710678118654755, places=9)


class TestRetypedProperties(ExpressionUnitsBase):
    """ops#319 round 2: properties that hold an angle or a length were plain floats, so an
    expression with its unit became an error: Part Revolution Angle, SubShapeBinder Offset."""

    def testRevolutionAngleInDegrees(self):
        import math
        import Part

        varSet = self.addVarSet(Ang=("App::PropertyAngle", 90))
        profile = self.doc.addObject("Part::Feature", "Profile")
        corners = [FreeCAD.Vector(x, 0, z) for x, z in ((10, 0), (20, 0), (20, 10), (10, 10))]
        profile.Shape = Part.Face(Part.makePolygon(corners + corners[:1]))
        revolution = self.doc.addObject("Part::Revolution", "Revolution")
        revolution.Source = profile
        revolution.Axis = FreeCAD.Vector(0, 0, 1)
        revolution.Solid = True
        revolution.setExpression("Angle", "VarSet.Ang")
        self.doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(revolution.Angle, FreeCAD.Units.Quantity("90 deg"))
        # Pappus: area 100 mm^2, centroid at radius 15 mm, a quarter turn.
        self.assertAlmostEqual(revolution.Shape.Volume, 100 * 15 * math.pi / 2, places=6)
        revolution.setExpression("Angle", "10 mm")
        self.doc.recompute()
        self.assertInvalid(revolution, "Unit mismatch")

    def testSubShapeBinderOffsetInMillimetres(self):
        import Part

        source = self.doc.addObject("Part::Feature", "Square")
        corners = [FreeCAD.Vector(x, y, 0) for x, y in ((0, 0), (10, 0), (10, 10), (0, 10))]
        source.Shape = Part.makePolygon(corners + corners[:1])
        binder = self.doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(source, ("Edge1", "Edge2", "Edge3", "Edge4"))]
        binder.MakeFace = True
        binder.setExpression("Offset", "0.2 cm")
        self.doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        self.assertEqual(binder.Offset, FreeCAD.Units.Quantity("2 mm"))
        # A 10 mm square grown by 2 mm with round corners: 100 + 4 * 10 * 2 + pi * 2^2.
        import math

        self.assertAlmostEqual(binder.Shape.Area, 180 + 4 * math.pi, places=4)


class TestLargeIntegers(ExpressionUnitsBase):
    """ops#319 round 4: a Python int or an expression result that doesn't fit a C long (32 bits
    on Windows) was stored as -1 or an unrelated number. It is stored exactly when it fits, and
    refused naming the value when it doesn't."""

    LONG_MAX = 2 ** (8 * ctypes.sizeof(ctypes.c_long) - 1) - 1
    VALUES = (2**31, 2**40, -(2**40))

    def assertSetExactlyOrRefused(self, obj, name, value, errors):
        before = getattr(obj, name)
        if -self.LONG_MAX - 1 <= value <= self.LONG_MAX:
            setattr(obj, name, value)
            self.assertEqual(getattr(obj, name), value)
            setattr(obj, name, before)
            return
        with self.assertRaises(errors) as cm:
            setattr(obj, name, value)
        self.assertIn(str(value), str(cm.exception))
        self.assertEqual(getattr(obj, name), before)

    def testPlainInteger(self):
        varSet = self.addVarSet(Count=("App::PropertyInteger", 3))
        for value in self.VALUES + (2**70, -(2**70)):
            self.assertSetExactlyOrRefused(varSet, "Count", value, OverflowError)
        # No error is left pending: the next calls work
        varSet.Count = 4
        self.assertEqual(varSet.Count, 4)

    def testConstrainedInteger(self):
        # -1 is inside the range: the old conversion's -1 passed the check
        varSet = self.addVarSet(Count=("App::PropertyIntegerConstraint", (3, -5, 5, 1)))
        for value in self.VALUES + (2**70,):
            with self.assertRaises((OverflowError, ValueError)) as cm:
                varSet.Count = value
            self.assertIn(str(value), str(cm.exception))
            self.assertEqual(varSet.Count, 3)
        varSet.Count = -1
        self.assertEqual(varSet.Count, -1)

    def testPercent(self):
        varSet = self.addVarSet(P=("App::PropertyPercent", 50))
        with self.assertRaises((OverflowError, ValueError)) as cm:
            varSet.P = 2**40
        self.assertIn(str(2**40), str(cm.exception))
        self.assertEqual(varSet.P, 50)

    def testFloats(self):
        varSet = self.addVarSet(
            F=("App::PropertyFloat", 1.0),
            Ratio=("App::PropertyFloatConstraint", (0.0, -1.0, 1e15, 1.0)),
        )
        for value in self.VALUES:
            varSet.F = value
            self.assertEqual(varSet.F, float(value))
        varSet.Ratio = 2**40
        self.assertEqual(varSet.Ratio, float(2**40))
        with self.assertRaises(OverflowError):
            varSet.F = 10**400
        self.assertEqual(varSet.F, float(-(2**40)))

    def testIntegerByExpression(self):
        varSet = self.addVarSet(Count=("App::PropertyInteger", 3))
        varSet.setExpression("Count", "2^70")
        self.doc.recompute()
        self.assertInvalid(varSet, "out of range")
        self.assertEqual(varSet.Count, 3)
        varSet.setExpression("Count", "2^40")
        self.doc.recompute()
        if 2**40 <= self.LONG_MAX:
            self.assertTrue(varSet.isValid())
            self.assertEqual(varSet.Count, 2**40)
        else:
            self.assertInvalid(varSet, "out of range")
            self.assertEqual(varSet.Count, 3)


class TestWhitespaceCharacters(ExpressionUnitsBase):
    """ops#320 round 2: characters without a rule that count as whitespace."""

    def testNoBreakSpaces(self):
        varSet = self.addVarSet(Flag=("App::PropertyBool", False))
        self.assertEqual(varSet.evalExpression("1 + 2"), 3)
        self.assertEqual(varSet.evalExpression("1\f+\v2"), 3)
        self.assertEqual(varSet.evalExpression("2 mm"), FreeCAD.Units.Quantity("2 mm"))
