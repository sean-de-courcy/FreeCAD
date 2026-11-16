# SPDX-License-Identifier: LGPL-2.1-or-later

"""The file carries a part's material (FreeCAD-CH, ops#696; design E1 of the ops repo's
part-properties-design note).

Each test saves a designed document (10 mm cubes) here and opens it in a child FreeCADCmd whose
settings folder is a second one, made by the test: empty, or holding a card the test writes. The
expected values are geometric: a 10 mm cube of 1990 kg/m^3 weighs 1000 mm^3 * 1.99e-6 kg/mm^3.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile

import FreeCAD
import Materials

DENSITY_MODEL = "454661e5-265b-4320-8e6f-fcf6223ac3af"
DEFAULT_UUID = "7f9fd73b-50c9-41d8-b7b2-575a030c1eeb"
STEEL_UUID = "90bbd8ef-8623-4d78-b3bf-e0bdb9b74dd3"  # Standard/Metal/Steel/Steel-Generic.FCMat
PLASTER = "E1 test plaster"
PLASTER_DENSITY = 1990.0  # kg/m^3
CUBE_VOLUME = 1000.0  # mm^3
TEST_MODEL = "34d0583d-f999-49ba-99e6-aa40bd5c3a6b"  # Resources/Models/Test: every value type

CHILD = r'''
import json, os
import FreeCAD, Materials

def density(mat, unit):
    if not mat.hasPhysicalProperty("Density"):
        return None
    value = mat.getPhysicalValue("Density")
    if value is None or value == "":
        return None
    try:
        return FreeCAD.Units.Quantity(value).getValueAs(unit).Value
    except Exception:  # an empty value reads as a dimensionless 0
        return None

out = {"userAppData": FreeCAD.getUserAppDataDir(), "objects": {}}
if os.environ.get("E1_EXEC"):
    exec(os.environ["E1_EXEC"])
doc = FreeCAD.openDocument(os.environ["E1_DOC"]) if os.environ.get("E1_DOC") else None
if doc:
    for obj in doc.Objects:
        entry = {"null": obj.Shape.isNull(), "volume": None if obj.Shape.isNull() else obj.Shape.Volume}
        mat = obj.ShapeMaterial
        entry["uuid"] = mat.UUID
        entry["name"] = mat.Name
        entry["density"] = density(mat, "kg/m^3")
        raw = mat.getPhysicalValue("Density") if mat.hasPhysicalProperty("Density") else None
        entry["densityText"] = None if raw is None else str(raw)
        if mat.hasPhysicalProperty("TestInteger"):
            entry["integer"] = mat.getPhysicalValue("TestInteger")
        perMm3 = density(mat, "kg/mm^3")
        entry["mass"] = None if perMm3 is None or entry["volume"] is None else entry["volume"] * perMm3
        out["objects"][obj.Name] = entry
    if os.environ.get("E1_RESAVE"):
        doc.saveAs(os.environ["E1_RESAVE"])
library = os.path.join(FreeCAD.getUserAppDataDir(), "Material")
out["learned"] = sorted(os.listdir(library)) if os.path.isdir(library) else []
if os.environ.get("E1_UUID"):
    try:
        card = Materials.MaterialManager().getMaterial(os.environ["E1_UUID"])
        out["library"] = {"name": card.Name, "density": density(card, "kg/m^3")}
        if card.hasPhysicalProperty("TestInteger"):
            out["library"]["integer"] = card.getPhysicalValue("TestInteger")
    except Exception as e:
        out["library"] = {"error": str(e)}
with open(os.environ["E1_OUT"], "w", encoding="utf-8") as f:
    json.dump(out, f)
'''


def _freecadCmd():
    names = ("FreeCADCmd.exe", "FreeCADCmd") if sys.platform == "win32" else ("FreeCADCmd",)
    packaged = FreeCAD.ConfigGet("ExeName") + "Cmd"
    if sys.platform == "win32":
        names = (packaged + ".exe",) + names
    base = os.path.basename(sys.executable).lower()
    if base.startswith("freecadcmd") or base.startswith(packaged.lower()):
        return sys.executable
    for folder in ("bin", "MacOS", ""):
        for name in names:
            path = os.path.join(FreeCAD.getHomePath(), folder, name)
            if os.path.isfile(path):
                return path
    raise FileNotFoundError("FreeCADCmd next to " + FreeCAD.getHomePath())


class MaterialInFileTestCases(unittest.TestCase):
    """A saved document carries its parts' materials"""

    def setUp(self):
        self.work = os.path.abspath(tempfile.mkdtemp(prefix="e1-material-"))
        self.docs = []

    def tearDown(self):
        for doc in self.docs:
            try:
                FreeCAD.closeDocument(doc.Name)
            except Exception:
                pass
        shutil.rmtree(self.work, ignore_errors=True)

    # -- helpers ------------------------------------------------------------------------------

    def newDoc(self, name):
        doc = FreeCAD.newDocument(name)
        self.docs.append(doc)
        return doc

    def cube(self, doc, name, x=0.0):
        box = doc.addObject("Part::Box", name)
        box.Length = box.Width = box.Height = 10
        box.Placement.Base = FreeCAD.Vector(x, 0, 0)
        return box

    def plaster(self):
        """A material made in this session: in no library on any computer"""
        mat = Materials.Material()
        mat.Name = PLASTER
        mat.addPhysicalModel(DENSITY_MODEL)
        mat.setPhysicalValue("Density", "{} kg/m^3".format(PLASTER_DENSITY))
        return mat

    def settingsFolder(self, name):
        """A second settings folder, absolute and existing (empty)"""
        folder = os.path.join(self.work, name)
        os.makedirs(folder)
        return folder

    def child(self, home, doc=None, uuidToResolve=None, resave=None, code=None):
        """Opens doc (and resolves a UUID) in a FreeCADCmd whose settings folder is home; resave
        saves the opened document there; code runs first"""
        try:
            freecadCmd = _freecadCmd()
        except FileNotFoundError as e:
            self.skipTest(str(e))
        script = os.path.join(self.work, "child.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(CHILD)
        out = os.path.join(self.work, "child-{}.json".format(uuid.uuid4().hex[:8]))
        env = dict(os.environ)
        env["FREECAD_USER_HOME"] = home
        for inherited in ("FREECAD_USER_DATA", "FREECAD_USER_TEMP"):
            env.pop(inherited, None)  # they override FREECAD_USER_HOME's folders
        env["E1_OUT"] = out
        for own in ("E1_DOC", "E1_UUID", "E1_RESAVE", "E1_EXEC"):
            env.pop(own, None)
        if resave:
            env["E1_RESAVE"] = resave
        if code:
            env["E1_EXEC"] = code
        if doc:
            env["E1_DOC"] = doc
        if uuidToResolve:
            env["E1_UUID"] = uuidToResolve
        proc = subprocess.run(
            [freecadCmd, script],
            env=env,
            cwd=self.work,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        log = proc.stdout.decode("utf-8", "replace")
        self.assertTrue(os.path.isfile(out), "the child wrote no result:\n" + log[-3000:])
        with open(out, encoding="utf-8") as f:
            return json.load(f), log

    def assertCube(self, entry, label):
        self.assertFalse(entry["null"], label + " was not restored")
        self.assertAlmostEqual(entry["volume"], CUBE_VOLUME, places=6, msg=label)

    def documentXml(self, path):
        with zipfile.ZipFile(path) as z:
            return z.read("Document.xml").decode("utf-8")

    def rewriteDocumentXml(self, path, change):
        """Rewrites the file's Document.xml through change(text)"""
        tmp = path + ".tmp"
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "Document.xml":
                    data = change(data.decode("utf-8")).encode("utf-8")
                dst.writestr(item, data)
        os.replace(tmp, path)

    # -- tests ---------------------------------------------------------------------------------

    def testFileHoldsTheMaterial(self):
        """The saved element holds the name, the density model and the density in internal units"""
        doc = self.newDoc("E1Xml")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        doc.recompute()
        path = os.path.join(self.work, "xml.FCStd")
        doc.saveAs(path)
        xml = self.documentXml(path)
        element = re.search(
            r'<PropertyMaterial uuid="{}"[^>]*>.*?</PropertyMaterial>'.format(
                re.escape(box.ShapeMaterial.UUID)
            ),
            xml,
            re.S,
        )
        self.assertIsNotNone(element, "no PropertyMaterial element for the box")
        text = element.group(0)
        self.assertIn('name="{}"'.format(PLASTER), text)
        self.assertIn('<Model uuid="{}"/>'.format(DENSITY_MODEL), text)
        value = re.search(r'<Value name="Density" value="([^"]+)" unit="kg/mm\^3"/>', text)
        self.assertIsNotNone(value, text)
        self.assertAlmostEqual(float(value.group(1)), PLASTER_DENSITY * 1e-9, delta=1e-18)

    def testSessionMaterialOnAnotherComputer(self):
        """A session-made material reopens under a second, empty settings folder: same name,
        density and mass; the material is then in that folder's library for new documents"""
        doc = self.newDoc("E1Session")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        made = box.ShapeMaterial.UUID
        later = self.cube(doc, "Later", 20)
        later.ShapeMaterial = Materials.MaterialManager().getMaterial(STEEL_UUID)
        doc.recompute()
        path = os.path.join(self.work, "session.FCStd")
        doc.saveAs(path)

        home = self.settingsFolder("empty-settings")
        result, log = self.child(home, path)
        entry = result["objects"]["Box"]
        self.assertCube(entry, "Box")
        self.assertEqual(entry["uuid"], made, log[-2000:])
        self.assertEqual(entry["name"], PLASTER)
        self.assertAlmostEqual(entry["density"], PLASTER_DENSITY, places=9)
        self.assertAlmostEqual(entry["mass"], CUBE_VOLUME * PLASTER_DENSITY * 1e-9, places=15)
        self.assertCube(result["objects"]["Later"], "Later")
        self.assertEqual(result["objects"]["Later"]["uuid"], STEEL_UUID)
        self.assertNotIn("Material not found", log)

        # learned on open: a new session with the same settings folder resolves the UUID
        again, log = self.child(home, None, made)
        self.assertEqual(again["library"].get("name"), PLASTER, log[-2000:])
        self.assertAlmostEqual(again["library"]["density"], PLASTER_DENSITY, places=9)

    def testUnknownReferenceWithoutValues(self):
        """A reference nothing resolves and no stored values (a file from before E1): the part
        gets Default with a warning that names it, and every later object is restored"""
        doc = self.newDoc("E1Unknown")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        steel = self.cube(doc, "Box2", 20)
        steel.ShapeMaterial = Materials.MaterialManager().getMaterial(STEEL_UUID)
        self.cube(doc, "Box3", 40)
        doc.recompute()
        path = os.path.join(self.work, "unknown.FCStd")
        doc.saveAs(path)
        unknown = str(uuid.uuid4())

        def oldFormat(xml):
            # each element back to the uuid-only form; the plaster's reference becomes unknown
            def one(match):
                ref = unknown if match.group(1) == box.ShapeMaterial.UUID else match.group(1)
                return '<PropertyMaterial uuid="{}"/>'.format(ref)

            return re.sub(
                r'<PropertyMaterial uuid="([^"]+)"[^>]*?(?:/>|>.*?</PropertyMaterial>)',
                one,
                xml,
                flags=re.S,
            )

        self.rewriteDocumentXml(path, oldFormat)
        self.assertNotIn("<Value ", self.documentXml(path))

        result, log = self.child(self.settingsFolder("empty-settings"), path)
        objects = result["objects"]
        self.assertEqual(objects["Box"]["uuid"], DEFAULT_UUID)
        self.assertCube(objects["Box"], "Box")
        self.assertCube(objects["Box2"], "Box2")
        self.assertEqual(objects["Box2"]["uuid"], STEEL_UUID)
        self.assertCube(objects["Box3"], "Box3")
        warning = [
            line
            for line in log.splitlines()
            if unknown in line and "Box" in line and "Default" in line
        ]
        self.assertTrue(warning, "no warning naming the part:\n" + log[-2000:])
        self.assertNotIn("Invalid Document.xml", log)

    def testChangedLibraryCardFileWins(self):
        """A library card of the same UUID whose density changed after the save: the file's density
        stays, and the card is left as it is"""
        doc = self.newDoc("E1Changed")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        made = box.ShapeMaterial.UUID
        doc.recompute()
        path = os.path.join(self.work, "changed.FCStd")
        doc.saveAs(path)

        home = self.settingsFolder("card-settings")
        # where a FreeCAD with this settings folder keeps its user library
        probe, _ = self.child(home)
        library = os.path.join(probe["userAppData"], "Material")
        os.makedirs(library, exist_ok=True)
        card = os.path.join(library, "E1 changed card.FCMat")
        with open(card, "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "General:\n"
                '  UUID: "{}"\n'
                '  Name: "E1 changed card"\n'
                "Models:\n"
                "  Density:\n"
                "    UUID: '{}'\n"
                '    Density: "2500 kg/m^3"\n'.format(made, DENSITY_MODEL)
            )
        with open(card, encoding="utf-8") as f:
            before = f.read()

        result, log = self.child(home, path, made)
        self.assertEqual(result["library"].get("density"), 2500.0, log[-2000:])
        entry = result["objects"]["Box"]
        self.assertEqual(entry["uuid"], made)
        self.assertEqual(entry["name"], PLASTER)
        self.assertAlmostEqual(entry["density"], PLASTER_DENSITY, places=9)
        self.assertAlmostEqual(entry["mass"], CUBE_VOLUME * PLASTER_DENSITY * 1e-9, places=15)
        with open(card, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(
            sorted(os.listdir(library)), ["E1 changed card.FCMat"], "nothing learned over a card"
        )

    def testLibraryMaterialRoundTrip(self):
        """A library material saved and reopened in this process is the library's material"""
        doc = self.newDoc("E1Library")
        box = self.cube(doc, "Box")
        steel = Materials.MaterialManager().getMaterial(STEEL_UUID)
        box.ShapeMaterial = steel
        doc.recompute()
        path = os.path.join(self.work, "library.FCStd")
        doc.saveAs(path)
        FreeCAD.closeDocument(doc.Name)
        self.docs.remove(doc)
        reopened = FreeCAD.openDocument(path)
        self.docs.append(reopened)
        mat = reopened.getObject("Box").ShapeMaterial
        self.assertEqual(mat.UUID, STEEL_UUID)
        self.assertEqual(mat.Name, steel.Name)
        self.assertEqual(
            sorted(mat.PhysicalModels), sorted(steel.PhysicalModels)
        )
        self.assertEqual(
            str(mat.getPhysicalValue("Density")), str(steel.getPhysicalValue("Density"))
        )

    def testValuesThatDoNotFitAreReported(self):
        """A stored value whose unit does not fit the model and a model unknown here: the part keeps
        the rest of its material, a warning names what was not restored, the document is whole"""
        doc = self.newDoc("E1Unfit")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        made = box.ShapeMaterial.UUID
        self.cube(doc, "Box2", 20)
        doc.recompute()
        path = os.path.join(self.work, "unfit.FCStd")
        doc.saveAs(path)
        unknownModel = str(uuid.uuid4())

        def unfit(xml):
            start = xml.index('<PropertyMaterial uuid="{}"'.format(made))
            end = xml.index("</PropertyMaterial>", start)
            element = xml[start:end]
            changed = element.replace('models="1"', 'models="2"', 1)
            changed = changed.replace(
                '<Model uuid="{}"/>'.format(DENSITY_MODEL),
                '<Model uuid="{}"/>\n<Model uuid="{}"/>'.format(DENSITY_MODEL, unknownModel),
                1,
            )
            changed = changed.replace('unit="kg/mm^3"', 'unit="mm"', 1)
            self.assertNotEqual(changed, element)
            return xml[:start] + changed + xml[end:]

        self.rewriteDocumentXml(path, unfit)
        result, log = self.child(self.settingsFolder("empty-settings"), path)
        entry = result["objects"]["Box"]
        self.assertEqual(entry["uuid"], made)
        self.assertEqual(entry["name"], PLASTER)
        self.assertIsNone(entry["density"])
        text = entry["densityText"] or ""
        self.assertNotIn("mm", text, "the density kept the unit that does not fit")
        self.assertNotIn("1.99", text)
        self.assertCube(entry, "Box")
        self.assertCube(result["objects"]["Box2"], "Box2")
        warning = [line for line in log.splitlines() if "not restored" in line and "Box" in line]
        self.assertTrue(warning, log[-2000:])
        self.assertIn("Density", warning[0])
        self.assertIn(unknownModel, warning[0])
        self.assertEqual(result["learned"], [], "a partly restored material became a card")

    def testQuantityTextIsKeptAsText(self):
        """A density whose text is not a quantity is saved as that text, not as 0"""
        doc = self.newDoc("E1Text")
        box = self.cube(doc, "Box")
        mat = self.plaster()
        mat.setPhysicalValue("Density", "about two")
        box.ShapeMaterial = mat
        doc.recompute()
        path = os.path.join(self.work, "text.FCStd")
        doc.saveAs(path)
        self.assertIn('<Value name="Density" value="about two"/>', self.documentXml(path))
        result, log = self.child(self.settingsFolder("empty-settings"), path)
        entry = result["objects"]["Box"]
        self.assertEqual(entry["name"], PLASTER, log[-2000:])
        self.assertEqual(entry["densityText"], "about two")
        self.assertIsNone(entry["density"])

    # -- the desktop's persistence review (ops#675 comment 6821046237) --------------------------

    def elementOf(self, xml, materialUuid):
        start = xml.index('<PropertyMaterial uuid="{}"'.format(materialUuid))
        end = xml.index("</PropertyMaterial>", start) + len("</PropertyMaterial>")
        return start, end

    def editElement(self, path, materialUuid, edit):
        def change(xml):
            start, end = self.elementOf(xml, materialUuid)
            element = xml[start:end]
            changed = edit(element)
            self.assertNotEqual(changed, element)
            return xml[:start] + changed + xml[end:]

        self.rewriteDocumentXml(path, change)

    def testControlCharactersStaySafe(self):
        """A material name and a string value with control characters: the file is valid XML and
        the whole document reopens"""
        import xml.dom.minidom

        doc = self.newDoc("E1Control")
        box = self.cube(doc, "Box")
        mat = self.plaster()
        mat.Name = "E1\x01plaster\x1b"
        mat.addPhysicalModel(TEST_MODEL)
        mat.setPhysicalValue("TestString", "a\x0bb")
        box.ShapeMaterial = mat
        self.cube(doc, "Box2", 20)
        doc.recompute()
        path = os.path.join(self.work, "control.FCStd")
        doc.saveAs(path)
        xml.dom.minidom.parseString(self.documentXml(path).encode("utf-8"))  # raises if invalid

        result, log = self.child(self.settingsFolder("empty-settings"), path)
        entry = result["objects"]["Box"]
        self.assertCube(entry, "Box")
        self.assertCube(result["objects"]["Box2"], "Box2")
        self.assertEqual(entry["name"], "E1_plaster_", log[-2000:])
        self.assertAlmostEqual(entry["density"], PLASTER_DENSITY, places=9)

    def testCountsAboveTheChildren(self):
        """Counts above the real children (a hand-edited file): the children there are restored, a
        warning says what is missing, the rest of the document is read, nothing is learned"""
        doc = self.newDoc("E1Counts")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        made = box.ShapeMaterial.UUID
        later = self.cube(doc, "Box2", 20)
        later.ShapeMaterial = Materials.MaterialManager().getMaterial(STEEL_UUID)
        doc.recompute()
        path = os.path.join(self.work, "counts.FCStd")
        doc.saveAs(path)
        self.editElement(
            path,
            made,
            lambda e: e.replace('models="1"', 'models="5"').replace('values="1"', 'values="9"'),
        )

        result, log = self.child(self.settingsFolder("empty-settings"), path)
        entry = result["objects"]["Box"]
        self.assertEqual(entry["name"], PLASTER, log[-2000:])
        self.assertAlmostEqual(entry["density"], PLASTER_DENSITY, places=9)
        self.assertCube(result["objects"]["Box2"], "Box2")
        self.assertEqual(result["objects"]["Box2"]["uuid"], STEEL_UUID)
        self.assertIn("1 of 5 models and 1 of 9 values found", log)
        self.assertNotIn("Invalid Document.xml", log)
        self.assertEqual(result["learned"], [])

    def testInvalidUuidIsNotLearned(self):
        """A stored uuid that is no UUID: the material is restored, not learned, and a warning says
        why"""
        doc = self.newDoc("E1BadUuid")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        made = box.ShapeMaterial.UUID
        doc.recompute()
        path = os.path.join(self.work, "baduuid.FCStd")
        doc.saveAs(path)
        self.editElement(path, made, lambda e: e.replace(made, "not-a-uuid", 1))

        result, log = self.child(self.settingsFolder("empty-settings"), path)
        entry = result["objects"]["Box"]
        self.assertEqual(entry["uuid"], "not-a-uuid", log[-2000:])
        self.assertAlmostEqual(entry["density"], PLASTER_DENSITY, places=9)
        self.assertEqual(result["learned"], [])
        self.assertIn("has no valid UUID ('not-a-uuid')", log)

    def testLearnedNamesThatCannotBeFiles(self):
        """Names Windows reserves, names over 200 characters and names that differ from a card's
        file only in case are not learned; an ordinary name is"""
        doc = self.newDoc("E1Names")
        names = ["Aux", "com3.ini", "x" * 210, "E1 TEST PLASTER", "E1 fine"]
        uuids = {}
        for i, name in enumerate(names):
            box = self.cube(doc, "Box{}".format(i), 20 * i)
            mat = self.plaster()
            mat.Name = name
            box.ShapeMaterial = mat
            uuids[name] = box.ShapeMaterial.UUID
        doc.recompute()
        path = os.path.join(self.work, "names.FCStd")
        doc.saveAs(path)

        home = self.settingsFolder("names-settings")
        probe, _ = self.child(home)
        library = os.path.join(probe["userAppData"], "Material")
        os.makedirs(library, exist_ok=True)
        with open(os.path.join(library, "e1 test plaster.FCMat"), "w", encoding="utf-8") as f:
            f.write(
                "---\nGeneral:\n"
                '  UUID: "{}"\n'
                '  Name: "e1 test plaster"\n'
                "Models:\n  Density:\n    UUID: '{}'\n"
                '    Density: "2500 kg/m^3"\n'.format(uuid.uuid4(), DENSITY_MODEL)
            )

        result, log = self.child(home, path)
        self.assertEqual(
            result["learned"], ["E1 fine.FCMat", "e1 test plaster.FCMat"], log[-3000:]
        )
        for i, name in enumerate(names):
            entry = result["objects"]["Box{}".format(i)]
            self.assertEqual(entry["uuid"], uuids[name])
            self.assertAlmostEqual(entry["density"], PLASTER_DENSITY, places=9)

    @unittest.skipIf(
        sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        "needs a folder the user can't write",
    )
    def testUnwritableLibraryRegistersNothing(self):
        """A user library that can't be written: the material isn't learned, and the session
        doesn't pretend it is in the library"""
        doc = self.newDoc("E1ReadOnly")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        made = box.ShapeMaterial.UUID
        doc.recompute()
        path = os.path.join(self.work, "readonly.FCStd")
        doc.saveAs(path)

        home = self.settingsFolder("readonly-settings")
        probe, _ = self.child(home)
        library = os.path.join(probe["userAppData"], "Material")
        os.makedirs(library, exist_ok=True)
        os.chmod(library, 0o555)
        try:
            result, log = self.child(home, path, made)
        finally:
            os.chmod(library, 0o755)
        self.assertAlmostEqual(result["objects"]["Box"]["density"], PLASTER_DENSITY, places=9)
        self.assertEqual(result["learned"], [])
        self.assertIn("error", result["library"], log[-2000:])

    def testIntegersKeep64Bits(self):
        """An integer value above 2^31 survives a reopen and a save"""
        doc = self.newDoc("E1Integer")
        box = self.cube(doc, "Box")
        mat = self.plaster()
        mat.addPhysicalModel(TEST_MODEL)
        mat.setPhysicalValue("TestInteger", "42")
        box.ShapeMaterial = mat
        made = box.ShapeMaterial.UUID
        doc.recompute()
        path = os.path.join(self.work, "integer.FCStd")
        doc.saveAs(path)
        self.assertIn('<Value name="TestInteger" value="42"/>', self.documentXml(path))
        self.editElement(
            path,
            made,
            lambda e: e.replace(
                '<Value name="TestInteger" value="42"/>',
                '<Value name="TestInteger" value="3000000000"/>',
            ),
        )

        resaved = os.path.join(self.work, "integer-resaved.FCStd")
        home = self.settingsFolder("empty-settings")
        result, log = self.child(home, path, resave=resaved)
        self.assertTrue(os.path.isfile(resaved), log[-2000:])
        self.assertEqual(result["objects"]["Box"]["integer"], 3000000000)
        xml = self.documentXml(resaved)
        start, end = self.elementOf(xml, made)
        self.assertIn('<Value name="TestInteger" value="3000000000"/>', xml[start:end])
        # the card learned on open keeps it too
        again, log = self.child(home, None, made)
        self.assertEqual(again["library"].get("integer"), 3000000000, log[-2000:])

    def testValuesNotCarriedAreNamed(self):
        """A session material holding a list value: saving warns that the list is not in the file"""
        save = os.path.join(self.work, "list.FCStd")
        code = (
            "import FreeCAD, Materials\n"
            "d = FreeCAD.newDocument('E1List')\n"
            "b = d.addObject('Part::Box', 'Box')\n"
            "m = Materials.Material()\n"
            "m.Name = 'E1 list'\n"
            "m.addPhysicalModel('{}')\n"
            "m.setValue('TestList', ['one', 'two'])\n"
            "b.ShapeMaterial = m\n"
            "d.recompute()\n"
            "d.saveAs({!r})\n".format(TEST_MODEL, save)
        )
        result, log = self.child(self.settingsFolder("empty-settings"), code=code)
        self.assertTrue(os.path.isfile(save), log[-2000:])
        warning = [l for l in log.splitlines() if "not saved with the document" in l]
        self.assertTrue(warning, log[-2000:])
        self.assertIn("TestList", warning[0])
        xml = self.documentXml(save)
        self.assertNotIn('<Value name="TestList"', xml)
        self.assertIn('<Dropped name="TestList"/>', xml)
        # another computer without the card: the material is incomplete, so it is not learned
        result, log = self.child(self.settingsFolder("other-settings"), save)
        self.assertEqual(result["objects"]["Box"]["name"], "E1 list", log[-2000:])
        self.assertIn("TestList (not saved with the document)", log)
        self.assertEqual(result["learned"], [])

    # -- the desktop's follow-up (ops#675 comment 6822760173) -----------------------------------

    def testCountsThatAreNoNumbers(self):
        """Counts that are no numbers (a hand-edited file): the material and the rest of the
        document are restored, a warning names the part, nothing is learned"""
        doc = self.newDoc("E1JunkCounts")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        made = box.ShapeMaterial.UUID
        self.cube(doc, "Box2", 20)
        doc.recompute()
        path = os.path.join(self.work, "junkcounts.FCStd")
        doc.saveAs(path)
        self.editElement(
            path,
            made,
            lambda e: e.replace('models="1"', 'models="abc"').replace('values="1"', 'values="1x"'),
        )

        result, log = self.child(self.settingsFolder("empty-settings"), path)
        entry = result["objects"]["Box"]
        self.assertEqual(entry["name"], PLASTER, log[-2000:])
        self.assertEqual(entry["uuid"], made)
        self.assertAlmostEqual(entry["density"], PLASTER_DENSITY, places=9)
        self.assertCube(result["objects"]["Box2"], "Box2")
        warning = [l for l in log.splitlines() if "1 of abc models and 1 of 1x values found" in l]
        self.assertTrue(warning, log[-2000:])
        self.assertIn("(Box)", warning[0])
        self.assertEqual(result["learned"], [])

    def testMissingUuid(self):
        """No uuid attribute: the material's values are restored, the rest of the document too, a
        warning names the part, nothing is learned"""
        doc = self.newDoc("E1NoUuid")
        box = self.cube(doc, "Box")
        box.ShapeMaterial = self.plaster()
        made = box.ShapeMaterial.UUID
        self.cube(doc, "Box2", 20)
        doc.recompute()
        path = os.path.join(self.work, "nouuid.FCStd")
        doc.saveAs(path)
        self.editElement(path, made, lambda e: e.replace('uuid="{}" '.format(made), "", 1))
        self.assertNotIn(made, self.documentXml(path))

        result, log = self.child(self.settingsFolder("empty-settings"), path)
        entry = result["objects"]["Box"]
        self.assertEqual(entry["name"], PLASTER, log[-2000:])
        self.assertAlmostEqual(entry["density"], PLASTER_DENSITY, places=9)
        self.assertCube(result["objects"]["Box2"], "Box2")
        warning = [l for l in log.splitlines() if "has no valid UUID ('')" in l]
        self.assertTrue(warning, log[-2000:])
        self.assertIn("(Box)", warning[0])
        self.assertEqual(result["learned"], [])
