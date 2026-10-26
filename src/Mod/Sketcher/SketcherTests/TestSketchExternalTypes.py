# SPDX-License-Identifier: LGPL-2.1-or-later

"""A sketch's external link types stay with their links (ops#140).

`ExternalTypes` holds each link's type (projection, intersection or both), parallel to
`ExternalGeometry` by index. Deleting a link left its type behind, so the links after it read
the type of the link before them: an intersection rebuilt as a projection, its geometry count
changed, and the rebuild deleted the "surplus" geometry with the constraints on it.

The model: in a sketch on the XY plane at the origin, a projection of the rail, a line
(-20, 20, 0)-(20, 20, 0), and an intersection of the ring, a circle of radius 10 about the
origin in the XZ plane. The ring crosses the sketch plane at (10, 0) and (-10, 0): two points.
Its projection would be one line, (-10, 0)-(10, 0). A sketch line has its ends coincident with
the two points: two constraints, neither on the rail."""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD
import Part
import Sketcher

App = FreeCAD
V = App.Vector
TOL = 1e-6
PROJECTION, INTERSECTION, BOTH = 0, 1, 2
PENDING = -1  # the entry an open leaves when it couldn't tell every link's type


class TestSketchExternalTypes(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestSketchExternalTypes")
        self.rail = self.addEdge("Rail", Part.makeLine(V(-20, 20, 0), V(20, 20, 0)))
        self.ring = self.addEdge("Ring", Part.makeCircle(10, V(0, 0, 0), V(0, 1, 0)))
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.doc.recompute()
        self.sketch.addExternal(self.rail.Name, "Edge1", False, False)
        self.sketch.addExternal(self.ring.Name, "Edge1", False, True)
        self.doc.recompute()
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION])
        line = self.sketch.addGeometry(Part.LineSegment(V(-9, 1, 0), V(9, 1, 0)), False)
        # GeoIds -1, -2 are the axes, -3 the rail, -4 and -5 the ring's points
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", line, 1, -4, 1))
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", line, 2, -5, 1))
        self.doc.recompute()
        self.assertRingPoints()
        # which of the ring's points (x = 10 or -10) each constraint is on
        self.ringSides = [round(g.X / 10) for g in self.constrainedExternals()]
        self.assertEqual(sorted(self.ringSides), [-1, 1])

    def tearDown(self):
        if hasattr(self, "doc"):
            App.closeDocument(self.doc.Name)
        for folder in getattr(self, "folders", []):
            shutil.rmtree(folder, ignore_errors=True)

    def tempPath(self, name):
        """A path for a saved file, in a folder that tearDown removes."""
        folder = tempfile.mkdtemp()
        self.folders = getattr(self, "folders", []) + [folder]
        return os.path.join(folder, name)

    def addEdge(self, name, edge):
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = edge
        return obj

    def externalPoints(self, sketch=None):
        sketch = sketch or self.sketch
        return sorted(
            round(g.X, 6) for g in list(sketch.ExternalGeo)[2:] if isinstance(g, Part.Point)
        )

    def assertRingPoints(self, sketch=None):
        """The ring's two points, both constraints, and the sketch line between the points."""
        sketch = sketch or self.sketch
        self.assertEqual(self.externalPoints(sketch), [-10, 10])
        self.assertEqual(len(sketch.Constraints), 2)
        line = sketch.Geometry[0]
        self.assertEqual(
            sorted(round(p.x, 6) for p in (line.StartPoint, line.EndPoint)), [-10, 10]
        )

    def testDeleteKeepsTheOtherLinksType(self):
        self.sketch.delExternal(0)
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION])
        self.doc.recompute()
        self.assertRingPoints()

    def testAddAfterDeleteKeepsEachLinksType(self):
        self.sketch.delExternal(0)
        rail2 = self.addEdge("Rail2", Part.makeLine(V(-20, -20, 0), V(20, -20, 0)))
        self.doc.recompute()
        self.sketch.addExternal(rail2.Name, "Edge1", False, False)
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION, PROJECTION])
        self.doc.recompute()
        self.assertRingPoints()
        lines = [g for g in list(self.sketch.ExternalGeo)[2:] if isinstance(g, Part.LineSegment)]
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(lines[0].StartPoint.y, -20, delta=TOL)

    def testDeletingTheSourceObjectDropsItsType(self):
        """Deleting the rail drops its link outside the sketch (PropertyLinkSubList::breakLink)."""
        self.doc.removeObject(self.rail.Name)
        self.assertEqual(self.sketch.ExternalGeometry, [(self.ring, ("Edge1",))])
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION])
        self.doc.recompute()
        self.assertRingPoints()

    def testDeleteWithInvalidConstraintListKeepsConstraints(self):
        """With the sketch's geometry gone the constraint list is flagged invalid; deleting the
        rail then must not write it back empty. With the geometry back, both are there."""
        geometry = self.sketch.Geometry
        self.sketch.Geometry = []
        self.sketch.delExternal(0)
        self.sketch.Geometry = geometry
        self.assertEqual(len(self.sketch.Constraints), 2)
        self.assertEqual(
            [c.Type for c in self.sketch.Constraints], ["Coincident", "Coincident"]
        )
        self.doc.recompute()
        self.assertRingPoints()

    def testStaleTypeListRepairedOnOpen(self):
        """A file saved before the fix: a projection deleted before the rail left its type at
        index 0, so the list is [projection (stale), projection (rail), intersection (ring)] and
        the ring reads a projection by index. Opening it gives each link the type that gives back
        its saved geometries: the ring's two points."""
        self.sketch.ExternalTypes = [PROJECTION, PROJECTION, INTERSECTION]
        path = self.tempPath("StaleTypes.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, INTERSECTION])
        sketch.touch()
        self.doc.recompute()
        self.assertRingPoints(sketch)

    def saveAndReopen(self, name):
        path = self.tempPath(name + ".FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.doc = App.openDocument(path)
        return self.doc.getObject("Sketch")

    def testStaleTypeOfTheSameKindsRepairedByGeometry(self):
        """A sphere of radius 10 about (0, 0, 6) crosses the sketch plane in a circle of radius 8;
        its projection is a circle as well, of radius 10. Linked as an intersection behind a stale
        projection type, the counts and kinds can't tell the two apart: the saved circle's radius
        does. The repaired type is intersection, and the circle keeps radius 8."""
        ball = self.doc.addObject("Part::Feature", "Ball")
        ball.Shape = Part.makeSphere(10, V(0, 0, 6))
        self.doc.recompute()
        self.sketch.delExternal(0)
        self.sketch.addExternal(ball.Name, "Face1", False, True)
        self.doc.recompute()
        circles = [g for g in list(self.sketch.ExternalGeo)[2:] if isinstance(g, Part.Circle)]
        self.assertEqual(len(circles), 1)
        self.assertAlmostEqual(circles[0].Radius, 8, delta=TOL)
        # the ring, then the ball; a stale list gives the ball the projection type by index
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION, INTERSECTION])
        self.sketch.ExternalTypes = [INTERSECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("SameKinds")
        self.assertEqual(list(sketch.ExternalTypes), [INTERSECTION, INTERSECTION])
        sketch.touch()
        self.doc.recompute()
        circles = [g for g in list(sketch.ExternalGeo)[2:] if isinstance(g, Part.Circle)]
        self.assertEqual(len(circles), 1)
        self.assertAlmostEqual(circles[0].Radius, 8, delta=TOL)
        self.assertRingPoints(sketch)

    def testStaleTypesWithMissingElements(self):
        """Both sources lose their edge, so no type can be built. The ring's saved geometry, two
        distinct points of an edge, can only be an intersection; the rail's, one line, can't be
        told. The rail keeps the type at its index, and the type list ends in the pending mark so
        a later open can still repair it."""
        self.rail.Shape = Part.Vertex(V(0, 20, 0))
        self.ring.Shape = Part.Vertex(V(0, 0, 10))
        self.doc.recompute()
        self.sketch.ExternalTypes = [PROJECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("MissingElements")
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, PENDING])
        self.assertEqual(self.externalPoints(sketch), [-10, 10])

    def testUndoRedoOfDelete(self):
        self.doc.UndoMode = 1
        self.doc.openTransaction("Delete the rail")
        self.sketch.delExternal(0)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION])
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(len(self.sketch.ExternalGeometry), 2)
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION])
        self.assertRingPoints()
        self.doc.redo()
        self.doc.recompute()
        self.assertEqual(self.sketch.ExternalGeometry, [(self.ring, ("Edge1",))])
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION])
        self.assertRingPoints()

    def addBall(self, z=6):
        """A sphere of radius 10 about (0, 0, z), linked as an intersection: a circle of radius
        sqrt(100 - z^2). Its projection is a circle of radius 10."""
        ball = self.doc.addObject("Part::Feature", "Ball")
        ball.Shape = Part.makeSphere(10, V(0, 0, z))
        self.doc.recompute()
        self.sketch.addExternal(ball.Name, "Face1", False, True)
        self.doc.recompute()
        return ball

    def circleRadii(self, sketch=None):
        sketch = sketch or self.sketch
        return [
            round(g.Radius, 6) for g in list(sketch.ExternalGeo)[2:] if isinstance(g, Part.Circle)
        ]

    def makeRailUndecided(self):
        """The rail moves 5 above the sketch plane (its projection doesn't change, it no longer
        crosses the plane), then loses its edge: no type can be built for it, and its saved line
        can't tell the type."""
        self.rail.Shape = Part.makeLine(V(-20, 20, 5), V(20, 20, 5))
        self.doc.recompute()
        self.rail.Shape = Part.Vertex(V(0, 20, 5))
        self.doc.recompute()

    def testIntersectionTypeSurvivesARecomputeWhileARepairIsPending(self):
        """A stale list with a link whose type can't be told keeps its stale entry after the
        open. The repair runs only on the open: moved off the sketch plane, the ball gives no
        intersection, and a recompute must not turn it into a projection (a circle of radius 10,
        the same kind as the saved circle). Moved back, it gives its circle of radius 8 again."""
        self.addBall()
        self.makeRailUndecided()
        self.sketch.ExternalTypes = [PROJECTION, PROJECTION, INTERSECTION, INTERSECTION]
        sketch = self.saveAndReopen("PendingRepair")
        self.assertEqual(
            list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, INTERSECTION, PENDING]
        )
        ball = self.doc.getObject("Ball")
        ball.Shape = Part.makeSphere(10, V(0, 0, 20))
        self.doc.recompute()
        self.assertNotIn(10, self.circleRadii(sketch))
        self.assertNotIn(PROJECTION, list(sketch.ExternalTypes)[1:3])
        ball.Shape = Part.makeSphere(10, V(0, 0, 6))
        self.doc.recompute()
        self.assertNotIn(PROJECTION, list(sketch.ExternalTypes)[1:3])
        self.assertEqual(self.circleRadii(sketch), [8])

    def testShortTypeListWhenTheFirstSourceIsDeleted(self):
        """A file saved by a version whose paths appended links without a type: three links, two
        types. Deleting the rail's object drops its link outside the sketch; the ring keeps its
        intersection and the third link (a projection) its projection."""
        rail2 = self.addEdge("Rail2", Part.makeLine(V(-20, -20, 0), V(20, -20, 0)))
        self.doc.recompute()
        self.sketch.addExternal(rail2.Name, "Edge1", False, False)
        self.doc.recompute()
        self.sketch.ExternalTypes = [PROJECTION, INTERSECTION]
        self.doc.removeObject(self.rail.Name)
        self.assertEqual(len(self.sketch.ExternalGeometry), 2)
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION, PROJECTION])
        self.doc.recompute()
        self.assertRingPoints()

    def testKindsOnlyMatchTakesTheClosestType(self):
        """The ball moves half a unit up after its sketch was last rebuilt: its intersection is a
        circle of radius about 7.6, its projection one of radius 10, the saved one has radius 8.
        Neither gives the saved geometry exactly; behind a stale projection type, the repair on
        open takes the closer one, the intersection."""
        ball = self.addBall()
        self.sketch.delExternal(0)
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION, INTERSECTION])
        ball.Shape = Part.makeSphere(10, V(0, 0, 6.5))
        self.sketch.ExternalTypes = [INTERSECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("KindsOnly")
        self.assertEqual(list(sketch.ExternalTypes), [INTERSECTION, INTERSECTION])
        self.doc.recompute()
        radius = (100 - 6.5**2) ** 0.5
        self.assertEqual(self.circleRadii(sketch), [round(radius, 6)])
        self.assertRingPoints(sketch)

    @staticmethod
    def freezeInFile(path, obj):
        """Sets the Frozen flag of the external geometries of `obj` in a saved file (Python's
        copies of external points don't carry their extension, so it can't be set on them)."""
        with zipfile.ZipFile(path) as archive:
            entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for info, data in entries:
                if info.filename == "Document.xml":
                    data, count = re.subn(
                        rb'(Ref="' + obj.encode() + rb'\.[^"]*" Flags=")(\d+)"',
                        lambda m: m.group(1) + str(int(m.group(2)) | 2).encode() + b'"',
                        data,
                    )
                    assert count > 0
                archive.writestr(info, data)

    def testFrozenLinkTypeRepairedOnOpen(self):
        """The ring's points are frozen, and the stale list gives the ring a projection by index.
        The repair builds frozen links too: the ring gets its intersection back. Its points stay
        frozen: moving the ring doesn't move them."""
        self.sketch.ExternalTypes = [PROJECTION, PROJECTION, INTERSECTION]
        path = self.tempPath("Frozen.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.freezeInFile(path, "Ring")
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, INTERSECTION])
        self.doc.getObject("Ring").Shape = Part.makeCircle(12, V(0, 0, 0), V(0, 1, 0))
        sketch.touch()
        self.doc.recompute()
        self.assertRingPoints(sketch)

    def assertRailRepairedWhenItsEdgeIsBack(self, sketch, path, types):
        """Gives the rail its edge back, saves and opens again: the rail gets its projection,
        the stale entry goes."""
        self.doc.getObject("Rail").Shape = Part.makeLine(V(-20, 20, 5), V(20, 20, 5))
        self.doc.save()
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        self.assertEqual(list(sketch.ExternalTypes), types)
        sketch.touch()
        self.doc.recompute()
        lines = [g for g in list(sketch.ExternalGeo)[2:] if isinstance(g, Part.LineSegment)]
        self.assertTrue(any(abs(g.StartPoint.y - 20) < TOL for g in lines))
        self.assertRingPoints(sketch)
        return sketch

    def testLaterOpenWithTheElementBackRepairsTheType(self):
        """The rail's type can't be told while its edge is missing: it keeps the stale
        intersection at its index, and the list its stale entry. Opened again with the edge
        back, the rail gets its projection."""
        self.makeRailUndecided()
        self.sketch.ExternalTypes = [INTERSECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("ElementBack")
        self.assertEqual(list(sketch.ExternalTypes), [INTERSECTION, INTERSECTION, PENDING])
        self.assertRailRepairedWhenItsEdgeIsBack(
            sketch, self.doc.FileName, [PROJECTION, INTERSECTION]
        )

    def testStaleEntryKeptThroughALinkEdit(self):
        """As above, with a link added between the two opens: the stale entry stays after the
        new link's type, so the later open still repairs the rail."""
        self.makeRailUndecided()
        self.sketch.ExternalTypes = [INTERSECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("LinkEdit")
        rail2 = self.addEdge("Rail2", Part.makeLine(V(-20, -20, 0), V(20, -20, 0)))
        self.doc.recompute()
        sketch.addExternal(rail2.Name, "Edge1", False, False)
        self.assertEqual(
            list(sketch.ExternalTypes), [INTERSECTION, INTERSECTION, PROJECTION, PENDING]
        )
        self.assertRailRepairedWhenItsEdgeIsBack(
            sketch, self.doc.FileName, [PROJECTION, INTERSECTION, PROJECTION]
        )

    def testUndecidedTypeRepairedWhenTheElementComesBack(self):
        """The ball loses its face, and the stale list gives it a projection by index: on open its
        type can't be told (no type builds, a circle doesn't say which), so it keeps the
        projection, and the list ends in the pending mark. The face comes back in the same
        session: the recompute matches the ball with its saved circle (radius 8), so it gets its
        intersection back, not the projection's circle of radius 10, and the mark goes."""
        ball = self.addBall()
        ball.Shape = Part.Vertex(V(0, 0, 6))
        self.doc.recompute()
        self.sketch.ExternalTypes = [PROJECTION, INTERSECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("ElementBackInSession")
        self.assertEqual(
            list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, PROJECTION, PENDING]
        )
        self.doc.getObject("Ball").Shape = Part.makeSphere(10, V(0, 0, 6))
        self.doc.recompute()
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, INTERSECTION])
        self.assertEqual(self.circleRadii(sketch), [8])
        self.assertRingPoints(sketch)

    def testUndecidedTypeRepairedAfterAnUndo(self):
        """ops#237 Q5: as above, but the transaction that brings the face back (and so decides
        the type) is undone: the list has its stale projection and the mark again, and the link
        waits for its repair again. The face comes back once more: the recompute matches the
        ball with its saved circle again, intersection, radius 8. Before, the undo left the link
        decided, and it was built as the projection at its index, radius 10."""
        ball = self.addBall()
        ball.Shape = Part.Vertex(V(0, 0, 6))
        self.doc.recompute()
        self.sketch.ExternalTypes = [PROJECTION, INTERSECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("UndoneDecision")
        self.assertEqual(
            list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, PROJECTION, PENDING]
        )
        self.doc.UndoMode = 1
        ball = self.doc.getObject("Ball")
        self.doc.openTransaction("The face back")
        ball.Shape = Part.makeSphere(10, V(0, 0, 6))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, INTERSECTION])
        self.doc.undo()
        self.assertEqual(
            list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, PROJECTION, PENDING]
        )
        ball.Shape = Part.makeSphere(10, V(0, 0, 6))
        self.doc.recompute()
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, INTERSECTION])
        self.assertEqual(self.circleRadii(sketch), [8])
        self.assertRingPoints(sketch)

    def testUndecidedTypeKeptThroughARepairedReference(self):
        """As above, but the ball's sphere comes back as Face2 of a compound (Face1 a small square
        above the plane), and App.repairReference re-points the link to it: the link's key
        changes before the recompute. The link is still undecided under its new key, so the
        recompute matches it with its saved circle: intersection, radius 8."""
        ball = self.addBall()
        ball.Shape = Part.Vertex(V(0, 0, 6))
        self.doc.recompute()
        self.sketch.ExternalTypes = [PROJECTION, INTERSECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("RepairedReference")
        self.assertEqual(
            list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, PROJECTION, PENDING]
        )
        square = Part.makePlane(1, 1, V(30, 30, 5))
        self.doc.getObject("Ball").Shape = Part.makeCompound(
            [square, Part.makeSphere(10, V(0, 0, 6)).Faces[0]]
        )
        App.repairReference(sketch, "ExternalGeometry", 2, "Face2", True)
        self.assertEqual(sketch.ExternalGeometry[2][1], ("Face2",))
        self.doc.recompute()
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, INTERSECTION])
        self.assertEqual(self.circleRadii(sketch), [8])
        self.assertRingPoints(sketch)

    def testLaterOpenRepairsOnlyTheUndecidedLinks(self):
        """An open decides the ring and the ball from their saved geometry and leaves the rail
        (no edge) undecided. The ball then moves 3 up without a recompute: its saved circle (radius
        8) is now closer to its projection (radius 10) than to its intersection (radius about
        4.4). The next open repairs only the rail: the ball keeps its intersection."""
        ball = self.addBall()
        self.makeRailUndecided()
        self.sketch.ExternalTypes = [PROJECTION, PROJECTION, INTERSECTION, INTERSECTION]
        sketch = self.saveAndReopen("LaterOpen")
        self.assertEqual(
            list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, INTERSECTION, PENDING]
        )
        self.doc.getObject("Ball").Shape = Part.makeSphere(10, V(0, 0, 9))
        path = self.doc.FileName
        self.doc.save()
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        self.assertEqual(
            list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, INTERSECTION, PENDING]
        )

    def testKindsOnlyMatchOfARotatedSource(self):
        """As testKindsOnlyMatchTakesTheClosestType, with the ball also turned a quarter about the
        sketch normal, which moves where its circles' parameters start: the repair still takes the
        intersection."""
        ball = self.addBall()
        self.sketch.delExternal(0)
        shape = Part.makeSphere(10, V(0, 0, 6.5))
        shape.rotate(V(0, 0, 0), V(0, 0, 1), 90)
        ball.Shape = shape
        self.sketch.ExternalTypes = [INTERSECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("Rotated")
        self.assertEqual(list(sketch.ExternalTypes), [INTERSECTION, INTERSECTION])
        self.doc.recompute()
        radius = (100 - 6.5**2) ** 0.5
        self.assertEqual(self.circleRadii(sketch), [round(radius, 6)])

    def testDeletingTwoSourcesKeepsTheThirdLinksTypeAndConstraints(self):
        """Links to the rail, the ring and a second rail; deleting both rails' objects leaves the
        ring with its intersection and the two constraints on its points."""
        rail2 = self.addEdge("Rail2", Part.makeLine(V(-20, -20, 0), V(20, -20, 0)))
        self.doc.recompute()
        self.sketch.addExternal(rail2.Name, "Edge1", False, False)
        self.doc.recompute()
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION, PROJECTION])
        self.doc.removeObject(rail2.Name)
        self.doc.removeObject(self.rail.Name)
        self.assertEqual(self.sketch.ExternalGeometry, [(self.ring, ("Edge1",))])
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION])
        self.doc.recompute()
        self.assertRingPoints()

    def testCarbonCopyKeepsEachLinksType(self):
        """The rail's link deleted, a second sketch with a link to a second rail copies the first:
        it gets the ring's intersection after its own projection, and the line and both
        constraints on the ring's points."""
        self.sketch.delExternal(0)
        self.doc.recompute()
        rail2 = self.addEdge("Rail2", Part.makeLine(V(-20, -20, 0), V(20, -20, 0)))
        copy = self.doc.addObject("Sketcher::SketchObject", "Copy")
        self.doc.recompute()
        copy.addExternal(rail2.Name, "Edge1", False, False)
        self.doc.recompute()
        copy.carbonCopy(self.sketch.Name, False)
        self.assertEqual(list(copy.ExternalTypes), [PROJECTION, INTERSECTION])
        self.doc.recompute()
        self.assertRingPoints(copy)
        lines = [g for g in list(copy.ExternalGeo)[2:] if isinstance(g, Part.LineSegment)]
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(lines[0].StartPoint.y, -20, delta=TOL)

    def testUndoRedoOfDeletingASource(self):
        """Deleting the rail's object drops its link outside the sketch; undo brings the link and
        its type back, redo drops them again."""
        self.doc.UndoMode = 1
        self.doc.openTransaction("Delete the rail object")
        self.doc.removeObject(self.rail.Name)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION])
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(len(self.sketch.ExternalGeometry), 2)
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION])
        self.assertRingPoints()
        self.doc.redo()
        self.doc.recompute()
        self.assertEqual(len(self.sketch.ExternalGeometry), 1)
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION])
        self.assertRingPoints()

    def testStaleFileWhoseGeometryCameFromTheWrongType(self):
        """A file saved before the fix, in which the ring was already rebuilt by the stale
        projection type: its saved geometry is the projection, the line (-10, 0)-(10, 0). The
        repair keeps what the file shows: the ring stays a projection, and opening changes neither
        its geometry nor the document."""
        self.sketch.delExternal(1)
        self.sketch.addExternal(self.ring.Name, "Edge1", False, False)
        self.doc.recompute()
        lines = [g for g in list(self.sketch.ExternalGeo)[2:] if isinstance(g, Part.LineSegment)]
        self.assertEqual(len(lines), 2)
        self.sketch.ExternalTypes = [PROJECTION, INTERSECTION, PROJECTION]
        # such a file was saved recomputed: a touched object is saved as touched
        self.sketch.purgeTouched()
        self.assertFalse(self.doc.isTouched())
        sketch = self.saveAndReopen("WrongType")
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, PROJECTION])
        self.assertFalse(self.doc.isTouched())
        self.assertNotIn("Touched", sketch.State)
        lines = [g for g in list(sketch.ExternalGeo)[2:] if isinstance(g, Part.LineSegment)]
        self.assertEqual(len(lines), 2)
        self.assertEqual(self.externalPoints(sketch), [])

    def constrainedExternals(self, sketch=None):
        """The external geometry each constraint's second element is on, in constraint order."""
        sketch = sketch or self.sketch
        return [list(sketch.ExternalGeo)[-c.Second - 1] for c in sketch.Constraints]

    def assertConstraintsOnRingPoints(self, x, sketch=None):
        """Both constraints are on the ring's points at (x, 0) and (-x, 0), each on the one it
        was on in setUp."""
        geos = self.constrainedExternals(sketch)
        self.assertTrue(all(isinstance(g, Part.Point) for g in geos), geos)
        self.assertEqual([round(g.X, 6) for g in geos], [side * x for side in self.ringSides])
        self.assertEqual([round(g.Y, 6) for g in geos], [0, 0])

    def ringProjections(self, sketch=None):
        """The ring's projection: lines on the X axis (the rail's is at y = 20)."""
        sketch = sketch or self.sketch
        return [
            g
            for g in list(sketch.ExternalGeo)[2:]
            if isinstance(g, Part.LineSegment) and abs(g.StartPoint.y) < TOL
        ]

    def testProjectionAddedToAnIntersectionLinkKeepsItsConstraints(self):
        """ops#260: the ring is an intersection link with both constraints on its points. Adding
        its projection makes it Both. The constraints stay on the points, and the projection is
        the line (-10, 0)-(10, 0); a later rebuild (the ring grown to radius 12) keeps them so."""
        self.assertConstraintsOnRingPoints(10)
        self.sketch.addExternal(self.ring.Name, "Edge1", False, False)
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, BOTH])
        self.assertConstraintsOnRingPoints(10)
        lines = self.ringProjections()
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            sorted(round(p.x, 6) for p in (lines[0].StartPoint, lines[0].EndPoint)), [-10, 10]
        )
        self.doc.recompute()
        self.assertRingPoints()
        self.ring.Shape = Part.makeCircle(12, V(0, 0, 0), V(0, 1, 0))
        self.doc.recompute()
        self.assertConstraintsOnRingPoints(12)
        self.assertEqual(len(self.ringProjections()), 1)
        sketch = self.saveAndReopen("Both")
        sketch.touch()
        self.doc.recompute()
        self.assertConstraintsOnRingPoints(12, sketch)

    def testProjectionAddedToAnIntersectionLinkUndoes(self):
        """Undo gives back the intersection link with its constraints on the points; redo the
        Both link with them still on the points."""
        self.doc.UndoMode = 1
        self.doc.openTransaction("Add projection")
        self.sketch.addExternal(self.ring.Name, "Edge1", False, False)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.doc.undo()
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION])
        self.assertEqual(self.ringProjections(), [])
        self.assertConstraintsOnRingPoints(10)
        self.doc.redo()
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, BOTH])
        self.assertEqual(len(self.ringProjections()), 1)
        self.assertConstraintsOnRingPoints(10)

    def testDefiningProjectionAddedToAnIntersectionLink(self):
        """A defining projection added to the (non-defining) ring link is defining: the sketch's
        Shape has the sketch line and the projected line."""
        self.doc.recompute()
        self.assertEqual(len(self.sketch.Shape.Edges), 1)
        self.sketch.addExternal(self.ring.Name, "Edge1", True, False)
        self.doc.recompute()
        self.assertConstraintsOnRingPoints(10)
        self.assertEqual(len(self.sketch.Shape.Edges), 2)

    def testIntersectionAddedToAProjectionLinkKeepsItsConstraint(self):
        """The reverse: the ring linked as a projection in a second sketch, a constraint on the
        projected line. Adding the intersection keeps the constraint on the line."""
        sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch2")
        sketch.addExternal(self.ring.Name, "Edge1", False, False)
        line = sketch.addGeometry(Part.LineSegment(V(-9, 5, 0), V(9, 5, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("Parallel", line, -3))
        self.doc.recompute()
        sketch.addExternal(self.ring.Name, "Edge1", False, True)
        self.assertEqual(list(sketch.ExternalTypes), [BOTH])
        self.doc.recompute()
        geos = self.constrainedExternals(sketch)
        self.assertIsInstance(geos[0], Part.LineSegment)
        self.assertEqual(
            sorted(round(p.x, 6) for p in (geos[0].StartPoint, geos[0].EndPoint)), [-10, 10]
        )
        self.assertEqual(self.externalPoints(sketch), [-10, 10])

    def testLinkThatGivesNoGeometryIsRefused(self):
        """ops#252: an edge 5 above the sketch plane has no intersection with it. Linked as an
        intersection it gives no geometry: the add raises and the sketch is as it was. Before,
        the rebuild dropped the new link and the add returned the previous link's index, so
        nothing said it failed (the GUI committed an empty command)."""
        self.addEdge("Above", Part.makeLine(V(-20, 0, 5), V(20, 0, 5)))
        self.doc.recompute()
        links = self.sketch.ExternalGeometry
        count = len(self.sketch.ExternalGeo)
        with self.assertRaises(ValueError):
            self.sketch.addExternal("Above", "Edge1", False, True)
        self.assertEqual(self.sketch.ExternalGeometry, links)
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION])
        self.assertEqual(len(self.sketch.ExternalGeo), count)
        self.doc.recompute()
        self.assertRingPoints()

    def testIntersectionThatGivesNoGeometryAddedToAProjectionLinkIsRefused(self):
        """ops#252: the same edge linked as a projection (a line); adding its intersection, which
        gives nothing, raises and leaves the link a projection. Before, it became Both with no
        intersection geometry, silently."""
        self.addEdge("Above", Part.makeLine(V(-20, 0, 5), V(20, 0, 5)))
        self.doc.recompute()
        self.sketch.addExternal("Above", "Edge1", False, False)
        self.doc.recompute()
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION, PROJECTION])
        count = len(self.sketch.ExternalGeo)
        with self.assertRaises(ValueError):
            self.sketch.addExternal("Above", "Edge1", False, True)
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION, PROJECTION])
        self.assertEqual(len(self.sketch.ExternalGeo), count)
        self.doc.recompute()
        self.assertRingPoints()

    def testProjectionAddedWhileTheIntersectionShrinksIsAccepted(self):
        """PR 269 review L1: a wave crossing the sketch plane three times, linked as an
        intersection (three points). Its source becomes a line crossing it once, and before a
        recompute its projection is added: the rebuild gives one point and one projected line,
        two geometries where there were three. The added projection gives one, so the add is
        accepted (Both). Counting all of the link's geometries refused it."""
        wave = Part.BSplineCurve()
        wave.interpolate([V(0, -30, -2), V(5, -25, 2), V(10, -30, -2), V(15, -25, 2)])
        source = self.addEdge("Wave", wave.toShape())
        self.doc.recompute()
        self.sketch.addExternal(source.Name, "Edge1", False, True)
        self.doc.recompute()
        self.assertEqual(len(self.sketch.ExternalGeo), 2 + 3 + 3)
        source.Shape = Part.makeLine(V(0, -30, -2), V(10, -30, 2))
        self.sketch.addExternal(source.Name, "Edge1", False, False)
        self.assertEqual(list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION, BOTH])
        self.doc.recompute()
        self.assertEqual(len(self.sketch.ExternalGeo), 2 + 3 + 2)
        # the ring's two points and the line's crossing at x = 5; the ring's constraints kept
        self.assertEqual(self.externalPoints(), [-10, 5, 10])
        self.assertEqual(len(self.sketch.Constraints), 2)

    def testShapesIntersectionAddedToItsProjectionLinksIsAccepted(self):
        """PR 269 round 2: a zigzag wire crossing the sketch plane twice, its two edges linked as
        projections. The whole wire's intersection, added at once, gives each edge's link its
        crossing point (both become Both) and adds no link. The add counted links, so it raised
        "gives no intersection geometry" while keeping the change."""
        zigzag = Part.Wire(
            [
                Part.makeLine(V(0, -30, -2), V(5, -30, 2)),
                Part.makeLine(V(5, -30, 2), V(10, -30, -2)),
            ]
        )
        source = self.addEdge("Zigzag", zigzag)
        self.doc.recompute()
        self.sketch.addExternal(source.Name, "Edge1", False, False)
        self.sketch.addExternal(source.Name, "Edge2", False, False)
        self.doc.recompute()
        self.assertEqual(len(self.sketch.ExternalGeo), 2 + 3 + 2)
        self.sketch.addExternal(source.Name, "", False, True)
        self.assertEqual(
            list(self.sketch.ExternalTypes), [PROJECTION, INTERSECTION, BOTH, BOTH]
        )
        self.doc.recompute()
        self.assertEqual(len(self.sketch.ExternalGeo), 2 + 3 + 2 + 2)
        self.assertEqual(self.externalPoints(), [-10, 2.5, 7.5, 10])
        self.assertEqual(len(self.sketch.Constraints), 2)

    def testProjectionAddedToAFrozenIntersectionLinkIsRefused(self):
        """A frozen link isn't rebuilt, so the projection added to it would have no geometry
        until the link thaws, and then take the points' slots. The add is refused, loudly."""
        path = self.tempPath("FrozenRing.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.freezeInFile(path, "Ring")
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        with self.assertRaises(ValueError):
            sketch.addExternal("Ring", "Edge1", False, False)
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, INTERSECTION])
        self.assertConstraintsOnRingPoints(10, sketch)

    # ops#264: a link's geometry Ids were handed out by position within the link, so a Both link
    # whose projection changed in number, or a type written from Python, moved constraints from
    # one kind to the other, silently. The Ids go per kind now (projection, intersection).

    def testTypeWrittenFromPythonIntersectionToBothKeepsTheConstraints(self):
        """ExternalTypes written from Python (the ring from intersection to both): the
        constraints stay on the ring's points, and the projection is the line (-10, 0)-(10, 0)."""
        self.sketch.ExternalTypes = [PROJECTION, BOTH]
        self.doc.recompute()
        self.assertConstraintsOnRingPoints(10)
        self.assertEqual(len(self.ringProjections()), 1)
        self.assertEqual(self.externalPoints(), [-10, 10])

    def addRingProjectionWithAConstraint(self, sketch=None):
        """The ring made Both by adding its projection, and a second sketch line parallel to the
        projection: constraint 2, on the projected line."""
        sketch = sketch or self.sketch
        sketch.addExternal(self.ring.Name, "Edge1", False, False)
        self.doc.recompute()
        (index,) = [
            i
            for i, g in enumerate(sketch.ExternalGeo)
            if i >= 2 and isinstance(g, Part.LineSegment) and abs(g.StartPoint.y) < TOL
        ]
        geo_id = -index - 1
        line = sketch.addGeometry(Part.LineSegment(V(-5, 5, 0), V(5, 6, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("Parallel", line, geo_id))
        self.doc.recompute()
        self.assertEqual(len(sketch.Constraints), 3)
        self.assertIs(type(self.constrainedExternals(sketch)[2]), Part.LineSegment)
        return line

    def assertPointConstraintsKept(self, sketch=None):
        """The first two constraints are still on the ring's points, each on its own."""
        sketch = sketch or self.sketch
        geos = self.constrainedExternals(sketch)[:2]
        self.assertTrue(all(isinstance(g, Part.Point) for g in geos), geos)
        self.assertEqual([round(g.X / 10) for g in geos], self.ringSides)

    def testTypeWrittenFromPythonBothToIntersectionDropsOnlyTheProjection(self):
        """The reverse: the ring Both, with a constraint on its projection, written back to
        intersection. The projection goes, with its constraint (and a warning); the points keep
        theirs."""
        self.addRingProjectionWithAConstraint()
        self.sketch.ExternalTypes = [PROJECTION, INTERSECTION]
        self.doc.recompute()
        self.assertEqual(self.ringProjections(), [])
        self.assertEqual(len(self.sketch.Constraints), 2)
        self.assertPointConstraintsKept()

    def testLegacyGeometryWithoutKindsKeepsItsIds(self):
        """A file saved before ops#264 has no kinds on its external geometry: a rebuild that gives
        the same count keeps the Ids by position, as before, and records the kinds, so writing the
        ring back to intersection afterwards keeps the points' constraints."""
        self.addRingProjectionWithAConstraint()
        path = self.tempPath("Legacy.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.clearKindsInFile(path, "Ring")
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        sketch.touch()
        self.doc.recompute()
        self.assertPointConstraintsKept(sketch)
        self.assertIs(type(self.constrainedExternals(sketch)[2]), Part.LineSegment)
        sketch.ExternalTypes = [PROJECTION, INTERSECTION]
        self.doc.recompute()
        self.assertEqual(len(sketch.Constraints), 2)
        self.assertPointConstraintsKept(sketch)

    def testLegacyBothLinkGetsItsKindsOnOpen(self):
        """ops#269 (PR 241 review M1): a file saved before ops#264 (no kinds) with the ring Both,
        a constraint on its projection. The open records the kinds the saved type gives, so the
        ring written to intersection before any recompute drops the projection with its
        constraint, and the points keep theirs (by position, the first point took the
        projection's Id and the second point's constraint went, silently)."""
        self.addRingProjectionWithAConstraint()
        path = self.tempPath("LegacyBothOpen.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.clearKindsInFile(path, "Ring")
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        self.assertEqual(self.lineKinds(sketch), ["P", "P"])  # the rail's line, the ring's
        self.assertFalse(self.doc.isTouched())
        # saved, the kinds are in the file: the next open finds them, and touches nothing either
        sketch = self.saveAndReopen("LegacyBothSaved")
        self.assertEqual(self.lineKinds(sketch), ["P", "P"])
        self.assertFalse(self.doc.isTouched())
        sketch.ExternalTypes = [PROJECTION, INTERSECTION]
        self.doc.recompute()
        self.assertEqual(self.ringProjections(sketch), [])
        self.assertEqual(len(sketch.Constraints), 2)
        self.assertPointConstraintsKept(sketch)

    def makeTiltedBothSketch(self, outline):
        """The tilted face of `outline` linked Both by a new sketch, TiltedSketch; the sketch."""
        face = self.doc.addObject("Part::Feature", "Face")
        face.Shape = self.tiltedFace(outline)
        sketch = self.doc.addObject("Sketcher::SketchObject", "TiltedSketch")
        self.doc.recompute()
        sketch.addExternal(face.Name, "Face1", False, False)
        sketch.addExternal(face.Name, "Face1", False, True)
        self.doc.recompute()
        self.assertEqual(list(sketch.ExternalTypes), [BOTH])
        return sketch

    def testFrozenLegacyBothLinkGetsItsKindsOnOpen(self):
        """ops#278: a file saved before ops#264 (no kinds) with the tilted square face linked
        Both (four projected lines and a section line), frozen. The open records the kinds for a
        frozen link too, since its type gives the saved geometry, so once unfrozen its rebuild
        hands the Ids out by kind. Before, the open skipped frozen links: no kinds. The frozen
        geometry stays as saved, and the open leaves the document untouched (PR 253 review L6)."""

        def lineEnds(sketch):
            return [
                (tuple(round(c, 6) for c in g.StartPoint), tuple(round(c, 6) for c in g.EndPoint))
                for g in list(sketch.ExternalGeo)[2:]
                if isinstance(g, Part.LineSegment)
            ]

        sketch = self.makeTiltedBothSketch(self.SQUARE)
        self.assertEqual(sorted(self.lineKinds(sketch)), ["I"] + ["P"] * 4)
        saved = lineEnds(sketch)
        path = self.tempPath("LegacyFrozenBoth.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.clearKindsInFile(path, "Face")
        self.freezeInFile(path, "Face")
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("TiltedSketch")
        self.assertEqual(sorted(self.lineKinds(sketch)), ["I"] + ["P"] * 4)
        self.assertEqual(lineEnds(sketch), saved)
        self.assertFalse(self.doc.isTouched())
        self.assertNotIn("Touched", sketch.State)

    def testLegacyBothLinkInAStaleTypeListGetsTypeAndKindsOnOpen(self):
        """PR 251 review L3: a file saved before ops#140 and ops#264, a stale type in front of the
        rail and the ring Both, its geometry without kinds. One open gives each link its type
        back and the ring its kinds, so the ring written to intersection keeps the points'
        constraints."""
        self.addRingProjectionWithAConstraint()
        self.sketch.ExternalTypes = [PROJECTION, PROJECTION, BOTH]
        path = self.tempPath("LegacyStaleTypes.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.clearKindsInFile(path, "Ring")
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, BOTH])
        self.assertEqual(self.lineKinds(sketch), ["P", "P"])
        sketch.ExternalTypes = [PROJECTION, INTERSECTION]
        self.doc.recompute()
        self.assertEqual(self.ringProjections(sketch), [])
        self.assertEqual(len(sketch.Constraints), 2)
        self.assertPointConstraintsKept(sketch)

    def lineKinds(self, sketch=None):
        """The kind flags of each external line after the axes, as "P" (Projection), "I"
        (Intersection), "" (none) or "PI" (both). Lines only: a Part.Point read from ExternalGeo
        loses its extensions (a facade on it has a new Id and no flags)."""
        sketch = sketch or self.sketch
        out = []
        for geo in list(sketch.ExternalGeo)[2:]:
            if isinstance(geo, Part.Point):
                continue
            facade = Sketcher.ExternalGeometryFacade(geo)
            out.append(
                ("P" if facade.testFlag("Projection") else "")
                + ("I" if facade.testFlag("Intersection") else "")
            )
        return out

    def testKindsSurviveSaveAndReopen(self):
        """PR 241 review L4: the ring Both, with a constraint on its projection, saved and
        reopened: the kinds are still there, and used. Written back to intersection, the
        projection goes with its constraint and the points keep theirs (by position, the first
        point would take the projection's Id and the second point's constraint would go)."""
        self.addRingProjectionWithAConstraint()
        self.assertEqual(self.lineKinds(), ["P", "P"])  # the rail's line, the ring's
        sketch = self.saveAndReopen("Kinds")
        self.assertEqual(self.lineKinds(sketch), ["P", "P"])
        sketch.ExternalTypes = [PROJECTION, INTERSECTION]
        self.doc.recompute()
        self.assertEqual(self.ringProjections(sketch), [])
        self.assertEqual(len(sketch.Constraints), 2)
        self.assertPointConstraintsKept(sketch)

    def testBothKindFlagsSetCountsAsNone(self):
        """PR 241 review (Sonnet 4): a geometry with both kind flags (set from Python) has no
        kind to trust. The tilted square face linked Both, a constraint on its section line; the
        section line flagged both: the link gets its Ids by position, as a file saved before
        ops#264, so the same count keeps the constraint on the section, and the rebuild gives the
        section its one kind again. Read as a projection, the section took a fifth projection's
        place, and its constraint went."""
        face = self.doc.addObject("Part::Feature", "Face")
        face.Shape = self.tiltedFace(self.SQUARE)
        sketch = self.doc.addObject("Sketcher::SketchObject", "TiltedSketch")
        self.doc.recompute()
        sketch.addExternal(face.Name, "Face1", False, False)
        sketch.addExternal(face.Name, "Face1", False, True)
        self.doc.recompute()
        [(index, _)], projections = self.sectionAndProjections(sketch)
        self.assertEqual(len(projections), 4)
        line = sketch.addGeometry(Part.LineSegment(V(-4, 1, 0), V(4, 2, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("Coincident", line, 1, -index - 1, 1))
        self.doc.recompute()
        geos = list(sketch.ExternalGeo)
        facade = Sketcher.ExternalGeometryFacade(geos[index])
        self.assertTrue(facade.testFlag("Intersection"))
        facade.setFlag("Projection", True)
        geos[index] = facade.Geometry
        sketch.ExternalGeo = geos
        self.assertEqual(sorted(self.lineKinds(sketch)), ["P", "P", "P", "P", "PI"])
        sketch.touch()
        self.doc.recompute()
        self.assertEqual(len(sketch.Constraints), 1)
        [(index, section)], projections = self.sectionAndProjections(sketch)
        self.assertEqual(len(projections), 4)
        self.assertEqual(-sketch.Constraints[0].Second - 1, index)
        self.assertLess((sketch.Geometry[line].StartPoint - section.StartPoint).Length, TOL)
        self.assertEqual(sorted(self.lineKinds(sketch)), ["I", "P", "P", "P", "P"])

    @staticmethod
    def clearKindsInFile(path, obj):
        """Clears the kind flags (Projection, bit 5; Intersection, bit 6) of the external
        geometries of `obj` in a saved file, as a file saved before ops#264 has them."""
        with zipfile.ZipFile(path) as archive:
            entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for info, data in entries:
                if info.filename == "Document.xml":
                    data, count = re.subn(
                        rb'(Ref="' + obj.encode() + rb'\.[^"]*" Flags=")(\d+)"',
                        lambda m: m.group(1) + str(int(m.group(2)) & ~96).encode() + b'"',
                        data,
                    )
                    assert count > 0
                archive.writestr(info, data)

    @staticmethod
    def tiltedFace(outline):
        """A face from `outline`, (u, v) points in its plane, tilted 45 degrees about the X axis:
        (u, v) is at (u, v cos 45, v sin 45). It crosses the sketch plane z = 0 along v = 0."""
        c = 0.5**0.5
        points = [V(u, v * c, v * c) for u, v in outline]
        return Part.Face(Part.makePolygon(points + points[:1]))

    SQUARE = [(-5, -5), (5, -5), (5, 5), (-5, 5)]
    PENTAGON = [(-5, -5), (5, -5), (5, 5), (0, 8), (-5, 5)]

    @staticmethod
    def sectionAndProjections(sketch):
        """The face link's external lines, as (index in ExternalGeo, line): the section (on
        y = 0), and the projected edges."""
        lines = [
            (i, g)
            for i, g in enumerate(list(sketch.ExternalGeo)[2:], 2)
            if isinstance(g, Part.LineSegment)
        ]
        section = [(i, g) for i, g in lines if abs(g.StartPoint.y) + abs(g.EndPoint.y) < TOL]
        return section, [(i, g) for i, g in lines if abs(g.StartPoint.y) + abs(g.EndPoint.y) >= TOL]

    def testBothLinkWhoseProjectionChangesInNumberKeepsTheSectionsConstraint(self):
        """A square face tilted 45 degrees, linked as Both: 4 projected edges and the section
        line (-5, 0)-(5, 0), with a sketch line's start on the section's start. The face becomes
        a pentagon (5 edges): the constraint stays on the section. A constraint on an edge the
        pentagon added, and the face a square again: that edge has no counterpart, so the
        sketch fails naming it and keeps the constraint on it (ops#264 e2: before, the Ids went
        by position and the last projected geometry went, with its constraint and a warning);
        the section's constraint stays."""
        face = self.doc.addObject("Part::Feature", "Face")
        face.Shape = self.tiltedFace(self.SQUARE)
        sketch = self.doc.addObject("Sketcher::SketchObject", "TiltedSketch")
        self.doc.recompute()
        sketch.addExternal(face.Name, "Face1", False, False)
        sketch.addExternal(face.Name, "Face1", False, True)
        self.doc.recompute()
        self.assertEqual(list(sketch.ExternalTypes), [BOTH])
        section, projections = self.sectionAndProjections(sketch)
        self.assertEqual((len(section), len(projections)), (1, 4))
        line = sketch.addGeometry(Part.LineSegment(V(-4, 1, 0), V(4, 2, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("Coincident", line, 1, -section[0][0] - 1, 1))
        self.doc.recompute()

        def assertOnTheSection():
            section, _ = self.sectionAndProjections(sketch)
            self.assertEqual(len(section), 1)
            self.assertEqual(-sketch.Constraints[0].Second - 1, section[0][0])
            start = sketch.Geometry[line].StartPoint
            self.assertLess((start - section[0][1].StartPoint).Length, TOL)

        assertOnTheSection()
        face.Shape = self.tiltedFace(self.PENTAGON)
        self.doc.recompute()
        section, projections = self.sectionAndProjections(sketch)
        self.assertEqual((len(section), len(projections)), (1, 5))
        assertOnTheSection()
        # the projection of the pentagon's edge (0, 8)-(-5, 5), which the square doesn't have
        c = 0.5**0.5
        tip = [
            i
            for i, g in projections
            if {(round(p.x, 6), round(p.y, 6)) for p in (g.StartPoint, g.EndPoint)}
            == {(0, round(8 * c, 6)), (-5, round(5 * c, 6))}
        ][0]
        end = 1
        sketch.addConstraint(Sketcher.Constraint("Coincident", line, 2, -tip - 1, end))
        self.doc.recompute()
        self.assertEqual(len(sketch.Constraints), 2)
        tipLine = sketch.ExternalGeo[tip]
        face.Shape = self.tiltedFace(self.SQUARE)
        self.doc.recompute()
        self.assertFalse(sketch.isValid())
        self.assertIn(f"ExternalEdge{tip - 1}", sketch.getStatusString())
        self.assertEqual(len(sketch.Constraints), 2)
        kept = sketch.ExternalGeo[-sketch.Constraints[1].Second - 1]
        self.assertTrue(Sketcher.ExternalGeometryFacade(kept).testFlag("Missing"))
        self.assertLess((kept.StartPoint - tipLine.StartPoint).Length, TOL)
        self.assertLess((kept.EndPoint - tipLine.EndPoint).Length, TOL)
        section, projections = self.sectionAndProjections(sketch)
        self.assertEqual(len(section), 1)
        assertOnTheSection()

    def testFaceThatGainsAnEdgeKeepsTheConstraintOnItsEdge(self):
        """ops#264 e2 (class E's E1): the tilted square face projected (four lines), a sketch
        line's start on the projection of its left edge (x = -5). The face becomes the pentagon,
        its new edges between the right and left ones in the face's order: by position the left
        edge's Id went to the new edge (0, 8)-(-5, 5) and the line's start followed it, silently.
        The shape is set anew from Python, so the edges' names are no evidence; geometry pairs
        the left edge with its predecessor, and the constraint stays on it."""
        face = self.doc.addObject("Part::Feature", "Face")
        face.Shape = self.tiltedFace(self.SQUARE)
        sketch = self.doc.addObject("Sketcher::SketchObject", "TiltedSketch")
        self.doc.recompute()
        sketch.addExternal(face.Name, "Face1", False, False)
        self.doc.recompute()

        def left():
            _, projections = self.sectionAndProjections(sketch)
            found = [
                i
                for i, g in projections
                if abs(g.StartPoint.x + 5) < TOL and abs(g.EndPoint.x + 5) < TOL
            ]
            self.assertEqual(len(found), 1)
            return found[0]

        line = sketch.addGeometry(Part.LineSegment(V(-4, 1, 0), V(4, 2, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", line, 1, -left() - 1))
        self.doc.recompute()
        face.Shape = self.tiltedFace(self.PENTAGON)
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        _, projections = self.sectionAndProjections(sketch)
        self.assertEqual(len(projections), 5)
        self.assertEqual(-sketch.Constraints[0].Second - 1, left())
        self.assertAlmostEqual(sketch.Geometry[line].StartPoint.x, -5, delta=TOL)


def reportText():
    """The Report view's text (GUI only), where FC_WARN's warnings go."""
    import FreeCADGui
    from PySide import QtWidgets

    QtWidgets.QApplication.processEvents()
    for edit in FreeCADGui.getMainWindow().findChildren(QtWidgets.QTextEdit):
        if edit.metaObject().className() == "Gui::DockWnd::ReportOutput":
            return edit.toPlainText()
    return ""


class TestSketchExternalTypesGui(unittest.TestCase):
    """The warnings of TestSketchExternalTypes's cases, read in the Report view: in
    TestSketcherGui."""

    setUp = TestSketchExternalTypes.setUp
    tearDown = TestSketchExternalTypes.tearDown
    tempPath = TestSketchExternalTypes.tempPath
    addEdge = TestSketchExternalTypes.addEdge
    externalPoints = TestSketchExternalTypes.externalPoints
    assertRingPoints = TestSketchExternalTypes.assertRingPoints
    constrainedExternals = TestSketchExternalTypes.constrainedExternals
    addRingProjectionWithAConstraint = TestSketchExternalTypes.addRingProjectionWithAConstraint
    clearKindsInFile = staticmethod(TestSketchExternalTypes.clearKindsInFile)
    tiltedFace = staticmethod(TestSketchExternalTypes.tiltedFace)
    SQUARE = TestSketchExternalTypes.SQUARE
    PENTAGON = TestSketchExternalTypes.PENTAGON
    lineKinds = TestSketchExternalTypes.lineKinds
    freezeInFile = staticmethod(TestSketchExternalTypes.freezeInFile)
    makeTiltedBothSketch = TestSketchExternalTypes.makeTiltedBothSketch
    addBall = TestSketchExternalTypes.addBall
    circleRadii = TestSketchExternalTypes.circleRadii
    saveAndReopen = TestSketchExternalTypes.saveAndReopen
    sectionAndProjections = staticmethod(TestSketchExternalTypes.sectionAndProjections)
    # an arrowhead, its notch at (0, 1): the line v = 0 crosses its two arms apart
    DART = [(-5, -5), (0, 5), (5, -5), (0, 1)]

    def testLegacyBothLinkWhoseSplitMovedWarnsInsteadOfGivingKinds(self):
        """PR 251 review M1: a file saved before ops#264 (no kinds) with the tilted pentagon face
        linked Both: five projected lines and one section line. The face made the dart before the
        save, without the sketch's rebuild: four projected lines and two section lines, six lines
        as well. The same types in the same order don't say which saved line is which kind: the
        open compares the shapes, warns, and gives no kinds (by type, the fifth projection
        would have been read as a section, and its Id handed to one)."""
        if not App.GuiUp:
            self.skipTest("the Report view")
        face = self.doc.addObject("Part::Feature", "Face")
        face.Shape = self.tiltedFace(self.PENTAGON)
        sketch = self.doc.addObject("Sketcher::SketchObject", "TiltedSketch")
        self.doc.recompute()
        sketch.addExternal(face.Name, "Face1", False, False)
        sketch.addExternal(face.Name, "Face1", False, True)
        self.doc.recompute()
        self.assertEqual(sorted(self.lineKinds(sketch)), ["I"] + ["P"] * 5)
        face.Shape = self.tiltedFace(self.DART)
        path = self.tempPath("LegacySplit.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.clearKindsInFile(path, "Face")
        before = len(reportText())
        self.doc = App.openDocument(path)
        new = reportText()[before:]
        self.assertIn("its type no longer gives the same geometries", new)
        sketch = self.doc.getObject("TiltedSketch")
        self.assertEqual(self.lineKinds(sketch), [""] * 6)
        # the case is the one meant: the dart gives six lines, two of them sections
        sketch.touch()
        self.doc.recompute()
        section, projections = self.sectionAndProjections(sketch)
        self.assertEqual((len(section), len(projections)), (2, 4))

    def testFrozenLegacyBothLinkWhoseSplitMovedWarns(self):
        """ops#278: the case above with the link frozen. The open compares the shapes for a
        frozen link too: they differ, so it gives no kinds and says the Ids will go by position
        once the link is unfrozen. Before, it skipped the frozen link silently."""
        if not App.GuiUp:
            self.skipTest("the Report view")
        sketch = self.makeTiltedBothSketch(self.PENTAGON)
        self.doc.getObject("Face").Shape = self.tiltedFace(self.DART)
        path = self.tempPath("LegacyFrozenSplit.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.clearKindsInFile(path, "Face")
        self.freezeInFile(path, "Face")
        before = len(reportText())
        self.doc = App.openDocument(path)
        new = reportText()[before:]
        self.assertIn("its type no longer gives the same geometries", new)
        self.assertIn("(once it is unfrozen) the Ids go by position", new)
        sketch = self.doc.getObject("TiltedSketch")
        self.assertEqual(self.lineKinds(sketch), [""] * 6)

    def testUndecidedLinkWhoseElementComesBackUnmatchedWarns(self):
        """ops#237 (its nit): as in testUndecidedTypeRepairedWhenTheElementComesBack, but the
        ball's face comes back as a flat square above the sketch plane: no type gives the saved
        circle (the projection gives four lines, the intersection nothing), so its type can't be
        told. The recompute builds the type at its index, a projection, in place of the saved
        circle, and says so; the mark goes. Before, it did so silently."""
        if not App.GuiUp:
            self.skipTest("the Report view")
        ball = self.addBall()
        ball.Shape = Part.Vertex(V(0, 0, 6))
        self.doc.recompute()
        self.sketch.ExternalTypes = [PROJECTION, INTERSECTION, PROJECTION, INTERSECTION]
        sketch = self.saveAndReopen("ElementBackUnmatched")
        self.assertEqual(
            list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, PROJECTION, PENDING]
        )
        self.doc.getObject("Ball").Shape = Part.makePlane(4, 4, V(-2, -2, 5))
        before = len(reportText())
        self.doc.recompute()
        new = reportText()[before:]
        self.assertIn("its element is back, but no type gives its saved geometry", new)
        self.assertEqual(list(sketch.ExternalTypes), [PROJECTION, INTERSECTION, PROJECTION])
        self.assertEqual(self.circleRadii(sketch), [])
        # the axes, the rail's line and the square's four
        lines = [g for g in sketch.ExternalGeo if isinstance(g, Part.LineSegment)]
        self.assertEqual(len(lines), 2 + 1 + 4)

    def testTypeWrittenBeforeTheFirstRebuildOfLegacyGeometryNamesTheDeletedConstraint(self):
        """PR 241 review M1 and L2: a file saved before ops#264 (no kinds) with the ring Both (its
        projection line and two points, a constraint on the line); the ring written to
        intersection before any recompute. The open recorded the kinds (ops#269), so the rebuild
        drops the projection and says which constraint went with it: Constraint3."""
        if not App.GuiUp:
            self.skipTest("the Report view")
        self.addRingProjectionWithAConstraint()
        path = self.tempPath("LegacyBoth.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.clearKindsInFile(path, "Ring")
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        sketch.ExternalTypes = [PROJECTION, INTERSECTION]
        before = len(reportText())
        self.doc.recompute()
        new = reportText()[before:]
        self.assertIn("no longer gives are deleted (Constraint3)", new)
        self.assertNotIn("instead of", new)
        self.assertEqual(len(sketch.Constraints), 2)

    def testLegacyLinkWhoseTypeNoLongerGivesItsGeometryWarns(self):
        """ops#269: a file saved before ops#264 (no kinds) with a projection of the tilted square
        face (four lines), the face made a pentagon before the save, without the sketch's
        rebuild. The open can't tell the saved geometry's kinds from a build (five lines), and
        says the Ids will go by position; the rebuild then says they did, without the text about
        projections and intersections, which a link of one kind doesn't need."""
        if not App.GuiUp:
            self.skipTest("the Report view")
        face = self.doc.addObject("Part::Feature", "Face")
        face.Shape = self.tiltedFace(self.SQUARE)
        sketch = self.doc.addObject("Sketcher::SketchObject", "TiltedSketch")
        self.doc.recompute()
        sketch.addExternal(face.Name, "Face1", False, False)
        self.doc.recompute()
        self.assertEqual(len(sketch.ExternalGeo), 6)
        face.Shape = self.tiltedFace(self.PENTAGON)
        path = self.tempPath("LegacyStale.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.clearKindsInFile(path, "Face")
        before = len(reportText())
        self.doc = App.openDocument(path)
        new = reportText()[before:]
        self.assertIn("its type no longer gives the same geometries", new)
        sketch = self.doc.getObject("TiltedSketch")
        self.assertEqual(len(sketch.ExternalGeo), 6)
        sketch.touch()
        before = len(reportText())
        self.doc.recompute()
        new = reportText()[before:]
        self.assertIn("gives 5 geometries instead of 4, and they took its Ids by position", new)
        self.assertNotIn("doesn't record", new)
        self.assertEqual(len(sketch.ExternalGeo), 7)
