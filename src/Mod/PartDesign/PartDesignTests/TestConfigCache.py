# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#671 C3): the cache of other configurations' shapes, which lets an instance
# outside a configured studio show a row the studio doesn't show (Onshape's configured Insert).
# Designed geometry: TestConfigurations' studio (A 10 x 10 x 10, padded 10 in Small, 20 in Large).

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests import TestConfigurations as TC
from PartDesignTests.TestConfigurations import TOL, invalid, linkHeight
from PartDesignTests.TestStudio import pad, sketch, xyPlane


def stats():
    return PartDesign.configCacheStats()


def topFace(shape):
    """The name of shape's face with the highest centre"""
    best = max(range(len(shape.Faces)), key=lambda i: shape.Faces[i].CenterOfMass.z)
    return "Face%d" % (best + 1)


class TestConfigCache(unittest.TestCase):
    setUp = TC.TestConfigurations.setUp
    tearDown = TC.TestConfigurations.tearDown
    edit = TC.TestConfigurations.edit
    configureSizes = TC.TestConfigurations.configureSizes

    def instance(self, values=None, doc=None):
        """A Link of A, in doc (default: the studio's), set to values"""
        doc = doc or self.doc
        link = doc.addObject("App::Link", "Instance")
        link.LinkedObject = self.A
        doc.recompute()
        if values:
            PartDesign.configSetInstanceKey(link, values)
            doc.recompute()
        return link

    def entry(self, link):
        obj = link.LinkedObject
        self.assertEqual(obj.TypeId, "PartDesign::ConfigShape")
        return obj

    def saveAndReopen(self, name="TestConfigurationsCache"):
        folder = tempfile.mkdtemp(prefix="cfgc")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, name + ".FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.studio = self.doc.getObject("S")
        self.A = self.doc.getObject("A")
        return path

    # ---------------------------------------------------------------- the hasher (ruling 9)
    def testEntryNamesSurviveADivergedHasher(self):
        """An entry's shape is made in a hidden copy whose string hasher then differs from the
        live document's. Saved and reopened, the entry's mapped names must be the ones it had,
        and a mapped name must still find the same face; never another face"""
        self.configureSizes()
        link = self.instance({"Size": "Large"})
        entry = self.entry(link)
        before = dict(entry.Shape.ElementMap)
        self.assertTrue(before)
        face = topFace(entry.Shape)
        mapped = entry.Shape.ElementReverseMap[face]
        top = entry.Shape.getElement(face).CenterOfMass
        # The live document's hasher diverges: new features add strings the copy never had
        extra = self.doc.addObject("PartDesign::Body", "Extra")
        sk = sketch(extra, "ExtraSketch", xyPlane(extra), (50, 0, 53, 3))
        pad(extra, "ExtraPad", sk, 4)
        self.doc.recompute()
        self.saveAndReopen()
        link = self.doc.getObject("Instance")
        entry = self.entry(link)
        self.assertFalse(invalid(link))
        self.assertEqual(dict(entry.Shape.ElementMap), before)
        name = entry.Shape.getElementName(mapped)
        self.assertTrue(name.startswith("Face"), name)
        self.assertTrue(entry.Shape.getElement(name).CenterOfMass.isEqual(top, TOL))
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)

    # ---------------------------------------------------------------- filling and staleness
    def testInstanceOnAnotherRowFillsOnce(self):
        """configSetInstanceKey + recompute fills one entry from one copy; a second recompute
        makes no copy"""
        self.configureSizes()
        copies = stats()["copies"]
        link = self.instance({"Size": "Large"})
        self.assertFalse(invalid(link))
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        self.assertEqual(stats()["copies"], copies + 1)
        entries = PartDesign.configCacheEntries(self.doc)
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0]["stale"])
        self.assertEqual(entries[0]["error"], "")
        self.doc.recompute()
        self.assertEqual(stats()["copies"], copies + 1)

    def studioEditIsLazy(self, doc):
        """A studio edit makes no pass; the entry is stale and the instance touched until the
        next recompute, which shows the edit (ruling 1)"""
        self.configureSizes()
        link = self.instance({"Size": "Large"}, doc)
        passes = stats()["passes"]
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "30 mm"))
        self.assertEqual(stats()["passes"], passes)
        self.assertTrue(PartDesign.configCacheEntries(self.doc)[0]["stale"])
        self.assertIn("Touched", link.State)
        doc.recompute()
        self.assertFalse(invalid(link))
        self.assertAlmostEqual(linkHeight(link), 30, delta=TOL)

    def testStudioEditIsLazy(self):
        self.studioEditIsLazy(self.doc)

    def testStudioEditIsLazyAcrossDocuments(self):
        folder = tempfile.mkdtemp(prefix="cfgc")
        self.addCleanup(shutil.rmtree, folder, True)
        self.doc.saveAs(os.path.join(folder, "TestConfigurationsStudio.FCStd"))
        other = App.newDocument("TestConfigurationsAssembly")
        other.saveAs(os.path.join(folder, "TestConfigurationsAssembly.FCStd"))
        self.studioEditIsLazy(other)

    def testKeySetInATransactionDefers(self):
        """A key set inside an open transaction waits for the commit, which fills it; the fill
        adds no undo step"""
        self.configureSizes()
        link = self.instance()
        undo = self.doc.UndoCount
        deferred = stats()["deferred"]
        self.doc.openTransaction("key")
        PartDesign.configSetInstanceKey(link, {"Size": "Large"})
        self.doc.recompute()
        self.assertEqual(stats()["deferred"], deferred + 1)
        self.doc.commitTransaction()
        self.assertFalse(invalid(link))
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        self.assertEqual(self.doc.UndoCount, undo + 1)

    def testFailingCellErrorsNamingTheKey(self):
        """A Large cell that fails makes the instance on Large loud, naming the key, with no
        shape; a fixed cell heals it"""
        self.configureSizes()
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "0 mm"))
        link = self.instance({"Size": "Large"})
        self.assertTrue(invalid(link))
        entries = PartDesign.configCacheEntries(self.doc)
        self.assertIn("Large", entries[0]["error"])
        self.assertTrue(entries[0]["object"].Shape.isNull())
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "25 mm"))
        self.doc.recompute()
        self.assertFalse(invalid(link))
        self.assertAlmostEqual(linkHeight(link), 25, delta=TOL)

    def testUndoShowsTheUndoneRowAfterOneRecompute(self):
        """Undo of a studio edit: the next recompute shows the undone row (it showed the edit)"""
        self.configureSizes()
        link = self.instance({"Size": "Large"})
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "30 mm"))
        self.doc.recompute()
        self.assertAlmostEqual(linkHeight(link), 30, delta=TOL)
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse(invalid(link))
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        self.doc.redo()
        self.doc.recompute()
        self.assertAlmostEqual(linkHeight(link), 30, delta=TOL)

    def testTheCacheRecordsNoStepAndKeepsRedo(self):
        """Filling an instance is derived data (ruling A, C3i): after an edit and the recompute
        that follows its commit (the step reopened for the regeneration, ops#654 10.15) the undo
        stack holds the edit's step only, an undo of it keeps Redo (the refill clears nothing) and
        the redo shows the edit again"""
        self.configureSizes()
        link = self.instance({"Size": "Large"})
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        undos = self.doc.UndoCount
        foreign = stats()["foreignWrites"]
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "30 mm"))
        self.doc.recompute()
        self.assertAlmostEqual(linkHeight(link), 30, delta=TOL)
        self.assertEqual(self.doc.UndoCount, undos + 1, self.doc.UndoNames)
        self.doc.undo()
        self.doc.recompute()
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        self.assertEqual(self.doc.RedoCount, 1, "the refill after the undo cleared Redo")
        self.assertEqual(self.doc.UndoCount, undos)
        self.doc.redo()
        self.doc.recompute()
        self.assertAlmostEqual(linkHeight(link), 30, delta=TOL)
        self.assertEqual(self.doc.UndoCount, undos + 1, self.doc.UndoNames)
        self.assertEqual(stats()["foreignWrites"], foreign, "the fill wrote what it doesn't call derived")

    def testUndoMarksStaleAndTheSaveKeepsIt(self):
        """Undo of a studio edit marks the entries stale (review 6); a save before the next
        recompute writes the stale state (ConfigStale), so the reopened entry is rebuilt"""
        self.configureSizes()
        link = self.instance({"Size": "Large"})
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "30 mm"))
        self.doc.recompute()
        self.assertAlmostEqual(linkHeight(link), 30, delta=TOL)
        self.doc.undo()
        self.assertTrue(PartDesign.configCacheEntries(self.doc)[0]["stale"])
        self.assertIn("Touched", link.State)
        self.saveAndReopen()
        link = self.doc.getObject("Instance")
        self.assertTrue(self.entry(link).ConfigStale)
        self.assertTrue(PartDesign.configCacheEntries(self.doc)[0]["stale"])
        self.doc.recompute()
        self.assertFalse(invalid(link))
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        self.assertFalse(PartDesign.configCacheEntries(self.doc)[0]["stale"])

    # ---------------------------------------------------------------- C3e: pieces, drivers, documents
    pieceBodies = TC.TestConfigurations.pieceBodies
    configuredCut = TC.TestConfigurations.configuredCut

    # C3e found, C3f fixed: App::Link answers getPropertyByName with its linked entry's property, so the
    # key was written to the entry, not the instance, and the switch read the instance as Default (loud).
    def testPieceOnlyInLargeSurvivesTheSwitchToSmall(self):
        """An instance on Large of a piece only Large makes (B's right end, 4 x 10 x 10) keeps
        showing it from an entry after the studio switches to Small"""
        self.configuredCut("Large")
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        right = [b for b in self.pieceBodies() if b.Shape.BoundBox.XMin > 25][0]
        link = self.doc.addObject("App::Link", "Instance")
        link.LinkedObject = right
        self.doc.recompute()
        PartDesign.configSetInstanceKey(link, {"Size": "Large"})
        self.doc.recompute()
        self.assertAlmostEqual(Part.getShape(link).Volume, 400, delta=1e-4)
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.doc.recompute()
        self.assertFalse(invalid(link))
        self.assertEqual(link.LinkedObject.TypeId, "PartDesign::ConfigShape")
        shape = Part.getShape(link)
        self.assertAlmostEqual(shape.Volume, 400, delta=1e-4)
        self.assertAlmostEqual(shape.BoundBox.XMin, 26, delta=TOL)

    # C3f found: with the syntax fixed, the fill's temporary copy re-opens the VarSet's document by a path
    # under the temporary folder and FreeCAD crashes (Illegal storage access). Skipped so the suite runs;
    # fixed in C3g (work\configs-c3\handoff6.md). C3h: other.recompute() runs only the VarSet; the studio's
    # recompute is the edit's, which touches the instance (ruling 1), and the one after it refreshes.
    def testCrossDocumentVarSetMarksEntriesStale(self):
        """Review 2: a VarSet in another document drives BPad by expression; its edit marks the
        studio's entries stale, the studio's recompute touches the instance (ruling 1), and the
        next recompute refreshes them"""
        folder = tempfile.mkdtemp(prefix="cfgc")
        self.addCleanup(shutil.rmtree, folder, True)
        self.configureSizes()
        self.doc.saveAs(os.path.join(folder, "TestConfigurationsStudio.FCStd"))
        other = App.newDocument("TestConfigurationsVars")
        other.saveAs(os.path.join(folder, "TestConfigurationsVars.FCStd"))
        var = other.addObject("App::VarSet", "Vars")  # not "V": the expression lexer reads volts
        var.addProperty("App::PropertyLength", "Len")
        var.Len = 10
        other.recompute()
        bpad = self.doc.getObject("BPad")
        self.edit(lambda: bpad.setExpression("Length", "TestConfigurationsVars#Vars.Len"))
        link = self.instance({"Size": "Large"})
        self.assertFalse(PartDesign.configCacheEntries(self.doc)[0]["stale"])
        var.Len = 15
        self.assertTrue(PartDesign.configCacheEntries(self.doc)[0]["stale"])
        other.recompute()
        self.doc.recompute()
        self.assertTrue(PartDesign.configCacheEntries(self.doc)[0]["stale"])
        self.assertIn("Touched", link.State)
        self.doc.recompute()
        self.assertFalse(PartDesign.configCacheEntries(self.doc)[0]["stale"])
        self.assertFalse(invalid(link))
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)

    def testStudioEditEndedByTheAssemblysRecompute(self):
        """C3h: the assembly's recompute runs the studio's edited objects (its instance on the shown
        configuration depends on them), which ends the studio edit though the studio's document
        never recomputed: the instance on an entry is touched, and the next recompute shows the edit"""
        folder = tempfile.mkdtemp(prefix="cfgc")
        self.addCleanup(shutil.rmtree, folder, True)
        self.configureSizes()
        self.doc.saveAs(os.path.join(folder, "TestConfigurationsStudio.FCStd"))
        asm = App.newDocument("TestConfigurationsAssembly")
        asm.saveAs(os.path.join(folder, "TestConfigurationsAssembly.FCStd"))
        shown = self.instance({"Size": "Small"}, asm)
        link = self.instance({"Size": "Large"}, asm)
        self.assertAlmostEqual(linkHeight(shown), 10, delta=TOL)
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        self.doc.openTransaction("edit")
        PartDesign.configSetCell(self.APad, "Length", "Small", "12 mm")
        PartDesign.configSetCell(self.APad, "Length", "Large", "30 mm")
        self.doc.commitTransaction()
        asm.recompute()
        self.assertAlmostEqual(linkHeight(shown), 12, delta=TOL)
        self.assertIn("Touched", link.State)
        asm.recompute()
        self.assertFalse(invalid(link))
        self.assertAlmostEqual(linkHeight(link), 30, delta=TOL)

    def testPartiallyLoadedStudioNeverGivesAWrongRow(self):
        """Review 3: the assembly reopened alone loads the studio partly; the saved entry shows,
        and a key change is loud or right (A 10 on Small), never the old row's 20"""
        folder = tempfile.mkdtemp(prefix="cfgc")
        self.addCleanup(shutil.rmtree, folder, True)
        self.configureSizes()
        studioPath = os.path.join(folder, "TestConfigurationsStudio.FCStd")
        self.doc.saveAs(studioPath)
        asm = App.newDocument("TestConfigurationsAssembly")
        asmPath = os.path.join(folder, "TestConfigurationsAssembly.FCStd")
        asm.saveAs(asmPath)
        link = self.instance({"Size": "Large"}, asm)
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        self.doc.save()
        asm.save()
        App.closeDocument(asm.Name)
        App.closeDocument(self.doc.Name)
        asm = App.openDocument(asmPath)
        studio = App.getDocument("TestConfigurationsStudio")
        self.assertTrue(studio.Partial)
        link = asm.getObject("Instance")
        self.assertFalse(invalid(link))
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        try:
            PartDesign.configSetInstanceKey(link, {"Size": "Small"})
            asm.recompute()
        except Exception:
            return  # loud
        self.assertTrue(invalid(link) or abs(linkHeight(link) - 10) < TOL,
                        "a partly loaded studio showed the old row")

    # C3e found, C3f fixed: a Link at a document studio's root counted as inside the studio, so its key
    # was never read and it silently stayed on the shown row (Onshape inserts any row).
    def testTopLevelStudioEntryIsNotTheStudios(self):
        """Review 10: a configured studio that is the document itself; its entry (at the document
        root) is not read as one of its objects: the write marks nothing stale and the next
        recompute makes no copy"""
        doc = App.newDocument("TestConfigurationsTop")
        body = doc.addObject("PartDesign::Body", "T")
        tpad = pad(body, "TPad", sketch(body, "TSketch", xyPlane(body), (0, 0, 10, 10)), 10)
        doc.recompute()
        size = PartDesign.configAddList(doc, "Size", ["Small", "Large"])
        PartDesign.configConfigure(tpad, "Length", size)
        PartDesign.configSetCell(tpad, "Length", "Large", "20 mm")
        doc.recompute()
        link = doc.addObject("App::Link", "Instance")
        link.LinkedObject = body
        doc.recompute()
        PartDesign.configSetInstanceKey(link, {"Size": "Large"})
        doc.recompute()
        entries = PartDesign.configCacheEntries(doc)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["studio"], "")
        self.assertFalse(entries[0]["stale"])
        self.assertAlmostEqual(linkHeight(link), 20, delta=TOL)
        self.assertAlmostEqual(body.Shape.BoundBox.ZLength, 10, delta=TOL)
        copies = stats()["copies"]
        doc.recompute()
        self.assertEqual(stats()["copies"], copies)
        self.assertFalse(PartDesign.configCacheEntries(doc)[0]["stale"])
        self.assertNotIn("Touched", link.State)

    def testAssemblyJointFollowsAKeyChange(self):
        """A lid fixed by an Assembly joint to the instance's top face rises by 10 when the
        instance goes from Small (A 10) to Large (A 20): the joint's face is found in the entry"""
        try:
            import JointObject
        except ImportError as e:
            self.skipTest("Assembly not importable: %s" % e)
        self.configureSizes()
        asm = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        joints = asm.newObject("Assembly::JointGroup", "Joints")
        inst = asm.newObject("App::Link", "Instance")
        inst.LinkedObject = self.A
        lid = asm.newObject("Part::Box", "Lid")
        lid.Length = lid.Width = 10
        lid.Height = 1
        self.doc.recompute()
        ground = joints.newObject("App::FeaturePython", "GroundedJoint")
        JointObject.GroundedJoint(ground, inst)
        shape = Part.getShape(inst)
        top = topFace(shape)
        face = shape.getElement(top)
        corner = min(range(len(shape.Vertexes)), key=lambda i: (
            not face.isInside(shape.Vertexes[i].Point, TOL, True), shape.Vertexes[i].Point.x
            + shape.Vertexes[i].Point.y))
        joint = joints.newObject("App::FeaturePython", "Fixed")
        JointObject.Joint(joint, 0)
        joint.Proxy.setJointConnectors(
            joint, [[lid, ["Face5", "Vertex1"]], [inst, [top, "Vertex%d" % (corner + 1)]]])
        self.assertEqual(asm.solve(), 0)
        small = lid.Placement.Base.z
        PartDesign.configSetInstanceKey(inst, {"Size": "Large"})
        self.doc.recompute()
        self.assertAlmostEqual(linkHeight(inst), 20, delta=TOL)
        self.assertEqual(asm.solve(), 0)
        self.assertAlmostEqual(lid.Placement.Base.z - small, 10, delta=1e-6)

    def testJointReferenceRetargetsUnrecorded(self):
        """The key change of an instance a joint references, in a user's step: the retarget
        rewrites the joint's reference as derived data (ruling A, coordinator c752): no warned
        write, no undo step beside the user's, and the lid follows (Small 10 -> Large 20)"""
        try:
            import JointObject
        except ImportError as e:
            self.skipTest("Assembly not importable: %s" % e)
        self.configureSizes()
        asm = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        joints = asm.newObject("Assembly::JointGroup", "Joints")
        inst = asm.newObject("App::Link", "Instance")
        inst.LinkedObject = self.A
        lid = asm.newObject("Part::Box", "Lid")
        lid.Length = lid.Width = 10
        lid.Height = 1
        self.doc.recompute()
        ground = joints.newObject("App::FeaturePython", "GroundedJoint")
        JointObject.GroundedJoint(ground, inst)
        shape = Part.getShape(inst)
        top = topFace(shape)
        face = shape.getElement(top)
        corner = min(range(len(shape.Vertexes)), key=lambda i: (
            not face.isInside(shape.Vertexes[i].Point, TOL, True), shape.Vertexes[i].Point.x
            + shape.Vertexes[i].Point.y))
        joint = joints.newObject("App::FeaturePython", "Fixed")
        JointObject.Joint(joint, 0)
        joint.Proxy.setJointConnectors(
            joint, [[lid, ["Face5", "Vertex1"]], [inst, [top, "Vertex%d" % (corner + 1)]]])
        self.assertEqual(asm.solve(), 0)
        small = lid.Placement.Base.z
        undos = self.doc.UndoCount
        foreign = stats()["foreignWrites"]
        self.edit(lambda: PartDesign.configSetInstanceKey(inst, {"Size": "Large"}))
        self.doc.recompute()
        self.assertEqual(inst.LinkedObject.TypeId, "PartDesign::ConfigShape")
        self.assertEqual(stats()["foreignWrites"], foreign, "the retarget warned")
        self.assertEqual(self.doc.UndoCount, undos + 1, self.doc.UndoNames)
        self.assertEqual(asm.solve(), 0)
        self.assertAlmostEqual(lid.Placement.Base.z - small, 10, delta=1e-6)

if __name__ == "__main__":
    unittest.main()
