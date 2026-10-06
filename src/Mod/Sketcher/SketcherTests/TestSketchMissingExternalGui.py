# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opening a sketch whose external geometry lost its element (ops#72, ops#75).

`ViewProviderSketch::setEdit` runs `SketchObject::validateExternalLinks` whenever the sketch's
support isn't a Part::Feature, an origin plane included. It removed each link whose element
can't be found and deleted constraints by the link's index, not by its external geometry's
(ops#75). A missing link now keeps its frozen geometry and the constraints on it when the sketch
is opened, as it does on recompute (ops#72). Designed geometry, judged geometrically."""

import FreeCAD
import Part
import Sketcher

from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase
from SketcherTests.TestSketchMissingExternal import (
    TOL,
    add_lines,
    edge_between,
    external_lines,
    face_at_x,
)

App = FreeCAD
V = App.Vector


class TestSketchMissingExternalGui(SketcherGuiTestCase):
    """A 20 x 20 x 10 pad from a sketch at z = 0; the edit replaces the profile's line at x = 20
    by a V, (20, 0)-(25, 10)-(20, 20), so the side face at x = 20 and its edges are gone."""

    def setUp(self):
        super().setUp()
        if "BUILD_PART_DESIGN" not in App.__cmake__:
            self.skipTest("needs PartDesign")
        self.doc = App.newDocument("TestSketchMissingExternalGui")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.profile = self.body.newObject("Sketcher::SketchObject", "Profile")
        add_lines(self.profile, [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)])
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Length = 10
        self.doc.recompute()

    def plane(self, role):
        return [f for f in self.body.Origin.OriginFeatures if f.Role == role][0]

    def sketchOn(self, name, role):
        sketch = self.body.newObject("Sketcher::SketchObject", name)
        sketch.AttachmentSupport = [(self.plane(role), "")]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        return sketch

    def circleOn(self, sketch, center, geoId):
        """A circle r 1 whose centre lies on the external geometry geoId."""
        circle = sketch.addGeometry(Part.Circle(center, V(0, 0, 1), 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, geoId))
        return circle

    def replaceRightSide(self):
        self.profile.delGeometry(1)
        add_lines(self.profile, [(20, 0), (25, 10), (20, 20)])
        self.doc.recompute()
        self.assertAlmostEqual(self.pad.Shape.BoundBox.XMax, 25, delta=TOL)

    def openAndClose(self, sketch):
        FreeCADGui.ActiveDocument.setEdit(sketch.Name)
        self.flush_gui()
        FreeCADGui.ActiveDocument.resetEdit()
        self.flush_gui()

    def externalConstraints(self, sketch):
        return sorted(
            (c.First, c.Second)
            for c in sketch.Constraints
            if c.Type == "PointOnObject" and c.Second <= -3
        )

    def testOpeningKeepsTheMissingLink(self):
        """A sketch on the XY plane with the pad's top edge at x = 20 as external geometry and a
        circle centred on it: opened after the edit, it keeps the link, the frozen line at x = 20
        and the constraint on it, and still fails."""
        sketch = self.sketchOn("OnRight", "XY_Plane")
        top = edge_between(self.pad.Shape, (20, 0, 10), (20, 20, 10))
        sketch.addExternal(self.pad.Name, top)
        self.circleOn(sketch, V(20, 10, 0), -3)
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())

        self.replaceRightSide()
        self.assertFalse(sketch.isValid())
        self.openAndClose(sketch)

        self.assertEqual(sketch.ExternalGeometry, [(self.pad, ("?" + top,))])
        lines = external_lines(sketch)
        self.assertEqual(len(lines), 1)
        self.assertTrue(all(abs(p.x - 20) < TOL for p in lines[0]))
        self.assertEqual(self.externalConstraints(sketch), [(0, -3)])
        self.doc.recompute()
        self.assertFalse(sketch.isValid())

    def testOpeningKeepsEachLinksConstraints(self):
        """A sketch on the YZ plane with two links: (1) the pad's side face at x = 20, which
        projects to four edges, and (2) the top edge at x = 0. Circle 0 is centred on link 2's
        line, circle 1 on link 1's first edge. After the edit link 1 is missing; opening the sketch
        keeps both links and both constraints, each on its own geometry (ops#75: the old code
        deleted the constraints on geometry -3 and moved link 2's onto a frozen edge of link 1)."""
        sketch = self.sketchOn("OnSide", "YZ_Plane")
        face = face_at_x(self.pad.Shape, 20)
        edge = edge_between(self.pad.Shape, (0, 0, 10), (0, 20, 10))
        sketch.addExternal(self.pad.Name, face)
        sketch.addExternal(self.pad.Name, edge)
        self.doc.recompute()
        lines = external_lines(sketch)
        self.assertEqual(len(lines), 5)
        # link 2's line: the x = 0 top edge projected onto the YZ plane, (0, 0, 10)-(0, 20, 10)
        self.assertTrue(all(abs(p.z - 10) < TOL for p in lines[4]))
        middle = (lines[4][0] + lines[4][1]) * 0.5
        self.circleOn(sketch, sketch.getGlobalPlacement().inverse().multVec(middle), -7)
        first = (lines[0][0] + lines[0][1]) * 0.5
        self.circleOn(sketch, sketch.getGlobalPlacement().inverse().multVec(first), -3)
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())

        self.replaceRightSide()
        if getattr(self.doc, "ReferenceSolver", False):
            # link 2 resolves: a reference solver document computes on it, warned (ops#127)
            self.assertTrue(sketch.isValid(), sketch.getStatusString())
            self.assertIn("Warning", sketch.State)
        else:
            self.assertFalse(sketch.isValid())
        self.openAndClose(sketch)

        edge = edge_between(self.pad.Shape, (0, 0, 10), (0, 20, 10))  # renumbered by the edit
        self.assertEqual(sketch.ExternalGeometry, [(self.pad, ("?" + face, edge))])
        self.assertEqual(len(external_lines(sketch)), 5)
        self.assertEqual(self.externalConstraints(sketch), [(0, -7), (1, -3)])
        # circle 0's centre still lies on link 2's line
        self.doc.recompute()
        center = sketch.getGlobalPlacement().multVec(sketch.Geometry[0].Center)
        self.assertAlmostEqual(center.z, 10, delta=TOL)
        self.assertAlmostEqual(center.x, 0, delta=TOL)
