# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#800): an undo in an assembly in edit leaves a computed state, as Onshape's (oracle
# 25, UD1): delete a Fastened mate, one Undo brings it back solved at once, no Solve; delete a part
# instance, its mate goes with it; one Undo brings both back, solved.
# Designed geometry: "Base", a Part box 10 x 10 x 10 grounded at the origin; "Peg", an instance of
# the same box, Fixed top face onto top face (Vertex2 onto Vertex2) with the offset (20, 30, 0) in
# the base's top-face frame. The faces and vertices coincide but for the offset, which Offset2 applies
# to the base's frame, so the peg's frame sits at its inverse: the solved peg is at (-20, -30, 0), no
# rotation.

import FreeCAD as App
import FreeCADGui as Gui

import AssemblyPattern
import JointObject
from AssemblyTests.TestOnshapeAssembliesGui import AssembliesGuiBase, pump, tabsOn, waitFor

SOLVED = App.Placement(App.Vector(-20, -30, 0), App.Rotation())
STALE = ("Touched", "Invalid")


class TestUndoRegenerateGui(AssembliesGuiBase):
    def model(self):
        doc = self.newDocument("UndoRegenerateGui")
        box = doc.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 10
        asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        joints = asm.newObject("Assembly::JointGroup", "Joints")
        base = asm.newObject("App::Link", "Base")
        base.LinkedObject = box
        base.Label = AssemblyPattern.instanceLabel(asm, box)
        peg = asm.newObject("App::Link", "Peg")
        peg.LinkedObject = box
        peg.Label = AssemblyPattern.instanceLabel(asm, box)
        peg.Placement = App.Placement(App.Vector(-50, 40, 25), App.Rotation(10, 20, 30))
        doc.recompute()
        ground = joints.newObject("App::FeaturePython", "GroundedJoint")
        JointObject.GroundedJoint(ground, base)
        mate = joints.newObject("App::FeaturePython", "Fastened")
        JointObject.Joint(mate, 0)
        mate.Proxy.setJointConnectors(mate, [[peg, ["Face6", "Vertex2"]], [base, ["Face6", "Vertex2"]]])
        mate.Offset2 = App.Placement(App.Vector(20, 30, 0), App.Rotation())
        doc.recompute()
        pump(0.2)
        # The assembly in edit, as its tab or a double-click leaves it while the user works in it
        if tabsOn():
            done, refusal = Gui.DocumentTabs.switchTo(doc, asm.Name)
            self.assertTrue(done, refusal)
        else:
            Gui.getDocument(doc.Name).setEdit(asm)
        pump(0.4)
        self.assertIsNotNone(Gui.getDocument(doc.Name).getInEdit(), "the assembly in edit")
        doc.UndoMode = 1
        self.assertTrue(peg.Placement.isSame(SOLVED, 1e-6), f"solved peg at {peg.Placement}")
        return doc, asm, peg

    def assertComputed(self, doc, what):
        stale = [(o.Name, o.State) for o in doc.Objects if any(s in o.State for s in STALE)]
        self.assertEqual(stale, [], f"{what}: nothing is left to recompute")

    def step(self, doc, name, action):
        doc.openTransaction(name)
        action()
        doc.commitTransaction()
        pump(0.2)

    def testUndoDeletedMate(self):
        doc, asm, peg = self.model()
        self.step(doc, "Delete", lambda: doc.removeObject("Fastened"))
        self.assertIsNone(doc.getObject("Fastened"))
        self.assertTrue(peg.Placement.isSame(SOLVED, 1e-6), "the peg stays where the mate left it")
        # Off the solved place, as a drag leaves it (Onshape: the free part moves), one more step
        self.step(doc, "Move part", lambda: setattr(peg, "Placement", App.Placement(App.Vector(70, 0, 0), App.Rotation())))
        doc.undo()  # the move
        pump(0.2)
        doc.undo()  # the delete
        pump(0.2)
        mate = doc.getObject("Fastened")
        self.assertIsNotNone(mate, "the mate is back")
        self.assertComputed(doc, "after the undo")
        self.assertTrue(peg.Placement.isSame(SOLVED, 1e-6), f"peg at {peg.Placement}, solved at once")

    def testUndoDeletedInstance(self):
        doc, asm, peg = self.model()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, asm.Name, f"{peg.Name}.")
        Gui.runCommand("Std_Delete")
        self.assertTrue(waitFor(lambda: doc.getObject("Peg") is None), "the instance is deleted")
        self.assertIsNone(doc.getObject("Fastened"), "its mate goes with it, no confirmation")
        Gui.Selection.clearSelection()
        doc.undo()
        pump(0.3)
        peg = doc.getObject("Peg")
        self.assertIsNotNone(peg, "the instance is back")
        self.assertIsNotNone(doc.getObject("Fastened"), "its mate is back")
        self.assertComputed(doc, "after the undo")
        self.assertTrue(peg.Placement.isSame(SOLVED, 1e-6), f"peg at {peg.Placement}")
