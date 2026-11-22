# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#919, notes/surface-upto-split-919.md 8)

"""A surface extruded from picked edges of a sketch up to a face, and a part split by that
sheet: `Part::Extrusion`'s `BaseEdges`, `EndType` UpToFace and `UpToFace`, and
`PartDesign.split` with a sheet in no Body as its tool.

Designed geometry: a block x 0..40, y 0..30, z 0..20 (24000); one sketch on z = 0 with a regular
hexagon of circumradius 8 centred (20, 15) (area 3 sqrt(3) / 2 * 64 = 166.2769) and an open
polyline (5, -5), (15, 15), (25, 15), (35, 35). The hexagon up to the block's top is a closed
tube of six faces 8 x 20 (960); split by it, the block gives the plug 20 x 166.2769 = 3325.5376
(8 faces) and the block with a six-sided hole, 20674.4624 (12 faces). Onshape gives the same
(ops#919 comment 7069649714, SU1 and SU5). Oracles are areas, volumes, face counts and boxes;
the slanted case is checked against an independent construction of each piece."""

import math
import unittest

import FreeCAD as App
import Part
import PartDesign

V = App.Vector

BLOCK = 24000.0
HEXAGON = 3 * math.sqrt(3) / 2 * 64
PLUG = 20 * HEXAGON
HOLED = BLOCK - PLUG


def hexagon(clockwise=False, cx=20.0, cy=15.0, r=8.0):
    points = [
        V(cx + r * math.cos(k * math.pi / 3), cy + r * math.sin(k * math.pi / 3), 0)
        for k in range(6)
    ]
    if clockwise:
        points.reverse()
    return points + [points[0]]


POLYLINE = [V(5, -5, 0), V(15, 15, 0), V(25, 15, 0), V(35, 35, 0)]


def box(shape):
    return shape.optimalBoundingBox(False, False)


def near(point, points, tol=1e-6):
    return any(point.distanceToPoint(p) <= tol for p in points)


class TestSurfaceUpToSplit(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestSurfaceUpToSplit")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    # --- the model ---------------------------------------------------------------------------

    def block(self, height=20, slot=False):
        self.body = self.doc.addObject("PartDesign::Body", "Block")
        self.body.Label = "Block"
        self.box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        self.box.Length, self.box.Width, self.box.Height = 40, 30, height
        if slot:
            # A through slot x 18..22, y 14..30: the polyline sheet cuts the block in three
            cut = self.body.newObject("PartDesign::SubtractiveBox", "Slot")
            cut.Length, cut.Width, cut.Height = 4, 20, height + 2
            cut.Placement = App.Placement(V(18, 14, -1), App.Rotation())
        self.doc.recompute()
        return self.body

    def faceOf(self, feature, test):
        for i, face in enumerate(feature.Shape.Faces, 1):
            if test(face):
                return f"Face{i}"
        self.fail(f"no such face on {feature.Label}")

    def top(self, feature, z=None):
        def test(face):
            normal = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
            return normal.z > 1 - 1e-9 and (z is None or abs(face.CenterOfMass.z - z) < 1e-6)

        return (feature, self.faceOf(feature, test))

    def sketch(self, *polylines, construction=()):
        sketch = self.doc.addObject("Sketcher::SketchObject", "Profile")
        for points in polylines:
            for a, b in zip(points, points[1:]):
                sketch.addGeometry(Part.LineSegment(a, b), False)
        for a, b in construction:
            sketch.addGeometry(Part.LineSegment(a, b), True)
        self.doc.recompute()
        return sketch

    def edgesOf(self, sketch, points):
        """The names of the sketch's shape edges both of whose ends are among points: found by
        geometry, never counted (the shape's order is its wires', not the geometry's)."""
        names = []
        for i, edge in enumerate(sketch.Shape.Edges, 1):
            if all(near(v.Point, points) for v in edge.Vertexes):
                names.append(f"Edge{i}")
        return names

    def surface(self, sketch, names, target=None, length=None, reverse=False, label="Surface"):
        ext = self.doc.addObject("Part::Extrusion", label)
        ext.Base = sketch
        ext.BaseEdges = (sketch, names)
        ext.DirMode = "Custom"
        ext.Dir = V(0, 0, 1)
        ext.Solid = False
        ext.Reversed = reverse
        if target is not None:
            ext.EndType = "UpToFace"
            ext.UpToFace = target
        else:
            ext.LengthFwd = length
        self.doc.recompute()
        return ext

    def hexTube(self, clockwise=False):
        self.profile = self.sketch(hexagon(clockwise), POLYLINE)
        names = self.edgesOf(self.profile, hexagon(clockwise))
        self.assertEqual(len(names), 6)
        return self.surface(self.profile, names, self.top(self.box, 20))

    def split(self, tool, side="Front", keep=False):
        part = PartDesign.split(self.body, tool, side, keep)
        self.doc.recompute()
        self.original = self.body.Tip
        self.half = part.Tip
        for split in (self.original, self.half):
            self.assertEqual(split.TypeId, "PartDesign::Split")
            self.assertTrue(split.isValid(), split.getStatusString())
        return part

    def assertValid(self, obj):
        self.assertTrue(obj.isValid(), obj.getStatusString())

    def assertFails(self, obj, text):
        self.assertFalse(obj.isValid())
        self.assertIn(text, obj.getStatusString())

    # --- T1: up to a parallel plane -----------------------------------------------------------

    def testUpToParallelFace(self):
        """T1 (SU1): the hexagon's six edges up to the block's top face: a closed tube of six
        faces 8 x 20, 18 edges, no solid, z 0..20; the blind sheet of length 20 is the same."""
        self.block()
        ext = self.hexTube()
        self.assertValid(ext)
        shape = ext.Shape
        self.assertEqual(len(shape.Solids), 0)
        self.assertEqual(len(shape.Faces), 6)
        self.assertEqual(len(shape.Edges), 18)
        self.assertAlmostEqual(shape.Area, 960, places=6)
        for face in shape.Faces:
            self.assertAlmostEqual(face.Area, 160, places=6)
        bound = box(shape)
        self.assertAlmostEqual(bound.ZMin, 0, places=6)
        self.assertAlmostEqual(bound.ZMax, 20, places=6)
        blind = self.surface(
            self.profile, list(ext.BaseEdges[1]), length=20, label="Blind"
        )
        self.assertValid(blind)
        self.assertEqual(len(blind.Shape.Faces), 6)
        self.assertAlmostEqual(blind.Shape.Area, 960, places=6)
        points = [v.Point for v in blind.Shape.Vertexes]
        for vertex in shape.Vertexes:
            self.assertTrue(near(vertex.Point, points), vertex.Point)

    def testPickedEdgesOnly(self):
        """4a: the three edges of the polyline, blind to 10: three faces, its length 22.3607 + 10
        + 22.3607 times 10; the hexagon's edges in the same sketch are not extruded."""
        self.block()
        sketch = self.sketch(hexagon(), POLYLINE)
        names = self.edgesOf(sketch, POLYLINE)
        self.assertEqual(len(names), 3)
        ext = self.surface(sketch, names, length=10)
        self.assertValid(ext)
        self.assertEqual(len(ext.Shape.Faces), 3)
        self.assertAlmostEqual(ext.Shape.Area, (2 * math.sqrt(500) + 10) * 10, places=6)

    def testBehindTheSketchReversed(self):
        """SU4, the Drum Holder's own case: a face behind the sketch's normal builds with
        Reversed on, the extrude's direction alone deciding; with Reversed off it fails."""
        self.block()
        self.box.Placement = App.Placement(V(0, 0, -30), App.Rotation())
        self.doc.recompute()
        sketch = self.sketch(hexagon())
        names = self.edgesOf(sketch, hexagon())
        ext = self.surface(sketch, names, self.top(self.box, -10), reverse=True)
        self.assertValid(ext)
        self.assertAlmostEqual(ext.Shape.Area, 6 * 8 * 10, places=6)
        bound = box(ext.Shape)
        self.assertAlmostEqual(bound.ZMin, -10, places=6)
        self.assertAlmostEqual(bound.ZMax, 0, places=6)
        ext.Reversed = False
        self.doc.recompute()
        self.assertFails(ext, "is not ahead of the profile in the extrude's direction")

    # --- T2: a split by the tube -------------------------------------------------------------

    def testSplitByTube(self):
        """T2 (SU5): the block split by the tube: the plug, 3325.5376 with 8 faces, and the block
        with a six-sided hole, 20674.4624 with 12; Front is the side the sheet's normals point
        to, for this hexagon (drawn counter-clockwise) the inside of the tube: the plug (T8);
        the sheet is hidden (Keep tools off)."""
        self.block()
        ext = self.hexTube()
        part = self.split(ext, "Back")
        self.assertAlmostEqual(self.original.Shape.Volume, HOLED, places=4)
        self.assertEqual(len(self.original.Shape.Faces), 12)
        self.assertAlmostEqual(self.half.Shape.Volume, PLUG, places=4)
        self.assertEqual(len(self.half.Shape.Faces), 8)
        self.assertAlmostEqual(self.original.Shape.common(self.half.Shape).Volume, 0, places=6)
        self.assertAlmostEqual(part.Shape.Volume, PLUG, places=4)
        plug = box(self.half.Shape)
        self.assertAlmostEqual(plug.XMin, 12, places=6)
        self.assertAlmostEqual(plug.XMax, 28, places=6)
        self.assertFalse(ext.Visibility)
        self.assertFalse(self.original.KeepTool)

    def testSides(self):
        """T8 (review r1): Front of a tube is its inside, the plug, however the hexagon was
        drawn: a closed wire is turned counter-clockwise about the extrude's direction before
        the sheet is made, so the side doesn't follow the drawing direction."""
        for clockwise in (False, True):
            self.block()
            ext = self.hexTube(clockwise)
            self.split(ext, "Front")
            self.assertAlmostEqual(self.original.Shape.Volume, PLUG, places=4)
            self.assertAlmostEqual(self.half.Shape.Volume, HOLED, places=4)
            self.tearDown()
            self.setUp()

    def testFirstEdgeReversed(self):
        """Review r1 (SideFollowsFirstEdge): the sketch's first segment reversed in place by
        moving its end points: the sheet's geometry is the same, and so is the piece each part
        keeps."""
        self.block()
        ext = self.hexTube()
        self.split(ext, "Front")
        self.assertAlmostEqual(self.original.Shape.Volume, PLUG, places=4)
        sketch = self.profile
        g = sketch.Geometry[0]
        a, b = g.StartPoint, g.EndPoint
        sketch.moveGeometry(0, 1, (a + b) * 0.5 + V(0.5, 0.5, 0), False)
        self.doc.recompute()
        sketch.moveGeometry(0, 2, a, False)
        self.doc.recompute()
        sketch.moveGeometry(0, 1, b, False)
        self.doc.recompute()
        self.assertTrue(sketch.Geometry[0].StartPoint.isEqual(b, 1e-9))
        self.assertValid(self.original)
        self.assertAlmostEqual(self.original.Shape.Volume, PLUG, places=4)
        self.assertAlmostEqual(self.half.Shape.Volume, HOLED, places=4)


    def testFaceProfileIsNotTurned(self):
        """Review r2 (FaceProfileTurnedOver): a face as the profile makes a solid even with Solid
        off; it is never turned inside out (its volume stays positive), whichever way the face
        faces."""
        self.block()
        for normal in (V(0, 0, -1), V(0, 0, 1)):
            square = self.doc.addObject("Part::Feature", "Square")
            face = Part.Face(Part.makePolygon(
                [V(15, 10, 30), V(25, 10, 30), V(25, 20, 30), V(15, 20, 30), V(15, 10, 30)]))
            if face.normalAt(0, 0).dot(normal) < 0:
                face.reverse()
            square.Shape = face
            ext = self.doc.addObject("Part::Extrusion", "FaceUpTo")
            ext.Base = square
            ext.Dir = V(0, 0, -1)
            ext.Solid = False
            ext.EndType = "UpToFace"
            ext.UpToFace = self.top(self.box, 20)
            self.doc.recompute()
            self.assertValid(ext)
            self.assertAlmostEqual(ext.Shape.Volume, 1000, places=6)

    def testEmptyPickIsTheWholeBase(self):
        """Review r2: BaseEdges naming Base with no edges is the whole of Base, as made today: the
        same faces, facing the same way, as with BaseEdges empty."""
        sketch = self.sketch(hexagon(clockwise=True))
        plain = self.doc.addObject("Part::Extrusion", "Plain")
        plain.Base = sketch
        plain.Dir = V(0, 0, 7)
        picked = self.doc.addObject("Part::Extrusion", "Picked")
        picked.Base = sketch
        picked.BaseEdges = (sketch, [])
        picked.Dir = V(0, 0, 7)
        self.doc.recompute()
        for a, b in zip(plain.Shape.Faces, picked.Shape.Faces):
            self.assertTrue(a.normalAt(0, 0).isEqual(b.normalAt(0, 0), 1e-9))

    def testOpenSheetSplitIsRefused(self):
        """Reviews r2 and r3: an open polyline's sheet up to the top divides the block, but it has
        no inside: which part would keep which piece follows the way its edges run, which a move
        (OpenSheetSideAfterTilt), a redraw, a turned Placement or a copy turned silently. The
        Split refuses it, loudly, before anything changes."""
        self.block()
        line = [V(20, -5, 0), V(20.5, 15, 0), V(21, 35, 0)]
        sketch = self.sketch(line)
        ext = self.surface(sketch, self.edgesOf(sketch, line), self.top(self.box, 20))
        self.assertValid(ext)
        with self.assertRaisesRegex(ValueError, "isn.t supported yet"):
            PartDesign.split(self.body, ext)
        self.assertEqual(len(self.body.Group), 1)
        self.assertTrue(ext.Visibility)

    def testNegativeLengthKeepsTheSide(self):
        """Review r5 (NegativeLengthTube): Reversed on with LengthFwd -20 makes the same tube as
        LengthFwd 20; the tube is turned by the way the prism runs, so the Split keeps the same
        piece."""
        self.block()
        self.profile = self.sketch(hexagon())
        ext = self.surface(self.profile, self.edgesOf(self.profile, hexagon()), length=20)
        self.split(ext, "Front")
        self.assertAlmostEqual(self.original.Shape.Volume, PLUG, places=4)
        ext.Reversed = True
        ext.LengthFwd = -20
        self.doc.recompute()
        bound = box(ext.Shape)
        self.assertAlmostEqual(bound.ZMin, 0, places=6)
        self.assertAlmostEqual(bound.ZMax, 20, places=6)
        self.assertValid(self.original)
        self.assertAlmostEqual(self.original.Shape.Volume, PLUG, places=4)

    def testBowtieIsRefused(self):
        """Review r5 (BowtieTubeRedrawnReversed): a loop that crosses itself into two lobes of
        equal area has no inside to turn toward: refused."""
        self.block()
        bowtie = [V(4, 5, 0), V(36, 25, 0), V(36, 5, 0), V(4, 25, 0), V(4, 5, 0)]
        sketch = self.sketch(bowtie)
        ext = self.surface(sketch, self.edgesOf(sketch, bowtie), self.top(self.box, 20))
        with self.assertRaisesRegex(ValueError, "isn't supported yet"):
            PartDesign.split(self.body, ext)

    def testCrossingLoopAndTaperAreRefused(self):
        """Review r6 (BowtieLobeGrows, TaperAddedToTube): a loop that crosses itself with unequal
        lobes would turn by its larger lobe, which an edit can change; a taper makes the walls
        by a loft, whose faces don't follow the turn. Both are refused."""
        self.block()
        bowtie = [V(4, 5, 0), V(36, 25, 0), V(36, 5, 0), V(10, 25, 0), V(4, 5, 0)]
        sketch = self.sketch(bowtie)
        ext = self.surface(sketch, self.edgesOf(sketch, bowtie), self.top(self.box, 20))
        with self.assertRaisesRegex(ValueError, "isn't supported yet"):
            PartDesign.split(self.body, ext)
        self.profile = self.sketch(hexagon())
        tube = self.surface(self.profile, self.edgesOf(self.profile, hexagon()), length=20,
                            label="Tapered")
        tube.TaperAngle = 2
        self.doc.recompute()
        self.assertValid(tube)
        with self.assertRaisesRegex(ValueError, "isn't supported yet"):
            PartDesign.split(self.body, tube)

    def testRetooledToOneLineFails(self):
        """Review r5 (TubeRetooledToOneLine): the tube's BaseEdges changed after the Split to one
        line, a sheet of one planar face: the Split fails, it doesn't cut by that face's plane."""
        self.block()
        ext = self.hexTube()
        self.split(ext, "Front")
        line = [V(20, -5, 0), V(21, 35, 0)]
        self.profile.addGeometry(Part.LineSegment(*line), False)
        self.doc.recompute()
        ext.BaseEdges = (self.profile, self.edgesOf(self.profile, line))
        self.doc.recompute()
        self.assertValid(ext)
        self.assertFails(self.original, "isn't supported yet")

    def testTargetBodyMoved(self):
        """Review r1 (SheetUpToMovedBody, design 4b): the target's Body moved up 5 moves the face
        the sheet runs to (a move no link sees): the sheet runs to z 25 (1200)."""
        self.block()
        ext = self.hexTube()
        self.body.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        self.doc.recompute()
        self.assertValid(ext)
        self.assertAlmostEqual(box(ext.Shape).ZMax, 25, places=6)
        self.assertAlmostEqual(ext.Shape.Area, 1200, places=6)

    def testSplitByStaleSheetFails(self):
        """Review r1 (SplitByStaleSheet): a block z 5..15 split by the tube up to a plate's top
        (z 22) in another Body; the plate's Body down 10 brings the sheet's end to z 12, inside
        the block: the Split fails (SU6-SU8), it doesn't keep the old cut."""
        self.block(height=10)
        self.box.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        plateBody = self.doc.addObject("PartDesign::Body", "Plate")
        plate = plateBody.newObject("PartDesign::AdditiveBox", "PlateBox")
        plate.Length, plate.Width, plate.Height = 40, 30, 2
        plate.Placement = App.Placement(V(0, 0, 20), App.Rotation())
        self.doc.recompute()
        self.profile = self.sketch(hexagon())
        ext = self.surface(self.profile, self.edgesOf(self.profile, hexagon()),
                           self.top(plate, 22))
        self.split(ext)
        plateBody.Placement = App.Placement(V(0, 0, -10), App.Rotation())
        self.doc.recompute()
        self.assertValid(ext)
        self.assertAlmostEqual(box(ext.Shape).ZMax, 12, places=6)
        self.assertFails(self.original, "doesn't cut Block")

    def testClosedTubeUpToSlantedFace(self):
        """Review r1 (ClosedTubeUpToSlantedFace): the hexagon's closed tube up to the slanted top
        z = 20 + 0.25 x: six faces whose far edges lie in the plane, area 8 x 6 x 25 = 1200 (the
        edges' midpoints average x = 20); the plug of the slab split by it is the hexagon times
        its mean height, 166.2769 x 25."""
        base = self.slab()
        sketch = self.sketch(hexagon())
        ext = self.surface(sketch, self.edgesOf(sketch, hexagon()), self.faceSlanted(base))
        self.assertValid(ext)
        self.assertEqual(len(ext.Shape.Faces), 6)
        self.assertAlmostEqual(ext.Shape.Area, 1200, places=4)
        for vertex in ext.Shape.Vertexes:
            p = vertex.Point
            if p.z > 1e-6:
                self.assertAlmostEqual(p.z, 20 + 0.25 * p.x, places=6)
        self.split(ext)
        got = sorted([self.original.Shape.Volume, self.half.Shape.Volume])
        self.assertAlmostEqual(got[0], 25 * HEXAGON, places=4)
        self.assertAlmostEqual(got[1], base.Shape.Volume - 25 * HEXAGON, places=4)

    def testEditFollows(self):
        """T6: a taller block (25) lengthens the tube (1200) and the plug (25 x 166.2769), and the
        plug's wall names stay."""
        self.block()
        ext = self.hexTube()
        self.split(ext, "Back")

        def walls():
            names = []
            for i, face in enumerate(self.half.Shape.Faces, 1):
                if abs(face.normalAt(0, 0).z) < 1e-9:
                    names.append(self.half.Shape.ElementReverseMap.get(f"Face{i}"))
            return sorted(n for n in names if n)

        before = walls()
        self.assertEqual(len(before), 6)
        self.box.Height = 25
        self.doc.recompute()
        self.assertValid(ext)
        self.assertValid(self.original)
        self.assertValid(self.half)
        self.assertAlmostEqual(ext.Shape.Area, 1200, places=6)
        self.assertAlmostEqual(self.half.Shape.Volume, 25 * HEXAGON, places=4)
        self.assertAlmostEqual(self.original.Shape.Volume, 30000 - 25 * HEXAGON, places=4)
        self.assertEqual(walls(), before)

    def testKeepToolAndDelete(self):
        """T9: Keep tools on leaves the sheet shown; off, the Split hides it, and deleting the
        Split shows it again."""
        self.block()
        ext = self.hexTube()
        self.split(ext, keep=True)
        self.assertTrue(ext.Visibility)
        self.assertTrue(self.original.KeepTool)
        self.original.KeepTool = False
        self.assertFalse(ext.Visibility)
        half, original = self.half, self.original
        part = half.getParentGeoFeatureGroup()
        part.removeObjectsFromDocument()
        self.doc.removeObject(part.Name)
        self.doc.removeObject(original.Name)
        self.doc.recompute()
        self.assertTrue(ext.Visibility)

    def testSaveAndReopen(self):
        """T9: saved and reopened, the extrusion keeps its picks and its end, and the split
        computes the same."""
        self.block()
        self.hexTube()
        self.split(self.doc.getObject("Surface"))
        path = App.getUserAppDataDir() + "TestSurfaceUpToSplit.FCStd"
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = App.openDocument(path)
        ext = self.doc.getObject("Surface")
        self.assertEqual(ext.EndType, "UpToFace")
        self.assertEqual(len(ext.BaseEdges[1]), 6)
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()
        self.assertValid(ext)
        self.assertAlmostEqual(ext.Shape.Area, 960, places=6)
        volumes = sorted(
            o.Shape.Volume for o in self.doc.Objects if o.TypeId == "PartDesign::Split"
        )
        self.assertAlmostEqual(volumes[0], PLUG, places=4)
        self.assertAlmostEqual(volumes[1], HOLED, places=4)

    # --- T3: a slanted target ----------------------------------------------------------------

    def slab(self):
        """A part whose top is the plane z = 20 + 0.25 x over x 0..40, y 0..30."""
        section = Part.Face(
            Part.makePolygon([V(0, 0, 0), V(40, 0, 0), V(40, 0, 30), V(0, 0, 20), V(0, 0, 0)])
        )
        solid = section.extrude(V(0, 30, 0))
        slab = self.doc.addObject("Part::Feature", "Slab")
        slab.Shape = solid
        self.body = self.doc.addObject("PartDesign::Body", "Block")
        self.body.Label = "Block"
        self.body.BaseFeature = slab
        self.doc.recompute()
        self.base = self.body.Group[0]
        return self.base

    def testSlantedTarget(self):
        """T3 (SU2): the polyline up to the slanted top z = 20 + 0.25 x: three faces whose far
        edges lie in that plane, also past the face (the plane is whole), area 22.3607 x 22.5
        + 10 x 25 + 22.3607 x 27.5 = 1368.034. The Split refuses this open sheet (no inside)."""
        base = self.slab()
        sketch = self.sketch(POLYLINE)
        names = self.edgesOf(sketch, POLYLINE)
        ext = self.surface(sketch, names, self.faceSlanted(base))
        self.assertValid(ext)
        self.assertEqual(len(ext.Shape.Faces), 3)
        self.assertAlmostEqual(ext.Shape.Area, math.sqrt(500) * 50 + 250, places=4)
        for vertex in ext.Shape.Vertexes:
            p = vertex.Point
            if p.z > 1e-6:
                self.assertAlmostEqual(p.z, 20 + 0.25 * p.x, places=6)
        # An open sheet: no inside, so the Split refuses it (reviews r2, r3)
        with self.assertRaisesRegex(ValueError, "isn.t supported yet"):
            PartDesign.split(self.body, ext)

    def faceSlanted(self, feature):
        def test(face):
            normal = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
            return normal.z > 0.5 and abs(normal.x) > 0.1
        return (feature, self.faceOf(feature, test))

    # --- T4: errors --------------------------------------------------------------------------

    def testTargetErrors(self):
        """T4: a face ahead with Reversed on, a plane along the direction, a cylinder, Solid on
        (SU4: Onshape fails such an extrude)."""
        self.block()
        sketch = self.sketch(hexagon())
        names = self.edgesOf(sketch, hexagon())
        ext = self.surface(sketch, names, self.top(self.box, 20), reverse=True)
        self.assertFails(ext, "is not ahead of the profile in the extrude's direction")
        ext.Reversed = False
        side = self.faceOf(self.box, lambda f: abs(f.CenterOfMass.x) < 1e-6)
        ext.UpToFace = (self.box, side)
        self.doc.recompute()
        self.assertFails(ext, "is not ahead of the profile in the extrude's direction")
        cylinder = self.doc.addObject("Part::Cylinder", "Cylinder")
        cylinder.Radius, cylinder.Height = 40, 30
        self.doc.recompute()
        ext.UpToFace = (cylinder, self.faceOf(cylinder, lambda f: f.Surface.TypeId == "Part::GeomCylinder"))
        self.doc.recompute()
        self.assertFails(ext, "isn't planar")
        ext.UpToFace = self.top(self.box, 20)
        ext.Solid = True
        self.doc.recompute()
        self.assertFails(ext, "set Solid to false")

    def testBaseEdgesErrors(self):
        """T4: BaseEdges of another object, a sketch's other numberings, a name twice, edges
        that branch (two squares sharing a corner, all eight picked)."""
        a = [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0), V(0, 0, 0)]
        b = [V(10, 10, 0), V(20, 10, 0), V(20, 20, 0), V(10, 20, 0), V(10, 10, 0)]
        sketch = self.sketch(a, b)
        other = self.sketch(hexagon())
        ext = self.surface(sketch, self.edgesOf(sketch, a), length=5)
        self.assertValid(ext)
        ext.BaseEdges = (other, ["Edge1"])
        self.doc.recompute()
        self.assertFails(ext, "BaseEdges names edges of")
        for bad, text in (
            (["edge1"], "not edge1"),
            (["Edge1", "Edge1"], "twice"),
            (["Edge%d" % i for i in range(1, 9)], "branch"),
        ):
            ext.BaseEdges = (sketch, bad)
            self.doc.recompute()
            self.assertFails(ext, text)

    def testSplitErrors(self):
        """T4 (SU6, SU8): a tube that ends inside the block (blind to 10), or starts inside it (from
        z 5 up to the top), doesn't cut it: the sheet isn't extended. Two tubes as one tool (a
        compound) and an open sheet are refused. Nothing is changed."""
        self.block()
        hexagons = self.sketch(hexagon(), hexagon(cx=10, cy=8, r=3))
        low = self.surface(hexagons, self.edgesOf(hexagons, hexagon()), length=10, label="Low")
        self.assertValid(low)
        with self.assertRaisesRegex(ValueError, "doesn't cut Block"):
            PartDesign.split(self.body, low)
        raised = self.sketch(hexagon())
        raised.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        self.doc.recompute()
        inside = self.surface(raised, self.edgesOf(raised, [p + V(0, 0, 5) for p in hexagon()]),
                              self.top(self.box, 20), label="Inside")
        self.assertValid(inside)
        self.assertAlmostEqual(inside.Shape.Area, 6 * 8 * 15, places=6)
        with self.assertRaisesRegex(ValueError, "doesn't cut Block"):
            PartDesign.split(self.body, inside)
        one = self.surface(hexagons, self.edgesOf(hexagons, hexagon()), length=20, label="One")
        two = self.surface(hexagons, self.edgesOf(hexagons, hexagon(cx=10, cy=8, r=3)),
                           length=20, label="Two")
        both = self.doc.addObject("Part::Compound", "Both")
        both.Links = [one, two]
        self.doc.recompute()
        with self.assertRaisesRegex(ValueError, "isn't supported yet"):
            PartDesign.split(self.body, both)
        line = self.sketch(POLYLINE[:3])
        short = self.surface(line, self.edgesOf(line, POLYLINE), self.top(self.box, 20))
        with self.assertRaisesRegex(ValueError, "isn't supported yet"):
            PartDesign.split(self.body, short)
        self.assertEqual(len(self.body.Group), 1)
        self.assertTrue(short.Visibility)
        self.assertTrue(low.Visibility)

    def testThreePieces(self):
        """T4 (SU10): a slot x 19..21, y 5..25 through the block cuts the hexagon's plug in two, so
        the tube would give three pieces: Onshape makes three parts, FreeCAD-CH refuses, saying
        so."""
        self.block()
        cut = self.body.newObject("PartDesign::SubtractiveBox", "Slot")
        cut.Length, cut.Width, cut.Height = 2, 20, 22
        cut.Placement = App.Placement(V(19, 5, -1), App.Rotation())
        self.doc.recompute()
        ext = self.hexTube()
        with self.assertRaisesRegex(ValueError, "into 3 pieces"):
            PartDesign.split(self.body, ext)

    # --- T5, T7 ------------------------------------------------------------------------------

    def testOnePlaneSheetIsRefused(self):
        """SU9 and review r4: Onshape extends a sheet of one planar face to its whole plane; here
        its Front would follow the way its line was drawn, so a Split refuses it (as before this
        change): a datum plane or a picked face cuts by a plane."""
        self.block()
        sketch = self.sketch([V(20, 5, 0), V(20, 25, 0)])
        sketch.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        self.doc.recompute()
        ext = self.surface(sketch, ["Edge1"], length=10)
        self.assertValid(ext)
        with self.assertRaisesRegex(ValueError, "isn't supported yet"):
            PartDesign.split(self.body, ext)
        self.assertTrue(ext.Visibility)

    def testLengthUnchanged(self):
        """T5: BaseEdges empty and EndType Length: the whole sketch, as before."""
        sketch = self.sketch(hexagon())
        ext = self.doc.addObject("Part::Extrusion", "Plain")
        ext.Base = sketch
        ext.Dir = V(0, 0, 7)
        self.doc.recompute()
        self.assertValid(ext)
        self.assertEqual(ext.EndType, "Length")
        self.assertAlmostEqual(ext.Shape.Area, 6 * 8 * 7, places=6)

    def testTwoLoopsSharingACorner(self):
        """T7, the Drum Holder's shape: two squares sharing a corner in one sketch, each picked
        to its own tube; a construction line, and a segment deleted that neither picks: the
        same edges are extruded, the picks following their edges."""
        a = [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0), V(0, 0, 0)]
        b = [V(10, 10, 0), V(20, 10, 0), V(20, 20, 0), V(10, 20, 0), V(10, 10, 0)]
        stray = [V(-10, -10, 0), V(-5, -10, 0)]
        sketch = self.sketch(stray, b, a, construction=[(V(0, 0, 0), V(20, 20, 0))])
        tubeA = self.surface(sketch, self.edgesOf(sketch, a), length=5, label="TubeA")
        tubeB = self.surface(sketch, self.edgesOf(sketch, b), length=5, label="TubeB")
        for tube, square in ((tubeA, a), (tubeB, b)):
            self.assertValid(tube)
            self.assertEqual(len(tube.Shape.Faces), 4)
        sketch.delGeometry(0)
        self.doc.recompute()
        for tube, square in ((tubeA, a), (tubeB, b)):
            self.assertValid(tube)
            self.assertEqual(len(tube.Shape.Faces), 4)
            bound = box(tube.Shape)
            self.assertAlmostEqual(bound.XMin, square[0].x, places=6)
            self.assertAlmostEqual(bound.YMin, square[0].y, places=6)
            self.assertAlmostEqual(bound.XMax, square[0].x + 10, places=6)
