# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: Onshape's rules for the Draft feature (ops#640, rank 17).

"""A Draft waits for its neutral plane: with faces picked and no neutral plane it fails with
Onshape's message, "Select a neutral plane.", instead of guessing one from the first face's
edges. Designed geometry: a 10 mm box; the front face drafted 2 degrees about the bottom plane
changes the volume by 1/2 * 10 * 10 * tan(2 deg) * 10 = 500 tan(2 deg)."""

import math
import unittest

import FreeCAD

App = FreeCAD
V = App.Vector

MESSAGE = "Select a neutral plane."
DRAFT_CHANGE = 500 * math.tan(math.radians(2))


def faceWhere(shape, normal, point):
    """The name of the planar face of `shape` with outward `normal` through `point`."""
    for i, f in enumerate(shape.Faces, 1):
        n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
        if n.sub(normal).Length < 1e-9 and abs(n.dot(f.CenterOfMass.sub(point))) < 1e-9:
            return f"Face{i}"
    raise AssertionError(f"no face with normal {normal} through {point}")


class TestDraftNeedsNeutralPlane(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("PartDesignTestDraftRules")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        self.box.Length = self.box.Width = self.box.Height = 10
        self.doc.recompute()
        self.front = faceWhere(self.box.Shape, V(0, -1, 0), V(0, 0, 0))
        self.bottom = faceWhere(self.box.Shape, V(0, 0, -1), V(0, 0, 0))

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def draft(self, faces):
        draft = self.body.newObject("PartDesign::Draft", "Draft")
        draft.Base = (self.box, faces)
        draft.Angle = 2
        return draft

    def testNoNeutralPlaneFailsRed(self):
        """Faces and no neutral plane: the draft is in error with Onshape's message (it used to
        guess a plane from the face's bottom edge and succeed)."""
        draft = self.draft([self.front])
        self.doc.recompute()
        self.assertFalse(draft.isValid())
        self.assertIn(MESSAGE, draft.getStatusString())

    def testNeutralPlanePickedDrafts(self):
        """The same draft once its neutral plane is picked: valid, the volume changed by the
        closed-form wedge."""
        draft = self.draft([self.front])
        self.doc.recompute()
        self.assertFalse(draft.isValid())
        draft.NeutralPlane = (self.box, [self.bottom])
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        self.assertAlmostEqual(abs(draft.Shape.Volume - 1000), DRAFT_CHANGE, places=6)

    def testClearedNeutralPlaneFails(self):
        """A valid draft whose neutral plane is cleared goes red; nothing is guessed."""
        draft = self.draft([self.front])
        draft.NeutralPlane = (self.box, [self.bottom])
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        draft.NeutralPlane = None
        self.doc.recompute()
        self.assertFalse(draft.isValid())
        self.assertIn(MESSAGE, draft.getStatusString())

    def testOriginPlaneIsANeutralPlane(self):
        """The body's XY plane as the neutral plane: valid, the same wedge."""
        draft = self.draft([self.front])
        [xy] = [f for f in self.body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        draft.NeutralPlane = (xy, [""])
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        self.assertAlmostEqual(abs(draft.Shape.Volume - 1000), DRAFT_CHANGE, places=6)

    def testNoFacesStaysACopy(self):
        """No faces and no neutral plane: still the base unchanged, no error (only a picked face
        asks for the plane)."""
        draft = self.draft([])
        self.doc.recompute()
        self.assertTrue(draft.isValid(), draft.getStatusString())
        self.assertAlmostEqual(draft.Shape.Volume, 1000, places=6)


if __name__ == "__main__":
    unittest.main()
