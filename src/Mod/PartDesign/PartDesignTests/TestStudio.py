# SPDX-License-Identifier: LGPL-2.1-or-later

"""B+ Stage 1, session 1a (ops#325): direct references between the Bodies of a studio.

A studio is the App::Part that holds Bodies (not an Assembly), or the document's top level. Its
Bodies share one origin, so a pick may link another part directly, with no binder or copy. The
Gui gates call the predicates tested here (PartDesign.isStudioPick, isStudioProfile,
studioOriginFeature; Sketcher's isExternalAllowed). Every model is designed: the expected shapes
come from volumes, bounding boxes and point membership.
"""

import os
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign
import Sketcher

V = App.Vector


def rect(sketch, x0, y0, x1, y1):
    points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    first = len(sketch.Geometry)
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(points[i], points[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1)
        )


def xyPlane(body):
    return [(body.Origin.OriginFeatures[3], "")]


def sketch(body, name, support, *rects, z=None):
    s = body.newObject("Sketcher::SketchObject", name)
    s.AttachmentSupport = support
    s.MapMode = "FlatFace"
    if z is not None:
        s.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
    for r in rects:
        rect(s, *r)
    return s


def pad(body, name, profile, length):
    p = body.newObject("PartDesign::Pad", name)
    p.Profile = profile
    p.Length = length
    return p


def faceAt(feature, z, nz=1):
    """The planar face of feature's shape at height z facing nz."""
    for i, face in enumerate(feature.Shape.Faces, 1):
        if (
            face.Surface.__class__.__name__ == "Plane"
            and abs(face.normalAt(0, 0).z - nz) < 1e-9
            and abs(face.CenterOfMass.z - z) < 1e-6
        ):
            return f"Face{i}"
    return None


def edgeAt(feature, start, end):
    """The edge of feature's shape between the points start and end."""
    for i, edge in enumerate(feature.Shape.Edges, 1):
        ends = {tuple(round(c, 6) for c in v.Point) for v in edge.Vertexes}
        if ends == {tuple(start), tuple(end)}:
            return f"Edge{i}"
    return None


def inside(shape, point):
    return shape.isInside(point, 1e-6, True)


def outOfScope(doc, objects):
    """Whether recomputing objects warns "links are out of scope" (DocumentObject::recompute).
    The warning goes through the console's std observer to stderr: fd 2 is caught meanwhile."""
    observers = App.Console.GetObservers()
    if "Console" not in observers:
        raise unittest.SkipTest("no console observer to catch the warning")
    status = App.Console.GetStatus("Console", "Wrn")
    App.Console.SetStatus("Console", "Wrn", True)
    saved = os.dup(2)
    with tempfile.TemporaryFile() as caught:
        os.dup2(caught.fileno(), 2)
        try:
            for obj in objects:
                obj.touch()
            doc.recompute()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            App.Console.SetStatus("Console", "Wrn", bool(status))
        caught.seek(0)
        return b"links are out of scope" in caught.read()


class TestStudio(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestStudio")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assertSettled(self):
        self.doc.recompute()
        bad = [o.Name for o in self.doc.Objects if not o.isValid()]
        self.assertEqual(bad, [])
        self.assertEqual(self.doc.recompute(), 0)

    def twoBodies(self, container=None):
        """Lower (40x40x10 at z 0) and Upper (40x40x5 at z 10), in container or at top level."""
        lower = self.doc.addObject("PartDesign::Body", "Lower")
        upper = self.doc.addObject("PartDesign::Body", "Upper")
        if container:
            container.addObject(lower)
            container.addObject(upper)
        padL = pad(lower, "LowerPad", sketch(lower, "LowSk", xyPlane(lower), (0, 0, 40, 40)), 10)
        padU = pad(
            upper, "UpperPad", sketch(upper, "UpSk", xyPlane(upper), (0, 0, 40, 40), z=10), 5
        )
        self.doc.recompute()
        return lower, upper, padL, padU

    # ---------------------------------------------------------------- the studio and its rule

    def testStudioOfABody(self):
        part = self.doc.addObject("App::Part", "Part")
        inPart = self.doc.addObject("PartDesign::Body", "InPart")
        part.addObject(inPart)
        top = self.doc.addObject("PartDesign::Body", "Top")
        self.doc.recompute()
        self.assertEqual(PartDesign.studioOf(inPart), part)
        self.assertEqual(PartDesign.studioOf(inPart.Origin.OriginFeatures[3]), part)
        self.assertEqual(PartDesign.studioOf(top), self.doc)
        free = self.doc.addObject("Part::Box", "Free")
        self.assertIsNone(PartDesign.studioOf(free))

    def testPicksInOneStudio(self):
        """Same App::Part and both at the top level: allowed; across App::Parts: refused."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        top = self.doc.addObject("PartDesign::Body", "Top")
        padT = pad(top, "TopPad", sketch(top, "TopSk", xyPlane(top), (50, 0, 60, 10)), 3)
        top2 = self.doc.addObject("PartDesign::Body", "Top2")
        padT2 = pad(top2, "Top2Pad", sketch(top2, "Top2Sk", xyPlane(top2), (70, 0, 80, 10)), 3)
        self.doc.recompute()
        self.assertTrue(PartDesign.isStudioPick(padU, padL, "Face1"))
        self.assertTrue(PartDesign.isStudioPick(padU, padU, "Face1"))
        self.assertTrue(PartDesign.isStudioPick(padT, padT2, "Face1"))
        self.assertFalse(PartDesign.isStudioPick(padT, padL, "Face1"))
        self.assertFalse(PartDesign.isStudioPick(padU, padT, "Face1"))
        # the pick's path from the container
        self.assertTrue(PartDesign.isStudioPick(padU, part, "Lower.LowerPad.Face1"))
        # an object in no Body
        free = self.doc.addObject("Part::Box", "Free")
        self.assertFalse(PartDesign.isStudioPick(padT, free, "Face1"))

    def testOriginOfAnotherPartIsRelinked(self):
        """Another part's origin is the same plane under one origin: the owner's own is used."""
        lower, upper, padL, padU = self.twoBodies()
        for role in range(6):
            theirs = lower.Origin.OriginFeatures[role]
            ours = upper.Origin.OriginFeatures[role]
            self.assertEqual(PartDesign.studioOriginFeature(padU, theirs), ours)
        self.assertIsNone(PartDesign.studioOriginFeature(padU, upper.Origin.OriginFeatures[3]))
        part = self.doc.addObject("App::Part", "Part")
        part.addObject(lower)
        self.doc.recompute()
        self.assertIsNone(PartDesign.studioOriginFeature(padU, lower.Origin.OriginFeatures[3]))

    # ---------------------------------------------------------------- D-t6: Assembly and Link

    def testAssemblyIsNoStudio(self):
        """D-t6: Bodies placed directly in an Assembly may not link each other directly."""
        try:
            import AssemblyApp  # noqa: F401  (registers Assembly::AssemblyObject)

            assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        except Exception:
            self.skipTest("the Assembly module isn't available")
        lower, upper, padL, padU = self.twoBodies(assembly)
        self.assertIsNone(PartDesign.studioOf(lower))
        self.assertFalse(PartDesign.isStudioPick(padU, padL, "Face1"))
        self.assertFalse(PartDesign.isStudioProfile(padU, lower.getObject("LowSk")))
        self.assertIsNone(PartDesign.studioOriginFeature(padU, lower.Origin.OriginFeatures[3]))
        # the same Body still links itself
        self.assertTrue(PartDesign.isStudioPick(padL, padL, "Face1"))
        # an App::Part in the Assembly is a studio of its own
        part = self.doc.addObject("App::Part", "Part")
        assembly.addObject(part)
        part.addObject(lower)
        part.addObject(upper)
        self.doc.recompute()
        self.assertEqual(PartDesign.studioOf(lower), part)
        self.assertTrue(PartDesign.isStudioPick(padU, padL, "Face1"))

    def testPickThroughALinkIsRefused(self):
        """D-t6: a pick through an App::Link would ignore the Link's placement."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        link = self.doc.addObject("App::Link", "Link")
        link.LinkedObject = lower
        link.Placement = App.Placement(V(100, 0, 0), App.Rotation())
        part.addObject(link)
        self.doc.recompute()
        self.assertTrue(PartDesign.isStudioPick(padU, part, "Lower.LowerPad.Face1"))
        self.assertFalse(PartDesign.isStudioPick(padU, part, "Link.LowerPad.Face1"))
        self.assertFalse(PartDesign.isStudioPick(padU, link, "LowerPad.Face1"))
        self.assertFalse(PartDesign.isStudioPick(padU, link, ""))
        self.assertFalse(PartDesign.isStudioProfile(padU, link, "LowerPad.Face1"))

    # ---------------------------------------------------------------- D-t1: the opened gates

    def testThroughHoleAcrossParts(self):
        """D-t1, Stage 0b's case B: one sketch cuts a hole through two parts of an App::Part,
        and a blind cut in Upper goes down to Lower's top face."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        holeSk = sketch(upper, "HoleSk", [(padU, faceAt(padU, 15))], (18, 18, 22, 22))
        holeU = upper.newObject("PartDesign::Pocket", "HoleUpper")
        holeU.Profile = holeSk
        holeU.Type = "ThroughAll"
        self.assertTrue(PartDesign.isStudioProfile(lower, holeSk))
        holeL = lower.newObject("PartDesign::Pocket", "HoleLower")
        holeL.Profile = holeSk
        holeL.Type = "ThroughAll"
        blindSk = sketch(upper, "BlindSk", [(padU, faceAt(padU, 15))], (30, 30, 34, 34))
        blind = upper.newObject("PartDesign::Pocket", "UpperToLower")
        blind.Profile = blindSk
        blind.Type = "UpToFace"
        top = faceAt(padL, 10)
        self.assertTrue(PartDesign.isStudioPick(blind, padL, top))
        blind.UpToFace = (padL, [top])
        self.assertSettled()

        def check(cx, cy):
            self.assertAlmostEqual(upper.Shape.Volume, 8000 - 80 - 80, places=3)
            self.assertAlmostEqual(lower.Shape.Volume, 16000 - 160, places=3)
            for z in (1, 5, 9):
                self.assertFalse(inside(lower.Shape, V(cx, cy, z)))
            for z in (11, 14):
                self.assertFalse(inside(upper.Shape, V(cx, cy, z)))
            self.assertFalse(inside(upper.Shape, V(32, 32, 10.5)))
            self.assertTrue(inside(lower.Shape, V(32, 32, 9.5)))

        check(20, 20)
        holeSk.AttachmentOffset = App.Placement(V(-8, -8, 0), App.Rotation())
        self.assertSettled()
        check(12, 12)

    def testInterleavedReferences(self):
        """D-t1, Stage 0b's case C at the top level: references both ways between two parts,
        a box attached to the other part's face, and a pocket whose Profile is its face."""
        body1 = self.doc.addObject("PartDesign::Body", "Body1")
        padA = pad(body1, "PadA", sketch(body1, "SkA", xyPlane(body1), (0, 0, 20, 10)), 5)
        self.doc.recompute()
        body2 = self.doc.addObject("PartDesign::Body", "Body2")
        padB = body2.newObject("PartDesign::AdditiveBox", "PadB")
        padB.Length = padB.Width = 6
        padB.Height = 3
        padB.AttachmentSupport = [(padA, faceAt(padA, 5))]
        padB.MapMode = "FlatFace"
        padB.AttachmentOffset = App.Placement(V(2, 2, 0), App.Rotation())
        self.doc.recompute()
        bottom = faceAt(padB, 5, nz=-1)
        self.assertTrue(PartDesign.isStudioProfile(body1, padB, bottom))
        pocket1 = body1.newObject("PartDesign::Pocket", "Pocket1")
        pocket1.Profile = (padB, [bottom])
        pocket1.Type = "ThroughAll"
        pocket1.SideType = "Symmetric"
        skC2 = sketch(body1, "SkC2", [(padB, faceAt(padB, 8))], (4, 0, 10, 4))
        pocket2 = body1.newObject("PartDesign::Pocket", "Pocket2")
        pocket2.Profile = skC2
        pocket2.Type = "ThroughAll"
        pocket2.SideType = "Symmetric"
        self.assertTrue(PartDesign.isStudioProfile(padB, skC2))
        pocketB = body2.newObject("PartDesign::Pocket", "PocketB")
        pocketB.Profile = skC2
        pocketB.Type = "ThroughAll"
        pocketB.SideType = "Symmetric"
        self.assertSettled()
        self.assertEqual([o.Name for o in self.doc.Objects if o in o.OutListRecursive], [])

        def check(h):
            self.assertAlmostEqual(body1.Shape.Volume, (200 - 36 - 16) * h, places=3)
            self.assertAlmostEqual(body2.Shape.Volume, 108 - 24, places=3)
            self.assertAlmostEqual(body2.Shape.BoundBox.ZMin, h, places=6)

        check(5)
        padA.Length = 7
        self.assertSettled()
        check(7)

    def testEnclosureAndLid(self):
        """D-t1, Stage 0b's case D-xy: an enclosure with four screw bosses and a lid in one
        App::Part. The lid's notch sketch sits on the enclosure's XY plane, and its clearance
        holes use the enclosure's screw sketch as Profile. Compared with shapes built directly."""
        W, D, H, wall, lidT, lip, clr = 120, 80, 60, 3, 4, 5, 0.5
        bossR, screwR, inset, depth = 5, 1.75, 8, 15
        bosses = [(x, y) for x in (inset, W - inset) for y in (inset, D - inset)]
        part = self.doc.addObject("App::Part", "Part")
        enc = self.doc.addObject("PartDesign::Body", "Enclosure")
        lid = self.doc.addObject("PartDesign::Body", "Lid")
        part.addObject(enc)
        part.addObject(lid)

        def circles(s, r):
            for x, y in bosses:
                s.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), r))

        outer = enc.newObject("PartDesign::AdditiveBox", "Outer")
        outer.Length, outer.Width, outer.Height = W, D, H
        cavity = enc.newObject("PartDesign::SubtractiveBox", "Cavity")
        cavity.Length, cavity.Width, cavity.Height = W - 2 * wall, D - 2 * wall, H
        cavity.Placement = App.Placement(V(wall, wall, wall), App.Rotation())
        bossSk = sketch(enc, "BossSk", xyPlane(enc))
        circles(bossSk, bossR)
        pad(enc, "Bosses", bossSk, H)
        screwSk = sketch(enc, "ScrewSk", xyPlane(enc), z=H)
        circles(screwSk, screwR)
        holes = enc.newObject("PartDesign::Pocket", "ScrewHoles")
        holes.Profile = screwSk
        holes.Length = depth
        plate = lid.newObject("PartDesign::AdditiveBox", "Plate")
        plate.Length, plate.Width, plate.Height = W, D, lidT
        plate.AttachmentSupport = xyPlane(enc)
        plate.MapMode = "FlatFace"
        plate.AttachmentOffset = App.Placement(V(0, 0, H), App.Rotation())
        lipBox = lid.newObject("PartDesign::AdditiveBox", "Lip")
        c = wall + clr
        lipBox.Length, lipBox.Width, lipBox.Height = W - 2 * c, D - 2 * c, lip
        lipBox.Placement = App.Placement(V(c, c, H - lip), App.Rotation())
        notchSk = lid.newObject("Sketcher::SketchObject", "NotchSk")
        self.assertTrue(PartDesign.isStudioPick(notchSk, enc.Origin.OriginFeatures[3], ""))
        notchSk.AttachmentSupport = xyPlane(enc)
        notchSk.MapMode = "FlatFace"
        notchSk.AttachmentOffset = App.Placement(V(0, 0, H), App.Rotation())
        circles(notchSk, bossR + clr)
        notch = lid.newObject("PartDesign::Pocket", "Notch")
        notch.Profile = notchSk
        notch.Length = lip
        self.assertTrue(PartDesign.isStudioProfile(notch, screwSk))
        clearance = lid.newObject("PartDesign::Pocket", "Clearance")
        clearance.Profile = screwSk
        clearance.Type = "ThroughAll"
        clearance.SideType = "Symmetric"
        self.assertSettled()

        E = Part.makeBox(W, D, H).cut(
            Part.makeBox(W - 2 * wall, D - 2 * wall, H, V(wall, wall, wall))
        )
        for x, y in bosses:
            E = E.fuse(Part.makeCylinder(bossR, H, V(x, y, 0)))
        for x, y in bosses:
            E = E.cut(Part.makeCylinder(screwR, depth, V(x, y, H - depth)))
        L = Part.makeBox(W, D, lidT, V(0, 0, H)).fuse(
            Part.makeBox(W - 2 * c, D - 2 * c, lip, V(c, c, H - lip))
        )
        for x, y in bosses:
            L = L.cut(Part.makeCylinder(bossR + clr, lip, V(x, y, H - lip)))
            L = L.cut(Part.makeCylinder(screwR, lidT + lip + 2, V(x, y, H - lip - 1)))
        for body, expected in ((enc, E), (lid, L)):
            shape = body.Shape
            self.assertEqual(len(shape.Solids), 1, body.Name)
            difference = shape.cut(expected).Volume + expected.cut(shape).Volume
            self.assertLess(difference, 0.01, body.Name)
        self.assertLess(enc.Shape.common(lid.Shape).Volume, 1e-6)

    # ---------------------------------------------------------------- D-t2: external geometry

    def externalEdge(self, owner, target, targetPad):
        """owner's sketch (z 20) takes targetPad's top front edge, (0,0,10)-(40,0,10)."""
        s = sketch(owner, "Ext", xyPlane(owner), z=20)
        self.doc.recompute()
        edge = edgeAt(targetPad, (0, 0, 10), (40, 0, 10))
        self.assertIsNotNone(edge)
        s.addExternal(targetPad.Name, edge)
        self.doc.recompute()
        self.assertTrue(s.isValid())
        line = s.ExternalGeo[2]  # after the H and V axes
        ends = sorted((round(p.x, 6), round(p.y, 6)) for p in (line.StartPoint, line.EndPoint))
        self.assertEqual(ends, [(0, 0), (40, 0)])
        return s

    def testExternalGeometryFromAnotherPart(self):
        """D-t2: same App::Part and the top level: allowed; another App::Part: refused."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        ext = self.externalEdge(upper, lower, padL)
        self.assertFalse(outOfScope(self.doc, [ext]))

    def testExternalGeometryAtTheTopLevel(self):
        lower, upper, padL, padU = self.twoBodies()
        ext = self.externalEdge(upper, lower, padL)
        self.assertFalse(outOfScope(self.doc, [ext]))

    def testExternalGeometryFromAnotherAppPartIsRefused(self):
        lower, upper, padL, padU = self.twoBodies()
        partL = self.doc.addObject("App::Part", "PartL")
        partU = self.doc.addObject("App::Part", "PartU")
        partL.addObject(lower)
        partU.addObject(upper)
        s = sketch(upper, "Ext", xyPlane(upper), z=20)
        self.doc.recompute()
        with self.assertRaises(ValueError):
            s.addExternal(padL.Name, edgeAt(padL, (0, 0, 10), (40, 0, 10)))

    # ---------------------------------------------------------------- D-t3: link scope

    def testNoOutOfScopeLinksInAStudio(self):
        """D-t3: Profile and Up-to-face into another part of the studio are in scope; the same
        links across two App::Parts are not (the control)."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        holeSk = sketch(upper, "HoleSk", xyPlane(upper), (18, 18, 22, 22), z=15)
        holeL = lower.newObject("PartDesign::Pocket", "HoleLower")
        holeL.Profile = holeSk
        holeL.Type = "ThroughAll"
        cap = pad(upper, "Cap", sketch(upper, "CapSk", xyPlane(upper), (5, 5, 10, 10), z=20), 1)
        cap.Type = "UpToFace"
        cap.Reversed = True
        cap.UpToFace = (padL, [faceAt(padL, 10)])
        self.assertSettled()
        self.assertFalse(outOfScope(self.doc, [holeL, cap]))
        other = self.doc.addObject("App::Part", "Other")
        other.addObject(lower)
        self.assertTrue(outOfScope(self.doc, [holeL]))

    def testMovesCarryTheirLinksAsBefore(self):
        """D-t3: what moves together with an object is unchanged. A Body moved into an App::Part
        brings its features; a free sketch moved into one brings the object it projects."""
        lower, upper, padL, padU = self.twoBodies()
        part = self.doc.addObject("App::Part", "Part")
        part.addObject(lower)
        self.assertEqual(lower.getParentGeoFeatureGroup(), part)
        self.assertEqual(padL.Profile[0].getParentGeoFeatureGroup(), lower)
        box = self.doc.addObject("Part::Box", "Box")
        free = self.doc.addObject("Sketcher::SketchObject", "Free")
        self.doc.recompute()
        free.addExternal("Box", "Edge1")
        self.doc.recompute()
        other = self.doc.addObject("App::Part", "Other")
        other.addObject(free)
        self.assertEqual(free.getParentGeoFeatureGroup(), other)
        self.assertEqual(box.getParentGeoFeatureGroup(), other)

    # ---------------------------------------------------------------- D-t7: T1's second path

    def testFaceProfileOfAFirstFeatureIsRefused(self):
        """D-t7: another part's face as the Profile of a Body's first feature would make the
        whole part its base (ProfileBased::getBaseObject, T1's second path, ops#308). Until T1
        covers it, the predicate refuses it; a later feature, or a sketch, is fine."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        top = faceAt(padL, 10)
        empty = self.doc.addObject("PartDesign::Body", "Empty")
        part.addObject(empty)
        self.assertFalse(PartDesign.isStudioProfile(empty, padL, top))
        self.assertTrue(PartDesign.isStudioProfile(upper, padL, top))
        self.assertTrue(PartDesign.isStudioProfile(empty, lower.getObject("LowSk")))
        first = empty.newObject("PartDesign::Pad", "First")
        self.assertFalse(PartDesign.isStudioProfile(first, padL, top))
        later = upper.newObject("PartDesign::Pocket", "Later")
        self.assertTrue(PartDesign.isStudioProfile(later, padL, top))
        # a Body that only has a sketch so far: its next feature is still its first
        sketchy = self.doc.addObject("PartDesign::Body", "Sketchy")
        part.addObject(sketchy)
        only = sketch(sketchy, "Only", xyPlane(sketchy), (0, 0, 1, 1))
        sketchy.Tip = only
        self.assertFalse(PartDesign.isStudioProfile(sketchy, padL, top))
