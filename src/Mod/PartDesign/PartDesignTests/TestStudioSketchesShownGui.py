# SPDX-License-Identifier: LGPL-2.1-or-later
"""A hidden part leaves its studio's sketches and planes shown (FreeCAD-CH ops#654 P3a, report
20, notes/parts-design.md 3.4 and probe C3).

In Onshape a part studio's sketches and planes belong to the studio: hiding a part hides its solid
only. A Body still claims its sketches and datums, so their selection paths stay
Studio.Body.Sketch.; while the Body is hidden a switch after its mode switch shows them
(ViewProviderBody.cpp, updateStudioShown), and Gui::ViewProviderDocumentObject picks and
highlights them through it. Checked in the scene graph, not by screenshot: a node is drawn when a
search that follows only the active child of each switch reaches it.

Designed geometry: a studio (an App::Part, or the document's top level) with Body A, a 20 x 10 x 5
pad on SketchA at z = 0 and a datum plane at z = 7, and Body B, a 10 x 10 x 5 pad at x = 100.
Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PartDesignTests.Scenarios import models
from PartDesignTests.TestExpressionFieldsGui import pump

V = App.Vector


def coin():
    from pivy import coin as module

    return module


def drawnPaths(view, node):
    """The paths from the view's scene to node that drawing follows (each switch's active child
    only)."""
    search = coin().SoSearchAction()
    search.setNode(node)
    search.setInterest(coin().SoSearchAction.ALL)
    search.setSearchingAll(False)
    search.apply(view.getSceneGraph())
    paths = search.getPaths()
    return [paths[i] for i in range(paths.getLength())]


def inScene(view, node):
    """node is somewhere in the view's scene, drawn or not."""
    search = coin().SoSearchAction()
    search.setNode(node)
    search.setSearchingAll(True)
    search.apply(view.getSceneGraph())
    return search.getPath() is not None


class StudioSketchesCase(unittest.TestCase):
    inPart = True

    def setUp(self):
        Gui.activateWorkbench("PartDesignWorkbench")
        self.doc = models.newDocument("TestStudioSketchesShownGui")
        self.gdoc = Gui.getDocument(self.doc.Name)
        self.bodyA = self.doc.addObject("PartDesign::Body", "BodyA")
        self.bodyB = self.doc.addObject("PartDesign::Body", "BodyB")
        self.studio = None
        if self.inPart:
            self.studio = self.doc.addObject("App::Part", "Studio")
            self.studio.addObject(self.bodyA)
            self.studio.addObject(self.bodyB)
        self.sketchA = models.sketch(self.doc, "SketchA", models.rectangle(0, 0, 20, 10), self.bodyA)
        self.padA = models.pad(self.bodyA, self.sketchA, 5, "PadA")
        self.datum = self.bodyA.newObject("PartDesign::Plane", "DatumA")
        self.datum.AttachmentSupport = [(models.originFeature(self.bodyA, "XY_Plane"), "")]
        self.datum.MapMode = "FlatFace"
        self.datum.AttachmentOffset = App.Placement(V(0, 0, 7), App.Rotation())
        sketchB = models.sketch(self.doc, "SketchB", models.rectangle(100, 0, 110, 10), self.bodyB)
        self.padB = models.pad(self.bodyB, sketchB, 5, "PadB")
        self.doc.recompute()
        for obj in (self.padA, self.datum, self.padB):
            self.assertTrue(obj.isValid(), obj.getStatusString())
        # The user shows the pad's sketch again (a feature's sketch hides when the feature uses it)
        self.sketchA.ViewObject.Visibility = True
        self.datum.ViewObject.Visibility = True
        pump(0.2)
        self.view = self.gdoc.ActiveView
        self.assertIsNotNone(self.view, "no 3D view")

    def tearDown(self):
        Gui.Selection.clearSelection()
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        pump(0.1)

    def drawn(self, obj):
        """obj's own switch is on and the drawing reaches its root once."""
        vp = obj.ViewObject
        count = len(drawnPaths(self.view, vp.RootNode))
        self.assertLessEqual(count, 1, f"{obj.Name} is drawn {count} times")
        return count == 1 and vp.SwitchNode.whichChild.getValue() >= 0

    def assertDrawn(self, objs, drawn=True):
        for obj in objs:
            self.assertEqual(self.drawn(obj), drawn, f"{obj.Name} drawn: expected {drawn}")

    def hideA(self, how):
        if how == "property":
            self.bodyA.ViewObject.Visibility = False
        else:
            self.bodyA.ViewObject.hide()
        pump(0.1)
        self.assertFalse(self.bodyA.ViewObject.isVisible())
        self.assertFalse(self.bodyA.ViewObject.Visibility)

    def showA(self, how):
        if how == "property":
            self.bodyA.ViewObject.Visibility = True
        else:
            self.bodyA.ViewObject.show()
        pump(0.1)
        self.assertTrue(self.bodyA.ViewObject.isVisible())

    def runHideShowToggle(self):
        studioOwned = (self.sketchA, self.datum)
        self.assertDrawn(studioOwned + (self.padA, self.padB))
        for how in ("property", "call"):
            self.hideA(how)
            # The part's solid goes; the studio's sketch and plane stay, still in Body A
            self.assertDrawn((self.padA,), drawn=False)
            self.assertTrue(inScene(self.view, self.padA.ViewObject.RootNode))
            self.assertDrawn(studioOwned + (self.padB,))
            self.assertIn(self.sketchA, self.bodyA.Group)
            # The sketch's own visibility still decides
            self.sketchA.ViewObject.Visibility = False
            pump(0.1)
            self.assertDrawn((self.sketchA,), drawn=False)
            self.assertDrawn((self.datum,))
            self.sketchA.ViewObject.Visibility = True
            pump(0.1)
            self.assertDrawn((self.sketchA,))
            # Shown again: everything once, through the Body's mode switch
            self.showA(how)
            self.assertDrawn(studioOwned + (self.padA, self.padB))
            self.sketchA.ViewObject.Visibility = False
            pump(0.1)
            self.assertDrawn((self.sketchA,), drawn=False)
            self.sketchA.ViewObject.Visibility = True
            pump(0.1)
            self.assertDrawn((self.sketchA,))

    def topViewObject(self):
        return (self.studio or self.bodyA).ViewObject

    def prefix(self):
        return "BodyA." if self.studio else ""

    def runPathsWhileHidden(self):
        """Hidden, the sketch's edge highlights through the Body's path, and a click on the
        datum plane names it through the Body (no wrong element of the hidden Body)."""
        self.hideA("property")
        vp = self.topViewObject()
        for sub, wantsDetail in (("SketchA.Edge1", True), ("SketchA.", False)):
            path = coin().SoPath(16)
            path.ref()
            det = vp.getDetailPath(self.prefix() + sub, path, True)
            self.assertTrue(path.containsNode(self.sketchA.ViewObject.RootNode), sub)
            self.assertTrue(path.containsNode(self.bodyA.ViewObject.RootNode), sub)
            if wantsDetail:
                self.assertIsNotNone(det, sub)
            path.unref()
        pick = coin().SoRayPickAction(coin().SbViewportRegion(400, 400))
        # Over the hidden pad, inside the plane, away from the sketch's lines; the plane at z = 7
        # is nearer than the sketch at z = 0
        pick.setRay(coin().SbVec3f(5, 3, 50), coin().SbVec3f(0, 0, -1))
        pick.apply(self.view.getSceneGraph())
        point = pick.getPickedPoint()
        self.assertIsNotNone(point, "nothing picked over the hidden part")
        self.assertAlmostEqual(point.getPoint()[2], 7, places=4)
        name = vp.getElementPicked(point)
        self.assertIsNotNone(name)
        self.assertTrue(name.startswith(self.prefix() + "DatumA."), name)


class TestStudioSketchesShownGui(StudioSketchesCase):
    """The studio is an App::Part."""

    def testHiddenPartLeavesItsSketchAndPlaneShown(self):
        self.runHideShowToggle()

    def testHiddenPartsSketchAndPlaneArePickedThroughTheBody(self):
        self.runPathsWhileHidden()


class TestTopLevelStudioSketchesShownGui(StudioSketchesCase):
    """The studio is the document's top level (Bodies in no App::Part)."""

    inPart = False

    def testHiddenPartLeavesItsSketchAndPlaneShown(self):
        self.runHideShowToggle()

    def testHiddenPartsSketchAndPlaneArePickedThroughTheBody(self):
        self.runPathsWhileHidden()


if __name__ == "__main__":
    unittest.main()
