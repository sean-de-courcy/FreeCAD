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

"""Copies of Onshape exports, App::VarSetCopy and freecad.variables.copies (FreeCAD-CH, ops#317
PR E1).

notes/variables-studio.md section 6, "Import" (I-1 to I-6) and R-9. Every export here is made up,
in the structure of an Onshape variable studio export (section 0); expected values are worked out
by hand from the made-up inputs (1 in = 25.4 mm).
"""

import hashlib
import json
import os
import shutil
import tempfile
import unittest

import FreeCAD as App

from freecad.variables import copies
from freecad.variables.copies import ImportBlocked, ImportCheckFailed

# The static properties of section 3.1 and their types: the copy's file format for the beta
# (decision 65). A change here is a format change: raise CopyFormat and write an upgrade.
FORMAT = {
    "CopyFormat": "App::PropertyInteger",
    "SourceKind": "App::PropertyEnumeration",
    "SourcePath": "App::PropertyString",
    "SourceRelativePath": "App::PropertyString",
    "SourceObject": "App::PropertyString",
    "SourceEntries": "App::PropertyInteger",
    "SourceStamp": "App::PropertyString",
    "SourceRefreshed": "App::PropertyString",
    "SourceExpressions": "App::PropertyMap",
    "NameMap": "App::PropertyMap",
    "Bindings": "App::PropertyMap",
    "Skipped": "App::PropertyStringList",
    "Orphans": "App::PropertyStringList",
}


def variable(kind, name, expression, description=""):
    return {"type": kind, "name": name, "value": None, "description": description,
            "expression": expression}


def entry(*variables):
    return {"variableStudioReference": None, "variables": list(variables)}


# I-1: lengths, an angle, a number, a fraction, a chain of references, descriptions.
STUDIO = [entry(
    variable("LENGTH", "Width", "10 mm", "the width"),
    variable("LENGTH", "Rail", "3/4 in", "first line\nsecond <&> line"),
    variable("ANGLE", "Tilt", "30 deg"),
    variable("NUMBER", "Count", "3"),
    variable("LENGTH", "Gap", "#Width / #Count + 2 mm"),
    variable("LENGTH", "Total", "#Gap * 2 + #Rail", "a chain"),
)]
STUDIO_VALUES = {  # by hand, in mm, deg or plain
    "Width": 10,
    "Rail": 19.05,
    "Tilt": 30,
    "Count": 3,
    "Gap": 10 / 3 + 2,
    "Total": (10 / 3 + 2) * 2 + 19.05,
}
STUDIO_TYPES = {
    "Width": "App::PropertyDistance",
    "Rail": "App::PropertyDistance",
    "Tilt": "App::PropertyAngle",
    "Count": "App::PropertyFloat",
    "Gap": "App::PropertyDistance",
    "Total": "App::PropertyDistance",
}

# I-2: A uses #Gap, which only B defines.
STUDIO_A = [entry(
    variable("LENGTH", "Width", "#Gap * 2"),
    variable("LENGTH", "Height", "5 mm"),
)]
STUDIO_B = [entry(variable("LENGTH", "Gap", "3 mm"))]


def value(obj, name):
    prop = getattr(obj, name)
    return prop.Value if hasattr(prop, "Value") else prop


def expression(obj, name):
    for path, text in obj.ExpressionEngine:
        if path == name:
            return text
    return None


class TestVariablesCopies(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="TestVariablesCopies")
        self.doc = App.newDocument("TestVariablesCopies")
        self.doc.UndoMode = 1

    def tearDown(self):
        copies._check_hook = None
        for name in list(App.listDocuments()):
            if name.startswith("TestVariablesCopies"):
                App.closeDocument(name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def export(self, name, data):
        path = os.path.join(self.folder, name + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

    def names(self):
        return sorted(o.Name for o in self.doc.Objects)

    def documentVariables(self, gap="7 mm"):
        """The document's own "Variables" set, with Gap."""
        variables = self.doc.addObject("App::VarSet", "Variables")
        variables.addProperty("App::PropertyDistance", "Gap")
        variables.Gap = gap
        self.doc.recompute()
        return variables

    # I-1

    def test_import(self):
        """I-1. Values by hand, types, descriptions, SourceExpressions equal the JSON's texts,
        the variables read-only, the source recorded; one undo removes everything."""
        path = self.export("Studio A", STUDIO)
        undoCount = self.doc.UndoCount
        result = copies.import_studios(self.doc, [path])
        self.assertEqual(len(result.copies), 1)
        copy = result.copies[0]
        self.assertEqual(copy.TypeId, "App::VarSetCopy")
        self.assertEqual(copy.Label, "Studio A")
        self.assertNotIn("Touched", copy.State)  # recorded the source after the recompute
        for name, expected in STUDIO_VALUES.items():
            with self.subTest(name=name):
                self.assertEqual(copy.getTypeIdOfProperty(name), STUDIO_TYPES[name])
                self.assertAlmostEqual(value(copy, name), expected, places=9)
                self.assertIn("ReadOnly", copy.getPropertyStatus(name))
                self.assertNotIn("#", expression(copy, name))
        self.assertEqual(copy.getDocumentationOfProperty("Width"), "the width")
        self.assertEqual(copy.getDocumentationOfProperty("Rail"), "first line\nsecond <&> line")
        self.assertEqual(copy.getDocumentationOfProperty("Tilt"), "")
        self.assertEqual(copy.SourceExpressions,
                         {v["name"]: v["expression"] for v in STUDIO[0]["variables"]})
        self.assertEqual(copy.SourceKind, "Onshape JSON")
        self.assertEqual(copy.SourcePath, os.path.abspath(path).replace(os.sep, "/"))
        self.assertEqual(copy.SourceObject, "0")
        self.assertEqual(copy.SourceEntries, 1)
        self.assertEqual(copy.NameMap, {})
        self.assertEqual(copy.Bindings, {})
        self.assertEqual(copy.Skipped, [])
        self.assertEqual(copy.Orphans, [])
        self.assertTrue(copy.SourceRefreshed.endswith("Z"))
        # the stamp: the version and the SHA-256 of the canonical form (section 3.2), by hand
        canonical = [[v["name"], v["type"], v["expression"], v["description"], v["value"]]
                     for v in STUDIO[0]["variables"]]
        text = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        self.assertEqual(copy.SourceStamp,
                         "sha256:json1:" + hashlib.sha256(text.encode("utf-8")).hexdigest())
        # the read-only variables still follow their expressions
        copy.touch()
        self.doc.recompute()
        self.assertAlmostEqual(copy.Total.Value, STUDIO_VALUES["Total"], places=9)

        self.assertEqual(self.doc.UndoCount, undoCount + 1)
        self.doc.undo()
        self.assertEqual(self.doc.Objects, [])

    def test_import_twice_warns(self):
        path = self.export("Studio A", STUDIO)
        copies.import_studios(self.doc, [path])
        plan = copies.plan_import(self.doc, [path])
        self.assertTrue(plan.ok)
        self.assertTrue(any("already a copy" in w for w in plan.warnings), plan.warnings)
        second = copies.import_studios(self.doc, [path]).copies[0]
        self.assertNotEqual(second.Name, "Studio_A")
        self.assertEqual(len(self.doc.findObjects("App::VarSetCopy")), 2)

    def test_paths_portable(self):
        """Paths are saved with "/" (section 3.1), so a document saved on Windows finds its
        sources on macOS: the absolute one and the one relative to the document's file."""
        os.mkdir(os.path.join(self.folder, "exports"))
        path = self.export(os.path.join("exports", "Studio A"), STUDIO)
        self.doc.saveAs(os.path.join(self.folder, "model.FCStd"))
        copy = copies.import_studios(self.doc, [path]).copies[0]
        self.assertNotIn("\\", copy.SourcePath)
        self.assertEqual(copy.SourceRelativePath, "exports/Studio A.json")
        # the same file, given with the other separator, is the same source
        plan = copies.plan_import(self.doc, [path.replace(os.sep, "/")])
        self.assertTrue(any("already a copy" in w for w in plan.warnings), plan.warnings)

    # I-2

    def test_missing_studio(self):
        """I-2. A uses #Gap, which only B defines; the document has Variables.Gap = 7 mm. A alone:
        listed with its users, nothing made, Variables.Gap no new user. "Use Variables.Gap": the
        expression names it and Bindings records it. A and B together: A names B's copy."""
        variables = self.documentVariables()
        a = self.export("Studio A", STUDIO_A)
        b = self.export("Studio B", STUDIO_B)
        before = self.names()

        with self.assertRaises(ImportBlocked) as blocked:
            copies.import_studios(self.doc, [a])
        plan = blocked.exception.plan
        self.assertEqual(plan.unresolved, {"Gap": ["Width"]})
        self.assertIn("#Gap is used by Width but defined in none of the imported files",
                      str(blocked.exception))
        self.assertEqual(self.names(), before)
        self.assertEqual(variables.InList, [])

        copy = copies.import_studios(self.doc, [a], bindings={"Gap": "Variables.Gap"}).copies[0]
        self.assertIn("Variables.Gap", expression(copy, "Width"))
        self.assertEqual(copy.Bindings, {"Gap": "Variables.Gap"})
        self.assertAlmostEqual(copy.Width.Value, 14)
        variables.Gap = "8 mm"  # the binding is live, through the read-only variable
        self.doc.recompute()
        self.assertAlmostEqual(copy.Width.Value, 16)
        self.doc.undo()

        result = copies.import_studios(self.doc, [a, b])
        copyA, copyB = result.copies
        self.assertEqual(expression(copyA, "Width").replace(" ", "").count(copyB.Name + ".Gap"), 1)
        self.assertNotIn("Variables", expression(copyA, "Width"))
        self.assertEqual(copyA.Bindings, {})
        self.assertAlmostEqual(copyA.Width.Value, 6)
        self.assertEqual(variables.InList, [])

    def test_missing_studio_value(self):
        """A value entered for #Gap becomes an input variable in "Variables", editable; one undo
        removes it and the copy."""
        a = self.export("Studio A", STUDIO_A)
        result = copies.import_studios(self.doc, [a], values={"Gap": ("LENGTH", "7 mm")})
        variables = self.doc.getObject("Variables")
        self.assertIsNotNone(variables)
        self.assertEqual(variables.TypeId, "App::VarSet")
        self.assertAlmostEqual(variables.Gap.Value, 7)
        self.assertNotIn("ReadOnly", variables.getPropertyStatus("Gap"))
        copy = result.copies[0]
        self.assertEqual(copy.Bindings, {"Gap": "Variables.Gap"})
        self.assertAlmostEqual(copy.Width.Value, 14)
        self.doc.undo()
        self.assertEqual(self.doc.Objects, [])

    def test_missing_studio_skip(self):
        """Skip #Gap: Width, which needs it, isn't imported; Height is. Skipped keeps the choice,
        so Refresh can tell Width from a variable added at the source."""
        a = self.export("Studio A", STUDIO_A)
        result = copies.import_studios(self.doc, [a], skip=["Gap"])
        copy = result.copies[0]
        self.assertNotIn("Width", copy.PropertiesList)
        self.assertAlmostEqual(copy.Height.Value, 5)
        self.assertEqual([(s[1]) for s in result.plan.skipped], ["Width"])
        self.assertEqual(copy.SourceExpressions, {"Height": "5 mm"})
        self.assertEqual(copy.Skipped, ["Gap"])

    def test_skip_variable(self):
        """Skip a variable the file defines: Skipped names it, in the copy of the file that
        defines it and in the copy that uses it; a skip that concerns neither isn't kept."""
        a = self.export("Studio A", STUDIO_A)
        b = self.export("Studio B", STUDIO_B)
        result = copies.import_studios(self.doc, [a, b], skip=["Height", "Gap", "Nothing"])
        copyA, copyB = result.copies
        self.assertEqual(copyA.Skipped, ["Gap", "Height"])
        self.assertEqual(copyB.Skipped, ["Gap"])
        self.assertEqual(copyA.SourceExpressions, {})
        self.assertEqual(copyB.SourceExpressions, {})

    def test_choices_for_defined_names(self):
        """A choice for a name the files define only warns: no input variable, no "Variables"
        set, and neither a taken name nor a bad path stops the import."""
        b = self.export("Studio B", STUDIO_B)
        for choices in ({"values": {"Gap": ("LENGTH", "7 mm")}},
                        {"bindings": {"Gap": "Nothing.Gap"}}):
            with self.subTest(choices=choices):
                result = copies.import_studios(self.doc, [b], **choices)
                self.assertTrue(any("#Gap is defined by the imported files" in w
                                    for w in result.plan.warnings), result.plan.warnings)
                self.assertEqual(result.inputs, [])
                self.assertEqual(result.copies[0].Bindings, {})
                self.assertIsNone(self.doc.getObject("Variables"))
                self.doc.undo()
        variables = self.documentVariables()  # Variables.Gap exists: a value would clash
        result = copies.import_studios(self.doc, [b], values={"Gap": ("LENGTH", "7 mm")})
        self.assertAlmostEqual(result.copies[0].Gap.Value, 3)
        self.assertEqual(variables.InList, [])

    def test_skip_and_bind(self):
        """Skip the file's Gap and bind #Gap to Variables.Gap: Width uses the document's Gap,
        and Bindings records it (the name is no longer defined once skipped)."""
        self.documentVariables()
        a = self.export("Studio A", [entry(variable("LENGTH", "Gap", "3 mm"),
                                           variable("LENGTH", "Width", "#Gap * 2"))])
        result = copies.import_studios(self.doc, [a], skip=["Gap"],
                                       bindings={"Gap": "Variables.Gap"})
        copy = result.copies[0]
        self.assertNotIn("Gap", copy.PropertiesList)
        self.assertAlmostEqual(copy.Width.Value, 14)
        self.assertEqual(copy.Bindings, {"Gap": "Variables.Gap"})
        self.assertEqual(copy.Skipped, ["Gap"])
        self.assertFalse(any("Gap" in w for w in result.plan.warnings), result.plan.warnings)

    def test_bad_choices(self):
        a = self.export("Studio A", STUDIO_A)
        for choices, fragment in [
            ({"bindings": {"Gap": "Nothing.Gap"}}, "isn't a variable of this document"),
            ({"values": {"Gap": ("LENGTH", "7")}}, "default unit"),
            ({"values": {"Gap": ("LENGTH", "#Other")}}, "can't use #Other"),
            ({"bindings": {"Gap": "Variables.Gap"}, "values": {"Gap": ("LENGTH", "7 mm")}},
             "two choices"),
        ]:
            with self.subTest(choices=choices):
                plan = copies.plan_import(self.doc, [a], **choices)
                self.assertFalse(plan.ok)
                self.assertTrue(any(fragment in p for p in plan.problems), plan.problems)

    # I-3

    def test_defined_twice(self):
        """I-3. A name two entries define is refused until a provider is chosen."""
        a = self.export("Studio A", [entry(variable("LENGTH", "Gap", "3 mm"))])
        b = self.export("Studio B", [entry(variable("LENGTH", "Gap", "4 mm"))])
        c = self.export("Studio C", [entry(variable("LENGTH", "Width", "#Gap * 2"))])
        with self.assertRaises(ImportBlocked) as blocked:
            copies.import_studios(self.doc, [a, b, c])
        self.assertEqual(blocked.exception.plan.ambiguous, {"Gap": [0, 1]})
        self.assertEqual(self.doc.Objects, [])
        result = copies.import_studios(self.doc, [a, b, c], providers={"Gap": 1})
        copyB, copyC = result.copies[1], result.copies[2]
        self.assertIn(copyB.Name + ".Gap", expression(copyC, "Width").replace(" ", ""))
        self.assertAlmostEqual(copyC.Width.Value, 8)

    def test_copies_cycle(self):
        """A.x uses B.y and B.z uses A.w: no variable refers to itself, but the copies would
        depend on each other, which FreeCAD can't recompute. The plan says so and names both
        uses; nothing is made. Skipping z breaks the cycle."""
        a = self.export("Studio A", [entry(variable("LENGTH", "x", "#y + 1 mm"),
                                           variable("LENGTH", "w", "2 mm"))])
        b = self.export("Studio B", [entry(variable("LENGTH", "y", "3 mm"),
                                           variable("LENGTH", "z", "#w * 2"))])
        with self.assertRaises(ImportBlocked) as blocked:
            copies.import_studios(self.doc, [a, b])
        message = str(blocked.exception)
        self.assertIn("depend on each other", message)
        self.assertIn("Studio A.x uses #y of Studio B", message)
        self.assertIn("Studio B.z uses #w of Studio A", message)
        self.assertEqual(self.doc.Objects, [])
        copyA, copyB = copies.import_studios(self.doc, [a, b], skip=["z"]).copies
        self.assertAlmostEqual(copyA.x.Value, 4)
        self.assertNotIn("z", copyB.PropertiesList)

    # I-4

    def test_check_failure_undoes(self):
        """I-4. The translator's value disagrees with FreeCAD's (the test hook moves Gap's by
        1 um): the import is undone, nothing is left, and the message shows both values and
        both texts."""
        path = self.export("Studio A", STUDIO)
        undoCount = self.doc.UndoCount

        def hook(result, expected):
            if result.name == "Gap":
                return copies.Quantity(expected.value + 1e-6, expected.dims)
            return expected

        copies._check_hook = hook
        with self.assertRaises(ImportCheckFailed) as failed:
            copies.import_studios(self.doc, [path])
        message = str(failed.exception)
        self.assertIn("Studio A.Gap", message)
        self.assertIn("#Width / #Count + 2 mm", message)
        self.assertIn("5.33333333333 mm", message)  # FreeCAD's
        self.assertIn("5.33433333333 mm", message)  # the translator's, moved
        self.assertEqual(self.doc.Objects, [])
        self.assertEqual(self.doc.UndoCount, undoCount)
        self.assertEqual(self.doc.getBookedTransactionID(), 0)

    def test_check_failure_in_booked_transaction(self):
        """The same inside a transaction someone else booked: what was made is taken out by
        hand, and the booking stays."""
        path = self.export("Studio A", STUDIO)
        copies._check_hook = lambda result, expected: copies.Quantity(expected.value * 2,
                                                                      expected.dims)
        self.doc.openTransaction("Task")
        booked = self.doc.getBookedTransactionID()
        with self.assertRaises(ImportCheckFailed):
            copies.import_studios(self.doc, [path], values={})
        self.assertEqual(self.doc.Objects, [])
        self.assertEqual(self.doc.getBookedTransactionID(), booked)
        self.doc.abortTransaction()
        self.assertEqual(self.doc.Objects, [])

    # I-5

    def test_unit_names(self):
        """I-5. Names t and H (units in FreeCAD): the plan proposes t_ and H_, NameMap records
        them, the expressions use them, and planning again with NameMap gives the same names
        (as Refresh will)."""
        path = self.export("Studio A", [entry(
            variable("LENGTH", "t", "2 mm"),
            variable("LENGTH", "H", "#t * 3"),
        )])
        plan = copies.plan_import(self.doc, [path])
        self.assertTrue(plan.ok, plan.problems)
        self.assertEqual(plan.renames, {"t": "t_", "H": "H_"})
        copy = copies.import_studios(self.doc, [path]).copies[0]
        self.assertEqual(copy.NameMap, {"t": "t_", "H": "H_"})
        self.assertNotIn("t", copy.PropertiesList)
        self.assertAlmostEqual(copy.H_.Value, 6)
        self.assertEqual(expression(copy, "H_").replace(" ", "").replace("(", "")[:2], "t_")
        again = copies.plan_import(self.doc, [path], name_map=dict(copy.NameMap))
        self.assertEqual(again.renames, dict(copy.NameMap))

    def test_names_freecad_cant_use(self):
        """The translator's FreeCAD names are checked (review 309's note): constants, a unit, a
        function, a property every copy has. Each gets a usable proposal; a name_map that names
        an unusable one is refused. A cell address's shape (`W2`) is a usable name: the copy's
        `#W2 * 2` computes."""
        names = ["pi", "e", "mm", "cos", "Label", "SourcePath", "Count_", "W2"]
        path = self.export("Studio A", [entry(
            *[variable("NUMBER", name, str(i + 1)) for i, name in enumerate(names)],
            variable("NUMBER", "Twice", "#W2 * 2"))])
        plan = copies.plan_import(self.doc, [path])
        self.assertTrue(plan.ok, plan.problems)
        for name in names[:-2]:
            with self.subTest(name=name):
                self.assertIn(name, plan.renames)
                self.assertEqual(App.checkVariableName(plan.renames[name], "App::VarSetCopy"),
                                 "")
        self.assertNotIn("Count_", plan.renames)
        self.assertNotIn("W2", plan.renames)
        copy = copies.import_studios(self.doc, [path]).copies[0]
        for i, name in enumerate(names):
            self.assertEqual(value(copy, plan.renames.get(name, name)), i + 1)
        self.assertEqual(copy.Twice, 16)
        bad = copies.plan_import(self.doc, [path], name_map={"pi": "e"})
        self.assertFalse(bad.ok)
        self.assertTrue(any("pi can't become e" in p for p in bad.problems), bad.problems)

    def test_check_variable_name(self):
        """FreeCAD.checkVariableName, the rules of section 1.3 for Python (PR B's question)."""
        self.assertIn("unit", App.checkVariableName("t"))
        self.assertIn("constant", App.checkVariableName("pi"))
        self.assertIn("function", App.checkVariableName("cos"))
        self.assertEqual(App.checkVariableName("Width_2"), "")
        self.assertIn("property of every", App.checkVariableName("Label", "App::VarSet"))
        self.assertEqual(App.checkVariableName("SourcePath", "App::VarSet"), "")
        self.assertIn("property of every", App.checkVariableName("SourcePath", "App::VarSetCopy"))
        variables = self.documentVariables()
        self.assertIn("already", App.checkVariableName("Gap", variables))
        self.doc.removeObject(variables.Name)
        with self.assertRaises(ReferenceError):  # a deleted holder: no checks to make
            App.checkVariableName("Gap", variables)
        with self.assertRaises(ValueError):
            App.checkVariableName("x", "App::NoSuchType")
        with self.assertRaises(UnicodeEncodeError):  # a lone surrogate isn't UTF-8
            App.checkVariableName("x", "App::VarSet" + chr(0xDCFF))

    # I-6

    def test_format(self):
        """I-6. CopyFormat is 1 and every static property of section 3.1 exists, of its type,
        in the group "Source": the format oracle for the beta's reopen gate."""
        copy = self.doc.addObject("App::VarSetCopy", "Copy")
        self.assertEqual(copy.CopyFormat, 1)
        self.assertEqual(copy.SourceKind, "None")
        self.assertEqual(copy.getEnumerationsOfProperty("SourceKind"),
                         ["FreeCAD document", "Onshape JSON", "None"])
        static = {name for name in copy.PropertiesList
                  if copy.getGroupOfProperty(name) == "Source"}
        self.assertEqual(static, set(FORMAT))
        self.assertEqual(set(copies.SOURCE_PROPERTIES), set(FORMAT))
        for name, kind in FORMAT.items():
            with self.subTest(name=name):
                self.assertEqual(copy.getTypeIdOfProperty(name), kind)
        self.assertTrue(copy.isDerivedFrom("App::VarSet"))
        self.assertEqual(copy.ViewObject, None)  # no GUI here; VarSet's view provider in the GUI

    def test_newer_format(self):
        """A copy saved with a higher CopyFormat marks the reopened document as newer: the
        notice and the save guard of decision 65 see it."""
        copy = self.doc.addObject("App::VarSetCopy", "Copy")
        copy.CopyFormat = 2
        saved = os.path.join(self.folder, "newer.FCStd")
        self.doc.saveAs(saved)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(saved)
        self.assertIn("CopyFormat 2", App.getNewerFormat(self.doc))

    # R-9

    def test_detach(self):
        """R-9. Detach, save, reopen: the variables are editable and keep their values, the
        source properties are empty. Detach is one undo step, and its undo makes the variables
        read-only again."""
        path = self.export("Studio A", STUDIO)
        copy = copies.import_studios(self.doc, [path]).copies[0]
        undoCount = self.doc.UndoCount
        copies.detach(copy)
        self.assertEqual(self.doc.UndoCount, undoCount + 1)
        self.assertNotIn("Touched", copy.State)
        self.assertNotIn("ReadOnly", copy.getPropertyStatus("Width"))
        self.doc.undo()
        self.assertEqual(copy.SourceKind, "Onshape JSON")
        self.assertEqual(copy.SourcePath, os.path.abspath(path).replace(os.sep, "/"))
        self.assertIn("ReadOnly", copy.getPropertyStatus("Width"))
        self.doc.redo()

        saved = os.path.join(self.folder, "detached.FCStd")
        self.doc.saveAs(saved)
        name = copy.Name
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(saved)
        copy = self.doc.getObject(name)
        self.assertEqual(copy.TypeId, "App::VarSetCopy")
        self.assertEqual(copy.SourceKind, "None")
        for name in ("SourcePath", "SourceRelativePath", "SourceObject", "SourceStamp",
                     "SourceRefreshed"):
            self.assertEqual(getattr(copy, name), "", name)
        self.assertEqual(copy.SourceEntries, 0)
        self.assertEqual(copy.SourceExpressions, {})
        self.assertEqual(copy.NameMap, {})
        self.assertEqual(copy.Bindings, {})
        self.assertEqual(copy.Skipped, [])
        self.assertEqual(copy.Orphans, [])
        for name, expected in STUDIO_VALUES.items():
            with self.subTest(name=name):
                self.assertNotIn("ReadOnly", copy.getPropertyStatus(name))
                self.assertAlmostEqual(value(copy, name), expected, places=9)
        # editable as any variable: the panel replaces the expression, as here
        copy.setExpression("Width", "12 mm")
        self.doc.recompute()
        self.assertAlmostEqual(copy.Gap.Value, 12 / 3 + 2, places=9)

    def test_saved_and_reopened(self):
        """An attached copy saves and reopens as it was: read-only, its source recorded."""
        path = self.export("Studio A", STUDIO)
        copy = copies.import_studios(self.doc, [path]).copies[0]
        stamp = copy.SourceStamp
        copy.addProperty("App::PropertyLength", "Later")  # from Python: no ReadOnly bit yet
        self.assertNotIn("ReadOnly", copy.getPropertyStatus("Later"))
        saved = os.path.join(self.folder, "attached.FCStd")
        self.doc.saveAs(saved)
        name = copy.Name
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(saved)
        copy = self.doc.getObject(name)
        self.assertEqual(copy.SourceKind, "Onshape JSON")
        self.assertEqual(copy.SourceStamp, stamp)
        self.assertEqual(copy.SourceRelativePath, "")  # the document had no file at the import
        self.assertIn("ReadOnly", copy.getPropertyStatus("Total"))
        self.assertIn("ReadOnly", copy.getPropertyStatus("Later"))
        self.assertAlmostEqual(copy.Total.Value, STUDIO_VALUES["Total"], places=9)


if __name__ == "__main__":
    unittest.main()
