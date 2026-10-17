# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#325, B+ Stage 1 session 2a; ops#311)

"""The origin of a FlatFace attachment on a face of a solid feature (MapOrigin, ops#311 option
(a)), and New part (PartDesign.newPartFrom). Designed geometry: notes/bplus-stage1-design.md 2.2
(O-t1-t6) and 2.3 (N-t1-t6). Oracles are placements, volumes and bounding boxes."""

import os
import re
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import faceAt, pad, rect, sketch, xyPlane

V = App.Vector


def assertVector(test, got, expected, msg=None):
    test.assertLess((got - V(*expected)).Length, 1e-6, msg or f"{got} != {expected}")


def globalBox(feature):
    """The bounding box of an additive feature's own solid (its AddSubShape, in the feature's
    frame) in the document's frame"""
    return feature.AddSubShape.transformed(feature.getGlobalPlacement().toMatrix()).BoundBox


class TestMapOrigin(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestMapOrigin")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def recomputeAll(self):
        """Every object recomputed, so an attachment is computed again whatever the document
        thinks changed"""
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()

    def pocketModel(self):
        """ops#311's case, one Body: a box 100 x 60 x 20 at the origin; a cylinder r5 h20 at
        (80, 40), whose Placement the next feature inherits; a 10 x 10 pocket 5 deep from the
        top. Returns the body, the cylinder, the pocket and the pocket's top face."""
        body = self.doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length, box.Width, box.Height = 100, 60, 20
        cylinder = body.newObject("PartDesign::AdditiveCylinder", "Cylinder")
        cylinder.Radius, cylinder.Height = 5, 20
        cylinder.Placement.Base = V(80, 40, 0)
        hole = sketch(body, "HoleSk", xyPlane(body), (10, 10, 20, 20), z=20)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = hole
        pocket.Length = 5
        self.doc.recompute()
        assertVector(self, pocket.Placement.Base, (80, 40, 0), "the model: an inherited Placement")
        return body, cylinder, pocket, faceAt(pocket, 20)

    def attached(self, body, typeId, name, support):
        obj = body.newObject(typeId, name)
        obj.AttachmentSupport = support
        obj.MapMode = "FlatFace"
        self.doc.recompute()
        return obj

    def testSketchOnAMidChainFaceTakesTheBodyOrigin(self):
        """O-t1: a new sketch on the pocket's top face has its origin at (0, 0, 20), the Body's
        origin projected (it was (80, 40, 20), the cylinder's). Moving the cylinder to (60, 30)
        leaves it there (it followed the cylinder)."""
        body, cylinder, pocket, top = self.pocketModel()
        sk = self.attached(body, "Sketcher::SketchObject", "OnTop", [(pocket, top)])
        self.assertEqual(sk.MapOrigin, "Body")
        assertVector(self, sk.Placement.Base, (0, 0, 20))
        cylinder.Placement.Base = V(60, 30, 0)
        self.recomputeAll()
        assertVector(self, sk.Placement.Base, (0, 0, 20))

    def testDatumPlaneAndPrimitiveOnAMidChainFaceTakeTheBodyOrigin(self):
        """O-t2: a datum plane and an additive box attached to the pocket's top face: origin
        (0, 0, 20), before and after the cylinder moves."""
        body, cylinder, pocket, top = self.pocketModel()
        plane = self.attached(body, "PartDesign::Plane", "OnTopPlane", [(pocket, top)])
        lid = self.attached(body, "PartDesign::AdditiveBox", "OnTopBox", [(pocket, top)])
        for obj in (plane, lid):
            assertVector(self, obj.Placement.Base, (0, 0, 20), obj.Name)
        cylinder.Placement.Base = V(60, 30, 0)
        self.recomputeAll()
        for obj in (plane, lid):
            assertVector(self, obj.Placement.Base, (0, 0, 20), obj.Name)
            self.assertTrue(obj.isValid(), obj.Name)

    def testObjectFromAFileWithoutMapOriginKeepsItsFrame(self):
        """O-t3: a sketch at the feature's origin (80, 40, 20), saved without the property (renamed
        in Document.xml, as a file from before it): restored as "Feature", it keeps that
        origin when it recomputes, and follows the cylinder (as before)."""
        body, cylinder, pocket, top = self.pocketModel()
        sk = self.attached(body, "Sketcher::SketchObject", "OnTop", [(pocket, top)])
        sk.MapOrigin = "Feature"
        self.doc.recompute()
        assertVector(self, sk.Placement.Base, (80, 40, 20))
        path = os.path.join(tempfile.mkdtemp(), "nomaporigin.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        stripped = path + ".tmp"
        with (
            zipfile.ZipFile(path) as old,
            zipfile.ZipFile(stripped, "w", zipfile.ZIP_DEFLATED) as new,
        ):
            for item in old.infolist():
                data = old.read(item.filename)
                if item.filename == "Document.xml":
                    # renamed, not removed: each object's property count stays right, and an
                    # unknown property is skipped on restore, as in a file from before it
                    text, count = re.subn(
                        r'<Property name="MapOrigin"',
                        '<Property name="NotMapOrigin"',
                        data.decode("utf-8"),
                    )
                    self.assertGreater(count, 0)
                    data = text.encode("utf-8")
                new.writestr(item, data)
        os.replace(stripped, path)
        self.doc = App.openDocument(path)
        sk = self.doc.getObject("OnTop")
        self.assertEqual(sk.MapOrigin, "Feature")
        self.recomputeAll()
        assertVector(self, sk.Placement.Base, (80, 40, 20))
        self.doc.getObject("Cylinder").Placement.Base = V(60, 30, 0)
        self.recomputeAll()
        assertVector(self, sk.Placement.Base, (60, 30, 20))

    def testLidOnTheRimStaysWhenTheWidthChanges(self):
        """O-t4 (Stage 0b's D-face): an enclosure 120 x 80 x 60 whose boss, a cylinder at
        (width - 8, 72), places the shell's pocket; a lid in its own Body, sketched on the rim
        face. The width 120 -> 150, the boss with it: the lid stays at x 0..120 (it moved by
        30)."""
        enclosure = self.doc.addObject("PartDesign::Body", "Enclosure")
        box = enclosure.newObject("PartDesign::AdditiveBox", "Box")
        box.Length, box.Width, box.Height = 120, 80, 60
        boss = enclosure.newObject("PartDesign::AdditiveCylinder", "Boss")
        boss.Radius, boss.Height = 4, 60
        boss.Placement.Base = V(112, 72, 0)
        shellSk = sketch(enclosure, "ShellSk", xyPlane(enclosure), (5, 5, 100, 60), z=60)
        shell = enclosure.newObject("PartDesign::Pocket", "Shell")
        shell.Profile = shellSk
        shell.Length = 55
        self.doc.recompute()
        assertVector(self, shell.Placement.Base, (112, 72, 0), "the model: an inherited Placement")
        lid = self.doc.addObject("PartDesign::Body", "Lid")
        lidSk = lid.newObject("Sketcher::SketchObject", "LidSk")
        lidSk.AttachmentSupport = [(shell, faceAt(shell, 60))]
        lidSk.MapMode = "FlatFace"
        rect(lidSk, 0, 0, 120, 80)
        plate = pad(lid, "Plate", lidSk, 3)
        self.doc.recompute()
        self.assertTrue(plate.isValid(), plate.getStatusString())
        self.assertAlmostEqual(lid.Shape.BoundBox.XMin, 0, places=6)
        self.assertAlmostEqual(plate.Shape.Volume, 120 * 80 * 3, places=3)
        box.Length = 150
        boss.Placement.Base = V(142, 72, 0)
        self.recomputeAll()
        self.assertTrue(plate.isValid(), plate.getStatusString())
        self.assertAlmostEqual(lid.Shape.BoundBox.XMin, 0, places=6)
        self.assertAlmostEqual(lid.Shape.BoundBox.XMax, 120, places=6)

    def testPlanesAndOutsideSupportsKeepTheirFrames(self):
        """O-t5: on the XY, XZ and YZ planes, a datum plane offset (10, 20, 30) and turned 30
        degrees about Z, and a Part::Box's top face outside every Body, "Body" gives the frame
        "Feature" (today's) gives."""
        body = self.doc.addObject("PartDesign::Body", "Body")
        datum = body.newObject("PartDesign::Plane", "Datum")
        datum.Placement = App.Placement(V(10, 20, 30), App.Rotation(V(0, 0, 1), 30))
        box = self.doc.addObject("Part::Box", "Outside")
        box.Placement = App.Placement(V(5, 7, 0), App.Rotation(V(0, 0, 1), 15))
        self.doc.recompute()
        top = faceAt(box, 10)
        supports = [(plane, "") for plane in body.Origin.OriginFeatures[3:6]]
        supports += [(datum, ""), (box, top)]
        for i, support in enumerate(supports):
            sk = self.attached(body, "Sketcher::SketchObject", f"Sk{i}", [support])
            self.assertEqual(sk.MapOrigin, "Body")
            frame = sk.Placement
            sk.MapOrigin = "Feature"
            self.doc.recompute()
            self.assertTrue(sk.Placement.isSame(frame, 1e-9), f"{support}: {frame} {sk.Placement}")

    def testSupportThroughTheBodyGetsTheSameOrigin(self):
        """O-t6: a support stored as (Body, "Pocket.FaceN") gets the origin (Pocket, "FaceN")
        gets, (0, 0, 20)."""
        body, cylinder, pocket, top = self.pocketModel()
        direct = self.attached(body, "Sketcher::SketchObject", "Direct", [(pocket, top)])
        path = self.attached(
            body, "Sketcher::SketchObject", "Path", [(body, f"{pocket.Name}.{top}")]
        )
        for sk in (direct, path):
            assertVector(self, sk.Placement.Base, (0, 0, 20), sk.Name)


class TestNewPart(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestNewPart")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def enclosure(self, container=None):
        """A1's geometry: the enclosure, 40 x 40 x 10 (16000), and a lid sketch on its top face,
        30 x 30, in the enclosure."""
        body = self.doc.addObject("PartDesign::Body", "Enclosure")
        if container:
            container.addObject(body)
        base = pad(body, "Base", sketch(body, "BaseSk", xyPlane(body), (0, 0, 40, 40)), 10)
        self.doc.recompute()
        lidSk = body.newObject("Sketcher::SketchObject", "LidSk")
        lidSk.AttachmentSupport = [(base, faceAt(base, 10))]
        lidSk.MapMode = "FlatFace"
        rect(lidSk, 0, 0, 30, 30)
        return body, base, lidSk

    def assertLid(self, part, lid, volume, zMin=10):
        self.assertTrue(part.Placement.isIdentity())
        self.assertIs(part.Tip, lid)
        self.assertTrue(lid.isValid(), lid.getStatusString())
        self.assertAlmostEqual(part.Shape.Volume, volume, places=3)
        self.assertAlmostEqual(part.Shape.BoundBox.ZMin, zMin, places=6)

    def testNewPartFromTheLidPad(self):
        """N-t1: the lid's pad made in the enclosure (20500 together), then New part: a new Body
        at identity holds the pad and its sketch; the lid is the plate alone (4500), and the
        enclosure is back to 16000."""
        body, base, lidSk = self.enclosure()
        lid = pad(body, "Lid", lidSk, 5)
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 20500, places=3)
        part = PartDesign.newPartFrom(lid)
        self.doc.recompute()
        self.assertEqual(part.TypeId, "PartDesign::Body")
        self.assertEqual(part.Group, [lidSk, lid])
        self.assertIs(lid.BaseFeature, None)
        self.assertLid(part, lid, 4500)
        self.assertIs(body.Tip, base)
        self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])

    def testNewPartStaysInTheStudio(self):
        """N-t2: in an App::Part, the new Body is in that Part; at the top level, at the top
        level."""
        part = self.doc.addObject("App::Part", "Studio")
        body, base, lidSk = self.enclosure(part)
        lid = pad(body, "Lid", lidSk, 5)
        self.doc.recompute()
        made = PartDesign.newPartFrom(lid)
        self.doc.recompute()
        self.assertIs(made.getParentGeoFeatureGroup(), part)
        self.assertLid(made, lid, 4500)
        top = self.doc.addObject("PartDesign::Body", "Top")
        cube = pad(top, "Cube", sketch(top, "CubeSk", xyPlane(top), (0, 0, 10, 10)), 10)
        self.doc.recompute()
        moved = PartDesign.newPartFrom(cube)
        self.doc.recompute()
        self.assertIsNone(moved.getParentGeoFeatureGroup())
        self.assertAlmostEqual(moved.Shape.Volume, 1000, places=3)

    def testUndoLeavesTheDocumentAsBefore(self):
        """N-t3: New part in an open transaction, undone: the same objects, the enclosure's Tip
        the lid again, and 20500."""
        self.doc.UndoMode = 1
        body, base, lidSk = self.enclosure()
        lid = pad(body, "Lid", lidSk, 5)
        self.doc.recompute()
        before = sorted(o.Name for o in self.doc.Objects)
        self.doc.openTransaction("New part")
        PartDesign.newPartFrom(lid)
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertNotEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertIs(body.Tip, lid)
        self.assertIn(lidSk, body.Group)
        self.assertAlmostEqual(body.Shape.Volume, 20500, places=3)

    def testNewPartFromAnAdditivePrimitive(self):
        """N-t4: an additive box 10 x 10 x 5 attached to the enclosure's top face, then New part:
        500 alone, on the top face; the enclosure 16000."""
        body, base, lidSk = self.enclosure()
        box = body.newObject("PartDesign::AdditiveBox", "Knob")
        box.Length, box.Width, box.Height = 10, 10, 5
        box.AttachmentSupport = [(base, faceAt(base, 10))]
        box.MapMode = "FlatFace"
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 16500, places=3)
        part = PartDesign.newPartFrom(box)
        self.doc.recompute()
        self.assertEqual(part.Group, [box])
        self.assertLid(part, box, 500)
        self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)

    def testASketchUsedTwiceStays(self):
        """N-t5: the lid sketch also cut a 2 deep recess into the enclosure (14200): it stays
        there, and the new part's pad links it directly (4500)."""
        body, base, lidSk = self.enclosure()
        recess = body.newObject("PartDesign::Pocket", "Recess")
        recess.Profile = lidSk
        recess.Length = 2
        lid = pad(body, "Lid", lidSk, 5)
        self.doc.recompute()
        part = PartDesign.newPartFrom(lid)
        self.doc.recompute()
        self.assertEqual(part.Group, [lid])
        self.assertIn(lidSk, body.Group)
        self.assertIs(lid.Profile[0], lidSk)
        self.assertLid(part, lid, 4500)
        self.assertIs(body.Tip, recess)
        self.assertAlmostEqual(body.Shape.Volume, 14200, places=3)

    def testNewPartFromAFaceProfile(self):
        """N-t6: a pad of the enclosure's top face (another part's face once moved): 40 x 40 x 5
        alone (8000), not the enclosure as its base (24000)."""
        body, base, lidSk = self.enclosure()
        lid = pad(body, "Lid", (base, [faceAt(base, 10)]), 5)
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 24000, places=3)
        other = self.doc.addObject("PartDesign::Body", "Other")
        self.assertTrue(PartDesign.isStudioProfile(other, base, faceAt(base, 10)))
        part = PartDesign.newPartFrom(lid)
        self.doc.recompute()
        self.assertLid(part, lid, 8000)
        self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)

    def placedLid(self, body, base, lidSk, on):
        """The lid of testNewPartFromAPlacedBodyStaysWhereItWas, 30 x 30 x 3 from z = 10, made
        `on`: the enclosure's top face, its XY plane 10 up, its XZ plane (the sketch's y is z,
        10 up; padded along y), the sketch unattached at z = 10, or an additive box on the XY
        plane 10 up (lidSk unused). Returns the lid and what the new Body should hold."""
        up = App.Placement(V(0, 0, 10), App.Rotation())
        if on == "box":
            lid = body.newObject("PartDesign::AdditiveBox", "Lid")
            lid.Length, lid.Width, lid.Height = 30, 30, 3
            lid.AttachmentSupport = xyPlane(body)
            lid.MapMode = "FlatFace"
            lid.AttachmentOffset = up
            return lid, [lid]
        if on == "origin":
            lidSk.AttachmentSupport = xyPlane(body)
            lidSk.AttachmentOffset = up
        elif on == "xz":
            lidSk.AttachmentSupport = [(body.Origin.OriginFeatures[4], "")]
            lidSk.AttachmentOffset = App.Placement(V(0, 10, 0), App.Rotation())
        elif on == "unattached":
            lidSk.MapMode = "Deactivated"
            lidSk.AttachmentSupport = []
            lidSk.Placement = up
        return pad(body, "Lid", lidSk, 3), [lidSk]

    def testNewPartFromAPlacedBodyStaysWhereItWas(self):
        """A placed enclosure (at (100, 0, 0), turned 20 deg about Z; at the top level and in an
        App::Part), and a lid 30 x 30 x 3 from z = 10: on its top face, its XY plane, its XZ
        plane, an unattached sketch, or an additive box (placedLid). New part puts the new Body
        where the enclosure is and keeps each lid's global bounding box (with the new Body at
        identity, the origin-plane lid went to (0, 0, 10)-(30, 30, 13))."""
        placement = App.Placement(V(100, 0, 0), App.Rotation(V(0, 0, 1), 20))
        for container in (None, self.doc.addObject("App::Part", "Studio")):
            for on in ("origin", "face", "xz", "unattached", "box"):
                with self.subTest(container=container and container.Name, on=on):
                    body, base, lidSk = self.enclosure(container)
                    body.Placement = placement
                    lid, held = self.placedLid(body, base, lidSk, on)
                    self.doc.recompute()
                    before = globalBox(lid)
                    self.assertAlmostEqual(before.ZMin, 10, places=6)
                    self.assertGreater(before.XMin, 80)  # the enclosure's placement counts
                    part = PartDesign.newPartFrom(lid)
                    self.doc.recompute()
                    self.assertEqual(part.Group, held + [lid] if on != "box" else held)
                    after = globalBox(lid)
                    for corner in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"):
                        self.assertAlmostEqual(
                            getattr(after, corner), getattr(before, corner), places=6, msg=corner
                        )
                    self.assertTrue(part.Placement.isSame(placement, 1e-9))
                    self.assertTrue(lid.isValid(), lid.getStatusString())
                    self.assertAlmostEqual(part.Shape.Volume, 2700, places=3)
                    self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)

    def testOnlyAnUnusedTipMoves(self):
        """A feature that something uses, or that isn't the Tip, is refused, and nothing
        changes."""
        body, base, lidSk = self.enclosure()
        lid = pad(body, "Lid", lidSk, 5)
        self.doc.recompute()
        names = sorted(o.Name for o in self.doc.Objects)
        with self.assertRaises(ValueError):
            PartDesign.newPartFrom(base)
        with self.assertRaises(ValueError):
            PartDesign.newPartFrom(lidSk)
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertIs(body.Tip, lid)
