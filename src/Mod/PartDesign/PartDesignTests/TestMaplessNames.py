# SPDX-License-Identifier: LGPL-2.1-or-later

"""References to results without history, whose element ids their producer gives by a verified
match (MLN; FreeCAD-CH, ops#502, the class C ruling of 10-28): a retired id breaks at the reference
solver (invariant I-C5), an element that comes back is a new element, an undone id is never given
again, and a script builder's index map counts as no map. Designed models in documents with the
reference solver on."""

import os
import shutil
import tempfile
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
        self.folder = tempfile.mkdtemp(prefix="MaplessNames")

    def tearDown(self):
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)
        shutil.rmtree(self.folder, ignore_errors=True)

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
        self.assertIn("Missing face reference", consumer.getStatusString())
        self.assertIn("couldn't tell it from its neighbours", consumer.getStatusString())

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
        # a cross-document link needs both documents saved
        doc.saveAs(os.path.join(self.folder, "target.FCStd"))
        other.saveAs(os.path.join(self.folder, "binder.FCStd"))
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

    def testRetiredIdInACompoundOfTwoProducers(self):
        """The review's T1: a Part::Compound of two script compounds A and B with the same
        structure (each producer counts its ids from 1). A's twin cubes are traded, so P1 retires
        A's ids; B holds the same id numbers under its own tag, which is no evidence for A's: the
        reference to A's first cube's top breaks as retired, never resolves at the same place."""
        # Arrange
        doc = self.newDocument()

        def cubes(y, swapped=False):
            solids = [Part.makeBox(4, 4, 4, V(0, y, 0)), Part.makeBox(4, 4, 4, V(10, y, 0))]
            return Part.makeCompound(solids[::-1] if swapped else solids)

        a = models.feature(doc, "A", cubes(0))
        models.feature(doc, "B", cubes(20))
        both = doc.addObject("Part::Compound", "Both")
        both.Links = [a, doc.getObject("B")]
        doc.recompute()
        top = topFace(both.Shape, 2)
        sketch = self.attach(doc, both, top)

        # Act
        a.Shape = cubes(0, swapped=True)
        doc.recompute()

        # Assert
        self.assertRetired(sketch, topFace(both.Shape, 2))

    def testSplitPieceOfAnMlnElementIsNotRetired(self):
        """The review's T2: a Part::Cut of a 10 mm Part::Box by a slot pocketing its top face, a
        sketch on the cut's top face. The slot lengthened across the top splits the face in two:
        the pieces carry the old name as their source, so the old id is held, and the split's
        own handling decides (never a `retired` break)."""
        # Arrange
        doc = self.newDocument()
        box = models.box(doc, "Box", (10, 10, 10))
        slot = models.box(doc, "Slot", (4, 2, 4), (3, 4, 8))
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = box, slot
        doc.recompute()
        top = [
            "Face%d" % i
            for i, f in enumerate(cut.Shape.Faces, 1)
            if abs(f.CenterOfMass.z - 10) < 1e-6 and f.normalAt(0, 0).z > 0.5
        ][0]
        sketch = self.attach(doc, cut, top)

        # Act
        slot.Length = 12
        slot.Placement.Base = V(-1, 4, 8)
        doc.recompute()

        # Assert
        for entry in App.getReferenceReport(sketch):
            self.assertFalse(entry["evidence"].startswith("retired:"), entry["evidence"])

    def attachToVertex(self, doc, target, vertex):
        sketch = doc.addObject("Sketcher::SketchObject", "At" + vertex)
        sketch.AttachmentSupport = [(target, vertex)]
        sketch.MapMode = "Translate"
        doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        return sketch

    def testLoneVertexKeepsItsId(self):
        """ops#633: a script feature's shape, a lone vertex (no edge, no face), set again at the
        same place keeps its id, as an edge with no adjacent edge does: a sketch on it stays
        there. Before, the match never confirmed such a vertex, so every value gave it a fresh
        id and the sketch broke."""
        # Arrange
        doc = self.newDocument()
        target = models.feature(doc, "Spot", Part.Vertex(V(5, 2, 1)))
        doc.recompute()
        names = list(target.Shape.ElementMap)
        self.assertEqual(len(names), 1)
        self.assertIn(";MLN;", names[0])
        sketch = self.attachToVertex(doc, target, "Vertex1")

        # Act
        target.Shape = Part.Vertex(V(5, 2, 1))
        doc.recompute()

        # Assert
        self.assertEqual(list(target.Shape.ElementMap), names)
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertAlmostEqual((sketch.Placement.Base - V(5, 2, 1)).Length, 0)

    def testCornerOfARemovedSolidIsNotALoneVertex(self):
        """ops#633's bound: a box's corner and, after the edit, a lone vertex at that corner's
        place are other elements (the vertex stood at no edge before only if its old partner
        did too): a sketch on the corner breaks, never moves to the lone vertex quietly."""
        # Arrange
        doc = self.newDocument()
        target = models.feature(doc, "Corner", boxes([0]))
        doc.recompute()
        corner = [
            "Vertex%d" % i
            for i, v in enumerate(target.Shape.Vertexes, 1)
            if v.Point.distanceToPoint(V(0, 0, 0)) < 1e-9
        ][0]
        sketch = self.attachToVertex(doc, target, corner)

        # Act
        target.Shape = Part.Vertex(V(0, 0, 0))
        doc.recompute()

        # Assert
        self.assertFalse(sketch.isValid())

    def testDroppedLonePointWithTheRestSlidBreaks(self):
        """Review pr431-r1's round (`LonePointsFirstDeletedRestSlid`): a script compound of lone
        points at x = 0, 20, 40, the first dropped and the other two slid onto the places before
        them. A place match can't tell lone points apart, so only a shape that is one vertex
        keeps its id: the sketches on the first two points break, never sit on the wrong point
        quietly."""
        # Arrange
        doc = self.newDocument()

        def points(places):
            return Part.makeCompound([Part.Vertex(V(x, 0, 0)) for x in places])

        target = models.feature(doc, "Points", points([0, 20, 40]))
        doc.recompute()
        first = self.attachToVertex(doc, target, "Vertex1")
        second = self.attachToVertex(doc, target, "Vertex2")

        # Act
        target.Shape = points([0, 20])
        doc.recompute()

        # Assert
        self.assertFalse(first.isValid())
        self.assertFalse(second.isValid())


class TestDatumNamesAfterReopen(unittest.TestCase):
    """ops#633: a datum point's shape is rebuilt when its document opens (the restored one has the
    old placement in it). Its element names after the open, and after a recompute, are the ones it
    was saved with, so a reference to its vertex holds across any number of save and reopen cycles
    (Onshape keeps references to points). Before, the rebuilt shape came without names and the
    recompute gave the vertex a fresh id at every open: the reference broke at the first."""

    def setUp(self):
        self.documents = []
        self.folder = tempfile.mkdtemp(prefix="DatumNames")

    def tearDown(self):
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def build(self):
        """A 10 mm box in a body, a datum point at its top face's centre and a second one
        attached to the first one's vertex, 5 mm above it."""
        doc = models.newDocument("DatumNames")
        doc.HistoryAlgorithm = "V2"
        doc.ReferenceSolver = True
        self.documents.append(doc.Name)
        body = doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 10
        doc.recompute()
        top = [
            "Face%d" % i
            for i, f in enumerate(box.Shape.Faces, 1)
            if abs(f.CenterOfMass.z - 10) < 1e-6 and f.normalAt(0, 0).z > 0.5
        ][0]
        point = body.newObject("PartDesign::Point", "Mid")
        point.AttachmentSupport = [(box, top)]
        point.MapMode = "CenterOfMass"
        doc.recompute()
        above = body.newObject("PartDesign::Point", "Above")
        above.AttachmentSupport = [(point, "Vertex1")]
        above.MapMode = "Vertex"
        above.AttachmentOffset = App.Placement(V(0, 0, 5), App.Rotation())
        doc.recompute()
        self.assertTrue(above.isValid(), above.getStatusString())
        return doc

    def reopen(self, doc):
        path = doc.FileName
        doc.save()
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        self.documents.append(doc.Name)
        return doc

    def testPointReferenceAcrossTwoReopens(self):
        # Arrange
        doc = self.build()
        doc.saveAs(os.path.join(self.folder, "points.FCStd"))
        names = dict(doc.getObject("Mid").Shape.ElementMap)
        # an MLN name, the case of ops#633: the point's shape was named by a match
        self.assertEqual(len(names), 1)
        self.assertIn(";MLN;", next(iter(names)))
        where = V(5, 5, 15)
        self.assertAlmostEqual((doc.getObject("Above").Placement.Base - where).Length, 0)

        for cycle in (1, 2):
            # Act
            doc = self.reopen(doc)
            opened = dict(doc.getObject("Mid").Shape.ElementMap)
            for obj in doc.Objects:
                obj.touch()
            doc.recompute()

            # Assert
            self.assertEqual(opened, names, f"open {cycle}")
            self.assertEqual(dict(doc.getObject("Mid").Shape.ElementMap), names, f"recompute {cycle}")
            above = doc.getObject("Above")
            self.assertTrue(above.isValid(), f"open {cycle}: {above.getStatusString()}")
            self.assertEqual(above.AttachmentSupport[0][1], ("Vertex1",))
            self.assertAlmostEqual((above.Placement.Base - where).Length, 0)

    def testLineReferenceAcrossTwoReopens(self):
        """A datum line's infinite edge isn't written to the file: the reopened line had a null
        shape until it was rebuilt, so a sketch normal to its edge broke at the first recompute.
        It is rebuilt at the open, at its own placement (here set directly, not attached)."""
        # Arrange
        doc = models.newDocument("DatumLine")
        doc.HistoryAlgorithm = "V2"
        doc.ReferenceSolver = True
        self.documents.append(doc.Name)
        body = doc.addObject("PartDesign::Body", "Body")
        line = body.newObject("PartDesign::Line", "Axis")
        line.Placement = App.Placement(V(3, 4, 0), App.Rotation(V(1, 0, 0), 30))
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "Across")
        sketch.AttachmentSupport = [(line, "Edge1")]
        sketch.MapMode = "NormalToEdge"
        doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        doc.saveAs(os.path.join(self.folder, "line.FCStd"))
        placed, where = line.Placement, sketch.Placement

        for cycle in (1, 2):
            # Act
            doc = self.reopen(doc)
            opened = doc.getObject("Axis").Shape
            for obj in doc.Objects:
                obj.touch()
            doc.recompute()

            # Assert
            self.assertEqual(len(opened.Edges), 1, f"open {cycle}: the line has no edge")
            self.assertTrue(doc.getObject("Axis").Placement.isSame(placed, 1e-9), f"open {cycle}")
            sketch = doc.getObject("Across")
            self.assertTrue(sketch.isValid(), f"open {cycle}: {sketch.getStatusString()}")
            self.assertTrue(sketch.Placement.isSame(where, 1e-9), f"open {cycle}")
