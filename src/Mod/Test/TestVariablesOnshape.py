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
hand from the made-up inputs (1 in = 25.4 mm); TestFreeCADAgrees checks that FreeCAD computes the
written text to the translator's own value. The reference studio (TestReferenceStudio and
TestReferenceStudioImport) is the oracle from Onshape itself: made-up variables the user built
in Onshape for this test, with the values Onshape shows (decision 68, D3).
"""

import json
import math
import os
import shutil
import tempfile
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
    ("3/4in", "LENGTH", 19.05, "((3 / 4) * 1 in)"),
    ("3/4 in", "LENGTH", 19.05, "((3 / 4) * 1 in)"),
    ("(3/4) in", "LENGTH", 19.05, "((3 / 4) * 1 in)"),
    ("-3/4 in", "LENGTH", -19.05, "(((-3) / 4) * 1 in)"),
    ("2in+3/4in", "LENGTH", 69.85, "(2 * 1 in) + ((3 / 4) * 1 in)"),
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
    ("PI * 2 mm", "LENGTH", 2 * math.pi, "((pi * 2) * 1 mm)"),
    ("Pi * 2 mm", "LENGTH", 2 * math.pi, None),
    ("max(#Width, 1 cm, 3/4 in)", "LENGTH", 19.05, None),
    ("abs(-2 mm)", "LENGTH", 2, None),
    ("sqrt(#Width * #Width)", "LENGTH", 10, None),
    ("(2 mm)^2 / (1 mm)", "LENGTH", 4, None),
    ("2^3 * 1 mm", "LENGTH", 8, None),
    # right to left, as Onshape (the reference studio, row 27)
    ("2^3^2", "NUMBER", 512, "2 ^ (3 ^ 2)"),
    # a minus on a number goes first, as Onshape (the reference studio, row 22)
    ("-2^2", "NUMBER", 4, "(-2) ^ 2"),
    ("3 - 2^2", "NUMBER", -1, None),
    ("-2^3 * 1 mm", "LENGTH", -8, None),
    ("(-2^2) * 1 mm", "LENGTH", 4, None),
    ("max(1, -2^2)", "NUMBER", 4, None),
    # ^ binds to the unit, as Onshape (the reference studio, row 23)
    ("2 mm^2 / (1 mm)", "LENGTH", 2, "(2 * ((1 mm) ^ 2)) / (1 * 1 mm)"),
    ("sqrt(3 in^2 + 1 in^2)", "LENGTH", 50.8, None),
    ("-2 mm^2 / (1 mm)", "LENGTH", -2, None),
    ("2 mm^6 / (1 mm)^5", "LENGTH", 2, None),
    # halves up, as Onshape (the reference studio, row 24); FreeCAD's round() goes away from 0
    ("round(2.5) * 10 + round(-2.5)", "NUMBER", 28,
     "(floor(2.5 + 0.5) * 10) + floor((-2.5) + 0.5)"),
    ("round(-2.6)", "NUMBER", -3, None),
    ("round(#Count / 2) * 1 mm", "LENGTH", 2, None),
    # the sign of the divisor, as Onshape (the reference studio, row 25)
    ("-7 % 3", "NUMBER", 2, "(-7) % 3"),
    ("#Count % 2", "NUMBER", 1, "Count % 2"),
    ("(0 - #Count) % 2", "NUMBER", 1, None),
    ("7.5 % 2", "NUMBER", 1.5, "7.5 % 2"),
    ("-7.5 % 2", "NUMBER", 0.5, None),
    # not a whole number: Python's remainder, as FreeCAD's % (3 % 0.1 is 0.0999..., not 0)
    ("#Count % 0.1", "NUMBER", 3 % 0.1, "Count % 0.1"),
    ("(#Count * 0 + 1) % 0.2", "NUMBER", 1 % 0.2, None),
    # a unit name after / is one of it, as Onshape (the reference studio, row 26)
    ("(floor(#Rail/mm)) mm", "LENGTH", 101, "(floor((Rail / (1 mm))) * 1 mm)"),
    ("#Rail / in", "NUMBER", 4, "Rail / (1 in)"),
    ("#Rail / inches * 2", "NUMBER", 8, None),
    ("90 deg / rad", "NUMBER", math.pi / 2, None),
    # and after *, as Onshape (oracle 14 V3, ops#720)
    ("2.9*mm", "LENGTH", 2.9, "(2.9 * 1 mm)"),
    ("-0.0254*m", "LENGTH", -25.4, "((-0.0254) * 1 m)"),
    ("1.5e-3*m", "LENGTH", 1.5, "(1.5e-3 * 1 m)"),
    ("#Count * mm", "LENGTH", 3, "(Count * 1 mm)"),
    ("0.5*rad", "ANGLE", math.degrees(0.5), "(0.5 * 1 rad)"),
    # a unit word is `* unit`, left to right with * and /, as Onshape (the reference studio,
    # row 21; oracle 14 V3, ops#728)
    ("2 * 3/4 in", "LENGTH", 38.1, "(((2 * 3) / 4) * 1 in)"),
    ("#Count*3/4 in", "LENGTH", 57.15, "(((Count * 3) / 4) * 1 in)"),
    ("2 / 4 * -1/2 in", "LENGTH", -6.35, "((((2 / 4) * (-1)) / 2) * 1 in)"),
    ("3/4 in * 2", "LENGTH", 38.1, "((3 / 4) * 1 in) * 2"),
    ("6 / 3/4 in", "LENGTH", 12.7, None),
    ("1/3/4 in", "LENGTH", 25.4 / 12, None),
    ("1.5/2 in", "LENGTH", 19.05, "((1.5 / 2) * 1 in)"),
    ("2 * 1.5/2 in", "LENGTH", 38.1, None),
    ("3in/8", "LENGTH", 9.525, "(3 * 1 in) / 8"),
    ("1/2 mm^2 / (1 mm)", "LENGTH", 0.5, None),
    ("sqrt(4) mm^2 / (1 mm)", "LENGTH", 2, "(sqrt(4) * ((1 mm) ^ 2)) / (1 * 1 mm)"),
    ("2^3 mm", "LENGTH", 8, "((2 ^ 3) * 1 mm)"),
    ("#Count in", "LENGTH", 76.2, "(Count * 1 in)"),
    ("#Width * 1 mm / mm^2", "NUMBER", 10, "((Width * 1) * 1 mm) / ((1 mm) ^ 2)"),
    ("7 % 4", "NUMBER", 3, None),
    ("(7 % 3) mm", "LENGTH", 1, "((7 % 3) * 1 mm)"),
    ("floor(2.5) * 1 mm", "LENGTH", 2, None),
    (".5 mm", "LENGTH", 0.5, "(0.5 * 1 mm)"),
    ("#Count * 2", "NUMBER", 6, "Count * 2"),
    ("1.5 rad", "ANGLE", math.degrees(1.5), None),
    # exponent notation: Onshape's 1.5e2 is 150 (the reference studio, row 28)
    ("1.5e2", "NUMBER", 150, "1.5e2"),
    ("1e3 * 1 mm", "LENGTH", 1000, "((1e3 * 1) * 1 mm)"),
    ("2.5E-1 in", "LENGTH", 6.35, "(2.5E-1 * 1 in)"),
    ("5.e1 mm", "LENGTH", 50, "(5.0e1 * 1 mm)"),
]

# (Onshape text, type, a fragment of the reason)
REFUSED = [
    ("#Width && #Rail", "LENGTH", "no && (and)"),
    ("#Width || #Rail", "LENGTH", "no || (or)"),
    ("!x", "NUMBER", "no ! (not)"),
    ("[1,2][0]", "NUMBER", "arrays"),
    ('"text"', "NUMBER", "strings"),
    ("round(2.5 mm)", "LENGTH", "round() of a value with a unit"),
    ("round(2.5, 1)", "NUMBER", "round() takes 1 argument, not 2"),
    ("asinh(1)", "NUMBER", "asinh"),
    ("5 furlong", "LENGTH", "unknown unit 'furlong'"),
    ("foo + 1", "NUMBER", "unknown name 'foo'"),
    ("#Width + 2", "LENGTH", "bare number"),
    ("", "LENGTH", "empty"),
    ("5", "LENGTH", "default unit"),
    ("#Count * 2", "LENGTH", "default unit"),
    ("#Width*3/4 in", "LENGTH", "length^2"),
    # `/ 1 mm` divides by 1 and then multiplies by mm (oracle 14 V3, ops#728)
    ("(2 mm)^2 / 1 mm", "LENGTH", "length^3"),
    ("-2 mm^2 / 1 mm", "LENGTH", "length^3"),
    # a number plus a length, an error in Onshape too (oracle 14 V3)
    ("1/2 + 1/2in", "LENGTH", "bare number"),
    ("1/(8in)", "LENGTH", "length^-1"),
    ("-#Count^2", "NUMBER", "minus before ^"),
    ("-(2)^2", "NUMBER", "minus before ^"),
    # the studio shows -2^2 only as a whole expression (review 320, finding 2)
    ("2^-1^2 * 1 mm", "LENGTH", "a minus on a number before ^ after an operator"),
    ("2^-3^2", "NUMBER", "a minus on a number before ^ after an operator"),
    ("2 * -2^2", "NUMBER", "a minus on a number before ^ after an operator"),
    ("1 - -2^2", "NUMBER", "a minus on a number before ^ after an operator"),
    ("-+2^2", "NUMBER", "two signs before ^"),
    ("+-2^2", "NUMBER", "a minus on a number before ^ after an operator"),
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
    ("sqrt(4) mm^2 / 1 mm", "LENGTH", "length^3"),
    ("2 mm^0", "NUMBER", "a unit to the power 0"),
    ("2 mm^-1", "NUMBER", "a unit to a power other than a whole number"),
    ("2 mm^1.5", "NUMBER", "a unit to a power other than a whole number"),
    ("2 mm^2^2", "NUMBER", "chained ^ after a unit"),
    ("2 mm^400 / (1 mm)^399", "LENGTH", "a unit to a power above 6"),
    ("2 mm^7 / (1 mm)^6", "LENGTH", "a unit to a power above 6"),
    ("1/2 mm^2 / 1 mm", "LENGTH", "length^3"),
    ("2 mm^2", "LENGTH", "length^2"),
    ("#Width/2 in", "LENGTH", "length^2"),
    ("#Width*1/8in", "LENGTH", "length^2"),
    ("3in*3in", "LENGTH", "length^2"),
    ("10 mm", "ANGLE", "is a length, but the variable is an angle"),
    ("7 mm % 4 mm", "LENGTH", "a unit after %"),
    ("7 mm % 4", "LENGTH", "% with units"),
    ("7 % -4", "NUMBER", "% by a negative number or zero"),
    ("7 % 0", "NUMBER", "% by a negative number or zero"),
    ("floor(2.5 mm)", "LENGTH", "floor() of a value with a unit: Onshape rejects it"),
    ("ceil(2.5 mm)", "LENGTH", "ceil() of a value with a unit"),
    ("#Width / mm^2", "NUMBER", "length^-1"),
    ("#Width / mm mm", "NUMBER", "two units"),
    ("#Width * mm", "NUMBER", "length^2"),
    ("2 * mm 3", "LENGTH", "unexpected '3'"),
    ("#Width in", "LENGTH", "length^2"),
    ("7 % mm", "NUMBER", "% before a unit"),
    ("7 % 3 mm", "LENGTH", "a unit after % and its operand"),
    ("2 mm + mm", "LENGTH", "needs a number"),
    ("2 * (mm)", "LENGTH", "needs a number"),
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


# The reference studio the user built in Onshape for this test (decision 68, D3; made-up values,
# notes/variables-studio.md 5.1): each variable as the studio's export has it, in its order, and
# the value Onshape shows for it. Rows 1-19 are forms the translator accepted before; rows 20-28
# were refused until this studio settled them. The document's default units were mm and deg.
REFERENCE_STUDIO = [
    # (type, name, expression as exported, Onshape's value as shown)
    ("LENGTH", "Len_mm", "10mm", "10 mm"),
    ("LENGTH", "Len_frac", "2 in + 3/4 in", "69.85 mm"),
    ("LENGTH", "Len_ft", "1ft + 2in", "355.6 mm"),
    ("LENGTH", "Len_mixed", "1 m - 25 cm + 3in", "826.2 mm"),
    ("LENGTH", "Len_words", "(3/4) inches + 1 foot", "323.85 mm"),
    ("LENGTH", "Chain1", "#Len_mm * 2 + 1 cm", "30 mm"),
    ("LENGTH", "Chain2", "#Chain1 + #Len_mm", "40 mm"),
    ("NUMBER", "Chain3", "#Chain2 / #Len_mm", "4"),
    ("NUMBER", "Prec", "2 + 3 * 2^2 - 8 / 4 / 2", "13"),
    ("LENGTH", "Pow_len", "sqrt((3 mm)^2 + (4 mm)^2)", "5 mm"),
    ("LENGTH", "Sqrt_area", "sqrt(#Len_mm * #Chain1)", "17.321 mm"),
    ("ANGLE", "Ang_mixed", "30 deg + 0.5 rad", "58.648 deg"),
    ("NUMBER", "Trig", "sin(30 deg) + cos(#Ang_mixed - 0.5 rad + 30 deg) + tan(45 deg)", "2"),
    ("ANGLE", "Inv_trig", "atan2(1 in, 25.4 mm) + asin(0.5)", "75 deg"),
    ("NUMBER", "Floor_ceil", "floor(7.6) + ceil(-2.1)", "5"),
    ("LENGTH", "Floor_qty", "floor(#Len_frac / (1 in)) * 1 in + ceil(#Len_ft / (1 ft)) * 1 ft",
     "660.4 mm"),
    ("LENGTH", "Min_max", "min(#Len_ft, 1 ft) - max(#Len_mm, max(1/2in, 12.5mm))", "292.1 mm"),
    ("LENGTH", "Cond", "#Chain2 > 4 in ? 1 in : 2 in", "50.8 mm"),
    ("NUMBER", "Mod", "17 % 5", "2"),
    ("LENGTH", "Unitless_len", "25 mm", "25 mm"),
    ("LENGTH", "R_frac_prod", "2 * 3/4 in", "38.1 mm"),
    ("NUMBER", "R_neg_pow", "-2^2", "4"),
    ("LENGTH", "R_unit_pow", "2 mm^2 / (1 mm)", "2 mm"),
    ("NUMBER", "R_round", "round(2.5) * 10 + round(-2.5)", "28"),
    ("NUMBER", "R_mod_neg", "-7 % 3", "2"),
    ("LENGTH", "R_floor_qty", "(floor(#Len_frac/mm)) mm", "69 mm"),
    ("NUMBER", "R_chain_pow", "2^3^2", "512"),
    ("NUMBER", "R_exp", "1.5e2", "150"),
]
REFERENCE_UNITS = {"LENGTH": "mm", "ANGLE": "deg"}
# Onshape shows at most three decimals and drops trailing zeros (17.321 mm, 58.648 deg), so a
# shown value is the true one to within half of 0.001.
SHOWN_TOLERANCE = 0.0005


def shown_value(shown):
    """(number, unit or None) of a value as Onshape shows it: "17.321 mm", "4"."""
    number, _, unit = shown.partition(" ")
    return float(number), unit or None


class TestReferenceStudio(unittest.TestCase):
    """The translator against the values Onshape shows for the reference studio (the oracle,
    decision 68 D3 A). A disagreement is a translator bug."""

    def assertShown(self, value, shown, what):
        number, unit = shown_value(shown)
        expected_dims = {"mm": LENGTH, "deg": ANGLE, None: NONE}[unit]
        self.assertEqual(value.dims, expected_dims, f"{what}: {onshape.describe_dims(value.dims)}")
        actual = value.to(unit) if unit else value.value
        self.assertLessEqual(abs(actual - number), SHOWN_TOLERANCE,
                             f"{what}: Onshape shows {shown}, the translator {actual}")

    def test_every_variable_has_onshape_s_value(self):
        entries = onshape.parse_export(export([v[:3] for v in REFERENCE_STUDIO]))
        result = onshape.translate_export(entries, default_units=REFERENCE_UNITS)
        self.assertEqual(result.unresolved, {})
        for kind, name, _expression, shown in REFERENCE_STUDIO:
            with self.subTest(name=name):
                variable = result.result(name)
                self.assertIsNone(variable.refusal)
                self.assertEqual(variable.translation.property_type, onshape.TYPES[kind][0])
                self.assertShown(variable.translation.value, shown, name)

    def test_the_forms_onshape_rejects_stay_refused(self):
        # the user, building the studio: Onshape takes only a number in floor() (row 26)
        with self.assertRaises(Refused) as cm:
            translate("floor(#Rail)", "LENGTH")
        self.assertIn("Onshape rejects it", str(cm.exception))


# Oracle 14 V3 (ops#640, 2026-11-12): how Onshape binds a unit. Each expression was an ANY
# variable in a test studio, evaluated by Onshape's getVariable, with #w = 1 in. The rule: a unit
# word is `* unit` at the precedence of `*` and `/`, applied left to right (ops#728).
# (expression, Onshape's value in SI units with its dimensions, or None for Onshape's error)
V3_W = Quantity(0.0254, LENGTH)
AREA = (2, 0)
V3_ORACLE = [
    ("1/8in", 0.003175, LENGTH),
    ("3/8in", 0.009525, LENGTH),
    ("1/32in", 0.00079375, LENGTH),
    ("3/8 in", 0.009525, LENGTH),
    ("(3/8)in", 0.009525, LENGTH),
    ("1/(8in)", 4.92125984, (-1, 0)),
    ("3in/8", 0.009525, LENGTH),
    ("2*3/8in", 0.01905, LENGTH),
    ("1/8in*2", 0.00635, LENGTH),
    ("1/2 + 1/2in", None, None),
    ("1/2mm + 1mm", 0.0015, LENGTH),
    ("2mm*3", 0.006, LENGTH),
    (".8", 0.8, NONE),
    ("1.5cm", 0.015, LENGTH),
    ("0.5cm*2", 0.01, LENGTH),
    ("100mm*0.95 + 1cm", 0.105, LENGTH),
    ("-0.0254*m", -0.0254, LENGTH),
    ("1.5e-3*m", 0.0015, LENGTH),
    ("0.5*rad", 0.5, ANGLE),
    ("45 degree", 0.785398163, ANGLE),
    ("1 meter", 1.0, LENGTH),
    ("cos(45 deg)", 0.707106781, NONE),
    ("sqrt(2)", 1.41421356, NONE),
    ("tan(86.4280321 deg)", 16.0196097, NONE),
    ("#w/2in", 3.2258e-4, AREA),
    ("2^3", 8.0, NONE),
    ("10 mm ^ 2", 1e-5, AREA),
    # more # forms
    ("#w/2", 0.0127, LENGTH),
    ("#w*2", 0.0508, LENGTH),
    ("#w/(2in)", 0.5, NONE),
    ("#w/2 in", 3.2258e-4, AREA),
    ("#w / 2in", 3.2258e-4, AREA),
    ("#w/2mm", 1.27e-5, AREA),
    ("#w + 1/8in", 0.028575, LENGTH),
    ("#w*1/8in", 8.0645e-5, AREA),
    ("1/2in + #w", 0.0381, LENGTH),
]
# Onshape's values above are shown to 9 significant digits
V3_TOLERANCE = 1e-8


def v3_resolve(name):
    if name != "w":
        raise Refused(f"#{name} isn't defined")
    return ("W", V3_W)


class TestUnitRuleOracle(unittest.TestCase):
    """The translator against Onshape's own values for oracle 14 V3 (ops#720, ops#728). A
    disagreement is a translator bug."""

    def test_every_row_has_onshape_s_value(self):
        for text, expected, dims in V3_ORACLE:
            with self.subTest(text=text):
                tree = onshape.parse(text)
                if expected is None:
                    with self.assertRaises(Refused):
                        onshape.evaluate(tree, lambda name: v3_resolve(name)[1])
                    continue
                value = onshape.evaluate(tree, lambda name: v3_resolve(name)[1])
                self.assertEqual(value.dims, dims, onshape.describe_dims(value.dims))
                self.assertLessEqual(abs(value.value - expected), V3_TOLERANCE * abs(expected),
                                     f"Onshape {expected}, the translator {value.value}")

    def test_a_variable_takes_only_its_type(self):
        """A LENGTH variable rejects what isn't a length, as Onshape's "Bad variable expression"
        does; a length row translates to the same value."""
        for text, expected, dims in V3_ORACLE:
            with self.subTest(text=text):
                if dims == LENGTH:
                    result = onshape.translate(text, "LENGTH", v3_resolve)
                    self.assertLessEqual(abs(result.value.value - expected),
                                         V3_TOLERANCE * abs(expected))
                else:
                    with self.assertRaises(Refused):
                        onshape.translate(text, "LENGTH", v3_resolve)


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


@unittest.skipIf(FreeCAD is None, "needs FreeCAD")
class TestReferenceStudioImport(unittest.TestCase):
    """The reference studio imported as a copy (PR E1): the import's own check (section 2.5)
    computes every written text in FreeCAD against the translator, and each variable keeps the
    value Onshape shows."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="TestVariablesOnshape")
        self.doc = FreeCAD.newDocument("TestReferenceStudio")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_the_copy_holds_onshape_s_values(self):
        from freecad.variables import copies

        path = os.path.join(self.folder, "Onshape Reference Studio.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(export([v[:3] for v in REFERENCE_STUDIO]))
        copy = copies.import_studios(self.doc, [path], default_units=REFERENCE_UNITS).copies[0]
        units = {"mm": FreeCAD.Units.Length, "deg": FreeCAD.Units.Angle}
        for _kind, name, _expression, shown in REFERENCE_STUDIO:
            with self.subTest(name=name):
                value = getattr(copy, name)
                number, unit = shown_value(shown)
                if unit:
                    self.assertEqual(value.Unit, units[unit])
                    value = value.Value  # mm or deg, FreeCAD's internal units
                self.assertLessEqual(abs(value - number), SHOWN_TOLERANCE,
                                     f"{name}: Onshape shows {shown}, the copy {value}")


@unittest.skipIf(FreeCAD is None, "needs FreeCAD")
class TestUnitRuleInFreeCAD(unittest.TestCase):
    """Oracle 14 V3 in FreeCAD (ops#720, ops#728): the written text of every row Onshape accepts
    computes to Onshape's value, and imported variables drive pads. Designed model: 10 x 10 mm
    squares padded by imported lengths."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="TestVariablesOnshape")
        self.doc = FreeCAD.newDocument("TestUnitRule")
        self.varSet = self.doc.addObject("App::VarSet", "VarSet")
        self.varSet.addProperty("App::PropertyDistance", "W")
        self.varSet.W = "1 in"

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def si_value(self, text, dims):
        """FreeCAD's value of @a text in SI units: divided by the SI unit of @a dims (multiplied,
        for an inverse length), so that FreeCAD's result must be a plain number."""
        length, angle = dims
        if length > 0:
            text = f"({text}) / ((1 m) ^ {length})"
        elif length < 0:
            text = f"({text}) * ((1 m) ^ {-length})"
        if angle:
            text = f"({text}) / (1 rad)"
        value = self.varSet.evalExpression(text)
        if isinstance(value, FreeCAD.Units.Quantity):
            self.assertEqual(value.Unit, FreeCAD.Units.Unit(), f"{text}: {value.Unit}")
            return value.Value
        return float(value)

    def test_freecad_computes_onshape_s_value(self):
        for text, expected, dims in V3_ORACLE:
            if expected is None:
                continue
            with self.subTest(text=text):
                tree = onshape.parse(text)
                written = onshape.write(tree, lambda name: v3_resolve(name)[0])
                actual = self.si_value(written, dims)
                self.assertLessEqual(abs(actual - expected), V3_TOLERANCE * abs(expected),
                                     f"{written}: FreeCAD {actual}, Onshape {expected}")

    def pad(self, name, length):
        import Part

        body = self.doc.addObject("PartDesign::Body", "Body" + name)
        sketch = body.newObject("Sketcher::SketchObject", "Sketch" + name)
        corners = [FreeCAD.Vector(x, y, 0) for x, y in ((0, 0), (10, 0), (10, 10), (0, 10))]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        pad = body.newObject("PartDesign::Pad", "Pad" + name)
        pad.Profile = sketch
        pad.setExpression("Length", length)
        return pad

    def import_studio(self, variables):
        from freecad.variables import copies

        path = os.path.join(self.folder, "Unit Rule Studio.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(export(variables))
        return copies.import_studios(self.doc, [path]).copies[0]

    def test_a_bare_unit_after_times(self):
        """ops#720 (G1): L = 2.9*mm imports as 2.9 mm, and a pad by #L is 290 mm³."""
        copy = self.import_studio([("LENGTH", "L", "2.9*mm")])
        pad = self.pad("L", "#L")
        self.doc.recompute()
        self.assertAlmostEqual(copy.L.Value, 2.9, places=9)
        self.assertAlmostEqual(pad.Shape.Volume, 290, places=6)

    def test_a_unit_is_times_unit_left_to_right(self):
        """ops#728 (G10): a = 1/8in*2 and b = 3in/8 import as Onshape reads them, 6.35 mm and
        9.525 mm, and pads by them are that tall."""
        copy = self.import_studio([("LENGTH", "a", "1/8in*2"), ("LENGTH", "b", "3in/8")])
        pad_a = self.pad("A", "#a")
        pad_b = self.pad("B", "#b")
        self.doc.recompute()
        self.assertAlmostEqual(copy.a.Value, 6.35, places=9)
        self.assertAlmostEqual(copy.b.Value, 9.525, places=9)
        self.assertAlmostEqual(pad_a.Shape.BoundBox.ZLength, 6.35, places=6)
        self.assertAlmostEqual(pad_b.Shape.BoundBox.ZLength, 9.525, places=6)


if __name__ == "__main__":
    unittest.main()
