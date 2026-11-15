# SPDX-License-Identifier: LGPL-2.1-or-later

"""The sketch axes of a FlatFace attachment on a face tilted near 45 degrees (FreeCAD-CH ops#692).

FlatFace takes its X axis by the world axis the face normal is closest to. With a bare maximum, a
face at exactly 45 degrees between Z and X (or Y) picked by the last bit of the normal, so mirror-image
faces of one part got frames a quarter turn apart. Onshape (fact GS12c) never gives an exact 45-degree
face to Z: Z wins over X only beyond 44.76132 degrees from Z, and over Y beyond 44.72423 degrees.

Designed model: a 10 mm cube whose geometry (not its placement) is rotated so that its +Z face has the
normal (sin t, 0, cos t), (-sin t, 0, cos t), (0, sin t, cos t) or (0, -sin t, cos t), t from Z. The
expected sketch x, by Onshape's rule:
- Z wins (t below the handover): world X projected onto the face;
- toward +X: +Y; toward -X: -Y; toward +Y: -X; toward -Y: +X."""

import math
import unittest

import FreeCAD as App
import Part

V = App.Vector

HANDOVER_X = 44.76132
HANDOVER_Y = 44.72423


def tilted_cube_face(axis, sign, degrees):
    """The +Z face of a 10 mm cube rotated by `degrees` so its normal leans toward sign*axis."""
    box = Part.makeBox(10, 10, 10, V(-5, -5, -5))
    # A rotation about Y by +t tips +Z toward +X; about X by -t tips +Z toward +Y.
    # transformGeometry, not rotate: the attacher reads the support's placement as its axes.
    if axis == "X":
        rotation = App.Rotation(V(0, 1, 0), sign * degrees)
    else:
        rotation = App.Rotation(V(1, 0, 0), -sign * degrees)
    box = box.transformGeometry(App.Placement(V(), rotation).toMatrix())
    t = math.radians(degrees)
    want = V(sign * math.sin(t), 0, math.cos(t)) if axis == "X" else V(0, sign * math.sin(t), math.cos(t))
    for i, face in enumerate(box.Faces):
        n = face.normalAt(0.5, 0.5)
        if (n - want).Length < 1e-9:
            return box, "Face%d" % (i + 1), n
    raise AssertionError("no face with normal %s" % want)


def expected_x(axis, sign, degrees, normal):
    handover = HANDOVER_X if axis == "X" else HANDOVER_Y
    if degrees < handover:
        x = V(1, 0, 0)
        x = x - normal * x.dot(normal)
        return x.normalize()
    if axis == "X":
        return V(0, sign, 0)
    return V(-sign, 0, 0)


class FlatFaceAxesTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("FlatFaceAxes")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sketch_x(self, shape, face):
        feature = self.doc.addObject("Part::Feature", "Tilted")
        feature.Shape = shape
        self.doc.recompute()
        engine = Part.AttachEngine("Attacher::AttachEngine3D")
        engine.References = [(feature, face)]
        engine.Mode = "FlatFace"
        placement = engine.calculateAttachedPlacement(App.Placement())
        return placement.Rotation.multVec(V(1, 0, 0))

    def test_handover_angles(self):
        # 44.74 lies between the two handovers: Z toward X, Y toward Y.
        for degrees in (44.5, 44.74, 44.9, 45.0, 45.1):
            for axis in ("X", "Y"):
                for sign in (1, -1):
                    with self.subTest(degrees=degrees, axis=axis, sign=sign):
                        shape, face, normal = tilted_cube_face(axis, sign, degrees)
                        got = self.sketch_x(shape, face)
                        want = expected_x(axis, sign, degrees, normal)
                        self.assertLess((got - want).Length, 1e-9, "x %s, want %s" % (got, want))

    def test_exact_45_never_z_either_last_bit(self):
        # The same 45-degree face with the normal's last bit forced both ways.
        s = math.sqrt(0.5)
        for nx, nz in ((s, math.nextafter(s, 1)), (math.nextafter(s, 1), s)):
            for sign in (1, -1):
                with self.subTest(nx=nx, nz=nz, sign=sign):
                    normal = V(sign * nx, 0, nz).normalize()
                    plane = Part.Plane(V(0, 0, 0), normal)
                    face = plane.toShape(-5, 5, -5, 5)
                    got = self.sketch_x(face, "Face1")
                    self.assertLess((got - V(0, sign, 0)).Length, 1e-6, "x %s" % got)


if __name__ == "__main__":
    unittest.main()
