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

"""The naming gate across documents: the consumer-side pass at open (FreeCAD-CH, ops#116).

A producer file A and a consumer file B that references two faces of A. A naming fix is emulated
as TestNamingGate does it, across the two files: the two faces trade names in A's saved map, A is
stamped with the previous revision, and B's references hold each other's names, so that both
files are consistent as saved (each name gives its stored index in A's restored map) while the
build names the faces as before. B is a file saved before ops#116: no `NamingRevision`.

When A is migrated on its own and B opened later, B's references must stay on the same geometric
faces (solver on: from their saved fingerprints) or be reported broken (solver off: there is no
snapshot to search), never follow their names to the other face.
"""

import os
import re

import FreeCAD as App

from PartDesignTests.Scenarios import models
from PartDesignTests.TestNamingGate import (
    CONFIGS,
    NamingGateTestBase,
    ageStamps,
    currentRevision,
    readFile,
    stamps,
    swapNames,
    writeFile,
)
from PartDesignTests.Scenarios.harness import face

# Pad1 a box 20 x 10 x 10; Pad2 two bosses 6 x 6 x 3 on its top, at x 2..8 and 12..18. FaceC is
# the right boss's side at x = 18, FaceD the left boss's at x = 8: the same kind, size and normal.
FACE_C = (18, 5, 11.5)
FACE_D = (8, 5, 11.5)
LEFT = (2, 2, 8, 8)
RIGHT = (12, 2, 18, 8)


def xmlOf(path):
    return readFile(path)["Document.xml"].decode("utf-8")


def namingRevision(path):
    """The file's `NamingRevision`, None without one."""
    found = re.findall(r'<Document [^>]*NamingRevision="([0-9]+)"', xmlOf(path))
    return int(found[0]) if found else None


def shadowOf(xml, index):
    """The one shadow the file's references to `index` hold (an XLink's `sub` attribute)."""
    found = set(re.findall(r'sub="%s" shadow="([^"]*)"' % index, xml))
    if len(found) != 1:
        raise AssertionError("%d shadows for %s, not one" % (len(found), index))
    return found.pop()


def withShadows(xml, shadows):
    """The XML with every reference to an index of `shadows` holding its shadow there."""
    return re.sub(
        r'(sub="([^"]*)" shadow=")([^"]*)(")',
        lambda m: m.group(1) + shadows.get(m.group(2), m.group(3)) + m.group(4),
        xml,
    )


def withoutRevision(xml):
    """The XML of a file saved before ops#116: no `NamingRevision`."""
    return re.sub(r' NamingRevision="[0-9]+"', "", xml)


def faceCentre(shape):
    return shape.Faces[0].CenterOfMass


class ConsumerPassTestBase(NamingGateTestBase):
    """Two files, A and B, and the cases on them."""

    def twoFiles(self, config, throughLink=False):
        """Saves A (Pad1, Pad2) and B: `Refs.Ref` (an XLinkSub) and a binder on FaceC, and
        `Other.Ref` on FaceD; with `throughLink`, the references go through a Link to Pad2 and B
        holds no shape. Returns (path of A, path of B, FaceC, FaceD)."""
        a = self.newDocument(config)
        body = models.body(a)
        profile = models.sketch(a, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10, name="Pad1")
        bosses = models.sketch(
            a, "Bosses", models.rectangle(*LEFT) + models.rectangle(*RIGHT), body, z=10
        )
        pad2 = models.pad(body, bosses, 3, name="Pad2")
        a.recompute()
        self.assertTrue(pad2.isValid(), "the setup")
        faceC = face(contains=FACE_C).one(pad2.Shape)[0]
        faceD = face(contains=FACE_D).one(pad2.Shape)[0]
        pathA = os.path.join(self.folder, "A.FCStd")
        a.saveAs(pathA)

        b = self.newDocument(config)
        pathB = os.path.join(self.folder, "B.FCStd")
        b.saveAs(pathB)  # an external link needs its owner saved
        target = pad2
        if throughLink:
            target = b.addObject("App::Link", "Link")
            target.LinkedObject = pad2
        for name, element in (("Refs", faceC), ("Other", faceD)):
            refs = b.addObject("App::FeaturePython", name)
            refs.addProperty("App::PropertyXLinkSub", "Ref")
            refs.Ref = (target, [element])
        if not throughLink:
            binder = b.addObject("PartDesign::SubShapeBinder", "Binder")
            binder.Support = [(pad2, (faceC,))]
        b.recompute()
        b.save()
        App.closeDocument(b.Name)
        App.closeDocument(a.Name)
        return pathA, pathB, faceC, faceD

    def editFiles(self, pathA, pathB, faceC, faceD, move=True):
        """A of the previous revision, with FaceC's and FaceD's names traded by a naming fix
        (`move`); B saved before ops#116, its references holding each other's names."""
        files = readFile(pathA)
        xml = withoutRevision(ageStamps(files["Document.xml"].decode("utf-8")))
        files["Document.xml"] = xml.encode("utf-8")
        if move:
            mapText = files["Pad2.Shape.Map.txt"].decode("utf-8")
            files["Pad2.Shape.Map.txt"] = swapNames(mapText, "Face", faceC, faceD).encode("utf-8")
        writeFile(pathA, files)

        files = readFile(pathB)
        xml = withoutRevision(files["Document.xml"].decode("utf-8"))
        if move:
            nameC = shadowOf(xml, faceC)[: -len(faceC)]  # the name with its dot
            nameD = shadowOf(xml, faceD)[: -len(faceD)]
            xml = withShadows(xml, {faceC: nameD + faceC, faceD: nameC + faceD})
        files["Document.xml"] = xml.encode("utf-8")
        writeFile(pathB, files)

    def openAlone(self, path, edit=None):
        """Opens the file alone, applies `edit(doc)`, recomputes (a migration when its stamps are
        old), saves and closes it."""
        doc = self.open(path)
        if edit:
            edit(doc)
        doc.recompute()
        doc.save()
        App.closeDocument(doc.Name)

    def documentOf(self, path):
        for doc in App.listDocuments().values():
            if os.path.normcase(os.path.realpath(doc.FileName)) == os.path.normcase(
                os.path.realpath(path)
            ):
                self.documents.append(doc.Name)
                return doc
        raise AssertionError("%s isn't open" % path)

    def assertOnFaces(self, b, faceC, faceD, centre=FACE_C):
        """B's references are on FaceC and FaceD, and its binder, once recomputed, at `centre`."""
        self.assertEqual(b.getObject("Refs").Ref[1], [faceC])
        self.assertEqual(b.getObject("Other").Ref[1], [faceD])
        b.recompute()
        binder = b.getObject("Binder")
        if binder:
            self.assertTrue(binder.isValid(), binder.getStatusString())
            self.assertTrue(faceCentre(binder.Shape).isEqual(App.Vector(*centre), 1e-6))

    def assertBroken(self, b, faceC, faceD):
        """B's references are broken at their stored indices, not moved (solver off: no
        snapshot)."""
        self.assertEqual(b.getObject("Refs").Ref[1], ["?" + faceC])
        self.assertEqual(b.getObject("Other").Ref[1], ["?" + faceD])
        binder = b.getObject("Binder")
        if binder:
            self.assertEqual(binder.Support[0][1], ("?" + faceC,))
        self.assertIn("Touched", b.getObject("Refs").State)

    def assertRepaired(self, b, faceC, faceD):
        """Solver on: each reference re-derived from its saved fingerprint, with the migration's
        evidence, its owner touched."""
        for name, element in (("Refs", faceC), ("Other", faceD)):
            refs = b.getObject(name)
            report = App.getReferenceReport(refs)
            self.assertEqual(
                [(e["status"], e["new"], e["evidence"]) for e in report],
                [("index", element, "migration: the name moved; %s sits where it was" % element)],
            )
            self.assertIn("Touched", refs.State)
        self.assertOnFaces(b, faceC, faceD)

    def assertReport(self, refs, candidates, roles, evidence=None):
        report = App.getReferenceReport(refs)
        self.assertEqual(len(report), 1, report)
        self.assertEqual(report[0]["status"], "broken")
        self.assertEqual(report[0]["candidates"], candidates)
        self.assertEqual(report[0]["candidate_roles"], roles)
        if evidence:
            self.assertEqual(report[0]["evidence"], evidence)

    def producerFirst(self, config):
        """The issue's case: A migrated and saved on its own, B opened later. B's references stay
        on their faces (solver on) or break (solver off); before ops#116 they followed their names
        to each other's face in every configuration."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        self.editFiles(pathA, pathB, faceC, faceD)
        self.openAlone(pathA)
        aged = ".F%d" % (currentRevision() - 1)
        self.assertNotIn(aged, "".join(stamps(pathA)), "the setup: A migrated")

        # Act
        b = self.open(pathB)

        # Assert
        if b.ReferenceSolver:
            self.assertRepaired(b, faceC, faceD)
        else:
            self.assertBroken(b, faceC, faceD)

    def assertPassed(self, b, faceC, faceD):
        """The pass's outcome: repaired with the solver on, broken with it off."""
        if b.ReferenceSolver:
            self.assertRepaired(b, faceC, faceD)
        else:
            self.assertBroken(b, faceC, faceD)

    def targetOpenedLater(self, config):
        """B opened while A's file was missing, A opened later in the session: B's links attach
        in A's open, and the pass at its end takes them (B was opened before it)."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        self.editFiles(pathA, pathB, faceC, faceD)
        self.openAlone(pathA)
        away = os.path.join(self.folder, "away.FCStd")
        os.rename(pathA, away)
        b = self.open(pathB)
        self.assertIsNone(b.getObject("Refs").Ref, "the setup: A missing")
        os.rename(away, pathA)

        # Act
        self.open(pathA)

        # Assert
        self.assertPassed(b, faceC, faceD)

    def targetSavedAtItsPath(self, config):
        """B opened while A's file was missing, then a copy of A saved at A's path: B's links
        attach outside an open (restoreLink) and take the pass there."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        self.editFiles(pathA, pathB, faceC, faceD)
        self.openAlone(pathA)
        other = os.path.join(self.folder, "Other.FCStd")
        os.rename(pathA, other)
        b = self.open(pathB)
        a = self.open(other)

        # Act
        a.saveAs(pathA)

        # Assert
        self.assertPassed(b, faceC, faceD)

    def chain(self, config):
        """C references B's binder, B references A: opening C loads B and A; B's references into
        A (migrated alone) take the pass, and C's into B, whose names didn't move, are kept."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        b = self.open(pathB)
        c = self.newDocument(config)
        pathC = os.path.join(self.folder, "C.FCStd")
        c.saveAs(pathC)
        refs = c.addObject("App::FeaturePython", "Refs")
        refs.addProperty("App::PropertyXLinkSub", "Ref")
        refs.Ref = (b.getObject("Binder"), ["Face1"])
        # B loads partially with C, its objects that C needs: Refs and Other too
        refs.addProperty("App::PropertyXLinkList", "Keep")
        refs.Keep = [b.getObject("Refs"), b.getObject("Other")]
        c.recompute()
        c.save()
        for doc in list(App.listDocuments().values()):
            App.closeDocument(doc.Name)
        self.editFiles(pathA, pathB, faceC, faceD)
        files = readFile(pathC)
        files["Document.xml"] = withoutRevision(xmlOf(pathC)).encode("utf-8")
        writeFile(pathC, files)
        self.openAlone(pathA)

        # Act
        c = self.open(pathC)

        # Assert
        b = self.documentOf(pathB)
        self.assertEqual(c.getObject("Refs").Ref[1], ["Face1"])
        self.assertNotIn("Touched", c.getObject("Refs").State)
        self.assertPassed(b, faceC, faceD)  # recomputes B (solver on)

    def consumerFirst(self, config):
        """B opened first, A loading with it, both old: the pass leaves the references alone (A's
        names aren't current yet), and A's migration recompute re-derives them."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        self.editFiles(pathA, pathB, faceC, faceD)

        # Act
        b = self.open(pathB)
        a = self.documentOf(pathA)
        self.assertEqual(b.getObject("Refs").Ref[1], [faceC], "the names agree with A's maps")
        a.recompute()

        # Assert
        self.assertOnFaces(b, faceC, faceD)

    def shapeLessConsumer(self, config):
        """B holds no shape (a Link to Pad2 and references through it), so only its
        `NamingRevision` tells that it is old: the pass runs on it alone."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config, throughLink=True)
        self.assertEqual(stamps(pathB) - {""}, set(), "the setup: B holds no shape")
        self.editFiles(pathA, pathB, faceC, faceD)
        self.openAlone(pathA)

        # Act
        b = self.open(pathB)

        # Assert
        if b.ReferenceSolver:
            self.assertRepaired(b, faceC, faceD)
        else:
            self.assertBroken(b, faceC, faceD)

    def savedBeforeTheMigration(self, config):
        """A and B opened together and B saved without the migration recompute (the dialog
        answered No): B's revision is lowered to A's, so the pass still runs once A is migrated."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        self.editFiles(pathA, pathB, faceC, faceD)
        b = self.open(pathB)
        a = self.documentOf(pathA)
        b.save()
        App.closeDocument(b.Name)
        App.closeDocument(a.Name)
        self.assertEqual(namingRevision(pathB), 0)
        self.openAlone(pathA)

        # Act
        b = self.open(pathB)

        # Assert
        if b.ReferenceSolver:
            self.assertRepaired(b, faceC, faceD)
        else:
            self.assertBroken(b, faceC, faceD)

    def editedWhileClosed(self, config):
        """No naming change: current files, A edited while B was closed so that the two bosses
        trade places. Solver on, B's saved fingerprints are kept at the open, so ops#105's check
        breaks each reference with both faces as candidates (Q2); solver off, they follow their
        names, as within a session."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)

        def tradePlaces(a):
            bosses = a.getObject("Bosses")
            models.moveRectangle(bosses, *RIGHT, first=0)
            models.moveRectangle(bosses, *LEFT, first=4)

        self.openAlone(pathA, tradePlaces)

        # Act
        b = self.open(pathB)

        # Assert: the edit renumbered the faces; the right boss's side (FaceC's name) is now at
        # x = 8, the left boss's (FaceD's name) at x = 18
        pad2 = self.documentOf(pathA).getObject("Pad2")
        atC = face(contains=FACE_C).one(pad2.Shape)[0]
        atD = face(contains=FACE_D).one(pad2.Shape)[0]
        if b.ReferenceSolver:
            self.assertReport(b.getObject("Refs"), [atC, atD], ["place", "name"])
            self.assertReport(b.getObject("Other"), [atD, atC], ["place", "name"])
        else:
            self.assertOnFaces(b, atD, atC, centre=FACE_D)

    def movedAloneAfterMigration(self, config):
        """No name moved, but A was edited after its migration (the bosses 3 mm higher), so each
        face moved alone: kept, as ops#105 keeps it (review F4)."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        self.editFiles(pathA, pathB, faceC, faceD, move=False)
        self.openAlone(pathA, lambda a: setattr(a.getObject("Pad2"), "Length", 6))

        # Act
        b = self.open(pathB)

        # Assert
        self.assertOnFaces(b, faceC, faceD, centre=(18, 5, 13))

    def movedNameAndEditBreak(self, config):
        """A's names moved and A was edited after its migration, so nothing sits where the faces
        were: broken, with the name's element as the candidate (Q4), never moved to it."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        self.editFiles(pathA, pathB, faceC, faceD)
        self.openAlone(pathA, lambda a: setattr(a.getObject("Pad2"), "Length", 6))

        # Act
        b = self.open(pathB)

        # Assert
        if b.ReferenceSolver:
            evidence = "migration: the name moved; nothing sits where it was"
            self.assertReport(b.getObject("Refs"), [faceD], ["name"], evidence)
            self.assertReport(b.getObject("Other"), [faceC], ["name"], evidence)
            self.assertEqual(b.getObject("Refs").Ref[1], ["?" + faceC])
        else:
            self.assertBroken(b, faceC, faceD)

    def currentFiles(self, config):
        """Files saved by this build carry the current revision, and opening them changes and
        touches nothing."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        current = namingRevision(pathA)

        # Act
        b = self.open(pathB)

        # Assert
        self.assertIsNotNone(current)
        self.assertEqual(namingRevision(pathB), current)
        for name in ("Refs", "Other"):
            refs = b.getObject(name)
            self.assertNotIn("Touched", refs.State)
            self.assertEqual(App.getReferenceReport(refs), [])
        self.assertOnFaces(b, faceC, faceD)


class TestNamingConsumerPass(ConsumerPassTestBase):
    """Each case in each configuration (`test<Name><Config>`)."""


class TestNamingConsumerPassSolver(ConsumerPassTestBase):
    """Cases of the solver alone (`test<Name><Config>`, V2s and V2is)."""

    def withoutFingerprints(self, config):
        """B saved without fingerprints (Q4, review F1): the open doesn't fill them from the
        names' elements before the pass, so each reference whose name now gives another element
        is broken, with that element as the `name` candidate, never followed."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        self.editFiles(pathA, pathB, faceC, faceD)
        files = readFile(pathB)
        files["Document.xml"] = re.sub(r' fp="[^"]*"', "", xmlOf(pathB)).encode("utf-8")
        writeFile(pathB, files)
        self.openAlone(pathA)

        # Act
        b = self.open(pathB)

        # Assert
        evidence = "migration: the name moved; no fingerprint to find its place"
        self.assertReport(b.getObject("Refs"), [faceD], ["name"], evidence)
        self.assertReport(b.getObject("Other"), [faceC], ["name"], evidence)
        self.assertEqual(b.getObject("Refs").Ref[1], ["?" + faceC])
        self.assertEqual(b.getObject("Other").Ref[1], ["?" + faceD])

    def missingAtOpen(self, config):
        """A reference of an old B whose name A no longer has at all (missing at the open) is
        carried by its stored index, verified by its saved fingerprint, in reverse across the
        documents."""
        # Arrange
        pathA, pathB, faceC, faceD = self.twoFiles(config)
        self.editFiles(pathA, pathB, faceC, faceD, move=False)
        files = readFile(pathB)
        xml = xmlOf(pathB)
        shadowC = shadowOf(xml, faceC)
        name = shadowC[: -len(faceC) - 1]
        gone = name.replace(";F;", ";E;", 1)  # a name of no element of A
        self.assertNotEqual(gone, name, "the setup")
        files["Document.xml"] = withShadows(xml, {faceC: gone + "." + faceC}).encode("utf-8")
        writeFile(pathB, files)
        self.openAlone(pathA)

        # Act
        b = self.open(pathB)

        # Assert
        refs = b.getObject("Refs")
        self.assertEqual(refs.Ref[1], [faceC])
        report = App.getReferenceReport(refs)
        self.assertEqual(
            [(e["status"], e["new"], e["evidence"]) for e in report],
            [("index", faceC, "index carry, fingerprint equal")],
        )


def _addConfigTests():
    for method in (
        "producerFirst",
        "targetOpenedLater",
        "targetSavedAtItsPath",
        "chain",
        "consumerFirst",
        "shapeLessConsumer",
        "savedBeforeTheMigration",
        "editedWhileClosed",
        "movedAloneAfterMigration",
        "movedNameAndEditBreak",
        "currentFiles",
    ):
        for config in CONFIGS:

            def test(self, method=method, config=config):
                getattr(self, method)(config)

            test.__name__ = "test%s%s%s" % (method[0].upper(), method[1:], config)
            summary = getattr(TestNamingConsumerPass, method).__doc__.split(".")[0]
            test.__doc__ = "%s (%s)" % (summary, config)
            setattr(TestNamingConsumerPass, test.__name__, test)
    for method in ("withoutFingerprints", "missingAtOpen"):
        for config in ("V2s", "V2is"):

            def test(self, method=method, config=config):
                getattr(self, method)(config)

            test.__name__ = "test%s%s%s" % (method[0].upper(), method[1:], config)
            summary = getattr(TestNamingConsumerPassSolver, method).__doc__.split(".")[0]
            test.__doc__ = "%s (%s)" % (summary, config)
            setattr(TestNamingConsumerPassSolver, test.__name__, test)


_addConfigTests()
