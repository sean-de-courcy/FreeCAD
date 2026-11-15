# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: a pick on a pad's corner edge survives a split of a sketch edge that ends at the
# corner (ops#852).

"""A fillet on a plate's four corner edges survives a Sketcher split of the plate's sketch, as in
Onshape.

Designed geometry: a plate LX x LY x ZT padded from a rectangle sketched at z = 0, and a Fillet of
radius R on its four vertical corner edges. Each rounded corner takes (1 - pi/4) R^2 ZT off the
plate, so the solid's volume is known: LX LY ZT - n (1 - pi/4) R^2 ZT for n rounded corners.

A corner edge is the extrusion of a sketch vertex, and a sketch vertex is named after the edge
ends that meet there (`g1v2` and `g2v1`: the first edge's end and the second one's start).
Sketcher's split keeps the edge's id on its first piece; the second piece is new and takes the
old end, so the corner at the split edge's end is renamed (`g2v1` and `g5v2`) although nothing
there moved. The pad joins the two collinear side faces again, so the split point makes no edge.
The fillet as a studio owner (the GUI's path) lost that pick: three corners rounded, a warning,
another volume.

The rule (NameAncestry, loose sketch vertices): a sketch vertex that keeps one of its edge ends
is the picked one when no other vertex of the part does. Where the corner is cut off by a new
sketch line, two vertices each keep one end: the pick is not found (a warning, the other corners
rounded), never guessed."""

import math
import unittest

import FreeCAD
import Part
import PartDesign
import Sketcher

App = FreeCAD
V = App.Vector

LX, LY, ZT, R = 60.0, 40.0, 10.0, 4.0
CUT = 9.0  # the legs of the triangle the new sketch line cuts off a corner
EPS = 1e-6


def volume(corners, height=ZT, cutOff=False):
    """The plate's volume with `corners` of them rounded; `cutOff`: one corner cut by the line."""
    full = LX * LY - (CUT * CUT / 2 if cutOff else 0.0)
    return (full - corners * (1 - math.pi / 4) * R * R) * height


def rect(sketch, pieces=1):
    """The rectangle, its first edge the bottom one (left to right), then the right, top and
    left ones. The sizes sit on the top and left edges and the place on the first corner, so
    the bottom and right edges can be split, joined and shortened without touching a dimension.
    `pieces` = 2: the bottom edge drawn as two collinear lines (by the split)."""
    x, y = -LX / 2, -LY / 2
    pts = [V(x, y, 0), V(x + LX, y, 0), V(x + LX, y + LY, 0), V(x, y + LY, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    for g in (0, 2):
        sketch.addConstraint(Sketcher.Constraint("Horizontal", g))
    for g in (1, 3):
        sketch.addConstraint(Sketcher.Constraint("Vertical", g))
    sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, x))
    sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, y))
    sketch.addConstraint(Sketcher.Constraint("DistanceX", 2, 2, 2, 1, LX))
    sketch.addConstraint(Sketcher.Constraint("DistanceY", 3, 2, 3, 1, LY))
    if pieces == 2:
        split(sketch)


def split(sketch, edge=0):
    """Sketcher's split tool on an edge, 3.5 mm from its start: the edge keeps its id as the
    first piece, the second piece is new and ends at the old end."""
    line = sketch.Geometry[edge]
    along = (line.EndPoint - line.StartPoint).normalize()
    count = len(sketch.Geometry)
    sketch.split(edge, line.StartPoint + along * 3.5)
    assert len(sketch.Geometry) == count + 1


def join(sketch):
    """The bottom edge's split undone as a user does it: the second piece deleted, the first
    one's end put back on the corner."""
    end = sketch.Geometry[0].EndPoint
    second = [
        i
        for i, g in enumerate(sketch.Geometry)
        if i != 0 and (g.StartPoint - end).Length < EPS and abs(g.EndPoint.y - end.y) < EPS
    ]
    assert len(second) == 1 and second[0] > 1, second
    sketch.delGeometry(second[0])
    sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))


def cutCorner(sketch):
    """The corner between the bottom and the right edge cut off by a new line: both edges are
    shortened by CUT and the line joins their ends. The old corner's two edge ends now lie on
    two vertices, CUT apart."""
    for i, c in enumerate(sketch.Constraints):
        if c.Type == "Coincident" and (c.First, c.FirstPos, c.Second, c.SecondPos) == (0, 2, 1, 1):
            sketch.delConstraint(i)
            break
    else:
        raise AssertionError("the corner's coincidence is not found")
    sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, LX - CUT))
    sketch.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, LY - CUT))
    a, b = sketch.Geometry[0].EndPoint, sketch.Geometry[1].StartPoint
    new = sketch.addGeometry(Part.LineSegment(a, b), False)
    sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, new, 1))
    sketch.addConstraint(Sketcher.Constraint("Coincident", new, 2, 1, 1))


def isCorner(edge):
    """Whether the edge is one of the plate's vertical corner edges."""
    p = [v.Point for v in edge.Vertexes]
    return (
        len(p) == 2
        and abs(abs(p[0].x) - LX / 2) < EPS
        and abs(abs(p[0].y) - LY / 2) < EPS
        and abs(p[0].x - p[1].x) < EPS
        and abs(p[0].y - p[1].y) < EPS
    )


def cornerNames(doc):
    """The names of the corner edges in the shape the fillet works on, by corner (signs of x, y)."""
    shape = doc.getObject("Plate").Shape
    return {
        (e.CenterOfMass.x > 0, e.CenterOfMass.y > 0): shape.getElementName(f"Edge{i}", 1)
        for i, e in enumerate(shape.Edges, 1)
        if isCorner(e)
    }


def build(name, owners, pieces=1, refine=True):
    """The model; with `owners` the Fillet is a studio owner outside the Body (what the GUI
    makes), else a Body member. `pieces`: of the plate sketch's bottom edge. `refine`: the
    pad's Refine (the default follows a user preference, so it is always set)."""
    doc = App.newDocument(name)
    doc.UndoMode = 0
    body = doc.addObject("PartDesign::Body", "Part")
    PartDesign.studioList(doc, True)
    s = body.newObject("Sketcher::SketchObject", "PlateSk")
    s.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
    s.MapMode = "FlatFace"
    PartDesign.studioInsert(s, -1)
    rect(s, pieces)
    pad = body.newObject("PartDesign::Pad", "Plate")
    pad.Profile = s
    pad.Length = ZT
    pad.Refine = refine
    PartDesign.studioInsert(pad, -1)
    doc.recompute()
    corners = [f"Edge{i}" for i, e in enumerate(pad.Shape.Edges, 1) if isCorner(e)]
    assert len(corners) == 4, corners
    if owners:
        fillet = doc.addObject("PartDesign::Fillet", "Fillet")
        fillet.StudioPickIds = [PartDesign.studioPickId(pad, n) for n in corners]
        fillet.Radius = R
    else:
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, corners)
        fillet.Radius = R
    PartDesign.studioInsert(fillet, -1)
    doc.recompute()
    return doc


class _CornerThroughSketchEdit:
    OWNERS = False

    def setUp(self):
        self.doc = None

    def tearDown(self):
        if self.doc:
            App.closeDocument(self.doc.Name)

    def build(self, pieces=1, refine=True):
        self.doc = build("TestCornerSplitNaming", self.OWNERS, pieces, refine)
        return self.doc.getObject("PlateSk")

    def rounded(self):
        """The fillet's faces in the part: vertical cylinders of radius R."""
        return [
            f
            for f in self.doc.getObject("Part").Shape.Faces
            if isinstance(f.Surface, Part.Cylinder)
            and abs(f.Surface.Radius - R) < EPS
            and abs(abs(f.Surface.Axis.z) - 1) < EPS
        ]

    def check(self, height=ZT):
        """Nothing in error, all four corners rounded, the solid's volume the designed one."""
        bad = {
            o.Name: o.getStatusString()
            for o in self.doc.Objects
            if "Invalid" in o.State or "Error" in o.State
        }
        self.assertEqual(bad, {})
        self.assertEqual(len(self.rounded()), 4)
        self.assertAlmostEqual(
            self.doc.getObject("Part").Shape.Volume, volume(4, height), places=5
        )

    def testBuilt(self):
        self.build()
        self.check()

    def testSplit(self):
        """The bottom edge split: the corner at its end is renamed, the fillet stays on it."""
        sketch = self.build()
        before = cornerNames(self.doc)
        self.assertEqual(len(before), 4)
        split(sketch)
        self.doc.recompute()
        self.assertEqual(len(sketch.Geometry), 5)
        after = cornerNames(self.doc)
        self.assertEqual(len(after), 4)
        # What this test is about: the split renames the corner at the split edge's end, and
        # only that one (were vertices named another way one day, this test would say nothing)
        self.assertEqual([k for k in before if before[k] != after[k]], [(True, False)])
        self.check()

    def testSplitAndHeightInOneRecompute(self):
        sketch = self.build()
        split(sketch)
        self.doc.getObject("Plate").Length = ZT + 2.5
        self.doc.recompute()
        self.check(ZT + 2.5)

    def testTwoEdgesSplit(self):
        """The bottom and the right edge split, one recompute each: two corners renamed."""
        sketch = self.build()
        before = cornerNames(self.doc)
        split(sketch, 0)
        self.doc.recompute()
        self.check()
        split(sketch, 1)
        self.doc.recompute()
        self.assertEqual(len(sketch.Geometry), 6)
        after = cornerNames(self.doc)
        self.assertEqual(
            sorted(k for k in before if before[k] != after[k]), [(True, False), (True, True)]
        )
        self.check()

    def testSplitThenJoined(self):
        """And back: the names are the first ones again."""
        sketch = self.build()
        before = cornerNames(self.doc)
        split(sketch)
        self.doc.recompute()
        join(sketch)
        self.doc.recompute()
        self.assertEqual(len(sketch.Geometry), 4)
        self.assertEqual(cornerNames(self.doc), before)
        self.check()

    def testJoin(self):
        """The sketch loses an edge: drawn in five edges, picked, then joined into four."""
        sketch = self.build(pieces=2)
        self.check()
        join(sketch)
        self.doc.recompute()
        self.assertEqual(len(sketch.Geometry), 4)
        self.check()


class TestCornerThroughSketchEditOwners(_CornerThroughSketchEdit, unittest.TestCase):
    """A studio owner, as the GUI builds it: the fillet's picks are studio pick ids."""

    OWNERS = True

    def testCornerCutOff(self):
        """A new sketch line cuts the corner off: its two edge ends are on two vertices now, so
        the pick is on neither. The other three corners stay rounded, and the owner warns."""
        sketch = self.build()
        cutCorner(sketch)
        self.doc.recompute()
        self.assertEqual(len(sketch.Geometry), 5)
        fillet = self.doc.getObject("Fillet")
        self.assertNotIn("Invalid", fillet.State)
        self.assertIn("a picked edge is not found", fillet.getStatusString())
        self.assertEqual(len(self.rounded()), 3)
        self.assertAlmostEqual(
            self.doc.getObject("Part").Shape.Volume, volume(3, cutOff=True), places=5
        )

    def testSplitUnrefined(self):
        """A pad that doesn't refine keeps an edge at the split point, whose vertex keeps the
        old corner's other edge end: two candidates, so the pick is not found."""
        sketch = self.build(refine=False)
        self.check()
        split(sketch)
        self.doc.recompute()
        fillet = self.doc.getObject("Fillet")
        self.assertNotIn("Invalid", fillet.State)
        self.assertIn("a picked edge is not found", fillet.getStatusString())
        # Three corners rounded, by the volume alone: the split point is nearer the first corner
        # than R, so that corner's fillet runs over it and its face is no plain cylinder
        self.assertAlmostEqual(self.doc.getObject("Part").Shape.Volume, volume(3), places=5)


class TestCornerThroughSketchEditBody(_CornerThroughSketchEdit, unittest.TestCase):
    """A Body member: the fillet's picks are a link's sub-elements."""

    OWNERS = False


if __name__ == "__main__":
    unittest.main()
