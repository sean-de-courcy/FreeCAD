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

"""The sketch dialog's Sketch plane field, with Onshape's keymap (FreeCAD-CH, ops#640, rank 2).

- The sketch dialog has a Sketch plane box at the top: one reference field on the sketch's
  AttachmentSupport. A pick of a planar face or a plane replaces it (Flat face, MapOrigin Body)
  and disarms the field; the 2D geometry stays as it is in the sketch, so it rides along with the
  plane, and the editing view follows.
- While a sketch is edited the model is shown rolled back to it: the solid before it is drawn, a
  solid after it is not, in the scene only (no Visibility changes); closing the sketch puts the
  scene back.
- New Sketch with nothing selected opens a sketch with no plane (hands-on C-1): the field armed,
  a "Select a sketch plane" banner, the Body's planes shown, and a sketch tool started before a
  pick cancelled (Onshape greys its sketch tools until a plane is picked).
- The field takes only what the sketch may link: its own Body's or a studio sibling's (a loose
  Part feature is refused). A pick puts the sketch on the plane itself: no attachment offset and
  no flip.
- Attach Sketch with a sketch and a plane selected attaches at once, without its two lists; with
  the sketch alone it opens the sketch with the field armed.

Designed model: a Body with Pad (a 10 x 20 rectangle at the origin, length 5: its top face is the
plane z = 5) and a second sketch holding a circle of radius 2 at (3, 4). On the top face from the
Body's origin the circle's centre is at (3, 4, 5); on the XZ plane the sketch's placement is the
plane's."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models

V = App.Vector
KEYMAP = "User parameter:BaseApp/Preferences/General"  # the preference Keymap (ForkKeymap)
PARTDESIGN = "User parameter:BaseApp/Preferences/Mod/PartDesign"


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def visibleChild(name):
    for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget, name):
        if widget.isVisible():
            return widget
    return None


def closeModals(seen):
    """Rejects every modal dialog shown, and records it (a list would block the test)."""
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if isinstance(widget, QtWidgets.QDialog) and widget.isVisible() and widget.isModal():
            seen.append(widget.windowTitle())
            widget.reject()


def topFace(shape, z):
    """The 1-based index of the planar face of the shape lying in the plane at height z."""
    for i, face in enumerate(shape.Faces):
        box = face.BoundBox
        if abs(box.ZMin - z) < 1e-9 and abs(box.ZMax - z) < 1e-9:
            return i + 1
    raise ValueError(z)


class TestSketchPlaneGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gui.getMainWindow().show()
        Gui.activateWorkbench("PartDesignWorkbench")
        group = App.ParamGet(KEYMAP)
        cls.savedKeymap = group.GetString("Keymap") if "Keymap" in group.GetStrings() else None
        param = App.ParamGet(PARTDESIGN)
        cls.savedUseAttachment = param.GetBool("NewSketchUseAttachmentDialog", False)
        pump()

    @classmethod
    def tearDownClass(cls):
        group = App.ParamGet(KEYMAP)
        if cls.savedKeymap is None:
            group.RemString("Keymap")
        else:
            group.SetString("Keymap", cls.savedKeymap)
        App.ParamGet(PARTDESIGN).SetBool("NewSketchUseAttachmentDialog", cls.savedUseAttachment)
        pump()

    def setUp(self):
        # The fork's keymap, Onshape, is the default
        App.ParamGet(KEYMAP).RemString("Keymap")
        App.ParamGet(PARTDESIGN).SetBool("NewSketchUseAttachmentDialog", False)
        self.doc = models.newDocument("SketchPlaneGui")
        self.body = models.body(self.doc)
        self.xy = models.originFeature(self.body, "XY_Plane")
        self.xz = models.originFeature(self.body, "XZ_Plane")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        Gui.activateView("Gui::View3DInventor", True)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()

    def tearDown(self):
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
            pump(0.3)
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump(0.2)
        Gui.Selection.clearSelection()
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        pump(0.2)

    # -- the model --------------------------------------------------------------------------------

    def onPlane(self, sketch, plane):
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
        return sketch

    def padModel(self):
        """Sketch on XY with a 10 x 20 rectangle, padded 5; the Pad shown."""
        profile = self.onPlane(
            models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 20), self.body), self.xy
        )
        pad = models.pad(self.body, profile, 5)
        self.doc.recompute()
        return pad

    def circleSketch(self, name="Circle"):
        sketch = self.onPlane(
            models.sketch(self.doc, name, [models.circle(3, 4, 2)], self.body), self.xy
        )
        self.doc.recompute()
        return sketch

    # -- the dialog -------------------------------------------------------------------------------

    def openSketch(self, sketch):
        Gui.ActiveDocument.setEdit(sketch.Name)
        pump(1.0)
        self.assertTrue(Gui.ActiveDocument.getInEdit(), "the sketch isn't in edit")

    def planeField(self):
        field = visibleChild("fieldAttachmentSupport")
        self.assertIsNotNone(field, "no Sketch plane field in the sketch dialog")
        return field

    def pick(self, obj, sub=""):
        """A pick in the 3D view, on the Body's path, as the view makes it."""
        if obj in self.body.Origin.OriginFeatures:
            path = self.body.Origin.Name + "." + obj.Name + "."
        else:
            path = obj.Name + "." + sub
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, path)
        pump(0.5)

    def supportOf(self, sketch):
        refs = sketch.AttachmentSupport
        self.assertEqual(len(refs), 1, refs)
        obj, subs = refs[0]
        return obj, [s for s in subs if s]

    # -- the tests --------------------------------------------------------------------------------

    def testTheSketchDialogHasTheSketchPlaneBox(self):
        """The sketch dialog's Sketch plane box lists the sketch's plane, XY, and isn't armed."""
        sketch = self.circleSketch()
        self.openSketch(sketch)
        self.assertIsNotNone(visibleChild("sketchPlaneBox"))
        field = self.planeField()
        entries = field.findChild(QtWidgets.QListWidget, "entries")
        self.assertEqual(entries.count(), 1)
        self.assertIn(self.xy.Label, entries.item(0).text())
        self.assertFalse(field.property("armed"))

    def testAPickedFaceTakesTheSketchAndItsGeometryAlong(self):
        """Armed, the field takes the Pad's top face (z = 5): the sketch is on that face, Flat
        face from the Body's origin, its circle unchanged in the sketch (centre (3, 4), radius 2)
        and so at (3, 4, 5) in the model; the editing view is on the face; the field disarms."""
        pad = self.padModel()
        sketch = self.circleSketch()
        face = topFace(pad.Shape, 5.0)
        self.openSketch(sketch)
        field = self.planeField()
        field.setProperty("armed", True)
        pump(0.3)
        self.assertTrue(field.property("armed"))

        self.pick(pad, "Face%d" % face)

        obj, subs = self.supportOf(sketch)
        self.assertEqual(obj.Name, pad.Name)
        self.assertEqual(len(subs), 1, subs)
        self.assertTrue(subs[0].endswith("Face%d" % face), subs)
        self.assertEqual(sketch.MapMode, "FlatFace")
        self.assertEqual(sketch.MapOrigin, "Body")
        self.assertFalse(field.property("armed"), "the field stayed armed after the pick")
        # Onshape's words for the face (ops#640 round 6, J10), not "Pad:Face6"
        entries = field.findChild(QtWidgets.QListWidget, "entries")
        pump(0.3)
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.item(0).text(), "Face of %s" % pad.Label)

        self.assertAlmostEqual(sketch.Placement.Base.z, 5.0, places=9)
        normal = sketch.Placement.Rotation.multVec(V(0, 0, 1))
        self.assertAlmostEqual((normal - V(0, 0, 1)).Length, 0.0, places=9)
        circle = sketch.Geometry[0]
        self.assertAlmostEqual((circle.Center - V(3, 4, 0)).Length, 0.0, places=9)
        self.assertAlmostEqual(circle.Radius, 2.0, places=9)
        centre = sketch.getGlobalPlacement().multVec(circle.Center)
        self.assertAlmostEqual((centre - V(3, 4, 5)).Length, 0.0, places=9)

        editing = App.Placement(Gui.ActiveDocument.EditingTransform)
        self.assertTrue(editing.isSame(sketch.getGlobalPlacement(), 1e-9), editing)

    def testAPickedPlaneTakesTheSketch(self):
        """The XZ plane picked: the sketch's placement is the plane's, its geometry unchanged."""
        sketch = self.circleSketch()
        self.openSketch(sketch)
        field = self.planeField()
        field.setProperty("armed", True)
        pump(0.3)
        self.pick(self.xz)
        obj, subs = self.supportOf(sketch)
        self.assertEqual(obj.Name, self.xz.Name)
        self.assertEqual(subs, [])
        self.assertTrue(sketch.Placement.isSame(self.xz.Placement, 1e-9), sketch.Placement)
        circle = sketch.Geometry[0]
        self.assertAlmostEqual((circle.Center - V(3, 4, 0)).Length, 0.0, places=9)
        editing = App.Placement(Gui.ActiveDocument.EditingTransform)
        self.assertTrue(editing.isSame(self.xz.Placement, 1e-9), editing)

    def testALostPlaneShowsRed(self):
        """The sketch is on the Pad's top face and the Pad goes: the box's red line says the
        plane is missing; a sketch on a plane has none."""
        pad = self.padModel()
        sketch = models.sketch(self.doc, "OnFace", [models.circle(3, 4, 2)], self.body)
        sketch.AttachmentSupport = [(pad, "Face%d" % topFace(pad.Shape, 5.0))]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        self.openSketch(sketch)
        self.assertIsNone(visibleChild("lostPlane"), "a plane that is there shows as lost")
        Gui.ActiveDocument.resetEdit()
        pump(0.3)

        self.doc.removeObject(pad.Name)
        self.doc.recompute()
        self.assertEqual(sketch.MapMode, "FlatFace")
        self.openSketch(sketch)
        self.assertIsNotNone(visibleChild("lostPlane"), "the lost plane isn't shown")

    def testTheEditShowsTheModelBeforeASketchAFeatureUses(self):
        """Pad2 is made from the circle sketch, on Pad: while the sketch is edited Pad is drawn
        (its Visibility still off) and Pad2 isn't; closing the sketch puts the scene back."""
        pad = self.padModel()
        sketch = self.circleSketch()
        pad2 = models.pad(self.body, sketch, 10, "Pad2")
        self.doc.recompute()
        pad.ViewObject.Visibility = False
        pad2.ViewObject.Visibility = True
        pump(0.2)
        self.assertFalse(pad.ViewObject.isVisible())

        self.openSketch(sketch)
        self.assertTrue(pad.ViewObject.isVisible(), "the model before the sketch isn't shown")
        self.assertFalse(pad.ViewObject.Visibility, "the roll-back changed a Visibility")
        self.assertFalse(pad2.ViewObject.isVisible())

        Gui.ActiveDocument.resetEdit()
        pump(0.5)
        self.assertFalse(pad.ViewObject.isVisible())
        self.assertFalse(pad.ViewObject.Visibility)
        self.assertTrue(pad2.ViewObject.Visibility)
        self.assertTrue(pad2.ViewObject.isVisible())

    def testTheEditHidesALaterSolidTheSketchDoesNotMake(self):
        """Pad2 comes after the circle sketch but is made from another sketch: while the circle
        sketch is edited Pad is drawn and Pad2 isn't, with neither Visibility changed."""
        pad = self.padModel()
        sketch = self.circleSketch()
        other = self.onPlane(
            models.sketch(self.doc, "Other", models.rectangle(20, 0, 30, 10), self.body), self.xy
        )
        pad2 = models.pad(self.body, other, 5, "Pad2")
        self.doc.recompute()
        pad.ViewObject.Visibility = False
        pad2.ViewObject.Visibility = True
        pump(0.2)

        self.openSketch(sketch)
        self.assertTrue(pad.ViewObject.isVisible())
        self.assertFalse(pad.ViewObject.Visibility)
        self.assertFalse(pad2.ViewObject.isVisible(), "the solid after the sketch is shown")
        self.assertTrue(pad2.ViewObject.Visibility, "the roll-back changed a Visibility")

        Gui.ActiveDocument.resetEdit()
        pump(0.5)
        self.assertFalse(pad.ViewObject.isVisible())
        self.assertTrue(pad2.ViewObject.isVisible())

    def testNewSketchWithNothingSelectedWaitsForAPlane(self):
        """New Sketch with nothing selected: the sketch opens with no plane (MapMode Deactivated,
        no support), its Sketch plane field armed, the banner shown, the Body's XZ plane shown,
        and no other dialog. The Line tool started then is cancelled and the field armed again.
        A pick of XZ puts the sketch there and the banner goes."""
        self.padModel()
        before = {o.Name for o in self.doc.Objects}
        seen = []
        QtCore.QTimer.singleShot(2000, lambda: closeModals(seen))
        Gui.runCommand("PartDesign_NewSketch")
        pump(1.0)
        self.assertEqual(seen, [], "a modal dialog opened")
        added = [o for o in self.doc.Objects if o.Name not in before]
        sketches = [o for o in added if o.isDerivedFrom("Sketcher::SketchObject")]
        self.assertEqual(len(sketches), 1, [o.Name for o in added])
        sketch = sketches[0]
        self.assertTrue(Gui.ActiveDocument.getInEdit(), "the new sketch isn't in edit")
        self.assertEqual(sketch.AttachmentSupport, [])
        self.assertEqual(sketch.MapMode, "Deactivated")
        field = self.planeField()
        self.assertTrue(field.property("armed"), "the Sketch plane field isn't armed")
        self.assertIsNotNone(visibleChild("pickPlaneBanner"), "no 'Select a sketch plane' banner")
        self.assertTrue(self.xz.ViewObject.isVisible(), "the planes to pick from aren't shown")

        # A tool before the plane: it ends, and the field is armed again
        Gui.runCommand("Sketcher_CreateLine")
        pump(0.5)
        self.assertTrue(field.property("armed"), "the field wasn't armed again after the tool")
        self.assertEqual(len(sketch.Geometry), 0)

        self.pick(self.xz)
        obj, subs = self.supportOf(sketch)
        self.assertEqual(obj.Name, self.xz.Name)
        self.assertTrue(sketch.Placement.isSame(self.xz.Placement, 1e-9), sketch.Placement)
        self.assertFalse(field.property("armed"))
        self.assertIsNone(visibleChild("pickPlaneBanner"), "the banner stayed after the pick")

    def testAPickPutsTheSketchOnThePlaneItself(self):
        """A sketch on XY with an offset of 7 along z and its flip on: the XZ plane picked, the
        sketch's placement is the plane's, its offset zero and its flip off."""
        sketch = self.circleSketch()
        sketch.AttachmentOffset = App.Placement(V(0, 0, 7), App.Rotation())
        sketch.MapReversed = True
        self.doc.recompute()
        self.assertFalse(sketch.Placement.isSame(self.xy.Placement, 1e-9), sketch.Placement)
        self.openSketch(sketch)
        field = self.planeField()
        field.setProperty("armed", True)
        pump(0.3)
        self.pick(self.xz)
        obj, subs = self.supportOf(sketch)
        self.assertEqual(obj.Name, self.xz.Name)
        self.assertFalse(sketch.MapReversed)
        self.assertTrue(sketch.AttachmentOffset.isSame(App.Placement(), 1e-12))
        self.assertTrue(sketch.Placement.isSame(self.xz.Placement, 1e-9), sketch.Placement)

    def testTheFieldRefusesAFaceOutsideThePartStudio(self):
        """A loose Part box (10 x 10 x 3, outside the Body): its top face (z = 3) is refused,
        the sketch stays on XY and the field stays armed."""
        box = self.doc.addObject("Part::Box", "Loose")
        box.Length, box.Width, box.Height = 10, 10, 3
        self.doc.recompute()
        sketch = self.circleSketch()
        self.openSketch(sketch)
        field = self.planeField()
        field.setProperty("armed", True)
        pump(0.3)
        Gui.Selection.addSelection(self.doc.Name, box.Name, "Face%d" % topFace(box.Shape, 3.0))
        pump(0.5)
        obj, subs = self.supportOf(sketch)
        self.assertEqual(obj.Name, self.xy.Name)
        self.assertTrue(field.property("armed"))

    def testTheEditHidesEveryLaterSolidOnAFaceSketch(self):
        """The circle sketch on Pad's top face (z = 5), then Pad2 from another sketch after it,
        Pad2 shown: opening the sketch shows Pad (its support, by the sketch's own automation)
        and Pad2 isn't drawn; closing the sketch draws Pad2 again, every Visibility as before."""
        pad = self.padModel()
        sketch = models.sketch(self.doc, "OnFace", [models.circle(3, 4, 2)], self.body)
        sketch.AttachmentSupport = [(pad, "Face%d" % topFace(pad.Shape, 5.0))]
        sketch.MapMode = "FlatFace"
        other = self.onPlane(
            models.sketch(self.doc, "Other", models.rectangle(20, 0, 30, 10), self.body), self.xy
        )
        pad2 = models.pad(self.body, other, 5, "Pad2")
        self.doc.recompute()
        pad.ViewObject.Visibility = False
        pad2.ViewObject.Visibility = True
        pump(0.2)

        self.openSketch(sketch)
        self.assertTrue(pad.ViewObject.isVisible(), "the model before the sketch isn't shown")
        self.assertFalse(pad2.ViewObject.isVisible(), "a solid after the sketch is shown")
        # The sketch's own automation shows its support for the edit (TempoVis), and the Body,
        # one solid shown, hides Pad2's Visibility meanwhile; both come back with the edit's end

        Gui.ActiveDocument.resetEdit()
        pump(0.5)
        self.assertTrue(pad2.ViewObject.Visibility, "the edit left a Visibility changed")
        self.assertFalse(pad.ViewObject.Visibility, "the edit left a Visibility changed")
        self.assertTrue(pad2.ViewObject.isVisible())

    def testAttachSketchTakesTheSelectedPlaneWithoutLists(self):
        """Attach Sketch with the circle sketch and the Pad's top face selected: no list opens,
        the sketch is on the face (Flat face, Body origin), its circle's centre at (3, 4, 5)."""
        pad = self.padModel()
        sketch = models.sketch(self.doc, "Free", [models.circle(3, 4, 2)], self.body)
        self.doc.recompute()
        face = topFace(pad.Shape, 5.0)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, sketch.Name + ".")
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, pad.Name + ".Face%d" % face)
        pump(0.2)
        seen = []
        QtCore.QTimer.singleShot(2000, lambda: closeModals(seen))
        Gui.runCommand("Sketcher_MapSketch")
        pump(1.0)
        self.assertEqual(seen, [], "Attach Sketch opened a list")
        obj, subs = self.supportOf(sketch)
        self.assertEqual(obj.Name, pad.Name)
        self.assertTrue(subs and subs[0].endswith("Face%d" % face), subs)
        self.assertEqual(sketch.MapMode, "FlatFace")
        self.assertEqual(sketch.MapOrigin, "Body")
        centre = sketch.getGlobalPlacement().multVec(sketch.Geometry[0].Center)
        self.assertAlmostEqual((centre - V(3, 4, 5)).Length, 0.0, places=9)

    def testAttachSketchWithTheSketchAloneArmsItsField(self):
        """Attach Sketch with only a sketch selected: the sketch opens with its field armed."""
        sketch = self.circleSketch()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, sketch.Name + ".")
        pump(0.2)
        seen = []
        QtCore.QTimer.singleShot(2000, lambda: closeModals(seen))
        Gui.runCommand("Sketcher_MapSketch")
        pump(1.0)
        self.assertEqual(seen, [], "Attach Sketch opened a list")
        self.assertTrue(Gui.ActiveDocument.getInEdit(), "the sketch isn't in edit")
        self.assertTrue(self.planeField().property("armed"))

    def testAttachSketchInTheSketchEditorArmsTheField(self):
        """Attach Sketch while the sketch is edited arms its Sketch plane field, with no list."""
        sketch = self.circleSketch()
        self.openSketch(sketch)
        field = self.planeField()
        self.assertFalse(field.property("armed"))
        seen = []
        QtCore.QTimer.singleShot(2000, lambda: closeModals(seen))
        Gui.runCommand("Sketcher_MapSketch")
        pump(0.5)
        self.assertEqual(seen, [], "Attach Sketch opened a list")
        self.assertTrue(field.property("armed"))

    # -- round 2: a new sketch's Cancel and its greyed tools ---------------------------------------

    def newSketchOn(self, plane=None):
        """PartDesign_NewSketch with `plane` selected (or nothing); returns the new sketch, in edit."""
        before = {o.Name for o in self.doc.Objects}
        Gui.Selection.clearSelection()
        if plane is not None:
            self.pick(plane)
        seen = []
        QtCore.QTimer.singleShot(2000, lambda: closeModals(seen))
        Gui.runCommand("PartDesign_NewSketch")
        pump(1.0)
        self.assertEqual(seen, [], "a modal dialog opened")
        sketches = [
            o
            for o in self.doc.Objects
            if o.Name not in before and o.isDerivedFrom("Sketcher::SketchObject")
        ]
        self.assertEqual(len(sketches), 1, sketches)
        self.assertTrue(Gui.ActiveDocument.getInEdit(), "the new sketch isn't in edit")
        return sketches[0]

    def cancelDialog(self):
        dialog = Gui.Control.activeTaskDialog()
        self.assertIsNotNone(dialog, "no sketch dialog")
        dialog.reject()
        pump(0.5)

    def testCancelRemovesANewSketch(self):
        """Onshape's cancel of a new sketch removes it (hands-on R1): New Sketch on the selected XZ
        plane, a line drawn, Cancel: the sketch is gone, in its own undo step (Ctrl+Z brings it
        back, as Onshape's "Restore")."""
        import Part

        sketch = self.newSketchOn(self.xz)
        name = sketch.Name
        sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        pump(0.2)
        self.cancelDialog()
        self.assertFalse(Gui.ActiveDocument.getInEdit())
        self.assertIsNone(self.doc.getObject(name), "the cancelled new sketch stayed")
        self.assertNotIn(name, [o.Name for o in self.body.Group])
        self.doc.undo()
        pump(0.3)
        self.assertIsNotNone(self.doc.getObject(name), "Ctrl+Z didn't bring the sketch back")

    def testCancelOfANewSketchWithNothingDrawnRemovesIt(self):
        """New Sketch with nothing selected, Cancel before a pick: no sketch is left."""
        sketch = self.newSketchOn()
        name = sketch.Name
        self.cancelDialog()
        self.assertIsNone(self.doc.getObject(name), "the cancelled new sketch stayed")

    def testOkOnANewSketchWithNoPlaneRemovesIt(self):
        """New Sketch with nothing selected, OK before a pick: nothing could be drawn, so the
        sketch goes as a cancelled one does."""
        sketch = self.newSketchOn()
        name = sketch.Name
        dialog = Gui.Control.activeTaskDialog()
        dialog.accept()
        pump(0.5)
        self.assertIsNone(self.doc.getObject(name), "the empty sketch with no plane stayed")

    def testCancelKeepsAnExistingSketch(self):
        """Cancel on a sketch that was there before the edit keeps it (and its circle)."""
        sketch = self.circleSketch()
        self.openSketch(sketch)
        self.cancelDialog()
        self.assertIsNotNone(self.doc.getObject(sketch.Name))
        self.assertEqual(len(sketch.Geometry), 1)

    def testOkKeepsANewSketchOnAPlane(self):
        """OK on a new sketch on the XZ plane keeps it, even empty (only Cancel removes it)."""
        sketch = self.newSketchOn(self.xz)
        name = sketch.Name
        Gui.Control.activeTaskDialog().accept()
        pump(0.5)
        self.assertIsNotNone(self.doc.getObject(name))

    def testTheSketchToolsAreGreyedUntilAPlane(self):
        """Onshape greys the sketch toolbar until the plane is picked (hands-on C-1): with a new
        sketch with no plane, Line and Circle are inactive; after the XZ pick they are active."""
        self.newSketchOn()
        line = Gui.Command.get("Sketcher_CreateLine")
        circle = Gui.Command.get("Sketcher_CreateCircle")
        self.assertFalse(line.isActive(), "Line is active before a plane is picked")
        self.assertFalse(circle.isActive(), "Circle is active before a plane is picked")
        self.pick(self.xz)
        pump(0.3)
        self.assertTrue(line.isActive(), "Line stayed greyed after the pick")
        self.assertTrue(circle.isActive(), "Circle stayed greyed after the pick")


if __name__ == "__main__":
    unittest.main()
