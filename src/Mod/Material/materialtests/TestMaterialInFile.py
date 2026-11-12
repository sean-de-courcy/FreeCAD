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
        perMm3 = density(mat, "kg/mm^3")
        entry["mass"] = None if perMm3 is None or entry["volume"] is None else entry["volume"] * perMm3
        out["objects"][obj.Name] = entry
if os.environ.get("E1_UUID"):
    try:
        card = Materials.MaterialManager().getMaterial(os.environ["E1_UUID"])
        out["library"] = {"name": card.Name, "density": density(card, "kg/m^3")}
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

    def child(self, home, doc=None, uuidToResolve=None):
        """Opens doc (and resolves a UUID) in a FreeCADCmd whose settings folder is home"""
        script = os.path.join(self.work, "child.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(CHILD)
        out = os.path.join(self.work, "child-{}.json".format(uuid.uuid4().hex[:8]))
        env = dict(os.environ)
        env["FREECAD_USER_HOME"] = home
        for inherited in ("FREECAD_USER_DATA", "FREECAD_USER_TEMP"):
            env.pop(inherited, None)  # they override FREECAD_USER_HOME's folders
        env["E1_OUT"] = out
        env.pop("E1_DOC", None)
        env.pop("E1_UUID", None)
        if doc:
            env["E1_DOC"] = doc
        if uuidToResolve:
            env["E1_UUID"] = uuidToResolve
        proc = subprocess.run(
            [_freecadCmd(), script],
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
