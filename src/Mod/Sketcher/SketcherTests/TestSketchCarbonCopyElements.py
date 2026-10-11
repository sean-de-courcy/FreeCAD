# SPDX-License-Identifier: LGPL-2.1-or-later

"""Carbon copy remaps every element of a constraint, headless (ops#247, ops#267).

A Group holds any number of elements, and each can name internal geometry, an axis, the root
point, external geometry or nothing (GeoUndef). Designed geometry: a 10 x 10 square in the source,
one line apart from it in the destination, and edges of a box as external geometry; each copied
element must name a geometry equal to the source's, with its position unchanged."""

import math
import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD
import Part
import Sketcher

V = FreeCAD.Vector
TOL = 1e-9
GEO_UNDEF = -2000

SQUARE = [((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10)), ((0, 10), (0, 0))]


def elements(constraint):
    """Every element's GeoId and position, read from the constraint's saved form (Python sees
    only the first three)."""
    ids = re.search(r'ElementIds="([^"]*)"', constraint.Content).group(1).split()
    positions = re.search(r'ElementPositions="([^"]*)"', constraint.Content).group(1).split()
    return [int(n) for n in ids], [int(n) for n in positions]


class TestSketchCarbonCopyElements(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestSketchCarbonCopyElements")
        self.source = self.doc.addObject("Sketcher::SketchObject", "Source")
        for start, end in SQUARE:
            self.source.addGeometry(Part.LineSegment(V(*start, 0), V(*end, 0)), False)
        self.dest = self.doc.addObject("Sketcher::SketchObject", "Dest")
        self.dest.addGeometry(Part.LineSegment(V(20, 0, 0), V(30, 0, 0)), False)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def group(self, sketch):
        groups = [c for c in sketch.Constraints if c.Type == "Group"]
        self.assertEqual(len(groups), 1)
        return elements(groups[0])

    def assert_same_line(self, a, b):
        self.assertLess((a.StartPoint - b.StartPoint).Length, TOL)
        self.assertLess((a.EndPoint - b.EndPoint).Length, TOL)

    def test_every_kind_of_element(self):
        """PR 229 review L2: a Group of three lines, the H axis, the fourth line and nothing,
        with several positions, copied after Dest's line: the lines move up by one, the axis and
        GeoUndef stay, and every position is kept."""
        ids = [0, 1, 2, -1, 3, GEO_UNDEF]
        positions = [1, 2, 0, 1, 0, 0]
        content = [n for pair in zip(ids, positions) for n in pair]
        self.source.addConstraint(Sketcher.Constraint("Group", content))
        self.doc.recompute()
        self.assertEqual(self.group(self.source), (ids, positions))
        self.dest.carbonCopy(self.source.Name, False)
        self.doc.recompute()
        self.assertEqual(self.group(self.dest), ([1, 2, 3, -1, 4, GEO_UNDEF], positions))
        for geo_id in range(4):
            self.assert_same_line(self.dest.Geometry[geo_id + 1], self.source.Geometry[geo_id])

    def test_external_elements_after_the_destinations_externals(self):
        """External elements name the copies of the source's external geometry, which come after
        Dest's own: Dest links one edge of a box, Source two others, and Source's Group names
        both, a line and the V axis."""
        box = self.doc.addObject("Part::Box", "Box")
        box.Placement = FreeCAD.Placement(V(50, 50, 0), FreeCAD.Rotation())
        self.doc.recompute()
        # three edges of the box's bottom face, each a line in the plane z = 0
        bottom = [
            "Edge%d" % (i + 1)
            for i, e in enumerate(box.Shape.Edges)
            if all(abs(v.Point.z) < TOL for v in e.Vertexes)
        ]
        self.assertEqual(len(bottom), 4)
        self.dest.addExternal(box.Name, bottom[0])
        self.source.addExternal(box.Name, bottom[1])
        self.source.addExternal(box.Name, bottom[2])
        self.doc.recompute()
        self.assertEqual(len(self.dest.ExternalGeo), 3)
        self.assertEqual(len(self.source.ExternalGeo), 4)
        self.source.addConstraint(Sketcher.Constraint("Group", [-4, 1, -3, 2, 0, 0, -2, 0]))
        self.doc.recompute()
        self.dest.carbonCopy(self.source.Name, False)
        self.doc.recompute()
        ids, positions = self.group(self.dest)
        self.assertEqual(positions, [1, 2, 0, 0])
        self.assertEqual(ids[2:], [1, -2])
        # each external element names the copy of the source's geometry it named
        for dest_id, source_id in zip(ids[:2], (-4, -3)):
            self.assertLessEqual(dest_id, -4)
            self.assert_same_line(
                self.dest.ExternalGeo[-dest_id - 1], self.source.ExternalGeo[-source_id - 1]
            )


class TestCarbonCopySelfReference(unittest.TestCase):
    """PR 250 review L1: a source external whose ref names the destination's own geometry isn't
    copied, and a constraint on it goes to that geometry. Such a ref has no live link (one would
    make the copy a cycle, which carbonCopy refuses): the tests write the external geometry with
    its ref, as a link removed from the file leaves it. Dest: Edge1 (0, 0)-(10, 0) and Edge2
    (10, 0)-(10, 10); a sketch numbers each geometry's ends, so its Vertex4 is Edge2's end.
    Source: one line."""

    def setUp(self):
        self.doc = FreeCAD.newDocument("TestCarbonCopySelfReference")
        self.dest = self.doc.addObject("Sketcher::SketchObject", "Dest")
        self.dest.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)), False)
        self.dest.addGeometry(Part.LineSegment(V(10, 0, 0), V(10, 10, 0)), False)
        self.source = self.doc.addObject("Sketcher::SketchObject", "Source")
        self.source.addGeometry(Part.LineSegment(V(20, 20, 0), V(30, 20, 0)), False)
        self.doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        for folder in getattr(self, "folders", []):
            shutil.rmtree(folder, ignore_errors=True)

    def test_vertex_reference_names_that_point(self):
        """A point external at Dest.Vertex4, the source line's start on it: the copy's start is
        on Edge2's end, not on its start (the position the point's own constraint names). A
        Part.Point loses its ref in Python, so the ref is written into the saved file."""
        self.source.ExternalGeo = list(self.source.ExternalGeo) + [Part.Point(V(10, 10, 0))]
        self.source.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
        folder = tempfile.mkdtemp()
        self.folders = [folder]
        path = os.path.join(folder, "SelfReference.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        with zipfile.ZipFile(path) as archive:
            entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for info, data in entries:
                if info.filename == "Document.xml":
                    # Source's object data, its only point, that point's empty ref
                    source = data.rindex(b'<Object name="Source"')
                    point = data.index(b'<Geometry type="Part::GeomPoint"', source)
                    ref = data.index(b'Ref=""', point)
                    data = data[:ref] + b'Ref="Dest.Vertex4"' + data[ref + len(b'Ref=""') :]
                archive.writestr(info, data)
        self.doc = FreeCAD.openDocument(path)
        dest = self.doc.getObject("Dest")
        dest.carbonCopy("Source", False)
        self.assertEqual(len(dest.ExternalGeo), 2)  # the point isn't copied
        (c,) = dest.Constraints
        # the copied line (2) by its start, Edge2 (1) by its end
        self.assertEqual(
            (c.Type, c.First, c.FirstPos, c.Second, c.SecondPos), ("Coincident", 2, 1, 1, 2)
        )
        dest.solve()
        self.assertLess((dest.Geometry[2].StartPoint - dest.Geometry[1].EndPoint).Length, 1e-6)

    def turn_source_over(self):
        """Source turned over, 180 degrees about X: it sees Dest's geometry with y the other
        way round."""
        self.source.Placement = FreeCAD.Placement(V(), FreeCAD.Rotation(V(1, 0, 0), 180))

    def add_self_reference(self, geometry, ref):
        """`geometry` as an external of Source whose ref names Dest's `ref`: -3, the first."""
        facade = Sketcher.ExternalGeometryFacade(geometry)
        facade.Ref = ref
        self.source.ExternalGeo = list(self.source.ExternalGeo) + [facade.Geometry]

    def add_dest_arc(self):
        """Dest's Edge3: a quarter of the circle of radius 10 about the origin, from (10, 0) to
        (0, 10). Seen from the turned-over Source it runs from (0, -10) to (10, 0): a sketch's
        arcs run counterclockwise, so its start is the image of Dest's end. Returns that arc."""
        circle = Part.Circle(V(0, 0, 0), V(0, 0, 1), 10)
        self.dest.addGeometry(Part.ArcOfCircle(circle, 0, math.pi / 2), False)
        seen = Part.ArcOfCircle(circle, -math.pi / 2, 0)
        end = self.dest.Geometry[2].EndPoint
        self.assertLess((seen.StartPoint - V(end.x, -end.y, 0)).Length, TOL)
        return seen

    def add_width(self):
        """A length named width on Source's line, after the constraints on the external, with
        an expression."""
        width = self.source.addConstraint(Sketcher.Constraint("Distance", 0, 10))
        self.source.renameConstraint(width, "width")
        self.source.setExpression(".Constraints.width", "4 mm + 6 mm")

    def assert_width_copied_last(self):
        """The width is the last constraint copied, and its expression lands on it, not one
        constraint further on."""
        last = len(self.dest.Constraints) - 1
        self.assertEqual(self.dest.Constraints[last].Name, "width")
        paths = [path for path, _ in self.dest.ExpressionEngine]
        self.assertEqual(len(paths), 1)
        self.assertIn(
            paths[0], ("Constraints[%d]" % last, ".Constraints[%d]" % last, ".Constraints.width")
        )

    def test_mirrored_copy_keeps_a_constraint_on_a_self_referenced_line_end(self):
        """ops#280 (the PR 250 verification's nit): Source turned over and copied aligned, so
        the copy is mirrored back. A line keeps its start then (projected or mirrored, a line
        runs the same way): the source line's start on the start of a line external at
        Dest.Edge2 is copied, and the copy's start is on Edge2's start, (10, 0). Before, every
        constraint on a self-reference was refused in a mirrored copy."""
        self.turn_source_over()
        self.dest.setAllowUnaligned(False)  # True (the default) copies without flipping
        # Edge2 seen from the turned-over Source: y runs the other way
        self.add_self_reference(Part.LineSegment(V(10, 0, 0), V(10, -10, 0)), "Dest.Edge2")
        self.source.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
        self.add_width()
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        coincident = self.dest.Constraints[0]
        self.assertEqual(
            (coincident.Type, coincident.First, coincident.FirstPos),
            ("Coincident", 2, 1),
        )
        self.assertEqual((coincident.Second, coincident.SecondPos), (1, 1))
        self.assert_width_copied_last()
        self.dest.solve()
        self.assertLess((self.dest.Geometry[2].StartPoint - V(10, 0, 0)).Length, 1e-6)

    def test_mirrored_copy_refuses_every_constraint_on_a_self_referenced_arc(self):
        """Mirrored back, an arc runs the other way: its ends swap, and an angle at it changes
        in a way the value corrections don't know. So no constraint on an arc external at
        Dest.Edge3 is copied (each with a warning): the line's start on its start, the line's
        end on it, a tangency of the line's end with it (locked when added), its sweep (an Angle
        on it alone). The width after them is copied with its expression. Before (PR 253 review
        M1), all but the first were copied: the sweep "corrected" to minus itself drove Dest's
        arc to another sweep, and the tangency turned the copied line round."""
        self.turn_source_over()
        self.dest.setAllowUnaligned(False)
        self.add_self_reference(self.add_dest_arc(), "Dest.Edge3")
        self.source.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
        self.source.addConstraint(Sketcher.Constraint("PointOnObject", 0, 2, -3))
        self.source.addConstraint(Sketcher.Constraint("Tangent", 0, 2, -3))
        self.source.addConstraint(Sketcher.Constraint("Angle", -3, math.pi / 2))
        self.add_width()
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        self.assert_width_copied_last()

    def test_mirrored_copy_refuses_a_locked_perpendicular_at_a_self_referenced_line(self):
        """A line keeps its start when mirrored back, but a perpendicularity of the source
        line's end with a line external at Dest.Edge2, locked when added (+-90 degrees), says
        which side the line turns to, and the mirror turns it to the other: it isn't copied,
        with a warning. A perpendicularity of the two edges (no point, no locked value) is, on
        Edge2, and so is the width. Before (PR 253 review M1), the locked one was copied as it
        was."""
        self.turn_source_over()
        self.dest.setAllowUnaligned(False)
        self.add_self_reference(Part.LineSegment(V(10, 0, 0), V(10, -10, 0)), "Dest.Edge2")
        self.source.addConstraint(Sketcher.Constraint("Perpendicular", 0, -3))
        locked = self.source.addConstraint(Sketcher.Constraint("Perpendicular", 0, 2, -3))
        self.assertNotEqual(self.source.Constraints[locked].Value, 0)
        self.add_width()
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Perpendicular", "Distance"])
        perpendicular = self.dest.Constraints[0]
        self.assertEqual((perpendicular.First, perpendicular.Second), (2, 1))
        self.assert_width_copied_last()

    def add_orphaned_self_reference(self):
        """A line external of Source whose ref names Dest.Edge9, which Dest (two edges) doesn't
        have, the source line's start on its start."""
        self.add_self_reference(Part.LineSegment(V(40, 0, 0), V(50, 0, 0)), "Dest.Edge9")
        self.source.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
        self.add_width()

    def test_copy_refuses_a_constraint_on_an_orphaned_self_reference(self):
        """PR 253 review M2: the constraint on the external at Dest.Edge9 has nothing to go to
        here: it isn't copied (with a warning), and Dest's list stays valid. Before, it was
        copied onto GeoId 8, which Dest doesn't have: the list was flagged invalid."""
        self.add_orphaned_self_reference()
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        self.assert_width_copied_last()
        self.assertEqual(self.dest.solve(), 0)

    def test_mirrored_copy_refuses_a_constraint_on_an_orphaned_self_reference(self):
        """As above, mirrored back: before, the copy read Dest's geometry past its end (a
        crash, or a wrong refusal)."""
        self.turn_source_over()
        self.dest.setAllowUnaligned(False)
        self.add_orphaned_self_reference()
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        self.assert_width_copied_last()

    def test_reversed_unaligned_copy_refuses_a_constraint_on_a_self_reference(self):
        """ops#280 (PR 250 verification 1): Source turned over and copied unaligned (the
        default), so the copy isn't flipped back, and Source still sees Dest's geometry mirrored:
        a constraint on the start of an arc external at Dest.Edge3 named Dest's arc's end, and
        copied as it was it named its start. No constraint on the self-reference is copied then,
        with or without a position; the width is, with its expression. Before, both were copied
        (with only the warning that they are on the edge itself)."""
        self.turn_source_over()
        # Dest allows unaligned copies by default
        self.add_self_reference(self.add_dest_arc(), "Dest.Edge3")
        self.source.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
        self.source.addConstraint(Sketcher.Constraint("PointOnObject", 0, 2, -3))
        self.add_width()
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        self.assert_width_copied_last()


if __name__ == "__main__":
    unittest.main()
