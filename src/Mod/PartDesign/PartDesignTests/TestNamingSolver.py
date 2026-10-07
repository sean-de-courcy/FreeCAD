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
        that every other edge is within d_max) and the guess rules off (their wider tier 3 would
        decide), reopening the stale-name file breaks the reference, and the version change then
        restores it."""
        # Arrange
        group = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/NamingSolver")
        group.SetFloat("Tier3Distance", 100.0)
        self.addCleanup(group.RemFloat, "Tier3Distance")
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
        # NaN last; the survivors tier 1 dropped (ops#174) come after the ranked ones
        dropped = ("other maker", "other source")
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
        NamingSolver/Tier1SameMaker off, tier 1 takes B's circle as before."""
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

        #   the switches off (T1 and T1', ops#173)
        self.guessSwitch("Tier1SameMaker", False)
        self.guessSwitch("Tier1SameSource", False)
        doc = self.newDocument()
        last, fillet = self.filletedHoles(doc, (holeA, holeB), 0.5)
        self.deleteHoleA(doc)
        [bottom] = edge("circle", center=(22, 10, 0), radius=2).one(last.Shape)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(fillet.Base[1], [bottom])
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual((entry["status"], entry["tier"]), ("resolved", 1))

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
        and its rim second. With NamingSolver/Tier1SameSource off, tier 1 takes it as before."""
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
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                self.assertEqual(fillet.Base[1], [bottom])
                self.assertEqual((entry["status"], entry["tier"]), ("resolved", 1))

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
        them and stays tier 1's, no warning."""
        doc = self.newDocument()
        pocket, fillet = self.filletedHole(doc)

        for _ in range(4):
            doc.Profile.delGeometry(0)
        doc.Profile.addGeometry(models.rectangle(0, 0, 30, 20), False)
        doc.recompute()

        self.assertHoleCircleKept(pocket, fillet, 1)

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

    def assertWarnedInPlace(self, owner, kind, expected):
        """The reference resolved by geometry at tier 3, on `expected`, with a warning. Returns
        its report row."""
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertIn("Warning", owner.State)
        [entry] = App.getReferenceReport(owner)
        self.assertEqual((entry["status"], entry["tier"]), ("resolved", 3), entry)
        self.assertIn(f"{kind} reference resolved by geometry: {expected}", owner.getStatusString())
        return entry

    def testHorizontalHoleKeepsTheEntryCircle(self):
        """ops#183: a hole through the block from its front face (y = 0) to its back (y = 20); a
        fillet on its entry circle. The block's whole profile is redrawn, every line a new
        geometry ID, which renames both circles. T1' asks only for the hole's own source (its
        circle), which the exit circle keeps too: both survive tier 1 with equal overlap. Tier 3
        takes the entry circle, in place, with a warning, and lists the exit circle, 20 mm away,
        as the alternative. Never the exit circle, and never silently."""
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

        [entry] = entryCircle.one(pocket.Shape)
        [exitCircle] = edge("circle", center=(15, 20, 5), radius=2).one(pocket.Shape)
        self.assertNotEqual(pocket.Shape.getElementMappedName(entry), oldName)
        self.assertEqual(fillet.Base[1], [entry])
        row = self.assertWarnedInPlace(fillet, "Edge", entry)
        self.assertIn(exitCircle, [a["index"] for a in row["alternatives"]])

    def testPatternedHoleUnderARedrawnProfileWarns(self):
        """ops#183: T1''s fallback. A hole pocketed at (8, 10) and patterned 14 mm along x; a
        fillet on the patterned hole's bottom circle at (22, 10, 0). The block's whole profile is
        redrawn, which renames the circle. Its maker is the pattern, which made no input of the
        name itself, so T1' asks for every known source, the block's lines among them: the circle
        lost them and isn't tier 1's. Tier 3 takes it in place, with a warning. With
        NamingSolver/Tier1SameSource off, tier 1 takes it silently (round 0's behaviour there)."""
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
            if sameSource:
                self.assertWarnedInPlace(fillet, "Edge", bottom)
            else:
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                self.assertNotIn("Warning", fillet.State)
                [entry] = App.getReferenceReport(fillet)
                self.assertEqual((entry["status"], entry["tier"]), ("resolved", 1))

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
        place, with a warning (also with T1' off)."""
        for redrawn in ("ProfileB", "Profile"):
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
            self.assertEqual(sketch.AttachmentSupport[0][1], (merged,))
            if redrawn == "ProfileB":
                self.assertTrue(sketch.isValid(), sketch.getStatusString())
                self.assertNotIn("Warning", sketch.State)
                self.assertFalse(App.getReferenceReport(sketch))
            else:
                self.assertWarnedInPlace(sketch, "Face", merged)

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
        self.assertEqual(fillet.Base[1], [merged])
        self.assertWarnedInPlace(fillet, "Edge", merged)

    def testCollarFromExternalGeometry(self):
        """ops#183: a collar padded 3 mm on the block from a sketch of a circle (radius 4) and,
        as defining external geometry, the hole's top circle (radius 2); a fillet (0.3) on the
        collar's inner top circle, made from the external circle. The hole moved 1 mm: the
        external circle follows it and keeps its geometry ID, so the circle keeps its name:
        exact. The external circle deleted and added again: a new geometry ID renames the
        circle, and no element has its structure: tier 3 takes it in place, with a warning."""
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

            if edit == "move":
                geometry = holeSketch.Geometry
                geometry[0].Center = App.Vector(9, 10, 0)
                holeSketch.Geometry = geometry
                inner = edge("circle", center=(9, 10, 13), radius=2)
            else:
                sketch.delExternal(0)
                doc.recompute()
                [holeTop] = edge("circle", center=(8, 10, 10), radius=2).one(hole.Shape)
                sketch.addExternal(hole.Name, holeTop, True)
            doc.recompute()

            [circle] = inner.one(collar.Shape)
            self.assertEqual(fillet.Base[1], [circle])
            if edit == "move":
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                self.assertNotIn("Warning", fillet.State)
                self.assertFalse(App.getReferenceReport(fillet))
            else:
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
