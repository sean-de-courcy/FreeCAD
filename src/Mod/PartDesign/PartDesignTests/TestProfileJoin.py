# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH, ops#1149: a sketch curve drawn in pieces is one profile edge, so one wall, as Onshape's.
# Design: the ops repo's notes/extrude-join-profile-edges-1149.md (the row numbers below are its
# cases). Designed geometry only; F, E, V counted by hand (a prism of a profile with n edges has
# 3n edges and 2n vertices), volumes against the same outline drawn in one piece.

import math
import unittest

import FreeCAD
import Part

from PartDesignTests.Scenarios import models

V = FreeCAD.Vector
A, B = 10.0, 6.0  # the ellipse's radii
H = 4.0  # the pads' length


def ellipse(major=(A, 0), center=(0, 0)):
    """An ellipse of radii A and B whose major axis points to `major` from `center`."""
    cx, cy = center
    mx, my = major
    length = math.hypot(mx, my)
    ux, uy = mx / length, my / length
    return Part.Ellipse(V(cx + A * ux, cy + A * uy, 0), V(cx - B * uy, cy + B * ux, 0), V(cx, cy, 0))


def arcs(curve, cuts):
    """The curve's arcs between the parameters `cuts`, in order."""
    return [Part.ArcOfEllipse(curve, a, b) if isinstance(curve, Part.Ellipse) else Part.ArcOfCircle(curve, a, b)
            for a, b in zip(cuts, cuts[1:])]


def counts(shape):
    return len(shape.Faces), len(shape.Edges), len(shape.Vertexes)


class TestProfileJoin(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PartDesignTestProfileJoin")
        self.body = models.body(self.doc)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def pad(self, geometry, construction=(), refine=True, length=H, taper=0.0, name="Sk"):
        sketch = models.sketch(self.doc, name, geometry, self.body)
        for line in construction:
            sketch.addGeometry(line, True)
        pad = models.pad(self.body, sketch, length)
        pad.Refine = refine
        pad.TaperAngle = taper
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        return pad

    def oneSolid(self, feature):
        self.assertEqual(len(feature.Shape.Solids), 1)
        return feature.Shape

    def test1WholeEllipseInTwoArcs(self):
        """Row 1: a whole ellipse drawn as two arcs is one closed edge: F 3, E 3, V 2."""
        shape = self.oneSolid(self.pad(arcs(ellipse(), [0, math.pi, 2 * math.pi])))
        self.assertEqual(counts(shape), (3, 3, 2))
        self.assertAlmostEqual(shape.Volume, math.pi * A * B * H, delta=1e-6)

    def test2EllipticalArcInTwoPiecesWithAChord(self):
        """Row 2 (the Atrium's form): an elliptical arc in two pieces closed by a chord, a
        construction line ending at the joint: F 4, E 6, V 4."""
        geometry = arcs(ellipse(), [0, math.pi / 2, math.pi]) + [Part.LineSegment(V(-A, 0, 0), V(A, 0, 0))]
        shape = self.oneSolid(self.pad(geometry, construction=[Part.LineSegment(V(0, B, 0), V(0, -5, 0))]))
        self.assertEqual(counts(shape), (4, 6, 4))
        self.assertAlmostEqual(shape.Volume, math.pi * A * B * H / 2, delta=1e-6)

    def test2rOneRoundAlongTheJoinedWall(self):
        """Row 2r (ops#1149's done-when model): a round on the elliptical wall's bottom edge is one
        face: F 5 (integration: two rounds, F 7)."""
        geometry = arcs(ellipse(), [0, math.pi / 2, math.pi]) + [Part.LineSegment(V(-A, 0, 0), V(A, 0, 0))]
        pad = self.pad(geometry)
        edges = [i + 1 for i, e in enumerate(pad.Shape.Edges)
                 if isinstance(e.Curve, Part.Ellipse) and e.BoundBox.ZMax < 1e-6]
        self.assertEqual(len(edges), 1)
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, ["Edge%d" % i for i in edges])
        fillet.Radius = 1.0
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(len(fillet.Shape.Faces), 5)

    def test2aTheArcsDrawnOtherwise(self):
        """Row 2a: the arcs' major axes opposite, the pieces drawn in opposite directions, in the
        other order, and on a rotated sketch: as row 2."""
        chord = Part.LineSegment(V(-A, 0, 0), V(A, 0, 0))
        forms = {
            "opposite axes": [Part.ArcOfEllipse(ellipse(), 0, math.pi / 2),
                              Part.ArcOfEllipse(ellipse(major=(-A, 0)), -math.pi / 2, 0), chord],
            "other order": list(reversed(arcs(ellipse(), [0, math.pi / 2, math.pi]))) + [chord],
        }
        for name, geometry in forms.items():
            with self.subTest(form=name):
                shape = self.oneSolid(self.pad(geometry, name="Sk" + name.replace(" ", "")))
                self.assertEqual(counts(shape), (4, 6, 4))
                self.body.removeObject(self.body.Tip)

    def test3WholeCircleInTwoAndThreeArcs(self):
        """Row 3: a whole circle in two arcs, and in three: F 3, E 3, V 2."""
        circle = models.circle(0, 0, 5)
        for cuts in ([0, math.pi, 2 * math.pi], [0, 2, 4, 2 * math.pi]):
            with self.subTest(pieces=len(cuts) - 1):
                shape = self.oneSolid(self.pad(arcs(circle, cuts), name="Sk%d" % len(cuts)))
                self.assertEqual(counts(shape), (3, 3, 2))
                self.assertAlmostEqual(shape.Volume, math.pi * 25 * H, delta=1e-6)
                self.body.removeObject(self.body.Tip)

    def test3rRoundOnTheRimIsOneTorusFace(self):
        """Row 3r: a round on the top rim of a two-arc circle pad: F 4."""
        pad = self.pad(arcs(models.circle(0, 0, 5), [0, math.pi, 2 * math.pi]))
        edges = [i + 1 for i, e in enumerate(pad.Shape.Edges) if e.BoundBox.ZMin > H - 1e-6]
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, ["Edge%d" % i for i in edges])
        fillet.Radius = 1.0
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(len(fillet.Shape.Faces), 4)

    def test3tTaperOnAClosedChain(self):
        """Row 3t: rows 1 and 3 with a taper of 5 degrees: the faces and the volume of the curve
        drawn in one piece (a tapered ellipse's wall is 4 B-spline faces even then)."""
        for name, pieces, whole in (
            ("circle", arcs(models.circle(0, 0, 5), [0, math.pi, 2 * math.pi]), [models.circle(0, 0, 5)]),
            ("ellipse", arcs(ellipse(), [0, math.pi, 2 * math.pi]), [ellipse()]),
        ):
            with self.subTest(curve=name):
                one = self.oneSolid(self.pad(whole, taper=5.0, name="One" + name))
                faces, volume = len(one.Faces), one.Volume
                self.body.removeObject(self.body.Tip)
                shape = self.oneSolid(self.pad(pieces, taper=5.0, name="Two" + name))
                self.assertEqual(len(shape.Faces), faces)
                self.assertAlmostEqual(shape.Volume, volume, delta=1e-6 * volume)
                self.body.removeObject(self.body.Tip)

    def test4DInTwoPieces(self):
        """Row 4: a D, a circular arc in two pieces and a chord: F 4, E 6, V 4."""
        geometry = arcs(models.circle(0, 0, 5), [0, math.pi / 2, math.pi]) + [Part.LineSegment(V(-5, 0, 0), V(5, 0, 0))]
        shape = self.oneSolid(self.pad(geometry))
        self.assertEqual(counts(shape), (4, 6, 4))

    def test5SideInCollinearLines(self):
        """Rows 5 and 5c: a rectangle with one side in two, or three, collinear lines: F 6, E 12,
        V 8, with Refine on and off."""
        for cuts in ([0, 4, 10], [0, 3, 7, 10]):
            bottom = [Part.LineSegment(V(a, 0, 0), V(b, 0, 0)) for a, b in zip(cuts, cuts[1:])]
            rest = models.polyline([(10, 0), (10, 5), (0, 5), (0, 0)])
            for refine in (False, True):
                with self.subTest(pieces=len(bottom), refine=refine):
                    shape = self.oneSolid(self.pad(bottom + rest, refine=refine, name="Sk%d%d" % (len(bottom), refine)))
                    self.assertEqual(counts(shape), (6, 12, 8))
                    self.body.removeObject(self.body.Tip)

    def test5sMetreScaleWithAShortPiece(self):
        """Row 5s: at 10 m, a 1 mm piece beside a long one on one line: as row 5 (Refine off)."""
        s = 10000.0
        geometry = [Part.LineSegment(V(0, 0, 0), V(1, 0, 0)), Part.LineSegment(V(1, 0, 0), V(s, 0, 0))]
        geometry += models.polyline([(s, 0), (s, 5000), (0, 5000), (0, 0)])
        shape = self.oneSolid(self.pad(geometry, refine=False, length=100))
        self.assertEqual(counts(shape), (6, 12, 8))

    def test7NotOneCurve(self):
        """Rows 7a and 7c: a stadium (lines tangent to arcs) and two arcs of radius 5 whose centres
        are 1e-5 apart stay as drawn."""
        r = 5.0
        stadium = [Part.LineSegment(V(0, -r, 0), V(10, -r, 0)),
                   Part.ArcOfCircle(models.circle(10, 0, r), -math.pi / 2, math.pi / 2),
                   Part.LineSegment(V(10, r, 0), V(0, r, 0)),
                   Part.ArcOfCircle(models.circle(0, 0, r), math.pi / 2, 3 * math.pi / 2)]
        shape = self.oneSolid(self.pad(stadium, refine=False))
        self.assertEqual(len(shape.Faces), 6)
        self.body.removeObject(self.body.Tip)
        # the lower arc through the upper one's ends, its centre 1e-5 above: two walls
        d = 1e-5
        lower = Part.Circle(V(0, d, 0), V(0, 0, 1), math.hypot(r, d))
        off = [Part.ArcOfCircle(models.circle(0, 0, r), 0, math.pi),
               Part.ArcOfCircle(lower, math.atan2(-d, -r), math.atan2(-d, r))]
        shape = self.oneSolid(self.pad(off, name="SkOff"))
        self.assertEqual(len(shape.Faces), 4)

    def test8aConstructionThroughBothJoints(self):
        """Row 8a: row 1 with a construction line through both joints: F 3."""
        construction = [Part.LineSegment(V(-A - 2, 0, 0), V(A + 2, 0, 0))]
        shape = self.oneSolid(self.pad(arcs(ellipse(), [0, math.pi, 2 * math.pi]), construction=construction))
        self.assertEqual(counts(shape), (3, 3, 2))

    def test9aPlateWithATwoArcHole(self):
        """Row 9a: a rectangular plate with a hole drawn as two arcs: F 7, E 15."""
        geometry = models.rectangle(-20, -20, 20, 20) + arcs(models.circle(0, 0, 5), [0, math.pi, 2 * math.pi])
        shape = self.oneSolid(self.pad(geometry))
        self.assertEqual(counts(shape)[:2], (7, 15))

    def test10PocketOfATwoArcEllipse(self):
        """Row 10: row 1 as a pocket through a block: the hole is one wall face."""
        block = self.pad(models.rectangle(-20, -20, 20, 20), length=10, name="Block")
        sketch = models.sketch(self.doc, "Hole", arcs(ellipse(), [0, math.pi, 2 * math.pi]), self.body, z=10)
        pocket = models.pocketThroughAll(self.body, sketch)
        pocket.Refine = True
        self.doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertEqual(len(pocket.Shape.Faces), 7)
        self.assertAlmostEqual(pocket.Shape.Volume, block.Shape.Volume - math.pi * A * B * 10, delta=1e-5)

    def test11TaperOnRow4(self):
        """Row 11: row 4 (a circular D in two pieces) with a taper of 5 degrees: one wall per joined
        edge, F 4. Row 2's elliptical D with a taper is refused on integration too ("command not
        done"): not this change's."""
        geometry = arcs(models.circle(0, 0, 5), [0, math.pi / 2, math.pi]) + [Part.LineSegment(V(-5, 0, 0), V(5, 0, 0))]
        shape = self.oneSolid(self.pad(geometry, taper=5.0))
        self.assertEqual(len(shape.Faces), 4)
