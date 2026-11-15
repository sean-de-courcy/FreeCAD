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

"""A document never gives a deleted object's ID again (FreeCAD-CH ops#657).

Element names carry the IDs of the objects that made them, so an ID given twice lets a reference
to a deleted object's geometry match the geometry of a later, unrelated object. Before ops#657 a
reopened document numbered on from the highest *loaded* ID: delete the newest features, save,
reopen and model on, and a red reference turned green on the new geometry with no warning.
Onshape keeps a reference to deleted geometry broken. The document now saves the highest ID it
ever gave (`LastObjectId` on `<Document>`) and takes the larger of it and the loaded IDs.

- testDeletedPocketFloorStaysBroken: a datum plane on a pocket's floor (z 7); the pocket and its
  sketch, the newest objects, are deleted (the datum goes Invalid); save, reopen, and a new
  pocket whose floor is at z 4. The new objects get fresh IDs and the datum stays broken at z 7.
  (With `LastObjectId` taken out of the file it re-binds to z 4, Up-to-date: the bug.)
- testSavedHighWater: the file carries the highest ID ever given, deleted objects included, and
  a reopened document gives IDs above it.
- testUndoDelete, testUndoAdd: undo gives an object back its own ID, and no other object takes
  that ID, before or after redo.
- testMerge: a merge (`Document.mergeProject`, `importObjects`) gives the merged objects IDs
  above the target's high-water mark, deleted IDs included, and the mark survives a save.
"""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part
import Sketcher

__all__ = ["TestObjectIdReuse"]


def _rect(body, name, x0, y0, x1, y1, z):
    """A closed rectangle sketch on the body's XY plane, offset to height z."""
    sk = body.newObject("Sketcher::SketchObject", name)
    xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
    sk.AttachmentSupport = [(xy, "")]
    sk.MapMode = "FlatFace"
    sk.AttachmentOffset = App.Placement(App.Vector(0, 0, z), App.Rotation())
    p = [App.Vector(x0, y0, 0), App.Vector(x1, y0, 0), App.Vector(x1, y1, 0), App.Vector(x0, y1, 0)]
    for i in range(4):
        sk.addGeometry(Part.LineSegment(p[i], p[(i + 1) % 4]))
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    return sk


def _floorAt(shape, z):
    """The name of the small horizontal face at height z (a pocket floor), or None."""
    for i, f in enumerate(shape.Faces):
        bb = f.BoundBox
        if abs(bb.ZMin - z) < 1e-6 and abs(bb.ZMax - z) < 1e-6 and f.Area < 99:
            return "Face%d" % (i + 1)
    return None


def _savedLastObjectId(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("Document.xml").decode("utf-8")
    m = re.search(r'<Document [^>]*\bLastObjectId="(\d+)"', xml)
    return int(m.group(1)) if m else None


class TestObjectIdReuse(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="i657_")
        self.docs = []

    def tearDown(self):
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _new(self, name):
        doc = App.newDocument(name)
        self.docs.append(doc.Name)
        return doc

    def _reopen(self, doc):
        path = os.path.join(self.dir, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        self.docs.append(doc.Name)
        return doc, path

    def testDeletedPocketFloorStaysBroken(self):
        doc = self._new("i657pocket")
        body = doc.addObject("PartDesign::Body", "Body")
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = _rect(body, "PadSketch", 0, 0, 10, 10, 0)
        pad.Length = 10
        ref = doc.addObject("Part::Plane", "RefP")
        ref.Length = ref.Width = 1
        doc.recompute()
        sk1 = _rect(body, "PocketSketch", 5, 2, 8, 8, 10)
        p1 = body.newObject("PartDesign::Pocket", "Pocket")
        p1.Profile = sk1
        p1.Length = 3
        doc.recompute()
        floor = _floorAt(body.Shape, 7)
        self.assertIsNotNone(floor)
        ref.AttachmentSupport = [(body, floor)]
        ref.MapMode = "FlatFace"
        doc.recompute()
        self.assertAlmostEqual(ref.Placement.Base.z, 7)
        deleted = {sk1.ID, p1.ID}

        body.removeObject(p1)
        doc.removeObject(p1.Name)
        body.removeObject(sk1)
        doc.removeObject(sk1.Name)
        doc.recompute()
        self.assertIn("Invalid", ref.State)  # loud while the session lasts

        doc, _ = self._reopen(doc)
        body, ref = doc.getObject("Body"), doc.getObject("RefP")
        self.assertIn("Invalid", ref.State)
        sk2 = _rect(body, "PocketSketch2", 1, 2, 4, 8, 10)
        p2 = body.newObject("PartDesign::Pocket", "Pocket2")
        p2.Profile = sk2
        p2.Length = 6
        doc.recompute()
        self.assertIsNotNone(_floorAt(body.Shape, 4))
        self.assertFalse({sk2.ID, p2.ID} & deleted, "a deleted object's ID was given again")

        ref.touch()
        doc.recompute()
        self.assertIn("Invalid", ref.State, "the reference to the deleted floor re-bound")
        self.assertNotAlmostEqual(ref.Placement.Base.z, 4)
        subs = [s for _, ss in ref.AttachmentSupport for s in ss]
        self.assertTrue(subs and all(s.startswith("?") for s in subs), subs)

    def testSavedHighWater(self):
        doc = self._new("i657mark")
        objs = [doc.addObject("App::FeatureTest", "F%d" % i) for i in range(4)]
        given = max(o.ID for o in objs)
        kept = sorted(o.ID for o in objs[:2])
        doc.removeObject(objs[-1].Name)
        doc.removeObject(objs[-2].Name)
        doc, path = self._reopen(doc)
        self.assertEqual(_savedLastObjectId(path), given)
        self.assertEqual(sorted(o.ID for o in doc.Objects), kept)
        fresh = doc.addObject("App::FeatureTest", "G").ID
        self.assertGreater(fresh, given)
        # A second round: the mark only grows
        doc.removeObject("G")
        doc, path = self._reopen(doc)
        self.assertEqual(_savedLastObjectId(path), fresh)
        self.assertGreater(doc.addObject("App::FeatureTest", "H").ID, fresh)

    def testUndoDelete(self):
        doc = self._new("i657undodel")
        doc.UndoMode = 1
        doc.openTransaction("add")
        aid = doc.addObject("App::FeatureTest", "A").ID
        bid = doc.addObject("App::FeatureTest", "B").ID
        doc.commitTransaction()
        doc.openTransaction("delete")
        doc.removeObject("B")
        doc.commitTransaction()
        cid = doc.addObject("App::FeatureTest", "C").ID
        self.assertNotEqual(cid, bid)
        doc.undo()  # B is back with its own ID
        self.assertEqual(doc.getObject("B").ID, bid)
        ids = [o.ID for o in doc.Objects]
        self.assertEqual(len(ids), len(set(ids)), ids)
        did = doc.addObject("App::FeatureTest", "D").ID
        self.assertNotIn(did, [aid, bid, cid])
        doc, _ = self._reopen(doc)
        self.assertGreater(doc.addObject("App::FeatureTest", "E").ID, max(bid, cid, did))

    def testUndoAdd(self):
        doc = self._new("i657undoadd")
        doc.UndoMode = 1
        doc.addObject("App::FeatureTest", "A")
        doc.openTransaction("add")
        bid = doc.addObject("App::FeatureTest", "B").ID
        doc.commitTransaction()
        doc.undo()  # B is gone
        self.assertIsNone(doc.getObject("B"))
        cid = doc.addObject("App::FeatureTest", "C").ID
        self.assertNotEqual(cid, bid)
        doc.redo()  # B is back with its own ID, still unique
        self.assertEqual(doc.getObject("B").ID, bid)
        ids = [o.ID for o in doc.Objects]
        self.assertEqual(len(ids), len(set(ids)), ids)
        # B undone again and the document reopened: its ID stays used
        doc.undo()
        doc, _ = self._reopen(doc)
        self.assertGreater(doc.addObject("App::FeatureTest", "D").ID, max(bid, cid))

    def testMerge(self):
        src = self._new("i657src")
        for i in range(3):
            src.addObject("App::FeatureTest", "S%d" % i)
        srcPath = os.path.join(self.dir, "i657src.FCStd")
        src.saveAs(srcPath)

        doc = self._new("i657dst")
        objs = [doc.addObject("App::FeatureTest", "T%d" % i) for i in range(3)]
        mark = max(o.ID for o in objs)
        doc.removeObject(objs[-1].Name)  # its ID stays used
        doc, _ = self._reopen(doc)
        before = {o.Name for o in doc.Objects}
        doc.mergeProject(srcPath)
        merged = [o for o in doc.Objects if o.Name not in before]
        self.assertEqual(len(merged), 3)
        self.assertTrue(all(o.ID > mark for o in merged), [o.ID for o in merged])
        ids = [o.ID for o in doc.Objects]
        self.assertEqual(len(ids), len(set(ids)), ids)
        top = max(ids)
        doc, path = self._reopen(doc)
        self.assertGreaterEqual(_savedLastObjectId(path), top)
        self.assertGreater(doc.addObject("App::FeatureTest", "N").ID, top)


if __name__ == "__main__":
    unittest.main()
