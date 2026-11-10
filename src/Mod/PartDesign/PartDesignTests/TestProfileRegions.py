# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: a sketch's profile as Onshape's regions (feat/profile-regions).
#
# Onshape's rule (notes/profile-regions.md): a sketch's regions are the bounded faces of the
# arrangement of its solid curves, plus the model edges lying in its plane (imprint). A feature
# takes one region, several, or the whole sketch; the whole sketch is every region of the
# sketch's own curves except those whose outer boundary is another region's inner boundary
# (filterInnerLoops). Every case is designed geometry with a geometric expectation; a Pad of
# length 1 on XY has the profile's area as its volume.

import math
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
        """A circle of r 5 inside a 20 x 20 square, tangent to its bottom side: OCCT makes the
        square's region with the circle as its hole, so the circle's region is an inner loop and
        the whole sketch is the square less the disk. Unverified in Onshape (it may count the
        touching circle as no hole and give the full square, 400)."""
        body, sk = self.sketch()
        rect(sk, 0, 0, 20, 20)
        sk.addGeometry(Part.Circle(V(10, 5, 0), V(0, 0, 1), 5), False)
        self.Doc.recompute()
        self.assertVolume(self.pad(body, sk), 400 - 25 * math.pi)

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

    # -- picked regions --------------------------------------------------------------------

    def testOneRegion(self):
        body, sk = self.overlapping()
        self.assertVolume(self.pad(body, (sk, [regionName(sk, 25)])), 25, solids=1)

    def testSeveralRegions(self):
        """The two L regions without the lens: 150 (they touch at two corners only)."""
        body, sk = self.overlapping()
        ls = [regionName(sk, 75, x=c, y=c) for c in (25 / 6.0, 65 / 6.0)]
        self.assertVolume(self.pad(body, (sk, ls)), 150)

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
        and the pad fails loudly, never pads another region."""
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

    def testImprintSplitsTheFaceWithALine(self):
        """A sketch on a 30 x 20 block's top face with one line across it at y = 8: the face's
        edges bound regions, so there are two, 240 and 360, without projecting anything; the
        240 strip padded 3 adds 720."""
        body, block, sk = self.blockAndTopSketch()
        sk.addGeometry(Part.LineSegment(V(-5, 8, 0), V(35, 8, 0)), False)
        self.Doc.recompute()
        self.assertEqual(sorted(round(f.Area, 6) for f in sk.InternalShape.Faces), [240, 360])
        self.assertEqual(len(sk.ExternalGeo), 2)  # nothing projected: the axes only
        self.assertEqual(len(sk.Shape.Edges), 1)  # nor added to the sketch's geometry
        pad = self.pad(body, (sk, [regionName(sk, 240)]), length=3)
        self.assertVolume(pad, 3000 + 720, solids=1)

    def testImprintDoesNotChangeTheWholeSketch(self):
        """The same sketch with a circle of r 3 inside the face: the whole sketch is the disk
        (the face's own region, bounded by model edges only, is not the sketch's)."""
        body, block, sk = self.blockAndTopSketch()
        sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 3), False)
        self.Doc.recompute()
        self.assertEqual(len(sk.InternalShape.Faces), 2)
        pad = self.pad(body, sk, length=2)
        self.assertVolume(pad, 3000 + 18 * math.pi, solids=1)

    def testImprintRegionPickedFollowsTheLine(self):
        """The 240 strip picked, then the line moved to y = 6 by its dimension: the strip is
        180, the pick follows it (the other region is 420)."""
        body, block, sk = self.blockAndTopSketch()
        sk.addGeometry(Part.LineSegment(V(-5, 8, 0), V(35, 8, 0)), False)
        sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
        c = sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, 8))
        self.Doc.recompute()
        pad = self.pad(body, (sk, [regionName(sk, 240)]), length=3)
        self.assertVolume(pad, 3720)
        sk.setDatum(c, FreeCAD.Units.Quantity("6 mm"))
        self.Doc.recompute()
        self.assertVolume(pad, 3000 + 540)

    def testImprintIgnoresEdgesOffThePlane(self):
        """The block's bottom and vertical edges don't bound regions: a circle alone gives the
        disk and the top face less the disk, nothing else."""
        body, block, sk = self.blockAndTopSketch()
        sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 3), False)
        self.Doc.recompute()
        areas = sorted(round(f.Area, 4) for f in sk.InternalShape.Faces)
        self.assertEqual(areas, sorted([round(9 * math.pi, 4), round(600 - 9 * math.pi, 4)]))


if __name__ == "__main__":
    unittest.main()
