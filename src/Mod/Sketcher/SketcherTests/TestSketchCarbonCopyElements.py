# SPDX-License-Identifier: LGPL-2.1-or-later

"""Carbon copy remaps every element of a constraint, headless (ops#247, ops#267).

A Group holds any number of elements, and each can name internal geometry, an axis, the root
point, external geometry or nothing (GeoUndef). Designed geometry: a 10 x 10 square in the source,
one line apart from it in the destination, and edges of a box as external geometry; each copied
element must name a geometry equal to the source's, with its position unchanged."""

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

    def test_mirrored_copy_refuses_a_constraint_on_a_self_reference(self):
        """Source turned over (180 degrees about X), so its copy is mirrored, while Dest's own
        geometry isn't: which end of Edge2 a constraint on a line external at Dest.Edge2 names
        isn't known, so that constraint isn't copied (with a warning). The length named width
        after it is, and its expression lands on it, not one constraint further on."""
        self.source.Placement = FreeCAD.Placement(V(), FreeCAD.Rotation(V(1, 0, 0), 180))
        self.dest.setAllowUnaligned(False)  # True (the default) copies without flipping
        # Edge2 seen from the turned-over Source: y runs the other way
        facade = Sketcher.ExternalGeometryFacade(Part.LineSegment(V(10, 0, 0), V(10, -10, 0)))
        facade.Ref = "Dest.Edge2"
        self.source.ExternalGeo = list(self.source.ExternalGeo) + [facade.Geometry]
        self.source.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
        width = self.source.addConstraint(Sketcher.Constraint("Distance", 0, 10))
        self.source.renameConstraint(width, "width")
        self.dest.carbonCopy("Source", False)
        self.assertEqual(len(self.dest.ExternalGeo), 2)
        self.assertEqual([c.Type for c in self.dest.Constraints], ["Distance"])
        paths = [path for path, _ in self.dest.ExpressionEngine]
        self.assertEqual(len(paths), 1)
        self.assertIn(paths[0], ("Constraints[0]", ".Constraints[0]", ".Constraints.width"))


if __name__ == "__main__":
    unittest.main()
