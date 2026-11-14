# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#640 (Case Base #113): a revolve whose profile is a face of a solid, with a free-form
# edge ending on the axis, and the refusal of a revolve that makes no solid. ops#768: a profile's
# B-spline edges that lie on a line or circle revolve into the analytic surfaces Onshape makes.

import math
import unittest

import FreeCAD as App
import Part
import Sketcher  # noqa: F401  (registers Sketcher::SketchObject)

V3 = App.Vector

# The cap: half an ellipse, semi-axes A along the chord and B across it, below the chord
A = 4.0
B = 0.8
DEPTH = 3.0
CAP = math.pi * A * B / 2.0
# Turned a whole turn about its chord the cap sweeps an ellipsoid of revolution, 4/3 pi A B^2;
# the quarter of it inside the pad (behind the cap, below the chord) is what a Groove removes
QUARTER = math.pi * A * B * B / 3.0
# ops#768's profile: a half disk of radius R about (C, 0) and a triangle beside it, turned about z
R = 2.0
C = 5.0
PAPPUS = 2.0 * math.pi * (
    math.pi * R * R / 2.0 * (C + 4.0 * R / (3.0 * math.pi)) + 2.0 * (3.0 * C - 1.0) / 3.0
)


class TestRevolveFaceProfile(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("RevolveFaceProfile")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def pad(self, zoff, bspline=True):
        """A Pad of the half-ellipse cap, sketched on XZ (sketch y is global z) zoff above the
        origin and padded DEPTH towards +y. Its cap at y 0 is a planar face of the solid whose
        straight edge (the chord) lies on the sketch's Edge2."""
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        sk = self.body.newObject("Sketcher::SketchObject", "Cap")
        sk.AttachmentSupport = [(self.body.Origin.OriginFeatures[4], "")]  # XZ_Plane
        sk.MapMode = "FlatFace"
        sk.AttachmentOffset = App.Placement(V3(0, zoff, 0), App.Rotation())
        arc = Part.ArcOfEllipse(Part.Ellipse(V3(0, 0, 0), A, B), math.pi, 2 * math.pi)
        sk.addGeometry(arc.toBSpline() if bspline else arc)
        sk.addGeometry(Part.LineSegment(V3(-A, 0, 0), V3(A, 0, 0)))
        self.doc.recompute()
        pad = self.body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sk
        pad.Length = DEPTH
        pad.Reversed = True
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, CAP * DEPTH, places=6)
        caps = [
            i
            for i, f in enumerate(pad.Shape.Faces)
            if f.Surface.__class__.__name__ == "Plane"
            and abs(f.Area - CAP) < 1e-6
            and abs(f.CenterOfMass.y) < 1e-9
        ]
        self.assertEqual(len(caps), 1)
        return sk, pad, "Face%d" % (caps[0] + 1)

    def testGrooveOfBSplineCapAboutItsChord(self):
        """#113's case designed: the cap (a rational B-spline half-ellipse, a face of the pad)
        grooved a whole turn about its chord removes the quarter ellipsoid, pi A B^2 / 3, at the
        origin and off it. Before, the tool was empty and the Groove reported success."""
        for zoff in (0.0, 20.225):
            with self.subTest(zoff=zoff):
                sk, pad, cap = self.pad(zoff)
                groove = self.body.newObject("PartDesign::Groove", "Groove")
                groove.Profile = (pad, [cap])
                groove.ReferenceAxis = (sk, ["Edge2"])
                groove.Angle = 360
                self.doc.recompute()
                self.assertTrue(groove.isValid(), groove.getStatusString())
                self.assertTrue(groove.AddSubShape.isValid())
                self.assertAlmostEqual(groove.AddSubShape.Volume, 4.0 * QUARTER, places=6)
                self.assertAlmostEqual(pad.Shape.Volume - groove.Shape.Volume, QUARTER, places=6)
                self.assertTrue(groove.Shape.isValid())
                App.closeDocument(self.doc.Name)
                self.doc = App.newDocument("RevolveFaceProfile")

    def testRevolutionOfBSplineCapQuarterTurn(self):
        """The same cap revolved a quarter turn as a Revolution: its tool is the quarter
        ellipsoid, pi A B^2 / 3, either way round; one way it lies in the pad (nothing added),
        the other way it is added. Before, the quarter came out 1.009 or -0.454."""
        sk, pad, cap = self.pad(20.225)
        rev = self.body.newObject("PartDesign::Revolution", "Revolution")
        rev.Profile = (pad, [cap])
        rev.ReferenceAxis = (sk, ["Edge2"])
        rev.Angle = 90
        added = []
        for reversed_ in (False, True):
            rev.Reversed = reversed_
            self.doc.recompute()
            self.assertTrue(rev.isValid(), rev.getStatusString())
            self.assertAlmostEqual(abs(rev.AddSubShape.Volume), QUARTER, places=6)
            self.assertTrue(rev.Shape.isValid())
            added.append(rev.Shape.Volume - CAP * DEPTH)
        self.assertAlmostEqual(min(added), 0.0, places=6)
        self.assertAlmostEqual(max(added), QUARTER, places=6)

    def testRevolveThatCannotBeMadeIsRefused(self):
        """Must fail: the cap as a B-spline surface face (outside the planar faces given fresh
        edges), on its own placed by a location, its chord on the axis: OCCT's revolve of it is
        invalid with no volume. The Groove fails with its message and leaves the base as it was;
        it is never applied as nothing with success, as #113's was."""
        el = Part.Ellipse(V3(0, 0, 0), A, B)
        el.rotate(App.Placement(V3(), App.Rotation(V3(1, 0, 0), 90)))
        arc = Part.ArcOfEllipse(el, math.pi, 2 * math.pi).toBSpline().toShape()
        chord = Part.LineSegment(arc.Vertexes[-1].Point, arc.Vertexes[0].Point).toShape()
        face = Part.Face(Part.Wire([arc, chord])).toNurbs().Faces[0]
        face.translate(V3(0, 0, 20.225))
        raw = face.revolve(V3(0, 0, 20.225), V3(1, 0, 0), 360)
        self.assertFalse(raw.isValid() and raw.Volume > 1e-7)  # the kernel's defect, as found
        body = self.doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        box.Height = 40
        box.Placement = App.Placement(V3(-10, -10, 0), App.Rotation())
        cap = self.doc.addObject("Part::Feature", "Cap")
        cap.Shape = face
        axis = body.newObject("PartDesign::Line", "Axis")
        axis.Placement = App.Placement(V3(0, 0, 20.225), App.Rotation(V3(0, 1, 0), 90))
        self.doc.recompute()
        groove = body.newObject("PartDesign::Groove", "Groove")
        groove.Profile = (cap, ["Face1"])
        groove.ReferenceAxis = (axis, [""])
        groove.Angle = 360
        self.doc.recompute()
        self.assertFalse(groove.isValid())
        self.assertNotEqual(groove.getStatusString(), "Valid")
        self.assertAlmostEqual(box.Shape.Volume, 16000.0, places=6)

    def testPlanarCapPlacedByLocationGrooves(self):
        """The planar cap placed by a location (a Part::Feature's face, as a face from another
        solid comes): fresh edges, and the Groove removes the whole ellipsoid from a box holding it."""
        el = Part.Ellipse(V3(0, 0, 0), A, B)
        el.rotate(App.Placement(V3(), App.Rotation(V3(1, 0, 0), 90)))
        arc = Part.ArcOfEllipse(el, math.pi, 2 * math.pi).toBSpline().toShape()
        chord = Part.LineSegment(arc.Vertexes[-1].Point, arc.Vertexes[0].Point).toShape()
        face = Part.Face(Part.Wire([arc, chord]))
        face.translate(V3(0, 0, 20.225))
        body = self.doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        box.Height = 40
        box.Placement = App.Placement(V3(-10, -10, 0), App.Rotation())
        cap = self.doc.addObject("Part::Feature", "Cap")
        cap.Shape = face
        axis = body.newObject("PartDesign::Line", "Axis")
        axis.Placement = App.Placement(V3(0, 0, 20.225), App.Rotation(V3(0, 1, 0), 90))
        self.doc.recompute()
        groove = body.newObject("PartDesign::Groove", "Groove")
        groove.Profile = (cap, ["Face1"])
        groove.ReferenceAxis = (axis, [""])
        groove.Angle = 360
        self.doc.recompute()
        self.assertTrue(groove.isValid(), groove.getStatusString())
        self.assertAlmostEqual(16000.0 - groove.Shape.Volume, 4.0 * QUARTER, places=6)

    def bsplineProfileRevolution(self, angle, bspline=True):
        """A Revolution of a sketch on XZ about its V axis (global z): the half disk of radius
        R about (C, 0) outside x = C, and the triangle (C, R), (C - 1, -R), (C, -R). The arc
        and the slanted side are B-splines (or a circle arc and a line)."""
        body = self.doc.addObject("PartDesign::Body", "Body")
        sk = body.newObject("Sketcher::SketchObject", "Profile")
        sk.AttachmentSupport = [(body.Origin.OriginFeatures[4], "")]  # XZ_Plane
        sk.MapMode = "FlatFace"
        arc = Part.ArcOfCircle(Part.Circle(V3(C, 0, 0), V3(0, 0, 1), R), -math.pi / 2, math.pi / 2)
        slant = Part.LineSegment(V3(C, R, 0), V3(C - 1, -R, 0))
        # the arc as an exact rational B-spline (toBSpline() gives one 1.6e-8 off the circle)
        sk.addGeometry(arc.toNurbs() if bspline else arc)
        sk.addGeometry(slant.toBSpline() if bspline else slant)
        sk.addGeometry(Part.LineSegment(V3(C - 1, -R, 0), V3(C, -R, 0)))
        self.doc.recompute()
        self.assertEqual(
            [e.Curve.__class__.__name__ for e in sk.Shape.Edges].count("BSplineCurve"),
            2 if bspline else 0,
        )
        rev = body.newObject("PartDesign::Revolution", "Revolution")
        rev.Profile = sk
        rev.ReferenceAxis = (sk, ["V_Axis"])
        rev.Angle = angle
        self.doc.recompute()
        self.assertTrue(rev.isValid(), rev.getStatusString())
        self.assertTrue(rev.Shape.isValid())
        return rev

    def testBSplineProfileRevolvesToAnalyticSurfaces(self):
        """ops#768 (FSLC #021/#022/#030/#031 designed): a B-spline circle arc revolves into a
        torus and a B-spline line segment into a cone, as Onshape makes them, not into a
        SurfaceOfRevolution; the volume is Pappus's, the same as the analytic profile's."""
        for angle in (360, 90):
            with self.subTest(angle=angle):
                rev = self.bsplineProfileRevolution(angle)
                kinds = sorted(f.Surface.__class__.__name__ for f in rev.Shape.Faces)
                self.assertNotIn("SurfaceOfRevolution", kinds)
                self.assertEqual(kinds.count("Toroid"), 1, kinds)
                self.assertEqual(kinds.count("Cone"), 1, kinds)
                self.assertEqual(kinds.count("Plane"), 1 if angle == 360 else 3, kinds)
                self.assertAlmostEqual(rev.Shape.Volume, PAPPUS * angle / 360.0, places=9)
                torus = [f.Surface for f in rev.Shape.Faces if f.Surface.__class__.__name__ == "Toroid"][0]
                self.assertAlmostEqual(torus.MajorRadius, C, places=9)
                self.assertAlmostEqual(torus.MinorRadius, R, places=9)
                App.closeDocument(self.doc.Name)
                self.doc = App.newDocument("RevolveFaceProfile")

    def testAnalyticProfileRevolutionUnchanged(self):
        """The control: the same profile drawn as a circle arc and lines gives the same solid."""
        rev = self.bsplineProfileRevolution(360, bspline=False)
        kinds = sorted(f.Surface.__class__.__name__ for f in rev.Shape.Faces)
        self.assertEqual(kinds, ["Cone", "Plane", "Toroid"])
        self.assertAlmostEqual(rev.Shape.Volume, PAPPUS, places=9)


if __name__ == "__main__":
    unittest.main()
