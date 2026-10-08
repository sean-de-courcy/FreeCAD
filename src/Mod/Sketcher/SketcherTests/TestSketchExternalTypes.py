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
import tempfile
import unittest
import zipfile

import FreeCAD
import Part
import Sketcher

App = FreeCAD
V = App.Vector
TOL = 1e-6
PROJECTION, INTERSECTION = 0, 1
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

    def tearDown(self):
        if hasattr(self, "doc"):
            App.closeDocument(self.doc.Name)

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
        path = os.path.join(tempfile.mkdtemp(), "StaleTypes.FCStd")
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
        path = os.path.join(tempfile.mkdtemp(), name + ".FCStd")
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
        path = os.path.join(tempfile.mkdtemp(), "Frozen.FCStd")
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
