# SPDX-License-Identifier: LGPL-2.1-or-later

"""A sketch's element names in a V1 document, which upstream (FreeCAD 1.1) spells
`g<id>;SKT` and `g<id>v<n>;SKT`, and the references to them that a saved file holds (ops#44)."""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD
import Part
import Sketcher  # noqa: F401

App = FreeCAD
V = App.Vector


class TestSketchNamesV1(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestSketchNamesV1")
        self.doc.HistoryAlgorithm = "V1"
        self.tempDir = os.path.realpath(tempfile.mkdtemp())

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        shutil.rmtree(self.tempDir, ignore_errors=True)

    def lines(self, sketch, count):
        """Horizontal lines of length 10 at y = 0, 10, 20, ...; returns their geometry IDs."""
        for i in range(count):
            sketch.addGeometry(Part.LineSegment(V(0, 10 * i, 0), V(10, 10 * i, 0)))
        return [sketch.getGeometryId(i) for i in range(count)]

    def testNamesAsUpstream(self):
        """Edges, line ends and a point are named with no tag section after SKT."""
        sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        line, = self.lines(sketch, 1)
        sketch.addGeometry(Part.Point(V(5, 5, 0)))  # a point makes the shape a compound
        point = sketch.getGeometryId(1)
        self.doc.recompute()
        names = sketch.Shape.ElementReverseMap
        self.assertEqual(names["Edge1"], f"g{line};SKT")
        ends = {names["Vertex1"], names["Vertex2"]}
        self.assertEqual(ends, {f"g{line}v1;SKT", f"g{line}v2;SKT"})
        self.assertEqual(names["Vertex3"], f"g{point}v1;SKT")

    def testSavedReferencesFollowTheirLines(self):
        """A file stores references to the sketch's edges by upstream's names, and they follow
        their lines when an earlier line is deleted."""
        sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        _, middle, top = self.lines(sketch, 3)
        self.doc.recompute()
        ruled = self.doc.addObject("Part::RuledSurface", "Ruled")
        ruled.Curve1 = (sketch, ["Edge2"])
        ruled.Curve2 = (sketch, ["Edge3"])
        self.doc.recompute()

        path = os.path.join(self.tempDir, "names.FCStd")
        self.doc.saveAs(path)
        xml = zipfile.ZipFile(path).read("Document.xml").decode()
        shadows = re.findall(r'<Sub value="(Edge\d)" shadow="([^"]*)"', xml)
        self.assertEqual(
            shadows, [("Edge2", f";g{middle};SKT.Edge2"), ("Edge3", f";g{top};SKT.Edge3")]
        )

        sketch.delGeometry(0)
        self.doc.recompute()
        self.assertEqual(ruled.Curve1[1], ["Edge1"])
        self.assertEqual(ruled.Curve2[1], ["Edge2"])
        box = ruled.Shape.BoundBox
        self.assertAlmostEqual(box.YMin, 10.0)
        self.assertAlmostEqual(box.YMax, 20.0)


if __name__ == "__main__":
    unittest.main()
