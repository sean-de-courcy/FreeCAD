# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import math
import unittest

import FreeCAD
import Part


class TestThickness(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def _create_case_5829(self):
        """Create the rotated wedge/box/fillet model from issue case 5829."""
        body = self.Doc.addObject("PartDesign::Body", "Body")

        wedge = self.Doc.addObject("PartDesign::AdditiveWedge", "Wedge")
        wedge.Xmin = 0.0
        wedge.X2min = 10.0
        wedge.Xmax = 96.0
        wedge.X2max = 86.0
        wedge.Zmin = 0.0
        wedge.Z2min = 10.0
        wedge.Zmax = 126.0
        wedge.Z2max = 116.0
        wedge.Ymin = 0.0
        wedge.Ymax = 25.0
        body.addObject(wedge)

        box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        box.Length = 96.0
        box.Width = 126.0
        box.Height = 10.0
        box.Placement = FreeCAD.Placement(
            FreeCAD.Vector(),
            FreeCAD.Rotation(0.0, 0.0, 90.0),
        )
        body.addObject(box)
        self.Doc.recompute()

        fillet = self.Doc.addObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (
            box,
            [
                "Edge15",
                "Edge13",
                "Edge12",
                "Edge11",
                "Edge4",
                "Edge5",
                "Edge3",
                "Edge2",
                "Face4",
                "Edge19",
                "Edge9",
                "Edge7",
            ],
        )
        fillet.Radius = 8.0
        body.addObject(fillet)
        self.Doc.recompute()
        return body, fillet

    def _find_case_5829_opening_face_name(self, shape):
        candidates = [
            (index, face)
            for index, face in enumerate(shape.Faces, 1)
            if isinstance(face.Surface, Part.Plane) and abs(face.CenterOfMass.y + 10.0) < 1.0e-7
        ]
        self.assertTrue(candidates)
        index, _face = max(candidates, key=lambda item: item[1].Area)
        return "Face" + str(index)

    def testReversedThickness(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.Thickness = self.Doc.addObject("PartDesign::Thickness", "Thickness")
        self.Thickness.Base = (self.Box, ["Face1"])
        self.Body.addObject(self.Thickness)
        self.Doc.recompute()
        self.Thickness.Value = 1.0
        self.Thickness.Reversed = 1
        self.Thickness.Mode = 0
        self.Thickness.Join = 0
        self.Thickness.Base = (self.Box, ["Face1"])
        self.Doc.recompute()
        self.assertEqual(len(self.Thickness.Shape.Faces), 11)
        # 6 faces of outer box + 4 faces of inner box + 16 edges outer, 8 inner,
        # + 8 vertexes outer, 8 inner + 1 solid = 51
        self.assertEqual(self.Thickness.Shape.ElementMapSize, 51)

    def testCase5829ThicknessOnRotatedFillet(self):
        """Verify thickness succeeds on the rotated fillet from issue 5829."""
        body, fillet = self._create_case_5829()
        self.assertTrue(fillet.Shape.isValid())
        self.assertEqual(len(fillet.Shape.Solids), 1)
        self.assertNotEqual(fillet.Placement, FreeCAD.Placement())
        opening = self._find_case_5829_opening_face_name(fillet.Shape)

        thickness = self.Doc.addObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (fillet, [opening])
        thickness.Value = 1.0
        thickness.Reversed = True
        body.addObject(thickness)
        self.Doc.recompute()

        self.assertTrue(thickness.isValid())
        self.assertTrue(thickness.Shape.isValid())
        self.assertEqual(len(thickness.Shape.Solids), 1)
        self.assertEqual(thickness.Placement, fillet.Placement)

    def _cup(self, value):
        """A cylinder Pad, radius 20 and height 10, hollowed from its top face by <value>."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        sketch.AttachmentSupport = (self.Doc.getObject("XY_Plane"), [""])
        sketch.MapMode = "FlatFace"
        sketch.addGeometry(Part.Circle(FreeCAD.Vector(), FreeCAD.Vector(0, 0, 1), 20))
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 10
        self.Doc.recompute()
        top = next(
            "Face" + str(i)
            for i, face in enumerate(pad.Shape.Faces, 1)
            if isinstance(face.Surface, Part.Plane) and abs(face.CenterOfMass.z - 10) < 1e-7
        )
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (pad, [top])
        thickness.Value = value
        self.Doc.recompute()
        return thickness

    def testThicknessLeavesAWall(self):
        """A wall thinner than the cup's height leaves a floor 1 thick (ops#389)."""
        thickness = self._cup(9)
        self.assertTrue(thickness.isValid())
        self.assertTrue(thickness.Shape.isValid())
        # Walls 9 thick: the cavity is radius 11, from z = 9 up to the open top at z = 10
        self.assertAlmostEqual(
            thickness.Shape.Volume, math.pi * 20**2 * 10 - math.pi * 11**2 * 1, places=4
        )

    def testThicknessAsThickAsTheHeightFails(self):
        """A wall as thick as the cup is high leaves no cavity: the feature fails instead of
        keeping an invalid solid (upstream issue 25050, ops#389)."""
        for value in (10, 11):
            with self.subTest(value=value):
                thickness = self._cup(value)
                self.assertFalse(thickness.isValid())
                self.assertIn("invalid", thickness.getStatusString())
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def _pocketedBox(self, x0, y0, depth=3.0, hole=False):
        """A 40 x 30 x 10 box with a 6 x 6 blind pocket at (x0, y0) in its top face, and a
        Thickness removing that top face (it has two wires: the box's and the pocket's). With
        <hole>, a through hole of radius 2 at (8, 8) gives the face a third wire."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length, box.Width, box.Height = 40, 30, 10
        pocket = body.newObject("PartDesign::SubtractiveBox", "Pocket")
        pocket.Length, pocket.Width, pocket.Height = 6, 6, depth
        pocket.Placement.Base = FreeCAD.Vector(x0, y0, 10 - depth)
        base = pocket
        if hole:
            base = body.newObject("PartDesign::SubtractiveCylinder", "Hole")
            base.Radius, base.Height = 2, 10
            base.Placement.Base = FreeCAD.Vector(8, 8, 0)
        self.Doc.recompute()
        self.assertAlmostEqual(
            base.Shape.Volume, 12000 - 36 * depth - (40 * math.pi if hole else 0), places=6
        )
        top = [
            "Face" + str(i)
            for i, face in enumerate(base.Shape.Faces, 1)
            if isinstance(face.Surface, Part.Plane)
            and abs(face.CenterOfMass.z - 10) < 1e-7
            and len(face.Wires) == (3 if hole else 2)
        ]
        self.assertEqual(len(top), 1)
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (base, top)
        return thickness

    @staticmethod
    def _pocketShellVolume(t, join, outward=False, a=6.0, d=3.0):
        """The shell's volume, defined geometrically: the open box's walls (the material within
        t of its kept faces) plus the band of the pocket's walls and floor, a cup."""
        if outward:
            box = (40 + 2 * t) * (30 + 2 * t) * (10 + t) - 40 * 30 * 10
            if join == "Arc":
                # the outer skin of a box with rounded edges and corners, its top cut flat
                box = (
                    2 * (40 + 30) * 10 * t
                    + 40 * 30 * t
                    + math.pi * t * t / 4 * (2 * (40 + 30) + 4 * 10)
                    + 4 / 8 * 4 / 3 * math.pi * t**3
                )
            # the lining inside the pocket, its edges sharp either way (the pocket's are concave)
            return box + a * a * d - (a - 2 * t) ** 2 * (d - t)
        box = 40 * 30 * 10 - (40 - 2 * t) * (30 - 2 * t) * (10 - t)
        if join == "Arc":
            # the pocket grown by a ball of radius t below the top: slabs on the walls and the
            # floor, quarter cylinders on its concave edges and eighth spheres at its corners
            cup = (
                4 * a * d * t
                + a * a * t
                + math.pi * t * t / 4 * (4 * a + 4 * d)
                + 4 / 8 * 4 / 3 * math.pi * t**3
            )
        else:
            cup = (a + 2 * t) ** 2 * (d + t) - a * a * d
        return box + cup

    def testShellOfAPocketedFace(self):
        """A shell removing a face with a blind pocket builds: the pocket's walls and floor are
        shelled into a cup inside the open box (ops#640, F46; OCCT refuses it, the kept faces
        falling apart once the face is gone). The corner pocket's cup reaches the box's walls at
        1 mm; the centred one stands free."""
        for (x0, y0), value, join, reversed_ in (
            ((2, 2), 1.0, "Arc", True),
            ((2, 2), 1.0, "Intersection", True),
            ((2, 2), 0.5, "Arc", True),
            ((17, 12), 1.0, "Arc", True),
            ((17, 12), 1.0, "Intersection", True),
            ((17, 12), 1.0, "Intersection", False),
            ((17, 12), 0.5, "Arc", False),
        ):
            with self.subTest(pocket=(x0, y0), value=value, join=join, inward=reversed_):
                thickness = self._pocketedBox(x0, y0)
                thickness.Value = value
                thickness.Join = join
                thickness.Reversed = reversed_
                self.Doc.recompute()
                self.assertTrue(thickness.isValid(), thickness.getStatusString())
                shape = thickness.Shape
                self.assertTrue(shape.isValid())
                expected = self._pocketShellVolume(value, join, outward=not reversed_)
                self.assertLess(abs(shape.Volume - expected) / expected, 1e-6)
                # open at the top, nothing above it, the cup inside the box
                self.assertAlmostEqual(shape.BoundBox.ZMax, 10, places=6)
                self.assertGreater(len(shape.Solids), 0)
                # named through the element map, as any shell
                self.assertGreater(shape.ElementMapSize, 0)
                # a cup wall beside the pocket (inward) or a lining inside it (outward)
                wall = x0 - value / 2 if reversed_ else x0 + value / 2
                self.assertTrue(shape.isInside(FreeCAD.Vector(wall, y0 + 3, 9), 1e-6, False))
                self.assertFalse(shape.isInside(FreeCAD.Vector(30, 25, 5), 1e-6, False))
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testShellOfAPocketedFaceInASingleSolidBody(self):
        """With the single-solid rule on, a shell that falls apart (the centred pocket's cup
        stands free in the open box) fails instead of keeping the box alone; the corner pocket's
        cup reaches the box's walls at 1 mm, one solid (ops#640, review of F46)."""
        for (x0, y0), valid in (((17, 12), False), ((2, 2), True)):
            with self.subTest(pocket=(x0, y0)):
                thickness = self._pocketedBox(x0, y0)
                self.Doc.getObject("Body").AllowCompound = False
                thickness.Value = 1.0
                self.Doc.recompute()
                self.assertEqual(thickness.isValid(), valid, thickness.getStatusString())
                if valid:
                    self.assertEqual(len(thickness.Shape.Solids), 1)
                    expected = self._pocketShellVolume(1.0, "Arc")
                    self.assertLess(abs(thickness.Shape.Volume - expected) / expected, 1e-6)
                else:
                    self.assertIn("multiple solids", thickness.getStatusString())
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testShellOfAFaceWithAPocketAndAThroughHole(self):
        """The removed face has three wires and the kept faces two groups: a through hole's walls
        join the box's faces through the bottom, so the hole's wire closes the box with the
        outer one, and the blind pocket's wire its cup (ops#640, review of F46)."""
        for join in ("Arc", "Intersection"):
            with self.subTest(join=join):
                thickness = self._pocketedBox(17, 12, hole=True)
                thickness.Value = 1.0
                thickness.Join = join
                self.Doc.recompute()
                self.assertTrue(thickness.isValid(), thickness.getStatusString())
                shape = thickness.Shape
                self.assertTrue(shape.isValid())
                # the open box less the hole through its floor, the hole's wall band (radius 2 to
                # 3, above the floor) and the pocket's cup
                expected = (
                    self._pocketShellVolume(1.0, join)
                    - math.pi * 2**2 * 1
                    + math.pi * (3**2 - 2**2) * 9
                )
                self.assertLess(abs(shape.Volume - expected) / expected, 1e-6)
                self.assertAlmostEqual(shape.BoundBox.ZMax, 10, places=6)
                self.assertTrue(shape.isInside(FreeCAD.Vector(8, 10.5, 5), 1e-6, False))
                self.assertFalse(shape.isInside(FreeCAD.Vector(8, 8, 5), 1e-6, False))
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testShellWithoutAPocketUnchanged(self):
        """The shell OCCT builds is its own: the same box without the pocket keeps 2424 mm^3."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length, box.Width, box.Height = 40, 30, 10
        self.Doc.recompute()
        top = next(
            "Face" + str(i)
            for i, face in enumerate(box.Shape.Faces, 1)
            if abs(face.CenterOfMass.z - 10) < 1e-7
        )
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (box, [top])
        thickness.Value = 1.0
        self.Doc.recompute()
        self.assertTrue(thickness.isValid())
        self.assertAlmostEqual(thickness.Shape.Volume, 2424.0, places=6)
        self.assertEqual(len(thickness.Shape.Faces), 11)

    def _plateWithHoles(self, holes, join="Arc", t=1.5):
        """A 120 x 80 x 10 plate with through holes of diameter 6 at the (x, y) of <holes>, and
        a Thickness of <t> inwards removing its bottom face. Returns the feature and the shell
        defined geometrically: the plate without the block that leaves walls of <t> at the sides
        and the top, where that block in turn leaves a wall of <t> around each hole."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        base = body.newObject("PartDesign::AdditiveBox", "Plate")
        base.Length, base.Width, base.Height = 120, 80, 10
        plate = Part.makeBox(120, 80, 10)
        cavity = Part.makeBox(120 - 2 * t, 80 - 2 * t, 10 - t, FreeCAD.Vector(t, t, 0))
        for x, y in holes:
            base = body.newObject("PartDesign::SubtractiveCylinder", "Hole")
            base.Radius, base.Height = 3, 10
            base.Placement.Base = FreeCAD.Vector(x, y, 0)
            plate = plate.cut(Part.makeCylinder(3, 10, FreeCAD.Vector(x, y, 0)))
            cavity = cavity.cut(Part.makeCylinder(3 + t, 10, FreeCAD.Vector(x, y, 0)))
        self.Doc.recompute()
        self.assertAlmostEqual(base.Shape.Volume, plate.Volume, places=6)
        bottom = [
            "Face" + str(i)
            for i, face in enumerate(base.Shape.Faces, 1)
            if isinstance(face.Surface, Part.Plane) and abs(face.CenterOfMass.z) < 1e-7
        ]
        self.assertEqual(len(bottom), 1)
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (base, bottom)
        thickness.Value = t
        thickness.Join = join
        self.Doc.recompute()
        return thickness, plate.cut(cavity)

    def _assertShell(self, thickness, expected):
        self.assertTrue(thickness.isValid(), thickness.getStatusString())
        shape = thickness.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertLess(abs(shape.Volume - expected.Volume), 1e-6 * expected.Volume)
        self.assertLess(shape.cut(expected).Volume + expected.cut(shape).Volume, 1e-4)

    def testShellOfAPlateWithAHoleNearItsWall(self):
        """A hole 5 from the plate's side: the wall of 1.5 around it (radius 4.5) runs into the
        side's wall, 3.5 from the hole's axis. The shell builds, the two walls merged (ops#795;
        OCCT's plain mode returns an invalid shell there, or none with the Intersection join)."""
        for join in ("Arc", "Intersection"):
            with self.subTest(join=join):
                thickness, expected = self._plateWithHoles([(60, 5)], join)
                # the hole's wall less its segment beyond the side wall's inner plane
                segment = 4.5**2 * math.acos(3.5 / 4.5) - 3.5 * math.sqrt(4.5**2 - 3.5**2)
                volume = (
                    (120 * 80 * 10 - 117 * 77 * 8.5)
                    + (math.pi * (4.5**2 - 3**2) - segment) * 8.5
                    - math.pi * 3**2 * 1.5
                )
                self.assertAlmostEqual(expected.Volume, volume, places=6)
                self._assertShell(thickness, expected)
                self.assertFalse(thickness.Intersection)
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testShellOfAPlateWithHolesNearACornerAndEachOther(self):
        """A hole 5 from two sides, two holes 8 apart (their walls of radius 4.5 overlap) and a
        row of three along a side: each builds as the walls merged (ops#795)."""
        for holes in ([(5, 5)], [(60, 40), (68, 40)], [(10, 5), (22, 5), (34, 5)]):
            with self.subTest(holes=holes):
                thickness, expected = self._plateWithHoles(holes)
                self._assertShell(thickness, expected)
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testShellOfAPlateWithAHoleApartUnchanged(self):
        """A hole whose wall stays clear of the sides is OCCT's plain shell, as before:
        19681.503 mm^3 mid-plate, and the same 6.5 from a side (clear by 0.5)."""
        for y in (40, 6.5):
            with self.subTest(y=y):
                thickness, expected = self._plateWithHoles([(60, y)])
                self._assertShell(thickness, expected)
                self.assertAlmostEqual(
                    thickness.Shape.Volume,
                    (120 * 80 * 10 - 117 * 77 * 8.5)
                    + math.pi * (4.5**2 - 3**2) * 8.5
                    - math.pi * 3**2 * 1.5,
                    places=5,
                )
                self.assertEqual(len(thickness.Shape.Faces), 14)
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testShellRefusalsSayWhatHelps(self):
        """Where no mode of OCCT's builds the shell, the feature fails and says what helps. With
        OCCT 8.0.1 on Windows a hole's wall tangent to the side's wall (6 from the side) fails
        with either join (the intersecting mode returns the plate as it was there, which is
        never taken for the shell, ops#795). Where a kernel builds one, it is the shell."""
        for holes, join in (
            ([(60, 6)], "Arc"),
            ([(60, 6)], "Intersection"),
        ):
            with self.subTest(holes=holes, join=join):
                thickness, expected = self._plateWithHoles(holes, join)
                if thickness.isValid():
                    self._assertShell(thickness, expected)
                else:
                    self.assertIn("opposite direction", thickness.getStatusString())
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testShellWithTheIntersectionJoinAndAHoleNearACorner(self):
        """The Intersection join with the hole 5 from two sides, which no mode of OCCT's
        thick-solid builder builds: the cavity is built with the open face held in place
        (ops#811). It is the Arc join's shell there, but for the sliver of cavity the hole's
        wall cuts off in the corner (0.21 mm^2 across, between the two side walls' inner
        planes and the hole's wall of radius 4.5): OCCT's offset of the whole solid leaves
        that out, so the corner stays solid, 1.781 mm^3 more than designed. Debt, and never
        a wall thinner than asked."""
        thickness, expected = self._plateWithHoles([(5, 5)], "Intersection")
        self.assertTrue(thickness.isValid(), thickness.getStatusString())
        shape = thickness.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertLess(expected.cut(shape).Volume, 1e-4)
        # the sliver's section: within 3.5 of the hole's axis along x and along y, outside
        # the radius 4.5; the cavity is 8.5 high
        reach = math.sqrt(4.5**2 - 3.5**2)
        area = 3.5 * (3.5 - reach) - 4.5**2 / 2 * (math.asin(3.5 / 4.5) - math.asin(reach / 4.5))
        self.assertAlmostEqual(shape.cut(expected).Volume, area * 8.5, places=4)

    def _outwardShellOfABlockWithAPocket(self, length, width, height, pocket, join, removeTop):
        """A <length> x <width> x <height> block with a through pocket <pocket> = (x, y, dx, dy),
        shelled outward by 1.5 with <join>, its top (or bottom) face removed."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length, block.Width, block.Height = length, width, height
        x, y, dx, dy = pocket
        hole = body.newObject("PartDesign::SubtractiveBox", "Pocket")
        hole.Length, hole.Width, hole.Height = dx, dy, height
        hole.Placement.Base = FreeCAD.Vector(x, y, 0)
        self.Doc.recompute()
        z = height if removeTop else 0
        removed = [
            "Face" + str(i)
            for i, face in enumerate(hole.Shape.Faces, 1)
            if isinstance(face.Surface, Part.Plane) and abs(face.CenterOfMass.z - z) < 1e-7
        ]
        self.assertEqual(len(removed), 1)
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (hole, removed)
        thickness.Value = 1.5
        thickness.Join = join
        thickness.Reversed = False
        self.Doc.recompute()
        return thickness

    def testOutwardShellOfABlockWithARectangularPocket(self):
        """Onshape's SL1 (oracle 25): a 40 x 30 x 20 block with a 10 x 20 through pocket, top
        removed, shelled outward by 1.5, keeps sharp corners: 20 planar faces, V 7950 =
        43*33*21.5 - 7*17*21.5 - 20000. OCCT's Arc join gives an invalid solid there in both
        modes, so the Intersection join is built (ops#807); with it the result is the same."""
        for join in ("Arc", "Intersection"):
            with self.subTest(join=join):
                thickness = self._outwardShellOfABlockWithAPocket(
                    40, 30, 20, (15, 5, 10, 20), join, True
                )
                self.assertTrue(thickness.isValid(), thickness.getStatusString())
                shape = thickness.Shape
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids), 1)
                self.assertAlmostEqual(shape.Volume, 43 * 33 * 21.5 - 7 * 17 * 21.5 - 20000, places=5)
                self.assertEqual(len(shape.Faces), 20)
                self.assertTrue(all(isinstance(f.Surface, Part.Plane) for f in shape.Faces))
                box = shape.BoundBox
                for got, want in zip(
                    (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax),
                    (-1.5, -1.5, -1.5, 41.5, 31.5, 20),
                ):
                    self.assertAlmostEqual(got, want, places=6)
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testOutwardShellOfAPlateWithARectangularPocket(self):
        """ops#807's smallest case: a 120 x 80 x 10 plate with a 10 x 20 through pocket, bottom
        removed, outward 1.5 with the Arc join: built sharp, V 22035 = 123*83*11.5 -
        7*17*11.5 - (120*80 - 200)*10."""
        thickness = self._outwardShellOfABlockWithAPocket(
            120, 80, 10, (55, 30, 10, 20), "Arc", False
        )
        self.assertTrue(thickness.isValid(), thickness.getStatusString())
        self.assertTrue(thickness.Shape.isValid())
        self.assertAlmostEqual(
            thickness.Shape.Volume, 123 * 83 * 11.5 - 7 * 17 * 11.5 - 9400 * 10, places=5
        )

    def testOutwardArcShellOfAPlateWithARoundHoleStaysRound(self):
        """Where OCCT's Arc join builds the outward shell, it is kept: a plate 120 x 80 x 10 with
        a hole d6, bottom removed, outward 1.5 has rounded outer edges (not all faces planar)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        plate = body.newObject("PartDesign::AdditiveBox", "Plate")
        plate.Length, plate.Width, plate.Height = 120, 80, 10
        hole = body.newObject("PartDesign::SubtractiveCylinder", "Hole")
        hole.Radius, hole.Height = 3, 10
        hole.Placement.Base = FreeCAD.Vector(60, 40, 0)
        self.Doc.recompute()
        bottom = [
            "Face" + str(i)
            for i, face in enumerate(hole.Shape.Faces, 1)
            if isinstance(face.Surface, Part.Plane) and abs(face.CenterOfMass.z) < 1e-7
        ]
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (hole, bottom)
        thickness.Value = 1.5
        thickness.Join = "Arc"
        thickness.Reversed = False
        self.Doc.recompute()
        self.assertTrue(thickness.isValid(), thickness.getStatusString())
        self.assertTrue(thickness.Shape.isValid())
        self.assertFalse(all(isinstance(f.Surface, Part.Plane) for f in thickness.Shape.Faces))

    def _steppedBlock(self, low, high, opened, t, join="Arc", reversed_=True):
        """A block <low> = (length, width, height) with a step <high> = (x0, y0, length, width,
        height) standing on its top, and a Thickness of <t> (inward unless <reversed_> is
        False) removing the face of the block's top that holds the point <opened>. Returns
        the feature and the stepped block's shape."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length, block.Width, block.Height = low
        step = body.newObject("PartDesign::AdditiveBox", "Step")
        step.Length, step.Width, step.Height = high[2:]
        step.Placement.Base = FreeCAD.Vector(high[0], high[1], low[2])
        step.Refine = True
        self.Doc.recompute()
        solid = Part.makeBox(*low).fuse(
            Part.makeBox(*high[2:], FreeCAD.Vector(high[0], high[1], low[2]))
        )
        self.assertAlmostEqual(step.Shape.Volume, solid.Volume, places=6)
        self.assertEqual(len(step.Shape.Faces), 8)
        point = Part.Vertex(FreeCAD.Vector(*opened))
        top = [
            "Face" + str(i)
            for i, face in enumerate(step.Shape.Faces, 1)
            if isinstance(face.Surface, Part.Plane)
            and abs(face.normalAt(0, 0).z) > 0.99
            and face.distToShape(point)[0] < 1e-7
        ]
        self.assertEqual(len(top), 1)
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (step, top)
        thickness.Value = t
        thickness.Reversed = reversed_
        thickness.Join = join
        self.Doc.recompute()
        return thickness, solid

    def testShellOfAnLBlockFromItsStep(self):
        """An L-block, 40 x 20 x 10 with a 20 x 20 x 10 block on the half x 0..20 of its top,
        shelled 2 inward from the other half of that top (x 20..40, z 10). The whole L is
        shelled: walls of 2 everywhere, the cavity 36 x 16 x 8 under the open face and on under
        the upper block's wall, and 16 x 16 x 8 in the upper block. The cavity's ceiling
        x 18..20 at z 10 lies on the removed face's own plane, a face OCCT's thick-solid
        builder cannot make: it hands the L back unchanged, 12000 mm^3, with either join and
        in both modes. Onshape builds 5344.000 mm^3 with 16 faces (oracle 25, SL2; ops#811)."""
        for join in ("Arc", "Intersection"):
            with self.subTest(join=join):
                thickness, solid = self._steppedBlock(
                    (40, 20, 10), (0, 0, 20, 20, 10), (30, 10, 10), 2, join
                )
                self.assertAlmostEqual(solid.Volume, 12000, places=6)
                cavity = Part.makeBox(36, 16, 8, FreeCAD.Vector(2, 2, 2)).fuse(
                    Part.makeBox(16, 16, 8, FreeCAD.Vector(2, 2, 10))
                )
                expected = solid.cut(cavity)
                self.assertAlmostEqual(
                    expected.Volume, 12000 - (36 * 16 * 8 + 16 * 16 * 8), places=6
                )
                self.assertAlmostEqual(expected.Volume, 5344, places=6)
                self._assertShell(thickness, expected)
                self.assertEqual(len(thickness.Shape.Faces), 16)
                # every face of the composed shell is named
                names = thickness.Shape.ElementReverseMap
                for i in range(1, 17):
                    self.assertIn("Face" + str(i), names)
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testShellFromAStepAsHighAsTheWall(self):
        """A block 20 x 10 x 10 with a step 2 high on the back half of its top (y 5..10),
        shelled 1 inward from the front half (the naming scenario StepDeletedFacesMerge's
        model, which OCCT handed back unchanged, 2200 mm^3). The cavity: the block's, 1 from
        its sides and floor, open to z 10 in front of the step's wall offset to y 6, and on up
        into the step behind it, 1 under its top (ops#811)."""
        thickness, solid = self._steppedBlock((20, 10, 10), (0, 5, 20, 5, 2), (10, 2.5, 10), 1)
        self.assertAlmostEqual(solid.Volume, 2200, places=6)
        cavity = Part.makeBox(18, 5, 9, FreeCAD.Vector(1, 1, 1)).fuse(
            Part.makeBox(18, 3, 10, FreeCAD.Vector(1, 6, 1))
        )
        expected = solid.cut(cavity)
        self.assertAlmostEqual(expected.Volume, 2200 - (18 * 5 * 9 + 18 * 3 * 10), places=6)
        self._assertShell(thickness, expected)

    def testShellFromAStepLowerThanTheWallIsRefused(self):
        """The same with the step 0.5 high, half the wall of 1: the step's wall has no offset
        face (it would stand upside down), and the cavity built without it runs on under the
        step's top, 0.5 below it, where a wall of 1 is asked. That is refused: the feature fails
        and says what helps (ops#811). Onshape builds one there (a 40 x 20 x 10 block with a
        step 1 high, 2 inward: 8400 -> 4048.000, 16 faces, oracle 26, SL7), with the strip
        under the step's wall half as thick as asked; OCCT's offset gives another solid, so
        this stays debt. Where a kernel builds a shell, it is smaller."""
        thickness, solid = self._steppedBlock((20, 10, 10), (0, 5, 20, 5, 0.5), (10, 2.5, 10), 1)
        if thickness.isValid():
            self.assertTrue(thickness.Shape.isValid())
            self.assertLess(thickness.Shape.Volume, solid.Volume - 1)
            self.fail("a shell from a step lower than the wall: check it and pin it here")
        self.assertIn("opposite direction", thickness.getStatusString())

    def testShellFromAStepExactlyAsHighAsTheThickness(self):
        """A 40 x 20 x 10 block with a step 2 high on half its top, shelled 2 inward from the
        other half: the step is the cavity's roof there, 2 thick, and the cavity 36 x 16 x 8
        runs under it whole (ops#811)."""
        thickness, solid = self._steppedBlock((40, 20, 10), (0, 0, 20, 20, 2), (30, 10, 10), 2)
        self.assertAlmostEqual(solid.Volume, 8800, places=6)
        expected = solid.cut(Part.makeBox(36, 16, 8, FreeCAD.Vector(2, 2, 2)))
        self.assertAlmostEqual(expected.Volume, 8800 - 36 * 16 * 8, places=6)
        self._assertShell(thickness, expected)

    def testShellBesideAStepWithAGrooveOrAHoleJustAboveTheOpenFaceIsRefused(self):
        """The L-block with a groove across the step's wall (x 18..20, z 10.5..11) or a blind
        hole into it (r 1, 5 deep, axis at z 11.5): either lies 0.5 above the cavity's strip
        under the step's wall, where 2 is asked. Refused (ops#811, the review's finds)."""
        for cut in (
            Part.makeBox(2, 20, 0.5, FreeCAD.Vector(18, 0, 10.5)),
            Part.makeCylinder(1, 5, FreeCAD.Vector(15, 10, 11.5), FreeCAD.Vector(1, 0, 0)),
        ):
            with self.subTest(cut=cut.Volume):
                solid, faceAt = self._lBlock()
                solid = solid.cut(cut)
                self.assertTrue(solid.isValid())
                top = faceAt(solid, 30, 10, 10)
                with self.assertRaises(Exception):
                    solid.makeThickness([top], -2, 1e-7, False, False, 0, 0)

    def _lBlockCavity(self):
        """The cavity of the L-block shelled 2 inward from its low top: 6656 mm^3."""
        return Part.makeBox(36, 16, 8, FreeCAD.Vector(2, 2, 2)).fuse(
            Part.makeBox(16, 16, 8, FreeCAD.Vector(2, 2, 10))
        )

    def _assertBuiltShell(self, shell, expected, volume, solids=1):
        """The shell is the solid defined by construction, of the closed-form volume."""
        self.assertTrue(shell.isValid())
        self.assertEqual(len(shell.Solids), solids)
        self.assertAlmostEqual(expected.Volume, volume, places=6)
        self.assertLess(abs(shell.Volume - volume), 1e-6 * volume)
        self.assertLess(shell.cut(expected).Volume + expected.cut(shell).Volume, 1e-4)

    def testShellFromAFaceWithAPocketABossOrAHoleBesideAStep(self):
        """The L-block with a pocket 6 x 6 x 3 in the open face, a boss (r 4, 5 high) on it or
        a through hole (r 3) in it. With the pocket or the boss the kept faces fall apart, and
        of the pieces shelled one by one OCCT hands the L's own back unchanged, which once gave
        the solid unshelled (11892 mm^3); with the hole OCCT fails. Each is the L's shell now
        (ops#811): the cavity keeps 2 from the pocket (a cup 10 x 10 x 5, standing free), runs
        up into the boss (r 2, to 2 under its top; the boss's tube stands free on the opening)
        or keeps 2 from the hole (r 5)."""
        solid, faceAt = self._lBlock()
        cavity = self._lBlockCavity()
        for name, part, hollow, volume, solids in (
            (
                "pocket",
                solid.cut(Part.makeBox(6, 6, 3, FreeCAD.Vector(27, 7, 7))),
                cavity.cut(Part.makeBox(10, 10, 5, FreeCAD.Vector(25, 5, 5))),
                (12000 - 108) - (6656 - 10 * 10 * 5),
                2,
            ),
            (
                "boss",
                solid.fuse(Part.makeCylinder(4, 5, FreeCAD.Vector(30, 10, 10))).removeSplitter(),
                cavity.fuse(Part.makeCylinder(2, 5, FreeCAD.Vector(30, 10, 8))),
                (12000 + math.pi * 16 * 5) - (6656 + math.pi * 4 * 3),
                2,
            ),
            (
                "hole",
                solid.cut(Part.makeCylinder(3, 10, FreeCAD.Vector(30, 10, 0))),
                cavity.cut(Part.makeCylinder(5, 20, FreeCAD.Vector(30, 10, 0))),
                (12000 - math.pi * 9 * 10) - (6656 - math.pi * 25 * 8),
                1,
            ),
        ):
            with self.subTest(name=name):
                top = faceAt(part, 22, 2, 10)
                shell = part.makeThickness([top], -2, 1e-7, False, False, 0, 2)
                self._assertBuiltShell(shell, part.cut(hollow), volume, solids)

    def testShellBesideAStepOverAHoleFromBelow(self):
        """The L-block with a blind hole from its bottom under the open face (r 1 at (30, 10),
        to z 7): the cavity keeps 2 from the hole and from its cap (r 3, to z 9), 5519.929 mm^3
        as in Onshape (oracle 26). The shell composed from prisms left a column standing to
        the open face there, 5548.204 (ops#811, ops#839)."""
        solid, faceAt = self._lBlock()
        part = solid.cut(Part.makeCylinder(1, 7, FreeCAD.Vector(30, 10, 0)))
        hollow = self._lBlockCavity().cut(Part.makeCylinder(3, 9, FreeCAD.Vector(30, 10, 0)))
        shell = part.makeThickness([faceAt(part, 22, 2, 10)], -2, 1e-7, False, False, 0, 2)
        volume = (12000 - math.pi * 7) - (6656 - math.pi * 9 * 7)
        self.assertAlmostEqual(volume, 5519.929, places=3)
        self._assertBuiltShell(shell, part.cut(hollow), volume)

    def testShellFromAValleyBetweenTwoSteps(self):
        """A block 60 x 20 x 10 with a step at each end of its top (x 0..20, 10 high, and
        x 40..60, 5 high), shelled 2 inward from the valley's floor between them: both steps
        are hollowed, each through the strip under its wall (ops#811)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length, block.Width, block.Height = 60, 20, 10
        left = body.newObject("PartDesign::AdditiveBox", "Left")
        left.Length, left.Width, left.Height = 20, 20, 10
        left.Placement.Base = FreeCAD.Vector(0, 0, 10)
        right = body.newObject("PartDesign::AdditiveBox", "Right")
        right.Length, right.Width, right.Height = 20, 20, 5
        right.Placement.Base = FreeCAD.Vector(40, 0, 10)
        right.Refine = True
        self.Doc.recompute()
        self.assertAlmostEqual(right.Shape.Volume, 18000, places=6)
        floor = [
            "Face" + str(i)
            for i, face in enumerate(right.Shape.Faces, 1)
            if isinstance(face.Surface, Part.Plane)
            and abs(face.CenterOfMass.z - 10) < 1e-7
            and abs(face.CenterOfMass.x - 30) < 1e-7
        ]
        self.assertEqual(len(floor), 1)
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (right, floor)
        thickness.Value = 2
        thickness.Reversed = True
        self.Doc.recompute()
        cavity = Part.makeBox(56, 16, 8, FreeCAD.Vector(2, 2, 2)).fuse(
            [
                Part.makeBox(16, 16, 8, FreeCAD.Vector(2, 2, 10)),
                Part.makeBox(16, 16, 3, FreeCAD.Vector(42, 2, 10)),
            ]
        )
        expected = right.Shape.cut(cavity)
        self.assertAlmostEqual(expected.Volume, 18000 - (56 * 16 * 8 + 16 * 16 * 8 + 16 * 16 * 3), places=6)
        self._assertShell(thickness, expected)

    def testShellWithTheIntersectionJoinAndAHoleNearItsWall(self):
        """The Intersection join with a hole 4.4 or 4 from the plate's side: OCCT handed the
        plate back unchanged in both modes, and the feature showed it as the shell. It is the
        shell the Arc join builds there, the hole's wall merged with the side's (ops#811)."""
        for y in (4.4, 4):
            with self.subTest(y=y):
                thickness, expected = self._plateWithHoles([(60, y)], "Intersection")
                self._assertShell(thickness, expected)
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testTheSolidUnchangedIsNeverItsShell(self):
        """Outward from the L-block's step with the Intersection join OCCT hands the L back
        too (12000 mm^3, and invalid), and nothing composes an outward shell: the feature
        fails and says what helps, it never shows the solid as shelled (ops#811). Where a
        kernel builds one, it differs from the L."""
        thickness, solid = self._steppedBlock(
            (40, 20, 10), (0, 0, 20, 20, 10), (30, 10, 10), 2, "Intersection", False
        )
        if thickness.isValid():
            self.assertTrue(thickness.Shape.isValid())
            self.assertGreater(abs(thickness.Shape.Volume - solid.Volume), 1)
        else:
            self.assertIn("opposite direction", thickness.getStatusString())

    def testAnOutwardShellWithItsSolidsVolumeIsAShell(self):
        """A box 6 x 6 x 8 shelled 1 outward from its top is a band of 8 x 8 x 9 less the box:
        288 mm^3, the box's own volume. And a box 40 x 20 x 12 with a pocket 6 x 6 x 8 in its
        top, shelled 1 inward from the top: the pocket's cup, built outward around the hollow,
        has the hollow's 288 too. Neither is taken for a solid handed back (ops#811, the
        review's finds)."""
        box = Part.makeBox(6, 6, 8)
        top = [face for face in box.Faces if abs(face.CenterOfMass.z - 8) < 1e-7]
        shell = box.makeThickness(top, 1, 1e-7, False, False, 0, 2)
        self.assertTrue(shell.isValid())
        self.assertAlmostEqual(shell.Volume, 8 * 8 * 9 - 6 * 6 * 8, places=6)
        self.assertAlmostEqual(shell.Volume, box.Volume, places=6)
        pocketed = Part.makeBox(40, 20, 12).cut(Part.makeBox(6, 6, 8, FreeCAD.Vector(27, 7, 4)))
        top = [
            face
            for face in pocketed.Faces
            if abs(face.CenterOfMass.z - 12) < 1e-7 and abs(face.normalAt(0, 0).z) > 0.99
        ]
        self.assertEqual(len(top), 1)
        shell = pocketed.makeThickness(top, -1, 1e-7, False, False, 0, 2)
        self.assertTrue(shell.isValid())
        # the box's walls and floor, and the cup: walls and a floor of 1 around the pocket
        expected = (40 * 20 * 12 - 38 * 18 * 11) + (8 * 8 * 9 - 6 * 6 * 8)
        self.assertAlmostEqual(shell.Volume, 2364, places=4)
        self.assertAlmostEqual(expected, 2364, places=6)

    def testShellBesideAStepWithALeaningWall(self):
        """The L-block with a leaning wall beside the open face: its outer side (x 40 at the
        floor and 36 at the open face, or 36 and 40) or the step's wall (x 22 at the open face
        and 18 at the top, or 18 and 22). The cavity's wall is the leaning wall's offset, 2
        along its normal, up to the open face's plane (ops#811). The first is Onshape's
        5270.920 mm^3 with 16 faces (oracle 26, SL5)."""
        k = 2 * math.sqrt(116)  # the offset 2 along the normal (10, 4) / sqrt(116), times 116

        def area(profile):
            ahead = profile[1:] + profile[:1]
            return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(profile, ahead))) / 2

        def prism(profile, y, width):
            points = [FreeCAD.Vector(x, y, z) for x, z in profile + profile[:1]]
            return Part.Face(Part.makePolygon(points)).extrude(FreeCAD.Vector(0, width, 0))

        for profile, hollow in (
            (
                [(0, 0), (40, 0), (36, 10), (20, 10), (20, 20), (0, 20)],
                [(2, 2), ((392 - k) / 10, 2), ((360 - k) / 10, 10), (18, 10), (18, 18), (2, 18)],
            ),
            (
                [(0, 0), (36, 0), (40, 10), (20, 10), (20, 20), (0, 20)],
                [(2, 2), ((368 - k) / 10, 2), ((400 - k) / 10, 10), (18, 10), (18, 18), (2, 18)],
            ),
            (
                [(0, 0), (40, 0), (40, 10), (22, 10), (18, 20), (0, 20)],
                [(2, 2), (38, 2), (38, 10), ((220 - k) / 10, 10), ((188 - k) / 10, 18), (2, 18)],
            ),
            (
                [(0, 0), (40, 0), (40, 10), (18, 10), (22, 20), (0, 20)],
                [(2, 2), (38, 2), (38, 10), ((180 - k) / 10, 10), ((212 - k) / 10, 18), (2, 18)],
            ),
        ):
            with self.subTest(profile=profile):
                solid = prism(profile, 0, 20)
                self.assertTrue(solid.isValid())
                opened = [
                    face
                    for face in solid.Faces
                    if abs(face.CenterOfMass.z - 10) < 1e-7 and abs(face.normalAt(0, 0).z) > 0.99
                ]
                self.assertEqual(len(opened), 1)
                shell = solid.makeThickness(opened, -2, 1e-7, False, False, 0, 2)
                volume = area(profile) * 20 - area(hollow) * 16
                self._assertBuiltShell(shell, solid.cut(prism(hollow, 2, 16)), volume)
                self.assertEqual(len(shell.Faces), 16)
        self.assertAlmostEqual(
            580 * 20 - area([(2, 2), ((392 - k) / 10, 2), ((360 - k) / 10, 10), (18, 10), (18, 18), (2, 18)]) * 16,
            5270.920,
            places=3,
        )

    def _lBlock(self):
        """The L-block of testShellOfAnLBlockFromItsStep as a plain solid, and a function
        giving its planar face through a point."""
        solid = (
            Part.makeBox(40, 20, 10)
            .fuse(Part.makeBox(20, 20, 10, FreeCAD.Vector(0, 0, 10)))
            .removeSplitter()
        )
        self.assertEqual(len(solid.Faces), 8)

        def faceAt(shape, x, y, z):
            point = Part.Vertex(FreeCAD.Vector(x, y, z))
            found = [
                face
                for face in shape.Faces
                if isinstance(face.Surface, Part.Plane) and face.distToShape(point)[0] < 1e-7
            ]
            self.assertEqual(len(found), 1)
            return found[0]

        return solid, faceAt


    def testShellFromTwoTouchingFacesBesideAStep(self):
        """The L-block shelled 2 inward from the step's top and a face next to it: the end
        (x 40) or a side (y 0). Both open faces stay where they are and the cavity runs out
        through each: 5088 mm^3 with 16 faces, as in Onshape (oracle 26, SL6), and 4512
        (ops#811)."""
        solid, faceAt = self._lBlock()
        top = faceAt(solid, 30, 10, 10)
        for other, cavity, volume in (
            (
                faceAt(solid, 40, 10, 5),
                Part.makeBox(38, 16, 8, FreeCAD.Vector(2, 2, 2)).fuse(
                    Part.makeBox(16, 16, 8, FreeCAD.Vector(2, 2, 10))
                ),
                12000 - (38 * 16 * 8 + 16 * 16 * 8),
            ),
            (
                faceAt(solid, 30, 0, 5),
                Part.makeBox(36, 18, 8, FreeCAD.Vector(2, 0, 2)).fuse(
                    Part.makeBox(16, 18, 16, FreeCAD.Vector(2, 0, 2))
                ),
                12000 - (36 * 18 * 8 + 16 * 18 * 8),
            ),
        ):
            with self.subTest(other=other.CenterOfMass):
                shell = solid.makeThickness([top, other], -2, 1e-7, False, False, 0, 0)
                self._assertBuiltShell(shell, solid.cut(cavity), volume)
        self.assertEqual(12000 - (38 * 16 * 8 + 16 * 16 * 8), 5088)

    def testShellBesideAStepWithAChamferOnTheOpenFace(self):
        """The L-block with a chamfer on an edge of the open face: 0.5 or 1 on its side edge
        (y 0, z 10) or 1 on its end edge (x 40, z 10). The cavity keeps 2 from the chamfer
        along its normal: a corner with legs of the chamfer's size + 2 sqrt(2) - 2 stays, along
        the cavity's 20 (the side, on under the step's wall) or 16 (the end). The last is
        Onshape's 5360.745 mm^3 with 18 faces (oracle 26, SL4; ops#811)."""
        for size, where, length in ((0.5, "side", 20), (1.0, "side", 20), (1.0, "end", 16)):
            with self.subTest(size=size, where=where):
                solid, faceAt = self._lBlock()
                edges = [
                    edge
                    for edge in solid.Edges
                    if abs(edge.CenterOfMass.z - 10) < 1e-7
                    and (
                        abs(edge.CenterOfMass.x - 40) < 1e-7
                        if where == "end"
                        else abs(edge.CenterOfMass.y) < 1e-7 and abs(edge.CenterOfMass.x - 30) < 1e-7
                    )
                ]
                self.assertEqual(len(edges), 1)
                dressed = solid.makeChamfer(size, edges)
                self.assertTrue(dressed.isValid())
                self.assertAlmostEqual(dressed.Volume, 12000 - size * size / 2 * 20, places=6)
                top = faceAt(dressed, 30, 10, 10)
                shell = dressed.makeThickness([top], -2, 1e-7, False, False, 0, 0)
                self.assertTrue(shell.isValid())
                self.assertEqual(len(shell.Solids), 1)
                self.assertEqual(len(shell.Faces), 18)
                leg = size + 2 * math.sqrt(2) - 2
                volume = (12000 - size * size / 2 * 20) - (6656 - leg * leg / 2 * length)
                self.assertLess(abs(shell.Volume - volume), 1e-6 * volume)
        self.assertAlmostEqual(11990 - (6656 - (2 * math.sqrt(2) - 1) ** 2 / 2 * 16), 5360.745, places=3)

    def testShellUnderARampOrATiltedStepIsNeverThinnerOrClosed(self):
        """Two shells OCCT's offset of the whole solid gets wrong, both refused (ops#811, the
        review's finds). A 40 x 40 x 10 block with a ramp on a quarter of its top (x 0..20,
        y 0..20, from the top's level at y 20 up to 2 at y 0), shelled 2 inward from the
        L-shaped rest of the top: the ramp has no offset face, and the cavity ran flat under
        it, the roof as thin as the ramp is high (6032 = 16400 - 36 x 36 x 8). And a
        40 x 20 x 10 block with a step on x 0..20 whose top tilts down to the open face's
        level at the one corner (20, 20, 10): the offset came back as a closed pocket under
        the step's top, 17 mm^3, nowhere near the open face (8623.014 for 8640). Where a
        kernel builds either, it has a real cavity and a roof left under the ramp."""
        V = FreeCAD.Vector
        ramp = Part.Face(
            Part.makePolygon([V(0, 0, 10), V(0, 20, 10), V(0, 0, 12), V(0, 0, 10)])
        ).extrude(V(20, 0, 0))
        ramped = Part.makeBox(40, 40, 10).fuse(ramp).removeSplitter()
        self.assertAlmostEqual(ramped.Volume, 16400, places=6)
        under = Part.Face(
            Part.makePolygon(
                [V(-10, -10, 14.8), V(30, -10, 11.6), V(30, 30, 8.4), V(-10, 30, 11.6), V(-10, -10, 14.8)]
            )
        ).extrude(V(0, 0, -30))
        tilted = (
            Part.makeBox(40, 20, 10)
            .fuse(under.common(Part.makeBox(20, 20, 30, V(0, 0, 10))))
            .removeSplitter()
        )
        self.assertAlmostEqual(tilted.Volume, 8640, places=6)
        for name, solid, point, least, most in (
            ("ramp", ramped, V(30, 30, 10), 16400 - 36 * 36 * 8 + 100, 16400 - 1000),
            ("tilted step", tilted, V(30, 10, 10), 8640 - 36 * 16 * 8, 8640 - 1000),
        ):
            with self.subTest(name=name):
                self.assertTrue(solid.isValid())
                opened = [
                    face for face in solid.Faces if face.distToShape(Part.Vertex(point))[0] < 1e-7
                ]
                self.assertEqual(len(opened), 1)
                try:
                    shell = solid.makeThickness(opened, -2, 1e-7, False, False, 0, 2)
                except Exception as error:  # the kernel's refusal
                    self.assertIn("no shell was built", str(error))
                else:
                    self.assertTrue(shell.isValid())
                    self.assertGreater(shell.Volume, least)
                    self.assertLess(shell.Volume, most)

    def testShellFromASlopeRunningIntoATowersWall(self):
        """A tower 20 x 20 x 26 with a lower part beside it whose top slopes from the tower's
        wall (z 10 there) up or down by 0.3 or 1 per mm, shelled 2 inward from the slope. The
        cavity under the slope reaches its plane, continued under the tower's wall to that
        wall's offset (x 18), and ends 2 from the end wall (x 38): its section there is
        20 x 8 and the slope's rise over those 20, 160 (1 + slope); the tower's is 16 x 22
        (ops#811; the tower's wall is measured from the slope's plane, the review's find)."""
        for slope in (0.3, 1.0, -0.3):
            with self.subTest(slope=slope):
                profile = [(0, 0), (40, 0), (40, 10 + 20 * slope), (20, 10), (20, 26), (0, 26)]
                points = [FreeCAD.Vector(x, 0, z) for x, z in profile + profile[:1]]
                solid = Part.Face(Part.makePolygon(points)).extrude(FreeCAD.Vector(0, 20, 0))
                opened = [
                    face
                    for face in solid.Faces
                    if abs(face.CenterOfMass.x - 30) < 1e-6
                    and abs(face.CenterOfMass.z - (10 + 10 * slope)) < 1e-6
                ]
                self.assertEqual(len(opened), 1)
                shell = solid.makeThickness(opened, -2, 1e-7, False, False, 0, 2)
                self.assertTrue(shell.isValid())
                self.assertEqual(len(shell.Solids), 1)
                self.assertEqual(len(shell.Faces), 16)
                removed = (16 * 22 + 160 * (1 + slope)) * 16
                self.assertAlmostEqual(solid.Volume - shell.Volume, removed, places=4)

    def testShellUnderAHalfRoundStepWithATiltedTop(self):
        """A 40 x 60 x 10 block with a half-round step at its wall whose top rises from the
        open face's level at the wall, shelled 2 inward from the block's top. Radius 15,
        rising 0.5 per mm: OCCT's offset runs the cavity flat under the step, the roof as
        thin as the step is high there. Radius 3, rising 0.2 per mm: the step is all within
        the wall, the cavity is the plain block's 36 x 56 x 8, but OCCT's offset leaves the
        top's offset face untrimmed, a wedge of 376 mm^3 across the cavity. Both are refused
        (ops#811, the reviews' finds): the step's top is held up to 2 from the open face's
        edge, along the arc of its foot too, and no face of the cavity may run on far from
        the face it is the offset of. Where a kernel builds either, a roof is left under the
        large step and nothing under the small one."""
        V = FreeCAD.Vector
        for radius, rise, least, most in (
            (15, 0.5, 0, 36 * 56 * 8 - 100),
            (3, 0.2, 36 * 56 * 8 - 1e-3, 36 * 56 * 8 + 1e-3),
        ):
            with self.subTest(radius=radius):
                half = Part.makeCylinder(radius, 40, V(0, 0, 10)).common(
                    Part.makeBox(radius, 2 * radius, 40, V(0, -radius, 10))
                )
                low, high = 10 - 5 * rise, 10 + 20 * rise
                under = Part.Face(
                    Part.makePolygon(
                        [V(-5, -20, low), V(20, -20, high), V(20, 20, high), V(-5, 20, low), V(-5, -20, low)]
                    )
                ).extrude(V(0, 0, -40))
                solid = (
                    Part.makeBox(40, 60, 10, V(0, -30, 0)).fuse(half.common(under)).removeSplitter()
                )
                self.assertTrue(solid.isValid())
                opened = [
                    face
                    for face in solid.Faces
                    if abs(face.CenterOfMass.z - 10) < 1e-3 and face.Area > 1000
                ]
                self.assertEqual(len(opened), 1)
                for join in (0, 2):
                    try:
                        shell = solid.makeThickness(opened, -2, 1e-7, False, False, 0, join)
                    except Exception as error:  # the kernel's refusal
                        self.assertIn("no shell was built", str(error))
                    else:
                        self.assertTrue(shell.isValid())
                        self.assertGreater(solid.Volume - shell.Volume, least)
                        self.assertLess(solid.Volume - shell.Volume, most)

    def testShellBesideAStepWithARoundOnTheOpenFaceIsRefused(self):
        """The L-block with a round of 0.5 or 1 on the open face's side edge (y 0, z 10), which
        OCCT's thick-solid builder returned as a solid larger than the L. The round's offset
        face does not reach the open face's plane, and the cavity OCCT's offset gives there
        cuts the wall beside the round away: refused (ops#811). Debt: Onshape, not checked."""
        for size in (0.5, 1.0):
            with self.subTest(size=size):
                solid, faceAt = self._lBlock()
                edges = [
                    edge
                    for edge in solid.Edges
                    if abs(edge.CenterOfMass.y) < 1e-7
                    and abs(edge.CenterOfMass.z - 10) < 1e-7
                    and abs(edge.CenterOfMass.x - 30) < 1e-7
                ]
                self.assertEqual(len(edges), 1)
                dressed = solid.makeFillet(size, edges)
                self.assertTrue(dressed.isValid())
                top = faceAt(dressed, 30, 10, 10)
                with self.assertRaises(Exception) as refusal:
                    dressed.makeThickness([top], -2, 1e-7, False, False, 0, 0)
                self.assertIn("no shell was built", str(refusal.exception))

    def _partThicknessOfAPlate(self, hole, join):
        """Part's Thickness of a 120 x 80 x 10 plate less <hole> (a through solid), bottom face
        removed, outward 1.5 with <join>."""
        plate = Part.makeBox(120, 80, 10).cut(hole)
        source = self.Doc.addObject("Part::Feature", "Plate")
        source.Shape = plate
        bottom = [
            "Face" + str(i)
            for i, face in enumerate(plate.Faces, 1)
            if isinstance(face.Surface, Part.Plane)
            and abs(face.CenterOfMass.z) < 1e-7
            and abs(face.normalAt(0, 0).z + 1) < 1e-7
        ]
        self.assertEqual(len(bottom), 1)
        thickness = self.Doc.addObject("Part::Thickness", "Thickness")
        thickness.Faces = (source, bottom)
        thickness.Value = 1.5
        thickness.Join = join
        self.Doc.recompute()
        return thickness

    def testPartThicknessSaysWhenTheArcJoinFallsBack(self):
        """ops#807's plate with a 10 x 20 through pocket by Part's Thickness: the Arc join gives
        no valid outward shell, so the sharp one is built, V 22035 = 123*83*11.5 - 7*17*11.5 -
        9400*10, with a warning; asked for the Intersection join, the same shell, no warning."""
        pocket = Part.makeBox(10, 20, 10, FreeCAD.Vector(55, 30, 0))
        for join, warns in (("Arc", True), ("Intersection", False)):
            with self.subTest(join=join):
                thickness = self._partThicknessOfAPlate(pocket, join)
                status = thickness.getStatusString()
                self.assertTrue(thickness.isValid(), status)
                self.assertTrue(thickness.Shape.isValid())
                self.assertAlmostEqual(
                    thickness.Shape.Volume, 123 * 83 * 11.5 - 7 * 17 * 11.5 - 9400 * 10, places=5
                )
                self.assertEqual("Intersection join" in status, warns, status)
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestThickness")

    def testPartThicknessWithAnArcJoinOCCTBuildsHasNoWarning(self):
        """A round hole d6: OCCT's Arc join builds the outward shell, rounded, and nothing is said."""
        hole = Part.makeCylinder(3, 10, FreeCAD.Vector(60, 40, 0))
        thickness = self._partThicknessOfAPlate(hole, "Arc")
        status = thickness.getStatusString()
        self.assertTrue(thickness.isValid(), status)
        self.assertNotIn("Intersection join", status)
        self.assertFalse(all(isinstance(f.Surface, Part.Plane) for f in thickness.Shape.Faces))

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestThickness")
        # print ("omit closing document for debugging")
