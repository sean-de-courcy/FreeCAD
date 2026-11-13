# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (slice 9 of parts-design 10.11): the part mirror
#
# A part mirror is a studio feature: a PartDesign::Mirrored in the studio, outside every Body, held
# by the studio's list, with PatternType "Part", the source part's id in StudioEntities, its
# MirrorPlane, a dynamic Operation (Union, Subtraction, Common: New is a Union whose scope is the
# part it made, as an Extrude owner's) and its scope in StudioScope. Its tool is the source part as it is just before the
# mirror (its last solid there), mirrored about the plane. Onshape's part mirror
# (notes/patterns-design.md 2, 3.1): New makes a new part following the source; Add merges the
# copy into the scope part it touches (the survivor); Remove cuts it from them; Intersect keeps
# their common part. Onshape oracle 9 (R4): an Add consumes the source part, outside the scope,
# exactly when the copy merges into a scope part and the source touches the merged result; the
# copy touching no scope part would be a new part (refused loudly until P6p). Remove, Intersect and
# New never consume the source.
#
# Designed geometry only: boxes and cylinders a few mm across, each a Body with a sketch and a Pad.
# Expected volumes and positions come from the geometry itself.

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import faceAt, pad, sketch, xyPlane

V = App.Vector
# The Result row's words -> the owner's Operation (FreeCAD's words, as an Extrude owner's); New is
# Union with the scope the parts it makes
OPERATIONS = {"New": "Union", "Add": "Union", "Remove": "Subtraction", "Intersect": "Common"}


def boxPart(doc, studio, name, x0, y0, x1, y1, z0, height):
    """A Body name in studio: the rectangle (x0, y0)-(x1, y1) at z0 padded height up."""
    body = doc.addObject("PartDesign::Body", name)
    studio.addObject(body)
    pad(body, name + "Pad", sketch(body, name + "Sk", xyPlane(body), (x0, y0, x1, y1), z=z0), height)
    return body


def cylinderPart(doc, studio, name, cx, cy, radius, z0, height):
    body = doc.addObject("PartDesign::Body", name)
    studio.addObject(body)
    sk = sketch(body, name + "Sk", xyPlane(body), z=z0)
    sk.addGeometry(Part.Circle(V(cx, cy, 0), V(0, 0, 1), radius))
    pad(body, name + "Pad", sk, height)
    return body


def originPlane(body, role):
    return [f for f in body.Origin.OriginFeatures if f.Role == role][0]


def offsetPlane(body, name, role, offset):
    """A datum plane in body on its origin plane role, offset along the plane's normal."""
    plane = body.newObject("PartDesign::Plane", name)
    plane.AttachmentSupport = [(originPlane(body, role), "")]
    plane.MapMode = "FlatFace"
    plane.AttachmentOffset = App.Placement(V(0, 0, offset), App.Rotation())
    return plane


def threePointPlane(body, name, points):
    """A datum plane in body through three datum points."""
    datums = []
    for i, p in enumerate(points):
        point = body.newObject("PartDesign::Point", f"{name}P{i}")
        point.MapMode = "Deactivated"
        point.Placement = App.Placement(p, App.Rotation())
        datums.append(point)
    plane = body.newObject("PartDesign::Plane", name)
    plane.AttachmentSupport = [(d, "") for d in datums]
    plane.MapMode = "ThreePointsPlane"
    return plane


def partMirror(doc, studio, name, source, plane, operation="New", scope=(), index=-1):
    """A part mirror of the part id source about plane (a link sub), listed at index (-1: the
    bar); New makes its new part. No recompute."""
    owner = doc.addObject("PartDesign::Mirrored", name)
    studio.addObject(owner)
    owner.PatternType = "Part"
    owner.StudioEntities = [source] if isinstance(source, str) else list(source)
    owner.MirrorPlane = plane
    owner.Refine = False
    owner.addProperty("App::PropertyEnumeration", "Operation", "Studio")
    owner.Operation = ["Union", "Subtraction", "Common"]
    owner.Operation = OPERATIONS[operation]
    owner.StudioScope = list(scope)
    PartDesign.studioInsert(owner, index)
    if operation == "New":
        PartDesign.studioNewPart(owner)
    return owner


class TestStudioPartMirror(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestStudioPartMirror")
        self.doc.UndoMode = 1
        self.studio = self.doc.addObject("App::Part", "S")
        self.dir = None

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestStudioPartMirror"):
                App.closeDocument(doc.Name)
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers
    def listed(self):
        """The studio's list, made now (it adopts every Body's features)."""
        self.doc.recompute()
        self.list = PartDesign.studioList(self.studio, True)
        return self.list

    def mirror(self, *args, **kwargs):
        self.doc.openTransaction("mirror")
        owner = partMirror(self.doc, self.studio, *args, **kwargs)
        self.doc.commitTransaction()
        self.doc.recompute()
        return owner

    def made(self, owner):
        return [
            b for b in self.studio.Group
            if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner
        ]

    def live(self):
        return sorted(b.Name for b in PartDesign.studioLiveParts(self.list))

    def shape(self, part):
        body = self.doc.getObject(part)
        return body.Tip.Shape if body.Tip else Part.Shape()

    def assertVolume(self, part, expected, places=3):
        self.assertAlmostEqual(self.shape(part).Volume, expected, places=places, msg=part)

    def assertValid(self, *objects):
        for obj in objects:
            self.assertTrue(obj.isValid(), f"{obj.Name}: {obj.getStatusString()}")

    def assertPoint(self, part, point, inside):
        self.assertEqual(
            self.shape(part).isInside(point, 1e-6, True), inside, f"{part} at {point}"
        )

    def assertCentre(self, shape, expected):
        centre = (shape.Solids[0] if len(shape.Solids) == 1 else shape).CenterOfMass
        for got, want in zip(centre, expected):
            self.assertAlmostEqual(got, want, places=4)

    # ------------------------------------------------------------------------------- New
    def blockAndPlane(self):
        """Block S 10 x 20 x 5 (x 0..10, y 0..20) and, in part D, a datum plane x = 30 (an offset
        of D's YZ plane)."""
        s = boxPart(self.doc, self.studio, "Src", 0, 0, 10, 20, 0, 5)
        d = boxPart(self.doc, self.studio, "D", 100, 0, 110, 10, 0, 5)
        plane = offsetPlane(d, "X30", "YZ_Plane", 30)
        self.listed()
        return s, d, plane

    def testNewMakesAMirroredPart(self):
        """New: a new part holding only the mirrored block (x 50..60), equal volume, centroid
        mirrored about x = 30; the source stays live and unchanged."""
        s, d, plane = self.blockAndPlane()
        m = self.mirror("Mir", "Src", (plane, [""]))
        self.assertValid(m)
        self.assertTrue(m.Shape.isNull())
        [new] = self.made(m)
        self.assertValid(*[o for o in new.Group if o.isDerivedFrom("PartDesign::Feature")])
        self.assertAlmostEqual(new.Shape.Volume, 1000, places=3)
        self.assertEqual(len(new.Shape.Solids), 1)
        self.assertCentre(new.Shape, (55, 10, 2.5))
        self.assertVolume("Src", 1000)
        self.assertCentre(self.shape("Src"), (5, 10, 2.5))
        self.assertIn("Src", self.live())
        self.assertIn(new.Name, self.live())
        self.assertIsNone(PartDesign.studioStepOf(m, s))

    def testNewFollowsTheSourceAndThePlane(self):
        """The source's pad made 8 high, before the mirror: the new part follows (1600); the
        plane moved to x = 40: it moves to x 70..80."""
        s, d, plane = self.blockAndPlane()
        m = self.mirror("Mir", "Src", (plane, [""]))
        [new] = self.made(m)
        self.doc.getObject("SrcPad").Length = 8
        self.doc.recompute()
        self.assertAlmostEqual(new.Shape.Volume, 1600, places=3)
        self.assertCentre(new.Shape, (55, 10, 4))
        plane.AttachmentOffset = App.Placement(V(0, 0, 40), App.Rotation())
        self.doc.recompute()
        self.assertValid(m)
        self.assertCentre(new.Shape, (75, 10, 4))
        self.assertAlmostEqual(new.Shape.Volume, 1600, places=3)

    def testNewAboutAFaceOfAnotherPart(self):
        """The plane: W's face at x = 30 (W is x 30..35). New gives x 50..60."""
        s = boxPart(self.doc, self.studio, "Src", 0, 0, 10, 20, 0, 5)
        w = boxPart(self.doc, self.studio, "W", 30, 0, 35, 10, 0, 5)
        self.listed()
        wpad = self.doc.getObject("WPad")
        face = [
            f"Face{i}" for i, f in enumerate(wpad.Shape.Faces, 1)
            if abs(f.CenterOfMass.x - 30) < 1e-6 and abs(abs(f.normalAt(0, 0).x) - 1) < 1e-9
        ][0]
        m = self.mirror("Mir", "Src", (wpad, [face]))
        self.assertValid(m)
        [new] = self.made(m)
        self.assertCentre(new.Shape, (55, 10, 2.5))
        self.assertAlmostEqual(new.Shape.Volume, 1000, places=3)
        self.assertVolume("W", 250)

    # ------------------------------------------------------------------------------- Add
    def testAddIntoItselfAboutItsOwnFace(self):
        """Add into the source about its own face x = 10: one part x 0..20, double volume."""
        s = boxPart(self.doc, self.studio, "Src", 0, 0, 10, 20, 0, 5)
        self.listed()
        spad = self.doc.getObject("SrcPad")
        face = [
            f"Face{i}" for i, f in enumerate(spad.Shape.Faces, 1)
            if abs(f.CenterOfMass.x - 10) < 1e-6
        ][0]
        m = self.mirror("Mir", "Src", (spad, [face]), "Add", ("Src",))
        self.assertValid(m)
        step = PartDesign.studioStepOf(m, s)
        self.assertIsNotNone(step)
        self.assertValid(step)
        self.assertEqual(step.Operation, "Union")
        self.assertIs(s.Tip, step)
        self.assertVolume("Src", 2000)
        self.assertEqual(len(self.shape("Src").Solids), 1)
        self.assertCentre(self.shape("Src"), (10, 10, 2.5))
        self.assertEqual(self.live(), ["Src"])
        self.assertFalse(self.made(m))

    # Onshape oracle 9, case R4: cubes Y (x 0..10 or 2..12) and X, Y mirrored about its YZ plane,
    # Add, scope X only
    def cubes(self, y0, x0):
        y = boxPart(self.doc, self.studio, "Y", y0, 0, y0 + 10, 10, 0, 10)
        x = boxPart(self.doc, self.studio, "X", x0, 0, x0 + 10, 10, 0, 10)
        self.listed()
        return y, x

    def testAddMergesTheSourceTouchingItsCopy(self):
        """R4: Y (x 0..10) touches its copy (x -10..0), X (x -20..-10) touches the copy: one part
        with X's id, 3000; Y is consumed though outside the scope. Suppressed or undone: Y lives
        again, X 1000."""
        y, x = self.cubes(0, -20)
        m = self.mirror("Mir", "Y", (originPlane(y, "YZ_Plane"), [""]), "Add", ("X",))
        self.assertValid(m, PartDesign.studioStepOf(m, x))
        self.assertVolume("X", 3000)
        self.assertEqual(len(self.shape("X").Solids), 1)
        self.assertCentre(self.shape("X"), (-5, 5, 5))
        self.assertEqual(self.live(), ["X"])
        self.assertIs(PartDesign.studioConsumerOf(y), m)
        self.assertFalse(y.Visibility)
        self.assertIsNone(PartDesign.studioStepOf(m, y))
        self.doc.openTransaction("suppress")
        PartDesign.studioSuppress(m, True)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(self.live(), ["X", "Y"])
        self.assertVolume("X", 1000)
        self.assertTrue(y.Visibility)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.live(), ["X"])
        self.assertVolume("X", 3000)
        self.doc.undo()  # the mirror
        self.doc.recompute()
        self.assertEqual(self.live(), ["X", "Y"])
        self.assertVolume("X", 1000)
        self.assertVolume("Y", 1000)

    def testAddLeavesTheSourceApartFromItsCopy(self):
        """R4: Y (x 2..12) apart from its copy (x -12..-2), X (x -22..-12) touches the copy:
        X + copy = 2000 with X's id, Y unchanged and live."""
        y, x = self.cubes(2, -22)
        m = self.mirror("Mir", "Y", (originPlane(y, "YZ_Plane"), [""]), "Add", ("X",))
        self.assertValid(m)
        self.assertVolume("X", 2000)
        self.assertEqual(len(self.shape("X").Solids), 1)
        self.assertVolume("Y", 1000)
        self.assertEqual(self.live(), ["X", "Y"])
        self.assertIsNone(PartDesign.studioConsumerOf(y))

    def testAddCopyTouchingOnlyTheSourceIsRefused(self):
        """R4: Y touches its copy, X (x -30..-20) is apart: Onshape makes the copy a new part
        (P6p): refused loudly; Y not merged, X unchanged."""
        y, x = self.cubes(0, -30)
        m = self.mirror("Mir", "Y", (originPlane(y, "YZ_Plane"), [""]), "Add", ("X",))
        self.assertFalse(m.isValid())
        self.assertIn("touches no part of the merge scope", m.getStatusString())
        self.assertVolume("X", 1000)
        self.assertVolume("Y", 1000)
        self.assertEqual(self.live(), ["X", "Y"])

    def testAddTouchingNoScopePartIsRefused(self):
        """S2's refusal: the mirrored copy touches no part of the scope (it would be a new part,
        P6p): the mirror fails, no part changes."""
        s, d, plane = self.blockAndPlane()
        m = self.mirror("Mir", "Src", (plane, [""]), "Add", ("Src",))
        self.assertFalse(m.isValid())
        self.assertIn("touches no part of the merge scope", m.getStatusString())
        self.assertVolume("Src", 1000)

    def testAddTouchingTwoScopePartsIsRefused(self):
        """The copy bridges two scope parts (merging them is not done yet): loud, not two
        overlapping parts."""
        s = boxPart(self.doc, self.studio, "Src", 0, 0, 10, 10, 0, 5)
        boxPart(self.doc, self.studio, "A", -20, 0, -8, 10, 0, 5)
        boxPart(self.doc, self.studio, "B", -6, 0, -2, 10, 0, 5)
        self.listed()
        # The copy, x -10..0, overlaps A (x -20..-8) and B (x -6..-2), which are apart
        m = self.mirror("Mir", "Src", (originPlane(s, "YZ_Plane"), [""]), "Add", ("A", "B"))
        self.assertFalse(m.isValid())
        self.assertIn("merge", m.getStatusString())
        self.assertVolume("A", 600)
        self.assertVolume("B", 200)

    # ------------------------------------------------------------------------------- Remove
    def plateAndCylinder(self):
        """Plate P x -20..20, y 0..20, z 0..5 and cylinder C r 3 at (10, 10), z -1..6."""
        p = boxPart(self.doc, self.studio, "P", -20, 0, 20, 20, 0, 5)
        c = cylinderPart(self.doc, self.studio, "C", 10, 10, 3, -1, 7)
        self.listed()
        return p, c

    def testRemoveCutsTheMirroredCylinderAndKeepsTheSource(self):
        """Remove of C mirrored about C's YZ plane (an origin plane) from P: P loses pi 9 5 at
        x = -10, not at x = 10; C stays live and unchanged."""
        p, c = self.plateAndCylinder()
        m = self.mirror("Mir", "C", (originPlane(c, "YZ_Plane"), [""]), "Remove", ("P",))
        self.assertValid(m)
        step = PartDesign.studioStepOf(m, p)
        self.assertValid(step)
        self.assertEqual(step.Operation, "Subtraction")
        self.assertVolume("P", 4000 - math.pi * 9 * 5)
        self.assertPoint("P", V(-10, 10, 2.5), False)
        self.assertPoint("P", V(10, 10, 2.5), True)
        self.assertVolume("C", math.pi * 9 * 7)
        self.assertEqual(self.live(), ["C", "P"])
        self.assertTrue(c.Visibility)
        self.assertIsNone(PartDesign.studioConsumerOf(c))

    def testEditsAsListEdits(self):
        """Suppress, the bar above it, delete, undo, redo, save and reopen: each as a list edit."""
        p, c = self.plateAndCylinder()
        m = self.mirror("Mir", "C", (originPlane(c, "YZ_Plane"), [""]), "Remove", ("P",))
        cut = 4000 - math.pi * 9 * 5
        self.assertVolume("P", cut)
        # Suppressed: P whole; back on: cut
        self.doc.openTransaction("suppress")
        PartDesign.studioSuppress(m, True)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertVolume("P", 4000)
        self.doc.openTransaction("unsuppress")
        PartDesign.studioSuppress(m, False)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertVolume("P", cut)
        # The bar above it: P whole at the bar; back at the end: cut
        at = list(self.list.Entries).index(m)
        self.doc.openTransaction("bar")
        PartDesign.studioSetBar(self.list, at)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertVolume("P", 4000)
        self.doc.openTransaction("bar end")
        PartDesign.studioSetBar(self.list, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertVolume("P", cut)
        # Save and reopen
        self.dir = tempfile.mkdtemp(prefix="partmirror")
        path = os.path.join(self.dir, "mirror.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.doc.UndoMode = 1
        self.studio = self.doc.getObject("S")
        self.list = PartDesign.studioList(self.studio, False)
        m = self.doc.getObject("Mir")
        self.assertEqual(m.PatternType, "Part")
        self.assertEqual(m.Operation, "Subtraction")
        self.assertEqual(list(m.StudioEntities), ["C"])
        self.doc.getObject("CPad").touch()
        self.doc.recompute()
        self.assertValid(m)
        self.assertVolume("P", cut)
        # Delete: P whole; undo: cut; redo: whole
        self.doc.openTransaction("delete")
        PartDesign.studioRemove(m)
        self.doc.removeObject("Mir")
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertVolume("P", 4000)
        self.doc.undo()
        self.doc.recompute()
        self.assertVolume("P", cut)
        self.doc.redo()
        self.doc.recompute()
        self.assertVolume("P", 4000)

    def testSourceEditedBeforeTheMirror(self):
        """C's radius 3 -> 4 (before the mirror): P loses pi 16 5; moved after the mirror (a
        later feature of C), it doesn't reach P."""
        p, c = self.plateAndCylinder()
        m = self.mirror("Mir", "C", (originPlane(c, "YZ_Plane"), [""]), "Remove", ("P",))
        sk = self.doc.getObject("CSk")
        sk.Geometry = [Part.Circle(V(10, 10, 0), V(0, 0, 1), 4)]
        self.doc.recompute()
        self.assertVolume("P", 4000 - math.pi * 16 * 5)
        # A boss on C after the mirror: C grows, the copy doesn't
        self.doc.openTransaction("boss")
        bsk = c.newObject("Sketcher::SketchObject", "CBossSk")
        bsk.AttachmentSupport = xyPlane(c)
        bsk.MapMode = "FlatFace"
        bsk.AttachmentOffset = App.Placement(V(0, 0, 6), App.Rotation())
        bsk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 1))
        boss = c.newObject("PartDesign::Pad", "CBoss")
        boss.Profile = bsk
        boss.Length = 2
        for obj in (bsk, boss):
            if obj not in self.list.Entries:
                PartDesign.studioInsert(obj, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertGreater(list(self.list.Entries).index(boss), list(self.list.Entries).index(m))
        self.assertVolume("C", math.pi * 16 * 7 + math.pi * 2)
        self.assertVolume("P", 4000 - math.pi * 16 * 5)
        # Moved before the mirror, the boss (above P, z 6..8) changes nothing of P's cut either,
        # but the mirror now reads it
        self.doc.openTransaction("move")
        PartDesign.studioMove(bsk, list(self.list.Entries).index(m))
        PartDesign.studioMove(boss, list(self.list.Entries).index(m))
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertLess(list(self.list.Entries).index(boss), list(self.list.Entries).index(m))
        self.assertValid(m)
        self.assertVolume("P", 4000 - math.pi * 16 * 5)

    # ------------------------------------------------------------------------------- TEST DOC
    def testTestDocShape(self):
        """The TEST DOC shape, designed: tool part T (x 5..15, y -3..1, z -2..6) mirrored about
        the vertical plane x = y (three datum points), Remove from plate P (x, y -20..20,
        z 0..4); then a Boolean Subtract of T itself from P, T still a live tool there."""
        p = boxPart(self.doc, self.studio, "P", -20, -20, 20, 20, 0, 4)
        t = boxPart(self.doc, self.studio, "T", 5, -3, 15, 1, -2, 8)
        plane = threePointPlane(t, "XeqY", (V(0, 0, 0), V(10, 10, 0), V(0, 0, 10)))
        self.listed()
        m = self.mirror("Mir", "T", (plane, [""]), "Remove", ("P",))
        self.assertValid(m, plane)
        self.assertVolume("P", 6400 - 40 * 4)
        # The copy is x -3..1, y 5..15
        self.assertPoint("P", V(-1, 10, 2), False)
        self.assertPoint("P", V(10, -1, 2), True)
        self.assertIn("T", self.live())
        self.assertVolume("T", 320)
        # The Boolean Subtract of T from P, after the mirror: T is its tool (consumed there)
        from PartDesignTests.TestBooleanScope import booleanOwner

        self.doc.openTransaction("boolean")
        b = booleanOwner(self.doc, self.studio, "Bool", "Cut", ("P",), ("T",))
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertValid(b, m)
        self.assertVolume("P", 6400 - 2 * 40 * 4)
        self.assertPoint("P", V(10, -1, 2), False)
        self.assertNotIn("T", self.live())
        self.assertIs(PartDesign.studioConsumerOf(t), b)

    # ------------------------------------------------------------------------------- Intersect
    def testIntersectOnOnePart(self):
        """P x -10..10 (10 x 10 high), S x 2..12 mirrored about the YZ plane to x -12..-2:
        Intersect leaves P x -10..-2 (800)."""
        p = boxPart(self.doc, self.studio, "P", -10, 0, 10, 10, 0, 10)
        s = boxPart(self.doc, self.studio, "Src", 2, 0, 12, 10, 0, 10)
        self.listed()
        m = self.mirror("Mir", "Src", (originPlane(s, "YZ_Plane"), [""]), "Intersect", ("P",))
        self.assertValid(m)
        self.assertEqual(PartDesign.studioStepOf(m, p).Operation, "Common")
        self.assertVolume("P", 800)
        self.assertCentre(self.shape("P"), (-6, 5, 5))
        self.assertVolume("Src", 1000)

    # ------------------------------------------------------------------------------- refusals
    def testNoSourceIsRefused(self):
        """A source id that resolves to nothing (gone): loud, P unchanged."""
        p, c = self.plateAndCylinder()
        m = self.mirror("Mir", "Gone", (originPlane(c, "YZ_Plane"), [""]), "Remove", ("P",))
        self.assertFalse(m.isValid())
        self.assertIn("part to mirror", m.getStatusString())
        self.assertVolume("P", 4000)

    def testTwoSourcesAreRefused(self):
        p, c = self.plateAndCylinder()
        m = self.mirror(
            "Mir", ["C", "P"], (originPlane(c, "YZ_Plane"), [""]), "Remove", ("P",)
        )
        self.assertFalse(m.isValid())
        self.assertIn("one part", m.getStatusString())
        self.assertVolume("P", 4000)

    def testNonPlanarPlaneIsRefused(self):
        """A cylindrical face as the plane: loud."""
        p, c = self.plateAndCylinder()
        cpad = self.doc.getObject("CPad")
        face = [
            f"Face{i}" for i, f in enumerate(cpad.Shape.Faces, 1)
            if f.Surface.__class__.__name__ == "Cylinder"
        ][0]
        m = self.mirror("Mir", "C", (cpad, [face]), "Remove", ("P",))
        self.assertFalse(m.isValid())
        self.assertIn("plane", m.getStatusString())
        self.assertVolume("P", 4000)

    def testPartLinearPatternIsRefused(self):
        """A part pattern other than the mirror is not done yet: loud."""
        p, c = self.plateAndCylinder()
        pat = self.doc.addObject("PartDesign::LinearPattern", "Pat")
        self.studio.addObject(pat)
        pat.PatternType = "Part"
        pat.StudioEntities = ["C"]
        pat.StudioScope = ["P"]
        self.doc.openTransaction("pattern")
        PartDesign.studioInsert(pat, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertFalse(pat.isValid())
        self.assertIn("not done yet", pat.getStatusString())
        self.assertVolume("P", 4000)


if __name__ == "__main__":
    unittest.main()
