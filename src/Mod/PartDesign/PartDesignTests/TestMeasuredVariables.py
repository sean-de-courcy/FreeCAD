# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, notes/measured-variables-design.md in the ops repo)

"""Measured variables (Onshape's Variable feature in the MEASURED mode): a part studio variable
whose value is read from the geometry on every recompute.

Designed geometry, in part studio P:
- Body A: a sketch on XY, a 20 x 10 rectangle with its corner on the origin (constraints W and H),
  padded 5 mm. Its bottom long edge (y = 0, z = 0) is 20 mm long.
- Body B: a sketch on XY, a 4 x 4 square at x = 40, padded by `#w`; the expected result is B's
  volume, 16 x w.
- Sometimes a hole of radius 2 at (5, 5) in A's sketch, or two such holes 10 mm apart.
Every expected value is geometric: a length, a diameter, a distance, or a volume."""

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher
from FreeCAD import Vector as V


def rectangle(sketch, x, y, w, h, names=None):
    first = sketch.GeometryCount
    pts = [V(x, y, 0), V(x + w, y, 0), V(x + w, y + h, 0), V(x, y + h, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", first))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", first + 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", first + 1))
    sketch.addConstraint(Sketcher.Constraint("Vertical", first + 3))
    if names:
        sketch.addConstraint(Sketcher.Constraint("Coincident", first, 1, -1, 1))
        c = sketch.addConstraint(Sketcher.Constraint("DistanceX", first, 1, first, 2, w))
        sketch.renameConstraint(c, names[0])
        c = sketch.addConstraint(Sketcher.Constraint("DistanceY", first + 1, 1, first + 1, 2, h))
        sketch.renameConstraint(c, names[1])


def edge_named(shape, test):
    """The indexed name of the one edge of `shape` passing `test`."""
    found = ["Edge%d" % i for i, e in enumerate(shape.Edges, 1) if test(e)]
    assert len(found) == 1, found
    return found[0]


def face_named(shape, test):
    found = ["Face%d" % i for i, f in enumerate(shape.Faces, 1) if test(f)]
    assert len(found) == 1, found
    return found[0]


def bottom_long(e, length=20):
    return abs(e.Length - length) < 1e-6 and e.BoundBox.YMax < 1e-6 and e.BoundBox.ZMax < 1e-6


def top_long(e):
    return abs(e.Length - 20) < 1e-6 and e.BoundBox.YMin > 10 - 1e-6 and e.BoundBox.ZMax < 1e-6


def bottom_circle(cx, r=2):
    def test(e):
        c = e.Curve
        return (isinstance(c, Part.Circle) and abs(c.Radius - r) < 1e-6
                and abs(c.Center.x - cx) < 1e-6 and e.BoundBox.ZMax < 1e-6)
    return test


class TestMeasuredVariables(unittest.TestCase):
    def setUp(self):
        from freecad.variables import measured

        self.measured = measured
        self.doc = App.newDocument("MeasuredVariables")
        self.studio = self.doc.addObject("App::Part", "P")
        self.bodyA = self.doc.addObject("PartDesign::Body", "BodyA")
        self.studio.addObject(self.bodyA)
        self.sketchA = self.sketch(self.bodyA, "SketchA")
        rectangle(self.sketchA, 0, 0, 20, 10, names=("W", "H"))
        self.padA = self.bodyA.newObject("PartDesign::Pad", "PadA")
        self.padA.Profile = self.sketchA
        self.padA.Length = 5
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sketch(self, body, name):
        sk = body.newObject("Sketcher::SketchObject", name)
        sk.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]  # XY_Plane
        sk.MapMode = "FlatFace"
        return sk

    def make_user(self, expression="#w"):
        """Body B: a 4 x 4 square padded by `expression`."""
        self.bodyB = self.doc.addObject("PartDesign::Body", "BodyB")
        self.studio.addObject(self.bodyB)
        sk = self.sketch(self.bodyB, "SketchB")
        rectangle(sk, 40, 0, 4, 4)
        self.padB = self.bodyB.newObject("PartDesign::Pad", "PadB")
        self.padB.Profile = sk
        self.padB.setExpression("Length", expression)
        return self.padB

    def assertValid(self, *objs):
        for o in objs:
            self.assertNotIn("Invalid", o.State, "{}: {}".format(o.Label, o.getStatusString()))

    # --- the kickoff's three: drives a Pad, follows a moved reference, a lost one fails loudly

    def testLengthDrivesPadDepth(self):
        edge = edge_named(self.padA.Shape, bottom_long)
        vs, m = self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        pad = self.make_user("#w")
        self.doc.recompute()
        self.assertValid(m, vs, pad)
        self.assertIs(vs.getParentGeoFeatureGroup(), self.studio)
        self.assertAlmostEqual(vs.w.Value, 20, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 16 * 20, places=4)
        self.assertEqual(pad.ExpressionEngine[0][1].replace(" ", ""), vs.Name + ".w")

    def testMovedReferenceUpdates(self):
        edge = edge_named(self.padA.Shape, bottom_long)
        vs, m = self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        pad = self.make_user("#w")
        self.doc.recompute()
        self.sketchA.setDatum("W", App.Units.Quantity("30 mm"))
        self.doc.recompute()
        self.assertValid(m, vs, pad)
        self.assertAlmostEqual(vs.w.Value, 30, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 16 * 30, places=4)

    def testReferenceFollowsRenumberedEdge(self):
        """The sketch's lines are reordered and a circle added before them: the pad's edges are
        renumbered, and the measured edge is still the top one."""
        edge = edge_named(self.padA.Shape, top_long)
        vs, m = self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        self.doc.recompute()
        g0, g1 = self.sketchA.Geometry[0], self.sketchA.Geometry[1]
        self.sketchA.delGeometry(1)
        self.sketchA.delGeometry(0)
        self.sketchA.addGeometry(Part.Circle(V(10, 5, 0), V(0, 0, 1), 1))
        self.sketchA.addGeometry(g1)
        self.sketchA.addGeometry(g0)
        self.doc.recompute()
        moved = edge_named(self.padA.Shape, top_long)
        self.assertNotEqual(moved, edge, "the edit should renumber the edge")
        self.assertValid(m, vs)
        self.assertEqual(m.References[0][1][0], moved)
        self.assertAlmostEqual(vs.w.Value, 20, places=6)

    def testLostReferenceFailsLoudly(self):
        self.sketchA.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 2))
        self.doc.recompute()
        edge = edge_named(self.padA.Shape, bottom_circle(5))
        vs, m = self.measured.add(self.studio, "w", "Diameter", [(self.padA, edge)])
        pad = self.make_user("#w * 5")
        self.doc.recompute()
        self.assertValid(m, vs, pad)
        self.assertAlmostEqual(pad.Shape.Volume, 16 * 20, places=4)
        self.sketchA.delGeometry(self.sketchA.GeometryCount - 1)  # the hole
        self.doc.recompute()
        for o in (m, vs, pad):
            self.assertIn("Invalid", o.State, o.Label)
        self.assertIn(edge, m.getStatusString())
        self.assertIn("has an error", pad.getStatusString())
        # Onshape's MV4: the variable is unset and its user fails with no last value kept; here
        # its body's result is gone (the pad's own shape is not shown when its body has one).
        self.assertTrue(self.bodyB.Shape.isNull(), "the user's body kept a result")

    def testDeletedObjectFailsLoudly(self):
        box = self.doc.addObject("Part::Box", "Src")
        self.studio.addObject(box)
        box.Length = 7
        self.doc.recompute()
        edge = edge_named(box.Shape, lambda e: abs(e.Length - 7) < 1e-6 and e.BoundBox.YMax < 1e-6
                          and e.BoundBox.ZMax < 1e-6)
        vs, m = self.measured.add(self.studio, "w", "Length", [(box, edge)])
        self.doc.recompute()
        self.assertAlmostEqual(vs.w.Value, 7, places=6)
        self.doc.removeObject("Src")
        self.doc.recompute()
        self.assertIn("Invalid", m.State)
        self.assertIn("Invalid", vs.State)
        self.assertIn("lost reference Src." + edge, m.getStatusString())
        self.assertIn("'w'", m.getStatusString())

    # --- the kinds

    def testDistanceMinimumUseAxisAndMaximum(self):
        """Two holes r2, centres 10 apart: gap 6, centre to centre 10, farthest points 14."""
        self.sketchA.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 2))
        self.sketchA.addGeometry(Part.Circle(V(15, 5, 0), V(0, 0, 1), 2))
        self.doc.recompute()
        a = edge_named(self.padA.Shape, bottom_circle(5))
        b = edge_named(self.padA.Shape, bottom_circle(15))
        refs = [(self.padA, a), (self.padA, b)]
        vs, low = self.measured.add(self.studio, "gap", "Distance", refs)
        hp, mid = self.measured.add(self.studio, "pitch", "Distance", refs, use_axis=True)
        hf, far = self.measured.add(self.studio, "far", "Distance", refs, distance_type="Maximum")
        x0 = face_named(self.padA.Shape, lambda f: f.BoundBox.XMax < 1e-6)
        x1 = face_named(self.padA.Shape, lambda f: f.BoundBox.XMin > 20 - 1e-6)
        hs, faces = self.measured.add(self.studio, "span", "Distance", [(self.padA, x0), (self.padA, x1)])
        self.doc.recompute()
        self.assertValid(low, mid, far, faces, vs, hp, hf, hs)
        self.assertAlmostEqual(vs.gap.Value, 10 - 2 * 2, places=6)
        self.assertAlmostEqual(hp.pitch.Value, 10, places=6)
        self.assertAlmostEqual(hf.far.Value, 10 + 2 * 2, places=9)
        self.assertAlmostEqual(hs.span.Value, 20, places=6)
        self.assertTrue(mid.UseAxis)
        self.assertEqual(far.DistanceType, "Maximum")

    def testDistanceAcrossPlacedObjects(self):
        """A's face x = 20 (inside BodyA) and the near face of a box placed at x = 45 in the studio:
        25 mm, read in the studio's frame."""
        box = self.doc.addObject("Part::Box", "Block")
        self.studio.addObject(box)
        box.Placement = App.Placement(V(45, 0, 0), App.Rotation())
        self.doc.recompute()
        a = face_named(self.padA.Shape, lambda f: f.BoundBox.XMin > 20 - 1e-6)
        b = face_named(box.Shape, lambda f: f.BoundBox.XMax < 45 + 1e-6)
        vs, m = self.measured.add(self.studio, "gap", "Distance", [(self.padA, a), (box, b)])
        self.doc.recompute()
        self.assertValid(m)
        self.assertAlmostEqual(vs.gap.Value, 25, places=6)

    def testLengthSumsEdges(self):
        edges = [edge_named(self.padA.Shape, bottom_long), edge_named(self.padA.Shape, top_long)]
        vs, m = self.measured.add(self.studio, "w", "Length", [(self.padA, e) for e in edges])
        self.doc.recompute()
        self.assertValid(m)
        self.assertAlmostEqual(vs.w.Value, 40, places=6)
        # A reference removed on purpose is not a lost one.
        self.measured.set_references(m, [(self.padA, edges[0])])
        self.doc.recompute()
        self.assertValid(m)
        self.assertAlmostEqual(vs.w.Value, 20, places=6)

    def testDiameterOfCylindricalFace(self):
        self.sketchA.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 1.5))
        self.doc.recompute()
        face = face_named(self.padA.Shape, lambda f: isinstance(f.Surface, Part.Cylinder))
        vs, m = self.measured.add(self.studio, "d", "Diameter", [(self.padA, face)])
        self.doc.recompute()
        self.assertValid(m)
        self.assertAlmostEqual(vs.d.Value, 3, places=6)

    def testUnsuitableReferencesFail(self):
        face = face_named(self.padA.Shape, lambda f: f.BoundBox.XMax < 1e-6)
        _, m = self.measured.add(self.studio, "a", "Length", [(self.padA, face)])
        line = edge_named(self.padA.Shape, bottom_long)
        _, d = self.measured.add(self.studio, "b", "Diameter", [(self.padA, line)])
        self.doc.recompute()
        self.assertIn("Invalid", m.State)
        self.assertIn("select edges to measure", m.getStatusString())
        self.assertIn("Invalid", d.State)
        self.assertIn("select an entity to measure", d.getStatusString())

    def testAddChecks(self):
        edge = edge_named(self.padA.Shape, bottom_long)
        with self.assertRaises(ValueError):
            self.measured.add(self.bodyA, "w", "Length", [(self.padA, edge)])  # not a studio
        with self.assertRaises(ValueError):
            self.measured.add(self.studio, "w", "Distance", [(self.padA, edge)])  # one reference
        with self.assertRaises(ValueError):
            self.measured.add(self.studio, "w", "Diameter", [(self.padA, edge)] * 2)
        with self.assertRaises(ValueError):
            self.measured.add(self.studio, "w", "Volume", [(self.padA, edge)])
        two = [(self.padA, edge), (self.padA, edge_named(self.padA.Shape, top_long))]
        with self.assertRaises(ValueError):  # lane 1's "Center" is Use axis now
            self.measured.add(self.studio, "w", "Distance", two, distance_type="Center")
        with self.assertRaises(ValueError):
            self.measured.add(self.studio, "w", "Distance", two, record="W")
        self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        with self.assertRaises(ValueError):
            self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])  # name taken

    def testSaveAndRestore(self):
        edge = edge_named(self.padA.Shape, bottom_long)
        vs, m = self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        top = edge_named(self.padA.Shape, top_long)
        _hx, mx = self.measured.add(self.studio, "x", "Distance", [(self.padA, edge), (self.padA, top)],
                                    distance_type="Maximum", record="Y", use_axis=True)
        self.make_user("#w")
        self.doc.recompute()
        names = m.Name, vs.Name, mx.Name
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "measured.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            m = self.doc.getObject(names[0])
            self.assertEqual(m.Format, 1)
            self.assertEqual(m.Kind, "Length")
            mx = self.doc.getObject(names[2])
            self.assertEqual((mx.DistanceType, mx.ValueToRecord, mx.UseAxis, mx.Radius),
                             ("Maximum", "Y", True, False))
            self.doc.getObject("SketchA").setDatum("W", App.Units.Quantity("25 mm"))
            self.doc.recompute()
            pad = self.doc.getObject("PadB")
            self.assertAlmostEqual(self.doc.getObject(names[1]).w.Value, 25, places=6)
            self.assertAlmostEqual(pad.Shape.Volume, 16 * 25, places=4)
            # the bottom and top long edges, farthest apart corner to corner: Y is the 10 between them
            self.assertAlmostEqual(mx.Value.Value, 10, places=9)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


    # --- measured variables 2: one holder per variable, picks resolved to the feature that made
    # the element, the implicit studio

    def testMeasuresFeatureUsingStudioVariable(self):
        """A's pad is driven by the studio variable h; w measures that pad and drives B. With one
        set shared by h and w this was a cycle (set -> measurement -> pad -> set)."""
        own = self.measured.studio_variables(self.studio)
        own.addProperty("App::PropertyDistance", "h", "", "")
        own.h = 7
        self.padA.setExpression("Length", "#h")
        self.doc.recompute()
        edge = edge_named(self.padA.Shape, bottom_long)
        holder, m = self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        pad = self.make_user("#w")
        self.doc.recompute()
        self.assertValid(self.padA, m, holder, pad)
        self.assertIsNot(holder, own)
        self.assertTrue(self.measured.is_measured_holder(holder))
        self.assertIs(self.measured.studio_variables(self.studio), own)
        self.assertAlmostEqual(pad.Shape.Volume, 16 * 20, places=4)
        own.h = 9  # the measured edge keeps its length; the chain still recomputes
        self.sketchA.setDatum("W", App.Units.Quantity("30 mm"))
        self.doc.recompute()
        self.assertValid(self.padA, m, holder, pad)
        self.assertAlmostEqual(pad.Shape.Volume, 16 * 30, places=4)

    def testTrueCycleRefused(self):
        """Measuring a feature that uses the measured variable itself stays a loud error."""
        pad = self.make_user("5 mm")
        self.doc.recompute()
        edge = edge_named(pad.Shape, lambda e: abs(e.Length - 4) < 1e-6
                          and e.BoundBox.YMax < 1e-6 and e.BoundBox.ZMax < 1e-6)
        holder, m = self.measured.add(self.studio, "w", "Length", [(pad, edge)])
        self.doc.recompute()
        self.assertAlmostEqual(holder.w.Value, 4, places=6)
        with self.assertRaisesRegex(Exception, "(?i)cycl"):
            pad.setExpression("Length", "#w")

    def testNameTakenAcrossTheStudio(self):
        edge = edge_named(self.padA.Shape, bottom_long)
        self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        self.assertIn("w", self.measured.check_name(self.studio, "w"))
        self.assertEqual(self.measured.check_name(self.studio, "w2"), "")
        own = self.measured.studio_variables(self.studio)
        own.addProperty("App::PropertyDistance", "h", "", "")
        self.assertIn("h", self.measured.check_name(self.studio, "h"))

    def testImplicitStudio(self):
        """The document's top level is a part studio too: its holder and measurement sit there."""
        doc = App.newDocument("MeasuredImplicit")
        try:
            body = doc.addObject("PartDesign::Body", "Body")
            sk = self.sketch(body, "Sk")
            rectangle(sk, 0, 0, 20, 10)
            pad = body.newObject("PartDesign::Pad", "Pad")
            pad.Profile = sk
            pad.Length = 5
            doc.recompute()
            edge = edge_named(pad.Shape, bottom_long)
            holder, m = self.measured.add(doc, "w", "Length", [(pad, edge)])
            doc.recompute()
            self.assertIsNone(holder.getParentGeoFeatureGroup())
            self.assertAlmostEqual(holder.w.Value, 20, places=6)
            own = self.measured.studio_variables(doc, create=False)
            self.assertIsNotNone(own)
            self.assertEqual(own.Label, "Variables")
            self.assertIsNot(own, holder)
            self.assertIs(self.measured.studio_of(pad), doc)
        finally:
            App.closeDocument(doc.Name)

    # picks

    def side_pad(self, x=5, y=-2, w=4, h=4, length=5, z=0, name="Pad2"):
        """A second pad in body A: a w x h rectangle at (x, y) on a plane z above XY."""
        sk = self.sketch(self.bodyA, name + "Sketch")
        sk.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
        rectangle(sk, x, y, w, h)
        # fully constrained: its corner at (x, y), its size w x h
        sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, x))
        sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, y))
        sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, w))
        sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, h))
        pad = self.bodyA.newObject("PartDesign::Pad", name)
        pad.Profile = sk
        pad.Length = length
        self.doc.recompute()
        self.assertValid(pad)
        return pad

    def testPickReadsTheFeatureItWasPickedOn(self):
        """Onshape's variable reads the geometry at its own place, after every feature that existed
        when it was made: a pick on the tip names the tip's element, even for an edge a later pad
        left alone (an earlier feature with the same edge is not where the variable sits)."""
        pad2 = self.side_pad(x=5, y=2, z=5, length=3)  # on top, away from the bottom edges
        tip_edge = edge_named(pad2.Shape, bottom_long)
        feature, element = self.measured.resolve_pick(
            self.studio, "{}.{}.{}".format(self.bodyA.Name, pad2.Name, tip_edge))
        self.assertIs(feature, pad2)
        self.assertEqual(element, tip_edge)
        # through the body (its shape is the tip's)
        feature, element = self.measured.resolve_pick(
            self.studio, "{}.{}".format(self.bodyA.Name, tip_edge))
        self.assertIs(feature, pad2)
        self.assertEqual(element, tip_edge)
        # a feature picked in the tree is read as that feature left it
        first = edge_named(self.padA.Shape, bottom_long)
        feature, element = self.measured.resolve_pick(
            self.studio, "{}.{}.{}".format(self.bodyA.Name, self.padA.Name, first))
        self.assertIs(feature, self.padA)
        self.assertEqual(element, first)

    def testPickOfAChangedEdgeStaysOnTheFeatureThatChangedIt(self):
        """A pad across the bottom front edge splits it: the piece picked is not in the first pad,
        so it is read where it was picked, and measures what was picked (5 mm, not 20)."""
        pad2 = self.side_pad(x=5, y=-2, z=0, length=5)
        piece = edge_named(pad2.Shape, lambda e: abs(e.Length - 5) < 1e-6
                           and e.BoundBox.YMax < 1e-6 and e.BoundBox.XMax < 5 + 1e-6
                           and e.BoundBox.ZMax < 1e-6)
        feature, element = self.measured.resolve_pick(
            self.studio, "{}.{}.{}".format(self.bodyA.Name, pad2.Name, piece))
        self.assertIs(feature, pad2)
        self.assertEqual(element, piece)
        holder, m = self.measured.add(self.studio, "w", "Length", [(feature, element)])
        self.doc.recompute()
        self.assertAlmostEqual(holder.w.Value, 5, places=6)

    def testPickedEdgeLetsALaterFeatureUseTheVariable(self):
        """Picked on the first pad (the variable's place is after it), the variable can drive a
        later pad; picked on the later pad, that pad using it is a cycle, refused at once (in
        Onshape a feature before the variable can't read it)."""
        pad2 = self.side_pad(x=5, y=2, z=5, length=3)
        first = edge_named(self.padA.Shape, bottom_long)
        ref = self.measured.resolve_pick(
            self.studio, "{}.{}.{}".format(self.bodyA.Name, self.padA.Name, first))
        holder, m = self.measured.add(self.studio, "w", "Length", [ref])
        pad2.setExpression("Length", "#w / 4")
        self.doc.recompute()
        self.assertValid(m, holder, pad2)
        self.assertAlmostEqual(pad2.Length.Value, 5, places=6)
        pad3 = self.side_pad(x=12, y=2, z=5, length=2, name="Pad3")
        tip_edge = edge_named(pad3.Shape, top_long)
        ref = self.measured.resolve_pick(self.studio, "{}.{}".format(self.bodyA.Name, tip_edge))
        self.assertIs(ref[0], pad3)
        holder3, m3 = self.measured.add(self.studio, "t", "Length", [ref])
        self.doc.recompute()
        with self.assertRaisesRegex(Exception, "(?i)cycl"):
            pad3.setExpression("Length", "#t / 10")

    # --- integrator 12's review cases (ops#673 comment 6816773029): the variable reads the
    # studio's geometry at its own place, and a body's placement counts

    def pocket_rect(self, x, y, w, h):
        """A through-all midplane pocket in body A of a w x h rectangle at (x, y), its corner
        held by the constraints PX and PY."""
        sk = self.sketch(self.bodyA, "CutSketch")
        rectangle(sk, x, y, w, h)
        for kind, a, b, value, name in (("DistanceX", (-1, 1), (0, 1), x, "PX"),
                                        ("DistanceY", (-1, 1), (0, 1), y, "PY"),
                                        ("DistanceX", (0, 1), (0, 2), w, None),
                                        ("DistanceY", (1, 1), (1, 2), h, None)):
            c = sk.addConstraint(Sketcher.Constraint(kind, a[0], a[1], b[0], b[1], value))
            if name:
                sk.renameConstraint(c, name)
        pocket = self.bodyA.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = sk
        pocket.Type = "ThroughAll"
        pocket.Midplane = True
        self.doc.recompute()
        self.assertValid(pocket)
        return sk, pocket

    def testMeasuredEdgeTrimmedBetween(self):
        """A pocket clear of A's top front edge (y = 0, z = 5) at the pick, then moved to notch it:
        the edge is 0..15 in the studio's result, so w reads 15 (it read 20, from PadA's untrimmed
        edge, with no warning, on e8fdaa630e)."""
        sk, pocket = self.pocket_rect(15, 6, 6, 5)
        top_front = lambda e: (isinstance(e.Curve, Part.Line)
                               and Part.Vertex(V(5, 0, 5)).distToShape(e)[0] < 1e-6)
        edge = edge_named(self.bodyA.Shape, top_front)
        ref = self.measured.resolve_pick(self.studio, "{}.{}".format(self.bodyA.Name, edge))
        holder, m = self.measured.add(self.studio, "w", "Length", [ref])
        pad = self.make_user("#w")
        self.doc.recompute()
        self.assertValid(m, holder, pad)
        self.assertAlmostEqual(holder.w.Value, 20, places=6)
        sk.setDatum("PY", App.Units.Quantity("-1 mm"))
        self.doc.recompute()
        trimmed = self.bodyA.Shape.getElement(edge_named(self.bodyA.Shape, top_front))
        self.assertAlmostEqual(trimmed.Length, 15, places=6)  # the model is what the case says
        self.assertValid(m, holder, pad)
        self.assertAlmostEqual(holder.w.Value, 15, places=6)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 15, places=6)

    def testMeasuredDistanceBodyMoved(self):
        """d is the distance between A's face x = 20 and a second body's face x = 30 (10); moving
        that body by its Placement (x + 5) makes it 15 (it stayed 10 on e8fdaa630e: the body's
        placement was ignored, and nothing recomputed the measurement)."""
        body2 = self.doc.addObject("PartDesign::Body", "Body2")
        self.studio.addObject(body2)
        sk = self.sketch(body2, "Sketch2")
        rectangle(sk, 30, 0, 10, 10)
        pad2 = body2.newObject("PartDesign::Pad", "Pad2")
        pad2.Profile = sk
        pad2.Length = 5
        self.doc.recompute()
        f1 = face_named(self.bodyA.Shape, lambda f: abs(f.CenterOfMass.x - 20) < 1e-6)
        f2 = face_named(body2.Shape, lambda f: abs(f.CenterOfMass.x - 30) < 1e-6)
        refs = [self.measured.resolve_pick(self.studio, "{}.{}".format(self.bodyA.Name, f1)),
                self.measured.resolve_pick(self.studio, "{}.{}".format(body2.Name, f2))]
        holder, m = self.measured.add(self.studio, "d", "Distance", refs)
        pad = self.make_user("#d")
        self.doc.recompute()
        self.assertValid(m, holder, pad)
        self.assertAlmostEqual(holder.d.Value, 10, places=6)
        body2.Placement = App.Placement(V(5, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertValid(m, holder, pad)
        self.assertAlmostEqual(holder.d.Value, 15, places=6)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 15, places=6)
        # read in the studio's frame: moving the studio itself changes nothing
        self.studio.Placement = App.Placement(V(0, 7, 3), App.Rotation(V(0, 0, 1), 30))
        self.doc.recompute()
        self.assertAlmostEqual(holder.d.Value, 15, places=6)

    def testPickOfASketchEdge(self):
        line = "Edge1"
        feature, element = self.measured.resolve_pick(
            self.studio, "{}.{}.{}".format(self.bodyA.Name, self.sketchA.Name, line))
        self.assertIs(feature, self.sketchA)
        self.assertEqual(element, line)

    def testPickByMappedNameResolvesToTheIndexedName(self):
        """The selection hands its observers the mapped name of a shape with an element map
        (Gui::SelectionSingleton::checkSelection), with or without the ';' prefix: it is read
        as the edge it names."""
        edge = edge_named(self.padA.Shape, bottom_long)
        mapped = self.padA.Shape.getElementName(edge, 1)
        self.assertNotEqual(mapped, edge, "the pad's shape has no element map")
        for name in (mapped, ";" + mapped.lstrip(";")):
            feature, element = self.measured.resolve_pick(
                self.studio, "{}.{}.{}".format(self.bodyA.Name, self.padA.Name, name))
            self.assertIs(feature, self.padA)
            self.assertEqual(element, edge)

    def testPickOfAWholeObjectRefused(self):
        with self.assertRaises(self.measured.MeasureError):
            self.measured.resolve_pick(self.studio, "{}.{}.".format(self.bodyA.Name, self.padA.Name))


    def testPickThroughALinkRefused(self):
        """A link's instance is elsewhere than its original: a pick through it is refused rather
        than measuring the original's place."""
        box = self.doc.addObject("Part::Box", "Block")
        self.studio.addObject(box)
        link = self.doc.addObject("App::Link", "BlockLink")
        link.LinkedObject = box
        link.Placement = App.Placement(V(50, 0, 0), App.Rotation())
        self.studio.addObject(link)
        self.doc.recompute()
        feature, element = self.measured.resolve_pick(self.studio, "Block.Edge1")
        self.assertIs(feature, box)
        with self.assertRaisesRegex(self.measured.MeasureError, "link"):
            self.measured.resolve_pick(self.studio, "BlockLink.Edge1")

    # --- measured variables 3: Onshape's answers (notes/onshape-facts.md MV1-MV5 in the ops repo),
    # on the oracle's own geometry: two cylinders r5 h10 with centres 20 apart, a cone, a sphere

    def cylinders(self):
        """Two cylinders r5 h10 standing on XY, centres (100, 0) and (120, 0)."""
        made = []
        for i, x in enumerate((100, 120)):
            c = self.doc.addObject("Part::Cylinder", "Cyl%d" % i)
            c.Radius = 5
            c.Height = 10
            c.Placement = App.Placement(V(x, 0, 0), App.Rotation())
            self.studio.addObject(c)
            made.append(c)
        self.doc.recompute()
        return made

    @staticmethod
    def circle_at(z, r=5):
        return lambda e: (isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - r) < 1e-6
                          and abs(e.BoundBox.ZMin - z) < 1e-6 and abs(e.BoundBox.ZMax - z) < 1e-6)

    @staticmethod
    def surface_of(kind):
        return lambda f: isinstance(f.Surface, kind)

    def tops(self):
        a, b = self.cylinders()
        return (a, edge_named(a.Shape, self.circle_at(10))), (b, edge_named(b.Shape, self.circle_at(10)))

    def testDistanceOfTwoCirclesAsOnshape(self):
        """MV1: two top circle edges, centres 20 apart: Minimum 10 (the gap), Maximum 30, Minimum
        with Use axis 20, Maximum with Use axis 30 (Onshape hides the option then)."""
        ta, tb = self.tops()
        for options, want in (({}, 10), ({"distance_type": "Maximum"}, 30), ({"use_axis": True}, 20),
                              ({"distance_type": "Maximum", "use_axis": True}, 30)):
            self.assertAlmostEqual(self.measured.measure("Distance", [ta, tb], **options), want,
                                   places=9, msg=str(options))
        holder, m = self.measured.add(self.studio, "far", "Distance", [ta, tb], distance_type="Maximum")
        self.doc.recompute()
        self.assertValid(m, holder)
        self.assertAlmostEqual(holder.far.Value, 30, places=9)

    def testDistanceValueToRecord(self):
        """MV1: Value to record X is 10 from either pick order (unsigned), Y 0; Use axis with X 20."""
        ta, tb = self.tops()
        measure = self.measured.measure
        self.assertAlmostEqual(measure("Distance", [ta, tb], record="X"), 10, places=9)
        self.assertAlmostEqual(measure("Distance", [tb, ta], record="X"), 10, places=9)
        self.assertAlmostEqual(measure("Distance", [ta, tb], record="Y"), 0, places=9)
        self.assertAlmostEqual(measure("Distance", [ta, tb], record="Z"), 0, places=9)
        self.assertAlmostEqual(measure("Distance", [tb, ta], record="X", use_axis=True), 20, places=9)
        self.assertAlmostEqual(measure("Distance", [ta, tb], record="X", distance_type="Maximum"),
                               30, places=9)
        d, x, y, z = self.measured.distance_components([tb, ta])
        self.assertAlmostEqual(d, 10, places=9)
        self.assertAlmostEqual(x, 10, places=9)
        holder, m = self.measured.add(self.studio, "dx", "Distance", [tb, ta], record="X", use_axis=True)
        self.doc.recompute()
        self.assertValid(m, holder)
        self.assertAlmostEqual(holder.dx.Value, 20, places=9)

    def testDistanceOfCylinderFacesAndOneCylinder(self):
        """MV1: two cylinder faces 10, with Use axis 20 (axis to axis); a top and the bottom edge of
        one cylinder 10 (its height)."""
        a, b = self.cylinders()
        fa = (a, face_named(a.Shape, self.surface_of(Part.Cylinder)))
        fb = (b, face_named(b.Shape, self.surface_of(Part.Cylinder)))
        measure = self.measured.measure
        self.assertAlmostEqual(measure("Distance", [fa, fb]), 10, places=9)
        self.assertAlmostEqual(measure("Distance", [fa, fb], use_axis=True), 20, places=9)
        top, bottom = (a, edge_named(a.Shape, self.circle_at(10))), (a, edge_named(a.Shape, self.circle_at(0)))
        self.assertAlmostEqual(measure("Distance", [top, bottom]), 10, places=9)

    def testMaximumOfTwoFaces(self):
        """PadA's faces x = 0 and x = 20 (each 10 x 5): farthest corner to corner, sqrt(20^2 + 10^2 + 5^2)."""
        x0 = (self.padA, face_named(self.padA.Shape, lambda f: f.BoundBox.XMax < 1e-6))
        x1 = (self.padA, face_named(self.padA.Shape, lambda f: f.BoundBox.XMin > 20 - 1e-6))
        d, x, y, z = self.measured.distance_components([x0, x1], distance_type="Maximum")
        self.assertAlmostEqual(d, (20 ** 2 + 10 ** 2 + 5 ** 2) ** 0.5, places=9)
        self.assertEqual((round(x, 9), round(y, 9), round(z, 9)), (20, 10, 5))

    def testLengthAsOnshape(self):
        """MV2: edges summed (one circle 2 pi 5, two, three); a face beside an edge ignored; a face
        alone refused; Radius ignored."""
        ta, tb = self.tops()
        a = ta[0]
        bottom = (a, edge_named(a.Shape, self.circle_at(0)))
        side = (a, face_named(a.Shape, self.surface_of(Part.Cylinder)))
        measure = self.measured.measure
        circle = 2 * math.pi * 5
        self.assertAlmostEqual(measure("Length", [ta]), circle, places=9)
        self.assertAlmostEqual(measure("Length", [ta, tb]), 2 * circle, places=9)
        self.assertAlmostEqual(measure("Length", [ta, tb, bottom]), 3 * circle, places=9)
        self.assertAlmostEqual(measure("Length", [side, ta]), circle, places=9)
        self.assertAlmostEqual(measure("Length", [ta], radius=True), circle, places=9)
        with self.assertRaisesRegex(self.measured.MeasureError, "select edges to measure"):
            measure("Length", [side])
        holder, m = self.measured.add(self.studio, "w", "Length", [ta, side])
        self.doc.recompute()
        self.assertValid(m, holder)
        self.assertAlmostEqual(holder.w.Value, circle, places=9)

    def testLengthOfAWireBody(self):
        """MV2: a wire body (here a sketch, picked whole) sums its edges: A's rectangle, 60."""
        sub = "{}.{}.".format(self.bodyA.Name, self.sketchA.Name)
        ref = self.measured.resolve_pick(self.studio, sub, wire_body=True)
        self.assertEqual((ref[0].Name, ref[1]), (self.sketchA.Name, ""))
        with self.assertRaises(self.measured.MeasureError):  # not for Distance or Diameter
            self.measured.resolve_pick(self.studio, sub)
        with self.assertRaises(self.measured.MeasureError):  # a solid is no wire body
            self.measured.resolve_pick(self.studio, "{}.{}.".format(self.bodyA.Name, self.padA.Name),
                                       wire_body=True)
        holder, m = self.measured.add(self.studio, "p", "Length", [ref])
        self.doc.recompute()
        self.assertValid(m, holder)
        self.assertAlmostEqual(holder.p.Value, 60, places=9)
        self.sketchA.setDatum("W", App.Units.Quantity("30 mm"))
        self.doc.recompute()
        self.assertAlmostEqual(holder.p.Value, 80, places=9)

    def testDiameterAsOnshape(self):
        """MV3: a circle edge 10, with Radius 5; a cylinder face 10; a sphere face 10; a sketch arc
        (half a circle r5) 10; a cone's circular edge 10. A cone face and a plane are refused."""
        ta, _tb = self.tops()
        a = ta[0]
        sphere = self.doc.addObject("Part::Sphere", "Ball")
        sphere.Radius = 5
        sphere.Placement = App.Placement(V(140, 0, 0), App.Rotation())
        cone = self.doc.addObject("Part::Cone", "Cone")
        cone.Radius1, cone.Radius2, cone.Height = 5, 3, 10
        cone.Placement = App.Placement(V(160, 0, 0), App.Rotation())
        arc = self.doc.addObject("Sketcher::SketchObject", "ArcSketch")
        arc.addGeometry(Part.ArcOfCircle(Part.Circle(V(180, 0, 0), V(0, 0, 1), 5), 0, math.pi))
        for o in (sphere, cone, arc):
            self.studio.addObject(o)
        self.doc.recompute()
        measure = self.measured.measure
        self.assertAlmostEqual(measure("Diameter", [ta]), 10, places=9)
        self.assertAlmostEqual(measure("Diameter", [ta], radius=True), 5, places=9)
        side = (a, face_named(a.Shape, self.surface_of(Part.Cylinder)))
        self.assertAlmostEqual(measure("Diameter", [side]), 10, places=9)
        ball = (sphere, face_named(sphere.Shape, self.surface_of(Part.Sphere)))
        self.assertAlmostEqual(measure("Diameter", [ball]), 10, places=9)
        self.assertAlmostEqual(measure("Diameter", [(arc, "Edge1")]), 10, places=9)
        self.assertAlmostEqual(measure("Diameter", [(cone, edge_named(cone.Shape, self.circle_at(0)))]),
                               10, places=9)
        conical = (cone, face_named(cone.Shape, self.surface_of(Part.Cone)))
        with self.assertRaisesRegex(self.measured.MeasureError, "is a cone face"):
            measure("Diameter", [conical])
        plane = (cone, face_named(cone.Shape, lambda f: isinstance(f.Surface, Part.Plane)
                                  and f.BoundBox.ZMin > 10 - 1e-6))
        with self.assertRaisesRegex(self.measured.MeasureError, "select an entity to measure"):
            measure("Diameter", [plane])
        holder, m = self.measured.add(self.studio, "r", "Diameter", [ball], radius=True)
        self.doc.recompute()
        self.assertValid(m, holder)
        self.assertAlmostEqual(holder.r.Value, 5, places=9)

    def testVariableStudioRefused(self):
        """MV5: a Variable Studio holds no measured variable (it has no geometry to measure)."""
        studio = self.doc.addObject("App::VarSet", "VarSet")
        studio.Label = "Variable Studio 1"
        App.DocumentTabs.setVariableStudio(studio)
        edge = edge_named(self.padA.Shape, bottom_long)
        with self.assertRaisesRegex(ValueError, "Variable Studio"):
            self.measured.add(studio, "w", "Length", [(self.padA, edge)])
        self.assertEqual([p for p in studio.PropertiesList if p == "w"], [])



if __name__ == "__main__":
    unittest.main()
