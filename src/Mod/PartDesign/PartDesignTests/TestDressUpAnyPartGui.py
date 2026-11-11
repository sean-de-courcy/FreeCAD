# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dress-ups on any part, tool-first (FreeCAD-CH ops#640 rank 14, with rank 13's tool-first flow).

An Onshape Part Studio has no active part: a Fillet (Chamfer, Shell, Draft) started with nothing
selected opens with no question, and its first pick, an edge or a face of any part, decides the
part it rounds. Here the dress-up waits in the active Body (else the first Body with a solid),
with no "active body is required" modal, and moves into the first pick's Body inside the
dialog's step: Cancel takes it and leaves no step; the dialog comes back with its field armed,
so the next picks add to it. Designed geometry: Body A, a 10 x 10 x 10 pad at the origin; Body B,
the same at x = 20..30; both at the document's top level (one studio) or each in its own
App::Part. A vertical edge of B rounded at r costs r^2 (1 - pi/4) L, L = 10. Off screen:
QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import math

import FreeCAD as App
import FreeCADGui as Gui

from PartDesignTests.TestCrossBodyGui import ResultBoxGuiCase
from PartDesignTests.TestExpressionFieldsGui import pump, waitFor
from PartDesignTests.TestReferenceFieldGui import fields
# the module, not its classes: a TestCase imported here would run with this unit
import PartDesignTests.TestStudioPicksGui as studio
from PartDesignTests.TestStudioPicksGui import verticalEdge


def base(dressUp):
    """The dress-up's Base: its object and its element names (no empty one)."""
    if not dressUp.Base:
        return None, []
    obj, subs = dressUp.Base
    return obj, [s for s in subs if s]


def filletLoss(r, edges=1):
    """What rounding `edges` vertical 10 mm edges of a box at radius r removes."""
    return edges * r * r * (1 - math.pi / 4) * 10


class TestDressUpAnyPartGui(ResultBoxGuiCase):
    """A dress-up started with nothing selected takes its part from its dialog's first pick."""

    # the two-part model and its helpers (TestStudioPicksGui.TestStudioDressUpsGui)
    twoParts = studio.TestStudioDressUpsGui.twoParts
    watchModals = studio.TestStudioDressUpsGui.watchModals
    made = studio.TestStudioDressUpsGui.made
    panelWidget = studio.TestStudioDressUpsGui.panelWidget
    setField = studio.TestStudioDressUpsGui.setField

    def setUp(self):
        super().setUp()
        self.modals = []
        self.watching = False

    def tearDown(self):
        self.watching = False
        super().tearDown()

    def toolFirst(self, command, active):
        """`command` with nothing selected, `active` the active Body (None: none); waits for its
        dialog and returns the dress-up it made."""
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", active)
        Gui.Selection.clearSelection()
        self.undos = list(self.doc.UndoNames)
        self.redos = list(self.doc.RedoNames)
        self.watchModals()
        Gui.runCommand(command)
        self.waitForPanel()
        typeId = "PartDesign::" + command.split("_", 1)[1]
        [dressUp] = self.made(typeId)
        return dressUp

    def click(self, feature, sub):
        """A pick in the 3D view: the feature's element on its path through its Body (a gate may
        refuse it)."""
        body = feature.getParentGeoFeatureGroup()
        Gui.Selection.addSelection(self.doc.Name, body.Name, feature.Name + "." + sub)

    def placedIn(self, dressUp, body):
        """Waits until the dress-up is in `body` and its dialog is back."""
        self.assertTrue(
            waitFor(lambda: body.hasObject(dressUp) and Gui.Control.activeDialog() is not None),
            "the dress-up stayed in " + dressUp.getParentGeoFeatureGroup().Name,
        )
        pump(0.3)

    def assertNoTrace(self, a, b, padA, padB):
        """No dress-up, the parts as they were, no undo step (and the Redo stack kept)."""
        self.assertEqual(
            [o.Name for o in self.doc.Objects if o.isDerivedFrom("PartDesign::DressUp")], []
        )
        self.assertEqual((a.Tip, b.Tip), (padA, padB))
        self.assertEqual([o.Name for o in a.Group if o.isDerivedFrom("PartDesign::Feature")], [padA.Name])
        self.assertEqual([o.Name for o in b.Group if o.isDerivedFrom("PartDesign::Feature")], [padB.Name])
        self.assertTrue(padA.Visibility and padB.Visibility, (padA.Visibility, padB.Visibility))
        self.assertEqual(list(self.doc.UndoNames), self.undos)
        self.assertEqual(list(self.doc.RedoNames), self.redos)

    # -- the first pick decides the part

    def testToolFirstFilletGoesToThePickedPart(self):
        """A active, Fillet with nothing selected: no modal, the dialog opens; the first click,
        on an edge of B, moves the fillet into B (Base that edge, after B's pad) and the dialog
        comes back with the edges field armed. r = 2: B loses r^2 (1 - pi/4) 10, A unchanged,
        one undo step."""
        a, b, padA, padB = self.twoParts()
        fillet = self.toolFirst("PartDesign_Fillet", a)
        self.assertTrue(a.hasObject(fillet))
        edge = verticalEdge(padB, 30, 10)
        self.click(padB, edge)
        self.placedIn(fillet, b)
        self.assertFalse(a.hasObject(fillet))
        self.assertEqual(base(fillet), (padB, [edge]))
        self.assertEqual(fillet.BaseFeature, padB)
        self.assertEqual((a.Tip, b.Tip), (padA, fillet))
        [field] = fields()
        self.assertTrue(field.property("armed"), "the edges field is not armed")
        self.setField("filletRadius", 2)
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertAlmostEqual(fillet.Shape.Volume, 1000 - filletLoss(2), places=4)
        self.assertAlmostEqual(b.Shape.Volume, 1000 - filletLoss(2), places=4)
        self.assertAlmostEqual(a.Shape.Volume, 1000, places=6)
        self.assertTrue(padA.Visibility, "A's pad is hidden")
        self.assertEqual(len(self.doc.UndoNames), len(self.undos) + 1, self.doc.UndoNames)

    def testToolFirstFilletWithNoBodyActive(self):
        """Two Bodies, none active: Fillet with nothing selected asks nothing (no 'active body
        is required'); the first pick, B's edge, puts the fillet in B."""
        a, b, padA, padB = self.twoParts()
        fillet = self.toolFirst("PartDesign_Fillet", None)
        edge = verticalEdge(padB, 30, 10)
        self.click(padB, edge)
        self.placedIn(fillet, b)
        self.setField("filletRadius", 2)
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertAlmostEqual(b.Shape.Volume, 1000 - filletLoss(2), places=4)
        self.assertAlmostEqual(a.Shape.Volume, 1000, places=6)
        self.assertEqual(a.Tip, padA)

    def testTheNextPicksAddToTheField(self):
        """After the first pick moved the fillet into B, a second edge of B joins it: both
        rounded at r = 2."""
        a, b, padA, padB = self.twoParts()
        fillet = self.toolFirst("PartDesign_Fillet", a)
        first, second = verticalEdge(padB, 30, 10), verticalEdge(padB, 20, 0)
        self.click(padB, first)
        self.placedIn(fillet, b)
        self.click(padB, second)
        pump(0.3)
        self.assertEqual(base(fillet), (padB, [first, second]))
        self.setField("filletRadius", 2)
        self.close(ok=True)
        self.watching = False
        self.doc.recompute()
        self.assertAlmostEqual(b.Shape.Volume, 1000 - filletLoss(2, edges=2), places=4)
        self.assertAlmostEqual(a.Shape.Volume, 1000, places=6)

    def testFirstPickOnTheSamePart(self):
        """A active, the first pick on A's own edge: the fillet stays in A, on that edge."""
        a, b, padA, padB = self.twoParts()
        fillet = self.toolFirst("PartDesign_Fillet", a)
        edge = verticalEdge(padA, 10, 10)
        self.click(padA, edge)
        self.assertTrue(waitFor(lambda: base(fillet) == (padA, [edge])), str(fillet.Base))
        pump(0.3)
        self.assertTrue(a.hasObject(fillet))
        self.setField("filletRadius", 2)
        self.close(ok=True)
        self.watching = False
        self.doc.recompute()
        self.assertAlmostEqual(a.Shape.Volume, 1000 - filletLoss(2), places=4)
        self.assertAlmostEqual(b.Shape.Volume, 1000, places=6)
        self.assertEqual(b.Tip, padB)

    def testToolFirstChamferGoesToThePickedPart(self):
        """Chamfer with nothing selected, A active, first pick on B's edge: the chamfer is B's.
        Size 2 on a 10 mm vertical edge removes a 2 x 2 / 2 x 10 prism: 980."""
        a, b, padA, padB = self.twoParts()
        chamfer = self.toolFirst("PartDesign_Chamfer", a)
        self.click(padB, verticalEdge(padB, 30, 10))
        self.placedIn(chamfer, b)
        self.setField("chamferSize", 2)
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertAlmostEqual(b.Shape.Volume, 980, places=4)
        self.assertAlmostEqual(a.Shape.Volume, 1000, places=6)

    def testAnActiveBodyWithNoSolidGivesWay(self):
        """Review (hub 5) 1: an active Body with no solid yet (a new, empty part) made the tool
        say it needs a part with a solid. The fillet starts in the first part with one (A) and
        the first pick, B's edge, takes it to B."""
        a, b, padA, padB = self.twoParts()
        empty = self.doc.addObject("PartDesign::Body", "Empty")
        fillet = self.toolFirst("PartDesign_Fillet", empty)
        self.assertFalse(empty.hasObject(fillet))
        edge = verticalEdge(padB, 30, 10)
        self.click(padB, edge)
        self.placedIn(fillet, b)
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.modals, [])

    def testAnEarlierFeatureOfAnotherPartIsRefused(self):
        """Review (hub 5) 2: B's pad is no longer B's Tip (a box after it). A pick on the pad,
        shown, would make the fillet B's Tip on the pad and drop the box's material: refused;
        the fillet waits in A and B is unchanged."""
        a, b, padA, padB = self.twoParts()
        box = b.newObject("PartDesign::AdditiveBox", "Later")
        box.Placement.Base = padB.Shape.BoundBox.Center + App.Vector(0, 0, 4)
        self.doc.recompute()
        self.assertIs(b.Tip, box)
        volume = b.Shape.Volume
        padB.ViewObject.Visibility = True
        fillet = self.toolFirst("PartDesign_Fillet", a)
        self.click(padB, verticalEdge(padB, 30, 10))
        pump(0.5)
        self.assertTrue(a.hasObject(fillet), "the fillet moved to an earlier feature of B")
        self.assertIs(b.Tip, box)
        self.close(ok=False)
        self.watching = False
        self.doc.recompute()
        self.assertAlmostEqual(b.Shape.Volume, volume, places=6)

    def testAPickInAnotherStudioIsRefused(self):
        """A and B each in its own App::Part (two part studios): B's edge is refused (Onshape
        needs a Derived feature); the fillet waits in A."""
        a, b, padA, padB = self.twoParts(apart=True)
        fillet = self.toolFirst("PartDesign_Fillet", a)
        self.click(padB, verticalEdge(padB, 30, 10))
        pump(0.5)
        self.assertTrue(a.hasObject(fillet))
        self.assertEqual(base(fillet)[1], [])
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.modals, [])

    # -- Cancel and the dialog's own history

    def testCancelBeforeAPickLeavesNoStep(self):
        a, b, padA, padB = self.twoParts()
        self.toolFirst("PartDesign_Fillet", a)
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.assertNoTrace(a, b, padA, padB)

    def testCancelAfterTheMoveLeavesNoStep(self):
        """Cancel after the first pick moved the fillet into B: no fillet anywhere, A's and B's
        pads their Tips and shown again, no undo step."""
        a, b, padA, padB = self.twoParts()
        fillet = self.toolFirst("PartDesign_Fillet", a)
        self.click(padB, verticalEdge(padB, 30, 10))
        self.placedIn(fillet, b)
        self.setField("filletRadius", 2)
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.assertNoTrace(a, b, padA, padB)
        self.doc.recompute()
        self.assertAlmostEqual(b.Shape.Volume, 1000, places=6)

    def testDialogUndoAfterTheMove(self):
        """The dialog's own undo after the move: a second edge, then Std_Undo with the dialog
        open takes that edge back (the fillet stays in B, the dialog open); Cancel then leaves
        no trace."""
        a, b, padA, padB = self.twoParts()
        fillet = self.toolFirst("PartDesign_Fillet", a)
        first, second = verticalEdge(padB, 30, 10), verticalEdge(padB, 20, 0)
        self.click(padB, first)
        self.placedIn(fillet, b)
        self.click(padB, second)
        pump(0.3)
        self.assertEqual(base(fillet), (padB, [first, second]))
        self.assertTrue(Gui.Command.get("Std_Undo").isActive(), "Std_Undo inactive in the dialog")
        Gui.runCommand("Std_Undo")
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertEqual(base(fillet), (padB, [first]))
        self.assertTrue(b.hasObject(fillet))
        self.close(ok=False)
        self.watching = False
        self.assertNoTrace(a, b, padA, padB)

    def checkAPartPreselectedLeavesItEmpty(self, command):
        """Selection parity P6 (oracle 8, SQ12): a part picked whole, then Fillet or Chamfer:
        the dialog opens on that part with no edge in the field and not every edge (the fork
        took all 12 edges); an edge click then adds just that edge."""
        a, b, padA, padB = self.twoParts()
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", a)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, b.Name)
        self.watchModals()
        Gui.runCommand(command)
        self.waitForPanel()
        typeId = "PartDesign::" + command.split("_", 1)[1]
        [dressUp] = self.made(typeId)
        self.assertEqual(base(dressUp)[1], [], command + ": the part's edges were taken")
        self.assertFalse(dressUp.UseAllEdges, command + ": UseAllEdges")
        self.assertEqual(dressUp.BaseFeature, padB, command + ": not on the picked part")
        edge = verticalEdge(padB, 30, 10)
        self.click(padB, edge)
        pump(0.3)
        self.assertEqual(base(dressUp), (padB, [edge]), command)
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.modals, [])

    def testAPartPreselectedLeavesFilletEmpty(self):
        self.checkAPartPreselectedLeavesItEmpty("PartDesign_Fillet")

    def testAPartPreselectedLeavesChamferEmpty(self):
        self.checkAPartPreselectedLeavesItEmpty("PartDesign_Chamfer")
