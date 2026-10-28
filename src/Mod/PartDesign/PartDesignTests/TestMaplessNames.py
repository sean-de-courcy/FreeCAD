# SPDX-License-Identifier: LGPL-2.1-or-later

"""References to results without history, whose element ids their producer gives by a verified
match (MLN; FreeCAD-CH, ops#502, the class C ruling of 10-28): a retired id breaks at the reference
solver (invariant I-C5), an element that comes back is a new element, an undone id is never given
again, and a script builder's index map counts as no map. Designed models in documents with the
reference solver on."""

import unittest

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models

V = App.Vector


def boxes(places, size=(8, 8, 5)):
    """A fresh shape (no element map) holding a box of `size` at each x of `places`."""
    shape = Part.Shape()
    compound = Part.makeCompound([Part.makeBox(*size, V(x, 0, 0)) for x in places])
    shape.importBrepFromString(compound.exportBrepToString())
    return shape


def topFace(shape, x):
    """The index name of the face of `shape` facing +z at its top, over the point (x, 4)."""
    for i, f in enumerate(shape.Faces, 1):
        if f.normalAt(0, 0).z > 0.5 and f.isInside(V(x, 4, f.CenterOfMass.z), 1e-6, True):
            return "Face%d" % i
    raise AssertionError(f"no top face over x = {x}")


class TestMaplessNames(unittest.TestCase):
    def setUp(self):
        self.documents = []

    def tearDown(self):
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)

    def newDocument(self):
        doc = models.newDocument("MaplessNames")
        doc.HistoryAlgorithm = "V2"
        doc.ReferenceSolver = True
        self.documents.append(doc.Name)
        return doc

    def attach(self, doc, target, face):
        sketch = doc.addObject("Sketcher::SketchObject", "On" + face)
        sketch.AttachmentSupport = [(target, face)]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        self.assertTrue(sketch.isValid())
        return sketch

    def assertRetired(self, consumer, candidate):
        """The consumer's reference broke on a retired id, `candidate` among its candidates."""
        self.assertFalse(consumer.isValid())
        report = App.getReferenceReport(consumer)
        self.assertEqual(len(report), 1)
        entry = report[0]
        self.assertEqual(entry["status"], "broken")
        self.assertTrue(entry["evidence"].startswith("retired:"), entry["evidence"])
        self.assertIn(candidate, entry["candidates"])
        self.assertIn("Renamed face reference", consumer.getStatusString())

    def testFreshIdAtTheSamePlaceBreaks(self):
        """The ruling's probe `Sk`: the same box set again with every face given a new id by its
        producer. The top face's id is retired: the reference breaks with the face at its place
        as the candidate, never resolves there quietly (I-C5)."""
        # Arrange
        doc = self.newDocument()
        target = doc.addObject("Part::Feature", "Named")

        def named(first):
            shape = boxes([0])
            for i in range(1, len(shape.Faces) + 1):
                shape.setElementName("Face%d" % i, "_;_;%d;MLN;%d;F;0;_;_" % (target.ID, first + i))
            return shape

        target.Shape = named(900)
        doc.recompute()
        top = topFace(target.Shape, 4)
        sketch = self.attach(doc, target, top)

        # Act
        target.Shape = named(950)
        doc.recompute()

        # Assert
        self.assertRetired(sketch, top)

    def testRestoredElementStaysRetired(self):
        """The ruling's A5: a box of a script's compound removed and put back by a later edit is
        a new element: its old ids were retired when it went and are never given again, so a
        reference to its old top face breaks, the box back at its place as the candidate."""
        # Arrange
        doc = self.newDocument()
        target = models.feature(doc, "Twins", boxes([0, 20]))
        doc.recompute()
        top = topFace(target.Shape, 24)
        sketch = self.attach(doc, target, top)

        # Act
        target.Shape = boxes([0])
        doc.recompute()
        target.Shape = boxes([0, 20])
        doc.recompute()

        # Assert
        self.assertRetired(sketch, topFace(target.Shape, 24))

    def testUndoneIdBreaksAcrossDocumentsAndRedoBringsItBack(self):
        """The ruling's A5: a box added to a script's compound in a transaction, a binder in
        another document linked to its top face. Undo takes the box away: the binder's id is
        gone from the target, so the binder breaks. Redo brings the id back: the binder resolves
        again. Undone again and the box given back by a new edit, the counter has kept the undone
        ids (an id given in an undone step is never given again): the box's id is fresh, and the
        binder stays broken."""
        # Arrange
        doc = self.newDocument()
        doc.UndoMode = 1
        target = models.feature(doc, "Row", boxes([0]))
        doc.recompute()
        doc.openTransaction("add")
        target.Shape = boxes([0, 20])
        doc.commitTransaction()
        doc.recompute()
        top = topFace(target.Shape, 24)
        other = self.newDocument()
        binder = other.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(target, (top,))]
        other.recompute()
        self.assertTrue(binder.isValid())
        self.assertAlmostEqual(binder.Shape.BoundBox.XMin, 20)

        # Act: undo
        doc.undo()
        doc.recompute()
        other.recompute()

        # Assert
        self.assertFalse(binder.isValid())

        # Act: redo
        doc.redo()
        doc.recompute()
        other.recompute()

        # Assert: the redone step's ids, the binder's among them
        self.assertTrue(binder.isValid(), binder.getStatusString())
        self.assertAlmostEqual(binder.Shape.BoundBox.XMin, 20)

        # Act: undone again, and the box given back by a new edit
        doc.undo()
        doc.recompute()
        doc.openTransaction("again")
        target.Shape = boxes([0, 20])
        doc.commitTransaction()
        doc.recompute()
        other.recompute()

        # Assert
        self.assertFalse(binder.isValid())

    def testScriptCompoundIndexMapIsNoMap(self):
        """The ruling's item 4: `Part.makeCompound` of map-less shapes gives every element an
        index name (`MKR` with the IDX flag). Stored in a feature, the compound is named by the
        match as if it had no map: its elements carry MLN ids, and a box removed from the front
        of the row leaves the other's ids on it."""
        # Arrange
        doc = self.newDocument()
        target = doc.addObject("Part::Feature", "Row")
        target.Shape = Part.makeCompound([Part.makeBox(8, 8, 5), Part.makeBox(8, 8, 5, V(20, 0, 0))])
        doc.recompute()
        names = list(target.Shape.ElementMap)
        self.assertTrue(names)
        self.assertTrue(all(";MLN;" in name and "IDX" not in name for name in names), names[:4])
        top = topFace(target.Shape, 24)
        sketch = self.attach(doc, target, top)

        # Act
        target.Shape = Part.makeCompound([Part.makeBox(8, 8, 5, V(20, 0, 0))])
        doc.recompute()

        # Assert
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertEqual(sketch.AttachmentSupport[0][1][0], topFace(target.Shape, 24))
