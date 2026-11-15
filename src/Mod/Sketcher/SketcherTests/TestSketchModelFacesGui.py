# SPDX-License-Identifier: LGPL-2.1-or-later

"""A sketch dimension or constraint to a planar model face (FreeCAD-CH, ops#640, rank 19).

Onshape's Dimension takes a planar part face perpendicular to the sketch plane (hands-on F4): the
face counts as its trace on the plane, a line. A face parallel to the sketch plane gets no hover
and is refused with "A dimension cannot be created between these items" (hands-on C-6). FreeCAD-CH:
plain edit mode's gate, the constraint tools' gates and the Dimension tool's gate let such a face
through; it is linked as external geometry (one line, SketchObject's processFace), as a model edge
is (ops#634), and a parallel face is refused.

Designed geometry (TestSketchModelPicksGui's): a 20 x 10 x 5 box Pad from the origin, and a sketch
on the XY plane offset to z 5 (the box's top) with one line from (2, 2) to (8, 2). The box's face
at x = 20 is perpendicular to the sketch plane: its trace is the line x = 20, so the line's start
(2, 2) is 18 from it. The box's top face (z = 5) is parallel to the sketch plane."""

import FreeCAD

from SketcherTests.GuiTestCase import FreeCADGui
from SketcherTests.TestSketchModelPicksGui import TOL, ModelPicksGuiCase


class TestSketchModelFacesGui(ModelPicksGuiCase):
    def face_in_plane(self, axis, value):
        """The Pad's face lying in the plane axis = value ("x", "y" or "z")."""
        for i, face in enumerate(self.pad.Shape.Faces):
            box = face.BoundBox
            lo, hi = {
                "x": (box.XMin, box.XMax),
                "y": (box.YMin, box.YMax),
                "z": (box.ZMin, box.ZMax),
            }[axis]
            if abs(lo - value) < TOL and abs(hi - value) < TOL:
                return "Face%d" % (i + 1)
        self.fail("No face of the Pad in the plane %s = %s" % (axis, value))

    def test_plain_edit_takes_a_perpendicular_face_not_a_parallel_one(self):
        """The box's x = 20 face can be selected beside a sketch element; its top face can't."""
        self.start_edit()
        side = self.face_in_plane("x", 20)
        top = self.face_in_plane("z", 5)
        self.select((self.sketch, "Edge1"), (self.pad, side), (self.pad, top))
        self.assertEqual(self.selected(), {("Sketch", "Edge1"), ("Pad", side)})

    def test_a_rotated_body_changes_nothing(self):
        """The Body turned 90 deg about x: its features and the sketch keep their places in it,
        and the face is read in the sketch's frame (as its external geometry is), so the x = 20
        face is still taken and the top face still refused. Read in the document's frame instead,
        the top face's normal (now -y) would be perpendicular to the sketch's local normal z."""
        self.body.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 0, 0), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)
        )
        self.doc.recompute()
        self.start_edit()
        side = self.face_in_plane("x", 20)
        top = self.face_in_plane("z", 5)
        self.select((self.sketch, "Edge1"), (self.pad, side), (self.pad, top))
        self.assertEqual(self.selected(), {("Sketch", "Edge1"), ("Pad", side)})

    def test_distance_to_a_perpendicular_face(self):
        """The line's start (2, 2) and the x = 20 face, then Distance: 18, to the face's trace,
        the line x = 20; one link, one undo step."""
        self.start_edit()
        self.select((self.sketch, "Vertex1"), (self.pad, self.face_in_plane("x", 20)))
        self.run_command("Sketcher_ConstrainDistance")

        distances = self.constraints_of("Distance")
        self.assertEqual(len(distances), 1)
        self.assertAlmostEqual(distances[0].Value, 18.0, places=6)
        self.assertEqual(len(self.sketch.ExternalGeometry), 1)
        trace = self.sketch.ExternalGeo[-distances[0].Second - 1]
        self.assertAlmostEqual(trace.StartPoint.x, 20.0, places=6)
        self.assertAlmostEqual(trace.EndPoint.x, 20.0, places=6)
        self.assertEqual(self.doc.UndoCount, self.undo_start + 1)

    def test_point_on_a_perpendicular_face(self):
        """The line's end (8, 2) on the x = 20 face (Point on object): the end moves to x = 20."""
        self.start_edit()
        self.select((self.sketch, "Vertex2"), (self.pad, self.face_in_plane("x", 20)))
        self.run_command("Sketcher_ConstrainPointOnObject")
        self.assertEqual(len(self.constraints_of("PointOnObject")), 1)
        self.assertAlmostEqual(self.line_point(2).x, 20.0, places=6)

    def test_the_dimension_tool_takes_a_perpendicular_face_and_refuses_a_parallel_one(self):
        """In the Dimension tool the top face (parallel) is refused and links nothing; the x = 20
        face is linked (one external line)."""
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.run_command("Sketcher_Dimension")
        FreeCADGui.Selection.addSelection(self.doc.Name, self.pad.Name, self.face_in_plane("z", 5))
        self.flush_gui(100)
        self.assertEqual(len(self.sketch.ExternalGeometry), 0, "the parallel face was linked")
        FreeCADGui.Selection.addSelection(self.doc.Name, self.pad.Name, self.face_in_plane("x", 20))
        self.flush_gui(100)
        self.assertEqual(len(self.sketch.ExternalGeometry), 1, "the perpendicular face wasn't linked")
