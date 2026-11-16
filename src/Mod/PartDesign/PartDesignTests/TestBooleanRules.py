# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, the Onshape experiment, ranks 3b and 28)

"""Onshape's Boolean results (ops#640 rank 3b; hands-on B3-3a and A-2') and Keep tools (rank 28,
A-5), in the App.

- A Union fuses the tools that touch its part, directly or through another tool it fuses; a tool
  apart from all of that is left as it was (SeparateTools) and stays a part. A Union that changes
  nothing is healthy, with Onshape's info "Boolean resulted in no geometry change. The parts
  either do not intersect or are totally contained."
- A Subtract whose tools miss the target is healthy, the target unchanged, with the info
  "Selected tools and targets do not intersect."; the tools are consumed.
- An Intersect with no overlap leaves nothing (an empty shape, no message), and consumes both
  parts; with Keep tools the part stays as it was.
- PartDesign.consumerOf(body) names the Boolean that consumes a part (Keep tools off, the
  Boolean in effect: not a Merge, not suppressed, not after its part's bar).
- KeepTools is a new property: a new Boolean takes the user parameter BooleanKeepTools (the
  dialog's last accepted value), a restored one reads its own (old files: false).

Designed geometry: the part Target, a 10 mm box at the origin (1000), and tool parts, 10 mm boxes
moved along X. Oracles are volumes and solid counts."""

import os
import re
import tempfile
import unittest
import zipfile

import FreeCAD as App
import PartDesign

V = App.Vector

PARAM = "User parameter:BaseApp/Preferences/Mod/PartDesign"
NO_CHANGE = "Boolean resulted in no geometry change."
NO_INTERSECTION = "Selected tools and targets do not intersect."


class TestBooleanRules(unittest.TestCase):
    def setUp(self):
        self.param = App.ParamGet(PARAM)
        self.savedKeep = self.param.GetBool("BooleanKeepTools", False)
        self.param.SetBool("BooleanKeepTools", False)
        self.doc = App.newDocument("TestBooleanRules")
        self.target, self.box = self.part("Target", 0)

    def tearDown(self):
        self.param.SetBool("BooleanKeepTools", self.savedKeep)
        App.closeDocument(self.doc.Name)

    def part(self, name, x, size=10, y=0, z=0):
        """A part: a Body with one box of edge `size` at (x, y, z)."""
        body = self.doc.addObject("PartDesign::Body", name)
        box = body.newObject("PartDesign::AdditiveBox", name + "Box")
        box.Length = box.Width = box.Height = size
        box.Placement.Base = V(x, y, z)
        return body, box

    def boolean(self, kind, tools):
        boolean = self.target.newObject("PartDesign::Boolean", kind)
        boolean.setObjects(tools)
        boolean.Type = kind
        self.doc.recompute()
        self.assertTrue(boolean.isValid(), boolean.getStatusString())
        return boolean

    def assertNoteIs(self, boolean, note):
        status = boolean.getStatusString()
        for text in (NO_CHANGE, NO_INTERSECTION):
            if text == note:
                self.assertIn(text, status)
            else:
                self.assertNotIn(text, status)

    # -- Union ------------------------------------------------------------------------------------

    def testAUnionOfPartsApartKeepsThemSeparate(self):
        """A-2' b: Target and a tool 10 away: the Union is healthy, with the no-change info;
        Target stays 1000 and one solid, the tool is left separate and stays a part (1000)."""
        tool, _ = self.part("Tool", 20)
        fuse = self.boolean("Fuse", [tool])
        self.assertNoteIs(fuse, NO_CHANGE)
        self.assertAlmostEqual(self.target.Shape.Volume, 1000, places=6)
        self.assertEqual(len(self.target.Shape.Solids), 1)
        self.assertEqual(fuse.SeparateTools, [tool])
        self.assertIsNone(PartDesign.consumerOf(tool))
        self.assertAlmostEqual(tool.Shape.Volume, 1000, places=6)
        # SeparateTools is written during the compute, as an output: the Boolean is left clean
        self.assertNotIn("Touched", fuse.State)
        self.doc.recompute()
        self.assertNotIn("Touched", fuse.State)
        self.assertEqual(fuse.SeparateTools, [tool])

    def testAUnionFusesWhatTouchesThroughAnotherTool(self):
        """Tools A (x 5..15, overlaps Target), C (x 14..24, overlaps A only) and D (x 40..50,
        apart): A and C are fused, x 0..24, 2400, one solid, no info; D stays a part; A and C
        are consumed."""
        a, _ = self.part("A", 5)
        c, _ = self.part("C", 14)
        d, _ = self.part("D", 40)
        fuse = self.boolean("Fuse", [d, c, a])
        self.assertNoteIs(fuse, None)
        self.assertAlmostEqual(self.target.Shape.Volume, 2400, places=6)
        self.assertEqual(len(self.target.Shape.Solids), 1)
        self.assertEqual(fuse.SeparateTools, [d])
        self.assertIs(PartDesign.consumerOf(a), fuse)
        self.assertIs(PartDesign.consumerOf(c), fuse)
        self.assertIsNone(PartDesign.consumerOf(d))

    def testAUnionSharingAFaceFuses(self):
        """A tool at x 10..20, sharing Target's face: fused, 2000, one solid, no info."""
        tool, _ = self.part("Tool", 10)
        fuse = self.boolean("Fuse", [tool])
        self.assertNoteIs(fuse, None)
        self.assertAlmostEqual(self.target.Shape.Volume, 2000, places=6)
        self.assertEqual(len(self.target.Shape.Solids), 1)
        self.assertEqual(fuse.SeparateTools, [])
        self.assertIs(PartDesign.consumerOf(tool), fuse)

    def testAUnionOfAContainedToolNotes(self):
        """A 2 mm box at (4, 4, 4), inside Target: fused (consumed), Target 1000, the no-change
        info ("totally contained")."""
        tool, _ = self.part("Tool", 4, size=2, y=4, z=4)
        fuse = self.boolean("Fuse", [tool])
        self.assertNoteIs(fuse, NO_CHANGE)
        self.assertAlmostEqual(self.target.Shape.Volume, 1000, places=6)
        self.assertEqual(fuse.SeparateTools, [])
        self.assertIs(PartDesign.consumerOf(tool), fuse)

    def testAUnionThatMovesApartLeavesTheToolAgain(self):
        """The tool fused at x 5 (1500), moved to x 30: left separate, Target 1000; back at 5:
        fused again (SeparateTools follows each compute)."""
        tool, toolBox = self.part("Tool", 5)
        fuse = self.boolean("Fuse", [tool])
        self.assertAlmostEqual(self.target.Shape.Volume, 1500, places=6)
        toolBox.Placement.Base = V(30, 0, 0)
        self.doc.recompute()
        self.assertEqual(fuse.SeparateTools, [tool])
        self.assertAlmostEqual(self.target.Shape.Volume, 1000, places=6)
        toolBox.Placement.Base = V(5, 0, 0)
        self.doc.recompute()
        self.assertEqual(fuse.SeparateTools, [])
        self.assertAlmostEqual(self.target.Shape.Volume, 1500, places=6)

    # -- Subtract ---------------------------------------------------------------------------------

    def testASubtractThatMissesNotesAndConsumes(self):
        """B3-3a: a tool 10 away: healthy, Target 1000, the info "Selected tools and targets do
        not intersect."; the tool is consumed (Keep tools off)."""
        tool, _ = self.part("Tool", 20)
        cut = self.boolean("Cut", [tool])
        self.assertNoteIs(cut, NO_INTERSECTION)
        self.assertAlmostEqual(self.target.Shape.Volume, 1000, places=6)
        self.assertIs(PartDesign.consumerOf(tool), cut)

    def testASubtractSharingOnlyAFaceNotes(self):
        """A tool at x 10..20, only sharing a face: nothing removed, the same info."""
        tool, _ = self.part("Tool", 10)
        cut = self.boolean("Cut", [tool])
        self.assertNoteIs(cut, NO_INTERSECTION)
        self.assertAlmostEqual(self.target.Shape.Volume, 1000, places=6)

    def testASubtractThatCutsHasNoNote(self):
        """A tool at x 5: Target 500, no info."""
        tool, _ = self.part("Tool", 5)
        cut = self.boolean("Cut", [tool])
        self.assertNoteIs(cut, None)
        self.assertAlmostEqual(self.target.Shape.Volume, 500, places=6)

    # -- Intersect --------------------------------------------------------------------------------

    def testAnIntersectWithNoOverlapLeavesNothing(self):
        """A-2' c: a tool 10 away, Keep tools off: healthy, no info, Target has no solid left;
        the tool is consumed too."""
        tool, _ = self.part("Tool", 20)
        common = self.boolean("Common", [tool])
        self.assertNoteIs(common, None)
        self.assertEqual(len(self.target.Shape.Solids), 0)
        self.assertAlmostEqual(self.target.Shape.Volume, 0, places=6)
        self.assertIs(PartDesign.consumerOf(tool), common)

    def testAnIntersectWithNoOverlapAndKeepToolsKeepsBoth(self):
        """A-2' c with Keep tools: Target stays 1000, the tool is not consumed."""
        tool, _ = self.part("Tool", 20)
        common = self.target.newObject("PartDesign::Boolean", "Common")
        common.setObjects([tool])
        common.Type = "Common"
        common.KeepTools = True
        self.doc.recompute()
        self.assertTrue(common.isValid(), common.getStatusString())
        self.assertAlmostEqual(self.target.Shape.Volume, 1000, places=6)
        self.assertIsNone(PartDesign.consumerOf(tool))

    def testAnIntersectSharingOnlyAFaceLeavesNothing(self):
        """A tool at x 10..20, only sharing a face with Target: no volume in common, so as A-2' c,
        healthy (not 'Boolean operation failed'), no info, no solid left, the tool consumed."""
        tool, _ = self.part("Tool", 10)
        common = self.boolean("Common", [tool])
        self.assertNoteIs(common, None)
        self.assertEqual(len(self.target.Shape.Solids), 0)
        self.assertAlmostEqual(self.target.Shape.Volume, 0, places=6)
        self.assertIs(PartDesign.consumerOf(tool), common)

    def testAnIntersectSharingOnlyAnEdgeLeavesNothing(self):
        """A tool at (10, 10, 0), touching Target along one edge only: the same, nothing left."""
        tool, _ = self.part("Tool", 10, y=10)
        common = self.boolean("Common", [tool])
        self.assertEqual(len(self.target.Shape.Solids), 0)
        self.assertIs(PartDesign.consumerOf(tool), common)

    def testAnIntersectThatOverlaps(self):
        """A tool at x 5: Target 500, the tool consumed."""
        tool, _ = self.part("Tool", 5)
        common = self.boolean("Common", [tool])
        self.assertAlmostEqual(self.target.Shape.Volume, 500, places=6)
        self.assertIs(PartDesign.consumerOf(tool), common)

    # -- consumerOf -------------------------------------------------------------------------------

    def testKeepToolsKeepsTheToolAPart(self):
        """A Subtract at x 5 (500) with Keep tools: the tool isn't consumed; Keep tools off
        again: consumed; the geometry is the same both ways."""
        tool, _ = self.part("Tool", 5)
        cut = self.boolean("Cut", [tool])
        cut.KeepTools = True
        self.doc.recompute()
        self.assertIsNone(PartDesign.consumerOf(tool))
        self.assertAlmostEqual(self.target.Shape.Volume, 500, places=6)
        cut.KeepTools = False
        self.doc.recompute()
        self.assertIs(PartDesign.consumerOf(tool), cut)

    def testABooleanAfterTheBarOrSuppressedConsumesNothing(self):
        """Rolled back before the Boolean, or the Boolean suppressed: its tool is a part."""
        tool, _ = self.part("Tool", 5)
        cut = self.boolean("Cut", [tool])
        self.target.rollTo(self.box)
        self.doc.recompute()
        self.assertIsNone(PartDesign.consumerOf(tool))
        self.target.rollToEnd()
        self.doc.recompute()
        self.assertIs(PartDesign.consumerOf(tool), cut)
        cut.Suppressed = True
        self.doc.recompute()
        self.assertIsNone(PartDesign.consumerOf(tool))

    def testAMergeIsNoConsumer(self):
        """A Merge has its own rule (MergedInto): consumerOf names no Merge."""
        tool, _ = self.part("Tool", 5)
        self.doc.recompute()
        merge = PartDesign.makeMerge(self.target, [tool])
        self.doc.recompute()
        self.assertTrue(merge.isValid(), merge.getStatusString())
        self.assertIsNone(PartDesign.consumerOf(tool))

    def testTheFirstFeatureBooleanIsUnchanged(self):
        """A Boolean as the first feature of an empty Body, with one tool, takes the tool's shape
        (no tools left to fuse): no info."""
        tool, _ = self.part("Tool", 20)
        body = self.doc.addObject("PartDesign::Body", "Empty")
        fuse = body.newObject("PartDesign::Boolean", "Fuse")
        fuse.setObjects([tool])
        self.doc.recompute()
        self.assertTrue(fuse.isValid(), fuse.getStatusString())
        self.assertNotIn(NO_CHANGE, fuse.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 1000, places=6)

    # -- KeepTools ----------------------------------------------------------------------------------

    def testKeepToolsDefaultsToTheParameter(self):
        """A-5: a new Boolean takes BooleanKeepTools (the dialog's last accepted value); saved off
        with the parameter on, it reads off again."""
        self.assertFalse(self.target.newObject("PartDesign::Boolean", "Off").KeepTools)
        self.param.SetBool("BooleanKeepTools", True)
        on = self.target.newObject("PartDesign::Boolean", "On")
        self.assertTrue(on.KeepTools)
        on.KeepTools = False
        name = on.Name
        path = os.path.join(tempfile.mkdtemp(), "keep.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.assertFalse(self.doc.getObject(name).KeepTools)

    def testAFileSavedWithoutKeepToolsReadsOff(self):
        """The ledger row: a Boolean saved before KeepTools existed (the property taken out of the
        saved Document.xml here) reads Keep tools off even with the parameter on, so its tool is
        consumed and leaves the Parts list; the geometry is the same (500)."""
        tool, _ = self.part("Tool", 5)
        cut = self.boolean("Cut", [tool])
        name, toolName = cut.Name, tool.Name
        path = os.path.join(tempfile.mkdtemp(), "old.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        withoutProperty(path, name, "KeepTools")
        self.param.SetBool("BooleanKeepTools", True)
        self.doc = App.openDocument(path)
        cut = self.doc.getObject(name)
        self.assertFalse(cut.KeepTools)
        self.doc.recompute()
        self.assertTrue(cut.isValid(), cut.getStatusString())
        self.assertIs(PartDesign.consumerOf(self.doc.getObject(toolName)), cut)
        self.assertAlmostEqual(self.doc.getObject("Target").Shape.Volume, 500, places=6)


def withoutProperty(path, objectName, propertyName):
    """Takes propertyName out of objectName's saved data in the FCStd at path, as a file written
    before the property existed has it; Document.xml stays the archive's first entry."""
    with zipfile.ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    rewritten = []
    for info, data in entries:
        if info.filename == "Document.xml":
            xml = data.decode("utf-8")
            start = xml.index(f'<Object name="{objectName}"', xml.index("<ObjectData"))
            end = xml.index("</Object>", start)
            block, count = re.subn(
                rf'\s*<Property name="{propertyName}"[^>]*>.*?</Property>',
                "",
                xml[start:end],
                count=1,
                flags=re.S,
            )
            assert count == 1, f"{propertyName} not saved for {objectName}"
            block, count = re.subn(
                r'<Properties Count="(\d+)"',
                lambda m: f'<Properties Count="{int(m.group(1)) - 1}"',
                block,
                count=1,
            )
            assert count == 1, f"no property count for {objectName}"
            data = (xml[:start] + block + xml[end:]).encode("utf-8")
        rewritten.append((info, data))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for info, data in rewritten:
            archive.writestr(info.filename, data)


if __name__ == "__main__":
    unittest.main()
