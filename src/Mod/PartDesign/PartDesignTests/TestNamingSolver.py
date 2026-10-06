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

import os
import re
import shutil
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree

import FreeCAD as App
import Part

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
        that every other edge is within d_max), reopening the stale-name file breaks the
        reference, and the version change then restores it."""
        # Arrange
        group = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/NamingSolver")
        group.SetFloat("Tier3Distance", 100.0)
        self.addCleanup(group.RemFloat, "Tier3Distance")
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

    def testSetterDropsFrom(self):
        """Setting the property anew, even to the same subs, drops `from`: the user chose them."""
        doc = self.newDocument()
        rib, fillet, name = self.ribAcrossFillet(doc)
        models.moveRectangle(doc.RibSketch, 8, -3, 12, 3)
        doc.recompute()
        self.assertEqual(self.froms(doc), [name, name])

        fillet.Base = (rib, list(fillet.Base[1]))

        self.assertEqual(self.froms(doc), [None, None])

    def notch(self, doc):
        """Cuts a notch (x 8..12, 2 deep) into the front of the profile: the front line ends at
        x = 8, and four new lines follow, the last one the rest of the side (x 12..20)."""
        models.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(
            models.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False
        )
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
            lambda: group.SetBool("NamingMultiMatch", old)
            if had
            else group.RemBool("NamingMultiMatch")
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
        state and a text naming the edge, the original and the tier; the reference holds the
        edge, and its saved record names the original."""
        doc, pad, fillet, original = self.redrawnFillet()

        corner = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)
        self.assertEqual(fillet.Base[1], corner)
        self.assertIn("Warning", fillet.State)
        self.assertEqual(
            fillet.getStatusString(),
            "Warning: Edge reference resolved by geometry: %s for %s (Base[0], tier 3)"
            % (corner[0], original),
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
        fillet fails naming it."""
        doc, pad, fillet, original = self.redrawnFillet()

        App.markReferenceBroken(fillet, "Base", 0)
        doc.recompute()

        self.assertFalse(fillet.isValid())
        self.assertEqual(fillet.Base[1], ["?" + original])
        self.assertIn("Missing edge reference: " + original, fillet.getStatusString())
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        self.assertNotIn("guess", sub)
        self.assertIn("fp", sub)  # for a retry

    def testSetterDropsTheRecord(self):
        """Setting the property anew, even to the same sub, drops the record: the user chose it."""
        doc, pad, fillet, original = self.redrawnFillet()

        fillet.Base = (pad, list(fillet.Base[1]))
        doc.recompute()

        self.assertTrue(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        [sub] = self.savedSubs(doc, "Fillet", "Base")
        self.assertNotIn("guess", sub)

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
