# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""A joint's references keep their guess records when the assembly code rewrites them
(FreeCAD-CH, ops#504 E2): the swap of Reference1 and Reference2 during a solve (swapJCS) and
the re-rooting of a parent assembly's joints when an AssemblyLink turns rigid or flexible. On
designed models in documents with ReferenceSolver on, where redrawing a pad's profile makes the
joint's edge reference a tier 3 guess."""

import unittest

import FreeCAD as App

import JointObject
from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import Z, edge

ASSEMBLY_PARAMETERS = "User parameter:BaseApp/Preferences/Mod/Assembly"


class TestJointRecords(unittest.TestCase):
    def setUp(self):
        self.documents = []
        # The solves happen where the tests call them, not on every recompute.
        group = App.ParamGet(ASSEMBLY_PARAMETERS)
        if "SolveOnRecompute" in group.GetBools():
            self.addCleanup(group.SetBool, "SolveOnRecompute", group.GetBool("SolveOnRecompute"))
        else:
            self.addCleanup(group.RemBool, "SolveOnRecompute")
        group.SetBool("SolveOnRecompute", False)

    def tearDown(self):
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)

    def newDocument(self):
        doc = models.newDocument("JointRecords")
        doc.HistoryAlgorithm = "V2"
        doc.ReferenceSolver = True
        self.documents.append(doc.Name)
        return doc

    def padBody(self, doc, group):
        """A body in `group` with a pad of the rectangle 0..20 x 0..10, 10 high, from the sketch
        Profile. Returns the body."""
        body = models.body(doc)
        group.addObject(body)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10)
        return body

    def redraw(self, doc):
        """Deletes the profile's lines and draws the rectangle again from its right back corner,
        the other way round (TestNamingSolver.redraw): the same geometry, new geometry IDs, so
        the joint's edge is found again by geometry alone (tier 3)."""
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        doc.recompute()

    def records(self, joint):
        """The joint's reference report as (property, index, status, guess kind)."""
        return [
            (e["property"], e["index"], e["status"], e.get("guess_kind"))
            for e in App.getReferenceReport(joint)
        ]

    def distanceJoint(self, joints, reference1, reference2):
        """A Distance joint in `joints`, its references set without a solve."""
        joint = joints.newObject("App::FeaturePython", "Distance")
        JointObject.Joint(joint, JointObject.JointTypes.index("Distance"))
        joint.Reference1 = reference1
        joint.Reference2 = reference2
        return joint

    def testSwappedReferencesKeepTheirGuess(self):
        """A Distance joint from a cylinder's bottom circle (Reference1) to the pad's vertical
        edge at (20, 0) (Reference2). The redraw makes the edge reference a tier 3 guess. The
        solve puts the line first (swapJCS from getDistanceType): the edge reference moves to
        Reference1 and takes its guess record with it; the circle, now Reference2, has none."""
        # Arrange
        doc = self.newDocument()
        assembly = doc.addObject("Assembly::AssemblyObject", "Assembly")
        joints = assembly.newObject("Assembly::JointGroup", "Joints")
        body = self.padBody(doc, assembly)
        cylinder = assembly.newObject("Part::Cylinder", "Cylinder")
        cylinder.Radius, cylinder.Height = 2, 5
        cylinder.Placement.Base = App.Vector(40, 0, 0)
        doc.recompute()
        JointObject.GroundedJoint(joints.newObject("App::FeaturePython", "Grounded"), cylinder)
        circle = edge("circle", center=(40, 0, 0)).one(cylinder.Shape)
        corner = edge("line", direction=Z, through=(20, 0, 0))
        joint = self.distanceJoint(joints, [cylinder, circle], [body, corner.one(body.Shape)])
        doc.recompute()
        self.redraw(doc)
        #   the setup: the edge reference is a warned guess, and the circle is still first
        self.assertEqual(self.records(joint), [("Reference2", 0, "resolved", "tier3")])
        self.assertIn("Warning", joint.State)
        guessed = (body, corner.one(body.Shape))
        self.assertEqual(joint.Reference2, guessed)
        self.assertEqual(joint.Reference1, (cylinder, circle))

        # Act
        assembly.solve()

        # Assert
        #   the precondition: the solve swapped the references (it moves the body too, so the
        #   edge is compared by its name, not its place)
        self.assertEqual(joint.Reference1, guessed)
        self.assertEqual(joint.Reference2, (cylinder, circle))
        #   the guess went with the edge reference
        self.assertEqual(self.records(joint), [("Reference1", 0, "resolved", "tier3")])

        #   and a recompute keeps it
        doc.recompute()
        self.assertEqual(self.records(joint), [("Reference1", 0, "resolved", "tier3")])

    def subAssemblyJoint(self, rigid):
        """A parent assembly with a grounded box and an AssemblyLink (`rigid` or flexible) to a
        sub-assembly holding the pad body, and a Distance joint in the parent from the box's
        vertical edge at (40, 0) (Reference1) to the pad's vertical edge at (20, 0) through the
        AssemblyLink's link to the body (Reference2): rooted at the AssemblyLink when rigid, at
        the link when flexible, as the joint task makes them. Returns (document, AssemblyLink,
        the link to the body, the joint)."""
        doc = self.newDocument()
        subAssembly = doc.addObject("Assembly::AssemblyObject", "SubAssembly")
        subAssembly.newObject("Assembly::JointGroup", "SubJoints")
        body = self.padBody(doc, subAssembly)
        assembly = doc.addObject("Assembly::AssemblyObject", "Assembly")
        joints = assembly.newObject("Assembly::JointGroup", "Joints")
        box = assembly.newObject("Part::Box", "Box")
        box.Placement.Base = App.Vector(40, 0, 0)
        assemblyLink = assembly.newObject("Assembly::AssemblyLink", "SubLink")
        assemblyLink.LinkedObject = subAssembly
        doc.recompute()
        assemblyLink.Rigid = rigid
        doc.recompute()
        [link] = [o for o in assemblyLink.Group if o.isDerivedFrom("App::Link")]
        self.assertEqual(link.LinkedObject, body)
        JointObject.GroundedJoint(joints.newObject("App::FeaturePython", "Grounded"), box)
        [line] = edge("line", direction=Z, through=(20, 0, 0)).one(body.Shape)
        boxEdge = edge("line", direction=Z, through=(40, 0, 0)).one(box.Shape)
        if rigid:
            reference2 = [assemblyLink, [f"{link.Name}.{line}"]]
        else:
            reference2 = [link, [line]]
        joint = self.distanceJoint(joints, [box, boxEdge], reference2)
        doc.recompute()
        return doc, assemblyLink, link, joint

    def testRigidToggleKeepsTheGuess(self):
        """The joint's edge reference through the AssemblyLink, a tier 3 guess after the redraw.
        Turning the AssemblyLink flexible re-roots the reference from (AssemblyLink,
        "Link.EdgeN") to (Link, "EdgeN"), turning it rigid re-roots it back
        (AssemblyLink::updateParentJoints): either way the reference keeps its guess record."""
        for rigid in (True, False):
            with self.subTest(startsRigid=rigid):
                # Arrange
                doc, assemblyLink, link, joint = self.subAssemblyJoint(rigid)
                root = assemblyLink if rigid else link
                self.assertEqual(joint.Reference2[0], root)
                self.redraw(doc)
                #   the setup: the edge reference is a warned guess
                self.assertEqual(self.records(joint), [("Reference2", 0, "resolved", "tier3")])
                self.assertIn("Warning", joint.State)
                [sub] = joint.Reference2[1]

                # Act
                assemblyLink.Rigid = not rigid

                # Assert
                #   the precondition: the toggle re-rooted the reference
                if rigid:
                    self.assertEqual(joint.Reference2, (link, [sub.split(".", 1)[1]]))
                else:
                    self.assertEqual(joint.Reference2, (assemblyLink, [f"{link.Name}.{sub}"]))
                #   the guess stayed with it
                self.assertEqual(self.records(joint), [("Reference2", 0, "resolved", "tier3")])

                #   a recompute that changes nothing keeps it
                doc.recompute()
                self.assertEqual(self.records(joint), [("Reference2", 0, "resolved", "tier3")])
