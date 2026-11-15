# SPDX-License-Identifier: LGPL-2.1-or-later
"""Where a new Remove, Revolve, Loft, Sweep or Helix opens (FreeCAD-CH ops#640, round 3 of hands-on
check A-1): as an Extrude, an Add opens with the one part its tool touches as its scope (else New);
a Remove opens in its own part when its tool overlaps it, else in the one other part it overlaps;
overlapping none it stays in its own part, a healthy no-op, as Onshape's Remove that misses
(hands-on R7b); overlapping two other parts it stays too (not seen in Onshape). Designed geometry.
Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestCrossBodyGui import ResultBoxGuiCase
from PartDesignTests.TestExpressionFieldsGui import pump
from PartDesignTests.TestCrossBodyGui import siblingEraPath  # ops#654 list on first use

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))  # sketch y -> global z


class TestOpeningScopeGui(ResultBoxGuiCase):
    """Body A: a 10 x 10 x 10 pad at the origin (x 0..10, y 0..10); Body B: a 10 x 10 x 10 pad at
    x 20..30, y -5..5; both at the document's top level (one studio). A is active. A Pocket is
    5 deep from its sketch at z = 10, into the material."""

    def setUp(self):
        super().setUp()
        self.modals = []
        self.watching = False

    def tearDown(self):
        self.watching = False
        super().tearDown()

    def twoParts(self):
        a = self.doc.addObject("PartDesign::Body", "A")
        b = self.doc.addObject("PartDesign::Body", "B")
        padA = models.pad(a, models.sketch(self.doc, "SkA", models.rectangle(0, 0, 10, 10), a), 10)
        padB = models.pad(
            b, models.sketch(self.doc, "SkB", models.rectangle(20, -5, 30, 5), b), 10, name="PadB"
        )
        self.doc.recompute()
        self.assertAlmostEqual(padA.Shape.Volume, 1000, places=6)
        self.assertAlmostEqual(padB.Shape.Volume, 1000, places=6)
        self.a, self.b, self.padA, self.padB = a, b, padA, padB
        return a, b

    def watchModals(self):
        """Records and closes every message box until self.watching is False."""
        self.watching = True

        def poll():
            if not self.watching:
                return
            widget = QtWidgets.QApplication.activeModalWidget()
            if isinstance(widget, QtWidgets.QMessageBox):
                self.modals.append(widget.text())
                widget.accept()
            QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)

    def runIn(self, body, command, *selection):
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", body)
        Gui.Selection.clearSelection()
        for obj in selection:
            Gui.Selection.addSelection(self.doc.Name, obj.Name)
        self.watchModals()
        Gui.runCommand(command)
        self.waitForPanel()

    def made(self, typeId):
        [feature] = [o for o in self.doc.Objects if o.TypeId == typeId]
        return feature

    def pocketOver(self, body, x0, y0, x1, y1):
        """A Pocket from a sketch of `body` at z = 10 over the rectangle, accepted."""
        sk = models.sketch(self.doc, "PocketSk", models.rectangle(x0, y0, x1, y1), body, z=10)
        self.doc.recompute()
        self.runIn(body, "PartDesign_Pocket", sk)
        pocket = self.made("PartDesign::Pocket")
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        return pocket

    @siblingEraPath
    def testPocketOverItsOwnPartStays(self):
        """Over A: the Pocket stays in A and cuts it, 2 x 2 x 5 = 20."""
        a, b = self.twoParts()
        pocket = self.pocketOver(a, 2, 2, 4, 4)
        self.assertTrue(a.hasObject(pocket))
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(a.Shape.Volume, 980, places=4)
        self.assertAlmostEqual(b.Shape.Volume, 1000, places=4)

    @siblingEraPath
    def testPocketOverAnotherPartOpensThere(self):
        """A sketch of A over B only: the Pocket opens in B (its scope) and cuts it, 20; A keeps
        its pad as its tip."""
        a, b = self.twoParts()
        pocket = self.pocketOver(a, 22, -1, 24, 1)
        self.assertTrue(b.hasObject(pocket))
        self.assertEqual(b.Tip, pocket)
        self.assertEqual(a.Tip, self.padA)
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(b.Shape.Volume, 980, places=4)
        self.assertAlmostEqual(a.Shape.Volume, 1000, places=4)

    @siblingEraPath
    def testPocketOverNothingStaysHealthy(self):
        """Over no part: the Pocket stays in A, healthy, removing nothing (Onshape's no-op Remove,
        R7b); no Body is made for it, and neither part changes."""
        a, b = self.twoParts()
        pocket = self.pocketOver(a, 40, 0, 42, 2)
        self.assertTrue(a.hasObject(pocket))
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertEqual(sorted(self.bodies()), ["A", "B"])
        self.assertAlmostEqual(a.Shape.Volume, 1000, places=4)
        self.assertAlmostEqual(b.Shape.Volume, 1000, places=4)

    @siblingEraPath
    def testPocketOverTwoOtherPartsStays(self):
        """A third part C, a 10 x 10 x 10 pad at x 20..30, y 10..20: a sketch of A over B and C
        (x 22..24, y 3..12), not over A: the Pocket stays in A, healthy, and no part changes
        (Onshape not seen; no Body is made for it)."""
        a, b = self.twoParts()
        c = self.doc.addObject("PartDesign::Body", "C")
        padC = models.pad(
            c, models.sketch(self.doc, "SkC", models.rectangle(20, 10, 30, 20), c), 10, name="PadC"
        )
        self.doc.recompute()
        self.assertAlmostEqual(padC.Shape.Volume, 1000, places=6)
        pocket = self.pocketOver(a, 22, 3, 24, 12)
        self.assertTrue(a.hasObject(pocket))
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertEqual(sorted(self.bodies()), ["A", "B", "C"])
        for body in (a, b, c):
            self.assertAlmostEqual(body.Shape.Volume, 1000, places=4)

    @siblingEraPath
    def testPocketInAnEmptyPartOpensInTheOneItOverlaps(self):
        """A third Body C, empty and active: Pocket asks nothing (there was a 'no solid to subtract
        from' modal) and opens in B, which its tool overlaps: 980."""
        a, b = self.twoParts()
        c = self.doc.addObject("PartDesign::Body", "C")
        pocket = self.pocketOver(c, 22, -1, 24, 1)
        self.assertTrue(b.hasObject(pocket))
        self.assertAlmostEqual(b.Shape.Volume, 980, places=4)

    def testSweepTouchingAnotherPartOpensAsAddThere(self):
        """A Sweep of A: a 2 x 2 square at z = 5 inside B's footprint swept 10 up a line of A
        (x = 23, y = 0): its tool touches B only, so it opens as Add to B: B gains the 2 x 2 x 5
        above its top, 1020; A is untouched."""
        a, b = self.twoParts()
        profile = models.sketch(self.doc, "Profile", models.rectangle(22, -1, 24, 1), a, z=5)
        line = Part.LineSegment(V(23, 5, 0), V(23, 15, 0))
        spine = models.sketch(self.doc, "Spine", [line], a, placement=XZ)
        self.doc.recompute()
        self.runIn(a, "PartDesign_AdditivePipe", profile, spine)
        pipe = self.made("PartDesign::AdditivePipe")
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertTrue(b.hasObject(pipe))
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(b.Shape.Volume, 1020, places=3)
        self.assertAlmostEqual(a.Shape.Volume, 1000, places=4)
