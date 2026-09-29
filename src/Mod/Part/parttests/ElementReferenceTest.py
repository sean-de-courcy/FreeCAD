# SPDX-License-Identifier: LGPL-2.1-or-later

"""Element references across documents, refreshed when documents are opened."""

import os
import shutil
import tempfile
import unittest

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
