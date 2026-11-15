# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""A face split by a feature and made whole again by its refine keeps its name (FreeCAD-CH,
ops#806).

A rib that ends flush with a plate's top face and reaches into the plate is fused in two steps:
the fusion cuts the top face along the rib's outline (the piece is named `<top>|...;FUS;...;MOD`),
then the refine merges the piece, the rib's top and the strips between them into one face. That
face kept only the piece's names, so every element a later feature generated on it was named from
the piece: a boss's junction edge with the plate, far from the rib and unchanged, got another name
when the rib was inserted before the boss, and a fillet on it lost its edge.

The models (designed, no file): a plate 80 x 50 x 10 with its top at z 10.
- The rib: a slot 3 deep, a boss whose cylinder cuts the top face, then a rib standing in the slot,
  inserted before the boss. Expected by construction: the boss and the top face around it are the
  same with and without the rib, so the junction edge keeps its name for every rib; the top face
  keeps its name first where the rib is flush (it is the old face and more).
- The grooves: full-width grooves cut the top face into pieces, a flush fill bridges two of them.
  Expected: with one groove the bridged face holds all that is left of the top face and takes its
  name again; with two grooves a piece stays outside, and no face is the top face.
- The wall: a wall across the plate standing above the top face. The top face stays in two
  pieces: neither takes its name.
"""

import unittest

import FreeCAD as App
import Part

TOP = 10.0


class TestRefineWholeNames(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("RefineWholeNames")
        self.body = self.doc.addObject("PartDesign::Body", "Body")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sketch(self, name, z, rectangles=(), circle=None):
        sketch = self.body.newObject("Sketcher::SketchObject", name)
        plane = [o for o in self.body.Origin.OriginFeatures if o.Role == "XY_Plane"][0]
        sketch.AttachmentSupport = (plane, [""])
        sketch.MapMode = "FlatFace"
        sketch.AttachmentOffset = App.Placement(App.Vector(0, 0, z), App.Rotation())
        for x0, y0, x1, y1 in rectangles:
            p = [App.Vector(x0, y0), App.Vector(x1, y0), App.Vector(x1, y1), App.Vector(x0, y1)]
            for i in range(4):
                sketch.addGeometry(Part.LineSegment(p[i], p[(i + 1) % 4]))
        if circle:
            x, y, r = circle
            sketch.addGeometry(Part.Circle(App.Vector(x, y, 0), App.Vector(0, 0, 1), r))
        return sketch

    def feature(self, kind, name, sketch, length):
        feature = self.body.newObject("PartDesign::" + kind, name)
        feature.Profile = sketch
        feature.Length = length
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        return feature

    def plate(self):
        return self.feature("Pad", "Plate", self.sketch("PlateSk", 0, [(0, -25, 80, 25)]), TOP)

    def names(self, feature, element):
        """The element's names in full form, in the map's order"""
        found = feature.Shape.ElementReverseMap.get(element, [])
        return [App.expandMappedName(n) for n in ([found] if isinstance(found, str) else found)]

    def topAt(self, feature, x, y):
        """The face in the plate's top plane that holds (x, y)"""
        point = App.Vector(x, y, TOP)
        found = [
            "Face%d" % (i + 1)
            for i, f in enumerate(feature.Shape.Faces)
            if abs(f.BoundBox.ZMin - TOP) < 1e-6
            and abs(f.BoundBox.ZMax - TOP) < 1e-6
            and f.isInside(point, 1e-6, True)
        ]
        self.assertEqual(len(found), 1, "one top face at (%g, %g)" % (x, y))
        return found[0]

    def insertAfter(self, objects, target):
        """Moves the objects, made at the tip, to just after target, in order"""
        for obj in objects:
            self.body.removeObject(obj)
        for obj in objects:
            self.body.insertObject(obj, target, True)
            target = obj
        self.doc.recompute()

    # ------------------------------------------------------------------ the rib

    def junction(self, boss):
        """The names of the circle where the boss's cylinder leaves the plate's top face"""
        found = [
            "Edge%d" % (i + 1)
            for i, e in enumerate(boss.Shape.Edges)
            if hasattr(e.Curve, "Radius")
            and abs(e.Curve.Radius - 12) < 1e-6
            and abs(e.Curve.Center.z - TOP) < 1e-6
        ]
        self.assertEqual(len(found), 1, "the boss's junction circle is one edge")
        return self.names(boss, found[0])

    def rib(self, height, halfLength):
        """The top face's and the junction edge's names at the boss, without and with the rib"""
        self.plate()
        slot = self.feature("Pocket", "Slot", self.sketch("SlotSk", TOP, [(16, -4, 36, 4)]), 3)
        # The boss starts inside the plate: its cylinder cuts the top face (a fusion's edge)
        boss = self.feature("Pad", "Boss", self.sketch("BossSk", 5, circle=(60, 0, 12)), 25)
        before = (self.names(boss, self.topAt(boss, 60, 20)), self.junction(boss))
        self.assertEqual(len(before[0]), 1)
        ribSketch = self.sketch("RibSk", TOP - 3, [(25, -halfLength, 27, halfLength)])
        rib = self.feature("Pad", "Rib", ribSketch, height)
        self.insertAfter([ribSketch, rib], slot)
        self.assertEqual(boss.BaseFeature, rib)
        for obj in (rib, boss):
            self.assertTrue(obj.isValid(), obj.getStatusString())
        after = (self.names(boss, self.topAt(boss, 60, 20)), self.junction(boss))
        return before, after, rib

    def testFlushRibIntoThePlateKeepsTheFarJunctionEdge(self):
        """ops#806: the rib reaches 1 mm into the plate at both ends, flush with its top"""
        before, after, rib = self.rib(3, 5)
        self.assertEqual(self.topAt(rib, 26, 0), self.topAt(rib, 60, 20), "the rib's top merged")
        self.assertEqual(after[0][0], before[0][0], "the top face is named as before, first")
        # The piece's name stays on the face, for references made to it
        self.assertTrue(any(n.startswith(before[0][0] + "|") for n in after[0][1:]), after[0])
        self.assertEqual(after[1], before[1], "the junction edge keeps its name")

    def testFlushRibFittingTheSlotKeepsTheFarJunctionEdge(self):
        """The rib ends at the slot's walls: the top face isn't cut, only merged"""
        before, after, rib = self.rib(3, 4)
        self.assertEqual(self.topAt(rib, 26, 0), self.topAt(rib, 60, 20), "the rib's top merged")
        self.assertEqual(after[0][0], before[0][0])
        self.assertEqual(after[1], before[1])

    def testRibBelowOrAboveTheTopChangesNoName(self):
        for height in (2.5, 3.5):
            with self.subTest(height=height):
                before, after, _ = self.rib(height, 5)
                self.assertEqual(after, before)
                self.tearDown()
                self.setUp()

    # ------------------------------------------------------------------ the grooves

    def grooves(self, positions):
        """The plate's top name, then full-width grooves at the x positions and a flush fill
        that bridges the first groove between y -10 and 10"""
        plate = self.plate()
        top = self.names(plate, self.topAt(plate, 40, 0))
        self.assertEqual(len(top), 1)
        cuts = [(x, -25, x + 4, 25) for x in positions]
        self.feature("Pocket", "Grooves", self.sketch("GrooveSk", TOP, cuts), 3)
        x = positions[0]
        fill = self.feature("Pad", "Fill", self.sketch("FillSk", TOP - 3, [(x, -10, x + 4, 10)]), 3)
        return top[0], fill

    def testFilledGrooveMakesTheTopFaceWhole(self):
        """The split is an earlier feature's: the fill bridges both pieces, all that is left"""
        top, fill = self.grooves([20])
        face = self.topAt(fill, 10, 0)
        self.assertEqual(face, self.topAt(fill, 60, 0), "both sides are one face")
        names = self.names(fill, face)
        self.assertEqual(names[0], top, "the top face's name is back, first")
        self.assertGreaterEqual(sum(n.startswith(top + "|") for n in names), 1, names)

    def testAPieceLeftOutsideKeepsTheNameAway(self):
        """Two grooves, three pieces: the fill bridges two, the third stays apart"""
        top, fill = self.grooves([20, 50])
        bridged = self.topAt(fill, 10, 0)
        self.assertEqual(bridged, self.topAt(fill, 40, 0))
        apart = self.topAt(fill, 70, 0)
        self.assertNotEqual(bridged, apart)
        for face in (bridged, apart):
            names = self.names(fill, face)
            self.assertNotIn(top, names)
            self.assertTrue(any(n.startswith(top + "|") for n in names), names)

    # ------------------------------------------------------------------ the wall

    def testWallAcrossThePlateLeavesTwoPieces(self):
        plate = self.plate()
        top = self.names(plate, self.topAt(plate, 40, 0))[0]
        wall = self.feature("Pad", "Wall", self.sketch("WallSk", TOP, [(25, -25, 27, 25)]), 2)
        left, right = self.topAt(wall, 10, 0), self.topAt(wall, 60, 0)
        self.assertNotEqual(left, right)
        for face in (left, right):
            names = self.names(wall, face)
            self.assertNotIn(top, names)
            self.assertTrue(all(n.startswith(top + "|") for n in names), names)
