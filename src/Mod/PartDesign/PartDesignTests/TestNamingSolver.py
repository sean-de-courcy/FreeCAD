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

import FreeCAD as App

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

    def testReverseUpdateCarriesTheIndexWhenTheFingerprintAgrees(self):
        """A reference whose mapped name is gone after an element-map version change is
        re-derived by its index, checked against its saved fingerprint: the same geometry
        resolves ("index"). The stale name is written into the saved file; reopening breaks the
        reference (no name relates it), and the version change then restores it."""
        # Arrange
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
