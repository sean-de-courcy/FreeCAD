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

App = FreeCAD


class TestDraft(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestDraft")

    def testSimpleDraft(self):
        # fix: create datum plane on YZ. create datum line on Z + 10i
        # find top face by first making list comprehension of Z-normal faces
        # and then find which has the higher center of mass Z-value
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.DatumPlane = self.Doc.addObject("PartDesign::Plane", "DatumPlane")
        self.DatumPlane.AttachmentSupport = [(self.Doc.YZ_Plane, "")]
        self.DatumPlane.MapMode = "FlatFace"
        self.Body.addObject(self.DatumPlane)
        self.Doc.recompute()
        self.DatumLine = self.Doc.addObject("PartDesign::Line", "DatumLine")
        self.DatumLine.AttachmentSupport = [(self.Doc.X_Axis, "")]
        self.DatumLine.MapMode = "TwoPointLine"
        self.Body.addObject(self.DatumLine)
        self.Doc.recompute()
        self.Draft = self.Doc.addObject("PartDesign::Draft", "Draft")
        # Draft.Base needs to be top face
        self.Faces = self.Box.Shape.Faces
        # Grab the two faces with Z-normals and find the higher one
        self.ZFaceIndexes = [
            i for i in range(len(self.Faces)) if self.Faces[i].Surface.Axis == App.Vector(0, 0, 1)
        ]
        if (
            self.Faces[self.ZFaceIndexes[0]].CenterOfMass.z
            > self.Faces[self.ZFaceIndexes[1]].CenterOfMass.z
        ):
            self.TopFaceIndex = self.ZFaceIndexes[0]
        else:
            self.TopFaceIndex = self.ZFaceIndexes[1]
        self.Draft.Base = (self.Box, ["Face" + str(self.TopFaceIndex + 1)])
        self.Draft.NeutralPlane = (self.DatumPlane, [""])
        self.Draft.PullDirection = (self.DatumLine, [""])
        self.Draft.Angle = 45.0
        self.Draft.Reversed = 1
        self.Body.addObject(self.Draft)
        self.Doc.recompute()
        if "Invalid" in self.Draft.State:
            self.Draft.Reversed = 0
            self.Doc.recompute()
        self.assertAlmostEqual(self.Draft.Shape.Volume, 1500)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestDraft")
        # print ("omit closing document for debugging")



def _xyPlane(coordinateSystem):
    [plane] = [f for f in coordinateSystem.OriginFeatures if f.Role == "XY_Plane"]
    return plane


class TestNeutralPlanePlacement(unittest.TestCase):
    """Where a draft pivots when its neutral plane is a plane that isn't a face (FreeCAD-CH
    ops#150 W2, ops#198). A 10 mm cube in a body; its front face (y = 0) drafted 2 degrees, the
    neutral plane parallel to XY at height z in the body. The face turns about its line at z:
    the cube loses 5 tan 2 ((10 - z)^2 - z^2) mm^3, so 1000 - 500 tan 2 at z = 0, 1000 at
    z = 5 (the two wedges cancel), 1000 + 500 tan 2 at z = 10."""

    bodyPlacement = App.Placement()

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestNeutralPlane")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Body.Placement = self.bodyPlacement
        self.Box = self.Body.newObject("PartDesign::AdditiveBox", "Box")
        self.Box.Length = self.Box.Width = self.Box.Height = 10
        self.Doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def expected(self, z):
        return 1000 - 5 * math.tan(math.radians(2)) * ((10 - z) ** 2 - z * z)

    def assertPivot(self, plane, z):
        front = _faceAt(self.Box.Shape, App.Vector(5, 0, 5), App.Vector(0, -1, 0))
        draft = self.Body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (self.Box, [front])
        draft.NeutralPlane = (plane, [""])
        draft.Angle = 2
        self.Doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        self.assertAlmostEqual(draft.Shape.Volume, self.expected(z), places=3)

    def coordinateSystemPlane(self, z):
        lcs = self.Doc.addObject("Part::LocalCoordinateSystem", "LCS")
        self.Body.addObject(lcs)
        lcs.Placement = App.Placement(App.Vector(0, 0, z), App.Rotation())
        self.Doc.recompute()
        return _xyPlane(lcs)

    def testOriginPlane(self):
        self.assertPivot(_xyPlane(self.Body.Origin), 0)

    def testDatumPlane(self):
        plane = self.Body.newObject("PartDesign::Plane", "DatumPlane")
        plane.MapMode = "Deactivated"
        plane.Placement = App.Placement(App.Vector(0, 0, 10), App.Rotation())
        self.assertPivot(plane, 10)

    def testCoordinateSystemPlane(self):
        """The coordinate system at z = 5, its XY plane: the pivot at mid height. The draft took
        the plane at z = 0 (ops#198)."""
        self.assertPivot(self.coordinateSystemPlane(5), 5)


class TestNeutralPlanePlacementInAPlacedBody(TestNeutralPlanePlacement):
    """The same in a body moved and turned: the planes are in the body's coordinates, so the
    volumes don't change (the body's own placement isn't added to them)."""

    bodyPlacement = App.Placement(App.Vector(5, -4, 9), App.Rotation(App.Vector(1, 1, 0), 30))

def _sketch(doc, body, name, geometry, z=0):
    sketch = body.newObject("Sketcher::SketchObject", name)
    sketch.Placement = App.Placement(App.Vector(0, 0, z), App.Rotation())
    sketch.addGeometry(geometry, False)
    return sketch


def _rectangle(x0, y0, x1, y1):
    points = [App.Vector(x, y, 0) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    return [Part.LineSegment(p, q) for p, q in zip(points, points[1:] + points[:1])]


def _faceAt(shape, point, normal=None):
    """The index name of the one face containing the point (with that normal, if given)."""
    names = []
    for i, f in enumerate(shape.Faces, 1):
        u, v = f.Surface.parameter(point)
        if not f.isInside(point, 1e-7, True):
            continue
        if normal is not None and f.normalAt(u, v).getAngle(normal) > 1e-9:
            continue
        names.append(f"Face{i}")
    if len(names) != 1:
        raise RuntimeError(f"faces at {point}: {names}")
    return names[0]


class TestDressUpFaces(unittest.TestCase):
    """Which faces a draft or a defeaturing takes from its Base (DressUp::getFaces), on designed
    models (FreeCAD-CH ops#60, ops#65)."""

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestDressUpFaces")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        profile = _sketch(self.Doc, self.Body, "Profile", _rectangle(0, 0, 20, 10))
        pad = self.Body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Length = 10

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def missingFace(self):
        """A block 0..20 x 0..10 x 0..10 with a slot (x 14..16, y 4..6) through it; a draft of
        the right face (x = 20), then the left face (x = 0). The slot becomes a step along the
        whole right side: the right face is gone. Returns (draft, right, left)."""
        slotSketch = _sketch(self.Doc, self.Body, "SlotSketch", _rectangle(14, 4, 16, 6), z=10)
        slot = self.Body.newObject("PartDesign::Pocket", "Slot")
        slot.Profile = slotSketch
        slot.Type = "ThroughAll"
        self.Doc.recompute()
        right = _faceAt(slot.Shape, App.Vector(20, 2, 5), App.Vector(1, 0, 0))
        left = _faceAt(slot.Shape, App.Vector(0, 5, 5), App.Vector(-1, 0, 0))
        bottom = _faceAt(slot.Shape, App.Vector(5, 5, 0), App.Vector(0, 0, -1))
        draft = self.Body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (slot, [right, left])
        draft.NeutralPlane = (slot, [bottom])
        draft.Angle = 5
        self.Doc.recompute()
        self.assertTrue(draft.isValid())

        geometry = slotSketch.Geometry
        for line, (start, end) in zip(
            geometry, (((18, -1), (21, -1)), ((21, -1), (21, 11)), ((21, 11), (18, 11)),
                       ((18, 11), (18, -1)))
        ):
            line.EndPoint = App.Vector(*end, 0)
            line.StartPoint = App.Vector(*start, 0)
        slotSketch.Geometry = geometry
        self.Doc.recompute()

        self.assertTrue(slot.isValid())
        self.assertEqual(draft.Base[1][0], "?" + right)
        return draft, right, left

    def testMissingFaceIsNamed(self):
        """Without the reference solver the draft fails, and its error names the right face,
        not the left one (the left face used to be looked up under the right face's name)."""
        self.Doc.ReferenceSolver = False  # new documents start with it on (ops#7 Q7)
        draft, right, left = self.missingFace()
        self.assertFalse(draft.isValid())
        message = draft.getStatusString()
        self.assertIn("Missing face", message)
        self.assertRegex(message, rf"\b{right}\b")
        self.assertNotRegex(message, rf"\b{left}\b")

    def testMissingFaceIsWarnedWithTheSolver(self):
        """In a reference solver document the draft computes on the left face, with a warning
        that names the right face, not the left one (ops#127, Onshape's rule)."""
        self.Doc.HistoryAlgorithm = "V2"
        self.Doc.ReferenceSolver = True
        draft, right, left = self.missingFace()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        self.assertIn("Warning", draft.State)
        message = draft.getStatusString()
        self.assertIn("Missing face", message)
        self.assertRegex(message, rf"\b{right}\b")
        self.assertNotRegex(message, rf"\b{left}\b")
        self.assertTrue(message.endswith("computed on 1 of 2 faces"), message)

    def testFaceAfterEdge(self):
        """A block 0..20 x 0..10 x 0..10 with a hole (radius 2 at (10, 5)) through it; a
        defeaturing whose Base lists an edge of the block, then the hole's wall. The hole is
        filled: the edge is skipped, and the wall is still the wall (it used to be looked up
        under the edge's name and skipped too)."""
        holeSketch = _sketch(
            self.Doc, self.Body, "HoleSketch",
            [Part.Circle(App.Vector(10, 5, 0), App.Vector(0, 0, 1), 2)], z=10
        )
        hole = self.Body.newObject("PartDesign::Pocket", "Hole")
        hole.Profile = holeSketch
        hole.Type = "ThroughAll"
        self.Doc.recompute()
        self.assertAlmostEqual(hole.Shape.Volume, 2000 - 40 * math.pi, places=6)
        edges = [
            f"Edge{i}"
            for i, e in enumerate(hole.Shape.Edges, 1)
            if (e.CenterOfMass - App.Vector(10, 0, 10)).Length < 1e-7
        ]
        wall = [f"Face{i}" for i, f in enumerate(hole.Shape.Faces, 1)
                if f.Surface.TypeId == "Part::GeomCylinder"]
        self.assertEqual((len(edges), len(wall)), (1, 1))
        defeaturing = self.Body.newObject("PartDesign::Defeaturing", "Defeaturing")
        defeaturing.Base = (hole, edges + wall)
        self.Doc.recompute()

        self.assertTrue(defeaturing.isValid())
        self.assertAlmostEqual(defeaturing.Shape.Volume, 2000, places=6)
