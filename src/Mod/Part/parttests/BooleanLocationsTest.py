# SPDX-License-Identifier: LGPL-2.1-or-later

"""Part::Boolean's inputs carry their location replaced, not composed (FreeCAD-CH ops#310, fix B).

Each Part::Cut used to move its inputs by a new datum on top of the one their stored shape has, and
the cut keeps that location on every sub-shape it leaves untouched: along a chain the locations
grew by two datums per cut (8 locations per cut in the result's BREP), and every query on those
sub-shapes walked them (a chain of 30 cuts took 8 s instead of 1 s). The guard counts the BREP's
locations, which is deterministic, instead of timing anything.

Inputs that share TShapes (a simple copy, solids of one BooleanFragments) must stay distinct across
Base and Tool, as the composed datums kept them: a Tool at an identity Placement gets a datum of its
own. Without it, Common and Fuse of a box with its simple copy named every element as if the
boolean hadn't touched it (half the element map).

Designed models: a 30x20x10 box cut by 2x2x12 boxes along X, the tools placed or made in place;
moved and rotated inputs checked against the same cut of the placed shapes; a 10x8x6 box with its
simple copy and its deep copy; the two solids of a BooleanFragments of two touching 10 mm cubes."""

import re
import unittest

import FreeCAD as App
import Part
import BOPTools.SplitFeatures

V = App.Vector


def locationCount(shape):
    """The number of entries in the shape's BREP Locations table."""
    for line in shape.exportBrepToString().splitlines():
        if line.startswith("Locations "):
            return int(line.split()[1])
    return 0


def sharedFaces(first, second):
    """How many faces of first share their TShape with a face of second."""
    return sum(1 for face in first.Faces for other in second.Faces if face.isPartner(other))


def elementMap(shape, placeholders):
    """The shape's element map, each input's tags (its object's and its shape's) replaced by the
    placeholder given for that input: {placeholder: object}."""
    tags = {str(t): p for p, obj in placeholders.items() for t in (obj.ID, obj.Shape.Tag)}

    def rename(match):
        return ";" + tags.get(match.group(1).lstrip("-"), match.group(1)) + ";"

    return {k: re.sub(r";(-?\d+);", rename, str(v)) for k, v in shape.ElementReverseMap.items()}


class BooleanLocationsTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("BooleanLocationsTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def box(self, name, length, width, height, placement=App.Placement()):
        box = self.doc.addObject("Part::Box", name)
        box.Length, box.Width, box.Height = length, width, height
        box.Placement = placement
        return box

    def cut(self, name, base, tool):
        return self.boolean("Cut", name, base, tool)

    def boolean(self, kind, name, base, tool):
        result = self.doc.addObject("Part::" + kind, name)
        result.Base, result.Tool, result.Refine = base, tool, False
        return result

    def feature(self, name, shape):
        feature = self.doc.addObject("Part::Feature", name)
        feature.Shape = shape
        return feature

    def testCutChainLocationsDontCompound(self):
        count = 10
        for prefix, placed in (("Placed", True), ("InPlace", False)):
            with self.subTest(tools=prefix):
                result = self.box(prefix + "Base", 30, 20, 10)
                for i in range(count):
                    if placed:
                        placement = App.Placement(V(1 + 3 * i, 2, -1), App.Rotation())
                        tool = self.box(f"{prefix}Tool{i}", 2, 2, 12, placement)
                    else:
                        tool = self.feature(f"{prefix}Tool{i}", Part.makeBox(2, 2, 12, V(1 + 3 * i, 2, -1)))
                    result = self.cut(f"{prefix}Cut{i}", result, tool)
                self.doc.recompute()
                self.assertTrue(result.isValid(), result.getStatusString())
                self.assertAlmostEqual(result.Shape.Volume, 30 * 20 * 10 - count * 2 * 2 * 10, places=6)
                # Two per cut since the fix (each tool's own datum, at an identity too), eight before
                self.assertLessEqual(locationCount(result.Shape), 3 * count)

    def testSimpleCopyIsNamedLikeADeepCopy(self):
        """A boolean of a box with its simple copy (every TShape shared) gives the result, names
        included, of the same boolean with a deep copy (no TShape shared)."""
        box = self.box("Box", 10, 8, 6)
        self.doc.recompute()
        simple = self.feature("Simple", box.Shape)
        deep = self.feature("Deep", box.Shape.copy())
        self.doc.recompute()
        self.assertEqual(sharedFaces(simple.Shape, box.Shape), 6)
        self.assertEqual(sharedFaces(deep.Shape, box.Shape), 0)
        for kind, volume in (("Common", 480), ("Fuse", 480), ("Cut", 0)):
            with self.subTest(kind=kind):
                results = {c.Name: self.boolean(kind, kind + c.Name, box, c) for c in (simple, deep)}
                self.doc.recompute()
                maps = {}
                for name, result in results.items():
                    self.assertTrue(result.isValid(), result.getStatusString())
                    self.assertAlmostEqual(result.Shape.Volume, volume, places=6)
                    maps[name] = elementMap(result.Shape, {"Copy": self.doc.getObject(name)})
                self.assertEqual(len(results["Simple"].Shape.Faces), 6 if volume else 0)
                self.assertEqual(maps["Simple"], maps["Deep"])

    def testFragmentsShareTheirInterface(self):
        """Fuse, Common and Cut of the two solids of a BooleanFragments of two touching cubes,
        which share the interface face, against the same booleans of their deep copies."""
        first = self.box("First", 10, 10, 10)
        second = self.box("Second", 10, 10, 10, App.Placement(V(10, 0, 0), App.Rotation()))
        fragments = BOPTools.SplitFeatures.makeBooleanFragments("Fragments")
        fragments.Objects = [first, second]
        self.doc.recompute()
        solids = fragments.Shape.Solids
        pieces = [self.feature(f"Piece{i}", s) for i, s in enumerate(solids)]
        copies = [self.feature(f"PieceCopy{i}", s.copy()) for i, s in enumerate(solids)]
        self.doc.recompute()
        self.assertEqual(sharedFaces(pieces[0].Shape, pieces[1].Shape), 1)
        self.assertEqual(sharedFaces(copies[0].Shape, copies[1].Shape), 0)
        for kind, volume, faces in (("Fuse", 2000, 10), ("Common", 0, 0), ("Cut", 1000, 6)):
            with self.subTest(kind=kind):
                shared = self.boolean(kind, kind + "Pieces", *pieces)
                apart = self.boolean(kind, kind + "Copies", *copies)
                self.doc.recompute()
                for result in (shared, apart):
                    self.assertTrue(result.isValid(), result.getStatusString())
                    self.assertAlmostEqual(result.Shape.Volume, volume, places=6)
                    self.assertEqual(len(result.Shape.Faces), faces)
                self.assertEqual(
                    elementMap(shared.Shape, {"First": pieces[0], "Second": pieces[1]}),
                    elementMap(apart.Shape, {"First": copies[0], "Second": copies[1]}),
                )

    def testMovedInputsAreWhereTheyWere(self):
        base = self.box("Base", 20, 10, 10, App.Placement(V(5, -3, 2), App.Rotation(V(0, 0, 1), 20)))
        tool = self.box("Tool", 4, 4, 30, App.Placement(V(8, 0, -5), App.Rotation(V(1, 0, 0), 10)))
        first = self.cut("Cut", base, tool)
        second = self.cut("Cut2", first, self.box("Tool2", 3, 3, 30, App.Placement(V(14, 2, -5), App.Rotation())))
        self.doc.recompute()
        expected = base.Shape.cut(tool.Shape).cut(self.doc.getObject("Tool2").Shape)
        for result in (first, second):
            self.assertTrue(result.isValid(), result.getStatusString())
        self.assertAlmostEqual(second.Shape.Volume, expected.Volume, places=6)
        self.assertTrue(second.Shape.BoundBox.isInside(expected.BoundBox))
        self.assertTrue(expected.BoundBox.isInside(second.Shape.BoundBox))
        self.assertAlmostEqual(second.Shape.common(expected).Volume, expected.Volume, places=4)
