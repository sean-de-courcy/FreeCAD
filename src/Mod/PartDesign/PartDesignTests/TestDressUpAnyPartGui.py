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

    # -- a part picked whole in an open dialog (selection parity P6a, oracle 8 SQ12)

    def partRowPicks(self, a, b, padB):
        """The picks a Parts-list row and a feature row make (FeaturesView::pushSelection, the
        tree): each part whole, and B's pad whole on its path through B."""
        return [(a.Name, ""), (b.Name, ""), (b.Name, padB.Name + ".")]

    def assertRowsSelectable(self, a, b, padB):
        """With no dialog open each row pick selects: a refusal later is the dialog's."""
        for obj, sub in self.partRowPicks(a, b, padB):
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self.doc.Name, obj, sub)
            self.assertEqual(len(Gui.Selection.getSelectionEx("", 0)), 1, "%s.%s selects nothing" % (obj, sub))
        Gui.Selection.clearSelection()

    def checkAPartRowIsRefused(self, command):
        """SQ12: with Fillet (Chamfer) open, a Parts-list row click is refused (Onshape: silently).
        The field keeps its entry and stays armed, nothing is selected, and an edge click still
        adds."""
        a, b, padA, padB = self.twoParts()
        self.assertRowsSelectable(a, b, padB)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", b)
        edge = verticalEdge(padB, 30, 10)
        Gui.Selection.clearSelection()
        self.click(padB, edge)
        self.watchModals()
        Gui.runCommand(command)
        self.waitForPanel()
        typeId = "PartDesign::" + command.split("_", 1)[1]
        [dressUp] = self.made(typeId)
        pump(0.3)
        self.assertEqual(base(dressUp), (padB, [edge]), command)
        [field] = fields()
        self.assertTrue(field.property("armed"), command + ": the field is not armed")
        for obj, sub in self.partRowPicks(a, b, padB):
            Gui.Selection.addSelection(self.doc.Name, obj, sub)
            pump(0.2)
            self.assertEqual(base(dressUp), (padB, [edge]), "%s: %s.%s changed Base" % (command, obj, sub))
            self.assertEqual(Gui.Selection.getSelectionEx("", 0), [], "%s: %s.%s is selected" % (command, obj, sub))
            self.assertTrue(field.property("armed"), "%s: %s.%s disarmed the field" % (command, obj, sub))
        other = verticalEdge(padB, 20, 0)
        self.click(padB, other)
        pump(0.3)
        self.assertEqual(sorted(base(dressUp)[1]), sorted([edge, other]), command)
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.modals, [])

    def testAPartRowIsRefusedInAnOpenFillet(self):
        self.checkAPartRowIsRefused("PartDesign_Fillet")

    def testAPartRowIsRefusedInAnOpenChamfer(self):
        self.checkAPartRowIsRefused("PartDesign_Chamfer")

    def testAPartRowDoesNotPlaceAToolFirstFillet(self):
        """SQ12: Fillet with nothing selected waits for its first pick; a Parts-list row click is
        refused (the fillet stays where it waits, Base empty), and an edge click of B places it."""
        a, b, padA, padB = self.twoParts()
        self.assertRowsSelectable(a, b, padB)
        fillet = self.toolFirst("PartDesign_Fillet", a)
        for obj, sub in self.partRowPicks(a, b, padB):
            Gui.Selection.addSelection(self.doc.Name, obj, sub)
            pump(0.2)
            self.assertTrue(a.hasObject(fillet), "%s.%s moved the fillet" % (obj, sub))
            self.assertEqual(base(fillet)[1], [], "%s.%s entered Base" % (obj, sub))
            self.assertEqual(Gui.Selection.getSelectionEx("", 0), [], "%s.%s is selected" % (obj, sub))
        edge = verticalEdge(padB, 30, 10)
        self.click(padB, edge)
        self.placedIn(fillet, b)
        self.assertEqual(base(fillet), (padB, [edge]))
        self.close(ok=False)
        self.watching = False
        self.assertNoTrace(a, b, padA, padB)

    # -- a vertex click takes its adjacent edge nearest the click (selection parity P6b, SQ13)

    @staticmethod
    def vertexAt(feature, x, y, z):
        for index, vertex in enumerate(feature.Shape.Vertexes, start=1):
            if vertex.Point.distanceToPoint(App.Vector(x, y, z)) < 1e-6:
                return "Vertex%d" % index
        raise AssertionError("no vertex at (%g, %g, %g)" % (x, y, z))

    @staticmethod
    def edgeThrough(feature, p, q):
        """The straight edge from p to q (either way)."""
        p, q = App.Vector(*p), App.Vector(*q)
        for index, edge in enumerate(feature.Shape.Edges, start=1):
            ends = [v.Point for v in edge.Vertexes]
            if len(ends) == 2 and {
                (round(e.x, 6), round(e.y, 6), round(e.z, 6)) for e in ends
            } == {(round(p.x, 6), round(p.y, 6), round(p.z, 6)), (round(q.x, 6), round(q.y, 6), round(q.z, 6))}:
                return "Edge%d" % index
        raise AssertionError("no edge %s-%s" % (p, q))

    def clickVertex(self, feature, vertex, at):
        """A click on the vertex at the point `at` (as the 3D view gives it)."""
        body = feature.getParentGeoFeatureGroup()
        Gui.Selection.addSelection(self.doc.Name, body.Name, feature.Name + "." + vertex, *at)

    def testAVertexClickInAnOpenFilletAddsTheNearestEdge(self):
        """SQ13: B's corner (30, 0, 10) clicked just below it, just left of it and just behind
        it adds the vertical, the front top and the right top edge in turn; the same click again
        takes its edge out. Fillet r1 on the four edges: B loses the three edges' rounds, less the
        corner's overlap (checked only as a valid solid smaller than 1000)."""
        a, b, padA, padB = self.twoParts()
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", b)
        first = verticalEdge(padB, 30, 10)
        Gui.Selection.clearSelection()
        self.click(padB, first)
        self.watchModals()
        Gui.runCommand("PartDesign_Fillet")
        self.waitForPanel()
        [fillet] = self.made("PartDesign::Fillet")
        pump(0.3)
        corner = self.vertexAt(padB, 30, 0, 10)
        vertical = verticalEdge(padB, 30, 0)
        front = self.edgeThrough(padB, (20, 0, 10), (30, 0, 10))
        right = self.edgeThrough(padB, (30, 0, 10), (30, 10, 10))
        expected = [first]
        for at, edge in (((30, 0, 9.6), vertical), ((29.6, 0, 10), front), ((30, 0.4, 10), right)):
            self.clickVertex(padB, corner, at)
            pump(0.3)
            expected.append(edge)
            self.assertEqual(sorted(base(fillet)[1]), sorted(expected), "click at %s" % (at,))
            self.assertEqual(Gui.Selection.getSelectionEx("", 0), [])
        self.clickVertex(padB, corner, (29.6, 0, 10))
        pump(0.3)
        expected.remove(front)
        self.assertEqual(sorted(base(fillet)[1]), sorted(expected), "the second click kept the front edge")
        self.setField("filletRadius", 1)
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(sorted(base(fillet)[1]), sorted(expected))
        self.assertLess(fillet.Shape.Volume, 1000 - filletLoss(1, 2) + 1e-6)

    def testAVertexAsTheFirstPickPlacesTheFilletWithTheNearestEdge(self):
        """SQ13 with the tool-first flow: A active, Fillet with nothing selected; a click on B's
        corner (30, 0, 10) just below it puts the fillet in B on the vertical edge at (30, 0)."""
        a, b, padA, padB = self.twoParts()
        fillet = self.toolFirst("PartDesign_Fillet", a)
        self.clickVertex(padB, self.vertexAt(padB, 30, 0, 10), (30, 0, 9.6))
        self.placedIn(fillet, b)
        self.assertEqual(base(fillet), (padB, [verticalEdge(padB, 30, 0)]))
        self.close(ok=False)
        self.watching = False
        self.assertNoTrace(a, b, padA, padB)
