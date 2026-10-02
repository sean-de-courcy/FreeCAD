# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Saving and reopening documents with interned names (ops#6, Task 1 PR 7).

An interned name refers to entries of the process-wide name table (`~<ID>`). A saved file holds
the entries its names need in a `NameTable` element at the end of Document.xml, so another process
can expand them. In one process the table would hide a missing entry, so each file is reopened in
a child `FreeCADCmd` that has built nothing.

- TestNamingSaveFile: each dump model (TestNamingDump), saved in V2i. Every reference anywhere in
  the file (Document.xml and every map file) has its entry in the file's table, the table refers
  to nothing outside itself, and each entry's ID is its content's.
- TestNamingSaveReopen: the child opens each file. Every reference resolves, the names are the
  saved ones and expand to the same plain names; after touching every object and recomputing,
  the names are the same again, and a new save holds the same table.
- TestNamingSaveMerge: another child merges each file into a new document (File > Merge
  project, `Document.importObjects`): every reference resolves and the names are the saved ones.
- TestNamingSavePlain: plain V2 and V1 files don't change by a byte once the process has interned
  names: the child saves each model before and after it has opened an interned file.
- TestNamingSaveCrossDoc: the cross-document scenarios (Scenarios/crossdoc.py) in V2i, and the
  mixed ones in V2 too (a plain document whose binders hold an interned document's names): built
  and saved here, opened, judged, edited and judged again in the child. The references are
  correct after the reopen, and after the edit the child's records equal an in-process run's.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import traceback
import unittest
import zipfile

import FreeCAD as App

from PartDesignTests import TestNamingDump as dump
from PartDesignTests.Scenarios import crossdoc, harness, models

__all__ = [
    "TestNamingSaveFile",
    "TestNamingSaveReopen",
    "TestNamingSaveMerge",
    "TestNamingSavePlain",
    "TestNamingSaveCrossDoc",
]

REF = re.compile(r"~([0-9a-v]{13})")
TABLE = re.compile(r'<NameTable NamingFormat="(\d+)" count="(\d+)">\s*<!\[CDATA\[(.*?)\]\]>', re.S)
SAVED_DATE = re.compile(r'<Property name="LastModifiedDate".*?</Property>', re.S)

# The cross-document scenarios, each in V2i; the mixed ones also in V2, where the scenario's own
# document is plain and the one it binds is interned
CROSSDOC = [
    (cls.__name__, config)
    for cls in harness.scenarioClasses([crossdoc])
    for config in (("V2i", "V2") if cls.mixed else ("V2i",))
]
# The fields of a SCORE record compared with the in-process run (TestNamingScenarios' oracle)
FIELDS = ("verdict", "stored", "outcome", "subs", "names", "names_before", "subs_before")
GEOMETRY_ID = re.compile(r"\bg[0-9]+\b")


def fileEntries(path):
    """{zip entry: text} of a saved document."""
    with zipfile.ZipFile(path) as z:
        return {name: z.read(name).decode("utf-8", "replace") for name in z.namelist()}


def nameTable(entries):
    """(format, {ID: content}) of the NameTable element in Document.xml, or (None, {})."""
    match = TABLE.search(entries["Document.xml"])
    if not match:
        return None, {}
    lines = match.group(3).split("\n")
    lines = [line.rstrip("\r") for line in lines if line.strip()]
    head = lines[0].split()
    if head[:2] != ["NameTableStart", "v1"] or int(head[2]) != len(lines) - 1:
        raise AssertionError(f"bad table header {lines[0]!r}")
    table = {}
    for line in lines[1:]:
        id, content = line.split(" ", 1)
        table[id] = content
    if len(table) != int(match.group(2)):
        raise AssertionError(f"count {match.group(2)} for {len(table)} entries")
    return int(match.group(1)), table


def refsIn(texts):
    return {m for text in texts for m in REF.findall(text)}


def _maskDate(text):
    return SAVED_DATE.sub("", text)


# ---------------------------------------------------------------------------------------------
# The child process: everything it does is on files it didn't build
# ---------------------------------------------------------------------------------------------


def _childPlainSave(manifest):
    """Builds every model in V2 and V1 and saves it, while the table is empty. Returns the
    documents to save again later."""
    docs = []
    for model in dump.MODELS:
        for mode in ("V2", "V1"):
            doc = models.newDocument(f"Plain{model}{mode}")
            dump._setMode(doc, mode)
            features = [f.Name for f in dump.MODELS[model](doc)]
            doc.recompute()
            path = os.path.join(manifest["folder"], f"plain-{model}-{mode}.FCStd")
            doc.saveAs(path)
            shutil.copyfile(path, path + ".before")
            docs.append((f"{model}.{mode}", doc, path, features))
    return docs


def _dumpPlain(model, mode, doc, features):
    return dump._dumpFeatures(model, [doc.getObject(n) for n in features], None, mode)


def _resolves(paths):
    """The references in the files that the table doesn't know."""
    refs = refsIn(text for path in paths for text in fileEntries(path).values())
    return sorted(r for r in refs if App.getNameTableEntry(r) is None)


def _childModels(manifest):
    out = {}
    for model, info in manifest["models"].items():
        try:
            doc = App.openDocument(info["path"])
            features = [doc.getObject(name) for name in info["features"]]
            result = {
                "unresolved": _resolves([info["path"]]),
                "raw": dump._dumpFeatures(model, features, None, "V2"),
                "expanded": dump._dumpFeatures(model, features, None, "V2i"),
            }
            for obj in doc.Objects:
                obj.touch()
            doc.recompute()
            result["recomputed"] = dump._dumpFeatures(model, features, None, "V2")
            again = info["path"].replace(".FCStd", "-again.FCStd")
            doc.saveAs(again)
            result["again"] = again
            App.closeDocument(doc.Name)
        except Exception:
            result = {"error": traceback.format_exc()}
        out[model] = result
    return out


def _childMerge(manifest):
    """Merges each file into a new document (File > Merge project): the same names."""
    out = {}
    for model, info in manifest["models"].items():
        try:
            doc = App.newDocument(f"Merged{model}")
            doc.mergeProject(info["path"])
            features = [doc.getObject(name) for name in info["features"]]
            out[model] = {
                "unresolved": _resolves([info["path"]]),
                "raw": dump._dumpFeatures(model, features, None, "V2"),
                "expanded": dump._dumpFeatures(model, features, None, "V2i"),
            }
            App.closeDocument(doc.Name)
        except Exception:
            out[model] = {"error": traceback.format_exc()}
    return out


def _records(results):
    return {name: {f: r.record.get(f) for f in FIELDS} for name, r in results.items()}


def _childCrossDoc(manifest):
    out = {}
    for key, info in manifest["crossdoc"].items():
        try:
            scenario = getattr(crossdoc, info["scenario"])(info["config"])
            scenario.folder = info["folder"]
            scenario.doc = App.openDocument(info["pathA"])  # opens B too
            target = App.getDocument(info["nameB"])
            scenario.documents = [scenario.doc.Name, target.Name]
            result = {"unresolved": _resolves([info["pathA"], info["pathB"]])}
            scenario.recordRefs(scenario.doc)
            for obj in scenario.doc.Objects + target.Objects:
                obj.touch()
            target.recompute()
            scenario.doc.recompute()
            scenario.stepName = "reopen"
            reopen = {n: scenario.judge(r, "reopen") for n, r in scenario.refs.items()}
            result["reopen"] = _records(reopen)
            scenario.stepName = "edit"
            scenario.edit(scenario.doc)
            scenario.doc.recompute()
            after = {n: scenario.judge(r, "edit") for n, r in scenario.refs.items()}
            for name, r in after.items():
                r.record["names_before"] = reopen[name].record["names"]
                r.record["subs_before"] = reopen[name].record["subs"]
            result["edit"] = _records(after)
            for name in scenario.documents:
                if name in App.listDocuments():
                    App.closeDocument(name)
        except Exception:
            result = {"error": traceback.format_exc()}
        out[key] = result
    return out


def childMain(manifestPath, outPath, part):
    with open(manifestPath, encoding="utf-8") as fh:
        manifest = json.load(fh)
    if part == "merge":  # a process of its own: the entries come from the merged files only
        result = {"merged": _childMerge(manifest)}
        with open(outPath, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
        return
    result = {}
    plain = _childPlainSave(manifest)  # first: nothing is interned in this process yet
    result["models"] = _childModels(manifest)
    result["crossdoc"] = _childCrossDoc(manifest)
    result["plain"] = {}
    for key, doc, path, features in plain:
        model, mode = key.split(".")
        names = _dumpPlain(model, mode, doc, features)
        doc.save()  # now with entries in the process table
        App.closeDocument(doc.Name)
        try:
            doc = App.openDocument(path)  # a file without a NameTable element
            reopened = _dumpPlain(model, mode, doc, features) == names
            App.closeDocument(doc.Name)
        except Exception:
            reopened = traceback.format_exc()
        result["plain"][key] = {"path": path, "reopened": reopened}
    with open(outPath, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)


CHILD_SCRIPT = """\
import os, traceback
try:
    from PartDesignTests import TestNamingSave
    TestNamingSave.childMain(os.environ["FREECAD_NAMING_SAVE_MANIFEST"],
                             os.environ["FREECAD_NAMING_SAVE_OUT"],
                             os.environ["FREECAD_NAMING_SAVE_PART"])
except Exception:
    with open(os.environ["FREECAD_NAMING_SAVE_OUT"] + ".error", "w") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
"""


# ---------------------------------------------------------------------------------------------
# This process: build, save, run the child once
# ---------------------------------------------------------------------------------------------


def _saveModels(folder):
    saved = {}
    for model in dump.MODELS:
        doc = models.newDocument(f"Saved{model}")
        try:
            dump._setMode(doc, "V2i")
            features = dump.MODELS[model](doc)
            doc.recompute()
            path = os.path.join(folder, f"{model}.FCStd")
            doc.saveAs(path)
            saved[model] = {
                "path": path,
                "features": [f.Name for f in features],
                "raw": dump._dumpFeatures(model, features, None, "V2"),
                "expanded": dump._dumpFeatures(model, features, None, "V2i"),
            }
        finally:
            App.closeDocument(doc.Name)
    return saved


def _saveCrossDoc():
    """Builds and saves each case in its own folder (the scenario's: the child edits and saves
    its documents there); also runs it here, as the reference for the child's records."""
    saved = {}
    for name, config in CROSSDOC:
        key = f"{name}.{config}"
        cls = getattr(crossdoc, name)
        scenario = cls(config)
        try:
            scenario.doc = scenario.newDocument()
            scenario.build(scenario.doc)
            scenario.doc.recompute()
            before = {n: scenario.judge(r, "build").verdict for n, r in scenario.refs.items()}
            target = App.getDocument(scenario.documents[1])
            target.save()
            scenario.doc.save()
            info = {
                "scenario": name,
                "config": config,
                "before": before,
                "folder": scenario.folder,
                "pathA": scenario.path(scenario.doc),
                "pathB": scenario.path(target),
                "nameB": target.Name,
            }
        finally:
            for doc in scenario.documents:  # not cleanup(): it removes the folder
                if doc in App.listDocuments():
                    App.closeDocument(doc)
        try:
            info["inProcess"] = _records(cls(config).run())
        except Exception:
            info["inProcess"] = traceback.format_exc()
        saved[key] = info
    return saved


_saved = None


def saved():
    """{"folder", "models", "crossdoc", "child"}: the files saved here and the child's results.
    Runs once per process."""
    global _saved
    if _saved is not None:
        return _saved
    folder = tempfile.mkdtemp(prefix="naming-save-")
    _saved = {"folder": folder, "models": _saveModels(folder), "crossdoc": _saveCrossDoc()}
    manifest = os.path.join(folder, "manifest.json")
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(_saved, fh, indent=1)
    script = os.path.join(folder, "child.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(CHILD_SCRIPT)
    runs = {}
    for part in ("main", "merge"):
        out = os.path.join(folder, f"child-{part}.json")
        env = dict(os.environ)
        env.pop("FREECAD_INTERN_NAMES", None)  # the plain models must be plain
        env["FREECAD_NAMING_SAVE_MANIFEST"] = manifest
        env["FREECAD_NAMING_SAVE_OUT"] = out
        env["FREECAD_NAMING_SAVE_PART"] = part
        log = open(os.path.join(folder, f"child-{part}.log"), "w")
        proc = subprocess.Popen(
            [dump._freecadCmd(), script], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=folder
        )
        runs[part] = (proc, out, log)
    _saved["child"] = {}
    for part, (proc, out, log) in runs.items():
        try:
            proc.wait(timeout=900)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        if os.path.isfile(out):
            with open(out, encoding="utf-8") as fh:
                _saved["child"].update(json.load(fh))
        else:
            error = out + ".error"
            reason = open(error).read() if os.path.isfile(error) else f"no output ({folder})"
            _saved["child"]["ERROR"] = f"{part}: {reason}"
    return _saved


def child(test, section, key):
    result = saved()["child"]
    test.assertNotIn("ERROR", result, result.get("ERROR"))
    value = result[section][key]
    if isinstance(value, dict):
        test.assertNotIn("error", value, value.get("error"))
    return value


# ---------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------


class TestNamingSaveFile(unittest.TestCase):
    """The file holds the entries of every reference in it, and no others."""

    def check(self, model):
        info = saved()["models"][model]
        entries = fileEntries(info["path"])
        format, table = nameTable(entries)
        refs = refsIn(entries.values())
        if not refs:
            self.assertIsNone(format, "a table without references")
            self.assertNotIn("~", info["expanded"])
            return
        self.assertEqual(format, 1)
        # every reference in the file, the table's own included, has its entry
        self.assertEqual(sorted(refs - set(table)), [])
        # and no entry is there for nothing: each is referenced from outside the table
        # or from another entry
        reached = refsIn(text for name, text in entries.items() if name != "Document.xml")
        reached |= refsIn([TABLE.sub("", entries["Document.xml"])])
        pending = list(reached)
        while pending:
            for ref in REF.findall(table.get(pending.pop(), "")):
                if ref not in reached:
                    reached.add(ref)
                    pending.append(ref)
        self.assertEqual(set(table), reached)
        self.assertEqual(list(table), sorted(table), "entries sorted by ID")
        for id, content in table.items():
            self.assertEqual(App.getMappedNameId(content), id, content)
        self.assertNotIn("^", "".join(table.values()))


class TestNamingSaveReopen(unittest.TestCase):
    """Another process opens the file: every reference resolves, and the names are the saved ones,
    also after a recompute."""

    def check(self, model):
        info = saved()["models"][model]
        result = child(self, "models", model)
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(result["raw"], info["raw"], "names after the reopen")
        self.assertEqual(result["expanded"], info["expanded"], "expanded names after the reopen")
        self.assertEqual(result["recomputed"], info["raw"], "names after a recompute")
        self.assertEqual(
            nameTable(fileEntries(result["again"])),
            nameTable(fileEntries(info["path"])),
            "the table of the recomputed document",
        )


class TestNamingSaveMerge(unittest.TestCase):
    """Another process merges the file into a new document (File > Merge project): every
    reference resolves, and the names are the saved ones."""

    def check(self, model):
        info = saved()["models"][model]
        result = child(self, "merged", model)
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(result["raw"], info["raw"], "names after the merge")
        self.assertEqual(result["expanded"], info["expanded"], "expanded names after the merge")


class TestNamingSavePlain(unittest.TestCase):
    """A plain V2 or V1 file is the same, byte for byte, whether the process's table is empty or
    not: no NameTable element, nothing else changed. It reopens with the same names."""

    def check(self, model, mode):
        result = child(self, "plain", f"{model}.{mode}")
        self.assertIs(result["reopened"], True, "the names after reopening the file")
        path = result["path"]
        before = fileEntries(path + ".before")
        after = fileEntries(path)
        self.assertEqual(sorted(after), sorted(before))
        self.assertNotIn("<NameTable", after["Document.xml"])
        self.assertEqual(refsIn(after.values()), set())
        for name in before:
            if name == "Document.xml":
                self.assertEqual(_maskDate(after[name]), _maskDate(before[name]))
            else:
                self.assertEqual(after[name], before[name], name)


class TestNamingSaveCrossDoc(unittest.TestCase):
    """A cross-document scenario saved here, then reopened, judged, edited and judged in another
    process: correct after the reopen, and after the edit as in an in-process run."""

    def check(self, key):
        info = saved()["crossdoc"][key]
        self.assertEqual(set(info["before"].values()), {"correct"}, info["before"])
        result = child(self, "crossdoc", key)
        self.assertEqual(result["unresolved"], [])
        # A's own file holds the entries of its binders' names, in B's form
        a = fileEntries(info["pathA"])
        _, table = nameTable(a)
        self.assertEqual(sorted(refsIn(a.values()) - set(table)), [])
        for name, record in result["reopen"].items():
            self.assertEqual(record["verdict"], "correct", f"{name} after the reopen: {record}")
        inProcess = info["inProcess"]
        self.assertIsInstance(inProcess, dict, inProcess)
        for name, record in result["edit"].items():
            for field in FIELDS:
                if field in ("names_before", "subs_before"):
                    continue  # before the edit: after the build here, after the reopen there
                a, b = record[field], inProcess[name][field]
                if field == "names" and a and b:
                    a = [GEOMETRY_ID.sub("g#", n) if n else n for n in a]
                    b = [GEOMETRY_ID.sub("g#", n) if n else n for n in b]
                self.assertEqual(a, b, f"{name} after the edit: {field}")


def _addTests():
    for model in dump.MODELS:
        doc = dump.MODELS[model].__doc__.split(".")[0]
        for cls in (TestNamingSaveFile, TestNamingSaveReopen, TestNamingSaveMerge):

            def test(self, model=model):
                self.check(model)

            test.__name__ = f"test{model}"
            test.__doc__ = f"{doc} (V2i)"
            setattr(cls, test.__name__, test)
        for mode in ("V2", "V1"):

            def test(self, model=model, mode=mode):
                self.check(model, mode)

            test.__name__ = f"test{model}{mode}"
            test.__doc__ = f"{doc} ({mode})"
            setattr(TestNamingSavePlain, test.__name__, test)
    for name, config in CROSSDOC:

        def test(self, key=f"{name}.{config}"):
            self.check(key)

        test.__name__ = f"test{name}{config}"
        test.__doc__ = f"{name} ({config})"
        setattr(TestNamingSaveCrossDoc, test.__name__, test)


_addTests()
