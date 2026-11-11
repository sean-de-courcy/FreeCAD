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

notes/variables-studio.md section 6, "Import" (I-1 to I-6) and R-9; Refresh (R-1 to R-8, PR E2), a
FreeCAD document as a source (R-10, PR F) and the hierarchy of studios (ops#640 round 5) after
them, and the clashes of a local name with an imported one (ops#640, decision 317). Every
export and every source document here is made up,
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

    def test_missing_studio_value_names(self):
        """A value for a name FreeCAD can't use as a variable (#Gap, which "Variables" has
        already) gets a proposal, as a copy's variable does (review 317, 6), and name_map gives
        another name. #t, a unit name, is usable as it is (ops#640, rank 54)."""
        self.documentVariables()
        a = self.export("Studio A", [entry(variable("LENGTH", "Width", "#t * 2"),
                                           variable("LENGTH", "Depth", "#Gap * 3"))])
        values = {"t": ("LENGTH", "3 mm"), "Gap": ("LENGTH", "4 mm")}
        plan = copies.plan_import(self.doc, [a], values=values)
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.input_renames, {"Gap": "Gap_"})
        self.assertIn("The value of #Gap becomes Variables.Gap_", plan.report())
        copy = copies.import_studios(self.doc, [a], values=values,
                                     name_map={"t": "Thick"}).copies[0]
        variables = self.doc.getObject("Variables")
        self.assertAlmostEqual(variables.Thick.Value, 3)
        self.assertAlmostEqual(variables.Gap_.Value, 4)
        self.assertAlmostEqual(variables.Gap.Value, 7)  # the document's own, untouched
        self.assertEqual(copy.Bindings, {"t": "Variables.Thick", "Gap": "Variables.Gap_"})
        self.assertAlmostEqual(copy.Width.Value, 6)
        self.assertAlmostEqual(copy.Depth.Value, 12)
        self.doc.undo()
        self.assertNotIn("Thick", variables.PropertiesList)
        self.assertNotIn("Gap_", variables.PropertiesList)
        # a name given that FreeCAD can't use either is a problem, nothing made
        with self.assertRaises(ImportBlocked) as blocked:
            copies.import_studios(self.doc, [a], values=values, name_map={"t": "cos"})
        self.assertIn("#t can't be the input variable cos", str(blocked.exception))

    def test_fem_json_opens_through_fem(self):
        """A FEM mesh .json still opens through FEM when nothing says which module reads it:
        the Onshape type is registered after the modules (review 317, 7)."""
        modules = App.getImportType("json")
        self.assertIn("freecad.variables.importer", modules)
        try:
            import Fem
            from feminout import importYamlJsonMesh
        except ImportError:
            self.skipTest("no FEM")
        self.assertLess(modules.index("feminout.importYamlJsonMesh"),
                        modules.index("freecad.variables.importer"))
        mesh = Fem.FemMesh()
        for node, xyz in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)), 1):
            mesh.addNode(*xyz, node)
        mesh.addVolume([1, 2, 3, 4])
        path = os.path.join(self.folder, "Mesh.json")
        importYamlJsonMesh.write(path, mesh)
        App.loadFile(path, self.doc.Name)  # the first module's insert(), as File > Import's
        meshes = [o for o in self.doc.Objects if o.isDerivedFrom("Fem::FemMeshObject")]
        self.assertEqual(len(meshes), 1)
        self.assertEqual(meshes[0].FemMesh.NodeCount, 4)

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

    def test_bind_to_unit_named_variable(self):
        """A document variable named like a unit (Variables.H) binds like any other: qualified,
        an expression reads it as the variable, not as henry (rank 54; before, the plan refused
        it, ops#652)."""
        variables = self.doc.addObject("App::VarSet", "Variables")
        variables.addProperty("App::PropertyLength", "H")
        variables.H = "5 mm"
        self.doc.recompute()
        a = self.export(
            "Studio A",
            [entry(variable("LENGTH", "Gap", "3 mm"), variable("LENGTH", "Width", "#Gap * 2"))],
        )
        plan = copies.plan_import(self.doc, [a], skip=["Gap"], bindings={"Gap": "Variables.H"})
        self.assertFalse(any("Variables.H" in p for p in plan.problems), plan.problems)
        result = copies.import_studios(self.doc, [a], skip=["Gap"], bindings={"Gap": "Variables.H"})
        self.assertAlmostEqual(result.copies[0].Width.Value, 10)
        self.assertEqual(result.copies[0].Bindings, {"Gap": "Variables.H"})

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
        """I-5, after ops#640 rank 54. Names t and H (units in FreeCAD) are kept, as Onshape has
        them: no renames, the sibling written `t * 3` reads as the copy's own t (stored `.t`),
        and the value follows t."""
        path = self.export("Studio A", [entry(
            variable("LENGTH", "t", "2 mm"),
            variable("LENGTH", "H", "#t * 3"),
        )])
        plan = copies.plan_import(self.doc, [path])
        self.assertTrue(plan.ok, plan.problems)
        self.assertEqual(plan.renames, {})
        copy = copies.import_studios(self.doc, [path]).copies[0]
        self.assertEqual(copy.NameMap, {})
        self.assertIn("t", copy.PropertiesList)
        self.assertAlmostEqual(copy.H.Value, 6)
        self.assertEqual(expression(copy, "H").replace(" ", "").replace("(", "")[:2], ".t")
        again = copies.plan_import(self.doc, [path], name_map=dict(copy.NameMap))
        self.assertEqual(again.renames, {})

    def test_names_freecad_cant_use(self):
        """The translator's FreeCAD names are checked (review 309's note): a function, a property
        every copy has. Each gets a usable proposal; a name_map that names an unusable one is
        refused. Constants and a unit (`pi`, `e`, `mm`) are usable since ops#640 rank 54, and so
        is a cell address's shape (`W2`): the copy's `#W2 * 2` computes."""
        names = ["cos", "Label", "SourcePath", "pi", "e", "mm", "Count_", "W2"]
        path = self.export("Studio A", [entry(
            *[variable("NUMBER", name, str(i + 1)) for i, name in enumerate(names)],
            variable("NUMBER", "Twice", "#W2 * 2"))])
        plan = copies.plan_import(self.doc, [path])
        self.assertTrue(plan.ok, plan.problems)
        for name in names[:3]:
            with self.subTest(name=name):
                self.assertIn(name, plan.renames)
                self.assertEqual(App.checkVariableName(plan.renames[name], "App::VarSetCopy"),
                                 "")
        for name in names[3:]:
            self.assertNotIn(name, plan.renames)
        copy = copies.import_studios(self.doc, [path]).copies[0]
        for i, name in enumerate(names):
            self.assertEqual(value(copy, plan.renames.get(name, name)), i + 1)
        self.assertEqual(copy.Twice, 16)
        bad = copies.plan_import(self.doc, [path], name_map={"pi": "sin"})
        self.assertFalse(bad.ok)
        self.assertTrue(any("pi can't become sin" in p for p in bad.problems), bad.problems)

    def test_check_variable_name(self):
        """FreeCAD.checkVariableName, the rules of section 1.3 for Python (PR B's question)."""
        # ops#640 rank 54: unit and constant names are usable, as in Onshape
        self.assertEqual(App.checkVariableName("t"), "")
        self.assertEqual(App.checkVariableName("pi"), "")
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
        if App.GuiUp:  # VarSet's view provider in the GUI
            self.assertEqual(copy.ViewObject.TypeId, "Gui::ViewProviderVarSet")
        else:
            self.assertEqual(copy.ViewObject, None)

    def test_format_round_trip(self):
        """Every source property, non-empty and with the characters XML and maps must escape,
        saves and reopens unchanged."""
        copy = self.doc.addObject("App::VarSetCopy", "Copy")
        values = {
            "SourceKind": "Onshape JSON",
            "SourcePath": 'D:/Exports/Studio <&> "A".json',
            "SourceRelativePath": '../Exports/Studio <&> "A".json',
            "SourceObject": "1",
            "SourceEntries": 3,
            "SourceStamp": "sha256:json1:" + "0" * 64,
            "SourceRefreshed": "2026-10-17T12:00:00Z",
            "SourceExpressions": {"t": "2 mm", "Odd": 'first <&> "line"\nsecond line',
                                  "Width": "#Gap * 2"},
            "NameMap": {"t": "t_"},
            "Bindings": {"Gap": "Variables.Gap", "Lit": "12 mm"},
            "Skipped": ["Unused", "Z"],
            "Orphans": ["Old", "Older"],
        }
        for name, value in values.items():
            setattr(copy, name, value)
        saved = os.path.join(self.folder, "roundtrip.FCStd")
        self.doc.saveAs(saved)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(saved)
        copy = self.doc.getObject("Copy")
        for name, value in values.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(copy, name), value)
        self.assertEqual(copy.CopyFormat, 1)

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
        # the document had no file at the import; its save writes the relative path (E2)
        self.assertEqual(copy.SourceRelativePath, "Studio A.json")
        self.assertIn("ReadOnly", copy.getPropertyStatus("Total"))
        self.assertIn("ReadOnly", copy.getPropertyStatus("Later"))
        self.assertAlmostEqual(copy.Total.Value, STUDIO_VALUES["Total"], places=9)


# --- Refresh (ops#317 PR E2; ops#640 round 5) -----------------------------------------------------

def studio(*changes, drop=(), add=()):
    """STUDIO's entry with @a changes ((name, key, value)) applied, @a drop removed and @a add
    appended: a later export of the same made-up studio."""
    variables = [dict(v) for v in STUDIO[0]["variables"] if v["name"] not in drop]
    for name, key, new in changes:
        for v in variables:
            if v["name"] == name:
                v[key] = new
    return [entry(*(variables + list(add)))]


STATIC = set(FORMAT) | {"ExpressionEngine", "Label", "Label2", "Visibility"}


def dump(copy):
    """A canonical dump of a copy: each variable's type, expression, value, description and
    ReadOnly bit, and every source property (R-6's oracle)."""
    result = {name: getattr(copy, name) for name in FORMAT}
    for name in sorted(copy.PropertiesList):
        if name in STATIC:
            continue
        result["var " + name] = (copy.getTypeIdOfProperty(name), expression(copy, name),
                                 round(value(copy, name), 9),
                                 copy.getDocumentationOfProperty(name),
                                 "ReadOnly" in copy.getPropertyStatus(name))
    return result


class TestVariablesRefresh(unittest.TestCase):
    """Refresh of a JSON copy (notes/variables-studio.md 3.2, 3.4; section 6, R-1 to R-8). Every
    export is made up; values are worked out by hand (1 in = 25.4 mm)."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="TestVariablesRefresh")
        self.doc = App.newDocument("TestVariablesCopiesRefresh")
        self.doc.UndoMode = 1
        self.path = self.export("Studio A", STUDIO)
        self.copy = copies.import_studios(self.doc, [self.path]).copies[0]
        # a user of the copy outside it
        self.user = self.doc.addObject("App::VarSet", "User")
        self.user.addProperty("App::PropertyDistance", "Len")
        self.user.setExpression("Len", "Studio_A.Total + 1 mm")
        self.doc.recompute()

    def tearDown(self):
        copies._check_hook = None
        for name in list(App.listDocuments()):
            if name.startswith("TestVariablesCopies"):
                App.closeDocument(name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def export(self, name, data, indent=2):
        path = os.path.join(self.folder, name + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
        return path

    def rewrite(self, data, indent=2):
        """The export written again, with a later time (a re-export)."""
        self.export("Studio A", data, indent)
        later = os.stat(self.path).st_mtime + 10
        os.utime(self.path, (later, later))

    def state(self):
        return copies.source_state(self.copy).state

    def test_formatting_only(self):
        """R-1. A re-export that changes only the formatting, or only the file's time, isn't out
        of date; the check reads nothing into the document (no undo step, nothing touched)."""
        undo = self.doc.UndoCount
        self.assertEqual(self.state(), copies.UP_TO_DATE)
        self.rewrite(STUDIO, indent=None)
        self.assertEqual(self.state(), copies.UP_TO_DATE)
        self.rewrite(STUDIO, indent=8)
        self.assertEqual(self.state(), copies.UP_TO_DATE)
        plan = copies.plan_refresh(self.copy)
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.summary(), "Nothing changed at the source")
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertNotIn("Touched", self.copy.State)

    def test_added_changed_described(self):
        """R-2. Added, changed expression, changed description: the preview lists each, Refresh
        applies them in one undo step, the stamp follows and the user follows (by hand)."""
        new = variable("LENGTH", "Depth", "#Width + 5 mm", "added")
        self.rewrite(studio(("Width", "expression", "20 mm"),
                            ("Rail", "description", "the rail"), add=[new]))
        self.assertEqual(self.state(), copies.OUT_OF_DATE)
        state = copies.source_state(self.copy)
        self.assertIn("changed since the last Refresh", state.message)
        plan = copies.plan_refresh(self.copy)
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.added, ["Depth"])
        self.assertEqual(plan.changed, ["Width"])
        self.assertEqual(plan.described, ["Rail"])
        self.assertEqual(plan.summary(), "Added 1, changed 1, description changed 1")
        undo = self.doc.UndoCount
        copies.refresh(self.copy)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertIn("Refresh Studio A", self.doc.UndoNames)
        gap = 20 / 3 + 2
        total = gap * 2 + 19.05
        self.assertAlmostEqual(self.copy.Width.Value, 20, places=9)
        self.assertAlmostEqual(self.copy.Depth.Value, 25, places=9)
        self.assertAlmostEqual(self.copy.Total.Value, total, places=9)
        self.assertAlmostEqual(self.user.Len.Value, total + 1, places=9)
        self.assertEqual(self.copy.getDocumentationOfProperty("Rail"), "the rail")
        self.assertEqual(self.copy.getDocumentationOfProperty("Depth"), "added")
        self.assertIn("ReadOnly", self.copy.getPropertyStatus("Depth"))
        self.assertEqual(self.copy.SourceExpressions["Width"], "20 mm")
        self.assertEqual(self.state(), copies.UP_TO_DATE)
        self.assertEqual(copies.plan_refresh(self.copy).summary(), "Nothing changed at the source")

    def test_removed(self):
        """R-3. Removed and unused: gone. Removed and used by User: an orphan, frozen to its value
        (the Box stays valid); a sibling the orphan read then changes and the orphan doesn't. Once
        nothing uses it, the next Refresh removes it."""
        self.rewrite(studio(("Width", "expression", "40 mm"), drop=("Tilt", "Total")))
        plan = copies.plan_refresh(self.copy)
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.removed, ["Tilt"])
        self.assertEqual(plan.orphaned, {"Total": ["User.Len"]})
        self.assertEqual(plan.summary(), "Changed 1, removed 2 (used by 1 object)")
        before = self.copy.Total.Value
        copies.refresh(self.copy)
        self.assertNotIn("Tilt", self.copy.PropertiesList)
        self.assertEqual(self.copy.Orphans, ["Total"])
        self.assertIsNone(expression(self.copy, "Total"))
        self.assertIn("ReadOnly", self.copy.getPropertyStatus("Total"))
        self.assertAlmostEqual(self.copy.Gap.Value, 40 / 3 + 2, places=9)  # its sibling moved
        self.assertAlmostEqual(self.copy.Total.Value, before, places=9)  # the orphan didn't
        self.assertAlmostEqual(self.user.Len.Value, before + 1, places=9)
        self.assertNotIn("Invalid", self.user.State)
        self.assertNotIn("Total", self.copy.SourceExpressions)
        state, _message, _tip, orphans = copies.panel_state(self.copy)
        self.assertEqual(state, copies.UP_TO_DATE)
        self.assertEqual(orphans, {"Total": "removed at the source; used by User"})

        self.user.setExpression("Len", "12 mm")
        self.doc.recompute()
        plan = copies.plan_refresh(self.copy)
        self.assertEqual(plan.removed, ["Total"])
        copies.refresh(self.copy)
        self.assertNotIn("Total", self.copy.PropertiesList)
        self.assertEqual(self.copy.Orphans, [])

    def test_renamed(self):
        """R-4. A rename at the source is a removal and an addition (no identity): the old name,
        still used, becomes an orphan; the new one is added."""
        renamed = [dict(v) for v in STUDIO[0]["variables"]]
        for v in renamed:
            v["expression"] = v["expression"].replace("#Total", "#Sum")
            if v["name"] == "Total":
                v["name"] = "Sum"
        self.rewrite([entry(*renamed)])
        plan = copies.plan_refresh(self.copy)
        self.assertEqual(plan.added, ["Sum"])
        self.assertEqual(plan.orphaned, {"Total": ["User.Len"]})
        copies.refresh(self.copy)
        self.assertAlmostEqual(self.copy.Sum.Value, self.copy.Total.Value, places=9)
        self.assertEqual(self.copy.Orphans, ["Total"])

    def test_retyped(self):
        """R-5. Tilt retyped from Angle to Length: the preview lists its user; after Refresh the
        property is a Distance with the same description, and the Angle using it fails loudly
        (ops#319)."""
        self.user.addProperty("App::PropertyAngle", "Lean")
        self.user.setExpression("Lean", "Studio_A.Tilt * 2")
        self.doc.recompute()
        self.assertAlmostEqual(self.user.Lean.Value, 60, places=9)
        self.rewrite(studio(("Tilt", "type", "LENGTH"), ("Tilt", "expression", "5 mm"),
                            ("Tilt", "description", "now a length")))
        plan = copies.plan_refresh(self.copy)
        self.assertEqual(plan.retyped, {"Tilt": ("App::PropertyAngle", "App::PropertyDistance",
                                                 ["User.Lean"])})
        self.assertIn("Retyped: Tilt, Angle to Distance; used by User.Lean", plan.report())
        copies.refresh(self.copy)
        self.assertEqual(self.copy.getTypeIdOfProperty("Tilt"), "App::PropertyDistance")
        self.assertAlmostEqual(self.copy.Tilt.Value, 5, places=9)
        self.assertEqual(self.copy.getDocumentationOfProperty("Tilt"), "now a length")
        self.assertIn("ReadOnly", self.copy.getPropertyStatus("Tilt"))
        self.assertIn("Invalid", self.user.State)

    def test_undo_restores_exactly(self):
        """R-6. Undo of a Refresh with every kind of change restores the copy exactly (a canonical
        dump); redo gives the Refresh's result again."""
        before = dump(self.copy)
        self.rewrite(studio(("Width", "expression", "20 mm"), ("Rail", "description", "r"),
                            ("Tilt", "type", "NUMBER"), ("Tilt", "expression", "4"),
                            drop=("Total", "Count"),
                            add=[variable("LENGTH", "Depth", "6 mm")]))
        # Gap used #Count: it isn't defined any more
        plan = copies.plan_refresh(self.copy)
        self.assertFalse(plan.ok)
        self.assertIn("Count", plan.unresolved)
        copies.refresh(self.copy, values={"Count": ("NUMBER", "5")})
        after = dump(self.copy)
        self.assertNotEqual(after, before)
        self.assertEqual(self.copy.Bindings, {"Count": "Variables.Count"})
        self.assertAlmostEqual(self.copy.Gap.Value, 20 / 5 + 2, places=9)
        self.doc.undo()
        self.assertEqual(dump(self.copy), before)
        self.doc.redo()
        self.assertEqual(dump(self.copy), after)

    def test_overwritten(self):
        """A copied variable edited from Python is listed as changed here and overwritten; Refresh
        puts the source's expression back."""
        self.copy.setExpression("Width", "15 mm")
        self.doc.recompute()
        plan = copies.plan_refresh(self.copy)
        self.assertEqual(plan.overwritten, ["Width"])
        self.assertEqual(plan.changed, [])
        copies.refresh(self.copy)
        self.assertAlmostEqual(self.copy.Width.Value, 10, places=9)

    def test_missing_and_locate(self):
        """R-7. The source deleted: "not found", the values unchanged, Refresh refused. Locate to
        a renamed copy of the file works and the copy follows that file."""
        moved = os.path.join(self.folder, "Studio A renamed.json")
        shutil.copy(self.path, moved)
        os.remove(self.path)
        state = copies.source_state(self.copy)
        self.assertEqual(state.state, copies.NOT_FOUND)
        self.assertIn("Locate", state.message)
        with self.assertRaises(copies.RefreshBlocked):
            copies.refresh(self.copy)
        self.assertAlmostEqual(self.copy.Total.Value, STUDIO_VALUES["Total"], places=9)
        copies.refresh(self.copy, moved)
        self.assertEqual(self.copy.SourcePath, os.path.abspath(moved).replace(os.sep, "/"))
        self.assertEqual(self.state(), copies.UP_TO_DATE)

    def test_save_as_rewrites_relative_path(self):
        """R-7. The relative path is rewritten on every save, Save As to another folder too, and
        still finds the source when both are moved together."""
        os.makedirs(os.path.join(self.folder, "a"))
        os.makedirs(os.path.join(self.folder, "b", "c"))
        self.doc.saveAs(os.path.join(self.folder, "a", "model.FCStd"))
        self.assertEqual(self.copy.SourceRelativePath, "../Studio A.json")
        self.doc.saveAs(os.path.join(self.folder, "b", "c", "model.FCStd"))
        self.assertEqual(self.copy.SourceRelativePath, "../../Studio A.json")
        # the folder moved: the absolute path is gone, the relative one finds the file
        moved = tempfile.mkdtemp(prefix="TestVariablesRefreshMoved")
        try:
            os.makedirs(os.path.join(moved, "b", "c"))
            shutil.copy(self.path, moved)
            name = self.doc.Name
            App.closeDocument(name)
            shutil.copy(os.path.join(self.folder, "b", "c", "model.FCStd"),
                        os.path.join(moved, "b", "c"))
            shutil.rmtree(self.folder)
            self.doc = App.openDocument(os.path.join(moved, "b", "c", "model.FCStd"))
            copy = self.doc.getObject("Studio_A")
            self.assertEqual(copies.source_state(copy).state, copies.UP_TO_DATE)
            copies.refresh(copy)
            self.assertEqual(copy.SourcePath,
                             os.path.join(moved, "Studio A.json").replace(os.sep, "/"))
        finally:
            for name, doc in list(App.listDocuments().items()):
                if doc.FileName and os.path.normcase(os.path.abspath(doc.FileName)).startswith(
                        os.path.normcase(moved)):
                    App.closeDocument(name)
            shutil.rmtree(moved, ignore_errors=True)

    def test_entries_changed(self):
        """A file whose number of studio entries changed: entries have no identity, so the state
        is unreadable and Refresh refuses until Locate picks the entry (section 3.1)."""
        p, q, r = ([entry(variable("LENGTH", name, f"{n} mm"))] for n, name in
                   enumerate("PQR", start=1))
        two = self.export("Two", p + q)
        copy = copies.import_studios(self.doc, [two]).copies[1]
        self.assertEqual(copy.SourceObject, "1")
        self.export("Two", p + r + q)
        state = copies.source_state(copy)
        self.assertEqual(state.state, copies.UNREADABLE)
        self.assertIn("now has 3 studio entries", state.message)
        self.assertFalse(copies.plan_refresh(copy).ok)
        copies.refresh(copy, two, entry=2)
        self.assertEqual((copy.SourceObject, copy.SourceEntries), ("2", 3))
        self.assertEqual(copies.source_state(copy).state, copies.UP_TO_DATE)

    def alone(self):
        """No other copy (setUp's defines Gap too). In a transaction: a removal outside one
        leaves the next transaction uncommitted (an App quirk, not the copies')."""
        self.doc.openTransaction("Remove")
        self.doc.removeObject(self.user.Name)
        self.doc.removeObject(self.copy.Name)
        self.doc.commitTransaction()
        self.doc.recompute()

    def test_binding_kept_then_switched(self):
        """Section 2.6 on Refresh: A's #Gap bound to Variables.Gap stays bound; once a copy of B
        defines Gap, the preview says so and keeps the binding unless asked to switch."""
        self.alone()
        variables = self.doc.addObject("App::VarSet", "Variables")
        variables.addProperty("App::PropertyDistance", "Gap")
        variables.Gap = "7 mm"
        a = copies.import_studios(self.doc, [self.export("Studio X", STUDIO_A)],
                                  bindings={"Gap": "Variables.Gap"}).copies[0]
        self.assertEqual(a.Bindings, {"Gap": "Variables.Gap"})
        plan = copies.plan_refresh(a)
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.switchable, {})
        copies.import_studios(self.doc, [self.export("Studio B", STUDIO_B)])
        plan = copies.plan_refresh(a)
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.switchable, {"Gap": ("Variables.Gap", "Studio B.Gap")})
        copies.refresh(a)
        self.assertEqual(a.Bindings, {"Gap": "Variables.Gap"})
        self.assertAlmostEqual(a.Width.Value, 14, places=9)
        plan = copies.plan_refresh(a, switch=["Gap"])
        self.assertEqual(plan.changed, ["Width"])
        copies.refresh(a, switch=["Gap"])
        self.assertEqual(a.Bindings, {})
        self.assertIn("Studio_B.Gap", expression(a, "Width").replace(" ", ""))
        self.assertAlmostEqual(a.Width.Value, 6, places=9)

    def test_binding_target_gone(self):
        """A binding whose target no longer exists: the name is unresolved again, with the
        reason; a new choice resolves it."""
        self.alone()
        variables = self.doc.addObject("App::VarSet", "Variables")
        variables.addProperty("App::PropertyDistance", "Gap")
        variables.Gap = "7 mm"
        a = copies.import_studios(self.doc, [self.export("Studio X", STUDIO_A)],
                                  bindings={"Gap": "Variables.Gap"}).copies[0]
        variables.removeProperty("Gap")
        plan = copies.plan_refresh(a)
        self.assertFalse(plan.ok)
        self.assertEqual(plan.unresolved, {"Gap": ["Width"]})
        self.assertIn("it was bound to Variables.Gap", plan.report())
        copies.refresh(a, values={"Gap": ("LENGTH", "4 mm")})
        self.assertAlmostEqual(a.Width.Value, 8, places=9)

    def test_new_unresolved_name(self):
        """A variable added at the source using a name nothing defines: the same choices as the
        import; Skip leaves it out and is recorded."""
        self.rewrite(studio(add=[variable("LENGTH", "Far", "#Missing * 2")]))
        plan = copies.plan_refresh(self.copy)
        self.assertEqual(plan.unresolved, {"Missing": ["Far"]})
        copies.refresh(self.copy, skip=["Missing"])
        self.assertNotIn("Far", self.copy.PropertiesList)
        self.assertEqual(self.copy.Skipped, ["Missing"])
        # the skip is kept by the next Refresh
        self.assertTrue(copies.plan_refresh(self.copy).ok)

    def test_several_files_provider(self):
        """Copies imported together: on Refresh, A's #Gap comes from B again, as at the import
        (no binding recorded)."""
        a_path = self.export("Studio X", STUDIO_A)
        a, b = copies.import_studios(self.doc, [a_path, self.export("Studio B", STUDIO_B)]).copies
        self.export("Studio X", [entry(variable("LENGTH", "Width", "#Gap * 3"),
                                       variable("LENGTH", "Height", "5 mm"))])
        plan = copies.plan_refresh(a)
        self.assertTrue(plan.ok, plan.report())
        copies.refresh(a)
        self.assertEqual(a.Bindings, {})
        self.assertAlmostEqual(a.Width.Value, 9, places=9)

    def test_check_failure_undoes(self):
        """A value that disagrees after the Refresh (the test hook): everything is undone, no
        Refresh step is left."""
        before = dump(self.copy)
        undo = self.doc.UndoCount
        self.rewrite(studio(("Width", "expression", "20 mm")))
        copies._check_hook = lambda target, value: copies.Quantity(value.value * 2, value.dims)
        with self.assertRaises(copies.RefreshCheckFailed):
            copies.refresh(self.copy)
        self.assertEqual(dump(self.copy), before)
        self.assertEqual(self.doc.UndoCount, undo)

    def test_default_unit_kept(self):
        """A unitless Length took the import's default unit (inches); the copy doesn't record it,
        so Refresh reads it back from the written expression and keeps 5 as 127 mm."""
        path = self.export("Plain", [entry(variable("LENGTH", "Size", "5"),
                                            variable("LENGTH", "Other", "1 mm"))])
        copy = copies.import_studios(self.doc, [path], default_units={"LENGTH": "in"}).copies[0]
        self.assertAlmostEqual(copy.Size.Value, 127, places=9)
        self.export("Plain", [entry(variable("LENGTH", "Size", "5"),
                                    variable("LENGTH", "Other", "2 mm"))])
        copies.refresh(copy)
        self.assertAlmostEqual(copy.Size.Value, 127, places=9)
        self.assertAlmostEqual(copy.Other.Value, 2, places=9)

    def test_other_stamp_version(self):
        """A stamp of another canonical form's version can't be compared: never "out of date"."""
        self.copy.SourceStamp = "sha256:json0:" + "0" * 64
        self.assertEqual(self.state(), copies.OTHER_STAMP)

    def test_two_sources(self):
        """The relative and the absolute path are different files with different content: shown
        with both paths, never chosen; Refresh refuses until Locate."""
        os.makedirs(os.path.join(self.folder, "model", "exports"))
        self.doc.saveAs(os.path.join(self.folder, "model", "m.FCStd"))
        self.copy.SourceRelativePath = "exports/Studio A.json"
        with open(os.path.join(self.folder, "model", "exports", "Studio A.json"), "w") as f:
            json.dump(studio(("Width", "expression", "11 mm")), f)
        state = copies.source_state(self.copy)
        self.assertEqual(state.state, copies.TWO_SOURCES)
        self.assertIn("Two different sources", state.message)
        self.assertFalse(copies.plan_refresh(self.copy).ok)

    def test_detached_refused(self):
        copies.detach(self.copy)
        self.assertEqual(self.state(), copies.DETACHED_STATE)
        with self.assertRaises(copies.RefreshBlocked):
            copies.refresh(self.copy)


# --- A FreeCAD document as a source (ops#317 PR F; ops#640 round 5) ----------------------------

class FreeCADSource(unittest.TestCase):
    """Saved FreeCAD documents built by the tests, read as sources (section 3.3)."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="TestVariablesSource")
        self.doc = App.newDocument("TestVariablesCopiesPart")
        self.doc.UndoMode = 1

    def tearDown(self):
        copies._check_hook = None
        folder = os.path.normcase(os.path.abspath(self.folder))
        for name, doc in list(App.listDocuments().items()):
            mine = doc.FileName and os.path.normcase(os.path.abspath(doc.FileName)).startswith(
                folder)
            if name.startswith("TestVariablesCopies") or mine:
                App.closeDocument(name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def save(self, name, build, recompute=True):
        """A saved document @a name.FCStd made by build(doc), closed again; its path."""
        doc = App.newDocument("TestVariablesCopiesSource")
        build(doc)
        if recompute:
            doc.recompute()
        path = os.path.join(self.folder, name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        return path

    def edit(self, path, change, recompute=True):
        """Opens @a path, applies change(doc), saves it with a later time, closes it."""
        doc = App.openDocument(path)
        change(doc)
        if recompute:
            doc.recompute()
        doc.save()
        App.closeDocument(doc.Name)
        later = os.stat(path).st_mtime + 10
        os.utime(path, (later, later))

    @staticmethod
    def master(doc, width=100):
        """VarSet "Master": Width = width (described), Wall = Width / 10."""
        master = doc.addObject("App::VarSet", "Master")
        master.addProperty("App::PropertyLength", "Width", "Base", "the width")
        master.Width = width
        master.addProperty("App::PropertyDistance", "Wall")
        master.setExpression("Wall", "Width / 10")
        return master


class TestVariablesFreeCADSource(FreeCADSource):
    def test_types_and_refusals(self):
        """The types read (Length, Distance, Angle, Float, Bool, String) and those refused by
        name (Integer, a plain Quantity, Placement); skipped, the rest is copied with the source's
        types and saved values, read-only, its source recorded. The source document isn't
        opened. One undo removes the copy."""
        def build(doc):
            v = doc.addObject("App::VarSet", "Master")
            v.Label = "Master set"
            v.addProperty("App::PropertyLength", "Width", "Base", "the width <&>")
            v.Width = 10
            v.addProperty("App::PropertyDistance", "Gap")
            v.setExpression("Gap", "Width / 4 + 1 mm")
            v.addProperty("App::PropertyAngle", "Tilt")
            v.Tilt = 30
            v.addProperty("App::PropertyFloat", "Count")
            v.Count = 3
            v.addProperty("App::PropertyBool", "Flag")
            v.Flag = True
            v.addProperty("App::PropertyString", "Note")
            v.Note = 'a <&> "b"'
            v.addProperty("App::PropertyInteger", "N")
            v.addProperty("App::PropertyQuantity", "Q")
            v.addProperty("App::PropertyPlacement", "P")

        path = self.save("Master", build)
        self.assertEqual(copies.fcstd_varsets(path), [("Master", "Master set", 9)])
        plan = copies.plan_copy(self.doc, path, "Master")
        self.assertFalse(plan.ok)
        refused = dict(plan.refused)
        self.assertEqual(set(refused), {"N", "Q", "P"})
        self.assertIn("Integer", refused["N"])
        self.assertIn("unit isn't saved", refused["Q"])
        self.assertIn("Placement", refused["P"])
        undo = self.doc.UndoCount
        copy = copies.copy_from_fcstd(self.doc, path, "Master", skip=["N", "Q", "P"])
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(copy.Label, "Master set")
        self.assertEqual(copy.SourceKind, "FreeCAD document")
        self.assertEqual(copy.SourceObject, "Master")
        self.assertEqual(copy.SourceEntries, 0)
        self.assertTrue(copy.SourceStamp.startswith("sha256:fcstd1:"))
        self.assertEqual(copy.SourcePath, os.path.abspath(path).replace(os.sep, "/"))
        self.assertEqual(copy.Skipped, ["N", "P", "Q"])
        types = {"Width": "App::PropertyLength", "Gap": "App::PropertyDistance",
                 "Tilt": "App::PropertyAngle", "Count": "App::PropertyFloat",
                 "Flag": "App::PropertyBool", "Note": "App::PropertyString"}
        for name, kind in types.items():
            with self.subTest(name=name):
                self.assertEqual(copy.getTypeIdOfProperty(name), kind)
                self.assertIn("ReadOnly", copy.getPropertyStatus(name))
        self.assertAlmostEqual(copy.Width.Value, 10, places=9)
        self.assertAlmostEqual(copy.Gap.Value, 3.5, places=9)
        self.assertAlmostEqual(copy.Tilt.Value, 30, places=9)
        self.assertEqual(copy.Count, 3)
        self.assertIs(copy.Flag, True)
        self.assertEqual(copy.Note, 'a <&> "b"')
        self.assertEqual(copy.getDocumentationOfProperty("Width"), "the width <&>")
        self.assertEqual(expression(copy, "Gap"), "Width / 4 + 1 mm")
        self.assertIsNone(expression(copy, "Width"))
        self.assertEqual(copy.SourceExpressions["Gap"], "Width / 4 + 1 mm")
        self.assertEqual(copy.SourceExpressions["Width"], "")
        self.assertEqual([d for d in App.listDocuments() if "Source" in d], [])
        self.assertEqual(copies.source_state(copy).state, copies.UP_TO_DATE)
        self.doc.undo()
        self.assertEqual(self.doc.Objects, [])

    def test_qualified_siblings(self):
        """A sibling named by the set's name, its label or `.name` is written bare in the copy."""
        def build(doc):
            v = self.master(doc)
            v.Label = "The master"
            for name, text in (("A", "Master.Width * 2"), ("B", "<<The master>>.Width + 1 mm"),
                               ("C", ".Width - 1 mm")):
                v.addProperty("App::PropertyDistance", name)
                v.setExpression(name, text)

        copy = copies.copy_from_fcstd(self.doc, self.save("Master", build), "Master")
        self.assertEqual(expression(copy, "A"), "Width * 2")
        self.assertEqual(expression(copy, "B"), "Width + 1 mm")
        self.assertEqual(expression(copy, "C"), "Width - 1 mm")
        self.assertAlmostEqual(copy.A.Value, 200, places=9)
        self.assertAlmostEqual(copy.B.Value, 101, places=9)
        self.assertAlmostEqual(copy.C.Value, 99, places=9)

    def test_freeze_and_refresh(self):
        """R-10. Depth reads Dims.L, outside the set: unresolved, with "freeze the value" offered;
        frozen, the copy holds the file's value. Dims.L then changes in the source and is saved:
        out of date, and Refresh freezes it again. Saved touched: refused. Open with unsaved
        changes: Refresh reads the saved file."""
        def build(doc):
            dims = doc.addObject("App::VarSet", "Dims")
            dims.addProperty("App::PropertyLength", "L")
            dims.L = 40
            v = self.master(doc)
            v.addProperty("App::PropertyDistance", "Depth")
            v.setExpression("Depth", "Dims.L / 2 + Width / 100")

        path = self.save("Master", build)
        plan = copies.plan_copy(self.doc, path, "Master")
        self.assertEqual(plan.unresolved, {"Dims.L": ["Depth"]})
        self.assertEqual(plan.freezable, {"Dims.L": "40.0 mm"})
        self.assertIn("its saved value (40.0 mm)", plan.report())
        copy = copies.copy_from_fcstd(self.doc, path, "Master", freeze=["Dims.L"])
        self.assertEqual(copy.Bindings, {"Dims.L": "40.0 mm"})
        self.assertAlmostEqual(copy.Depth.Value, 21, places=9)

        self.edit(path, lambda doc: setattr(doc.getObject("Dims"), "L", 60))
        self.assertEqual(copies.source_state(copy).state, copies.OUT_OF_DATE)
        plan = copies.plan_refresh(copy)
        self.assertTrue(plan.ok, plan.report())
        self.assertIn("Dims.L is frozen again from the file: 40.0 mm becomes 60.0 mm",
                      plan.report())
        copies.refresh(copy)
        self.assertAlmostEqual(copy.Depth.Value, 31, places=9)
        self.assertEqual(copies.source_state(copy).state, copies.UP_TO_DATE)

        # saved touched: stale values, refused
        self.edit(path, lambda doc: setattr(doc.getObject("Master"), "Width", 300),
                  recompute=False)
        state = copies.source_state(copy)
        self.assertEqual(state.state, copies.UNREADABLE)
        self.assertIn("before its recompute", state.message)
        with self.assertRaises(copies.RefreshBlocked):
            copies.refresh(copy)

        # open with unsaved changes: the saved file is what Refresh reads
        self.edit(path, lambda doc: None)
        source = App.openDocument(path)
        source.getObject("Master").Width = 500
        self.assertIn("unsaved changes", copies.source_state(copy).message)
        copies.refresh(copy)
        self.assertAlmostEqual(copy.Width.Value, 300, places=9)
        App.closeDocument(source.Name)

    def test_bound_reference_not_checked(self):
        """A reference bound to a variable of this document: its users take this document's
        value, so they aren't checked against the file's."""
        def build(doc):
            dims = doc.addObject("App::VarSet", "Dims")
            dims.addProperty("App::PropertyLength", "L")
            dims.L = 40
            v = self.master(doc)
            v.addProperty("App::PropertyDistance", "Depth")
            v.setExpression("Depth", "Dims.L / 2")

        local = self.doc.addObject("App::VarSet", "Variables")
        local.addProperty("App::PropertyDistance", "L")
        local.L = 10
        self.doc.recompute()
        copy = copies.copy_from_fcstd(self.doc, self.save("Master", build), "Master",
                                      bindings={"Dims.L": "Variables.L"})
        self.assertEqual(copy.Bindings, {"Dims.L": "Variables.L"})
        self.assertAlmostEqual(copy.Depth.Value, 5, places=9)

    def test_check_against_saved_values(self):
        """The value check (section 3.3): a copy whose value disagrees with the file's (the test
        hook moves it) is undone, nothing left."""
        path = self.save("Master", self.master)
        copies._check_hook = lambda target, saved: (saved[0] + 1, saved[1])
        with self.assertRaises(copies.RefreshCheckFailed):
            copies.copy_from_fcstd(self.doc, path, "Master")
        self.assertEqual(self.doc.Objects, [])

    def test_touched_source_refused(self):
        """A source VarSet saved touched (not recomputed) may hold stale values: refused."""
        def build(doc):
            self.master(doc)
            doc.recompute()
            doc.getObject("Master").Width = 7

        plan = copies.plan_copy(self.doc, self.save("Master", build, recompute=False), "Master")
        self.assertFalse(plan.ok)
        self.assertIn("before its recompute", plan.report())

    def test_bad_sources(self):
        """Not a zip, no Document.xml, no such VarSet, an object that isn't a VarSet: refused with
        the reason."""
        junk = os.path.join(self.folder, "junk.FCStd")
        with open(junk, "w") as f:
            f.write("not a zip")
        self.assertIn("not a zip", copies.plan_copy(self.doc, junk, "Master").report())
        import zipfile

        empty = os.path.join(self.folder, "empty.FCStd")
        with zipfile.ZipFile(empty, "w") as z:
            z.writestr("Other.xml", "<x/>")
        self.assertIn("no Document.xml", copies.plan_copy(self.doc, empty, "Master").report())
        path = self.save("Master", lambda doc: (self.master(doc),
                                                doc.addObject("App::FeaturePython", "Feature")))
        self.assertIn("no VarSet Nothing", copies.plan_copy(self.doc, path, "Nothing").report())
        self.assertIn("no VarSet Feature", copies.plan_copy(self.doc, path, "Feature").report())

    def test_resave_not_out_of_date(self):
        """R-1 for a FreeCAD source: resaved unchanged, it isn't out of date."""
        path = self.save("Master", self.master)
        copy = copies.copy_from_fcstd(self.doc, path, "Master")
        self.edit(path, lambda doc: None)
        self.assertEqual(copies.source_state(copy).state, copies.UP_TO_DATE)

    def test_own_source_refused(self):
        """A copy can't be its own source (section 3.1)."""
        copy = copies.copy_from_fcstd(self.doc, self.save("Master", self.master), "Master")
        own = os.path.join(self.folder, "Part.FCStd")
        self.doc.saveAs(own)
        plan = copies.plan_refresh(copy, own, varset=copy.Name)
        self.assertIn("can't be its own source", plan.report())

    def test_copy_of_a_copy(self):
        """A source VarSet that is itself a copy: allowed, and the preview says what it copies."""
        master = self.save("Master", self.master)

        def build(doc):
            copies.copy_from_fcstd(doc, master, "Master")

        sub = self.save("Sub", build)
        plan = copies.plan_copy(self.doc, sub, "Master")
        self.assertTrue(plan.ok, plan.report())
        self.assertIn("The source is a copy of Master.FCStd", plan.report())
        copy = copies.copy_from_fcstd(self.doc, sub, "Master")
        self.assertAlmostEqual(copy.Wall.Value, 10, places=9)
        self.assertIn("copy of Master.FCStd", copies.source_state(copy).detail)

    def test_saved_and_reopened(self):
        """Compat: a copy of a FreeCAD source saves and reopens as it was (read-only, its source
        and stamp recorded, up to date)."""
        path = self.save("Master", self.master)
        copy = copies.copy_from_fcstd(self.doc, path, "Master")
        before = dump(copy)
        saved = os.path.join(self.folder, "Part.FCStd")
        self.doc.saveAs(saved)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(saved)
        copy = self.doc.getObject("Master")
        self.assertEqual(dump(copy), {**before, "SourceRelativePath": "Master.FCStd"})
        self.assertEqual(copies.source_state(copy).state, copies.UP_TO_DATE)


class TestVariablesHierarchy(FreeCADSource):
    """The team's hierarchy (ops#640 round 5): a master studio in its own file copied into a part
    file that has its own small set, and a second-level studio whose variables use the first's
    (bound to the copy's variable, section 2.6 / D1)."""

    def test_master_into_part_with_local_set(self):
        """The part's own "Variables" uses the copy of the master; a Refresh after the master
        changed moves the part's variables, and one undo takes it back."""
        master = self.save("Master", self.master)
        copy = copies.copy_from_fcstd(self.doc, master, "Master")
        local = self.doc.addObject("App::VarSet", "Variables")
        local.addProperty("App::PropertyDistance", "Post")
        local.setExpression("Post", "Master.Wall * 2 + 1 mm")
        self.doc.recompute()
        self.assertAlmostEqual(local.Post.Value, 21, places=9)

        self.edit(master, lambda doc: setattr(doc.getObject("Master"), "Width", 200))
        self.assertEqual(copies.source_state(copy).state, copies.OUT_OF_DATE)
        plan = copies.plan_refresh(copy)
        self.assertEqual(plan.changed, ["Width"])
        copies.refresh(copy)
        self.assertAlmostEqual(copy.Wall.Value, 20, places=9)
        self.assertAlmostEqual(local.Post.Value, 41, places=9)
        self.doc.undo()
        self.doc.recompute()
        self.assertAlmostEqual(local.Post.Value, 21, places=9)

    def test_second_level_json(self):
        """Studio B uses #Gap from studio A, already a copy here: B is imported alone with #Gap
        bound to A's copy. A's Refresh moves B; B's Refresh keeps the binding; A removing Gap
        leaves it as an orphan B still uses."""
        folder = self.folder
        a_path = os.path.join(folder, "Studio A.json")
        b_path = os.path.join(folder, "Studio B.json")
        with open(a_path, "w") as f:
            json.dump(STUDIO_B, f)  # Gap = 3 mm
        with open(b_path, "w") as f:
            json.dump(STUDIO_A, f)  # Width = #Gap * 2, Height = 5 mm
        a = copies.import_studios(self.doc, [a_path]).copies[0]
        b = copies.import_studios(self.doc, [b_path], bindings={"Gap": "Studio_A.Gap"}).copies[0]
        self.assertAlmostEqual(b.Width.Value, 6, places=9)
        with open(a_path, "w") as f:
            json.dump([entry(variable("LENGTH", "Gap", "4 mm"))], f)
        copies.refresh(a)
        self.assertAlmostEqual(b.Width.Value, 8, places=9)
        plan = copies.plan_refresh(b)
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.summary(), "Nothing changed at the source")
        self.assertEqual(plan.switchable, {"Gap": ("Studio_A.Gap", "Studio A.Gap")})
        copies.refresh(b)
        self.assertEqual(b.Bindings, {"Gap": "Studio_A.Gap"})
        with open(a_path, "w") as f:
            json.dump([entry(variable("LENGTH", "Other", "1 mm"))], f)
        plan = copies.plan_refresh(a)
        self.assertEqual(plan.orphaned, {"Gap": ["Studio B.Width"]})
        copies.refresh(a)
        self.assertEqual(a.Orphans, ["Gap"])
        self.assertAlmostEqual(b.Width.Value, 8, places=9)

    def test_second_level_freecad(self):
        """Sub.FCStd has a copy of the master's Main and its own set S (Height = Main.Width * 2);
        the part copies Main from the master, then S from Sub with Main.Width bound to its own
        copy of Main. The master changes: refreshing the part's Main moves its S; S's Refresh
        keeps the binding."""
        master = self.save("Master", lambda doc: self.master(doc).__setattr__("Label", "Main"))

        def sub(doc):
            m = copies.copy_from_fcstd(doc, master, "Master")
            self.assertEqual(m.Name, "Main")
            s = doc.addObject("App::VarSet", "S")
            s.addProperty("App::PropertyDistance", "Height")
            s.setExpression("Height", "Main.Width * 2")
            s.addProperty("App::PropertyDistance", "Half")
            s.setExpression("Half", "Height / 2")

        sub_path = self.save("Sub", sub)
        m = copies.copy_from_fcstd(self.doc, master, "Master")
        self.assertEqual(m.Name, "Main")
        plan = copies.plan_copy(self.doc, sub_path, "S")
        self.assertEqual(plan.unresolved, {"Main.Width": ["Height"]})
        s = copies.copy_from_fcstd(self.doc, sub_path, "S", bindings={"Main.Width": "Main.Width"})
        self.assertEqual(s.Bindings, {"Main.Width": "Main.Width"})
        self.assertEqual(expression(s, "Height"), "Main.Width * 2")
        self.assertAlmostEqual(s.Half.Value, 100, places=9)

        self.edit(master, lambda doc: setattr(doc.getObject("Master"), "Width", 150))
        copies.refresh(m)
        self.assertAlmostEqual(s.Half.Value, 150, places=9)
        plan = copies.plan_refresh(s)
        self.assertTrue(plan.ok, plan.report())
        copies.refresh(s)
        self.assertEqual(s.Bindings, {"Main.Width": "Main.Width"})
        self.assertAlmostEqual(s.Height.Value, 300, places=9)


class TestVariablesClashes(FreeCADSource):
    """A local variable and an imported one of the same name (ops#640, decision 317): `#name` is
    ambiguous for new expressions until the user chooses which it means, recorded on the copies
    (Bindings under `#name`), so a reopened file resolves the same way; existing expressions keep
    the variables they use. Made-up exports and documents; values by hand."""

    def export(self, name, data):
        path = os.path.join(self.folder, name + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

    def local(self, **values):
        """The document's own "Variables" set with @a values (name -> mm)."""
        local = self.doc.addObject("App::VarSet", "Variables")
        for name, mm in values.items():
            local.addProperty("App::PropertyDistance", name)
            setattr(local, name, mm)
        self.doc.recompute()
        return local

    def user(self, text, name="Box"):
        """A VarSet whose Len is @a text; its Len after a recompute (mm)."""
        obj = self.doc.getObject(name) or self.doc.addObject("App::VarSet", name)
        if "Len" not in obj.PropertiesList:
            obj.addProperty("App::PropertyDistance", "Len")
        obj.setExpression("Len", text)
        self.doc.recompute()
        return obj

    def assertAmbiguous(self, name="Width"):
        with self.assertRaises(Exception) as caught:
            self.user(f"#{name} * 1", "Probe")
        self.assertIn("ambiguous", str(caught.exception))
        if self.doc.getObject("Probe") is not None:
            self.doc.removeObject("Probe")

    def test_nothing_chosen_as_before(self):
        """Without a choice, a scripted import goes ahead as before: the plan lists the clash and
        warns, nothing is recorded, `#Width` is ambiguous for a new expression, and an expression
        made before the import keeps Variables.Width (7 mm)."""
        local = self.local(Width=7)
        before = self.user("#Width * 2")
        self.assertEqual(expression(before, "Len"), "Variables.Width * 2")
        path = self.export("Studio A", STUDIO)
        plan = copies.plan_import(self.doc, [path])
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.clashes, {"Width": ["Variables.Width"]})
        self.assertEqual(plan.clash_paths, {"Width": ["Studio_A.Width"]})
        self.assertEqual(plan.chosen, {})
        self.assertTrue(any("#Width stays ambiguous" in w for w in plan.warnings), plan.warnings)
        copy = copies.import_studios(self.doc, [path]).copies[0]
        self.assertEqual(copy.Bindings, {})
        self.assertAmbiguous()
        self.doc.recompute()
        self.assertAlmostEqual(before.Len.Value, 14, places=9)
        self.assertEqual(local.InList, [before])

    def test_use_import(self):
        """"Use Studio A.json": the copy records its own Width; `#Width` then means it (10 mm);
        the expression made before keeps Variables.Width. One undo removes the copy and the
        choice: `#Width` is the local one again."""
        self.local(Width=7)
        before = self.user("#Width * 2")
        path = self.export("Studio A", STUDIO)
        copy = copies.import_studios(self.doc, [path], clashes=copies.IMPORT).copies[0]
        self.assertEqual(copy.Bindings, {"#Width": "Studio_A.Width"})
        after = self.user("#Width * 2", "After")
        self.assertEqual(expression(after, "Len"), "Studio_A.Width * 2")
        self.assertAlmostEqual(after.Len.Value, 20, places=9)
        self.assertAlmostEqual(before.Len.Value, 14, places=9)
        self.doc.removeObject("After")
        self.doc.undo()
        self.assertIsNone(self.doc.getObject("Studio_A"))
        again = self.user("#Width * 3", "Again")
        self.assertEqual(expression(again, "Len"), "Variables.Width * 3")

    def test_use_local(self):
        """"Use local": `#Width` means Variables.Width (7 mm); the copy's Gap, defined only
        there, is `#Gap` as before."""
        self.local(Width=7)
        path = self.export("Studio A", STUDIO)
        copy = copies.import_studios(self.doc, [path], clashes=copies.LOCAL).copies[0]
        self.assertEqual(copy.Bindings, {"#Width": "Variables.Width"})
        after = self.user("#Width + #Gap")
        self.assertEqual(expression(after, "Len"), "Variables.Width + Studio_A.Gap")
        self.assertAlmostEqual(after.Len.Value, 7 + 10 / 3 + 2, places=9)

    def test_pick(self):
        """"Pick", per name: Width from the file, Gap the local one; a pick that names neither
        is a problem, and one for a name no local set has only warns."""
        self.local(Width=7, Gap=1)
        path = self.export("Studio A", STUDIO)
        plan = copies.plan_import(self.doc, [path], clashes={"Width": "Nothing.Width"})
        self.assertFalse(plan.ok)
        self.assertTrue(any("#Width can't mean Nothing.Width" in p for p in plan.problems),
                        plan.problems)
        plan = copies.plan_import(self.doc, [path], clashes={"Tilt": copies.LOCAL})
        self.assertTrue(any("#Tilt isn't defined by one local set" in w for w in plan.warnings),
                        plan.warnings)
        copy = copies.import_studios(self.doc, [path], clashes={
            "Width": "Studio_A.Width", "Gap": copies.LOCAL}).copies[0]
        self.assertEqual(copy.Bindings, {"#Width": "Studio_A.Width", "#Gap": "Variables.Gap"})
        after = self.user("#Width + #Gap")
        self.assertEqual(expression(after, "Len"), "Studio_A.Width + Variables.Gap")
        self.assertAlmostEqual(after.Len.Value, 11, places=9)

    def test_saved_and_reopened(self):
        """The choice is saved with the copy: the reopened file's `#Width` means the same."""
        self.local(Width=7)
        path = self.export("Studio A", STUDIO)
        copies.import_studios(self.doc, [path], clashes=copies.IMPORT)
        saved = os.path.join(self.folder, "Part.FCStd")
        self.doc.saveAs(saved)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(saved)
        after = self.user("#Width * 2")
        self.assertEqual(expression(after, "Len"), "Studio_A.Width * 2")
        self.assertAlmostEqual(after.Len.Value, 20, places=9)

    def test_local_after_import(self):
        """A local Width made after the import, with copies.choose() in its transaction (the
        panel's add): `#Width` means the local one; one undo takes both back. choose() refuses a
        path that isn't a variable of that name, and a name no copy defines."""
        path = self.export("Studio A", STUDIO)
        copy = copies.import_studios(self.doc, [path]).copies[0]
        self.doc.openTransaction("Add Width")
        self.local(Width=7)
        copies.choose(self.doc, "Width", "Variables.Width")
        self.doc.commitTransaction()
        self.assertEqual(copy.Bindings, {"#Width": "Variables.Width"})
        self.assertEqual(expression(self.user("#Width"), "Len"), "Variables.Width")
        self.doc.removeObject("Box")
        self.doc.undo()
        self.assertEqual(copy.Bindings, {})
        self.assertIsNone(self.doc.getObject("Variables"))
        for name, path in (("Width", "Variables.Width"), ("Width", "Studio_A.Gap"),
                           ("Nothing", "Studio_A.Nothing")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                copies.choose(self.doc, name, path)

    def test_records_agree(self):
        """Copies of the name must agree: a second import with "Use import" moves the first
        copy's record to the new copy; a third copy imported without a choice makes `#Width`
        ambiguous again."""
        self.local(Width=7)
        a = copies.import_studios(self.doc, [self.export("Studio A", STUDIO)],
                                  clashes=copies.LOCAL).copies[0]
        b_path = self.export("Studio B", [entry(variable("LENGTH", "Width", "4 mm"))])
        plan = copies.plan_import(self.doc, [b_path], clashes={"Width": "Studio_A.Width"})
        self.assertTrue(plan.ok, plan.report())  # another copy of the name can be picked
        b = copies.import_studios(self.doc, [b_path], clashes=copies.IMPORT).copies[0]
        self.assertEqual(a.Bindings["#Width"], "Studio_B.Width")
        self.assertEqual(b.Bindings, {"#Width": "Studio_B.Width"})
        self.assertAlmostEqual(self.user("#Width").Len.Value, 4, places=9)
        copies.import_studios(self.doc, [self.export("Studio C", [entry(
            variable("LENGTH", "Width", "5 mm"))])])
        self.assertAmbiguous()

    def test_two_local_sets(self):
        """Two local sets define Width: `#Width` is ambiguous among the document's own already,
        and no choice of the copy's settles it (a warning; a choice for it isn't used). A choice
        made between one local set and the copy doesn't cover a second local set made later:
        `#Width` is ambiguous again."""
        self.local(Width=7)
        other = self.doc.addObject("App::VarSet", "Other")
        other.addProperty("App::PropertyDistance", "Width")
        other.Width = 8
        self.doc.recompute()
        path = self.export("Studio A", STUDIO)
        plan = copies.plan_import(self.doc, [path], clashes=copies.LOCAL)
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.clashes, {})
        self.assertTrue(any("#Width is ambiguous here already" in w for w in plan.warnings),
                        plan.warnings)
        copy = copies.import_studios(self.doc, [path],
                                     clashes={"Width": "Other.Width"}).copies[0]
        self.assertEqual(copy.Bindings, {})
        self.assertAmbiguous()
        self.doc.removeObject(copy.Name)
        self.doc.removeObject("Other")
        self.doc.recompute()
        copies.import_studios(self.doc, [path], clashes=copies.LOCAL)
        self.assertEqual(expression(self.user("#Width"), "Len"), "Variables.Width")
        self.doc.removeObject("Box")
        third = self.doc.addObject("App::VarSet", "Third")
        third.addProperty("App::PropertyDistance", "Width")
        self.assertAmbiguous()

    def test_refresh_new_clash(self):
        """A Refresh that brings a name a local set has: the preview lists it; the choice of an
        earlier name is kept and not asked again; one undo takes the Refresh back with its
        choice."""
        self.local(Width=7, Depth=2)
        path = self.export("Studio A", STUDIO)
        copy = copies.import_studios(self.doc, [path], clashes=copies.LOCAL).copies[0]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(studio(add=[variable("LENGTH", "Depth", "6 mm")]), f)
        later = os.stat(path).st_mtime + 10
        os.utime(path, (later, later))
        plan = copies.plan_refresh(copy)
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.clashes, {"Depth": ["Variables.Depth"]})
        copies.refresh(copy, clashes=copies.IMPORT)
        self.assertEqual(copy.Bindings, {"#Width": "Variables.Width", "#Depth": "Studio_A.Depth"})
        self.assertEqual(expression(self.user("#Width + #Depth"), "Len"),
                         "Variables.Width + Studio_A.Depth")
        self.doc.removeObject("Box")
        self.doc.undo()
        self.assertEqual(copy.Bindings, {"#Width": "Variables.Width"})
        self.assertNotIn("Depth", copy.PropertiesList)

    def test_copy_from_freecad_file(self):
        """Copy variables from a FreeCAD file whose VarSet defines Width, as the part's own set
        does: the same choices."""
        master = self.save("Master", self.master)
        self.local(Width=7)
        plan = copies.plan_copy(self.doc, master, "Master")
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.clashes, {"Width": ["Variables.Width"]})
        self.assertEqual(plan.clash_paths, {"Width": ["Master.Width"]})
        copy = copies.copy_from_fcstd(self.doc, master, "Master", clashes=copies.IMPORT)
        self.assertEqual(copy.Bindings, {"#Width": "Master.Width"})
        self.assertAlmostEqual(self.user("#Width").Len.Value, 100, places=9)

    def test_detach_keeps_choice(self):
        """Detach clears the source's bindings but not the record of what `#Width` meant; the
        detached set is a local one, though (review R6-6): with the document's own Width as well,
        `#Width` is ambiguous among two local sets, which no choice settles, and new expressions
        write the full path."""
        self.local(Width=7)
        copy = copies.import_studios(self.doc, [self.export("Studio A", STUDIO)],
                                     clashes=copies.IMPORT).copies[0]
        self.assertEqual(expression(self.user("#Width"), "Len"), "Studio_A.Width")
        self.doc.removeObject("Box")
        copies.detach(copy)
        self.assertEqual(copy.Bindings, {"#Width": "Studio_A.Width"})
        self.assertEqual(copies.local_holders(self.doc, "Width"),
                         ["Variables.Width", "Studio_A.Width"])
        self.assertAmbiguous()

    def test_import_warns_on_a_detached_copys_name(self):
        """Review R6-6: a detached copy's variables are local ones. Importing a file that defines
        Width, which a detached copy (Studio A, detached) defines: the plan lists the clash with
        the detached set as the local one; "Use import" makes `#Width` the new copy's (5 mm),
        "Use local" the detached set's (10 mm); an import with nothing chosen leaves it
        ambiguous, as beside any local set."""
        old = copies.import_studios(self.doc, [self.export("Studio A", STUDIO)]).copies[0]
        copies.detach(old)
        self.assertEqual(copies.copies_defining(self.doc, "Width"), [])
        path = self.export("Studio B", [entry(variable("LENGTH", "Width", "5 mm"))])
        plan = copies.plan_import(self.doc, [path])
        self.assertTrue(plan.ok, plan.report())
        self.assertEqual(plan.clashes, {"Width": ["Studio_A.Width"]})
        self.assertEqual(plan.clash_paths, {"Width": ["Studio_B.Width"]})
        self.assertTrue(any("#Width stays ambiguous" in w for w in plan.warnings), plan.warnings)
        new = copies.import_studios(self.doc, [path], clashes=copies.IMPORT).copies[0]
        self.assertEqual(new.Bindings, {"#Width": "Studio_B.Width"})
        self.assertAlmostEqual(self.user("#Width").Len.Value, 5, places=9)
        self.assertEqual(expression(self.user("#Width"), "Len"), "Studio_B.Width")
        self.doc.removeObject("Box")
        self.doc.removeObject(new.Name)
        self.doc.recompute()
        new = copies.import_studios(self.doc, [path], clashes=copies.LOCAL).copies[0]
        self.assertEqual(new.Bindings, {"#Width": "Studio_A.Width"})
        self.assertEqual(expression(self.user("#Width"), "Len"), "Studio_A.Width")
        self.assertAlmostEqual(self.user("#Width").Len.Value, 10, places=9)
        self.doc.removeObject("Box")
        self.doc.removeObject(new.Name)
        self.doc.recompute()
        copies.import_studios(self.doc, [path])
        self.assertAmbiguous()


class TestVariablesPaths(unittest.TestCase):
    """The paths of a FreeCAD expression (copies.fc_paths), which the FreeCAD source and the
    search for users read."""

    def paths(self, text):
        return [(p.text, p.document, p.obj, p.by_label, p.props, p.local)
                for p in copies.fc_paths(text)]

    def test_forms(self):
        self.assertEqual(self.paths("Width * 2 + .Gap - VarSet.Rail"), [
            ("Width", None, None, False, ["Width"], False),
            (".Gap", None, None, False, ["Gap"], True),
            ("VarSet.Rail", None, "VarSet", False, ["Rail"], False)])
        self.assertEqual(self.paths("<<My set>>.Width + Doc#Box.Length + <<D o>>#<<B x>>.Height"),
                         [("<<My set>>.Width", None, "My set", True, ["Width"], False),
                          ("Doc#Box.Length", "Doc", "Box", False, ["Length"], False),
                          ("<<D o>>#<<B x>>.Height", "D o", "B x", True, ["Height"], False)])
        self.assertEqual(self.paths("sqrt(Box.Placement.Base.x) * 1 mm + <<text>>"), [
            ("Box.Placement.Base.x", None, "Box", False, ["Placement", "Base", "x"], False),
            ("mm", None, None, False, ["mm"], False)])
        self.assertEqual(self.paths("2.5e3 + .5"), [])
        self.assertEqual(self.paths("Box@.Length"),
                         [("Box@.Length", None, "Box", False, ["Length"], False)])


if __name__ == "__main__":
    unittest.main()
