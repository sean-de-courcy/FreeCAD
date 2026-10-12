# SPDX-License-Identifier: LGPL-2.1-or-later

"""The fork release stamp and files of a newer release (ops#323 PR A,
notes/beta-compatibility.md 2.2, 2.3, 3.4).

Every save writes `ForkRelease="<n>"` on the `Document` element (`App.getForkRelease()`), and an
open reads it back (`App.getForkRelease(doc)`, 0 without one). A file is newer when its
`ForkRelease`, `NamingFormat`, `NamingRevision` or a shape's `.F<n>`/`.N<n>` token is above this
build's (`App.getNewerFormat(doc)` says why); a newer `.F`/`.N` takes no naming migration. The
files are a Part box saved by the test and edited in their Document.xml, never a user's file.

A child FreeCADCmd checks the console error (once per open) and the rehearsal aid
FREECAD_TEST_NAMING_REVISION_OFFSET=1, which makes the build report its naming revision + 1, so a
file saved at the real revision takes the migration. The export side (`exportObjects`) and the
token parsing are tested in C++ (tests/src/App/Document.cpp, "ForkRelease").
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

FORK_RELEASE = re.compile(r'<Document [^>]*ForkRelease="([0-9]+)"')
NAMING_REVISION = re.compile(r'<Document [^>]*NamingRevision="([0-9]+)"')
ELEMENT_MAP = re.compile(r'ElementMap="([^"]*)"')
CONSOLE_ERROR = "was saved by fork release"


def _documentXml(path):
    with zipfile.ZipFile(path) as archive:
        return archive.read("Document.xml").decode("utf-8")


def _rewriteDocumentXml(source, target, rewrite):
    """Copies the zip `source` to `target` with Document.xml passed through `rewrite(text)`."""
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Document.xml":
                text = data.decode("utf-8")
                changed = rewrite(text)
                if changed == text:
                    raise AssertionError("the rewrite changed nothing")
                data = changed.encode("utf-8")
            zout.writestr(item, data)


def _setDocumentAttribute(name, value):
    """A rewrite: the `Document` element's attribute `name` set to `value`, added if missing."""

    def rewrite(text):
        start = text.index("<Document ")
        end = text.index(">", start)
        tag = text[start:end]
        if f' {name}="' in tag:
            tag = re.sub(rf' {name}="[^"]*"', f' {name}="{value}"', tag)
        else:
            tag += f' {name}="{value}"'
        return text[:start] + tag + text[end:]

    return rewrite


def _withoutDocumentAttribute(name):
    def rewrite(text):
        start = text.index("<Document ")
        end = text.index(">", start)
        return text[:start] + re.sub(rf' {name}="[^"]*"', "", text[start:end]) + text[end:]

    return rewrite


def _setMapToken(letter, value):
    """A rewrite: every shape's `.<letter><n>` element map token set to `value`."""

    def rewrite(text):
        return ELEMENT_MAP.sub(
            lambda m: 'ElementMap="'
            + re.sub(rf"\.{letter}[0-9]+(?=\.|$)", f".{letter}{value}", m.group(1))
            + '"',
            text,
        )

    return rewrite


def _token(version, letter):
    match = re.search(rf"\.{letter}([0-9]+)(?=\.|$)", version)
    return int(match.group(1)) if match else None


def _markers(message):
    """The markers a `getNewerFormat()` message lists, without the document's label."""
    start = message.find("(newer: ")
    return message[start:] if start >= 0 else ""


def _boxModel(doc):
    """A box cut by a cylinder: names with embedded names, which an interned document holds in
    its name table (so the file has `NamingFormat`)."""
    box = doc.addObject("Part::Box", "Box")
    cylinder = doc.addObject("Part::Cylinder", "Cylinder")
    cylinder.Radius = 3
    cylinder.Height = 20
    cylinder.Placement.Base = App.Vector(10, 5, -5)
    cut = doc.addObject("Part::Cut", "Cut")
    cut.Base, cut.Tool = box, cylinder
    doc.recompute()
    return cut


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


class ForkReleaseTest(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ForkReleaseTest"))
        self.docNames = []

    def tearDown(self):
        for name in self.docNames:
            if name in App.listDocuments():
                App.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _new(self, name):
        doc = App.newDocument(name)
        self.docNames.append(doc.Name)
        doc.HistoryAlgorithm = "V2"
        doc.InternNames = True
        return doc

    def _open(self, path):
        doc = App.openDocument(path)
        self.docNames.append(doc.Name)
        return doc

    def _saved(self, name="Saved"):
        """A box saved by this build, and its Document.xml."""
        doc = self._new(name)
        _boxModel(doc)
        path = os.path.join(self.dir, name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        return path, _documentXml(path)

    def _edited(self, source, name, rewrite):
        target = os.path.join(self.dir, name + ".FCStd")
        _rewriteDocumentXml(source, target, rewrite)
        return target

    def testSaveWritesTheBuildsRelease(self):
        """A save writes this build's release, and an open reads it back; a new document has
        this build's."""
        release = App.getForkRelease()
        self.assertGreater(release, 0)
        self.assertEqual(App.getForkRelease(self._new("Fresh")), release)
        path, xml = self._saved()
        self.assertEqual(FORK_RELEASE.findall(xml), [str(release)])
        doc = self._open(path)
        self.assertEqual(App.getForkRelease(doc), release)
        self.assertEqual(App.getNewerFormat(doc), "")

    def testAbsentReadsZero(self):
        """A file without the stamp (a preview build's, FreeCAD's) reads 0 and isn't newer; a
        save stamps it with this build's release."""
        path, _ = self._saved()
        old = self._edited(path, "Unstamped", _withoutDocumentAttribute("ForkRelease"))
        self.assertNotIn("ForkRelease=", _documentXml(old))
        doc = self._open(old)
        self.assertEqual(App.getForkRelease(doc), 0)
        self.assertEqual(App.getNewerFormat(doc), "")
        doc.save()
        self.assertEqual(App.getForkRelease(doc), App.getForkRelease())
        self.assertEqual(FORK_RELEASE.findall(_documentXml(old)), [str(App.getForkRelease())])

    def _checkNewer(self, path, marker):
        doc = self._open(path)
        message = App.getNewerFormat(doc)
        self.assertIn(marker, message)
        self.assertIn(f"release {App.getForkRelease()}", message)
        return doc

    def testEachDocumentMarkerMakesItNewer(self):
        """ForkRelease, NamingFormat and NamingRevision above this build's each make the file
        newer, and the message names it; one at this build's value doesn't."""
        path, xml = self._saved()
        revision = int(NAMING_REVISION.findall(xml)[0])
        self.assertIn('NamingFormat="2"', xml, "the premise: the box's names are interned")
        cases = {
            "ForkRelease": App.getForkRelease() + 1,
            "NamingFormat": 3,
            "NamingRevision": revision + 1,
        }
        for attribute, value in cases.items():
            with self.subTest(attribute=attribute):
                newer = self._edited(path, attribute, _setDocumentAttribute(attribute, value))
                doc = self._checkNewer(newer, f"{attribute} {value}")
                if attribute == "ForkRelease":
                    self.assertEqual(App.getForkRelease(doc), value)
                    self.assertIn(f"saved by fork release {value}", App.getNewerFormat(doc))
                App.closeDocument(doc.Name)
        same = self._open(path)
        self.assertEqual(App.getNewerFormat(same), "")

    def testNewerMapTokenTakesNoMigration(self):
        """A shape's `.F` or `.N` above this build's makes the file newer, and the shape takes no
        naming migration: its version is current after the open. An older `.F` still takes it
        (the control: the version stays the file's until the shape is rebuilt)."""
        path, xml = self._saved()
        versions = set(ELEMENT_MAP.findall(xml))
        self.assertEqual(len(versions), 1, versions)
        version = versions.pop()
        revision, form = _token(version, "F"), _token(version, "N")
        self.assertIsNotNone(revision, version)
        self.assertIsNotNone(form, version)
        for letter, value in (("F", revision + 1), ("N", form + 1)):
            with self.subTest(token=letter):
                newer = self._edited(path, "Map" + letter, _setMapToken(letter, value))
                doc = self._checkNewer(newer, "element map")
                self.assertIn(f".{letter}{value}", App.getNewerFormat(doc))
                box = doc.getObject("Box")
                self.assertEqual(box._ElementMapVersion, box.getCorrectElementMapVersion())
                App.closeDocument(doc.Name)
        if revision > 0:
            older = self._edited(path, "MapOlder", _setMapToken("F", revision - 1))
            doc = self._open(older)
            self.assertEqual(App.getNewerFormat(doc), "")
            box = doc.getObject("Box")
            self.assertIn(f".F{revision - 1}", box._ElementMapVersion, "the migration's control")

    def testSaveEndsNewer(self):
        """A save writes this build's file: the document is no longer newer (FreeCADCmd saves
        with a warning; the GUI asks first)."""
        path, _ = self._saved()
        newer = self._edited(path, "Newer", _setDocumentAttribute("ForkRelease", 999))
        doc = self._checkNewer(newer, "ForkRelease 999")
        doc.save()
        self.assertEqual(App.getNewerFormat(doc), "")
        self.assertEqual(App.getForkRelease(doc), App.getForkRelease())
        self.assertEqual(FORK_RELEASE.findall(_documentXml(newer)), [str(App.getForkRelease())])

    def testSaveCopyKeepsNewer(self):
        """A copy saved elsewhere leaves the document newer: its own file is untouched."""
        path, _ = self._saved()
        newer = self._edited(path, "NewerCopy", _setDocumentAttribute("ForkRelease", 999))
        doc = self._checkNewer(newer, "ForkRelease 999")
        doc.saveCopy(os.path.join(self.dir, "Copy.FCStd"))
        self.assertIn("ForkRelease 999", App.getNewerFormat(doc))

    def testMergeOfANewerFileMakesTheDocumentNewer(self):
        """Objects merged from a newer file make the document newer (an import reads the stamp
        too); a merge of a current file doesn't."""
        path, _ = self._saved()
        current = self._new("MergeCurrent")
        current.mergeProject(path)
        self.assertEqual(App.getNewerFormat(current), "")
        newer = self._edited(path, "MergeNewer", _setDocumentAttribute("ForkRelease", 999))
        doc = self._new("MergeTarget")
        doc.mergeProject(newer)
        self.assertIn("ForkRelease 999", App.getNewerFormat(doc))
        self.assertEqual(App.getForkRelease(doc), App.getForkRelease(), "its own release stays")

    def _recovered(self, doc, name):
        """`doc`'s compressed recovery snapshot, copied out of its TransientDir."""
        self.assertTrue(App.writeRecoverySnapshotToTransientDir(doc, compressed=True))
        snapshot = os.path.join(doc.TransientDir, "fc_recovery_file.fcstd")
        target = os.path.join(self.dir, name + ".FCStd")
        shutil.copyfile(snapshot, target)
        return target

    def testRecoverySnapshotKeepsNewer(self):
        """The recovery snapshot of a newer document is newer too (PR 293 review): it keeps the
        file's release and every marker (`NewerFormat`), so the recovered document still asks
        before its first save. A current document's snapshot is this build's, without
        `NewerFormat`."""
        path, xml = self._saved()
        revision = _token(ELEMENT_MAP.findall(xml)[0], "F")
        cases = {
            "ForkRelease": (_setDocumentAttribute("ForkRelease", 999), 999),
            "MapF": (_setMapToken("F", revision + 1), App.getForkRelease()),
        }
        for name, (rewrite, release) in cases.items():
            with self.subTest(case=name):
                doc = self._open(self._edited(path, "Snap" + name, rewrite))
                markers = _markers(App.getNewerFormat(doc))
                self.assertTrue(markers)
                recovered = self._recovered(doc, "Recovered" + name)
                snapshot = _documentXml(recovered)
                self.assertEqual(FORK_RELEASE.findall(snapshot), [str(release)])
                self.assertIn("NewerFormat=", snapshot)
                again = self._open(recovered)
                self.assertEqual(_markers(App.getNewerFormat(again)), markers, "each marker once")
                self.assertEqual(App.getForkRelease(again), release)
                App.closeDocument(again.Name)
                App.closeDocument(doc.Name)
        current = self._open(path)
        snapshot = _documentXml(self._recovered(current, "RecoveredCurrent"))
        self.assertEqual(FORK_RELEASE.findall(snapshot), [str(App.getForkRelease())])
        self.assertNotIn("NewerFormat=", snapshot)

    def testUnreadableMarkersOpenNewer(self):
        """A `ForkRelease`, `NamingFormat` or `NamingRevision` that isn't a whole number in range
        (a damaged file, or a later format) opens, recorded as newer with its raw value, instead
        of aborting the open (PR 293 review)."""
        path, _ = self._saved()
        cases = [
            ("ForkRelease", ""),
            ("ForkRelease", "v9"),
            ("ForkRelease", "99999999999"),
            ("NamingFormat", "x"),
            ("NamingRevision", "x"),
        ]
        for index, (attribute, value) in enumerate(cases):
            with self.subTest(attribute=attribute, value=value):
                unreadable = self._edited(
                    path, f"Unreadable{index}", _setDocumentAttribute(attribute, value)
                )
                doc = self._open(unreadable)
                self.assertIn(f'{attribute} "{value}" (unreadable)', App.getNewerFormat(doc))
                self.assertTrue(doc.getObject("Cut").Shape.isValid())
                if attribute == "ForkRelease":
                    self.assertEqual(App.getForkRelease(doc), 0)
                App.closeDocument(doc.Name)

    def testFailedImportLeavesTheRecord(self):
        """A merge of a newer file that fails after reading its markers leaves the target's
        record as it was: a current document stays current, a newer one keeps its own markers
        only (PR 293 review)."""
        path, _ = self._saved()

        def broken(text):
            newer = _setDocumentAttribute("ForkRelease", 999)(text)
            return newer.replace("<Objects ", "<Objects <", 1)

        failing = self._edited(path, "Broken", broken)
        current = self._new("FailedCurrent")
        with self.assertRaises(Exception):
            current.mergeProject(failing)
        self.assertEqual(App.getNewerFormat(current), "")
        newer = self._open(
            self._edited(path, "FailedNewer", _setDocumentAttribute("NamingFormat", 3))
        )
        with self.assertRaises(Exception):
            newer.mergeProject(failing)
        message = App.getNewerFormat(newer)
        self.assertIn("NamingFormat 3", message)
        self.assertNotIn("ForkRelease 999", message)

    def testClosedDocumentHandleRaises(self):
        """A handle to a closed document raises, as its neighbours do (PR 293 review)."""
        doc = self._new("Closed")
        App.closeDocument(doc.Name)
        with self.assertRaises(RuntimeError):
            App.getForkRelease(doc)
        with self.assertRaises(RuntimeError):
            App.getNewerFormat(doc)

    def testConsoleErrorAndRehearsalAid(self):
        """In a child FreeCADCmd with FREECAD_TEST_NAMING_REVISION_OFFSET=1: the build reports
        its naming revision + 1 in a new shape's `.F` and a saved `NamingRevision`; a file saved
        at the real revision takes the migration, isn't newer, and stays so after the open; a
        newer file gets one console error at its open."""
        path, xml = self._saved()
        revision = int(NAMING_REVISION.findall(xml)[0])
        newer = self._edited(path, "ConsoleNewer", _setDocumentAttribute("ForkRelease", 999))
        out = os.path.join(self.dir, "child.json")
        manifest = os.path.join(self.dir, "manifest.json")
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"saved": path, "newer": newer, "dir": self.dir, "out": out}, fh)
        script = os.path.join(self.dir, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(_CHILD)
        env = dict(os.environ)
        env["FREECAD_TEST_NAMING_REVISION_OFFSET"] = "1"
        env["FORK_RELEASE_TEST_MANIFEST"] = manifest
        run = subprocess.run(
            [_freecadCmd(), script],
            env=env,
            cwd=self.dir,
            timeout=600,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log = run.stdout.decode("utf-8", "replace")
        if os.path.isfile(out + ".error"):
            with open(out + ".error", encoding="utf-8") as fh:
                self.fail(fh.read() + "\n" + log)
        with open(out, encoding="utf-8") as fh:
            result = json.load(fh)
        self.assertEqual(_token(result["newVersion"], "F"), revision + 1, result)
        self.assertEqual(result["savedRevision"], revision + 1, result)
        self.assertEqual(result["openedNewer"], "", "a file at the real revision is older here")
        self.assertIn(f".F{revision}", result["openedVersion"], "it takes the migration")
        self.assertIn("ForkRelease 999", result["newerMessage"])
        self.assertIn("FREECAD_TEST_NAMING_REVISION_OFFSET=1", log)
        self.assertEqual(log.count(CONSOLE_ERROR), 1, log)


_CHILD = """\
import json, os, re, traceback
import FreeCAD as App
manifest = json.load(open(os.environ["FORK_RELEASE_TEST_MANIFEST"], encoding="utf-8"))
try:
    result = {}
    doc = App.newDocument("AidNew")
    doc.HistoryAlgorithm = "V2"
    doc.InternNames = True
    box = doc.addObject("Part::Box", "Box")
    doc.recompute()
    result["newVersion"] = box.getCorrectElementMapVersion()
    path = os.path.join(manifest["dir"], "aid.FCStd")
    doc.saveAs(path)
    import zipfile
    xml = zipfile.ZipFile(path).read("Document.xml").decode("utf-8")
    result["savedRevision"] = int(re.findall(r'<Document [^>]*NamingRevision="([0-9]+)"', xml)[0])
    App.closeDocument(doc.Name)
    opened = App.openDocument(manifest["saved"])
    result["openedNewer"] = App.getNewerFormat(opened)
    result["openedVersion"] = opened.getObject("Box")._ElementMapVersion
    App.closeDocument(opened.Name)
    newer = App.openDocument(manifest["newer"])
    result["newerMessage"] = App.getNewerFormat(newer)
    App.closeDocument(newer.Name)
    with open(manifest["out"], "w", encoding="utf-8") as fh:
        json.dump(result, fh)
except Exception:
    with open(manifest["out"] + ".error", "w", encoding="utf-8") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
"""
