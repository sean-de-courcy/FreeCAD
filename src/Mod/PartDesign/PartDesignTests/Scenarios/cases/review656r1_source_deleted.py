# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prrows656-r1 (ops#656 D4 row 2): a sketch's external source object is deleted.

A 20 x 20 x 10 box (Part::Box). A sketch on the XY plane, outside any body, projects the box's top
edge on y = 0 (z = 10) and holds a circle of radius 1 whose centre is PointOnObject on the
projected line. The edit deletes the box. The element is gone: a loud break is the only right
answer. Deleting the source empties ExternalGeometry (the link goes with the object), while the
frozen line stays in ExternalGeo."""

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import BROKEN, Scenario, X, edge

V = App.Vector


class SketchExternalSourceDeleted(Scenario):
    """The box a sketch projects an edge of is deleted."""

    area = "external-missing"
    CLASSES = ("D",)
    AXES = ("M1", "E7")
    ISSUE = "ops#656"
    FOUND_BY = "review prrows656-r1"
    TIER = "F"
    REFS = ("external_edge",)
    edited = False

    def want(self):
        return BROKEN if self.edited else edge("line", direction=X, through=(0, 0, 10))

    def build(self, doc):
        box = doc.addObject("Part::Box", "Src")
        box.Length, box.Width, box.Height = 20, 20, 10
        sketch = doc.addObject("Sketcher::SketchObject", "Sk")
        doc.recompute()
        names = [
            f"Edge{i + 1}"
            for i, e in enumerate(box.Shape.Edges)
            if abs(e.BoundBox.ZMin - 10) < 1e-6
            and abs(e.BoundBox.ZMax - 10) < 1e-6
            and abs(e.BoundBox.YMax) < 1e-6
        ]
        if len(names) != 1:
            raise RuntimeError(f"{len(names)} top edges on y = 0")
        sketch.addExternal("Src", names[0])
        circle = sketch.addGeometry(Part.Circle(V(5, 0, 0), V(0, 0, 1), 1))
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, -3))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1.0))
        doc.recompute()
        self.ref("external_edge", sketch, "ExternalGeometry", lambda: self.want())

    def edit(self, doc):
        doc.removeObject("Src")
        self.edited = True
