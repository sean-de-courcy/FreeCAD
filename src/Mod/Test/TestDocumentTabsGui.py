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


def statusMessage():
    """The status bar's texts: MainWindow::showMessage writes its action label, not the bar's
    own message."""
    bar = Gui.getMainWindow().statusBar()
    texts = [bar.currentMessage()] + [label.text() for label in bar.findChildren(QtWidgets.QLabel)]
    return " | ".join(t for t in texts if t)


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
        """"+" > Create Assembly: a root assembly "Assembly 1", its tab active, in edit. A second
        one is "Assembly 2", at the root too, as Onshape's several assemblies (ops#651). A Variable
        Studio is a marked VarSet "Variable Studio 1"."""
        self.model(assembly=False)
        first = GuiTabs.create(self.doc, "Assembly")
        pump(0.3)
        self.assertTrue(first)
        self.assertEqual(GuiTabs.activeTab(self.doc), first)
        self.assertEqual(self.doc.getObject(first).getParentGeoFeatureGroup(), None)
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit())
        second = GuiTabs.create(self.doc, "Assembly")
        pump(0.3)
        self.assertTrue(second)
        self.assertEqual(GuiTabs.activeTab(self.doc), second)
        self.assertEqual(self.doc.getObject(second).getParentGeoFeatureGroup(), None)
        labels = [l for _n, k, l in Tabs.tabs(self.doc) if k == "Assembly"]
        self.assertEqual(labels, ["Assembly 1", "Assembly 2"], Tabs.tabs(self.doc))
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

    def testTreeItemInAGroupedStudioSwitchesToItsTab(self):
        """Review F7-1: Part Studio 2 kept in a plain group (Std_Group, an older file's habit): a
        tree click on its cylinder from Part Studio 1's tab opens Part Studio 2's tab, the group
        being no tab of its own."""
        objects = self.model(assembly=False)
        group = self.doc.addObject("App::DocumentObjectGroup", "Folder")
        group.addObject(objects["studio2"])
        self.doc.recompute()
        GuiTabs.reconcile(self.doc)
        pump(0.3)
        params = App.ParamGet("User parameter:BaseApp/Preferences/TreeView")
        saved = params.GetBool("SyncView", True)
        params.SetBool("SyncView", True)
        try:
            self.switch("*")
            widget, item = self.treeItem(objects["cylinder"])
            widget.clearSelection()
            widget.setCurrentItem(item)
            pump(0.5)
            self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "Part")
        finally:
            params.SetBool("SyncView", saved)

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

    def testUndoBesideAnOpenDialogIsRefused(self):
        """F6-3 (was R6T-10): with a dialog open that doesn't lock the history (a script's task
        panel), Ctrl+Z of a step made in Part Studio 2 is refused ("Finish or cancel the open
        dialog first"): showing that tab under the dialog stranded the user there. Once the
        dialog is closed the undo switches and undoes."""
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
            self.assertEqual(GuiTabs.activeTab(self.doc), "*")
            self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "*")
            self.assertAlmostEqual(cylinder.Height.Value, 30, 6)
            self.assertIn("Finish or cancel", statusMessage())
        finally:
            Gui.Control.closeDialog()
            pump(0.2)
        undo()
        self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
        self.assertAlmostEqual(cylinder.Height.Value, 20, 6)

    def testUndoBesideAPlacementPanelLeavesTheAssemblyReachable(self):
        """F6-3: a step made in Part Studio 2 (the cylinder 20 -> 30), then the assembly's tab with
        Std_Placement's dialog open on its cube (it doesn't lock the history): Ctrl+Z is refused
        with the reason, the assembly's tab and view stay, the dialog stays open; closed, the undo
        switches to Part Studio 2 and undoes, and the assembly's tab is reachable again. (A joint
        dialog holds its own open step, "Create ... Joint", which a Ctrl+Z beside it undoes first,
        in place.)"""
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        objects = self.model()
        cylinder = objects["cylinder"]
        cube = objects["assembly"].newObject("Part::Box", "AsmCube")
        cube.Length = cube.Width = cube.Height = 10
        self.doc.recompute()
        self.switch("Part")
        Gui.ActiveDocument.openCommand("Cylinder height")
        cylinder.Height = 30
        Gui.ActiveDocument.commitCommand()
        self.doc.recompute()
        self.switch("Assembly")
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit())

        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "Assembly", "AsmCube.")
        Gui.runCommand("Std_Placement")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "no placement dialog")
        try:
            info = (self.doc.isStepLocked(), self.doc.HasPendingTransaction, self.doc.UndoNames)
            undo()
            info += (self.doc.UndoNames, statusMessage())
            self.assertEqual(GuiTabs.activeTab(self.doc), "Assembly", info)
            self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "Assembly")
            self.assertAlmostEqual(cylinder.Height.Value, 30, 6)
            self.assertIn("Finish or cancel", statusMessage(), info)
            self.assertTrue(Gui.Control.activeDialog(), "the dialog was closed")
        finally:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            pump(0.3)
        undo()
        self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
        self.assertAlmostEqual(cylinder.Height.Value, 20, 6)
        self.switch("Assembly")
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit())

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

    def linkedItem(self, tree, top, path):
        """The tree item reached from top by the labels in path, each expanded on the way (a
        link's children are made when it is expanded)."""
        item = top
        for label in path:
            item.setExpanded(True)
            pump(0.2)
            found = None
            stack = [item.child(i) for i in range(item.childCount())]
            while stack and found is None:
                child = stack.pop(0)
                if child.text(0) == label:
                    found = child
                else:
                    child.setExpanded(True)
                    stack += [child.child(i) for i in range(child.childCount())]
            self.assertIsNotNone(found, f"{label} under {item.text(0)}")
            item = found
        return item

    def testTreeItemUnderAnAssemblyLinkStaysInTheAssembly(self):
        """F6-1: from the assembly's tab (in edit, Assembly workbench), the cylinder selected in
        the tree through the assembly's link (Assembly > Link > Cylinder) leaves the tab, the edit
        and the workbench as they are (the path's top object is the assembly), where Part Studio
        2's tab came up with Part Design; double-clicked there, it is edited in the assembly's
        tab (Part Design's dialog), the Assembly workbench back once it is closed."""
        from PySide6 import QtTest
        from PySide import QtCore

        objects = self.model()
        link = objects["assembly"].newObject("App::Link", "Link")
        link.LinkedObject = objects["body2"]
        self.doc.recompute()
        group = App.ParamGet("User parameter:BaseApp/Preferences/TreeView")
        saved = group.GetBool("SyncView", True)
        group.SetBool("SyncView", True)
        try:
            Gui.activateWorkbench("AssemblyWorkbench")
            self.switch("Assembly")
            self.assertIsNotNone(Gui.ActiveDocument.getInEdit())
            tree, top = self.treeItem(objects["assembly"])
            item = self.linkedItem(tree, top, ["Link", "Cylinder"])
            tree.clearSelection()
            tree.scrollToItem(item)
            tree.setCurrentItem(item)
            pump(0.5)
            self.assertEqual(GuiTabs.activeTab(self.doc), "Assembly")
            self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "Assembly")
            self.assertIsNotNone(Gui.ActiveDocument.getInEdit(), "the assembly left edit")
            self.assertEqual(Gui.activeWorkbench().name(), "AssemblyWorkbench")

            rect = tree.visualItemRect(item)
            QtTest.QTest.mouseDClick(tree.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center())
            pump(0.5)
            self.assertEqual(GuiTabs.activeTab(self.doc), "Assembly")
            self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), "Assembly")
            # The cylinder's dialog is Part Design's (its edit brings Part Design up, as
            # upstream); closed, the workbench is the assembly's again, the tab unchanged
            self.assertTrue(Gui.Control.activeDialog(), "the cylinder isn't edited")
            Gui.Control.closeDialog()
            pump(0.3)
            if Gui.ActiveDocument.getInEdit():
                Gui.ActiveDocument.resetEdit()
                pump(0.3)
            self.assertEqual(Gui.activeWorkbench().name(), "AssemblyWorkbench")
            self.assertEqual(GuiTabs.activeTab(self.doc), "Assembly")
        finally:
            group.SetBool("SyncView", saved)
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            pump(0.2)

    def testOpeningATopLevelSolidFileIsNotModified(self):
        """F6-2: an old file with a top-level solid (its implicit Part Studio 1, a 10 mm box),
        opened under the Onshape keymap and its tab shown, is not modified and its Meta holds no
        implicit label: showing a tab stores nothing (closing doesn't ask to save). Deleting the
        box there stores it: the emptied tab stays (R6T-12)."""
        import shutil
        import tempfile

        self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        meta = dict(self.doc.Meta)
        meta.pop(Tabs.metaKey(), None)
        self.doc.Meta = meta
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "TopLevelSolid.FCStd")
            self.doc.saveAs(path)
            name = self.doc.Name
            App.closeDocument(name)
            pump(0.2)
            doc = App.openDocument(path)
            self.docs.append(doc.Name)
            self.doc = doc
            pump(0.5)
            GuiTabs.reconcile(doc)
            done, refusal = GuiTabs.switchTo(doc, "*")
            self.assertTrue(done, refusal)
            pump(0.3)
            self.assertAlmostEqual(doc.getObject("Box").Shape.Volume, 1000, 6)
            self.assertNotIn("implicit=", doc.Meta.get(Tabs.metaKey(), ""))
            self.assertFalse(Gui.getDocument(doc.Name).Modified, "opening marked it modified")

            Gui.getDocument(doc.Name).openCommand("Delete the box")
            doc.removeObject("Box")
            Gui.getDocument(doc.Name).commitCommand()
            GuiTabs.reconcile(doc)
            pump(0.3)
            self.assertIn("*", [n for n, _k, _l in Tabs.tabs(doc)])
            App.closeDocument(doc.Name)
            pump(0.2)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def testSketchInTheAssemblyTabIsRefused(self):
        """With the assembly's tab active (in edit), Part Design's New Sketch and a primitive make
        no top-level Body (a new implicit studio tab, the assembly out of edit): they are refused
        with "Open a Part Studio tab to sketch", nothing added, no undo step, the tab and the edit
        kept, as Derived refuses outside a Part Studio."""
        import PartDesignGui  # noqa: F401 (the commands)

        self.model()
        self.switch("Assembly")
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit())
        before = sorted(o.Name for o in self.doc.Objects)
        undoCount = self.doc.UndoCount
        Gui.runCommand("PartDesign_NewSketch")
        pump(0.3)
        self.assertIn("Open a Part Studio tab", statusMessage())
        self.assertFalse(Gui.Control.activeDialog())
        Gui.runCommand("PartDesign_CompPrimitiveAdditive", 0)
        pump(0.3)
        self.assertFalse(Gui.Control.activeDialog())
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertEqual(self.doc.UndoCount, undoCount)
        self.assertEqual(GuiTabs.activeTab(self.doc), "Assembly")
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit())

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


    # -- slice 2: Duplicate, Export, the Tab manager, the bar's drag (ops#640 round 8) -------------

    def testDuplicateFromTheBar(self):
        """The tab menu's Duplicate: Part Studio 2's copy "Part Studio 2 (1)" right of it, made
        active, its view showing only the copy (the same volume), its Body named "Part N" (RT-4);
        one undo step removes the copy tab, its redo shows it again (RT-3). The implicit studio
        isn't offered, with the reason."""
        objects = self.model(assembly=False)
        self.switch("Part")
        undoCount = self.doc.UndoCount
        copy, refusal = GuiTabs.duplicate(self.doc, "Part")
        pump(0.3)
        self.assertTrue(copy, refusal)
        self.assertEqual(self.doc.UndoCount, undoCount + 1)
        self.assertEqual(self.barTexts(), ["Part Studio 1", "Part Studio 2", "Part Studio 2 (1)"])
        self.assertEqual(GuiTabs.activeTab(self.doc), copy)
        view = GuiTabs.viewOf(self.doc, copy)
        self.assertIsNotNone(view)
        copyBodies = [
            o for o in self.doc.getObject(copy).Group if o.isDerivedFrom("PartDesign::Body")
        ]
        self.assertEqual(len(copyBodies), 1)
        names = shown(view)
        self.assertIn(copyBodies[0].Name, names)
        self.assertNotIn(objects["body2"].Name, names)
        self.assertNotIn(objects["body1"].Name, names)
        self.assertAlmostEqual(copyBodies[0].Shape.Volume, objects["body2"].Shape.Volume, 6)
        self.assertEqual(copyBodies[0].Label, "Part 1")

        undo()
        pump(0.3)
        self.assertIsNone(self.doc.getObject(copy))
        self.assertEqual(self.barTexts(), ["Part Studio 1", "Part Studio 2"])
        self.switch("*")
        redo()
        pump(0.5)
        self.assertIsNotNone(self.doc.getObject(copy))
        self.assertEqual(GuiTabs.activeTab(self.doc), copy)

        copy, refusal = GuiTabs.duplicate(self.doc, "*")
        self.assertEqual(copy, "")
        self.assertIn("top level", refusal)

    def testExportFromTheBar(self):
        """The tab menu's Export once the file is chosen (ImportGui's writer): Part Studio 2's
        cylinder, re-read, has its volume."""
        import shutil
        import tempfile

        objects = self.model(assembly=False)
        folder = tempfile.mkdtemp(prefix="TestDocumentTabsGui")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Part Studio 2.step")
        done, error = GuiTabs.exportTab(self.doc, "Part", path)
        self.assertTrue(done, error)
        self.assertAlmostEqual(Part.read(path).Volume, objects["body2"].Shape.Volume, 3)
        done, error = GuiTabs.exportTab(self.doc, "VarSetMissing", path)
        self.assertFalse(done)

    # -- E1: a drawing's tab exports (ops#640, notes/drawings-design.md section 5) ------------------

    def drawingTab(self, title, source=None):
        """A drawing on the ANSI A (landscape) template whose first title line is `title`, its
        tab's name."""
        import TechDrawCreateDrawing as Create

        page = Create.createDrawing(self.doc, source, views=source is not None)
        svg = page.Template
        texts = dict(svg.EditableTexts)
        texts["DrawingTitle1"] = title
        svg.EditableTexts = texts
        self.doc.recompute()
        GuiTabs.reconcile(self.doc)
        pump(0.3)
        names = [n for n, kind, _label in Tabs.tabs(self.doc) if kind == "Drawing"]
        return [n for n in names if self.doc.getObject(n) == page][0]

    def tabMenu(self, tabName):
        """The tab menu of a tab, opened on its bar and read: {action's object name or text:
        (text, enabled)}, then closed."""
        from PySide import QtCore

        bar = Gui.getMainWindow().findChild(QtWidgets.QTabBar, "FreeCADCH_TypedTabBar")
        self.assertIsNotNone(bar)
        index = [bar.tabData(i) for i in range(bar.count())].index(tabName)
        found = {}

        def read():
            menu = QtWidgets.QApplication.activePopupWidget()
            if menu is None:
                return
            for action in menu.actions():
                found[action.objectName() or action.text()] = (action.text(), action.isEnabled())
            menu.close()

        QtCore.QTimer.singleShot(400, read)
        bar.customContextMenuRequested.emit(bar.tabRect(index).center())
        pump(0.2)
        return found

    def testDrawingTabExports(self):
        """A drawing's tab menu offers Export; it writes the page as a PDF of one ANSI A page
        (11 x 8.5 in = 792 x 612 pt) holding the title's text, or as an SVG, with the page's
        window closed; other file types are refused."""
        import shutil
        import tempfile

        if not techDrawTemplateReadable():
            self.skipTest("no readable TechDraw template")
        objects = self.model(assembly=False)
        name = self.drawingTab("BLOCKTITLE", objects["body1"])
        folder = tempfile.mkdtemp(prefix="TestDocumentTabsGui")
        self.addCleanup(shutil.rmtree, folder, True)

        menu = self.tabMenu(name)
        self.assertTrue(menu["FreeCADCH_ExportTab"][1], menu)
        self.assertTrue(menu["FreeCADCH_ExportAllDrawings"][1], menu)
        partMenu = self.tabMenu("Part")
        self.assertTrue(partMenu["FreeCADCH_ExportTab"][1], partMenu)
        self.assertNotIn("FreeCADCH_ExportAllDrawings", partMenu)

        # the page's window closed first: the export does not need it
        page = self.doc.getObject(name)
        page.ViewObject.hide()
        pump(0.3)
        pdf = os.path.join(folder, "Bob's one.pdf")  # an apostrophe in the name
        done, error = GuiTabs.exportTab(self.doc, name, pdf)
        self.assertTrue(done, error)
        data = open(pdf, "rb").read()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(self.pdfPageSizes(data), [(792, 612)])
        self.assertIn("BLOCKTITLE", self.pdfText(data))

        svg = os.path.join(folder, "one.svg")
        done, error = GuiTabs.exportTab(self.doc, name, svg)
        self.assertTrue(done, error)
        self.assertIn("BLOCKTITLE", open(svg, encoding="utf-8").read())

        done, error = GuiTabs.exportTab(self.doc, name, os.path.join(folder, "one.dxf"))
        self.assertFalse(done)
        self.assertIn("PDF or SVG", error)

    def testReopenedDrawingExportsUnopened(self):
        """A drawing of a saved and reopened document, its page never shown, exports to PDF and
        SVG with its title (the scene is filled for the export)."""
        import shutil
        import tempfile

        if not techDrawTemplateReadable():
            self.skipTest("no readable TechDraw template")
        objects = self.model(assembly=False)
        name = self.drawingTab("REOPENEDTITLE", objects["body1"])
        folder = tempfile.mkdtemp(prefix="TestDocumentTabsGui")
        self.addCleanup(shutil.rmtree, folder, True)
        saved = os.path.join(folder, "drawing.FCStd")
        self.switch("Part")
        self.doc.getObject(name).ViewObject.hide()  # saved hidden: reopened without its window
        self.doc.saveAs(saved)
        oldName = self.doc.Name
        App.closeDocument(oldName)
        self.docs.remove(oldName)
        pump(0.3)
        self.doc = App.openDocument(saved)
        self.docs.append(self.doc.Name)
        pump(0.5)
        page = self.doc.getObject(name)
        self.assertIsNotNone(page)
        self.assertIsNone(GuiTabs.viewOf(self.doc, name), "the page's window is not open")

        pdf = os.path.join(folder, "reopened.pdf")
        done, error = GuiTabs.exportTab(self.doc, name, pdf)
        self.assertTrue(done, error)
        data = open(pdf, "rb").read()
        self.assertEqual(self.pdfPageSizes(data), [(792, 612)])
        self.assertIn("REOPENEDTITLE", self.pdfText(data))
        svg = os.path.join(folder, "reopened.svg")
        done, error = GuiTabs.exportTab(self.doc, name, svg)
        self.assertTrue(done, error)
        self.assertIn("REOPENEDTITLE", open(svg, encoding="utf-8").read())

    def testAllDrawingsExportAsOnePdf(self):
        """Two drawings give one PDF of two pages, in the bar's order, each with its own title;
        a document without a drawing refuses and writes nothing."""
        import shutil
        import tempfile

        if not techDrawTemplateReadable():
            self.skipTest("no readable TechDraw template")
        objects = self.model(assembly=False)
        self.drawingTab("FIRSTSHEET", objects["body1"])
        self.drawingTab("SECONDSHEET")
        folder = tempfile.mkdtemp(prefix="TestDocumentTabsGui")
        self.addCleanup(shutil.rmtree, folder, True)

        path = os.path.join(folder, "all.pdf")
        done, error = GuiTabs.exportAllDrawings(self.doc, path)
        self.assertTrue(done, error)
        data = open(path, "rb").read()
        self.assertEqual(self.pdfPageSizes(data), [(792, 612), (792, 612)])
        text = self.pdfText(data)
        self.assertIn("FIRSTSHEET", text)
        self.assertIn("SECONDSHEET", text)
        self.assertLess(text.index("FIRSTSHEET"), text.index("SECONDSHEET"))

        other = self.newDocument("TestDocumentTabsGuiNoDrawing")
        none = os.path.join(folder, "none.pdf")
        done, error = GuiTabs.exportAllDrawings(other, none)
        self.assertFalse(done)
        self.assertFalse(os.path.exists(none))

    def pdfObjects(self, data):
        """The objects of a Qt-written PDF: (dictionary text, decoded stream or None) each."""
        import re
        import zlib

        text = data.decode("latin-1")
        objects = []
        for match in re.finditer(r"\d+ 0 obj(.*?)endobj", text, re.S):
            body = match.group(1)
            stream = None
            start = body.find("stream")
            if start >= 0:
                raw = body[start + 6 :].lstrip("\r\n")
                raw = raw[: raw.rfind("endstream")].rstrip("\r\n").encode("latin-1")
                try:
                    stream = zlib.decompress(raw) if "FlateDecode" in body[:start] else raw
                except zlib.error:
                    stream = None
            objects.append((body[: start if start >= 0 else len(body)], stream))
        return objects

    def pdfPageSizes(self, data):
        """The pages' (width, height) in points, rounded, in file order."""
        import re

        sizes = []
        for info, _stream in self.pdfObjects(data):
            if re.search(r"/Type\s*/Page\b(?!s)", info):
                box = re.search(r"/MediaBox\s*\[([^\]]*)\]", info)
                x0, y0, x1, y1 = (float(v) for v in box.group(1).split())
                sizes.append((round(x1 - x0), round(y1 - y0)))
        return sizes

    def pdfText(self, data):
        """The text a Qt-written PDF shows, page by page ("\n" between pages): each glyph of a
        content stream mapped back through its font's ToUnicode table (Qt writes one `<glyph> Tj`
        per glyph, the fonts as /F<n> in the page's resources)."""
        import re

        objects = {}
        text = data.decode("latin-1")
        decoded = self.pdfObjects(data)
        for match, (info, stream) in zip(re.finditer(r"(\d+) 0 obj", text), decoded):
            objects[int(match.group(1))] = (info, stream)

        def cmap(number):
            table = {}
            stream = (objects.get(number) or ("", None))[1]
            if not stream:
                return table
            body = stream.decode("latin-1")
            for block in re.findall(r"beginbfchar(.*?)endbfchar", body, re.S):
                for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                    table[int(src, 16)] = chr(int(dst[:4], 16))
            for block in re.findall(r"beginbfrange(.*?)endbfrange", body, re.S):
                for lo, hi, dst in re.findall(
                    r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", block
                ):
                    values = re.findall(r"<([0-9A-Fa-f]+)>", dst)
                    for k in range(int(lo, 16), int(hi, 16) + 1):
                        index = k - int(lo, 16)
                        if dst.startswith("["):
                            table[k] = chr(int(values[index][:4], 16))
                        else:
                            table[k] = chr(int(values[0][:4], 16) + index)
            return table

        pages = []
        for info, _stream in decoded:
            if not re.search(r"/Type\s*/Page\b(?!s)", info):
                continue
            contents = int(re.search(r"/Contents\s+(\d+) 0 R", info).group(1))
            resources = objects[int(re.search(r"/Resources\s+(\d+) 0 R", info).group(1))][0]
            fonts = {}
            for name, number in re.findall(r"/(F\d+)\s+(\d+) 0 R", resources):
                font = objects[int(number)][0]
                unicode_table = re.search(r"/ToUnicode\s+(\d+) 0 R", font)
                fonts[name] = cmap(int(unicode_table.group(1))) if unicode_table else {}
            words = []
            table = {}
            for token in re.finditer(rb"/(F\d+)\s+[\d.]+\s+Tf|<([0-9A-Fa-f]+)>\s*Tj", objects[contents][1]):
                if token.group(1):
                    table = fonts.get(token.group(1).decode(), {})
                else:
                    run = token.group(2)
                    words.append(
                        "".join(table.get(int(run[i : i + 4], 16), "?") for i in range(0, len(run), 4))
                    )
            pages.append("".join(words))
        return "\n".join(pages)

    def testDragOnTheBarSavesTheOrder(self):
        """A tab dragged along the bar: the order is the document's (saved, the document marked
        modified), not an undo step."""
        self.model()
        pump(0.2)
        undoCount = self.doc.UndoCount
        Gui.ActiveDocument.Modified = False
        GuiTabs.moveTab(0, 2)
        pump(0.3)
        self.assertEqual(self.barTexts(), ["Part Studio 2", "Assembly", "Part Studio 1"])
        self.assertEqual([n for n, _k, _l in Tabs.tabs(self.doc)], ["Part", "Assembly", "*"])
        self.assertEqual(Tabs.order(self.doc), ["Part", "Assembly", "*"])
        self.assertEqual(self.doc.UndoCount, undoCount)
        self.assertTrue(Gui.ActiveDocument.Modified)

    def manager(self):
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget.objectName() == "FreeCADCH_TabManagerDialog" and widget.isVisible():
                return widget
        return None

    def visibleRows(self, tabList):
        rows = range(tabList.count())
        return [tabList.item(r).text() for r in rows if not tabList.isRowHidden(r)]

    def testTabManager(self):
        """Alt+T opens the Tab manager: the tabs, a search, a type filter; a row moved reorders
        the tabs (saved, no undo step); Enter on a row opens its tab and closes the manager."""
        from PySide6.QtTest import QTest
        from PySide import QtCore

        self.model()
        variables = self.doc.addObject("App::VarSet", "VarSet")
        variables.Label = "Variable Studio 1"
        Tabs.setVariableStudio(variables)
        GuiTabs.reconcile(self.doc)
        self.switch("*")
        mw = Gui.getMainWindow()
        QTest.keyClick(mw, QtCore.Qt.Key_T, QtCore.Qt.AltModifier)
        pump(0.3)
        dialog = self.manager()
        self.assertIsNotNone(dialog, "Alt+T opened no Tab manager")
        search = dialog.findChild(QtWidgets.QLineEdit, "FreeCADCH_TabSearch")
        typeFilter = dialog.findChild(QtWidgets.QComboBox, "FreeCADCH_TabFilter")
        tabList = dialog.findChild(QtWidgets.QListWidget, "FreeCADCH_TabList")
        self.assertEqual(
            self.visibleRows(tabList),
            ["Part Studio 1", "Part Studio 2", "Assembly", "Variable Studio 1"],
        )
        search.setText("studio 2")
        pump(0.1)
        self.assertEqual(self.visibleRows(tabList), ["Part Studio 2"])
        search.clear()
        typeFilter.setCurrentIndex(typeFilter.findText("Assemblies"))
        pump(0.1)
        self.assertEqual(self.visibleRows(tabList), ["Assembly"])
        typeFilter.setCurrentIndex(typeFilter.findText("Variable Studios"))
        pump(0.1)
        self.assertEqual(self.visibleRows(tabList), ["Variable Studio 1"])
        typeFilter.setCurrentIndex(0)
        pump(0.1)

        undoCount = self.doc.UndoCount
        item = tabList.takeItem(0)
        tabList.insertItem(2, item)
        pump(0.3)
        self.assertEqual(
            [n for n, _k, _l in Tabs.tabs(self.doc)], ["Part", "Assembly", "*", "VarSet"]
        )
        self.assertEqual(
            self.barTexts(), ["Part Studio 2", "Assembly", "Part Studio 1", "Variable Studio 1"]
        )
        self.assertEqual(self.doc.UndoCount, undoCount)

        dialog = self.manager()
        tabList = dialog.findChild(QtWidgets.QListWidget, "FreeCADCH_TabList")
        rows = [tabList.item(r).text() for r in range(tabList.count())]
        tabList.setCurrentRow(rows.index("Part Studio 2"))
        tabList.setFocus()
        QTest.keyClick(tabList, QtCore.Qt.Key_Return)
        pump(0.3)
        self.assertEqual(GuiTabs.activeTab(self.doc), "Part")
        self.assertIsNone(self.manager())

    def testTabManagerButton(self):
        """The bar's leftmost button opens the Tab manager; Enter in its search box opens the
        first match."""
        self.model()
        self.switch("*")
        button = Gui.getMainWindow().findChild(QtWidgets.QToolButton, "FreeCADCH_TabManager")
        self.assertTrue(button.isEnabled())
        button.click()
        pump(0.3)
        dialog = self.manager()
        self.assertIsNotNone(dialog)
        search = dialog.findChild(QtWidgets.QLineEdit, "FreeCADCH_TabSearch")
        search.setText("assem")
        search.returnPressed.emit()
        pump(0.5)
        self.assertEqual(GuiTabs.activeTab(self.doc), "Assembly")
        self.assertIsNone(self.manager())

    # -- tabs 3: a tab's kind fixes its tools; the strip and "+" (ops#640) ------------------------------

    def workbenchAction(self, name):
        """The checkable QAction of the workbench selector's group (what the toolbar's combo box
        and View > Workbench trigger), by workbench name."""
        from PySide import QtGui

        for action in QtWidgets.QApplication.instance().findChildren(QtGui.QAction):
            if action.objectName() == name and action.isCheckable():
                return action
        self.fail("no workbench action " + name)

    def userActivates(self, name):
        """A click on the workbench in the selector or the menu: the action is triggered, which
        runs Std_Workbench."""
        self.workbenchAction(name).trigger()
        pump(0.3)

    def viewMenu(self):
        mw = Gui.getMainWindow()
        for action in mw.menuBar().actions():
            if action.text().replace("&", "") == "View":
                return action.menu()
        self.fail("no View menu")

    def workbenchSubmenuVisible(self):
        return any(
            a.menu() is not None and a.text().replace("&", "") == "Workbench" and a.isVisible()
            for a in self.viewMenu().actions()
        )

    def workbenchToolbarVisible(self):
        bar = Gui.getMainWindow().findChild(QtWidgets.QToolBar, "Workbench")
        return bar is not None and bar.isVisible()

    def testTheWorkbenchSelectorIsNotOffered(self):
        """Under the Onshape keymap the "Workbench" toolbar and the View > Workbench submenu are
        gone, on every workbench; under FreeCAD's keymap they are there."""
        self.model()
        for name, tab in (("PartDesignWorkbench", "*"), ("AssemblyWorkbench", "Assembly")):
            self.switch(tab)
            self.assertEqual(Gui.activeWorkbench().name(), name)
            self.assertFalse(self.workbenchToolbarVisible(), name)
            self.assertFalse(self.workbenchSubmenuVisible(), name)
        group = App.ParamGet("User parameter:BaseApp/Preferences/General")
        saved = group.GetString("Keymap") if "Keymap" in group.GetStrings() else None
        try:
            group.SetString("Keymap", "FreeCAD")
            pump(0.5)
            self.assertFalse(GuiTabs.isOn())
            self.assertTrue(self.workbenchSubmenuVisible())
            self.assertTrue(self.workbenchToolbarVisible())
            # FreeCAD's keymap switches freely, by the selector too
            self.userActivates("PartDesignWorkbench")
            self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
            self.userActivates("AssemblyWorkbench")
            self.assertEqual(Gui.activeWorkbench().name(), "AssemblyWorkbench")
        finally:
            if saved is None:
                group.RemString("Keymap")
            else:
                group.SetString("Keymap", saved)
            pump(0.5)
        self.assertTrue(GuiTabs.isOn())
        self.assertFalse(self.workbenchSubmenuVisible())
        self.assertFalse(self.workbenchToolbarVisible())

    def testAWorkbenchThatDoesNotFitTheTabIsTurnedBack(self):
        """A Part Studio tab takes Part Design (and the Sketcher); Assembly from the selector or
        the menu is turned back, with the reason in the status bar. An assembly tab takes
        Assembly only. A script's activateWorkbench stays usable."""
        self.model()
        self.switch("*")
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        self.userActivates("AssemblyWorkbench")
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        self.assertTrue(self.workbenchAction("PartDesignWorkbench").isChecked())
        self.assertFalse(self.workbenchAction("AssemblyWorkbench").isChecked())
        self.assertIn("This tab is a Part Studio: use + for an Assembly", statusMessage())
        self.userActivates("TechDrawWorkbench")
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        self.assertIn("This tab is a Part Studio: use + for a Drawing", statusMessage())
        self.assertEqual(GuiTabs.activeTab(self.doc), "*")
        # the Sketcher and Part Design are the studio's
        self.userActivates("SketcherWorkbench")
        self.assertEqual(Gui.activeWorkbench().name(), "SketcherWorkbench")
        self.userActivates("PartDesignWorkbench")
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        # the assembly tab: Assembly yes, Part Design no
        self.switch("Assembly")
        self.assertEqual(Gui.activeWorkbench().name(), "AssemblyWorkbench")
        self.userActivates("PartDesignWorkbench")
        self.assertEqual(Gui.activeWorkbench().name(), "AssemblyWorkbench")
        self.assertIn("This tab is an Assembly: use + for a Part Studio", statusMessage())
        self.assertEqual(GuiTabs.activeTab(self.doc), "Assembly")
        # a script is not the selector
        Gui.activateWorkbench("PartDesignWorkbench")
        pump(0.2)
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        self.switch("*")
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")

    def testWhichWorkbenchesAKindTakes(self):
        """The rule by kind: a Part Studio takes PartDesign and Sketcher, an Assembly its own
        workbench, a Variable Studio none besides the one it has."""
        self.model()
        for tab, allowed, refused in (
            ("*", ["PartDesignWorkbench", "SketcherWorkbench"], ["AssemblyWorkbench", "TechDrawWorkbench"]),
            ("Assembly", ["AssemblyWorkbench"], ["PartDesignWorkbench", "TechDrawWorkbench"]),
        ):
            self.switch(tab)
            for name in allowed:
                self.assertTrue(GuiTabs.allowsWorkbench(name)[0], (tab, name))
            for name in refused:
                ok, why = GuiTabs.allowsWorkbench(name)
                self.assertFalse(ok, (tab, name))
                self.assertIn("This tab is", why)
        name = GuiTabs.create(self.doc, "VariableStudio")
        pump(0.3)
        self.assertEqual(GuiTabs.activeTab(self.doc), name)
        current = Gui.activeWorkbench().name()
        self.assertTrue(GuiTabs.allowsWorkbench(current)[0])
        for other in ("PartDesignWorkbench", "AssemblyWorkbench", "TechDrawWorkbench"):
            if other != current:
                ok, why = GuiTabs.allowsWorkbench(other)
                self.assertFalse(ok, other)
                self.assertIn("This tab is a Variable Studio", why)

    def testASketchOpensAndLeavesInAStudioTab(self):
        """Editing a sketch enters the Sketcher and leaving it comes back to Part Design, in a
        Part Studio tab; the selector's refusal doesn't block it or loop."""
        objects = self.model(assembly=False)
        self.switch("*")
        sketch = self.doc.getObject("Profile")
        Gui.ActiveDocument.setEdit(sketch.Name)
        pump(0.5)
        self.assertEqual(Gui.activeWorkbench().name(), "SketcherWorkbench")
        self.assertEqual(GuiTabs.activeTab(self.doc), "*")
        self.userActivates("AssemblyWorkbench")  # turned back while the sketch is open
        self.assertEqual(Gui.activeWorkbench().name(), "SketcherWorkbench")
        Gui.ActiveDocument.resetEdit()
        pump(0.5)
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        self.assertEqual(GuiTabs.activeTab(self.doc), "*")

    def testNoDocumentTakesAnyWorkbench(self):
        """With no document open there is no tab: any workbench can be activated."""
        for name in list(App.listDocuments()):
            App.closeDocument(name)
        pump(0.3)
        self.assertTrue(GuiTabs.allowsWorkbench("AssemblyWorkbench")[0])
        self.userActivates("AssemblyWorkbench")
        self.assertEqual(Gui.activeWorkbench().name(), "AssemblyWorkbench")
        self.userActivates("PartDesignWorkbench")
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")

    def stripGeometry(self):
        """The document strip's row: its top, left, width and height in the main window, and the
        top-area toolbars that share its row or lie above it."""
        from PySide import QtCore

        mw = Gui.getMainWindow()
        strip = mw.findChild(QtWidgets.QToolBar, "FreeCADCH_DocumentStrip")
        self.assertIsNotNone(strip)
        self.assertTrue(strip.isVisible())
        self.assertEqual(mw.toolBarArea(strip), QtCore.Qt.TopToolBarArea)
        origin = strip.mapTo(mw, QtCore.QPoint(0, 0))
        geometry = (origin.x(), origin.y(), strip.width(), strip.height())
        beside = []
        for bar in mw.findChildren(QtWidgets.QToolBar):
            if bar is strip or not bar.isVisible() or mw.toolBarArea(bar) != QtCore.Qt.TopToolBarArea:
                continue
            top = bar.mapTo(mw, QtCore.QPoint(0, 0)).y()
            if top < origin.y() + strip.height():
                beside.append(bar.objectName())
        return geometry, beside

    def testTheStripHasItsOwnRowAboveTheTools(self):
        """The document strip is alone on a full-width row above every toolbar, and it neither
        moves nor changes width when the tab or the workbench changes or a sketch is edited."""
        self.model()
        mw = Gui.getMainWindow()
        self.switch("*")
        pump(0.3)
        before, beside = self.stripGeometry()
        self.assertEqual(beside, [], "toolbars on or above the strip's row")
        self.assertGreaterEqual(before[2], mw.width() * 0.9, before)  # a full-width row
        self.switch("Assembly")
        pump(0.3)
        self.assertEqual(self.stripGeometry(), (before, []))
        self.switch("Part")
        pump(0.3)
        self.assertEqual(self.stripGeometry(), (before, []))
        self.switch("*")
        Gui.ActiveDocument.setEdit(self.doc.getObject("Profile").Name)
        pump(0.5)
        self.assertEqual(Gui.activeWorkbench().name(), "SketcherWorkbench")
        self.assertEqual(self.stripGeometry(), (before, []))
        Gui.ActiveDocument.resetEdit()
        pump(0.5)
        self.assertEqual(self.stripGeometry(), (before, []))
        # a toolbar a workbench makes later lands below the strip, not on its row
        Gui.activateWorkbench("TechDrawWorkbench")
        pump(0.5)
        self.assertEqual(self.stripGeometry(), (before, []))
        Gui.activateWorkbench("PartDesignWorkbench")
        pump(0.3)

    def testTheNewTabButtonIsAsEasyToSeeAsATab(self):
        """"+" and the Tab manager button are at least a tab high, "+" shows its glyph and says
        what it inserts."""
        self.model()
        self.switch("*")
        pump(0.3)
        mw = Gui.getMainWindow()
        typed = mw.findChild(QtWidgets.QTabBar, "FreeCADCH_TypedTabBar")
        plus = mw.findChild(QtWidgets.QToolButton, "FreeCADCH_NewTab")
        manager = mw.findChild(QtWidgets.QToolButton, "FreeCADCH_TabManager")
        self.assertGreater(typed.count(), 0)
        tabHeight = typed.tabRect(0).height()
        self.assertGreater(tabHeight, 0)
        for button in (plus, manager):
            self.assertTrue(button.isVisible(), button.objectName())
            self.assertGreaterEqual(button.height(), tabHeight, button.objectName())
            self.assertGreaterEqual(button.width(), tabHeight, button.objectName())
        self.assertEqual(plus.text(), "+")
        self.assertEqual(
            plus.toolTip(), "Insert a Part Studio, Assembly, Drawing or Variable Studio"
        )
        # the glyph is big enough to see: its font is larger than the toolbar's own
        self.assertGreater(plus.font().pointSizeF(), mw.font().pointSizeF())


    # -- J1T: a studio's Top, Front and Right are sketch planes (ops#640 round 8) ---------------------

    def selectAsTheFeaturesList(self, doc, obj):
        """A Features list row's selection: from the top-level object down
        (FeaturesView::pushSelection), as the tree selects."""
        Gui.Selection.clearSelection()
        parents = obj.Parents
        if parents:
            Gui.Selection.addSelection(doc.Name, parents[0][0].Name, parents[0][1])
        else:
            Gui.Selection.addSelection(doc.Name, obj.Name)
        pump(0.3)

    def originPlane(self, container, role):
        return [f for f in container.Origin.OriginFeatures if f.Role == role][0]

    def newSketch(self, doc, closeModals):
        """PartDesign_NewSketch; any modal it shows is recorded and closed, so a regression fails
        instead of hanging. Returns the new sketch (or None) and the modals' titles."""
        from PySide import QtCore

        modals = []

        def close():
            modal = QtWidgets.QApplication.activeModalWidget()
            if modal is not None:
                modals.append(modal.windowTitle())
                modal.reject()

        before = {o.Name for o in doc.Objects}
        if closeModals:
            for delay in (800, 1600, 2400):
                QtCore.QTimer.singleShot(delay, close)
        Gui.runCommand("PartDesign_NewSketch")
        pump(2.6 if closeModals else 0.5)
        new = [
            o for o in doc.Objects if o.Name not in before and o.isDerivedFrom("Sketcher::SketchObject")
        ]
        return (new[0] if new else None), modals

    def endEdit(self, doc):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        gdoc = Gui.getDocument(doc.Name)
        if gdoc.getInEdit():
            gdoc.resetEdit()
        pump(0.3)

    def assertOnPlane(self, sketch, plane):
        self.assertEqual(len(sketch.AttachmentSupport), 1, sketch.AttachmentSupport)
        self.assertEqual(sketch.AttachmentSupport[0][0], plane)
        self.assertEqual(sketch.MapMode, "FlatFace")
        sketch.recompute()
        expected = plane.getGlobalPlacement()
        self.assertTrue(
            sketch.getGlobalPlacement().isSame(expected, 1e-9),
            (sketch.getGlobalPlacement(), expected),
        )

    def studiosByStdNewAndPlus(self):
        """Std_New (Part Studio 1 with its "Part 1") and "+" > Create Part Studio (empty)."""
        Gui.activateWorkbench("PartDesignWorkbench")
        doc = self.stdNew()
        [part1] = [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")]
        studio1 = part1.getParentGeoFeatureGroup()
        name = GuiTabs.create(doc, "PartStudio")
        pump(0.3)
        self.assertEqual(GuiTabs.activeTab(doc), name)
        return doc, studio1, part1, doc.getObject(name)

    def testTopRowIsASketchPlane(self):
        """J1T A: in a new, empty Part Studio, New Sketch with nothing selected makes its "Part N"
        and waits for a plane; the Features list's Top row (the studio's own XY plane) is taken,
        written as the Body's own XY plane (the same place). In Part Studio 1 (Std_New) too."""
        doc, studio1, part1, studio2 = self.studiosByStdNewAndPlus()
        Gui.Selection.clearSelection()
        sketch, modals = self.newSketch(doc, True)
        self.assertEqual(modals, [])
        self.assertIsNotNone(sketch)
        body = sketch.getParentGeoFeatureGroup()
        self.assertEqual(body.getParentGeoFeatureGroup(), studio2)
        self.assertFalse(sketch.AttachmentSupport)
        self.selectAsTheFeaturesList(doc, self.originPlane(studio2, "XY_Plane"))
        self.assertOnPlane(sketch, self.originPlane(body, "XY_Plane"))
        self.endEdit(doc)

        done, refusal = GuiTabs.switchTo(doc, studio1.Name)
        self.assertTrue(done, refusal)
        pump(0.3)
        Gui.Selection.clearSelection()
        sketch, modals = self.newSketch(doc, True)
        self.assertEqual(modals, [])
        self.assertEqual(sketch.getParentGeoFeatureGroup(), part1)
        # The studio's Front, picked as an object in the view would be
        front = self.originPlane(studio1, "XZ_Plane")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, front.Name)
        pump(0.3)
        self.assertOnPlane(sketch, self.originPlane(part1, "XZ_Plane"))

    def testTopSelectedThenNewSketch(self):
        """J1T B: Top selected first (the Features list's row), then New Sketch: in the empty Part
        Studio 2, no "Active Body Required" question, a Body "Part N" made there and the sketch on
        its XY plane; in Part Studio 1, the sketch in "Part 1" on its Front."""
        doc, studio1, part1, studio2 = self.studiosByStdNewAndPlus()
        undoCount = doc.UndoCount
        self.selectAsTheFeaturesList(doc, self.originPlane(studio2, "XY_Plane"))
        sketch, modals = self.newSketch(doc, True)
        self.assertEqual(modals, [])
        self.assertIsNotNone(sketch)
        body = sketch.getParentGeoFeatureGroup()
        self.assertTrue(body.isDerivedFrom("PartDesign::Body"))
        self.assertEqual(body.getParentGeoFeatureGroup(), studio2)
        self.assertTrue(body.Label.startswith("Part "), body.Label)
        self.assertOnPlane(sketch, self.originPlane(body, "XY_Plane"))
        self.assertIsNotNone(Gui.getDocument(doc.Name).getInEdit())
        self.endEdit(doc)
        self.assertEqual(doc.UndoCount, undoCount + 1)  # the Body with the sketch, one step

        done, refusal = GuiTabs.switchTo(doc, studio1.Name)
        self.assertTrue(done, refusal)
        pump(0.3)
        self.selectAsTheFeaturesList(doc, self.originPlane(studio1, "XZ_Plane"))
        sketch, modals = self.newSketch(doc, True)
        self.assertEqual(modals, [])
        self.assertEqual(sketch.getParentGeoFeatureGroup(), part1)
        self.assertOnPlane(sketch, self.originPlane(part1, "XZ_Plane"))

    def testRedoOfCreatePartStudioShowsIt(self):
        """J1T: the redo of "Create Part Studio" brings the tab back and shows it; the undo of a
        tab's delete made in that tab too."""
        self.model(assembly=False)
        self.switch("*")
        name = GuiTabs.create(self.doc, "PartStudio")
        pump(0.2)
        undo()
        pump(0.3)
        self.assertIsNone(self.doc.getObject(name))
        self.assertNotEqual(GuiTabs.activeTab(self.doc), name)
        redo()
        pump(0.5)
        self.assertIsNotNone(self.doc.getObject(name))
        self.assertEqual(GuiTabs.activeTab(self.doc), name)
        self.assertEqual(GuiTabs.tabOfView(Gui.ActiveDocument.ActiveView), name)

        self.switch("Part")  # deleted from its own tab: the step is that tab's
        done, message, _users = GuiTabs.deleteTab(self.doc, "Part")
        self.assertTrue(done, message)
        pump(0.3)
        self.assertNotEqual(GuiTabs.activeTab(self.doc), "Part")
        undo()
        pump(0.5)
        self.assertEqual(GuiTabs.activeTab(self.doc), "Part")

    def testStudioTopForABodyOffItsOrigin(self):
        """RT-2: a Body placed 7 mm up in Part Studio 2: the Sketch plane field takes the studio's
        own Top unmapped (attached to it directly), and the sketch lies on it at global z = 0."""
        doc, studio1, part1, studio2 = self.studiosByStdNewAndPlus()
        body = doc.addObject("PartDesign::Body", "Offset")
        studio2.addObject(body)
        body.Placement.Base = V(0, 0, 7)
        doc.recompute()
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        pump(0.2)
        Gui.Selection.clearSelection()
        sketch, modals = self.newSketch(doc, True)
        self.assertEqual(modals, [])
        self.assertEqual(sketch.getParentGeoFeatureGroup(), body)
        top = self.originPlane(studio2, "XY_Plane")
        self.selectAsTheFeaturesList(doc, top)
        self.assertOnPlane(sketch, top)
        self.assertAlmostEqual(sketch.getGlobalPlacement().Base.z, 0, 9)


# FreeCAD-CH, ops#640 P11: under the Onshape keymap the Start view is Onshape's Documents page:
# New, Open and the recent documents, shown whenever no document is open, and gone once one is.
START = "User parameter:BaseApp/Preferences/Mod/Start"



def page():
    """The Start view while it is shown, else None."""
    view = Gui.getMainWindow().findChild(QtWidgets.QWidget, "StartView")
    return view if view is not None and view.isVisible() else None


class TestDocumentsPageGui(unittest.TestCase):
    def setUp(self):
        if not Gui.DocumentTabs.isOn():
            self.skipTest("the Documents page is the Onshape keymap's")
        if "Start_Start" not in Gui.listCommands():
            import StartGui  # noqa: F401
        self.docs = []
        self.closeAll()
        self.closePage()

    def tearDown(self):
        App.ParamGet(START).RemBool("DocumentsPageInScripts")
        self.closeAll()
        self.closePage()

    def closeAll(self):
        for name in list(App.listDocuments()):
            App.closeDocument(name)
        pump(0.2)

    def closePage(self):
        view = page()
        if view is not None:
            sub = view.parentWidget()
            while sub is not None and not isinstance(sub, QtWidgets.QMdiSubWindow):
                sub = sub.parentWidget()
            (sub or view).close()
            pump(0.2)

    def showPage(self):
        Gui.runCommand("Start_Start")
        pump(0.5)
        view = page()
        self.assertIsNotNone(view, "Expected the Documents page")
        return view

    def testThePageShowsNewOpenAndTheRecentDocuments(self):
        view = self.showPage()
        self.assertEqual(view.windowTitle(), "Documents")
        row = view.findChild(QtWidgets.QWidget, "CreateNewRow")
        buttons = [b for b in row.findChildren(QtWidgets.QPushButton) if b.isVisibleTo(view)]
        self.assertEqual(
            sorted(b.objectName() for b in buttons), ["DocumentsPageNew", "DocumentsPageOpen"]
        )
        # No first-start page, examples or footer ("Do not show again", "First Start Setup")
        self.assertEqual(
            [c for c in view.findChildren(QtWidgets.QCheckBox) if c.isVisibleTo(view)], []
        )
        labels = [l.text() for l in view.findChildren(QtWidgets.QLabel) if l.isVisibleTo(view)]
        self.assertFalse(any("Examples" in t for t in labels), labels)
        self.assertTrue(any("Recent" in t for t in labels) or not labels, labels)

    def testNewDocumentTakesThePagesPlace(self):
        view = self.showPage()
        view.findChild(QtWidgets.QPushButton, "DocumentsPageNew").click()
        pump(0.5)
        self.assertEqual(len(App.listDocuments()), 1)
        self.assertIsNone(page(), "Expected the page gone once a document is open")

    def testCtrlNTakesThePagesPlace(self):
        self.showPage()
        Gui.runCommand("Std_New")
        pump(0.5)
        self.assertEqual(len(App.listDocuments()), 1)
        self.assertIsNone(page(), "Expected the page gone once a document is open")

    def testClosingTheLastDocumentShowsThePage(self):
        App.ParamGet(START).SetBool("DocumentsPageInScripts", True)
        first = App.newDocument("DocumentsPageA")
        second = App.newDocument("DocumentsPageB")
        pump(0.3)
        App.closeDocument(first.Name)
        pump(0.5)
        self.assertIsNone(page(), "Expected no page while a document is open")
        App.closeDocument(second.Name)
        pump(0.5)
        view = page()
        self.assertIsNotNone(view, "Expected the Documents page once the last document closed")
        self.assertEqual(view.windowTitle(), "Documents")

    def testNoPageInAScriptRun(self):
        """The GUI test runs (a script on the command line) close documents all the time."""
        App.newDocument("DocumentsPageC")
        pump(0.3)
        self.closeAll()
        pump(0.3)
        self.assertIsNone(page())
