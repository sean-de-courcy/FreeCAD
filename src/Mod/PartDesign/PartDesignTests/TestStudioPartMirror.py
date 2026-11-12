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
# copy touching no scope part would be a new part (made inside the step that records it; loud
# only where no step can hold it, 10.12). Remove, Intersect and
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

    def testAddCopyTouchingOnlyTheSourceMakesANewPart(self):
        """R4 and U2: Y touches its copy, X (x -30..-20) is apart: the copy touches no part of the
        merge scope, so inside the mirror's step it is a new part made by Mir (1000, centre
        x -5), Mir OK; Y is not consumed (the copy merged into no scope part), X unchanged.
        Undo takes the new part away with the mirror."""
        y, x = self.cubes(0, -30)
        before = sorted(b.Name for b in self.studio.Group if b.TypeId == "PartDesign::Body")
        m = self.mirror("Mir", "Y", (originPlane(y, "YZ_Plane"), [""]), "Add", ("X",))
        self.assertValid(m)
        [new] = self.made(m)
        self.assertValid(PartDesign.studioStepOf(m, new))
        self.assertAlmostEqual(new.Shape.Volume, 1000, places=3)
        self.assertCentre(new.Shape, (-5, 5, 5))
        self.assertVolume("X", 1000)
        self.assertVolume("Y", 1000)
        self.assertEqual(self.live(), sorted(["X", "Y", new.Name]))
        self.assertIsNone(PartDesign.studioConsumerOf(y))
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(
            sorted(b.Name for b in self.studio.Group if b.TypeId == "PartDesign::Body"), before
        )

    def testAddTouchingNoScopePartMakesANewPart(self):
        """S2 and U2: the mirrored copy (x 50..60) touches no part of the scope: inside the
        mirror's step it is a new part made by Mir (1000, centre (55, 10, 2.5)), Mir OK, Src
        unchanged."""
        s, d, plane = self.blockAndPlane()
        m = self.mirror("Mir", "Src", (plane, [""]), "Add", ("Src",))
        self.assertValid(m)
        [new] = self.made(m)
        self.assertAlmostEqual(new.Shape.Volume, 1000, places=3)
        self.assertCentre(new.Shape, (55, 10, 2.5))
        self.assertVolume("Src", 1000)
        self.assertIn(new.Name, self.live())

    def testAddTouchingNoScopePartWithNoStepRecordedStaysLoud(self):
        """The loud path: a script that records no step (no transaction) has no step to hold the
        new part, so the mirror fails with the command's hint and no part is made."""
        s, d, plane = self.blockAndPlane()
        m = partMirror(self.doc, self.studio, "Mir", "Src", (plane, [""]), "Add", ("Src",))
        self.doc.recompute()
        self.assertFalse(m.isValid())
        self.assertIn("touches no part of the merge scope", m.getStatusString())
        self.assertEqual(self.made(m), [])
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

    def testPartPatternOfAnotherTypeIsRefused(self):
        """A part pattern other than the mirror, Linear and Polar (T2: the curve pattern's place,
        a MultiTransform here) is not done yet: loud."""
        p, c = self.plateAndCylinder()
        pat = self.doc.addObject("PartDesign::MultiTransform", "Pat")
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


# ----------------------------------------------------------------------------------------------
# FreeCAD-CH ops#654 T2 (notes/parts-design.md 10.16 T2 and settled 9): the part pattern, Linear
# and Polar. A LinearPattern or PolarPattern in the studio, outside every Body, PatternType "Part":
# its sources' ids in StudioEntities, its Operation as the mirror's. Its copies are each source as it
# is just before the pattern, moved by every instance but the first. New (Operation Union, no
# scope): each copy a new part made by the pattern ("<pattern>:k", P6p), following the source.
# Add: the copies through 10.13's graph against the scope (a copy touching nothing a new part, one
# bridging two scope parts merges them); each source consumed when it touches the result (Onshape
# O5, Q3), kept when it touches neither copy nor result (Q10). Remove and Intersect consume the
# source (Q5: instance 1 is the source itself, a tool); Intersect is per scope part and per
# instance, unfused (Q6: pieces with new ids).

X_AXIS, Y_AXIS, Z_AXIS = range(3)


def partPattern(doc, studio, kind, name, sources, operation="New", scope=(), index=-1, **values):
    """A part pattern (PartDesign::<kind>, PatternType Part) of the part ids sources, listed at
    index; New has no scope (its parts are the ones it makes). No recompute."""
    owner = doc.addObject("PartDesign::" + kind, name)
    studio.addObject(owner)
    owner.PatternType = "Part"
    owner.StudioEntities = list(sources)
    for key, value in values.items():
        setattr(owner, key, value)
    owner.Refine = False
    owner.addProperty("App::PropertyEnumeration", "Operation", "Studio")
    owner.Operation = ["Union", "Subtraction", "Common"]
    owner.Operation = OPERATIONS[operation]
    owner.StudioScope = [] if operation == "New" else list(scope)
    PartDesign.studioInsert(owner, index)
    return owner


class TestStudioPartPattern(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestStudioPartMirrorT2")
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
    def box(self, name, x0, y0, x1, y1, z0, height):
        return boxPart(self.doc, self.studio, name, x0, y0, x1, y1, z0, height)

    def listed(self):
        self.doc.recompute()
        self.list = PartDesign.studioList(self.studio, True)
        return self.list

    def axis(self, index):
        return (self.studio.Origin.OriginFeatures[index], [""])

    def edit(self, label, change):
        """change() in one transaction, computed inside it (the command path: the resync makes
        the parts a step needs there)."""
        self.doc.openTransaction(label)
        result = change()
        self.doc.recompute()
        self.doc.commitTransaction()
        self.doc.recompute()
        return result

    def linear(self, name, sources, operation, scope=(), length=20, count=3, direction=X_AXIS):
        return self.edit(name, lambda: partPattern(
            self.doc, self.studio, "LinearPattern", name, sources, operation, scope,
            Direction=self.axis(direction), Mode="Extent", Length=length, Occurrences=count,
        ))

    def polar(self, name, sources, operation, scope=(), count=4):
        return self.edit(name, lambda: partPattern(
            self.doc, self.studio, "PolarPattern", name, sources, operation, scope,
            Axis=self.axis(Z_AXIS), Angle=360, Occurrences=count,
        ))

    def made(self, owner):
        return sorted(
            (b for b in self.doc.Objects
             if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner),
            key=lambda b: b.StudioPartId,
        )

    def live(self):
        return sorted(b.Name for b in PartDesign.studioLiveParts(self.list))

    def shape(self, part):
        body = self.doc.getObject(part) if isinstance(part, str) else part
        return body.Tip.Shape if body.Tip else Part.Shape()

    def assertVolume(self, part, expected, places=3):
        self.assertAlmostEqual(self.shape(part).Volume, expected, places=places, msg=str(part))

    def assertValid(self, *objects):
        for obj in objects:
            self.assertTrue(obj.isValid(), f"{obj.Name}: {obj.getStatusString()}")

    def assertCentres(self, bodies, expected):
        got = sorted(tuple(round(c, 4) for c in self.shape(b).CenterOfMass) for b in bodies)
        self.assertEqual(got, sorted(tuple(float(c) for c in e) for e in expected))

    def reopen(self):
        self.dir = self.dir or tempfile.mkdtemp(prefix="partpattern")
        path = os.path.join(self.dir, "pattern.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.doc.UndoMode = 1
        self.studio = self.doc.getObject("S")
        self.list = PartDesign.studioList(self.studio, False)
        self.doc.recompute()

    def names(self, *bodies):
        from PartDesignTests.TestStudioList import elementNames

        return {b.StudioPartId: elementNames(self.shape(b)) for b in bodies}

    # ------------------------------------------------------------------------------- New
    def cube(self):
        """Source S: a cube x 0..10, y 0..10, z 0..10 (1000)."""
        s = self.box("Src", 0, 0, 10, 10, 0, 10)
        self.listed()
        return s

    def testNewMakesAPartPerCopyFollowingTheSource(self):
        """Acceptance T2 (2): New +x 20 x 3: two new parts 'Pat:1', 'Pat:2' of 1000 at x 20..30
        and 40..50, the source kept; the source's pad 10 -> 5 high: both copies follow (500)."""
        s = self.cube()
        pat = self.linear("Pat", ["Src"], "New", length=40)
        self.assertValid(pat)
        made = self.made(pat)
        self.assertEqual([b.StudioPartId for b in made], ["Pat:1", "Pat:2"])
        self.assertCentres(made, [(25, 5, 5), (45, 5, 5)])
        for body in made:
            self.assertVolume(body, 1000)
        self.assertVolume("Src", 1000)
        self.assertEqual(self.live(), sorted(["Src"] + [b.Name for b in made]))
        self.assertIsNone(PartDesign.studioConsumerOf(s))
        self.doc.getObject("SrcPad").Length = 5
        self.doc.recompute()
        self.assertValid(pat)
        for body in made:
            self.assertVolume(body, 500)

    def testNewCountChangeAddsAndDeletesParts(self):
        """Acceptance T2 (2): count 3 -> 5 in an edit adds two parts; 5 -> 2 with the command's
        OK deletes the Bodies left empty."""
        self.cube()
        pat = self.linear("Pat", ["Src"], "New", length=40)
        self.assertEqual(len(self.made(pat)), 2)

        def more():
            pat.Occurrences = 5
            pat.Length = 80

        self.edit("count", more)
        self.assertValid(pat)
        self.assertEqual(len(self.made(pat)), 4)
        self.assertCentres(self.made(pat), [(25, 5, 5), (45, 5, 5), (65, 5, 5), (85, 5, 5)])

        def fewer():
            pat.Occurrences = 2
            pat.Length = 20
            PartDesign.studioMakePieces(pat)

        self.edit("count", fewer)
        self.assertValid(pat)
        self.assertEqual(len(self.made(pat)), 1)
        self.assertCentres(self.made(pat), [(25, 5, 5)])
        self.assertEqual(len(self.live()), 2)

    def testNewCopyGoneUnderALaterFeatureIsLoud(self):
        """10.16 (count edit): a copy gone whose Body holds a later feature (a boss on 'Pat:2')
        is not deleted: loud, never a part dropped in silence."""
        self.cube()
        pat = self.linear("Pat", ["Src"], "New", length=40)
        second = self.made(pat)[1]

        def boss():
            sk = sketch(second, "BossSk", xyPlane(second), (42, 2, 48, 8), z=10)
            b = pad(second, "Boss", sk, 2)
            for obj in (sk, b):
                if obj not in self.list.Entries:
                    PartDesign.studioInsert(obj, -1)
            return b

        b = self.edit("boss", boss)
        self.assertValid(b)
        self.assertVolume(second, 1072)

        def fewer():
            pat.Occurrences = 2
            pat.Length = 20
            PartDesign.studioMakePieces(pat)

        self.edit("count", fewer)
        self.assertIsNotNone(self.doc.getObject(second.Name))
        self.assertFalse(pat.isValid() and b.isValid(), "a copy gone under a feature: silent")

    def testNewCopiesOverlappingEachOtherStaySeparateParts(self):
        """Onshape Q4: cube x 0..10, +5 x 3: three separate parts, the source and two copies of
        1000 at x 5..15 and 10..20, in instance order."""
        self.cube()
        pat = self.linear("Pat", ["Src"], "New", length=10)
        self.assertValid(pat)
        made = self.made(pat)
        self.assertEqual(len(made), 2)
        self.assertCentres(made, [(10, 5, 5), (15, 5, 5)])
        self.assertVolume("Src", 1000)
        for body in made:
            self.assertVolume(body, 1000)

    def testPolarNewFourAboutZ(self):
        """Acceptance T2 (4): a cube x 10..20, y -5..5, z 0..10 patterned about the studio's Z,
        4 over 360: three new parts of 1000 centred at (0, 15), (-15, 0), (0, -15)."""
        self.box("Src", 10, -5, 20, 5, 0, 10)
        self.listed()
        pat = self.polar("Pat", ["Src"], "New")
        self.assertValid(pat)
        made = self.made(pat)
        self.assertEqual(len(made), 3)
        self.assertCentres(made, [(0, 15, 5), (-15, 0, 5), (0, -15, 5)])
        for body in made:
            self.assertVolume(body, 1000)

    def testNewUndoRedoAndSaveReopen(self):
        """Undo takes the pattern and its parts away, redo brings them back; saved and opened
        again, the same parts and element names."""
        self.cube()
        pat = self.linear("Pat", ["Src"], "New", length=40)
        self.assertEqual(len(self.made(pat)), 2)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("Pat"))
        self.assertFalse([b for b in self.doc.Objects if b.TypeId == "PartDesign::Body"
                          and b.StudioPartId.startswith("Pat:")])
        self.doc.redo()
        self.doc.recompute()
        pat = self.doc.getObject("Pat")
        self.assertValid(pat)
        before = self.names(*self.made(pat))
        self.assertEqual(sorted(before), ["Pat:1", "Pat:2"])
        self.reopen()
        pat = self.doc.getObject("Pat")
        self.assertValid(pat)
        self.assertEqual(self.names(*self.made(pat)), before)

    def testSuppressAndDelete(self):
        """Acceptance T2 (8): suppressed, the copies are no parts; back on, they are; deleted,
        their Bodies go with it in one step (undo brings them back)."""
        self.cube()
        pat = self.linear("Pat", ["Src"], "New", length=40)
        made = [b.Name for b in self.made(pat)]
        self.assertEqual(len(made), 2)
        self.edit("suppress", lambda: PartDesign.studioSuppress(pat, True))
        self.assertEqual(self.live(), ["Src"])
        self.edit("unsuppress", lambda: PartDesign.studioSuppress(pat, False))
        self.assertEqual(self.live(), sorted(["Src"] + made))

        def delete():
            PartDesign.studioRemove(pat)
            self.doc.removeObject("Pat")

        self.edit("delete", delete)
        self.assertEqual(self.live(), ["Src"])
        for name in made:
            self.assertIsNone(self.doc.getObject(name))
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.live(), sorted(["Src"] + made))

    # ------------------------------------------------------------------------------- Add
    def o5(self):
        """Onshape O5: plate P x 0..30, y 0..20, z 0..5 (3000); source S 10 x 10 x 5 at x 0..10,
        y 5..15 on P's top (500), a part of its own."""
        p = self.box("P", 0, 0, 30, 20, 0, 5)
        s = self.box("Src", 0, 5, 10, 15, 5, 5)
        self.listed()
        return p, s

    def testO5AddConsumesTheSourceAndMakesTheLoneCopyAPart(self):
        """Acceptance T2 (1), O5: +x 20 x 3, Add, scope P: P 4000 with its id (S and instance 2
        merged in), S consumed, instance 3 (x 40..50, touching nothing) a new part of 500."""
        p, s = self.o5()
        pat = self.linear("Pat", ["Src"], "Add", ("P",), length=40)
        self.assertValid(pat, PartDesign.studioStepOf(pat, p))
        self.assertVolume("P", 4000)
        self.assertEqual(len(self.shape("P").Solids), 1)
        self.assertEqual(p.StudioPartId, "P")
        self.assertIs(PartDesign.studioConsumerOf(s), pat)
        [new] = self.made(pat)
        self.assertEqual(new.StudioPartId, "Pat:1")
        self.assertVolume(new, 500)
        self.assertCentres([new], [(45, 10, 7.5)])
        self.assertEqual(self.live(), sorted(["P", new.Name]))

    def testO5UndoRedoAndSaveReopen(self):
        """Undo: S and P as they were, no new part; redo: as made; saved and opened again: the
        first recompute agrees (S consumed, P 4000), the same element names."""
        p, s = self.o5()
        pat = self.linear("Pat", ["Src"], "Add", ("P",), length=40)
        self.assertVolume("P", 4000)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.live(), ["P", "Src"])
        self.assertVolume("P", 3000)
        self.doc.redo()
        self.doc.recompute()
        pat = self.doc.getObject("Pat")
        self.assertValid(pat)
        self.assertVolume("P", 4000)
        [new] = self.made(pat)
        self.assertEqual(self.live(), sorted(["P", new.Name]))
        before = self.names(self.doc.getObject("P"), new)
        self.reopen()
        pat = self.doc.getObject("Pat")
        self.assertValid(pat)
        self.assertVolume("P", 4000)
        self.assertIs(PartDesign.studioConsumerOf(self.doc.getObject("Src")), pat)
        [new] = self.made(pat)
        self.assertEqual(self.live(), sorted(["P", new.Name]))
        self.assertEqual(self.names(self.doc.getObject("P"), new), before)

    def testQ3AddOfTwoSourcesConsumesBoth(self):
        """Onshape Q3: P x 0..60 (12000); S1 x 0..10 and S2 x 20..30, y 0..10, z 10..20 on P's
        top; +5 x 2, Add, scope P: one part, P 15000, both sources consumed."""
        p = self.box("P", 0, 0, 60, 20, 0, 10)
        s1 = self.box("S1", 0, 0, 10, 10, 10, 10)
        s2 = self.box("S2", 20, 0, 30, 10, 10, 10)
        self.listed()
        pat = self.linear("Pat", ["S1", "S2"], "Add", ("P",), length=5, count=2)
        self.assertValid(pat)
        self.assertVolume("P", 15000)
        self.assertEqual(len(self.shape("P").Solids), 1)
        self.assertIs(PartDesign.studioConsumerOf(s1), pat)
        self.assertIs(PartDesign.studioConsumerOf(s2), pat)
        self.assertEqual(self.live(), ["P"])
        self.assertFalse(self.made(pat))

    def testQ10SourceTouchingNeitherCopyNorResultIsKept(self):
        """Onshape Q10 (designed the other way along x): P x 0..20 (4000); S x -25..-20,
        y 0..5, z 0..15 (375); +40 x 2, Add, scope P: the copy (x 15..20) sticks out of P's top:
        P 4125, S kept as its own part."""
        p = self.box("P", 0, 0, 20, 20, 0, 10)
        s = self.box("Src", -25, 0, -20, 5, 0, 15)
        self.listed()
        pat = self.linear("Pat", ["Src"], "Add", ("P",), length=40, count=2)
        self.assertValid(pat)
        self.assertVolume("P", 4125)
        self.assertVolume("Src", 375)
        self.assertIsNone(PartDesign.studioConsumerOf(s))
        self.assertEqual(self.live(), ["P", "Src"])

    def testAddCopyBridgingTwoScopePartsMergesThem(self):
        """Acceptance T2 (6): A x 0..10 and B x 20..30, y 0..10, z 0..10 (1000 each); S x
        -35..-15, y 0..10, z 10..15 (1000), apart from both; +40 x 2, Add, scope A, B: the copy
        (x 5..25) lies on both tops and merges B into A (3000, A's id); S kept (Q10)."""
        a = self.box("A", 0, 0, 10, 10, 0, 10)
        b = self.box("B", 20, 0, 30, 10, 0, 10)
        s = self.box("Src", -35, 0, -15, 10, 10, 5)
        self.listed()
        pat = self.linear("Pat", ["Src"], "Add", ("A", "B"), length=40, count=2)
        self.assertValid(pat)
        self.assertVolume("A", 3000)
        self.assertEqual(len(self.shape("A").Solids), 1)
        self.assertIs(PartDesign.studioConsumerOf(b), pat)
        self.assertIsNone(PartDesign.studioConsumerOf(s))
        self.assertEqual(self.live(), ["A", "Src"])

    # ------------------------------------------------------------------------------- Remove
    def q5(self):
        """Onshape Q5: P 60 x 20 x 10 (12000); pin S 5 x 5 at x 5..10, y 5..10, z 0..20."""
        p = self.box("P", 0, 0, 60, 20, 0, 10)
        s = self.box("Src", 5, 5, 10, 10, 0, 20)
        self.listed()
        return p, s

    def testQ5RemoveConsumesTheSourceAndCutsEveryInstance(self):
        """Acceptance T2 (3) with Q5: +15 x 3, Remove, scope P: P 11250 (three holes, the one at
        the source's own place included), S consumed."""
        p, s = self.q5()
        pat = self.linear("Pat", ["Src"], "Remove", ("P",), length=30)
        self.assertValid(pat, PartDesign.studioStepOf(pat, p))
        self.assertVolume("P", 11250)
        for x in (7.5, 22.5, 37.5):
            self.assertFalse(self.shape("P").isInside(V(x, 7.5, 5), 1e-6, True), x)
        self.assertTrue(self.shape("P").isInside(V(15, 7.5, 5), 1e-6, True))
        self.assertIs(PartDesign.studioConsumerOf(s), pat)
        self.assertEqual(self.live(), ["P"])

    def testQ5IntersectMakesAPartPerInstance(self):
        """Acceptance T2 (5) with Q5: Intersect, scope P: P is replaced by three new parts of
        250 (the overlaps, the one at the source's place included), S consumed."""
        p, s = self.q5()
        pat = self.linear("Pat", ["Src"], "Intersect", ("P",), length=30)
        self.assertValid(pat)
        made = self.made(pat)
        self.assertEqual(len(made), 3)
        for body in made:
            self.assertVolume(body, 250)
        self.assertCentres(made, [(7.5, 7.5, 5), (22.5, 7.5, 5), (37.5, 7.5, 5)])
        self.assertIs(PartDesign.studioConsumerOf(s), pat)
        self.assertEqual(self.live(), sorted(b.Name for b in made))

    def q6(self):
        """Onshape Q6: A x 0..20, B x 30..50 (y 0..20, z 0..10); bar S x -5..55, y 2..7,
        z 2..7; +y 6 x 2, Intersect, scope A, B."""
        self.box("A", 0, 0, 20, 20, 0, 10)
        self.box("B", 30, 0, 50, 20, 0, 10)
        s = self.box("Src", -5, 2, 55, 7, 2, 5)
        self.listed()
        pat = self.linear("Pat", ["Src"], "Intersect", ("A", "B"), length=6, count=2,
                          direction=Y_AXIS)
        return s, pat

    def testQ6IntersectWithTwoScopePartsIsPerPartAndPerInstance(self):
        """Onshape Q6: four parts of 500 (A and B each with S and with its copy), not fused, new
        ids; S consumed, A and B no parts."""
        s, pat = self.q6()
        self.assertValid(pat)
        made = self.made(pat)
        self.assertEqual(len(made), 4)
        for body in made:
            self.assertVolume(body, 500)
        self.assertCentres(
            made, [(10, 4.5, 4.5), (10, 10.5, 4.5), (40, 4.5, 4.5), (40, 10.5, 4.5)]
        )
        self.assertIs(PartDesign.studioConsumerOf(s), pat)
        self.assertEqual(self.live(), sorted(b.Name for b in made))

    def testQ6UndoRedoAndSaveReopen(self):
        """Undo: A, B and S back; redo: the four pieces; saved and opened again, the same
        pieces and element names."""
        s, pat = self.q6()
        self.assertEqual(len(self.made(pat)), 4)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.live(), ["A", "B", "Src"])
        self.assertVolume("A", 4000)
        self.doc.redo()
        self.doc.recompute()
        pat = self.doc.getObject("Pat")
        self.assertValid(pat)
        made = self.made(pat)
        self.assertEqual(self.live(), sorted(b.Name for b in made))
        before = self.names(*made)
        self.reopen()
        pat = self.doc.getObject("Pat")
        self.assertValid(pat)
        self.assertEqual(self.names(*self.made(pat)), before)
        self.assertEqual(len(self.live()), 4)

    def testASourceNoLongerSplitAtThePatternGivesItsCopyAPartInTheEdit(self):
        """ops#654 T2 gate (seed 1, op 14, a move): P x 0..30, y 0..20, z 0..5; source S x
        40..60, y 0..10, z 0..10 (2000) split by a slot at x 49..50 before the pattern (S:1, S:2);
        +x 40 x 2, Add, scope P: the copies touch nothing, two parts (900, 1000). The slot moved
        after the pattern in an edit: S is whole at the pattern's place, its one copy (2000) is
        held in the move's step (10.12 amendment), and a later recompute outside any step makes no
        part. (The gate's case, a Polar Add of a split source's pieces, stays loud there.)"""
        from PartDesignTests.TestStudioList import makeOwner

        self.box("P", 0, 0, 30, 20, 0, 5)
        self.box("Src", 40, 0, 60, 10, 0, 10)
        self.listed()

        def slot():
            owner = makeOwner(self.doc, self.studio, "Slot", [49, -1, 50, 11], 11,
                              "Subtraction", ["Src"])
            PartDesign.studioInsert(owner, -1)
            PartDesign.studioMakePieces(owner)
            return owner

        owner = self.edit("slot", slot)
        pat = self.linear("Pat", ["Src"], "Add", ("P",), length=40, count=2)
        self.assertValid(pat)
        self.assertEqual(sorted(round(self.shape(b).Volume) for b in self.made(pat)), [900, 1000])
        self.edit("move", lambda: PartDesign.studioMove(owner, len(self.list.Entries) - 1))
        held = [b for b in self.made(pat) if b.Tip and b.Tip.isValid()]
        self.assertEqual([round(self.shape(b).Volume) for b in held], [2000])
        bodies = len([b for b in self.doc.Objects if b.TypeId == "PartDesign::Body"])
        self.doc.recompute()
        self.assertEqual(
            len([b for b in self.doc.Objects if b.TypeId == "PartDesign::Body"]), bodies
        )

    def testARecomputeAfterAnAbortLeavesAPartPatternsPartsAsTheyWere(self):
        """ops#654 T2 gate (seed 1, op 14; R1, c750): P x 0..30, y 0..20, z 0..5; S x 40..60,
        y 0..10, z 0..10 split by a slot at x 49..50 (S:1, S:2); a Polar Add of S over P, 2
        copies about the studio's z: the copies touch nothing, two parts. The slot moved after
        the pattern by the drag's command (the move, then the slot's piece command): S is whole at
        the pattern's place, the old records hold nothing, and the pattern stays loud (as built).
        Then a recompute with no step recorded, and a transaction that deletes and remakes the
        pattern's steps, aborted and recomputed: the parts list and every Body's chain stay as
        they were (no part made outside a step, no Body emptied)."""
        from PartDesignTests.TestStudioList import makeOwner

        self.box("P", 0, 0, 30, 20, 0, 5)
        self.box("Src", 40, 0, 60, 10, 0, 10)
        self.listed()

        def slot():
            owner = makeOwner(self.doc, self.studio, "Slot", [49, -1, 50, 11], 11,
                              "Subtraction", ["Src"])
            PartDesign.studioInsert(owner, -1)
            PartDesign.studioMakePieces(owner)
            return owner

        owner = self.edit("slot", slot)
        pat = self.polar("Pat", ["Src"], "Add", ("P",), count=2)
        self.assertValid(pat)
        self.assertEqual(len(self.made(pat)), 2)

        def move():
            PartDesign.studioMove(owner, len(self.list.Entries) - 1)
            PartDesign.studioMakePieces(owner)

        self.edit("move", move)

        def state():
            return sorted(
                (b.Name, b.StudioPartId, tuple(m.Name for m in b.Group))
                for b in self.doc.Objects if b.TypeId == "PartDesign::Body"
            )

        before = state()
        undo = self.doc.UndoNames
        pat.touch()
        self.doc.recompute()
        self.assertEqual(state(), before, "a recompute with no step recorded")
        self.doc.openTransaction("regenerate")
        try:
            for body in self.made(pat):
                for step in [o for o in body.Group if o.TypeId == "PartDesign::FeatureApply"]:
                    body.removeObject(step)
                    self.doc.removeObject(step.Name)
            PartDesign.studioReconcile(self.list)
            self.doc.recompute()
        finally:
            self.doc.abortTransaction()
        self.doc.recompute()
        self.assertEqual(state(), before, "a recompute after an abort")
        self.assertEqual(self.doc.UndoNames, undo)

    def testAPatternWithNoSourceLeftFailsInEveryRecordEvenOneMergedBack(self):
        """ops#654 T2 gate (seed 2, op 33): P x 60..90, y 0..20, z 0..5; S x 40..50, y 0..10,
        z 0..10. An Add of S over P, +x 60 x 2: the copy (x 100..110) touches nothing, a part.
        The spacing made 40: the copy (x 80..90) merges into P, its part's record dormant (10.12
        amendment point 5). Then a Remove pattern of S before it consumes S (Q5): the Add has no
        source, loud, and its record fails in its Body, a live part (as a build from scratch has
        it), never an empty Body left from the earlier merge."""
        self.box("P", 60, 0, 90, 20, 0, 5)
        self.box("Src", 40, 0, 50, 10, 0, 10)
        self.listed()
        pat = self.linear("Pat", ["Src"], "Add", ("P",), length=60, count=2)
        self.assertValid(pat)
        self.assertEqual(len(self.made(pat)), 1)
        self.edit("spacing", lambda: setattr(pat, "Length", 40))
        self.assertValid(pat)
        self.assertEqual(list(pat.StudioLeftoverLost), [self.made(pat)[0].StudioPartId])
        self.edit("remove", lambda: partPattern(
            self.doc, self.studio, "LinearPattern", "Rem", ["Src"], "Remove", ("P",),
            index=list(self.list.Entries).index(pat),
            Direction=self.axis(X_AXIS), Mode="Extent", Length=100, Occurrences=2,
        ))
        self.assertFalse(pat.isValid())
        self.assertIn("No part to pattern", pat.getStatusString())
        record = self.made(pat)[0]
        self.assertEqual([m.StudioOwner.Name for m in record.Group], ["Pat"])
        self.assertIn(record.Name, self.live())

    def splitUnderACopy(self):
        """P x 0..30, y 0..20, z 0..5; S x 40..60, y 0..10, z 0..10 (2000); an Add of S over P,
        +x 40 x 2: the copy (x 80..100) touches nothing, a part (its record's witness: the copy's
        faces). Then a slot at x 49..50 through S, inserted before the pattern in an edit: S is two
        solids there, so the copy is two (900, 1000), and the record's witness lies on both
        halves alike (an end face each): which one it is can't be told."""
        from PartDesignTests.TestStudioList import makeOwner

        self.box("P", 0, 0, 30, 20, 0, 5)
        self.box("Src", 40, 0, 60, 10, 0, 10)
        self.listed()
        pat = self.linear("Pat", ["Src"], "Add", ("P",), length=40, count=2)
        self.assertValid(pat)
        self.assertEqual(len(self.made(pat)), 1)

        def slot():
            owner = makeOwner(self.doc, self.studio, "Slot", [49, -1, 50, 11], 11,
                              "Subtraction", ["Src"])
            PartDesign.studioInsert(owner, list(self.list.Entries).index(pat))
            return owner

        self.edit("slot", slot)
        return pat

    def testOneRecomputeMakesNoMorePartsThanItsEntriesAccountFor(self):
        """ops#654 T2 gate (seed 2, op 47, a runaway): splitUnderACopy. Whatever the record
        decides, one recompute makes at most the two halves' parts beside the record: the
        resync's fixed point never makes an entry's parts twice in one recompute (it stops, loud,
        naming the entry), so a document can't grow Bodies without end."""
        pat = self.splitUnderACopy()
        self.assertLessEqual(len(self.made(pat)), 3)
        count = len(self.made(pat))
        self.doc.recompute()
        self.assertLessEqual(len(self.made(pat)), count + 2)

    def testARecordThatCantBeToldMakesNoFurtherParts(self):
        """ops#654 T2 gate (seed 2, op 47): splitUnderACopy. The record that can't be told holds
        nothing and stays a record (dormant, as a leftover merged back); each half is a new part,
        as a build of the same list from scratch gives two parts; a recompute after it makes
        nothing more."""
        pat = self.splitUnderACopy()
        made = self.made(pat)
        self.assertEqual(len(made), 3, [b.StudioPartId for b in made])
        held = sorted(round(self.shape(b).Volume) for b in made if b.Tip and b.Tip.isValid())
        self.assertEqual(held, [900, 1000])
        self.assertValid(pat)
        bodies = len([b for b in self.doc.Objects if b.TypeId == "PartDesign::Body"])
        self.doc.recompute()
        self.assertEqual(
            len([b for b in self.doc.Objects if b.TypeId == "PartDesign::Body"]), bodies
        )
        self.assertEqual(len(self.made(pat)), 3)


if __name__ == "__main__":
    unittest.main()
