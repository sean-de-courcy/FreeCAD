# SPDX-License-Identifier: LGPL-2.1-or-later
"""Studio picks (FreeCAD-CH ops#640 rank 14, from ops#634 slices 3 and 4): a datum, a Pipe, a
Hole and the dress-ups take another part's geometry inside one part studio, with no Body to
activate first, as Onshape's features take any part's entities. Designed geometry. Off screen:
QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestCrossBodyGui import ResultBoxGuiCase
from PartDesignTests.TestExpressionFieldsGui import pump, waitFor
from PartDesignTests.TestStudio import faceAt

V = App.Vector


def positions(hole):
    """The hole's Profile, its empty names left out."""
    obj, subs = hole.Profile
    return obj, [s for s in subs if s]


class TestStudioPicksGui(ResultBoxGuiCase):
    """A datum, a Pipe and a Hole take another part's picks directly inside one part studio
    (ops#634 slice 3, notes/direct-references-design.md 2), as Onshape's Plane, Sweep and Hole
    take any part's entity: OK asks no copy question and the link is the pick itself. Across two
    App::Parts (two part studios) the datum and the Pipe still ask, and the Hole refuses the
    pick. Designed geometry: Body This and Body Sibling at the origin, at the document's top level
    (one studio) or each in its own App::Part (apart)."""

    def setUp(self):
        super().setUp()
        self.modals = []
        self.answering = False

    def tearDown(self):
        self.answering = False
        guiDoc = Gui.getDocument(self.doc.Name)
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        super().tearDown()

    def twoBodies(self, apart):
        this = self.doc.addObject("PartDesign::Body", "This")
        sibling = self.doc.addObject("PartDesign::Body", "Sibling")
        if apart:
            for name, body in (("ThisPart", this), ("SiblingPart", sibling)):
                self.doc.addObject("App::Part", name).addObject(body)
        return this, sibling

    def answerModals(self, choice="radioIndependent"):
        """Until self.answering is False: answers the copy dialog (DlgReference) with `choice` and
        closes any message box; records each in self.modals."""
        self.answering = True

        def poll():
            if not self.answering:
                return
            widget = QtWidgets.QApplication.activeModalWidget()
            if widget is not None:
                radio = widget.findChild(QtWidgets.QRadioButton, choice)
                if radio is not None:
                    self.modals.append("DlgReference")
                    radio.setChecked(True)
                    widget.accept()
                elif isinstance(widget, QtWidgets.QMessageBox):
                    self.modals.append("QMessageBox: " + widget.text())
                    widget.accept()
            QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)

    def edit(self, obj):
        self.doc.openTransaction("Edit " + obj.Name)
        Gui.getDocument(self.doc.Name).setEdit(obj.Name)
        self.waitForPanel()

    def okAnswered(self, obj):
        """OK on obj's panel, the copy dialog answered Make independent copy."""
        self.edit(obj)
        self.answerModals()
        self.close(ok=True)
        self.answering = False

    def copies(self):
        return [o.Name for o in self.doc.Objects if o.Name.startswith(("Copy", "Reference"))]

    # -- D1: a datum plane on another part's face ------------------------------------------------

    def datumOnASiblingsTop(self, apart):
        """A datum plane in This on the top face (z = 5) of a 20 x 10 x 5 pad in Sibling, then OK
        answered; returns the datum and the pad's top."""
        this, sibling = self.twoBodies(apart)
        self.body = this
        sk = models.sketch(self.doc, "SiblingSk", models.rectangle(0, 0, 20, 10), sibling)
        sibPad = models.pad(sibling, sk, 5)
        self.doc.recompute()
        top = faceAt(sibPad, 5)
        datum = this.newObject("PartDesign::Plane", "Datum")
        datum.AttachmentSupport = [(sibPad, top)]
        datum.MapMode = "FlatFace"
        self.doc.recompute()
        self.assertTrue(datum.isValid(), datum.getStatusString())
        self.okAnswered(datum)
        self.doc.recompute()
        self.assertTrue(datum.isValid(), datum.getStatusString())
        placement = datum.getGlobalPlacement()
        self.assertAlmostEqual(abs(placement.Rotation.multVec(V(0, 0, 1)).z), 1, places=6)
        self.assertAlmostEqual(placement.Base.z, 5, places=6)
        return datum, sibPad, top

    def testDatumOnASiblingsFaceLinksDirectly(self):
        """D1: one studio: OK asks nothing, and the datum is on the sibling's face itself; no copy
        is made."""
        datum, sibPad, top = self.datumOnASiblingsTop(apart=False)
        self.assertEqual(self.modals, [])
        self.assertEqual(datum.AttachmentSupport, [(sibPad, (top,))])
        self.assertEqual(self.copies(), [])

    def testDatumOnAFaceInAnotherPartAsks(self):
        """D1, two App::Parts: OK asks the copy question, as before; the datum goes on the copy,
        in This."""
        datum, sibPad, _ = self.datumOnASiblingsTop(apart=True)
        self.assertEqual(self.modals, ["DlgReference"])
        [(copy, _)] = datum.AttachmentSupport
        self.assertIsNot(copy, sibPad)
        self.assertTrue(self.body.hasObject(copy))

    # -- D2: a Pipe along another part's sketch ----------------------------------------------------

    def pipeAlongASiblingsSketch(self, apart):
        """A Pipe in This: a 2 x 2 square at z = 0 swept along a 10 mm line along Z in a sketch of
        Sibling (on XZ), then OK answered; returns the pipe and the sibling's sketch. V = 40."""
        this, sibling = self.twoBodies(apart)
        self.body = this
        profile = models.sketch(self.doc, "Profile", models.rectangle(-1, -1, 1, 1), this)
        xz = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))  # sketch y -> global z
        line = Part.LineSegment(V(0, 0, 0), V(0, 10, 0))
        spine = models.sketch(self.doc, "SiblingSpine", [line], sibling, placement=xz)
        self.doc.recompute()
        pipe = this.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (spine, ["Edge1"])
        self.doc.recompute()
        self.okAnswered(pipe)
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 40, places=3)
        return pipe, spine

    def testPipeAlongASiblingsSketchLinksDirectly(self):
        """D2: one studio: OK asks nothing, and the spine is the sibling's sketch itself; no copy
        is made."""
        pipe, spine = self.pipeAlongASiblingsSketch(apart=False)
        self.assertEqual(self.modals, [])
        self.assertEqual(pipe.Spine, (spine, ["Edge1"]))
        self.assertEqual(self.copies(), [])

    def testPipeAlongASketchInAnotherPartAsks(self):
        """D2, two App::Parts: OK asks the copy question, as before; the spine is the copy, in
        This."""
        pipe, spine = self.pipeAlongASiblingsSketch(apart=True)
        self.assertEqual(self.modals, ["DlgReference"])
        self.assertIsNot(pipe.Spine[0], spine)
        self.assertTrue(self.body.hasObject(pipe.Spine[0]))

    # -- D4: Hole positions on another part's sketch -----------------------------------------------

    def plateAndASiblingsCircle(self, apart):
        """In This a 20 x 20 x 10 box and a hole through all, diameter 2, on its own sketch's
        circle r = 1 at (5, 5) on the top; in Sibling a sketch on the top with a circle r = 1 at
        (15, 5). Each hole removes 10 pi. Returns the hole, the box and the sibling's sketch, with
        the hole's panel open and its positions field armed."""
        this, sibling = self.twoBodies(apart)
        self.body = this
        box = this.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        box.Height = 10
        own = models.sketch(self.doc, "Holes", [models.circle(5, 5, 1)], this, z=10)
        other = models.sketch(self.doc, "SiblingHoles", [models.circle(15, 5, 1)], sibling, z=10)
        self.doc.recompute()
        hole = this.newObject("PartDesign::Hole", "Hole")
        hole.Profile = (own, [])
        hole.Diameter = 2
        hole.DepthType = "ThroughAll"
        hole.BaseProfileType = 6
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        self.edit(hole)
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        field = Gui.getMainWindow().findChild(QtWidgets.QWidget, "fieldProfile")
        self.assertIsNotNone(field, "no positions field")
        field.setProperty("armed", True)
        pump(0.1)
        self.assertTrue(waitFor(lambda: bool(field.property("armed"))), "the field isn't armed")
        return hole, box, other

    def removedAt(self, hole, box):
        """The volume the hole removes from the box, and whether it drills at (5, 5) and at
        (15, 5)."""
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        drilled = [
            not hole.Shape.isInside(V(x, 5, 5), 1e-6, True) for x in (5, 15)
        ]
        return box.Shape.Volume - hole.Shape.Volume, drilled

    def testHoleOnASiblingsSketchLinksDirectly(self):
        """D4: one studio: the sibling's circle is taken as the positions (the pick starts the
        list on its sketch), and OK keeps it: the hole drills at (15, 5) alone, 10 pi."""
        hole, box, other = self.plateAndASiblingsCircle(apart=False)
        Gui.Selection.addSelection(self.doc.Name, other.Name, "Edge1")
        pump(0.2)
        self.assertEqual(positions(hole), (other, ["Edge1"]))
        self.close(ok=True)
        self.assertEqual(positions(hole), (other, ["Edge1"]))
        removed, drilled = self.removedAt(hole, box)
        self.assertAlmostEqual(removed, 10 * math.pi, places=3)
        self.assertEqual(drilled, [False, True])

    def testHoleOnASketchInAnotherPartIsRefused(self):
        """D4, two App::Parts: the pick is refused, saying why, and the hole stays on its own
        circle at (5, 5). Onshape takes no sketch of another part studio either (a Derived
        feature first)."""
        from PartDesignTests.TestReferenceFieldGui import statusText

        hole, box, other = self.plateAndASiblingsCircle(apart=True)
        Gui.Selection.addSelection(self.doc.Name, other.Name, "Edge1")
        text = statusText()
        pump(0.2)
        self.assertIn("part studio", text)
        self.assertEqual(hole.Profile[0], self.doc.getObject("Holes"))
        self.close(ok=True)
        removed, drilled = self.removedAt(hole, box)
        self.assertAlmostEqual(removed, 10 * math.pi, places=3)
        self.assertEqual(drilled, [True, False])


def verticalEdge(feature, x, y):
    """The name of the feature's vertical edge at (x, y)."""
    for index, edge in enumerate(feature.Shape.Edges, start=1):
        box = edge.BoundBox
        if (
            box.XLength < 1e-6
            and box.YLength < 1e-6
            and box.ZLength > 1e-6
            and abs(box.XMin - x) < 1e-6
            and abs(box.YMin - y) < 1e-6
        ):
            return "Edge%d" % index
    raise AssertionError("no vertical edge at (%g, %g)" % (x, y))


def sideFace(feature, x):
    """The name of the feature's face in the plane X = x."""
    for index, face in enumerate(feature.Shape.Faces, start=1):
        box = face.BoundBox
        if box.XLength < 1e-6 and abs(box.XMin - x) < 1e-6:
            return "Face%d" % index
    raise AssertionError("no face at x = %g" % x)


def filletedBoxVolume(r):
    """A 10 x 10 x 10 box with one vertical edge rounded to radius r."""
    return 1000 - 10 * r * r * (1 - math.pi / 4)


class TestStudioDressUpsGui(ResultBoxGuiCase):
    """ops#640 rank 14 (ops#634 slice 4): Fillet, Chamfer, Draft and Shell take edges and faces of
    any part of the studio, the active Body or not; 'Selection is not in the active body' goes. A
    pick on two parts makes one dress-up in each part, in one transaction, the second's size
    following the first's by expression (Onshape's one Fillet rounds each owner). Designed
    geometry: Body A, a 10 x 10 x 10 pad at the origin; Body B, the same at x = 20..30; both at
    the document's top level (one studio) or each in its own App::Part."""

    def setUp(self):
        super().setUp()
        self.modals = []
        self.watching = False

    def tearDown(self):
        self.watching = False
        super().tearDown()

    def twoParts(self, apart=False):
        a = self.doc.addObject("PartDesign::Body", "A")
        b = self.doc.addObject("PartDesign::Body", "B")
        if apart:
            for name, body in (("PartA", a), ("PartB", b)):
                self.doc.addObject("App::Part", name).addObject(body)
        padA = models.pad(a, models.sketch(self.doc, "SkA", models.rectangle(0, 0, 10, 10), a), 10)
        padB = models.pad(
            b, models.sketch(self.doc, "SkB", models.rectangle(20, 0, 30, 10), b), 10, name="PadB"
        )
        self.doc.recompute()
        self.assertAlmostEqual(padA.Shape.Volume, 1000, places=6)
        self.assertAlmostEqual(padB.Shape.Volume, 1000, places=6)
        return a, b, padA, padB

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
            elif isinstance(widget, QtWidgets.QDialog):
                # the active Body question (DlgActiveBody) or another dialog: refused
                self.modals.append(type(widget).__name__ + ": " + widget.objectName())
                widget.reject()
            QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)

    def runWith(self, command, active, picks, panel=True):
        """`command` with `active` the active Body (None: none) and `picks` ((feature, sub),
        ...) selected."""
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", active)
        Gui.Selection.clearSelection()
        for feature, sub in picks:
            Gui.Selection.addSelection(self.doc.Name, feature.Name, sub)
        self.watchModals()
        Gui.runCommand(command)
        if panel:
            self.waitForPanel()
        else:
            pump(0.5)

    def made(self, typeId):
        return [o for o in self.doc.Objects if o.TypeId == typeId]

    def panelWidget(self, name, kind=QtWidgets.QWidget):
        """The open dialog's widget `name`."""
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        widget = Gui.getMainWindow().findChild(kind, name)
        self.assertIsNotNone(widget, "no field " + name)
        return widget

    def setField(self, name, value):
        """Types `value` into the open dialog's quantity field `name`, as the user would: OK
        writes the fields back over the feature (apply()), so a value set on the property from
        Python while the dialog is open would not last."""
        self.panelWidget(name).setProperty("rawValue", value)
        pump(0.2)

    def twoEdges(self, padA, padB):
        return [(padA, verticalEdge(padA, 10, 10)), (padB, verticalEdge(padB, 30, 10))]

    def testFilletOnAnotherPartsEdge(self):
        """With A active, a fillet on an edge of B goes in B, with no modal: B's pad rounded at
        r = 2, A untouched."""
        a, b, padA, padB = self.twoParts()
        self.runWith("PartDesign_Fillet", a, [(padB, verticalEdge(padB, 30, 10))])
        [fillet] = self.made("PartDesign::Fillet")
        self.assertTrue(b.hasObject(fillet))
        self.setField("filletRadius", 2)
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertAlmostEqual(fillet.Shape.Volume, filletedBoxVolume(2), places=4)
        self.assertEqual(b.Tip, fillet)
        self.assertEqual(a.Tip, padA)

    # -- P8a (ops#654, parts-design.md 10.14): in a listed studio, one studio feature --------------

    def listed(self):
        """The two parts' studio (the document's top level) with its list, as a studio command
        makes it on first use."""
        import PartDesign

        PartDesign.studioList(self.doc, True)
        self.doc.recompute()
        return PartDesign.studioList(self.doc)

    def owners(self, typeId="PartDesign::Fillet"):
        """The studio features of typeId: outside every Body."""
        return [o for o in self.made(typeId) if getattr(o, "StudioOwner", None) is None]

    def rows(self):
        field = self.panelWidget("studioPicks", QtWidgets.QListWidget)
        return [field.item(i).text() for i in range(field.count())]

    def testFilletOnEdgesOfTwoPartsRoundsEach(self):
        """P8a (10.14; Onshape O2): edges of A and of B, one Fillet command in a listed studio: one
        studio feature, one entry in the list, a Fillet step in each part reading its radius; the
        dialog lists both picks, "A: Edge.." and "B: Edge..". Both rounded at r = 2 after OK.
        Until P8a this pinned two native fillets, one per Body, the second's Radius following
        the first's by expression (the per-Body path, which unlisted documents keep)."""
        a, b, padA, padB = self.twoParts()
        lst = self.listed()
        before = len(lst.Entries)
        self.runWith("PartDesign_Fillet", a, self.twoEdges(padA, padB))
        [owner] = self.owners()
        self.assertEqual(len(lst.Entries), before + 1)
        self.assertEqual(
            self.rows(),
            ["A: " + verticalEdge(padA, 10, 10), "B: " + verticalEdge(padB, 30, 10)],
        )
        self.setField("filletRadius", 2)
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertTrue(owner.isValid(), owner.getStatusString())
        for body in (a, b):
            [step] = [o for o in body.Group if getattr(o, "StudioOwner", None) is owner]
            self.assertEqual(step.TypeId, "PartDesign::Fillet")
            self.assertAlmostEqual(step.Radius.Value, 2)
            self.assertAlmostEqual(body.Shape.Volume, filletedBoxVolume(2), places=4)
            self.assertEqual(body.Tip, step)

    def testStudioFilletTakesAnotherPartsEdgeInItsDialog(self):
        """P8a (10.14, SQ13's fix): in a listed studio the fillet's edge field takes an edge of
        another part: an edge of A picked, the dialog open, then B's edge picked in the 3D view:
        the rows are A's and B's, and OK rounds both."""
        a, b, padA, padB = self.twoParts()
        self.listed()
        self.runWith("PartDesign_Fillet", a, [(padA, verticalEdge(padA, 10, 10))])
        [owner] = self.owners()
        self.assertEqual(self.rows(), ["A: " + verticalEdge(padA, 10, 10)])
        Gui.Selection.addSelection(self.doc.Name, padB.Name, verticalEdge(padB, 30, 10))
        pump(0.3)
        self.assertEqual(
            self.rows(),
            ["A: " + verticalEdge(padA, 10, 10), "B: " + verticalEdge(padB, 30, 10)],
        )
        self.setField("filletRadius", 2)
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertTrue(owner.isValid(), owner.getStatusString())
        for body in (a, b):
            self.assertAlmostEqual(body.Shape.Volume, filletedBoxVolume(2), places=4)

    def testCancelLeavesNoStudioFillet(self):
        """P8a (10.14): Cancel on the studio fillet's dialog leaves nothing: no fillet, no list
        entry, the parts' Tips as before."""
        a, b, padA, padB = self.twoParts()
        lst = self.listed()
        entries = [e.Name for e in lst.Entries]
        self.runWith("PartDesign_Fillet", a, self.twoEdges(padA, padB))
        self.assertEqual(len(self.owners()), 1)
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.made("PartDesign::Fillet"), [])
        self.assertEqual([e.Name for e in lst.Entries], entries)
        self.assertEqual((a.Tip, b.Tip), (padA, padB))
        for body in (a, b):
            self.assertAlmostEqual(body.Shape.Volume, 1000, places=4)

    def testStudioChamferOnTwoParts(self):
        """P8a (10.14): a Chamfer in a listed studio on an edge of each part: one studio feature,
        both chamfered at size 2 (a prism of 2 x 2 / 2 x 10 off each: 980)."""
        a, b, padA, padB = self.twoParts()
        self.listed()
        self.runWith("PartDesign_Chamfer", b, self.twoEdges(padA, padB))
        [owner] = self.owners("PartDesign::Chamfer")
        self.setField("chamferSize", 2)
        self.close(ok=True)
        self.watching = False
        self.doc.recompute()
        self.assertTrue(owner.isValid(), owner.getStatusString())
        for body in (a, b):
            self.assertAlmostEqual(body.Shape.Volume, 980, places=4)

    # -- the per-Body path (unlisted documents, until R0) ------------------------------------------

    def testCancelTakesEveryPartsFillet(self):
        """Cancel on the two-part fillet's dialog leaves no fillet in either part."""
        a, b, padA, padB = self.twoParts()
        self.runWith("PartDesign_Fillet", a, self.twoEdges(padA, padB))
        self.assertEqual(len(self.made("PartDesign::Fillet")), 2)
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.made("PartDesign::Fillet"), [])
        self.assertEqual((a.Tip, b.Tip), (padA, padB))

    def testChamferOnTwoPartsFollowsTheFirst(self):
        """With B active, a chamfer on an edge of each part: the first is A's (the first pick),
        the second's Size follows it. Size 2 on a 10 mm vertical edge removes a prism of
        2 x 2 / 2 x 10: 980 each."""
        a, b, padA, padB = self.twoParts()
        self.runWith("PartDesign_Chamfer", b, self.twoEdges(padA, padB))
        chamfers = self.made("PartDesign::Chamfer")
        self.assertEqual(len(chamfers), 2)
        [first] = [c for c in chamfers if a.hasObject(c)]
        [second] = [c for c in chamfers if b.hasObject(c)]
        expressions = dict(second.ExpressionEngine)
        for name in ("ChamferType", "Size", "Size2", "Angle", "FlipDirection"):
            self.assertEqual(expressions.get(name), first.Name + "." + name)
        self.setField("chamferSize", 2)
        self.close(ok=True)
        self.watching = False
        self.doc.recompute()
        for chamfer in (first, second):
            self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
            self.assertAlmostEqual(chamfer.Shape.Volume, 980, places=4)

    def testFilletAcrossTwoStudiosIsRefused(self):
        """A and B each in its own App::Part (two studios): the pick is refused with a message,
        as Onshape needs a Derived feature; no fillet is made."""
        a, b, padA, padB = self.twoParts(apart=True)
        self.runWith("PartDesign_Fillet", a, self.twoEdges(padA, padB), panel=False)
        self.watching = False
        self.assertEqual(len(self.modals), 1, self.modals)
        self.assertIn("one part studio", self.modals[0])
        self.assertEqual(self.made("PartDesign::Fillet"), [])

    def testDraftTakesOnePart(self):
        """Faces of A and of B, one Draft command: one Draft, in A; B's face is left out (a
        Draft's neutral plane and pull direction are its part's)."""
        a, b, padA, padB = self.twoParts()
        sideA, sideB = sideFace(padA, 10), sideFace(padB, 30)
        self.runWith("PartDesign_Draft", b, [(padA, sideA), (padB, sideB)])
        [draft] = self.made("PartDesign::Draft")
        self.assertTrue(a.hasObject(draft))
        self.assertEqual(list(draft.Base[1]), [sideA])
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.modals, [])

    def testShellOnFacesOfTwoPartsShellsEach(self):
        """The top face of A and of B, one Shell command: a Thickness in each Body, the second's
        Value following the first's. Thickness 1 inwards, the top open: 10 x 10 x 10 less
        8 x 8 x 9 = 424 each."""
        a, b, padA, padB = self.twoParts()
        self.runWith(
            "PartDesign_Thickness", a, [(padA, faceAt(padA, 10)), (padB, faceAt(padB, 10))]
        )
        shells = self.made("PartDesign::Thickness")
        self.assertEqual(len(shells), 2)
        [first] = [t for t in shells if a.hasObject(t)]
        [second] = [t for t in shells if b.hasObject(t)]
        expressions = dict(second.ExpressionEngine)
        for name in ("Value", "Reversed", "Mode", "Join", "Intersection"):
            self.assertEqual(expressions.get(name), first.Name + "." + name)
        self.setField("Value", 1)
        self.close(ok=True)
        self.watching = False
        self.doc.recompute()
        for shell in (first, second):
            self.assertTrue(shell.isValid(), shell.getStatusString())
            self.assertAlmostEqual(shell.Shape.Volume, 1000 - 8 * 8 * 9, places=3)

    def testShellReversedInTheDialogTurnsEveryPartsShell(self):
        """The two-part shell, Reversed ticked in the first part's dialog: both shells grow
        outwards (the setting is the feature's, as in Onshape), so each wall is larger than the
        inward 424 and the two are equal."""
        a, b, padA, padB = self.twoParts()
        self.runWith(
            "PartDesign_Thickness", a, [(padA, faceAt(padA, 10)), (padB, faceAt(padB, 10))]
        )
        [first] = [t for t in self.made("PartDesign::Thickness") if a.hasObject(t)]
        [second] = [t for t in self.made("PartDesign::Thickness") if b.hasObject(t)]
        self.setField("Value", 1)
        reverse = self.panelWidget("checkReverse", QtWidgets.QCheckBox)
        reverse.setChecked(not reverse.isChecked())
        pump(0.2)
        self.close(ok=True)
        self.watching = False
        self.doc.recompute()
        self.assertEqual(second.Reversed, first.Reversed)
        for shell in (first, second):
            self.assertTrue(shell.isValid(), shell.getStatusString())
            self.assertGreater(shell.Shape.Volume, 1000 - 8 * 8 * 9 + 1)
        self.assertAlmostEqual(first.Shape.Volume, second.Shape.Volume, places=3)

    def testDatumPlaneWithNoBodyActive(self):
        """No Body active, B's top face selected: Plane makes the datum in B, on that face, with
        no question for an active Body."""
        a, b, padA, padB = self.twoParts()
        self.runWith("PartDesign_Plane", None, [(padB, faceAt(padB, 10))])
        [datum] = self.made("PartDesign::Plane")
        self.assertTrue(b.hasObject(datum))
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertAlmostEqual(datum.getGlobalPlacement().Base.z, 10, places=6)

    def testDatumWithABodyPickedWholeAndNoBodyActive(self):
        """No Body active, Body B picked whole (as in the tree): Plane makes the datum in B, with
        no question for an active Body."""
        a, b, padA, padB = self.twoParts()
        self.runWith("PartDesign_Plane", None, [(b, "")])
        [datum] = self.made("PartDesign::Plane")
        self.assertTrue(b.hasObject(datum))
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.modals, [])

    def testPipeWithNoBodyActiveGoesInItsProfilesPart(self):
        """No Body active, a sketch of B selected: the additive Pipe goes in B, with no question
        for an active Body; Cancel leaves no Pipe."""
        a, b, padA, padB = self.twoParts()
        profile = models.sketch(self.doc, "ProfileB", models.rectangle(24, 4, 26, 6), b, z=10)
        self.doc.recompute()
        self.runWith("PartDesign_AdditivePipe", None, [(profile, "")])
        [pipe] = self.made("PartDesign::AdditivePipe")
        self.assertTrue(b.hasObject(pipe))
        self.close(ok=False)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.assertEqual(self.made("PartDesign::AdditivePipe"), [])

    def testHoleGoesInItsSketchsPart(self):
        """A active, a sketch on B's top with a circle r = 1 at (25, 5) selected: the Hole goes in
        B and drills it through, 10 pi; A is untouched."""
        a, b, padA, padB = self.twoParts()
        holes = models.sketch(self.doc, "HolesB", [models.circle(25, 5, 1)], b, z=10)
        self.doc.recompute()
        self.runWith("PartDesign_Hole", a, [(holes, "")])
        [hole] = self.made("PartDesign::Hole")
        self.assertTrue(b.hasObject(hole))
        self.setField("Diameter", 2)
        depthType = self.panelWidget("DepthType", QtWidgets.QComboBox)
        depthType.setCurrentIndex(hole.getEnumerationsOfProperty("DepthType").index("ThroughAll"))
        pump(0.2)
        self.close(ok=True)
        self.watching = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        self.assertAlmostEqual(1000 - hole.Shape.Volume, 10 * math.pi, places=3)
        self.assertEqual(a.Tip, padA)
