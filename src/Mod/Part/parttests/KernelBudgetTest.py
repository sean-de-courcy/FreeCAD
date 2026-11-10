# SPDX-License-Identifier: LGPL-2.1-or-later

"""The time limit for a feature's geometry (FreeCAD-CH kernel safety S1).

A fillet or a boolean on a face with many edges runs for seconds to minutes in OCCT, and nothing
could stop it. Now it runs on a worker under the time limit ("GeometryTimeLimit" in
Mod/Part/General), and a call over it fails its feature with a clear error; the document stays
consistent (undo, a recompute with a longer limit). Designed models: a plate whose top carries a
wavy cut of 800 segments (a fillet of its outer edges takes about 1.6 s, a cut by the wavy tool
about 3 s on the reference machine); the limit in the tests is 0.3 s.
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

    def lid(self):
        doc = FreeCAD.newDocument("KernelBudgetLid")
        self.docs.append(doc)
        base = doc.addObject("Part::Feature", "Lid")
        base.Shape = Part.makeBox(60, 60, 5).cut(wavy(800, 30, 30, 4.0).extrude(V(0, 0, 2)))
        body = doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = base
        doc.recompute()
        return doc, body

    def testDefaultLimit(self):
        self.params.RemFloat("GeometryTimeLimit")
        self.assertEqual(Part.kernelBudget()["limit"], 60.0)

    def testFilletOverTheLimitFails(self):
        doc, body = self.lid()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (body.BaseFeature, outer_top_edges(body.BaseFeature.Shape))
        fillet.Radius = 1.0
        self.setLimit(0.3)
        start = time.perf_counter()
        doc.recompute()
        elapsed = time.perf_counter() - start
        self.assertFalse(fillet.isValid())
        self.assertIn("took longer than 0.3 s", fillet.getStatusString())
        self.assertIn("the feature is not built", fillet.getStatusString())
        # It returned at the limit, not when OCCT finished
        self.assertLess(elapsed, 1.2)
        # The failed feature passes its base through
        self.assertAlmostEqual(body.Shape.Volume, body.BaseFeature.Shape.Volume, places=6)
        # A longer limit builds it, and undo works around it
        self.setLimit(60)
        fillet.touch()
        doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertLess(fillet.Shape.Volume, body.BaseFeature.Shape.Volume)

    def testCutOverTheLimitFails(self):
        doc = FreeCAD.newDocument("KernelBudgetCut")
        self.docs.append(doc)
        box = doc.addObject("Part::Box", "Plate")
        box.Length = box.Width = 60
        box.Height = 5
        prof = doc.addObject("Part::Feature", "Profile")
        prof.Shape = wavy(800, 30, 30, -1.0)
        ext = doc.addObject("Part::Extrusion", "Tool")
        ext.Base = prof
        ext.DirMode = "Custom"
        ext.Dir = V(0, 0, 1)
        ext.LengthFwd = 7
        ext.Solid = True
        doc.recompute()
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base = box
        cut.Tool = ext
        self.setLimit(0.3)
        start = time.perf_counter()
        doc.recompute()
        elapsed = time.perf_counter() - start
        self.assertFalse(cut.isValid())
        self.assertIn("took longer than", cut.getStatusString())
        # A boolean reads the document's shapes: it is waited for until OCCT reads the cancel
        # (it is not abandoned), so it returns after the limit but before the cut would end alone
        self.assertLess(elapsed, 10)
        # The rest of the document goes on: a new box computes
        other = doc.addObject("Part::Box", "Other")
        doc.recompute()
        self.assertTrue(other.isValid())
        self.setLimit(60)
        cut.touch()
        doc.recompute()
        self.assertTrue(cut.isValid(), cut.getStatusString())

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
        # Five abandoned fillets, then ordinary modelling in the same process
        doc, body = self.lid()
        self.setLimit(0.2)
        names = outer_top_edges(body.BaseFeature.Shape)
        fillets = []
        for k in range(5):
            f = body.newObject("PartDesign::Fillet", "Fillet%d" % k)
            f.Base = (body.BaseFeature, names)
            f.Radius = 1.0
            doc.recompute()
            self.assertFalse(f.isValid())
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


if __name__ == "__main__":
    unittest.main()
