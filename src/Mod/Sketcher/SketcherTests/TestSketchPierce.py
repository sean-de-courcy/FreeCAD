# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: Onshape's Pierce in one step. A sketch point is kept where a model edge (not in the
# sketch plane) crosses the plane by one constraint of type 'Pierce' (sketch.addPierce), whose
# crossing is a point of the edge's Intersection external, added as the constraint's helper
# (ops#634's implicit link) with the Pierce mark: as Onshape (oracle 10d), the crossing is the edge's
# underlying curve's (a line that stops short pierces at its extension's crossing), and the first
# along the edge from its start when the curve crosses more than once.
#
# The models are designed: a sketch on the XY plane at the origin and model edges whose crossings
# with z = 0 are known by construction. The expectations are geometric (where the point is).

import os
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector
TOL = 1e-7
NONE, START, END = 0, 1, 2  # PointPos
INTERSECTION = 1
IMPLICIT = 0x100
PIERCE = 0x200


class TestSketchPierce(unittest.TestCase):
    """The pole: a line (2, 3, -5)-(2, 3, 5), crossing the plane at (2, 3)."""

    def setUp(self):
        self.doc = App.newDocument("TestSketchPierce")
        self.pole = self.addEdge("Pole", Part.makeLine(V(2, 3, -5), V(2, 3, 5)))
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def addEdge(self, name, edge):
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = edge
        self.doc.recompute()
        return obj

    def addPoint(self, x, y, sketch=None):
        sketch = sketch or self.sketch
        return sketch.addGeometry(Part.Point(V(x, y, 0)))

    def links(self, sketch=None):
        sketch = sketch or self.sketch
        return [(obj.Name, sub) for obj, subs in sketch.ExternalGeometry for sub in subs]

    def assertAt(self, geoId, x, y, pos=START, sketch=None):
        sketch = sketch or self.sketch
        p = sketch.getPoint(geoId, pos)
        self.assertAlmostEqual(p.x, x, delta=TOL, msg=f"x of {geoId}.{pos}: {p}")
        self.assertAlmostEqual(p.y, y, delta=TOL, msg=f"y of {geoId}.{pos}: {p}")

    def testOnePierceConstraintPutsThePointAtTheCrossing(self):
        point = self.addPoint(0, 0)
        index = self.sketch.addPierce(point, START, self.pole, "Edge1")
        self.assertEqual(len(self.sketch.Constraints), 1)
        constraint = self.sketch.Constraints[index]
        self.assertEqual(constraint.Type, "Pierce")
        self.assertEqual(constraint.First, point)
        self.assertEqual(constraint.FirstPos, START)
        self.assertLess(constraint.Second, -2, "the crossing is external geometry, not an axis")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(point, 2, 3)
        # the crossing comes from one implicit Intersection link of the edge
        self.assertEqual(self.links(), [("Pole", "Edge1")])
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION | IMPLICIT | PIERCE])
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.assertAt(point, 2, 3)

    def testTheObjectCanBeGivenByName(self):
        point = self.addPoint(0, 0)
        self.sketch.addPierce(point, START, self.pole.Name, "Edge1")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(point, 2, 3)

    def testALinesEndPointPierces(self):
        """A curve's vertex as the point: the line's start goes to the crossing."""
        line = self.sketch.addGeometry(Part.LineSegment(V(-4, -4, 0), V(-1, -6, 0)))
        self.sketch.addPierce(line, START, self.pole, "Edge1")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(line, 2, 3, START)

    def testThePointFollowsTheEdge(self):
        """The pole moved by its Placement (its edge keeps its name): the point follows."""
        point = self.addPoint(0, 0)
        self.sketch.addPierce(point, START, self.pole, "Edge1")
        self.doc.recompute()
        self.assertAt(point, 2, 3)
        self.pole.Placement = App.Placement(V(4, -1, 0), App.Rotation())
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.assertAt(point, 6, 2)
        # tilted 45 degrees about the X axis: the crossing moves along the tilt
        self.pole.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 45))
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        # the rotation about X maps (2, 3, z) to (2, 3c - zs, 3s + zc), c = s = sqrt(1/2): z = -3
        # at the plane, so y = 3c + 3s = 6c
        self.assertAt(point, 2, 6 * 0.5**0.5)

    def testASlantedEdge(self):
        """The line (0, 0, -2)-(4, 2, 2) crosses z = 0 half way, at (2, 1)."""
        slant = self.addEdge("Slant", Part.makeLine(V(0, 0, -2), V(4, 2, 2)))
        point = self.addPoint(5, 5)
        self.sketch.addPierce(point, START, slant, "Edge1")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(point, 2, 1)

    def testAnEdgeThatMissesThePlaneIsRefused(self):
        """A line parallel to the plane, 3 above it: no crossing, so no Pierce (Onshape refuses
        it), and nothing is left behind."""
        rail = self.addEdge("Rail", Part.makeLine(V(-5, 0, 3), V(5, 0, 3)))
        point = self.addPoint(0, 0)
        with self.assertRaises(Exception):
            self.sketch.addPierce(point, START, rail, "Edge1")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(self.links(), [])
        self.assertEqual(len(self.sketch.ExternalGeo), 2)

    def testAnEdgeThatStopsShortPiercesAtItsExtension(self):
        """A slanted line (0, 0, 1)-(3, 3, 4) that ends 1 above the plane: Onshape pierces its
        underlying line, which crosses z = 0 one length unit before the start, at (-1, -1)."""
        stub = self.addEdge("Stub", Part.makeLine(V(0, 0, 1), V(3, 3, 4)))
        point = self.addPoint(5, 0)
        self.sketch.addPierce(point, START, stub, "Edge1")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(point, -1, -1)
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.assertAt(point, -1, -1)
        # moved up by 1: the extension's crossing moves back along it, to (-2, -2)
        stub.Placement = App.Placement(V(0, 0, 1), App.Rotation())
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.assertAt(point, -2, -2)

    def testAnArcWhoseSpanMissesThePlanePiercesThroughItsCircle(self):
        """An arc of the circle of radius 10 about the origin in the XZ plane, from (8, 0, 6) over
        the top to (-8, 0, 6), all above the plane: its circle crosses at (10, 0) and (-10, 0), and
        going on from the arc's end the first it meets is (-10, 0)."""
        arc = self.addEdge("Arc", Part.Arc(V(8, 0, 6), V(0, 0, 10), V(-8, 0, 6)).toShape())
        point = self.addPoint(9, 1)
        self.sketch.addPierce(point, START, arc, "Edge1")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(point, -10, 0)

    def testACircleThatMissesThePlaneIsRefused(self):
        """A circle parallel to the plane, 3 above it: its curve never crosses, so no Pierce."""
        ring = self.addEdge("Ring", Part.makeCircle(4, V(0, 0, 3), V(0, 0, 1)))
        point = self.addPoint(0, 0)
        with self.assertRaises(Exception):
            self.sketch.addPierce(point, START, ring, "Edge1")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(self.links(), [])

    def testAnEdgeInThePlaneIsRefused(self):
        """A line in the sketch plane has no crossing point (its section is the line)."""
        flat = self.addEdge("Flat", Part.makeLine(V(-5, 1, 0), V(5, 1, 0)))
        point = self.addPoint(0, 0)
        with self.assertRaises(Exception):
            self.sketch.addPierce(point, START, flat, "Edge1")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(self.links(), [])

    def testThePointMustBeTheSketchsOwn(self):
        """The origin (GeoId -1) can't be pierced: it can't move."""
        with self.assertRaises(Exception):
            self.sketch.addPierce(-1, START, self.pole, "Edge1")
        self.assertEqual(len(self.sketch.Constraints), 0)

    def testTwoCrossingsGiveTheFirstFromTheEdgesStart(self):
        """An arc of the circle of radius 10 about the origin in the XZ plane, from (0, 0, -10)
        through (-10, 0, 0) and over the top round to (6, 0, -8): it crosses the plane at (-10, 0)
        and then at (10, 0). Every point goes to the first from the start, (-10, 0), whatever its
        place (as Onshape), both from one link."""
        arc = self.addEdge(
            "Arc", Part.Arc(V(0, 0, -10), V(-10, 0, 0), V(6, 0, -8)).toShape()
        )
        right_point = self.addPoint(9, 1)
        left_point = self.addPoint(-9, 1)
        self.sketch.addPierce(right_point, START, arc, "Edge1")
        self.sketch.addPierce(left_point, START, arc, "Edge1")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(right_point, -10, 0)
        self.assertAt(left_point, -10, 0)
        self.assertEqual(self.links(), [("Arc", "Edge1")])
        self.assertEqual([c.Type for c in self.sketch.Constraints], ["Pierce", "Pierce"])
        self.assertEqual(self.sketch.Constraints[0].Second, self.sketch.Constraints[1].Second)

    def testTheEdgesDirectionDecidesTheFirstCrossing(self):
        """The same circle the other way round: from (6, 0, -8) through (10, 0, 0) over the top to
        (0, 0, -10). The first crossing from this start is (10, 0)."""
        arc = self.addEdge(
            "Arc", Part.Arc(V(6, 0, -8), V(10, 0, 0), V(0, 0, -10)).toShape()
        )
        point = self.addPoint(-9, 1)
        self.sketch.addPierce(point, START, arc, "Edge1")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(point, 10, 0)

    def testDeletingThePierceLeavesNoHelperBehind(self):
        """The constraint goes, then the helpers nothing uses (the constraint list's and the edit
        view's delete do both): the link goes with it."""
        point = self.addPoint(0, 0)
        index = self.sketch.addPierce(point, START, self.pole, "Edge1")
        self.doc.recompute()
        self.sketch.delConstraint(index)
        self.assertEqual(self.sketch.delUnusedImplicitExternals(), 1)
        self.doc.recompute()
        self.assertEqual(self.links(), [])
        self.assertEqual(len(self.sketch.ExternalGeo), 2)
        self.assertEqual(len(self.sketch.Constraints), 0)

    def testAHelperSharedByTwoPiercesStaysWhileOneRemains(self):
        point = self.addPoint(0, 0)
        other = self.addPoint(1, 1)
        first = self.sketch.addPierce(point, START, self.pole, "Edge1")
        self.sketch.addPierce(other, START, self.pole, "Edge1")
        self.assertEqual(self.links(), [("Pole", "Edge1")])
        self.sketch.delConstraint(first)
        self.assertEqual(self.sketch.delUnusedImplicitExternals(), 0)
        self.assertEqual(self.links(), [("Pole", "Edge1")])
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(other, 2, 3)

    def testTheUsersOwnIntersectionLinkIsReusedAndKept(self):
        """An Intersection link the user made gives the crossing; it isn't a helper, so it stays
        when the Pierce goes."""
        self.sketch.addExternal(self.pole.Name, "Edge1", False, True)
        self.doc.recompute()
        point = self.addPoint(0, 0)
        index = self.sketch.addPierce(point, START, self.pole, "Edge1")
        self.assertEqual(self.links(), [("Pole", "Edge1")])
        self.assertEqual(list(self.sketch.ExternalTypes), [INTERSECTION])
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(point, 2, 3)
        self.sketch.delConstraint(index)
        self.assertEqual(self.sketch.delUnusedImplicitExternals(), 0)
        self.assertEqual(self.links(), [("Pole", "Edge1")])

    def testACurveThatStopsCrossingFailsTheSketchAndPinsNothingElsewhere(self):
        """A circle of radius 2 about (2, 3, 0) in the XZ plane, crossing at (0, 3) and (4, 3),
        then lifted clear of the plane (its centre at z = 20): its crossing's geometry is kept
        where it was, flagged missing, and the sketch fails naming the reference, as for any
        external geometry that loses its source (Onshape: a warning, the points left where they
        are); lowered again, it is whole and the point at the same crossing."""
        ring = self.addEdge("Ring", Part.makeCircle(2, V(2, 3, 0), V(0, 1, 0)))
        point = self.addPoint(2, 0)
        self.sketch.addPierce(point, START, ring, "Edge1")
        self.doc.recompute()
        at = self.sketch.getPoint(point, START)
        self.assertAlmostEqual(at.y, 3, delta=TOL)
        self.assertAlmostEqual(abs(at.x - 2), 2, delta=TOL)
        ring.Placement = App.Placement(V(0, 0, 20), App.Rotation())
        self.doc.recompute()
        self.assertFalse(self.sketch.isValid())
        self.assertIn("Ring", self.sketch.getStatusString())
        self.assertAt(point, at.x, at.y)
        self.assertEqual([c.Type for c in self.sketch.Constraints], ["Pierce"])
        ring.Placement = App.Placement(V(1, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.assertAt(point, at.x + 1, at.y)

    def testSaveAndReopenKeepsThePierce(self):
        point = self.addPoint(0, 0)
        self.sketch.addPierce(point, START, self.pole, "Edge1")
        self.doc.recompute()
        path = os.path.join(tempfile.mkdtemp(), "Pierce.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        del self.doc
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        self.assertEqual([c.Type for c in sketch.Constraints], ["Pierce"])
        self.assertEqual(list(sketch.ExternalTypes), [INTERSECTION | IMPLICIT | PIERCE])
        self.assertAt(point, 2, 3, sketch=sketch)
        sketch.touch()
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertEqual(sketch.solve(), 0)
        self.assertAt(point, 2, 3, sketch=sketch)
        # and it still follows the edge
        self.doc.getObject("Pole").Placement = App.Placement(V(-2, 1, 0), App.Rotation())
        self.doc.recompute()
        self.assertAt(point, 0, 4, sketch=sketch)

    def assertThrough(self, lineGeoId, x, y):
        """The line's infinite extension passes through (x, y)."""
        line = self.sketch.Geometry[lineGeoId]
        d = line.EndPoint - line.StartPoint
        v = V(x, y, 0) - line.StartPoint
        self.assertAlmostEqual(d.cross(v).Length / d.Length, 0, delta=TOL)

    def testALineAsTheLocalEntitySlidesItsExtensionThroughTheCrossing(self):
        """Onshape's Pierce of a line: its extension passes through the crossing, the line moved
        keeping its direction and length. The diagonal (0, 0)-(3, 3) and the crossing (2, 3): the
        line slides by (-0.5, 0.5) along its normal, to (-0.5, 0.5)-(2.5, 3.5)."""
        line = self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(3, 3, 0)))
        index = self.sketch.addPierce(line, NONE, self.pole, "Edge1")
        constraint = self.sketch.Constraints[index]
        self.assertEqual(len(self.sketch.Constraints), 1)
        self.assertEqual(constraint.Type, "Pierce")
        self.assertEqual(constraint.First, line)
        self.assertEqual(constraint.FirstPos, NONE)
        self.assertLess(constraint.Second, -2)
        self.assertEqual(self.sketch.solve(), 0)
        self.assertThrough(line, 2, 3)
        self.assertAt(line, -0.5, 0.5, START)
        self.assertAt(line, 2.5, 3.5, END)
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.assertThrough(line, 2, 3)
        # the edge moved: the extension follows the crossing
        self.pole.Placement = App.Placement(V(4, -1, 0), App.Rotation())
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.assertThrough(line, 6, 2)

    def testALinePastTheCrossingKeepsItsLength(self):
        """The vertical (0, 0)-(0, 1) and the crossing (2, 3), beyond its end: the line slides to
        x = 2 and stays (2, 0)-(2, 1), the crossing on its extension, not on the segment."""
        line = self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, 1, 0)))
        self.sketch.addPierce(line, NONE, self.pole, "Edge1")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertAt(line, 2, 0, START)
        self.assertAt(line, 2, 1, END)

    def testACircleAsTheLocalEntityPassesThroughTheCrossing(self):
        """A circle of radius 1 about the origin: it slides along the line to the crossing (2, 3)
        until its circle passes through it, radius kept."""
        circle = self.sketch.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 1))
        self.sketch.addPierce(circle, NONE, self.pole, "Edge1")
        self.assertEqual(self.sketch.solve(), 0)
        c = self.sketch.Geometry[circle]
        self.assertAlmostEqual(c.Radius, 1, delta=TOL)
        self.assertAlmostEqual((c.Center - V(2, 3, 0)).Length, 1, delta=TOL)

    def testAnUnsupportedEntityIsRefusedWithItsReason(self):
        """An ellipse as the local entity: Pierce takes a point, a line, a circle or an arc."""
        ellipse = self.sketch.addGeometry(Part.Ellipse(V(0, 0, 0), 4, 2))
        with self.assertRaisesRegex(Exception, "a point, a line, a circle or an arc"):
            self.sketch.addPierce(ellipse, NONE, self.pole, "Edge1")
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(self.links(), [])

    def testTheConstraintFromPython(self):
        """Sketcher.Constraint('Pierce', point, pos, external): the crossing's own point."""
        constraint = Sketcher.Constraint("Pierce", 0, START, -3)
        self.assertEqual(constraint.Type, "Pierce")
        self.assertEqual(constraint.First, 0)
        self.assertEqual(constraint.FirstPos, START)
        self.assertEqual(constraint.Second, -3)
        self.assertEqual(constraint.SecondPos, START)
