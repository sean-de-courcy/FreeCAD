# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#683, design group C slice C4): instances that carry no mate, as Onshape's
# (notes/assemblies-design.md section 4; notes/onshape-facts.md GB10, GB11, B7).
#
# - A free instance (no mate, not grounded) keeps its placement through a solve of its assembly,
#   a save and a reopen, and an edit of its part in the studio (Onshape stores the instance's
#   transform; an edit of the part changes its shape, not where it is).
# - A hidden instance stays hidden after a save and a reopen (B7: `occurrences[].hidden` is
#   stored) and still counts in the BOM (B7: the hidden S is listed; a part inserted twice is
#   listed with quantity 2). Its mass is the GUI test's (TestFreeInstancesGui).
# Designed geometry: studios are PartDesign Bodies at the document's root, each one AdditiveBox;
# the assembly holds App::Link instances of them, as Insert makes them. Expected placements are
# the ones set; expected BOM rows are the studios' labels and counts.

import os
import tempfile
import unittest

import FreeCAD as App

import JointObject
import Part
import UtilsAssembly

V = App.Vector
TOL = 1e-9


class TestFreeInstances(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument(self.__class__.__name__)
        self.files = []

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        for path in self.files:
            if os.path.exists(path):
                os.remove(path)

    def studio(self, name, label, length, width, height):
        body = self.doc.addObject("PartDesign::Body", name)
        body.Label = label
        box = body.newObject("PartDesign::AdditiveBox", name + "Box")
        box.Length, box.Width, box.Height = length, width, height
        return body, box

    def instance(self, name, studio, plc):
        link = self.asm.newObject("App::Link", name)
        link.LinkedObject = studio
        link.Placement = plc
        return link

    def model(self):
        """Part 1 (10 x 10 x 10) grounded as G; Part 2 (20 x 10 x 5) as M, fastened onto G's
        top; Part 3 (30 x 20 x 10) as F, free, turned and moved off the origin."""
        self.asm = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.asm.Type = "Assembly"
        self.joints = self.asm.newObject("Assembly::JointGroup", "Joints")
        self.part1, _ = self.studio("Part1", "Part 1", 10, 10, 10)
        self.part2, _ = self.studio("Part2", "Part 2", 20, 10, 5)
        self.part3, self.box3 = self.studio("Part3", "Part 3", 30, 20, 10)
        self.g = self.instance("G", self.part1, App.Placement())
        self.m = self.instance("M", self.part2, App.Placement(V(50, 0, 0), App.Rotation()))
        self.freePlc = App.Placement(V(-35, 47, 12.5), App.Rotation(V(1, 2, 3), 37))
        self.f = self.instance("F", self.part3, self.freePlc)
        self.doc.recompute()
        ground = self.joints.newObject("App::FeaturePython", "GroundG")
        JointObject.GroundedJoint(ground, self.g)
        joint = self.joints.newObject("App::FeaturePython", "Fastened")
        JointObject.Joint(joint, 0)
        joint.Proxy.setJointConnectors(
            joint, [[self.m, ["Face6", "Face6"]], [self.g, ["Face6", "Face6"]]]
        )
        self.doc.recompute()
        self.assertTrue(joint.isValid(), joint.getStatusString())

    def assertAt(self, obj, plc, what):
        self.assertTrue(obj.Placement.isSame(plc, TOL), f"{what}: {obj.Name} at {obj.Placement}, not {plc}")

    def saveAndReopen(self):
        path = os.path.join(tempfile.gettempdir(), f"{self.doc.Name}_{os.getpid()}.FCStd")
        self.files.append(path)
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        return self.doc

    def testFreeInstanceKeepsItsPlacementThroughSolveSaveAndReopen(self):
        self.model()
        self.assertEqual(self.asm.solve(), 0)
        self.assertAt(self.f, self.freePlc, "after a solve")
        doc = self.saveAndReopen()
        asm, f = doc.getObject("Assembly"), doc.getObject("F")
        self.assertAt(f, self.freePlc, "after the reopen")
        doc.recompute()
        self.assertEqual(asm.solve(), 0)
        self.assertAt(f, self.freePlc, "after the reopen's recompute and solve")

    def testFreeInstanceKeepsItsPlacementThroughAnEditOfItsPart(self):
        self.model()
        self.box3.Length = 45
        self.box3.Height = 4
        self.doc.recompute()
        self.assertAlmostEqual(Part.getShape(self.f).Volume, 45 * 20 * 4, 6)
        self.assertEqual(self.asm.solve(), 0)
        self.assertAt(self.f, self.freePlc, "after its part changed")
        # The instance's shape is the part's, where the instance is
        expected = self.freePlc.multVec(V(45, 20, 4))
        self.assertIn(
            True,
            [(v.Point - expected).Length < 1e-6 for v in Part.getShape(self.f).Vertexes],
            "the instance's far corner is not where its placement puts it",
        )

    def testHiddenInstanceStaysHiddenAfterReopen(self):
        self.model()
        self.f.Visibility = False
        self.doc.recompute()
        self.assertEqual(self.asm.solve(), 0)
        self.assertFalse(self.f.Visibility, "the solve showed the hidden instance")
        doc = self.saveAndReopen()
        f = doc.getObject("F")
        self.assertFalse(f.Visibility, "a hidden instance came back shown")
        self.assertTrue(doc.getObject("G").Visibility, "a shown instance came back hidden")
        self.assertAt(f, self.freePlc, "the hidden instance after the reopen")

    def testHiddenInstanceCountsInTheBom(self):
        """B7: the hidden instance is listed; a part inserted twice is one row of quantity 2."""
        self.model()
        self.instance("G2", self.part1, App.Placement(V(0, -40, 0), App.Rotation()))
        self.f.Visibility = False
        self.doc.recompute()
        bom = UtilsAssembly.getBomGroup(self.asm).newObject("Assembly::BomObject", "BOM")
        bom.columnsNames = ["Index", "Name", "Quantity"]
        self.doc.recompute()
        rows = {}
        row = 2
        while bom.getContents(f"B{row}"):
            rows[bom.getContents(f"B{row}").lstrip("'")] = bom.getContents(f"C{row}").lstrip("'=")
            row += 1
        self.assertEqual(rows, {"Part 1": "2", "Part 2": "1", "Part 3": "1"}, rows)


if __name__ == "__main__":
    unittest.main()
