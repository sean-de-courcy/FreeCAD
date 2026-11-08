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
# ***************************************************************************/

"""Onshape's typed tabs in the GUI (FreeCAD-CH, ops#640 rank 59, Gui/DocumentTabBar.cpp).

notes/onshape-tabs-design.md section 6, GUI tests, slice 1. Under the Onshape keymap each Part
Studio and Assembly tab is its own 3D view showing only the tab's objects; a bar along the bottom
lists the tabs, with "+" and Rename/Delete; a strip on top lists the documents; the toolbar follows
the tab; an undo or redo of a step made in another tab switches to that tab first. The Modes toolbar
(rank 58) is gone.

Designed model: Part Studio 1 (the top level) a Body with a 10 x 10 sketch padded 10 (a 10 mm box at
the origin, 1000 mm^3); Part Studio 2 (an App::Part) a Body with a cylinder r 5, h 20 on the origin,
overlapping the box; one assembly.
"""

import math
import os
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtWidgets

Tabs = App.DocumentTabs
GuiTabs = Gui.DocumentTabs
V = App.Vector


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def techDrawTemplateReadable():
    """Whether TechDraw_PageDefault finds a template: without one it shows a modal message box."""
    default = os.path.join(
        App.getResourceDir(), "Mod", "TechDraw", "Templates", "Default_Template_A4_Landscape.svg"
    )
    files = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Files")
    chosen = files.GetString("TemplateFile", default) or default
    return os.access(chosen, os.R_OK) or os.access(default, os.R_OK)


def rectangle(x0, y0, x1, y1):
    points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    return [Part.LineSegment(p, q) for p, q in zip(points, points[1:] + points[:1])]


def undo():
    """Ctrl+Z: Std_Undo, through the active view (Gui::Document::undo)."""
    Gui.runCommand("Std_Undo")
    pump(0.2)


def redo():
    Gui.runCommand("Std_Redo")
    pump(0.2)


def shown(view):
    """The names of the active document's objects whose view providers' root nodes are in the
    view's scene, at any depth."""
    from pivy import coin

    scene = view.getSceneGraph()
    names = set()
    for obj in App.ActiveDocument.Objects:
        root = obj.ViewObject.RootNode if obj.ViewObject is not None else None
        if root is None:
            continue
        search = coin.SoSearchAction()
        search.setNode(root)
        search.setSearchingAll(True)
        search.apply(scene)
        if search.getPath() is not None:
            names.add(obj.Name)
    return names


class TestDocumentTabsGui(unittest.TestCase):
    def setUp(self):
        if not GuiTabs.isOn():
            self.skipTest("the typed tabs are on under the Onshape keymap only")
        self.startWorkbench = Gui.activeWorkbench().name()
        self.docs = []
        self.doc = self.newDocument("TestDocumentTabsGui")

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        for name in self.docs:
            gdoc = Gui.getDocument(name) if name in App.listDocuments() else None
            if gdoc and gdoc.getInEdit():
                gdoc.resetEdit()
        pump(0.1)
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        Gui.activateWorkbench(self.startWorkbench)
        pump(0.1)

    def newDocument(self, name):
        doc = App.newDocument(name)
        self.docs.append(doc.Name)
        pump(0.1)
        return doc

    def model(self, assembly=True):
        doc = self.doc
        body1 = doc.addObject("PartDesign::Body", "Body")
        profile = doc.addObject("Sketcher::SketchObject", "Profile")
        body1.addObject(profile)
        profile.addGeometry(rectangle(0, 0, 10, 10), False)
        pad = body1.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Length = 10
        studio2 = doc.addObject("App::Part", "Part")
        studio2.Label = "Part Studio 2"
        body2 = doc.addObject("PartDesign::Body", "Body001")
        studio2.addObject(body2)
        cylinder = body2.newObject("PartDesign::AdditiveCylinder", "Cylinder")
        cylinder.Radius = 5
        cylinder.Height = 20
        objects = {"body1": body1, "pad": pad, "studio2": studio2, "body2": body2, "cylinder": cylinder}
        if assembly:
            asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
            asm.Type = "Assembly"
            asm.newObject("Assembly::JointGroup", "Joints")
            objects["assembly"] = asm
        doc.recompute()
        profile.ViewObject.Visibility = False
        GuiTabs.reconcile(doc)
        pump(0.2)
        self.assertAlmostEqual(body1.Shape.Volume, 1000, 6)
        return objects

    def switch(self, name):
        done, refusal = GuiTabs.switchTo(self.doc, name)
        self.assertTrue(done, refusal)
        pump(0.2)
        view = GuiTabs.viewOf(self.doc, name)
        self.assertIsNotNone(view, name)
        self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), name)
        return view

    # -- one view per tab, filtered --------------------------------------------------------------

    def testEachTabShowsOnlyItsObjects(self):
        """Part Studio 1's view shows its Body and Pad, not Part Studio 2 or the assembly; Part
        Studio 2's its App::Part with the cylinder's Body, not the Pad; the assembly's its
        assembly only. Part Studio 2's Body linked into the assembly (a link of pi * 25 * 20
        mm^3) is shown in the assembly's view, and the studios' views are unchanged by it. (Off
        screen the pick is unreliable, so the views' scenes are searched instead of a pick.)"""
        objects = self.model()
        studio1 = {"Body", "Pad"}
        studio2 = {"Part", "Body001", "Cylinder"}
        assembly = {"Assembly", "Joints"}

        def check(view, inside, outside):
            names = shown(view)
            self.assertTrue(inside <= names, (inside, names))
            self.assertFalse(outside & names, (outside, names))

        check(self.switch("*"), studio1, studio2 | assembly)
        check(self.switch("Part"), studio2, studio1 | assembly)
        view = self.switch("Assembly")
        check(view, assembly, studio1 | {"Part"})
        link = objects["assembly"].newObject("App::Link", "Link")
        link.LinkedObject = objects["body2"]
        self.doc.recompute()
        pump(0.2)
        self.assertAlmostEqual(link.Shape.Volume, math.pi * 25 * 20, 6)
        check(view, assembly | {"Link"}, studio1 | {"Part"})
        check(self.switch("*"), studio1, studio2 | assembly | {"Link"})
        check(self.switch("Part"), studio2, studio1 | assembly | {"Link"})
        # Switching touched no Visibility
        self.assertTrue(objects["body1"].Visibility)
        self.assertTrue(objects["studio2"].Visibility)

    def testANewTopLevelBodyGoesToTheImplicitStudio(self):
        """A Body made at the top level while Part Studio 2's view is active isn't added to that
        view; it is in Part Studio 1's."""
        self.model(assembly=False)
        view2 = self.switch("Part")
        body = self.doc.addObject("PartDesign::Body", "Body002")
        pump(0.2)
        self.assertNotIn(body.Name, shown(view2))
        self.assertIn(body.Name, shown(self.switch("*")))

    def testNewBodyLandsInTheTabsStudio(self):
        """A Body made in Part Studio 2's tab is in that App::Part; a 10 mm pad on a 10 x 10 sketch
        in it is 1000 mm^3."""
        objects = self.model(assembly=False)
        self.switch("Part")
        before = {o.Name for o in self.doc.Objects}
        Gui.runCommand("PartDesign_Body")
        pump(0.3)
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump(0.2)
        bodies = [
            o for o in self.doc.Objects if o.Name not in before and o.isDerivedFrom("PartDesign::Body")
        ]
        self.assertEqual(len(bodies), 1)
        body = bodies[0]
        self.assertEqual(body.getParentGeoFeatureGroup(), objects["studio2"])
        sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        body.addObject(sketch)
        sketch.addGeometry(rectangle(20, 0, 30, 10), False)
        pad = body.newObject("PartDesign::Pad", "Pad001")
        pad.Profile = sketch
        pad.Length = 10
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 1000, 6)
        self.assertEqual(Tabs.tabOf(pad), "Part")

    # -- switching ---------------------------------------------------------------------------------

    def testSwitchingFollowsTheKind(self):
        """A Part Studio tab is Part Design's, an assembly tab the Assembly workbench's with the
        assembly in edit while its tab is active; leaving it ends the edit. The selection is empty
        after a switch."""
        objects = self.model()
        self.switch("*")
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        Gui.Selection.addSelection(self.doc.Name, objects["body1"].Name)
        self.switch("Assembly")
        self.assertEqual(Gui.activeWorkbench().name(), "AssemblyWorkbench")
        self.assertEqual(Gui.Selection.getSelection(), [])
        import UtilsAssembly

        self.assertIsNotNone(Gui.ActiveDocument.getInEdit())
        self.assertEqual(UtilsAssembly.activeAssembly(), objects["assembly"])
        self.switch("Part")
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        self.assertIsNone(Gui.ActiveDocument.getInEdit())
        self.assertEqual(GuiTabs.activeTab(self.doc), "Part")

    def testSwitchRefusedWithADialogOpen(self):
        """With the Pad's dialog open in Part Studio 1 the switch to Part Studio 2 is refused, as
        Onshape asks to finish the feature first."""
        objects = self.model(assembly=False)
        self.switch("*")
        Gui.ActiveDocument.setEdit(objects["pad"].Name)
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog())
        done, refusal = GuiTabs.switchTo(self.doc, "Part")
        self.assertFalse(done)
        self.assertIn("Finish or cancel", refusal)
        self.assertEqual(GuiTabs.activeTab(self.doc), "*")
        Gui.ActiveDocument.resetEdit()
        pump(0.2)

    def testEditOpensTheObjectsTab(self):
        """Editing an object of another tab (the cylinder, from Part Studio 1's tab) opens that
        tab's view for the edit."""
        objects = self.model(assembly=False)
        self.switch("*")
        Gui.ActiveDocument.setEdit(objects["cylinder"].Name)
        pump(0.3)
        self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "Part")
        self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
        Gui.ActiveDocument.resetEdit()
        pump(0.2)

    # -- undo: one history, the step's tab shown first ---------------------------------------------

    def testUndoAndRedoSwitchToTheStepsTab(self):
        """A step made in Part Studio 2 (the cylinder's height 20 -> 30), undone from Part Studio
        1's tab, switches to Part Studio 2 first; its redo from Part Studio 1 too. A step of the
        active tab undoes in place."""
        objects = self.model(assembly=False)
        cylinder = objects["cylinder"]
        self.switch("Part")
        Gui.ActiveDocument.openCommand("Cylinder height")
        cylinder.Height = 30
        Gui.ActiveDocument.commitCommand()
        self.doc.recompute()
        self.switch("*")
        Gui.ActiveDocument.openCommand("Pad length")
        objects["pad"].Length = 12
        Gui.ActiveDocument.commitCommand()
        self.doc.recompute()

        undo()  # the pad's step, made here
        pump(0.2)
        self.assertEqual(GuiTabs.activeTab(self.doc), "*")
        self.assertAlmostEqual(objects["pad"].Length.Value, 10, 6)
        undo()  # the cylinder's, made in Part Studio 2
        pump(0.2)
        self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
        self.assertAlmostEqual(cylinder.Height.Value, 20, 6)
        self.switch("*")
        redo()
        pump(0.2)
        self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
        self.assertAlmostEqual(cylinder.Height.Value, 30, 6)

    # -- the bar: "+", Rename, Delete ----------------------------------------------------------------

    def barTexts(self):
        bar = Gui.getMainWindow().findChild(QtWidgets.QTabBar, "FreeCADCH_TypedTabBar")
        self.assertIsNotNone(bar)
        return [bar.tabText(i) for i in range(bar.count())]

    def testTheBarsAndTheMdiTabs(self):
        """The bottom bar lists the active document's tabs by name; the strip on top lists the
        documents; the MDI area's own tab bar takes no room; the Modes toolbar is gone."""
        self.model()
        pump(0.2)
        self.assertEqual(self.barTexts(), ["Part Studio 1", "Part Studio 2", "Assembly"])
        mw = Gui.getMainWindow()
        strip = mw.findChild(QtWidgets.QTabBar, "FreeCADCH_DocumentTabBar")
        self.assertIsNotNone(strip)
        self.assertIn(self.doc.Label, [strip.tabText(i) for i in range(strip.count())])
        self.assertTrue(mw.findChild(QtWidgets.QToolBar, "FreeCADCH_TypedTabs").isVisible())
        mdi = mw.findChild(QtWidgets.QMdiArea)
        mdiTabs = mdi.findChild(QtWidgets.QTabBar, "mdiAreaTabBar")
        self.assertFalse(mdiTabs.isVisible())
        self.assertEqual(mdiTabs.sizeHint().height(), 0)  # QMdiArea sizes its viewport by it
        self.assertIsNone(mw.findChild(QtWidgets.QToolBar, "FreeCADCH_Modes"))

    def testCreatePartStudioAndUndo(self):
        """"+" > Create Part Studio: an App::Part "Part Studio 3" right of the active tab, made
        active; its undo removes it, in one step."""
        self.model(assembly=False)
        self.switch("*")
        name = GuiTabs.create(self.doc, "PartStudio")
        pump(0.2)
        self.assertEqual(self.doc.getObject(name).Label, "Part Studio 3")
        self.assertEqual(GuiTabs.activeTab(self.doc), name)
        self.assertEqual([n for n, _k, _l in Tabs.tabs(self.doc)], ["*", name, "Part"])
        undo()
        pump(0.2)
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(self.barTexts(), ["Part Studio 1", "Part Studio 2"])

    def testCreateAssemblyAndVariableStudio(self):
        """"+" > Create Assembly: a root assembly, its tab active, in edit. A second one is refused
        while upstream's one-assembly rule is on (a document with two crashes after it is closed,
        with or without the tabs). A Variable Studio is a marked VarSet "Variable Studio 1"."""
        self.model(assembly=False)
        first = GuiTabs.create(self.doc, "Assembly")
        pump(0.3)
        self.assertTrue(first)
        self.assertEqual(GuiTabs.activeTab(self.doc), first)
        self.assertEqual(self.doc.getObject(first).getParentGeoFeatureGroup(), None)
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit())
        self.assertEqual(GuiTabs.create(self.doc, "Assembly"), "")
        kinds = [k for _n, k, _l in Tabs.tabs(self.doc)]
        self.assertEqual(kinds.count("Assembly"), 1, Tabs.tabs(self.doc))
        name = GuiTabs.create(self.doc, "VariableStudio")
        pump(0.2)
        variables = self.doc.getObject(name)
        self.assertEqual(variables.TypeId, "App::VarSet")
        self.assertEqual(variables.Label, "Variable Studio 1")
        self.assertTrue(Tabs.isVariableStudio(variables))

    def testCreateDrawing(self):
        """"+" > Create Drawing: a page, its own tab, the TechDraw toolbar."""
        if not techDrawTemplateReadable():
            self.skipTest("no readable TechDraw template")
        self.model(assembly=False)
        name = GuiTabs.create(self.doc, "Drawing")
        pump(0.5)
        tab = [t for t in Tabs.tabs(self.doc) if t[0] == name]
        self.assertEqual(len(tab), 1)
        self.assertEqual(tab[0][1], "Drawing")
        self.assertEqual(GuiTabs.activeTab(self.doc), name)
        self.assertEqual(Gui.activeWorkbench().name(), "TechDrawWorkbench")

    def testRename(self):
        """Rename sets the tab object's Label (an undo step); the implicit studio's name is the
        registry's."""
        objects = self.model(assembly=False)
        self.assertTrue(GuiTabs.rename(self.doc, "Part", "Bracket"))
        self.assertEqual(objects["studio2"].Label, "Bracket")
        self.assertTrue(GuiTabs.rename(self.doc, "*", "Base"))
        pump(0.2)
        self.assertEqual(self.barTexts(), ["Base", "Bracket"])
        undo()
        self.assertEqual(objects["studio2"].Label, "Part Studio 2")

    def testDeleteListsWhatItBreaks(self):
        """Deleting Part Studio 2 while the assembly links its Body is refused with the link
        named; forced, it removes the studio in one undo step; the last Part Studio can't be
        deleted."""
        objects = self.model()
        link = objects["assembly"].newObject("App::Link", "Link")
        link.LinkedObject = objects["body2"]
        self.doc.recompute()
        done, message, users = GuiTabs.deleteTab(self.doc, "Part")
        self.assertFalse(done)
        self.assertIn(link, users)
        self.assertIn("Link", message)
        self.assertIsNotNone(self.doc.getObject("Part"))
        done, message, users = GuiTabs.deleteTab(self.doc, "Part", True)
        self.assertTrue(done, message)
        pump(0.2)
        self.assertIsNone(self.doc.getObject("Part"))
        self.assertIsNone(self.doc.getObject("Cylinder"))
        done, message, _users = GuiTabs.deleteTab(self.doc, "*")
        self.assertFalse(done)
        self.assertIn("last Part Studio", message)
        undo()
        pump(0.2)
        self.assertIsNotNone(self.doc.getObject("Part"))
        self.assertIn("Part", [n for n, _k, _l in Tabs.tabs(self.doc)])

    # -- new documents ---------------------------------------------------------------------------

    def testStdNewStartsWithAPartStudio(self):
        """Std_New under the Onshape keymap: the document's first Part Studio is an App::Part
        "Part Studio 1" (design T2-a), its view that tab's; no undo step, not modified; in Part
        Design the new Body is in it."""
        Gui.activateWorkbench("PartDesignWorkbench")
        before = set(App.listDocuments())
        Gui.runCommand("Std_New")
        pump(0.3)
        added = [n for n in App.listDocuments() if n not in before]
        self.assertEqual(len(added), 1)
        self.docs.append(added[0])
        doc = App.getDocument(added[0])
        parts = [o for o in doc.Objects if o.TypeId == "App::Part"]
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].Label, "Part Studio 1")
        self.assertEqual([(n, k) for n, k, _l in Tabs.tabs(doc)], [(parts[0].Name, "PartStudio")])
        self.assertEqual(GuiTabs.tabOfView(Gui.getDocument(doc.Name).ActiveView), parts[0].Name)
        bodies = [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")]
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0].getParentGeoFeatureGroup(), parts[0])
        self.assertNotIn("Create Part Studio", doc.UndoNames)

    # -- round 6 fixes (ops#640) -------------------------------------------------------------------

    def stdNew(self):
        """Std_New under the Onshape keymap: the new document (closed in tearDown)."""
        before = set(App.listDocuments())
        Gui.runCommand("Std_New")
        pump(0.3)
        added = [n for n in App.listDocuments() if n not in before]
        self.assertEqual(len(added), 1)
        self.docs.append(added[0])
        return App.getDocument(added[0])

    def visibleWidget(self, name):
        found = [w for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget, name) if w.isVisible()]
        return found[0] if found else None

    def treeItem(self, obj):
        """The tree holding obj's item (found by its label), and the item."""
        from PySide import QtCore

        for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
            if tree.metaObject().className() != "Gui::TreeWidget":
                continue
            items = tree.findItems(obj.Label, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive)
            if items:
                return tree, items[0]
        self.fail(f"{obj.Label} isn't in the tree")

    def testSketchInANewStudioMakesItsOwnPart(self):
        """R6T-1: Std_New in Part Design (Part Studio 1 with its "Part 1", here a 10 mm box), then
        "+" > Create Part Studio and New Sketch: the sketch is in a new Body of Part Studio 2, as
        Onshape's sketch in an empty studio makes a part there, not in Part Studio 1's Body; the
        tab stays Part Studio 2. A 10 mm pad on a 10 x 10 rectangle in it is 1000 mm^3; Part
        Studio 1 is unchanged."""
        Gui.activateWorkbench("PartDesignWorkbench")
        doc = self.stdNew()
        [part1] = [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")]
        feature = part1.newObject("PartDesign::AdditiveBox", "Box")
        feature.Length = feature.Width = feature.Height = 10
        doc.recompute()
        self.assertAlmostEqual(part1.Shape.Volume, 1000, 6)
        group1 = [o.Name for o in part1.Group]
        name = GuiTabs.create(doc, "PartStudio")
        pump(0.3)
        self.assertEqual(GuiTabs.activeTab(doc), name)
        Gui.Selection.clearSelection()
        Gui.runCommand("PartDesign_NewSketch")
        pump(0.5)
        sketches = [o for o in doc.Objects if o.isDerivedFrom("Sketcher::SketchObject")]
        self.assertEqual(len(sketches), 1, [o.Name for o in doc.Objects])
        sketch = sketches[0]
        body = sketch.getParentGeoFeatureGroup()
        self.assertTrue(body.isDerivedFrom("PartDesign::Body"), body.Name)
        self.assertIsNot(body, part1)
        self.assertEqual(body.getParentGeoFeatureGroup(), doc.getObject(name))
        self.assertEqual(GuiTabs.activeTab(doc), name)
        gdoc = Gui.getDocument(doc.Name)
        self.assertEqual(GuiTabs.tabOfView(gdoc.ActiveView), name)
        if gdoc.getInEdit():
            gdoc.resetEdit()
            pump(0.3)
        [plane] = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
        sketch.addGeometry(rectangle(0, 0, 10, 10), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 10
        doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 1000, 6)
        self.assertEqual([o.Name for o in part1.Group], group1)
        self.assertAlmostEqual(part1.Shape.Volume, 1000, 6)

    def testNestedPartBodyIsInItsTabsStudio(self):
        """R6T-2: one tab is one studio. Std_Part in Part Studio 2's tab makes a Part Studio tab
        (a top-level App::Part "Part Studio 3", made active), not an App::Part nested in Part
        Studio 2 whose Bodies would be drawn there but missing from its lists; a Body made there
        is in that studio and its tab."""
        self.model(assembly=False)
        self.switch("Part")
        before = {o.Name for o in self.doc.Objects}
        Gui.runCommand("Std_Part")
        pump(0.3)
        parts = [o for o in self.doc.Objects if o.Name not in before and o.TypeId == "App::Part"]
        self.assertEqual(len(parts), 1)
        studio = parts[0]
        self.assertIsNone(studio.getParentGeoFeatureGroup())
        self.assertEqual(studio.Label, "Part Studio 3")
        self.assertEqual(GuiTabs.activeTab(self.doc), studio.Name)
        before = {o.Name for o in self.doc.Objects}
        Gui.runCommand("PartDesign_Body")
        pump(0.3)
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump(0.2)
        bodies = [
            o for o in self.doc.Objects if o.Name not in before and o.isDerivedFrom("PartDesign::Body")
        ]
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0].getParentGeoFeatureGroup(), studio)
        self.assertEqual(Tabs.tabOf(bodies[0]), studio.Name)

    def testEditInAnotherTabWithADialogOpen(self):
        """R6T-3: with the Pad's dialog open in Part Studio 1 (its length changed to 12), editing
        Part Studio 2's cylinder accepts the Pad first, then switches: the Pad's step is Part
        Studio 1's, so its undo from Part Studio 2 switches back there."""
        objects = self.model(assembly=False)
        pad = objects["pad"]
        self.switch("*")
        Gui.ActiveDocument.setEdit(pad.Name)
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog())
        field = self.visibleWidget("lengthEdit")
        self.assertIsNotNone(field, "no length field")
        field.setProperty("rawValue", 12.0)
        pump(0.2)
        Gui.ActiveDocument.setEdit(objects["cylinder"].Name)
        pump(0.3)
        self.assertAlmostEqual(pad.Length.Value, 12, 6)
        self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
        self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "Part")
        Gui.ActiveDocument.resetEdit()
        pump(0.3)
        undo()
        self.assertEqual(GuiTabs.activeTab(self.doc), "*")
        self.assertAlmostEqual(pad.Length.Value, 10, 6)

    def testKeymapSwitchShowsEverything(self):
        """R6T-4: switching to FreeCAD's keymap at runtime (Preferences > General) shows every
        object in every view, with no bars; switching back filters the views by tab again."""
        self.model()
        view2 = self.switch("Part")
        group = App.ParamGet("User parameter:BaseApp/Preferences/General")
        saved = group.GetString("Keymap") if "Keymap" in group.GetStrings() else None
        everything = {"Body", "Pad", "Part", "Body001", "Cylinder", "Assembly"}
        mw = Gui.getMainWindow()
        try:
            group.SetString("Keymap", "FreeCAD")
            pump(0.5)
            self.assertFalse(GuiTabs.isOn())
            self.assertTrue(everything <= shown(view2), shown(view2))
            self.assertEqual(GuiTabs.tabOfView(view2), "")
            self.assertFalse(mw.findChild(QtWidgets.QToolBar, "FreeCADCH_TypedTabs").isVisible())
        finally:
            if saved is None:
                group.RemString("Keymap")
            else:
                group.SetString("Keymap", saved)
            pump(0.5)
        self.assertTrue(GuiTabs.isOn())
        view = Gui.ActiveDocument.ActiveView
        tab = GuiTabs.tabOfView(view)
        self.assertTrue(tab, "the view has no tab again")
        self.assertEqual(GuiTabs.activeTab(self.doc), tab)
        self.assertFalse(everything <= shown(view), shown(view))
        self.assertTrue(mw.findChild(QtWidgets.QToolBar, "FreeCADCH_TypedTabs").isVisible())

    def testTreeSelectionOpensTheObjectsTab(self):
        """R6T-5: from the assembly's tab (in edit), selecting Part Studio 2's Body in the tree
        (SyncView) opens Part Studio 2's tab as the bar does: Part Design's toolbar, the assembly
        out of edit, the selection kept. With a dialog open there, selecting Part Studio 1's Body
        leaves the tab as it is."""
        objects = self.model()
        group = App.ParamGet("User parameter:BaseApp/Preferences/TreeView")
        saved = group.GetBool("SyncView", True)
        group.SetBool("SyncView", True)
        try:
            self.switch("Assembly")
            self.assertIsNotNone(Gui.ActiveDocument.getInEdit())
            widget, item = self.treeItem(objects["body2"])
            widget.clearSelection()
            widget.setCurrentItem(item)
            pump(0.5)
            self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
            self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "Part")
            self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
            self.assertIsNone(Gui.ActiveDocument.getInEdit())
            self.assertIn(objects["body2"], Gui.Selection.getSelection())

            Gui.ActiveDocument.setEdit(objects["cylinder"].Name)
            pump(0.3)
            self.assertTrue(Gui.Control.activeDialog())
            widget, item = self.treeItem(objects["body1"])
            widget.setCurrentItem(item)
            pump(0.5)
            self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
            self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "Part")
            Gui.ActiveDocument.resetEdit()
            pump(0.2)
        finally:
            group.SetBool("SyncView", saved)

    def testImplicitStudioLabelIsUnique(self):
        """R6T-7: after Std_New (its App::Part "Part Studio 1"), a solid a macro or an import puts at
        the top level is the implicit "Part Studio 2" in the bar, not a second "Part Studio 1"."""
        doc = self.stdNew()
        doc.addObject("Part::Box", "Box")
        doc.recompute()
        pump(0.3)
        self.assertEqual(Tabs.label(doc, "*"), "Part Studio 2")
        self.assertEqual(sorted(self.barTexts()), ["Part Studio 1", "Part Studio 2"])

    def testEmptiedImplicitStudioKeepsItsTab(self):
        """R6T-12: Part Studio 1 (the top level) shown, then emptied: its tab and view stay, as
        Onshape keeps an empty Part Studio; the undo brings the Body back into that view."""
        self.model(assembly=False)
        self.switch("*")
        Gui.ActiveDocument.openCommand("Delete the Body")
        for name in ("Pad", "Profile"):
            self.doc.removeObject(name)
        self.doc.getObject("Body").removeObjectsFromDocument()
        self.doc.removeObject("Body")
        Gui.ActiveDocument.commitCommand()
        GuiTabs.reconcile(self.doc)
        pump(0.3)
        self.assertIn("*", [n for n, _k, _l in Tabs.tabs(self.doc)])
        self.assertEqual(self.barTexts(), ["Part Studio 1", "Part Studio 2"])
        self.assertIsNotNone(GuiTabs.viewOf(self.doc, "*"))
        undo()
        pump(0.3)
        self.assertIsNotNone(self.doc.getObject("Body"))
        self.assertIn("Body", shown(GuiTabs.viewOf(self.doc, "*")))

    def testUndoBesideAnOpenDialogShowsTheTab(self):
        """R6T-10: with a dialog open that doesn't lock the history (a script's task panel), Ctrl+Z
        of a step made in Part Studio 2 still shows Part Studio 2, so the undo isn't unseen."""
        objects = self.model(assembly=False)
        cylinder = objects["cylinder"]
        self.switch("Part")
        Gui.ActiveDocument.openCommand("Cylinder height")
        cylinder.Height = 30
        Gui.ActiveDocument.commitCommand()
        self.doc.recompute()
        self.switch("*")

        class Panel:
            def __init__(self):
                self.form = QtWidgets.QWidget()

            def accept(self):
                return True

            def reject(self):
                return True

        Gui.Control.showDialog(Panel())
        pump(0.2)
        try:
            undo()
            self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
            self.assertAlmostEqual(cylinder.Height.Value, 20, 6)
        finally:
            Gui.Control.closeDialog()
            pump(0.2)

    def testReusedNameIsNoVariableStudio(self):
        """R6T-8: a Variable Studio deleted, a new VarSet made with its name (a script) isn't a
        Variable Studio: the mark kept for the delete's undo isn't inherited."""
        name = GuiTabs.create(self.doc, "VariableStudio")
        pump(0.2)
        self.doc.removeObject(name)
        variables = self.doc.addObject("App::VarSet", name)
        self.assertEqual(variables.Name, name)
        self.assertFalse(Tabs.isVariableStudio(variables))
        self.assertNotIn(name, [n for n, _k, _l in Tabs.tabs(self.doc)])

    def testEditThroughAnAssemblyLinkStaysInTheAssembly(self):
        """R6T-11: the cylinder edited through the assembly's link (selected there) is edited in
        the assembly's tab, by the path's top object, not in Part Studio 2's view with the
        assembly's path."""
        objects = self.model()
        link = objects["assembly"].newObject("App::Link", "Link")
        link.LinkedObject = objects["body2"]
        self.doc.recompute()
        self.switch("Assembly")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "Assembly", "Link.Cylinder.")
        Gui.ActiveDocument.setEdit(objects["cylinder"].Name)
        pump(0.3)
        self.assertEqual(GuiTabs.activeTab(self.doc), "Assembly")
        self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "Assembly")
