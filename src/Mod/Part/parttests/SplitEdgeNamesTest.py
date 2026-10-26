# SPDX-License-Identifier: LGPL-2.1-or-later

"""A split edge's pieces keep their names when a MultiFuse's inputs are reordered (FreeCAD-CH
ops#431, `notes\\ops431-connected-name.md` design A).

Designed model: box A, 10 mm at the origin; boxes B and C, 2 x 6 x 2 at (3, -3, -1), turned +30 and
-30 degrees about the vertical axis through V = (5, 0, 0); a Part::MultiFuse of A, B and C. A's
edge y = 0, z = 0 is cut by B and C's union into two pieces, [0, 2.69] and [5, 10]. Where the edge
leaves the union, at V, two faces of other inputs meet it: B's and C's turned x = 5 faces. A piece
is told apart by the names at its ends, one face of another input per end: the face the result
listed first, before ops#431, so reordering the MultiFuse's inputs (which reorders the result's
faces) renamed the piece. It takes the smallest of the faces by name, which no order changes.

A Part::DatumPoint sits at the piece [5, 10]'s centre and a Part::Fillet rounds the piece; the
reorder must leave both on it, exactly (no guess, no warning)."""

import unittest

import FreeCAD as App
import Part

V = App.Vector
TOL = 1e-6

# The piece [5, 10] of A's edge y = 0, z = 0, by its centre
PIECE = V(7.5, 0, 0)


def edgeAt(shape, point):
    """The index name of the edge of `shape` whose centre of mass is `point`, or None."""
    for i, edge in enumerate(shape.Edges, 1):
        if (edge.CenterOfMass - point).Length < TOL:
            return "Edge%d" % i
    return None


def pieceNames(shape):
    """{x of the centre: mapped name} of the pieces of A's edge y = 0, z = 0."""
    names = {}
    for i, edge in enumerate(shape.Edges, 1):
        center = edge.CenterOfMass
        if abs(center.y) < TOL and abs(center.z) < TOL:
            names[round(center.x, 6)] = shape.ElementReverseMap.get("Edge%d" % i)
    return names


class SplitEdgeNamesTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SplitEdgeNamesTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def turnedBox(self, name, degrees):
        box = self.doc.addObject("Part::Box", name)
        box.Length, box.Width, box.Height = 2, 6, 2
        turn = App.Rotation(V(0, 0, 1), degrees)
        axis = V(5, 0, 0)
        box.Placement = App.Placement(axis + turn.multVec(V(3, -3, -1) - axis), turn)
        return box

    def warned(self, obj):
        return any(
            entry.get("warning_level") not in (None, "", "none")
            or entry.get("status") == "guessed"
            for entry in App.getReferenceReport(obj)
        )

    def testSplitEdgeNamesIgnoreInputOrder(self):
        doc = self.doc
        a = doc.addObject("Part::Box", "A")
        b = self.turnedBox("B", 30)
        c = self.turnedBox("C", -30)
        fuse = doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [a, b, c]
        doc.recompute()
        # The model: one valid solid (B and C overlap), A's edge in two pieces
        self.assertTrue(fuse.isValid(), fuse.getStatusString())
        self.assertTrue(fuse.Shape.isValid())
        self.assertEqual(len(fuse.Shape.Solids), 1)
        before = pieceNames(fuse.Shape)
        self.assertEqual(len(before), 2, before)
        self.assertIn(7.5, before)
        self.assertTrue(all(before.values()), before)

        point = doc.addObject("Part::DatumPoint", "Point")
        point.AttachmentSupport = [(fuse, edgeAt(fuse.Shape, PIECE))]
        point.MapMode = "CenterOfMass"
        fillet = doc.addObject("Part::Fillet", "Fillet")
        fillet.Base = fuse
        fillet.Edges = [(int(edgeAt(fuse.Shape, PIECE)[len("Edge"):]), 0.3, 0.3)]
        doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        rounded = fillet.Shape.Volume

        fuse.Shapes = [a, c, b]
        doc.recompute()

        # The pieces keep their names at their places
        self.assertEqual(pieceNames(fuse.Shape), before)
        # The point and the fillet stay on the piece, exactly
        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertFalse(self.warned(point))
        self.assertLess((point.Placement.Base - PIECE).Length, TOL)
        self.assertEqual(point.AttachmentSupport[0][1][0], edgeAt(fuse.Shape, PIECE))
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertFalse(self.warned(fillet))
        self.assertAlmostEqual(fillet.Shape.Volume, rounded, places=6)
