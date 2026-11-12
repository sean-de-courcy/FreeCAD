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

if __name__ == "__main__":
    unittest.main()
