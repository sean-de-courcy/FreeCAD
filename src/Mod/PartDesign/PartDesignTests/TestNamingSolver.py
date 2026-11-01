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

"""The reference solver's report, repair, failing owners and reverse updates (FreeCAD-CH, ops#7,
Task 2 PR 3), on designed models in documents with ReferenceSolver on. The resolutions
themselves are judged by the naming scenarios in their V2s configuration
(TestNamingScenarios)."""

import itertools
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree

import FreeCAD as App
import Part

from PartDesignTests import TestNamingDump as dump
from PartDesignTests import TestPipe as pipes
from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.moves import moveCircles
from PartDesignTests.Scenarios.harness import X, Z, edge, face


class TestNamingSolver(unittest.TestCase):
    def setUp(self):
        self.documents = []

    def tearDown(self):
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)

    def newDocument(self, solver=True):
        doc = models.newDocument("NamingSolver")
        doc.HistoryAlgorithm = "V2"
        doc.ReferenceSolver = solver
        self.documents.append(doc.Name)
        return doc

    def padWithFillet(self, doc, corner=(20, 0, 0)):
        """A pad of a rectangle 0..20 x 0..10, 10 high, and a fillet, radius 1, on its vertical
        edge at `corner`."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, edge("line", direction=Z, through=corner).one(pad.Shape))
        fillet.Radius = 1
        doc.recompute()
        self.assertTrue(fillet.isValid())
        return pad, fillet

    def testReportListsCandidatesAndRepairUsesOne(self):
        """AmbiguousHalves' model: a datum point at the centre of mass of a pad's top face, which
        a groove across the middle then splits into two halves. The point has no element to go
        to: it fails naming its reference, the report lists the halves (the pieces of its old
        face) as candidates, and repairing to one of them makes the point valid."""
        # Arrange
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10)
        sketch = models.sketch(doc, "GrooveSketch", models.rectangle(16, 2, 18, 4), body, z=10)
        groove = models.pocket(body, sketch, 4, "Groove")
        doc.recompute()
        top = face("plane", normal=Z, through=(0, 0, 10))
        point = body.newObject("PartDesign::Point", "Centre")
        point.AttachmentSupport = [(groove, top.one(groove.Shape)[0])]
        point.MapMode = "CenterOfMass"
        doc.recompute()
        self.assertTrue(point.isValid())

        # Act
        models.moveRectangle(sketch, 9, -1, 11, 11)
        doc.recompute()

        # Assert
        self.assertFalse(point.isValid())
        self.assertRegex(
            point.getStatusString(), r"Missing face reference: Face\d+ \(AttachmentSupport\[0\]"
        )
        report = App.getReferenceReport(point)
        self.assertEqual(len(report), 1)
        entry = report[0]
        self.assertEqual(
            (entry["property"], entry["index"], entry["status"]),
            ("AttachmentSupport", 0, "broken"),
        )
        self.assertTrue(entry["sub"].startswith("?Face"))
        self.assertEqual(entry["target"], groove.FullName)
        halves = top.select(groove.Shape)
        #   the pieces first, then any other survivor of tier 1
        self.assertEqual(sorted(entry["candidates"][:2]), sorted(halves))
        self.assertEqual(len(entry["candidate_names"]), len(entry["candidates"]))
        for name in entry["candidates"]:
            self.assertIn(name, entry["evidence"] + " " + point.getStatusString())

        #   a name that isn't a candidate is refused
        other = face("plane", normal=X, through=(20, 0, 0)).one(groove.Shape)[0]
        with self.assertRaises(ValueError):
            App.repairReference(point, "AttachmentSupport", 0, other)
        with self.assertRaises(ValueError):
            App.repairReference(point, "AttachmentSupport", 1, halves[0])

        #   a candidate repairs it
        App.repairReference(point, "AttachmentSupport", 0, halves[0])
        doc.recompute()
        self.assertTrue(point.isValid())
        self.assertEqual(point.AttachmentSupport, [(groove, (halves[0],))])
        self.assertEqual(App.getReferenceReport(point), [])

    def testAttacherPlacementOnCoplanarPieces(self):
        """What the attachment's equivalence relies on (Task 2 PR 5): a groove across a pad's
        top face splits it into two coplanar pieces; FlatFace gives the same placement on
        either, CenterOfMass a different one on each."""
        # Arrange
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10)
        sketch = models.sketch(doc, "Groove", models.rectangle(9, -1, 11, 11), body, z=10)
        groove = models.pocket(body, sketch, 4, "Groove")
        doc.recompute()
        halves = face("plane", normal=Z, through=(0, 0, 10)).select(groove.Shape)
        self.assertEqual(len(halves), 2)

        def placement(engineType, mode, name):
            engine = Part.AttachEngine(engineType)
            engine.References = [(groove, name)]
            engine.Mode = mode
            return engine.calculateAttachedPlacement(App.Placement())

        def same(a, b):
            return (a.Base - b.Base).Length < 1e-7 and a.Rotation.isSame(b.Rotation, 1e-12)

        # Act
        flat = [placement("Attacher::AttachEngine3D", "FlatFace", n) for n in halves]
        centre = [placement("Attacher::AttachEnginePoint", "CenterOfMass", n) for n in halves]

        # Assert
        self.assertTrue(same(flat[0], flat[1]), f"{flat[0]} != {flat[1]}")
        self.assertFalse(same(centre[0], centre[1]), f"{centre[0]} == {centre[1]}")

    def testBinderWithoutItsFaceFails(self):
        """A pad 0..20 x 0..10 x 10 with a slot (x 8..12, y 4..6, through all), and a
        SubShapeBinder of the slot feature's front face. The slot becomes a step along the whole
        front (x -1..21, y -1..3), which removes the face. The binder fails, naming its
        reference, instead of keeping its old shape or binding nothing (ops#69)."""
        # Arrange
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10)
        sketch = models.sketch(doc, "SlotSketch", models.rectangle(8, 4, 12, 6), body, z=10)
        slot = models.pocketThroughAll(body, sketch, "Slot")
        doc.recompute()
        front = face("plane", normal=(0, -1, 0), through=(0, 0, 0))
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(slot, tuple(front.one(slot.Shape)))]
        doc.recompute()
        self.assertTrue(binder.isValid())

        # Act
        models.moveRectangle(doc.SlotSketch, -1, -1, 21, 3)
        doc.recompute()

        # Assert
        self.assertFalse(binder.isValid())
        self.assertIn("(Support[0], ", binder.getStatusString())

    def stale(self, doc, feature):
        """Recomputes `feature` as after an element-map version change (as Task 1's files will
        cause): its references are updated in reverse."""
        feature._ElementMapVersion = "stale"
        feature.touch()
        doc.recompute()

    def openWithStaleName(self):
        """The fillet's reference with a stale mapped name written into the saved file (no name
        relates it to the pad's edges), its fingerprint kept; the file opened again. Returns
        (document, the reference's index name)."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        index = fillet.Base[1][0]
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Reverse.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        stale = ";_;g9;_;1;SKT;0;E;0;SRC;_." + index
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        xml = files["Document.xml"].decode("utf-8")
        found = re.findall(r'(<Sub value="%s" shadow=")([^"]*)(" fp=")' % index, xml)
        self.assertEqual(len(found), 1)  # the setup: the fillet's reference, with a fingerprint
        xml = xml.replace("".join(found[0]), found[0][0] + stale + found[0][2])
        files["Document.xml"] = xml.encode("utf-8")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        doc = App.openDocument(path)
        self.documents.append(doc.Name)
        return doc, index

    def testStaleNameIsFoundByItsFingerprintOnOpen(self):
        """No name relates the stale name to the pad's edges, but the edge is in its place: on
        opening, tiers 2 and 3 find it against the saved fingerprint (Task 2 PR 4)."""
        doc, index = self.openWithStaleName()
        self.assertEqual(doc.Fillet.Base[1], [index])
        report = App.getReferenceReport(doc.Fillet)
        self.assertEqual([(e["status"], e["tier"]) for e in report], [("resolved", 3)])

    def testReverseUpdateCarriesTheIndexWhenTheFingerprintAgrees(self):
        """A reference whose mapped name is gone after an element-map version change is
        re-derived by its index, checked against its saved fingerprint: the same geometry
        resolves ("index"). With tier 3 kept from deciding (NamingSolver/Tier3Distance so large
        that every other edge is within d_max), the exact place off (the edge is at its place,
        ops#394) and the guess rules off (their wider tier 3 would decide), reopening the
        stale-name file breaks the reference, and the version change then restores it."""
        # Arrange
        group = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/NamingSolver")
        group.SetFloat("Tier3Distance", 100.0)
        self.addCleanup(group.RemFloat, "Tier3Distance")
        group.SetBool("ExactPlace", False)
        self.addCleanup(group.RemBool, "ExactPlace")
        group.SetBool("Guess", False)
        self.addCleanup(group.RemBool, "Guess")
        doc, index = self.openWithStaleName()
        pad, fillet = doc.Pad, doc.Fillet
        self.assertEqual(fillet.Base[1], ["?" + index])

        # Act
        self.stale(doc, pad)

        # Assert
        self.assertTrue(fillet.isValid())
        self.assertEqual(fillet.Base[1], [index])
        report = App.getReferenceReport(fillet)
        self.assertEqual([(e["status"], e["new"]) for e in report], [("index", index)])

    def testReverseUpdateBreaksWhenTheFingerprintDiffers(self):
        """FilletCornerCut's model, with the version change in the same recompute: the edge at
        the old index is another one (a new corner edge), so the fingerprint differs and the
        reference breaks with that element as the candidate."""
        # Arrange
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        index = fillet.Base[1][0]

        # Act
        models.setLines(doc.Profile, {0: ((0, 0), (19, 0)), 1: ((20, 1), (20, 10))})
        doc.Profile.addGeometry(models.polyline([(19, 0), (20, 1)]), False)
        self.stale(doc, pad)

        # Assert
        self.assertFalse(fillet.isValid())
        report = App.getReferenceReport(fillet)
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["status"], "broken")
        self.assertEqual(report[0]["candidates"], [index])
        self.assertEqual(report[0]["evidence"], "index carry, fingerprint differs")

    @unittest.skipUnless(dump.OLD_FILE_TESTS, dump.OLD_FILE_SKIP)
    def testSolverOffChangesNothing(self):
        """The report and the recompute check need the switch: the same broken fillet in a V2
        document without it reports nothing, and its owner isn't failed by the check."""
        doc = self.newDocument(solver=False)
        pad, fillet = self.padWithFillet(doc)
        models.setLines(doc.Profile, {0: ((0, 0), (19, 0)), 1: ((20, 1), (20, 10))})
        doc.Profile.addGeometry(models.polyline([(19, 0), (20, 1)]), False)
        doc.recompute()
        # the solver's check names candidates; a solver-off owner's error doesn't
        self.assertNotIn("candidates", fillet.getStatusString())
        self.assertEqual([e for e in App.getReferenceReport(fillet) if e["status"] != "broken"], [])

    # Tiers 2 and 3 (Task 2 PR 4): the saved fingerprint is the only geometry evidence.

    def redraw(self, doc):
        """Deletes the profile's lines and draws the rectangle again from its right back corner,
        the other way round (as the SketchRedraw scenario): the same geometry, new geometry IDs,
        so no name relates the old edges to the new ones."""
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        doc.recompute()

    def testRedrawnSketchResolvesByGeometry(self):
        """Every sketch line drawn again: the filleted edge is back in its place under a new
        name. No structural candidate; tiers 2 and 3 find it against the saved fingerprint."""
        # Arrange
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)

        # Act
        self.redraw(doc)

        # Assert
        self.assertTrue(fillet.isValid())
        corner = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)
        self.assertEqual(fillet.Base[1], corner)
        report = App.getReferenceReport(fillet)
        self.assertEqual([(e["status"], e["tier"]) for e in report], [("resolved", 3)])
        self.assertTrue(report[0]["evidence"].startswith("no structural candidate, tier 3"))

    def breakThenRedraw(self, stripFingerprint):
        """FilletCornerCut's edit breaks the fillet; the document is saved (its `fp` attribute
        taken out if `stripFingerprint`) and opened again; then the rectangle is drawn again,
        which puts the edge back in its place under a new name."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        models.setLines(doc.Profile, {0: ((0, 0), (19, 0)), 1: ((20, 1), (20, 10))})
        doc.Profile.addGeometry(models.polyline([(19, 0), (20, 1)]), False)
        doc.recompute()
        self.assertFalse(fillet.isValid())
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Broken.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        xml = files["Document.xml"].decode("utf-8")
        found = re.findall(r'<Sub value="\?Edge[0-9]+" shadow="[^"]*"( fp="[^"]*")', xml)
        self.assertEqual(len(found), 1)  # the setup: the broken reference kept its fingerprint
        if stripFingerprint:
            xml = xml.replace(found[0], "")
        files["Document.xml"] = xml.encode("utf-8")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        doc = App.openDocument(path)
        self.documents.append(doc.Name)
        for obj in doc.Objects:
            obj.touch()
        doc.recompute()
        self.assertFalse(doc.Fillet.isValid())
        self.redraw(doc)
        return doc.Pad, doc.Fillet

    def testBrokenReferenceIsFoundByItsSavedFingerprint(self):
        """The retry after a reopen uses the fingerprint the broken reference kept."""
        pad, fillet = self.breakThenRedraw(stripFingerprint=False)
        self.assertTrue(fillet.isValid())
        self.assertEqual(
            fillet.Base[1], edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)
        )
        report = App.getReferenceReport(fillet)
        self.assertEqual([(e["status"], e["tier"]) for e in report], [("resolved", 3)])

    def testReferenceWithoutAFingerprintStaysBroken(self):
        """The same without the saved fingerprint (an old file): tiers 2 and 3 can't run, so
        the reference stays broken although its edge is back."""
        pad, fillet = self.breakThenRedraw(stripFingerprint=True)
        self.assertFalse(fillet.isValid())
        self.assertTrue(fillet.Base[1][0].startswith("?Edge"))
        report = App.getReferenceReport(fillet)
        self.assertEqual([e["status"] for e in report], ["broken"])

    def testTier3TolerancesAreParameters(self):
        """The rectangle drawn again 5 mm over. With the default tolerances (d_max 1 % of the
        diagonal, the second nearest 3 times as far) the fillet breaks. With
        NamingSolver/Tier3Distance at 0.3 (d_max 7.3 mm) and Tier3GapFactor at 2, the moved edge
        (5 mm) is within reach and the next one (11.2 mm) far enough, so it resolves to it."""
        group = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/NamingSolver")
        self.addCleanup(group.RemFloat, "Tier3Distance")
        self.addCleanup(group.RemFloat, "Tier3GapFactor")

        def redrawMoved(doc):
            doc.Profile.deleteAllGeometry()
            doc.Profile.addGeometry(models.polygon([(25, 10), (25, 0), (5, 0), (5, 10)]), False)
            doc.recompute()

        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        redrawMoved(doc)
        self.assertFalse(fillet.isValid())

        group.SetFloat("Tier3Distance", 0.3)
        group.SetFloat("Tier3GapFactor", 2.0)
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        redrawMoved(doc)
        self.assertTrue(fillet.isValid())
        self.assertEqual(
            fillet.Base[1], edge("line", direction=Z, through=(25, 0, 0)).one(pad.Shape)
        )

    # Splits (Task 2 PR 7): Expand, `from` and collapse, the continuation.

    def savedSubs(self, doc, objectName, propertyName):
        """The `<Sub>` attributes of `objectName.propertyName` (a PropertyLinkSub) as `doc`
        saves them now."""
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Saved.FCStd")
        doc.saveCopy(path)
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("Document.xml"))
        for obj in root.iter("Object"):
            if obj.get("name") != objectName:
                continue
            for prop in obj.iter("Property"):
                if prop.get("name") == propertyName:
                    return [dict(sub.attrib) for sub in prop.iter("Sub")]
        raise AssertionError(f"{objectName}.{propertyName} isn't saved")

    def froms(self, doc):
        return [s.get("from") for s in self.savedSubs(doc, "Fillet", "Base")]

    def ribAcrossFillet(self, doc):
        """SplitFilletFuse's model: a rib (x 8..12, y 3..7, 12 high) on a block 0..20 x 0..10 x
        10, a fillet (radius 1) on the block's front top edge. Returns (rib, fillet, the edge's
        mapped name)."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10)
        rib = models.sketch(doc, "RibSketch", models.rectangle(8, 3, 12, 7), body)
        rib = models.pad(body, rib, 12, name="Rib")
        doc.recompute()
        front = edge("line", direction=X, through=(0, 0, 10)).one(rib.Shape)
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib, front)
        fillet.Radius = 1
        doc.recompute()
        self.assertTrue(fillet.isValid())
        name = rib.Shape.getElementMappedName(front[0])
        name = name[0] if isinstance(name, (list, tuple)) else name
        return rib, fillet, name

    def frontPieces(self, rib):
        return sorted(edge("line", direction=X, through=(0, 0, 10)).select(rib.Shape))

    def testExpansionSavesFromAndCollapses(self):
        """The rib moves across the filleted edge: the fillet takes both pieces, each saved with
        `from` = the edge's old name; reopened, they keep it; the rib moved back, the pieces
        merge back into the one edge, and `from` goes."""
        # Arrange
        doc = self.newDocument()
        rib, fillet, name = self.ribAcrossFillet(doc)

        # Act: split
        models.moveRectangle(doc.RibSketch, 8, -3, 12, 3)
        doc.recompute()

        # Assert
        self.assertTrue(fillet.isValid())
        self.assertEqual(len(fillet.Base[1]), 2)
        self.assertEqual(sorted(fillet.Base[1]), self.frontPieces(rib))
        self.assertEqual(self.froms(doc), [name, name])
        report = App.getReferenceReport(fillet)
        self.assertEqual([(e["status"], e["tier"]) for e in report], [("expanded", 1)])
        self.assertEqual(sorted(report[0]["pieces"]), self.frontPieces(rib))

        #   reopened, the pieces keep their `from`
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Expanded.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        self.documents.append(doc.Name)
        rib, fillet = doc.Rib, doc.Fillet
        self.assertEqual(len(fillet.Base[1]), 2)
        self.assertEqual(self.froms(doc), [name, name])

        # Act: merge
        models.moveRectangle(doc.RibSketch, 8, 3, 12, 7)
        doc.recompute()

        # Assert
        self.assertTrue(fillet.isValid())
        front = edge("line", direction=X, through=(0, 0, 10)).one(rib.Shape)
        self.assertEqual(fillet.Base[1], front)
        self.assertEqual(self.froms(doc), [None])

    def testUndoOfAnExpansion(self):
        """Undo gives the one reference back without `from`; redo the pieces, with it (a
        property is restored through Paste)."""
        doc = self.newDocument()
        doc.UndoMode = 1
        rib, fillet, name = self.ribAcrossFillet(doc)
        doc.openTransaction("split")
        models.moveRectangle(doc.RibSketch, 8, -3, 12, 3)
        doc.recompute()
        doc.commitTransaction()
        self.assertEqual(len(fillet.Base[1]), 2)

        doc.undo()
        self.assertEqual(len(fillet.Base[1]), 1)
        self.assertEqual(self.froms(doc), [None])

        doc.redo()
        self.assertEqual(len(fillet.Base[1]), 2)
        self.assertEqual(self.froms(doc), [name, name])

    def testSetterKeepsFromOfTheSameSubs(self):
        """Setting the property again to the same subs keeps `from`, as it keeps the records
        (ops#504 E2, I-S10, PLAN decision 142). A piece kept without the other loses it, so
        that no merge widens it back to the whole edge (the review of fork PR 386,
        PieceKeptThenMergedBack); a sub chosen anew starts without it."""
        doc = self.newDocument()
        rib, fillet, name = self.ribAcrossFillet(doc)
        models.moveRectangle(doc.RibSketch, 8, -3, 12, 3)
        doc.recompute()
        self.assertEqual(self.froms(doc), [name, name])
        pieces = list(fillet.Base[1])

        fillet.Base = (rib, pieces)
        self.assertEqual(self.froms(doc), [name, name])

        other = edge("line", direction=Z, through=(0, 0, 0)).one(rib.Shape)
        fillet.Base = (rib, pieces[:1] + other)
        self.assertEqual(self.froms(doc), [None, None])

    def twoRibsAcrossFillet(self, doc):
        """A 30 long block (0..30 x 0..10 x 10) with two ribs (x 8..12 and x 20..24, y 3..7, 12
        high) and a fillet (radius 1) on the block's front top edge. Returns (the second rib,
        the fillet, the front top edge's predicate)."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 30, 10), body)
        models.pad(body, profile, 10)
        sketch = models.sketch(doc, "RibSketch", models.rectangle(8, 3, 12, 7), body)
        models.pad(body, sketch, 12, name="Rib")
        sketch2 = models.sketch(doc, "RibSketch2", models.rectangle(20, 3, 24, 7), body)
        rib2 = models.pad(body, sketch2, 12, name="Rib2")
        doc.recompute()
        front = edge("line", direction=X, through=(0, 0, 10))
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rib2, front.one(rib2.Shape))
        fillet.Radius = 1
        doc.recompute()
        return rib2, fillet, front

    def guesses(self, doc):
        return [s.get("guess") for s in self.savedSubs(doc, "Fillet", "Base")]

    def rightPiece(self, rib2, front):
        right = [e for e in front.select(rib2.Shape) if rib2.Shape.getElement(e).CenterOfMass.x > 24]
        self.assertEqual(len(right), 1)
        return right

    def testSetterEndsTheGuessOfAPieceKeptAlone(self):
        """A piece kept without the other loses its guess record too: its original is the whole
        edge, and when the edge is whole again the record would widen the piece to it silently
        (the review of fork PR 386, TrimmedPieceKeepsItsGuessRecord). The fillet breaks instead,
        as it does without the record."""
        # Arrange: the second rib splits the edge, the first splits and joins it again, which
        # leaves the right piece a tier 3 guess
        doc = self.newDocument()
        rib2, fillet, front = self.twoRibsAcrossFillet(doc)
        for sketch, rectangle in (
            (doc.RibSketch2, (20, -3, 24, 3)),
            (doc.RibSketch, (8, -3, 12, 3)),
            (doc.RibSketch, (8, 3, 12, 7)),
        ):
            models.moveRectangle(sketch, *rectangle)
            doc.recompute()
        right = self.rightPiece(rib2, front)
        self.assertEqual(sorted(fillet.Base[1]), sorted(front.select(rib2.Shape)))
        self.assertEqual(sorted(self.guesses(doc)), ["expanded", "tier3"])
        fillet.Base = (rib2, list(fillet.Base[1]))
        self.assertEqual(sorted(self.guesses(doc)), ["expanded", "tier3"])

        # Act
        fillet.Base = (rib2, right)

        # Assert
        self.assertEqual(self.guesses(doc), [None])
        self.assertEqual(self.froms(doc), [None])
        models.moveRectangle(doc.RibSketch2, 20, 3, 24, 7)
        doc.recompute()
        self.assertFalse(fillet.isValid())
        self.assertNotEqual(fillet.Base[1], front.one(rib2.Shape))

    def testSetterEndsTheExpandedRecordOfAPieceKeptAlone(self):
        """A piece kept alone right after the split loses its `expanded` record too: a later
        guess of the piece takes the record's original, the whole edge, and snaps back to it
        when the edge is whole again (the review of fork PR 386 round 3,
        FilletPieceTrimmedEarlyThenSplitMerged). The fillet breaks instead."""
        # Arrange
        doc = self.newDocument()
        rib2, fillet, front = self.twoRibsAcrossFillet(doc)
        models.moveRectangle(doc.RibSketch2, 20, -3, 24, 3)
        doc.recompute()
        right = self.rightPiece(rib2, front)
        self.assertEqual(self.guesses(doc), ["expanded", "expanded"])

        # Act
        fillet.Base = (rib2, right)

        # Assert
        self.assertEqual(self.guesses(doc), [None])
        self.assertEqual(self.froms(doc), [None])
        for rectangle in ((8, -3, 12, 3), (8, 3, 12, 7)):
            models.moveRectangle(doc.RibSketch, *rectangle)
            doc.recompute()
        models.moveRectangle(doc.RibSketch2, 20, 3, 24, 7)
        doc.recompute()
        self.assertFalse(fillet.isValid())
        self.assertNotEqual(fillet.Base[1], front.one(rib2.Shape))

    def notch(self, doc):
        """Cuts a notch (x 8..12, 2 deep) into the front of the profile: the front line ends at
        x = 8, and four new lines follow, the last one the rest of the side (x 12..20)."""
        models.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(models.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)
        doc.recompute()

    def testContinuationReportsTier4(self):
        """SplitFilletNotch's model: the fillet's edge keeps its name on 0..8; the rest (12..20)
        comes from a new line. The fillet takes both, at tier 4."""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        front = edge("line", direction=X, through=(0, 0, 10))
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, front.one(pad.Shape))
        fillet.Radius = 1
        doc.recompute()

        self.notch(doc)

        self.assertTrue(fillet.isValid())
        self.assertEqual(sorted(fillet.Base[1]), sorted(front.select(pad.Shape)))
        report = App.getReferenceReport(fillet)
        self.assertEqual([(e["status"], e["tier"]) for e in report], [("expanded", 4)])
        self.assertEqual(sorted(report[0]["pieces"]), sorted(front.select(pad.Shape)))

    def testContinuationBreaksExternalAndRepairUsesAPiece(self):
        """ExternalSplit's model: a sketch's external edge on the pad's front top edge, which a
        notch splits; the kept piece is an exact hit. The reference breaks with both pieces as
        candidates, stays broken on the next recompute, and a repair to one piece holds."""
        # Arrange
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        front = edge("line", direction=X, through=(0, 0, 10))
        sketch = models.sketch(doc, "OnFront", [], body, z=10)
        sketch.addExternal(pad.Name, front.one(pad.Shape)[0])
        doc.recompute()
        self.assertTrue(sketch.isValid())

        # Act
        self.notch(doc)

        # Assert
        pieces = sorted(front.select(pad.Shape))
        self.assertEqual(len(pieces), 2)
        self.assertFalse(sketch.isValid())
        report = App.getReferenceReport(sketch)
        self.assertEqual(len(report), 1)
        entry = report[0]
        self.assertEqual(
            (entry["property"], entry["index"], entry["status"]),
            ("ExternalGeometry", 0, "broken"),
        )
        self.assertEqual(sorted(entry["candidates"]), pieces)
        self.assertTrue(entry["evidence"].startswith("split: the old edge continues in"))
        self.assertEqual(sorted(entry["candidate_roles"]), ["name", "piece"])  # ops#105

        #   the break is stable
        pad.touch()
        doc.recompute()
        self.assertFalse(sketch.isValid())

        #   a repair to one piece holds, and the external geometry follows it: no geometry is
        #   left behind under the old reference (the sketch would fail on it, ops#72)
        externalCount = len(sketch.ExternalGeo)
        App.repairReference(sketch, "ExternalGeometry", 0, pieces[0])
        doc.recompute()
        self.assertTrue(sketch.isValid())
        pad.touch()
        doc.recompute()
        self.assertTrue(sketch.isValid())
        self.assertEqual(len(sketch.ExternalGeo), externalCount)
        piece = pad.Shape.getElement(pieces[0])
        line = sketch.ExternalGeo[-1]
        ends = sorted([(p.x, p.y) for p in (line.StartPoint, line.EndPoint)])
        expected = sorted([(v.X, v.Y) for v in piece.Vertexes])
        for (x, y), (ex, ey) in zip(ends, expected):
            self.assertAlmostEqual(x, ex, places=6)
            self.assertAlmostEqual(y, ey, places=6)

    @unittest.skipUnless(dump.OLD_FILE_TESTS, dump.OLD_FILE_SKIP)
    def testSolverOffSavesNoFrom(self):
        """Without the switch, nothing saves `from`, and the fillet keeps one reference (the
        solver-off behaviour)."""
        doc = self.newDocument(solver=False)
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, edge("line", direction=X, through=(0, 0, 10)).one(pad.Shape))
        fillet.Radius = 1
        doc.recompute()

        self.notch(doc)

        self.assertEqual(len(fillet.Base[1]), 1)
        self.assertEqual(self.froms(doc), [None])

    def multiMatchOn(self):
        """Turns the user parameter NamingMultiMatch on for the dress-ups created next (it is
        read when a feature is created), and back as it was after the test."""
        group = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        had = "NamingMultiMatch" in group.GetBools()
        old = group.GetBool("NamingMultiMatch", False)
        group.SetBool("NamingMultiMatch", True)
        self.addCleanup(
            lambda: (
                group.SetBool("NamingMultiMatch", old) if had else group.RemBool("NamingMultiMatch")
            )
        )

    def testMultiMatchFlagsAreIgnoredInSolverDocuments(self):
        """With NamingMultiMatch on, a solver document's fillet still follows the solver alone
        (ops#88): the split expands with `from`, and after a reopen the pieces merge back."""
        # Arrange
        self.multiMatchOn()
        doc = self.newDocument()
        rib, fillet, name = self.ribAcrossFillet(doc)

        # Act: split, reopen
        models.moveRectangle(doc.RibSketch, 8, -3, 12, 3)
        doc.recompute()
        report = App.getReferenceReport(fillet)
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "MultiMatch.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        self.documents.append(doc.Name)
        rib, fillet = doc.Rib, doc.Fillet

        # Assert
        self.assertEqual([(e["status"], e["tier"]) for e in report], [("expanded", 1)])
        self.assertEqual(sorted(fillet.Base[1]), self.frontPieces(rib))
        self.assertEqual(self.froms(doc), [name, name])

        # Act: merge
        models.moveRectangle(doc.RibSketch, 8, 3, 12, 7)
        doc.recompute()

        # Assert
        self.assertTrue(fillet.isValid())
        front = edge("line", direction=X, through=(0, 0, 10)).one(rib.Shape)
        self.assertEqual(fillet.Base[1], front)
        self.assertEqual(self.froms(doc), [None])

    def testMultiMatchExpansionBreaksWhenMergedAfterTheSolverIsTurnedOn(self):
        """A known limit (ops#88): the multi-match flags expand a split in a solver-off document,
        which keeps no `from`. With the solver turned on afterwards, the merged pieces can't
        collapse: each breaks, loudly, with the whole edge among its candidates."""
        # Arrange
        self.multiMatchOn()
        doc = self.newDocument(solver=False)
        rib, fillet, name = self.ribAcrossFillet(doc)
        models.moveRectangle(doc.RibSketch, 8, -3, 12, 3)
        doc.recompute()
        self.assertEqual(sorted(fillet.Base[1]), self.frontPieces(rib))
        doc.ReferenceSolver = True

        # Act
        models.moveRectangle(doc.RibSketch, 8, 3, 12, 7)
        doc.recompute()

        # Assert
        self.assertFalse(fillet.isValid())
        front = edge("line", direction=X, through=(0, 0, 10)).one(rib.Shape)
        report = App.getReferenceReport(fillet)
        self.assertEqual(
            [(e["index"], e["status"]) for e in report], [(0, "broken"), (1, "broken")]
        )
        for entry in report:
            self.assertIn(front[0], entry["candidates"])

    @staticmethod
    def topCircle(x, y):
        return edge("circle", center=(x, y, 10), radius=3)

    def tradedBosses(self, doc):
        """BossesTradePlaces' model with one fillet, on boss a's top circle; then the circles
        trade places. Returns the bosses' sketch, their pad and the fillet."""
        body = models.body(doc)
        plate = models.sketch(doc, "Plate", models.rectangle(0, 0, 30, 30), body)
        models.pad(body, plate, 5, name="PlatePad")
        circles = [models.circle(10, 15, 3), models.circle(20, 15, 3)]
        bosses = models.sketch(doc, "Bosses", circles, body, z=5)
        bossPad = models.pad(body, bosses, 5, name="BossPad")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (bossPad, self.topCircle(10, 15).one(bossPad.Shape))
        fillet.Radius = 0.5
        doc.recompute()
        self.assertTrue(fillet.isValid())
        moveCircles(bosses, {0: (20, 15), 1: (10, 15)})
        doc.recompute()
        return bosses, bossPad, fillet

    def testMovedBossIsAmbiguousAndRepairToItsPlaceHolds(self):
        """BossesTradePlaces' model with one fillet, on boss a's top circle (ops#105): the
        circles trade places, so a's circle moved and b's sits where it was. The fillet fails
        naming both, the element at the old place first; the break is stable; a repair to that
        element holds, and the fillet then follows that boss."""
        # Arrange, Act
        doc = self.newDocument()
        bosses, bossPad, fillet = self.tradedBosses(doc)
        topCircle = self.topCircle

        # Assert
        place = topCircle(10, 15).one(bossPad.Shape)[0]
        named = topCircle(20, 15).one(bossPad.Shape)[0]
        self.assertFalse(fillet.isValid())
        report = App.getReferenceReport(fillet)
        self.assertEqual(len(report), 1)
        entry = report[0]
        self.assertEqual(entry["status"], "broken")
        self.assertEqual(entry["candidates"], [place, named])
        self.assertEqual(entry["candidate_roles"], ["place", "name"])
        self.assertAlmostEqual(entry["candidate_distances"][0], 0.0, places=6)
        self.assertAlmostEqual(entry["candidate_distances"][1], 10.0, places=6)
        self.assertEqual(entry["evidence"], f"moved 10.000 mm; {place} sits where it was")
        self.assertIn(
            f"Ambiguous edge reference: {named} moved and {place} sits where it was",
            fillet.getStatusString(),
        )

        #   the break is stable
        bossPad.touch()
        doc.recompute()
        self.assertFalse(fillet.isValid())

        #   a repair to the element at the old place holds, and later edits follow it
        App.repairReference(fillet, "Base", 0, place)
        doc.recompute()
        self.assertTrue(fillet.isValid())
        moveCircles(bosses, {1: (10, 22)})
        doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertEqual(fillet.Base[1], topCircle(10, 22).one(bossPad.Shape))

    def testMovedBossRepairToItsNameFollowsIt(self):
        """As above, repaired to the `name` candidate: the fillet follows boss a to its new
        place, and a later move of boss b (now on a's old place) leaves it there (ops#105)."""
        # Arrange
        doc = self.newDocument()
        bosses, bossPad, fillet = self.tradedBosses(doc)
        named = self.topCircle(20, 15).one(bossPad.Shape)[0]
        self.assertFalse(fillet.isValid())
        self.assertEqual(App.getReferenceReport(fillet)[0]["candidate_roles"], ["place", "name"])

        # Act
        App.repairReference(fillet, "Base", 0, named)
        doc.recompute()

        # Assert
        self.assertTrue(fillet.isValid())
        self.assertEqual(fillet.Base[1], self.topCircle(20, 15).one(bossPad.Shape))
        moveCircles(bosses, {1: (10, 22)})
        doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertEqual(fillet.Base[1], self.topCircle(20, 15).one(bossPad.Shape))

    # The warning state, the saved guess record and partial regeneration (ops#127, design note
    # N2: P5). A reference resolved by geometry alone (tier 3 here) computes with a warning and a
    # record of its original, until it is accepted, repaired or set, or the original comes back.

    def savedObject(self, doc, objectName):
        """The attributes of `objectName`'s entry in the saved document's object list."""
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Saved.FCStd")
        doc.saveCopy(path)
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("Document.xml"))
        for obj in root.iter("Object"):
            if obj.get("name") == objectName and obj.get("type"):
                return dict(obj.attrib)
        raise AssertionError(f"{objectName} isn't saved")

    def redrawnFillet(self):
        """A fillet whose edge was found again by geometry alone (the redrawn rectangle, tier 3).
        Returns (document, pad, fillet, the reference's index before the redraw)."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        original = fillet.Base[1][0]
        self.redraw(doc)
        self.assertTrue(fillet.isValid())
        return doc, pad, fillet, original

    def testGeometryResolutionWarnsWithARecord(self):
        """The redrawn rectangle's edge, found by tier 3: the fillet computes, with the Warning
        state and, the edge being where it was, the short same-place text (ops#391); the
        reference holds the edge, and its saved record names the original."""
        self.quietRedraws()
        doc, pad, fillet, original = self.redrawnFillet()

        corner = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)
        self.assertEqual(fillet.Base[1], corner)
        self.assertIn("Warning", fillet.State)
        self.assertEqual(
            fillet.getStatusString(),
            "Warning: Edge reference found again in the same place (Base[0])",
        )
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual((entry["status"], entry["tier"]), ("resolved", 3))
        self.assertEqual(entry["guess_kind"], "tier3")
        self.assertEqual(entry["original"]["index"], original)
        self.assertEqual(entry["warning"], fillet.getStatusString()[len("Warning: ") :])
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        self.assertEqual(sub["guess"], "tier3")
        self.assertTrue(sub["orig"].endswith("." + original))
        self.assertIn("fp", sub)
        self.assertTrue(self.savedObject(doc, "Fillet")["Warning"].startswith("Edge reference"))

        #   a recompute that changes nothing keeps it, and the reference
        fillet.touch()
        doc.recompute()
        self.assertIn("Warning", fillet.State)
        self.assertEqual(fillet.Base[1], corner)

    def testGuessSnapsBackWhenTheOriginalReturns(self):
        """Undoing the redraw brings the old sketch geometry back, and with it the edge's old
        name: the reference snaps back to it, its record goes, and so does the warning."""
        # Arrange
        doc = self.newDocument()
        doc.UndoMode = 1
        pad, fillet = self.padWithFillet(doc)
        original = fillet.Base[1][0]
        doc.openTransaction("redraw")
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        doc.commitTransaction()
        doc.recompute()  # outside the transaction: the guess isn't undone with it
        self.assertIn("Warning", fillet.State)

        # Act
        doc.undo()
        doc.recompute()

        # Assert
        self.assertTrue(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        self.assertEqual(fillet.Base[1], [original])
        self.assertEqual(App.getReferenceReport(fillet), [])
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        self.assertNotIn("guess", sub)

    def testWarningAndRecordAreReopened(self):
        """Saved and opened again, the fillet shows its warning before any recompute, and the
        report lists the reference with its original."""
        doc, pad, fillet, original = self.redrawnFillet()
        text = fillet.getStatusString()
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Warned.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)

        doc = App.openDocument(path)
        self.documents.append(doc.Name)

        fillet = doc.Fillet
        self.assertIn("Warning", fillet.State)
        self.assertEqual(fillet.getStatusString(), text)
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual(entry["guess_kind"], "tier3")
        self.assertEqual(entry["original"]["index"], original)
        doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertIn("Warning", fillet.State)

    def testAcceptClearsTheRecordAndTheWarning(self):
        """Accepting the guess: the edge becomes the reference, its record and the warning go."""
        doc, pad, fillet, original = self.redrawnFillet()
        held = fillet.Base[1]

        App.acceptReference(fillet, "Base", 0)

        self.assertNotIn("Warning", fillet.State)
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        self.assertNotIn("guess", sub)
        self.assertIn("fp", sub)
        doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        self.assertEqual(fillet.Base[1], held)
        self.assertEqual(App.getReferenceReport(fillet), [])
        #   nothing left to accept
        with self.assertRaises(ValueError):
            App.acceptReference(fillet, "Base", 0)

    def testMarkBrokenFailsTheOwnerWithTheOriginal(self):
        """Marking the guess broken: the reference goes back to its original, missing, and the
        fillet fails naming it and the rejected edge. The next edit upstream doesn't pick the
        rejected edge again: its record is a rejection, and it keeps no fingerprint (the rejected
        edge's)."""
        doc, pad, fillet, original = self.redrawnFillet()
        rejected = fillet.Base[1][0]

        App.markReferenceBroken(fillet, "Base", 0)
        doc.recompute()

        self.assertFalse(fillet.isValid())
        self.assertEqual(fillet.Base[1], ["?" + original])
        status = fillet.getStatusString()
        self.assertIn("Missing edge reference: " + original, status)
        self.assertIn("rejected: " + rejected, status)
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        self.assertEqual(sub["guess"], "rejected")
        self.assertNotIn("fp", sub)

        #   an edit upstream: the rejected edge is still there, and still not taken
        pad.Length = 12
        doc.recompute()
        self.assertFalse(fillet.isValid())
        self.assertEqual(fillet.Base[1], ["?" + original])

    def testUndoOfAnAcceptBringsTheRecordBack(self):
        """Undo restores a property through Paste: an accept undone gives the record back, and
        the next recompute the warning."""
        doc = self.newDocument()
        doc.UndoMode = 1
        pad, fillet = self.padWithFillet(doc)
        original = fillet.Base[1][0]
        self.redraw(doc)
        self.assertIn("Warning", fillet.State)

        doc.openTransaction("accept")
        App.acceptReference(fillet, "Base", 0)
        doc.commitTransaction()
        self.assertNotIn("guess", self.savedSubs(doc, "Fillet", "Base")[0])

        doc.undo()
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        self.assertEqual(sub["guess"], "tier3")
        self.assertTrue(sub["orig"].endswith("." + original))
        fillet.touch()
        doc.recompute()
        self.assertIn("Warning", fillet.State)

    def testBinderRecordIsReopened(self):
        """A PropertyXLinkSubList's record (a SubShapeBinder's Support): the pad's right face,
        found again by geometry after the rectangle is redrawn, keeps its record through save
        and reopen."""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        right = face("plane", normal=X, through=(20, 0, 0))
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(pad, tuple(right.one(pad.Shape)))]
        doc.recompute()
        self.assertTrue(binder.isValid())
        original = right.one(pad.Shape)[0]
        self.redraw(doc)
        self.assertIn("Warning", binder.State)
        [entry] = App.getReferenceReport(binder)
        self.assertEqual(entry["guess_kind"], "tier3")

        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Binder.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        self.documents.append(doc.Name)

        binder = doc.Binder
        self.assertIn("Warning", binder.State)
        [entry] = App.getReferenceReport(binder)
        self.assertEqual(entry["guess_kind"], "tier3")
        self.assertEqual(entry["original"]["index"], original)

    def testSetterKeepsTheRecordOfTheSameSub(self):
        """Setting the property again to the same sub keeps the record and the warning: a rewrite
        keeps what it doesn't change (ops#504 E2, I-S10, PLAN decision 142). The user ends a
        guess with Accept or Repair. It dropped them, and the guess read as an exact pick."""
        doc, pad, fillet, original = self.redrawnFillet()

        fillet.Base = (pad, list(fillet.Base[1]))
        doc.recompute()

        self.assertTrue(fillet.isValid())
        self.assertIn("Warning", fillet.State)
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        self.assertEqual(sub.get("guess"), "tier3")

    def testFilletComputesOnTheEdgesLeft(self):
        """A fillet on two vertical edges of the pad, at (20, 0) and (0, 10); the corner at
        (20, 0) is cut (FilletCornerCut's edit), so its edge is gone. The fillet computes on the
        other edge with a warning naming the missing one, which its reference keeps missing
        (Onshape's rule): the result is the pad filleted at (0, 10) alone."""
        # Arrange
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        other = edge("line", direction=Z, through=(0, 10, 0))
        fillet.Base = (pad, list(fillet.Base[1]) + other.one(pad.Shape))
        doc.recompute()
        self.assertTrue(fillet.isValid())

        # Act
        models.setLines(doc.Profile, {0: ((0, 0), (19, 0)), 1: ((20, 1), (20, 10))})
        doc.Profile.addGeometry(models.polyline([(19, 0), (20, 1)]), False)
        doc.recompute()

        # Assert
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertIn("Warning", fillet.State)
        missing = [s for s in fillet.Base[1] if s.startswith("?")]
        self.assertEqual(len(missing), 1)
        self.assertEqual([s for s in fillet.Base[1] if not s.startswith("?")], other.one(pad.Shape))
        status = fillet.getStatusString()
        self.assertIn("Missing edge reference: " + missing[0][1:], status)
        self.assertTrue(status.endswith("computed on 1 of 2 edges"), status)
        #   the oracle: the pad's shape filleted at (0, 10) alone, radius 1
        expected = pad.Shape.makeFillet(1, [pad.Shape.getElement(other.one(pad.Shape)[0])])
        self.assertAlmostEqual(fillet.Shape.Volume, expected.Volume, places=6)
        self.assertTrue(
            fillet.Shape.BoundBox.isInside(expected.BoundBox.Center)
            and expected.BoundBox.isInside(fillet.Shape.BoundBox.Center)
        )

    def testFilletWithNothingLeftFails(self):
        """The same fillet on the cut corner's edge alone: nothing left to compute on, so it
        fails, naming the edge."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)

        models.setLines(doc.Profile, {0: ((0, 0), (19, 0)), 1: ((20, 1), (20, 10))})
        doc.Profile.addGeometry(models.polyline([(19, 0), (20, 1)]), False)
        doc.recompute()

        self.assertFalse(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        self.assertIn("Missing edge reference", fillet.getStatusString())
        self.assertNotIn("computed on", fillet.getStatusString())

    def testExpressionErrorDropsTheWarning(self):
        """A warned fillet whose Radius expression then fails (it reads a property that doesn't
        exist) fails before DocumentObject::recompute(): it shows the error, not the old warning
        beside it (N1 4.9)."""
        doc, pad, fillet, original = self.redrawnFillet()
        self.assertIn("Warning", fillet.State)

        fillet.setExpression("Radius", "Pad.NoSuchProperty")
        doc.recompute()

        self.assertFalse(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        self.assertNotIn("Warning", fillet.getStatusString())

    def testInputFailureDropsTheWarning(self):
        """A warned fillet whose pad then fails (its Length 0): the fillet fails on its input in
        error before it runs (the failure pass-through's check, ops#126) and shows that error,
        not the old warning beside it (N1 4.9)."""
        doc, pad, fillet, original = self.redrawnFillet()
        self.assertIn("Warning", fillet.State)

        pad.Length = 0
        doc.recompute()

        self.assertFalse(pad.isValid())
        self.assertFalse(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        self.assertNotIn("Warning", fillet.getStatusString())

    # The guess rules (ops#127, N2 section 5): G1, G2 and G3 on designed models, each warned,
    # with its kind and its alternatives, and turned off by its switch.

    def guessSwitch(self, name, value):
        group = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/NamingSolver")
        group.SetBool(name, value)
        self.addCleanup(group.RemBool, name)

    def quietRedraws(self):
        """T1''s test off for this test: a line deleted and drawn again in place lost the old
        line's ID, so tier 3's pick there is warned at the normal level, never the quieter
        same-place one (PLAN decisions 155 and 165), until D2 (ops#526) tells a redraw from a
        sibling moved there. The same-place level's own tests still reach it this way."""
        self.guessSwitch("Tier1SameSource", False)

    def filletedSlot(self, doc):
        """The pad (0..20 x 0..10, 10 high) with a rectangular slot (x 6..14, y 3..7) pocketed
        through it, and a fillet, radius 0.5, on the slot's bottom edge at y = 3. The edge's
        name comes from the cut, so it shares structure with the slot's other bottom edges."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10)
        slot = models.sketch(doc, "SlotSketch", models.rectangle(6, 3, 14, 7), body, z=10)
        pocket = models.pocketThroughAll(body, slot)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, edge("line", direction=X, through=(0, 3, 0)).one(pocket.Shape))
        fillet.Radius = 0.5
        doc.recompute()
        self.assertTrue(fillet.isValid())
        return pocket, fillet

    def redrawSlotShifted(self, doc):
        """The slot drawn again 0.5 mm over in y: new geometry IDs, every edge 0.5 mm from its
        old place."""
        doc.SlotSketch.deleteAllGeometry()
        doc.SlotSketch.addGeometry(
            models.polygon([(14, 7.5), (14, 3.5), (6, 3.5), (6, 7.5)]), False
        )
        doc.recompute()

    def testStructuralCandidatesAreGuessedByTheNearest(self):
        """The slot redrawn 0.5 mm over. Its bottom edges along x have the slot's maker, but
        every line of the slot is new, so they lost the old edge's source (ops#173): no
        structural candidate. Tier 3's strict reach (1 % of the diagonal, 0.24 mm) holds
        neither; G2's wide reach (5 %, 1.22 mm) holds the nearer one, 0.5 mm away, from the same
        sketch and pocket (policy D), and the other is far enough (4.5 mm). The fillet computes
        on it, warned, kind `geometric` (G1, `nearest`, before ops#173), the other as the
        alternative. Marked broken, the fillet fails naming the original and the rejected
        pick."""
        # Arrange
        doc = self.newDocument()
        pocket, fillet = self.filletedSlot(doc)
        original = fillet.Base[1][0]

        # Act
        self.redrawSlotShifted(doc)

        # Assert
        nearer = edge("line", direction=X, through=(0, 3.5, 0)).one(pocket.Shape)
        other = edge("line", direction=X, through=(0, 7.5, 0)).one(pocket.Shape)
        self.assertTrue(fillet.isValid())
        self.assertEqual(fillet.Base[1], nearer)
        self.assertIn("Warning", fillet.State)
        self.assertIn("tier 3 wide", fillet.getStatusString())
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual((entry["status"], entry["tier"]), ("guessed", 3))
        self.assertEqual(entry["guess_kind"], "geometric")
        self.assertEqual(entry["original"]["index"], original)
        #   the alternatives: what geometry ranked (the other edge among them), not the pick
        alternatives = [(a["index"], a["role"]) for a in entry["alternatives"]]
        self.assertIn((other[0], "geometric"), alternatives)
        self.assertEqual({role for _, role in alternatives}, {"geometric"})
        self.assertNotIn(nearer[0], [index for index, _ in alternatives])
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        self.assertEqual(sub["guess"], "geometric")

        #   marked broken: the fillet fails on the original, the pick rejected
        App.markReferenceBroken(fillet, "Base", 0)
        doc.recompute()
        self.assertFalse(fillet.isValid())
        self.assertEqual(fillet.Base[1], ["?" + original])
        self.assertIn("rejected: " + nearer[0], fillet.getStatusString())

    def testStructuralCandidatesBreakWithTheGuessesOff(self):
        """G1's model with NamingSolver/Guess off: neither bottom edge along x is within tier 3's
        strict reach, so the fillet breaks with the slot's bottom edges as candidates."""
        self.guessSwitch("Guess", False)
        doc = self.newDocument()
        pocket, fillet = self.filletedSlot(doc)

        self.redrawSlotShifted(doc)

        self.assertFalse(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual(entry["status"], "broken")
        self.assertEqual(entry["guess_kind"], "")
        for y in (3.5, 7.5):
            [along] = edge("line", direction=X, through=(0, y, 0)).one(pocket.Shape)
            self.assertIn(along, entry["candidates"])

    def redrawShifted(self, doc):
        """The profile's rectangle drawn again 0.5 mm over in x: new geometry IDs, so no name
        relates the old edges to the new ones, and every edge 0.5 mm from its old place."""
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(models.polygon([(20.5, 10), (20.5, 0), (0.5, 0), (0.5, 10)]), False)
        doc.recompute()

    def testNoStructureIsGuessedByTheWideReach(self):
        """G2: the rectangle redrawn 0.5 mm over. No structural candidate; tier 3's strict reach
        (0.24 mm) misses the moved corner edge, the wide one (1.22 mm) holds it, and the next
        vertical edge is 19.5 mm away. The fillet computes on it, warned, kind `geometric`. With
        NamingSolver/GuessNoStructure off it breaks."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)

        self.redrawShifted(doc)

        corner = edge("line", direction=Z, through=(20.5, 0, 0)).one(pad.Shape)
        self.assertTrue(fillet.isValid())
        self.assertEqual(fillet.Base[1], corner)
        self.assertIn("Warning", fillet.State)
        self.assertIn("no structural candidate", fillet.getStatusString())
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual((entry["status"], entry["tier"]), ("guessed", 3))
        self.assertEqual(entry["guess_kind"], "geometric")

        #   the switch off
        self.guessSwitch("GuessNoStructure", False)
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        self.redrawShifted(doc)
        self.assertFalse(fillet.isValid())

    def assertBrokenNearest(self, fillet, nearest, distance):
        """The fillet failed on a reference the solver broke, `nearest` listed first at
        `distance` from the saved centre, in the report and in the error (N3 5.3)."""
        self.assertFalse(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual(entry["status"], "broken")
        self.assertEqual(entry["candidates"][0], nearest)
        self.assertAlmostEqual(entry["candidate_distances"][0], distance, places=6)
        # NaN last; the survivors tier 1 dropped (ops#174, ops#446, ops#454) come after the
        # ranked ones
        dropped = ("other generator", "other faces", "other maker", "other source")
        roles = entry["candidate_roles"]
        ranked = [r for r in roles if r not in dropped]
        self.assertEqual(roles[: len(ranked)], ranked)
        distances = [
            d for d, r in zip(entry["candidate_distances"], roles) if d == d and r not in dropped
        ]
        self.assertEqual(distances, sorted(distances))
        self.assertLessEqual(len(entry["candidates"]), 8)
        self.assertIn(f"candidates: {nearest} ({distance:.3g} mm)", fillet.getStatusString())

    def testNoStructureFromANewSketchBreaks(self):
        """Policy D (N3 4.4): the rectangle drawn 0.5 mm over in a new sketch, which the pad
        then takes as its profile. The corner edge's analogue is within G2's wide reach, but it
        comes from the new sketch, not the original's (Profile): no guess. The fillet breaks with
        the moved corner edge listed first, 0.5 mm away. With NamingSolver/GuessAnySource on, G2
        guesses it as before."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)

        self.redrawInANewSketch(doc)

        [corner] = edge("line", direction=Z, through=(20.5, 0, 0)).one(pad.Shape)
        self.assertBrokenNearest(fillet, corner, 0.5)

        #   any source
        self.guessSwitch("GuessAnySource", True)
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        self.redrawInANewSketch(doc)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(fillet.Base[1], [corner])
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual((entry["status"], entry["guess_kind"]), ("guessed", "geometric"))

    def redrawInANewSketch(self, doc):
        """redrawShifted's rectangle, drawn in a new sketch that the pad takes as its profile."""
        redrawn = models.sketch(
            doc, "Redrawn", models.polygon([(20.5, 10), (20.5, 0), (0.5, 0), (0.5, 10)]), doc.Body
        )
        doc.Pad.Profile = redrawn
        doc.recompute()

    def testDeletionBesideANeighbourBreaks(self):
        """Policy D's N11 (N3): FilletDeleteNearStep's model. A step (x 20..20.5) padded onto the
        block's right side, the fillet on its front vertical edge; the step deleted. The block's
        front right edge, 0.5 mm away, is within G2's wide reach, but it comes from the block's
        sketch, not the step's: the fillet breaks with it listed first. With
        NamingSolver/GuessAnySource on, G2 takes it (the guess N2 7.2 scored guessed-wrong)."""
        for anySource in (False, True):
            if anySource:
                self.guessSwitch("GuessAnySource", True)
            doc = self.newDocument()
            body = models.body(doc)
            profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
            pad = models.pad(body, profile, 10)
            stepSketch = models.sketch(doc, "StepSketch", models.rectangle(20, 0, 20.5, 10), body)
            step = models.pad(body, stepSketch, 10, name="Step")
            doc.recompute()
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (step, edge("line", direction=Z, through=(20.5, 0, 0)).one(step.Shape))
            fillet.Radius = 0.25
            doc.recompute()
            self.assertTrue(fillet.isValid(), fillet.getStatusString())

            body.removeObject(step)
            doc.removeObject("Step")
            doc.recompute()

            [corner] = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)
            if anySource:
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                [entry] = App.getReferenceReport(fillet)
                self.assertEqual((entry["status"], entry["guess_kind"]), ("guessed", "geometric"))
                self.assertEqual(fillet.Base[1], [corner])
            else:
                self.assertBrokenNearest(fillet, corner, 0.5)

    # ops#167: a deleted hole's edge on the face it cut isn't another hole's edge on that face.

    def filletedHoles(self, doc, holes, radius):
        """A block 0..30 x 0..20, 10 high, with holes pocketed through it, `holes` being
        (name, x, y, r) with hole A first, and a fillet of `radius` on A's bottom circle (z = 0),
        its Base the last hole. Returns (the last hole, the fillet)."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 30, 20), body)
        models.pad(body, profile, 10)
        for name, x, y, r in holes:
            sketch = models.sketch(doc, name + "Sketch", [models.circle(x, y, r)], body, z=10)
            last = models.pocketThroughAll(body, sketch, name)
        doc.recompute()
        _, x, y, r = holes[0]
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (last, edge("circle", center=(x, y, 0), radius=r).one(last.Shape))
        fillet.Radius = radius
        doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        return last, fillet

    def deleteHoleA(self, doc):
        doc.Body.removeObject(doc.HoleA)
        doc.removeObject("HoleA")
        doc.recompute()

    def testDeletedHoleBesideAnotherHoleBreaks(self):
        """ops#167 (seed 272, gap 1): holes A and B, radius 2, at (8, 10) and (22, 10), a fillet
        on A's bottom circle; A deleted. B's bottom circle is generated from the same bottom face
        and was tier 1's survivor (overlap 0.62), resolved silently 14 mm away; with hole C
        (radius 1 at (15, 4)) too, tier 2 took it with a warning. It comes from another hole:
        the fillet breaks with B's bottom circle first and B's rim circle second. With
        NamingSolver/Tier1SameMaker and Tier1SameSource off, tier 1 took B's circle as before;
        since ops#503 D1 the face-generator net breaks it there too: A's cylinder, the old
        circle's face generator, is held by no face."""
        holeA, holeB = ("HoleA", 8, 10, 2), ("HoleB", 22, 10, 2)
        for holes in ((holeA, holeB), (holeA, holeB, ("HoleC", 15, 4, 1))):
            doc = self.newDocument()
            last, fillet = self.filletedHoles(doc, holes, 0.5)

            self.deleteHoleA(doc)

            [bottom] = edge("circle", center=(22, 10, 0), radius=2).one(last.Shape)
            [rim] = edge("circle", center=(22, 10, 10), radius=2).one(last.Shape)
            self.assertBrokenNearest(fillet, bottom, 14.0)
            [entry] = App.getReferenceReport(fillet)
            self.assertEqual(entry["candidates"][1], rim)
            self.assertAlmostEqual(entry["candidate_distances"][1], (14**2 + 10**2) ** 0.5, 6)

        #   the switches off (T1 and T1', ops#173): the face-generator net (ops#503 D1)
        self.guessSwitch("Tier1SameMaker", False)
        self.guessSwitch("Tier1SameSource", False)
        doc = self.newDocument()
        last, fillet = self.filletedHoles(doc, (holeA, holeB), 0.5)
        self.deleteHoleA(doc)
        [bottom] = edge("circle", center=(22, 10, 0), radius=2).one(last.Shape)
        self.assertBrokenNearest(fillet, bottom, 14.0)
        [entry] = App.getReferenceReport(fillet)
        self.assertIn("lacks the old element's face generator", entry["evidence"])

    def testDeletedHoleNearAnotherHoleBreaks(self):
        """ops#167, G2': holes A and B, radius 0.5, at (8, 10) and (9.5, 10), a fillet (radius
        0.1) on A's bottom circle; A deleted. B's bottom circle is within G2's wide reach (1.87
        mm) and shares a source with A's (the block's sketch, through the face both cut), but
        not A's maker: no guess. The fillet breaks with B's bottom circle first at 1.5 mm and
        B's rim second. With NamingSolver/GuessAnySource on, G2 takes B's circle."""
        holes = (("HoleA", 8, 10, 0.5), ("HoleB", 9.5, 10, 0.5))
        for anySource in (False, True):
            if anySource:
                self.guessSwitch("GuessAnySource", True)
            doc = self.newDocument()
            last, fillet = self.filletedHoles(doc, holes, 0.1)

            self.deleteHoleA(doc)

            [bottom] = edge("circle", center=(9.5, 10, 0), radius=0.5).one(last.Shape)
            if anySource:
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                [entry] = App.getReferenceReport(fillet)
                self.assertEqual((entry["status"], entry["guess_kind"]), ("guessed", "geometric"))
                self.assertEqual(fillet.Base[1], [bottom])
            else:
                [rim] = edge("circle", center=(9.5, 10, 10), radius=0.5).one(last.Shape)
                self.assertBrokenNearest(fillet, bottom, 1.5)
                [entry] = App.getReferenceReport(fillet)
                self.assertEqual(entry["candidates"][1], rim)
                self.assertAlmostEqual(
                    entry["candidate_distances"][1], (1.5**2 + 10**2) ** 0.5, 6
                )

    # ops#173: a deleted circle of a multi-circle sketch isn't another circle's hole.

    def testDeletedCircleOfATwoCircleSketchBreaks(self):
        """ops#173: the first circle of the pocket's sketch is deleted. The other hole's bottom
        circle has the same maker (the pocket) and shares the block's bottom face, so it was
        tier 1's only survivor and the fillet moved to it silently, 14 mm away. It lost the old
        circle's source (its own circle has another geometry ID): the fillet breaks with it first
        and its rim second. With NamingSolver/Tier1SameSource off, tier 1 took it as before;
        since ops#503 D1 the face-generator net breaks it there too: the deleted circle's
        cylinder, the old circle's face generator, is held by no face."""
        for sameSource in (True, False):
            if not sameSource:
                self.guessSwitch("Tier1SameSource", False)
            doc = self.newDocument()
            pocket, fillet = self.filletedHole(doc, circles=((8, 10), (22, 10)))

            doc.HoleSketch.delGeometry(0)
            doc.recompute()

            [bottom] = edge("circle", center=(22, 10, 0), radius=2).one(pocket.Shape)
            [entry] = App.getReferenceReport(fillet)
            if sameSource:
                [rim] = edge("circle", center=(22, 10, 10), radius=2).one(pocket.Shape)
                self.assertBrokenNearest(fillet, bottom, 14.0)
                #   the whole list: no other maker's element (PR 149's review)
                self.assertEqual(entry["candidates"], [bottom, rim])
                self.assertEqual(entry["candidate_roles"], ["geometric", "geometric"])
                self.assertIn("lost the old element's source", entry["evidence"])
                self.assertNotIn("another maker", entry["evidence"])
            else:
                self.assertBrokenNearest(fillet, bottom, 14.0)
                self.assertIn("lacks the old element's face generator", entry["evidence"])

    def filletedHole(self, doc, size=(30, 20), circles=((8, 10),), height=10):
        """A block 0..size, `height` high, its sketch `Profile`; one pocket through all from
        `HoleSketch`, circles of radius 2 at `circles`, and a fillet (0.5) on the first hole's
        bottom circle. Returns (the pocket, the fillet)."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, *size), body)
        models.pad(body, profile, height)
        holes = [models.circle(x, y, 2) for x, y in circles]
        sketch = models.sketch(doc, "HoleSketch", holes, body, z=height)
        pocket = models.pocketThroughAll(body, sketch, "Holes")
        doc.recompute()
        x, y = circles[0]
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, edge("circle", center=(x, y, 0), radius=2).one(pocket.Shape))
        fillet.Radius = 0.5
        doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        return pocket, fillet

    def assertHoleCircleKept(self, pocket, fillet, tier):
        """The fillet still on the hole's bottom circle at (8, 10, 0), no warning; resolved by
        `tier` (None: exact, no solver row)."""
        [bottom] = edge("circle", center=(8, 10, 0), radius=2).one(pocket.Shape)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(fillet.Base[1], [bottom])
        self.assertNotIn("Warning", fillet.State)
        rows = App.getReferenceReport(fillet)
        self.assertFalse([e for e in rows if e["status"] in ("broken", "guessed")], rows)
        if tier is not None:
            self.assertEqual([(e["status"], e["tier"]) for e in rows], [("resolved", tier)], rows)

    def testRedrawnHoleCircleIsAWarnedGuess(self):
        """ops#173's control: the single hole's circle is deleted and drawn again 0.5 mm over, a
        new geometry ID. The new bottom circle lost the old one's source as another hole's would,
        so geometry decides: within G2's reach, from the same sketch and pocket (policy D), the
        fillet takes it with a warning (decision 20, as a pad edge's redraw)."""
        doc = self.newDocument()
        pocket, fillet = self.filletedHole(doc)

        doc.HoleSketch.delGeometry(0)
        doc.HoleSketch.addGeometry(models.circle(8.5, 10, 2), False)
        doc.recompute()

        [bottom] = edge("circle", center=(8.5, 10, 0), radius=2).one(pocket.Shape)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(fillet.Base[1], [bottom])
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual((entry["status"], entry["guess_kind"]), ("guessed", "geometric"))

    def testUnrelatedEditKeepsTheHoleCircle(self):
        """ops#173: the rule touches only references whose name is gone. After an edit of the
        block's sketch, the single hole's bottom circle keeps its name: exact, no warning."""
        doc = self.newDocument()
        pocket, fillet = self.filletedHole(doc)

        models.moveRectangle(doc.Profile, 0, 0, 32, 20)
        doc.recompute()

        self.assertHoleCircleKept(pocket, fillet, None)

    def testRedrawnBlockLineKeepsTheHoleCircle(self):
        """PR 149's review: the block's bottom line is deleted and drawn again, a new geometry
        ID. The hole's bottom circle keeps its name (the block's bottom face is named from its
        other lines): exact, no warning. testRedrawnBlockProfileKeepsTheHoleCircle renames it."""
        doc = self.newDocument()
        pocket, fillet = self.filletedHole(doc)

        doc.Profile.delGeometry(0)
        doc.Profile.addGeometry(models.polyline([(0, 0), (30, 0)]), False)
        doc.recompute()

        self.assertHoleCircleKept(pocket, fillet, None)

    def testRedrawnBlockProfileKeepsTheHoleCircle(self):
        """PR 149's review (Medium 1): the block's whole profile is deleted and drawn again, every
        line a new geometry ID. T1' asks only for the sources of what the pocket made itself (the
        hole's cylinder, from its circle), not of the face it cut: the hole's bottom circle keeps
        them and stays tier 1's, no warning. Since ops#503 D1: the redraw renames the block's
        bottom face, the circle's face generator, and no face holds its old name, so the
        face-generator net drops the circle and geometry finds it in place, with the quieter
        same-place warning."""
        doc = self.newDocument()
        pocket, fillet = self.filletedHole(doc)

        for _ in range(4):
            doc.Profile.delGeometry(0)
        doc.Profile.addGeometry(models.rectangle(0, 0, 30, 20), False)
        doc.recompute()

        [bottom] = edge("circle", center=(8, 10, 0), radius=2).one(pocket.Shape)
        self.assertEqual(fillet.Base[1], [bottom])
        entry = self.assertWarnedInPlace(fillet, "Edge", bottom)
        self.assertTrue(entry["evidence"].startswith("no structural candidate"), entry["evidence"])

    def testDeletedCircleWithinReachIsAWarnedGuess(self):
        """ops#173 under policy D: the deleted circle's sketch and pocket survive, so another hole
        of that sketch within G2's wide reach is its warned pick, never silent: holes 5 mm apart
        in a block 200 x 100 x 20 (diagonal 224 mm: strict reach 2.2 mm, wide 11.2 mm); the
        other hole's rim, 20.6 mm away, is beyond three times that."""
        doc = self.newDocument()
        pocket, fillet = self.filletedHole(doc, (200, 100), ((100, 50), (105, 50)), 20)

        doc.HoleSketch.delGeometry(0)
        doc.recompute()

        [other] = edge("circle", center=(105, 50, 0), radius=2).one(pocket.Shape)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(fillet.Base[1], [other])
        self.assertIn("Warning", fillet.State)
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual((entry["status"], entry["guess_kind"]), ("guessed", "geometric"))

    # ops#183: T1' on a horizontal through-hole, a patterned hole, refined faces and external
    # sketch geometry. Each pins the reference's element; none may move it silently.

    def redrawProfile(self, sketch, corners):
        """Deletes the rectangle drawn by `models.rectangle()` (geometry 0-3) and draws it again
        at `corners`: every line a new geometry ID."""
        for _ in range(4):
            sketch.delGeometry(0)
        sketch.addGeometry(models.rectangle(*corners), False)

    def assertWarnedInPlace(self, owner, kind, expected, quiet=True):
        """The reference resolved by geometry at tier 3, on `expected`, with a warning: the
        short same-place text and the quieter level (ops#391), or, not `quiet` (the pick lost the
        old name's sources, PLAN decision 165), the full text and the normal level. Returns its
        report row."""
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertIn("Warning", owner.State)
        [entry] = App.getReferenceReport(owner)
        self.assertEqual((entry["status"], entry["tier"]), ("resolved", 3), entry)
        self.assertEqual(entry["new"], expected, entry)
        if quiet:
            self.assertIn(
                f"{kind} reference found again in the same place (", owner.getStatusString()
            )
            self.assertEqual(entry["warning_level"], "same-place", entry)
        else:
            self.assertIn(f"{kind} reference resolved by geometry: ", owner.getStatusString())
            self.assertEqual(entry["warning_level"], "normal", entry)
        return entry

    def testHorizontalHoleKeepsTheEntryCircle(self):
        """ops#183: a hole through the block from its front face (y = 0) to its back (y = 20); a
        fillet on its entry circle. The block's whole profile is redrawn, every line a new
        geometry ID, which renames both circles. T1' asks only for the hole's own source (its
        circle), which the exit circle keeps too: both survive tier 1 with equal overlap. Tier 3
        takes the entry circle, in place, with a warning. Never the exit circle, and never
        silently. (Before ops#503 D1 the exit circle, 20 mm away, was the pick's alternative; the
        redraw renames the front face, the entry circle's face generator, so the face-generator
        net drops both survivors and geometry finds the circle over the whole pool.)"""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 30, 20), body)
        models.pad(body, profile, 10)
        #   the sketch on the front plane (its y is the block's z), its normal -y
        front = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 90))
        sketch = models.sketch(doc, "HoleSketch", [models.circle(15, 5, 2)], body, placement=front)
        pocket = models.pocketThroughAll(body, sketch, "Hole")
        pocket.Midplane = True
        doc.recompute()
        entryCircle = edge("circle", center=(15, 0, 5), radius=2)
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, entryCircle.one(pocket.Shape))
        fillet.Radius = 0.5
        doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        [old] = entryCircle.one(pocket.Shape)
        oldName = pocket.Shape.getElementMappedName(old)

        self.redrawProfile(profile, (0, 0, 30, 20))
        doc.recompute()

        [entryEdge] = entryCircle.one(pocket.Shape)
        [exitCircle] = edge("circle", center=(15, 20, 5), radius=2).one(pocket.Shape)
        self.assertNotEqual(pocket.Shape.getElementMappedName(entryEdge), oldName)
        self.assertEqual(fillet.Base[1], [entryEdge])
        row = self.assertWarnedInPlace(fillet, "Edge", entryEdge)
        self.assertNotEqual(row["new"], exitCircle)
        self.assertTrue(row["evidence"].startswith("no structural candidate"), row["evidence"])

    def testPatternedHoleUnderARedrawnProfileWarns(self):
        """ops#183: T1''s fallback. A hole pocketed at (8, 10) and patterned 14 mm along x; a
        fillet on the patterned hole's bottom circle at (22, 10, 0). The block's whole profile is
        redrawn, which renames the circle. Its maker is the pattern, which made no input of the
        name itself, so T1' asks for every known source, the block's lines among them: the circle
        lost them and isn't tier 1's. Tier 3 takes it in place, with a warning. With
        NamingSolver/Tier1SameSource off, tier 1 took it silently (round 0's behaviour there);
        since ops#503 D1 the face-generator net drops it there too (the block's bottom face, its
        generator, is renamed by the redraw and held by no face), and tier 3 takes it in place."""
        for sameSource in (True, False):
            if not sameSource:
                self.guessSwitch("Tier1SameSource", False)
            doc = self.newDocument()
            body = models.body(doc)
            profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 30, 20), body)
            models.pad(body, profile, 10)
            sketch = models.sketch(doc, "HoleSketch", [models.circle(8, 10, 2)], body, z=10)
            pocket = models.pocketThroughAll(body, sketch, "Hole")
            doc.recompute()
            pattern = doc.addObject("PartDesign::LinearPattern", "Pattern")
            pattern.Originals = [pocket]
            pattern.Direction = (models.originFeature(body, "X_Axis"), [""])
            pattern.Length = 14
            pattern.Occurrences = 2
            pattern.Refine = False
            body.addObject(pattern)
            doc.recompute()
            circle = edge("circle", center=(22, 10, 0), radius=2)
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (pattern, circle.one(pattern.Shape))
            fillet.Radius = 0.5
            doc.recompute()
            self.assertTrue(fillet.isValid(), fillet.getStatusString())

            self.redrawProfile(profile, (0, 0, 30, 20))
            doc.recompute()

            [bottom] = circle.one(pattern.Shape)
            self.assertEqual(fillet.Base[1], [bottom])
            #   the circle lost the block's lines, but the new lines are newer than the record's
            #   mark of the sketch: drawn again there, the same-place level (ops#526 D2, design 9.5)
            self.assertWarnedInPlace(fillet, "Edge", bottom)

    def refinedBlocks(self, doc):
        """Pad A, 0..20 x 0..20 x 10, from `Profile`, and pad B beside it, 20..40, from
        `ProfileB`, refined: one top face over both and one front top edge. Returns pad B."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 20), body)
        models.pad(body, profile, 10)
        profileB = models.sketch(doc, "ProfileB", models.rectangle(20, 0, 40, 20), body)
        padB = models.pad(body, profileB, 10, "PadB")
        padB.Refine = True
        doc.recompute()
        self.assertTrue(padB.isValid(), padB.getStatusString())
        return padB

    def testRefinedFaceAfterAProfileRedrawn(self):
        """ops#183: a sketch attached to the refined top face of two pads. Pad B's whole profile
        redrawn leaves the face's name (the refined face is named from pad A's): exact. Pad A's
        redrawn renames it, and no element has the old name's structure: tier 3 takes the face in
        place, with a warning, also with NamingSolver/Tier1SameSource off."""
        for sameSource, redrawn in itertools.product((True, False), ("ProfileB", "Profile")):
            if not sameSource:
                self.guessSwitch("Tier1SameSource", False)
            doc = self.newDocument()
            padB = self.refinedBlocks(doc)
            top = face("plane", normal=Z, through=(0, 0, 10))
            sketch = doc.addObject("Sketcher::SketchObject", "OnTop")
            padB.getParent().addObject(sketch)
            sketch.AttachmentSupport = [(padB, top.one(padB.Shape)[0])]
            sketch.MapMode = "FlatFace"
            doc.recompute()
            self.assertTrue(sketch.isValid(), sketch.getStatusString())

            corners = (20, 0, 40, 20) if redrawn == "ProfileB" else (0, 0, 20, 20)
            self.redrawProfile(doc.getObject(redrawn), corners)
            doc.recompute()

            [merged] = top.one(padB.Shape)
            if redrawn == "Profile" and sameSource:
                #   the merged face is now named from pad B's profile, whose line was in the model
                #   before: it breaks, the face listed first (ops#526 D2, decision 219)
                self.assertEqual(sketch.AttachmentSupport[0][1], ("?" + merged,))
                [entry] = App.getReferenceReport(sketch)
                self.assertEqual(entry["status"], "broken", entry)
                self.assertEqual(entry["candidates"][0], merged, entry)
                self.assertIn("was in the model before", entry["evidence"])
                continue
            self.assertEqual(sketch.AttachmentSupport[0][1], (merged,))
            if redrawn == "ProfileB":
                self.assertTrue(sketch.isValid(), sketch.getStatusString())
                self.assertNotIn("Warning", sketch.State)
                self.assertFalse(App.getReferenceReport(sketch))
            else:
                #   the face lost pad A's lines: never quiet while T1''s test is on
                self.assertWarnedInPlace(sketch, "Face", merged, quiet=not sameSource)

    def testRefinedEdgeAfterAProfileRedrawn(self):
        """ops#183: as testRefinedFaceAfterAProfileRedrawn, with a fillet on the refined front
        top edge (0..40 at y = 0, z = 10). Pad A's whole profile redrawn: tier 3 takes the edge
        in place, with a warning."""
        doc = self.newDocument()
        padB = self.refinedBlocks(doc)
        frontTop = edge("line", direction=X, contains=(30, 0, 10), where=lambda e: e.Length > 39)
        fillet = padB.getParent().newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (padB, frontTop.one(padB.Shape))
        fillet.Radius = 0.5
        doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())

        self.redrawProfile(doc.Profile, (0, 0, 20, 20))
        doc.recompute()

        [merged] = frontTop.one(padB.Shape)
        #   the edge lost pad A's lines and is now named from pad B's, which was in the model
        #   before: it breaks, the edge listed first (ops#526 D2, decision 219)
        self.assertEqual(fillet.Base[1], ["?" + merged])
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual(entry["status"], "broken", entry)
        self.assertEqual(entry["candidates"][0], merged, entry)
        self.assertIn("was in the model before", entry["evidence"])

    def testCollarFromExternalGeometry(self):
        """ops#183: a collar padded 3 mm on the block from a sketch of a circle (radius 4) and,
        as defining external geometry, the hole's top circle (radius 2); a fillet (0.3) on the
        collar's inner top circle, made from the external circle. The hole moved 1 mm: the
        external circle follows it and keeps its geometry ID, so the circle keeps its name:
        exact. The external circle deleted and added again before one recompute: a new geometry
        ID renames the circle, and no element has its structure: tier 3 takes it in place, with
        a warning."""
        for edit in ("move", "re-add"):
            doc = self.newDocument()
            body = models.body(doc)
            profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 30, 20), body)
            models.pad(body, profile, 10)
            holeSketch = models.sketch(doc, "HoleSketch", [models.circle(8, 10, 2)], body, z=10)
            hole = models.pocketThroughAll(body, holeSketch, "Hole")
            doc.recompute()
            [holeTop] = edge("circle", center=(8, 10, 10), radius=2).one(hole.Shape)
            sketch = models.sketch(doc, "CollarSketch", [models.circle(8, 10, 4)], body, z=10)
            sketch.addExternal(hole.Name, holeTop, True)
            collar = models.pad(body, sketch, 3, "Collar")
            doc.recompute()
            inner = edge("circle", center=(8, 10, 13), radius=2)
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (collar, inner.one(collar.Shape))
            fillet.Radius = 0.3
            doc.recompute()
            self.assertTrue(fillet.isValid(), fillet.getStatusString())
            oldName = collar.Shape.getElementMappedName(inner.one(collar.Shape)[0])

            if edit == "move":
                geometry = holeSketch.Geometry
                geometry[0].Center = App.Vector(9, 10, 0)
                holeSketch.Geometry = geometry
                inner = edge("circle", center=(9, 10, 13), radius=2)
            else:
                #   no recompute in between: without the external circle the collar would cover
                #   the hole, failing the fillet before the rename
                sketch.delExternal(0)
                sketch.addExternal(hole.Name, holeTop, True)
            doc.recompute()

            [circle] = inner.one(collar.Shape)
            self.assertEqual(fillet.Base[1], [circle])
            renamed = collar.Shape.getElementMappedName(circle) != oldName
            self.assertEqual(renamed, edit == "re-add")
            if edit == "move":
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                self.assertNotIn("Warning", fillet.State)
                self.assertFalse(App.getReferenceReport(fillet))
            else:
                #   the external circle's new ID, newer than the record's mark of the sketch: drawn
                #   again there, the same-place level (ops#526 D2, design 9.5)
                self.assertWarnedInPlace(fillet, "Edge", circle)

    def openIndexOnly(self):
        """The fillet's reference saved as an index-only missing reference (`?EdgeN`, no shadow:
        no name to solve from, ops#123), its fingerprint kept; the file opened again with the
        solver off, which is then turned on. Returns (document, the reference's index name)."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        index = fillet.Base[1][0]
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "IndexOnly.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        xml = files["Document.xml"].decode("utf-8")
        found = re.findall(r'<Sub value="%s" shadow="[^"]*"( fp=")' % index, xml)
        self.assertEqual(len(found), 1)  # the setup: the fillet's reference, with a fingerprint
        xml = re.sub(
            r'<Sub value="%s" shadow="[^"]*" fp="' % index, '<Sub value="?%s" fp="' % index, xml
        )
        # Opened with the solver off: on, the open itself would find the edge in its place
        # (strict tier 3), before any edit.
        xml, solverOff = re.subn(
            r'(<Property name="ReferenceSolver"[^>]*>\s*<Bool value=")true(")', r"\1false\2", xml
        )
        self.assertEqual(solverOff, 1)
        files["Document.xml"] = xml.encode("utf-8")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        doc = App.openDocument(path)
        self.documents.append(doc.Name)
        self.assertEqual(doc.Fillet.Base[1], ["?" + index])
        doc.ReferenceSolver = True
        return doc, index

    def testIndexOnlyReferenceBreaksWithItsCandidates(self):
        """N2 5.4 under policy D (N3 Q3): an index-only missing reference has no name, so no
        structural candidate and no source; in a forward update of its target it is solved by its
        fingerprint, and breaks with the candidates ranked by distance. The rectangle redrawn
        0.5 mm over: the moved corner edge is listed first, 0.5 mm away. With
        NamingSolver/GuessAnySource on, G2 picks it, kind `geometric`, and the record has no
        original name (it never snaps back). With NamingSolver/GuessNoStructure off it stays
        broken (the review of fork PR 117, 4b)."""
        doc, index = self.openIndexOnly()

        self.redrawShifted(doc)

        [corner] = edge("line", direction=Z, through=(20.5, 0, 0)).one(doc.Pad.Shape)
        self.assertEqual(doc.Fillet.Base[1], ["?" + index])
        self.assertBrokenNearest(doc.Fillet, corner, 0.5)

        #   any source
        self.guessSwitch("GuessAnySource", True)
        doc, index = self.openIndexOnly()
        self.redrawShifted(doc)
        corner = [corner]
        fillet = doc.Fillet
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(fillet.Base[1], corner)
        self.assertIn("Warning", fillet.State)
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual((entry["status"], entry["guess_kind"]), ("guessed", "geometric"))
        self.assertEqual(entry["original"]["name"], "")

        #   the switch off
        self.guessSwitch("GuessNoStructure", False)
        doc, index = self.openIndexOnly()
        self.redrawShifted(doc)
        self.assertFalse(doc.Fillet.isValid())
        self.assertEqual(doc.Fillet.Base[1], ["?" + index])

    def testSplitIsGuessedByThePieceAtTheSavedCentre(self):
        """G3: ExternalSplitOffCentre's model. A notch at x 4..8 splits the front top edge; the
        piece with its name (x 0..4) misses its old centre (x = 10), the rest (x 8..20) holds
        it. The external edge takes the rest, warned, kind `piece`, with the named piece as the
        alternative. Accepted, the warning goes and the reference holds."""
        # Arrange
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        front = edge("line", direction=X, through=(0, 0, 10))
        sketch = models.sketch(doc, "OnFront", [], body, z=10)
        original = front.one(pad.Shape)[0]
        sketch.addExternal(pad.Name, original)
        doc.recompute()

        # Act
        models.setLines(doc.Profile, {0: ((0, 0), (4, 0))})
        doc.Profile.addGeometry(models.polyline([(4, 0), (4, 2), (8, 2), (8, 0), (20, 0)]), False)
        doc.recompute()

        # Assert
        rest = edge("line", direction=X, contains=(14, 0, 10)).one(pad.Shape)
        named = edge("line", direction=X, contains=(2, 0, 10)).one(pad.Shape)
        self.assertTrue(sketch.isValid())
        self.assertIn("Warning", sketch.State)
        self.assertIn("the piece at the saved centre", sketch.getStatusString())
        [entry] = App.getReferenceReport(sketch)
        self.assertEqual((entry["status"], entry["tier"]), ("guessed", 1))
        self.assertEqual(entry["guess_kind"], "piece")
        self.assertEqual(entry["new"], rest[0])
        self.assertEqual([a["index"] for a in entry["alternatives"]], named)

        #   accepted
        App.acceptReference(sketch, "ExternalGeometry", 0)
        doc.recompute()
        self.assertTrue(sketch.isValid())
        self.assertNotIn("Warning", sketch.State)
        self.assertEqual(App.getReferenceReport(sketch), [])

    # A pick whose original's name gives another element (ops#133; the Fable review of fork PR
    # 122, 3b and 3c): the reference snaps back only to the original as saved, by the record's
    # original fingerprint (`ofp`); a record saved without one snaps back by name, except a
    # piece's.

    def putBackAsHole(self, doc, lines):
        """The rectangle's original lines (copies that keep their geometry IDs) added to the
        profile again, in their order (front, right, back, left), as a hole x 6..14, y 3..7."""
        corners = [(6, 3), (14, 3), (14, 7), (6, 7)]
        for i, line in enumerate(lines):
            line.StartPoint = App.Vector(*corners[i], 0)
            line.EndPoint = App.Vector(*corners[(i + 1) % 4], 0)
        doc.Profile.Geometry = doc.Profile.Geometry + lines
        doc.recompute()

    def reopenWithoutOfp(self, doc):
        """`doc` saved, its one record's original fingerprint (`ofp`) taken out as in a file
        saved before ops#133, and opened again. Returns the document opened."""
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "NoOfp.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        xml, count = re.subn(r' ofp="[^"]*"', "", files["Document.xml"].decode("utf-8"))
        self.assertEqual(count, 1)  # the setup: one record, with its original fingerprint
        files["Document.xml"] = xml.encode("utf-8")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        doc = App.openDocument(path)
        self.documents.append(doc.Name)
        return doc

    def assertGeometricPickAt(self, fillet, pad, x):
        corner = edge("line", direction=Z, through=(x, 0, 0)).one(pad.Shape)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(fillet.Base[1], corner)
        self.assertIn("Warning", fillet.State)
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual((entry["status"], entry["guess_kind"]), ("guessed", "geometric"))

    def testPickStandsWhenTheOriginalsNameGivesAnotherElement(self):
        """The rectangle redrawn 0.5 mm over (G2, kind `geometric`), then its original lines put
        back with their geometry IDs as a hole in the block: the original's name gives the
        hole's corner edge at (14, 3), not the original as saved, while the pick is still there.
        The pick and its record stand, and through a later edit too (before ops#133 the
        reference snapped back to the hole's corner by the name alone, silently)."""
        # Arrange
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        lines = doc.Profile.Geometry
        self.redrawShifted(doc)
        self.assertGeometricPickAt(fillet, pad, 20.5)
        original = App.getReferenceReport(fillet)[0]["original"]["name"]

        # Act
        self.putBackAsHole(doc, lines)

        # Assert
        hole = edge("line", direction=Z, through=(14, 3, 0)).one(pad.Shape)
        self.assertEqual([pad.Shape.getElementName(original)], hole)  # the setup
        self.assertGeometricPickAt(fillet, pad, 20.5)

        #   a later edit
        pad.Length = 12
        doc.recompute()
        self.assertGeometricPickAt(fillet, pad, 20.5)

    def testRecordWithoutTheOriginalsFingerprintSnapsBackByName(self):
        """A guess other than a piece's, saved without the original's fingerprint, snaps back
        when the original's name gives an element again, as before ops#133. The rectangle
        redrawn 0.5 mm over (G2), the file saved without `ofp` and opened again, then the
        original lines put back in their place: the reference is the original edge, plainly."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        lines = doc.Profile.Geometry
        self.redrawShifted(doc)
        self.assertGeometricPickAt(fillet, pad, 20.5)
        doc = self.reopenWithoutOfp(doc)

        doc.Profile.Geometry = lines
        doc.recompute()

        fillet = doc.Fillet
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertNotIn("Warning", fillet.State)
        self.assertEqual(
            fillet.Base[1], edge("line", direction=Z, through=(20, 0, 0)).one(doc.Pad.Shape)
        )
        self.assertEqual(App.getReferenceReport(fillet), [])

    def testPieceWithoutTheOriginalsFingerprintNeverSnapsBack(self):
        """A piece's record saved without the original's fingerprint doesn't snap back by name,
        which can give the other piece. testSplitIsGuessedByThePieceAtTheSavedCentre's model,
        saved without `ofp` and opened again: the original's name gives the named piece
        (x 0..4); the external edge stays on the rest (x 8..20), warned, and through a later
        recompute too."""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        sketch = models.sketch(doc, "OnFront", [], body, z=10)
        front = edge("line", direction=X, through=(0, 0, 10)).one(pad.Shape)[0]
        sketch.addExternal(pad.Name, front)
        doc.recompute()
        models.setLines(doc.Profile, {0: ((0, 0), (4, 0))})
        doc.Profile.addGeometry(models.polyline([(4, 0), (4, 2), (8, 2), (8, 0), (20, 0)]), False)
        doc.recompute()
        self.assertEqual(App.getReferenceReport(sketch)[0]["guess_kind"], "piece")

        doc = self.reopenWithoutOfp(doc)

        sketch, pad = doc.OnFront, doc.Pad
        rest = edge("line", direction=X, contains=(14, 0, 10)).one(pad.Shape)
        for step in ("opened", "recomputed"):
            self.assertTrue(sketch.isValid(), step)
            self.assertEqual(list(sketch.ExternalGeometry[0][1]), rest, step)
            self.assertIn("Warning", sketch.State, step)
            [entry] = App.getReferenceReport(sketch)
            self.assertEqual(entry["guess_kind"], "piece", step)
            pad.touch()
            doc.recompute()

    # The warning load (ops#391, decision 97): a warning prints once, the solver's developer
    # lines are at log level, and a reference found again in the same place is the quieter level
    # with a shorter text.

    def consoleOutput(self, action, log=False):
        """What `action()` prints through the console's std observer (stderr, fd 2), warnings and
        errors on and the log tags at their defaults, as text; with `log`, log lines too and the
        `App` tag at log level. Fails without the observer, which FreeCADCmd has; the GUI's
        Report view replaces it, so there the test is skipped."""
        if "Console" not in App.Console.GetObservers():
            if App.GuiUp:
                self.skipTest("no console observer to catch the warnings (the GUI)")
            self.fail("no console observer to catch the warnings")
        kinds = ("Wrn", "Err", "Log") if log else ("Wrn", "Err")
        statuses = {kind: App.Console.GetStatus("Console", kind) for kind in kinds}
        for kind in kinds:
            App.Console.SetStatus("Console", kind, True)
        level = App.getLogLevel("App")
        if log:
            App.setLogLevel("App", "Log")
        saved = os.dup(2)
        with tempfile.TemporaryFile() as caught:
            os.dup2(caught.fileno(), 2)
            try:
                action()
            finally:
                os.dup2(saved, 2)
                os.close(saved)
                for kind, status in statuses.items():
                    App.Console.SetStatus("Console", kind, bool(status))
                App.setLogLevel("App", level)
            caught.seek(0)
            return caught.read().decode("utf-8", "replace")

    def twoEdgeFillet(self, doc):
        """padWithFillet's model with the fillet on both vertical edges at y = 0."""
        pad, fillet = self.padWithFillet(doc)
        fillet.Base = (
            pad,
            [
                edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)[0],
                edge("line", direction=Z, through=(0, 0, 0)).one(pad.Shape)[0],
            ],
        )
        doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        return pad, fillet

    def testSolverDeveloperLinesAreLogLevel(self):
        """The redrawn rectangle's two filleted edges, found again by geometry: the redraw prints
        the fillet's warning and none of the solver's developer lines (`<PropertyLinks>`: the
        resolutions and the raw `missing element reference`), which are at log level."""
        doc = self.newDocument()
        pad, fillet = self.twoEdgeFillet(doc)
        printed = self.consoleOutput(lambda: self.redraw(doc))
        self.assertIn("Warning", fillet.State)
        self.assertIn("Fillet: ", printed)
        self.assertNotIn("<PropertyLinks>", printed)
        self.assertNotIn("missing element reference", printed)

    def testWarningPrintsOnceAndAgainWhenItChanges(self):
        """The redrawn rectangle's two filleted edges, both found again by geometry: the fillet's
        warning prints once, at the redraw, and not at the three recomputes after (a pad length
        changed each time), until its text changes (one reference accepted)."""
        doc = self.newDocument()
        pad, fillet = self.twoEdgeFillet(doc)

        def lines(text):
            return [line for line in text.splitlines() if line.startswith("Fillet: ")]

        def warning():
            return "Fillet: " + fillet.getStatusString()[len("Warning: ") :]

        printed = self.consoleOutput(lambda: self.redraw(doc))
        self.assertIn("Warning", fillet.State)
        self.assertEqual(lines(printed), [warning()])
        for length in (11, 12, 13):

            def lengthen():
                pad.Length = length
                doc.recompute()

            self.assertEqual(lines(self.consoleOutput(lengthen)), [], f"length {length}")
            self.assertIn("Warning", fillet.State)

        def accept():
            App.acceptReference(fillet, "Base", 0)
            doc.recompute()

        before = warning()
        self.assertEqual(lines(self.consoleOutput(accept)), [warning()])
        self.assertNotEqual(warning(), before)

        def touch():
            pad.touch()
            doc.recompute()

        self.assertEqual(lines(self.consoleOutput(touch)), [])

    def testSamePlaceLevelAndAfterReopen(self):
        """The redrawn rectangle's edge, exactly where it was: the warning names it in the short
        same-place form and is the quieter level, also after the pad is made longer (the edge
        then no longer matches the record's snapshot of the original). Drawn 0.1 mm off instead
        (tier 3 within its distance, not the same place), the warning keeps its full form and
        the normal level. Both levels read the same after a save and reopen (derived at load,
        nothing new saved)."""
        self.quietRedraws()
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        self.redraw(doc)
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "same-place")
        self.assertEqual(
            fillet.getStatusString(),
            "Warning: Edge reference found again in the same place (Base[0])",
        )
        pad.Length = 12
        doc.recompute()
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "same-place")
        self.assertEqual(
            fillet.getStatusString(),
            "Warning: Edge reference found again in the same place (Base[0])",
        )

        other = self.newDocument()
        pad2, fillet2 = self.padWithFillet(other)
        original = fillet2.Base[1][0]
        other.Profile.deleteAllGeometry()
        other.Profile.addGeometry(models.polygon([(20.1, 10), (20.1, 0), (0, 0), (0, 10)]), False)
        other.recompute()
        self.assertTrue(fillet2.isValid())
        corner = edge("line", direction=Z, through=(20.1, 0, 0)).one(pad2.Shape)
        self.assertEqual(fillet2.Base[1], corner)
        self.assertEqual(
            fillet2.getStatusString(),
            "Warning: Edge reference resolved by geometry: %s for %s (Base[0], tier 3)"
            % (corner[0], original),
        )
        self.assertEqual(App.getReferenceReport(fillet2)[0]["warning_level"], "normal")

        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        for document, level in ((doc, "same-place"), (other, "normal")):
            path = os.path.join(folder, document.Name + ".FCStd")
            document.saveAs(path)
            name = document.Name
            App.closeDocument(name)
            reopened = App.openDocument(path)
            self.documents.append(reopened.Name)
            fillet = reopened.Fillet
            self.assertIn("Warning", fillet.State, name)
            self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], level, name)
            reopened.Pad.Length = 14
            reopened.recompute()
            self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], level, name)

    # Fork PR 348 round 1 (ops#391, decisions 100 and 102)

    def redrawAt(self, doc, x, recompute=True):
        """`redraw`, with the profile's right side drawn at `x` (20: where it was)."""
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(models.polygon([(x, 10), (x, 0), (0, 0), (0, 10)]), False)
        if recompute:
            doc.recompute()

    def assertReopenedNormal(self, doc):
        """Saves `doc`, reopens it, and expects its fillet's warning at the normal level, before
        and after a recompute, which words it in full (resolved by geometry, 0.1 mm off)."""
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Saved.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        reopened = App.openDocument(path)
        self.documents.append(reopened.Name)
        fillet = reopened.Fillet
        self.assertIn("Warning", fillet.State)
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "normal")
        fillet.touch()
        reopened.recompute()
        self.assertIn("Warning", fillet.State)
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "normal")
        self.assertRegex(
            fillet.getStatusString(),
            r"^Warning: Edge reference resolved by geometry: Edge\d+ for Edge\d+ \(Base\[0\], tier 3\)$",
        )

    def testPartialRecomputeBeforeSaveIsJudgedFromTheShapes(self):
        """The redrawn rectangle's edge, exactly in place (the quieter level), then drawn 0.1 mm
        off and only the profile and the pad recomputed: the fillet, touched, keeps the
        same-place text while its record is now the 0.1 mm one. Saved so and reopened, its level
        comes from the shapes, not the text (decision 102): normal, and the full text after a
        recompute."""
        self.quietRedraws()
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        self.redrawAt(doc, 20)
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "same-place")
        self.redrawAt(doc, 20.1, recompute=False)
        doc.recompute([doc.Profile, pad])
        self.assertIn("Touched", fillet.State)
        self.assertEqual(
            fillet.getStatusString(),
            "Warning: Edge reference found again in the same place (Base[0])",
        )
        self.assertReopenedNormal(doc)

    def testUndoBeforeSaveIsJudgedFromTheShapes(self):
        """The redrawn rectangle drawn 0.1 mm off (normal), then back in place (the quieter
        level), and that undone: the fillet, touched, keeps the same-place text with the 0.1 mm
        record back. Saved so and reopened, its level comes from the shapes (decision 102):
        normal, and the full text after a recompute."""
        self.quietRedraws()
        doc = self.newDocument()
        doc.UndoMode = 1
        pad, fillet = self.padWithFillet(doc)
        doc.openTransaction("off")
        self.redrawAt(doc, 20.1)
        doc.commitTransaction()
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "normal")
        doc.openTransaction("in place")
        self.redrawAt(doc, 20)
        doc.commitTransaction()
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "same-place")
        doc.undo()
        self.assertIn("Touched", fillet.State)
        self.assertEqual(
            fillet.getStatusString(),
            "Warning: Edge reference found again in the same place (Base[0])",
        )
        self.assertReopenedNormal(doc)

    def testRecordBackAfterAnotherIsJudgedAgain(self):
        """The redrawn rectangle's edge, exactly in place (the quieter level), stays quiet when
        the pad is made longer (its record unchanged, decision 102). Drawn 0.1 mm off, the solver
        writes another record (normal); undone, the first record and its pick come back, but the
        edge is no longer where that record's original was: judged again, the level is normal,
        not the old judgement's quieter one."""
        self.quietRedraws()
        doc = self.newDocument()
        doc.UndoMode = 1
        pad, fillet = self.padWithFillet(doc)
        self.redrawAt(doc, 20)
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "same-place")
        pad.Length = 12
        doc.recompute()
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "same-place")
        judged = fillet.Base[1]
        doc.openTransaction("off")
        self.redrawAt(doc, 20.1)
        doc.commitTransaction()
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "normal")
        doc.undo()
        doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertEqual(fillet.Base[1], judged)
        self.assertIn("Warning", fillet.State)
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "normal")

    # Fork PR 348 round 3 (ops#391): a judgement goes when its reference isn't found in place

    def testRecordBackAfterMissingIsJudgedAgain(self):
        """The redrawn rectangle's edge, exactly in place (the quieter level), stays quiet when
        the pad is made longer. Drawn at 60 mm instead, the edge goes missing; undone, the
        judged record and its pick come back, but the edge is no longer where that record's
        original was: judged again, the level is normal, also after a redo and a second undo."""
        self.quietRedraws()
        doc = self.newDocument()
        doc.UndoMode = 1
        pad, fillet = self.padWithFillet(doc)
        self.redrawAt(doc, 20)
        pad.Length = 12
        doc.recompute()
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "same-place")
        judged = fillet.Base[1]
        doc.openTransaction("far")
        self.redrawAt(doc, 60)
        doc.commitTransaction()
        self.assertFalse(fillet.isValid())
        for action in (doc.undo, doc.redo, doc.undo):
            action()
            doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertEqual(fillet.Base[1], judged)
        self.assertIn("Warning", fillet.State)
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "normal")

    def testRemovedReferenceBackIsJudgedAgain(self):
        """A fillet on the rectangle's left bottom edge and its right vertical edge. Redrawn in
        place, then the pad made longer: both quiet (the bottom edge in place now, the vertical
        one by its judgement). The vertical edge's reference removed and the removal undone:
        its record comes back, but the edge has moved since: judged again, the level is normal."""
        self.quietRedraws()
        doc = self.newDocument()
        doc.UndoMode = 1
        pad, fillet = self.padWithFillet(doc)
        fillet.Base = (
            pad,
            [
                edge("line", direction=App.Vector(0, 1, 0), through=(0, 5, 0)).one(pad.Shape)[0],
                edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)[0],
            ],
        )
        doc.recompute()
        self.assertTrue(fillet.isValid())
        self.redrawAt(doc, 20)
        pad.Length = 12
        doc.recompute()
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "same-place")
        both = fillet.Base[1]
        doc.openTransaction("remove")
        fillet.Base = (pad, both[:1])
        doc.recompute()
        doc.commitTransaction()
        doc.undo()
        doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertEqual(fillet.Base[1], both)
        self.assertIn("Warning", fillet.State)
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "normal")

    def testHiddenSamePlaceMarkerSendsItsPrintToTheLog(self):
        """With the tree's marker for same-place warnings hidden (the TreeView preference), the
        redrawn rectangle's two filleted edges, found again in the same place, print no warning
        line; the fillet keeps the Warning state and the quieter level, and the line is in the
        log. Drawn 0.1 mm off, the normal warning still prints."""
        self.quietRedraws()
        params = App.ParamGet("User parameter:BaseApp/Preferences/TreeView")
        params.SetBool("ShowSamePlaceWarnings", False)
        self.addCleanup(params.RemBool, "ShowSamePlaceWarnings")
        doc = self.newDocument()
        pad, fillet = self.twoEdgeFillet(doc)
        printed = self.consoleOutput(lambda: self.redrawAt(doc, 20), log=True)
        self.assertIn("Warning", fillet.State)
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "same-place")
        text = fillet.getStatusString()[len("Warning: ") :]
        self.assertNotIn("Fillet: " + text, printed.splitlines())  # the warning line
        self.assertIn("#Fillet: " + text, printed)  # the log line, NamingSolver#Fillet

        printed = self.consoleOutput(lambda: self.redrawAt(doc, 20.1))
        self.assertEqual(App.getReferenceReport(fillet)[0]["warning_level"], "normal")
        self.assertIn("Fillet: " + fillet.getStatusString()[len("Warning: ") :], printed)

    def testAcceptedWarningPrintsAgainWhenItComesBack(self):
        """The redrawn rectangle's two filleted edges, found again in the same place: the warning
        prints; both references accepted, with no recompute after, and the rectangle redrawn
        again: the same text comes back, and prints again (it was gone)."""
        self.quietRedraws()
        doc = self.newDocument()
        pad, fillet = self.twoEdgeFillet(doc)

        def lines(text):
            return [line for line in text.splitlines() if line.startswith("Fillet: ")]

        printed = self.consoleOutput(lambda: self.redrawAt(doc, 20))
        first = fillet.getStatusString()
        self.assertEqual(lines(printed), ["Fillet: " + first[len("Warning: ") :]])
        App.acceptReference(fillet, "Base", 0)
        App.acceptReference(fillet, "Base", 1)
        self.assertNotIn("Warning", fillet.State)
        printed = self.consoleOutput(lambda: self.redrawAt(doc, 20))
        self.assertEqual(fillet.getStatusString(), first)
        self.assertEqual(lines(printed), ["Fillet: " + first[len("Warning: ") :]])

    def testErrorPrintsOnceAndAgainWhenItComesBack(self):
        """A fillet too large for its edge fails: its error prints once, and not at the two
        recomputes after (the pad touched), though it stays in error; mended and broken again,
        it prints again (decision 100)."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)

        def lines(text):
            return [line for line in text.splitlines() if line.startswith("Fillet: ")]

        def setRadius(radius):
            fillet.Radius = radius
            doc.recompute()

        printed = self.consoleOutput(lambda: setRadius(30))
        self.assertIn("Invalid", fillet.State)
        error = "Fillet: " + fillet.getStatusString()
        self.assertEqual(lines(printed), [error])

        def touch():
            pad.touch()
            doc.recompute()

        for step in range(2):
            self.assertEqual(lines(self.consoleOutput(touch)), [], f"recompute {step}")
            self.assertIn("Invalid", fillet.State)
        self.assertEqual(lines(self.consoleOutput(lambda: setRadius(1))), [])
        self.assertTrue(fillet.isValid())
        printed = self.consoleOutput(lambda: setRadius(30))
        self.assertEqual(lines(printed), [error])

    @unittest.skipUnless(dump.OLD_FILE_TESTS, dump.OLD_FILE_SKIP)
    def testMissingElementReferenceStaysAWarningWithoutTheSolver(self):
        """Without the reference solver, the fillet's edge gone (the profile drawn as a triangle
        without it): `PropertyLinks`' "missing element reference" stays a warning (upstream's);
        only solver documents put it at log level (ops#391)."""
        doc = self.newDocument(solver=False)
        pad, fillet = self.padWithFillet(doc)

        def triangle():
            doc.Profile.deleteAllGeometry()
            doc.Profile.addGeometry(models.polygon([(0, 0), (0, 10), (15, 10)]), False)
            doc.recompute()

        printed = self.consoleOutput(triangle)
        self.assertIn("missing element reference", printed)

    def testReorderPrintsNoTransientAttachError(self):
        """A sketch on the top face of the last pocket of a block, with a pocket of its own,
        moved before that pocket (right after an earlier one): the reorder points the sketch at
        the earlier pocket's face, marked missing until the solver finds it there. It prints no
        "PositionBySupport" error on the way, and after the recompute the sketch sits on that
        face where it was and every feature computes (ops#391 H)."""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 40, 20), body)
        models.pad(body, profile, 10, "Block")
        notch = models.pocketThroughAll(
            body, models.sketch(doc, "NotchSketch", models.rectangle(30, 0, 40, 20), body, z=10), "Notch"
        )
        slot = models.pocketThroughAll(
            body, models.sketch(doc, "SlotSketch", models.rectangle(0, 0, 5, 20), body, z=10), "Slot"
        )
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "OutletSketch")
        sketch.AttachmentSupport = (slot, face("plane", normal=Z, through=(0, 0, 10)).one(slot.Shape))
        sketch.MapMode = "FlatFace"
        sketch.addGeometry(Part.Circle(App.Vector(15, 10, 0), App.Vector(0, 0, 1), 2), False)
        outlet = models.pocket(body, sketch, 3, "Outlet")
        doc.recompute()
        self.assertTrue(outlet.isValid())
        placement = sketch.Placement

        def reorder():
            body.reorderObject([sketch, outlet], notch, True)
            doc.recompute()

        printed = self.consoleOutput(reorder)
        self.assertNotIn("PositionBySupport", printed)
        [(support, subs)] = sketch.AttachmentSupport
        self.assertEqual(support, notch)
        self.assertEqual(list(subs), face("plane", normal=Z, through=(0, 0, 10)).one(notch.Shape))
        self.assertTrue(sketch.Placement.isSame(placement, 1e-9), sketch.Placement)
        for feature in body.Group:
            self.assertTrue(feature.isValid(), (feature.Name, feature.getStatusString()))
        self.assertEqual([o.Name for o in body.Group][-4:], ["OutletSketch", "Outlet", "SlotSketch", "Slot"])

    # The exact place (ops#394): an element found again where it was, in a long part

    def chamferedRims(self, doc):
        """A floor frame's two rims, 3600 x 45 and 235 high, 4045 apart, padded from one sketch
        (the target's diagonal 5454, so tier 3's d_max is 54.5 mm), and a Chamfer of 5 mm on the
        first rim's outer top edge (y = 0, z = 235). The rim's other top edge lies 45 mm away."""
        body = models.body(doc)
        geometry = models.rectangle(0, 0, 3600, 45) + models.rectangle(0, 4045, 3600, 4090)
        profile = models.sketch(doc, "Profile", geometry, body)
        pad = models.pad(body, profile, 235, "Rims")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, edge("line", direction=X, through=(0, 0, 235)).one(pad.Shape))
        chamfer.Size = 5
        doc.recompute()
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        return pad, chamfer

    def redrawFirstRim(self, doc, corners):
        """The first rim's four lines deleted and the rim drawn again through `corners`: new
        geometry IDs, so no name relates its old edges to the new ones."""
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(models.polygon(corners), False)
        doc.recompute()

    def assertChamferAt(self, chamfer, pad, through):
        base, subs = chamfer.Base
        self.assertEqual(base, pad)
        [sub] = subs
        centre = pad.Shape.getElement(sub).CenterOfMass
        self.assertLess((centre - App.Vector(*through)).Length, 1e-6, (sub, centre))

    def assertBrokenAtThePlace(self, feature):
        """The feature's reference broke at the saved place: the one element there lost the old
        element's sources (T1''s test), and the record says it was in the model before (a sibling
        of the old element's sketch moved into its place, ops#526 D2), or comes from another
        object (PLAN decisions 155 and 184)."""
        self.assertFalse(feature.isValid(), feature.Name)
        rows = App.getReferenceReport(feature)
        self.assertIn("broken", [e["status"] for e in rows], rows)
        self.assertTrue(
            any(
                re.search(
                    "has another source|was in the model before|sides are not the old element's",
                    e.get("evidence", ""),
                )
                for e in rows
            ),
            rows,
        )

    def testExactPlaceRedrawInPlaceIsQuiet(self):
        """The first rim drawn again exactly where it was: no name relates the chamfered edge to
        the new rim's, and the board's other top edge lies 45 mm from it, within tier 3's d_max.
        The one edge at the saved place, with the saved length, lost the old line's ID, but its
        line is newer than the record's mark of the sketch and its faces are the old edge's: the
        element drawn again there, at the quieter same-place level (decision 97 Q3, restored by D2,
        ops#526; broken under PLAN decision 155 until then)."""
        doc = self.newDocument()
        pad, chamfer = self.chamferedRims(doc)

        self.redrawFirstRim(doc, [(3600, 45), (3600, 0), (0, 0), (0, 45)])

        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertChamferAt(chamfer, pad, (1800, 0, 235))
        [entry] = App.getReferenceReport(chamfer)
        self.assertEqual((entry["status"], entry["tier"]), ("resolved", 3), entry)
        self.assertTrue(
            entry["evidence"].startswith("no structural candidate, at the same place:"),
            entry["evidence"],
        )
        self.assertIn("drawn again there", entry["evidence"])
        self.assertEqual(
            chamfer.getStatusString(),
            "Warning: Edge reference found again in the same place (Base[0])",
        )

    def testRecordSavesSidesAndMarks(self):
        """Fingerprint version 7 (ops#526 D2): the fillet's record of the pad's vertical edge at
        (20, 0) saves its faces' outward normals (+x, -y) and the marks of what the pad is built
        from: the profile with its highest geometry ID, the pad without IDs."""
        doc = self.newDocument()
        pad, fillet = self.padWithFillet(doc)
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        fields = sub["fp"].split("|")
        self.assertEqual((fields[0], fields[1], len(fields)), ("7", "E", 15), sub["fp"])
        self.assertEqual(sorted(fields[13].split("/")), ["0,-1,0", "1,0,0"], sub["fp"])
        marks = dict(m.split(":") for m in fields[14].split("/"))
        ids = [doc.Profile.getGeometryId(i) for i in range(doc.Profile.GeometryCount)]
        self.assertGreaterEqual(int(marks[str(doc.Profile.ID)]), max(ids), marks)
        self.assertEqual(marks[str(pad.ID)], "_", marks)

    def testSketchNeverGivesAnIdAgainAfterAReload(self):
        """A sketch's highest geometry ID is saved (ops#526 D2, review F4): the last line deleted,
        the file saved and opened again, a new line gets an ID above the deleted one's, where the
        sketch used to give the deleted ID again."""
        doc = self.newDocument()
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), models.body(doc))
        doc.recompute()
        last = profile.getGeometryId(3)
        profile.delGeometries([3])
        doc.recompute()
        folder = tempfile.mkdtemp(prefix="NamingSolver")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Ids.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        self.documents.append(doc.Name)

        index = doc.Profile.addGeometry(Part.LineSegment(App.Vector(0, 10, 0), App.Vector(0, 0, 0)))
        self.assertGreater(doc.Profile.getGeometryId(index), last)

    def testRimMovedIntoAVacatedPlaceBreaks(self):
        """PR 379 round 3's Opus review: a third rim at y = 2000 in the same sketch; the first
        rim's lines deleted and the third rim's moved (IDs kept) onto the first rim's place. Its
        outer top edge lies at the saved place, a sibling's edge that existed before the edit: the
        chamfer breaks, never taken there quietly (PLAN decision 155); the record says its line
        was in the model before (ops#526 D2)."""
        doc = self.newDocument()
        body = models.body(doc)
        geometry = (
            models.rectangle(0, 0, 3600, 45)
            + models.rectangle(0, 2000, 3600, 2045)
            + models.rectangle(0, 4045, 3600, 4090)
        )
        profile = models.sketch(doc, "Profile", geometry, body)
        pad = models.pad(body, profile, 235, "Rims")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, edge("line", direction=X, through=(0, 0, 235)).one(pad.Shape))
        chamfer.Size = 5
        doc.recompute()
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())

        models.moveRectangle(profile, 0, 0, 3600, 45, first=4)
        profile.delGeometries([0, 1, 2, 3])
        doc.recompute()

        self.assertBrokenAtThePlace(chamfer)

    def testExactPlaceNeedsTheSameSize(self):
        """The control: the first rim drawn again 3000 long from the same corner. Its top edge's
        centre is 300 mm from the saved one and its length differs: nothing is at the saved place,
        and the reference is never taken quietly (broken, or a guess with the full warning)."""
        doc = self.newDocument()
        pad, chamfer = self.chamferedRims(doc)

        self.redrawFirstRim(doc, [(3000, 45), (3000, 0), (0, 0), (0, 45)])

        if chamfer.isValid():
            [entry] = App.getReferenceReport(chamfer)
            self.assertEqual(entry["warning_level"], "normal", entry["evidence"])
        else:
            [entry] = App.getReferenceReport(chamfer)
            self.assertEqual(entry["status"], "broken")

    # A held generator (ops#467): a hole across an edge, the edge moved off it

    def holedBlock(self, doc):
        """A Pad of 0..20 x 0..10, 10 high, and a refined Pocket (through all, midplane, along y)
        of a circle of radius 0.5 centred at x = 10 on the top edges' height, in an XZ sketch.
        The hole's vertices on the front top edge, at (9.5, 0, 10) and (10.5, 0, 10), are
        generated from that edge and the hole's cylinder, the second (where the circle's seam
        lies) from the edge and the seam. A datum point on each; returns (pad, hole sketch,
        points, their places)."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        xz = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 90))
        hole = models.sketch(doc, "Hole", [models.circle(10, 10, 0.5)], body, placement=xz)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = hole
        pocket.Type = 1  # through all
        pocket.Midplane = True
        pocket.Refine = True
        doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        points = []
        for x in (9.5, 10.5):
            [vertex] = pipes.elementsWhere(
                pocket.Shape, "Vertex", lambda p: (p - App.Vector(x, 0, 10)).Length < 1e-6
            )
            point = body.newObject("PartDesign::Point", "On" + vertex)
            point.AttachmentSupport = [(pocket, vertex)]
            point.MapMode = "Vertex"
            points.append(point)
        doc.recompute()
        return pad, hole, points, {p.Name: App.Vector(p.Placement.Base) for p in points}

    def moveCircle(self, sketch, x):
        geometry = sketch.Geometry
        geometry[0].Center = App.Vector(x, 10, 0)
        sketch.Geometry = geometry

    def testSeamVertexLeftByAMovedHole(self):
        """The Pad made 3 mm taller and the hole moved 2 mm along x: the front top edge, still
        there under its name, no longer meets the hole, which lies wholly in the front face. The
        seam vertex there links the seam and the front face; it shares most of the old seam
        vertex's ancestry, the maker and the sources, and tier 1 took it, 2 mm away and silently,
        so the reference didn't come back when the edit was undone. The front top edge didn't
        generate it: the references break or warn, and are in their place again once the Pad and
        the hole are back."""
        doc = self.newDocument()
        pad, hole, points, before = self.holedBlock(doc)

        pad.Length = 13
        self.moveCircle(hole, 12)
        doc.recompute()

        for point in points:
            if point.isValid():
                levels = [e.get("warning_level") for e in App.getReferenceReport(point)]
                self.assertIn("normal", levels, (point.Name, point.AttachmentSupport))

        pad.Length = 10
        self.moveCircle(hole, 10)
        doc.recompute()
        self.assertBackInPlace(points, before)

    # The same on a refined pipe's joint (ops#454's model). Since the Pipe's leg names (ops#415),
    # each leg's face has its own spine line as a source, so T1' keeps these loud without the
    # held-generator test; they pin that they stay so.

    def holedPipe(self, doc, heights):
        """ops#454's model: a refined "Transformed" pipe of the 4 x 4 square along TestPipe's U
        (legs 30, 20 and 20, turned 40 and 20 degrees), and a refined Pocket, through all and
        midplane along x, of circles of radius 0.5 at the `heights`, in a sketch on the plane
        x = 0 (sketch x is world y, sketch y world z). Returns (body, spine sketch, its points,
        pocket)."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(-2, -2, 2, 2), body)
        points = pipes.bendPoints(40, 20)
        path = models.sketch(doc, "Path", models.polyline(points), body, placement=pipes.XZ)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = True
        placement = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 1, 1), 120))
        circles = [models.circle(0, z, 0.5) for z in heights]
        hole = models.sketch(doc, "Hole", circles, body, placement=placement)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = hole
        pocket.Type = 1  # through all
        pocket.Midplane = True
        pocket.Refine = True
        doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        return body, path, points, pocket

    def pointsAt(self, body, target, at):
        """A datum point on each of the target's edges and vertices lying wholly in the square at
        the spine vertex `at`, with their places"""
        points = []
        for kind in ("Edge", "Vertex"):
            for element in pipes.elementsWhere(target.Shape, kind, pipes.inSquareAt(at)):
                point = body.newObject("PartDesign::Point", "On" + element)
                point.AttachmentSupport = [(target, element)]
                point.MapMode = "Vertex" if kind == "Vertex" else "CenterOfMass"
                points.append(point)
        body.Document.recompute()
        self.assertEqual([p.Name for p in points if not p.isValid()], [])
        return points, {p.Name: App.Vector(p.Placement.Base) for p in points}

    def setSpine(self, path, points):
        """The spine's lines moved through `points`, keeping their geometry IDs (a drag)"""
        models.setLines(path, {i: (p, q) for i, (p, q) in enumerate(zip(points, points[1:]))})
        path.Document.recompute()

    def assertNothingMovedSilently(self, points, before):
        """No point the solver re-bound lies elsewhere than it was without the normal warning: a
        point is invalid, at its place, warned, or follows its element by its exact name"""
        for point in points:
            if not point.isValid():
                continue
            for entry in App.getReferenceReport(point):
                if entry["status"] == "broken" or entry["tier"] == 0:
                    continue
                if entry.get("warning_level") == "normal":
                    continue
                moved = (point.Placement.Base - before[point.Name]).Length
                self.assertLess(moved, 1e-6, (point.Name, point.AttachmentSupport, entry))

    def assertBackInPlace(self, points, before):
        for point in points:
            self.assertTrue(point.isValid(), (point.Name, point.getStatusString()))
            moved = (point.Placement.Base - before[point.Name]).Length
            self.assertLess(moved, 1e-6, (point.Name, point.AttachmentSupport))

    def testHoleLeftByAMovedJoint(self):
        """Leg 0 made 1 mm longer: the first bend's joint rises off the hole, keeping its name.
        The hole's vertices where the joint entered it, at (+-2, -0.5, 30), were generated from
        the joint and the cylinder; the seam vertex on the same hole is 1 mm away (before the
        leg names, tier 1 took it silently, ops#467). Those references break or warn. The seam
        vertices at (+-2, 0.5, 30) are found at their place (the hole's seam is there still).
        Leg 0 back at 30: every point is in its place."""
        doc = self.newDocument()
        body, path, points, pocket = self.holedPipe(doc, [30])
        joint, before = self.pointsAt(body, pocket, App.Vector(0, 0, 30))
        # the joint edges' four pieces beside the hole and the hole's seam; the four corners, and
        # the hole's and the seam's vertices on the joint edges
        self.assertEqual(len(joint), 13, [p.Name for p in joint])

        self.setSpine(path, points[:1] + [(x, z + 1) for x, z in points[1:]])

        self.assertNothingMovedSilently(joint, before)
        onHole = [p for p in joint if p.MapMode == "Vertex" and abs(before[p.Name].z - 30) < 1e-6]
        holeVertices = [p for p in onHole if abs(before[p.Name].y + 0.5) < 1e-6]
        seamVertices = [p for p in onHole if abs(before[p.Name].y - 0.5) < 1e-6]
        self.assertEqual((len(holeVertices), len(seamVertices)), (2, 2), [p.Name for p in onHole])
        for point in holeVertices:
            if point.isValid():
                levels = [e.get("warning_level") for e in App.getReferenceReport(point)]
                self.assertIn("normal", levels, point.Name)
        for point in seamVertices:
            #   the seam vertex left the joint edge: its edges are not the old vertex's, so it
            #   breaks, the vertex at its place listed first (ops#526 D2, decision 219)
            self.assertFalse(point.isValid(), point.Name)
            [entry] = App.getReferenceReport(point)
            self.assertEqual(entry["status"], "broken", entry)
            self.assertIn("sides are not the old element's", entry["evidence"])
            first = pocket.Shape.getElement(entry["candidates"][0])
            self.assertLess((first.Point - before[point.Name]).Length, 1e-6, (point.Name, entry))

        self.setSpine(path, points)
        self.assertBackInPlace(joint, before)

    def testSeamVertexLeftByAStraightenedBend(self):
        """Holes across both bends' joints, the first bend made straight: the second bend moves
        12.9 mm, away from its hole, which now crosses leg 1. The seam vertices of that hole on the
        second bend's joint were generated from the joint and the seam; the hole's seam vertex now
        on leg 1 links the seam but not the joint, which is still there (before the leg names,
        tier 1 took it silently, ops#467). Those references break or warn; the bend turned back,
        every point is in its place."""
        doc = self.newDocument()
        bends = pipes.bendPoints(40, 20)[1:3]
        body, path, points, pocket = self.holedPipe(doc, [z for _, z in bends])
        x, z = points[2]
        joint, before = self.pointsAt(body, pocket, App.Vector(x, 0, z))
        self.assertGreater(len(joint), 4, [p.Name for p in joint])

        self.setSpine(path, pipes.bendPoints(0, 20))

        self.assertNothingMovedSilently(joint, before)

        self.setSpine(path, points)
        self.assertBackInPlace(joint, before)

    def testHoleVertexFollowsAJointStillCrossingIt(self):
        """The control: leg 0 made 0.3 mm longer, so the joint still crosses the hole, at
        y = +-0.4. The hole vertex at (2, -0.5, 30) follows it by its name to (2, -0.4, 30.3).
        Only the x = +2 side: on the other, the two crossings' names can swap (ops#468)."""
        doc = self.newDocument()
        body, path, points, pocket = self.holedPipe(doc, [30])
        joint, before = self.pointsAt(body, pocket, App.Vector(0, 0, 30))
        [hole] = [
            p
            for p in joint
            if p.MapMode == "Vertex" and (before[p.Name] - App.Vector(2, -0.5, 30)).Length < 1e-6
        ]

        self.setSpine(path, points[:1] + [(x, z + 0.3) for x, z in points[1:]])

        self.assertTrue(hole.isValid(), hole.getStatusString())
        moved = (hole.Placement.Base - App.Vector(2, -0.4, 30.3)).Length
        self.assertLess(moved, 1e-6, hole.AttachmentSupport)
        self.assertNothingMovedSilently(joint, before)

    # Twins (ops#503 class D, D1): a hole across an edge crosses it twice, at two vertices told
    # apart only by their place along the edge (the Index field), and leaves two vertical lines
    # on the front face told apart the same way. When one of them goes, the survivor carries the
    # old name's twin; a pick of it is never quiet.

    def crossedEdge(self, doc, turn=0, fillet=False):
        """A Pad of 0..20 x 0..10, 5 high, and a Pocket (through all, midplane) of a circle of
        radius 1 at (10, 0.5), its sketch turned by `turn` degrees about the centre: the circle
        crosses the top front edge (y = 0, z = 5) at x = 10 -+ 0.866, and its seam lies at its
        start point, on the right for no turn. A datum point on each crossing, left first; with
        `fillet`, a Fillet (0.3) on the front face's right vertical line. Returns (hole sketch,
        points, fillet or None)."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 5)
        hole = models.sketch(doc, "Hole", [models.circle(10, 0.5, 1)], body)
        if turn:
            rotation = App.Rotation(App.Vector(0, 0, 1), turn)
            centre = App.Vector(10, 0.5, 0)
            hole.Placement = App.Placement(centre - rotation.multVec(centre), rotation)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = hole
        pocket.Type = 1  # through all
        pocket.Midplane = True
        doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        points = []
        for x in (10 - 0.75**0.5, 10 + 0.75**0.5):
            [vertex] = pipes.elementsWhere(
                pocket.Shape, "Vertex", lambda p: (p - App.Vector(x, 0, 5)).Length < 1e-6
            )
            point = body.newObject("PartDesign::Point", "On" + vertex)
            point.AttachmentSupport = [(pocket, vertex)]
            point.MapMode = "Vertex"
            points.append(point)
        rounded = None
        if fillet:
            line = edge("line", direction=Z, through=(10 + 0.75**0.5, 0, 0)).one(pocket.Shape)
            rounded = body.newObject("PartDesign::Fillet", "Fillet")
            rounded.Base = (pocket, line)
            rounded.Radius = 0.3
        doc.recompute()
        for point in points:
            self.assertTrue(point.isValid(), point.getStatusString())
        if rounded:
            self.assertTrue(rounded.isValid(), rounded.getStatusString())
        return hole, points, rounded

    def moveHole(self, hole, x, y):
        """The hole's circle centred at (x, y) in the world, its sketch's turn kept"""
        hole.moveGeometry(0, 3, hole.Placement.inverse().multVec(App.Vector(x, y, 0)), False)
        hole.Document.recompute()

    def assertNeverQuietlyAt(self, point, wrong, right):
        """The point is broken, or sits at `right` with the normal warning; never at `wrong` and
        never at `right` quietly (no report row, or the same-place level)"""
        if not point.isValid():
            return
        at = point.Placement.Base
        levels = [e.get("warning_level") for e in App.getReferenceReport(point)]
        self.assertGreater((at - App.Vector(*wrong)).Length, 1e-6, (point.Name, levels))
        self.assertLess((at - App.Vector(*right)).Length, 1e-6, (point.Name, levels))
        self.assertIn("normal", levels, point.Name)

    def testCrossingThatBecameTheSeamVertexIsNotItsTwin(self):
        """The circle's centre moved onto the edge (y 0.5 -> 0): the right crossing becomes the
        seam vertex at (11, 0, 5), named after the seam, and the left one, at (9, 0, 5), keeps
        its name. The right point's name misses; the left crossing is its twin, the seam vertex
        the element: the right point at (11, 0, 5) with the normal warning, or broken; never on
        the left crossing. Builds differ in tier 1's survivors here (the twin alone, taken
        silently; or both, and tier 3 picks the seam vertex), so this is the end-to-end check,
        and the gtest twinSurvivorGoesToGeometry the fail-before."""
        doc = self.newDocument()
        hole, (left, right), _ = self.crossedEdge(doc)

        self.moveHole(hole, 10, 0)

        self.assertNeverQuietlyAt(right, (9, 0, 5), (11, 0, 5))
        self.assertTrue(left.isValid(), left.getStatusString())
        self.assertLess((left.Placement.Base - App.Vector(9, 0, 5)).Length, 1e-6)

    def testTwinLandingOnTheSavedPlaceBreaks(self):
        """CC1 (ops#503 round 2): the circle moved to (11.866, 0): the left crossing lands exactly
        where the right one was, and the right one becomes the seam vertex, 2 mm further, at
        (12.866, 0, 5). The right point's name misses and its twin sits at the saved place; the
        twins' record says 2 and the shape holds 1 now, so the pick is a trade: the right point
        breaks (or is warned at 12.866), never at 10.866 quietly. The left point follows its
        name, or breaks."""
        doc = self.newDocument()
        hole, (left, right), _ = self.crossedEdge(doc)
        landing = 10 + 0.75**0.5

        self.moveHole(hole, landing + 1, 0)

        self.assertNeverQuietlyAt(right, (landing, 0, 5), (landing + 2, 0, 5))
        if left.isValid():
            self.assertLess((left.Placement.Base - App.Vector(landing, 0, 5)).Length, 1e-6)

    def testLoneTwinIsNotAnotherHolesCrossing(self):
        """PR 379 round 1 (R1): a plate 200 x 100 x 5 with two through holes of radius 1 crossing
        its top front edge, A at (100, 0.5) and B, from another sketch, at (102.5, 0.5); a datum
        point on A's right crossing (100.866). Hole A moved to (0.3, 0.5): its left crossing
        falls off the edge's end and the right one, alone, is renumbered. Tier 1's one survivor
        is the old element's twin, so geometry decides, and B's left crossing (101.634) lies
        0.77 from the saved place: another hole's vertex, of another sketch and another Pocket,
        is no pick. The point breaks, or sits on A's crossing (1.166) with the normal warning;
        never on B's."""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 200, 100), body)
        models.pad(body, profile, 5)
        holes = []
        for name, x in (("HoleA", 100), ("HoleB", 102.5)):
            sketch = models.sketch(doc, name, [models.circle(x, 0.5, 1)], body)
            pocket = body.newObject("PartDesign::Pocket", "Pocket" + name[-1])
            pocket.Profile = sketch
            pocket.Type = 1  # through all
            pocket.Midplane = True
            holes.append((sketch, pocket))
        doc.recompute()
        [(hole, _), (_, last)] = holes
        half = 0.75**0.5
        [vertex] = pipes.elementsWhere(
            last.Shape, "Vertex", lambda p: (p - App.Vector(100 + half, 0, 5)).Length < 1e-6
        )
        point = body.newObject("PartDesign::Point", "OnRight")
        point.AttachmentSupport = [(last, vertex)]
        point.MapMode = "Vertex"
        doc.recompute()
        self.assertTrue(point.isValid(), point.getStatusString())

        self.moveHole(hole, 0.3, 0.5)

        self.assertNeverQuietlyAt(point, (102.5 - half, 0, 5), (0.3 + half, 0, 5))

    def sameSketchHoles(self, doc):
        """R1's plate with both circles in one sketch, `Holes`, cut by one Pocket: A at
        (100, 0.5), B at (102.5, 0.5), and a datum point on A's right crossing (100.866)"""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 200, 100), body)
        models.pad(body, profile, 5)
        holes = models.sketch(
            doc, "Holes", [models.circle(100, 0.5, 1), models.circle(102.5, 0.5, 1)], body
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = holes
        pocket.Type = 1  # through all
        pocket.Midplane = True
        doc.recompute()
        half = 0.75**0.5
        [vertex] = pipes.elementsWhere(
            pocket.Shape, "Vertex", lambda p: (p - App.Vector(100 + half, 0, 5)).Length < 1e-6
        )
        point = body.newObject("PartDesign::Point", "OnRight")
        point.AttachmentSupport = [(pocket, vertex)]
        point.MapMode = "Vertex"
        doc.recompute()
        self.assertTrue(point.isValid(), point.getStatusString())
        return holes, point

    def testLoneTwinIsNotASiblingCirclesCrossing(self):
        """PR 379 round 2's cloud review (F1), R1 with both holes drawn in one sketch: A moved to
        (0.3, 0.5), its right crossing alone and renumbered. B's crossings share A's sketch and
        Pocket, so the origin gate passes them, but they come from another circle of the sketch
        (T1''s test): B's left crossing (101.634), 0.77 from the saved place, is no pick. The
        point breaks, or sits on A's crossing (1.166) with the normal warning; never on B's."""
        doc = self.newDocument()
        holes, point = self.sameSketchHoles(doc)
        half = 0.75**0.5

        holes.moveGeometry(0, 3, App.Vector(0.3, 0.5, 0), False)
        doc.recompute()

        self.assertNeverQuietlyAt(point, (102.5 - half, 0, 5), (0.3 + half, 0, 5))

    def testLoneTwinIsNotASiblingCirclesCrossingAtThePlace(self):
        """F1's quiet form: the same edit also moves B to (100 + 2 * 0.866, 0.5), so its left
        crossing lies exactly at the saved place (100.866, 0, 5). Taken there, the batch gave it
        the same-place level, with no warning. The point breaks, or sits on A's crossing (1.166)
        with the normal warning; never at the saved place."""
        doc = self.newDocument()
        holes, point = self.sameSketchHoles(doc)
        half = 0.75**0.5

        holes.moveGeometry(0, 3, App.Vector(0.3, 0.5, 0), False)
        holes.moveGeometry(1, 3, App.Vector(100 + 2 * half, 0.5, 0), False)
        doc.recompute()

        self.assertNeverQuietlyAt(point, (100 + half, 0, 5), (0.3 + half, 0, 5))

    def testSiblingCirclesCrossingAtThePlaceIsNotQuiet(self):
        """The cloud review's pre-existing path, without the twin clause: A moved off the edge to
        (100, 10), so both its crossings are gone and T1' drops B's (another circle of the
        sketch); B moved to (100 + 2 * 0.866, 0.5), its left crossing exactly at the saved place.
        Nothing tells it from A's circle drawn there again: the point breaks (PLAN decision 155)."""
        doc = self.newDocument()
        holes, point = self.sameSketchHoles(doc)
        half = 0.75**0.5

        holes.moveGeometry(0, 3, App.Vector(100, 10, 0), False)
        holes.moveGeometry(1, 3, App.Vector(100 + 2 * half, 0.5, 0), False)
        doc.recompute()

        self.assertBrokenAtThePlace(point)

    def testSiblingCirclesCrossingAtThePlaceWithTheHoleOffThePlateBreaks(self):
        """S1 (PR 379 round 3's cloud review): the same edit with A moved off the plate. A's
        circle is still in the sketch, but no element of the Pocket's shape holds its ID, so the
        batch took B's crossing at the saved place quietly, as if A's circle had been drawn there
        again. The point breaks (PLAN decision 155)."""
        doc = self.newDocument()
        holes, point = self.sameSketchHoles(doc)
        half = 0.75**0.5

        holes.moveGeometry(0, 3, App.Vector(100, -50, 0), False)
        holes.moveGeometry(1, 3, App.Vector(100 + 2 * half, 0.5, 0), False)
        doc.recompute()

        self.assertBrokenAtThePlace(point)

    @unittest.expectedFailure
    def testCrossingWhoseTwinBecameTheSeamVertexIsLoud(self):
        """CC2 (ops#503 round 2), the mirrored seam: the hole's sketch turned 180 degrees (seam
        on the left), then its centre moved onto the edge. The left crossing becomes the seam
        vertex at (9, 0, 5); the right one, alone, is renumbered and carries the left one's old
        name, so the left point follows it 1.866 mm by its name, silently (an exact hit, no
        report row). It must break, or sit at (9, 0, 5) with a warning; never at (11, 0, 5).
        Fails until D3's vanished-twin net (or A2)."""
        doc = self.newDocument()
        hole, (left, right), _ = self.crossedEdge(doc, turn=180)

        self.moveHole(hole, 10, 0)

        self.assertNeverQuietlyAt(left, (11, 0, 5), (9, 0, 5))

    @unittest.expectedFailure
    def testFilletOnATwinEdgeIsLoudWhenItsTwinGoes(self):
        """The edge form (ops#503 round 2): a Fillet on the front face's right vertical line, the
        circle's centre moved onto the edge (seam on the right). The right line becomes the seam's
        B-spline and the left one, alone, takes the right one's old name: the fillet follows it to
        x = 9, an exact hit, silently. It must break; never compute on the line at x = 9. Fails
        until D3's vanished-twin net."""
        doc = self.newDocument()
        hole, _, fillet = self.crossedEdge(doc, fillet=True)
        pocket = doc.Pocket

        self.moveHole(hole, 10, 0)

        if fillet.isValid():
            [sub] = fillet.Base[1]
            x = pocket.Shape.getElement(sub).CenterOfMass.x
            self.assertGreater(abs(x - 9), 1e-3, (sub, App.getReferenceReport(fillet)))

    def testTaperedPadsTopRimArcIsNotItsBottomArc(self):
        """CC3 (class B's review): a Pad 20 x 10 x 5 with a through hole of radius 2 at (10, 0)
        and a Fillet (0.3) on the hole's top rim arc; then the Pad tapered by 1 degree. The draft
        renames the caps (index names of the offset wire), so the top rim arc's face generator,
        the top cap, is held by no face, and tier 1 kept the bottom rim arc, 5 mm down, silently.
        The fillet's reference breaks, or lies on an arc at z = 5 with the normal warning; never
        on the bottom arc."""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 5)
        doc.recompute()
        hole = models.sketch(doc, "Hole", [models.circle(10, 0, 2)], body, z=5)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = hole
        pocket.Type = 1  # through all
        pocket.Midplane = True
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, edge("circle", center=(10, 0, 5), radius=2).one(pocket.Shape))
        fillet.Radius = 0.3
        doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())

        pad.TaperAngle = 1
        doc.recompute()

        rows = App.getReferenceReport(fillet)
        if fillet.isValid():
            [sub] = fillet.Base[1]
            z = pocket.Shape.getElement(sub).CenterOfMass.z
            self.assertLess(abs(z - 5), 1e-6, (sub, rows))
            self.assertIn("normal", [e.get("warning_level") for e in rows], rows)
        else:
            self.assertIn("broken", [e["status"] for e in rows], rows)

    def testExactPlaceFromAnotherSketchBreaks(self):
        """XP's source condition (ops#503 D1): the rims padded from a new sketch with the same
        rectangles. The chamfered edge's name misses, and the one edge at its saved place comes
        from another sketch, policy D's new sketch object: it lost the old edge's sources, so it
        breaks like a redraw (PLAN decision 155)."""
        doc = self.newDocument()
        pad, chamfer = self.chamferedRims(doc)

        geometry = models.rectangle(0, 0, 3600, 45) + models.rectangle(0, 4045, 3600, 4090)
        pad.Profile = models.sketch(doc, "Redrawn", geometry, pad.getParentGeoFeatureGroup())
        doc.recompute()

        self.assertBrokenAtThePlace(chamfer)
