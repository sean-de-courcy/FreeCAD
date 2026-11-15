# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#787): a grounded part stays grounded through undo and redo.
#
# Onshape restores an undone delete's part fixed, as it was. Here a grounded part is the one whose
# Placement is ReadOnly; undoing its deletion restored its AttachmentSupport after the grounded
# joint's ObjectToGround, and the attacher then made the Placement editable: the part read as not
# grounded, and the next solve removed its grounded joint. Designed geometry: two 10 mm cubes.

import unittest

import FreeCAD as App

import JointObject

from AssemblyTests.TestCore import AssemblyTestBase


def readOnly(obj):
    return "ReadOnly" in obj.getPropertyStatus("Placement")


class TestGroundedUndo(AssemblyTestBase):
    def setUp(self):
        super().setUp()
        self.assembly.Type = "Assembly"
        self.doc.UndoMode = 1
        self.a = self.cube("A", 0.0)
        self.b = self.cube("B", 20.0)
        self.grounded = self.jointgroup.newObject("App::FeaturePython", "GroundedA")
        JointObject.GroundedJoint(self.grounded, self.a)
        self.doc.recompute()
        self.assembly.solve()

    def cube(self, name, x):
        box = self.assembly.newObject("Part::Box", name)
        box.Length = box.Width = box.Height = 10
        box.Placement.Base.x = x
        return box

    def assertGrounded(self, part, when):
        self.assertTrue(readOnly(part), when + ": Placement not ReadOnly")
        self.assertTrue(self.assembly.isPartGrounded(part), when + ": not grounded")

    def testDeleteUndoKeepsThePartGrounded(self):
        self.assertGrounded(self.a, "before")
        self.doc.openTransaction("Delete A")
        self.doc.removeObject("A")
        self.doc.commitTransaction()
        self.assertFalse(self.assembly.isPartGrounded(self.b))
        self.doc.undo()
        self.assertIs(self.grounded.ObjectToGround, self.a)
        self.assertGrounded(self.a, "after the undo")
        self.assembly.solve()
        self.assertGrounded(self.a, "after a solve")
        # the solve keeps the grounded joint (it removes a joint whose part isn't ReadOnly)
        self.assertIsNotNone(self.doc.getObject("GroundedA"))
        self.assertFalse(self.assembly.isPartGrounded(self.b))
        # redo deletes A again; a second undo brings it back grounded
        self.doc.redo()
        self.assertIsNone(self.doc.getObject("A"))
        self.doc.undo()
        self.assertGrounded(self.a, "after a second undo")

    def testUndoOfAnAttachmentChangeKeepsThePartGrounded(self):
        # an attachment change on a grounded part, undone: grounded as before
        self.doc.openTransaction("Attach")
        self.a.AttachmentOffset = App.Placement(App.Vector(1, 0, 0), App.Rotation())
        self.doc.commitTransaction()
        self.doc.undo()
        self.assertGrounded(self.a, "after the undo")

    def testUngroundingIsUndoneToo(self):
        # deleting the grounded joint ungrounds A; its undo grounds A again
        self.doc.openTransaction("Unground")
        self.doc.removeObject("GroundedA")
        self.doc.commitTransaction()
        self.assertFalse(readOnly(self.a))
        self.doc.undo()
        self.assertGrounded(self.a, "after the undo")
        self.doc.redo()
        self.assertFalse(readOnly(self.a))
        self.assertFalse(self.assembly.isPartGrounded(self.a))


if __name__ == "__main__":
    unittest.main()
