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

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestThickness")
        # print ("omit closing document for debugging")
