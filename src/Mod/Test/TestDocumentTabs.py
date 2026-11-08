# SPDX-License-Identifier: LGPL-2.1-or-later
# ****************************************************************************
# *                                                                          *
# *   This file is part of FreeCAD.                                          *
# *                                                                          *
# *   FreeCAD is free software: you can redistribute it and/or modify it     *
# *   under the terms of the GNU Lesser General Public License as            *
# *   published by the Free Software Foundation, either version 2.1 of the   *
# *   License, or (at your option) any later version.                        *
# *                                                                          *
# *   FreeCAD is distributed in the hope that it will be useful, but         *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
# *   Lesser General Public License for more details.                        *
# *                                                                          *
# *   You should have received a copy of the GNU Lesser General Public       *
# *   License along with FreeCAD. If not, see                                *
# *   <https://www.gnu.org/licenses/>.                                       *
# *                                                                          *
# ***************************************************************************/

"""Onshape's typed tabs, the registry (FreeCAD-CH, ops#640 rank 59, App/DocumentTabs.cpp).

notes/onshape-tabs-design.md section 6, App tests. A tab is an object the document already has: a
top-level App::Part (a Part Studio), the top level itself (the implicit "Part Studio 1"), a root
assembly, a page, a VarSet marked as a Variable Studio. The registry is one key of the document's
Meta map: the order, the marks and the implicit studio's label; a stale or missing key loses no tab.

Designed model: Part Studio 1 (the top level) a Body with a 10 x 10 x 10 mm box at the origin; Part
Studio 2 (an App::Part) a Body with a cylinder r 5, h 20 on the origin; an assembly; a page; a marked
VarSet.
"""

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App

Tabs = App.DocumentTabs


def box(doc, body):
    feature = body.newObject("PartDesign::AdditiveBox", "Box")
    feature.Length = feature.Width = feature.Height = 10
    return feature


def cylinder(doc, body):
    feature = body.newObject("PartDesign::AdditiveCylinder", "Cylinder")
    feature.Radius = 5
    feature.Height = 20
    return feature


class TestDocumentTabs(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="TestDocumentTabs")
        self.doc = App.newDocument("TestDocumentTabs")
        self.doc.UndoMode = 1

    def tearDown(self):
        for name in list(App.listDocuments()):
            if name.startswith("TestDocumentTabs"):
                App.closeDocument(name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def model(self, assembly=True, page=True):
        """The designed model; returns its objects by role."""
        doc = self.doc
        body1 = doc.addObject("PartDesign::Body", "Body")
        box(doc, body1)
        studio2 = doc.addObject("App::Part", "Part")
        studio2.Label = "Part Studio 2"
        body2 = doc.addObject("PartDesign::Body", "Body001")
        studio2.addObject(body2)
        cylinder(doc, body2)
        objects = {"body1": body1, "studio2": studio2, "body2": body2}
        if assembly:
            asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
            asm.Type = "Assembly"
            asm.newObject("Assembly::JointGroup", "Joints")
            objects["assembly"] = asm
        if page:
            objects["page"] = doc.addObject("TechDraw::DrawPage", "Page")
        variables = doc.addObject("App::VarSet", "VarSet")
        variables.Label = "Variable Studio 1"
        Tabs.setVariableStudio(variables)
        objects["variables"] = variables
        doc.recompute()
        return objects

    def kinds(self):
        return [(name, kind) for name, kind, _label in Tabs.tabs(self.doc)]

    # -- kinds, labels, order --------------------------------------------------------------------

    def testKindsLabelsAndOrder(self):
        """The model's tabs: the implicit studio first, then the tab objects in creation order,
        each with its kind; the labels are the objects' Labels and "Part Studio 1"."""
        objects = self.model()
        self.assertEqual(
            self.kinds(),
            [
                ("*", "PartStudio"),
                ("Part", "PartStudio"),
                ("Assembly", "Assembly"),
                ("Page", "Drawing"),
                ("VarSet", "VariableStudio"),
            ],
        )
        labels = [label for _name, _kind, label in Tabs.tabs(self.doc)]
        self.assertEqual(labels[:2], ["Part Studio 1", "Part Studio 2"])
        self.assertEqual(labels[4], "Variable Studio 1")
        self.assertAlmostEqual(objects["body1"].Shape.Volume, 1000, 6)
        self.assertAlmostEqual(objects["body2"].Shape.Volume, math.pi * 25 * 20, 6)

    def testTabOf(self):
        """Each object belongs to its tab: the box to the implicit studio, the cylinder (in Part
        Studio 2's Body) to Part Studio 2, a joint group to its assembly."""
        objects = self.model()
        self.assertEqual(Tabs.tabOf(objects["body1"]), "*")
        self.assertEqual(Tabs.tabOf(objects["body1"].Group[0]), "*")
        self.assertEqual(Tabs.tabOf(objects["body2"].Group[0]), "Part")
        self.assertEqual(Tabs.tabOf(objects["studio2"]), "Part")
        self.assertEqual(Tabs.tabOf(objects["assembly"].Group[0]), "Assembly")
        self.assertEqual(Tabs.tabOf(objects["page"]), "Page")

    def testNestedPartIsNoTab(self):
        """An App::Part inside Part Studio 2 is part of that studio, not a tab of its own; nor is an
        assembly inside an assembly."""
        objects = self.model(page=False)
        inner = self.doc.addObject("App::Part", "Inner")
        objects["studio2"].addObject(inner)
        nested = objects["assembly"].newObject("Assembly::AssemblyObject", "SubAssembly")
        names = [name for name, _kind in self.kinds()]
        self.assertNotIn("Inner", names)
        self.assertNotIn("SubAssembly", names)
        self.assertEqual(Tabs.tabOf(inner), "Part")
        self.assertEqual(Tabs.tabOf(nested), "Assembly")

    def testUnmarkedVarSetAndCopyAreNoTabs(self):
        """A VarSet the Variable tool makes (unmarked) and a VarSetCopy are variable sets, not
        tabs; a VarSetCopy can't be marked."""
        plain = self.doc.addObject("App::VarSet", "Variables")
        copy = self.doc.addObject("App::VarSetCopy", "Copy")
        names = [name for name, _kind in self.kinds()]
        self.assertNotIn(plain.Name, names)
        self.assertNotIn(copy.Name, names)
        self.assertFalse(Tabs.isVariableStudio(plain))
        with self.assertRaises(TypeError):
            Tabs.setVariableStudio(copy)
        Tabs.setVariableStudio(plain)
        self.assertIn(plain.Name, [name for name, _kind in self.kinds()])
        Tabs.setVariableStudio(plain, False)
        self.assertNotIn(plain.Name, [name for name, _kind in self.kinds()])

    def testImplicitStudio(self):
        """An empty document is one implicit studio; a document whose top level holds no solid but
        has an App::Part studio has none; a top-level Body brings it back."""
        self.assertEqual(self.kinds(), [("*", "PartStudio")])
        part = self.doc.addObject("App::Part", "Part")
        self.assertEqual(self.kinds(), [("Part", "PartStudio")])
        self.doc.addObject("PartDesign::Body", "Body")
        self.assertEqual(self.kinds(), [("*", "PartStudio"), ("Part", "PartStudio")])
        self.assertTrue(Tabs.hasImplicitStudio(self.doc))
        part.addObject(self.doc.Body)
        self.assertFalse(Tabs.hasImplicitStudio(self.doc))

    def testStaleAndUnlistedNames(self):
        """A stale name in the stored order is skipped; a tab the order doesn't list comes last,
        in creation order; the listed ones keep their order."""
        self.model()
        Tabs.setOrder(self.doc, ["VarSet", "Gone", "Part", "*"])
        self.assertEqual(
            [name for name, _kind in self.kinds()], ["VarSet", "Part", "*", "Assembly", "Page"]
        )
        self.assertEqual(Tabs.order(self.doc), ["VarSet", "Gone", "Part", "*"])

    def testPlaceAfter(self):
        """A new tab goes right of the active one."""
        self.model(assembly=False, page=False)
        studio3 = self.doc.addObject("App::Part", "Part001")
        Tabs.placeAfter(self.doc, studio3.Name, "*")
        self.assertEqual(
            [name for name, _kind in self.kinds()], ["*", "Part001", "Part", "VarSet"]
        )

    def testOrderSurvivesSaveAndReopen(self):
        """The order, the marks and the implicit studio's label survive a save and a reopen."""
        self.model()
        Tabs.setOrder(self.doc, ["Page", "*", "Assembly", "Part", "VarSet"])
        Tabs.setImplicitLabel(self.doc, "Main studio")
        path = os.path.join(self.folder, "tabs.FCStd")
        self.doc.saveAs(path)
        expected = Tabs.tabs(self.doc)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.assertEqual(Tabs.tabs(self.doc), expected)
        self.assertEqual(Tabs.label(self.doc, "*"), "Main studio")
        self.assertTrue(Tabs.isVariableStudio(self.doc.VarSet))

    def testMetaClearedKeepsEveryTab(self):
        """With the registry's key gone (an older build's file, or cleared) every tab is still
        there, in creation order; only the marks of Variable Studios go with it."""
        self.model()
        meta = self.doc.Meta
        meta.pop(Tabs.metaKey(), None)
        self.doc.Meta = meta
        self.assertEqual(
            [name for name, _kind in self.kinds()], ["*", "Part", "Assembly", "Page"]
        )

    def testFileWithoutTabsOpensAsTabs(self):
        """A file saved without the registry (every file to date) opens as tabs with no
        conversion: its top-level Bodies are the implicit "Part Studio 1", its assembly and page
        tabs; nothing is moved and the file isn't marked modified by the reading."""
        self.model()
        meta = self.doc.Meta
        meta.pop(Tabs.metaKey(), None)
        self.doc.Meta = meta
        path = os.path.join(self.folder, "plain.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.assertEqual(
            self.kinds(),
            [("*", "PartStudio"), ("Part", "PartStudio"), ("Assembly", "Assembly"), ("Page", "Drawing")],
        )
        self.assertEqual(Tabs.label(self.doc, "*"), "Part Studio 1")
        self.assertNotIn(Tabs.metaKey(), self.doc.Meta)
        self.assertEqual(self.doc.Body.getParentGeoFeatureGroup(), None)
        self.assertFalse(self.doc.isTouched())

    def testUndoRedoCreatePartStudio(self):
        """Undo of "Create Part Studio" removes the tab; redo puts it back in its place (the order
        isn't part of the undo history)."""
        self.model(assembly=False, page=False)
        self.doc.openTransaction("Create Part Studio")
        studio3 = self.doc.addObject("App::Part", "Part001")
        studio3.Label = Tabs.nextLabel(self.doc, "Part Studio")
        Tabs.placeAfter(self.doc, studio3.Name, "*")
        self.doc.commitTransaction()
        self.assertEqual(studio3.Label, "Part Studio 3")
        order = [name for name, _kind in self.kinds()]
        self.assertEqual(order, ["*", "Part001", "Part", "VarSet"])
        self.doc.undo()
        self.assertEqual([name for name, _kind in self.kinds()], ["*", "Part", "VarSet"])
        self.doc.redo()
        self.assertEqual([name for name, _kind in self.kinds()], order)
        self.assertEqual(Tabs.label(self.doc, "Part001"), "Part Studio 3")

    def testRenameIsUndoable(self):
        """A tab's name is its object's Label: a rename is an undo step."""
        objects = self.model(assembly=False, page=False)
        self.doc.openTransaction("Rename tab")
        objects["studio2"].Label = "Bracket"
        self.doc.commitTransaction()
        self.assertEqual(Tabs.label(self.doc, "Part"), "Bracket")
        self.doc.undo()
        self.assertEqual(Tabs.label(self.doc, "Part"), "Part Studio 2")

    def testNextLabel(self):
        """The lowest free "Part Studio N" among the tab names."""
        self.model(assembly=False, page=False)
        self.assertEqual(Tabs.nextLabel(self.doc, "Part Studio"), "Part Studio 3")
        self.doc.Part.Label = "Bracket"
        self.assertEqual(Tabs.nextLabel(self.doc, "Part Studio"), "Part Studio 2")
        self.assertEqual(Tabs.nextLabel(self.doc, "Variable Studio"), "Variable Studio 2")

    def testDependentsAndRemove(self):
        """Part Studio 2's Body linked into the assembly: deleting Part Studio 2 lists the link as
        what it would break; the delete removes the studio, its Body and its features in one undo
        step, and the undo brings them back with the cylinder's volume."""
        objects = self.model(page=False)
        link = objects["assembly"].newObject("App::Link", "Link")
        link.LinkedObject = objects["body2"]
        self.doc.recompute()
        users = Tabs.dependents(self.doc, "Part")
        self.assertIn(link, users)
        members = Tabs.members(self.doc, "Part")
        for obj in (objects["studio2"], objects["body2"], objects["body2"].Group[0]):
            self.assertIn(obj, members)
        self.assertNotIn(objects["body1"], members)
        self.assertEqual(Tabs.dependents(self.doc, "*"), [])

        self.doc.openTransaction("Delete Part Studio 2")
        Tabs.removeTab(self.doc, "Part")
        self.doc.commitTransaction()
        self.assertIsNone(self.doc.getObject("Part"))
        self.assertIsNone(self.doc.getObject("Body001"))
        self.assertIsNone(self.doc.getObject("Cylinder"))
        self.assertNotIn("Part", [name for name, _kind in self.kinds()])
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNotNone(self.doc.getObject("Part"))
        self.assertAlmostEqual(self.doc.Body001.Shape.Volume, math.pi * 25 * 20, 6)
        self.assertIn("Part", [name for name, _kind in self.kinds()])

    def testRemoveImplicitStudio(self):
        """Deleting the implicit studio removes the top level's solids, not the other tabs."""
        objects = self.model(assembly=False, page=False)
        Tabs.removeTab(self.doc, "*")
        self.assertIsNone(self.doc.getObject("Body"))
        self.assertIsNone(self.doc.getObject("Box"))
        self.assertIsNotNone(self.doc.getObject("Part"))
        self.assertEqual([name for name, _kind in self.kinds()], ["Part", "VarSet"])
