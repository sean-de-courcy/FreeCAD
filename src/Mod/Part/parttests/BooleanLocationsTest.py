# SPDX-License-Identifier: LGPL-2.1-or-later

"""Part::Boolean's inputs carry their location replaced, not composed (FreeCAD-CH ops#310, fix B).

Each Part::Cut used to move its inputs by a new datum on top of the one their stored shape has, and
the cut keeps that location on every sub-shape it leaves untouched: along a chain the locations
grew by two datums per cut (8 locations per cut in the result's BREP), and every query on those
sub-shapes walked them (a chain of 30 cuts took 8 s instead of 1 s). The guard counts the BREP's
locations, which is deterministic, instead of timing anything.

Designed models: a 30x20x10 box cut by 2x2x12 boxes along X; moved and rotated inputs checked
against the same cut of the placed shapes."""

import unittest

import FreeCAD as App
import Part

V = App.Vector


def locationCount(shape):
    """The number of entries in the shape's BREP Locations table."""
    for line in shape.exportBrepToString().splitlines():
        if line.startswith("Locations "):
            return int(line.split()[1])
    return 0


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
        cut = self.doc.addObject("Part::Cut", name)
        cut.Base, cut.Tool, cut.Refine = base, tool, False
        return cut

    def testCutChainLocationsDontCompound(self):
        count = 10
        result = self.box("Base", 30, 20, 10)
        for i in range(count):
            tool = self.box(f"Tool{i}", 2, 2, 12, App.Placement(V(1 + 3 * i, 2, -1), App.Rotation()))
            result = self.cut(f"Cut{i}", result, tool)
        self.doc.recompute()
        self.assertTrue(result.isValid(), result.getStatusString())
        self.assertAlmostEqual(result.Shape.Volume, 30 * 20 * 10 - count * 2 * 2 * 10, places=6)
        # Two per cut since the fix (each tool's own placement), eight before
        self.assertLessEqual(locationCount(result.Shape), 3 * count)

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
