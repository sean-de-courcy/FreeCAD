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

    def testDistanceMinimumAndCenter(self):
        self.sketchA.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 2))
        self.sketchA.addGeometry(Part.Circle(V(15, 5, 0), V(0, 0, 1), 2))
        self.doc.recompute()
        a = edge_named(self.padA.Shape, bottom_circle(5))
        b = edge_named(self.padA.Shape, bottom_circle(15))
        vs, low = self.measured.add(self.studio, "gap", "Distance", [(self.padA, a), (self.padA, b)])
        hp, mid = self.measured.add(self.studio, "pitch", "Distance", [(self.padA, a), (self.padA, b)],
                                   distance_type="Center")
        x0 = face_named(self.padA.Shape, lambda f: f.BoundBox.XMax < 1e-6)
        x1 = face_named(self.padA.Shape, lambda f: f.BoundBox.XMin > 20 - 1e-6)
        hs, faces = self.measured.add(self.studio, "span", "Distance", [(self.padA, x0), (self.padA, x1)])
        self.doc.recompute()
        self.assertValid(low, mid, faces, vs, hp, hs)
        self.assertAlmostEqual(vs.gap.Value, 10 - 2 * 2, places=6)
        self.assertAlmostEqual(hp.pitch.Value, 10, places=6)
        self.assertAlmostEqual(hs.span.Value, 20, places=6)

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
        self.assertIn("takes edges", m.getStatusString())
        self.assertIn("Invalid", d.State)
        self.assertIn("is not one", d.getStatusString())

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
        self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        with self.assertRaises(ValueError):
            self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])  # name taken

    def testSaveAndRestore(self):
        edge = edge_named(self.padA.Shape, bottom_long)
        vs, m = self.measured.add(self.studio, "w", "Length", [(self.padA, edge)])
        self.make_user("#w")
        self.doc.recompute()
        names = m.Name, vs.Name
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "measured.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            m = self.doc.getObject(names[0])
            self.assertEqual(m.Format, 1)
            self.assertEqual(m.Kind, "Length")
            self.doc.getObject("SketchA").setDatum("W", App.Units.Quantity("25 mm"))
            self.doc.recompute()
            pad = self.doc.getObject("PadB")
            self.assertAlmostEqual(self.doc.getObject(names[1]).w.Value, 25, places=6)
            self.assertAlmostEqual(pad.Shape.Volume, 16 * 25, places=4)
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

    def testPickResolvesToTheFeatureThatMadeIt(self):
        """An edge a later pad left alone, picked on the tip, names the first pad's edge."""
        pad2 = self.side_pad(x=5, y=2, z=5, length=3)  # on top, away from the bottom edges
        tip_edge = edge_named(pad2.Shape, bottom_long)
        feature, element = self.measured.resolve_pick(
            self.studio, "{}.{}.{}".format(self.bodyA.Name, pad2.Name, tip_edge))
        self.assertIs(feature, self.padA)
        self.assertEqual(element, edge_named(self.padA.Shape, bottom_long))
        # through the body (its shape is the tip's)
        feature, element = self.measured.resolve_pick(
            self.studio, "{}.{}".format(self.bodyA.Name, tip_edge))
        self.assertIs(feature, self.padA)
        # a face
        bottom = face_named(pad2.Shape, lambda f: f.BoundBox.ZMax < 1e-6)
        feature, element = self.measured.resolve_pick(
            self.studio, "{}.{}.{}".format(self.bodyA.Name, pad2.Name, bottom))
        self.assertIs(feature, self.padA)
        self.assertEqual(element, face_named(self.padA.Shape, lambda f: f.BoundBox.ZMax < 1e-6))

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
        """Resolved to the first pad, the pick can drive the later pad that showed it."""
        pad2 = self.side_pad(x=5, y=2, z=5, length=3)
        tip_edge = edge_named(pad2.Shape, bottom_long)
        ref = self.measured.resolve_pick(
            self.studio, "{}.{}.{}".format(self.bodyA.Name, pad2.Name, tip_edge))
        holder, m = self.measured.add(self.studio, "w", "Length", [ref])
        pad2.setExpression("Length", "#w / 4")
        self.doc.recompute()
        self.assertValid(m, holder, pad2)
        self.assertAlmostEqual(pad2.Length.Value, 5, places=6)

    def testPickOfASketchEdge(self):
        line = "Edge1"
        feature, element = self.measured.resolve_pick(
            self.studio, "{}.{}.{}".format(self.bodyA.Name, self.sketchA.Name, line))
        self.assertIs(feature, self.sketchA)
        self.assertEqual(element, line)

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


if __name__ == "__main__":
    unittest.main()
