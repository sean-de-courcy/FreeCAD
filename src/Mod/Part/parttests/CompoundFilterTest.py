# SPDX-License-Identifier: LGPL-2.1-or-later

"""CompoundFilter's "specific items" filter with Invert (FreeCAD-CH ops#252).

Designed model: a compound of five 1 mm boxes along X, box i at x = 2 i, so each item is told
apart by its BoundBox.XMin."""

import unittest

import FreeCAD as App
import Part

from CompoundTools import CompoundFilter


class CompoundFilterTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("CompoundFilterTest")
        boxes = [Part.makeBox(1, 1, 1, App.Vector(2 * i, 0, 0)) for i in range(5)]
        self.base = self.doc.addObject("Part::Feature", "Boxes")
        self.base.Shape = Part.makeCompound(boxes)
        self.filter = CompoundFilter.makeCompoundFilter("Filter", self.doc)
        self.filter.Base = self.base
        self.filter.FilterType = "specific items"

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def kept(self, items, invert):
        """The x of each box the filter keeps for `items`, inverted or not."""
        self.filter.items = items
        self.filter.Invert = invert
        self.doc.recompute()
        self.assertTrue(self.filter.isValid(), self.filter.getStatusString())
        return sorted(round(s.BoundBox.XMin) for s in self.filter.Shape.childShapes())

    def testRange(self):
        self.assertEqual(self.kept("1:3", False), [2, 4])

    def testInvertedRangeDropsTheRange(self):
        """Inverted, a range keeps the other items. It kept the range's items too (all five):
        the flags were never set."""
        self.assertEqual(self.kept("1:3", True), [0, 6, 8])

    def testInvertedSteppedRangeAndItem(self):
        self.assertEqual(self.kept("0::2;3", True), [2])
