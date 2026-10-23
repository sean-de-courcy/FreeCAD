# SPDX-License-Identifier: LGPL-2.1-or-later

"""Part::Refine, Part::Reverse and Part::Scale keep the element map of their source (FreeCAD-CH
ops#453).

Designed model: two 10 mm boxes side by side, A at the origin and B at x = 10, fused into one
20 x 10 x 10 block (6 faces, 12 edges): by a Part::Refine of the unrefined fuse, or by the fuse's own
Refine under a Part::Reverse or a Part::Scale (uniform by 2, or by 2 along X only). A
Part::DatumPoint sits at the centre of each of the result's edges, and a Part::Fillet rounds the
bottom edge at the block's far end in X (radius 1; not on the Reverse, whose solid is inside out).

Each edit below leaves seven of the block's twelve edges exactly where they were, listed by their
midpoints in the block (a Scale's result has them scaled). A reference to one of those must stay on
it; a reference to any other edge must stay on an edge of its own direction or break loudly, and
never land on one of the seven unchanged edges. Without the map (a bare shape from
removeSplitter(), Reversed() or BRepBuilderAPI_Transform in their execute()) the references went by
index: all twelve points on a Refine moved to other edges silently, by 2.5 to 20 mm."""

import unittest

import FreeCAD as App
import Part

V = App.Vector
TOL = 1e-6

# The bottom edge at the block's far end the fillet rounds; it is unchanged by every edit
FILLET_EDGE = (20, 5, 0)

EDITS = {
    # B lower: the top faces no longer merge
    "B.Height 10 -> 5": (
        lambda a, b: setattr(b, "Height", 5),
        [(0, 5, 0), (0, 0, 5), (0, 10, 5), (0, 5, 10), (10, 0, 0), (10, 10, 0), (20, 5, 0)],
    ),
    # A taller: the top faces no longer merge, B's end stays
    "A.Height 10 -> 15": (
        lambda a, b: setattr(a, "Height", 15),
        [(20, 5, 0), (20, 0, 5), (20, 10, 5), (20, 5, 10), (0, 5, 0), (10, 0, 0), (10, 10, 0)],
    ),
}

# How each feature puts the block into its result: (its setup, the block's point -> the result's)
TARGETS = {
    "Refine": (None, lambda p: V(*p)),
    "Reverse": (None, lambda p: V(*p)),
    "Scale": ({"Uniform": True, "UniformScale": 2}, lambda p: V(*p) * 2),
    "Scale along X": (
        {"Uniform": False, "XScale": 2, "YScale": 1, "ZScale": 1},
        lambda p: V(2 * p[0], p[1], p[2]),
    ),
}


def midpoint(edge):
    return edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)


def direction(edge):
    return (edge.Vertexes[-1].Point - edge.Vertexes[0].Point).normalize()


def edgeAt(shape, point):
    """The index of the edge of `shape` whose midpoint is `point`, or None."""
    for i, edge in enumerate(shape.Edges, 1):
        if (midpoint(edge) - point).Length < TOL:
            return i
    return None


class RefineElementMapTest(unittest.TestCase):
    def setUp(self):
        self.doc = None

    def tearDown(self):
        if self.doc:
            App.closeDocument(self.doc.Name)
            self.doc = None

    def model(self, target):
        """The block as `target` makes it, recomputed; the fuse and the target."""
        self.tearDown()
        self.doc = doc = App.newDocument("RefineElementMapTest")
        self.a = doc.addObject("Part::Box", "A")
        self.b = doc.addObject("Part::Box", "B")
        self.b.Placement = App.Placement(V(10, 0, 0), App.Rotation())
        fuse = doc.addObject("Part::Fuse", "Fuse")
        fuse.Base, fuse.Tool = self.a, self.b
        fuse.Refine = target != "Refine"
        setup = TARGETS[target][0]
        if target == "Refine":
            result = doc.addObject("Part::Refine", "Refine")
            result.Source = fuse
        elif target == "Reverse":
            result = doc.addObject("Part::Reverse", "Reverse")
            result.Source = fuse
        else:
            result = doc.addObject("Part::Scale", "Scale")
            result.Base = fuse
            for name, value in setup.items():
                setattr(result, name, value)
        doc.recompute()
        self.assertTrue(result.isValid(), result.getStatusString())
        return fuse, result

    def testResultNamesEveryElement(self):
        """Each result has an element map that names each of its faces, edges and vertexes.
        Their execute() dropped it: ElementMapSize 0, no edge named."""
        for target in TARGETS:
            with self.subTest(target=target):
                fuse, result = self.model(target)
                if target == "Refine":
                    # The Refine merges the fuse's split faces
                    self.assertEqual(len(fuse.Shape.Faces), 10)
                shape = result.Shape
                self.assertEqual(
                    (len(shape.Faces), len(shape.Edges), len(shape.Vertexes)), (6, 12, 8)
                )
                self.assertGreater(shape.ElementMapSize, 0)
                for kind, elements in (("Face", shape.Faces), ("Edge", shape.Edges),
                                       ("Vertex", shape.Vertexes)):
                    for i in range(1, len(elements) + 1):
                        name = "%s%d" % (kind, i)
                        self.assertTrue(shape.ElementReverseMap.get(name), name)

    def warned(self, obj):
        return any(
            entry.get("warning_level") not in (None, "", "none")
            for entry in App.getReferenceReport(obj)
        )

    def testReferencesStayOnTheirEdges(self):
        for target in TARGETS:
            for name, (edit, unchanged) in EDITS.items():
                with self.subTest(target=target, edit=name):
                    self.referencesStayOnTheirEdges(target, edit, unchanged)

    def referencesStayOnTheirEdges(self, target, edit, unchanged):
        _, result = self.model(target)
        doc, place = self.doc, TARGETS[target][1]
        points = []
        for i, edge in enumerate(result.Shape.Edges, 1):
            point = doc.addObject("Part::DatumPoint", "P%d" % i)
            point.AttachmentSupport = [(result, "Edge%d" % i)]
            point.MapMode = "CenterOfMass"
            points.append((point, midpoint(edge), direction(edge)))
        fillet = None
        if target != "Reverse":  # a reversed solid is inside out: nothing to round
            fillet = doc.addObject("Part::Fillet", "Fillet")
            fillet.Base = result
            fillet.Edges = [(edgeAt(result.Shape, place(FILLET_EDGE)), 1.0, 1.0)]
        doc.recompute()
        for point, at, _ in points:
            self.assertLess((point.Placement.Base - at).Length, TOL, point.Name)

        edit(self.a, self.b)
        doc.recompute()
        shape = result.Shape
        self.assertTrue(result.isValid(), result.getStatusString())
        unchangedPoints = [place(m) for m in unchanged]
        # The model: the unchanged edges are still there, as they were
        for m in unchangedPoints:
            self.assertIsNotNone(edgeAt(shape, m), m)

        for point, at, along in points:
            if any((at - m).Length < TOL for m in unchangedPoints):
                # The edge is unchanged: the reference stays on it
                self.assertTrue(point.isValid(), "%s: %s" % (point.Name, point.getStatusString()))
                self.assertLess(
                    (point.Placement.Base - at).Length, TOL,
                    "%s on the unchanged edge at %s moved to %s" % (point.Name, at, point.Placement.Base),
                )
                continue
            if not point.isValid() or self.warned(point):
                continue  # broken or warned: loud
            now = point.Placement.Base
            self.assertFalse(
                any((now - m).Length < TOL for m in unchangedPoints),
                "%s on the edge at %s moved silently onto another edge, at %s" % (point.Name, at, now),
            )
            index = int(point.AttachmentSupport[0][1][0][len("Edge"):])
            self.assertLess(
                abs(abs(direction(shape.Edges[index - 1]).dot(along)) - 1), TOL,
                "%s on the edge at %s moved silently to an edge across it, at %s" % (point.Name, at, now),
            )

        if fillet is None:
            return
        # The fillet rounds the same edge: the corner at the far end is cut away (a point 0.1 in
        # from both faces lies 1.27 from the round's axis, outside its radius 1), the one at x = 0
        # isn't. Under a Scale along X the round is a B-spline, so it is found by these points.
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        far = place(FILLET_EDGE)
        self.assertFalse(fillet.Shape.isInside(V(far.x - 0.1, far.y, 0.1), 0, True))
        self.assertTrue(fillet.Shape.isInside(V(0.1, far.y, 0.1), 0, True))


if __name__ == "__main__":
    unittest.main()
