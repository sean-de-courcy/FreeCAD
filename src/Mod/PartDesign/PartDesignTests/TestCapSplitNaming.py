# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: a pick on an edge a cut makes in a cap face survives a split of the cap's profile
# (ops#849).

"""A chamfer on a pocket's rim survives a Sketcher split of the plate's sketch, as in Onshape.

Designed geometry: a plate 60 x 40 x 10 padded from a sketch at z = 0; a pocket 10 x 10 cut 4 mm
into the plate's top from a sketch on a plane 4 mm above it (z = 14, length 8), and another
10 x 10 cut 4 mm into its bottom from a sketch 4 mm below it (z = -4, facing down, length 8); a
1 mm Chamfer on the eight rim edges (four at z = 10, four at z = 0). The pockets' sketches lie off
the plate, so each rim edge is an edge the cut generates between a pocket's side and one of the
pad's caps, and is named after those two faces.

A cap is named after its whole profile (the bottom: the face made of the sketch's edges; the top:
that face, extruded). Splitting the plate sketch's bottom edge in two collinear pieces changes no
geometry, but renames both caps and with them all eight rim edges, although they are far from the
split. The chamfer as a studio owner (the GUI's path) lost every pick: red, "a picked edge is not
found". The expected solid is the unedited model's: the reference is a second document built the
same way and never edited. The same holds the other way round, for a profile drawn with the
bottom edge in two pieces that are then joined into one."""

import unittest

import FreeCAD
import Part
import PartDesign
import Sketcher

App = FreeCAD
V = App.Vector

LX, LY, ZT = 60.0, 40.0, 10.0
SIDE, DEPTH, OFF = 10.0, 4.0, 4.0
TOP_AT = (14.0, -12.0)  # the top pocket's corner (x, y)
BOTTOM_AT = (-24.0, 2.0)  # the bottom pocket's corner (x, y), in model coordinates
EPS = 1e-6


def rect(sketch, x, y, w, h, pieces=1):
    """A rectangle whose bottom edge is one line, or two collinear ones (`pieces` = 2) meeting
    3.5 mm from its start. The sizes sit on the top and right edges, the place on the first
    corner, so the bottom edge can be split and joined without touching a dimension."""
    pts = [V(x, y, 0), V(x + w, y, 0), V(x + w, y + h, 0), V(x, y + h, 0)]
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
    sketch.addConstraint(Sketcher.Constraint("DistanceX", 2, 2, 2, 1, w))
    sketch.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, h))
    if pieces == 2:
        split(sketch)


def split(sketch):
    """Sketcher's split tool on the first edge (the bottom one), 3.5 mm from its start: the edge
    keeps its id as the first piece, the second piece is new."""
    start = sketch.Geometry[0].StartPoint
    count = len(sketch.Geometry)
    sketch.split(0, V(start.x + 3.5, start.y, 0))
    assert len(sketch.Geometry) == count + 1


def join(sketch):
    """The split undone as a user does it: the second piece deleted, the first one's end put
    back on the corner."""
    end = sketch.Geometry[0].EndPoint
    second = [
        i
        for i, g in enumerate(sketch.Geometry)
        if i != 0 and (g.StartPoint - end).Length < EPS and abs(g.EndPoint.y - end.y) < EPS
    ]
    assert len(second) == 1 and second[0] > 1, second
    sketch.delGeometry(second[0])
    sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))


def rimNames(doc):
    """The names of the eight rim edges in the shape the chamfer works on, sorted."""
    step = doc.getObject("BottomPocket_at_Part") or doc.getObject("BottomPocket")
    shape = step.Shape
    return sorted(
        shape.getElementName(f"Edge{i}", 1)
        for i, e in enumerate(shape.Edges, 1)
        if (all(abs(v.Point.z - ZT) < EPS for v in e.Vertexes) and inRim(e.CenterOfMass, TOP_AT))
        or (all(abs(v.Point.z) < EPS for v in e.Vertexes) and inRim(e.CenterOfMass, BOTTOM_AT))
    )


def inRim(point, at, margin=EPS):
    return (
        at[0] - margin < point.x < at[0] + SIDE + margin
        and at[1] - margin < point.y < at[1] + SIDE + margin
    )


def build(name, owners, pieces=1):
    """The model; with `owners` the pockets and the Chamfer are studio owners outside the Body
    (what the GUI makes), else Body members. `pieces`: of the plate sketch's bottom edge."""
    doc = App.newDocument(name)
    doc.UndoMode = 0
    body = doc.addObject("PartDesign::Body", "Part")
    PartDesign.studioList(doc, True)
    xy = body.Origin.OriginFeatures[3]

    def sketch(name, placement):
        s = body.newObject("Sketcher::SketchObject", name)
        s.AttachmentSupport = [(xy, "")]
        s.MapMode = "FlatFace"
        s.AttachmentOffset = placement
        PartDesign.studioInsert(s, -1)
        return s

    def feature(kind, name, owner=False, **props):
        if owner:
            f = doc.addObject("PartDesign::" + kind, name)
            f.StudioScope = [body.StudioPartId or body.Name]
        else:
            f = body.newObject("PartDesign::" + kind, name)
        for key, value in props.items():
            setattr(f, key, value)
        PartDesign.studioInsert(f, -1)
        doc.recompute()
        return f

    s = sketch("PlateSk", App.Placement())
    rect(s, -LX / 2, -LY / 2, LX, LY, pieces)
    feature("Pad", "Plate", Profile=s, Length=ZT)
    s = sketch("TopSk", App.Placement(V(0, 0, ZT + OFF), App.Rotation()))
    rect(s, TOP_AT[0], TOP_AT[1], SIDE, SIDE)
    feature("Pocket", "TopPocket", owner=owners, Profile=s, Length=OFF + DEPTH)
    # Facing down: turned half round about x, so the sketch's y is the model's -y
    s = sketch("BottomSk", App.Placement(V(0, 0, -OFF), App.Rotation(V(1, 0, 0), 180)))
    rect(s, BOTTOM_AT[0], -BOTTOM_AT[1] - SIDE, SIDE, SIDE)
    feature("Pocket", "BottomPocket", owner=owners, Profile=s, Length=OFF + DEPTH)
    # An owner's result is the step it made in the part: the Body's tip, as the GUI picks
    tip = body.Tip
    rim = [
        f"Edge{i}"
        for i, e in enumerate(tip.Shape.Edges, 1)
        if (
            all(abs(v.Point.z - ZT) < EPS for v in e.Vertexes) and inRim(e.CenterOfMass, TOP_AT)
        )
        or (all(abs(v.Point.z) < EPS for v in e.Vertexes) and inRim(e.CenterOfMass, BOTTOM_AT))
    ]
    assert len(rim) == 8, rim
    if owners:
        chamfer = doc.addObject("PartDesign::Chamfer", "Chamfer")
        chamfer.StudioPickIds = [PartDesign.studioPickId(tip, n) for n in rim]
        chamfer.Size = 1
        PartDesign.studioInsert(chamfer, -1)
        doc.recompute()
    else:
        feature("Chamfer", "Chamfer", Base=(tip, rim), Size=1)
    return doc


class _RimThroughProfileEdit:
    OWNERS = False

    def setUp(self):
        self.doc = None
        self.ref = build("TestCapSplitNamingRef", self.OWNERS)

    def tearDown(self):
        if self.doc:
            App.closeDocument(self.doc.Name)
        App.closeDocument(self.ref.Name)

    def volume(self, doc):
        return doc.getObject("Part").Shape.Volume

    def check(self):
        """Nothing in error, the chamfer on all eight rim edges, the solid the unedited model's."""
        bad = {
            o.Name: o.getStatusString()
            for o in self.doc.Objects
            if "Invalid" in o.State or "Error" in o.State
        }
        self.assertEqual(bad, {})
        shape = self.doc.getObject("Part").Shape
        # Each chamfered rim edge leaves a 45 degree bevel, 1 mm into the cap and 1 mm down the
        # pocket's side
        bevels = [
            f
            for f in shape.Faces
            if abs(abs(f.normalAt(0, 0).z) - 0.5**0.5) < EPS
            and (
                (abs(f.BoundBox.ZMax - ZT) < EPS and inRim(f.CenterOfMass, TOP_AT, 1))
                or (abs(f.BoundBox.ZMin) < EPS and inRim(f.CenterOfMass, BOTTOM_AT, 1))
            )
        ]
        self.assertEqual(len(bevels), 8)
        self.assertAlmostEqual(self.volume(self.doc), self.volume(self.ref), places=5)

    def testBuilt(self):
        """Before any edit: the chamfer is on all eight rim edges, and takes material off."""
        self.doc = build("TestCapSplitNaming", self.OWNERS)
        self.check()
        # Each rim loses a 1 x 1 triangle along its 4 x 10 mm, and gains the corners' pyramids
        self.assertLess(self.volume(self.doc), LX * LY * ZT - 2 * SIDE * SIDE * DEPTH - 2 * 20)

    def testSplit(self):
        """The profile gains an edge."""
        self.doc = build("TestCapSplitNaming", self.OWNERS)
        before = rimNames(self.doc)
        self.assertEqual(len(before), 8)
        split(self.doc.getObject("PlateSk"))
        self.doc.recompute()
        self.assertEqual(len(self.doc.getObject("PlateSk").Geometry), 5)
        # What this test is about: the split renames every rim edge (were the caps named another
        # way one day, the picks would hold by their own names and this test would say nothing)
        after = rimNames(self.doc)
        self.assertEqual(len(after), 8)
        self.assertEqual(set(before) & set(after), set())
        self.check()

    def testSplitAndDepthInOneRecompute(self):
        self.doc = build("TestCapSplitNaming", self.OWNERS)
        split(self.doc.getObject("PlateSk"))
        for doc in (self.doc, self.ref):
            doc.getObject("TopPocket").Length = OFF + DEPTH + 1.25
            doc.recompute()
        self.check()

    def testSplitThenJoined(self):
        """And back: the names are the first ones again."""
        self.doc = build("TestCapSplitNaming", self.OWNERS)
        split(self.doc.getObject("PlateSk"))
        self.doc.recompute()
        join(self.doc.getObject("PlateSk"))
        self.doc.recompute()
        self.assertEqual(len(self.doc.getObject("PlateSk").Geometry), 4)
        self.check()

    def testJoin(self):
        """The profile loses an edge: drawn in five edges, picked, then joined into four."""
        self.doc = build("TestCapSplitNaming", self.OWNERS, pieces=2)
        self.check()
        join(self.doc.getObject("PlateSk"))
        self.doc.recompute()
        self.assertEqual(len(self.doc.getObject("PlateSk").Geometry), 4)
        self.check()


class TestCapRimThroughProfileEditOwners(_RimThroughProfileEdit, unittest.TestCase):
    """Studio owners, as the GUI builds them: the chamfer's picks are studio pick ids."""

    OWNERS = True


class TestCapRimThroughProfileEditBody(_RimThroughProfileEdit, unittest.TestCase):
    """Body members: the chamfer's picks are a link's sub-elements."""

    OWNERS = False


if __name__ == "__main__":
    unittest.main()
