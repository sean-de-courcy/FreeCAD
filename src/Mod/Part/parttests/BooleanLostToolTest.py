# SPDX-License-Identifier: LGPL-2.1-or-later

"""A Cut or Fuse that loses a tool solid lying inside its base fails loudly (FreeCAD-CH ops#472).

OCCT's solid builder can take a base's outer shell for a hole when the shell has a long, steep
B-spline face (the infinite-point classification, as in ops#426). A tool wholly inside the base
then leaves no trace: the cut returns the base without the void, and the fuse keeps the tool as a
second, overlapping solid, both silently. FCBRepAlgoAPIHelper::checkLostTools turns that into an
error.

Designed models: the prism under the wave x = 4 (1 - cos(2 pi y / period)), interpolated at integer
y into one cubic B-spline of `spans` spans, closed by x = -5 and extruded 10 in z. The tool is the
box [-4, -2] x [5, 7] x [4, 6], 1 from every face of the prism. The solid builder fails at 1000
spans with period 10 and at 600 spans with period 8 (both amplitude 4), and is right at 990 spans.
A correct cut has a void: 2 shells, and the unit cube at the box's centre has no common part with
the result. A correct fuse is the prism: 1 solid with the prism's faces. The lost-tool tests accept
either that result or the error, so they also hold once the result is repaired instead of refused.

The other cases must not raise: voids in a block, a cut through its top, tools outside, in an L's
notch, touching a face from outside, in another tool's cavity, and in the wave's trough."""

import math
import unittest

import FreeCAD as App
import Part

V = App.Vector


def wavePrism(spans, period=10.0, amplitude=4.0):
    """The prism under the wave, closed by x = -5 and extruded 10 in z."""
    points = [
        V(amplitude * (1 - math.cos(2 * math.pi * y / period)), y, 0) for y in range(spans + 1)
    ]
    wave = Part.BSplineCurve()
    wave.interpolate(points)
    corners = [points[-1], V(-5, spans, 0), V(-5, 0, 0), V(0, 0, 0)]
    edges = [wave.toShape()] + [Part.makeLine(a, b) for a, b in zip(corners, corners[1:])]
    return Part.Face(Part.Wire(edges)).extrude(V(0, 0, 10)).Solids[0]


def innerBox():
    """The box 1 from every face of the wave prisms."""
    return Part.makeBox(2, 2, 2, V(-4, 5, 4))


def notchBox():
    """A box 1 deep through the prisms' face x = -5: a notch that changes the outer shell."""
    return Part.makeBox(2, 1, 1, V(-6, 50, 4))


def vertexDownCube(position):
    """The 2 mm cube turned about its centre so that its first vertex is its lowest point, then
    moved to put that vertex at position: on a face there, it touches the face at that vertex only
    """
    cube = Part.makeBox(2, 2, 2)
    centre = V(1, 1, 1)
    direction = cube.Vertexes[0].Point - centre
    direction.normalize()
    cube.Placement = App.Placement(V(0, 0, 0), App.Rotation(direction, V(0, 0, -1)), centre)
    cube = cube.copy()
    cube.translate(position - cube.Vertexes[0].Point)
    return cube


def unitCube(centre):
    return Part.makeBox(1, 1, 1, centre - V(0.5, 0.5, 0.5))


def lShape():
    """The 20 x 20 x 10 block without its quarter [10, 20] x [10, 20]."""
    return Part.makeBox(20, 20, 10).cut(Part.makeBox(10, 10, 10, V(10, 10, 0)))


class BooleanLostToolTest(unittest.TestCase):
    def setUp(self):
        self.doc = None

    def tearDown(self):
        if self.doc:
            App.closeDocument(self.doc.Name)

    def assertLostToolError(self, error, operation):
        self.assertIn(operation, str(error))
        self.assertIn("ops#472", str(error))

    def assertVoid(self, result, tool, faces):
        """The cut kept the tool as a void: one more shell, the tool's faces, and no material
        around the tool's centre."""
        self.assertEqual(len(result.Solids), 1)
        self.assertEqual(len(result.Shells), 2)
        self.assertEqual(len(result.Faces), faces)
        centre = tool.BoundBox.Center
        self.assertAlmostEqual(result.common(unitCube(centre)).Volume, 0.0, places=6)

    def assertUnchanged(self, result, base):
        """The boolean removed and added nothing: the base's faces and solids."""
        self.assertEqual(len(result.Solids), len(base.Solids))
        self.assertEqual(len(result.Faces), len(base.Faces))
        self.assertAlmostEqual(result.Volume, base.Volume, places=6)

    def checkVoidCut(self, prism, tool=None):
        tool = tool or innerBox()
        try:
            result = prism.cut(tool)
        except Exception as error:  # the loud check
            self.assertLostToolError(error, "Cut")
            return
        self.assertVoid(result, tool, len(prism.Faces) + 6)

    def checkInnerFuse(self, prism):
        try:
            result = prism.fuse(innerBox())
        except Exception as error:  # the loud check
            self.assertLostToolError(error, "Fuse")
            return
        self.assertEqual(len(result.Solids), 1)
        self.assertEqual(len(result.Faces), len(prism.Faces))

    # Lost tools: silently wrong before ops#472, an error since

    def testVoidCutPeriod10Spans1000(self):
        self.checkVoidCut(wavePrism(1000))

    def testVoidCutPeriod8Spans600(self):
        self.checkVoidCut(wavePrism(600, period=8.0))

    def testInnerFusePeriod10Spans1000(self):
        self.checkInnerFuse(wavePrism(1000))

    def testInnerFusePeriod8Spans600(self):
        self.checkInnerFuse(wavePrism(600, period=8.0))

    def testVoidCutOfCompound(self):
        """A compound of one solid, as every boolean returns, takes one build: checked."""
        self.checkVoidCut(Part.makeCompound([wavePrism(1000)]))

    def testVoidCutAfterCut(self):
        notched = wavePrism(1000).cut(notchBox())
        self.assertEqual(notched.ShapeType, "Compound")
        self.checkVoidCut(notched)

    def testVoidCutVertexOnBoundary(self):
        """The tool's first vertex lies on the prism's face z = 0: the next one decides."""
        tool = vertexDownCube(V(-3, 6, 0))
        self.assertAlmostEqual(tool.BoundBox.ZMin, 0.0, places=9)
        self.checkVoidCut(wavePrism(1000), tool)

    def testChainedPartCut(self):
        """Part::Cut on a Part::Cut: its base is a compound."""
        self.doc = App.newDocument("BooleanLostToolChain")
        base = self.doc.addObject("Part::Feature", "Wave")
        base.Shape = wavePrism(1000)
        notch = self.doc.addObject("Part::Feature", "Notch")
        notch.Shape = notchBox()
        tool = self.doc.addObject("Part::Feature", "Box")
        tool.Shape = innerBox()
        first = self.doc.addObject("Part::Cut", "Notched")
        first.Base = base
        first.Tool = notch
        second = self.doc.addObject("Part::Cut", "Cut")
        second.Base = first
        second.Tool = tool
        self.doc.recompute()
        self.assertTrue(first.isValid())
        if not second.isValid():
            self.assertIn("ops#472", second.getStatusString())
        else:
            self.assertVoid(second.Shape, tool.Shape, len(first.Shape.Faces) + 6)

    def testPartCutFeature(self):
        """Part::Cut builds its boolean itself, not through makeElementBoolean."""
        self.doc = App.newDocument("BooleanLostToolCut")
        base = self.doc.addObject("Part::Feature", "Wave")
        base.Shape = wavePrism(1000)
        tool = self.doc.addObject("Part::Feature", "Box")
        tool.Shape = innerBox()
        cut = self.doc.addObject("Part::Cut", "Cut")
        cut.Base = base
        cut.Tool = tool
        self.doc.recompute()
        if not cut.isValid():
            self.assertIn("ops#472", cut.getStatusString())
        else:
            self.assertVoid(cut.Shape, tool.Shape, len(base.Shape.Faces) + 6)

    def testPartMultiFuseFeature(self):
        """Part::MultiFuse builds its boolean itself too."""
        self.doc = App.newDocument("BooleanLostToolFuse")
        base = self.doc.addObject("Part::Feature", "Wave")
        base.Shape = wavePrism(1000)
        tool = self.doc.addObject("Part::Feature", "Box")
        tool.Shape = innerBox()
        fuse = self.doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [base, tool]
        self.doc.recompute()
        if not fuse.isValid():
            self.assertIn("ops#472", fuse.getStatusString())
        else:
            self.assertEqual(len(fuse.Shape.Solids), 1)
            self.assertEqual(len(fuse.Shape.Faces), len(base.Shape.Faces))

    # No false positives: right before and after

    def testVoidCut990Spans(self):
        prism = wavePrism(990)
        tool = innerBox()
        self.assertVoid(prism.cut(tool), tool, len(prism.Faces) + 6)

    def testVoidsInBlock(self):
        block = Part.makeBox(20, 20, 10)
        for tool, faces in (
            (Part.makeBox(2, 2, 2, V(5, 5, 4)), 12),
            (Part.makeCylinder(2, 2, V(10, 10, 4)), 9),
            (Part.makeSphere(2, V(10, 10, 5)), 7),
        ):
            with self.subTest(tool=tool.ShapeType + str(len(tool.Faces))):
                self.assertVoid(block.cut(tool), tool, faces)

    def testVertexOnBoundaryInBlock(self):
        """The rotated cube touching a block's bottom at one vertex: a void, no error."""
        block = Part.makeBox(20, 20, 10)
        tool = vertexDownCube(V(10, 10, 0))
        result = block.cut(tool)
        self.assertEqual(len(result.Faces), 12)
        self.assertAlmostEqual(result.common(unitCube(tool.BoundBox.Center)).Volume, 0.0, places=6)

    def testInnerFuseInBlock(self):
        block = Part.makeBox(20, 20, 10)
        self.assertUnchanged(block.fuse(Part.makeBox(2, 2, 2, V(5, 5, 4))), block)

    def testCutThroughTop(self):
        block = Part.makeBox(20, 20, 10)
        result = block.cut(Part.makeBox(2, 2, 8, V(5, 5, 4)))
        self.assertEqual(len(result.Shells), 1)
        self.assertAlmostEqual(result.Volume, 20 * 20 * 10 - 2 * 2 * 6, places=6)

    def testToolOutside(self):
        block = Part.makeBox(20, 20, 10)
        tool = Part.makeBox(2, 2, 2, V(30, 5, 4))
        self.assertUnchanged(block.cut(tool), block)
        fused = block.fuse(tool)
        self.assertEqual(len(fused.Solids), 2)

    def testToolInNotch(self):
        """Inside the L's bounding box, outside its material."""
        lshape = lShape()
        tool = Part.makeBox(2, 2, 2, V(14, 14, 4))
        self.assertUnchanged(lshape.cut(tool), lshape)
        self.assertEqual(len(lshape.fuse(tool).Solids), 2)

    def testToolTouchingFromOutside(self):
        """In the notch, one face on the L's face y = 10: its vertices there classify ON."""
        lshape = lShape()
        result = lshape.cut(Part.makeBox(2, 2, 2, V(14, 10, 4)))
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume, lshape.Volume, places=6)

    def testToolInsideAnotherToolsCavity(self):
        """A tool inside another tool leaves no trace in a right cut, and lies in the void."""
        block = Part.makeBox(20, 20, 10)
        outer = Part.makeBox(6, 6, 6, V(5, 5, 2))
        inner = Part.makeBox(2, 2, 2, V(7, 7, 4))
        self.assertVoid(block.cut([outer, inner]), outer, 12)

    def testFuseIntoCavity(self):
        """A solid inside a void, touching nothing, stays a solid of its own."""
        hollow = Part.makeBox(20, 20, 10).cut(Part.makeBox(6, 6, 6, V(5, 5, 2)))
        result = hollow.fuse(Part.makeBox(2, 2, 2, V(7, 7, 4)))
        self.assertEqual(len(result.Solids), 2)

    def testToolInWaveTrough(self):
        """Outside the 1000-span prism, between two crests, inside its bounding box."""
        prism = wavePrism(1000)
        self.assertUnchanged(prism.cut(Part.makeBox(1, 2, 2, V(3, 99, 4))), prism)


if __name__ == "__main__":
    unittest.main()
