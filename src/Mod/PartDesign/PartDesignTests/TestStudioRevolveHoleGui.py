# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#640 (walk bugs 1): Revolve, Groove and Hole in a studio make owners
#
# The Windows walk (ops#640, 2026-11-14) found Revolve's "Add" building a new part, a Hole on the
# plate failing with "the active Body does not contain a base shape", a Hole landing on the wrong
# part, and its "Through all" freezing the GUI. All of it came from one cause: Revolve, Groove
# and Hole kept the per-Body command path, so they went into the active Body (the studio's empty
# first part, or the last part made) instead of becoming studio features that act on the part
# their tool meets, as Extrude does (TestStudioFeatureGui).
#
# Designed geometry only: two 20 x 20 x 10 boxes, A (x 0..20) and B (x 30..50), in the studio S
# (TestStudioFeatureGui.twoBoxStudio). Expected volumes come from the boxes and the tools.

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
import PartDesign
from PySide import QtWidgets

from PartDesignTests.TestExpressionFieldsGui import pump, waitFor
from PartDesignTests.TestStudio import xyPlane
from PartDesignTests.TestStudioFeatureGui import QA, StudioDialog, twoBoxStudio

V = App.Vector


class TestStudioRevolveHoleGui(StudioDialog, unittest.TestCase):
    def setUp(self):
        self.openStudio(*twoBoxStudio("StudioRevolveHoleGui"))

    def runOwner(self, command, profile, typeId, active):
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", self.body(active) if active else None)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, profile.Name)
        before = set(self.objects())
        Gui.runCommand(command)
        self.waitForPanel()
        made = [self.doc.getObject(n) for n in set(self.objects()) - before]
        made = [o for o in made if o.TypeId == typeId and not getattr(o, "StudioOwner", None)]
        self.assertEqual(len(made), 1, [o.Name for o in made])
        owner = made[0]
        bodies = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"]
        self.assertFalse([b.Name for b in bodies if owner in b.Group], "the feature is in a Body")
        self.assertIn(owner.Name, self.entries(), "the feature is no studio feature")
        return owner

    def circleInA(self, name, centre, radius):
        """A sketch in Body A on A's top plane (z = 10), one circle."""
        body = self.body("A")
        s = body.newObject("Sketcher::SketchObject", name)
        s.AttachmentSupport = xyPlane(body)
        s.MapMode = "FlatFace"
        s.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        s.addGeometry(Part.Circle(V(centre[0], centre[1], 0), V(0, 0, 1), radius))
        self.doc.recompute()
        return s

    def depthType(self, text):
        combo = self.visible(QtWidgets.QComboBox, "DepthType")
        self.assertIsNotNone(combo, "no Depth type box")
        combo.setCurrentIndex(combo.findText(text))
        pump(0.5)

    # ------------------------------------------------------------------------------- Hole
    def testHoleOnBCutsBNotTheActivePart(self):
        """A Hole whose sketch is in A, with A active, over B: an owner cutting B only (the walk's
        finding 4: it went into the active part and cut nothing there, no error)."""
        owner = self.runOwner("PartDesign_Hole", self.circleInA("HoleSk", (40, 10), 2), "PartDesign::Hole", "A")
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(PartDesign.studioScopeIds(owner), ["B"])
        self.assertAlmostEqual(self.volume("A"), QA, places=4)
        self.assertLess(self.volume("B"), QA - 1)

    def testHoleThroughAll(self):
        """Through all from the panel, with no part active: B loses pi r^2 * 10 (the walk's
        findings 2 and 3: "no base shape", then the GUI froze)."""
        owner = self.runOwner("PartDesign_Hole", self.circleInA("HoleSk", (40, 10), 2), "PartDesign::Hole", None)
        self.depthType("Through all")
        diameter = self.visible(QtWidgets.QWidget, "Diameter")
        diameter.setProperty("rawValue", 4.0)
        pump(0.5)
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(PartDesign.studioScopeIds(owner), ["B"])
        self.assertAlmostEqual(self.volume("A"), QA, places=4)
        self.assertAlmostEqual(self.volume("B"), QA - math.pi * 4 * 10, places=3)

    def testHoleOverNothingFailsLoudly(self):
        """Over no part: no scope, the feature fails loudly (Onshape's Remove with nothing to cut)."""
        owner = self.runOwner("PartDesign_Hole", self.circleInA("HoleSk", (25, 10), 2), "PartDesign::Hole", "A")
        self.close(ok=True)
        self.assertEqual(PartDesign.studioScopeIds(owner), [])
        self.assertFalse(owner.isValid())
        self.assertVolumes(A=QA, B=QA)

    # ---------------------------------------------------------------------------- Revolve
    def testRevolveOnAsTopAdds(self):
        """A 6 x 6 profile in B on the XZ plane at u 0..6, v 10..16, about the sketch's vertical
        axis: a cylinder r 6 h 6 on A's top face (global z axis). The axis picked in the panel:
        Add, scope A (the walk's finding 1: "Add" became a new part). A = QA + pi 36 * 6."""
        body = self.body("B")
        s = body.newObject("Sketcher::SketchObject", "BossSk")
        s.AttachmentSupport = [(body.Origin.OriginFeatures[4], "")]
        s.MapMode = "FlatFace"
        pts = [V(0, 10, 0), V(6, 10, 0), V(6, 16, 0), V(0, 16, 0)]
        for i in range(4):
            s.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
        self.doc.recompute()
        owner = self.runOwner("PartDesign_Revolution", s, "PartDesign::Revolution", "B")
        axis = self.visible(QtWidgets.QComboBox, "axis")
        self.assertIsNotNone(axis, "no axis box")
        texts = [axis.itemText(i) for i in range(axis.count())]
        vertical = [i for i, t in enumerate(texts) if "Vertical" in t]
        self.assertTrue(vertical, texts)
        axis.setCurrentIndex(vertical[0])
        axis.activated.emit(vertical[0])  # a click's signal: the box acts on activated only
        pump(0.5)
        self.waitForResult("Add")
        self.assertEqual(self.ticks(), [("A", True), ("B", False)])
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(PartDesign.studioScopeIds(owner), ["A"])
        self.assertEqual(self.madeParts(owner), [])
        self.assertAlmostEqual(self.volume("A"), QA + math.pi * 36 * 6, places=3)
        self.assertAlmostEqual(self.volume("B"), QA, places=4)

    # ------------------------------------------------------- the per-Body path's freeze
    def testThroughAllInABodyWithoutBaseReturns(self):
        """The per-Body path (a studio with no list and StudioListOnFirstUse off, the test hook):
        a Hole in an empty Body E, its sketch on A's top. Choosing Through all made Hole::onChanged
        throw "Base property not set" out of the panel's slot, and the GUI froze (ops#782). Now
        the choice returns at once and the Hole fails at its recompute. Run behind a timeout:
        before the fix it never returns."""
        group = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        group.SetBool("StudioListOnFirstUse", False)
        doc, studio = twoBoxStudio("HoleNoBase")
        try:
            empty = doc.addObject("PartDesign::Body", "E")
            studio.addObject(empty)
            a = doc.getObject("A")
            s = empty.newObject("Sketcher::SketchObject", "HoleSk")
            s.AttachmentSupport = xyPlane(a)
            s.MapMode = "FlatFace"
            s.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
            s.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 3))
            doc.recompute()
            App.setActiveDocument(doc.Name)
            Gui.setActiveDocument(doc.Name)
            Gui.getDocument(doc.Name).ActiveView.setActiveObject("pdbody", empty)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, s.Name)
            Gui.runCommand("PartDesign_Hole")
            self.waitForPanel()
            holes = [o for o in empty.Group if o.TypeId == "PartDesign::Hole"]
            self.assertEqual(len(holes), 1, [o.Name for o in empty.Group])
            self.depthType("Through all")
            self.assertEqual(holes[0].DepthType, "ThroughAll")
            self.assertFalse(holes[0].isValid())
            self.assertAlmostEqual(a.Shape.Volume, QA, places=4)
        finally:
            group.RemBool("StudioListOnFirstUse")
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
                pump()
            App.closeDocument(doc.Name)
            pump()
