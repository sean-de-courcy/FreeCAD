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
import tempfile
import unittest

import FreeCAD
import Part
import Sketcher

App = FreeCAD
V = App.Vector
TOL = 1e-6
PROJECTION, INTERSECTION = 0, 1


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
