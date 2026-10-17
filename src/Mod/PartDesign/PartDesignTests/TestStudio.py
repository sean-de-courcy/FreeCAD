# SPDX-License-Identifier: LGPL-2.1-or-later

"""B+ Stage 1, session 1a (ops#325): direct references between the Bodies of a studio.

A studio is the App::Part that holds Bodies (not an Assembly), or the document's top level. Its
Bodies share one origin, so a pick may link another part directly, with no binder or copy. The
Gui gates call the predicates tested here (PartDesign.isStudioPick, isStudioProfile,
studioOriginFeature; Sketcher's isExternalAllowed). Every model is designed: the expected shapes
come from volumes, bounding boxes and point membership.
"""

import json
import os
import subprocess
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
    """Whether recomputing objects warns "links are out of scope" (DocumentObject::recompute,
    GeoFeatureGroupExtension::isLinkValid). The warning goes through the console's std observer
    to stderr: fd 2 is caught meanwhile. Every test that expects no warning also has a control
    that expects one, so a capture that fails can't pass unseen. (The dependency graph's orange
    edges don't show these links: its edges join property nodes.)"""
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


def globalBox(feature, shape=None):
    """The bounding box of feature's shape (or of shape, in feature's Body), placed globally, as
    (xmin, ymin, zmin, xmax, ymax, zmax) rounded to 1e-6."""
    shape = (shape if shape is not None else feature.Shape).copy()
    body = feature.getParentGeoFeatureGroup()
    shape.Placement = body.getGlobalPlacement().multiply(shape.Placement)
    box = shape.BoundBox
    return tuple(
        round(v, 6) + 0.0 for v in (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)
    )


CHILD_ASSEMBLY = """\
import json, os, sys, traceback
out = {}
try:
    import FreeCAD as App
    import Part
    import PartDesign
    import Sketcher

    def body(doc, name, container=None):
        b = doc.addObject("PartDesign::Body", name)
        if container is not None:
            container.addObject(b)
        s = b.newObject("Sketcher::SketchObject", name + "Sk")
        s.AttachmentSupport = [(b.Origin.OriginFeatures[3], "")]
        s.MapMode = "FlatFace"
        for a, c in (((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10)), ((0, 10), (0, 0))):
            s.addGeometry(Part.LineSegment(App.Vector(*a, 0), App.Vector(*c, 0)))
        p = b.newObject("PartDesign::Pad", name + "Pad")
        p.Profile = s
        p.Length = 10
        return b, s, p

    out["assemblyLoadedAtStart"] = "AssemblyApp" in sys.modules
    doc = App.newDocument("Child")
    one, oneSk, onePad = body(doc, "One")
    two, twoSk, twoPad = body(doc, "Two")
    doc.recompute()
    # the predicates and App's scope rule, asked before the Assembly module loads
    out["earlyPick"] = PartDesign.isStudioPick(onePad, twoPad, "Face1")
    out["earlyStudio"] = PartDesign.studioOf(one) is not None
    oneCross = one.newObject("PartDesign::Pad", "OneCross")
    oneCross.Profile = twoSk
    oneCross.Length = 2
    doc.recompute()
    asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
    x, xSk, xPad = body(doc, "X", asm)
    y, ySk, yPad = body(doc, "Y", asm)
    cross = x.newObject("PartDesign::Pad", "Cross")
    cross.Profile = ySk
    cross.Length = 2
    doc.recompute()
    out["assemblyStudio"] = PartDesign.studioOf(x) is not None
    out["assemblyPick"] = PartDesign.isStudioPick(xPad, yPad, "Face1")
    # App's scope rule: the warning of the Cross pad's recompute, caught on fd 2
    import tempfile
    App.Console.SetStatus("Console", "Wrn", True)
    saved = os.dup(2)
    with tempfile.TemporaryFile() as caught:
        os.dup2(caught.fileno(), 2)
        try:
            cross.touch()
            doc.recompute()
        finally:
            os.dup2(saved, 2)
        caught.seek(0)
        out["assemblyOutOfScope"] = b"links are out of scope" in caught.read()
except Exception:
    out["error"] = traceback.format_exc()
with open(os.environ["FC_STUDIO_CHILD_OUT"], "w") as fh:
    json.dump(out, fh)
os._exit(0)
"""


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
        """D-t6: a pick through an App::Link would ignore the Link's placement. Round 2 (review
        H1): the selection gates see only the resolved object, so a Body that any link shows (it,
        a container holding it, or one of its features) is no studio pick at all."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        self.assertTrue(PartDesign.isStudioPick(padU, part, "Lower.LowerPad.Face1"))
        self.assertTrue(PartDesign.isStudioPick(padU, padL, "Face1"))
        link = self.doc.addObject("App::Link", "Link")
        link.LinkedObject = lower
        link.Placement = App.Placement(V(100, 0, 0), App.Rotation())
        part.addObject(link)
        self.doc.recompute()
        self.assertFalse(PartDesign.isStudioPick(padU, part, "Lower.LowerPad.Face1"))
        self.assertFalse(PartDesign.isStudioPick(padU, part, "Link.LowerPad.Face1"))
        self.assertFalse(PartDesign.isStudioPick(padU, link, "LowerPad.Face1"))
        self.assertFalse(PartDesign.isStudioPick(padU, link, ""))
        self.assertFalse(PartDesign.isStudioProfile(padU, link, "LowerPad.Face1"))
        # the resolved pick, as the gates see it
        self.assertFalse(PartDesign.isStudioPick(padU, padL, "Face1"))
        self.assertFalse(PartDesign.isStudioProfile(padU, lower.getObject("LowSk")))
        self.assertIsNone(PartDesign.studioOriginFeature(padU, lower.Origin.OriginFeatures[3]))
        # Upper isn't shown by a link: Lower may still use it
        self.assertTrue(PartDesign.isStudioPick(padL, padU, "Face1"))
        # a link to one of Lower's features counts too
        link.LinkedObject = padL
        self.doc.recompute()
        self.assertFalse(PartDesign.isStudioPick(padU, padL, "Face1"))
        # and one to the App::Part holding both: neither may use the other
        self.doc.removeObject(link.Name)
        self.assertTrue(PartDesign.isStudioPick(padU, padL, "Face1"))
        partLink = self.doc.addObject("App::Link", "PartLink")
        partLink.LinkedObject = part
        partLink.Placement = App.Placement(V(0, 100, 0), App.Rotation())
        self.doc.recompute()
        self.assertFalse(PartDesign.isStudioPick(padU, padL, "Face1"))
        self.assertFalse(PartDesign.isStudioPick(padL, padU, "Face1"))

    def assertLowerRefused(self, padU, padL, lower, refused=True):
        """Upper may (refused False) or may not (True) use Lower directly, as the gates ask."""
        self.assertEqual(PartDesign.isStudioPick(padU, padL, "Face1"), not refused)
        self.assertEqual(PartDesign.isStudioProfile(padU, lower.getObject("LowSk")), not refused)
        origin = PartDesign.studioOriginFeature(padU, lower.Origin.OriginFeatures[3])
        self.assertEqual(origin is None, refused)

    def testSubLinkIsRefused(self):
        """Round 3 (review r2, silent wrong): a link to the App::Part with a subname, (Part,
        "Lower.") or (Part, "Lower.LowerPad."), shows Lower elsewhere. It sits in the Part's
        in-list and resolves to Lower or its pad, not to the Part, so the rule missed it: a gate
        linked Lower's face 100 mm from the face picked. Any link-type user of what shows Lower
        counts, whatever it resolves to."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        self.assertLowerRefused(padU, padL, lower, refused=False)
        for sub in ("Lower.", "Lower.LowerPad."):
            link = self.doc.addObject("App::Link", "SubLink")
            link.LinkedObject = (part, sub)
            link.Placement = App.Placement(V(100, 0, 0), App.Rotation())
            self.doc.recompute()
            self.assertEqual(link.getLinkedObject(False), lower if sub == "Lower." else padL)
            self.assertLowerRefused(padU, padL, lower)
            self.assertFalse(PartDesign.isStudioPick(padU, link, "LowerPad.Face1"))
            self.doc.removeObject(link.Name)
            self.doc.recompute()
            self.assertLowerRefused(padU, padL, lower, refused=False)

    def testLinkArrayIsRefused(self):
        """Round 3: a link array of Lower, and its elements."""
        lower, upper, padL, padU = self.twoBodies()
        self.assertLowerRefused(padU, padL, lower, refused=False)
        array = self.doc.addObject("App::Link", "Array")
        array.LinkedObject = lower
        array.ElementCount = 3
        array.ShowElement = True
        self.doc.recompute()
        self.assertLowerRefused(padU, padL, lower)
        self.assertFalse(PartDesign.isStudioPick(padU, array, "1.LowerPad.Face1"))

    def testLinkGroupHoldingABodyIsRefused(self):
        """Round 3 (review r2, p8): an App::LinkGroup holding Lower, placed at z 100, shows it
        there. It resolves to itself and is no group of Lower's, so neither the resolved pick nor
        the pick's path through it was refused. It is now, both ways."""
        lower, upper, padL, padU = self.twoBodies()
        self.assertLowerRefused(padU, padL, lower, refused=False)
        group = self.doc.addObject("App::LinkGroup", "LinkGroup")
        group.ElementList = [lower]
        group.Placement = App.Placement(V(0, 0, 100), App.Rotation())
        self.doc.recompute()
        self.assertEqual(group.getLinkedObject(False), group)
        self.assertLowerRefused(padU, padL, lower)
        self.assertFalse(PartDesign.isStudioPick(padU, group, "Lower.LowerPad.Face1"))
        group.ElementList = []
        self.doc.removeObject(group.Name)
        self.doc.recompute()
        self.assertLowerRefused(padU, padL, lower, refused=False)

    def testLinkToAnOriginIsRefused(self):
        """Round 3 (review r2, p5): a link to Lower's Origin, or to one of its planes, shows
        Lower's frame elsewhere: Lower's origin (and Lower) are no pick."""
        lower, upper, padL, padU = self.twoBodies()
        for target in (lower.Origin, lower.Origin.OriginFeatures[3]):
            self.assertLowerRefused(padU, padL, lower, refused=False)
            link = self.doc.addObject("App::Link", "OriginLink")
            link.LinkedObject = target
            link.Placement = App.Placement(V(0, 0, 50), App.Rotation())
            self.doc.recompute()
            self.assertLowerRefused(padU, padL, lower)
            self.doc.removeObject(link.Name)
            self.doc.recompute()
        self.assertLowerRefused(padU, padL, lower, refused=False)

    def testAssemblyIsNoStudioWhateverLoadsFirst(self):
        """Review S2: the Assembly type was looked up once, at the first call. Asked before the
        Assembly module loaded, it stayed unknown, and Bodies placed directly in an Assembly
        (moved by its joints) counted as one studio. In a child FreeCADCmd that has loaded no
        Assembly: a pick between two top-level Bodies first, then an Assembly."""
        from PartDesignTests.TestNamingDump import _freecadCmd

        workDir = tempfile.mkdtemp(prefix="studio-child-")
        script = os.path.join(workDir, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(CHILD_ASSEMBLY)
        out = os.path.join(workDir, "out.json")
        env = dict(os.environ, FC_STUDIO_CHILD_OUT=out)
        with open(os.path.join(workDir, "child.log"), "w") as log:
            subprocess.run(
                [_freecadCmd(), script], env=env, stdout=log, stderr=subprocess.STDOUT,
                cwd=workDir, timeout=300,
            )
        self.assertTrue(os.path.isfile(out), f"no result from the child ({workDir})")
        with open(out, encoding="utf-8") as fh:
            result = json.load(fh)
        if "error" in result and "Assembly" in result["error"]:
            self.skipTest("the Assembly module isn't available")
        self.assertNotIn("error", result)
        self.assertFalse(result["assemblyLoadedAtStart"])
        self.assertTrue(result["earlyPick"])
        self.assertTrue(result["earlyStudio"])
        self.assertFalse(result["assemblyStudio"])
        self.assertFalse(result["assemblyPick"])
        self.assertTrue(result["assemblyOutOfScope"])

    def testAWholeBodyIsNoPick(self):
        """Review M3: another Body picked whole (it shows its Tip's shape). A link to it would
        depend on all of it, a cycle once its features use the owner. Its features are picked
        instead; the owner's own Body is fine."""
        lower, upper, padL, padU = self.twoBodies()
        self.assertFalse(PartDesign.isStudioPick(padU, lower, "Face1"))
        self.assertFalse(PartDesign.isStudioProfile(upper, lower, "Face1"))
        self.assertTrue(PartDesign.isStudioPick(padU, padL, "Face1"))
        self.assertTrue(PartDesign.isStudioPick(padU, upper, "Face1"))

    def testDatumOfAnotherPart(self):
        """Review M5: a datum plane of another part is a pick like its faces: a sketch on it lands
        where it is. Placed differently, the Bodies are no studio for it either."""
        lower, upper, padL, padU = self.twoBodies()
        datum = lower.newObject("PartDesign::Plane", "DatumL")
        datum.AttachmentSupport = [(padL, faceAt(padL, 10))]
        datum.MapMode = "FlatFace"
        self.doc.recompute()
        self.assertTrue(PartDesign.isStudioPick(padU, datum, ""))
        onDatum = sketch(upper, "OnDatum", [(datum, "")], (0, 0, 5, 5))
        self.assertSettled()
        self.assertAlmostEqual(onDatum.getGlobalPlacement().Base.z, 10, places=6)
        upper.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        self.assertFalse(PartDesign.isStudioPick(padU, datum, ""))

    # ---------------------------------------------------------------- one origin (review S1)

    def placedSiblings(self, where):
        """Review probe p1's model at the top level: A, a 10 mm cube pad at A's origin, and B at
        `where`. Returns A, B, A's sketch, A's pad and the pad's top face."""
        a = self.doc.addObject("PartDesign::Body", "A")
        b = self.doc.addObject("PartDesign::Body", "B")
        b.Placement = App.Placement(where, App.Rotation())
        sa = sketch(a, "SA", xyPlane(a), (0, 0, 10, 10))
        padA = pad(a, "PadA", sa, 10)
        self.doc.recompute()
        return a, b, sa, padA, faceAt(padA, 10)

    def testPlacedSiblingsAreNoStudio(self):
        """Review S1: B placed at (30, 0, 3). Every reader takes A's geometry in B's frame: a
        sketch of B on A's top face sat at (30, 0, 13), not z = 10, external geometry 30 off, a
        pad of A's sketch at x 30..40, all silently. The predicates refuse such picks (the copy
        places them right); a pad of A's sketch set from Python fails loudly (ops#308). Placed
        alike, the Bodies are one studio."""
        a, b, sa, padA, top = self.placedSiblings(V(30, 0, 3))
        sb = b.newObject("Sketcher::SketchObject", "SB")
        self.assertFalse(PartDesign.isStudioPick(sb, padA, top))
        self.assertFalse(PartDesign.isStudioProfile(b, sa))
        self.assertFalse(PartDesign.isStudioProfile(b, padA, top))
        self.assertIsNone(PartDesign.studioOriginFeature(sb, a.Origin.OriginFeatures[3]))
        sx = sketch(b, "SX", xyPlane(b))
        self.doc.recompute()
        with self.assertRaises(ValueError):
            sx.addExternal(padA.Name, edgeAt(padA, (0, 0, 0), (10, 0, 0)))
        padB = b.newObject("PartDesign::Pad", "PadB")
        padB.Profile = sa
        padB.Length = 2
        # the same link set from Python fails loudly (ops#308), before any scope warning
        self.doc.recompute()
        self.assertFalse(padB.isValid())
        self.assertIn("placed elsewhere", padB.getStatusString())
        a.Placement = b.Placement
        self.assertTrue(PartDesign.isStudioPick(sb, padA, top))
        self.assertTrue(PartDesign.isStudioProfile(b, sa))
        self.assertFalse(outOfScope(self.doc, [padB]))
        self.assertTrue(padB.isValid(), padB.getStatusString())

    def testSiblingsAtOneOriginLandRight(self):
        """Review S1's oracles, p1's model with B at A's origin: B's sketch on A's top face and
        its pad, a datum plane on that face, a pad up to it, a pad of A's sketch and external
        geometry from A all land where A's geometry is (placed apart, p1 found them at z 13,
        x 32..38, 30 off)."""
        a, b, sa, padA, top = self.placedSiblings(V(0, 0, 0))
        sb = b.newObject("Sketcher::SketchObject", "SB")
        self.assertTrue(PartDesign.isStudioPick(sb, padA, top))
        sb.AttachmentSupport = [(padA, top)]
        sb.MapMode = "FlatFace"
        rect(sb, 2, 2, 8, 8)
        padB = pad(b, "PadB", sb, 5)
        datum = b.newObject("PartDesign::Plane", "DP")
        datum.AttachmentSupport = [(padA, top)]
        datum.MapMode = "FlatFace"
        su = sketch(b, "SU", xyPlane(b), (5, 20, 10, 25))
        upTo = b.newObject("PartDesign::Pad", "PadU")
        upTo.Profile = su
        upTo.Type = "UpToFace"
        upTo.UpToFace = (padA, [top])
        self.assertTrue(PartDesign.isStudioProfile(b, sa))
        padP = pad(b, "PadP", sa, 2)
        sx = sketch(b, "SX", xyPlane(b), z=20)
        self.assertSettled()
        sx.addExternal(padA.Name, edgeAt(padA, (0, 0, 0), (10, 0, 0)))
        self.assertSettled()
        self.assertAlmostEqual(sb.getGlobalPlacement().Base.z, 10, places=6)
        self.assertAlmostEqual(datum.getGlobalPlacement().Base.z, 10, places=6)
        self.assertEqual(globalBox(padB, padB.AddSubShape), (2, 2, 10, 8, 8, 15))
        self.assertEqual(globalBox(upTo, upTo.AddSubShape), (5, 20, 0, 10, 25, 10))
        self.assertEqual(globalBox(padP, padP.AddSubShape), (0, 0, 0, 10, 10, 2))
        line = sx.ExternalGeo[2]
        ends = sorted((round(p.x, 6), round(p.y, 6)) for p in (line.StartPoint, line.EndPoint))
        self.assertEqual(ends, [(0, 0), (10, 0)])
        self.assertFalse(outOfScope(self.doc, [padB, upTo, padP, sx]))

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
        # the control: Lower in another App::Part
        other = self.doc.addObject("App::Part", "Other")
        other.addObject(lower)
        self.assertTrue(outOfScope(self.doc, [ext]))

    def testExternalGeometryAtTheTopLevel(self):
        lower, upper, padL, padU = self.twoBodies()
        ext = self.externalEdge(upper, lower, padL)
        self.assertFalse(outOfScope(self.doc, [ext]))
        # the control: Lower placed elsewhere
        lower.Placement = App.Placement(V(0, 0, 1), App.Rotation())
        self.assertTrue(outOfScope(self.doc, [ext]))

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

    def testALinkShownSiblingIsOutOfScope(self):
        """Round 3 (review r2, low 5): App's scope rule follows the gates: a link into a Body that
        a link shows elsewhere is out of scope (here a sub-link (Part, "Upper.")), and back in
        scope once the link goes."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        holeSk = sketch(upper, "HoleSk", xyPlane(upper), (18, 18, 22, 22), z=15)
        holeL = lower.newObject("PartDesign::Pocket", "HoleLower")
        holeL.Profile = holeSk
        holeL.Type = "ThroughAll"
        self.assertSettled()
        self.assertFalse(outOfScope(self.doc, [holeL]))
        link = self.doc.addObject("App::Link", "SubLink")
        link.LinkedObject = (part, "Upper.")
        link.Placement = App.Placement(V(100, 0, 0), App.Rotation())
        self.assertTrue(outOfScope(self.doc, [holeL]))
        self.doc.removeObject(link.Name)
        self.assertFalse(outOfScope(self.doc, [holeL]))

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

    def testFaceProfileOfAFirstFeatureIsAllowed(self):
        """D-t7: another part's face may be the Profile of a Body's first feature too (2a):
        ProfileBased::getBaseObject takes no base from it (T1's second path, ops#308; N-t6 checks
        the volume)."""
        part = self.doc.addObject("App::Part", "Part")
        lower, upper, padL, padU = self.twoBodies(part)
        top = faceAt(padL, 10)
        empty = self.doc.addObject("PartDesign::Body", "Empty")
        part.addObject(empty)
        self.assertTrue(PartDesign.isStudioProfile(empty, padL, top))
        self.assertTrue(PartDesign.isStudioProfile(upper, padL, top))
        self.assertTrue(PartDesign.isStudioProfile(empty, lower.getObject("LowSk")))
        first = empty.newObject("PartDesign::Pad", "First")
        self.assertTrue(PartDesign.isStudioProfile(first, padL, top))
        later = upper.newObject("PartDesign::Pocket", "Later")
        self.assertTrue(PartDesign.isStudioProfile(later, padL, top))
        # a Body that only has a sketch so far: its next feature is still its first
        sketchy = self.doc.addObject("PartDesign::Body", "Sketchy")
        part.addObject(sketchy)
        only = sketch(sketchy, "Only", xyPlane(sketchy), (0, 0, 1, 1))
        sketchy.Tip = only
        self.assertTrue(PartDesign.isStudioProfile(sketchy, padL, top))

    # ---------------------------------------------------------------- D-t4: a moved Body (1b-1)

    def movedSibling(self):
        """D-t4's model at the top level, at one origin: B, a 40x40x10 pad; A uses it four ways:
        a pad of B's sketch, a pattern along B's front bottom edge, a sketch attached to B's top
        face, and a sketch on A's XZ plane taking B's top front edge as external geometry."""
        a = self.doc.addObject("PartDesign::Body", "A")
        b = self.doc.addObject("PartDesign::Body", "B")
        sb = sketch(b, "SB", xyPlane(b), (0, 0, 40, 40))
        padB = pad(b, "PadB", sb, 10)
        sa = sketch(a, "SA", xyPlane(a), (0, 50, 10, 60))
        padA = pad(a, "PadA", sa, 10)
        self.doc.recompute()
        across = pad(a, "Across", sb, 2)  # a pad of B's sketch
        pattern = a.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [padA]
        pattern.Direction = (padB, [edgeAt(padB, (0, 0, 0), (40, 0, 0))])
        pattern.Length = 20
        pattern.Occurrences = 2
        a.Tip = pattern
        attached = a.newObject("Sketcher::SketchObject", "Attached")
        attached.AttachmentSupport = [(padB, faceAt(padB, 10))]
        attached.MapMode = "FlatFace"
        ext = a.newObject("Sketcher::SketchObject", "Ext")
        ext.AttachmentSupport = [(a.Origin.OriginFeatures[4], "")]  # XZ_Plane
        ext.MapMode = "FlatFace"
        self.doc.recompute()
        ext.addExternal(padB.Name, edgeAt(padB, (0, 0, 10), (40, 0, 10)))
        self.assertSettled()
        return a, b, padB, across, pattern, attached, ext

    def externalEnds(self, ext):
        """The global end points of ext's first external edge (after the H and V axes)."""
        line = ext.ExternalGeo[2]
        placement = ext.getGlobalPlacement()
        return sorted(
            tuple(round(c, 6) + 0.0 for c in placement.multVec(p))
            for p in (line.StartPoint, line.EndPoint)
        )

    def assertFollows(self, b, across, pattern, attached, ext, offset):
        """At one origin with B offset by `offset` from A, or apart (a failing pad and pattern)."""
        apart = offset != V(0, 0, 0)
        for feature in (across, pattern):
            self.assertEqual(feature.isValid(), not apart, feature.Name)
            if apart:
                self.assertIn("placed elsewhere", feature.getStatusString(), feature.Name)
        self.assertTrue(attached.isValid(), attached.getStatusString())
        self.assertTrue(ext.isValid(), ext.getStatusString())
        base = attached.getGlobalPlacement().Base
        self.assertEqual(
            tuple(round(c, 6) + 0.0 for c in base), tuple(V(0, 0, 10) + offset), "attached"
        )
        start, end = V(0, 0, 10) + offset, V(40, 0, 10) + offset
        self.assertEqual(
            self.externalEnds(ext),
            sorted(tuple(round(c, 6) + 0.0 for c in p) for p in (start, end)),
            "external edge",
        )

    def testMovedSiblingFailsOrFollows(self):
        """D-t4 (revised for 1b, ops#325): B moved by (10, 0, 0) after A linked it, then a plain
        doc.recompute(), no touch: A's pad of B's sketch and its pattern along B's edge fail
        loudly (they read B's geometry as if it were in A); the sketch attached to B's face and
        the external edge of B follow B (ops#318's linkFrame; the external edge was left at its
        old place, ops#331). Set back, all recover."""
        a, b, padB, across, pattern, attached, ext = self.movedSibling()
        self.assertFollows(b, across, pattern, attached, ext, V(0, 0, 0))
        b.Placement = App.Placement(V(10, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertFollows(b, across, pattern, attached, ext, V(10, 0, 0))
        b.Placement = App.Placement()
        self.doc.recompute()
        self.assertFollows(b, across, pattern, attached, ext, V(0, 0, 0))
        self.assertSettled()

    def testSiblingMovedIntoAPlacedPart(self):
        """D-t4's variant (Opus M1, p4): B moved into an App::Part placed (0, 0, 5)."""
        a, b, padB, across, pattern, attached, ext = self.movedSibling()
        part = self.doc.addObject("App::Part", "Part")
        part.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        part.addObject(b)
        self.doc.recompute()
        self.assertFollows(b, across, pattern, attached, ext, V(0, 0, 5))
        part.removeObject(b)
        self.doc.recompute()
        self.assertFollows(b, across, pattern, attached, ext, V(0, 0, 0))

    def testMovedSiblingAcrossAReopen(self):
        """The failure and the external edge's frames are saved: after a reopen, B set back
        recovers the pattern, and B moved again moves the external edge."""
        a, b, padB, across, pattern, attached, ext = self.movedSibling()
        b.Placement = App.Placement(V(10, 0, 0), App.Rotation())
        self.doc.recompute()
        path = os.path.join(tempfile.mkdtemp(), "moved.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        get = self.doc.getObject
        objects = [get(n) for n in ("B", "Across", "Pattern", "Attached", "Ext")]
        b = objects[0]
        self.doc.recompute()
        self.assertFollows(*objects, V(10, 0, 0))
        b.Placement = App.Placement(V(0, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertFollows(*objects, V(0, 0, 0))
        b.Placement = App.Placement(V(0, 0, 3), App.Rotation())
        self.doc.recompute()
        self.assertFollows(*objects, V(0, 0, 3))

    def movedByACell(self, inAPart):
        """B's x, or that of an App::Part holding B, follows a spreadsheet cell; dx 10 and one
        plain recompute, then dx 0 and one recompute (ops#342): the move lands in the same
        recompute, though it happens in the middle of it, after A's readers may have run (made
        last, the Part comes after them in the recompute's order; made first, before them)."""
        a, b, padB, across, pattern, attached, ext = self.movedSibling()
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "0")
        sheet.setAlias("A1", "dx")
        container = b
        if inAPart:
            container = self.doc.addObject("App::Part", "Part")
            container.addObject(b)
        container.setExpression(".Placement.Base.x", "Sheet.dx")
        self.doc.recompute()
        self.assertFollows(b, across, pattern, attached, ext, V(0, 0, 0))
        sheet.set("dx", "10")
        self.doc.recompute()
        self.assertFollows(b, across, pattern, attached, ext, V(10, 0, 0))
        sheet.set("dx", "0")
        self.doc.recompute()
        self.assertFollows(b, across, pattern, attached, ext, V(0, 0, 0))
        self.assertSettled()

    def testSiblingMovedByAnExpression(self):
        """D-t4 with B's Placement from a cell (ops#342): A's pad and pattern fail, and recover,
        in the same recompute; the attached sketch and the external edge follow."""
        self.movedByACell(False)

    def testSiblingInAPartMovedByAnExpression(self):
        """D-t4 with B in an App::Part whose Placement follows a cell (ops#342): no Body's
        Placement changes, and the same holds."""
        self.movedByACell(True)

    def testOtherPlacersInABodyPlacedElsewhereFail(self):
        """1b-1 (b): every PartDesign link read as if in the feature's Body fails loudly when its
        Body is placed elsewhere: a polar pattern's axis, a mirror plane, a draft's neutral plane
        and pull direction, a MultiTransform step's direction (probe_b, B turned 90 degrees: each
        kept its result, read in B's own frame). Set back, all recover."""
        a = self.doc.addObject("PartDesign::Body", "A")
        b = self.doc.addObject("PartDesign::Body", "B")
        padB = pad(b, "PadB", sketch(b, "SB", xyPlane(b), (20, 0, 40, 5)), 5)
        padA = pad(a, "PadA", sketch(a, "SA", xyPlane(a), (0, 0, 10, 10)), 10)
        self.doc.recompute()
        zEdge = edgeAt(padB, (20, 0, 0), (20, 0, 5))
        xEdge = edgeAt(padB, (20, 0, 0), (40, 0, 0))
        top = faceAt(padB, 5)
        polar = a.newObject("PartDesign::PolarPattern", "Polar")
        polar.Originals = [padA]
        polar.Axis = (padB, [zEdge])
        polar.Angle = 90
        polar.Occurrences = 2
        a.Tip = polar
        mirror = a.newObject("PartDesign::Mirrored", "Mirror")
        mirror.Originals = [padA]
        mirror.MirrorPlane = (padB, [top])
        a.Tip = mirror
        self.doc.recompute()
        draft = a.newObject("PartDesign::Draft", "Draft")
        side = next(
            f"Face{i}"
            for i, f in enumerate(mirror.Shape.Faces, 1)
            if abs(f.normalAt(0, 0).x + 1) < 1e-9
        )
        draft.Base = (mirror, [side])
        draft.Angle = 5
        draft.NeutralPlane = (padB, [top])
        draft.PullDirection = (padB, [zEdge])
        a.Tip = draft
        multi = a.newObject("PartDesign::MultiTransform", "Multi")
        multi.Originals = [padA]
        step = a.newObject("PartDesign::LinearPattern", "Step")
        step.Direction = (padB, [xEdge])
        step.Length = 30
        step.Occurrences = 2
        multi.Transformations = [step]
        a.Tip = multi
        self.assertSettled()
        features = (polar, mirror, draft, multi)
        b.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 1, 0), 90))
        self.doc.recompute()
        for feature in features:
            self.assertFalse(feature.isValid(), feature.Name)
            self.assertIn("placed elsewhere", feature.getStatusString(), feature.Name)
        b.Placement = App.Placement()
        self.doc.recompute()
        for feature in features:
            self.assertTrue(feature.isValid(), feature.Name + ": " + feature.getStatusString())
        self.assertSettled()

    def testMultiTransformJudgesAStepOutsideEveryBodyInItsOwnBody(self):
        """PR 301 review low 2: a MultiTransform step made by script at the document's root (in
        no Body), its direction a root sketch's line along X. Body A at identity: valid, the
        4 mm cube and its copy 20 along X. A turned 90 degrees about Z: the MultiTransform fails,
        naming the root (it stayed valid, its copies along A's own X, global Y). Set back, it
        recovers."""
        a = self.doc.addObject("PartDesign::Body", "A")
        cube = pad(a, "Cube", sketch(a, "SA", xyPlane(a), (0, 0, 4, 4)), 4)
        line = self.doc.addObject("Sketcher::SketchObject", "Dir")
        line.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        self.doc.recompute()
        multi = a.newObject("PartDesign::MultiTransform", "Multi")
        multi.Originals = [cube]
        step = self.doc.addObject("PartDesign::LinearPattern", "Step")
        step.Direction = (line, ["Edge1"])
        step.Length = 20
        step.Occurrences = 2
        multi.Transformations = [step]
        a.Tip = multi
        self.doc.recompute()
        self.assertIsNone(step.getParentGeoFeatureGroup())
        self.assertTrue(multi.isValid(), multi.getStatusString())
        self.assertAlmostEqual(multi.Shape.Volume, 128)
        self.assertAlmostEqual(multi.Shape.BoundBox.XMax, 24)
        a.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), 90))
        self.doc.recompute()
        self.assertFalse(multi.isValid())
        self.assertIn("placed elsewhere", multi.getStatusString())
        self.assertIn("the document's root", multi.getStatusString())
        a.Placement = App.Placement()
        self.doc.recompute()
        self.assertTrue(multi.isValid(), multi.getStatusString())
        self.assertAlmostEqual(multi.Shape.BoundBox.XMax, 24)

    def testBodylessSketchFollowsAMovedBody(self):
        """ops#324: a sketch in no Body, in an App::Part placed (0, 0, 5) beside Body B, takes
        B's top front edge as external geometry. B moved by (10, 0, 0) in the Part: the edge
        follows (it stayed, read in B's frame); set back, it returns. The Part's own placement
        changes nothing."""
        part = self.doc.addObject("App::Part", "Part")
        part.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        b = self.doc.addObject("PartDesign::Body", "B")
        part.addObject(b)
        padB = pad(b, "PadB", sketch(b, "SB", xyPlane(b), (0, 0, 40, 40)), 10)
        ext = self.doc.addObject("Sketcher::SketchObject", "Ext")
        part.addObject(ext)
        ext.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))  # the XZ plane
        self.doc.recompute()
        ext.addExternal(padB.Name, edgeAt(padB, (0, 0, 10), (40, 0, 10)))
        self.assertSettled()

        def ends(offset):
            points = (V(0, 0, 15) + offset, V(40, 0, 15) + offset)
            return sorted(tuple(round(c, 6) + 0.0 for c in p) for p in points)

        self.assertEqual(self.externalEnds(ext), ends(V(0, 0, 0)))
        b.Placement = App.Placement(V(10, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertTrue(ext.isValid(), ext.getStatusString())
        self.assertEqual(self.externalEnds(ext), ends(V(10, 0, 0)))
        part.Placement = App.Placement(V(0, 0, 8), App.Rotation())
        self.doc.recompute()
        self.assertEqual(self.externalEnds(ext), ends(V(10, 0, 3)))
        b.Placement = App.Placement()
        self.doc.recompute()
        self.assertEqual(self.externalEnds(ext), ends(V(0, 0, 3)))
        self.assertSettled()

    def testPlacerOutsideEveryBody(self):
        """ops#325 (1b-2, PR 300 review low 1): a pattern's Direction on an edge of a sketch
        outside every Body was read in the pattern's Body frame: with the Body turned 90 degrees
        about Z the copies went along the Body's X, global Y, instead of the sketch's line along
        global X. Such a placer is placed by its container (the document's root, an App::Part):
        the pattern fails while that container is placed elsewhere than its Body, and not at one
        origin. Model: A, a 10 mm cube at the origin, patterned twice 20 along the edge (0,0,0)-
        (10,0,0) of Dir, a sketch at the document's root."""
        a = self.doc.addObject("PartDesign::Body", "A")
        cube = pad(a, "Cube", sketch(a, "SA", xyPlane(a), (0, 0, 10, 10)), 10)
        line = self.doc.addObject("Sketcher::SketchObject", "Dir")
        line.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        self.doc.recompute()
        pattern = a.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [cube]
        pattern.Direction = (line, ["Edge1"])
        pattern.Length = 20
        pattern.Occurrences = 2
        a.Tip = pattern
        self.assertSettled()

        def assertApart(where):
            self.assertFalse(pattern.isValid())
            status = pattern.getStatusString()
            self.assertIn("placed elsewhere", status)
            self.assertIn("Direction of this feature is in " + where, status)

        def assertAlong():
            self.assertTrue(pattern.isValid(), pattern.getStatusString())
            self.assertAlmostEqual(pattern.Shape.Volume, 2000, places=6)
            box = globalBox(pattern)
            self.assertAlmostEqual(box[3] - box[0], 30, places=6)  # along global X
            self.assertAlmostEqual(box[4] - box[1], 10, places=6)

        assertAlong()
        a.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), 90))
        self.doc.recompute()
        assertApart("the document's root")
        a.Placement = App.Placement()
        self.doc.recompute()
        assertAlong()

        holder = self.doc.addObject("App::Part", "Holder")
        holder.addObject(line)
        self.doc.recompute()
        assertAlong()
        holder.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        self.doc.recompute()
        assertApart(holder.Label)
        holder.addObject(a)  # one origin again
        self.doc.recompute()
        assertAlong()
        self.assertSettled()
