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

import json
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
        tabs; an attached VarSetCopy can't be marked (a detached one can: ops#726, below)."""
        plain = self.doc.addObject("App::VarSet", "Variables")
        copy = self.doc.addObject("App::VarSetCopy", "Copy")
        copy.SourceKind = "Onshape JSON"
        names = [name for name, _kind in self.kinds()]
        self.assertNotIn(plain.Name, names)
        self.assertNotIn(copy.Name, names)
        self.assertFalse(Tabs.isVariableStudio(plain))
        with self.assertRaises(TypeError):
            Tabs.setVariableStudio(copy)
        Tabs.setVariableStudio(copy, False)  # unmarking takes any set
        Tabs.setVariableStudio(plain)
        self.assertIn(plain.Name, [name for name, _kind in self.kinds()])
        Tabs.setVariableStudio(plain, False)
        self.assertNotIn(plain.Name, [name for name, _kind in self.kinds()])

    def testDetachedCopyIsAVariableStudio(self):
        """ops#726 (replica stage 2, G8): an imported Onshape studio, once detached, can be a
        Variable Studio tab. Designed model: a studio export with w = 10 mm; a 10 x 10 mm square
        padded by #w is 1000 mm³. Attached, the copy is refused; undoing the Detach attaches it
        again and takes the tab away, the redo brings it back; the tab survives save and reopen."""
        import Part
        from freecad.variables import copies

        path = os.path.join(self.folder, "Studio.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"variableStudioReference": None, "variables": [
                {"type": "LENGTH", "name": "w", "value": None, "description": "the width",
                 "expression": "10 mm"}]}], f)
        copy = copies.import_studios(self.doc, [path]).copies[0]
        self.assertEqual(copy.TypeId, "App::VarSetCopy")
        with self.assertRaises(TypeError):
            Tabs.setVariableStudio(copy)  # attached: read-only, it follows its source
        self.assertFalse(Tabs.isVariableStudio(copy))

        copies.detach(copy)
        Tabs.setVariableStudio(copy)
        self.assertTrue(Tabs.isVariableStudio(copy))
        self.assertIn((copy.Name, "VariableStudio"), self.kinds())
        self.assertEqual(Tabs.tabOf(copy), copy.Name)

        body = self.doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        corners = [App.Vector(x, y, 0) for x, y in ((0, 0), (10, 0), (10, 10), (0, 10))]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.setExpression("Length", "#w")
        self.doc.recompute()
        self.assertAlmostEqual(copy.w.Value, 10, 9)
        self.assertAlmostEqual(pad.Shape.Volume, 1000, 6)

        # the Detach's undo: attached again, no tab; the redo: the tab again
        self.doc.undo()
        self.assertEqual(copy.SourceKind, "Onshape JSON")
        self.assertFalse(Tabs.isVariableStudio(copy))
        self.assertNotIn(copy.Name, [name for name, _kind in self.kinds()])
        self.doc.redo()
        self.assertEqual(copy.SourceKind, "None")
        self.assertTrue(Tabs.isVariableStudio(copy))

        saved = os.path.join(self.folder, "TestDocumentTabsDetached.FCStd")  # tearDown closes it
        self.doc.saveAs(saved)
        name = copy.Name
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(saved)
        copy = self.doc.getObject(name)
        self.assertEqual(copy.TypeId, "App::VarSetCopy")
        self.assertTrue(Tabs.isVariableStudio(copy))
        self.assertIn((name, "VariableStudio"), self.kinds())
        self.doc.getObject("Pad").touch()
        self.doc.recompute()
        self.assertAlmostEqual(self.doc.getObject("Pad").Shape.Volume, 1000, 6)

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
        """A stale name in the stored order is skipped, and not written (RT-5); a tab the order
        doesn't list comes last, in creation order; the listed ones keep their order."""
        self.model()
        Tabs.setOrder(self.doc, ["VarSet", "Gone", "Part", "*"])
        self.assertEqual(
            [name for name, _kind in self.kinds()], ["VarSet", "Part", "*", "Assembly", "Page"]
        )
        self.assertEqual(Tabs.order(self.doc), ["VarSet", "Part", "*"])

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

    # -- round 6 fixes (ops#640) -------------------------------------------------------------------

    def testImplicitStudioLabelIsUnique(self):
        """R6T-7: after Std_New's App::Part "Part Studio 1", solids an import (or a macro) puts at
        the top level are the implicit "Part Studio 2", not a second "Part Studio 1"."""
        part = self.doc.addObject("App::Part", "Part")
        part.Label = "Part Studio 1"
        self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        self.assertEqual(Tabs.label(self.doc, "*"), "Part Studio 2")
        labels = sorted(label for _name, _kind, label in Tabs.tabs(self.doc))
        self.assertEqual(labels, ["Part Studio 1", "Part Studio 2"])
        self.assertEqual(Tabs.nextLabel(self.doc, "Part Studio"), "Part Studio 3")

    def testNamedImplicitStudioStaysWhenEmptied(self):
        """R6T-12: an implicit studio whose label the registry holds (renamed, or shown in the GUI)
        stays a tab when its solids go, as Onshape keeps an empty Part Studio; deleting the tab
        forgets it."""
        self.model(assembly=False, page=False)
        Tabs.setImplicitLabel(self.doc, "Base")
        self.doc.removeObject("Box")
        self.doc.getObject("Body").removeObjectsFromDocument()
        self.doc.removeObject("Body")
        self.assertIsNone(self.doc.getObject("Body"))
        self.assertTrue(Tabs.hasImplicitStudio(self.doc))
        self.assertEqual(self.kinds()[0], ("*", "PartStudio"))
        self.assertEqual(Tabs.label(self.doc, "*"), "Base")
        Tabs.removeTab(self.doc, "*")
        self.assertFalse(Tabs.hasImplicitStudio(self.doc))
        self.assertNotIn("*", [name for name, _kind in self.kinds()])

    def testLinkArrayElementsAreNoImplicitContent(self):
        """R6T-9: a link array in Part Studio 2 doesn't make its elements top-level solids of the
        implicit studio."""
        studio = self.doc.addObject("App::Part", "Part")
        body = self.doc.addObject("PartDesign::Body", "Body")
        studio.addObject(body)
        box(self.doc, body)
        array = self.doc.addObject("App::Link", "Array")
        studio.addObject(array)
        array.LinkedObject = body
        array.ElementCount = 3
        array.ShowElement = True
        self.doc.recompute()
        self.assertEqual(len(array.ElementList), 3)
        self.assertFalse(Tabs.hasImplicitStudio(self.doc))
        self.assertEqual(self.kinds(), [("Part", "PartStudio")])


    # -- slice 2: Duplicate and Export (ops#640 round 8) -------------------------------------------

    def paddedStudio(self, label="Part Studio 2"):
        """An App::Part studio holding a Body with a 10 x 10 sketch padded 10 mm (1000 mm^3)."""
        import Part

        doc = self.doc
        studio = doc.addObject("App::Part", "Part")
        studio.Label = label
        body = doc.addObject("PartDesign::Body", "Body")
        studio.addObject(body)
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        corners = [App.Vector(x, y, 0) for x, y in ((0, 0), (10, 0), (10, 10), (0, 10))]
        for p, q in zip(corners, corners[1:] + corners[:1]):
            sketch.addGeometry(Part.LineSegment(p, q), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 10
        doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 1000, 6)
        return studio, body, pad

    def duplicateInTransaction(self, name):
        self.doc.openTransaction("Duplicate")
        copy = Tabs.duplicate(self.doc, name)
        self.doc.recompute()
        self.doc.commitTransaction()
        return self.doc.getObject(copy)

    def bodyOf(self, studio):
        bodies = [o for o in studio.Group if o.isDerivedFrom("PartDesign::Body")]
        self.assertEqual(len(bodies), 1, studio.Group)
        return bodies[0]

    def testDuplicatePartStudio(self):
        """Duplicate (design 6): a copy right of the original, "<name> (1)", not linked to it: the
        same volume; the original's pad 10 -> 15 leaves the copy at 1000 mm^3; one undo step
        removes the copy tab, the redo brings it back; a second copy is "(2)"."""
        studio, body, pad = self.paddedStudio()
        self.doc.addObject("TechDraw::DrawPage", "Page")
        self.assertEqual(Tabs.duplicateRefusal(self.doc, "Part"), "")
        self.assertEqual(Tabs.duplicateLabel(self.doc, "Part"), "Part Studio 2 (1)")
        copy = self.duplicateInTransaction("Part")
        self.assertEqual(copy.TypeId, "App::Part")
        self.assertEqual(copy.Label, "Part Studio 2 (1)")
        self.assertEqual([name for name, _kind in self.kinds()], ["Part", copy.Name, "Page"])
        copyBody = self.bodyOf(copy)
        self.assertNotEqual(copyBody, body)
        self.assertEqual(Tabs.tabOf(copyBody), copy.Name)
        for feature in copyBody.Group:
            self.assertEqual(Tabs.tabOf(feature), copy.Name)
            self.assertNotIn(feature, body.Group)
        self.assertAlmostEqual(copyBody.Shape.Volume, 1000, 6)
        self.assertNotEqual(copy.Origin, studio.Origin)

        pad.Length = 15
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 1500, 6)
        self.assertAlmostEqual(copyBody.Shape.Volume, 1000, 6)

        name = copy.Name
        self.doc.undo()
        self.assertNotIn(name, [n for n, _kind in self.kinds()])
        self.assertIsNone(self.doc.getObject(name))
        self.doc.redo()
        self.assertEqual([n for n, _kind in self.kinds()], ["Part", name, "Page"])
        second = self.duplicateInTransaction("Part")
        self.assertEqual(second.Label, "Part Studio 2 (2)")
        self.assertEqual([n for n, _kind in self.kinds()], ["Part", second.Name, name, "Page"])

    def testDuplicateSharesTheVariableStudio(self):
        """A studio whose pad length is a Variable Studio's variable duplicates; the copy uses the
        same variable (Onshape's variables are the document's), so a change moves both."""
        studio, body, pad = self.paddedStudio()
        variables = self.doc.addObject("App::VarSet", "VarSet")
        Tabs.setVariableStudio(variables)
        variables.addProperty("App::PropertyLength", "Depth")
        variables.Depth = 10
        pad.setExpression("Length", "VarSet.Depth")
        self.doc.recompute()
        copy = self.duplicateInTransaction("Part")
        copyPad = [o for o in self.bodyOf(copy).Group if o.isDerivedFrom("PartDesign::Pad")][0]
        self.assertEqual(dict(copyPad.ExpressionEngine)["Length"], "VarSet.Depth")
        variables.Depth = 15
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 1500, 6)
        self.assertAlmostEqual(self.bodyOf(copy).Shape.Volume, 1500, 6)

    def testDuplicateRefusals(self):
        """Not offered: the implicit studio (an older file's top level), a Drawing, a Variable
        Studio, and a Part Studio that uses an object outside it (here a link to the implicit
        studio's Body, as a Derived source would): the refusal names it, and duplicate() raises
        it, leaving the document as it was."""
        objects = self.model(assembly=False)
        self.assertIn("top level", Tabs.duplicateRefusal(self.doc, "*"))
        self.assertIn("Drawing", Tabs.duplicateRefusal(self.doc, "Page"))
        self.assertIn("Variable Studio", Tabs.duplicateRefusal(self.doc, "VarSet"))
        self.assertEqual(Tabs.duplicateRefusal(self.doc, "Part"), "")
        link = self.doc.addObject("App::Link", "Derived")
        objects["studio2"].addObject(link)
        link.LinkedObject = objects["body1"]
        self.doc.recompute()
        refusal = Tabs.duplicateRefusal(self.doc, "Part")
        self.assertIn("Body", refusal)
        self.assertIn("Part Studio 1", refusal)
        names = sorted(o.Name for o in self.doc.Objects)
        with self.assertRaises(RuntimeError):
            Tabs.duplicate(self.doc, "Part")
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)

    def testDuplicateAssembly(self):
        """An assembly duplicates with its links still pointing at the same studio's Body."""
        objects = self.model(page=False)
        link = objects["assembly"].newObject("App::Link", "Link")
        link.LinkedObject = objects["body2"]
        self.doc.recompute()
        self.assertEqual(Tabs.duplicateRefusal(self.doc, "Assembly"), "")
        copy = self.duplicateInTransaction("Assembly")
        self.assertEqual(copy.TypeId, "Assembly::AssemblyObject")
        self.assertEqual(copy.Label, "Assembly (1)")
        self.assertIsNone(copy.getParentGeoFeatureGroup())
        links = [o for o in copy.Group if o.isDerivedFrom("App::Link")]
        self.assertEqual(len(links), 1)
        self.assertNotEqual(links[0], link)
        self.assertEqual(links[0].LinkedObject, objects["body2"])
        self.assertEqual(Tabs.tabOf(links[0]), copy.Name)
        self.assertIn(copy.Name, [n for n, _kind in self.kinds()])
        self.assertAlmostEqual(links[0].Shape.Volume, math.pi * 25 * 20, 6)

    def testExportPartStudio(self):
        """Export writes a studio's visible parts to STEP (not its hidden Body or its sketches):
        re-read, the file's volume is the visible box's 1000 mm^3. An assembly exports its placed
        parts."""
        import Part

        studio, body, pad = self.paddedStudio()
        hidden = self.doc.addObject("PartDesign::Body", "Hidden")
        studio.addObject(hidden)
        cylinder(self.doc, hidden)
        self.doc.recompute()
        hidden.Visibility = False
        self.assertEqual(Tabs.exportObjects(self.doc, "Part"), [body])
        path = os.path.join(self.folder, "Part Studio 2.step")
        Tabs.exportTab(self.doc, "Part", path)
        self.assertTrue(os.path.exists(path))
        self.assertAlmostEqual(Part.read(path).Volume, 1000, 3)

        asm = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        link = asm.newObject("App::Link", "Link")
        link.LinkedObject = body
        link.Placement.Base = App.Vector(50, 0, 0)
        self.doc.recompute()
        self.assertEqual(Tabs.exportObjects(self.doc, "Assembly"), [asm])
        path = os.path.join(self.folder, "Assembly.step")
        Tabs.exportTab(self.doc, "Assembly", path)
        shape = Part.read(path)
        self.assertAlmostEqual(shape.Volume, 1000, 3)
        self.assertAlmostEqual(shape.BoundBox.XMin, 50, 3)

    def testExportRefusals(self):
        """A page and a Variable Studio don't export to STEP; a studio with nothing visible says
        so."""
        self.model(assembly=False)
        self.assertEqual(Tabs.exportObjects(self.doc, "Page"), [])
        with self.assertRaises(RuntimeError):
            Tabs.exportTab(self.doc, "Page", os.path.join(self.folder, "page.step"))
        self.doc.Body001.Visibility = False
        with self.assertRaises(RuntimeError) as raised:
            Tabs.exportTab(self.doc, "Part", os.path.join(self.folder, "empty.step"))
        self.assertIn("no visible part", str(raised.exception))


    # -- J1T A: a studio's Top, Front and Right stand for its Body's (ops#640 round 8) ------------

    def testStudioOriginPlaneStandsForTheBodys(self):
        """The studio's own origin planes map to the Body's own, by role, while the Body sits at
        the studio's origin; a Body placed apart, or another studio's plane, maps to nothing."""
        import PartDesign

        studio, body, pad = self.paddedStudio()
        sketch = body.Group[0]
        for role in ("XY_Plane", "XZ_Plane", "YZ_Plane", "Z_Axis"):
            theirs = [f for f in studio.Origin.OriginFeatures if f.Role == role][0]
            ours = [f for f in body.Origin.OriginFeatures if f.Role == role][0]
            self.assertEqual(PartDesign.studioOriginFeature(sketch, theirs), ours, role)
        own = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
        self.assertIsNone(PartDesign.studioOriginFeature(sketch, own))
        other = self.doc.addObject("App::Part", "Other")
        otherTop = [f for f in other.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
        self.assertIsNone(PartDesign.studioOriginFeature(sketch, otherTop))
        top = [f for f in studio.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
        body.Placement.Base = App.Vector(0, 0, 5)
        self.assertIsNone(PartDesign.studioOriginFeature(sketch, top))
