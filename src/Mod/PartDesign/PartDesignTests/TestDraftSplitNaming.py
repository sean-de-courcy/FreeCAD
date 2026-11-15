# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: a Draft's output keeps its edges' lineage when the profile sketch is split (ops#845).

"""A chamfer on a drafted boss's rim survives a Sketcher split of the boss sketch, as in Onshape.

Designed geometry: a plate 60 x 40 x 10; a boss 10 x 10 x 6 padded from a sketch on the plate's
top (z = 10); a Draft on the boss's four sides about the boss's top face (the rim keeps its
10 x 10 square); a 1 mm Chamfer on the rim's four edges. Splitting the sketch's bottom edge in two
collinear pieces changes no geometry, so the expected solid is the unsplit model's, at the same
draft angle: the reference is a second document built the same way and never split.

The draft's rim edges used to be named after the faces around them, and the boss's top face is
named after the whole profile: the split renamed the top face, with it all four rim edges, and
the chamfer lost every pick (studio owners, the GUI's path: red, "a picked edge is not found"),
or found them again by position only until the same recompute also changed the draft's angle
(Body members: red, ambiguous references)."""

import math
import unittest

import FreeCAD
import Part
import PartDesign
import Sketcher

App = FreeCAD
V = App.Vector

X0, Y0, SIDE, ZB, HEIGHT = 14.0, -12.0, 10.0, 10.0, 6.0
ZT = ZB + HEIGHT
EPS = 1e-6


def rect(sketch, x, y, w, h):
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
    sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, w))
    sketch.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, h))


def overBoss(point, margin=EPS):
    return (
        X0 - margin < point.x < X0 + SIDE + margin and Y0 - margin < point.y < Y0 + SIDE + margin
    )


def build(name, owners):
    """The model; with `owners` the boss Pad and the Chamfer are studio owners outside the Body
    (what the GUI makes), else Body members."""
    doc = App.newDocument(name)
    doc.UndoMode = 0
    body = doc.addObject("PartDesign::Body", "Part")
    PartDesign.studioList(doc, True)
    xy = body.Origin.OriginFeatures[3]

    def sketch(name, z):
        s = body.newObject("Sketcher::SketchObject", name)
        s.AttachmentSupport = [(xy, "")]
        s.MapMode = "FlatFace"
        s.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
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

    s = sketch("PlateSk", 0)
    rect(s, -30, -20, 60, 40)
    feature("Pad", "Plate", Profile=s, Length=ZB)
    s = sketch("BossSk", ZB)
    rect(s, X0, Y0, SIDE, SIDE)
    boss = feature("Pad", "Boss", owner=owners, Profile=s, Length=HEIGHT)
    # An owner's result is the step it made in the part: the Body's tip, as the GUI picks
    src = body.Tip if owners else boss
    shape = src.Shape
    sides = [
        f"Face{i}"
        for i, f in enumerate(shape.Faces, 1)
        if abs(f.normalAt(0, 0).z) < EPS and f.BoundBox.ZMin > ZB - EPS and overBoss(f.CenterOfMass)
    ]
    top = [
        f"Face{i}"
        for i, f in enumerate(shape.Faces, 1)
        if abs(f.normalAt(0, 0).z - 1) < EPS and abs(f.CenterOfMass.z - ZT) < EPS
    ]
    assert len(sides) == 4 and len(top) == 1, (sides, top)
    feature("Draft", "Draft", Base=(src, sides), NeutralPlane=(src, top), Angle=3)
    tip = body.Tip
    rim = [
        f"Edge{i}"
        for i, e in enumerate(tip.Shape.Edges, 1)
        if all(abs(v.Point.z - ZT) < EPS for v in e.Vertexes) and overBoss(e.CenterOfMass, 1)
    ]
    assert len(rim) == 4, rim
    if owners:
        chamfer = doc.addObject("PartDesign::Chamfer", "Chamfer")
        chamfer.StudioPickIds = [PartDesign.studioPickId(tip, n) for n in rim]
        chamfer.Size = 1
        PartDesign.studioInsert(chamfer, -1)
        doc.recompute()
    else:
        feature("Chamfer", "Chamfer", Base=(tip, rim), Size=1)
    return doc


def split(doc):
    """Sketcher's split tool on the boss sketch's bottom edge, 3.5 mm from its start."""
    doc.getObject("BossSk").split(0, V(X0 + 3.5, Y0, 0))


class _RimThroughSplit:
    OWNERS = False

    def setUp(self):
        self.doc = build("TestDraftSplitNaming", self.OWNERS)
        self.ref = build("TestDraftSplitNamingRef", self.OWNERS)

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        App.closeDocument(self.ref.Name)

    def volume(self, doc):
        return doc.getObject("Part").Shape.Volume

    def check(self):
        """Nothing in error, the chamfer on all four rim edges, the solid the unsplit model's."""
        bad = {
            o.Name: o.getStatusString()
            for o in self.doc.Objects
            if "Invalid" in o.State or "Error" in o.State
        }
        self.assertEqual(bad, {})
        shape = self.doc.getObject("Part").Shape
        # Each chamfered rim edge leaves a bevel from the boss's top down the drafted side: 1 mm
        # along the side, so a little under 1 mm in z
        bevels = [
            f
            for f in shape.Faces
            if abs(f.BoundBox.ZMax - ZT) < EPS
            and ZT - 1 - EPS < f.BoundBox.ZMin < ZT - 0.9
            and overBoss(f.CenterOfMass, 1)
        ]
        self.assertEqual(len(bevels), 4)
        self.assertAlmostEqual(self.volume(self.doc), self.volume(self.ref), places=5)

    def testBuilt(self):
        """Before any edit: the chamfer is on all four rim edges, and takes material off."""
        self.check()
        frustum = HEIGHT / 3 * (SIDE**2 + SIDE * self.base() + self.base() ** 2)
        self.assertLess(self.volume(self.doc), 60 * 40 * ZB + frustum - 1)

    def base(self):
        """The drafted boss's side length at the plate (3 degrees about its top)."""
        return SIDE + 2 * HEIGHT * math.tan(math.radians(3))

    def testSplitAlone(self):
        split(self.doc)
        self.doc.recompute()
        self.check()

    def testSplitAndAngleInOneRecompute(self):
        split(self.doc)
        self.doc.getObject("Draft").Angle = 5.45
        self.doc.recompute()
        self.ref.getObject("Draft").Angle = 5.45
        self.ref.recompute()
        self.check()

    def testSplitThenAngle(self):
        split(self.doc)
        self.doc.recompute()
        self.doc.getObject("Draft").Angle = 5.45
        self.doc.recompute()
        self.ref.getObject("Draft").Angle = 5.45
        self.ref.recompute()
        self.check()

    def testAngleThenSplit(self):
        self.doc.getObject("Draft").Angle = 5.45
        self.doc.recompute()
        split(self.doc)
        self.doc.recompute()
        self.ref.getObject("Draft").Angle = 5.45
        self.ref.recompute()
        self.check()


class TestDraftRimThroughSplitOwners(_RimThroughSplit, unittest.TestCase):
    """Studio owners, as the GUI builds them: the chamfer's picks are studio pick ids."""

    OWNERS = True


class TestDraftRimThroughSplitBody(_RimThroughSplit, unittest.TestCase):
    """Body members: the chamfer's picks are a link's sub-elements."""

    OWNERS = False


if __name__ == "__main__":
    unittest.main()
