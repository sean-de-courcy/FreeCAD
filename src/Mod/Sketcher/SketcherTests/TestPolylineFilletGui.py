# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD
import Part
from PySide import QtCore, QtGui
from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase


class TestPolylineFilletGui(SketcherGuiTestCase):
    """A polyline drawn with the tool's fillet option keeps every clicked point."""

    # Screen offsets from the projected origin, in widget pixels (y down). The zigzag keeps every
    # segment well away from horizontal and vertical, and every point away from the axes, so no
    # auto-constraint or snap moves a click.
    CLICK_OFFSETS = ((-150, 60), (-60, -70), (40, 70), (140, -60))
    PIXEL_TOLERANCE = 3

    def setUp(self):
        super().setUp()
        if not QtGui.QFontDatabase.families():
            # Off screen without QT_QPA_FONTDIR: drawing the fillet's merged constraint icons
            # throws, which aborts the fillet halfway.
            self.skipTest("Qt has no fonts; off screen, set QT_QPA_FONTDIR")

        FreeCADGui.activateWorkbench("SketcherWorkbench")
        self.doc = FreeCAD.newDocument("TestPolylineFilletGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.doc.recompute()

    def begin_sketch_edit(self):
        FreeCADGui.getMainWindow().show()
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.pump(200)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected sketch edit mode")

        view = FreeCADGui.ActiveDocument.ActiveView
        view.viewTop()
        view.fitAll()
        self.pump(150)
        return view, view.graphicsView().viewport()

    def screen_point(self, view, viewport, point):
        return self.viewport_to_qpoint(view, viewport, view.getPointOnScreen(point))

    def fillet_checkbox(self):
        boxes = [
            box
            for box in FreeCADGui.getMainWindow().findChildren(QtGui.QCheckBox)
            if box.isVisible() and box.text().startswith("Fillet")
        ]
        self.assertEqual(len(boxes), 1, "Expected the polyline tool's fillet checkbox")
        return boxes[0]

    def sketch_point(self, view, viewport, qpoint):
        """The point on the sketch plane under a widget position, and the size of a pixel there.
        The sketch is viewed from the top, so its plane is parallel to the focal plane."""
        _, height = view.getSize()
        scale = self.device_pixel_ratio(viewport)
        x = int(round(qpoint.x() * scale))
        y = int(round(height - 1 - qpoint.y() * scale))
        point = view.getPointOnFocalPlane(x, y)
        pixel = (view.getPointOnFocalPlane(x + 1, y) - point).Length
        return FreeCAD.Vector(point.x, point.y, 0), pixel

    def assert_near_click(self, point, click, what):
        clicked, pixel = click
        distance = (FreeCAD.Vector(point.x, point.y, 0) - clicked).Length
        self.assertLessEqual(
            distance,
            self.PIXEL_TOLERANCE * pixel,
            f"Expected {what} at the clicked point {clicked}, found it at {point}",
        )

    @staticmethod
    def line_intersection(line1, line2):
        p, r = line1.StartPoint, line1.EndPoint - line1.StartPoint
        q, s = line2.StartPoint, line2.EndPoint - line2.StartPoint
        denominator = r.x * s.y - r.y * s.x
        t = ((q.x - p.x) * s.y - (q.y - p.y) * s.x) / denominator
        return p + r * t

    def test_filleted_polyline_keeps_its_points(self):
        """Four clicks with the fillet option make one open chain through all four points:
        three lines joined by two fillet arcs, starting at the first click and ending at the
        last, with each inner click at the corner of the two lines around it.

        Before the fix, the tool continued from the fillet's construction corner piece after the
        first fillet, so the third line started at the fillet's tangent point instead of the third
        click, and the trimmed second line was left dangling (FreeCAD issue 32428).
        """
        view, viewport = self.begin_sketch_edit()
        origin = self.screen_point(view, viewport, FreeCAD.Vector(0, 0, 0))
        clicks = [
            self.clamp_to_widget(viewport, QtCore.QPoint(origin.x() + dx, origin.y() + dy))
            for dx, dy in self.CLICK_OFFSETS
        ]
        for a, b in zip(clicks, clicks[1:]):
            self.assertGreater(
                abs(a.x() - b.x()) + abs(a.y() - b.y()), 100, "Viewport too small for the test"
            )

        FreeCADGui.runCommand("Sketcher_CreatePolyline")
        self.pump(250)
        checkbox = self.fillet_checkbox()
        checkbox.setChecked(True)
        self.flush_gui(50)

        # Where each click lands on the sketch, taken at the time of the click: the viewport
        # changes size when the tool's panel closes.
        clicked = []
        try:
            for click in clicks:
                clicked.append(self.sketch_point(view, viewport, click))
                self.move(viewport, click)
                self.click(viewport, click)
            # Right-click ends the polyline; a second one leaves the tool.
            self.right_click(viewport, clicks[-1])
            self.right_click(viewport, clicks[-1])
        finally:
            if checkbox.isVisible():
                checkbox.setChecked(False)
        self.flush_gui(100)

        geometry = self.sketch.Geometry
        normal = [(i, geo) for i, geo in enumerate(geometry) if not self.sketch.getConstruction(i)]
        lines = [geo for _, geo in normal if isinstance(geo, Part.LineSegment)]
        arcs = [geo for _, geo in normal if isinstance(geo, Part.ArcOfCircle)]
        self.assertEqual(
            (len(lines), len(arcs)),
            (3, 2),
            "Expected three lines and two fillet arcs, got "
            f"{[type(geo).__name__ for _, geo in normal]}",
        )

        edges = [geo.toShape() for _, geo in normal]
        chains = Part.sortEdges(edges)
        self.assertEqual(len(chains), 1, "Expected the polyline to be one connected chain")
        wire = Part.Wire(chains[0])
        self.assertFalse(wire.isClosed(), "Expected an open polyline")

        # The chain's two free ends are the first and the last click.
        # The clicks run left to right, so sorting on x orders the ends and the lines along the
        # chain.
        ends = sorted(
            (
                vertex.Point
                for vertex in wire.Vertexes
                if len(wire.ancestorsOfType(vertex, Part.Edge)) == 1
            ),
            key=lambda point: point.x,
        )
        self.assertEqual(len(ends), 2, "Expected an open chain with two free ends")
        self.assert_near_click(ends[0], clicked[0], "the polyline's start")
        self.assert_near_click(ends[1], clicked[-1], "the polyline's end")

        # Each inner click is the corner the fillet replaced: the intersection of the two lines
        # around it.
        lines.sort(key=lambda line: line.StartPoint.x + line.EndPoint.x)
        for index, click in enumerate(clicked[1:-1]):
            corner = self.line_intersection(lines[index], lines[index + 1])
            self.assert_near_click(corner, click, f"corner {index + 1}")
