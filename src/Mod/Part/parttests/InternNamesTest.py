# SPDX-License-Identifier: LGPL-2.1-or-later

"""The document switch InternNames (ops#6, Task 1 PR 5): V2 element names held in the name table.

Interning must change no name: an interned name expands (`App.expandMappedName`) to the plain one,
byte for byte. The models here are built in documents whose object IDs start at 0
(`clearDocument`), so the tags of two documents agree and names are compared unmasked.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part


def _documentXml(path):
    with zipfile.ZipFile(path) as archive:
        return archive.read("Document.xml").decode("utf-8")


def _objectData(xml):
    """The objects' part of Document.xml: everything but the document's own properties, which
    hold the save time and the file name."""
    return xml[xml.index("<Objects ") :]


def _names(shape):
    """{name: element} of a shape."""
    return dict(shape.ElementMap)


def _expanded(names):
    return {App.expandMappedName(name): element for name, element in names.items()}


class InternNamesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="InternNamesTest")
        self.docNames = []

    def tearDown(self):
        for name in self.docNames:
            if name in App.listDocuments():
                App.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _document(self, name, interned, algorithm="V2"):
        doc = App.newDocument(name)
        self.docNames.append(doc.Name)
        doc.clearDocument()  # object IDs from 0: the same tags in every document
        doc.HistoryAlgorithm = algorithm
        # Explicitly, also when off: FREECAD_INTERN_NAMES=1 turns it on in new documents.
        doc.InternNames = interned
        return doc

    def _model(self, doc):
        """A box cut by a cylinder and filleted: names with embedded names and split pieces."""
        box = doc.addObject("Part::Box", "Box")
        cylinder = doc.addObject("Part::Cylinder", "Cylinder")
        cylinder.Radius = 3
        cylinder.Height = 20
        cylinder.Placement.Base = App.Vector(10, 5, -5)
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = box, cylinder
        doc.recompute()
        top = [
            i + 1
            for i, edge in enumerate(cut.Shape.Edges)
            if abs(edge.CenterOfMass.z - 10) < 1e-6 and edge.Curve.TypeId == "Part::GeomLine"
        ]
        fillet = doc.addObject("Part::Fillet", "Fillet")
        fillet.Base = cut
        fillet.Edges = [(i, 1.0, 1.0) for i in top[:2]]
        doc.recompute()
        return fillet

    def _save(self, doc, name):
        path = os.path.join(self.dir, name + ".FCStd")
        doc.saveAs(path)
        return path

    def assertInterned(self, names):
        text = "".join(names)
        self.assertIn("~", text)
        self.assertNotIn("^", text)  # no embedded name is left inline

    def assertPlain(self, names):
        self.assertNotIn("~", "".join(names))

    def testOffByDefaultAndNotSaved(self):
        """A new document has the switch off, and saves without it."""
        doc = App.newDocument("InternDefault")
        self.docNames.append(doc.Name)
        if os.environ.get("FREECAD_INTERN_NAMES") != "1":
            self.assertFalse(doc.InternNames)
        doc.InternNames = False
        fillet = self._model(doc)
        self.assertPlain(_names(fillet.Shape))
        xml = _documentXml(self._save(doc, "default"))
        self.assertNotIn("InternNames", xml)

    def testOnThenOffSavesAsBefore(self):
        """Turning the switch on and off again leaves the saved objects byte-identical."""
        doc = self._document("InternOnOff", False)
        fillet = self._model(doc)
        before = _documentXml(self._save(doc, "before"))
        doc.InternNames = True
        doc.recompute()
        self.assertInterned(_names(fillet.Shape))
        on = _documentXml(self._save(doc, "on"))
        self.assertIn('name="InternNames"', on)
        self.assertIn('.N2"', on)  # the element map version of interned maps (ops#6 T2: N2)
        doc.InternNames = False
        doc.recompute()
        self.assertPlain(_names(fillet.Shape))
        after = _documentXml(self._save(doc, "after"))
        self.assertNotIn("InternNames", after)
        self.assertEqual(_objectData(after), _objectData(before))

    def testElementMapVersion(self):
        """Interned V2 documents have their own element map version; V1 ignores the switch."""
        doc = self._document("InternVersion", False)
        box = doc.addObject("Part::Box", "Box")
        plain = box.getCorrectElementMapVersion()
        doc.InternNames = True
        self.assertEqual(box.getCorrectElementMapVersion(), plain + ".N2")
        doc.InternNames = False
        self.assertEqual(box.getCorrectElementMapVersion(), plain)
        v1 = self._document("InternVersionV1", True, algorithm="V1")
        v1box = v1.addObject("Part::Box", "Box")
        self.assertFalse(v1box.getCorrectElementMapVersion().endswith(".N2"))

    def testRecoverySnapshotWritesIndices(self):
        """The recovery snapshot, the second writer of interned files (ops#6 T2, review F2):
        uncompressed, its maps refer to the table by index and Document.xml holds the v2 table;
        made into a project file as recovery does, it opens with the names as they were."""
        doc = self._document("InternRecovery", True)
        fillet = self._model(doc)
        names = _names(fillet.Shape)
        self.assertInterned(names)
        self.assertTrue(App.writeRecoverySnapshotToTransientDir(doc, compressed=False))
        folder = os.path.join(doc.TransientDir, "fc_recovery_files")
        files = {}
        for name in os.listdir(folder):
            with open(os.path.join(folder, name), "rb") as fh:
                files[name] = fh.read()
        xml = files["Document.xml"].decode("utf-8")
        self.assertIn('NamingFormat="2"', xml)
        self.assertIn("NameTableStart v2 ", xml)
        maps = [text.decode("utf-8") for name, text in files.items() if name.endswith(".Map.txt")]
        self.assertTrue(maps)
        self.assertTrue(any(re.search(r"~[0-9]{1,12}(?![0-9a-v])", text) for text in maps))
        for text in maps:
            self.assertIsNone(re.search(r"~[0-9a-v]{13}", text), "a reference in the hash form")
        project = os.path.join(self.dir, "recovered.FCStd")
        with zipfile.ZipFile(project, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Document.xml", files.pop("Document.xml"))
            for name, data in files.items():
                archive.writestr(name, data)
        recovered = App.openDocument(project)
        self.docNames.append(recovered.Name)
        self.assertEqual(_names(recovered.getObject("Fillet").Shape), names)

    def testInternedNamesExpandToPlain(self):
        """Every feature of the model has the same names in both forms, element for element."""
        plainDoc = self._document("InternPlain", False)
        internedDoc = self._document("InternInterned", True)
        self._model(plainDoc)
        self._model(internedDoc)
        for plain in plainDoc.Objects:
            interned = internedDoc.getObject(plain.Name)
            self.assertEqual(interned.ID, plain.ID)
            plainNames = _names(plain.Shape)
            internedNames = _names(interned.Shape)
            if plain.Name in ("Cut", "Fillet"):
                self.assertInterned(internedNames)
            self.assertEqual(_expanded(internedNames), plainNames, plain.Name)

    def testSwitchRenamesExistingFeatures(self):
        """Switching on recomputes every feature in the interned form; off, in the plain form."""
        doc = self._document("InternSwitch", False)
        fillet = self._model(doc)
        plain = _names(fillet.Shape)
        doc.InternNames = True
        self.assertIn("Touched", fillet.State)
        doc.recompute()
        interned = _names(fillet.Shape)
        self.assertInterned(interned)
        self.assertEqual(_expanded(interned), plain)
        doc.InternNames = False
        doc.recompute()
        self.assertEqual(_names(fillet.Shape), plain)

    def testShapeFromAnotherDocumentTakesThisDocumentsForm(self):
        """A shape set into a feature is stored in its document's form, whichever form it has."""
        internedDoc = self._document("InternSource", True)
        plainDoc = self._document("PlainSource", False)
        internedShape = self._model(internedDoc).Shape
        plainShape = self._model(plainDoc).Shape
        self.assertInterned(_names(internedShape))
        self.assertPlain(_names(plainShape))

        intoPlain = plainDoc.addObject("Part::Feature", "FromInterned")
        intoPlain.Shape = internedShape
        intoInterned = internedDoc.addObject("Part::Feature", "FromPlain")
        intoInterned.Shape = plainShape

        self.assertPlain(_names(intoPlain.Shape))
        self.assertEqual(_names(intoPlain.Shape), _expanded(_names(internedShape)))
        self.assertInterned(_names(intoInterned.Shape))
        self.assertEqual(_expanded(_names(intoInterned.Shape)), _names(plainShape))

    def testReadersTakeEitherForm(self):
        """Task 1 PR 6: a lookup finds an element by its name in either form, and the readers that
        walk a name's structure (history, the solver's ancestry and pieces) see the plain one."""
        plainDoc = self._document("ReadPlain", False)
        internedDoc = self._document("ReadInterned", True)
        plainShape = self._model(plainDoc).Shape
        internedShape = self._model(internedDoc).Shape
        plainNames = _names(plainShape)
        internedByPlain = {App.expandMappedName(n): n for n in _names(internedShape)}
        self.assertEqual(set(internedByPlain), set(plainNames))
        pieces = 0
        for plain, element in plainNames.items():
            interned = internedByPlain[plain]
            self.assertEqual(internedShape.getElementIndexedName(plain), element)
            self.assertEqual(plainShape.getElementIndexedName(interned), element)
            self.assertEqual(App.getNameAncestors(interned), App.getNameAncestors(plain))
            plainHistory = plainShape.getElementHistory(plain)
            internedHistory = internedShape.getElementHistory(interned)
            self.assertEqual(internedHistory, plainHistory, plain)
            if "|" in plain:
                prefix = plain[: plain.rindex("|")]
                if App.isPieceOf(plain, prefix):
                    pieces += 1
                    self.assertTrue(App.isPieceOf(interned, App.internMappedName(prefix)))
        self.assertGreater(pieces, 0)

    def testShapesBuiltFromInternedShapesAreInterned(self):
        """A shape built in Python from an interned shape interns its names too, and they expand to
        the names of the same shape built from the plain one."""
        internedDoc = self._document("InternBuilt", True)
        plainDoc = self._document("PlainBuilt", False)
        internedShape = self._model(internedDoc).Shape
        plainShape = self._model(plainDoc).Shape
        tool = Part.makeBox(4, 4, 20, App.Vector(-1, -1, -5))

        internedCut = internedShape.cut(tool)
        plainCut = plainShape.cut(tool)

        self.assertInterned(_names(internedCut))
        self.assertPlain(_names(plainCut))
        self.assertEqual(_expanded(_names(internedCut)), _names(plainCut))

    def testRestoredMapsTakeTheDocumentsForm(self):
        """ops#97: a map read from a file holds the file's names as they are. When they are in
        the other form than the document's, they are put in the document's form once read: a
        file saved after the switch was turned over but before the recompute, and objects
        merged from a file of a document with the other setting. Checked in another process,
        whose name table holds only what the files bring."""
        files = {}
        for name, interned in (("turnedOff", True), ("turnedOn", False)):
            doc = self._document("Restore" + name, interned)
            self._model(doc)
            doc.InternNames = not interned  # turned over, saved before the recompute
            files[name] = (self._save(doc, name), not interned)
        for name, interned in (("interned", True), ("plain", False)):
            doc = self._document("Restore" + name, interned)
            self._model(doc)
            files[name] = (self._save(doc, name), interned)
        expected = _names(self._model(self._document("RestoreExpected", False)).Shape)
        manifest = os.path.join(self.dir, "manifest.json")
        out = os.path.join(self.dir, "out.json")
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"files": files, "out": out}, fh)
        script = os.path.join(self.dir, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(_RESTORE_CHILD)
        env = dict(os.environ)
        env.pop("FREECAD_INTERN_NAMES", None)
        env["INTERN_NAMES_TEST_MANIFEST"] = manifest
        subprocess.run([_freecadCmd(), script], env=env, cwd=self.dir, timeout=600, check=False)
        if os.path.isfile(out + ".error"):
            with open(out + ".error", encoding="utf-8") as fh:
                self.fail(fh.read())
        with open(out, encoding="utf-8") as fh:
            results = json.load(fh)
        self.assertEqual(
            sorted(results), ["mergedIntoInterned", "mergedIntoPlain", "turnedOff", "turnedOn"]
        )
        for case, result in results.items():
            with self.subTest(case=case):
                if result["interned"]:
                    self.assertInterned(result["names"])
                else:
                    self.assertPlain(result["names"])
                self.assertEqual(result["expanded"], expected)
                self.assertEqual(result["found"], len(expected))

    def testBuilderWithInputsInBothForms(self):
        """ops#97: a Cut whose tool is a link to a feature of a document with the other setting
        gets its inputs in both forms in one call. Its names are in its document's form, and
        expand to the names of the same model with every document plain."""
        results = {}
        for toolInterned, interned in ((False, False), (True, False), (False, True)):
            key = f"{int(toolInterned)}{int(interned)}"
            toolDoc = self._document("BothTool" + key, toolInterned)
            self._model(toolDoc)
            self._save(toolDoc, "tool" + key)
            doc = self._document("BothCut" + key, interned)
            base = self._model(doc)
            self._save(doc, "cut" + key)  # a link to another document needs its owner saved
            link = doc.addObject("App::Link", "Tool")
            link.LinkedObject = toolDoc.getObject("Fillet")
            link.LinkPlacement = App.Placement(App.Vector(5, 5, 5), App.Rotation())
            cut = doc.addObject("Part::Cut", "CutBoth")
            cut.Base, cut.Tool = base, link
            doc.recompute()
            self.assertTrue(cut.Shape.isValid(), key)
            # the tool comes in its own document's form: the Cut's inputs are in both forms
            toolNames = "".join(_names(Part.getShape(link)))
            self.assertEqual("~" in toolNames, toolInterned, key)
            names = _names(cut.Shape)
            if interned:
                self.assertInterned(names)
            else:
                self.assertPlain(names)
            results[key] = _expanded(names)
        self.assertGreater(len(results["00"]), 0)
        self.assertEqual(results["10"], results["00"])
        self.assertEqual(results["01"], results["00"])


def _freecadCmd():
    names = ("FreeCADCmd.exe", "FreeCADCmd") if sys.platform == "win32" else ("FreeCADCmd",)
    if os.path.basename(sys.executable).lower().startswith("freecadcmd"):
        return sys.executable
    for folder in ("bin", "MacOS", ""):
        for name in names:
            path = os.path.join(App.getHomePath(), folder, name)
            if os.path.isfile(path):
                return path
    raise FileNotFoundError("FreeCADCmd next to " + App.getHomePath())


def restoreChild(manifestPath):
    """In the child process of testRestoredMapsTakeTheDocumentsForm: opens the files saved after
    the switch was turned over, and merges the interned file into a plain document and the plain
    file into an interned one. Reports the fillet's names, the document's form, and how many
    names find their element."""
    with open(manifestPath, encoding="utf-8") as fh:
        manifest = json.load(fh)
    files = manifest["files"]

    def report(doc):
        shape = doc.getObject("Fillet").Shape
        names = _names(shape)
        found = sum(1 for n, e in names.items() if shape.getElementIndexedName(n) == e)
        return {
            "interned": doc.InternNames,
            "names": names,
            "expanded": _expanded(names),
            "found": found,
        }

    results = {}
    for case in ("turnedOff", "turnedOn"):
        doc = App.openDocument(files[case][0])
        results[case] = report(doc)
        App.closeDocument(doc.Name)
    for case, (source, interned) in (
        ("mergedIntoPlain", ("interned", False)),
        ("mergedIntoInterned", ("plain", True)),
    ):
        doc = App.newDocument(case)
        doc.InternNames = interned
        doc.mergeProject(files[source][0])
        results[case] = report(doc)
        App.closeDocument(doc.Name)
    with open(manifest["out"], "w", encoding="utf-8") as fh:
        json.dump(results, fh)


_RESTORE_CHILD = """\
import json, os, traceback
manifest = os.environ["INTERN_NAMES_TEST_MANIFEST"]
try:
    from parttests import InternNamesTest
    InternNamesTest.restoreChild(manifest)
except Exception:
    with open(json.load(open(manifest))["out"] + ".error", "w") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
"""
