# SPDX-License-Identifier: LGPL-2.1-or-later

"""The time limit for a feature's geometry (FreeCAD-CH kernel safety S1).

A fillet or a boolean on a face with many edges runs for seconds to minutes in OCCT, and nothing
could stop it. Now it runs on a worker under the time limit ("GeometryTimeLimit" in
Mod/Part/General), and a call over it fails its feature with a clear error; the document stays
consistent (undo, a recompute with a longer limit). Designed models: a plate whose top carries a
wavy cut of n segments, and a cut of a plate by the wavy prism of 800 segments (about 2.5 s on the
reference machine, 2026-11). OCCT's fillet of the plate's outer edges takes about 1.3 s for
n = 2400 and 3 s for n = 4000, and the feature's work before it about 0.1 s and 0.2 s; the limits
in the tests sit between the two, with room for a machine twice as fast or slow.
"""

import math
import time
import unittest

import FreeCAD
import Part

V = FreeCAD.Vector
PARAMS = "User parameter:BaseApp/Preferences/Mod/Part/General"


def wavy(n, cx, cy, z, r0=8.0, amp=1.0, lobes=12):
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        r = r0 + amp * math.sin(lobes * a)
        pts.append(V(cx + r * math.cos(a), cy + r * math.sin(a), z))
    pts.append(pts[0])
    return Part.Face(Part.makePolygon(pts))


def mid(edge):
    return edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))


def outer_top_edges(shape):
    names = []
    for i, e in enumerate(shape.Edges):
        m = mid(e)
        if abs(m.z - 5) < 1e-6 and (
            abs(m.x) < 1e-6 or abs(m.x - 60) < 1e-6 or abs(m.y) < 1e-6 or abs(m.y - 60) < 1e-6
        ):
            names.append("Edge%d" % (i + 1))
    return names


class KernelBudgetTest(unittest.TestCase):
    def setUp(self):
        self.params = FreeCAD.ParamGet(PARAMS)
        self.had = self.params.GetFloat("GeometryTimeLimit", -12345.0)
        self.docs = []

    def tearDown(self):
        if self.had == -12345.0:
            self.params.RemFloat("GeometryTimeLimit")
        else:
            self.params.SetFloat("GeometryTimeLimit", self.had)
        for doc in self.docs:
            FreeCAD.closeDocument(doc.Name)
        # The abandoned workers end on their own (the fillet in about 1.6 s): none may be left
        deadline = time.time() + 120
        while Part.kernelBudget()["abandonedRunning"] and time.time() < deadline:
            time.sleep(0.2)
        self.assertEqual(Part.kernelBudget()["abandonedRunning"], 0)

    def setLimit(self, seconds):
        self.params.SetFloat("GeometryTimeLimit", seconds)

    def lid(self, n):
        doc = FreeCAD.newDocument("KernelBudgetLid")
        self.docs.append(doc)
        base = doc.addObject("Part::Feature", "Lid")
        base.Shape = Part.makeBox(60, 60, 5).cut(wavy(n, 30, 30, 4.0).extrude(V(0, 0, 2)))
        body = doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = base
        doc.recompute()
        return doc, body

    def testDefaultLimit(self):
        self.params.RemFloat("GeometryTimeLimit")
        self.assertEqual(Part.kernelBudget()["limit"], 60.0)

    def testFilletOverTheLimitFails(self):
        doc, body = self.lid(2400)
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (body.BaseFeature, outer_top_edges(body.BaseFeature.Shape))
        fillet.Radius = 1.0
        self.setLimit(0.5)
        start = time.perf_counter()
        doc.recompute()
        elapsed = time.perf_counter() - start
        self.assertFalse(fillet.isValid())
        self.assertIn("took longer than 0.5 s", fillet.getStatusString())
        self.assertIn("the feature is not built", fillet.getStatusString())
        # The failed feature passes its base through
        self.assertAlmostEqual(body.Shape.Volume, body.BaseFeature.Shape.Volume, places=6)
        # A longer limit builds it, and undo works around it
        self.setLimit(60)
        fillet.touch()
        start = time.perf_counter()
        doc.recompute()
        built = time.perf_counter() - start
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        # It returned at the limit, not when OCCT finished: well before the whole build's time on
        # this machine, under its load now (an absolute 1.2 s failed by 0.03 s during a build)
        self.assertLess(elapsed, 0.6 * built, (elapsed, built))
        self.assertLess(fillet.Shape.Volume, body.BaseFeature.Shape.Volume)

    def tool(self, doc):
        prof = doc.addObject("Part::Feature", "Profile")
        prof.Shape = wavy(800, 30, 30, -1.0)
        ext = doc.addObject("Part::Extrusion", "Tool")
        ext.Base = prof
        ext.DirMode = "Custom"
        ext.Dir = V(0, 0, 1)
        ext.LengthFwd = 7
        ext.Solid = True
        return prof, ext

    def testOnlyPartDesignFeaturesHaveTheLimit(self):
        """The limit is PartDesign features' (the ruling of 11-11): a Part::Cut over it, as an
        Arch/BIM object's boolean (bimtests.TestArchCovering), runs to its end; a Pocket of the
        same profile into the same plate stops at it."""
        doc = FreeCAD.newDocument("KernelBudgetCut")
        self.docs.append(doc)
        box = doc.addObject("Part::Box", "Plate")
        box.Length = box.Width = 60
        box.Height = 5
        prof, ext = self.tool(doc)
        doc.recompute()
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base = box
        cut.Tool = ext
        self.setLimit(0.3)
        doc.recompute()
        self.assertTrue(cut.isValid(), cut.getStatusString())
        self.assertLess(cut.Shape.Volume, 60 * 60 * 5 - 100)

        body = doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = box
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = (prof, ["Face1"])
        # Length, not ThroughAll: a symmetric through-all pocket of this profile takes minutes
        # (kernel-11's find, its own item); this one about as long as the cut
        pocket.Type = "Length"
        pocket.Length = 20
        pocket.Midplane = True
        start = time.perf_counter()
        doc.recompute()
        elapsed = time.perf_counter() - start
        self.assertFalse(pocket.isValid())
        self.assertIn("took longer than", pocket.getStatusString())
        # A boolean reads the document's shapes: it is waited for until OCCT reads the cancel
        # (it is not abandoned), so it returns after the limit but before the cut would end alone
        self.assertLess(elapsed, 10)
        # The rest of the document goes on: a new box computes
        other = doc.addObject("Part::Box", "Other")
        doc.recompute()
        self.assertTrue(other.isValid())
        self.setLimit(60)
        pocket.touch()
        doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(pocket.Shape.Volume, cut.Shape.Volume, delta=1e-6 * cut.Shape.Volume)

    def testShortCallsUnderTheLimit(self):
        # Ordinary features are unaffected by a short limit
        self.setLimit(5)
        doc = FreeCAD.newDocument("KernelBudgetShort")
        self.docs.append(doc)
        box = doc.addObject("Part::Box", "Box")
        cyl = doc.addObject("Part::Cylinder", "Cyl")
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = box, cyl
        doc.recompute()
        self.assertTrue(cut.isValid(), cut.getStatusString())
        self.assertAlmostEqual(cut.Shape.Volume, 1000 - math.pi * 4 * 10 / 4, places=6)

    def testAbandonedWorkersDoNotDisturbLaterWork(self):
        # Five fillets stopped at the limit and abandoned, then ordinary modelling in the same
        # process. The limits climb so that on a slow machine the later ones still start
        doc, body = self.lid(4000)
        names = outer_top_edges(body.BaseFeature.Shape)
        fillets = []
        for k in range(5):
            self.setLimit(0.4 + 0.3 * k)
            f = body.newObject("PartDesign::Fillet", "Fillet%d" % k)
            f.Base = (body.BaseFeature, names)
            f.Radius = 1.0
            doc.recompute()
            self.assertFalse(f.isValid())
            self.assertIn("took longer than", f.getStatusString())
            fillets.append(f)
        self.assertGreaterEqual(Part.kernelBudget()["abandonedTotal"], 1)
        self.setLimit(60)
        doc2 = FreeCAD.newDocument("KernelBudgetAfter")
        self.docs.append(doc2)
        b2 = doc2.addObject("PartDesign::Body", "Body")
        plate = doc2.addObject("Part::Feature", "Plate")
        plate.Shape = Part.makeBox(40, 30, 10)
        b2.BaseFeature = plate
        prof = doc2.addObject("Part::Feature", "Hole")
        prof.Shape = Part.Face(Part.Wire(Part.makeCircle(4, V(20, 15, 10))))
        pocket = b2.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = (prof, ["Face1"])
        pocket.Type = "ThroughAll"
        doc2.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(pocket.Shape.Volume, 12000 - math.pi * 16 * 10, places=6)


    def testScriptThatSwallowsTheStopFails(self):
        """A PartDesign Python feature whose execute() catches the stopped cut and goes on
        (BIM-style: skip a subtraction that fails) would pass the plate without its hole as a
        valid result. The stop fails the feature, whatever its code does with the error
        (kernel-4). A Part::FeaturePython has no limit (only PartDesign features do): the same
        code builds the hole."""

        class Holes:
            def __init__(self, obj):
                obj.Proxy = self

            def execute(self, obj):
                shape = Part.makeBox(60, 60, 5)
                try:
                    shape = shape.cut(wavy(800, 30, 30, -1.0).extrude(V(0, 0, 7)))
                except Exception:
                    pass
                obj.Shape = shape

        doc = FreeCAD.newDocument("KernelBudgetSwallow")
        self.docs.append(doc)
        body = doc.addObject("PartDesign::Body", "Body")
        holes = body.newObject("PartDesign::FeaturePython", "Holes")
        Holes(holes)
        loose = doc.addObject("Part::FeaturePython", "LooseHoles")
        Holes(loose)
        self.setLimit(0.3)
        doc.recompute()
        self.assertFalse(holes.isValid())
        self.assertIn("took longer than", holes.getStatusString())
        self.assertTrue(loose.isValid(), loose.getStatusString())
        self.assertLess(loose.Shape.Volume, 60 * 60 * 5 - 100)
        self.setLimit(60)
        holes.touch()
        doc.recompute()
        self.assertTrue(holes.isValid(), holes.getStatusString())
        self.assertLess(holes.Shape.Volume, 60 * 60 * 5 - 100)

def circle_wire(cx, cy, r, reverse=True):
    w = Part.Wire([Part.makeCircle(r, V(cx, cy, 0), V(0, 0, 1))])
    return w.reversed() if reverse else w


def holed_face(holes, side=100.0):
    """A square plate face with the given hole wires: Part.Face(surface, wires) keeps them as given"""
    outer = Part.makePolygon([V(0, 0, 0), V(side, 0, 0), V(side, side, 0), V(0, side, 0), V(0, 0, 0)])
    return Part.Face(Part.Plane(), [outer] + holes)


def grid_holes(n, side=100.0, r=1.0):
    step = side / n
    return [circle_wire(step * (i + 0.5), step * (j + 0.5), r) for i in range(n) for j in range(n)]


class KernelCheckTest(unittest.TestCase):
    """Part.kernelCheck, the shape check of kernel safety (kernel-9, ops#640): BRepCheck_Analyzer's
    verdict, in time that grows with a face's holes and not with their square. OCCT 8.0.1 compares
    each two wires of a face: a plate with 3600 holes took about 25 s per face, and a Pocket of 25
    squares into it passed the 60 s limit, where Onshape builds such cuts in seconds. Designed
    faces with many holes, each wrong in one
    way the face check finds: the verdicts must be BRepCheck_Analyzer's. 18 x 18 = 324 holes, past the
    300 wires where the check goes by parts (batches of 30 holes, then pairs of batches)."""

    def verdicts(self, shape):
        """kernelCheck's and BRepCheck_Analyzer's (Shape.check: isValid uses kernelCheck now)"""
        try:
            shape.check()
            analyzer = True
        except ValueError:
            analyzer = False
        return Part.kernelCheck(shape), analyzer

    def testValidFaceWithManyHoles(self):
        face = holed_face(grid_holes(18))
        self.assertEqual(self.verdicts(face), (True, True))

    def testCrossingHolesFail(self):
        c = 100.0 / 18 / 2
        holes = grid_holes(18)
        holes.append(circle_wire(c + 1.5, c, 1.0))  # crosses the first hole, in another batch
        self.assertEqual(self.verdicts(holed_face(holes)), (False, False))
        holes = grid_holes(18)
        holes.insert(1, circle_wire(c + 1.5, c, 1.0))  # the same, in the first hole's batch
        self.assertEqual(self.verdicts(holed_face(holes)), (False, False))

    def testNestedHoleFails(self):
        c = 100.0 / 18 / 2
        holes = grid_holes(18, r=2.0)
        holes.append(circle_wire(c, c, 0.5))  # inside the first hole
        self.assertEqual(self.verdicts(holed_face(holes)), (False, False))

    def testHoleOutsideFails(self):
        holes = grid_holes(18)
        holes.append(circle_wire(150.0, 50.0, 1.0))
        self.assertEqual(self.verdicts(holed_face(holes)), (False, False))

    def testHoleTurnedTheWrongWayFails(self):
        holes = grid_holes(18)
        holes[200] = holes[200].reversed()
        self.assertEqual(self.verdicts(holed_face(holes)), (False, False))

    def testValidSolidWithManyHoles(self):
        solid = holed_face(grid_holes(18)).extrude(V(0, 0, 5))
        self.assertEqual(self.verdicts(solid), (True, True))
        self.assertEqual(self.verdicts(Part.makeCompound([solid])), (True, True))

    def testSolidWithAFaceTurnedFails(self):
        solid = holed_face(grid_holes(18)).extrude(V(0, 0, 5))
        faces = solid.Faces
        faces[0] = faces[0].reversed()
        broken = Part.Solid(Part.Shell(faces))
        self.assertEqual(self.verdicts(broken), (False, False))

    def testThousandsOfHolesInSeconds(self):
        """2500 holes: by parts a few seconds on the reference machine (2026-11), where
        BRepCheck_Analyzer took minutes"""
        solid = holed_face(grid_holes(50, r=0.5)).extrude(V(0, 0, 5))
        start = time.time()
        self.assertTrue(Part.kernelCheck(solid))
        self.assertLess(time.time() - start, 20.0)

if __name__ == "__main__":
    unittest.main()
