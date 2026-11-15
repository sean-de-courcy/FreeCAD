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
        OCCT 8.0.1 on Windows all three fail: the Intersection join with the hole 5 from two
        sides, and a hole's wall tangent to the side's wall (6 from the side) with either join
        (the intersecting mode returns the plate as it was there, which is never taken for the
        shell, ops#795). Where a kernel builds one, it is the shell."""
        for holes, join in (
            ([(5, 5)], "Intersection"),
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
