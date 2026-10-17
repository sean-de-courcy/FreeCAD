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

"""The Onshape translator, freecad.variables.onshape (FreeCAD-CH, ops#317 PR D).

notes/variables-studio.md section 6, "Translator". Every variable and export here is made up, in
the structure of an Onshape variable studio export (section 0). Expected values are worked out by
hand from the made-up inputs (1 in = 25.4 mm); the last class checks that FreeCAD computes the
written text to the translator's own value.
"""

import json
import math
import unittest

from freecad.variables import onshape
from freecad.variables.onshape import ANGLE, LENGTH, NONE, Binding, Quantity, Refused

# The made-up variables the expressions refer to: name -> (FreeCAD text, value).
WIDTH = Quantity(0.010, LENGTH)  # 10 mm
RAIL = Quantity(4 * 0.0254, LENGTH)  # 4 in
COUNT = Quantity(3.0)
REFS = {"Width": ("Width", WIDTH), "Rail": ("Rail", RAIL), "Count": ("Count", COUNT)}


def resolve(name):
    if name not in REFS:
        raise Refused(f"#{name} isn't defined")
    return REFS[name]


def translate(text, kind="LENGTH", default_units=None):
    return onshape.translate(text, kind, resolve, default_units)


# (Onshape text, type, value by hand in mm, deg or plain, FreeCAD text or None)
ACCEPTED = [
    ("10mm", "LENGTH", 10, "(10 * 1 mm)"),
    ("10 mm", "LENGTH", 10, "(10 * 1 mm)"),
    ("3/4in", "LENGTH", 19.05, "(3 / 4 * 1 in)"),
    ("3/4 in", "LENGTH", 19.05, "(3 / 4 * 1 in)"),
    ("(3/4) in", "LENGTH", 19.05, "((3 / 4) * 1 in)"),
    ("-3/4 in", "LENGTH", -19.05, "(-3 / 4 * 1 in)"),
    ("2in+3/4in", "LENGTH", 69.85, "(2 * 1 in) + (3 / 4 * 1 in)"),
    ("1 inch + 2 inches", "LENGTH", 76.2, "(1 * 1 in) + (2 * 1 in)"),
    ("1 foot - 6 in", "LENGTH", 152.4, None),
    ("sqrt(16) m", "LENGTH", 4000, "(sqrt(16) * 1 m)"),
    ("#Width/2", "LENGTH", 5, "Width / 2"),
    ("#Width + 3/4 in - 2 mm", "LENGTH", 27.05, None),
    ("(#Width + 3/4 in) * #Count", "LENGTH", (10 + 19.05) * 3, None),
    ("cos(60)", "NUMBER", 0.5, "cos(60)"),
    ("2 * cos(60 deg) * 1 in", "LENGTH", 25.4, None),
    ("atan2(1, 1)", "ANGLE", 45, "atan2(1, 1)"),
    ("90 deg - atan(1)", "ANGLE", 45, None),
    ("#Rail > 3 in ? 1 mm : 2 mm", "LENGTH", 1, "(Rail > (3 * 1 in)) ? (1 * 1 mm) : (2 * 1 mm)"),
    ("#Rail < 3 in ? 1 mm : 2 mm", "LENGTH", 2, None),
    ("#Count != 4 ? 1 mm : 2 mm", "LENGTH", 1, None),
    ("1.1 in == 27.95 mm ? 1 mm : 2 mm", "LENGTH", 2, None),
    ("PI * 2 mm", "LENGTH", 2 * math.pi, "pi * (2 * 1 mm)"),
    ("Pi * 2 mm", "LENGTH", 2 * math.pi, None),
    ("max(#Width, 1 cm, 3/4 in)", "LENGTH", 19.05, None),
    ("abs(-2 mm)", "LENGTH", 2, None),
    ("sqrt(#Width * #Width)", "LENGTH", 10, None),
    ("(2 mm)^2 / 1 mm", "LENGTH", 4, None),
    ("2^3 * 1 mm", "LENGTH", 8, None),
    ("7 % 4", "NUMBER", 3, None),
    ("floor(2.5) * 1 mm", "LENGTH", 2, None),
    (".5 mm", "LENGTH", 0.5, "(0.5 * 1 mm)"),
    ("#Count * 2", "NUMBER", 6, "Count * 2"),
    ("1.5 rad", "ANGLE", math.degrees(1.5), None),
]

# (Onshape text, type, a fragment of the reason)
REFUSED = [
    ("#Width && #Rail", "LENGTH", "no && (and)"),
    ("#Width || #Rail", "LENGTH", "no || (or)"),
    ("!x", "NUMBER", "no ! (not)"),
    ("[1,2][0]", "NUMBER", "arrays"),
    ('"text"', "NUMBER", "strings"),
    ("round(2.5)", "NUMBER", "round()"),
    ("asinh(1)", "NUMBER", "asinh"),
    ("5 furlong", "LENGTH", "unknown unit 'furlong'"),
    ("foo + 1", "NUMBER", "unknown name 'foo'"),
    ("#Width + 2", "LENGTH", "bare number"),
    ("", "LENGTH", "empty"),
    ("5", "LENGTH", "default unit"),
    ("#Count * 2", "LENGTH", "default unit"),
    ("#Width*3/4 in", "LENGTH", "next to *, / or ^"),
    ("1/3/4 in", "LENGTH", "next to *, / or ^"),
    ("3/4 in * 2", "LENGTH", "next to *, / or ^"),
    ("1.5/2 in", "LENGTH", "fraction of decimals"),
    ("-2^2", "NUMBER", "minus before ^"),
    ("2^3^2", "NUMBER", "chained ^"),
    ("0^-1", "NUMBER", "can't be computed"),
    ("(0 mm)^-1", "NUMBER", "can't be computed"),
    ("10^400", "NUMBER", "can't be computed"),
    ("exp(1000)", "NUMBER", "can't be computed"),
    ("cosh(1000)", "NUMBER", "can't be computed"),
    ("10^300 * 10^300 > 1 ? 1 : 2", "NUMBER", "can't be computed"),
    ("1.1 in == 27.94 mm ? 1 mm : 2 mm", "LENGTH", "equal within rounding"),
    ("1.1 in > 27.94 mm ? 1 mm : 2 mm", "LENGTH", "equal within rounding"),
    ("#Width <= 10 mm ? 1 mm : 2 mm", "LENGTH", "equal within rounding"),
    ("#Count != 3 ? 1 mm : 2 mm", "LENGTH", "equal within rounding"),
    ("٣ mm", "LENGTH", "unexpected character"),  # an Arabic-Indic 3
    ("1٣ mm", "LENGTH", "unexpected character"),
    ("2 mm^2 / 1 mm", "LENGTH", "a unit before ^"),
    ("sqrt(4) mm^2 / 1 mm", "LENGTH", "a unit before ^"),
    ("#Width/2 in", "LENGTH", "units cancel"),
    ("3in*3in", "LENGTH", "length^2"),
    ("10 mm", "ANGLE", "is a length, but the variable is an angle"),
    ("7 mm % 4 mm", "LENGTH", "% with units"),
    ("-7 % 4", "NUMBER", "% of a negative"),
    ("floor(2.5 mm)", "LENGTH", "floor()"),
    ("1e3 * 1 mm", "LENGTH", "exponent notation"),
    ("#Width in", "LENGTH", "a unit after #Width"),
    ("10 mm mm", "LENGTH", "two units"),
    ("mm", "LENGTH", "needs a number"),
    ("#Nope", "LENGTH", "#Nope isn't defined"),
    ("1 < 2 < 3", "NUMBER", "chained comparisons"),
    ("1 mm > 2 ? 1 : 2", "NUMBER", "bare number"),
    ("sin(1 mm)", "NUMBER", "sin() of a length"),
    ("1 mm", "ANY", "Any variables aren't supported yet"),
    ("1 mm", "Length", "unknown variable type"),
    ("1 = 1", "NUMBER", "= isn't an operator"),
    ("max(1;2)", "NUMBER", "; isn't allowed"),
]


def in_display_units(q):
    """mm for a length, degrees for an angle, the plain number otherwise."""
    if q.dims == LENGTH:
        return q.to("mm")
    if q.dims == ANGLE:
        return q.to("deg")
    return q.value


class TestTranslation(unittest.TestCase):
    def test_accepted_forms(self):
        for text, kind, expected, freecad in ACCEPTED:
            with self.subTest(text=text):
                result = translate(text, kind)
                self.assertAlmostEqual(in_display_units(result.value), expected, places=9)
                if freecad is not None:
                    self.assertEqual(result.text, freecad)

    def test_property_types(self):
        self.assertEqual(translate("1 mm").property_type, "App::PropertyDistance")
        self.assertEqual(translate("1 deg", "ANGLE").property_type, "App::PropertyAngle")
        self.assertEqual(translate("1", "NUMBER").property_type, "App::PropertyFloat")

    def test_refused_forms_say_why(self):
        for text, kind, fragment in REFUSED:
            with self.subTest(text=text):
                with self.assertRaises(Refused) as cm:
                    translate(text, kind)
                self.assertIn(fragment, str(cm.exception))

    def test_default_unit_becomes_explicit(self):
        inches = {"LENGTH": "in", "ANGLE": "deg"}
        result = translate("5", "LENGTH", inches)
        self.assertAlmostEqual(result.value.to("mm"), 127, places=9)
        self.assertEqual(result.text, "5 * 1 in")
        result = translate("#Count * 2", "LENGTH", inches)
        self.assertAlmostEqual(result.value.to("mm"), 6 * 25.4, places=9)
        self.assertEqual(result.text, "(Count * 2) * 1 in")
        self.assertAlmostEqual(translate("30", "ANGLE", inches).value.to("deg"), 30, places=9)
        # units that cancel aren't "no unit": the default doesn't apply
        with self.assertRaises(Refused):
            translate("#Width/2 in", "LENGTH", inches)

    def test_text_never_holds_what_freecad_misreads(self):
        for text, kind, _expected, _freecad in ACCEPTED:
            written = translate(text, kind).text
            for bad in ("#", "&&", "||"):
                self.assertNotIn(bad, written, text)
            self.assertNotRegex(written, "!(?!=)", text)  # != is FreeCAD's too

    def test_references_are_written_as_the_caller_says(self):
        result = onshape.translate("#Gap * 2", "LENGTH",
                                   lambda name: ("Variables.Gap", Quantity(0.007, LENGTH)))
        self.assertEqual(result.text, "Variables.Gap * 2")
        self.assertAlmostEqual(result.value.to("mm"), 14, places=9)


def export(*entries):
    """JSON text of an export: each entry a list of (type, name, expression[, description])."""
    data = []
    for variables in entries:
        data.append({
            "variableStudioReference": None,
            "variables": [
                {"type": v[0], "name": v[1], "value": None,
                 "description": v[3] if len(v) > 3 else "", "expression": v[2]}
                for v in variables
            ],
        })
    return json.dumps(data)


class TestExport(unittest.TestCase):
    def test_reads_the_structure(self):
        entries = onshape.parse_export(export(
            [("LENGTH", "Width", "10 mm", "the width"), ("ANGLE", "Tilt", "5 deg")]))
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0].reference)
        self.assertEqual([v.name for v in entries[0].variables], ["Width", "Tilt"])
        self.assertEqual(entries[0].variables[0].description, "the width")

    def test_refuses_other_structures(self):
        cases = [
            ("{}", "JSON array"),
            ("[{}]", "no list of variables"),
            ('[{"variables": [{"type": "LENGTH", "name": "A"}]}]', "exactly the keys"),
            ('[{"variables": [{"type": "LENGTH", "name": "1A", "value": null, '
             '"description": "", "expression": "1 mm"}]}]', "isn't a variable name"),
            ("not json", "not JSON"),
        ]
        for text, fragment in cases:
            with self.subTest(text=text):
                with self.assertRaises(onshape.ExportError) as cm:
                    onshape.parse_export(text)
                self.assertIn(fragment, str(cm.exception))

    def test_translates_in_dependency_order(self):
        entries = onshape.parse_export(export([
            ("LENGTH", "Total", "#Width + #Gap"),  # uses later variables
            ("LENGTH", "Width", "3/4 in"),
            ("LENGTH", "Gap", "#Width / 2"),
            ("NUMBER", "Ratio", "#Gap / #Width"),
            ("ANGLE", "Tilt", "atan2(#Gap, #Width)"),
        ]))
        result = onshape.translate_export(entries)
        self.assertEqual(result.unresolved, {})
        total = result.result("Total")
        self.assertEqual(total.translation.text, "Width + Gap")
        self.assertAlmostEqual(total.translation.value.to("mm"), 19.05 * 1.5, places=9)
        self.assertAlmostEqual(result.result("Ratio").translation.value.value, 0.5, places=12)
        self.assertAlmostEqual(result.result("Tilt").translation.value.to("deg"),
                               math.degrees(math.atan(0.5)), places=9)

    def test_names_nothing_defines_are_listed_not_guessed(self):
        entries = onshape.parse_export(export([
            ("LENGTH", "Width2", "#Gap * 2"),
            ("LENGTH", "Rail", "#Width2 + 1 mm"),
            ("LENGTH", "Free", "5 mm"),
        ]))
        result = onshape.translate_export(entries)
        self.assertEqual(result.unresolved, {"Gap": ["Width2"]})
        self.assertEqual(result.result("Width2").needs, ["Gap"])
        self.assertEqual(result.result("Rail").needs, ["Gap"])
        self.assertIsNone(result.result("Rail").translation)
        self.assertIsNotNone(result.result("Free").translation)
        # a binding chosen for it: a document variable's path
        bound = onshape.translate_export(
            entries, bindings={"Gap": Binding("Variables.Gap", Quantity(0.007, LENGTH))})
        self.assertEqual(bound.result("Width2").translation.text, "Variables.Gap * 2")
        self.assertAlmostEqual(bound.result("Rail").translation.value.to("mm"), 15, places=9)

    def test_several_exports_resolve_each_other(self):
        a = onshape.parse_export(export([("LENGTH", "Width2", "#Gap * 2")]))
        b = onshape.parse_export(export([("LENGTH", "Gap", "7 mm")]))
        result = onshape.translate_export(a + b, containers=["StudioA", "StudioB"])
        self.assertEqual(result.unresolved, {})
        self.assertEqual(result.result("Width2").translation.text, "StudioB.Gap * 2")
        self.assertAlmostEqual(result.result("Width2").translation.value.to("mm"), 14, places=9)

    def test_a_name_two_exports_define_needs_a_provider(self):
        a = onshape.parse_export(export([("LENGTH", "Gap", "7 mm"), ("LENGTH", "W", "#Gap")]))
        b = onshape.parse_export(export([("LENGTH", "Gap", "9 mm")]))
        c = onshape.parse_export(export([("LENGTH", "Use", "#Gap * 2")]))
        result = onshape.translate_export(a + b + c)
        self.assertEqual(result.ambiguous, {"Gap": [0, 1]})
        self.assertEqual(result.unresolved, {})  # defined, only not yet chosen
        self.assertEqual(result.result("Use").needs, ["Gap"])
        # a binding doesn't pick between two definitions: only a provider does
        bound = onshape.translate_export(
            a + b + c, bindings={"Gap": Binding("Variables.Gap", Quantity(0.007, LENGTH))})
        self.assertEqual(bound.ambiguous, {"Gap": [0, 1]})
        self.assertEqual(bound.result("Use").needs, ["Gap"])
        self.assertIsNone(bound.result("Use").translation)
        # a sibling definition is the one its own entry means
        self.assertAlmostEqual(result.result("W").translation.value.to("mm"), 7, places=9)
        chosen = onshape.translate_export(a + b + c, providers={"Gap": 1})
        self.assertEqual(chosen.ambiguous, {})
        self.assertEqual(chosen.result("Use").translation.text, "Studio2.Gap * 2")

    def test_cycles_and_duplicates_are_refused(self):
        entries = onshape.parse_export(export([
            ("LENGTH", "A", "#B + 1 mm"),
            ("LENGTH", "B", "#A + 1 mm"),
            ("LENGTH", "C", "1 mm"),
            ("LENGTH", "C", "2 mm"),
        ]))
        result = onshape.translate_export(entries)
        self.assertIn("refers to itself", result.result("B").refusal + result.result("A").refusal)
        self.assertIsNone(result.result("A").translation)
        self.assertIn("defined twice", result.result("C").refusal)

    def test_renamed_variables(self):
        entries = onshape.parse_export(export([("LENGTH", "t", "2 mm"),
                                               ("LENGTH", "Wall", "#t * 3")]))
        result = onshape.translate_export(entries, name_map={"t": "t_"})
        self.assertEqual(result.result("t").freecad_name, "t_")
        self.assertEqual(result.result("Wall").translation.text, "t_ * 3")

    def test_refusals_and_empty_expressions_are_per_variable(self):
        entries = onshape.parse_export(export([
            ("LENGTH", "Empty", ""),
            ("LENGTH", "Bad", "#Empty && 1"),
            ("LENGTH", "Uses", "#Empty * 2"),
            ("ANY", "Thing", "1 mm"),
        ]))
        result = onshape.translate_export(entries)
        self.assertIn("empty", result.result("Empty").refusal)
        self.assertIn("&&", result.result("Bad").refusal)
        self.assertIn("#Empty isn't translated", result.result("Uses").refusal)
        self.assertIn("Any variables", result.result("Thing").refusal)

    def test_an_exported_value_must_agree(self):
        data = json.loads(export([("LENGTH", "A", "3/4 in"), ("LENGTH", "B", "1 in")]))
        data[0]["variables"][0]["value"] = "19.05 mm"
        data[0]["variables"][1]["value"] = "20 mm"
        result = onshape.translate_export(onshape.parse_export(json.dumps(data)))
        self.assertIsNotNone(result.result("A").translation)
        self.assertIn("disagrees", result.result("B").refusal)

    def test_a_value_that_cant_be_computed_refuses_only_its_variable(self):
        data = json.loads(export([("NUMBER", "Huge", "10^400"), ("LENGTH", "A", "1 in"),
                                  ("LENGTH", "B", "2 in"), ("LENGTH", "C", "3 in")]))
        data[0]["variables"][2]["value"] = "0^-1"
        data[0]["variables"][3]["value"] = 1e400  # JSON reads it as infinity
        result = onshape.translate_export(onshape.parse_export(json.dumps(data)))
        self.assertIn("can't be computed", result.result("Huge").refusal)
        self.assertIsNotNone(result.result("A").translation)
        # an exported value that can't be read is no value, as before
        self.assertIsNotNone(result.result("B").translation)
        self.assertIsNotNone(result.result("C").translation)


try:
    import FreeCAD
except ImportError:  # the translator's own tests run without FreeCAD too
    FreeCAD = None


@unittest.skipIf(FreeCAD is None, "needs FreeCAD")
class TestFreeCADAgrees(unittest.TestCase):
    """The written text computes in FreeCAD to the translator's own value and unit (section
    2.5's check, here over the whole table). The text is evaluated, not read back from a
    property: a Distance turns a unitless result into millimetres and a Float drops a unit
    (section 2.3)."""

    def setUp(self):
        self.doc = FreeCAD.newDocument("TestVariablesOnshape")
        self.varSet = self.doc.addObject("App::VarSet", "VarSet")
        self.varSet.addProperty("App::PropertyDistance", "Width")
        self.varSet.Width = "10 mm"
        self.varSet.addProperty("App::PropertyDistance", "Rail")
        self.varSet.Rail = "4 in"
        self.varSet.addProperty("App::PropertyFloat", "Count")
        self.varSet.Count = 3

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def freecad_value(self, text):
        """FreeCAD's value of @a text with the VarSet as owner, in SI units with its dimensions."""
        value = self.varSet.evalExpression(text)
        if not isinstance(value, FreeCAD.Units.Quantity):
            return Quantity(float(value))
        if value.Unit == FreeCAD.Units.Length:
            return Quantity(value.Value / 1000, LENGTH)  # mm
        if value.Unit == FreeCAD.Units.Angle:
            return Quantity(math.radians(value.Value), ANGLE)  # deg
        if value.Unit == FreeCAD.Units.Unit():
            return Quantity(value.Value)
        self.fail(f"{text}: FreeCAD gives the unit {value.Unit}")

    def test_the_oracle_sees_units(self):
        self.assertEqual(self.freecad_value("2").dims, NONE)
        self.assertEqual(self.freecad_value("Width / (1 mm)").dims, NONE)
        self.assertEqual(self.freecad_value("Count * (1 mm)").dims, LENGTH)
        self.assertEqual(self.freecad_value("atan2(1, 1)").dims, ANGLE)
        self.assertAlmostEqual(self.freecad_value("Rail").value, 0.1016, places=12)

    def test_freecad_computes_the_same_value(self):
        for i, (text, kind, _expected, _freecad) in enumerate(ACCEPTED):
            with self.subTest(text=text):
                result = translate(text, kind)
                actual = self.freecad_value(result.text)
                self.assertEqual(actual.dims, result.value.dims, f"{result.text}: FreeCAD gives "
                                 f"{onshape.describe_dims(actual.dims)}")
                self.assertTrue(onshape.values_agree(actual.value, result.value.value),
                                f"{result.text}: FreeCAD {actual.value}, translator "
                                f"{result.value.value}")
                # and the text sets the variable's property without an error
                name = f"Result{i}"
                self.varSet.addProperty(result.property_type, name)
                self.varSet.setExpression(name, result.text)
                self.doc.recompute()
                self.assertNotIn("Invalid", self.varSet.State, result.text)


if __name__ == "__main__":
    unittest.main()
