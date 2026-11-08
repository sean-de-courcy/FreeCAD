# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 round 7): Onshape's assemblies, App side.
#
# - Several assemblies per document (gap A13, ops#651): two root assemblies, a joint each, solve
#   independently, survive a save and a reopen, and one deleted leaves the other solving.
# Designed geometry: 10 mm cubes; a Fixed joint between the same face and vertex of two equal
# cubes makes their placements equal, so the expected placements are exact.

import os
import tempfile
import unittest

import FreeCAD as App

import JointObject

ASSEMBLY_PARAMETERS = "User parameter:BaseApp/Preferences/Mod/Assembly"


class AssembliesBase(unittest.TestCase):
    def setUp(self):
        self.docs = []
        self.files = []
        self.doc = self.newDocument(self.__class__.__name__)

    def tearDown(self):
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        for path in self.files:
            if os.path.exists(path):
                os.remove(path)

    def newDocument(self, name):
        doc = App.newDocument(name)
        self.docs.append(doc.Name)
        return doc

    def assembly(self, name, label=None, doc=None):
        doc = doc or self.doc
        asm = doc.addObject("Assembly::AssemblyObject", name)
        asm.Type = "Assembly"
        if label:
            asm.Label = label
        asm.newObject("Assembly::JointGroup", name + "Joints")
        return asm

    @staticmethod
    def jointGroup(asm):
        return [o for o in asm.Group if o.TypeId == "Assembly::JointGroup"][0]

    @staticmethod
    def cube(asm, name, placement, size=10):
        box = asm.newObject("Part::Box", name)
        box.Length = box.Width = box.Height = size
        box.Placement = placement
        return box

    def fixedJoint(self, asm, moving, staying, name, faces=("Face6", "Vertex7")):
        """A Fixed joint picked as the dialog does: moving first, staying second."""
        joint = self.jointGroup(asm).newObject("App::FeaturePython", name)
        JointObject.Joint(joint, 0)
        refs = [[moving, list(faces)], [staying, list(faces)]]
        joint.Proxy.setJointConnectors(joint, refs)
        return joint

    def assertPlacement(self, obj, plc, what):
        self.assertTrue(
            obj.Placement.isSame(plc, 1e-6), f"{what}: {obj.Label} at {obj.Placement}, not {plc}"
        )

    def saveAndReopen(self, doc):
        path = os.path.join(tempfile.gettempdir(), f"{doc.Name}_{os.getpid()}.FCStd")
        self.files.append(path)
        doc.saveAs(path)
        name = doc.Name
        App.closeDocument(name)
        reopened = App.openDocument(path)
        self.docs.append(reopened.Name)
        return reopened


class TestSeveralAssemblies(AssembliesBase):
    """Two root assemblies in one document (Onshape: any number of Assembly tabs)."""

    def model(self):
        self.first = self.assembly("Assembly", "Assembly 1")
        self.second = self.assembly("Assembly001", "Assembly 2")
        self.target1 = App.Placement(App.Vector(40, 0, 0), App.Rotation(0, 0, 30))
        self.target2 = App.Placement(App.Vector(0, 80, 5), App.Rotation(45, 0, 0))
        self.a1 = self.cube(self.first, "A1", App.Placement())
        self.b1 = self.cube(self.first, "B1", self.target1)
        self.a2 = self.cube(self.second, "A2", App.Placement(App.Vector(-30, 0, 0), App.Rotation()))
        self.b2 = self.cube(self.second, "B2", self.target2)
        self.doc.recompute()
        self.j1 = self.fixedJoint(self.first, self.a1, self.b1, "Fixed1")
        self.j2 = self.fixedJoint(self.second, self.a2, self.b2, "Fixed2")

    def testEachSolvesItsOwn(self):
        """Each assembly's joint moves its own first pick onto its second; the other assembly's
        parts don't move, and each solve reports only its own joints."""
        self.model()
        self.assertEqual(self.first.solve(), 0)
        self.assertEqual(self.second.solve(), 0)
        self.assertPlacement(self.a1, self.target1, "Assembly 1's joint")
        self.assertPlacement(self.a2, self.target2, "Assembly 2's joint")
        self.assertPlacement(self.b1, self.target1, "Assembly 1's second pick stays")
        self.assertPlacement(self.b2, self.target2, "Assembly 2's second pick stays")
        # A second joint in Assembly 2 is redundant there only
        self.fixedJoint(self.second, self.a2, self.b2, "Fixed2b")
        self.assertEqual(self.second.solve(), 0)
        self.assertEqual(self.first.solve(), 0)
        self.assertEqual(self.first.RedundantJoints, [])
        self.assertTrue(set(self.second.RedundantJoints) <= {"Fixed2", "Fixed2b"})
        self.assertTrue(self.second.RedundantJoints)

    def testSaveAndReopen(self):
        """Both assemblies, their joints and placements come back from the file and solve."""
        self.model()
        self.doc.recompute()
        doc = self.saveAndReopen(self.doc)
        first, second = doc.getObject("Assembly"), doc.getObject("Assembly001")
        self.assertEqual((first.Label, second.Label), ("Assembly 1", "Assembly 2"))
        a1, a2 = doc.getObject("A1"), doc.getObject("A2")
        a1.Placement = App.Placement(App.Vector(-100, 0, 0), App.Rotation())
        a2.Placement = App.Placement(App.Vector(0, -100, 0), App.Rotation())
        self.assertEqual(first.solve(), 0)
        self.assertEqual(second.solve(), 0)
        self.assertPlacement(a1, self.target1, "Assembly 1 after the reopen")
        self.assertPlacement(a2, self.target2, "Assembly 2 after the reopen")

    def testDeleteOne(self):
        """Deleting Assembly 1 with its contents leaves Assembly 2 whole and solving."""
        self.doc.UndoMode = 1
        self.model()
        self.doc.recompute()
        names = [o.Name for o in self.first.OutListRecursive] + [self.first.Name]
        self.doc.openTransaction("Delete Assembly 1")
        for name in names:
            if self.doc.getObject(name):
                self.doc.removeObject(name)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("Assembly"))
        self.assertIsNone(self.doc.getObject("Fixed1"))
        self.a2.Placement = App.Placement(App.Vector(0, -100, 0), App.Rotation())
        self.assertEqual(self.second.solve(), 0)
        self.assertPlacement(self.a2, self.target2, "Assembly 2 after Assembly 1 went")
        # Undo brings Assembly 1 back, and it solves again
        self.doc.undo()
        self.doc.recompute()
        first = self.doc.getObject("Assembly")
        self.assertIsNotNone(first)
        self.doc.getObject("A1").Placement = App.Placement()
        self.assertEqual(first.solve(), 0)
        self.assertPlacement(self.doc.getObject("A1"), self.target1, "Assembly 1 after the undo")


if __name__ == "__main__":
    unittest.main()
