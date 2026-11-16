# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (notes/derived-design.md, slice 1: Derived from another document)

"""Onshape's Derived from another document: freecad.derived and PartDesign.makeDerivedCopies.

The saved source file stands for Onshape's version: the owner holds a copy of each part, made and
refreshed from the saved file only, so it opens and recomputes without the source, keeps its parts
when the source changes, and takes the change on Refresh.

Designed geometry. The source document has a studio S (an App::Part placed at x = 100) with Body A,
a 10 x 10 x 10 box at S's origin (1000 mm^3), and Body B, a 30 x 10 x 10 box from x = 20 in S
(3000 mm^3). The owner has a studio T at the origin. A derived A lies in T as A lies in S: x from 0
to 10. A 2 x 2 x 10 pocket box (40 mm^3) is cut from it: 960 mm^3."""

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import PartDesign
from freecad import derived

V = App.Vector


def boxBody(doc, studio, name, length, x=0):
    body = doc.addObject("PartDesign::Body", name)
    studio.addObject(body)
    box = body.newObject("PartDesign::AdditiveBox", name + "Box")
    box.Length = length
    box.Width = box.Height = 10
    box.Placement.Base = V(x, 0, 0)
    return body, box


class TestDerivedFiles(unittest.TestCase):
    def setUp(self):
        # Documents other suites left open under -t 0 (e.g. CAM's): not this test's to judge
        self.others = set(App.listDocuments())
        self.dir = tempfile.mkdtemp(prefix="derivedfiles")
        self.sourcePath = os.path.join(self.dir, "Source.FCStd")
        self.ownerPath = os.path.join(self.dir, "Owner.FCStd")
        src = App.newDocument("DerivedSource")
        studio = src.addObject("App::Part", "S")
        studio.Placement.Base = V(100, 0, 0)
        boxBody(src, studio, "A", 10)
        boxBody(src, studio, "B", 30, x=20)
        src.recompute()
        src.saveAs(self.sourcePath)
        App.closeDocument(src.Name)
        self.owner = App.newDocument("DerivedOwner")
        self.studio = self.owner.addObject("App::Part", "T")
        self.owner.recompute()
        self.owner.saveAs(self.ownerPath)

    def tearDown(self):
        for name in list(App.listDocuments()):
            if name.startswith("Derived") or name.startswith("Owner") or name.startswith("Source"):
                App.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    # helpers

    def derive(self, *parts):
        return derived.derive_from_file(self.owner, self.studio, self.sourcePath, "S", list(parts))

    def bodyOf(self, member):
        return member.getParentGeoFeatureGroup()

    def pocket(self, lead):
        cut = self.bodyOf(lead).newObject("PartDesign::SubtractiveBox", "Pocket")
        cut.Length = cut.Width = 2
        cut.Height = 10
        cut.Placement.Base = V(4, 4, 0)
        self.owner.recompute()
        return cut

    def editSource(self, edit):
        """Opens the saved source, applies edit(doc), recomputes, saves, closes."""
        src = App.openDocument(self.sourcePath)
        edit(src)
        src.recompute()
        src.save()
        App.closeDocument(src.Name)

    def reopenOwner(self):
        self.owner.save()
        App.closeDocument(self.owner.Name)
        self.owner = App.openDocument(self.ownerPath)
        self.studio = self.owner.getObject("T")

    def lead(self):
        [lead] = [
            o for o in self.owner.Objects
            if o.TypeId == "PartDesign::FeatureBase" and PartDesign.derivedLead(o) is o
        ]
        return lead

    def copies(self):
        return [o for o in self.owner.Objects if PartDesign.isDerivedCopy(o)]

    # cases

    def testADerivedPartLiesInItsStudioAsInTheSource(self):
        """A derived into T: one Body there with 1000 mm^3 from x = 0 to 10 (A's place in S, not in
        the document), on a hidden derived copy that T holds; the lead names A, S and the file."""
        lead = self.derive("A")
        self.assertTrue(lead.isValid(), lead.getStatusString())
        self.assertEqual(lead.DerivedFrom, "A (S) in Source.FCStd")
        body = self.bodyOf(lead)
        self.assertIs(PartDesign.studioOf(body), self.studio)
        self.assertAlmostEqual(body.Shape.Volume, 1000, places=6)
        box = body.Shape.BoundBox
        self.assertAlmostEqual(box.XMin, 0, places=6)
        self.assertAlmostEqual(box.XMax, 10, places=6)
        [copy] = self.copies()
        self.assertIn(copy, self.studio.Group)
        self.assertFalse(copy.Visibility)
        self.assertEqual(copy.DerivedSourcePart, "A")
        self.assertEqual(copy.DerivedSourceFile, "Source.FCStd")
        self.assertEqual(derived.derived_state(lead), derived.UP_TO_DATE)
        # the source isn't left open
        self.assertEqual(sorted(set(App.listDocuments()) - self.others), ["DerivedOwner"])

    def testLaterFeaturesCutTheDerivedPart(self):
        lead = self.derive("A")
        cut = self.pocket(lead)
        self.assertTrue(cut.isValid(), cut.getStatusString())
        self.assertAlmostEqual(self.bodyOf(lead).Shape.Volume, 960, places=6)

    def testTwoParts(self):
        """A and B in one Derived feature: two Bodies in T, 1000 and 3000 mm^3, B from x = 20."""
        lead = self.derive("A", "B")
        members = PartDesign.derivedMembers(lead)
        self.assertEqual(len(members), 2)
        volumes = sorted(round(self.bodyOf(m).Shape.Volume, 6) for m in members)
        self.assertEqual(volumes, [1000, 3000])
        bBody = [self.bodyOf(m) for m in members if m.BaseFeature.DerivedSourcePart == "B"][0]
        self.assertAlmostEqual(bBody.Shape.BoundBox.XMin, 20, places=6)

    def testReopensWithoutTheSource(self):
        """Owner saved and reopened with the source file gone: the same 960 mm^3 after a recompute,
        no other document opened, the state "not found", and Refresh refuses changing nothing."""
        lead = self.derive("A")
        self.pocket(lead)
        os.rename(self.sourcePath, self.sourcePath + ".gone")
        self.reopenOwner()
        self.owner.recompute()
        lead = self.lead()
        self.assertTrue(lead.isValid(), lead.getStatusString())
        self.assertAlmostEqual(self.bodyOf(lead).Shape.Volume, 960, places=6)
        self.assertEqual(sorted(set(App.listDocuments()) - self.others), ["Owner"])
        self.assertEqual(derived.derived_state(lead), derived.NOT_FOUND)
        with self.assertRaises(derived.DerivedError):
            derived.refresh_derived(lead)
        self.assertAlmostEqual(self.bodyOf(lead).Shape.Volume, 960, places=6)

    def testTheSourceEditedChangesNothingUntilRefresh(self):
        """A made 15 long and saved: the owner is "out of date" and stays 960 mm^3 through a
        recompute; Refresh makes it 1460 mm^3 (1500 - 40), up to date, as one undo step."""
        lead = self.derive("A")
        self.pocket(lead)
        self.editSource(lambda src: setattr(src.getObject("ABox"), "Length", 15))
        self.assertEqual(derived.derived_state(lead), derived.OUT_OF_DATE)
        self.owner.recompute()
        self.assertAlmostEqual(self.bodyOf(lead).Shape.Volume, 960, places=6)
        self.owner.UndoMode = 1
        derived.refresh_derived(lead)
        self.assertAlmostEqual(self.bodyOf(lead).Shape.Volume, 1460, places=6)
        self.assertEqual(derived.derived_state(lead), derived.UP_TO_DATE)

    def testRefreshReadsTheSavedFileNotTheOpenDocument(self):
        """The source open with an unsaved edit (A 20 long): Refresh copies the saved A (10)."""
        lead = self.derive("A")
        src = App.openDocument(self.sourcePath)
        src.getObject("ABox").Length = 20
        src.recompute()
        derived.refresh_derived(lead)
        self.assertAlmostEqual(self.bodyOf(lead).Shape.Volume, 1000, places=6)

    def testAPartGoneAtTheSourceFailsOnRefresh(self):
        """A deleted at the source and saved: until Refresh the owner keeps it; after, the member
        fails "Missing source part" naming A, and so does what was built on it."""
        lead = self.derive("A")
        self.pocket(lead)

        def delete(src):
            body = src.getObject("A")
            body.removeObjectsFromDocument()
            src.removeObject("A")

        self.editSource(delete)
        self.owner.recompute()
        self.assertTrue(lead.isValid())
        derived.refresh_derived(lead)
        self.assertFalse(lead.isValid())
        self.assertIn("Missing source part: A (S)", lead.getStatusString())
        self.assertFalse(self.bodyOf(lead).isValid())

    def testRefusals(self):
        """A missing file, the owner's own file, a part S doesn't have, no part: DerivedError and
        nothing added to the owner."""
        before = len(self.owner.Objects)
        with self.assertRaises(derived.DerivedError):
            derived.derive_from_file(self.owner, self.studio, self.sourcePath + "x", "S", ["A"])
        with self.assertRaises(derived.DerivedError):
            derived.derive_from_file(self.owner, self.studio, self.ownerPath, "", ["A"])
        with self.assertRaises(derived.DerivedError):
            self.derive("C")
        with self.assertRaises(derived.DerivedError):
            self.derive()
        self.assertEqual(len(self.owner.Objects), before)

    def testDeletingTheFeatureRemovesItsCopies(self):
        lead = self.derive("A", "B")
        PartDesign.deleteDerivedParts(lead)
        self.owner.removeObject(lead.Name)
        self.owner.recompute()
        self.assertEqual(self.copies(), [])
        self.assertEqual([o for o in self.owner.Objects if o.TypeId == "PartDesign::Body"], [])
