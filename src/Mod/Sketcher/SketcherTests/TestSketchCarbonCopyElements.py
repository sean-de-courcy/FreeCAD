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

    def flag(self, sketch):
        """Flags `sketch`'s constraint list invalid: a constraint on Edge100, which it doesn't
        have, written straight into the property: the sketch reports "invalid constraint
        indices", and in C++ the list reads as empty until it is repaired (Python reads the
        list as it is)."""
        sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sketch.Constraints = list(sketch.Constraints) + [
            Sketcher.Constraint("Coincident", 0, 1, 99, 1)
        ]

    def state(self, sketch):
        """What a refused copy mustn't change: the constraints, the links and the geometry."""
        return (
            [c.Content for c in sketch.Constraints],
            sketch.ExternalGeometry,
            [(g.StartPoint, g.EndPoint) for g in sketch.Geometry],
        )

    def assert_copy_refused(self, constraints):
        """The copy raises, and changes neither sketch: Dest keeps its one line and its
        `constraints`, a Horizontal first."""
        dest, source = self.state(self.dest), self.state(self.source)
        self.assertEqual(len(dest[2]), 1)
        self.assertEqual(len(dest[0]), constraints)
        self.assertEqual(self.dest.Constraints[0].Type, "Horizontal")
        with self.assertRaises(ValueError):
            self.dest.carbonCopy(self.source.Name, False)
        self.assertEqual(self.state(self.dest), dest)
        self.assertEqual(self.state(self.source), source)

    def test_copy_from_a_sketch_with_flagged_constraints_is_refused(self):
        """ops#237 (PR 218 review): before, the copy read the source's flagged list as empty and
        copied its geometry without a single constraint, silently."""
        self.flag(self.source)
        self.dest.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.assert_copy_refused(1)

    def test_copy_into_a_sketch_with_flagged_constraints_is_refused(self):
        """ops#237 (PR 218 review): before, the copy read Dest's flagged list as empty and wrote
        back the source's constraints alone: Dest's own were gone, silently."""
        self.flag(self.dest)
        self.assert_copy_refused(2)

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


    def test_copy_of_a_link_the_destination_has_is_refused_before_any_change(self):
        """ops#252: Dest links an edge of a box, and Source links another and that one. The copy
        is refused, and Dest's external geometry is as it was: the source's two geometries were
        written to it before the duplicate link was found, and stayed there without links."""
        box = self.doc.addObject("Part::Box", "Box")
        box.Placement = FreeCAD.Placement(V(50, 50, 0), FreeCAD.Rotation())
        self.doc.recompute()
        bottom = [
            "Edge%d" % (i + 1)
            for i, e in enumerate(box.Shape.Edges)
            if all(abs(v.Point.z) < TOL for v in e.Vertexes)
        ]
        self.dest.addExternal(box.Name, bottom[0])
        self.source.addExternal(box.Name, bottom[1])
        self.source.addExternal(box.Name, bottom[0])
        self.doc.recompute()
        links = self.dest.ExternalGeometry
        geometries = [(g.StartPoint, g.EndPoint) for g in self.dest.ExternalGeo[2:]]
        self.assertEqual(len(geometries), 1)
        with self.assertRaises(ValueError):
            self.dest.carbonCopy(self.source.Name, False)
        self.assertEqual(self.dest.ExternalGeometry, links)
        self.assertEqual([(g.StartPoint, g.EndPoint) for g in self.dest.ExternalGeo[2:]], geometries)
        self.assertEqual(len(self.dest.Geometry), 1)
        self.doc.recompute()
        self.assertEqual(len(self.dest.ExternalGeo), 3)


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

    def copy_onto_self_referenced_arc(self, seen, start, end, image):
        """Dest's arc as Source sees it (`seen`) as an external of Source at Dest.Edge3, and
        Source's line from `start` to `end`, from the arc's start and tangent to it there: the
        tangency end to end (locked when added: the line's start on the arc's start, going on
        along it), the arc's sweep (an Angle on it alone, 90 degrees) and the width. Copied
        aligned (flipped back): every constraint is copied, and the solve moves nothing, the
        copied line staying at the image of Source's. Returns the copied tangency."""
        self.dest.setAllowUnaligned(False)
        self.add_self_reference(seen, "Dest.Edge3")
        self.source.delGeometry(0)
        self.source.addGeometry(Part.LineSegment(V(*start, 0), V(*end, 0)), False)
        tangent = self.source.addConstraint(Sketcher.Constraint("Tangent", 0, 1, -3, 1))
        self.assertNotEqual(self.source.Constraints[tangent].Value, 0)
        self.source.addConstraint(Sketcher.Constraint("Angle", -3, math.pi / 2))
        self.add_width()
        # not solved: the sweep, on a fixed external alone, is redundant in Source
        line = self.source.Geometry[0]
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual(
            [c.Type for c in self.dest.Constraints], ["Tangent", "Angle", "Distance"]
        )
        self.assertEqual(self.dest.Constraints[2].Name, "width")
        # each copied dimension is bound to the source's, the sweep's at its own index
        self.assertEqual(
            sorted(self.dest.ExpressionEngine),
            [
                (".Constraints.width", "Source.Constraints.width"),
                ("Constraints[1]", "Source.Constraints[1]"),
            ],
        )
        self.assertAlmostEqual(self.dest.Constraints[1].Value, math.pi / 2, delta=1e-9)
        self.assertEqual(self.dest.solve(), 0)
        copied = self.dest.Geometry[3]
        self.assertLess((copied.StartPoint - image(line.StartPoint)).Length, 1e-6)
        self.assertLess((copied.EndPoint - image(line.EndPoint)).Length, 1e-6)
        arc = self.dest.Geometry[2]
        self.assertLess((arc.StartPoint - V(10, 0, 0)).Length, 1e-6)
        self.assertLess((arc.EndPoint - V(0, 10, 0)).Length, 1e-6)
        return self.dest.Constraints[0]

    def test_mirrored_copy_keeps_the_constraints_on_a_self_referenced_arc(self):
        """Mirrored back, an arc runs the other way: the source's external of Dest's arc starts
        at the image of the arc's end, so the tangency at its start goes to Dest's arc's end,
        and its locked value turns half a turn, as for a copied external (PR 253
        verification finding 4). Before, every constraint on the arc was refused (PR 253 review
        M1, which refused them rather than copy them wrong)."""
        self.turn_source_over()
        tangent = self.copy_onto_self_referenced_arc(
            self.add_dest_arc(), (0, -10), (-10, -10), lambda p: V(p.x, -p.y, 0)
        )
        self.assertEqual(
            (tangent.First, tangent.FirstPos, tangent.Second, tangent.SecondPos),
            (3, 1, 2, 2),
        )

    def test_turned_copy_keeps_the_constraints_on_a_self_referenced_arc(self):
        """PR 253 verification finding 4: Source turned round (180 degrees about Z), so the copy
        turns half a turn back, which keeps an arc's ends and the way it runs. The external of
        Dest's arc runs from (-10, 0) to (0, -10); the tangency at its start goes to Dest's
        arc's start. Before, every constraint on it was refused, as on any self-referenced edge
        that isn't a line."""
        self.source.Placement = FreeCAD.Placement(V(), FreeCAD.Rotation(V(0, 0, 1), 180))
        self.add_dest_arc()
        circle = Part.Circle(V(0, 0, 0), V(0, 0, 1), 10)
        tangent = self.copy_onto_self_referenced_arc(
            Part.ArcOfCircle(circle, math.pi, 1.5 * math.pi),
            (-10, 0),
            (-10, 10),
            lambda p: V(-p.x, -p.y, 0),
        )
        self.assertEqual(
            (tangent.First, tangent.FirstPos, tangent.Second, tangent.SecondPos),
            (3, 1, 2, 1),
        )

    def test_mirrored_copy_refuses_a_constraint_on_a_stale_self_referenced_arc(self):
        """PR 260 review L2: Source's external of Dest.Edge3 is stale: the rest of the circle,
        drawn from Dest's end round to its start, which Source sees from (10, 0) to (0, -10).
        Its ends are where those of Dest's arc are, taken the other way, so they compare as
        kept; its middle, which Dest sees at (-7.1, -7.1), isn't Dest's arc's. The source line's start
        on it isn't copied (with a warning); the width is. Before, the ends decided alone: the
        constraint was copied onto the wrong end, and an angle at it would be turned the wrong
        way."""
        self.turn_source_over()
        self.dest.setAllowUnaligned(False)
        self.add_dest_arc()
        circle = Part.Circle(V(0, 0, 0), V(0, 0, 1), 10)
        self.add_self_reference(Part.ArcOfCircle(circle, 0, 1.5 * math.pi), "Dest.Edge3")
        self.source.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
        self.add_width()
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        self.assert_width_copied_last()

    def add_dest_circle_seen(self, radius):
        """Dest's Edge3, the circle of radius 4 about (20, 5), and Source's external of it as a
        circle of `radius` about (20, -5), Source turned over; Source's line from (20, -19) to
        (20, -9) (the width's length), its end on that external. Copied aligned (flipped back)."""
        self.add_dest_conic_seen(
            Part.Circle(V(20, 5, 0), V(0, 0, 1), 4),
            Part.Circle(V(20, -5, 0), V(0, 0, 1), radius),
            (20, -19),
            (20, -9),
        )

    def add_dest_conic_seen(self, conic, seen, start, end):
        """Dest's Edge3 `conic`, and Source's external of it `seen`, Source turned over;
        Source's line from `start` to `end`, its end on that external, and the width. Copied
        aligned (flipped back)."""
        self.turn_source_over()
        self.dest.setAllowUnaligned(False)
        self.dest.addGeometry(conic, False)
        self.add_self_reference(seen, "Dest.Edge3")
        self.source.delGeometry(0)
        self.source.addGeometry(Part.LineSegment(V(*start, 0), V(*end, 0)), False)
        self.source.addConstraint(Sketcher.Constraint("PointOnObject", 0, 2, -3))
        self.add_width()
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)

    def test_mirrored_copy_keeps_a_point_on_a_self_referenced_circle(self):
        """PR 260 review L1: the external is the image of Dest's circle (centre and radius), so
        the line's end on it goes onto Dest's own circle, and the solve leaves the copied line at
        the image of Source's, from (20, 19) to (20, 9). (On integration before fork PR 260,
        every constraint on a self-referenced edge other than a line was refused.)"""
        self.add_dest_circle_seen(4)
        self.assertEqual(
            [(c.Type, c.First, c.FirstPos, c.Second) for c in self.dest.Constraints],
            [("PointOnObject", 3, 2, 2), ("Distance", 3, 0, GEO_UNDEF)],
        )
        self.assert_width_copied_last()
        self.assertEqual(self.dest.solve(), 0)
        copied = self.dest.Geometry[3]
        self.assertLess((copied.StartPoint - V(20, 19, 0)).Length, 1e-6)
        self.assertLess((copied.EndPoint - V(20, 9, 0)).Length, 1e-6)

    def test_mirrored_copy_refuses_a_point_on_a_stale_self_referenced_circle(self):
        """PR 260 review L1: Source last saw Dest's circle with radius 5: stale, so the line's
        end on it isn't copied (with a warning); the width is. Before (fork PR 260's first
        round), a whole circle was taken unchecked, and the solve pulled the line's end onto a
        circle it was never on."""
        self.add_dest_circle_seen(5)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        self.assert_width_copied_last()

    def add_dest_ellipse_seen(self, turned):
        """Dest's Edge3, the ellipse about (20, 5) with radii 6 (along x) and 3, and Source's
        external of it about (20, -5) with the same radii, its major axis along x, or along y
        if `turned`; Source's line from (26, -15) to (26, -5), its end on the external's
        major vertex as Source saw it."""
        major = V(26, -5, 0) if not turned else V(20, 1, 0)
        minor = V(20, -2, 0) if not turned else V(23, -5, 0)
        self.add_dest_conic_seen(
            Part.Ellipse(V(26, 5, 0), V(20, 8, 0), V(20, 5, 0)),
            Part.Ellipse(major, minor, V(20, -5, 0)),
            (26, -15),
            (26, -5),
        )

    def test_mirrored_copy_keeps_a_point_on_a_self_referenced_ellipse(self):
        """PR 260 verification L1: the external is the image of Dest's ellipse (centre, radii,
        axis): the line's end on it goes onto Dest's own ellipse, and the solve leaves the copied
        line at the image of Source's, from (26, 15) to (26, 5)."""
        self.add_dest_ellipse_seen(turned=False)
        self.assertEqual(
            [(c.Type, c.First, c.FirstPos, c.Second) for c in self.dest.Constraints],
            [("PointOnObject", 3, 2, 2), ("Distance", 3, 0, GEO_UNDEF)],
        )
        self.assert_width_copied_last()
        self.assertEqual(self.dest.solve(), 0)
        copied = self.dest.Geometry[3]
        self.assertLess((copied.StartPoint - V(26, 15, 0)).Length, 1e-6)
        self.assertLess((copied.EndPoint - V(26, 5, 0)).Length, 1e-6)

    def test_mirrored_copy_refuses_a_point_on_a_stale_self_referenced_ellipse(self):
        """PR 260 verification L1: Source last saw Dest's ellipse turned a quarter turn (same
        centre and radii): stale, so the line's end on it isn't copied (with a warning); the
        width is. Before, centre and radii matched, and the constraint was copied onto an
        ellipse the end was never on."""
        self.add_dest_ellipse_seen(turned=True)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        self.assert_width_copied_last()

    def test_mirrored_copy_refuses_a_constraint_on_a_stale_self_referenced_line(self):
        """Source's external of Dest.Edge2 is stale: Source last saw it from (10, 0) to
        (10, -12), and Dest's Edge2 is 10 long now. Its ends match neither way, so the source
        line's start on its start isn't copied (with a warning); the width is. Before, a line
        was copied whatever its ends (only a line: other edges were all refused)."""
        self.turn_source_over()
        self.dest.setAllowUnaligned(False)
        self.add_self_reference(Part.LineSegment(V(10, 0, 0), V(10, -12, 0)), "Dest.Edge2")
        self.source.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
        self.add_width()
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        self.assert_width_copied_last()

    def test_mirrored_copy_corrects_a_locked_perpendicular_at_a_self_referenced_line(self):
        """A line keeps its start when mirrored back, and a perpendicularity of the source
        line's end with a line external at Dest.Edge2, locked when added (+-90 degrees, which
        side the line turns to), is corrected like one between two of the source's own lines
        (ops#281): it is copied onto Edge2, and the solve leaves the copied line where Dest sees
        the source's, the image of it with y the other way. So is the width. Before, it was
        copied as it was (PR 253 review M1), and the solve turned the copied line."""
        self.turn_source_over()
        self.dest.setAllowUnaligned(False)
        self.add_self_reference(Part.LineSegment(V(10, 0, 0), V(10, -10, 0)), "Dest.Edge2")
        locked = self.source.addConstraint(Sketcher.Constraint("Perpendicular", 0, 2, -3))
        self.assertNotEqual(self.source.Constraints[locked].Value, 0)
        self.add_width()
        self.assertEqual(self.source.solve(), 0)
        seen = self.source.Geometry[0]
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual(
            [(c.Type, c.First, c.Second) for c in self.dest.Constraints],
            [("Perpendicular", 2, 1), ("Distance", 2, GEO_UNDEF)],
        )
        self.assert_width_copied_last()
        self.assertEqual(self.dest.solve(), 0)
        copied = self.dest.Geometry[2]
        image = lambda p: V(p.x, -p.y, 0)
        self.assertLess((copied.StartPoint - image(seen.StartPoint)).Length, 1e-6)
        self.assertLess((copied.EndPoint - image(seen.EndPoint)).Length, 1e-6)

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


class TestCarbonCopyFlipped(unittest.TestCase):
    """ops#281: a carbon copy from a source turned over (or round) and copied aligned is flipped
    back here: each copied geometry is the source's as Dest sees it, and each copied constraint
    must hold there as it held in the source, so the solve after the copy moves nothing.
    Designed geometry: Source's Edge1 is a quarter of the circle of radius 10 about the origin,
    from (10, 0) to (0, 10); each test adds lines and constraints."""

    def setUp(self):
        self.doc = FreeCAD.newDocument("TestCarbonCopyFlipped")
        self.dest = self.doc.addObject("Sketcher::SketchObject", "Dest")
        self.source = self.doc.addObject("Sketcher::SketchObject", "Source")
        circle = Part.Circle(V(0, 0, 0), V(0, 0, 1), 10)
        self.source.addGeometry(Part.ArcOfCircle(circle, 0, math.pi / 2), False)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def place(self, turn, image):
        """Source 10 above Dest along Dest's normal, turned by `turn` in Dest's frame; `image`
        maps a point of Source's to where Dest sees it."""
        where = self.dest.Placement
        self.source.Placement = FreeCAD.Placement(
            where.Base + where.Rotation.multVec(V(0, 0, 10)), where.Rotation.multiply(turn)
        )
        self.image = image

    def turn_over(self, tilt=0, spin=0):
        """Source turned over, 180 degrees about X: Dest sees it with y the other way. Then
        tilted by `tilt` degrees about its own Y, and turned by `spin` about its normal."""
        turn = FreeCAD.Rotation(V(1, 0, 0), 180).multiply(FreeCAD.Rotation(V(0, 1, 0), tilt))
        turn = turn.multiply(FreeCAD.Rotation(V(0, 0, 1), spin))
        self.place(turn, lambda p: V(p.x, -p.y, 0))

    def turn_round(self):
        """Source turned round, 180 degrees about Z: Dest sees it turned half a turn."""
        self.place(FreeCAD.Rotation(V(0, 0, 1), 180), lambda p: V(-p.x, -p.y, 0))

    def add_line(self, start, end):
        return self.source.addGeometry(Part.LineSegment(V(*start, 0), V(*end, 0)), False)

    def copy(self):
        """Source solved, then copied aligned (flipped back), the document recomputed and Dest
        solved again: every constraint is copied, and Dest's geometry is Source's as Dest sees
        it. An arc is checked by its
        centre, radii, ends (which swap in a mirror) and midpoint."""
        self.assertEqual(self.source.solve(), 0)
        self.dest.setAllowUnaligned(False)  # True (the default) copies without flipping
        self.dest.carbonCopy("Source", False)
        self.doc.recompute()
        self.assertEqual(self.dest.solve(), 0)
        self.assertEqual(len(self.dest.Geometry), len(self.source.Geometry))
        # every constraint copied: none refused (PR 254 review F1)
        self.assertEqual(len(self.dest.Constraints), len(self.source.Constraints))
        for seen, copied in zip(self.source.Geometry, self.dest.Geometry):
            if isinstance(seen, Part.LineSegment):
                # a line keeps its start
                self.assertLess((copied.StartPoint - self.image(seen.StartPoint)).Length, 1e-6)
                self.assertLess((copied.EndPoint - self.image(seen.EndPoint)).Length, 1e-6)
                continue
            self.assertLess((copied.Center - self.image(seen.Center)).Length, 1e-6)
            if isinstance(seen, Part.ArcOfCircle):
                self.assertAlmostEqual(copied.Radius, seen.Radius, delta=1e-6)
            else:
                self.assertAlmostEqual(copied.MajorRadius, seen.MajorRadius, delta=1e-6)
                self.assertAlmostEqual(copied.MinorRadius, seen.MinorRadius, delta=1e-6)
            ends = [self.image(seen.StartPoint), self.image(seen.EndPoint)]
            for point in (copied.StartPoint, copied.EndPoint):
                self.assertLess(min((point - end).Length for end in ends), 1e-6)

            def middle(arc):
                return arc.value((arc.FirstParameter + arc.LastParameter) / 2)

            self.assertLess((middle(copied) - self.image(middle(seen))).Length, 1e-6)

    def add_sweep(self):
        """The arc's sweep (an Angle on it alone), 90 degrees by an expression."""
        sweep = self.source.addConstraint(Sketcher.Constraint("Angle", 0, math.pi / 2))
        self.source.setExpression(".Constraints[%d]" % sweep, "45 deg + 45 deg")
        self.doc.recompute()

    def test_mirrored_copy_keeps_an_arcs_sweep(self):
        """The sweep isn't an angle to an axis: it stays 90 degrees. Before, it was "corrected"
        to -90 degrees (value and expression), and Dest's arc driven to another sweep."""
        self.turn_over()
        self.add_sweep()
        self.copy()
        (sweep,) = self.dest.Constraints
        self.assertAlmostEqual(sweep.Value, math.pi / 2, delta=1e-9)

    def test_turned_copy_keeps_an_arcs_sweep(self):
        """As above, Source turned round: before, the sweep became 270 degrees."""
        self.turn_round()
        self.add_sweep()
        self.copy()
        (sweep,) = self.dest.Constraints
        self.assertAlmostEqual(sweep.Value, math.pi / 2, delta=1e-9)

    def test_mirrored_copy_keeps_a_point_on_an_arcs_end(self):
        """A line from (10, 0) to (20, 0), its start on the arc's start. A mirrored arc runs the
        other way (a sketch's arcs run counterclockwise), so the copy's start is the image of
        the source's end: the copied constraint must name the copied arc's end. Before, it named
        its start, and the solve pulled the line onto the other end."""
        self.turn_over()
        line = self.add_line((10, 0), (20, 0))
        self.source.addConstraint(Sketcher.Constraint("Coincident", line, 1, 0, 1))
        self.copy()

    def test_mirrored_copy_keeps_a_locked_tangency_at_an_arcs_end(self):
        """A line from the arc's end (0, 10) to (-10, 10), tangent to the arc there (end to
        end, locked when added: the line goes on the way the arc goes). Mirrored, the arc runs
        the other way: the locked value must turn by 180 degrees. Before, it didn't (and named
        the arc's other end): the solve turned the line round."""
        self.turn_over()
        line = self.add_line((0, 10), (-10, 10))
        tangent = self.source.addConstraint(Sketcher.Constraint("Tangent", line, 1, 0, 2))
        self.assertNotEqual(self.source.Constraints[tangent].Value, 0)
        self.copy()

    def test_mirrored_copy_keeps_a_locked_perpendicularity_of_two_lines(self):
        """Two lines, (10, 0)-(20, 0) and (20, 0)-(20, 5), perpendicular end to end (locked:
        the second turns left). Mirrored, it turns right: the locked value must change sign.
        Before, it didn't: the solve turned the second line to the other side."""
        self.turn_over()
        first = self.add_line((10, 0), (20, 0))
        second = self.add_line((20, 0), (20, 5))
        perpendicular = self.source.addConstraint(
            Sketcher.Constraint("Perpendicular", second, 1, first, 2)
        )
        self.assertNotEqual(self.source.Constraints[perpendicular].Value, 0)
        self.copy()

    def test_mirrored_copy_keeps_an_angle_via_a_point_with_an_arc(self):
        """A line from (10, 0) at 30 degrees, at 60 degrees to the arc there (an angle via its
        start). Mirrored, the angle changes sign and, the arc running the other way, turns by
        180 degrees. Before, it only changed sign: the solve turned the line."""
        self.turn_over()
        end = V(10 + 10 * math.cos(math.pi / 6), 10 * math.sin(math.pi / 6), 0)
        line = self.add_line((10, 0), (end.x, end.y))
        self.source.addConstraint(
            Sketcher.Constraint("AngleViaPoint", 0, line, line, 1, math.pi / 3)
        )
        self.copy()

    def test_flipped_copy_keeps_a_lines_angle(self):
        """A line from (12, 0) to (20, 4), its direction locked by an Angle on it alone (to the
        horizontal axis): in a mirror the angle is negated, and turns half a turn when the
        horizontal axis runs the other way (x flipped)."""
        self.turn_over()
        line = self.add_line((12, 0), (20, 4))
        self.source.addConstraint(Sketcher.Constraint("Angle", line, math.atan2(4, 8)))
        self.copy()

    def test_flipped_copy_keeps_an_angle_to_the_vertical_axis(self):
        """The same line at an angle from the vertical axis (Angle of the two): it turns half a
        turn when the vertical axis runs the other way (y flipped)."""
        self.turn_over()
        line = self.add_line((12, 0), (20, 4))
        self.source.addConstraint(
            Sketcher.Constraint("Angle", -2, line, math.atan2(4, 8) - math.pi / 2)
        )
        self.copy()

    def test_flipped_copy_keeps_a_locked_tangency_with_the_horizontal_axis(self):
        """A second arc, of the circle of radius 10 about (0, 10), from (0, 0) to (10, 10),
        tangent to the horizontal axis at its start (end to edge, locked when added)."""
        self.turn_over()
        circle = Part.Circle(V(0, 10, 0), V(0, 0, 1), 10)
        arc = self.source.addGeometry(
            Part.ArcOfCircle(circle, 1.5 * math.pi, 2 * math.pi), False
        )
        tangent = self.source.addConstraint(Sketcher.Constraint("Tangent", arc, 1, -1))
        self.assertNotEqual(self.source.Constraints[tangent].Value, 0)
        self.copy()

    def test_flipped_copy_keeps_a_locked_tangency_at_an_arc_of_ellipses_end(self):
        """An arc of the ellipse about (0, -20) with radii 12 (along x) and 6, from (12, -20) to
        (0, -14), and a line from its end to (-10, -14), tangent there (end to end, locked). A
        mirrored arc of ellipse runs the other way as an arc of circle does."""
        self.turn_over()
        ellipse = Part.Ellipse(V(0, -20, 0), 12, 6)
        arc = self.source.addGeometry(Part.ArcOfEllipse(ellipse, 0, math.pi / 2), False)
        line = self.add_line((0, -14), (-10, -14))
        tangent = self.source.addConstraint(Sketcher.Constraint("Tangent", line, 1, arc, 2))
        self.assertNotEqual(self.source.Constraints[tangent].Value, 0)
        self.copy()

    def ring(self, *angles):
        """The circle of radius 5 about (0, 20, 5) whose axis is X, in Dest's frame (edge-on to
        both sketches), or the arc of it between `angles` (degrees)."""
        where = self.dest.Placement
        return Part.makeCircle(
            5, where.multVec(V(0, 20, 5)), where.Rotation.multVec(V(1, 0, 0)), *angles
        )

    def add_edge_on(self, edge):
        """`edge` (global) as Source's external -3, and a line whose start is on the
        external's start and which is at 60 degrees to it: both hold only if the copied
        external runs as the image of the source's."""
        ring = self.doc.addObject("Part::Feature", "Ring")
        ring.Shape = edge
        self.doc.recompute()
        self.source.addExternal(ring.Name, "Edge1")
        line = self.add_line((3, 3), (8, 6))
        self.source.addConstraint(Sketcher.Constraint("Coincident", line, 1, -3, 1))
        self.source.addConstraint(Sketcher.Constraint("Angle", -3, line, math.pi / 3))

    def assert_angle_kept(self):
        """The Angle (the last constraint) has the source's value."""
        self.assertAlmostEqual(
            self.dest.Constraints[-1].Value, self.source.Constraints[-1].Value, delta=1e-9
        )

    def test_flipped_copy_keeps_an_edge_on_circles_ends(self):
        """ops#283: a circle seen edge-on (`ring`): a sketch projects it as a line along its
        normal ^ the circle's axis, so in a mirrored copy the copied external runs the other way.
        Before, a constraint on its start landed on its end, and an angle with it was off by
        half a turn."""
        self.turn_over()
        self.add_edge_on(self.ring())
        self.copy()

    def test_flipped_copy_keeps_an_edge_on_arcs_ends(self):
        """As above, a quarter of that circle."""
        self.turn_over()
        self.add_edge_on(self.ring(0, 90))
        self.copy()

    def test_turned_copy_keeps_an_edge_on_circles_ends(self):
        """F4 (PR 254 review): as above, Source turned round, so the copy turns half a turn
        back (both flips): the copied external's ends are kept, and the angle with it keeps its
        value."""
        self.turn_round()
        self.add_edge_on(self.ring())
        self.copy()
        self.assert_angle_kept()

    def test_turned_copy_keeps_an_edge_on_arcs_ends(self):
        """As above, a quarter of that circle."""
        self.turn_round()
        self.add_edge_on(self.ring(0, 90))
        self.copy()
        self.assert_angle_kept()

    def test_slightly_tilted_copy_keeps_a_point_on_a_far_externals_end(self):
        """ops#283 F3: Source turned over and tilted by 3e-4 rad, which the alignment check
        allows (1 - cos is 4.5e-8). An external line in Dest's plane, at x = 100 from y = 0 to
        10, is then seen about 0.003 off where its image is. A source line's start on its start
        is copied, and the copied line's start ends up on the copied external's start, which is
        about where Dest sees the source's start (the other end is 10 away). Before, the ends
        compared to within 1e-6: neither pairing matched, and the constraint was refused."""
        self.turn_over(tilt=math.degrees(3e-4))
        self.check_far_external(0.01)

    def test_slightly_turned_copy_keeps_a_point_on_a_far_externals_end(self):
        """PR 260 review L4: as above, Source turned by 3e-4 rad about its normal instead (in
        the plane): the external's ends are seen about 0.03 off their images."""
        self.turn_over(spin=math.degrees(3e-4))
        self.check_far_external(0.05)

    def check_far_external(self, bound):
        """The external line at x = 100 and the source line's start on its start, copied: the
        constraint is copied, and the copied line's start is on the copied external's start,
        within `bound` of where Dest sees the source's."""
        where = self.dest.Placement
        rail = self.doc.addObject("Part::Feature", "Rail")
        rail.Shape = Part.makeLine(where.multVec(V(100, 0, 0)), where.multVec(V(100, 10, 0)))
        self.doc.recompute()
        self.source.addExternal(rail.Name, "Edge1")
        line = self.add_line((90, 3), (95, 8))
        self.source.addConstraint(Sketcher.Constraint("Coincident", line, 1, -3, 1))
        self.assertEqual(self.source.solve(), 0)
        seen = self.source.getPoint(-3, 1)
        self.dest.setAllowUnaligned(False)
        self.dest.carbonCopy("Source", False)
        self.doc.recompute()
        self.assertEqual(len(self.dest.Constraints), 1)
        self.assertEqual(self.dest.solve(), 0)
        start = self.dest.Geometry[line].StartPoint
        self.assertLess((start - self.dest.getPoint(-3, 1)).Length, 1e-6)
        self.assertLess((start - self.image(seen)).Length, bound)

    def test_flipped_copy_refuses_the_constraints_on_an_external_whose_ends_match_neither_way(self):
        """F4 (PR 254 review): an intersection-type external of a sloped face, which runs along
        y from x = 20 at z = -5 to x = 30 at z = 15 in Dest's frame. Dest (z = 0) cuts it at
        x = 22.5, Source (z = 10) at x = 27.5: the copied external's ends match the source's
        neither way, so the source line's start on it isn't copied (with a warning), while the
        line's length is."""
        self.turn_over()
        where = self.dest.Placement
        corners = [(20, -5, -5), (20, 5, -5), (30, 5, 15), (30, -5, 15), (20, -5, -5)]
        slope = self.doc.addObject("Part::Feature", "Slope")
        slope.Shape = Part.Face(Part.makePolygon([where.multVec(V(*c)) for c in corners]))
        self.doc.recompute()
        self.source.addExternal(slope.Name, "Face1", False, True)
        self.doc.recompute()
        self.assertAlmostEqual(abs(self.source.getPoint(-3, 1).x), 27.5, delta=1e-6)
        line = self.add_line((10, 3), (14, 6))
        self.source.addConstraint(Sketcher.Constraint("Coincident", line, 1, -3, 1))
        self.source.addConstraint(Sketcher.Constraint("Distance", line, 5))
        self.assertEqual(self.source.solve(), 0)
        self.dest.setAllowUnaligned(False)
        self.dest.carbonCopy("Source", False)
        self.doc.recompute()
        self.assertAlmostEqual(self.dest.getPoint(-3, 1).x, 22.5, delta=1e-6)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        self.assertEqual(self.dest.solve(), 0)
        seen = self.source.Geometry[line]
        copied = self.dest.Geometry[line]
        self.assertLess((copied.StartPoint - self.image(seen.StartPoint)).Length, 1e-6)
        self.assertLess((copied.EndPoint - self.image(seen.EndPoint)).Length, 1e-6)

    def freeze_and_copy(self, shape, element, line, pos):
        """`shape`'s `element` as Source's external -3, frozen, and the end `pos` of Source's
        `line` on its start; then copied (`copy`). Python can't set the Frozen flag on an
        external, so it is set in the saved file. Returns Source's view of the external's
        start."""
        post = self.doc.addObject("Part::Feature", "Post")
        post.Shape = shape
        self.doc.recompute()
        self.source.addExternal(post.Name, element)
        self.source.addConstraint(Sketcher.Constraint("Coincident", line, pos, -3, 1))
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "FrozenExternal.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        with zipfile.ZipFile(path) as archive:
            entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for info, data in entries:
                if info.filename == "Document.xml":
                    # the Frozen flag (2) of Source's external at Post
                    data, count = re.subn(
                        rb'(Ref="Post\.[^"]*" Flags=")(\d+)"',
                        lambda m: m.group(1) + str(int(m.group(2)) | 2).encode() + b'"',
                        data,
                    )
                    self.assertEqual(count, 1)
                archive.writestr(info, data)
        self.doc = FreeCAD.openDocument(path)
        self.dest = self.doc.getObject("Dest")
        self.source = self.doc.getObject("Source")
        seen = self.source.getPoint(-3, 1)
        self.copy()
        return seen

    def test_flipped_copy_flips_a_frozen_external(self):
        """PR 254 review F2: a frozen external point (a vertex at (3, 4, 0)), a line's end on it.
        The rebuild keeps a frozen external's geometry as copied, in Source's frame, so the copy
        must flip it like the internal geometry. Before, it stayed as the source saw it, and the
        solve dragged the copied line's end there."""
        self.turn_over()
        line = self.add_line((8, 1), (4, 2))
        seen = self.freeze_and_copy(Part.Vertex(V(3, 4, 0)), "Vertex1", line, 2)
        point = self.dest.getPoint(-3, 1)
        # where Dest sees the source's point (PR 254 round 1 glance (a))
        self.assertLess((point - self.image(seen)).Length, 1e-6)
        end = self.dest.Geometry[line].EndPoint
        self.assertLess((point - end).Length, 1e-6)

    def test_flipped_copy_keeps_a_point_on_a_frozen_external_arcs_start(self):
        """PR 254 round 1 glance (b): a frozen external arc (a quarter of the circle of radius 4
        about (-15, 5, 0) in Dest's plane), a line's start on its start. The copy flips it as
        copied, and a mirrored arc runs the other way: the ends compare as swapped, so the
        copied constraint names the copied arc's end, and the solve moves nothing."""
        self.turn_over()
        where = self.dest.Placement
        arc = Part.makeCircle(
            4, where.multVec(V(-15, 5, 0)), where.Rotation.multVec(V(0, 0, 1)), 0, 90
        )
        line = self.add_line((-20, 12), (-25, 15))
        seen = self.freeze_and_copy(arc, "Edge1", line, 1)
        start = self.dest.Geometry[line].StartPoint
        self.assertLess((start - self.image(seen)).Length, 1e-6)


class TestCarbonCopyFlippedInAMovedSketch(TestCarbonCopyFlipped):
    """ops#283: as above, with Dest off the origin and turned (at (5, 3, 2), 90 degrees about
    Z), and Source turned over about Dest's Y axis, so x flips. The flip is a mirror in Dest's
    own frame. Before, it mirrored about Dest's position and its axes taken in the global frame:
    the copy was shifted, and with Dest turned, y flipped instead of x."""

    def setUp(self):
        super().setUp()
        self.dest.Placement = FreeCAD.Placement(V(5, 3, 2), FreeCAD.Rotation(V(0, 0, 1), 90))

    def turn_over(self, tilt=0, spin=0):
        """Source turned over, 180 degrees about Dest's Y: Dest sees it with x the other way.
        Then tilted by `tilt` degrees about its own X, and turned by `spin` about its normal."""
        turn = FreeCAD.Rotation(V(0, 1, 0), 180).multiply(FreeCAD.Rotation(V(1, 0, 0), tilt))
        turn = turn.multiply(FreeCAD.Rotation(V(0, 0, 1), spin))
        self.place(turn, lambda p: V(-p.x, p.y, 0))


class TestCarbonCopyFlippedInATiltedSketch(TestCarbonCopyFlippedInAMovedSketch):
    """PR 254 review F4: as TestCarbonCopyFlippedInAMovedSketch, Dest turned about a tilted
    axis (70 degrees about (1, 1, 1))."""

    def setUp(self):
        super().setUp()
        self.dest.Placement = FreeCAD.Placement(V(5, 3, 2), FreeCAD.Rotation(V(1, 1, 1), 70))


if __name__ == "__main__":
    unittest.main()
