# SPDX-License-Identifier: LGPL-2.1-or-later

"""Element references across documents, refreshed when documents are opened."""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part  # noqa: F401  (loads the Part feature types)


def _box(doc, name, x):
    box = doc.addObject("Part::Box", name)
    box.Placement.Base = App.Vector(x, 0, 0)
    return box


def _faceAtX(shape, x):
    """Return the name of the face lying on the plane at x and facing -x."""
    for i, face in enumerate(shape.Faces, 1):
        if abs(face.CenterOfMass.x - x) < 1e-7 and face.normalAt(0, 0).x < -0.5:
            return "Face%d" % i
    return None


class ElementReferenceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ElementReferenceTest")
        self.docNames = []

    def tearDown(self):
        for name in self.docNames:
            if name in App.listDocuments():
                App.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _newDocument(self, name):
        doc = App.newDocument(name)
        self.docNames.append(doc.Name)
        doc.saveAs(os.path.join(self.dir, name + ".FCStd"))
        return doc

    def _path(self, name):
        return os.path.join(self.dir, name + ".FCStd")

    def _newTarget(self):
        """Document B: a compound of Box1 (x = 0) and Box2 (x = 20), saved."""
        docB = self._newDocument("ElementRefB")
        box1 = _box(docB, "Box1", 0)
        box2 = _box(docB, "Box2", 20)
        compound = docB.addObject("Part::Compound", "Compound")
        compound.Links = [box1, box2]
        docB.recompute()
        docB.save()
        return docB, compound

    def _newOwner(self, target, subs, propType="App::PropertyXLinkSub"):
        """Document A: an object whose property Target references `subs` of `target`, saved."""
        docA = self._newDocument("ElementRefA")
        ref = docA.addObject("App::FeaturePython", "Ref")
        ref.addProperty(propType, "Target")
        ref.Target = (target, subs)
        docA.recompute()
        docA.save()
        return docA

    @staticmethod
    def _moveFaces(docB):
        """Put a box at x = -20 first in B's compound: every face gets a new index, while its
        mapped name stays the same. Saves B."""
        compound = docB.getObject("Compound")
        compound.Links = [_box(docB, "Box0", -20)] + compound.Links
        docB.recompute()
        docB.save()

    def _prepareMovedCopy(self, docB):
        """Save B with its faces moved as a separate file, and leave B open as it was.

        The copy has the same objects, and so the same mapped names, as B. Returns B, opened
        again, and the copy's path.
        """
        pathB = docB.FileName
        original = self._path("Original")
        moved = self._path("Moved")
        shutil.copy(pathB, original)
        self._moveFaces(docB)
        shutil.copy(pathB, moved)
        App.closeDocument(docB.Name)
        shutil.copy(original, pathB)
        return App.openDocument(pathB), moved

    def _assertFace(self, shape, sub, x):
        """`sub` names the face of `shape` at x that faces -x."""
        face = shape.getElement(sub)
        self.assertAlmostEqual(face.CenterOfMass.x, x)
        self.assertLess(face.normalAt(0, 0).x, -0.5)

    def testReferenceRefreshedAfterOpening(self):
        """A reference saved in a closed document follows its element to a new index (ops#18).

        Document B holds a compound of two boxes; document A references the face of the second
        box at x = 20. With A closed, a third box is put first in the compound, so that face's
        index changes while its mapped name does not. Opening A again must refresh the reference
        to the face's new index: the refresh at the end of opening documents did nothing.
        """
        # Arrange
        docB = self._newDocument("ElementRefB")
        box1 = _box(docB, "Box1", 0)
        box2 = _box(docB, "Box2", 20)
        compound = docB.addObject("Part::Compound", "Compound")
        compound.Links = [box1, box2]
        docB.recompute()
        docB.save()
        oldIndex = _faceAtX(compound.Shape, 20)

        docA = self._newDocument("ElementRefA")
        ref = docA.addObject("App::FeaturePython", "Ref")
        ref.addProperty("App::PropertyXLinkSub", "Target")
        ref.Target = (compound, [oldIndex])
        docA.save()
        App.closeDocument(docA.Name)

        compound.Links = [_box(docB, "Box0", -20), box1, box2]
        docB.recompute()
        docB.save()
        newIndex = _faceAtX(compound.Shape, 20)
        self.assertNotEqual(oldIndex, newIndex)  # the setup moves the face

        # Act
        docA = App.openDocument(os.path.join(self.dir, "ElementRefA.FCStd"))

        # Assert
        linked, subs = docA.getObject("Ref").Target
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 1)
        face = compound.Shape.getElement(subs[0])
        self.assertAlmostEqual(face.CenterOfMass.x, 20)
        self.assertLess(face.normalAt(0, 0).x, -0.5)
        self.assertEqual(subs[0], newIndex)

    def testReferenceRefreshedWhenTargetClosed(self):
        """As above, with B closed too: opening A loads B, and the reference follows (ops#40).

        Attaching the reference to B, once B is loaded, threw away its saved mapped name and
        took the mapped name of whatever face now has the old index (Box1's face at x = 0).
        """
        # Arrange
        docB, compound = self._newTarget()
        oldIndex = _faceAtX(compound.Shape, 20)
        docA = self._newOwner(compound, [oldIndex])
        App.closeDocument(docA.Name)
        self._moveFaces(docB)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        linked, subs = docA.getObject("Ref").Target
        compound = App.getDocument("ElementRefB").getObject("Compound")
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 1)
        self._assertFace(compound.Shape, subs[0], 20)

    def testShadowKeptWhenTargetClosedWhileOpen(self):
        """Closing B while A is open keeps the reference's mapped name, also in A's file (ops#40).

        Closing B threw the mapped name away, and saving A then wrote the reference without it.
        """
        # Arrange
        docB, compound = self._newTarget()
        docA = self._newOwner(compound, [_faceAtX(compound.Shape, 20)])
        App.closeDocument(docB.Name)
        docA.save()
        App.closeDocument(docA.Name)
        with zipfile.ZipFile(self._path("ElementRefA")) as archive:
            xml = archive.read("Document.xml").decode("utf-8")
        # The file is saved relative to A's canonical directory. Where the temporary directory
        # is reached through a symlink (macOS: /var -> /private/var), that is a ../ path to B,
        # not the bare file name.
        xlink = re.search(r'<XLink file="([^"]*ElementRefB\.FCStd)"[^>]*>', xml)
        self.assertIsNotNone(xlink, "\n".join(re.findall(r"<XLink [^>]*>", xml)))
        savedPath = os.path.join(os.path.realpath(self.dir), xlink.group(1))
        self.assertTrue(os.path.samefile(savedPath, self._path("ElementRefB")), xlink.group(0))
        self.assertIn(' shadow="', xlink.group(0))
        docB = App.openDocument(self._path("ElementRefB"))
        self._moveFaces(docB)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        linked, subs = docA.getObject("Ref").Target
        compound = App.getDocument("ElementRefB").getObject("Compound")
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 1)
        self._assertFace(compound.Shape, subs[0], 20)

    def testTargetReopenedWhileOwnerOpen(self):
        """A stays open while B is closed, changed and opened again: A's reference follows its
        face, and A's object is touched to be recomputed with it (ops#40)."""
        # Arrange
        docB, _ = self._newTarget()
        docB, moved = self._prepareMovedCopy(docB)
        compound = docB.getObject("Compound")
        docA = self._newOwner(compound, [_faceAtX(compound.Shape, 20)])
        App.closeDocument(docB.Name)
        shutil.copy(moved, self._path("ElementRefB"))

        # Act
        docB = App.openDocument(self._path("ElementRefB"))

        # Assert
        ref = docA.getObject("Ref")
        linked, subs = ref.Target
        compound = docB.getObject("Compound")
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 1)
        self._assertFace(compound.Shape, subs[0], 20)
        self.assertIn("Touched", ref.State)

    def testSubListReference(self):
        """A PropertyXLinkSubList (the type of SubShapeBinder.Support) with a face of each box:
        both references follow their faces when B is closed, changed and opened again (ops#40).
        Its children are restored and detached inside the parent's change notification."""
        # Arrange
        docB, _ = self._newTarget()
        docB, moved = self._prepareMovedCopy(docB)
        compound = docB.getObject("Compound")
        faces = [_faceAtX(compound.Shape, 0), _faceAtX(compound.Shape, 20)]
        docA = self._newOwner(compound, faces, "App::PropertyXLinkSubList")
        App.closeDocument(docB.Name)
        shutil.copy(moved, self._path("ElementRefB"))

        # Act
        docB = App.openDocument(self._path("ElementRefB"))

        # Assert
        compound = docB.getObject("Compound")
        target = docA.getObject("Ref").Target
        self.assertEqual(len(target), 1)
        linked, subs = target[0]
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 2)
        self._assertFace(compound.Shape, subs[0], 0)
        self._assertFace(compound.Shape, subs[1], 20)

    def testRemovedElementReportedMissing(self):
        """When the referenced face is gone, the reference is marked missing on opening, and
        does not take the face that now has its old index (ops#40)."""
        # Arrange
        docB, compound = self._newTarget()
        oldIndex = _faceAtX(compound.Shape, 20)
        docA = self._newOwner(compound, [oldIndex])
        App.closeDocument(docA.Name)
        box1 = docB.getObject("Box1")
        compound.Links = [box1, _box(docB, "Box3", 40)]  # Box3's face at x = 40 takes the index
        docB.removeObject("Box2")
        docB.recompute()
        docB.save()
        self.assertEqual(_faceAtX(compound.Shape, 40), oldIndex)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        _, subs = docA.getObject("Ref").Target
        self.assertEqual(len(subs), 1)
        self.assertIn("?", subs[0])

    def testUnchangedTargetLeavesOwnerUntouched(self):
        """When B has not changed, opening A with B closed keeps the reference as it was and
        leaves A's object untouched."""
        # Arrange
        docB, compound = self._newTarget()
        index = _faceAtX(compound.Shape, 20)
        docA = self._newOwner(compound, [index])
        App.closeDocument(docA.Name)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        ref = docA.getObject("Ref")
        _, subs = ref.Target
        self.assertEqual(subs, [index])
        self.assertNotIn("Touched", ref.State)

    def testReferenceThroughLinkInOwner(self):
        """A reference to an App::Link in A that links B's compound, the shape of an Assembly
        joint's reference, follows its face when A is opened with B closed."""
        # Arrange
        docB, compound = self._newTarget()
        oldIndex = _faceAtX(compound.Shape, 20)
        docA = self._newDocument("ElementRefA")
        link = docA.addObject("App::Link", "Link")
        link.LinkedObject = compound
        ref = docA.addObject("App::FeaturePython", "Ref")
        ref.addProperty("App::PropertyXLinkSub", "Target")
        ref.Target = (link, [oldIndex])
        docA.recompute()
        docA.save()
        App.closeDocument(docA.Name)
        self._moveFaces(docB)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        linked, subs = docA.getObject("Ref").Target
        self.assertEqual(linked, docA.getObject("Link"))
        self.assertEqual(len(subs), 1)
        compound = App.getDocument("ElementRefB").getObject("Compound")
        self._assertFace(compound.Shape, subs[0], 20)
