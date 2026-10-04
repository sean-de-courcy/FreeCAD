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

"""The naming-revision gate (FreeCAD-CH, ops#103), on designed models.

A V2 element map version ends in the fork's naming revision, `.F<n>` (`.F<n>.N2` with
InternNames on). A file saved under another revision asks for a recompute, and that recompute
re-derives each reference into a rebuilt shape from its geometry: a reference whose saved name now
gives another element (a naming fix moved it) goes back to the element at its old place, solver
off (the geometric search) and on (the saved fingerprint); one whose old geometry is gone is
broken, never moved to the name's element.

A naming fix is emulated in the saved file: two faces of the producer trade names in its saved
element map (`<Object>.Shape.Map.txt`, one line per element), and the reference holds the other
face's name, so that the file is consistent as saved (the name gives the stored index in the
restored map) while the build names the faces as before (the name gives the other face). Aging
the file's stamps (`ElementMap="..."`) to the previous revision makes it a file from before the
fix; with the stamps left current, the same file shows the defect the gate exists for.
"""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App

from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import face

# (ReferenceSolver, InternNames) per configuration
CONFIGS = {
    "V2": (False, False),
    "V2i": (False, True),
    "V2s": (True, False),
    "V2is": (True, True),
}

# The face pad model: Pad1 a box 20 x 10 x 10, Pad2 its top face padded by 3, Pad3 Pad2's side
# face at x = 20 (FaceC) padded by 2. FaceD is Pad2's side face at x = 0, the same kind of face.
FACE_C = (20, 5, 11.5)
FACE_D = (0, 5, 11.5)


def currentRevision():
    """The naming revision of this build, from a new V2 document's element map version."""
    doc = App.newDocument("NamingGateRevision")
    try:
        doc.HistoryAlgorithm = "V2"
        box = doc.addObject("Part::Box", "Box")
        match = re.search(r"\.F([0-9]+)", box.getCorrectElementMapVersion())
        return int(match.group(1))
    finally:
        App.closeDocument(doc.Name)


def ageStamps(xml):
    """The document's XML with every shape stamped with the previous naming revision."""
    previous = currentRevision() - 1

    def age(match):
        return re.sub(r"\.F[0-9]+", ".F%d" % previous, match.group(0))

    return re.sub(r'ElementMap="[^"]*"', age, xml)


def swapNames(mapText, kind, a, b):
    """A saved element map with the names of elements `a` and `b` (`Face4`, `Face5`) traded:
    after `NameCount`, the map holds one line per element index, from 0."""
    lines = mapText.split("\n")
    # the type's section (`Face`, a blank line, `ChildCount`), not the header's list of types
    section = next(
        i
        for i in range(len(lines) - 2)
        if lines[i] == kind and lines[i + 2].startswith("ChildCount")
    )
    count = next(i for i in range(section, len(lines)) if lines[i].startswith("NameCount"))
    first = count + 1  # element 0's line
    i = first + int(a[len(kind) :])
    j = first + int(b[len(kind) :])
    lines[i], lines[j] = lines[j], lines[i]
    return "\n".join(lines)


def readFile(path):
    with zipfile.ZipFile(path) as archive:
        return {info.filename: archive.read(info.filename) for info in archive.infolist()}


def writeFile(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def subShadow(xml, index):
    """The shadow of the one saved reference to `index`."""
    found = re.findall(r'<Sub value="%s" shadow="([^"]*)"' % index, xml)
    if len(found) != 1:
        raise AssertionError("%d saved references to %s, not one" % (len(found), index))
    return found[0]


def stamps(path):
    """The element map versions the file's shapes are stamped with."""
    xml = readFile(path)["Document.xml"].decode("utf-8")
    return set(re.findall(r'ElementMap="([^"]*)"', xml))


class NamingGateTestBase(unittest.TestCase):
    def setUp(self):
        self.documents = []
        self.folder = os.path.realpath(tempfile.mkdtemp(prefix="NamingGate"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def tearDown(self):
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)

    def newDocument(self, config):
        solver, intern = CONFIGS[config]
        doc = models.newDocument("NamingGate")
        doc.HistoryAlgorithm = "V2"
        doc.InternNames = intern
        doc.ReferenceSolver = solver
        self.documents.append(doc.Name)
        return doc

    def open(self, path):
        doc = App.openDocument(path)
        self.documents.append(doc.Name)
        return doc

    def save(self, doc, name):
        path = os.path.join(self.folder, name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        return path

    def facePads(self, config, extra=None):
        """Saves the face pad model with Pad3 on FaceC. Returns (path, FaceC, FaceD, the shadow
        text of a reference to FaceD), the last from a first save with Pad3 on FaceD. `extra`
        adds objects to the document."""
        doc = self.newDocument(config)
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad1 = models.pad(body, profile, 10, name="Pad1")
        doc.recompute()
        pad2 = body.newObject("PartDesign::Pad", "Pad2")
        pad2.Profile = (pad1, face(contains=(10, 5, 10)).one(pad1.Shape))
        pad2.Length = 3
        doc.recompute()
        faceC = face(contains=FACE_C).one(pad2.Shape)[0]
        faceD = face(contains=FACE_D).one(pad2.Shape)[0]
        pad3 = body.newObject("PartDesign::Pad", "Pad3")
        pad3.Profile = (pad2, [faceD])
        pad3.Length = 2
        if extra:
            extra(doc)
        doc.recompute()
        self.assertTrue(pad3.isValid())
        path = os.path.join(self.folder, "FacePads.FCStd")
        doc.saveAs(path)
        shadowD = subShadow(readFile(path)["Document.xml"].decode("utf-8"), faceD)
        pad3.Profile = (pad2, [faceC])
        doc.recompute()
        self.assertTrue(pad3.isValid())
        self.assertAlmostEqual(pad3.Shape.BoundBox.XMax, 22, places=6)
        doc.save()
        App.closeDocument(doc.Name)
        return path, faceC, faceD, shadowD

    def edit(self, path, age=True, move=None, length=None):
        """Rewrites the saved file: stamps of the previous revision (`age`); a naming fix that
        traded the names of faces `move = (FaceC, FaceD, shadow of FaceD)` of Pad2, the
        reference to FaceC holding FaceD's name; Pad2's Length (`length`)."""
        files = readFile(path)
        xml = files["Document.xml"].decode("utf-8")
        if age:
            xml = ageStamps(xml)
        if move:
            faceC, faceD, shadowD = move
            shadowC = subShadow(xml, faceC)
            nameD = shadowD[: -len(faceD)]  # the name with its dot
            xml = xml.replace('shadow="%s"' % shadowC, 'shadow="%s%s"' % (nameD, faceC))
            mapFile = "Pad2.Shape.Map.txt"
            mapText = files[mapFile].decode("utf-8")
            files[mapFile] = swapNames(mapText, "Face", faceC, faceD).encode("utf-8")
        if length is not None:
            pad2 = xml.index('<Object name="Pad2"')  # in ObjectData
            at = xml.index('<Property name="Length"', pad2)
            value = re.compile(r'<Float value="[^"]*"/>').search(xml, at)
            xml = xml[: value.start()] + '<Float value="%s"/>' % length + xml[value.end() :]
        files["Document.xml"] = xml.encode("utf-8")
        writeFile(path, files)


class TestNamingGate(NamingGateTestBase):
    """A naming migration on the face pad model, in each configuration (`test<Name><Config>`)."""

    def movedNameGoesBackToItsGeometry(self, config):
        """The reproducer: Pad3's saved name now gives FaceD; after the migration recompute Pad3
        stands on FaceC, the face at the stored place, solver off and on."""
        # Arrange
        path, faceC, faceD, shadowD = self.facePads(config)
        self.edit(path, move=(faceC, faceD, shadowD))

        # Act
        doc = self.open(path)
        doc.recompute()

        # Assert
        pad3 = doc.getObject("Pad3")
        self.assertTrue(pad3.isValid(), pad3.getStatusString())
        self.assertEqual(pad3.Profile[1], [faceC])
        self.assertAlmostEqual(pad3.Shape.BoundBox.XMax, 22, places=6)
        self.assertAlmostEqual(pad3.Shape.BoundBox.XMin, 0, places=6)
        if doc.ReferenceSolver:
            report = App.getReferenceReport(pad3)
            self.assertEqual(
                [(e["status"], e["new"], e["evidence"]) for e in report],
                [("index", faceC, "migration: the name moved; %s sits where it was" % faceC)],
            )
        self.assertEqual(stamps(path) - {""}, {self.agedVersion(doc)}, "the setup")

    def agedVersion(self, doc):
        version = doc.getObject("Pad1").getCorrectElementMapVersion()
        return re.sub(r"\.F[0-9]+", ".F%d" % (currentRevision() - 1), version)

    def movedNameWithoutMigration(self, config):
        """Control: the same file with its stamps current. Solver off, the reference follows the
        name to FaceD (the defect, silently); solver on, it breaks with FaceC (where it was) and
        FaceD (its name) as the candidates (ops#105)."""
        # Arrange
        path, faceC, faceD, shadowD = self.facePads(config)
        self.edit(path, age=False, move=(faceC, faceD, shadowD))

        # Act
        doc = self.open(path)
        pad2 = doc.getObject("Pad2")
        pad2.touch()
        doc.recompute()

        # Assert
        pad3 = doc.getObject("Pad3")
        if not doc.ReferenceSolver:
            self.assertTrue(pad3.isValid())
            self.assertEqual(pad3.Profile[1], [faceD])
            self.assertAlmostEqual(pad3.Shape.BoundBox.XMin, -2, places=6)
        else:
            self.assertFalse(pad3.isValid())
            report = App.getReferenceReport(pad3)
            self.assertEqual(len(report), 1)
            self.assertEqual(report[0]["status"], "broken")
            self.assertEqual(report[0]["candidates"], [faceC, faceD])
            self.assertEqual(report[0]["candidate_roles"], ["place", "name"])

    def geometricMissBreaks(self, config):
        """As the reproducer, with Pad2 3 mm higher in the file: FaceC's old geometry is gone, so
        the reference breaks at its stored index; it never goes to FaceD, its name's element."""
        # Arrange
        path, faceC, faceD, shadowD = self.facePads(config)
        self.edit(path, move=(faceC, faceD, shadowD), length=6)

        # Act
        doc = self.open(path)
        doc.recompute()

        # Assert
        pad3 = doc.getObject("Pad3")
        self.assertFalse(pad3.isValid())
        self.assertEqual(pad3.Profile[1], ["?" + faceC])
        if doc.ReferenceSolver:
            report = App.getReferenceReport(pad3)
            self.assertEqual(len(report), 1)
            self.assertEqual(report[0]["status"], "broken")
            self.assertEqual(report[0]["candidates"], [faceD])
            self.assertEqual(report[0]["candidate_roles"], ["name"])
            self.assertEqual(
                report[0]["evidence"], "migration: the name moved; nothing sits where it was"
            )

        #   the break holds at the next recompute: the name isn't followed later either
        doc.getObject("Pad2").touch()
        doc.recompute()
        self.assertEqual(pad3.Profile[1], ["?" + faceC])

    def unmovedNamesStay(self, config):
        """A migration without a naming change: every reference stays, the model is the same,
        and the file saved after it carries the current stamps."""
        # Arrange
        path, faceC, faceD, shadowD = self.facePads(config)
        self.edit(path)

        # Act
        doc = self.open(path)
        doc.recompute()

        # Assert
        pad3 = doc.getObject("Pad3")
        self.assertTrue(pad3.isValid())
        self.assertEqual(pad3.Profile[1], [faceC])
        self.assertAlmostEqual(pad3.Shape.BoundBox.XMax, 22, places=6)
        if doc.ReferenceSolver:
            self.assertEqual(App.getReferenceReport(pad3), [])
        current = pad3.getCorrectElementMapVersion()
        doc.save()
        self.assertEqual(stamps(path) - {""}, {current})


def _addConfigTests():
    for method in (
        "movedNameGoesBackToItsGeometry",
        "movedNameWithoutMigration",
        "geometricMissBreaks",
        "unmovedNamesStay",
    ):
        for config in CONFIGS:

            def test(self, method=method, config=config):
                getattr(self, method)(config)

            test.__name__ = "test%s%s%s" % (method[0].upper(), method[1:], config)
            test.__doc__ = "%s (%s)" % (getattr(TestNamingGate, method).__doc__.split(".")[0], config)
            setattr(TestNamingGate, test.__name__, test)


_addConfigTests()


class TestNamingGateFile(NamingGateTestBase):
    """The stamps, the token, merged objects and coincident elements (ops#103)."""

    def testStampFollowsTheNames(self):
        """A file opened and saved without its migration recompute keeps its old stamps, so it
        asks again at the next open (Q2); after the recompute every shape is stamped current,
        a plain Part::Feature (which the recompute doesn't rebuild) included."""
        # Arrange
        path, faceC, faceD, shadowD = self.facePads(
            "V2", extra=lambda doc: models.feature(doc, "Plain", models.closedWire([(0, 0, 0), (1, 0, 0), (0, 1, 0)]))
        )
        self.edit(path)
        aged = stamps(path) - {""}
        self.assertEqual(len(aged), 1)

        # Act: open and save without recomputing
        doc = self.open(path)
        self.assertIn("Touched", doc.getObject("Plain").State)
        doc.save()
        App.closeDocument(doc.Name)

        # Assert
        self.assertEqual(stamps(path) - {""}, aged)

        # Act: open, recompute, save
        doc = self.open(path)
        self.assertIn("Touched", doc.getObject("Pad2").State)
        doc.recompute()
        current = doc.getObject("Pad2").getCorrectElementMapVersion()
        doc.save()
        App.closeDocument(doc.Name)

        # Assert
        self.assertEqual(stamps(path) - {""}, {current})
        doc = self.open(path)
        self.assertNotIn("Touched", doc.getObject("Plain").State)
        self.assertNotIn("Touched", doc.getObject("Pad2").State)

    def testRevisionToken(self):
        """A V2 document's version ends in `.F<n>` (`.F<n>.N2` interned), with no `.X1`; a V1
        document's has no naming revision."""
        plain = self.newDocument("V2")
        interned = self.newDocument("V2i")
        v1 = self.newDocument("V2")
        v1.HistoryAlgorithm = "V1"
        versions = [doc.addObject("Part::Box", "Box").getCorrectElementMapVersion() for doc in (plain, interned, v1)]
        self.assertRegex(versions[0], r"^15\.70200\.1\.5\.F[1-9][0-9]*$")
        self.assertEqual(versions[1], versions[0] + ".N2")
        self.assertNotIn(".F", versions[2])
        for version in versions:
            self.assertNotIn(".X1", version)

    def testMergedObjectsAreNotMigrated(self):
        """Objects merged in from a file of the previous revision aren't migrated (Q7): they are
        marked current as they are read, so they resolve by name (merging gives them new IDs, so
        a name with tags in it is found again by geometry, as before the gate)."""
        # Arrange
        path, faceC, faceD, shadowD = self.facePads("V2")
        self.edit(path)
        doc = self.newDocument("V2")
        current = doc.addObject("Part::Box", "Box").getCorrectElementMapVersion()

        # Act
        doc.mergeProject(path)

        # Assert
        for name in ("Pad1", "Pad2", "Pad3"):
            self.assertIn(doc.getObject(name)._ElementMapVersion, ("", current), name)
        merged = os.path.join(self.folder, "Merged.FCStd")
        doc.saveAs(merged)
        self.assertEqual(stamps(merged) - {""}, {current})

    def coincidentCompound(self, config):
        """A compound of two equal boxes in one place (12 faces, each in a coincident pair) and a
        reference to the second box's face at x = 10 that a naming fix moved to the next face:
        the migration takes the stored index from the two faces at the old place (rule 2)."""
        # Arrange
        doc = self.newDocument(config)
        boxA = models.box(doc, "BoxA", (10, 10, 10))
        boxB = models.box(doc, "BoxB", (10, 10, 10))
        compound = doc.addObject("Part::Compound", "Compound")
        compound.Links = [boxA, boxB]
        doc.recompute()
        right = face(contains=(10, 5, 5)).select(compound.Shape)
        self.assertEqual(len(right), 2, "the setup: two coincident faces")
        stored = right[1]
        other = "Face%d" % (int(stored[4:]) + 1)
        refs = doc.addObject("App::FeaturePython", "Refs")
        refs.addProperty("App::PropertyLinkSub", "Ref")
        refs.Ref = (compound, [other])
        doc.recompute()
        path = os.path.join(self.folder, "Compound.FCStd")
        doc.saveAs(path)
        shadowOther = subShadow(readFile(path)["Document.xml"].decode("utf-8"), other)
        refs.Ref = (compound, [stored])
        doc.recompute()
        doc.save()
        App.closeDocument(doc.Name)
        files = readFile(path)
        xml = ageStamps(files["Document.xml"].decode("utf-8"))
        shadowStored = subShadow(xml, stored)
        name = shadowOther[: -len(other)]
        xml = xml.replace('shadow="%s"' % shadowStored, 'shadow="%s%s"' % (name, stored))
        files["Document.xml"] = xml.encode("utf-8")
        mapText = files["Compound.Shape.Map.txt"].decode("utf-8")
        files["Compound.Shape.Map.txt"] = swapNames(mapText, "Face", stored, other).encode("utf-8")
        writeFile(path, files)

        # Act
        doc = self.open(path)
        doc.recompute()

        # Assert
        self.assertEqual(doc.getObject("Refs").Ref[1], [stored])

    def testCoincidentFacesTakeTheStoredIndex(self):
        """Rule 2, solver off (V2)"""
        self.coincidentCompound("V2")

    def testCoincidentFacesTakeTheStoredIndexSolver(self):
        """Rule 2, solver on (V2is)"""
        self.coincidentCompound("V2is")
