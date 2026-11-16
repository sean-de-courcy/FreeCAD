# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 ranks 21 and 22)

"""Onshape's end types Up to vertex (Extrude, Revolve) and Up to part (Revolve), appended to the
saved Type lists so that an existing index keeps its meaning.

- Extrude up to a vertex: the end lies on the plane through the vertex, parallel to the profile
  plane (Onshape's; the natural reading). The vertex is held in UpToFace.
- Revolve up to a vertex: the side turns until the profile reaches the half-plane through the
  axis and the vertex, in the side's sense (Flip turns the other way round).
- Revolve up to a part: the side stops at the first face of the part it reaches (UpToFace holds
  the part, whole).

Designed geometry, each model built by the test (no saved file):
- Plate: the 10 x 10 square x 0..10, y 0..10 sketched at z 0. Marker sketches hold a line whose
  first point is the vertex: z 25 above the plate (2500 padded up to it), z -15 under it (1500).
- Ring: the rectangle x 2..5, z 0..10 sketched in the XZ plane, revolved about the Z axis (the
  origin's): an angle theta gives V = (theta / 2)(R^2 - r^2) h = theta * 105. A vertex at
  (0, 7, 3) lies at 90 degrees counterclockwise about +Z (52.5 pi), 270 the other way (157.5 pi).
- Wall: the box x -20..0, y 0..20, z -5..15, outside the body: its face x = 0 is the first the
  ring's profile reaches counterclockwise (at 90 degrees), its face y = 0 clockwise (at 180).
"""

import math
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
import zipfile

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models

V = App.Vector
# The XZ plane, local y along +Z: a sketch's (x, y) is (x, 0, y)
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
RING_PER_RADIAN = 0.5 * (5**2 - 2**2) * 10  # (R^2 - r^2) h / 2 = 105

# The saved Type lists before round 4 (ops#640): each index keeps its name
OLD_TYPES = {
    "PartDesign::Pad": [
        "Length", "UpToLast", "UpToFirst", "UpToFace", "?TwoLengths", "UpToShape", "ThroughAll"
    ],
    "PartDesign::Pocket": [
        "Length", "ThroughAll", "UpToFirst", "UpToFace", "?TwoLengths", "UpToShape", "UpToLast"
    ],
    "PartDesign::Revolution": ["Angle", "UpToLast", "UpToFirst", "UpToFace", "?TwoAngles"],
    "PartDesign::Groove": ["Angle", "ThroughAll", "UpToFirst", "UpToFace", "?TwoAngles"],
}


def vertexAt(obj, point):
    """The name of `obj`'s vertex at `point`."""
    names = [
        "Vertex%d" % (i + 1)
        for i, vertex in enumerate(obj.Shape.Vertexes)
        if vertex.Point.distanceToPoint(point) < 1e-7
    ]
    assert len(names) == 1, (obj.Name, point, names)
    return names[0]


class TestOnshapeEndTypes(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestOnshapeEndTypes")
        self.tmp = None

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)

    # -- models ---------------------------------------------------------------------------------

    def marker(self, body, point, name="Marker"):
        """A sketch in `body` (parallel to XY, at the point's z) of a line whose first point is
        `point`; returns the sketch and that vertex's name."""
        x, y, z = point
        sketch = models.sketch(
            self.doc, name, [Part.LineSegment(V(x, y, 0), V(x + 1, y + 2, 0))], body, z=z
        )
        self.doc.recompute()
        return sketch, vertexAt(sketch, V(x, y, z))

    def plate(self, vertexZ, **values):
        """The plate padded up to the vertex at (20, 0, vertexZ)."""
        self.body = models.body(self.doc)
        marker, vertex = self.marker(self.body, (20, 0, vertexZ))
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        pad = models.pad(self.body, profile, 10)
        pad.Type = "UpToVertex"
        pad.UpToFace = (marker, [vertex])
        for name, value in values.items():
            setattr(pad, name, value)
        self.doc.recompute()
        return pad

    def ring(self, kind="Revolution", vertex=(0, 7, 3), **values):
        """The ring's profile revolved up to the vertex at `vertex`."""
        self.body = models.body(self.doc)
        marker, name = self.marker(self.body, vertex)
        profile = models.sketch(
            self.doc, "RingProfile", models.rectangle(2, 0, 5, 10), self.body, placement=XZ
        )
        feature = self.body.newObject("PartDesign::" + kind, kind)
        feature.Profile = profile
        feature.ReferenceAxis = (models.originFeature(self.body, "Z_Axis"), [""])
        feature.Type = "UpToVertex"
        feature.UpToFace = (marker, [name])
        for key, value in values.items():
            setattr(feature, key, value)
        self.doc.recompute()
        return feature

    def assertValid(self, feature):
        self.assertTrue(feature.isValid(), feature.getStatusString())

    # -- Extrude up to vertex ---------------------------------------------------------------------

    def testPadUpToAVertexAbove(self):
        """The vertex at z 25: the pad ends at z 25, 10 x 10 x 25 = 2500."""
        pad = self.plate(25)
        self.assertValid(pad)
        self.assertEqual(pad.Type, "UpToVertex")
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, 0, places=6)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 25, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 2500, places=6)

    def testPadUpToAVertexBelowGoesDown(self):
        """The vertex at z -15: one side goes towards it, z -15..0, 1500 (Reversed or not)."""
        for reversed in (False, True):
            pad = self.plate(-15, Reversed=reversed)
            self.assertValid(pad)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, -15, places=6)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 0, places=6)
            self.assertAlmostEqual(pad.Shape.Volume, 1500, places=6)
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("TestOnshapeEndTypes")

    def testPadUpToAVertexAlongACustomDirection(self):
        """Along (1, 0, 1) the end is still the plane z 25, parallel to the profile: an oblique
        prism of the same base and height, 2500, shifted 25 in x at the top."""
        pad = self.plate(25, UseCustomVector=True, Direction=V(1, 0, 1), AlongSketchNormal=False)
        self.assertValid(pad)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 25, places=6)
        self.assertAlmostEqual(pad.Shape.BoundBox.XMax, 35, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 2500, places=5)

    def testPadUpToAVertexWithAnOffset(self):
        """Onshape's sign (oracle 7c, UV1), as for a face: an offset of 5 ends 5 short of the
        vertex's plane, z 0..20, 2000; an offset of -5 goes past it, z 0..30, 3000."""
        pad = self.plate(25, Offset=5)
        self.assertValid(pad)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 20, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 2000, places=6)
        pad.Offset = -5
        self.doc.recompute()
        self.assertValid(pad)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 30, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 3000, places=6)

    def testPadUpToAVertexSymmetric(self):
        """Symmetric: each half reaches the vertex's plane, z -25..25, 5000."""
        pad = self.plate(25, SideType="Symmetric")
        self.assertValid(pad)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, -25, places=6)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 25, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 5000, places=6)

    def testPadTwoSidesUpToVertices(self):
        """Two sides: side 1 to z 25, side 2 blind 5 (z -5): 3000. Side 2 up to the same
        vertex, behind it, fails with the vertex's words."""
        pad = self.plate(25, SideType="Two sides", Type2="Length", Length2=5)
        self.assertValid(pad)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, -5, places=6)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 25, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 3000, places=6)
        pad.Type2 = "UpToVertex"
        pad.UpToFace2 = pad.UpToFace
        self.doc.recompute()
        self.assertFalse(pad.isValid())
        self.assertIn("vertex lies behind side 2", pad.getStatusString())

    def testPadUpToADatumPoint(self):
        """A datum point at z 25 (whole, as the field links it): 2500."""
        self.body = models.body(self.doc)
        point = self.body.newObject("PartDesign::Point", "DatumPoint")
        point.MapMode = "Deactivated"
        point.Placement = App.Placement(V(-5, 3, 25), App.Rotation())
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        pad = models.pad(self.body, profile, 10)
        pad.Type = "UpToVertex"
        pad.UpToFace = (point, [""])
        self.doc.recompute()
        self.assertValid(pad)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 25, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 2500, places=6)

    def testPadUpToAVertexOnTheProfilePlaneFails(self):
        """A vertex in the profile's plane leaves nothing to extrude: the pad fails."""
        pad = self.plate(0)
        self.assertFalse(pad.isValid())
        self.assertIn("profile plane", pad.getStatusString())

    def testPocketUpToAVertex(self):
        """A Pocket (the older class) of the 10 x 10 square sketched on top of a 20 x 20 x 30
        block, up to the vertex at z 10: 20 deep, 12000 - 2000 = 10000."""
        self.body = models.body(self.doc)
        block = models.sketch(self.doc, "Block", models.rectangle(-5, -5, 15, 15), self.body)
        models.pad(self.body, block, 30, "BlockPad")
        marker, vertex = self.marker(self.body, (40, 0, 10))
        top = models.sketch(self.doc, "Top", models.rectangle(0, 0, 10, 10), self.body, z=30)
        pocket = models.pocket(self.body, top, 5)
        pocket.Type = "UpToVertex"
        pocket.UpToFace = (marker, [vertex])
        self.doc.recompute()
        self.assertValid(pocket)
        self.assertAlmostEqual(pocket.Shape.Volume, 10000, places=5)
        self.assertTrue(pocket.Shape.isInside(V(5, 5, 5), 1e-6, True))
        self.assertFalse(pocket.Shape.isInside(V(5, 5, 15), 1e-6, True))

    # -- Revolve up to vertex ---------------------------------------------------------------------

    def testRevolveUpToAVertexAt90Degrees(self):
        """The vertex at (0, 7, 3): 90 degrees counterclockwise about +Z, 52.5 pi; flipped, the
        other way round to it, 270 degrees, 157.5 pi."""
        revolution = self.ring()
        self.assertValid(revolution)
        self.assertAlmostEqual(revolution.Shape.Volume, math.pi / 2 * RING_PER_RADIAN, places=4)
        self.assertTrue(revolution.Shape.isInside(V(2.5, 2.5, 5), 1e-6, True))
        self.assertFalse(revolution.Shape.isInside(V(-2.5, 2.5, 5), 1e-6, True))
        revolution.Reversed = True
        self.doc.recompute()
        self.assertValid(revolution)
        self.assertAlmostEqual(revolution.Shape.Volume, 1.5 * math.pi * RING_PER_RADIAN, places=4)

    def testRevolveUpToAVertexSymmetric(self):
        """Symmetric: each half turns the nearer way to the vertex's angle, 180 in all, 105 pi."""
        revolution = self.ring(SideType="Symmetric")
        self.assertValid(revolution)
        self.assertAlmostEqual(revolution.Shape.Volume, math.pi * RING_PER_RADIAN, places=4)

    def testRevolveTwoSidesUpToAVertexAndAnAngle(self):
        """Side 1 to the vertex (90), side 2 by 30 degrees: 120 in all, 70 pi."""
        revolution = self.ring(SideType="Two sides", Type2="Angle", Angle2=30)
        self.assertValid(revolution)
        self.assertAlmostEqual(
            revolution.Shape.Volume, 2 * math.pi / 3 * RING_PER_RADIAN, places=4
        )

    def testGrooveUpToAVertex(self):
        """A Groove of the ring's profile in a cylinder r 10, z -2..12 (1400 pi), up to the vertex
        at 90 degrees: 1400 pi - 52.5 pi."""
        self.body = models.body(self.doc)
        disc = models.sketch(self.doc, "Disc", [models.circle(0, 0, 10)], self.body, z=-2)
        models.pad(self.body, disc, 14, "Cylinder")
        marker, name = self.marker(self.body, (0, 7, 3))
        profile = models.sketch(
            self.doc, "RingProfile", models.rectangle(2, 0, 5, 10), self.body, placement=XZ
        )
        groove = self.body.newObject("PartDesign::Groove", "Groove")
        groove.Profile = profile
        groove.ReferenceAxis = (models.originFeature(self.body, "Z_Axis"), [""])
        groove.Type = "UpToVertex"
        groove.UpToFace = (marker, [name])
        self.doc.recompute()
        self.assertValid(groove)
        self.assertAlmostEqual(
            groove.Shape.Volume, 1400 * math.pi - math.pi / 2 * RING_PER_RADIAN, places=3
        )

    def testRevolveUpToAVertexOnTheAxisFails(self):
        """A vertex on the axis gives no angle: the revolution fails."""
        revolution = self.ring(vertex=(0, 0, 3))
        self.assertFalse(revolution.isValid())
        self.assertIn("axis", revolution.getStatusString())

    # -- Revolve up to part ---------------------------------------------------------------------

    def wall(self):
        wall = self.doc.addObject("Part::Feature", "Wall")
        wall.Shape = Part.makeBox(20, 20, 20, V(-20, 0, -5))
        return wall

    def testRevolveUpToAPart(self):
        """Up to the wall: counterclockwise its face x = 0 comes first, at 90 degrees (52.5 pi);
        flipped, its face y = 0, at 180 (105 pi)."""
        wall = self.wall()
        revolution = self.ring()
        revolution.Type = "UpToShape"
        revolution.UpToFace = (wall, [""])
        self.doc.recompute()
        self.assertValid(revolution)
        self.assertAlmostEqual(revolution.Shape.Volume, math.pi / 2 * RING_PER_RADIAN, places=3)
        revolution.Reversed = True
        self.doc.recompute()
        self.assertValid(revolution)
        self.assertAlmostEqual(revolution.Shape.Volume, math.pi * RING_PER_RADIAN, places=3)

    def testRevolveUpToNoPartFails(self):
        """Up to part with no part: the revolution fails and says so."""
        revolution = self.ring()
        revolution.Type = "UpToShape"
        revolution.UpToFace = None
        self.doc.recompute()
        self.assertFalse(revolution.isValid())
        self.assertIn("part", revolution.getStatusString())

    # -- the saved indices ----------------------------------------------------------------------

    def testExistingTypeIndicesKeepTheirMeaning(self):
        """The Type lists keep every earlier name at its index, the new ones appended; a file
        saves each earlier Type at its earlier index and reads it back by name."""
        body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), body)
        written = {}
        for kind, names in OLD_TYPES.items():
            probe = body.newObject(kind, "Probe")
            enums = probe.getEnumerationsOfProperty("Type")
            self.assertEqual(enums[: len(names)], names, kind)
            self.assertIn("UpToVertex", enums[len(names):], kind)
            if "Revolution" in kind or "Groove" in kind:
                self.assertIn("UpToShape", enums[len(names):], kind)
            for index, name in enumerate(names):
                if name.startswith("?"):
                    continue  # migrated on restore
                feature = body.newObject(kind, "Typed")
                feature.Profile = profile
                feature.Type = name
                written[feature.Name] = (kind, index, name)
        self.tmp = tempfile.mkdtemp()
        path = os.path.join(self.tmp, "types.FCStd")
        self.doc.saveAs(path)
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("Document.xml"))
        saved = {}
        for obj in root.iter("Object"):
            for prop in obj.iter("Property"):
                if prop.get("name") == "Type":
                    saved[obj.get("name")] = int(prop.find("Integer").get("value"))
        for name, (kind, index, _) in written.items():
            self.assertEqual(saved.get(name), index, (name, kind))
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        for name, (kind, _, typeName) in written.items():
            self.assertEqual(self.doc.getObject(name).Type, typeName, (name, kind))
