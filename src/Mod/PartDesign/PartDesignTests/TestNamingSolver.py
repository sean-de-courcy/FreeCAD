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
        self.assertIn("Broken reference AttachmentSupport[0]: ?Face", point.getStatusString())
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
        self.assertIn("Broken reference Support[0]", binder.getStatusString())

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
        self.assertNotIn("Broken reference", fillet.getStatusString())
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

        #   the break is stable
        pad.touch()
        doc.recompute()
        self.assertFalse(sketch.isValid())

        #   a repair to one piece holds
        App.repairReference(sketch, "ExternalGeometry", 0, pieces[0])
        doc.recompute()
        self.assertTrue(sketch.isValid())
        pad.touch()
        doc.recompute()
        self.assertTrue(sketch.isValid())

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
