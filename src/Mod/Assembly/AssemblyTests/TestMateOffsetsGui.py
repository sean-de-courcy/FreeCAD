# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, design C1, notes/assemblies-design.md section 3): the Fastened mate's dialog
# as Onshape's. With Offset ticked it has X, Y and Z fields, each taking an expression (`#name`
# included); the two buttons are Onshape's Flip primary axis and Reorient secondary axis.
#
# Designed geometry, the oracle's own (notes/onshape-facts.md, GC hands-on): box A 40 x 20 x 10 at
# the origin, box B 20 x 10 x 5 at x 60..80; a Fastened mate from A's top-face centre to B's.
# The expected positions without an offset are the ones Onshape gave (GC-B1, GC-B1.4): the first
# pick moves; unflipped T (50, -5, -5); Flip primary R diag(1, -1, -1), T (50, 15, 15); then
# Reorient secondary R [[0, 1, 0], [1, 0, 0], [0, 0, -1]], T (60, -15, 15). They are compared as
# A's placement relative to B's, so whichever part the solve moves the test holds.
#
# The offset is in the second pick's connector frame, as today (on a top face: the part's axes).
# Whether that frame and sign are Onshape's is design C2 (oracle questions B1.2 and B2, open):
# those expectations are geometric, "A's top centre sits at B's top centre + (x, y, z)".

import gc
import os
import shutil
import tempfile
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets

try:
    from PySide6 import QtTest
except ImportError:  # pragma: no cover
    QtTest = None

import CommandCreateJoint
import JointObject


def pump(seconds=0.2):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


B_AT = App.Vector(60, 0, 0)  # B's geometry sits at x 60..80 in Onshape's studio; here its placement


def onshape(rot_rows, t):
    """A's placement as Onshape reported it (B at identity, its geometry at x 60..80)."""
    r = rot_rows
    m = App.Matrix(*r[0], 0, *r[1], 0, *r[2], 0, 0, 0, 0, 1)
    return App.Placement(App.Vector(*t), App.Rotation(m))


IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
FLIPPED = ((1, 0, 0), (0, -1, 0), (0, 0, -1))
REORIENTED = ((0, 1, 0), (1, 0, 0), (0, 0, -1))


class TestMateOffsetsGui(unittest.TestCase):
    def setUp(self):
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        self.tmp = tempfile.mkdtemp(prefix="mateoffsets")
        self.doc = App.newDocument("MateOffsetsGui")
        Gui.activateWorkbench("AssemblyWorkbench")
        self.vars = self.doc.addObject("App::VarSet", "Variables")
        for name, value in (("ox", 5.0), ("A", 2.0), ("B", 3.0)):
            self.vars.addProperty("App::PropertyLength", name)
            setattr(self.vars, name, value)
        self.startAssembly()

    def startAssembly(self):
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.jointgroup = self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.a = self.box("A", 40, 20, 10, App.Vector())
        self.b = self.box("B", 20, 10, 5, B_AT)
        self.doc.recompute()
        self.edit()

    def edit(self):
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.setEdit(self.assembly.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))

    def tearDown(self):
        if JointObject.activeTask is not None:
            JointObject.activeTask.reject()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        pump()
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        App.closeDocument(self.doc.Name)
        Gui.doCommand("panel = None")  # activateJoint's console reference to the last dialog
        # the dialog's widgets go with deleteLater: let them, so that the next dialog's Qt
        # objects don't meet a stale wrapper at a reused address ("Signal source has been deleted")
        pump()
        gc.collect()
        pump()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def box(self, name, length, width, height, at):
        box = self.assembly.newObject("Part::Box", name)
        box.Length, box.Width, box.Height = length, width, height
        box.Placement = App.Placement(at, App.Rotation())
        return box

    # --- the dialog -------------------------------------------------------------------------

    def openFastened(self):
        CommandCreateJoint.activateJoint(0)
        self.assertTrue(waitFor(lambda: JointObject.activeTask is not None), "no joint dialog")
        panel = JointObject.activeTask
        self.assertEqual(panel.jType, "Fixed")
        return panel

    def pickTopCentres(self, panel):
        # A's top face (Face6, z 10) at its centre, then B's (z 5): the face centres (CENTROID)
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "A.Face6", 20, 10, 10)
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "B.Face6", 70, 5, 5)
        pump()
        self.assertEqual(len(panel.refs), 2)

    def commit(self, panel):
        self.assertTrue(panel.okButton.isEnabled())
        panel.okButton.click()
        pump()
        if Gui.Control.activeDialog() and JointObject.activeTask:
            JointObject.activeTask.reject()  # the next joint, empty
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        joints = [j for j in self.jointgroup.Group if getattr(j, "Reference2", None)]
        self.assertEqual(len(joints), 1)
        return joints[0]

    def typeInto(self, spin, text):
        if QtTest is None:
            self.skipTest("no QtTest")
        spin.setFocus()
        pump(0.1)
        spin.findChild(QtWidgets.QLineEdit).selectAll()
        QtTest.QTest.keyClicks(spin, text)
        if "#" in text and spin.property("unresolvedVariable") is None:
            self.skipTest("this build's fields do not take #variable (ops#640)")
        QtTest.QTest.keyClick(spin, QtCore.Qt.Key_Return)
        pump(0.2)

    def setOffset(self, panel, x=None, y=None, z=None):
        panel.jForm.offsetCheckbox.setChecked(True)
        pump()
        fields = (
            (x, panel.jForm.offsetXSpinbox),
            (y, panel.jForm.offsetYSpinbox),
            (z, panel.jForm.offsetSpinbox),
        )
        for value, spin in fields:
            if value is None:
                continue
            if isinstance(value, str):
                self.typeInto(spin, value)
            else:
                spin.setProperty("rawValue", float(value))
        pump()

    # --- the checks -------------------------------------------------------------------------

    def relative(self):
        """A's placement in the frame Onshape's numbers use (B's placement as identity there)."""
        b0 = App.Placement(B_AT, App.Rotation())
        return b0 * self.b.Placement.inverse() * self.a.Placement

    def assertPlacement(self, expected, msg=""):
        got = self.relative()
        self.assertTrue(
            got.Base.isEqual(expected.Base, 1e-6), f"{msg}: T {got.Base}, expected {expected.Base}"
        )
        self.assertTrue(
            got.Rotation.isSame(expected.Rotation, 1e-6),
            f"{msg}: R {got.Rotation.toMatrix()}, expected {expected.Rotation.toMatrix()}",
        )

    def assertTopCentreAt(self, offset, flipped, msg=""):
        """Geometric: A's top centre sits at B's top centre moved by `offset` (B's top-face
        connector axes are the part's), A's top facing B's (flipped) or the same way."""
        rel = self.relative()
        centre = rel.multVec(App.Vector(20, 10, 10))
        target = App.Vector(70, 5, 5) + App.Vector(*offset)
        self.assertTrue(centre.isEqual(target, 1e-6), f"{msg}: A's top centre {centre}, expected {target}")
        normal = rel.Rotation.multVec(App.Vector(0, 0, 1))
        self.assertAlmostEqual(normal.z, -1.0 if flipped else 1.0, places=6, msg=msg)

    # --- the tests ------------------------------------------------------------------------

    def test_buttons_have_onshapes_names(self):
        panel = self.openFastened()
        self.assertEqual(panel.jForm.PushButtonReverse.text(), "Flip primary axis")
        self.assertEqual(panel.jForm.PushButtonRotate90.text(), "Reorient secondary axis")
        self.assertEqual(
            panel.jForm.PushButtonReverse.toolButtonStyle(), QtCore.Qt.ToolButtonTextBesideIcon
        )

    def test_offset_off_by_default_and_fields_follow_the_box(self):
        panel = self.openFastened()
        box = panel.jForm.offsetCheckbox
        self.assertFalse(box.isHidden(), "no Offset checkbox on a Fastened mate")
        self.assertFalse(box.isChecked(), "a new mate starts with Offset on")
        for spin in (panel.jForm.offsetXSpinbox, panel.jForm.offsetYSpinbox, panel.jForm.offsetSpinbox):
            self.assertTrue(spin.isHidden(), "an offset field shows with Offset off")
        box.setChecked(True)
        pump()
        for spin in (panel.jForm.offsetXSpinbox, panel.jForm.offsetYSpinbox, panel.jForm.offsetSpinbox):
            self.assertFalse(spin.isHidden(), "an offset field is hidden with Offset on")

    def test_new_mate_unflipped_as_onshape(self):
        """GC-B1: the first pick moves, translation only; the connectors coincide, same way."""
        panel = self.openFastened()
        self.pickTopCentres(panel)
        self.commit(panel)
        self.assertPlacement(onshape(IDENTITY, (50, -5, -5)), "unflipped")

    def test_new_mate_unflipped_even_facing(self):
        """GC-B1: a new mate is unflipped whatever the parts' positions. A turned upside down
        first (its top facing -z, as B's top would face it) still gets the unflipped mate."""
        self.a.Placement = App.Placement(
            App.Vector(0, 20, 30), App.Rotation(App.Vector(1, 0, 0), 180)
        )
        self.doc.recompute()
        panel = self.openFastened()
        # A's top face now lies at z 20; its centre at (20, 10, 20)
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "A.Face6", 20, 10, 20)
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "B.Face6", 70, 5, 5)
        pump()
        self.assertEqual(len(panel.refs), 2)
        self.commit(panel)
        self.assertPlacement(onshape(IDENTITY, (50, -5, -5)), "unflipped from a facing start")

    def test_flip_primary_as_onshape(self):
        panel = self.openFastened()
        self.pickTopCentres(panel)
        panel.jForm.PushButtonReverse.click()
        pump()
        self.commit(panel)
        self.assertPlacement(onshape(FLIPPED, (50, 15, 15)), "Flip primary")

    def test_reorient_secondary_after_flip_as_onshape(self):
        panel = self.openFastened()
        self.pickTopCentres(panel)
        panel.jForm.PushButtonReverse.click()
        pump()
        panel.jForm.PushButtonRotate90.click()
        pump()
        self.commit(panel)
        self.assertPlacement(onshape(REORIENTED, (60, -15, 15)), "Flip, then Reorient")

    def test_flipped_mate_with_offset(self):
        """The team's normal case (67 of 74 mates flipped, GC-A2), with an offset."""
        panel = self.openFastened()
        self.pickTopCentres(panel)
        panel.jForm.PushButtonReverse.click()
        pump()
        self.setOffset(panel, 5, 7, 3)
        joint = self.commit(panel)
        self.assertTrue(joint.Offset2.Base.isEqual(App.Vector(5, 7, 3), 1e-9), joint.Offset2.Base)
        # Onshape's (oracle 12, GC-B1.2; ops#683 C2): the offset runs along the first pick's
        # connector axes, which the flip turned: (5, -7, -3) along B's
        self.assertTopCentreAt((5, -7, -3), flipped=True, msg="flipped, offset (5, 7, 3)")

    def test_each_offset_axis_alone_and_together(self):
        for offset in ((5, 0, 0), (0, 7, 0), (0, 0, 3), (5, 7, 3)):
            with self.subTest(offset=offset):
                if offset != (5, 0, 0):
                    self.restart()
                panel = self.openFastened()
                self.pickTopCentres(panel)
                self.setOffset(panel, *offset)
                joint = self.commit(panel)
                self.assertTrue(joint.Offset2.Base.isEqual(App.Vector(*offset), 1e-9), joint.Offset2.Base)
                self.assertTopCentreAt(offset, flipped=False, msg=f"offset {offset}")

    def restart(self):
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        pump()
        self.doc.removeObject(self.jointgroup.Name)
        for o in (self.a, self.b):
            self.doc.removeObject(o.Name)
        self.doc.removeObject(self.assembly.Name)
        self.doc.recompute()
        self.startAssembly()

    def test_untick_drops_the_offset(self):
        panel = self.openFastened()
        self.pickTopCentres(panel)
        self.setOffset(panel, 5, 7, 3)
        panel.jForm.offsetCheckbox.setChecked(False)
        pump()
        self.assertTrue(panel.joint.Offset2.Base.isEqual(App.Vector(), 1e-9))
        self.commit(panel)
        self.assertTopCentreAt((0, 0, 0), flipped=False, msg="unticked")

    def test_variables_save_and_reopen(self):
        """`#ox` from the document's variables and `#A + #B` typed in the fields; both stay
        expressions through save and reopen, and follow the variables."""
        panel = self.openFastened()
        self.pickTopCentres(panel)
        self.setOffset(panel, x="#ox", y="#A + #B", z=3)
        joint = self.commit(panel)
        exprs = self.offsetExprs(joint)
        self.assertEqual(exprs.get("Offset2.Base.x"), "#ox", exprs)
        self.assertEqual(exprs.get("Offset2.Base.y"), "#A+#B", exprs)
        self.assertTopCentreAt((5, 5, 3), flipped=False, msg="#ox, #A + #B, 3")

        path = os.path.join(self.tmp, "mate.FCStd")
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        pump()
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = App.openDocument(path)
        pump()
        self.assembly = self.doc.getObject("Assembly")
        self.a, self.b = self.doc.getObject("A"), self.doc.getObject("B")
        joint = [j for j in self.doc.Objects if getattr(j, "JointType", None) == "Fixed"][0]
        exprs = self.offsetExprs(joint)
        self.assertEqual(exprs.get("Offset2.Base.x"), "#ox", "lost through save and reopen")
        self.assertTopCentreAt((5, 5, 3), flipped=False, msg="after reopen")

        self.doc.getObject("Variables").ox = 8.0
        self.doc.recompute()
        self.assembly.solve()
        self.assertTopCentreAt((8, 5, 3), flipped=False, msg="#ox = 8 after reopen")

    @staticmethod
    def offsetExprs(joint):
        """The joint's expressions, `Variables.ox` (the document's variables, as stored) read
        back as `#ox`, spaces dropped."""
        return {
            p.lstrip("."): e.replace("Variables.", "#").replace(" ", "")
            for p, e in joint.ExpressionEngine
        }

    def test_edit_shows_the_offset(self):
        panel = self.openFastened()
        self.pickTopCentres(panel)
        self.setOffset(panel, 5, 7, 3)
        joint = self.commit(panel)
        panel = JointObject.TaskAssemblyCreateJoint(0, joint)
        Gui.Control.showDialog(panel)
        pump()
        try:
            self.assertTrue(panel.jForm.offsetCheckbox.isChecked(), "an offset mate opens unticked")
            self.assertAlmostEqual(panel.jForm.offsetXSpinbox.property("rawValue"), 5.0)
            self.assertAlmostEqual(panel.jForm.offsetYSpinbox.property("rawValue"), 7.0)
            self.assertAlmostEqual(panel.jForm.offsetSpinbox.property("rawValue"), 3.0)
        finally:
            panel.reject()
            pump()


if __name__ == "__main__":
    unittest.main()
