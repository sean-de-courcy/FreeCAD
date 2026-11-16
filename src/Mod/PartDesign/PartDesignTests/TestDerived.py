# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 round 6, notes/onshape-tabs-design.md 2.5 and 6: Derived)

"""Onshape's Derived inside one document: PartDesign.makeDerived and its friends (Derived.h).

A Derived feature brings parts of another part studio into this one: per part a new Body built on
a SubShapeBinder of the source part as its base feature, so it follows the source. Its members
are the new Bodies' base features; the last one made is the lead, whose row stands for the
feature ("Derived N").

Designed geometry: Part Studio 1 (the document's top level) holds a Body "Box" with a 10 x 10 x 10
box at the origin (1000 mm^3) and a Body "Bar" 30 x 10 x 10 from x = 20 (3000 mm^3); Part Studio 2
is an App::Part at the origin. The expected results are the boxes' own volumes and bounding boxes:
the derived part lies where its source lies in its studio."""

import math
import os
import tempfile
import unittest

import FreeCAD as App
import PartDesign

V = App.Vector


def boxBody(doc, name, length, x=0):
    body = doc.addObject("PartDesign::Body", name)
    box = body.newObject("PartDesign::AdditiveBox", name + "Box")
    box.Length = length
    box.Width = box.Height = 10
    box.Placement.Base = V(x, 0, 0)
    return body, box


def sameBox(test, one, other):
    for a, b in zip(
        (one.XMin, one.YMin, one.ZMin, one.XMax, one.YMax, one.ZMax),
        (other.XMin, other.YMin, other.ZMin, other.XMax, other.YMax, other.ZMax),
    ):
        test.assertAlmostEqual(a, b, places=6)


class TestDerived(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("Derived")
        self.box, self.boxFeature = boxBody(self.doc, "Box", 10)
        self.bar, self.barFeature = boxBody(self.doc, "Bar", 30, x=20)
        self.studio2 = self.doc.addObject("App::Part", "Studio2")
        self.studio2.Label = "Part Studio 2"
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def derive(self, *sources):
        lead = PartDesign.makeDerived(self.studio2, list(sources))
        self.doc.recompute()
        return lead

    def bodyOf(self, member):
        return member.getParentGeoFeatureGroup()

    def derivedBodies(self):
        return [o for o in self.studio2.Group if o.TypeId == "PartDesign::Body"]

    def testADerivedBoxIsTheBox(self):
        """Part Studio 1's box derived into Part Studio 2: one new Body there, labelled "Box" as
        Onshape names a derived part by its source (FreeCAD makes the label unique), built on a
        hidden binder of the box; 1000 mm^3 and the box's bounding box. The lead is "Derived 1",
        names its source "Box (Part Studio 1)", and is its own lead."""
        lead = self.derive(self.box)
        self.assertEqual(lead.Label, "Derived 1")
        self.assertEqual(lead.DerivedFrom, "Box (Part Studio 1)")
        self.assertIs(PartDesign.derivedLead(lead), lead)
        self.assertEqual(PartDesign.derivedMembers(lead), [lead])
        self.assertIs(PartDesign.derivedSource(lead), self.box)
        [body] = self.derivedBodies()
        self.assertIs(self.bodyOf(lead), body)
        self.assertIs(PartDesign.studioOf(body), self.studio2)
        self.assertTrue(body.Label.startswith("Box"))
        binder = lead.BaseFeature
        self.assertEqual(binder.TypeId, "PartDesign::SubShapeBinder")
        self.assertIn(binder, self.studio2.Group)
        self.assertFalse(binder.Visibility)
        self.assertTrue(lead.isValid(), lead.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 1000, places=6)
        sameBox(self, body.Shape.BoundBox, self.box.Shape.BoundBox)

    def testItFollowsTheSource(self):
        """The box to 15 mm long: after a recompute the derived part is 1500 mm^3 with the box's
        new bounding box."""
        lead = self.derive(self.box)
        body = self.bodyOf(lead)
        self.boxFeature.Length = 15
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 1500, places=6)
        sameBox(self, body.Shape.BoundBox, self.box.Shape.BoundBox)

    def testSaveAndReopen(self):
        """Saved and reopened: the same volume, the same lead and source; it still follows the
        source after the reopen (the box to 15 mm: 1500 mm^3)."""
        name = self.derive(self.box).Name
        path = os.path.join(tempfile.mkdtemp(), "derived.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        lead = self.doc.getObject(name)
        box = self.doc.getObject("Box")
        body = self.bodyOf(lead)
        self.assertAlmostEqual(body.Shape.Volume, 1000, places=6)
        self.assertIs(PartDesign.derivedLead(lead), lead)
        self.assertIs(PartDesign.derivedSource(lead), box)
        self.assertEqual(lead.DerivedFrom, "Box (Part Studio 1)")
        self.doc.getObject("BoxBox").Length = 15
        self.doc.recompute()
        self.assertTrue(lead.isValid(), lead.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 1500, places=6)
        sameBox(self, body.Shape.BoundBox, box.Shape.BoundBox)

    def testUndoRemovesItInOneStep(self):
        """Made in one transaction: one undo removes the Derived feature, its Body and its binder;
        redo brings them back, 1000 mm^3."""
        self.doc.UndoMode = 1
        before = sorted(o.Name for o in self.doc.Objects)
        self.doc.openTransaction("Derived")
        lead = self.derive(self.box)
        self.doc.commitTransaction()
        name = lead.Name
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertEqual(self.studio2.Group, [])
        self.doc.redo()
        self.doc.recompute()
        lead = self.doc.getObject(name)
        self.assertIsNotNone(lead)
        self.assertAlmostEqual(self.bodyOf(lead).Shape.Volume, 1000, places=6)

    def testSeveralPartsAreOneFeature(self):
        """The box and the bar in one Derived: two Bodies, two members; the lead is the last one
        made (the bar's), "Derived 1", the other labelled by its source and listed before the
        lead in the studio's history; 1000 and 3000 mm^3. The next Derived is "Derived 2"."""
        lead = self.derive(self.box, self.bar)
        members = PartDesign.derivedMembers(lead)
        self.assertEqual(len(members), 2)
        self.assertIs(members[-1], lead)
        other = members[0]
        self.assertEqual(lead.Label, "Derived 1")
        self.assertEqual(other.Label, "Derived 1 (Box)")
        self.assertIs(PartDesign.derivedLead(other), lead)
        self.assertIs(PartDesign.derivedSource(other), self.box)
        self.assertIs(PartDesign.derivedSource(lead), self.bar)
        sequence = PartDesign.studioSequence(self.studio2)
        self.assertLess(sequence.index(other), sequence.index(lead))
        self.assertAlmostEqual(self.bodyOf(other).Shape.Volume, 1000, places=6)
        self.assertAlmostEqual(self.bodyOf(lead).Shape.Volume, 3000, places=6)
        second = self.derive(self.box)
        self.assertEqual(second.Label, "Derived 2")

    def testAMissingSourceFailsNamingIt(self):
        """The source Body deleted: the derived part's feature fails "Missing source part: Box
        (Part Studio 1)", never left silently as it was (its binder keeps the last shape)."""
        lead = self.derive(self.box)
        self.box.removeObject(self.boxFeature)
        self.doc.removeObject(self.boxFeature.Name)
        self.doc.removeObject(self.box.Name)
        self.doc.recompute()
        self.assertFalse(lead.isValid())
        self.assertIn("Missing source part: Box (Part Studio 1)", lead.getStatusString())
        self.assertIsNone(PartDesign.derivedSource(lead))

    def testASourceLeftWithNoSolidFails(self):
        """The source's box deleted (the Body stays, with no solid): the same failure."""
        lead = self.derive(self.box)
        self.box.removeObject(self.boxFeature)
        self.doc.removeObject(self.boxFeature.Name)
        self.doc.recompute()
        self.assertFalse(lead.isValid())
        self.assertIn("Missing source part: Box (Part Studio 1)", lead.getStatusString())

    def testTheSourcesNewLabelIsNamed(self):
        """The source renamed: the member names it by its new label."""
        lead = self.derive(self.box)
        self.box.Label = "Cube"
        self.boxFeature.Length = 12
        self.doc.recompute()
        self.assertEqual(lead.DerivedFrom, "Cube (Part Studio 1)")

    def testAFilletOnTheDerivedPart(self):
        """A fillet r 1 on an edge of the derived part (its base feature's Edge1, 10 mm long):
        1000 - (1 - pi/4) * 10 mm^3; the source to 15 mm: still valid, the copy follows."""
        lead = self.derive(self.box)
        body = self.bodyOf(lead)
        edge = None
        for i, e in enumerate(lead.Shape.Edges):
            if abs(e.Length - 10) < 1e-6 and abs(e.BoundBox.XMin - e.BoundBox.XMax) < 1e-6:
                edge = f"Edge{i + 1}"
                break
        self.assertIsNotNone(edge)
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (lead, [edge])
        fillet.Radius = 1
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 1000 - (1 - math.pi / 4) * 10, places=4)
        self.boxFeature.Length = 15
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 1500 - (1 - math.pi / 4) * 10, places=4)

    def testEditKeepsDropsAndAddsParts(self):
        """editDerived: from [box, bar] to [box]: the lead (the bar's) goes with its Body and
        binder; the box's member becomes the lead, "Derived 1". Back to [box, bar]: two members,
        3000 mm^3 again."""
        lead = self.derive(self.box, self.bar)
        [other] = PartDesign.derivedMembers(lead)[:-1]
        leadBody = self.bodyOf(lead).Name
        binder = lead.BaseFeature.Name
        lead = PartDesign.editDerived(lead, [self.box])
        self.doc.recompute()
        self.assertIs(lead, other)
        self.assertEqual(lead.Label, "Derived 1")
        self.assertEqual(PartDesign.derivedMembers(lead), [lead])
        self.assertIsNone(self.doc.getObject(leadBody))
        self.assertIsNone(self.doc.getObject(binder))
        lead = PartDesign.editDerived(lead, [self.box, self.bar])
        self.doc.recompute()
        members = PartDesign.derivedMembers(lead)
        self.assertEqual([PartDesign.derivedSource(m) for m in members], [self.bar, self.box])
        self.assertEqual(len(self.derivedBodies()), 2)
        volumes = sorted(round(self.bodyOf(m).Shape.Volume, 6) for m in members)
        self.assertEqual(volumes, [1000, 3000])

    def testDeleteDerivedPartsLeavesNothing(self):
        """deleteDerivedParts then the lead removed (what Std_Delete does): no Body, binder or
        member is left in Part Studio 2."""
        lead = self.derive(self.box, self.bar)
        PartDesign.deleteDerivedParts(lead)
        self.assertIsNone(lead.getParentGeoFeatureGroup())
        self.doc.removeObject(lead.Name)
        self.doc.recompute()
        self.assertEqual(self.studio2.Group, [])
        self.assertFalse([o for o in self.doc.Objects if o.TypeId == "PartDesign::FeatureBase"])

    def testRefusals(self):
        """Refused before anything is written: no part; a part of the studio itself; parts of
        two studios."""
        count = len(self.doc.Objects)
        with self.assertRaises(ValueError):
            PartDesign.makeDerived(self.studio2, [])
        with self.assertRaises(ValueError):
            PartDesign.makeDerived(self.doc, [self.box])
        self.assertEqual(len(self.doc.Objects), count)
        lead = self.derive(self.box)
        studio3 = self.doc.addObject("App::Part", "Studio3")
        count = len(self.doc.Objects)
        with self.assertRaises(ValueError):
            PartDesign.makeDerived(studio3, [self.box, self.bodyOf(lead)])
        self.assertEqual(len(self.doc.Objects), count)

    def studio3(self):
        studio = self.doc.addObject("App::Part", "Studio3")
        studio.Label = "Part Studio 3"
        return studio

    def testDeriveBackIsRefused(self):
        """Review R6-1: Part Studio 2 derives Box; deriving Part Studio 2's copy back into Part
        Studio 1 is refused naming what it depends on (Onshape refuses a circular reference
        [guess]), before anything is written."""
        lead = self.derive(self.box)
        copy = self.bodyOf(lead)
        count = len(self.doc.Objects)
        with self.assertRaises(ValueError) as caught:
            PartDesign.makeDerived(self.doc, [copy])
        self.assertIn("circular reference", str(caught.exception))
        self.assertIn("Part Studio 1", str(caught.exception))
        self.assertEqual(len(self.doc.Objects), count)
        # Through a third studio as well: 3 derives 2's copy; 1 can't derive 3's
        studio3 = self.studio3()
        third = PartDesign.makeDerived(studio3, [copy])
        self.doc.recompute()
        count = len(self.doc.Objects)
        with self.assertRaises(ValueError):
            PartDesign.makeDerived(self.doc, [self.bodyOf(third)])
        self.assertEqual(len(self.doc.Objects), count)
        # A part of Part Studio 2 that reads nothing of Part Studio 1 is fine
        plate, _ = boxBody(self.doc, "Plate", 5)
        self.studio2.addObject(plate)
        self.doc.recompute()
        back = PartDesign.makeDerived(self.doc, [plate])
        self.doc.recompute()
        self.assertTrue(back.isValid(), back.getStatusString())

    def testEditCannotMakeACycle(self):
        """Review R6-1: Part Studio 2 derives Box (Derived 1); Part Studio 3 holds Z, a box whose
        length reads Part Studio 2's copy. Editing Derived 1 to bring in Z from Part Studio 3 is
        refused naming it (Z reads Part Studio 2), and Derived 1 is left as it was."""
        lead = self.derive(self.box)
        copy = self.bodyOf(lead)
        studio3 = self.studio3()
        z, zBox = boxBody(self.doc, "Z", 10)
        studio3.addObject(z)
        zBox.setExpression("Length", f"{copy.Name}.Shape.BoundBox.XLength")
        self.doc.recompute()
        self.assertAlmostEqual(z.Shape.Volume, 1000, places=6)
        names = sorted(o.Name for o in self.doc.Objects)
        with self.assertRaises(ValueError) as caught:
            PartDesign.editDerived(lead, [z])
        self.assertIn("circular reference", str(caught.exception))
        self.assertIn("Z (Part Studio 3)", str(caught.exception))
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertIs(PartDesign.derivedSource(lead), self.box)

    def testStudioPlacementDoesNotMoveTheCopy(self):
        """Review R6-2: Onshape's derived part keeps its place in its studio (the source's
        coordinates in its own studio). Here the copy keeps the source's place in the document,
        so studios placed differently are refused or fail naming both, never shift the copy
        silently: Part Studio 2 at x = 100, Derived of Box is refused; with Part Studio 2 and
        Part Studio 3 both at x = 100 the copy has the source's bounding box in its studio; Part
        Studio 2 moved again to y = 50 after the Derived: the copy fails naming both studios, and
        is right again once moved back."""
        self.studio2.Placement.Base = V(100, 0, 0)
        self.doc.recompute()
        count = len(self.doc.Objects)
        with self.assertRaises(ValueError) as caught:
            PartDesign.makeDerived(self.studio2, [self.box])
        self.assertIn("Part Studio 1 and Part Studio 2 are placed differently", str(caught.exception))
        self.assertEqual(len(self.doc.Objects), count)
        studio3 = self.studio3()
        studio3.Placement.Base = V(100, 0, 0)
        self.studio2.addObject(self.bar)
        self.doc.recompute()
        lead = PartDesign.makeDerived(studio3, [self.bar])
        self.doc.recompute()
        body = self.bodyOf(lead)
        self.assertTrue(lead.isValid(), lead.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 3000, places=6)
        sameBox(self, body.Shape.BoundBox, self.bar.Shape.BoundBox)
        studio3.Placement.Base = V(100, 50, 0)
        self.doc.recompute()
        self.assertFalse(lead.isValid())
        self.assertIn("Part Studio 2 and Part Studio 3 are placed differently", lead.getStatusString())
        studio3.Placement.Base = V(100, 0, 0)
        self.doc.recompute()
        self.assertTrue(lead.isValid(), lead.getStatusString())
        sameBox(self, body.Shape.BoundBox, self.bar.Shape.BoundBox)

    def testEditKeepsTheRowsPlace(self):
        """Review R6-4: Derived 1 of Box, then a Plate made in Part Studio 2 after it; an edit
        that brings in Bar instead (the lead's part unticked) keeps the row "Derived 1" before the
        Plate in the studio's history, also after a save and reopen."""
        lead = self.derive(self.box)
        plate, plateBox = boxBody(self.doc, "Plate", 5)
        self.studio2.addObject(plate)
        self.doc.recompute()
        sequence = PartDesign.studioSequence(self.studio2)
        self.assertLess(sequence.index(lead), sequence.index(plateBox))
        lead = PartDesign.editDerived(lead, [self.bar])
        self.doc.recompute()
        self.assertEqual(lead.Label, "Derived 1")
        self.assertIs(PartDesign.derivedSource(lead), self.bar)
        sequence = PartDesign.studioSequence(self.studio2)
        self.assertLess(sequence.index(lead), sequence.index(plateBox), [o.Name for o in sequence])
        name = lead.Name
        path = os.path.join(tempfile.mkdtemp(), "derived-edit.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        studio2 = self.doc.getObject("Studio2")
        sequence = PartDesign.studioSequence(studio2)
        self.assertLess(sequence.index(self.doc.getObject(name)), sequence.index(self.doc.getObject("PlateBox")))

    def testTheStudios(self):
        """derivedStudios lists the top level (it has parts) and Part Studio 2 once it has one;
        derivableParts the parts; studioLabel names them."""
        self.assertEqual(PartDesign.derivedStudios(self.doc), [self.doc])
        self.assertEqual(PartDesign.derivableParts(self.doc), [self.box, self.bar])
        self.assertEqual(PartDesign.studioLabel(self.doc), "Part Studio 1")
        self.assertEqual(PartDesign.studioLabel(self.studio2), "Part Studio 2")
        lead = self.derive(self.box)
        self.assertEqual(PartDesign.derivedStudios(self.doc), [self.doc, self.studio2])
        self.assertEqual(PartDesign.derivableParts(self.studio2), [self.bodyOf(lead)])
