# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: a sketch's profile as Onshape's regions (feat/profile-regions).
#
# Onshape's rule (notes/profile-regions.md): a sketch's regions are the bounded faces of the
# arrangement of its solid curves, plus the model edges lying in its plane (imprint). A feature
# takes one region, several, or the whole sketch; the whole sketch is every region of the
# sketch's own curves except those enclosed by curves that touch the outer boundary of all the
# regions nowhere (filterInnerLoops). Every case is designed geometry with a geometric expectation; a Pad of
# length 1 on XY has the profile's area as its volume.

import math
import os
import time
import unittest

import FreeCAD
import Part
import Sketcher

V = FreeCAD.Vector
TOL = 1e-6


def xyPlane(body):
    return [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]


def rect(sketch, x0, y0, x1, y1, construction=False):
    """A closed rectangle of four lines joined by coincidences; returns its first geometry index."""
    p = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    first = sketch.GeometryCount
    for k in range(4):
        sketch.addGeometry(Part.LineSegment(p[k], p[(k + 1) % 4]), construction)
    for k in range(4):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", first + k, 2, first + (k + 1) % 4, 1)
        )
    return first


def dimensionedRect(sketch, x0, y0, w, h):
    """A rectangle fully constrained by its lower left corner (x0, y0) and its size; returns
    the indices of the four datums (x0, y0, w, h)."""
    first = rect(sketch, x0, y0, x0 + w, y0 + h)
    sketch.addConstraint(Sketcher.Constraint("Horizontal", first))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", first + 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", first + 1))
    sketch.addConstraint(Sketcher.Constraint("Vertical", first + 3))
    datums = []
    datums.append(sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, first, 1, x0)))
    datums.append(sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, first, 1, y0)))
    datums.append(sketch.addConstraint(Sketcher.Constraint("DistanceX", first, 1, first, 2, w)))
    datums.append(
        sketch.addConstraint(Sketcher.Constraint("DistanceY", first + 1, 1, first + 1, 2, h))
    )
    return datums


def regionName(sketch, area, x=None, y=None):
    """The InternalFace name of the one region with this area (and centre, when given)."""
    found = []
    for i, f in enumerate(sketch.InternalShape.Faces):
        if abs(f.Area - area) > 1e-6 * max(1.0, area):
            continue
        c = f.CenterOfMass
        if x is not None and abs(c.x - x) > 1e-6:
            continue
        if y is not None and abs(c.y - y) > 1e-6:
            continue
        found.append("InternalFace%d" % (i + 1))
    if len(found) != 1:
        raise AssertionError(
            "%d regions of area %g in %s: %s"
            % (len(found), area, sketch.Name, [round(f.Area, 4) for f in sketch.InternalShape.Faces])
        )
    return found[0]


class TestProfileRegions(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("TestProfileRegions")

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    # -- helpers ---------------------------------------------------------------------------

    def sketch(self, body=None, name="Sketch", support=None):
        if body is None:
            body = self.Doc.addObject("PartDesign::Body", "Body")
        sk = body.newObject("Sketcher::SketchObject", name)
        sk.AttachmentSupport = support or [(xyPlane(body), "")]
        sk.MapMode = "FlatFace"
        return body, sk

    def pad(self, body, profile, length=1, name="Pad"):
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile = profile
        pad.Length = length
        pad.Refine = False
        self.Doc.recompute()
        return pad

    def assertVolume(self, feature, volume, solids=None):
        self.assertTrue(feature.isValid(), feature.getStatusString())
        shape = feature.Shape
        self.assertFalse(shape.isNull())
        self.assertTrue(shape.isValid())
        if solids is not None:
            self.assertEqual(len(shape.Solids), solids)
        for s in shape.Solids:
            self.assertGreater(s.Volume, 0)  # never an inverted solid
        self.assertAlmostEqual(shape.Volume, volume, places=4)

    def overlapping(self, body=None):
        body, sk = self.sketch(body)
        rect(sk, 0, 0, 10, 10)
        rect(sk, 5, 5, 15, 15)
        self.Doc.recompute()
        return body, sk

    # -- the whole sketch: all regions, inner loops filtered ----------------------------------

    def testWholeSketchOverlappingLoopsIsTheUnion(self):
        """Two 10 x 10 squares overlapping by 5 x 5: three regions (L, lens, L); the whole sketch
        is their union, 175 (before: a valid Pad of volume 0)."""
        body, sk = self.overlapping()
        self.assertEqual(sorted(round(f.Area, 6) for f in sk.InternalShape.Faces), [25, 75, 75])
        self.assertVolume(self.pad(body, sk), 175, solids=1)

    def testWholeSketchNestedLoopsFillsTheOutermost(self):
        """A 20 x 20 square, a 10 x 10 one inside it, a 4 x 4 one inside that: the outer region
        with its hole, 300; the ring's and the island's outer boundaries are inner boundaries,
        so they are left out (before: frame and island, 316)."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        rect(sk, 5, 5, 15, 15)
        rect(sk, 8, 8, 12, 12)
        self.Doc.recompute()
        self.assertVolume(self.pad(body, sk), 300, solids=1)

    def testWholeSketchPlateWithHoleUnchanged(self):
        """The common case keeps its result and its element names: a 20 x 20 square with a
        10 x 10 hole is the 300 frame."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        rect(sk, 5, 5, 15, 15)
        self.Doc.recompute()
        pad = self.pad(body, sk)
        self.assertVolume(pad, 300, solids=1)
        self.assertEqual(len(pad.Shape.Faces), 10)

    def testWholeSketchLoopsSharingASide(self):
        """Two 10 x 10 squares drawn side by side, sharing the side x = 10 (each its own loop):
        one 20 x 10 solid."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 10, 10)
        rect(sk, 10, 0, 20, 10)
        self.Doc.recompute()
        self.assertVolume(self.pad(body, sk), 200, solids=1)

    def testWholeSketchLoopTouchingFromInside(self):
        """A circle of r 5 inside a 20 x 20 square, tangent to its bottom side: a loop touching
        the outer boundary is no inner loop, so the whole sketch is both regions, 400 (Onshape,
        notes/onshape-facts.md PR4; before: 321.46). The DXF lane's "hole touching the outer
        boundary pads as a boss" is this case: Onshape fills it too; the face less the hole is a
        pick of that region."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        sk.addGeometry(Part.Circle(V(10, 5, 0), V(0, 0, 1), 5), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 2)
        self.assertVolume(self.pad(body, sk), 400, solids=1)
        frame = regionName(sk, 400 - 25 * math.pi)
        self.assertVolume(self.pad(body, (sk, [frame]), name="Frame"), 400, solids=1)

    def testWholeSketchChordAcrossAHoleKeepsTheHole(self):
        """A 20 x 20 square, a circle of r 4 at its centre and a line across the circle: the
        circle's halves lie in the square's hole, so they are left out like the hole itself:
        400 - 16 pi (Onshape, PR3)."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 4), False)
        sk.addGeometry(Part.LineSegment(V(5, 10, 0), V(15, 10, 0)), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 3)
        self.assertVolume(self.pad(body, sk), 400 - 16 * math.pi, solids=1)

    def testWholeSketchLineSideToSideThroughAHoleKeepsTheHole(self):
        """A 20 x 20 square, a circle of r 4 at its centre and a line y = 10 from side to side:
        four regions (two halves 200 - 8 pi, two half discs 8 pi). The line cuts the circle into
        two arcs, each on the outer wire of a half, but the circle touches the outer boundary
        nowhere, so it is still a hole: 400 - 16 pi, one solid (Onshape, PRQ1; before: 400)."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 4), False)
        sk.addGeometry(Part.LineSegment(V(0, 10, 0), V(20, 10, 0)), False)
        self.Doc.recompute()
        self.assertEqual(
            sorted(round(f.Area, 6) for f in sk.InternalShape.Faces),
            sorted(round(a, 6) for a in (8 * math.pi, 8 * math.pi, 200 - 8 * math.pi, 200 - 8 * math.pi)),
        )
        self.assertVolume(self.pad(body, sk), 400 - 16 * math.pi, solids=1)

    def testWholeSketchSquareAcrossAHoleCornerIsLeftOutWhole(self):
        """Squares (0,0)-(20,20) and (5,5)-(15,15), and (12,12)-(18,18) across the hole's corner:
        regions 273, 91, 9 and 27. The third square touches the outer boundary nowhere, so all of
        it is left out, its part in the material too: 273, one solid (Onshape, PRQ2; before:
        300, the 27 filled)."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        rect(sk, 5, 5, 15, 15)
        rect(sk, 12, 12, 18, 18)
        self.Doc.recompute()
        self.assertEqual(sorted(round(f.Area, 6) for f in sk.InternalShape.Faces), [9, 27, 91, 273])
        self.assertVolume(self.pad(body, sk), 273, solids=1)

    def testWholeSketchLineIntoAHoleKeepsTheHole(self):
        """A 20 x 20 square, a circle of r 4 at its centre and a line from the left side to the
        circle's centre: the line touches the outer boundary, the circle does not, so the disc
        (cut by the line's end piece, still one region) is a hole: 400 - 16 pi."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 4), False)
        sk.addGeometry(Part.LineSegment(V(0, 10, 0), V(10, 10, 0)), False)
        self.Doc.recompute()
        self.assertVolume(self.pad(body, sk), 400 - 16 * math.pi, solids=1)

    def testWholeSketchCrossThroughAHoleKeepsTheHole(self):
        """PRQ1 with a second line x = 10 from side to side: eight regions, the hole kept: 400 -
        16 pi, one solid."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 4), False)
        sk.addGeometry(Part.LineSegment(V(0, 10, 0), V(20, 10, 0)), False)
        sk.addGeometry(Part.LineSegment(V(10, 0, 0), V(10, 20, 0)), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 8)
        self.assertVolume(self.pad(body, sk), 400 - 16 * math.pi, solids=1)

    def testWholeSketchHashOfOpenLinesIsAHole(self):
        """A 20 x 20 square and a hash of four lines (x = 6, 14 from y = 4 to 16; y = 6, 14 from
        x = 4 to 16), none touching the square: no closed chain of curves, but the lines touch the
        outer boundary nowhere, so the 8 x 8 centre they close is a hole: 336, one solid
        (Onshape, PRQ3)."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        for k in (6, 14):
            sk.addGeometry(Part.LineSegment(V(k, 4, 0), V(k, 16, 0)), False)
            sk.addGeometry(Part.LineSegment(V(4, k, 0), V(16, k, 0)), False)
        self.Doc.recompute()
        self.assertEqual(sorted(round(f.Area, 6) for f in sk.InternalShape.Faces), [64, 336])
        self.assertVolume(self.pad(body, sk), 336, solids=1)

    def testWholeSketchCircleTangentToALineAcrossIsAHole(self):
        """A 20 x 20 square, a line x = 10 from side to side and a circle of r 3 at (7, 10)
        touching the line from the left: the line touches the outer boundary, the circle only the
        line, so it is a hole: 400 - 9 pi, one solid (Onshape, PRQ4)."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        sk.addGeometry(Part.LineSegment(V(10, 0, 0), V(10, 20, 0)), False)
        sk.addGeometry(Part.Circle(V(7, 10, 0), V(0, 0, 1), 3), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 3)
        self.assertVolume(self.pad(body, sk), 400 - 9 * math.pi, solids=1)

    def testWholeSketchCircleTangentToASharedSideIsAHole(self):
        """Two 10 x 10 squares drawn as one chain of seven lines sharing the side x = 10, and a
        circle of r 3 at (7, 5) touching that side from the left: the shared side touches the outer
        boundary at its ends, the circle touches it only inside, so it is a hole: 200 - 9 pi
        (Onshape, PRQ5)."""
        body, sk = self.sketch()
        for p, q in (((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10)), ((0, 10), (0, 0)),
                     ((10, 0), (20, 0)), ((20, 0), (20, 10)), ((20, 10), (10, 10))):
            sk.addGeometry(Part.LineSegment(V(*p, 0), V(*q, 0)), False)
        sk.addGeometry(Part.Circle(V(7, 5, 0), V(0, 0, 1), 3), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 3)
        self.assertVolume(self.pad(body, sk), 200 - 9 * math.pi, solids=1)

    def testWholeSketchGridIsFilled(self):
        """A 30 x 30 square cut into nine cells by two lines each way, side to side: no curve
        encloses the centre cell away from the outer boundary, so all nine: 900."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 30, 30)
        for k in (10, 20):
            sk.addGeometry(Part.LineSegment(V(k, 0, 0), V(k, 30, 0)), False)
            sk.addGeometry(Part.LineSegment(V(0, k, 0), V(30, k, 0)), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 9)
        self.assertVolume(self.pad(body, sk), 900, solids=1)

    def testWholeSketchLoopCutByALine(self):
        """A 10 x 10 square crossed by a line at y = 4 running past both sides: two regions,
        40 and 60; the whole sketch is the square."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 10, 10)
        sk.addGeometry(Part.LineSegment(V(-5, 4, 0), V(15, 4, 0)), False)
        self.Doc.recompute()
        self.assertEqual(sorted(round(f.Area, 6) for f in sk.InternalShape.Faces), [40, 60])
        self.assertVolume(self.pad(body, sk), 100, solids=1)
        pad = self.pad(body, (sk, [regionName(sk, 40)]), name="Strip")
        self.assertVolume(pad, 100, solids=1)  # the strip lies inside the first pad

    def testWholeSketchOpenCurvesClosingOnlyAgainstEachOther(self):
        """Three lines, none sharing an end point: y = 0, x = 0 and x + y = 11, each running past
        the others. They close a triangle of legs 11: 60.5 (before: "no closed region")."""
        body, sk = self.sketch()
        sk.addGeometry(Part.LineSegment(V(-2, 0, 0), V(13, 0, 0)), False)
        sk.addGeometry(Part.LineSegment(V(0, -2, 0), V(0, 13, 0)), False)
        sk.addGeometry(Part.LineSegment(V(13, -2, 0), V(-2, 13, 0)), False)
        self.Doc.recompute()
        self.assertVolume(self.pad(body, sk), 60.5, solids=1)

    def testWholeSketchLineFromALoopCorner(self):
        """A line drawn from a 10 x 10 square's corner outwards (one wire with the square):
        the square (before: the pad stopped)."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 10, 10)
        sk.addGeometry(Part.LineSegment(V(10, 10, 0), V(20, 20, 0)), False)
        sk.addConstraint(Sketcher.Constraint("Coincident", 4, 1, 1, 2))
        self.Doc.recompute()
        self.assertVolume(self.pad(body, sk), 100, solids=1)

    def testWholeSketchUClosingATab(self):
        """A 20 x 20 square and a U whose ends lie on its top side: the U closes a 10 x 10 tab,
        so the whole sketch is 500 in one solid (before: the pad stopped)."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        for (x1, y1), (x2, y2) in (((5, 20), (5, 30)), ((5, 30), (15, 30)), ((15, 30), (15, 20))):
            sk.addGeometry(Part.LineSegment(V(x1, y1, 0), V(x2, y2, 0)), False)
        self.Doc.recompute()
        self.assertVolume(self.pad(body, sk), 500, solids=1)

    def testConstructionGeometryIsIgnored(self):
        """A 10 x 10 square with a construction square overlapping it and a construction line
        across it: one region, the square."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 10, 10)
        rect(sk, 5, 5, 15, 15, construction=True)
        sk.addGeometry(Part.LineSegment(V(-5, 5, 0), V(15, 5, 0)), True)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 1)
        self.assertVolume(self.pad(body, sk), 100, solids=1)

    def testOnlyOpenCurvesStillFail(self):
        """Two lines that close nothing: the pad stops with the reason."""
        body, sk = self.sketch()
        sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)), False)
        sk.addGeometry(Part.LineSegment(V(0, 5, 0), V(10, 8, 0)), False)
        self.Doc.recompute()
        pad = self.pad(body, sk)
        self.assertFalse(pad.isValid())
        self.assertIn("no closed region", pad.getStatusString())

    # -- the other features on a whole sketch -----------------------------------------------

    def testPocketWholeSketchOverlapping(self):
        """A 30 x 30 x 5 block, the two overlapping squares on its top face (at x, y + 5),
        pocketed 2 deep: 4500 - 350."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length, block.Width, block.Height = 30, 30, 5
        self.Doc.recompute()
        top = [i for i, f in enumerate(block.Shape.Faces) if abs(f.CenterOfMass.z - 5) < TOL][0]
        _, sk = self.sketch(body, support=[(block, "Face%d" % (top + 1))])
        rect(sk, 5, 5, 15, 15)
        rect(sk, 10, 10, 20, 20)
        self.Doc.recompute()
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = sk
        pocket.Length = 2
        pocket.Refine = False
        self.Doc.recompute()
        self.assertVolume(pocket, 4500 - 350, solids=1)

    def testRevolutionWholeSketchOverlapping(self):
        """The squares at x = 1..11 and 6..16 (y 0..10 and 5..15) revolved fully about the
        sketch's V axis: Pappus on the union, 2 pi (600 + 1100 - 212.5)."""
        body, sk = self.sketch()
        rect(sk, 1, 0, 11, 10)
        rect(sk, 6, 5, 16, 15)
        self.Doc.recompute()
        rev = body.newObject("PartDesign::Revolution", "Revolution")
        rev.Profile = sk
        rev.ReferenceAxis = (sk, ["V_Axis"])
        rev.Angle = 360
        rev.Refine = False
        self.Doc.recompute()
        self.assertVolume(rev, 2 * math.pi * 1487.5, solids=1)

    def testPipeWholeSketchOverlapping(self):
        """The overlapping squares swept 7 along a straight line along z: 175 x 7."""
        body, sk = self.overlapping()
        path = self.Doc.addObject("Part::Line", "Path")
        path.X1, path.Y1, path.Z1 = 0, 0, 0
        path.X2, path.Y2, path.Z2 = 0, 0, 7
        self.Doc.recompute()
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = sk
        pipe.Spine = (path, ["Edge1"])
        pipe.Refine = False
        self.Doc.recompute()
        self.assertVolume(pipe, 175 * 7, solids=1)

    def testLoftWholeSketchOverlappingStops(self):
        """A loft's sections are loops paired by order, so a section of overlapping loops is no
        section: the loft stops with a reason, never a silent solid (Onshape takes one region
        or one loop per profile)."""
        body, sk = self.overlapping()
        _, top = self.sketch(body, "Top")
        top.AttachmentOffset = FreeCAD.Placement(V(0, 0, 10), FreeCAD.Rotation())
        rect(top, 0, 0, 10, 10)
        rect(top, 5, 5, 15, 15)
        self.Doc.recompute()
        loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = sk
        loft.Sections = [top]
        self.Doc.recompute()
        if loft.isValid():
            # Accepted only if it is the union lofted straight up
            self.assertVolume(loft, 1750, solids=1)
        else:
            self.assertTrue(loft.getStatusString())

    def testLoftWholeSketchNestedLoops(self):
        """Skeptic F1: sections of three nested squares (20, 10, 4) at z 0 and 10: the rule gives
        one region with one hole, which pairs as a plate with a hole does: the frame lofted
        straight up, 3000 (before: 3160 in 2 solids, the island filled)."""
        body, sk = self.sketch()
        for k, z in enumerate((0, 10)):
            if k:
                _, sk = self.sketch(body, "Top")
                sk.AttachmentOffset = FreeCAD.Placement(V(0, 0, z), FreeCAD.Rotation())
            rect(sk, 0, 0, 20, 20)
            rect(sk, 5, 5, 15, 15)
            rect(sk, 8, 8, 12, 12)
            if not k:
                bottom = sk
        self.Doc.recompute()
        loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = bottom
        loft.Sections = [sk]
        self.Doc.recompute()
        self.assertVolume(loft, 3000, solids=1)

    def ringSketch(self, body, name, z, circleFirst, strayLine=False):
        """A 20 x 20 square with a concentric circle of r 4, at height z."""
        _, sk = self.sketch(body, name)
        sk.AttachmentOffset = FreeCAD.Placement(V(0, 0, z), FreeCAD.Rotation())
        if circleFirst:
            sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 4), False)
        rect(sk, 0, 0, 20, 20)
        if not circleFirst:
            sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 4), False)
        if strayLine:
            sk.addGeometry(Part.LineSegment(V(20, 20, 0), V(25, 25, 0)), False)
        self.Doc.recompute()
        return sk

    def testLoftPickedRingPairsWithAnotherDrawingOrder(self):
        """Review r1 (LoftPickedRingRedrawn): a loft from a picked ring region (square drawn
        first) to a whole ring sketch drawn circle first: outer to outer, hole to hole, the square
        tube 8000 - 320 pi (before the fix: a valid loft of volume 0)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        bottom = self.ringSketch(body, "Bottom", 0, circleFirst=False)
        top = self.ringSketch(body, "Top", 20, circleFirst=True)
        loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = (bottom, [regionName(bottom, 400 - 16 * math.pi)])
        loft.Sections = [top]
        self.Doc.recompute()
        self.assertVolume(loft, 8000 - 320 * math.pi, solids=1)

    def testLoftRuleRingSectionPairsWithAPlainRing(self):
        """Review r1 (T2): a ring sketch drawn circle first with a solid line from the square's
        corner (the rule makes its region, outer wire first) lofted to a plain ring drawn circle
        first: the square tube, either way round."""
        for strayBelow in (True, False):
            body = self.Doc.addObject("PartDesign::Body", "Body")
            bottom = self.ringSketch(body, "Bottom", 0, circleFirst=True, strayLine=strayBelow)
            top = self.ringSketch(body, "Top", 20, circleFirst=True, strayLine=not strayBelow)
            loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
            loft.Profile = bottom
            loft.Sections = [top]
            self.Doc.recompute()
            self.assertVolume(loft, 8000 - 320 * math.pi, solids=1)

    def testLoftSeveralPickedRegionsStop(self):
        """Review r2 (LoftTwoPickedSquaresRedrawn): a loft profile picking two separate regions
        would pair them in the picks' order with the other section's sketch order (3500 of 4000
        when one was redrawn): a loft section takes one region, and stops with the reason."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketches = []
        for name, z in (("Bottom", 0), ("Top", 20)):
            _, sk = self.sketch(body, name)
            sk.AttachmentOffset = FreeCAD.Placement(V(0, 0, z), FreeCAD.Rotation())
            rect(sk, 0, 0, 10, 10)
            rect(sk, 20, 0, 30, 10)
            sketches.append(sk)
        self.Doc.recompute()
        bottom, top = sketches
        loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = (bottom, [regionName(bottom, 100, x=5), regionName(bottom, 100, x=25)])
        loft.Sections = [top]
        self.Doc.recompute()
        self.assertFalse(loft.isValid())
        self.assertIn("pick one region of it per section", loft.getStatusString())

    # -- picked regions --------------------------------------------------------------------

    def testOneRegion(self):
        body, sk = self.overlapping()
        self.assertVolume(self.pad(body, (sk, [regionName(sk, 25)])), 25, solids=1)

    def testSeveralRegions(self):
        """The two L regions without the lens: 150 in two solids (they touch at two corners
        only; Onshape PR2: two parts)."""
        body, sk = self.overlapping()
        ls = [regionName(sk, 75, x=c, y=c) for c in (25 / 6.0, 65 / 6.0)]
        self.assertVolume(self.pad(body, (sk, ls)), 150, solids=2)  # Onshape PR2: two parts

    def testAdjacentRegionsMakeOneSolid(self):
        body, sk = self.overlapping()
        pad = self.pad(body, (sk, [regionName(sk, 25), regionName(sk, 75, x=25 / 6.0)]))
        self.assertVolume(pad, 100, solids=1)
        # One face on top, as Onshape's: the two regions merged
        tops = [f for f in pad.Shape.Faces if abs(f.CenterOfMass.z - 1) < TOL]
        self.assertEqual(len(tops), 1)

    def testPickedRegionFollowsADimensionChange(self):
        """The lens of two dimensioned squares, then the second square moved from (5, 5) to
        (4, 3): the pick follows the lens, 6 x 7 = 42."""
        body, sk = self.sketch()
        dimensionedRect(sk, 0, 0, 10, 10)
        d = dimensionedRect(sk, 5, 5, 10, 10)
        self.Doc.recompute()
        pad = self.pad(body, (sk, [regionName(sk, 25)]))
        self.assertVolume(pad, 25)
        sk.setDatum(d[0], FreeCAD.Units.Quantity("4 mm"))
        sk.setDatum(d[1], FreeCAD.Units.Quantity("3 mm"))
        self.Doc.recompute()
        self.assertVolume(pad, 42)

    def testPickedRegionFollowsUnrelatedGeometry(self):
        """A circle added away from the squares renumbers the regions; the pick stays on the
        lens."""
        body, sk = self.overlapping()
        pad = self.pad(body, (sk, [regionName(sk, 25)]))
        sk.addGeometry(Part.Circle(V(-30, 0, 0), V(0, 0, 1), 2), False)
        sk.addGeometry(Part.Circle(V(-40, 0, 0), V(0, 0, 1), 3), False)
        self.Doc.recompute()
        self.assertVolume(pad, 25)

    def testPickedRegionThatDisappearsFails(self):
        """The lens picked, then the second square moved clear of the first: the lens is gone
        and the pad fails loudly. Onshape (PR8) stays valid and silently extrudes both squares,
        the regions bounded by the lens's curves: a deliberate difference, loud over silent."""
        body, sk = self.sketch()
        dimensionedRect(sk, 0, 0, 10, 10)
        d = dimensionedRect(sk, 5, 5, 10, 10)
        self.Doc.recompute()
        pad = self.pad(body, (sk, [regionName(sk, 25)]))
        self.assertVolume(pad, 25)
        sk.setDatum(d[0], FreeCAD.Units.Quantity("30 mm"))
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 2)  # two squares, no lens
        self.assertFalse(pad.isValid(), "the pad padded %g" % pad.Shape.Volume)

    # -- imprint: model edges in the sketch's plane ------------------------------------------

    def blockAndTopSketch(self):
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length, block.Width, block.Height = 30, 20, 5
        self.Doc.recompute()
        top = [i for i, f in enumerate(block.Shape.Faces) if abs(f.CenterOfMass.z - 5) < TOL][0]
        _, sk = self.sketch(body, support=[(block, "Face%d" % (top + 1))])
        return body, block, sk

    def testImprintSplitsARegionAtTheFaceEdge(self):
        """A sketch on a 30 x 20 block's top face with a circle of r 5 at (30, 10), over the
        face's right edge: the face's edge splits the disk into two halves, without projecting
        anything (Onshape, R4). The half on the face padded 3 adds 3 x 12.5 pi."""
        body, block, sk = self.blockAndTopSketch()
        sk.addGeometry(Part.Circle(V(30, 10, 0), V(0, 0, 1), 5), False)
        self.Doc.recompute()
        half = 12.5 * math.pi
        self.assertEqual(
            sorted(round(f.Area, 6) for f in sk.InternalShape.Faces), [round(half, 6)] * 2
        )
        self.assertEqual(len(sk.ExternalGeo), 2)  # nothing projected: the axes only
        self.assertEqual(len(sk.Shape.Edges), 1)  # nor added to the sketch's geometry
        onFace = regionName(sk, half, x=30 - 20 / (3 * math.pi))
        pad = self.pad(body, (sk, [onFace]), length=3)
        self.assertVolume(pad, 3000 + 3 * half, solids=1)

    def testDisableImprintingKeepsTheDiskWhole(self):
        """Onshape's Disable imprinting (R5, ops#640 polish P4): the same circle over the face's
        right edge stays one disk of 25 pi; unticked again, the face's edge splits it again."""
        body, block, sk = self.blockAndTopSketch()
        self.assertFalse(sk.DisableImprinting)  # Onshape's default: imprinting on
        sk.addGeometry(Part.Circle(V(30, 10, 0), V(0, 0, 1), 5), False)
        sk.DisableImprinting = True
        self.Doc.recompute()
        self.assertEqual([round(f.Area, 6) for f in sk.InternalShape.Faces],
                         [round(25 * math.pi, 6)])
        sk.DisableImprinting = False
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 2)

    def testImprintMakesNoRegionOfItsOwn(self):
        """A lone line across the face (ends past it): model edges never close a region, so there
        is none, and the whole sketch stops (Onshape, R4 and PR6b)."""
        body, block, sk = self.blockAndTopSketch()
        sk.addGeometry(Part.LineSegment(V(-5, 8, 0), V(35, 8, 0)), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 0)
        pad = self.pad(body, sk, length=2)
        self.assertFalse(pad.isValid())

    def testImprintDoesNotChangeTheWholeSketch(self):
        """A circle of r 3 inside the face: one region, the disk (not the face less the disk),
        and the whole sketch is the disk (Onshape, PR6a)."""
        body, block, sk = self.blockAndTopSketch()
        sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 3), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 1)
        pad = self.pad(body, sk, length=2)
        self.assertVolume(pad, 3000 + 18 * math.pi, solids=1)

    def testImprintWholeSketchIgnoresTheFaceEdge(self):
        """The circle over the face's edge, padded as a whole sketch: the whole disk (the
        imprint splits regions to pick, not the whole sketch)."""
        body, block, sk = self.blockAndTopSketch()
        sk.addGeometry(Part.Circle(V(30, 10, 0), V(0, 0, 1), 5), False)
        self.Doc.recompute()
        pad = self.pad(body, sk, length=3)
        self.assertVolume(pad, 3000 + 3 * 25 * math.pi, solids=1)

    def testImprintRegionPickedFollowsTheCircle(self):
        """The half on the face picked, then the circle's centre moved from x 30 to 28 by its
        dimension: the part on the face is the disk less the segment past x 30, and the pick
        follows it."""
        body, block, sk = self.blockAndTopSketch()
        sk.addGeometry(Part.Circle(V(30, 10, 0), V(0, 0, 1), 5), False)
        cx = sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, 30))
        sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 3, 10))
        sk.addConstraint(Sketcher.Constraint("Radius", 0, 5))
        self.Doc.recompute()
        half = 12.5 * math.pi
        pad = self.pad(body, (sk, [regionName(sk, half, x=30 - 20 / (3 * math.pi))]), length=3)
        self.assertVolume(pad, 3000 + 3 * half)
        sk.setDatum(cx, FreeCAD.Units.Quantity("28 mm"))
        self.Doc.recompute()
        segment = 25 * math.acos(2 / 5) - 2 * math.sqrt(21)
        self.assertVolume(pad, 3000 + 3 * (25 * math.pi - segment))

    def testImprintOfAHoleInTheFace(self):
        """The block with a hole of r 4 through it at (10, 10), and a 16 x 16 square around the
        hole on the top face: two regions, the square less the hole and a disk over the hole,
        though there is no material there (Onshape, R5)."""
        body, block, sk = self.blockAndTopSketch()
        _, hs = self.sketch(body, "HoleSketch")
        hs.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 4), False)
        pocket = body.newObject("PartDesign::Pocket", "Hole")
        pocket.Profile = hs
        pocket.Type = "ThroughAll"
        pocket.Midplane = True
        self.Doc.recompute()
        self.assertAlmostEqual(pocket.Shape.Volume, 3000 - 80 * math.pi, places=4)
        top = [
            i
            for i, f in enumerate(pocket.Shape.Faces)
            if abs(f.CenterOfMass.z - 5) < TOL and abs(f.BoundBox.ZLength) < TOL
        ][0]
        sk.AttachmentSupport = [(pocket, "Face%d" % (top + 1))]
        rect(sk, 2, 2, 18, 18)
        self.Doc.recompute()
        self.assertEqual(
            sorted(round(f.Area, 4) for f in sk.InternalShape.Faces),
            sorted([round(256 - 16 * math.pi, 4), round(16 * math.pi, 4)]),
        )

    def testImprintOnlyFromTheFace(self):
        """The circle over the edge, on the XY plane moved up to the top face's height: a plane
        imprints nothing, one region (Onshape, R4)."""
        body, block, _ = self.blockAndTopSketch()
        _, sk = self.sketch(body, "OnAPlane")
        sk.AttachmentOffset = FreeCAD.Placement(V(0, 0, 5), FreeCAD.Rotation())
        sk.addGeometry(Part.Circle(V(30, 10, 0), V(0, 0, 1), 5), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 1)

    def testImprintOfTheFaceOutline(self):
        """A rectangle drawn exactly over the 30 x 20 face's boundary: one region, the face."""
        body, block, sk = self.blockAndTopSketch()
        rect(sk, 0, 0, 30, 20)
        self.Doc.recompute()
        self.assertEqual([round(f.Area, 6) for f in sk.InternalShape.Faces], [600])


    # -- imprint near edges (perf profile 2b, ops#640) ----------------------------------------

    def holedPlateAndTopSketch(self, holes=12):
        """A 240 x 240 x 5 plate with holes x holes square through-holes of side 5 at the
        centres of a 20 mm grid's cells (Part::Feature as the body's base), and a sketch on its
        top face: the face has 4 + 4 * holes * holes edges."""
        pitch = 240 / holes
        square = lambda cx, cy, h: Part.makePolygon(
            [V(cx - h, cy - h, 0), V(cx + h, cy - h, 0), V(cx + h, cy + h, 0), V(cx - h, cy + h, 0),
             V(cx - h, cy - h, 0)]
        )
        wires = [square(120, 120, 120)] + [
            square((i + 0.5) * pitch, (j + 0.5) * pitch, 2.5) for i in range(holes) for j in range(holes)
        ]
        plate = self.Doc.addObject("Part::Feature", "Plate")
        plate.Shape = Part.makeFace(wires, "Part::FaceMakerBullseye").extrude(V(0, 0, 5))
        body = self.Doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = plate
        self.Doc.recompute()
        top = [
            i
            for i, f in enumerate(body.BaseFeature.Shape.Faces)
            if abs(f.BoundBox.ZMin - 5) < TOL and abs(f.BoundBox.ZMax - 5) < TOL and f.Area > 25000
        ][0]
        _, sk = self.sketch(body, support=[(body.BaseFeature, "Face%d" % (top + 1))])
        return body, sk, pitch

    def internalsWith(self, sk, mode):
        """The sketch's regions with FREECAD_CH_IMPRINT_NEAR = mode: their BRep text, their element
        names, and the faces' areas in order."""
        previous = os.environ.get("FREECAD_CH_IMPRINT_NEAR")
        os.environ["FREECAD_CH_IMPRINT_NEAR"] = mode
        try:
            sk.touch()
            self.Doc.recompute()
        finally:
            if previous is None:
                os.environ.pop("FREECAD_CH_IMPRINT_NEAR", None)
            else:
                os.environ["FREECAD_CH_IMPRINT_NEAR"] = previous
        shape = sk.InternalShape
        names = sorted(shape.ElementMap.items()) if hasattr(shape, "ElementMap") else []
        return shape.exportBrepToString(), names, [round(f.Area, 9) for f in shape.Faces]

    def checkNearEdgesKeepTheRegions(self, sk, regions):
        """The regions with the imprint's near edges only are those with all of them, to the
        BRep text and the element names; `regions`: their count."""
        self.Doc.recompute()
        allEdges = self.internalsWith(sk, "off")
        near = self.internalsWith(sk, "on")
        self.assertEqual(len(allEdges[2]), regions, allEdges[2])  # the setup
        self.assertEqual(near[2], allEdges[2])
        self.assertEqual(near[1], allEdges[1])
        self.assertEqual(near[0], allEdges[0])

    def testImprintNearEdgesInTheWeb(self):
        """A circle in the web between four holes: the disk only."""
        body, sk, pitch = self.holedPlateAndTopSketch()
        sk.addGeometry(Part.Circle(V(2 * pitch, 2 * pitch, 0), V(0, 0, 1), 3), False)
        self.checkNearEdgesKeepTheRegions(sk, 1)

    def testImprintNearEdgesOverAHole(self):
        """A circle around a hole: the ring and the square over the hole (R5)."""
        body, sk, pitch = self.holedPlateAndTopSketch()
        sk.addGeometry(Part.Circle(V(2.5 * pitch, 2.5 * pitch, 0), V(0, 0, 1), 6), False)
        self.checkNearEdgesKeepTheRegions(sk, 2)

    def testImprintNearEdgesAcrossAHole(self):
        """A circle across a hole's corner: the disk split by the hole's two sides."""
        body, sk, pitch = self.holedPlateAndTopSketch()
        sk.addGeometry(Part.Circle(V(2.5 * pitch + 2.5, 2.5 * pitch + 2.5, 0), V(0, 0, 1), 2), False)
        self.checkNearEdgesKeepTheRegions(sk, 2)

    def testImprintNearEdgesOverTheOutline(self):
        """A circle over the plate's corner: the quarter on the plate and the rest, the outline's
        loop near (the sketch's box meets two of its sides)."""
        body, sk, pitch = self.holedPlateAndTopSketch()
        sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 4), False)
        self.checkNearEdgesKeepTheRegions(sk, 2)

    def testImprintNearEdgesOfSeveralLoops(self):
        """A rectangle over four holes and a separate circle in the web: six regions (the frame,
        the four squares over the holes, the disk), in the face maker's order with all the edges."""
        body, sk, pitch = self.holedPlateAndTopSketch()
        rect(sk, 3 * pitch + 5, 3 * pitch + 5, 5 * pitch - 5, 5 * pitch - 5)
        sk.addGeometry(Part.Circle(V(8 * pitch, 8 * pitch, 0), V(0, 0, 1), 3), False)
        self.checkNearEdgesKeepTheRegions(sk, 6)

    def testImprintNearEdgesOverNineHoles(self):
        """A rectangle over a 3 x 3 block of holes (review memo3 F1): with the near edges only, the
        same ten regions, in the same order, of the same areas and names as with all of them. The
        face maker's boolean over fewer edges may number their edges and vertices otherwise (the
        BRep text differs): a reference holds by its name, not its index"""
        body, sk, pitch = self.holedPlateAndTopSketch()
        rect(sk, 3 * pitch + 5, 3 * pitch + 5, 6 * pitch - 5, 6 * pitch - 5)
        self.Doc.recompute()
        allEdges = self.internalsWith(sk, "off")
        near = self.internalsWith(sk, "on")
        self.assertEqual(len(allEdges[2]), 10, allEdges[2])  # the frame and nine squares
        self.assertEqual(near[2], allEdges[2])
        self.assertEqual(sorted(name for name, _ in near[1]), sorted(name for name, _ in allEdges[1]))

    def testImprintNearEdgesSpeedUpAManyHoledFace(self):
        """A circle on a face with 1600 hole edges: with only the near edges the regions are
        made several times faster than with all of them (perf profile 2b: every cell of the face
        was made and checked, then dropped). About 3.7 times at this size, where the imprint's own
        copies weigh in (73 s against 2.2 s at 6400 edges); with the switch set it measures nothing"""
        if os.environ.get("FREECAD_CH_IMPRINT_NEAR"):
            self.skipTest("FREECAD_CH_IMPRINT_NEAR is set")
        body, sk, pitch = self.holedPlateAndTopSketch(holes=20)
        sk.addGeometry(Part.Circle(V(2 * pitch, 2 * pitch, 0), V(0, 0, 1), 3), False)
        self.Doc.recompute()
        spent = {}
        for mode in ("off", "on"):
            start = time.perf_counter()
            self.internalsWith(sk, mode)
            spent[mode] = time.perf_counter() - start
        self.assertLess(spent["on"], spent["off"] / 2.5, spent)

if __name__ == "__main__":
    unittest.main()
