# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#1060)

"""A repaired fillet names the two arcs of a split hole rim the same way at every recompute.

When OCCT's fillet result is invalid, the dress-up repairs it with TopoShape::fix() (ShapeFix) and
names what the repair changed (op MAK). Where the repair cuts a closed edge, a hole's rim, into two
arcs, the arcs are twins of one closed source edge and are numbered `0of2` / `1of2` in the order the
mapper lists them. ShapeFix's history lists them in an order that is not repeatable, so the names
swapped between recomputes of an unchanged model (ops#1060); fix() now lists them in the repaired
shape's own sub-shape order.

Designed geometry: a 40 x 40 x 10 box with a through hole of radius 5 whose axis is 11 from the
box's x = 0 side; the top edge on x = 0 is filleted with radius 6, so the round's rail on the top
face (x = 6) is tangent to the hole's rim. OCCT's fillet is invalid there and the repair splits the
rim in two arcs. Expected, geometric: the result is the same solid at every recompute, so the upper
arc (larger y at its middle) and the lower arc each keep one name over every recompute.
"""

import unittest

import FreeCAD as App

RECOMPUTES = 16


class TestFixTwinOrder(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestFixTwinOrder")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def makeFillet(self):
        body = self.doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length, box.Width, box.Height = 40, 40, 10
        hole = body.newObject("PartDesign::SubtractiveCylinder", "Hole")
        hole.Radius, hole.Height = 5, 30
        hole.Placement = App.Placement(App.Vector(11, 20, -10), App.Rotation())
        self.doc.recompute()
        pick = None
        for i, e in enumerate(hole.Shape.Edges, 1):
            if len(e.Vertexes) == 2 and all(
                abs(v.X) < 1e-9 and abs(v.Z - 10) < 1e-9 for v in e.Vertexes
            ):
                pick = "Edge%d" % i
        self.assertIsNotNone(pick, "the box's top edge on x = 0")
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (hole, [pick])
        fillet.Radius = 6
        self.doc.recompute()
        return fillet

    def rimArcNames(self, shape):
        arcs = {}
        for i, e in enumerate(shape.Edges, 1):
            name = shape.getElementName("Edge%d" % i, 1)
            if "CLS" in name:
                mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
                arcs["upper" if mid.y > 20 else "lower"] = name
        return arcs

    def testRepairedRimArcsKeepTheirNames(self):
        fillet = self.makeFillet()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        first = self.rimArcNames(fillet.Shape)
        # the repair split the rim: two twins of the closed rim, one above and one below y = 20
        self.assertEqual(sorted(first), ["lower", "upper"], first)
        self.assertNotEqual(first["upper"], first["lower"])
        for k in range(RECOMPUTES):
            fillet.touch()
            fillet.recompute()
            self.assertTrue(fillet.isValid(), fillet.getStatusString())
            self.assertEqual(self.rimArcNames(fillet.Shape), first, "recompute %d" % (k + 1))
