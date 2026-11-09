# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#325, B+ Stage 1 session 2a; ops#311)

"""The origin of a FlatFace attachment on a face of a solid feature (MapOrigin, ops#311 option
(a)), New part (PartDesign.newPartFrom), and the four operations of a Pad or Pocket with Add to
part (PartDesign.addToPart, ops#640). Designed geometry: notes/bplus-stage1-design.md 2.2
(O-t1-t6) and 2.3 (N-t1-t6). Oracles are placements, volumes and bounding boxes."""

import math
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


# Onshape's info on a Remove or an Intersect that reaches nothing (hands-on check R7, ops#640 H3)
NO_INTERSECTION = "Selected tools and targets do not intersect"


def volume(shape):
    """A shape's volume, 0 for the empty shape."""
    return 0 if shape.isNull() else shape.Volume


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

    def bossWithFillet(self):
        """ops#640 round 5 (hands-on B5-3): the enclosure, a boss 20 x 20 x 5 on its top from
        (10, 10) and a fillet r = 1 on the boss's four top edges; returns (body, base, boss
        sketch, boss, fillet). The fillet removes 20 (1 - pi/4) per edge less 5/3 - pi/2 at each
        corner, where two edges' grooves meet in a mitre."""
        body, base, lidSk = self.enclosure()
        bossSk = body.newObject("Sketcher::SketchObject", "BossSk")
        bossSk.AttachmentSupport = [(base, faceAt(base, 10))]
        bossSk.MapMode = "FlatFace"
        rect(bossSk, 10, 10, 30, 30)
        boss = pad(body, "Boss", bossSk, 5)
        self.doc.recompute()
        edges = [
            f"Edge{i}"
            for i, edge in enumerate(boss.Shape.Edges, 1)
            if all(abs(v.Point.z - 15) < 1e-6 for v in edge.Vertexes)
        ]
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (boss, edges)
        fillet.Radius = 1
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        return body, base, bossSk, boss, fillet

    FILLET = 4 * 20 * (1 - math.pi / 4) - 4 * (5 / 3 - math.pi / 2)

    def testNewPartTakesTheFilletAlong(self):
        """B5-3: New part of the boss, the fillet on its edges: the boss, its sketch and the
        fillet go to the new part in order; the enclosure is 16000 again, its Tip the base; the
        new part is the filleted boss (2000 - FILLET)."""
        body, base, bossSk, boss, fillet = self.bossWithFillet()
        self.assertEqual(PartDesign.newPartRefusal(boss), "")
        part = PartDesign.newPartFrom(boss)
        self.doc.recompute()
        self.assertEqual(part.Group, [bossSk, boss, fillet])
        self.assertIs(part.Tip, fillet)
        self.assertIs(body.Tip, base)
        self.assertIs(fillet.BaseFeature, boss)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(part.Shape.Volume, 2000 - self.FILLET, places=3)

    def testNewPartTakesALaterFilletAlong(self):
        """Review R5-2 (a): a pocket 5 x 5 x 5 in the enclosure's corner between the boss and a
        fillet on the boss's top edges (the fillet's Base the pocket): the fillet's edges are the
        boss's own, so it goes to the new part after the boss; the pocket stays, on the base."""
        body, base, lidSk = self.enclosure()
        bossSk = body.newObject("Sketcher::SketchObject", "BossSk")
        bossSk.AttachmentSupport = [(base, faceAt(base, 10))]
        bossSk.MapMode = "FlatFace"
        rect(bossSk, 10, 10, 30, 30)
        boss = pad(body, "Boss", bossSk, 5)
        cornerSk = body.newObject("Sketcher::SketchObject", "CornerSk")
        cornerSk.AttachmentSupport = [(base, faceAt(base, 10))]
        cornerSk.MapMode = "FlatFace"
        rect(cornerSk, 0, 0, 5, 5)
        corner = body.newObject("PartDesign::Pocket", "Corner")
        corner.Profile = cornerSk
        corner.Length = 5
        self.doc.recompute()
        edges = [
            f"Edge{i}"
            for i, edge in enumerate(corner.Shape.Edges, 1)
            if all(abs(v.Point.z - 15) < 1e-6 for v in edge.Vertexes)
        ]
        self.assertEqual(len(edges), 4)
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (corner, edges)
        fillet.Radius = 1
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(PartDesign.newPartRefusal(boss), "")
        part = PartDesign.newPartFrom(boss)
        self.doc.recompute()
        self.assertEqual(part.Group, [bossSk, boss, fillet])
        self.assertIs(body.Tip, corner)
        self.assertIs(corner.BaseFeature, base)
        self.assertIs(fillet.BaseFeature, boss)
        self.assertIs(fillet.Base[0], boss)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.assertAlmostEqual(body.Shape.Volume, 16000 - 125, places=3)
        self.assertAlmostEqual(part.Shape.Volume, 2000 - self.FILLET, places=3)
        # the rounds on the boss's top edges: every curved face between z = 14 and 15
        for face in part.Shape.Faces:
            if face.Surface.TypeId != "Part::GeomPlane":
                self.assertGreater(face.BoundBox.ZMin, 14 - 1e-6)
                self.assertLess(face.BoundBox.ZMax, 15 + 1e-6)

    def testAFilletedNewPartGoesBack(self):
        """J8's change of mind: the boss with its fillet made a new part (2000 - FILLET), then
        added back (round 9): the enclosure holds the sketch, the boss and the fillet where they
        were, the fillet its Tip on the boss, still on the boss's top edges (16000 + 2000 -
        FILLET); the new part is gone."""
        body, base, bossSk, boss, fillet = self.bossWithFillet()
        group = body.Group
        part = PartDesign.newPartFrom(boss)
        self.doc.recompute()
        partName = part.Name
        self.assertEqual(PartDesign.addToPartRefusal(boss, body), "")
        PartDesign.addToPart(boss, body)
        self.doc.recompute()
        self.assertEqual(body.Group, group)
        self.assertIsNone(self.doc.getObject(partName))
        self.assertIs(body.Tip, fillet)
        self.assertIs(boss.BaseFeature, base)
        self.assertIs(fillet.BaseFeature, boss)
        self.assertIs(fillet.Base[0], boss)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.assertAlmostEqual(body.Shape.Volume, 16000 + 2000 - self.FILLET, places=3)

    def testNewPartLeavesAChamferOnTheRest(self):
        """Review R5-2 (b): a chamfer of 1 mm on the enclosure's bottom edges right after the boss
        (its Base the boss): none of its edges touches the boss, so it stays with the enclosure,
        on the base (Onshape keeps it on Part 1); the new part is the bare boss."""
        body, base, lidSk = self.enclosure()
        bossSk = body.newObject("Sketcher::SketchObject", "BossSk")
        bossSk.AttachmentSupport = [(base, faceAt(base, 10))]
        bossSk.MapMode = "FlatFace"
        rect(bossSk, 10, 10, 30, 30)
        boss = pad(body, "Boss", bossSk, 5)
        self.doc.recompute()
        edges = [
            f"Edge{i}"
            for i, edge in enumerate(boss.Shape.Edges, 1)
            if all(abs(v.Point.z) < 1e-6 for v in edge.Vertexes)
        ]
        self.assertEqual(len(edges), 4)
        chamfer = body.newObject("PartDesign::Chamfer", "Bottom")
        chamfer.Base = (boss, edges)
        chamfer.Size = 1
        self.doc.recompute()
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        before = body.Shape.Volume
        self.assertEqual(PartDesign.newPartRefusal(boss), "")
        part = PartDesign.newPartFrom(boss)
        self.doc.recompute()
        self.assertEqual(part.Group, [bossSk, boss])
        self.assertIs(body.Tip, chamfer)
        self.assertIs(chamfer.BaseFeature, base)
        self.assertIs(chamfer.Base[0], base)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.assertAlmostEqual(part.Shape.Volume, 2000, places=3)
        self.assertAlmostEqual(body.Shape.Volume, before - 2000, places=3)
        # the bevels on the bottom edges: every slanted face between z = 0 and 1
        slanted = [
            face for face in body.Shape.Faces
            if abs(abs(face.normalAt(0, 0).z) - 1) > 1e-6 and abs(face.normalAt(0, 0).z) > 1e-6
        ]
        self.assertEqual(len(slanted), 4)
        for face in slanted:
            self.assertLess(face.BoundBox.ZMax, 1 + 1e-6)

    def testNewPartRefusesADraftWithItsNeutralPlaneOnTheBoss(self):
        """Fix review F1: a draft of 2 degrees on the enclosure's four sides right after the boss,
        its neutral plane the bottom face picked on the boss: the move would reroute its Base but
        leave the neutral plane on the boss in the other part, so New part is refused, naming the
        draft, and nothing changes (loud, where Onshape keeps the draft; debt)."""
        body, base, lidSk = self.enclosure()
        bossSk = body.newObject("Sketcher::SketchObject", "BossSk")
        bossSk.AttachmentSupport = [(base, faceAt(base, 10))]
        bossSk.MapMode = "FlatFace"
        rect(bossSk, 10, 10, 30, 30)
        boss = pad(body, "Boss", bossSk, 5)
        self.doc.recompute()
        sides = []
        bottom = None
        for i, face in enumerate(boss.Shape.Faces, 1):
            bb = face.BoundBox
            if abs(bb.ZMin) < 1e-6 and abs(bb.ZMax - 10) < 1e-6:
                sides.append(f"Face{i}")
            elif abs(bb.ZMax) < 1e-6:
                bottom = f"Face{i}"
        self.assertEqual(len(sides), 4)
        self.assertIsNotNone(bottom)
        draft = body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (boss, sides)
        draft.NeutralPlane = (boss, [bottom])
        draft.Angle = 2
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        self.assertEqual(PartDesign.newPartRefusal(boss), "'Draft' uses 'Boss', which would go to the new part")
        names = sorted(o.Name for o in self.doc.Objects)
        with self.assertRaises(ValueError):
            PartDesign.newPartFrom(boss)
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertIs(body.Tip, draft)

    def testNewPartRefusesWhatCantBeToldApart(self):
        """A pad on the fillet's top (its sketch on that face) would stay with the enclosure and
        change: refused, naming the sketch, and nothing changes. A first solid with features after
        it is refused too."""
        body, base, bossSk, boss, fillet = self.bossWithFillet()
        topSk = body.newObject("Sketcher::SketchObject", "TopSk")
        topSk.AttachmentSupport = [(fillet, faceAt(fillet, 15))]
        topSk.MapMode = "FlatFace"
        rect(topSk, 15, 15, 25, 25)
        top = pad(body, "Top", topSk, 5)
        self.doc.recompute()
        self.assertTrue(top.isValid(), top.getStatusString())
        why = "'TopSk' uses 'Fillet', which would go to the new part"
        self.assertEqual(PartDesign.newPartRefusal(boss), why)
        names = sorted(o.Name for o in self.doc.Objects)
        with self.assertRaises(ValueError) as caught:
            PartDesign.newPartFrom(boss)
        self.assertIn(why, str(caught.exception))
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertIs(body.Tip, top)
        self.assertIn("is the first solid of", PartDesign.newPartRefusal(base))

    def testNewPartDropsItsMerge(self):
        """B5-4's New: the lid pad merged with a part beside it, nothing after the Merge: New part
        drops the Merge (the part is a part again, 16000) and takes the pad (4500 for 30 x 30 x 5).
        With a pocket after the Merge, refused, naming it, unless the Merge counts as gone
        (ignoreMerge: the dialog's whole scope unticked)."""
        body, base, lidSk = self.enclosure()
        lid = pad(body, "Lid", lidSk, 5)
        self.doc.recompute()
        right = self.doc.addObject("PartDesign::Body", "Right")
        pad(right, "RightPad", sketch(right, "RightSk", xyPlane(right), (30, 0, 70, 40), z=10), 10)
        self.doc.recompute()
        merge = PartDesign.setMergeScope(lid, [right])
        self.doc.recompute()
        self.assertTrue(merge.isValid(), merge.getStatusString())
        cornerSk = sketch(body, "CornerSk", xyPlane(body), (35, 35, 40, 40), z=10)
        corner = body.newObject("PartDesign::Pocket", "Corner")
        corner.Profile = cornerSk
        corner.Length = 5
        self.doc.recompute()
        self.assertTrue(corner.isValid(), corner.getStatusString())
        self.assertIn("'Corner' builds on 'Merge'", PartDesign.newPartRefusal(lid))
        self.assertEqual(PartDesign.newPartRefusal(lid, True), "")
        body.removeObject(corner)
        self.doc.removeObject(corner.Name)
        self.doc.recompute()
        self.assertEqual(PartDesign.newPartRefusal(lid), "")
        mergeName = merge.Name
        part = PartDesign.newPartFrom(lid)
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(mergeName))
        self.assertIsNone(right.MergedInto)
        self.assertEqual(part.Group, [lidSk, lid])
        self.assertAlmostEqual(right.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(part.Shape.Volume, 4500, places=3)
        self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)


class TestOperations(unittest.TestCase):
    """Onshape's New / Add / Remove / Intersect on one Pad or Pocket (FreeCAD-CH ops#640): a Pad can
    cut and a Pocket can add, each sweeping to its class's side, and Add to part, New part the other
    way (PartDesign.addToPart). Designed geometry: A1's enclosure, 40 x 40 x 10 (16000), and its lid
    sketch, 30 x 30 on the top face."""

    def setUp(self):
        self.doc = App.newDocument("TestOperations")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def enclosure(self):
        body = self.doc.addObject("PartDesign::Body", "Enclosure")
        base = pad(body, "Base", sketch(body, "BaseSk", xyPlane(body), (0, 0, 40, 40)), 10)
        self.doc.recompute()
        lidSk = body.newObject("Sketcher::SketchObject", "LidSk")
        lidSk.AttachmentSupport = [(base, faceAt(base, 10))]
        lidSk.MapMode = "FlatFace"
        rect(lidSk, 0, 0, 30, 30)
        self.body, self.base, self.lidSk = body, base, lidSk
        return body

    def assertValid(self):
        self.assertEqual(
            [(o.Name, o.getStatusString()) for o in self.doc.Objects if not o.isValid()], []
        )

    def testPadAndPocketTakeEveryOperation(self):
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 10)
        pocket = self.doc.addObject("PartDesign::Pocket", "Loose")
        for feature in (lid, pocket):
            self.assertEqual(
                feature.getEnumerationsOfProperty("Operation"), ["Union", "Subtraction", "Common"]
            )
        self.assertEqual(lid.Operation, "Union")
        self.assertEqual(pocket.Operation, "Subtraction")

    def testPadCuts(self):
        """The lid pad, 10 up (25000), set to Subtraction and reversed: the 30 x 30 x 10 goes
        through the enclosure (7000); Common: the shared 30 x 30 x 10 (9000)."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 25000, places=3)
        lid.Operation = "Subtraction"
        lid.Reversed = True
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 7000, places=3)
        lid.Operation = "Common"
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 9000, places=3)

    def testPocketAdds(self):
        """A pocket of the lid sketch, 5 deep (11500), set to Union and reversed: the 30 x 30 x 5
        plate on top (20500)."""
        body = self.enclosure()
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.lidSk
        pocket.Length = 5
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 11500, places=3)
        pocket.Operation = "Union"
        pocket.Reversed = True
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 20500, places=3)
        self.assertAlmostEqual(body.Shape.BoundBox.ZMax, 15, places=6)

    def testACutWithNothingBeforeItMakesNothing(self):
        """A regression guard, not H3's proof: this passed before ops#640 H3 too (ops#308 F8 failed
        the feature and passThroughBase wrote the empty base into Shape; review app-1). A Remove
        or an Intersect with nothing before it never makes its tool material. A Pad of a 30 x 30
        square, 10 up, its Body's first solid (9000), set to Subtraction: an empty shape, not the
        9000 tool, and in error, "Nothing to cut" (F8, kept; the dialog doesn't offer this on a
        new part touching nothing, ops#640 H3); Common the same; a Refine-only change keeps it
        empty. Union again: the 9000 block, valid."""
        body = self.doc.addObject("PartDesign::Body", "Body")
        block = pad(body, "Block", sketch(body, "BlockSk", xyPlane(body), (0, 0, 30, 30)), 10)
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 9000, places=3)
        for operation in ("Subtraction", "Common"):
            block.Operation = operation
            self.doc.recompute()
            self.assertFalse(block.isValid(), operation)
            self.assertIn("Nothing to cut", block.getStatusString(), operation)
            self.assertEqual(volume(block.Shape), 0, operation)
            self.assertEqual(volume(body.Shape), 0, operation)
            block.Refine = not block.Refine
            self.doc.recompute()
            self.assertEqual(volume(block.Shape), 0, operation + ", Refine changed")
        block.Operation = "Union"
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 9000, places=3)

    def testACutThatMissesLeavesThePart(self):
        """ops#640 H3: a pocket of a 10 x 10 square at x 100, beside the enclosure (16000), 5 deep
        from z 10: valid, the enclosure unchanged (16000), with the note. Intersect the same (it
        failed before H3: an empty common). The lid pocket, which cuts, has no note (11500)."""
        body = self.enclosure()
        self.doc.recompute()
        farSk = sketch(body, "FarSk", xyPlane(body), (100, 0, 110, 10), z=10)
        miss = body.newObject("PartDesign::Pocket", "Miss")
        miss.Profile = farSk
        miss.Length = 5
        self.doc.recompute()
        for operation in ("Subtraction", "Common"):
            miss.Operation = operation
            self.doc.recompute()
            self.assertValid()
            self.assertIn("Warning", miss.State, operation)
            self.assertIn(NO_INTERSECTION, miss.getStatusString(), operation)
            self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)
        miss.Operation = "Subtraction"
        hit = body.newObject("PartDesign::Pocket", "Hit")
        hit.Profile = self.lidSk
        hit.Length = 5
        self.doc.recompute()
        self.assertValid()
        self.assertNotIn("Warning", hit.State)
        self.assertAlmostEqual(body.Shape.Volume, 11500, places=3)

    def testAnIntersectThatMissesStaysTheBaseWhenRefined(self):
        """ops#640 H3: an Intersect that misses keeps its base as Shape, and keeps no raw result
        (the prism) for a Refine-only change: FeatureRefine::onlyHaveRefined would put the
        refined prism, a 10 x 10 x 5 positive solid (500), into Shape, valid and with no note.
        The pocket beside the enclosure on Common, its Refine toggled (both ways): 16000, valid,
        with the note."""
        body = self.enclosure()
        self.doc.recompute()
        farSk = sketch(body, "FarSk", xyPlane(body), (100, 0, 110, 10), z=10)
        miss = body.newObject("PartDesign::Pocket", "Miss")
        miss.Profile = farSk
        miss.Length = 5
        miss.Operation = "Common"
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)
        for _ in range(2):
            miss.Refine = not miss.Refine
            self.doc.recompute()
            self.assertValid()
            self.assertAlmostEqual(volume(miss.Shape), 16000, places=3)
            self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)
            self.assertIn(NO_INTERSECTION, miss.getStatusString())

    def testARemoveOutOfTheTopFaceMisses(self):
        """ops#640 H3, hands-on check R5's case: a sketch on the part's top face, Remove pointing
        out of the part. Onshape: "Selected tools and targets do not intersect", healthy. The tool
        shares the top face (distance 0), so the miss is judged by volume, not contact. The lid
        pad, 5, set to Subtraction, not reversed (a Pad keeps its side: up, out of the part):
        valid, 16000, with the note. Reversed: it cuts the 30 x 30 x 5 (11500), and the note goes
        (DocumentObject::recompute clears it)."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 5)
        lid.Operation = "Subtraction"
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 16000, places=3)
        self.assertIn("Warning", lid.State)
        self.assertIn(NO_INTERSECTION, lid.getStatusString())
        lid.Reversed = True
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 11500, places=3)
        self.assertNotIn("Warning", lid.State)
        self.assertNotIn(NO_INTERSECTION, lid.getStatusString())

    def testReferenceAxisSideIsTheClasss(self):
        """Along the lid sketch's normal as its ReferenceAxis, a Pad set to Subtraction keeps the
        Pad's side, so reversed it cuts (7000). The side followed the Operation before: it went up
        and cut nothing (16000)."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 10)
        lid.ReferenceAxis = (self.lidSk, ["N_Axis"])
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 25000, places=3)
        lid.Operation = "Subtraction"
        lid.Reversed = True
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 7000, places=3)

    def reload(self, name):
        """Saves the document, closes it and opens it again (self.doc is the reopened one)."""
        path = os.path.join(tempfile.mkdtemp(), name + ".FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        return self.doc

    def assertComputes(self, volume):
        """The enclosure's saved shape is `volume`, and a recompute gives the same."""
        body = self.doc.getObject("Enclosure")
        self.assertAlmostEqual(body.Shape.Volume, volume, places=3)
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, volume, places=3)

    def testASavedOneOperationListComesBackWhole(self):
        """A Pad saved with the list of a build before ops#640 (["Union"]) reads back with all
        three, its value kept, and computes as saved (25000)."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        lid.Operation = ["Union"]
        self.assertEqual(lid.getEnumerationsOfProperty("Operation"), ["Union"])
        self.doc.recompute()
        self.reload("OldOperation")
        lid = self.doc.getObject("Lid")
        self.assertEqual(lid.getEnumerationsOfProperty("Operation"), ["Union", "Subtraction", "Common"])
        self.assertEqual(lid.Operation, "Union")
        self.assertComputes(25000)
        lid.Operation = "Subtraction"
        lid.Reversed = True
        self.doc.recompute()
        self.assertAlmostEqual(self.doc.getObject("Enclosure").Shape.Volume, 7000, places=3)

    def testASavedCuttingPadReloadsCutting(self):
        """The saved-file effect the ledger states, a Pad saved cutting: the lid pad set to
        Subtraction and reversed (7000), saved and reopened, is still a reversed Subtraction with
        the three-item list, and computes 7000. A cut that reopened as a boss would be a silent
        wrong result on every reload."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 10)
        lid.Operation = "Subtraction"
        lid.Reversed = True
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 7000, places=3)
        self.reload("CuttingPad")
        lid = self.doc.getObject("Lid")
        self.assertEqual(
            lid.getEnumerationsOfProperty("Operation"), ["Union", "Subtraction", "Common"]
        )
        self.assertEqual(lid.Operation, "Subtraction")
        self.assertTrue(lid.Reversed)
        self.assertComputes(7000)

    def testASavedAddingPocketReloadsAdding(self):
        """The same for a Pocket saved adding: the lid pocket, 5, set to Union and reversed (the
        30 x 30 x 5 plate on top, 20500), saved and reopened: a reversed Union, 20500."""
        body = self.enclosure()
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.lidSk
        pocket.Length = 5
        pocket.Operation = "Union"
        pocket.Reversed = True
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 20500, places=3)
        self.reload("AddingPocket")
        pocket = self.doc.getObject("Pocket")
        self.assertEqual(
            pocket.getEnumerationsOfProperty("Operation"), ["Union", "Subtraction", "Common"]
        )
        self.assertEqual(pocket.Operation, "Union")
        self.assertTrue(pocket.Reversed)
        self.assertComputes(20500)
        self.assertAlmostEqual(self.doc.getObject("Enclosure").Shape.BoundBox.ZMax, 15, places=6)

    def testAPadCutsThroughAll(self):
        """D1 of the review (app-2): one end-type list, so a Pad that cuts offers Through all. It
        is appended after the Pad's own six (Type is restored by index, so none moves). The lid
        pad set to Subtraction, reversed, through all: the 30 x 30 goes through the enclosure
        (7000). Saved and reopened: still through all, 7000."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 10)
        for prop in ("Type", "Type2"):
            self.assertEqual(
                lid.getEnumerationsOfProperty(prop),
                # Up to vertex appended after (ops#640 rank 22): none moves
                ["Length", "UpToLast", "UpToFirst", "UpToFace", "?TwoLengths", "UpToShape",
                 "ThroughAll", "UpToVertex"],
            )
        lid.Operation = "Subtraction"
        lid.Reversed = True
        lid.Type = "ThroughAll"
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 7000, places=3)
        self.reload("ThroughAllPad")
        lid = self.doc.getObject("Lid")
        self.assertEqual(lid.Type, "ThroughAll")
        self.assertEqual(lid.Operation, "Subtraction")
        self.assertComputes(7000)

    def testAPocketAddsUpToLast(self):
        """D1 the other way: a Pocket that adds offers To last, appended after the Pocket's own
        six. A 30 x 30 square sketched 20 up, a pocket of it (down, against the sketch's normal)
        set to Union and To last: a column down to the enclosure's bottom face, 30 x 30 x 20 of
        which the upper 10 is new (16000 + 9000), from z 0 to 20. Saved and reopened: the same."""
        body = self.enclosure()
        highSk = sketch(body, "HighSk", xyPlane(body), (0, 0, 30, 30), z=20)
        pocket = body.newObject("PartDesign::Pocket", "Column")
        pocket.Profile = highSk
        for prop in ("Type", "Type2"):
            self.assertEqual(
                pocket.getEnumerationsOfProperty(prop),
                # Up to vertex appended after (ops#640 rank 22): none moves
                ["Length", "ThroughAll", "UpToFirst", "UpToFace", "?TwoLengths", "UpToShape",
                 "UpToLast", "UpToVertex"],
            )
        pocket.Operation = "Union"
        pocket.Type = "UpToLast"
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 25000, places=3)
        self.assertAlmostEqual(body.Shape.BoundBox.ZMin, 0, places=6)
        self.assertAlmostEqual(body.Shape.BoundBox.ZMax, 20, places=6)
        self.reload("UpToLastPocket")
        pocket = self.doc.getObject("Column")
        self.assertEqual(pocket.Type, "UpToLast")
        self.assertEqual(pocket.Operation, "Union")
        self.assertComputes(25000)

    def testAddToPartTakesNewPartBack(self):
        """The lid pad (5) made a new part, then added to the enclosure: the enclosure holds the
        sketch and the pad where they were, the pad is its Tip on the base (20500), and the new
        Body is gone with its origin."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 5)
        self.doc.recompute()
        group = body.Group
        part = PartDesign.newPartFrom(lid)
        self.doc.recompute()
        partName, originName = part.Name, part.Origin.Name
        # the rule's own binding, as the dialog's rows read it: '' when allowed, a TypeError
        # when the target is not a Body
        self.assertEqual(PartDesign.addToPartRefusal(lid, body), "")
        with self.assertRaises(TypeError):
            PartDesign.addToPartRefusal(lid, lid)
        self.assertIs(PartDesign.addToPart(lid, body), body)
        self.doc.recompute()
        self.assertEqual(body.Group, group)
        self.assertIs(body.Tip, lid)
        self.assertIs(lid.BaseFeature, self.base)
        self.assertIsNone(self.doc.getObject(partName))
        self.assertIsNone(self.doc.getObject(originName))
        self.assertAlmostEqual(body.Shape.Volume, 20500, places=3)
        self.assertValid()

    def testAddToPartGoesWhereTheHistoryHasIt(self):
        """The lid (5) a new part, then a corner cut in the enclosure, through all upward over
        25..40 x 25..40 (13750). Added to the enclosure, the lid goes between the base and the
        cut, which now also cuts the lid's 5 x 5 x 5 corner: 13750 + 4500 - 125 = 18125; the cut
        stays the Tip."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 5)
        self.doc.recompute()
        PartDesign.newPartFrom(lid)
        self.doc.recompute()
        cornerSk = sketch(body, "CornerSk", xyPlane(body), (25, 25, 40, 40))
        corner = body.newObject("PartDesign::Pocket", "Corner")
        corner.Profile = cornerSk
        corner.Type = "ThroughAll"
        corner.Reversed = True
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 13750, places=3)
        PartDesign.addToPart(lid, body)
        self.doc.recompute()
        self.assertEqual(
            [o.Name for o in body.Group], ["BaseSk", "Base", "LidSk", "Lid", "CornerSk", "Corner"]
        )
        self.assertIs(body.Tip, corner)
        self.assertIs(corner.BaseFeature, lid)
        self.assertFalse(lid.Visibility)
        self.assertAlmostEqual(body.Shape.Volume, 18125, places=3)
        self.assertValid()

    def testAddToPartRefusesWhatItCantTakeBack(self):
        """Refused, with nothing changed: a target in another studio, a rolled-back target, a
        member something outside the part uses (a binder of the lid in the enclosure: "'Binder'
        uses 'Lid'"), a member of the target between the lid and what builds on it in the
        history (round 9: the move would put it before)."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 5)
        self.doc.recompute()
        part = PartDesign.newPartFrom(lid)
        self.doc.recompute()

        def assertRefused(target, why=None):
            names = sorted(o.Name for o in self.doc.Objects)
            with self.assertRaises(ValueError) as caught:
                PartDesign.addToPart(lid, target)
            if why:
                self.assertIn(why, str(caught.exception))
            self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
            self.assertIs(lid.getParentGeoFeatureGroup(), part)

        studio = self.doc.addObject("App::Part", "Studio")
        elsewhere = self.doc.addObject("PartDesign::Body", "Elsewhere")
        studio.addObject(elsewhere)
        assertRefused(elsewhere)
        body.Tip = None
        assertRefused(body)
        body.Tip = self.base
        binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(lid, ("",))]
        self.doc.recompute()
        assertRefused(body, "'Binder' uses 'Lid'")
        body.removeObject(binder)
        self.doc.removeObject(binder.Name)
        self.doc.recompute()
        self.assertEqual(PartDesign.addToPartRefusal(lid, body), "")
        # a corner cut in the enclosure, then a pad on the lid's top in the new part
        cornerSk = sketch(body, "CornerSk", xyPlane(body), (35, 35, 40, 40))
        corner = body.newObject("PartDesign::Pocket", "Corner")
        corner.Profile = cornerSk
        corner.Type = "ThroughAll"
        corner.Reversed = True
        self.doc.recompute()
        topSk = part.newObject("Sketcher::SketchObject", "TopSk")
        topSk.AttachmentSupport = [(lid, faceAt(lid, 15))]
        topSk.MapMode = "FlatFace"
        rect(topSk, 0, 0, 10, 10)
        top = pad(part, "Top", topSk, 5)
        self.doc.recompute()
        assertRefused(body, "'TopSk' comes after 'CornerSk' of 'Enclosure' in the history")
        self.assertIs(part.Tip, top)

    def testAddToPartTakesTheRestOfThePart(self):
        """Round 9 (journeys J8, J17): the new part's other members follow the lid into the
        enclosure, in order: a loose sketch on the part's own plane (relinked to the enclosure's)
        and a pad 10 x 10 x 5 on the lid's top, its sketch on that face. The enclosure is
        16000 + 4500 + 500, the pad its Tip on the lid; the new part is gone."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 5)
        self.doc.recompute()
        part = PartDesign.newPartFrom(lid)
        self.doc.recompute()
        looseSk = sketch(part, "LooseSk", xyPlane(part), (0, 0, 5, 5))
        topSk = part.newObject("Sketcher::SketchObject", "TopSk")
        topSk.AttachmentSupport = [(lid, faceAt(lid, 15))]
        topSk.MapMode = "FlatFace"
        rect(topSk, 0, 0, 10, 10)
        top = pad(part, "Top", topSk, 5)
        self.doc.recompute()
        self.assertAlmostEqual(part.Shape.Volume, 5000, places=3)
        self.assertEqual(PartDesign.addToPartRefusal(lid, body), "")
        partName = part.Name
        PartDesign.addToPart(lid, body)
        self.doc.recompute()
        self.assertEqual(
            [o.Name for o in body.Group],
            ["BaseSk", "Base", "LidSk", "Lid", "LooseSk", "TopSk", "Top"],
        )
        self.assertIsNone(self.doc.getObject(partName))
        self.assertIs(body.Tip, top)
        self.assertIs(top.BaseFeature, lid)
        self.assertIs(lid.BaseFeature, self.base)
        self.assertIs(looseSk.AttachmentSupport[0][0], body.Origin.OriginFeatures[3])
        self.assertTrue(top.Visibility)
        self.assertFalse(lid.Visibility)
        self.assertAlmostEqual(body.Shape.Volume, 21000, places=3)
        self.assertValid()

    def mirroredBoss(self, onDatum=None, datumFirst=False):
        """J17's variant B: Part1 40 x 30 x 10 over x -20..20 (12000); a boss 8 x 8 x 5 on its top
        at (-10, 15) (320), its sketch on that face; Mirrored of the boss about the Right plane, or
        about a datum plane: onDatum "origin" (on the Right plane), "face" (on Part1's +x side,
        offset 20 back to x = 0) or "boss" (the same face picked on the boss's result, which is
        Part1's material: review R9-1); with datumFirst the plane is made before the boss (R9-4).
        Returns (body, base, boss sketch, boss, mirror, datum or None); the part is 12640."""
        body = self.doc.addObject("PartDesign::Body", "Part1")
        base = pad(body, "Base", sketch(body, "BaseSk", xyPlane(body), (-20, 0, 20, 30)), 10)
        self.doc.recompute()
        right = body.Origin.OriginFeatures[5]
        self.assertEqual(right.Role, "YZ_Plane")
        boss = None

        def makeDatum():
            datum = body.newObject("PartDesign::Plane", "DatumPlane")
            if onDatum == "origin":
                datum.AttachmentSupport = [(right, "")]
            else:
                support = boss if onDatum == "boss" else base
                [side] = [
                    f"Face{i}"
                    for i, face in enumerate(support.Shape.Faces, 1)
                    if abs(face.normalAt(0, 0).x - 1) < 1e-9 and abs(face.CenterOfMass.x - 20) < 1e-6
                ]
                datum.AttachmentSupport = [(support, side)]
                datum.AttachmentOffset = App.Placement(V(0, 0, -20), App.Rotation())
            datum.MapMode = "FlatFace"
            self.doc.recompute()
            self.assertLess(abs(datum.Placement.Base.x), 1e-6)
            return datum

        datum = makeDatum() if onDatum and datumFirst else None
        bossSk = body.newObject("Sketcher::SketchObject", "BossSk")
        bossSk.AttachmentSupport = [(base, faceAt(base, 10))]
        bossSk.MapMode = "FlatFace"
        rect(bossSk, -14, 11, -6, 19)
        boss = pad(body, "Boss", bossSk, 5)
        self.doc.recompute()
        if onDatum and not datumFirst:
            datum = makeDatum()
        mirror = body.newObject("PartDesign::Mirrored", "Mirrored")
        mirror.Originals = [boss]
        mirror.MirrorPlane = (datum or right, [""])
        body.Tip = mirror
        self.doc.recompute()
        self.assertTrue(mirror.isValid(), mirror.getStatusString())
        self.assertIs(mirror.BaseFeature, boss)
        self.assertAlmostEqual(body.Shape.Volume, 12640, places=3)
        return body, base, bossSk, boss, mirror, datum

    def testAddToPartTakesTheMirrorBack(self):
        """J17's variant B: the boss made a new part takes the mirror along (640); Add to Part1
        takes both back in one undo step: Part1 is one part again, the mirror merged, 12000 plus
        both bosses, its plane Part1's own Right plane. Undo: two parts again."""
        self.doc.UndoMode = 1
        body, base, bossSk, boss, mirror, datum = self.mirroredBoss()
        part = PartDesign.newPartFrom(boss)
        self.doc.recompute()
        self.assertEqual(part.Group, [bossSk, boss, mirror])
        self.assertIs(mirror.MirrorPlane[0], part.Origin.OriginFeatures[5])
        self.assertAlmostEqual(part.Shape.Volume, 640, places=3)
        self.assertAlmostEqual(body.Shape.Volume, 12000, places=3)
        self.assertEqual(PartDesign.addToPartRefusal(boss, body), "")
        partName = part.Name
        self.doc.openTransaction("Add")
        PartDesign.addToPart(boss, body)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual([o.Name for o in body.Group], ["BaseSk", "Base", "BossSk", "Boss", "Mirrored"])
        self.assertIsNone(self.doc.getObject(partName))
        self.assertIs(body.Tip, mirror)
        self.assertIs(boss.BaseFeature, base)
        self.assertIs(mirror.BaseFeature, boss)
        self.assertIs(mirror.MirrorPlane[0], body.Origin.OriginFeatures[5])
        self.assertAlmostEqual(body.Shape.Volume, 12640, places=3)
        self.assertTrue(body.Shape.isInside(V(10, 15, 12), 1e-6, True), "the mirrored boss")
        self.assertValid()
        self.doc.undo()
        self.doc.recompute()
        part = self.doc.getObject(partName)
        self.assertIsNotNone(part)
        self.assertEqual(part.Group, [bossSk, boss, mirror])
        self.assertEqual([o.Name for o in body.Group], ["BaseSk", "Base"])
        self.assertAlmostEqual(part.Shape.Volume, 640, places=3)
        self.assertAlmostEqual(body.Shape.Volume, 12000, places=3)

    def testNewPartTakesADatumOnTheOriginAlong(self):
        """Round 9 item 2: the mirror about a datum plane on Part1's Right plane, which only the
        mirror uses: New part takes the datum along, on the new part's Right plane (640, Part1
        12000); a second datum on the origin that nothing uses stays. Add takes them back
        (12640)."""
        body, base, bossSk, boss, mirror, datum = self.mirroredBoss("origin")
        unused = body.newObject("PartDesign::Plane", "Unused")
        unused.AttachmentSupport = [(body.Origin.OriginFeatures[4], "")]
        unused.MapMode = "FlatFace"
        self.doc.recompute()
        self.assertEqual(PartDesign.newPartRefusal(boss), "")
        part = PartDesign.newPartFrom(boss)
        self.doc.recompute()
        self.assertEqual(part.Group, [bossSk, boss, datum, mirror])
        self.assertIs(datum.AttachmentSupport[0][0], part.Origin.OriginFeatures[5])
        self.assertIn(unused, body.Group)
        self.assertAlmostEqual(part.Shape.Volume, 640, places=3)
        self.assertAlmostEqual(body.Shape.Volume, 12000, places=3)
        self.assertValid()
        PartDesign.addToPart(boss, body)
        self.doc.recompute()
        self.assertEqual(
            [o.Name for o in body.Group],
            ["BaseSk", "Base", "BossSk", "Boss", "DatumPlane", "Mirrored", "Unused"],
        )
        self.assertIs(datum.AttachmentSupport[0][0], body.Origin.OriginFeatures[5])
        self.assertAlmostEqual(body.Shape.Volume, 12640, places=3)
        self.assertValid()

    def testNewPartTakesADatumMadeFirstAlong(self):
        """Review R9-4: the datum plane on the Right plane made before the boss (the usual order:
        the plane, then the Mirror), used only by the mirror: New part takes it along, before the
        boss's sketch as in Part1 (640; Part1 12000). Add takes them back in that order, and the
        saved history follows the part's order (R9-5)."""
        body, base, bossSk, boss, mirror, datum = self.mirroredBoss("origin", datumFirst=True)
        self.assertEqual(
            [o.Name for o in body.Group][2:], ["DatumPlane", "BossSk", "Boss", "Mirrored"]
        )
        self.assertEqual(PartDesign.newPartRefusal(boss), "")
        part = PartDesign.newPartFrom(boss)
        self.doc.recompute()
        self.assertEqual(part.Group, [datum, bossSk, boss, mirror])
        self.assertIs(datum.AttachmentSupport[0][0], part.Origin.OriginFeatures[5])
        self.assertAlmostEqual(part.Shape.Volume, 640, places=3)
        self.assertAlmostEqual(body.Shape.Volume, 12000, places=3)
        self.assertValid()
        PartDesign.addToPart(boss, body)
        self.doc.recompute()
        self.assertEqual(
            [o.Name for o in body.Group],
            ["BaseSk", "Base", "DatumPlane", "BossSk", "Boss", "Mirrored"],
        )
        self.assertAlmostEqual(body.Shape.Volume, 12640, places=3)
        self.assertValid()

    def testNewPartKeepsADatumOnTheBossFace(self):
        """Review R9-1: the datum plane on the +x side face picked on the boss's result, which is
        Part1's material (the boss was its Tip): it can't go along, and it uses the boss, so New
        part is refused as before round 9."""
        body, base, bossSk, boss, mirror, datum = self.mirroredBoss("boss")
        self.assertIs(datum.AttachmentSupport[0][0], boss)
        self.assertEqual(
            PartDesign.newPartRefusal(boss), "'DatumPlane' uses 'Boss', which would go to the new part"
        )

    def testAddToPartRefusesWhatWouldActOnTheTarget(self):
        """Reviews R9-2 and R9-3: in the new part, the mirror switched to the whole shape would
        mirror Part1 too once merged, and a pocket through the boss would cut Part1 too: Add to
        part refuses each, naming it, and nothing changes."""
        body, base, bossSk, boss, mirror, datum = self.mirroredBoss()
        part = PartDesign.newPartFrom(boss)
        self.doc.recompute()
        mirror.TransformMode = "Whole shape"
        self.doc.recompute()
        self.assertIn("'Mirrored' copies the whole of", PartDesign.addToPartRefusal(boss, body))
        mirror.TransformMode = "Features"
        self.doc.recompute()
        self.assertEqual(PartDesign.addToPartRefusal(boss, body), "")
        holeSk = sketch(part, "HoleSk", xyPlane(part), (-11, 14, -9, 16))
        hole = part.newObject("PartDesign::Pocket", "Pocket")
        hole.Profile = holeSk
        hole.Type = "ThroughAll"
        hole.Midplane = True
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        self.assertAlmostEqual(part.Shape.Volume, 640 - 4 * 5, places=3)
        names = sorted(o.Name for o in self.doc.Objects)
        self.assertEqual(PartDesign.addToPartRefusal(boss, body), "'Pocket' would cut 'Part1' too")
        with self.assertRaises(ValueError):
            PartDesign.addToPart(boss, body)
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)

    def testAddToPartRanksTheHistoryAsThePartHoldsIt(self):
        """Review R9-5: the lid sketch drawn, then a corner cut, then the lid pad on the cut; New
        part, then Add: the sketch now follows the cut in the enclosure, and its saved history rank
        does too."""
        body = self.enclosure()
        cornerSk = sketch(body, "CornerSk", xyPlane(body), (35, 35, 40, 40))
        corner = body.newObject("PartDesign::Pocket", "Corner")
        corner.Profile = cornerSk
        corner.Type = "ThroughAll"
        corner.Reversed = True
        self.doc.recompute()
        lid = pad(body, "Lid", self.lidSk, 5)
        self.doc.recompute()
        self.assertEqual(
            [o.Name for o in body.Group], ["BaseSk", "Base", "LidSk", "CornerSk", "Corner", "Lid"]
        )
        PartDesign.newPartFrom(lid)
        self.doc.recompute()
        PartDesign.addToPart(lid, body)
        self.doc.recompute()
        self.assertEqual(
            [o.Name for o in body.Group], ["BaseSk", "Base", "CornerSk", "Corner", "LidSk", "Lid"]
        )
        self.assertGreater(self.lidSk.HistoryRank, corner.HistoryRank)
        self.assertLess(self.lidSk.HistoryRank, lid.HistoryRank)
        self.assertValid()

    def testNewPartKeepsADatumOnWhatStays(self):
        """J17's refusal, kept: a datum plane on Part1's side face (what stays) can't go along, so
        the mirror about it can't either: "'Mirrored' uses 'DatumPlane', which stays in 'Part1'".
        A datum on the origin that a sketch staying in Part1 also uses stays too, with the same
        refusal."""
        body, base, bossSk, boss, mirror, datum = self.mirroredBoss("face")
        self.assertEqual(
            PartDesign.newPartRefusal(boss), "'Mirrored' uses 'DatumPlane', which stays in 'Part1'"
        )
        datum.AttachmentSupport = [(body.Origin.OriginFeatures[5], "")]
        datum.AttachmentOffset = App.Placement()
        self.doc.recompute()
        self.assertEqual(PartDesign.newPartRefusal(boss), "")
        onDatum = body.newObject("Sketcher::SketchObject", "OnDatum")
        onDatum.AttachmentSupport = [(datum, "")]
        onDatum.MapMode = "FlatFace"
        self.doc.recompute()
        self.assertEqual(
            PartDesign.newPartRefusal(boss), "'Mirrored' uses 'DatumPlane', which stays in 'Part1'"
        )

    def lidPart(self):
        """The lid pad, 10 up, made a part of its own (9000; the enclosure 16000)."""
        body = self.enclosure()
        lid = pad(body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        part = PartDesign.newPartFrom(lid)
        self.doc.recompute()
        self.assertAlmostEqual(part.Shape.Volume, 9000, places=3)
        return body, lid, part

    def assertAddRefused(self, lid, body, part, why):
        """addToPart(lid, body) refused with `why` in its text, and nothing changed"""
        names = sorted(o.Name for o in self.doc.Objects)
        self.assertIn(why, PartDesign.addToPartRefusal(lid, body))
        with self.assertRaises(ValueError) as caught:
            PartDesign.addToPart(lid, body)
        self.assertIn(why, str(caught.exception))
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertIs(lid.getParentGeoFeatureGroup(), part)
        self.assertEqual(part.Group, [self.lidSk, lid])

    def testAddToPartRefusesAPartABooleanUses(self):
        """D6 of the review (the App MISS on Body.cpp's addToPart): a Boolean in the enclosure
        fuses the lid's part, its tool being that Body (25000). addToPart would delete the Body
        under the Boolean, which then fails with no tools and passes its base through: refused,
        nothing changed, and the Boolean still fuses the part (25000)."""
        body, lid, part = self.lidPart()
        fuse = self.doc.addObject("PartDesign::Boolean", "Fuse")
        body.addObject(fuse)
        fuse.setObjects([part])
        self.doc.recompute()
        self.assertTrue(fuse.isValid(), fuse.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 25000, places=3)
        self.assertAddRefused(lid, body, part, "'Fuse' uses")
        self.assertEqual(fuse.Group, [part])
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 25000, places=3)

    def testAddToPartRefusesAMergedPart(self):
        """The same for a Merge of the lid's part into the enclosure (DeletePart refuses it too):
        refused, the Merge still valid (25000)."""
        body, lid, part = self.lidPart()
        merge = PartDesign.makeMerge(body, [part])
        self.doc.recompute()
        self.assertTrue(merge.isValid(), merge.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 25000, places=3)
        self.assertAddRefused(lid, body, part, "delete the Merge first")
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 25000, places=3)
