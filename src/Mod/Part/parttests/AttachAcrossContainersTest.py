# SPDX-License-Identifier: LGPL-2.1-or-later
"""Attachment across containers in the Part workbench (FreeCAD-CH ops#318): a Part feature in one
App::Part attached to an element of a feature in another read that element in the other Part's
coordinates as if they were its own, silently. Designed geometry; the oracle is the face's global
plane (the attached object's global z axis along the face's normal, its origin on the face)."""

import unittest

import FreeCAD
import Part

V = FreeCAD.Vector
R = FreeCAD.Rotation
P = FreeCAD.Placement
TOL = 1e-7

# The two App::Parts' placements
PAIRS = {
    "FirstMoved": (P(V(100, 50, 0), R()), P()),
    "SecondMoved": (P(), P(V(30, 0, 7), R())),
    "BothRotated": (P(V(100, 50, 0), R(V(1, 0, 0), 30)), P(V(30, 0, 7), R(V(0, 1, 0), 45))),
    "EqualRotated": (P(V(5, 6, 7), R(V(1, 1, 0), 20)), P(V(5, 6, 7), R(V(1, 1, 0), 20))),
}


def topFace(feature, z):
    [name] = [f"Face{i}" for i, f in enumerate(feature.Shape.Faces, 1)
              if abs(f.normalAt(0, 0).z - 1) < 1e-9 and abs(f.CenterOfMass.z - z) < 1e-6]
    return name


def globalElement(feature, name):
    element = feature.Shape.getElement(name).copy()
    group = feature.getParentGeoFeatureGroup()
    if group:
        element.Placement = group.getGlobalPlacement().multiply(element.Placement)
    return element


class AttachAcrossContainersTest(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("PartTestAttachAcross")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def fresh(self):
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.newDocument("PartTestAttachAcross")

    def assertOnFace(self, obj, face):
        frame = obj.getGlobalPlacement()
        z = frame.Rotation.multVec(V(0, 0, 1))
        normal = face.normalAt(0, 0)
        self.assertLess(z.cross(normal).Length, TOL, (obj.Name, frame, normal))
        self.assertGreater(z.dot(normal), 0)
        self.assertLess(abs((frame.Base - face.CenterOfMass).dot(normal)), TOL,
                        (obj.Name, frame, face.CenterOfMass))

    def parts(self, pair):
        """Box BoxA (10 x 10 x 10, at (1, 2, 0) turned 10 deg about Z) in App::Part PA, and an
        App::Part PB, placed by the pair."""
        first, second = PAIRS[pair]
        partA = self.doc.addObject("App::Part", "PA")
        partA.Placement = first
        partB = self.doc.addObject("App::Part", "PB")
        partB.Placement = second
        box = self.doc.addObject("Part::Box", "BoxA")
        box.Placement = P(V(1, 2, 0), R(V(0, 0, 1), 10))
        partA.addObject(box)
        self.doc.recompute()
        return partA, partB, box

    def checkAttached(self, make):
        for pair in PAIRS:
            with self.subTest(pair=pair):
                self.fresh()
                partA, partB, box = self.parts(pair)
                top = topFace(box, 10)
                attached = make()
                partB.addObject(attached)
                attached.AttachmentSupport = [(box, top)]
                attached.MapMode = "FlatFace"
                self.doc.recompute()
                self.assertTrue(attached.isValid(), attached.getStatusString())
                self.assertOnFace(attached, globalElement(box, top))
                # The Python attachment editor's preview agrees with the feature
                engine = Part.AttachEngine("Attacher::AttachEngine3D")
                engine.readParametersFromFeature(attached)
                preview = engine.calculateAttachedPlacement(attached.Placement)
                self.assertTrue(preview.isSame(attached.Placement, 1e-9),
                                (preview, attached.Placement))

    def testBoxOnABoxInAnotherPart(self):
        """A-t5: a Part::Box in PB attached to the top of a box in PA."""
        self.checkAttached(lambda: self.doc.addObject("Part::Box", "BoxB"))

    def testDatumPlaneOnABoxInAnotherPart(self):
        """A-t12: a Part datum plane in PB attached to the top of a box in PA."""
        self.checkAttached(lambda: self.doc.addObject("Part::DatumPlane", "Datum"))

    def testPythonFeatureOnABoxInAnotherPart(self):
        """A-t12: an AttachExtensionPython feature (BasicShapes' tube) in PB."""
        from BasicShapes import Shapes

        self.checkAttached(lambda: Shapes.addTube(self.doc, "Tube"))

    def testTopLevelOnABoxInAPart(self):
        """A-t12: a top-level datum plane attached to the box in PA (its frame is the
        document's)."""
        for pair in ("FirstMoved", "BothRotated"):
            with self.subTest(pair=pair):
                self.fresh()
                _, _, box = self.parts(pair)
                top = topFace(box, 10)
                datum = self.doc.addObject("Part::DatumPlane", "Datum")
                datum.AttachmentSupport = [(box, top)]
                datum.MapMode = "FlatFace"
                self.doc.recompute()
                self.assertOnFace(datum, globalElement(box, top))
