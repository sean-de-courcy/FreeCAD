# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 ranks 20, 21 and 52)

"""Onshape's Revolve fields (hands-on B-5): Full revolve, on by default; unticked, the end type
(Blind, Up to next, Up to face), the angle (30 deg), Flip, Symmetric, and Second end position with
its own end. A Profile field on top. The end types are the class's whatever the Operation (a Groove
set to Add keeps Through all). A new part studio's planes stay shown after the dialog (rank 52).
A preselected axis is kept (rank 21). The Result row's New / Add / Remove / Intersect on a
Revolve, Loft, Sweep and Helix (rank 20, TestOperationRowGui).

Designed model, built by the test: a 20 x 20 x 10 box (-10..10, z -5..5, 4000) and a sketch in the
XZ plane (local y along +Z) of the rectangle x 2..5, z 0..10, revolved about its V axis (the Z
axis): a full turn is the tube r 2..5, 210 pi, its inside half 105 pi; 30 deg of it is 210 pi / 12.
For the rows: a 4 x 4 square at z 0 lofted to z 10, or swept along the Z axis 0..10 (160, its
inside half 80: Add 4080, Remove 3920, Intersect 80); the 2 x 2 square x 2..4, z -4..-2 in the XZ
plane, a helix about the Z axis of pitch 5 and height 5 (one turn, z -4..3, all inside the box):
24 pi (Add 4000, Remove 4000 - 24 pi, Intersect 24 pi; the sweep is approximated, checked to 0.1).
"""

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestDressUpDeleteKeyGui import pump, taskButton, waitFor

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def widget(cls, name):
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
    return found[0] if found else None


def visibleItems(combo):
    """The texts of a combo box's entries its list shows."""
    view = combo.view()
    return [combo.itemText(i) for i in range(combo.count()) if not view.isRowHidden(i)]


class RevolveCase(unittest.TestCase):
    def setUp(self):
        self.docs = []
        Gui.activateWorkbench("PartDesignWorkbench")
        Gui.Selection.clearSelection()

    def tearDown(self):
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump(0.2)
        Gui.Selection.clearSelection()
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        pump(0.2)

    # -- models ---------------------------------------------------------------------------------

    def model(self, kind="Revolution", doc=None, body=None):
        if doc is None:
            doc = models.newDocument("RevolveFields")
            self.docs.append(doc.Name)
        self.doc = doc
        self.body = body or models.body(doc)
        base = models.sketch(doc, "BaseSk", models.rectangle(-10, -10, 10, 10), self.body, z=-5)
        models.pad(self.body, base, 10, name="Base")
        profile = models.sketch(doc, "TubeSk", models.rectangle(2, 0, 5, 10), self.body, placement=XZ)
        feature = self.body.newObject("PartDesign::" + kind, kind)
        feature.Profile = profile
        feature.ReferenceAxis = (profile, ["V_Axis"])
        feature.Angle = 360
        doc.recompute()
        App.setActiveDocument(doc.Name)
        Gui.setActiveDocument(doc.Name)
        pump(0.2)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        self.feature = feature
        return feature

    def edit(self, feature):
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.3)

    def full(self):
        return widget(QtWidgets.QCheckBox, "checkBoxFullRevolve")


class TestRevolveFieldsGui(RevolveCase):
    # -- the tests ------------------------------------------------------------------------------

    def testFullRevolveIsOnAndHidesTheEnd(self):
        """A 360 deg Revolve opens with Full revolve ticked, a Profile field showing its sketch, and
        no end type, angle, Flip, Symmetric or Second end position."""
        self.edit(self.model())
        full = self.full()
        self.assertIsNotNone(full, "no Full revolve box")
        self.assertTrue(full.isChecked())
        self.assertIsNotNone(widget(QtWidgets.QWidget, "fieldProfile"), "no Profile field")
        self.assertIsNone(widget(QtWidgets.QComboBox, "changeMode"))
        self.assertIsNone(widget(QtWidgets.QCheckBox, "checkBoxSymmetric"))
        self.assertIsNone(widget(QtWidgets.QCheckBox, "checkBoxSecondEnd"))
        self.assertIsNone(widget(QtWidgets.QComboBox, "sidesMode"), "the Sides box shows")

    def testUntickingFullRevolveGivesBlind30(self):
        """Full revolve unticked: Blind, 30 deg, one side (210 pi / 12 of the tube, its inside
        half added to the box), the end types Blind / Up to next / Up to face / Up to part / Up to
        vertex, Symmetric and
        Second end position shown. Ticked again: 360, the tube (4000 + 105 pi)."""
        rev = self.model()
        self.edit(rev)
        self.full().click()
        pump(0.3)
        self.assertAlmostEqual(rev.Angle.Value, 30, places=9)
        self.assertEqual(rev.SideType, "One side")
        self.assertEqual(rev.Type, "Angle")
        self.assertAlmostEqual(rev.AddSubShape.Volume, 210 * math.pi / 12, places=4)
        mode = widget(QtWidgets.QComboBox, "changeMode")
        self.assertIsNotNone(mode, "no end type")
        self.assertEqual(
            visibleItems(mode), ["Blind", "Up to next", "Up to face", "Up to part", "Up to vertex"]
        )
        self.assertEqual(mode.currentText(), "Blind")
        self.assertIsNotNone(widget(QtWidgets.QCheckBox, "checkBoxSymmetric"))
        self.assertIsNotNone(widget(QtWidgets.QCheckBox, "checkBoxSecondEnd"))
        self.full().click()
        pump(0.3)
        self.assertAlmostEqual(rev.Angle.Value, 360, places=9)
        self.assertAlmostEqual(self.body.Shape.Volume, 4000 + 105 * math.pi, places=4)

    def testSymmetricAndSecondEnd(self):
        """Symmetric: SideType Symmetric, Second end position hidden. Off, then Second end
        position: Two sides, the second end 30 deg the other way (Onshape's Start angle 330 deg),
        Symmetric hidden: 60 deg of the tube in all."""
        rev = self.model()
        self.edit(rev)
        self.full().click()
        pump(0.3)
        widget(QtWidgets.QCheckBox, "checkBoxSymmetric").click()
        pump(0.3)
        self.assertEqual(rev.SideType, "Symmetric")
        self.assertIsNone(widget(QtWidgets.QCheckBox, "checkBoxSecondEnd"))
        widget(QtWidgets.QCheckBox, "checkBoxSymmetric").click()
        pump(0.3)
        self.assertEqual(rev.SideType, "One side")
        widget(QtWidgets.QCheckBox, "checkBoxSecondEnd").click()
        pump(0.3)
        self.assertEqual(rev.SideType, "Two sides")
        self.assertAlmostEqual(rev.Angle2.Value, 30, places=9)
        self.assertIsNone(widget(QtWidgets.QCheckBox, "checkBoxSymmetric"))
        self.assertIsNotNone(widget(QtWidgets.QComboBox, "changeMode2"))
        self.assertAlmostEqual(rev.AddSubShape.Volume, 210 * math.pi / 6, places=4)

    def testOkKeepsTheFields(self):
        """Full revolve unticked and OK: the Revolve is 30 deg, one side, valid."""
        rev = self.model()
        self.edit(rev)
        self.full().click()
        pump(0.3)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertAlmostEqual(rev.Angle.Value, 30, places=9)
        self.assertEqual(rev.SideType, "One side")
        self.assertTrue(rev.isValid(), rev.getStatusString())

    def testAGrooveSetToAddKeepsItsEndTypes(self):
        """Rank 20: a Groove set to Add is still a Groove: its end types are a Groove's (index 1 is
        Through all), and Full revolve unticked shows Blind / Up to next / Up to face; the Revolve
        adds (4000 + 105 pi)."""
        groove = self.model("Groove")
        groove.Operation = "Union"
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 4000 + 105 * math.pi, places=4)
        self.edit(groove)
        self.full().click()
        pump(0.3)
        mode = widget(QtWidgets.QComboBox, "changeMode")
        self.assertEqual(mode.itemText(1), "Through all")
        self.assertEqual(
            visibleItems(mode), ["Blind", "Up to next", "Up to face", "Up to part", "Up to vertex"]
        )

    def testUpToVertexAndUpToPart(self):
        """Up to vertex (ops#640 rank 21): its field shows and arms; a pick of the box's corner
        (10, 10, 5) revolves the profile 45 degrees about +Z (315 the other way round), 105 per
        radian; OK keeps it. Up to part shows and arms its own field, the vertex's hidden, and
        writes UpToShape, dropping the vertex."""
        rev = self.model()
        self.edit(rev)
        self.full().click()
        pump(0.3)
        mode = widget(QtWidgets.QComboBox, "changeMode")
        mode.setCurrentIndex(mode.findText("Up to vertex"))
        pump(0.3)
        self.assertEqual(rev.Type, "UpToVertex")
        field = widget(QtWidgets.QWidget, "fieldUpToVertex")
        self.assertIsNotNone(field, "no vertex field")
        self.assertTrue(waitFor(lambda: bool(field.property("armed"))), "not armed")
        self.assertIsNone(widget(QtWidgets.QWidget, "fieldUpToFace"))
        base = self.doc.getObject("Base")
        [corner] = [
            "Vertex%d" % (i + 1)
            for i, v in enumerate(base.Shape.Vertexes)
            if v.Point.distanceToPoint(V(10, 10, 5)) < 1e-7
        ]
        Gui.Selection.addSelection(self.doc.Name, base.Name, corner)
        pump(0.3)
        self.assertEqual(rev.UpToFace[0].Name, base.Name)
        self.assertEqual([s for s in rev.UpToFace[1] if s], [corner])
        degrees = 315 if rev.Reversed else 45
        self.assertAlmostEqual(
            rev.AddSubShape.Volume, math.radians(degrees) * 105, places=3
        )
        mode.setCurrentIndex(mode.findText("Up to part"))
        pump(0.3)
        self.assertEqual(rev.Type, "UpToShape")
        self.assertIsNone(rev.UpToFace)
        part = widget(QtWidgets.QWidget, "fieldUpToPart")
        self.assertIsNotNone(part, "no part field")
        self.assertTrue(waitFor(lambda: bool(part.property("armed"))), "not armed")
        self.assertIsNone(widget(QtWidgets.QWidget, "fieldUpToVertex"))
        mode.setCurrentIndex(mode.findText("Up to vertex"))
        pump(0.3)
        Gui.Selection.addSelection(self.doc.Name, base.Name, corner)
        pump(0.3)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        self.assertEqual(rev.Type, "UpToVertex")
        self.assertTrue(rev.isValid(), rev.getStatusString())
        self.assertAlmostEqual(
            rev.AddSubShape.Volume, math.radians(degrees) * 105, places=3
        )

    def testStudioPlanesStayAfterTheDialog(self):
        """Rank 52: a part studio made by Std_New shows its planes; a Revolve dialog opened and
        cancelled in it leaves them shown (the dialog's axes go)."""
        before = set(App.listDocuments())
        Gui.runCommand("Std_New")
        pump(0.3)
        added = [name for name in App.listDocuments() if name not in before]
        self.assertEqual(len(added), 1, added)
        self.docs.append(added[0])
        doc = App.getDocument(added[0])
        bodies = [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")]
        if len(bodies) != 1:
            self.skipTest("Std_New made no part studio here")
        body = bodies[0]

        def shown(role):
            return body.Origin.ViewObject.Visibility and models.originFeature(
                body, role
            ).ViewObject.Visibility

        if not shown("XY_Plane"):
            self.skipTest("the studio's planes aren't shown")
        rev = self.model(doc=doc, body=body)
        self.edit(rev)
        self.assertTrue(shown("XZ_Plane"), "the planes went while the dialog is open")
        self.assertTrue(shown("Z_Axis"), "no axes for the pick")
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel didn't close")
        pump(0.3)
        for role in ("XY_Plane", "XZ_Plane", "YZ_Plane"):
            self.assertTrue(shown(role), role)
        self.assertFalse(shown("Z_Axis"))

    # -- pick-first (with Command.cpp's dialogTakesProfile listing Revolution and Groove) ---------

    def runRevolve(self, *selection):
        Gui.Selection.clearSelection()
        for obj in selection:
            Gui.Selection.addSelection(self.doc.Name, obj.Name)
        Gui.runCommand("PartDesign_Revolution")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.5)
        self.assertIsNone(
            Gui.getMainWindow().findChild(QtWidgets.QListWidget, "listWidget"), "a sketch list"
        )
        found = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Revolution"]
        return [o for o in found if o is not self.feature][0]

    def testRevolveWithNothingSelectedArmsItsProfile(self):
        """Nothing selected, then Revolve: a Revolution with no profile, its Profile field armed
        (no sketch list although the document has a free sketch). The sketch picked: the
        profile, the axis still to pick (hands-on B-2)."""
        self.model()
        sketch = models.sketch(
            self.doc, "FreeSk", models.rectangle(2, 20, 5, 30), self.body, placement=XZ
        )
        self.doc.recompute()
        rev = self.runRevolve()
        self.assertIsNone(rev.Profile)
        field = widget(QtWidgets.QWidget, "fieldProfile")
        self.assertTrue(waitFor(lambda: field is not None and field.property("armed")), "not armed")
        Gui.Selection.addSelection(self.doc.Name, sketch.Name)
        self.assertTrue(waitFor(lambda: rev.Profile is not None), "the pick wasn't taken")
        self.assertIs(rev.Profile[0], sketch)
        self.assertIsNone(rev.ReferenceAxis)

    def testRevolveWithASketchSelectedTakesIt(self):
        """Hands-on B-2: the sketch selected, then Revolve: the profile is the sketch, the axis
        empty, Full revolve ticked."""
        self.model()
        sketch = models.sketch(
            self.doc, "FreeSk", models.rectangle(2, 20, 5, 30), self.body, placement=XZ
        )
        self.doc.recompute()
        rev = self.runRevolve(sketch)
        self.assertIs(rev.Profile[0], sketch)
        self.assertIsNone(rev.ReferenceAxis)
        self.assertTrue(self.full().isChecked())

    def testAPreselectedAxisIsKept(self):
        """Rank 21: a sketch and then the Z axis selected, then Revolve: the profile is the sketch,
        the axis the Z axis (kept, not left out), the tube added: 4000 + 105 pi."""
        self.model()
        sketch = models.sketch(
            self.doc, "FreeSk", models.rectangle(2, 0, 5, 10), self.body, placement=XZ
        )
        self.doc.recompute()
        zAxis = models.originFeature(self.body, "Z_Axis")
        rev = self.runRevolve(sketch, zAxis)
        self.assertIs(rev.Profile[0], sketch)
        self.assertIsNotNone(rev.ReferenceAxis, "the axis was left out")
        self.assertIs(rev.ReferenceAxis[0], zAxis)
        self.assertTrue(waitFor(lambda: rev.isValid()), rev.getStatusString())

    def testAnAxisAloneArmsTheProfile(self):
        """Rank 21: only the Z axis selected, then Revolve: no profile, the Profile field armed,
        the axis set."""
        self.model()
        zAxis = models.originFeature(self.body, "Z_Axis")
        rev = self.runRevolve(zAxis)
        self.assertIsNone(rev.Profile)
        self.assertIsNotNone(rev.ReferenceAxis)
        self.assertIs(rev.ReferenceAxis[0], zAxis)
        field = widget(QtWidgets.QWidget, "fieldProfile")
        self.assertTrue(waitFor(lambda: field is not None and field.property("armed")), "not armed")


    def testAnAxisWrittenWhileTheDialogIsOpenIsComputedAtOk(self):
        """ops#640 F3: the sketch selected, then Revolve (no axis yet: red), the axis written
        outside the panel while the dialog is open (the property editor, a macro), then OK with
        no other recompute: the Revolution is computed with the axis, not left red with "Select
        the axis to revolve around", and the tube is added: 4000 + 105 pi."""
        self.model()
        sketch = models.sketch(
            self.doc, "FreeSk", models.rectangle(2, 0, 5, 10), self.body, placement=XZ
        )
        self.doc.recompute()
        rev = self.runRevolve(sketch)
        self.assertFalse(rev.isValid())
        rev.ReferenceAxis = (sketch, ["V_Axis"])
        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        self.assertIsNotNone(ok, "no OK button")
        ok.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays open")
        self.assertNotIn("Touched", rev.State)
        self.assertTrue(rev.isValid(), rev.getStatusString())
        self.assertAlmostEqual(rev.Shape.Volume, 4000 + 105 * math.pi, places=3)

class TestOperationRowGui(RevolveCase):
    """Rank 20: the Result row (New part, Add, Remove, Intersect) on a Revolve, Loft, Sweep and
    Helix, as on an Extrude. A Revolve flips its direction between adding and cutting, as a Pad
    and a Pocket; a Loft, Sweep or Helix changes only its Operation (the Helix's direction is
    checked by its volume: flipped, it would leave the box)."""

    def square(self, name, z):
        return models.sketch(self.doc, name, models.rectangle(-2, -2, 2, 2), self.body, z=z)

    def make(self, kind):
        """The feature `kind` on the 4000 box, made by script, valid."""
        if kind == "Revolution":
            feature = self.model()
        else:
            self.model()
            # As the Features list's delete: the Body lets it go first and moves its Tip back to
            # Base; a bare removeObject left the Tip empty, and the new feature went first in
            # the Body, before Base, with the Body still showing the Revolution
            self.body.removeObject(self.feature)
            self.doc.removeObject(self.feature.Name)
            if kind == "AdditiveLoft":
                feature = self.body.newObject("PartDesign::AdditiveLoft", kind)
                feature.Profile = self.square("LoftBottom", 0)
                feature.Sections = [self.square("LoftTop", 10)]
            elif kind == "AdditivePipe":
                spine = models.sketch(
                    self.doc,
                    "Spine",
                    [Part.LineSegment(V(0, 0, 0), V(0, 10, 0))],
                    self.body,
                    placement=XZ,
                )
                feature = self.body.newObject("PartDesign::AdditivePipe", kind)
                feature.Profile = self.square("PipeProfile", 0)
                feature.Spine = (spine, ["Edge1"])
            else:
                profile = models.sketch(
                    self.doc, "CoilSk", models.rectangle(2, -4, 4, -2), self.body, placement=XZ
                )
                feature = self.body.newObject("PartDesign::AdditiveHelix", kind)
                feature.Profile = profile
                feature.ReferenceAxis = (profile, ["V_Axis"])
                feature.Mode = 0  # pitch, height, angle
                feature.Pitch = 5
                feature.Height = 5
                feature.Angle = 0
                # One made and edited before: a first edit of a Helix that never was proposes
                # its pitch and height from the profile (proposeParameters), 3 turns here
                feature.HasBeenEdited = True
            self.doc.recompute()
            self.feature = feature
        self.assertTrue(feature.isValid(), feature.getStatusString())
        return feature

    def edit(self, feature):
        """As a user opens it, a double-click: that opens the edit's transaction, which the Result
        row's switch needs (isEditing); a bare setEdit has none, and the switch went back"""
        feature.ViewObject.doubleClicked()
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.3)

    def resultCombo(self):
        return widget(QtWidgets.QComboBox, "resultCombo")

    def choose(self, feature, key):
        """The Result row `key` chosen as a user does; waits for the edit's restart."""
        combo = self.resultCombo()
        self.assertIsNotNone(combo, "no Result row")
        index = combo.findData(key)
        self.assertGreaterEqual(index, 0, key)
        combo.setCurrentIndex(index)
        self.assertTrue(
            waitFor(
                lambda: self.resultCombo() is not None
                and self.resultCombo().currentData() == key
                and Gui.Control.activeDialog()
            ),
            f"the row doesn't show {key!r} again",
        )
        pump(0.3)

    def runRows(self, kind, expected, flips):
        feature = self.make(kind)
        self.assertAlmostEqual(self.body.Shape.Volume, expected["Union"], delta=0.1, msg=kind)
        reversed0 = feature.Reversed
        self.edit(feature)
        combo = self.resultCombo()
        self.assertIsNotNone(combo, f"{kind}: no Result row")
        self.assertEqual(
            [combo.itemData(i) for i in range(combo.count())],
            ["new", "add", "Subtraction", "Common"],
            kind,
        )
        self.assertEqual(combo.currentData(), "add", kind)
        self.choose(feature, "Subtraction")
        self.assertEqual(feature.Operation, "Subtraction", kind)
        self.assertEqual(feature.Reversed, reversed0 != flips, f"{kind}: direction on Remove")
        # The feature's own result: the Body isn't recomputed while its panel is open
        self.assertAlmostEqual(feature.Shape.Volume, expected["Subtraction"], delta=0.1, msg=kind)
        self.choose(feature, "Common")
        self.assertEqual(feature.Operation, "Common", kind)
        self.assertEqual(feature.Reversed, reversed0 != flips, f"{kind}: direction on Intersect")
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "OK didn't close")
        pump(0.2)
        self.assertEqual(feature.Operation, "Common", kind)
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, expected["Common"], delta=0.1, msg=kind)

    def testRevolveRows(self):
        """The Tube: Add 4000 + 105 pi, Remove 4000 - 105 pi (its direction flipped: a full turn
        either way), Intersect 105 pi."""
        inside = 105 * math.pi
        self.runRows(
            "Revolution",
            {"Union": 4000 + inside, "Subtraction": 4000 - inside, "Common": inside},
            flips=True,
        )

    def testLoftRows(self):
        """The Prism lofted: Add 4080, Remove 3920, Intersect 80; its direction kept."""
        self.runRows(
            "AdditiveLoft", {"Union": 4080, "Subtraction": 3920, "Common": 80}, flips=False
        )

    def testSweepRows(self):
        """The Prism swept: Add 4080, Remove 3920, Intersect 80; its direction kept."""
        self.runRows(
            "AdditivePipe", {"Union": 4080, "Subtraction": 3920, "Common": 80}, flips=False
        )

    def testHelixRows(self):
        """The Coil: Add 4000, Remove 4000 - 24 pi, Intersect 24 pi; its direction kept (Reversed
        would turn it down, out of the box)."""
        coil = 24 * math.pi
        self.runRows(
            "AdditiveHelix",
            {"Union": 4000, "Subtraction": 4000 - coil, "Common": coil},
            flips=False,
        )
